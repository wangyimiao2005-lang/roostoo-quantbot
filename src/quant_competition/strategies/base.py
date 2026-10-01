from abc import ABC, abstractmethod
import pandas as pd
class Strategy(ABC):
    name: str
    @abstractmethod
    def target_weights(self, prices: pd.DataFrame, **kwargs) -> pd.DataFrame: """Causal desired weights at each close."""
