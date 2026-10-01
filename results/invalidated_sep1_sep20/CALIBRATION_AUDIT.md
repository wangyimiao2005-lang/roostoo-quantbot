# Calibration Audit — FAILED FREEZE REPRODUCTION

The attempted run is invalid. It used feature-normalization constants
inconsistent with the frozen 2025 B2E calibration; this was found after the
September output was visible. A corrected rerun would violate the protocol.
See `HOLDOUT_INVALIDATION.md`. The remainder is a historical diagnostic record,
not an audit approval.

# Calibration Audit (Invalidated)

September 2026 was **not** used for fitting or calibration. `research/run_final_holdout.py` uses literal frozen values from `results/baseline_b2e/summary.json`, rather than deriving values from its evaluation frame.

| Frozen item | Source | Period |
|---|---|---|
| Feature means/stds, OLS intercept and betas, Q50/Q75, severe threshold | `results/baseline_b2e/summary.json` | 2025 development only |
| ConstantRisk scale | `results/baseline_b2e/summary.json` | 2025 development only |
| VolOnly k | `results/baseline_b2e/summary.json` | 2025 development only |
| EMA 8/24, sizing, caps, schedule, timing, costs | `research/run_baseline_b1.py`, `research/run_baseline_b2.py`, engine | pre-existing frozen implementation |

No September observations are passed to regression fitting, normalization, threshold calculation, multiplier selection, ConstantRisk calibration, VolOnly calibration, EMA/universe selection, or transaction-cost selection.

Data provider: Binance public spot klines; symbols: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT; requested: 2026-09-01 through 2026-09-20T15:00:00+00:00; actual closed interval: 2026-09-01 00:00:00+00:00 through 2026-09-20 14:00:00+00:00; complete bars per symbol: 471; missing bars: {'BTCUSDT': 0, 'ETHUSDT': 0, 'SOLUSDT': 0, 'BNBUSDT': 0, 'XRPUSDT': 0}.
