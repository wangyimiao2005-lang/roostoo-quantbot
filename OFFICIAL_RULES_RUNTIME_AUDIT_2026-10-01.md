# Official-Rules Runtime Audit — 2026-10-01

## Scope

Audited the competition branch against the organizer's current Luma problem statement,
the Official FAQ supplied by Team40-Life Game, the Data Sources Pack, and the public
Roostoo API documentation.  Strategy research/frozen selection logic was not retuned.

## Verified competition constraints

- Preparation: Oct 1–3; live trading: Oct 4–17 (14 full days).
- At least 8 active trading days.
- Autonomous API-only trading; no manual trades/intervention.
- No HFT, market making, or arbitrage.
- Spot only, 1x long/short, no leverage.
- $100,000 initial mock portfolio.
- Taker 10 bps; maker 5 bps.
- 30 Roostoo API calls/minute (FAQ).
- Open-source repository with traceable commit history and trade-log integrity.

## Strategy verdict

The frozen five-asset Trend 8/24 baseline is rule-compatible: directional, low-frequency,
1x gross-capped, next-bar causal, and modeled at 10 bps/side.  Its 2026 Jan–Aug frozen
OOS evidence was +19.72% net at 10 bps, Sharpe 0.805, Sortino 1.311, Calmar 0.980,
31.66% max drawdown, with both long and short contributions positive.  The 14-day
median (-1.18%) and positive-window rate (43.1%) remain the main competition-horizon
weakness.  The existing one-shot Baseline-vs-Funding gate is preserved.

### Active-day compliance diagnostic

On the untouched 2026 Jan-Aug OOS replay, the frozen daily schedule produced intended
asset orders on all 243 calendar days (1,215 asset orders total). Every rolling 14-day
window contained 14 active trading days and 70 intended asset orders, so the current
cadence has substantial historical headroom over the organizer's 8-active-day minimum.
This is a pre-exchange diagnostic: live MiniOrder/precision filtering and API failures can
still reduce actual filled activity and therefore must be monitored.

## Critical production gaps found in the prior package

1. No production 24/7 launcher: RUN_ON_OCT4.sh selected a strategy but never ran a bot.
2. No competition-time live OHLCV provider implementing LiveMarketDataProvider.
3. No explicit 30-call/minute limiter or API success/failure audit log.
4. Any non-DRY_RUN mode string enabled writes; a typo could submit orders.
5. Cross-asset bar timestamps could silently misalign and change targets.
6. Real exchangeInfo precision/MiniOrder rules were documented as a blocker but were not enforced by the competition runner.
7. Net positions could hide simultaneous long+short inventory in one asset.
8. Broker/network exceptions could escape the runner and kill the daemon.
9. README still described the repository as paper-only/live-not-approved.
10. The short implementation depended on undocumented `/v6/short_*` endpoints. This blocker has now been cleared by a General/Test live verification: read-only positions, minimum short open, full close, and empty final position all returned HTTP 200 / Success=true.

## Hardening added in this package

- BinanceCompetitionLiveProvider: historical bootstrap + persistent live Binance 1h OHLCV cache; closed bars only.
- Explicit modes: DRY_RUN, LOCAL_PAPER, COMPETITION; arbitrary strings are rejected.
- Cross-asset closed-bar alignment and execution-price universe checks.
- exchangeInfo tradability, AmountPrecision, and MiniOrder enforcement before plan persistence.
- Gross broker inventory checks, including simultaneous long/short detection.
- Daemon-level exception containment plus crash-safe recovery from broker-authoritative positions; uncertain writes are never blindly replayed.
- Roostoo sliding-window limiter capped at 28 calls/minute, leaving headroom below the official 30.
- Safe retry only for read/idempotent endpoints; order-creation writes are never blindly replayed.
- Structured JSONL API and runtime logs with no credentials/parameters written.
- 24/7 launcher with Oct-4 final gate auto-run and fail-closed behavior; DRY_RUN and COMPETITION use separate durable state files.

## Live API verification completed on 2026-10-01

The General/Test account passed:

- `/v3/balance` signed authentication with the live `SpotWallet`/`MarginWallet` schema.
- `/v6/short_positions` read-only capability.
- Minimum `BTC/USD` `/v6/short_open(pair, collateral)` execution.
- Immediate `/v6/short_close(pair, close_qty)` using the exact server-returned `ShortQty`.
- Final `/v6/short_positions` returned an empty position list.
- Observed open and close fees were approximately 10 bps per leg.

The production broker was updated to parse `SpotWallet`, include short collateral exactly once in equity, use v6 position quantity/collateral as authoritative, and halt on a material disagreement between `SpotWallet.USD.ShortCollateral` and the v6 position collateral sum.

## Remaining blockers before COMPETITION mode

1. Validate the **assigned competition credentials** read-only on the organizer AWS Sydney instance.
2. Run the competition launcher in authenticated `DRY_RUN --once` on AWS and inspect logs/state.
3. Initialize/push the open-source GitHub repository and maintain traceable commit history.
4. Confirm AWS process supervision/restart behavior using the organizer's AWS Guide.

The short-contract blocker is cleared. Keep `COMPETITION` mode disabled until the AWS/credential/deployment gates above are complete.
