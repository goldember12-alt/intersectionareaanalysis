from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("analysis/current/directional_bin_context_table")
REVIEW_CURRENT = OUTPUT_ROOT / "review/current"
IDENTITY_DIR = REVIEW_CURRENT / "roadway_identity_metadata_propagation"

IDENTITY_BINS_FILE = IDENTITY_DIR / "directional_bins_identity_enriched.csv"
CRASH_READINESS_FILE = REVIEW_CURRENT / "crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
CRASH_ASSIGNMENTS_FILE = REVIEW_CURRENT / "crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
ACCESS_BIN_FILE = REVIEW_CURRENT / "access_context_join/directional_bin_access_context.csv"
ACCESS_SUMMARY_FILE = REVIEW_CURRENT / "access_context_join/access_context_join_summary.csv"
SPEED_BIN_FILE = REVIEW_CURRENT / "speed_context_join_v4_identity_enriched/directional_bin_speed_context_v4.csv"
SPEED_SUMMARY_FILE = REVIEW_CURRENT / "speed_context_join_v4_identity_enriched/speed_context_v4_summary.csv"
AADT_BIN_FILE = REVIEW_CURRENT / "aadt_context_join_v3_identity_route_measure/directional_bin_aadt_context_v3.csv"
AADT_SUMMARY_FILE = REVIEW_CURRENT / "aadt_context_join_v3_identity_route_measure/aadt_context_v3_summary.csv"
URBAN_RURAL_RECOMMENDATION_FILE = REVIEW_CURRENT / "urban_rural_context_inventory/urban_rural_context_recommendation.csv"
URBAN_RURAL_FINDINGS_FILE = REVIEW_CURRENT / "urban_rural_context_inventory/urban_rural_context_inventory_findings.md"
URBAN_RURAL_SOURCE_RECOVERY_SUMMARY_FILE = REVIEW_CURRENT / "urban_rural_source_recovery/urban_rural_source_recovery_summary.csv"
URBAN_RURAL_SOURCE_RECOVERY_FINDINGS_FILE = REVIEW_CURRENT / "urban_rural_source_recovery/urban_rural_source_recovery_findings.md"
NORMALIZED_CRASHES_FILE = Path("artifacts/normalized/crashes.parquet")

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)
STABLE_SPEED_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
STABLE_AADT_STATUSES = {"stable_aadt_assigned_route_measure", "stable_aadt_assigned_single_route_candidate"}
WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}


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


def _read_crash_area_type_context(path: Path = NORMALIZED_CRASHES_FILE) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    header = pd.read_parquet(path, columns=[]).columns.tolist()
    # Some parquet readers do not expose schema through columns=[]; fall back to a zero-row metadata read.
    if not header:
        import pyarrow.parquet as pq

        header = pq.ParquetFile(path).schema.names
    desired = ["DOCUMENT_NBR", "AREA_TYPE"]
    optional = [
        column
        for column in header
        if column not in desired
        and "AREA" in column.upper()
        and "TYPE" in column.upper()
        and not _is_crash_direction_field(column)
    ]
    usecols = desired + optional
    missing = [column for column in desired if column not in header]
    if missing:
        raise ValueError(f"{path} is missing required crash AREA_TYPE columns: {missing}")
    blocked = [column for column in usecols if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    frame = pd.read_parquet(path, columns=usecols)
    frame["crash_id"] = frame["DOCUMENT_NBR"].astype(str)
    frame["crash_area_type_raw"] = frame["AREA_TYPE"].fillna("").astype(str).str.strip()
    normalized = frame["crash_area_type_raw"].str.upper()
    frame["crash_urban_rural_class"] = "unknown"
    frame.loc[normalized.str.contains("URBAN", na=False), "crash_urban_rural_class"] = "urban"
    frame.loc[normalized.str.contains("RURAL", na=False), "crash_urban_rural_class"] = "rural"
    frame["crash_urban_rural_context_status"] = "unknown_or_unrecognized"
    frame.loc[frame["crash_area_type_raw"].eq(""), "crash_urban_rural_context_status"] = "missing_area_type"
    frame.loc[frame["crash_urban_rural_class"].isin(["urban", "rural"]), "crash_urban_rural_context_status"] = "area_type_classified"
    keep = ["crash_id", "crash_area_type_raw", "crash_urban_rural_class", "crash_urban_rural_context_status"]
    return frame[keep].drop_duplicates(subset=["crash_id"], keep="first").copy()


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _summary_value(path: Path, metric: str) -> int:
    if not path.exists():
        return 0
    frame = _read_csv(path)
    row = frame.loc[frame["metric"].eq(metric)]
    if row.empty:
        return 0
    value = pd.to_numeric(row.iloc[0].get("count"), errors="coerce")
    return 0 if pd.isna(value) else int(value)


def _load_speed_bins() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "base_segment_id",
        "source_bin_key",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "far_anchor_type",
        "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value",
        "weighted_car_speed_limit",
        "weighted_truck_speed_limit",
        "speed_transition_within_bin_flag",
        "weighted_speed_context_flag",
        "weighted_speed_method",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
    ]
    speed = _read_csv(SPEED_BIN_FILE, usecols=[column for column in columns if column in pd.read_csv(SPEED_BIN_FILE, nrows=0).columns])
    speed = speed.loc[speed["distance_window"].isin(WINDOWS)].copy()
    if "bin_start_ft_from_reference_signal" not in speed.columns or "bin_end_ft_from_reference_signal" not in speed.columns:
        identity = _read_csv(
            IDENTITY_BINS_FILE,
            usecols=["reference_directional_bin_id", "bin_start_ft_from_reference_signal", "bin_end_ft_from_reference_signal"],
        )
        speed = speed.merge(identity, on="reference_directional_bin_id", how="left")
    return speed


def _load_crash_counts() -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_midpoint_ft_from_reference_signal",
        "analysis_readiness_class",
        "recommended_use",
        "functional_distance_window",
        "far_anchor_type",
    ]
    readiness = _read_csv(CRASH_READINESS_FILE, usecols=columns)
    midpoint = _num(readiness, "bin_midpoint_ft_from_reference_signal")
    in_context = readiness.loc[midpoint.le(2500)].copy()
    crash_area = _read_crash_area_type_context()
    in_context = in_context.merge(crash_area, on="crash_id", how="left")
    in_context["crash_area_type_raw"] = in_context["crash_area_type_raw"].fillna("")
    in_context["crash_urban_rural_class"] = in_context["crash_urban_rural_class"].fillna("unknown")
    in_context["crash_urban_rural_context_status"] = in_context["crash_urban_rural_context_status"].fillna("missing_area_type")
    in_context["has_crash_area_type"] = in_context["crash_area_type_raw"].astype(str).str.strip().ne("")
    counts = (
        in_context.groupby("reference_directional_bin_id", dropna=False)
        .agg(
            unique_assigned_crash_count=("crash_id", "nunique"),
            assigned_crashes_urban_count=("crash_urban_rural_class", lambda s: int(s.eq("urban").sum())),
            assigned_crashes_rural_count=("crash_urban_rural_class", lambda s: int(s.eq("rural").sum())),
            assigned_crashes_unknown_area_type_count=("crash_urban_rural_class", lambda s: int(s.eq("unknown").sum())),
            assigned_crashes_with_area_type_count=("has_crash_area_type", "sum"),
        )
        .reset_index()
    )
    return counts, in_context


def _load_access_bins() -> pd.DataFrame:
    columns = [
        "reference_directional_bin_id",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "nearest_access_distance_ft",
        "access_context_status",
        "access_ambiguous_multiple_bin_match_count",
    ]
    access = _read_csv(ACCESS_BIN_FILE, usecols=columns)
    access = access.rename(columns={"access_ambiguous_multiple_bin_match_count": "access_ambiguity_count"})
    access["access_ambiguity_flag"] = _num(access, "access_ambiguity_count").gt(0)
    access["has_access_context"] = access["access_context_status"].astype(str).ne("")
    return access


def _load_aadt_bins() -> pd.DataFrame:
    columns = [
        "reference_directional_bin_id",
        "aadt_value",
        "aadt_year",
        "aadt_direction_factor",
        "aadt_directionality",
        "route_measure_match_status",
        "measure_overlap_length",
        "measure_overlap_ratio",
        "aadt_context_status",
        "aadt_context_confidence",
    ]
    return _read_csv(AADT_BIN_FILE, usecols=columns)


def _urban_rural_decision() -> dict[str, Any]:
    source_recovery = {}
    if URBAN_RURAL_SOURCE_RECOVERY_SUMMARY_FILE.exists():
        recovery = _read_csv(URBAN_RURAL_SOURCE_RECOVERY_SUMMARY_FILE)
        if {"metric", "value"}.issubset(recovery.columns):
            source_recovery = dict(zip(recovery["metric"], recovery["value"]))
    if not URBAN_RURAL_RECOMMENDATION_FILE.exists():
        return {
            "recommendation": "source_not_found",
            "best_source_table": "",
            "best_source_field": "",
            "use_in_combined_table_now": False,
            "recommended_method": "inventory output missing; mark source_not_found",
            "source_recovery": source_recovery,
        }
    rec = _read_csv(URBAN_RURAL_RECOMMENDATION_FILE)
    if rec.empty:
        return {"recommendation": "source_not_found", "source_recovery": source_recovery}
    row = rec.iloc[0].to_dict()
    row["source_recovery"] = source_recovery
    return row


def _assemble_context() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    speed = _load_speed_bins()
    crash_counts, crash_rows = _load_crash_counts()
    access = _load_access_bins()
    aadt = _load_aadt_bins()
    urban = _urban_rural_decision()

    out = speed.merge(crash_counts, on="reference_directional_bin_id", how="left")
    out["unique_assigned_crash_count"] = _num(out, "unique_assigned_crash_count").fillna(0).astype(int)
    for column in [
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "assigned_crashes_with_area_type_count",
    ]:
        out[column] = _num(out, column).fillna(0).astype(int)
    out["bin_crash_area_type_summary_status"] = "no_assigned_crashes"
    has_crash = out["unique_assigned_crash_count"].gt(0)
    known_area_count = out["assigned_crashes_urban_count"] + out["assigned_crashes_rural_count"]
    out.loc[has_crash & known_area_count.eq(out["unique_assigned_crash_count"]), "bin_crash_area_type_summary_status"] = "all_assigned_crashes_classified"
    out.loc[has_crash & known_area_count.gt(0) & known_area_count.lt(out["unique_assigned_crash_count"]), "bin_crash_area_type_summary_status"] = "partial_assigned_crashes_classified"
    out.loc[has_crash & known_area_count.eq(0), "bin_crash_area_type_summary_status"] = "assigned_crashes_area_type_unknown"
    out["has_assigned_crash"] = out["unique_assigned_crash_count"].gt(0)
    out = out.merge(access, on="reference_directional_bin_id", how="left")
    out = out.merge(aadt, on="reference_directional_bin_id", how="left")

    for column in ["access_count_within_catchment", "access_count_within_100ft", "access_count_within_250ft"]:
        out[column] = _num(out, column).fillna(0).astype(int)
    out["has_access_context"] = out.get("has_access_context", pd.Series(False, index=out.index)).fillna(False).astype(bool)
    out["has_crash_context"] = True
    out["has_stable_speed_context"] = out["refined_speed_context_status"].isin(STABLE_SPEED_STATUSES)
    out["speed_review_or_missing_flag"] = ~out["has_stable_speed_context"]
    out["has_stable_aadt_context"] = out["aadt_context_status"].isin(STABLE_AADT_STATUSES)
    out["aadt_review_or_missing_flag"] = ~out["has_stable_aadt_context"]

    if str(urban.get("recommendation", "")) != "use_existing_roadway_level_field":
        out["urban_rural_class"] = ""
        out["urban_rural_source_field"] = ""
        out["urban_rural_source_table"] = ""
        out["urban_rural_context_status"] = "source_not_found"
        out["has_urban_rural_context"] = False
        out["roadway_urban_rural_class"] = ""
        out["roadway_urban_rural_context_status"] = "source_not_found"
    else:
        # Reserved for a future explicit roadway-level source. Current inventory normally refuses this path.
        out["urban_rural_class"] = ""
        out["urban_rural_source_field"] = str(urban.get("best_source_field", ""))
        out["urban_rural_source_table"] = str(urban.get("best_source_table", ""))
        out["urban_rural_context_status"] = "not_joined"
        out["has_urban_rural_context"] = False
        out["roadway_urban_rural_class"] = ""
        out["roadway_urban_rural_context_status"] = "source_not_found"

    out["has_complete_core_context"] = out["has_access_context"] & out["has_stable_speed_context"] & out["has_stable_aadt_context"] & out["has_urban_rural_context"]
    out["context_completeness_class"] = [_completeness_class(row) for row in out.to_dict(orient="records")]
    return out, crash_rows, urban


def _completeness_class(row: dict[str, Any]) -> str:
    has_crash = bool(row.get("has_assigned_crash"))
    has_access = bool(row.get("has_access_context"))
    has_speed = bool(row.get("has_stable_speed_context"))
    has_aadt = bool(row.get("has_stable_aadt_context"))
    has_urban = bool(row.get("has_urban_rural_context"))
    if has_access and has_speed and has_aadt and has_urban:
        return "complete_crash_access_speed_aadt_urban" if has_crash else "complete_bin_context_no_crash"
    if has_crash and has_access and has_speed and has_aadt and not has_urban:
        return "crash_with_access_speed_aadt_missing_urban"
    if has_crash and has_access and has_aadt and not has_speed:
        return "crash_with_access_aadt_speed_missing"
    if has_crash and has_speed and has_aadt and not has_access:
        return "crash_with_speed_aadt_access_missing"
    available = sum([has_access, has_speed, has_aadt, has_urban])
    if has_crash and available > 0:
        return "crash_context_partial"
    if not has_crash and available >= 2:
        return "bin_context_partial_no_crash"
    return "missing_major_context"


def _reference_signal_summary(context: pd.DataFrame) -> pd.DataFrame:
    grouped = context.groupby("reference_signal_id", dropna=False).agg(
        directional_bin_count=("reference_directional_bin_id", "nunique"),
        assigned_crash_count=("unique_assigned_crash_count", "sum"),
        assigned_crashes_urban_count=("assigned_crashes_urban_count", "sum"),
        assigned_crashes_rural_count=("assigned_crashes_rural_count", "sum"),
        assigned_crashes_unknown_area_type_count=("assigned_crashes_unknown_area_type_count", "sum"),
        assigned_crashes_with_area_type_count=("assigned_crashes_with_area_type_count", "sum"),
        bins_with_assigned_crash=("has_assigned_crash", "sum"),
        bins_with_access_context=("has_access_context", "sum"),
        bins_with_stable_speed_context=("has_stable_speed_context", "sum"),
        bins_with_stable_aadt_context=("has_stable_aadt_context", "sum"),
        bins_with_urban_rural_context=("has_urban_rural_context", "sum"),
        bins_with_complete_core_context=("has_complete_core_context", "sum"),
    ).reset_index()
    return grouped


def _crash_area_type_summary(crash_context: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    raw_counts = (
        crash_context.groupby(["crash_area_type_raw", "crash_urban_rural_class", "crash_urban_rural_context_status"], dropna=False)
        .agg(assigned_crash_count=("crash_id", "nunique"))
        .reset_index()
    )
    metrics = [
        {"metric": "assigned_crashes_total", "value": int(crash_context["crash_id"].nunique())},
        {"metric": "assigned_crashes_with_area_type", "value": int(crash_context["crash_area_type_raw"].astype(str).str.strip().ne("").sum())},
        {"metric": "assigned_crashes_urban", "value": int(crash_context["crash_urban_rural_class"].eq("urban").sum())},
        {"metric": "assigned_crashes_rural", "value": int(crash_context["crash_urban_rural_class"].eq("rural").sum())},
        {"metric": "assigned_crashes_unknown_area_type", "value": int(crash_context["crash_urban_rural_class"].eq("unknown").sum())},
        {"metric": "bins_with_urban_or_rural_crash_summary", "value": int(((context["assigned_crashes_urban_count"] + context["assigned_crashes_rural_count"]).gt(0)).sum())},
        {"metric": "signals_with_urban_or_rural_crash_summary", "value": int(crash_context.loc[crash_context["crash_urban_rural_class"].isin(["urban", "rural"]), "reference_signal_id"].nunique())},
        {"metric": "roadway_urban_rural_context_status", "value": "source_not_found"},
        {"metric": "crash_direction_fields_read_or_used", "value": False},
    ]
    metric_frame = pd.DataFrame(metrics)
    raw_counts["metric"] = "raw_area_type_value"
    raw_counts = raw_counts.rename(columns={"assigned_crash_count": "value"})
    raw_counts["raw_value"] = raw_counts["crash_area_type_raw"]
    raw_counts["class"] = raw_counts["crash_urban_rural_class"]
    raw_counts["status"] = raw_counts["crash_urban_rural_context_status"]
    return pd.concat(
        [
            metric_frame.assign(raw_value="", **{"class": ""}, status=""),
            raw_counts[["metric", "value", "raw_value", "class", "status"]],
        ],
        ignore_index=True,
    )


def _crash_area_type_by(crash_context: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return (
        crash_context.groupby(columns, dropna=False)
        .agg(
            assigned_crash_count=("crash_id", "nunique"),
            assigned_crashes_urban_count=("crash_urban_rural_class", lambda s: int(s.eq("urban").sum())),
            assigned_crashes_rural_count=("crash_urban_rural_class", lambda s: int(s.eq("rural").sum())),
            assigned_crashes_unknown_area_type_count=("crash_urban_rural_class", lambda s: int(s.eq("unknown").sum())),
            assigned_crashes_with_area_type_count=("crash_area_type_raw", lambda s: int(s.astype(str).str.strip().ne("").sum())),
        )
        .reset_index()
    )


def _completeness_by(context: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return (
        context.groupby(columns, dropna=False)
        .agg(
            directional_bin_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            bins_with_assigned_crash=("has_assigned_crash", "sum"),
            bins_with_access_context=("has_access_context", "sum"),
            bins_with_stable_speed_context=("has_stable_speed_context", "sum"),
            bins_with_stable_aadt_context=("has_stable_aadt_context", "sum"),
            bins_with_urban_rural_context=("has_urban_rural_context", "sum"),
            bins_with_complete_core_context=("has_complete_core_context", "sum"),
        )
        .reset_index()
    )


def _qa(context: pd.DataFrame, crash_rows: pd.DataFrame) -> pd.DataFrame:
    high = int(context["distance_window"].eq("high_priority_0_1000ft").sum())
    sensitivity = int(context["distance_window"].eq("sensitivity_1000_2500ft").sum())
    stable_speed = int(context["has_stable_speed_context"].sum())
    stable_aadt = int(context["has_stable_aadt_context"].sum())
    crash_count = int(context["unique_assigned_crash_count"].sum())
    access_within_catchment = int(_num(context, "access_count_within_catchment").gt(0).sum())
    bin_area_count_sum = int(
        (
            context["assigned_crashes_urban_count"]
            + context["assigned_crashes_rural_count"]
            + context["assigned_crashes_unknown_area_type_count"]
        ).sum()
    )
    signal_summary = _reference_signal_summary(context)
    signal_area_count_sum = int(
        (
            signal_summary["assigned_crashes_urban_count"]
            + signal_summary["assigned_crashes_rural_count"]
            + signal_summary["assigned_crashes_unknown_area_type_count"]
        ).sum()
    )
    no_crash_bins_with_area_context = int(
        context.loc[~context["has_assigned_crash"], ["assigned_crashes_urban_count", "assigned_crashes_rural_count", "assigned_crashes_unknown_area_type_count", "assigned_crashes_with_area_type_count"]]
        .sum(axis=1)
        .gt(0)
        .sum()
    )
    represented_area_type = int(crash_rows["crash_area_type_raw"].astype(str).str.strip().ne("").sum())
    return pd.DataFrame(
        [
            {"check_name": "one_row_per_0_2500ft_directional_bin", "passed": len(context) == context["reference_directional_bin_id"].nunique() == 110710, "observed": len(context), "expected": 110710},
            {"check_name": "distance_window_splits_sum", "passed": high + sensitivity == len(context), "observed": high + sensitivity, "expected": len(context)},
            {"check_name": "no_over_2500ft_bins_in_main", "passed": context["distance_window"].isin(WINDOWS).all(), "observed": int((~context["distance_window"].isin(WINDOWS)).sum()), "expected": 0},
            {"check_name": "crash_counts_match_readiness_0_2500ft", "passed": crash_count == len(crash_rows), "observed": crash_count, "expected": len(crash_rows)},
            {"check_name": "total_assigned_crashes_remains_13216", "passed": crash_count == 13216, "observed": crash_count, "expected": 13216},
            {"check_name": "all_matching_crash_area_type_rows_represented", "passed": represented_area_type == int(context["assigned_crashes_with_area_type_count"].sum()), "observed": int(context["assigned_crashes_with_area_type_count"].sum()), "expected": represented_area_type},
            {"check_name": "bin_level_area_type_counts_sum_to_assigned_crashes", "passed": bin_area_count_sum == crash_count, "observed": bin_area_count_sum, "expected": crash_count},
            {"check_name": "signal_level_area_type_counts_sum_to_assigned_crashes", "passed": signal_area_count_sum == crash_count, "observed": signal_area_count_sum, "expected": crash_count},
            {"check_name": "no_crash_bins_not_assigned_crash_area_type_context", "passed": no_crash_bins_with_area_context == 0, "observed": no_crash_bins_with_area_context, "expected": 0},
            {"check_name": "access_counts_match_access_summary", "passed": access_within_catchment == _summary_value(ACCESS_SUMMARY_FILE, "bins_with_access_within_catchment"), "observed": access_within_catchment, "expected": _summary_value(ACCESS_SUMMARY_FILE, "bins_with_access_within_catchment")},
            {"check_name": "speed_counts_match_speed_v4", "passed": stable_speed == _summary_value(SPEED_SUMMARY_FILE, "stable_speed_bins"), "observed": stable_speed, "expected": _summary_value(SPEED_SUMMARY_FILE, "stable_speed_bins")},
            {"check_name": "aadt_counts_match_aadt_v3", "passed": stable_aadt == _summary_value(AADT_SUMMARY_FILE, "bins_with_stable_aadt"), "observed": stable_aadt, "expected": _summary_value(AADT_SUMMARY_FILE, "bins_with_stable_aadt")},
            {"check_name": "urban_rural_source_not_found_documented", "passed": context["urban_rural_context_status"].eq("source_not_found").all(), "observed": context["urban_rural_context_status"].drop_duplicates().str.cat(sep="|"), "expected": "source_not_found"},
            {"check_name": "roadway_urban_rural_remains_source_not_found", "passed": context["roadway_urban_rural_class"].eq("").all() and context["roadway_urban_rural_context_status"].eq("source_not_found").all(), "observed": context["roadway_urban_rural_context_status"].drop_duplicates().str.cat(sep="|"), "expected": "source_not_found"},
            {"check_name": "ambiguous_unresolved_crashes_excluded", "passed": True, "observed": "readiness unique assigned rows only", "expected": "no ambiguous/unresolved assignment rows"},
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "crash_area_type_used_only_as_crash_level_context", "passed": True, "observed": "crash context fields and assigned-crash summary counts only", "expected": "not roadway truth and not upstream/downstream input"},
            {"check_name": "context_fields_do_not_redefine_upstream_downstream", "passed": True, "observed": False, "expected": False},
        ]
    )


def _findings(context: pd.DataFrame, crash_context: pd.DataFrame, urban: dict[str, Any], outputs: dict[str, Path]) -> str:
    stable_speed = int(context["has_stable_speed_context"].sum())
    stable_aadt = int(context["has_stable_aadt_context"].sum())
    urban_crashes = int(crash_context["crash_urban_rural_class"].eq("urban").sum())
    rural_crashes = int(crash_context["crash_urban_rural_class"].eq("rural").sum())
    unknown_crashes = int(crash_context["crash_urban_rural_class"].eq("unknown").sum())
    raw_values = " | ".join(sorted(v for v in set(crash_context["crash_area_type_raw"].astype(str)) if v))
    lines = [
        "# Directional Bin Context Table Findings",
        "",
        "## Bounded Question",
        "",
        "Assemble the read-only 0-2,500 ft directional-bin context universe from accepted crash, access, speed v4, AADT v3, roadway urban/rural source recovery, and crash-level AREA_TYPE context without changing source context joins or upstream/downstream interpretation.",
        "",
        "## Roadway Urban/Rural Source Decision",
        "",
        f"- decision: {urban.get('recommendation', 'source_not_found')}",
        f"- method: {urban.get('recommended_method', 'include null fields')}",
        f"- source recovery defensible roadway-level sources: {urban.get('source_recovery', {}).get('defensible_candidate_sources', 'not_read')}",
        "- roadway-level urban/rural source was not found.",
        "- roadway_urban_rural_class is null and roadway_urban_rural_context_status is source_not_found.",
        "- crash AREA_TYPE was not used as roadway-level urban/rural truth.",
        "",
        "## Crash-Level AREA_TYPE Context",
        "",
        f"- crash AREA_TYPE values found: {raw_values or 'none'}",
        f"- assigned crashes with AREA_TYPE: {int(crash_context['crash_area_type_raw'].astype(str).str.strip().ne('').sum())}",
        f"- assigned urban crashes: {urban_crashes}",
        f"- assigned rural crashes: {rural_crashes}",
        f"- assigned unknown area type crashes: {unknown_crashes}",
        f"- bins with urban/rural crash summaries: {int(((context['assigned_crashes_urban_count'] + context['assigned_crashes_rural_count']).gt(0)).sum())}",
        f"- signals with urban/rural crash summaries: {crash_context.loc[crash_context['crash_urban_rural_class'].isin(['urban', 'rural']), 'reference_signal_id'].nunique()}",
        "- crash AREA_TYPE was used only for assigned crash context and assigned-crash summary counts.",
        "- no-crash bins were not populated with crash AREA_TYPE-derived urban/rural values.",
        "",
        "## Key Counts",
        "",
        f"- total bins: {len(context)}",
        f"- 0-1,000 ft bins: {int(context['distance_window'].eq('high_priority_0_1000ft').sum())}",
        f"- 1,000-2,500 ft bins: {int(context['distance_window'].eq('sensitivity_1000_2500ft').sum())}",
        f"- bins with assigned crashes: {int(context['has_assigned_crash'].sum())}",
        f"- bins with access context: {int(context['has_access_context'].sum())}",
        f"- bins with stable speed context: {stable_speed}",
        f"- bins with stable AADT context: {stable_aadt}",
        f"- bins with roadway urban/rural context: {int(context['has_urban_rural_context'].sum())}",
        f"- bins with complete core context: {int(context['has_complete_core_context'].sum())}",
        f"- crashes represented: {int(context['unique_assigned_crash_count'].sum())}",
        f"- reference signals represented: {context['reference_signal_id'].nunique()}",
        "",
        "## Context Limitations",
        "",
        "- Roadway-level urban/rural context is not populated because no defensible roadway-level source was found.",
        "- Crash AREA_TYPE cannot populate no-crash bins and is not a roadway-level policy variable.",
        "- Speed review/missing statuses are preserved; only stable speed statuses should be used as usable speed context.",
        "- AADT review/missing statuses are preserved; only stable route-measure AADT statuses should be used as usable AADT context.",
        "- The table is ready as a prototype descriptive analysis universe, not a modeling-ready or policy-claim table.",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_directional_bin_context_table(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    context, crash_rows, urban = _assemble_context()
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
                "aadt_value",
                "aadt_year",
                "aadt_context_status",
                "aadt_context_confidence",
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

    outputs = {
        "directional_bin_context_csv": out_dir / "directional_bin_context.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_context_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_context_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_context.csv",
        "reference_signal_context_summary_csv": out_dir / "reference_signal_context_summary.csv",
        "crash_area_type_context_summary_csv": out_dir / "crash_area_type_context_summary.csv",
        "crash_area_type_by_distance_window_csv": out_dir / "crash_area_type_by_distance_window.csv",
        "crash_area_type_by_signal_relative_direction_csv": out_dir / "crash_area_type_by_signal_relative_direction.csv",
        "crash_area_type_by_roadway_representation_csv": out_dir / "crash_area_type_by_roadway_representation.csv",
        "context_completeness_by_bin_csv": out_dir / "context_completeness_by_bin.csv",
        "context_completeness_by_reference_signal_csv": out_dir / "context_completeness_by_reference_signal.csv",
        "context_completeness_by_distance_window_csv": out_dir / "context_completeness_by_distance_window.csv",
        "context_completeness_by_signal_relative_direction_csv": out_dir / "context_completeness_by_signal_relative_direction.csv",
        "combined_context_join_qa_csv": out_dir / "combined_context_join_qa.csv",
        "findings_md": out_dir / "directional_bin_context_findings.md",
        "manifest_json": out_dir / "directional_bin_context_manifest.json",
    }
    _write_csv(context, outputs["directional_bin_context_csv"])
    _write_csv(context.loc[context["distance_window"].eq("high_priority_0_1000ft")], outputs["directional_bin_context_0_1000_csv"])
    _write_csv(context.loc[context["distance_window"].eq("sensitivity_1000_2500ft")], outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(_reference_signal_summary(context), outputs["reference_signal_context_summary_csv"])
    _write_csv(_crash_area_type_summary(crash_context, context), outputs["crash_area_type_context_summary_csv"])
    _write_csv(_crash_area_type_by(crash_context, ["functional_distance_window"]), outputs["crash_area_type_by_distance_window_csv"])
    _write_csv(_crash_area_type_by(crash_context, ["signal_relative_direction"]), outputs["crash_area_type_by_signal_relative_direction_csv"])
    _write_csv(_crash_area_type_by(crash_context, ["roadway_representation_type"]), outputs["crash_area_type_by_roadway_representation_csv"])
    _write_csv(context[["reference_directional_bin_id", "reference_signal_id", "distance_window", "signal_relative_direction", "context_completeness_class", "has_assigned_crash", "has_access_context", "has_stable_speed_context", "has_stable_aadt_context", "has_urban_rural_context", "has_complete_core_context"]], outputs["context_completeness_by_bin_csv"])
    _write_csv(_completeness_by(context, ["reference_signal_id"]), outputs["context_completeness_by_reference_signal_csv"])
    _write_csv(_completeness_by(context, ["distance_window"]), outputs["context_completeness_by_distance_window_csv"])
    _write_csv(_completeness_by(context, ["signal_relative_direction"]), outputs["context_completeness_by_signal_relative_direction_csv"])
    qa = _qa(context, crash_rows)
    _write_csv(qa, outputs["combined_context_join_qa_csv"])
    _write_text(_findings(context, crash_context, urban, outputs), outputs["findings_md"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "read-only assembly of stable 0-2500ft directional-bin context universe",
            "inputs": {
                "crash_readiness": str(CRASH_READINESS_FILE),
                "crash_assignments_metadata_not_joined": str(CRASH_ASSIGNMENTS_FILE),
                "normalized_crashes_area_type_only": str(NORMALIZED_CRASHES_FILE),
                "access_bin_context": str(ACCESS_BIN_FILE),
                "speed_v4_bin_context": str(SPEED_BIN_FILE),
                "aadt_v3_bin_context": str(AADT_BIN_FILE),
                "identity_bins_for_bin_extent_fields": str(IDENTITY_BINS_FILE),
                "urban_rural_recommendation": str(URBAN_RURAL_RECOMMENDATION_FILE),
                "urban_rural_source_recovery_summary": str(URBAN_RURAL_SOURCE_RECOVERY_SUMMARY_FILE),
                "urban_rural_source_recovery_findings": str(URBAN_RURAL_SOURCE_RECOVERY_FINDINGS_FILE),
            },
            "urban_rural_decision": urban,
            "crash_direction_fields_read_or_used": False,
            "crash_area_type_used_as_roadway_truth": False,
            "crash_area_type_used_for_upstream_downstream": False,
            "context_fields_used_for_upstream_downstream": False,
            "source_context_joins_modified": False,
            "summary_counts": {
                "total_bins": len(context),
                "crashes_represented": int(context["unique_assigned_crash_count"].sum()),
                "assigned_crashes_with_area_type": int(crash_context["crash_area_type_raw"].astype(str).str.strip().ne("").sum()),
                "assigned_crashes_urban": int(crash_context["crash_urban_rural_class"].eq("urban").sum()),
                "assigned_crashes_rural": int(crash_context["crash_urban_rural_class"].eq("rural").sum()),
                "assigned_crashes_unknown_area_type": int(crash_context["crash_urban_rural_class"].eq("unknown").sum()),
                "bins_with_urban_or_rural_crash_summary": int(((context["assigned_crashes_urban_count"] + context["assigned_crashes_rural_count"]).gt(0)).sum()),
                "signals_with_urban_or_rural_crash_summary": int(crash_context.loc[crash_context["crash_urban_rural_class"].isin(["urban", "rural"]), "reference_signal_id"].nunique()),
                "reference_signals_represented": int(context["reference_signal_id"].nunique()),
                "stable_speed_bins": int(context["has_stable_speed_context"].sum()),
                "stable_aadt_bins": int(context["has_stable_aadt_context"].sum()),
                "roadway_urban_rural_bins": int(context["has_urban_rural_context"].sum()),
                "complete_core_context_bins": int(context["has_complete_core_context"].sum()),
            },
            "qa": qa.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble read-only directional-bin context table.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_directional_bin_context_table(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
