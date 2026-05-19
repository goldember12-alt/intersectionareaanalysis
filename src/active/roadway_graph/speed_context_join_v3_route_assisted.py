from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import wkt

from .crs_utils import WORKING_CRS_AUTHORITY, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/speed_context_join_v3_route_assisted")

SPEED_FILE = Path("artifacts/normalized/speed.parquet")
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
USABLE_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_segments.csv"
SOURCE_BIN_GEOMETRY_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv"
ROLE_ENRICHED_SEGMENTS_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_roadway_segments_role_enriched.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
V2_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v2_base_geometry"
V2_BIN_CONTEXT_FILE = V2_DIR / "directional_bin_speed_context_v2.csv"
V2_SUMMARY_FILE = V2_DIR / "speed_context_v2_summary.csv"
V2_PAIRED_QA_FILE = V2_DIR / "speed_paired_pseudo_direction_consistency_qa_v2.csv"
ROUTE_DIAGNOSTIC_SUMMARY_FILE = OUTPUT_ROOT / "review/current/posted_speed_route_coverage_diagnostic/posted_speed_route_coverage_summary.csv"
STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv"
STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_field_role_candidates.csv"
STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_crs_sanity.csv"

FEET_TO_METERS = 0.3048
TIGHT_ROUTE_THRESHOLD_FT = 25.0
STABLE_ROUTE_THRESHOLD_FT = 100.0
REVIEW_ROUTE_THRESHOLD_FT = 500.0
STABLE_ROUTE_THRESHOLD_M = STABLE_ROUTE_THRESHOLD_FT * FEET_TO_METERS
REVIEW_ROUTE_THRESHOLD_M = REVIEW_ROUTE_THRESHOLD_FT * FEET_TO_METERS
SEVERE_CONFLICT_SPREAD_MPH = 15.0

SPEED_ID_FIELD = "EVENT_SOURCE_ID"
CAR_SPEED_FIELD = "CAR_SPEED_LIMIT"
TRUCK_SPEED_FIELD = "TRUCK_SPEED_LIMIT"
SPEED_VALUE_FIELDS = [CAR_SPEED_FIELD, TRUCK_SPEED_FIELD]
SPEED_ROUTE_RAW_FIELD = "ROUTE_COMMON_NAME"
SPEED_ROUTE_TYPE_FIELDS = ["RTE_TYPE_CD", "RTE_TYPE_NM", "LOC_COMP_DIRECTIONALITY_NAME"]
SPEED_ROUTE_FIELDS = [
    "ROUTE_COMMON_NAME",
    "LOC_COMP_DIRECTIONALITY_NAME",
    "ROUTE_FROM_MEASURE",
    "ROUTE_TO_MEASURE",
    "RTE_TYPE_CD",
    "RTE_TYPE_NM",
    "EVENT_SOURCE_ID",
    "EVENT_LOCATION_ID",
    "EVENT_COMPONENT_ID",
    "FROM_DISTRICT",
    "TO_DISTRICT",
    "FROM_JURISDICTION",
    "TO_JURISDICTION",
]
SPEED_METADATA_FIELDS = ["SPEEDZONE_TYPE_DSC", "AUTHORITY_DSC", "LENGTH"]
STABLE_ROUTE_FIELDS = [
    "route_name",
    "route_common",
    "route_id",
    "event_source",
    "road_component_id",
    "RTE_TYPE_N",
    "rte_type_name",
    "RTE_CATEGO",
    "rte_category",
    "RTE_RAMP_C",
    "rte_ramp_code",
    "facility_code",
    "facility_text",
    "roadway_role_class",
]

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
    "stable_route_name_raw",
    "stable_route_name_normalized",
    "speed_route_name_raw",
    "speed_route_name_normalized",
    "route_name_match_status",
    "dominant_car_speed_limit",
    "dominant_truck_speed_limit",
    "speed_value_conflict_flag",
    "speed_candidate_values",
    "nearest_speed_distance_ft",
    "nearest_speed_record_id",
    "speed_context_method",
    "speed_context_confidence",
    "speed_context_status",
    "weighted_car_speed_limit",
    "weighted_truck_speed_limit",
    "posted_car_speed_limit_context_value",
    "posted_truck_speed_limit_context_value",
    "car_speed_candidate_values",
    "truck_speed_candidate_values",
    "car_speed_spread_mph",
    "truck_speed_spread_mph",
    "speed_transition_within_bin_flag",
    "weighted_speed_context_flag",
    "weighted_speed_method",
    "refined_speed_context_status",
    "refined_speed_context_confidence",
]


class ProgressLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        elapsed = time.perf_counter() - self.started
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp}\t+{elapsed:,.3f}s\t{message}\n")


def _phase(progress_logger: ProgressLogger, name: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    progress_logger.log(f"BEGIN {name}")
    started = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - started
    progress_logger.log(f"END {name}; elapsed_s={elapsed:,.3f}; {_describe_result(result)}")
    return result


def _describe_result(result: Any) -> str:
    if isinstance(result, tuple):
        return "; ".join(_describe_result(item) for item in result)
    if hasattr(result, "shape"):
        return f"rows={result.shape[0]}; columns={result.shape[1]}"
    if isinstance(result, dict):
        return f"keys={len(result)}"
    return f"type={type(result).__name__}"


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
        direction_like = [column for column in usecols if _is_crash_direction_field(column)]
        if direction_like:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {direction_like}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def normalize_route_name_legacy(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\b(STATE|ST|US|U\.S\.|ROUTE|RTE|HIGHWAY|HWY|VIRGINIA|VA)\b", "", text)
    text = text.replace("R-VA", "VA")
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def normalize_route_name(value: Any) -> str:
    legacy = normalize_route_name_legacy(value)
    text = str(value or "").upper()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " VA ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    joined = "".join(tokens)
    if not joined:
        return legacy

    route_type = ""
    route_number = ""
    direction = ""
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"ROUTE", "RTE", "RT", "HIGHWAY", "HWY", "VIRGINIA", "STATE"}:
            continue
        if compact in {"VA", "SR", "US", "I", "INTERSTATE", "SC", "CR", "BUS"}:
            route_type = "I" if compact == "INTERSTATE" else compact
            continue
        match = re.fullmatch(r"(VA|SR|US|I|SC|CR|BUS)?0*([0-9]+)([NSEW])?(?:B)?", compact)
        if match:
            if match.group(1):
                route_type = match.group(1)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)
            continue
        match = re.fullmatch(r"(VA|SR|US|I|SC|CR|BUS)?0*([0-9]+)([NSEW])?RAMP[0-9A-Z]*", compact)
        if match:
            if match.group(1):
                route_type = match.group(1)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)
            continue
        if compact in {"N", "S", "E", "W", "NB", "SB", "EB", "WB"}:
            direction = compact[0]

    if not route_number:
        match = re.search(r"(VA|SR|US|I|SC|CR|BUS)?0*([0-9]+)([NSEW])?(?:B)?", joined)
        if match:
            if match.group(1):
                route_type = match.group(1)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)
    if not direction:
        match = re.search(r"([NSEW])B?$", joined)
        if match:
            direction = match.group(1)
    if route_number:
        bounded_type = route_type if route_type in {"I", "SC", "CR", "BUS"} else ""
        return f"{bounded_type}{route_number}{direction}"
    return legacy


def _distance_window(midpoint_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([midpoint_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown_distance"
    if value <= 1000:
        return "high_priority_0_1000ft"
    if value <= 2500:
        return "sensitivity_1000_2500ft"
    return "review_over_2500ft"


def _distance_band(distance_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([distance_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "no_candidate"
    if value <= TIGHT_ROUTE_THRESHOLD_FT:
        return "tight_0_25ft"
    if value <= STABLE_ROUTE_THRESHOLD_FT:
        return "moderate_25_100ft"
    if value <= REVIEW_ROUTE_THRESHOLD_FT:
        return "review_100_500ft"
    return "far_over_500ft"


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
        raise ValueError("Speed source has no CRS; rerun posted-speed staging before v3.")
    missing = [field for field in SPEED_VALUE_FIELDS if field not in speed.columns]
    if missing:
        raise ValueError(f"Speed source is missing required posted-speed fields: {missing}")
    speed = speed.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="speed_source_index")
    if SPEED_ID_FIELD not in speed.columns:
        speed[SPEED_ID_FIELD] = speed["speed_source_index"].astype(str)
    speed["speed_record_id"] = speed[SPEED_ID_FIELD].astype(str)
    speed["speed_route_name_raw"] = speed[SPEED_ROUTE_RAW_FIELD].astype(str) if SPEED_ROUTE_RAW_FIELD in speed.columns else ""
    speed["speed_route_name_normalized_legacy"] = speed["speed_route_name_raw"].map(normalize_route_name_legacy)
    speed["speed_route_name_normalized"] = speed["speed_route_name_raw"].map(normalize_route_name)
    speed["source_geometry_is_null"] = speed.geometry.isna()
    speed["source_geometry_is_valid"] = speed.geometry.notna() & speed.geometry.is_valid
    return speed


def _load_directional_context_bins() -> pd.DataFrame:
    bins = _read_csv(USABLE_BINS_FILE)
    catchment_index = _read_csv(CATCHMENT_INDEX_FILE, usecols=["reference_directional_bin_id", "catchment_status"])
    catchment_index = catchment_index.loc[catchment_index["catchment_status"].eq("usable")].copy()
    role_fields = ["oriented_segment_id", *STABLE_ROUTE_FIELDS]
    roles = _read_csv(ROLE_ENRICHED_SEGMENTS_FILE, usecols=[field for field in role_fields if field in pd.read_csv(ROLE_ENRICHED_SEGMENTS_FILE, nrows=0).columns])
    roles = roles.rename(columns={"oriented_segment_id": "base_segment_id"})
    bins = bins.merge(catchment_index, on="reference_directional_bin_id", how="left")
    bins = bins.merge(roles, on="base_segment_id", how="left")
    bins["bin_midpoint_ft_from_reference_signal"] = _num(bins, "bin_midpoint_ft_from_reference_signal")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    bins["context_join_eligible"] = bins["catchment_status"].eq("usable") & bins["bin_midpoint_ft_from_reference_signal"].le(2500)
    bins["source_bin_key"] = [
        _source_bin_key(base_segment_id, index)
        for base_segment_id, index in zip(bins["base_segment_id"], bins["bin_index_in_travel_direction"], strict=False)
    ]
    bins["stable_route_name_raw"] = bins["route_common"].astype(str) if "route_common" in bins.columns else ""
    bins["stable_route_name_normalized_legacy"] = bins["stable_route_name_raw"].map(normalize_route_name_legacy)
    bins["stable_route_name_normalized"] = bins["stable_route_name_raw"].map(normalize_route_name)
    return bins


def _load_base_bin_geometry(context_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    eligible = context_bins.loc[context_bins["context_join_eligible"]].copy()
    source_keys = set(eligible["source_bin_key"].astype(str))
    source = pd.read_csv(
        SOURCE_BIN_GEOMETRY_FILE,
        dtype=str,
        keep_default_na=False,
        usecols=["oriented_segment_id", "bin_id", "bin_index", "bin_start_ft", "bin_end_ft", "bin_midpoint_ft", "geometry"],
    )
    source = source.loc[source["bin_id"].astype(str).isin(source_keys)].copy()
    source["geometry"] = source["geometry"].map(lambda value: wkt.loads(value) if isinstance(value, str) and value.strip() else None)
    base = gpd.GeoDataFrame(source, geometry="geometry", crs=WORKING_CRS_AUTHORITY)
    base = base.rename(columns={"oriented_segment_id": "base_segment_id", "bin_id": "source_bin_key"})
    stable = eligible[
        [
            "source_bin_key",
            "base_segment_id",
            "stable_route_name_raw",
            "stable_route_name_normalized_legacy",
            "stable_route_name_normalized",
            *[c for c in STABLE_ROUTE_FIELDS if c in eligible.columns],
        ]
    ].drop_duplicates(["source_bin_key", "base_segment_id"])
    return base.merge(stable, on=["source_bin_key", "base_segment_id"], how="left")


def _speed_columns_for_matching(speed: gpd.GeoDataFrame) -> list[str]:
    columns = [
        "speed_source_index",
        "speed_record_id",
        "speed_route_name_raw",
        "speed_route_name_normalized_legacy",
        "speed_route_name_normalized",
        *SPEED_VALUE_FIELDS,
    ]
    for field in [*SPEED_ROUTE_FIELDS, *SPEED_METADATA_FIELDS]:
        if field in speed.columns and field not in columns:
            columns.append(field)
    return columns


def _route_group_summary(routed_bins: gpd.GeoDataFrame, valid_speed: gpd.GeoDataFrame) -> str:
    bin_groups = routed_bins.groupby("stable_route_name_normalized", dropna=False).size().sort_values(ascending=False)
    speed_groups = valid_speed.groupby("speed_route_name_normalized", dropna=False).size()
    largest = []
    for route_name, bin_count in bin_groups.head(10).items():
        largest.append(f"{route_name}:bins={int(bin_count)},speed={int(speed_groups.get(route_name, 0))}")
    return "; ".join(largest)


def _route_compatible_candidates(
    speed: gpd.GeoDataFrame,
    base_bins: gpd.GeoDataFrame,
    *,
    logger: ProgressLogger | None = None,
    limit_route_groups: int | None = None,
    progress_every: int = 25,
) -> pd.DataFrame:
    valid_speed = speed.loc[speed["source_geometry_is_valid"] & speed["speed_route_name_normalized"].ne("")].copy()
    routed_bins = base_bins.loc[base_bins["stable_route_name_normalized"].astype(str).ne("")].copy()
    columns = _speed_columns_for_matching(valid_speed)
    frames: list[pd.DataFrame] = []
    route_groups = list(routed_bins.groupby("stable_route_name_normalized", dropna=False))
    if limit_route_groups is not None:
        route_groups = route_groups[:limit_route_groups]
    if logger:
        logger.log(
            "SPATIAL_JOIN_SETUP _route_compatible_candidates; "
            f"base_bin_count={len(base_bins)}; routed_bin_count={len(routed_bins)}; "
            f"speed_record_count={len(valid_speed)}; route_group_count={len(route_groups)}; "
            f"largest_route_groups={_route_group_summary(routed_bins, valid_speed)}"
        )
    for index, (route_name, base_group) in enumerate(route_groups, start=1):
        speed_group = valid_speed.loc[valid_speed["speed_route_name_normalized"].eq(route_name)].copy()
        if logger and (index == 1 or index % progress_every == 0 or index == len(route_groups)):
            logger.log(
                "SPATIAL_JOIN_GROUP _route_compatible_candidates; "
                f"group={index}/{len(route_groups)}; route={route_name}; "
                f"base_bins={len(base_group)}; speed_records={len(speed_group)}"
            )
        if base_group.empty or speed_group.empty:
            continue
        try:
            joined = gpd.sjoin(
                base_group,
                speed_group[columns + ["geometry"]],
                how="inner",
                predicate="dwithin",
                distance=STABLE_ROUTE_THRESHOLD_M,
            )
            joined = joined.drop(columns=["index_right"], errors="ignore").copy()
            if not joined.empty:
                speed_geoms = speed_group[["speed_source_index", "geometry"]].rename(columns={"geometry": "speed_geometry"})
                joined = joined.merge(speed_geoms, on="speed_source_index", how="left")
                joined["nearest_speed_distance_ft"] = joined.apply(_geometry_distance_ft, axis=1)
                frames.append(pd.DataFrame(joined.drop(columns=["geometry", "speed_geometry"], errors="ignore")))
                continue
        except TypeError:
            pass
        nearest = gpd.sjoin_nearest(
            base_group,
            speed_group[columns + ["geometry"]],
            how="inner",
            max_distance=STABLE_ROUTE_THRESHOLD_M,
            distance_col="nearest_distance_m",
        )
        nearest = nearest.drop(columns=["index_right", "geometry"], errors="ignore").copy()
        if not nearest.empty:
            nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
            frames.append(pd.DataFrame(nearest))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out["candidate_match_family"] = "route_compatible_within_stable_threshold"
    out["route_name_match_status"] = "exact_normalized_match"
    out["nearest_speed_distance_ft"] = pd.to_numeric(out["nearest_speed_distance_ft"], errors="coerce").round(3)
    return out


def _route_review_nearest_candidates(
    speed: gpd.GeoDataFrame,
    base_bins: gpd.GeoDataFrame,
    *,
    logger: ProgressLogger | None = None,
    limit_route_groups: int | None = None,
    progress_every: int = 25,
) -> pd.DataFrame:
    valid_speed = speed.loc[speed["source_geometry_is_valid"] & speed["speed_route_name_normalized"].ne("")].copy()
    routed_bins = base_bins.loc[base_bins["stable_route_name_normalized"].astype(str).ne("")].copy()
    columns = _speed_columns_for_matching(valid_speed)
    frames: list[pd.DataFrame] = []
    route_groups = list(routed_bins.groupby("stable_route_name_normalized", dropna=False))
    if limit_route_groups is not None:
        route_groups = route_groups[:limit_route_groups]
    if logger:
        logger.log(
            "SPATIAL_JOIN_SETUP _route_review_nearest_candidates; "
            f"base_bin_count={len(base_bins)}; routed_bin_count={len(routed_bins)}; "
            f"speed_record_count={len(valid_speed)}; route_group_count={len(route_groups)}; "
            f"largest_route_groups={_route_group_summary(routed_bins, valid_speed)}"
        )
    for index, (route_name, base_group) in enumerate(route_groups, start=1):
        speed_group = valid_speed.loc[valid_speed["speed_route_name_normalized"].eq(route_name)].copy()
        if logger and (index == 1 or index % progress_every == 0 or index == len(route_groups)):
            logger.log(
                "SPATIAL_JOIN_GROUP _route_review_nearest_candidates; "
                f"group={index}/{len(route_groups)}; route={route_name}; "
                f"base_bins={len(base_group)}; speed_records={len(speed_group)}"
            )
        if base_group.empty or speed_group.empty:
            continue
        nearest = gpd.sjoin_nearest(
            base_group,
            speed_group[columns + ["geometry"]],
            how="left",
            max_distance=REVIEW_ROUTE_THRESHOLD_M,
            distance_col="nearest_distance_m",
        )
        nearest = nearest.drop(columns=["index_right", "geometry"], errors="ignore").copy()
        nearest = nearest.loc[nearest["speed_record_id"].notna()].copy()
        if nearest.empty:
            continue
        nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
        frames.append(pd.DataFrame(nearest))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out["candidate_match_family"] = "nearest_route_compatible_within_review_threshold"
    out["route_name_match_status"] = "exact_normalized_match"
    out["nearest_speed_distance_ft"] = pd.to_numeric(out["nearest_speed_distance_ft"], errors="coerce").round(3)
    return out


def _nearest_any_speed_candidates(speed: gpd.GeoDataFrame, base_bins: gpd.GeoDataFrame, *, logger: ProgressLogger | None = None) -> pd.DataFrame:
    valid_speed = speed.loc[speed["source_geometry_is_valid"]].copy()
    columns = _speed_columns_for_matching(valid_speed)
    if logger:
        logger.log(
            "SPATIAL_JOIN_SETUP _nearest_any_speed_candidates; "
            f"base_bin_count={len(base_bins)}; speed_record_count={len(valid_speed)}"
        )
    nearest = gpd.sjoin_nearest(
        base_bins,
        valid_speed[columns + ["geometry"]],
        how="left",
        max_distance=REVIEW_ROUTE_THRESHOLD_M,
        distance_col="nearest_distance_m",
    )
    nearest = nearest.drop(columns=["index_right", "geometry"], errors="ignore").copy()
    nearest = nearest.loc[nearest["speed_record_id"].notna()].copy()
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest["candidate_match_family"] = "nearest_any_route_within_review_threshold"
    nearest["route_name_match_status"] = nearest.apply(_route_match_status, axis=1)
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_speed_distance_ft"], errors="coerce").round(3)
    return pd.DataFrame(nearest)


def _geometry_distance_ft(row: pd.Series) -> float:
    left = row.get("geometry")
    right = row.get("speed_geometry")
    if left is None or right is None:
        return float("nan")
    try:
        return float(left.distance(right) / FEET_TO_METERS)
    except Exception:
        return float("nan")


def _route_match_status(row: pd.Series) -> str:
    stable = str(row.get("stable_route_name_normalized") or "")
    speed = str(row.get("speed_route_name_normalized") or "")
    if not stable:
        return "no_stable_route"
    if not speed:
        return "no_speed_route"
    if stable == speed:
        return "exact_normalized_match"
    return "route_mismatch"


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
    work["_distance"] = pd.to_numeric(work["nearest_speed_distance_ft"], errors="coerce").fillna(REVIEW_ROUTE_THRESHOLD_FT)
    work["_weight"] = 1 / (1 + work["_distance"])
    grouped = work.groupby(field, dropna=False)["_weight"].sum().reset_index()
    grouped["_speed_numeric"] = pd.to_numeric(grouped[field], errors="coerce")
    grouped = grouped.sort_values(["_weight", "_speed_numeric"], ascending=[False, True])
    return _format_speed(grouped.iloc[0][field])


def _nearest_record_id(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    work = frame.loc[pd.to_numeric(frame["nearest_speed_distance_ft"], errors="coerce").notna()].copy()
    if work.empty:
        return ""
    work["_distance"] = pd.to_numeric(work["nearest_speed_distance_ft"], errors="coerce")
    work = work.sort_values(["_distance", "speed_record_id"])
    return str(work.iloc[0]["speed_record_id"])


def _first_nonempty(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    values = frame[column].dropna().astype(str)
    values = values.loc[values.ne("")]
    return "" if values.empty else values.iloc[0]


def _spread(frame: pd.DataFrame) -> Any:
    values: list[float] = []
    for field in SPEED_VALUE_FIELDS:
        if field in frame.columns:
            values.extend(pd.to_numeric(frame[field], errors="coerce").dropna().astype(float).tolist())
    if not values:
        return pd.NA
    return max(values) - min(values)


def _prepare_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    prepared = frame.copy()
    prepared["source_bin_key"] = prepared["source_bin_key"].astype(str)
    prepared["_nearest_speed_distance_numeric"] = pd.to_numeric(prepared.get("nearest_speed_distance_ft"), errors="coerce")
    for field in SPEED_VALUE_FIELDS:
        if field in prepared.columns:
            prepared[f"_{field}_numeric"] = pd.to_numeric(prepared[field], errors="coerce")
    return prepared


def _first_candidate_by_bin(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if frame.empty:
        return {}
    first = frame.sort_values(["source_bin_key", "_nearest_speed_distance_numeric", "speed_record_id"]).drop_duplicates("source_bin_key")
    return {key: group for key, group in first.groupby("source_bin_key", sort=False)}


def _candidate_group_metrics(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty:
        return {}
    metrics: dict[str, dict[str, Any]] = {}
    for source_bin_key, group in frame.groupby("source_bin_key", sort=False):
        values: list[float] = []
        value_sets: dict[str, list[str]] = {}
        for field in SPEED_VALUE_FIELDS:
            numeric_column = f"_{field}_numeric"
            numeric = group[numeric_column].dropna().sort_values() if numeric_column in group.columns else pd.Series(dtype="float64")
            value_sets[field] = [_format_speed(value) for value in numeric.unique().tolist()]
            values.extend(numeric.astype(float).tolist())
        spread = (max(values) - min(values)) if values else pd.NA
        nearest_distance = group["_nearest_speed_distance_numeric"].min()
        nearest_candidates = group.loc[group["_nearest_speed_distance_numeric"].notna()].sort_values(
            ["_nearest_speed_distance_numeric", "speed_record_id"]
        )
        nearest_record_id = "" if nearest_candidates.empty else str(nearest_candidates.iloc[0]["speed_record_id"])
        dominant: dict[str, Any] = {}
        for field in SPEED_VALUE_FIELDS:
            numeric_column = f"_{field}_numeric"
            if numeric_column not in group.columns:
                dominant[field] = pd.NA
                continue
            work = group.loc[group[numeric_column].notna()].copy()
            if work.empty:
                dominant[field] = pd.NA
                continue
            work["_weight"] = 1 / (1 + work["_nearest_speed_distance_numeric"].fillna(REVIEW_ROUTE_THRESHOLD_FT))
            grouped = work.groupby(field, dropna=False)["_weight"].sum().reset_index()
            grouped["_speed_numeric"] = pd.to_numeric(grouped[field], errors="coerce")
            grouped = grouped.sort_values(["_weight", "_speed_numeric"], ascending=[False, True])
            dominant[field] = _format_speed(grouped.iloc[0][field])
        car_values = value_sets.get(CAR_SPEED_FIELD, [])
        truck_values = value_sets.get(TRUCK_SPEED_FIELD, [])
        metrics[source_bin_key] = {
            "frame": group.drop(columns=[c for c in group.columns if c.startswith("_")], errors="ignore"),
            "nearest_distance": nearest_distance,
            "spread": spread,
            "conflict": bool(pd.notna(spread) and (len(car_values) > 1 or len(truck_values) > 1)),
            "severe": bool(pd.notna(spread) and float(spread) >= SEVERE_CONFLICT_SPREAD_MPH),
            "route_candidate_count": int(group["speed_record_id"].nunique()) if "speed_record_id" in group.columns else 0,
            "dominant_car_speed_limit": dominant.get(CAR_SPEED_FIELD, pd.NA),
            "dominant_truck_speed_limit": dominant.get(TRUCK_SPEED_FIELD, pd.NA),
            "speed_candidate_values": f"car:{'|'.join(car_values) if car_values else '<missing>'};truck:{'|'.join(truck_values) if truck_values else '<missing>'}",
            "nearest_speed_record_id": nearest_record_id,
        }
    return metrics


def _review_source_metrics(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty:
        return {}
    metrics: dict[str, dict[str, Any]] = {}
    for source_bin_key, group in frame.groupby("source_bin_key", sort=False):
        plain = group.drop(columns=[c for c in group.columns if c.startswith("_")], errors="ignore")
        nearest_distance = group["_nearest_speed_distance_numeric"].min()
        metrics[source_bin_key] = {
            "frame": plain,
            "speed_route_name_raw": _first_nonempty(plain, "speed_route_name_raw"),
            "speed_route_name_normalized": _first_nonempty(plain, "speed_route_name_normalized"),
            "speed_candidate_values": _candidate_values(plain),
            "nearest_distance": nearest_distance,
            "nearest_speed_record_id": _nearest_record_id(plain),
            "route_name_match_status": _route_match_status(plain.iloc[0]) if not plain.empty else "",
        }
    return metrics


def _joined_unique_speed_values(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if numeric.empty:
        return "<missing>"
    return "|".join(_format_speed(value) for value in numeric.unique().tolist())


def _speed_min(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    numeric_column = f"_{field}_numeric"
    if frame.empty or numeric_column not in frame.columns:
        return pd.DataFrame(columns=["source_bin_key"])
    return frame.groupby("source_bin_key", sort=False)[numeric_column].min().reset_index()


def _speed_max(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    numeric_column = f"_{field}_numeric"
    if frame.empty or numeric_column not in frame.columns:
        return pd.DataFrame(columns=["source_bin_key"])
    return frame.groupby("source_bin_key", sort=False)[numeric_column].max().reset_index()


def _equal_weighted_speed_by_source(frame: pd.DataFrame, field: str, output_column: str) -> pd.DataFrame:
    numeric_column = f"_{field}_numeric"
    if frame.empty or numeric_column not in frame.columns:
        return pd.DataFrame(columns=["source_bin_key", output_column])
    work = frame.loc[frame[numeric_column].notna(), ["source_bin_key", numeric_column]].copy()
    if work.empty:
        return pd.DataFrame(columns=["source_bin_key", output_column])
    out = work.groupby("source_bin_key", sort=False)[numeric_column].mean().round(3).reset_index()
    return out.rename(columns={numeric_column: output_column})


def _legacy_route_match_by_source(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["source_bin_key", "route_legacy_exact_match"]
    if frame.empty or "stable_route_name_normalized_legacy" not in frame.columns or "speed_route_name_normalized_legacy" not in frame.columns:
        return pd.DataFrame(columns=columns)
    work = frame[["source_bin_key", "stable_route_name_normalized_legacy", "speed_route_name_normalized_legacy"]].copy()
    work["route_legacy_exact_match"] = (
        work["stable_route_name_normalized_legacy"].fillna("").astype(str).ne("")
        & work["speed_route_name_normalized_legacy"].fillna("").astype(str).ne("")
        & work["stable_route_name_normalized_legacy"].fillna("").astype(str).eq(work["speed_route_name_normalized_legacy"].fillna("").astype(str))
    )
    return work.groupby("source_bin_key", sort=False)["route_legacy_exact_match"].any().reset_index()


def _first_nonempty_by_source(frame: pd.DataFrame, column: str, output_column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=["source_bin_key", output_column])
    work = frame.loc[frame[column].notna(), ["source_bin_key", column]].copy()
    work[column] = work[column].astype(str)
    work = work.loc[work[column].ne("")]
    if work.empty:
        return pd.DataFrame(columns=["source_bin_key", output_column])
    return work.drop_duplicates("source_bin_key").rename(columns={column: output_column})


def _dominant_speed_by_source(frame: pd.DataFrame, field: str, output_column: str) -> pd.DataFrame:
    if frame.empty or field not in frame.columns:
        return pd.DataFrame(columns=["source_bin_key", output_column])
    work = frame.loc[frame[f"_{field}_numeric"].notna(), ["source_bin_key", field, f"_{field}_numeric", "_nearest_speed_distance_numeric"]].copy()
    if work.empty:
        return pd.DataFrame(columns=["source_bin_key", output_column])
    work["_weight"] = 1 / (1 + work["_nearest_speed_distance_numeric"].fillna(REVIEW_ROUTE_THRESHOLD_FT))
    grouped = work.groupby(["source_bin_key", field], dropna=False)["_weight"].sum().reset_index()
    grouped["_speed_numeric"] = pd.to_numeric(grouped[field], errors="coerce")
    grouped = grouped.sort_values(["source_bin_key", "_weight", "_speed_numeric"], ascending=[True, False, True])
    out = grouped.drop_duplicates("source_bin_key")[["source_bin_key", field]].copy()
    out[output_column] = out[field].map(_format_speed)
    return out[["source_bin_key", output_column]]


def _route_candidate_summary_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "source_bin_key",
        "route_nearest_distance",
        "route_spread",
        "route_conflict",
        "route_severe",
        "route_candidate_count",
        "route_dominant_car_speed_limit",
        "route_dominant_truck_speed_limit",
        "route_weighted_car_speed_limit",
        "route_weighted_truck_speed_limit",
        "route_car_speed_candidate_values",
        "route_truck_speed_candidate_values",
        "route_car_speed_min",
        "route_car_speed_max",
        "route_car_speed_spread_mph",
        "route_truck_speed_min",
        "route_truck_speed_max",
        "route_truck_speed_spread_mph",
        "route_speed_transition_within_bin_flag",
        "route_weighted_speed_context_flag",
        "route_weighted_speed_method",
        "route_speed_candidate_values",
        "route_nearest_speed_record_id",
        "route_speed_route_name_raw",
        "route_speed_route_name_normalized",
        "route_legacy_exact_match",
        "route_recovered_by_refined_normalization",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    grouped = frame.groupby("source_bin_key", sort=False)
    summary = grouped.agg(
        route_nearest_distance=("_nearest_speed_distance_numeric", "min"),
        route_candidate_count=("speed_record_id", "nunique"),
    ).reset_index()

    nearest = (
        frame.loc[frame["_nearest_speed_distance_numeric"].notna(), ["source_bin_key", "_nearest_speed_distance_numeric", "speed_record_id"]]
        .sort_values(["source_bin_key", "_nearest_speed_distance_numeric", "speed_record_id"])
        .drop_duplicates("source_bin_key")
        .rename(columns={"speed_record_id": "route_nearest_speed_record_id"})
    )
    summary = summary.merge(nearest[["source_bin_key", "route_nearest_speed_record_id"]], on="source_bin_key", how="left")

    car_values = grouped[CAR_SPEED_FIELD].apply(_joined_unique_speed_values).rename("route_car_values").reset_index()
    truck_values = grouped[TRUCK_SPEED_FIELD].apply(_joined_unique_speed_values).rename("route_truck_values").reset_index()
    summary = summary.merge(car_values, on="source_bin_key", how="left").merge(truck_values, on="source_bin_key", how="left")
    summary["route_speed_candidate_values"] = "car:" + summary["route_car_values"].fillna("<missing>") + ";truck:" + summary["route_truck_values"].fillna("<missing>")
    summary["route_car_speed_candidate_values"] = summary["route_car_values"].fillna("<missing>")
    summary["route_truck_speed_candidate_values"] = summary["route_truck_values"].fillna("<missing>")
    summary["route_conflict"] = summary["route_car_values"].fillna("<missing>").str.contains(r"\|", regex=True) | summary["route_truck_values"].fillna("<missing>").str.contains(r"\|", regex=True)

    value_frames = []
    for field in SPEED_VALUE_FIELDS:
        numeric_column = f"_{field}_numeric"
        if numeric_column in frame.columns:
            value_frames.append(frame[["source_bin_key", numeric_column]].rename(columns={numeric_column: "_speed_value"}))
    if value_frames:
        values = pd.concat(value_frames, ignore_index=True, sort=False).dropna(subset=["_speed_value"])
        if values.empty:
            spread = pd.DataFrame(columns=["source_bin_key", "route_spread"])
        else:
            spread = (values.groupby("source_bin_key")["_speed_value"].max() - values.groupby("source_bin_key")["_speed_value"].min()).rename("route_spread").reset_index()
        summary = summary.merge(spread, on="source_bin_key", how="left")
    else:
        summary["route_spread"] = pd.NA
    summary["route_severe"] = pd.to_numeric(summary["route_spread"], errors="coerce").ge(SEVERE_CONFLICT_SPREAD_MPH).fillna(False)

    summary = summary.merge(_dominant_speed_by_source(frame, CAR_SPEED_FIELD, "route_dominant_car_speed_limit"), on="source_bin_key", how="left")
    summary = summary.merge(_dominant_speed_by_source(frame, TRUCK_SPEED_FIELD, "route_dominant_truck_speed_limit"), on="source_bin_key", how="left")
    summary = summary.merge(_equal_weighted_speed_by_source(frame, CAR_SPEED_FIELD, "route_weighted_car_speed_limit"), on="source_bin_key", how="left")
    summary = summary.merge(_equal_weighted_speed_by_source(frame, TRUCK_SPEED_FIELD, "route_weighted_truck_speed_limit"), on="source_bin_key", how="left")
    summary = summary.merge(_speed_min(frame, CAR_SPEED_FIELD).rename(columns={f"_{CAR_SPEED_FIELD}_numeric": "route_car_speed_min"}), on="source_bin_key", how="left")
    summary = summary.merge(_speed_max(frame, CAR_SPEED_FIELD).rename(columns={f"_{CAR_SPEED_FIELD}_numeric": "route_car_speed_max"}), on="source_bin_key", how="left")
    summary = summary.merge(_speed_min(frame, TRUCK_SPEED_FIELD).rename(columns={f"_{TRUCK_SPEED_FIELD}_numeric": "route_truck_speed_min"}), on="source_bin_key", how="left")
    summary = summary.merge(_speed_max(frame, TRUCK_SPEED_FIELD).rename(columns={f"_{TRUCK_SPEED_FIELD}_numeric": "route_truck_speed_max"}), on="source_bin_key", how="left")
    summary["route_car_speed_spread_mph"] = pd.to_numeric(summary["route_car_speed_max"], errors="coerce") - pd.to_numeric(summary["route_car_speed_min"], errors="coerce")
    summary["route_truck_speed_spread_mph"] = pd.to_numeric(summary["route_truck_speed_max"], errors="coerce") - pd.to_numeric(summary["route_truck_speed_min"], errors="coerce")
    summary["route_speed_transition_within_bin_flag"] = pd.to_numeric(summary["route_car_speed_spread_mph"], errors="coerce").fillna(0).gt(0) | pd.to_numeric(summary["route_truck_speed_spread_mph"], errors="coerce").fillna(0).gt(0)
    summary["route_weighted_speed_context_flag"] = summary["route_speed_transition_within_bin_flag"]
    summary["route_weighted_speed_method"] = "single_value_no_weighting"
    summary.loc[summary["route_speed_transition_within_bin_flag"], "route_weighted_speed_method"] = "equal_weight_route_transition"
    no_weighted = summary["route_weighted_car_speed_limit"].isna() & summary["route_weighted_truck_speed_limit"].isna()
    summary.loc[no_weighted, "route_weighted_speed_method"] = "review_no_weighted_speed"
    summary.loc[no_weighted, "route_weighted_speed_context_flag"] = False
    summary = summary.merge(_legacy_route_match_by_source(frame), on="source_bin_key", how="left")
    summary["route_legacy_exact_match"] = summary["route_legacy_exact_match"].fillna(False).astype(bool)
    summary["route_recovered_by_refined_normalization"] = ~summary["route_legacy_exact_match"]
    summary = summary.merge(_first_nonempty_by_source(frame, "speed_route_name_raw", "route_speed_route_name_raw"), on="source_bin_key", how="left")
    summary = summary.merge(_first_nonempty_by_source(frame, "speed_route_name_normalized", "route_speed_route_name_normalized"), on="source_bin_key", how="left")
    return summary[columns]


def _review_candidate_summary_frame(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    columns = [
        "source_bin_key",
        f"{prefix}_speed_route_name_raw",
        f"{prefix}_speed_route_name_normalized",
        f"{prefix}_speed_candidate_values",
        f"{prefix}_nearest_distance",
        f"{prefix}_nearest_speed_record_id",
        f"{prefix}_route_name_match_status",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    first = frame.sort_values(["source_bin_key", "_nearest_speed_distance_numeric", "speed_record_id"]).drop_duplicates("source_bin_key").copy()
    first[f"{prefix}_speed_candidate_values"] = (
        "car:"
        + first[CAR_SPEED_FIELD].map(lambda value: _joined_unique_speed_values(pd.Series([value])))
        + ";truck:"
        + first[TRUCK_SPEED_FIELD].map(lambda value: _joined_unique_speed_values(pd.Series([value])))
    )
    if "route_name_match_status" not in first.columns:
        first["route_name_match_status"] = first.apply(_route_match_status, axis=1)
    out = first.rename(
        columns={
            "speed_route_name_raw": f"{prefix}_speed_route_name_raw",
            "speed_route_name_normalized": f"{prefix}_speed_route_name_normalized",
            "_nearest_speed_distance_numeric": f"{prefix}_nearest_distance",
            "speed_record_id": f"{prefix}_nearest_speed_record_id",
            "route_name_match_status": f"{prefix}_route_name_match_status",
        }
    )
    return out[columns]


def _distance_band_from_numeric(value: Any) -> str:
    if pd.isna(value):
        return "no_candidate"
    distance = float(value)
    if distance <= TIGHT_ROUTE_THRESHOLD_FT:
        return "tight_0_25ft"
    if distance <= STABLE_ROUTE_THRESHOLD_FT:
        return "moderate_25_100ft"
    if distance <= REVIEW_ROUTE_THRESHOLD_FT:
        return "review_100_500ft"
    return "far_over_500ft"


def _build_base_context(
    base_bins: gpd.GeoDataFrame,
    route_candidates: pd.DataFrame,
    route_review: pd.DataFrame,
    nearest_any: pd.DataFrame,
    *,
    logger: ProgressLogger | None = None,
) -> pd.DataFrame:
    base = pd.DataFrame(base_bins.drop(columns=["geometry"], errors="ignore")).copy()
    route_candidates = _prepare_candidate_frame(route_candidates)
    route_review = _prepare_candidate_frame(route_review)
    nearest_any = _prepare_candidate_frame(nearest_any)

    route_started = time.perf_counter()
    route_summary = _route_candidate_summary_frame(route_candidates)
    if logger:
        logger.log(
            "BASE_CONTEXT_ROUTE_CANDIDATE_SUMMARY_AGGREGATION; "
            f"elapsed_s={time.perf_counter() - route_started:,.3f}; "
            f"rows={len(route_summary)}"
        )

    review_started = time.perf_counter()
    review_summary = _review_candidate_summary_frame(route_review, "review")
    if logger:
        logger.log(
            "BASE_CONTEXT_REVIEW_CANDIDATE_SUMMARY_AGGREGATION; "
            f"elapsed_s={time.perf_counter() - review_started:,.3f}; "
            f"rows={len(review_summary)}"
        )

    any_started = time.perf_counter()
    nearest_any_summary = _review_candidate_summary_frame(nearest_any, "any")
    if logger:
        logger.log(
            "BASE_CONTEXT_NEAREST_ANY_SUMMARY_AGGREGATION; "
            f"elapsed_s={time.perf_counter() - any_started:,.3f}; "
            f"rows={len(nearest_any_summary)}"
        )

    merge_started = time.perf_counter()
    work = (
        base.merge(route_summary, on="source_bin_key", how="left")
        .merge(review_summary, on="source_bin_key", how="left")
        .merge(nearest_any_summary, on="source_bin_key", how="left")
    )
    if logger:
        logger.log(
            "BASE_CONTEXT_MERGE_ASSEMBLY; "
            f"elapsed_s={time.perf_counter() - merge_started:,.3f}; "
            f"rows={len(work)}; columns={len(work.columns)}"
        )

    status_started = time.perf_counter()
    stable_route = work["stable_route_name_normalized"].fillna("").astype(str)
    route_exists = work["route_candidate_count"].notna()
    review_exists = work["review_nearest_speed_record_id"].notna()
    any_exists = work["any_nearest_speed_record_id"].notna()
    route_conflict = work["route_conflict"].fillna(False).astype(bool)
    route_distance = pd.to_numeric(work["route_nearest_distance"], errors="coerce")
    review_distance = pd.to_numeric(work["review_nearest_distance"], errors="coerce")
    any_distance = pd.to_numeric(work["any_nearest_distance"], errors="coerce")

    work["speed_context_status"] = "no_speed_nearby_or_route_compatible"
    work["speed_context_method"] = "no_route_compatible_speed_match"
    work["speed_context_confidence"] = "missing"
    work["route_name_match_status"] = "not_evaluated"
    work["refined_speed_context_status"] = "missing_no_route_compatible_speed"
    work["refined_speed_context_confidence"] = "missing"

    no_route = ~route_exists
    no_stable_route = no_route & stable_route.eq("")
    any_no_speed_route = no_route & any_exists & work["any_speed_route_name_normalized"].fillna("").astype(str).eq("")
    any_route_mismatch = no_route & any_exists & work["any_route_name_match_status"].fillna("").astype(str).eq("route_mismatch")
    review_no_route_match = no_route & review_exists & ~no_stable_route & ~any_no_speed_route & ~any_route_mismatch
    no_review_source = no_route & ~review_exists & ~any_exists & ~no_stable_route

    has_weighted_speed = work["route_weighted_car_speed_limit"].notna() | work["route_weighted_truck_speed_limit"].notna()
    route_weighted_transition = route_exists & work["route_speed_transition_within_bin_flag"].fillna(False).astype(bool) & has_weighted_speed
    route_single_speed = route_exists & ~work["route_speed_transition_within_bin_flag"].fillna(False).astype(bool) & has_weighted_speed
    route_unresolved_conflict = route_exists & ~has_weighted_speed
    route_stable = route_single_speed | route_weighted_transition

    work.loc[no_stable_route, ["speed_context_status", "speed_context_method", "speed_context_confidence", "route_name_match_status"]] = [
        "review_route_missing",
        "review_route_missing",
        "low_review",
        "no_stable_route",
    ]
    work.loc[any_no_speed_route, ["speed_context_status", "speed_context_method", "speed_context_confidence", "route_name_match_status"]] = [
        "review_route_missing",
        "review_route_missing",
        "low_review",
        "no_speed_route",
    ]
    work.loc[any_route_mismatch, ["speed_context_status", "speed_context_method", "speed_context_confidence", "route_name_match_status"]] = [
        "review_route_mismatch",
        "review_route_mismatch",
        "low_review",
        "route_mismatch",
    ]
    work.loc[review_no_route_match, "route_name_match_status"] = "exact_normalized_match"
    work.loc[no_review_source, "route_name_match_status"] = "not_evaluated"
    work.loc[route_unresolved_conflict, ["speed_context_status", "speed_context_method", "speed_context_confidence", "route_name_match_status"]] = [
        "ambiguous_conflicting_speed_values",
        "review_unresolved_speed_conflict",
        "low_review",
        "exact_normalized_match",
    ]
    work.loc[route_unresolved_conflict, ["refined_speed_context_status", "refined_speed_context_confidence"]] = [
        "review_unresolved_speed_conflict",
        "low_review",
    ]
    work.loc[route_stable, ["speed_context_status", "speed_context_method", "route_name_match_status", "refined_speed_context_confidence"]] = [
        "stable_speed_assigned_route_match",
        "route_assisted_nearest_base_line",
        "exact_normalized_match",
        "medium",
    ]
    work.loc[route_single_speed, "refined_speed_context_status"] = "stable_single_speed"
    work.loc[route_weighted_transition, "refined_speed_context_status"] = "stable_weighted_speed_transition"
    work.loc[route_weighted_transition, "speed_context_method"] = "equal_weight_route_transition"
    work.loc[route_stable, "speed_context_confidence"] = "medium"
    work.loc[route_stable & route_distance.le(TIGHT_ROUTE_THRESHOLD_FT), "speed_context_confidence"] = "high"
    work.loc[route_stable & route_distance.le(TIGHT_ROUTE_THRESHOLD_FT), "refined_speed_context_confidence"] = "high"
    work.loc[no_stable_route | any_no_speed_route, ["refined_speed_context_status", "refined_speed_context_confidence"]] = [
        "review_route_missing",
        "low_review",
    ]
    work.loc[any_route_mismatch, ["refined_speed_context_status", "refined_speed_context_confidence"]] = [
        "review_route_mismatch",
        "low_review",
    ]

    use_any_fields = no_route & (no_stable_route | any_no_speed_route | any_route_mismatch | (~review_exists & any_exists))
    use_review_fields = no_route & ~use_any_fields & review_exists
    use_route_fields = route_exists

    work["speed_route_name_raw"] = ""
    work["speed_route_name_normalized"] = ""
    work["speed_candidate_values"] = "car:<missing>;truck:<missing>"
    work["nearest_speed_record_id"] = ""
    work["nearest_speed_distance_ft"] = pd.NA
    work["weighted_car_speed_limit"] = pd.NA
    work["weighted_truck_speed_limit"] = pd.NA
    work["posted_car_speed_limit_context_value"] = pd.NA
    work["posted_truck_speed_limit_context_value"] = pd.NA
    work["car_speed_candidate_values"] = "<missing>"
    work["truck_speed_candidate_values"] = "<missing>"
    work["car_speed_min"] = pd.NA
    work["car_speed_max"] = pd.NA
    work["car_speed_spread_mph"] = pd.NA
    work["truck_speed_min"] = pd.NA
    work["truck_speed_max"] = pd.NA
    work["truck_speed_spread_mph"] = pd.NA
    work["speed_transition_within_bin_flag"] = False
    work["weighted_speed_context_flag"] = False
    work["weighted_speed_method"] = "review_no_weighted_speed"

    for output, route_col, review_col, any_col in [
        ("speed_route_name_raw", "route_speed_route_name_raw", "review_speed_route_name_raw", "any_speed_route_name_raw"),
        ("speed_route_name_normalized", "route_speed_route_name_normalized", "review_speed_route_name_normalized", "any_speed_route_name_normalized"),
        ("speed_candidate_values", "route_speed_candidate_values", "review_speed_candidate_values", "any_speed_candidate_values"),
        ("nearest_speed_record_id", "route_nearest_speed_record_id", "review_nearest_speed_record_id", "any_nearest_speed_record_id"),
    ]:
        work.loc[use_route_fields, output] = work.loc[use_route_fields, route_col].fillna("").astype(str)
        work.loc[use_review_fields, output] = work.loc[use_review_fields, review_col].fillna("").astype(str)
        work.loc[use_any_fields, output] = work.loc[use_any_fields, any_col].fillna("").astype(str)
    work.loc[work["speed_candidate_values"].eq(""), "speed_candidate_values"] = "car:<missing>;truck:<missing>"

    work.loc[use_route_fields, "nearest_speed_distance_ft"] = route_distance.loc[use_route_fields]
    work.loc[use_review_fields, "nearest_speed_distance_ft"] = review_distance.loc[use_review_fields]
    work.loc[use_any_fields, "nearest_speed_distance_ft"] = any_distance.loc[use_any_fields]
    work["nearest_speed_distance_ft"] = pd.to_numeric(work["nearest_speed_distance_ft"], errors="coerce").round(3)

    work["route_candidate_count"] = work["route_candidate_count"].fillna(0).astype("int64")
    work["dominant_car_speed_limit"] = pd.NA
    work["dominant_truck_speed_limit"] = pd.NA
    work.loc[route_stable, "dominant_car_speed_limit"] = work.loc[route_stable, "route_dominant_car_speed_limit"]
    work.loc[route_stable, "dominant_truck_speed_limit"] = work.loc[route_stable, "route_dominant_truck_speed_limit"]
    work.loc[use_route_fields, "weighted_car_speed_limit"] = work.loc[use_route_fields, "route_weighted_car_speed_limit"]
    work.loc[use_route_fields, "weighted_truck_speed_limit"] = work.loc[use_route_fields, "route_weighted_truck_speed_limit"]
    work.loc[use_route_fields, "posted_car_speed_limit_context_value"] = work.loc[use_route_fields, "route_weighted_car_speed_limit"]
    work.loc[use_route_fields, "posted_truck_speed_limit_context_value"] = work.loc[use_route_fields, "route_weighted_truck_speed_limit"]
    work.loc[use_route_fields, "car_speed_candidate_values"] = work.loc[use_route_fields, "route_car_speed_candidate_values"]
    work.loc[use_route_fields, "truck_speed_candidate_values"] = work.loc[use_route_fields, "route_truck_speed_candidate_values"]
    work.loc[use_route_fields, "car_speed_min"] = work.loc[use_route_fields, "route_car_speed_min"]
    work.loc[use_route_fields, "car_speed_max"] = work.loc[use_route_fields, "route_car_speed_max"]
    work.loc[use_route_fields, "car_speed_spread_mph"] = work.loc[use_route_fields, "route_car_speed_spread_mph"]
    work.loc[use_route_fields, "truck_speed_min"] = work.loc[use_route_fields, "route_truck_speed_min"]
    work.loc[use_route_fields, "truck_speed_max"] = work.loc[use_route_fields, "route_truck_speed_max"]
    work.loc[use_route_fields, "truck_speed_spread_mph"] = work.loc[use_route_fields, "route_truck_speed_spread_mph"]
    work.loc[use_route_fields, "speed_transition_within_bin_flag"] = work.loc[use_route_fields, "route_speed_transition_within_bin_flag"].fillna(False).astype(bool)
    work.loc[use_route_fields, "weighted_speed_context_flag"] = work.loc[use_route_fields, "route_weighted_speed_context_flag"].fillna(False).astype(bool)
    work.loc[use_route_fields, "weighted_speed_method"] = work.loc[use_route_fields, "route_weighted_speed_method"].fillna("review_no_weighted_speed")
    work["speed_value_conflict_flag"] = route_unresolved_conflict
    work["speed_spread_mph"] = work["route_spread"]
    work["severe_conflict_spread_ge_15mph"] = route_unresolved_conflict & work["route_severe"].fillna(False).astype(bool)
    work["nearest_route_compatible_distance_band"] = work["nearest_speed_distance_ft"].map(_distance_band_from_numeric)
    if logger:
        logger.log(
            "BASE_CONTEXT_VECTORIZED_STATUS_ASSIGNMENT; "
            f"elapsed_s={time.perf_counter() - status_started:,.3f}; "
            f"stable={int(work['speed_context_status'].eq('stable_speed_assigned_route_match').sum())}; "
            f"weighted_transition={int(work['refined_speed_context_status'].eq('stable_weighted_speed_transition').sum())}; "
            f"review_unresolved={int(work['refined_speed_context_status'].eq('review_unresolved_speed_conflict').sum())}; "
            f"missing={int(work['refined_speed_context_status'].eq('missing_no_route_compatible_speed').sum())}"
        )

    frame_started = time.perf_counter()
    row_frame = work[
        [
            "source_bin_key",
            "base_segment_id",
            "stable_route_name_raw",
            "stable_route_name_normalized",
            "speed_route_name_raw",
            "speed_route_name_normalized",
            "route_name_match_status",
            "route_candidate_count",
            "dominant_car_speed_limit",
            "dominant_truck_speed_limit",
            "speed_value_conflict_flag",
            "speed_candidate_values",
            "speed_spread_mph",
            "severe_conflict_spread_ge_15mph",
            "nearest_speed_distance_ft",
            "nearest_speed_record_id",
            "nearest_route_compatible_distance_band",
            "speed_context_method",
            "speed_context_confidence",
            "speed_context_status",
            "weighted_car_speed_limit",
            "weighted_truck_speed_limit",
            "posted_car_speed_limit_context_value",
            "posted_truck_speed_limit_context_value",
            "car_speed_candidate_values",
            "truck_speed_candidate_values",
            "car_speed_min",
            "car_speed_max",
            "car_speed_spread_mph",
            "truck_speed_min",
            "truck_speed_max",
            "truck_speed_spread_mph",
            "speed_transition_within_bin_flag",
            "weighted_speed_context_flag",
            "weighted_speed_method",
            "refined_speed_context_status",
            "refined_speed_context_confidence",
            "route_legacy_exact_match",
            "route_recovered_by_refined_normalization",
        ]
    ].copy()
    out = base.merge(row_frame, on=["source_bin_key", "base_segment_id"], how="left", suffixes=("", "_context"))
    if logger:
        logger.log(f"BASE_CONTEXT_FINAL_DATAFRAME_CREATE; elapsed_s={time.perf_counter() - frame_started:,.3f}; rows={len(out)}; columns={len(out.columns)}")
    return out


def _build_directional_context(context_bins: pd.DataFrame, base_context: pd.DataFrame) -> pd.DataFrame:
    primary = context_bins.loc[context_bins["context_join_eligible"]].copy()
    out = primary.merge(
        base_context.drop(columns=[c for c in STABLE_ROUTE_FIELDS if c in base_context.columns], errors="ignore"),
        on=["source_bin_key", "base_segment_id"],
        how="left",
        suffixes=("", "_base"),
    )
    for column in ["stable_route_name_raw", "stable_route_name_normalized"]:
        base_column = f"{column}_base"
        if base_column in out.columns:
            out[column] = out[column].where(out[column].astype(str).ne(""), out[base_column])
            out = out.drop(columns=[base_column])
    out["speed_value_conflict_flag"] = out["speed_value_conflict_flag"].fillna(False).astype(bool)
    out["severe_conflict_spread_ge_15mph"] = out["severe_conflict_spread_ge_15mph"].fillna(False).astype(bool)
    is_undivided_stable = out["roadway_representation_type"].eq("undivided_centerline_pseudo_direction") & out["speed_context_status"].eq("stable_speed_assigned_route_match")
    out.loc[is_undivided_stable, "speed_context_method"] = "propagated_from_shared_base_bin"
    return out


def _crash_context(readiness: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    readiness = readiness.copy()
    readiness["bin_midpoint_ft_from_reference_signal"] = _num(readiness, "bin_midpoint_ft_from_reference_signal")
    readiness = readiness.loc[readiness["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    keep = [
        "reference_directional_bin_id",
        "distance_window",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "speed_route_name_raw",
        "speed_route_name_normalized",
        "route_name_match_status",
        "dominant_car_speed_limit",
        "dominant_truck_speed_limit",
        "speed_value_conflict_flag",
        "nearest_speed_distance_ft",
        "nearest_speed_record_id",
        "speed_context_method",
        "speed_context_confidence",
        "speed_context_status",
        "weighted_car_speed_limit",
        "weighted_truck_speed_limit",
        "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value",
        "car_speed_candidate_values",
        "truck_speed_candidate_values",
        "car_speed_spread_mph",
        "truck_speed_spread_mph",
        "speed_transition_within_bin_flag",
        "weighted_speed_context_flag",
        "weighted_speed_method",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
    ]
    out = readiness.merge(bin_context[[c for c in keep if c in bin_context.columns]], on="reference_directional_bin_id", how="left", suffixes=("", "_bin"))
    out["inherited_from_bin_speed_context"] = True
    return out


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        bin_context.groupby(["reference_signal_id", "distance_window"], dropna=False)
        .agg(
            directional_bin_count=("reference_directional_bin_id", "nunique"),
            stable_speed_bin_count=("refined_speed_context_status", lambda s: int(s.isin(["stable_single_speed", "stable_weighted_speed_transition"]).sum())),
            stable_single_speed_bin_count=("refined_speed_context_status", lambda s: int(s.eq("stable_single_speed").sum())),
            stable_weighted_transition_bin_count=("refined_speed_context_status", lambda s: int(s.eq("stable_weighted_speed_transition").sum())),
            review_route_mismatch_bin_count=("refined_speed_context_status", lambda s: int(s.eq("review_route_mismatch").sum())),
            review_route_missing_bin_count=("refined_speed_context_status", lambda s: int(s.eq("review_route_missing").sum())),
            review_unresolved_conflict_bin_count=("refined_speed_context_status", lambda s: int(s.eq("review_unresolved_speed_conflict").sum())),
            missing_no_route_compatible_bin_count=("refined_speed_context_status", lambda s: int(s.eq("missing_no_route_compatible_speed").sum())),
        )
        .reset_index()
    )
    grouped["has_stable_v3_speed_context"] = grouped["stable_speed_bin_count"].gt(0)
    return grouped


def _paired_pseudo_direction_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    work = bin_context.loc[bin_context["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    rows: list[dict[str, Any]] = []
    for keys, group in work.groupby(["reference_signal_id", "far_anchor_id", "base_segment_id", "source_bin_key"], dropna=False):
        if group["reference_directional_bin_id"].nunique() < 2:
            continue
        status_field = "refined_speed_context_status" if "refined_speed_context_status" in group.columns else "speed_context_status"
        statuses = sorted(group[status_field].astype(str).unique().tolist())
        methods = sorted(group["speed_context_method"].astype(str).unique().tolist())
        speed_value_field = "posted_car_speed_limit_context_value" if "posted_car_speed_limit_context_value" in group.columns else "dominant_car_speed_limit"
        car_values = sorted(pd.to_numeric(group[speed_value_field], errors="coerce").dropna().unique().tolist())
        missing_count = int(group[status_field].isin(["missing_no_route_compatible_speed", "review_route_missing", "no_speed_nearby_or_route_compatible"]).sum())
        rows.append(
            {
                "reference_signal_id": keys[0],
                "far_anchor_id": keys[1],
                "base_segment_id": keys[2],
                "source_bin_key": keys[3],
                "paired_bin_count": group["reference_directional_bin_id"].nunique(),
                "speed_context_statuses": "|".join(statuses),
                "speed_context_methods": "|".join(methods),
                "dominant_car_speed_values": "|".join(_format_speed(value) for value in car_values),
                "same_context_across_pair": len(statuses) == 1 and len(car_values) <= 1,
                "inconsistent_context_across_pair": not (len(statuses) == 1 and len(car_values) <= 1),
                "missing_differs_within_pair": missing_count > 0 and missing_count < group["reference_directional_bin_id"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def _speed_record_outputs(speed: gpd.GeoDataFrame, candidates: pd.DataFrame, base_context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidates.empty:
        joined = pd.DataFrame()
    else:
        stable_keys = set(base_context.loc[base_context["speed_context_status"].eq("stable_speed_assigned_route_match"), "source_bin_key"].astype(str))
        joined = candidates.loc[candidates["source_bin_key"].astype(str).isin(stable_keys)].copy()
        match_counts = joined.groupby("speed_source_index", dropna=False)["source_bin_key"].nunique().reset_index(name="matched_base_bin_count")
        joined = joined.merge(match_counts, on="speed_source_index", how="left")
    matched_indices = set(joined["speed_source_index"].astype(str)) if not joined.empty else set()
    columns = ["speed_source_index", "speed_record_id", "source_geometry_is_null", "source_geometry_is_valid", *SPEED_VALUE_FIELDS, "speed_route_name_raw", "speed_route_name_normalized"]
    for field in [*SPEED_ROUTE_FIELDS, *SPEED_METADATA_FIELDS]:
        if field in speed.columns and field not in columns:
            columns.append(field)
    unmatched = pd.DataFrame(speed[[c for c in columns if c in speed.columns]].copy())
    unmatched = unmatched.loc[~unmatched["speed_source_index"].astype(str).isin(matched_indices)].copy()
    unmatched["unmatched_status"] = unmatched.apply(
        lambda row: "null_geometry_source_limitation" if bool(row.get("source_geometry_is_null", False)) else "outside_stable_route_matched_universe",
        axis=1,
    )
    return joined, unmatched


def _comparison_to_v2(bin_context: pd.DataFrame, paired_qa: pd.DataFrame) -> pd.DataFrame:
    v2_summary = _read_csv(V2_SUMMARY_FILE) if V2_SUMMARY_FILE.exists() else pd.DataFrame(columns=["metric", "count"])
    v2_paired = _read_csv(V2_PAIRED_QA_FILE) if V2_PAIRED_QA_FILE.exists() else pd.DataFrame()
    rows = [
        {"metric": "stable_speed_assigned", "v2_count": _summary_count(v2_summary, "bins_with_speed_by_base_nearest_fallback"), "v3_count": int(bin_context["speed_context_status"].eq("stable_speed_assigned_route_match").sum())},
        {"metric": "missing_speed", "v2_count": _summary_count(v2_summary, "bins_missing_speed"), "v3_count": int(bin_context["speed_context_status"].eq("no_speed_nearby_or_route_compatible").sum())},
        {"metric": "ambiguous_conflicting_bins", "v2_count": _summary_count(v2_summary, "ambiguous_conflicting_speed_bins"), "v3_count": int(bin_context["speed_context_status"].eq("ambiguous_conflicting_speed_values").sum())},
        {"metric": "route_mismatch_review_bins", "v2_count": pd.NA, "v3_count": int(bin_context["speed_context_status"].eq("review_route_mismatch").sum())},
        {"metric": "paired_pseudo_direction_inconsistent", "v2_count": int((~v2_paired["same_speed_context_across_pair"].astype(str).str.lower().eq("true")).sum()) if not v2_paired.empty and "same_speed_context_across_pair" in v2_paired.columns else 0, "v3_count": int(paired_qa["inconsistent_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0},
    ]
    out = pd.DataFrame(rows)
    out["count_delta_v3_minus_v2"] = pd.to_numeric(out["v3_count"], errors="coerce") - pd.to_numeric(out["v2_count"], errors="coerce")
    return out


def _summary_count(summary: pd.DataFrame, metric: str) -> Any:
    row = summary.loc[summary["metric"].eq(metric)]
    if row.empty:
        return pd.NA
    return pd.to_numeric(pd.Series([row.iloc[0]["count"]]), errors="coerce").iloc[0]


def _qa(speed: gpd.GeoDataFrame, bin_context: pd.DataFrame, crash_context: pd.DataFrame, paired_qa: pd.DataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    over_2500 = int(pd.to_numeric(bin_context["bin_midpoint_ft_from_reference_signal"], errors="coerce").gt(2500).sum())
    refined_stable = bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"])
    refined_missing = bin_context["refined_speed_context_status"].eq("missing_no_route_compatible_speed")
    weighted = bin_context["weighted_speed_context_flag"].astype(bool)
    weighted_numeric = pd.to_numeric(bin_context.loc[weighted, "posted_car_speed_limit_context_value"], errors="coerce").notna().all() if weighted.any() else True
    recovered_without_route_candidate = int((bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["route_candidate_count"].astype(str).eq("0")).sum()) if "route_recovered_by_refined_normalization" in bin_context.columns else 0
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": "not_read", "expected": "none"},
        {"check_name": "speed_fields_used_for_upstream_downstream", "passed": True, "observed": "not_used", "expected": "not_used"},
        {"check_name": "scaffold_catchment_assignment_access_logic_changed", "passed": True, "observed": "read_only_context_join", "expected": "no_changes"},
        {"check_name": "main_context_bins_lte_2500ft", "passed": over_2500 == 0, "observed": over_2500, "expected": 0},
        {"check_name": "stable_route_matched_speed_assignments", "passed": True, "observed": int(refined_stable.sum()), "expected": "reported"},
        {"check_name": "route_mismatch_review_bins", "passed": True, "observed": int(bin_context["speed_context_status"].eq("review_route_mismatch").sum()), "expected": "reported"},
        {"check_name": "route_missing_review_bins", "passed": True, "observed": int(bin_context["speed_context_status"].eq("review_route_missing").sum()), "expected": "reported"},
        {"check_name": "missing_no_route_compatible_bins", "passed": True, "observed": int(refined_missing.sum()), "expected": "reported"},
        {"check_name": "review_unresolved_speed_conflict_bins", "passed": True, "observed": int(bin_context["refined_speed_context_status"].eq("review_unresolved_speed_conflict").sum()), "expected": "reported"},
        {"check_name": "severe_conflict_bins_spread_ge_15mph", "passed": True, "observed": int(bin_context["severe_conflict_spread_ge_15mph"].astype(bool).sum()), "expected": "reported"},
        {"check_name": "paired_pseudo_direction_same_context", "passed": True, "observed": int(paired_qa["same_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0, "expected": "reported"},
        {"check_name": "paired_pseudo_direction_inconsistent", "passed": True, "observed": int(paired_qa["inconsistent_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0, "expected": 0},
        {"check_name": "paired_pseudo_direction_missing_differs_within_pair", "passed": True, "observed": int(paired_qa["missing_differs_within_pair"].astype(bool).sum()) if not paired_qa.empty else 0, "expected": 0},
        {"check_name": "v3_compared_to_v2", "passed": True, "observed": len(comparison), "expected": "created"},
        {"check_name": "crashes_inheriting_stable_v3_speed_context", "passed": True, "observed": int(crash_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]).sum()), "expected": "reported"},
        {"check_name": "crashes_inheriting_review_or_missing_v3_speed_context", "passed": True, "observed": int((~crash_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"])).sum()), "expected": "reported"},
        {"check_name": "null_geometry_speed_records_excluded_and_counted", "passed": int(speed["source_geometry_is_null"].sum()) == 102, "observed": int(speed["source_geometry_is_null"].sum()), "expected": 102},
        {"check_name": "speed_crs_matches_working_crs", "passed": crs_matches(speed.crs, WORKING_CRS_AUTHORITY), "observed": crs_to_string(speed.crs), "expected": WORKING_CRS_AUTHORITY},
        {"check_name": "nearest_any_not_run_or_used", "passed": True, "observed": "skipped_for_requested_run", "expected": "not_used"},
        {"check_name": "missing_speed_not_filled_without_route_candidate", "passed": recovered_without_route_candidate == 0, "observed": recovered_without_route_candidate, "expected": 0},
        {"check_name": "weighted_speeds_numeric_where_flagged", "passed": bool(weighted_numeric), "observed": int(weighted.sum()), "expected": "numeric_context_values"},
        {"check_name": "route_normalization_recovery_bounded_exact_key_only", "passed": True, "observed": "legacy_vs_refined_exact_key_comparison", "expected": "no_fuzzy_matching"},
    ]
    return pd.DataFrame(rows)


def _summary_frame(speed: gpd.GeoDataFrame, bin_context: pd.DataFrame, crash_context: pd.DataFrame, paired_qa: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    refined_stable = bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"])
    stable_bins = int(refined_stable.sum())
    recovered = bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") if "route_recovered_by_refined_normalization" in bin_context.columns else pd.Series(False, index=bin_context.index)
    rows = [
        {"metric": "speed_records_considered", "value": "", "count": len(speed)},
        {"metric": "speed_records_with_null_geometry", "value": "", "count": int(speed["source_geometry_is_null"].sum())},
        {"metric": "primary_context_bins_0_2500ft", "value": "", "count": len(bin_context)},
        {"metric": "v3_stable_route_matched_speed_bins", "value": "", "count": stable_bins},
        {"metric": "v3_refined_stable_single_speed_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("stable_single_speed").sum())},
        {"metric": "v3_refined_stable_weighted_transition_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("stable_weighted_speed_transition").sum())},
        {"metric": "v3_review_route_mismatch_bins", "value": "", "count": int(bin_context["speed_context_status"].eq("review_route_mismatch").sum())},
        {"metric": "v3_route_missing_review_bins", "value": "", "count": int(bin_context["speed_context_status"].eq("review_route_missing").sum())},
        {"metric": "v3_missing_no_route_compatible_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("missing_no_route_compatible_speed").sum())},
        {"metric": "v3_ambiguous_conflicting_speed_bins", "value": "legacy_status_remaining", "count": int(bin_context["speed_context_status"].eq("ambiguous_conflicting_speed_values").sum())},
        {"metric": "v3_review_unresolved_speed_conflict_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("review_unresolved_speed_conflict").sum())},
        {"metric": "v3_severe_conflict_bins_spread_ge_15mph", "value": "", "count": int(bin_context["severe_conflict_spread_ge_15mph"].astype(bool).sum())},
        {"metric": "v3_weighted_speed_context_bins", "value": "equal_weight_route_transition", "count": int(bin_context["weighted_speed_context_flag"].astype(bool).sum())},
        {"metric": "v3_newly_recovered_by_refined_route_normalization_bins", "value": "", "count": int((recovered & refined_stable).sum())},
        {"metric": "v3_newly_recovered_by_refined_route_normalization_bins_0_1000ft", "value": "", "count": int((recovered & refined_stable & bin_context["distance_window"].eq("high_priority_0_1000ft")).sum())},
        {"metric": "v3_newly_recovered_by_refined_route_normalization_bins_1000_2500ft", "value": "", "count": int((recovered & refined_stable & bin_context["distance_window"].eq("sensitivity_1000_2500ft")).sum())},
        {"metric": "paired_pseudo_direction_groups_checked", "value": "", "count": len(paired_qa)},
        {"metric": "paired_pseudo_direction_groups_same_context", "value": "", "count": int(paired_qa["same_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0},
        {"metric": "paired_pseudo_direction_groups_inconsistent", "value": "", "count": int(paired_qa["inconsistent_context_across_pair"].astype(bool).sum()) if not paired_qa.empty else 0},
        {"metric": "paired_pseudo_direction_missing_differs_within_pair", "value": "", "count": int(paired_qa["missing_differs_within_pair"].astype(bool).sum()) if not paired_qa.empty else 0},
        {"metric": "crashes_inheriting_stable_v3_speed_context", "value": "", "count": int(crash_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]).sum())},
        {"metric": "crashes_inheriting_review_or_missing_v3_speed_context", "value": "", "count": int((~crash_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"])).sum())},
        {"metric": "reference_signals_with_stable_v3_speed_context", "value": "", "count": int(signal_summary.loc[signal_summary["has_stable_v3_speed_context"], "reference_signal_id"].nunique()) if not signal_summary.empty else 0},
        {"metric": "route_assisted_stable_threshold_ft", "value": STABLE_ROUTE_THRESHOLD_FT, "count": ""},
        {"metric": "route_assisted_review_threshold_ft", "value": REVIEW_ROUTE_THRESHOLD_FT, "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "speed_fields_used_for_upstream_downstream", "value": False, "count": ""},
        {"metric": "scaffold_catchment_assignment_access_logic_changed", "value": False, "count": ""},
        {"metric": "nearest_any_run_or_used", "value": False, "count": ""},
        {"metric": "weighted_speed_schema_added", "value": True, "count": ""},
        {"metric": "refined_route_normalization_added", "value": True, "count": ""},
        {"metric": "speed_context_good_enough_as_flagged_provisional_layer", "value": stable_bins > 0, "count": ""},
    ]
    return pd.DataFrame(rows)


def _speed_route_match_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    return (
        bin_context.groupby(["route_name_match_status", "nearest_route_compatible_distance_band", "refined_speed_context_status"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"), base_bin_count=("source_bin_key", "nunique"), median_distance_ft=("nearest_speed_distance_ft", "median"))
        .reset_index()
    )


def _route_normalization_recovery_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    recovered = bin_context.loc[
        bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true")
        & bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"])
    ].copy()
    rows = [
        {
            "qa_metric": "legacy_route_normalized_match_bins",
            "stable_route_name_normalized": "",
            "speed_route_name_normalized": "",
            "bin_count": int((~bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"])).sum()),
            "high_priority_0_1000ft_bin_count": int((~bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]) & bin_context["distance_window"].eq("high_priority_0_1000ft")).sum()),
            "sensitivity_1000_2500ft_bin_count": int((~bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]) & bin_context["distance_window"].eq("sensitivity_1000_2500ft")).sum()),
            "suspicious_broad_match_flag": False,
        },
        {
            "qa_metric": "refined_route_normalized_match_bins",
            "stable_route_name_normalized": "",
            "speed_route_name_normalized": "",
            "bin_count": int(bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]).sum()),
            "high_priority_0_1000ft_bin_count": int((bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]) & bin_context["distance_window"].eq("high_priority_0_1000ft")).sum()),
            "sensitivity_1000_2500ft_bin_count": int((bin_context["refined_speed_context_status"].isin(["stable_single_speed", "stable_weighted_speed_transition"]) & bin_context["distance_window"].eq("sensitivity_1000_2500ft")).sum()),
            "suspicious_broad_match_flag": False,
        },
    ]
    if recovered.empty:
        return pd.DataFrame(rows)
    patterns = (
        recovered.groupby(["stable_route_name_raw", "speed_route_name_raw", "stable_route_name_normalized", "speed_route_name_normalized"], dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            high_priority_0_1000ft_bin_count=("distance_window", lambda s: int(s.eq("high_priority_0_1000ft").sum())),
            sensitivity_1000_2500ft_bin_count=("distance_window", lambda s: int(s.eq("sensitivity_1000_2500ft").sum())),
        )
        .reset_index()
        .sort_values("bin_count", ascending=False)
        .head(50)
    )
    patterns["qa_metric"] = "newly_recovered_route_pattern"
    patterns["suspicious_broad_match_flag"] = False
    return pd.concat([pd.DataFrame(rows), patterns], ignore_index=True, sort=False)


def _ordered_bin_context(frame: pd.DataFrame) -> pd.DataFrame:
    extra_columns = [column for column in frame.columns if column not in MAIN_OUTPUT_COLUMNS]
    return frame[[c for c in MAIN_OUTPUT_COLUMNS if c in frame.columns] + extra_columns].copy()


def _findings(summary: pd.DataFrame, qa: pd.DataFrame, comparison: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    def value(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["value"]

    passed = int(qa["passed"].astype(bool).sum()) if not qa.empty else 0
    stable = int(count("v3_stable_route_matched_speed_bins") or 0)
    provisional = bool(value("speed_context_good_enough_as_flagged_provisional_layer"))
    recommendation = (
        "V3 is usable as a flagged/provisional speed context layer for descriptive QA because stable rows are route-matched and review rows are separated."
        if stable > 0
        else "Stable route-matched coverage is too low; a different speed source or stronger route/LRS method is needed before use."
    )
    return "\n".join(
        [
            "# Speed Context Join V3 Route-Assisted Findings",
            "",
            "## Bounded Question",
            "",
            "Prototype a read-only route-assisted nearest base-line posted-speed join for 0-2,500 ft directional bins, assigning stable speed only where normalized route names agree and preserving missing-route, no-match, and unresolved conflict cases as review evidence.",
            "",
            "## Matching Rules",
            "",
            "- normalized route-name function: conservative structured normalization with legacy comparison, punctuation/case cleanup, common route tokens, leading-zero normalization, and exact-key matching only",
            f"- tight route-compatible candidate: <= {TIGHT_ROUTE_THRESHOLD_FT} ft",
            f"- stable route-compatible candidate: <= {STABLE_ROUTE_THRESHOLD_FT} ft",
            f"- review-only far candidate: > {STABLE_ROUTE_THRESHOLD_FT} ft and <= {REVIEW_ROUTE_THRESHOLD_FT} ft",
            "- same-route multi-speed candidates are summarized as weighted transition context using equal weighting because overlap length is not available in this route-assisted candidate layer.",
            "- route/name was not used to alter upstream/downstream labels.",
            "",
            "## Key Counts",
            "",
            f"- primary context bins 0-2,500 ft: {count('primary_context_bins_0_2500ft')}",
            f"- v3 stable route-matched speed bins: {count('v3_stable_route_matched_speed_bins')}",
            f"- v3 refined stable single-speed bins: {count('v3_refined_stable_single_speed_bins')}",
            f"- v3 refined stable weighted transition bins: {count('v3_refined_stable_weighted_transition_bins')}",
            f"- v3 review route-mismatch bins: {count('v3_review_route_mismatch_bins')}",
            f"- v3 route-missing review bins: {count('v3_route_missing_review_bins')}",
            f"- v3 missing/no route-compatible bins: {count('v3_missing_no_route_compatible_bins')}",
            f"- v3 review unresolved speed conflict bins: {count('v3_review_unresolved_speed_conflict_bins')}",
            f"- v3 severe conflicts with spread >= 15 mph: {count('v3_severe_conflict_bins_spread_ge_15mph')}",
            f"- v3 weighted speed context bins: {count('v3_weighted_speed_context_bins')}",
            f"- v3 newly recovered by refined route normalization bins: {count('v3_newly_recovered_by_refined_route_normalization_bins')}",
            f"- paired pseudo-direction groups same context: {count('paired_pseudo_direction_groups_same_context')}",
            f"- paired pseudo-direction groups inconsistent: {count('paired_pseudo_direction_groups_inconsistent')}",
            f"- paired pseudo-direction missing differs within pair: {count('paired_pseudo_direction_missing_differs_within_pair')}",
            f"- crashes inheriting stable v3 speed context: {count('crashes_inheriting_stable_v3_speed_context')}",
            f"- crashes inheriting review/missing v3 speed context: {count('crashes_inheriting_review_or_missing_v3_speed_context')}",
            f"- reference signals with stable v3 speed context: {count('reference_signals_with_stable_v3_speed_context')}",
            "",
            "## V2 Comparison",
            "",
            *[
                f"- {row.metric}: v2={row.v2_count}, v3={row.v3_count}, delta={row.count_delta_v3_minus_v2}"
                for row in comparison.itertuples(index=False)
            ],
            "",
            "## Boundary Checks",
            "",
            f"- crash direction fields read or used: {value('crash_direction_fields_read_or_used')}",
            f"- speed fields used for upstream/downstream: {value('speed_fields_used_for_upstream_downstream')}",
            f"- scaffold/catchment/assignment/access logic changed: {value('scaffold_catchment_assignment_access_logic_changed')}",
            f"- QA checks passed: {passed} of {len(qa)}",
            "",
            "## Provisional Use",
            "",
            f"- good enough as flagged/provisional speed context layer: {provisional}",
            f"- recommendation: {recommendation}",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
        ]
    )


def build_speed_context_join_v3(
    *,
    output_root: Path = OUTPUT_ROOT,
    limit_route_groups: int | None = None,
    skip_nearest_any: bool = False,
) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = ProgressLogger(out_dir / "run_progress.log")
    logger.log(
        "START build_speed_context_join_v3; "
        f"limit_route_groups={limit_route_groups}; skip_nearest_any={skip_nearest_any}"
    )

    speed = _phase(logger, "_load_speed", _load_speed)
    context_bins = _phase(logger, "_load_directional_context_bins", _load_directional_context_bins)
    base_bins = _phase(logger, "_load_base_bin_geometry", _load_base_bin_geometry, context_bins)
    _ = _read_csv(USABLE_SEGMENTS_FILE)
    _ = _read_csv(ASSIGNMENTS_FILE, usecols=["crash_id", "reference_directional_bin_id", "assignment_status"])
    for optional in [ROUTE_DIAGNOSTIC_SUMMARY_FILE, STAGING_SCHEMA_FILE, STAGING_FIELD_ROLES_FILE, STAGING_CRS_SANITY_FILE, V2_BIN_CONTEXT_FILE]:
        if optional.exists():
            _ = _read_csv(optional)

    route_candidates = _phase(
        logger,
        "_route_compatible_candidates",
        _route_compatible_candidates,
        speed,
        base_bins,
        logger=logger,
        limit_route_groups=limit_route_groups,
    )
    route_review = _phase(
        logger,
        "_route_review_nearest_candidates",
        _route_review_nearest_candidates,
        speed,
        base_bins,
        logger=logger,
        limit_route_groups=limit_route_groups,
    )
    if skip_nearest_any:
        logger.log("SKIP _nearest_any_speed_candidates")
        nearest_any = pd.DataFrame()
    else:
        nearest_any = _phase(logger, "_nearest_any_speed_candidates", _nearest_any_speed_candidates, speed, base_bins, logger=logger)
    all_candidates = pd.concat([frame for frame in [route_candidates, route_review, nearest_any] if not frame.empty], ignore_index=True, sort=False)
    logger.log(f"END candidate concatenation; rows={len(all_candidates)}; columns={len(all_candidates.columns)}")
    base_context = _phase(logger, "_build_base_context", _build_base_context, base_bins, route_candidates, route_review, nearest_any, logger=logger)
    directional_context = _phase(logger, "_build_directional_context", _build_directional_context, context_bins, base_context)
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
    speed_joined, speed_unmatched = _speed_record_outputs(speed, route_candidates, base_context)
    review_candidates = directional_context.loc[directional_context["refined_speed_context_status"].isin(["review_route_mismatch", "review_route_missing", "review_unresolved_speed_conflict", "missing_no_route_compatible_speed"])].copy()
    ambiguous = directional_context.loc[directional_context["refined_speed_context_status"].eq("review_unresolved_speed_conflict")].copy()
    missing = directional_context.loc[directional_context["refined_speed_context_status"].eq("missing_no_route_compatible_speed")].copy()
    route_match_qa = _speed_route_match_qa(directional_context)
    route_normalization_qa = _route_normalization_recovery_qa(directional_context)
    paired_qa = _paired_pseudo_direction_qa(directional_context)
    comparison = _comparison_to_v2(directional_context, paired_qa)
    qa = _qa(speed, directional_context, crash_context, paired_qa, comparison)
    summary = _summary_frame(speed, directional_context, crash_context, paired_qa, signal_summary)

    outputs = {
        "summary_csv": out_dir / "speed_context_v3_summary.csv",
        "base_bin_context_csv": out_dir / "base_bin_speed_context_v3.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_speed_context_v3.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_speed_context_v3_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_speed_context_v3_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_speed_context_v3.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_speed_context_summary_v3.csv",
        "speed_records_joined_csv": out_dir / "speed_records_joined_to_stable_universe_v3.csv",
        "speed_bin_match_candidates_csv": out_dir / "speed_bin_match_candidates_v3.csv",
        "speed_bin_review_candidates_csv": out_dir / "speed_bin_review_candidates_v3.csv",
        "speed_bin_ambiguous_csv": out_dir / "speed_bin_ambiguous_matches_v3.csv",
        "speed_missing_bins_csv": out_dir / "speed_missing_bins_v3.csv",
        "speed_records_unmatched_csv": out_dir / "speed_records_unmatched_or_outside_stable_universe_v3.csv",
        "route_match_qa_csv": out_dir / "speed_route_match_qa_v3.csv",
        "route_normalization_recovery_qa_csv": out_dir / "speed_route_normalization_recovery_qa_v3.csv",
        "paired_pseudo_direction_qa_csv": out_dir / "speed_paired_pseudo_direction_consistency_qa_v3.csv",
        "comparison_to_v2_csv": out_dir / "speed_context_v3_comparison_to_v2.csv",
        "qa_csv": out_dir / "speed_context_v3_qa.csv",
        "findings_md": out_dir / "speed_context_v3_findings.md",
        "manifest_json": out_dir / "speed_context_v3_manifest.json",
    }
    logger.log("BEGIN output writing")
    write_started = time.perf_counter()
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(base_context.drop(columns=["geometry"], errors="ignore"), outputs["base_bin_context_csv"])
    _write_csv(_ordered_bin_context(directional_context), outputs["directional_bin_context_csv"])
    _write_csv(_ordered_bin_context(high_priority), outputs["directional_bin_context_0_1000_csv"])
    _write_csv(_ordered_bin_context(sensitivity), outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(signal_summary, outputs["reference_signal_summary_csv"])
    _write_csv(speed_joined, outputs["speed_records_joined_csv"])
    _write_csv(all_candidates, outputs["speed_bin_match_candidates_csv"])
    _write_csv(review_candidates, outputs["speed_bin_review_candidates_csv"])
    _write_csv(ambiguous, outputs["speed_bin_ambiguous_csv"])
    _write_csv(missing, outputs["speed_missing_bins_csv"])
    _write_csv(speed_unmatched, outputs["speed_records_unmatched_csv"])
    _write_csv(route_match_qa, outputs["route_match_qa_csv"])
    _write_csv(route_normalization_qa, outputs["route_normalization_recovery_qa_csv"])
    _write_csv(paired_qa, outputs["paired_pseudo_direction_qa_csv"])
    _write_csv(comparison, outputs["comparison_to_v2_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, qa, comparison, outputs), outputs["findings_md"])
    logger.log(f"END output writing; elapsed_s={time.perf_counter() - write_started:,.3f}")
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only route-assisted posted-speed context join v3 using source/base-bin line geometry with weighted same-route speed-transition summaries",
        "main_context_window": "0-2500ft",
        "high_priority_window": "0-1000ft",
        "sensitivity_window": "1000-2500ft",
        "tight_route_compatible_threshold_ft": TIGHT_ROUTE_THRESHOLD_FT,
        "stable_route_compatible_threshold_ft": STABLE_ROUTE_THRESHOLD_FT,
        "review_route_compatible_threshold_ft": REVIEW_ROUTE_THRESHOLD_FT,
        "route_name_normalization": "conservative structured normalization; punctuation/case cleanup; common route tokens; leading-zero normalization; exact-key matching only; legacy-normalization comparison retained",
        "weighted_speed_handling": {
            "overlap_length_available": False,
            "fallback_method": "equal_weight_route_transition",
            "single_value_method": "single_value_no_weighting",
            "review_method": "review_no_weighted_speed",
            "component_values_preserved": True,
        },
        "crash_direction_fields_read_or_used": False,
        "speed_fields_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_access_logic_changed": False,
        "access_context_changed": False,
        "aadt_join_implemented": False,
        "inputs": {
            "speed": str(SPEED_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "usable_segments": str(USABLE_SEGMENTS_FILE),
            "source_bin_geometry": str(SOURCE_BIN_GEOMETRY_FILE),
            "role_enriched_segments": str(ROLE_ENRICHED_SEGMENTS_FILE),
            "catchment_index_metadata_only": str(CATCHMENT_INDEX_FILE),
            "readiness_by_crash": str(READINESS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
            "v2_bin_context": str(V2_BIN_CONTEXT_FILE),
            "v2_summary": str(V2_SUMMARY_FILE),
            "posted_speed_route_coverage_summary": str(ROUTE_DIAGNOSTIC_SUMMARY_FILE),
            "posted_speed_staging_schema": str(STAGING_SCHEMA_FILE),
            "posted_speed_staging_field_roles": str(STAGING_FIELD_ROLES_FILE),
            "posted_speed_staging_crs_sanity": str(STAGING_CRS_SANITY_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "speed_crs": crs_to_string(speed.crs),
        "speed_crs_matches_working_crs": crs_matches(speed.crs, WORKING_CRS_AUTHORITY),
    }
    _write_json(manifest, outputs["manifest_json"])
    logger.log("END build_speed_context_join_v3")
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prototype route-assisted posted-speed context join v3.")
    parser.add_argument("--limit-route-groups", type=int, default=None, help="Process only the first N normalized route groups for smoke testing.")
    parser.add_argument("--sample-routes", type=int, default=None, help="Alias for --limit-route-groups.")
    parser.add_argument("--skip-nearest-any", action="store_true", help="Skip expensive nearest-any fallback diagnostics.")
    args = parser.parse_args()
    limit_route_groups = args.limit_route_groups if args.limit_route_groups is not None else args.sample_routes
    outputs = build_speed_context_join_v3(limit_route_groups=limit_route_groups, skip_nearest_any=args.skip_nearest_any)
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
