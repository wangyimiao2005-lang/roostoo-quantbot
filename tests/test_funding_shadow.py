import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_competition.funding_shadow import (
    FundingShadowRuntime,
    causal_funding_mean,
    load_funding_shadow_manifest,
    phase4b1_baseline_targets,
)
from quant_competition.live import frozen_targets
from quant_competition.paper_runner import PaperRunner


SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def frames(periods=80):
    idx = pd.date_range("2026-10-05", periods=periods, freq="h", tz="UTC")
    # A rising signal history makes the scheduled Trend target non-zero; the final
    # execution bar has a distinct move to prove no same-bar signal return is used.
    close = pd.DataFrame({s: np.linspace(100, 180, periods) for s in SYMS}, index=idx)
    op = close.shift(1).bfill()
    return idx, op, close, pd.DataFrame(0.0, index=idx, columns=SYMS)


def runtime(tmp_path):
    return FundingShadowRuntime(
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "ledger.csv",
        summary_path=tmp_path / "summary.md",
    )


def test_funding_configuration_is_immutable_after_freeze(tmp_path):
    root_manifest = load_funding_shadow_manifest()
    assert root_manifest["status"] == "EXPERIMENTAL_SHADOW_ONLY"
    source = __import__("pathlib").Path("frozen/funding_shadow/FUNDING_SHADOW_FREEZE_MANIFEST.json")
    copied = tmp_path / source.name
    copied.write_text(source.read_text())
    copied.with_suffix(".sha256").write_text(source.with_suffix(".sha256").read_text())
    payload = json.loads(copied.read_text())
    payload["funding_thresholds"]["high"] = 1.0
    copied.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="hash mismatch"):
        FundingShadowRuntime(manifest_path=copied, state_path=tmp_path / "s", ledger_path=tmp_path / "l", summary_path=tmp_path / "m")


def test_shadow_runtime_has_no_order_routing_surface(tmp_path):
    shadow = runtime(tmp_path)
    assert not hasattr(shadow, "broker")
    assert not any(hasattr(shadow, name) for name in ("place_order", "place_long_order", "open_short", "close_short"))


def test_funding_feature_is_causal():
    idx, _, _, funding = frames(74)
    funding.loc[idx[-1], :] = 99.0  # Future relative to the selected completed bar.
    value = causal_funding_mean(funding, idx[-2], 72)
    assert (value == 0.0).all()


def test_observer_uses_next_bar_and_never_rewrites_ledger(tmp_path):
    idx, op, close, funding = frames()
    shadow = runtime(tmp_path)
    execution = idx[49]  # 01:00; its signal bar is the preceding completed 00:00 bar.
    assert execution.hour == 1
    assert shadow.observe(execution, op, close, funding) == "RECORDED"
    ledger = pd.read_csv(tmp_path / "ledger.csv")
    assert len(ledger) == len(SYMS)
    assert set(pd.to_datetime(ledger.timestamp, utc=True).dt.hour) == {1}
    expected_target = phase4b1_baseline_targets(close.loc[close.index <= idx[48]])
    next_bar_return = close.loc[execution].div(op.loc[execution]).sub(1)
    first = ledger.set_index("symbol").loc[SYMS[0]]
    expected = expected_target[SYMS[0]] * next_bar_return[SYMS[0]] - abs(expected_target[SYMS[0]]) * .001
    assert first.baseline_return == pytest.approx(expected)
    # A repeat is idempotent: neither the append-only ledger nor state history changes.
    before = (tmp_path / "ledger.csv").read_bytes()
    assert shadow.observe(execution, op, close, funding) == "ALREADY_PROCESSED"
    assert (tmp_path / "ledger.csv").read_bytes() == before
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_processed_timestamp"].startswith(execution.isoformat())


def test_production_targets_and_frozen_baseline_are_unchanged(tmp_path):
    idx, op, close, funding = frames()
    before_target = frozen_targets(close.iloc[:49]).copy()
    frozen = __import__("pathlib").Path("frozen/b2e_v1.json")
    threshold = __import__("pathlib").Path("results/derivatives_phase4b1/five_asset_baseline/PHASE4B1_THRESHOLDS.json")
    before_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (frozen, threshold)]
    shadow = runtime(tmp_path)
    shadow.observe(idx[49], op, close, funding)
    pd.testing.assert_series_equal(before_target, frozen_targets(close.iloc[:49]))
    assert before_hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in (frozen, threshold)]


def test_first_catchup_arms_without_backfilling_then_settles_all_new_hours(tmp_path):
    idx, op, close, funding = frames(97)  # Oct 5 00:00 through Oct 9 00:00.
    shadow = runtime(tmp_path)
    first_cut = idx[48]  # Oct 7 00:00, safely after the sealed-holdout release.
    status = shadow.catch_up_completed(
        op.loc[:first_cut], close.loc[:first_cut], funding.loc[:first_cut]
    )
    assert status == "ARMED_FORWARD_ONLY"
    assert pd.read_csv(tmp_path / "ledger.csv").empty
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["armed_timestamp"].startswith(first_cut.isoformat())
    assert state["last_processed_timestamp"].startswith(first_cut.isoformat())

    second_cut = idx[72]  # Exactly 24 completed hours later.
    status = shadow.catch_up_completed(
        op.loc[:second_cut], close.loc[:second_cut], funding.loc[:second_cut]
    )
    assert status == "CAUGHT_UP_24"
    ledger = pd.read_csv(tmp_path / "ledger.csv")
    assert len(ledger) == 24 * len(SYMS)
    observed = pd.to_datetime(ledger.timestamp, utc=True).drop_duplicates().sort_values()
    assert observed.iloc[0] == idx[49]
    assert observed.iloc[-1] == idx[72]

    before = (tmp_path / "ledger.csv").read_bytes()
    assert shadow.catch_up_completed(
        op.loc[:second_cut], close.loc[:second_cut], funding.loc[:second_cut]
    ) == "ALREADY_CAUGHT_UP"
    assert (tmp_path / "ledger.csv").read_bytes() == before


def test_paper_runner_never_calls_shadow_funding_provider_before_holdout_release(tmp_path):
    idx = pd.date_range("2026-09-26", periods=60, freq="h", tz="UTC")
    frames_map = {
        s: SimpleNamespace(
            open=pd.Series(np.linspace(100, 120, len(idx)), index=idx),
            close=pd.Series(np.linspace(100, 121, len(idx)), index=idx),
        )
        for s in SYMS
    }
    shadow = runtime(tmp_path)
    calls = {"n": 0}

    def provider(symbols, cutoff):
        calls["n"] += 1
        raise AssertionError("sealed funding provider must not be called")

    runner = object.__new__(PaperRunner)
    runner.shadow_runtime = shadow
    runner.funding_history_provider = provider
    runner._observe_funding_shadow(frames_map)
    assert calls["n"] == 0
    assert pd.read_csv(tmp_path / "ledger.csv").empty


def test_shadow_failure_is_quarantined_from_paper_runner(tmp_path):
    idx, op, close, funding = frames(80)
    frames_map = {
        s: SimpleNamespace(open=op[s], close=close[s])
        for s in SYMS
    }
    shadow = runtime(tmp_path)

    def broken_provider(symbols, cutoff):
        raise OSError("simulated shadow-only data failure")

    runner = object.__new__(PaperRunner)
    runner.shadow_runtime = shadow
    runner.funding_history_provider = broken_provider
    # Must not propagate: the optional observer cannot halt the production runner.
    runner._observe_funding_shadow(frames_map)
