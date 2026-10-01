"""One-shot final pre-competition selector: frozen Trend 8/24 vs frozen Funding filter.

The Sep22-Oct3 holdout is inaccessible before 2026-10-04 00:00 UTC.  After
release this script evaluates exactly the preregistered rules and writes one
immutable ACTIVE_STRATEGY artifact.  It does not tune anything.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/final_precompetition_gate"
START = pd.Timestamp("2026-09-22T00:00:00Z")
END = pd.Timestamp("2026-10-04T00:00:00Z")
RELEASE = datetime(2026, 10, 4, tzinfo=timezone.utc)
WARMUP_FUNDING_START = pd.Timestamp("2026-09-16T00:00:00Z")
DEV_START = "2025-01-01"

from quant_competition.backtest import run_backtest
from quant_competition.competition_selection import (
    BASELINE, FUNDING, active_strategy_path, load_gate_manifest,
)
from quant_competition.funding_provider import BinanceUSDMFundingProvider
from quant_competition.funding_shadow import funding_shadow_targets
from quant_competition.live import frozen_target_frame
from quant_competition.metrics.drawdown import drawdown
from quant_competition.portfolio import ExecutionPolicy
from run_baseline_b1 import fetch_public_binance, panel, read_or_fetch


def sealed_message() -> str:
    return (
        "FINAL PRE-COMPETITION GATE SEALED.\n"
        "Release: 2026-10-04T00:00:00Z\n"
        "Scored holdout: 2026-09-22T00:00:00Z through 2026-10-03T23:00:00Z.\n"
        "No holdout market/funding data may be loaded before release."
    )


def preflight(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now < RELEASE:
        raise RuntimeError(sealed_message())
    gate = load_gate_manifest()
    if gate["release_time"] != "2026-10-04T00:00:00Z":
        raise RuntimeError("gate release date mismatch")
    if gate["official_holdout"] != {
        "start": "2026-09-22T00:00:00Z",
        "end_exclusive": "2026-10-04T00:00:00Z",
    }:
        raise RuntimeError("gate holdout dates mismatch")
    if gate["decision"] != {"if_all_rules_pass": FUNDING, "otherwise": BASELINE}:
        raise RuntimeError("gate decision rule has changed")
    for relative, expected in gate.get("source_hashes", {}).items():
        path = ROOT / relative
        if not path.exists() or _digest(path) != expected:
            raise RuntimeError(f"frozen gate source hash mismatch: {relative}")
    return gate


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gap_cache_path(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    stamp = lambda x: x.strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "data/final_precompetition_gate" / f"{symbol}_1h_{stamp(start)}_{stamp(end)}.csv"


def _missing_ranges(missing: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if len(missing) == 0:
        return []
    missing = pd.DatetimeIndex(missing).sort_values()
    step = pd.Timedelta(hours=1)
    out = []
    start = prev = missing[0]
    for ts in missing[1:]:
        if ts != prev + step:
            out.append((start, prev + step))
            start = ts
        prev = ts
    out.append((start, prev + step))
    return out


def load_complete_history(symbol: str, start: str, end: str,
                          cached_loader=read_or_fetch, gap_fetcher=fetch_public_binance) -> pd.DataFrame:
    """Load complete spot OHLCV; network gaps are fetched only after preflight."""
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    expected = pd.date_range(start_ts, end_ts, freq="h", inclusive="left")
    frame = cached_loader(symbol, start, end).copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[(frame.index >= start_ts) & (frame.index < end_ts)]
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
    for a, b in _missing_ranges(expected.difference(frame.index)):
        fetched = gap_fetcher(symbol, a.isoformat(), b.isoformat()).copy()
        fetched.index = pd.to_datetime(fetched.index, utc=True)
        fetched = fetched[(fetched.index >= a) & (fetched.index < b)]
        fetched = fetched.loc[~fetched.index.duplicated(keep="last")].sort_index()
        if len(fetched):
            path = _gap_cache_path(symbol, a, b)
            path.parent.mkdir(parents=True, exist_ok=True)
            fetched.to_csv(path, index_label="timestamp")
            frame = pd.concat([frame, fetched]).loc[lambda x: ~x.index.duplicated(keep="last")].sort_index()
    missing = expected.difference(frame.index)
    if len(missing):
        raise RuntimeError(f"{symbol}: {len(missing)} hourly OHLCV bars missing from requested history")
    return frame.reindex(expected)


def funding_hourly(provider: BinanceUSDMFundingProvider, symbols: list[str], cutoff: pd.Timestamp) -> pd.DataFrame:
    """Build causal hourly funding state with enough warmup for the 72h feature."""
    hourly = pd.date_range(WARMUP_FUNDING_START, cutoff.floor("h"), freq="h", tz="UTC")
    out = pd.DataFrame(index=hourly, columns=symbols, dtype=float)
    for symbol in symbols:
        events = provider.events(symbol, WARMUP_FUNDING_START - pd.Timedelta(days=3), cutoff)
        if events.empty:
            raise RuntimeError(f"no final-holdout funding events for {symbol}")
        union = hourly.union(events.index)
        causal = events["funding_rate"].reindex(union).sort_index().ffill().reindex(hourly)
        if causal.loc[:START].tail(72).isna().any():
            raise RuntimeError(f"insufficient funding warmup for {symbol}")
        out[symbol] = causal
    return out


def target_frames(closes: pd.DataFrame, funding: pd.DataFrame, gate: dict) -> dict[str, pd.DataFrame]:
    baseline = frozen_target_frame(closes).fillna(0.0)
    fmean = funding.rolling(int(gate["funding_challenger"]["feature_hours"]), min_periods=int(gate["funding_challenger"]["feature_hours"])).mean()
    fmean = fmean.reindex(closes.index)
    low = float(gate["funding_challenger"]["funding_low"])
    high = float(gate["funding_challenger"]["funding_high"])
    blocked = ((baseline > 0) & (fmean > high)) | ((baseline < 0) & (fmean < low))
    # Missing warmup funding never suppresses a baseline position.
    candidate = baseline.where(~blocked.fillna(False), 0.0).fillna(0.0)
    return {BASELINE: baseline, FUNDING: candidate}


def run_strategy(opens: pd.DataFrame, closes: pd.DataFrame, target: pd.DataFrame, cost_bps: float):
    return run_backtest(opens, closes, target, cost_bps,
                        execution_policy=ExecutionPolicy("Rebalance24h", rebalance_every=24))


def _part(result, index: pd.DatetimeIndex):
    return type("Partial", (), {
        "returns": result.returns.loc[index],
        "gross_returns": result.gross_returns.loc[index],
        "costs": result.costs.loc[index],
        "turnover": result.turnover.loc[index],
        "weights": result.weights.loc[index],
        "trades": result.trades[result.trades.timestamp.isin(index)],
    })()


def metric_row(name: str, result) -> dict:
    net = float((1 + result.returns).prod() - 1)
    gross = float((1 + result.gross_returns).prod() - 1)
    dd = float(drawdown(result.returns).min()) if len(result.returns) else np.nan
    return {
        "strategy": name,
        "gross_return": gross,
        "net_return": net,
        "max_drawdown": dd,
        "turnover": float(result.turnover.sum()),
        "fees": float(result.costs.sum()),
        "trade_count": int(len(result.trades)),
    }


def leave_one_asset_out(opens: pd.DataFrame, closes: pd.DataFrame, targets: dict[str, pd.DataFrame], index: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for asset in targets[BASELINE].columns:
        results = {}
        for name, target in targets.items():
            altered = target.copy()
            altered[asset] = 0.0
            results[name] = _part(run_strategy(opens, closes, altered, 10), index)
        b = float((1 + results[BASELINE].returns).prod() - 1)
        f = float((1 + results[FUNDING].returns).prod() - 1)
        rows.append({
            "excluded_asset": asset,
            "baseline_net_return": b,
            "funding_net_return": f,
            "funding_beats_baseline": bool(f > b),
            "incremental_return": (1 + f) / (1 + b) - 1,
        })
    return pd.DataFrame(rows)


def incremental_rebalance_blocks(baseline, funding) -> pd.DataFrame:
    z = pd.DataFrame({"baseline": baseline.returns, "funding": funding.returns})
    # Fixed UTC daily blocks match the frozen 00:00 signal / 01:00 execution cadence.
    rows = []
    for day, frame in z.groupby(z.index.floor("D")):
        b = float((1 + frame.baseline).prod() - 1)
        f = float((1 + frame.funding).prod() - 1)
        rows.append({"date": day, "baseline_return": b, "funding_return": f,
                     "incremental_return": (1 + f) / (1 + b) - 1})
    return pd.DataFrame(rows)


def gate_checks(primary_10: pd.DataFrame, primary_15: pd.DataFrame, loo: pd.DataFrame,
                blocks: pd.DataFrame, gate: dict) -> pd.DataFrame:
    a10 = primary_10.set_index("strategy").loc[BASELINE]
    f10 = primary_10.set_index("strategy").loc[FUNDING]
    a15 = primary_15.set_index("strategy").loc[BASELINE]
    f15 = primary_15.set_index("strategy").loc[FUNDING]
    rules = gate["decision_rules"]
    positive = blocks.loc[blocks.incremental_return > 0, "incremental_return"]
    concentration = float(positive.max() / positive.sum()) if len(positive) and positive.sum() > 0 else 1.0
    checks = [
        ("funding_net_return_10bps_positive", f10.net_return > 0, f10.net_return, 0.0),
        ("funding_beats_baseline_10bps", f10.net_return > a10.net_return, f10.net_return - a10.net_return, 0.0),
        ("funding_net_return_15bps_positive", f15.net_return > 0, f15.net_return, 0.0),
        ("funding_beats_baseline_15bps", f15.net_return > a15.net_return, f15.net_return - a15.net_return, 0.0),
        ("max_drawdown_not_materially_worse", abs(f10.max_drawdown) <= abs(a10.max_drawdown) + rules["max_drawdown_worsening_limit_percentage_points"] / 100.0,
         abs(f10.max_drawdown) - abs(a10.max_drawdown), rules["max_drawdown_worsening_limit_percentage_points"] / 100.0),
        ("leave_one_asset_out_majority", int(loo.funding_beats_baseline.sum()) >= int(rules["leave_one_asset_out_minimum_wins_out_of_5"]),
         int(loo.funding_beats_baseline.sum()), int(rules["leave_one_asset_out_minimum_wins_out_of_5"])),
        ("increment_not_single_block_concentrated", concentration <= float(rules["maximum_single_rebalance_block_share_of_positive_incremental_return"]),
         concentration, float(rules["maximum_single_rebalance_block_share_of_positive_incremental_return"])),
    ]
    return pd.DataFrame([{"check": n, "pass": bool(ok), "observed": obs, "threshold": threshold} for n, ok, obs, threshold in checks])


def write_active_strategy(selected: str, checks: pd.DataFrame, metrics10: pd.DataFrame, metrics15: pd.DataFrame,
                          loo: pd.DataFrame, blocks: pd.DataFrame, gate: dict) -> dict:
    path = active_strategy_path()
    if path.exists():
        # One-shot means no rewriting after the holdout is revealed.
        hash_path = path.with_suffix(".sha256")
        if not hash_path.exists() or hash_path.read_text().split()[0] != _digest(path):
            raise RuntimeError("existing ACTIVE_STRATEGY artifact failed hash verification")
        return json.loads(path.read_text())
    payload = {
        "selection_id": "competition_strategy_2026_final_v1",
        "selected_strategy": selected,
        "strategy_version": "trend824_funding_filter_v1_final" if selected == FUNDING else "trend824_v1_frozen",
        "decision_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "holdout": gate["official_holdout"],
        "gate_id": gate["gate_id"],
        "gate_manifest_sha256": _digest(ROOT / "frozen/precompetition_gate/FUNDING_VS_BASELINE_GATE.json"),
        "all_funding_rules_passed": bool(checks["pass"].all()),
        "checks": checks.to_dict(orient="records"),
        "primary_10bps": metrics10.to_dict(orient="records"),
        "stress_15bps": metrics15.to_dict(orient="records"),
        "leave_one_asset_out": loo.to_dict(orient="records"),
        "incremental_rebalance_blocks": blocks.to_dict(orient="records"),
        "immutable_after_creation": True
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    path.with_suffix(".sha256").write_text(_digest(path) + "  " + path.name + "\n")
    return payload


def report(selection: dict, m10: pd.DataFrame, m15: pd.DataFrame, checks: pd.DataFrame,
           loo: pd.DataFrame, blocks: pd.DataFrame) -> str:
    return f"""# Final Pre-Competition Gate\n\n## Holdout\n\nScored exactly once: 2026-09-22 00:00 UTC through 2026-10-03 23:00 UTC. Parameters and decision rules were hash-locked before release.\n\n## 10 bps per side\n\n{m10.to_markdown(index=False, floatfmt='.6f')}\n\n## 15 bps stress\n\n{m15.to_markdown(index=False, floatfmt='.6f')}\n\n## Gate checks\n\n{checks.to_markdown(index=False)}\n\n## Leave-one-asset-out robustness\n\n{loo.to_markdown(index=False, floatfmt='.6f')}\n\n## Daily / rebalance-block incremental returns\n\n{blocks.to_markdown(index=False, floatfmt='.6f')}\n\n## Final competition selection\n\n**{selection['selected_strategy']}**\n\nNo threshold, feature, universe, cost assumption, or gate rule was changed after holdout release.\n"""


def evaluate(frames: dict[str, pd.DataFrame], funding: pd.DataFrame, gate: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    symbols = gate["universe"]
    opens, closes, _ = panel(frames, symbols)
    expected = pd.date_range(START, END, freq="h", inclusive="left")
    if len(expected.difference(opens.index)) or opens.loc[expected].isna().any().any() or closes.loc[expected].isna().any().any():
        raise RuntimeError("final holdout OHLCV coverage is incomplete")
    targets = target_frames(closes, funding, gate)
    holdout_index = expected
    all_results = {}
    all_results15 = {}
    for name, target in targets.items():
        all_results[name] = _part(run_strategy(opens, closes, target, 10), holdout_index)
        all_results15[name] = _part(run_strategy(opens, closes, target, 15), holdout_index)
    m10 = pd.DataFrame([metric_row(name, rr) for name, rr in all_results.items()])
    m15 = pd.DataFrame([metric_row(name, rr) for name, rr in all_results15.items()])
    loo = leave_one_asset_out(opens, closes, targets, holdout_index)
    blocks = incremental_rebalance_blocks(all_results[BASELINE], all_results[FUNDING])
    checks = gate_checks(m10, m15, loo, blocks, gate)
    return m10, m15, loo, blocks, checks


def main(now: datetime | None = None, funding_provider=None) -> dict:
    gate = preflight(now)  # No market/funding access occurs before this line.
    existing = active_strategy_path()
    if existing.exists():
        hash_path = existing.with_suffix(".sha256")
        if not hash_path.exists() or hash_path.read_text().split()[0] != _digest(existing):
            raise RuntimeError("existing active strategy artifact is corrupt")
        selection = json.loads(existing.read_text())
        print(json.dumps({"status": "ALREADY_SELECTED", "selected_strategy": selection["selected_strategy"]}, indent=2))
        return selection

    symbols = gate["universe"]
    frames = {s: load_complete_history(s, DEV_START, END.isoformat()) for s in symbols}
    provider = funding_provider or BinanceUSDMFundingProvider(
        cache_dir=ROOT / "data/final_precompetition_gate/funding",
        clock=lambda: now or datetime.now(timezone.utc),
    )
    funding = funding_hourly(provider, symbols, END - pd.Timedelta(hours=1))
    m10, m15, loo, blocks, checks = evaluate(frames, funding, gate)
    selected = FUNDING if bool(checks["pass"].all()) else BASELINE
    selection = write_active_strategy(selected, checks, m10, m15, loo, blocks, gate)

    OUT.mkdir(parents=True, exist_ok=True)
    m10.to_csv(OUT / "FINAL_HOLDOUT_10BPS.csv", index=False)
    m15.to_csv(OUT / "FINAL_HOLDOUT_15BPS.csv", index=False)
    loo.to_csv(OUT / "LEAVE_ONE_ASSET_OUT.csv", index=False)
    blocks.to_csv(OUT / "INCREMENTAL_REBALANCE_BLOCKS.csv", index=False)
    checks.to_csv(OUT / "GATE_CHECKS.csv", index=False)
    (OUT / "FINAL_PRECOMPETITION_GATE_REPORT.md").write_text(report(selection, m10, m15, checks, loo, blocks))
    print(json.dumps({
        "status": "FINAL_SELECTION_LOCKED",
        "selected_strategy": selected,
        "all_funding_rules_passed": bool(checks["pass"].all()),
        "active_strategy_path": str(active_strategy_path().relative_to(ROOT)),
    }, indent=2))
    return selection


if __name__ == "__main__":
    main()
