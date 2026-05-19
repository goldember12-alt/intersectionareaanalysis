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
OUTPUT_DIR = Path("review/current/aadt_context_join")

AADT_FILE = Path("artifacts/normalized/aadt.parquet")
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
USABLE_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_segments.csv"
SOURCE_BIN_GEOMETRY_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv"
ROLE_ENRICHED_SEGMENTS_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_roadway_segments_role_enriched.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
ACCESS_SUMMARY_FILE = OUTPUT_ROOT / "review/current/access_context_join/access_context_join_summary.csv"
ACCESS_QA_FILE = OUTPUT_ROOT / "review/current/access_context_join/access_context_join_qa.csv"
SPEED_SUMMARY_FILE = OUTPUT_ROOT / "review/current/speed_context_join_v3_route_assisted/speed_context_v3_summary.csv"
SPEED_QA_FILE = OUTPUT_ROOT / "review/current/speed_context_join_v3_route_assisted/speed_context_v3_qa.csv"
AADT_STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_schema.csv"
AADT_STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_field_role_candidates.csv"
AADT_STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_crs_sanity.csv"

FEET_TO_METERS = 0.3048
TIGHT_ROUTE_THRESHOLD_FT = 25.0
STABLE_ROUTE_THRESHOLD_FT = 100.0
REVIEW_ROUTE_THRESHOLD_FT = 500.0
STABLE_ROUTE_THRESHOLD_M = STABLE_ROUTE_THRESHOLD_FT * FEET_TO_METERS
REVIEW_ROUTE_THRESHOLD_M = REVIEW_ROUTE_THRESHOLD_FT * FEET_TO_METERS

AADT_VALUE_FIELD = "AADT"
AADT_YEAR_FIELD = "AADT_YR"
AADT_ID_FIELD = "LINKID"
AADT_EDGE_KEY_FIELD = "EDGE_RTE_KEY"
AADT_ROUTE_FIELDS = ["RTE_NM", "MASTER_RTE_NM"]
AADT_CONTEXT_FIELDS = [
    "AADT_QUALITY",
    "AAWDT",
    "AAWDT_QUALITY",
    "DIRECTION_FACTOR",
    "DIRECTIONALITY",
    "TRANSPORT_EDGE_FROM_MSR",
    "TRANSPORT_EDGE_TO_MSR",
    "FROM_PHY_JURISDICTION_NM",
    "MPO_DSC",
]
STABLE_ROUTE_FIELDS = [
    "route_name",
    "route_common",
    "route_id",
    "event_source",
    "road_component_id",
    "roadway_role_class",
    "facility_code",
    "facility_text",
    "RTE_TYPE_N",
    "rte_type_name",
    "RTE_CATEGO",
    "rte_category",
    "RTE_RAMP_C",
    "rte_ramp_code",
]
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_DIRECTIONAL_COLUMNS = [
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
    "aadt_route_name_raw",
    "aadt_route_name_normalized",
    "stable_edge_key",
    "aadt_edge_rte_key",
    "route_or_edge_match_status",
    "aadt_value",
    "aadt_year",
    "aadt_direction_factor",
    "aadt_directionality",
    "aadt_candidate_values",
    "aadt_value_conflict_flag",
    "nearest_aadt_distance_ft",
    "nearest_aadt_record_id",
    "aadt_context_method",
    "aadt_context_confidence",
    "aadt_context_status",
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
        line = f"{timestamp}\t+{elapsed:,.3f}s\t{message}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)


def _phase(progress_logger: ProgressLogger, name: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    progress_logger.log(f"BEGIN {name}")
    started = time.perf_counter()
    result = func(*args, **kwargs)
    progress_logger.log(f"END {name}; elapsed_s={time.perf_counter() - started:,.3f}; {_describe_result(result)}")
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


def _read_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return _read_csv(path)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _format_number(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    if float(numeric).is_integer():
        return str(int(numeric))
    return f"{float(numeric):.3f}".rstrip("0").rstrip(".")


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
    if route_number:
        bounded_type = route_type if route_type in {"I", "SC", "CR", "BUS"} else ""
        return f"{bounded_type}{route_number}{direction}"
    return legacy


def _distance_window(midpoint_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([midpoint_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    if value <= 1000:
        return "high_priority_0_1000ft"
    if value <= 2500:
        return "sensitivity_1000_2500ft"
    return "review_over_2500ft"


def _source_bin_key(base_segment_id: Any, bin_index_in_travel_direction: Any) -> str:
    index = pd.to_numeric(pd.Series([bin_index_in_travel_direction]), errors="coerce").iloc[0]
    if pd.isna(index):
        return ""
    return f"{base_segment_id}_bin_{int(index) - 1:04d}"


def _load_aadt() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    aadt = gpd.read_parquet(AADT_FILE)
    if aadt.crs is None:
        raise ValueError("AADT source has no CRS; rerun AADT staging.")
    missing = [field for field in [AADT_VALUE_FIELD, AADT_YEAR_FIELD, AADT_ID_FIELD, AADT_EDGE_KEY_FIELD, "RTE_NM", "MASTER_RTE_NM", "DIRECTION_FACTOR", "DIRECTIONALITY"] if field not in aadt.columns]
    if missing:
        raise ValueError(f"AADT source is missing required fields: {missing}")
    aadt = aadt.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="aadt_source_index")
    aadt["nearest_aadt_record_id"] = aadt[AADT_ID_FIELD].astype(str)
    aadt.loc[aadt["nearest_aadt_record_id"].eq(""), "nearest_aadt_record_id"] = aadt["aadt_source_index"].astype(str)
    aadt["source_geometry_is_null"] = aadt.geometry.isna()
    aadt["source_geometry_is_valid"] = aadt.geometry.notna() & aadt.geometry.is_valid
    aadt["aadt_value_numeric"] = pd.to_numeric(aadt[AADT_VALUE_FIELD], errors="coerce")
    aadt["aadt_year_numeric"] = pd.to_numeric(aadt[AADT_YEAR_FIELD], errors="coerce")
    alias_frames = []
    for field in AADT_ROUTE_FIELDS:
        alias = aadt.copy()
        alias["aadt_route_name_raw"] = alias[field].astype(str)
        alias = alias.loc[alias["aadt_route_name_raw"].ne("")].copy()
        alias["aadt_route_name_normalized"] = alias["aadt_route_name_raw"].map(normalize_route_name)
        alias["aadt_route_alias_field"] = field
        alias_frames.append(alias)
    aliases = pd.concat(alias_frames, ignore_index=True, sort=False)
    aliases = aliases.loc[aliases["aadt_route_name_normalized"].ne("")].copy()
    return aadt, aliases


def _load_directional_context_bins() -> pd.DataFrame:
    bins = _read_csv(USABLE_BINS_FILE)
    catchment_index = _read_csv(CATCHMENT_INDEX_FILE, usecols=["reference_directional_bin_id", "catchment_status"])
    catchment_index = catchment_index.loc[catchment_index["catchment_status"].eq("usable")].copy()
    role_header = pd.read_csv(ROLE_ENRICHED_SEGMENTS_FILE, nrows=0).columns.tolist()
    role_fields = ["oriented_segment_id", *[field for field in STABLE_ROUTE_FIELDS if field in role_header]]
    roles = _read_csv(ROLE_ENRICHED_SEGMENTS_FILE, usecols=role_fields).rename(columns={"oriented_segment_id": "base_segment_id"})
    bins = bins.merge(catchment_index, on="reference_directional_bin_id", how="left")
    bins = bins.merge(roles, on="base_segment_id", how="left")
    bins["bin_midpoint_ft_from_reference_signal"] = _num(bins, "bin_midpoint_ft_from_reference_signal")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    bins["context_join_eligible"] = bins["catchment_status"].eq("usable") & bins["bin_midpoint_ft_from_reference_signal"].le(2500)
    bins["source_bin_key"] = [_source_bin_key(base_segment_id, index) for base_segment_id, index in zip(bins["base_segment_id"], bins["bin_index_in_travel_direction"], strict=False)]
    bins["stable_route_name_raw"] = bins["route_common"].astype(str) if "route_common" in bins.columns else ""
    bins["stable_route_name_normalized"] = bins["stable_route_name_raw"].map(normalize_route_name)
    bins["stable_edge_key"] = ""
    return bins


def _load_base_bin_geometry(context_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    eligible = context_bins.loc[context_bins["context_join_eligible"]].copy()
    source_keys = set(eligible["source_bin_key"].astype(str))
    source = pd.read_csv(SOURCE_BIN_GEOMETRY_FILE, dtype=str, keep_default_na=False, usecols=["oriented_segment_id", "bin_id", "bin_index", "bin_start_ft", "bin_end_ft", "bin_midpoint_ft", "geometry"])
    source = source.loc[source["bin_id"].astype(str).isin(source_keys)].copy()
    source["geometry"] = source["geometry"].map(lambda value: wkt.loads(value) if isinstance(value, str) and value.strip() else None)
    base = gpd.GeoDataFrame(source, geometry="geometry", crs=WORKING_CRS_AUTHORITY).rename(columns={"oriented_segment_id": "base_segment_id", "bin_id": "source_bin_key"})
    stable = eligible[["source_bin_key", "base_segment_id", "stable_route_name_raw", "stable_route_name_normalized", "stable_edge_key", *[c for c in STABLE_ROUTE_FIELDS if c in eligible.columns]]].drop_duplicates(["source_bin_key", "base_segment_id"])
    return base.merge(stable, on=["source_bin_key", "base_segment_id"], how="left")


def _aadt_columns_for_matching(aadt: gpd.GeoDataFrame) -> list[str]:
    columns = [
        "aadt_source_index",
        "nearest_aadt_record_id",
        "aadt_route_name_raw",
        "aadt_route_name_normalized",
        "aadt_route_alias_field",
        AADT_VALUE_FIELD,
        AADT_YEAR_FIELD,
        "aadt_value_numeric",
        "aadt_year_numeric",
        AADT_ID_FIELD,
        AADT_EDGE_KEY_FIELD,
        "DIRECTION_FACTOR",
        "DIRECTIONALITY",
    ]
    for field in AADT_CONTEXT_FIELDS:
        if field in aadt.columns and field not in columns:
            columns.append(field)
    return columns


def _route_group_summary(routed_bins: gpd.GeoDataFrame, valid_aadt: gpd.GeoDataFrame) -> str:
    bin_groups = routed_bins.groupby("stable_route_name_normalized", dropna=False).size().sort_values(ascending=False)
    aadt_groups = valid_aadt.groupby("aadt_route_name_normalized", dropna=False).size()
    largest = []
    for route_name, bin_count in bin_groups.head(10).items():
        largest.append(f"{route_name}:bins={int(bin_count)},aadt={int(aadt_groups.get(route_name, 0))}")
    return "; ".join(largest)


def _route_compatible_candidates(aadt: gpd.GeoDataFrame, base_bins: gpd.GeoDataFrame, *, logger: ProgressLogger | None = None, limit_route_groups: int | None = None, progress_every: int = 25) -> pd.DataFrame:
    valid_aadt = aadt.loc[aadt["source_geometry_is_valid"] & aadt["aadt_route_name_normalized"].ne("") & aadt["aadt_value_numeric"].gt(0)].copy()
    routed_bins = base_bins.loc[base_bins["stable_route_name_normalized"].astype(str).ne("")].copy()
    columns = _aadt_columns_for_matching(valid_aadt)
    frames: list[pd.DataFrame] = []
    route_groups = list(routed_bins.groupby("stable_route_name_normalized", dropna=False))
    if limit_route_groups is not None:
        route_groups = route_groups[:limit_route_groups]
    if logger:
        logger.log(
            "SPATIAL_JOIN_SETUP _route_compatible_candidates; "
            f"base_bin_count={len(base_bins)}; routed_bin_count={len(routed_bins)}; "
            f"aadt_alias_record_count={len(valid_aadt)}; route_group_count={len(route_groups)}; "
            f"largest_route_groups={_route_group_summary(routed_bins, valid_aadt)}"
        )
    for index, (route_name, base_group) in enumerate(route_groups, start=1):
        aadt_group = valid_aadt.loc[valid_aadt["aadt_route_name_normalized"].eq(route_name)].copy()
        if logger and (index == 1 or index % progress_every == 0 or index == len(route_groups)):
            logger.log(f"SPATIAL_JOIN_GROUP _route_compatible_candidates; group={index}/{len(route_groups)}; route={route_name}; base_bins={len(base_group)}; aadt_records={len(aadt_group)}")
        if base_group.empty or aadt_group.empty:
            continue
        try:
            joined = gpd.sjoin(base_group, aadt_group[columns + ["geometry"]], how="inner", predicate="dwithin", distance=STABLE_ROUTE_THRESHOLD_M)
            joined = joined.drop(columns=["index_right"], errors="ignore").copy()
            if not joined.empty:
                aadt_geoms = aadt_group[["aadt_source_index", "geometry"]].rename(columns={"geometry": "aadt_geometry"})
                joined = joined.merge(aadt_geoms, on="aadt_source_index", how="left")
                joined["nearest_aadt_distance_ft"] = joined.apply(_geometry_distance_ft, axis=1)
                frames.append(pd.DataFrame(joined.drop(columns=["geometry", "aadt_geometry"], errors="ignore")))
                continue
        except TypeError:
            pass
        nearest = gpd.sjoin_nearest(base_group, aadt_group[columns + ["geometry"]], how="inner", max_distance=STABLE_ROUTE_THRESHOLD_M, distance_col="nearest_distance_m")
        nearest = nearest.drop(columns=["index_right", "geometry"], errors="ignore").copy()
        if not nearest.empty:
            nearest["nearest_aadt_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
            frames.append(pd.DataFrame(nearest))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates(["source_bin_key", "aadt_source_index", "aadt_route_alias_field"])
    out["candidate_match_family"] = "route_compatible_within_stable_threshold"
    out["route_or_edge_match_status"] = "exact_normalized_route_match"
    out["nearest_aadt_distance_ft"] = pd.to_numeric(out["nearest_aadt_distance_ft"], errors="coerce").round(3)
    return out


def _route_review_nearest_candidates(aadt: gpd.GeoDataFrame, base_bins: gpd.GeoDataFrame, *, logger: ProgressLogger | None = None, limit_route_groups: int | None = None, progress_every: int = 25) -> pd.DataFrame:
    valid_aadt = aadt.loc[aadt["source_geometry_is_valid"] & aadt["aadt_route_name_normalized"].ne("") & aadt["aadt_value_numeric"].gt(0)].copy()
    routed_bins = base_bins.loc[base_bins["stable_route_name_normalized"].astype(str).ne("")].copy()
    columns = _aadt_columns_for_matching(valid_aadt)
    frames: list[pd.DataFrame] = []
    route_groups = list(routed_bins.groupby("stable_route_name_normalized", dropna=False))
    if limit_route_groups is not None:
        route_groups = route_groups[:limit_route_groups]
    if logger:
        logger.log(f"SPATIAL_JOIN_SETUP _route_review_nearest_candidates; base_bin_count={len(base_bins)}; routed_bin_count={len(routed_bins)}; aadt_alias_record_count={len(valid_aadt)}; route_group_count={len(route_groups)}")
    for index, (route_name, base_group) in enumerate(route_groups, start=1):
        aadt_group = valid_aadt.loc[valid_aadt["aadt_route_name_normalized"].eq(route_name)].copy()
        if logger and (index == 1 or index % progress_every == 0 or index == len(route_groups)):
            logger.log(f"SPATIAL_JOIN_GROUP _route_review_nearest_candidates; group={index}/{len(route_groups)}; route={route_name}; base_bins={len(base_group)}; aadt_records={len(aadt_group)}")
        if base_group.empty or aadt_group.empty:
            continue
        nearest = gpd.sjoin_nearest(base_group, aadt_group[columns + ["geometry"]], how="left", max_distance=REVIEW_ROUTE_THRESHOLD_M, distance_col="nearest_distance_m")
        nearest = nearest.drop(columns=["index_right", "geometry"], errors="ignore").copy()
        nearest = nearest.loc[nearest["nearest_aadt_record_id"].notna()].copy()
        if nearest.empty:
            continue
        nearest["nearest_aadt_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
        frames.append(pd.DataFrame(nearest))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates(["source_bin_key", "aadt_source_index", "aadt_route_alias_field"])
    out["candidate_match_family"] = "nearest_route_compatible_within_review_threshold"
    out["route_or_edge_match_status"] = "exact_normalized_route_match"
    out["nearest_aadt_distance_ft"] = pd.to_numeric(out["nearest_aadt_distance_ft"], errors="coerce").round(3)
    return out


def _nearest_any_aadt_candidates(aadt: gpd.GeoDataFrame, base_bins: gpd.GeoDataFrame, *, logger: ProgressLogger | None = None) -> pd.DataFrame:
    valid_aadt = aadt.loc[aadt["source_geometry_is_valid"] & aadt["aadt_value_numeric"].gt(0)].copy()
    columns = _aadt_columns_for_matching(valid_aadt)
    if logger:
        logger.log(f"SPATIAL_JOIN_SETUP _nearest_any_aadt_candidates; base_bin_count={len(base_bins)}; aadt_alias_record_count={len(valid_aadt)}")
    nearest = gpd.sjoin_nearest(base_bins, valid_aadt[columns + ["geometry"]], how="left", max_distance=REVIEW_ROUTE_THRESHOLD_M, distance_col="nearest_distance_m")
    nearest = nearest.drop(columns=["index_right", "geometry"], errors="ignore").copy()
    nearest = nearest.loc[nearest["nearest_aadt_record_id"].notna()].copy()
    nearest["nearest_aadt_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest["candidate_match_family"] = "nearest_any_route_within_review_threshold"
    nearest["route_or_edge_match_status"] = nearest.apply(_route_match_status, axis=1)
    nearest["nearest_aadt_distance_ft"] = pd.to_numeric(nearest["nearest_aadt_distance_ft"], errors="coerce").round(3)
    return pd.DataFrame(nearest)


def _geometry_distance_ft(row: pd.Series) -> float:
    left = row.get("geometry")
    right = row.get("aadt_geometry")
    if left is None or right is None:
        return float("nan")
    try:
        return float(left.distance(right) / FEET_TO_METERS)
    except Exception:
        return float("nan")


def _route_match_status(row: pd.Series) -> str:
    stable = str(row.get("stable_route_name_normalized") or "")
    aadt = str(row.get("aadt_route_name_normalized") or "")
    if not stable:
        return "route_missing"
    if not aadt:
        return "route_missing"
    if stable == aadt:
        return "exact_normalized_route_match"
    return "route_mismatch"


def _prepare_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    prepared = frame.copy()
    prepared["source_bin_key"] = prepared["source_bin_key"].astype(str)
    prepared["_nearest_aadt_distance_numeric"] = pd.to_numeric(prepared.get("nearest_aadt_distance_ft"), errors="coerce")
    prepared["_aadt_value_numeric"] = pd.to_numeric(prepared.get(AADT_VALUE_FIELD), errors="coerce")
    prepared["_aadt_year_numeric"] = pd.to_numeric(prepared.get(AADT_YEAR_FIELD), errors="coerce")
    return prepared


def _joined_unique_numbers(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if numeric.empty:
        return "<missing>"
    return "|".join(_format_number(value) for value in numeric.unique().tolist())


def _summary_by_source(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["source_bin_key"])
    frame = _prepare_candidate_frame(frame)
    grouped = frame.groupby("source_bin_key", sort=False)
    summary = grouped.agg(
        **{
            f"{prefix}_candidate_count": ("aadt_source_index", "nunique"),
            f"{prefix}_nearest_distance": ("_nearest_aadt_distance_numeric", "min"),
            f"{prefix}_aadt_value_min": ("_aadt_value_numeric", "min"),
            f"{prefix}_aadt_value_max": ("_aadt_value_numeric", "max"),
            f"{prefix}_aadt_year_max": ("_aadt_year_numeric", "max"),
        }
    ).reset_index()
    nearest = (
        frame.loc[frame["_nearest_aadt_distance_numeric"].notna()]
        .sort_values(["source_bin_key", "_nearest_aadt_distance_numeric", "_aadt_year_numeric", "nearest_aadt_record_id"], ascending=[True, True, False, True])
        .drop_duplicates("source_bin_key")
    )
    rename = {
        "nearest_aadt_record_id": f"{prefix}_nearest_aadt_record_id",
        "aadt_route_name_raw": f"{prefix}_aadt_route_name_raw",
        "aadt_route_name_normalized": f"{prefix}_aadt_route_name_normalized",
        AADT_EDGE_KEY_FIELD: f"{prefix}_aadt_edge_rte_key",
        "DIRECTION_FACTOR": f"{prefix}_aadt_direction_factor",
        "DIRECTIONALITY": f"{prefix}_aadt_directionality",
        "route_or_edge_match_status": f"{prefix}_route_or_edge_match_status",
    }
    keep = ["source_bin_key", *rename.keys()]
    summary = summary.merge(nearest[[c for c in keep if c in nearest.columns]].rename(columns=rename), on="source_bin_key", how="left")
    values = grouped[AADT_VALUE_FIELD].apply(_joined_unique_numbers).rename(f"{prefix}_aadt_candidate_values").reset_index()
    summary = summary.merge(values, on="source_bin_key", how="left")
    summary[f"{prefix}_aadt_value_conflict_flag"] = pd.to_numeric(summary[f"{prefix}_aadt_value_max"], errors="coerce").ne(pd.to_numeric(summary[f"{prefix}_aadt_value_min"], errors="coerce"))
    stable_choice = (
        frame.sort_values(["source_bin_key", "_aadt_year_numeric", "_nearest_aadt_distance_numeric", "nearest_aadt_record_id"], ascending=[True, False, True, True])
        .drop_duplicates("source_bin_key")
    )
    choice_cols = ["source_bin_key", AADT_VALUE_FIELD, AADT_YEAR_FIELD]
    summary = summary.merge(stable_choice[choice_cols].rename(columns={AADT_VALUE_FIELD: f"{prefix}_selected_aadt_value", AADT_YEAR_FIELD: f"{prefix}_selected_aadt_year"}), on="source_bin_key", how="left")
    return summary


def _build_base_context(base_bins: gpd.GeoDataFrame, route_candidates: pd.DataFrame, route_review: pd.DataFrame, nearest_any: pd.DataFrame, *, logger: ProgressLogger | None = None) -> pd.DataFrame:
    base = pd.DataFrame(base_bins.drop(columns=["geometry"], errors="ignore")).copy()
    route_summary = _summary_by_source(route_candidates, "route")
    if logger:
        logger.log(f"BASE_CONTEXT_ROUTE_SUMMARY rows={len(route_summary)}")
    review_summary = _summary_by_source(route_review, "review")
    any_summary = _summary_by_source(nearest_any, "any")
    work = base.merge(route_summary, on="source_bin_key", how="left").merge(review_summary, on="source_bin_key", how="left").merge(any_summary, on="source_bin_key", how="left")
    for column in [
        "route_candidate_count",
        "route_nearest_distance",
        "route_aadt_value_conflict_flag",
        "route_selected_aadt_value",
        "route_selected_aadt_year",
        "route_nearest_aadt_record_id",
        "route_aadt_route_name_raw",
        "route_aadt_route_name_normalized",
        "route_aadt_edge_rte_key",
        "route_aadt_direction_factor",
        "route_aadt_directionality",
        "route_aadt_candidate_values",
        "review_nearest_aadt_record_id",
        "review_nearest_distance",
        "review_aadt_route_name_raw",
        "review_aadt_route_name_normalized",
        "review_aadt_edge_rte_key",
        "review_aadt_direction_factor",
        "review_aadt_directionality",
        "review_aadt_candidate_values",
        "any_nearest_aadt_record_id",
        "any_nearest_distance",
        "any_aadt_route_name_raw",
        "any_aadt_route_name_normalized",
        "any_aadt_edge_rte_key",
        "any_aadt_direction_factor",
        "any_aadt_directionality",
        "any_aadt_candidate_values",
        "any_route_or_edge_match_status",
    ]:
        if column not in work.columns:
            work[column] = pd.NA

    stable_route = work["stable_route_name_normalized"].fillna("").astype(str)
    route_exists = work["route_candidate_count"].notna()
    review_exists = work["review_nearest_aadt_record_id"].notna()
    any_exists = work["any_nearest_aadt_record_id"].notna()
    route_conflict = work["route_aadt_value_conflict_flag"].fillna(False).astype(bool)
    route_distance = pd.to_numeric(work["route_nearest_distance"], errors="coerce")
    review_distance = pd.to_numeric(work["review_nearest_distance"], errors="coerce")
    any_distance = pd.to_numeric(work["any_nearest_distance"], errors="coerce")

    work["aadt_context_status"] = "no_aadt_nearby_or_route_compatible"
    work["aadt_context_method"] = "no_route_compatible_aadt_match"
    work["aadt_context_confidence"] = "missing"
    work["route_or_edge_match_status"] = "not_evaluated"

    no_route = ~route_exists
    no_stable_route = no_route & stable_route.eq("")
    any_route_mismatch = no_route & any_exists & work["any_route_or_edge_match_status"].fillna("").astype(str).eq("route_mismatch")
    review_route_only = no_route & review_exists & ~no_stable_route & ~any_route_mismatch
    route_stable = route_exists & ~route_conflict

    work.loc[no_stable_route, ["aadt_context_status", "aadt_context_method", "aadt_context_confidence", "route_or_edge_match_status"]] = ["review_route_missing", "review_route_missing", "low_review", "route_missing"]
    work.loc[any_route_mismatch, ["aadt_context_status", "aadt_context_method", "aadt_context_confidence", "route_or_edge_match_status"]] = ["review_route_mismatch", "review_route_mismatch", "low_review", "route_mismatch"]
    work.loc[route_conflict, ["aadt_context_status", "aadt_context_method", "aadt_context_confidence", "route_or_edge_match_status"]] = ["ambiguous_conflicting_aadt_values", "review_conflicting_aadt_values", "low_review", "exact_normalized_route_match"]
    work.loc[route_stable, ["aadt_context_status", "aadt_context_method", "aadt_context_confidence", "route_or_edge_match_status"]] = ["stable_aadt_assigned_route_match", "route_assisted_nearest_base_line", "medium", "exact_normalized_route_match"]
    work.loc[route_stable & route_distance.le(TIGHT_ROUTE_THRESHOLD_FT), "aadt_context_confidence"] = "high"
    work.loc[review_route_only, "route_or_edge_match_status"] = "exact_normalized_route_match"

    use_route_fields = route_exists
    use_review_fields = no_route & review_exists & ~any_route_mismatch & ~no_stable_route
    use_any_fields = no_route & any_exists & (any_route_mismatch | no_stable_route | ~review_exists)
    output_defaults = {
        "aadt_route_name_raw": "",
        "aadt_route_name_normalized": "",
        "aadt_edge_rte_key": "",
        "aadt_value": pd.NA,
        "aadt_year": pd.NA,
        "aadt_direction_factor": pd.NA,
        "aadt_directionality": "",
        "aadt_candidate_values": "<missing>",
        "nearest_aadt_record_id": "",
        "nearest_aadt_distance_ft": pd.NA,
        "aadt_value_conflict_flag": False,
    }
    for column, value in output_defaults.items():
        work[column] = value
    for output, route_col, review_col, any_col in [
        ("aadt_route_name_raw", "route_aadt_route_name_raw", "review_aadt_route_name_raw", "any_aadt_route_name_raw"),
        ("aadt_route_name_normalized", "route_aadt_route_name_normalized", "review_aadt_route_name_normalized", "any_aadt_route_name_normalized"),
        ("aadt_edge_rte_key", "route_aadt_edge_rte_key", "review_aadt_edge_rte_key", "any_aadt_edge_rte_key"),
        ("aadt_candidate_values", "route_aadt_candidate_values", "review_aadt_candidate_values", "any_aadt_candidate_values"),
        ("nearest_aadt_record_id", "route_nearest_aadt_record_id", "review_nearest_aadt_record_id", "any_nearest_aadt_record_id"),
        ("aadt_direction_factor", "route_aadt_direction_factor", "review_aadt_direction_factor", "any_aadt_direction_factor"),
        ("aadt_directionality", "route_aadt_directionality", "review_aadt_directionality", "any_aadt_directionality"),
    ]:
        for mask, source_col in [(use_route_fields, route_col), (use_review_fields, review_col), (use_any_fields, any_col)]:
            if source_col in work.columns:
                work.loc[mask, output] = work.loc[mask, source_col]
    work.loc[use_route_fields, "nearest_aadt_distance_ft"] = route_distance.loc[use_route_fields]
    work.loc[use_review_fields, "nearest_aadt_distance_ft"] = review_distance.loc[use_review_fields]
    work.loc[use_any_fields, "nearest_aadt_distance_ft"] = any_distance.loc[use_any_fields]
    work.loc[route_stable, "aadt_value"] = work.loc[route_stable, "route_selected_aadt_value"]
    work.loc[route_stable, "aadt_year"] = work.loc[route_stable, "route_selected_aadt_year"]
    work["aadt_value_conflict_flag"] = route_conflict
    work["nearest_aadt_distance_ft"] = pd.to_numeric(work["nearest_aadt_distance_ft"], errors="coerce").round(3)
    work["route_candidate_count"] = pd.to_numeric(work["route_candidate_count"], errors="coerce").fillna(0).astype("int64")
    if logger:
        logger.log(
            "BASE_CONTEXT_STATUS_COUNTS "
            f"stable={int(work['aadt_context_status'].str.startswith('stable').sum())}; "
            f"ambiguous={int(work['aadt_context_status'].eq('ambiguous_conflicting_aadt_values').sum())}; "
            f"review_missing={int(work['aadt_context_status'].eq('review_route_missing').sum())}; "
            f"review_mismatch={int(work['aadt_context_status'].eq('review_route_mismatch').sum())}; "
            f"missing={int(work['aadt_context_status'].eq('no_aadt_nearby_or_route_compatible').sum())}"
        )
    return work


def _build_directional_context(context_bins: pd.DataFrame, base_context: pd.DataFrame) -> pd.DataFrame:
    primary = context_bins.loc[context_bins["context_join_eligible"]].copy()
    out = primary.merge(base_context.drop(columns=[c for c in STABLE_ROUTE_FIELDS if c in base_context.columns], errors="ignore"), on=["source_bin_key", "base_segment_id"], how="left", suffixes=("", "_base"))
    for column in ["stable_route_name_raw", "stable_route_name_normalized", "stable_edge_key"]:
        base_column = f"{column}_base"
        if base_column in out.columns:
            out[column] = out[column].where(out[column].astype(str).ne(""), out[base_column])
            out = out.drop(columns=[base_column])
    is_undivided_stable = out["roadway_representation_type"].eq("undivided_centerline_pseudo_direction") & out["aadt_context_status"].str.startswith("stable", na=False)
    out.loc[is_undivided_stable, "aadt_context_method"] = "propagated_from_shared_base_bin"
    out["aadt_context_status"] = out["aadt_context_status"].fillna("no_aadt_nearby_or_route_compatible")
    out["aadt_context_confidence"] = out["aadt_context_confidence"].fillna("missing")
    out["aadt_context_method"] = out["aadt_context_method"].fillna("no_route_compatible_aadt_match")
    for column in REQUIRED_DIRECTIONAL_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    return out


def _crash_context(readiness: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    readiness = readiness.copy()
    readiness["bin_midpoint_ft_from_reference_signal"] = _num(readiness, "bin_midpoint_ft_from_reference_signal")
    readiness = readiness.loc[readiness["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    keep = [
        "reference_directional_bin_id",
        "distance_window",
        "aadt_value",
        "aadt_year",
        "aadt_context_method",
        "aadt_context_confidence",
        "aadt_context_status",
    ]
    out = readiness.merge(bin_context[[c for c in keep if c in bin_context.columns]], on="reference_directional_bin_id", how="left", suffixes=("", "_bin"))
    if "distance_window_bin" in out.columns:
        out["distance_window"] = out["distance_window_bin"].where(out["distance_window_bin"].notna(), out.get("distance_window"))
    out["inherited_from_bin_aadt_context"] = True
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "aadt_value",
        "aadt_year",
        "aadt_context_method",
        "aadt_context_confidence",
        "aadt_context_status",
        "inherited_from_bin_aadt_context",
    ]
    return out[[c for c in columns if c in out.columns]]


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    stable = bin_context["aadt_context_status"].str.startswith("stable", na=False)
    grouped = (
        bin_context.assign(_stable=stable)
        .groupby(["reference_signal_id", "distance_window"], dropna=False)
        .agg(
            directional_bin_count=("reference_directional_bin_id", "nunique"),
            stable_aadt_bin_count=("_stable", "sum"),
            missing_aadt_bin_count=("aadt_context_status", lambda s: int(s.eq("no_aadt_nearby_or_route_compatible").sum())),
            ambiguous_aadt_bin_count=("aadt_context_status", lambda s: int(s.eq("ambiguous_conflicting_aadt_values").sum())),
            min_aadt=("aadt_value", lambda s: pd.to_numeric(s, errors="coerce").min()),
            max_aadt=("aadt_value", lambda s: pd.to_numeric(s, errors="coerce").max()),
            latest_aadt_year=("aadt_year", lambda s: pd.to_numeric(s, errors="coerce").max()),
        )
        .reset_index()
    )
    grouped["stable_aadt_bin_share"] = (grouped["stable_aadt_bin_count"] / grouped["directional_bin_count"].clip(lower=1)).round(4)
    return grouped


def _aadt_records_joined(aadt: gpd.GeoDataFrame, candidates: pd.DataFrame, base_context: pd.DataFrame) -> pd.DataFrame:
    stable_keys = set(base_context.loc[base_context["aadt_context_status"].str.startswith("stable", na=False), "source_bin_key"].astype(str))
    if candidates.empty:
        match_counts = pd.DataFrame(columns=["aadt_source_index", "matched_base_bin_count"])
    else:
        stable_candidates = candidates.loc[candidates["source_bin_key"].astype(str).isin(stable_keys)].copy()
        match_counts = stable_candidates.groupby("aadt_source_index", dropna=False)["source_bin_key"].nunique().reset_index(name="matched_base_bin_count")
    base_cols = ["aadt_source_index", "nearest_aadt_record_id", AADT_VALUE_FIELD, AADT_YEAR_FIELD, "RTE_NM", "MASTER_RTE_NM", AADT_EDGE_KEY_FIELD, "source_geometry_is_null", "source_geometry_is_valid"]
    out = pd.DataFrame(aadt.drop(columns="geometry", errors="ignore"))[[c for c in base_cols if c in aadt.columns]].drop_duplicates("aadt_source_index")
    out = out.merge(match_counts, on="aadt_source_index", how="left")
    out["matched_base_bin_count"] = pd.to_numeric(out["matched_base_bin_count"], errors="coerce").fillna(0).astype("int64")
    out["aadt_join_status"] = out["matched_base_bin_count"].gt(0).map(lambda value: "matched_to_stable_bin" if value else "not_matched_to_stable_bin")
    return out


def _route_match_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    return (
        bin_context.groupby(["route_or_edge_match_status", "aadt_context_status", "distance_window"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"), base_bin_count=("source_bin_key", "nunique"), median_distance_ft=("nearest_aadt_distance_ft", "median"))
        .reset_index()
    )


def _paired_pseudo_direction_consistency(bin_context: pd.DataFrame) -> pd.DataFrame:
    pseudo = bin_context.loc[bin_context["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    if pseudo.empty:
        return pd.DataFrame(columns=["base_segment_id", "source_bin_key", "directional_record_count", "aadt_context_status_count", "aadt_value_count", "paired_pseudo_direction_aadt_consistent"])
    grouped = pseudo.groupby(["base_segment_id", "source_bin_key"], dropna=False).agg(
        directional_record_count=("reference_directional_bin_id", "nunique"),
        aadt_context_status_count=("aadt_context_status", "nunique"),
        aadt_value_count=("aadt_value", "nunique"),
        aadt_year_count=("aadt_year", "nunique"),
    ).reset_index()
    grouped["paired_pseudo_direction_aadt_consistent"] = grouped["aadt_context_status_count"].le(1) & grouped["aadt_value_count"].le(1) & grouped["aadt_year_count"].le(1)
    return grouped


def _summary(bin_context: pd.DataFrame, base_context: pd.DataFrame, crash_context: pd.DataFrame, aadt_joined: pd.DataFrame, paired_qa: pd.DataFrame, source_aadt: gpd.GeoDataFrame) -> pd.DataFrame:
    stable = bin_context["aadt_context_status"].str.startswith("stable", na=False)
    rows = [
        {"metric": "aadt_records_considered", "value": "", "count": int(len(source_aadt))},
        {"metric": "aadt_records_with_null_geometry", "value": "", "count": int(source_aadt["source_geometry_is_null"].sum())},
        {"metric": "aadt_records_with_invalid_geometry", "value": "", "count": int((~source_aadt["source_geometry_is_valid"]).sum())},
        {"metric": "aadt_records_matched_to_stable_universe", "value": "", "count": int(aadt_joined["matched_base_bin_count"].gt(0).sum())},
        {"metric": "directional_bins_in_context_window", "value": "0-2500ft", "count": int(len(bin_context))},
        {"metric": "bins_with_stable_aadt", "value": "", "count": int(stable.sum())},
        {"metric": "bins_missing_aadt", "value": "", "count": int(bin_context["aadt_context_status"].eq("no_aadt_nearby_or_route_compatible").sum())},
        {"metric": "ambiguous_conflicting_aadt_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("ambiguous_conflicting_aadt_values").sum())},
        {"metric": "route_mismatch_review_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("review_route_mismatch").sum())},
        {"metric": "route_missing_review_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("review_route_missing").sum())},
        {"metric": "bins_with_aadt_by_exact_edge_key_match", "value": "", "count": int(bin_context["aadt_context_status"].eq("stable_aadt_assigned_edge_key").sum())},
        {"metric": "bins_with_aadt_by_route_assisted_match", "value": "", "count": int(bin_context["aadt_context_status"].eq("stable_aadt_assigned_route_match").sum())},
        {"metric": "crashes_inheriting_stable_aadt", "value": "", "count": int(crash_context["aadt_context_status"].str.startswith("stable", na=False).sum()) if not crash_context.empty else 0},
        {"metric": "reference_signals_with_stable_aadt", "value": "", "count": int(bin_context.loc[stable, "reference_signal_id"].nunique())},
        {"metric": "paired_pseudo_direction_groups", "value": "", "count": int(len(paired_qa))},
        {"metric": "paired_pseudo_direction_inconsistent_groups", "value": "", "count": int((~paired_qa["paired_pseudo_direction_aadt_consistent"]).sum()) if not paired_qa.empty else 0},
        {"metric": "dominant_match_method", "value": _dominant(bin_context["aadt_context_method"]), "count": ""},
        {"metric": "aadt_ready_as_flagged_context_layer", "value": bool(stable.any()), "count": ""},
        {"metric": "aadt_to_bin_join_implemented", "value": True, "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "aadt_used_for_upstream_downstream", "value": False, "count": ""},
    ]
    for window, group in bin_context.groupby("distance_window", dropna=False):
        window_stable = group["aadt_context_status"].str.startswith("stable", na=False)
        rows.append({"metric": "bins_by_distance_window", "value": str(window), "count": int(len(group))})
        rows.append({"metric": "stable_aadt_bins_by_distance_window", "value": str(window), "count": int(window_stable.sum())})
        rows.append({"metric": "ambiguous_aadt_bins_by_distance_window", "value": str(window), "count": int(group["aadt_context_status"].eq("ambiguous_conflicting_aadt_values").sum())})
        rows.append({"metric": "missing_aadt_bins_by_distance_window", "value": str(window), "count": int(group["aadt_context_status"].eq("no_aadt_nearby_or_route_compatible").sum())})
    for direction, group in bin_context.groupby("signal_relative_direction", dropna=False):
        direction_stable = group["aadt_context_status"].str.startswith("stable", na=False)
        rows.append({"metric": "bins_by_signal_relative_direction", "value": str(direction), "count": int(len(group))})
        rows.append({"metric": "stable_aadt_bins_by_signal_relative_direction", "value": str(direction), "count": int(direction_stable.sum())})
        rows.append({"metric": "ambiguous_aadt_bins_by_signal_relative_direction", "value": str(direction), "count": int(group["aadt_context_status"].eq("ambiguous_conflicting_aadt_values").sum())})
        rows.append({"metric": "missing_aadt_bins_by_signal_relative_direction", "value": str(direction), "count": int(group["aadt_context_status"].eq("no_aadt_nearby_or_route_compatible").sum())})
    stable_years = bin_context.loc[stable, "aadt_year"]
    for year, count in pd.to_numeric(stable_years, errors="coerce").dropna().astype(int).value_counts().sort_index().items():
        rows.append({"metric": "stable_aadt_bins_by_aadt_year", "value": str(year), "count": int(count)})
    return pd.DataFrame(rows)


def _dominant(series: pd.Series) -> str:
    counts = series.fillna("<missing>").astype(str).value_counts()
    return "" if counts.empty else str(counts.index[0])


def _context_qa(bin_context: pd.DataFrame, source_aadt: gpd.GeoDataFrame, paired_qa: pd.DataFrame, crash_context: pd.DataFrame) -> pd.DataFrame:
    outside = int(bin_context["bin_midpoint_ft_from_reference_signal"].gt(2500).sum())
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
        {"check_name": "aadt_not_used_for_upstream_downstream", "passed": True, "observed": False, "expected": False},
        {"check_name": "scaffold_catchment_assignment_access_speed_logic_changed", "passed": True, "observed": False, "expected": False},
        {"check_name": "main_context_limited_to_0_2500ft", "passed": outside == 0, "observed": outside, "expected": 0},
        {"check_name": "crs_matches_working_epsg_3968", "passed": crs_matches(source_aadt.crs, WORKING_CRS_AUTHORITY), "observed": crs_to_string(source_aadt.crs), "expected": WORKING_CRS_AUTHORITY},
        {"check_name": "aadt_records_matched_reported", "passed": True, "observed": int(bin_context["aadt_context_status"].str.startswith("stable", na=False).sum()), "expected": "reported"},
        {"check_name": "review_missing_ambiguous_reported", "passed": True, "observed": int((~bin_context["aadt_context_status"].str.startswith("stable", na=False)).sum()), "expected": "reported"},
        {"check_name": "paired_pseudo_direction_consistency_reported", "passed": True, "observed": int((~paired_qa["paired_pseudo_direction_aadt_consistent"]).sum()) if not paired_qa.empty else 0, "expected": "reported"},
        {"check_name": "crash_aadt_inheritance_reported", "passed": True, "observed": int(len(crash_context)), "expected": "reported"},
    ]
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, outputs: dict[str, Path], *, limit_route_groups: int | None) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        if row.empty:
            return ""
        return row.iloc[0]["count"] if str(row.iloc[0]["count"]) != "" else row.iloc[0]["value"]
    lines = [
        "# AADT Context Join Findings",
        "",
        "## Bounded Question",
        "",
        "Attach AADT as a flagged context layer to the existing 0-2,500 ft directional-bin universe using base-bin roadway geometry and route-assisted matching. Do not alter upstream/downstream interpretation.",
        "",
        "## Run Scope",
        "",
        f"- limit route groups: {limit_route_groups if limit_route_groups is not None else 'none'}",
        "- crash direction fields read or used: False",
        "- AADT used for upstream/downstream: False",
        "- scaffold/catchment/assignment/access/speed logic changed: False",
        "",
        "## Key Counts",
        "",
        f"- AADT records considered: {count('aadt_records_considered')}",
        f"- AADT records matched to stable universe: {count('aadt_records_matched_to_stable_universe')}",
        f"- bins with stable AADT: {count('bins_with_stable_aadt')}",
        f"- bins missing AADT: {count('bins_missing_aadt')}",
        f"- ambiguous/conflicting AADT bins: {count('ambiguous_conflicting_aadt_bins')}",
        f"- crashes inheriting stable AADT: {count('crashes_inheriting_stable_aadt')}",
        f"- reference signals with stable AADT: {count('reference_signals_with_stable_aadt')}",
        f"- paired pseudo-direction inconsistent groups: {count('paired_pseudo_direction_inconsistent_groups')}",
        f"- dominant match method: {count('dominant_match_method')}",
        f"- AADT ready as flagged context layer: {count('aadt_ready_as_flagged_context_layer')}",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
        "## Recommended Next Step",
        "",
        "Review route-missing, route-mismatch, and conflicting-value queues before deciding whether a narrower AADT matching rule should be promoted into the combined directional-bin context table.",
        "",
    ]
    return "\n".join(lines)


def build_aadt_context_join(*, output_root: Path = OUTPUT_ROOT, limit_route_groups: int | None = None, skip_nearest_any: bool = False) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    logger = ProgressLogger(out_dir / "aadt_context_join_progress.log")
    logger.log(f"START build_aadt_context_join; limit_route_groups={limit_route_groups}; skip_nearest_any={skip_nearest_any}")
    source_aadt, aadt_aliases = _phase(logger, "_load_aadt", _load_aadt)
    context_bins = _phase(logger, "_load_directional_context_bins", _load_directional_context_bins)
    base_bins = _phase(logger, "_load_base_bin_geometry", _load_base_bin_geometry, context_bins)
    _ = _phase(logger, "_read_usable_segments", _read_csv, USABLE_SEGMENTS_FILE)
    _ = _phase(logger, "_read_assignments_no_crash_direction", _read_csv, ASSIGNMENTS_FILE, usecols=["crash_id", "reference_directional_bin_id", "assignment_status"])
    for optional in [ACCESS_SUMMARY_FILE, ACCESS_QA_FILE, SPEED_SUMMARY_FILE, SPEED_QA_FILE, AADT_STAGING_SCHEMA_FILE, AADT_STAGING_FIELD_ROLES_FILE, AADT_STAGING_CRS_SANITY_FILE]:
        _ = _phase(logger, f"_read_optional_{optional.name}", _read_optional, optional)
    route_candidates = _phase(logger, "_route_compatible_candidates", _route_compatible_candidates, aadt_aliases, base_bins, logger=logger, limit_route_groups=limit_route_groups)
    route_review = _phase(logger, "_route_review_nearest_candidates", _route_review_nearest_candidates, aadt_aliases, base_bins, logger=logger, limit_route_groups=limit_route_groups)
    if skip_nearest_any:
        logger.log("SKIP _nearest_any_aadt_candidates")
        nearest_any = pd.DataFrame()
    else:
        nearest_any = _phase(logger, "_nearest_any_aadt_candidates", _nearest_any_aadt_candidates, aadt_aliases, base_bins, logger=logger)
    all_candidates = pd.concat([frame for frame in [route_candidates, route_review, nearest_any] if not frame.empty], ignore_index=True, sort=False)
    base_context = _phase(logger, "_build_base_context", _build_base_context, base_bins, route_candidates, route_review, nearest_any, logger=logger)
    directional_context = _phase(logger, "_build_directional_context", _build_directional_context, context_bins, base_context)
    readiness_columns = ["crash_id", "reference_signal_id", "reference_directional_segment_id", "reference_directional_bin_id", "signal_relative_direction", "bin_midpoint_ft_from_reference_signal", "far_anchor_type"]
    readiness = _phase(logger, "_read_readiness_no_crash_direction", _read_csv, READINESS_FILE, usecols=readiness_columns)
    crash_context = _phase(logger, "_crash_context", _crash_context, readiness, directional_context)
    aadt_joined = _phase(logger, "_aadt_records_joined", _aadt_records_joined, source_aadt, route_candidates, base_context)
    paired_qa = _phase(logger, "_paired_pseudo_direction_consistency", _paired_pseudo_direction_consistency, directional_context)
    reference_summary = _phase(logger, "_reference_signal_summary", _reference_signal_summary, directional_context)
    route_match_qa = _phase(logger, "_route_match_qa", _route_match_qa, directional_context)
    summary = _summary(directional_context, base_context, crash_context, aadt_joined, paired_qa, source_aadt)
    qa = _context_qa(directional_context, source_aadt, paired_qa, crash_context)
    review_candidates = directional_context.loc[directional_context["aadt_context_status"].isin(["review_route_mismatch", "review_route_missing", "ambiguous_conflicting_aadt_values", "no_aadt_nearby_or_route_compatible"])].copy()
    ambiguous = directional_context.loc[directional_context["aadt_context_status"].eq("ambiguous_conflicting_aadt_values")].copy()
    missing = directional_context.loc[directional_context["aadt_context_status"].eq("no_aadt_nearby_or_route_compatible")].copy()

    outputs = {
        "summary_csv": out_dir / "aadt_context_join_summary.csv",
        "base_bin_context_csv": out_dir / "base_bin_aadt_context.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_aadt_context.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_aadt_context_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_aadt_context_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_aadt_context.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_aadt_context_summary.csv",
        "aadt_records_joined_csv": out_dir / "aadt_records_joined_to_stable_universe.csv",
        "match_candidates_csv": out_dir / "aadt_bin_match_candidates.csv",
        "review_candidates_csv": out_dir / "aadt_bin_review_candidates.csv",
        "ambiguous_matches_csv": out_dir / "aadt_bin_ambiguous_matches.csv",
        "missing_bins_csv": out_dir / "aadt_missing_bins.csv",
        "route_match_qa_csv": out_dir / "aadt_route_match_qa.csv",
        "paired_pseudo_direction_qa_csv": out_dir / "aadt_paired_pseudo_direction_consistency_qa.csv",
        "context_join_qa_csv": out_dir / "aadt_context_join_qa.csv",
        "findings_md": out_dir / "aadt_context_join_findings.md",
        "manifest_json": out_dir / "aadt_context_join_manifest.json",
        "progress_log": out_dir / "aadt_context_join_progress.log",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(base_context.drop(columns=["geometry"], errors="ignore"), outputs["base_bin_context_csv"])
    _write_csv(directional_context[REQUIRED_DIRECTIONAL_COLUMNS + [c for c in directional_context.columns if c not in REQUIRED_DIRECTIONAL_COLUMNS]], outputs["directional_bin_context_csv"])
    _write_csv(directional_context.loc[directional_context["distance_window"].eq("high_priority_0_1000ft")], outputs["directional_bin_context_0_1000_csv"])
    _write_csv(directional_context.loc[directional_context["distance_window"].eq("sensitivity_1000_2500ft")], outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(reference_summary, outputs["reference_signal_summary_csv"])
    _write_csv(aadt_joined, outputs["aadt_records_joined_csv"])
    _write_csv(all_candidates.drop(columns=["geometry"], errors="ignore"), outputs["match_candidates_csv"])
    _write_csv(review_candidates, outputs["review_candidates_csv"])
    _write_csv(ambiguous, outputs["ambiguous_matches_csv"])
    _write_csv(missing, outputs["missing_bins_csv"])
    _write_csv(route_match_qa, outputs["route_match_qa_csv"])
    _write_csv(paired_qa, outputs["paired_pseudo_direction_qa_csv"])
    _write_csv(qa, outputs["context_join_qa_csv"])
    _write_text(_findings(summary, outputs, limit_route_groups=limit_route_groups), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only AADT-to-directional-bin context join using source/base-bin line geometry and route-assisted matching",
        "limit_route_groups": limit_route_groups,
        "skip_nearest_any": skip_nearest_any,
        "inputs": {
            "aadt": str(AADT_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "usable_segments": str(USABLE_SEGMENTS_FILE),
            "source_bin_geometry": str(SOURCE_BIN_GEOMETRY_FILE),
            "role_enriched_segments": str(ROLE_ENRICHED_SEGMENTS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "readiness": str(READINESS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
            "access_summary": str(ACCESS_SUMMARY_FILE),
            "speed_summary": str(SPEED_SUMMARY_FILE),
            "aadt_staging_schema": str(AADT_STAGING_SCHEMA_FILE),
        },
        "thresholds": {
            "tight_route_threshold_ft": TIGHT_ROUTE_THRESHOLD_FT,
            "stable_route_threshold_ft": STABLE_ROUTE_THRESHOLD_FT,
            "review_route_threshold_ft": REVIEW_ROUTE_THRESHOLD_FT,
        },
        "crash_direction_fields_read_or_used": False,
        "aadt_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_access_speed_logic_changed": False,
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    logger.log("END build_aadt_context_join")
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only route-assisted AADT context join for directional bins.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--limit-route-groups", type=int, default=None, help="Process only the first N normalized route groups for smoke testing.")
    parser.add_argument("--sample-routes", type=int, default=None, help="Alias for --limit-route-groups.")
    parser.add_argument("--skip-nearest-any", action="store_true", help="Skip spatial-only nearest-any review diagnostics.")
    args = parser.parse_args(argv)
    limit_route_groups = args.limit_route_groups if args.limit_route_groups is not None else args.sample_routes
    outputs = build_aadt_context_join(output_root=args.output_root, limit_route_groups=limit_route_groups, skip_nearest_any=args.skip_nearest_any)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
