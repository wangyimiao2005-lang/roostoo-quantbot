"""Ten-rebalance Phase 2.4 LOCAL_PAPER acceptance run with populated journals."""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from quant_competition.broker import PaperBroker
from quant_competition.live import RuntimeState
from quant_competition.live_data import CachedLiveProvider
from quant_competition.paper_runner import PaperRunner
from quant_competition.strategies import MultiHorizonTrend

SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']

def load_frames():
    frames={}
    for s in SYMS:
        f=pd.read_csv(ROOT/f'data/raw/{s}_1h_2026-01-01_2026-09-01.csv',index_col='timestamp',parse_dates=True)
        f.index=pd.to_datetime(f.index,utc=True);frames[s]=f
    return frames

def main():
    out=ROOT/'results/paper';out.mkdir(parents=True,exist_ok=True)
    state_path=out/'acceptance_state.sqlite'
    if state_path.exists():state_path.unlink()
    frames=load_frames();broker=PaperBroker(100000,10);state=RuntimeState(state_path)
    signals=[];targets=[];orders=[];fills=[];positions=[];equity_rows=[];recs=[];errors=[]
    previous_positions={}; start_equity=100000.; action_counts={}; crossings=0; scheduled=completed=0
    min_cash=float('inf');max_locked=max_gross=max_asset=0.; exceptions=0
    for i in [48+24*k for k in range(10)]:
        scheduled+=1;signal_ts=frames['BTCUSDT'].index[i];exec_ts=frames['BTCUSDT'].index[i+1]
        provider=CachedLiveProvider({s:f.iloc[:i+1] for s,f in frames.items()})
        recent_prices={s:float(frames[s].iloc[i+1].open) for s in SYMS};broker_prices={s.replace('USDT','/USD'):p for s,p in recent_prices.items()};broker.set_tickers(broker_prices)
        closes=pd.DataFrame({s:f.close.iloc[:i+1] for s,f in frames.items()})
        raw=MultiHorizonTrend(8,24).target_weights(closes).iloc[-1]
        try:
            result=PaperRunner(provider,broker,state,'LOCAL_PAPER').run(SYMS,recent_prices,exec_ts+pd.Timedelta(minutes=2))
        except Exception as exc:
            exceptions+=1;errors.append({'timestamp':exec_ts,'error':repr(exc)});continue
        if result.status=='RECONCILED':completed+=1
        else:errors.append({'timestamp':exec_ts,'error':result.reason,'status':result.status})
        rb=state.get_rebalance(result.rebalance_id) if result.rebalance_id else None;payload=rb['payload'] if rb else {}
        theo=payload.get('theoretical_targets',{});exe=payload.get('executable_targets',{})
        pos=broker.get_positions();snap=broker.account_snapshot(broker_prices)
        min_cash=min(min_cash,snap.free_cash);max_locked=max(max_locked,snap.locked_cash)
        gross=sum(abs(q*broker_prices[s]) for s,q in pos.items())/snap.total_equity if snap.total_equity else 0
        asset=max([abs(q*broker_prices[s])/snap.total_equity for s,q in pos.items()] or [0]);max_gross=max(max_gross,gross);max_asset=max(max_asset,asset)
        for research_symbol in SYMS:
            asset_name=research_symbol.replace('USDT','');broker_symbol=f'{asset_name}/USD';actual_q=pos.get(broker_symbol,0.);actual_w=actual_q*broker_prices[broker_symbol]/snap.total_equity if snap.total_equity else 0
            signals.append({'timestamp':signal_ts,'strategy_version':'trend824_v1_frozen','asset':asset_name,'signal':float(raw[research_symbol])})
            targets.append({'signal_timestamp':signal_ts,'execution_timestamp':exec_ts,'strategy_version':'trend824_v1_frozen','asset':asset_name,'research_symbol':research_symbol,'broker_symbol':broker_symbol,'theoretical_target':theo.get(asset_name,0),'executable_target':exe.get(asset_name,0),'actual_weight':actual_w,'tracking_error':actual_w-exe.get(asset_name,0)})
            positions.append({'timestamp':exec_ts,'asset':asset_name,'quantity':actual_q,'actual_weight':actual_w})
            old=previous_positions.get(broker_symbol,0.)
            if old*actual_q<0:crossings+=1
        previous_positions=dict(pos)
        for o in result.orders:
            response=o.get('response',{});action=o.get('action');action_counts[action]=action_counts.get(action,0)+1
            orders.append({'timestamp':exec_ts,'rebalance_id':result.rebalance_id,'asset':o.get('asset'),'action':action,'quantity':o.get('quantity'),'order_id':response.get('OrderID'),'success':response.get('Success'),'status':response.get('Status'),'error':response.get('ErrMsg','')})
            if response.get('Success'):
                fills.append({'timestamp':exec_ts,'rebalance_id':result.rebalance_id,'order_id':response.get('OrderID'),'asset':o.get('asset'),'action':action,'filled_quantity':response.get('FilledQuantity',0),'fill_price':response.get('FilledAverPrice',0),'fee':response.get('Fee',0)})
        equity_rows.append({'timestamp':exec_ts,'free_cash':snap.free_cash,'locked_cash':snap.locked_cash,'long_market_value':sum(q*broker_prices[s] for s,q in snap.long_positions.items()),'short_collateral':snap.short_collateral,'short_unrealized_pnl':snap.short_unrealized_pnl,'total_equity':snap.total_equity,'gross_exposure':gross,'net_exposure':sum(q*broker_prices[s] for s,q in pos.items())/snap.total_equity if snap.total_equity else 0})
        recs.append({'timestamp':exec_ts,'rebalance_id':result.rebalance_id,'status':result.status,'tracking_error':payload.get('tracking_error',0),'gross_exposure':payload.get('gross_exposure',gross),'reason':result.reason})
    pd.DataFrame(signals).to_csv(out/'signals.csv',index=False);pd.DataFrame(targets).to_csv(out/'targets.csv',index=False);pd.DataFrame(orders).to_csv(out/'orders.csv',index=False);pd.DataFrame(fills).to_csv(out/'fills.csv',index=False);pd.DataFrame(positions).to_csv(out/'positions.csv',index=False);pd.DataFrame(equity_rows).to_csv(out/'equity.csv',index=False);pd.DataFrame(recs).to_csv(out/'reconciliation.csv',index=False);pd.DataFrame(errors,columns=['timestamp','error','status']).to_csv(out/'errors.csv',index=False)
    fees=sum(float(x.get('Fee',0) or 0) for x in broker.orders.values());end_equity=equity_rows[-1]['total_equity'] if equity_rows else start_equity
    report={'scheduled_rebalances':scheduled,'completed_rebalances':completed,'start_equity':start_equity,'end_equity':end_equity,'minimum_free_cash':min_cash,'maximum_locked_short_collateral':max_locked,'maximum_gross_exposure':max_gross,'maximum_asset_exposure':max_asset,'action_counts':action_counts,'direction_crossings':crossings,'total_fees':fees,'reconciliation_failures':scheduled-completed,'uncaught_exceptions':exceptions,'order_count':len(broker.orders)}
    (out/'local_paper_acceptance.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return report

if __name__=='__main__':main()
