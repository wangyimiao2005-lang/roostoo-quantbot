"""True frozen research-vs-streaming parity check, including schedule and next-bar timing."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_competition.live import frozen_targets
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def load_closes():
    series = {}
    for symbol in SYMS:
        f = pd.read_csv(
            ROOT / f"data/raw/{symbol}_1h_2026-01-01_2026-09-01.csv",
            index_col="timestamp",
            parse_dates=True,
        )
        f.index = pd.to_datetime(f.index, utc=True)
        series[symbol] = f.close
    return pd.DataFrame(series).dropna()


def main(sample_rebalances=60):
    closes = load_closes()

    # Independent authoritative research vector path used by the original backtest.
    ema8_ref = closes.ewm(span=8, adjust=False).mean()
    ema24_ref = closes.ewm(span=24, adjust=False).mean()
    std24_ref = closes.rolling(24).std()
    signal_ref = ((ema8_ref - ema24_ref) / std24_ref).clip(-2, 2).div(2).fillna(0.0)
    returns = closes.pct_change()
    vol48_ref = returns.rolling(48).std() * (8760 ** 0.5)
    scale_ref = (0.35 / vol48_ref.clip(lower=0.05)).clip(upper=3.0).shift(1).fillna(0.0)
    risk_ref = signal_ref * scale_ref
    target_ref = enforce_exposure_limits(risk_ref)
    policy_ref = ExecutionPolicy("Rebalance24h", rebalance_every=24).apply(target_ref)
    effective_ref = policy_ref.shift(1).fillna(0.0)

    rows = []
    max_errors = dict(ema8=0.0, ema24=0.0, std24=0.0, vol48=0.0, signal=0.0, target=0.0)
    signal_mismatch = execution_mismatch = rebalance_mismatch = 0

    # Scheduled research signals are t % 24 == 0; require warm state and a next bar.
    scheduled = [i for i in range(48, len(closes) - 1) if i % 24 == 0][:sample_rebalances]
    for i in scheduled:
        prefix = closes.iloc[: i + 1]
        signal_ts = closes.index[i]
        execution_ts = closes.index[i + 1]

        # Operational streaming path: only prefix bars are visible.
        live_target = frozen_targets(prefix)
        live_ema8 = prefix.ewm(span=8, adjust=False).mean().iloc[-1]
        live_ema24 = prefix.ewm(span=24, adjust=False).mean().iloc[-1]
        live_std24 = prefix.rolling(24).std().iloc[-1]
        live_signal = ((live_ema8 - live_ema24) / live_std24).clip(-2, 2).div(2).fillna(0.0)
        live_vol48 = prefix.pct_change().rolling(48).std().iloc[-1] * (8760 ** 0.5)

        # Research policy must actually change/hold on the same scheduled bar, and its shifted
        # effective portfolio at i+1 must equal the scheduled signal target.
        research_scheduled_target = policy_ref.iloc[i]
        research_effective = effective_ref.iloc[i + 1]
        if not np.allclose(research_scheduled_target.values, target_ref.iloc[i].values, atol=1e-12, rtol=0):
            rebalance_mismatch += 1
        if not np.allclose(research_effective.values, research_scheduled_target.values, atol=1e-12, rtol=0):
            execution_mismatch += 1

        errs = {
            "ema8": float((live_ema8 - ema8_ref.iloc[i]).abs().max()),
            "ema24": float((live_ema24 - ema24_ref.iloc[i]).abs().max()),
            "std24": float((live_std24 - std24_ref.iloc[i]).abs().max()),
            "vol48": float((live_vol48 - vol48_ref.iloc[i]).abs().max()),
            "signal": float((live_signal - signal_ref.iloc[i]).abs().max()),
            "target": float((live_target - research_scheduled_target).abs().max()),
        }
        for key, value in errs.items():
            max_errors[key] = max(max_errors[key], value)

        # Frozen schedule is explicitly 00:00 signal -> 01:00 effective execution on this dataset.
        if signal_ts.hour != 0:
            signal_mismatch += 1
        if execution_ts != signal_ts + pd.Timedelta(hours=1) or execution_ts.hour != 1:
            execution_mismatch += 1

        rows.append(
            {
                "signal_timestamp": signal_ts,
                "execution_timestamp": execution_ts,
                "max_target_error": errs["target"],
                **{f"max_{k}_error": v for k, v in errs.items() if k != "target"},
            }
        )

    out = ROOT / "results/paper"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "research_reference.csv", index=False)
    tolerance = 1e-10
    report = {
        "timestamps_compared": len(rows),
        "max_ema8_error": max_errors["ema8"],
        "max_ema24_error": max_errors["ema24"],
        "max_rolling_std_error": max_errors["std24"],
        "max_volatility_error": max_errors["vol48"],
        "max_signal_error": max_errors["signal"],
        "max_target_error": max_errors["target"],
        "signal_timestamp_mismatches": signal_mismatch,
        "execution_timestamp_mismatches": execution_mismatch,
        "rebalance_mismatches": rebalance_mismatch,
        "tolerance": tolerance,
    }
    report["pass"] = (
        report["max_target_error"] <= tolerance
        and signal_mismatch == 0
        and execution_mismatch == 0
        and rebalance_mismatch == 0
    )
    (out / "parity_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
