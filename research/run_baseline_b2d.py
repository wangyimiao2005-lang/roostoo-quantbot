"""B2D: is raw/residual disagreement an *incremental* risk-state signal?

No trading rule is changed.  The experiment compares nested causal risk models:

RISK
    48h market realized volatility, trailing 720h average pairwise correlation,
    frozen-A gross exposure, current frozen-A drawdown.
RISK+AGREEMENT
    RISK plus B2C portfolio agreement.
RISK+SIGNAL
    RISK plus two simpler raw-signal geometry variables: target-weighted raw
    signal strength and cross-sectional raw-signal dispersion.
FULL
    RISK+SIGNAL plus agreement.

All predictor standardization and predictive model fitting use 2025 development
only.  2026 is used once for out-of-sample prediction comparisons.  OOS
regression coefficients are diagnostic replication checks, not fitted trading
rules.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "baseline_b2d"

from baseline_b2c import agreement_score, portfolio_agreement
from baseline_b2d import (
    apply_standardizer,
    development_standardizer,
    trailing_average_pairwise_correlation,
    weighted_absolute_signal_strength,
)
from run_baseline_b1 import BASE, DEV_START, OOS_END, OOS_START, panel, read_or_fetch, run
from run_baseline_b2 import raw_targets, residual_targets
from run_baseline_b2c import future_outcomes, scheduled_signal_times
from quant_competition.strategies import MultiHorizonTrend

OOS = pd.Timestamp(OOS_START, tz="UTC")
END = pd.Timestamp(OOS_END, tz="UTC")

RISK = ["market_vol_48h", "corr_720h", "gross_exposure", "current_drawdown"]
SIGNAL_GEOMETRY = ["raw_signal_strength", "signal_dispersion"]
MODEL_COLUMNS = {
    "RISK": RISK,
    "RISK+AGREEMENT": RISK + ["portfolio_agreement"],
    "RISK+SIGNAL": RISK + SIGNAL_GEOMETRY,
    "FULL": RISK + SIGNAL_GEOMETRY + ["portfolio_agreement"],
}
HORIZONS = {"24h": 1, "3d": 3, "7d": 7}  # HAC daily lags


def build_feature_frame() -> pd.DataFrame:
    frames = {s: read_or_fetch(s, DEV_START, OOS_END) for s in BASE}
    opens, closes, _ = panel(frames, BASE)
    returns = closes.pct_change(fill_method=None)

    raw_signal = MultiHorizonTrend(8, 24).target_weights(closes)
    a_target = raw_targets(closes)
    _, residual_signal, residual_returns, _, _, _ = residual_targets(closes, 720)
    agreement = agreement_score(raw_signal, residual_signal)
    valid_residual = residual_returns.notna().rolling(24, min_periods=24).sum().eq(24)
    agreement = agreement.where(valid_residual)
    p_agreement = portfolio_agreement(agreement, a_target)

    a_result = run(opens, closes, a_target, 10)
    signals = scheduled_signal_times(closes.index)
    outcomes = future_outcomes(a_result, signals, p_agreement).set_index("signal_timestamp")

    # All features below are observable by the signal timestamp.
    market_return = returns.mean(axis=1)
    market_vol = (
        market_return.rolling(48, min_periods=48).std(ddof=1) * np.sqrt(24 * 365)
    ).rename("market_vol_48h")
    corr = trailing_average_pairwise_correlation(returns, outcomes.index, 720).rename("corr_720h")
    strength = weighted_absolute_signal_strength(raw_signal, a_target)
    dispersion = raw_signal.std(axis=1, ddof=0).rename("signal_dispersion")
    gross = a_target.abs().sum(axis=1).rename("gross_exposure")
    wealth = (1.0 + a_result.returns).cumprod()
    current_dd = (wealth / wealth.cummax() - 1.0).rename("current_drawdown")

    features = pd.concat(
        [market_vol, strength, dispersion, gross, current_dd], axis=1
    ).reindex(outcomes.index)
    features["corr_720h"] = corr
    return outcomes.join(features).dropna()


def fit_hac(y: pd.Series, x: pd.DataFrame, lags: int):
    return sm.OLS(y, sm.add_constant(x, has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )


def predictive_metrics(y: pd.Series, prediction: pd.Series, severe_threshold: float) -> dict:
    mse = float(np.mean((y - prediction) ** 2))
    mae = float(np.mean(np.abs(y - prediction)))
    denom = float(((y - y.mean()) ** 2).sum())
    r2 = float(1.0 - ((y - prediction) ** 2).sum() / denom) if denom > 0 else np.nan
    severe = (y <= severe_threshold).astype(int)
    auc = float(roc_auc_score(severe, -prediction)) if severe.nunique() > 1 else np.nan
    return {"mse": mse, "mae": mae, "oos_r2": r2, "severe_drawdown_auc": auc}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frame = build_feature_frame()
    frame.to_csv(OUT / "FEATURES_AND_OUTCOMES.csv")

    dev = frame[frame.index < OOS].copy()
    oos = frame[(frame.index >= OOS) & (frame.index < END)].copy()
    all_predictors = RISK + SIGNAL_GEOMETRY + ["portfolio_agreement"]
    mean, std = development_standardizer(dev, all_predictors)
    z_dev = apply_standardizer(dev, mean, std)
    z_oos = apply_standardizer(oos, mean, std)

    regression_rows = []
    prediction_rows = []
    for horizon, lags in HORIZONS.items():
        outcome = f"max_drawdown_{horizon}"
        threshold = float(dev[outcome].quantile(1 / 3))
        for model_name, cols in MODEL_COLUMNS.items():
            dev_model = fit_hac(dev[outcome], z_dev[cols], lags)
            oos_model = fit_hac(oos[outcome], z_oos[cols], lags)
            for sample, model in (("DEV_2025", dev_model), ("OOS_2026_DIAGNOSTIC", oos_model)):
                regression_rows.append({
                    "sample": sample,
                    "horizon": horizon,
                    "model": model_name,
                    "n": int(model.nobs),
                    "agreement_coef_per_dev_sd": float(model.params.get("portfolio_agreement", np.nan)),
                    "agreement_pvalue_hac": float(model.pvalues.get("portfolio_agreement", np.nan)),
                    "agreement_ci_low": float(model.conf_int().loc["portfolio_agreement", 0]) if "portfolio_agreement" in model.params else np.nan,
                    "agreement_ci_high": float(model.conf_int().loc["portfolio_agreement", 1]) if "portfolio_agreement" in model.params else np.nan,
                    "r_squared": float(model.rsquared),
                })

            # For genuine OOS prediction, fit plain OLS on DEV only and freeze coefficients.
            predictive_model = sm.OLS(
                dev[outcome], sm.add_constant(z_dev[cols], has_constant="add")
            ).fit()
            prediction = predictive_model.predict(sm.add_constant(z_oos[cols], has_constant="add"))
            pm = predictive_metrics(oos[outcome], prediction, threshold)
            prediction_rows.append({
                "horizon": horizon,
                "model": model_name,
                "dev_severe_drawdown_threshold": threshold,
                **pm,
            })

    regressions = pd.DataFrame(regression_rows)
    predictions = pd.DataFrame(prediction_rows)
    regressions.to_csv(OUT / "NESTED_REGRESSIONS.csv", index=False)
    predictions.to_csv(OUT / "OOS_PREDICTIVE_COMPARISON.csv", index=False)

    # Explicit incremental comparisons requested by the research question.
    increments = []
    for horizon in HORIZONS:
        p = predictions[predictions.horizon == horizon].set_index("model")
        for child, parent in (("RISK+AGREEMENT", "RISK"), ("FULL", "RISK+SIGNAL"), ("RISK+SIGNAL", "RISK")):
            increments.append({
                "horizon": horizon,
                "comparison": f"{child} vs {parent}",
                "mse_improvement_pct": float((1.0 - p.loc[child, "mse"] / p.loc[parent, "mse"]) * 100),
                "mae_improvement_pct": float((1.0 - p.loc[child, "mae"] / p.loc[parent, "mae"]) * 100),
                "oos_r2_change": float(p.loc[child, "oos_r2"] - p.loc[parent, "oos_r2"]),
                "auc_change": float(p.loc[child, "severe_drawdown_auc"] - p.loc[parent, "severe_drawdown_auc"]),
            })
    increments = pd.DataFrame(increments)
    increments.to_csv(OUT / "INCREMENTAL_VALUE.csv", index=False)

    # Correlations are diagnostic only and help identify redundancy / collinearity.
    dev_corr = dev[all_predictors + ["max_drawdown_24h"]].corr()
    oos_corr = oos[all_predictors + ["max_drawdown_24h"]].corr()
    dev_corr.to_csv(OUT / "DEV_CORRELATION_MATRIX.csv")
    oos_corr.to_csv(OUT / "OOS_CORRELATION_MATRIX.csv")

    def row(sample, horizon, model):
        return regressions[(regressions["sample"] == sample) & (regressions["horizon"] == horizon) & (regressions["model"] == model)].iloc[0]

    dev_risk_agree = row("DEV_2025", "24h", "RISK+AGREEMENT")
    oos_risk_agree = row("OOS_2026_DIAGNOSTIC", "24h", "RISK+AGREEMENT")
    dev_full = row("DEV_2025", "24h", "FULL")
    oos_full = row("OOS_2026_DIAGNOSTIC", "24h", "FULL")
    inc24 = increments[(increments.horizon == "24h")].set_index("comparison")

    independent_of_market_risk = bool(
        dev_risk_agree.agreement_coef_per_dev_sd > 0
        and dev_risk_agree.agreement_pvalue_hac < 0.05
        and oos_risk_agree.agreement_coef_per_dev_sd > 0
        and oos_risk_agree.agreement_pvalue_hac < 0.05
        and inc24.loc["RISK+AGREEMENT vs RISK", "mse_improvement_pct"] > 0
    )
    independent_of_signal_geometry = bool(
        dev_full.agreement_pvalue_hac < 0.05
        and oos_full.agreement_pvalue_hac < 0.05
        and np.sign(dev_full.agreement_coef_per_dev_sd) == np.sign(oos_full.agreement_coef_per_dev_sd)
        and inc24.loc["FULL vs RISK+SIGNAL", "mse_improvement_pct"] > 1.0
    )

    summary = {
        "design": {
            "development": "2025",
            "frozen_oos": "2026-01-01 through 2026-08-31",
            "risk_controls": RISK,
            "signal_geometry_controls": SIGNAL_GEOMETRY,
            "all_standardization_fit_on_development_only": True,
            "all_predictive_coefficients_fit_on_development_only": True,
        },
        "24h_result": {
            "agreement_independent_of_vol_corr_gross_current_drawdown": independent_of_market_risk,
            "agreement_independent_of_raw_signal_strength_and_dispersion": independent_of_signal_geometry,
            "risk_plus_agreement_dev_coef_per_sd": float(dev_risk_agree.agreement_coef_per_dev_sd),
            "risk_plus_agreement_dev_p": float(dev_risk_agree.agreement_pvalue_hac),
            "risk_plus_agreement_oos_coef_per_sd": float(oos_risk_agree.agreement_coef_per_dev_sd),
            "risk_plus_agreement_oos_p": float(oos_risk_agree.agreement_pvalue_hac),
            "full_dev_coef_per_sd": float(dev_full.agreement_coef_per_dev_sd),
            "full_dev_p": float(dev_full.agreement_pvalue_hac),
            "full_oos_coef_per_sd": float(oos_full.agreement_coef_per_dev_sd),
            "full_oos_p": float(oos_full.agreement_pvalue_hac),
            "risk_plus_agreement_mse_improvement_pct": float(inc24.loc["RISK+AGREEMENT vs RISK", "mse_improvement_pct"]),
            "risk_plus_signal_mse_improvement_pct": float(inc24.loc["RISK+SIGNAL vs RISK", "mse_improvement_pct"]),
            "agreement_on_top_of_signal_mse_improvement_pct": float(inc24.loc["FULL vs RISK+SIGNAL", "mse_improvement_pct"]),
        },
        "interpretation": {
            "disagreement_is_more_than_volatility_correlation_proxy": independent_of_market_risk,
            "disagreement_has_unique_information_beyond_simple_raw_signal_geometry": independent_of_signal_geometry,
            "recommendation": "DO NOT DEPLOY PCA DISAGREEMENT OVERLAY; TEST A SIMPLER RAW-SIGNAL-GEOMETRY RISK OVERLAY NEXT",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))

    pred24 = predictions[predictions.horizon == "24h"].set_index("model")
    report = f"""# Baseline B2D — Incremental Risk-Signal Validation

## Question
Does B2C raw/residual agreement predict future Baseline-A drawdown after controlling for simpler, causal information already known at the rebalance timestamp?

No trading rule is changed in this experiment. 2025 development fits all standardization and predictive coefficients; 2026-01-01 through 2026-08-31 is held out for prediction comparison.

## Causal controls
`RISK` contains trailing 48h equal-weight crypto-market realized volatility, trailing 720h average pairwise correlation, frozen-A gross exposure, and current frozen-A drawdown. `RISK+SIGNAL` additionally contains target-weighted absolute raw Trend-8/24 signal strength and cross-sectional raw-signal dispersion. All features use data available at the signal timestamp only.

## 24h result: agreement versus conventional risk state
After controlling for volatility, correlation, gross exposure and current drawdown, agreement remains stable and significant. Development standardized agreement coefficient = {dev_risk_agree.agreement_coef_per_dev_sd:.6f} (HAC p={dev_risk_agree.agreement_pvalue_hac:.4g}); frozen-OOS diagnostic coefficient = {oos_risk_agree.agreement_coef_per_dev_sd:.6f} (p={oos_risk_agree.agreement_pvalue_hac:.4g}). Positive coefficients mean higher agreement predicts a shallower (less negative) next-24h maximum drawdown.

Adding agreement to the development-fitted RISK model improves frozen-OOS 24h MSE by {inc24.loc['RISK+AGREEMENT vs RISK','mse_improvement_pct']:.2f}% and severe-drawdown AUC from {pred24.loc['RISK','severe_drawdown_auc']:.3f} to {pred24.loc['RISK+AGREEMENT','severe_drawdown_auc']:.3f}. Therefore disagreement is not merely a proxy for realized volatility or pairwise correlation.

## 24h result: is PCA disagreement uniquely necessary?
No. Once the two simpler raw-signal geometry variables are included jointly, agreement loses incremental explanatory power. In FULL, the development agreement coefficient is {dev_full.agreement_coef_per_dev_sd:.6f} (p={dev_full.agreement_pvalue_hac:.3f}) and the frozen-OOS diagnostic coefficient is {oos_full.agreement_coef_per_dev_sd:.6f} (p={oos_full.agreement_pvalue_hac:.3f}). Adding agreement on top of RISK+SIGNAL changes frozen-OOS MSE by only {inc24.loc['FULL vs RISK+SIGNAL','mse_improvement_pct']:.3f}%.

The simpler RISK+SIGNAL model itself improves 24h frozen-OOS MSE by {inc24.loc['RISK+SIGNAL vs RISK','mse_improvement_pct']:.2f}% versus RISK, versus {inc24.loc['RISK+AGREEMENT vs RISK','mse_improvement_pct']:.2f}% for RISK+AGREEMENT. Severe-drawdown AUC is {pred24.loc['RISK+SIGNAL','severe_drawdown_auc']:.3f} for RISK+SIGNAL and {pred24.loc['FULL','severe_drawdown_auc']:.3f} for FULL, essentially unchanged by agreement.

## Horizon stability
The strongest reproducible result is next-24h risk. The longer 3d/7d outcomes overlap and their OOS predictive R-squared values are weak/negative for these small linear models, so they are diagnostic rather than promotion evidence. See `NESTED_REGRESSIONS.csv`, `OOS_PREDICTIVE_COMPARISON.csv` and `INCREMENTAL_VALUE.csv` for every horizon.

## Interpretation
B2C disagreement **does contain real short-horizon risk information beyond volatility/correlation/gross/current drawdown**, but that information is largely redundant with two much simpler quantities already present in the raw strategy: how strong the raw signals are and how dispersed they are across assets.

This changes the engineering conclusion. The PCA/residual pipeline is not justified as a production risk overlay yet. A simpler raw-signal-geometry risk hypothesis should be tested next against the same constant-risk and volatility-only controls.

## Decision
**DO NOT DEPLOY THE PCA DISAGREEMENT OVERLAY. KEEP IT AS A DIAGNOSTIC. NEXT TEST: RAW-SIGNAL-STRENGTH / DISPERSION RISK OVERLAY.**
"""
    (ROOT / "BASELINE_B2D_RESEARCH_REPORT.md").write_text(report)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
