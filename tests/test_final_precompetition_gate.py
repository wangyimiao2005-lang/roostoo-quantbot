from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import run_final_precompetition_gate as gate_runner
from quant_competition.competition_selection import (
    BASELINE, FUNDING, competition_targets, load_active_strategy, load_gate_manifest,
)
from quant_competition.funding_provider import BinanceUSDMFundingProvider, FROZEN_SYMBOLS, RELEASE


class FakeResponse:
    def __init__(self, rows): self._rows = rows
    def raise_for_status(self): pass
    def json(self): return self._rows


class FakeSession:
    def __init__(self, rows=None): self.calls=[]; self.rows=rows or []
    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse(self.rows)


def test_gate_manifest_is_hash_locked():
    gate = load_gate_manifest()
    assert gate["decision"]["if_all_rules_pass"] == FUNDING
    assert gate["decision"]["otherwise"] == BASELINE
    assert gate["decision_rules"]["funding_net_return_10bps_must_be_positive"] is True


def test_pre_release_gate_stops_before_market_data(monkeypatch):
    called=[]
    monkeypatch.setattr(gate_runner, "load_gate_manifest", lambda: called.append("manifest") or {})
    with pytest.raises(RuntimeError, match="SEALED"):
        gate_runner.preflight(gate_runner.RELEASE - timedelta(seconds=1))
    assert called == []


def test_funding_provider_makes_zero_http_calls_before_release(tmp_path):
    session=FakeSession()
    provider=BinanceUSDMFundingProvider(cache_dir=tmp_path, session=session,
        clock=lambda: RELEASE.to_pydatetime()-timedelta(seconds=1))
    with pytest.raises(RuntimeError, match="SEALED"):
        provider(FROZEN_SYMBOLS, RELEASE-pd.Timedelta(hours=1))
    assert session.calls == []


def test_funding_provider_never_returns_after_cutoff(tmp_path):
    cutoff=pd.Timestamp("2026-10-04T08:00:00Z")
    rows=[
        {"symbol":"BTCUSDT","fundingTime":int(pd.Timestamp("2026-10-04T00:00:00Z").timestamp()*1000),"fundingRate":"0.0001"},
        {"symbol":"BTCUSDT","fundingTime":int(pd.Timestamp("2026-10-04T08:00:00Z").timestamp()*1000),"fundingRate":"0.0002"},
        {"symbol":"BTCUSDT","fundingTime":int(pd.Timestamp("2026-10-04T16:00:00Z").timestamp()*1000),"fundingRate":"0.999"},
    ]
    session=FakeSession(rows)
    provider=BinanceUSDMFundingProvider(cache_dir=tmp_path, session=session,
        clock=lambda: pd.Timestamp("2026-10-05T00:00:00Z").to_pydatetime(), sleep_fn=lambda _:None)
    ev=provider.events("BTCUSDT",pd.Timestamp("2026-10-03T00:00:00Z"),cutoff)
    assert ev.index.max() <= cutoff
    assert 0.999 not in ev.funding_rate.tolist()


def test_active_strategy_defaults_to_frozen_baseline_when_no_selection(tmp_path):
    missing=tmp_path/"ACTIVE_STRATEGY.json"
    selected=load_active_strategy(missing)
    assert selected["selected_strategy"] == BASELINE


def test_competition_targets_baseline_path_does_not_need_funding():
    idx=pd.date_range("2026-10-04", periods=80, freq="h", tz="UTC")
    closes=pd.DataFrame({s:range(100,180) for s in FROZEN_SYMBOLS},index=idx,dtype=float)
    target=competition_targets(closes, selection={"selected_strategy":BASELINE})
    assert set(target.index)==set(FROZEN_SYMBOLS)


def test_gate_checks_require_profit_not_just_less_loss():
    gate=load_gate_manifest()
    m10=pd.DataFrame([
        {"strategy":BASELINE,"net_return":-0.08,"max_drawdown":-0.10},
        {"strategy":FUNDING,"net_return":-0.04,"max_drawdown":-0.06},
    ])
    m15=pd.DataFrame([
        {"strategy":BASELINE,"net_return":-0.09,"max_drawdown":-0.11},
        {"strategy":FUNDING,"net_return":-0.05,"max_drawdown":-0.07},
    ])
    loo=pd.DataFrame({"funding_beats_baseline":[True]*5})
    blocks=pd.DataFrame({"incremental_return":[.01,.01,.01,.01]})
    checks=gate_runner.gate_checks(m10,m15,loo,blocks,gate)
    lookup=checks.set_index("check")["pass"]
    assert bool(lookup["funding_beats_baseline_10bps"]) is True
    assert bool(lookup["funding_net_return_10bps_positive"]) is False
    assert bool(checks["pass"].all()) is False


def test_active_strategy_hash_rejects_manual_edit(tmp_path):
    path=tmp_path/"ACTIVE_STRATEGY.json"
    path.write_text(json.dumps({"selected_strategy":FUNDING}))
    path.with_suffix(".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest()+"  "+path.name+"\n")
    assert load_active_strategy(path)["selected_strategy"] == FUNDING
    path.write_text(json.dumps({"selected_strategy":BASELINE}))
    with pytest.raises(RuntimeError, match="hash mismatch"):
        load_active_strategy(path)
