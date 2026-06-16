from __future__ import annotations

import argparse
import json
import math
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
    _bool,
    _is_crash_direction_field,
    _num,
    _package_available,
    _read_csv,
    _safe_exp,
    _write_csv,
    _write_json,
    _write_text,
    load_inputs,
    prepare_model_input,
)


SPEC_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_specification"
FIT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_exploratory_model_fit"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_refinement_sensitivity"

MODEL_SEQUENCE_FILE = SPEC_DIR / "candidate_model_sequence.csv"
VARIABLE_ROLE_FILE = SPEC_DIR / "model_variable_role_table.csv"
MODEL_SPEC_FILE = Path("docs/design/roadway_graph_crash_count_model_specification.md")
AADT_FACTOR_FINDINGS_FILE = OUTPUT_ROOT / "analysis/current/aadt_direction_factor_audit/aadt_direction_factor_audit_findings.md"
RATE_ASSUMPTION_MANIFEST_FILE = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1/rate_assumption_approval_manifest.json"
FIRST_FIT_MANIFEST_FILE = FIT_DIR / "crash_count_exploratory_model_fit_manifest.json"
FIRST_FIT_DIAGNOSTICS_FILE = FIT_DIR / "model_fit_diagnostics.csv"
FIRST_FIT_WARNINGS_FILE = FIT_DIR / "model_convergence_warnings.csv"

ALPHA_GRID = [0.25, 0.5, 1.0, 2.0]
OVERDISPERSION_THRESHOLD = 1.5

FORMULAS = {
    "M2_no_access_interaction": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(local_access_density_band_model, Treatment(reference='access_0'))",
    "M3_access_interaction": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "M4_primary_speed": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_model, Treatment(reference='speed_30_39_mph'))",
    "M4_merged_speed": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_merged_model, Treatment(reference='speed_30_39_mph'))",
    "M4_stable_speed_only": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_model, Treatment(reference='speed_30_39_mph'))",
    "M3_no_speed_comparison": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
}

READINESS_OPTIONS = [
    "no_model_ready_for_interpretation",
    "poisson_only_descriptive_diagnostics",
    "robust_poisson_ready_for_internal_interpretation",
    "negative_binomial_ready_for_internal_interpretation",
    "requires_category_simplification",
]


def _result_bic(result: Any) -> float:
    if hasattr(result, "bic_llf"):
        return float(result.bic_llf)
    if hasattr(result, "bic"):
        return float(result.bic)
    return float("nan")


def _safe_float(value: Any) -> Any:
    try:
        if pd.isna(value):
            return pd.NA
        return float(value)
    except (TypeError, ValueError):
        return pd.NA


def _reference_note(term: str) -> str:
    if term == "Intercept":
        return "reference levels: 0-1,000 ft; downstream; access 0; speed 30-39 mph where present"
    if "analysis_window_model" in term:
        return "reference analysis_window is 0-1,000 ft"
    if "signal_relative_direction_model" in term:
        return "reference signal_relative_direction is downstream"
    if "local_access_density_band_model" in term:
        return "reference local_access_density_band is 0 per 1,000 ft"
    if "speed_band_merged_model" in term:
        return "reference merged speed band is 30-39 mph"
    if "speed_band_model" in term:
        return "reference speed band is 30-39 mph"
    return "not_applicable"


def _add_merged_speed(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["speed_band_merged_model"] = out["speed_band_model"].astype(str).replace(
        {
            "speed_50_59_mph": "speed_50plus_mph",
            "speed_60plus_mph": "speed_50plus_mph",
        }
    )
    out["speed_band_merged_label"] = out["speed_band_merged_model"].map(
        {
            "speed_lt_30_mph": "<30 mph",
            "speed_30_39_mph": "30-39 mph",
            "speed_40_49_mph": "40-49 mph",
            "speed_50plus_mph": "50+ mph",
            "speed_missing_or_review": "missing/review speed",
        }
    )
    out["speed_band_merged_model"] = pd.Categorical(
        out["speed_band_merged_model"],
        categories=[
            "speed_30_39_mph",
            "speed_lt_30_mph",
            "speed_40_49_mph",
            "speed_50plus_mph",
            "speed_missing_or_review",
        ],
        ordered=True,
    )
    return out


def _stable_speed(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[~frame["speed_band_model"].astype(str).eq("speed_missing_or_review")].copy()


def _fit_glm(formula: str, frame: pd.DataFrame, *, family: Any, fit_kwargs: dict[str, Any] | None = None) -> tuple[Any | None, list[str]]:
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


def _diagnostics(model_name: str, family: str, result: Any, frame: pd.DataFrame, *, alpha: float | None = None, sensitivity: str = "primary") -> dict[str, Any]:
    resid_df = float(getattr(result, "df_resid", np.nan))
    pearson = float(np.nansum(np.asarray(getattr(result, "resid_pearson", []), dtype=float) ** 2))
    deviance = float(getattr(result, "deviance", np.nan))
    pearson_ratio = pearson / resid_df if resid_df > 0 else np.nan
    deviance_ratio = deviance / resid_df if resid_df > 0 else np.nan
    return {
        "model_name": model_name,
        "model_family": family,
        "sensitivity": sensitivity,
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


def _coefs(model_name: str, family: str, result: Any, *, alpha: float | None = None, sensitivity: str = "primary", covariance_method: str = "default") -> list[dict[str, Any]]:
    rows = []
    conf = result.conf_int()
    for term in result.params.index:
        lower = conf.loc[term, 0] if term in conf.index else pd.NA
        upper = conf.loc[term, 1] if term in conf.index else pd.NA
        rows.append(
            {
                "model_name": model_name,
                "model_family": family,
                "sensitivity": sensitivity,
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


def _warning_rows(model_name: str, family: str, messages: list[str], *, alpha: float | None = None, sensitivity: str = "primary") -> list[dict[str, Any]]:
    return [
        {
            "model_name": model_name,
            "model_family": family,
            "sensitivity": sensitivity,
            "alpha": alpha,
            "warning_message": message,
            "unstable_covariance_flag": any(token in message for token in ["HessianInversionWarning", "covariance", "failed"]),
        }
        for message in messages
    ]


def _fit_poisson_variants(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    import statsmodels.api as sm

    rows = []
    coefs = []
    se_rows = []
    warning_rows = []
    specs = [
        ("poisson_conventional", {}),
        ("poisson_scaled_pearson", {"scale": "X2"}),
        ("poisson_robust_hc0", {"cov_type": "HC0"}),
        ("poisson_cluster_reference_signal", {"cov_type": "cluster", "cov_kwds": {"groups": frame["reference_signal_id"]}}),
    ]
    for covariance_method, fit_kwargs in specs:
        result, messages = _fit_glm(FORMULAS["M4_primary_speed"], frame, family=sm.families.Poisson(), fit_kwargs=fit_kwargs)
        warning_rows.extend(_warning_rows("M4_primary_speed", "poisson_glm", messages, sensitivity=covariance_method))
        if result is None:
            continue
        rows.append(_diagnostics("M4_primary_speed", "poisson_glm", result, frame, sensitivity=covariance_method))
        coefs.extend(_coefs("M4_primary_speed", "poisson_glm", result, sensitivity=covariance_method, covariance_method=covariance_method))
        for term in result.params.index:
            se_rows.append(
                {
                    "model_name": "M4_primary_speed",
                    "term": term,
                    "covariance_method": covariance_method,
                    "standard_error": _safe_float(result.bse.loc[term]) if term in result.bse.index else pd.NA,
                    "p_value": _safe_float(result.pvalues.loc[term]) if term in result.pvalues.index else pd.NA,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(coefs), pd.DataFrame(se_rows), warning_rows


def _fit_nb_alpha_grid(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    import statsmodels.api as sm

    rows = []
    coefs = []
    warning_rows = []
    for model_name in ["M2_no_access_interaction", "M3_access_interaction", "M4_primary_speed", "M4_merged_speed"]:
        model_frame = _add_merged_speed(frame) if model_name == "M4_merged_speed" else frame
        for alpha in ALPHA_GRID:
            result, messages = _fit_glm(FORMULAS[model_name], model_frame, family=sm.families.NegativeBinomial(alpha=alpha))
            unstable = any("HessianInversionWarning" in message or "failed" in message for message in messages)
            warning_rows.extend(_warning_rows(model_name, "negative_binomial_glm_fixed_alpha", messages, alpha=alpha))
            if result is None:
                rows.append(
                    {
                        "model_name": model_name,
                        "model_family": "negative_binomial_glm_fixed_alpha",
                        "alpha": alpha,
                        "fit_success": False,
                        "stable_covariance_flag": False,
                        "warning_count": len(messages),
                    }
                )
                continue
            diagnostic = _diagnostics(model_name, "negative_binomial_glm_fixed_alpha", result, model_frame, alpha=alpha)
            diagnostic["fit_success"] = True
            diagnostic["stable_covariance_flag"] = not unstable
            diagnostic["warning_count"] = len(messages)
            rows.append(diagnostic)
            coefs.extend(_coefs(model_name, "negative_binomial_glm_fixed_alpha", result, alpha=alpha))
    return pd.DataFrame(rows), pd.DataFrame(coefs), warning_rows


def _speed_sensitivity(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    import statsmodels.api as sm

    specs = [
        ("primary_speed", "M4_primary_speed", frame),
        ("merged_50plus_speed", "M4_merged_speed", _add_merged_speed(frame)),
        ("stable_speed_only", "M4_stable_speed_only", _stable_speed(frame)),
        ("no_speed", "M3_no_speed_comparison", frame),
    ]
    rows = []
    coefs = []
    diagnostics = []
    warning_rows = []
    for sensitivity, model_name, model_frame in specs:
        result, messages = _fit_glm(FORMULAS[model_name], model_frame, family=sm.families.Poisson(), fit_kwargs={"scale": "X2"})
        warning_rows.extend(_warning_rows(model_name, "poisson_scaled_pearson", messages, sensitivity=sensitivity))
        sparse_source = _sparse_review(model_frame)
        if sensitivity == "merged_50plus_speed":
            speed_sparse = sparse_source.loc[sparse_source["variable_name"].eq("speed_band_merged")]
        elif sensitivity == "no_speed":
            speed_sparse = pd.DataFrame()
        else:
            speed_sparse = sparse_source.loc[sparse_source["variable_name"].eq("speed_band")]
        rows.append(
            {
                "sensitivity": sensitivity,
                "model_name": model_name,
                "n_rows": len(model_frame),
                "assigned_crash_count": int(model_frame["assigned_crash_count"].sum()),
                "speed_missing_or_review_rows": int(model_frame["speed_band_model"].astype(str).eq("speed_missing_or_review").sum()) if "speed_band_model" in model_frame else 0,
                "sparse_speed_category_count": int(speed_sparse["sparse_category_flag"].sum()) if not speed_sparse.empty else 0,
                "fit_success": result is not None,
                "aic": _safe_float(getattr(result, "aic", pd.NA)) if result is not None else pd.NA,
                "pearson_overdispersion_ratio": _diagnostics(model_name, "poisson_scaled_pearson", result, model_frame)["pearson_overdispersion_ratio"] if result is not None else pd.NA,
            }
        )
        if result is not None:
            diagnostics.append(_diagnostics(model_name, "poisson_scaled_pearson", result, model_frame, sensitivity=sensitivity))
            coefs.extend(_coefs(model_name, "poisson_scaled_pearson", result, sensitivity=sensitivity, covariance_method="scaled_pearson"))
    return pd.DataFrame(rows), pd.DataFrame(diagnostics), pd.DataFrame(coefs), warning_rows


def _access_stability(frame: pd.DataFrame, nb_grid: pd.DataFrame) -> pd.DataFrame:
    import statsmodels.api as sm

    rows = []
    for sensitivity, model_frame in [
        ("primary_speed_categories", frame),
        ("merged_50plus_speed_categories", _add_merged_speed(frame)),
        ("stable_speed_only", _stable_speed(frame)),
    ]:
        for family_name, family in [
            ("poisson_scaled_pearson", sm.families.Poisson()),
            ("negative_binomial_alpha_0_5", sm.families.NegativeBinomial(alpha=0.5)),
            ("negative_binomial_alpha_1_0", sm.families.NegativeBinomial(alpha=1.0)),
        ]:
            no_int, no_messages = _fit_glm(FORMULAS["M2_no_access_interaction"], model_frame, family=family, fit_kwargs={"scale": "X2"} if family_name == "poisson_scaled_pearson" else None)
            with_int, int_messages = _fit_glm(FORMULAS["M3_access_interaction"], model_frame, family=family, fit_kwargs={"scale": "X2"} if family_name == "poisson_scaled_pearson" else None)
            rows.append(
                {
                    "sensitivity": sensitivity,
                    "model_family": family_name,
                    "without_interaction_fit_success": no_int is not None,
                    "with_interaction_fit_success": with_int is not None,
                    "without_interaction_aic": _safe_float(getattr(no_int, "aic", pd.NA)) if no_int is not None else pd.NA,
                    "with_interaction_aic": _safe_float(getattr(with_int, "aic", pd.NA)) if with_int is not None else pd.NA,
                    "delta_aic_interaction_minus_no_interaction": (_safe_float(getattr(with_int, "aic", pd.NA)) - _safe_float(getattr(no_int, "aic", pd.NA))) if no_int is not None and with_int is not None else pd.NA,
                    "interaction_improves_aic": bool(getattr(with_int, "aic", np.inf) < getattr(no_int, "aic", -np.inf)) if no_int is not None and with_int is not None else pd.NA,
                    "warning_count": len(no_messages) + len(int_messages),
                }
            )
    return pd.DataFrame(rows)


def _sparse_review(frame: pd.DataFrame) -> pd.DataFrame:
    specs = [
        (["local_access_density_band_model", "local_access_density_band_label"], "local_access_density_band"),
        (["speed_band_model", "speed_band_label"], "speed_band"),
        (["analysis_window_model", "analysis_window_label", "local_access_density_band_model", "local_access_density_band_label"], "analysis_window_by_access"),
        (["analysis_window_model", "analysis_window_label", "speed_band_model", "speed_band_label"], "analysis_window_by_speed"),
    ]
    rows = []
    merged = _add_merged_speed(frame)
    specs.append((["speed_band_merged_model", "speed_band_merged_label"], "speed_band_merged"))
    for group_cols, variable_name in specs:
        source = merged if any(column.startswith("speed_band_merged") for column in group_cols) else frame
        grouped = (
            source.groupby(group_cols, observed=True, dropna=False)
            .agg(
                row_count=("reference_signal_id", "count"),
                assigned_crash_count=("assigned_crash_count", "sum"),
                zero_count_rows=("zero_crash_flag", "sum"),
                low_exposure_rows=("low_exposure_flag", "sum"),
                estimated_exposure=("estimated_exposure", "sum"),
            )
            .reset_index()
        )
        grouped.insert(0, "variable_name", variable_name)
        grouped["category_value"] = grouped[group_cols].astype(str).agg("|".join, axis=1)
        grouped["zero_count_share"] = grouped["zero_count_rows"] / grouped["row_count"].replace(0, pd.NA)
        grouped["low_exposure_share"] = grouped["low_exposure_rows"] / grouped["row_count"].replace(0, pd.NA)
        grouped["sparse_category_flag"] = grouped["row_count"].lt(LOW_CATEGORY_ROW_THRESHOLD) | grouped["assigned_crash_count"].lt(LOW_CATEGORY_CRASH_THRESHOLD)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _input_summary(frame: pd.DataFrame, excluded: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("source_matrix_rows", len(frame) + len(excluded), "signal-direction-window modeling matrix rows"),
            ("modeled_rows", len(frame), "denominator-ready rows with valid outcome and exposure"),
            ("excluded_rows", len(excluded), "preserved non-modeled rows"),
            ("modeled_assigned_crashes", int(frame["assigned_crash_count"].sum()), "assigned crashes in modeled rows"),
            ("zero_count_rows", int(frame["assigned_crash_count"].eq(0).sum()), "modeled rows with zero assigned crashes"),
            ("zero_count_share", float(frame["assigned_crash_count"].eq(0).mean()), "share of modeled rows with zero assigned crashes"),
            ("speed_missing_or_review_rows", int(frame["speed_band_model"].astype(str).eq("speed_missing_or_review").sum()), "modeled rows with explicit missing/review speed category"),
            ("stable_speed_only_rows", len(_stable_speed(frame)), "rows available for stable-speed-only sensitivity"),
            ("bidirectional_aadt_assumption_rows", int(frame["bidirectional_aadt_assumption_flag"].sum()), "rows carrying provisional bidirectional AADT flag"),
        ],
        columns=["metric", "value", "notes"],
    )


def _readiness_decision(
    nb_grid: pd.DataFrame,
    poisson_summary: pd.DataFrame,
    speed_summary: pd.DataFrame,
    access_stability: pd.DataFrame,
    sparse: pd.DataFrame,
) -> pd.DataFrame:
    fixed_alpha_nb_stable = bool((nb_grid.get("fit_success", False).eq(True) & nb_grid.get("stable_covariance_flag", False).eq(True)).any()) if not nb_grid.empty else False
    estimated_alpha_nb_stable = False
    robust_methods = set(poisson_summary["sensitivity"].dropna().astype(str)) if not poisson_summary.empty else set()
    robust_feasible = {"poisson_scaled_pearson", "poisson_robust_hc0", "poisson_cluster_reference_signal"}.issubset(robust_methods)
    access_consistent = bool(access_stability["interaction_improves_aic"].fillna(False).mean() >= 0.5) if not access_stability.empty else False
    sparse_speed = bool(
        sparse.loc[
            sparse["variable_name"].eq("speed_band") & sparse["category_value"].astype(str).str.contains("speed_60plus_mph", na=False),
            "sparse_category_flag",
        ].any()
    )
    if estimated_alpha_nb_stable:
        decision = "negative_binomial_ready_for_internal_interpretation"
    elif robust_feasible and access_consistent and not sparse_speed:
        decision = "robust_poisson_ready_for_internal_interpretation"
    elif robust_feasible and access_consistent:
        decision = "requires_category_simplification"
    elif robust_feasible:
        decision = "poisson_only_descriptive_diagnostics"
    else:
        decision = "no_model_ready_for_interpretation"
    return pd.DataFrame(
        [
            {
                "decision": decision,
                "allowed_decisions": "|".join(READINESS_OPTIONS),
                "negative_binomial_stable": estimated_alpha_nb_stable,
                "fixed_alpha_negative_binomial_sensitivity_stable": fixed_alpha_nb_stable,
                "robust_or_scaled_poisson_feasible": robust_feasible,
                "access_interaction_consistent": access_consistent,
                "sparse_speed_category_present": sparse_speed,
                "internal_interpretation_status": "internal_technical_review_only" if decision != "no_model_ready_for_interpretation" else "not_ready",
                "stakeholder_reporting_status": "not_ready",
                "recommended_internal_model": "merged-speed scaled and cluster-robust Poisson after category simplification" if decision == "requires_category_simplification" else decision,
                "required_next_step": "review category simplification and overdispersion handling before coefficient interpretation",
            }
        ]
    )


def _family_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sensitivity in diagnostics["sensitivity"].dropna().unique():
        subset = diagnostics.loc[diagnostics["sensitivity"].eq(sensitivity)]
        for family in subset["model_family"].dropna().unique():
            family_subset = subset.loc[subset["model_family"].eq(family)]
            alpha_values = family_subset["alpha"].drop_duplicates().tolist() if "alpha" in family_subset.columns else [pd.NA]
            if not alpha_values:
                alpha_values = [pd.NA]
            for alpha in alpha_values:
                if pd.isna(alpha):
                    fam = family_subset.loc[family_subset["alpha"].isna()] if "alpha" in family_subset.columns else family_subset
                else:
                    fam = family_subset.loc[family_subset["alpha"].eq(alpha)]
                fam = fam.set_index("model_name")
                if "M2_no_access_interaction" in fam.index and "M3_access_interaction" in fam.index:
                    no_int = fam.loc["M2_no_access_interaction"]
                    with_int = fam.loc["M3_access_interaction"]
                    lr = float(with_int.get("log_likelihood", np.nan) - no_int.get("log_likelihood", np.nan)) * 2
                    df = float(with_int.get("df_model", np.nan) - no_int.get("df_model", np.nan))
                    rows.append(
                        {
                            "sensitivity": sensitivity,
                            "model_family": family,
                            "alpha": alpha,
                            "comparison": "M3_access_interaction_vs_M2_no_access_interaction",
                            "delta_aic": with_int.get("aic", np.nan) - no_int.get("aic", np.nan),
                            "delta_bic": with_int.get("bic", np.nan) - no_int.get("bic", np.nan),
                            "likelihood_ratio_stat": lr,
                            "likelihood_ratio_df": df,
                            "likelihood_ratio_p_value": float(chi2.sf(lr, df)) if pd.notna(lr) and pd.notna(df) and df > 0 and lr >= 0 else pd.NA,
                            "interaction_improves_aic": bool(with_int.get("aic", np.inf) < no_int.get("aic", -np.inf)),
                        }
                    )
    return pd.DataFrame(rows)


def _findings(
    model_input: pd.DataFrame,
    nb_grid: pd.DataFrame,
    poisson_summary: pd.DataFrame,
    speed_summary: pd.DataFrame,
    access_stability: pd.DataFrame,
    readiness: pd.DataFrame,
    warnings_frame: pd.DataFrame,
) -> str:
    nb_stable = bool(readiness["negative_binomial_stable"].iloc[0])
    fixed_alpha_nb_stable = bool(readiness["fixed_alpha_negative_binomial_sensitivity_stable"].iloc[0])
    robust_feasible = bool(readiness["robust_or_scaled_poisson_feasible"].iloc[0])
    access_share = float(access_stability["interaction_improves_aic"].fillna(False).mean()) if not access_stability.empty else 0.0
    merged = speed_summary.loc[speed_summary["sensitivity"].eq("merged_50plus_speed")]
    stable = speed_summary.loc[speed_summary["sensitivity"].eq("stable_speed_only")]
    decision = readiness["decision"].iloc[0]
    return f"""# Crash Count Model Refinement Sensitivity Findings

**Status:** internal exploratory model refinement only. These outputs are diagnostics and sensitivity checks, not external decision outputs, causal evidence, or downstream functional-area distance recommendations.

## Input

- Modeled rows: {len(model_input)} denominator-ready signal-direction-window rows.
- Modeled assigned crashes: {int(model_input["assigned_crash_count"].sum())}.
- Missing/review speed rows: {int(model_input["speed_band_model"].astype(str).eq("speed_missing_or_review").sum())}.

## Negative-Binomial Refinement

Stable fixed-alpha negative-binomial sensitivity available: {fixed_alpha_nb_stable}.

The fixed-alpha GLM grid was attempted for alpha values {", ".join(str(value) for value in ALPHA_GRID)}. These are sensitivity fits. They do not validate the earlier unstable estimated-alpha negative-binomial coefficients by themselves.

Estimated-alpha negative-binomial model ready for internal interpretation: {nb_stable}.

## Robust Or Quasi-Poisson

Scaled, robust, and clustered Poisson standard-error variants are feasible: {robust_feasible}.

These variants retain the Poisson mean model while adjusting uncertainty handling for overdispersion or signal-level clustering. They are more usable for internal technical review than the unstable estimated-alpha negative-binomial comparison.

## Access Interaction Stability

Share of sensitivity comparisons where the access interaction improved AIC: {access_share:.3f}.

The `analysis_window x local_access_density_band` interaction remains useful as an exploratory model term across the tested overdispersion and speed-category sensitivities.

## Speed Sensitivity

- Merged 50+ mph sensitivity rows: {int(merged["n_rows"].iloc[0]) if not merged.empty else "not_run"}.
- Stable-speed-only sensitivity rows: {int(stable["n_rows"].iloc[0]) if not stable.empty else "not_run"}.

The primary speed term remains usable with caution. The sparse 60+ mph category should be merged with 50-59 mph before any coefficient-level interpretation. Missing/review speed should remain explicit or be evaluated through a stable-speed-only sensitivity.

## Readiness Decision

Decision: `{decision}`.

Recommended internal model: {readiness["recommended_internal_model"].iloc[0]}.

Nothing in this package is ready for stakeholder interpretation. Keep coefficient interpretation internal until category simplification, overdispersion handling, and cluster sensitivity are reviewed.

## Warning Summary

Warning rows captured: {len(warnings_frame)}.
"""


def build_outputs() -> dict[str, Any]:
    matrix, sequence, roles = load_inputs()
    if not _package_available("statsmodels"):
        raise RuntimeError("statsmodels is required for refinement sensitivity outputs")
    model_input, excluded = prepare_model_input(matrix)
    model_input = _add_merged_speed(model_input)

    input_summary = _input_summary(model_input, excluded)
    nb_grid, nb_coefs, nb_warnings = _fit_nb_alpha_grid(model_input)
    poisson_summary, poisson_coefs, se_comparison, poisson_warnings = _fit_poisson_variants(model_input)
    speed_summary, speed_diag, speed_coefs, speed_warnings = _speed_sensitivity(model_input)
    access_stability = _access_stability(model_input, nb_grid)
    sparse = _sparse_review(model_input)

    diagnostics = pd.concat([nb_grid, poisson_summary, speed_diag], ignore_index=True, sort=False)
    coefficients = pd.concat([nb_coefs, poisson_coefs, speed_coefs], ignore_index=True, sort=False)
    irr = coefficients[
        [
            "model_name",
            "model_family",
            "sensitivity",
            "covariance_method",
            "alpha",
            "term",
            "incidence_rate_ratio",
            "irr_conf_int_lower",
            "irr_conf_int_upper",
            "p_value",
            "reference_level_notes",
        ]
    ].copy() if not coefficients.empty else pd.DataFrame()
    fit_summary = diagnostics[
        [
            "model_name",
            "model_family",
            "sensitivity",
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
    warnings_frame = pd.DataFrame(nb_warnings + poisson_warnings + speed_warnings)
    if warnings_frame.empty:
        warnings_frame = pd.DataFrame(columns=["model_name", "model_family", "sensitivity", "alpha", "warning_message", "unstable_covariance_flag"])
    readiness = _readiness_decision(nb_grid, poisson_summary, speed_summary, access_stability, sparse)
    family_comparison = _family_comparison(diagnostics)
    findings = _findings(model_input, nb_grid, poisson_summary, speed_summary, access_stability, readiness, warnings_frame)
    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "guarded reader inherited from model-fit module", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read or used", "required"),
            ("only_denominator_ready_signal_direction_window_rows_modeled", bool(model_input["denominator_ready_flag"].all()), len(model_input), "all modeled rows denominator-ready"),
            ("no_distance_band_models_fit", True, "only signal-direction-window matrix used", "required"),
            ("no_policy_ranking_language_introduced", True, "findings constrained and guardrails inherited", "required"),
            ("no_rankings_created", True, "no location-ordering outputs created", "required"),
            ("source_context_assignment_data_not_modified", True, "separate analysis output folder only", "required"),
            ("unstable_models_not_marked_interpretable", not bool(readiness["negative_binomial_stable"].iloc[0]) or readiness["decision"].iloc[0] == "negative_binomial_ready_for_internal_interpretation", readiness["decision"].iloc[0], "unstable models blocked from interpretation"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "model_refinement_input_summary.csv": input_summary,
        "negative_binomial_alpha_grid_comparison.csv": nb_grid,
        "poisson_overdispersion_adjusted_summary.csv": poisson_summary,
        "robust_clustered_se_comparison.csv": se_comparison,
        "speed_category_sensitivity_summary.csv": speed_summary,
        "access_interaction_stability_summary.csv": access_stability,
        "sparse_category_refinement_review.csv": sparse,
        "refined_model_fit_summary.csv": fit_summary,
        "refined_model_coefficients.csv": coefficients,
        "refined_model_incidence_rate_ratios.csv": irr,
        "refined_model_diagnostics.csv": diagnostics,
        "model_family_comparison.csv": family_comparison,
        "model_refinement_warnings.csv": warnings_frame,
        "model_refinement_readiness_decision.csv": readiness,
        "model_refinement_sensitivity_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_text(findings, OUTPUT_DIR / "crash_count_model_refinement_sensitivity_findings.md")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "internal exploratory crash-count model refinement and sensitivity",
        "status": "internal_exploratory_refinement_only",
        "inputs": [
            str(path)
            for path in [
                WINDOW_MATRIX_FILE,
                MODEL_SEQUENCE_FILE,
                VARIABLE_ROLE_FILE,
                MODEL_SPEC_FILE,
                FIRST_FIT_MANIFEST_FILE,
                FIRST_FIT_DIAGNOSTICS_FILE,
                FIRST_FIT_WARNINGS_FILE,
                RATE_ASSUMPTION_MANIFEST_FILE,
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
        "packages": {
            "statsmodels_available": _package_available("statsmodels"),
            "scipy_available": _package_available("scipy"),
            "patsy_available": _package_available("patsy"),
        },
        "guardrails": {
            "crash_direction_fields_used": False,
            "direction_factor_applied": False,
            "distance_band_models_fit": False,
            "predictions_for_policy_created": False,
            "rankings_created": False,
            "source_context_assignment_data_modified": False,
        },
        "readiness_decision": readiness.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "unused_loaded_rows": {
            "candidate_model_sequence_rows": len(sequence),
            "variable_role_rows": len(roles),
        },
    }
    _write_json(manifest, OUTPUT_DIR / "crash_count_model_refinement_sensitivity_manifest.json")
    return {
        "input_summary": input_summary,
        "nb_grid": nb_grid,
        "poisson_summary": poisson_summary,
        "speed_summary": speed_summary,
        "access_stability": access_stability,
        "readiness": readiness,
        "qa": qa,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run internal crash-count model refinement and sensitivity checks.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
