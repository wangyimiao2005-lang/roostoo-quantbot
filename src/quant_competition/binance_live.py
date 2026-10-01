"""Competition-time Binance OHLCV provider.

The official hackathon FAQ states that Roostoo pricing is streamed from Binance and
allows external market-data APIs.  This provider keeps a persistent hourly cache,
merges the repository's historical bootstrap files, and fetches only the missing
public Binance spot klines.  Only fully closed bars are returned.
"""
from __future__ import annotations

from pathlib import Path
import time

import pandas as pd
import requests

from .live_data import LiveMarketDataProvider


_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


class BinanceCompetitionLiveProvider(LiveMarketDataProvider):
    base_url = "https://api.binance.com/api/v3/klines"

    def __init__(
        self,
        bootstrap_dir: str | Path = "data/raw",
        cache_dir: str | Path = "data/binance_competition_live",
        session=None,
        sleep_fn=time.sleep,
    ):
        self.bootstrap_dir = Path(bootstrap_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn
        self.as_of = None
        self._bootstrap_cache: dict[str, pd.DataFrame] = {}

    def set_as_of(self, now):
        ts = pd.Timestamp(now)
        self.as_of = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        out = frame.copy()
        out.index = pd.to_datetime(out.index, utc=True)
        cols = ["open", "high", "low", "close", "volume"]
        out = out[cols]
        for c in cols:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        return out.dropna().sort_index()

    def _load_bootstrap(self, symbol: str) -> pd.DataFrame:
        if symbol in self._bootstrap_cache:
            return self._bootstrap_cache[symbol].copy()
        pieces = []
        for path in sorted(self.bootstrap_dir.glob(f"{symbol}_1h_*.csv")):
            try:
                frame = pd.read_csv(path, index_col="timestamp", parse_dates=True)
                pieces.append(self._normalize(frame))
            except Exception:
                continue
        if not pieces:
            result = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        else:
            result = pd.concat(pieces).sort_index()
            result = result[~result.index.duplicated(keep="last")]
        self._bootstrap_cache[symbol] = result
        return result.copy()

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}_1h.csv"

    def _load_live_cache(self, symbol: str) -> pd.DataFrame:
        path = self._cache_path(symbol)
        if not path.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return self._normalize(pd.read_csv(path, index_col="timestamp", parse_dates=True))

    def _write_live_cache(self, symbol: str, frame: pd.DataFrame) -> None:
        frame.to_csv(self._cache_path(symbol), index_label="timestamp")

    def _fetch(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        start = pd.Timestamp(start).tz_convert("UTC") if pd.Timestamp(start).tzinfo else pd.Timestamp(start).tz_localize("UTC")
        end = pd.Timestamp(end).tz_convert("UTC") if pd.Timestamp(end).tzinfo else pd.Timestamp(end).tz_localize("UTC")
        cursor = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        rows = []
        while cursor <= end_ms:
            response = self.session.get(
                self.base_url,
                params={"symbol": symbol, "interval": "1h", "startTime": cursor, "endTime": end_ms, "limit": 1000},
                timeout=30,
            )
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            rows.extend(page)
            last_close = int(page[-1][6])
            next_cursor = last_close + 1
            if next_cursor <= cursor:
                raise RuntimeError("Binance kline pagination did not advance")
            cursor = next_cursor
            if len(page) < 1000:
                break
            self.sleep_fn(0.15)
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        raw = pd.DataFrame(rows, columns=_COLUMNS)
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], unit="ms", utc=True)
        raw["close_time"] = pd.to_datetime(raw["close_time"], unit="ms", utc=True)
        # A bar is admissible only if its exchange close time is not in the future.
        raw = raw.loc[raw["close_time"] <= end]
        raw = raw.set_index("timestamp")
        return self._normalize(raw)

    def get_recent_closed_bars(self, symbol: str, limit: int | None = None) -> pd.DataFrame:
        now = self.as_of or pd.Timestamp.now(tz="UTC")
        bootstrap = self._load_bootstrap(symbol)
        live = self._load_live_cache(symbol)
        existing = pd.concat([bootstrap, live]).sort_index() if len(live) else bootstrap.copy()
        if len(existing):
            existing = existing[~existing.index.duplicated(keep="last")]
            # overlap by two hours to repair a partial prior fetch deterministically
            start = existing.index.max() - pd.Timedelta(hours=2)
        else:
            start = now - pd.Timedelta(days=90)
        fetched = self._fetch(symbol, start, now)
        if len(existing) and len(fetched):
            merged = pd.concat([existing, fetched]).sort_index()
        elif len(fetched):
            merged = fetched.copy()
        else:
            merged = existing.copy()
        merged = merged[~merged.index.duplicated(keep="last")]
        # At 01:xx UTC the 00:00 bar is closed; the current 01:00 bar is not.
        latest_closed_start = now.floor("h") - pd.Timedelta(hours=1)
        merged = merged.loc[merged.index <= latest_closed_start]
        if len(fetched):
            live_merged = pd.concat([live, fetched]).sort_index() if len(live) else fetched.copy()
            live_merged = live_merged[~live_merged.index.duplicated(keep="last")]
            self._write_live_cache(symbol, live_merged)
        return merged.copy() if limit is None else merged.iloc[-int(limit):].copy()
