# B2E_v1 New Final Holdout Pre-Registration

Frozen artifact: frozen/b2e_v1.json
SHA-256: a0d7d4b2b331926c1763effa8835749e56cb7a3dcd813cf71e5dc9acea41853c

This preregistration supersedes the prior Sep21 start date. The final untouched
holdout is 2026-09-22 00:00 UTC through 2026-10-03 23:00 UTC. It is sealed
until 2026-10-04 00:00 UTC. Eligible strategies are Baseline
A, frozen ConstantRisk A, frozen VolOnly A, and frozen B2E_v1.

Primary cost is 10 bps per side; stress costs are 5, 15, and 20 bps per side.
No refitting, tuning, holdout-driven parameter changes, or subwindow selection
is permitted. The entire fixed period is the competition-length block; complete
rolling 14-day windows will be reported only if available.

Official performance requires only complete Sep22–Oct3 hourly bars. A B2E risk
prediction is scored against realized 24-hour drawdown only when its complete
future 24-hour outcome lies inside that same official dataset; late predictions
remain trading and risk-state observations but are excluded from risk scoring.

The central comparison is A versus ConstantRisk versus VolOnly versus B2E.
After release exactly one status will be used: B2E FINAL HOLDOUT SUPPORTIVE,
MIXED, or UNSUPPORTIVE. No Sep22-Oct3 performance had been evaluated at the
time of this seal. The sole official evaluator is
python research/run_b2e_final_holdout.py.
