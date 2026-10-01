from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable

import numpy as np
import pandas as pd

from quant_competition.backtest import BacktestResult, run_backtest
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend

SEP_CUTOFF = pd.Timestamp('2026-09-01', tz='UTC')
CAL_END = pd.Timestamp('2025-07-01', tz='UTC')
OOS_START = pd.Timestamp('2026-01-01', tz='UTC')


def assert_pre_sep(*objs: pd.Series | pd.DataFrame) -> None:
    """Research selection in 4B.1 is forbidden from seeing Sep-2026 rows."""
    for obj in objs:
        if len(obj.index) and pd.DatetimeIndex(obj.index).max() >= SEP_CUTOFF:
            raise ValueError('Phase 4B.1 research object contains Sep-2026 or later data')


def trend_targets(closes: pd.DataFrame) -> pd.DataFrame:
    raw = MultiHorizonTrend(8, 24).target_weights(closes)
    return enforce_exposure_limits(risk_scale_targets(raw, closes.pct_change(fill_method=None))).fillna(0.0)


def rolling_weighted_imbalance(buy: pd.DataFrame, total: pd.DataFrame, hours: int) -> pd.DataFrame:
    b = buy.rolling(hours, min_periods=hours).sum()
    q = total.rolling(hours, min_periods=hours).sum()
    return (2 * b - q).div(q.replace(0.0, np.nan))


def funding_mean_hourly(funding_hourly: pd.DataFrame, hours: int = 72) -> pd.DataFrame:
    """A true elapsed-time rolling mean on the causal hourly funding state."""
    return funding_hourly.rolling(hours, min_periods=hours).mean()


@dataclass(frozen=True)
class Thresholds:
    flow_low: float
    flow_high: float
    premium_low: float
    premium_high: float
    funding_low: float
    funding_high: float


def fit_thresholds(
    flow4: pd.DataFrame,
    premium24: pd.DataFrame,
    funding72: pd.DataFrame,
    calibration_mask: pd.Series | np.ndarray,
) -> Thresholds:
    """Fit all cutoffs on the first half of 2025 only."""
    def vals(x: pd.DataFrame) -> pd.Series:
        return x.loc[calibration_mask].stack(future_stack=True).dropna()

    f = vals(flow4)
    p = vals(premium24)
    u = vals(funding72)
    return Thresholds(
        flow_low=float(f.quantile(0.20)),
        flow_high=float(f.quantile(0.80)),
        premium_low=float(p.quantile(0.10)),
        premium_high=float(p.quantile(0.90)),
        funding_low=float(u.quantile(0.10)),
        funding_high=float(u.quantile(0.90)),
    )


def component_masks(
    trend: pd.DataFrame,
    flow4: pd.DataFrame,
    premium24: pd.DataFrame,
    funding72: pd.DataFrame,
    thresholds: Thresholds,
) -> Dict[str, pd.DataFrame]:
    """True means the baseline trend position is allowed to remain active."""
    long = trend > 0
    short = trend < 0

    flow_ok = ~((long & (flow4 < thresholds.flow_low)) | (short & (flow4 > thresholds.flow_high)))
    premium_ok = ~((long & (premium24 > thresholds.premium_high)) | (short & (premium24 < thresholds.premium_low)))
    funding_ok = ~((long & (funding72 > thresholds.funding_high)) | (short & (funding72 < thresholds.funding_low)))

    all_true = pd.DataFrame(True, index=trend.index, columns=trend.columns)
    return {
        'BASELINE': all_true,
        'FLOW': flow_ok,
        'PREMIUM': premium_ok,
        'FUNDING': funding_ok,
        'FLOW_PREMIUM': flow_ok & premium_ok,
        'FLOW_FUNDING': flow_ok & funding_ok,
        'PREMIUM_FUNDING': premium_ok & funding_ok,
        'FLOW_PREMIUM_FUNDING': flow_ok & premium_ok & funding_ok,
    }


def filtered_targets(trend: pd.DataFrame, masks: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    return {name: trend.where(mask, 0.0).fillna(0.0) for name, mask in masks.items()}


def backtest_targets(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: pd.DataFrame,
    cost_bps: float = 10.0,
) -> BacktestResult:
    return run_backtest(
        opens,
        closes,
        targets,
        cost_bps,
        execution_policy=ExecutionPolicy('Rebalance24h', rebalance_every=24),
    )


def daily_14d_windows(returns: pd.Series) -> pd.DataFrame:
    d = (1 + returns).groupby(returns.index.floor('D')).prod() - 1
    rows = []
    for i in range(max(len(d) - 13, 0)):
        x = d.iloc[i:i + 14]
        rows.append({'start': x.index[0], 'end': x.index[-1], 'return_14d': (1 + x).prod() - 1})
    return pd.DataFrame(rows)


def nonoverlap_14d_windows(returns: pd.Series) -> pd.DataFrame:
    d = (1 + returns).groupby(returns.index.floor('D')).prod() - 1
    rows = []
    for i in range(0, max(len(d) - 13, 0), 14):
        x = d.iloc[i:i + 14]
        if len(x) < 14:
            continue
        rows.append({'start': x.index[0], 'end': x.index[-1], 'return_14d': (1 + x).prod() - 1})
    return pd.DataFrame(rows)


def matched_window_stats(candidate: pd.Series, baseline: pd.Series, nonoverlap: bool = False) -> dict:
    fn = nonoverlap_14d_windows if nonoverlap else daily_14d_windows
    c = fn(candidate)
    b = fn(baseline)
    if c.empty or b.empty:
        return {}
    z = c.merge(b, on=['start', 'end'], suffixes=('', '_baseline'))
    inc = z.return_14d - z.return_14d_baseline
    return {
        'mean_14d': float(z.return_14d.mean()),
        'median_14d': float(z.return_14d.median()),
        'positive_14d': float((z.return_14d > 0).mean()),
        'p_beat_baseline': float((inc > 0).mean()),
        'mean_incremental_14d': float(inc.mean()),
        'median_incremental_14d': float(inc.median()),
        'p10_incremental_14d': float(inc.quantile(.10)),
        'worst_14d': float(z.return_14d.min()),
        'best_14d': float(z.return_14d.max()),
        'n_14d_windows': int(len(z)),
    }


def result_summary(name: str, result: BacktestResult, baseline: BacktestResult) -> dict:
    gross = float((1 + result.gross_returns).prod() - 1)
    net = float((1 + result.returns).prod() - 1)
    turn = float(result.turnover.sum())
    out = {
        'strategy': name,
        'gross_return': gross,
        'net_return_10bps': net,
        'turnover': turn,
        'fees': float(result.costs.sum()),
        'break_even_cost_bps': gross / max(turn, 1e-12) * 10000,
        'orders': int(len(result.trades)),
        'active_rebalance_timestamps': int(result.trades.timestamp.nunique()) if len(result.trades) else 0,
    }
    out.update({f'daily_{k}': v for k, v in matched_window_stats(result.returns, baseline.returns).items()})
    out.update({f'nonoverlap_{k}': v for k, v in matched_window_stats(result.returns, baseline.returns, True).items()})
    return out


def subperiod_rows(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: Dict[str, pd.DataFrame],
    periods: Iterable[tuple[str, pd.Timestamp, pd.Timestamp]],
) -> list[dict]:
    rows = []
    for period, start, end in periods:
        ix = opens.index[(opens.index >= start) & (opens.index < end)]
        res = {name: backtest_targets(opens.loc[ix], closes.loc[ix], tar.loc[ix]) for name, tar in targets.items()}
        b = res['BASELINE']
        bnet = (1 + b.returns).prod() - 1
        for name, rr in res.items():
            net = (1 + rr.returns).prod() - 1
            w = matched_window_stats(rr.returns, b.returns)
            rows.append({
                'period': period,
                'strategy': name,
                'net_return': net,
                'baseline_net_return': bnet,
                'incremental_return_geometric': (1 + net) / (1 + bnet) - 1,
                'median_14d': w.get('median_14d', np.nan),
                'p_beat_baseline': w.get('p_beat_baseline', np.nan),
            })
    return rows


def select_development_candidate(dev_table: pd.DataFrame) -> str:
    """Pre-OOS selection: prioritize 14d profit, require positive net if possible."""
    x = dev_table[dev_table.strategy != 'BASELINE'].copy()
    positive = x[x.net_return_10bps > 0]
    if not positive.empty:
        x = positive
    # Profit-first: mean daily-start 14d, then median, then total net.
    return str(x.sort_values(
        ['daily_mean_14d', 'daily_median_14d', 'net_return_10bps'], ascending=False
    ).iloc[0].strategy)


def incremental_by_week(candidate: pd.Series, baseline: pd.Series) -> pd.DataFrame:
    z = pd.DataFrame({'candidate': candidate, 'baseline': baseline}).fillna(0)
    # Weekly compounded relative performance; W-SUN keeps complete deterministic buckets.
    rows = []
    for week, g in z.groupby(pd.Grouper(freq='W-SUN')):
        if g.empty:
            continue
        c = (1 + g.candidate).prod() - 1
        b = (1 + g.baseline).prod() - 1
        rows.append({'week_end': week, 'candidate_return': c, 'baseline_return': b, 'incremental_return': (1 + c)/(1 + b)-1})
    return pd.DataFrame(rows)


def concentration_audit(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: pd.DataFrame,
    baseline_targets: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cand = backtest_targets(opens, closes, targets)
    base = backtest_targets(opens, closes, baseline_targets)
    full_c = (1 + cand.returns).prod() - 1
    full_b = (1 + base.returns).prod() - 1

    asset_rows = []
    for asset in targets.columns:
        ct = targets.copy(); bt = baseline_targets.copy()
        ct[asset] = 0.0; bt[asset] = 0.0
        cr = backtest_targets(opens, closes, ct); br = backtest_targets(opens, closes, bt)
        cn = (1 + cr.returns).prod() - 1; bn = (1 + br.returns).prod() - 1
        asset_rows.append({
            'excluded_asset': asset,
            'candidate_net_ex_asset': cn,
            'baseline_net_ex_asset': bn,
            'incremental_ex_asset': (1 + cn)/(1 + bn)-1,
            'candidate_return_loss_from_exclusion': full_c - cn,
        })
    asset_df = pd.DataFrame(asset_rows)

    week_df = incremental_by_week(cand.returns, base.returns)
    if not week_df.empty:
        best_week = week_df.loc[week_df.incremental_return.idxmax(), 'week_end']
        week_start = best_week - pd.Timedelta(days=6)
        mask = ~((cand.returns.index >= week_start) & (cand.returns.index < best_week + pd.Timedelta(days=1)))
        # Exclusion diagnostic on realized return stream, not a hypothetical re-backtest.
        c_ex = (1 + cand.returns.loc[mask]).prod() - 1
        b_ex = (1 + base.returns.loc[mask]).prod() - 1
    else:
        best_week = pd.NaT; c_ex = np.nan; b_ex = np.nan

    summary = {
        'candidate_net': full_c,
        'baseline_net': full_b,
        'best_week_end': best_week,
        'candidate_net_ex_best_week': c_ex,
        'baseline_net_ex_best_week': b_ex,
        'incremental_ex_best_week': (1 + c_ex)/(1 + b_ex)-1 if pd.notna(c_ex) else np.nan,
        'worst_incremental_ex_asset': float(asset_df.incremental_ex_asset.min()),
        'best_incremental_ex_asset': float(asset_df.incremental_ex_asset.max()),
    }
    return asset_df, week_df, summary


def thresholds_dict(t: Thresholds) -> dict:
    return asdict(t)
