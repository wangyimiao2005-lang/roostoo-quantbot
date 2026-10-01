import json
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import pytest

from quant_competition.broker import PaperBroker, RoostooBroker
from quant_competition.execution import executable_portfolio
from quant_competition.live import RuntimeState, frozen_targets
from quant_competition.live_data import CachedLiveProvider
from quant_competition.paper_runner import PaperRunner
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend

SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']


def _frames(root='data/raw'):
    out={}
    for s in SYMS:
        f=pd.read_csv(f'{root}/{s}_1h_2026-01-01_2026-09-01.csv',index_col='timestamp',parse_dates=True)
        f.index=pd.to_datetime(f.index,utc=True);out[s]=f
    return out


def test_true_research_live_target_and_timing_parity():
    frames=_frames(); closes=pd.DataFrame({s:f.close for s,f in frames.items()})
    ref=enforce_exposure_limits(risk_scale_targets(MultiHorizonTrend(8,24).target_weights(closes),closes.pct_change()))
    policy=ExecutionPolicy('Rebalance24h',rebalance_every=24).apply(ref).shift(1).fillna(0)
    for i in [48+24*k for k in range(30)]:
        assert closes.index[i].hour==0 and closes.index[i+1].hour==1
        live=frozen_targets(closes.iloc[:i+1])
        assert np.allclose(live.values,ref.iloc[i].values,atol=1e-10,rtol=0)
        assert np.allclose(policy.iloc[i+1].values,ref.iloc[i].values,atol=1e-10,rtol=0)


def test_executable_target_reserves_cash_and_collateral():
    current={'BTC':0.2,'ETH':-1.0}; weights={'BTC':-.35,'ETH':-.35,'SOL':-.30}; prices={'BTC':100.,'ETH':100.,'SOL':100.}
    w,d,scale,fees=executable_portfolio(current,weights,prices,1000,10,free_cash=300,short_collateral={'ETH':100},short_entry={'ETH':100})
    assert scale < 1
    assert sum(abs(d[a])*prices[a] for a in d) <= 1000


def test_short_accounting_locks_collateral_and_marks_equity():
    b=PaperBroker(1000,10);r=b.open_short('BTC/USD',500,100);assert r['Success']
    snap=b.account_snapshot({'BTC/USD':100});assert np.isclose(snap.free_cash,499.5);assert np.isclose(snap.locked_cash,500);assert np.isclose(snap.total_equity,999.5)
    b.close_short('BTC/USD',2.5,80);snap=b.account_snapshot({'BTC/USD':80});assert np.isclose(snap.short_collateral,250);assert snap.free_cash>700


class CrashOnceBroker(PaperBroker):
    def __init__(self,*a,**k): super().__init__(*a,**k);self.did_crash=False
    def place_long_order(self,*a,**k):
        result=super().place_long_order(*a,**k)
        if result.get('Success') and not self.did_crash:
            self.did_crash=True
            raise RuntimeError('injected crash after fill')
        return result


def test_crash_after_fill_resumes_without_duplicate(tmp_path):
    frames=_frames();i=72;provider=CachedLiveProvider({s:f.iloc[:i+1] for s,f in frames.items()});prices={s:float(f.open.iloc[i+1]) for s,f in frames.items()};now=frames['BTCUSDT'].index[i+1]+pd.Timedelta(minutes=2)
    broker=CrashOnceBroker(100000,10);state=RuntimeState(tmp_path/'state.sqlite');runner=PaperRunner(provider,broker,state,'LOCAL_PAPER')
    with pytest.raises(RuntimeError): runner.run(SYMS,prices,now)
    pre_orders=len(broker.orders);assert pre_orders==1
    result=PaperRunner(provider,broker,state,'LOCAL_PAPER').run(SYMS,prices,now);assert result.status=='RECONCILED'
    payload=state.get_rebalance(result.rebalance_id);assert payload['status']=='COMPLETED'
    desired=payload['payload']['desired_quantities']; positions={k.split('/')[0]:v for k,v in broker.get_positions().items()}
    for a,q in desired.items(): assert np.isclose(positions.get(a,0),q,atol=1e-10)
    # The already-filled first action was recognized from broker state, not submitted twice.
    assert len(broker.orders)==5


class FakeResponse:
    def __init__(self,payload): self.payload=payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class FakeSession:
    def __init__(self): self.calls=[]
    def request(self,method,url,params=None,data=None,headers=None,timeout=None):
        self.calls.append(dict(method=method,path=urlparse(url).path,params=params,data=data,headers=headers or {}))
        path=urlparse(url).path
        if path=='/v3/serverTime': return FakeResponse({'ServerTime':1700000000000})
        if path=='/v3/ticker': return FakeResponse({'Success':True,'ErrMsg':'','Data':{'BTC/USD':{'LastPrice':100,'MaxBid':99,'MinAsk':101}}})
        if path=='/v3/balance': return FakeResponse({'Success':True,'ErrMsg':'','SpotWallet':{'USD':{'Free':300,'Lock':100,'PendingOrders':0,'ShortCollateral':200},'BTC':{'Free':1,'Lock':0}},'MarginWallet':{}})
        if path=='/v6/short_positions': return FakeResponse({'Success':True,'Positions':[{'ID':7,'Pair':'ETH/USD','EntryPrice':100,'ShortQty':2,'Collateral':200,'UnrealizedPNL':10}]})
        if path=='/v3/query_order':
            if data and 'pending_only=TRUE' in data:return FakeResponse({'Success':False,'ErrMsg':'no order matched'})
            return FakeResponse({'Success':True,'OrderMatched':[{'OrderID':81,'Pair':'BTC/USD','Status':'FILLED','FilledQuantity':1,'FilledAverPrice':100,'CommissionChargeValue':.1}]})
        if path=='/v3/place_order': return FakeResponse({'Success':True,'OrderDetail':{'OrderID':81,'Pair':'BTC/USD','Status':'FILLED','FilledQuantity':1,'FilledAverPrice':100,'CommissionChargeValue':.1}})
        if path=='/v6/short_open': return FakeResponse({'Success':True,'ID':9,'Pair':'ETH/USD','Status':'OPEN','ShortQty':1,'EntryPrice':100,'OpenFee':.1,'Collateral':100})
        if path=='/v6/short_close': return FakeResponse({'Success':True,'ClosePrice':100,'ClosedQty':1,'CloseFee':.1,'RealizedPNL':0,'FullyClosed':True})
        if path=='/v3/exchangeInfo': return FakeResponse({'IsRunning':True,'TradePairs':{}})
        if path=='/v3/pending_count': return FakeResponse({'Success':False,'ErrMsg':'no pending order under this account','TotalPending':0,'OrderPairs':{}})
        if path=='/v3/cancel_order': return FakeResponse({'Success':True,'CanceledList':[81]})
        raise AssertionError(path)


def test_roostoo_contract_paths_auth_and_normalization():
    sess=FakeSession();b=RoostooBroker('https://mock-api.roostoo.com','k','s',sess);b.server_time_offset_ms=0
    tick=b.get_tickers();call=sess.calls[-1];assert call['path']=='/v3/ticker' and 'timestamp' in call['params'] and 'MSG-SIGNATURE' not in call['headers'] and 'BTC/USD' in tick
    balances=b.get_balances();call=sess.calls[-1];assert call['path']=='/v3/balance' and 'MSG-SIGNATURE' in call['headers'] and balances['BTC']==1
    assert b.get_pending_orders()==[];assert 'pending_only=TRUE' in sess.calls[-1]['data']
    order=b.place_long_order('BTC/USD','BUY',1);assert order['OrderID']=='81'
    short=b.open_short('ETH/USD',100);assert short['OrderID']=='9' and short['FilledQuantity']==1 and short['Collateral']==100 and short['Fee']==.1
    closed=b.close_short('ETH/USD',1);assert closed['Side']=='SHORT_CLOSE' and closed['FilledQuantity']==1 and closed['FullyClosed']
    positions=b.get_positions();assert positions['BTC/USD']==1 and positions['ETH/USD']==-2
    snap=b.account_snapshot({'BTC/USD':100,'ETH/USD':100});assert snap.total_equity==710 and snap.short_collateral==200


def test_roostoo_live_2026_balance_schema_and_short_equity():
    """Regression for the live General/Test payload verified on 2026-10-01."""
    sess=FakeSession(); b=RoostooBroker('https://mock-api.roostoo.com','k','s',sess)
    snap=b.account_snapshot({'BTC/USD':100,'ETH/USD':100})
    assert snap.free_cash==300
    assert snap.locked_cash==100
    assert snap.long_positions=={'BTC/USD':1}
    assert snap.short_positions=={'ETH/USD':2}
    assert snap.short_collateral==200
    assert snap.short_collateral_by_symbol=={'ETH/USD':200}
    assert snap.short_entry_prices=={'ETH/USD':100}
    assert snap.short_unrealized_pnl==10
    assert snap.total_equity==710


class CollateralMismatchSession(FakeSession):
    def request(self,method,url,params=None,data=None,headers=None,timeout=None):
        path=urlparse(url).path
        if path=='/v3/balance':
            return FakeResponse({'Success':True,'ErrMsg':'','SpotWallet':{'USD':{'Free':300,'Lock':0,'ShortCollateral':250}},'MarginWallet':{}})
        if path=='/v6/short_positions':
            return FakeResponse({'Success':True,'Positions':[{'ID':7,'Pair':'ETH/USD','EntryPrice':100,'ShortQty':2,'Collateral':200,'UnrealizedPNL':0}]})
        return super().request(method,url,params=params,data=data,headers=headers,timeout=timeout)


def test_roostoo_collateral_source_disagreement_halts():
    b=RoostooBroker('https://mock-api.roostoo.com','k','s',CollateralMismatchSession())
    with pytest.raises(RuntimeError, match='short collateral mismatch'):
        b.account_snapshot({'ETH/USD':100})
