from abc import ABC, abstractmethod
import pandas as pd

class MarketDataProvider(ABC):
    @abstractmethod
    def get_ohlcv(self, symbol: str, interval: str, start: str | None = None, end: str | None = None) -> pd.DataFrame: ...
    @abstractmethod
    def get_symbols(self) -> list[str]: ...
    def validate(self, frame: pd.DataFrame, interval: str):
        from .validation import validate_ohlcv
        return validate_ohlcv(frame, interval)
