"""Policies that translate a causal raw target into a tradable target position.

Policies never inspect prices or future targets: their only inputs are target values
known at a completed bar and the current position established previously.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class ExecutionPolicy:
    name: str = "ImmediateRebalance"
    absolute_buffer: float = 0.0
    relative_buffer: float = 0.0
    rebalance_every: int = 1
    smoothing_alpha: float = 1.0
    partial_lambda: float = 1.0
    minimum_holding_bars: int = 0

    def apply(self, raw_target: pd.DataFrame) -> pd.DataFrame:
        if self.rebalance_every < 1 or not 0 < self.smoothing_alpha <= 1 or not 0 < self.partial_lambda <= 1:
            raise ValueError("invalid execution-policy parameter")
        raw = raw_target.fillna(0.0).to_numpy(dtype=float); actual = np.zeros_like(raw); held = np.zeros(raw.shape[1], dtype=int)
        for t in range(len(raw)):
            current = actual[t - 1] if t else np.zeros(raw.shape[1])
            smoothed = self.smoothing_alpha * raw[t] + (1-self.smoothing_alpha) * current
            scheduled = (t % self.rebalance_every) == 0
            minimum_reference = .01
            hurdle = np.maximum(self.absolute_buffer, self.relative_buffer * np.maximum(np.abs(current), minimum_reference))
            allowed = (held >= self.minimum_holding_bars) | (np.abs(current) < 1e-12)
            change = np.abs(smoothed-current) >= hurdle
            trade = scheduled & allowed & change
            proposal = current + self.partial_lambda * (smoothed-current)
            actual[t] = np.where(trade, proposal, current)
            held = np.where(np.abs(actual[t]-current) > 1e-12, 0, held+1)
        return pd.DataFrame(actual, index=raw_target.index, columns=raw_target.columns)

def immediate_rebalance() -> ExecutionPolicy:
    return ExecutionPolicy()
