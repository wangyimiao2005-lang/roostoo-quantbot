"""Causality and frozen-construction guardrails for B2 research."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from baseline_b2 import residual_index, rolling_pca_residuals
from run_baseline_b2 import raw_targets, residual_targets
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy


def returns(rows=80):
    rng=np.random.default_rng(7); idx=pd.date_range("2025-01-01",periods=rows,freq="h",tz="UTC")
    common=rng.normal(0,.01,rows); return pd.DataFrame({s:common+rng.normal(0,.003,rows) for s in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]},index=idx)


def test_pca_is_causal_and_orientation_is_deterministic():
    r=returns(); first=rolling_pca_residuals(r, 24)[0]
    changed=r.copy(); changed.iloc[60:] *= 100
    second=rolling_pca_residuals(changed, 24)[0]
    assert np.allclose(first.iloc[:60],second.iloc[:60],equal_nan=True)
    _, _, _, loading=rolling_pca_residuals(r,24)
    assert (loading.BTCUSDT >= 0).all()


def test_residual_is_actual_minus_reconstructed_component_and_index_is_arithmetic():
    r=returns(); residual, factor, _, loadings=rolling_pca_residuals(r,24)
    assert residual.iloc[23:].notna().all().all() and factor.iloc[23:].notna().all()
    idx=residual_index(pd.DataFrame({"x":[.1,-.1]})); assert np.isclose(idx.x.iloc[-1], .99)


def test_b2_preserves_parameters_caps_and_next_bar_execution():
    idx=pd.date_range("2025-01-01",periods=100,freq="h",tz="UTC"); r=returns(100)
    closes=(1+r).cumprod()*100; closes.index=idx
    target, *_=residual_targets(closes,24)
    assert (target.abs() <= .35 + 1e-12).all().all() and (target.abs().sum(axis=1) <= 1 + 1e-12).all()
    result=run_backtest(closes*.999,closes,target,10,execution_policy=ExecutionPolicy("Rebalance24h",rebalance_every=24))
    assert np.allclose(result.weights.iloc[1], target.iloc[0])
    assert raw_targets(closes).shape == target.shape
