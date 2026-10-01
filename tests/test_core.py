import numpy as np
import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.backtest.costs import transaction_costs
from quant_competition.data.validation import validate_ohlcv
from quant_competition.metrics.drawdown import drawdown
from quant_competition.portfolio.exposure import enforce_exposure_limits
from quant_competition.portfolio.execution_policy import ExecutionPolicy
from quant_competition.data.resample import resample_ohlcv
from quant_competition.strategies import StateTrend
from quant_competition.broker import PaperBroker,canonical_params,sign_params
from quant_competition.live_data import CachedLiveProvider
from quant_competition.live import frozen_targets,RuntimeState,rebalance_id
from quant_competition.symbols import asset_from_research,broker_from_asset,asset_from_broker
from quant_competition.paper_runner import PaperRunner
from quant_competition.execution import plan_orders
def test_signal_is_filled_next_bar_not_same_bar():
    idx=pd.date_range("2025-01-01",periods=3,freq="h",tz="UTC"); o=pd.DataFrame({"BTC":[100,100,100]},index=idx); c=pd.DataFrame({"BTC":[100,110,100]},index=idx); t=pd.DataFrame({"BTC":[1,0,0]},index=idx)
    r=run_backtest(o,c,t,0,0); assert r.returns.iloc[0] == 0 and np.isclose(r.returns.iloc[1], .1)
def test_cost_is_paid_on_weight_change(): assert np.allclose(transaction_costs(pd.DataFrame({"x":[1.,-2.]}),10).values,[.001,.002])
def test_short_pnl():
    idx=pd.date_range("2025-01-01",periods=3,freq="h",tz="UTC"); o=pd.DataFrame({"x":[100,100,100]},index=idx); c=pd.DataFrame({"x":[100,90,100]},index=idx); t=pd.DataFrame({"x":[-1,0,0]},index=idx); assert run_backtest(o,c,t,0,0).returns.iloc[1] > 0
def test_exposure_cap(): assert enforce_exposure_limits(pd.DataFrame([[2.,2.]],columns=["a","b"]),.8,1).abs().sum(axis=1).iloc[0] <= 1
def test_drawdown(): assert np.isclose(drawdown(pd.Series([.1,-.2])).iloc[-1], -.2)
def test_quality_detects_duplicate():
    idx=pd.DatetimeIndex([pd.Timestamp("2025-01-01",tz="UTC")]*2); f=pd.DataFrame({"open":[1,1],"high":[1,1],"low":[1,1],"close":[1,1],"volume":[1,1]},index=idx); assert validate_ohlcv(f,"1h").duplicates == 1
def test_immediate_policy_reproduces_zero_buffer_baseline():
    idx=pd.date_range("2025-01-01",periods=4,freq="h",tz="UTC"); target=pd.DataFrame({"x":[.2,.8,-.2,0]},index=idx); o=pd.DataFrame({"x":[100]*4},index=idx); c=o.copy()
    a=run_backtest(o,c,target,0,0); b=run_backtest(o,c,target,0,execution_policy=ExecutionPolicy()); assert np.allclose(a.weights,b.weights)
def test_scheduled_rebalance_holds_between_dates():
    idx=pd.date_range("2025-01-01",periods=5,freq="h",tz="UTC"); target=pd.DataFrame({"x":[1,0,-1,0,1]},index=idx); actual=ExecutionPolicy(rebalance_every=2).apply(target); assert actual.iloc[1,0] == actual.iloc[0,0] and actual.iloc[3,0] == actual.iloc[2,0]
def test_buffer_and_partial_rebalance():
    idx=pd.date_range("2025-01-01",periods=3,freq="h",tz="UTC"); target=pd.DataFrame({"x":[.1,.12,.9]},index=idx)
    assert ExecutionPolicy(absolute_buffer=.05).apply(target).iloc[1,0] == .1
    assert np.isclose(ExecutionPolicy(partial_lambda=.5).apply(target).iloc[0,0],.05)
def test_smoothing_and_minimum_hold():
    idx=pd.date_range("2025-01-01",periods=4,freq="h",tz="UTC"); target=pd.DataFrame({"x":[1,0,0,0]},index=idx)
    assert np.isclose(ExecutionPolicy(smoothing_alpha=.5).apply(target).iloc[0,0],.5)
    assert ExecutionPolicy(minimum_holding_bars=2).apply(target).iloc[1,0] == 1
def test_state_trend_hysteresis_persists_until_exit():
    idx=pd.date_range('2025-01-01',periods=80,freq='h',tz='UTC'); price=pd.DataFrame({'x':np.r_[np.ones(40),np.linspace(1,3,40)]},index=idx); state=StateTrend(2,6,.25,0).target_weights(price); assert state.iloc[-1,0] == 1
def test_resample_is_completed_bar_aggregation():
    idx=pd.date_range('2025-01-01',periods=5,freq='h',tz='UTC'); f=pd.DataFrame({'open':range(5),'high':range(5),'low':range(5),'close':range(5),'volume':1},index=idx); out=resample_ohlcv(f,'4h'); assert out.iloc[-1]['close'] == 4
def test_paper_broker_fill_reconciles_cash_and_position():
    b=PaperBroker(1000,10); result=b.place_order('BTC/USD','BUY',1,100); assert result['Success'] and b.get_open_positions()['BTC/USD']==1 and np.isclose(b.get_balances()['USD'],899.9)
def test_roostoo_signing_is_sorted_and_deterministic():
    p={'side':'BUY','timestamp':1580774512000,'pair':'BNB/USD','quantity':2000,'type':'MARKET'}
    assert canonical_params(p)=='pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET'
    assert sign_params('S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep',p)=='20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff'
def test_live_health_rejects_stale_bars():
    idx=pd.date_range('2025-01-01',periods=60,freq='h',tz='UTC'); f=pd.DataFrame({'open':1.,'high':1.,'low':1.,'close':1.,'volume':1.},index=idx); assert CachedLiveProvider({'x':f}).validate(f,pd.Timestamp('2025-01-03',tz='UTC')).status=='HALT_NEW_RISK'
def test_frozen_target_streaming_parity():
    idx=pd.date_range('2025-01-01',periods=60,freq='h',tz='UTC'); p=pd.DataFrame({'a':np.linspace(100,140,60),'b':np.linspace(200,180,60)},index=idx); assert np.allclose(frozen_targets(p),frozen_targets(p.iloc[:60]))
def test_runtime_state_persists_and_deduplicates(tmp_path):
    p=tmp_path/'state.sqlite'; s=RuntimeState(p);s.record('r1','payload');s.db.close();s=RuntimeState(p);assert s.already_seen('r1');s.record('r1','other');assert s.db.execute('select count(*) from runs').fetchone()[0]==1
def test_symbol_mapping_is_explicit():assert asset_from_broker(broker_from_asset(asset_from_research('BTCUSDT')))=='BTC'
def test_paper_short_profit_and_no_negative_cash():
    b=PaperBroker(1000,10);b.open_short('BTC/USD',100,100);b.close_short('BTC/USD',1,80);assert b.short.get('BTC/USD',0)==0 and b.cash>=0 and b.realized_pnl>0
def test_paper_short_locks_and_releases_collateral():
    b=PaperBroker(1000,10);b.open_short('BTC/USD',500,100);assert np.isclose(b.cash,499.5) and np.isclose(b.short_collateral['BTC/USD'],500);b.close_short('BTC/USD',2.5,80);assert np.isclose(b.short_collateral['BTC/USD'],250)
def test_local_paper_multi_rebalance_and_equity(tmp_path):
    # Signal bar must be 00:00 and becomes effective at 01:00, matching frozen research shift(1).
    idx=pd.date_range('2025-01-01 00:00',periods=98,freq='h',tz='UTC'); frames={}
    for i,symbol in enumerate(['BTCUSDT','ETHUSDT']):
        wave=np.sin(np.arange(len(idx))/5+i)+np.arange(len(idx))*.01
        close=pd.Series(100+i*10+wave,index=idx);frames[symbol]=pd.DataFrame({'open':close,'high':close,'low':close,'close':close,'volume':1.})
    broker=PaperBroker(10000,10);state=RuntimeState(tmp_path/'state.db')
    for signal_i in (48,72,96):
        provider=CachedLiveProvider({s:f.iloc[:signal_i+1] for s,f in frames.items()});prices={s:float(f.open.iloc[signal_i+1]) for s,f in frames.items()}
        result=PaperRunner(provider,broker,state,'LOCAL_PAPER').run(list(frames),prices,idx[signal_i+1]+pd.Timedelta(minutes=2))
        assert result.status=='RECONCILED'
    bp={s.replace('USDT','/USD'):float(f.open.iloc[97]) for s,f in frames.items()}
    assert broker.equity(bp)>0

def test_order_plan_is_reduction_first_and_short_delta_correct():
    p=plan_orders({'BTC':1.,'ETH':-.1},{'BTC':-.2,'ETH':-.06}); assert [x.action for x in p]==['SELL_LONG','CLOSE_SHORT','OPEN_SHORT'] and np.isclose(p[-1].quantity,.2)
def test_cross_zero_plan_does_not_open_preclose_delta():
    p=plan_orders({'BTC':-.1},{'BTC':.1}); assert [(x.action,round(x.quantity,3)) for x in p]==[('CLOSE_SHORT',.1),('BUY_LONG',.1)]
