import pandas as pd
from derivatives_alpha.phase4 import causal_funding_hourly

def test_funding_is_not_backfilled_before_publication():
    i=pd.date_range('2026-01-01',periods=5,freq='h',tz='UTC'); events=pd.Series([.001],index=[i[2]])
    out=causal_funding_hourly(events,i)
    assert out.iloc[:2].isna().all() and out.iloc[2:].eq(.001).all()
