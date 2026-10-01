# Baseline B2E — Preregistration

This document was created before the B2E 2026 OOS evaluation.  B2E is a
research-only, portfolio-level risk overlay; it does not modify Baseline A
production code, asset selection, signal direction, relative weights, sizing,
rebalance schedule, execution timing, or costs.

## Frozen baseline and samples

Baseline A is the five-asset (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT)
hourly EMA 8/24 Trend signal, with its existing 48-hour volatility sizing,
35% target volatility, 5% volatility floor, 35% single-asset cap, 100% gross
cap, long/short positions, 24-hour rebalance, and next-bar open-to-close
execution. Primary cost is 10 bps per side; 5, 15 and 20 bps are stress cases.

Development is 2025-01-01 through 2025-12-31 UTC. Frozen OOS is 2026-01-01
through 2026-08-31 UTC. All fitting, normalisation, calibration and thresholds
below use development observations only.

## Features, target and model

At each 00:00 UTC scheduled rebalance, raw signals are the existing frozen
five-asset Trend 8/24 signals. `signal_strength = mean(abs(raw_signal_i))` and
`signal_dispersion = std(raw_signal_i, ddof=0)`. Neither is target-weighted.

The target is `future_dd_risk = abs(future_24h_max_drawdown)`, calculated from
the next 24 executed Baseline-A hourly net returns (starting with the next bar).
Both features are standardized by their 2025 population mean and population
standard deviation. One OLS model is fitted on 2025 only:

`future_dd_risk = intercept + beta_strength*z_strength + beta_dispersion*z_dispersion`.

The 2026 score uses those frozen constants and coefficients. The severe-risk
classification threshold is the development 75th percentile of target risk.

## Primary overlay and controls

Q50 and Q75 are respectively the 2025 median and 75th percentile of fitted
development predicted risk. At each scheduled rebalance the portfolio multiplier
is 1.00 for prediction <= Q50, 0.75 for Q50 < prediction <= Q75, and 0.50 for
prediction > Q75. It is held until the next scheduled rebalance. B2E target is
exactly Baseline-A target times this scalar; it never exceeds A exposure or
reverses a position.

`ConstantRisk_A` is Baseline A times one scalar: B2E's 2025 mean gross exposure
divided by A's 2025 mean gross exposure. `VolOnly_A` uses only causal trailing
48-hour equal-weight-market realized annualized volatility and multiplier
`min(1, k / market_vol_48h)`. `k` is calibrated by deterministic bisection on
2025 only to match B2E's 2025 mean gross exposure as closely as possible. Both
controls are frozen before OOS.

## Evaluation and success standard

All four strategies (A, ConstantRisk_A, VolOnly_A, B2E_SignalGeometry) are run
at 5/10/15/20 bps per side. OOS metrics are net return, Sharpe, Sortino, Calmar,
max drawdown, annualized volatility, average gross, turnover, fees and
break-even cost. Identical overlapping 14-day windows report mean, median,
positive rate, 25th/10th/5th percentiles, best/worst return, median/90th/worst
drawdown magnitude, turnover and fees.

Primary evidence requires B2E to improve tail outcomes versus *both* matched
risk controls at reasonably comparable average gross / realized volatility:
10th and 5th percentile 14-day return, worst 14-day return, median and worst
14-day drawdown, and full-OOS maximum drawdown, with reasonable upside capture,
turnover and subperiod stability. Lower risk versus A alone is insufficient.
The permitted decisions are PROMOTE B2E FOR FURTHER VALIDATION, KEEP B2E AS
RESEARCH-ONLY RISK SIGNAL, or REJECT B2E. No rules will be tuned after OOS.
