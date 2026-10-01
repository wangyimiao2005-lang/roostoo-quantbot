# Phase 4B.1 — Proper Derivatives Signal Decomposition

## Protocol
- Common universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT. Missing local premium/taker history: ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, TRXUSDT, UNIUSDT, NEARUSDT. No data were fabricated.
- Threshold calibration: 2025 H1 only.
- Candidate selection: 2025 H2 only.
- Historical evaluation: 2026 Jan–Aug only.
- Sep 2026: **not loaded into research selection or diagnostics**.
- Cost stress re-runs raw targets at each fee; the prior `weights.shift(-1)` issue is removed.

## Development-selected challenger
`FLOW` was selected before the 2026 decomposition using profit-first 14-day development-validation metrics.

Development H2 net: 12.46% vs baseline 6.99%.

2026 Jan–Aug net: 20.01% vs common-universe baseline 19.72%.
Mean matched 14-day incremental return: -0.12%.
Median matched 14-day return: -0.87%.
P(beat baseline): 51.7%.

The development-selected rule therefore does **not** reproduce its 2025 H2 advantage in economically meaningful 14-day average PnL.

## Full decomposition (diagnostic, not a new selection pass)
| Strategy | Net @10bps | Mean 14d | Median 14d | P(beat baseline) | Mean incremental 14d |
|---|---:|---:|---:|---:|---:|
| BASELINE | 19.72% | 1.16% | -1.12% | 0.0% | 0.00% |
| FLOW | 20.01% | 1.04% | -0.87% | 51.7% | -0.12% |
| PREMIUM | 17.77% | 1.01% | -0.62% | 59.1% | -0.15% |
| FUNDING | 23.02% | 1.29% | -0.50% | 59.1% | 0.13% |
| FLOW_PREMIUM | 19.89% | 1.02% | -0.34% | 63.5% | -0.14% |
| FLOW_FUNDING | 23.52% | 1.20% | -0.49% | 63.9% | 0.04% |
| PREMIUM_FUNDING | 18.10% | 1.01% | -0.56% | 58.7% | -0.15% |
| FLOW_PREMIUM_FUNDING | 20.02% | 1.01% | -0.48% | 63.0% | -0.15% |

The highest 2026 total-net challenger is `FLOW_FUNDING` at 23.52%, but this was identified after inspecting 2026 and must remain exploratory. Variants with positive geometric incremental return in all three 2026 subperiods: FUNDING.

## Stability
`PHASE4B1_SUBPERIOD_STABILITY.csv` separates Q1, Q2 and Jul–Aug. A headline gain is not treated as robust if it disappears in individual subperiods.

## Concentration
For the development-selected rule, worst incremental result after excluding any single asset is -4.92%. Incremental performance excluding its best week is -3.06%. This is a material fragility warning.

## Decision
**MIXED — INCREMENTAL ALPHA EXISTS BUT IS TEMPORALLY UNSTABLE**

Interpretation: the prior +28% combined-filter headline should not be treated as deployable evidence. The clean pre-2026 selection chose Flow, and Flow barely matched the baseline in 2026 while failing the average 14-day incremental-PnL test. Funding may deserve a separately preregistered future test because it is the only component here with positive incremental return across Q1, Q2 and Jul–Aug, but it underperformed the baseline in 2025 H2 and cannot be promoted from this analysis.

This phase is intentionally a decomposition/stability audit. Because 2026 results were already observed in earlier Phase 4B iterations, they are not represented as a pristine new holdout. The final sealed competition holdout remains untouched by this code.
