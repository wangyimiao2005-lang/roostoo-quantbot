import numpy as np
import pandas as pd
from ml_alpha.phase3a import FrozenPreprocessor, build_features, build_labels, rank_targets, rolling_14d

def test_future_label_uses_next_open_and_future_close():
    i=pd.date_range("2025-01-01",periods=5,freq="h",tz="UTC"); o=pd.DataFrame({"A":[10,20,30,40,50]},index=i); c=pd.DataFrame({"A":[11,21,31,41,51]},index=i)
    assert np.isclose(build_labels(o,c,2).loc[(i[0],"A"),"future_return"],31/20-1)
def test_cross_sectional_ranking_is_market_neutral():
    i=pd.MultiIndex.from_product([[pd.Timestamp("2025-01-01",tz="UTC")],["A","B","C","D","E","F"]],names=["timestamp","symbol"]); t=rank_targets(pd.Series([1,2,3,4,5,6],index=i)); assert np.isclose(t.iloc[0].sum(),0) and np.isclose(t.iloc[0].abs().sum(),1)
def test_14d_windows_are_daily_and_deterministic():
    i=pd.date_range("2025-01-01",periods=24*15,freq="h",tz="UTC"); x=pd.Series(0.,index=i); assert len(rolling_14d(x,x,x,"daily"))==2 and len(rolling_14d(x,x,x,"nonoverlap"))==1
def test_preprocessing_is_fitted_only_on_development():
    dev=pd.DataFrame({"x":[0.,1.,2.]}); oos=pd.DataFrame({"x":[999.]}); p=FrozenPreprocessor.fit(dev); assert p.upper.x==1.98 and p.transform(oos).iloc[0,0]==1.98
def test_return_minus_market_uses_24h_market_horizon():
    i=pd.date_range("2025-01-01",periods=26,freq="h",tz="UTC"); c=pd.DataFrame({"BTCUSDT":np.arange(100,126),"ETHUSDT":np.arange(100,152,2)},index=i); f=build_features(c,c,c,c,pd.DataFrame(1.,index=i,columns=c.columns)); assert f.loc[(i[-1],"ETHUSDT"),"return_minus_market"] > 0
