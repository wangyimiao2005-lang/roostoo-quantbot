"""Frozen competition strategy executor.

Strategy logic remains unchanged.  This module hardens only the production boundary:
closed-bar alignment, exchange-rule quantization, broker inventory safety, explicit
execution modes, exception containment, and crash-safe reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import math
import pandas as pd

from .execution import executable_portfolio, estimate_fees, plan_orders
from .live import rebalance_id
from .competition_selection import competition_targets, load_active_strategy, strategy_version, FUNDING
from .reconciliation import reconcile
from .symbols import asset_from_broker, asset_from_research, broker_from_asset


@dataclass
class RunResult:
    status: str
    rebalance_id: str | None
    targets: dict
    orders: list
    reason: str = ""
    executable_targets: dict | None = None


class PaperRunner:
    """Operational implementation of the exact frozen 00:00 -> 01:00 UTC schedule."""

    ALLOWED_MODES = {"DRY_RUN", "LOCAL_PAPER", "COMPETITION"}

    def __init__(self, provider, broker, state, mode="DRY_RUN", shadow_runtime=None, funding_history_provider=None):
        if mode not in self.ALLOWED_MODES:
            raise ValueError(f"unsupported execution mode: {mode}")
        self.provider = provider
        self.broker = broker
        self.state = state
        self.mode = mode
        self.shadow_runtime = shadow_runtime
        self.funding_history_provider = funding_history_provider

    def _observe_funding_shadow(self, frames):
        if self.shadow_runtime is None or self.funding_history_provider is None:
            return
        if set(frames) != set(self.shadow_runtime.symbols):
            return
        closes = pd.DataFrame({symbol: frame.close for symbol, frame in frames.items()})
        opens = pd.DataFrame({symbol: frame.open for symbol, frame in frames.items()})
        if not self.shadow_runtime.data_access_allowed(closes.index[-1]):
            return
        try:
            funding = self.funding_history_provider(self.shadow_runtime.symbols, closes.index[-1])
            self.shadow_runtime.catch_up_completed(opens, closes, funding)
        except Exception:
            return

    @staticmethod
    def _canonical_prices(recent_prices):
        out = {asset_from_research(k): float(v) for k, v in recent_prices.items()}
        if any((not math.isfinite(v)) or v <= 0 for v in out.values()):
            raise ValueError("non-positive or non-finite execution price")
        return out

    def _current_positions(self):
        return {asset_from_broker(k): float(v) for k, v in self.broker.get_positions().items()}

    @staticmethod
    def _floor_signed_quantity(quantity: float, precision: int) -> float:
        if abs(quantity) <= 0:
            return 0.0
        quantum = Decimal("1").scaleb(-int(precision))
        q = float(Decimal(str(abs(quantity))).quantize(quantum, rounding=ROUND_DOWN))
        return q if quantity >= 0 else -q

    def _exchange_rules(self, assets):
        try:
            info = self.broker.get_exchange_info() or {}
        except Exception as exc:
            return {}, f"Roostoo exchangeInfo unavailable: {exc}"
        pairs = info.get("TradePairs", {}) if isinstance(info, dict) else {}
        # PaperBroker deliberately returns no rules.
        if not pairs:
            return {}, ""
        rules = {}
        for asset in assets:
            pair = broker_from_asset(asset)
            raw = pairs.get(pair)
            if raw is None:
                return {}, f"Roostoo exchangeInfo missing required pair {pair}"
            if not bool(raw.get("CanTrade", False)):
                return {}, f"Roostoo pair is not tradable: {pair}"
            rules[asset] = {
                "amount_precision": int(raw.get("AmountPrecision", 0)),
                "min_order": float(raw.get("MiniOrder", 0.0) or 0.0),
            }
        return rules, ""

    def _apply_exchange_rules(self, current, desired, prices, equity, rules):
        if not rules:
            return dict(desired), ""
        current_gross = sum(abs(float(q)) * prices[a] for a, q in current.items() if a in prices) / max(equity, 1e-12)
        adjusted = {}
        for asset in sorted(set(desired) | set(current)):
            if asset not in prices:
                continue
            c = float(current.get(asset, 0.0))
            t = float(desired.get(asset, 0.0))
            rule = rules[asset]
            q = self._floor_signed_quantity(t, rule["amount_precision"])
            delta = abs(q - c)
            if delta <= 1e-15:
                adjusted[asset] = q
                continue
            notional = delta * prices[asset]
            if notional <= rule["min_order"] + 1e-12:
                current_weight = c * prices[asset] / max(equity, 1e-12)
                required_reduction = (
                    abs(q) < abs(c)
                    and (abs(current_weight) > 0.35 + 1e-12 or current_gross > 1.0 + 1e-12)
                )
                if required_reduction:
                    return {}, f"required {asset} risk reduction is below Roostoo MiniOrder"
                adjusted[asset] = c
            else:
                adjusted[asset] = q
        return adjusted, ""

    @staticmethod
    def _reconciliation_tolerance(rules, prices, equity):
        """Allow only sub-lot exposure differences from exchange quantity rounding."""
        if not rules:
            return 1e-6
        one_lot_weight = sum(
            (10.0 ** -rule["amount_precision"]) * prices[asset] / equity
            for asset, rule in rules.items() if asset in prices
        )
        return max(1e-6, one_lot_weight + 1e-9)

    def _execute(self, planned, canonical_prices):
        """Submit exactly one write.

        Deliberately do not swallow transport/process exceptions here. An exception can
        occur *after* the venue accepted the order, so converting it into an ordinary
        failure would falsely imply that no fill occurred. The rebalance state is already
        durable before this call; the supervisor may restart the cycle, which first
        re-reads broker-authoritative positions and plans only the remaining delta.
        """
        symbol = broker_from_asset(planned.asset)
        price = canonical_prices[planned.asset]
        if planned.action == "SELL_LONG":
            return self.broker.place_long_order(symbol, "SELL", planned.quantity, price)
        if planned.action == "CLOSE_SHORT":
            return self.broker.close_short(symbol, planned.quantity, price)
        if planned.action == "BUY_LONG":
            return self.broker.place_long_order(symbol, "BUY", planned.quantity, price)
        return self.broker.open_short(symbol, planned.quantity * price, price)

    def run(self, symbols, recent_prices, now):
        if hasattr(self.provider, "set_as_of"):
            self.provider.set_as_of(now)
        try:
            frames = {s: self.provider.get_recent_closed_bars(s, None) for s in symbols}
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", None, {}, [], f"market-data fetch failed: {exc}")
        health = [self.provider.validate(x, now) for x in frames.values()]
        if any(x.status != "OK" for x in health):
            bad = next(x for x in health if x.status != "OK")
            return RunResult("HALT_NEW_RISK", None, {}, [], bad.reason)

        latest_by_symbol = {s: pd.Timestamp(f.index[-1]) for s, f in frames.items()}
        if len(set(latest_by_symbol.values())) != 1:
            return RunResult("HALT_NEW_RISK", None, {}, [], f"latest completed bars not aligned: {latest_by_symbol}")
        closes = pd.DataFrame({s: f.close for s, f in frames.items()}).dropna(how="any")
        if closes.empty:
            return RunResult("HALT_NEW_RISK", None, {}, [], "no common completed bars")
        signal_ts = closes.index[-1]
        if any(ts != signal_ts for ts in latest_by_symbol.values()):
            return RunResult("HALT_NEW_RISK", None, {}, [], "common signal timestamp is stale")

        self._observe_funding_shadow(frames)
        selection = load_active_strategy()
        funding = None
        if selection["selected_strategy"] == FUNDING:
            if self.funding_history_provider is None:
                return RunResult("HALT_NEW_RISK", None, {}, [], "Funding strategy selected but funding provider is unavailable")
            try:
                funding = self.funding_history_provider(list(symbols), signal_ts)
            except Exception as exc:
                return RunResult("HALT_NEW_RISK", None, {}, [], f"Funding strategy selected but funding data failed: {exc}")
        try:
            theoretical = competition_targets(closes, funding=funding, signal_timestamp=signal_ts, selection=selection).to_dict()
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", None, {}, [], f"active strategy target failure: {exc}")
        execution_ts = signal_ts + pd.Timedelta(hours=1)
        if signal_ts.hour != 0 or execution_ts.hour != 1:
            return RunResult("NOT_DUE", None, theoretical, [])

        rid = rebalance_id(execution_ts, strategy_version(selection))
        existing = self.state.get_rebalance(rid)
        if existing and existing["status"] == "COMPLETED":
            return RunResult("ALREADY_DONE", rid, theoretical, [])

        try:
            canonical_prices = self._canonical_prices(recent_prices)
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", rid, theoretical, [], f"execution-price validation failed: {exc}")
        expected_assets = {asset_from_research(s) for s in symbols}
        if set(canonical_prices) != expected_assets:
            return RunResult("HALT_NEW_RISK", rid, theoretical, [], f"execution-price universe mismatch: {sorted(canonical_prices)}")
        broker_prices = {broker_from_asset(a): p for a, p in canonical_prices.items()}

        try:
            pending = self.broker.get_pending_orders()
            if pending:
                return RunResult("HALT_NEW_RISK", rid, theoretical, [], "pending orders")
            current = self._current_positions()
            extra_positions = sorted(set(current) - set(canonical_prices))
            if extra_positions:
                return RunResult("HALT_NEW_RISK", rid, theoretical, [], f"out-of-universe broker positions: {extra_positions}")
            safety_snapshot = self.broker.account_snapshot(broker_prices)
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", rid, theoretical, [], f"broker state read failed: {exc}")

        snapshot_symbols = set(safety_snapshot.long_positions) | set(safety_snapshot.short_positions)
        snapshot_assets = {asset_from_broker(x) for x in snapshot_symbols}
        extras = sorted(snapshot_assets - set(canonical_prices))
        if extras:
            return RunResult("HALT_NEW_RISK", rid, theoretical, [], f"out-of-universe gross broker positions: {extras}")
        overlapping = sorted(
            asset_from_broker(x)
            for x in set(safety_snapshot.long_positions) & set(safety_snapshot.short_positions)
            if float(safety_snapshot.long_positions.get(x, 0.0)) > 1e-15
            and float(safety_snapshot.short_positions.get(x, 0.0)) > 1e-15
        )
        if overlapping:
            return RunResult("HALT_NEW_RISK", rid, theoretical, [], f"simultaneous long/short inventory: {overlapping}")

        if existing is None:
            snapshot = safety_snapshot
            equity = float(snapshot.total_equity)
            if not math.isfinite(equity) or equity <= 0:
                return RunResult("HALT_NEW_RISK", rid, theoretical, [], "non-positive/non-finite equity")
            canonical_theoretical = {asset_from_research(k): float(v) for k, v in theoretical.items()}
            fee_bps = float(getattr(self.broker, "fee_bps", 10.0))
            short_collateral = {asset_from_broker(k): float(v) for k, v in snapshot.short_collateral_by_symbol.items()}
            short_entry = {asset_from_broker(k): float(v) for k, v in snapshot.short_entry_prices.items()}
            executable, desired, scale, estimated_fees = executable_portfolio(
                current, canonical_theoretical, canonical_prices, equity, fee_bps,
                free_cash=float(snapshot.free_cash), short_collateral=short_collateral, short_entry=short_entry
            )
            rules, rules_error = self._exchange_rules(canonical_prices)
            if rules_error:
                return RunResult("HALT_NEW_RISK", rid, theoretical, [], rules_error)
            desired, rules_error = self._apply_exchange_rules(current, desired, canonical_prices, equity, rules)
            if rules_error:
                return RunResult("HALT_NEW_RISK", rid, theoretical, [], rules_error)
            executable = {a: desired.get(a, 0.0) * canonical_prices[a] / equity for a in canonical_prices}
            estimated_fees = estimate_fees(current, desired, canonical_prices, fee_bps)
            payload = {
                "signal_timestamp": str(signal_ts), "execution_timestamp": str(execution_ts),
                "active_strategy": selection["selected_strategy"], "strategy_version": strategy_version(selection),
                "theoretical_targets": canonical_theoretical, "executable_targets": executable,
                "desired_quantities": desired, "prices": canonical_prices,
                "pretrade_equity": equity, "pretrade_free_cash": float(snapshot.free_cash),
                "execution_scale": scale, "estimated_fees": estimated_fees,
                "exchange_rules": rules, "orders": [],
            }
            existing = self.state.begin_rebalance(rid, payload)

        payload = existing["payload"]
        desired = {k: float(v) for k, v in payload["desired_quantities"].items()}
        executable = {k: float(v) for k, v in payload["executable_targets"].items()}
        canonical_prices = {k: float(v) for k, v in payload["prices"].items()}
        broker_prices = {broker_from_asset(a): p for a, p in canonical_prices.items()}
        orders = list(payload.get("orders", []))

        try:
            current = self._current_positions()
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", rid, theoretical, orders, f"position refresh failed: {exc}", executable)
        if self.mode == "DRY_RUN":
            planned = plan_orders(current, desired)
            return RunResult("DRY_RUN", rid, theoretical, [x.__dict__ for x in planned], executable_targets=executable)

        self.state.update_rebalance(rid, "EXECUTING_REDUCTIONS", payload)
        try:
            current = self._current_positions()
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", rid, theoretical, orders, f"position refresh failed: {exc}", executable)
        reductions = [x for x in plan_orders(current, desired) if x.action in ("SELL_LONG", "CLOSE_SHORT")]
        for action in reductions:
            response = self._execute(action, canonical_prices)
            orders.append({**action.__dict__, "response": response})
            payload["orders"] = orders
            self.state.update_rebalance(rid, "EXECUTING_REDUCTIONS", payload)
            if not response.get("Success"):
                self.state.update_rebalance(rid, "FAILED", payload)
                return RunResult("HALT_NEW_RISK", rid, theoretical, orders, response.get("ErrMsg", "broker failure"), executable)

        try:
            if self.broker.get_pending_orders():
                return RunResult("HALT_NEW_RISK", rid, theoretical, orders, "pending after reductions", executable)
            current = self._current_positions()
        except Exception as exc:
            return RunResult("HALT_NEW_RISK", rid, theoretical, orders, f"post-reduction broker read failed: {exc}", executable)

        self.state.update_rebalance(rid, "EXECUTING_INCREASES", payload)
        increases = [x for x in plan_orders(current, desired) if x.action in ("BUY_LONG", "OPEN_SHORT")]
        for action in increases:
            response = self._execute(action, canonical_prices)
            orders.append({**action.__dict__, "response": response})
            payload["orders"] = orders
            self.state.update_rebalance(rid, "EXECUTING_INCREASES", payload)
            if not response.get("Success"):
                self.state.update_rebalance(rid, "FAILED", payload)
                return RunResult("HALT_NEW_RISK", rid, theoretical, orders, response.get("ErrMsg", "broker failure"), executable)

        self.state.update_rebalance(rid, "FINAL_RECONCILIATION", payload)
        try:
            post = self._current_positions()
            post_snapshot = self.broker.account_snapshot(broker_prices)
            post_equity = float(post_snapshot.total_equity)
            pending = self.broker.get_pending_orders()
        except Exception as exc:
            self.state.update_rebalance(rid, "FAILED", payload)
            return RunResult("HALT_NEW_RISK", rid, theoretical, orders, f"final broker read failed: {exc}", executable)
        if not math.isfinite(post_equity) or post_equity <= 0:
            self.state.update_rebalance(rid, "FAILED", payload)
            return RunResult("HALT_NEW_RISK", rid, theoretical, orders, "invalid post-trade equity", executable)
        expected_weights = {a: desired.get(a, 0.0) * canonical_prices[a] / post_equity for a in set(desired)}
        tolerance = self._reconciliation_tolerance(payload.get("exchange_rules", {}), canonical_prices, post_equity)
        postrec = reconcile(expected_weights, post, canonical_prices, post_equity, pending, set(), tolerance=tolerance)
        payload.update({
            "post_equity": post_equity, "post_positions": post,
            "reconciliation_status": postrec.status, "tracking_error": postrec.target_tracking_error,
            "gross_exposure": postrec.gross_exposure, "net_exposure": postrec.net_exposure,
        })
        self.state.save_snapshot("latest", {
            "rebalance_id": rid, "theoretical_targets": theoretical, "executable_targets": executable,
            "positions": post, "execution_health": postrec.status,
        })
        if postrec.status == "OK":
            self.state.complete_rebalance(rid, payload)
            return RunResult("RECONCILED", rid, theoretical, orders, "OK", executable)
        self.state.update_rebalance(rid, "FAILED", payload)
        return RunResult("HALT_NEW_RISK", rid, theoretical, orders, postrec.status, executable)
