import pandas as pd
def enforce_exposure_limits(weights: pd.DataFrame, max_asset: float = .35, max_gross: float = 1.0) -> pd.DataFrame:
    out = weights.clip(-max_asset, max_asset); gross = out.abs().sum(axis=1)
    return out.div((gross / max_gross).clip(lower=1.0), axis=0)
