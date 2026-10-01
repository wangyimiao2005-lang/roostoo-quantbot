import json
from datetime import timedelta

import pytest
import numpy as np
import pandas as pd

from b2e_freeze import ARTIFACT, DEV_END, HASH_FILE, calibrate_controls, digest, load_and_verify_hash, verify, verify_artifact
from run_b2e_final_holdout import RELEASE, preflight


def test_artifact_hash_and_reproduction_pass():
    assert load_and_verify_hash()["strategy_id"] == "B2E_v1"
    assert verify()["max_difference"] <= 1e-10


def test_expected_2025_normalization():
    x = json.loads(ARTIFACT.read_text())["normalization"]
    assert abs(x["signal_strength_mean"] - .2777150486) < 1e-10
    assert abs(x["signal_strength_std"] - .1121155255) < 1e-10
    assert abs(x["signal_dispersion_mean"] - .1228876620) < 1e-10
    assert abs(x["signal_dispersion_std"] - .0783294053) < 1e-10


def test_frozen_baseline_and_development_boundary():
    x = load_and_verify_hash()
    assert x["development_period"]["end"] == "2025-12-31T23:00:00Z"
    assert DEV_END.isoformat() == "2026-01-01T00:00:00+00:00"
    assert x["baseline_strategy"] == {"ema_fast": 8, "ema_slow": 24, "volatility_window_hours": 48, "target_volatility": .35, "volatility_floor": .05, "max_asset_abs_weight": .35, "max_gross": 1.0, "rebalance_hours": 24, "next_bar_execution": True}


@pytest.mark.parametrize("key", ["signal_strength_mean", "signal_strength_std", "signal_dispersion_mean", "signal_dispersion_std"])
def test_wrong_normalization_aborts_before_performance(key):
    payload = json.loads(ARTIFACT.read_text()); payload["normalization"][key] += .01
    with pytest.raises(RuntimeError, match="reproduction failed"):
        verify_artifact(payload)


@pytest.mark.parametrize("section,key", [("controls", "constant_risk_multiplier"), ("vol_only_parameters", "k")])
def test_wrong_control_calibration_aborts(section, key):
    payload = json.loads(ARTIFACT.read_text())
    target = payload["controls"] if section == "controls" else payload["controls"][section]
    target[key] += .01
    with pytest.raises(RuntimeError, match="reproduction failed"):
        verify_artifact(payload)


def test_hash_tamper_aborts(tmp_path):
    bad = tmp_path / "b2e_v1.json"; bad.write_bytes(ARTIFACT.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        load_and_verify_hash(bad, HASH_FILE)


def test_preflight_date_lock_prevents_performance():
    with pytest.raises(RuntimeError, match="SEALED"):
        preflight(RELEASE - timedelta(seconds=1))


def test_future_rows_cannot_change_control_calibration():
    index=pd.date_range("2025-12-31 00:00",periods=8,freq="h",tz="UTC"); cols=["BTCUSDT"]
    a=pd.DataFrame(1.0,index=index,columns=cols); b=pd.DataFrame(.75,index=index,columns=cols)
    target=a.copy(); vol=pd.Series(.4,index=index); mask=pd.Series([True]*4+[False]*4,index=index)
    base=calibrate_controls(a,b,target,target*.75,vol,mask)
    # Deliberately extreme post-development values must be ignored.
    a.iloc[4:]=100; b.iloc[4:]=.001; target.iloc[4:]=99; vol.iloc[4:]=99
    changed=calibrate_controls(a,b,target,target*.75,vol,mask)
    assert changed == base
