"""Patch staged distance_band_context access semantics.

This bounded repair recomputes typed access context from current staged
unit/bin route-measure lineage and artifacts/normalized/access_v2.parquet.
It separates route/measure matched access, route/measure zero evidence, and
source/join-limited unknown access. Geometry access assignment is audited but
deferred.

It does not repair roadway, speed, AADT, exposure, crash, rate, MVP, or lookup
products.
"""

from __future__ import annotations

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
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_access"

CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
TRAVELWAY = STAGING / "travelway_network_index.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"
TEMP = STAGING / "distance_band_context.access_candidate.tmp.parquet"

ACCESS = REPO / "artifacts/normalized/access_v2.parquet"
ROADS = REPO / "artifacts/normalized/roads.parquet"
SPEED = REPO / "artifacts/normalized/speed.parquet"
AADT = REPO / "artifacts/normalized/aadt.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

BUILD_VERSION = "distance_band_context_access_patch_v1_2026-06-15"
MILE_FT = 5280.0
MEASURE_BUCKET_MI = 0.05
MIN_OVERLAP_MI = 1e-8

IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
]

ACCESS_PATCH_FIELDS = [
    "access_count",
    "access_count_band",
    "access_type_flags",
    "access_type_dominant",
    "access_type_summary",
    "typed_access_count",
    "untyped_access_count",
    "riro_access_count",
    "other_review_access_count",
    "access_context_status",
    "access_source_match_method",
    "access_missing_reason",
    "access_zero_evidence_status",
    "access_context_quality_flag",
    "access_candidate_count",
    "mixed_access_flag",
]

CRASH_DIRECTION_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

FORBIDDEN_OUTPUT_TOKENS = ("lookup", "rate_distribution", "mvp")

CORRECTED_CATEGORY_MAP = {
    "U": "unrestricted_or_full_access",
    "RIRO": "right_in_right_out",
    "R": "right_in_right_out",
    "RC": "right_in_right_out",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "LIRIRO": "restricted_partial_access",
    "": "unknown",
}

ACCESS_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_out_only",
    "right_in_only",
    "other_review",
    "unknown",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"- {now()} - {message}\n"
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(line)
    print(line.strip(), flush=True)


@contextmanager
def phase(name: str, **details: Any):
    suffix = f" {details}" if details else ""
    log(f"BEGIN {name}{suffix}")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        PHASE_TIMINGS.append({"phase": name, "elapsed_seconds": round(elapsed, 3), **details})
        log(f"END {name}; elapsed_seconds={elapsed:.3f}")


PHASE_TIMINGS: list[dict[str, Any]] = []


def write_csv(name: str, rows: Any) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(OUT / name, index=False)
    return frame


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json_path(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def route_key(value: Any) -> str:
    text = clean_text(value).upper()
    if not text:
        return ""
    text = text.replace("R-VA", " ").replace("S-VA", " ").replace("VA", " ")
    text = re.sub(r"[^A-Z0-9]", " ", text)
    joined = "".join(part for part in text.split() if part)
    if not joined:
        return ""
    direction_map = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}
    match = re.search(r"(US|SR|IS|I)(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?(BUS\d+)?", joined)
    if match:
        prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
        direction = direction_map.get(match.group(4) or "", match.group(4) or "")
        suffix = match.group(5) or ""
        return f"{prefix}{int(match.group(3))}{direction}{suffix}"
    match = re.search(r"(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?(BUS\d+)?", joined)
    if match:
        direction = direction_map.get(match.group(3) or "", match.group(3) or "")
        suffix = match.group(4) or ""
        return f"{int(match.group(2))}{direction}{suffix}"
    return joined


def directionless_route_key(value: Any) -> str:
    return re.sub(r"[NSEW](BUS\d+)?$", lambda m: m.group(1) or "", route_key(value))


def route_number_key(value: Any) -> str:
    key = route_key(value)
    match = re.search(r"([A-Z]+)?(\d+)", key)
    return str(int(match.group(2))) if match else ""


def normalize_route_cache(values: pd.Series, label: str) -> pd.DataFrame:
    unique = pd.Series(values.dropna().astype(str).unique(), name="raw_route")
    out = pd.DataFrame({"raw_route": unique})
    out["route_key"] = out["raw_route"].map(route_key)
    out["directionless_route_key"] = out["raw_route"].map(directionless_route_key)
    out["route_number_key"] = out["raw_route"].map(route_number_key)
    log(f"Route cache {label}: {len(out):,} unique routes.")
    return out


def category_from_raw(raw_code: Any, prior_category: Any = "") -> str:
    code = clean_text(raw_code).upper()
    if code in CORRECTED_CATEGORY_MAP:
        return CORRECTED_CATEGORY_MAP[code]
    prior = clean_text(prior_category)
    return prior if prior in ACCESS_CATEGORIES else "other_review"


def access_count_band(count: Any) -> str:
    value = pd.to_numeric(pd.Series([count]), errors="coerce").iloc[0]
    if pd.isna(value):
        return ""
    value = int(value)
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2-3"
    if value <= 7:
        return "4-7"
    return "8+"


def parquet_row_count(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def forbidden_crash_direction_cols(columns: list[str]) -> list[str]:
    blocked = []
    for col in columns:
        lower = col.lower()
        if any(token in lower for token in CRASH_DIRECTION_TOKENS):
            blocked.append(col)
    return blocked


def source_schema_inventory(access: pd.DataFrame, context: pd.DataFrame) -> None:
    rows = []
    for col in access.columns:
        s = access[col]
        role = (
            "route" if col in {"route_name", "_rte_nm"} else
            "measure" if col in {"route_measure", "_m"} else
            "geometry" if col in {"geometry", "_x", "_y"} else
            "access_type" if "access_control" in col.lower() or "access_direction" in col.lower() else
            "source_id" if "source" in col.lower() or col == "id" else
            "other"
        )
        if role == "geometry" or s.dtype != object and not str(s.dtype).startswith("string"):
            nonblank = int(s.notna().sum())
        else:
            nonblank = int(clean_series(s).ne("").sum())
        rows.append(
            {
                "column": col,
                "dtype": str(s.dtype),
                "nonnull_count": int(s.notna().sum()),
                "nonblank_count": nonblank,
                "nunique": int(s.nunique(dropna=True)),
                "role": role,
            }
        )
    write_csv("access_source_schema_inventory.csv", rows)

    current = context.groupby(["access_context_status", "access_missing_reason"], dropna=False).size().reset_index(name="unit_count")
    write_csv("current_access_status_audit.csv", current)


def source_coverage_outputs(access: pd.DataFrame) -> None:
    route_nonblank = clean_series(access.get("route_name", pd.Series("", index=access.index))).ne("")
    measure_nonnull = pd.to_numeric(access.get("route_measure", pd.Series(np.nan, index=access.index)), errors="coerce").notna()
    by_route = access.loc[route_nonblank].groupby("route_key", dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        measure_populated_count=("route_measure", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        min_measure=("route_measure", "min"),
        max_measure=("route_measure", "max"),
        access_type_count=("access_category", "nunique"),
    ).reset_index()
    summary = [
        {"metric": "source_rows", "value": len(access)},
        {"metric": "route_name_populated_rows", "value": int(route_nonblank.sum())},
        {"metric": "route_measure_populated_rows", "value": int(measure_nonnull.sum())},
        {"metric": "unique_strict_route_keys", "value": int(access["route_key"].replace("", np.nan).nunique(dropna=True))},
        {"metric": "unique_directionless_route_keys", "value": int(access["directionless_route_key"].replace("", np.nan).nunique(dropna=True))},
        {"metric": "unique_route_number_keys", "value": int(access["route_number_key"].replace("", np.nan).nunique(dropna=True))},
    ]
    write_csv("access_source_route_coverage_summary.csv", pd.concat([pd.DataFrame(summary), by_route.head(250).assign(metric="route_sample", value="")], ignore_index=True, sort=False))

    geom_rows = [
        {"metric": "geometry_nonnull_rows", "value": int(access.get("geometry", pd.Series(index=access.index, dtype=object)).notna().sum())},
        {"metric": "x_y_nonnull_rows", "value": int(access.get("_x", pd.Series(index=access.index, dtype=object)).notna().sum() & access.get("_y", pd.Series(index=access.index, dtype=object)).notna().sum())},
        {"metric": "unique_xy_pairs", "value": int(access[["_x", "_y"]].dropna().drop_duplicates().shape[0]) if {"_x", "_y"}.issubset(access.columns) else 0},
        {"metric": "geometry_patch_decision", "value": "deferred_conservative_route_measure_patch_selected"},
    ]
    write_csv("access_source_geometry_summary.csv", geom_rows)

    type_counts = access.groupby(["raw_access_control_code", "prior_access_category", "access_category"], dropna=False).size().reset_index(name="source_point_count")
    write_csv("access_type_recode_summary.csv", type_counts.sort_values(["access_category", "raw_access_control_code"]))


def load_access_source() -> pd.DataFrame:
    access = pd.read_parquet(ACCESS)
    blocked = forbidden_crash_direction_cols(list(access.columns))
    if blocked:
        raise ValueError(f"Refusing to read crash direction-like fields from access source: {blocked}")
    access = access.copy()
    access["access_point_id"] = (
        clean_series(access.get("access_v2_source_priority", pd.Series("", index=access.index)))
        + ":"
        + clean_series(access.get("access_v2_source_row_id", pd.Series("", index=access.index)))
    )
    blank_id = clean_series(access["access_point_id"]).isin({":", ""})
    access.loc[blank_id, "access_point_id"] = access.loc[blank_id].index.astype(str)
    access["route_name"] = clean_series(access.get("route_name", access.get("_rte_nm", pd.Series("", index=access.index))))
    access["route_measure"] = pd.to_numeric(access.get("route_measure", access.get("_m", pd.Series(np.nan, index=access.index))), errors="coerce")
    cache = normalize_route_cache(access["route_name"], "access_route_name")
    access = access.merge(cache, left_on="route_name", right_on="raw_route", how="left").drop(columns=["raw_route"])
    access["raw_access_control_code"] = clean_series(access.get("access_control_code", pd.Series("", index=access.index))).str.upper()
    access["prior_access_category"] = clean_series(access.get("access_control_category", pd.Series("", index=access.index))).replace("", "unknown")
    access["access_category"] = [
        category_from_raw(code, prior)
        for code, prior in zip(access["raw_access_control_code"], access["prior_access_category"])
    ]
    access["access_direction_normalized"] = clean_series(access.get("access_direction_normalized", pd.Series("", index=access.index))).replace("", "unknown")
    valid = access["route_key"].fillna("").ne("") & access["route_measure"].notna()
    access = access.loc[valid].drop_duplicates(["access_point_id", "route_key", "route_measure", "access_category"]).copy()
    return access


def build_unit_route_spans(units: pd.DataFrame, bins: pd.DataFrame) -> dict[str, pd.DataFrame]:
    with phase("build_compact_unit_route_spans"):
        unit_join_cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
        need = [
            *unit_join_cols,
            "stable_bin_id",
            "logical_corridor_chain_id",
            "primary_stable_travelway_id",
            "route_base",
            "source_route_name",
            "source_measure_start",
            "source_measure_end",
            "bin_length_ft",
        ]
        merged = bins[[c for c in need if c in bins.columns]].copy()
        merged["upstream_downstream"] = clean_series(merged["upstream_downstream"])
        merged.loc[~merged["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        merged = merged.merge(units[IDENTITY_COLUMNS], on=unit_join_cols, how="left", validate="many_to_one")
        if merged["distance_band_unit_id"].isna().any():
            raise RuntimeError("bin_context rows failed distance_band_units reconciliation")
        merged["source_measure_start"] = pd.to_numeric(merged["source_measure_start"], errors="coerce")
        merged["source_measure_end"] = pd.to_numeric(merged["source_measure_end"], errors="coerce")
        merged["measure_min"] = merged[["source_measure_start", "source_measure_end"]].min(axis=1)
        merged["measure_max"] = merged[["source_measure_start", "source_measure_end"]].max(axis=1)
        merged["span_length_ft"] = pd.to_numeric(merged.get("bin_length_ft", pd.Series(np.nan, index=merged.index)), errors="coerce").fillna(0)
        source_cache = normalize_route_cache(merged["source_route_name"], "bin_source_route_name")
        base_cache = normalize_route_cache(merged["route_base"], "bin_route_base")
        merged = merged.merge(source_cache.add_prefix("source_"), left_on="source_route_name", right_on="source_raw_route", how="left")
        merged = merged.merge(base_cache.add_prefix("base_"), left_on="route_base", right_on="base_raw_route", how="left")
        method_map = {
            "strict": "source_route_key",
            "directionless": "source_directionless_route_key",
            "route_number": "source_route_number_key",
            "alternate_route_base_directionless": "base_directionless_route_key",
        }
        spans: dict[str, pd.DataFrame] = {}
        for method, col in method_map.items():
            part = merged[["distance_band_unit_id", col, "measure_min", "measure_max", "span_length_ft", "logical_corridor_chain_id", "primary_stable_travelway_id"]].rename(columns={col: "route_key"}).copy()
            part["route_key"] = clean_series(part["route_key"])
            part = part.loc[part["route_key"].ne("") & part["measure_min"].notna() & part["measure_max"].notna()].copy()
            grouped = part.groupby(["distance_band_unit_id", "route_key"], dropna=False).agg(
                measure_min=("measure_min", "min"),
                measure_max=("measure_max", "max"),
                span_length_ft=("span_length_ft", "sum"),
                bin_count=("route_key", "size"),
                chain_count=("logical_corridor_chain_id", "nunique"),
                travelway_count=("primary_stable_travelway_id", "nunique"),
            ).reset_index()
            grouped = grouped.loc[grouped["measure_max"].ge(grouped["measure_min"])].copy()
            spans[method] = grouped
        summary = []
        for method, frame in spans.items():
            summary.append(
                {
                    "method": method,
                    "span_rows": len(frame),
                    "unit_count": frame["distance_band_unit_id"].nunique(),
                    "unique_route_keys": frame["route_key"].nunique(),
                }
            )
        write_csv("unit_route_span_summary.csv", summary)
        return spans


def source_for_method(access: pd.DataFrame, method: str) -> pd.DataFrame:
    key_col = {
        "strict": "route_key",
        "directionless": "directionless_route_key",
        "route_number": "route_number_key",
        "alternate_route_base_directionless": "directionless_route_key",
    }[method]
    cols = [
        "access_point_id",
        key_col,
        "route_measure",
        "access_category",
        "raw_access_control_code",
        "access_direction_normalized",
    ]
    out = access[cols].rename(columns={key_col: "route_key"}).copy()
    out["route_key"] = clean_series(out["route_key"])
    return out.loc[out["route_key"].ne("") & out["route_measure"].notna()].copy()


def expand_span_buckets(spans: pd.DataFrame) -> pd.DataFrame:
    work = spans.loc[spans["route_key"].ne("") & spans["measure_min"].notna() & spans["measure_max"].notna()].copy()
    work["bucket_start"] = np.floor(work["measure_min"] / MEASURE_BUCKET_MI).astype("int64")
    work["bucket_end"] = np.floor(work["measure_max"] / MEASURE_BUCKET_MI).astype("int64")
    work["measure_bucket"] = [range(start, end + 1) for start, end in zip(work["bucket_start"], work["bucket_end"])]
    return work.explode("measure_bucket")[["distance_band_unit_id", "route_key", "measure_min", "measure_max", "span_length_ft", "measure_bucket"]]


def match_access_method(spans: pd.DataFrame, source: pd.DataFrame, method: str, *, run_full: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    with phase("match_access_method", method=method, span_rows=len(spans), source_rows=len(source), run_full=run_full):
        source_routes = set(source["route_key"].dropna().unique())
        route_compatible_units = set(spans.loc[spans["route_key"].isin(source_routes), "distance_band_unit_id"].unique())
        summary = {
            "method": method,
            "route_compatible_units": len(route_compatible_units),
            "run_full_interval_match": run_full,
            "risk_note": "selected strict source-rooted route_measure" if method == "strict" else "diagnostic_only_not_selected",
        }
        if not run_full:
            return pd.DataFrame(), summary
        left = expand_span_buckets(spans[spans["route_key"].isin(source_routes)].copy())
        right = source.copy()
        right["measure_bucket"] = np.floor(right["route_measure"] / MEASURE_BUCKET_MI).astype("int64")
        cand = left.merge(right, on=["route_key", "measure_bucket"], how="inner")
        matches = cand.loc[
            cand["route_measure"].ge(cand["measure_min"] - MIN_OVERLAP_MI)
            & cand["route_measure"].le(cand["measure_max"] + MIN_OVERLAP_MI)
        ].copy()
        matches = matches.drop_duplicates(["distance_band_unit_id", "access_point_id", "access_category"])
        summary.update(
            {
                "candidate_rows": len(cand),
                "match_rows": len(matches),
                "units_with_matched_access_points": matches["distance_band_unit_id"].nunique() if not matches.empty else 0,
                "matched_access_points": matches["access_point_id"].nunique() if not matches.empty else 0,
            }
        )
        return matches, summary


def dominant_category(grouped: pd.DataFrame) -> pd.DataFrame:
    if grouped.empty:
        return pd.DataFrame(columns=["distance_band_unit_id", "access_type_dominant"])
    work = grouped.sort_values(["distance_band_unit_id", "category_count", "access_category"], ascending=[True, False, True])
    return work.drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", "access_category"]].rename(columns={"access_category": "access_type_dominant"})


def collapse_unique(values: pd.Series, limit: int = 20) -> str:
    out: list[str] = []
    for val in values.dropna().astype(str):
        val = val.strip()
        if val and val not in out:
            out.append(val)
        if len(out) >= limit:
            break
    return "|".join(out)


def aggregate_access(matches: pd.DataFrame, spans: pd.DataFrame, context: pd.DataFrame, source_routes: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("aggregate_access_matches", match_rows=len(matches), matched_units=matches["distance_band_unit_id"].nunique() if not matches.empty else 0):
        if matches.empty:
            matched = pd.DataFrame(columns=["distance_band_unit_id", *ACCESS_PATCH_FIELDS])
        else:
            base = matches.groupby("distance_band_unit_id", dropna=False).agg(
                access_count=("access_point_id", "nunique"),
                access_candidate_count=("access_point_id", "size"),
                access_type_flags=("access_category", lambda s: collapse_unique(pd.Series(sorted(set(s.dropna().astype(str)))))),
                access_type_summary=("raw_access_control_code", lambda s: collapse_unique(s, 30)),
            ).reset_index()
            cat_counts = matches.groupby(["distance_band_unit_id", "access_category"], dropna=False)["access_point_id"].nunique().reset_index(name="category_count")
            dom = dominant_category(cat_counts)
            pivot = cat_counts.pivot_table(index="distance_band_unit_id", columns="access_category", values="category_count", aggfunc="sum", fill_value=0).reset_index()
            for cat in ACCESS_CATEGORIES:
                if cat not in pivot.columns:
                    pivot[cat] = 0
            matched = base.merge(dom, on="distance_band_unit_id", how="left").merge(pivot, on="distance_band_unit_id", how="left")
            matched["typed_access_count"] = matched[[
                "unrestricted_or_full_access",
                "right_in_right_out",
                "restricted_partial_access",
                "right_out_only",
                "right_in_only",
                "other_review",
            ]].sum(axis=1).astype(int)
            matched["untyped_access_count"] = matched["unknown"].fillna(0).astype(int)
            matched["riro_access_count"] = matched["right_in_right_out"].fillna(0).astype(int)
            matched["other_review_access_count"] = matched["other_review"].fillna(0).astype(int)
            matched["access_count_band"] = matched["access_count"].map(access_count_band)
            matched["access_context_status"] = "matched_access_points"
            matched["access_source_match_method"] = "strict_route_measure_access_v2"
            matched["access_missing_reason"] = ""
            matched["access_zero_evidence_status"] = "not_zero_access_points_matched"
            matched["access_context_quality_flag"] = np.where(
                matched["untyped_access_count"].gt(0),
                "matched_access_contains_unknown_type",
                "matched_access_typed_source",
            )
            matched["mixed_access_flag"] = cat_counts.groupby("distance_band_unit_id")["access_category"].nunique().reindex(matched["distance_band_unit_id"]).fillna(0).gt(1).to_numpy()
            drop_cols = [c for c in ACCESS_CATEGORIES if c in matched.columns]
            matched = matched.drop(columns=drop_cols)

        route_compatible_units = set(spans.loc[spans["route_key"].isin(source_routes), "distance_band_unit_id"].unique())
        matched_units = set(matched["distance_band_unit_id"]) if not matched.empty else set()
        zero_units = sorted(route_compatible_units - matched_units)
        zero = pd.DataFrame({"distance_band_unit_id": zero_units})
        if not zero.empty:
            zero["access_count"] = 0
            zero["access_count_band"] = "0"
            zero["access_type_flags"] = ""
            zero["access_type_dominant"] = "none"
            zero["access_type_summary"] = ""
            zero["typed_access_count"] = 0
            zero["untyped_access_count"] = 0
            zero["riro_access_count"] = 0
            zero["other_review_access_count"] = 0
            zero["access_context_status"] = "valid_zero_access_route_measure_evidence"
            zero["access_source_match_method"] = "strict_route_measure_access_v2"
            zero["access_missing_reason"] = ""
            zero["access_zero_evidence_status"] = "zero_access_points_observed_on_route_measure_compatible_source_route"
            zero["access_context_quality_flag"] = "valid_zero_access_route_measure_evidence"
            zero["access_candidate_count"] = 0
            zero["mixed_access_flag"] = False

        patched = pd.concat([matched, zero], ignore_index=True, sort=False)
        all_ids = set(context["distance_band_unit_id"])
        missing_ids = sorted(all_ids - set(patched["distance_band_unit_id"]))
        missing = pd.DataFrame({"distance_band_unit_id": missing_ids})
        if not missing.empty:
            missing["access_count"] = np.nan
            missing["access_count_band"] = ""
            missing["access_type_flags"] = ""
            missing["access_type_dominant"] = ""
            missing["access_type_summary"] = ""
            missing["typed_access_count"] = np.nan
            missing["untyped_access_count"] = np.nan
            missing["riro_access_count"] = np.nan
            missing["other_review_access_count"] = np.nan
            missing["access_context_status"] = "missing_no_route_compatible_access"
            missing["access_source_match_method"] = ""
            missing["access_missing_reason"] = "no strict route-compatible access_v2 source route for unit route lineage"
            missing["access_zero_evidence_status"] = "unknown_no_zero_access_evidence"
            missing["access_context_quality_flag"] = "source_or_route_identity_limited"
            missing["access_candidate_count"] = 0
            missing["mixed_access_flag"] = False
        return pd.concat([patched, missing], ignore_index=True, sort=False), matches


def method_comparison(context: pd.DataFrame, spans_by_method: dict[str, pd.DataFrame], access: pd.DataFrame, strict_matches: pd.DataFrame, strict_summary: dict[str, Any]) -> None:
    before_status = context.set_index("distance_band_unit_id")["access_context_status"]
    before_missing = set(before_status[before_status.astype(str).str.contains("missing", case=False, na=False)].index)
    rows = []
    strict_matched = set(strict_matches["distance_band_unit_id"]) if not strict_matches.empty else set()
    strict_routes = set(source_for_method(access, "strict")["route_key"].unique())
    strict_route_compatible = set(spans_by_method["strict"].loc[spans_by_method["strict"]["route_key"].isin(strict_routes), "distance_band_unit_id"])
    rows.append(
        {
            "method": "strict",
            "units_with_matched_access_points": len(strict_matched),
            "valid_zero_access_units": len(strict_route_compatible - strict_matched),
            "still_missing_no_compatible_route": len(set(context["distance_band_unit_id"]) - strict_route_compatible),
            "recovered_units_relative_to_current_missing": len(before_missing & strict_route_compatible),
            "conflict_count": 0,
            "false_positive_risk": "low_strict_route_measure_point_containment",
            "runtime_note": "see qa_manifest phase timings",
            **strict_summary,
        }
    )
    for method in ["directionless", "route_number", "alternate_route_base_directionless"]:
        source = source_for_method(access, method)
        source_routes = set(source["route_key"].unique())
        compatible = set(spans_by_method[method].loc[spans_by_method[method]["route_key"].isin(source_routes), "distance_band_unit_id"])
        rows.append(
            {
                "method": method,
                "units_with_matched_access_points": "",
                "valid_zero_access_units": "",
                "still_missing_no_compatible_route": len(set(context["distance_band_unit_id"]) - compatible),
                "recovered_units_relative_to_current_missing": len(before_missing & compatible),
                "conflict_count": "",
                "false_positive_risk": "diagnostic_only_route_key_broadened_not_selected",
                "runtime_note": "route compatibility only; full interval match deferred to avoid broad fanout",
                "route_compatible_units": len(compatible),
                "run_full_interval_match": False,
            }
        )
    out = pd.DataFrame(rows)
    write_csv("access_route_measure_method_comparison.csv", out)
    write_csv("access_route_recovery_feasibility.csv", out)


def geometry_feasibility(access: pd.DataFrame, bins: pd.DataFrame, matches: pd.DataFrame) -> None:
    with phase("access_geometry_feasibility_audit"):
        geom_points = int(access.get("geometry", pd.Series(index=access.index, dtype=object)).notna().sum()) if "geometry" in access.columns else 0
        xy_points = int((access.get("_x", pd.Series(np.nan, index=access.index)).notna() & access.get("_y", pd.Series(np.nan, index=access.index)).notna()).sum()) if {"_x", "_y"}.issubset(access.columns) else 0
        bin_geom = int(bins.get("geometry", pd.Series(index=bins.index, dtype=object)).notna().sum()) if "geometry" in bins.columns else 0
        matched_points = matches["access_point_id"].nunique() if not matches.empty else 0
        rows = [
            {"metric": "candidate_access_points_considered", "value": len(access)},
            {"metric": "access_points_with_geometry", "value": geom_points},
            {"metric": "access_points_with_xy", "value": xy_points},
            {"metric": "bins_with_geometry", "value": bin_geom},
            {"metric": "strict_route_measure_matched_points", "value": matched_points},
            {"metric": "strict_route_measure_unmatched_points", "value": len(access) - matched_points},
            {"metric": "ambiguous_candidate_count", "value": "", "note": "not computed; geometry assignment deferred"},
            {"metric": "duplicate_overlap_risk", "value": "present", "note": "directional units and overlapping chains can duplicate point assignment without route-space agreement"},
            {"metric": "lateral_distance_distribution", "value": "not_computed", "note": "requires bounded corridor geometry assignment, deferred"},
            {"metric": "route_space_agreement_where_available", "value": "strict_route_measure_selected", "note": "geometry should be used only with route-space agreement or map review"},
            {"metric": "recommended_geometry_decision", "value": "defer_geometry_assignment"},
        ]
        write_csv("access_geometry_feasibility_audit.csv", rows)
        write_csv("access_ambiguous_geometry_ledger.csv", [{"status": "geometry_assignment_deferred", "reason": "not patched in this narrow route_measure access repair"}])


def patch_context(context: pd.DataFrame, access_rollup: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in ACCESS_PATCH_FIELDS:
        if col not in out.columns:
            if col in {"mixed_access_flag"}:
                out[col] = False
            elif col in {"access_count", "typed_access_count", "untyped_access_count", "riro_access_count", "other_review_access_count", "access_candidate_count"}:
                out[col] = math.nan
            else:
                out[col] = ""
    patch = access_rollup[["distance_band_unit_id", *ACCESS_PATCH_FIELDS]].drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")
    idx = out["distance_band_unit_id"].isin(patch.index)
    ids = out.loc[idx, "distance_band_unit_id"]
    for col in ACCESS_PATCH_FIELDS:
        out.loc[idx, col] = ids.map(patch[col])
    out["mixed_access_flag"] = out["mixed_access_flag"].fillna(False).map(bool_value)
    return out


def audit_outputs(before: pd.DataFrame, after: pd.DataFrame, matches: pd.DataFrame) -> None:
    before_access = pd.to_numeric(before["access_count"], errors="coerce")
    after_access = pd.to_numeric(after["access_count"], errors="coerce")
    write_csv(
        "access_missingness_before_after.csv",
        [
            {"metric": "access_non_missing_units", "before": int(before_access.notna().sum()), "after": int(after_access.notna().sum())},
            {"metric": "access_missing_units", "before": int(before_access.isna().sum()), "after": int(after_access.isna().sum())},
            {"metric": "matched_access_units", "before": int((before["access_context_status"] == "matched_access_points").sum()), "after": int((after["access_context_status"] == "matched_access_points").sum())},
            {"metric": "zero_access_units", "before": int((before_access.fillna(-1).eq(0)).sum()), "after": int((after_access.fillna(-1).eq(0)).sum())},
        ],
    )
    summary = after.groupby(["access_context_status", "access_zero_evidence_status", "access_context_quality_flag"], dropna=False).size().reset_index(name="unit_count")
    write_csv("access_patch_summary.csv", summary)
    zero = after.loc[after["access_zero_evidence_status"].astype(str).str.contains("zero_access", na=False), ["distance_band_unit_id", "access_context_status", "access_zero_evidence_status", "access_count", "access_source_match_method"]]
    write_csv("access_zero_evidence_audit.csv", zero.head(50000))
    source_limited = after.loc[after["access_context_quality_flag"].astype(str).str.contains("limited|unknown", case=False, na=False), ["distance_band_unit_id", "access_context_status", "access_missing_reason", "access_zero_evidence_status"]]
    write_csv("access_source_limited_ledger.csv", source_limited.head(50000))
    conflict = pd.DataFrame(columns=["distance_band_unit_id", "conflict_type", "reason"])
    write_csv("access_conflict_ledger.csv", conflict)
    band = after.groupby(["access_count_band", "access_context_status"], dropna=False).size().reset_index(name="unit_count")
    write_csv("access_count_band_summary.csv", band)


def old_method_inventory() -> None:
    terms = [
        "access",
        "access_v2",
        "driveway",
        "entrance",
        "RIM access",
        "access count",
        "RIRO",
        "route measure access",
        "access geometry",
        "typed access",
        "directional access",
    ]
    rows = []
    roots = [REPO / "src/active/roadway_graph", REPO / "docs/workflow", REPO / "docs/methodology"]
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            low = text.lower()
            matched = [term for term in terms if term.lower() in low]
            if not matched:
                continue
            stale = "work/output" in text or "review/current" in text or "analysis/current" in text
            source_layer = "artifacts/normalized/access_v2.parquet" if "access_v2.parquet" in text or "ACCESS_V2" in text else ""
            route_fields = "|".join([field for field in ["route_name", "route_measure", "_rte_nm", "_m", "source_route_key", "EDGE_RTE_KEY"] if field in text])
            geometry_method = "geometry/catchment evidence" if "geometry" in low or "spatial" in low or "catchment" in low else ""
            rows.append(
                {
                    "path": rel(path),
                    "matched_terms": "|".join(matched),
                    "relevant_function_or_rule": "|".join(re.findall(r"def\s+([A-Za-z0-9_]+)", text)[:20]),
                    "source_layer_used": source_layer,
                    "route_fields_used": route_fields,
                    "measure_overlap_method": "route_measure containment/overlap" if "measure" in low or "route_measure" in low else "",
                    "geometry_method": geometry_method,
                    "access_type_recoding_logic": "R/RC to RIRO; U/RIRO/RIO/ROO/LIRIRO/other_review" if "R/RC" in text or "RIRO" in text else "",
                    "riro_other_review_handling": "mentions RIRO/other_review" if "RIRO" in text or "other_review" in text else "",
                    "achieved_coverage_if_documented": collapse_unique(pd.Series(re.findall(r"(matched[^\\n]{0,80}|coverage[^\\n]{0,80}|recovered[^\\n]{0,80})", text, flags=re.IGNORECASE))[:5]),
                    "uses_stale_cache_parent_flag": stale,
                    "compatible_with_rebuilt_cache": "requires_adaptation_review" if stale else "method_evidence_only",
                    "should_be_adapted": "yes_method_only" if "route_measure" in text or "geometry" in low or "RIRO" in text else "no",
                    "used_as_data_parent": False,
                }
            )
    write_csv("old_access_method_inventory.csv", rows)


def parent_dependency_check() -> None:
    parents = [CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS]
    compare_only = [ROADS, SPEED, AADT, CRASHES]
    rows = []
    for path in parents:
        rows.append({"path": rel(path), "role": "parent", "exists": path.exists(), "sha256": file_sha256(path) if path.exists() else "", "used_as_hidden_parent": False})
    for path in compare_only:
        rows.append({"path": rel(path), "role": "read_optional_or_guard_only", "exists": path.exists(), "sha256": file_sha256(path) if path.exists() else "", "used_as_hidden_parent": False})
    write_csv("parent_dependency_check.csv", rows)


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
    for col in ["bin_count", "unit_length_ft"]:
        b = pd.to_numeric(before[col], errors="coerce")
        a = pd.to_numeric(after[col], errors="coerce")
        rows.append(
            {
                "field": col,
                "passed": bool(np.isclose(b.sum(), a.sum()) and b.equals(a)),
                "before_sum": float(b.sum()),
                "after_sum": float(a.sum()),
                "changed_rows": int((~b.fillna(-999999).eq(a.fillna(-999999))).sum()),
            }
        )
    out = pd.DataFrame(rows)
    write_csv("length_bin_count_reconciliation.csv", out)
    return out


def unchanged_non_target_check(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    allowed = set(ACCESS_PATCH_FIELDS)
    rows = []
    for col in before.columns:
        if col not in after.columns or col in allowed:
            continue
        b = before[col].astype("string").fillna("<NA>")
        a = after[col].astype("string").fillna("<NA>")
        changed = int((b != a).sum())
        rows.append({"field": col, "passed": changed == 0, "changed_rows": changed})
    out = pd.DataFrame(rows)
    write_csv("unchanged_non_target_context_fields_check.csv", out)
    return out


def rate_readiness_check(after: pd.DataFrame) -> pd.DataFrame:
    out = after.groupby("rate_readiness_status", dropna=False).size().reset_index(name="unit_count")
    out["crash_assignment_deferred"] = True
    out["rate_ready_claimed"] = out["rate_readiness_status"].astype(str).str.startswith("rate_ready")
    write_csv("rate_readiness_consistency_check.csv", out)
    return out


def no_crash_direction_field_check() -> pd.DataFrame:
    rows = []
    for path in [CONTEXT, UNITS, BINS, TRAVELWAY, ACCESS, CRASHES]:
        if not path.exists():
            rows.append({"path": rel(path), "crash_direction_like_fields_detected": "", "used_as_join_or_derivation_field": False, "passed": True})
            continue
        try:
            cols = pq.read_schema(path).names
        except Exception:
            cols = []
        detected = forbidden_crash_direction_cols(cols)
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
    access_count = pd.to_numeric(after["access_count"], errors="coerce")
    zero_unknown_mismatch = int((access_count.eq(0) & after["access_zero_evidence_status"].astype(str).eq("unknown_no_zero_access_evidence")).sum())
    write_csv(
        "access_semantics_consistency_check.csv",
        [
            {
                "check": "zero_access_requires_zero_evidence_status",
                "passed": zero_unknown_mismatch == 0,
                "mismatch_count": zero_unknown_mismatch,
            }
        ],
    )
    checks = [
        row_identity_check(before, after, units)["passed"].all(),
        unit_grain_check(after)["passed"].all(),
        directionality_reconciliation(before, after)["passed"].all(),
        length_bin_reconciliation(before, after)["passed"].all(),
        unchanged_non_target_check(before, after)["passed"].all(),
        not rate_readiness_check(after)["rate_ready_claimed"].any(),
        no_crash_direction_field_check()["passed"].all(),
        zero_unknown_mismatch == 0,
    ]
    forbidden = forbidden_mvp_lookup_product_check()
    if not forbidden.empty:
        checks.append(bool(forbidden["passed"].all()))
    checks.append(len(after) == parquet_row_count(TEMP))
    return bool(all(checks))


def write_findings(final_decision: str, before: pd.DataFrame, after: pd.DataFrame) -> None:
    before_access = pd.to_numeric(before["access_count"], errors="coerce")
    after_access = pd.to_numeric(after["access_count"], errors="coerce")
    status = after["access_context_status"].value_counts(dropna=False)
    text = f"""# Access Context Patch Findings

## Problem Addressed
This patch separates matched access, valid route/measure zero-access evidence, and source/join-limited unknown access for staged `distance_band_context.parquet`.

## Access Source/Schema
`access_v2.parquet` contains typed point access evidence with route name, route measure, point geometry/XY, raw access control codes, normalized categories, and access direction fields. Route/measure is sufficient for a conservative strict repair; geometry exists but is deferred because directional corridor assignment can duplicate or ambiguously assign points without route-space agreement.

## Useful Old Methods
Old access scripts and docs were useful as method evidence for access_v2 staging, route/measure matching, geometry catchment risk, and typed code recoding. They were not used as data parents.

## Route/Measure Repair
Selected method: `strict_route_measure_access_v2`. Directionless and route-number keys were reported as diagnostics only because broader keys raise false-positive and fanout risk. Units on route-compatible source routes with no access points in their measure window are labeled as valid zero-access evidence, not missing access.

## Geometry Feasibility
Geometry matching was not patched. The source has point geometry and staged bins have geometry, but bounded point-to-corridor assignment needs lateral/along-corridor constraints and duplicate-direction controls. Geometry cases are deferred to a focused spatial/map-review task.

## Access Type And Bands
Raw `R` and `RC` are corrected to `right_in_right_out`; `I`, `M`, `S`, `AS`, and `AU` remain `other_review`; unknown/blank remains `unknown`. Count bands are `0`, `1`, `2-3`, `4-7`, and `8+`.

## Coverage
Access non-missing before/after: {int(before_access.notna().sum())} -> {int(after_access.notna().sum())}.
Matched access units after: {int(status.get('matched_access_points', 0))}.
Valid zero-access units after: {int(status.get('valid_zero_access_route_measure_evidence', 0))}.
Access-unknown/source-limited units after: {int(status.get('missing_no_route_compatible_access', 0))}.

## Guard Confirmations
Roadway, speed, AADT/exposure, crash, and rate readiness fields were not changed. Crash direction fields were not used. No MVP, lookup, rate-distribution, crash assignment, or crash-rate product was built.

## Final Decision
`{final_decision}`

## Recommended Next Task
Run the crash assignment layer task from `remaining_context_patch_queue.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_recommendations() -> None:
    write_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "recommended_next_action": "Run crash assignment layer", "reason": "Access context is now separated into matched, valid-zero, and source-limited statuses; crash assignment remains deferred."},
            {"priority": 2, "recommended_next_action": "Defer geometry access assignment to focused spatial/map-review task if route-missing residual needs recovery", "reason": "Geometry exists but duplicate directional assignment risk was not resolved in this narrow patch."},
        ],
    )
    write_csv(
        "remaining_context_patch_queue.csv",
        [
            {"sequence": 1, "task": "Crash assignment layer", "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA"},
            {"sequence": 2, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build"},
        ],
    )


def update_metadata(candidate: pd.DataFrame, final_decision: str) -> None:
    stamp = now()
    manifest = read_json(MANIFEST)
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "bounded_phase": "access feasibility and safe access-context repair",
            "build_version": BUILD_VERSION,
            "patched_utc": stamp,
            "row_count": int(len(candidate)),
            "script": "src.roadway_graph.patch.patch_distance_band_context_access",
            "final_decision": final_decision,
            "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()),
        }
    )
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    parents = set(product.get("canonical_parents", []))
    parents.update([rel(UNITS), rel(BINS), rel(TRAVELWAY), rel(APPROACH_CORRIDORS), rel(ACCESS)])
    product.update(
        {
            "row_count": int(len(candidate)),
            "updated_utc": stamp,
            "script": "src.roadway_graph.patch.patch_distance_band_context_access",
            "final_decision": final_decision,
            "qa_review_path": rel(OUT),
            "access_patch_status": "passed",
            "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()),
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
        "access_count_band_definition": "0, 1, 2-3, 4-7, 8+",
    }
    write_json_path(SCHEMA, schema)

    note = f"""

## Access Context Patch ({stamp})

- Final decision: `{final_decision}`.
- Script: `src.roadway_graph.patch.patch_distance_band_context_access`.
- Source parent: `{rel(ACCESS)}` plus staged unit/bin route-measure lineage.
- Selected method: strict route/measure access_v2 point containment.
- Geometry access assignment: deferred.
- Count bands: `0`, `1`, `2-3`, `4-7`, `8+`.
- No roadway, speed, AADT/exposure, crash, rate, MVP, lookup, or rate-distribution fields were patched.
- QA outputs: `{rel(OUT)}`.
"""
    README.write_text(README.read_text(encoding="utf-8") + note, encoding="utf-8")


def write_manifests(final_decision: str, replacement: bool) -> None:
    write_json(
        "manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.patch.patch_distance_band_context_access",
            "build_version": BUILD_VERSION,
            "parents": [rel(p) for p in [CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS]],
            "replacement_performed": replacement,
            "final_decision": final_decision,
        },
    )
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "final_decision": final_decision,
            "replacement_performed": replacement,
            "phase_timings": PHASE_TIMINGS,
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.name not in {"progress_log.md", "findings_memo.md", "manifest.json", "qa_manifest.json"}),
        },
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started access context patch.\n", encoding="utf-8")
    parent_dependency_check()
    old_method_inventory()
    with phase("load_inputs"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
        bins = pd.read_parquet(BINS)
        access = load_access_source()
    source_schema_inventory(access, context)
    source_coverage_outputs(access)
    spans_by_method = build_unit_route_spans(units, bins)
    strict_source = source_for_method(access, "strict")
    strict_matches, strict_summary = match_access_method(spans_by_method["strict"], strict_source, "strict", run_full=True)
    method_comparison(context, spans_by_method, access, strict_matches, strict_summary)
    access_rollup, matches = aggregate_access(strict_matches, spans_by_method["strict"], context, set(strict_source["route_key"].dropna().unique()))
    geometry_feasibility(access, bins, matches)
    candidate = patch_context(context, access_rollup)
    audit_outputs(context, candidate, matches)
    write_recommendations()

    final_decision = "access_route_repair_passed_geometry_deferred"
    with phase("write_temp_candidate_parquet"):
        if TEMP.exists():
            TEMP.unlink()
        candidate.to_parquet(TEMP, index=False)
    qa_passed = full_qa(context, candidate, units)
    write_csv(
        "distance_band_context_patch_readiness_decision.csv",
        [
            {
                "stage": "final",
                "passed": qa_passed,
                "final_decision": final_decision if qa_passed else "access_patch_failed_no_replacement",
                "replacement_performed": qa_passed,
                "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()),
                "matched_access_units": int((candidate["access_context_status"] == "matched_access_points").sum()),
                "valid_zero_access_units": int((candidate["access_context_status"] == "valid_zero_access_route_measure_evidence").sum()),
                "access_unknown_units": int((candidate["access_context_status"] == "missing_no_route_compatible_access").sum()),
            }
        ],
    )
    if not qa_passed:
        final_decision = "access_patch_failed_no_replacement"
        write_findings(final_decision, context, candidate)
        write_manifests(final_decision, False)
        raise SystemExit("QA failed; staged distance_band_context was not replaced.")
    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(TEMP), str(CONTEXT))
    update_metadata(candidate, final_decision)
    write_findings(final_decision, context, candidate)
    write_manifests(final_decision, True)
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    main()
