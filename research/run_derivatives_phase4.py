"""Phase 4 funding-data feasibility audit. Requests are hard-capped at 2026-09-20."""
from __future__ import annotations
import csv, json, time, urllib.parse, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend
from derivatives_alpha.phase4 import causal_funding_hourly, coverage_row, future_return
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'results/derivatives_phase4'; RAW=ROOT/'data/derivatives_raw/binance_futures'; PROC=ROOT/'data/derivatives_processed'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','TRXUSDT','UNIUSDT','NEARUSDT']; BASE=SYMS[:5]
START=pd.Timestamp('2025-01-01',tz='UTC'); OOS=pd.Timestamp('2026-01-01',tz='UTC'); SEP=pd.Timestamp('2026-09-01',tz='UTC'); END=pd.Timestamp('2026-09-21',tz='UTC')
def ms(t): return int(t.timestamp()*1000)
def funding(symbol, log):
    """Official Binance Futures endpoint; pagination stops strictly before END."""
    p=RAW/symbol; p.mkdir(parents=True,exist_ok=True); file=p/'funding_rate_2025-01-01_2026-09-20.csv'
    if file.exists():
        x=pd.read_csv(file,parse_dates=['timestamp']); x.timestamp=pd.to_datetime(x.timestamp,utc=True,format='mixed'); log.append({'provider':'Binance Futures','endpoint':'/fapi/v1/fundingRate','symbol':symbol,'start_time_utc':START,'end_time_utc':END-pd.Timedelta(seconds=1),'rows':len(x),'url_parameters':'cached prior request; original cap 2026-09-20T23:59:59Z'}); return x.set_index('timestamp').funding_rate
    rows=[]; cursor=ms(START); limit=1000; end=ms(END)-1
    while cursor<=end:
        q=urllib.parse.urlencode({'symbol':symbol,'startTime':cursor,'endTime':end,'limit':limit}); url='https://fapi.binance.com/fapi/v1/fundingRate?'+q
        with urllib.request.urlopen(url,timeout=30) as r: page=json.load(r)
        log.append({'provider':'Binance Futures','endpoint':'/fapi/v1/fundingRate','symbol':symbol,'start_time_utc':pd.to_datetime(cursor,unit='ms',utc=True),'end_time_utc':pd.to_datetime(end,unit='ms',utc=True),'rows':len(page),'url_parameters':q})
        if not page: break
        rows.extend(page); cursor=int(page[-1]['fundingTime'])+1
        if len(page)<limit: break
        time.sleep(.08)
    x=pd.DataFrame(rows); x['timestamp']=pd.to_datetime(x.fundingTime,unit='ms',utc=True); x['funding_rate']=pd.to_numeric(x.fundingRate); x=x[['timestamp','funding_rate']].drop_duplicates('timestamp').sort_values('timestamp'); x=x[x.timestamp<END]; x.to_csv(file,index=False); return x.set_index('timestamp').funding_rate
def ohlcv(symbol):
    a=[]
    for p in (ROOT/'data/raw').glob(f'{symbol}_1h_*.csv'):
        x=pd.read_csv(p,index_col='timestamp',parse_dates=True); x.index=pd.to_datetime(x.index,utc=True); a.append(x)
    for p in (ROOT/'data/raw/ml_alpha_phase3a1').glob(f'{symbol}_1h_*.csv'):
        x=pd.read_csv(p,index_col='timestamp',parse_dates=True); x.index=pd.to_datetime(x.index,utc=True); a.append(x)
    return pd.concat(a).loc[lambda x:~x.index.duplicated(keep='last')].sort_index().loc[:END-pd.Timedelta(hours=1)]
def trend(c): return enforce_exposure_limits(risk_scale_targets(MultiHorizonTrend(8,24).target_weights(c),c.pct_change(fill_method=None)).fillna(0))
def roll(r,b):
    def w(x):
        d=(1+x).groupby(x.index.floor('D')).prod()-1; return pd.DataFrame({'start':d.index[:-13],'return':[(1+d.iloc[i:i+14]).prod()-1 for i in range(len(d)-13)]})
    a,bb=w(r),w(b); m=a.merge(bb,on='start',suffixes=('','_base')); inc=m['return']-m['return_base']; return {'mean_14d_net_return':a['return'].mean(),'median_14d_net_return':a['return'].median(),'positive_14d_probability':(a['return']>0).mean(),'p_beats_baseline':(inc>0).mean(),'mean_incremental_14d':inc.mean(),'median_incremental_14d':inc.median(),'p10_incremental_14d':inc.quantile(.1)}
def metrics(name,result,base):
    gross=(1+result.gross_returns).prod()-1; ch=result.weights.diff().fillna(result.weights).abs()>1e-12
    return {'strategy':name,'gross_return':gross,'net_return_10bps':(1+result.returns).prod()-1,'turnover':result.turnover.sum(),'fees':result.costs.sum(),'break_even_cost_bps':gross/max(result.turnover.sum(),1e-12)*10000,'asset_orders':int(ch.sum().sum()),'active_rebalances':int(ch.any(axis=1).sum()),**roll(result.returns,base.returns)}
def main():
    OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True); PROC.mkdir(parents=True,exist_ok=True); request_log=[]
    frames={s:ohlcv(s) for s in SYMS}; idx=pd.date_range(START,END-pd.Timedelta(hours=1),freq='h',tz='UTC',name='timestamp'); opens=pd.DataFrame({s:frames[s].open.reindex(idx) for s in SYMS}); closes=pd.DataFrame({s:frames[s].close.reindex(idx) for s in SYMS}); opens.columns.name=closes.columns.name='symbol'
    funds={s:causal_funding_hourly(funding(s,request_log),idx) for s in SYMS}; fp=pd.DataFrame(funds,index=idx); fp.to_csv(PROC/'binance_futures_funding_hourly_causal.csv',index_label='timestamp'); pd.DataFrame(request_log).to_csv(OUT/'EXTERNAL_REQUEST_LOG.csv',index=False)
    expected=len(idx); cov=pd.DataFrame([coverage_row(s,'funding_rate',fp[s],expected) for s in SYMS]); unavailable=[]
    for s in SYMS:
        for v,reason in [('open_interest','Binance historical OI statistics endpoint documents latest one-month availability; insufficient 2025–2026 reproducible depth'),('liquidations','aggregate historical liquidation endpoint not provided by official exchange API with required depth'),('basis','not downloaded: funding-only feasibility path; mark/index archive not established')]: unavailable.append({'asset':s,'variable':v,'first_timestamp':None,'last_timestamp':None,'expected_observations':expected,'actual_observations':0,'coverage_pct':0.,'missing_pct':100.,'maximum_gap_hours':None,'provider':'not used','usable':False,'reason':reason})
    cov=pd.concat([cov,pd.DataFrame(unavailable)],ignore_index=True); cov.to_csv(OUT/'DERIVATIVES_DATA_COVERAGE.csv',index=False)
    eligible=cov.query("variable == 'funding_rate' and usable == True").asset.tolist(); (OUT/'DERIVATIVES_ELIGIBLE_UNIVERSE.json').write_text(json.dumps({'rule':'funding coverage >=95% over 2025-01-01 through 2026-09-20; no long gaps','eligible_assets':eligible,'required_variables':['funding_rate'],'excluded_assets':[s for s in SYMS if s not in eligible]},indent=2))
    audit='''# Phase 4 Data Source Audit\n\nRepository inspection found no derivatives cache, exchange-futures client, CoinGlass configuration, or non-Roostoo credentials. Existing Roostoo credentials are not read or printed.\n\n| Provider | Dataset | Coverage / suitability | Auth | Notes |\n|---|---|---|---|---|\n| Binance Futures | `/fapi/v1/fundingRate` | Public, paginated, 8-hour settlement records; tested through 2026-09-20 only | No | Reproducible; timestamps are settlement/publication times. |\n| Binance Futures | Open-interest statistics | Insufficient: endpoint documents recent/one-month history | No | Not suitable for 2025–2026 research. |\n| Binance Futures | Liquidations | No official historical aggregate endpoint with required depth | No | Unavailable. |\n| Bybit / OKX | Not downloaded | No configured client or verified reproducible archive | Varies | Not used. |\n| CoinGlass | Not downloaded | No credential/configuration found | Paid/API key | Unavailable. |\n\nAll external requests are in `EXTERNAL_REQUEST_LOG.csv`; each is capped before 2026-09-21 UTC. Symbol mapping uses USDⓈ-M perpetual symbols identical to the B1 `USDT` tickers. Funding is sparse (normally 8-hourly) and causally forward-filled only **after** settlement; it is never backward-filled.\n'''; (OUT/'DATA_SOURCE_AUDIT.md').write_text(audit)
    # Features and descriptive conditional returns, computed only through OOS initially.
    ret=future_return(opens,closes,24); fchg=fp.diff(); fmean=fp.rolling(9,min_periods=3).mean(); features={'funding_rate':fp,'funding_change':fchg,'funding_72h_mean':fmean,'funding_abs':fp.abs(),'funding_cs_rank':fp.rank(axis=1,pct=True)}
    rows=[]; ic=[]
    for n,x in features.items():
        stack=pd.DataFrame({'feature':x.stack(future_stack=True),'future_return':ret.stack(future_stack=True)}).dropna(); stack=stack[(stack.index.get_level_values('timestamp')>=OOS)&(stack.index.get_level_values('timestamp')<SEP)]
        for bucket,g in stack.assign(bucket=pd.qcut(stack.feature.rank(method='first'),5,labels=False)).groupby('bucket'):
            y=g.future_return; rows.append({'feature':n,'bucket':int(bucket)+1,'observations':len(y),'mean_future_return':y.mean(),'median_future_return':y.median(),'hit_rate':(y>0).mean(),'standard_error':y.std()/np.sqrt(len(y)),'t_stat_descriptive':y.mean()/(y.std()/np.sqrt(len(y))) if y.std() else np.nan,'p10':y.quantile(.1),'p25':y.quantile(.25),'p75':y.quantile(.75),'p90':y.quantile(.9)})
        dates=stack.groupby(level='timestamp').apply(lambda z:z.feature.rank().corr(z.future_return.rank())); ic.append({'feature':n,'mean_ic':dates.mean(),'median_ic':dates.median(),'positive_ic_date_pct':(dates>0).mean()})
    pd.DataFrame(rows).to_csv(OUT/'DERIVATIVES_FORWARD_RETURN_ANALYSIS.csv',index=False); pd.DataFrame(ic).to_csv(OUT/'DERIVATIVES_CROSS_SECTIONAL_IC.csv',index=False)
    # Development-only funding crowding filter on frozen 5-asset Trend 8/24.
    dev=fp.loc[START:OOS-pd.Timedelta(hours=1),BASE]; hi=dev.stack().quantile(.9); lo=dev.stack().quantile(.1); target=trend(closes[BASE]); # skip crowded longs / crowded shorts, no reversal
    filtered=target.where(~(((target>0)&(fp[BASE]>hi))|((target<0)&(fp[BASE]<lo))),0).fillna(0)
    oi=idx[(idx>=OOS)&(idx<SEP)]; base=run_backtest(opens.loc[oi,BASE],closes.loc[oi,BASE],target.loc[oi],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); rule=run_backtest(opens.loc[oi,BASE],closes.loc[oi,BASE],filtered.loc[oi],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24))
    back=pd.DataFrame([metrics('FROZEN_TREND824',base,base),metrics('TREND824_FUNDING_CROWDING_FILTER',rule,base)]); back.to_csv(OUT/'DERIVATIVES_RULE_BACKTESTS.csv',index=False); back.to_csv(OUT/'DERIVATIVES_14D_RESULTS.csv',index=False)
    states=[]; direction=np.sign(target); cont=ret[BASE]*direction
    for label,mask in [('high_positive_funding',fp[BASE]>hi),('high_negative_funding',fp[BASE]<lo),('neutral_funding',(fp[BASE]<=hi)&(fp[BASE]>=lo))]:
        y=cont.where((direction!=0)&mask).stack().dropna(); states.append({'state':label,'observations':len(y),'trend_continuation_probability':(y>0).mean(),'mean_directional_future_24h_return':y.mean(),'median_directional_future_24h_return':y.median()})
    pd.DataFrame(states).to_csv(OUT/'TREND_CONTINUATION_ANALYSIS.csv',index=False)
    cost=[]
    for name,res in [('FROZEN_TREND824',base),('TREND824_FUNDING_CROWDING_FILTER',rule)]:
        for bps in (5,10,15,20):
            rr=run_backtest(opens.loc[oi,BASE],closes.loc[oi,BASE],res.weights.shift(-1).fillna(0),bps); cost.append({'strategy':name,'cost_bps_per_side':bps,'gross_return':(1+res.gross_returns).prod()-1,'net_return':(1+rr.returns).prod()-1,'fees':rr.costs.sum(),'turnover':res.turnover.sum(),'break_even_cost_bps':((1+res.gross_returns).prod()-1)/max(res.turnover.sum(),1e-12)*10000})
    pd.DataFrame(cost).to_csv(OUT/'DERIVATIVES_COST_STRESS.csv',index=False)
    best=back.iloc[1]; survives=best.net_return_10bps>base.returns.add(1).prod()-1 and best.mean_incremental_14d>0
    decision='MIXED — DERIVATIVES SIGNAL EXISTS BUT ECONOMIC EDGE IS NOT YET ROBUST' if survives else 'REJECT — NO ROBUST INCREMENTAL DERIVATIVES ALPHA'
    report=f'# Phase 4 Report\n\n**{decision}.**\n\nData availability: funding is reproducibly available for {len(eligible)}/13 assets; OI, liquidations and basis fail the historical-data feasibility screen. Predictive evidence is recorded in the univariate and IC files. Economic test used one predeclared development-calibrated crowding filter; it was not tuned on 2026 or September. Its Jan–Aug OOS net return was {best.net_return_10bps:.2%}, versus baseline {(1+base.returns).prod()-1:.2%}; mean 14d incremental return {best.mean_incremental_14d:.2%}.\n\nNo candidate reached the required economic validation threshold, so Sep 1–20 was **not evaluated as a strategy holdout**. No ML or ablation was justified. Further research should obtain reliable historical OI/liquidation/basis data rather than add OHLCV transformations.\n'; (OUT/'PHASE4_REPORT.md').write_text(report)
    pd.DataFrame([{'experiment':'funding feasibility + one predeclared trend crowding filter','development':'2025 only','oos':'2026-01-01 to 2026-08-31','fresh_sep_evaluated':False,'decision':decision}]).to_csv(OUT/'EXPERIMENT_LOG.csv',index=False)
    print(f'PHASE 4 SUMMARY\nData providers used: Binance Futures\nEligible universe: {len(eligible)}/13\nFunding: usable yes; coverage {cov.query("variable == \'funding_rate\'").coverage_pct.min():.1f}% minimum\nOpen interest: usable no\nLiquidations: usable no\nBasis: usable no\nBest simple derivatives signal: TREND824_FUNDING_CROWDING_FILTER\nBest OOS net return @10bps: {best.net_return_10bps:.2%}\nMedian 14d net return: {best.median_14d_net_return:.2%}\nPositive 14d probability: {best.positive_14d_probability:.1%}\nP(beat Frozen Trend 8/24): {best.p_beats_baseline:.1%}\nBreak-even transaction cost: {best.break_even_cost_bps:.2f}bps\nWas ML justified? No\nWas Sep 1–20 fresh validation used? No\nFinal decision: {decision}')
if __name__=='__main__': main()
