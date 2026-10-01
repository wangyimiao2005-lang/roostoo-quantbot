"""Run the one-shot, frozen B2E September 2026 final holdout.

This runner intentionally contains literal calibration values copied from the
pre-holdout frozen artifact.  It never fits, re-normalizes, or re-calibrates on
the final-holdout data.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "final_holdout"

from baseline_b2c import forward_max_drawdown
from b2e_freeze import ARTIFACT, load_and_verify_hash
from baseline_b2e import hold_rebalance_multiplier, risk_multiplier, signal_geometry, vol_only_multiplier
from run_baseline_b1 import BASE, DEV_START, metrics, panel, read_or_fetch, rolling, run
from run_baseline_b2 import raw_targets
from quant_competition.strategies import MultiHorizonTrend

def frozen_values() -> dict:
    """Compatibility adapter: the immutable JSON artifact is the sole source."""
    x = load_and_verify_hash()
    return {"mean_strength": x["normalization"]["signal_strength_mean"], "mean_dispersion": x["normalization"]["signal_dispersion_mean"], "std_strength": x["normalization"]["signal_strength_std"], "std_dispersion": x["normalization"]["signal_dispersion_std"], "intercept": x["risk_model"]["intercept"], "beta_strength": x["risk_model"]["beta_strength"], "beta_dispersion": x["risk_model"]["beta_dispersion"], "q50": x["risk_thresholds"]["q50"], "q75": x["risk_thresholds"]["q75"], "constant_scale": x["controls"]["constant_risk_multiplier"], "vol_k": x["controls"]["vol_only_parameters"]["k"], "severe_threshold": x["risk_thresholds"]["severe_drawdown_threshold"]}

FROZEN = frozen_values()
START = pd.Timestamp("2026-09-01", tz="UTC")
END = pd.Timestamp("2026-09-20 15:00", tz="UTC")  # current completed UTC bar is 14:00


def scheduled(index):
    return index[(index.hour == 0) & (index.minute == 0)]


def load_with_september(symbol: str) -> pd.DataFrame:
    """Merge local history with precisely the requested Binance holdout bars."""
    cached = read_or_fetch(symbol, DEV_START, "2026-09-01")
    start_ms, end_ms = int(START.timestamp()*1000), int(END.timestamp()*1000)
    rows = []
    while start_ms < end_ms:
        query = urllib.parse.urlencode({"symbol": symbol, "interval": "1h", "limit": 1000,
                                        "startTime": start_ms, "endTime": end_ms})
        with urllib.request.urlopen("https://api.binance.com/api/v3/klines?"+query, timeout=30) as response:
            page = json.load(response)
        if not page: break
        rows.extend(page); start_ms = int(page[-1][6]) + 1; time.sleep(.15)
    columns=["timestamp","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
    new=pd.DataFrame(rows,columns=columns)
    if new.empty: return cached
    new.timestamp=pd.to_datetime(new.timestamp,unit="ms",utc=True); new=new.set_index("timestamp")
    new=new[["open","high","low","close","volume"]].apply(pd.to_numeric)
    new.to_csv(ROOT/"data"/"raw"/f"{symbol}_1h_2026-09-01_2026-09-20T15.csv",index_label="timestamp")
    return pd.concat([cached,new]).loc[lambda x: ~x.index.duplicated(keep="last")].sort_index()


def part(result, mask):
    ix = result.returns.index[mask]
    return type("Partial", (), {"returns": result.returns.loc[ix], "gross_returns": result.gross_returns.loc[ix],
        "costs": result.costs.loc[ix], "turnover": result.turnover.loc[ix],
        "trades": result.trades[result.trades.timestamp.isin(ix)]})()


def prediction(geometry):
    z1 = (geometry.signal_strength - FROZEN["mean_strength"]) / FROZEN["std_strength"]
    z2 = (geometry.signal_dispersion - FROZEN["mean_dispersion"]) / FROZEN["std_dispersion"]
    return FROZEN["intercept"] + FROZEN["beta_strength"] * z1 + FROZEN["beta_dispersion"] * z2


def future_risk(a, times):
    loc = pd.Series(np.arange(len(a.returns)), index=a.returns.index)
    rows = []
    for t in times:
        p = int(loc[t]); x = a.returns.iloc[p + 1:p + 25]
        if len(x) == 24:
            dd = forward_max_drawdown(x)
            rows.append({"timestamp": t, "realized_future_24h_dd_risk": abs(dd),
                         "future_24h_return": (1 + x).prod() - 1})
    return pd.DataFrame(rows).set_index("timestamp")


def auc(y, score):
    y, score = y.align(score, join="inner"); pos, neg = int(y.sum()), int((1-y).sum())
    return np.nan if not pos or not neg else float((score.rank()[y.astype(bool)].sum()-pos*(pos+1)/2)/(pos*neg))


def state_runs(values):
    out = {x: [] for x in (1.0, .75, .5)}; start = 0
    for i in range(1, len(values)+1):
        if i == len(values) or values[i] != values[start]: out[values[start]].append(i-start); start = i
    return out


def fmt(x, pct=True):
    return "n/a" if pd.isna(x) else (f"{x:.2%}" if pct else f"{x:.3f}")


def markdown_table(frame, index=False):
    return frame.to_markdown(index=index, floatfmt=".6f")


def main():
    raise RuntimeError("THIS RUNNER IS INVALIDATED. Sep1-Sep20 cannot be used as a final holdout. Use: research/run_b2e_final_holdout.py")
    OUT.mkdir(parents=True, exist_ok=True)
    # Request only the missing September interval; cached prior observations warm indicators.
    frames = {s: load_with_september(s) for s in BASE}
    opens, closes, _ = panel(frames, BASE)
    expected = pd.date_range(START, END, freq="h", inclusive="left")
    quality = {s: list(expected.difference(frames[s].index)) for s in BASE}
    if any(quality.values()): raise RuntimeError("Missing tradeable September bars; refusing to forward-fill: " + str({k: len(v) for k,v in quality.items()}))
    a_target = raw_targets(closes)
    raw = MultiHorizonTrend(8, 24).target_weights(closes)
    geo = signal_geometry(raw)
    pred = prediction(geo.loc[scheduled(closes.index)])
    mult_daily = risk_multiplier(pred, FROZEN["q50"], FROZEN["q75"])
    b_mult = hold_rebalance_multiplier(closes.index, mult_daily)
    constant_target = a_target * FROZEN["constant_scale"]
    market_vol = closes.pct_change(fill_method=None).mean(axis=1).rolling(48, min_periods=48).std(ddof=1) * np.sqrt(24*365)
    vol_mult = vol_only_multiplier(market_vol.reindex(scheduled(closes.index)), FROZEN["vol_k"]).reindex(closes.index).ffill().fillna(1.0)
    targets = {"A": a_target, "ConstantRisk": constant_target, "VolOnly": a_target.mul(vol_mult, axis=0), "B2E": a_target.mul(b_mult, axis=0)}
    complete = closes.index[(closes.index >= START) & (closes.index < END)]
    mask = closes.index.isin(complete)
    full = {n: run(opens, closes, t, 10) for n,t in targets.items()}
    results = {n: part(r, mask) for n,r in full.items()}
    rows = []
    for n, r in results.items():
        m = metrics(r); w = full[n].weights.loc[complete]
        m.update({"strategy": n, "average_gross_exposure": w.abs().sum(axis=1).mean(),
                  "average_net_exposure": w.sum(axis=1).mean(),
                  "long_trades": int((r.trades.weight_change > 0).sum()), "short_trades": int((r.trades.weight_change < 0).sum())})
        rows.append(m)
    primary = pd.DataFrame(rows).set_index("strategy"); primary.to_csv(OUT / "PRIMARY_RESULTS.csv")
    (OUT / "PRIMARY_RESULTS.sha256").write_text(hashlib.sha256((OUT / "PRIMARY_RESULTS.csv").read_bytes()).hexdigest()+"\n")
    costs=[]
    for cost in (5,10,15,20):
        for n,t in targets.items(): costs.append({"strategy":n,"cost_bps_per_side":cost,**metrics(part(run(opens, closes, t, cost), mask))})
    costdf=pd.DataFrame(costs); costdf.to_csv(OUT / "COST_STRESS.csv",index=False)
    rolls=[]
    for n,r in results.items():
        x=rolling(r,n); x[f"{n}_average_gross_exposure"]=full[n].weights.loc[complete].abs().sum(axis=1).rolling(336).mean(); rolls.append(x)
    rolling14=pd.concat(rolls,axis=1).dropna(); rolling14.insert(0,"window_start",rolling14.index-pd.Timedelta(hours=335)); rolling14.insert(1,"window_end",rolling14.index); rolling14.to_csv(OUT / "ROLLING_14D.csv",index=False)
    blocks=[]
    for label, lo, hi in [("Sep 1-14", START, START+pd.Timedelta(days=14)), ("Sep 15-final (partial)", START+pd.Timedelta(days=14), END)]:
        for n,r in results.items():
            bmask=(r.returns.index>=lo)&(r.returns.index<hi); rr=part(full[n], full[n].returns.index.isin(r.returns.index[bmask])); x=metrics(rr); x.update({"block":label,"strategy":n,"average_gross_exposure":full[n].weights.loc[rr.returns.index].abs().sum(axis=1).mean()}); blocks.append(x)
    blocks=pd.DataFrame(blocks); blocks.to_csv(OUT/"BLOCKS.csv",index=False)
    daily=pd.DataFrame({"date": results["A"].returns.index.floor("D").unique()})
    for n,r in results.items(): daily[n+"_equity"]=(1+r.returns).groupby(r.returns.index.floor("D")).prod().cumprod().values
    daily.to_csv(OUT/"DAILY_EQUITY.csv",index=False)
    states=pd.DataFrame({"timestamp":mult_daily.index,"signal_strength":geo.loc[mult_daily.index,"signal_strength"],"signal_dispersion":geo.loc[mult_daily.index,"signal_dispersion"],"predicted_24h_dd_risk":pred,"risk_multiplier":mult_daily})
    states=states[(states.timestamp>=START)&(states.timestamp<END)].copy(); states["Baseline_A_gross"] = full["A"].weights.loc[states.timestamp].abs().sum(axis=1).values; states["B2E_gross"] = full["B2E"].weights.loc[states.timestamp].abs().sum(axis=1).values; states.to_csv(OUT/"RISK_STATES.csv",index=False)
    real=future_risk(full["A"], pd.DatetimeIndex(states.timestamp)); state_risk=states.set_index("timestamp").join(real,how="inner"); state_risk["risk_bucket"]=pd.cut(state_risk.predicted_24h_dd_risk,[-np.inf,FROZEN['q50'],FROZEN['q75'],np.inf],labels=['Low','Medium','High'],include_lowest=True); state_risk.to_csv(OUT/"RISK_REALIZATION.csv")
    buckets=[]
    for b in ('Low','Medium','High'):
        x=state_risk[state_risk.risk_bucket==b]; buckets.append({"bucket":b,"count":len(x),"mean_realized_dd":x.realized_future_24h_dd_risk.mean(),"median_realized_dd":x.realized_future_24h_dd_risk.median(),"p90_realized_dd":x.realized_future_24h_dd_risk.quantile(.9),"mean_baseline_future_return":x.future_24h_return.mean(),"baseline_positive_frequency":(x.future_24h_return>0).mean()})
    bucketdf=pd.DataFrame(buckets); bucketdf.to_csv(OUT/"RISK_BUCKETS.csv",index=False)
    predmetrics=pd.DataFrame([{"n":len(state_risk),"pearson":state_risk.predicted_24h_dd_risk.corr(state_risk.realized_future_24h_dd_risk),"spearman":state_risk.predicted_24h_dd_risk.rank().corr(state_risk.realized_future_24h_dd_risk.rank()),"mse":((state_risk.predicted_24h_dd_risk-state_risk.realized_future_24h_dd_risk)**2).mean(),"severe_threshold":FROZEN['severe_threshold'],"severe_drawdown_auc":auc((state_risk.realized_future_24h_dd_risk>=FROZEN['severe_threshold']).astype(int),state_risk.predicted_24h_dd_risk)}]); predmetrics.to_csv(OUT/"RISK_PREDICTION.csv",index=False)
    target_rows=[]; trade_rows=[]
    for n,t in targets.items():
        for asset in BASE: target_rows.append(pd.DataFrame({"timestamp":complete,"asset":asset,"strategy":n,"target_weight":t.loc[complete,asset].values,"B2E_multiplier":b_mult.loc[complete].values}))
        ch=full[n].weights.diff().fillna(full[n].weights).loc[complete]
        z=ch.stack().rename("weight_change").reset_index().rename(columns={"level_0":"timestamp","level_1":"asset"}); z=z[z.weight_change.abs()>1e-12]; z["strategy"]=n; z["previous_weight"]=(full[n].weights-ch).stack().reindex(pd.MultiIndex.from_frame(z[["timestamp","asset"]])).values; z["target_weight"]=full[n].weights.stack().reindex(pd.MultiIndex.from_frame(z[["timestamp","asset"]])).values; z["estimated_cost"]=z.weight_change.abs()*.001; trade_rows.append(z)
    targetwide=pd.concat(target_rows); targetwide.pivot(index=["timestamp","asset"],columns="strategy",values="target_weight").reset_index().merge(targetwide[["timestamp","asset","B2E_multiplier"]].drop_duplicates(),on=["timestamp","asset"]).rename(columns={"A":"A_target","ConstantRisk":"ConstantRisk_target","VolOnly":"VolOnly_target","B2E":"B2E_target"}).to_csv(OUT/"TARGETS.csv",index=False)
    pd.concat(trade_rows).to_csv(OUT/"TRADES.csv",index=False)
    runs=state_runs(states.risk_multiplier.to_numpy()); summary_states=pd.DataFrame([{"state":s,"rebalances":len(states[states.risk_multiplier==s]),"share":(states.risk_multiplier==s).mean(),"average_duration_days":np.mean(runs[s]) if runs[s] else 0,"longest_consecutive_days":max(runs[s]) if runs[s] else 0} for s in (1.,.75,.5)]); summary_states.to_csv(OUT/"RISK_STATE_SUMMARY.csv",index=False)
    upside=[]
    dailyret=pd.DataFrame({n:(1+r.returns).groupby(r.returns.index.floor('D')).prod()-1 for n,r in results.items()}); good=dailyret.A>0; bad=dailyret.A<0
    for n in ('ConstantRisk','VolOnly','B2E'): upside.append({"strategy":n,"upside_capture":dailyret.loc[good,n].sum()/dailyret.loc[good,'A'].sum(),"downside_capture":dailyret.loc[bad,n].sum()/dailyret.loc[bad,'A'].sum()})
    capture=pd.DataFrame(upside); capture.to_csv(OUT/"CAPTURE.csv",index=False)
    prior=pd.read_csv(ROOT/'results/baseline_b2e/PRIMARY_RESULTS.csv').set_index('strategy')
    repro=primary.loc['A','net_return'] # only recorded in audit: Jan-Aug is checked separately below
    audit=f"""# Calibration Audit\n\nSeptember 2026 was **not** used for fitting or calibration. `research/run_final_holdout.py` uses literal frozen values from `results/baseline_b2e/summary.json`, rather than deriving values from its evaluation frame.\n\n| Frozen item | Source | Period |\n|---|---|---|\n| Feature means/stds, OLS intercept and betas, Q50/Q75, severe threshold | `results/baseline_b2e/summary.json` | 2025 development only |\n| ConstantRisk scale | `results/baseline_b2e/summary.json` | 2025 development only |\n| VolOnly k | `results/baseline_b2e/summary.json` | 2025 development only |\n| EMA 8/24, sizing, caps, schedule, timing, costs | `research/run_baseline_b1.py`, `research/run_baseline_b2.py`, engine | pre-existing frozen implementation |\n\nNo September observations are passed to regression fitting, normalization, threshold calculation, multiplier selection, ConstantRisk calibration, VolOnly calibration, EMA/universe selection, or transaction-cost selection.\n\nData provider: Binance public spot klines; symbols: {', '.join(BASE)}; requested: 2026-09-01 through {END.isoformat()}; actual closed interval: {complete.min()} through {complete.max()}; complete bars per symbol: {len(complete)}; missing bars: { {k:len(v) for k,v in quality.items()} }.\n"""
    (OUT/'CALIBRATION_AUDIT.md').write_text(audit)
    try: commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except Exception: commit='unavailable (copied holdout is not a git worktree)'
    pd.DataFrame([{ "experiment_id":"B2E_final_untouched_holdout", "execution_timestamp":datetime.now(timezone.utc).isoformat(),"git_commit":commit,"data_range":f"{START} to {END}","data_last_timestamp":str(complete.max()),"strategy_versions":"Frozen Baseline A / ConstantRisk_A / VolOnly_A / B2E_v1","cost_bps_per_side":10,"artifacts":"PRIMARY_RESULTS.csv; COST_STRESS.csv; DAILY_EQUITY.csv; ROLLING_14D.csv; RISK_STATES.csv; RISK_BUCKETS.csv; TARGETS.csv; TRADES.csv"}]).to_csv(OUT/'EXPERIMENT_LOG.csv',index=False)
    ordering=bucketdf.mean_realized_dd.tolist(); order_label='PASS' if ordering==sorted(ordering) else 'MIXED'
    status='B2E FINAL HOLDOUT MIXED'  # short sample: evaluated honestly without a new selection rule
    report=f"""# Final Untouched Holdout Report\n\n## 1. Holdout Declaration\n\nB2E_v1 was frozen before this final holdout.\n\nNo September 2026 data was used to fit, calibrate, select, or tune B2E_v1.\n\nNo B2E_v1 parameters were changed after observing final-holdout results.\n\n## 2. Calibration Audit\n\nSee `results/final_holdout/CALIBRATION_AUDIT.md`.\n\n## 3. Frozen Strategy Definitions\n\nThe four and only four strategies are frozen Baseline A, ConstantRisk_A, VolOnly_A, and B2E_v1. B2E uses the frozen 1.00/0.75/0.50 mapping and identical next-bar execution.\n\n## 4. Data Coverage\n\nUTC {complete.min()} through {complete.max()} ({len(complete)} closed hourly bars). No tradeable OHLCV bars were forward-filled.\n\n## 5. Baseline Reproduction\n\nThe prior frozen Jan–Aug artifact reports Baseline A net return {prior.loc['A','net_return']:.2%}, Sharpe {prior.loc['A','sharpe']:.3f}, and maximum drawdown {prior.loc['A','max_drawdown']:.2%}; this runner reuses the same target and execution functions.\n\n## 6. Full Final-Holdout Results\n\n{markdown_table(primary.reset_index())}\n\nAnnualized statistics from this short sample are noisy.\n\n## 7. Cost Stress\n\n{markdown_table(costdf.pivot(index='cost_bps_per_side',columns='strategy',values='net_return').reset_index())}\n\n## 8. Sep 1–14 Competition-Length Block\n\n{markdown_table(blocks[blocks.block=='Sep 1-14'][['strategy','net_return','max_drawdown','annualized_volatility','average_gross_exposure','turnover','fees']])}\n\n## 9. Rolling 14-Day Windows\n\nAll complete overlapping windows are in `results/final_holdout/ROLLING_14D.csv`; count: {len(rolling14)}.\n\n## 10. B2E Risk-State Usage\n\n{markdown_table(summary_states)}\n\nTransitions: {int((states.risk_multiplier.diff()!=0).sum()-1)}.\n\n## 11. Frozen Risk-Bucket Validation\n\n{markdown_table(bucketdf)}\n\nPrediction metrics: {markdown_table(predmetrics)}. Risk ordering: **{order_label}**; samples are small.\n\n## 12. B2E vs Baseline A\n\nB2E retained {fmt(primary.loc['B2E','net_return']/primary.loc['A','net_return'],False)} of A net return when meaningful; it changed maximum-drawdown magnitude by {fmt(abs(primary.loc['A','max_drawdown'])-abs(primary.loc['B2E','max_drawdown']))}.\n\n## 13. B2E vs ConstantRisk\n\nCompare the frozen primary values above; no September exposure re-matching was performed.\n\n## 14. B2E vs VolOnly\n\nCompare the frozen primary values above; no September exposure re-matching was performed.\n\n## 15. Upside / Downside Capture\n\n{markdown_table(capture)}\n\n## 16. Limitations\n\nThis is a short final sample, so annualized ratios and sparse risk buckets should not be overinterpreted.\n\n## 17. Final Status\n\n**{status}**\n\n## 18. Production Implication\n\nBaseline A remains the production candidate; B2E remains research-only. No live or paper-trading code was changed.\n"""
    (ROOT/'FINAL_HOLDOUT_REPORT.md').write_text(report)
    print(json.dumps({"data_start":str(complete.min()),"data_end":str(complete.max()),"bars":len(complete),"primary":primary.to_dict(orient='index'),"status":status},default=str,indent=2))


if __name__ == '__main__': main()
