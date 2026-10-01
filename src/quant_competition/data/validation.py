from dataclasses import dataclass, asdict
import pandas as pd

_FREQ = {"15m": "15min", "1h": "1h", "4h": "4h"}
@dataclass(frozen=True)
class DataQualityReport:
    rows: int; duplicates: int; missing_candles: int; invalid_ohlc: int; nonpositive_prices: int; stale_sequences: int; abnormal_gaps: int; issues: tuple[str, ...]
    def to_dict(self): return asdict(self)
def validate_ohlcv(frame: pd.DataFrame, interval: str) -> DataQualityReport:
    needed = {"open", "high", "low", "close", "volume"}; missing = needed - set(frame.columns)
    if missing: raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    idx = pd.DatetimeIndex(frame.index); duplicate = int(idx.duplicated().sum()); expected = pd.Timedelta(_FREQ[interval])
    missing_candles = int((idx.to_series().diff().dropna() / expected - 1).clip(lower=0).sum())
    invalid = int(((frame.high < frame[["open", "close", "low"]].max(axis=1)) | (frame.low > frame[["open", "close", "high"]].min(axis=1))).sum())
    nonpositive = int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()); stale = int(((frame.close == frame.close.shift()) & (frame.volume == 0)).sum()); abnormal = int((frame.close.pct_change().abs() > .30).sum())
    issues = tuple(x for x,n in [("duplicate timestamps",duplicate),("missing candles",missing_candles),("invalid OHLC",invalid),("nonpositive prices",nonpositive),("stale candles",stale),("abnormal gaps",abnormal)] if n)
    return DataQualityReport(len(frame), duplicate, missing_candles, invalid, nonpositive, stale, abnormal, issues)
