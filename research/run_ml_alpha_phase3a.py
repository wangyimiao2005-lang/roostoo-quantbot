"""Run isolated Phase 3A; reads only data ending 2026-09-01 and writes additive results."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend
from ml_alpha.phase3a import *

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"results/ml_alpha_phase3a"; DEV_END=pd.Timestamp("2026-01-01",tz="UTC"); OOS_END=pd.Timestamp("2026-09-01",tz="UTC")
def spearman(a, b):
    """Rank correlation without scipy (the local scipy wheel is ABI-incompatible)."""
    return a.rank().corr(b.rank())
def load(s):
    frames=[]
    for p in (ROOT/"data/raw").glob(f"{s}_1h_*.csv"):
        x=pd.read_csv(p,index_col="timestamp",parse_dates=True); x.index=pd.to_datetime(x.index,utc=True); frames.append(x)
    x=pd.concat(frames).loc[lambda z:~z.index.duplicated(keep="last")].sort_index(); return x[x.index<OOS_END]
def panel(frames, col): return pd.DataFrame({s:frames[s][col] for s in UNIVERSE})
def diagnostics(features):
    return pd.DataFrame({"feature":features.columns,"missing_rate":features.isna().mean().values,"infinite_count":np.isinf(features.to_numpy(float)).sum(0),"median":features.median().values,"std":features.std().values,"p01":features.quantile(.01).values,"p99":features.quantile(.99).values,"causal_timing":"uses observations at or before timestamp t"})
def prepare_x(frame, medians=None):
    if medians is None: medians=frame.median(); return frame.fillna(medians).clip(frame.quantile(.01),frame.quantile(.99),axis=1),medians
    return frame.fillna(medians).clip(frame.quantile(.01),frame.quantile(.99),axis=1),medians
def trend_targets(closes):
    raw=MultiHorizonTrend(8,24).target_weights(closes); return enforce_exposure_limits(risk_scale_targets(raw,closes.pct_change(fill_method=None)).fillna(0))
def summarize(name,res,baseline,score=None):
    rows=[]
    for mode in ("daily","nonoverlap"):
        w=rolling_14d(res.returns,res.costs,res.turnover,mode); b=rolling_14d(baseline.returns,baseline.costs,baseline.turnover,mode)
        merged=w.merge(b[["window_start","return"]],on="window_start",suffixes=("","_baseline")); inc=merged["return"]-merged["return_baseline"]
        rows.append({"strategy":name,"view":mode,"full_oos_net_return":(1+res.returns).prod()-1,"mean_14d_return":w["return"].mean(),"median_14d_return":w["return"].median(),"positive_14d_probability":(w["return"]>0).mean(),"p25_14d_return":w["return"].quantile(.25),"p10_14d_return":w["return"].quantile(.1),"p5_14d_return":w["return"].quantile(.05),"best_14d_return":w["return"].max(),"worst_14d_return":w["return"].min(),"median_14d_max_drawdown":w.max_drawdown.median(),"turnover_per_14d":w.turnover.median(),"fees_per_14d":w.fees.median(),"effective_trades_per_14d":res.trades.shape[0]/max(len(w),1),"p_beats_baseline":(inc>0).mean(),"mean_incremental_14d":inc.mean(),"median_incremental_14d":inc.median(),"p10_incremental_14d":inc.quantile(.1)})
        merged.assign(strategy=name,incremental_return=inc).to_csv(OUT/f"windows_{name}_{mode}.csv",index=False)
    return rows
def main():
    OUT.mkdir(parents=True,exist_ok=True); frames={s:load(s) for s in UNIVERSE}; opens,highs,lows,closes,volumes=[panel(frames,c) for c in ("open","high","low","close","volume")]
    feat=build_features(opens,highs,lows,closes,volumes); labels=build_labels(opens,closes); data=feat.join(labels).dropna(subset=["future_excess"]); data=data[data.index.get_level_values("timestamp").hour == 0]  # preregistered 00:00 UTC daily decision schedule
    diagnostics(feat).to_csv(OUT/"FEATURE_DIAGNOSTICS.csv",index=False)
    train=data[data.index.get_level_values("timestamp")<DEV_END]; train=train[train.index.get_level_values("timestamp")>=pd.Timestamp("2025-01-01",tz="UTC")]; valid=train[train.index.get_level_values("timestamp")>=pd.Timestamp("2025-10-01",tz="UTC")]; fit=train[train.index.get_level_values("timestamp")<pd.Timestamp("2025-10-01",tz="UTC")]; oos=data[(data.index.get_level_values("timestamp")>=DEV_END)&(data.index.get_level_values("timestamp")<OOS_END)]
    xfit,med=prepare_x(fit[FEATURE_COLUMNS]); xval,_=prepare_x(valid[FEATURE_COLUMNS],med); xoos,_=prepare_x(oos[FEATURE_COLUMNS],med)
    configs=[("ridge",{"alpha":1.0}),("ridge",{"alpha":10.0}),("tree",{"iterations":30,"learning_rate":.05,"max_features":12}),("tree",{"iterations":50,"learning_rate":.05,"max_features":16})]; log=[]; models={}
    for n,p in configs:
        m=RidgeRegressor(**p) if n=="ridge" else StumpBoostingRegressor(**p); m.fit(xfit,fit.future_excess); pred=m.predict(xval); z=pd.DataFrame({"p":pred,"y":valid.future_excess},index=valid.index); ic=z.groupby(level="timestamp").apply(lambda x:spearman(x.p,x.y)).mean(); log.append({"model":n,"params":json.dumps(p,sort_keys=True),"sample":"2025 validation only","validation_mean_ic":ic,"portfolio_rule":"top3/bottom3 daily; gate=0 development median spread"}); models[(n,json.dumps(p,sort_keys=True))]=m
    pd.DataFrame(log).to_csv(OUT/"EXPERIMENT_LOG.csv",index=False)
    # Fixed small grid selection on development validation only, then refit with all 2025.
    best=max(log,key=lambda z:z["validation_mean_ic"]); p=json.loads(best["params"]); model=RidgeRegressor(**p) if best["model"]=="ridge" else StumpBoostingRegressor(**p); xtrain,med=prepare_x(train[FEATURE_COLUMNS]); model.fit(xtrain,train.future_excess); xoos,_=prepare_x(oos[FEATURE_COLUMNS],med); pred=pd.Series(model.predict(xoos),index=oos.index,name="prediction")
    # Development-only economical gate: median daily predicted top-bottom spread.
    dev_pred=pd.Series(model.predict(xtrain),index=train.index).unstack("symbol"); gate=float((dev_pred.max(axis=1)-dev_pred.min(axis=1)).median())
    signals={}; gates={}
    # Always publish both required models using their predeclared configs with strongest validation per class.
    for name in ("ridge","tree"):
        cand=max([x for x in log if x["model"]==name],key=lambda z:z["validation_mean_ic"]); pp=json.loads(cand["params"]); mm=RidgeRegressor(**pp) if name=="ridge" else StumpBoostingRegressor(**pp); mm.fit(xtrain,train.future_excess)
        development_scores=pd.Series(mm.predict(xtrain),index=train.index).unstack("symbol")
        signals[f"{name.upper()}_RANKING"]=pd.Series(mm.predict(xoos),index=oos.index); gates[f"{name.upper()}_RANKING"]=float((development_scores.max(axis=1)-development_scores.min(axis=1)).median())
    oos_idx=closes.index[(closes.index>=DEV_END)&(closes.index<OOS_END)]; base=run_backtest(opens.loc[oos_idx,UNIVERSE[:5]],closes.loc[oos_idx,UNIVERSE[:5]],trend_targets(closes[UNIVERSE[:5]]).loc[oos_idx],10,execution_policy=ExecutionPolicy("Rebalance24h",rebalance_every=24))
    mom=rank_targets(data.loc[oos.index,"return_24h"]); results={"FROZEN_TREND824":base,"MOMENTUM_24H":run_backtest(opens.loc[oos_idx],closes.loc[oos_idx],mom.reindex(oos_idx).fillna(0),10,execution_policy=ExecutionPolicy("Rebalance24h",rebalance_every=24))}
    score_rows=[]; ic_rows=[]; bucket_rows=[]; imp=[]
    for name,sc in signals.items():
        if sc is None: continue
        target=rank_targets(sc,gate=gates[name]); results[name]=run_backtest(opens.loc[oos_idx],closes.loc[oos_idx],target.reindex(oos_idx).fillna(0),10,execution_policy=ExecutionPolicy("Rebalance24h",rebalance_every=24))
        z=pd.DataFrame({"prediction":sc,"outcome":oos.future_excess}); score_rows.append(z.assign(strategy=name)); ic=z.groupby(level="timestamp").apply(lambda x:spearman(x.prediction,x.outcome)); ic_rows.extend({"strategy":name,"timestamp":t,"period":"2026_Q1" if t.month<=3 else ("2026_Q2" if t.month<=6 else "2026_JulAug"),"spearman_ic":v} for t,v in ic.items())
        bucket=z.assign(bucket=z.groupby(level="timestamp").prediction.transform(lambda x:pd.qcut(x.rank(method="first"),5,labels=False,duplicates="drop"))).groupby("bucket").outcome.agg(["mean","count"]).reset_index()
        bucket_rows.extend({"strategy":name,"quintile":int(row.bucket)+1,"mean_future_excess_return":row.mean,"observations":int(row.count)} for row in bucket.itertuples())
        # Refit stores importances for transparent selected models.
        if name.startswith("RIDGE"): vals=pd.Series(mm.coef_ if False else 0,index=FEATURE_COLUMNS)
    # ML trend filter uses selected prediction, fixed development quantiles: retain/reduce/skip only.
    qlow,qmid=dev_pred.stack().quantile([.33,.5]); st=trend_targets(closes[UNIVERSE]); matrix=pred.unstack("symbol").reindex(columns=UNIVERSE); filtered=st.copy()
    filtered=filtered.where(matrix>=qlow,0).where(~((matrix>=qlow)&(matrix<qmid)),filtered*.5).fillna(0); results["ML_FILTERED_TREND824"]=run_backtest(opens.loc[oos_idx,UNIVERSE[:5]],closes.loc[oos_idx,UNIVERSE[:5]],filtered[UNIVERSE[:5]].loc[oos_idx],10,execution_policy=ExecutionPolicy("Rebalance24h",rebalance_every=24))
    pd.DataFrame(bucket_rows).to_csv(OUT/"OOS_SCORE_BUCKETS.csv",index=False); pd.DataFrame(ic_rows).to_csv(OUT/"OOS_IC_BY_DATE.csv",index=False)
    pred_diag=[]
    for name,sc in signals.items():
        if sc is None: continue
        z=pd.DataFrame({"prediction":sc,"outcome":oos.future_excess}); ic=pd.Series([r["spearman_ic"] for r in ic_rows if r["strategy"]==name]); buckets=z.assign(bucket=z.groupby(level="timestamp").prediction.transform(lambda x:pd.qcut(x.rank(method="first"),5,labels=False,duplicates="drop"))).groupby("bucket").outcome.mean(); pred_diag.append({"strategy":name,"pearson":z.prediction.corr(z.outcome),"mean_ic":ic.mean(),"median_ic":ic.median(),"ic_positive_frequency":(ic>0).mean(),"top_quintile_return":buckets.get(4,np.nan),"bottom_quintile_return":buckets.get(0,np.nan),"top_minus_bottom":buckets.get(4,np.nan)-buckets.get(0,np.nan)})
    pd.DataFrame(pred_diag).to_csv(OUT/"OOS_PREDICTIVE_DIAGNOSTICS.csv",index=False)
    # Feature importance based on each model's absolute standardized coefficient / split frequency.
    fi=[]
    for n in ("ridge","tree"):
        cand=max([x for x in log if x["model"]==n],key=lambda z:z["validation_mean_ic"]); pp=json.loads(cand["params"]); mm=RidgeRegressor(**pp) if n=="ridge" else StumpBoostingRegressor(**pp); mm.fit(xtrain,train.future_excess); values=pd.Series(abs(mm.coef_),index=FEATURE_COLUMNS) if n=="ridge" else mm.importance(FEATURE_COLUMNS); fi.extend({"model":n,"feature":k,"importance":v} for k,v in values.items())
    pd.DataFrame(fi).to_csv(OUT/"FEATURE_IMPORTANCE.csv",index=False)
    comp=[]
    for n,r in results.items(): comp+=summarize(n,r,base)
    pd.DataFrame(comp).to_csv(OUT/"COMPETITION_14D_RESULTS.csv",index=False); pd.concat([pd.read_csv(p) for p in OUT.glob("windows_*_daily.csv")]).to_csv(OUT/"COMPETITION_14D_WINDOWS.csv",index=False)
    costs=[]
    for n,r in results.items():
        for c in (5,10,15,20):
            # fixed realized weights makes stresses comparable
            rr=run_backtest(opens.loc[oos_idx,r.weights.columns],closes.loc[oos_idx,r.weights.columns],r.weights.shift(-1).fillna(0),c) # target shift restores same executed weights
            costs.append({"strategy":n,"cost_bps_per_side":c,"gross_return":(1+r.gross_returns).prod()-1,"net_return":(1+rr.returns).prod()-1,"turnover":r.turnover.sum(),"fees":rr.costs.sum(),"break_even_cost_bps":((1+r.gross_returns).prod()-1)/max(r.turnover.sum(),1e-12)*10000})
    pd.DataFrame(costs).to_csv(OUT/"COST_STRESS.csv",index=False)
    primary=pd.DataFrame(comp).query("view == 'daily' and strategy != 'FROZEN_TREND824'").sort_values("mean_14d_return",ascending=False).iloc[0]; decision="PROCEED — ML SHOWS ECONOMIC OOS EDGE" if primary.strategy in ("RIDGE_RANKING","TREE_RANKING","ML_FILTERED_TREND824") and primary.mean_incremental_14d>0 and primary.positive_14d_probability>.5 else "MIXED — PREDICTIVE SIGNAL EXISTS BUT ECONOMIC EDGE IS INSUFFICIENT" if max(x["mean_ic"] for x in pred_diag)>0 else "REJECT — NO ROBUST ML ALPHA FOUND"
    report=f"# ML Alpha Phase 3A\n\n**Decision: {decision}.** This isolated run used only 2025 for model/grid/gate choices and frozen 2026-01-01 to 2026-08-31 for evaluation; no files after 2026-09-01 were read.\n\nSelected validation model: {best['model']} `{best['params']}`. The nonlinear model is a deterministic dependency-free boosted decision-stump ensemble because the installed scikit-learn binary is incompatible with the environment NumPy; no production dependency was added.\n\nThe primary economic table is `COMPETITION_14D_RESULTS.csv`; prediction diagnostics are `OOS_PREDICTIVE_DIAGNOSTICS.csv`; cost stress is `COST_STRESS.csv`. ML is promoted only when it improves mean matched 14-day net return after costs.\n\nBest candidate by daily 14-day mean: {primary.strategy}; mean {primary.mean_14d_return:.2%}, median {primary.median_14d_return:.2%}, positive probability {primary.positive_14d_probability:.1%}, matched P(beats A) {primary.p_beats_baseline:.1%}.\n"
    (OUT/"ML_ALPHA_PHASE3A_REPORT.md").write_text(report); print(json.dumps({"best_ml_model":best["model"],"oos_ic":max(x["mean_ic"] for x in pred_diag),"gross_return":float(pd.DataFrame(costs).query("strategy == @primary.strategy and cost_bps_per_side == 10").gross_return.iloc[0]),"net_return_10bps":float(primary.full_oos_net_return),"mean_14d_return":float(primary.mean_14d_return),"median_14d_return":float(primary.median_14d_return),"positive_14d_probability":float(primary.positive_14d_probability),"p_beats_baseline":float(primary.p_beats_baseline),"break_even_cost":float(pd.DataFrame(costs).query("strategy == @primary.strategy and cost_bps_per_side == 10").break_even_cost_bps.iloc[0]),"decision":decision},indent=2))
if __name__=="__main__": main()
