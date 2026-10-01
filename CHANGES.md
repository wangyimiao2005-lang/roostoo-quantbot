# Changes

## Created

- Python package covering provider abstraction, Binance historical ingestion, data validation, strategy signals, risk sizing, exposure caps, causal backtesting, performance metrics, walk-forward selection, and sensitivity analysis.
- CLI research commands, YAML configuration, dependency manifest, environment example, tests, and project documentation.
- Result folders with ignored generated CSV/plot/diagnostic artifacts.

## Design decisions

- Signal-to-fill timing is explicitly next-bar open; no strategy gets a same-bar fill.
- Costs apply to absolute changes in target portfolio weights and are separated from gross PnL.
- Cash is a first-class strategy and walk-forward selection has no obligation to fill Top-K.
- Live brokerage code, secrets, and unverified fee assumptions are excluded.

## Known limitations / next steps

- Add point-in-time cointegration/stat-arb, multi-timeframe resampling, cost-scenario summaries, plots, full ablations, and multiple-testing correction before making a production recommendation.
- Validate actual competition symbols, fees, leverage/short constraints, and data source when published.

## Phase 1.5: execution research

- Added an explicit execution-policy layer with immediate baseline, absolute/relative buffers, scheduled rebalancing, smoothing, partial adjustment, and minimum holding behavior.
- Added regression tests for policy equivalence and each policy mechanism; 10 tests pass.
- Added turnover and trade-size diagnostics, staged execution-policy experiments, cost robustness, break-even cost, and Phase 1 before/after outputs.
- Finding: 24-hour scheduled Trend 12/36 sharply reduced turnover and reduced the 10 bps loss, but did not create robust net profitability. No active strategy advanced.

## Phase 1.6: trend and stat-arb challenger

- Added causal OHLCV resampling, persistent state-machine trend signals, a compact 1h/4h deep-dive runner, and point-in-time Engle--Granger/half-life pair utilities.
- Added state-transition and resampling tests; 12 tests pass.
- The best descriptive trend result was 1h Trend 8/24 rebalanced every 24 hours, net +8.2% at 10 bps and break-even 15.3 bps, but nearby configurations did not corroborate it. It remains WATCHLIST only.
- 4h reduced turnover but lost more gross signal; no fast cointegrated pair windows met the strict <24h half-life standard in the controlled universe.

## Phase 1.7: frozen Trend 8/24 validation

- Downloaded a new 2026-01-01 through 2026-08-31 closed-hourly dataset for an untouched frozen OOS run.
- Added frozen OOS, predeclared 3×3 local robustness, yearly, attribution, long/short, and 14-day distribution outputs.
- Frozen Trend 8/24 / 24h rebalancing returned +19.7% net at 10 bps with 22.4 bps break-even; all local OOS cells were positive. It advances to Phase 2 paper trading only, with documented short-horizon and fee-sensitivity risks.

## Phase 2.4: parity and broker-accounting finalization

- Replaced truncated 60-bar live target calculation with complete causal history and matched the frozen 00:00 signal -> 01:00 next-bar execution timing.
- Replaced the prior superficial parity check with an independent research-vector versus streaming operational harness; 60 scheduled rebalances match with max target error `5.55e-17` and zero timestamp/rebalance mismatches.
- Added fee/collateral-aware executable-target scaling with reductions before increases, a deterministic cash reserve, and post-fee gross/per-asset exposure enforcement.
- Corrected PaperBroker short collateral locking, proportional collateral release, short PnL/fee accounting, and normalized account-equity snapshots.
- Added crash-safe SQLite rebalance states persisted before broker actions; crash-after-fill recovery replans from broker-authoritative positions and avoids duplicate orders.
- Normalized Roostoo API paths/auth/response shapes for `/v3/ticker`, `/v3/balance`, pending/query/place/cancel order, and `/v6` short endpoints.
- Added contract and integration regression tests; current suite is 28 passing tests.
- Added a real 10-rebalance LOCAL_PAPER acceptance run: 10/10 completed, zero reconciliation failures/exceptions, max gross `0.99999`, and minimum free cash approximately `$1`.
- Added populated paper journals, `PHASE2_IMPLEMENTATION_REPORT.md`, and `PAPER_RUNBOOK.md`.

## Baseline B2C: raw/residual disagreement diagnostic

- Added a research-only diagnostic for whether raw Trend 8/24 and causal 720h-PCA residual Trend 8/24 disagreement predicts future Baseline-A quality.
- Froze the agreement formula as `1 - abs(raw_signal - residual_signal) / 2`; 2025 development only determines tercile cutoffs and the matched constant-risk control scale.
- Added one parameter-free dynamic scaler (`Baseline-A target × per-asset agreement`) plus a development-matched constant-risk Baseline-A control to separate timing information from generic de-risking.
- Finding: disagreement does not predict mean return out of sample, but strongly predicts short-horizon drawdown severity. The dynamic scaler reduces tail losses but does not beat the matched constant-risk control on Sharpe, median 14-day return, or positive-window rate, so it remains a risk diagnostic only.
- Added 3 B2C regression tests; full suite: 36 passed.

## Baseline B2D: incremental risk-signal validation

- Added a research-only nested-model test of whether B2C raw/residual agreement predicts future Baseline-A drawdown beyond simpler causal controls.
- Development-only standardization/model fitting uses 2025; 2026 frozen OOS is used for prediction comparison.
- Agreement adds meaningful 24h drawdown information beyond realized volatility, pairwise correlation, gross exposure and current drawdown, but becomes redundant once raw signal strength and cross-sectional signal dispersion are included jointly.
- Production Baseline A remains unchanged. PCA disagreement remains diagnostic only; the next research candidate is a simpler raw-signal-geometry risk overlay.

## Phase 4B.1: derivatives signal decomposition audit

- Added a strict five-asset common-universe decomposition of Flow, Premium, Funding, and all pair/triple filter combinations using only locally available Binance Futures histories.
- Split 2025 into H1 threshold calibration and H2 development selection; Sep-2026 rows are discarded before coverage, feature, or selection work.
- Repaired Phase 4B cost-stress methodology by re-running raw targets at each fee rather than feeding executed weights back through the causal engine.
- Added true 72-hour funding averaging, daily and non-overlapping 14-day competition metrics, subperiod stability, leave-one-asset-out, best-week concentration, and filter-activity diagnostics.
- Development selected Flow-only (+12.46% vs +6.99% baseline in 2025 H2), but it only reached +20.01% vs +19.72% in 2026 Jan-Aug and had negative mean matched 14-day incremental PnL. It is not deployable.
- Funding-only is an exploratory finding (+23.02% in 2026 Jan-Aug and positive incremental return in Q1/Q2/Jul-Aug), but it underperformed the baseline in 2025 H2 and therefore was not promoted.
- Added six Phase 4B.1 regression tests; full suite: 83 passed.

## 2026-09-26 — Final pre-competition selector

- Reframed 2026-09-22 through 2026-10-03 as a one-shot final dress-rehearsal holdout before the 2026-10-04 competition start.
- Added hash-locked Baseline-vs-Funding decision rules under `frozen/precompetition_gate/`.
- Added `research/run_final_precompetition_gate.py`; it performs no holdout data access before 2026-10-04 00:00 UTC and writes one immutable `ACTIVE_STRATEGY.json` after release.
- Added causal, release-gated Binance USDⓈ-M funding provider for competition-time Funding operation.
- Updated `PaperRunner` to read the immutable competition selection while preserving Baseline A as the default before final selection.
- Funding-selected runtime halts new risk if causal funding data are unavailable rather than silently changing strategy.
- Restored forward-only Funding shadow catch-up safeguards from the reviewed runtime.
- Added final-gate/provider/hash tests. Full suite: 99 passed.

## 2026-10-01 — live v6 short contract integrated

- Live-verified General/Test `/v3/balance` schema (`SpotWallet`/`MarginWallet`).
- Live-verified `/v6/short_positions`, `/v6/short_open(pair, collateral)`, and `/v6/short_close(pair, close_qty)`.
- Updated `RoostooBroker` to parse `SpotWallet`, include short collateral exactly once in equity, normalize live short response fields, and fail closed on material collateral-source disagreement.
- Replaced the old SELL-from-zero verifier path with a guarded v6-only General/Test open→verify→close→verify probe using `/usr/bin/curl` and normal TLS verification.
- Added live-schema/collateral-consistency regression tests; full suite now 105/105.
- Frozen research parameters and B2E freeze remain unchanged.
