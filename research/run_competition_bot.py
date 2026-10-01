#!/usr/bin/env python3
"""24/7 competition launcher.  Defaults to DRY_RUN and never stores credentials."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_competition.binance_live import BinanceCompetitionLiveProvider
from quant_competition.broker import RoostooBroker
from quant_competition.competition_runtime import build_competition_paper_runner
from quant_competition.competition_selection import active_strategy_path
from quant_competition.funding_provider import RELEASE
from quant_competition.live import RuntimeState
from quant_competition.symbols import broker_from_asset, asset_from_research

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def emit(path: Path, event: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"logged_at": datetime.now(timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(body, default=str, sort_keys=True) + "\n")
    print(json.dumps(body, default=str, sort_keys=True), flush=True)


def ensure_final_gate(now: pd.Timestamp, log_path: Path):
    if now < RELEASE or active_strategy_path().exists():
        return
    emit(log_path, {"event": "final_gate_start"})
    proc = subprocess.run(
        [sys.executable, str(ROOT / "research/run_final_precompetition_gate.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    emit(log_path, {
        "event": "final_gate_finish", "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:],
    })
    if proc.returncode != 0 or not active_strategy_path().exists():
        raise RuntimeError("final precompetition gate failed; competition trading remains blocked")


def make_runtime(mode: str):
    base = os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com")
    key = os.getenv("ROOSTOO_API_KEY")
    secret = os.getenv("ROOSTOO_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ROOSTOO_API_KEY and ROOSTOO_SECRET_KEY are required")
    if mode == "COMPETITION" and os.getenv("ROOSTOO_COMPETITION_ACK") != "YES":
        raise RuntimeError("set ROOSTOO_COMPETITION_ACK=YES once before enabling COMPETITION mode")
    api_log = ROOT / "logs/roostoo_api.jsonl"
    broker = RoostooBroker(base, key, secret, max_calls_per_minute=28, audit_log_path=api_log)
    provider = BinanceCompetitionLiveProvider(
        bootstrap_dir=ROOT / "data/raw",
        cache_dir=ROOT / "data/binance_competition_live",
    )
    state_file = "runtime_state.sqlite" if mode == "COMPETITION" else "dry_run_state.sqlite"
    state = RuntimeState(ROOT / "data/competition" / state_file)
    runner = build_competition_paper_runner(provider, broker, state, mode=mode, cache_dir=ROOT / "data/funding_competition_live")
    return broker, runner


def one_cycle(broker, runner, mode, log_path):
    server_ms = broker.get_server_time()
    now = pd.Timestamp(server_ms, unit="ms", tz="UTC")
    ensure_final_gate(now, log_path)
    info = broker.get_exchange_info()
    if not bool(info.get("IsRunning", False)):
        emit(log_path, {"event": "cycle", "status": "HALT_NEW_RISK", "reason": "exchange not running", "server_time": str(now)})
        return "HALT_NEW_RISK"
    tickers = broker.get_tickers()
    prices = {}
    for symbol in SYMBOLS:
        asset = asset_from_research(symbol)
        pair = broker_from_asset(asset)
        raw = tickers.get(pair)
        if not raw or float(raw.get("LastPrice", 0) or 0) <= 0:
            emit(log_path, {"event": "cycle", "status": "HALT_NEW_RISK", "reason": f"missing ticker {pair}", "server_time": str(now)})
            return "HALT_NEW_RISK"
        prices[symbol] = float(raw["LastPrice"])
    result = runner.run(SYMBOLS, prices, now)
    emit(log_path, {
        "event": "cycle", "mode": mode, "server_time": str(now),
        "status": result.status, "rebalance_id": result.rebalance_id,
        "reason": result.reason, "targets": result.targets,
        "executable_targets": result.executable_targets, "orders": result.orders,
    })
    return result.status


def in_execution_window(now_utc: datetime) -> bool:
    # Strategy uses the completed 00:00 UTC bar and may execute during 01:02-01:54.
    return now_utc.hour == 1 and 2 <= now_utc.minute <= 54


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["DRY_RUN", "COMPETITION"], default="DRY_RUN")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=300)
    args = parser.parse_args()
    log_path = ROOT / "logs/competition_runtime.jsonl"
    broker, runner = make_runtime(args.mode)
    if args.once:
        one_cycle(broker, runner, args.mode, log_path)
        return
    emit(log_path, {"event": "daemon_start", "mode": args.mode})
    while True:
        try:
            now_local = datetime.now(timezone.utc)
            if in_execution_window(now_local):
                status = one_cycle(broker, runner, args.mode, log_path)
                # Once today's rebalance is complete, there is no reason to keep hitting Roostoo.
                if status in {"RECONCILED", "ALREADY_DONE", "DRY_RUN"}:
                    time.sleep(max(args.poll_seconds, 600))
                else:
                    time.sleep(args.poll_seconds)
            else:
                time.sleep(min(max(args.poll_seconds, 60), 900))
        except KeyboardInterrupt:
            emit(log_path, {"event": "daemon_stop", "reason": "keyboard_interrupt"})
            return
        except Exception as exc:
            emit(log_path, {"event": "daemon_exception", "error": repr(exc)})
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
