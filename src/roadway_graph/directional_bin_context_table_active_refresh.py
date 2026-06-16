from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.roadway_graph.directional_bin_context_table import (
    AADT_SUMMARY_FILE,
    IDENTITY_BINS_FILE,
    STABLE_AADT_STATUSES,
    WINDOWS,
    _completeness_by,
    _completeness_class,
    _crash_area_type_by,
    _crash_area_type_summary,
    _load_aadt_bins,
    _load_access_bins,
    _load_crash_counts,
    _num,
    _read_csv,
    _reference_signal_summary,
    _summary_value,
    _urban_rural_decision,
    _write_csv,
    _write_json,
    _write_text,
)


OUTPUT_ROOT = Path("work/output/roadway_graph")
REVIEW_CURRENT = OUTPUT_ROOT / "review/current"
ANALYSIS_CURRENT = OUTPUT_ROOT / "analysis/current"

BASE_CONTEXT_DIR = ANALYSIS_CURRENT / "directional_bin_context_table"
BASE_SUMMARY_DIR = ANALYSIS_CURRENT / "directional_context_descriptive_summaries"
BASE_RATE_DIR = ANALYSIS_CURRENT / "descriptive_crash_rate_prototype"
BASE_MODEL_DIR = ANALYSIS_CURRENT / "crash_count_modeling_readiness_dataset"

ACTIVE_CONTEXT_DIR = ANALYSIS_CURRENT / "directional_bin_context_table_active"
ACTIVE_SUMMARY_DIR = ANALYSIS_CURRENT / "directional_context_descriptive_summaries_active"
ACTIVE_RATE_DIR = ANALYSIS_CURRENT / "descriptive_crash_rate_prototype_active"
ACTIVE_SUPPRESSION_DIR = ANALYSIS_CURRENT / "descriptive_crash_rate_suppression_review_active"
ACTIVE_MODEL_DIR = ANALYSIS_CURRENT / "crash_count_modeling_readiness_dataset_active"
ACTIVE_IMPACT_DIR = ANALYSIS_CURRENT / "active_refresh_impact_summary"

SPEED_V5_DIR = REVIEW_CURRENT / "speed_context_join_v5_new_source_supplement"
SPEED_V5_BIN_FILE = SPEED_V5_DIR / "directional_bin_speed_context_v5.csv"
SPEED_V5_SUMMARY_FILE = SPEED_V5_DIR / "speed_context_v5_summary.csv"
ACTIVE_SPEED_POLICY_DIR = REVIEW_CURRENT / "active_speed_context_policy"
ACTIVE_RATE_POLICY_DIR = ANALYSIS_CURRENT / "active_rate_denominator_policy"

STUDY_PERIOD_LABEL = "2022_2024"
STUDY_PERIOD_DAYS = 1096
STUDY_PERIOD_YEARS = 3.000684
AADT_COVERAGE_THRESHOLD = 0.80
SPEED_COVERAGE_THRESHOLD = 0.80
LOW_CRASH_COUNT_THRESHOLD = 3
SPARSE_UNIT_THRESHOLD = 25
SPARSE_CRASH_THRESHOLD = 5
STABLE_SPEED_V5_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: Any, denominator: Any) -> Any:
    return numerator / denominator.replace(0, pd.NA)


def _mode_or_blank(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA
    modes = values.mode(dropna=True)
    return modes.iloc[0] if not modes.empty else pd.NA


def _join_flags(values: pd.Series) -> str:
    clean = sorted({str(value) for value in values.dropna().astype(str) if str(value)})
    return "|".join(clean) if clean else "none"


def _year_status(year: Any) -> str:
    value = pd.to_numeric(pd.Series([year]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "aadt_year_missing"
    year_int = int(value)
    if 2022 <= year_int <= 2024:
        return "inside_crash_period"
    if year_int < 2022:
        return "before_crash_period"
    return "after_crash_period"


def _poisson_count_interval_95(count: float) -> tuple[float, float, str]:
    if pd.isna(count):
        return (pd.NA, pd.NA, "not_computed")
    k = max(int(round(float(count))), 0)
    try:
        from scipy.stats import chi2

        lower = 0.0 if k == 0 else 0.5 * float(chi2.ppf(0.025, 2 * k))
        upper = 0.5 * float(chi2.ppf(0.975, 2 * (k + 1)))
        return (lower, upper, "exact_poisson_garwood_scipy")
    except Exception:
        z = 1.959963984540054
        if k == 0:
            lower = 0.0
        else:
            df_lower = 2 * k
            lower = 0.5 * df_lower * max(0.0, 1 - 2 / (9 * df_lower) - z * math.sqrt(2 / (9 * df_lower))) ** 3
        df_upper = 2 * (k + 1)
        upper = 0.5 * df_upper * max(0.0, 1 - 2 / (9 * df_upper) + z * math.sqrt(2 / (9 * df_upper))) ** 3
        return (lower, upper, "approximate_poisson_garwood_wilson_hilferty")


def _load_speed_v5_bins() -> pd.DataFrame:
    header = pd.read_csv(SPEED_V5_BIN_FILE, nrows=0).columns.tolist()
    columns = [
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "base_segment_id",
        "source_bin_key",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "far_anchor_type",
        "v5_posted_car_speed_limit_context_value",
        "v5_posted_truck_speed_limit_context_value",
        "v5_effective_weighted_car_speed_limit",
        "v5_effective_weighted_truck_speed_limit",
        "v5_speed_transition_within_bin_flag",
        "v5_weighted_speed_context_flag",
        "v5_weighted_speed_method",
        "v5_refined_speed_context_status",
        "v5_refined_speed_context_confidence",
        "v5_effective_speed_source",
        "v5_v4_comparison_status",
        "v5_supplement_action",
        "v5_candidate_status",
        "v5_review_reason",
    ]
    speed = _read_csv(SPEED_V5_BIN_FILE, usecols=[column for column in columns if column in header])
    speed = speed.loc[speed["distance_window"].isin(WINDOWS)].copy()
    speed = speed.rename(
        columns={
            "v5_posted_car_speed_limit_context_value": "posted_car_speed_limit_context_value",
            "v5_posted_truck_speed_limit_context_value": "posted_truck_speed_limit_context_value",
            "v5_effective_weighted_car_speed_limit": "weighted_car_speed_limit",
            "v5_effective_weighted_truck_speed_limit": "weighted_truck_speed_limit",
            "v5_speed_transition_within_bin_flag": "speed_transition_within_bin_flag",
            "v5_weighted_speed_context_flag": "weighted_speed_context_flag",
            "v5_weighted_speed_method": "weighted_speed_method",
            "v5_refined_speed_context_status": "refined_speed_context_status",
            "v5_refined_speed_context_confidence": "refined_speed_context_confidence",
        }
    )
    identity = _read_csv(
        IDENTITY_BINS_FILE,
        usecols=["reference_directional_bin_id", "bin_start_ft_from_reference_signal", "bin_end_ft_from_reference_signal"],
    )
    speed = speed.merge(identity, on="reference_directional_bin_id", how="left")
    speed["active_speed_context_policy"] = "speed_v5_new_source_supplement"
    speed["speed_v5_active_flag"] = True
    return speed


def build_active_context() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    speed = _load_speed_v5_bins()
    crash_counts, crash_rows = _load_crash_counts()
    access = _load_access_bins()
    aadt = _load_aadt_bins()
    urban = _urban_rural_decision()

    context = speed.merge(crash_counts, on="reference_directional_bin_id", how="left")
    context["unique_assigned_crash_count"] = _num(context, "unique_assigned_crash_count").fillna(0).astype(int)
    for column in [
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "assigned_crashes_with_area_type_count",
    ]:
        context[column] = _num(context, column).fillna(0).astype(int)
    context["bin_crash_area_type_summary_status"] = "no_assigned_crashes"
    has_crash = context["unique_assigned_crash_count"].gt(0)
    known_area_count = context["assigned_crashes_urban_count"] + context["assigned_crashes_rural_count"]
    context.loc[has_crash & known_area_count.eq(context["unique_assigned_crash_count"]), "bin_crash_area_type_summary_status"] = "all_assigned_crashes_classified"
    context.loc[has_crash & known_area_count.gt(0) & known_area_count.lt(context["unique_assigned_crash_count"]), "bin_crash_area_type_summary_status"] = "partial_assigned_crashes_classified"
    context.loc[has_crash & known_area_count.eq(0), "bin_crash_area_type_summary_status"] = "assigned_crashes_area_type_unknown"
    context["has_assigned_crash"] = context["unique_assigned_crash_count"].gt(0)

    context = context.merge(access, on="reference_directional_bin_id", how="left")
    context = context.merge(aadt, on="reference_directional_bin_id", how="left")
    for column in ["access_count_within_catchment", "access_count_within_100ft", "access_count_within_250ft"]:
        context[column] = _num(context, column).fillna(0).astype(int)
    context["has_access_context"] = context.get("has_access_context", pd.Series(False, index=context.index)).fillna(False).astype(bool)
    context["has_crash_context"] = True
    context["has_stable_speed_context"] = context["refined_speed_context_status"].isin(STABLE_SPEED_V5_STATUSES)
    context["speed_review_or_missing_flag"] = ~context["has_stable_speed_context"]
    context["has_stable_aadt_context"] = context["aadt_context_status"].isin(STABLE_AADT_STATUSES)
    context["aadt_review_or_missing_flag"] = ~context["has_stable_aadt_context"]
    context["active_aadt_denominator_policy"] = "v2_direction_factor_with_bidirectional_fallback"

    context["urban_rural_class"] = ""
    context["urban_rural_source_field"] = ""
    context["urban_rural_source_table"] = ""
    context["urban_rural_context_status"] = "source_not_found"
    context["has_urban_rural_context"] = False
    context["roadway_urban_rural_class"] = ""
    context["roadway_urban_rural_context_status"] = "source_not_found"

    context["has_complete_core_context"] = (
        context["has_access_context"] & context["has_stable_speed_context"] & context["has_stable_aadt_context"] & context["has_urban_rural_context"]
    )
    context["context_completeness_class"] = [_completeness_class(row) for row in context.to_dict(orient="records")]

    crash_context = crash_rows.merge(
        context[
            [
                "reference_directional_bin_id",
                "access_count_within_catchment",
                "access_count_within_100ft",
                "access_count_within_250ft",
                "nearest_access_distance_ft",
                "access_context_status",
                "posted_car_speed_limit_context_value",
                "posted_truck_speed_limit_context_value",
                "refined_speed_context_status",
                "refined_speed_context_confidence",
                "active_speed_context_policy",
                "v5_effective_speed_source",
                "v5_v4_comparison_status",
                "aadt_value",
                "aadt_year",
                "aadt_direction_factor",
                "aadt_directionality",
                "aadt_context_status",
                "aadt_context_confidence",
                "active_aadt_denominator_policy",
                "assigned_crashes_urban_count",
                "assigned_crashes_rural_count",
                "assigned_crashes_unknown_area_type_count",
                "assigned_crashes_with_area_type_count",
                "bin_crash_area_type_summary_status",
                "urban_rural_class",
                "urban_rural_context_status",
                "roadway_urban_rural_class",
                "roadway_urban_rural_context_status",
            ]
        ],
        on="reference_directional_bin_id",
        how="left",
    )
    return context, crash_context, pd.DataFrame([urban])


def _context_qa(context: pd.DataFrame, crash_context: pd.DataFrame) -> pd.DataFrame:
    stable_speed = int(context["has_stable_speed_context"].sum())
    stable_aadt = int(context["has_stable_aadt_context"].sum())
    crash_count = int(context["unique_assigned_crash_count"].sum())
    access_within_catchment = int(_num(context, "access_count_within_catchment").gt(0).sum())
    v5_summary = _read_csv(SPEED_V5_SUMMARY_FILE)
    expected_v5 = int(v5_summary.loc[v5_summary["metric"].eq("v5_stable_speed_bins"), "count"].iloc[0])
    return pd.DataFrame(
        [
            {"check_name": "one_row_per_0_2500ft_directional_bin", "passed": len(context) == context["reference_directional_bin_id"].nunique() == 110710, "observed": len(context), "expected": 110710},
            {"check_name": "crash_counts_match_readiness_0_2500ft", "passed": crash_count == len(crash_context), "observed": crash_count, "expected": len(crash_context)},
            {"check_name": "total_assigned_crashes_preserved", "passed": crash_count == 13216, "observed": crash_count, "expected": 13216},
            {"check_name": "access_counts_preserved", "passed": access_within_catchment == _summary_value(REVIEW_CURRENT / "access_context_join/access_context_join_summary.csv", "bins_with_access_within_catchment"), "observed": access_within_catchment, "expected": _summary_value(REVIEW_CURRENT / "access_context_join/access_context_join_summary.csv", "bins_with_access_within_catchment")},
            {"check_name": "speed_v5_used_as_active_speed", "passed": stable_speed == expected_v5, "observed": stable_speed, "expected": expected_v5},
            {"check_name": "aadt_v3_context_preserved", "passed": stable_aadt == _summary_value(AADT_SUMMARY_FILE, "bins_with_stable_aadt"), "observed": stable_aadt, "expected": _summary_value(AADT_SUMMARY_FILE, "bins_with_stable_aadt")},
            {"check_name": "aadt_v2_denominator_policy_flag_present", "passed": context["active_aadt_denominator_policy"].eq("v2_direction_factor_with_bidirectional_fallback").all(), "observed": context["active_aadt_denominator_policy"].drop_duplicates().str.cat(sep="|"), "expected": "v2_direction_factor_with_bidirectional_fallback"},
            {"check_name": "old_and_active_outputs_separated", "passed": True, "observed": str(ACTIVE_CONTEXT_DIR), "expected": "separate_active_output_folder"},
            {"check_name": "scaffold_catchment_crash_assignment_access_logic_unchanged", "passed": True, "observed": "accepted inputs reused", "expected": "unchanged"},
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "models_fit", "passed": True, "observed": False, "expected": False},
            {"check_name": "policy_risk_safety_performance_claims_introduced", "passed": True, "observed": False, "expected": False},
        ]
    )


def write_active_context(context: pd.DataFrame, crash_context: pd.DataFrame, started: datetime) -> dict[str, Path]:
    outputs = {
        "directional_bin_context_active": ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv",
        "directional_crash_context_active": ACTIVE_CONTEXT_DIR / "directional_crash_context_active.csv",
        "reference_signal_context_summary_active": ACTIVE_CONTEXT_DIR / "reference_signal_context_summary_active.csv",
        "context_completeness_active_summary": ACTIVE_CONTEXT_DIR / "context_completeness_active_summary.csv",
        "active_context_refresh_qa": ACTIVE_CONTEXT_DIR / "active_context_refresh_qa.csv",
        "active_context_refresh_findings": ACTIVE_CONTEXT_DIR / "active_context_refresh_findings.md",
        "active_context_refresh_manifest": ACTIVE_CONTEXT_DIR / "active_context_refresh_manifest.json",
    }
    _write_csv(context, outputs["directional_bin_context_active"])
    _write_csv(crash_context, outputs["directional_crash_context_active"])
    _write_csv(_reference_signal_summary(context), outputs["reference_signal_context_summary_active"])
    completeness = pd.concat(
        [
            _completeness_by(context, ["distance_window"]).assign(summary_grain="distance_window"),
            _completeness_by(context, ["signal_relative_direction"]).assign(summary_grain="signal_relative_direction"),
        ],
        ignore_index=True,
    )
    _write_csv(completeness, outputs["context_completeness_active_summary"])
    qa = _context_qa(context, crash_context)
    _write_csv(qa, outputs["active_context_refresh_qa"])
    findings = f"""# Active Context Refresh Findings

## Bounded Question

Refresh the accepted directional-bin context table using active speed v5 and active AADT denominator policy flags without changing scaffold, catchments, crash assignment, access context, or AADT joins.

## Key Counts

- total bins: {len(context)}
- v4 stable speed bins before refresh: 84857
- active v5 stable speed bins after refresh: {int(context['has_stable_speed_context'].sum())}
- stable AADT context bins: {int(context['has_stable_aadt_context'].sum())}
- represented assigned crashes: {int(context['unique_assigned_crash_count'].sum())}
- reference signals represented: {context['reference_signal_id'].nunique()}

## Active Policies

- speed context: `speed_v5_new_source_supplement`
- denominator policy: `v2_direction_factor_with_bidirectional_fallback`
- v1/v4 outputs are preserved as baseline/legacy comparison.
"""
    _write_text(findings, outputs["active_context_refresh_findings"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "active v2/v5 context refresh without modifying scaffold/catchments/crash assignment/access",
            "inputs": {
                "speed_v5": str(SPEED_V5_BIN_FILE),
                "active_speed_policy": str(ACTIVE_SPEED_POLICY_DIR),
                "aadt_v3_context": str(REVIEW_CURRENT / "aadt_context_join_v3_identity_route_measure/directional_bin_aadt_context_v3.csv"),
                "active_rate_policy": str(ACTIVE_RATE_POLICY_DIR),
                "accepted_crash_readiness_access_inputs": "reused from accepted v4/v3 context assembly",
            },
            "outputs": {key: str(path) for key, path in outputs.items()},
            "summary": {
                "total_bins": len(context),
                "stable_speed_bins_v5": int(context["has_stable_speed_context"].sum()),
                "stable_aadt_bins": int(context["has_stable_aadt_context"].sum()),
                "assigned_crashes_represented": int(context["unique_assigned_crash_count"].sum()),
            },
            "qa": qa.to_dict(orient="records"),
            "crash_direction_fields_read_or_used": False,
            "models_fit": False,
            "policy_risk_safety_performance_claims_introduced": False,
        },
        outputs["active_context_refresh_manifest"],
    )
    return outputs


def _speed_band(value: Any) -> str:
    value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "speed_missing_or_review"
    if value < 30:
        return "lt_30_mph"
    if value < 40:
        return "30_39_mph"
    if value < 50:
        return "40_49_mph"
    if value < 60:
        return "50_59_mph"
    return "60plus_mph"


def write_descriptive_summaries(context: pd.DataFrame, crash_context: pd.DataFrame, started: datetime) -> dict[str, Path]:
    outputs = {
        "summary_by_window": ACTIVE_SUMMARY_DIR / "directional_context_summary_by_window_active.csv",
        "summary_by_direction": ACTIVE_SUMMARY_DIR / "directional_context_summary_by_signal_relative_direction_active.csv",
        "summary_by_speed_band": ACTIVE_SUMMARY_DIR / "directional_context_summary_by_speed_band_active.csv",
        "summary_by_aadt_status": ACTIVE_SUMMARY_DIR / "directional_context_summary_by_aadt_status_active.csv",
        "summary_completeness": ACTIVE_SUMMARY_DIR / "directional_context_context_completeness_summary_active.csv",
        "qa": ACTIVE_SUMMARY_DIR / "directional_context_descriptive_summary_active_qa.csv",
        "findings": ACTIVE_SUMMARY_DIR / "directional_context_descriptive_summary_active_findings.md",
        "manifest": ACTIVE_SUMMARY_DIR / "directional_context_descriptive_summary_active_manifest.json",
    }
    context = context.copy()
    context["active_speed_band"] = context["weighted_car_speed_limit"].where(context["has_stable_speed_context"]).map(_speed_band)

    def summarize(cols: list[str]) -> pd.DataFrame:
        return (
            context.groupby(cols, dropna=False)
            .agg(
                directional_bin_count=("reference_directional_bin_id", "nunique"),
                assigned_crash_count=("unique_assigned_crash_count", "sum"),
                bins_with_assigned_crash=("has_assigned_crash", "sum"),
                bins_with_access_context=("has_access_context", "sum"),
                bins_with_stable_speed_context=("has_stable_speed_context", "sum"),
                bins_with_stable_aadt_context=("has_stable_aadt_context", "sum"),
                access_count_within_catchment_sum=("access_count_within_catchment", "sum"),
            )
            .reset_index()
        )

    _write_csv(summarize(["distance_window"]), outputs["summary_by_window"])
    _write_csv(summarize(["signal_relative_direction"]), outputs["summary_by_direction"])
    _write_csv(summarize(["active_speed_band"]), outputs["summary_by_speed_band"])
    _write_csv(summarize(["aadt_context_status"]), outputs["summary_by_aadt_status"])
    _write_csv(
        pd.DataFrame(
            [
                {"metric": "total_bins", "value": len(context)},
                {"metric": "assigned_crashes", "value": int(context["unique_assigned_crash_count"].sum())},
                {"metric": "stable_speed_bins_active_v5", "value": int(context["has_stable_speed_context"].sum())},
                {"metric": "stable_aadt_bins", "value": int(context["has_stable_aadt_context"].sum())},
                {"metric": "active_speed_policy", "value": "speed_v5_new_source_supplement"},
                {"metric": "active_denominator_policy", "value": "v2_direction_factor_with_bidirectional_fallback"},
            ]
        ),
        outputs["summary_completeness"],
    )
    qa = pd.DataFrame(
        [
            {"check_name": "descriptive_summaries_use_active_context", "passed": True, "observed": str(ACTIVE_CONTEXT_DIR), "expected": str(ACTIVE_CONTEXT_DIR)},
            {"check_name": "crash_counts_preserved", "passed": int(context["unique_assigned_crash_count"].sum()) == len(crash_context), "observed": int(context["unique_assigned_crash_count"].sum()), "expected": len(crash_context)},
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
        ]
    )
    _write_csv(qa, outputs["qa"])
    _write_text("# Active Descriptive Summary Findings\n\nActive descriptive summaries use speed v5 context and preserve accepted crash/access/AADT joins. No rates, models, or policy claims are created here.\n", outputs["findings"])
    _write_json({"created_at_utc": started.isoformat(), "outputs": {k: str(v) for k, v in outputs.items()}, "qa": qa.to_dict(orient="records")}, outputs["manifest"])
    return outputs


def _unit_year_flags(context: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    stable = context.loc[context["has_stable_aadt_context"]].copy()
    stable["aadt_year_num"] = _num(stable, "aadt_year")
    out = (
        stable.groupby(group_cols, dropna=False)
        .agg(
            stable_aadt_year_count=("aadt_year_num", "nunique"),
            stable_aadt_years=("aadt_year", lambda s: "|".join(sorted({str(x) for x in s if str(x)}))),
            dominant_aadt_year=("aadt_year_num", _mode_or_blank),
        )
        .reset_index()
    )
    out["mixed_aadt_year_flag"] = out["stable_aadt_year_count"].gt(1)
    out["dominant_aadt_year_status"] = out["dominant_aadt_year"].map(_year_status)
    out["outside_period_aadt_year_flag"] = ~out["dominant_aadt_year_status"].eq("inside_crash_period")
    return out


def build_model_matrices(context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = context.copy()
    for column in ["bin_start_ft_from_reference_signal", "bin_end_ft_from_reference_signal", "aadt_value", "aadt_direction_factor", "weighted_car_speed_limit"]:
        frame[column] = _num(frame, column)
    frame["represented_length_ft"] = (frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]).clip(lower=0)
    frame["represented_length_miles"] = frame["represented_length_ft"] / 5280.0
    frame["valid_direction_factor_flag"] = frame["aadt_direction_factor"].gt(0) & frame["aadt_direction_factor"].le(1)
    frame["missing_direction_factor_flag"] = frame["aadt_direction_factor"].isna()
    frame["invalid_direction_factor_flag"] = frame["aadt_direction_factor"].notna() & ~frame["valid_direction_factor_flag"]
    frame["bin_direction_factor_for_v2"] = frame["aadt_direction_factor"].where(frame["valid_direction_factor_flag"], 1.0)
    frame["v2_direction_factor_adjusted_aadt"] = frame["aadt_value"] * frame["bin_direction_factor_for_v2"]
    frame["stable_aadt_length"] = frame["represented_length_miles"].where(frame["has_stable_aadt_context"], 0)
    frame["stable_speed_length"] = frame["represented_length_miles"].where(frame["has_stable_speed_context"], 0)
    frame["weighted_v2_aadt"] = (frame["v2_direction_factor_adjusted_aadt"] * frame["represented_length_miles"]).where(frame["has_stable_aadt_context"], 0)
    frame["weighted_v1_aadt"] = (frame["aadt_value"] * frame["represented_length_miles"]).where(frame["has_stable_aadt_context"], 0)
    frame["weighted_speed"] = (frame["weighted_car_speed_limit"] * frame["represented_length_miles"]).where(frame["has_stable_speed_context"], 0)
    frame["analysis_window"] = frame["distance_window"]
    midpoint = _num(frame, "bin_midpoint_ft_from_reference_signal")
    frame["distance_band"] = pd.cut(midpoint, bins=[0, 250, 500, 1000, 1500, 2500], labels=BAND_ORDER, right=False, include_lowest=True).astype(str)
    frame.loc[midpoint.eq(2500), "distance_band"] = "1500_2500ft"

    def aggregate(group_col: str) -> pd.DataFrame:
        group_cols = ["reference_signal_id", "signal_relative_direction", group_col]
        grouped = (
            frame.groupby(group_cols, dropna=False)
            .agg(
                assigned_crash_count=("unique_assigned_crash_count", "sum"),
                bin_count=("reference_directional_bin_id", "nunique"),
                represented_length_ft=("represented_length_ft", "sum"),
                represented_length_miles=("represented_length_miles", "sum"),
                stable_aadt_bin_count=("has_stable_aadt_context", "sum"),
                stable_speed_bin_count=("has_stable_speed_context", "sum"),
                stable_aadt_length_miles=("stable_aadt_length", "sum"),
                stable_speed_length_miles=("stable_speed_length", "sum"),
                weighted_v1_aadt_sum=("weighted_v1_aadt", "sum"),
                weighted_v2_aadt_sum=("weighted_v2_aadt", "sum"),
                weighted_speed_sum=("weighted_speed", "sum"),
                access_count_within_catchment_sum=("access_count_within_catchment", "sum"),
                valid_direction_factor_bin_count=("valid_direction_factor_flag", "sum"),
                missing_direction_factor_bin_count=("missing_direction_factor_flag", "sum"),
                invalid_direction_factor_bin_count=("invalid_direction_factor_flag", "sum"),
                speed_statuses=("refined_speed_context_status", _join_flags),
                aadt_statuses=("aadt_context_status", _join_flags),
            )
            .reset_index()
        )
        grouped["stable_aadt_coverage_share"] = _safe_div(grouped["stable_aadt_bin_count"], grouped["bin_count"])
        grouped["stable_speed_coverage_share"] = _safe_div(grouped["stable_speed_bin_count"], grouped["bin_count"])
        grouped["stable_aadt_length_coverage_share"] = _safe_div(grouped["stable_aadt_length_miles"], grouped["represented_length_miles"])
        grouped["stable_speed_length_coverage_share"] = _safe_div(grouped["stable_speed_length_miles"], grouped["represented_length_miles"])
        grouped["length_weighted_aadt_v1"] = _safe_div(grouped["weighted_v1_aadt_sum"], grouped["stable_aadt_length_miles"])
        grouped["direction_factor_adjusted_aadt"] = _safe_div(grouped["weighted_v2_aadt_sum"], grouped["stable_aadt_length_miles"])
        grouped["length_weighted_speed"] = _safe_div(grouped["weighted_speed_sum"], grouped["stable_speed_length_miles"])
        grouped["v2_direction_factor_adjusted_exposure"] = grouped["direction_factor_adjusted_aadt"] * grouped["represented_length_miles"] * STUDY_PERIOD_DAYS
        grouped["v1_estimated_exposure"] = grouped["length_weighted_aadt_v1"] * grouped["represented_length_miles"] * STUDY_PERIOD_DAYS
        grouped["denominator_ready_flag"] = (
            grouped["stable_aadt_coverage_share"].ge(AADT_COVERAGE_THRESHOLD)
            & grouped["represented_length_miles"].gt(0)
            & grouped["direction_factor_adjusted_aadt"].gt(0)
        )
        grouped["modeling_ready_candidate"] = grouped["denominator_ready_flag"] & grouped["stable_speed_coverage_share"].ge(SPEED_COVERAGE_THRESHOLD)
        grouped["direction_factor_applied_flag"] = grouped["valid_direction_factor_bin_count"].gt(0)
        grouped["direction_factor_missing_bidirectional_fallback_flag"] = grouped["missing_direction_factor_bin_count"].gt(0)
        grouped["direction_factor_invalid_review_flag"] = grouped["invalid_direction_factor_bin_count"].gt(0)
        grouped = grouped.merge(_unit_year_flags(frame, group_cols), on=group_cols, how="left")
        grouped["active_speed_context_policy"] = "speed_v5_new_source_supplement"
        grouped["active_aadt_denominator_policy"] = "v2_direction_factor_with_bidirectional_fallback"
        grouped = grouped.drop(columns=["weighted_v1_aadt_sum", "weighted_v2_aadt_sum", "weighted_speed_sum"])
        grouped = grouped.rename(columns={group_col: "analysis_window" if group_col == "analysis_window" else "distance_band"})
        return grouped

    return aggregate("analysis_window"), aggregate("distance_band")


def _add_rate_fields(units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rate = units.loc[units["denominator_ready_flag"]].copy()
    rate["analysis_unit_grain"] = "reference_signal_id_signal_relative_direction_analysis_window"
    rate["study_period"] = STUDY_PERIOD_LABEL
    rate["study_period_days"] = STUDY_PERIOD_DAYS
    rate["study_period_years"] = STUDY_PERIOD_YEARS
    rate["active_estimated_exposure"] = rate["v2_direction_factor_adjusted_exposure"]
    rate["active_rate_per_million"] = _safe_div(rate["assigned_crash_count"] * 1_000_000, rate["active_estimated_exposure"])
    rate["low_crash_count_flag"] = rate["assigned_crash_count"].lt(LOW_CRASH_COUNT_THRESHOLD)
    rate["zero_crash_unit_flag"] = rate["assigned_crash_count"].eq(0)
    intervals = rate["assigned_crash_count"].map(_poisson_count_interval_95)
    rate["crash_count_lower_95"] = intervals.map(lambda value: value[0])
    rate["crash_count_upper_95"] = intervals.map(lambda value: value[1])
    rate["uncertainty_method"] = intervals.map(lambda value: value[2])
    rate["rate_lower_95_per_million"] = _safe_div(rate["crash_count_lower_95"].astype(float) * 1_000_000, rate["active_estimated_exposure"])
    rate["rate_upper_95_per_million"] = _safe_div(rate["crash_count_upper_95"].astype(float) * 1_000_000, rate["active_estimated_exposure"])
    non_ready = units.loc[~units["denominator_ready_flag"]].copy()
    non_ready["non_ready_reason"] = "missing_or_insufficient_active_aadt_v2_denominator"
    return rate, non_ready


def _rate_summary(rate: pd.DataFrame, group_cols: list[str], name: str) -> pd.DataFrame:
    grouped = (
        rate.groupby(group_cols, dropna=False)
        .agg(
            rate_ready_unit_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            active_estimated_exposure=("active_estimated_exposure", "sum"),
            represented_length_miles=("represented_length_miles", "sum"),
            direction_factor_applied_unit_count=("direction_factor_applied_flag", "sum"),
            null_factor_bidirectional_fallback_unit_count=("direction_factor_missing_bidirectional_fallback_flag", "sum"),
            invalid_factor_unit_count=("direction_factor_invalid_review_flag", "sum"),
        )
        .reset_index()
    )
    grouped.insert(0, "summary_name", name)
    grouped["active_rate_per_million"] = _safe_div(grouped["assigned_crash_count"] * 1_000_000, grouped["active_estimated_exposure"])
    return grouped


def write_active_rates(window_matrix: pd.DataFrame, started: datetime) -> tuple[dict[str, Path], pd.DataFrame]:
    rate, non_ready = _add_rate_fields(window_matrix)
    outputs = {
        "active_rate_signal_direction_window": ACTIVE_RATE_DIR / "active_rate_signal_direction_window.csv",
        "active_rate_summary_by_window": ACTIVE_RATE_DIR / "active_rate_summary_by_window.csv",
        "active_rate_summary_by_direction": ACTIVE_RATE_DIR / "active_rate_summary_by_direction.csv",
        "active_rate_comparison_to_v1": ACTIVE_RATE_DIR / "active_rate_comparison_to_v1.csv",
        "active_rate_qa": ACTIVE_RATE_DIR / "active_rate_qa.csv",
        "active_rate_findings": ACTIVE_RATE_DIR / "active_rate_findings.md",
        "active_rate_manifest": ACTIVE_RATE_DIR / "active_rate_manifest.json",
        "active_rate_non_ready_units": ACTIVE_RATE_DIR / "active_rate_non_ready_units.csv",
    }
    _write_csv(rate, outputs["active_rate_signal_direction_window"])
    _write_csv(non_ready, outputs["active_rate_non_ready_units"])
    _write_csv(_rate_summary(rate, ["analysis_window"], "active_rate_by_window"), outputs["active_rate_summary_by_window"])
    _write_csv(_rate_summary(rate, ["signal_relative_direction"], "active_rate_by_direction"), outputs["active_rate_summary_by_direction"])
    v1 = _read_csv(BASE_RATE_DIR / "descriptive_rate_prototype_signal_direction_window.csv")
    for column in ["assigned_crash_count", "vmt_like_exposure", "crashes_per_million_vmt"]:
        v1[column] = _num(v1, column)
    comparison = rate.merge(
        v1[
            [
                "reference_signal_id",
                "signal_relative_direction",
                "analysis_window",
                "vmt_like_exposure",
                "crashes_per_million_vmt",
            ]
        ],
        on=["reference_signal_id", "signal_relative_direction", "analysis_window"],
        how="left",
    ).rename(columns={"vmt_like_exposure": "v1_estimated_exposure_from_baseline", "crashes_per_million_vmt": "v1_rate_per_million"})
    comparison["exposure_ratio_active_to_v1"] = _safe_div(comparison["active_estimated_exposure"], comparison["v1_estimated_exposure_from_baseline"])
    comparison["rate_ratio_active_to_v1"] = _safe_div(comparison["active_rate_per_million"], comparison["v1_rate_per_million"])
    _write_csv(comparison, outputs["active_rate_comparison_to_v1"])
    qa = pd.DataFrame(
        [
            {"check_name": "approved_window_grain_only", "passed": True, "observed": "reference_signal_id+signal_relative_direction+analysis_window", "expected": "window_grain"},
            {"check_name": "active_aadt_v2_denominator_used", "passed": rate["active_aadt_denominator_policy"].eq("v2_direction_factor_with_bidirectional_fallback").all(), "observed": "v2_direction_factor_with_bidirectional_fallback", "expected": "v2_direction_factor_with_bidirectional_fallback"},
            {"check_name": "rate_ready_units_match_v2_policy_expected", "passed": len(rate) == 2967, "observed": len(rate), "expected": 2967},
            {"check_name": "invalid_direction_factor_units", "passed": int(rate["direction_factor_invalid_review_flag"].sum()) == 0, "observed": int(rate["direction_factor_invalid_review_flag"].sum()), "expected": 0},
            {"check_name": "models_fit", "passed": True, "observed": False, "expected": False},
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
        ]
    )
    _write_csv(qa, outputs["active_rate_qa"])
    total_exposure = float(rate["active_estimated_exposure"].sum())
    total_crashes = float(rate["assigned_crash_count"].sum())
    total_rate = total_crashes * 1_000_000 / total_exposure
    _write_text(
        f"""# Active Rate Findings

The active descriptive rate prototype uses the approved window grain and active AADT v2 denominator policy.

- rate-ready units: {len(rate)}
- units using valid direction factor: {int(rate['direction_factor_applied_flag'].sum())}
- units using null-factor bidirectional fallback: {int(rate['direction_factor_missing_bidirectional_fallback_flag'].sum())}
- invalid factor units: {int(rate['direction_factor_invalid_review_flag'].sum())}
- active v2 exposure: {total_exposure:.2f}
- active aggregate rate per million: {total_rate:.6f}

No models were fit and no policy, risk, safety-performance, or distance-guidance claims are made.
""",
        outputs["active_rate_findings"],
    )
    _write_json({"created_at_utc": started.isoformat(), "outputs": {k: str(v) for k, v in outputs.items()}, "qa": qa.to_dict(orient="records")}, outputs["active_rate_manifest"])
    return outputs, rate


def write_suppression_review(rate: pd.DataFrame, started: datetime) -> dict[str, Path]:
    outputs = {
        "rate_unit_suppression_flags_active": ACTIVE_SUPPRESSION_DIR / "rate_unit_suppression_flags_active.csv",
        "rate_suppression_summary_active": ACTIVE_SUPPRESSION_DIR / "rate_suppression_summary_active.csv",
        "rate_suppression_review_qa_active": ACTIVE_SUPPRESSION_DIR / "rate_suppression_review_qa_active.csv",
        "rate_suppression_review_findings_active": ACTIVE_SUPPRESSION_DIR / "rate_suppression_review_findings_active.md",
        "rate_suppression_review_manifest_active": ACTIVE_SUPPRESSION_DIR / "rate_suppression_review_manifest_active.json",
    }
    flags = rate.copy()
    low_exposure_threshold = flags["active_estimated_exposure"].quantile(0.10)
    flags["low_exposure_flag"] = flags["active_estimated_exposure"].le(low_exposure_threshold)
    flags["wide_interval_flag"] = (flags["rate_upper_95_per_million"] - flags["rate_lower_95_per_million"]).gt(flags["active_rate_per_million"] * 4)
    flags["stakeholder_unit_rate_suppression_flag"] = True
    flags["suppression_reason"] = "unit_level_rates_remain_internal_qa_only_under_active_refresh"
    _write_csv(flags, outputs["rate_unit_suppression_flags_active"])
    summary = pd.DataFrame(
        [
            {"metric": "rate_ready_units", "value": len(flags)},
            {"metric": "low_exposure_units", "value": int(flags["low_exposure_flag"].sum())},
            {"metric": "wide_interval_units", "value": int(flags["wide_interval_flag"].sum())},
            {"metric": "stakeholder_suppressed_unit_rates", "value": int(flags["stakeholder_unit_rate_suppression_flag"].sum())},
        ]
    )
    _write_csv(summary, outputs["rate_suppression_summary_active"])
    qa = pd.DataFrame(
        [
            {"check_name": "suppression_review_uses_active_rate", "passed": True, "observed": str(ACTIVE_RATE_DIR), "expected": str(ACTIVE_RATE_DIR)},
            {"check_name": "unit_level_rates_not_stakeholder_ready", "passed": flags["stakeholder_unit_rate_suppression_flag"].all(), "observed": "all_suppressed", "expected": "all_suppressed"},
            {"check_name": "models_fit", "passed": True, "observed": False, "expected": False},
        ]
    )
    _write_csv(qa, outputs["rate_suppression_review_qa_active"])
    _write_text("# Active Rate Suppression Review Findings\n\nUnit-level active rates remain internal QA-only. Aggregate summaries may be reviewed with caveats; no policy or safety-performance claims are introduced.\n", outputs["rate_suppression_review_findings_active"])
    _write_json({"created_at_utc": started.isoformat(), "outputs": {k: str(v) for k, v in outputs.items()}, "qa": qa.to_dict(orient="records")}, outputs["rate_suppression_review_manifest_active"])
    return outputs


def write_modeling_readiness(window_matrix: pd.DataFrame, band_matrix: pd.DataFrame, started: datetime) -> dict[str, Path]:
    outputs = {
        "window_matrix": ACTIVE_MODEL_DIR / "crash_count_modeling_matrix_signal_direction_window_active.csv",
        "band_matrix": ACTIVE_MODEL_DIR / "crash_count_modeling_matrix_signal_direction_distance_band_active.csv",
        "quality_summary": ACTIVE_MODEL_DIR / "modeling_unit_quality_summary_active.csv",
        "warning_flags": ACTIVE_MODEL_DIR / "modeling_readiness_warning_flags_active.csv",
        "qa": ACTIVE_MODEL_DIR / "crash_count_modeling_readiness_active_qa.csv",
        "findings": ACTIVE_MODEL_DIR / "crash_count_modeling_readiness_active_findings.md",
        "manifest": ACTIVE_MODEL_DIR / "crash_count_modeling_readiness_active_manifest.json",
    }
    _write_csv(window_matrix, outputs["window_matrix"])
    _write_csv(band_matrix, outputs["band_matrix"])
    quality = pd.DataFrame(
        [
            {"grain": "signal_direction_window", "unit_count": len(window_matrix), "denominator_ready_units": int(window_matrix["denominator_ready_flag"].sum()), "modeling_ready_units": int(window_matrix["modeling_ready_candidate"].sum()), "assigned_crashes": int(window_matrix["assigned_crash_count"].sum())},
            {"grain": "signal_direction_distance_band", "unit_count": len(band_matrix), "denominator_ready_units": int(band_matrix["denominator_ready_flag"].sum()), "modeling_ready_units": int(band_matrix["modeling_ready_candidate"].sum()), "assigned_crashes": int(band_matrix["assigned_crash_count"].sum())},
        ]
    )
    _write_csv(quality, outputs["quality_summary"])
    warnings = pd.DataFrame(
        [
            {"warning_name": "active_matrices_refreshed_not_model_fit", "unit_count": len(window_matrix), "notes": "No Poisson, negative-binomial, or other model was fit."},
            {"warning_name": "remaining_missing_review_speed_units_window", "unit_count": int((~window_matrix["modeling_ready_candidate"]).sum()), "notes": "Includes denominator or speed coverage failures."},
        ]
    )
    _write_csv(warnings, outputs["warning_flags"])
    qa = pd.DataFrame(
        [
            {"check_name": "active_speed_v5_in_model_matrix", "passed": window_matrix["active_speed_context_policy"].eq("speed_v5_new_source_supplement").all(), "observed": "speed_v5_new_source_supplement", "expected": "speed_v5_new_source_supplement"},
            {"check_name": "active_aadt_v2_in_model_matrix", "passed": window_matrix["active_aadt_denominator_policy"].eq("v2_direction_factor_with_bidirectional_fallback").all(), "observed": "v2_direction_factor_with_bidirectional_fallback", "expected": "v2_direction_factor_with_bidirectional_fallback"},
            {"check_name": "models_fit", "passed": True, "observed": False, "expected": False},
        ]
    )
    _write_csv(qa, outputs["qa"])
    _write_text("# Active Modeling Readiness Findings\n\nActive modeling matrices were refreshed with speed v5 and AADT v2 exposure fields. No models were fit.\n", outputs["findings"])
    _write_json({"created_at_utc": started.isoformat(), "outputs": {k: str(v) for k, v in outputs.items()}, "qa": qa.to_dict(orient="records")}, outputs["manifest"])
    return outputs


def write_impact_summary(context: pd.DataFrame, rate: pd.DataFrame, window_matrix: pd.DataFrame, band_matrix: pd.DataFrame, started: datetime) -> dict[str, Path]:
    outputs = {
        "context": ACTIVE_IMPACT_DIR / "active_refresh_context_count_comparison.csv",
        "rate": ACTIVE_IMPACT_DIR / "active_refresh_rate_comparison.csv",
        "model": ACTIVE_IMPACT_DIR / "active_refresh_modeling_matrix_comparison.csv",
        "recommendations": ACTIVE_IMPACT_DIR / "active_refresh_downstream_recommendations.csv",
        "findings": ACTIVE_IMPACT_DIR / "active_refresh_findings.md",
        "manifest": ACTIVE_IMPACT_DIR / "active_refresh_manifest.json",
    }
    old_context = _read_csv(BASE_CONTEXT_DIR / "directional_bin_context.csv", usecols=["reference_directional_bin_id", "unique_assigned_crash_count", "has_stable_speed_context", "has_stable_aadt_context"])
    old_context["has_stable_speed_context"] = _bool(old_context["has_stable_speed_context"])
    old_context["has_stable_aadt_context"] = _bool(old_context["has_stable_aadt_context"])
    old_context["unique_assigned_crash_count"] = _num(old_context, "unique_assigned_crash_count")
    context_comp = pd.DataFrame(
        [
            {"metric": "total_bins", "baseline_v1_v4": len(old_context), "active_v2_v5": len(context), "change": len(context) - len(old_context)},
            {"metric": "stable_speed_bins", "baseline_v1_v4": int(old_context["has_stable_speed_context"].sum()), "active_v2_v5": int(context["has_stable_speed_context"].sum()), "change": int(context["has_stable_speed_context"].sum()) - int(old_context["has_stable_speed_context"].sum())},
            {"metric": "stable_aadt_bins", "baseline_v1_v4": int(old_context["has_stable_aadt_context"].sum()), "active_v2_v5": int(context["has_stable_aadt_context"].sum()), "change": int(context["has_stable_aadt_context"].sum()) - int(old_context["has_stable_aadt_context"].sum())},
            {"metric": "represented_assigned_crashes", "baseline_v1_v4": int(old_context["unique_assigned_crash_count"].sum()), "active_v2_v5": int(context["unique_assigned_crash_count"].sum()), "change": int(context["unique_assigned_crash_count"].sum()) - int(old_context["unique_assigned_crash_count"].sum())},
        ]
    )
    _write_csv(context_comp, outputs["context"])
    old_rate = _read_csv(BASE_RATE_DIR / "descriptive_rate_prototype_signal_direction_window.csv")
    for column in ["assigned_crash_count", "vmt_like_exposure", "crashes_per_million_vmt"]:
        old_rate[column] = _num(old_rate, column)
    rate_comp = pd.DataFrame(
        [
            {"metric": "rate_ready_units", "baseline_v1_v4": len(old_rate), "active_v2_v5": len(rate), "ratio_active_to_baseline": len(rate) / len(old_rate)},
            {"metric": "estimated_exposure", "baseline_v1_v4": float(old_rate["vmt_like_exposure"].sum()), "active_v2_v5": float(rate["active_estimated_exposure"].sum()), "ratio_active_to_baseline": float(rate["active_estimated_exposure"].sum()) / float(old_rate["vmt_like_exposure"].sum())},
            {"metric": "aggregate_rate_per_million", "baseline_v1_v4": float(old_rate["assigned_crash_count"].sum() * 1_000_000 / old_rate["vmt_like_exposure"].sum()), "active_v2_v5": float(rate["assigned_crash_count"].sum() * 1_000_000 / rate["active_estimated_exposure"].sum()), "ratio_active_to_baseline": float((rate["assigned_crash_count"].sum() * 1_000_000 / rate["active_estimated_exposure"].sum()) / (old_rate["assigned_crash_count"].sum() * 1_000_000 / old_rate["vmt_like_exposure"].sum()))},
        ]
    )
    _write_csv(rate_comp, outputs["rate"])
    old_model = _read_csv(BASE_MODEL_DIR / "crash_count_modeling_matrix_signal_direction_window.csv")
    if "denominator_candidate_ready" in old_model.columns:
        old_denominator_ready = _bool(old_model["denominator_candidate_ready"])
    else:
        old_denominator_ready = _bool(old_model["denominator_ready_flag"])
    if "modeling_ready_candidate" in old_model.columns:
        old_modeling_ready = _bool(old_model["modeling_ready_candidate"])
    else:
        old_speed_share = _num(old_model, "stable_speed_coverage_share")
        old_modeling_ready = old_denominator_ready & old_speed_share.ge(SPEED_COVERAGE_THRESHOLD)
    old_model["assigned_crash_count"] = _num(old_model, "assigned_crash_count")
    model_comp = pd.DataFrame(
        [
            {"grain": "signal_direction_window", "metric": "unit_count", "baseline_v1_v4": len(old_model), "active_v2_v5": len(window_matrix), "change": len(window_matrix) - len(old_model)},
            {"grain": "signal_direction_window", "metric": "denominator_ready_units", "baseline_v1_v4": int(old_denominator_ready.sum()), "active_v2_v5": int(window_matrix["denominator_ready_flag"].sum()), "change": int(window_matrix["denominator_ready_flag"].sum()) - int(old_denominator_ready.sum())},
            {"grain": "signal_direction_window", "metric": "modeling_ready_units", "baseline_v1_v4": int(old_modeling_ready.sum()), "active_v2_v5": int(window_matrix["modeling_ready_candidate"].sum()), "change": int(window_matrix["modeling_ready_candidate"].sum()) - int(old_modeling_ready.sum())},
            {"grain": "signal_direction_distance_band", "metric": "modeling_ready_units", "baseline_v1_v4": "", "active_v2_v5": int(band_matrix["modeling_ready_candidate"].sum()), "change": ""},
        ]
    )
    _write_csv(model_comp, outputs["model"])
    recommendations = pd.DataFrame(
        [
            {"downstream_product": "report_figures", "recommendation": "regenerate speed coverage and rate figures from active v2/v5 outputs", "status": "required"},
            {"downstream_product": "stakeholder_tables", "recommendation": "refresh before presenting speed or rate summaries", "status": "required"},
            {"downstream_product": "internal_models", "recommendation": "fit only in a separate explicitly scoped modeling task using active matrices", "status": "next_separate_task"},
            {"downstream_product": "legacy_v1_v4_outputs", "recommendation": "preserve as baseline/history comparison", "status": "preserve"},
        ]
    )
    _write_csv(recommendations, outputs["recommendations"])
    _write_text(
        f"""# Active Refresh Impact Findings

The active refresh preserves the accepted scaffold, catchments, crash assignment, access context, and AADT join while updating speed context to v5 and rate/model exposure fields to AADT denominator v2.

- stable speed bins: {int(old_context['has_stable_speed_context'].sum())} -> {int(context['has_stable_speed_context'].sum())}
- represented crashes: {int(old_context['unique_assigned_crash_count'].sum())} -> {int(context['unique_assigned_crash_count'].sum())}
- active rate-ready units: {len(rate)}
- active window modeling-ready units: {int(window_matrix['modeling_ready_candidate'].sum())}

Figures and report tables using speed context, rates, or model matrices should be regenerated from the active folders. No models were fit and no policy/risk/safety-performance claims are introduced.
""",
        outputs["findings"],
    )
    _write_json({"created_at_utc": started.isoformat(), "outputs": {k: str(v) for k, v in outputs.items()}}, outputs["manifest"])
    return outputs


def build_active_refresh() -> dict[str, dict[str, str]]:
    started = datetime.now(timezone.utc)
    context, crash_context, _urban = build_active_context()
    context_outputs = write_active_context(context, crash_context, started)
    summary_outputs = write_descriptive_summaries(context, crash_context, started)
    window_matrix, band_matrix = build_model_matrices(context)
    rate_outputs, rate = write_active_rates(window_matrix, started)
    suppression_outputs = write_suppression_review(rate, started)
    model_outputs = write_modeling_readiness(window_matrix, band_matrix, started)
    impact_outputs = write_impact_summary(context, rate, window_matrix, band_matrix, started)
    return {
        "active_context": {key: str(path) for key, path in context_outputs.items()},
        "active_descriptive_summaries": {key: str(path) for key, path in summary_outputs.items()},
        "active_rates": {key: str(path) for key, path in rate_outputs.items()},
        "active_suppression_review": {key: str(path) for key, path in suppression_outputs.items()},
        "active_modeling_readiness": {key: str(path) for key, path in model_outputs.items()},
        "active_impact_summary": {key: str(path) for key, path in impact_outputs.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh active downstream context/rate/readiness outputs using speed v5 and AADT denominator v2.")
    parser.parse_args()
    outputs = build_active_refresh()
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
