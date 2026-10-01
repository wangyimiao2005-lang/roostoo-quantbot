"""Baseline B2: pre-registered rolling-PCA residual trend research only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from baseline_b2 import residual_index, residual_ready, rolling_pca_residuals
from run_baseline_b1 import BASE, DEV_START, OOS_END, OOS_START, metrics, panel, read_or_fetch, rolling, rolling_summary, run
from quant_competition.portfolio import enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend

OUT = ROOT / "results" / "baseline_b2"
OOS = pd.Timestamp(OOS_START, tz="UTC")


def raw_targets(closes: pd.DataFrame) -> pd.DataFrame:
    raw = MultiHorizonTrend(8, 24).target_weights(closes)
    scaled = risk_scale_targets(raw, closes.pct_change(fill_method=None))
    ready = closes.notna() & closes.rolling(48, min_periods=48).count().eq(48)
    return enforce_exposure_limits(scaled.where(ready, 0.0).fillna(0.0))


def residual_targets(closes: pd.DataFrame, lookback: int):
    returns = closes.pct_change(fill_method=None)
    residual, factor, diagnostics, loadings = rolling_pca_residuals(returns, lookback)
    index = residual_index(residual)
    signal = MultiHorizonTrend(8, 24).target_weights(index)
    # Deliberately use raw returns for the frozen 48h sizing model: B2 changes
    # signal construction only, not risk construction.
    scaled = risk_scale_targets(signal, returns)
    ready = residual_ready(residual) & closes.notna() & closes.rolling(48, min_periods=48).count().eq(48)
    return enforce_exposure_limits(scaled.where(ready, 0.0).fillna(0.0)), signal.where(ready, 0.0), residual, factor, diagnostics, loadings


def partial_result(result, mask):
    return type("Partial", (), {"returns": result.returns.loc[mask], "gross_returns": result.gross_returns.loc[mask],
        "costs": result.costs.loc[mask], "turnover": result.turnover.loc[mask],
        "trades": result.trades[result.trades.timestamp.isin(result.returns.index[mask])]})()


def factor_beta(result, factor: pd.Series) -> float:
    joined = pd.concat([result.gross_returns.rename("portfolio"), factor], axis=1).dropna()
    return float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / joined.iloc[:, 1].var()) if len(joined) > 1 and joined.iloc[:, 1].var() else np.nan


def contributions(result, closes, opens, label):
    intra = closes.div(opens).sub(1).replace([np.inf, -np.inf], 0).fillna(0)
    gross_by = result.weights * intra
    changes = result.weights.diff().fillna(result.weights)
    fees_by = changes.abs() * .001
    return pd.DataFrame([{"strategy": label, "asset": s, "gross_contribution": gross_by[s].sum(),
        "net_contribution": (gross_by[s] - fees_by[s]).sum(), "turnover": changes[s].abs().sum(), "fees": fees_by[s].sum(),
        "long_contribution": (gross_by[s].where(result.weights[s] > 0, 0) - fees_by[s].where(result.weights[s] > 0, 0)).sum(),
        "short_contribution": (gross_by[s].where(result.weights[s] < 0, 0) - fees_by[s].where(result.weights[s] < 0, 0)).sum()} for s in closes])


def report(summary, pca_summary, signal_corr, decision):
    table = pd.DataFrame(summary).T
    text = f"""# Baseline B2 — Common-Factor-Removed / Residual Trend Research

## Scope and causal design
This isolated research implementation retains exactly BTC, ETH, SOL, BNB and XRP; the frozen hourly Trend 8/24, raw 48-hour volatility sizing, 35%/100% caps, 24-hour rebalance, next-bar open-to-close execution and 10 bps-side cost. It changes only the signal source. PCA uses arithmetic hourly returns and, at each timestamp, only the trailing window ending at that timestamp. PC1 is standardized within that trailing sample and oriented so BTC's loading is positive. The raw-unit PC1 reconstruction (including window mean) is removed; residual arithmetic returns compound from an index base of 1.0. No PCA fitting, normalization, or selection uses future data.

## Baseline A reproduction
A reproduced the frozen reference before B2 was evaluated: net {summary['A']['net_return']:.2%}, Sharpe {summary['A']['sharpe']:.3f}, Sortino {summary['A']['sortino']:.3f}, Calmar {summary['A']['calmar']:.3f}, maximum drawdown {summary['A']['max_drawdown']:.2%}, turnover {summary['A']['turnover']:.2f}.

## Primary 720h result
B2A (residual-only) net {summary['B2A']['net_return']:.2%}, Sharpe {summary['B2A']['sharpe']:.3f}; B2B (pre-specified 50/50 raw/residual) net {summary['B2B']['net_return']:.2%}, Sharpe {summary['B2B']['sharpe']:.3f}. PC1 explained variance: mean {pca_summary['mean']:.2%}, median {pca_summary['median']:.2%}. Full results are in `results/baseline_b2`.

## Signal and factor diagnostics
Raw/residual signal correlation is mean {signal_corr['correlation'].mean():.3f}, median {signal_corr['correlation'].median():.3f}. Factor beta is reported as the covariance slope of gross portfolio returns to the causal PC1 score; it is diagnostic only and market neutrality was not imposed.

## Decision
**{decision}**. This does not replace Baseline A or alter any production/paper-trading path.
"""
    (ROOT / "BASELINE_B2_RESEARCH_REPORT.md").write_text(text)
    table.to_csv(OUT / "MAIN_COMPARISON.csv")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = {s: read_or_fetch(s, DEV_START, OOS_END) for s in BASE}
    opens, closes, _ = panel(frames, BASE)
    mask = (opens.index >= OOS) & (opens.index < pd.Timestamp(OOS_END, tz="UTC"))
    raw = raw_targets(closes)
    # Primary is executed and written before the prescribed robustness runs.
    b2target, residual_signal, residual, factor, pca, loadings = residual_targets(closes, 720)
    ensemble = enforce_exposure_limits(risk_scale_targets((MultiHorizonTrend(8,24).target_weights(closes) + residual_signal) * .5, closes.pct_change(fill_method=None)).where(closes.notna(), 0).fillna(0))
    ra, rb2a, rb2b = (run(opens.loc[mask], closes.loc[mask], x.loc[mask], 10) for x in (raw, b2target, ensemble))
    names, results = ("A", "B2A", "B2B"), (ra, rb2a, rb2b)
    summary = {n: metrics(r) for n, r in zip(names, results)}
    pd.DataFrame([{"strategy": n, **summary[n]} for n in names]).to_csv(OUT / "PRIMARY_720H_RESULTS.csv", index=False)
    pca_oos, load_oos = pca.loc[pca.index >= OOS], loadings.loc[loadings.index >= OOS]
    stats = pca_oos.pc1_explained_variance_ratio.agg(["mean", "median", "min", "max"]).to_dict()
    stats.update({"p25": pca_oos.pc1_explained_variance_ratio.quantile(.25), "p75": pca_oos.pc1_explained_variance_ratio.quantile(.75)})
    pca_oos.to_csv(OUT / "PCA_DIAGNOSTICS.csv"); load_oos.to_csv(OUT / "PCA_LOADINGS.csv")
    load_summary = load_oos.agg(["mean", "std", "min", "max"]).T.reset_index(names="asset")
    # Mean absolute hourly loading change is the pre-specified instability / turnover diagnostic.
    loading_change = load_oos.diff().abs().mean().rename("mean_abs_hourly_loading_change")
    load_summary = load_summary.merge(loading_change, left_on="asset", right_index=True)
    load_summary.to_csv(OUT / "PCA_LOADING_STABILITY.csv", index=False)
    signal_corr = pd.DataFrame({"asset": BASE, "correlation": [MultiHorizonTrend(8,24).target_weights(closes)[s].loc[mask].corr(residual_signal[s].loc[mask]) for s in BASE]})
    signal_corr.to_csv(OUT / "SIGNAL_CORRELATION.csv", index=False)
    rolling_frame = pd.concat([rolling(r, n) for n, r in zip(names, results)], axis=1).dropna()
    rolling_frame.insert(0, "window_start", rolling_frame.index - pd.Timedelta(hours=335)); rolling_frame.insert(1, "window_end", rolling_frame.index)
    rolling_frame.to_csv(OUT / "ROLLING_14D.csv", index=False)
    rolling_summaries = {n: rolling_summary(rolling_frame, n) for n in names}
    costs = []
    for cost in (5, 10, 15, 20):
        for name, target in zip(names, (raw, b2target, ensemble)):
            costs.append({"strategy": name, "cost_bps_per_side": cost, **metrics(run(opens.loc[mask], closes.loc[mask], target.loc[mask], cost))})
    cost_df = pd.DataFrame(costs); cost_df.to_csv(OUT / "COST_STRESS.csv", index=False)
    pd.concat([contributions(r, closes.loc[mask], opens.loc[mask], n) for n, r in zip(names, results)]).to_csv(OUT / "ASSET_CONTRIBUTION.csv", index=False)
    periods=[]
    for start, end, label in [("2026-01-01", "2026-04-01", "2026-Q1"), ("2026-04-01", "2026-07-01", "2026-Q2"), ("2026-07-01", "2026-09-01", "2026-JulAug")]:
        ix=(ra.returns.index >= pd.Timestamp(start, tz="UTC")) & (ra.returns.index < pd.Timestamp(end, tz="UTC"))
        periods.extend({"period": label, "strategy": n, **metrics(partial_result(r, ix))} for n,r in zip(names, results))
    pd.DataFrame(periods).to_csv(OUT / "SUBPERIODS.csv", index=False)
    breadth=pd.DataFrame({"raw_long":(raw.loc[mask]>1e-12).sum(axis=1),"raw_short":(raw.loc[mask]<-1e-12).sum(axis=1),"residual_long":(b2target.loc[mask]>1e-12).sum(axis=1),"residual_short":(b2target.loc[mask]<-1e-12).sum(axis=1)})
    breadth["raw_near_zero"]=len(BASE)-breadth.raw_long-breadth.raw_short; breadth["residual_near_zero"]=len(BASE)-breadth.residual_long-breadth.residual_short; breadth.to_csv(OUT / "SIGNAL_BREADTH.csv")
    dispersion = residual.loc[mask].std(axis=1).rename("residual_return_cross_sectional_dispersion")
    dispersion_frame = pd.concat([dispersion, rb2a.gross_returns.rename("b2a_gross_return")], axis=1).dropna()
    dispersion_frame.to_csv(OUT / "CROSS_SECTIONAL_DISPERSION.csv")
    (OUT / "CROSS_SECTIONAL_DISPERSION_SUMMARY.json").write_text(json.dumps({"contemporaneous_correlation_with_b2a_gross_return": dispersion_frame.corr().iloc[0, 1]}, indent=2))
    robustness=[]
    for window in (360, 720, 1440):
        target, _, _, _, _, _ = residual_targets(closes, window)
        robustness.append({"pca_lookback_hours":window, **metrics(run(opens.loc[mask], closes.loc[mask], target.loc[mask], 10))})
    pd.DataFrame(robustness).to_csv(OUT / "PCA_WINDOW_ROBUSTNESS.csv", index=False)
    betas = {n: factor_beta(r, factor.loc[mask]) for n,r in zip(names, results)}
    factor_exposure = pd.DataFrame([{"strategy":n,"factor_beta":b} for n,b in betas.items()]); factor_exposure.to_csv(OUT / "FACTOR_EXPOSURE.csv", index=False)
    # Transparent pre-registered execution log; no omitted parameter searches.
    now=datetime.now(timezone.utc).isoformat(); log=[]
    for n in names: log.append({"experiment_id":f"primary_720_{n}","timestamp":now,"pca_lookback_hours":720,"strategy":n,"cost_bps":10,"purpose":"primary frozen B2 comparison","result":f"net={summary[n]['net_return']:.4%}; sharpe={summary[n]['sharpe']:.3f}"})
    for row in robustness: log.append({"experiment_id":f"robustness_{int(row['pca_lookback_hours'])}_B2A","timestamp":now,"pca_lookback_hours":row['pca_lookback_hours'],"strategy":"B2A","cost_bps":10,"purpose":"predeclared PCA-window robustness","result":f"net={row['net_return']:.4%}; sharpe={row['sharpe']:.3f}"})
    pd.DataFrame(log).to_csv(OUT / "EXPERIMENT_LOG.csv", index=False)
    decision = "KEEP RESIDUAL TREND AS COMPLEMENTARY RESEARCH SIGNAL" if summary["B2B"]["sharpe"] > summary["A"]["sharpe"] and rolling_summaries["B2B"]["p10_14d_return"] >= rolling_summaries["A"]["p10_14d_return"] else "REJECT RESIDUAL TREND"
    report(summary, stats, signal_corr, decision)
    output={"metrics":summary,"rolling_14d":rolling_summaries,"pca_explained_variance":stats,"factor_beta":betas,"decision":decision}
    (OUT / "summary.json").write_text(json.dumps(output, indent=2, default=str)); print(json.dumps(output, indent=2, default=str))

if __name__ == "__main__":
    main()
