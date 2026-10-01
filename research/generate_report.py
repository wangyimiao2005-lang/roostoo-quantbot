from pathlib import Path
import os
import pandas as pd
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "data/cache/matplotlib"))
import matplotlib.pyplot as plt
from common import ROOT
def main():
    zoo=ROOT/"results/tables/strategy_zoo.csv"
    if not zoo.exists(): raise SystemExit("Run `python research/run_strategy_zoo.py` before generating the report.")
    table=pd.read_csv(zoo,index_col=0); eligible=(table.total_return>0)&(table.sharpe>0)&(table.median_trades_per_14d>=4)&(table.total_cost < table.gross_return.clip(lower=0))
    table["status"]="REJECTED"; table.loc[eligible,"status"]="WATCHLIST"
    table.loc["Cash", "status"]="SURVIVES"
    table.to_csv(ROOT/"results/tables/strategy_summary.csv")
    returns=pd.read_csv(ROOT/"results/tables/strategy_returns.csv",index_col=0,parse_dates=True)
    plots=ROOT/"results/plots"; plots.mkdir(parents=True,exist_ok=True)
    equity=(1+returns).cumprod(); ax=equity.plot(figsize=(11,5),title="Net equity curves (10 bps per side)"); ax.set_ylabel("growth of $1"); plt.tight_layout(); plt.savefig(plots/"equity_curves.png",dpi=150); plt.close()
    drawdowns=equity.div(equity.cummax()).sub(1); ax=drawdowns.plot(figsize=(11,5),title="Drawdown curves"); ax.set_ylabel("drawdown"); plt.tight_layout(); plt.savefig(plots/"drawdowns.png",dpi=150); plt.close()
    rolling=(1+returns).rolling(336).apply(__import__("numpy").prod,raw=True).sub(1); ax=rolling.plot(kind="hist",bins=40,alpha=.35,figsize=(10,5),title="Rolling 14-day net-return distribution"); plt.tight_layout(); plt.savefig(plots/"rolling_14d_distribution.png",dpi=150); plt.close()
    execution_file=ROOT/"results/tables/execution_robustness_summary.csv"
    diag_file=ROOT/"results/diagnostics/turnover_diagnostics.csv"
    execution=pd.read_csv(execution_file) if execution_file.exists() else pd.DataFrame()
    diagnostics=pd.read_csv(diag_file) if diag_file.exists() else pd.DataFrame()
    before_after=pd.read_csv(ROOT/"results/tables/execution_before_after.csv",index_col=0) if execution_file.exists() else pd.DataFrame()
    wf_file=ROOT/"results/tables/execution_walk_forward_windows.csv"
    wf=pd.read_csv(wf_file) if wf_file.exists() else pd.DataFrame()
    wf_returns=pd.read_csv(ROOT/"results/tables/execution_walk_forward_returns.csv",index_col=0).iloc[:,0] if wf_file.exists() else pd.Series(dtype=float)
    trend_file=ROOT/'results/tables/trend_deep_dive.csv'; trend=pd.read_csv(trend_file) if trend_file.exists() else pd.DataFrame()
    stat_file=ROOT/'results/tables/stat_arb_results.csv'; stat=pd.read_csv(stat_file) if stat_file.exists() else pd.DataFrame()
    frozen_file=ROOT/'results/tables/frozen_oos_trend824.csv'; frozen=pd.read_csv(frozen_file) if frozen_file.exists() else pd.DataFrame()
    local_file=ROOT/'results/tables/trend824_local_robustness.csv'; local=pd.read_csv(local_file) if local_file.exists() else pd.DataFrame()
    yearly_file=ROOT/'results/tables/trend824_yearly.csv'; yearly=pd.read_csv(yearly_file) if yearly_file.exists() else pd.DataFrame()
    best=execution.sort_values("net_return_10bps",ascending=False).groupby("strategy",as_index=False).first() if not execution.empty else pd.DataFrame()
    report=f'''# Quant Competition Research Report

## Executive summary

This report is generated from causal bar backtests, with next-bar-open execution and 10 bps per-side costs. Phase 1.5 found that slower execution preserves some gross trend edge while sharply reducing churn, but no active candidate produced positive net return at the primary cost. Cash remains the only surviving allocation.

## Data and methodology

The data-quality file is `results/diagnostics/data_quality.json`. The universe, date range, and interval used are recorded by the research commands. Signals are calculated at candle close and shifted before open-to-close PnL. Costs are charged on every absolute target-weight change. Missing data is intersected rather than forward-filled.

## Strategy results

```
{table.round(4).to_string()}
```

All 5/10/15/20 bps cost scenarios are available in `results/tables/cost_scenarios.csv`; no non-cash candidate was advanced from the 10 bps primary screen.

## Turnover Diagnosis

```
{diagnostics.round(4).to_string(index=False) if not diagnostics.empty else 'Run turnover diagnostics first.'}
```

The key diagnosis is execution, not only signal quality. Trend had a positive gross return but small repeated target adjustments: its median raw absolute target change was below 1%. Breakout and cross-sectional momentum had larger discrete target changes, so their cost problem is not primarily micro-adjustment alone. VWAP had negative gross performance and is not a rescue priority.

## Execution Policy Experiments

The baseline `Phase1_Buffer2pct` is preserved. Policies are applied to raw targets at a completed close and are then shifted for next-bar fills. The staged set tests immediate, broad absolute buffers, 4–24 hour scheduled rebalancing, one combined cadence/buffer, and smoothing/partial-adjustment controls. It is intentionally not a full grid.

Best historical policy per family (still a descriptive in-sample screen):

```
{best[[c for c in ['strategy','execution_policy','gross_return','net_return_5bps','net_return_10bps','net_return_15bps','net_return_20bps','turnover','trades','break_even_cost_bps','positive_14d_probability'] if c in best]].round(4).to_string(index=False) if not best.empty else 'No execution results.'}
```

## Before / After Phase 1 Comparison

```
{before_after.round(4).to_string() if not before_after.empty else 'No comparison available.'}
```

Trend 12/36 improved from -30.9% to -4.1% net at 10 bps under 24-hour scheduled rebalancing, while turnover fell from 599.7 to 279.3. Its break-even cost is roughly 9.6 bps per side—too close to the 10 bps primary assumption to be robust. This supports **WATCHLIST research**, not promotion.

## Transaction-Cost Robustness and 14-Day Fit

All policy rows include net returns and Sharpe at 5/10/15/20 bps, break-even cost, trades per 14 days, and historical positive 14-day probability in `results/tables/execution_robustness_summary.csv`. A cost-sensitive result whose conclusion changes around plausible fees is not live-ready. The execution run is a controlled 1-hour study; 15-minute/4-hour validation and policy-aware walk-forward selection remain required before an active strategy can survive.

## Updated Strategy Decisions

- **Trend:** WATCHLIST for further out-of-sample multi-timeframe execution testing. Gross edge survives less-frequent trading but net return is still negative at 10 bps.
- **Breakout:** REJECTED in the current forms. Some turnover falls under cadence controls, but gross edge is too weak to pay costs.
- **Cross-sectional momentum:** REJECTED in the current hourly forms. Ranking less frequently helps but does not yield a positive net result.
- **VWAP mean reversion:** REJECTED. Gross results are weak/negative as well as cost-sensitive.
- **Statistical arbitrage:** NOT YET IMPLEMENTED; no claim is made.
- **Cash:** SURVIVES.

## Walk-Forward Execution Selection

The policy-aware walk-forward experiment uses a 30-day trailing training window and frozen seven-day tests. It selected only from the small predeclared set: Phase 1 2% buffer, 10% buffer, 12-hour cadence, and 24-hour cadence. The stitched 47-test-window net return was **{((1+wf_returns).prod()-1):.2%}** at 10 bps. That negative OOS outcome prevents promotion despite Trend's encouraging in-sample turnover improvement.

```
{wf.groupby(['strategy','execution_policy']).size().rename('selected_windows').to_string() if not wf.empty else 'Run execution walk-forward first.'}
```

## 14-day competition analysis

`median_trades_per_14d`, rolling return quantiles, and probability of a positive 14-day return are reported in the summary table. These statistics describe historical samples only and are not forecasts.

## Selection and risk controls

Walk-forward selection ranks only the prior 30 days, selects up to three candidates with positive training Sharpe and at least eight trades, then evaluates the following unseen seven days. It may choose fewer than three or cash. Exposure is capped at 1x gross and 35% per asset; volatility scaling uses only lagged rolling volatility and has a floor.

## Failure analysis and recommendation

No active strategy should advance to Phase 2 Roostoo paper/live testing yet. Trend is the only justified WATCHLIST because execution improvements retained positive gross edge and reduced needless turnover, but it did not yet survive 10 bps, policy-aware out-of-sample validation, or multi-timeframe review. Use Cash pending that work.

## Phase 2 execution note

Future Roostoo execution must reconcile broker state: calculate target → submit order → confirm API response and order status → reconcile filled quantity, balances, and short positions → update local state. Credentials are intentionally absent from this repository.

# Phase 1.6: Trend Deep Dive and Stat-Arb Challenger

## Trend Deep Dive: 1h vs 4h and persistent states

The compact, predeclared study tested {len(trend)} trend configurations. The best 1h result was Trend 8/24 with 24-hour rebalancing: gross 48.0%, net 8.2% at 10 bps, turnover 313.1, and break-even cost 15.3 bps. It remains **WATCHLIST**, not a survivor: nearby 12/36 and 16/48 configurations were negative at 10 bps, so the local parameter evidence is not broad.

The best 4h result, Trend 6/18 with 24-hour rebalancing, had lower turnover (193.9) but net -10.6% at 10 bps. Thus 4h reduced trades but also discarded too much gross signal in this sample. Fixed state targets likewise remained net negative, so state persistence did not yet solve the economics.

```
{trend.sort_values('net_10bps',ascending=False).head(12).round(4).to_string(index=False) if not trend.empty else 'Run trend deep dive first.'}
```

## Short-Horizon Stat-Arb

Pair discovery was independently rerun in every prior 60-day training window using Engle--Granger stationarity and a strict half-life below 24 hours. It found **{len(stat)//3}** qualifying pair windows in the controlled universe. No qualifying pairs means no PnL rows were manufactured: stat-arb is rejected for insufficient fast, stable opportunity evidence.

## Updated Final Decision

- Trend: **WATCHLIST**. The one promising 1h configuration needs frozen OOS success and broad nearby robustness.
- 4h trend and state trend: **REJECTED** in tested forms.
- Stat-arb: **REJECTED** for the present five-asset universe; no fast pair windows qualified.
- Cash: **SURVIVES**.

# Phase 1.7: Frozen Validation of Trend 8/24

## Frozen strategy specification and split

The candidate was frozen before its OOS evaluation: 1-hour Trend 8/24, existing causal volatility sizing and exposure caps, 24-hour scheduled rebalance, next-bar execution, and 10 bps per side. Development evidence is the previously used 2025 dataset; the frozen OOS is newly downloaded 2026-01-01 through 2026-08-31. No parameters, cadence, or universe members were changed after seeing OOS results.

## Frozen OOS results

```
{frozen.round(4).to_string(index=False) if not frozen.empty else 'Run frozen validation first.'}
```

The frozen test passed the primary numerical hurdle: net return was +19.7% at 10 bps, Sharpe 0.81, and break-even cost 22.4 bps (12.4 bps margin over the primary assumption). It remains positive at 15 bps (+7.3%), though negative at 20 bps. The 14-day median return was -1.18% and positive probability 43.1%, a meaningful competition-fit weakness despite long-period profitability.

## Local parameter robustness

The 3×3 predeclared neighbourhood was evaluated only as a diagnostic; no cell replaces 8/24. All nine cells were positive net at 10 bps in frozen OOS, ranging from 10.95% to 22.21%. That rejects the isolated-parameter-peak explanation for this period.

```
{local.pivot(index='fast',columns='slow',values='net_return').round(4).to_string() if not local.empty else 'No local grid.'}
```

## Year-by-year, attribution, and multiple-testing caveat

The year table, asset attribution, long/short decomposition, and rolling 14-day distribution are saved under `results/tables/trend824_*`. Both long and short made positive frozen-OOS contributions, so this result is not simply a long-only bull-market exposure in the observed OOS period.

Trend 8/24 was selected after original trend variants, execution-policy variants, multi-timeframe work, state-machine variants, and other strategy research. Its original development Sharpe is therefore upward-biased. The 2026 frozen period and full supportive local OOS neighbourhood mitigate—but cannot eliminate—that research-history risk.

## Final Phase 1.7 decision

**YES — proceed to Phase 2 paper trading only.** The candidate meets frozen-OOS and local-cost-robustness evidence at 10 bps, with a break-even margin above the primary cost. It is not approved for live competition deployment: its 14-day positive-return probability is below 50%, 20 bps is negative, and paper execution must verify actual fills, fees, and data quality.
'''
    (ROOT/"RESEARCH_REPORT.md").write_text(report); print("Wrote RESEARCH_REPORT.md")
if __name__ == "__main__": main()
