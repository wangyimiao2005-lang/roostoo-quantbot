"""B2C disagreement diagnostics and pre-registered risk scaler utilities.

Research-only.  The scaler has no fitted parameter:
    agreement = 1 - abs(raw_signal - residual_signal) / 2
    B2C target = Baseline-A target * agreement
Signals are clipped to [-1, 1] by the frozen Trend 8/24 implementation, so
agreement is in [0, 1].
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def agreement_score(raw_signal: pd.DataFrame, residual_signal: pd.DataFrame) -> pd.DataFrame:
    """Element-wise raw/residual agreement in [0, 1]."""
    raw, residual = raw_signal.align(residual_signal, join="inner", axis=0)
    raw, residual = raw.align(residual, join="inner", axis=1)
    score = 1.0 - (raw - residual).abs() / 2.0
    return score.clip(lower=0.0, upper=1.0)


def disagreement_scaled_targets(a_targets: pd.DataFrame, agreement: pd.DataFrame) -> pd.DataFrame:
    """Scale frozen A targets only downward by the pre-registered agreement score."""
    target, score = a_targets.align(agreement, join="left", axis=0)
    target, score = target.align(score, join="left", axis=1)
    # No residual history => no B2C position. OOS has a full 2025 warm-up, so
    # this only affects the initial development warm-up interval.
    return target * score.fillna(0.0)


def portfolio_agreement(agreement: pd.DataFrame, a_targets: pd.DataFrame) -> pd.Series:
    """Absolute-A-target-weighted agreement; NaN when A has no gross target."""
    score, target = agreement.align(a_targets, join="inner", axis=0)
    score, target = score.align(target, join="inner", axis=1)
    weights = target.abs()
    denom = weights.sum(axis=1)
    out = (score * weights).sum(axis=1).div(denom.where(denom > 1e-12))
    return out.rename("portfolio_agreement")


def classify_by_frozen_dev_terciles(score: pd.Series, low_cut: float, high_cut: float) -> pd.Series:
    labels = pd.Series(index=score.index, dtype="object", name="agreement_bucket")
    labels.loc[score < low_cut] = "LOW"
    labels.loc[(score >= low_cut) & (score < high_cut)] = "MEDIUM"
    labels.loc[score >= high_cut] = "HIGH"
    return labels


def forward_max_drawdown(returns: pd.Series) -> float:
    if len(returns) == 0:
        return np.nan
    wealth = (1.0 + returns).cumprod()
    dd = wealth / wealth.cummax() - 1.0
    return float(dd.min())
