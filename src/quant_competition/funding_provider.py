"""Causal Binance USDⓈ-M funding history for competition-time use.

The provider is intentionally release-gated so this module cannot become a path
for peeking at the sealed Sep22-Oct3 final holdout before 2026-10-04 UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

import pandas as pd
import requests

RELEASE = pd.Timestamp("2026-10-04T00:00:00Z")
FROZEN_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


class BinanceUSDMFundingProvider:
    """Fetch sparse funding settlements and expose a causal hourly state.

    Only observations with ``fundingTime <= cutoff`` are returned. Sparse
    settlement observations are forward-filled *after* their publication time;
    future settlements are never propagated backward.
    """

    base_url = "https://fapi.binance.com/fapi/v1/fundingRate"

    def __init__(self, cache_dir: str | Path = "data/funding_competition_live", session=None,
                 clock=None, sleep_fn=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep_fn = sleep_fn

    def _assert_released(self) -> None:
        now = _utc(self.clock())
        if now < RELEASE:
            raise RuntimeError(
                "FINAL HOLDOUT SEALED: funding network access is disabled until "
                "2026-10-04T00:00:00Z"
            )

    def _cache_path(self, symbol: str) -> Path:
        if symbol not in FROZEN_SYMBOLS:
            raise ValueError(f"symbol outside frozen competition universe: {symbol}")
        return self.cache_dir / f"{symbol}_funding_events.csv"

    def _load_cache(self, symbol: str) -> pd.DataFrame:
        path = self._cache_path(symbol)
        if not path.exists():
            return pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
        frame = pd.read_csv(path, parse_dates=["timestamp"])
        if frame.empty:
            return pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
        return frame.dropna(subset=["funding_rate"]).drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()

    def _write_cache(self, symbol: str, frame: pd.DataFrame) -> None:
        path = self._cache_path(symbol)
        out = frame.reset_index().rename(columns={frame.index.name or "index": "timestamp"})
        out.to_csv(path, index=False)

    def _fetch_events(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Fetch [start, end] funding events from the public USDⓈ-M endpoint."""
        self._assert_released()  # Must happen before any HTTP call.
        start, end = _utc(start), _utc(end)
        rows = []
        cursor = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        while cursor <= end_ms:
            response = self.session.get(
                self.base_url,
                params={"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
                timeout=30,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError("malformed Binance funding response")
            if not page:
                break
            for row in page:
                if "fundingTime" not in row or "fundingRate" not in row:
                    raise RuntimeError("malformed Binance funding row")
                rows.append({"timestamp": pd.to_datetime(int(row["fundingTime"]), unit="ms", utc=True),
                             "funding_rate": float(row["fundingRate"])})
            last = max(int(row["fundingTime"]) for row in page)
            if last < cursor:
                raise RuntimeError("Binance funding pagination did not advance")
            cursor = last + 1
            if len(page) < 1000:
                break
            self.sleep_fn(0.10)
        if not rows:
            return pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
        frame = pd.DataFrame(rows).drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
        return frame[(frame.index >= start) & (frame.index <= end)]

    def events(self, symbol: str, start, cutoff) -> pd.DataFrame:
        """Return cached+downloaded events inside [start, cutoff], never beyond cutoff."""
        start, cutoff = _utc(start), _utc(cutoff)
        if cutoff < start:
            raise ValueError("cutoff precedes start")
        if symbol not in FROZEN_SYMBOLS:
            raise ValueError(f"symbol outside frozen competition universe: {symbol}")
        self._assert_released()
        cached = self._load_cache(symbol)
        # A small overlap protects against a partially written prior request and
        # revised duplicate settlement rows while deduplication keeps idempotency.
        if cached.empty:
            fetch_start = start
        else:
            fetch_start = max(start, cached.index.max() - pd.Timedelta(hours=8))
        if cached.empty or cached.index.max() < cutoff:
            fetched = self._fetch_events(symbol, fetch_start, cutoff)
            if cached.empty:
                combined = fetched.copy()
            elif fetched.empty:
                combined = cached.copy()
            else:
                combined = pd.concat([cached, fetched]).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
            combined = combined.loc[combined.index <= cutoff]
            self._write_cache(symbol, combined)
        else:
            combined = cached.loc[cached.index <= cutoff]
        return combined.loc[(combined.index >= start) & (combined.index <= cutoff)]

    def __call__(self, symbols: list[str], cutoff) -> pd.DataFrame:
        """Return hourly causal funding state ending at ``cutoff``.

        Ten days are requested so a 72-hour mean has ample warmup even on a
        first live invocation.  Only the frozen five-asset universe is accepted.
        """
        cutoff = _utc(cutoff).floor("h")
        if list(symbols) != FROZEN_SYMBOLS and set(symbols) != set(FROZEN_SYMBOLS):
            raise ValueError("funding provider requires the frozen five-asset universe")
        self._assert_released()
        start = cutoff - pd.Timedelta(days=10)
        hourly = pd.date_range(start, cutoff, freq="h", tz="UTC")
        result = pd.DataFrame(index=hourly, columns=symbols, dtype=float)
        for symbol in symbols:
            events = self.events(symbol, start - pd.Timedelta(days=2), cutoff)
            if events.empty:
                raise RuntimeError(f"no funding history available for {symbol}")
            union = hourly.union(events.index)
            causal = events["funding_rate"].reindex(union).sort_index().ffill().reindex(hourly)
            if causal.tail(72).isna().any():
                raise RuntimeError(f"insufficient causal funding warmup for {symbol}")
            result[symbol] = causal
        return result
