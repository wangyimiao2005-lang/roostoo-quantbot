import pandas as pd
import pytest

from quant_competition.broker import PaperBroker
from quant_competition.live import RuntimeState
from quant_competition.live_data import CachedLiveProvider
from quant_competition.paper_runner import PaperRunner
from quant_competition.reconciliation import reconcile

SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]


def frames(last_by_symbol=None):
    idx=pd.date_range("2026-09-28", periods=73, freq="h", tz="UTC")
    out={}
    for j,s in enumerate(SYMS):
        use=idx if not last_by_symbol or s not in last_by_symbol else idx[:-1]
        base=100+j*10
        close=pd.Series([base+i*.05 for i in range(len(use))], index=use)
        out[s]=pd.DataFrame({"open":close,"high":close+1,"low":close-1,"close":close,"volume":1.0},index=use)
    return out


def test_mode_typo_cannot_enable_orders(tmp_path):
    p=CachedLiveProvider(frames()); b=PaperBroker(); st=RuntimeState(tmp_path/"s.sqlite")
    with pytest.raises(ValueError):
        PaperRunner(p,b,st,mode="PAPER")


def test_cross_asset_misalignment_halts(tmp_path):
    f=frames({"XRPUSDT":"short"}); p=CachedLiveProvider(f); b=PaperBroker(); st=RuntimeState(tmp_path/"s.sqlite")
    prices={s:float(f[s].close.iloc[-1]) for s in SYMS}
    now=pd.Timestamp("2026-10-01T01:05:00Z")
    r=PaperRunner(p,b,st,"DRY_RUN").run(SYMS,prices,now)
    assert r.status=="HALT_NEW_RISK" and "aligned" in r.reason


def test_execution_price_universe_mismatch_halts(tmp_path):
    f=frames(); p=CachedLiveProvider(f); b=PaperBroker(); st=RuntimeState(tmp_path/"s.sqlite")
    prices={s:float(f[s].close.iloc[-1]) for s in SYMS[:-1]}
    now=pd.Timestamp("2026-10-01T01:05:00Z")
    r=PaperRunner(p,b,st,"DRY_RUN").run(SYMS,prices,now)
    assert r.status=="HALT_NEW_RISK" and "universe mismatch" in r.reason


def test_post_trade_reconciliation_allows_only_one_exchange_lot_of_rounding():
    rules = {"BTC": {"amount_precision": 3, "min_order": 1.0}}
    prices = {"BTC": 100.0}
    tolerance = PaperRunner._reconciliation_tolerance(rules, prices, 1000.0)
    rounded = reconcile({"BTC": 0.5}, {"BTC": 4.9995}, prices, 1000.0, [], set(), tolerance)
    material = reconcile({"BTC": 0.5}, {"BTC": 4.998}, prices, 1000.0, [], set(), tolerance)
    assert rounded.status == "OK"
    assert material.status == "HALT_NEW_RISK"
    assert PaperRunner._reconciliation_tolerance({}, prices, 1000.0) == 1e-6


class _KlineResponse:
    def __init__(self, rows): self._rows=rows
    def raise_for_status(self): return None
    def json(self): return self._rows

class _KlineSession:
    def __init__(self, rows): self.rows=rows
    def get(self, *args, **kwargs): return _KlineResponse(self.rows)


def _kline(start):
    ts=pd.Timestamp(start)
    if ts.tzinfo is None: ts=ts.tz_localize("UTC")
    open_ms=int(ts.timestamp()*1000)
    close_ms=int((ts+pd.Timedelta(hours=1)-pd.Timedelta(milliseconds=1)).timestamp()*1000)
    return [open_ms,"100","101","99","100.5","10",close_ms,"0",1,"0","0","0"]


def test_binance_provider_filters_open_bar(tmp_path):
    from quant_competition.binance_live import BinanceCompetitionLiveProvider
    rows=[_kline("2026-10-01T00:00:00Z"), _kline("2026-10-01T01:00:00Z")]
    provider=BinanceCompetitionLiveProvider(
        bootstrap_dir=tmp_path/"empty", cache_dir=tmp_path/"cache", session=_KlineSession(rows)
    )
    provider.set_as_of(pd.Timestamp("2026-10-01T01:05:00Z"))
    frame=provider.get_recent_closed_bars("BTCUSDT")
    assert list(frame.index)==[pd.Timestamp("2026-10-01T00:00:00Z")]
