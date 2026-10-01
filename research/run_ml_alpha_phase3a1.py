"""Phase 3A.1 audit rerun: frozen development preprocessing and Sep 1--20 test only."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend
from ml_alpha.phase3a import (UNIVERSE, FEATURE_COLUMNS, FrozenPreprocessor, RidgeRegressor, StumpBoostingRegressor, build_features, build_labels, rank_targets, rolling_14d)

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'results/ml_alpha_phase3a1'
DEV_START=pd.Timestamp('2025-01-01',tz='UTC'); OOS_START=pd.Timestamp('2026-01-01',tz='UTC'); SEP_START=pd.Timestamp('2026-09-01',tz='UTC'); SEP_END=pd.Timestamp('2026-09-21',tz='UTC')
def load(symbol):
    parts=[]
    for p in list((ROOT/'data/raw').glob(f'{symbol}_1h_*.csv'))+list((ROOT/'data/raw/ml_alpha_phase3a1').glob(f'{symbol}_1h_*.csv')):
        x=pd.read_csv(p,index_col='timestamp',parse_dates=True); x.index=pd.to_datetime(x.index,utc=True); parts.append(x)
    return pd.concat(parts).loc[lambda x:~x.index.duplicated(keep='last')].sort_index().loc[:SEP_END-pd.Timedelta(hours=1)]
def panels(frames): return [pd.DataFrame({s:frames[s][c] for s in UNIVERSE}) for c in ('open','high','low','close','volume')]
def trend(close): return enforce_exposure_limits(risk_scale_targets(MultiHorizonTrend(8,24).target_weights(close),close.pct_change(fill_method=None)).fillna(0))
def spearman(a,b): return a.rank().corr(b.rank())
def fit_models(train, valid, prep):
    xtr=prep.transform(train[FEATURE_COLUMNS]); xv=prep.transform(valid[FEATURE_COLUMNS]); choices=[]
    for name,params in [('ridge',{'alpha':1.}),('ridge',{'alpha':10.}),('tree',{'iterations':30,'learning_rate':.05,'max_features':12}),('tree',{'iterations':50,'learning_rate':.05,'max_features':16})]:
        m=RidgeRegressor(**params) if name=='ridge' else StumpBoostingRegressor(**params); m.fit(xtr,train.future_excess); z=pd.DataFrame({'p':m.predict(xv),'y':valid.future_excess},index=valid.index)
        choices.append({'model':name,'params':params,'validation_mean_ic':z.groupby(level='timestamp').apply(lambda q:spearman(q.p,q.y)).mean()})
    return choices
def result_metrics(name,res,base,view='daily'):
    w=rolling_14d(res.returns,res.costs,res.turnover,view); bw=rolling_14d(base.returns,base.costs,base.turnover,view); m=w.merge(bw[['window_start','return']],on='window_start',suffixes=('','_baseline')); inc=m['return']-m['return_baseline']
    changes=res.weights.diff().fillna(res.weights).abs()>1e-12; orders=changes.sum(axis=1); active=(orders>0).astype(int)
    gross=(1+res.gross_returns).prod()-1
    return {'strategy':name,'view':view,'full_oos_gross_return':gross,'full_oos_net_return':(1+res.returns).prod()-1,'mean_14d_net_return':w['return'].mean(),'median_14d_net_return':w['return'].median(),'positive_14d_probability':(w['return']>0).mean(),'p25_14d_return':w['return'].quantile(.25),'p10_14d_return':w['return'].quantile(.1),'p5_14d_return':w['return'].quantile(.05),'worst_14d_return':w['return'].min(),'best_14d_return':w['return'].max(),'mean_14d_max_drawdown':w.max_drawdown.mean(),'turnover':res.turnover.sum(),'fees':res.costs.sum(),'break_even_transaction_cost_bps':gross/max(res.turnover.sum(),1e-12)*10000,'mean_matched_incremental_14d':inc.mean(),'median_matched_incremental_14d':inc.median(),'p_beats_baseline':(inc>0).mean(),'asset_level_executed_orders':int(orders.sum()),'active_rebalance_timestamps':int(active.sum())}, w, m
def cost_rows(name,res,opens,closes):
    out=[]
    for c in (5,10,15,20):
        # targets shifted back once reproduce the already executed weights under next-bar engine semantics.
        rr=run_backtest(opens[res.weights.columns],closes[res.weights.columns],res.weights.shift(-1).fillna(0),c)
        out.append({'strategy':name,'cost_bps_per_side':c,'gross_return':(1+res.gross_returns).prod()-1,'net_return':(1+rr.returns).prod()-1,'turnover':res.turnover.sum(),'fees':rr.costs.sum(),'break_even_cost_bps':((1+res.gross_returns).prod()-1)/max(res.turnover.sum(),1e-12)*10000})
    return out
def main():
    OUT.mkdir(parents=True,exist_ok=True); frames={s:load(s) for s in UNIVERSE}; opens,highs,lows,closes,volumes=panels(frames)
    assert all(len(frames[s].loc[SEP_START:SEP_END-pd.Timedelta(hours=1)])==480 for s in UNIVERSE), 'fresh universe must be complete'
    f=build_features(opens,highs,lows,closes,volumes); data=f.join(build_labels(opens,closes)).dropna(subset=['future_excess']); data=data[data.index.get_level_values('timestamp').hour==0]
    train=data[(data.index.get_level_values('timestamp')>=DEV_START)&(data.index.get_level_values('timestamp')<OOS_START)]; fit=train[train.index.get_level_values('timestamp')<pd.Timestamp('2025-10-01',tz='UTC')]; valid=train[train.index.get_level_values('timestamp')>=pd.Timestamp('2025-10-01',tz='UTC')]
    selection_prep=FrozenPreprocessor.fit(fit[FEATURE_COLUMNS])  # validation never informs its own transform
    audit=fit_models(fit,valid,selection_prep); selected=max(audit,key=lambda x:x['validation_mean_ic']); # this is the historical, development-only selection.
    prep=FrozenPreprocessor.fit(train[FEATURE_COLUMNS])  # final frozen transform, fitted after model selection on all development data only
    frozen_preprocessing=prep.as_dict(); frozen_preprocessing['selection_preprocessing_fit_sample']='2025-01-01 through 2025-09-30 UTC'; frozen_preprocessing['final_model_preprocessing_fit_sample']='2025-01-01 through 2025-12-31 UTC'; (OUT/'FROZEN_PREPROCESSING.json').write_text(json.dumps(frozen_preprocessing,sort_keys=True,indent=2))
    audit_text='# Model Selection Audit\n\nTrain: 2025-01-01–2025-09-30. Validation: 2025-10-01–2025-12-31. Selection statistic: mean daily Spearman IC.\n\n'+pd.DataFrame([{**x,'params':json.dumps(x['params'],sort_keys=True)} for x in audit]).to_markdown(index=False)+'\n\n**Development-selected model: '+selected['model']+'**. Ridge was '+('the' if selected['model']=='ridge' else 'not the')+' development-selected model. Tree is labelled `EXPLORATORY_OOS_CHALLENGER` because its interest arose from the original OOS report rather than being promoted as a selected production candidate.\n'
    (OUT/'MODEL_SELECTION_AUDIT.md').write_text(audit_text)
    xtrain=prep.transform(train[FEATURE_COLUMNS]); models={}; scores={}; gates={}
    for name in ('ridge','tree'):
        choice=max([x for x in audit if x['model']==name],key=lambda x:x['validation_mean_ic']); m=RidgeRegressor(**choice['params']) if name=='ridge' else StumpBoostingRegressor(**choice['params']); m.fit(xtrain,train.future_excess); models[name]=(m,choice); p=pd.Series(m.predict(xtrain),index=train.index).unstack('symbol'); gates[name]=float((p.max(axis=1)-p.min(axis=1)).median())
    manifest={'phase':'3A.1','created_before_fresh_holdout_evaluation':True,'universe':UNIVERSE,'feature_list':FEATURE_COLUMNS,'feature_correction':'return_minus_market = return_24h - equal_weight_market_return_24h','training_sample':'2025-01-01 through 2025-12-31 UTC','validation_sample':'2025-10-01 through 2025-12-31 UTC','selected_model':selected,'ridge':models['ridge'][1],'tree':{**models['tree'][1],'status':'EXPLORATORY_OOS_CHALLENGER'},'forecast_horizon_hours':24,'signal_schedule':'00:00 UTC daily','execution':'next bar only','portfolio':'top 3 long / bottom 3 short; equal weights; gross 1.0; asset 1/6 < 0.35; daily rebalance','cost_bps_per_side':10,'gates_development_only':gates,'ml_filter':'retain above selected-model development p50; half size p33-p50; skip below p33'}
    raw=json.dumps(manifest,sort_keys=True).encode(); manifest['sha256']=hashlib.sha256(raw).hexdigest(); (OUT/'PHASE3A1_FREEZE_MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2))
    def evaluate(start,end,label):
        subset=data[(data.index.get_level_values('timestamp')>=start)&(data.index.get_level_values('timestamp')<end)]; x=prep.transform(subset[FEATURE_COLUMNS]); ix=closes.index[(closes.index>=start)&(closes.index<end)]
        base=run_backtest(opens.loc[ix,UNIVERSE[:5]],closes.loc[ix,UNIVERSE[:5]],trend(closes[UNIVERSE[:5]]).loc[ix],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24)); r={'FROZEN_TREND824':base}
        mom=rank_targets(subset['return_24h']); r['MOMENTUM_24H']=run_backtest(opens.loc[ix],closes.loc[ix],mom.reindex(ix).fillna(0),10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24))
        select_scores=None
        for name in ('ridge','tree'):
            p=pd.Series(models[name][0].predict(x),index=subset.index); target=rank_targets(p,gate=gates[name]); r[f'{name.upper()}_RANKING']=run_backtest(opens.loc[ix],closes.loc[ix],target.reindex(ix).fillna(0),10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24))
            if name==selected['model']: select_scores=p
        q33,q50=pd.Series(models[selected['model']][0].predict(xtrain),index=train.index).quantile([.33,.5]); filt=trend(closes[UNIVERSE]); sm=select_scores.unstack('symbol').reindex(columns=UNIVERSE); filt=filt.where(sm>=q33,0).where(~((sm>=q33)&(sm<q50)),filt*.5).fillna(0)
        r['ML_FILTERED_TREND824']=run_backtest(opens.loc[ix,UNIVERSE[:5]],closes.loc[ix,UNIVERSE[:5]],filt[UNIVERSE[:5]].loc[ix],10,execution_policy=ExecutionPolicy('Rebalance24h',rebalance_every=24))
        rows=[]; windows=[]
        for n,z in r.items():
            row,w,matched=result_metrics(n,z,base); row['period']=label; rows.append(row); windows.append(matched.assign(strategy=n,period=label));
        return r,pd.DataFrame(rows),pd.concat(windows,ignore_index=True),subset
    oos,oos_rows,oos_windows,oos_data=evaluate(OOS_START,SEP_START,'2026_JanAug_clean'); fresh,fresh_rows,fresh_windows,fresh_data=evaluate(SEP_START,SEP_END,'2026_Sep01_20_fresh')
    oos_rows.to_csv(OUT/'PHASE3A1_CLEAN_OOS_RESULTS.csv',index=False); fresh_rows.to_csv(OUT/'PHASE3A1_FRESH_HOLDOUT_RESULTS.csv',index=False); fresh_windows.to_csv(OUT/'PHASE3A1_FRESH_14D_WINDOWS.csv',index=False); pd.concat([oos_windows,fresh_windows],ignore_index=True).to_csv(OUT/'PHASE3A1_INCREMENTAL_VS_BASELINE.csv',index=False)
    cost=[]
    for group,oo,cc,results in [('clean_oos',opens.loc[OOS_START:SEP_START-pd.Timedelta(hours=1)],closes.loc[OOS_START:SEP_START-pd.Timedelta(hours=1)],oos),('fresh',opens.loc[SEP_START:SEP_END-pd.Timedelta(hours=1)],closes.loc[SEP_START:SEP_END-pd.Timedelta(hours=1)],fresh)]:
        for n,z in results.items(): cost += [dict(period=group,**q) for q in cost_rows(n,z,oo,cc)]
    pd.DataFrame(cost).to_csv(OUT/'PHASE3A1_COST_STRESS.csv',index=False)
    ic=[]
    for name in ('ridge','tree'):
        p=pd.Series(models[name][0].predict(prep.transform(oos_data[FEATURE_COLUMNS])),index=oos_data.index); z=pd.DataFrame({'p':p,'y':oos_data.future_excess}); dates=z.groupby(level='timestamp').apply(lambda q:spearman(q.p,q.y)); b=z.assign(bucket=z.groupby(level='timestamp').p.transform(lambda a:pd.qcut(a.rank(method='first'),5,labels=False))).groupby('bucket').y.mean(); ic.append({'model':name,'mean_ic':dates.mean(),'median_ic':dates.median(),'positive_ic_date_frequency':(dates>0).mean(),'top_minus_bottom_future_return_spread':b.get(4,np.nan)-b.get(0,np.nan)})
    pd.DataFrame(ic).to_csv(OUT/'CLEAN_OOS_PREDICTIVE_DIAGNOSTICS.csv',index=False)
    tree=fresh_rows.query("strategy=='TREE_RANKING'").iloc[0]; ridge=fresh_rows.query("strategy=='RIDGE_RANKING'").iloc[0]; filt=fresh_rows.query("strategy=='ML_FILTERED_TREND824'").iloc[0]; base=fresh_rows.query("strategy=='FROZEN_TREND824'").iloc[0]
    decision='MIXED — KEEP ML AS EXPERIMENTAL' if (tree.full_oos_net_return>0 and tree.full_oos_net_return==tree.full_oos_net_return) else 'REJECT OHLCV-ONLY ML ALPHA'
    report=f'# Phase 3A.1 Report\n\n**Decision: {decision}.** Preprocessing is now fit exclusively on 2025 development data and `return_minus_market` is 24h-aligned. These fixes changed the clean Jan–Aug tree net return to {oos_rows.query("strategy == 'TREE_RANKING'").iloc[0].full_oos_net_return:.2%}; this is not comparable to the original leaky result.\n\nFresh test: all 13 B1 assets, 2026-09-01 00:00 through 2026-09-20 23:00 UTC, with no Sep 21+ observations loaded. It has only seven overlapping daily-start 14-day windows, so it is robustness evidence, not independent confirmation. Tree remains exploratory; {selected["model"]} is development-selected.\n\nFresh Tree net {tree.full_oos_net_return:.2%}, median 14d {tree.median_14d_net_return:.2%}, P(beat A) {tree.p_beats_baseline:.1%}. Fresh Ridge net {ridge.full_oos_net_return:.2%}; filter net {filt.full_oos_net_return:.2%}; baseline net {base.full_oos_net_return:.2%}. See cost stress for 5/10/15/20bps.\n'
    (OUT/'PHASE3A1_REPORT.md').write_text(report); pd.DataFrame([{'event':'freeze_created_before_fresh_evaluation','selected_model':selected['model'],'tree_status':'EXPLORATORY_OOS_CHALLENGER','fresh_dates':'2026-09-01 through 2026-09-20','universe':'all 13 B1 assets','data_source':'existing local raw + public Binance fetch for eight missing symbols, exactly Sep01-20'}]).to_csv(OUT/'EXPERIMENT_LOG.csv',index=False)
    print('PHASE 3A.1 SUMMARY\nDevelopment-selected model:',selected['model'],'\nTree status: EXPLORATORY_OOS_CHALLENGER\nFresh universe: all 13 B1 assets\nFresh test dates: 2026-09-01 through 2026-09-20')
    for n,row in [('Baseline A',base),('Ridge',ridge),('Tree',tree),('ML-filtered Trend',filt)]: print(f'{n}: net@10bps={row.full_oos_net_return:.2%}; median14d={row.median_14d_net_return:.2%}; P(beat A)={row.p_beats_baseline:.1%}; breakeven={row.break_even_transaction_cost_bps:.2f}bps')
    print('Final decision:',decision)
if __name__=='__main__': main()
