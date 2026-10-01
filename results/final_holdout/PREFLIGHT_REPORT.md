# B2E_v1 New Final Holdout Preflight

- Freeze artifact created: YES
- Freeze SHA-256: a0d7d4b2b331926c1763effa8835749e56cb7a3dcd813cf71e5dc9acea41853c
- 2025 calibration reproduced: PASS (strict tolerance: 1e-10)
- Feature normalization: strength mean 0.27771504862335994; strength std
  0.11211552554818305; dispersion mean 0.12288766204098177; dispersion std
  0.07832940530864453.
- OLS: intercept 0.01663969115222859; beta strength 0.006841290631899482;
  beta dispersion -0.0018338145465563657.
- Q50/Q75: 0.015435113699219554 / 0.02181284722052758.
- ConstantRisk calibration: 0.7775497273015051 (2025-only: PASS).
- VolOnly calibration k: 0.40283666199416146 (2025-only: PASS).
- Baseline A definition verified: PASS
- B2E_v1 definition verified: PASS
- Sep 1–20 marked invalid: YES
- New final holdout start: 2026-09-22T00:00:00Z
- New final holdout end: 2026-10-03T23:00:00Z
- Stage-B evaluator complete: YES
- Old runner disabled: YES
- Holdout performance viewed: NO
- Full test suite at seal: 70 passed / 0 failed.
- Holdout performance currently locked: YES
- Official coverage requirement: Sep22–Oct3 only; no Oct4/Oct5 bars required.
- Late risk predictions: state/trading included; truncated 24h outcomes excluded.
- Cached-data completion: PASS; official runner fetches only missing contiguous hourly ranges after the release gate and aborts if any requested history remains incomplete.
- Direct reproducibility: `python -m pytest -q` and `python research/verify_b2e_freeze.py` work from repository root.

No Sep 21–Oct 3 data was downloaded, inspected, or evaluated during this
preflight.
