"""Past-only selection of a strategy plus execution policy; test choices are frozen."""
import json
import pandas as pd
from common import ROOT, load_universe
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics
from quant_competition.portfolio import ExecutionPolicy, enforce_exposure_limits, risk_scale_targets
from quant_competition.strategies import MultiHorizonTrend, DonchianBreakout, CrossSectionalMomentum, VWAPMeanReversion

def main():
    opens,closes,volumes,_=load_universe(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"],"2025-01-01","2026-01-01")
    ss=[MultiHorizonTrend(12,36),DonchianBreakout(48),CrossSectionalMomentum(48),VWAPMeanReversion(2)]
    targets={s.name:enforce_exposure_limits(risk_scale_targets(s.target_weights(closes,volumes=volumes),closes.pct_change())) for s in ss}
    policies=[ExecutionPolicy("Phase1_Buffer2pct",absolute_buffer=.02),ExecutionPolicy("Buffer10pct",absolute_buffer=.1),ExecutionPolicy("Rebalance12h",rebalance_every=12),ExecutionPolicy("Rebalance24h",rebalance_every=24)]
    records=[]; returns=[]; train_bars,test_bars=30*24,7*24
    for start in range(0,len(closes)-train_bars-test_bars+1,test_bars):
        tr=slice(start,start+train_bars); te=slice(start+train_bars,start+train_bars+test_bars); scored=[]
        for name,target in targets.items():
            for p in policies:
                r=run_backtest(opens.iloc[tr],closes.iloc[tr],target.iloc[tr],10,execution_policy=p); m=performance_metrics(r.returns,r.costs,r.turnover)
                if pd.notna(m['sharpe']) and m['sharpe']>0 and len(r.trades)>=8: scored.append((m['sharpe'],name,p))
        if scored:
            _,name,p=max(scored,key=lambda x:x[0]); r=run_backtest(opens.iloc[te],closes.iloc[te],targets[name].iloc[te],10,execution_policy=p)
        else:
            name,p='Cash',ExecutionPolicy('Cash'); r=run_backtest(opens.iloc[te],closes.iloc[te],targets[next(iter(targets))].iloc[te]*0,10,execution_policy=p)
        returns.append(r.returns); records.append({'train_start':str(closes.index[start]),'train_end':str(closes.index[start+train_bars-1]),'test_start':str(closes.index[start+train_bars]),'test_end':str(closes.index[start+train_bars+test_bars-1]),'strategy':name,'execution_policy':p.name,**performance_metrics(r.returns,r.costs,r.turnover),'trades':len(r.trades)})
    out=pd.DataFrame(records); out.to_csv(ROOT/'results/tables/execution_walk_forward_windows.csv',index=False); pd.concat(returns).rename('returns').to_csv(ROOT/'results/tables/execution_walk_forward_returns.csv'); (ROOT/'results/diagnostics/execution_walk_forward.json').write_text(json.dumps(records,indent=2,default=float)); print(out.groupby(['strategy','execution_policy']).size().to_string())
if __name__ == '__main__': main()
