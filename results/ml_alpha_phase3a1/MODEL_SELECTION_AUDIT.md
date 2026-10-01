# Model Selection Audit

Train: 2025-01-01–2025-09-30. Validation: 2025-10-01–2025-12-31. Selection statistic: mean daily Spearman IC.

| model   | params                                                        |   validation_mean_ic |
|:--------|:--------------------------------------------------------------|---------------------:|
| ridge   | {"alpha": 1.0}                                                |           0.00441949 |
| ridge   | {"alpha": 10.0}                                               |          -0.00149307 |
| tree    | {"iterations": 30, "learning_rate": 0.05, "max_features": 12} |          -0.0335643  |
| tree    | {"iterations": 50, "learning_rate": 0.05, "max_features": 16} |          -0.0281008  |

**Development-selected model: ridge**. Ridge was the development-selected model. Tree is labelled `EXPLORATORY_OOS_CHALLENGER` because its interest arose from the original OOS report rather than being promoted as a selected production candidate.
