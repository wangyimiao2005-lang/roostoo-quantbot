# ML Alpha Phase 3A

**Decision: MIXED — PREDICTIVE SIGNAL EXISTS BUT ECONOMIC EDGE IS INSUFFICIENT.** This isolated run used only 2025 for model/grid/gate choices and frozen 2026-01-01 to 2026-08-31 for evaluation; no files after 2026-09-01 were read.

Selected validation model: ridge `{"alpha": 1.0}`. The nonlinear model is a deterministic dependency-free boosted decision-stump ensemble because the installed scikit-learn binary is incompatible with the environment NumPy; no production dependency was added.

The primary economic table is `COMPETITION_14D_RESULTS.csv`; prediction diagnostics are `OOS_PREDICTIVE_DIAGNOSTICS.csv`; cost stress is `COST_STRESS.csv`. ML is promoted only when it improves mean matched 14-day net return after costs.

Best candidate by daily 14-day mean: TREE_RANKING; mean 0.42%, median 0.75%, positive probability 59.6%, matched P(beats A) 56.5%.
