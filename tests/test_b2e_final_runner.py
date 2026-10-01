from datetime import timedelta

import pytest

import run_b2e_final_holdout as runner
import pandas as pd
import json
from b2e_freeze import ARTIFACT, HASH_FILE, load_and_verify_hash


def test_before_release_does_not_call_verifier(monkeypatch):
    called=False
    def forbidden():
        nonlocal called; called=True; raise AssertionError("verification should not run before release")
    monkeypatch.setattr(runner, "load_and_verify_hash", forbidden)
    with pytest.raises(RuntimeError, match="SEALED"):
        runner.preflight(runner.RELEASE-timedelta(seconds=1))
    assert not called


def test_date_lock_allows_release_with_mocked_gates(monkeypatch):
    x={"final_holdout":{"start":"2026-09-22T00:00:00Z","end":"2026-10-03T23:00:00Z","release":"2026-10-04T00:00:00Z"},"risk_multipliers":{"low":1.0,"medium":.75,"high":.5}}
    monkeypatch.setattr(runner,"load_and_verify_hash",lambda:x)
    monkeypatch.setattr(runner,"verify",lambda:{"hash":"test"})
    assert runner.preflight(runner.RELEASE)["verification"]["hash"] == "test"
    assert runner.preflight(runner.RELEASE+timedelta(seconds=1))["artifact"] is x


def test_wrong_holdout_date_aborts(monkeypatch):
    x={"final_holdout":{"start":"2026-09-21T00:00:00Z","end":"2026-10-03T23:00:00Z","release":"2026-10-04T00:00:00Z"},"risk_multipliers":{"low":1.0,"medium":.75,"high":.5}}
    monkeypatch.setattr(runner,"load_and_verify_hash",lambda:x)
    with pytest.raises(RuntimeError,match="dates"):
        runner.preflight(runner.RELEASE)


def test_official_coverage_ends_at_last_holdout_bar():
    index=pd.date_range(runner.START, runner.END, freq="h", inclusive="left")
    frames={symbol:pd.DataFrame(index=index) for symbol in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]}
    runner._coverage(frames)  # Oct4/Oct5 absence is deliberately irrelevant.


def test_late_risk_prediction_is_not_scored_but_is_a_state():
    late=runner.END-pd.Timedelta(hours=1)
    assert runner._risk_outcome_observable(late) is False
    assert late >= runner.START  # It remains an official performance/state row.


def test_last_observable_risk_prediction_uses_only_holdout_bars():
    assert runner._risk_outcome_observable(runner.END-pd.Timedelta(hours=25)) is True


@pytest.mark.parametrize("mutator", [
    lambda x: x.__setitem__("primary_cost_bps", 999),
    lambda x: x["risk_multipliers"].__setitem__("medium", .6),
    lambda x: x["baseline_strategy"].__setitem__("ema_fast", 9),
])
def test_modified_frozen_strategy_config_fails_hash_gate(tmp_path, mutator):
    payload=json.loads(ARTIFACT.read_text()); mutator(payload)
    path=tmp_path/"b2e_v1.json"; path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError,match="hash mismatch"):
        load_and_verify_hash(path,HASH_FILE)


def _toy_ohlcv(index):
    return pd.DataFrame(
        {
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        },
        index=pd.DatetimeIndex(index),
    )


def test_complete_cache_does_not_fetch_missing_history(tmp_path):
    start="2026-09-20T00:00:00Z"; end="2026-09-20T04:00:00Z"
    index=pd.date_range(start,end,freq="h",inclusive="left")
    cached=_toy_ohlcv(index)
    calls=[]
    def loader(symbol, requested_start, requested_end):
        assert (requested_start,requested_end)==(start,end)
        return cached
    def forbidden_fetch(*args):
        calls.append(args)
        raise AssertionError("complete cache must not trigger network fetch")
    result=runner._load_complete_history(
        "BTCUSDT",start,end,cached_loader=loader,gap_fetcher=forbidden_fetch,
        cache_path_factory=lambda *_: tmp_path/"unused.csv",
    )
    assert result.index.equals(index)
    assert calls == []


def test_missing_tail_fetches_only_missing_hours_and_persists_gap(tmp_path):
    start="2026-09-20T00:00:00Z"; end="2026-09-20T08:00:00Z"
    cached_index=pd.date_range(start,"2026-09-20T05:00:00Z",freq="h",inclusive="left")
    cached=_toy_ohlcv(cached_index)
    calls=[]
    def loader(*_):
        return cached
    def fetch(symbol, gap_start, gap_end):
        calls.append((symbol,pd.Timestamp(gap_start),pd.Timestamp(gap_end)))
        return _toy_ohlcv(pd.date_range(gap_start,gap_end,freq="h",inclusive="left"))
    result=runner._load_complete_history(
        "BTCUSDT",start,end,cached_loader=loader,gap_fetcher=fetch,
        cache_path_factory=lambda *_: tmp_path/"tail.csv",
    )
    expected=pd.date_range(start,end,freq="h",inclusive="left")
    assert result.index.equals(expected)
    assert calls == [("BTCUSDT",pd.Timestamp("2026-09-20T05:00:00Z"),pd.Timestamp("2026-09-20T08:00:00Z"))]
    persisted=pd.read_csv(tmp_path/"tail.csv",index_col="timestamp",parse_dates=True)
    assert len(persisted) == 3


def test_internal_cache_gap_fetches_only_contiguous_missing_range(tmp_path):
    start="2026-09-20T00:00:00Z"; end="2026-09-20T06:00:00Z"
    expected=pd.date_range(start,end,freq="h",inclusive="left")
    cached=_toy_ohlcv(expected.delete([2,3]))
    calls=[]
    def fetch(symbol, gap_start, gap_end):
        calls.append((pd.Timestamp(gap_start),pd.Timestamp(gap_end)))
        return _toy_ohlcv(pd.date_range(gap_start,gap_end,freq="h",inclusive="left"))
    result=runner._load_complete_history(
        "BTCUSDT",start,end,cached_loader=lambda *_:cached,gap_fetcher=fetch,
        cache_path_factory=lambda *_: tmp_path/"gap.csv",
    )
    assert result.index.equals(expected)
    assert calls == [(pd.Timestamp("2026-09-20T02:00:00Z"),pd.Timestamp("2026-09-20T04:00:00Z"))]


def test_unfilled_missing_history_aborts_instead_of_running_partial_holdout(tmp_path):
    start="2026-09-20T00:00:00Z"; end="2026-09-20T03:00:00Z"
    cached=_toy_ohlcv(pd.date_range(start,"2026-09-20T01:00:00Z",freq="h",inclusive="left"))
    empty=_toy_ohlcv(pd.DatetimeIndex([],tz="UTC"))
    with pytest.raises(RuntimeError,match="still missing"):
        runner._load_complete_history(
            "BTCUSDT",start,end,cached_loader=lambda *_:cached,gap_fetcher=lambda *_:empty,
            cache_path_factory=lambda *_: tmp_path/"none.csv",
        )
