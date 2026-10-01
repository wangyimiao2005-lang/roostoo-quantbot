"""Causal rolling-PCA residual signal utilities for isolated B2 research.

This module intentionally lives under ``research``.  It does not alter the
frozen strategy, live runner, or production portfolio construction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_pca_residuals(returns: pd.DataFrame, lookback: int = 720):
    """Return strictly trailing, PC1-removed arithmetic residual returns.

    At row *t*, the PCA is fitted only to returns in ``[t-lookback+1, t]``.
    PC1 is fit on per-window standardized returns.  Its sign is oriented so
    BTC's loading is positive (falling back to a positive loading sum if BTC
    is absent).  The component is reconstructed in original return units,
    including the trailing-window mean, before subtraction.
    """
    if lookback < 2:
        raise ValueError("lookback must be at least two bars")
    values = returns.to_numpy(dtype=float)
    residual = np.full_like(values, np.nan)
    factor = np.full(len(returns), np.nan)
    rows, loading_rows = [], []
    btc_index = returns.columns.get_loc("BTCUSDT") if "BTCUSDT" in returns else None
    for end in range(lookback - 1, len(returns)):
        window = values[end - lookback + 1 : end + 1]
        if not np.isfinite(window).all():
            continue
        mean = window.mean(axis=0)
        std = window.std(axis=0, ddof=1)
        if (std <= 0).any() or not np.isfinite(std).all():
            continue
        z = (window - mean) / std
        covariance = np.cov(z, rowvar=False, ddof=1)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues, loading = eigenvalues[order], eigenvectors[:, order[0]]
        orientation = loading[btc_index] if btc_index is not None else loading.sum()
        if orientation < 0:
            loading = -loading
        z_now = z[-1]
        score = float(z_now @ loading)
        common_component = mean + std * (score * loading)
        residual[end] = window[-1] - common_component
        factor[end] = score
        explained = float(eigenvalues[0] / eigenvalues.sum())
        stamp = returns.index[end]
        rows.append({"timestamp": stamp, "pc1_explained_variance_ratio": explained, "factor_score": score})
        loading_rows.append({"timestamp": stamp, **dict(zip(returns.columns, loading))})
    return (pd.DataFrame(residual, index=returns.index, columns=returns.columns),
            pd.Series(factor, index=returns.index, name="pc1_factor"),
            pd.DataFrame(rows).set_index("timestamp") if rows else pd.DataFrame(),
            pd.DataFrame(loading_rows).set_index("timestamp") if loading_rows else pd.DataFrame())


def residual_index(residual_returns: pd.DataFrame) -> pd.DataFrame:
    """Synthetic price index using only arithmetic residual returns."""
    return (1.0 + residual_returns.fillna(0.0)).cumprod()


def residual_ready(residual_returns: pd.DataFrame, slow: int = 24) -> pd.DataFrame:
    """Require a complete residual signal window; invalid observations are flat."""
    return residual_returns.notna().rolling(slow, min_periods=slow).sum().eq(slow)
