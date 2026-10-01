from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd
from .data.validation import validate_ohlcv


@dataclass(frozen=True)
class DataHealth:
    status: str
    latest_bar: str | None
    reason: str = ""


class LiveMarketDataProvider(ABC):
    @abstractmethod
    def get_recent_closed_bars(self, symbol: str, limit: int | None = None) -> pd.DataFrame: ...

    def validate(self, frame, now=None, finalization_delay_minutes=2):
        try:
            report = validate_ohlcv(frame, "1h")
        except Exception as exc:
            return DataHealth("HALT_NEW_RISK", None, str(exc))
        if report.issues:
            return DataHealth("HALT_NEW_RISK", str(frame.index[-1]), "; ".join(report.issues))
        if len(frame) < 48:
            return DataHealth("HALT_NEW_RISK", str(frame.index[-1]), "warmup")
        now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        if frame.index[-1] + pd.Timedelta(hours=1, minutes=finalization_delay_minutes) > now:
            return DataHealth("HALT_NEW_RISK", str(frame.index[-1]), "latest bar incomplete")
        if now - (frame.index[-1] + pd.Timedelta(hours=1)) > pd.Timedelta(hours=2):
            return DataHealth("HALT_NEW_RISK", str(frame.index[-1]), "stale")
        return DataHealth("OK", str(frame.index[-1]))


class CachedLiveProvider(LiveMarketDataProvider):
    """Historical streaming provider used for parity/integration tests."""

    def __init__(self, frames):
        self.frames = frames

    def get_recent_closed_bars(self, symbol, limit=None):
        frame = self.frames[symbol]
        return frame.copy() if limit is None else frame.iloc[-limit:].copy()
