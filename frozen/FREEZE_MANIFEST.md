# B2E_v1 Freeze Manifest

- Strategy ID: B2E_v1
- Freeze status: FROZEN
- Freeze timestamp: 2026-09-21 UTC
- Development calibration rows: 2025-01-01 through 2025-12-31 UTC only
- Source calibration code: research/b2e_freeze.py
- Source datasets: local Binance spot 1-hour OHLCV for BTCUSDT, ETHUSDT,
  SOLUSDT, BNBUSDT, and XRPUSDT. Jan 1 2026 bars are used solely as realized
  outcome labels for Dec 31 2025 decisions, never as calibration rows.
- Immutable artifact: frozen/b2e_v1.json
- SHA-256: a0d7d4b2b331926c1763effa8835749e56cb7a3dcd813cf71e5dc9acea41853c
- Git commit: unavailable; this copied holdout directory is not a git worktree.
- Official Stage-B runner: research/run_b2e_final_holdout.py
- Freeze verifier: PASS; control calibrations use an explicit 2025-only mask.
- Full test suite at seal: 70 passed, 0 failed.
- Engineering-only metadata: metrics.hours_per_year = 8760; reporting only.
- Official data loader audits cached hourly coverage after release and fetches only missing contiguous Binance ranges; partial history cannot proceed to performance evaluation.
- New sealed final holdout: 2026-09-22T00:00:00Z through
  2026-10-03T23:00:00Z; release 2026-10-04T00:00:00Z.

## Historical exclusion

Sep 1–20 2026 is an **INVALIDATED HOLDOUT**, **DIAGNOSTIC ONLY**, and **NOT
ELIGIBLE FOR FINAL VALIDATION**. Its artifacts reside in
results/invalidated_sep1_sep20.
