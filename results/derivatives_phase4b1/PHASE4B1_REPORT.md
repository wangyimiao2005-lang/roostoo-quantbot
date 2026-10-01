# Phase 4B.1 — Proper Derivatives Signal Decomposition

## Protocol
- Common universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, TRXUSDT, UNIUSDT, NEARUSDT. Missing local premium/taker history: none. No data were fabricated.
- Threshold calibration: 2025 H1 only.
- Candidate selection: 2025 H2 only.
- Historical evaluation: 2026 Jan–Aug only.
- Sep 2026: **not loaded into research selection or diagnostics**.
- Cost stress re-runs raw targets at each fee; the prior `weights.shift(-1)` issue is removed.

## Development-selected challenger
`FLOW` was selected before the 2026 decomposition using profit-first 14-day development-validation metrics.

Development H2 net: 5.67% vs baseline 2.76%.

2026 Jan–Aug net: -2.17% vs common-universe baseline -12.09%.
Mean matched 14-day incremental return: 0.51%.
Median matched 14-day return: -1.48%.
P(beat baseline): 65.7%.

The development-selected rule has a positive mean matched 14-day incremental return versus the expanded-universe baseline. This remains historical decomposition evidence, not a new selection pass.

## Full decomposition (diagnostic, not a new selection pass)
| Strategy | Net @10bps | Mean 14d | Median 14d | P(beat baseline) | Mean incremental 14d |
|---|---:|---:|---:|---:|---:|
| BASELINE | -12.09% | -0.55% | -2.19% | 0.0% | 0.00% |
| FLOW | -2.17% | -0.04% | -1.48% | 65.7% | 0.51% |
| PREMIUM | -2.81% | -0.14% | -2.01% | 64.3% | 0.41% |
| FUNDING | -10.72% | -0.50% | -2.17% | 61.3% | 0.05% |
| FLOW_PREMIUM | 6.46% | 0.38% | -1.12% | 64.3% | 0.93% |
| FLOW_FUNDING | -1.85% | -0.03% | -1.08% | 63.0% | 0.52% |
| PREMIUM_FUNDING | -4.07% | -0.21% | -2.01% | 59.6% | 0.34% |
| FLOW_PREMIUM_FUNDING | 4.87% | 0.32% | -1.03% | 63.5% | 0.87% |

The highest 2026 total-net challenger is `FLOW_PREMIUM` at 6.46%, but this was identified after inspecting 2026 and must remain exploratory. Variants with positive geometric incremental return in all three 2026 subperiods: FLOW, PREMIUM, FUNDING, FLOW_PREMIUM, FLOW_FUNDING, PREMIUM_FUNDING, FLOW_PREMIUM_FUNDING.

## Stability
`PHASE4B1_SUBPERIOD_STABILITY.csv` separates Q1, Q2 and Jul–Aug. A headline gain is not treated as robust if it disappears in individual subperiods.

## Five-asset versus expanded-universe robustness
`PHASE4B1_UNIVERSE_EXPANSION_COMPARISON.csv` preserves the original five-asset result alongside this 13-asset rerun, including the requested Q1, Q2, and Jul–Aug net-return comparisons.

For the expanded universe, Flow returned -2.17% versus the baseline's -12.09%, with 0.51% mean matched 14-day incremental return. Funding returned -10.72% versus the same baseline and had 0.05% mean matched 14-day incremental return. Funding's incremental geometric result was positive in Q1, Q2, and Jul–Aug, but it underperformed the baseline in 2025 H2 development validation and is not promoted by this robustness test.

## Concentration
For the development-selected rule, worst incremental result after excluding any single asset is 8.10%. Incremental performance excluding its best week is 8.06%. This is a material fragility warning.

## Decision
**PROCEED — DEV-SELECTED DERIVATIVES FILTER IS STABLE ENOUGH FOR A FORMAL NEXT VALIDATION**

Interpretation: the prior +28% combined-filter headline should not be treated as deployable evidence. The clean pre-2026 selection chose Flow; in the expanded universe it outperformed the expanded baseline on 2026 total net return and mean matched 14-day incremental PnL. This is a robustness observation, not a new parameter-selection pass. Funding was incrementally positive in each 2026 subperiod but underperformed the baseline in 2025 H2 and cannot be promoted from this analysis.

This phase is intentionally a decomposition/stability audit. Because 2026 results were already observed in earlier Phase 4B iterations, they are not represented as a pristine new holdout. The final sealed competition holdout remains untouched by this code.
