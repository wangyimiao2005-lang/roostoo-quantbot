# Holdout Invalidation Record

The attempted September B2E_v1 evaluation is invalid and must not be called an
untouched final holdout. The first execution used incorrect 2025 feature
normalization values. The discrepancy was discovered only after the September
output was visible. Applying corrected values in a rerun would change the
implementation after outcome observation and violates the frozen-final-holdout
protocol.

No September data was used in calibration, but frozen B2E reproduction failed.
All generated outputs are quarantined diagnostic artifacts only; no final
status, strategy selection, or production decision follows from them.
