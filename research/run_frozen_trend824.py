"""One-shot frozen validation. Candidate and 2026-01-01:2026-09-01 OOS are fixed here."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from common import ROOT
from quant_competition.strategies import MultiHorizonTrend
from quant_competition.portfolio import enforce_exposure_limits, risk_scale_targets, ExecutionPolicy
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics, rolling_competition_metrics
from quant_competition.metrics.drawdown import drawdown
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']; DEV_END='2026-01-01'; OOS_START='2026-01-01'; OOS_END='2026-09-01'
def load_range(start,end):
    fs={}
    for s in SYMS:
        f=pd.read_csv(ROOT/f'data/raw/{s}_1h_{start}_{end}.csv',index_col='timestamp',parse_dates=True); f.index=pd.to_datetime(f.index,utc=True); fs[s]=f
    idx=next(iter(fs.values())).index
    for f in fs.values(): idx=idx.intersection(f.index)
    return (pd.DataFrame({s:f.loc[idx,c] for s,f in fs.items()}) for c in ['open','close','volume'])
def targets(close):
    raw=MultiHorizonTrend(8,24).target_weights(close); return enforce_exposure_limits(risk_scale_targets(raw,close.pct_change()))
def stats(o,c,t,cost=10):
    r=run_backtest(o,c,t,cost,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); m=performance_metrics(r.returns,r.costs,r.turnover); roll=rolling_competition_metrics(r.returns)
    gross=(1+r.gross_returns).prod()-1
    return r,{'gross_return':gross,'net_return':(1+r.returns).prod()-1,'sharpe':m['sharpe'],'sortino':m['sortino'],'calmar':m['calmar'],'max_drawdown':m['max_drawdown'],'turnover':m['turnover'],'trades':len(r.trades),'trades_per_14d':len(r.trades)/(len(r.returns)/336),'median_14d_return':roll['median_14d_return'],'positive_14d_probability':roll['positive_14d_probability'],'break_even_cost_bps':gross/max(m['turnover'],1e-9)*10000}
def main():
    do,dc,dv=load_range('2025-01-01','2026-01-01'); oo,oc,ov=load_range('2026-01-01','2026-09-01'); o=pd.concat([do,oo]); c=pd.concat([dc,oc]); t=targets(c); oos_o=o.loc[OOS_START:]; oos_c=c.loc[OOS_START:]; oos_t=t.loc[OOS_START:]
    r,base=stats(oos_o,oos_c,oos_t); row={'development_dates':'2025-01-01:2025-12-31 (candidate previously selected)','oos_dates':'2026-01-01:2026-08-31 (untouched before Phase 1.7)',**base}
    for bps in [5,15,20]: row[f'net_{bps}bps']=stats(oos_o,oos_c,oos_t,bps)[1]['net_return']
    intrabar= oos_c.div(oos_o).sub(1); gross_by=(r.weights*intrabar); costs_by=r.weights.diff().fillna(r.weights).abs()*.001; net_by=gross_by-costs_by
    row['long_contribution']=gross_by.where(r.weights>0,0).sum().sum()-costs_by.where(r.weights>0,0).sum().sum(); row['short_contribution']=gross_by.where(r.weights<0,0).sum().sum()-costs_by.where(r.weights<0,0).sum().sum(); row['status']='SURVIVES' if row['net_return']>0 and row['break_even_cost_bps']>10 else 'REJECTED'
    pd.DataFrame([row]).to_csv(ROOT/'results/tables/frozen_oos_trend824.csv',index=False)
    # Predeclared local grid is diagnostic only; candidate is not replaced.
    rows=[]
    for fast in [6,8,10]:
        for slow in [20,24,28]:
            tt=enforce_exposure_limits(risk_scale_targets(MultiHorizonTrend(fast,slow).target_weights(c),c.pct_change())).loc[OOS_START:]; _,m=stats(oos_o,oos_c,tt); rows.append({'fast':fast,'slow':slow,**m})
    pd.DataFrame(rows).to_csv(ROOT/'results/tables/trend824_local_robustness.csv',index=False)
    # calendar and asset attribution for development+new OOS, explicitly labelled descriptive.
    fullr, _=stats(o,c,t); yearly=[]
    for year in sorted(set(c.index.year)):
        mask=c.index.year==year; rr=fullr.returns[mask]; yearly.append({'year':year,**performance_metrics(rr,fullr.costs[mask],fullr.turnover[mask]),'gross_return':(1+fullr.gross_returns[mask]).prod()-1,'trades':len(fullr.trades[fullr.trades.timestamp.dt.year==year])})
    pd.DataFrame(yearly).to_csv(ROOT/'results/tables/trend824_yearly.csv',index=False)
    attrs=[]
    for s in SYMS: attrs.append({'asset':s,'gross_contribution':gross_by[s].sum(),'net_contribution':net_by[s].sum(),'cost':costs_by[s].sum(),'turnover':r.weights[s].diff().abs().sum(),'trades':int((r.weights[s].diff().abs()>1e-12).sum()),'long_contribution':gross_by[s].where(r.weights[s]>0,0).sum()-costs_by[s].where(r.weights[s]>0,0).sum(),'short_contribution':gross_by[s].where(r.weights[s]<0,0).sum()-costs_by[s].where(r.weights[s]<0,0).sum()})
    pd.DataFrame(attrs).to_csv(ROOT/'results/tables/trend824_asset_attribution.csv',index=False)
    pd.DataFrame([{'side':'long','net_contribution':row['long_contribution']},{'side':'short','net_contribution':row['short_contribution']},{'side':'combined','net_contribution':row['net_return']}]).to_csv(ROOT/'results/tables/trend824_long_short.csv',index=False)
    rolling=(1+r.returns).rolling(336).apply(np.prod,raw=True)-1; rolling_dd=r.returns.rolling(336).apply(lambda x: drawdown(pd.Series(x)).min(),raw=False)
    dist=[]
    for label,x in [('all',rolling),*[(str(y),rolling[rolling.index.year==y]) for y in sorted(set(rolling.index.year))]]:
        x=x.dropna(); d=rolling_dd.reindex(x.index).dropna(); dist.append({'period':label,'mean_14d_return':x.mean(),'median_14d_return':x.median(),'p_positive':(x>0).mean(),'p_gt_1pct':(x>.01).mean(),'p_gt_2pct':(x>.02).mean(),'p_gt_5pct':(x>.05).mean(),'p10':x.quantile(.1),'p25':x.quantile(.25),'p75':x.quantile(.75),'p90':x.quantile(.9),'worst':x.min(),'best':x.max(),'median_14d_turnover':r.turnover.rolling(336).sum().median(),'median_14d_cost':r.costs.rolling(336).sum().median(),'median_14d_trades':len(r.trades)/(len(r.returns)/336),'median_14d_max_dd':d.median(),'p_dd_lt_5pct':(d>-.05).mean(),'p_dd_lt_10pct':(d>-.10).mean()})
    pd.DataFrame(dist).to_csv(ROOT/'results/tables/trend824_14d_distribution.csv',index=False)
    p=ROOT/'results/plots'; eq=(1+r.returns).cumprod(); pd.DataFrame({'gross':(1+r.gross_returns).cumprod(),'net':eq}).plot(title='Frozen OOS Trend 8/24 gross vs net'); plt.tight_layout(); plt.savefig(p/'trend824_frozen_oos_equity.png',dpi=150); plt.close(); drawdown(r.returns).plot(title='Frozen OOS drawdown'); plt.tight_layout(); plt.savefig(p/'trend824_frozen_oos_drawdown.png',dpi=150); plt.close(); pd.DataFrame(rows).pivot(index='fast',columns='slow',values='net_return').plot(kind='bar',title='Local OOS robustness at 10bps'); plt.tight_layout(); plt.savefig(p/'trend824_local_robustness.png',dpi=150); plt.close()
    print(pd.DataFrame([row]).round(4).to_string(index=False)); print(pd.DataFrame(rows).pivot(index='fast',columns='slow',values='net_return').round(4))
if __name__=='__main__': main()
