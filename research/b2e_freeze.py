"""2025-only reconstruction and verification for the immutable B2E_v1 freeze."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ARTIFACT = ROOT / "frozen" / "b2e_v1.json"
HASH_FILE = ROOT / "frozen" / "b2e_v1.sha256"
DEV_END = pd.Timestamp("2026-01-01", tz="UTC")
DEV_START_TS = pd.Timestamp("2025-01-01", tz="UTC")
TOLERANCE = 1e-10

from baseline_b2c import forward_max_drawdown
from baseline_b2e import FEATURES, fit_standardizer, hold_rebalance_multiplier, risk_multiplier, signal_geometry, vol_only_multiplier
from run_baseline_b1 import BASE, DEV_START, panel, read_or_fetch, run
from run_baseline_b2 import raw_targets
from quant_competition.strategies import MultiHorizonTrend


def scheduled(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index[(index.hour == 0) & (index.minute == 0)]


def fit_ols(y: pd.Series, z: pd.DataFrame) -> pd.Series:
    x = np.column_stack([np.ones(len(z)), z.to_numpy(dtype=float)])
    coef, _, _, _ = np.linalg.lstsq(x, y.to_numpy(dtype=float), rcond=None)
    return pd.Series(coef, index=["const", *FEATURES])


def predict_ols(z: pd.DataFrame, coef: pd.Series) -> pd.Series:
    return pd.Series(np.column_stack([np.ones(len(z)), z.to_numpy(dtype=float)]) @ coef.loc[["const", *FEATURES]].to_numpy(), index=z.index)


def future_risk(result, times: pd.DatetimeIndex) -> pd.DataFrame:
    loc = pd.Series(np.arange(len(result.returns)), index=result.returns.index)
    rows = []
    for timestamp in times:
        p = int(loc[timestamp]); segment = result.returns.iloc[p + 1:p + 25]
        if len(segment) == 24:
            dd = forward_max_drawdown(segment)
            rows.append({"timestamp": timestamp, "future_dd_risk": abs(dd)})
    return pd.DataFrame(rows).set_index("timestamp")


def market_volatility(closes: pd.DataFrame) -> pd.Series:
    return closes.pct_change(fill_method=None).mean(axis=1).rolling(48, min_periods=48).std(ddof=1) * np.sqrt(24 * 365)


def calibrate_vol_k(a_targets, b2e_targets, vol, dev_mask) -> float:
    desired = b2e_targets.loc[dev_mask].abs().sum(axis=1).mean()
    daily_vol = vol.where((vol.index.hour == 0) & (vol.index.minute == 0)).ffill()
    v, a = daily_vol.loc[dev_mask], a_targets.loc[dev_mask]
    lo, hi = 0.0, max(float(v.quantile(.99)) * 2, 1.0)
    for _ in range(80):
        mid = (lo + hi) / 2
        if a.mul(vol_only_multiplier(v, mid), axis=0).abs().sum(axis=1).mean() < desired: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def calibrate_controls(a_weights, b_weights, a_targets, b_targets, vol, development_mask) -> tuple[float, float]:
    """Calibrate controls exclusively on an explicit development mask."""
    if not development_mask.any() or not development_mask.index.equals(a_weights.index):
        raise AssertionError("invalid explicit development mask")
    scale = float(b_weights.loc[development_mask].abs().sum(axis=1).mean() / a_weights.loc[development_mask].abs().sum(axis=1).mean())
    return scale, calibrate_vol_k(a_targets, b_targets, vol, development_mask)


def reconstruct() -> dict:
    """Return every calibrated value, using only bars strictly before 2026."""
    # Jan 1 2026 bars are outcome labels for Dec 31 *2025* decisions only;
    # they never enter a feature, fit, quantile, or control-calibration row.
    frames = {s: read_or_fetch(s, DEV_START, "2026-01-02") for s in BASE}
    opens, closes, _ = panel(frames, BASE)
    a_target = raw_targets(closes); a_full = run(opens, closes, a_target, 10)
    outcomes = future_risk(a_full, scheduled(closes.index))
    geometry = signal_geometry(MultiHorizonTrend(8, 24).target_weights(closes)).reindex(outcomes.index)
    dev = outcomes.join(geometry).dropna()
    if not (dev.index < DEV_END).all(): raise AssertionError("non-2025 calibration row")
    mean, std = fit_standardizer(dev)
    z = (dev[FEATURES] - mean) / std
    model = fit_ols(dev.future_dd_risk, z)
    prediction = predict_ols(z, model)
    q50, q75 = prediction.quantile([.5, .75])
    multiplier = risk_multiplier(prediction, q50, q75)
    b_target = a_target.mul(hold_rebalance_multiplier(closes.index, multiplier), axis=0)
    b_full = run(opens, closes, b_target, 10)
    # Outcome-support bars from Jan 1 2026 exist solely for Dec 31 labels.
    # They are explicitly excluded from both frozen control calibrations.
    development_mask = (closes.index >= DEV_START_TS) & (closes.index < DEV_END)
    if development_mask.sum() != 365 * 24:
        raise AssertionError("development mask is not exactly the 2025 hourly sample")
    scale, vol_k = calibrate_controls(a_full.weights, b_full.weights, a_target, b_target, market_volatility(closes), pd.Series(development_mask, index=closes.index))
    return {
        "normalization": {"signal_strength_mean": float(mean.signal_strength), "signal_strength_std": float(std.signal_strength), "signal_dispersion_mean": float(mean.signal_dispersion), "signal_dispersion_std": float(std.signal_dispersion)},
        "risk_model": {"intercept": float(model["const"]), "beta_strength": float(model.signal_strength), "beta_dispersion": float(model.signal_dispersion)},
        "risk_thresholds": {"q50": float(q50), "q75": float(q75), "severe_drawdown_threshold": float(dev.future_dd_risk.quantile(.75))},
        "controls": {"constant_risk_multiplier": scale, "vol_only_parameters": {"market_volatility_window_hours": 48, "annualization_hours": 8760, "k": vol_k}},
    }


def artifact_payload(values: dict) -> dict:
    return {"strategy_id":"B2E_v1", "status":"FROZEN", "development_period":{"start":"2025-01-01T00:00:00Z","end":"2025-12-31T23:00:00Z"}, "assets":["BTC","ETH","SOL","BNB","XRP"], "symbols":BASE, "feature_definition":{"signal_strength":"mean(abs(raw_signal_i))","signal_dispersion":"std(raw_signal_i, ddof=0)"}, **values, "risk_multipliers":{"low":1.0,"medium":0.75,"high":0.5}, "baseline_strategy":{"ema_fast":8,"ema_slow":24,"volatility_window_hours":48,"target_volatility":0.35,"volatility_floor":0.05,"max_asset_abs_weight":0.35,"max_gross":1.0,"rebalance_hours":24,"next_bar_execution":True}, "primary_cost_bps":10,"stress_cost_bps":[5,15,20],"metrics":{"hours_per_year":8760,"note":"Reporting annualization only; does not affect trades."},"created_before_final_holdout":True,"final_holdout":{"start":"2026-09-22T00:00:00Z","end":"2026-10-03T23:00:00Z","release":"2026-10-04T00:00:00Z"}}


def digest(path: Path = ARTIFACT) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifact() -> str:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(artifact_payload(reconstruct()), indent=2, sort_keys=True) + "\n")
    value = digest(); HASH_FILE.write_text(value + "  b2e_v1.json\n")
    return value


def load_and_verify_hash(path: Path = ARTIFACT, hash_path: Path = HASH_FILE) -> dict:
    expected = hash_path.read_text().split()[0]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected: raise RuntimeError("B2E freeze hash mismatch; aborting before performance evaluation")
    return json.loads(path.read_text())


def verify() -> dict:
    artifact = load_and_verify_hash()
    return verify_artifact(artifact)


def verify_artifact(artifact: dict) -> dict:
    """Compare an already hash-checked artifact to a 2025-only reconstruction."""
    actual = reconstruct()
    diffs = {}
    for section, values in actual.items():
        for key, value in values.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items(): diffs[f"{section}.{key}.{subkey}"] = abs(artifact[section][key][subkey] - subvalue)
            else: diffs[f"{section}.{key}"] = abs(artifact[section][key] - value)
    failed = {k:v for k,v in diffs.items() if v > TOLERANCE}
    if failed: raise RuntimeError(f"B2E freeze reproduction failed (tolerance {TOLERANCE}): {failed}")
    return {"hash": digest(), "tolerance": TOLERANCE, "values": actual, "max_difference": max(diffs.values(), default=0.0)}
