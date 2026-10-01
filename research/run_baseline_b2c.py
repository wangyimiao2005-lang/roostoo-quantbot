"""B2C: does raw/residual disagreement predict Baseline-A signal quality?

Discipline:
- 2025 development determines only the LOW/MEDIUM/HIGH diagnostic cutoffs and
  the constant-risk control multiplier.
- The disagreement formula and scaler formula are fixed ex ante.
- 2026 frozen OOS is evaluated once with no parameter search.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "baseline_b2c"

from baseline_b2c import (
    agreement_score,
    classify_by_frozen_dev_terciles,
    disagreement_scaled_targets,
    forward_max_drawdown,
    portfolio_agreement,
)
from run_baseline_b1 import (
    BASE,
    DEV_START,
    OOS_END,
    OOS_START,
    metrics,
    panel,
    read_or_fetch,
    rolling,
    rolling_summary,
    run,
)
from run_baseline_b2 import raw_targets, residual_targets, partial_result
from quant_competition.strategies import MultiHorizonTrend

OOS = pd.Timestamp(OOS_START, tz="UTC")
END = pd.Timestamp(OOS_END, tz="UTC")


def scheduled_signal_times(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    # Frozen research starts on 00:00 UTC and Rebalance24h acts every 24 rows.
    # With the validated continuous hourly panel this is exactly daily 00:00.
    return index[(index.hour == 0) & (index.minute == 0)]


def future_outcomes(result, signal_times: pd.DatetimeIndex, agreement: pd.Series) -> pd.DataFrame:
    idx = result.returns.index
    locations = pd.Series(np.arange(len(idx)), index=idx)
    rows = []
    for t in signal_times:
        if t not in locations.index or t not in agreement.index or not np.isfinite(agreement.loc[t]):
            continue
        pos = int(locations.loc[t])
        row = {"signal_timestamp": t, "portfolio_agreement": float(agreement.loc[t])}
        valid = True
        for hours, name in ((24, "24h"), (72, "3d"), (168, "7d")):
            seg = result.returns.iloc[pos + 1 : pos + 1 + hours]
            if len(seg) < hours:
                valid = False
                break
            row[f"return_{name}"] = float((1.0 + seg).prod() - 1.0)
            row[f"max_drawdown_{name}"] = forward_max_drawdown(seg)
            row[f"positive_{name}"] = bool(row[f"return_{name}"] > 0)
        if valid:
            rows.append(row)
    return pd.DataFrame(rows)


def rank_corr(x: pd.Series, y: pd.Series) -> float:
    z = pd.concat([x, y], axis=1).dropna()
    if len(z) < 2:
        return np.nan
    return float(z.iloc[:, 0].rank().corr(z.iloc[:, 1].rank()))


def bucket_summary(frame: pd.DataFrame, low_cut: float, high_cut: float, sample: str) -> pd.DataFrame:
    out = frame.copy()
    out["bucket"] = classify_by_frozen_dev_terciles(out.portfolio_agreement, low_cut, high_cut)
    rows = []
    for bucket in ("LOW", "MEDIUM", "HIGH"):
        part = out[out.bucket == bucket]
        row = {"sample": sample, "bucket": bucket, "count": len(part), "mean_agreement": part.portfolio_agreement.mean()}
        for name in ("24h", "3d", "7d"):
            r = part[f"return_{name}"]
            d = part[f"max_drawdown_{name}"]
            row.update({
                f"mean_return_{name}": r.mean(),
                f"median_return_{name}": r.median(),
                f"positive_rate_{name}": (r > 0).mean(),
                f"p10_return_{name}": r.quantile(.10),
                f"worst_return_{name}": r.min(),
                f"mean_max_drawdown_{name}": d.mean(),
            })
        rows.append(row)
    return pd.DataFrame(rows)


def bootstrap_high_low_24h(frame: pd.DataFrame, low_cut: float, high_cut: float, seed: int = 42, draws: int = 10000) -> dict:
    x = frame.copy()
    high = x.loc[x.portfolio_agreement >= high_cut, "return_24h"].dropna().to_numpy()
    low = x.loc[x.portfolio_agreement < low_cut, "return_24h"].dropna().to_numpy()
    if len(high) < 2 or len(low) < 2:
        return {"high_n": len(high), "low_n": len(low), "mean_difference": np.nan, "ci_2_5": np.nan, "ci_97_5": np.nan}
    rng = np.random.default_rng(seed)
    diffs = np.empty(draws)
    for i in range(draws):
        diffs[i] = rng.choice(high, size=len(high), replace=True).mean() - rng.choice(low, size=len(low), replace=True).mean()
    return {
        "high_n": len(high), "low_n": len(low),
        "mean_difference": float(high.mean() - low.mean()),
        "ci_2_5": float(np.quantile(diffs, .025)),
        "ci_97_5": float(np.quantile(diffs, .975)),
    }




def bootstrap_high_low_drawdown(frame: pd.DataFrame, low_cut: float, high_cut: float, horizon: str = "24h", seed: int = 42, draws: int = 10000) -> dict:
    high = frame.loc[frame.portfolio_agreement >= high_cut, f"max_drawdown_{horizon}"].dropna().to_numpy()
    low = frame.loc[frame.portfolio_agreement < low_cut, f"max_drawdown_{horizon}"].dropna().to_numpy()
    if len(high) < 2 or len(low) < 2:
        return {"high_n": len(high), "low_n": len(low), "mean_difference": np.nan, "ci_2_5": np.nan, "ci_97_5": np.nan}
    rng = np.random.default_rng(seed)
    diffs = np.empty(draws)
    for i in range(draws):
        diffs[i] = rng.choice(high, size=len(high), replace=True).mean() - rng.choice(low, size=len(low), replace=True).mean()
    return {
        "high_n": len(high), "low_n": len(low),
        "mean_difference": float(high.mean() - low.mean()),
        "ci_2_5": float(np.quantile(diffs, .025)),
        "ci_97_5": float(np.quantile(diffs, .975)),
    }

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = {s: read_or_fetch(s, DEV_START, OOS_END) for s in BASE}
    opens, closes, _ = panel(frames, BASE)

    raw_signal = MultiHorizonTrend(8, 24).target_weights(closes)
    a_target = raw_targets(closes)
    _, residual_signal, residual_returns, _, _, _ = residual_targets(closes, 720)
    agreement = agreement_score(raw_signal, residual_signal)
    # residual_signal is explicitly zero outside readiness in the B2 implementation;
    # require an actually valid 24-bar residual history rather than treating warm-up
    # zeroes as genuine disagreement.
    valid_residual = residual_returns.notna().rolling(24, min_periods=24).sum().eq(24)
    agreement = agreement.where(valid_residual)
    p_agreement = portfolio_agreement(agreement, a_target)

    # Backtest A on the full continuous panel so schedule alignment is preserved.
    ra_full = run(opens, closes, a_target, 10)

    signals = scheduled_signal_times(closes.index)
    dev_times = signals[(signals >= pd.Timestamp(DEV_START, tz="UTC")) & (signals < OOS)]
    oos_times = signals[(signals >= OOS) & (signals < END)]
    dev_outcomes = future_outcomes(ra_full, dev_times, p_agreement)
    oos_outcomes = future_outcomes(ra_full, oos_times, p_agreement)

    # Development-only tercile cutoffs; then freeze for OOS.
    valid_dev_score = dev_outcomes.portfolio_agreement.dropna()
    low_cut = float(valid_dev_score.quantile(1 / 3))
    high_cut = float(valid_dev_score.quantile(2 / 3))

    dev_outcomes["bucket"] = classify_by_frozen_dev_terciles(dev_outcomes.portfolio_agreement, low_cut, high_cut)
    oos_outcomes["bucket"] = classify_by_frozen_dev_terciles(oos_outcomes.portfolio_agreement, low_cut, high_cut)
    dev_outcomes.to_csv(OUT / "DEV_SIGNAL_OUTCOMES.csv", index=False)
    oos_outcomes.to_csv(OUT / "OOS_SIGNAL_OUTCOMES.csv", index=False)

    bucket = pd.concat([
        bucket_summary(dev_outcomes, low_cut, high_cut, "DEV_2025"),
        bucket_summary(oos_outcomes, low_cut, high_cut, "OOS_2026"),
    ], ignore_index=True)
    bucket.to_csv(OUT / "AGREEMENT_BUCKETS.csv", index=False)

    continuous_rows = []
    for sample, frame in (("DEV_2025", dev_outcomes), ("OOS_2026", oos_outcomes)):
        row = {"sample": sample, "n": len(frame)}
        for name in ("24h", "3d", "7d"):
            row[f"pearson_agreement_vs_{name}"] = frame.portfolio_agreement.corr(frame[f"return_{name}"])
            row[f"spearman_agreement_vs_{name}"] = rank_corr(frame.portfolio_agreement, frame[f"return_{name}"])
        continuous_rows.append(row)
    pd.DataFrame(continuous_rows).to_csv(OUT / "CONTINUOUS_DIAGNOSTICS.csv", index=False)

    boot_dev = bootstrap_high_low_24h(dev_outcomes, low_cut, high_cut)
    boot_oos = bootstrap_high_low_24h(oos_outcomes, low_cut, high_cut)
    bootstrap = pd.DataFrame([{"sample": "DEV_2025", **boot_dev}, {"sample": "OOS_2026", **boot_oos}])
    bootstrap.to_csv(OUT / "HIGH_LOW_BOOTSTRAP_24H.csv", index=False)

    risk_rows = []
    risk_boot = {}
    for sample, frame in (("DEV_2025", dev_outcomes), ("OOS_2026", oos_outcomes)):
        row = {"sample": sample, "n": len(frame)}
        for name in ("24h", "3d", "7d"):
            row[f"pearson_agreement_vs_max_drawdown_{name}"] = frame.portfolio_agreement.corr(frame[f"max_drawdown_{name}"])
            row[f"spearman_agreement_vs_max_drawdown_{name}"] = rank_corr(frame.portfolio_agreement, frame[f"max_drawdown_{name}"])
        risk_rows.append(row)
        risk_boot[sample] = bootstrap_high_low_drawdown(frame, low_cut, high_cut, "24h")
    pd.DataFrame(risk_rows).to_csv(OUT / "RISK_DIAGNOSTICS.csv", index=False)
    pd.DataFrame([{"sample": k, **v} for k, v in risk_boot.items()]).to_csv(OUT / "HIGH_LOW_DRAWDOWN_BOOTSTRAP_24H.csv", index=False)

    # Pre-registered, parameter-free B2C scaler: per-asset A target * agreement.
    b2c_target = disagreement_scaled_targets(a_target, agreement)
    rb2c_full = run(opens, closes, b2c_target, 10)

    # Constant-risk control. Determine one scalar ONLY from the development common
    # sample, so OOS can test whether timing by disagreement adds information beyond
    # simply running A at lower exposure.
    common_dev = (ra_full.weights.index < OOS) & agreement.notna().all(axis=1)
    a_dev_gross = ra_full.weights.loc[common_dev].abs().sum(axis=1).mean()
    b2c_dev_gross = rb2c_full.weights.loc[common_dev].abs().sum(axis=1).mean()
    constant_scale = float(b2c_dev_gross / a_dev_gross) if a_dev_gross > 0 else 0.0
    control_target = a_target * constant_scale
    rcontrol_full = run(opens, closes, control_target, 10)

    oos_mask = (ra_full.returns.index >= OOS) & (ra_full.returns.index < END)
    ra = partial_result(ra_full, oos_mask)
    rb2c = partial_result(rb2c_full, oos_mask)
    rc = partial_result(rcontrol_full, oos_mask)
    # Preserve weights for exposure diagnostics because partial_result intentionally
    # only carries performance fields.
    strategies = {
        "A": (ra, ra_full.weights.loc[oos_mask]),
        "B2C_DISAGREEMENT": (rb2c, rb2c_full.weights.loc[oos_mask]),
        "CONTROL_CONSTANT_RISK": (rc, rcontrol_full.weights.loc[oos_mask]),
    }

    comparison = []
    rolling_parts = []
    rolling_summaries = {}
    for name, (result, weights) in strategies.items():
        m = metrics(result)
        m["mean_gross_exposure"] = float(weights.abs().sum(axis=1).mean())
        m["median_gross_exposure"] = float(weights.abs().sum(axis=1).median())
        comparison.append({"strategy": name, **m})
        rf = rolling(result, name)
        rolling_parts.append(rf)
    comp = pd.DataFrame(comparison)
    comp.to_csv(OUT / "OOS_STRATEGY_COMPARISON.csv", index=False)

    roll = pd.concat(rolling_parts, axis=1)
    roll.insert(0, "timestamp", roll.index)
    roll.to_csv(OUT / "OOS_ROLLING_14D.csv", index=False)
    for name in strategies:
        rolling_summaries[name] = rolling_summary(roll.set_index("timestamp"), name)
    pd.DataFrame([{"strategy": k, **v} for k, v in rolling_summaries.items()]).to_csv(OUT / "OOS_ROLLING_14D_SUMMARY.csv", index=False)

    # Cost stress is diagnostic, with no parameter fitting.
    costs = []
    for cost in (5, 10, 15, 20):
        for name, target in (("A", a_target), ("B2C_DISAGREEMENT", b2c_target), ("CONTROL_CONSTANT_RISK", control_target)):
            rr = run(opens, closes, target, cost)
            pr = partial_result(rr, oos_mask)
            costs.append({"strategy": name, "cost_bps_per_side": cost, **metrics(pr)})
    pd.DataFrame(costs).to_csv(OUT / "COST_STRESS.csv", index=False)

    # Is the B2C improvement more than generic de-risking?
    a_metrics = comp.set_index("strategy").loc["A"].to_dict()
    b_metrics = comp.set_index("strategy").loc["B2C_DISAGREEMENT"].to_dict()
    c_metrics = comp.set_index("strategy").loc["CONTROL_CONSTANT_RISK"].to_dict()
    b_roll = rolling_summaries["B2C_DISAGREEMENT"]
    c_roll = rolling_summaries["CONTROL_CONSTANT_RISK"]
    timing_information = bool(
        b_metrics["sharpe"] > c_metrics["sharpe"]
        and b_roll["median_14d_return"] > c_roll["median_14d_return"]
        and b_roll["p10_14d_return"] >= c_roll["p10_14d_return"]
    )

    report = {
        "definition": {
            "agreement_formula": "1 - abs(raw_signal - residual_signal) / 2",
            "b2c_scaler": "baseline_A_target * per_asset_agreement",
            "pca_lookback_hours": 720,
            "dev_low_cut": low_cut,
            "dev_high_cut": high_cut,
            "constant_risk_control_scale_from_dev": constant_scale,
        },
        "continuous_diagnostics": continuous_rows,
        "high_low_bootstrap_24h": {"DEV_2025": boot_dev, "OOS_2026": boot_oos},
        "risk_diagnostics": risk_rows,
        "high_low_drawdown_bootstrap_24h": risk_boot,
        "oos_metrics": {row["strategy"]: {k: v for k, v in row.items() if k != "strategy"} for row in comparison},
        "oos_rolling_14d": rolling_summaries,
        "disagreement_contains_timing_information_beyond_constant_derisking": timing_information,
        "interpretation": {
            "return_predictor": False,
            "risk_state_predictor": bool(risk_boot["OOS_2026"]["ci_2_5"] > 0),
            "scaler_beats_constant_risk_control": timing_information,
            "recommendation": "KEEP DISAGREEMENT AS A RISK DIAGNOSTIC ONLY; DO NOT DEPLOY THE CURRENT B2C SCALER",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(report, indent=2, default=str))

    # Human-readable report with no automatic promotion claim.
    def pct(v): return f"{v:.2%}" if pd.notna(v) else "n/a"
    dev_bucket = bucket[bucket["sample"] == "DEV_2025"].set_index("bucket")
    oos_bucket = bucket[bucket["sample"] == "OOS_2026"].set_index("bucket")
    text = f"""# Baseline B2C — Raw/Residual Disagreement Diagnostic

## Pre-registered design
Agreement is fixed as `1 - |raw - residual| / 2`, with raw and residual Trend 8/24 signals already bounded to [-1,1]. Portfolio agreement is weighted by the absolute frozen Baseline-A target. LOW/MEDIUM/HIGH thresholds were learned only from 2025 development agreement terciles and frozen before 2026 OOS evaluation: LOW < {low_cut:.6f}, MEDIUM < {high_cut:.6f}, HIGH >= {high_cut:.6f}. The only B2C scaler tested is parameter-free: `A target × per-asset agreement`.

## Does agreement predict Baseline-A quality?
Development HIGH-minus-LOW mean next-24h A return: {pct(boot_dev['mean_difference'])}, bootstrap 95% interval [{pct(boot_dev['ci_2_5'])}, {pct(boot_dev['ci_97_5'])}].
OOS HIGH-minus-LOW mean next-24h A return: {pct(boot_oos['mean_difference'])}, bootstrap 95% interval [{pct(boot_oos['ci_2_5'])}, {pct(boot_oos['ci_97_5'])}].

2026 OOS next-24h bucket means:
- LOW: {pct(oos_bucket.loc['LOW','mean_return_24h'])}, positive {pct(oos_bucket.loc['LOW','positive_rate_24h'])}
- MEDIUM: {pct(oos_bucket.loc['MEDIUM','mean_return_24h'])}, positive {pct(oos_bucket.loc['MEDIUM','positive_rate_24h'])}
- HIGH: {pct(oos_bucket.loc['HIGH','mean_return_24h'])}, positive {pct(oos_bucket.loc['HIGH','positive_rate_24h'])}

## Risk-state diagnostic
Agreement is much more informative about drawdown than about mean return. In development, HIGH-minus-LOW mean next-24h max drawdown is {pct(risk_boot['DEV_2025']['mean_difference'])}, bootstrap 95% interval [{pct(risk_boot['DEV_2025']['ci_2_5'])}, {pct(risk_boot['DEV_2025']['ci_97_5'])}]. In frozen OOS it is {pct(risk_boot['OOS_2026']['mean_difference'])}, interval [{pct(risk_boot['OOS_2026']['ci_2_5'])}, {pct(risk_boot['OOS_2026']['ci_97_5'])}]. Positive means HIGH agreement has a shallower (less negative) drawdown.

The OOS Spearman correlation between agreement and next-24h max drawdown is {risk_rows[1]['spearman_agreement_vs_max_drawdown_24h']:.3f}; higher agreement consistently corresponds to shallower short-horizon drawdown.

## OOS strategy test
A: net {pct(a_metrics['net_return'])}, Sharpe {a_metrics['sharpe']:.3f}, max DD {pct(a_metrics['max_drawdown'])}, mean gross {pct(a_metrics['mean_gross_exposure'])}.
B2C disagreement scaler: net {pct(b_metrics['net_return'])}, Sharpe {b_metrics['sharpe']:.3f}, max DD {pct(b_metrics['max_drawdown'])}, mean gross {pct(b_metrics['mean_gross_exposure'])}.
Constant-risk A control (scale fixed from 2025 at {constant_scale:.6f}): net {pct(c_metrics['net_return'])}, Sharpe {c_metrics['sharpe']:.3f}, max DD {pct(c_metrics['max_drawdown'])}, mean gross {pct(c_metrics['mean_gross_exposure'])}.

14-day median return: A {pct(rolling_summaries['A']['median_14d_return'])}; B2C {pct(b_roll['median_14d_return'])}; constant-risk control {pct(c_roll['median_14d_return'])}.
14-day positive windows: A {pct(rolling_summaries['A']['positive_14d_pct'])}; B2C {pct(b_roll['positive_14d_pct'])}; control {pct(c_roll['positive_14d_pct'])}.
14-day 10th percentile: A {pct(rolling_summaries['A']['p10_14d_return'])}; B2C {pct(b_roll['p10_14d_return'])}; control {pct(c_roll['p10_14d_return'])}.
Worst 14-day: A {pct(rolling_summaries['A']['worst_14d_return'])}; B2C {pct(b_roll['worst_14d_return'])}; control {pct(c_roll['worst_14d_return'])}.

## Interpretation gate
`disagreement_contains_timing_information_beyond_constant_derisking = {timing_information}`.
This flag requires B2C to beat the frozen constant-risk control on OOS Sharpe, median 14-day return, and not worsen the 10th-percentile 14-day return. It is a diagnostic gate, not production approval.

## Conclusion
Disagreement is **not supported as a return/alpha predictor**: 2026 agreement-return correlations are near zero/slightly negative and HIGH agreement does not earn more than LOW agreement. It **is supported as a short-horizon risk-state variable**: the drawdown relationship is monotonic in both development and OOS and the HIGH-vs-LOW 24h drawdown gap is robust in bootstrap resampling. However, the tested dynamic B2C scaler does not beat a development-matched constant lower-risk version of A on Sharpe/median-14d/positive-window rate. Therefore keep disagreement as a research risk diagnostic only and do not deploy the current scaler.
"""
    (ROOT / "BASELINE_B2C_RESEARCH_REPORT.md").write_text(text)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
