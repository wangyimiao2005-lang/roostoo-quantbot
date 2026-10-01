from pathlib import Path
import json
import numpy as np
import pandas as pd
from common import ROOT, load_universe
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics, rolling_competition_metrics
from quant_competition.portfolio import enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import Cash, MultiHorizonTrend, DonchianBreakout, VWAPMeanReversion, CrossSectionalMomentum
def main():
    symbols=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]; opens,closes,volumes,diagnostics=load_universe(symbols,"2025-01-01","2026-01-01")
    strategies=[Cash(),MultiHorizonTrend(4,12),MultiHorizonTrend(8,24),MultiHorizonTrend(12,36),DonchianBreakout(12),DonchianBreakout(24),DonchianBreakout(48),CrossSectionalMomentum(6),CrossSectionalMomentum(24),CrossSectionalMomentum(48),VWAPMeanReversion(1.0),VWAPMeanReversion(1.5),VWAPMeanReversion(2.0)]
    rows=[]; returns={}; cost_rows=[]
    for strategy in strategies:
        target=strategy.target_weights(closes,volumes=volumes); target=risk_scale_targets(target,closes.pct_change()).pipe(enforce_exposure_limits)
        result=run_backtest(opens,closes,target,10,.02); m=performance_metrics(result.returns,result.costs,result.turnover); m.update(rolling_competition_metrics(result.returns)); m.update({"strategy":strategy.name,"gross_return":(1+result.gross_returns).prod()-1,"trades":len(result.trades),"median_trades_per_14d":len(result.trades)/max(len(result.returns)/336,1)}); rows.append(m); returns[strategy.name]=result.returns
        for bps in [5,10,15,20]:
            stressed=run_backtest(opens,closes,target,bps,.02)
            cost_rows.append({"strategy":strategy.name,"cost_bps_per_side":bps,"net_return":(1+stressed.returns).prod()-1,"gross_return":(1+stressed.gross_returns).prod()-1,"total_cost":stressed.costs.sum(),"turnover":stressed.turnover.sum()})
    table=pd.DataFrame(rows).set_index("strategy").sort_values("sharpe",ascending=False); (ROOT/"results/tables").mkdir(parents=True,exist_ok=True); table.to_csv(ROOT/"results/tables/strategy_zoo.csv"); pd.DataFrame(returns).to_csv(ROOT/"results/tables/strategy_returns.csv")
    pd.DataFrame(cost_rows).to_csv(ROOT/"results/tables/cost_scenarios.csv",index=False)
    (ROOT/"results/diagnostics/data_quality.json").write_text(json.dumps(diagnostics,indent=2)); print(table.round(4).to_string())
if __name__ == "__main__": main()
