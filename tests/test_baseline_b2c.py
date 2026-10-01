import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from baseline_b2c import agreement_score, disagreement_scaled_targets, portfolio_agreement


def test_agreement_formula_extremes():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    raw = pd.DataFrame({"BTCUSDT": [1.0, 1.0]}, index=idx)
    residual = pd.DataFrame({"BTCUSDT": [1.0, -1.0]}, index=idx)
    out = agreement_score(raw, residual)
    assert np.isclose(out.iloc[0, 0], 1.0)
    assert np.isclose(out.iloc[1, 0], 0.0)


def test_disagreement_scaler_never_increases_absolute_a_target():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    target = pd.DataFrame({"BTCUSDT": [.3, -.2], "ETHUSDT": [-.1, .25]}, index=idx)
    score = pd.DataFrame({"BTCUSDT": [.7, .4], "ETHUSDT": [.2, 1.]}, index=idx)
    scaled = disagreement_scaled_targets(target, score)
    assert (scaled.abs() <= target.abs() + 1e-15).all().all()
    assert np.all(np.sign(scaled.to_numpy()) == np.sign(target.to_numpy()))


def test_portfolio_agreement_is_a_target_weighted():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-01-01", tz="UTC")])
    score = pd.DataFrame({"BTCUSDT": [1.0], "ETHUSDT": [0.0]}, index=idx)
    target = pd.DataFrame({"BTCUSDT": [.3], "ETHUSDT": [.1]}, index=idx)
    out = portfolio_agreement(score, target)
    assert np.isclose(out.iloc[0], .75)
