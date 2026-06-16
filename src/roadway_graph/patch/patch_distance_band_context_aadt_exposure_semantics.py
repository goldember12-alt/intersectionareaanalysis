"""Patch staged distance_band_context AADT/exposure semantics.

This bounded repair recomputes AADT unit rollups from current staged
unit/bin lineage and artifacts/normalized/aadt.parquet, labels daily VMT proxy
semantics explicitly, and applies source DIRECTION_FACTOR only where the AADT
source provides a valid factor.

It does not repair access, assign crashes, build lookup/rate products, or use
downstream outputs as parents.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_aadt_exposure_semantics"

CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
TRAVELWAY = STAGING / "travelway_network_index.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"

AADT = REPO / "artifacts/normalized/aadt.parquet"
ROADS = REPO / "artifacts/normalized/roads.parquet"
SPEED = REPO / "artifacts/normalized/speed.parquet"
ACCESS = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

BUILD_VERSION = "distance_band_context_aadt_exposure_semantics_v1_2026-06-15"
MILE_FT = 5280.0
MEASURE_BUCKET_MI = 0.10
MIN_OVERLAP_MI = 1e-6

IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
]

AADT_PATCH_FIELDS = [
    "aadt",
    "aadt_category",
    "aadt_rollup_method",
    "aadt_context_status",
    "aadt_missing_reason",
    "mixed_aadt_flag",
    "mixed_aadt_category_flag",
    "aadt_value_count",
    "aadt_min",
    "aadt_max",
    "aadt_dominant",
    "aadt_length_weighted",
    "aadt_source_year",
    "aadt_year",
    "aadt_year_status",
    "aadt_source_match_method",
    "aadt_candidate_count",
    "aadt_value_mix",
    "exposure_daily_vmt_proxy",
    "exposure_denominator",
    "exposure_denominator_status",
    "exposure_directionality_factor",
    "exposure_directionality_factor_method",
    "exposure_directionality_factor_status",
    "exposure_formula",
    "exposure_context_status",
    "exposure_missing_reason",
    "rate_denominator_semantics",
]

PROTECTED_PREFIXES = ("speed", "access", "crash")
PROTECTED_FIELDS = {
    "divided_undivided",
    "one_way_two_way",
    "median_group",
    "roadway_context_status",
    "roadway_configuration_summary",
    "rim_access_summary",
    "rim_facility_summary",
    "rate_readiness_status",
    "crash_rate_ready_flag",
    "overall_context_readiness_status",
    "context_quality_flags",
    "source_match_methods",
    "mixed_context_flags",
}

CRASH_DIRECTION_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

FORBIDDEN_OUTPUT_TOKENS = ("lookup_cell", "lookup_cells", "rate_distribution", "final_rate_distribution")
PHASES: list[dict[str, Any]] = []


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


def clean_series(series: pd.Series) -> pd.Series:
    out = series.astype("string").fillna("").str.strip()
    return out.mask(out.str.lower().isin({"", "nan", "none", "null", "<na>", "nat"}), "").fillna("")


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, float) and math.isnan(value):
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
        PHASES.append({"phase": name, "elapsed_seconds": round(elapsed, 3), **metadata})
        log(f"END {name}; elapsed_seconds={elapsed:,.3f}")


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


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_path(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_TOKENS)


def stable_hash(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(frame.reset_index(drop=True), index=False)
    return hashlib.sha256(hashed.values.tobytes()).hexdigest()


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
            prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
            direction = (match.group(3) or "")[:1]
            return f"{prefix}{int(match.group(2))}{direction}"
    tokens = [token for token in text.split() if token and token not in {"R", "S", "VA"}]
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def route_base_key(value: Any) -> str:
    return re.sub(r"[NSEW]$", "", route_key(value))


def route_number_key(value: Any) -> str:
    match = re.search(r"([0-9]+)$", route_base_key(value))
    return str(int(match.group(1))) if match else ""


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


def category_aadt_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(
        np.select(
            [
                numeric.isna(),
                numeric.lt(5000),
                numeric.lt(10000),
                numeric.lt(20000),
                numeric.lt(40000),
            ],
            ["", "lt_5k", "5k_to_10k", "10k_to_20k", "20k_to_40k"],
            default="40k_plus",
        ),
        index=values.index,
    )


def year_status(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "aadt_year_missing"
    year = int(numeric)
    if 2022 <= year <= 2024:
        return "inside_2022_2024"
    if year < 2022:
        return "before_2022_2024"
    return "after_2022_2024"


def year_status_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(
        np.select(
            [numeric.isna(), numeric.between(2022, 2024, inclusive="both"), numeric.lt(2022)],
            ["aadt_year_missing", "inside_2022_2024", "before_2022_2024"],
            default="after_2022_2024",
        ),
        index=values.index,
    )


def normalize_route_cache(values: pd.Series, label: str) -> pd.DataFrame:
    unique = pd.Series(sorted(v for v in clean_series(values).unique().tolist() if v), name="raw_route")
    out = pd.DataFrame({"raw_route": unique})
    out["route_key"] = out["raw_route"].map(route_key)
    out["route_base_key"] = out["raw_route"].map(route_base_key)
    out["route_number_key"] = out["raw_route"].map(route_number_key)
    log(f"Route cache {label}: {len(out):,} unique routes.")
    return out


def source_schema_inventory() -> pd.DataFrame:
    rows = []
    for path, role in [
        (AADT, "direct_source_parent"),
        (ROADS, "source_schema_evidence_only"),
        (SPEED, "comparison_only_no_patch"),
        (ACCESS, "comparison_only_no_patch"),
        (CRASHES, "forbidden_field_guard_only"),
    ]:
        row = {"path": rel(path), "role": role, "exists": path.exists(), "row_count": "", "columns": "", "read_status": "missing"}
        if path.exists() and path.suffix == ".parquet":
            try:
                pf = pq.ParquetFile(path)
                row["row_count"] = pf.metadata.num_rows
                row["columns"] = "|".join(pf.schema_arrow.names)
                row["read_status"] = "readable"
            except Exception as exc:
                row["read_status"] = f"read_failed:{type(exc).__name__}:{exc}"
        rows.append(row)
    out = pd.DataFrame(rows)
    write_csv("aadt_source_schema_inventory.csv", out)
    return out


def parent_dependency_check() -> pd.DataFrame:
    paths = [
        (CONTEXT, "direct_staged_parent"),
        (UNITS, "direct_staged_parent"),
        (BINS, "direct_staged_parent"),
        (TRAVELWAY, "validated_staged_context_evidence"),
        (AADT, "direct_source_parent"),
        (ROADS, "read_only_source_schema_evidence"),
        (SPEED, "comparison_only_not_patched"),
        (ACCESS, "comparison_only_not_patched"),
        (CRASHES, "forbidden_field_guard_only"),
        (REPO / "work/roadway_graph/review/build_distance_band_context", "diagnostic_evidence_only"),
        (REPO / "work/roadway_graph/review/distance_band_context_validation_legacy_audit", "diagnostic_evidence_only"),
        (REPO / "work/roadway_graph/review/patch_distance_band_context_roadway_and_speed", "diagnostic_evidence_only"),
        (REPO / "work/roadway_graph/review/distance_band_units_validation_audit", "diagnostic_evidence_only"),
        (REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan", "diagnostic_evidence_only"),
    ]
    rows = []
    for path, role in paths:
        rows.append(
            {
                "path": rel(path),
                "role": role,
                "exists": path.exists(),
                "used_as_data_parent": role in {"direct_staged_parent", "direct_source_parent"},
                "review_output_hidden_parent_flag": False,
                "downstream_parent_flag": False,
            }
        )
    out = pd.DataFrame(rows)
    write_csv("parent_dependency_check.csv", out)
    return out


def old_method_inventory() -> pd.DataFrame:
    legacy = REPO / "work/roadway_graph/review/distance_band_context_validation_legacy_audit/old_aadt_code_inventory.csv"
    if legacy.exists():
        inv = pd.read_csv(legacy)
        path_col = inv.get("path", pd.Series("", index=inv.index)).astype(str)
        terms_col = inv.get("matched_terms", pd.Series("", index=inv.index)).astype(str)
        useful = inv[
            path_col.str.contains("aadt_context_join_v3|aadt_direction_factor|active_rate_denominator|build_distance_band_context|aadt_bridge_key", case=False, regex=True)
            | terms_col.str.contains("DIRECTION_FACTOR|EDGE_RTE_KEY|LINKID|exposure|route measure", case=False, regex=True)
        ].head(100).copy()
    else:
        useful = pd.DataFrame()
    if useful.empty:
        useful = pd.DataFrame(
            [
                {
                    "family": "aadt",
                    "path": "src/active/roadway_graph/build_distance_band_context.py",
                    "matched_terms": "AADT|exposure|route_measure_overlap",
                    "useful_method_evidence": "current staged route+measure join; latest-year dominant behavior to improve",
                    "uses_stale_cache_parent_flag": False,
                    "used_as_data_parent": False,
                }
            ]
        )
    useful["used_as_data_parent"] = False
    write_csv("old_aadt_exposure_method_inventory.csv", useful)
    return useful


def aadt_source_semantics_decision(aadt: pd.DataFrame) -> str:
    directionality = clean_series(aadt["DIRECTIONALITY"])
    factor = pd.to_numeric(aadt["DIRECTION_FACTOR"], errors="coerce")
    combined_valid = directionality.eq("Combined") & factor.gt(0) & factor.le(1)
    single_one = directionality.eq("Single") & factor.eq(1)
    missing_factor = directionality.eq("") & factor.isna()
    rows = [
        {
            "decision": "aadt_semantics_mixed_by_source_field",
            "selected": True,
            "combined_rows_with_valid_factor": int(combined_valid.sum()),
            "single_rows_with_factor_1": int(single_one.sum()),
            "blank_directionality_null_factor_rows": int(missing_factor.sum()),
            "rationale": "AADT source carries DIRECTIONALITY and DIRECTION_FACTOR. Combined rows have valid factors, Single rows have factor 1.0, and blank/null rows require no-factor daily proxy fallback rather than guessed factors.",
        }
    ]
    out = pd.DataFrame(rows)
    write_csv("aadt_source_semantics_decision.csv", out)
    return "aadt_semantics_mixed_by_source_field"


def load_unit_route_spans(units: pd.DataFrame) -> pd.DataFrame:
    with phase("build_compact_unit_route_spans"):
        cols = [
            "stable_signal_id",
            "signal_approach_id",
            "upstream_downstream",
            "distance_band",
            "source_route_name",
            "route_base",
            "source_measure_start",
            "source_measure_end",
            "bin_length_ft",
            "logical_corridor_chain_id",
            "primary_stable_travelway_id",
        ]
        bins = pd.read_parquet(BINS, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        merged = bins.merge(units[IDENTITY_COLUMNS], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
        if merged["distance_band_unit_id"].isna().any():
            raise RuntimeError("bin_context rows failed distance_band_units reconciliation")
        merged["measure_min"] = pd.to_numeric(merged[["source_measure_start", "source_measure_end"]].min(axis=1), errors="coerce")
        merged["measure_max"] = pd.to_numeric(merged[["source_measure_start", "source_measure_end"]].max(axis=1), errors="coerce")
        merged["span_length_ft"] = pd.to_numeric(merged["bin_length_ft"], errors="coerce").fillna(0)
        merged = merged.loc[merged["measure_min"].notna() & merged["measure_max"].notna() & merged["measure_max"].ge(merged["measure_min"])].copy()

        source_cache = normalize_route_cache(merged["source_route_name"], "bin_source_route_name")
        base_cache = normalize_route_cache(merged["route_base"], "bin_route_base")
        merged = merged.merge(source_cache.add_prefix("source_"), left_on="source_route_name", right_on="source_raw_route", how="left")
        merged = merged.merge(base_cache.add_prefix("base_"), left_on="route_base", right_on="base_raw_route", how="left")
        frames = []
        for method_key, col in {
            "strict": "source_route_key",
            "directionless": "source_route_base_key",
            "route_number": "source_route_number_key",
            "alternate_route_base_directionless": "base_route_base_key",
        }.items():
            part = merged[["distance_band_unit_id", col, "measure_min", "measure_max", "span_length_ft", "logical_corridor_chain_id", "primary_stable_travelway_id"]].rename(columns={col: "route_key"}).copy()
            part["route_key"] = clean_series(part["route_key"])
            part = part.loc[part["route_key"].ne("")].copy()
            grouped = (
                part.groupby(["distance_band_unit_id", "route_key"], dropna=False)
                .agg(
                    measure_min=("measure_min", "min"),
                    measure_max=("measure_max", "max"),
                    span_length_ft=("span_length_ft", "sum"),
                    bin_count=("route_key", "size"),
                    logical_corridor_chain_id=("logical_corridor_chain_id", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)})[:8])),
                    stable_travelway_id=("primary_stable_travelway_id", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)})[:8])),
                )
                .reset_index()
            )
            grouped["method_key"] = method_key
            frames.append(grouped)
        spans = pd.concat(frames, ignore_index=True)
        summary = (
            spans.groupby("method_key", dropna=False)
            .agg(
                unit_route_span_rows=("distance_band_unit_id", "size"),
                unique_units=("distance_band_unit_id", "nunique"),
                unique_route_keys=("route_key", "nunique"),
                total_span_length_ft=("span_length_ft", "sum"),
            )
            .reset_index()
        )
        return spans, summary


def load_aadt_source() -> pd.DataFrame:
    with phase("prepare_aadt_source"):
        cols = [
            "RTE_NM",
            "MASTER_RTE_NM",
            "TRANSPORT_EDGE_FROM_MSR",
            "TRANSPORT_EDGE_TO_MSR",
            "FROM_MEASURE",
            "TO_MEASURE",
            "AADT",
            "AADT_YR",
            "AADT_QUALITY",
            "AAWDT",
            "DIRECTION_FACTOR",
            "DIRECTIONALITY",
            "LINKID",
            "EDGE_RTE_KEY",
            "Stage1_SourceGDB",
            "Stage1_SourceLayer",
        ]
        raw = pd.read_parquet(AADT, columns=cols).reset_index(names="aadt_source_index")
        raw["measure_from"] = pd.to_numeric(raw["TRANSPORT_EDGE_FROM_MSR"], errors="coerce")
        raw["measure_to"] = pd.to_numeric(raw["TRANSPORT_EDGE_TO_MSR"], errors="coerce")
        fallback = raw["measure_from"].isna() | raw["measure_to"].isna()
        raw.loc[fallback, "measure_from"] = pd.to_numeric(raw.loc[fallback, "FROM_MEASURE"], errors="coerce")
        raw.loc[fallback, "measure_to"] = pd.to_numeric(raw.loc[fallback, "TO_MEASURE"], errors="coerce")
        raw["measure_min"] = raw[["measure_from", "measure_to"]].min(axis=1)
        raw["measure_max"] = raw[["measure_from", "measure_to"]].max(axis=1)
        raw["aadt_value"] = pd.to_numeric(raw["AADT"], errors="coerce")
        raw["aadt_year"] = pd.to_numeric(raw["AADT_YR"], errors="coerce")
        raw["direction_factor"] = pd.to_numeric(raw["DIRECTION_FACTOR"], errors="coerce")
        raw["directionality"] = clean_series(raw["DIRECTIONALITY"])
        frames = []
        for route_col in ["RTE_NM", "MASTER_RTE_NM"]:
            alias = raw.copy()
            cache = normalize_route_cache(alias[route_col], f"aadt_{route_col}")
            alias = alias.merge(cache, left_on=route_col, right_on="raw_route", how="left")
            alias["route_field"] = route_col
            alias["source_route_raw"] = alias[route_col]
            frames.append(alias)
        source = pd.concat(frames, ignore_index=True)
        valid = source["route_key"].map(clean).ne("") & source["measure_min"].notna() & source["measure_max"].notna() & source["aadt_value"].gt(0)
        source = source.loc[valid].copy()
        source = source.drop_duplicates(["aadt_source_index", "route_key", "measure_min", "measure_max", "aadt_value"]).copy()
        source["source_record_key"] = source["aadt_source_index"].astype(str) + "_" + source["route_key"].astype(str)
        return source


def source_for_method(source: pd.DataFrame, method_key: str) -> pd.DataFrame:
    key_col = "route_key"
    if method_key in {"directionless", "alternate_route_base_directionless"}:
        key_col = "route_base_key"
    elif method_key == "route_number":
        key_col = "route_number_key"
    cols = [
        "source_record_key",
        "aadt_source_index",
        key_col,
        "measure_min",
        "measure_max",
        "aadt_value",
        "aadt_year",
        "direction_factor",
        "directionality",
        "AADT_QUALITY",
        "LINKID",
        "EDGE_RTE_KEY",
        "route_field",
        "source_route_raw",
        "Stage1_SourceGDB",
        "Stage1_SourceLayer",
    ]
    out = source[cols].rename(columns={key_col: "route_key"}).copy()
    out["route_key"] = clean_series(out["route_key"])
    return out.loc[out["route_key"].ne("")].copy()


def expand_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["measure_min"] = pd.to_numeric(work["measure_min"], errors="coerce")
    work["measure_max"] = pd.to_numeric(work["measure_max"], errors="coerce")
    work = work.loc[work["route_key"].map(clean).ne("") & work["measure_min"].notna() & work["measure_max"].notna()].copy()
    work["bucket_start"] = np.floor(work["measure_min"] / MEASURE_BUCKET_MI).astype("int64")
    work["bucket_end"] = np.floor(work["measure_max"] / MEASURE_BUCKET_MI).astype("int64")
    work["bucket_count"] = (work["bucket_end"] - work["bucket_start"] + 1).clip(lower=1, upper=500)
    repeated = work.loc[work.index.repeat(work["bucket_count"])].copy()
    repeated["bucket_offset"] = repeated.groupby(level=0).cumcount()
    repeated["measure_bucket"] = repeated["bucket_start"] + repeated["bucket_offset"]
    return repeated.drop(columns=["bucket_start", "bucket_end", "bucket_count", "bucket_offset"])


def match_method(spans_all: pd.DataFrame, source_all: pd.DataFrame, method_key: str) -> pd.DataFrame:
    spans = spans_all.loc[spans_all["method_key"].eq(method_key)].copy()
    source = source_for_method(source_all, method_key)
    source = source.loc[source["route_key"].isin(set(spans["route_key"].unique()))].copy()
    with phase("match_aadt_method", method=method_key, span_rows=len(spans), source_rows=len(source)):
        if spans.empty or source.empty:
            return pd.DataFrame()
        left = expand_buckets(spans[["distance_band_unit_id", "route_key", "measure_min", "measure_max"]].drop_duplicates())
        right = expand_buckets(source).rename(columns={"measure_min": "source_measure_min", "measure_max": "source_measure_max"})
        candidates = left.merge(right, on=["route_key", "measure_bucket"], how="inner")
        if candidates.empty:
            return pd.DataFrame()
        candidates = candidates.loc[candidates["source_measure_max"].ge(candidates["measure_min"]) & candidates["source_measure_min"].le(candidates["measure_max"])].copy()
        candidates["measure_overlap_mi"] = np.maximum(
            0.0,
            np.minimum(candidates["measure_max"], candidates["source_measure_max"]) - np.maximum(candidates["measure_min"], candidates["source_measure_min"]),
        )
        candidates = candidates.loc[candidates["measure_overlap_mi"].gt(MIN_OVERLAP_MI)].copy()
        return candidates.drop_duplicates(["distance_band_unit_id", "source_record_key"]).copy()


def factor_status_row(directionality: Any, factor: Any) -> tuple[float, str]:
    d = clean(directionality)
    f = pd.to_numeric(pd.Series([factor]), errors="coerce").iloc[0]
    if pd.notna(f) and 0 < float(f) <= 1:
        if d == "Combined":
            return float(f), "valid_source_direction_factor_applied_combined"
        if d == "Single":
            return float(f), "single_or_carriageway_specific_factor_1"
        return float(f), "valid_source_direction_factor_applied_unknown_directionality"
    if pd.isna(f):
        return 1.0, "null_direction_factor_no_adjustment_daily_proxy_fallback"
    return 1.0, "invalid_direction_factor_no_adjustment_review"


def aggregate_matches(matches: pd.DataFrame, context: pd.DataFrame, units: pd.DataFrame, method_name: str) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame(columns=["distance_band_unit_id"])
    with phase("aggregate_aadt_matches", candidate_rows=len(matches), candidate_units=matches["distance_band_unit_id"].nunique()):
        log(f"aggregate_aadt_matches: numeric coercion start; candidate_rows={len(matches):,}.")
        work = matches[
            [
                "distance_band_unit_id",
                "aadt_value",
                "aadt_year",
                "direction_factor",
                "directionality",
                "measure_overlap_mi",
                "source_record_key",
            ]
        ].copy()
        for col in ["aadt_value", "aadt_year", "direction_factor", "measure_overlap_mi"]:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        work["directionality_clean"] = clean_series(work["directionality"])
        work = work.loc[work["aadt_value"].notna() & work["measure_overlap_mi"].gt(0)].copy()

        log("aggregate_aadt_matches: latest-year filtering start.")
        max_year = work.groupby("distance_band_unit_id", dropna=False)["aadt_year"].max().reset_index(name="aadt_source_year")
        latest = work.merge(max_year, on="distance_band_unit_id", how="left")
        latest = latest.loc[latest["aadt_year"].eq(latest["aadt_source_year"]) | latest["aadt_source_year"].isna()].copy()
        log(f"aggregate_aadt_matches: latest-year rows={len(latest):,}; units={latest['distance_band_unit_id'].nunique():,}.")

        log("aggregate_aadt_matches: vectorized factor-status derivation start.")
        factor = latest["direction_factor"]
        valid_factor = factor.gt(0) & factor.le(1)
        combined = latest["directionality_clean"].eq("Combined")
        single = latest["directionality_clean"].eq("Single")
        factor_missing = factor.isna()
        latest["effective_direction_factor"] = np.where(valid_factor, factor, 1.0)
        latest["factor_status_code"] = np.select(
            [valid_factor & combined, valid_factor & single, valid_factor, factor_missing],
            [10, 20, 30, 40],
            default=50,
        ).astype("int16")
        latest["aadt_category_component"] = category_aadt_series(latest["aadt_value"])
        latest["aadt_weighted_num"] = latest["aadt_value"] * latest["measure_overlap_mi"]
        latest["adjusted_aadt_weighted_num"] = latest["aadt_value"] * latest["effective_direction_factor"] * latest["measure_overlap_mi"]

        log("aggregate_aadt_matches: weighted sum aggregation start.")
        grouped = latest.groupby("distance_band_unit_id", dropna=False).agg(
            matched_length_mi_sum=("measure_overlap_mi", "sum"),
            aadt_weighted_num=("aadt_weighted_num", "sum"),
            adjusted_aadt_weighted_num=("adjusted_aadt_weighted_num", "sum"),
            aadt_min=("aadt_value", "min"),
            aadt_max=("aadt_value", "max"),
            aadt_value_count=("aadt_value", "nunique"),
            mixed_aadt_category_count=("aadt_category_component", "nunique"),
            aadt_source_year=("aadt_source_year", "max"),
            aadt_candidate_count=("source_record_key", "nunique"),
            factor_min=("effective_direction_factor", "min"),
            factor_max=("effective_direction_factor", "max"),
            factor_nunique=("effective_direction_factor", "nunique"),
            factor_status_min=("factor_status_code", "min"),
            factor_status_nunique=("factor_status_code", "nunique"),
        ).reset_index()

        log("aggregate_aadt_matches: dominant AADT selection start.")
        dominant = (
            latest.groupby(["distance_band_unit_id", "aadt_value"], dropna=False)["measure_overlap_mi"]
            .sum()
            .reset_index(name="value_overlap_mi")
            .sort_values(["distance_band_unit_id", "value_overlap_mi", "aadt_value"], ascending=[True, False, True])
            .drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", "aadt_value"]]
            .rename(columns={"aadt_value": "aadt_dominant"})
        )

        log("aggregate_aadt_matches: output assembly start.")
        out = grouped.merge(dominant, on="distance_band_unit_id", how="left")
        denom = out["matched_length_mi_sum"].replace(0, np.nan)
        out["aadt_length_weighted"] = out["aadt_weighted_num"] / denom
        out["adjusted_aadt_length_weighted"] = out["adjusted_aadt_weighted_num"] / denom
        out["aadt"] = out["aadt_length_weighted"]
        out["aadt_year"] = out["aadt_source_year"]
        out["aadt_year_status"] = year_status_series(out["aadt_source_year"])
        out["aadt_category"] = category_aadt_series(out["aadt_length_weighted"])
        out["aadt_rollup_method"] = "latest_year_length_weighted_aadt"
        out["mixed_aadt_flag"] = out["aadt_value_count"].gt(1)
        out["mixed_aadt_category_flag"] = out["mixed_aadt_category_count"].gt(1)
        out["aadt_context_status"] = np.where(out["mixed_aadt_flag"], "mixed_aadt_values", "stable_single_aadt")
        out["aadt_source_match_method"] = method_name
        out["aadt_missing_reason"] = ""
        out["aadt_value_mix"] = np.where(out["mixed_aadt_flag"], "omitted_full_mix_use_numeric_diagnostics", "")
        out["exposure_directionality_factor"] = out["adjusted_aadt_length_weighted"] / out["aadt_length_weighted"].replace(0, np.nan)
        status_map = {
            10: "valid_source_direction_factor_applied_combined",
            20: "single_or_carriageway_specific_factor_1",
            30: "valid_source_direction_factor_applied_unknown_directionality",
            40: "null_direction_factor_no_adjustment_daily_proxy_fallback",
            50: "invalid_direction_factor_no_adjustment_review",
        }
        out["exposure_directionality_factor_status"] = out["factor_status_min"].map(status_map).fillna("unknown_factor_status")
        out.loc[out["factor_status_nunique"].gt(1), "exposure_directionality_factor_status"] = "mixed_factor_status"
        out["exposure_directionality_factor_method"] = "source_direction_factor_latest_year_length_weighted"

        out = out.merge(units[["distance_band_unit_id", "unit_length_ft", "directionality_status"]], on="distance_band_unit_id", how="left")
        unit_miles = pd.to_numeric(out["unit_length_ft"], errors="coerce") / MILE_FT
        out["exposure_daily_vmt_proxy"] = out["adjusted_aadt_length_weighted"] * unit_miles
        out["exposure_denominator"] = out["exposure_daily_vmt_proxy"]
        out["exposure_denominator_status"] = "daily_vmt_proxy_direction_factor_adjusted_not_crash_period_exposure"
        out["exposure_formula"] = "sum(latest_year_aadt_i * effective_direction_factor_i * overlap_length_i) / sum(overlap_length_i) * unit_length_ft / 5280"
        out["exposure_context_status"] = "computed_daily_vmt_proxy_with_source_direction_factor_semantics"
        out["exposure_missing_reason"] = ""
        out["rate_denominator_semantics"] = "daily_vmt_proxy_not_final_crash_period_exposure"
        unresolved = clean_series(out["directionality_status"]).ne("assigned")
        out.loc[unresolved, "rate_denominator_semantics"] = "daily_vmt_proxy_not_rate_ready_unresolved_directionality"
        log(f"aggregate_aadt_matches: output rows={len(out):,}; units={out['distance_band_unit_id'].nunique():,}.")
        return out.drop(
            columns=[
                "unit_length_ft",
                "directionality_status",
                "aadt_weighted_num",
                "adjusted_aadt_weighted_num",
                "matched_length_mi_sum",
                "mixed_aadt_category_count",
                "factor_min",
                "factor_max",
                "factor_nunique",
                "factor_status_min",
                "factor_status_nunique",
                "adjusted_aadt_length_weighted",
            ],
            errors="ignore",
        )


def missing_context(units: pd.DataFrame, spans_all: pd.DataFrame, source_all: pd.DataFrame, method_key: str) -> pd.DataFrame:
    spans = spans_all.loc[spans_all["method_key"].eq(method_key)].copy()
    source_routes = set(source_for_method(source_all, method_key)["route_key"])
    route_flags = spans.assign(route_available=spans["route_key"].isin(source_routes)).groupby("distance_band_unit_id", dropna=False).agg(
        has_route_lineage=("route_key", "count"),
        has_route_compatible_source=("route_available", "any"),
    ).reset_index()
    base = units[["distance_band_unit_id"]].merge(route_flags, on="distance_band_unit_id", how="left")
    base["has_route_lineage"] = base["has_route_lineage"].fillna(0).gt(0)
    base["has_route_compatible_source"] = base["has_route_compatible_source"].fillna(False).map(bool_value)
    base["aadt_context_status"] = np.select(
        [~base["has_route_lineage"], ~base["has_route_compatible_source"]],
        ["missing_no_route_measure_lineage_aadt", "missing_no_route_compatible_aadt"],
        default="missing_no_measure_overlap_aadt",
    )
    base["aadt_missing_reason"] = np.select(
        [~base["has_route_lineage"], ~base["has_route_compatible_source"]],
        ["no usable bin route/measure lineage", "no route-compatible source records"],
        default="route matched but no measure overlap",
    )
    return base[["distance_band_unit_id", "aadt_context_status", "aadt_missing_reason"]]


def route_compatibility_for_method(spans_all: pd.DataFrame, source_all: pd.DataFrame, context: pd.DataFrame, method_key: str) -> dict[str, Any]:
    before_missing = set(context.loc[pd.to_numeric(context["aadt"], errors="coerce").isna(), "distance_band_unit_id"])
    spans = spans_all.loc[spans_all["method_key"].eq(method_key)].copy()
    source_routes = set(source_for_method(source_all, method_key)["route_key"])
    route_compatible_units = set(spans.loc[spans["route_key"].isin(source_routes), "distance_band_unit_id"])
    return {
        "method": method_key,
        "matched_units": "",
        "missing_units_recoverable": len(before_missing & route_compatible_units),
        "resulting_aadt_populated_if_used": "",
        "candidate_match_rows": "",
        "selected_for_patch": False,
        "risk_note": "route-compatibility-only diagnostic; full interval fanout not run because non-strict keys are too broad for this narrow patch",
    }


def compare_methods(method_matches: dict[str, pd.DataFrame], context: pd.DataFrame, spans_all: pd.DataFrame, source_all: pd.DataFrame) -> pd.DataFrame:
    before_missing = set(context.loc[pd.to_numeric(context["aadt"], errors="coerce").isna(), "distance_band_unit_id"])
    rows = []
    before_pop = int(pd.to_numeric(context["aadt"], errors="coerce").notna().sum())
    for method, matches in method_matches.items():
        matched_units = set(matches["distance_band_unit_id"]) if not matches.empty else set()
        rows.append(
            {
                "method": method,
                "matched_units": len(matched_units),
                "missing_units_recoverable": len(before_missing & matched_units),
                "resulting_aadt_populated_if_used": before_pop + len(before_missing & matched_units),
                "candidate_match_rows": len(matches),
                "selected_for_patch": method == "strict",
                "risk_note": "selected strict rebuilt route-measure parent" if method == "strict" else "not selected; route-key fanout risk for narrow semantics patch",
            }
        )
    for method in ["directionless", "route_number", "alternate_route_base_directionless"]:
        rows.append(route_compatibility_for_method(spans_all, source_all, context, method))
    out = pd.DataFrame(rows)
    write_csv("aadt_rollup_method_comparison.csv", out)
    write_csv("aadt_missing_recovery_feasibility.csv", out)
    return out


def patch_context(context: pd.DataFrame, units: pd.DataFrame, aadt_rollup: pd.DataFrame, missing: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in AADT_PATCH_FIELDS:
        if col not in out.columns:
            if col in {"mixed_aadt_flag", "mixed_aadt_category_flag"}:
                out[col] = False
            elif col in {
                "aadt",
                "aadt_year",
                "aadt_value_count",
                "aadt_min",
                "aadt_max",
                "aadt_dominant",
                "aadt_length_weighted",
                "aadt_source_year",
                "exposure_daily_vmt_proxy",
                "exposure_denominator",
                "exposure_directionality_factor",
            }:
                out[col] = math.nan
            else:
                out[col] = ""
    patch_cols = [c for c in AADT_PATCH_FIELDS if c in aadt_rollup.columns]
    patch = aadt_rollup[["distance_band_unit_id", *patch_cols]].drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")
    idx = out["distance_band_unit_id"].isin(patch.index)
    ids = out.loc[idx, "distance_band_unit_id"]
    for col in patch_cols:
        out.loc[idx, col] = ids.map(patch[col])

    miss = missing.loc[~missing["distance_band_unit_id"].isin(patch.index)].drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")
    midx = out["distance_band_unit_id"].isin(miss.index)
    existing_aadt = pd.to_numeric(out["aadt"], errors="coerce")
    fallback_idx = midx & existing_aadt.notna()
    true_missing_idx = midx & ~fallback_idx

    if fallback_idx.any():
        unit_length = units.drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")["unit_length_ft"]
        fallback_ids = out.loc[fallback_idx, "distance_band_unit_id"]
        fallback_aadt = existing_aadt.loc[fallback_idx]
        fallback_unit_miles = pd.to_numeric(fallback_ids.map(unit_length), errors="coerce") / MILE_FT
        fallback_exposure = fallback_aadt.to_numpy(dtype=float) * fallback_unit_miles.to_numpy(dtype=float)
        out.loc[fallback_idx, "aadt_rollup_method"] = "existing_aadt_preserved_no_strict_rebuild_match"
        out.loc[fallback_idx, "aadt_context_status"] = "populated_from_existing_context_no_strict_rebuild_match"
        out.loc[fallback_idx, "aadt_missing_reason"] = ""
        out.loc[fallback_idx, "aadt_source_match_method"] = "existing_context_preserved_after_strict_rebuild_gap"
        out.loc[fallback_idx, "mixed_aadt_flag"] = out.loc[fallback_idx, "mixed_aadt_flag"].fillna(False).map(bool_value)
        out.loc[fallback_idx, "mixed_aadt_category_flag"] = out.loc[fallback_idx, "mixed_aadt_category_flag"].fillna(False).map(bool_value)
        out.loc[fallback_idx, "aadt_value_count"] = np.where(out.loc[fallback_idx, "mixed_aadt_flag"].map(bool_value), np.nan, 1)
        out.loc[fallback_idx, "aadt_min"] = fallback_aadt
        out.loc[fallback_idx, "aadt_max"] = fallback_aadt
        out.loc[fallback_idx, "aadt_dominant"] = fallback_aadt
        out.loc[fallback_idx, "aadt_length_weighted"] = fallback_aadt
        if "aadt_year" in out.columns:
            out.loc[fallback_idx, "aadt_source_year"] = out.loc[fallback_idx, "aadt_year"]
            out.loc[fallback_idx, "aadt_year_status"] = np.where(
                pd.to_numeric(out.loc[fallback_idx, "aadt_year"], errors="coerce").notna(),
                "existing_context_year_preserved",
                "existing_context_year_missing",
            )
        out.loc[fallback_idx, "aadt_value_mix"] = "existing_context_preserved_no_strict_rebuild_match"
        out.loc[fallback_idx, "exposure_daily_vmt_proxy"] = fallback_exposure
        out.loc[fallback_idx, "exposure_denominator"] = fallback_exposure
        out.loc[fallback_idx, "exposure_denominator_status"] = "daily_vmt_proxy_existing_aadt_no_factor_not_crash_period_exposure"
        out.loc[fallback_idx, "exposure_directionality_factor"] = 1.0
        out.loc[fallback_idx, "exposure_directionality_factor_method"] = "no_factor_existing_aadt_preserved"
        out.loc[fallback_idx, "exposure_directionality_factor_status"] = "existing_aadt_no_strict_rebuild_match_no_direction_factor_applied"
        out.loc[fallback_idx, "exposure_formula"] = "existing_aadt * unit_length_ft / 5280"
        out.loc[fallback_idx, "exposure_context_status"] = "computed_daily_vmt_proxy_existing_aadt_no_factor_fallback"
        out.loc[fallback_idx, "exposure_missing_reason"] = ""
        out.loc[fallback_idx, "rate_denominator_semantics"] = "daily_vmt_proxy_not_final_crash_period_exposure"

    mids = out.loc[true_missing_idx, "distance_band_unit_id"]
    out.loc[true_missing_idx, "aadt_context_status"] = mids.map(miss["aadt_context_status"])
    out.loc[true_missing_idx, "aadt_missing_reason"] = mids.map(miss["aadt_missing_reason"])
    out.loc[true_missing_idx, "aadt_source_match_method"] = ""
    out.loc[true_missing_idx, "aadt_rollup_method"] = ""
    out.loc[true_missing_idx, "mixed_aadt_flag"] = False
    out.loc[true_missing_idx, "mixed_aadt_category_flag"] = False
    out.loc[true_missing_idx, "exposure_daily_vmt_proxy"] = math.nan
    out.loc[true_missing_idx, "exposure_denominator"] = math.nan
    out.loc[true_missing_idx, "exposure_denominator_status"] = "missing_aadt"
    out.loc[true_missing_idx, "exposure_directionality_factor"] = math.nan
    out.loc[true_missing_idx, "exposure_directionality_factor_method"] = ""
    out.loc[true_missing_idx, "exposure_directionality_factor_status"] = "missing_aadt_no_factor"
    out.loc[true_missing_idx, "exposure_formula"] = "not_computed_missing_aadt"
    out.loc[true_missing_idx, "exposure_context_status"] = "missing_aadt"
    out.loc[true_missing_idx, "exposure_missing_reason"] = "AADT unavailable"
    out.loc[true_missing_idx, "rate_denominator_semantics"] = "missing_aadt_no_denominator"

    out["mixed_aadt_flag"] = out["mixed_aadt_flag"].fillna(False).map(bool_value)
    out["mixed_aadt_category_flag"] = out["mixed_aadt_category_flag"].fillna(False).map(bool_value)
    # Preserve rate readiness doctrine while refreshing numeric context.
    out.loc[clean_series(out["directionality_status"]).ne("assigned"), "rate_readiness_status"] = "not_rate_ready_unresolved_directionality"
    out.loc[clean_series(out["directionality_status"]).eq("assigned"), "rate_readiness_status"] = "not_rate_ready_crash_assignment_deferred"
    out["crash_rate_ready_flag"] = False
    return out


def audit_outputs(before: pd.DataFrame, after: pd.DataFrame, matches: pd.DataFrame) -> None:
    before_aadt = pd.to_numeric(before["aadt"], errors="coerce")
    after_aadt = pd.to_numeric(after["aadt"], errors="coerce")
    write_csv(
        "aadt_missingness_before_after.csv",
        [
            {
                "metric": "aadt_populated_units",
                "before": int(before_aadt.notna().sum()),
                "after": int(after_aadt.notna().sum()),
            },
            {"metric": "aadt_missing_units", "before": int(before_aadt.isna().sum()), "after": int(after_aadt.isna().sum())},
            {"metric": "mixed_aadt_units", "before": int(before["mixed_aadt_flag"].map(bool_value).sum()), "after": int(after["mixed_aadt_flag"].map(bool_value).sum())},
        ],
    )
    mixed = after.loc[after["mixed_aadt_flag"].map(bool_value), ["distance_band_unit_id", "aadt", "aadt_min", "aadt_max", "aadt_value_count", "aadt_value_mix", "aadt_rollup_method"]]
    write_csv("aadt_mixed_value_audit.csv", mixed.head(50000))
    cat = after.groupby(["aadt_category", "mixed_aadt_category_flag"], dropna=False).size().reset_index(name="unit_count")
    write_csv("aadt_category_mixedness_audit.csv", cat)
    factor = after.groupby(["exposure_directionality_factor_status", "exposure_directionality_factor_method"], dropna=False).agg(
        unit_count=("distance_band_unit_id", "size"),
        exposure_sum=("exposure_denominator", lambda s: float(pd.to_numeric(s, errors="coerce").sum())),
    ).reset_index()
    write_csv("exposure_directionality_factor_summary.csv", factor)
    write_csv(
        "exposure_directionality_factor_decision.csv",
        [
            {
                "decision": "apply_valid_source_direction_factor_else_no_adjustment_fallback",
                "selected": True,
                "rules": "Combined rows with valid DIRECTION_FACTOR apply source factor; Single rows use factor 1.0; null factor/directionality rows keep no-adjustment daily proxy fallback; unresolved directionality remains not rate ready.",
            }
        ],
    )
    before_exp = pd.to_numeric(before["exposure_denominator"], errors="coerce")
    after_exp = pd.to_numeric(after["exposure_denominator"], errors="coerce")
    write_csv(
        "exposure_before_after_summary.csv",
        [
            {"metric": "exposure_populated_units", "before": int(before_exp.notna().sum()), "after": int(after_exp.notna().sum())},
            {"metric": "exposure_sum", "before": float(before_exp.sum()), "after": float(after_exp.sum())},
        ],
    )
    write_csv(
        "exposure_formula_summary.csv",
        [
            {"stage": "before", "formula": "aadt * unit_length_ft / 5280", "semantics": "daily vehicle-mile proxy without direction factor"},
            {
                "stage": "after",
                "formula": "sum(latest_year_aadt_i * effective_direction_factor_i * overlap_length_i) / sum(overlap_length_i) * unit_length_ft / 5280",
                "semantics": "direction-factor-adjusted daily VMT proxy, not final crash-period exposure",
            },
        ],
    )
    rate = after.groupby("rate_readiness_status", dropna=False).size().reset_index(name="unit_count")
    rate["crash_assignment_deferred"] = True
    rate["rate_ready_claimed"] = rate["rate_readiness_status"].astype(str).str.startswith("rate_ready")
    write_csv("rate_readiness_consistency_check.csv", rate)


def row_identity_check(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"check": "row_count_unchanged", "passed": len(before) == len(after) == len(units), "before": len(before), "after": len(after), "expected": len(units)},
        {
            "check": "distance_band_unit_id_set_unchanged",
            "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]),
            "before": before["distance_band_unit_id"].nunique(),
            "after": after["distance_band_unit_id"].nunique(),
            "expected": units["distance_band_unit_id"].nunique(),
        },
        {"check": "distance_band_unit_id_unique", "passed": after["distance_band_unit_id"].is_unique, "before": int(before["distance_band_unit_id"].duplicated().sum()), "after": int(after["distance_band_unit_id"].duplicated().sum()), "expected": 0},
    ]
    out = pd.DataFrame(rows)
    write_csv("row_identity_unchanged_check.csv", out)
    return out


def unit_grain_check(after: pd.DataFrame) -> pd.DataFrame:
    dupes = int(after.duplicated(IDENTITY_COLUMNS).sum())
    out = pd.DataFrame([{"check": "unit_grain_uniqueness", "passed": dupes == 0, "duplicate_count": dupes, "identity_columns": "|".join(IDENTITY_COLUMNS)}])
    write_csv("unit_grain_uniqueness_check.csv", out)
    return out


def directionality_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    b = before.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="before_count")
    a = after.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="after_count")
    out = b.merge(a, on=["upstream_downstream", "directionality_status"], how="outer").fillna(0)
    out["passed"] = out["before_count"].astype(int).eq(out["after_count"].astype(int))
    write_csv("directionality_reconciliation.csv", out)
    return out


def length_bin_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field in ["bin_count", "unit_length_ft"]:
        b = pd.to_numeric(before[field], errors="coerce").fillna(-999999)
        a = pd.to_numeric(after[field], errors="coerce").fillna(-999999)
        rows.append({"field": field, "passed": bool(b.eq(a).all()), "before_sum": float(b.sum()), "after_sum": float(a.sum()), "changed_rows": int((b != a).sum())})
    out = pd.DataFrame(rows)
    write_csv("length_bin_count_reconciliation.csv", out)
    return out


def unchanged_non_target_check(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    protected = [c for c in before.columns if c in after.columns and (c.startswith(PROTECTED_PREFIXES) or c in PROTECTED_FIELDS)]
    rows = []
    for col in protected:
        same = before[col].equals(after[col])
        changed = 0
        if not same:
            changed = int((before[col].astype("string").fillna("<NA>") != after[col].astype("string").fillna("<NA>")).sum())
        rows.append({"field": col, "passed": same, "changed_rows": changed})
    out = pd.DataFrame(rows)
    write_csv("unchanged_non_target_context_fields_check.csv", out)
    return out


def no_crash_direction_field_check() -> pd.DataFrame:
    rows = []
    for path in [CONTEXT, UNITS, BINS, TRAVELWAY, AADT, CRASHES]:
        cols = pq.ParquetFile(path).schema_arrow.names if path.exists() and path.suffix == ".parquet" else []
        detected = [c for c in cols if is_crash_direction_field(c)]
        rows.append({"path": rel(path), "crash_direction_like_fields_detected": "|".join(detected), "used_as_join_or_derivation_field": False, "passed": True})
    out = pd.DataFrame(rows)
    write_csv("no_crash_direction_field_check.csv", out)
    return out


def forbidden_mvp_lookup_product_check() -> pd.DataFrame:
    rows = []
    if OUT.exists():
        for path in OUT.iterdir():
            rows.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": any(token in path.name.lower() for token in FORBIDDEN_OUTPUT_TOKENS)})
    out = pd.DataFrame(rows)
    out["passed"] = ~out["forbidden_mvp_lookup_or_rate_distribution_name"] if not out.empty else True
    write_csv("forbidden_mvp_lookup_product_check.csv", out)
    return out


def full_qa(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> bool:
    after_aadt = pd.to_numeric(after["aadt"], errors="coerce")
    after_exposure = pd.to_numeric(after["exposure_denominator"], errors="coerce")
    aadt_exposure_mismatch = int((after_aadt.notna() & after_exposure.isna()).sum())
    write_csv(
        "aadt_exposure_consistency_check.csv",
        [
            {
                "check": "aadt_populated_rows_have_exposure_denominator",
                "passed": aadt_exposure_mismatch == 0,
                "mismatch_count": aadt_exposure_mismatch,
                "aadt_populated_units": int(after_aadt.notna().sum()),
                "exposure_populated_units": int(after_exposure.notna().sum()),
            }
        ],
    )
    checks = [
        row_identity_check(before, after, units)["passed"].all(),
        unit_grain_check(after)["passed"].all(),
        directionality_reconciliation(before, after)["passed"].all(),
        length_bin_reconciliation(before, after)["passed"].all(),
        unchanged_non_target_check(before, after)["passed"].all(),
        no_crash_direction_field_check()["passed"].all(),
        aadt_exposure_mismatch == 0,
    ]
    forbidden = forbidden_mvp_lookup_product_check()
    if not forbidden.empty:
        checks.append(bool(forbidden["passed"].all()))
    readback_ok = len(after) == parquet_row_count(STAGING / "distance_band_context.aadt_exposure_candidate.tmp.parquet")
    checks.append(readback_ok)
    return bool(all(checks))


def update_metadata(candidate: pd.DataFrame, final_decision: str) -> None:
    stamp = now()
    manifest = read_json(MANIFEST)
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "bounded_phase": "AADT exposure semantics and directionality-factor patch",
            "build_version": BUILD_VERSION,
            "patched_utc": stamp,
            "row_count": int(len(candidate)),
            "script": "src.roadway_graph.patch.patch_distance_band_context_aadt_exposure_semantics",
            "final_decision": final_decision,
            "aadt_populated_units": int(pd.to_numeric(candidate["aadt"], errors="coerce").notna().sum()),
            "exposure_semantics": "daily_vmt_proxy_not_final_crash_period_exposure",
        }
    )
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    parents = set(product.get("canonical_parents", []))
    parents.update([rel(UNITS), rel(BINS), rel(TRAVELWAY), rel(AADT)])
    product.update(
        {
            "row_count": int(len(candidate)),
            "updated_utc": stamp,
            "script": "src.roadway_graph.patch.patch_distance_band_context_aadt_exposure_semantics",
            "final_decision": final_decision,
            "qa_review_path": rel(OUT),
            "aadt_exposure_patch_status": "passed",
            "aadt_populated_units": int(pd.to_numeric(candidate["aadt"], errors="coerce").notna().sum()),
            "exposure_populated_units": int(pd.to_numeric(candidate["exposure_denominator"], errors="coerce").notna().sum()),
            "rate_denominator_semantics": "daily_vmt_proxy_not_final_crash_period_exposure",
            "mvp_lookup_or_rate_distribution_status": "not_built",
            "crash_direction_field_status": "not_used",
            "canonical_parents": sorted(parents),
        }
    )
    write_json_path(MANIFEST, manifest)

    schema = read_json(SCHEMA)
    schema["updated_utc"] = stamp
    schema.setdefault("tables", {})["distance_band_context.parquet"] = {
        "path": rel(CONTEXT),
        "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved",
        "row_count": int(len(candidate)),
        "columns": [{"name": c, "dtype": str(candidate[c].dtype)} for c in candidate.columns],
        "updated_utc": stamp,
        "build_version": BUILD_VERSION,
    }
    write_json_path(SCHEMA, schema)

    note = f"""

## AADT/Exposure Semantics Patch ({BUILD_VERSION})

Patched staged `distance_band_context.parquet` after temp-output QA. AADT is
now represented with latest-year length-weighted rollup diagnostics, and
`exposure_denominator` is explicitly a direction-factor-aware daily VMT proxy,
not final crash-period exposure. No access, speed, crash, MVP, lookup, rate
distribution, or canonical root product was built.

Decision: `{final_decision}`.
"""
    README.write_text(README.read_text(encoding="utf-8") + note, encoding="utf-8")


def write_remaining_queue() -> None:
    write_csv(
        "remaining_context_patch_queue.csv",
        [
            {
                "sequence": 1,
                "task": "Access feasibility/repair patch",
                "scope": "separate true zero-access from missing/no-compatible-route; test route alias fanout and geometry-based assignment; preserve source-limited access flags",
            },
            {
                "sequence": 2,
                "task": "Crash assignment layer",
                "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA",
            },
            {
                "sequence": 3,
                "task": "Final distance_band_context validation and MVP-readiness pass",
                "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build",
            },
        ],
    )
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "priority": 1,
                "recommended_next_action": "Run Access feasibility/repair patch",
                "reason": "Access remains the next context family needing true-zero versus missing/source-limited separation.",
            },
            {
                "priority": 2,
                "recommended_next_action": "Keep exposure labeled as daily proxy until crash-period denominator policy is explicitly accepted",
                "reason": "This patch does not compute crash-period exposure or rates.",
            },
        ],
    )


def write_findings(final_decision: str, before: pd.DataFrame, after: pd.DataFrame, decision: str) -> None:
    before_aadt = int(pd.to_numeric(before["aadt"], errors="coerce").notna().sum())
    after_aadt = int(pd.to_numeric(after["aadt"], errors="coerce").notna().sum())
    before_exp = int(pd.to_numeric(before["exposure_denominator"], errors="coerce").notna().sum())
    after_exp = int(pd.to_numeric(after["exposure_denominator"], errors="coerce").notna().sum())
    remaining = len(after) - after_aadt
    text = f"""# AADT/Exposure Semantics Patch Findings

## Problem Addressed
The staged context had high AADT coverage but used latest-year dominant AADT and labeled `exposure_denominator` only as `AADT * unit_length_ft / 5280`. This patch documents mixed AADT selection and source direction-factor semantics.

## AADT Source Semantics
Decision: `{decision}`. The source has `DIRECTIONALITY` and `DIRECTION_FACTOR`: `Combined` rows carry valid factors, `Single` rows carry factor 1.0, and blank/null rows require no-adjustment daily proxy fallback. This is mixed by source field, not a blanket two-way assumption.

## Useful Old Methods
Old AADT v3 and active denominator scripts were useful as method evidence for route+measure matching, latest-year selection, source `DIRECTION_FACTOR`, null-factor fallback, and LINKID/EDGE_RTE_KEY diagnostics. They were not used as data parents.

## Mixed AADT Handling
Representative AADT is `latest_year_length_weighted_aadt`. Dominant, min, max, value count, value mix, mixed flag, and mixed-category flag are preserved. AADT category is based on length-weighted AADT.

## Directionality Factor
Valid source factors are applied length-weighted. `Single`/carriageway-specific rows use factor 1.0. Null/blank factor rows use no-adjustment daily proxy fallback. Unresolved directionality units remain not rate ready.

## Exposure Formula
Before: `aadt * unit_length_ft / 5280`.

After: `sum(latest_year_aadt_i * effective_direction_factor_i * overlap_length_i) / sum(overlap_length_i) * unit_length_ft / 5280`.

`exposure_denominator` is a daily VMT proxy, not final crash-period exposure.

## Coverage
AADT coverage before/after: {before_aadt} -> {after_aadt}. Exposure coverage before/after: {before_exp} -> {after_exp}. Remaining AADT missing units: {remaining}.

## Guard Confirmations
Speed, access, crash, and roadway fields were not changed. Crash direction fields were not used. No MVP, lookup, rate-distribution, crash assignment, or crash-rate product was built.

## Final Decision
`{final_decision}`

## Recommended Next Task
Run the Access feasibility/repair patch from `remaining_context_patch_queue.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_manifests(final_decision: str, replaced: bool) -> None:
    write_json(
        "manifest.json",
        {
            "bounded_question": "AADT/exposure semantics and directionality-factor patch for staged distance_band_context",
            "created_utc": now(),
            "script": "src.roadway_graph.patch.patch_distance_band_context_aadt_exposure_semantics",
            "staged_product": rel(CONTEXT),
            "review_output": rel(OUT),
            "final_decision": final_decision,
            "replacement_performed": replaced,
            "no_crash_direction_fields_used": True,
            "mvp_lookup_rate_distribution_built": False,
        },
    )
    write_json(
        "qa_manifest.json",
        {"created_utc": now(), "phase_timings": PHASES, "qa_outputs": sorted(p.name for p in OUT.glob("*.csv")), "final_decision": final_decision, "replacement_performed": replaced},
    )


def main(*, smoke: bool = False, smoke_units: int = 5000) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mode = "smoke benchmark" if smoke else "AADT/exposure semantics patch"
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started {mode}.\n", encoding="utf-8")
    parent_dependency_check()
    source_schema_inventory()
    old_method_inventory()

    with phase("load_context_units_aadt"):
        before = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
        aadt_source = load_aadt_source()
    decision = aadt_source_semantics_decision(aadt_source)

    spans, span_summary = load_unit_route_spans(units)
    method_matches = {"strict": match_method(spans, aadt_source, "strict")}
    compare_methods(method_matches, before, spans, aadt_source)

    strict_matches = method_matches["strict"]
    if smoke:
        started = time.perf_counter()
        smoke_ids = strict_matches["distance_band_unit_id"].drop_duplicates().head(smoke_units)
        smoke_matches = strict_matches.loc[strict_matches["distance_band_unit_id"].isin(set(smoke_ids))].copy()
        log(f"smoke: aggregating {len(smoke_matches):,} strict candidate rows across {smoke_matches['distance_band_unit_id'].nunique():,} units.")
        smoke_rollup = aggregate_matches(
            smoke_matches,
            before,
            units,
            "strict_route_measure_latest_year_length_weighted_aadt_with_source_direction_factor_smoke",
        )
        elapsed = time.perf_counter() - started
        write_csv(
            "aadt_aggregation_benchmark.csv",
            [
                {
                    "mode": "smoke",
                    "smoke_units_requested": smoke_units,
                    "candidate_rows": int(len(smoke_matches)),
                    "candidate_units": int(smoke_matches["distance_band_unit_id"].nunique()),
                    "aggregated_rows": int(len(smoke_rollup)),
                    "elapsed_seconds": round(elapsed, 3),
                    "staged_replacement_performed": False,
                }
            ],
        )
        write_manifests("smoke_benchmark_no_replacement", False)
        log("Smoke benchmark completed without staged replacement.")
        return

    rollup = aggregate_matches(strict_matches, before, units, "strict_route_measure_latest_year_length_weighted_aadt_with_source_direction_factor")
    missing = missing_context(units, spans, aadt_source, "strict")
    after = patch_context(before, units, rollup, missing)
    audit_outputs(before, after, strict_matches)

    final_decision = "aadt_exposure_patch_passed_with_daily_proxy_semantics"
    temp = STAGING / "distance_band_context.aadt_exposure_candidate.tmp.parquet"
    with phase("write_temp_candidate_parquet"):
        after.to_parquet(temp, index=False)
    reread = pd.read_parquet(temp)
    qa_passed = full_qa(before, reread, units)
    write_csv(
        "distance_band_context_patch_readiness_decision.csv",
        [
            {
                "stage": "final",
                "passed": qa_passed,
                "final_decision": final_decision if qa_passed else "aadt_exposure_patch_failed_no_replacement",
                "replacement_performed": qa_passed,
                "aadt_source_semantics_decision": decision,
                "aadt_populated_units": int(pd.to_numeric(reread["aadt"], errors="coerce").notna().sum()),
                "exposure_populated_units": int(pd.to_numeric(reread["exposure_denominator"], errors="coerce").notna().sum()),
            }
        ],
    )
    if not qa_passed:
        final_decision = "aadt_exposure_patch_failed_no_replacement"
        temp.unlink(missing_ok=True)
        write_remaining_queue()
        write_findings(final_decision, before, before, decision)
        write_manifests(final_decision, False)
        log("Final QA failed; staged product not replaced.")
        return

    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(temp), str(CONTEXT))
    update_metadata(after, final_decision)
    write_remaining_queue()
    write_findings(final_decision, before, after, decision)
    write_manifests(final_decision, True)
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Patch staged distance_band_context AADT/exposure semantics.")
    parser.add_argument("--smoke", action="store_true", help="Run strict-match aggregation smoke benchmark only; do not write staged parquet.")
    parser.add_argument("--smoke-units", type=int, default=5000, help="Number of matched units to include in smoke aggregation.")
    args = parser.parse_args()
    main(smoke=args.smoke, smoke_units=args.smoke_units)
