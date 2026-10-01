import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics
def parameter_sensitivity(opens, closes, candidates: dict, cost_bps: float) -> pd.DataFrame:
    rows=[]
    for name, strategy in candidates.items():
        result=run_backtest(opens,closes,strategy.target_weights(closes),cost_bps)
        rows.append({"parameter":name,**performance_metrics(result.returns,result.costs,result.turnover),"trades":len(result.trades)})
    return pd.DataFrame(rows).set_index("parameter")
