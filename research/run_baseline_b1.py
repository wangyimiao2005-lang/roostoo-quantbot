"""Baseline B1 -- pre-registered expanded-universe research.

This is deliberately separate from the production and paper-runner paths.  It
uses the frozen Baseline A Trend 8/24 signal, sizing and next-bar execution;
only the ex-ante eligible universe changes.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics
from quant_competition.metrics.drawdown import drawdown
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend

BASE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
CANDIDATES = BASE + ["ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "TRXUSDT", "UNIUSDT", "ETCUSDT", "APTUSDT", "NEARUSDT", "ATOMUSDT"]
DEV_START, OOS_START, OOS_END = "2025-01-01", "2026-01-01", "2026-09-01"
SELECTION_END = pd.Timestamp(OOS_START, tz="UTC")
OUT = ROOT / "results" / "baseline_b1"


def raw_path(symbol: str, start: str, end: str) -> Path:
    return ROOT / "data" / "raw" / f"{symbol}_1h_{start}_{end}.csv"


def fetch_public_binance(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Fetch exactly the requested public Binance 1h interval, [start, end).

    This helper deliberately does not inspect or merge repository caches.  It is
    used by the sealed final-holdout loader only after a coverage audit has
    identified a missing contiguous range.
    """
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    rows = []
    while start_ms < end_ms:
        query = urllib.parse.urlencode({"symbol": symbol, "interval": "1h", "limit": 1000,
                                        "startTime": start_ms, "endTime": end_ms})
        with urllib.request.urlopen(f"https://api.binance.com/api/v3/klines?{query}", timeout=30) as response:
            page = json.load(response)
        if not page:
            break
        rows.extend(page)
        next_start = int(page[-1][6]) + 1
        if next_start <= start_ms:
            raise RuntimeError("Binance pagination did not advance")
        start_ms = next_start
        time.sleep(.15)
    columns = ["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    frame = pd.DataFrame(rows, columns=columns)
    if len(frame):
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        frame = frame.set_index("timestamp")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column])
        frame = frame[["open", "high", "low", "close", "volume"]]
        start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        frame = frame[(frame.index >= start_ts) & (frame.index < end_ts)]
    else:
        frame = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return frame.sort_index()


def read_or_fetch(symbol: str, start: str, end: str) -> pd.DataFrame:
    path = raw_path(symbol, start, end)
    if path.exists():
        frame = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        return frame.sort_index()
    # Baseline A was cached as adjacent development and OOS files. Reuse those
    # exact observations instead of redownloading the frozen reference data.
    parts = sorted((ROOT / "data" / "raw").glob(f"{symbol}_1h_*.csv"))
    selected = []
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    for part in parts:
        frame = pd.read_csv(part, index_col="timestamp", parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame = frame[(frame.index >= start_ts) & (frame.index < end_ts)]
        if len(frame): selected.append(frame)
    if selected:
        return pd.concat(selected).loc[lambda x: ~x.index.duplicated(keep="last")].sort_index()
    # Kept local to B1 so this research runner has no dependency on production
    # provider configuration. It requests public Binance spot klines only.
    frame = fetch_public_binance(symbol, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index_label="timestamp")
    return frame.sort_index()


def expected_index(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")


def selection_and_quality(frames: dict[str, pd.DataFrame]) -> tuple[list[str], pd.DataFrame]:
    expected = expected_index(DEV_START, OOS_START)
    rows, included = [], []
    for asset in CANDIDATES:
        frame = frames[asset]
        train = frame.reindex(expected)
        valid = train[["open", "close", "volume"]].notna().all(axis=1)
        missing = 1 - valid.mean()
        # Dollar-volume selection uses only 2025 observations, before frozen OOS.
        median_dollar_volume = (train.loc[valid, "close"] * train.loc[valid, "volume"]).median()
        first = frame.index.min() if len(frame) else pd.NaT
        last = frame.index.max() if len(frame) else pd.NaT
        reason = "included"
        if valid.sum() < 24 * 180:
            reason = "fewer than 180 days of valid pre-OOS hourly history"
        elif missing > 0.005:
            reason = "pre-OOS missing-bar rate exceeds 0.5%"
        elif not pd.notna(median_dollar_volume) or median_dollar_volume < 1_000_000:
            reason = "2025 median hourly dollar volume below US$1m"
        else:
            included.append(asset)
        usable = train.index[valid][0] if valid.any() else pd.NaT
        rows.append({"asset": asset, "first_timestamp": first, "last_timestamp": last,
                     "hourly_rows": len(frame), "expected_rows": len(expected), "missing_rate": missing,
                     "median_hourly_dollar_volume_2025": median_dollar_volume, "usable_from": usable,
                     "included_or_excluded": "included" if reason == "included" else "excluded",
                     "exclusion_reason": "" if reason == "included" else reason})
    return included, pd.DataFrame(rows)


def panel(frames: dict[str, pd.DataFrame], symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Union preserves genuine gaps. No OHLCV bar is forward-filled.
    idx = pd.DatetimeIndex(sorted(set().union(*(set(frames[s].index) for s in symbols))))
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in symbols}, index=idx)
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in symbols}, index=idx)
    volumes = pd.DataFrame({s: frames[s]["volume"].reindex(idx) for s in symbols}, index=idx)
    return opens, closes, volumes


def targets(closes: pd.DataFrame) -> pd.DataFrame:
    raw = MultiHorizonTrend(8, 24).target_weights(closes)
    # Explicitly prohibit pandas' historical default forward-fill behaviour.
    scaled = risk_scale_targets(raw, closes.pct_change(fill_method=None))
    # Both indicators and a current real bar are required; missing data means flat.
    ready = closes.notna() & (closes.rolling(48, min_periods=48).count() == 48)
    return enforce_exposure_limits(scaled.where(ready, 0.0).fillna(0.0))


def run(opens: pd.DataFrame, closes: pd.DataFrame, target: pd.DataFrame, cost: int):
    return run_backtest(opens, closes, target, cost, execution_policy=ExecutionPolicy("Rebalance24h", rebalance_every=24))


def metrics(result) -> dict:
    m = performance_metrics(result.returns, result.costs, result.turnover)
    gross_return = (1 + result.gross_returns).prod() - 1
    net_return = (1 + result.returns).prod() - 1
    gross_pnl = result.gross_returns.sum()
    return {"gross_return": gross_return, "net_return": net_return, "sharpe": m["sharpe"], "sortino": m["sortino"],
            "calmar": m["calmar"], "max_drawdown": m["max_drawdown"], "annualized_volatility": m["annualized_volatility"],
            "turnover": m["turnover"], "annualized_turnover": m["turnover"] * 8760 / max(len(result.returns), 1),
            "trade_count": len(result.trades), "trades_per_day": len(result.trades) / max(len(result.returns) / 24, 1),
            "fees": m["total_cost"], "fees_pct_gross_pnl": m["total_cost"] / gross_pnl if gross_pnl else np.nan,
            "break_even_cost_bps": gross_return / max(m["turnover"], 1e-12) * 10000}


def rolling(result, prefix: str) -> pd.DataFrame:
    n = 336
    ret = (1 + result.returns).rolling(n).apply(np.prod, raw=True) - 1
    dd = result.returns.rolling(n).apply(lambda x: drawdown(pd.Series(x)).min(), raw=False)
    return pd.DataFrame({f"{prefix}_return": ret, f"{prefix}_max_drawdown": dd,
                         f"{prefix}_turnover": result.turnover.rolling(n).sum(), f"{prefix}_fees": result.costs.rolling(n).sum()})


def rolling_summary(frame: pd.DataFrame, prefix: str) -> dict:
    r, d = frame[f"{prefix}_return"].dropna(), frame[f"{prefix}_max_drawdown"].dropna()
    return {"windows": len(r), "mean_14d_return": r.mean(), "median_14d_return": r.median(), "positive_14d_pct": (r > 0).mean(),
            "p25_14d_return": r.quantile(.25), "p10_14d_return": r.quantile(.10), "p5_14d_return": r.quantile(.05),
            "worst_14d_return": r.min(), "best_14d_return": r.max(), "median_14d_max_drawdown": d.median(),
            "worst_14d_max_drawdown": d.min(), "median_14d_turnover": frame[f"{prefix}_turnover"].median(),
            "median_14d_fees": frame[f"{prefix}_fees"].median()}


def attribution(result) -> pd.DataFrame:
    intrabar = result.weights.mul(0)  # aligned empty holder
    # The caller stores open/close-derived gross elsewhere; reconstructing per-asset is passed in main.
    return intrabar


def write_report(included: list[str], excluded: pd.DataFrame, a: dict, b: dict, roll: dict, wf: pd.DataFrame, concentration: dict, cost: pd.DataFrame):
    decision = "KEEP B1 AS RESEARCH CANDIDATE" if b["net_return"] >= a["net_return"] and b["sharpe"] >= a["sharpe"] else "REJECT B1"
    text = f"""# Baseline B1 — Expanded Universe Research

## 1. Objective
Test whether an expanded, ex-ante selected crypto universe improves frozen Baseline A while holding signal, timing, sizing, caps, rebalancing and costs constant.

## 2. Frozen Baseline A definition
BTC, ETH, SOL, BNB, XRP; hourly EMA 8/24 standardized by 24-hour close standard deviation, clipped to [-2,2] / 2; 48-hour per-asset volatility scaling to 35% with 5% floor; 35% asset and 100% gross caps; 24-hour rebalance; next-bar open-to-close execution; 10 bps per side primary cost.

## 3. Pre-registered B1 universe selection rule
The candidate list was fixed before performance runs: {', '.join(CANDIDATES)}. Selection cutoff was 2026-01-01 UTC. An asset must have at least 180 days of valid 2025 hourly OHLCV, <=0.5% missing valid OHLCV bars during 2025, and median 2025 hourly close × volume >= US$1m. Strategy returns, Sharpe, momentum and PnL were never inputs. Indicators require 48 consecutive valid hourly closes; a missing/currently invalid bar is excluded, never forward-filled.

Included ({len(included)}): {', '.join(included)}.

Excluded: {', '.join(excluded.asset.tolist()) or 'none'}.

## 4. Data quality
See `results/baseline_b1/data_quality.csv`; it records point-in-time availability and each inclusion decision.

## 5. Baseline A reproduction
At 10 bps OOS, net return {a['net_return']:.2%}, Sharpe {a['sharpe']:.3f}, Sortino {a['sortino']:.3f}, Calmar {a['calmar']:.3f}, max drawdown {a['max_drawdown']:.2%}. This run uses the frozen engine and OOS dates 2026-01-01 through 2026-08-31.

## 6–9. B1, walk-forward, frozen OOS and cost stress
B1 net return {b['net_return']:.2%}, Sharpe {b['sharpe']:.3f}, max drawdown {b['max_drawdown']:.2%}. Cost results are in `COST_STRESS.csv`; walk-forward fixed-policy weekly results are in `walk_forward.csv`.

## 10. Rolling 14-day comparison
A median {roll['A']['median_14d_return']:.2%}; B1 median {roll['B1']['median_14d_return']:.2%}. Full overlapping-window distribution is `rolling_14d.csv`.

## 11–14. Attribution, concentration and robustness
Per-asset attribution is in `asset_contribution.csv`, breadth in `breadth.csv`, subperiods in `subperiods.csv`, correlation diagnostics in `correlation_diagnostics.csv`, universe breadth variants in `universe_size_robustness.csv`, and leave-one-out diagnostics in `leave_one_out.csv`. B1 top-1 / top-3 PnL shares are {concentration['top1_pnl_share']:.1%} / {concentration['top3_pnl_share']:.1%}.

## 15. Multiple-testing caveats
All breadth variants and leave-one-out diagnostics are logged in `EXPERIMENT_LOG.csv`. They are diagnostics only and cannot be used to select a new production universe.

## 16. Limitations
Binance spot OHLCV and dollar volume are proxies for Roostoo tradability. The universe is selected using pre-OOS history, but exchange availability is not a guarantee of competition availability. Correlation diagnostics do not change weights.

## 17. Decision
**{decision}**. Baseline A remains frozen and no live, broker, PaperRunner, or production configuration was changed.
"""
    (ROOT / "BASELINE_B1_RESEARCH_REPORT.md").write_text(text)
    return decision


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Fetch the single fixed research span once for selection and evaluation.
    frames = {s: read_or_fetch(s, DEV_START, OOS_END) for s in CANDIDATES}
    included, quality = selection_and_quality(frames)
    quality.to_csv(OUT / "data_quality.csv", index=False)
    if not set(BASE).issubset(included):
        raise RuntimeError("Baseline A assets failed B1 data-quality screen; investigate data before comparison")
    o_a, c_a, _ = panel(frames, BASE)
    o_b, c_b, _ = panel(frames, included)
    t_a, t_b = targets(c_a), targets(c_b)
    # Same fixed calendar OOS and engine.  Targets include pre-OOS warm-up history.
    mask_a = (o_a.index >= SELECTION_END) & (o_a.index < pd.Timestamp(OOS_END, tz="UTC"))
    mask_b = (o_b.index >= SELECTION_END) & (o_b.index < pd.Timestamp(OOS_END, tz="UTC"))
    ra = run(o_a.loc[mask_a], c_a.loc[mask_a], t_a.loc[mask_a], 10)
    rb = run(o_b.loc[mask_b], c_b.loc[mask_b], t_b.loc[mask_b], 10)
    a, b = metrics(ra), metrics(rb)
    common = ra.returns.index.intersection(rb.returns.index)
    ra_common = run(o_a.loc[common], c_a.loc[common], t_a.loc[common], 10)
    rb_common = run(o_b.loc[common], c_b.loc[common], t_b.loc[common], 10)
    a_common, b_common = metrics(ra_common), metrics(rb_common)
    rows = [{"metric": k, "Baseline_A": v, "Baseline_B1": b.get(k), "difference": b.get(k, np.nan)-v if pd.notna(b.get(k, np.nan)) else np.nan,
             "relative_difference": (b.get(k, np.nan)/v-1) if v not in (0, np.nan) else np.nan, "comparison": "production_realistic"} for k,v in a.items()]
    rows += [{"metric": k, "Baseline_A": v, "Baseline_B1": b_common.get(k), "difference": b_common.get(k, np.nan)-v if pd.notna(b_common.get(k, np.nan)) else np.nan,
              "relative_difference": (b_common.get(k, np.nan)/v-1) if v else np.nan, "comparison": "strict_common_sample"} for k,v in a_common.items()]
    pd.DataFrame(rows).to_csv(OUT / "AB_COMPARISON.csv", index=False)
    costs=[]
    for fee in (5,10,15,20):
        xa, xb = metrics(run(o_a.loc[mask_a],c_a.loc[mask_a],t_a.loc[mask_a],fee)), metrics(run(o_b.loc[mask_b],c_b.loc[mask_b],t_b.loc[mask_b],fee))
        costs.extend([{"strategy":"A","cost_bps_per_side":fee,**xa},{"strategy":"B1","cost_bps_per_side":fee,**xb}])
    cost_df=pd.DataFrame(costs); cost_df.to_csv(OUT / "COST_STRESS.csv",index=False)
    roll = rolling(ra,"A").join(rolling(rb,"B1"),how="inner").dropna()
    roll.insert(0,"window_start",roll.index-pd.Timedelta(hours=335)); roll.insert(1,"window_end",roll.index)
    roll.to_csv(OUT / "rolling_14d.csv",index=False)
    rollsum={"A":rolling_summary(roll,"A"),"B1":rolling_summary(roll,"B1")}
    # Attribution / concentration based solely on B1 OOS.
    intrabar=c_b.loc[mask_b].div(o_b.loc[mask_b]).sub(1).fillna(0)
    gross_by=rb.weights*intrabar; changes=rb.weights.diff().fillna(rb.weights); fees_by=changes.abs()*.001
    attrs=[]
    for s in included:
        attrs.append({"asset":s,"gross_contribution":gross_by[s].sum(),"net_contribution":(gross_by[s]-fees_by[s]).sum(),"turnover":changes[s].abs().sum(),"fees":fees_by[s].sum(),"average_absolute_weight":rb.weights[s].abs().mean(),"long_contribution":(gross_by[s].where(rb.weights[s]>0,0)-fees_by[s].where(rb.weights[s]>0,0)).sum(),"short_contribution":(gross_by[s].where(rb.weights[s]<0,0)-fees_by[s].where(rb.weights[s]<0,0)).sum()})
    attrs=pd.DataFrame(attrs); attrs.to_csv(OUT/"asset_contribution.csv",index=False)
    netpos=attrs.net_contribution.clip(lower=0).sort_values(ascending=False); denom=netpos.sum()
    concentration={"average_active_positions":(rb.weights.abs()>1e-12).sum(axis=1).mean(),"median_active_positions":(rb.weights.abs()>1e-12).sum(axis=1).median(),"largest_average_asset_weight":attrs.average_absolute_weight.max(),"top1_pnl_share":netpos.iloc[:1].sum()/denom if denom else np.nan,"top3_pnl_share":netpos.iloc[:3].sum()/denom if denom else np.nan}
    breadth=pd.DataFrame({"eligible_assets":c_b.loc[mask_b].notna().sum(axis=1),"active_positions":(rb.weights.abs()>1e-12).sum(axis=1),"long_positions":(rb.weights>1e-12).sum(axis=1),"short_positions":(rb.weights<-1e-12).sum(axis=1)}); breadth.to_csv(OUT/"breadth.csv")
    subperiods=[]
    for year in sorted(set(ra.returns.index.year)):
        ia, ib = ra.returns.index.year == year, rb.returns.index.year == year
        subperiods.append({"period":str(year), **{f"A_{k}":v for k,v in metrics(type("R",(),{"returns":ra.returns.loc[ia],"gross_returns":ra.gross_returns.loc[ia],"costs":ra.costs.loc[ia],"turnover":ra.turnover.loc[ia],"trades":ra.trades[ra.trades.timestamp.dt.year==year]})()).items()}, **{f"B1_{k}":v for k,v in metrics(type("R",(),{"returns":rb.returns.loc[ib],"gross_returns":rb.gross_returns.loc[ib],"costs":rb.costs.loc[ib],"turnover":rb.turnover.loc[ib],"trades":rb.trades[rb.trades.timestamp.dt.year==year]})()).items()}})
    pd.DataFrame(subperiods).to_csv(OUT/"subperiods.csv",index=False)
    correlations=c_b.loc[mask_b].pct_change(fill_method=None).corr()
    corr_rows=[{"metric":"median_pairwise_correlation","asset":"ALL","value":correlations.where(~np.eye(len(correlations),dtype=bool)).stack().median()}]
    corr_rows += [{"metric":"BTC_correlation","asset":s,"value":correlations.loc["BTCUSDT",s]} for s in included if s != "BTCUSDT"]
    pd.DataFrame(corr_rows).to_csv(OUT/"correlation_diagnostics.csv",index=False)
    # Pre-specified breadth follows ex-ante 2025 median dollar volume ranking.
    ranking=quality.query("included_or_excluded == 'included'").sort_values("median_hourly_dollar_volume_2025",ascending=False).asset.tolist()
    robust=[]
    for n in [x for x in (8,12,16,len(ranking)) if x <= len(ranking)]:
        syms=ranking[:n]; oo,cc,_=panel(frames,syms); tt=targets(cc); m=(oo.index>=SELECTION_END)&(oo.index<pd.Timestamp(OOS_END,tz="UTC")); robust.append({"universe_size":n,"assets":" ".join(syms),**metrics(run(oo.loc[m],cc.loc[m],tt.loc[m],10))})
    pd.DataFrame(robust).drop_duplicates("universe_size").to_csv(OUT/"universe_size_robustness.csv",index=False)
    loo=[]
    for omit in included:
        syms=[s for s in included if s!=omit]; oo,cc,_=panel(frames,syms); tt=targets(cc); m=(oo.index>=SELECTION_END)&(oo.index<pd.Timestamp(OOS_END,tz="UTC")); loo.append({"omitted_asset":omit,**metrics(run(oo.loc[m],cc.loc[m],tt.loc[m],10))})
    pd.DataFrame(loo).to_csv(OUT/"leave_one_out.csv",index=False)
    # Fixed-policy rolling walk-forward reporting: no model/universe selection occurs inside windows.
    wf=[]
    for start in pd.date_range(OOS_START, OOS_END, freq="7D", inclusive="left", tz="UTC"):
        end=min(start+pd.Timedelta(days=7),pd.Timestamp(OOS_END,tz="UTC")); ix=ra.returns.index[(ra.returns.index>=start)&(ra.returns.index<end)];
        if len(ix): wf.append({"test_start":start,"test_end":end,"A_net_return":(1+ra.returns.loc[ix]).prod()-1,"B1_net_return":(1+rb.returns.loc[ix]).prod()-1,"A_sharpe":performance_metrics(ra.returns.loc[ix],ra.costs.loc[ix],ra.turnover.loc[ix])["sharpe"],"B1_sharpe":performance_metrics(rb.returns.loc[ix],rb.costs.loc[ix],rb.turnover.loc[ix])["sharpe"]})
    wf=pd.DataFrame(wf); wf.to_csv(OUT/"walk_forward.csv",index=False)
    experiment=[]
    now=datetime.now(timezone.utc).isoformat()
    for _,x in cost_df.iterrows(): experiment.append({"experiment_id":f"cost_{x.strategy}_{int(x.cost_bps_per_side)}","date_time":now,"universe_rule":"pre-registered 2025 data/liquidity screen","number_of_assets":len(BASE) if x.strategy=="A" else len(included),"cost":x.cost_bps_per_side,"period":"2026-01-01:2026-08-31","reason_for_experiment":"required cost stress","result_summary":f"net={x.net_return:.4%}; sharpe={x.sharpe:.3f}"})
    for _,x in pd.DataFrame(robust).drop_duplicates("universe_size").iterrows(): experiment.append({"experiment_id":f"breadth_{int(x.universe_size)}","date_time":now,"universe_rule":"pre-registered dollar-volume ranking","number_of_assets":x.universe_size,"cost":10,"period":"2026-01-01:2026-08-31","reason_for_experiment":"pre-specified breadth robustness","result_summary":f"net={x.net_return:.4%}; sharpe={x.sharpe:.3f}"})
    for _,x in pd.DataFrame(loo).iterrows(): experiment.append({"experiment_id":f"leave_out_{x.omitted_asset}","date_time":now,"universe_rule":"full pre-registered universe less one diagnostic asset","number_of_assets":len(included)-1,"cost":10,"period":"2026-01-01:2026-08-31","reason_for_experiment":"leave-one-out diagnostic","result_summary":f"net={x.net_return:.4%}; sharpe={x.sharpe:.3f}"})
    pd.DataFrame(experiment).to_csv(OUT/"EXPERIMENT_LOG.csv",index=False)
    (ROOT/"BASELINE_B1_UNIVERSE.md").write_text("# Baseline B1 pre-registered universe\n\nSelection cutoff: 2026-01-01 UTC. Candidates: " + ", ".join(CANDIDATES) + ".\n\nRule: >=180 days valid pre-OOS hourly OHLCV, <=0.5% missing valid 2025 bars, and >=US$1m median 2025 hourly close × volume. No return, PnL, Sharpe, momentum, or post-selection strategy metric was used.\n\nIncluded: " + ", ".join(included) + ".\n\nSee `results/baseline_b1/data_quality.csv` for exclusions and timestamps.\n")
    decision=write_report(included,quality.query("included_or_excluded == 'excluded'"),a,b,rollsum,wf,concentration,cost_df)
    summary={"baseline_a":a,"baseline_b1":b,"rolling_14d":rollsum,"concentration":concentration,"included":included,"decision":decision}
    (OUT/"summary.json").write_text(json.dumps(summary,default=str,indent=2))
    print(json.dumps(summary,default=str,indent=2))

if __name__ == "__main__":
    main()
