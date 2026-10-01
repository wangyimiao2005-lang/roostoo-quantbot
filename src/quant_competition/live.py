"""Frozen paper runtime helpers and crash-safe SQLite state."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from .portfolio import enforce_exposure_limits, risk_scale_targets
from .strategies import MultiHorizonTrend

STRATEGY_VERSION = "trend824_v1_frozen"


def frozen_target_frame(closes: pd.DataFrame) -> pd.DataFrame:
    """Return the frozen theoretical target series over the full supplied history."""
    if len(closes) < 48:
        raise ValueError("insufficient closed-bar warmup")
    raw = MultiHorizonTrend(8, 24).target_weights(closes)
    return enforce_exposure_limits(risk_scale_targets(raw, closes.pct_change()))


def frozen_targets(closes: pd.DataFrame) -> pd.Series:
    return frozen_target_frame(closes).iloc[-1]


def rebalance_id(timestamp, strategy_version: str | None = None) -> str:
    version = strategy_version or STRATEGY_VERSION
    return f"{version}_{pd.Timestamp(timestamp).isoformat()}"


class RuntimeState:
    """Durable state for idempotent/recoverable paper rebalances."""

    def __init__(self, path="data/cache/paper_state.sqlite"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "create table if not exists runs (id text primary key, payload text, created_at text default current_timestamp)"
        )
        self.db.execute(
            "create table if not exists snapshots (key text primary key, payload text, updated_at text default current_timestamp)"
        )
        self.db.execute(
            """create table if not exists rebalances (
                   id text primary key,
                   status text not null,
                   payload text not null,
                   updated_at text default current_timestamp
               )"""
        )
        self.db.commit()

    def already_seen(self, run_id):
        row = self.db.execute("select status from rebalances where id=?", (run_id,)).fetchone()
        if row is not None:
            return row[0] == "COMPLETED"
        return self.db.execute("select 1 from runs where id=?", (run_id,)).fetchone() is not None

    def record(self, run_id, payload):
        with self.db:
            self.db.execute("insert or ignore into runs(id,payload) values (?,?)", (run_id, payload))

    def save_snapshot(self, key, payload):
        with self.db:
            self.db.execute(
                "insert into snapshots(key,payload) values (?,?) "
                "on conflict(key) do update set payload=excluded.payload,updated_at=current_timestamp",
                (key, json.dumps(payload, default=str)),
            )

    def load_snapshot(self, key):
        row = self.db.execute("select payload from snapshots where key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_rebalance(self, run_id):
        row = self.db.execute("select status,payload from rebalances where id=?", (run_id,)).fetchone()
        if not row:
            return None
        return {"status": row[0], "payload": json.loads(row[1])}

    def begin_rebalance(self, run_id, payload):
        """Persist intent before any broker action; existing unfinished work is preserved."""
        with self.db:
            self.db.execute(
                "insert or ignore into rebalances(id,status,payload) values (?,?,?)",
                (run_id, "PLANNED", json.dumps(payload, default=str)),
            )
        return self.get_rebalance(run_id)

    def update_rebalance(self, run_id, status, payload=None):
        current = self.get_rebalance(run_id)
        if current is None:
            raise KeyError(run_id)
        body = current["payload"] if payload is None else payload
        with self.db:
            self.db.execute(
                "update rebalances set status=?,payload=?,updated_at=current_timestamp where id=?",
                (status, json.dumps(body, default=str), run_id),
            )

    def complete_rebalance(self, run_id, payload=None):
        self.update_rebalance(run_id, "COMPLETED", payload)
        self.record(run_id, "completed")
