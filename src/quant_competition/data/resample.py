import pandas as pd
def resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate only completed source bars, with right-labelled completed intervals."""
    out=frame.resample(rule,label="right",closed="right").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    return out
