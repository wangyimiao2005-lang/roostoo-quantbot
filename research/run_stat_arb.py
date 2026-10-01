"""Walk-forward, past-only pair discovery; deliberately rejects slow relationships."""
import itertools
import pandas as pd
from common import ROOT, load_universe
from quant_competition.strategies.stat_arb import discover_pairs, pair_targets
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics

def main():
    opens,closes,_,_=load_universe(['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'],'2025-01-01','2026-01-01'); train,test=60*24,7*24; rows=[]; returns=[]
    for start in range(0,len(closes)-train-test+1,test):
        training=closes.iloc[start:start+train]; models=discover_pairs(training,.05,24)
        for model in models:
            # Fit is frozen from training; only test prices create causal z-score and next-bar trades.
            sl=slice(start+train,start+train+test); test_prices=closes.iloc[sl][[model.left,model.right]]; test_opens=opens.iloc[sl][[model.left,model.right]]
            for entry in [1.5,2.0,2.5]:
                target=pair_targets(test_prices,model,48,entry,.25); result=run_backtest(test_opens,test_prices,target,10)
                m=performance_metrics(result.returns,result.costs,result.turnover); rows.append({'training_window':f'{training.index[0]}:{training.index[-1]}','test_window':f'{test_prices.index[0]}:{test_prices.index[-1]}','pair':f'{model.left}/{model.right}','adf_pvalue':model.adf_pvalue,'half_life_hours':model.half_life_hours,'hedge_ratio':model.beta,'entry_z':entry,'exit_z':.25,'number_trades':len(result.trades),'gross_return':(1+result.gross_returns).prod()-1,'net_return':(1+result.returns).prod()-1,'turnover':m['turnover'],'cost':m['total_cost'],'sharpe':m['sharpe'],'max_drawdown':m['max_drawdown'],'status':'EXPERIMENTAL'}); returns.append(result.returns)
    columns=['training_window','test_window','pair','adf_pvalue','half_life_hours','hedge_ratio','entry_z','exit_z','number_trades','gross_return','net_return','turnover','cost','sharpe','max_drawdown','status']
    pd.DataFrame(rows,columns=columns).to_csv(ROOT/'results/tables/stat_arb_results.csv',index=False)
    if returns: pd.concat(returns).rename('returns').to_csv(ROOT/'results/tables/stat_arb_returns.csv')
    print(f'fast pair/window/threshold experiments: {len(rows)}; qualifying pair windows: {len(rows)//3}')
if __name__=='__main__': main()
