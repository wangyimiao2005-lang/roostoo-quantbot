"""Describe raw-target churn before attempting to change execution."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from common import ROOT, load_universe
from quant_competition.portfolio import enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend, DonchianBreakout, CrossSectionalMomentum, VWAPMeanReversion
from quant_competition.backtest import run_backtest

def main():
    opens, closes, volumes, _ = load_universe(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"],"2025-01-01","2026-01-01")
    strategies=[MultiHorizonTrend(12,36),DonchianBreakout(48),CrossSectionalMomentum(48),VWAPMeanReversion(2.0)]
    rows=[]; buckets=[]
    for s in strategies:
        target=s.target_weights(closes,volumes=volumes); target=enforce_exposure_limits(risk_scale_targets(target,closes.pct_change()))
        changes=target.diff().abs().stack().dropna(); result=run_backtest(opens,closes,target,10,.02); gross_abs=result.gross_returns.abs().sum()
        rows.append({"strategy":s.name,"target_weight_changes":len(changes),"actual_trades":len(result.trades),"avg_abs_target_change":changes.mean(),"median_abs_target_change":changes.median(),"p90_abs_target_change":changes.quantile(.9),"p95_abs_target_change":changes.quantile(.95),"turnover_per_day":result.turnover.sum()/365,"turnover_per_week":result.turnover.sum()/52,"median_turnover_per_14d":result.turnover.rolling(336).sum().median(),"cost_to_gross_profit":result.costs.sum()/max((1+result.gross_returns).prod()-1,1e-9),"cost_to_absolute_gross_pnl":result.costs.sum()/max(gross_abs,1e-9)})
        for label,lo,hi in [("<1%",0,.01),("1-2%",.01,.02),("2-5%",.02,.05),("5-10%",.05,.1),("10-20%",.1,.2),(">20%",.2,np.inf)]: buckets.append({"strategy":s.name,"trade_size_bucket":label,"pct_target_changes":((changes>=lo)&(changes<hi)).mean()})
    out=ROOT/"results/diagnostics"; pd.DataFrame(rows).to_csv(out/"turnover_diagnostics.csv",index=False); pd.DataFrame(buckets).to_csv(out/"trade_size_distribution.csv",index=False)
    pivot=pd.DataFrame(buckets).pivot(index="trade_size_bucket",columns="strategy",values="pct_target_changes"); pivot.plot(kind="bar",figsize=(10,5),title="Raw target-change size distribution"); plt.tight_layout(); plt.savefig(ROOT/"results/plots/trade_size_distribution.png",dpi=150); plt.close()
    print(pd.DataFrame(rows).round(4).to_string(index=False))
if __name__ == "__main__": main()
