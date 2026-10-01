# Phase 4 corrections

`funding_72h_mean` previously used nine forward-filled hourly values. Phase 4B does not reuse that feature; funding event means must be computed on raw settlements or a true 72h window. Phase 4 trend-continuation diagnostics included Sep 1–20; Phase 4B diagnostics and thresholds use only development and Jan–Aug OOS. Old Phase 4 artifacts were not overwritten.
