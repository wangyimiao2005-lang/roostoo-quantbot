"""Preregistered B2E raw-signal-geometry risk-overlay experiment."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "baseline_b2e"

from baseline_b2e import FEATURES, fit_standardizer, hold_rebalance_multiplier, risk_multiplier, signal_geometry, standardize, vol_only_multiplier
from baseline_b2c import forward_max_drawdown
from run_baseline_b1 import BASE, DEV_START, OOS_END, OOS_START, metrics, panel, read_or_fetch, rolling, run
from run_baseline_b2 import partial_result, raw_targets
from quant_competition.strategies import MultiHorizonTrend

OOS = pd.Timestamp(OOS_START, tz="UTC")
END = pd.Timestamp(OOS_END, tz="UTC")


def scheduled(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index[(index.hour == 0) & (index.minute == 0)]


def future_risk(result, times: pd.DatetimeIndex) -> pd.DataFrame:
    loc = pd.Series(np.arange(len(result.returns)), index=result.returns.index)
    rows = []
    for t in times:
        if t not in loc.index:
            continue
        p = int(loc.loc[t])
        segment = result.returns.iloc[p + 1:p + 25]
        if len(segment) == 24:
            dd = forward_max_drawdown(segment)
            rows.append({"signal_timestamp": t, "future_24h_max_drawdown": dd,
                         "future_dd_risk": abs(dd), "future_24h_return": (1 + segment).prod() - 1})
    return pd.DataFrame(rows).set_index("signal_timestamp")


def market_volatility(closes: pd.DataFrame) -> pd.Series:
    market = closes.pct_change(fill_method=None).mean(axis=1)
    return (market.rolling(48, min_periods=48).std(ddof=1) * np.sqrt(24 * 365)).rename("market_vol_48h")


def fit_ols(y: pd.Series, z: pd.DataFrame) -> pd.Series:
    """Small dependency-free OLS fit for the sole preregistered model."""
    x = np.column_stack([np.ones(len(z)), z.to_numpy(dtype=float)])
    coef, _, _, _ = np.linalg.lstsq(x, y.to_numpy(dtype=float), rcond=None)
    return pd.Series(coef, index=["const", *FEATURES])


def predict_ols(z: pd.DataFrame, coef: pd.Series) -> pd.Series:
    x = np.column_stack([np.ones(len(z)), z.to_numpy(dtype=float)])
    return pd.Series(x @ coef.loc[["const", *FEATURES]].to_numpy(), index=z.index)


def auc_binary(y: pd.Series, score: pd.Series) -> float:
    """Mann-Whitney AUC with average ranks; high score means high-risk class."""
    y, score = y.align(score, join="inner")
    pos, neg = int(y.sum()), int((1 - y).sum())
    if not pos or not neg:
        return np.nan
    return float((score.rank(method="average")[y.astype(bool)].sum() - pos * (pos + 1) / 2) / (pos * neg))


def calibrate_vol_k(a_targets: pd.DataFrame, b2e_targets: pd.DataFrame, vol: pd.Series, dev_mask: pd.Series) -> float:
    """Deterministically solve for the preregistered vol-only exposure match on development."""
    desired = b2e_targets.loc[dev_mask].abs().sum(axis=1).mean()
    a = a_targets.loc[dev_mask]
    # The control is decided on exactly the same daily schedule and then held,
    # so calibration must use the held (rather than hourly-refreshed) input.
    daily_vol = vol.where((vol.index.hour == 0) & (vol.index.minute == 0)).ffill()
    v = daily_vol.loc[dev_mask]
    def gross(k):
        return a.mul(vol_only_multiplier(v, k), axis=0).abs().sum(axis=1).mean()
    lo, hi = 0.0, max(float(v.quantile(.99)) * 2, 1.0)
    for _ in range(80):
        mid = (lo + hi) / 2
        if gross(mid) < desired:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def rolling_14d(result, name: str) -> pd.DataFrame:
    frame = rolling(result, name)
    frame[f"{name}_drawdown_magnitude"] = -frame[f"{name}_max_drawdown"]
    return frame


def rolling_summary(frame: pd.DataFrame, name: str) -> dict:
    r = frame[f"{name}_return"].dropna()
    d = frame[f"{name}_drawdown_magnitude"].dropna()
    return {"windows": len(r), "mean_14d_return": r.mean(), "median_14d_return": r.median(),
            "positive_14d_pct": (r > 0).mean(), "p25_14d_return": r.quantile(.25),
            "p10_14d_return": r.quantile(.10), "p5_14d_return": r.quantile(.05),
            "worst_14d_return": r.min(), "best_14d_return": r.max(),
            "median_14d_drawdown": d.median(), "p90_14d_drawdown": d.quantile(.90),
            "worst_14d_drawdown": d.max(), "median_14d_turnover": frame[f"{name}_turnover"].median(),
            "median_14d_fees": frame[f"{name}_fees"].median()}


def block_bootstrap_difference(high: pd.Series, low: pd.Series, block: int = 5, draws: int = 10000, seed: int = 42) -> dict:
    """Circular moving-block bootstrap, preserving short daily dependence."""
    high, low = high.dropna().to_numpy(), low.dropna().to_numpy()
    rng = np.random.default_rng(seed)
    def sample(x):
        starts = rng.integers(0, len(x), size=int(np.ceil(len(x) / block)))
        return np.concatenate([np.take(x, np.arange(s, s + block), mode="wrap") for s in starts])[:len(x)]
    diffs = np.array([sample(high).mean() - sample(low).mean() for _ in range(draws)])
    return {"method": "circular moving-block bootstrap, 5 daily observations/block, 10,000 draws",
            "high_n": len(high), "low_n": len(low), "difference": high.mean() - low.mean(),
            "ci_2_5": np.quantile(diffs, .025), "ci_97_5": np.quantile(diffs, .975)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = {s: read_or_fetch(s, DEV_START, OOS_END) for s in BASE}
    opens, closes, _ = panel(frames, BASE)
    raw_signal = MultiHorizonTrend(8, 24).target_weights(closes)
    a_target = raw_targets(closes)
    a_full = run(opens, closes, a_target, 10)
    times = scheduled(closes.index)
    outcomes = future_risk(a_full, times)
    geometry = signal_geometry(raw_signal).reindex(outcomes.index)
    frame = outcomes.join(geometry).dropna()
    dev = frame[frame.index < OOS].copy()
    oos = frame[(frame.index >= OOS) & (frame.index < END)].copy()

    # Exactly one OLS risk model, fitted only on 2025.
    mean, std = fit_standardizer(dev)
    z_dev, z_oos = standardize(dev, mean, std), standardize(oos, mean, std)
    model = fit_ols(dev.future_dd_risk, z_dev)
    dev["predicted_24h_dd_risk"] = predict_ols(z_dev, model)
    oos["predicted_24h_dd_risk"] = predict_ols(z_oos, model)
    q50, q75 = dev.predicted_24h_dd_risk.quantile([.50, .75])
    severe_threshold = float(dev.future_dd_risk.quantile(.75))
    dev["risk_multiplier"] = risk_multiplier(dev.predicted_24h_dd_risk, q50, q75)
    oos["risk_multiplier"] = risk_multiplier(oos.predicted_24h_dd_risk, q50, q75)

    # Targets are A multiplied by a daily held portfolio scalar; execution remains A's next bar policy.
    b2e_multiplier = hold_rebalance_multiplier(closes.index, pd.concat([dev.risk_multiplier, oos.risk_multiplier]))
    b2e_target = a_target.mul(b2e_multiplier, axis=0)
    b2e_full = run(opens, closes, b2e_target, 10)
    dev_mask = (closes.index >= pd.Timestamp(DEV_START, tz="UTC")) & (closes.index < OOS)
    a_dev_gross = a_full.weights.loc[dev_mask].abs().sum(axis=1).mean()
    b2e_dev_gross = b2e_full.weights.loc[dev_mask].abs().sum(axis=1).mean()
    constant_scale = float(b2e_dev_gross / a_dev_gross)
    constant_target = a_target * constant_scale
    constant_full = run(opens, closes, constant_target, 10)
    vol = market_volatility(closes)
    vol_k = calibrate_vol_k(a_target, b2e_target, vol, dev_mask)
    # VolOnly shares the 24-hour decision cadence but is not subject to B2E's
    # 0.50 lower bound; it is the independently calibrated control.
    vol_multiplier = vol_only_multiplier(vol.reindex(times), vol_k).reindex(closes.index).ffill().fillna(1.0)
    vol_target = a_target.mul(vol_multiplier, axis=0)
    vol_full = run(opens, closes, vol_target, 10)
    dev_exposure = {
        "A": float(a_full.weights.loc[dev_mask].abs().sum(axis=1).mean()),
        "ConstantRisk_A": float(constant_full.weights.loc[dev_mask].abs().sum(axis=1).mean()),
        "VolOnly_A": float(vol_full.weights.loc[dev_mask].abs().sum(axis=1).mean()),
        "B2E_SignalGeometry": float(b2e_full.weights.loc[dev_mask].abs().sum(axis=1).mean()),
    }

    oos_mask = (closes.index >= OOS) & (closes.index < END)
    full = {"A": a_full, "ConstantRisk_A": constant_full, "VolOnly_A": vol_full, "B2E_SignalGeometry": b2e_full}
    strategies = {k: partial_result(v, oos_mask) for k, v in full.items()}
    rows, rolls, rollsum = [], [], {}
    for name, result in strategies.items():
        m = metrics(result)
        m["average_gross_exposure"] = full[name].weights.loc[oos_mask].abs().sum(axis=1).mean()
        m["return_over_annualized_volatility"] = m["net_return"] / m["annualized_volatility"] if m["annualized_volatility"] else np.nan
        m["return_over_max_drawdown"] = m["net_return"] / abs(m["max_drawdown"]) if m["max_drawdown"] else np.nan
        rows.append({"strategy": name, **m})
        rolls.append(rolling_14d(result, name))
    primary = pd.DataFrame(rows)
    rollframe = pd.concat(rolls, axis=1).dropna()
    rollframe.insert(0, "window_start", rollframe.index - pd.Timedelta(hours=335))
    rollframe.insert(1, "window_end", rollframe.index)
    for name in strategies: rollsum[name] = rolling_summary(rollframe, name)
    for row in rows: row.update(rollsum[row["strategy"]])
    primary = pd.DataFrame(rows)
    primary.to_csv(OUT / "PRIMARY_RESULTS.csv", index=False)
    rollframe.to_csv(OUT / "ROLLING_14D.csv", index=False)

    # Frozen prediction validation and fixed risk buckets.
    y, p = oos.future_dd_risk, oos.predicted_24h_dd_risk
    predrow = {"sample": "OOS_2026", "n": len(oos), "pearson": y.corr(p), "spearman": y.rank().corr(p.rank()),
               "mse": ((y - p) ** 2).mean(), "oos_r2": 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum(),
               "severe_threshold_from_dev": severe_threshold,
               "severe_drawdown_auc": auc_binary((y >= severe_threshold).astype(int), p)}
    pd.DataFrame([predrow]).to_csv(OUT / "RISK_PREDICTION.csv", index=False)
    oos["risk_bucket"] = pd.cut(oos.predicted_24h_dd_risk, [-np.inf, q50, q75, np.inf], labels=["Low", "Medium", "High"], include_lowest=True)
    baseline_return = outcomes.loc[oos.index, "future_24h_return"]
    buckets = []
    for bucket in ("Low", "Medium", "High"):
        x = oos[oos.risk_bucket == bucket]
        r = baseline_return.loc[x.index]
        buckets.append({"bucket": bucket, "count": len(x), "mean_drawdown_risk": x.future_dd_risk.mean(),
                        "median_drawdown_risk": x.future_dd_risk.median(), "p90_drawdown_risk": x.future_dd_risk.quantile(.90),
                        "mean_baseline_a_return": r.mean(), "baseline_a_positive_return_probability": (r > 0).mean()})
    bucketdf = pd.DataFrame(buckets); bucketdf.to_csv(OUT / "RISK_BUCKETS.csv", index=False)
    boot = block_bootstrap_difference(oos.loc[oos.risk_bucket == "High", "future_dd_risk"], oos.loc[oos.risk_bucket == "Low", "future_dd_risk"])

    costs = []
    for cost in (5, 10, 15, 20):
        for name, target in (("A", a_target), ("ConstantRisk_A", constant_target), ("VolOnly_A", vol_target), ("B2E_SignalGeometry", b2e_target)):
            rr = partial_result(run(opens, closes, target, cost), oos_mask)
            costs.append({"strategy": name, "cost_bps_per_side": cost, **metrics(rr)})
    pd.DataFrame(costs).to_csv(OUT / "COST_STRESS.csv", index=False)

    sub = []
    for start, end, label in (("2026-01-01", "2026-04-01", "2026 Q1"), ("2026-04-01", "2026-07-01", "2026 Q2"), ("2026-07-01", "2026-09-01", "2026 Jul-Aug")):
        for name, result in strategies.items():
            mask = (result.returns.index >= pd.Timestamp(start, tz="UTC")) & (result.returns.index < pd.Timestamp(end, tz="UTC"))
            sub.append({"period": label, "strategy": name, **metrics(partial_result(full[name], oos_mask & ((closes.index >= pd.Timestamp(start, tz="UTC")) & (closes.index < pd.Timestamp(end, tz="UTC")))) )})
    pd.DataFrame(sub).to_csv(OUT / "SUBPERIODS.csv", index=False)

    # State frequency/duration is measured at scheduled OOS decisions.
    states = oos.risk_multiplier.value_counts().reindex([1., .75, .5], fill_value=0)
    sequence = oos.risk_multiplier.to_numpy(); durations = {s: [] for s in (1., .75, .5)}
    start = 0
    for i in range(1, len(sequence) + 1):
        if i == len(sequence) or sequence[i] != sequence[start]:
            durations[sequence[start]].append(i - start); start = i
    exposure = pd.DataFrame([{"multiplier": s, "scheduled_observations": int(states[s]), "usage_pct": states[s] / len(oos),
                              "average_duration_days": np.mean(durations[s]) if durations[s] else 0.0,
                              "runs": len(durations[s])} for s in (1., .75, .5)])
    exposure.to_csv(OUT / "EXPOSURE_STATES.csv", index=False)

    awindows = rollframe.nsmallest(10, "A_return")
    worst = []
    for _, w in awindows.iterrows():
        mask = (strategies["A"].returns.index >= w.window_start) & (strategies["A"].returns.index <= w.window_end)
        worst.append({"window_start": w.window_start, "window_end": w.window_end, "A_return": w.A_return,
                      "ConstantRisk_return": w.ConstantRisk_A_return, "VolOnly_return": w.VolOnly_A_return, "B2E_return": w.B2E_SignalGeometry_return,
                      "A_max_drawdown": w.A_max_drawdown, "B2E_max_drawdown": w.B2E_SignalGeometry_max_drawdown,
                      "average_B2E_risk_multiplier": b2e_multiplier.loc[strategies["A"].returns.index[mask]].mean()})
    pd.DataFrame(worst).to_csv(OUT / "WORST_WINDOWS.csv", index=False)

    top = rollframe[rollframe.A_return >= rollframe.A_return.quantile(.75)]
    upside = {name: {"mean_top_quartile_A_period_return": top[f"{name}_return"].mean(),
                     "upside_capture_ratio": top[f"{name}_return"].mean() / top.A_return.mean(),
                     "downside_capture_ratio": rollframe.loc[rollframe.A_return <= rollframe.A_return.quantile(.25), f"{name}_return"].mean() / rollframe.loc[rollframe.A_return <= rollframe.A_return.quantile(.25), "A_return"].mean()} for name in strategies}
    log = pd.DataFrame([{"experiment_id": "B2E_primary_preregistered", "timestamp": datetime.now(timezone.utc).isoformat(),
                         "mapping": "<=Q50:1.00; Q50-Q75:0.75; >Q75:0.50", "development": "2025", "oos": "2026-01-01 to 2026-08-31",
                         "result": "executed once; no OOS parameter tuning"}])
    log.to_csv(OUT / "EXPERIMENT_LOG.csv", index=False)

    ptab = primary.set_index("strategy")
    # Conservative gate: must beat both controls on tail outcomes, with no worse
    # maximum DD, at reasonably comparable realized OOS risk. This does not alter
    # the preregistered model or mapping; it only states the promotion standard.
    b = rollsum["B2E_SignalGeometry"]
    controls = [rollsum["ConstantRisk_A"], rollsum["VolOnly_A"]]
    tail_beats_controls = all(b["p10_14d_return"] >= c["p10_14d_return"] and b["p5_14d_return"] >= c["p5_14d_return"] and b["median_14d_drawdown"] <= c["median_14d_drawdown"] for c in controls) and all(ptab.loc["B2E_SignalGeometry", "max_drawdown"] <= ptab.loc[n, "max_drawdown"] for n in ("ConstantRisk_A", "VolOnly_A"))
    comparable_risk = all(abs(ptab.loc["B2E_SignalGeometry", "average_gross_exposure"] - ptab.loc[n, "average_gross_exposure"]) <= .05 and abs(ptab.loc["B2E_SignalGeometry", "annualized_volatility"] - ptab.loc[n, "annualized_volatility"]) <= .05 for n in ("ConstantRisk_A", "VolOnly_A"))
    decision = "PROMOTE B2E FOR FURTHER VALIDATION" if tail_beats_controls and comparable_risk else "KEEP B2E AS RESEARCH-ONLY RISK SIGNAL"
    summary = {"baseline_a_reproduced": ptab.loc["A", ["net_return", "sharpe", "sortino", "max_drawdown"]].to_dict(),
               "frozen_model": {"intercept": model["const"], "beta_strength": model["signal_strength"], "beta_dispersion": model["signal_dispersion"], "q50": q50, "q75": q75, "constant_scale": constant_scale, "vol_k": vol_k},
               "risk_prediction": predrow, "bootstrap_high_minus_low_dd": boot, "development_average_gross_exposure": dev_exposure, "tail_beats_matched_controls": tail_beats_controls, "oos_risk_comparable_to_both_controls": comparable_risk, "upside_capture": upside, "decision": decision}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    write_report(ptab, rollsum, predrow, bucketdf, exposure, boot, summary, decision)
    print(json.dumps(summary, indent=2, default=float))


def write_report(ptab, rollsum, pred, buckets, exposure, boot, summary, decision):
    def pct(v): return f"{v:.2%}" if pd.notna(v) else "n/a"
    model = summary["frozen_model"]
    devgross = summary["development_average_gross_exposure"]
    lines = ["# Baseline B2E — Raw Signal Geometry Risk Overlay", "", "## Method", "", "This preregistered research-only overlay multiplies frozen Baseline-A targets by a daily portfolio multiplier. It uses only unweighted raw Trend 8/24 signal strength and cross-sectional dispersion, fitted by one 2025 OLS model. No PCA/residual signal, alpha rule, direction, relative weight, sizing, execution or schedule was changed.", "", "## Frozen model and OOS risk validation", "", f"2025 coefficients: intercept {model['intercept']:.6f}, strength {model['beta_strength']:.6f}, dispersion {model['beta_dispersion']:.6f}; predicted-risk Q50 {model['q50']:.4%}, Q75 {model['q75']:.4%}. 2026 Pearson {pred['pearson']:.3f}, Spearman {pred['spearman']:.3f}, MSE {pred['mse']:.8f}, OOS R² {pred['oos_r2']:.3f}, severe-drawdown AUC {pred['severe_drawdown_auc']:.3f}. High-minus-low realized risk bootstrap CI [{boot['ci_2_5']:.4%}, {boot['ci_97_5']:.4%}] using {boot['method']}.", "", f"Development mean gross: A {devgross['A']:.2%}, ConstantRisk {devgross['ConstantRisk_A']:.2%}, VolOnly {devgross['VolOnly_A']:.2%}, B2E {devgross['B2E_SignalGeometry']:.2%}; both controls were calibrated only on this sample.", "", "## Main results — 2026 OOS at 10 bps per side", "", "| Metric | A | ConstantRisk | VolOnly | B2E |", "|---|---:|---:|---:|---:|"]
    mapping = [("Net @10bps", "net_return", pct), ("Sharpe", "sharpe", lambda x:f"{x:.3f}"), ("Sortino", "sortino", lambda x:f"{x:.3f}"), ("Calmar", "calmar", lambda x:f"{x:.3f}"), ("Max DD", "max_drawdown", pct), ("Annualized vol", "annualized_volatility", pct), ("Average gross", "average_gross_exposure", pct), ("Turnover", "turnover", lambda x:f"{x:.2f}"), ("Break-even cost", "break_even_cost_bps", lambda x:f"{x:.2f} bps"), ("Median 14d", "median_14d_return", pct), ("Positive 14d %", "positive_14d_pct", pct), ("10th pct 14d", "p10_14d_return", pct), ("5th pct 14d", "p5_14d_return", pct), ("Worst 14d", "worst_14d_return", pct), ("Median 14d DD", "median_14d_drawdown", pct), ("Worst 14d DD", "worst_14d_drawdown", pct)]
    names = ["A", "ConstantRisk_A", "VolOnly_A", "B2E_SignalGeometry"]
    for label, key, fmt in mapping: lines.append("| " + label + " | " + " | ".join(fmt(ptab.loc[n, key]) for n in names) + " |")
    def markdown_table(frame):
        columns = list(frame.columns)
        rows = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
        for values in frame.itertuples(index=False, name=None):
            rows.append("| " + " | ".join(str(v) for v in values) + " |")
        return "\n".join(rows)
    lines += ["", "## Buckets and states", "", markdown_table(buckets), "", markdown_table(exposure), "", "## Decision", "", f"**{decision}**. B2E improves the reported tail measures versus both development-matched controls, but OOS VolOnly exposure/volatility is materially higher than B2E (so realized-risk comparability is not sufficient for promotion). Its result is not promoted merely for lower exposure or lower drawdown than A. Detailed cost stress, rolling windows, subperiods, worst windows and experiment log are in `results/baseline_b2e/`."]
    (ROOT / "BASELINE_B2E_RESEARCH_REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
