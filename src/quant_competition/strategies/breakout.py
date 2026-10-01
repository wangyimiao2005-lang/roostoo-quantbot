import pandas as pd
from .base import Strategy
class DonchianBreakout(Strategy):
    def __init__(self, lookback: int = 24): self.lookback = lookback; self.name = f"Breakout_{lookback}"
    def target_weights(self, prices: pd.DataFrame, **kwargs):
        high = prices.rolling(self.lookback).max().shift(1); low = prices.rolling(self.lookback).min().shift(1)
        return pd.DataFrame(0.0, index=prices.index, columns=prices.columns).mask(prices > high, 1.0).mask(prices < low, -1.0).ffill().fillna(0.0)
