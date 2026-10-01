"""B2D incremental risk-signal validation helpers.

Research only.  These utilities deliberately avoid any trading-rule changes.
They support causal, development-fitted comparisons of whether B2C agreement
adds drawdown-prediction information beyond simpler observable risk controls.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def trailing_average_pairwise_correlation(
    returns: pd.DataFrame,
    timestamps: pd.DatetimeIndex,
    lookback: int = 720,
) -> pd.Series:
    """Average off-diagonal correlation using exactly the trailing lookback rows.

    The window ends at each timestamp; rows after that timestamp are never read.
    A value is returned only when all assets have a complete lookback window.
    """
    out = []
    for ts in timestamps:
        if ts not in returns.index:
            out.append(np.nan)
            continue
        pos = returns.index.get_loc(ts)
        if not isinstance(pos, (int, np.integer)) or pos + 1 < lookback:
            out.append(np.nan)
            continue
        window = returns.iloc[pos - lookback + 1 : pos + 1].dropna(how="any")
        if len(window) != lookback:
            out.append(np.nan)
            continue
        corr = window.corr().to_numpy()
        n = len(corr)
        out.append(float((corr.sum() - np.trace(corr)) / (n * (n - 1))))
    return pd.Series(out, index=timestamps, name=f"avg_pairwise_corr_{lookback}h")


def development_standardizer(frame: pd.DataFrame, columns: list[str]) -> tuple[pd.Series, pd.Series]:
    """Return mean/std for predictors from development data only."""
    mean = frame[columns].mean()
    std = frame[columns].std(ddof=0).replace(0.0, np.nan)
    return mean, std


def apply_standardizer(frame: pd.DataFrame, mean: pd.Series, std: pd.Series) -> pd.DataFrame:
    """Apply an already-fitted standardizer without refitting."""
    return (frame[mean.index] - mean) / std


def weighted_absolute_signal_strength(signal: pd.DataFrame, targets: pd.DataFrame) -> pd.Series:
    """Absolute-target-weighted mean absolute raw signal."""
    s, w = signal.align(targets.abs(), join="inner", axis=0)
    s, w = s.align(w, join="inner", axis=1)
    denom = w.sum(axis=1).replace(0.0, np.nan)
    return ((s.abs() * w).sum(axis=1) / denom).rename("raw_signal_strength")
