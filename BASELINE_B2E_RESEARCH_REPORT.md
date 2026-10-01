# Baseline B2E — Raw Signal Geometry Risk Overlay

## Method

This preregistered research-only overlay multiplies frozen Baseline-A targets by a daily portfolio multiplier. It uses only unweighted raw Trend 8/24 signal strength and cross-sectional dispersion, fitted by one 2025 OLS model. No PCA/residual signal, alpha rule, direction, relative weight, sizing, execution or schedule was changed.

## Frozen model and OOS risk validation

2025 coefficients: intercept 0.016640, strength 0.006841, dispersion -0.001834; predicted-risk Q50 1.5435%, Q75 2.1813%. 2026 Pearson 0.549, Spearman 0.595, MSE 0.00011143, OOS R² 0.278, severe-drawdown AUC 0.749. High-minus-low realized risk bootstrap CI [1.0047%, 1.7795%] using circular moving-block bootstrap, 5 daily observations/block, 10,000 draws.

Development mean gross: A 77.78%, ConstantRisk 60.48%, VolOnly 62.29%, B2E 60.48%; both controls were calibrated only on this sample.

## Main results — 2026 OOS at 10 bps per side

| Metric | A | ConstantRisk | VolOnly | B2E |
|---|---:|---:|---:|---:|
| Net @10bps | 19.91% | 16.15% | 10.47% | 15.61% |
| Sharpe | 0.814 | 0.841 | 0.505 | 0.913 |
| Sortino | 1.324 | 1.370 | 0.822 | 1.535 |
| Calmar | 0.990 | 0.994 | 0.657 | 1.070 |
| Max DD | 31.66% | 25.36% | 24.54% | 22.76% |
| Annualized vol | 38.55% | 29.97% | 31.96% | 26.68% |
| Average gross | 82.27% | 63.97% | 72.95% | 62.31% |
| Turnover | 218.78 | 170.11 | 195.62 | 174.47 |
| Break-even cost | 22.51 bps | 22.16 bps | 17.56 bps | 21.59 bps |
| Median 14d | -1.18% | -0.88% | -1.17% | -0.92% |
| Positive 14d % | 43.10% | 43.51% | 43.57% | 40.49% |
| 10th pct 14d | -5.76% | -4.47% | -5.27% | -3.96% |
| 5th pct 14d | -7.07% | -5.49% | -6.33% | -4.74% |
| Worst 14d | -12.14% | -9.51% | -9.90% | -7.73% |
| Median 14d DD | 7.14% | 5.57% | 5.96% | 5.20% |
| Worst 14d DD | 12.81% | 10.05% | 11.38% | 8.13% |

## Buckets and states

| bucket | count | mean_drawdown_risk | median_drawdown_risk | p90_drawdown_risk | mean_baseline_a_return | baseline_a_positive_return_probability |
|---|---|---|---|---|---|---|
| Low | 109 | 0.009401577642836955 | 0.007360482656050493 | 0.020678386740943053 | 0.0006931592236121612 | 0.45871559633027525 |
| Medium | 63 | 0.01659654995050437 | 0.01568711142773649 | 0.02564304094084202 | 0.001202871260472651 | 0.49206349206349204 |
| High | 70 | 0.023055902907118897 | 0.018432826186748796 | 0.04072795340147983 | 0.0012705503157493525 | 0.45714285714285713 |

| multiplier | scheduled_observations | usage_pct | average_duration_days | runs |
|---|---|---|---|---|
| 1.0 | 109 | 0.45041322314049587 | 1.7868852459016393 | 61 |
| 0.75 | 63 | 0.2603305785123967 | 1.4318181818181819 | 44 |
| 0.5 | 70 | 0.2892561983471074 | 1.627906976744186 | 43 |

## Decision

**KEEP B2E AS RESEARCH-ONLY RISK SIGNAL**. B2E improves the reported tail measures versus both development-matched controls, but OOS VolOnly exposure/volatility is materially higher than B2E (so realized-risk comparability is not sufficient for promotion). Its result is not promoted merely for lower exposure or lower drawdown than A. Detailed cost stress, rolling windows, subperiods, worst windows and experiment log are in `results/baseline_b2e/`.
