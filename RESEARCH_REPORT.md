# Quant Competition Research Report

## Executive summary

This report is generated from causal bar backtests, with next-bar-open execution and 10 bps per-side costs. Phase 1.5 found that slower execution preserves some gross trend edge while sharply reducing churn, but no active candidate produced positive net return at the primary cost. Cash remains the only surviving allocation.

## Data and methodology

The data-quality file is `results/diagnostics/data_quality.json`. The universe, date range, and interval used are recorded by the research commands. Signals are calculated at candle close and shifted before open-to-close PnL. Costs are charged on every absolute target-weight change. Missing data is intersected rather than forward-filled.

## Strategy results

```
               total_return  annualized_return  annualized_volatility  sharpe  sortino  calmar  max_drawdown  win_rate  profit_factor  total_cost   turnover  median_14d_return  positive_14d_probability  worst_14d_return  best_14d_return  gross_return  trades  median_trades_per_14d    status
strategy                                                                                                                                                                                                                                                                                           
Trend_12_36         -0.3094            -0.3094                 0.4115 -0.7520  -1.2785 -0.6824        0.4534    0.4718         0.9759      0.5997   599.7365            -0.0082                    0.4637           -0.2011           0.2033        0.2580   15278               586.0055  REJECTED
Trend_8_24          -0.4516            -0.4516                 0.4067 -1.1104  -1.8944 -0.8116        0.5564    0.4570         0.9566      0.9056   905.6125            -0.0118                    0.4440           -0.2382           0.2225        0.3565   19012               729.2274  REJECTED
Trend_4_12          -0.7831            -0.7831                 0.4088 -1.9154  -3.2552 -0.9863        0.7940    0.4349         0.8849      1.8463  1846.3111            -0.0503                    0.2063           -0.2188           0.1280        0.3747   26256              1007.0795  REJECTED
VWAPMR_1            -0.9775            -0.9775                 0.4661 -2.0972  -2.9042 -1.0000        0.9776    0.3864         0.7462      3.2647  3264.6627            -0.1438                    0.0173           -0.3413           0.0577       -0.4105   15066               577.8740  REJECTED
Breakout_12         -0.9821            -0.9821                 0.4037 -2.4329  -3.8850 -0.9997        0.9824    0.2306         0.6555      4.1841  4184.0818            -0.1490                    0.0114           -0.2916           0.0247        0.1772   16111               617.9562  REJECTED
Breakout_24         -0.9340            -0.9340                 0.3509 -2.6613  -4.3327 -0.9984        0.9354    0.1731         0.6806      2.8306  2830.5596            -0.0993                    0.0395           -0.2286           0.0586        0.1205   10554               404.8110  REJECTED
VWAPMR_1.5          -0.9398            -0.9398                 0.3437 -2.7348  -3.5741 -0.9999        0.9400    0.2533         0.6916      2.5332  2533.2202            -0.0976                    0.0089           -0.2933           0.0288       -0.2412   10005               383.7534  REJECTED
Breakout_48         -0.8462            -0.8462                 0.3080 -2.7480  -4.3738 -0.9953        0.8503    0.1255         0.7000      1.9307  1930.7054            -0.0731                    0.0726           -0.1669           0.0923        0.0606    6932               265.8849  REJECTED
VWAPMR_2            -0.7753            -0.7753                 0.2246 -3.4521  -4.3496 -0.9964        0.7781    0.1118         0.6347      1.3804  1380.4481            -0.0562                    0.0618           -0.1509           0.0569       -0.1059    4834               185.4137  REJECTED
CSMomentum_48       -0.7719            -0.7719                 0.2024 -3.8134  -6.4422 -0.9675        0.7978    0.4354         0.7999      1.6454  1645.3709            -0.0594                    0.1200           -0.1452           0.1273        0.1830    4915               188.5205  REJECTED
CSMomentum_24       -0.8837            -0.8837                 0.2032 -4.3482  -7.4127 -0.9992        0.8844    0.4106         0.7246      2.2007  2200.6542            -0.0759                    0.0843           -0.1843           0.1223        0.0516    6509               249.6603  REJECTED
CSMomentum_6        -0.9838            -0.9838                 0.2047 -4.8059  -7.3724 -0.9998        0.9839    0.3661         0.5446      4.2948  4294.8459            -0.1466                    0.0000           -0.2338          -0.0547        0.1935   12297               471.6658  REJECTED
Cash                 0.0000             0.0000                 0.0000     NaN      NaN     NaN       -0.0000    0.0000            NaN      0.0000     0.0000             0.0000                    0.0000            0.0000           0.0000        0.0000       0                 0.0000  SURVIVES
```

All 5/10/15/20 bps cost scenarios are available in `results/tables/cost_scenarios.csv`; no non-cash candidate was advanced from the 10 bps primary screen.

## Turnover Diagnosis

```
     strategy  target_weight_changes  actual_trades  avg_abs_target_change  median_abs_target_change  p90_abs_target_change  p95_abs_target_change  turnover_per_day  turnover_per_week  median_turnover_per_14d  cost_to_gross_profit  cost_to_absolute_gross_pnl
  Trend_12_36                  43795          15278                 0.0156                    0.0087                 0.0372                 0.0534            1.6431            11.5334                  22.8084          2.324400e+00                      0.0257
  Breakout_48                  43795           6932                 0.0442                    0.0000                 0.2500                 0.3500            5.2896            37.1290                  75.2205          3.188350e+01                      0.2033
CSMomentum_48                  43795           4915                 0.0377                    0.0000                 0.3468                 0.3500            4.5079            31.6417                  63.6835          8.990100e+00                      0.1295
     VWAPMR_2                  43795           4834                 0.0316                    0.0000                 0.1333                 0.3500            3.7820            26.5471                  53.3869          1.380448e+09                      0.2275
```

The key diagnosis is execution, not only signal quality. Trend had a positive gross return but small repeated target adjustments: its median raw absolute target change was below 1%. Breakout and cross-sectional momentum had larger discrete target changes, so their cost problem is not primarily micro-adjustment alone. VWAP had negative gross performance and is not a rescue priority.

## Execution Policy Experiments

The baseline `Phase1_Buffer2pct` is preserved. Policies are applied to raw targets at a completed close and are then shifted for next-bar fills. The staged set tests immediate, broad absolute buffers, 4–24 hour scheduled rebalancing, one combined cadence/buffer, and smoothing/partial-adjustment controls. It is intentionally not a full grid.

Best historical policy per family (still a descriptive in-sample screen):

```
     strategy execution_policy  gross_return  net_return_5bps  net_return_10bps  net_return_15bps  net_return_20bps  turnover  trades  break_even_cost_bps  positive_14d_probability
  Breakout_48      Rebalance8h        0.0029          -0.1716           -0.3159           -0.4351           -0.5335  382.4548    1325               0.0770                    0.3620
CSMomentum_48      Rebalance8h        0.1367          -0.1292           -0.3329           -0.4891           -0.6088  532.8472    1710               2.5658                    0.3323
  Trend_12_36     Rebalance24h        0.2679           0.1026           -0.0412           -0.1664           -0.2752  279.2594    1807               9.5921                    0.5388
     VWAPMR_2     Rebalance24h       -0.0074          -0.0502           -0.0912           -0.1304           -0.1680   88.2085     304              -0.8442                    0.4404
```

## Before / After Phase 1 Comparison

```
               phase1_net_10bps  improved_net_10bps  phase1_cost  improved_cost  phase1_turnover  improved_turnover  phase1_trades  improved_trades  phase1_sharpe  improved_sharpe selected_policy
strategy                                                                                                                                                                                           
Breakout_48             -0.8462             -0.3159       1.9307         0.3825        1930.7054           382.4548           6932             1325        -2.7480          -1.0721     Rebalance8h
CSMomentum_48           -0.7719             -0.3329       1.6454         0.5328        1645.3709           532.8472           4915             1710        -3.8134          -1.6443     Rebalance8h
Trend_12_36             -0.3094             -0.0412       0.5997         0.2793         599.7365           279.2594          15278             1807        -0.7520          -0.0974    Rebalance24h
VWAPMR_2                -0.7753             -0.0912       1.3804         0.0882        1380.4481            88.2085           4834              304        -3.4521          -0.5428    Rebalance24h
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

The policy-aware walk-forward experiment uses a 30-day trailing training window and frozen seven-day tests. It selected only from the small predeclared set: Phase 1 2% buffer, 10% buffer, 12-hour cadence, and 24-hour cadence. The stitched 47-test-window net return was **-30.77%** at 10 bps. That negative OOS outcome prevents promotion despite Trend's encouraging in-sample turnover improvement.

```
strategy       execution_policy 
Breakout_48    Rebalance12h         3
               Rebalance24h         2
CSMomentum_48  Rebalance12h         2
Cash           Cash                 5
Trend_12_36    Buffer10pct          2
               Phase1_Buffer2pct    5
               Rebalance12h         3
               Rebalance24h         9
VWAPMR_2       Rebalance12h         7
               Rebalance24h         9
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

The compact, predeclared study tested 30 trend configurations. The best 1h result was Trend 8/24 with 24-hour rebalancing: gross 48.0%, net 8.2% at 10 bps, turnover 313.1, and break-even cost 15.3 bps. It remains **WATCHLIST**, not a survivor: nearby 12/36 and 16/48 configurations were negative at 10 bps, so the local parameter evidence is not broad.

The best 4h result, Trend 6/18 with 24-hour rebalancing, had lower turnover (193.9) but net -10.6% at 10 bps. Thus 4h reduced trades but also discarded too much gross signal in this sample. Fixed state targets likewise remained net negative, so state persistence did not yet solve the economics.

```
timeframe signal_configuration    execution_type  gross_return  net_10bps  sharpe  sortino  calmar  max_drawdown  turnover  trades  trades_per_14d  positive_14d_probability  median_14d_return  break_even_cost_bps  net_5bps  net_15bps  net_20bps  entry_threshold  exit_threshold risk_sizing_cadence    status
       1h           Trend_8_24      Rebalance24h        0.4799     0.0818  0.1925   0.3162  0.3070        0.2666  313.0923    1807         69.3096                    0.5739             0.0103              15.3287    0.2654    -0.0752    -0.2095              NaN             NaN                 NaN WATCHLIST
       1h          Trend_16_48      Rebalance24h        0.2433    -0.0367 -0.0867  -0.1409 -0.0914        0.4012  254.9569    1808         69.3479                    0.4843            -0.0019               9.5422    0.0944    -0.1521    -0.2538              NaN             NaN                 NaN  REJECTED
       1h          Trend_12_36      Rebalance24h        0.2679    -0.0412 -0.0974  -0.1578 -0.1073        0.3843  279.2594    1807         69.3096                    0.5388             0.0046               9.5921    0.1026    -0.1664    -0.2752              NaN             NaN                 NaN  REJECTED
       4h           Trend_6_18      Rebalance24h        0.0850    -0.1063 -0.2619  -0.4211 -0.2617        0.4060  193.9396    1774         68.0128                    0.4896            -0.0015               4.3846   -0.0152    -0.1889    -0.2640              NaN             NaN                 NaN  REJECTED
       4h           Trend_4_12      Rebalance24h        0.0746    -0.1550 -0.3749  -0.6060 -0.3635        0.4262  240.1950    1777         68.1278                    0.4383            -0.0073               3.1074   -0.0470    -0.2507    -0.3357              NaN             NaN                 NaN  REJECTED
       4h            Trend_3_9      Rebalance24h        0.0181    -0.2222 -0.5325  -0.8695 -0.5093        0.4361  269.0050    1778         68.1661                    0.4810            -0.0019               0.6747   -0.1101    -0.3203    -0.4060              NaN             NaN                 NaN  REJECTED
       4h           Trend_6_18 Phase1_Buffer2pct       -0.0145    -0.2527 -0.6126  -0.9976 -0.6748        0.3743  276.7777    5235        200.7029                    0.4326            -0.0154              -0.5222   -0.1418    -0.3493    -0.4334              NaN             NaN                 NaN  REJECTED
       4h      StateTrend_6_18        StateFixed       -0.1105    -0.2780 -0.5684  -0.8767 -0.5516        0.5038  208.7167    1192         45.6997                    0.4663            -0.0104              -5.2942   -0.1986    -0.3496    -0.4141             0.75            0.25          entry_only  REJECTED
       1h          Trend_16_48 Phase1_Buffer2pct        0.1226    -0.2872 -0.6945  -1.1662 -0.7537        0.3811  454.1509   12987        498.1315                    0.4362            -0.0142               2.6985   -0.1055    -0.4320    -0.5474              NaN             NaN                 NaN  REJECTED
       1h          Trend_12_36 Phase1_Buffer2pct        0.2580    -0.3094 -0.7520  -1.2785 -0.6824        0.4534  599.7365   15278        586.0055                    0.4637            -0.0082               4.3022   -0.0679    -0.4884    -0.6210              NaN             NaN                 NaN  REJECTED
       1h     StateTrend_16_48        StateFixed       -0.0421    -0.3131 -0.6273  -0.9669 -0.6860        0.4564  332.6000    2030         77.8630                    0.4369            -0.0154              -1.2645   -0.1888    -0.4184    -0.5076             0.75            0.25          entry_only  REJECTED
       1h      StateTrend_8_24        StateFixed        0.2480    -0.3493 -0.7217  -1.1736 -0.7189        0.4859  651.2500    3857        147.9397                    0.4255            -0.0144               3.8084   -0.0988    -0.5302    -0.6609             0.75            0.25          entry_only  REJECTED
```

## Short-Horizon Stat-Arb

Pair discovery was independently rerun in every prior 60-day training window using Engle--Granger stationarity and a strict half-life below 24 hours. It found **0** qualifying pair windows in the controlled universe. No qualifying pairs means no PnL rows were manufactured: stat-arb is rejected for insufficient fast, stable opportunity evidence.

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
                                    development_dates                                          oos_dates  gross_return  net_return  sharpe  sortino  calmar  max_drawdown  turnover  trades  trades_per_14d  median_14d_return  positive_14d_probability  break_even_cost_bps  net_5bps  net_15bps  net_20bps  long_contribution  short_contribution   status
2025-01-01:2025-12-31 (candidate previously selected) 2026-01-01:2026-08-31 (untouched before Phase 1.7)        0.4895      0.1972  0.8051   1.3107  0.9802        0.3166  218.3943    1215            70.0            -0.0118                     0.431              22.4133    0.3354     0.0732    -0.0381             0.1234               0.106 SURVIVES
```

The frozen test passed the primary numerical hurdle: net return was +19.7% at 10 bps, Sharpe 0.81, and break-even cost 22.4 bps (12.4 bps margin over the primary assumption). It remains positive at 15 bps (+7.3%), though negative at 20 bps. The 14-day median return was -1.18% and positive probability 43.1%, a meaningful competition-fit weakness despite long-period profitability.

## Local parameter robustness

The 3×3 predeclared neighbourhood was evaluated only as a diagnostic; no cell replaces 8/24. All nine cells were positive net at 10 bps in frozen OOS, ranging from 10.95% to 22.21%. That rejects the isolated-parameter-peak explanation for this period.

```
slow      20      24      28
fast                        
6     0.2136  0.1968  0.1758
8     0.2221  0.1972  0.1348
10    0.1844  0.1732  0.1095
```

## Year-by-year, attribution, and multiple-testing caveat

The year table, asset attribution, long/short decomposition, and rolling 14-day distribution are saved under `results/tables/trend824_*`. Both long and short made positive frozen-OOS contributions, so this result is not simply a long-only bull-market exposure in the observed OOS period.

Trend 8/24 was selected after original trend variants, execution-policy variants, multi-timeframe work, state-machine variants, and other strategy research. Its original development Sharpe is therefore upward-biased. The 2026 frozen period and full supportive local OOS neighbourhood mitigate—but cannot eliminate—that research-history risk.

## Final Phase 1.7 decision

**YES — proceed to Phase 2 paper trading only.** The candidate meets frozen-OOS and local-cost-robustness evidence at 10 bps, with a break-even margin above the primary cost. It is not approved for live competition deployment: its 14-day positive-return probability is below 50%, 20 bps is negative, and paper execution must verify actual fills, fees, and data quality.
