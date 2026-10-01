# Phase 2 Paper-Trading Strategy Specification — Frozen Trend 8/24

Status: paper-trading candidate only; not approved for live competition deployment.

- Data: closed 1-hour OHLCV for BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, and XRPUSDT.
- Warm-up: at least 48 valid hourly bars per eligible asset; do not forward-fill missing prices.
- Signal: `(EMA(close, 8) - EMA(close, 24)) / rolling_std(close, 24)`, clipped to [-2, 2], divided by 2.
- Position construction: causal rolling-volatility scaling (48 bars, 35% target volatility, 5% volatility floor), then 35% absolute per-asset cap and 1.0 gross cap.
- Schedule: calculate every completed hour; submit/reconcile target changes only every 24 hours. Signals are shifted and filled on the next bar, never on the signal candle.
- Direction: long and short, exactly as produced by the frozen signal; no side removal based on historical attribution.
- Assumed costs for paper evaluation: 10 bps per side; continue to stress at 5/15/20 bps.
- Required state: last valid bar, EMA inputs, rolling volatility, current broker-confirmed positions, scheduled rebalance clock, and data-quality state.
- Required safeguards: stale/invalid-data halt, maximum gross/per-asset exposure enforcement, post-order broker reconciliation, and no local position update before confirmed fill state.
- Known weaknesses: previous 2025 selection creates multiple-testing bias; OOS 14-day positive-return probability was 43.1%, and 15 bps OOS net return was only 7.3%. Paper results must be monitored before any deployment decision.
