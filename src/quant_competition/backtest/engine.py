from dataclasses import dataclass
import numpy as np
import pandas as pd
from .costs import transaction_costs
from quant_competition.portfolio.execution_policy import ExecutionPolicy
@dataclass
class BacktestResult:
    returns: pd.Series; gross_returns: pd.Series; costs: pd.Series; weights: pd.DataFrame; turnover: pd.Series; trades: pd.DataFrame
def run_backtest(opens: pd.DataFrame, closes: pd.DataFrame, targets: pd.DataFrame, cost_bps_per_side: float = 10, no_trade_buffer: float | None = None, execution_policy: ExecutionPolicy | None = None) -> BacktestResult:
    """Causal: close-t target is held next open-to-close; never filled within its signal candle."""
    common = opens.index.intersection(closes.index).intersection(targets.index); opens, closes, targets = opens.loc[common], closes.loc[common], targets.loc[common]
    if execution_policy is not None and no_trade_buffer is not None: raise ValueError("pass a policy or legacy no_trade_buffer, not both")
    policy = execution_policy or ExecutionPolicy(name=f"AbsoluteBuffer_{no_trade_buffer or 0:g}", absolute_buffer=no_trade_buffer or 0)
    # Apply at completed close, then shift one bar so no signal can receive a same-bar fill.
    weights = policy.apply(targets).shift(1).fillna(0.0)
    changes = weights.diff().fillna(weights); turnover = changes.abs().sum(axis=1); costs = transaction_costs(changes, cost_bps_per_side)
    intrabar = closes.div(opens).sub(1).replace([float("inf"), -float("inf")], 0).fillna(0); gross = (weights * intrabar).sum(axis=1); net = gross - costs
    changed = changes.stack(); trades = changed[changed.abs() > 1e-12].rename("weight_change").reset_index().rename(columns={"level_0":"timestamp", "level_1":"symbol"})
    return BacktestResult(net, gross, costs, weights, turnover, trades)
