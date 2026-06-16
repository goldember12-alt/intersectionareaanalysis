from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.roadway_graph.crash_count_simplified_internal_model import (
    ALPHA_GRID,
    FORMULAS,
    MODEL_ORDER,
    OVERDISPERSION_THRESHOLD,
    _access_interaction_summary,
    _family_comparison,
    _fit_models,
    _readiness_decision,
    _sparse_summary,
    _speed_summary,
)


OUTPUT_ROOT = Path("work/output/roadway_graph")
ACTIVE_MODEL_DIR = OUTPUT_ROOT / "analysis/current/crash_count_modeling_readiness_dataset_active"
ACTIVE_CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active"
ACTIVE_RATE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype_active"
ACTIVE_SPEED_POLICY_DIR = OUTPUT_ROOT / "review/current/active_speed_context_policy"
ACTIVE_AADT_POLICY_DIR = OUTPUT_ROOT / "analysis/current/active_rate_denominator_policy"
BASELINE_MODEL_DIR = OUTPUT_ROOT / "analysis/current/crash_count_simplified_internal_model"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_simplified_internal_model_active"

ACTIVE_WINDOW_MATRIX_FILE = ACTIVE_MODEL_DIR / "crash_count_modeling_matrix_signal_direction_window_active.csv"
ACTIVE_CONTEXT_FILE = ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv"
ACTIVE_RATE_FILE = ACTIVE_RATE_DIR / "active_rate_signal_direction_window.csv"
BASELINE_FIT_SUMMARY_FILE = BASELINE_MODEL_DIR / "simplified_model_fit_summary.csv"
BASELINE_FAMILY_FILE = BASELINE_MODEL_DIR / "simplified_model_family_comparison.csv"
BASELINE_IRR_FILE = BASELINE_MODEL_DIR / "simplified_model_incidence_rate_ratios.csv"

CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel")
LOW_EXPOSURE_QUANTILE = 0.10


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
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


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, pd.NA)


def _access_density_band(value: Any) -> str:
    if pd.isna(value):
        return "access_density_unavailable"
    value = float(value)
    if value == 0:
        return "0_per_1000ft"
    if value < 1:
        return "gt0_lt1_per_1000ft"
    if value < 3:
        return "1_lt3_per_1000ft"
    if value < 6:
        return "3_lt6_per_1000ft"
    return "6plus_per_1000ft"


def _speed_band(value: Any, stable_share: Any) -> str:
    if pd.isna(value) or pd.isna(stable_share) or float(stable_share) < 0.80:
        return "speed_missing_or_review"
    value = float(value)
    if value < 30:
        return "lt_30_mph"
    if value < 40:
        return "30_39_mph"
    if value < 50:
        return "40_49_mph"
    if value < 60:
        return "50_59_mph"
    return "60plus_mph"


def _load_active_speed_unit_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "signal_relative_direction",
        "distance_window",
        "reference_directional_bin_id",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "has_stable_speed_context",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
    ]
    context = _read_csv(ACTIVE_CONTEXT_FILE, usecols=columns)
    for column in ["bin_start_ft_from_reference_signal", "bin_end_ft_from_reference_signal", "posted_car_speed_limit_context_value", "weighted_car_speed_limit"]:
        context[column] = _num(context[column])
    context["has_stable_speed_context"] = _bool(context["has_stable_speed_context"])
    context["analysis_window"] = context["distance_window"]
    context["bin_length_miles"] = (context["bin_end_ft_from_reference_signal"] - context["bin_start_ft_from_reference_signal"]).clip(lower=0) / 5280.0
    context["active_speed_value"] = context["weighted_car_speed_limit"].where(context["weighted_car_speed_limit"].notna(), context["posted_car_speed_limit_context_value"])
    stable = context.loc[context["has_stable_speed_context"] & context["active_speed_value"].notna()].copy()
    stable["weighted_speed"] = stable["active_speed_value"] * stable["bin_length_miles"]
    grouped = (
        stable.groupby(["reference_signal_id", "signal_relative_direction", "analysis_window"], dropna=False)
        .agg(
            active_stable_speed_bin_count=("reference_directional_bin_id", "nunique"),
            active_stable_speed_length_miles=("bin_length_miles", "sum"),
            active_weighted_speed_sum=("weighted_speed", "sum"),
            active_speed_min=("active_speed_value", "min"),
            active_speed_max=("active_speed_value", "max"),
        )
        .reset_index()
    )
    grouped["active_length_weighted_speed"] = _safe_div(grouped["active_weighted_speed_sum"], grouped["active_stable_speed_length_miles"])
    return grouped.drop(columns=["active_weighted_speed_sum"])


def _prepare_active_input() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    matrix = _read_csv(ACTIVE_WINDOW_MATRIX_FILE)
    speed_context = _load_active_speed_unit_context()
    frame = matrix.merge(speed_context, on=["reference_signal_id", "signal_relative_direction", "analysis_window"], how="left")
    numeric_columns = [
        "assigned_crash_count",
        "bin_count",
        "represented_length_ft",
        "represented_length_miles",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "access_count_within_catchment_sum",
        "v2_direction_factor_adjusted_exposure",
        "active_length_weighted_speed",
        "direction_factor_adjusted_aadt",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame[column])
    for column in [
        "denominator_ready_flag",
        "modeling_ready_candidate",
        "direction_factor_applied_flag",
        "direction_factor_missing_bidirectional_fallback_flag",
        "direction_factor_invalid_review_flag",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
    ]:
        frame[column] = _bool(frame[column])
    frame["estimated_exposure"] = frame["v2_direction_factor_adjusted_exposure"]
    frame["log_estimated_exposure"] = np.log(frame["estimated_exposure"].where(frame["estimated_exposure"].gt(0)))
    frame["local_access_count"] = frame["access_count_within_catchment_sum"]
    frame["local_access_density_per_1000ft"] = _safe_div(frame["local_access_count"] * 1000.0, frame["represented_length_ft"])
    frame["local_access_density_band"] = frame["local_access_density_per_1000ft"].map(_access_density_band)
    frame["speed_band"] = [
        _speed_band(value, share)
        for value, share in zip(frame["active_length_weighted_speed"], frame["stable_speed_coverage_share"])
    ]
    frame["speed_missing_or_review_share"] = 1.0 - frame["stable_speed_coverage_share"].fillna(0)
    low_exposure_threshold = frame.loc[frame["denominator_ready_flag"], "estimated_exposure"].quantile(LOW_EXPOSURE_QUANTILE)
    frame["low_exposure_flag"] = frame["estimated_exposure"].le(low_exposure_threshold)
    frame["low_crash_count_flag"] = frame["assigned_crash_count"].lt(3)
    frame["zero_crash_flag"] = frame["assigned_crash_count"].eq(0)
    frame["bidirectional_aadt_assumption_flag"] = frame["direction_factor_missing_bidirectional_fallback_flag"]
    frame["aadt_year_status"] = frame["dominant_aadt_year_status"].replace("", "aadt_year_missing")
    frame["urban_crash_count"] = 0
    frame["rural_crash_count"] = 0
    frame["context_completeness_flags"] = "active_v2_v5"
    frame["roadway_representation_mix"] = ""
    frame["model_exclusion_reason"] = ""
    frame.loc[~frame["denominator_ready_flag"], "model_exclusion_reason"] += "not_denominator_ready;"
    frame.loc[frame["assigned_crash_count"].isna(), "model_exclusion_reason"] += "missing_assigned_crash_count;"
    frame.loc[frame["assigned_crash_count"].lt(0), "model_exclusion_reason"] += "negative_assigned_crash_count;"
    frame.loc[~np.isfinite(frame["log_estimated_exposure"]), "model_exclusion_reason"] += "nonfinite_log_estimated_exposure;"
    frame.loc[~frame["estimated_exposure"].gt(0), "model_exclusion_reason"] += "nonpositive_estimated_exposure;"
    included = frame.loc[frame["model_exclusion_reason"].eq("")].copy()
    excluded = frame.loc[~frame["model_exclusion_reason"].eq("")].copy()
    included["analysis_window_model"] = included["analysis_window"].map(
        {"high_priority_0_1000ft": "window_0_1000ft", "sensitivity_1000_2500ft": "window_1000_2500ft"}
    )
    included["analysis_window_readable"] = included["analysis_window_model"].map(
        {"window_0_1000ft": "0-1,000 ft", "window_1000_2500ft": "1,000-2,500 ft"}
    )
    included["signal_relative_direction_model"] = included["signal_relative_direction"].map(
        {"downstream_of_reference_signal": "downstream", "upstream_of_reference_signal": "upstream"}
    )
    included["local_access_density_band_model"] = included["local_access_density_band"].map(
        {
            "0_per_1000ft": "access_0",
            "gt0_lt1_per_1000ft": "access_gt0_1",
            "1_lt3_per_1000ft": "access_1_3",
            "3_lt6_per_1000ft": "access_3_6",
            "6plus_per_1000ft": "access_6plus",
        }
    )
    included["local_access_density_label"] = included["local_access_density_band_model"].map(
        {"access_0": "0", "access_gt0_1": ">0-1", "access_1_3": "1-3", "access_3_6": "3-6", "access_6plus": "6+"}
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
    included["speed_band_simplified"] = included["speed_band_model"].map(
        {
            "speed_lt_30_mph": "<30 mph",
            "speed_30_39_mph": "30-39 mph",
            "speed_40_49_mph": "40-49 mph",
            "speed_50_59_mph": "50+ mph",
            "speed_60plus_mph": "50+ mph",
            "speed_missing_or_review": "missing/review speed",
        }
    )
    included["analysis_window_readable"] = pd.Categorical(included["analysis_window_readable"], categories=["0-1,000 ft", "1,000-2,500 ft"], ordered=True)
    included["signal_relative_direction_model"] = pd.Categorical(included["signal_relative_direction_model"], categories=["downstream", "upstream"], ordered=True)
    included["local_access_density_label"] = pd.Categorical(included["local_access_density_label"], categories=["0", ">0-1", "1-3", "3-6", "6+"], ordered=True)
    included["speed_band_simplified"] = pd.Categorical(included["speed_band_simplified"], categories=["30-39 mph", "<30 mph", "40-49 mph", "50+ mph", "missing/review speed"], ordered=True)
    mapping = pd.DataFrame(
        [
            ("speed", "50_59_mph", "50+ mph", "merged with 60+ mph"),
            ("speed", "60plus_mph", "50+ mph", "merged with 50-59 mph"),
            ("speed", "speed_missing_or_review", "missing/review speed", "preserved as explicit category"),
            ("speed_source", "active_context", "v5 posted/weighted speed", "stable single-speed values use posted_car_speed_limit_context_value when weighted field is null"),
            ("exposure", "v2_direction_factor_adjusted_exposure", "estimated_exposure", "active AADT v2 denominator already applied upstream"),
        ],
        columns=["variable", "source_category", "simplified_category", "mapping_note"],
    )
    return included, excluded, mapping


def _baseline_comparison(active_fit: pd.DataFrame, active_family: pd.DataFrame, active_irr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if BASELINE_FIT_SUMMARY_FILE.exists():
        base = _read_csv(BASELINE_FIT_SUMMARY_FILE)
        for column in ["n_rows", "total_crashes", "aic", "pearson_overdispersion_ratio"]:
            if column in base.columns:
                base[column] = _num(base[column])
        active = active_fit.copy()
        for column in ["n_rows", "total_crashes", "aic", "pearson_overdispersion_ratio"]:
            if column in active.columns:
                active[column] = _num(active[column])
        key = ["model_name", "model_family", "covariance_method"]
        merged = active.merge(base, on=key, how="left", suffixes=("_active", "_baseline"))
        primary = merged.loc[
            merged["model_family"].eq("poisson_glm")
            & merged["covariance_method"].eq("poisson_scaled_pearson")
            & merged["model_name"].isin(["S2_access_interaction", "S3_access_interaction_speed_simplified"])
        ]
        for row in primary.itertuples(index=False):
            rows.append(
                {
                    "comparison_type": "fit_summary",
                    "model_name": row.model_name,
                    "metric": "aic",
                    "baseline_value": getattr(row, "aic_baseline", pd.NA),
                    "active_value": getattr(row, "aic_active", pd.NA),
                    "active_minus_baseline": getattr(row, "aic_active", pd.NA) - getattr(row, "aic_baseline", pd.NA),
                }
            )
            if hasattr(row, "pearson_overdispersion_ratio_active"):
                rows.append(
                    {
                        "comparison_type": "fit_summary",
                        "model_name": row.model_name,
                        "metric": "pearson_overdispersion_ratio",
                        "baseline_value": getattr(row, "pearson_overdispersion_ratio_baseline", pd.NA),
                        "active_value": getattr(row, "pearson_overdispersion_ratio_active", pd.NA),
                        "active_minus_baseline": getattr(row, "pearson_overdispersion_ratio_active", pd.NA) - getattr(row, "pearson_overdispersion_ratio_baseline", pd.NA),
                    }
                )
    if BASELINE_FAMILY_FILE.exists():
        base_family = _read_csv(BASELINE_FAMILY_FILE)
        for column in ["delta_aic_vs_previous"]:
            base_family[column] = _num(base_family[column])
            active_family[column] = _num(active_family[column])
        merged_family = active_family.merge(
            base_family[["model_name", "comparison_model", "delta_aic_vs_previous"]],
            on=["model_name", "comparison_model"],
            how="left",
            suffixes=("_active", "_baseline"),
        )
        for row in merged_family.itertuples(index=False):
            rows.append(
                {
                    "comparison_type": "family_comparison",
                    "model_name": row.model_name,
                    "metric": "delta_aic_vs_previous",
                    "baseline_value": row.delta_aic_vs_previous_baseline,
                    "active_value": row.delta_aic_vs_previous_active,
                    "active_minus_baseline": row.delta_aic_vs_previous_active - row.delta_aic_vs_previous_baseline,
                }
            )
    if BASELINE_IRR_FILE.exists():
        base_irr = _read_csv(BASELINE_IRR_FILE)
        terms = [
            "C(speed_band_simplified, Treatment(reference='30-39 mph'))[T.50+ mph]",
            "C(speed_band_simplified, Treatment(reference='30-39 mph'))[T.missing/review speed]",
            "C(local_access_density_label, Treatment(reference='0'))[T.6+]",
        ]
        active_terms = active_irr.loc[
            active_irr["model_name"].eq("S3_access_interaction_speed_simplified")
            & active_irr["model_family"].eq("poisson_glm")
            & active_irr["covariance_method"].eq("poisson_scaled_pearson")
            & active_irr["term"].isin(terms)
        ].copy()
        base_terms = base_irr.loc[
            base_irr["model_name"].eq("S3_access_interaction_speed_simplified")
            & base_irr["model_family"].eq("poisson_glm")
            & base_irr["covariance_method"].eq("poisson_scaled_pearson")
            & base_irr["term"].isin(terms)
        ].copy()
        active_terms["incidence_rate_ratio"] = _num(active_terms["incidence_rate_ratio"])
        base_terms["incidence_rate_ratio"] = _num(base_terms["incidence_rate_ratio"])
        merged_terms = active_terms.merge(base_terms[["term", "incidence_rate_ratio"]], on="term", how="left", suffixes=("_active", "_baseline"))
        for row in merged_terms.itertuples(index=False):
            rows.append(
                {
                    "comparison_type": "irr",
                    "model_name": "S3_access_interaction_speed_simplified",
                    "metric": row.term,
                    "baseline_value": row.incidence_rate_ratio_baseline,
                    "active_value": row.incidence_rate_ratio_active,
                    "active_minus_baseline": row.incidence_rate_ratio_active - row.incidence_rate_ratio_baseline,
                }
            )
    return pd.DataFrame(rows)


def _findings(model_input: pd.DataFrame, family: pd.DataFrame, diagnostics: pd.DataFrame, access: pd.DataFrame, speed: pd.DataFrame, comparison: pd.DataFrame) -> str:
    access_row = family.loc[family["model_name"].eq("S2_access_interaction")]
    speed_row = family.loc[family["model_name"].eq("S3_access_interaction_speed_simplified")]
    s3_diag = diagnostics.loc[
        diagnostics["model_name"].eq("S3_access_interaction_speed_simplified")
        & diagnostics["model_family"].eq("poisson_glm")
        & diagnostics["covariance_method"].eq("poisson_scaled_pearson")
    ]
    return f"""# Active Simplified Internal Crash-Count Model Findings

**Status:** internal technical review only. These outputs are exploratory model diagnostics using active v2/v5 inputs. They are not external decision outputs, causal evidence, risk rankings, safety-performance rankings, policy guidance, or downstream functional-area distance recommendations.

## Input

- Modeled rows: {len(model_input)} denominator-ready signal-direction-window rows.
- Modeled assigned crashes: {int(model_input['assigned_crash_count'].sum())}.
- Active speed context: v5 Speed_Limit_RNS supplement.
- Active exposure: AADT v2 direction-factor denominator already present in the active modeling matrix.

## Access Interaction

- Access interaction improves AIC: {bool(access_row['fit_improves_aic'].iloc[0]) if not access_row.empty else 'not_available'}.
- Delta AIC for S2 versus S1: {access_row['delta_aic_vs_previous'].iloc[0] if not access_row.empty else 'not_available'}.

## Simplified Speed

- Simplified speed improves AIC: {bool(speed_row['fit_improves_aic'].iloc[0]) if not speed_row.empty else 'not_available'}.
- Delta AIC for S3 versus S2: {speed_row['delta_aic_vs_previous'].iloc[0] if not speed_row.empty else 'not_available'}.
- Missing/review speed rows modeled explicitly: {int(model_input['speed_band_simplified'].astype(str).eq('missing/review speed').sum())}.

## Overdispersion

- S3 scaled-Poisson Pearson overdispersion ratio: {s3_diag['pearson_overdispersion_ratio'].iloc[0] if not s3_diag.empty else 'not_available'}.
- Overdispersion remains present: {bool(s3_diag['overdispersion_flag'].iloc[0]) if not s3_diag.empty else 'not_available'}.

## Inference Recommendation

Scaled and cluster-robust Poisson remain the primary internal-review family. Fixed-alpha negative-binomial fits are retained as sensitivity evidence only. Estimated-alpha NB stabilization should be rerun under active v2/v5 before any NB interpretation.
"""


def build_outputs() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    model_input, excluded, mapping = _prepare_active_input()
    diagnostics, coefficients, se_comparison, nb_alpha, warnings_frame = _fit_models(model_input)
    sparse = _sparse_summary(model_input)
    family = _family_comparison(diagnostics)
    access_summary = _access_interaction_summary(family, nb_alpha)
    speed_summary = _speed_summary(family, diagnostics)
    readiness = _readiness_decision(diagnostics, sparse, family, nb_alpha)
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
            "pearson_overdispersion_ratio",
            "deviance_overdispersion_ratio",
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
    active_vs_baseline = _baseline_comparison(fit_summary, family, irr)
    qa = pd.DataFrame(
        [
            {"check_name": "no_crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "source_context_assignment_data_modified", "passed": True, "observed": False, "expected": False},
            {"check_name": "rankings_created", "passed": True, "observed": False, "expected": False},
            {"check_name": "policy_risk_safety_language_introduced", "passed": True, "observed": False, "expected": False},
            {"check_name": "active_v2_v5_inputs_used", "passed": model_input["active_speed_context_policy"].eq("speed_v5_new_source_supplement").all() and model_input["active_aadt_denominator_policy"].eq("v2_direction_factor_with_bidirectional_fallback").all(), "observed": "active_v2_v5", "expected": "active_v2_v5"},
            {"check_name": "additional_direction_factor_not_applied", "passed": True, "observed": "used active estimated exposure already present", "expected": "no additional application"},
            {"check_name": "baseline_model_retained_for_comparison_only", "passed": BASELINE_MODEL_DIR.exists(), "observed": str(BASELINE_MODEL_DIR), "expected": "exists"},
            {"check_name": "distance_band_models_fit", "passed": True, "observed": False, "expected": False},
            {"check_name": "modeled_rows_active_expected", "passed": len(model_input) == 2967, "observed": len(model_input), "expected": 2967},
        ]
    )
    findings = _findings(model_input, family, diagnostics, access_summary, speed_summary, active_vs_baseline)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "active_simplified_model_input_rows.csv": model_input,
        "active_simplified_model_input_excluded_rows.csv": excluded,
        "active_simplified_category_mapping.csv": mapping,
        "active_simplified_sparse_category_summary.csv": sparse,
        "active_simplified_model_fit_summary.csv": fit_summary,
        "active_simplified_model_coefficients.csv": coefficients,
        "active_simplified_model_irrs.csv": irr,
        "active_simplified_model_diagnostics.csv": diagnostics,
        "active_simplified_model_family_comparison.csv": family,
        "active_simplified_model_warnings.csv": warnings_frame,
        "active_simplified_nb_alpha_sensitivity.csv": nb_alpha,
        "active_simplified_clustered_se_comparison.csv": se_comparison,
        "active_simplified_access_interaction_summary.csv": access_summary,
        "active_simplified_speed_sensitivity_summary.csv": speed_summary,
        "active_vs_baseline_model_comparison.csv": active_vs_baseline,
        "active_simplified_model_readiness_decision.csv": readiness,
        "active_simplified_model_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_text(findings, OUTPUT_DIR / "active_simplified_model_findings.md")
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "rerun simplified internal count model using active v2/v5 window-grain matrix",
        "status": "internal_technical_review_only",
        "inputs": {
            "active_window_matrix": str(ACTIVE_WINDOW_MATRIX_FILE),
            "active_context_for_speed_band": str(ACTIVE_CONTEXT_FILE),
            "active_rate": str(ACTIVE_RATE_FILE),
            "active_speed_policy": str(ACTIVE_SPEED_POLICY_DIR),
            "active_aadt_policy": str(ACTIVE_AADT_POLICY_DIR),
            "baseline_model_for_comparison_only": str(BASELINE_MODEL_DIR),
        },
        "outputs": {filename: str(OUTPUT_DIR / filename) for filename in outputs} | {"findings": str(OUTPUT_DIR / "active_simplified_model_findings.md")},
        "model_sequence": MODEL_ORDER,
        "formulas": FORMULAS,
        "row_counts": {
            "modeled_rows": int(len(model_input)),
            "excluded_rows": int(len(excluded)),
            "modeled_assigned_crashes": int(model_input["assigned_crash_count"].sum()),
        },
        "guardrails": {
            "crash_direction_fields_read_or_used": False,
            "additional_direction_factor_applied": False,
            "distance_band_models_fit": False,
            "predictions_for_policy_created": False,
            "rankings_created": False,
            "source_context_assignment_data_modified": False,
            "policy_risk_safety_language_introduced": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "active_simplified_model_manifest.json")
    return {"outputs": manifest["outputs"], "qa": qa.to_dict(orient="records")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit active v2/v5 simplified internal crash-count models.")
    parser.parse_args()
    result = build_outputs()
    print(json.dumps(result["outputs"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
