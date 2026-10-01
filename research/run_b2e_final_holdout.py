"""The sole official, pre-registered B2E_v1 final-holdout evaluator."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from b2e_freeze import DEV_END, load_and_verify_hash, verify
from baseline_b2c import forward_max_drawdown
from baseline_b2e import hold_rebalance_multiplier, risk_multiplier, signal_geometry, vol_only_multiplier
from run_baseline_b1 import DEV_START, fetch_public_binance, metrics, panel, read_or_fetch
from quant_competition.backtest import run_backtest
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits
from quant_competition.strategies import MultiHorizonTrend

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "final_holdout"
RELEASE = datetime(2026, 10, 4, tzinfo=timezone.utc)
START = pd.Timestamp("2026-09-22T00:00:00Z")
END = pd.Timestamp("2026-10-04T00:00:00Z")


def sealed_message() -> str:
    return "FINAL HOLDOUT SEALED.\n\nRelease time:\n2026-10-04T00:00:00Z\n\nOfficial holdout:\n2026-09-22T00:00:00Z\nthrough\n2026-10-03T23:00:00Z\n\nPerformance evaluation remains locked."


def preflight(now: datetime | None = None) -> dict:
    """All gates before any holdout data is loaded; clock is injectable for tests."""
    now = now or datetime.now(timezone.utc)
    if now < RELEASE:
        raise RuntimeError(sealed_message())
    artifact = load_and_verify_hash()
    if artifact["final_holdout"] != {"start":"2026-09-22T00:00:00Z", "end":"2026-10-03T23:00:00Z", "release":"2026-10-04T00:00:00Z"}:
        raise RuntimeError("final-holdout dates do not match this preregistration")
    if artifact["risk_multipliers"] != {"low":1.0,"medium":.75,"high":.5}:
        raise RuntimeError("frozen risk multipliers failed verification")
    # This recomputes only 2025 calibration rows and validates controls/features.
    return {"artifact": artifact, "verification": verify()}


def _prediction(geometry: pd.DataFrame, x: dict) -> pd.Series:
    n, m = x["normalization"], x["risk_model"]
    return m["intercept"] + m["beta_strength"] * ((geometry.signal_strength-n["signal_strength_mean"])/n["signal_strength_std"]) + m["beta_dispersion"] * ((geometry.signal_dispersion-n["signal_dispersion_mean"])/n["signal_dispersion_std"])


def _part(result, index):
    return type("Result", (), {"returns":result.returns.loc[index], "gross_returns":result.gross_returns.loc[index], "costs":result.costs.loc[index], "turnover":result.turnover.loc[index], "trades":result.trades[result.trades.timestamp.isin(index)]})()


def _future_dd(result, times):
    loc=pd.Series(np.arange(len(result.returns)), index=result.returns.index); rows=[]
    for t in times:
        x=result.returns.iloc[int(loc[t])+1:int(loc[t])+25]
        if len(x)==24: rows.append({"timestamp":t,"realized_future_dd":abs(forward_max_drawdown(x))})
    return pd.DataFrame(rows).set_index("timestamp")


def _missing_hour_ranges(missing: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Collapse missing hourly timestamps into minimal contiguous [start, end) ranges."""
    if len(missing) == 0:
        return []
    missing = pd.DatetimeIndex(missing).sort_values()
    step = pd.Timedelta(hours=1)
    ranges = []
    start = previous = missing[0]
    for timestamp in missing[1:]:
        if timestamp != previous + step:
            ranges.append((start, previous + step))
            start = timestamp
        previous = timestamp
    ranges.append((start, previous + step))
    return ranges


def _gap_cache_path(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    stamp = lambda x: x.strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "data" / "raw" / f"{symbol}_1h_{stamp(start)}_{stamp(end)}.csv"


def _load_complete_history(
    symbol: str,
    start: str,
    end: str,
    cached_loader=read_or_fetch,
    gap_fetcher=fetch_public_binance,
    cache_path_factory=_gap_cache_path,
) -> pd.DataFrame:
    """Load cached history, then download only missing contiguous hourly ranges.

    The release gate runs before this function.  Existing cache remains the
    authoritative source for already-present bars; network access is limited to
    timestamps absent from the requested [start, end) interval.
    """
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    expected = pd.date_range(start_ts, end_ts, freq="h", inclusive="left")
    frame = cached_loader(symbol, start, end).copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[(frame.index >= start_ts) & (frame.index < end_ts)]
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()

    for gap_start, gap_end in _missing_hour_ranges(expected.difference(frame.index)):
        fetched = gap_fetcher(symbol, gap_start.isoformat(), gap_end.isoformat()).copy()
        fetched.index = pd.to_datetime(fetched.index, utc=True)
        fetched = fetched[(fetched.index >= gap_start) & (fetched.index < gap_end)]
        fetched = fetched.loc[~fetched.index.duplicated(keep="last")].sort_index()
        if len(fetched):
            cache_path = cache_path_factory(symbol, gap_start, gap_end)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            fetched.to_csv(cache_path, index_label="timestamp")
            frame = pd.concat([frame, fetched])
            frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()

    remaining = expected.difference(frame.index)
    if len(remaining):
        preview = ", ".join(str(x) for x in remaining[:5])
        raise RuntimeError(
            f"unable to complete requested Binance history for {symbol}: "
            f"{len(remaining)} hourly bars still missing; first missing: {preview}"
        )
    return frame.reindex(expected)


def _coverage(frames: dict) -> None:
    # Official performance requires only the official holdout bars.
    expected=pd.date_range(START, END, freq="h", inclusive="left")
    missing={s:len(expected.difference(frame.index)) for s,frame in frames.items()}
    if any(missing.values()): raise RuntimeError(f"incomplete final-holdout/risk-label data coverage: {missing}")


def _baseline_targets(closes: pd.DataFrame, config: dict, hours_per_year: int) -> pd.DataFrame:
    raw=MultiHorizonTrend(config["ema_fast"],config["ema_slow"]).target_weights(closes)
    volatility=closes.pct_change(fill_method=None).rolling(config["volatility_window_hours"]).std()*np.sqrt(hours_per_year)
    scaled=raw.mul((config["target_volatility"]/volatility.clip(lower=config["volatility_floor"])).clip(upper=3.0).shift(1).fillna(0.0))
    ready=closes.notna() & closes.rolling(config["volatility_window_hours"],min_periods=config["volatility_window_hours"]).count().eq(config["volatility_window_hours"])
    return enforce_exposure_limits(scaled.where(ready,0.0).fillna(0.0), max_asset=config["max_asset_abs_weight"], max_gross=config["max_gross"])


def _run(opens, closes, targets, cost, config):
    return run_backtest(opens, closes, targets, cost, execution_policy=ExecutionPolicy("Rebalance24h", rebalance_every=config["rebalance_hours"]))


def _risk_outcome_observable(timestamp: pd.Timestamp) -> bool:
    """Next 24 executed hourly returns must end inside the official period."""
    return timestamp + pd.Timedelta(hours=24) < END


def _state_summary(states: pd.DataFrame) -> pd.DataFrame:
    values=states.risk_multiplier.to_numpy(); runs={x:[] for x in (1.0,.75,.5)}; start=0
    for i in range(1,len(values)+1):
        if i==len(values) or values[i] != values[start]: runs[values[start]].append(i-start); start=i
    return pd.DataFrame([{"state":x,"count":int((states.risk_multiplier==x).sum()),"share":float((states.risk_multiplier==x).mean()),"mean_duration_days":float(np.mean(runs[x])) if runs[x] else 0.0,"max_consecutive_days":max(runs[x]) if runs[x] else 0} for x in (1.0,.75,.5)])


def _auc(y: pd.Series, score: pd.Series) -> float:
    positives=int(y.sum()); negatives=int((1-y).sum())
    if not positives or not negatives: return np.nan
    return float((score.rank()[y.astype(bool)].sum()-positives*(positives+1)/2)/(positives*negatives))


def evaluate(frames: dict[str, pd.DataFrame], artifact: dict) -> dict[str, pd.DataFrame]:
    """Fixed Stage-B logic. Caller must have passed preflight before invoking."""
    _coverage(frames)
    symbols=artifact["symbols"]; baseline=artifact["baseline_strategy"]
    opens, closes, _ = panel(frames, symbols); full_index=closes.index
    a_target=_baseline_targets(closes,baseline,artifact["metrics"]["hours_per_year"]); raw=MultiHorizonTrend(baseline["ema_fast"],baseline["ema_slow"]).target_weights(closes); geo=signal_geometry(raw)
    decisions=full_index[(full_index.hour==0)&(full_index.minute==0)]
    pred=_prediction(geo.loc[decisions],artifact); th=artifact["risk_thresholds"]
    daily_mult=risk_multiplier(pred,th["q50"],th["q75"])
    bmult=hold_rebalance_multiplier(full_index,daily_mult)
    c=artifact["controls"]; constant=a_target*c["constant_risk_multiplier"]
    vol=closes.pct_change(fill_method=None).mean(axis=1).rolling(baseline["volatility_window_hours"],min_periods=baseline["volatility_window_hours"]).std(ddof=1)*np.sqrt(artifact["metrics"]["hours_per_year"])
    vmult=vol_only_multiplier(vol.reindex(decisions),c["vol_only_parameters"]["k"]).reindex(full_index).ffill().fillna(1.0)
    targets={"Baseline_A":a_target,"ConstantRisk_A":constant,"VolOnly_A":a_target.mul(vmult,axis=0),"B2E_v1":a_target.mul(bmult,axis=0)}
    performance_index=full_index[(full_index>=START)&(full_index<END)]
    primary_cost=artifact["primary_cost_bps"]
    primary=[]; full={n:_run(opens,closes,t,primary_cost,baseline) for n,t in targets.items()}; results={n:_part(r,performance_index) for n,r in full.items()}
    for n,r in results.items():
        m=metrics(r); w=full[n].weights.loc[performance_index]
        primary.append({"strategy":n,"gross_return":m["gross_return"],"net_return_10bps":m["net_return"],"sharpe":m["sharpe"],"sortino":m["sortino"],"max_drawdown":m["max_drawdown"],"realized_vol":m["annualized_volatility"],"average_gross":w.abs().sum(axis=1).mean(),"average_net":w.sum(axis=1).mean(),"turnover":m["turnover"],"fees":m["fees"],"trade_count":m["trade_count"],"long_trade_count":int((r.trades.weight_change>0).sum()),"short_trade_count":int((r.trades.weight_change<0).sum())})
    costs=[]
    for cost in [*artifact["stress_cost_bps"], primary_cost]:
        for n,t in targets.items():
            r=_part(_run(opens,closes,t,cost,baseline),performance_index); m=metrics(r); costs.append({"cost_bps":cost,"strategy":n,"net_return":m["net_return"],"fees":m["fees"]})
    states=pd.DataFrame({"timestamp":daily_mult.index,"signal_strength":geo.loc[daily_mult.index,"signal_strength"],"signal_dispersion":geo.loc[daily_mult.index,"signal_dispersion"],"predicted_24h_dd_risk":pred,"risk_multiplier":daily_mult})
    states=states[(states.timestamp>=START)&(states.timestamp<END)].copy(); states["risk_bucket"]=pd.cut(states.predicted_24h_dd_risk,[-np.inf,th["q50"],th["q75"],np.inf],labels=["Low","Medium","High"],include_lowest=True).astype(str); states["risk_outcome_observable"]=states.timestamp.map(_risk_outcome_observable); states["baseline_gross"]=full["Baseline_A"].weights.loc[states.timestamp].abs().sum(axis=1).values; states["b2e_gross"]=full["B2E_v1"].weights.loc[states.timestamp].abs().sum(axis=1).values
    observed=states.loc[states.risk_outcome_observable].set_index("timestamp"); realized=_future_dd(full["Baseline_A"],observed.index); joined=observed.join(realized,how="left")
    buckets=pd.DataFrame([{"bucket":b,"count":int((joined.risk_bucket==b).sum()),"mean_realized_dd":joined.loc[joined.risk_bucket==b,"realized_future_dd"].mean(),"median_realized_dd":joined.loc[joined.risk_bucket==b,"realized_future_dd"].median(),"p90_realized_dd":joined.loc[joined.risk_bucket==b,"realized_future_dd"].quantile(.9)} for b in ("Low","Medium","High")])
    severe=artifact["risk_thresholds"]["severe_drawdown_threshold"]
    diagnostic=pd.DataFrame([{"eligible_predictions":len(joined),"pearson":joined.predicted_24h_dd_risk.corr(joined.realized_future_dd),"spearman":joined.predicted_24h_dd_risk.rank().corr(joined.realized_future_dd.rank()),"mse":((joined.predicted_24h_dd_risk-joined.realized_future_dd)**2).mean(),"severe_drawdown_auc":_auc((joined.realized_future_dd>=severe).astype(int),joined.predicted_24h_dd_risk)}])
    daily=pd.DataFrame({"date":performance_index.floor("D").unique()})
    for n,r in results.items(): daily[n+"_equity"]=(1+r.returns).groupby(r.returns.index.floor("D")).prod().cumprod().values
    daily_returns=pd.DataFrame({n:(1+r.returns).groupby(r.returns.index.floor("D")).prod()-1 for n,r in results.items()})
    positive=daily_returns.Baseline_A>0; negative=daily_returns.Baseline_A<0
    capture=pd.DataFrame([{"strategy":n,"upside_capture":daily_returns.loc[positive,n].sum()/daily_returns.loc[positive,"Baseline_A"].sum() if daily_returns.loc[positive,"Baseline_A"].sum() else np.nan,"downside_capture":daily_returns.loc[negative,n].sum()/daily_returns.loc[negative,"Baseline_A"].sum() if daily_returns.loc[negative,"Baseline_A"].sum() else np.nan} for n in ("ConstantRisk_A","VolOnly_A","B2E_v1")])
    trades=[]; target_rows=[]
    for n,t in targets.items():
        for asset in symbols: target_rows.append(pd.DataFrame({"timestamp":performance_index,"asset":asset,"strategy":n,"target_weight":t.loc[performance_index,asset].values,"strategy_version":"B2E_v1","freeze_hash":artifact.get("freeze_hash","")}))
        change=full[n].weights.diff().fillna(full[n].weights).loc[performance_index].stack().rename("weight_change").reset_index().rename(columns={"level_0":"timestamp","level_1":"asset"}); change=change[change.weight_change.abs()>1e-12]; change["strategy"]=n; change["estimated_cost"]=change.weight_change.abs()*.001; trades.append(change)
    return {"PRIMARY_RESULTS":pd.DataFrame(primary),"COST_STRESS":pd.DataFrame(costs),"DAILY_EQUITY":daily,"RISK_STATES":states,"RISK_STATE_SUMMARY":_state_summary(states),"RISK_BUCKETS":buckets,"RISK_DIAGNOSTICS":diagnostic,"CAPTURE":capture,"TARGETS":pd.concat(target_rows),"TRADES":pd.concat(trades)}


def _status(outputs: dict[str,pd.DataFrame]) -> str:
    """Predeclared qualitative rule; this is not an optimization score."""
    p=outputs["PRIMARY_RESULTS"].set_index("strategy"); b=outputs["RISK_BUCKETS"]
    ordering=list(b.mean_realized_dd.dropna()) == sorted(b.mean_realized_dd.dropna())
    b2e=p.loc["B2E_v1"]
    if not ordering and b2e.max_drawdown >= min(p.loc["ConstantRisk_A","max_drawdown"],p.loc["VolOnly_A","max_drawdown"]): return "B2E FINAL HOLDOUT UNSUPPORTIVE"
    if ordering and b2e.max_drawdown <= p.loc["Baseline_A","max_drawdown"] and b2e.max_drawdown <= min(p.loc["ConstantRisk_A","max_drawdown"],p.loc["VolOnly_A","max_drawdown"]): return "B2E FINAL HOLDOUT SUPPORTIVE"
    return "B2E FINAL HOLDOUT MIXED"


def _report(outputs: dict[str,pd.DataFrame], artifact: dict) -> str:
    p=outputs["PRIMARY_RESULTS"].set_index("strategy"); cost=outputs["COST_STRESS"].pivot(index="cost_bps",columns="strategy",values="net_return"); states=outputs["RISK_STATES"]; buckets=outputs["RISK_BUCKETS"]; diag=outputs["RISK_DIAGNOSTICS"].iloc[0]; status=_status(outputs); state_summary=outputs["RISK_STATE_SUMMARY"]
    ret=p.loc["B2E_v1","net_return_10bps"]/p.loc["Baseline_A","net_return_10bps"] if p.loc["Baseline_A","net_return_10bps"] else np.nan
    def comparison(name):
        x=p.loc["B2E_v1"]-p.loc[name]
        return f"Net return difference {x.net_return_10bps:.2%}; max-DD difference {x.max_drawdown:.2%}; realized-vol difference {x.realized_vol:.2%}; average-gross difference {x.average_gross:.2%}; turnover difference {x.turnover:.3f}."
    implication="Baseline A remains the competition candidate. B2E_v1 remains research-only." if status.endswith("UNSUPPORTIVE") else ("Baseline A remains the production candidate. B2E_v1 is not promoted." if status.endswith("MIXED") else "B2E_v1 may be labeled A+ CANDIDATE. No production migration is performed automatically.")
    return f"""# B2E_v1 Final Holdout Report

## 1. Holdout Declaration

B2E_v1 was frozen before this final holdout. The official untouched holdout is 2026-09-22 00:00 UTC through 2026-10-03 23:00 UTC. No final-holdout observations were used for calibration, parameter selection, feature selection, or strategy tuning. No B2E_v1 parameter was changed after the holdout was released.

## 2. Freeze / Calibration Verification

Artifact: frozen/b2e_v1.json. SHA-256: {artifact['freeze_hash']}. Freeze verifier: PASS; maximum reproduction error: {artifact['verification']['max_difference']:.3e}. ConstantRisk multiplier: {artifact['controls']['constant_risk_multiplier']:.16f}. VolOnly k: {artifact['controls']['vol_only_parameters']['k']:.16f}. Strategy version: B2E_v1.

## 3. Data Coverage

First official timestamp: {START}; last: {END-pd.Timedelta(hours=1)}; expected/observed hourly bars: {len(pd.date_range(START,END,freq='h',inclusive='left'))}; missing bars: 0. Warmup begins before the official period and does not contribute to PnL. B2E predictions: {len(states)}; complete 24h outcomes: {states.risk_outcome_observable.sum()}; excluded late outcomes: {(~states.risk_outcome_observable).sum()}.

## 4. Frozen Strategy Definitions

Exactly four strategies: Baseline A, frozen ConstantRisk A, frozen VolOnly A, and frozen B2E_v1. All configuration and costs are loaded from the immutable artifact.

## 5. Full Holdout Results

{p.T.to_markdown(floatfmt='.6f')}

## 6. Cost Stress

{cost.to_markdown(floatfmt='.6f')}

## 7. Competition-Length Interpretation

The complete fixed 12-day official period is the competition-length interpretation; no subwindow was selected.

## 8. B2E Risk-State Usage

{state_summary.to_markdown(floatfmt='.6f')}

## 9. B2E Risk-Prediction Validation

Only complete future-24h outcomes inside the official dataset are scored. N={int(diag.eligible_predictions)}, Pearson={diag.pearson:.4f}, Spearman={diag.spearman:.4f}, MSE={diag.mse:.6g}, severe-drawdown AUC={diag.severe_drawdown_auc:.4f}.

## 10. Frozen Risk-Bucket Validation

Only predictions with complete 24h outcomes inside the official holdout are included.

{buckets.to_markdown(index=False,floatfmt='.6f')}

## 11. B2E vs Baseline A

{comparison('Baseline_A')} Return retention: {ret:.4f}.

## 12. B2E vs ConstantRisk

{comparison('ConstantRisk_A')} This is a descriptive comparison of dynamic timing with permanent exposure reduction.

## 13. B2E vs VolOnly

{comparison('VolOnly_A')} The simpler volatility-only control receives equal treatment.

## 14. Upside / Downside Capture

Upside capture is the ratio of strategy to Baseline A summed daily returns on days where Baseline A is positive; downside capture uses days where Baseline A is negative.

{outputs['CAPTURE'].to_markdown(index=False,floatfmt='.6f')}

## 15. Limitations

This is a short sample. Annualized ratios and small risk buckets are descriptive, not statistically conclusive.

## 16. Final Status

**{status}**

## 17. Production Implication

{implication}
"""


def write_outputs(outputs: dict[str,pd.DataFrame], artifact: dict) -> None:
    OUT.mkdir(parents=True,exist_ok=True)
    for name,frame in outputs.items(): frame.to_csv(OUT/f"{name}.csv",index=False)
    pd.DataFrame([{ "strategy_version":"B2E_v1", "freeze_hash":artifact["freeze_hash"], "holdout_start":START.isoformat(), "holdout_end":(END-pd.Timedelta(hours=1)).isoformat()}]).to_csv(OUT/"EXPERIMENT_LOG.csv",index=False)
    (ROOT/"FINAL_HOLDOUT_REPORT.md").write_text(_report(outputs,artifact))


def main() -> None:
    gate=preflight()  # Must happen before any market-data call.
    artifact=gate["artifact"]; artifact["freeze_hash"]=gate["verification"]["hash"]
    frames={s:_load_complete_history(s,DEV_START,END.isoformat()) for s in artifact["symbols"]}
    outputs=evaluate(frames,artifact); artifact["verification"]=gate["verification"]
    write_outputs(outputs,artifact)


if __name__ == "__main__": main()
