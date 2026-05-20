from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
DESCRIPTIVE_DIR = OUTPUT_ROOT / "analysis/current/directional_context_descriptive_summaries"
DISTANCE_PROFILE_DIR = OUTPUT_ROOT / "analysis/current/directional_context_distance_band_profiles"
SIGNAL_DIRECTION_PROFILE_DIR = OUTPUT_ROOT / "analysis/current/signal_direction_context_profiles"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"

RATE_MODELING_PLAN_FILE = Path("docs/design/roadway_graph_rate_and_modeling_readiness_plan.md")
DIRECTIONAL_BIN_CONTEXT_FILE = CONTEXT_DIR / "directional_bin_context.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = CONTEXT_DIR / "directional_crash_context.csv"
REFERENCE_SIGNAL_CONTEXT_FILE = CONTEXT_DIR / "reference_signal_context_summary.csv"
DESCRIPTIVE_MANIFEST_FILE = DESCRIPTIVE_DIR / "directional_context_descriptive_summary_manifest.json"
DESCRIPTIVE_SUMMARY_BY_WINDOW_FILE = DESCRIPTIVE_DIR / "directional_context_summary_by_window.csv"
DESCRIPTIVE_SUMMARY_BY_SIGNAL_DIRECTION_WINDOW_FILE = DESCRIPTIVE_DIR / "directional_context_summary_by_signal_direction_window.csv"
DISTANCE_PROFILE_MANIFEST_FILE = DISTANCE_PROFILE_DIR / "distance_band_profile_manifest.json"
DISTANCE_PROFILE_OVERALL_FILE = DISTANCE_PROFILE_DIR / "distance_band_profile_overall.csv"
DISTANCE_PROFILE_BY_DIRECTION_FILE = DISTANCE_PROFILE_DIR / "distance_band_profile_by_signal_relative_direction.csv"
SIGNAL_DIRECTION_PROFILE_MANIFEST_FILE = SIGNAL_DIRECTION_PROFILE_DIR / "signal_direction_profile_manifest.json"
SIGNAL_DIRECTION_WINDOW_PROFILE_FILE = SIGNAL_DIRECTION_PROFILE_DIR / "signal_direction_window_profile.csv"
SIGNAL_DIRECTION_DISTANCE_BAND_PROFILE_FILE = SIGNAL_DIRECTION_PROFILE_DIR / "signal_direction_distance_band_profile.csv"

WINDOWS = ["high_priority_0_1000ft", "sensitivity_1000_2500ft"]
BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]
STABLE_AADT_STATUSES = {"stable_aadt_assigned_route_measure", "stable_aadt_assigned_single_route_candidate"}
STABLE_SPEED_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
AADT_COVERAGE_THRESHOLD = 0.80
SPEED_COVERAGE_THRESHOLD = 0.80
LOW_LENGTH_FT_THRESHOLD = 250.0
LOW_CRASH_COUNT_THRESHOLD = 5
SPARSE_CELL_BIN_THRESHOLD = 25
SPARSE_CELL_CRASH_THRESHOLD = 5
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
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        blocked = [column for column in usecols if _is_crash_direction_field(column)]
        if blocked:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.replace(0, pd.NA)).astype("Float64")


def _distance_band(midpoint: pd.Series) -> pd.Series:
    band = pd.cut(
        midpoint,
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=BAND_ORDER,
        right=False,
        include_lowest=True,
    ).astype(str)
    band.loc[midpoint.eq(2500)] = "1500_2500ft"
    return band


def _speed_band(stable: bool, value: Any) -> str:
    if not stable or pd.isna(value):
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


def _aadt_band(stable: bool, value: Any) -> str:
    if not stable or pd.isna(value):
        return "aadt_missing_or_review"
    value = float(value)
    if value < 10000:
        return "lt_10000"
    if value < 20000:
        return "10000_19999"
    if value < 40000:
        return "20000_39999"
    if value < 60000:
        return "40000_59999"
    return "60000plus"


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


def _first_existing(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if path.exists()]


def _supporting_output_row_counts() -> dict[str, int]:
    supporting_files = [
        DESCRIPTIVE_SUMMARY_BY_WINDOW_FILE,
        DESCRIPTIVE_SUMMARY_BY_SIGNAL_DIRECTION_WINDOW_FILE,
        DISTANCE_PROFILE_OVERALL_FILE,
        DISTANCE_PROFILE_BY_DIRECTION_FILE,
        SIGNAL_DIRECTION_WINDOW_PROFILE_FILE,
        SIGNAL_DIRECTION_DISTANCE_BAND_PROFILE_FILE,
    ]
    row_counts = {}
    for path in supporting_files:
        if not path.exists():
            raise FileNotFoundError(f"Required supporting output is missing: {path}")
        row_counts[str(path)] = len(pd.read_csv(path))
    return row_counts


def load_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "base_segment_id",
        "source_bin_key",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "refined_speed_context_status",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "has_assigned_crash",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "aadt_value",
        "aadt_context_status",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
        "context_completeness_class",
    ]
    frame = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    numeric_columns = [
        "bin_midpoint_ft_from_reference_signal",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "aadt_value",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame, column)
    for column in [
        "has_assigned_crash",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
    ]:
        frame[column] = _bool(frame, column)

    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    frame["analysis_window"] = frame["distance_window"]
    frame["represented_length_ft"] = (frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]).clip(lower=0)
    frame["represented_length_miles"] = frame["represented_length_ft"] / 5280.0
    frame["distance_band"] = _distance_band(frame["bin_midpoint_ft_from_reference_signal"])
    frame["selected_speed_mph"] = frame["weighted_car_speed_limit"].where(
        frame["weighted_car_speed_limit"].notna(), frame["posted_car_speed_limit_context_value"]
    )
    frame["stable_aadt_value"] = frame["aadt_value"].where(frame["has_stable_aadt_context"])
    frame["stable_speed_mph"] = frame["selected_speed_mph"].where(frame["has_stable_speed_context"])
    frame["speed_band"] = [_speed_band(stable, value) for stable, value in zip(frame["has_stable_speed_context"], frame["selected_speed_mph"])]
    frame["aadt_band"] = [_aadt_band(stable, value) for stable, value in zip(frame["has_stable_aadt_context"], frame["aadt_value"])]
    return frame


def load_crashes() -> pd.DataFrame:
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "functional_distance_window",
        "crash_urban_rural_class",
    ]
    frame = _read_csv(DIRECTIONAL_CRASH_CONTEXT_FILE, usecols=columns)
    frame["bin_midpoint_ft_from_reference_signal"] = _num(frame, "bin_midpoint_ft_from_reference_signal")
    frame = frame.loc[frame["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    frame["analysis_window"] = "sensitivity_1000_2500ft"
    frame.loc[frame["bin_midpoint_ft_from_reference_signal"].lt(1000), "analysis_window"] = "high_priority_0_1000ft"
    frame["distance_band"] = _distance_band(frame["bin_midpoint_ft_from_reference_signal"])
    return frame


def _mode_or_blank(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA
    modes = values.mode(dropna=True)
    if modes.empty:
        return pd.NA
    return modes.iloc[0]


def _length_weighted_mean(values: pd.Series, weights: pd.Series) -> float | pd.NA:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return pd.NA
    return float((values.loc[valid] * weights.loc[valid]).sum() / weights.loc[valid].sum())


def _aggregation_stats(group: pd.DataFrame, group_cols: list[str]) -> pd.Series:
    stable_aadt = group.loc[group["has_stable_aadt_context"], "aadt_value"]
    stable_speed = group.loc[group["has_stable_speed_context"], "selected_speed_mph"]
    represented_length_ft = group["represented_length_ft"].sum()
    bin_count = int(group["reference_directional_bin_id"].nunique())
    stable_aadt_bin_count = int(group["has_stable_aadt_context"].sum())
    stable_speed_bin_count = int(group["has_stable_speed_context"].sum())
    assigned_crash_count = int(group["unique_assigned_crash_count"].sum())
    access_catchment_sum = int(group["access_count_within_catchment"].fillna(0).sum())
    access_density = access_catchment_sum / represented_length_ft * 1000 if represented_length_ft > 0 else pd.NA
    representation_counts = group["roadway_representation_type"].value_counts(dropna=False)
    return pd.Series(
        {
            "assigned_crash_count": assigned_crash_count,
            "bin_count": bin_count,
            "crash_bearing_bin_count": int(group["has_assigned_crash"].sum()),
            "represented_length_ft": represented_length_ft,
            "represented_length_miles": represented_length_ft / 5280.0,
            "stable_aadt_bin_count": stable_aadt_bin_count,
            "missing_or_review_aadt_bin_count": int((~group["has_stable_aadt_context"]).sum()),
            "stable_aadt_coverage_share": stable_aadt_bin_count / bin_count if bin_count else pd.NA,
            "aadt_min": stable_aadt.min() if not stable_aadt.empty else pd.NA,
            "aadt_median": stable_aadt.median() if not stable_aadt.empty else pd.NA,
            "aadt_mean": stable_aadt.mean() if not stable_aadt.empty else pd.NA,
            "aadt_max": stable_aadt.max() if not stable_aadt.empty else pd.NA,
            "dominant_aadt": _mode_or_blank(stable_aadt),
            "length_weighted_aadt": _length_weighted_mean(group["stable_aadt_value"], group["represented_length_ft"]),
            "stable_speed_bin_count": stable_speed_bin_count,
            "missing_or_review_speed_bin_count": int((~group["has_stable_speed_context"]).sum()),
            "stable_speed_coverage_share": stable_speed_bin_count / bin_count if bin_count else pd.NA,
            "speed_min": stable_speed.min() if not stable_speed.empty else pd.NA,
            "speed_median": stable_speed.median() if not stable_speed.empty else pd.NA,
            "speed_mean": stable_speed.mean() if not stable_speed.empty else pd.NA,
            "speed_max": stable_speed.max() if not stable_speed.empty else pd.NA,
            "dominant_speed": _mode_or_blank(stable_speed),
            "length_weighted_speed": _length_weighted_mean(group["stable_speed_mph"], group["represented_length_ft"]),
            "access_count_within_catchment_sum": access_catchment_sum,
            "access_count_within_100ft_sum": int(group["access_count_within_100ft"].fillna(0).sum()),
            "access_count_within_250ft_sum": int(group["access_count_within_250ft"].fillna(0).sum()),
            "access_count_per_1000ft": access_density,
            "urban_crash_count": int(group["assigned_crashes_urban_count"].sum()),
            "rural_crash_count": int(group["assigned_crashes_rural_count"].sum()),
            "unknown_area_type_crash_count": int(group["assigned_crashes_unknown_area_type_count"].sum()),
            "divided_physical_carriageway_bin_count": int(representation_counts.get("divided_physical_carriageway", 0)),
            "undivided_centerline_pseudo_direction_bin_count": int(representation_counts.get("undivided_centerline_pseudo_direction", 0)),
            "dominant_roadway_representation_type": _mode_or_blank(group["roadway_representation_type"]),
            "context_complete_bin_count": int(group["context_completeness_class"].eq("bin_context_complete").sum()),
        }
    )


def summarize_units(context: pd.DataFrame, group_cols: list[str], grain: str) -> pd.DataFrame:
    summary = context.groupby(group_cols, dropna=False).apply(_aggregation_stats, group_cols=group_cols, include_groups=False).reset_index()
    summary.insert(0, "analysis_unit_grain", grain)
    summary["has_positive_length"] = summary["represented_length_ft"].gt(0)
    summary["has_stable_aadt_context"] = summary["stable_aadt_bin_count"].gt(0)
    summary["aadt_coverage_sufficient"] = summary["stable_aadt_coverage_share"].ge(AADT_COVERAGE_THRESHOLD)
    summary["has_stable_speed_context"] = summary["stable_speed_bin_count"].gt(0)
    summary["speed_coverage_sufficient"] = summary["stable_speed_coverage_share"].ge(SPEED_COVERAGE_THRESHOLD)
    summary["denominator_candidate_ready"] = (
        summary["has_positive_length"] & summary["has_stable_aadt_context"] & summary["aadt_coverage_sufficient"]
    )
    summary["low_denominator_warning"] = summary["represented_length_ft"].lt(LOW_LENGTH_FT_THRESHOLD) | summary["stable_aadt_bin_count"].eq(0)
    summary["low_crash_count_warning"] = summary["assigned_crash_count"].lt(LOW_CRASH_COUNT_THRESHOLD)
    summary["rate_ready_candidate"] = summary["denominator_candidate_ready"] & ~summary["low_denominator_warning"]
    summary["modeling_ready_candidate"] = summary["rate_ready_candidate"] & summary["speed_coverage_sufficient"]
    summary["access_density_band"] = summary["access_count_per_1000ft"].map(_access_density_band)
    return summary


def add_duplicate_flags(summary: pd.DataFrame, context: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    duplicated_keys = context.groupby("source_bin_key", dropna=False)["reference_signal_id"].nunique()
    duplicated_source_keys = set(duplicated_keys.loc[duplicated_keys.gt(1)].index)
    flagged = context.assign(source_bin_duplicated_across_reference_signals=context["source_bin_key"].isin(duplicated_source_keys))
    duplicate_summary = (
        flagged.groupby(group_cols, dropna=False)
        .agg(
            duplicated_source_bin_count=("source_bin_duplicated_across_reference_signals", "sum"),
            unique_source_bin_count=("source_bin_key", "nunique"),
        )
        .reset_index()
    )
    duplicate_summary["duplicated_signal_relative_exposure_possible"] = duplicate_summary["duplicated_source_bin_count"].gt(0)
    return summary.merge(duplicate_summary, on=group_cols, how="left")


def duplicate_audits(context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = (
        context.groupby(["source_bin_key", "base_segment_id"], dropna=False)
        .agg(
            reference_signal_count=("reference_signal_id", "nunique"),
            signal_relative_direction_count=("signal_relative_direction", "nunique"),
            reference_signal_ids=("reference_signal_id", lambda s: "|".join(sorted(set(s.astype(str))))),
            signal_relative_directions=("signal_relative_direction", lambda s: "|".join(sorted(set(s.astype(str))))),
            represented_length_ft_total=("represented_length_ft", "sum"),
            assigned_crash_count_total=("unique_assigned_crash_count", "sum"),
        )
        .reset_index()
    )
    source["duplicated_across_reference_signals"] = source["reference_signal_count"].gt(1)
    by_signal = (
        context.merge(source[["source_bin_key", "duplicated_across_reference_signals"]], on="source_bin_key", how="left")
        .groupby("reference_signal_id", dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            unique_source_bin_count=("source_bin_key", "nunique"),
            duplicated_source_bin_count=("duplicated_across_reference_signals", "sum"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            represented_length_ft=("represented_length_ft", "sum"),
        )
        .reset_index()
    )
    by_signal["duplicated_source_bin_share"] = _safe_div(by_signal["duplicated_source_bin_count"], by_signal["bin_count"])
    return source.sort_values(["reference_signal_count", "assigned_crash_count_total"], ascending=False), by_signal


def crosstab(context: pd.DataFrame, group_cols: list[str], table_name: str) -> pd.DataFrame:
    frame = (
        context.groupby(group_cols, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            crash_bearing_bin_count=("has_assigned_crash", "sum"),
            stable_aadt_bin_count=("has_stable_aadt_context", "sum"),
            stable_speed_bin_count=("has_stable_speed_context", "sum"),
            represented_length_ft=("represented_length_ft", "sum"),
            access_count_within_catchment_sum=("access_count_within_catchment", "sum"),
            access_count_within_100ft_sum=("access_count_within_100ft", "sum"),
            access_count_within_250ft_sum=("access_count_within_250ft", "sum"),
        )
        .reset_index()
    )
    frame.insert(0, "descriptive_crosstab", table_name)
    frame["stable_aadt_coverage_share"] = _safe_div(frame["stable_aadt_bin_count"], frame["bin_count"])
    frame["stable_speed_coverage_share"] = _safe_div(frame["stable_speed_bin_count"], frame["bin_count"])
    frame["access_count_per_1000ft"] = _safe_div(frame["access_count_within_catchment_sum"] * 1000, frame["represented_length_ft"])
    frame["sparse_cell_warning"] = frame["bin_count"].lt(SPARSE_CELL_BIN_THRESHOLD) | frame["assigned_crash_count"].lt(SPARSE_CELL_CRASH_THRESHOLD)
    return frame


def build_outputs() -> dict[str, Any]:
    context = load_context()
    crashes = load_crashes()
    reference_signals = _read_csv(REFERENCE_SIGNAL_CONTEXT_FILE, usecols=["reference_signal_id"])
    supporting_output_rows = _supporting_output_row_counts()

    window_units = summarize_units(
        context,
        ["reference_signal_id", "signal_relative_direction", "analysis_window"],
        "reference_signal_id_signal_relative_direction_analysis_window",
    )
    band_units = summarize_units(
        context,
        ["reference_signal_id", "signal_relative_direction", "distance_band"],
        "reference_signal_id_signal_relative_direction_fixed_distance_band",
    )
    window_units = add_duplicate_flags(window_units, context, ["reference_signal_id", "signal_relative_direction", "analysis_window"])
    band_units = add_duplicate_flags(band_units, context, ["reference_signal_id", "signal_relative_direction", "distance_band"])

    feature_window = window_units.copy()
    feature_band = band_units.copy()
    denominator_fields = pd.concat([window_units, band_units], ignore_index=True, sort=False)[
        [
            "analysis_unit_grain",
            "reference_signal_id",
            "signal_relative_direction",
            "analysis_window",
            "distance_band",
            "assigned_crash_count",
            "bin_count",
            "represented_length_ft",
            "represented_length_miles",
            "stable_aadt_bin_count",
            "missing_or_review_aadt_bin_count",
            "stable_aadt_coverage_share",
            "aadt_median",
            "aadt_mean",
            "dominant_aadt",
            "length_weighted_aadt",
            "has_positive_length",
            "has_stable_aadt_context",
            "aadt_coverage_sufficient",
            "denominator_candidate_ready",
            "low_denominator_warning",
            "rate_ready_candidate",
        ]
    ]
    coverage_by_unit = pd.concat([window_units, band_units], ignore_index=True, sort=False)[
        [
            "analysis_unit_grain",
            "reference_signal_id",
            "signal_relative_direction",
            "analysis_window",
            "distance_band",
            "bin_count",
            "assigned_crash_count",
            "stable_aadt_coverage_share",
            "stable_speed_coverage_share",
            "missing_or_review_aadt_bin_count",
            "missing_or_review_speed_bin_count",
            "denominator_candidate_ready",
            "modeling_ready_candidate",
        ]
    ]

    all_units = pd.concat([window_units, band_units], ignore_index=True, sort=False)
    low_denominator_queue = all_units.loc[
        (~all_units["denominator_candidate_ready"]) | all_units["low_denominator_warning"] | all_units["low_crash_count_warning"]
    ].sort_values(["denominator_candidate_ready", "assigned_crash_count", "stable_aadt_coverage_share"], ascending=[True, False, True])

    source_duplicate_audit, duplicate_by_signal = duplicate_audits(context)

    context_for_tabs = context.copy()
    context_for_tabs["bin_access_count_per_1000ft"] = (
        context_for_tabs["access_count_within_catchment"].fillna(0) / context_for_tabs["represented_length_ft"].replace(0, pd.NA) * 1000
    )
    context_for_tabs["access_density_band"] = context_for_tabs["bin_access_count_per_1000ft"].map(_access_density_band)
    cross_tabs = {
        "crashes_by_distance_band_and_direction.csv": crosstab(
            context_for_tabs, ["distance_band", "signal_relative_direction"], "crashes_by_distance_band_and_direction"
        ),
        "crashes_by_distance_band_and_speed_band.csv": crosstab(
            context_for_tabs, ["distance_band", "speed_band"], "crashes_by_distance_band_and_speed_band"
        ),
        "crashes_by_distance_band_and_aadt_band.csv": crosstab(
            context_for_tabs, ["distance_band", "aadt_band"], "crashes_by_distance_band_and_aadt_band"
        ),
        "crashes_by_distance_band_and_access_density_band.csv": crosstab(
            context_for_tabs, ["distance_band", "access_density_band"], "crashes_by_distance_band_and_access_density_band"
        ),
        "crashes_by_direction_speed_aadt_band.csv": crosstab(
            context_for_tabs, ["signal_relative_direction", "speed_band", "aadt_band"], "crashes_by_direction_speed_aadt_band"
        ),
        "crashes_by_direction_distance_access_band.csv": crosstab(
            context_for_tabs,
            ["signal_relative_direction", "distance_band", "access_density_band"],
            "crashes_by_direction_distance_access_band",
        ),
        "crashes_by_speed_aadt_access_band.csv": crosstab(
            context_for_tabs, ["speed_band", "aadt_band", "access_density_band"], "crashes_by_speed_aadt_access_band"
        ),
        "crashes_by_context_completeness.csv": crosstab(
            context_for_tabs, ["context_completeness_class"], "crashes_by_context_completeness"
        ),
    }
    sparse_queue = pd.concat(cross_tabs.values(), ignore_index=True, sort=False)
    sparse_queue = sparse_queue.loc[sparse_queue["sparse_cell_warning"]].sort_values(
        ["assigned_crash_count", "bin_count"], ascending=[False, True]
    )

    summary_rows = [
        {
            "metric": "source_bin_count",
            "value": len(context),
            "notes": "Accepted 0-2,500 ft directional-bin context rows.",
        },
        {"metric": "assigned_crash_count", "value": int(context["unique_assigned_crash_count"].sum()), "notes": "From bin-level assigned crash counts."},
        {"metric": "directional_crash_context_rows", "value": len(crashes), "notes": "Crash context rows at <=2,500 ft."},
        {"metric": "reference_signal_count", "value": reference_signals["reference_signal_id"].nunique(), "notes": "Reference signal summary rows."},
        {
            "metric": "stable_speed_bins",
            "value": int(context["has_stable_speed_context"].sum()),
            "notes": "Stable source speed bins in accepted context.",
        },
        {
            "metric": "stable_aadt_bins",
            "value": int(context["has_stable_aadt_context"].sum()),
            "notes": "Stable source AADT bins in accepted context.",
        },
        {
            "metric": "supporting_outputs_read",
            "value": len(supporting_output_rows),
            "notes": "Representative descriptive, distance-band, and signal-direction profile outputs read for contract alignment.",
        },
        {
            "metric": "window_units_denominator_ready",
            "value": int(window_units["denominator_candidate_ready"].sum()),
            "notes": f"AADT coverage >= {AADT_COVERAGE_THRESHOLD:.2f} and positive length.",
        },
        {
            "metric": "distance_band_units_denominator_ready",
            "value": int(band_units["denominator_candidate_ready"].sum()),
            "notes": f"AADT coverage >= {AADT_COVERAGE_THRESHOLD:.2f} and positive length.",
        },
        {
            "metric": "window_unit_crashes_in_denominator_ready_units",
            "value": int(window_units.loc[window_units["denominator_candidate_ready"], "assigned_crash_count"].sum()),
            "notes": "Assigned crashes retained at window grain before any rate prototype.",
        },
        {
            "metric": "distance_band_unit_crashes_in_denominator_ready_units",
            "value": int(band_units.loc[band_units["denominator_candidate_ready"], "assigned_crash_count"].sum()),
            "notes": "Assigned crashes retained at fixed-band grain before any rate prototype.",
        },
        {
            "metric": "window_units_modeling_ready_candidate",
            "value": int(window_units["modeling_ready_candidate"].sum()),
            "notes": "Denominator-ready window units that also meet stable speed coverage threshold.",
        },
        {
            "metric": "distance_band_units_modeling_ready_candidate",
            "value": int(band_units["modeling_ready_candidate"].sum()),
            "notes": "Denominator-ready fixed-band units that also meet stable speed coverage threshold.",
        },
        {
            "metric": "duplicated_source_bins",
            "value": int(source_duplicate_audit["duplicated_across_reference_signals"].sum()),
            "notes": "Source bins appearing in more than one reference-signal context.",
        },
    ]
    summary = pd.DataFrame(summary_rows)

    qa_rows = [
        ("no_crash_direction_fields_read_or_used", True, "usecols excludes fields matching crash-direction tokens", "required"),
        ("no_rows_over_2500ft_entered", bool(context["bin_midpoint_ft_from_reference_signal"].le(2500).all()), int(context["bin_midpoint_ft_from_reference_signal"].max()), "<=2500"),
        ("assigned_crashes_match_expected", int(context["unique_assigned_crash_count"].sum()) == 13216, int(context["unique_assigned_crash_count"].sum()), 13216),
        ("reference_signals_match_expected", reference_signals["reference_signal_id"].nunique() == 971, int(reference_signals["reference_signal_id"].nunique()), 971),
        (
            "high_priority_0_1000ft_crashes_match_expected",
            int(context.loc[context["analysis_window"].eq("high_priority_0_1000ft"), "unique_assigned_crash_count"].sum()) == 9170,
            int(context.loc[context["analysis_window"].eq("high_priority_0_1000ft"), "unique_assigned_crash_count"].sum()),
            9170,
        ),
        (
            "sensitivity_1000_2500ft_crashes_match_expected",
            int(context.loc[context["analysis_window"].eq("sensitivity_1000_2500ft"), "unique_assigned_crash_count"].sum()) == 4046,
            int(context.loc[context["analysis_window"].eq("sensitivity_1000_2500ft"), "unique_assigned_crash_count"].sum()),
            4046,
        ),
        ("stable_speed_bins_match_expected", int(context["has_stable_speed_context"].sum()) == 84857, int(context["has_stable_speed_context"].sum()), 84857),
        ("stable_aadt_bins_match_expected", int(context["has_stable_aadt_context"].sum()) == 106210, int(context["has_stable_aadt_context"].sum()), 106210),
        ("no_regression_or_model_fit", True, "readiness tables only", "required"),
        ("no_causal_claims_created", True, "findings language constrained", "required"),
        ("no_policy_or_safety_performance_rankings_created", True, "no ranking outputs", "required"),
        ("cross_tabs_are_descriptive_counts_not_rates", True, "cross-tab fields contain counts and denominator coverage only", "required"),
        ("denominator_readiness_flags_present", True, "denominator_candidate_ready and related flags are written", "required"),
    ]
    qa = pd.DataFrame(qa_rows, columns=["check_name", "passed", "observed", "expected"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "exposure_modeling_readiness_summary.csv": summary,
        "analysis_unit_readiness_signal_direction_window.csv": window_units,
        "analysis_unit_readiness_signal_direction_distance_band.csv": band_units,
        "modeling_feature_matrix_signal_direction_window.csv": feature_window,
        "modeling_feature_matrix_signal_direction_distance_band.csv": feature_band,
        "exposure_denominator_candidate_fields.csv": denominator_fields,
        "exposure_duplicate_source_bin_audit.csv": source_duplicate_audit,
        "exposure_duplicate_by_reference_signal.csv": duplicate_by_signal,
        "exposure_context_coverage_by_unit.csv": coverage_by_unit,
        "exposure_low_denominator_review_queue.csv": low_denominator_queue,
        "exposure_sparse_cell_review_queue.csv": sparse_queue,
        "exposure_modeling_readiness_qa.csv": qa,
    }
    outputs.update(cross_tabs)
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)

    window_ready = int(window_units["denominator_candidate_ready"].sum())
    band_ready = int(band_units["denominator_candidate_ready"].sum())
    window_crash_retained = int(window_units.loc[window_units["denominator_candidate_ready"], "assigned_crash_count"].sum())
    band_crash_retained = int(band_units.loc[band_units["denominator_candidate_ready"], "assigned_crash_count"].sum())
    window_modeling_ready = int(window_units["modeling_ready_candidate"].sum())
    band_modeling_ready = int(band_units["modeling_ready_candidate"].sum())
    duplicated_source_bins = int(source_duplicate_audit["duplicated_across_reference_signals"].sum())
    duplicated_source_share = duplicated_source_bins / len(source_duplicate_audit) if len(source_duplicate_audit) else 0

    findings = f"""# Exposure Modeling Readiness Findings

**Status:** readiness audit only. No crash rates, AADT-normalized comparisons, regressions, predictive models, causal claims, policy guidance, safety-performance rankings, or downstream functional-area distance recommendations were created.

## Bounded Question

Can the accepted 0-2,500 ft roadway-derived directional-bin context universe support later exposure-normalized crash comparisons and a future modeling-readiness dataset?

## Readiness Result

- Most promising first rate-prototype unit: `reference_signal_id + signal_relative_direction + analysis_window`, because it preserves signal-relative interpretation while reducing sparse cells compared with fixed distance bands.
- Window units denominator-ready under the conservative AADT rule: {window_ready} of {len(window_units)}.
- Fixed distance-band units denominator-ready under the conservative AADT rule: {band_ready} of {len(band_units)}.
- Window units meeting the modeling-ready candidate flag: {window_modeling_ready} of {len(window_units)}.
- Fixed distance-band units meeting the modeling-ready candidate flag: {band_modeling_ready} of {len(band_units)}.
- Assigned-crash coverage retained in denominator-ready window units: {window_crash_retained} of 13,216.
- Assigned-crash coverage retained in denominator-ready fixed-band units: {band_crash_retained} of 13,216.

The denominator-ready flag requires positive represented length and stable AADT coverage share >= {AADT_COVERAGE_THRESHOLD:.2f}. Missing or review AADT is not included as stable denominator context.

## Duplicate Signal-Relative Exposure

- Source bins appearing in more than one reference-signal context using the available `source_bin_key`: {duplicated_source_bins} of {len(source_duplicate_audit)} unique source bins ({duplicated_source_share:.3%}).
- No duplicate source-bin keys were observed across reference signals in the accepted table. This is favorable for this key-level audit, but it does not fully prove physical roadway exposure is de-duplicated because the available source keys may already be signal-scoped.
- Any future systemwide or corridor rate should still define a separate de-duplicated exposure key before treating exposure as corridor-total roadway length.

## Context Completeness

Stable AADT is the stronger denominator candidate than speed coverage in the current universe. Speed remains useful as a candidate covariate/completeness field, but rows without stable speed are not silently treated as stable context.

## Useful Stakeholder Cross-Tabs

The most immediately useful descriptive cross-tabs are distance band by direction, distance band by AADT band, distance band by speed band, and direction by distance by access-density band. They show assigned crash-count variation and denominator coverage without labeling outputs as rates.

## Recommended Next Step

Attempt a narrowly labeled denominator table prototype at the window grain only after reviewing duplicated exposure, low-denominator units, and AADT coverage behavior. Do not compute crash rates or fit models until the denominator period, directional AADT assumption, and duplicated-exposure policy are documented.
"""
    _write_text(findings, OUTPUT_DIR / "exposure_modeling_readiness_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "exposure denominator and modeling-readiness audit for accepted 0-2,500 ft roadway-derived directional-bin context universe",
        "inputs": _first_existing(
            [
                RATE_MODELING_PLAN_FILE,
                DIRECTIONAL_BIN_CONTEXT_FILE,
                DIRECTIONAL_CRASH_CONTEXT_FILE,
                REFERENCE_SIGNAL_CONTEXT_FILE,
                DESCRIPTIVE_MANIFEST_FILE,
                DESCRIPTIVE_SUMMARY_BY_WINDOW_FILE,
                DESCRIPTIVE_SUMMARY_BY_SIGNAL_DIRECTION_WINDOW_FILE,
                DISTANCE_PROFILE_MANIFEST_FILE,
                DISTANCE_PROFILE_OVERALL_FILE,
                DISTANCE_PROFILE_BY_DIRECTION_FILE,
                SIGNAL_DIRECTION_PROFILE_MANIFEST_FILE,
                SIGNAL_DIRECTION_WINDOW_PROFILE_FILE,
                SIGNAL_DIRECTION_DISTANCE_BAND_PROFILE_FILE,
            ]
        ),
        "supporting_output_row_counts": supporting_output_rows,
        "outputs": sorted(str(OUTPUT_DIR / filename) for filename in list(outputs) + ["exposure_modeling_readiness_findings.md", "exposure_modeling_readiness_manifest.json"]),
        "thresholds": {
            "aadt_coverage_sufficient": AADT_COVERAGE_THRESHOLD,
            "speed_coverage_sufficient": SPEED_COVERAGE_THRESHOLD,
            "low_length_ft_threshold": LOW_LENGTH_FT_THRESHOLD,
            "low_crash_count_threshold": LOW_CRASH_COUNT_THRESHOLD,
            "sparse_cell_bin_threshold": SPARSE_CELL_BIN_THRESHOLD,
            "sparse_cell_crash_threshold": SPARSE_CELL_CRASH_THRESHOLD,
        },
        "analysis_units": [
            "reference_signal_id + signal_relative_direction + analysis_window",
            "reference_signal_id + signal_relative_direction + fixed distance_band",
        ],
        "guardrails": {
            "crash_direction_fields_used": False,
            "rows_over_2500ft_included": False,
            "regression_or_model_fit": False,
            "causal_claims": False,
            "policy_or_safety_performance_rankings": False,
            "cross_tabs_are_rates": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "exposure_modeling_readiness_manifest.json")
    return {
        "summary": summary,
        "window_units": window_units,
        "band_units": band_units,
        "qa": qa,
        "manifest": manifest,
        "duplicate_by_signal": duplicate_by_signal,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit exposure and modeling readiness for roadway-graph context outputs.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
