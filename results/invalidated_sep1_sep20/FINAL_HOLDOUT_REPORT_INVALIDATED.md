# INVALIDATED — NOT AN UNTOUCHED FINAL HOLDOUT

The first September B2E execution used feature-normalization constants that
did not match the frozen 2025 calibration. This defect was discovered after
the output was visible. Per the protocol, corrected constants may not be
applied in a rerun. The remainder of this document and all CSV artifacts below
are quarantined implementation diagnostics, **not official results**. No final
status or production decision is assigned. See
`results/final_holdout/HOLDOUT_INVALIDATION.md`.

# Final Untouched Holdout Report (Invalidated)

## 1. Holdout Declaration

B2E_v1 was frozen before this final holdout.

No September 2026 data was used to fit, calibrate, select, or tune B2E_v1.

No B2E_v1 parameters were changed after observing final-holdout results.

## 2. Calibration Audit

See `results/final_holdout/CALIBRATION_AUDIT.md`.

## 3. Frozen Strategy Definitions

The four and only four strategies are frozen Baseline A, ConstantRisk_A, VolOnly_A, and B2E_v1. B2E uses the frozen 1.00/0.75/0.50 mapping and identical next-bar execution.

## 4. Data Coverage

UTC 2026-09-01 00:00:00+00:00 through 2026-09-20 14:00:00+00:00 (471 closed hourly bars). No tradeable OHLCV bars were forward-filled.

## 5. Baseline Reproduction

The prior frozen Jan–Aug artifact reports Baseline A net return 19.91%, Sharpe 0.814, and maximum drawdown 31.66%; this runner reuses the same target and execution functions.

## 6. Full Final-Holdout Results

| strategy     |   gross_return |   net_return |    sharpe |   sortino |    calmar |   max_drawdown |   annualized_volatility |   turnover |   annualized_turnover |   trade_count |   trades_per_day |     fees |   fees_pct_gross_pnl |   break_even_cost_bps |   average_gross_exposure |   average_net_exposure |   long_trades |   short_trades |
|:-------------|---------------:|-------------:|----------:|----------:|----------:|---------------:|------------------------:|-----------:|----------------------:|--------------:|-----------------:|---------:|---------------------:|----------------------:|-------------------------:|-----------------------:|--------------:|---------------:|
| A            |      -0.067604 |    -0.087350 | -2.336275 | -3.267655 | -6.043216 |       0.135245 |                0.349836 |  21.402839 |            398.065534 |           100 |         5.095541 | 0.021403 |            -0.320931 |            -31.586247 |                 0.829659 |              -0.004021 |            55 |             45 |
| ConstantRisk |      -0.052428 |    -0.068069 | -2.685468 | -3.756058 | -6.865250 |       0.106404 |                0.272015 |  16.641771 |            309.515748 |           100 |         5.095541 | 0.016642 |            -0.320931 |            -31.503999 |                 0.645101 |              -0.003126 |            55 |             45 |
| VolOnly      |      -0.061296 |    -0.079717 | -2.389172 | -3.383676 | -6.126660 |       0.128407 |                0.329279 |  19.812496 |            368.487186 |           100 |         5.095541 | 0.019812 |            -0.328393 |            -30.938057 |                 0.759315 |              -0.012531 |            55 |             45 |
| B2E          |      -0.056892 |    -0.074914 | -2.539814 | -3.621599 | -6.139101 |       0.124615 |                0.301211 |  19.285161 |            358.679435 |           100 |         5.095541 | 0.019285 |            -0.343563 |            -29.500145 |                 0.740487 |               0.034196 |            53 |             47 |

Annualized statistics from this short sample are noisy.

## 7. Cost Stress

|   cost_bps_per_side |         A |       B2E |   ConstantRisk |   VolOnly |
|--------------------:|----------:|----------:|---------------:|----------:|
|            5.000000 | -0.077527 | -0.065944 |      -0.060279 | -0.070549 |
|           10.000000 | -0.087350 | -0.074914 |      -0.068069 | -0.079717 |
|           15.000000 | -0.097075 | -0.083803 |      -0.075798 | -0.088800 |
|           20.000000 | -0.106703 | -0.092612 |      -0.083466 | -0.097798 |

## 8. Sep 1–14 Competition-Length Block

| strategy     |   net_return |   max_drawdown |   annualized_volatility |   average_gross_exposure |   turnover |     fees |
|:-------------|-------------:|---------------:|------------------------:|-------------------------:|-----------:|---------:|
| A            |    -0.084033 |       0.097219 |                0.339955 |                 0.798308 |  14.781394 | 0.014781 |
| ConstantRisk |    -0.065609 |       0.076094 |                0.264332 |                 0.620724 |  11.493269 | 0.011493 |
| VolOnly      |    -0.079769 |       0.092911 |                0.318877 |                 0.739853 |  13.868757 | 0.013869 |
| B2E          |    -0.078986 |       0.092245 |                0.281864 |                 0.726880 |  13.525671 | 0.013526 |

## 9. Rolling 14-Day Windows

All complete overlapping windows are in `results/final_holdout/ROLLING_14D.csv`; count: 136.

## 10. B2E Risk-State Usage

|    state |   rebalances |    share |   average_duration_days |   longest_consecutive_days |
|---------:|-------------:|---------:|------------------------:|---------------------------:|
| 1.000000 |    14.000000 | 0.700000 |                2.333333 |                   5.000000 |
| 0.750000 |     5.000000 | 0.250000 |                1.250000 |                   2.000000 |
| 0.500000 |     1.000000 | 0.050000 |                1.000000 |                   1.000000 |

Transitions: 10.

## 11. Frozen Risk-Bucket Validation

| bucket   |   count |   mean_realized_dd |   median_realized_dd |   p90_realized_dd |   mean_baseline_future_return |   baseline_positive_frequency |
|:---------|--------:|-------------------:|---------------------:|------------------:|------------------------------:|------------------------------:|
| Low      |      13 |           0.013569 |             0.011371 |          0.029228 |                     -0.002878 |                      0.384615 |
| Medium   |       5 |           0.021953 |             0.014207 |          0.039084 |                     -0.005052 |                      0.400000 |
| High     |       1 |           0.017103 |             0.017103 |          0.017103 |                     -0.013143 |                      0.000000 |

Prediction metrics: |         n |   pearson |   spearman |      mse |   severe_threshold |   severe_drawdown_auc |
|----------:|----------:|-----------:|---------:|-------------------:|----------------------:|
| 19.000000 |  0.344539 |   0.426316 | 0.000150 |           0.021563 |              0.650000 |. Risk ordering: **MIXED**; samples are small.

## 12. B2E vs Baseline A

B2E retained 0.858 of A net return when meaningful; it changed maximum-drawdown magnitude by 1.06%.

## 13. B2E vs ConstantRisk

Compare the frozen primary values above; no September exposure re-matching was performed.

## 14. B2E vs VolOnly

Compare the frozen primary values above; no September exposure re-matching was performed.

## 15. Upside / Downside Capture

| strategy     |   upside_capture |   downside_capture |
|:-------------|-----------------:|-------------------:|
| ConstantRisk |         0.775524 |           0.777084 |
| VolOnly      |         0.980847 |           0.944673 |
| B2E          |         0.960201 |           0.906239 |

## 16. Limitations

This is a short final sample, so annualized ratios and sparse risk buckets should not be overinterpreted.

## 17. Final Status

**B2E FINAL HOLDOUT MIXED**

## 18. Production Implication

Baseline A remains the production candidate; B2E remains research-only. No live or paper-trading code was changed.
