import pandas as pd
def drawdown(returns: pd.Series) -> pd.Series:
    equity = (1 + returns.fillna(0)).cumprod(); return equity / equity.cummax() - 1
