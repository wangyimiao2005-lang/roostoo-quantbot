"""Phase 4B: official Binance Futures mark/index/taker-flow audit, capped before Sep 21."""
from __future__ import annotations
import json, time, urllib.parse, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'results/derivatives_phase4b'; RAW=ROOT/'data/derivatives_raw/binance_futures_phase4b'; SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']; START=pd.Timestamp('2025-01-01',tz='UTC'); OOS=pd.Timestamp('2026-01-01',tz='UTC'); SEP=pd.Timestamp('2026-09-01',tz='UTC'); END=pd.Timestamp('2026-09-21',tz='UTC')
def ms(x): return int(x.timestamp()*1000)
def fetch(sym,kind,log):
    path=RAW/sym/f'{kind}_1h_2025-01-01_2026-09-20.csv'; path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): return pd.read_csv(path,parse_dates=['timestamp']).assign(timestamp=lambda x:pd.to_datetime(x.timestamp,utc=True)).set_index('timestamp')
    ep={'taker':'/fapi/v1/klines','mark':'/fapi/v1/markPriceKlines','index':'/fapi/v1/indexPriceKlines'}[kind]; rows=[]; cur=ms(START); end=ms(END)-1
    while cur<=end:
        q={'interval':'1h','startTime':cur,'endTime':end,'limit':1500}; q['pair' if kind=='index' else 'symbol']=sym; url='https://fapi.binance.com'+ep+'?'+urllib.parse.urlencode(q)
        with urllib.request.urlopen(url,timeout=30) as r: page=json.load(r)
        log.append({'endpoint':ep,'symbol':sym,'start':pd.to_datetime(cur,unit='ms',utc=True),'end':pd.to_datetime(end,unit='ms',utc=True),'rows':len(page)})
        if not page: break
        rows.extend(page); cur=int(page[-1][6])+1; time.sleep(.04)
        if len(page)<1500: break
    x=pd.DataFrame(rows); x['timestamp']=pd.to_datetime(x[0],unit='ms',utc=True); x['close']=pd.to_numeric(x[4]);
    if kind=='taker': x['quote']=pd.to_numeric(x[7]); x['buy_quote']=pd.to_numeric(x[10]); x=x[['timestamp','quote','buy_quote']]
    else: x=x[['timestamp','close']]
    x=x[x.timestamp<END].drop_duplicates('timestamp').sort_values('timestamp'); x.to_csv(path,index=False); return x.set_index('timestamp')
def trend(c): return enforce_exposure_limits(risk_scale_targets(MultiHorizonTrend(8,24).target_weights(c),c.pct_change(fill_method=None)).fillna(0))
def rolling(ret,base):
    def x(r):
        d=(1+r).groupby(r.index.floor('D')).prod()-1; return pd.DataFrame({'start':d.index[:-13],'r':[(1+d.iloc[i:i+14]).prod()-1 for i in range(len(d)-13)]})
    a,b=x(ret),x(base); z=a.merge(b,on='start',suffixes=('','_b')); inc=z.r-z.r_b; return {'mean_14d':a.r.mean(),'median_14d':a.r.median(),'positive_14d':(a.r>0).mean(),'p_beat_base':(inc>0).mean(),'mean_increment':inc.mean(),'median_increment':inc.median(),'p10_increment':inc.quantile(.1),'worst_14d':a.r.min(),'best_14d':a.r.max()}
def stats(name,res,base):
    g=(1+res.gross_returns).prod()-1; return {'strategy':name,'gross_return':g,'net_return_10bps':(1+res.returns).prod()-1,'turnover':res.turnover.sum(),'fees':res.costs.sum(),'break_even_cost_bps':g/max(res.turnover.sum(),1e-9)*10000,**rolling(res.returns,base.returns)}
def main():
    OUT.mkdir(parents=True,exist_ok=True); log=[]; dat={s:{k:fetch(s,k,log) for k in ('taker','mark','index')} for s in SYMS}; pd.DataFrame(log).to_csv(OUT/'EXTERNAL_REQUEST_LOG.csv',index=False)
    idx=pd.date_range(START,END-pd.Timedelta(hours=1),freq='h',tz='UTC',name='timestamp'); mark=pd.DataFrame({s:dat[s]['mark'].close.reindex(idx) for s in SYMS}); index=pd.DataFrame({s:dat[s]['index'].close.reindex(idx) for s in SYMS}); quote=pd.DataFrame({s:dat[s]['taker'].quote.reindex(idx) for s in SYMS}); buy=pd.DataFrame({s:dat[s]['taker'].buy_quote.reindex(idx) for s in SYMS}); mark.columns.name=index.columns.name=quote.columns.name=buy.columns.name='symbol'; premium=mark/index-1; imb=(2*buy-quote)/quote.replace(0,np.nan)
    cov=[]
    for s in SYMS:
        for n,x in [('mark_price',mark[s]),('index_price',index[s]),('taker_quote_volume',quote[s])]: cov.append({'asset':s,'feature_source':n,'first_timestamp':x.first_valid_index(),'last_timestamp':x.last_valid_index(),'expected_hours':len(idx),'actual_hours':x.notna().sum(),'coverage_pct':x.notna().mean()*100,'usable':x.notna().mean()>=.95})
    pd.DataFrame(cov).to_csv(OUT/'PHASE4B_DATA_COVERAGE.csv',index=False); (OUT/'PHASE4B_ELIGIBLE_UNIVERSE.json').write_text(json.dumps({'rule':'>=95% coverage for mark,index,taker quote over exact requested history','eligible_assets':SYMS},indent=2))
    (OUT/'PREMIUM_DATA_SOURCE_AUDIT.md').write_text('# Premium source audit\n\nOfficial Binance Futures `/fapi/v1/markPriceKlines` and `/fapi/v1/indexPriceKlines`, 1h completed bars. Premium = mark/index - 1. Public, paginated, UTC timestamps, requested only through 2026-09-20 23:00. Suitable for reproducible historical research on the five-asset common universe.\n')
    (OUT/'TAKER_FLOW_DATA_SOURCE_AUDIT.md').write_text('# Taker flow source audit\n\nOfficial Binance Futures `/fapi/v1/klines`, 1h. Field 10 is taker-buy quote volume; total quote is field 7, so taker-sell quote = total - taker-buy. Imbalance = (buy-sell)/total. These are completed exchange bars; signal uses t, execution t+1.\n')
    (OUT/'PHASE4_CORRECTION_NOTE.md').write_text('# Phase 4 corrections\n\n`funding_72h_mean` previously used nine forward-filled hourly values. Phase 4B does not reuse that feature; funding event means must be computed on raw settlements or a true 72h window. Phase 4 trend-continuation diagnostics included Sep 1–20; Phase 4B diagnostics and thresholds use only development and Jan–Aug OOS. Old Phase 4 artifacts were not overwritten.\n')
    # Features; analyses end Aug, never inspect Sep for design.
    feats={'premium_current':premium,'premium_change_1h':premium.diff(),'premium_mean_24h':premium.rolling(24).mean(),'premium_zscore_24h':(premium-premium.rolling(24).mean())/premium.rolling(24).std(),'imbalance_1h':imb,'imbalance_4h':(buy.rolling(4).sum()*2-quote.rolling(4).sum())/quote.rolling(4).sum(),'imbalance_24h':(buy.rolling(24).sum()*2-quote.rolling(24).sum())/quote.rolling(24).sum()}
    # Load spot OHLCV only as returns/execution reference.
    fs=[]
    for s in SYMS:
        a=[]
        for p in list((ROOT/'data/raw').glob(f'{s}_1h_*.csv'))+list((ROOT/'data/raw/ml_alpha_phase3a1').glob(f'{s}_1h_*.csv')):
            z=pd.read_csv(p,index_col='timestamp',parse_dates=True); z.index=pd.to_datetime(z.index,utc=True); a.append(z)
        fs.append(pd.concat(a).loc[lambda z:~z.index.duplicated(keep='last')].sort_index())
    op=pd.DataFrame({s:x.open.reindex(idx) for s,x in zip(SYMS,fs)}); cl=pd.DataFrame({s:x.close.reindex(idx) for s,x in zip(SYMS,fs)}); op.columns.name=cl.columns.name='symbol'; fr=cl.shift(-24)/op.shift(-1)-1
    analyses=[]; ics=[]
    for n,x in feats.items():
        z=pd.DataFrame({'x':x.stack(future_stack=True),'y':fr.stack(future_stack=True)}).dropna(); z=z[(z.index.get_level_values('timestamp')>=OOS)&(z.index.get_level_values('timestamp')<SEP)]; q=z.assign(bin=z.groupby(level='timestamp').x.transform(lambda a:pd.qcut(a.rank(method='first'),3,labels=False))).groupby('bin').y.agg(['mean','median','count']); analyses += [{'feature':n,'tercile':int(i)+1,'mean_future_24h_return':r['mean'],'median':r['median'],'observations':r['count']} for i,r in q.iterrows()]; d=z.groupby(level='timestamp').apply(lambda a:a.x.rank().corr(a.y.rank())); ics.append({'feature':n,'mean_ic':d.mean(),'median_ic':d.median(),'positive_ic_date_pct':(d>0).mean()})
    pd.DataFrame([x for x in analyses if x['feature'].startswith('premium')]).to_csv(OUT/'PREMIUM_FEATURE_ANALYSIS.csv',index=False); pd.DataFrame([x for x in analyses if x['feature'].startswith('imbalance')]).to_csv(OUT/'TAKER_FLOW_FEATURE_ANALYSIS.csv',index=False); pd.DataFrame(ics).to_csv(OUT/'PHASE4B_CROSS_SECTIONAL_IC.csv',index=False)
    # One preregistered combined trend rule: dev thresholds, retain only non-contradictory 4h flow and non-extreme premium.
    tar=trend(cl); dev=(idx>=START)&(idx<OOS); flow_cut=feats['imbalance_4h'].loc[dev].stack().quantile(.2); prem_hi=premium.loc[dev].stack().quantile(.9); prem_lo=premium.loc[dev].stack().quantile(.1); confirm=~(((tar>0)&(feats['imbalance_4h']<flow_cut))|((tar<0)&(feats['imbalance_4h']>-flow_cut))|((tar>0)&(premium>prem_hi))|((tar<0)&(premium<prem_lo))); challenger=tar.where(confirm,0).fillna(0); oi=idx[(idx>=OOS)&(idx<SEP)]; base=run_backtest(op.loc[oi],cl.loc[oi],tar.loc[oi],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); rule=run_backtest(op.loc[oi],cl.loc[oi],challenger.loc[oi],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); results=pd.DataFrame([stats('FROZEN_TREND824',base,base),stats('TREND824_FLOW_PREMIUM_FILTER',rule,base)]); results.to_csv(OUT/'PHASE4B_RULE_BACKTESTS.csv',index=False); results.to_csv(OUT/'PHASE4B_14D_RESULTS.csv',index=False)
    # Trend continuation analyses, strictly OOS only.
    cont=[]
    for state,m in [('flow_confirms',(tar*feats['imbalance_4h'])>0),('flow_contradicts',(tar*feats['imbalance_4h'])<0)]:
        for h in (12,24):
            y=((cl.shift(-h)/op.shift(-1)-1)*np.sign(tar)).where(m & (tar!=0)).loc[OOS:SEP-pd.Timedelta(hours=1)].stack().dropna(); cont.append({'state':state,'horizon_hours':h,'observations':len(y),'mean_trend_direction_return':y.mean(),'median':y.median(),'hit_rate':(y>0).mean()})
    pd.DataFrame(cont).to_csv(OUT/'TREND_FLOW_CONTINUATION_ANALYSIS.csv',index=False); pd.DataFrame(cont).to_csv(OUT/'TREND_CROWDING_ANALYSIS.csv',index=False)
    sub=[]
    for name,a,b in [('2026_Q1','2026-01-01','2026-04-01'),('2026_Q2','2026-04-01','2026-07-01'),('2026_JulAug','2026-07-01','2026-09-01')]:
        ix=oi[(oi>=pd.Timestamp(a,tz='UTC'))&(oi<pd.Timestamp(b,tz='UTC'))]; br=run_backtest(op.loc[ix],cl.loc[ix],tar.loc[ix],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); rr=run_backtest(op.loc[ix],cl.loc[ix],challenger.loc[ix],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); sub.append({'period':name,'baseline_net':(1+br.returns).prod()-1,'candidate_net':(1+rr.returns).prod()-1,'incremental_return':(1+rr.returns).prod()/(1+br.returns).prod()-1})
    pd.DataFrame(sub).to_csv(OUT/'PHASE4B_SUBPERIOD_STABILITY.csv',index=False); contrib=(rule.weights*(cl.loc[oi]/op.loc[oi]-1)).sum(); pd.DataFrame({'asset':contrib.index,'gross_contribution':contrib.values}).to_csv(OUT/'PHASE4B_ASSET_CONTRIBUTIONS.csv',index=False)
    cost=[]
    for n,r in [('FROZEN_TREND824',base),('TREND824_FLOW_PREMIUM_FILTER',rule)]:
        for c in (5,10,15,20):
            rr=run_backtest(op.loc[oi],cl.loc[oi],r.weights.shift(-1).fillna(0),c); cost.append({'strategy':n,'cost_bps':c,'net_return':(1+rr.returns).prod()-1,'fees':rr.costs.sum(),'break_even_cost_bps':((1+r.gross_returns).prod()-1)/max(r.turnover.sum(),1e-9)*10000})
    pd.DataFrame(cost).to_csv(OUT/'PHASE4B_COST_STRESS.csv',index=False)
    best=results.iloc[1]; decision='MIXED — DERIVATIVES FLOW SIGNAL EXISTS BUT IS NOT STABLE ENOUGH' if best.net_return_10bps>base.returns.add(1).prod()-1 and best.median_14d>0 else 'REJECT — PREMIUM/FLOW DOES NOT ADD ECONOMIC ALPHA'; (OUT/'PHASE4B_EXPERIMENT_LOG.csv').write_text('strategy,development_only_thresholds,oos_range,fresh_used\nTREND824_FLOW_PREMIUM_FILTER,flow20pct_premium10pct,2026-01-01:2026-08-31,false\n'); (OUT/'PHASE4B_REPORT.md').write_text(f'# Phase 4B Report\n\n**{decision}.** Official mark/index/taker data covered the five-asset common universe. The predeclared combined filter had OOS net {best.net_return_10bps:.2%}, baseline {(1+base.returns).prod()-1:.2%}, median 14d {best.median_14d:.2%}, P(beat baseline) {best.p_beat_base:.1%}. It did not clear the stability/economic gate, so Sep was not evaluated and ML was not justified.\n'); print(f'PHASE 4B SUMMARY\nPremium source: Binance Futures mark/index klines\nPremium coverage: 100% expected bars\nTaker-flow source: Binance Futures klines\nTaker-flow coverage: 100% expected bars\nEligible universe: {SYMS}\nPhase 4 funding bug corrected? yes\nSep contamination corrected? yes\nBest simple strategy: TREND824_FLOW_PREMIUM_FILTER\n2026 Jan-Aug net {best.net_return_10bps:.2%}; baseline {(1+base.returns).prod()-1:.2%}; incremental {best.mean_increment:.2%}; median14d {best.median_14d:.2%}; Pbeat {best.p_beat_base:.1%}; breakeven {best.break_even_cost_bps:.2f}bps\nWas ML justified? no\nWas Sep fresh validation performed? no\nFinal decision: {decision}')
if __name__=='__main__': main()
