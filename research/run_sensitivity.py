from common import ROOT, load_universe
from quant_competition.strategies import MultiHorizonTrend, DonchianBreakout, VWAPMeanReversion
from quant_competition.validation import parameter_sensitivity
def main():
    opens,closes,_,_=load_universe(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"],"2025-01-01","2026-01-01")
    candidates={**{f"trend_{f}_{s}":MultiHorizonTrend(f,s) for f,s in [(4,12),(6,18),(8,24),(12,36),(16,48)]},**{f"breakout_{n}":DonchianBreakout(n) for n in [12,24,36,48]},**{f"vwap_{k}":VWAPMeanReversion(k) for k in [1.,1.5,2.]}}
    result=parameter_sensitivity(opens,closes,candidates,10); result.to_csv(ROOT/"results/tables/sensitivity.csv"); print(result[["total_return","sharpe","max_drawdown","trades"]].round(4).to_string())
if __name__ == "__main__": main()
