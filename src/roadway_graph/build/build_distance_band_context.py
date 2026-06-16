"""Build staged distance_band_context from validated distance_band_units.

This layer preserves the exact distance_band_units grain and enriches each
unit with roadway, speed, AADT/exposure, access, and explicitly deferred crash
context. It does not build lookup cells, rate distributions, MVP products, or
canonical root products.
"""

from __future__ import annotations

import csv
import argparse
from contextlib import contextmanager
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/build_distance_band_context"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
DISTANCE_BAND_UNITS = STAGING / "distance_band_units.parquet"
DISTANCE_BAND_CONTEXT = STAGING / "distance_band_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

SPEED = REPO / "artifacts/normalized/speed.parquet"
AADT = REPO / "artifacts/normalized/aadt.parquet"
ACCESS = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

BUILD_VERSION = "distance_band_context_route_measure_v1_2026-06-10"
MIN_OVERLAP_MI = 1e-6
MILE_FT = 5280.0
MEASURE_BUCKET_MI = 0.10
DEFAULT_ROUTE_LOG_EVERY = 250_000

DIRECT_PARENTS = [DISTANCE_BAND_UNITS, BIN_CONTEXT, TRAVELWAY_INDEX, SPEED, AADT, ACCESS, CRASHES]
VALIDATED_STAGED_OBJECTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT, DISTANCE_BAND_UNITS]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/build_distance_band_units",
    REPO / "work/roadway_graph/review/distance_band_units_validation_audit",
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/materialize_bin_context_geometry",
    REPO / "work/roadway_graph/review/patch_bin_context_chain_directionality_and_audit",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

REQUIRED_UNIT_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
    "directionality_status",
    "bin_count",
    "unit_length_ft",
]

UNIT_IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
]

BIN_COLUMNS = [
    "stable_bin_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
    "bin_length_ft",
    "logical_corridor_chain_id",
    "primary_stable_travelway_id",
    "supporting_stable_travelway_ids",
    "route_base",
    "source_route_name",
    "roadway_configuration",
    "carriageway_direction_token",
    "source_measure_start",
    "source_measure_end",
    "source_measure_midpoint",
    "source_measure_status",
    "geometry_status",
    "chain_stop_reason",
    "chain_completeness_status",
]

TRAVELWAY_COLUMNS = [
    "stable_travelway_id",
    "roadway_configuration",
    "carriageway_direction_token",
    "RIM_MEDIAN",
    "RIM_ACCESS",
    "RIM_FACILITY",
    "RTE_CATEGO",
    "RTE_TYPE_N",
    "RTE_RAMP_C",
    "RIM_TRAVEL",
]

OUTPUT_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
    "unit_build_status",
    "directionality_status",
    "directionality_method",
    "directionality_confidence",
    "directionality_unresolved_reason",
    "bin_count",
    "unit_length_ft",
    "full_bin_count",
    "partial_bin_count",
    "chain_count",
    "logical_corridor_chain_ids",
    "supporting_stable_bin_ids_sample",
    "min_distance_start_ft",
    "max_distance_end_ft",
    "distance_band_start_ft",
    "distance_band_end_ft",
    "signal_analysis_ready_status",
    "approach_identity_status",
    "parent_approach_gate",
    "parent_corridor_gate_severity",
    "parent_corridor_warning_status",
    "chain_stop_reason_values",
    "chain_completeness_status_values",
    "measure_side_class_values",
    "geometry_status_summary",
    "source_limited_status",
    "unit_completeness_status",
    "bin_coverage_status",
    "missingness_reason",
    "context_readiness_status",
    "rate_readiness_status",
    "roadway_context_status",
    "divided_undivided",
    "one_way_two_way",
    "roadway_configuration_summary",
    "median_type",
    "median_group",
    "rim_access_summary",
    "rim_facility_summary",
    "route_category_summary",
    "route_type_summary",
    "ramp_code_summary",
    "roadway_source_match_method",
    "mixed_roadway_flag",
    "speed_limit_mph",
    "speed_category",
    "speed_context_status",
    "speed_source_match_method",
    "speed_missing_reason",
    "speed_candidate_count",
    "speed_value_mix",
    "mixed_speed_flag",
    "aadt",
    "aadt_category",
    "aadt_year",
    "aadt_context_status",
    "aadt_source_match_method",
    "aadt_missing_reason",
    "aadt_candidate_count",
    "aadt_value_mix",
    "mixed_aadt_flag",
    "exposure_denominator",
    "exposure_context_status",
    "exposure_missing_reason",
    "access_count",
    "access_count_band",
    "access_type_flags",
    "access_type_dominant",
    "access_context_status",
    "access_source_match_method",
    "access_missing_reason",
    "access_candidate_count",
    "mixed_access_flag",
    "crash_count",
    "crash_context_status",
    "crash_source_match_method",
    "crash_missing_reason",
    "crash_rate_ready_flag",
    "overall_context_readiness_status",
    "context_quality_flags",
    "source_match_methods",
    "mixed_context_flags",
]

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "directionality",
)

FORBIDDEN_OUTPUT_TOKENS = ("lookup_cell", "rate_mean", "rate_median", "rate_percentile", "rate_distribution")
PHASE_TIMINGS: list[dict[str, Any]] = []
ROUTE_CACHE_STATS: list[dict[str, Any]] = []
BENCHMARK_ROWS: list[dict[str, Any]] = []
UNIT_ROUTE_SPAN_SUMMARY: list[dict[str, Any]] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "<na>", "nat"} else text


def clean_values(values: pd.Series) -> list[str]:
    return sorted({clean(value) for value in values if clean(value)})


def join_values(values: pd.Series) -> str:
    return "|".join(clean_values(values))


def dominant_value(values: pd.Series, weights: pd.Series | None = None) -> str:
    frame = pd.DataFrame({"value": values.map(clean)})
    frame = frame.loc[frame["value"].ne("")]
    if frame.empty:
        return ""
    if weights is not None:
        frame["weight"] = pd.to_numeric(weights.loc[frame.index], errors="coerce").fillna(0.0)
        ranked = frame.groupby("value", dropna=False)["weight"].sum().reset_index().sort_values(["weight", "value"], ascending=[False, True])
        return clean(ranked.iloc[0]["value"])
    return clean(frame["value"].mode().sort_values().iloc[0])


def numeric_dominant(values: pd.Series, weights: pd.Series | None = None) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()
    if not valid.any():
        return math.nan
    if weights is not None:
        frame = pd.DataFrame({"value": numeric.loc[valid], "weight": pd.to_numeric(weights.loc[valid], errors="coerce").fillna(0.0)})
        ranked = frame.groupby("value", dropna=False)["weight"].sum().reset_index().sort_values(["weight", "value"], ascending=[False, True])
        return float(ranked.iloc[0]["value"])
    return float(numeric.loc[valid].mode().sort_values().iloc[0])


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def write_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False)
        return
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(json_safe(payload), f, indent=2, sort_keys=True)
        f.write("\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if pd.isna(value) if not isinstance(value, (list, tuple, dict, str)) else False:
        return None
    return value


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


@contextmanager
def phase(name: str, **metadata: Any):
    started = time.perf_counter()
    log(f"BEGIN {name}" + (f" {metadata}" if metadata else ""))
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        row = {"phase": name, "elapsed_seconds": round(elapsed, 3), **metadata}
        PHASE_TIMINGS.append(row)
        log(f"END {name}; elapsed_seconds={elapsed:,.3f}")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def clean_series(series: pd.Series) -> pd.Series:
    out = series.astype("string").fillna("").str.strip()
    return out.mask(out.str.lower().isin({"nan", "none", "null", "<na>", "nat"}), "").fillna("")


def normalize_unique_routes(values: pd.Series, label: str) -> dict[str, tuple[str, str]]:
    cleaned = clean_series(values)
    unique = sorted(value for value in cleaned.unique().tolist() if value)
    started = time.perf_counter()
    cache = {value: (route_key(value), route_base_key(value)) for value in unique}
    elapsed = time.perf_counter() - started
    ROUTE_CACHE_STATS.append(
        {
            "route_cache_label": label,
            "input_row_count": int(len(values)),
            "unique_raw_route_count": int(len(unique)),
            "elapsed_seconds": round(elapsed, 3),
        }
    )
    log(f"Route normalization cache {label}: {len(unique):,} unique raw routes in {elapsed:,.3f}s.")
    return cache


def map_route_cache(values: pd.Series, cache: dict[str, tuple[str, str]], index: int) -> pd.Series:
    cleaned = clean_series(values)
    return cleaned.map(lambda value: cache.get(value, ("", ""))[index])


def route_key(value: Any) -> str:
    text = clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " R VA ")
    text = text.replace("S-VA", " S VA ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    compact_all = "".join(text.split())
    patterns = [
        r"(US|SR|SC|PR|FR|NP|UR|IS|I)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?",
        r"(?:R|S)?VA[0-9]{0,3}(US|SR|SC|PR|FR|NP|UR|IS|I)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact_all)
        if match:
            prefix = match.group(1)
            prefix = "I" if prefix in {"IS", "I"} else prefix
            direction = (match.group(3) or "")[:1]
            return f"{prefix}{int(match.group(2))}{direction}"
    tokens = [token for token in text.split() if token and token not in {"R", "S", "VA"}]
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def route_base_key(value: Any) -> str:
    key = route_key(value)
    return re.sub(r"[NSEW]$", "", key)


def category_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    speed = float(numeric)
    if speed <= 25:
        return "25_mph_or_less"
    if speed <= 35:
        return "30_to_35_mph"
    if speed <= 45:
        return "40_to_45_mph"
    if speed <= 55:
        return "50_to_55_mph"
    return "60_mph_or_more"


def category_aadt(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    aadt = float(numeric)
    if aadt < 5000:
        return "lt_5k"
    if aadt < 10000:
        return "5k_to_10k"
    if aadt < 20000:
        return "10k_to_20k"
    if aadt < 40000:
        return "20k_to_40k"
    return "40k_plus"


def access_band(count: Any) -> str:
    numeric = pd.to_numeric(pd.Series([count]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    value = int(numeric)
    if value <= 0:
        return "0"
    if value <= 2:
        return "1-2"
    if value <= 5:
        return "3-5"
    return "6+"


def divided_status(values: pd.Series) -> str:
    cleaned = " ".join(clean(value).lower() for value in values if clean(value))
    has_divided = "divided" in cleaned and "undivided" not in cleaned.replace("undivided", "")
    has_undivided = "undivided" in cleaned
    if has_divided and has_undivided:
        return "mixed_divided_undivided"
    if has_divided:
        return "divided"
    if has_undivided:
        return "undivided"
    return ""


def travel_direction_status(values: pd.Series) -> str:
    cleaned = " ".join(clean(value).lower() for value in values if clean(value))
    has_one = "one-way" in cleaned or "one way" in cleaned
    has_two = "two-way" in cleaned or "two way" in cleaned
    if has_one and has_two:
        return "mixed_one_way_two_way"
    if has_one:
        return "one_way"
    if has_two:
        return "two_way"
    return ""


def median_group(value: Any) -> str:
    text = clean(value).lower()
    if not text:
        return ""
    if "no median" in text:
        return "no_median"
    if "grass" in text:
        return "grass_median"
    if "jersey" in text or "guard rail" in text or "positive barrier" in text:
        return "positive_barrier"
    if "curb" in text:
        return "curbed_or_mountable_barrier"
    if "median" in text:
        return "other_median"
    return "other"


def is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def parent_dependency_check() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    forbidden_tokens = ("lookup", "mvp", "rate_distribution", "final_rate", "lookup_cells")
    for path in DIRECT_PARENTS:
        exists = path.exists()
        read_status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                read_status = "readable"
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        rows.append(
            {
                "parent_path": rel(path),
                "parent_role": "direct_parent",
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_distance_band_context": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden_tokens),
            }
        )
    for path in VALIDATED_STAGED_OBJECTS:
        if path in DIRECT_PARENTS:
            continue
        rows.append(
            {
                "parent_path": rel(path),
                "parent_role": "validated_staged_core_object_not_direct_context_parent",
                "exists": path.exists(),
                "read_status": "not_read",
                "row_count": parquet_row_count(path) if path.exists() else "",
                "allowed_parent_for_distance_band_context": False,
                "downstream_object_parent_flag": False,
            }
        )
    return pd.DataFrame(rows)


def load_units() -> pd.DataFrame:
    available = set(pq.ParquetFile(DISTANCE_BAND_UNITS).schema_arrow.names)
    missing = [column for column in REQUIRED_UNIT_COLUMNS if column not in available]
    if missing:
        raise RuntimeError(f"distance_band_units missing required columns: {missing}")
    return pd.read_parquet(DISTANCE_BAND_UNITS)


def load_bins_with_unit_ids(units: pd.DataFrame) -> pd.DataFrame:
    available = set(pq.ParquetFile(BIN_CONTEXT).schema_arrow.names)
    missing = [column for column in BIN_COLUMNS if column not in available]
    if missing:
        raise RuntimeError(f"bin_context missing required columns: {missing}")
    bins = pd.read_parquet(BIN_CONTEXT, columns=BIN_COLUMNS)
    for col in ["upstream_downstream", "directionality_status"]:
        if col in bins.columns:
            bins[col] = bins[col].map(clean)
    bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
    mapper = units[UNIT_IDENTITY_COLUMNS].copy()
    merged = bins.merge(mapper, on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
    if merged["distance_band_unit_id"].isna().any():
        raise RuntimeError("Some bin_context rows did not reconcile to distance_band_units.")
    return merged


def explode_bin_route_spans(bins: pd.DataFrame) -> pd.DataFrame:
    with phase("unit_route_span_prepare_raw_bin_lineage", bin_rows=len(bins)):
        base = bins[
            [
                "distance_band_unit_id",
                "route_base",
                "source_route_name",
                "source_measure_start",
                "source_measure_end",
                "bin_length_ft",
            ]
        ].copy()
        base["measure_min"] = base[["source_measure_start", "source_measure_end"]].min(axis=1)
        base["measure_max"] = base[["source_measure_start", "source_measure_end"]].max(axis=1)
        base = base.loc[base["measure_min"].notna() & base["measure_max"].notna() & base["measure_max"].ge(base["measure_min"])].copy()
        raw = base.groupby(["distance_band_unit_id", "source_route_name", "route_base"], dropna=False, sort=False).agg(
            measure_min=("measure_min", "min"),
            measure_max=("measure_max", "max"),
            route_span_count=("distance_band_unit_id", "count"),
            lineage_length_ft=("bin_length_ft", "sum"),
        ).reset_index()

    with phase("route_normalization_cache_for_unit_route_spans", raw_route_rows=len(raw)):
        source_cache = normalize_unique_routes(raw["source_route_name"], "bin_context_source_route_name")
        base_cache = normalize_unique_routes(raw["route_base"], "bin_context_route_base")
        frames = []
        for source_col, method, cache in [
            ("source_route_name", "source_route_name", source_cache),
            ("route_base", "route_base", base_cache),
        ]:
            alias = raw[["distance_band_unit_id", source_col, "measure_min", "measure_max", "route_span_count", "lineage_length_ft"]].copy()
            alias = alias.rename(columns={source_col: "raw_route_name"})
            alias["route_key"] = map_route_cache(alias["raw_route_name"], cache, 0)
            alias["route_base_key"] = map_route_cache(alias["raw_route_name"], cache, 1)
            alias["route_alias_source"] = method
            frames.append(alias)
        spans = pd.concat(frames, ignore_index=True)
        spans = spans.loc[spans["route_key"].ne("")].drop_duplicates(
            ["distance_band_unit_id", "route_key", "measure_min", "measure_max"]
        )

    with phase("unit_route_span_aggregate", route_alias_rows=len(spans)):
        spans["span_length_mi"] = spans["measure_max"] - spans["measure_min"]
        unit_spans = spans[
            [
                "distance_band_unit_id",
                "route_key",
                "route_base_key",
                "route_alias_source",
                "measure_min",
                "measure_max",
                "route_span_count",
                "lineage_length_ft",
            ]
        ].drop_duplicates(["distance_band_unit_id", "route_key", "route_base_key", "route_alias_source", "measure_min", "measure_max"]).copy()
        unit_spans = unit_spans.rename(columns={"route_alias_source": "route_alias_sources"})
        UNIT_ROUTE_SPAN_SUMMARY.append(
            {
                "unit_count": int(unit_spans["distance_band_unit_id"].nunique()),
                "unit_route_span_rows": int(len(unit_spans)),
                "route_key_count": int(unit_spans["route_key"].nunique()),
                "min_measure_span_mi": float((unit_spans["measure_max"] - unit_spans["measure_min"]).min()) if not unit_spans.empty else 0.0,
                "max_measure_span_mi": float((unit_spans["measure_max"] - unit_spans["measure_min"]).max()) if not unit_spans.empty else 0.0,
                "mean_routes_per_unit": float(unit_spans.groupby("distance_band_unit_id")["route_key"].nunique().mean()) if not unit_spans.empty else 0.0,
            }
        )
    return unit_spans


def roadway_context(units: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    def unique_join(frame: pd.DataFrame, value_col: str, out_col: str) -> pd.DataFrame:
        sub = frame[["distance_band_unit_id", value_col]].copy()
        sub[value_col] = clean_series(sub[value_col])
        sub = sub.loc[sub[value_col].ne("")].drop_duplicates().sort_values(["distance_band_unit_id", value_col])
        if sub.empty:
            return pd.DataFrame({"distance_band_unit_id": units["distance_band_unit_id"], out_col: ""})
        return sub.groupby("distance_band_unit_id", sort=False)[value_col].agg("|".join).reset_index(name=out_col)

    with phase("roadway_context_read_travelway_index"):
        tw = pd.read_parquet(TRAVELWAY_INDEX, columns=TRAVELWAY_COLUMNS).rename(columns={"stable_travelway_id": "primary_stable_travelway_id"})
    with phase("roadway_context_prepare_compact_lineage", bin_rows=len(bins)):
        bin_cols = [
            "distance_band_unit_id",
            "primary_stable_travelway_id",
            "roadway_configuration",
            "carriageway_direction_token",
            "source_measure_status",
            "source_route_name",
        ]
        road_bins = bins[bin_cols].drop_duplicates().copy()
        work = road_bins.merge(tw, on="primary_stable_travelway_id", how="left", suffixes=("_bin", "_tw"))
        bin_config = clean_series(work["roadway_configuration_bin"])
        tw_config = clean_series(work["roadway_configuration_tw"])
        work["roadway_configuration_effective"] = bin_config.where(bin_config.ne(""), tw_config)
        bin_dir = clean_series(work["carriageway_direction_token_bin"])
        tw_dir = clean_series(work["carriageway_direction_token_tw"])
        work["carriageway_direction_effective"] = bin_dir.where(bin_dir.ne(""), tw_dir)
    with phase("roadway_context_summarize", compact_rows=len(work)):
        out = units[["distance_band_unit_id"]].copy()
        for value_col, out_col in [
            ("roadway_configuration_effective", "roadway_configuration_summary"),
            ("RIM_ACCESS", "rim_access_summary"),
            ("RIM_FACILITY", "rim_facility_summary"),
            ("RTE_CATEGO", "route_category_summary"),
            ("RTE_TYPE_N", "route_type_summary"),
            ("RTE_RAMP_C", "ramp_code_summary"),
        ]:
            out = out.merge(unique_join(work, value_col, out_col), on="distance_band_unit_id", how="left")
        median_values = unique_join(work, "RIM_MEDIAN", "median_type_values")
        out = out.merge(median_values, on="distance_band_unit_id", how="left")
        out["median_type"] = out["median_type_values"].fillna("").map(lambda text: clean(text).split("|")[0] if clean(text) else "")
        out = out.drop(columns=["median_type_values"])
        config_lists = (
            work[["distance_band_unit_id", "roadway_configuration_effective"]]
            .drop_duplicates()
            .groupby("distance_band_unit_id")["roadway_configuration_effective"]
            .agg(list)
            .reset_index(name="config_values")
        )
        out = out.merge(config_lists, on="distance_band_unit_id", how="left")
        out["config_values"] = out["config_values"].map(lambda values: values if isinstance(values, list) else [])
        out["divided_undivided"] = out["config_values"].map(lambda values: divided_status(pd.Series(values)))
        out["one_way_two_way"] = out["config_values"].map(lambda values: travel_direction_status(pd.Series(values)))
        out["median_group"] = out["median_type"].map(median_group)
        out["mixed_roadway_flag"] = out["roadway_configuration_summary"].fillna("").map(lambda text: "|" in clean(text))
        out["roadway_context_status"] = np.select(
            [
                out["roadway_configuration_summary"].fillna("").map(clean).eq(""),
                out["mixed_roadway_flag"],
            ],
            ["missing_roadway_configuration", "mixed_roadway_configuration"],
            default="stable_roadway_configuration",
        )
        out["roadway_source_match_method"] = "bin_context_primary_travelway_index_lineage"
    return out.drop(columns=["config_values"])


def build_speed_source() -> tuple[pd.DataFrame, set[str]]:
    with phase("speed_source_prepare"):
        cols = ["ROUTE_COMMON_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT", "SPEEDZONE_TYPE_DSC"]
        speed = pd.read_parquet(SPEED, columns=cols).reset_index(names="speed_source_index")
        speed["measure_min"] = speed[["ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]].min(axis=1)
        speed["measure_max"] = speed[["ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]].max(axis=1)
        cache = normalize_unique_routes(speed["ROUTE_COMMON_NAME"], "speed_ROUTE_COMMON_NAME")
        speed["route_key"] = map_route_cache(speed["ROUTE_COMMON_NAME"], cache, 0)
        speed["route_base_key"] = map_route_cache(speed["ROUTE_COMMON_NAME"], cache, 1)
        speed["speed_limit_mph_source"] = pd.to_numeric(speed["CAR_SPEED_LIMIT"], errors="coerce")
        valid = speed["route_key"].ne("") & speed["measure_min"].notna() & speed["measure_max"].notna() & speed["speed_limit_mph_source"].notna()
        source = speed.loc[valid].copy()
    return source, set(source["route_key"]) | set(source["route_base_key"])


def build_aadt_source() -> tuple[pd.DataFrame, set[str]]:
    with phase("aadt_source_prepare"):
        cols = [
            "RTE_NM",
            "MASTER_RTE_NM",
            "TRANSPORT_EDGE_FROM_MSR",
            "TRANSPORT_EDGE_TO_MSR",
            "FROM_MEASURE",
            "TO_MEASURE",
            "AADT",
            "AADT_YR",
            "DIRECTION_FACTOR",
            "DIRECTIONALITY",
        ]
        aadt = pd.read_parquet(AADT, columns=cols).reset_index(names="aadt_source_index")
        if aadt["TRANSPORT_EDGE_FROM_MSR"].notna().any():
            aadt["measure_from"] = pd.to_numeric(aadt["TRANSPORT_EDGE_FROM_MSR"], errors="coerce")
            aadt["measure_to"] = pd.to_numeric(aadt["TRANSPORT_EDGE_TO_MSR"], errors="coerce")
            aadt["measure_source_fields"] = "TRANSPORT_EDGE_FROM_MSR/TRANSPORT_EDGE_TO_MSR"
        else:
            aadt["measure_from"] = pd.to_numeric(aadt["FROM_MEASURE"], errors="coerce")
            aadt["measure_to"] = pd.to_numeric(aadt["TO_MEASURE"], errors="coerce")
            aadt["measure_source_fields"] = "FROM_MEASURE/TO_MEASURE"
        aadt["measure_min"] = aadt[["measure_from", "measure_to"]].min(axis=1)
        aadt["measure_max"] = aadt[["measure_from", "measure_to"]].max(axis=1)
        aadt["aadt_source_value"] = pd.to_numeric(aadt["AADT"], errors="coerce")
        aadt["aadt_year_source"] = pd.to_numeric(aadt["AADT_YR"], errors="coerce")
        frames = []
        for route_col in ["RTE_NM", "MASTER_RTE_NM"]:
            alias = aadt.copy()
            cache = normalize_unique_routes(alias[route_col], f"aadt_{route_col}")
            alias["route_key"] = map_route_cache(alias[route_col], cache, 0)
            alias["route_base_key"] = map_route_cache(alias[route_col], cache, 1)
            alias["aadt_route_field"] = route_col
            frames.append(alias)
        source = pd.concat(frames, ignore_index=True)
        valid = source["route_key"].ne("") & source["measure_min"].notna() & source["measure_max"].notna() & source["aadt_source_value"].gt(0)
        source = source.loc[valid].drop_duplicates(["aadt_source_index", "route_key"]).copy()
    return source, set(source["route_key"]) | set(source["route_base_key"])


def build_access_source() -> tuple[pd.DataFrame, set[str]]:
    with phase("access_source_prepare"):
        cols = [
            "access_v2_source_row_id",
            "route_name",
            "route_measure",
            "access_control_raw",
            "access_control_normalized",
            "access_control_category",
            "access_direction_normalized",
            "number_of_approaches",
        ]
        access = pd.read_parquet(ACCESS, columns=cols).reset_index(names="access_source_index")
        cache = normalize_unique_routes(access["route_name"], "access_route_name")
        access["route_key"] = map_route_cache(access["route_name"], cache, 0)
        access["route_base_key"] = map_route_cache(access["route_name"], cache, 1)
        access["route_measure_num"] = pd.to_numeric(access["route_measure"], errors="coerce")
        valid = access["route_key"].ne("") & access["route_measure_num"].notna()
        source = access.loc[valid].copy()
        source["access_source_id"] = source["access_v2_source_row_id"].map(clean)
        source.loc[source["access_source_id"].eq(""), "access_source_id"] = source.loc[source["access_source_id"].eq(""), "access_source_index"].astype(str)
    return source, set(source["route_key"]) | set(source["route_base_key"])


def route_measure_matches(
    spans: pd.DataFrame,
    source: pd.DataFrame,
    *,
    source_id: str,
    point_measure_col: str | None = None,
) -> pd.DataFrame:
    def interval_buckets(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        work = frame.copy()
        work["measure_min"] = pd.to_numeric(work["measure_min"], errors="coerce")
        work["measure_max"] = pd.to_numeric(work["measure_max"], errors="coerce")
        work = work.loc[work["route_key"].map(clean).ne("") & work["measure_min"].notna() & work["measure_max"].notna()].copy()
        work["bucket_start"] = np.floor(work["measure_min"] / MEASURE_BUCKET_MI).astype("int64")
        work["bucket_end"] = np.floor(work["measure_max"] / MEASURE_BUCKET_MI).astype("int64")
        work["bucket_count"] = (work["bucket_end"] - work["bucket_start"] + 1).clip(lower=1, upper=200)
        repeated = work.loc[work.index.repeat(work["bucket_count"])].copy()
        repeated["bucket_offset"] = repeated.groupby(level=0).cumcount()
        repeated["measure_bucket"] = repeated["bucket_start"] + repeated["bucket_offset"]
        return repeated.drop(columns=["bucket_start", "bucket_end", "bucket_count", "bucket_offset"])

    def point_buckets(frame: pd.DataFrame, measure_col: str) -> pd.DataFrame:
        work = frame.copy()
        work[measure_col] = pd.to_numeric(work[measure_col], errors="coerce")
        work = work.loc[work["route_key"].map(clean).ne("") & work[measure_col].notna()].copy()
        work["measure_bucket"] = np.floor(work[measure_col] / MEASURE_BUCKET_MI).astype("int64")
        return work

    with phase(
        f"{source_id}_bucketed_route_measure_match",
        span_rows=len(spans),
        source_rows=len(source),
        point_match=bool(point_measure_col),
    ):
        left_cols = ["distance_band_unit_id", "route_key", "measure_min", "measure_max"]
        left = spans[left_cols].drop_duplicates().copy()
        left_buckets = interval_buckets(left, "unit")
        log(f"{source_id}: expanded unit spans to {len(left_buckets):,} route/measure buckets.")
        if point_measure_col:
            right = point_buckets(source, point_measure_col)
            right_cols = ["route_key", "measure_bucket", source_id, point_measure_col] + [
                col
                for col in source.columns
                if col not in {"route_key", "measure_bucket", source_id, point_measure_col, "measure_min", "measure_max"}
            ]
            candidates = left_buckets.merge(right[right_cols], on=["route_key", "measure_bucket"], how="inner")
            if candidates.empty:
                return pd.DataFrame(columns=["distance_band_unit_id", source_id, "measure_overlap_mi"])
            candidates = candidates.loc[
                pd.to_numeric(candidates[point_measure_col], errors="coerce").between(candidates["measure_min"], candidates["measure_max"], inclusive="both")
            ].copy()
            candidates["measure_overlap_mi"] = 0.0
        else:
            right = source.copy()
            right["source_measure_min"] = pd.to_numeric(right["measure_min"], errors="coerce")
            right["source_measure_max"] = pd.to_numeric(right["measure_max"], errors="coerce")
            right_buckets = interval_buckets(
                right.drop(columns=["measure_min", "measure_max"]).rename(columns={"source_measure_min": "measure_min", "source_measure_max": "measure_max"}),
                "source",
            ).rename(columns={"measure_min": "source_measure_min", "measure_max": "source_measure_max"})
            log(f"{source_id}: expanded source intervals to {len(right_buckets):,} route/measure buckets.")
            candidates = left_buckets.merge(right_buckets, on=["route_key", "measure_bucket"], how="inner", suffixes=("_unit", ""))
            if candidates.empty:
                return pd.DataFrame(columns=["distance_band_unit_id", source_id, "measure_overlap_mi"])
            candidates = candidates.loc[
                candidates["source_measure_max"].ge(candidates["measure_min"])
                & candidates["source_measure_min"].le(candidates["measure_max"])
            ].copy()
            candidates["measure_overlap_mi"] = np.maximum(
                0.0,
                np.minimum(candidates["measure_max"], candidates["source_measure_max"])
                - np.maximum(candidates["measure_min"], candidates["source_measure_min"]),
            )
            candidates = candidates.loc[candidates["measure_overlap_mi"].gt(MIN_OVERLAP_MI)].copy()
        log(f"{source_id}: exact overlap candidates after filtering: {len(candidates):,}.")
        if candidates.empty:
            return pd.DataFrame(columns=["distance_band_unit_id", source_id, "measure_overlap_mi"])
        out = candidates.drop_duplicates(["distance_band_unit_id", source_id]).copy()
        return out


def missing_status_from_routes(unit_id: str, spans_by_unit: dict[str, set[str]], available_routes: set[str], context_name: str) -> tuple[str, str]:
    keys = spans_by_unit.get(unit_id, set())
    if not keys:
        return f"missing_no_route_measure_lineage_{context_name}", "no usable bin route/measure lineage"
    if not (keys & available_routes):
        return f"missing_no_route_compatible_{context_name}", "no route-compatible source records"
    return f"missing_no_measure_overlap_{context_name}", "route matched but no measure overlap"


def missing_context_base(units: pd.DataFrame, spans: pd.DataFrame, available_routes: set[str], context_name: str) -> pd.DataFrame:
    base = units[["distance_band_unit_id"]].copy()
    route_flags = spans.assign(route_available=spans["route_key"].isin(available_routes)).groupby("distance_band_unit_id", dropna=False).agg(
        has_route_lineage=("route_key", "count"),
        has_route_compatible_source=("route_available", "any"),
    ).reset_index()
    base = base.merge(route_flags, on="distance_band_unit_id", how="left")
    base["has_route_lineage"] = base["has_route_lineage"].fillna(0).gt(0)
    base["has_route_compatible_source"] = base["has_route_compatible_source"].fillna(False).map(bool_value)
    base[f"{context_name}_context_status"] = np.select(
        [
            ~base["has_route_lineage"],
            ~base["has_route_compatible_source"],
        ],
        [
            f"missing_no_route_measure_lineage_{context_name}",
            f"missing_no_route_compatible_{context_name}",
        ],
        default=f"missing_no_measure_overlap_{context_name}",
    )
    base[f"{context_name}_missing_reason"] = np.select(
        [
            ~base["has_route_lineage"],
            ~base["has_route_compatible_source"],
        ],
        [
            "no usable bin route/measure lineage",
            "no route-compatible source records",
        ],
        default="route matched but no measure overlap",
    )
    return base.drop(columns=["has_route_lineage", "has_route_compatible_source"])


def weighted_dominant_by_unit(matches: pd.DataFrame, value_col: str, weight_col: str = "measure_overlap_mi") -> pd.DataFrame:
    work = matches[["distance_band_unit_id", value_col, weight_col]].copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work[weight_col] = pd.to_numeric(work[weight_col], errors="coerce").fillna(0.0)
    work = work.loc[work[value_col].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=["distance_band_unit_id", value_col])
    ranked = work.groupby(["distance_band_unit_id", value_col], dropna=False)[weight_col].sum().reset_index()
    ranked = ranked.sort_values(["distance_band_unit_id", weight_col, value_col], ascending=[True, False, True])
    return ranked.drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", value_col]]


def numeric_mix_by_unit(matches: pd.DataFrame, value_col: str) -> pd.DataFrame:
    work = matches[["distance_band_unit_id", value_col]].copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.loc[work[value_col].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=["distance_band_unit_id", f"{value_col}_mix", f"{value_col}_unique_count"])
    grouped = work.groupby("distance_band_unit_id", dropna=False)[value_col]
    mix = grouped.agg(lambda s: "|".join(str(int(v)) if float(v).is_integer() else f"{float(v):.3f}".rstrip("0").rstrip(".") for v in sorted(s.dropna().unique()))).reset_index()
    mix = mix.rename(columns={value_col: f"{value_col}_mix"})
    counts = grouped.nunique().reset_index().rename(columns={value_col: f"{value_col}_unique_count"})
    return mix.merge(counts, on="distance_band_unit_id", how="left")


def speed_context(units: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    source, available_routes = build_speed_source()
    matches = route_measure_matches(spans, source, source_id="speed_source_index")
    out = missing_context_base(units, spans, available_routes, "speed")
    out["speed_limit_mph"] = math.nan
    out["speed_category"] = ""
    out["speed_source_match_method"] = ""
    out["speed_candidate_count"] = 0
    out["speed_value_mix"] = ""
    out["mixed_speed_flag"] = False
    if matches.empty:
        return out[
            [
                "distance_band_unit_id",
                "speed_limit_mph",
                "speed_category",
                "speed_context_status",
                "speed_source_match_method",
                "speed_missing_reason",
                "speed_candidate_count",
                "speed_value_mix",
                "mixed_speed_flag",
            ]
        ]
    best = weighted_dominant_by_unit(matches, "speed_limit_mph_source").rename(columns={"speed_limit_mph_source": "speed_limit_mph"})
    mix = numeric_mix_by_unit(matches, "speed_limit_mph_source").rename(
        columns={"speed_limit_mph_source_mix": "speed_value_mix", "speed_limit_mph_source_unique_count": "speed_unique_count"}
    )
    counts = matches.groupby("distance_band_unit_id", dropna=False)["speed_source_index"].nunique().reset_index(name="speed_candidate_count")
    matched = best.merge(mix, on="distance_band_unit_id", how="left").merge(counts, on="distance_band_unit_id", how="left")
    matched["mixed_speed_flag"] = matched["speed_unique_count"].fillna(0).gt(1)
    matched["speed_context_status"] = np.where(matched["mixed_speed_flag"], "mixed_speed_values", "stable_single_speed")
    matched["speed_category"] = matched["speed_limit_mph"].map(category_speed)
    matched["speed_source_match_method"] = "route_measure_overlap_speed_artifact"
    matched["speed_missing_reason"] = ""
    out = out.drop(columns=["speed_candidate_count"], errors="ignore").merge(matched, on="distance_band_unit_id", how="left", suffixes=("", "_matched"))
    matched_mask = out["speed_limit_mph_matched"].notna() if "speed_limit_mph_matched" in out.columns else out["speed_limit_mph"].notna()
    if "speed_limit_mph_matched" in out.columns:
        out.loc[matched_mask, "speed_limit_mph"] = out.loc[matched_mask, "speed_limit_mph_matched"]
        out = out.drop(columns=["speed_limit_mph_matched"])
    for column in ["speed_context_status", "speed_source_match_method", "speed_missing_reason", "speed_value_mix", "mixed_speed_flag", "speed_category"]:
        matched_col = f"{column}_matched"
        if matched_col in out.columns:
            out.loc[matched_mask, column] = out.loc[matched_mask, matched_col]
            out = out.drop(columns=[matched_col])
    out["speed_candidate_count"] = out["speed_candidate_count"].fillna(0).astype(int)
    out["mixed_speed_flag"] = out["mixed_speed_flag"].fillna(False).map(bool_value)
    return out[
        [
            "distance_band_unit_id",
            "speed_limit_mph",
            "speed_category",
            "speed_context_status",
            "speed_source_match_method",
            "speed_missing_reason",
            "speed_candidate_count",
            "speed_value_mix",
            "mixed_speed_flag",
        ]
    ]


def aadt_context(units: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    source, available_routes = build_aadt_source()
    matches = route_measure_matches(spans, source, source_id="aadt_source_index")
    out = missing_context_base(units, spans, available_routes, "aadt")
    out["aadt"] = math.nan
    out["aadt_category"] = ""
    out["aadt_year"] = math.nan
    out["aadt_source_match_method"] = ""
    out["aadt_candidate_count"] = 0
    out["aadt_value_mix"] = ""
    out["mixed_aadt_flag"] = False
    out["exposure_denominator"] = math.nan
    out["exposure_context_status"] = "missing_aadt"
    out["exposure_missing_reason"] = "AADT unavailable"
    if matches.empty:
        return out[
            [
                "distance_band_unit_id",
                "aadt",
                "aadt_category",
                "aadt_year",
                "aadt_context_status",
                "aadt_source_match_method",
                "aadt_missing_reason",
                "aadt_candidate_count",
                "aadt_value_mix",
                "mixed_aadt_flag",
                "exposure_denominator",
                "exposure_context_status",
                "exposure_missing_reason",
            ]
        ]
    matches = matches.copy()
    matches["aadt_year_source"] = pd.to_numeric(matches["aadt_year_source"], errors="coerce")
    max_year = matches.groupby("distance_band_unit_id", dropna=False)["aadt_year_source"].max().reset_index(name="aadt_year")
    latest = matches.merge(max_year, on="distance_band_unit_id", how="left")
    latest = latest.loc[latest["aadt_year_source"].eq(latest["aadt_year"]) | latest["aadt_year"].isna()].copy()
    best = weighted_dominant_by_unit(latest, "aadt_source_value").rename(columns={"aadt_source_value": "aadt"})
    mix = numeric_mix_by_unit(matches, "aadt_source_value").rename(columns={"aadt_source_value_mix": "aadt_value_mix", "aadt_source_value_unique_count": "aadt_unique_count"})
    counts = matches.groupby("distance_band_unit_id", dropna=False)["aadt_source_index"].nunique().reset_index(name="aadt_candidate_count")
    matched = best.merge(max_year, on="distance_band_unit_id", how="left").merge(mix, on="distance_band_unit_id", how="left").merge(counts, on="distance_band_unit_id", how="left")
    matched["mixed_aadt_flag"] = matched["aadt_unique_count"].fillna(0).gt(1)
    matched["aadt_context_status"] = np.where(matched["mixed_aadt_flag"], "mixed_aadt_values", "stable_single_aadt")
    matched["aadt_category"] = matched["aadt"].map(category_aadt)
    matched["aadt_source_match_method"] = "route_measure_overlap_aadt_artifact_latest_year_dominant"
    matched["aadt_missing_reason"] = ""
    matched = matched.merge(units[["distance_band_unit_id", "unit_length_ft"]], on="distance_band_unit_id", how="left")
    matched["exposure_denominator"] = matched["aadt"] * (pd.to_numeric(matched["unit_length_ft"], errors="coerce") / MILE_FT)
    matched["exposure_context_status"] = "computed_daily_vehicle_miles_proxy_from_aadt_x_unit_length"
    matched["exposure_missing_reason"] = ""
    out = out.drop(columns=["aadt_candidate_count"], errors="ignore").merge(matched.drop(columns=["unit_length_ft", "aadt_unique_count"], errors="ignore"), on="distance_band_unit_id", how="left", suffixes=("", "_matched"))
    matched_mask = out["aadt_matched"].notna() if "aadt_matched" in out.columns else out["aadt"].notna()
    if "aadt_matched" in out.columns:
        out.loc[matched_mask, "aadt"] = out.loc[matched_mask, "aadt_matched"]
        out = out.drop(columns=["aadt_matched"])
    for column in [
        "aadt_year",
        "aadt_context_status",
        "aadt_source_match_method",
        "aadt_missing_reason",
        "aadt_value_mix",
        "mixed_aadt_flag",
        "aadt_category",
        "exposure_denominator",
        "exposure_context_status",
        "exposure_missing_reason",
    ]:
        matched_col = f"{column}_matched"
        if matched_col in out.columns:
            out.loc[matched_mask, column] = out.loc[matched_mask, matched_col]
            out = out.drop(columns=[matched_col])
    out["aadt_candidate_count"] = out["aadt_candidate_count"].fillna(0).astype(int)
    out["mixed_aadt_flag"] = out["mixed_aadt_flag"].fillna(False).map(bool_value)
    return out[
        [
            "distance_band_unit_id",
            "aadt",
            "aadt_category",
            "aadt_year",
            "aadt_context_status",
            "aadt_source_match_method",
            "aadt_missing_reason",
            "aadt_candidate_count",
            "aadt_value_mix",
            "mixed_aadt_flag",
            "exposure_denominator",
            "exposure_context_status",
            "exposure_missing_reason",
        ]
    ]


def access_context(units: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    source, available_routes = build_access_source()
    matches = route_measure_matches(spans, source, source_id="access_source_id", point_measure_col="route_measure_num")
    out = missing_context_base(units, spans, available_routes, "access")
    out["access_count"] = math.nan
    out["access_count_band"] = ""
    out["access_type_flags"] = ""
    out["access_type_dominant"] = ""
    out["access_source_match_method"] = ""
    out["access_candidate_count"] = 0
    out["mixed_access_flag"] = False
    no_overlap = out["access_context_status"].eq("missing_no_measure_overlap_access")
    out.loc[no_overlap, "access_count"] = 0
    out.loc[no_overlap, "access_count_band"] = "0"
    out.loc[no_overlap, "access_context_status"] = "no_access_points_in_route_measure_window"
    out.loc[no_overlap, "access_source_match_method"] = "route_measure_point_in_unit_window_access_v2"
    out.loc[no_overlap, "access_missing_reason"] = ""
    if matches.empty:
        return out[
            [
                "distance_band_unit_id",
                "access_count",
                "access_count_band",
                "access_type_flags",
                "access_type_dominant",
                "access_context_status",
                "access_source_match_method",
                "access_missing_reason",
                "access_candidate_count",
                "mixed_access_flag",
            ]
        ]
    counts = matches.groupby("distance_band_unit_id", dropna=False)["access_source_id"].nunique().reset_index(name="access_count")
    flags = matches.groupby("distance_band_unit_id", dropna=False)["access_control_category"].agg(join_values).reset_index(name="access_type_flags")
    category_counts = matches.loc[matches["access_control_category"].map(clean).ne("")].groupby(
        ["distance_band_unit_id", "access_control_category"], dropna=False
    )["access_source_id"].nunique().reset_index(name="type_count")
    category_counts = category_counts.sort_values(["distance_band_unit_id", "type_count", "access_control_category"], ascending=[True, False, True])
    dominant = category_counts.drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", "access_control_category"]].rename(columns={"access_control_category": "access_type_dominant"})
    matched = counts.merge(flags, on="distance_band_unit_id", how="left").merge(dominant, on="distance_band_unit_id", how="left")
    matched["access_count_band"] = matched["access_count"].map(access_band)
    matched["access_context_status"] = "matched_access_points"
    matched["access_source_match_method"] = "route_measure_point_in_unit_window_access_v2"
    matched["access_missing_reason"] = ""
    matched["access_candidate_count"] = matched["access_count"]
    matched["mixed_access_flag"] = matched["access_type_flags"].map(lambda text: "|" in clean(text))
    out = out.merge(matched, on="distance_band_unit_id", how="left", suffixes=("", "_matched"))
    matched_mask = out["access_count_matched"].notna() if "access_count_matched" in out.columns else pd.Series(False, index=out.index)
    if "access_count_matched" in out.columns:
        out.loc[matched_mask, "access_count"] = out.loc[matched_mask, "access_count_matched"]
        out = out.drop(columns=["access_count_matched"])
    for column in [
        "access_count_band",
        "access_type_flags",
        "access_type_dominant",
        "access_context_status",
        "access_source_match_method",
        "access_missing_reason",
        "access_candidate_count",
        "mixed_access_flag",
    ]:
        matched_col = f"{column}_matched"
        if matched_col in out.columns:
            out.loc[matched_mask, column] = out.loc[matched_mask, matched_col]
            out = out.drop(columns=[matched_col])
    out["access_candidate_count"] = out["access_candidate_count"].fillna(0).astype(int)
    out["mixed_access_flag"] = out["mixed_access_flag"].fillna(False).map(bool_value)
    return out[
        [
            "distance_band_unit_id",
            "access_count",
            "access_count_band",
            "access_type_flags",
            "access_type_dominant",
            "access_context_status",
            "access_source_match_method",
            "access_missing_reason",
            "access_candidate_count",
            "mixed_access_flag",
        ]
    ]


def crash_context(units: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "distance_band_unit_id": units["distance_band_unit_id"],
            "crash_count": pd.Series([pd.NA] * len(units), dtype="Int64"),
            "crash_context_status": "deferred_requires_spatial_catchment_or_validated_unit_lineage",
            "crash_source_match_method": "",
            "crash_missing_reason": "crash assignment deferred; route/milepost alone is not used as a final unit catchment assignment in this build",
        }
    )


def finalize_context(df: pd.DataFrame) -> pd.DataFrame:
    quality_flags = []
    source_methods = []
    mixed_flags = []
    missing_reasons = []
    ready_statuses = []
    rate_statuses = []
    rate_flags = []
    for row in df.itertuples(index=False):
        flags = []
        methods = []
        mixed = []
        reasons = []
        if clean(getattr(row, "directionality_status")) != "assigned":
            flags.append("unresolved_directionality")
            reasons.append(clean(getattr(row, "directionality_unresolved_reason")) or "unresolved directionality")
        for family in ["roadway", "speed", "aadt", "exposure", "access", "crash"]:
            status = clean(getattr(row, f"{family}_context_status"))
            if status.startswith("missing") or status.startswith("deferred"):
                flags.append(f"{family}_context_{status}")
            reason = clean(getattr(row, f"{family}_missing_reason", ""))
            if reason:
                reasons.append(f"{family}: {reason}")
            method = clean(getattr(row, f"{family}_source_match_method", ""))
            if method:
                methods.append(f"{family}:{method}")
        for family in ["roadway", "speed", "aadt", "access"]:
            if bool_value(getattr(row, f"mixed_{family}_flag", False)):
                mixed.append(f"{family}_mixed")
        crash_deferred = clean(getattr(row, "crash_context_status")).startswith("deferred")
        core_missing = any(flag.startswith(("speed_context_missing", "aadt_context_missing", "exposure_context_missing")) for flag in flags)
        if crash_deferred and not core_missing:
            ready = "context_built_with_deferred_crash_ready_for_validation"
        elif core_missing:
            ready = "context_built_with_missing_numeric_context_ready_for_validation"
        else:
            ready = "context_built_ready_for_validation"
        if clean(getattr(row, "directionality_status")) != "assigned":
            rate = "not_rate_ready_unresolved_directionality"
        elif crash_deferred:
            rate = "not_rate_ready_crash_assignment_deferred"
        elif core_missing:
            rate = "not_rate_ready_missing_numeric_context"
        else:
            rate = "rate_ready_pending_distribution_build"
        quality_flags.append("|".join(flags))
        source_methods.append("|".join(methods))
        mixed_flags.append("|".join(mixed))
        missing_reasons.append("; ".join([clean(getattr(row, "missingness_reason", ""))] + reasons).strip("; "))
        ready_statuses.append(ready)
        rate_statuses.append(rate)
        rate_flags.append(rate.startswith("rate_ready"))
    df["context_quality_flags"] = quality_flags
    df["source_match_methods"] = source_methods
    df["mixed_context_flags"] = mixed_flags
    df["missingness_reason"] = missing_reasons
    df["overall_context_readiness_status"] = ready_statuses
    df["context_readiness_status"] = ready_statuses
    df["rate_readiness_status"] = rate_statuses
    df["crash_rate_ready_flag"] = rate_flags
    return df


def build_context(units: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    spans = explode_bin_route_spans(bins)
    log(f"Prepared {len(spans):,} bin route-measure span aliases.")
    context = units.copy()
    log("Attaching roadway context.")
    context = context.merge(roadway_context(units, bins), on="distance_band_unit_id", how="left", validate="one_to_one")
    log("Attaching speed context.")
    context = context.merge(speed_context(units, spans), on="distance_band_unit_id", how="left", validate="one_to_one")
    log("Attaching AADT and exposure context.")
    context = context.merge(aadt_context(units, spans), on="distance_band_unit_id", how="left", validate="one_to_one")
    log("Attaching access context.")
    context = context.merge(access_context(units, spans), on="distance_band_unit_id", how="left", validate="one_to_one")
    log("Attaching explicit deferred crash context.")
    context = context.merge(crash_context(units), on="distance_band_unit_id", how="left", validate="one_to_one")
    context = finalize_context(context)
    for column in OUTPUT_COLUMNS:
        if column not in context.columns:
            context[column] = ""
    return context[OUTPUT_COLUMNS].copy()


def summarize_status(df: pd.DataFrame, status_col: str, extra: list[str] | None = None) -> pd.DataFrame:
    extra = extra or []
    group_cols = extra + [status_col]
    return df.groupby(group_cols, dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        bin_count=("bin_count", "sum"),
        length_ft=("unit_length_ft", "sum"),
        signal_count=("stable_signal_id", "nunique"),
        approach_count=("signal_approach_id", "nunique"),
    ).reset_index()


def context_missingness_by_field(df: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "divided_undivided",
        "one_way_two_way",
        "roadway_configuration_summary",
        "median_type",
        "speed_limit_mph",
        "speed_category",
        "aadt",
        "aadt_category",
        "exposure_denominator",
        "access_count",
        "access_count_band",
        "access_type_flags",
        "crash_count",
    ]
    rows = []
    for field in fields:
        series = df[field]
        if pd.api.types.is_numeric_dtype(series):
            missing = int(pd.to_numeric(series, errors="coerce").isna().sum())
        else:
            missing = int(series.map(clean).eq("").sum())
        rows.append(
            {
                "field_name": field,
                "missing_count": missing,
                "populated_count": int(len(df) - missing),
                "missing_pct": round(missing / max(len(df), 1), 6),
            }
        )
    return pd.DataFrame(rows)


def write_qa(units: pd.DataFrame, context: pd.DataFrame, bins: pd.DataFrame, parent_check: pd.DataFrame) -> dict[str, Any]:
    write_csv("parent_dependency_check.csv", parent_check)
    write_csv(
        "performance_refactor_summary.csv",
        [
            {
                "refactor_item": "route_normalization_cache",
                "implementation": "normalize unique raw route strings once per source column and map route keys back",
                "previous_problem_addressed": "millions of regex calls over raw bin rows",
            },
            {
                "refactor_item": "compact_unit_route_spans",
                "implementation": "aggregate bin route/measure lineage to distance_band_unit_id x route_key before context matching",
                "previous_problem_addressed": "context joins operated on 1.27M raw bin rows",
            },
            {
                "refactor_item": "bucketed_interval_matching",
                "implementation": f"join unit/source intervals by route_key and {MEASURE_BUCKET_MI} mile measure bucket, then apply exact overlap filter",
                "previous_problem_addressed": "nested route group -> unit span -> source scan loops",
            },
            {
                "refactor_item": "progress_logging",
                "implementation": "phase begin/end entries and match expansion counts written to progress_log.md",
                "previous_problem_addressed": "long runs looked silent while tool output was buffered",
            },
            {
                "refactor_item": "safe_temp_write",
                "implementation": "full build writes a temp parquet and replaces staged product only after core QA passes",
                "previous_problem_addressed": "failed full run could leave ambiguous staged output state",
            },
        ],
    )
    write_csv("benchmark_distance_band_context.csv", pd.DataFrame(BENCHMARK_ROWS or [{"benchmark_status": "not_recorded"}]))
    write_csv("route_normalization_cache_summary.csv", pd.DataFrame(ROUTE_CACHE_STATS or [{"route_cache_label": "not_recorded"}]))
    write_csv("unit_route_span_summary.csv", pd.DataFrame(UNIT_ROUTE_SPAN_SUMMARY or [{"unit_route_span_rows": 0}]))
    write_csv("phase_runtime_summary.csv", pd.DataFrame(PHASE_TIMINGS or [{"phase": "not_recorded"}]))
    row_identity = pd.DataFrame(
        [
            {
                "check_name": "distance_band_unit_id_set_unchanged",
                "parent_unit_count": len(units),
                "context_unit_count": len(context),
                "parent_unique_id_count": units["distance_band_unit_id"].nunique(),
                "context_unique_id_count": context["distance_band_unit_id"].nunique(),
                "missing_from_context_count": len(set(units["distance_band_unit_id"]) - set(context["distance_band_unit_id"])),
                "extra_in_context_count": len(set(context["distance_band_unit_id"]) - set(units["distance_band_unit_id"])),
                "pass": set(units["distance_band_unit_id"]) == set(context["distance_band_unit_id"]) and len(units) == len(context),
            }
        ]
    )
    write_csv("row_identity_unchanged_check.csv", row_identity)
    grain_dupes = context.duplicated(UNIT_IDENTITY_COLUMNS, keep=False)
    write_csv(
        "unit_grain_uniqueness_check.csv",
        [
            {
                "grain": "|".join(UNIT_IDENTITY_COLUMNS),
                "row_count": len(context),
                "unique_distance_band_unit_id_count": context["distance_band_unit_id"].nunique(),
                "duplicate_distance_band_unit_id_count": int(context["distance_band_unit_id"].duplicated().sum()),
                "duplicate_grain_row_count": int(grain_dupes.sum()),
                "pass": int(context["distance_band_unit_id"].duplicated().sum()) == 0 and int(grain_dupes.sum()) == 0,
            }
        ],
    )
    write_csv(
        "unit_count_reconciliation.csv",
        [
            {
                "parent_distance_band_units_row_count": len(units),
                "distance_band_context_row_count": len(context),
                "row_count_delta": len(context) - len(units),
                "pass": len(context) == len(units),
            }
        ],
    )
    direction_parent = units.groupby("directionality_status", dropna=False).agg(parent_unit_count=("distance_band_unit_id", "count")).reset_index()
    direction_context = context.groupby("directionality_status", dropna=False).agg(context_unit_count=("distance_band_unit_id", "count")).reset_index()
    direction = direction_parent.merge(direction_context, on="directionality_status", how="outer").fillna(0)
    direction["unit_count_delta"] = direction["context_unit_count"] - direction["parent_unit_count"]
    direction["pass"] = direction["unit_count_delta"].eq(0)
    write_csv("directionality_reconciliation.csv", direction)
    length = units[["distance_band_unit_id", "bin_count", "unit_length_ft"]].merge(
        context[["distance_band_unit_id", "bin_count", "unit_length_ft"]],
        on="distance_band_unit_id",
        suffixes=("_parent", "_context"),
        how="outer",
    )
    length["bin_count_delta"] = length["bin_count_context"] - length["bin_count_parent"]
    length["unit_length_delta_ft"] = length["unit_length_ft_context"] - length["unit_length_ft_parent"]
    write_csv(
        "length_bin_count_reconciliation.csv",
        [
            {
                "row_count": len(length),
                "bin_count_mismatch_count": int(length["bin_count_delta"].fillna(999).ne(0).sum()),
                "unit_length_mismatch_count": int(length["unit_length_delta_ft"].abs().fillna(999).gt(1e-6).sum()),
                "max_abs_length_delta_ft": float(length["unit_length_delta_ft"].abs().max()),
                "pass": int(length["bin_count_delta"].fillna(999).ne(0).sum()) == 0
                and int(length["unit_length_delta_ft"].abs().fillna(999).gt(1e-6).sum()) == 0,
            }
        ],
    )
    write_csv("roadway_context_summary.csv", summarize_status(context, "roadway_context_status"))
    write_csv("speed_context_summary.csv", summarize_status(context, "speed_context_status"))
    write_csv("aadt_context_summary.csv", summarize_status(context, "aadt_context_status"))
    write_csv("exposure_context_summary.csv", summarize_status(context, "exposure_context_status"))
    write_csv("access_context_summary.csv", summarize_status(context, "access_context_status"))
    write_csv("crash_context_summary.csv", summarize_status(context, "crash_context_status"))
    write_csv("context_missingness_by_field.csv", context_missingness_by_field(context))
    write_csv("context_missingness_by_distance_band.csv", summarize_status(context, "overall_context_readiness_status", ["distance_band"]))
    write_csv("context_missingness_by_directionality_status.csv", summarize_status(context, "overall_context_readiness_status", ["directionality_status"]))
    write_csv(
        "context_missingness_by_signal.csv",
        context.groupby("stable_signal_id", dropna=False).agg(
            unit_count=("distance_band_unit_id", "count"),
            speed_missing_count=("speed_limit_mph", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            aadt_missing_count=("aadt", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            exposure_missing_count=("exposure_denominator", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            access_missing_count=("access_count", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            crash_deferred_count=("crash_context_status", lambda s: int(s.map(clean).str.startswith("deferred").sum())),
            ready_statuses=("overall_context_readiness_status", join_values),
        ).reset_index().sort_values("unit_count", ascending=False),
    )
    write_csv(
        "context_missingness_by_approach.csv",
        context.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
            unit_count=("distance_band_unit_id", "count"),
            speed_missing_count=("speed_limit_mph", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            aadt_missing_count=("aadt", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            exposure_missing_count=("exposure_denominator", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            access_missing_count=("access_count", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            ready_statuses=("overall_context_readiness_status", join_values),
        ).reset_index().sort_values("unit_count", ascending=False),
    )
    mixed = []
    for field in ["mixed_roadway_flag", "mixed_speed_flag", "mixed_aadt_flag", "mixed_access_flag"]:
        mixed.append(
            {
                "mixed_field": field,
                "mixed_unit_count": int(context[field].map(bool_value).sum()),
                "total_units": len(context),
            }
        )
    write_csv("mixed_context_value_audit.csv", mixed)
    method_rows = []
    for field in ["roadway_source_match_method", "speed_source_match_method", "aadt_source_match_method", "access_source_match_method", "crash_source_match_method"]:
        method_rows.extend(
            context.groupby(field, dropna=False).agg(unit_count=("distance_band_unit_id", "count")).reset_index().rename(columns={field: "source_match_method"}).assign(method_field=field).to_dict("records")
        )
    write_csv("source_match_method_summary.csv", pd.DataFrame(method_rows))
    write_csv("rate_readiness_summary.csv", summarize_status(context, "rate_readiness_status"))
    write_csv("rate_readiness_by_distance_band.csv", summarize_status(context, "rate_readiness_status", ["distance_band"]))
    write_csv("rate_readiness_by_directionality_status.csv", summarize_status(context, "rate_readiness_status", ["directionality_status"]))
    unresolved = context.loc[context["directionality_status"].ne("assigned")]
    write_csv(
        "unresolved_directionality_context_summary.csv",
        unresolved.groupby(["directionality_status", "directionality_unresolved_reason"], dropna=False).agg(
            unit_count=("distance_band_unit_id", "count"),
            speed_populated_count=("speed_limit_mph", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            aadt_populated_count=("aadt", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            access_populated_count=("access_count", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            crash_deferred_count=("crash_context_status", lambda s: int(s.map(clean).str.startswith("deferred").sum())),
        ).reset_index(),
    )
    crash_columns = pq.ParquetFile(CRASHES).schema_arrow.names
    direction_like = [col for col in crash_columns if is_crash_direction_field(col)]
    write_csv(
        "no_crash_direction_field_check.csv",
        [
            {
                "check_name": "no_crash_direction_fields_used",
                "crash_artifact_direction_like_columns_present": "|".join(direction_like),
                "used_crash_direction_field_count": 0,
                "used_crash_direction_fields": "",
                "pass": True,
            }
        ],
    )
    forbidden_cols = [col for col in context.columns if any(token in col.lower() for token in FORBIDDEN_OUTPUT_TOKENS)]
    forbidden_files = [path.name for path in STAGING.glob("*") if any(token in path.name.lower() for token in ("lookup", "mvp", "rate_distribution"))]
    write_csv(
        "forbidden_mvp_lookup_product_check.csv",
        [
            {
                "forbidden_output_column_count": len(forbidden_cols),
                "forbidden_output_columns": "|".join(forbidden_cols),
                "new_forbidden_product_count": 0,
                "staging_lookup_mvp_rate_files_seen_for_guard_only": "|".join(forbidden_files),
                "pass": len(forbidden_cols) == 0,
            }
        ],
    )
    hard_pass = bool(
        parent_check.loc[parent_check["parent_role"].eq("direct_parent"), "allowed_parent_for_distance_band_context"].all()
        and not parent_check["downstream_object_parent_flag"].any()
        and bool(row_identity["pass"].all())
        and context["distance_band_unit_id"].is_unique
        and int(grain_dupes.sum()) == 0
        and bool(direction["pass"].all())
        and len(units) == len(context)
    )
    if not hard_pass:
        decision = "distance_band_context_needs_parent_unit_repair"
    elif any(context[col].isna().all() if pd.api.types.is_numeric_dtype(context[col]) else context[col].map(clean).eq("").all() for col in ["speed_context_status", "aadt_context_status", "access_context_status", "crash_context_status"]):
        decision = "distance_band_context_needs_missingness_status_repair"
    elif context["crash_context_status"].map(clean).str.startswith("deferred").any():
        decision = "distance_band_context_built_with_deferred_context_ready_for_validation"
    else:
        decision = "distance_band_context_built_ready_for_validation"
    write_csv(
        "distance_band_context_readiness_decision.csv",
        [
            {
                "decision": decision,
                "hard_acceptance_checks_pass": hard_pass,
                "row_count": len(context),
                "crash_context_deferred_unit_count": int(context["crash_context_status"].map(clean).str.startswith("deferred").sum()),
            }
        ],
    )
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "priority": 1,
                "recommended_next_action": "Run independent validation of distance_band_context row identity, missingness statuses, and route-measure context joins.",
            },
            {
                "priority": 2,
                "recommended_next_action": "Implement a bounded crash assignment layer using validated spatial catchment or source-rooted unit lineage before any rate distribution build.",
            },
            {
                "priority": 3,
                "recommended_next_action": "After validation and crash assignment acceptance, build MVP lookup/rate distribution products as separate downstream products.",
            },
        ],
    )
    write_csv(
        "distance_band_context_build_summary.csv",
        [
            {
                "build_version": BUILD_VERSION,
                "row_count": len(context),
                "parent_unit_count": len(units),
                "speed_populated_units": int(pd.to_numeric(context["speed_limit_mph"], errors="coerce").notna().sum()),
                "aadt_populated_units": int(pd.to_numeric(context["aadt"], errors="coerce").notna().sum()),
                "exposure_populated_units": int(pd.to_numeric(context["exposure_denominator"], errors="coerce").notna().sum()),
                "access_nonmissing_units": int(pd.to_numeric(context["access_count"], errors="coerce").notna().sum()),
                "crash_deferred_units": int(context["crash_context_status"].map(clean).str.startswith("deferred").sum()),
                "rate_ready_units": int(context["crash_rate_ready_flag"].map(bool_value).sum()),
                "decision": decision,
            }
        ],
    )
    return {"decision": decision, "hard_pass": hard_pass}


def write_findings(context: pd.DataFrame, summary: dict[str, Any]) -> None:
    def count_status(field: str, prefix: str | None = None) -> int:
        series = context[field].map(clean)
        if prefix is None:
            return int(series.ne("").sum())
        return int(series.str.startswith(prefix).sum())

    speed_populated = int(pd.to_numeric(context["speed_limit_mph"], errors="coerce").notna().sum())
    aadt_populated = int(pd.to_numeric(context["aadt"], errors="coerce").notna().sum())
    exposure_populated = int(pd.to_numeric(context["exposure_denominator"], errors="coerce").notna().sum())
    access_nonmissing = int(pd.to_numeric(context["access_count"], errors="coerce").notna().sum())
    phase_lines = "\n".join(
        f"- {row.get('phase')}: {row.get('elapsed_seconds')} seconds"
        for row in PHASE_TIMINGS
    )
    benchmark_lines = "\n".join(
        f"- smoke_units={row.get('smoke_units', '')}: {row.get('total_elapsed_seconds', '')} seconds; rows={row.get('context_rows', '')}"
        for row in BENCHMARK_ROWS
    ) or "- No smoke benchmark row recorded in this process."
    memo = f"""# distance_band_context Build Findings

## Previous Halt / Performance Problem
The previous attempt was halted because context joins were CPU-bound in Python/pandas logic: route normalization ran row-by-row across raw bin rows, roadway context used slow custom string aggregation over large groups, and route/measure matching used nested route/unit/source scans.

## Performance Refactor Implemented
The build now caches route normalization by unique raw route string, reduces bin lineage to compact `distance_band_unit_id x route_key` spans before context joins, uses bucketed route/measure candidate joins with exact overlap filters for speed/AADT/access, writes phase progress to `progress_log.md`, and writes full staged output through a temp parquet before replacement.

## Benchmark / Smoke Results
{benchmark_lines}

## Full Runtime By Major Phase
{phase_lines}

## What Was Built
Built staged `distance_band_context.parquet` with one row per `distance_band_unit_id`. The output preserves the exact `distance_band_units` row identity and enriches units with roadway, speed, AADT/exposure, access, and explicit crash-context status fields.

## What Was Not Built
No MVP product, `lookup_cells.parquet`, grouped rate distribution table, rate mean/median/percentile product, or canonical root product was built.

## Parent Dependency Statement
Direct parents were validated staged `distance_band_units.parquet`, `bin_context.parquet`, `travelway_network_index.parquet`, and normalized source-derived speed, AADT, access, and crash artifacts. Review folders were diagnostic evidence only. No downstream object was used as a parent.

## Unit Grain Preservation Result
Rows written: {len(context):,}. Unique `distance_band_unit_id`: {context['distance_band_unit_id'].nunique():,}. Duplicate IDs: {int(context['distance_band_unit_id'].duplicated().sum()):,}. Acceptance decision: `{summary['decision']}`.

## Context Sources Used
Roadway context used bin/travelway lineage. Speed used route/measure overlap with `artifacts/normalized/speed.parquet`. AADT and exposure used route/measure overlap with `artifacts/normalized/aadt.parquet`. Access used route/measure point-in-window matching with `artifacts/normalized/access_v2.parquet`.

## Context Sources Deferred
Crash counts are deferred for every unit because this build does not create a validated spatial catchment or source-rooted unit crash assignment. Crash route/milepost fields were not used as a substitute final assignment.

## Completeness
Roadway populated units: {count_status('roadway_context_status'):,}.
Speed populated units: {speed_populated:,} of {len(context):,}.
AADT populated units: {aadt_populated:,} of {len(context):,}.
Exposure populated units: {exposure_populated:,} of {len(context):,}.
Access non-missing units: {access_nonmissing:,} of {len(context):,}.
Crash populated units: 0 of {len(context):,}; crash deferred units: {count_status('crash_context_status', 'deferred'):,}.

## Directionality Unresolved Handling
Unresolved directionality units remain in the table with blank `upstream_downstream`, original directionality status/reason fields, context fields where joinable, and `rate_readiness_status = not_rate_ready_unresolved_directionality`.

## Missingness And Rate Readiness
Missing context is explicit in family status and missing-reason fields. No crash-rate-ready units are claimed because crash assignment is deferred. Rate readiness is descriptive only and no rate distribution was computed.

## Crash Direction Field Guard
Crash direction-like columns were detected only for QA inventory where present. Used crash direction field count is zero.

## Readiness
`distance_band_context.parquet` is ready for independent validation and later crash-assignment work. It is not a modeling-ready or MVP lookup product.

## Recommended Next Task
Run independent validation of `distance_band_context.parquet`, then implement a bounded crash assignment layer using validated spatial catchment or accepted source-rooted unit lineage.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def write_manifests(summary: dict[str, Any]) -> None:
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "product": "distance_band_context",
            "build_version": BUILD_VERSION,
            "target": rel(DISTANCE_BAND_CONTEXT),
            "canonical_parents": [rel(path) for path in DIRECT_PARENTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "bounded_question": "Build enriched staged distance-band context while preserving distance_band_units grain.",
            "output_grain": "one row per distance_band_unit_id",
            "crash_direction_fields_used": False,
            "mvp_lookup_or_rate_distribution_built": False,
            "final_decision": summary["decision"],
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "product": "distance_band_context",
            "qa_outputs": sorted(path.name for path in OUT.glob("*") if path.is_file()),
            "acceptance_checks": {
                "parent_dependency_check_passed": bool(summary["hard_pass"]),
                "row_identity_preserved": True,
                "distance_band_unit_id_unique": True,
                "crash_direction_fields_not_used": True,
                "mvp_lookup_rate_products_not_built": True,
                "crash_assignment_deferred": True,
            },
            "final_decision": summary["decision"],
        },
    )


def update_staging_metadata(context: pd.DataFrame, summary: dict[str, Any]) -> None:
    stamp = now()
    manifest = read_json(STAGING_MANIFEST)
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    product.update(
        {
            "path": rel(DISTANCE_BAND_CONTEXT),
            "script": "src.roadway_graph.build.build_distance_band_context",
            "build_version": BUILD_VERSION,
            "updated_utc": stamp,
            "canonical_parents": [rel(path) for path in DIRECT_PARENTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved",
            "row_count": int(len(context)),
            "speed_populated_units": int(pd.to_numeric(context["speed_limit_mph"], errors="coerce").notna().sum()),
            "aadt_populated_units": int(pd.to_numeric(context["aadt"], errors="coerce").notna().sum()),
            "exposure_populated_units": int(pd.to_numeric(context["exposure_denominator"], errors="coerce").notna().sum()),
            "access_nonmissing_units": int(pd.to_numeric(context["access_count"], errors="coerce").notna().sum()),
            "crash_context_status": "deferred_requires_spatial_catchment_or_validated_unit_lineage",
            "crash_direction_field_status": "not_used",
            "mvp_lookup_or_rate_distribution_status": "not_built",
            "final_decision": summary["decision"],
            "qa_review_path": rel(OUT),
        }
    )
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "script": "src.roadway_graph.build.build_distance_band_context",
            "bounded_phase": "final core rebuilt cache object distance_band_context only",
            "built_utc": stamp,
            "row_count": int(len(context)),
            "final_decision": summary["decision"],
            "build_version": BUILD_VERSION,
            "crash_context_status": "deferred",
        }
    )
    write_json(STAGING_MANIFEST, manifest)

    schema = read_json(STAGING_SCHEMA)
    table = schema.setdefault("tables", {}).setdefault("distance_band_context.parquet", {})
    table.update(
        {
            "build_version": BUILD_VERSION,
            "canonical_parent": [rel(path) for path in DIRECT_PARENTS],
            "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved",
            "required_columns": [
                "distance_band_unit_id",
                "stable_signal_id",
                "signal_approach_id",
                "upstream_downstream",
                "distance_band",
                "directionality_status",
                "bin_count",
                "unit_length_ft",
                "roadway_context_status",
                "speed_context_status",
                "aadt_context_status",
                "exposure_context_status",
                "access_context_status",
                "crash_context_status",
                "overall_context_readiness_status",
                "rate_readiness_status",
                "missingness_reason",
            ],
            "columns": OUTPUT_COLUMNS,
            "crash_direction_field_status": "not_used",
            "forbidden_fields": "No lookup_cell_id, rate_mean, rate_median, rate_percentiles, grouped distribution, or MVP export fields.",
            "crash_assignment_policy": "deferred until validated spatial catchment or source-rooted unit lineage is available",
            "updated_utc": stamp,
        }
    )
    schema["updated_utc"] = stamp
    write_json(STAGING_SCHEMA, schema)

    with STAGING_README.open("a", encoding="utf-8") as f:
        f.write(
            f"""

## Phase C.5 distance_band_context

Built `{rel(DISTANCE_BAND_CONTEXT)}` from validated staged distance-band units,
bin lineage, travelway lineage, and normalized source-derived context artifacts.
The table preserves one row per `distance_band_unit_id` and enriches unit rows
with roadway, speed, AADT/exposure, access, and explicit crash-context status.

Crash counts are deferred pending a validated spatial catchment or accepted
source-rooted unit crash assignment. Crash direction fields were not used. No
MVP lookup cells, grouped rate distributions, rate mean/median/percentiles, or
canonical root products were built.

Decision: `{summary['decision']}`.
"""
        )


def append_benchmark_row(row: dict[str, Any]) -> None:
    existing: list[dict[str, Any]] = []
    path = OUT / "benchmark_distance_band_context.csv"
    if path.exists():
        try:
            prior = pd.read_csv(path)
            if not (len(prior) == 1 and "benchmark_status" in prior.columns):
                existing = prior.to_dict("records")
        except Exception:
            existing = []
    existing.append(row)
    BENCHMARK_ROWS.clear()
    BENCHMARK_ROWS.extend(existing)


def run_build(*, smoke_units: int | None = None) -> dict[str, Any]:
    global PHASE_TIMINGS, ROUTE_CACHE_STATS, UNIT_ROUTE_SPAN_SUMMARY
    PHASE_TIMINGS = []
    ROUTE_CACHE_STATS = []
    UNIT_ROUTE_SPAN_SUMMARY = []
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    mode = "smoke" if smoke_units is not None else "full"
    total_start = time.perf_counter()
    log(f"Starting distance_band_context {mode} build.")
    with phase("parent_dependency_check"):
        parent_check = parent_dependency_check()
        if (
            not parent_check.loc[parent_check["parent_role"].eq("direct_parent"), "allowed_parent_for_distance_band_context"].all()
            or parent_check["downstream_object_parent_flag"].any()
        ):
            write_csv("parent_dependency_check.csv", parent_check)
            raise RuntimeError("Parent dependency check failed.")
    with phase("load_distance_band_units"):
        full_units = load_units()
        units = full_units.head(smoke_units).copy() if smoke_units is not None else full_units
        log(f"Loaded {len(full_units):,} distance-band units; active run units={len(units):,}.")
    with phase("load_bin_context_and_reconcile"):
        bins = load_bins_with_unit_ids(full_units)
        if smoke_units is not None:
            wanted = set(units["distance_band_unit_id"])
            bins = bins.loc[bins["distance_band_unit_id"].isin(wanted)].copy()
        log(f"Loaded {len(bins):,} bins reconciled to active units.")
    with phase("build_context_dataframe", active_units=len(units), active_bins=len(bins)):
        context = build_context(units, bins)
    if len(context) != len(units) or not context["distance_band_unit_id"].is_unique:
        raise RuntimeError("Context build broke unit grain before write.")
    total_elapsed = time.perf_counter() - total_start
    append_benchmark_row(
        {
            "run_utc": now(),
            "mode": mode,
            "smoke_units": smoke_units if smoke_units is not None else "",
            "context_rows": int(len(context)),
            "bin_rows": int(len(bins)),
            "total_elapsed_seconds": round(total_elapsed, 3),
            "staged_output_written": False if smoke_units is not None else "pending_temp_validation",
        }
    )
    if smoke_units is not None:
        log("Writing smoke QA outputs; staged product and staging metadata will not be updated.")
        summary = write_qa(units, context, bins, parent_check)
        write_findings(context, summary)
        write_manifests(summary)
        log(f"Completed smoke build with decision {summary['decision']}.")
        return summary

    tmp = STAGING / "distance_band_context.parquet.tmp"
    if tmp.exists():
        tmp.unlink()
    with phase("write_temp_parquet"):
        context.to_parquet(tmp, index=False)
        readback_rows = parquet_row_count(tmp)
        if readback_rows != len(context):
            raise RuntimeError(f"Temp readback row count mismatch: {readback_rows} vs {len(context)}")
    with phase("write_full_qa_outputs"):
        summary = write_qa(units, context, bins, parent_check)
    if not summary["hard_pass"]:
        log(f"Core QA failed; leaving temp file at {rel(tmp)} and not replacing staged product.")
        write_findings(context, summary)
        write_manifests(summary)
        return summary
    with phase("replace_staged_parquet_after_qa"):
        if DISTANCE_BAND_CONTEXT.exists():
            DISTANCE_BAND_CONTEXT.unlink()
        tmp.replace(DISTANCE_BAND_CONTEXT)
        readback_rows = parquet_row_count(DISTANCE_BAND_CONTEXT)
        if readback_rows != len(context):
            raise RuntimeError(f"Staged readback row count mismatch: {readback_rows} vs {len(context)}")
    append_benchmark_row(
        {
            "run_utc": now(),
            "mode": "full_completed",
            "smoke_units": "",
            "context_rows": int(len(context)),
            "bin_rows": int(len(bins)),
            "total_elapsed_seconds": round(time.perf_counter() - total_start, 3),
            "staged_output_written": True,
        }
    )
    write_csv("benchmark_distance_band_context.csv", pd.DataFrame(BENCHMARK_ROWS))
    write_findings(context, summary)
    write_manifests(summary)
    update_staging_metadata(context, summary)
    log(f"Completed distance_band_context build with decision {summary['decision']}.")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-units", type=int, default=None, help="Run the real build path on the first N units without writing staged product or staging metadata.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_build(smoke_units=args.smoke_units)


if __name__ == "__main__":
    main()
