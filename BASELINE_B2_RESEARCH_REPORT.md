# Baseline B2 — Common-Factor-Removed / Residual Trend Research

## Scope and causal design
This isolated research implementation retains exactly BTC, ETH, SOL, BNB and XRP; the frozen hourly Trend 8/24, raw 48-hour volatility sizing, 35%/100% caps, 24-hour rebalance, next-bar open-to-close execution and 10 bps-side cost. It changes only the signal source. PCA uses arithmetic hourly returns and, at each timestamp, only the trailing window ending at that timestamp. PC1 is standardized within that trailing sample and oriented so BTC's loading is positive. The raw-unit PC1 reconstruction (including window mean) is removed; residual arithmetic returns compound from an index base of 1.0. No PCA fitting, normalization, or selection uses future data.

## Baseline A reproduction
A reproduced the frozen reference before B2 was evaluated: net 19.72%, Sharpe 0.805, Sortino 1.311, Calmar 0.980, maximum drawdown 31.66%, turnover 218.39.

## Primary 720h result
B2A (residual-only) net -11.86%, Sharpe -1.367; B2B (pre-specified 50/50 raw/residual) net 7.90%, Sharpe 0.492. PC1 explained variance: mean 85.27%, median 86.42%. Full results are in `results/baseline_b2`.

## Signal and factor diagnostics
Raw/residual signal correlation is mean 0.226, median 0.225. Factor beta is reported as the covariance slope of gross portfolio returns to the causal PC1 score; it is diagnostic only and market neutrality was not imposed.

## Decision
**REJECT RESIDUAL TREND**. This does not replace Baseline A or alter any production/paper-trading path.
