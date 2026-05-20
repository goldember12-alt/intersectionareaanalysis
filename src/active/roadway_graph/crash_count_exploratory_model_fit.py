from __future__ import annotations

import argparse
import importlib.util
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2


OUTPUT_ROOT = Path("work/output/roadway_graph")
READINESS_DIR = OUTPUT_ROOT / "analysis/current/crash_count_modeling_readiness_dataset"
SPEC_DIR = OUTPUT_ROOT / "analysis/current/crash_count_model_specification"
SUPPRESSION_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_suppression_review"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_exploratory_model_fit"

WINDOW_MATRIX_FILE = READINESS_DIR / "crash_count_modeling_matrix_signal_direction_window.csv"
MODEL_SEQUENCE_FILE = SPEC_DIR / "candidate_model_sequence.csv"
VARIABLE_ROLE_FILE = SPEC_DIR / "model_variable_role_table.csv"
MODEL_SPEC_FILE = Path("docs/design/roadway_graph_crash_count_model_specification.md")
SUPPRESSION_MANIFEST_FILE = SUPPRESSION_DIR / "rate_suppression_review_manifest.json"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

LOW_CATEGORY_ROW_THRESHOLD = 30
LOW_CATEGORY_CRASH_THRESHOLD = 5
OVERDISPERSION_THRESHOLD = 1.5
INFLUENCE_QUEUE_LIMIT = 250

FORMULAS = {
    "M0_exposure_only": "assigned_crash_count ~ 1",
    "M1_window_direction": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "M2_add_access": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(local_access_density_band_model, Treatment(reference='access_0'))",
    "M3_window_access_interaction": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "M4_add_speed": "assigned_crash_count ~ C(analysis_window_model, Treatment(reference='window_0_1000ft')) * C(local_access_density_band_model, Treatment(reference='access_0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_model, Treatment(reference='speed_30_39_mph'))",
}

MODEL_ORDER = list(FORMULAS)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    header = pd.read_csv(path, nrows=0).columns.tolist()
    columns = header if usecols is None else usecols
    blocked = [column for column in columns if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _finite(series: pd.Series) -> pd.Series:
    numeric = _num(series)
    return numeric.notna() & np.isfinite(numeric)


def _safe_exp(value: Any) -> Any:
    if pd.isna(value):
        return pd.NA
    try:
        return float(math.exp(float(value)))
    except (OverflowError, ValueError):
        return pd.NA


def _package_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = [
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "assigned_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "represented_length_ft",
        "represented_length_miles",
        "estimated_exposure",
        "log_estimated_exposure",
        "denominator_ready_flag",
        "low_exposure_flag",
        "low_crash_count_flag",
        "zero_crash_flag",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "aadt_year_status",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "bidirectional_aadt_assumption_flag",
        "speed_band",
        "speed_missing_or_review_share",
        "local_access_count",
        "local_access_density_per_1000ft",
        "local_access_density_band",
        "roadway_representation_mix",
        "urban_crash_count",
        "rural_crash_count",
        "context_completeness_flags",
    ]
    matrix = _read_csv(WINDOW_MATRIX_FILE, usecols=columns)
    sequence = _read_csv(MODEL_SEQUENCE_FILE)
    roles = _read_csv(VARIABLE_ROLE_FILE)
    return matrix, sequence, roles


def prepare_model_input(matrix: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = matrix.copy()
    numeric_columns = [
        "assigned_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "represented_length_ft",
        "represented_length_miles",
        "estimated_exposure",
        "log_estimated_exposure",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "speed_missing_or_review_share",
        "local_access_count",
        "local_access_density_per_1000ft",
        "urban_crash_count",
        "rural_crash_count",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame[column])
    for column in [
        "denominator_ready_flag",
        "low_exposure_flag",
        "low_crash_count_flag",
        "zero_crash_flag",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "bidirectional_aadt_assumption_flag",
    ]:
        frame[column] = _bool(frame[column])

    frame["model_exclusion_reason"] = ""
    frame.loc[~frame["denominator_ready_flag"], "model_exclusion_reason"] += "not_denominator_ready;"
    frame.loc[frame["assigned_crash_count"].isna(), "model_exclusion_reason"] += "missing_assigned_crash_count;"
    frame.loc[frame["assigned_crash_count"].lt(0), "model_exclusion_reason"] += "negative_assigned_crash_count;"
    frame.loc[~_finite(frame["log_estimated_exposure"]), "model_exclusion_reason"] += "nonfinite_log_estimated_exposure;"
    frame.loc[~frame["estimated_exposure"].gt(0), "model_exclusion_reason"] += "nonpositive_estimated_exposure;"
    keep = frame["model_exclusion_reason"].eq("")

    included = frame.loc[keep].copy()
    excluded = frame.loc[~keep].copy()
    included["analysis_window_model"] = included["analysis_window"].map(
        {
            "high_priority_0_1000ft": "window_0_1000ft",
            "sensitivity_1000_2500ft": "window_1000_2500ft",
        }
    )
    included["analysis_window_label"] = included["analysis_window_model"].map(
        {
            "window_0_1000ft": "0-1,000 ft",
            "window_1000_2500ft": "1,000-2,500 ft",
        }
    )
    included["signal_relative_direction_model"] = included["signal_relative_direction"].map(
        {
            "downstream_of_reference_signal": "downstream",
            "upstream_of_reference_signal": "upstream",
        }
    )
    included["signal_relative_direction_label"] = included["signal_relative_direction_model"]
    included["local_access_density_band_model"] = included["local_access_density_band"].map(
        {
            "0_per_1000ft": "access_0",
            "gt0_lt1_per_1000ft": "access_gt0_1",
            "1_lt3_per_1000ft": "access_1_3",
            "3_lt6_per_1000ft": "access_3_6",
            "6plus_per_1000ft": "access_6plus",
        }
    )
    included["local_access_density_band_label"] = included["local_access_density_band_model"].map(
        {
            "access_0": "0",
            "access_gt0_1": ">0-1",
            "access_1_3": "1-3",
            "access_3_6": "3-6",
            "access_6plus": "6+",
        }
    )
    included["speed_band_model"] = included["speed_band"].map(
        {
            "lt_30_mph": "speed_lt_30_mph",
            "30_39_mph": "speed_30_39_mph",
            "40_49_mph": "speed_40_49_mph",
            "50_59_mph": "speed_50_59_mph",
            "60plus_mph": "speed_60plus_mph",
            "speed_missing_or_review": "speed_missing_or_review",
        }
    )
    included["speed_band_label"] = included["speed_band_model"].map(
        {
            "speed_lt_30_mph": "<30 mph",
            "speed_30_39_mph": "30-39 mph",
            "speed_40_49_mph": "40-49 mph",
            "speed_50_59_mph": "50-59 mph",
            "speed_60plus_mph": "60+ mph",
            "speed_missing_or_review": "missing/review speed",
        }
    )

    included["analysis_window_model"] = pd.Categorical(
        included["analysis_window_model"],
        categories=["window_0_1000ft", "window_1000_2500ft"],
        ordered=True,
    )
    included["signal_relative_direction_model"] = pd.Categorical(
        included["signal_relative_direction_model"],
        categories=["downstream", "upstream"],
        ordered=True,
    )
    included["local_access_density_band_model"] = pd.Categorical(
        included["local_access_density_band_model"],
        categories=["access_0", "access_gt0_1", "access_1_3", "access_3_6", "access_6plus"],
        ordered=True,
    )
    included["speed_band_model"] = pd.Categorical(
        included["speed_band_model"],
        categories=[
            "speed_30_39_mph",
            "speed_lt_30_mph",
            "speed_40_49_mph",
            "speed_50_59_mph",
            "speed_60plus_mph",
            "speed_missing_or_review",
        ],
        ordered=True,
    )
    return included, excluded


def _blocked_outputs(reason: str, matrix: pd.DataFrame, sequence: pd.DataFrame, roles: pd.DataFrame) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    qa = pd.DataFrame(
        [
            ("model_fit_blocked", True, reason, "statsmodels available"),
            ("no_model_was_fit", True, "blocked before fitting", "required"),
            ("no_crash_direction_fields_read_or_used", True, "guarded reader blocks crash-direction field tokens", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read or used", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )
    _write_csv(matrix.head(0), OUTPUT_DIR / "model_input_rows.csv")
    _write_csv(matrix, OUTPUT_DIR / "model_input_excluded_rows.csv")
    for name in [
        "model_fit_summary.csv",
        "model_fit_coefficients.csv",
        "model_fit_incidence_rate_ratios.csv",
        "model_fit_diagnostics.csv",
        "model_overdispersion_summary.csv",
        "model_family_comparison.csv",
        "model_residual_summary.csv",
        "model_influence_review_queue.csv",
        "model_sparse_category_summary.csv",
    ]:
        _write_csv(pd.DataFrame(), OUTPUT_DIR / name)
    _write_csv(pd.DataFrame([{"warning_type": "blocked", "warning_message": reason}]), OUTPUT_DIR / "model_convergence_warnings.csv")
    _write_csv(_guardrails(), OUTPUT_DIR / "model_interpretation_guardrails.csv")
    _write_csv(qa, OUTPUT_DIR / "crash_count_exploratory_model_fit_qa.csv")
    findings = f"""# Crash Count Exploratory Model Fit Findings

**Status:** blocked exploratory model fit. No models were fit.

Reason: {reason}
"""
    _write_text(findings, OUTPUT_DIR / "crash_count_exploratory_model_fit_findings.md")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "blocked_no_models_fit",
        "blocked_reason": reason,
        "inputs": [str(WINDOW_MATRIX_FILE), str(MODEL_SEQUENCE_FILE), str(VARIABLE_ROLE_FILE), str(MODEL_SPEC_FILE)],
        "guardrails": _guardrail_dict(models_fit=False),
        "qa": qa.to_dict(orient="records"),
        "input_sequence_rows": len(sequence),
        "input_variable_role_rows": len(roles),
    }
    _write_json(manifest, OUTPUT_DIR / "crash_count_exploratory_model_fit_manifest.json")
    return {"blocked": True, "reason": reason, "qa": qa}


def _guardrail_dict(*, models_fit: bool) -> dict[str, bool]:
    return {
        "models_fit": models_fit,
        "crash_direction_fields_used": False,
        "direction_factor_applied": False,
        "rows_over_2500ft_used": False,
        "distance_band_models_fit": False,
        "predictions_for_policy_created": False,
        "rankings_created": False,
        "source_context_assignment_data_modified": False,
    }


def _guardrails() -> pd.DataFrame:
    rows = [
        ("allowed", "exploratory association", "Use only for internal technical review."),
        ("allowed", "modeled crash count", "Use with exposure-offset caveat."),
        ("allowed", "after accounting for estimated exposure", "Use when describing model terms."),
        ("allowed", "incidence rate ratio", "Use as coefficient transform, not as location ranking."),
        ("allowed", "model diagnostic", "Use for technical review."),
        ("allowed", "provisional", "Use for all model outputs."),
        ("avoid", "causes", "Do not use causal language."),
        ("avoid", "risk", "Do not use ranking or hazard language."),
        ("avoid", "danger", "Do not use hazard language."),
        ("avoid", "safety performance", "Do not present as performance ranking."),
        ("avoid", "expected crashes for policy", "Do not present fitted values for policy use."),
        ("avoid", "final recommendations", "Do not recommend distances or actions."),
        ("avoid", "warrants", "Do not frame as warrants."),
        ("avoid", "guidance", "Do not frame as policy guidance."),
        ("avoid", "unsafe/safe locations", "Do not classify locations."),
    ]
    return pd.DataFrame(rows, columns=["language_type", "phrase", "handling"])


def fit_models(model_input: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    fitted: dict[str, Any] = {}
    warnings_out: list[dict[str, Any]] = []
    for model_name, formula in FORMULAS.items():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                result = smf.glm(
                    formula=formula,
                    data=model_input,
                    family=sm.families.Poisson(),
                    offset=model_input["log_estimated_exposure"],
                ).fit(maxiter=200)
                fitted[(model_name, "poisson_glm")] = {"result": result, "formula": formula}
                for warning in caught:
                    warnings_out.append(
                        {
                            "model_name": model_name,
                            "model_family": "poisson_glm",
                            "warning_type": warning.category.__name__,
                            "warning_message": str(warning.message),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - diagnostics package records fitting failures.
                warnings_out.append(
                    {
                        "model_name": model_name,
                        "model_family": "poisson_glm",
                        "warning_type": type(exc).__name__,
                        "warning_message": str(exc),
                    }
                )
    for model_name, formula in FORMULAS.items():
        if (model_name, "poisson_glm") not in fitted:
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                groups = model_input["reference_signal_id"]
                robust = smf.glm(
                    formula=formula,
                    data=model_input,
                    family=sm.families.Poisson(),
                    offset=model_input["log_estimated_exposure"],
                ).fit(maxiter=200, cov_type="cluster", cov_kwds={"groups": groups})
                fitted[(model_name, "poisson_glm")]["cluster_result"] = robust
                for warning in caught:
                    warnings_out.append(
                        {
                            "model_name": model_name,
                            "model_family": "poisson_glm_cluster_se",
                            "warning_type": warning.category.__name__,
                            "warning_message": str(warning.message),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                warnings_out.append(
                    {
                        "model_name": model_name,
                        "model_family": "poisson_glm_cluster_se",
                        "warning_type": type(exc).__name__,
                        "warning_message": str(exc),
                    }
                )
    return fitted, warnings_out


def _diagnostics_for_result(model_name: str, family: str, result: Any, frame: pd.DataFrame) -> dict[str, Any]:
    resid_df = float(getattr(result, "df_resid", np.nan))
    pearson = float(np.nansum(np.asarray(getattr(result, "resid_pearson", []), dtype=float) ** 2))
    deviance = float(getattr(result, "deviance", np.nan))
    pearson_ratio = pearson / resid_df if resid_df > 0 else np.nan
    deviance_ratio = deviance / resid_df if resid_df > 0 else np.nan
    return {
        "model_name": model_name,
        "model_family": family,
        "n_rows": int(getattr(result, "nobs", len(frame))),
        "total_crashes": int(frame["assigned_crash_count"].sum()),
        "zero_count_rows": int(frame["assigned_crash_count"].eq(0).sum()),
        "zero_count_share": float(frame["assigned_crash_count"].eq(0).mean()),
        "aic": float(getattr(result, "aic", np.nan)),
        "bic": _result_bic(result),
        "log_likelihood": float(getattr(result, "llf", np.nan)),
        "deviance": deviance,
        "pearson_chi_square": pearson,
        "residual_df": resid_df,
        "pearson_overdispersion_ratio": pearson_ratio,
        "deviance_overdispersion_ratio": deviance_ratio,
        "overdispersion_flag": bool(pearson_ratio > OVERDISPERSION_THRESHOLD),
        "converged": bool(getattr(result, "converged", True)),
        "df_model": float(getattr(result, "df_model", np.nan)),
    }


def _result_bic(result: Any) -> float:
    if hasattr(result, "bic_llf"):
        return float(result.bic_llf)
    if hasattr(result, "bic"):
        return float(result.bic)
    return float("nan")


def _coef_rows(model_name: str, family: str, result: Any, cluster_result: Any | None) -> list[dict[str, Any]]:
    rows = []
    params = result.params
    conf = result.conf_int()
    cluster_bse = getattr(cluster_result, "bse", pd.Series(dtype=float)) if cluster_result is not None else pd.Series(dtype=float)
    cluster_p = getattr(cluster_result, "pvalues", pd.Series(dtype=float)) if cluster_result is not None else pd.Series(dtype=float)
    for term in params.index:
        lower = conf.loc[term, 0] if term in conf.index else pd.NA
        upper = conf.loc[term, 1] if term in conf.index else pd.NA
        rows.append(
            {
                "model_name": model_name,
                "model_family": family,
                "term": term,
                "coefficient": float(params.loc[term]),
                "standard_error": float(result.bse.loc[term]) if term in result.bse.index else pd.NA,
                "clustered_standard_error": float(cluster_bse.loc[term]) if term in cluster_bse.index else pd.NA,
                "p_value": float(result.pvalues.loc[term]) if term in result.pvalues.index else pd.NA,
                "clustered_p_value": float(cluster_p.loc[term]) if term in cluster_p.index else pd.NA,
                "conf_int_lower": lower,
                "conf_int_upper": upper,
                "incidence_rate_ratio": _safe_exp(params.loc[term]),
                "irr_conf_int_lower": _safe_exp(lower),
                "irr_conf_int_upper": _safe_exp(upper),
                "reference_level_notes": _reference_note(term),
            }
        )
    return rows


def _reference_note(term: str) -> str:
    if term == "Intercept":
        return "reference levels: 0-1,000 ft; downstream; access 0; speed 30-39 mph where present"
    if "analysis_window_model" in term:
        return "reference analysis_window is 0-1,000 ft"
    if "signal_relative_direction_model" in term:
        return "reference signal_relative_direction is downstream"
    if "local_access_density_band_model" in term:
        return "reference local_access_density_band is 0 per 1,000 ft"
    if "speed_band_model" in term:
        return "reference speed_band is 30-39 mph"
    return "not_applicable"


def attempt_negative_binomial(
    model_input: pd.DataFrame, poisson_diagnostics: pd.DataFrame, warnings_out: list[dict[str, Any]]
) -> dict[tuple[str, str], Any]:
    import statsmodels.formula.api as smf

    if not bool(poisson_diagnostics["overdispersion_flag"].any()):
        return {}

    fitted = {}
    for model_name, formula in FORMULAS.items():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                result = smf.negativebinomial(
                    formula=formula,
                    data=model_input,
                    offset=model_input["log_estimated_exposure"],
                ).fit(maxiter=300, disp=False)
                fitted[(model_name, "negative_binomial")] = {"result": result, "formula": formula}
                for warning in caught:
                    warnings_out.append(
                        {
                            "model_name": model_name,
                            "model_family": "negative_binomial",
                            "warning_type": warning.category.__name__,
                            "warning_message": str(warning.message),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                warnings_out.append(
                    {
                        "model_name": model_name,
                        "model_family": "negative_binomial",
                        "warning_type": type(exc).__name__,
                        "warning_message": str(exc),
                    }
                )
    return fitted


def _nb_diagnostics(model_name: str, family: str, result: Any, frame: pd.DataFrame) -> dict[str, Any]:
    resid_df = float(getattr(result, "df_resid", np.nan))
    pearson = np.nan
    pearson_ratio = np.nan
    try:
        resid = np.asarray(result.resid, dtype=float)
        pearson = float(np.nansum(resid**2))
        pearson_ratio = pearson / resid_df if resid_df > 0 else np.nan
    except Exception:  # noqa: BLE001
        pass
    return {
        "model_name": model_name,
        "model_family": family,
        "n_rows": int(getattr(result, "nobs", len(frame))),
        "total_crashes": int(frame["assigned_crash_count"].sum()),
        "zero_count_rows": int(frame["assigned_crash_count"].eq(0).sum()),
        "zero_count_share": float(frame["assigned_crash_count"].eq(0).mean()),
        "aic": float(getattr(result, "aic", np.nan)),
        "bic": _result_bic(result),
        "log_likelihood": float(getattr(result, "llf", np.nan)),
        "deviance": pd.NA,
        "pearson_chi_square": pearson,
        "residual_df": resid_df,
        "pearson_overdispersion_ratio": pearson_ratio,
        "deviance_overdispersion_ratio": pd.NA,
        "overdispersion_flag": pd.NA,
        "converged": bool(getattr(result, "mle_retvals", {}).get("converged", getattr(result, "converged", False))),
        "df_model": float(getattr(result, "df_model", np.nan)),
    }


def _nb_coef_rows(model_name: str, family: str, result: Any) -> list[dict[str, Any]]:
    rows = []
    params = result.params
    conf = result.conf_int()
    for term in params.index:
        lower = conf.loc[term, 0] if term in conf.index else pd.NA
        upper = conf.loc[term, 1] if term in conf.index else pd.NA
        rows.append(
            {
                "model_name": model_name,
                "model_family": family,
                "term": term,
                "coefficient": float(params.loc[term]),
                "standard_error": float(result.bse.loc[term]) if term in result.bse.index else pd.NA,
                "clustered_standard_error": pd.NA,
                "p_value": float(result.pvalues.loc[term]) if term in result.pvalues.index else pd.NA,
                "clustered_p_value": pd.NA,
                "conf_int_lower": lower,
                "conf_int_upper": upper,
                "incidence_rate_ratio": _safe_exp(params.loc[term]),
                "irr_conf_int_lower": _safe_exp(lower),
                "irr_conf_int_upper": _safe_exp(upper),
                "reference_level_notes": _reference_note(term),
            }
        )
    return rows


def _fit_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "model_name",
        "model_family",
        "n_rows",
        "total_crashes",
        "zero_count_rows",
        "zero_count_share",
        "aic",
        "bic",
        "log_likelihood",
        "converged",
        "overdispersion_flag",
    ]
    return diagnostics[[column for column in keep if column in diagnostics.columns]].copy()


def _family_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family in diagnostics["model_family"].dropna().unique():
        fam = diagnostics.loc[diagnostics["model_family"].eq(family)].set_index("model_name")
        previous = None
        for model_name in MODEL_ORDER:
            if model_name not in fam.index:
                continue
            row = fam.loc[model_name]
            out = {
                "model_name": model_name,
                "model_family": family,
                "aic": row.get("aic", pd.NA),
                "bic": row.get("bic", pd.NA),
                "log_likelihood": row.get("log_likelihood", pd.NA),
                "comparison_model": previous,
                "delta_aic_vs_previous": pd.NA,
                "likelihood_ratio_stat_vs_previous": pd.NA,
                "likelihood_ratio_df_vs_previous": pd.NA,
                "likelihood_ratio_p_value_vs_previous": pd.NA,
                "fit_improvement_flag_vs_previous": pd.NA,
            }
            if previous is not None and previous in fam.index:
                prev = fam.loc[previous]
                out["delta_aic_vs_previous"] = row.get("aic", np.nan) - prev.get("aic", np.nan)
                lr = 2 * (row.get("log_likelihood", np.nan) - prev.get("log_likelihood", np.nan))
                df = row.get("df_model", np.nan) - prev.get("df_model", np.nan)
                out["likelihood_ratio_stat_vs_previous"] = lr
                out["likelihood_ratio_df_vs_previous"] = df
                out["likelihood_ratio_p_value_vs_previous"] = float(chi2.sf(lr, df)) if pd.notna(lr) and pd.notna(df) and df > 0 and lr >= 0 else pd.NA
                out["fit_improvement_flag_vs_previous"] = bool(out["delta_aic_vs_previous"] < 0)
            rows.append(out)
            previous = model_name
    return pd.DataFrame(rows)


def _residual_summary(model_name: str, family: str, result: Any) -> pd.DataFrame:
    rows = []
    residual_sources = {
        "response": getattr(result, "resid_response", None),
        "pearson": getattr(result, "resid_pearson", None),
        "deviance": getattr(result, "resid_deviance", None),
    }
    for residual_type, values in residual_sources.items():
        if values is None:
            continue
        series = pd.Series(np.asarray(values, dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
        if series.empty:
            continue
        rows.append(
            {
                "model_name": model_name,
                "model_family": family,
                "residual_type": residual_type,
                "count": int(series.count()),
                "mean": float(series.mean()),
                "std": float(series.std()),
                "min": float(series.min()),
                "p05": float(series.quantile(0.05)),
                "p25": float(series.quantile(0.25)),
                "median": float(series.median()),
                "p75": float(series.quantile(0.75)),
                "p95": float(series.quantile(0.95)),
                "max": float(series.max()),
            }
        )
    return pd.DataFrame(rows)


def _influence_queue(model_name: str, family: str, result: Any, frame: pd.DataFrame) -> pd.DataFrame:
    try:
        influence = result.get_influence()
        cooks = influence.cooks_distance[0]
        hat = influence.hat_matrix_diag
        resid = np.asarray(getattr(result, "resid_pearson", np.repeat(np.nan, len(frame))), dtype=float)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    out = frame[
        [
            "reference_signal_id",
            "signal_relative_direction",
            "analysis_window",
            "assigned_crash_count",
            "estimated_exposure",
            "local_access_density_band",
            "speed_band",
            "low_exposure_flag",
            "low_crash_count_flag",
            "zero_crash_flag",
        ]
    ].copy()
    out.insert(0, "model_name", model_name)
    out.insert(1, "model_family", family)
    out["cooks_distance"] = cooks
    out["hat_value"] = hat
    out["pearson_residual"] = resid
    out["model_review_queue_reason"] = "large_model_influence_diagnostic"
    return out.sort_values("cooks_distance", ascending=False).head(INFLUENCE_QUEUE_LIMIT)


def _sparse_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variable, label_column in [
        ("analysis_window_model", "analysis_window_label"),
        ("signal_relative_direction_model", "signal_relative_direction_label"),
        ("local_access_density_band_model", "local_access_density_band_label"),
        ("speed_band_model", "speed_band_label"),
    ]:
        grouped = (
            frame.groupby([variable, label_column], observed=True, dropna=False)
            .agg(
                row_count=("reference_signal_id", "count"),
                assigned_crash_count=("assigned_crash_count", "sum"),
                zero_count_rows=("zero_crash_flag", "sum"),
                estimated_exposure=("estimated_exposure", "sum"),
            )
            .reset_index()
            .rename(columns={variable: "category_value", label_column: "category_label"})
        )
        grouped.insert(0, "variable_name", variable)
        grouped["zero_count_share"] = grouped["zero_count_rows"] / grouped["row_count"].replace(0, pd.NA)
        grouped["sparse_category_flag"] = grouped["row_count"].lt(LOW_CATEGORY_ROW_THRESHOLD) | grouped["assigned_crash_count"].lt(LOW_CATEGORY_CRASH_THRESHOLD)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _findings(
    model_input: pd.DataFrame,
    excluded: pd.DataFrame,
    diagnostics: pd.DataFrame,
    family_comparison: pd.DataFrame,
    sparse: pd.DataFrame,
    warnings_frame: pd.DataFrame,
    nb_attempted: bool,
) -> str:
    poisson = diagnostics.loc[diagnostics["model_family"].eq("poisson_glm")].copy()
    poisson_success = set(poisson["model_name"]) == set(MODEL_ORDER)
    primary = poisson.loc[poisson["model_name"].eq("M4_add_speed")]
    overdispersion = bool(poisson["overdispersion_flag"].fillna(False).any())
    overdispersion_ratio = float(primary["pearson_overdispersion_ratio"].iloc[0]) if not primary.empty else float("nan")
    nb = diagnostics.loc[diagnostics["model_family"].eq("negative_binomial")]
    nb_warning = (
        not warnings_frame.loc[
            warnings_frame["model_family"].eq("negative_binomial")
            & warnings_frame["warning_type"].isin(["HessianInversionWarning", "ConvergenceWarning"])
        ].empty
        if not warnings_frame.empty
        else False
    )
    nb_success = not nb.empty and set(nb["model_name"]) == set(MODEL_ORDER) and bool(nb["converged"].fillna(False).all()) and not nb_warning
    compare = family_comparison.loc[
        family_comparison["model_name"].eq("M3_window_access_interaction") & family_comparison["model_family"].eq("poisson_glm")
    ]
    access_improved = bool(compare["fit_improvement_flag_vs_previous"].iloc[0]) if not compare.empty else False
    access_delta = compare["delta_aic_vs_previous"].iloc[0] if not compare.empty else pd.NA
    sparse_count = int(sparse["sparse_category_flag"].sum())
    speed_missing_share = float(model_input["speed_band_model"].astype(str).eq("speed_missing_or_review").mean())
    speed_usable = "usable_with_missing_review_category_and_sensitivity" if speed_missing_share < 0.50 else "too_missing_heavy_for_primary_interpretation"
    ready_internal = poisson_success and len(model_input) > 0
    return f"""# Crash Count Exploratory Model Fit Findings

**Status:** exploratory/internal technical review only. These outputs are model diagnostics and exploratory associations. They are not external decision outputs, causal evidence, or downstream functional-area distance recommendations.

## Bounded Question

How does the first signal-direction-window crash-count model sequence fit when `assigned_crash_count` is modeled with `offset(log_estimated_exposure)`?

## Input Rows

- Modeled rows: {len(model_input)}.
- Excluded rows preserved: {len(excluded)}.
- Modeled assigned crashes: {int(model_input["assigned_crash_count"].sum())}.
- Zero-count modeled rows: {int(model_input["assigned_crash_count"].eq(0).sum())} ({model_input["assigned_crash_count"].eq(0).mean():.3f}).
- Speed missing/review modeled rows: {int(model_input["speed_band_model"].astype(str).eq("speed_missing_or_review").sum())} ({speed_missing_share:.3f}).

## Fit Status

- Poisson sequence fit successfully: {poisson_success}.
- Overdispersion present under threshold {OVERDISPERSION_THRESHOLD}: {overdispersion}.
- M4 Pearson overdispersion ratio: {overdispersion_ratio:.3f}.
- Negative-binomial comparison attempted: {nb_attempted}.
- Negative-binomial comparison returned usable covariance diagnostics: {nb_success}.
- Convergence/fitting warning rows: {len(warnings_frame)}.

## Access Interaction

The Poisson `M3_window_access_interaction` model improved AIC compared with `M2_add_access`: {access_improved}. Delta AIC versus M2: {access_delta}.

The access interaction remains exploratory. It is motivated by the readiness finding that the broad windows have different access-density patterns, not by a causal claim.

## Sparse Categories And Speed

- Sparse category rows flagged: {sparse_count}.
- Speed term usability: {speed_usable}.

The primary sequence keeps missing/review speed as an explicit category. A stable-speed-only sensitivity should be considered before any interpretation of speed terms.

## Review Readiness

Results are ready for internal technical review: {ready_internal}.

Results are not ready for stakeholder interpretation. Required next review includes overdispersion handling, category sparsity, coefficient stability, influence diagnostics, exposure denominator caveats, and signal-level non-independence.

## Recommended Next Refinement

Review Poisson versus negative-binomial diagnostics, then decide whether the exploratory fitting module should add a stable-speed-only sensitivity, simplified roadway-representation sensitivity, or clustered/robust inference refinement before any report-facing summary is drafted.
"""


def build_outputs() -> dict[str, Any]:
    matrix, sequence, roles = load_inputs()
    if not _package_available("statsmodels"):
        return _blocked_outputs("statsmodels is not available in the active environment", matrix, sequence, roles)

    model_input, excluded = prepare_model_input(matrix)
    poisson_fitted, warnings_out = fit_models(model_input)

    diagnostics_rows: list[dict[str, Any]] = []
    coef_rows: list[dict[str, Any]] = []
    residual_frames: list[pd.DataFrame] = []
    influence_frames: list[pd.DataFrame] = []
    for (model_name, family), payload in poisson_fitted.items():
        result = payload["result"]
        cluster_result = payload.get("cluster_result")
        diagnostics_rows.append(_diagnostics_for_result(model_name, family, result, model_input))
        coef_rows.extend(_coef_rows(model_name, family, result, cluster_result))
        residual_frames.append(_residual_summary(model_name, family, result))
        influence_frames.append(_influence_queue(model_name, family, result, model_input))

    poisson_diagnostics = pd.DataFrame(diagnostics_rows)
    nb_fitted = attempt_negative_binomial(model_input, poisson_diagnostics, warnings_out)
    nb_attempted = bool(poisson_diagnostics["overdispersion_flag"].fillna(False).any())
    for (model_name, family), payload in nb_fitted.items():
        result = payload["result"]
        diagnostics_rows.append(_nb_diagnostics(model_name, family, result, model_input))
        coef_rows.extend(_nb_coef_rows(model_name, family, result))

    diagnostics = pd.DataFrame(diagnostics_rows)
    coefficients = pd.DataFrame(coef_rows)
    irr = coefficients[
        [
            "model_name",
            "model_family",
            "term",
            "incidence_rate_ratio",
            "irr_conf_int_lower",
            "irr_conf_int_upper",
            "p_value",
            "clustered_p_value",
            "reference_level_notes",
        ]
    ].copy()
    fit_summary = _fit_summary(diagnostics)
    overdispersion = diagnostics.loc[diagnostics["model_family"].eq("poisson_glm")][
        [
            "model_name",
            "pearson_chi_square",
            "residual_df",
            "pearson_overdispersion_ratio",
            "deviance",
            "deviance_overdispersion_ratio",
            "overdispersion_flag",
        ]
    ].copy()
    family_comparison = _family_comparison(diagnostics)
    residual_summary = pd.concat(residual_frames, ignore_index=True, sort=False) if residual_frames else pd.DataFrame()
    influence_queue = pd.concat(influence_frames, ignore_index=True, sort=False) if influence_frames else pd.DataFrame()
    if not influence_queue.empty:
        influence_queue = influence_queue.sort_values("cooks_distance", ascending=False).head(INFLUENCE_QUEUE_LIMIT)
    sparse = _sparse_summary(model_input)
    warnings_frame = pd.DataFrame(warnings_out)
    if warnings_frame.empty:
        warnings_frame = pd.DataFrame(columns=["model_name", "model_family", "warning_type", "warning_message"])

    guardrails = _guardrails()
    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "usecols excludes fields matching crash-direction tokens", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read or used", "required"),
            (
                "only_denominator_ready_signal_direction_window_rows_modeled",
                bool(model_input["denominator_ready_flag"].all() and set(model_input["analysis_window"].unique()).issubset({"high_priority_0_1000ft", "sensitivity_1000_2500ft"})),
                f"{len(model_input)} modeled rows",
                "all modeled rows denominator-ready window grain",
            ),
            ("no_distance_band_models_fit", True, "only signal-direction-window matrix was read", "required"),
            ("no_policy_ranking_language_introduced", True, "guardrail terms isolated in language table; findings constrained", "required"),
            ("no_rankings_created", True, "influence queue is model diagnostic review only", "required"),
            ("outputs_labeled_exploratory_internal_review_only", True, "findings and guardrails state exploratory/internal technical review only", "required"),
            ("source_context_assignment_data_not_modified", True, "read source matrices and wrote separate analysis folder only", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )
    findings = _findings(model_input, excluded, diagnostics, family_comparison, sparse, warnings_frame, nb_attempted)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "model_input_rows.csv": model_input,
        "model_input_excluded_rows.csv": excluded,
        "model_fit_summary.csv": fit_summary,
        "model_fit_coefficients.csv": coefficients,
        "model_fit_incidence_rate_ratios.csv": irr,
        "model_fit_diagnostics.csv": diagnostics,
        "model_overdispersion_summary.csv": overdispersion,
        "model_family_comparison.csv": family_comparison,
        "model_residual_summary.csv": residual_summary,
        "model_influence_review_queue.csv": influence_queue,
        "model_sparse_category_summary.csv": sparse,
        "model_convergence_warnings.csv": warnings_frame,
        "model_interpretation_guardrails.csv": guardrails,
        "crash_count_exploratory_model_fit_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_text(findings, OUTPUT_DIR / "crash_count_exploratory_model_fit_findings.md")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "first exploratory signal-direction-window crash-count model fit with exposure offset",
        "status": "exploratory_internal_technical_review_only",
        "inputs": [
            str(path)
            for path in [
                WINDOW_MATRIX_FILE,
                MODEL_SEQUENCE_FILE,
                VARIABLE_ROLE_FILE,
                MODEL_SPEC_FILE,
                SUPPRESSION_MANIFEST_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(path) for path in OUTPUT_DIR.glob("*")),
        "row_counts": {
            "source_matrix_rows": int(len(matrix)),
            "modeled_rows": int(len(model_input)),
            "excluded_rows": int(len(excluded)),
            "modeled_assigned_crashes": int(model_input["assigned_crash_count"].sum()),
        },
        "packages": {
            "statsmodels_available": _package_available("statsmodels"),
            "scipy_available": _package_available("scipy"),
            "patsy_available": _package_available("patsy"),
        },
        "model_sequence": MODEL_ORDER,
        "negative_binomial_attempted": nb_attempted,
        "guardrails": _guardrail_dict(models_fit=True),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "crash_count_exploratory_model_fit_manifest.json")
    return {
        "model_input": model_input,
        "excluded": excluded,
        "diagnostics": diagnostics,
        "family_comparison": family_comparison,
        "warnings": warnings_frame,
        "qa": qa,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit exploratory signal-direction-window crash-count models with diagnostics.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
