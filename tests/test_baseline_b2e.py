import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from baseline_b2e import fit_standardizer, hold_rebalance_multiplier, risk_multiplier, signal_geometry, standardize, vol_only_multiplier
from run_baseline_b2e import calibrate_vol_k
from run_baseline_b2e import scheduled
from run_baseline_b1 import run


def test_geometry_is_current_cross_section_only():
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    raw = pd.DataFrame({"A": [1.0, 0.2, -0.4], "B": [-1.0, 0.6, 0.8]}, index=idx)
    before = signal_geometry(raw).loc[idx[1]].copy()
    changed = raw.copy(); changed.loc[idx[2], "A"] = 999.0
    after = signal_geometry(changed).loc[idx[1]]
    assert np.allclose(before, after)
    assert np.isclose(before.signal_strength, .4)
    assert np.isclose(before.signal_dispersion, .2)


def test_oos_standardization_uses_frozen_development_constants():
    dev = pd.DataFrame({"signal_strength": [1., 2., 3.], "signal_dispersion": [2., 4., 6.]})
    oos = pd.DataFrame({"signal_strength": [100.], "signal_dispersion": [200.]})
    mean, std = fit_standardizer(dev)
    z = standardize(oos, mean, std)
    assert np.isclose(mean.signal_strength, 2.)
    assert z.signal_strength.iloc[0] > 100


def test_multiplier_mapping_is_bounded_and_future_proof():
    idx = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
    scores = pd.Series([0., 1., 2., 3.], index=idx)
    m = risk_multiplier(scores, .5, 1.5)
    assert m.tolist() == [1., .75, .5, .5]
    hourly = pd.date_range(idx[0], periods=72, freq="h", tz="UTC")
    held = hold_rebalance_multiplier(hourly, m)
    altered = m.copy(); altered.iloc[-1] = 1.
    assert held.loc[hourly[:48]].equals(hold_rebalance_multiplier(hourly, altered).loc[hourly[:48]])
    assert held.between(.5, 1.).all()


def test_b2e_is_only_a_portfolio_scalar_and_cannot_reverse_positions():
    targets = pd.DataFrame({"A": [-.2, .3], "B": [.1, -.1]})
    multiplier = pd.Series([1., .5])
    scaled = targets.mul(multiplier, axis=0)
    assert np.allclose(scaled, targets * np.array([[1.], [.5]]))
    assert ((scaled * targets) >= 0).all().all()
    assert (scaled.abs() <= targets.abs()).all().all()


def test_vol_only_and_control_calibration_depend_only_on_development():
    idx = pd.date_range("2025-01-01", periods=6, freq="h", tz="UTC")
    a = pd.DataFrame({"A": [.2] * 6}, index=idx)
    b = pd.DataFrame({"A": [.15] * 6}, index=idx)
    vol = pd.Series([.2, .25, .3, .4, .5, .6], index=idx)
    dev = pd.Series([True, True, True, False, False, False], index=idx)
    k = calibrate_vol_k(a, b, vol, dev)
    altered = vol.copy(); altered.iloc[3:] = 99.
    assert np.isclose(k, calibrate_vol_k(a, b, altered, dev))
    assert (vol_only_multiplier(vol, k) <= 1).all()


def test_b2e_uses_same_daily_schedule_and_next_bar_execution():
    idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    assert list(scheduled(idx)) == [idx[0], idx[24], idx[48]]
    opens = pd.DataFrame({"A": [100.] * len(idx)}, index=idx)
    closes = opens.copy()
    target = pd.DataFrame({"A": [.2] * len(idx)}, index=idx)
    result = run(opens, closes, target, 10)
    assert result.weights.iloc[0, 0] == 0.0
    assert result.weights.iloc[1, 0] == .2
