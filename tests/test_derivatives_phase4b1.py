import pandas as pd
import numpy as np
import pytest

from derivatives_alpha_phase4b.phase4b1 import (
    assert_pre_sep, rolling_weighted_imbalance, funding_mean_hourly,
    fit_thresholds, component_masks, backtest_targets,
)


def test_phase4b1_rejects_sep_rows():
    x = pd.DataFrame({'a':[1.,2.]}, index=pd.to_datetime(['2026-08-31 23:00Z','2026-09-01 00:00Z']))
    with pytest.raises(ValueError):
        assert_pre_sep(x)


def test_weighted_imbalance_uses_rolling_quote_volume():
    idx=pd.date_range('2025-01-01', periods=4, freq='h', tz='UTC')
    total=pd.DataFrame({'A':[10.,20.,30.,40.]},index=idx)
    buy=pd.DataFrame({'A':[10.,0.,30.,0.]},index=idx)
    got=rolling_weighted_imbalance(buy,total,4).iloc[-1,0]
    expected=(2*(10+0+30+0)-(10+20+30+40))/(10+20+30+40)
    assert got == pytest.approx(expected)


def test_funding_72h_is_actual_72_hour_window():
    idx=pd.date_range('2025-01-01', periods=72, freq='h', tz='UTC')
    x=pd.DataFrame({'A':np.arange(72,dtype=float)},index=idx)
    got=funding_mean_hourly(x,72).iloc[-1,0]
    assert got == pytest.approx(np.arange(72).mean())


def test_thresholds_use_only_calibration_rows():
    idx=pd.date_range('2025-01-01',periods=10,freq='h',tz='UTC')
    base=pd.DataFrame({'A':range(10)},index=idx,dtype=float)
    mask=np.array([True]*5+[False]*5)
    t1=fit_thresholds(base,base,base,mask)
    altered=base.copy(); altered.iloc[5:]=1e9
    t2=fit_thresholds(altered,altered,altered,mask)
    assert t1==t2


def test_component_filters_are_direction_aware():
    idx=pd.date_range('2025-01-01',periods=2,freq='h',tz='UTC')
    trend=pd.DataFrame({'A':[1.,-1.]},index=idx)
    flow=pd.DataFrame({'A':[-1.,1.]},index=idx)
    premium=pd.DataFrame({'A':[1.,-1.]},index=idx)
    funding=pd.DataFrame({'A':[1.,-1.]},index=idx)
    from derivatives_alpha_phase4b.phase4b1 import Thresholds
    t=Thresholds(-.5,.5,-.5,.5,-.5,.5)
    m=component_masks(trend,flow,premium,funding,t)
    assert not m['FLOW'].any().any()
    assert not m['PREMIUM'].any().any()
    assert not m['FUNDING'].any().any()


def test_cost_rebacktest_preserves_gross_path_for_same_targets():
    idx=pd.date_range('2025-01-01',periods=60,freq='h',tz='UTC')
    op=pd.DataFrame({'A':100.},index=idx)
    cl=op.copy(); cl.loc[idx[1::2],'A']=101.
    tar=pd.DataFrame({'A':1.},index=idx)
    r5=backtest_targets(op,cl,tar,5)
    r20=backtest_targets(op,cl,tar,20)
    pd.testing.assert_series_equal(r5.gross_returns,r20.gross_returns)
    assert r20.costs.sum() > r5.costs.sum()
