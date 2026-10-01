import pandas as pd
from .base import Strategy
class MultiHorizonTrend(Strategy):
    def __init__(self, fast: int = 8, slow: int = 24):
        if fast >= slow: raise ValueError("fast must be below slow")
        self.fast, self.slow = fast, slow; self.name = f"Trend_{fast}_{slow}"
    def target_weights(self, prices: pd.DataFrame, **kwargs):
        signal = (prices.ewm(span=self.fast, adjust=False).mean() - prices.ewm(span=self.slow, adjust=False).mean()) / prices.rolling(self.slow).std()
        return signal.clip(-2, 2).div(2).fillna(0.0)
