import pandas as pd
from derivatives_alpha.phase4 import causal_funding_hourly
def test_no_future_funding_event_leaks_to_hour_before_event():
    i=pd.date_range('2025-01-01',periods=3,freq='h',tz='UTC'); assert causal_funding_hourly(pd.Series([1.],index=[i[1]]),i).iloc[0] != 1.
