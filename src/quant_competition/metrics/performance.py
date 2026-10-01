import numpy as np
import pandas as pd
from .drawdown import drawdown
def performance_metrics(returns: pd.Series, costs: pd.Series | None = None, turnover: pd.Series | None = None, bars_per_year: int = 8760) -> dict[str, float]:
    r = returns.dropna(); ann_return = (1+r).prod() ** (bars_per_year / max(len(r), 1)) - 1; ann_vol = r.std(ddof=0) * np.sqrt(bars_per_year); downside = r.clip(upper=0).std(ddof=0) * np.sqrt(bars_per_year)
    dd = drawdown(r); mdd = -dd.min(); wins = r[r > 0].sum(); losses = -r[r < 0].sum()
    return {"total_return":(1+r).prod()-1,"annualized_return":ann_return,"annualized_volatility":ann_vol,"sharpe":ann_return/ann_vol if ann_vol else np.nan,"sortino":ann_return/downside if downside else np.nan,"calmar":ann_return/mdd if mdd else np.nan,"max_drawdown":mdd,"win_rate":float((r>0).mean()),"profit_factor":wins/losses if losses else np.nan,"total_cost":float(costs.sum()) if costs is not None else 0.,"turnover":float(turnover.sum()) if turnover is not None else 0.}
def rolling_competition_metrics(returns: pd.Series, bars_per_day: int = 24, days: int = 14) -> dict[str, float]:
    count = ((1+returns).rolling(bars_per_day*days).apply(np.prod, raw=True)-1).dropna()
    return {"median_14d_return":float(count.median()) if len(count) else np.nan,"positive_14d_probability":float((count>0).mean()) if len(count) else np.nan,"worst_14d_return":float(count.min()) if len(count) else np.nan,"best_14d_return":float(count.max()) if len(count) else np.nan}
