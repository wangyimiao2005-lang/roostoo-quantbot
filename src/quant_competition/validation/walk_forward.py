from dataclasses import dataclass
import pandas as pd
from quant_competition.backtest import run_backtest
from quant_competition.metrics import performance_metrics
@dataclass
class WalkForwardWindow:
    train_start: str; train_end: str; test_start: str; test_end: str; selected: list[str]; metrics: dict
def walk_forward(opens, closes, candidates: dict, train_bars: int, test_bars: int, cost_bps: float, top_k: int = 3) -> tuple[pd.Series, list[WalkForwardWindow]]:
    all_returns=[]; records=[]
    for start in range(0, len(closes)-train_bars-test_bars+1, test_bars):
        train=slice(start,start+train_bars); test=slice(start+train_bars,start+train_bars+test_bars); scored=[]
        for name, target in candidates.items():
            result=run_backtest(opens.iloc[train], closes.iloc[train], target.iloc[train], cost_bps); score=performance_metrics(result.returns,result.costs,result.turnover)["sharpe"]
            if pd.notna(score) and len(result.trades)>=8 and score>0: scored.append((score,name))
        selected=[name for _,name in sorted(scored, reverse=True)[:top_k]]
        target=sum((candidates[x].iloc[test] for x in selected))/len(selected) if selected else pd.DataFrame(0.,index=closes.iloc[test].index,columns=closes.columns)
        result=run_backtest(opens.iloc[test],closes.iloc[test],target,cost_bps); all_returns.append(result.returns)
        records.append(WalkForwardWindow(str(closes.index[start]),str(closes.index[start+train_bars-1]),str(closes.index[start+train_bars]),str(closes.index[start+train_bars+test_bars-1]),selected,performance_metrics(result.returns,result.costs,result.turnover)))
    return pd.concat(all_returns) if all_returns else pd.Series(dtype=float), records
