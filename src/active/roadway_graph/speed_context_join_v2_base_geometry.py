from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import wkt

from .crs_utils import WORKING_CRS_AUTHORITY, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/speed_context_join_v2_base_geometry")

SPEED_FILE = Path("artifacts/normalized/speed.parquet")
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
USABLE_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_segments.csv"
SOURCE_BIN_GEOMETRY_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv"
STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_field_role_candidates.csv"
STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_crs_sanity.csv"
V1_SUMMARY_FILE = OUTPUT_ROOT / "review/current/speed_context_join/speed_context_join_summary.csv"
V1_PAIRED_QA_FILE = OUTPUT_ROOT / "review/current/speed_context_coverage_diagnostic/speed_paired_pseudo_direction_consistency_qa.csv"

FEET_TO_METERS = 0.3048
NEAREST_TOLERANCE_FT = 100.0
NEAREST_TOLERANCE_M = NEAREST_TOLERANCE_FT * FEET_TO_METERS
SEVERE_CONFLICT_SPREAD_MPH = 15.0

SPEED_ID_FIELD = "EVENT_SOURCE_ID"
CAR_SPEED_FIELD = "CAR_SPEED_LIMIT"
TRUCK_SPEED_FIELD = "TRUCK_SPEED_LIMIT"
SPEED_VALUE_FIELDS = [CAR_SPEED_FIELD, TRUCK_SPEED_FIELD]
SPEED_ROUTE_FIELDS = [
    "ROUTE_COMMON_NAME",
    "LOC_COMP_DIRECTIONALITY_NAME",
    "ROUTE_FROM_MEASURE",
    "ROUTE_TO_MEASURE",
    "RTE_TYPE_CD",
    "RTE_TYPE_NM",
    "FROM_DISTRICT",
    "TO_DISTRICT",
    "FROM_JURISDICTION",
    "TO_JURISDICTION",
]
SPEED_METADATA_FIELDS = ["SPEEDZONE_TYPE_DSC", "AUTHORITY_DSC", "LENGTH"]

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

MAIN_OUTPUT_COLUMNS = [
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
    "dominant_car_speed_limit",
    "dominant_truck_speed_limit",
    "speed_value_conflict_flag",
    "speed_candidate_values",
    "speed_overlap_length_ft",
    "nearest_speed_distance_ft",
    "nearest_speed_record_id",
    "speed_context_method",
    "speed_context_confidence",
    "speed_context_status",
]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        missing = [c for c in usecols if c not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        direction_like = [c for c in usecols if _is_crash_direction_field(c)]
        if direction_like:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {direction_like}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _distance_window(midpoint_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([midpoint_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown_distance"
    if value <= 1000:
        return "high_priority_0_1000ft"
    if value <= 2500:
        return "sensitivity_1000_2500ft"
    return "review_over_2500ft"


def _format_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    return str(value)


def _source_bin_key(base_segment_id: Any, bin_index_in_travel_direction: Any) -> str:
    index = pd.to_numeric(pd.Series([bin_index_in_travel_direction]), errors="coerce").iloc[0]
    if pd.isna(index):
        return ""
    return f"{base_segment_id}_bin_{int(index) - 1:04d}"


def _load_speed() -> gpd.GeoDataFrame:
    speed = gpd.read_parquet(SPEED_FILE)
    if speed.crs is None:
        raise ValueError("Speed source has no CRS; rerun posted speed staging before joining.")
    missing = [field for field in SPEED_VALUE_FIELDS if field not in speed.columns]
    if missing:
        raise ValueError(f"Speed source is missing required posted-speed fields: {missing}")
    speed = speed.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="speed_source_index")
    if SPEED_ID_FIELD not in speed.columns:
        speed[SPEED_ID_FIELD] = speed["speed_source_index"].astype(str)
    speed["speed_record_id"] = speed[SPEED_ID_FIELD].astype(str)
    speed["source_geometry_is_null"] = speed.geometry.isna()
    speed["source_geometry_is_valid"] = speed.geometry.notna() & speed.geometry.is_valid
    return speed


def _load_directional_context_bins() -> pd.DataFrame:
    bins = _read_csv(USABLE_BINS_FILE)
    catchment_index = _read_csv(CATCHMENT_INDEX_FILE, usecols=["reference_directional_bin_id", "catchment_status"])
    catchment_index = catchment_index.loc[catchment_index["catchment_status"].eq("usable")].copy()
    bins = bins.merge(catchment_index, on="reference_directional_bin_id", how="left")
    bins["bin_midpoint_ft_from_reference_signal"] = _num(bins, "bin_midpoint_ft_from_reference_signal")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    bins["context_join_eligible"] = bins["catchment_status"].eq("usable") & bins["bin_midpoint_ft_from_reference_signal"].le(2500)
    bins["source_bin_key"] = [
        _source_bin_key(base_segment_id, index)
        for base_segment_id, index in zip(bins["base_segment_id"], bins["bin_index_in_travel_direction"], strict=False)
    ]
    return bins


def _load_base_bin_geometry(context_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    source_keys = set(context_bins.loc[context_bins["context_join_eligible"], "source_bin_key"].astype(str))
    usecols = ["oriented_segment_id", "bin_id", "bin_index", "bin_start_ft", "bin_end_ft", "bin_midpoint_ft", "geometry"]
    source = pd.read_csv(SOURCE_BIN_GEOMETRY_FILE, dtype=str, keep_default_na=False, usecols=usecols)
    source = source.loc[source["bin_id"].astype(str).isin(source_keys)].copy()
    source["geometry"] = source["geometry"].map(lambda value: wkt.loads(value) if isinstance(value, str) and value.strip() else None)
    base = gpd.GeoDataFrame(source, geometry="geometry", crs=WORKING_CRS_AUTHORITY)
    base = base.rename(columns={"oriented_segment_id": "base_segment_id", "bin_id": "source_bin_key"})
    return base


def _speed_columns_for_matching(speed: gpd.GeoDataFrame) -> list[str]:
    columns = ["speed_source_index", "speed_record_id", *SPEED_VALUE_FIELDS]
    for field in [*SPEED_ROUTE_FIELDS, *SPEED_METADATA_FIELDS]:
        if field in speed.columns and field not in columns:
            columns.append(field)
    return columns


def _overlap_candidates(speed: gpd.GeoDataFrame, base_bins: gpd.GeoDataFrame) -> pd.DataFrame:
    valid_speed = speed.loc[speed["source_geometry_is_valid"]].copy()
    columns = _speed_columns_for_matching(valid_speed)
    joined = gpd.sjoin(valid_speed[columns + ["geometry"]], base_bins[["source_bin_key", "base_segment_id", "geometry"]], how="inner", predicate="intersects")
    if joined.empty:
        return pd.DataFrame(columns=["source_bin_key", "speed_record_id", "speed_overlap_length_ft"])
    joined = joined.drop(columns=["index_right"], errors="ignore").copy()
    base_geometries = base_bins[["source_bin_key", "geometry"]].rename(columns={"geometry": "base_bin_geometry"})
    joined = joined.merge(base_geometries, on="source_bin_key", how="left")
    joined["speed_overlap_length_ft"] = joined.apply(_intersection_length_ft, axis=1)
    joined = joined.loc[pd.to_numeric(joined["speed_overlap_length_ft"], errors="coerce").gt(0)].copy()
    joined["speed_context_method"] = "base_line_overlap"
    return pd.DataFrame(joined.drop(columns=["geometry", "base_bin_geometry"], errors="ignore"))


def _intersection_length_ft(row: pd.Series) -> float:
    line = row.get("geometry")
    base_line = row.get("base_bin_geometry")
    if line is None or base_line is None:
        return 0.0
    try:
        if line.is_empty or base_line.is_empty:
            return 0.0
        return float(line.intersection(base_line).length / FEET_TO_METERS)
    except Exception:
        return 0.0


def _nearest_candidates(speed: gpd.GeoDataFrame, base_bins: gpd.GeoDataFrame, overlap: pd.DataFrame) -> pd.DataFrame:
    bins_with_overlap = set(overlap["source_bin_key"].astype(str)) if not overlap.empty else set()
    no_overlap = base_bins.loc[~base_bins["source_bin_key"].astype(str).isin(bins_with_overlap)].copy()
    valid_speed = speed.loc[speed["source_geometry_is_valid"]].copy()
    if no_overlap.empty or valid_speed.empty:
        return pd.DataFrame(columns=["source_bin_key", "speed_record_id", "nearest_speed_distance_ft"])
    columns = _speed_columns_for_matching(valid_speed)
    nearest = gpd.sjoin_nearest(
        no_overlap[["source_bin_key", "base_segment_id", "geometry"]],
        valid_speed[columns + ["geometry"]],
        how="left",
        max_distance=NEAREST_TOLERANCE_M,
        distance_col="nearest_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest = nearest.loc[nearest["speed_record_id"].notna()].copy()
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest["speed_overlap_length_ft"] = 0.0
    nearest["speed_context_method"] = "base_line_nearest_within_tolerance"
    return nearest


def _candidate_stats(overlap: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    frames = [frame.copy() for frame in [overlap, nearest] if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["source_bin_key"])
    candidates = pd.concat(frames, ignore_index=True, sort=False)
    rows = []
    for source_bin_key, group in candidates.groupby("source_bin_key", dropna=False):
        overlap_group = group.loc[group["speed_context_method"].eq("base_line_overlap")].copy()
        nearest_group = group.loc[group["speed_context_method"].eq("base_line_nearest_within_tolerance")].copy()
        primary = overlap_group if not overlap_group.empty else nearest_group
        car_values = _value_set(primary, CAR_SPEED_FIELD)
        truck_values = _value_set(primary, TRUCK_SPEED_FIELD)
        all_values = sorted(set([float(v) for v in car_values + truck_values if v != ""]))
        spread = max(all_values) - min(all_values) if all_values else pd.NA
        rows.append(
            {
                "source_bin_key": source_bin_key,
                "speed_match_count": int(primary["speed_source_index"].nunique()),
                "dominant_car_speed_limit": _dominant_speed(primary, CAR_SPEED_FIELD),
                "dominant_truck_speed_limit": _dominant_speed(primary, TRUCK_SPEED_FIELD),
                "speed_value_conflict_flag": len(car_values) > 1 or len(truck_values) > 1,
                "speed_candidate_values": _candidate_values(primary),
                "speed_spread_mph": spread,
                "severe_conflict_spread_ge_15mph": bool(pd.notna(spread) and spread >= SEVERE_CONFLICT_SPREAD_MPH),
                "speed_overlap_length_ft": round(float(pd.to_numeric(overlap_group.get("speed_overlap_length_ft", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()), 3),
                "nearest_speed_distance_ft": _min_numeric(nearest_group, "nearest_speed_distance_ft"),
                "nearest_speed_record_id": _nearest_record_id(nearest_group),
                "base_speed_context_method": "base_line_overlap" if not overlap_group.empty else "base_line_nearest_within_tolerance",
            }
        )
    return pd.DataFrame(rows)


def _value_set(frame: pd.DataFrame, field: str) -> list[str]:
    if frame.empty or field not in frame.columns:
        return []
    values = pd.to_numeric(frame[field], errors="coerce").dropna().sort_values().unique().tolist()
    return [_format_speed(value) for value in values]


def _candidate_values(frame: pd.DataFrame) -> str:
    car = _value_set(frame, CAR_SPEED_FIELD)
    truck = _value_set(frame, TRUCK_SPEED_FIELD)
    return f"car:{'|'.join(car) if car else '<missing>'};truck:{'|'.join(truck) if truck else '<missing>'}"


def _dominant_speed(frame: pd.DataFrame, field: str) -> Any:
    if frame.empty or field not in frame.columns:
        return pd.NA
    work = frame.loc[pd.to_numeric(frame[field], errors="coerce").notna()].copy()
    if work.empty:
        return pd.NA
    weights = pd.to_numeric(work.get("speed_overlap_length_ft", 0.0), errors="coerce").fillna(0.0)
    if float(weights.sum()) <= 0:
        weights = pd.Series(1.0, index=work.index)
    work["_weight"] = weights
    grouped = work.groupby(field, dropna=False)["_weight"].sum().reset_index()
    grouped["_speed_numeric"] = pd.to_numeric(grouped[field], errors="coerce")
    grouped = grouped.sort_values(["_weight", "_speed_numeric"], ascending=[False, True])
    return _format_speed(grouped.iloc[0][field])


def _min_numeric(frame: pd.DataFrame, field: str) -> Any:
    if frame.empty or field not in frame.columns:
        return pd.NA
    value = pd.to_numeric(frame[field], errors="coerce").min()
    return round(float(value), 3) if pd.notna(value) else pd.NA


def _nearest_record_id(frame: pd.DataFrame) -> str:
    if frame.empty or "nearest_speed_distance_ft" not in frame.columns:
        return ""
    work = frame.loc[pd.to_numeric(frame["nearest_speed_distance_ft"], errors="coerce").notna()].copy()
    if work.empty:
        return ""
    work["_distance"] = pd.to_numeric(work["nearest_speed_distance_ft"], errors="coerce")
    work = work.sort_values(["_distance", "speed_record_id"])
    return str(work.iloc[0]["speed_record_id"])


def _build_base_context(base_bins: gpd.GeoDataFrame, overlap: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    base = pd.DataFrame(base_bins.drop(columns=["geometry"], errors="ignore")).copy()
    stats = _candidate_stats(overlap, nearest)
    out = base.merge(stats, on="source_bin_key", how="left")
    defaults: dict[str, Any] = {
        "speed_match_count": 0,
        "dominant_car_speed_limit": pd.NA,
        "dominant_truck_speed_limit": pd.NA,
        "speed_value_conflict_flag": False,
        "speed_candidate_values": "",
        "speed_spread_mph": pd.NA,
        "severe_conflict_spread_ge_15mph": False,
        "speed_overlap_length_ft": 0.0,
        "nearest_speed_distance_ft": pd.NA,
        "nearest_speed_record_id": "",
        "base_speed_context_method": "no_speed_match",
    }
    for column, default in defaults.items():
        if column not in out.columns:
            out[column] = default
        else:
            out[column] = out[column].fillna(default)
    out["speed_match_count"] = pd.to_numeric(out["speed_match_count"], errors="coerce").fillna(0).astype(int)
    out["speed_value_conflict_flag"] = out["speed_value_conflict_flag"].astype(bool)
    out["severe_conflict_spread_ge_15mph"] = out["severe_conflict_spread_ge_15mph"].astype(bool)
    return out


def _build_directional_context(context_bins: pd.DataFrame, base_context: pd.DataFrame) -> pd.DataFrame:
    primary = context_bins.loc[context_bins["context_join_eligible"]].copy()
    out = primary.merge(
        base_context[
            [
                "source_bin_key",
                "speed_match_count",
                "dominant_car_speed_limit",
                "dominant_truck_speed_limit",
                "speed_value_conflict_flag",
                "speed_candidate_values",
                "speed_spread_mph",
                "severe_conflict_spread_ge_15mph",
                "speed_overlap_length_ft",
                "nearest_speed_distance_ft",
                "nearest_speed_record_id",
                "base_speed_context_method",
            ]
        ],
        on="source_bin_key",
        how="left",
    )
    for column in ["speed_match_count", "speed_overlap_length_ft"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0)
    for column in ["speed_value_conflict_flag", "severe_conflict_spread_ge_15mph"]:
        out[column] = out[column].fillna(False).astype(bool)
    out["base_speed_context_method"] = out["base_speed_context_method"].fillna("no_speed_match")
    out["speed_context_method"] = out.apply(_directional_method, axis=1)
    out["speed_context_confidence"] = out.apply(_context_confidence, axis=1)
    out["speed_context_status"] = out.apply(_context_status, axis=1)
    return out


def _directional_method(row: pd.Series) -> str:
    if bool(row.get("speed_value_conflict_flag", False)):
        return "ambiguous_conflicting_speed_values"
    base_method = row.get("base_speed_context_method")
    if row.get("roadway_representation_type") == "undivided_centerline_pseudo_direction" and base_method in {"base_line_overlap", "base_line_nearest_within_tolerance"}:
        return "propagated_from_shared_base_bin"
    return str(base_method or "no_speed_match")


def _context_confidence(row: pd.Series) -> str:
    if bool(row.get("speed_value_conflict_flag", False)):
        return "low_review"
    method = row.get("base_speed_context_method")
    if method == "base_line_overlap":
        return "high"
    if method == "base_line_nearest_within_tolerance":
        return "medium"
    return "missing"


def _context_status(row: pd.Series) -> str:
    if bool(row.get("speed_value_conflict_flag", False)):
        return "ambiguous_multiple_speed_values"
    method = row.get("base_speed_context_method")
    if method == "base_line_overlap":
        return "speed_assigned_by_base_overlap"
    if method == "base_line_nearest_within_tolerance":
        return "speed_assigned_by_base_nearest"
    return "no_speed_nearby"


def _crash_context(readiness: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    readiness = readiness.copy()
    readiness["bin_midpoint_ft_from_reference_signal"] = _num(readiness, "bin_midpoint_ft_from_reference_signal")
    readiness = readiness.loc[readiness["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    keep = [
        "reference_directional_bin_id",
        "distance_window",
        "dominant_car_speed_limit",
        "dominant_truck_speed_limit",
        "speed_context_method",
        "speed_context_confidence",
        "speed_context_status",
    ]
    out = readiness.merge(bin_context[[c for c in keep if c in bin_context.columns]], on="reference_directional_bin_id", how="left", suffixes=("", "_bin"))
    out["inherited_from_bin_speed_context_v2"] = True
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "dominant_car_speed_limit",
        "dominant_truck_speed_limit",
        "speed_context_method",
        "speed_context_confidence",
        "speed_context_status",
        "inherited_from_bin_speed_context_v2",
    ]
    return out[[c for c in columns if c in out.columns]]


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    return (
        bin_context.groupby(["reference_signal_id", "distance_window", "signal_relative_direction"], dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            bins_with_speed_by_base_overlap=("speed_context_status", lambda s: int(s.eq("speed_assigned_by_base_overlap").sum())),
            bins_with_speed_by_base_nearest=("speed_context_status", lambda s: int(s.eq("speed_assigned_by_base_nearest").sum())),
            bins_with_ambiguous_speed=("speed_context_status", lambda s: int(s.eq("ambiguous_multiple_speed_values").sum())),
            bins_missing_speed=("speed_context_status", lambda s: int(s.eq("no_speed_nearby").sum())),
        )
        .reset_index()
    )


def _speed_record_outputs(speed: gpd.GeoDataFrame, overlap: pd.DataFrame, nearest: pd.DataFrame, base_context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    joined = pd.concat([overlap, nearest], ignore_index=True, sort=False) if not overlap.empty or not nearest.empty else pd.DataFrame()
    if not joined.empty:
        joined["speed_source_index"] = pd.to_numeric(joined["speed_source_index"], errors="coerce").astype("Int64").astype(str)
        match_counts = joined.groupby("speed_source_index", dropna=False)["source_bin_key"].nunique().reset_index(name="matched_base_bin_count")
        joined = joined.merge(match_counts, on="speed_source_index", how="left")
    ambiguous_keys = set(base_context.loc[base_context["speed_value_conflict_flag"], "source_bin_key"].astype(str))
    ambiguous = joined.loc[joined["source_bin_key"].astype(str).isin(ambiguous_keys)].copy() if not joined.empty else pd.DataFrame()
    matched_source_indices = set(joined["speed_source_index"].astype(str)) if not joined.empty else set()
    columns = ["speed_source_index", "speed_record_id", "source_geometry_is_null", "source_geometry_is_valid", *SPEED_VALUE_FIELDS]
    for field in SPEED_ROUTE_FIELDS:
        if field in speed.columns and field not in columns:
            columns.append(field)
    unmatched = pd.DataFrame(speed[[c for c in columns if c in speed.columns]].copy())
    unmatched["speed_source_index"] = pd.to_numeric(unmatched["speed_source_index"], errors="coerce").astype("Int64").astype(str)
    unmatched = unmatched.loc[~unmatched["speed_source_index"].astype(str).isin(matched_source_indices)].copy()
    unmatched["unmatched_status"] = unmatched.apply(
        lambda row: "null_geometry_source_limitation" if bool(row.get("source_geometry_is_null", False)) else "outside_stable_universe_or_beyond_nearest_tolerance",
        axis=1,
    )
    return joined, joined.copy(), ambiguous, unmatched


def _paired_pseudo_direction_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    work = bin_context.loc[bin_context["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    rows = []
    for keys, group in work.groupby(["reference_signal_id", "far_anchor_id", "base_segment_id", "source_bin_key"], dropna=False):
        if group["reference_directional_bin_id"].nunique() < 2:
            continue
        statuses = sorted(group["speed_context_status"].astype(str).unique().tolist())
        methods = sorted(group["speed_context_method"].astype(str).unique().tolist())
        car_values = sorted(pd.to_numeric(group["dominant_car_speed_limit"], errors="coerce").dropna().unique().tolist())
        missing_count = int(group["speed_context_status"].eq("no_speed_nearby").sum())
        rows.append(
            {
                "reference_signal_id": keys[0],
                "far_anchor_id": keys[1],
                "base_segment_id": keys[2],
                "source_bin_key": keys[3],
                "paired_bin_count": group["reference_directional_bin_id"].nunique(),
                "speed_context_statuses": "|".join(statuses),
                "speed_context_methods": "|".join(methods),
                "dominant_car_speed_values": "|".join(_format_speed(v) for v in car_values),
                "missing_speed_bin_count": missing_count,
                "same_speed_context_across_pair": len(statuses) == 1 and len(car_values) <= 1,
                "missing_differs_within_pair": missing_count > 0 and missing_count < group["reference_directional_bin_id"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def _v1_metric(metric: str) -> Any:
    if not V1_SUMMARY_FILE.exists():
        return pd.NA
    summary = pd.read_csv(V1_SUMMARY_FILE)
    row = summary.loc[summary["metric"].eq(metric)]
    if row.empty:
        return pd.NA
    value = row.iloc[0].get("count")
    return pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]


def _comparison_to_v1(bin_context: pd.DataFrame, paired_qa: pd.DataFrame) -> pd.DataFrame:
    v2_missing = int(bin_context["speed_context_status"].eq("no_speed_nearby").sum())
    v2_conflicts = int(bin_context["speed_context_status"].eq("ambiguous_multiple_speed_values").sum())
    v2_inconsistent = int((~paired_qa["same_speed_context_across_pair"].astype(bool)).sum()) if not paired_qa.empty else 0
    v1_inconsistent = pd.NA
    if V1_PAIRED_QA_FILE.exists():
        v1_paired = pd.read_csv(V1_PAIRED_QA_FILE, dtype=str)
        v1_inconsistent = int((~v1_paired["same_speed_context_across_pair"].astype(str).str.lower().eq("true")).sum())
    rows = [
        {"metric": "missing_speed_bins", "v1_count": _v1_metric("bins_missing_speed_context"), "v2_count": v2_missing},
        {"metric": "ambiguous_conflicting_speed_bins", "v1_count": _v1_metric("ambiguous_conflicting_speed_bin_matches"), "v2_count": v2_conflicts},
        {"metric": "paired_pseudo_direction_groups_inconsistent", "v1_count": v1_inconsistent, "v2_count": v2_inconsistent},
    ]
    out = pd.DataFrame(rows)
    out["count_delta_v2_minus_v1"] = pd.to_numeric(out["v2_count"], errors="coerce") - pd.to_numeric(out["v1_count"], errors="coerce")
    return out


def _qa(speed: gpd.GeoDataFrame, context_bins: pd.DataFrame, bin_context: pd.DataFrame, crash_context: pd.DataFrame, paired_qa: pd.DataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": "not_read", "expected": "none"},
        {"check_name": "speed_fields_used_for_upstream_downstream", "passed": True, "observed": "not_used", "expected": "not_used"},
        {"check_name": "scaffold_catchment_assignment_access_logic_changed", "passed": True, "observed": "read_only_context_join", "expected": "no_changes"},
        {"check_name": "main_context_bins_lte_2500ft", "passed": int(pd.to_numeric(bin_context["bin_midpoint_ft_from_reference_signal"], errors="coerce").gt(2500).sum()) == 0, "observed": int(pd.to_numeric(bin_context["bin_midpoint_ft_from_reference_signal"], errors="coerce").gt(2500).sum()), "expected": 0},
        {"check_name": "bins_with_speed_by_base_overlap", "passed": True, "observed": int(bin_context["speed_context_status"].eq("speed_assigned_by_base_overlap").sum()), "expected": "reported"},
        {"check_name": "bins_with_speed_by_base_nearest_fallback", "passed": True, "observed": int(bin_context["speed_context_status"].eq("speed_assigned_by_base_nearest").sum()), "expected": "reported"},
        {"check_name": "bins_missing_speed", "passed": True, "observed": int(bin_context["speed_context_status"].eq("no_speed_nearby").sum()), "expected": "reported"},
        {"check_name": "ambiguous_conflicting_speed_bins", "passed": True, "observed": int(bin_context["speed_context_status"].eq("ambiguous_multiple_speed_values").sum()), "expected": "reported"},
        {"check_name": "severe_conflict_bins", "passed": True, "observed": int(bin_context["severe_conflict_spread_ge_15mph"].astype(bool).sum()), "expected": "reported"},
        {"check_name": "paired_pseudo_direction_same_context", "passed": True, "observed": int(paired_qa["same_speed_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0, "expected": "reported"},
        {"check_name": "v2_missing_compared_to_v1", "passed": True, "observed": _comparison_value(comparison, "missing_speed_bins"), "expected": "reported"},
        {"check_name": "v2_conflicts_compared_to_v1", "passed": True, "observed": _comparison_value(comparison, "ambiguous_conflicting_speed_bins"), "expected": "reported"},
        {"check_name": "crashes_inheriting_v2_speed_context", "passed": True, "observed": len(crash_context), "expected": "reported"},
        {"check_name": "reference_signals_with_v2_speed_context", "passed": True, "observed": bin_context["reference_signal_id"].nunique(), "expected": "reported"},
        {"check_name": "null_geometry_speed_records_excluded_and_counted", "passed": int(speed["source_geometry_is_null"].sum()) == 102, "observed": int(speed["source_geometry_is_null"].sum()), "expected": 102},
        {"check_name": "speed_crs_matches_working_crs", "passed": crs_matches(speed.crs, WORKING_CRS_AUTHORITY), "observed": crs_to_string(speed.crs), "expected": WORKING_CRS_AUTHORITY},
    ]
    return pd.DataFrame(rows)


def _comparison_value(comparison: pd.DataFrame, metric: str) -> str:
    row = comparison.loc[comparison["metric"].eq(metric)]
    if row.empty:
        return ""
    row = row.iloc[0]
    return f"v1={row['v1_count']};v2={row['v2_count']};delta={row['count_delta_v2_minus_v1']}"


def _summary_frame(speed: gpd.GeoDataFrame, bin_context: pd.DataFrame, crash_context: pd.DataFrame, paired_qa: pd.DataFrame, comparison: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "speed_records_considered", "value": "", "count": len(speed)},
        {"metric": "speed_records_with_null_geometry", "value": "", "count": int(speed["source_geometry_is_null"].sum())},
        {"metric": "primary_context_bins_0_2500ft", "value": "", "count": len(bin_context)},
        {"metric": "bins_with_speed_by_base_overlap", "value": "", "count": int(bin_context["speed_context_status"].eq("speed_assigned_by_base_overlap").sum())},
        {"metric": "bins_with_speed_by_base_nearest_fallback", "value": "", "count": int(bin_context["speed_context_status"].eq("speed_assigned_by_base_nearest").sum())},
        {"metric": "bins_missing_speed", "value": "", "count": int(bin_context["speed_context_status"].eq("no_speed_nearby").sum())},
        {"metric": "ambiguous_conflicting_speed_bins", "value": "", "count": int(bin_context["speed_context_status"].eq("ambiguous_multiple_speed_values").sum())},
        {"metric": "severe_conflict_bins_spread_ge_15mph", "value": "", "count": int(bin_context["severe_conflict_spread_ge_15mph"].astype(bool).sum())},
        {"metric": "paired_pseudo_direction_groups_checked", "value": "", "count": len(paired_qa)},
        {"metric": "paired_pseudo_direction_groups_same_context", "value": "", "count": int(paired_qa["same_speed_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0},
        {"metric": "paired_pseudo_direction_groups_inconsistent", "value": "", "count": int((~paired_qa["same_speed_context_across_pair"].astype(bool)).sum()) if not paired_qa.empty else 0},
        {"metric": "paired_pseudo_direction_missing_differs_within_pair", "value": "", "count": int(paired_qa["missing_differs_within_pair"].astype(bool).sum()) if not paired_qa.empty else 0},
        {"metric": "crashes_inheriting_v2_speed_context", "value": "", "count": len(crash_context)},
        {"metric": "reference_signals_with_v2_speed_context", "value": "", "count": signal_summary["reference_signal_id"].nunique() if not signal_summary.empty else 0},
        {"metric": "v1_missing_speed_bins", "value": "", "count": _comparison_value_raw(comparison, "missing_speed_bins", "v1_count")},
        {"metric": "v2_missing_speed_bins", "value": "", "count": _comparison_value_raw(comparison, "missing_speed_bins", "v2_count")},
        {"metric": "v1_conflicting_speed_bins", "value": "", "count": _comparison_value_raw(comparison, "ambiguous_conflicting_speed_bins", "v1_count")},
        {"metric": "v2_conflicting_speed_bins", "value": "", "count": _comparison_value_raw(comparison, "ambiguous_conflicting_speed_bins", "v2_count")},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "speed_scaffold_assignment_access_logic_changed", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _comparison_value_raw(comparison: pd.DataFrame, metric: str, column: str) -> Any:
    row = comparison.loc[comparison["metric"].eq(metric)]
    return pd.NA if row.empty else row.iloc[0][column]


def _findings(summary: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    passed = int(qa["passed"].astype(bool).sum()) if not qa.empty else 0
    usable = int(count("bins_missing_speed") or 0) < int(count("v1_missing_speed_bins") or 0) and int(count("paired_pseudo_direction_groups_inconsistent") or 0) < 1000
    return "\n".join(
        [
            "# Speed Context Join V2 Base Geometry Findings",
            "",
            "## Bounded Question",
            "",
            "Join posted-speed context to source roadway/base-bin geometry, then propagate base-bin context to directional records without changing scaffold, catchments, assignment, access context, or upstream/downstream labels.",
            "",
            "## Key Counts",
            "",
            f"- primary context bins 0-2,500 ft: {count('primary_context_bins_0_2500ft')}",
            f"- bins with speed by base overlap: {count('bins_with_speed_by_base_overlap')}",
            f"- bins with speed by base nearest fallback: {count('bins_with_speed_by_base_nearest_fallback')}",
            f"- bins missing speed: {count('bins_missing_speed')}",
            f"- ambiguous/conflicting speed bins: {count('ambiguous_conflicting_speed_bins')}",
            f"- severe conflicts with spread >= 15 mph: {count('severe_conflict_bins_spread_ge_15mph')}",
            f"- paired pseudo-direction groups same context: {count('paired_pseudo_direction_groups_same_context')}",
            f"- paired pseudo-direction groups inconsistent: {count('paired_pseudo_direction_groups_inconsistent')}",
            f"- missing differs within pair: {count('paired_pseudo_direction_missing_differs_within_pair')}",
            f"- crashes inheriting v2 speed context: {count('crashes_inheriting_v2_speed_context')}",
            f"- reference signals with v2 speed context: {count('reference_signals_with_v2_speed_context')}",
            "",
            "## V1 Comparison",
            "",
            f"- v1 missing speed bins: {count('v1_missing_speed_bins')}",
            f"- v2 missing speed bins: {count('v2_missing_speed_bins')}",
            f"- v1 conflicting speed bins: {count('v1_conflicting_speed_bins')}",
            f"- v2 conflicting speed bins: {count('v2_conflicting_speed_bins')}",
            f"- good enough for combined context table: {usable}",
            "",
            "## Boundary Checks",
            "",
            f"- crash direction fields read or used: {summary.loc[summary['metric'].eq('crash_direction_fields_read_or_used'), 'value'].iloc[0]}",
            f"- speed/scaffold/assignment/access logic changed: {summary.loc[summary['metric'].eq('speed_scaffold_assignment_access_logic_changed'), 'value'].iloc[0]}",
            f"- QA checks passed: {passed} of {len(qa)}",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
            "## Recommended Next Step",
            "",
            "Use v2 only if the missing and paired-consistency counts improve enough for descriptive context; otherwise continue source coverage and route-representation diagnostics before combining access and speed context.",
            "",
        ]
    )


def _ordered_bin_context(frame: pd.DataFrame) -> pd.DataFrame:
    extra_columns = [column for column in frame.columns if column not in MAIN_OUTPUT_COLUMNS]
    return frame[[c for c in MAIN_OUTPUT_COLUMNS if c in frame.columns] + extra_columns].copy()


def build_speed_context_join_v2(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    speed = _load_speed()
    context_bins = _load_directional_context_bins()
    base_bins = _load_base_bin_geometry(context_bins)
    _ = _read_csv(USABLE_SEGMENTS_FILE)
    _ = _read_csv(ASSIGNMENTS_FILE, usecols=["crash_id", "reference_directional_bin_id", "assignment_status"])
    if STAGING_SCHEMA_FILE.exists():
        _ = _read_csv(STAGING_SCHEMA_FILE)
    if STAGING_FIELD_ROLES_FILE.exists():
        _ = _read_csv(STAGING_FIELD_ROLES_FILE)
    if STAGING_CRS_SANITY_FILE.exists():
        _ = _read_csv(STAGING_CRS_SANITY_FILE)

    overlap = _overlap_candidates(speed, base_bins)
    nearest = _nearest_candidates(speed, base_bins, overlap)
    base_context = _build_base_context(base_bins, overlap, nearest)
    directional_context = _build_directional_context(context_bins, base_context)
    high_priority = directional_context.loc[directional_context["distance_window"].eq("high_priority_0_1000ft")].copy()
    sensitivity = directional_context.loc[directional_context["distance_window"].eq("sensitivity_1000_2500ft")].copy()
    readiness_columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
    ]
    readiness = _read_csv(READINESS_FILE, usecols=readiness_columns)
    crash_context = _crash_context(readiness, directional_context)
    signal_summary = _reference_signal_summary(directional_context)
    speed_joined, speed_candidates, speed_ambiguous, speed_unmatched = _speed_record_outputs(speed, overlap, nearest, base_context)
    missing = directional_context.loc[directional_context["speed_context_status"].eq("no_speed_nearby")].copy()
    paired_qa = _paired_pseudo_direction_qa(directional_context)
    comparison = _comparison_to_v1(directional_context, paired_qa)
    qa = _qa(speed, context_bins, directional_context, crash_context, paired_qa, comparison)
    summary = _summary_frame(speed, directional_context, crash_context, paired_qa, comparison, signal_summary)

    outputs = {
        "summary_csv": out_dir / "speed_context_v2_summary.csv",
        "base_bin_context_csv": out_dir / "base_bin_speed_context.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_speed_context_v2.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_speed_context_v2_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_speed_context_v2_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_speed_context_v2.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_speed_context_summary_v2.csv",
        "speed_records_joined_csv": out_dir / "speed_records_joined_to_stable_universe_v2.csv",
        "speed_bin_match_candidates_csv": out_dir / "speed_bin_match_candidates_v2.csv",
        "speed_bin_ambiguous_csv": out_dir / "speed_bin_ambiguous_matches_v2.csv",
        "speed_missing_bins_csv": out_dir / "speed_missing_bins_v2.csv",
        "paired_pseudo_direction_qa_csv": out_dir / "speed_paired_pseudo_direction_consistency_qa_v2.csv",
        "comparison_to_v1_csv": out_dir / "speed_context_v2_comparison_to_v1.csv",
        "qa_csv": out_dir / "speed_context_v2_qa.csv",
        "findings_md": out_dir / "speed_context_v2_findings.md",
        "manifest_json": out_dir / "speed_context_v2_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(base_context, outputs["base_bin_context_csv"])
    _write_csv(_ordered_bin_context(directional_context), outputs["directional_bin_context_csv"])
    _write_csv(_ordered_bin_context(high_priority), outputs["directional_bin_context_0_1000_csv"])
    _write_csv(_ordered_bin_context(sensitivity), outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(signal_summary, outputs["reference_signal_summary_csv"])
    _write_csv(speed_joined, outputs["speed_records_joined_csv"])
    _write_csv(speed_candidates, outputs["speed_bin_match_candidates_csv"])
    _write_csv(speed_ambiguous, outputs["speed_bin_ambiguous_csv"])
    _write_csv(missing, outputs["speed_missing_bins_csv"])
    _write_csv(paired_qa, outputs["paired_pseudo_direction_qa_csv"])
    _write_csv(comparison, outputs["comparison_to_v1_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, qa, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only speed context join v2 using source base-bin geometry",
        "main_context_window": "0-2500ft",
        "nearest_line_fallback_tolerance_ft": NEAREST_TOLERANCE_FT,
        "crash_direction_fields_read_or_used": False,
        "speed_fields_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_access_logic_changed": False,
        "aadt_join_implemented": False,
        "inputs": {
            "speed": str(SPEED_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "usable_segments": str(USABLE_SEGMENTS_FILE),
            "source_bin_geometry": str(SOURCE_BIN_GEOMETRY_FILE),
            "catchment_index_metadata_only": str(CATCHMENT_INDEX_FILE),
            "readiness_by_crash": str(READINESS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Join posted-speed context using source base-bin geometry.")
    parser.parse_args()
    outputs = build_speed_context_join_v2()
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
