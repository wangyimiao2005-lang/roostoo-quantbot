import pandas as pd
from .base import Strategy
class CrossSectionalMomentum(Strategy):
    def __init__(self, lookback: int = 24, leg_fraction: float = .3): self.lookback, self.leg_fraction = lookback, leg_fraction; self.name = f"CSMomentum_{lookback}"
    def target_weights(self, prices: pd.DataFrame, **kwargs):
        momentum = prices.pct_change(self.lookback); n = prices.shape[1]; leg_n = max(1, int(n * self.leg_fraction)); ranks = momentum.rank(axis=1, method="first")
        out = pd.DataFrame(0.0, index=prices.index, columns=prices.columns); out[ranks > n - leg_n] = 1 / leg_n; out[ranks <= leg_n] = -1 / leg_n
        return out.where(momentum.notna(), 0.0)
