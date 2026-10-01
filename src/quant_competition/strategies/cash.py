import pandas as pd
from .base import Strategy
class Cash(Strategy):
    name = "Cash"
    def target_weights(self, prices: pd.DataFrame, **kwargs): return pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
