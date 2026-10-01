"""Read-only Roostoo connectivity validation. Never places or cancels orders."""
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from quant_competition.broker import RoostooBroker


def main():
    base=os.getenv('ROOSTOO_BASE_URL','https://mock-api.roostoo.com')
    key=os.getenv('ROOSTOO_API_KEY')
    secret=os.getenv('ROOSTOO_SECRET_KEY')
    if not key or not secret:
        result={'status':'BLOCKED','reason':'current ROOSTOO_API_KEY / ROOSTOO_SECRET_KEY not provided'}
        print(json.dumps(result,indent=2));return result
    broker=RoostooBroker(base,key,secret)
    result={'status':'READY'}
    try:
        result['server_time']=broker.get_server_time()
        info=broker.get_exchange_info();result['exchange_running']=info.get('IsRunning');result['trade_pair_count']=len(info.get('TradePairs',{}))
        result['ticker_count']=len(broker.get_tickers())
        result['balances']=broker.get_balances()
        result['pending_orders']=len(broker.get_pending_orders())
        result['signed_positions']=broker.get_positions()
    except Exception as exc:
        result={'status':'NOT_READY','error':repr(exc)}
    print(json.dumps(result,indent=2,default=str));return result

if __name__=='__main__':main()
