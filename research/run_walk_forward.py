from pathlib import Path
import json
import pandas as pd
from common import ROOT, load_universe
from quant_competition.strategies import MultiHorizonTrend, DonchianBreakout, CrossSectionalMomentum, VWAPMeanReversion
from quant_competition.validation import walk_forward
from quant_competition.metrics import performance_metrics, rolling_competition_metrics
def main():
    opens,closes,volumes,_=load_universe(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"],"2025-01-01","2026-01-01")
    strategies=[MultiHorizonTrend(4,12),MultiHorizonTrend(8,24),MultiHorizonTrend(12,36),DonchianBreakout(12),DonchianBreakout(24),CrossSectionalMomentum(6),CrossSectionalMomentum(24),VWAPMeanReversion(1.0),VWAPMeanReversion(1.5)]
    candidates={s.name:s.target_weights(closes,volumes=volumes) for s in strategies}; returns, windows=walk_forward(opens,closes,candidates,30*24,7*24,10,3)
    pd.DataFrame({"returns":returns}).to_csv(ROOT/"results/tables/walk_forward_returns.csv"); (ROOT/"results/diagnostics/walk_forward_windows.json").write_text(json.dumps([{"train_start":x.train_start,"train_end":x.train_end,"test_start":x.test_start,"test_end":x.test_end,"selected":x.selected,"metrics":x.metrics} for x in windows],indent=2,default=float))
    print({**performance_metrics(returns),**rolling_competition_metrics(returns)})
if __name__ == "__main__": main()
