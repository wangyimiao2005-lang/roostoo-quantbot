"""Side-aware, order-independent target reconciliation and executable-target budgeting."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedOrder:
    asset: str
    action: str
    quantity: float


def plan_orders(current: dict, target: dict) -> list[PlannedOrder]:
    reductions, increases = [], []
    for asset in sorted(set(current) | set(target)):
        c = float(current.get(asset, 0.0))
        t = float(target.get(asset, 0.0))
        if c > 0 and (t <= 0 or t < c):
            reductions.append(PlannedOrder(asset, "SELL_LONG", c if t <= 0 else c - t))
        if c < 0 and (t >= 0 or t > c):
            reductions.append(PlannedOrder(asset, "CLOSE_SHORT", -c if t >= 0 else t - c))
        if t > 0 and (c <= 0 or t > c):
            increases.append(PlannedOrder(asset, "BUY_LONG", t if c <= 0 else t - c))
        if t < 0 and (c >= 0 or t < c):
            increases.append(PlannedOrder(asset, "OPEN_SHORT", -t if c >= 0 else c - t))
    return reductions + increases


def estimate_fees(current: dict, desired: dict, prices: dict, fee_bps: float) -> float:
    rate = fee_bps / 10000.0
    return sum(abs(x.quantity) * prices[x.asset] * rate for x in plan_orders(current, desired))


def projected_free_cash(
    current: dict,
    desired: dict,
    prices: dict,
    fee_bps: float,
    free_cash: float,
    short_collateral: dict | None = None,
    short_entry: dict | None = None,
):
    """Project funding cash through reductions first, then increases, at fixed rebalance prices."""
    rate = fee_bps / 10000.0
    short_collateral = short_collateral or {}
    short_entry = short_entry or {}
    cash = float(free_cash)
    for action in plan_orders(current, desired):
        price = prices[action.asset]
        notional = action.quantity * price
        fee = notional * rate
        if action.action == "SELL_LONG":
            cash += notional - fee
        elif action.action == "CLOSE_SHORT":
            old_qty = max(-float(current.get(action.asset, 0.0)), 0.0)
            collateral = float(short_collateral.get(action.asset, 0.0))
            released = collateral * (action.quantity / old_qty) if old_qty else 0.0
            entry = float(short_entry.get(action.asset, price))
            pnl = max((entry - price) * action.quantity, -released)
            cash += released + pnl - fee
        elif action.action == "BUY_LONG":
            cash -= notional + fee
        elif action.action == "OPEN_SHORT":
            cash -= notional + fee
    return cash


def executable_portfolio(
    current: dict,
    theoretical_weights: dict,
    prices: dict,
    equity: float,
    fee_bps: float,
    max_gross: float = 1.0,
    free_cash: float | None = None,
    short_collateral: dict | None = None,
    short_entry: dict | None = None,
):
    """Find the largest common target scale that is actually cash/collateral feasible."""
    if equity <= 0:
        raise ValueError("non-positive equity")
    if free_cash is None:
        free_cash = equity
    gross = sum(abs(float(w)) for w in theoretical_weights.values())
    if gross == 0:
        return dict(theoretical_weights), {a: 0.0 for a in theoretical_weights}, 1.0, 0.0

    def candidate(scale):
        weights = {a: float(w) * scale for a, w in theoretical_weights.items()}
        desired = {a: weights[a] * equity / prices[a] for a in weights}
        fees = estimate_fees(current, desired, prices, fee_bps)
        final_gross_notional = sum(abs(desired[a]) * prices[a] for a in desired)
        max_asset_notional = max((abs(desired[a]) * prices[a] for a in desired), default=0.0)
        cash_after = projected_free_cash(
            current, desired, prices, fee_bps, free_cash, short_collateral, short_entry
        )
        return weights, desired, fees, final_gross_notional, max_asset_notional, cash_after

    upper = min(1.0, max_gross / gross) if gross > 0 else 1.0

    # Keep a tiny deterministic cash cushion for float/precision differences between planning and broker execution.
    cash_reserve = max(0.01, equity * 1e-5)

    def feasible(result):
        _, _, fees, funded, max_asset_notional, cash_after = result
        post_fee_equity = max(equity - fees, 1e-12)
        return (
            cash_after >= cash_reserve
            and funded <= max_gross * post_fee_equity + 1e-9
            and max_asset_notional <= 0.35 * post_fee_equity + 1e-9
        )

    result = candidate(upper)
    if feasible(result):
        weights, desired, fees, *_ = result
        return weights, desired, upper, fees

    lo, hi = 0.0, upper
    for _ in range(80):
        mid = (lo + hi) / 2
        result = candidate(mid)
        if feasible(result):
            lo = mid
        else:
            hi = mid
    weights, desired, fees, *_ = candidate(lo)
    return weights, desired, lo, fees
