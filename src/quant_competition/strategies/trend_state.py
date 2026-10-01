"""Persistent state-machine trend; state transitions use completed-bar signals only."""
from dataclasses import dataclass
import pandas as pd
from .base import Strategy

@dataclass
class StateTrend(Strategy):
    fast: int = 12
    slow: int = 36
    entry: float = .5
    exit: float = 0.0
    direct_reversal: bool = False
    name: str = "StateTrend"
    def __post_init__(self): self.name=f"StateTrend_{self.fast}_{self.slow}_e{self.entry:g}_x{self.exit:g}"
    def score(self, prices: pd.DataFrame) -> pd.DataFrame:
        return ((prices.ewm(span=self.fast,adjust=False).mean()-prices.ewm(span=self.slow,adjust=False).mean()) / prices.rolling(self.slow).std()).fillna(0)
    def target_weights(self, prices: pd.DataFrame, **kwargs) -> pd.DataFrame:
        score=self.score(prices); out=pd.DataFrame(0.,index=prices.index,columns=prices.columns)
        for col in prices:
            state=0.
            for i, value in enumerate(score[col]):
                if state == 0:
                    if value >= self.entry: state=1.
                    elif value <= -self.entry: state=-1.
                elif state == 1 and value <= self.exit:
                    state=-1. if self.direct_reversal and value <= -self.entry else 0.
                elif state == -1 and value >= -self.exit:
                    state=1. if self.direct_reversal and value >= self.entry else 0.
                out.iloc[i,out.columns.get_loc(col)]=state
        return out
