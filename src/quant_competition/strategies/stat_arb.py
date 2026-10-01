"""Small, transparent point-in-time Engle--Granger stat-arb utilities."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import linregress
from statsmodels.tsa.stattools import adfuller

@dataclass(frozen=True)
class PairModel:
    left: str; right: str; beta: float; adf_pvalue: float; half_life_hours: float
def fit_pair(prices: pd.DataFrame, left: str, right: str) -> PairModel | None:
    y=np.log(prices[left].dropna()); x=np.log(prices[right].reindex(y.index).dropna()); y=y.reindex(x.index)
    if len(x)<80: return None
    beta=linregress(x,y).slope; spread=y-beta*x
    try: p=adfuller(spread,autolag="AIC",result_object=False)[1]
    except ValueError: return None
    lag=spread.shift(1).dropna(); delta=spread.diff().dropna().reindex(lag.index); phi=linregress(lag,delta).slope
    half_life=float(-np.log(2)/phi) if phi < 0 else np.inf
    return PairModel(left,right,float(beta),float(p),half_life)
def discover_pairs(prices: pd.DataFrame, pvalue_max: float=.05, half_life_max: float=24) -> list[PairModel]:
    cols=list(prices.columns); models=[]
    for i,left in enumerate(cols):
        for right in cols[i+1:]:
            model=fit_pair(prices,left,right)
            if model and model.adf_pvalue<=pvalue_max and model.half_life_hours<half_life_max: models.append(model)
    return models
def pair_targets(prices: pd.DataFrame, model: PairModel, lookback: int=48, entry: float=2., exit: float=.25) -> pd.DataFrame:
    spread=np.log(prices[model.left])-model.beta*np.log(prices[model.right]); z=(spread-spread.rolling(lookback).mean())/spread.rolling(lookback).std(); state=0.; out=[]
    for value in z.fillna(0):
        if state==0 and value>=entry: state=-1.
        elif state==0 and value<=-entry: state=1.
        elif state and abs(value)<=exit: state=0.
        out.append(state)
    # gross=1 dollar neutral; beta converts opposing-leg exposure.
    left=pd.Series(out,index=prices.index)*.5; right=-left*model.beta
    gross=(left.abs()+right.abs()).clip(lower=1); return pd.DataFrame({model.left:left/gross,model.right:right/gross},index=prices.index)
