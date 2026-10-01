"""Guardrails for the isolated Baseline B1 research implementation."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from run_baseline_b1 import targets
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy


def test_b1_warmup_and_gap_are_flat_without_forward_fill():
    index = pd.date_range("2025-01-01", periods=100, freq="h", tz="UTC")
    close = pd.DataFrame({"X": np.linspace(100, 200, len(index))}, index=index)
    close.loc[index[70], "X"] = np.nan
    result = targets(close)
    assert (result.iloc[:48, 0] == 0).all()
    assert result.loc[index[70], "X"] == 0
    assert (result.loc[index[71:118] if len(index)>118 else index[71:], "X"] == 0).all()


def test_b1_caps_and_next_bar_execution_are_preserved():
    index = pd.date_range("2025-01-01", periods=120, freq="h", tz="UTC")
    close = pd.DataFrame({"A": np.linspace(100, 300, len(index)), "B": np.linspace(200, 50, len(index))}, index=index)
    target = targets(close)
    assert (target.abs() <= .35 + 1e-12).all().all()
    assert (target.abs().sum(axis=1) <= 1.0 + 1e-12).all()
    opens = close * .999
    result = run_backtest(opens, close, target, 10, execution_policy=ExecutionPolicy("Rebalance24h", rebalance_every=24))
    assert np.allclose(result.weights.iloc[1].values, target.iloc[0].values)

