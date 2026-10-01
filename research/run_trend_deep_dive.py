"""Predeclared 1h/4h persistent-trend study; no configuration is selected on test data."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from common import ROOT, load_universe
from quant_competition.data.resample import resample_ohlcv
from quant_competition.strategies import MultiHorizonTrend, StateTrend
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import enforce_exposure_limits, risk_scale_targets, ExecutionPolicy
from quant_competition.metrics import performance_metrics, rolling_competition_metrics

def aggregate(opens,closes,volumes,rule):
    frames=[]
    for sym in closes:
        f=pd.DataFrame({'open':opens[sym],'high':closes[sym].cummax(), 'low':closes[sym].cummin(), 'close':closes[sym],'volume':volumes[sym]})
        # High/low are not used by trend; aggregate opens/closes/volume causally.
        frames.append((sym,resample_ohlcv(f,rule)))
    idx=frames[0][1].index
    for _,f in frames[1:]: idx=idx.intersection(f.index)
    return tuple(pd.DataFrame({s:f.loc[idx,c] for s,f in frames}) for c in ['open','close','volume'])
def evaluate(name, timeframe, opens, closes, target, policy, bars_per_day):
    r10=run_backtest(opens,closes,target,10,execution_policy=policy); m=performance_metrics(r10.returns,r10.costs,r10.turnover,bars_per_year=bars_per_day*365); roll=rolling_competition_metrics(r10.returns,bars_per_day=bars_per_day)
    gross=(1+r10.gross_returns).prod()-1; row={'timeframe':timeframe,'signal_configuration':name,'execution_type':policy.name,'gross_return':gross,'net_10bps':(1+r10.returns).prod()-1,'sharpe':m['sharpe'],'sortino':m['sortino'],'calmar':m['calmar'],'max_drawdown':m['max_drawdown'],'turnover':m['turnover'],'trades':len(r10.trades),'trades_per_14d':len(r10.trades)/(len(r10.returns)/(14*bars_per_day)),'positive_14d_probability':roll['positive_14d_probability'],'median_14d_return':roll['median_14d_return'],'break_even_cost_bps':gross/max(m['turnover'],1e-9)*10000}
    for bps in [5,15,20]: row[f'net_{bps}bps']=(1+run_backtest(opens,closes,target,bps,execution_policy=policy).returns).prod()-1
    return row,r10
def main():
    o,c,v,_=load_universe(['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'],'2025-01-01','2026-01-01'); datasets=[('1h',o,c,v,24,[(8,24),(12,36),(16,48)]),('4h',*aggregate(o,c,v,'4h'),6,[(3,9),(4,12),(6,18)])]
    rows=[]; returns={}
    for tf,op,cl,vol,bpd,pairs in datasets:
        for fast,slow in pairs:
            continuous=MultiHorizonTrend(fast,slow).target_weights(cl); continuous=enforce_exposure_limits(risk_scale_targets(continuous,cl.pct_change(),bars_per_year=bpd*365))
            for policy in [ExecutionPolicy('Rebalance24h',rebalance_every=24//(24//bpd)),ExecutionPolicy('Phase1_Buffer2pct',absolute_buffer=.02)]:
                row,r=evaluate(f'Trend_{fast}_{slow}',tf,op,cl,continuous,policy,bpd); rows.append(row); returns[f'{tf}_continuous_{fast}_{slow}_{policy.name}']=r.returns
            for entry,exit in [(0.25,0),(0.5,0),(0.75,.25)]:
                state=enforce_exposure_limits(StateTrend(fast,slow,entry,exit).target_weights(cl))
                row,r=evaluate(f'StateTrend_{fast}_{slow}',tf,op,cl,state,ExecutionPolicy('StateFixed'),bpd); row.update({'entry_threshold':entry,'exit_threshold':exit,'risk_sizing_cadence':'entry_only'}); rows.append(row); returns[f'{tf}_state_{fast}_{slow}_{entry}']=r.returns
    table=pd.DataFrame(rows); table['status']=np.where((table.net_10bps>0)&(table.break_even_cost_bps>15),'WATCHLIST','REJECTED'); table.to_csv(ROOT/'results/tables/trend_deep_dive.csv',index=False); pd.DataFrame(returns).to_csv(ROOT/'results/tables/trend_deep_dive_returns.csv')
    table.pivot_table(index='signal_configuration',columns='timeframe',values='net_10bps',aggfunc='max').plot(kind='bar',title='Best 1h vs 4h trend net return at 10 bps'); plt.tight_layout(); plt.savefig(ROOT/'results/plots/trend_timeframe_comparison.png',dpi=150); plt.close()
    print(table.sort_values('net_10bps',ascending=False).head(12).round(4).to_string(index=False))
if __name__=='__main__': main()
