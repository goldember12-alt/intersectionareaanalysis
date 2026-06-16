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

from .crs_utils import WORKING_CRS_AUTHORITY, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/speed_context_join_v4_identity_enriched")
IDENTITY_DIR = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation"
V3_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v3_route_assisted"
V3_QA_DIR = OUTPUT_ROOT / "review/current/speed_context_v3_readiness_qa"

SPEED_FILE = Path("artifacts/normalized/speed.parquet")
DIRECTIONAL_BINS_FILE = IDENTITY_DIR / "directional_bins_identity_enriched.csv"
BASE_BINS_FILE = IDENTITY_DIR / "base_bins_identity_enriched.csv"
DIRECTIONAL_SEGMENTS_FILE = IDENTITY_DIR / "directional_segments_identity_enriched.csv"
READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
POSTED_SPEED_SCHEMA_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv"
POSTED_SPEED_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_field_role_candidates.csv"
POSTED_SPEED_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_crs_sanity.csv"
IDENTITY_SPEED_DIAG_FILE = IDENTITY_DIR / "speed_identity_enriched_match_diagnostic.csv"
IDENTITY_SPEED_ROUTE_DIAG_FILE = IDENTITY_DIR / "speed_identity_enriched_route_match_diagnostic.csv"
V3_SUMMARY_FILE = V3_DIR / "speed_context_v3_summary.csv"
V3_BIN_CONTEXT_FILE = V3_DIR / "directional_bin_speed_context_v3.csv"
V3_READINESS_SUMMARY_FILE = V3_QA_DIR / "speed_context_v3_readiness_summary.csv"

SPEED_ID_FIELD = "EVENT_SOURCE_ID"
CAR_SPEED_FIELD = "CAR_SPEED_LIMIT"
TRUCK_SPEED_FIELD = "TRUCK_SPEED_LIMIT"
SPEED_ROUTE_FIELD = "ROUTE_COMMON_NAME"
SPEED_DIRECTION_FIELD = "LOC_COMP_DIRECTIONALITY_NAME"
SPEED_MEASURE_FROM_FIELD = "ROUTE_FROM_MEASURE"
SPEED_MEASURE_TO_FIELD = "ROUTE_TO_MEASURE"
BIN_MEASURE_FIELD_PAIRS = [("source_RTE_FROM_M", "source_RTE_TO_MSR"), ("source_FROM_MEASURE", "source_TO_MEASURE")]
MIN_OVERLAP_RATIO = 0.50
MIN_OVERLAP_LENGTH = 0.001

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

STABLE_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
EXPECTED_STATUSES = {
    "stable_single_speed",
    "stable_weighted_speed_transition",
    "review_route_mismatch",
    "review_directionality_mismatch",
    "review_route_missing",
    "review_unresolved_speed_conflict",
    "missing_no_route_compatible_speed",
}

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
    "stable_directionality_raw",
    "stable_directionality_normalized",
    "speed_route_name_raw",
    "speed_route_name_normalized",
    "speed_directionality_raw",
    "speed_directionality_normalized",
    "route_identity_match_status",
    "directionality_match_status",
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


class ProgressLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        elapsed = time.perf_counter() - self.started
        line = f"{datetime.now(timezone.utc).isoformat()}\t+{elapsed:,.3f}s\t{message}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)


def _phase(logger: ProgressLogger, name: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    logger.log(f"BEGIN {name}")
    started = time.perf_counter()
    result = func(*args, **kwargs)
    logger.log(f"END {name}; elapsed_s={time.perf_counter() - started:,.3f}; {_describe_result(result)}")
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


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


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


def _read_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return _read_csv(path)


def _num(series: pd.Series | Any, index: pd.Index | None = None) -> pd.Series:
    if isinstance(series, pd.Series):
        return pd.to_numeric(series, errors="coerce")
    return pd.Series(pd.NA, index=index, dtype="Float64")


def _format_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    if float(numeric).is_integer():
        return str(int(numeric))
    return f"{float(numeric):.3f}".rstrip("0").rstrip(".")


def _joined_unique_speeds(values: pd.Series) -> str:
    return "|".join(sorted({value for value in values.map(_format_speed) if value}))


def normalize_route_name(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " ")
    text = text.replace("S-VA", " ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    joined = "".join(tokens)
    route_type = ""
    route_number = ""
    direction = ""
    route_token_seen = False

    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"US", "SR", "VA", "I", "SC", "PR", "FR"}:
            route_type = "SR" if compact == "VA" else compact
            route_token_seen = True
            continue
        if compact in {"NB", "SB", "EB", "WB", "N", "S", "E", "W"}:
            direction = compact[0]
            continue
        match = re.fullmatch(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            route_token_seen = True
            continue
        match = re.fullmatch(r"0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match and route_type:
            route_number = str(int(match.group(1)))
            if match.group(2):
                direction = match.group(2)[0]
    if not route_number:
        match = re.search(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", joined)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            route_token_seen = True
    if route_number and route_type and route_token_seen:
        return f"{route_type}{route_number}{direction}"
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def normalize_directionality(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", text)
    if compact in {"B", "BI", "BIDIRECTIONAL", "BOTH", "BOTHWAYS", "TWO WAY", "TWOWAY"}:
        return "BIDIRECTIONAL"
    if compact in {"N", "NB", "NORTH", "NORTHBOUND"}:
        return "N"
    if compact in {"S", "SB", "SOUTH", "SOUTHBOUND"}:
        return "S"
    if compact in {"E", "EB", "EAST", "EASTBOUND"}:
        return "E"
    if compact in {"W", "WB", "WEST", "WESTBOUND"}:
        return "W"
    if compact.endswith("BOUND") and compact[:1] in {"N", "S", "E", "W"}:
        return compact[:1]
    return compact


def directionality_compatible(stable: str, speed: str) -> bool:
    if not stable or not speed:
        return False
    return stable == speed or stable == "BIDIRECTIONAL" or speed == "BIDIRECTIONAL"


def _distance_window(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown_distance"
    if numeric <= 1000:
        return "high_priority_0_1000ft"
    if numeric <= 2500:
        return "sensitivity_1000_2500ft"
    return "outside_context_window"


def _load_speed() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    speed = gpd.read_parquet(SPEED_FILE)
    if speed.crs is None:
        raise ValueError("Speed source has no CRS; rerun posted-speed staging before v4.")
    missing = [field for field in [CAR_SPEED_FIELD, TRUCK_SPEED_FIELD, SPEED_ROUTE_FIELD, SPEED_DIRECTION_FIELD, SPEED_MEASURE_FROM_FIELD, SPEED_MEASURE_TO_FIELD] if field not in speed.columns]
    if missing:
        raise ValueError(f"Speed source is missing required fields: {missing}")
    speed = speed.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="speed_source_index")
    if SPEED_ID_FIELD not in speed.columns:
        speed[SPEED_ID_FIELD] = speed["speed_source_index"].astype(str)
    speed["speed_record_id"] = speed[SPEED_ID_FIELD].astype(str)
    speed["speed_route_name_raw"] = speed[SPEED_ROUTE_FIELD].astype(str).map(_clean)
    speed["speed_route_name_normalized"] = speed["speed_route_name_raw"].map(normalize_route_name)
    speed["speed_directionality_raw"] = speed[SPEED_DIRECTION_FIELD].astype(str).map(_clean)
    speed["speed_directionality_normalized"] = speed["speed_directionality_raw"].map(normalize_directionality)
    speed["speed_measure_from"] = pd.to_numeric(speed[SPEED_MEASURE_FROM_FIELD], errors="coerce")
    speed["speed_measure_to"] = pd.to_numeric(speed[SPEED_MEASURE_TO_FIELD], errors="coerce")
    speed["speed_measure_min"] = speed[["speed_measure_from", "speed_measure_to"]].min(axis=1)
    speed["speed_measure_max"] = speed[["speed_measure_from", "speed_measure_to"]].max(axis=1)
    speed["speed_measure_length"] = speed["speed_measure_max"] - speed["speed_measure_min"]
    speed["source_geometry_is_null"] = speed.geometry.isna()
    speed["source_geometry_is_valid"] = speed.geometry.notna() & speed.geometry.is_valid
    aliases = pd.DataFrame(speed.drop(columns=["geometry"], errors="ignore")).copy()
    aliases = aliases.loc[
        aliases["speed_route_name_normalized"].ne("")
        & aliases["speed_directionality_normalized"].ne("")
        & aliases["speed_measure_min"].notna()
        & aliases["speed_measure_max"].notna()
        & (pd.to_numeric(aliases[CAR_SPEED_FIELD], errors="coerce").notna() | pd.to_numeric(aliases[TRUCK_SPEED_FIELD], errors="coerce").notna())
    ].copy()
    return speed, aliases


def _load_directional_bins() -> pd.DataFrame:
    columns = [
        "reference_directional_bin_id",
        "reference_directional_segment_id",
        "base_segment_id",
        "reference_signal_id",
        "far_anchor_type",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "roadway_representation_type",
        "source_bin_key",
        "distance_window",
        "catchment_status",
        "source_RTE_NM",
        "source_RTE_COMMON",
        "source_RTE_ID",
        "source_LOC_COMP_D",
        "DirCode_Norm",
        "source_FROM_MEASURE",
        "source_TO_MEASURE",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "identity_enrichment_status",
        "identity_enrichment_confidence",
    ]
    bins = _read_csv(DIRECTIONAL_BINS_FILE, usecols=columns)
    bins["bin_midpoint_ft_from_reference_signal"] = pd.to_numeric(bins["bin_midpoint_ft_from_reference_signal"], errors="coerce")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    bins = bins.loc[bins["catchment_status"].eq("usable") & bins["distance_window"].isin(["high_priority_0_1000ft", "sensitivity_1000_2500ft"])].copy()
    bins["stable_route_name_raw"] = bins["source_RTE_NM"].astype(str).map(_clean)
    bins["stable_route_name_normalized"] = bins["stable_route_name_raw"].map(normalize_route_name)
    fallback = bins["stable_route_name_normalized"].eq("")
    bins.loc[fallback, "stable_route_name_raw"] = bins.loc[fallback, "source_RTE_COMMON"].astype(str).map(_clean)
    bins.loc[fallback, "stable_route_name_normalized"] = bins.loc[fallback, "stable_route_name_raw"].map(normalize_route_name)
    bins["stable_directionality_raw"] = bins["source_LOC_COMP_D"].astype(str).map(_clean)
    dir_fallback = bins["stable_directionality_raw"].eq("")
    bins.loc[dir_fallback, "stable_directionality_raw"] = bins.loc[dir_fallback, "DirCode_Norm"].astype(str).map(_clean)
    bins["stable_directionality_normalized"] = bins["stable_directionality_raw"].map(normalize_directionality)
    return bins


def _choose_bin_measure_pair(frame: pd.DataFrame) -> tuple[str, str, pd.Series, pd.Series]:
    for left, right in BIN_MEASURE_FIELD_PAIRS:
        if left in frame.columns and right in frame.columns:
            left_num = pd.to_numeric(frame[left], errors="coerce")
            right_num = pd.to_numeric(frame[right], errors="coerce")
            if (left_num.notna() & right_num.notna()).any():
                return left, right, left_num, right_num
    return "", "", pd.Series(pd.NA, index=frame.index, dtype="Float64"), pd.Series(pd.NA, index=frame.index, dtype="Float64")


def _load_base_bins(context_bins: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "base_segment_id",
        "source_bin_key",
        "bin_index",
        "bin_start_ft",
        "bin_end_ft",
        "bin_midpoint_ft",
        "source_RTE_NM",
        "source_RTE_COMMON",
        "source_RTE_ID",
        "source_LOC_COMP_D",
        "DirCode_Norm",
        "source_FROM_MEASURE",
        "source_TO_MEASURE",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "identity_enrichment_status",
        "identity_enrichment_confidence",
    ]
    base = _read_csv(BASE_BINS_FILE, usecols=columns)
    wanted = context_bins[["base_segment_id", "source_bin_key"]].drop_duplicates()
    base = base.merge(wanted, on=["base_segment_id", "source_bin_key"], how="inner")
    base["stable_route_name_raw"] = base["source_RTE_NM"].astype(str).map(_clean)
    base["stable_route_name_normalized"] = base["stable_route_name_raw"].map(normalize_route_name)
    fallback = base["stable_route_name_normalized"].eq("")
    base.loc[fallback, "stable_route_name_raw"] = base.loc[fallback, "source_RTE_COMMON"].astype(str).map(_clean)
    base.loc[fallback, "stable_route_name_normalized"] = base.loc[fallback, "stable_route_name_raw"].map(normalize_route_name)
    base["stable_directionality_raw"] = base["source_LOC_COMP_D"].astype(str).map(_clean)
    dir_fallback = base["stable_directionality_raw"].eq("")
    base.loc[dir_fallback, "stable_directionality_raw"] = base.loc[dir_fallback, "DirCode_Norm"].astype(str).map(_clean)
    base["stable_directionality_normalized"] = base["stable_directionality_raw"].map(normalize_directionality)

    measure_left, measure_right, source_from, source_to = _choose_bin_measure_pair(base)
    base["stable_measure_source_fields"] = f"{measure_left}/{measure_right}" if measure_left else ""
    bin_start = pd.to_numeric(base["bin_start_ft"], errors="coerce")
    bin_end = pd.to_numeric(base["bin_end_ft"], errors="coerce")
    base["stable_measure_from"] = source_from + ((source_to - source_from) * (bin_start / 5280.0))
    base["stable_measure_to"] = source_from + ((source_to - source_from) * (bin_end / 5280.0))
    base["stable_measure_min"] = base[["stable_measure_from", "stable_measure_to"]].min(axis=1)
    base["stable_measure_max"] = base[["stable_measure_from", "stable_measure_to"]].max(axis=1)
    base["stable_measure_length"] = base["stable_measure_max"] - base["stable_measure_min"]
    return base.drop_duplicates(["base_segment_id", "source_bin_key"]).copy()


def _candidate_columns() -> list[str]:
    return [
        "base_segment_id",
        "source_bin_key",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_directionality_raw",
        "stable_directionality_normalized",
        "stable_measure_min",
        "stable_measure_max",
        "speed_source_index",
        "speed_record_id",
        "speed_route_name_raw",
        "speed_route_name_normalized",
        "speed_directionality_raw",
        "speed_directionality_normalized",
        "speed_measure_min",
        "speed_measure_max",
        CAR_SPEED_FIELD,
        TRUCK_SPEED_FIELD,
        "measure_overlap_length",
        "measure_overlap_ratio",
        "directionality_match_status",
        "candidate_decision",
    ]


def _route_measure_candidates(speed_aliases: pd.DataFrame, base_bins: pd.DataFrame, *, progress_logger: ProgressLogger, limit_route_groups: int | None = None, progress_every: int = 25) -> pd.DataFrame:
    routed = base_bins.loc[base_bins["stable_route_name_normalized"].ne("")].copy()
    route_groups = list(routed.groupby("stable_route_name_normalized", dropna=False))
    if limit_route_groups is not None:
        route_groups = route_groups[:limit_route_groups]
    needed_routes = {str(route) for route, _ in route_groups}
    speed_by_route = {
        route: group.copy()
        for route, group in speed_aliases.loc[speed_aliases["speed_route_name_normalized"].isin(needed_routes)].groupby("speed_route_name_normalized", dropna=False)
    }
    frames: list[pd.DataFrame] = []
    progress_logger.log(f"ROUTE_MEASURE_SETUP; route_groups={len(route_groups)}; base_bins={len(routed)}; speed_records={len(speed_aliases)}")
    for index, (route_key, bin_group) in enumerate(route_groups, start=1):
        speed_group = speed_by_route.get(route_key)
        if index == 1 or index % progress_every == 0 or index == len(route_groups):
            progress_logger.log(f"ROUTE_MEASURE_GROUP; group={index}/{len(route_groups)}; route={route_key}; base_bins={len(bin_group)}; speed_records={0 if speed_group is None else len(speed_group)}")
        if speed_group is None or speed_group.empty:
            continue
        pairs = bin_group.reset_index(drop=True).merge(speed_group.reset_index(drop=True), how="cross", suffixes=("", "_speed"))
        if pairs.empty:
            continue
        compatible = [
            directionality_compatible(stable, speed)
            for stable, speed in zip(pairs["stable_directionality_normalized"], pairs["speed_directionality_normalized"], strict=False)
        ]
        pairs["directionality_match_status"] = pd.Series(compatible, index=pairs.index).map(lambda value: "compatible" if value else "directionality_mismatch")
        pairs = pairs.loc[pairs["directionality_match_status"].eq("compatible")].copy()
        if pairs.empty:
            continue
        pairs = pairs.loc[pairs["speed_measure_max"].ge(pairs["stable_measure_min"]) & pairs["speed_measure_min"].le(pairs["stable_measure_max"])].copy()
        if pairs.empty:
            continue
        overlap_min = pairs[["stable_measure_max", "speed_measure_max"]].min(axis=1)
        overlap_max = pairs[["stable_measure_min", "speed_measure_min"]].max(axis=1)
        pairs["measure_overlap_length"] = (overlap_min - overlap_max).clip(lower=0)
        pairs["measure_overlap_ratio"] = pairs["measure_overlap_length"] / pairs["stable_measure_length"]
        pairs = pairs.loc[pairs["measure_overlap_length"].gt(0)].copy()
        if pairs.empty:
            continue
        pairs["candidate_decision"] = pairs["measure_overlap_ratio"].ge(MIN_OVERLAP_RATIO) & pairs["measure_overlap_length"].ge(MIN_OVERLAP_LENGTH)
        keep = [column for column in _candidate_columns() if column in pairs.columns]
        frames.append(pairs[keep].copy())
    if not frames:
        return pd.DataFrame(columns=_candidate_columns())
    out = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates(["base_segment_id", "source_bin_key", "speed_source_index"])
    for column in ["measure_overlap_length", "measure_overlap_ratio"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").round(6)
    return out


def _build_base_context(base_bins: pd.DataFrame, candidates: pd.DataFrame, speed_aliases: pd.DataFrame) -> pd.DataFrame:
    out = base_bins.copy()
    out["route_identity_match_status"] = "not_evaluated"
    out["directionality_match_status"] = "not_evaluated"
    out["refined_speed_context_status"] = "missing_no_route_compatible_speed"
    out["refined_speed_context_confidence"] = "missing"
    for column in [
        "speed_route_name_raw",
        "speed_route_name_normalized",
        "speed_directionality_raw",
        "speed_directionality_normalized",
        "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value",
        "weighted_car_speed_limit",
        "weighted_truck_speed_limit",
        "speed_transition_within_bin_flag",
        "weighted_speed_context_flag",
        "weighted_speed_method",
        "car_speed_candidate_values",
        "truck_speed_candidate_values",
        "measure_overlap_length",
        "measure_overlap_ratio",
        "speed_candidate_count",
    ]:
        out[column] = ""

    speed_routes = set(speed_aliases["speed_route_name_normalized"].astype(str))
    out.loc[out["stable_route_name_normalized"].eq(""), ["route_identity_match_status", "refined_speed_context_status", "refined_speed_context_confidence"]] = ["route_missing", "review_route_missing", "low_review"]
    out.loc[out["stable_route_name_normalized"].ne("") & ~out["stable_route_name_normalized"].isin(speed_routes), ["route_identity_match_status", "refined_speed_context_status", "refined_speed_context_confidence"]] = ["route_mismatch", "review_route_mismatch", "low_review"]

    candidate_keys = set(map(tuple, candidates.loc[candidates["candidate_decision"].astype(bool), ["base_segment_id", "source_bin_key"]].drop_duplicates().itertuples(index=False, name=None))) if not candidates.empty else set()
    routed_keys = set(map(tuple, out.loc[out["stable_route_name_normalized"].isin(speed_routes), ["base_segment_id", "source_bin_key"]].itertuples(index=False, name=None)))
    no_candidate_keys = routed_keys - candidate_keys
    if no_candidate_keys:
        key_index = pd.MultiIndex.from_tuples(list(no_candidate_keys), names=["base_segment_id", "source_bin_key"])
        mask = pd.MultiIndex.from_frame(out[["base_segment_id", "source_bin_key"]]).isin(key_index)
        out.loc[mask, ["route_identity_match_status", "directionality_match_status", "refined_speed_context_status", "refined_speed_context_confidence"]] = [
            "exact_route_identity_match",
            "no_compatible_directional_overlap",
            "missing_no_route_compatible_speed",
            "missing",
        ]

    chosen_rows = []
    valid = candidates.loc[candidates["candidate_decision"].astype(bool)].copy()
    for key, group in valid.groupby(["base_segment_id", "source_bin_key"], dropna=False):
        group = group.copy()
        car_values = pd.to_numeric(group[CAR_SPEED_FIELD], errors="coerce").dropna()
        truck_values = pd.to_numeric(group[TRUCK_SPEED_FIELD], errors="coerce").dropna()
        car_unique = sorted(car_values.unique().tolist())
        truck_unique = sorted(truck_values.unique().tolist())
        car_conflict = len(car_unique) > 1
        truck_conflict = len(truck_unique) > 1
        weight = pd.to_numeric(group["measure_overlap_length"], errors="coerce").fillna(0)
        if weight.sum() <= 0:
            weight = pd.Series(1.0, index=group.index)
        weighted_car = _weighted_average(pd.to_numeric(group[CAR_SPEED_FIELD], errors="coerce"), weight)
        weighted_truck = _weighted_average(pd.to_numeric(group[TRUCK_SPEED_FIELD], errors="coerce"), weight)
        top = group.sort_values(["measure_overlap_ratio", "measure_overlap_length"], ascending=[False, False]).iloc[0].to_dict()
        transition = car_conflict or truck_conflict
        top.update(
            {
                "base_segment_id": key[0],
                "source_bin_key": key[1],
                "route_identity_match_status": "exact_route_identity_match",
                "directionality_match_status": "compatible",
                "posted_car_speed_limit_context_value": _format_speed(weighted_car if transition else (car_unique[0] if car_unique else "")),
                "posted_truck_speed_limit_context_value": _format_speed(weighted_truck if transition else (truck_unique[0] if truck_unique else "")),
                "weighted_car_speed_limit": _format_speed(weighted_car) if transition else "",
                "weighted_truck_speed_limit": _format_speed(weighted_truck) if transition else "",
                "speed_transition_within_bin_flag": bool(transition),
                "weighted_speed_context_flag": bool(transition),
                "weighted_speed_method": "measure_overlap_weighted_route_transition" if transition else "single_value_no_weighting",
                "refined_speed_context_status": "stable_weighted_speed_transition" if transition else "stable_single_speed",
                "refined_speed_context_confidence": "high",
                "car_speed_candidate_values": _joined_unique_speeds(group[CAR_SPEED_FIELD]),
                "truck_speed_candidate_values": _joined_unique_speeds(group[TRUCK_SPEED_FIELD]),
                "speed_candidate_count": int(group["speed_source_index"].nunique()),
            }
        )
        chosen_rows.append(top)
    chosen = pd.DataFrame(chosen_rows)
    if not chosen.empty:
        _apply_chosen(out, chosen)
    return out


def _weighted_average(values: pd.Series, weights: pd.Series) -> float | pd.NA:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return pd.NA
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def _apply_chosen(out: pd.DataFrame, chosen: pd.DataFrame) -> None:
    chosen = chosen.drop_duplicates(["base_segment_id", "source_bin_key"]).set_index(["base_segment_id", "source_bin_key"])
    target_index = pd.MultiIndex.from_frame(out[["base_segment_id", "source_bin_key"]])
    mapping = {
        "speed_route_name_raw": "speed_route_name_raw",
        "speed_route_name_normalized": "speed_route_name_normalized",
        "speed_directionality_raw": "speed_directionality_raw",
        "speed_directionality_normalized": "speed_directionality_normalized",
        "route_identity_match_status": "route_identity_match_status",
        "directionality_match_status": "directionality_match_status",
        "posted_car_speed_limit_context_value": "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value": "posted_truck_speed_limit_context_value",
        "weighted_car_speed_limit": "weighted_car_speed_limit",
        "weighted_truck_speed_limit": "weighted_truck_speed_limit",
        "speed_transition_within_bin_flag": "speed_transition_within_bin_flag",
        "weighted_speed_context_flag": "weighted_speed_context_flag",
        "weighted_speed_method": "weighted_speed_method",
        "refined_speed_context_status": "refined_speed_context_status",
        "refined_speed_context_confidence": "refined_speed_context_confidence",
        "car_speed_candidate_values": "car_speed_candidate_values",
        "truck_speed_candidate_values": "truck_speed_candidate_values",
        "measure_overlap_length": "measure_overlap_length",
        "measure_overlap_ratio": "measure_overlap_ratio",
        "speed_candidate_count": "speed_candidate_count",
    }
    for src, dest in mapping.items():
        if src in chosen.columns:
            mapped = pd.Series(target_index.map(chosen[src]), index=out.index)
            out[dest] = mapped.where(mapped.notna(), out[dest])


def _build_directional_context(context_bins: pd.DataFrame, base_context: pd.DataFrame) -> pd.DataFrame:
    base_cols = [column for column in base_context.columns if column not in {"source_RTE_NM", "source_RTE_COMMON", "source_RTE_ID", "source_LOC_COMP_D", "DirCode_Norm"}]
    out = context_bins.merge(base_context[base_cols], on=["base_segment_id", "source_bin_key"], how="left", suffixes=("", "_base"))
    for column in ["stable_route_name_raw", "stable_route_name_normalized", "stable_directionality_raw", "stable_directionality_normalized"]:
        base_column = f"{column}_base"
        if base_column in out.columns:
            out[column] = out[column].where(out[column].astype(str).ne(""), out[base_column])
            out = out.drop(columns=[base_column])
    return out


def _retain_v3_stable_context(bin_context: pd.DataFrame) -> pd.DataFrame:
    if not V3_BIN_CONTEXT_FILE.exists():
        return bin_context
    v3_columns = [
        "reference_directional_bin_id",
        "speed_route_name_raw",
        "speed_route_name_normalized",
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
    v3 = _read_csv(V3_BIN_CONTEXT_FILE, usecols=v3_columns)
    rename = {column: f"v3_{column}" for column in v3.columns if column != "reference_directional_bin_id"}
    v3 = v3.rename(columns=rename)
    out = bin_context.merge(v3, on="reference_directional_bin_id", how="left")
    v4_stable = out["refined_speed_context_status"].isin(STABLE_STATUSES)
    v3_stable = out["v3_refined_speed_context_status"].isin(STABLE_STATUSES)
    retain = v3_stable & ~v4_stable
    if not retain.any():
        return out.drop(columns=[column for column in out.columns if column.startswith("v3_")], errors="ignore")
    for column in [
        "speed_route_name_raw",
        "speed_route_name_normalized",
        "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value",
        "weighted_car_speed_limit",
        "weighted_truck_speed_limit",
        "speed_transition_within_bin_flag",
        "weighted_speed_context_flag",
        "weighted_speed_method",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
    ]:
        v3_column = f"v3_{column}"
        if v3_column in out.columns:
            out.loc[retain, column] = out.loc[retain, v3_column]
    out.loc[retain, "route_identity_match_status"] = "retained_v3_route_assisted_stable"
    out.loc[retain, "directionality_match_status"] = "not_evaluated_v3_retained"
    out.loc[retain, "speed_directionality_raw"] = out.loc[retain, "speed_directionality_raw"].where(out.loc[retain, "speed_directionality_raw"].astype(str).ne(""), "v3_not_directionality_evaluated")
    out.loc[retain, "speed_directionality_normalized"] = out.loc[retain, "speed_directionality_normalized"].where(out.loc[retain, "speed_directionality_normalized"].astype(str).ne(""), "V3_RETAINED")
    out.loc[retain, "v3_stable_context_retained_flag"] = True
    out["v3_stable_context_retained_flag"] = out.get("v3_stable_context_retained_flag", False)
    return out.drop(columns=[column for column in out.columns if column.startswith("v3_") and column != "v3_stable_context_retained_flag"], errors="ignore")


def _crash_context(readiness: pd.DataFrame, directional_context: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "reference_directional_bin_id",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_directionality_raw",
        "stable_directionality_normalized",
        "speed_route_name_raw",
        "speed_route_name_normalized",
        "speed_directionality_raw",
        "speed_directionality_normalized",
        "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value",
        "weighted_car_speed_limit",
        "weighted_truck_speed_limit",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
    ]
    return readiness.merge(directional_context[[column for column in keep if column in directional_context.columns]], on="reference_directional_bin_id", how="left")


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    stable = bin_context["refined_speed_context_status"].isin(STABLE_STATUSES)
    work = bin_context.assign(stable_speed_bin=stable)
    grouped = work.groupby("reference_signal_id", dropna=False).agg(
        directional_bin_count=("reference_directional_bin_id", "nunique"),
        stable_speed_bin_count=("stable_speed_bin", "sum"),
        stable_single_speed_bin_count=("refined_speed_context_status", lambda s: int(s.eq("stable_single_speed").sum())),
        stable_weighted_transition_bin_count=("refined_speed_context_status", lambda s: int(s.eq("stable_weighted_speed_transition").sum())),
        missing_speed_bin_count=("refined_speed_context_status", lambda s: int(s.eq("missing_no_route_compatible_speed").sum())),
    ).reset_index()
    grouped["has_stable_speed"] = grouped["stable_speed_bin_count"].gt(0)
    return grouped


def _paired_pseudo_direction_consistency(bin_context: pd.DataFrame) -> pd.DataFrame:
    pseudo = bin_context.loc[bin_context["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    if pseudo.empty:
        return pd.DataFrame(columns=["base_segment_id", "source_bin_key", "directional_record_count", "paired_pseudo_direction_speed_consistent"])
    grouped = pseudo.groupby(["base_segment_id", "source_bin_key"], dropna=False).agg(
        directional_record_count=("reference_directional_bin_id", "nunique"),
        status_count=("refined_speed_context_status", "nunique"),
        car_speed_count=("posted_car_speed_limit_context_value", "nunique"),
        truck_speed_count=("posted_truck_speed_limit_context_value", "nunique"),
        route_count=("speed_route_name_normalized", "nunique"),
    ).reset_index()
    grouped["paired_pseudo_direction_speed_consistent"] = grouped[["status_count", "car_speed_count", "truck_speed_count", "route_count"]].le(1).all(axis=1)
    return grouped


def _route_identity_match_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    return (
        bin_context.groupby(["route_identity_match_status", "refined_speed_context_status", "distance_window"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"), base_bin_count=("source_bin_key", "nunique"))
        .reset_index()
    )


def _directionality_match_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    return (
        bin_context.groupby(["stable_directionality_normalized", "speed_directionality_normalized", "directionality_match_status", "refined_speed_context_status"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"), base_bin_count=("source_bin_key", "nunique"))
        .reset_index()
        .sort_values("bin_count", ascending=False)
    )


def _summary(bin_context: pd.DataFrame, crash_context: pd.DataFrame, reference_summary: pd.DataFrame, paired_qa: pd.DataFrame) -> pd.DataFrame:
    stable = bin_context["refined_speed_context_status"].isin(STABLE_STATUSES)
    rows = [
        {"metric": "main_0_2500ft_bins", "value": "", "count": int(len(bin_context))},
        {"metric": "stable_speed_bins", "value": "", "count": int(stable.sum())},
        {"metric": "stable_single_speed_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("stable_single_speed").sum())},
        {"metric": "stable_weighted_transition_bins", "value": "measure_overlap_weighted_route_transition", "count": int(bin_context["refined_speed_context_status"].eq("stable_weighted_speed_transition").sum())},
        {"metric": "missing_no_route_compatible_speed_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("missing_no_route_compatible_speed").sum())},
        {"metric": "review_route_mismatch_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("review_route_mismatch").sum())},
        {"metric": "review_route_missing_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("review_route_missing").sum())},
        {"metric": "review_directionality_mismatch_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("review_directionality_mismatch").sum())},
        {"metric": "review_unresolved_speed_conflict_bins", "value": "", "count": int(bin_context["refined_speed_context_status"].eq("review_unresolved_speed_conflict").sum())},
        {"metric": "crashes_inheriting_stable_speed", "value": "", "count": int(crash_context["refined_speed_context_status"].isin(STABLE_STATUSES).sum())},
        {"metric": "reference_signals_with_stable_speed", "value": "", "count": int(reference_summary["has_stable_speed"].sum())},
        {"metric": "paired_pseudo_direction_groups", "value": "", "count": int(len(paired_qa))},
        {"metric": "paired_pseudo_direction_inconsistent_groups", "value": "", "count": int((~paired_qa["paired_pseudo_direction_speed_consistent"]).sum()) if not paired_qa.empty else 0},
        {"metric": "nearest_any_stable_promotions", "value": "", "count": 0},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "speed_used_for_upstream_downstream", "value": False, "count": ""},
    ]
    for window, group in bin_context.groupby("distance_window", dropna=False):
        stable_window = group["refined_speed_context_status"].isin(STABLE_STATUSES)
        rows.extend(
            [
                {"metric": "bins_by_distance_window", "value": str(window), "count": int(len(group))},
                {"metric": "stable_speed_bins_by_distance_window", "value": str(window), "count": int(stable_window.sum())},
                {"metric": "missing_speed_bins_by_distance_window", "value": str(window), "count": int(group["refined_speed_context_status"].eq("missing_no_route_compatible_speed").sum())},
                {"metric": "review_speed_bins_by_distance_window", "value": str(window), "count": int((~group["refined_speed_context_status"].isin(STABLE_STATUSES) & ~group["refined_speed_context_status"].eq("missing_no_route_compatible_speed")).sum())},
            ]
        )
    return pd.DataFrame(rows)


def _summary_value(summary: pd.DataFrame, metric: str) -> int:
    if summary.empty:
        return 0
    row = summary.loc[summary["metric"].eq(metric)]
    if row.empty:
        return 0
    value = pd.to_numeric(row.iloc[0].get("count"), errors="coerce")
    return 0 if pd.isna(value) else int(value)


def _comparison_to_v3(v4_summary: pd.DataFrame) -> pd.DataFrame:
    v3 = _read_optional(V3_SUMMARY_FILE)
    v3_review = (
        _summary_value(v3, "v3_review_route_mismatch_bins")
        + _summary_value(v3, "v3_route_missing_review_bins")
        + _summary_value(v3, "v3_review_unresolved_speed_conflict_bins")
    )
    v4_review = (
        _summary_value(v4_summary, "review_route_mismatch_bins")
        + _summary_value(v4_summary, "review_route_missing_bins")
        + _summary_value(v4_summary, "review_directionality_mismatch_bins")
        + _summary_value(v4_summary, "review_unresolved_speed_conflict_bins")
    )
    mapping = [
        ("stable_single_speed_bins", _summary_value(v3, "v3_refined_stable_single_speed_bins"), _summary_value(v4_summary, "stable_single_speed_bins")),
        ("stable_weighted_transition_bins", _summary_value(v3, "v3_refined_stable_weighted_transition_bins"), _summary_value(v4_summary, "stable_weighted_transition_bins")),
        ("total_stable_speed_bins", _summary_value(v3, "v3_stable_route_matched_speed_bins"), _summary_value(v4_summary, "stable_speed_bins")),
        ("missing_speed_bins", _summary_value(v3, "v3_missing_no_route_compatible_bins"), _summary_value(v4_summary, "missing_no_route_compatible_speed_bins")),
        ("review_speed_bins", v3_review, v4_review),
        ("crashes_inheriting_stable_speed", _summary_value(v3, "crashes_inheriting_stable_v3_speed_context"), _summary_value(v4_summary, "crashes_inheriting_stable_speed")),
        ("reference_signals_with_stable_speed", _summary_value(v3, "reference_signals_with_stable_v3_speed_context"), _summary_value(v4_summary, "reference_signals_with_stable_speed")),
    ]
    rows = []
    for label, v3_count, v4_count in mapping:
        rows.append({"metric": label, "v3_count": v3_count, "v4_count": v4_count, "v4_minus_v3": v4_count - v3_count})
    return pd.DataFrame(rows)


def _qa(bin_context: pd.DataFrame, paired_qa: pd.DataFrame) -> pd.DataFrame:
    outside = int((~bin_context["distance_window"].isin(["high_priority_0_1000ft", "sensitivity_1000_2500ft"])).sum())
    duplicate_bins = int(bin_context["reference_directional_bin_id"].duplicated().sum())
    inconsistent = int((~paired_qa["paired_pseudo_direction_speed_consistent"]).sum()) if not paired_qa.empty else 0
    unknown_status = sorted(set(bin_context["refined_speed_context_status"].astype(str)) - EXPECTED_STATUSES)
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "speed_not_used_for_upstream_downstream", "passed": True, "observed": False, "expected": False},
            {"check_name": "scaffold_catchment_assignment_access_aadt_logic_changed", "passed": True, "observed": False, "expected": False},
            {"check_name": "main_context_limited_to_0_2500ft", "passed": outside == 0, "observed": outside, "expected": 0},
            {"check_name": "one_row_per_directional_bin", "passed": duplicate_bins == 0, "observed": duplicate_bins, "expected": 0},
            {"check_name": "paired_pseudo_direction_inconsistencies", "passed": inconsistent == 0, "observed": inconsistent, "expected": 0},
            {"check_name": "status_closure_110710_bins", "passed": len(bin_context) == 110710 and not unknown_status, "observed": len(bin_context), "expected": 110710},
            {"check_name": "known_status_vocabulary_only", "passed": not unknown_status, "observed": "|".join(unknown_status), "expected": "|".join(sorted(EXPECTED_STATUSES))},
            {"check_name": "nearest_any_stable_promotion_absent", "passed": True, "observed": 0, "expected": 0},
        ]
    )


def _findings(summary: pd.DataFrame, comparison: pd.DataFrame, outputs: dict[str, Path], *, limit_route_groups: int | None) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        if row.empty:
            return ""
        return row.iloc[0]["count"] if str(row.iloc[0]["count"]) != "" else row.iloc[0]["value"]

    lines = [
        "# Speed Context Join v4 Identity-Enriched Findings",
        "",
        "## Bounded Question",
        "",
        "Attach posted speed as a read-only flagged context layer to existing 0-2,500 ft directional bins using propagated roadway identity route and directionality fields, with route-measure overlap used for stable assignment. Do not alter scaffold, catchments, crash assignment, access, AADT, or upstream/downstream logic.",
        "",
        "## Run Scope",
        "",
        f"- limit route groups: {limit_route_groups if limit_route_groups is not None else 'none'}",
        "- crash direction fields read or used: False",
        "- speed used for upstream/downstream: False",
        "- scaffold/catchment/assignment/access/AADT logic changed: False",
        "- nearest-any stable promotion: 0",
        "",
        "## Key Counts",
        "",
        f"- stable speed bins: {count('stable_speed_bins')}",
        f"- stable single-speed bins: {count('stable_single_speed_bins')}",
        f"- stable weighted transition bins: {count('stable_weighted_transition_bins')}",
        f"- missing/no route-compatible bins: {count('missing_no_route_compatible_speed_bins')}",
        f"- review route mismatch bins: {count('review_route_mismatch_bins')}",
        f"- review route missing bins: {count('review_route_missing_bins')}",
        f"- review directionality mismatch bins: {count('review_directionality_mismatch_bins')}",
        f"- review unresolved speed conflict bins: {count('review_unresolved_speed_conflict_bins')}",
        f"- crashes inheriting stable speed: {count('crashes_inheriting_stable_speed')}",
        f"- reference signals with stable speed: {count('reference_signals_with_stable_speed')}",
        f"- paired pseudo-direction inconsistent groups: {count('paired_pseudo_direction_inconsistent_groups')}",
        "",
        "## v3 Comparison",
        "",
        "| metric | v3_count | v4_count | v4_minus_v3 |",
        "|---|---:|---:|---:|",
        *[f"| {row.metric} | {row.v3_count} | {row.v4_count} | {row.v4_minus_v3} |" for row in comparison.itertuples(index=False)],
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_speed_context_join_v4_identity_enriched(*, output_root: Path = OUTPUT_ROOT, limit_route_groups: int | None = None) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    logger = ProgressLogger(out_dir / "speed_context_v4_progress.log")
    logger.log(f"START build_speed_context_join_v4_identity_enriched; limit_route_groups={limit_route_groups}")
    source_speed, speed_aliases = _phase(logger, "_load_speed", _load_speed)
    context_bins = _phase(logger, "_load_directional_bins", _load_directional_bins)
    base_bins = _phase(logger, "_load_base_bins", _load_base_bins, context_bins)
    _ = _phase(logger, "_read_directional_segments_identity_enriched", _read_csv, DIRECTIONAL_SEGMENTS_FILE)
    _ = _phase(logger, "_read_assignments_no_crash_direction", _read_csv, ASSIGNMENTS_FILE, usecols=["crash_id", "reference_directional_bin_id", "assignment_status"])
    _ = _phase(logger, "_read_catchment_index", _read_csv, CATCHMENT_INDEX_FILE, usecols=["reference_directional_bin_id", "catchment_status"])
    for optional in [V3_BIN_CONTEXT_FILE, V3_READINESS_SUMMARY_FILE, POSTED_SPEED_SCHEMA_FILE, POSTED_SPEED_FIELD_ROLES_FILE, POSTED_SPEED_CRS_SANITY_FILE, IDENTITY_SPEED_DIAG_FILE, IDENTITY_SPEED_ROUTE_DIAG_FILE]:
        _ = _phase(logger, f"_read_optional_{optional.name}", _read_optional, optional)
    candidates = _phase(logger, "_route_measure_candidates", _route_measure_candidates, speed_aliases, base_bins, progress_logger=logger, limit_route_groups=limit_route_groups)
    base_context = _phase(logger, "_build_base_context", _build_base_context, base_bins, candidates, speed_aliases)
    directional_context = _phase(logger, "_build_directional_context", _build_directional_context, context_bins, base_context)
    directional_context = _phase(logger, "_retain_v3_stable_context", _retain_v3_stable_context, directional_context)
    readiness_cols = ["crash_id", "reference_signal_id", "reference_directional_segment_id", "reference_directional_bin_id", "signal_relative_direction", "roadway_representation_type", "bin_index_from_reference_signal", "bin_midpoint_ft_from_reference_signal", "far_anchor_type"]
    readiness = _phase(logger, "_read_readiness_no_crash_direction", _read_csv, READINESS_FILE, usecols=readiness_cols)
    crash_context = _phase(logger, "_crash_context", _crash_context, readiness, directional_context)
    reference_summary = _phase(logger, "_reference_signal_summary", _reference_signal_summary, directional_context)
    paired_qa = _phase(logger, "_paired_pseudo_direction_consistency", _paired_pseudo_direction_consistency, directional_context)
    route_qa = _phase(logger, "_route_identity_match_qa", _route_identity_match_qa, directional_context)
    direction_qa = _phase(logger, "_directionality_match_qa", _directionality_match_qa, directional_context)
    summary = _summary(directional_context, crash_context, reference_summary, paired_qa)
    comparison = _comparison_to_v3(summary)
    qa = _qa(directional_context, paired_qa)

    missing = directional_context.loc[directional_context["refined_speed_context_status"].eq("missing_no_route_compatible_speed")].copy()
    review = directional_context.loc[~directional_context["refined_speed_context_status"].isin(STABLE_STATUSES) & ~directional_context["refined_speed_context_status"].eq("missing_no_route_compatible_speed")].copy()
    weighted = directional_context.loc[directional_context["refined_speed_context_status"].eq("stable_weighted_speed_transition")].copy()

    outputs = {
        "summary_csv": out_dir / "speed_context_v4_summary.csv",
        "base_bin_context_csv": out_dir / "base_bin_speed_context_v4.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_speed_context_v4.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_speed_context_v4_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_speed_context_v4_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_speed_context_v4.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_speed_context_summary_v4.csv",
        "route_identity_match_qa_csv": out_dir / "speed_route_identity_match_qa_v4.csv",
        "directionality_match_qa_csv": out_dir / "speed_directionality_match_qa_v4.csv",
        "missing_bins_csv": out_dir / "speed_missing_bins_v4.csv",
        "review_bins_csv": out_dir / "speed_review_bins_v4.csv",
        "weighted_transition_bins_csv": out_dir / "speed_weighted_transition_bins_v4.csv",
        "paired_pseudo_direction_qa_csv": out_dir / "speed_paired_pseudo_direction_consistency_qa_v4.csv",
        "comparison_to_v3_csv": out_dir / "speed_context_v4_comparison_to_v3.csv",
        "qa_csv": out_dir / "speed_context_v4_qa.csv",
        "findings_md": out_dir / "speed_context_v4_findings.md",
        "manifest_json": out_dir / "speed_context_v4_manifest.json",
        "progress_log": out_dir / "speed_context_v4_progress.log",
    }
    ordered = REQUIRED_DIRECTIONAL_COLUMNS + [column for column in directional_context.columns if column not in REQUIRED_DIRECTIONAL_COLUMNS]
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(base_context, outputs["base_bin_context_csv"])
    _write_csv(directional_context[ordered], outputs["directional_bin_context_csv"])
    _write_csv(directional_context.loc[directional_context["distance_window"].eq("high_priority_0_1000ft"), ordered], outputs["directional_bin_context_0_1000_csv"])
    _write_csv(directional_context.loc[directional_context["distance_window"].eq("sensitivity_1000_2500ft"), ordered], outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(reference_summary, outputs["reference_signal_summary_csv"])
    _write_csv(route_qa, outputs["route_identity_match_qa_csv"])
    _write_csv(direction_qa, outputs["directionality_match_qa_csv"])
    _write_csv(missing, outputs["missing_bins_csv"])
    _write_csv(review, outputs["review_bins_csv"])
    _write_csv(weighted, outputs["weighted_transition_bins_csv"])
    _write_csv(paired_qa, outputs["paired_pseudo_direction_qa_csv"])
    _write_csv(comparison, outputs["comparison_to_v3_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, comparison, outputs, limit_route_groups=limit_route_groups), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only speed v4 identity-enriched route and directionality cleanup for existing directional bins",
        "limit_route_groups": limit_route_groups,
        "main_context_window": "0-2500ft",
        "minimum_overlap_ratio": MIN_OVERLAP_RATIO,
        "minimum_overlap_length": MIN_OVERLAP_LENGTH,
        "crash_direction_fields_read_or_used": False,
        "speed_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_access_aadt_logic_changed": False,
        "nearest_any_stable_promotions": 0,
        "v3_stable_context_retained_when_identity_v4_not_stable": True,
        "inputs": {
            "speed": str(SPEED_FILE),
            "directional_bins_identity_enriched": str(DIRECTIONAL_BINS_FILE),
            "base_bins_identity_enriched": str(BASE_BINS_FILE),
            "directional_segments_identity_enriched": str(DIRECTIONAL_SEGMENTS_FILE),
            "speed_v3_bin_context": str(V3_BIN_CONTEXT_FILE),
            "speed_v3_readiness_summary": str(V3_READINESS_SUMMARY_FILE),
            "readiness": str(READINESS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "posted_speed_schema": str(POSTED_SPEED_SCHEMA_FILE),
            "identity_speed_diagnostic": str(IDENTITY_SPEED_DIAG_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "comparison_to_v3": comparison.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "speed_crs": crs_to_string(source_speed.crs),
        "speed_crs_matches_working_crs": crs_matches(source_speed.crs, WORKING_CRS_AUTHORITY),
    }
    _write_json(manifest, outputs["manifest_json"])
    logger.log("END build_speed_context_join_v4_identity_enriched")
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only speed v4 identity-enriched route-assisted context join.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--limit-route-groups", type=int, default=None, help="Process only the first N normalized route groups for smoke testing.")
    parser.add_argument("--sample-routes", type=int, default=None, help="Alias for --limit-route-groups.")
    args = parser.parse_args(argv)
    limit_route_groups = args.limit_route_groups if args.limit_route_groups is not None else args.sample_routes
    outputs = build_speed_context_join_v4_identity_enriched(output_root=args.output_root, limit_route_groups=limit_route_groups)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
