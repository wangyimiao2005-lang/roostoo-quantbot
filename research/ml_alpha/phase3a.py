"""Causal feature, label, portfolio, and reporting helpers for Phase 3A."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "UNIUSDT", "NEARUSDT"]
FEATURE_COLUMNS = [
    "return_1h", "return_4h", "return_12h", "return_24h", "return_48h", "return_72h",
    "ema_gap_price", "ema_gap_vol", "trend_direction", "trend_age", "dist_24h_high", "dist_24h_low", "dist_72h_high", "dist_72h_low",
    "ma_24h_distance", "ma_72h_distance", "return_4h_minus_24h", "zscore_24h",
    "vol_12h", "vol_24h", "vol_48h", "vol_168h", "vol_ratio", "atr_range",
    "volume_change", "volume_24h_7d", "volume_zscore", "dollar_volume", "volume_cs_rank",
    "cs_rank_return_1h", "cs_rank_return_4h", "cs_rank_return_12h", "cs_rank_return_24h", "cs_rank_return_48h", "cs_rank_vol_24h", "cs_rank_volume_accel", "cs_rank_trend_strength",
    "return_minus_market", "return_minus_btc", "market_return_4h", "market_return_12h", "market_return_24h", "market_vol_24h", "market_dispersion", "btc_trend",
]

def _cs_rank(x: pd.DataFrame) -> pd.DataFrame:
    return x.rank(axis=1, pct=True).sub(.5).mul(2)

def build_features(opens: pd.DataFrame, highs: pd.DataFrame, lows: pd.DataFrame, closes: pd.DataFrame, volumes: pd.DataFrame) -> pd.DataFrame:
    """Return a timestamp/symbol panel whose every feature ends at timestamp t."""
    r = closes.pct_change(fill_method=None)
    market = r.mean(axis=1)
    vol24 = r.rolling(24, min_periods=24).std()
    ema8, ema24 = closes.ewm(span=8, adjust=False).mean(), closes.ewm(span=24, adjust=False).mean()
    gap = ema8.sub(ema24)
    direction = np.sign(gap).replace(0, np.nan).ffill().fillna(0)
    age = direction.copy()
    for s in age:
        groups = direction[s].ne(direction[s].shift()).cumsum()
        age[s] = direction[s].groupby(groups).cumcount() + 1
    f = {}
    for h in (1,4,12,24,48,72): f[f"return_{h}h"] = closes.pct_change(h, fill_method=None)
    f.update({"ema_gap_price": gap / closes, "ema_gap_vol": gap / (closes * vol24), "trend_direction": direction, "trend_age": age,
        "dist_24h_high": closes / closes.rolling(24).max() - 1, "dist_24h_low": closes / closes.rolling(24).min() - 1,
        "dist_72h_high": closes / closes.rolling(72).max() - 1, "dist_72h_low": closes / closes.rolling(72).min() - 1,
        "ma_24h_distance": closes / closes.rolling(24).mean() - 1, "ma_72h_distance": closes / closes.rolling(72).mean() - 1,
        "return_4h_minus_24h": f["return_4h"] - f["return_24h"], "zscore_24h": (closes-closes.rolling(24).mean()) / closes.rolling(24).std(),
        "vol_12h": r.rolling(12).std(), "vol_24h": vol24, "vol_48h": r.rolling(48).std(), "vol_168h": r.rolling(168).std(),
        "vol_ratio": r.rolling(12).std() / r.rolling(168).std(), "atr_range": (highs-lows).rolling(24).mean() / closes,
        "volume_change": volumes.pct_change(fill_method=None), "volume_24h_7d": volumes.rolling(24).mean()/volumes.rolling(168).mean(),
        "volume_zscore": (volumes-volumes.rolling(168).mean())/volumes.rolling(168).std(), "dollar_volume": closes*volumes,
        "volume_cs_rank": _cs_rank(volumes), "return_minus_market": f["return_24h"].sub(market.rolling(24).sum(), axis=0), "return_minus_btc": f["return_24h"].sub(f["return_24h"]["BTCUSDT"], axis=0),
        "market_return_4h": pd.DataFrame({s: market.rolling(4).sum() for s in closes}), "market_return_12h": pd.DataFrame({s: market.rolling(12).sum() for s in closes}),
        "market_return_24h": pd.DataFrame({s: market.rolling(24).sum() for s in closes}), "market_vol_24h": pd.DataFrame({s: market.rolling(24).std() for s in closes}),
        "market_dispersion": pd.DataFrame({s: r.std(axis=1) for s in closes}), "btc_trend": pd.DataFrame({s: direction["BTCUSDT"] for s in closes})})
    for name, value in [("cs_rank_return_1h",f["return_1h"]),("cs_rank_return_4h",f["return_4h"]),("cs_rank_return_12h",f["return_12h"]),("cs_rank_return_24h",f["return_24h"]),("cs_rank_return_48h",f["return_48h"]),("cs_rank_vol_24h",vol24),("cs_rank_volume_accel",f["volume_change"]),("cs_rank_trend_strength",gap.abs()/closes)]: f[name]=_cs_rank(value)
    out = pd.concat({k: v.stack(future_stack=True) for k,v in f.items()}, axis=1)
    out.index.names = ["timestamp", "symbol"]
    return out.reindex(columns=FEATURE_COLUMNS).replace([np.inf,-np.inf], np.nan)

def build_labels(opens: pd.DataFrame, closes: pd.DataFrame, horizon: int = 24) -> pd.DataFrame:
    """At signal t, entry is open(t+1), exit is close(t+horizon); future-only labels."""
    future = closes.shift(-horizon).div(opens.shift(-1)).sub(1)
    excess = future.sub(future.median(axis=1), axis=0)
    out = pd.concat({"future_return": future.stack(future_stack=True), "future_excess": excess.stack(future_stack=True)}, axis=1)
    out.index.names = ["timestamp", "symbol"]
    return out

class RidgeRegressor:
    def __init__(self, alpha: float = 10.0): self.alpha=alpha
    def fit(self, x, y):
        self.mean_=x.mean(0); self.scale_=x.std(0).replace(0,1); z=((x-self.mean_)/self.scale_).to_numpy(); self.coef_=np.linalg.solve(z.T@z+self.alpha*np.eye(z.shape[1]), z.T@y.to_numpy()); self.intercept_=float(y.mean()); return self
    def predict(self,x): return ((x-self.mean_)/self.scale_).to_numpy()@self.coef_+self.intercept_

@dataclass
class FrozenPreprocessor:
    """Development-fitted median/winsorisation transform; immutable by convention."""
    medians: pd.Series
    lower: pd.Series
    upper: pd.Series
    @classmethod
    def fit(cls, frame: pd.DataFrame):
        return cls(frame.median(), frame.quantile(.01), frame.quantile(.99))
    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.reindex(columns=self.medians.index).fillna(self.medians).clip(self.lower, self.upper, axis=1)
    def as_dict(self):
        return {"fit_sample":"2025-01-01 through 2025-12-31 UTC only", "medians":self.medians.to_dict(), "clip_lower_1pct":self.lower.to_dict(), "clip_upper_99pct":self.upper.to_dict()}

class StumpBoostingRegressor:
    """Small deterministic squared-error tree ensemble; dependency-free fallback for Phase 3A."""
    def __init__(self, iterations=40, learning_rate=.05, max_features=12): self.iterations,self.learning_rate,self.max_features=iterations,learning_rate,max_features
    def fit(self,x,y):
        a=x.to_numpy(float); target=y.to_numpy(float); self.base_=target.mean(); pred=np.full(len(target),self.base_); self.stumps_=[]
        variances=np.nanvar(a,axis=0); candidates=np.argsort(variances)[-min(self.max_features,a.shape[1]):]
        for _ in range(self.iterations):
            residual=target-pred; best=None
            for j in candidates:
                for threshold in np.nanquantile(a[:,j],[.25,.5,.75]):
                    left=a[:,j]<=threshold; lv=residual[left].mean() if left.any() else 0; rv=residual[~left].mean() if (~left).any() else 0
                    gain=(left.sum()*lv*lv+(~left).sum()*rv*rv)
                    if best is None or gain>best[0]: best=(gain,j,threshold,lv,rv)
            _,j,t,lv,rv=best; update=np.where(a[:,j]<=t,lv,rv); pred += self.learning_rate*update; self.stumps_.append((j,t,lv,rv))
        return self
    def predict(self,x):
        a=x.to_numpy(float); p=np.full(len(a),self.base_)
        for j,t,l,r in self.stumps_: p += self.learning_rate*np.where(a[:,j]<=t,l,r)
        return p
    def importance(self, columns):
        counts=pd.Series([z[0] for z in self.stumps_]).value_counts(); return pd.Series({c:counts.get(i,0) for i,c in enumerate(columns)},dtype=float)/max(len(self.stumps_),1)

def rank_targets(scores: pd.Series, top=3, gate=0.0) -> pd.DataFrame:
    matrix=scores.unstack("symbol"); out=pd.DataFrame(0., index=matrix.index, columns=matrix.columns)
    for t,row in matrix.iterrows():
        if row.max()-row.min() < gate: continue
        long=row.nlargest(top).index; short=row.nsmallest(top).index; out.loc[t,long]=1/(2*top); out.loc[t,short]=-1/(2*top)
    return out

def rolling_14d(returns: pd.Series, costs: pd.Series, turnover: pd.Series, mode="daily") -> pd.DataFrame:
    daily=pd.DataFrame({"return":(1+returns).groupby(returns.index.floor("D")).prod()-1,"fees":costs.groupby(costs.index.floor("D")).sum(),"turnover":turnover.groupby(turnover.index.floor("D")).sum()})
    rows=[]; starts=range(0,len(daily)-13) if mode=="daily" else range(0,len(daily)-13,14)
    for i in starts:
        x=daily.iloc[i:i+14]; rows.append({"window_start":x.index[0],"window_end":x.index[-1],"return":(1+x["return"]).prod()-1,"max_drawdown":((1+x["return"]).cumprod()/((1+x["return"]).cumprod().cummax())-1).min(),"fees":x.fees.sum(),"turnover":x.turnover.sum(),"mode":mode})
    return pd.DataFrame(rows)
