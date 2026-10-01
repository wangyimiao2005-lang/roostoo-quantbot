# Phase 2.4 Implementation Report

## Status

The frozen `trend824_v1_frozen` strategy remains unchanged. Phase 2.4 fixes operational parity, broker accounting, executable target feasibility, Roostoo API normalization, and crash-safe rebalance recovery. No live competition execution is enabled.

## Frozen strategy

- Closed 1-hour bars.
- EMA 8 / EMA 24 trend signal.
- 48-bar volatility sizing, 35% target volatility, 5% volatility floor.
- 35% absolute per-asset cap and 1.0 gross cap.
- Long and short enabled.
- Research timing preserved exactly: scheduled 00:00 UTC signal bar, next-bar effective execution at 01:00 UTC.

## True research/live parity

`research/run_paper_parity.py` now compares two independent paths:

1. the original vectorized research path (`MultiHorizonTrend -> risk_scale_targets -> enforce_exposure_limits -> Rebalance24h -> shift(1)`), and
2. a streaming operational path that sees only the historical prefix available at each signal time.

Measured result over 60 scheduled rebalances:

- timestamps compared: **60**
- max EMA8 error: **0.0**
- max EMA24 error: **0.0**
- max rolling-std error: **0.0**
- max volatility error: **0.0**
- max signal error: **0.0**
- max target error: **5.551115123125783e-17**
- signal timestamp mismatches: **0**
- execution timestamp mismatches: **0**
- rebalance mismatches: **0**
- tolerance: **1e-10**
- result: **PASS**

The operational runner no longer truncates EMA state to 60 bars; it uses the complete available causal history supplied by the provider.

## Executable portfolio budgeting

The theoretical strategy target remains untouched. Before submission, a separate executable target is derived with a common scale factor that respects:

- actual broker-confirmed current positions;
- free cash;
- existing short collateral and entry prices;
- reductions before increases;
- estimated transaction fees;
- new short collateral requirements;
- a small deterministic cash reserve for numerical/precision differences;
- 1.0 actual gross-exposure cap;
- 35% actual per-asset cap.

This closes the earlier failure mode where a rebalance could reach the final short order and fail with `insufficient collateral`.

## Correct short accounting

`PaperBroker` now models Roostoo-style collateral accounting:

- opening a short locks collateral and charges the open fee;
- locked collateral is not free cash;
- partial closes release collateral proportionally;
- realized short PnL is settled on close;
- close fees are charged;
- the documented collateral loss cap is modeled on the closed slice;
- account equity includes free cash, long market value, locked short collateral, and short unrealized PnL without double counting.

Example: with $1,000 free USD, opening $500 of short collateral at a 10 bps fee leaves approximately $499.50 free USD and $500 locked collateral.

## Multi-day LOCAL_PAPER acceptance

`research/run_local_paper_acceptance.py` streamed the actual 2026 frozen dataset through the operational runner for 10 consecutive scheduled rebalances using the corrected timing and collateral model.

Measured result:

- scheduled rebalances: **10**
- completed rebalances: **10**
- start equity: **100000.0**
- end equity: **102902.33401367394**
- minimum free cash: **1.000000000005457**
- maximum locked short collateral: **103135.90476619058**
- maximum gross exposure: **0.9999899996510856**
- maximum asset exposure: **0.3174756715651094**
- BUY_LONG actions: **17**
- SELL_LONG actions: **16**
- OPEN_SHORT actions: **18**
- CLOSE_SHORT actions: **9**
- direction crossings: **14**
- total simulated fees: **719.441832854404**
- reconciliation failures: **0**
- uncaught exceptions: **0**
- broker orders: **60**

The acceptance run therefore exercises both long and short books, resizing, and zero-crossing behavior while remaining within the frozen exposure limits.

## Crash recovery and idempotency

The SQLite state now persists a rebalance intent before broker execution and tracks states including `PLANNED`, `EXECUTING_REDUCTIONS`, `RECONCILING_REDUCTIONS`, `EXECUTING_INCREASES`, `FINAL_RECONCILIATION`, `COMPLETED`, and `FAILED`.

A deliberate crash was injected after the first broker fill but before local completion:

- crash injected: **true**
- persisted state after crash: **EXECUTING_INCREASES**
- orders already filled at crash: **1**
- restart result: **RECONCILED**
- total orders after recovery: **5**
- second attempt of the same completed rebalance: **ALREADY_DONE**
- duplicate orders on repeated attempt: **0**

Recovery works by re-reading broker-authoritative positions and replanning only the remaining delta toward the previously persisted desired quantities.

## Roostoo API adapter audit

The adapter was normalized against the current public Roostoo API contract and is covered by mocked contract tests.

Implemented/verified endpoints:

| Endpoint | Auth | Normalized behavior |
|---|---|---|
| `GET /v3/serverTime` | none | server-time offset |
| `GET /v3/exchangeInfo` | none | raw exchange rules for later instrument parsing |
| `GET /v3/ticker` | timestamp check | returns ticker `Data` map; no unnecessary HMAC signature |
| `GET /v3/balance` | signed | wallet normalized to balances / account snapshot |
| `GET /v3/pending_count` | signed | documented zero-pending `Success=false` normalized to zero |
| `POST /v3/place_order` | signed | nested `OrderDetail` normalized to a common order result |
| `POST /v3/query_order` | signed | uses `pending_only=TRUE/FALSE` convention and normalized results |
| `POST /v3/cancel_order` | signed | normalized cancel result |
| `POST /v6/short_open` | signed | `ID`, `ShortQty`, `Collateral`, `OpenFee` normalized |
| `POST /v6/short_close` | signed | `close_qty` contract and close response normalized |
| `GET /v6/short_positions` | signed | normalized short positions |

The account snapshot combines spot long inventory from `/v3/balance` with short inventory from `/v6/short_positions` instead of treating the short endpoint as the whole portfolio.

## Tests

Current suite result: **28 passed, 0 failed**.

The suite includes regression tests for true target/timing parity, executable collateral budgeting, short collateral accounting, crash-after-fill recovery, duplicate-rebalance prevention, and Roostoo endpoint/auth/response normalization.

## Generated paper artifacts

The acceptance run populates:

- `results/paper/parity_report.json`
- `results/paper/research_reference.csv`
- `results/paper/local_paper_acceptance.json`
- `results/paper/crash_recovery.json`
- `results/paper/signals.csv`
- `results/paper/targets.csv`
- `results/paper/orders.csv`
- `results/paper/fills.csv`
- `results/paper/positions.csv`
- `results/paper/equity.csv`
- `results/paper/reconciliation.csv`
- `results/paper/errors.csv`

## Remaining blockers

- No current 2026 Roostoo credentials were supplied, so authenticated read-only calls have not been verified against the real competition account.
- Real order placement has not been performed and remains intentionally disabled for acceptance purposes.
- Exchange precision/minimum-order behavior still needs to be validated against the actual competition `exchangeInfo` response before paper orders.
- Actual competition fees and symbol availability must be sourced dynamically from the competition environment rather than inferred from historical/public examples.

## Readiness matrix

- UNIT TESTS: **READY**
- TRUE RESEARCH-LIVE PARITY: **READY**
- EXACT TIMING PARITY: **READY**
- EMA / STATE PARITY: **READY**
- MULTI-DAY LOCAL PAPER: **READY**
- SHORT COLLATERAL ACCOUNTING: **READY**
- EXPOSURE CONTROLS: **READY**
- POST-ORDER RECONCILIATION: **READY**
- SQLITE STATE: **READY**
- CRASH RECOVERY: **READY**
- ROOSTOO API ADAPTER: **READY (mocked contract tests)**
- ROOSTOO READ-ONLY: **BLOCKED — current credentials not provided**
- ROOSTOO PAPER: **NOT READY**
- LIVE COMPETITION: **NOT APPROVED**
