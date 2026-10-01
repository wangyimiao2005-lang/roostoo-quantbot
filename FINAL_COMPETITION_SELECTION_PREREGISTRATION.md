# Final Competition Selection Preregistration

## Purpose

The competition begins on **2026-10-04**. The final untouched period **2026-09-22 00:00 UTC through 2026-10-03 23:00 UTC** is therefore used exactly once as a pre-competition dress rehearsal to choose between two already-frozen strategies:

1. `BASELINE_TREND824` — frozen five-asset Trend 8/24 Baseline A.
2. `FUNDING_FILTER` — the same frozen Trend 8/24 targets with the already-frozen Phase 4B.1 72-hour funding crowding filter.

This is a selection gate, not a new research phase. No post-release tuning is permitted.

## Release lock

Before `2026-10-04T00:00:00Z`, `research/run_final_precompetition_gate.py` exits before loading holdout market data or funding data.

The hash-locked rules are stored at:

`frozen/precompetition_gate/FUNDING_VS_BASELINE_GATE.json`

and verified by its `.sha256` file.

## Funding promotion rule

Funding is selected only if **all** preregistered checks pass:

- Funding net return at 10 bps per side is positive.
- Funding beats Baseline A at 10 bps per side.
- Funding net return at 15 bps per side is positive.
- Funding beats Baseline A at 15 bps per side.
- Funding maximum drawdown is not worse than Baseline A by more than 2 percentage points.
- Funding beats Baseline A in at least 3 of 5 leave-one-asset-out robustness tests.
- No single UTC daily/rebalance block contributes more than 80% of the sum of positive incremental block returns.

If any check fails, the selected competition strategy is `BASELINE_TREND824`.

This deliberately prevents a candidate that merely **loses less** than Baseline A from being promoted.

## One-shot output

After release, run:

```bash
PYTHONPATH=src:research python research/run_final_precompetition_gate.py
```

The runner writes exactly one immutable selection artifact:

`frozen/competition_strategy/ACTIVE_STRATEGY.json`

plus:

`frozen/competition_strategy/ACTIVE_STRATEGY.sha256`

A later rerun reads the existing selection and does not rewrite it.

Detailed evidence is written under:

`results/final_precompetition_gate/`

## Competition runtime

`PaperRunner` now reads the immutable active-strategy artifact. Before the final gate exists it remains the original frozen Baseline A.

If the gate selects Funding, the runtime requires causal USDⓈ-M funding history. The helper:

`quant_competition.competition_runtime.build_competition_paper_runner`

constructs a runner with the release-gated Binance funding provider. A Funding-selected runtime halts new risk rather than silently falling back to Baseline if funding data are unavailable.

If the gate selects Baseline, the active strategy path does not need funding data.

## No further alpha research

After this preregistration, Sep22-Oct3 is not to be inspected for feature design, threshold changes, model selection, or strategy iteration. It is opened once on Oct 4 for the final Baseline-vs-Funding decision.
