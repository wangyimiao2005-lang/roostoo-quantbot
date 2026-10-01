# Phase 3A.1 Report

**Decision: REJECT OHLCV-ONLY ML ALPHA.** Preprocessing is now fit exclusively on 2025 development data and `return_minus_market` is 24h-aligned. These fixes changed the clean Jan–Aug tree net return to 8.44%; this is not comparable to the original leaky result.

Fresh test: all 13 B1 assets, 2026-09-01 00:00 through 2026-09-20 23:00 UTC, with no Sep 21+ observations loaded. It has only seven overlapping daily-start 14-day windows, so it is robustness evidence, not independent confirmation. Tree remains exploratory; ridge is development-selected.

Fresh Tree net -3.81%, median 14d -3.38%, P(beat A) 100.0%. Fresh Ridge net -16.63%; filter net -3.18%; baseline net -7.46%. See cost stress for 5/10/15/20bps.
