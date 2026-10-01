import pandas as pd
def risk_scale_targets(targets: pd.DataFrame, returns: pd.DataFrame, target_vol: float = .35, vol_floor: float = .05, bars_per_year: int = 8760) -> pd.DataFrame:
    vol = returns.rolling(48).std() * bars_per_year ** .5; scale = (target_vol / vol.clip(lower=vol_floor)).clip(upper=3.0)
    return targets * scale.shift(1).fillna(0.0)
