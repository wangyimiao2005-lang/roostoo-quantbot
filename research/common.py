"""Research IO. Uses an existing CSV cache or downloads explicit public Binance data."""
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from quant_competition.data import BinanceHistoricalProvider, validate_ohlcv
def load_universe(symbols: list[str], start: str, end: str, interval: str="1h"):
    frames={}; diagnostics={}; provider=BinanceHistoricalProvider(ROOT/"data/cache")
    for symbol in symbols:
        file=ROOT/"data/raw"/f"{symbol}_{interval}_{start}_{end}.csv"
        if file.exists():
            f=pd.read_csv(file,index_col="timestamp",parse_dates=True); f.index=pd.to_datetime(f.index,utc=True)
        else:
            f=provider.get_ohlcv(symbol,interval,start,end); f.to_csv(file,index_label="timestamp")
        diagnostics[symbol]=validate_ohlcv(f,interval).to_dict(); frames[symbol]=f
    idx=None
    for f in frames.values(): idx=f.index if idx is None else idx.intersection(f.index)
    opens=pd.DataFrame({s:f.loc[idx,"open"] for s,f in frames.items()}); closes=pd.DataFrame({s:f.loc[idx,"close"] for s,f in frames.items()}); volumes=pd.DataFrame({s:f.loc[idx,"volume"] for s,f in frames.items()})
    return opens,closes,volumes,diagnostics
