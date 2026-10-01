import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from baseline_b2d import (
    apply_standardizer,
    development_standardizer,
    trailing_average_pairwise_correlation,
    weighted_absolute_signal_strength,
)


def test_trailing_pairwise_correlation_cannot_see_future():
    idx = pd.date_range("2026-01-01", periods=8, freq="h", tz="UTC")
    r = pd.DataFrame({"A": np.arange(8.0), "B": np.arange(8.0) * 2}, index=idx)
    t = pd.DatetimeIndex([idx[5]])
    before = trailing_average_pairwise_correlation(r, t, lookback=4).iloc[0]
    changed = r.copy()
    changed.loc[idx[6]:, "B"] = -9999
    after = trailing_average_pairwise_correlation(changed, t, lookback=4).iloc[0]
    assert np.isclose(before, after)


def test_standardizer_is_fitted_once_and_reused():
    dev = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    oos = pd.DataFrame({"x": [100.0, 200.0]})
    mean, std = development_standardizer(dev, ["x"])
    z = apply_standardizer(oos, mean, std)
    assert np.isclose(mean["x"], 2.0)
    assert z.iloc[0, 0] > 100


def test_weighted_signal_strength_uses_absolute_target_weights():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-01-01", tz="UTC")])
    signal = pd.DataFrame({"A": [1.0], "B": [-0.5]}, index=idx)
    target = pd.DataFrame({"A": [0.3], "B": [-0.1]}, index=idx)
    out = weighted_absolute_signal_strength(signal, target)
    assert np.isclose(out.iloc[0], (1.0 * 0.3 + 0.5 * 0.1) / 0.4)
