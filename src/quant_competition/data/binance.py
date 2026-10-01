"""Public Binance spot klines provider. Returned bars are closed only."""
from pathlib import Path
import time
import pandas as pd
import requests
from .base import MarketDataProvider

class BinanceHistoricalProvider(MarketDataProvider):
    base_url = "https://api.binance.com/api/v3"
    def __init__(self, cache_dir: str | Path = "data/cache", session: requests.Session | None = None):
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True); self.session = session or requests.Session()
    def get_symbols(self) -> list[str]:
        response = self.session.get(f"{self.base_url}/exchangeInfo", timeout=30); response.raise_for_status()
        return [x["symbol"] for x in response.json()["symbols"] if x["status"] == "TRADING" and x["quoteAsset"] == "USDT"]
    def get_ohlcv(self, symbol: str, interval: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        params = {"symbol": symbol, "interval": interval, "limit": 1000}
        if start: params["startTime"] = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        if end: params["endTime"] = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
        rows = []
        while True:
            response = self.session.get(f"{self.base_url}/klines", params=params, timeout=30); response.raise_for_status(); page = response.json()
            if not page: break
            rows.extend(page)
            if len(page) < 1000 or not end: break
            params["startTime"] = page[-1][6] + 1
            if params["startTime"] >= params["endTime"]: break
            time.sleep(.15)
        columns = ["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
        frame = pd.DataFrame(rows, columns=columns)
        if frame.empty: return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True); frame = frame.set_index("timestamp")
        for col in ["open", "high", "low", "close", "volume"]: frame[col] = pd.to_numeric(frame[col])
        return frame[["open", "high", "low", "close", "volume"]].iloc[:-1].copy()
