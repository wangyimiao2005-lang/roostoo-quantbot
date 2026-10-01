"""Single symbol-namespace boundary for research, portfolio, and broker adapters."""
RESEARCH_TO_ASSET={'BTCUSDT':'BTC','ETHUSDT':'ETH','SOLUSDT':'SOL','BNBUSDT':'BNB','XRPUSDT':'XRP'}
def asset_from_research(symbol): return RESEARCH_TO_ASSET[symbol]
def broker_from_asset(asset): return f'{asset}/USD'
def asset_from_broker(symbol): return symbol.split('/')[0]
def research_from_asset(asset): return next(k for k,v in RESEARCH_TO_ASSET.items() if v==asset)
