# Baseline B2C — Raw/Residual Disagreement Diagnostic

## Pre-registered design
Agreement is fixed as `1 - |raw - residual| / 2`, with raw and residual Trend 8/24 signals already bounded to [-1,1]. Portfolio agreement is weighted by the absolute frozen Baseline-A target. LOW/MEDIUM/HIGH thresholds were learned only from 2025 development agreement terciles and frozen before 2026 OOS evaluation: LOW < 0.825672, MEDIUM < 0.909411, HIGH >= 0.909411. The only B2C scaler tested is parameter-free: `A target × per-asset agreement`.

## Does agreement predict Baseline-A quality?
Development HIGH-minus-LOW mean next-24h A return: 0.24%, bootstrap 95% interval [-0.27%, 0.76%].
OOS HIGH-minus-LOW mean next-24h A return: -0.13%, bootstrap 95% interval [-0.89%, 0.62%].

2026 OOS next-24h bucket means:
- LOW: 0.17%, positive 49.32%
- MEDIUM: 0.18%, positive 53.33%
- HIGH: 0.04%, positive 38.36%

## Risk-state diagnostic
Agreement is much more informative about drawdown than about mean return. In development, HIGH-minus-LOW mean next-24h max drawdown is 1.40%, bootstrap 95% interval [1.05%, 1.78%]. In frozen OOS it is 1.51%, interval [1.14%, 1.91%]. Positive means HIGH agreement has a shallower (less negative) drawdown.

The OOS Spearman correlation between agreement and next-24h max drawdown is 0.551; higher agreement consistently corresponds to shallower short-horizon drawdown.

## OOS strategy test
A: net 19.91%, Sharpe 0.814, max DD 31.66%, mean gross 82.27%.
B2C disagreement scaler: net 15.76%, Sharpe 0.776, max DD 26.75%, mean gross 69.74%.
Constant-risk A control (scale fixed from 2025 at 0.854709): net 17.51%, Sharpe 0.832, max DD 27.59%, mean gross 70.32%.

14-day median return: A -1.18%; B2C -1.09%; constant-risk control -0.98%.
14-day positive windows: A 43.10%; B2C 41.75%; control 43.35%.
14-day 10th percentile: A -5.76%; B2C -4.74%; control -4.92%.
Worst 14-day: A -12.14%; B2C -9.91%; control -10.43%.

## Interpretation gate
`disagreement_contains_timing_information_beyond_constant_derisking = False`.
This flag requires B2C to beat the frozen constant-risk control on OOS Sharpe, median 14-day return, and not worsen the 10th-percentile 14-day return. It is a diagnostic gate, not production approval.

## Conclusion
Disagreement is **not supported as a return/alpha predictor**: 2026 agreement-return correlations are near zero/slightly negative and HIGH agreement does not earn more than LOW agreement. It **is supported as a short-horizon risk-state variable**: the drawdown relationship is monotonic in both development and OOS and the HIGH-vs-LOW 24h drawdown gap is robust in bootstrap resampling. However, the tested dynamic B2C scaler does not beat a development-matched constant lower-risk version of A on Sharpe/median-14d/positive-window rate. Therefore keep disagreement as a research risk diagnostic only and do not deploy the current scaler.
