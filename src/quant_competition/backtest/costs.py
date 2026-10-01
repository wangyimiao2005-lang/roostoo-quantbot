import pandas as pd
def transaction_costs(weight_changes: pd.DataFrame, cost_bps_per_side: float) -> pd.Series:
    return weight_changes.abs().sum(axis=1) * cost_bps_per_side / 10_000
