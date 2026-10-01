# Baseline B2D — Incremental Risk-Signal Validation

## Question
Does B2C raw/residual agreement predict future Baseline-A drawdown after controlling for simpler, causal information already known at the rebalance timestamp?

No trading rule is changed in this experiment. 2025 development fits all standardization and predictive coefficients; 2026-01-01 through 2026-08-31 is held out for prediction comparison.

## Causal controls
`RISK` contains trailing 48h equal-weight crypto-market realized volatility, trailing 720h average pairwise correlation, frozen-A gross exposure, and current frozen-A drawdown. `RISK+SIGNAL` additionally contains target-weighted absolute raw Trend-8/24 signal strength and cross-sectional raw-signal dispersion. All features use data available at the signal timestamp only.

## 24h result: agreement versus conventional risk state
After controlling for volatility, correlation, gross exposure and current drawdown, agreement remains stable and significant. Development standardized agreement coefficient = 0.002488 (HAC p=0.004418); frozen-OOS diagnostic coefficient = 0.004572 (p=3.54e-05). Positive coefficients mean higher agreement predicts a shallower (less negative) next-24h maximum drawdown.

Adding agreement to the development-fitted RISK model improves frozen-OOS 24h MSE by 8.60% and severe-drawdown AUC from 0.696 to 0.721. Therefore disagreement is not merely a proxy for realized volatility or pairwise correlation.

## 24h result: is PCA disagreement uniquely necessary?
No. Once the two simpler raw-signal geometry variables are included jointly, agreement loses incremental explanatory power. In FULL, the development agreement coefficient is 0.000606 (p=0.319) and the frozen-OOS diagnostic coefficient is -0.001007 (p=0.636). Adding agreement on top of RISK+SIGNAL changes frozen-OOS MSE by only 0.015%.

The simpler RISK+SIGNAL model itself improves 24h frozen-OOS MSE by 15.08% versus RISK, versus 8.60% for RISK+AGREEMENT. Severe-drawdown AUC is 0.745 for RISK+SIGNAL and 0.746 for FULL, essentially unchanged by agreement.

## Horizon stability
The strongest reproducible result is next-24h risk. The longer 3d/7d outcomes overlap and their OOS predictive R-squared values are weak/negative for these small linear models, so they are diagnostic rather than promotion evidence. See `NESTED_REGRESSIONS.csv`, `OOS_PREDICTIVE_COMPARISON.csv` and `INCREMENTAL_VALUE.csv` for every horizon.

## Interpretation
B2C disagreement **does contain real short-horizon risk information beyond volatility/correlation/gross/current drawdown**, but that information is largely redundant with two much simpler quantities already present in the raw strategy: how strong the raw signals are and how dispersed they are across assets.

This changes the engineering conclusion. The PCA/residual pipeline is not justified as a production risk overlay yet. A simpler raw-signal-geometry risk hypothesis should be tested next against the same constant-risk and volatility-only controls.

## Decision
**DO NOT DEPLOY THE PCA DISAGREEMENT OVERLAY. KEEP IT AS A DIAGNOSTIC. NEXT TEST: RAW-SIGNAL-STRENGTH / DISPERSION RISK OVERLAY.**
