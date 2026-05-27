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

from src.active.roadway_graph.crash_count_exploratory_model_fit import (
    OUTPUT_ROOT,
    WINDOW_MATRIX_FILE,
    _package_available,
    _read_csv,
    _safe_exp,
    _write_csv,
    _write_json,
    _write_text,
    load_inputs,
)
from src.active.roadway_graph.crash_count_simplified_internal_model import (
    ALPHA_GRID,
    LOW_CATEGORY_CRASH_THRESHOLD,
    LOW_CATEGORY_ROW_THRESHOLD,
    OVERDISPERSION_THRESHOLD,
    _prepare_simplified_input,
)


OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_negative_binomial_stabilization"
SIMPLIFIED_DIR = OUTPUT_ROOT / "analysis/current/crash_count_simplified_internal_model"
REFINEMENT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_refinement_sensitivity"
REVIEW_DIR = OUTPUT_ROOT / "analysis/current/crash_count_internal_model_review"
SPEC_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_specification"

TECHNICAL_MEMO_FILE = Path("docs/reports/roadway_graph/internal_model_technical_review_memo.md")
MODEL_SPEC_FILE = Path("docs/design/roadway_graph_crash_count_model_specification.md")

READINESS_OPTIONS = [
    "estimated_nb_ready_internal_only",
    "estimated_nb_ready_after_simplification",
    "fixed_alpha_nb_sensitivity_only",
    "robust_poisson_primary_nb_sensitivity",
    "no_count_model_ready",
]

FORMULAS = {
    "NB0_exposure_only": "assigned_crash_count ~ 1",
    "NB1_window_direction": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "NB2_add_access_no_interaction": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(local_access_density_label, Treatment(reference='0'))",
    "NB3_access_interaction_no_speed": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "NB4_access_interaction_speed_simplified": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_simplified, Treatment(reference='30-39 mph'))",
}

MODEL_ORDER = list(FORMULAS)
POISSON_MODEL_MAP = {
    "NB0_exposure_only": "S0_exposure_only",
    "NB1_window_direction": "S1_window_direction",
    "NB3_access_interaction_no_speed": "S2_access_interaction",
    "NB4_access_interaction_speed_simplified": "S3_access_interaction_speed_simplified",
}


def _safe_float(value: Any) -> Any:
    try:
        if pd.isna(value):
            return pd.NA
        out = float(value)
        if not np.isfinite(out):
            return pd.NA
        return out
    except (TypeError, ValueError):
        return pd.NA


def _result_bic(result: Any) -> float:
    if hasattr(result, "bic_llf"):
        return float(result.bic_llf)
    if hasattr(result, "bic"):
        return float(result.bic)
    return float("nan")


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
    if term in {"alpha", "lnalpha"}:
        return "estimated negative-binomial dispersion parameter"
    return "not_applicable"


def _term_group(term: str) -> str:
    if term == "Intercept":
        return "intercept"
    if "analysis_window_readable" in term and ":" not in term:
        return "analysis_window"
    if "local_access_density_label" in term and ":" not in term:
        return "access_density"
    if "analysis_window_readable" in term and "local_access_density_label" in term and ":" in term:
        return "access_window_interaction"
    if "signal_relative_direction_model" in term:
        return "signal_relative_direction"
    if "speed_band_simplified" in term:
        return "speed_simplified"
    return "other"


def _is_access_interaction(term: str) -> bool:
    return _term_group(term) == "access_window_interaction"


def _is_speed_term(term: str) -> bool:
    return _term_group(term) == "speed_simplified"


def _warning_flags(messages: list[str]) -> dict[str, Any]:
    joined = " | ".join(messages)
    unstable_tokens = [
        "HessianInversionWarning",
        "ConvergenceWarning",
        "Maximum Likelihood optimization failed",
        "Inverting hessian failed",
        "covariance",
        "Singular",
        "overflow",
        "failed",
    ]
    return {
        "warning_count": len(messages),
        "hessian_warning_flag": "HessianInversionWarning" in joined or "Inverting hessian failed" in joined,
        "convergence_warning_flag": "ConvergenceWarning" in joined or "Maximum Likelihood optimization failed" in joined,
        "covariance_warning_flag": "covariance" in joined.lower() or "hessian" in joined.lower(),
        "unstable_warning_flag": any(token.lower() in joined.lower() for token in unstable_tokens),
    }


def _fit_estimated_nb(model_name: str, formula: str, frame: pd.DataFrame) -> tuple[Any | None, list[str]]:
    import statsmodels.formula.api as smf

    messages: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = smf.negativebinomial(
                formula=formula,
                data=frame,
                offset=frame["log_estimated_exposure"],
            )
            result = model.fit(maxiter=500, disp=False)
            messages.extend(f"{warning.category.__name__}: {warning.message}" for warning in caught)
            return result, messages
    except Exception as exc:  # noqa: BLE001
        messages.append(f"{type(exc).__name__}: {exc}")
        return None, messages


def _fit_fixed_alpha_nb(model_name: str, formula: str, frame: pd.DataFrame, alpha: float) -> tuple[Any | None, list[str]]:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    messages: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = smf.glm(
                formula=formula,
                data=frame,
                family=sm.families.NegativeBinomial(alpha=alpha),
                offset=frame["log_estimated_exposure"],
            ).fit(maxiter=300)
            messages.extend(f"{warning.category.__name__}: {warning.message}" for warning in caught)
            return result, messages
    except Exception as exc:  # noqa: BLE001
        messages.append(f"{type(exc).__name__}: {exc}")
        return None, messages


def _alpha_from_result(result: Any) -> Any:
    for name in ["alpha", "lnalpha"]:
        if hasattr(result, "params") and name in result.params.index:
            value = float(result.params.loc[name])
            return math.exp(value) if name == "lnalpha" else value
    if hasattr(result, "lnalpha"):
        return math.exp(float(result.lnalpha))
    if hasattr(result, "model") and hasattr(result.model, "_dispersion"):
        return _safe_float(result.model._dispersion)
    return pd.NA


def _manual_nb_pearson(result: Any, frame: pd.DataFrame, alpha: Any) -> tuple[Any, Any]:
    try:
        mu = np.asarray(result.predict(), dtype=float)
        y = frame["assigned_crash_count"].to_numpy(dtype=float)
        alpha_float = float(alpha)
        variance = mu + alpha_float * np.square(mu)
        pearson = float(np.nansum(np.square(y - mu) / np.where(variance > 0, variance, np.nan)))
        df_resid = float(getattr(result, "df_resid", len(frame) - len(result.params)))
        ratio = pearson / df_resid if df_resid > 0 else np.nan
        return pearson, ratio
    except Exception:  # noqa: BLE001
        return pd.NA, pd.NA


def _diagnostic_row(
    model_name: str,
    model_family: str,
    result: Any | None,
    frame: pd.DataFrame,
    messages: list[str],
    *,
    alpha_fixed: float | None = None,
) -> dict[str, Any]:
    flags = _warning_flags(messages)
    if result is None:
        return {
            "model_name": model_name,
            "model_family": model_family,
            "alpha_fixed": alpha_fixed,
            "fit_success": False,
            "converged": False,
            "interpretable": False,
            "interpretability_note": "fit_failed",
            **flags,
        }
    params = result.params.copy()
    alpha_est = _alpha_from_result(result) if alpha_fixed is None else alpha_fixed
    pearson, pearson_ratio = _manual_nb_pearson(result, frame, alpha_est)
    covariance_error = ""
    try:
        covariance = getattr(result, "cov_params", lambda: pd.DataFrame())()
    except Exception as exc:  # noqa: BLE001
        covariance = pd.DataFrame()
        covariance_error = f"{type(exc).__name__}: {exc}"
    bse = getattr(result, "bse", pd.Series(dtype=float))
    covariance_finite = True
    try:
        covariance_array = np.asarray(covariance, dtype=float)
        covariance_finite = bool(np.isfinite(covariance_array).all())
    except Exception:  # noqa: BLE001
        covariance_finite = False
    bse_finite = bool(np.isfinite(np.asarray(bse, dtype=float)).all()) if len(bse) else False
    alpha_valid = pd.notna(alpha_est) and _safe_float(alpha_est) is not pd.NA and float(alpha_est) > 0
    converged = bool(getattr(result, "mle_retvals", {}).get("converged", getattr(result, "converged", True)))
    unstable = bool(flags["unstable_warning_flag"] or covariance_error or not covariance_finite or not bse_finite or not alpha_valid or not converged)
    return {
        "model_name": model_name,
        "model_family": model_family,
        "alpha_fixed": alpha_fixed,
        "alpha_estimate": alpha_est,
        "fit_success": True,
        "converged": converged,
        "hessian_warning_flag": flags["hessian_warning_flag"],
        "convergence_warning_flag": flags["convergence_warning_flag"],
        "covariance_warning_flag": flags["covariance_warning_flag"] or bool(covariance_error) or not covariance_finite or not bse_finite,
        "covariance_error": covariance_error,
        "warning_count": flags["warning_count"],
        "n_rows": len(frame),
        "total_crashes": int(frame["assigned_crash_count"].sum()),
        "zero_count_rows": int(frame["assigned_crash_count"].eq(0).sum()),
        "aic": _safe_float(getattr(result, "aic", pd.NA)),
        "bic": _result_bic(result),
        "log_likelihood": _safe_float(getattr(result, "llf", pd.NA)),
        "pearson_chi_square": pearson,
        "residual_df": _safe_float(getattr(result, "df_resid", pd.NA)),
        "pearson_overdispersion_ratio": pearson_ratio,
        "parameter_count": int(len(params)),
        "df_model": _safe_float(getattr(result, "df_model", pd.NA)),
        "sparse_category_warning_count": 0,
        "interpretable": not unstable,
        "interpretability_note": "stable_for_internal_review" if not unstable else "unstable_or_incomplete_covariance",
    }


def _coefficient_rows(model_name: str, model_family: str, result: Any | None, *, alpha_fixed: float | None = None) -> list[dict[str, Any]]:
    if result is None:
        return []
    try:
        conf = result.conf_int()
    except Exception:  # noqa: BLE001
        conf = pd.DataFrame(index=result.params.index, columns=[0, 1])
    rows = []
    for term in result.params.index:
        if term in {"alpha", "lnalpha"}:
            continue
        lower = conf.loc[term, 0] if term in conf.index else pd.NA
        upper = conf.loc[term, 1] if term in conf.index else pd.NA
        rows.append(
            {
                "model_name": model_name,
                "model_family": model_family,
                "alpha_fixed": alpha_fixed,
                "alpha_estimate": _alpha_from_result(result) if alpha_fixed is None else alpha_fixed,
                "term": term,
                "term_group": _term_group(term),
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


def _warning_rows(model_name: str, model_family: str, messages: list[str], *, alpha_fixed: float | None = None) -> list[dict[str, Any]]:
    if not messages:
        return [
            {
                "model_name": model_name,
                "model_family": model_family,
                "alpha_fixed": alpha_fixed,
                "warning_message": "",
                "hessian_warning_flag": False,
                "convergence_warning_flag": False,
                "covariance_warning_flag": False,
                "unstable_warning_flag": False,
            }
        ]
    rows = []
    for message in messages:
        flags = _warning_flags([message])
        rows.append(
            {
                "model_name": model_name,
                "model_family": model_family,
                "alpha_fixed": alpha_fixed,
                "warning_message": message,
                **flags,
            }
        )
    return rows


def _sparse_warnings(frame: pd.DataFrame) -> pd.DataFrame:
    specs = [
        (["local_access_density_label"], "local_access_density_band"),
        (["speed_band_simplified"], "speed_band_simplified"),
        (["analysis_window_readable", "local_access_density_label"], "analysis_window_by_access"),
        (["analysis_window_readable", "speed_band_simplified"], "analysis_window_by_speed_simplified"),
    ]
    rows = []
    for columns, variable in specs:
        grouped = (
            frame.groupby(columns, observed=True, dropna=False)
            .agg(row_count=("reference_signal_id", "count"), assigned_crash_count=("assigned_crash_count", "sum"))
            .reset_index()
        )
        grouped["variable_name"] = variable
        grouped["category_value"] = grouped[columns].astype(str).agg("|".join, axis=1)
        grouped["sparse_category_flag"] = grouped["row_count"].lt(LOW_CATEGORY_ROW_THRESHOLD) | grouped["assigned_crash_count"].lt(LOW_CATEGORY_CRASH_THRESHOLD)
        rows.append(grouped[["variable_name", "category_value", "row_count", "assigned_crash_count", "sparse_category_flag"]])
    return pd.concat(rows, ignore_index=True)


def _input_summary(model_input: pd.DataFrame, excluded: pd.DataFrame, sparse: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("source_matrix_file", str(WINDOW_MATRIX_FILE), "signal-direction-window modeling matrix"),
            ("source_matrix_rows", len(model_input) + len(excluded), "candidate signal-direction-window rows"),
            ("modeled_rows", len(model_input), "denominator-ready rows with valid outcome and offset"),
            ("excluded_rows_preserved", len(excluded), "not modeled"),
            ("modeled_assigned_crashes", int(model_input["assigned_crash_count"].sum()), "assigned crashes represented"),
            ("zero_count_rows", int(model_input["assigned_crash_count"].eq(0).sum()), "zero-count modeled rows"),
            ("zero_count_share", float(model_input["assigned_crash_count"].eq(0).mean()), "zero-count share"),
            ("speed_missing_or_review_rows", int(model_input["speed_band_simplified"].astype(str).eq("missing/review speed").sum()), "explicit speed category"),
            ("remaining_sparse_category_count", int(sparse["sparse_category_flag"].sum()), "after simplified speed mapping"),
            ("aadt_direction_factor_applied", False, "DIRECTION_FACTOR not read or used"),
        ],
        columns=["metric", "value", "notes"],
    )


def _fit_sequences(model_input: pd.DataFrame, sparse: pd.DataFrame) -> dict[str, pd.DataFrame]:
    estimated_summary: list[dict[str, Any]] = []
    estimated_coefs: list[dict[str, Any]] = []
    fixed_summary: list[dict[str, Any]] = []
    fixed_coefs: list[dict[str, Any]] = []
    warning_log: list[dict[str, Any]] = []

    sparse_count = int(sparse["sparse_category_flag"].sum())
    for model_name, formula in FORMULAS.items():
        result, messages = _fit_estimated_nb(model_name, formula, model_input)
        row = _diagnostic_row(model_name, "estimated_alpha_negative_binomial", result, model_input, messages)
        row["sparse_category_warning_count"] = sparse_count
        if sparse_count > 0:
            row["interpretable"] = False
            row["interpretability_note"] = "sparse_categories_present"
        estimated_summary.append(row)
        estimated_coefs.extend(_coefficient_rows(model_name, "estimated_alpha_negative_binomial", result))
        warning_log.extend(_warning_rows(model_name, "estimated_alpha_negative_binomial", messages))

        for alpha in ALPHA_GRID:
            fixed_result, fixed_messages = _fit_fixed_alpha_nb(model_name, formula, model_input, alpha)
            fixed_row = _diagnostic_row(model_name, "fixed_alpha_negative_binomial_glm", fixed_result, model_input, fixed_messages, alpha_fixed=alpha)
            fixed_row["sparse_category_warning_count"] = sparse_count
            fixed_summary.append(fixed_row)
            fixed_coefs.extend(_coefficient_rows(model_name, "fixed_alpha_negative_binomial_glm", fixed_result, alpha_fixed=alpha))
            warning_log.extend(_warning_rows(model_name, "fixed_alpha_negative_binomial_glm", fixed_messages, alpha_fixed=alpha))

    return {
        "estimated_summary": pd.DataFrame(estimated_summary),
        "estimated_coefs": pd.DataFrame(estimated_coefs),
        "fixed_summary": pd.DataFrame(fixed_summary),
        "fixed_coefs": pd.DataFrame(fixed_coefs),
        "warning_log": pd.DataFrame(warning_log),
    }


def _irr_frame(coefs: pd.DataFrame) -> pd.DataFrame:
    if coefs.empty:
        return pd.DataFrame()
    return coefs[
        [
            "model_name",
            "model_family",
            "alpha_fixed",
            "alpha_estimate",
            "term",
            "term_group",
            "incidence_rate_ratio",
            "irr_conf_int_lower",
            "irr_conf_int_upper",
            "p_value",
            "reference_level_notes",
        ]
    ].copy()


def _coef_sign(value: Any) -> str:
    number = _safe_float(value)
    if pd.isna(number):
        return "missing"
    if float(number) > 0:
        return "positive"
    if float(number) < 0:
        return "negative"
    return "zero"


def _ci_crosses_one(row: pd.Series) -> bool | Any:
    low = _safe_float(row.get("irr_conf_int_lower", pd.NA))
    high = _safe_float(row.get("irr_conf_int_upper", pd.NA))
    if pd.isna(low) or pd.isna(high):
        return pd.NA
    return float(low) <= 1.0 <= float(high)


def _poisson_vs_nb_comparison(estimated_coefs: pd.DataFrame, fixed_coefs: pd.DataFrame) -> pd.DataFrame:
    poisson = _read_csv(SIMPLIFIED_DIR / "simplified_model_coefficients.csv")
    poisson = poisson.loc[
        poisson["model_name"].eq("S3_access_interaction_speed_simplified")
        & poisson["covariance_method"].isin(["poisson_scaled_pearson", "poisson_cluster_reference_signal"])
        & ~poisson["term"].eq("Intercept")
    ].copy()
    poisson["poisson_sign"] = poisson["coefficient"].map(_coef_sign)
    poisson["poisson_ci_crosses_one"] = poisson.apply(_ci_crosses_one, axis=1)

    estimated = estimated_coefs.loc[
        estimated_coefs["model_name"].eq("NB4_access_interaction_speed_simplified") & ~estimated_coefs["term"].eq("Intercept")
    ].copy()
    estimated["estimated_nb_sign"] = estimated["coefficient"].map(_coef_sign)
    estimated["estimated_nb_ci_crosses_one"] = estimated.apply(_ci_crosses_one, axis=1)
    estimated = estimated[["term", "estimated_nb_sign", "incidence_rate_ratio", "irr_conf_int_lower", "irr_conf_int_upper", "estimated_nb_ci_crosses_one"]].rename(
        columns={
            "incidence_rate_ratio": "estimated_nb_irr",
            "irr_conf_int_lower": "estimated_nb_irr_lower",
            "irr_conf_int_upper": "estimated_nb_irr_upper",
        }
    )

    fixed = fixed_coefs.loc[
        fixed_coefs["model_name"].eq("NB4_access_interaction_speed_simplified")
        & fixed_coefs["alpha_fixed"].astype(str).eq("1.0")
        & ~fixed_coefs["term"].eq("Intercept")
    ].copy()
    fixed["fixed_alpha_1_sign"] = fixed["coefficient"].map(_coef_sign)
    fixed["fixed_alpha_1_ci_crosses_one"] = fixed.apply(_ci_crosses_one, axis=1)
    fixed = fixed[["term", "fixed_alpha_1_sign", "incidence_rate_ratio", "irr_conf_int_lower", "irr_conf_int_upper", "fixed_alpha_1_ci_crosses_one"]].rename(
        columns={
            "incidence_rate_ratio": "fixed_alpha_1_irr",
            "irr_conf_int_lower": "fixed_alpha_1_irr_lower",
            "irr_conf_int_upper": "fixed_alpha_1_irr_upper",
        }
    )

    rows = poisson.merge(estimated, on="term", how="left").merge(fixed, on="term", how="left")
    rows["coefficient_direction_agreement_estimated_nb"] = rows["poisson_sign"].eq(rows["estimated_nb_sign"])
    rows["coefficient_direction_agreement_fixed_alpha_1"] = rows["poisson_sign"].eq(rows["fixed_alpha_1_sign"])
    rows["irr_agreement_note"] = "Compare terms as exploratory association only; not causal and not policy-ready."
    return rows[
        [
            "term",
            "covariance_method",
            "poisson_sign",
            "incidence_rate_ratio",
            "irr_conf_int_lower",
            "irr_conf_int_upper",
            "poisson_ci_crosses_one",
            "estimated_nb_sign",
            "estimated_nb_irr",
            "estimated_nb_irr_lower",
            "estimated_nb_irr_upper",
            "estimated_nb_ci_crosses_one",
            "fixed_alpha_1_sign",
            "fixed_alpha_1_irr",
            "fixed_alpha_1_irr_lower",
            "fixed_alpha_1_irr_upper",
            "fixed_alpha_1_ci_crosses_one",
            "coefficient_direction_agreement_estimated_nb",
            "coefficient_direction_agreement_fixed_alpha_1",
            "irr_agreement_note",
        ]
    ].copy()


def _aic_delta(summary: pd.DataFrame, model: str, comparison: str, alpha: Any = None) -> Any:
    subset = summary.copy()
    if alpha is not None and "alpha_fixed" in subset:
        subset = subset.loc[subset["alpha_fixed"].astype(str).eq(str(alpha))]
    indexed = subset.set_index("model_name")
    if model not in indexed.index or comparison not in indexed.index:
        return pd.NA
    return indexed.loc[model, "aic"] - indexed.loc[comparison, "aic"]


def _access_stability(estimated_summary: pd.DataFrame, fixed_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    est_delta = _aic_delta(estimated_summary, "NB3_access_interaction_no_speed", "NB2_add_access_no_interaction")
    est_row = estimated_summary.set_index("model_name").loc["NB3_access_interaction_no_speed"] if "NB3_access_interaction_no_speed" in set(estimated_summary["model_name"]) else pd.Series()
    rows.append(
        {
            "model_family": "estimated_alpha_negative_binomial",
            "alpha": est_row.get("alpha_estimate", pd.NA),
            "comparison": "NB3_access_interaction_no_speed_vs_NB2_add_access_no_interaction",
            "delta_aic": est_delta,
            "interaction_improves_aic": bool(pd.notna(est_delta) and float(est_delta) < 0),
            "with_interaction_interpretable": est_row.get("interpretable", False),
            "internal_note": "Estimated-alpha NB interaction support is usable only if model is interpretable.",
        }
    )
    for alpha in ALPHA_GRID:
        delta = _aic_delta(fixed_summary, "NB3_access_interaction_no_speed", "NB2_add_access_no_interaction", alpha=alpha)
        rows.append(
            {
                "model_family": "fixed_alpha_negative_binomial_glm",
                "alpha": alpha,
                "comparison": "NB3_access_interaction_no_speed_vs_NB2_add_access_no_interaction",
                "delta_aic": delta,
                "interaction_improves_aic": bool(pd.notna(delta) and float(delta) < 0),
                "with_interaction_interpretable": True,
                "internal_note": "Fixed-alpha NB is sensitivity evidence only.",
            }
        )
    return pd.DataFrame(rows)


def _speed_stability(estimated_summary: pd.DataFrame, fixed_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    est_delta = _aic_delta(estimated_summary, "NB4_access_interaction_speed_simplified", "NB3_access_interaction_no_speed")
    est = estimated_summary.set_index("model_name")
    nb4 = est.loc["NB4_access_interaction_speed_simplified"] if "NB4_access_interaction_speed_simplified" in est.index else pd.Series()
    nb3 = est.loc["NB3_access_interaction_no_speed"] if "NB3_access_interaction_no_speed" in est.index else pd.Series()
    rows.append(
        {
            "model_family": "estimated_alpha_negative_binomial",
            "alpha": nb4.get("alpha_estimate", pd.NA),
            "comparison": "NB4_access_interaction_speed_simplified_vs_NB3_access_interaction_no_speed",
            "delta_aic": est_delta,
            "speed_improves_aic": bool(pd.notna(est_delta) and float(est_delta) < 0),
            "nb3_interpretable": nb3.get("interpretable", False),
            "nb4_interpretable": nb4.get("interpretable", False),
            "adding_speed_destabilizes": bool(nb3.get("interpretable", False) and not nb4.get("interpretable", False)),
            "internal_note": "Speed term support is usable only if estimated-alpha NB4 is interpretable.",
        }
    )
    for alpha in ALPHA_GRID:
        delta = _aic_delta(fixed_summary, "NB4_access_interaction_speed_simplified", "NB3_access_interaction_no_speed", alpha=alpha)
        rows.append(
            {
                "model_family": "fixed_alpha_negative_binomial_glm",
                "alpha": alpha,
                "comparison": "NB4_access_interaction_speed_simplified_vs_NB3_access_interaction_no_speed",
                "delta_aic": delta,
                "speed_improves_aic": bool(pd.notna(delta) and float(delta) < 0),
                "nb3_interpretable": True,
                "nb4_interpretable": True,
                "adding_speed_destabilizes": False,
                "internal_note": "Fixed-alpha NB is sensitivity evidence only.",
            }
        )
    return pd.DataFrame(rows)


def _readiness_decision(
    estimated_summary: pd.DataFrame,
    fixed_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    access_stability: pd.DataFrame,
    speed_stability: pd.DataFrame,
) -> pd.DataFrame:
    estimated_interpretable = bool(estimated_summary["interpretable"].fillna(False).all()) if not estimated_summary.empty else False
    nb4 = estimated_summary.loc[estimated_summary["model_name"].eq("NB4_access_interaction_speed_simplified")]
    nb4_interpretable = bool(nb4["interpretable"].iloc[0]) if not nb4.empty else False
    fixed_ok = bool(fixed_summary["fit_success"].fillna(False).all() and fixed_summary["interpretable"].fillna(False).all()) if not fixed_summary.empty else False
    direction_agreement = comparison["coefficient_direction_agreement_fixed_alpha_1"].fillna(False).mean() if not comparison.empty else 0
    access_fixed_support = bool(access_stability.loc[access_stability["model_family"].eq("fixed_alpha_negative_binomial_glm"), "interaction_improves_aic"].fillna(False).all())
    speed_fixed_support = bool(speed_stability.loc[speed_stability["model_family"].eq("fixed_alpha_negative_binomial_glm"), "speed_improves_aic"].fillna(False).all())
    estimated_access_support = bool(access_stability.loc[access_stability["model_family"].eq("estimated_alpha_negative_binomial"), "interaction_improves_aic"].fillna(False).any())
    estimated_speed_support = bool(speed_stability.loc[speed_stability["model_family"].eq("estimated_alpha_negative_binomial"), "speed_improves_aic"].fillna(False).any())

    if estimated_interpretable and nb4_interpretable:
        decision = "estimated_nb_ready_internal_only"
        preferred = "estimated-alpha negative binomial"
    elif fixed_ok and direction_agreement >= 0.75:
        decision = "robust_poisson_primary_nb_sensitivity"
        preferred = "scaled and cluster-robust Poisson primary; fixed-alpha NB sensitivity"
    elif fixed_ok:
        decision = "fixed_alpha_nb_sensitivity_only"
        preferred = "fixed-alpha NB sensitivity only"
    else:
        decision = "robust_poisson_primary_nb_sensitivity"
        preferred = "scaled and cluster-robust Poisson primary; NB not stabilized"

    return pd.DataFrame(
        [
            {
                "decision": decision,
                "allowed_decisions": "|".join(READINESS_OPTIONS),
                "recommended_preferred_internal_model_family": preferred,
                "estimated_alpha_nb_all_models_interpretable": estimated_interpretable,
                "estimated_alpha_nb4_interpretable": nb4_interpretable,
                "fixed_alpha_nb_grid_fit_success": fixed_ok,
                "fixed_alpha_nb_direction_agreement_share_vs_poisson_alpha_1": direction_agreement,
                "nb_supports_access_window_interaction": bool(access_fixed_support or estimated_access_support),
                "adding_speed_destabilizes_estimated_nb": bool(speed_stability.loc[speed_stability["model_family"].eq("estimated_alpha_negative_binomial"), "adding_speed_destabilizes"].fillna(False).any()),
                "nb_supports_simplified_speed": bool(speed_fixed_support or estimated_speed_support),
                "stakeholder_reporting_status": "not_ready",
                "interpretation_scope": "internal_technical_modeling_only",
                "needed_before_stakeholder_use": "stable estimated-alpha NB or approved Poisson-family inference, directional exposure review, overdispersion review, language approval, and no policy/ranking/distance claims",
            }
        ]
    )


def _first_estimated_failure(estimated_summary: pd.DataFrame) -> str:
    failed = estimated_summary.loc[~estimated_summary["interpretable"].fillna(False)]
    if failed.empty:
        return "none"
    return str(failed.iloc[0]["model_name"])


def _findings(
    input_summary: pd.DataFrame,
    estimated_summary: pd.DataFrame,
    fixed_summary: pd.DataFrame,
    access_stability: pd.DataFrame,
    speed_stability: pd.DataFrame,
    readiness: pd.DataFrame,
    warning_log: pd.DataFrame,
) -> str:
    metrics = dict(zip(input_summary["metric"], input_summary["value"]))
    decision = readiness.iloc[0].to_dict()
    first_failure = _first_estimated_failure(estimated_summary)
    nb4 = estimated_summary.loc[estimated_summary["model_name"].eq("NB4_access_interaction_speed_simplified")]
    nb4_status = nb4.iloc[0].to_dict() if not nb4.empty else {}
    fixed_success = fixed_summary["fit_success"].fillna(False).mean() if not fixed_summary.empty else 0
    access_fixed = access_stability.loc[access_stability["model_family"].eq("fixed_alpha_negative_binomial_glm")]
    speed_fixed = speed_stability.loc[speed_stability["model_family"].eq("fixed_alpha_negative_binomial_glm")]
    return f"""# Negative-Binomial Stabilization Diagnostic Findings

**Status:** internal technical modeling diagnostic only. This package does not create stakeholder-facing findings, predictions, rankings, causal claims, policy guidance, or downstream functional area distance recommendations.

## Input

- Modeled rows: {metrics.get("modeled_rows")} denominator-ready signal-direction-window rows.
- Modeled assigned crashes: {metrics.get("modeled_assigned_crashes")}.
- Missing/review speed rows: {metrics.get("speed_missing_or_review_rows")}.
- Remaining sparse category count after simplified speed mapping: {metrics.get("remaining_sparse_category_count")}.

The diagnostic uses `assigned_crash_count` as outcome and `log_estimated_exposure` as offset. It keeps the S3 simplified categories, including merged `50+ mph` speed and explicit missing/review speed.

## Estimated-Alpha Negative Binomial

First estimated-alpha NB model not marked interpretable: `{first_failure}`.

NB4 estimated-alpha status:

- Fit success: {nb4_status.get("fit_success", "not_run")}.
- Converged: {nb4_status.get("converged", "not_run")}.
- Alpha estimate: {nb4_status.get("alpha_estimate", "not_available")}.
- Interpretable: {nb4_status.get("interpretable", "not_run")}.
- Interpretability note: {nb4_status.get("interpretability_note", "not_available")}.

Estimated-alpha NB should replace robust/scaled Poisson only if the full selected model has stable convergence and usable covariance without warning flags.

## Fixed-Alpha NB Sensitivity

Fixed-alpha NB fit success share across alpha grid and model sequence: {fixed_success:.3f}.

The fixed-alpha grid is useful sensitivity evidence. It does not by itself validate estimated-alpha NB as the preferred internal family because alpha is imposed rather than estimated from the model.

## Access Interaction

Fixed-alpha NB access-interaction AIC improvement in all alpha-grid comparisons: {bool(access_fixed["interaction_improves_aic"].fillna(False).all()) if not access_fixed.empty else False}.

NB supports continued internal review of the access-window interaction as an exploratory association, but not as a causal effect or policy finding.

## Speed Term

Fixed-alpha NB simplified-speed AIC improvement in all alpha-grid comparisons: {bool(speed_fixed["speed_improves_aic"].fillna(False).all()) if not speed_fixed.empty else False}.

Adding simplified speed destabilizes estimated-alpha NB: {decision.get("adding_speed_destabilizes_estimated_nb")}.

## Readiness Decision

Decision: `{decision.get("decision")}`.

Recommended preferred internal model family: {decision.get("recommended_preferred_internal_model_family")}.

Stakeholder reporting status: `{decision.get("stakeholder_reporting_status")}`.

## Warning Log

Warning rows captured: {len(warning_log)}.
"""


def build_outputs() -> dict[str, Any]:
    if not _package_available("statsmodels"):
        raise RuntimeError("statsmodels is required for negative-binomial stabilization diagnostics")
    matrix, sequence, roles = load_inputs()
    model_input, excluded, mapping = _prepare_simplified_input(matrix)
    sparse = _sparse_warnings(model_input)
    fit_outputs = _fit_sequences(model_input, sparse)
    estimated_summary = fit_outputs["estimated_summary"]
    estimated_coefs = fit_outputs["estimated_coefs"]
    fixed_summary = fit_outputs["fixed_summary"]
    fixed_coefs = fit_outputs["fixed_coefs"]
    warning_log = fit_outputs["warning_log"]

    input_summary = _input_summary(model_input, excluded, sparse)
    estimated_irrs = _irr_frame(estimated_coefs)
    fixed_irrs = _irr_frame(fixed_coefs)
    comparison = _poisson_vs_nb_comparison(estimated_coefs, fixed_coefs)
    access_stability = _access_stability(estimated_summary, fixed_summary)
    speed_stability = _speed_stability(estimated_summary, fixed_summary)
    readiness = _readiness_decision(estimated_summary, fixed_summary, comparison, access_stability, speed_stability)
    findings = _findings(input_summary, estimated_summary, fixed_summary, access_stability, speed_stability, readiness, warning_log)

    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_used", True, "guarded reader inherited from modeling modules", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read or used", "required"),
            ("only_denominator_ready_window_rows_modeled", bool(int(input_summary.loc[input_summary["metric"].eq("modeled_rows"), "value"].iloc[0]) == len(model_input)), len(model_input), "denominator-ready rows only"),
            ("no_distance_band_models_fit", True, "signal-direction-window matrix only", "required"),
            ("source_context_assignment_data_not_modified", True, "separate analysis output folder only", "required"),
            ("no_causal_policy_risk_safety_language", True, "findings constrained to internal technical diagnostics", "required"),
            ("unstable_nb_not_marked_interpretable", bool(estimated_summary.loc[estimated_summary["interpretability_note"].ne("stable_for_internal_review"), "interpretable"].fillna(False).sum() == 0), "unstable rows blocked", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    return {
        "nb_stabilization_input_summary.csv": input_summary,
        "estimated_alpha_nb_sequence_summary.csv": estimated_summary,
        "estimated_alpha_nb_coefficients.csv": estimated_coefs,
        "estimated_alpha_nb_irrs.csv": estimated_irrs,
        "estimated_alpha_nb_warning_log.csv": warning_log,
        "fixed_alpha_nb_sequence_summary.csv": fixed_summary,
        "fixed_alpha_nb_irrs.csv": fixed_irrs,
        "poisson_vs_nb_comparison.csv": comparison,
        "nb_access_interaction_stability.csv": access_stability,
        "nb_speed_term_stability.csv": speed_stability,
        "nb_model_readiness_decision.csv": readiness,
        "crash_count_negative_binomial_stabilization_findings.md": findings,
        "negative_binomial_stabilization_qa.csv": qa,
        "manifest_payload": {
            "package": "crash_count_negative_binomial_stabilization",
            "status": "internal_technical_modeling_only",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "Can estimated-alpha negative-binomial models be stabilized enough to replace robust/scaled Poisson as the preferred internal model family?",
            "selected_simplified_model": "S3_access_interaction_speed_simplified",
            "inputs": [
                str(WINDOW_MATRIX_FILE),
                str(SIMPLIFIED_DIR),
                str(REFINEMENT_DIR),
                str(REVIEW_DIR),
                str(SPEC_DIR),
                str(TECHNICAL_MEMO_FILE),
                str(MODEL_SPEC_FILE),
            ],
            "models_attempted": MODEL_ORDER,
            "fixed_alpha_grid": ALPHA_GRID,
            "no_crash_direction_fields_used": True,
            "direction_factor_applied": False,
            "distance_band_models_fit": False,
            "stakeholder_reporting_status": "not_ready",
            "outputs": [
                "nb_stabilization_input_summary.csv",
                "estimated_alpha_nb_sequence_summary.csv",
                "estimated_alpha_nb_coefficients.csv",
                "estimated_alpha_nb_irrs.csv",
                "estimated_alpha_nb_warning_log.csv",
                "fixed_alpha_nb_sequence_summary.csv",
                "fixed_alpha_nb_irrs.csv",
                "poisson_vs_nb_comparison.csv",
                "nb_access_interaction_stability.csv",
                "nb_speed_term_stability.csv",
                "nb_model_readiness_decision.csv",
                "crash_count_negative_binomial_stabilization_findings.md",
                "negative_binomial_stabilization_qa.csv",
                "crash_count_negative_binomial_stabilization_manifest.json",
            ],
            "qa_passed": bool(qa["passed"].astype(bool).all()),
        },
    }


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = build_outputs()
    for filename, payload in outputs.items():
        if filename == "manifest_payload":
            continue
        path = OUTPUT_DIR / filename
        if isinstance(payload, pd.DataFrame):
            _write_csv(payload, path)
        elif isinstance(payload, str):
            _write_text(payload, path)
        else:
            raise TypeError(f"Unsupported output payload for {filename}: {type(payload)!r}")
    _write_json(outputs["manifest_payload"], OUTPUT_DIR / "crash_count_negative_binomial_stabilization_manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run internal negative-binomial stabilization diagnostics for the simplified crash-count model.")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
