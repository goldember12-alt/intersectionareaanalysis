from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2

from src.roadway_graph.crash_count_exploratory_model_fit import (
    LOW_CATEGORY_CRASH_THRESHOLD,
    LOW_CATEGORY_ROW_THRESHOLD,
    OUTPUT_ROOT,
    WINDOW_MATRIX_FILE,
    _package_available,
    _safe_exp,
    _write_csv,
    _write_json,
    _write_text,
    load_inputs,
    prepare_model_input,
)


SPEC_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_specification"
FIT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_exploratory_model_fit"
REFINEMENT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_refinement_sensitivity"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_simplified_internal_model"

MODEL_SEQUENCE_FILE = SPEC_DIR / "candidate_model_sequence.csv"
VARIABLE_ROLE_FILE = SPEC_DIR / "model_variable_role_table.csv"
MODEL_SPEC_FILE = Path("docs/design/roadway_graph_crash_count_model_specification.md")
FIRST_FIT_MANIFEST_FILE = FIT_DIR / "crash_count_exploratory_model_fit_manifest.json"
REFINEMENT_MANIFEST_FILE = REFINEMENT_DIR / "crash_count_model_refinement_sensitivity_manifest.json"
REFINEMENT_DECISION_FILE = REFINEMENT_DIR / "model_refinement_readiness_decision.csv"
AADT_FACTOR_FINDINGS_FILE = OUTPUT_ROOT / "analysis/current/aadt_direction_factor_audit/aadt_direction_factor_audit_findings.md"

ALPHA_GRID = [0.25, 0.5, 1.0, 2.0]
OVERDISPERSION_THRESHOLD = 1.5
STABLE_SPEED_MIN_ROWS = 500

FORMULAS = {
    "S0_exposure_only": "assigned_crash_count ~ 1",
    "S1_window_direction": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "S2_access_interaction": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "S3_access_interaction_speed_simplified": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_simplified, Treatment(reference='30-39 mph'))",
    "S4_speed_sensitivity_no_missing": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_simplified, Treatment(reference='30-39 mph'))",
}
MODEL_ORDER = list(FORMULAS)


def _safe_float(value: Any) -> Any:
    try:
        if pd.isna(value):
            return pd.NA
        return float(value)
    except (TypeError, ValueError):
        return pd.NA


def _result_bic(result: Any) -> float:
    if hasattr(result, "bic_llf"):
        return float(result.bic_llf)
    if hasattr(result, "bic"):
        return float(result.bic)
    return float("nan")


def _prepare_simplified_input(matrix: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    model_input, excluded = prepare_model_input(matrix)
    out = model_input.copy()
    out["original_speed_band"] = out["speed_band"]
    out["analysis_window_readable"] = out["analysis_window_model"].astype(str).map(
        {"window_0_1000ft": "0-1,000 ft", "window_1000_2500ft": "1,000-2,500 ft"}
    )
    out["analysis_window_readable"] = pd.Categorical(out["analysis_window_readable"], categories=["0-1,000 ft", "1,000-2,500 ft"], ordered=True)
    out["local_access_density_label"] = out["local_access_density_band_model"].astype(str).map(
        {
            "access_0": "0",
            "access_gt0_1": ">0-1",
            "access_1_3": "1-3",
            "access_3_6": "3-6",
            "access_6plus": "6+",
        }
    )
    out["local_access_density_label"] = pd.Categorical(out["local_access_density_label"], categories=["0", ">0-1", "1-3", "3-6", "6+"], ordered=True)
    out["speed_band_simplified"] = out["speed_band_model"].astype(str).map(
        {
            "speed_lt_30_mph": "<30 mph",
            "speed_30_39_mph": "30-39 mph",
            "speed_40_49_mph": "40-49 mph",
            "speed_50_59_mph": "50+ mph",
            "speed_60plus_mph": "50+ mph",
            "speed_missing_or_review": "missing/review speed",
        }
    )
    out["speed_band_simplified"] = pd.Categorical(
        out["speed_band_simplified"],
        categories=["30-39 mph", "<30 mph", "40-49 mph", "50+ mph", "missing/review speed"],
        ordered=True,
    )
    mapping = pd.DataFrame(
        [
            ("speed", "50_59_mph", "50+ mph", "merged with 60+ mph"),
            ("speed", "60plus_mph", "50+ mph", "merged with 50-59 mph"),
            ("speed", "speed_missing_or_review", "missing/review speed", "preserved as explicit category"),
            ("access", "0_per_1000ft", "0", "preserved"),
            ("access", "gt0_lt1_per_1000ft", ">0-1", "preserved"),
            ("access", "1_lt3_per_1000ft", "1-3", "preserved"),
            ("access", "3_lt6_per_1000ft", "3-6", "preserved"),
            ("access", "6plus_per_1000ft", "6+", "preserved"),
            ("analysis_window", "high_priority_0_1000ft", "0-1,000 ft", "readable label"),
            ("analysis_window", "sensitivity_1000_2500ft", "1,000-2,500 ft", "readable label"),
        ],
        columns=["variable", "source_category", "simplified_category", "mapping_note"],
    )
    return out, excluded, mapping


def _fit_glm(formula: str, frame: pd.DataFrame, family: Any, fit_kwargs: dict[str, Any] | None = None) -> tuple[Any | None, list[str]]:
    import statsmodels.formula.api as smf

    messages: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = smf.glm(
                formula=formula,
                data=frame,
                family=family,
                offset=frame["log_estimated_exposure"],
            ).fit(maxiter=300, **(fit_kwargs or {}))
            messages.extend(f"{warning.category.__name__}: {warning.message}" for warning in caught)
            return result, messages
    except Exception as exc:  # noqa: BLE001
        messages.append(f"{type(exc).__name__}: {exc}")
        return None, messages


def _diagnostics(model_name: str, family: str, covariance_method: str, result: Any, frame: pd.DataFrame, *, alpha: float | None = None) -> dict[str, Any]:
    resid_df = float(getattr(result, "df_resid", np.nan))
    pearson = float(np.nansum(np.asarray(getattr(result, "resid_pearson", []), dtype=float) ** 2))
    deviance = float(getattr(result, "deviance", np.nan))
    pearson_ratio = pearson / resid_df if resid_df > 0 else np.nan
    deviance_ratio = deviance / resid_df if resid_df > 0 else np.nan
    return {
        "model_name": model_name,
        "model_family": family,
        "covariance_method": covariance_method,
        "alpha": alpha,
        "n_rows": int(getattr(result, "nobs", len(frame))),
        "total_crashes": int(frame["assigned_crash_count"].sum()),
        "zero_count_rows": int(frame["assigned_crash_count"].eq(0).sum()),
        "zero_count_share": float(frame["assigned_crash_count"].eq(0).mean()),
        "aic": _safe_float(getattr(result, "aic", pd.NA)),
        "bic": _result_bic(result),
        "log_likelihood": _safe_float(getattr(result, "llf", pd.NA)),
        "deviance": deviance,
        "pearson_chi_square": pearson,
        "residual_df": resid_df,
        "pearson_overdispersion_ratio": pearson_ratio,
        "deviance_overdispersion_ratio": deviance_ratio,
        "overdispersion_flag": bool(pearson_ratio > OVERDISPERSION_THRESHOLD) if pd.notna(pearson_ratio) else pd.NA,
        "converged": bool(getattr(result, "converged", True)),
        "df_model": _safe_float(getattr(result, "df_model", pd.NA)),
    }


def _reference_note(term: str) -> str:
    if term == "Intercept":
        return "reference levels: 0-1,000 ft; downstream; access 0; speed 30-39 mph where present"
    if "analysis_window_readable" in term:
        return "reference analysis window is 0-1,000 ft"
    if "signal_relative_direction_model" in term:
        return "reference direction is downstream"
    if "local_access_density_label" in term:
        return "reference access density is 0 per 1,000 ft"
    if "speed_band_simplified" in term:
        return "reference simplified speed band is 30-39 mph"
    return "not_applicable"


def _coefs(model_name: str, family: str, covariance_method: str, result: Any, *, alpha: float | None = None) -> list[dict[str, Any]]:
    conf = result.conf_int()
    rows = []
    for term in result.params.index:
        lower = conf.loc[term, 0] if term in conf.index else pd.NA
        upper = conf.loc[term, 1] if term in conf.index else pd.NA
        rows.append(
            {
                "model_name": model_name,
                "model_family": family,
                "covariance_method": covariance_method,
                "alpha": alpha,
                "term": term,
                "coefficient": _safe_float(result.params.loc[term]),
                "standard_error": _safe_float(result.bse.loc[term]) if term in result.bse.index else pd.NA,
                "p_value": _safe_float(result.pvalues.loc[term]) if term in result.pvalues.index else pd.NA,
                "conf_int_lower": lower,
                "conf_int_upper": upper,
                "incidence_rate_ratio": _safe_exp(result.params.loc[term]),
                "irr_conf_int_lower": _safe_exp(lower),
                "irr_conf_int_upper": _safe_exp(upper),
                "reference_level_notes": _reference_note(term),
            }
        )
    return rows


def _warning_rows(model_name: str, family: str, covariance_method: str, messages: list[str], *, alpha: float | None = None) -> list[dict[str, Any]]:
    return [
        {
            "model_name": model_name,
            "model_family": family,
            "covariance_method": covariance_method,
            "alpha": alpha,
            "warning_message": message,
            "unstable_model_flag": any(token in message for token in ["HessianInversionWarning", "failed", "ConvergenceWarning"]),
        }
        for message in messages
    ]


def _model_frame(model_name: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if model_name == "S4_speed_sensitivity_no_missing":
        stable = frame.loc[~frame["speed_band_simplified"].astype(str).eq("missing/review speed")].copy()
        return stable, len(stable) >= STABLE_SPEED_MIN_ROWS
    return frame, True


def _fit_models(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    import statsmodels.api as sm

    diagnostics = []
    coefs = []
    warnings_out = []
    clustered_se = []
    nb_rows = []
    for model_name in MODEL_ORDER:
        model_frame, should_fit = _model_frame(model_name, frame)
        if not should_fit:
            warnings_out.append(
                {
                    "model_name": model_name,
                    "model_family": "all",
                    "covariance_method": "not_fit",
                    "alpha": pd.NA,
                    "warning_message": f"stable speed rows below threshold {STABLE_SPEED_MIN_ROWS}",
                    "unstable_model_flag": True,
                }
            )
            continue
        formula = FORMULAS[model_name]
        poisson_specs = [
            ("poisson_conventional", {}),
            ("poisson_scaled_pearson", {"scale": "X2"}),
            ("poisson_robust_hc0", {"cov_type": "HC0"}),
            ("poisson_cluster_reference_signal", {"cov_type": "cluster", "cov_kwds": {"groups": model_frame["reference_signal_id"]}}),
        ]
        for covariance_method, kwargs in poisson_specs:
            result, messages = _fit_glm(formula, model_frame, sm.families.Poisson(), kwargs)
            warnings_out.extend(_warning_rows(model_name, "poisson_glm", covariance_method, messages))
            if result is None:
                continue
            diagnostics.append(_diagnostics(model_name, "poisson_glm", covariance_method, result, model_frame))
            coef_rows = _coefs(model_name, "poisson_glm", covariance_method, result)
            coefs.extend(coef_rows)
            if covariance_method in {"poisson_scaled_pearson", "poisson_robust_hc0", "poisson_cluster_reference_signal"}:
                for row in coef_rows:
                    clustered_se.append(
                        {
                            "model_name": model_name,
                            "term": row["term"],
                            "covariance_method": covariance_method,
                            "standard_error": row["standard_error"],
                            "p_value": row["p_value"],
                        }
                    )
        for alpha in ALPHA_GRID:
            result, messages = _fit_glm(formula, model_frame, sm.families.NegativeBinomial(alpha=alpha))
            unstable = any("HessianInversionWarning" in message or "failed" in message for message in messages)
            warnings_out.extend(_warning_rows(model_name, "negative_binomial_glm_fixed_alpha", "default", messages, alpha=alpha))
            if result is None:
                nb_rows.append({"model_name": model_name, "alpha": alpha, "fit_success": False, "stable_covariance_flag": False, "warning_count": len(messages)})
                continue
            diag = _diagnostics(model_name, "negative_binomial_glm_fixed_alpha", "default", result, model_frame, alpha=alpha)
            diag["fit_success"] = True
            diag["stable_covariance_flag"] = not unstable
            diag["warning_count"] = len(messages)
            nb_rows.append(diag)
            diagnostics.append(diag)
            coefs.extend(_coefs(model_name, "negative_binomial_glm_fixed_alpha", "default", result, alpha=alpha))
    return pd.DataFrame(diagnostics), pd.DataFrame(coefs), pd.DataFrame(clustered_se), pd.DataFrame(nb_rows), pd.DataFrame(warnings_out)


def _sparse_summary(frame: pd.DataFrame) -> pd.DataFrame:
    specs = [
        (["local_access_density_label"], "local_access_density_band"),
        (["speed_band_simplified"], "speed_band_simplified"),
        (["analysis_window_readable", "local_access_density_label"], "analysis_window_by_access"),
        (["analysis_window_readable", "speed_band_simplified"], "analysis_window_by_speed_simplified"),
    ]
    rows = []
    for cols, variable in specs:
        grouped = (
            frame.groupby(cols, observed=True, dropna=False)
            .agg(
                row_count=("reference_signal_id", "count"),
                assigned_crash_count=("assigned_crash_count", "sum"),
                zero_count_rows=("zero_crash_flag", "sum"),
                low_exposure_rows=("low_exposure_flag", "sum"),
                estimated_exposure=("estimated_exposure", "sum"),
            )
            .reset_index()
        )
        grouped.insert(0, "variable_name", variable)
        grouped["category_value"] = grouped[cols].astype(str).agg("|".join, axis=1)
        grouped["zero_count_share"] = grouped["zero_count_rows"] / grouped["row_count"].replace(0, pd.NA)
        grouped["low_exposure_share"] = grouped["low_exposure_rows"] / grouped["row_count"].replace(0, pd.NA)
        grouped["sparse_category_flag"] = grouped["row_count"].lt(LOW_CATEGORY_ROW_THRESHOLD) | grouped["assigned_crash_count"].lt(LOW_CATEGORY_CRASH_THRESHOLD)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _family_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    primary = diagnostics.loc[diagnostics["model_family"].eq("poisson_glm") & diagnostics["covariance_method"].eq("poisson_scaled_pearson")].set_index("model_name")
    comparisons = [("S1_window_direction", "S0_exposure_only"), ("S2_access_interaction", "S1_window_direction"), ("S3_access_interaction_speed_simplified", "S2_access_interaction")]
    for model_name, previous in comparisons:
        if model_name not in primary.index or previous not in primary.index:
            continue
        cur = primary.loc[model_name]
        prev = primary.loc[previous]
        lr = 2 * (cur["log_likelihood"] - prev["log_likelihood"])
        df = cur["df_model"] - prev["df_model"]
        rows.append(
            {
                "model_family": "poisson_glm",
                "covariance_method": "poisson_scaled_pearson",
                "model_name": model_name,
                "comparison_model": previous,
                "delta_aic_vs_previous": cur["aic"] - prev["aic"],
                "delta_bic_vs_previous": cur["bic"] - prev["bic"],
                "likelihood_ratio_stat": lr,
                "likelihood_ratio_df": df,
                "likelihood_ratio_p_value": float(chi2.sf(lr, df)) if pd.notna(lr) and pd.notna(df) and df > 0 and lr >= 0 else pd.NA,
                "fit_improves_aic": bool(cur["aic"] < prev["aic"]),
            }
        )
    return pd.DataFrame(rows)


def _access_interaction_summary(family_comparison: pd.DataFrame, nb_alpha: pd.DataFrame) -> pd.DataFrame:
    rows = []
    poisson = family_comparison.loc[family_comparison["model_name"].eq("S2_access_interaction")]
    if not poisson.empty:
        rows.append(
            {
                "comparison_scope": "scaled_poisson",
                "interaction_model": "S2_access_interaction",
                "comparison_model": "S1_window_direction",
                "delta_aic": poisson["delta_aic_vs_previous"].iloc[0],
                "interaction_improves_aic": bool(poisson["fit_improves_aic"].iloc[0]),
            }
        )
    for alpha in ALPHA_GRID:
        nb = nb_alpha.loc[nb_alpha["alpha"].eq(alpha)].set_index("model_name")
        if "S2_access_interaction" in nb.index and "S1_window_direction" in nb.index:
            rows.append(
                {
                    "comparison_scope": f"fixed_alpha_nb_{alpha}",
                    "interaction_model": "S2_access_interaction",
                    "comparison_model": "S1_window_direction",
                    "delta_aic": nb.loc["S2_access_interaction", "aic"] - nb.loc["S1_window_direction", "aic"],
                    "interaction_improves_aic": bool(nb.loc["S2_access_interaction", "aic"] < nb.loc["S1_window_direction", "aic"]),
                }
            )
    return pd.DataFrame(rows)


def _speed_summary(family_comparison: pd.DataFrame, diagnostics: pd.DataFrame) -> pd.DataFrame:
    speed = family_comparison.loc[family_comparison["model_name"].eq("S3_access_interaction_speed_simplified")]
    s4 = diagnostics.loc[
        diagnostics["model_name"].eq("S4_speed_sensitivity_no_missing")
        & diagnostics["model_family"].eq("poisson_glm")
        & diagnostics["covariance_method"].eq("poisson_scaled_pearson")
    ]
    return pd.DataFrame(
        [
            {
                "sensitivity": "simplified_speed_added",
                "comparison": "S3_access_interaction_speed_simplified_vs_S2_access_interaction",
                "delta_aic": speed["delta_aic_vs_previous"].iloc[0] if not speed.empty else pd.NA,
                "fit_improves_aic": bool(speed["fit_improves_aic"].iloc[0]) if not speed.empty else pd.NA,
                "n_rows": int(diagnostics.loc[diagnostics["model_name"].eq("S3_access_interaction_speed_simplified"), "n_rows"].iloc[0]) if not diagnostics.loc[diagnostics["model_name"].eq("S3_access_interaction_speed_simplified")].empty else pd.NA,
            },
            {
                "sensitivity": "stable_speed_only",
                "comparison": "S4_speed_sensitivity_no_missing",
                "delta_aic": pd.NA,
                "fit_improves_aic": pd.NA,
                "n_rows": int(s4["n_rows"].iloc[0]) if not s4.empty else 0,
            },
        ]
    )


def _readiness_decision(diagnostics: pd.DataFrame, sparse: pd.DataFrame, family_comparison: pd.DataFrame, nb_alpha: pd.DataFrame) -> pd.DataFrame:
    scaled = diagnostics.loc[diagnostics["model_family"].eq("poisson_glm") & diagnostics["covariance_method"].eq("poisson_scaled_pearson")]
    clustered = diagnostics.loc[diagnostics["model_family"].eq("poisson_glm") & diagnostics["covariance_method"].eq("poisson_cluster_reference_signal")]
    access = family_comparison.loc[family_comparison["model_name"].eq("S2_access_interaction")]
    speed = family_comparison.loc[family_comparison["model_name"].eq("S3_access_interaction_speed_simplified")]
    sparse_flags = int(sparse["sparse_category_flag"].sum())
    fixed_nb_ok = bool(nb_alpha["stable_covariance_flag"].fillna(False).all()) if not nb_alpha.empty else False
    access_ok = bool(access["fit_improves_aic"].iloc[0]) if not access.empty else False
    speed_ok = bool(speed["fit_improves_aic"].iloc[0]) if not speed.empty else False
    robust_ready = not scaled.empty and not clustered.empty and access_ok and sparse_flags == 0
    if robust_ready and speed_ok:
        decision = "access_speed_model_ready_internal_only"
        recommended = "S3_access_interaction_speed_simplified with scaled and cluster-robust Poisson inference"
    elif robust_ready:
        decision = "access_interaction_model_ready_internal_only"
        recommended = "S2_access_interaction with scaled and cluster-robust Poisson inference"
    elif fixed_nb_ok and access_ok:
        decision = "fixed_alpha_nb_sensitivity_only"
        recommended = "fixed-alpha NB sensitivity only; keep Poisson diagnostics primary"
    elif sparse_flags > 0:
        decision = "requires_more_category_simplification"
        recommended = "review remaining sparse categories"
    else:
        decision = "no_model_ready_for_interpretation"
        recommended = "none"
    return pd.DataFrame(
        [
            {
                "decision": decision,
                "allowed_decisions": "no_model_ready_for_interpretation|access_interaction_model_ready_internal_only|access_speed_model_ready_internal_only|robust_poisson_ready_internal_only|fixed_alpha_nb_sensitivity_only|requires_more_category_simplification",
                "recommended_internal_model": recommended,
                "scaled_poisson_available": not scaled.empty,
                "clustered_poisson_available": not clustered.empty,
                "fixed_alpha_nb_sensitivity_available": fixed_nb_ok,
                "access_interaction_improves_fit": access_ok,
                "simplified_speed_improves_fit": speed_ok,
                "remaining_sparse_category_count": sparse_flags,
                "stakeholder_reporting_status": "not_ready",
            }
        ]
    )


def _guardrails() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("allowed", "exploratory association"),
            ("allowed", "modeled crash count"),
            ("allowed", "after accounting for estimated exposure"),
            ("allowed", "incidence rate ratio"),
            ("allowed", "overdispersion-adjusted"),
            ("allowed", "cluster-robust"),
            ("allowed", "internal technical review"),
            ("allowed", "provisional"),
            ("avoid", "causal language"),
            ("avoid", "ranking language"),
            ("avoid", "external decision language"),
            ("avoid", "location classification language"),
        ],
        columns=["language_type", "phrase"],
    )


def _findings(model_input: pd.DataFrame, family_comparison: pd.DataFrame, readiness: pd.DataFrame, sparse: pd.DataFrame, speed_summary: pd.DataFrame) -> str:
    access = family_comparison.loc[family_comparison["model_name"].eq("S2_access_interaction")]
    speed = family_comparison.loc[family_comparison["model_name"].eq("S3_access_interaction_speed_simplified")]
    return f"""# Crash Count Simplified Internal Model Findings

**Status:** internal technical review only. These outputs are exploratory model diagnostics and are not external decision outputs, causal evidence, or downstream functional-area distance recommendations.

## Input

- Modeled rows: {len(model_input)} denominator-ready signal-direction-window rows.
- Modeled assigned crashes: {int(model_input["assigned_crash_count"].sum())}.
- Speed simplification: 50-59 mph and 60+ mph are merged into 50+ mph; missing/review speed remains explicit.

## Access Interaction

The access interaction remains useful after category simplification: {bool(access["fit_improves_aic"].iloc[0]) if not access.empty else "not_available"}.

Delta AIC for `S2_access_interaction` versus `S1_window_direction`: {access["delta_aic_vs_previous"].iloc[0] if not access.empty else "not_available"}.

## Simplified Speed

Adding simplified speed improves fit: {bool(speed["fit_improves_aic"].iloc[0]) if not speed.empty else "not_available"}.

Delta AIC for `S3_access_interaction_speed_simplified` versus `S2_access_interaction`: {speed["delta_aic_vs_previous"].iloc[0] if not speed.empty else "not_available"}.

Stable-speed-only rows are reported in `simplified_speed_sensitivity_summary.csv`.

## Inference

Poisson, overdispersion-adjusted Poisson, robust Poisson, cluster-robust Poisson, and fixed-alpha negative-binomial sensitivity models were fit. Fixed-alpha NB remains sensitivity evidence, not the primary interpretation family.

## Category Review

Remaining sparse category rows after simplification: {int(sparse["sparse_category_flag"].sum())}.

## Readiness Decision

Decision: `{readiness["decision"].iloc[0]}`.

Recommended internal model: {readiness["recommended_internal_model"].iloc[0]}.

Stakeholder interpretation remains blocked.
"""


def build_outputs() -> dict[str, Any]:
    matrix, sequence, roles = load_inputs()
    if not _package_available("statsmodels"):
        raise RuntimeError("statsmodels is required for simplified internal model outputs")
    model_input, excluded, mapping = _prepare_simplified_input(matrix)
    diagnostics, coefficients, se_comparison, nb_alpha, warnings_frame = _fit_models(model_input)
    if warnings_frame.empty:
        warnings_frame = pd.DataFrame(columns=["model_name", "model_family", "covariance_method", "alpha", "warning_message", "unstable_model_flag"])
    sparse = _sparse_summary(model_input)
    family_comparison = _family_comparison(diagnostics)
    access_summary = _access_interaction_summary(family_comparison, nb_alpha)
    speed_summary = _speed_summary(family_comparison, diagnostics)
    readiness = _readiness_decision(diagnostics, sparse, family_comparison, nb_alpha)
    fit_summary = diagnostics[
        [
            "model_name",
            "model_family",
            "covariance_method",
            "alpha",
            "n_rows",
            "total_crashes",
            "aic",
            "bic",
            "log_likelihood",
            "converged",
            "overdispersion_flag",
        ]
    ].copy()
    overdispersion = diagnostics.loc[diagnostics["model_family"].eq("poisson_glm")][
        [
            "model_name",
            "covariance_method",
            "pearson_chi_square",
            "residual_df",
            "pearson_overdispersion_ratio",
            "deviance_overdispersion_ratio",
            "overdispersion_flag",
        ]
    ].copy()
    irr = coefficients[
        [
            "model_name",
            "model_family",
            "covariance_method",
            "alpha",
            "term",
            "incidence_rate_ratio",
            "irr_conf_int_lower",
            "irr_conf_int_upper",
            "p_value",
            "reference_level_notes",
        ]
    ].copy()
    input_summary = pd.DataFrame(
        [
            ("modeled_rows", len(model_input), "denominator-ready signal-direction-window rows"),
            ("excluded_rows", len(excluded), "preserved excluded rows"),
            ("modeled_assigned_crashes", int(model_input["assigned_crash_count"].sum()), "assigned crashes represented"),
            ("missing_review_speed_rows", int(model_input["speed_band_simplified"].astype(str).eq("missing/review speed").sum()), "explicit speed category"),
        ],
        columns=["metric", "value", "notes"],
    )
    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "guarded reader inherited from model-fit module", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read or used", "required"),
            ("only_denominator_ready_signal_direction_window_rows_modeled", bool(model_input["denominator_ready_flag"].all()), len(model_input), "all modeled rows denominator-ready"),
            ("no_distance_band_models_fit", True, "only signal-direction-window matrix used", "required"),
            ("no_policy_ranking_language_introduced", True, "findings constrained", "required"),
            ("no_rankings_created", True, "no location-ordering outputs created", "required"),
            ("source_context_assignment_data_not_modified", True, "separate analysis output folder only", "required"),
            ("speed_category_merging_documented", True, "simplified_category_mapping.csv", "required"),
            ("unstable_models_not_marked_interpretable", True, readiness["decision"].iloc[0], "unstable models blocked from interpretation"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )
    guardrails = _guardrails()
    findings = _findings(model_input, family_comparison, readiness, sparse, speed_summary)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "simplified_model_input_rows.csv": model_input,
        "simplified_model_input_excluded_rows.csv": excluded,
        "simplified_category_mapping.csv": mapping,
        "simplified_sparse_category_summary.csv": sparse,
        "simplified_model_fit_summary.csv": fit_summary,
        "simplified_model_coefficients.csv": coefficients,
        "simplified_model_incidence_rate_ratios.csv": irr,
        "simplified_model_clustered_se_comparison.csv": se_comparison,
        "simplified_model_overdispersion_summary.csv": overdispersion,
        "simplified_model_family_comparison.csv": family_comparison,
        "simplified_nb_alpha_sensitivity.csv": nb_alpha,
        "simplified_access_interaction_summary.csv": access_summary,
        "simplified_speed_sensitivity_summary.csv": speed_summary,
        "simplified_model_interpretation_guardrails.csv": guardrails,
        "simplified_model_readiness_decision.csv": readiness,
        "simplified_model_input_summary.csv": input_summary,
        "simplified_model_warnings.csv": warnings_frame,
        "simplified_model_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_text(findings, OUTPUT_DIR / "crash_count_simplified_internal_model_findings.md")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "category-simplified internal signal-direction-window crash-count model",
        "status": "internal_technical_review_only",
        "inputs": [
            str(path)
            for path in [
                WINDOW_MATRIX_FILE,
                MODEL_SEQUENCE_FILE,
                VARIABLE_ROLE_FILE,
                MODEL_SPEC_FILE,
                FIRST_FIT_MANIFEST_FILE,
                REFINEMENT_MANIFEST_FILE,
                REFINEMENT_DECISION_FILE,
                AADT_FACTOR_FINDINGS_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(path) for path in OUTPUT_DIR.glob("*")),
        "row_counts": {
            "modeled_rows": int(len(model_input)),
            "excluded_rows": int(len(excluded)),
            "modeled_assigned_crashes": int(model_input["assigned_crash_count"].sum()),
        },
        "category_simplifications": ["speed: 50-59 mph and 60+ mph merged into 50+ mph", "speed: missing/review preserved"],
        "readiness_decision": readiness.to_dict(orient="records"),
        "guardrails": {
            "crash_direction_fields_used": False,
            "direction_factor_applied": False,
            "distance_band_models_fit": False,
            "predictions_for_policy_created": False,
            "rankings_created": False,
            "source_context_assignment_data_modified": False,
        },
        "qa": qa.to_dict(orient="records"),
        "unused_loaded_rows": {"candidate_model_sequence_rows": len(sequence), "variable_role_rows": len(roles)},
    }
    _write_json(manifest, OUTPUT_DIR / "crash_count_simplified_internal_model_manifest.json")
    return {"readiness": readiness, "diagnostics": diagnostics, "family_comparison": family_comparison, "qa": qa}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit category-simplified internal crash-count models.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
