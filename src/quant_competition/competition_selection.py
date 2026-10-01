"""Immutable competition-strategy selection and runtime target adapter."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .funding_shadow import causal_funding_mean, funding_shadow_targets
from .live import frozen_targets

BASELINE = "BASELINE_TREND824"
FUNDING = "FUNDING_FILTER"
ALLOWED = {BASELINE, FUNDING}


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gate_manifest(path: Path | None = None) -> dict:
    path = path or _root() / "frozen/precompetition_gate/FUNDING_VS_BASELINE_GATE.json"
    hash_path = path.with_suffix(".sha256")
    expected = hash_path.read_text().split()[0]
    actual = _digest(path)
    if expected != actual:
        raise RuntimeError("precompetition gate manifest hash mismatch")
    payload = json.loads(path.read_text())
    if payload.get("status") != "PREREGISTERED_AND_SEALED":
        raise RuntimeError("invalid precompetition gate status")
    return payload


def active_strategy_path() -> Path:
    return _root() / "frozen/competition_strategy/ACTIVE_STRATEGY.json"


def load_active_strategy(path: Path | None = None) -> dict:
    """Load the one-shot final selection; default safely to frozen Baseline A.

    Before the final gate is run there is intentionally no active selection
    artifact.  In that state the existing frozen Baseline A remains unchanged.
    """
    path = path or active_strategy_path()
    if not path.exists():
        return {
            "selected_strategy": BASELINE,
            "strategy_version": "trend824_v1_frozen",
            "source": "default_before_final_gate",
        }
    hash_path = path.with_suffix(".sha256")
    if not hash_path.exists():
        raise RuntimeError("active strategy hash is missing")
    expected = hash_path.read_text().split()[0]
    actual = _digest(path)
    if expected != actual:
        raise RuntimeError("active strategy hash mismatch")
    payload = json.loads(path.read_text())
    if payload.get("selected_strategy") not in ALLOWED:
        raise RuntimeError("unknown active competition strategy")
    return payload


def strategy_version(selection: dict | None = None) -> str:
    selection = selection or load_active_strategy()
    if selection["selected_strategy"] == FUNDING:
        return "trend824_funding_filter_v1_final"
    return "trend824_v1_frozen"


def competition_targets(closes: pd.DataFrame, funding: pd.DataFrame | None = None,
                        signal_timestamp=None, selection: dict | None = None) -> pd.Series:
    """Return the exact active theoretical target for a completed signal bar."""
    selection = selection or load_active_strategy()
    baseline = frozen_targets(closes).fillna(0.0)
    if selection["selected_strategy"] == BASELINE:
        return baseline
    if funding is None:
        raise RuntimeError("Funding strategy selected but causal funding data are unavailable")
    gate = load_gate_manifest()
    signal_timestamp = pd.Timestamp(signal_timestamp if signal_timestamp is not None else closes.index[-1])
    if signal_timestamp.tzinfo is None:
        signal_timestamp = signal_timestamp.tz_localize("UTC")
    else:
        signal_timestamp = signal_timestamp.tz_convert("UTC")
    hours = int(gate["funding_challenger"]["feature_hours"])
    fmean = causal_funding_mean(funding[gate["universe"]], signal_timestamp, hours)
    target, _ = funding_shadow_targets(
        baseline.reindex(gate["universe"]),
        fmean.reindex(gate["universe"]),
        float(gate["funding_challenger"]["funding_low"]),
        float(gate["funding_challenger"]["funding_high"]),
    )
    return target.reindex(baseline.index).fillna(0.0)
