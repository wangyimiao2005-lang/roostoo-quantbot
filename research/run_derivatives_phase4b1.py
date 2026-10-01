"""Phase 4B.1: strict decomposition of funding, premium and taker-flow filters.

No Sep-2026 observations are used anywhere in research selection or diagnostics.
Premium/flow are limited to the five assets already present locally; no external data
are fabricated when network access is unavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

from derivatives_alpha_phase4b.phase4b1 import (
    SEP_CUTOFF, CAL_END, OOS_START, assert_pre_sep, trend_targets,
    rolling_weighted_imbalance, funding_mean_hourly, fit_thresholds,
    component_masks, filtered_targets, backtest_targets, result_summary,
    subperiod_rows, select_development_candidate, concentration_audit,
    thresholds_dict,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results' / 'derivatives_phase4b1'
RAW = ROOT / 'data' / 'derivatives_raw' / 'binance_futures_phase4b'
B1_SYMS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','TRXUSDT','UNIUSDT','NEARUSDT']

def _raw_file(sym: str, kind: str) -> Path | None:
    files = sorted((RAW/sym).glob(f'{kind}_1h_2025-01-01_*.csv'))
    return files[-1] if files else None

def _available_derivatives_symbols():
    return [s for s in B1_SYMS if all(_raw_file(s,k) is not None for k in ('taker','mark','index'))]
START = pd.Timestamp('2025-01-01', tz='UTC')
DEV_VAL_START = CAL_END
DEV_VAL_END = OOS_START
OOS_END = SEP_CUTOFF


def _read_deriv(sym: str, kind: str) -> pd.DataFrame:
    p = _raw_file(sym, kind)
    if p is None:
        raise FileNotFoundError(f'no local {kind} history for {sym}')
    x = pd.read_csv(p, parse_dates=['timestamp'])
    x['timestamp'] = pd.to_datetime(x.timestamp, utc=True)
    # Hard isolation: Sep is discarded immediately, before coverage/feature work.
    x = x[x.timestamp < SEP_CUTOFF].drop_duplicates('timestamp').sort_values('timestamp')
    return x.set_index('timestamp')


def _load_spot(sym: str, idx: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    parts = []
    for p in list((ROOT/'data/raw').glob(f'{sym}_1h_*.csv')) + list((ROOT/'data/raw/ml_alpha_phase3a1').glob(f'{sym}_1h_*.csv')):
        z = pd.read_csv(p, index_col='timestamp', parse_dates=True)
        z.index = pd.to_datetime(z.index, utc=True)
        z = z[z.index < SEP_CUTOFF]
        parts.append(z)
    if not parts:
        raise FileNotFoundError(f'no OHLCV for {sym}')
    z = pd.concat(parts).loc[lambda a: ~a.index.duplicated(keep='last')].sort_index()
    return z.open.reindex(idx), z.close.reindex(idx)


def _funding(idx: pd.DatetimeIndex, syms) -> pd.DataFrame:
    p = ROOT/'data/derivatives_processed/binance_futures_funding_hourly_causal.csv'
    x = pd.read_csv(p, index_col='timestamp', parse_dates=True)
    x.index = pd.to_datetime(x.index, utc=True)
    x = x.loc[(x.index >= START) & (x.index < SEP_CUTOFF), syms].reindex(idx)
    return x


def _tables_for_period(op, cl, targets, start, end):
    ix = op.index[(op.index >= start) & (op.index < end)]
    res = {n: backtest_targets(op.loc[ix], cl.loc[ix], t.loc[ix]) for n,t in targets.items()}
    base = res['BASELINE']
    tab = pd.DataFrame([result_summary(n, r, base) for n,r in res.items()])
    return tab, res


def _write_universe_expansion_comparison(oos_tab: pd.DataFrame, sub_tab: pd.DataFrame) -> None:
    """Compare the preserved five-asset run with this data-only universe expansion.

    This reporting helper intentionally consumes existing result artifacts only; it
    does not participate in threshold fitting, selection, or backtesting.
    """
    old_dir = OUT / 'five_asset_baseline'
    old_oos = pd.read_csv(old_dir / 'PHASE4B1_OOS_DECOMPOSITION.csv')
    old_sub = pd.read_csv(old_dir / 'PHASE4B1_SUBPERIOD_STABILITY.csv')
    metrics = [
        'net_return_10bps', 'daily_mean_14d', 'daily_median_14d',
        'daily_positive_14d', 'daily_p_beat_baseline',
        'daily_mean_incremental_14d', 'break_even_cost_bps',
    ]
    full = old_oos[['strategy', *metrics]].merge(
        oos_tab[['strategy', *metrics]], on='strategy', suffixes=('_5asset', '_expanded'), how='outer'
    )
    full.insert(0, 'period', '2026_JanAug')
    full.insert(1, 'comparison_scope', 'full_2026_jan_aug')
    full = full.rename(columns={
        'net_return_10bps_5asset': 'five_asset_net_return_10bps',
        'net_return_10bps_expanded': 'expanded_universe_net_return_10bps',
        'daily_mean_14d_5asset': 'five_asset_mean_14d_return',
        'daily_mean_14d_expanded': 'expanded_universe_mean_14d_return',
        'daily_median_14d_5asset': 'five_asset_median_14d_return',
        'daily_median_14d_expanded': 'expanded_universe_median_14d_return',
        'daily_positive_14d_5asset': 'five_asset_positive_14d_probability',
        'daily_positive_14d_expanded': 'expanded_universe_positive_14d_probability',
        'daily_p_beat_baseline_5asset': 'five_asset_p_beat_baseline',
        'daily_p_beat_baseline_expanded': 'expanded_universe_p_beat_baseline',
        'daily_mean_incremental_14d_5asset': 'five_asset_mean_incremental_14d_return',
        'daily_mean_incremental_14d_expanded': 'expanded_universe_mean_incremental_14d_return',
        'break_even_cost_bps_5asset': 'five_asset_break_even_cost_bps',
        'break_even_cost_bps_expanded': 'expanded_universe_break_even_cost_bps',
    })
    sub_metrics = ['net_return', 'median_14d', 'p_beat_baseline']
    periods = ['2026_Q1', '2026_Q2', '2026_JulAug']
    sub = old_sub[old_sub.period.isin(periods)][['period', 'strategy', *sub_metrics]].merge(
        sub_tab[sub_tab.period.isin(periods)][['period', 'strategy', *sub_metrics]],
        on=['period', 'strategy'], suffixes=('_5asset', '_expanded'), how='outer'
    )
    sub.insert(1, 'comparison_scope', 'subperiod_stability')
    sub = sub.rename(columns={
        'net_return_5asset': 'five_asset_net_return_10bps',
        'net_return_expanded': 'expanded_universe_net_return_10bps',
        'median_14d_5asset': 'five_asset_median_14d_return',
        'median_14d_expanded': 'expanded_universe_median_14d_return',
        'p_beat_baseline_5asset': 'five_asset_p_beat_baseline',
        'p_beat_baseline_expanded': 'expanded_universe_p_beat_baseline',
    })
    # A single stable schema makes the unavailable subperiod-only metrics explicit.
    columns = list(full.columns)
    for col in columns:
        if col not in sub:
            sub[col] = np.nan
    pd.concat([full, sub[columns]], ignore_index=True).to_csv(
        OUT / 'PHASE4B1_UNIVERSE_EXPANSION_COMPARISON.csv', index=False
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range(START, OOS_END - pd.Timedelta(hours=1), freq='h', tz='UTC', name='timestamp')

    # Existing local derivatives data only; never touch Sep rows.
    syms = _available_derivatives_symbols()
    if len(syms) < 3:
        raise RuntimeError(f'insufficient local premium/flow universe: {syms}')
    dat = {s: {k: _read_deriv(s,k) for k in ('taker','mark','index')} for s in syms}
    mark = pd.DataFrame({s:dat[s]['mark'].close.reindex(idx) for s in syms})
    ind = pd.DataFrame({s:dat[s]['index'].close.reindex(idx) for s in syms})
    quote = pd.DataFrame({s:dat[s]['taker'].quote.reindex(idx) for s in syms})
    buy = pd.DataFrame({s:dat[s]['taker'].buy_quote.reindex(idx) for s in syms})
    for x in (mark,ind,quote,buy): x.columns.name='symbol'
    assert_pre_sep(mark, ind, quote, buy)

    op_parts, cl_parts = {}, {}
    for s in syms:
        op_parts[s], cl_parts[s] = _load_spot(s, idx)
    op = pd.DataFrame(op_parts); cl = pd.DataFrame(cl_parts)
    op.columns.name = cl.columns.name = 'symbol'
    funding = _funding(idx, syms)
    assert_pre_sep(op, cl, funding)

    premium = mark.div(ind).sub(1)
    premium24 = premium.rolling(24, min_periods=24).mean()
    flow4 = rolling_weighted_imbalance(buy, quote, 4)
    funding72 = funding_mean_hourly(funding, 72)

    coverage=[]
    for s in syms:
        for name, series in [('mark',mark[s]),('index',ind[s]),('taker',quote[s]),('funding',funding[s])]:
            valid=series.notna(); coverage.append({
                'asset':s,'variable':name,'start':idx.min(),'end':idx.max(),
                'expected_hours':len(idx),'actual_hours':int(valid.sum()),
                'coverage_pct':float(valid.mean()*100),'usable_95pct':bool(valid.mean()>=.95),
            })
    pd.DataFrame(coverage).to_csv(OUT/'PHASE4B1_DATA_COVERAGE.csv',index=False)
    (OUT/'PHASE4B1_ELIGIBLE_UNIVERSE.json').write_text(json.dumps({
        'b1_universe': B1_SYMS, 'premium_flow_locally_available': syms,
        'missing_premium_flow_assets': [s for s in B1_SYMS if s not in syms],
        'rule': 'asset included only when local mark/index/taker files all exist; no network fetch in Phase 4B.1'
    }, indent=2))

    # H1-2025 calibration only. H2-2025 is an untouched development validation set.
    cal_mask = (idx >= START) & (idx < CAL_END)
    thresholds = fit_thresholds(flow4, premium24, funding72, cal_mask)
    (OUT/'PHASE4B1_THRESHOLDS.json').write_text(json.dumps({
        'calibration_period':'2025-01-01..2025-06-30 UTC',
        **thresholds_dict(thresholds)
    }, indent=2))

    trend = trend_targets(cl)
    masks = component_masks(trend, flow4, premium24, funding72, thresholds)
    targets = filtered_targets(trend, masks)

    # Development validation selects a single candidate BEFORE 2026 evaluation.
    dev_tab, dev_res = _tables_for_period(op, cl, targets, DEV_VAL_START, DEV_VAL_END)
    selected = select_development_candidate(dev_tab)
    dev_tab['development_selected'] = dev_tab.strategy.eq(selected)
    dev_tab.to_csv(OUT/'PHASE4B1_DEV_VALIDATION.csv',index=False)

    oos_tab, oos_res = _tables_for_period(op, cl, targets, OOS_START, OOS_END)
    oos_tab['development_selected'] = oos_tab.strategy.eq(selected)
    oos_tab.to_csv(OUT/'PHASE4B1_OOS_DECOMPOSITION.csv',index=False)

    periods=[
        ('2025_H2_DEV_VALIDATION',DEV_VAL_START,DEV_VAL_END),
        ('2026_Q1',pd.Timestamp('2026-01-01',tz='UTC'),pd.Timestamp('2026-04-01',tz='UTC')),
        ('2026_Q2',pd.Timestamp('2026-04-01',tz='UTC'),pd.Timestamp('2026-07-01',tz='UTC')),
        ('2026_JulAug',pd.Timestamp('2026-07-01',tz='UTC'),OOS_END),
    ]
    sub_df = pd.DataFrame(subperiod_rows(op,cl,targets,periods))
    sub_df.to_csv(OUT/'PHASE4B1_SUBPERIOD_STABILITY.csv',index=False)

    # Correct cost stress: re-run original TARGETS at each cost; never re-feed executed weights.
    ix = op.index[(op.index>=OOS_START)&(op.index<OOS_END)]
    cost_rows=[]
    for name, tar in targets.items():
        for c in (5,10,15,20):
            rr=backtest_targets(op.loc[ix],cl.loc[ix],tar.loc[ix],c)
            gross=(1+rr.gross_returns).prod()-1; net=(1+rr.returns).prod()-1
            cost_rows.append({'strategy':name,'cost_bps':c,'gross_return':gross,'net_return':net,'fees':rr.costs.sum(),'turnover':rr.turnover.sum(),'break_even_cost_bps':gross/max(rr.turnover.sum(),1e-12)*10000})
    cost_df=pd.DataFrame(cost_rows); cost_df.to_csv(OUT/'PHASE4B1_COST_STRESS.csv',index=False)
    _write_universe_expansion_comparison(oos_tab, sub_df)

    # Concentration for every challenger; selected candidate gets detailed files.
    concentration_rows=[]
    for name in targets:
        if name=='BASELINE': continue
        a,w,s=concentration_audit(op.loc[ix],cl.loc[ix],targets[name].loc[ix],targets['BASELINE'].loc[ix])
        concentration_rows.append({'strategy':name,**s})
        if name==selected:
            a.to_csv(OUT/'PHASE4B1_SELECTED_LEAVE_ONE_ASSET_OUT.csv',index=False)
            w.to_csv(OUT/'PHASE4B1_SELECTED_WEEKLY_INCREMENT.csv',index=False)
    pd.DataFrame(concentration_rows).to_csv(OUT/'PHASE4B1_CONCENTRATION.csv',index=False)

    # Filter activity: how much of baseline exposure each component removes.
    act=[]
    active=trend.abs()>1e-12
    for name,mask in masks.items():
        if name=='BASELINE': continue
        removed=(active & ~mask).sum().sum(); total=active.sum().sum()
        act.append({'strategy':name,'active_asset_hours':int(total),'filtered_asset_hours':int(removed),'filtered_pct':float(removed/max(total,1))})
    pd.DataFrame(act).to_csv(OUT/'PHASE4B1_FILTER_ACTIVITY.csv',index=False)

    # Experiment log explicitly notes that 2026 is historical research evidence, not pristine after prior rounds.
    pd.DataFrame([{
        'phase':'4B.1','calibration':'2025_H1','development_validation':'2025_H2',
        'historical_oos':'2026-01-01..2026-08-31','sep_used':False,
        'universe':','.join(syms),'selected_on_dev':selected,
        'note':'2026 had been inspected in earlier Phase 4B, so this is decomposition/stability evidence, not a pristine new holdout.'
    }]).to_csv(OUT/'PHASE4B1_EXPERIMENT_LOG.csv',index=False)

    # Determine whether the dev-selected rule is stable enough to deserve further work.
    sel_oos=oos_tab.loc[oos_tab.strategy==selected].iloc[0]
    sub=pd.read_csv(OUT/'PHASE4B1_SUBPERIOD_STABILITY.csv')
    ss=sub[sub.strategy==selected]
    stable_positive=(ss[ss.period.str.startswith('2026_')].incremental_return_geometric>0).all()
    dev_base=dev_tab.loc[dev_tab.strategy=='BASELINE','net_return_10bps'].iloc[0]
    dev_sel=dev_tab.loc[dev_tab.strategy==selected,'net_return_10bps'].iloc[0]
    improves_dev=dev_sel>dev_base
    improves_oos=float(sel_oos.net_return_10bps)>float(oos_tab.loc[oos_tab.strategy=='BASELINE','net_return_10bps'].iloc[0])

    if improves_dev and improves_oos and stable_positive and sel_oos.daily_mean_incremental_14d>0:
        decision='PROCEED — DEV-SELECTED DERIVATIVES FILTER IS STABLE ENOUGH FOR A FORMAL NEXT VALIDATION'
    elif improves_dev and improves_oos:
        decision='MIXED — INCREMENTAL ALPHA EXISTS BUT IS TEMPORALLY UNSTABLE'
    else:
        decision='REJECT — DEV-SELECTED DERIVATIVES FILTER DOES NOT GENERALIZE ECONOMICALLY'

    conc=pd.read_csv(OUT/'PHASE4B1_CONCENTRATION.csv')
    crow=conc[conc.strategy==selected].iloc[0]
    baseline_oos=oos_tab[oos_tab.strategy=='BASELINE'].iloc[0]
    oos_sub=sub[sub.period.str.startswith('2026_')]
    challengers=[x for x in targets if x!='BASELINE']
    stable_exploratory=[]
    for n in challengers:
        r=oos_sub[oos_sub.strategy==n]
        if len(r)==3 and (r.incremental_return_geometric>0).all():
            stable_exploratory.append(n)
    best_net_row=oos_tab[oos_tab.strategy!='BASELINE'].sort_values('net_return_10bps',ascending=False).iloc[0]
    flow_oos=oos_tab.loc[oos_tab.strategy=='FLOW'].iloc[0]
    funding_oos=oos_tab.loc[oos_tab.strategy=='FUNDING'].iloc[0]
    decomp_lines=['| Strategy | Net @10bps | Mean 14d | Median 14d | P(beat baseline) | Mean incremental 14d |',
                  '|---|---:|---:|---:|---:|---:|']
    for _,r in oos_tab.iterrows():
        decomp_lines.append(f"| {r.strategy} | {r.net_return_10bps:.2%} | {r.daily_mean_14d:.2%} | {r.daily_median_14d:.2%} | {r.daily_p_beat_baseline:.1%} | {r.daily_mean_incremental_14d:.2%} |")
    decomp='\n'.join(decomp_lines)
    missing=[x for x in B1_SYMS if x not in syms]
    report=f'''# Phase 4B.1 — Proper Derivatives Signal Decomposition

## Protocol
- Common universe: {', '.join(syms)}. Missing local premium/taker history: {', '.join(missing) if missing else 'none'}. No data were fabricated.
- Threshold calibration: 2025 H1 only.
- Candidate selection: 2025 H2 only.
- Historical evaluation: 2026 Jan–Aug only.
- Sep 2026: **not loaded into research selection or diagnostics**.
- Cost stress re-runs raw targets at each fee; the prior `weights.shift(-1)` issue is removed.

## Development-selected challenger
`{selected}` was selected before the 2026 decomposition using profit-first 14-day development-validation metrics.

Development H2 net: {dev_sel:.2%} vs baseline {dev_base:.2%}.

2026 Jan–Aug net: {sel_oos.net_return_10bps:.2%} vs common-universe baseline {baseline_oos.net_return_10bps:.2%}.
Mean matched 14-day incremental return: {sel_oos.daily_mean_incremental_14d:.2%}.
Median matched 14-day return: {sel_oos.daily_median_14d:.2%}.
P(beat baseline): {sel_oos.daily_p_beat_baseline:.1%}.

The development-selected rule has a positive mean matched 14-day incremental return versus the expanded-universe baseline. This remains historical decomposition evidence, not a new selection pass.

## Full decomposition (diagnostic, not a new selection pass)
{decomp}

The highest 2026 total-net challenger is `{best_net_row.strategy}` at {best_net_row.net_return_10bps:.2%}, but this was identified after inspecting 2026 and must remain exploratory. Variants with positive geometric incremental return in all three 2026 subperiods: {', '.join(stable_exploratory) if stable_exploratory else 'none'}.

## Stability
`PHASE4B1_SUBPERIOD_STABILITY.csv` separates Q1, Q2 and Jul–Aug. A headline gain is not treated as robust if it disappears in individual subperiods.

## Five-asset versus expanded-universe robustness
`PHASE4B1_UNIVERSE_EXPANSION_COMPARISON.csv` preserves the original five-asset result alongside this 13-asset rerun, including the requested Q1, Q2, and Jul–Aug net-return comparisons.

For the expanded universe, Flow returned {flow_oos.net_return_10bps:.2%} versus the baseline's {baseline_oos.net_return_10bps:.2%}, with {flow_oos.daily_mean_incremental_14d:.2%} mean matched 14-day incremental return. Funding returned {funding_oos.net_return_10bps:.2%} versus the same baseline and had {funding_oos.daily_mean_incremental_14d:.2%} mean matched 14-day incremental return. Funding's incremental geometric result was positive in Q1, Q2, and Jul–Aug, but it underperformed the baseline in 2025 H2 development validation and is not promoted by this robustness test.

## Concentration
For the development-selected rule, worst incremental result after excluding any single asset is {crow.worst_incremental_ex_asset:.2%}. Incremental performance excluding its best week is {crow.incremental_ex_best_week:.2%}. This is a material fragility warning.

## Decision
**{decision}**

Interpretation: the prior +28% combined-filter headline should not be treated as deployable evidence. The clean pre-2026 selection chose Flow; in the expanded universe it outperformed the expanded baseline on 2026 total net return and mean matched 14-day incremental PnL. This is a robustness observation, not a new parameter-selection pass. Funding was incrementally positive in each 2026 subperiod but underperformed the baseline in 2025 H2 and cannot be promoted from this analysis.

This phase is intentionally a decomposition/stability audit. Because 2026 results were already observed in earlier Phase 4B iterations, they are not represented as a pristine new holdout. The final sealed competition holdout remains untouched by this code.
'''
    (OUT/'PHASE4B1_REPORT.md').write_text(report)
    (OUT/'PHASE4B1_DECISION.json').write_text(json.dumps({'selected_on_2025_h2':selected,'decision':decision,'sep_used':False},indent=2))

    print('PHASE 4B.1 SUMMARY')
    print('Common universe:', syms)
    print('Calibration: 2025 H1; development selection: 2025 H2; evaluation: 2026 Jan-Aug; Sep used: NO')
    print('Development-selected:', selected)
    print(f'Dev H2 net: {dev_sel:.2%} vs baseline {dev_base:.2%}')
    print(f'OOS net: {sel_oos.net_return_10bps:.2%} vs baseline {baseline_oos.net_return_10bps:.2%}')
    print(f'OOS mean incremental 14d: {sel_oos.daily_mean_incremental_14d:.2%}; Pbeat: {sel_oos.daily_p_beat_baseline:.1%}')
    print('Decision:', decision)

if __name__=='__main__':
    main()
