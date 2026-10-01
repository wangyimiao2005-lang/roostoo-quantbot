"""Forward-only, non-trading observer for the frozen Phase 4B.1 Funding rule."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .portfolio import enforce_exposure_limits, risk_scale_targets
from .strategies import MultiHorizonTrend


STATUS = "EXPERIMENTAL_SHADOW_ONLY"
LEDGER_COLUMNS = [
    "timestamp", "symbol", "baseline_target", "funding_shadow_target", "funding_value",
    "funding_threshold_low", "funding_threshold_high", "filter_active", "baseline_trade",
    "shadow_trade", "baseline_turnover", "shadow_turnover", "baseline_fee", "shadow_fee",
    "baseline_return", "shadow_return", "baseline_equity", "shadow_equity", "incremental_equity",
]


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_funding_shadow_manifest(manifest_path: Path | None = None) -> dict:
    """Load the immutable configuration and reject any post-freeze edit."""
    manifest_path = manifest_path or _root() / "frozen" / "funding_shadow" / "FUNDING_SHADOW_FREEZE_MANIFEST.json"
    hash_path = manifest_path.with_suffix(".sha256")
    expected = hash_path.read_text().split()[0]
    actual = _digest(manifest_path)
    if actual != expected:
        raise RuntimeError("Funding shadow freeze hash mismatch; refusing to observe")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != STATUS:
        raise RuntimeError("Funding shadow is not marked EXPERIMENTAL_SHADOW_ONLY")
    if manifest.get("real_order_routing") is not False:
        raise RuntimeError("Funding shadow manifest must prohibit real order routing")
    return manifest


def phase4b1_baseline_targets(closes: pd.DataFrame) -> pd.Series:
    """Exact Phase 4B.1 Trend 8/24 target before the Funding mask."""
    if len(closes) < 48:
        raise ValueError("insufficient closed-bar warmup")
    raw = MultiHorizonTrend(8, 24).target_weights(closes)
    return enforce_exposure_limits(risk_scale_targets(raw, closes.pct_change(fill_method=None))).fillna(0.0).iloc[-1]


def causal_funding_mean(funding: pd.DataFrame, signal_timestamp, hours: int = 72) -> pd.Series:
    """Use only funding state published at or before the completed signal bar."""
    signal_timestamp = _utc(signal_timestamp)
    history = funding.copy()
    history.index = pd.to_datetime(history.index, utc=True)
    history = history.loc[history.index <= signal_timestamp]
    if len(history) < hours:
        return pd.Series(np.nan, index=funding.columns, dtype=float)
    return history.rolling(hours, min_periods=hours).mean().iloc[-1]


def funding_shadow_targets(baseline: pd.Series, funding72: pd.Series, low: float, high: float) -> tuple[pd.Series, pd.Series]:
    """Exact direction-aware Funding-only Phase 4B.1 filter."""
    blocked = ((baseline > 0) & (funding72 > high)) | ((baseline < 0) & (funding72 < low))
    target = baseline.where(~blocked, 0.0).fillna(0.0)
    return target, blocked.fillna(False)


class FundingShadowRuntime:
    """Append-only observer. It deliberately has no broker or order-submission API."""

    def __init__(self, state_path: Path | str | None = None, ledger_path: Path | str | None = None,
                 summary_path: Path | str | None = None, manifest_path: Path | str | None = None,
                 audit_rebuild: bool = False):
        root = _root()
        self.manifest_path = Path(manifest_path) if manifest_path else root / "frozen/funding_shadow/FUNDING_SHADOW_FREEZE_MANIFEST.json"
        self.manifest = load_funding_shadow_manifest(self.manifest_path)
        self.symbols = list(self.manifest["universe"])
        self.state_path = Path(state_path) if state_path else root / "state/funding_shadow_state.json"
        self.ledger_path = Path(ledger_path) if ledger_path else root / "results/funding_shadow/FUNDING_SHADOW_LEDGER.csv"
        self.summary_path = Path(summary_path) if summary_path else root / "results/funding_shadow/FUNDING_SHADOW_SUMMARY.md"
        self.fourteen_day_path = self.summary_path.parent / "FUNDING_SHADOW_14D_COMPARISON.csv"
        if audit_rebuild:
            # This is the sole explicit history-rewrite path, and is never the default.
            for path in (self.state_path, self.ledger_path):
                if path.exists():
                    path.unlink()
        self.state = self._load_state()
        self._append_ledger([])  # Create the append-only schema before first activation.
        self._save_state()
        self.write_summary()

    def _initial_state(self) -> dict:
        zero = {symbol: 0.0 for symbol in self.symbols}
        return {
            "status": STATUS, "armed_timestamp": None, "first_activation_timestamp": None, "last_processed_timestamp": None,
            "baseline_equity": 1.0, "funding_shadow_equity": 1.0, "baseline_peak_equity": 1.0,
            "funding_shadow_peak_equity": 1.0, "baseline_max_drawdown": 0.0,
            "funding_shadow_max_drawdown": 0.0, "baseline_targets": zero, "funding_shadow_targets": zero,
            "baseline_turnover": 0.0, "funding_shadow_turnover": 0.0, "baseline_fees": 0.0,
            "funding_shadow_fees": 0.0, "suppressed_positions": 0,
            "baseline_contribution": zero.copy(), "funding_shadow_contribution": zero.copy(), "trades": [],
        }

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return self._initial_state()
        state = json.loads(self.state_path.read_text())
        if state.get("status") != STATUS:
            raise RuntimeError("invalid funding shadow state")
        return state

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, self.state_path)

    def _append_ledger(self, rows: list[dict]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.ledger_path.exists()
        with self.ledger_path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerows(rows)

    def data_access_allowed(self, completed_timestamp) -> bool:
        """Return whether shadow-only data may be accessed without breaking the sealed holdout."""
        gate = self.manifest.get("forward_only", {}).get("data_access_not_before")
        return gate is None or _utc(completed_timestamp) >= _utc(gate)

    def execution_allowed(self, execution_timestamp) -> bool:
        """The first scored bar must start after the sealed holdout release signal bar."""
        gate = self.manifest.get("forward_only", {}).get("first_execution_not_before")
        return gate is None or _utc(execution_timestamp) >= _utc(gate)

    def catch_up_completed(self, opens: pd.DataFrame, closes: pd.DataFrame, funding: pd.DataFrame) -> str:
        """Settle every newly completed hourly bar since the prior invocation.

        The first invocation only *arms* the observer at the latest completed bar;
        it never backfills historical PnL.  Later invocations may settle several
        completed hours at once, which keeps the shadow ledger correct even when
        the production runner itself is only launched around the daily rebalance.
        """
        opens = opens.copy()
        closes = closes.copy()
        funding = funding.copy()
        for frame, name in ((opens, "opens"), (closes, "closes"), (funding, "funding")):
            frame.index = pd.to_datetime(frame.index, utc=True)
            missing = set(self.symbols).difference(frame.columns)
            if missing:
                raise ValueError(f"{name} missing symbols: {sorted(missing)}")
        common = opens.index.intersection(closes.index)
        if common.empty:
            raise ValueError("no completed bars available for funding shadow")
        latest = common.max()
        if not self.data_access_allowed(latest):
            return "SEALED_HOLDOUT_LOCKED"

        previous = self.state.get("last_processed_timestamp")
        if previous is None:
            # Forward-only activation: history up to the current completed bar is
            # warmup context, not shadow performance.
            self.state["armed_timestamp"] = latest.isoformat()
            self.state["last_processed_timestamp"] = latest.isoformat()
            self._save_state()
            self.write_summary()
            return "ARMED_FORWARD_ONLY"

        previous = _utc(previous)
        if latest <= previous:
            return "ALREADY_CAUGHT_UP"

        expected = pd.date_range(previous + pd.Timedelta(hours=1), latest, freq="h", tz="UTC")
        missing_open = expected.difference(opens.index)
        missing_close = expected.difference(closes.index)
        missing_funding = expected.difference(funding.index)
        if len(missing_open) or len(missing_close) or len(missing_funding):
            raise ValueError(
                "funding shadow catch-up gap: "
                f"opens={len(missing_open)} closes={len(missing_close)} funding={len(missing_funding)}"
            )

        recorded = 0
        for execution_ts in expected:
            if not self.execution_allowed(execution_ts):
                # This can only occur at the release boundary.  Advancing the
                # cursor without scoring prevents later retroactive backfill.
                self.state["last_processed_timestamp"] = execution_ts.isoformat()
                continue
            status = self.observe(execution_ts, opens, closes, funding)
            if status == "RECORDED":
                recorded += 1
        self._save_state()
        self.write_summary()
        return f"CAUGHT_UP_{recorded}"

    def observe(self, timestamp, opens: pd.DataFrame, closes: pd.DataFrame, funding: pd.DataFrame) -> str:
        """Record the next-bar result at ``timestamp`` without mutating any live target.

        The target held for an execution bar is calculated from data ending one hour
        earlier.  Calling again for an already observed timestamp never changes the
        state or ledger.
        """
        execution_ts = _utc(timestamp)
        if not self.execution_allowed(execution_ts):
            return "SEALED_HOLDOUT_LOCKED"
        previous = self.state["last_processed_timestamp"]
        if previous is not None and execution_ts <= _utc(previous):
            return "ALREADY_PROCESSED"
        signal_ts = execution_ts - pd.Timedelta(hours=1)
        for frame, name in ((opens, "opens"), (closes, "closes"), (funding, "funding")):
            frame.index = pd.to_datetime(frame.index, utc=True)
            missing = set(self.symbols).difference(frame.columns)
            if missing:
                raise ValueError(f"{name} missing symbols: {sorted(missing)}")
        if execution_ts not in opens.index or execution_ts not in closes.index:
            raise ValueError("execution bar is unavailable")
        closed = closes.loc[closes.index <= signal_ts, self.symbols]
        if signal_ts not in closed.index:
            raise ValueError("completed signal bar is unavailable")

        old_base = pd.Series(self.state["baseline_targets"], dtype=float).reindex(self.symbols).fillna(0.0)
        old_shadow = pd.Series(self.state["funding_shadow_targets"], dtype=float).reindex(self.symbols).fillna(0.0)
        base_target, shadow_target = old_base, old_shadow
        funding_value = causal_funding_mean(funding[self.symbols], signal_ts, int(self.manifest["funding_feature"]["hours"]))
        blocked = pd.Series(False, index=self.symbols)
        # The exact frozen schedule: completed 00:00 signal, effective at 01:00.
        if signal_ts.hour == 0:
            base_target = phase4b1_baseline_targets(closed)
            shadow_target, blocked = funding_shadow_targets(
                base_target, funding_value,
                float(self.manifest["funding_thresholds"]["low"]),
                float(self.manifest["funding_thresholds"]["high"]),
            )
        base_trade = base_target - old_base
        shadow_trade = shadow_target - old_shadow
        base_turnover, shadow_turnover = base_trade.abs(), shadow_trade.abs()
        cost_rate = float(self.manifest["cost_assumptions"]["primary_cost_bps_per_side"]) / 10000.0
        base_fee, shadow_fee = base_turnover * cost_rate, shadow_turnover * cost_rate
        intrabar = closes.loc[execution_ts, self.symbols].div(opens.loc[execution_ts, self.symbols]).sub(1).replace([np.inf, -np.inf], 0).fillna(0.0)
        base_return = base_target * intrabar - base_fee
        shadow_return = shadow_target * intrabar - shadow_fee
        self.state["baseline_equity"] *= 1.0 + float(base_return.sum())
        self.state["funding_shadow_equity"] *= 1.0 + float(shadow_return.sum())
        self.state["baseline_peak_equity"] = max(self.state["baseline_peak_equity"], self.state["baseline_equity"])
        self.state["funding_shadow_peak_equity"] = max(self.state["funding_shadow_peak_equity"], self.state["funding_shadow_equity"])
        self.state["baseline_max_drawdown"] = min(self.state["baseline_max_drawdown"], self.state["baseline_equity"] / self.state["baseline_peak_equity"] - 1)
        self.state["funding_shadow_max_drawdown"] = min(self.state["funding_shadow_max_drawdown"], self.state["funding_shadow_equity"] / self.state["funding_shadow_peak_equity"] - 1)
        rows = []
        for symbol in self.symbols:
            self.state["baseline_contribution"][symbol] += float(base_return[symbol])
            self.state["funding_shadow_contribution"][symbol] += float(shadow_return[symbol])
            rows.append({
                "timestamp": execution_ts.isoformat(), "symbol": symbol,
                "baseline_target": base_target[symbol], "funding_shadow_target": shadow_target[symbol],
                "funding_value": funding_value[symbol], "funding_threshold_low": self.manifest["funding_thresholds"]["low"],
                "funding_threshold_high": self.manifest["funding_thresholds"]["high"], "filter_active": bool(blocked[symbol]),
                "baseline_trade": base_trade[symbol], "shadow_trade": shadow_trade[symbol],
                "baseline_turnover": base_turnover[symbol], "shadow_turnover": shadow_turnover[symbol],
                "baseline_fee": base_fee[symbol], "shadow_fee": shadow_fee[symbol],
                "baseline_return": base_return[symbol], "shadow_return": shadow_return[symbol],
                "baseline_equity": self.state["baseline_equity"], "shadow_equity": self.state["funding_shadow_equity"],
                "incremental_equity": self.state["funding_shadow_equity"] - self.state["baseline_equity"],
            })
        self.state["first_activation_timestamp"] = self.state["first_activation_timestamp"] or execution_ts.isoformat()
        self.state["last_processed_timestamp"] = execution_ts.isoformat()
        self.state["baseline_targets"] = {k: float(v) for k, v in base_target.items()}
        self.state["funding_shadow_targets"] = {k: float(v) for k, v in shadow_target.items()}
        self.state["baseline_turnover"] += float(base_turnover.sum())
        self.state["funding_shadow_turnover"] += float(shadow_turnover.sum())
        self.state["baseline_fees"] += float(base_fee.sum())
        self.state["funding_shadow_fees"] += float(shadow_fee.sum())
        self.state["suppressed_positions"] += int(blocked.sum())
        self.state["trades"].append({"timestamp": execution_ts.isoformat(), "baseline": base_trade.to_dict(), "funding_shadow": shadow_trade.to_dict()})
        self._append_ledger(rows)
        self._save_state()
        self.write_summary()
        return "RECORDED"

    def write_summary(self) -> None:
        count = len(self.state["trades"])
        bret = self.state["baseline_equity"] - 1.0
        sret = self.state["funding_shadow_equity"] - 1.0
        lines = [
            "# Funding Shadow Summary", "", f"Status: `{STATUS}` — no real or paper-portfolio orders are routed.",
            f"Start date: {self.state['first_activation_timestamp'] or 'not activated'}", f"Elapsed observations: {count}",
            f"Baseline cumulative net return: {bret:.2%}", f"Funding-shadow cumulative net return: {sret:.2%}",
            f"Incremental return: {(self.state['funding_shadow_equity'] / self.state['baseline_equity'] - 1):.2%}",
            f"Baseline turnover: {self.state['baseline_turnover']:.6f}", f"Funding turnover: {self.state['funding_shadow_turnover']:.6f}",
            f"Baseline fees: {self.state['baseline_fees']:.6f}", f"Funding fees: {self.state['funding_shadow_fees']:.6f}",
            f"Funding filter suppressed Trend positions: {self.state['suppressed_positions']}",
            f"Baseline maximum drawdown: {self.state['baseline_max_drawdown']:.2%}", f"Funding-shadow maximum drawdown: {self.state['funding_shadow_max_drawdown']:.2%}",
            "", "## Per-asset net contribution", "", "| Asset | Baseline | Funding shadow |", "|---|---:|---:|",
        ]
        lines.extend(f"| {s} | {self.state['baseline_contribution'][s]:.4%} | {self.state['funding_shadow_contribution'][s]:.4%} |" for s in self.symbols)
        comparison_columns = ["end_timestamp", "funding_shadow_14d_return", "baseline_14d_return", "incremental_14d_return", "funding_beat_baseline"]
        comparison = pd.DataFrame(columns=comparison_columns)
        if count >= 14 * 24:
            ledger = pd.read_csv(self.ledger_path, parse_dates=["timestamp"])
            hourly = ledger.groupby("timestamp")[["baseline_return", "shadow_return"]].sum().sort_index()
            rows = []
            for end in range(14 * 24 - 1, len(hourly)):
                window = hourly.iloc[end - 14 * 24 + 1:end + 1]
                baseline_14d = float((1 + window.baseline_return).prod() - 1)
                shadow_14d = float((1 + window.shadow_return).prod() - 1)
                rows.append({"end_timestamp": window.index[-1], "funding_shadow_14d_return": shadow_14d,
                             "baseline_14d_return": baseline_14d,
                             "incremental_14d_return": (1 + shadow_14d) / (1 + baseline_14d) - 1,
                             "funding_beat_baseline": shadow_14d > baseline_14d})
            comparison = pd.DataFrame(rows, columns=comparison_columns)
            latest = comparison.iloc[-1]
            lines.extend([
                "", "## Rolling 14-day evaluation", "",
                f"Funding-shadow 14d return: {latest.funding_shadow_14d_return:.2%}",
                f"Baseline 14d return: {latest.baseline_14d_return:.2%}",
                f"Incremental 14d return: {latest.incremental_14d_return:.2%}",
                f"Funding beat Baseline: {latest.funding_beat_baseline}",
                "These observations do not alter the frozen shadow configuration.",
            ])
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        comparison.to_csv(self.fourteen_day_path, index=False)
        self.summary_path.write_text("\n".join(lines) + "\n")
