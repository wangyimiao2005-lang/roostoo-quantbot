from __future__ import annotations
import numpy as np
import pandas as pd

def causal_funding_hourly(events: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Funding published at t is usable from t onward, never filled backward."""
    e=events.sort_index().loc[lambda x: ~x.index.duplicated(keep='last')]
    return e.reindex(index.union(e.index)).sort_index().ffill().reindex(index)

def future_return(opens: pd.DataFrame, closes: pd.DataFrame, horizon=24):
    return closes.shift(-horizon).div(opens.shift(-1)).sub(1)

def coverage_row(asset, variable, series, expected, provider='Binance Futures'):
    x=series.dropna(); gaps=x.index.to_series().diff().dt.total_seconds().div(3600).sub(1)
    return {'asset':asset,'variable':variable,'first_timestamp':x.index.min(),'last_timestamp':x.index.max(),'expected_observations':expected,'actual_observations':len(x),'coverage_pct':len(x)/expected*100,'missing_pct':(1-len(x)/expected)*100,'maximum_gap_hours':max(float(gaps.max() or 0),0),'provider':provider,'usable':len(x)/expected>=.95}
