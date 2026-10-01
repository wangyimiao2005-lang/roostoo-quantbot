"""Causal helpers for the preregistered B2E signal-geometry risk overlay."""
from __future__ import annotations

import numpy as np
import pandas as pd


FEATURES = ["signal_strength", "signal_dispersion"]


def signal_geometry(raw_signal: pd.DataFrame) -> pd.DataFrame:
    """Unweighted, current-five-asset geometry of frozen raw signals."""
    return pd.DataFrame({
        "signal_strength": raw_signal.abs().mean(axis=1),
        "signal_dispersion": raw_signal.std(axis=1, ddof=0),
    }, index=raw_signal.index)


def fit_standardizer(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    mean = frame[FEATURES].mean()
    std = frame[FEATURES].std(ddof=0).replace(0.0, np.nan)
    return mean, std


def standardize(frame: pd.DataFrame, mean: pd.Series, std: pd.Series) -> pd.DataFrame:
    return (frame[FEATURES] - mean) / std


def risk_multiplier(prediction: pd.Series, q50: float, q75: float) -> pd.Series:
    """The sole preregistered 1.00/0.75/0.50 portfolio mapping."""
    out = pd.Series(1.0, index=prediction.index, name="risk_multiplier")
    out.loc[prediction > q50] = 0.75
    out.loc[prediction > q75] = 0.50
    return out.clip(0.50, 1.00)


def hold_rebalance_multiplier(index: pd.DatetimeIndex, scheduled: pd.Series) -> pd.Series:
    """Hold a scheduled multiplier; future rows cannot affect earlier values."""
    out = scheduled.reindex(index).ffill().fillna(1.0)
    return out.clip(0.50, 1.00).rename("risk_multiplier")


def vol_only_multiplier(market_vol: pd.Series, k: float) -> pd.Series:
    """Causal volatility-only overlay; it can only reduce exposure."""
    return (k / market_vol.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0).rename("vol_multiplier")

