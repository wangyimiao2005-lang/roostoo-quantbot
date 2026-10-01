# Baseline B1 — Expanded Universe Research

## 1. Objective
Test whether an expanded, ex-ante selected crypto universe improves frozen Baseline A while holding signal, timing, sizing, caps, rebalancing and costs constant.

## 2. Frozen Baseline A definition
BTC, ETH, SOL, BNB, XRP; hourly EMA 8/24 standardized by 24-hour close standard deviation, clipped to [-2,2] / 2; 48-hour per-asset volatility scaling to 35% with 5% floor; 35% asset and 100% gross caps; 24-hour rebalance; next-bar open-to-close execution; 10 bps per side primary cost.

## 3. Pre-registered B1 universe selection rule
The candidate list was fixed before performance runs: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT, LTCUSDT, BCHUSDT, TRXUSDT, UNIUSDT, ETCUSDT, APTUSDT, NEARUSDT, ATOMUSDT. Selection cutoff was 2026-01-01 UTC. An asset must have at least 180 days of valid 2025 hourly OHLCV, <=0.5% missing valid OHLCV bars during 2025, and median 2025 hourly close × volume >= US$1m. Strategy returns, Sharpe, momentum and PnL were never inputs. Indicators require 48 consecutive valid hourly closes; a missing/currently invalid bar is excluded, never forward-filled.

Included (13): BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, TRXUSDT, UNIUSDT, NEARUSDT.

Excluded: DOTUSDT, BCHUSDT, ETCUSDT, APTUSDT, ATOMUSDT.

## 4. Data quality
See `results/baseline_b1/data_quality.csv`; it records point-in-time availability and each inclusion decision.

## 5. Baseline A reproduction
At 10 bps OOS, net return 19.72%, Sharpe 0.805, Sortino 1.311, Calmar 0.980, max drawdown 31.66%. This run uses the frozen engine and OOS dates 2026-01-01 through 2026-08-31.

## 6–9. B1, walk-forward, frozen OOS and cost stress
B1 net return -12.09%, Sharpe -0.422, max drawdown 43.22%. Cost results are in `COST_STRESS.csv`; walk-forward fixed-policy weekly results are in `walk_forward.csv`.

## 10. Rolling 14-day comparison
A median -1.18%; B1 median -2.29%. Full overlapping-window distribution is `rolling_14d.csv`.

## 11–14. Attribution, concentration and robustness
Per-asset attribution is in `asset_contribution.csv`, breadth in `breadth.csv`, subperiods in `subperiods.csv`, correlation diagnostics in `correlation_diagnostics.csv`, universe breadth variants in `universe_size_robustness.csv`, and leave-one-out diagnostics in `leave_one_out.csv`. B1 top-1 / top-3 PnL shares are 27.0% / 68.2%.

## 15. Multiple-testing caveats
All breadth variants and leave-one-out diagnostics are logged in `EXPERIMENT_LOG.csv`. They are diagnostics only and cannot be used to select a new production universe.

## 16. Limitations
Binance spot OHLCV and dollar volume are proxies for Roostoo tradability. The universe is selected using pre-OOS history, but exchange availability is not a guarantee of competition availability. Correlation diagnostics do not change weights.

## 17. Decision
**REJECT B1**. Baseline A remains frozen and no live, broker, PaperRunner, or production configuration was changed.
