import pandas as pd
from .base import Strategy
class VWAPMeanReversion(Strategy):
    def __init__(self, band: float = 1.5, session_bars: int = 24): self.band, self.session_bars = band, session_bars; self.name = f"VWAPMR_{band:g}"
    def target_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame | None = None, **kwargs):
        vol = volumes if volumes is not None else pd.DataFrame(1.0, index=prices.index, columns=prices.columns)
        vwap = (prices * vol).rolling(self.session_bars).sum() / vol.rolling(self.session_bars).sum(); z = (prices - vwap) / prices.rolling(self.session_bars).std()
        return (-z / self.band).clip(-1, 1).where(z.abs() >= self.band, 0.0).fillna(0.0)
