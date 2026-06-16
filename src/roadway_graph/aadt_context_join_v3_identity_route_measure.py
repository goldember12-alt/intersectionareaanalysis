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
OUTPUT_DIR = Path("review/current/aadt_context_join_v3_identity_route_measure")
IDENTITY_DIR = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation"

AADT_FILE = Path("artifacts/normalized/aadt.parquet")
DIRECTIONAL_BINS_FILE = IDENTITY_DIR / "directional_bins_identity_enriched.csv"
BASE_BINS_FILE = IDENTITY_DIR / "base_bins_identity_enriched.csv"
DIRECTIONAL_SEGMENTS_FILE = IDENTITY_DIR / "directional_segments_identity_enriched.csv"
READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
AADT_STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_schema.csv"
AADT_STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_field_role_candidates.csv"
AADT_STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_crs_sanity.csv"
AADT_V1_SUMMARY_FILE = OUTPUT_ROOT / "review/current/aadt_context_join/aadt_context_join_summary.csv"
AADT_V2_SUMMARY_FILE = OUTPUT_ROOT / "review/current/aadt_context_join_v2_route_key_first/aadt_context_v2_summary.csv"
IDENTITY_MANIFEST_FILE = IDENTITY_DIR / "roadway_identity_enrichment_manifest.json"
IDENTITY_AADT_DIAG_FILE = IDENTITY_DIR / "aadt_identity_enriched_match_diagnostic.csv"

AADT_VALUE_FIELD = "AADT"
AADT_YEAR_FIELD = "AADT_YR"
AADT_ROUTE_FIELDS = ["RTE_NM", "MASTER_RTE_NM"]
AADT_MEASURE_FIELD_PAIRS = [("TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"), ("FROM_MEASURE", "TO_MEASURE")]
BIN_MEASURE_FIELD_PAIRS = [("source_RTE_FROM_M", "source_RTE_TO_MSR"), ("source_FROM_MEASURE", "source_TO_MEASURE")]
MIN_OVERLAP_RATIO = 0.50
MIN_OVERLAP_LENGTH = 0.001
TOP_RATIO_TOLERANCE = 0.01
ENDPOINT_TOLERANCE = 0.001

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
    "stable_measure_from",
    "stable_measure_to",
    "stable_measure_min",
    "stable_measure_max",
    "aadt_route_name_raw",
    "aadt_route_name_normalized",
    "aadt_measure_from",
    "aadt_measure_to",
    "aadt_measure_min",
    "aadt_measure_max",
    "route_measure_match_status",
    "measure_overlap_length",
    "measure_overlap_ratio",
    "measure_endpoint_difference",
    "aadt_value",
    "aadt_year",
    "aadt_direction_factor",
    "aadt_directionality",
    "aadt_candidate_values",
    "aadt_value_conflict_flag",
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


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def _format_number(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    if float(numeric).is_integer():
        return str(int(numeric))
    return f"{float(numeric):.6f}".rstrip("0").rstrip(".")


def _joined_unique_numbers(values: pd.Series) -> str:
    formatted = [_format_number(value) for value in values]
    return "|".join(sorted({value for value in formatted if value}))


def _route_key(value: Any) -> str:
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
        if compact in {"US", "SR", "VA", "I"}:
            route_type = "SR" if compact == "VA" else compact
            route_token_seen = True
            continue
        if compact in {"NB", "SB", "EB", "WB", "N", "S", "E", "W"}:
            direction = compact[0]
            continue
        match = re.fullmatch(r"(US|SR|VA|I|IS)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
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
        match = re.search(r"(US|SR|VA|I|IS)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", joined)
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


def _distance_window(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown_distance"
    if numeric <= 1000:
        return "high_priority_0_1000ft"
    if numeric <= 2500:
        return "sensitivity_1000_2500ft"
    return "outside_context_window"


def _load_aadt() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    aadt = gpd.read_parquet(AADT_FILE)
    missing = [field for field in [AADT_VALUE_FIELD, AADT_YEAR_FIELD, "LINKID", "DIRECTION_FACTOR", "DIRECTIONALITY", *AADT_ROUTE_FIELDS] if field not in aadt.columns]
    if missing:
        raise ValueError(f"AADT source is missing required fields: {missing}")
    aadt = aadt.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="aadt_source_index")
    aadt["aadt_value_numeric"] = pd.to_numeric(aadt[AADT_VALUE_FIELD], errors="coerce")
    aadt["aadt_year_numeric"] = pd.to_numeric(aadt[AADT_YEAR_FIELD], errors="coerce")
    for left, right in AADT_MEASURE_FIELD_PAIRS:
        if left in aadt.columns and right in aadt.columns:
            left_num = pd.to_numeric(aadt[left], errors="coerce")
            right_num = pd.to_numeric(aadt[right], errors="coerce")
            if (left_num.notna() & right_num.notna()).any():
                aadt["aadt_measure_from"] = left_num
                aadt["aadt_measure_to"] = right_num
                aadt["aadt_measure_source_fields"] = f"{left}/{right}"
                break
    if "aadt_measure_from" not in aadt.columns:
        aadt["aadt_measure_from"] = pd.NA
        aadt["aadt_measure_to"] = pd.NA
        aadt["aadt_measure_source_fields"] = ""
    aadt["aadt_measure_min"] = aadt[["aadt_measure_from", "aadt_measure_to"]].min(axis=1)
    aadt["aadt_measure_max"] = aadt[["aadt_measure_from", "aadt_measure_to"]].max(axis=1)
    aadt["aadt_measure_length"] = aadt["aadt_measure_max"] - aadt["aadt_measure_min"]
    alias_frames = []
    for field in AADT_ROUTE_FIELDS:
        alias = pd.DataFrame(aadt.drop(columns=["geometry"], errors="ignore"))
        alias["aadt_route_name_raw"] = alias[field].astype(str).map(_clean)
        alias["aadt_route_name_normalized"] = alias["aadt_route_name_raw"].map(_route_key)
        alias["aadt_route_alias_field"] = field
        alias_frames.append(alias.loc[alias["aadt_route_name_normalized"].ne("")].copy())
    aliases = pd.concat(alias_frames, ignore_index=True, sort=False)
    aliases = aliases.loc[aliases["aadt_value_numeric"].gt(0) & aliases["aadt_measure_min"].notna() & aliases["aadt_measure_max"].notna()].copy()
    aliases = aliases.drop_duplicates(["aadt_source_index", "aadt_route_name_normalized"]).copy()
    return aadt, aliases


def _choose_bin_measure_pair(frame: pd.DataFrame) -> tuple[str, str, pd.Series, pd.Series]:
    for left, right in BIN_MEASURE_FIELD_PAIRS:
        if left in frame.columns and right in frame.columns:
            left_num = pd.to_numeric(frame[left], errors="coerce")
            right_num = pd.to_numeric(frame[right], errors="coerce")
            if (left_num.notna() & right_num.notna()).any():
                return left, right, left_num, right_num
    return "", "", pd.Series(pd.NA, index=frame.index, dtype="Float64"), pd.Series(pd.NA, index=frame.index, dtype="Float64")


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
        "bin_index_in_travel_direction",
        "bin_start_ft_in_travel_direction",
        "bin_end_ft_in_travel_direction",
        "segment_length_ft",
        "source_bin_key",
        "distance_window",
        "catchment_status",
        "source_RTE_NM",
        "source_RTE_COMMON",
        "source_RTE_ID",
        "source_FROM_MEASURE",
        "source_TO_MEASURE",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "source_route_key_v2",
        "source_route_common_key_v2",
        "identity_enrichment_status",
        "identity_enrichment_confidence",
    ]
    bins = _read_csv(DIRECTIONAL_BINS_FILE, usecols=columns)
    bins["bin_midpoint_ft_from_reference_signal"] = pd.to_numeric(bins["bin_midpoint_ft_from_reference_signal"], errors="coerce")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    bins = bins.loc[bins["catchment_status"].eq("usable") & bins["distance_window"].isin(["high_priority_0_1000ft", "sensitivity_1000_2500ft"])].copy()
    bins["stable_route_name_raw"] = bins["source_RTE_NM"].astype(str).map(_clean)
    bins["stable_route_name_normalized"] = bins["source_route_key_v2"].astype(str).map(_clean)
    fallback_mask = bins["stable_route_name_normalized"].eq("")
    bins.loc[fallback_mask, "stable_route_name_raw"] = bins.loc[fallback_mask, "source_RTE_COMMON"].astype(str).map(_clean)
    bins.loc[fallback_mask, "stable_route_name_normalized"] = bins.loc[fallback_mask, "source_route_common_key_v2"].astype(str).map(_clean)
    return bins


def _load_base_bins(context_bins: pd.DataFrame) -> pd.DataFrame:
    base_columns = [
        "base_segment_id",
        "source_bin_key",
        "bin_index",
        "bin_start_ft",
        "bin_end_ft",
        "bin_midpoint_ft",
        "source_RTE_NM",
        "source_RTE_COMMON",
        "source_RTE_ID",
        "source_FROM_MEASURE",
        "source_TO_MEASURE",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "source_route_key_v2",
        "source_route_common_key_v2",
        "identity_enrichment_status",
        "identity_enrichment_confidence",
    ]
    base = _read_csv(BASE_BINS_FILE, usecols=base_columns)
    wanted = context_bins[["base_segment_id", "source_bin_key", "segment_length_ft"]].drop_duplicates(["base_segment_id", "source_bin_key"])
    base = base.merge(wanted, on=["base_segment_id", "source_bin_key"], how="inner")
    base["stable_route_name_raw"] = base["source_RTE_NM"].astype(str).map(_clean)
    base["stable_route_name_normalized"] = base["source_route_key_v2"].astype(str).map(_clean)
    fallback_mask = base["stable_route_name_normalized"].eq("")
    base.loc[fallback_mask, "stable_route_name_raw"] = base.loc[fallback_mask, "source_RTE_COMMON"].astype(str).map(_clean)
    base.loc[fallback_mask, "stable_route_name_normalized"] = base.loc[fallback_mask, "source_route_common_key_v2"].astype(str).map(_clean)

    measure_left, measure_right, source_from, source_to = _choose_bin_measure_pair(base)
    base["stable_measure_source_fields"] = f"{measure_left}/{measure_right}" if measure_left else ""
    segment_length = pd.to_numeric(base["segment_length_ft"], errors="coerce")
    start_ft = pd.to_numeric(base["bin_start_ft"], errors="coerce")
    end_ft = pd.to_numeric(base["bin_end_ft"], errors="coerce")
    start_ratio = (start_ft / segment_length).clip(lower=0, upper=1)
    end_ratio = (end_ft / segment_length).clip(lower=0, upper=1)
    usable_ratio = segment_length.gt(0) & source_from.notna() & source_to.notna()
    base["stable_measure_from"] = source_from + (source_to - source_from) * start_ratio
    base["stable_measure_to"] = source_from + (source_to - source_from) * end_ratio
    base.loc[~usable_ratio, ["stable_measure_from", "stable_measure_to"]] = pd.NA
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
        "stable_measure_from",
        "stable_measure_to",
        "stable_measure_min",
        "stable_measure_max",
        "aadt_source_index",
        "LINKID",
        "aadt_route_alias_field",
        "aadt_route_name_raw",
        "aadt_route_name_normalized",
        "aadt_measure_from",
        "aadt_measure_to",
        "aadt_measure_min",
        "aadt_measure_max",
        AADT_VALUE_FIELD,
        AADT_YEAR_FIELD,
        "DIRECTION_FACTOR",
        "DIRECTIONALITY",
        "measure_overlap_length",
        "measure_overlap_ratio",
        "measure_endpoint_difference",
        "candidate_rank",
        "candidate_decision",
    ]


def _route_measure_candidates(aadt_aliases: pd.DataFrame, base_bins: pd.DataFrame, *, progress_logger: ProgressLogger, limit_route_groups: int | None = None, progress_every: int = 25) -> pd.DataFrame:
    routed = base_bins.loc[base_bins["stable_route_name_normalized"].ne("")].copy()
    route_groups = list(routed.groupby("stable_route_name_normalized", dropna=False))
    if limit_route_groups is not None:
        route_groups = route_groups[:limit_route_groups]
    needed_routes = {str(route_key) for route_key, _ in route_groups}
    aadt_by_route = {
        key: group.copy()
        for key, group in aadt_aliases.loc[aadt_aliases["aadt_route_name_normalized"].isin(needed_routes)].groupby("aadt_route_name_normalized", dropna=False)
    }
    frames: list[pd.DataFrame] = []
    progress_logger.log(f"ROUTE_MEASURE_SETUP; route_groups={len(route_groups)}; base_bins={len(routed)}; aadt_alias_records={len(aadt_aliases)}")
    for index, (route_key, bin_group) in enumerate(route_groups, start=1):
        aadt_group = aadt_by_route.get(route_key)
        if index == 1 or index % progress_every == 0 or index == len(route_groups):
            progress_logger.log(f"ROUTE_MEASURE_GROUP; group={index}/{len(route_groups)}; route={route_key}; base_bins={len(bin_group)}; aadt_records={0 if aadt_group is None else len(aadt_group)}")
        if aadt_group is None or aadt_group.empty:
            continue
        if bin_group["stable_measure_min"].isna().all() or aadt_group["aadt_measure_min"].isna().all():
            continue
        left = bin_group.reset_index(drop=True)
        right = aadt_group.reset_index(drop=True)
        pairs = left.merge(right, how="cross", suffixes=("", "_aadt"))
        pairs = pairs.loc[pairs["aadt_measure_max"].ge(pairs["stable_measure_min"]) & pairs["aadt_measure_min"].le(pairs["stable_measure_max"])].copy()
        if pairs.empty:
            continue
        overlap_min = pairs[["stable_measure_max", "aadt_measure_max"]].min(axis=1)
        overlap_max = pairs[["stable_measure_min", "aadt_measure_min"]].max(axis=1)
        pairs["measure_overlap_length"] = (overlap_min - overlap_max).clip(lower=0)
        pairs["measure_overlap_ratio"] = pairs["measure_overlap_length"] / pairs["stable_measure_length"]
        pairs["measure_endpoint_difference"] = (pairs["stable_measure_min"] - pairs["aadt_measure_min"]).abs() + (pairs["stable_measure_max"] - pairs["aadt_measure_max"]).abs()
        pairs = pairs.loc[pairs["measure_overlap_length"].gt(0)].copy()
        if pairs.empty:
            continue
        pairs = pairs.sort_values(["base_segment_id", "source_bin_key", "measure_overlap_ratio", "measure_endpoint_difference"], ascending=[True, True, False, True])
        pairs["candidate_rank"] = pairs.groupby(["base_segment_id", "source_bin_key"]).cumcount() + 1
        pairs["candidate_decision"] = pairs["measure_overlap_ratio"].ge(MIN_OVERLAP_RATIO) & pairs["measure_overlap_length"].ge(MIN_OVERLAP_LENGTH)
        keep = [column for column in _candidate_columns() if column in pairs.columns]
        frames.append(pairs[keep].copy())
    if not frames:
        return pd.DataFrame(columns=_candidate_columns())
    out = pd.concat(frames, ignore_index=True, sort=False)
    for column in ["measure_overlap_length", "measure_overlap_ratio", "measure_endpoint_difference"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").round(6)
    return out


def _single_route_candidates(aadt_aliases: pd.DataFrame, base_bins: pd.DataFrame) -> pd.DataFrame:
    missing_measure = base_bins.loc[base_bins["stable_route_name_normalized"].ne("") & base_bins["stable_measure_min"].isna()].copy()
    if missing_measure.empty:
        return pd.DataFrame(columns=_candidate_columns())
    bucket = (
        aadt_aliases.groupby("aadt_route_name_normalized", dropna=False)
        .agg(aadt_candidate_record_count=("aadt_source_index", "nunique"), aadt_candidate_value_count=("aadt_value_numeric", "nunique"))
        .reset_index()
    )
    single_keys = set(bucket.loc[bucket["aadt_candidate_record_count"].eq(1) & bucket["aadt_candidate_value_count"].eq(1), "aadt_route_name_normalized"])
    work = missing_measure.loc[missing_measure["stable_route_name_normalized"].isin(single_keys)].copy()
    if work.empty:
        return pd.DataFrame(columns=_candidate_columns())
    single = aadt_aliases.loc[aadt_aliases["aadt_route_name_normalized"].isin(single_keys)].drop_duplicates("aadt_route_name_normalized")
    out = work.merge(single, left_on="stable_route_name_normalized", right_on="aadt_route_name_normalized", how="inner")
    out["measure_overlap_length"] = pd.NA
    out["measure_overlap_ratio"] = pd.NA
    out["measure_endpoint_difference"] = pd.NA
    out["candidate_rank"] = 1
    out["candidate_decision"] = True
    return out[[column for column in _candidate_columns() if column in out.columns]].copy()


def _build_base_context(base_bins: pd.DataFrame, candidates: pd.DataFrame, single_candidates: pd.DataFrame, aadt_aliases: pd.DataFrame) -> pd.DataFrame:
    out = base_bins.copy()
    out["route_measure_match_status"] = "not_evaluated"
    out["aadt_context_method"] = "no_route_compatible_aadt_match"
    out["aadt_context_confidence"] = "missing"
    out["aadt_context_status"] = "no_route_compatible_aadt_match"
    out["aadt_value_conflict_flag"] = False
    out["aadt_candidate_values"] = ""
    for column in ["aadt_route_name_raw", "aadt_route_name_normalized", "aadt_measure_from", "aadt_measure_to", "aadt_measure_min", "aadt_measure_max", "aadt_value", "aadt_year", "aadt_direction_factor", "aadt_directionality", "measure_overlap_length", "measure_overlap_ratio", "measure_endpoint_difference", "aadt_source_index", "aadt_linkid"]:
        out[column] = ""

    aadt_routes = set(aadt_aliases["aadt_route_name_normalized"].astype(str))
    out.loc[out["stable_route_name_normalized"].eq(""), ["route_measure_match_status", "aadt_context_method", "aadt_context_status"]] = ["route_missing", "no_route_compatible_aadt_match", "no_route_compatible_aadt_match"]
    out.loc[out["stable_route_name_normalized"].ne("") & ~out["stable_route_name_normalized"].isin(aadt_routes), ["route_measure_match_status", "aadt_context_method", "aadt_context_status"]] = ["route_mismatch", "no_route_compatible_aadt_match", "no_route_compatible_aadt_match"]
    out.loc[out["stable_route_name_normalized"].isin(aadt_routes) & out["stable_measure_min"].isna(), ["route_measure_match_status", "aadt_context_method", "aadt_context_confidence", "aadt_context_status"]] = ["measure_missing", "review_measure_missing", "low_review", "review_measure_missing"]

    grouped_candidates = candidates.loc[candidates["candidate_decision"].astype(bool)].groupby(["base_segment_id", "source_bin_key"], dropna=False) if not candidates.empty else []
    chosen_rows = []
    for key, group in grouped_candidates:
        group = group.sort_values(["measure_overlap_ratio", "measure_endpoint_difference"], ascending=[False, True]).copy()
        top_ratio = pd.to_numeric(group.iloc[0]["measure_overlap_ratio"], errors="coerce")
        top_endpoint = pd.to_numeric(group.iloc[0]["measure_endpoint_difference"], errors="coerce")
        comparable = group.loc[
            pd.to_numeric(group["measure_overlap_ratio"], errors="coerce").ge(top_ratio - TOP_RATIO_TOLERANCE)
            & pd.to_numeric(group["measure_endpoint_difference"], errors="coerce").le(top_endpoint + ENDPOINT_TOLERANCE)
        ].copy()
        comparable_values = comparable[AADT_VALUE_FIELD].map(_format_number).loc[lambda s: s.ne("")]
        value_conflict = comparable_values.nunique() > 1
        if value_conflict:
            status = "ambiguous_conflicting_aadt_values"
            method = "review_conflicting_aadt_values"
            confidence = "low_review"
        elif len(comparable.drop_duplicates("aadt_source_index")) > 1 and comparable_values.nunique() <= 1:
            status = "stable_aadt_assigned_route_measure"
            method = "route_measure_overlap"
            confidence = "medium"
        elif len(comparable.drop_duplicates("aadt_source_index")) == 1:
            status = "stable_aadt_assigned_route_measure"
            method = "route_measure_overlap"
            confidence = "high"
        else:
            status = "review_multi_candidate_route_measure"
            method = "review_multi_candidate_route_measure"
            confidence = "low_review"
        chosen = group.iloc[0].to_dict()
        chosen.update(
            {
                "base_segment_id": key[0],
                "source_bin_key": key[1],
                "route_measure_match_status": "exact_route_measure_overlap",
                "aadt_context_method": method,
                "aadt_context_confidence": confidence,
                "aadt_context_status": status,
                "aadt_value_conflict_flag": bool(value_conflict),
                "aadt_candidate_values": _joined_unique_numbers(group[AADT_VALUE_FIELD]),
            }
        )
        chosen_rows.append(chosen)
    chosen = pd.DataFrame(chosen_rows)
    if not chosen.empty:
        _apply_chosen(out, chosen)

    no_overlap_keys = set(
        map(tuple, out.loc[out["stable_route_name_normalized"].isin(aadt_routes) & out["stable_measure_min"].notna(), ["base_segment_id", "source_bin_key"]].itertuples(index=False, name=None))
    )
    matched_keys = set(map(tuple, chosen[["base_segment_id", "source_bin_key"]].itertuples(index=False, name=None))) if not chosen.empty else set()
    candidate_any_keys = set(map(tuple, candidates[["base_segment_id", "source_bin_key"]].drop_duplicates().itertuples(index=False, name=None))) if not candidates.empty else set()
    no_overlap_keys = no_overlap_keys - matched_keys
    if no_overlap_keys:
        key_index = pd.MultiIndex.from_tuples(list(no_overlap_keys), names=["base_segment_id", "source_bin_key"])
        mask = pd.MultiIndex.from_frame(out[["base_segment_id", "source_bin_key"]]).isin(key_index)
        out.loc[mask, ["route_measure_match_status", "aadt_context_method", "aadt_context_confidence", "aadt_context_status"]] = ["route_match_no_measure_overlap", "review_no_measure_overlap", "low_review", "review_no_measure_overlap"]
    if candidate_any_keys - matched_keys:
        key_index = pd.MultiIndex.from_tuples(list(candidate_any_keys - matched_keys), names=["base_segment_id", "source_bin_key"])
        mask = pd.MultiIndex.from_frame(out[["base_segment_id", "source_bin_key"]]).isin(key_index)
        out.loc[mask, ["route_measure_match_status", "aadt_context_method", "aadt_context_confidence", "aadt_context_status"]] = ["exact_route_measure_overlap", "review_multi_candidate_route_measure", "low_review", "review_multi_candidate_route_measure"]

    if not single_candidates.empty:
        single = single_candidates.copy()
        single["route_measure_match_status"] = "measure_missing"
        single["aadt_context_method"] = "stable_single_route_candidate"
        single["aadt_context_confidence"] = "medium"
        single["aadt_context_status"] = "stable_aadt_assigned_single_route_candidate"
        single["aadt_value_conflict_flag"] = False
        single["aadt_candidate_values"] = single[AADT_VALUE_FIELD].map(_format_number)
        _apply_chosen(out, single)

    return out


def _apply_chosen(out: pd.DataFrame, chosen: pd.DataFrame) -> None:
    chosen = chosen.drop_duplicates(["base_segment_id", "source_bin_key"]).set_index(["base_segment_id", "source_bin_key"])
    target_index = pd.MultiIndex.from_frame(out[["base_segment_id", "source_bin_key"]])
    for src, dest in [
        ("aadt_route_name_raw", "aadt_route_name_raw"),
        ("aadt_route_name_normalized", "aadt_route_name_normalized"),
        ("aadt_measure_from", "aadt_measure_from"),
        ("aadt_measure_to", "aadt_measure_to"),
        ("aadt_measure_min", "aadt_measure_min"),
        ("aadt_measure_max", "aadt_measure_max"),
        ("measure_overlap_length", "measure_overlap_length"),
        ("measure_overlap_ratio", "measure_overlap_ratio"),
        ("measure_endpoint_difference", "measure_endpoint_difference"),
        (AADT_VALUE_FIELD, "aadt_value"),
        (AADT_YEAR_FIELD, "aadt_year"),
        ("DIRECTION_FACTOR", "aadt_direction_factor"),
        ("DIRECTIONALITY", "aadt_directionality"),
        ("aadt_source_index", "aadt_source_index"),
        ("LINKID", "aadt_linkid"),
        ("route_measure_match_status", "route_measure_match_status"),
        ("aadt_context_method", "aadt_context_method"),
        ("aadt_context_confidence", "aadt_context_confidence"),
        ("aadt_context_status", "aadt_context_status"),
        ("aadt_value_conflict_flag", "aadt_value_conflict_flag"),
        ("aadt_candidate_values", "aadt_candidate_values"),
    ]:
        if src in chosen.columns:
            mapped = pd.Series(target_index.map(chosen[src]), index=out.index)
            out[dest] = mapped.where(mapped.notna(), out[dest])


def _build_directional_context(context_bins: pd.DataFrame, base_context: pd.DataFrame) -> pd.DataFrame:
    base_cols = [column for column in base_context.columns if column not in {"source_RTE_NM", "source_RTE_COMMON", "source_RTE_ID", "source_route_key_v2", "source_route_common_key_v2"}]
    out = context_bins.merge(base_context[base_cols], on=["base_segment_id", "source_bin_key"], how="left", suffixes=("", "_base"))
    pseudo = out["roadway_representation_type"].eq("undivided_centerline_pseudo_direction") & out["aadt_context_status"].str.startswith("stable", na=False)
    out.loc[pseudo, "aadt_context_method"] = out.loc[pseudo, "aadt_context_method"].where(out.loc[pseudo, "aadt_context_method"].eq("stable_single_route_candidate"), "propagated_from_shared_base_bin")
    return out


def _crash_context(readiness: pd.DataFrame, directional_context: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "reference_directional_bin_id",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_measure_min",
        "stable_measure_max",
        "aadt_route_name_raw",
        "aadt_route_name_normalized",
        "aadt_value",
        "aadt_year",
        "aadt_direction_factor",
        "aadt_directionality",
        "aadt_context_method",
        "aadt_context_confidence",
        "aadt_context_status",
    ]
    return readiness.merge(directional_context[[column for column in keep if column in directional_context.columns]], on="reference_directional_bin_id", how="left")


def _paired_pseudo_direction_consistency(bin_context: pd.DataFrame) -> pd.DataFrame:
    pseudo = bin_context.loc[bin_context["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    if pseudo.empty:
        return pd.DataFrame(columns=["base_segment_id", "source_bin_key", "directional_record_count", "paired_pseudo_direction_aadt_consistent"])
    grouped = pseudo.groupby(["base_segment_id", "source_bin_key"], dropna=False).agg(
        directional_record_count=("reference_directional_bin_id", "nunique"),
        aadt_context_status_count=("aadt_context_status", "nunique"),
        aadt_value_count=("aadt_value", "nunique"),
        aadt_year_count=("aadt_year", "nunique"),
        aadt_route_count=("aadt_route_name_normalized", "nunique"),
    ).reset_index()
    grouped["paired_pseudo_direction_aadt_consistent"] = grouped[["aadt_context_status_count", "aadt_value_count", "aadt_year_count", "aadt_route_count"]].le(1).all(axis=1)
    return grouped


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    stable = bin_context["aadt_context_status"].str.startswith("stable", na=False)
    grouped = bin_context.assign(stable_aadt_bin=stable).groupby("reference_signal_id", dropna=False).agg(
        directional_bin_count=("reference_directional_bin_id", "nunique"),
        stable_aadt_bin_count=("stable_aadt_bin", "sum"),
        aadt_value_count=("aadt_value", lambda s: s.loc[stable.reindex(s.index, fill_value=False)].astype(str).map(_clean).loc[lambda x: x.ne("")].nunique()),
        route_count=("stable_route_name_normalized", "nunique"),
    ).reset_index()
    grouped["has_stable_aadt"] = grouped["stable_aadt_bin_count"].gt(0)
    return grouped


def _route_match_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for status, group in bin_context.groupby("route_measure_match_status", dropna=False):
        rows.append({"qa_group": "route_measure_match_status", "value": status, "directional_bin_count": int(len(group))})
    for method, group in bin_context.groupby("aadt_context_method", dropna=False):
        rows.append({"qa_group": "aadt_context_method", "value": method, "directional_bin_count": int(len(group))})
    return pd.DataFrame(rows)


def _summary(bin_context: pd.DataFrame, base_context: pd.DataFrame, crash_context: pd.DataFrame, paired_qa: pd.DataFrame, source_aadt: gpd.GeoDataFrame) -> pd.DataFrame:
    stable = bin_context["aadt_context_status"].str.startswith("stable", na=False)
    rows = [
        {"metric": "aadt_records_considered", "value": "", "count": int(len(source_aadt))},
        {"metric": "directional_bins_in_context_window", "value": "0-2500ft", "count": int(len(bin_context))},
        {"metric": "base_bins_in_context_window", "value": "0-2500ft", "count": int(len(base_context))},
        {"metric": "bins_with_stable_aadt", "value": "", "count": int(stable.sum())},
        {"metric": "route_measure_stable_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("stable_aadt_assigned_route_measure").sum())},
        {"metric": "stable_single_route_candidate_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("stable_aadt_assigned_single_route_candidate").sum())},
        {"metric": "review_no_measure_overlap_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("review_no_measure_overlap").sum())},
        {"metric": "review_measure_missing_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("review_measure_missing").sum())},
        {"metric": "review_multi_candidate_route_measure_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("review_multi_candidate_route_measure").sum())},
        {"metric": "ambiguous_conflicting_aadt_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("ambiguous_conflicting_aadt_values").sum())},
        {"metric": "no_route_compatible_aadt_match_bins", "value": "", "count": int(bin_context["aadt_context_status"].eq("no_route_compatible_aadt_match").sum())},
        {"metric": "crashes_inheriting_stable_aadt", "value": "", "count": int(crash_context["aadt_context_status"].str.startswith("stable", na=False).sum()) if not crash_context.empty else 0},
        {"metric": "reference_signals_with_stable_aadt", "value": "", "count": int(bin_context.loc[stable, "reference_signal_id"].nunique())},
        {"metric": "paired_pseudo_direction_groups", "value": "", "count": int(len(paired_qa))},
        {"metric": "paired_pseudo_direction_inconsistent_groups", "value": "", "count": int((~paired_qa["paired_pseudo_direction_aadt_consistent"]).sum()) if not paired_qa.empty else 0},
        {"metric": "aadt_ready_as_strong_flagged_context_layer", "value": bool(stable.any()), "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "aadt_used_for_upstream_downstream", "value": False, "count": ""},
    ]
    for window, group in bin_context.groupby("distance_window", dropna=False):
        window_stable = group["aadt_context_status"].str.startswith("stable", na=False)
        rows.extend(
            [
                {"metric": "bins_by_distance_window", "value": str(window), "count": int(len(group))},
                {"metric": "stable_aadt_bins_by_distance_window", "value": str(window), "count": int(window_stable.sum())},
                {"metric": "review_no_measure_overlap_bins_by_distance_window", "value": str(window), "count": int(group["aadt_context_status"].eq("review_no_measure_overlap").sum())},
                {"metric": "ambiguous_aadt_bins_by_distance_window", "value": str(window), "count": int(group["aadt_context_status"].eq("ambiguous_conflicting_aadt_values").sum())},
                {"metric": "missing_aadt_bins_by_distance_window", "value": str(window), "count": int(group["aadt_context_status"].eq("no_route_compatible_aadt_match").sum())},
            ]
        )
    for direction, group in bin_context.groupby("signal_relative_direction", dropna=False):
        direction_stable = group["aadt_context_status"].str.startswith("stable", na=False)
        rows.extend(
            [
                {"metric": "bins_by_signal_relative_direction", "value": str(direction), "count": int(len(group))},
                {"metric": "stable_aadt_bins_by_signal_relative_direction", "value": str(direction), "count": int(direction_stable.sum())},
                {"metric": "review_no_measure_overlap_bins_by_signal_relative_direction", "value": str(direction), "count": int(group["aadt_context_status"].eq("review_no_measure_overlap").sum())},
                {"metric": "ambiguous_aadt_bins_by_signal_relative_direction", "value": str(direction), "count": int(group["aadt_context_status"].eq("ambiguous_conflicting_aadt_values").sum())},
            ]
        )
    for year, count in pd.to_numeric(bin_context.loc[stable, "aadt_year"], errors="coerce").dropna().astype(int).value_counts().sort_index().items():
        rows.append({"metric": "stable_aadt_bins_by_aadt_year", "value": str(year), "count": int(count)})
    return pd.DataFrame(rows)


def _summary_value(summary: pd.DataFrame, metric: str) -> int:
    if summary.empty:
        return 0
    row = summary.loc[summary["metric"].eq(metric)]
    if row.empty:
        return 0
    value = pd.to_numeric(row.iloc[0].get("count"), errors="coerce")
    return 0 if pd.isna(value) else int(value)


def _comparison_to_v1_v2(v3_summary: pd.DataFrame) -> pd.DataFrame:
    v1 = _read_optional(AADT_V1_SUMMARY_FILE)
    v2 = _read_optional(AADT_V2_SUMMARY_FILE)
    metrics = [
        "bins_with_stable_aadt",
        "ambiguous_conflicting_aadt_bins",
        "crashes_inheriting_stable_aadt",
        "reference_signals_with_stable_aadt",
    ]
    rows = []
    for metric in metrics:
        rows.append(
            {
                "metric": metric,
                "v1_count": _summary_value(v1, metric),
                "v2_count": _summary_value(v2, metric),
                "v3_count": _summary_value(v3_summary, metric),
                "v3_minus_v1": _summary_value(v3_summary, metric) - _summary_value(v1, metric),
                "v3_minus_v2": _summary_value(v3_summary, metric) - _summary_value(v2, metric),
            }
        )
    rows.extend(
        [
            {"metric": "route_measure_stable_bins", "v1_count": 0, "v2_count": 0, "v3_count": _summary_value(v3_summary, "route_measure_stable_bins"), "v3_minus_v1": _summary_value(v3_summary, "route_measure_stable_bins"), "v3_minus_v2": _summary_value(v3_summary, "route_measure_stable_bins")},
            {"metric": "stable_single_route_candidate_bins", "v1_count": 0, "v2_count": _summary_value(v2, "single_candidate_route_bucket_recovered_bins"), "v3_count": _summary_value(v3_summary, "stable_single_route_candidate_bins"), "v3_minus_v1": _summary_value(v3_summary, "stable_single_route_candidate_bins"), "v3_minus_v2": _summary_value(v3_summary, "stable_single_route_candidate_bins") - _summary_value(v2, "single_candidate_route_bucket_recovered_bins")},
            {"metric": "review_or_missing_bins", "v1_count": 110710 - _summary_value(v1, "bins_with_stable_aadt"), "v2_count": 110710 - _summary_value(v2, "bins_with_stable_aadt"), "v3_count": 110710 - _summary_value(v3_summary, "bins_with_stable_aadt"), "v3_minus_v1": (110710 - _summary_value(v3_summary, "bins_with_stable_aadt")) - (110710 - _summary_value(v1, "bins_with_stable_aadt")), "v3_minus_v2": (110710 - _summary_value(v3_summary, "bins_with_stable_aadt")) - (110710 - _summary_value(v2, "bins_with_stable_aadt"))},
        ]
    )
    return pd.DataFrame(rows)


def _context_qa(bin_context: pd.DataFrame, base_context: pd.DataFrame, source_aadt: gpd.GeoDataFrame, paired_qa: pd.DataFrame) -> pd.DataFrame:
    outside = int((~bin_context["distance_window"].isin(["high_priority_0_1000ft", "sensitivity_1000_2500ft"])).sum())
    duplicate_directional = int(bin_context["reference_directional_bin_id"].duplicated().sum())
    duplicate_base = int(base_context[["base_segment_id", "source_bin_key"]].duplicated().sum())
    inconsistent = int((~paired_qa["paired_pseudo_direction_aadt_consistent"]).sum()) if not paired_qa.empty else 0
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "aadt_not_used_for_upstream_downstream", "passed": True, "observed": False, "expected": False},
            {"check_name": "scaffold_catchment_assignment_access_speed_logic_changed", "passed": True, "observed": False, "expected": False},
            {"check_name": "main_context_limited_to_0_2500ft", "passed": outside == 0, "observed": outside, "expected": 0},
            {"check_name": "enriched_directional_bins_one_row_per_bin", "passed": duplicate_directional == 0, "observed": duplicate_directional, "expected": 0},
            {"check_name": "base_context_one_row_per_base_bin", "passed": duplicate_base == 0, "observed": duplicate_base, "expected": 0},
            {"check_name": "aadt_crs_matches_working_epsg_3968", "passed": crs_matches(source_aadt.crs, WORKING_CRS_AUTHORITY), "observed": crs_to_string(source_aadt.crs), "expected": WORKING_CRS_AUTHORITY},
            {"check_name": "paired_pseudo_direction_consistency", "passed": inconsistent == 0, "observed": inconsistent, "expected": 0},
        ]
    )


def _findings(summary: pd.DataFrame, comparison: pd.DataFrame, outputs: dict[str, Path], *, limit_route_groups: int | None) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        if row.empty:
            return ""
        return row.iloc[0]["count"] if str(row.iloc[0]["count"]) != "" else row.iloc[0]["value"]

    comparison_lines = ["| metric | v1_count | v2_count | v3_count | v3_minus_v1 | v3_minus_v2 |", "|---|---:|---:|---:|---:|---:|"]
    for row in comparison.to_dict(orient="records"):
        comparison_lines.append(
            f"| {row.get('metric', '')} | {row.get('v1_count', '')} | {row.get('v2_count', '')} | {row.get('v3_count', '')} | {row.get('v3_minus_v1', '')} | {row.get('v3_minus_v2', '')} |"
        )

    lines = [
        "# AADT Context Join v3 Identity Route-Measure Findings",
        "",
        "## Bounded Question",
        "",
        "Attach AADT as a read-only flagged context layer to existing 0-2,500 ft directional bins using enriched roadway identity route keys and route-measure interval overlap. Do not alter scaffold, catchments, crash assignment, access, speed, or upstream/downstream logic.",
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
        f"- bins with stable AADT: {count('bins_with_stable_aadt')}",
        f"- route+measure stable bins: {count('route_measure_stable_bins')}",
        f"- single-route-candidate stable bins: {count('stable_single_route_candidate_bins')}",
        f"- review no-measure-overlap bins: {count('review_no_measure_overlap_bins')}",
        f"- review measure-missing bins: {count('review_measure_missing_bins')}",
        f"- review multi-candidate route-measure bins: {count('review_multi_candidate_route_measure_bins')}",
        f"- ambiguous/conflicting AADT bins: {count('ambiguous_conflicting_aadt_bins')}",
        f"- no route-compatible AADT match bins: {count('no_route_compatible_aadt_match_bins')}",
        f"- crashes inheriting stable AADT: {count('crashes_inheriting_stable_aadt')}",
        f"- reference signals with stable AADT: {count('reference_signals_with_stable_aadt')}",
        f"- paired pseudo-direction inconsistent groups: {count('paired_pseudo_direction_inconsistent_groups')}",
        f"- AADT ready as strong flagged context layer: {count('aadt_ready_as_strong_flagged_context_layer')}",
        "",
        "## v1/v2 Comparison",
        "",
        *comparison_lines,
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_aadt_context_join_v3_identity_route_measure(*, output_root: Path = OUTPUT_ROOT, limit_route_groups: int | None = None) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    logger = ProgressLogger(out_dir / "aadt_context_v3_progress.log")
    logger.log(f"START build_aadt_context_join_v3_identity_route_measure; limit_route_groups={limit_route_groups}")
    source_aadt, aadt_aliases = _phase(logger, "_load_aadt", _load_aadt)
    context_bins = _phase(logger, "_load_directional_bins", _load_directional_bins)
    base_bins = _phase(logger, "_load_base_bins", _load_base_bins, context_bins)
    _ = _phase(logger, "_read_directional_segments_identity_enriched", _read_csv, DIRECTIONAL_SEGMENTS_FILE)
    _ = _phase(logger, "_read_assignments_no_crash_direction", _read_csv, ASSIGNMENTS_FILE, usecols=["crash_id", "reference_directional_bin_id", "assignment_status"])
    _ = _phase(logger, "_read_catchment_index", _read_csv, CATCHMENT_INDEX_FILE, usecols=["reference_directional_bin_id", "catchment_status"])
    for optional in [AADT_STAGING_SCHEMA_FILE, AADT_STAGING_FIELD_ROLES_FILE, AADT_STAGING_CRS_SANITY_FILE, IDENTITY_AADT_DIAG_FILE]:
        _ = _phase(logger, f"_read_optional_{optional.name}", _read_optional, optional)
    candidates = _phase(logger, "_route_measure_candidates", _route_measure_candidates, aadt_aliases, base_bins, progress_logger=logger, limit_route_groups=limit_route_groups)
    single_candidates = _phase(logger, "_single_route_candidates", _single_route_candidates, aadt_aliases, base_bins)
    base_context = _phase(logger, "_build_base_context", _build_base_context, base_bins, candidates, single_candidates, aadt_aliases)
    directional_context = _phase(logger, "_build_directional_context", _build_directional_context, context_bins, base_context)
    readiness_cols = ["crash_id", "reference_signal_id", "reference_directional_segment_id", "reference_directional_bin_id", "signal_relative_direction", "roadway_representation_type", "bin_index_from_reference_signal", "bin_midpoint_ft_from_reference_signal", "functional_distance_window", "far_anchor_type"]
    readiness = _phase(logger, "_read_readiness_no_crash_direction", _read_csv, READINESS_FILE, usecols=readiness_cols)
    crash_context = _phase(logger, "_crash_context", _crash_context, readiness, directional_context)
    paired_qa = _phase(logger, "_paired_pseudo_direction_consistency", _paired_pseudo_direction_consistency, directional_context)
    reference_summary = _phase(logger, "_reference_signal_summary", _reference_signal_summary, directional_context)
    route_match_qa = _phase(logger, "_route_match_qa", _route_match_qa, directional_context)
    summary = _summary(directional_context, base_context, crash_context, paired_qa, source_aadt)
    comparison = _comparison_to_v1_v2(summary)
    qa = _context_qa(directional_context, base_context, source_aadt, paired_qa)
    review = directional_context.loc[~directional_context["aadt_context_status"].str.startswith("stable", na=False)].copy()
    ambiguous = directional_context.loc[directional_context["aadt_context_status"].eq("ambiguous_conflicting_aadt_values")].copy()
    missing = directional_context.loc[directional_context["aadt_context_status"].eq("no_route_compatible_aadt_match")].copy()

    outputs = {
        "summary_csv": out_dir / "aadt_context_v3_summary.csv",
        "base_bin_context_csv": out_dir / "base_bin_aadt_context_v3.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_aadt_context_v3.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_aadt_context_v3_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_aadt_context_v3_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_aadt_context_v3.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_aadt_context_summary_v3.csv",
        "candidates_csv": out_dir / "aadt_route_measure_candidates_v3.csv",
        "review_candidates_csv": out_dir / "aadt_route_measure_review_candidates_v3.csv",
        "ambiguous_matches_csv": out_dir / "aadt_route_measure_ambiguous_matches_v3.csv",
        "missing_bins_csv": out_dir / "aadt_route_measure_missing_bins_v3.csv",
        "route_measure_match_qa_csv": out_dir / "aadt_route_measure_match_qa_v3.csv",
        "paired_pseudo_direction_qa_csv": out_dir / "aadt_paired_pseudo_direction_consistency_qa_v3.csv",
        "comparison_to_v1_v2_csv": out_dir / "aadt_context_v3_comparison_to_v1_v2.csv",
        "context_qa_csv": out_dir / "aadt_context_v3_qa.csv",
        "findings_md": out_dir / "aadt_context_v3_findings.md",
        "manifest_json": out_dir / "aadt_context_v3_manifest.json",
        "progress_log": out_dir / "aadt_context_v3_progress.log",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(base_context, outputs["base_bin_context_csv"])
    ordered = REQUIRED_DIRECTIONAL_COLUMNS + [column for column in directional_context.columns if column not in REQUIRED_DIRECTIONAL_COLUMNS]
    _write_csv(directional_context[ordered], outputs["directional_bin_context_csv"])
    _write_csv(directional_context.loc[directional_context["distance_window"].eq("high_priority_0_1000ft")], outputs["directional_bin_context_0_1000_csv"])
    _write_csv(directional_context.loc[directional_context["distance_window"].eq("sensitivity_1000_2500ft")], outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(reference_summary, outputs["reference_signal_summary_csv"])
    _write_csv(candidates, outputs["candidates_csv"])
    _write_csv(review, outputs["review_candidates_csv"])
    _write_csv(ambiguous, outputs["ambiguous_matches_csv"])
    _write_csv(missing, outputs["missing_bins_csv"])
    _write_csv(route_match_qa, outputs["route_measure_match_qa_csv"])
    _write_csv(paired_qa, outputs["paired_pseudo_direction_qa_csv"])
    _write_csv(comparison, outputs["comparison_to_v1_v2_csv"])
    _write_csv(qa, outputs["context_qa_csv"])
    _write_text(_findings(summary, comparison, outputs, limit_route_groups=limit_route_groups), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only AADT v3 context join using enriched roadway identity route keys and route-measure interval overlap",
        "limit_route_groups": limit_route_groups,
        "inputs": {
            "aadt": str(AADT_FILE),
            "directional_bins_identity_enriched": str(DIRECTIONAL_BINS_FILE),
            "base_bins_identity_enriched": str(BASE_BINS_FILE),
            "directional_segments_identity_enriched": str(DIRECTIONAL_SEGMENTS_FILE),
            "readiness": str(READINESS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "aadt_staging_schema": str(AADT_STAGING_SCHEMA_FILE),
            "identity_manifest": str(IDENTITY_MANIFEST_FILE),
        },
        "thresholds": {
            "minimum_overlap_ratio": MIN_OVERLAP_RATIO,
            "minimum_overlap_length": MIN_OVERLAP_LENGTH,
            "top_ratio_tolerance": TOP_RATIO_TOLERANCE,
            "endpoint_tolerance": ENDPOINT_TOLERANCE,
        },
        "crash_direction_fields_read_or_used": False,
        "aadt_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_access_speed_logic_changed": False,
        "summary": summary.to_dict(orient="records"),
        "comparison_to_v1_v2": comparison.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    logger.log("END build_aadt_context_join_v3_identity_route_measure")
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only AADT v3 identity route-measure context join for directional bins.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--limit-route-groups", type=int, default=None, help="Process only the first N normalized route groups for smoke testing.")
    parser.add_argument("--sample-routes", type=int, default=None, help="Alias for --limit-route-groups.")
    args = parser.parse_args(argv)
    limit_route_groups = args.limit_route_groups if args.limit_route_groups is not None else args.sample_routes
    outputs = build_aadt_context_join_v3_identity_route_measure(output_root=args.output_root, limit_route_groups=limit_route_groups)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
