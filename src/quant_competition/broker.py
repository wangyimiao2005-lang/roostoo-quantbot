"""Normalized broker boundary for local paper and the current Roostoo public API."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlencode

import requests


def canonical_params(p):
    return "&".join(f"{k}={p[k]}" for k in sorted(p))


def sign_params(secret, p):
    return hmac.new(secret.encode(), canonical_params(p).encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AccountSnapshot:
    free_cash: float
    locked_cash: float
    long_positions: dict
    short_positions: dict
    short_collateral: float
    short_unrealized_pnl: float
    total_equity: float
    short_collateral_by_symbol: dict = field(default_factory=dict)
    short_entry_prices: dict = field(default_factory=dict)


class Broker(ABC):
    @abstractmethod
    def get_server_time(self): ...
    @abstractmethod
    def get_exchange_info(self): ...
    @abstractmethod
    def get_tickers(self): ...
    @abstractmethod
    def get_balances(self): ...
    @abstractmethod
    def get_positions(self): ...
    @abstractmethod
    def get_pending_orders(self): ...
    @abstractmethod
    def place_long_order(self, symbol, side, quantity, price=None): ...
    @abstractmethod
    def open_short(self, symbol, collateral, price=None): ...
    @abstractmethod
    def close_short(self, symbol, quantity, price=None): ...
    @abstractmethod
    def query_order(self, order_id): ...
    @abstractmethod
    def cancel_order(self, order_id): ...
    @abstractmethod
    def account_snapshot(self, prices): ...

    def equity(self, prices):
        return self.account_snapshot(prices).total_equity


class PaperBroker(Broker):
    def __init__(self, cash=100000.0, fee_bps=10.0):
        self.cash = float(cash)
        self.fee_bps = float(fee_bps)
        self.long = {}
        self.short = {}
        self.short_entry = {}
        self.short_collateral = {}
        self.orders = {}
        self.tickers = {}
        self.realized_pnl = 0.0

    def get_server_time(self):
        return int(time.time() * 1000)

    def get_exchange_info(self):
        return {}

    def get_tickers(self):
        return self.tickers.copy()

    def set_tickers(self, x):
        self.tickers = dict(x)

    def get_balances(self):
        # Compatibility: this is spendable USD, not total equity.
        return {"USD": self.cash}

    def get_positions(self):
        return {
            s: self.long.get(s, 0.0) - self.short.get(s, 0.0)
            for s in set(self.long) | set(self.short)
            if abs(self.long.get(s, 0.0) - self.short.get(s, 0.0)) > 1e-15
        }

    def get_open_positions(self):
        return self.get_positions()

    def get_pending_orders(self):
        return []

    def get_order_history(self):
        return list(self.orders.values())

    def _new_order(self, **fields):
        oid = str(uuid.uuid4())
        order = {"Success": True, "OrderID": oid, "Status": "FILLED", **fields}
        self.orders[oid] = order
        return order

    def place_long_order(self, symbol, side, quantity, price=None):
        qty, price = float(quantity), float(price)
        if qty <= 0 or price <= 0 or side not in ("BUY", "SELL"):
            return {"Success": False, "ErrMsg": "invalid order"}
        rate = self.fee_bps / 10000.0
        if side == "BUY":
            max_qty = self.cash / (price * (1 + rate))
            qty = min(qty, max_qty)
            if qty <= 1e-15:
                return {"Success": False, "ErrMsg": "insufficient cash"}
            notional = qty * price
            fee = notional * rate
            self.cash -= notional + fee
            self.long[symbol] = self.long.get(symbol, 0.0) + qty
        else:
            qty = min(qty, self.long.get(symbol, 0.0))
            if qty <= 1e-15:
                return {"Success": False, "ErrMsg": "insufficient long inventory"}
            notional = qty * price
            fee = notional * rate
            self.long[symbol] = self.long.get(symbol, 0.0) - qty
            if self.long[symbol] <= 1e-15:
                self.long.pop(symbol, None)
            self.cash += notional - fee
        return self._new_order(FilledQuantity=qty, FilledAverPrice=price, Fee=fee, Side=side, Pair=symbol)

    def place_order(self, symbol, side, quantity, price=None):
        return self.place_long_order(symbol, side, quantity, price)

    def open_short(self, symbol, collateral, price=None):
        collateral, price = float(collateral), float(price)
        if collateral <= 0 or price <= 0:
            return {"Success": False, "ErrMsg": "invalid order"}
        rate = self.fee_bps / 10000.0
        fee = collateral * rate
        if collateral + fee > self.cash + 1e-12:
            return {"Success": False, "ErrMsg": "insufficient collateral"}
        qty = collateral / price
        old = self.short.get(symbol, 0.0)
        old_entry = self.short_entry.get(symbol, price)
        self.short_entry[symbol] = (old_entry * old + price * qty) / (old + qty)
        self.short[symbol] = old + qty
        self.short_collateral[symbol] = self.short_collateral.get(symbol, 0.0) + collateral
        self.cash -= collateral + fee
        return self._new_order(
            FilledQuantity=qty,
            FilledAverPrice=price,
            Fee=fee,
            Side="SHORT_OPEN",
            Pair=symbol,
            Collateral=collateral,
        )

    def close_short(self, symbol, quantity, price=None):
        qty, price = float(quantity), float(price)
        old = self.short.get(symbol, 0.0)
        if qty <= 0 or price <= 0 or old <= 0:
            return {"Success": False, "ErrMsg": "invalid or absent short"}
        close = min(qty, old)
        entry = self.short_entry.get(symbol, price)
        released = self.short_collateral.get(symbol, 0.0) * (close / old)
        gross_pnl = (entry - price) * close
        # Mirror the documented collateral loss cap on the closed slice.
        realized = max(gross_pnl, -released)
        fee = close * price * self.fee_bps / 10000.0
        self.realized_pnl += realized
        self.cash += released + realized - fee
        remaining = old - close
        remaining_collateral = self.short_collateral.get(symbol, 0.0) - released
        if remaining <= 1e-15:
            self.short.pop(symbol, None)
            self.short_entry.pop(symbol, None)
            self.short_collateral.pop(symbol, None)
        else:
            self.short[symbol] = remaining
            self.short_collateral[symbol] = remaining_collateral
        return self._new_order(
            FilledQuantity=close,
            FilledAverPrice=price,
            Fee=fee,
            Side="SHORT_CLOSE",
            Pair=symbol,
            RealizedPNL=realized,
            RemainingQuantity=max(0.0, remaining),
            RemainingCollateral=max(0.0, remaining_collateral),
        )

    def account_snapshot(self, prices):
        long_value = sum(q * prices[s] for s, q in self.long.items())
        short_collateral = sum(self.short_collateral.values())
        unrealized = sum(
            max((self.short_entry.get(s, prices[s]) - prices[s]) * q, -self.short_collateral.get(s, 0.0))
            for s, q in self.short.items()
        )
        total = self.cash + long_value + short_collateral + unrealized
        return AccountSnapshot(
            free_cash=self.cash,
            locked_cash=short_collateral,
            long_positions=dict(self.long),
            short_positions=dict(self.short),
            short_collateral=short_collateral,
            short_unrealized_pnl=unrealized,
            total_equity=total,
            short_collateral_by_symbol=dict(self.short_collateral),
            short_entry_prices=dict(self.short_entry),
        )

    def query_order(self, order_id):
        return self.orders.get(str(order_id), {"Success": False, "ErrMsg": "order not found"})

    def cancel_order(self, order_id):
        return {"Success": False, "ErrMsg": "immediate paper fills"}


class RoostooBroker(Broker):
    """Roostoo adapter. Public /v3 routes are documented; competition short routes
    are capability-gated and must be verified against the assigned account before live use."""

    def __init__(self, base_url, api_key, secret_key, session=None, max_calls_per_minute=28,
                 audit_log_path=None, sleep_fn=time.sleep, monotonic_fn=time.monotonic):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = session or requests.Session()
        self.server_time_offset_ms = 0
        self.fee_bps = 10.0  # competition runtime uses MARKET/taker execution: 10 bps.
        self.max_calls_per_minute = int(max_calls_per_minute)
        if not 1 <= self.max_calls_per_minute <= 30:
            raise ValueError("max_calls_per_minute must be between 1 and the official 30-call limit")
        self._call_times = deque()
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        if self.audit_log_path:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self):
        now = self._monotonic()
        while self._call_times and now - self._call_times[0] >= 60.0:
            self._call_times.popleft()
        if len(self._call_times) >= self.max_calls_per_minute:
            wait = max(0.0, 60.0 - (now - self._call_times[0]) + 0.01)
            self._sleep(wait)
            now = self._monotonic()
            while self._call_times and now - self._call_times[0] >= 60.0:
                self._call_times.popleft()
        self._call_times.append(self._monotonic())

    def _audit(self, method, path, outcome, attempt=1, status_code=None, error=None):
        if not self.audit_log_path:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method, "path": path, "outcome": outcome, "attempt": attempt,
            "status_code": status_code, "error": None if error is None else str(error),
        }
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    @staticmethod
    def _retry_safe(method, path):
        # Never automatically replay order-creation/short-write endpoints: a lost
        # response after a fill must be recovered from broker-authoritative state.
        return method == "GET" or path in {"/v3/query_order"}

    def _call(self, method, path, params=None, auth="none"):
        base_params = dict(params or {})
        attempts = 3 if self._retry_safe(method, path) else 1
        for attempt in range(1, attempts + 1):
            params = dict(base_params)
            headers = {}
            if auth in ("ts", "signed"):
                params["timestamp"] = int(time.time() * 1000) + self.server_time_offset_ms
            if auth == "signed":
                headers = {
                    "RST-API-KEY": self.api_key,
                    "MSG-SIGNATURE": sign_params(self.secret_key, params),
                }
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body = canonical_params(params)
            else:
                body = None
            try:
                self._rate_limit()
                if method == "POST":
                    response = self.session.request(method, self.base_url + path, data=body, headers=headers, timeout=15)
                else:
                    response = self.session.request(method, self.base_url + path, params=params, headers=headers, timeout=15)
                response.raise_for_status()
                payload = response.json()
                self._audit(method, path, "ok", attempt, getattr(response, "status_code", None))
                return payload
            except requests.RequestException as exc:
                self._audit(method, path, "transport_error", attempt, getattr(getattr(exc, "response", None), "status_code", None), exc)
                if attempt >= attempts:
                    raise
                self._sleep(0.5 * (2 ** (attempt - 1)))
        raise RuntimeError("unreachable API retry state")

    @staticmethod
    def _require_success(payload, allow_empty=False):
        if payload.get("Success", True):
            return payload
        msg = str(payload.get("ErrMsg", "API failure"))
        if allow_empty and ("no order" in msg.lower() or payload.get("TotalPending") == 0):
            return payload
        raise RuntimeError(msg)

    @staticmethod
    def _normalize_order(detail):
        if not detail:
            return {"Success": False, "ErrMsg": "missing order detail"}
        return {
            "Success": True,
            "OrderID": str(detail.get("OrderID", detail.get("ID", ""))),
            "Status": detail.get("Status", detail.get("PositionStatus", "")),
            "Pair": detail.get("Pair"),
            "Side": detail.get("Side"),
            "FilledQuantity": float(detail.get("FilledQuantity", detail.get("ShortQty", detail.get("ClosedQty", 0))) or 0),
            "FilledAverPrice": float(detail.get("FilledAverPrice", detail.get("EntryPrice", detail.get("ClosePrice", 0))) or 0),
            "Fee": float(detail.get("CommissionChargeValue", detail.get("OpenFee", detail.get("CloseFee", 0))) or 0),
            "Collateral": float(detail.get("Collateral", 0) or 0),
            "RealizedPNL": float(detail.get("RealizedPNL", 0) or 0),
            "FullyClosed": bool(detail.get("FullyClosed", False)),
            "Raw": detail,
        }

    def get_server_time(self):
        value = self._call("GET", "/v3/serverTime")["ServerTime"]
        self.server_time_offset_ms = int(value) - int(time.time() * 1000)
        return int(value)

    def get_exchange_info(self):
        return self._call("GET", "/v3/exchangeInfo")

    def get_tickers(self):
        payload = self._require_success(self._call("GET", "/v3/ticker", auth="ts"))
        return payload.get("Data", {})

    def _balance_payload(self):
        """Return the live balance payload using the verified 2026 competition schema.

        The General/Test account was live-verified on 2026-10-01 to return
        ``SpotWallet`` and ``MarginWallet``.  ``Wallet`` is retained only as a
        backwards-compatible fallback for older mocks/legacy environments.
        """
        return self._require_success(self._call("GET", "/v3/balance", auth="signed"))

    @staticmethod
    def _spot_wallet_from_payload(payload):
        return (payload.get("SpotWallet") or payload.get("Wallet") or {}) if isinstance(payload, dict) else {}

    def _wallet(self):
        return self._spot_wallet_from_payload(self._balance_payload())

    def get_balances(self):
        return {asset: float(v.get("Free", 0)) + float(v.get("Lock", 0)) for asset, v in self._wallet().items()}

    def _short_positions(self):
        payload = self._require_success(self._call("GET", "/v6/short_positions", auth="signed"))
        return payload.get("Positions", []) or []

    def get_positions(self):
        wallet = self._wallet()
        positions = {}
        for asset, values in wallet.items():
            if asset == "USD":
                continue
            qty = float(values.get("Free", 0)) + float(values.get("Lock", 0))
            if abs(qty) > 1e-15:
                positions[f"{asset}/USD"] = qty
        for pos in self._short_positions():
            pair = pos["Pair"]
            positions[pair] = positions.get(pair, 0.0) - float(pos.get("ShortQty", 0))
        return {k: v for k, v in positions.items() if abs(v) > 1e-15}

    def get_pending_orders(self):
        payload = self._call("POST", "/v3/query_order", {"pending_only": "TRUE"}, auth="signed")
        if not payload.get("Success", False):
            if "no order" in str(payload.get("ErrMsg", "")).lower():
                return []
            self._require_success(payload)
        return [self._normalize_order(x) for x in payload.get("OrderMatched", [])]

    def get_pending_count(self):
        payload = self._call("GET", "/v3/pending_count", auth="signed")
        if not payload.get("Success", False) and payload.get("TotalPending") == 0:
            return 0
        self._require_success(payload)
        return int(payload.get("TotalPending", 0))

    def place_long_order(self, symbol, side, quantity, price=None):
        params = {"pair": symbol, "side": side, "quantity": quantity, "type": "MARKET"}
        payload = self._require_success(self._call("POST", "/v3/place_order", params, auth="signed"))
        return self._normalize_order(payload.get("OrderDetail", {}))

    def open_short(self, symbol, collateral, price=None):
        payload = self._require_success(
            self._call("POST", "/v6/short_open", {"pair": symbol, "collateral": collateral}, auth="signed")
        )
        return self._normalize_order(payload)

    def close_short(self, symbol, quantity, price=None):
        payload = self._require_success(
            self._call("POST", "/v6/short_close", {"pair": symbol, "close_qty": quantity}, auth="signed")
        )
        result = self._normalize_order(payload)
        result["Status"] = "FILLED"
        result["Side"] = "SHORT_CLOSE"
        return result

    def query_order(self, order_id):
        if not order_id:
            return {"Success": False, "ErrMsg": "missing order id"}
        payload = self._call("POST", "/v3/query_order", {"order_id": order_id}, auth="signed")
        if not payload.get("Success", False):
            return {"Success": False, "ErrMsg": payload.get("ErrMsg", "query failed")}
        matched = payload.get("OrderMatched", [])
        return self._normalize_order(matched[0]) if matched else {"Success": False, "ErrMsg": "order not found"}

    def cancel_order(self, order_id):
        payload = self._call("POST", "/v3/cancel_order", {"order_id": order_id}, auth="signed")
        if not payload.get("Success", False):
            return {"Success": False, "ErrMsg": payload.get("ErrMsg", "cancel failed")}
        return {"Success": True, "CanceledList": payload.get("CanceledList", [])}

    def account_snapshot(self, prices):
        # Read both live sources on every reconciliation cycle.  The 2026-10-01
        # General/Test verification confirmed /v3/balance => SpotWallet/MarginWallet
        # and /v6/short_positions => authoritative ShortQty/Collateral/PnL.
        balance = self._balance_payload()
        wallet = self._spot_wallet_from_payload(balance)
        usd = wallet.get("USD", {}) or {}
        free_cash = float(usd.get("Free", 0) or 0)
        locked_cash = float(usd.get("Lock", 0) or 0)
        wallet_short_collateral = float(usd.get("ShortCollateral", 0) or 0)

        longs = {}
        long_value = 0.0
        for asset, values in wallet.items():
            if asset == "USD":
                continue
            pair = f"{asset}/USD"
            qty = float(values.get("Free", 0) or 0) + float(values.get("Lock", 0) or 0)
            if abs(qty) > 1e-15:
                longs[pair] = qty
                if pair in prices:
                    long_value += qty * prices[pair]

        shorts = {}
        collateral_by_symbol = {}
        entry_by_symbol = {}
        positions_collateral = 0.0
        unrealized = 0.0
        for pos in self._short_positions():
            pair = pos["Pair"]
            qty = float(pos.get("ShortQty", 0) or 0)
            if qty <= 0:
                continue
            shorts[pair] = qty
            collateral_by_symbol[pair] = float(pos.get("Collateral", 0) or 0)
            entry_by_symbol[pair] = float(pos.get("EntryPrice", 0) or 0)
            positions_collateral += collateral_by_symbol[pair]
            unrealized += float(pos.get("UnrealizedPNL", 0) or 0)

        # SpotWallet.ShortCollateral and v6 Positions[].Collateral are independent
        # live views of the same encumbered capital.  Prefer the per-position sum
        # for allocation/risk logic, but halt on a material disagreement rather
        # than silently double-counting or dropping collateral.
        if wallet_short_collateral > 0 and positions_collateral > 0:
            tol = max(0.02, 1e-4 * max(wallet_short_collateral, positions_collateral))
            if abs(wallet_short_collateral - positions_collateral) > tol:
                raise RuntimeError(
                    "Roostoo short collateral mismatch between SpotWallet and v6 positions: "
                    f"{wallet_short_collateral} vs {positions_collateral}"
                )
        collateral = positions_collateral if positions_collateral > 0 else wallet_short_collateral

        # Live verification shows short collateral is reported separately from
        # USD Free/Lock.  Add it once to reconstruct equity; v6 UnrealizedPNL then
        # marks that collateral to market.
        total = free_cash + locked_cash + long_value + collateral + unrealized
        return AccountSnapshot(
            free_cash, locked_cash, longs, shorts, collateral, unrealized, total,
            collateral_by_symbol, entry_by_symbol
        )
