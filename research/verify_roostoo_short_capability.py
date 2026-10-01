#!/usr/bin/env python3
"""Roostoo General/Test v6 short-capability verifier.

Default mode is read-only.  The only write-capable mode is explicitly guarded by
both --execute-v6-min-test and --yes-general-test.  It never calls /v3/place_order.
Credentials are read from environment variables and are never printed.

Live contract verified on a General/Test account on 2026-10-01:
  GET  /v3/balance          -> SpotWallet + MarginWallet
  GET  /v6/short_positions  -> Positions[]
  POST /v6/short_open       -> pair + collateral, returns ShortQty
  POST /v6/short_close      -> pair + close_qty
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode

DEFAULT_BASE = "https://mock-api.roostoo.com"
TIMEOUT = 15
OFFICIAL_TEST_PAYLOAD = "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
OFFICIAL_TEST_SECRET = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
OFFICIAL_TEST_SIGNATURE = "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"


def canonical_params(params: dict[str, Any]) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


def sign_raw(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign(secret: str, params: dict[str, Any]) -> str:
    return sign_raw(secret, canonical_params(params))


def credential_issue(value: str | None) -> str | None:
    if value is None or value == "":
        return "missing environment variable"
    if value != value.strip():
        return "leading/trailing whitespace"
    if "\n" in value or "\r" in value:
        return "newline/carriage-return character"
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return "surrounding quote characters"
    return None


def _json_or_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return {"raw_text": text[:1000]}


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if any(token in k.lower() for token in ("secret", "api_key", "apikey", "signature")):
                out[k] = "<redacted>"
            else:
                out[k] = redact_payload(v)
        return out
    if isinstance(payload, list):
        return [redact_payload(x) for x in payload]
    return payload


def print_step(name: str, status: int, payload: Any) -> None:
    print(f"\n=== {name} ===")
    print(f"HTTP {status}")
    print(json.dumps(redact_payload(payload), indent=2, default=str)[:12000])


class CurlApi:
    def __init__(self, base: str, key: str, secret: str):
        self.base = base.rstrip("/")
        self.key = key
        self.secret = secret
        self.offset_ms = 0

    def _run(self, method: str, path: str, params: dict[str, Any] | None = None, signed: bool = False):
        p = dict(params or {})
        if signed:
            p["timestamp"] = int(time.time() * 1000) + self.offset_ms
        canonical = canonical_params(p)
        headers: list[str] = []
        if signed:
            signature = sign_raw(self.secret, canonical)
            headers += ["-H", f"RST-API-KEY: {self.key}", "-H", f"MSG-SIGNATURE: {signature}"]

        cmd = ["/usr/bin/curl", "--silent", "--show-error", "--max-time", str(TIMEOUT), "--request", method.upper()]
        cmd += headers
        if method.upper() == "POST":
            cmd += ["-H", "Content-Type: application/x-www-form-urlencoded", "--data", canonical, self.base + path]
        else:
            url = self.base + path + (("?" + canonical) if canonical else "")
            cmd += [url]
        cmd += ["--write-out", "\n__HTTP_STATUS__:%{http_code}"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"curl failed with code {proc.returncode}")
        marker = "\n__HTTP_STATUS__:"
        if marker not in proc.stdout:
            raise RuntimeError("curl response missing status marker")
        body, code = proc.stdout.rsplit(marker, 1)
        return int(code.strip()), _json_or_text(body.strip()), canonical

    def public_get(self, path: str, params: dict[str, Any] | None = None):
        return self._run("GET", path, params=params, signed=False)

    def signed(self, method: str, path: str, params: dict[str, Any] | None = None):
        return self._run(method, path, params=params, signed=True)


def success(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("Success", True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("ROOSTOO_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--execute-min-test", action="store_true", help="Blocked: v3 SELL-from-zero probing is disabled")
    ap.add_argument("--yes-test-account", action="store_true", help="Retained for compatibility; v3 execution remains blocked")
    ap.add_argument("--execute-v6-min-test", action="store_true", help="Run one guarded General/Test v6 short open-and-close verification")
    ap.add_argument("--yes-general-test", action="store_true", help="Required with --execute-v6-min-test; confirms General/Test credentials")
    args = ap.parse_args()

    if args.execute_min_test:
        print("BLOCKED: /v3/place_order execution probing is disabled in this verifier.", file=sys.stderr)
        return 2
    if args.execute_v6_min_test and not args.yes_general_test:
        print("BLOCKED: add --yes-general-test only after confirming these are General/Test credentials.", file=sys.stderr)
        return 2

    self_sig = sign_raw(OFFICIAL_TEST_SECRET, OFFICIAL_TEST_PAYLOAD)
    print("HMAC self-test:", "PASS" if self_sig == OFFICIAL_TEST_SIGNATURE else "FAIL")
    if self_sig != OFFICIAL_TEST_SIGNATURE:
        return 3

    key = os.getenv("ROOSTOO_API_KEY")
    secret = os.getenv("ROOSTOO_SECRET_KEY")
    key_issue = credential_issue(key)
    secret_issue = credential_issue(secret)
    print("API key sanitation:", "PASS" if key_issue is None else f"FAIL ({key_issue})")
    print("Secret sanitation:", "PASS" if secret_issue is None else f"FAIL ({secret_issue})")
    if key_issue or secret_issue:
        print("Credential sanitation failed. Re-enter the affected General/Test credential without altering it in this script.")
        return 4

    api = CurlApi(args.base_url, key, secret)
    st, server, _ = api.public_get("/v3/serverTime")
    if st != 200 or not isinstance(server, dict) or "ServerTime" not in server:
        print_step("v3 serverTime (public)", st, server)
        return 5
    local_ms = int(time.time() * 1000)
    api.offset_ms = int(server["ServerTime"]) - local_ms

    # Build diagnostics from the exact timestamp/canonical payload used for balance.
    st_bal, bal, canonical = api.signed("GET", "/v3/balance")
    used_ts = int(canonical.split("=", 1)[1])
    print("timestamp used:", used_ts)
    print("serverTime:", int(server["ServerTime"]))
    print("absolute time delta in ms:", abs(used_ts - int(server["ServerTime"])))
    print("canonical signed string:", canonical)
    sig = sign(secret, {"timestamp": used_ts})
    print("signature format validity: 64 lowercase hex characters,", "YES" if re.fullmatch(r"[0-9a-f]{64}", sig) else "NO")

    print_step("v3 balance (signed, read-only)", st_bal, bal)
    if st_bal != 200 or not success(bal):
        print("\nRESULT: authentication/signed balance check failed; no short endpoint was called.")
        return 6

    st_pos, positions, _ = api.signed("GET", "/v6/short_positions")
    print_step("v6 short_positions (signed, read-only capability probe)", st_pos, positions)
    if st_pos == 200 and success(positions):
        print("Endpoint assessment: endpoint appears to exist")
    elif st_pos in (401, 403):
        print("Endpoint assessment: authentication/permission issue")
        return 7
    elif st_pos in (404, 405):
        print("Endpoint assessment: endpoint likely unavailable")
        return 7
    elif st_pos >= 500:
        print("Endpoint assessment: server-side/unsupported behavior")
        return 7
    else:
        print("Endpoint assessment: inconclusive")
        return 7

    if not args.execute_v6_min_test:
        print("\nRESULT: authentication and v6 read-only capability passed; no order endpoint was called.")
        return 0

    existing = positions.get("Positions", []) if isinstance(positions, dict) else []
    if existing:
        print("BLOCKED: General/Test account already has an open short; refusing to add test risk.", file=sys.stderr)
        return 8

    st_info, info, _ = api.public_get("/v3/exchangeInfo")
    if st_info != 200 or not isinstance(info, dict):
        print_step("v3 exchangeInfo (public)", st_info, info)
        return 9
    meta = (info.get("TradePairs", {}) or {}).get("BTC/USD")
    if not meta or not meta.get("CanTrade") or meta.get("AssetType") != "crypto":
        print("BLOCKED: BTC/USD is not a tradable crypto pair in exchangeInfo.", file=sys.stderr)
        return 9
    collateral = max(1.0, float(meta.get("MiniOrder", 1) or 1))
    if collateral.is_integer():
        collateral_param = str(int(collateral))
    else:
        collateral_param = format(collateral, ".12g")

    print("\n=== MINIMAL V6 SHORT TEST PLAN ===")
    print(json.dumps({
        "pair": "BTC/USD", "CanTrade": True, "AssetType": "crypto",
        "minimum_collateral_usd": collateral_param,
        "amount_precision": int(meta.get("AmountPrecision", 0) or 0),
        "open_endpoint": "/v6/short_open", "open_parameters": {"pair": "BTC/USD", "collateral": collateral_param},
        "close_endpoint": "/v6/short_close", "close_parameters": {"pair": "BTC/USD", "close_qty": "entire ShortQty returned by the server"},
    }, indent=2))

    st_open, opened, _ = api.signed("POST", "/v6/short_open", {"pair": "BTC/USD", "collateral": collateral_param})
    print_step("v6 short_open (one minimum General/Test short)", st_open, opened)
    if st_open != 200 or not success(opened):
        print("RESULT: short_open failed; stopped without trying alternate formats.")
        return 10
    short_qty = float(opened.get("ShortQty", 0) or 0)
    if short_qty <= 0:
        print("CRITICAL: short_open succeeded but returned no positive ShortQty; manual account inspection required.", file=sys.stderr)
        return 11

    st_after_open, after_open, _ = api.signed("GET", "/v6/short_positions")
    print_step("v6 short_positions after opening", st_after_open, after_open)
    if st_after_open != 200 or not success(after_open):
        print("CRITICAL: unable to verify open short. Attempting only the known full-quantity close for safety.", file=sys.stderr)

    # Once the test short exists, flattening it is mandatory.  Use the server-returned
    # ShortQty, never the theoretical/requested collateral conversion.
    close_qty = format(short_qty, ".16g")
    st_close, closed, _ = api.signed("POST", "/v6/short_close", {"pair": "BTC/USD", "close_qty": close_qty})
    print_step("v6 short_close (entire test position)", st_close, closed)
    if st_close != 200 or not success(closed):
        print("CRITICAL: test short may remain open. Do not open another position; inspect /v6/short_positions immediately.", file=sys.stderr)
        return 12

    st_final, final, _ = api.signed("GET", "/v6/short_positions")
    print_step("v6 short_positions after closing", st_final, final)
    remaining = final.get("Positions", []) if isinstance(final, dict) else None
    if st_final == 200 and success(final) and not remaining:
        print("RESULT: v6 short open → verify → close → verify completed with no remaining test short.")
        return 0
    print("CRITICAL: final short state is not empty; do not open another test position.", file=sys.stderr)
    return 13


if __name__ == "__main__":
    raise SystemExit(main())
