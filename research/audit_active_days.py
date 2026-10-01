#!/usr/bin/env python3
"""Historical compliance diagnostic for the frozen Trend 8/24 trading cadence.

This does not change any signal, parameter, or selection rule. It measures how many
calendar days in frozen 2026 OOS contain at least one scheduled asset order and reports
14-day active-day coverage relevant to the organizer's >=8 active-day rule.
"""
from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'research'))
from run_baseline_b1 import read_or_fetch,panel,targets,run,BASE

OUT=ROOT/'results/official_rules_audit'


def main():
    frames={s:read_or_fetch(s,'2025-01-01','2026-09-01') for s in BASE}
    opens,closes,_=panel(frames,BASE)
    target=targets(closes)
    start=pd.Timestamp('2026-01-01',tz='UTC'); end=pd.Timestamp('2026-09-01',tz='UTC')
    mask=(opens.index>=start)&(opens.index<end)
    result=run(opens.loc[mask],closes.loc[mask],target.loc[mask],10)
    trades=result.trades.copy()
    trades['timestamp']=pd.to_datetime(trades['timestamp'],utc=True)
    trades['day']=trades['timestamp'].dt.floor('D')
    rows=[]
    for window_start in pd.date_range(start,end-pd.Timedelta(days=14),freq='D'):
        window_end=window_start+pd.Timedelta(days=14)
        sub=trades[(trades.timestamp>=window_start)&(trades.timestamp<window_end)]
        rows.append({'window_start':window_start,'window_end_exclusive':window_end,
                     'active_trading_days':int(sub.day.nunique()),'asset_orders':int(len(sub))})
    windows=pd.DataFrame(rows)
    OUT.mkdir(parents=True,exist_ok=True)
    windows.to_csv(OUT/'ACTIVE_DAY_14D_WINDOWS.csv',index=False)
    summary={
        'oos_start':str(start),'oos_end_exclusive':str(end),
        'total_asset_orders':int(len(trades)),
        'calendar_days':int((end-start)/pd.Timedelta(days=1)),
        'active_days':int(trades.day.nunique()),
        'min_14d_active_days':int(windows.active_trading_days.min()),
        'median_14d_active_days':float(windows.active_trading_days.median()),
        'share_14d_windows_meeting_8_day_rule':float((windows.active_trading_days>=8).mean()),
        'min_14d_asset_orders':int(windows.asset_orders.min()),
        'median_14d_asset_orders':float(windows.asset_orders.median()),
        'note':'Historical intended asset-order activity before live exchange MiniOrder/precision filtering; not a guarantee of future fills.'
    }
    import json
    (OUT/'ACTIVE_DAY_SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
