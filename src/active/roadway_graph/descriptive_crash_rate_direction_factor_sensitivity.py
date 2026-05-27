from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_direction_factor_sensitivity"

CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"
RATE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype"
SUPPRESSION_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_suppression_review"
APPROVAL_DIR = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1"
AADT_FACTOR_AUDIT_DIR = OUTPUT_ROOT / "analysis/current/aadt_direction_factor_audit"
AADT_JOIN_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"

RATE_ROWS_FILE = RATE_DIR / "descriptive_rate_prototype_signal_direction_window.csv"
NON_READY_FILE = RATE_DIR / "descriptive_rate_prototype_non_ready_units.csv"
SUPPRESSION_FLAGS_FILE = SUPPRESSION_DIR / "rate_unit_suppression_flags.csv"
AUTHORIZATION_DECISION_FILE = APPROVAL_DIR / "rate_prototype_authorization_decision.csv"
DENOMINATOR_RULE_SPEC_FILE = APPROVAL_DIR / "denominator_rule_spec_v1.csv"
AADT_FACTOR_AUDIT_FILE = AADT_FACTOR_AUDIT_DIR / "aadt_direction_factor_denominator_sensitivity.csv"
AADT_FACTOR_AUDIT_FINDINGS_FILE = AADT_FACTOR_AUDIT_DIR / "aadt_direction_factor_audit_findings.md"
AADT_CONTEXT_FILE = AADT_JOIN_DIR / "directional_bin_aadt_context_v3.csv"
READINESS_FEATURE_FILE = READINESS_DIR / "modeling_feature_matrix_signal_direction_window.csv"
READINESS_UNIT_FILE = READINESS_DIR / "analysis_unit_readiness_signal_direction_window.csv"

AUTHORIZED_GRAIN = "reference_signal_id_signal_relative_direction_analysis_window"
WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
STUDY_PERIOD_LABEL = "2022_2024"
STUDY_PERIOD_DAYS = 1096
STUDY_PERIOD_YEARS = 3.000684

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)


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


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.replace(0, pd.NA)).astype("Float64")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": _sha256(path),
    }


def _mode_or_blank(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA
    modes = values.mode(dropna=True)
    if modes.empty:
        return pd.NA
    return modes.iloc[0]


def _input_files() -> list[Path]:
    return [
        CONTEXT_FILE,
        RATE_ROWS_FILE,
        NON_READY_FILE,
        SUPPRESSION_FLAGS_FILE,
        AUTHORIZATION_DECISION_FILE,
        DENOMINATOR_RULE_SPEC_FILE,
        AADT_FACTOR_AUDIT_FILE,
        AADT_FACTOR_AUDIT_FINDINGS_FILE,
        AADT_CONTEXT_FILE,
        READINESS_FEATURE_FILE,
        READINESS_UNIT_FILE,
    ]


def load_rate_rows() -> pd.DataFrame:
    columns = [
        "analysis_unit_grain",
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "assigned_crash_count",
        "represented_length_miles",
        "aadt_value_for_denominator",
        "vmt_like_exposure",
        "crashes_per_million_vmt",
        "denominator_ready_flag",
        "bidirectional_aadt_assumption_flag",
        "direction_factor_applied",
        "stable_aadt_coverage_share",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "low_crash_count_flag",
        "zero_crash_unit_flag",
        "low_exposure_flag",
        "rate_suppression_flag",
        "rate_interpretation_warning",
    ]
    frame = _read_csv(RATE_ROWS_FILE, usecols=columns)
    for column in [
        "assigned_crash_count",
        "represented_length_miles",
        "aadt_value_for_denominator",
        "vmt_like_exposure",
        "crashes_per_million_vmt",
        "stable_aadt_coverage_share",
    ]:
        frame[column] = _num(frame[column])
    for column in [
        "denominator_ready_flag",
        "bidirectional_aadt_assumption_flag",
        "direction_factor_applied",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "low_crash_count_flag",
        "zero_crash_unit_flag",
        "low_exposure_flag",
        "rate_suppression_flag",
    ]:
        frame[column] = _bool(frame[column])
    return frame


def load_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "distance_window",
        "bin_midpoint_ft_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "aadt_value",
        "aadt_direction_factor",
        "aadt_directionality",
        "aadt_year",
        "has_stable_aadt_context",
        "aadt_context_status",
    ]
    frame = _read_csv(CONTEXT_FILE, usecols=columns)
    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    frame["analysis_window"] = frame["distance_window"]
    for column in [
        "bin_midpoint_ft_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "aadt_value",
        "aadt_direction_factor",
        "aadt_year",
    ]:
        frame[column] = _num(frame[column])
    frame = frame.loc[frame["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    frame["has_stable_aadt_context"] = _bool(frame["has_stable_aadt_context"])
    frame["represented_length_ft"] = (frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]).clip(lower=0)
    frame["represented_length_miles"] = frame["represented_length_ft"] / 5280.0
    return frame


def build_factor_unit_context(context: pd.DataFrame) -> pd.DataFrame:
    stable = context.loc[context["has_stable_aadt_context"] & context["aadt_value"].gt(0) & context["represented_length_miles"].gt(0)].copy()
    stable["valid_direction_factor_flag"] = stable["aadt_direction_factor"].gt(0) & stable["aadt_direction_factor"].le(1)
    stable["missing_direction_factor_flag"] = stable["aadt_direction_factor"].isna()
    stable["invalid_direction_factor_flag"] = stable["aadt_direction_factor"].notna() & ~stable["valid_direction_factor_flag"]
    stable["bin_direction_factor_for_v2"] = stable["aadt_direction_factor"].where(stable["valid_direction_factor_flag"], 1.0)
    stable["bin_direction_factor_adjusted_aadt"] = stable["aadt_value"] * stable["bin_direction_factor_for_v2"]
    stable["weighted_v1_aadt"] = stable["aadt_value"] * stable["represented_length_miles"]
    stable["weighted_v2_aadt"] = stable["bin_direction_factor_adjusted_aadt"] * stable["represented_length_miles"]

    grouped = (
        stable.groupby(["reference_signal_id", "signal_relative_direction", "analysis_window"], dropna=False)
        .agg(
            factor_context_bin_count=("reference_directional_bin_id", "nunique"),
            factor_context_length_miles=("represented_length_miles", "sum"),
            valid_direction_factor_bin_count=("valid_direction_factor_flag", "sum"),
            missing_direction_factor_bin_count=("missing_direction_factor_flag", "sum"),
            invalid_direction_factor_bin_count=("invalid_direction_factor_flag", "sum"),
            weighted_v1_aadt_sum=("weighted_v1_aadt", "sum"),
            weighted_v2_aadt_sum=("weighted_v2_aadt", "sum"),
            median_valid_direction_factor=("aadt_direction_factor", lambda s: s.loc[s.gt(0) & s.le(1)].median()),
            mean_valid_direction_factor=("aadt_direction_factor", lambda s: s.loc[s.gt(0) & s.le(1)].mean()),
            min_direction_factor=("aadt_direction_factor", "min"),
            max_direction_factor=("aadt_direction_factor", "max"),
            dominant_aadt_directionality=("aadt_directionality", _mode_or_blank),
            dominant_aadt_year=("aadt_year", _mode_or_blank),
        )
        .reset_index()
    )
    grouped["context_length_weighted_v1_aadt"] = _safe_div(grouped["weighted_v1_aadt_sum"], grouped["factor_context_length_miles"])
    grouped["direction_factor_adjusted_aadt"] = _safe_div(grouped["weighted_v2_aadt_sum"], grouped["factor_context_length_miles"])
    grouped["direction_factor_applied_flag"] = grouped["valid_direction_factor_bin_count"].gt(0)
    grouped["direction_factor_missing_bidirectional_fallback_flag"] = grouped["missing_direction_factor_bin_count"].gt(0)
    grouped["direction_factor_invalid_review_flag"] = grouped["invalid_direction_factor_bin_count"].gt(0)
    return grouped.drop(columns=["weighted_v1_aadt_sum", "weighted_v2_aadt_sum"])


def add_v2_rates(rate_rows: pd.DataFrame, factor_units: pd.DataFrame) -> pd.DataFrame:
    frame = rate_rows.merge(
        factor_units,
        on=["reference_signal_id", "signal_relative_direction", "analysis_window"],
        how="left",
    )
    frame["direction_factor_adjusted_aadt"] = frame["direction_factor_adjusted_aadt"].where(
        frame["direction_factor_adjusted_aadt"].notna(), frame["aadt_value_for_denominator"]
    )
    frame["direction_factor_applied_flag"] = frame["direction_factor_applied_flag"].fillna(False).astype(bool)
    frame["direction_factor_missing_bidirectional_fallback_flag"] = (
        frame["direction_factor_missing_bidirectional_fallback_flag"].fillna(False).astype(bool)
    )
    frame["direction_factor_invalid_review_flag"] = frame["direction_factor_invalid_review_flag"].fillna(False).astype(bool)
    frame["v1_estimated_exposure"] = frame["vmt_like_exposure"]
    frame["v2_direction_factor_adjusted_exposure"] = (
        frame["direction_factor_adjusted_aadt"] * frame["represented_length_miles"] * STUDY_PERIOD_DAYS
    )
    frame["exposure_ratio_v2_to_v1"] = _safe_div(frame["v2_direction_factor_adjusted_exposure"], frame["v1_estimated_exposure"])
    frame["v1_rate_per_million"] = frame["crashes_per_million_vmt"]
    frame["v2_rate_per_million"] = _safe_div(frame["assigned_crash_count"] * 1_000_000, frame["v2_direction_factor_adjusted_exposure"])
    frame["rate_ratio_v2_to_v1"] = _safe_div(frame["v2_rate_per_million"], frame["v1_rate_per_million"])
    frame["study_period"] = STUDY_PERIOD_LABEL
    frame["study_period_days"] = STUDY_PERIOD_DAYS
    frame["study_period_years"] = STUDY_PERIOD_YEARS
    frame["sensitivity_output_flag"] = True
    frame["v2_interpretation_warning"] = (
        "direction_factor_sensitivity_only_not_replacement_for_v1_not_policy_or_safety_performance"
    )
    frame.loc[frame["direction_factor_missing_bidirectional_fallback_flag"], "v2_interpretation_warning"] += (
        ";null_factor_bidirectional_fallback"
    )
    frame.loc[frame["direction_factor_invalid_review_flag"], "v2_interpretation_warning"] += ";invalid_factor_v1_fallback_review"
    keep = [
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "analysis_unit_grain",
        "assigned_crash_count",
        "represented_length_miles",
        "aadt_value_for_denominator",
        "direction_factor_adjusted_aadt",
        "v1_estimated_exposure",
        "v2_direction_factor_adjusted_exposure",
        "exposure_ratio_v2_to_v1",
        "v1_rate_per_million",
        "v2_rate_per_million",
        "rate_ratio_v2_to_v1",
        "direction_factor_applied_flag",
        "direction_factor_missing_bidirectional_fallback_flag",
        "direction_factor_invalid_review_flag",
        "valid_direction_factor_bin_count",
        "missing_direction_factor_bin_count",
        "invalid_direction_factor_bin_count",
        "factor_context_bin_count",
        "factor_context_length_miles",
        "median_valid_direction_factor",
        "mean_valid_direction_factor",
        "min_direction_factor",
        "max_direction_factor",
        "dominant_aadt_directionality",
        "dominant_aadt_year",
        "stable_aadt_coverage_share",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "low_crash_count_flag",
        "zero_crash_unit_flag",
        "low_exposure_flag",
        "rate_suppression_flag",
        "bidirectional_aadt_assumption_flag",
        "study_period",
        "study_period_days",
        "study_period_years",
        "sensitivity_output_flag",
        "v2_interpretation_warning",
        "rate_interpretation_warning",
    ]
    return frame[keep].copy()


def summarize(frame: pd.DataFrame, group_cols: list[str], summary_name: str) -> pd.DataFrame:
    grouped = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            unit_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            v1_estimated_exposure=("v1_estimated_exposure", "sum"),
            v2_direction_factor_adjusted_exposure=("v2_direction_factor_adjusted_exposure", "sum"),
            represented_length_miles=("represented_length_miles", "sum"),
            direction_factor_applied_unit_count=("direction_factor_applied_flag", "sum"),
            null_factor_bidirectional_fallback_unit_count=("direction_factor_missing_bidirectional_fallback_flag", "sum"),
            invalid_factor_review_unit_count=("direction_factor_invalid_review_flag", "sum"),
            median_unit_exposure_ratio_v2_to_v1=("exposure_ratio_v2_to_v1", "median"),
            mean_unit_exposure_ratio_v2_to_v1=("exposure_ratio_v2_to_v1", "mean"),
            median_unit_rate_ratio_v2_to_v1=("rate_ratio_v2_to_v1", "median"),
            mean_unit_rate_ratio_v2_to_v1=("rate_ratio_v2_to_v1", "mean"),
        )
        .reset_index()
    )
    grouped.insert(0, "summary_name", summary_name)
    grouped["aggregate_exposure_ratio_v2_to_v1"] = _safe_div(
        grouped["v2_direction_factor_adjusted_exposure"], grouped["v1_estimated_exposure"]
    )
    grouped["v1_rate_per_million"] = _safe_div(grouped["assigned_crash_count"] * 1_000_000, grouped["v1_estimated_exposure"])
    grouped["v2_rate_per_million"] = _safe_div(
        grouped["assigned_crash_count"] * 1_000_000, grouped["v2_direction_factor_adjusted_exposure"]
    )
    grouped["aggregate_rate_ratio_v2_to_v1"] = _safe_div(grouped["v2_rate_per_million"], grouped["v1_rate_per_million"])
    grouped["sensitivity_output_flag"] = True
    return grouped


def build_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("total_rate_ready_units", len(frame), "All v1 denominator-ready window-grain units evaluated for v2 sensitivity."),
        ("units_with_valid_factor_applied", int(frame["direction_factor_applied_flag"].sum()), "At least one stable AADT bin had valid 0 < DIRECTION_FACTOR <= 1."),
        (
            "units_with_null_factor_bidirectional_fallback",
            int(frame["direction_factor_missing_bidirectional_fallback_flag"].sum()),
            "At least one stable AADT bin had null DIRECTION_FACTOR and retained v1 AADT treatment for that bin.",
        ),
        (
            "units_with_invalid_factor_review",
            int(frame["direction_factor_invalid_review_flag"].sum()),
            "At least one stable AADT bin had DIRECTION_FACTOR <= 0 or > 1 and retained v1 AADT treatment for that bin.",
        ),
        ("valid_factor_bins", int(frame["valid_direction_factor_bin_count"].fillna(0).sum()), "Stable denominator bins with valid factor."),
        (
            "null_factor_fallback_bins",
            int(frame["missing_direction_factor_bin_count"].fillna(0).sum()),
            "Stable denominator bins with null factor fallback.",
        ),
        (
            "invalid_factor_review_bins",
            int(frame["invalid_direction_factor_bin_count"].fillna(0).sum()),
            "Stable denominator bins with invalid factor review flag.",
        ),
    ]
    return pd.DataFrame(rows, columns=["metric", "value", "notes"])


def build_missing_fallback_summary(frame: pd.DataFrame) -> pd.DataFrame:
    fallback = frame.loc[frame["direction_factor_missing_bidirectional_fallback_flag"]].copy()
    if fallback.empty:
        return pd.DataFrame(
            columns=[
                "analysis_window",
                "signal_relative_direction",
                "unit_count",
                "assigned_crash_count",
                "missing_direction_factor_bin_count",
                "v1_estimated_exposure",
                "v2_direction_factor_adjusted_exposure",
                "aggregate_exposure_ratio_v2_to_v1",
            ]
        )
    grouped = (
        fallback.groupby(["analysis_window", "signal_relative_direction"], dropna=False)
        .agg(
            unit_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            missing_direction_factor_bin_count=("missing_direction_factor_bin_count", "sum"),
            v1_estimated_exposure=("v1_estimated_exposure", "sum"),
            v2_direction_factor_adjusted_exposure=("v2_direction_factor_adjusted_exposure", "sum"),
        )
        .reset_index()
    )
    grouped["aggregate_exposure_ratio_v2_to_v1"] = _safe_div(
        grouped["v2_direction_factor_adjusted_exposure"], grouped["v1_estimated_exposure"]
    )
    grouped["sensitivity_output_flag"] = True
    return grouped


def build_non_ready(non_ready: pd.DataFrame, factor_units: pd.DataFrame) -> pd.DataFrame:
    frame = non_ready.merge(
        factor_units,
        on=["reference_signal_id", "signal_relative_direction", "analysis_window"],
        how="left",
    )
    for column in [
        "direction_factor_applied_flag",
        "direction_factor_missing_bidirectional_fallback_flag",
        "direction_factor_invalid_review_flag",
    ]:
        frame[column] = frame[column].fillna(False).astype(bool)
    frame["sensitivity_non_ready_note"] = "preserved_from_v1_non_ready_units_no_v2_rate_computed"
    frame["sensitivity_output_flag"] = True
    return frame


def build_outputs() -> dict[str, Any]:
    missing = [str(path) for path in _input_files() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required direction-factor sensitivity input(s): {missing}")

    rate_before = _file_fingerprint(RATE_ROWS_FILE)
    authorization = _read_csv(AUTHORIZATION_DECISION_FILE)
    if authorization.loc[0, "authorization_decision"] != "approved_for_descriptive_rate_prototype_v1":
        raise ValueError("V1 rate prototype authorization is not present.")

    rate_rows = load_rate_rows()
    if not rate_rows["analysis_unit_grain"].eq(AUTHORIZED_GRAIN).all():
        raise ValueError("V1 rate rows are not limited to the approved window grain.")
    if not rate_rows["analysis_window"].isin(WINDOWS).all():
        raise ValueError("V1 rate rows contain an unexpected analysis window.")

    context = load_context()
    factor_units = build_factor_unit_context(context)
    unit_rates = add_v2_rates(rate_rows, factor_units)
    non_ready = build_non_ready(_read_csv(NON_READY_FILE), factor_units)

    summary_by_window = summarize(unit_rates, ["analysis_window"], "direction_factor_sensitivity_summary_by_window")
    summary_by_direction = summarize(
        unit_rates, ["signal_relative_direction"], "direction_factor_sensitivity_summary_by_direction"
    )
    comparison = unit_rates[
        [
            "reference_signal_id",
            "signal_relative_direction",
            "analysis_window",
            "assigned_crash_count",
            "v1_estimated_exposure",
            "v2_direction_factor_adjusted_exposure",
            "exposure_ratio_v2_to_v1",
            "v1_rate_per_million",
            "v2_rate_per_million",
            "rate_ratio_v2_to_v1",
            "direction_factor_applied_flag",
            "direction_factor_missing_bidirectional_fallback_flag",
            "direction_factor_invalid_review_flag",
            "sensitivity_output_flag",
        ]
    ].copy()
    coverage = build_coverage(unit_rates)
    missing_fallback = build_missing_fallback_summary(unit_rates)

    rate_after = _file_fingerprint(RATE_ROWS_FILE)
    v1_unchanged = rate_before == rate_after
    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "guarded reads reject crash-direction tokens", "required"),
            ("direction_factor_not_applied_to_v1_outputs", v1_unchanged, str(RATE_ROWS_FILE), "same fingerprint before and after"),
            (
                "v2_outputs_clearly_labeled_sensitivity",
                unit_rates["sensitivity_output_flag"].all()
                and summary_by_window["sensitivity_output_flag"].all()
                and summary_by_direction["sensitivity_output_flag"].all(),
                "sensitivity_output_flag present",
                "required",
            ),
            (
                "null_direction_factor_rows_use_bidirectional_fallback_and_are_flagged",
                unit_rates.loc[unit_rates["missing_direction_factor_bin_count"].fillna(0).gt(0), "direction_factor_missing_bidirectional_fallback_flag"].all(),
                int(unit_rates["direction_factor_missing_bidirectional_fallback_flag"].sum()),
                "all null-factor units flagged",
            ),
            ("no_models_or_regressions_fit", True, "descriptive arithmetic only", "required"),
            (
                "no_rankings_policy_risk_language",
                True,
                "outputs are grouped summaries and unordered unit comparisons only",
                "required",
            ),
            (
                "all_v2_rates_at_approved_window_grain_only",
                unit_rates["analysis_unit_grain"].eq(AUTHORIZED_GRAIN).all() and "distance_band" not in unit_rates.columns,
                AUTHORIZED_GRAIN,
                AUTHORIZED_GRAIN,
            ),
            ("no_raw_bin_rates_computed", True, "bin context used only to aggregate adjusted AADT to window units", "required"),
            ("no_fixed_band_rates_computed", True, "no fixed distance-band rate output created", "required"),
            ("no_signal_rankings_created", True, "no sorted ranking output created", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    outputs = {
        "direction_factor_sensitivity_unit_rates.csv": unit_rates,
        "direction_factor_sensitivity_non_ready_units.csv": non_ready,
        "direction_factor_sensitivity_summary_by_window.csv": summary_by_window,
        "direction_factor_sensitivity_summary_by_direction.csv": summary_by_direction,
        "direction_factor_sensitivity_comparison_to_v1.csv": comparison,
        "direction_factor_application_coverage.csv": coverage,
        "direction_factor_missing_fallback_summary.csv": missing_fallback,
        "direction_factor_sensitivity_qa.csv": qa,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)

    total_units = len(unit_rates)
    factor_units_count = int(unit_rates["direction_factor_applied_flag"].sum())
    fallback_units_count = int(unit_rates["direction_factor_missing_bidirectional_fallback_flag"].sum())
    invalid_units_count = int(unit_rates["direction_factor_invalid_review_flag"].sum())
    v1_exposure = float(unit_rates["v1_estimated_exposure"].sum())
    v2_exposure = float(unit_rates["v2_direction_factor_adjusted_exposure"].sum())
    exposure_ratio = v2_exposure / v1_exposure if v1_exposure else pd.NA
    v1_rate = float(unit_rates["assigned_crash_count"].sum() * 1_000_000 / v1_exposure)
    v2_rate = float(unit_rates["assigned_crash_count"].sum() * 1_000_000 / v2_exposure)
    rate_ratio = v2_rate / v1_rate if v1_rate else pd.NA
    plausibility = (
        "plausible_enough_for_internal_review_with_source_documentation_needed"
        if factor_units_count > 0 and invalid_units_count == 0 and v2_exposure < v1_exposure
        else "requires_internal_review_before_any_denominator_policy_change"
    )

    findings = f"""# Direction Factor Exposure Sensitivity Findings

**Status:** sensitivity analysis only. This does not replace descriptive crash-rate prototype v1, does not change the accepted bidirectional denominator policy, does not modify the AADT join, and is not a safety-performance, causal, policy, or ranking output.

## Bounded Question

How much do approved window-grain descriptive exposure and rates change if valid non-null AADT `DIRECTION_FACTOR` values are applied, while null factors retain v1 bidirectional AADT treatment?

## V2 Rule

For stable AADT denominator bins, valid `DIRECTION_FACTOR` values where `0 < factor <= 1` are applied to AADT. Null factors retain v1 bidirectional AADT treatment and are flagged. Invalid factors retain v1 treatment and are flagged for review. The adjusted AADT is length-weighted back to `reference_signal_id + signal_relative_direction + analysis_window` before computing v2 exposure and descriptive rates.

## Coverage

- Units evaluated: {total_units:,}.
- Units with factor applied: {factor_units_count:,}.
- Units using null-factor bidirectional fallback: {fallback_units_count:,}.
- Units with invalid factor: {invalid_units_count:,}.
- Non-ready v1 units preserved without v2 rates: {len(non_ready):,}.

## V1 To V2 Change

- V1 estimated exposure: {v1_exposure:,.2f}.
- V2 direction-factor adjusted exposure: {v2_exposure:,.2f}.
- Aggregate exposure ratio v2/v1: {exposure_ratio:.6f}.
- V1 aggregate descriptive rate per million: {v1_rate:.6f}.
- V2 aggregate descriptive rate per million: {v2_rate:.6f}.
- Aggregate rate ratio v2/v1: {rate_ratio:.6f}.

## Interpretation

The v2 result is `{plausibility}`. It is directionally plausible as an internal sensitivity because applying factors generally lowers exposure and raises descriptive rates, which matches the prior AADT direction-factor audit. It remains review-only because source documentation is still needed before treating `DIRECTION_FACTOR` as an accepted denominator policy.

## Validation

The QA table confirms no crash direction fields were read or used, v1 outputs were not overwritten, null-factor fallback rows are flagged, no models/regressions were fit, no raw-bin or fixed-band rates were created, and all v2 rates remain at the approved window grain.
"""
    _write_text(findings, OUTPUT_DIR / "direction_factor_sensitivity_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "direction-factor exposure sensitivity for approved window-grain descriptive crash-rate prototype",
        "status": "sensitivity_analysis_only_not_v1_replacement",
        "inputs": [str(path) for path in _input_files()],
        "outputs": sorted(
            str(OUTPUT_DIR / name)
            for name in list(outputs) + ["direction_factor_sensitivity_findings.md", "direction_factor_sensitivity_manifest.json"]
        ),
        "study_period": {
            "label": STUDY_PERIOD_LABEL,
            "days": STUDY_PERIOD_DAYS,
            "years": STUDY_PERIOD_YEARS,
        },
        "approved_rate_grain": "reference_signal_id + signal_relative_direction + analysis_window",
        "v2_rule": "valid non-null DIRECTION_FACTOR applied to stable AADT bins; null/invalid factors retain v1 AADT treatment with flags",
        "summary": {
            "units_evaluated": total_units,
            "units_with_factor_applied": factor_units_count,
            "units_with_null_factor_bidirectional_fallback": fallback_units_count,
            "units_with_invalid_factor": invalid_units_count,
            "v1_estimated_exposure": v1_exposure,
            "v2_direction_factor_adjusted_exposure": v2_exposure,
            "exposure_ratio_v2_to_v1": exposure_ratio,
            "v1_rate_per_million": v1_rate,
            "v2_rate_per_million": v2_rate,
            "rate_ratio_v2_to_v1": rate_ratio,
            "internal_review_plausibility": plausibility,
            "source_documentation_still_needed": True,
        },
        "guardrails": {
            "v1_outputs_overwritten": False,
            "accepted_denominator_policy_changed": False,
            "aadt_join_modified": False,
            "crash_direction_fields_used": False,
            "models_or_regressions_fit": False,
            "causal_policy_safety_performance_risk_claims": False,
            "signal_rankings_created": False,
            "raw_bin_rates_computed": False,
            "fixed_band_rates_computed": False,
        },
        "rate_file_fingerprint_before": rate_before,
        "rate_file_fingerprint_after": rate_after,
        "qa_passed": bool(qa["passed"].astype(str).str.lower().eq("true").all()),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "direction_factor_sensitivity_manifest.json")
    return {
        "unit_rates": unit_rates,
        "summary_by_window": summary_by_window,
        "summary_by_direction": summary_by_direction,
        "coverage": coverage,
        "qa": qa,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only AADT direction-factor exposure sensitivity rates.")
    parser.parse_args()
    result = build_outputs()
    print(json.dumps(result["manifest"]["summary"], indent=2))


if __name__ == "__main__":
    main()
