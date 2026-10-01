"""Staged, deliberately small execution-policy experiment at the primary 10 bps cost."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from common import ROOT, load_universe
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics, rolling_competition_metrics
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend, DonchianBreakout, CrossSectionalMomentum, VWAPMeanReversion

def candidate_targets(closes,volumes):
    strategies=[MultiHorizonTrend(12,36),DonchianBreakout(48),CrossSectionalMomentum(48),VWAPMeanReversion(2.0)]
    return {s.name:enforce_exposure_limits(risk_scale_targets(s.target_weights(closes,volumes=volumes),closes.pct_change())) for s in strategies}
def policy_set():
    return [ExecutionPolicy("Immediate"),ExecutionPolicy("Phase1_Buffer2pct",absolute_buffer=.02),ExecutionPolicy("Buffer5pct",absolute_buffer=.05),ExecutionPolicy("Buffer10pct",absolute_buffer=.10),ExecutionPolicy("Buffer15pct",absolute_buffer=.15),ExecutionPolicy("Rebalance4h",rebalance_every=4),ExecutionPolicy("Rebalance8h",rebalance_every=8),ExecutionPolicy("Rebalance12h",rebalance_every=12),ExecutionPolicy("Rebalance24h",rebalance_every=24),ExecutionPolicy("8h_Buffer5pct",rebalance_every=8,absolute_buffer=.05),ExecutionPolicy("Smoothing50pct",smoothing_alpha=.5),ExecutionPolicy("Partial50pct",partial_lambda=.5)]
def main():
    opens,closes,volumes,_=load_universe(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"],"2025-01-01","2026-01-01"); rows=[]
    for strategy,target in candidate_targets(closes,volumes).items():
        for policy in policy_set():
            results={bps:run_backtest(opens,closes,target,bps,execution_policy=policy) for bps in [5,10,15,20]}; primary=results[10]; m=performance_metrics(primary.returns,primary.costs,primary.turnover); rolling=rolling_competition_metrics(primary.returns)
            gross=(1+primary.gross_returns).prod()-1; break_even=(gross/max(primary.turnover.sum(),1e-9))*10000
            rows.append({"strategy":strategy,"timeframe":"1h","execution_policy":policy.name,"gross_return":gross,**{f"net_return_{bps}bps":(1+r.returns).prod()-1 for bps,r in results.items()},**{f"sharpe_{bps}bps":performance_metrics(r.returns,r.costs,r.turnover)["sharpe"] for bps,r in results.items()},"sortino":m["sortino"],"calmar":m["calmar"],"max_drawdown":m["max_drawdown"],"turnover":m["turnover"],"cost_drag_ratio":m["total_cost"]/max(abs(gross),1e-9),"trades":len(primary.trades),"trades_per_14d":len(primary.trades)/(len(primary.returns)/336),"positive_14d_probability":rolling["positive_14d_probability"],"break_even_cost_bps":break_even,"gross_return_per_turnover":gross/max(m["turnover"],1e-9),"net_return_per_turnover":((1+primary.returns).prod()-1)/max(m["turnover"],1e-9)})
    table=pd.DataFrame(rows); table["status"]="REJECTED"; table.to_csv(ROOT/"results/tables/execution_robustness_summary.csv",index=False)
    before=table[table.execution_policy=="Phase1_Buffer2pct"].set_index("strategy"); improved=table.sort_values("net_return_10bps",ascending=False).groupby("strategy").first(); compare=pd.DataFrame({"phase1_net_10bps":before.net_return_10bps,"improved_net_10bps":improved.net_return_10bps,"phase1_cost":before.turnover*.001,"improved_cost":improved.turnover*.001,"phase1_turnover":before.turnover,"improved_turnover":improved.turnover,"phase1_trades":before.trades,"improved_trades":improved.trades,"phase1_sharpe":before.sharpe_10bps,"improved_sharpe":improved.sharpe_10bps,"selected_policy":improved.execution_policy}); compare.to_csv(ROOT/"results/tables/execution_before_after.csv")
    for value,title,file in [("net_return_10bps","Net return at 10 bps", "net_vs_policy.png"),("turnover","Turnover", "turnover_vs_policy.png")]:
        table.pivot(index="execution_policy",columns="strategy",values=value).plot(kind="bar",figsize=(12,5),title=title); plt.tight_layout(); plt.savefig(ROOT/"results/plots"/file,dpi=150); plt.close()
    print(table.sort_values("net_return_10bps",ascending=False)[["strategy","execution_policy","gross_return","net_return_10bps","turnover","trades","break_even_cost_bps"]].head(16).round(4).to_string(index=False))
if __name__ == "__main__": main()
