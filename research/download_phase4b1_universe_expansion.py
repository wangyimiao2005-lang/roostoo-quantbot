"""Download and validate missing Phase 4B.1 raw Binance Futures datasets.

This is deliberately a data-preparation utility.  It does not import, select, or
alter any Phase 4B.1 research rule.  Requests are explicitly capped at the last
hour of 2026-08-31 UTC.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "derivatives_raw" / "binance_futures_phase4b"
OUT = ROOT / "results" / "derivatives_phase4b1"
SYMBOLS = ("ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "UNIUSDT", "NEARUSDT")
KINDS = ("mark", "index", "taker")
START = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
END = pd.Timestamp("2026-09-01 00:00:00", tz="UTC")
EXPECTED_INDEX = pd.date_range(START, END - pd.Timedelta(hours=1), freq="h", tz="UTC")
BASE_URL = "https://fapi.binance.com"
ENDPOINTS = {
    "mark": "/fapi/v1/markPriceKlines",
    "index": "/fapi/v1/indexPriceKlines",
    "taker": "/fapi/v1/klines",
}


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def _path(symbol: str, kind: str) -> Path:
    return RAW / symbol / f"{kind}_1h_2025-01-01_2026-08-31.csv"


def fetch(symbol: str, kind: str, request_log: list[dict]) -> pd.DataFrame:
    """Fetch only completed requested hourly bars from Binance's public API."""
    rows: list[list] = []
    cursor = _ms(START)
    end_ms = _ms(END) - 1
    while cursor <= end_ms:
        query = {"interval": "1h", "startTime": cursor, "endTime": end_ms, "limit": 1500}
        query["pair" if kind == "index" else "symbol"] = symbol
        url = BASE_URL + ENDPOINTS[kind] + "?" + urllib.parse.urlencode(query)
        with urllib.request.urlopen(url, timeout=45) as response:
            page = json.load(response)
        request_log.append({
            "provider": "Binance USD-M Futures public API",
            "endpoint": ENDPOINTS[kind],
            "symbol": symbol,
            "dataset": kind,
            "requested_start": pd.to_datetime(cursor, unit="ms", utc=True).isoformat(),
            "requested_end": pd.to_datetime(end_ms, unit="ms", utc=True).isoformat(),
            "returned_rows": len(page),
        })
        if not page:
            break
        rows.extend(page)
        cursor = int(page[-1][6]) + 1
        time.sleep(0.05)

    raw = pd.DataFrame(rows)
    if raw.empty:
        raise RuntimeError(f"Binance returned no {kind} data for {symbol}")
    raw["timestamp"] = pd.to_datetime(raw[0], unit="ms", utc=True)
    if kind == "taker":
        out = raw.assign(quote=pd.to_numeric(raw[7]), buy_quote=pd.to_numeric(raw[10]))[
            ["timestamp", "quote", "buy_quote"]
        ]
    else:
        out = raw.assign(close=pd.to_numeric(raw[4]))[["timestamp", "close"]]
    out = out[(out.timestamp >= START) & (out.timestamp < END)]
    return out.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def validate(symbol: str, kind: str, frame: pd.DataFrame) -> dict:
    ts = pd.DatetimeIndex(frame.timestamp)
    duplicates = int(ts.duplicated().sum())
    observed = pd.DatetimeIndex(ts.drop_duplicates().sort_values())
    gaps = observed.to_series().diff().dropna().dt.total_seconds().div(3600)
    missing = EXPECTED_INDEX.difference(observed)
    periods: list[str] = []
    if len(missing):
        run_start = missing[0]
        previous = missing[0]
        for current in missing[1:]:
            if current - previous != pd.Timedelta(hours=1):
                periods.append(f"{run_start.isoformat()}..{previous.isoformat()}")
                run_start = current
            previous = current
        periods.append(f"{run_start.isoformat()}..{previous.isoformat()}")
    return {
        "asset": symbol,
        "dataset": kind,
        "first_timestamp": observed.min().isoformat() if len(observed) else None,
        "last_timestamp": observed.max().isoformat() if len(observed) else None,
        "expected_hourly_bars": len(EXPECTED_INDEX),
        "actual_hourly_bars": len(observed),
        "coverage_pct": len(observed) / len(EXPECTED_INDEX) * 100,
        "duplicate_timestamps": duplicates,
        "maximum_gap_hours": float(gaps.max()) if len(gaps) else 0.0,
        "structural_missing_periods": "; ".join(periods) if periods else "",
        "usable_95pct": len(observed) / len(EXPECTED_INDEX) >= 0.95,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    request_log: list[dict] = []
    audits: list[dict] = []
    for symbol in SYMBOLS:
        for kind in KINDS:
            path = _path(symbol, kind)
            frame = fetch(symbol, kind, request_log)
            audit = validate(symbol, kind, frame)
            audits.append(audit)
            if not audit["usable_95pct"]:
                raise RuntimeError(f"Unsafe history for {symbol} {kind}: {audit}")
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            print(f"{symbol} {kind}: {audit['actual_hourly_bars']}/{audit['expected_hourly_bars']} ({audit['coverage_pct']:.2f}%)")
    pd.DataFrame(audits).to_csv(OUT / "PHASE4B1_UNIVERSE_EXPANSION_DATA_VALIDATION.csv", index=False)
    pd.DataFrame(request_log).to_csv(OUT / "PHASE4B1_UNIVERSE_EXPANSION_REQUEST_LOG.csv", index=False)


if __name__ == "__main__":
    main()
