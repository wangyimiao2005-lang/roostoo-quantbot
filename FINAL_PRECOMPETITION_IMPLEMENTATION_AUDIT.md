# Final Pre-Competition Implementation Audit

Date prepared: 2026-09-26.

## Competition timing correction

The competition starts on 2026-10-04. Funding is therefore **not** scheduled to begin a new shadow-validation period on Oct 4. Instead, Sep22-Oct3 remains sealed until the competition start date and is opened exactly once as the final Baseline-vs-Funding selection sample.

## Current state before release

- Final scored holdout: `2026-09-22 00:00 UTC` through `2026-10-03 23:00 UTC`.
- Release / selector unlock: `2026-10-04 00:00 UTC`.
- No `ACTIVE_STRATEGY.json` exists yet.
- Before selection, the runtime remains the frozen `BASELINE_TREND824` strategy.
- No Sep22-Oct3 market or funding observations were loaded while implementing or testing this change.

## Frozen decision logic

The hash-locked gate is `frozen/precompetition_gate/FUNDING_VS_BASELINE_GATE.json`.

Funding is promoted only if all checks pass:

1. positive 10-bps net return;
2. beats Baseline A at 10 bps;
3. positive 15-bps net return;
4. beats Baseline A at 15 bps;
5. max drawdown no more than 2 percentage points worse;
6. wins at least 3/5 leave-one-asset-out comparisons;
7. no one daily/rebalance block contributes >80% of positive incremental block return.

Otherwise the selector chooses Baseline A.

## Runtime behavior

`PaperRunner` reads the immutable active-strategy selection. Before an active selection exists it uses the original frozen Baseline A.

If Funding is selected, the runtime requires causal Binance USDⓈ-M funding history. Missing/failed funding data causes `HALT_NEW_RISK`; it does not silently substitute another strategy.

The helper `build_competition_paper_runner` constructs the runner with a funding provider ready, but provider construction itself performs no network request.

## Release safety

Both the selector and funding provider contain a hard release lock. Before 2026-10-04 00:00 UTC, the selector exits before any holdout loader is called, and the funding provider exits before any HTTP request.

## Validation

- Full pytest suite: **99 passed**.
- Synthetic end-to-end gate calculation path executed successfully.
- The synthetic test intentionally produced identical Baseline/Funding returns and correctly failed promotion because Funding did not beat Baseline, confirming there is no automatic preference for the more complex strategy.
- Python compile check passed for `src`, `research`, and `tests`.

## Oct 4 procedure

At or immediately after 2026-10-04 00:00 UTC, before the first 01:00 UTC scheduled execution:

```bash
PYTHONPATH=src:research python research/run_final_precompetition_gate.py
```

Then inspect:

```bash
cat frozen/competition_strategy/ACTIVE_STRATEGY.json
cat results/final_precompetition_gate/FINAL_PRECOMPETITION_GATE_REPORT.md
```

The first run writes the immutable strategy selection. Later runs do not rewrite it.
