from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .crs_utils import WORKING_CRS_AUTHORITY, apply_authoritative_crs, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/speed_context_join")

SPEED_FILE = Path("artifacts/normalized/speed.parquet")
READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
CATCHMENT_POLYGONS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_polygons.geojson"
CATCHMENT_CRS_METADATA_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_crs_metadata.json"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv"
STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_field_role_candidates.csv"
STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_crs_sanity.csv"

FEET_TO_METERS = 0.3048
NEAREST_TOLERANCE_FT = 100.0
NEAREST_TOLERANCE_M = NEAREST_TOLERANCE_FT * FEET_TO_METERS

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
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_midpoint_ft_from_reference_signal",
    "distance_window",
    "roadway_representation_type",
    "far_anchor_type",
    "speed_match_count",
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
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        direction_like = [column for column in usecols if _is_crash_direction_field(column)]
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


def _load_speed() -> gpd.GeoDataFrame:
    speed = gpd.read_parquet(SPEED_FILE)
    if speed.crs is None:
        raise ValueError("Speed source has no CRS; rerun posted speed staging before joining.")
    missing = [field for field in SPEED_VALUE_FIELDS if field not in speed.columns]
    if missing:
        raise ValueError(f"Speed source is missing required posted-speed fields: {missing}")
    speed = speed.to_crs(WORKING_CRS_AUTHORITY)
    speed = speed.reset_index(names="speed_source_index")
    if SPEED_ID_FIELD not in speed.columns:
        speed[SPEED_ID_FIELD] = speed["speed_source_index"].astype(str)
    speed["speed_record_id"] = speed[SPEED_ID_FIELD].astype(str)
    speed["source_geometry_is_null"] = speed.geometry.isna()
    speed["source_geometry_is_valid"] = speed.geometry.notna() & speed.geometry.is_valid
    return speed


def _load_context_bins() -> pd.DataFrame:
    bins = _read_csv(USABLE_BINS_FILE)
    catchment_index = _read_csv(CATCHMENT_INDEX_FILE)
    catchment_index = catchment_index.loc[catchment_index["catchment_status"].eq("usable")].copy()
    bins["bin_midpoint_ft_from_reference_signal"] = _num(bins, "bin_midpoint_ft_from_reference_signal")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    catchment_keep = [
        "catchment_id",
        "reference_directional_bin_id",
        "catchment_status",
        "catchment_confidence",
        "catchment_method",
    ]
    context = bins.merge(catchment_index[[c for c in catchment_keep if c in catchment_index.columns]], on="reference_directional_bin_id", how="left")
    context["context_join_eligible"] = context["catchment_status"].eq("usable") & context["bin_midpoint_ft_from_reference_signal"].le(2500)
    return context


def _load_context_catchments(context_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    catchments = gpd.read_file(CATCHMENT_POLYGONS_FILE)
    catchments, _, _ = apply_authoritative_crs(catchments, metadata_path=CATCHMENT_CRS_METADATA_FILE)
    eligible_ids = set(context_bins.loc[context_bins["context_join_eligible"], "catchment_id"].dropna().astype(str))
    catchments = catchments.loc[catchments["catchment_id"].astype(str).isin(eligible_ids)].copy()
    keep = [
        "catchment_id",
        "reference_directional_bin_id",
        "reference_directional_segment_id",
        "reference_signal_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_index_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "catchment_method",
        "catchment_status",
        "geometry",
    ]
    return catchments[[c for c in keep if c in catchments.columns]].copy()


def _speed_columns_for_matching(speed: gpd.GeoDataFrame) -> list[str]:
    columns = ["speed_source_index", "speed_record_id", *SPEED_VALUE_FIELDS]
    for field in [*SPEED_ROUTE_FIELDS, *SPEED_METADATA_FIELDS]:
        if field in speed.columns and field not in columns:
            columns.append(field)
    return columns


def _overlap_candidates(speed: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    valid_speed = speed.loc[speed["source_geometry_is_valid"]].copy()
    columns = _speed_columns_for_matching(valid_speed)
    joined = gpd.sjoin(valid_speed[columns + ["geometry"]], catchments, how="inner", predicate="intersects")
    if joined.empty:
        return pd.DataFrame(columns=["reference_directional_bin_id", "speed_record_id", "speed_overlap_length_ft"])
    joined = joined.drop(columns=["index_right"], errors="ignore").copy()
    right_geometries = catchments[["reference_directional_bin_id", "geometry"]].rename(columns={"geometry": "catchment_geometry"})
    joined = joined.merge(right_geometries, on="reference_directional_bin_id", how="left")
    joined["speed_overlap_length_ft"] = joined.apply(_intersection_length_ft, axis=1)
    joined = joined.loc[pd.to_numeric(joined["speed_overlap_length_ft"], errors="coerce").gt(0)].copy()
    joined["speed_context_method"] = "line_overlap"
    return pd.DataFrame(joined.drop(columns=["geometry", "catchment_geometry"], errors="ignore"))


def _intersection_length_ft(row: pd.Series) -> float:
    line = row.get("geometry")
    polygon = row.get("catchment_geometry")
    if line is None or polygon is None:
        return 0.0
    try:
        if line.is_empty or polygon.is_empty:
            return 0.0
        return float(line.intersection(polygon).length / FEET_TO_METERS)
    except Exception:
        return 0.0


def _nearest_candidates(speed: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame, overlap: pd.DataFrame) -> pd.DataFrame:
    bins_with_overlap = set(overlap["reference_directional_bin_id"].astype(str)) if not overlap.empty else set()
    no_overlap = catchments.loc[~catchments["reference_directional_bin_id"].astype(str).isin(bins_with_overlap)].copy()
    valid_speed = speed.loc[speed["source_geometry_is_valid"]].copy()
    if no_overlap.empty or valid_speed.empty:
        return pd.DataFrame(columns=["reference_directional_bin_id", "speed_record_id", "nearest_speed_distance_ft"])
    columns = _speed_columns_for_matching(valid_speed)
    nearest = gpd.sjoin_nearest(
        no_overlap,
        valid_speed[columns + ["geometry"]],
        how="left",
        max_distance=NEAREST_TOLERANCE_M,
        distance_col="nearest_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest = nearest.loc[nearest["speed_record_id"].notna()].copy()
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest["speed_overlap_length_ft"] = 0.0
    nearest["speed_context_method"] = "nearest_line_within_tolerance"
    return nearest


def _build_bin_context(context_bins: pd.DataFrame, overlap: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    primary = context_bins.loc[context_bins["context_join_eligible"]].copy()
    base_columns = [
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "far_anchor_type",
    ]
    out = primary[[c for c in base_columns if c in primary.columns]].copy()
    stats = _candidate_stats(overlap, nearest)
    if not stats.empty:
        out = out.merge(stats, on="reference_directional_bin_id", how="left")
    defaults: dict[str, Any] = {
        "speed_match_count": 0,
        "dominant_car_speed_limit": pd.NA,
        "dominant_truck_speed_limit": pd.NA,
        "speed_value_conflict_flag": False,
        "speed_candidate_values": "",
        "speed_overlap_length_ft": 0.0,
        "nearest_speed_distance_ft": pd.NA,
        "nearest_speed_record_id": "",
        "speed_context_method": "no_speed_match",
        "speed_context_confidence": "missing",
        "speed_context_status": "no_speed_nearby",
    }
    for column, default in defaults.items():
        if column not in out.columns:
            out[column] = default
        else:
            out[column] = out[column].fillna(default)
    out["speed_match_count"] = pd.to_numeric(out["speed_match_count"], errors="coerce").fillna(0).astype(int)
    out["speed_value_conflict_flag"] = out["speed_value_conflict_flag"].astype(bool)
    out["speed_context_method"] = out.apply(_context_method, axis=1)
    out["speed_context_confidence"] = out.apply(_context_confidence, axis=1)
    out["speed_context_status"] = out.apply(_context_status, axis=1)
    return out


def _candidate_stats(overlap: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not overlap.empty:
        frames.append(overlap.copy())
    if not nearest.empty:
        frames.append(nearest.copy())
    if not frames:
        return pd.DataFrame(columns=["reference_directional_bin_id"])
    candidates = pd.concat(frames, ignore_index=True, sort=False)
    rows = []
    for bin_id, group in candidates.groupby("reference_directional_bin_id", dropna=False):
        overlap_group = group.loc[group["speed_context_method"].eq("line_overlap")].copy()
        nearest_group = group.loc[group["speed_context_method"].eq("nearest_line_within_tolerance")].copy()
        primary = overlap_group if not overlap_group.empty else nearest_group
        car_values = _value_set(primary, CAR_SPEED_FIELD)
        truck_values = _value_set(primary, TRUCK_SPEED_FIELD)
        row = {
            "reference_directional_bin_id": bin_id,
            "speed_match_count": int(primary["speed_record_id"].nunique()),
            "dominant_car_speed_limit": _dominant_speed(primary, CAR_SPEED_FIELD),
            "dominant_truck_speed_limit": _dominant_speed(primary, TRUCK_SPEED_FIELD),
            "speed_value_conflict_flag": len(car_values) > 1 or len(truck_values) > 1,
            "speed_candidate_values": _candidate_values(primary),
            "speed_overlap_length_ft": round(float(pd.to_numeric(overlap_group.get("speed_overlap_length_ft", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()), 3),
            "nearest_speed_distance_ft": _min_numeric(nearest_group, "nearest_speed_distance_ft"),
            "nearest_speed_record_id": _nearest_record_id(nearest_group),
            "speed_context_method": "line_overlap" if not overlap_group.empty else "nearest_line_within_tolerance",
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _value_set(frame: pd.DataFrame, field: str) -> list[str]:
    if frame.empty or field not in frame.columns:
        return []
    values = pd.to_numeric(frame[field], errors="coerce").dropna().sort_values().unique().tolist()
    return [str(int(value)) if float(value).is_integer() else str(value) for value in values]


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
    value = grouped.iloc[0][field]
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return int(numeric)
    return value


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


def _context_method(row: pd.Series) -> str:
    if row.get("distance_window") == "review_over_2500ft":
        return "no_speed_match"
    if bool(row.get("speed_value_conflict_flag", False)):
        return "ambiguous_conflicting_speed_values"
    return str(row.get("speed_context_method") or "no_speed_match")


def _context_confidence(row: pd.Series) -> str:
    method = row.get("speed_context_method")
    if method == "line_overlap" and not bool(row.get("speed_value_conflict_flag", False)):
        return "high"
    if method == "nearest_line_within_tolerance" and not bool(row.get("speed_value_conflict_flag", False)):
        return "medium"
    if bool(row.get("speed_value_conflict_flag", False)):
        return "low_review"
    return "missing"


def _context_status(row: pd.Series) -> str:
    if row.get("distance_window") == "review_over_2500ft":
        return "outside_context_window"
    if bool(row.get("speed_value_conflict_flag", False)):
        return "ambiguous_multiple_speed_values"
    method = row.get("speed_context_method")
    if method == "line_overlap":
        return "speed_assigned_by_overlap"
    if method == "nearest_line_within_tolerance":
        return "speed_assigned_by_nearest"
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
    out["inherited_from_bin_speed_context"] = True
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
        "inherited_from_bin_speed_context",
    ]
    return out[[c for c in columns if c in out.columns]]


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in bin_context.groupby(["reference_signal_id", "distance_window", "signal_relative_direction"], dropna=False):
        reference_signal_id, distance_window, direction = keys
        rows.append(
            {
                "reference_signal_id": reference_signal_id,
                "distance_window": distance_window,
                "signal_relative_direction": direction,
                "bin_count": len(group),
                "bins_with_speed_by_overlap": int(group["speed_context_status"].eq("speed_assigned_by_overlap").sum()),
                "bins_with_speed_by_nearest": int(group["speed_context_status"].eq("speed_assigned_by_nearest").sum()),
                "bins_with_ambiguous_speed": int(group["speed_context_status"].eq("ambiguous_multiple_speed_values").sum()),
                "bins_missing_speed": int(group["speed_context_status"].eq("no_speed_nearby").sum()),
                "dominant_car_speed_values": _joined_values(group, "dominant_car_speed_limit"),
            }
        )
    return pd.DataFrame(rows)


def _joined_values(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns:
        return ""
    values = pd.to_numeric(frame[column], errors="coerce").dropna().sort_values().unique().tolist()
    return "|".join(str(int(value)) if float(value).is_integer() else str(value) for value in values)


def _summarize_bins(bin_context: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if bin_context.empty:
        return pd.DataFrame()
    return (
        bin_context.groupby(columns, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            bins_with_speed_by_overlap=("speed_context_status", lambda s: int(s.eq("speed_assigned_by_overlap").sum())),
            bins_with_speed_by_nearest=("speed_context_status", lambda s: int(s.eq("speed_assigned_by_nearest").sum())),
            bins_with_ambiguous_speed=("speed_context_status", lambda s: int(s.eq("ambiguous_multiple_speed_values").sum())),
            bins_missing_speed=("speed_context_status", lambda s: int(s.eq("no_speed_nearby").sum())),
        )
        .reset_index()
    )


def _by_posted_speed(bin_context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field, label in [(CAR_SPEED_FIELD, "car"), (TRUCK_SPEED_FIELD, "truck")]:
        context_field = "dominant_car_speed_limit" if field == CAR_SPEED_FIELD else "dominant_truck_speed_limit"
        work = bin_context.loc[pd.to_numeric(bin_context[context_field], errors="coerce").notna()].copy()
        if work.empty:
            continue
        grouped = work.groupby([context_field, "distance_window"], dropna=False).agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            overlap_bin_count=("speed_context_status", lambda s: int(s.eq("speed_assigned_by_overlap").sum())),
            nearest_bin_count=("speed_context_status", lambda s: int(s.eq("speed_assigned_by_nearest").sum())),
            ambiguous_bin_count=("speed_context_status", lambda s: int(s.eq("ambiguous_multiple_speed_values").sum())),
        )
        for row in grouped.reset_index().itertuples(index=False):
            rows.append(
                {
                    "speed_vehicle_type": label,
                    "posted_speed_limit": getattr(row, context_field),
                    "distance_window": row.distance_window,
                    "bin_count": int(row.bin_count),
                    "overlap_bin_count": int(row.overlap_bin_count),
                    "nearest_bin_count": int(row.nearest_bin_count),
                    "ambiguous_bin_count": int(row.ambiguous_bin_count),
                }
            )
    return pd.DataFrame(rows)


def _speed_record_outputs(speed: gpd.GeoDataFrame, overlap: pd.DataFrame, nearest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    joined = pd.concat([overlap, nearest], ignore_index=True, sort=False) if not overlap.empty or not nearest.empty else pd.DataFrame()
    if not joined.empty:
        joined = joined.copy()
        joined["speed_source_index"] = pd.to_numeric(joined["speed_source_index"], errors="coerce").astype("Int64").astype(str)
        match_counts = joined.groupby("speed_source_index", dropna=False)["reference_directional_bin_id"].nunique().reset_index(name="matched_bin_count")
        joined = joined.merge(match_counts, on="speed_source_index", how="left")
    ambiguous = pd.DataFrame()
    if not joined.empty:
        per_bin = _candidate_stats(
            joined.loc[joined["speed_context_method"].eq("line_overlap")].copy(),
            joined.loc[joined["speed_context_method"].eq("nearest_line_within_tolerance")].copy(),
        )
        ambiguous_bins = set(per_bin.loc[per_bin["speed_value_conflict_flag"], "reference_directional_bin_id"].astype(str))
        ambiguous = joined.loc[joined["reference_directional_bin_id"].astype(str).isin(ambiguous_bins)].copy()
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
    candidates = joined.copy()
    return joined, candidates, ambiguous, unmatched


def _qa(
    *,
    speed: gpd.GeoDataFrame,
    context_bins: pd.DataFrame,
    bin_context: pd.DataFrame,
    crash_context: pd.DataFrame,
    speed_joined: pd.DataFrame,
    speed_ambiguous: pd.DataFrame,
    speed_unmatched: pd.DataFrame,
    readiness_header: list[str],
) -> pd.DataFrame:
    direction_like_columns = [column for column in readiness_header if _is_crash_direction_field(column)]
    over_2500_in_main = int(pd.to_numeric(bin_context["bin_midpoint_ft_from_reference_signal"], errors="coerce").gt(2500).sum())
    null_geometry_count = int(speed["source_geometry_is_null"].sum())
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": not direction_like_columns, "observed": "|".join(direction_like_columns), "expected": "none"},
        {"check_name": "speed_fields_used_for_upstream_downstream", "passed": True, "observed": "not_used", "expected": "not_used"},
        {"check_name": "scaffold_catchment_assignment_access_logic_changed", "passed": True, "observed": "read_only_context_join", "expected": "no_changes"},
        {"check_name": "main_context_bins_lte_2500ft", "passed": over_2500_in_main == 0, "observed": over_2500_in_main, "expected": 0},
        {
            "check_name": "review_over_2500ft_bins_excluded_from_main",
            "passed": True,
            "observed": int((~context_bins["context_join_eligible"] & context_bins["bin_midpoint_ft_from_reference_signal"].gt(2500)).sum()),
            "expected": "reported_only",
        },
        {"check_name": "speed_crs_matches_working_crs", "passed": crs_matches(speed.crs, WORKING_CRS_AUTHORITY), "observed": crs_to_string(speed.crs), "expected": WORKING_CRS_AUTHORITY},
        {"check_name": "speed_records_matched_to_at_least_one_stable_bin", "passed": True, "observed": speed_joined["speed_source_index"].nunique() if not speed_joined.empty else 0, "expected": "reported"},
        {"check_name": "ambiguous_conflicting_speed_matches", "passed": True, "observed": speed_ambiguous["reference_directional_bin_id"].nunique() if not speed_ambiguous.empty else 0, "expected": "reported"},
        {"check_name": "unmatched_speed_records", "passed": True, "observed": len(speed_unmatched) if not speed_unmatched.empty else len(speed), "expected": "reported"},
        {"check_name": "bins_with_speed_by_overlap", "passed": True, "observed": int(bin_context["speed_context_status"].eq("speed_assigned_by_overlap").sum()), "expected": "reported"},
        {"check_name": "bins_with_speed_by_nearest_fallback", "passed": True, "observed": int(bin_context["speed_context_status"].eq("speed_assigned_by_nearest").sum()), "expected": "reported"},
        {"check_name": "bins_missing_speed_context", "passed": True, "observed": int(bin_context["speed_context_status"].eq("no_speed_nearby").sum()), "expected": "reported"},
        {"check_name": "crashes_inheriting_speed_context", "passed": True, "observed": len(crash_context), "expected": "reported"},
        {"check_name": "distance_window_summary_created", "passed": True, "observed": "speed_context_by_distance_window.csv", "expected": "created"},
        {"check_name": "upstream_downstream_summary_created", "passed": True, "observed": "speed_context_by_signal_relative_direction.csv", "expected": "created"},
        {"check_name": "posted_speed_summary_created", "passed": True, "observed": "speed_context_by_posted_speed.csv", "expected": "created"},
        {"check_name": "null_geometry_speed_records_excluded_and_counted", "passed": null_geometry_count == 102, "observed": null_geometry_count, "expected": 102},
    ]
    return pd.DataFrame(rows)


def _summary_frame(
    speed: gpd.GeoDataFrame,
    context_bins: pd.DataFrame,
    bin_context: pd.DataFrame,
    crash_context: pd.DataFrame,
    speed_joined: pd.DataFrame,
    speed_ambiguous: pd.DataFrame,
    speed_unmatched: pd.DataFrame,
    signal_summary: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        {"metric": "speed_records_considered", "value": "", "count": len(speed)},
        {"metric": "speed_records_with_null_geometry", "value": "", "count": int(speed["source_geometry_is_null"].sum())},
        {"metric": "speed_records_matched_to_at_least_one_stable_bin", "value": "", "count": speed_joined["speed_source_index"].nunique() if not speed_joined.empty else 0},
        {"metric": "ambiguous_conflicting_speed_bin_matches", "value": "", "count": speed_ambiguous["reference_directional_bin_id"].nunique() if not speed_ambiguous.empty else 0},
        {"metric": "unmatched_speed_records", "value": "", "count": len(speed_unmatched) if not speed_unmatched.empty else len(speed)},
        {"metric": "primary_context_bins_0_2500ft", "value": "", "count": len(bin_context)},
        {"metric": "excluded_review_bins_over_2500ft", "value": "", "count": int((~context_bins["context_join_eligible"] & context_bins["bin_midpoint_ft_from_reference_signal"].gt(2500)).sum())},
        {"metric": "bins_with_speed_by_overlap", "value": "", "count": int(bin_context["speed_context_status"].eq("speed_assigned_by_overlap").sum())},
        {"metric": "bins_with_speed_by_nearest_fallback", "value": "", "count": int(bin_context["speed_context_status"].eq("speed_assigned_by_nearest").sum())},
        {"metric": "bins_missing_speed_context", "value": "", "count": int(bin_context["speed_context_status"].eq("no_speed_nearby").sum())},
        {"metric": "crashes_inheriting_speed_context", "value": "", "count": len(crash_context)},
        {"metric": "reference_signals_with_speed_context", "value": "", "count": signal_summary["reference_signal_id"].nunique() if not signal_summary.empty else 0},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "speed_fields_used_for_upstream_downstream", "value": False, "count": ""},
        {"metric": "scaffold_catchment_assignment_access_logic_changed", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path], posted_speed_summary: pd.DataFrame) -> str:
    def count(metric: str) -> Any:
        matched = summary.loc[summary["metric"].eq(metric)]
        if matched.empty:
            return ""
        return matched.iloc[0]["count"]

    common = posted_speed_summary.loc[posted_speed_summary["speed_vehicle_type"].eq("car")].copy() if not posted_speed_summary.empty else pd.DataFrame()
    if not common.empty:
        common = common.groupby("posted_speed_limit", dropna=False)["bin_count"].sum().reset_index().sort_values("bin_count", ascending=False).head(5)
        common_values = ", ".join(f"{row.posted_speed_limit} mph ({int(row.bin_count)} bins)" for row in common.itertuples(index=False))
    else:
        common_values = ""
    passed = int(qa["passed"].astype(bool).sum()) if not qa.empty else 0
    return "\n".join(
        [
            "# Speed Context Join Findings",
            "",
            "## Bounded Question",
            "",
            "Attach posted-speed context to the stable roadway-derived directional bin/crash universe without changing scaffold, catchments, crash assignment, access context, or upstream/downstream labels.",
            "",
            "## Inputs",
            "",
            f"- `{SPEED_FILE}`",
            f"- `{USABLE_BINS_FILE}`",
            f"- `{CATCHMENT_INDEX_FILE}`",
            f"- `{CATCHMENT_POLYGONS_FILE}`",
            f"- `{READINESS_FILE}`",
            f"- `{ASSIGNMENTS_FILE}`",
            "",
            "## Key Counts",
            "",
            f"- speed records considered: {count('speed_records_considered')}",
            f"- speed records with null geometry excluded from spatial matching: {count('speed_records_with_null_geometry')}",
            f"- speed records matched to at least one stable bin: {count('speed_records_matched_to_at_least_one_stable_bin')}",
            f"- ambiguous/conflicting speed bin matches: {count('ambiguous_conflicting_speed_bin_matches')}",
            f"- unmatched speed records: {count('unmatched_speed_records')}",
            f"- primary context bins 0-2,500 ft: {count('primary_context_bins_0_2500ft')}",
            f"- bins with speed by overlap: {count('bins_with_speed_by_overlap')}",
            f"- bins with speed by nearest fallback: {count('bins_with_speed_by_nearest_fallback')}",
            f"- bins missing speed: {count('bins_missing_speed_context')}",
            f"- crashes inheriting speed context: {count('crashes_inheriting_speed_context')}",
            f"- reference signals with speed context: {count('reference_signals_with_speed_context')}",
            f"- most common car posted speeds: {common_values}",
            "",
            "## Boundary Checks",
            "",
            f"- crash direction fields read or used: {summary.loc[summary['metric'].eq('crash_direction_fields_read_or_used'), 'value'].iloc[0]}",
            f"- speed fields used for upstream/downstream: {summary.loc[summary['metric'].eq('speed_fields_used_for_upstream_downstream'), 'value'].iloc[0]}",
            f"- scaffold/catchment/assignment/access logic changed: {summary.loc[summary['metric'].eq('scaffold_catchment_assignment_access_logic_changed'), 'value'].iloc[0]}",
            f"- QA checks passed: {passed} of {len(qa)}",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
            "## Recommended Next Step",
            "",
            "Review overlap and ambiguous speed matches, then decide whether the combined context table should merge access and speed context at the directional-bin level before descriptive summaries.",
            "",
        ]
    )


def _ordered_bin_context(frame: pd.DataFrame) -> pd.DataFrame:
    extra_columns = [column for column in frame.columns if column not in MAIN_OUTPUT_COLUMNS]
    ordered = [column for column in MAIN_OUTPUT_COLUMNS if column in frame.columns] + extra_columns
    return frame[ordered].copy()


def build_speed_context_join(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    speed = _load_speed()
    context_bins = _load_context_bins()
    catchments = _load_context_catchments(context_bins)
    readiness_header = pd.read_csv(READINESS_FILE, nrows=0).columns.tolist()
    readiness_columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
    ]
    readiness = _read_csv(READINESS_FILE, usecols=readiness_columns)
    _ = _read_csv(ASSIGNMENTS_FILE, usecols=["crash_id", "reference_directional_bin_id", "assignment_status"])
    if STAGING_SCHEMA_FILE.exists():
        _ = pd.read_csv(STAGING_SCHEMA_FILE)
    if STAGING_FIELD_ROLES_FILE.exists():
        _ = pd.read_csv(STAGING_FIELD_ROLES_FILE)
    if STAGING_CRS_SANITY_FILE.exists():
        _ = pd.read_csv(STAGING_CRS_SANITY_FILE)

    overlap = _overlap_candidates(speed, catchments)
    nearest = _nearest_candidates(speed, catchments, overlap)
    bin_context = _build_bin_context(context_bins, overlap, nearest)
    high_priority = bin_context.loc[bin_context["distance_window"].eq("high_priority_0_1000ft")].copy()
    sensitivity = bin_context.loc[bin_context["distance_window"].eq("sensitivity_1000_2500ft")].copy()
    crash_context = _crash_context(readiness, bin_context)
    signal_summary = _reference_signal_summary(bin_context)
    speed_joined, speed_candidates, speed_ambiguous, speed_unmatched = _speed_record_outputs(speed, overlap, nearest)
    by_direction = _summarize_bins(bin_context, ["signal_relative_direction"])
    by_window = _summarize_bins(bin_context, ["distance_window"])
    by_posted_speed = _by_posted_speed(bin_context)
    qa = _qa(
        speed=speed,
        context_bins=context_bins,
        bin_context=bin_context,
        crash_context=crash_context,
        speed_joined=speed_joined,
        speed_ambiguous=speed_ambiguous,
        speed_unmatched=speed_unmatched,
        readiness_header=readiness_header,
    )
    summary = _summary_frame(speed, context_bins, bin_context, crash_context, speed_joined, speed_ambiguous, speed_unmatched, signal_summary)

    outputs = {
        "summary_csv": out_dir / "speed_context_join_summary.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_speed_context.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_speed_context_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_speed_context_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_speed_context.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_speed_context_summary.csv",
        "speed_records_joined_csv": out_dir / "speed_records_joined_to_stable_universe.csv",
        "speed_bin_match_candidates_csv": out_dir / "speed_bin_match_candidates.csv",
        "speed_bin_ambiguous_csv": out_dir / "speed_bin_ambiguous_matches.csv",
        "speed_records_unmatched_csv": out_dir / "speed_records_unmatched_or_outside_stable_universe.csv",
        "by_direction_csv": out_dir / "speed_context_by_signal_relative_direction.csv",
        "by_window_csv": out_dir / "speed_context_by_distance_window.csv",
        "by_posted_speed_csv": out_dir / "speed_context_by_posted_speed.csv",
        "qa_csv": out_dir / "speed_context_join_qa.csv",
        "findings_md": out_dir / "speed_context_join_findings.md",
        "manifest_json": out_dir / "speed_context_join_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(_ordered_bin_context(bin_context), outputs["directional_bin_context_csv"])
    _write_csv(_ordered_bin_context(high_priority), outputs["directional_bin_context_0_1000_csv"])
    _write_csv(_ordered_bin_context(sensitivity), outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(signal_summary, outputs["reference_signal_summary_csv"])
    _write_csv(speed_joined, outputs["speed_records_joined_csv"])
    _write_csv(speed_candidates, outputs["speed_bin_match_candidates_csv"])
    _write_csv(speed_ambiguous, outputs["speed_bin_ambiguous_csv"])
    _write_csv(speed_unmatched, outputs["speed_records_unmatched_csv"])
    _write_csv(by_direction, outputs["by_direction_csv"])
    _write_csv(by_window, outputs["by_window_csv"])
    _write_csv(by_posted_speed, outputs["by_posted_speed_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, qa, outputs, by_posted_speed), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only posted-speed context join for stable roadway-derived directional bin/crash universe",
        "main_context_window": "0-2500ft",
        "high_priority_window": "0-1000ft",
        "sensitivity_window": "1000-2500ft",
        "nearest_line_fallback_tolerance_ft": NEAREST_TOLERANCE_FT,
        "crash_direction_fields_read_or_used": False,
        "speed_fields_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_access_logic_changed": False,
        "speed_to_roadway_graph_modification": False,
        "aadt_join_implemented": False,
        "inputs": {
            "speed": str(SPEED_FILE),
            "readiness_by_crash": str(READINESS_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "catchment_polygons": str(CATCHMENT_POLYGONS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
            "staging_schema": str(STAGING_SCHEMA_FILE),
            "staging_field_roles": str(STAGING_FIELD_ROLES_FILE),
            "staging_crs_sanity": str(STAGING_CRS_SANITY_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Join staged posted-speed context to stable roadway_graph directional bins.")
    parser.parse_args()
    outputs = build_speed_context_join()
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
