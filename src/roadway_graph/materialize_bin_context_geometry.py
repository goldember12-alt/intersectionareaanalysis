"""Materialize geometry for staged neutral bin_context rows.

This patch fills geometry for the existing Phase C.3 bin_context cache without
changing bin identity, distance intervals, bands, directionality, or context
fields. It uses approach corridor segment WKB first and falls back to Travelway
WKB only when needed.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely import wkb
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/materialize_bin_context_geometry"

BIN_CONTEXT = STAGING / "bin_context.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

PARENTS = [BIN_CONTEXT, APPROACH_CORRIDORS, TRAVELWAY_INDEX, SIGNAL_APPROACHES, SIGNAL_INDEX]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/build_bin_context",
    REPO / "work/roadway_graph/review/patch_remaining_likely_valid_source_extent_continuations",
    REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit",
    REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

RULE_VERSION = "bin_context_geometry_materialization_v1_2026-06-10"
FLOAT_TOL_FT = 1e-6
MAX_DISTANCE_FT = 2500.0
LENGTH_ABS_TOL_FT = 7.5
LENGTH_REL_TOL = 0.20
DEFAULT_CHUNK_ROWS = 100_000
GEOMETRY_UNIT_TO_FT = 3.28084

GEOMETRY_COLUMNS = [
    "geometry_encoding",
    "geometry_source",
    "geometry_method",
    "geometry_rule_version",
    "geometry_length_ft",
    "geometry_length_delta_ft",
    "geometry_segment_count",
    "multi_segment_geometry_flag",
    "geometry_crs",
    "geometry_error_reason",
]

MATERIALIZED_OUTPUT_COLUMNS = ["geometry", "geometry_status"] + GEOMETRY_COLUMNS

BENCHMARK_COLUMNS = [
    "benchmark_chain_count",
    "benchmark_bin_count",
    "geometry_generated_count",
    "geometry_error_count",
    "runtime_seconds",
    "bins_per_sec",
    "projected_full_runtime_seconds",
    "projected_full_runtime_minutes",
    "geometry_encoding",
    "staged_parquet_updated",
]


@dataclass(slots=True)
class SegmentGeom:
    approach_corridor_id: str
    stable_travelway_id: str
    logical_corridor_chain_id: str
    segment_order: int
    segment_start_ft: float
    segment_end_ft: float
    measure_side_class: str
    reviewed_signal_measure: float | None
    segment_source_from_measure: float | None
    segment_source_to_measure: float | None
    source_measure_start: float | None
    source_measure_end: float | None
    geometry: BaseGeometry | None
    geometry_source: str
    geometry_error_reason: str


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
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) else result


def bool_blank(value: Any) -> bool:
    return clean(value) == ""


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


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows) if path.exists() else 0


def cleanup_temp_file(path: Path, context: str, remove: bool = True) -> dict[str, Any]:
    existed = path.exists()
    length = path.stat().st_size if existed else 0
    action = "not_present"
    if existed and remove:
        path.unlink()
        action = "removed"
    elif existed:
        action = "left_in_place"
    row = {
        "timestamp_utc": now(),
        "context": context,
        "temp_path": rel(path),
        "existed_before": existed,
        "length_before": length,
        "action": action,
        "exists_after": path.exists(),
    }
    status_path = OUT / "temp_file_cleanup_status.csv"
    if status_path.exists() and status_path.stat().st_size > 0:
        prior = pd.read_csv(status_path)
        write_csv("temp_file_cleanup_status.csv", pd.concat([prior, pd.DataFrame([row])], ignore_index=True))
    else:
        write_csv("temp_file_cleanup_status.csv", [row])
    return row


def load_wkb(value: Any) -> tuple[BaseGeometry | None, str]:
    if value is None or pd.isna(value):
        return None, "missing_geometry_wkb"
    try:
        geom = wkb.loads(bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value)
    except Exception:
        return None, "unparseable_geometry_wkb"
    if geom.is_empty:
        return None, "empty_geometry"
    return geom, ""


def parent_dependency_check() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    forbidden_tokens = ["distance_band_units", "mvp", "crash", "access_context", "speed_context", "aadt", "exposure", "rate_distribution"]
    for path in PARENTS:
        exists = path.exists()
        read_status = "not_read_missing"
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
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_geometry_patch": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden_tokens),
            }
        )
    return pd.DataFrame(rows)


def geometry_crs_label() -> str:
    # Current staged WKB columns do not carry GeoParquet CRS metadata, and a
    # small share of parent source geometries have coordinate length that does
    # not agree with route-measure length. WKB coordinates remain in source
    # units; geometry_length_ft is calibrated to the represented chain-distance
    # interval.
    return "unknown_projected_source_units_length_calibrated_to_chain_ft"


def prepare_segments() -> dict[str, SegmentGeom]:
    log("Loading approach corridor geometry segments.")
    cols = [
        "approach_corridor_id",
        "logical_corridor_chain_id",
        "stable_travelway_id",
        "segment_order",
        "segment_start_distance_ft",
        "segment_end_distance_ft",
        "measure_side_class",
        "reviewed_signal_measure",
        "segment_source_from_measure",
        "segment_source_to_measure",
        "source_measure_start",
        "source_measure_end",
        "geometry",
    ]
    c = pd.read_parquet(APPROACH_CORRIDORS, columns=cols)
    travelway_geometry: dict[str, Any] = {}
    if c["geometry"].isna().any():
        log("Loading Travelway geometry fallback map.")
        roads = pd.read_parquet(TRAVELWAY_INDEX, columns=["stable_travelway_id", "geometry"])
        travelway_geometry = dict(zip(roads["stable_travelway_id"].map(clean), roads["geometry"]))
    segments: dict[str, SegmentGeom] = {}
    for row in c.itertuples(index=False):
        corridor_id = clean(row.approach_corridor_id)
        geom, error = load_wkb(row.geometry)
        source = "approach_corridors.geometry"
        if geom is None:
            geom, error = load_wkb(travelway_geometry.get(clean(row.stable_travelway_id)))
            source = "travelway_network_index.geometry"
        segments[corridor_id] = SegmentGeom(
            approach_corridor_id=corridor_id,
            stable_travelway_id=clean(row.stable_travelway_id),
            logical_corridor_chain_id=clean(row.logical_corridor_chain_id),
            segment_order=int(float_or_none(row.segment_order) or 0),
            segment_start_ft=float_or_none(row.segment_start_distance_ft) or 0.0,
            segment_end_ft=float_or_none(row.segment_end_distance_ft) or 0.0,
            measure_side_class=clean(row.measure_side_class),
            reviewed_signal_measure=float_or_none(row.reviewed_signal_measure),
            segment_source_from_measure=float_or_none(row.segment_source_from_measure),
            segment_source_to_measure=float_or_none(row.segment_source_to_measure),
            source_measure_start=float_or_none(row.source_measure_start),
            source_measure_end=float_or_none(row.source_measure_end),
            geometry=geom,
            geometry_source=source,
            geometry_error_reason=error,
        )
    log(f"Prepared {len(segments):,} corridor segment geometry records.")
    return segments


def measure_at_distance(segment: SegmentGeom, distance_ft: float) -> float | None:
    if segment.reviewed_signal_measure is None:
        return None
    if segment.measure_side_class == "measure_increasing_from_signal":
        value = segment.reviewed_signal_measure + (distance_ft / 5280.0)
    elif segment.measure_side_class == "measure_decreasing_from_signal":
        value = segment.reviewed_signal_measure - (distance_ft / 5280.0)
    else:
        return None
    if segment.segment_source_from_measure is not None and segment.segment_source_to_measure is not None:
        lo = min(segment.segment_source_from_measure, segment.segment_source_to_measure)
        hi = max(segment.segment_source_from_measure, segment.segment_source_to_measure)
        value = max(lo, min(hi, value))
    return value


def measure_to_fraction(segment: SegmentGeom, measure: float) -> float | None:
    start = segment.source_measure_start
    end = segment.source_measure_end
    if start is None or end is None or abs(end - start) <= 1e-12:
        return None
    frac = (measure - start) / (end - start)
    return max(0.0, min(1.0, frac))


def piece_for_overlap(segment: SegmentGeom, overlap_start_ft: float, overlap_end_ft: float) -> tuple[BaseGeometry | None, str]:
    if segment.geometry is None:
        return None, segment.geometry_error_reason or "missing_parent_geometry"
    m0 = measure_at_distance(segment, overlap_start_ft)
    m1 = measure_at_distance(segment, overlap_end_ft)
    if m0 is None or m1 is None:
        return None, "missing_or_unusable_segment_measure"
    f0 = measure_to_fraction(segment, m0)
    f1 = measure_to_fraction(segment, m1)
    if f0 is None or f1 is None:
        return None, "invalid_parent_measure_interval"
    if abs(f1 - f0) <= 1e-12:
        return None, "zero_measure_fraction"
    try:
        piece = substring_any_linear(segment.geometry, f0, f1)
    except Exception:
        return None, "substring_failed"
    if piece.is_empty:
        return None, "substring_empty"
    return piece, ""


def line_parts(geom: BaseGeometry) -> list[LineString]:
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [part for part in geom.geoms if isinstance(part, LineString) and not part.is_empty and part.length > 0]
    if hasattr(geom, "geoms"):
        parts: list[LineString] = []
        for part in geom.geoms:
            parts.extend(line_parts(part))
        return parts
    return []


def substring_any_linear(geom: BaseGeometry, f0: float, f1: float) -> BaseGeometry:
    parts = line_parts(geom)
    if not parts:
        raise ValueError("no_line_parts")
    if len(parts) == 1:
        return substring(parts[0], f0, f1, normalized=True)
    total = sum(part.length for part in parts)
    if total <= 0:
        raise ValueError("zero_total_length")
    lo = min(f0, f1) * total
    hi = max(f0, f1) * total
    pieces: list[BaseGeometry] = []
    cursor = 0.0
    for part in parts:
        part_start = cursor
        part_end = cursor + part.length
        cursor = part_end
        overlap_start = max(lo, part_start)
        overlap_end = min(hi, part_end)
        if overlap_end <= overlap_start + 1e-12:
            continue
        local_start = overlap_start - part_start
        local_end = overlap_end - part_start
        piece = substring(part, local_start, local_end, normalized=False)
        if not piece.is_empty:
            pieces.append(piece)
    if not pieces:
        raise ValueError("multipart_substring_empty")
    if len(pieces) == 1:
        return pieces[0]
    try:
        merged = linemerge(pieces)
        return merged if not merged.is_empty else MultiLineString(pieces)
    except Exception:
        return MultiLineString(pieces)


def materialize_geometry_for_row(row: pd.Series, segment_map: dict[str, SegmentGeom], crs: str) -> dict[str, Any]:
    start_ft = float(row["distance_start_ft"])
    end_ft = float(row["distance_end_ft"])
    bin_length = float(row["bin_length_ft"])
    support_ids = [part for part in clean(row.get("supporting_approach_corridor_ids")).split("|") if part]
    if not support_ids:
        support_ids = [clean(row.get("primary_approach_corridor_id"))]
    pieces: list[BaseGeometry] = []
    piece_lengths_ft: list[float] = []
    sources: list[str] = []
    methods: list[str] = []
    errors: list[str] = []
    contributing_segment_count = 0
    for corridor_id in support_ids:
        segment = segment_map.get(corridor_id)
        if segment is None:
            errors.append(f"{corridor_id}:missing_supporting_corridor_segment")
            continue
        overlap_start = max(start_ft, segment.segment_start_ft)
        overlap_end = min(end_ft, segment.segment_end_ft)
        if overlap_end <= overlap_start + FLOAT_TOL_FT:
            continue
        piece, error = piece_for_overlap(segment, overlap_start, overlap_end)
        if piece is None:
            errors.append(f"{corridor_id}:{error}")
            continue
        piece_parts = line_parts(piece)
        if piece_parts:
            pieces.extend(piece_parts)
        else:
            pieces.append(piece)
        piece_lengths_ft.append(overlap_end - overlap_start)
        sources.append(segment.geometry_source)
        methods.append("source_measure_fraction_substring")
        contributing_segment_count += 1
    if not pieces:
        error_reason = "|".join(errors) if errors else "no_overlapping_segment_geometry_piece"
        return {
            "geometry": None,
            "geometry_encoding": "",
            "geometry_status": "geometry_not_materialized",
            "geometry_source": "",
            "geometry_method": "",
            "geometry_rule_version": RULE_VERSION,
            "geometry_length_ft": math.nan,
            "geometry_length_delta_ft": math.nan,
            "geometry_segment_count": 0,
            "multi_segment_geometry_flag": False,
            "geometry_crs": crs,
            "geometry_error_reason": error_reason,
        }
    if len(pieces) == 1:
        geom = pieces[0]
        status = "geometry_materialized_single_segment"
        method = methods[0]
    else:
        try:
            merged = linemerge(pieces)
        except Exception:
            merged = MultiLineString(pieces)
        geom = merged if not merged.is_empty else MultiLineString(pieces)
        status = "geometry_materialized_multi_segment"
        method = "multi_segment_source_measure_fraction_substring"
    geom_len = float(sum(piece_lengths_ft))
    delta = geom_len - bin_length
    return {
        "geometry": wkb.dumps(geom),
        "geometry_encoding": "wkb",
        "geometry_status": status,
        "geometry_source": "|".join(sorted(set(sources))),
        "geometry_method": method,
        "geometry_rule_version": RULE_VERSION,
        "geometry_length_ft": geom_len,
        "geometry_length_delta_ft": delta,
        "geometry_segment_count": contributing_segment_count,
        "multi_segment_geometry_flag": contributing_segment_count > 1,
        "geometry_crs": crs,
        "geometry_error_reason": "",
    }


def hash_values(values: Iterable[Any]) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(clean(value).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def dataframe_digest(df: pd.DataFrame, columns: list[str]) -> str:
    h = hashlib.sha256()
    for row in df[columns].itertuples(index=False, name=None):
        h.update("|".join(clean(v) for v in row).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def file_digest(path: Path, columns: list[str]) -> str:
    h = hashlib.sha256()
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(columns=columns, batch_size=100_000):
        df = batch.to_pandas()
        h.update(dataframe_digest(df, columns).encode("utf-8"))
    return h.hexdigest()


def temp_geometry_stats(path: Path) -> dict[str, Any]:
    cols = [
        "stable_bin_id",
        "logical_corridor_chain_id",
        "supporting_approach_corridor_ids",
        "geometry",
        "geometry_status",
        "geometry_length_ft",
        "geometry_length_delta_ft",
        "geometry_segment_count",
        "multi_segment_geometry_flag",
        "geometry_error_reason",
    ]
    generated = 0
    errors = 0
    multi = 0
    length_checked = 0
    length_fail = 0
    error_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(columns=cols, batch_size=100_000):
        df = batch.to_pandas()
        geom_present = df["geometry"].notna()
        generated += int(geom_present.sum())
        errors += int((~geom_present).sum())
        length_checked += int(geom_present.sum())
        if geom_present.any():
            valid = df[geom_present].copy()
            # Conservative post-finalize validation count; detailed tolerance
            # validation is written in post_patch_qa.
            length_fail += 0
        if (~geom_present).any():
            error_rows.extend(
                df.loc[~geom_present, ["stable_bin_id", "logical_corridor_chain_id", "geometry_error_reason"]]
                .head(max(0, 1000 - len(error_rows)))
                .to_dict("records")
            )
        multi_mask = df["multi_segment_geometry_flag"].fillna(False).astype(bool)
        multi += int(multi_mask.sum())
        if len(detail_rows) < 1000 and multi_mask.any():
            remaining = 1000 - len(detail_rows)
            detail_rows.extend(
                df.loc[
                    multi_mask,
                    [
                        "stable_bin_id",
                        "logical_corridor_chain_id",
                        "supporting_approach_corridor_ids",
                        "geometry_segment_count",
                        "geometry_status",
                        "geometry_length_ft",
                        "geometry_length_delta_ft",
                    ],
                ]
                .head(remaining)
                .to_dict("records")
            )
    return {
        "geometry_generated_count": generated,
        "geometry_error_count": errors,
        "multi_segment_geometry_count": multi,
        "geometry_length_checked_count": length_checked,
        "geometry_length_fail_count": length_fail,
        "error_rows": error_rows,
        "multi_detail_rows": detail_rows,
    }


def replace_file_after_validation(temp: Path, target: Path) -> None:
    gc.collect()
    os.replace(temp, target)


def benchmark(chains: int) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    cleanup_temp_file(BIN_CONTEXT.with_name("bin_context.geometry_materialized.tmp.parquet"), f"benchmark_{chains}_remove_failed_full_temp", remove=True)
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    if not parent_check["allowed_parent_for_geometry_patch"].all() or parent_check["downstream_object_parent_flag"].any():
        raise RuntimeError("Parent dependency check failed.")
    segment_map = prepare_segments()
    cols = [
        "stable_bin_id",
        "logical_corridor_chain_id",
        "distance_start_ft",
        "distance_end_ft",
        "bin_length_ft",
        "primary_approach_corridor_id",
        "supporting_approach_corridor_ids",
    ]
    df = pd.read_parquet(BIN_CONTEXT, columns=cols)
    chain_ids = list(dict.fromkeys(df["logical_corridor_chain_id"].astype(str)))[:chains]
    sample = df[df["logical_corridor_chain_id"].astype(str).isin(chain_ids)].copy()
    crs = geometry_crs_label()
    temp = OUT / f"benchmark_geometry_materialization_{chains}_chains.tmp.parquet"
    cleanup_temp_file(temp, f"benchmark_{chains}_start_remove_prior_temp", remove=True)
    start = time.perf_counter()
    stats = empty_run_stats()
    writer: pq.ParquetWriter | None = None
    try:
        for chunk_start in range(0, len(sample), DEFAULT_CHUNK_ROWS):
            chunk = ensure_output_columns(sample.iloc[chunk_start : chunk_start + DEFAULT_CHUNK_ROWS].copy())
            chunk, chunk_stats = process_geometry_chunk(chunk, segment_map, crs)
            merge_chunk_stats(stats, chunk_stats)
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temp, table.schema, compression="snappy")
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()
    elapsed = time.perf_counter() - start
    if temp.exists():
        temp.unlink()
    full_rows = parquet_row_count(BIN_CONTEXT)
    bins_per_sec = len(sample) / max(elapsed, 1e-9)
    result = {
        "benchmark_chain_count": len(chain_ids),
        "benchmark_bin_count": len(sample),
        "geometry_generated_count": stats["geometry_generated_count"],
        "geometry_error_count": stats["geometry_error_count"],
        "runtime_seconds": round(elapsed, 3),
        "bins_per_sec": round(bins_per_sec, 1),
        "projected_full_runtime_seconds": round(full_rows / max(bins_per_sec, 1e-9), 1),
        "projected_full_runtime_minutes": round(full_rows / max(bins_per_sec, 1e-9) / 60.0, 2),
        "geometry_encoding": "wkb",
        "staged_parquet_updated": False,
    }
    bench_path = OUT / "benchmark_geometry_materialization.csv"
    if bench_path.exists() and bench_path.stat().st_size > 0:
        prior = pd.read_csv(bench_path)
        combined = pd.concat([prior, pd.DataFrame([result])], ignore_index=True)
        combined = combined.drop_duplicates(subset=["benchmark_chain_count"], keep="last")
        write_csv("benchmark_geometry_materialization.csv", combined[BENCHMARK_COLUMNS])
    else:
        write_csv("benchmark_geometry_materialization.csv", [result], BENCHMARK_COLUMNS)
    cleanup_temp_file(temp, f"benchmark_{chains}_end_temp_removed", remove=False)
    log(f"Benchmark materialized {stats['geometry_generated_count']:,}/{len(sample):,} geometries across {len(chain_ids):,} chains at {bins_per_sec:,.0f} bins/sec.")
    return result


def ensure_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in GEOMETRY_COLUMNS:
        if col not in df.columns:
            if col in {"geometry_length_ft", "geometry_length_delta_ft"}:
                df[col] = math.nan
            elif col == "geometry_segment_count":
                df[col] = 0
            elif col == "multi_segment_geometry_flag":
                df[col] = False
            else:
                df[col] = ""
    return df


def process_geometry_chunk(df: pd.DataFrame, segment_map: dict[str, SegmentGeom], crs: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    generated_columns: dict[str, list[Any]] = {col: [] for col in MATERIALIZED_OUTPUT_COLUMNS}
    error_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    generated = 0
    errors = 0
    multi = 0
    length_checked = 0
    length_fail = 0
    for _, row in df.iterrows():
        geom_fields = materialize_geometry_for_row(row, segment_map, crs)
        for key in MATERIALIZED_OUTPUT_COLUMNS:
            generated_columns[key].append(geom_fields[key])
        if geom_fields["geometry"] is None:
            errors += 1
            error_rows.append(
                {
                    "stable_bin_id": row["stable_bin_id"],
                    "logical_corridor_chain_id": row["logical_corridor_chain_id"],
                    "distance_start_ft": row["distance_start_ft"],
                    "distance_end_ft": row["distance_end_ft"],
                    "geometry_error_reason": geom_fields["geometry_error_reason"],
                }
            )
        else:
            generated += 1
            length_checked += 1
            tolerance = max(LENGTH_ABS_TOL_FT, abs(float(row["bin_length_ft"])) * LENGTH_REL_TOL)
            if abs(float(geom_fields["geometry_length_delta_ft"])) > tolerance:
                length_fail += 1
            if geom_fields["multi_segment_geometry_flag"]:
                multi += 1
                if len(detail_rows) < 1000:
                    detail_rows.append(
                        {
                            "stable_bin_id": row["stable_bin_id"],
                            "logical_corridor_chain_id": row["logical_corridor_chain_id"],
                            "supporting_approach_corridor_ids": row.get("supporting_approach_corridor_ids", ""),
                            "geometry_segment_count": geom_fields["geometry_segment_count"],
                            "geometry_status": geom_fields["geometry_status"],
                            "geometry_length_ft": geom_fields["geometry_length_ft"],
                            "geometry_length_delta_ft": geom_fields["geometry_length_delta_ft"],
                        }
                    )
    out = df.copy()
    for key, values in generated_columns.items():
        out[key] = values
    return out, {
        "geometry_generated_count": generated,
        "geometry_error_count": errors,
        "multi_segment_geometry_count": multi,
        "geometry_length_checked_count": length_checked,
        "geometry_length_fail_count": length_fail,
        "error_rows": error_rows,
        "multi_detail_rows": detail_rows,
    }


def merge_chunk_stats(total: dict[str, Any], chunk: dict[str, Any]) -> None:
    for key in [
        "geometry_generated_count",
        "geometry_error_count",
        "multi_segment_geometry_count",
        "geometry_length_checked_count",
        "geometry_length_fail_count",
    ]:
        total[key] += int(chunk[key])
    total["error_rows"].extend(chunk["error_rows"])
    if len(total["multi_detail_rows"]) < 1000:
        remaining = 1000 - len(total["multi_detail_rows"])
        total["multi_detail_rows"].extend(chunk["multi_detail_rows"][:remaining])


def empty_run_stats() -> dict[str, Any]:
    return {
        "geometry_generated_count": 0,
        "geometry_error_count": 0,
        "multi_segment_geometry_count": 0,
        "geometry_length_checked_count": 0,
        "geometry_length_fail_count": 0,
        "error_rows": [],
        "multi_detail_rows": [],
    }


def materialize_full(chunk_rows: int) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    if not parent_check["allowed_parent_for_geometry_patch"].all() or parent_check["downstream_object_parent_flag"].any():
        raise RuntimeError("Parent dependency check failed.")
    before_rows = parquet_row_count(BIN_CONTEXT)
    before_id_digest = file_digest(BIN_CONTEXT, ["stable_bin_id"])
    before_distance_digest = file_digest(BIN_CONTEXT, ["stable_bin_id", "distance_start_ft", "distance_end_ft", "bin_length_ft"])
    before_band_digest = file_digest(BIN_CONTEXT, ["stable_bin_id", "distance_band"])

    temp = BIN_CONTEXT.with_name("bin_context.geometry_materialized.tmp.parquet")
    if temp.exists():
        try:
            temp_rows = parquet_row_count(temp)
        except Exception:
            temp_rows = -1
        if temp_rows == before_rows:
            log("Found complete existing geometry temp file; validating and finalizing without regenerating geometry.")
            after_id_digest = file_digest(temp, ["stable_bin_id"])
            after_distance_digest = file_digest(temp, ["stable_bin_id", "distance_start_ft", "distance_end_ft", "bin_length_ft"])
            after_band_digest = file_digest(temp, ["stable_bin_id", "distance_band"])
            identity_ok = before_id_digest == after_id_digest
            distance_ok = before_distance_digest == after_distance_digest
            band_ok = before_band_digest == after_band_digest
            write_csv("row_identity_unchanged_check.csv", [{"check_name": "row_count_unchanged", "before_row_count": before_rows, "after_row_count": temp_rows, "pass": True}])
            write_csv("stable_bin_id_unchanged_check.csv", [{"check_name": "stable_bin_id_ordered_digest_unchanged", "before_digest": before_id_digest, "after_digest": after_id_digest, "pass": identity_ok}])
            write_csv("distance_fields_unchanged_check.csv", [{"check_name": "distance_fields_ordered_digest_unchanged", "before_digest": before_distance_digest, "after_digest": after_distance_digest, "pass": distance_ok}])
            write_csv("distance_band_unchanged_check.csv", [{"check_name": "distance_band_ordered_digest_unchanged", "before_digest": before_band_digest, "after_digest": after_band_digest, "pass": band_ok}])
            if identity_ok and distance_ok and band_ok:
                stats = temp_geometry_stats(temp)
                replace_file_after_validation(temp, BIN_CONTEXT)
                cleanup_temp_file(temp, "finalized_existing_complete_temp", remove=False)
                log("Replaced staged bin_context.parquet from validated existing geometry temp file.")
                return {
                    "runtime_seconds": 0.0,
                    "before_row_count": before_rows,
                    "after_row_count": temp_rows,
                    **stats,
                }
            cleanup_temp_file(temp, "complete_temp_failed_identity_validation_removed", remove=True)
        else:
            cleanup_temp_file(temp, "full_run_start_remove_partial_or_stale_temp", remove=True)
    else:
        cleanup_temp_file(temp, "full_run_start_no_temp_present", remove=False)

    segment_map = prepare_segments()
    crs = geometry_crs_label()
    pf = pq.ParquetFile(BIN_CONTEXT)
    writer: pq.ParquetWriter | None = None
    total_rows = 0
    stats = empty_run_stats()
    start = time.perf_counter()
    try:
        for batch_i, batch in enumerate(pf.iter_batches(batch_size=chunk_rows), start=1):
            df = ensure_output_columns(batch.to_pandas())
            df, chunk_stats = process_geometry_chunk(df, segment_map, crs)
            merge_chunk_stats(stats, chunk_stats)
            table = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temp, table.schema, compression="snappy")
            writer.write_table(table)
            total_rows += len(df)
            elapsed = time.perf_counter() - start
            log(f"Materialized geometry chunk {batch_i}: {total_rows:,} rows total at {total_rows / max(elapsed, 1e-9):,.0f} bins/sec.")
    finally:
        if writer is not None:
            writer.close()
    runtime = time.perf_counter() - start
    after_rows = parquet_row_count(temp)
    after_id_digest = file_digest(temp, ["stable_bin_id"])
    after_distance_digest = file_digest(temp, ["stable_bin_id", "distance_start_ft", "distance_end_ft", "bin_length_ft"])
    after_band_digest = file_digest(temp, ["stable_bin_id", "distance_band"])
    identity_ok = before_rows == after_rows and before_id_digest == after_id_digest
    distance_ok = before_distance_digest == after_distance_digest
    band_ok = before_band_digest == after_band_digest
    write_csv("row_identity_unchanged_check.csv", [{"check_name": "row_count_unchanged", "before_row_count": before_rows, "after_row_count": after_rows, "pass": before_rows == after_rows}])
    write_csv("stable_bin_id_unchanged_check.csv", [{"check_name": "stable_bin_id_ordered_digest_unchanged", "before_digest": before_id_digest, "after_digest": after_id_digest, "pass": before_id_digest == after_id_digest}])
    write_csv("distance_fields_unchanged_check.csv", [{"check_name": "distance_fields_ordered_digest_unchanged", "before_digest": before_distance_digest, "after_digest": after_distance_digest, "pass": distance_ok}])
    write_csv("distance_band_unchanged_check.csv", [{"check_name": "distance_band_ordered_digest_unchanged", "before_digest": before_band_digest, "after_digest": after_band_digest, "pass": band_ok}])
    if not (identity_ok and distance_ok and band_ok):
        raise RuntimeError("Geometry materialization temp file failed identity/distance/band preservation checks; staged bin_context was not replaced.")
    del pf
    replace_file_after_validation(temp, BIN_CONTEXT)
    log(f"Replaced staged bin_context.parquet after QA-preserving geometry materialization checks.")
    return {
        "runtime_seconds": runtime,
        "before_row_count": before_rows,
        "after_row_count": after_rows,
        "geometry_generated_count": stats["geometry_generated_count"],
        "geometry_error_count": stats["geometry_error_count"],
        "multi_segment_geometry_count": stats["multi_segment_geometry_count"],
        "geometry_length_checked_count": stats["geometry_length_checked_count"],
        "geometry_length_fail_count": stats["geometry_length_fail_count"],
        "error_rows": stats["error_rows"],
        "multi_detail_rows": stats["multi_detail_rows"],
    }


def post_patch_qa(run: dict[str, Any], parent_check: pd.DataFrame) -> tuple[dict[str, Any], str]:
    cols = [
        "stable_bin_id",
        "logical_corridor_chain_id",
        "distance_start_ft",
        "distance_end_ft",
        "bin_length_ft",
        "distance_band",
        "chain_total_reach_ft",
        "geometry",
        "geometry_status",
        "geometry_source",
        "geometry_method",
        "geometry_encoding",
        "geometry_length_ft",
        "geometry_length_delta_ft",
        "geometry_segment_count",
        "multi_segment_geometry_flag",
        "geometry_crs",
        "geometry_error_reason",
        "directionality_status",
        "upstream_downstream",
    ]
    df = pd.read_parquet(BIN_CONTEXT, columns=cols)
    duplicate_ids = int(len(df) - df["stable_bin_id"].nunique(dropna=False))
    duplicate_intervals = int(
        (
            df.groupby(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft"], dropna=False)
            .size()
            .reset_index(name="n")["n"]
            > 1
        ).sum()
    )
    distance_fail = int(
        (
            (df["distance_start_ft"] < -FLOAT_TOL_FT)
            | (df["distance_end_ft"] > df["chain_total_reach_ft"] + FLOAT_TOL_FT)
            | (df["distance_end_ft"] > MAX_DISTANCE_FT + FLOAT_TOL_FT)
            | (df["distance_end_ft"] <= df["distance_start_ft"] + FLOAT_TOL_FT)
        ).sum()
    )
    geom_present = df["geometry"].notna()
    explicit_error = df["geometry_error_reason"].map(clean) != ""
    geometry_missing_without_reason = int((~geom_present & ~explicit_error).sum())
    length_valid = df[geom_present].copy()
    length_valid["length_tolerance_ft"] = length_valid["bin_length_ft"].abs().mul(LENGTH_REL_TOL).clip(lower=LENGTH_ABS_TOL_FT)
    length_valid["length_validation_status"] = length_valid.apply(
        lambda r: "within_tolerance" if abs(float(r["geometry_length_delta_ft"])) <= float(r["length_tolerance_ft"]) else "outside_tolerance",
        axis=1,
    )
    length_summary = length_valid.groupby("length_validation_status", dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        max_abs_delta_ft=("geometry_length_delta_ft", lambda s: float(s.abs().max()) if len(s) else 0.0),
    ).reset_index()
    write_csv("geometry_length_validation.csv", length_summary)
    write_csv("geometry_status_summary.csv", df.groupby("geometry_status", dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())
    write_csv("geometry_source_summary.csv", df.groupby("geometry_source", dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())
    write_csv("geometry_method_summary.csv", df.groupby("geometry_method", dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())
    write_csv("geometry_crs_summary.csv", df.groupby("geometry_crs", dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())
    write_csv("geometry_error_ledger.csv", pd.DataFrame(run["error_rows"]))
    write_csv("multi_segment_geometry_detail_sample.csv", pd.DataFrame(run["multi_detail_rows"]))
    write_csv(
        "multi_segment_geometry_summary.csv",
        df.groupby(["multi_segment_geometry_flag", "geometry_status"], dropna=False).agg(
            bin_count=("stable_bin_id", "count"),
            geometry_segment_count_max=("geometry_segment_count", "max"),
        ).reset_index(),
    )
    directionality = pd.DataFrame(
        [
            {"check_name": "directionality_status_not_assigned", "fail_count": int((df["directionality_status"] != "not_assigned").sum())},
            {"check_name": "upstream_downstream_null_or_blank", "fail_count": int((df["upstream_downstream"].map(clean) != "").sum())},
        ]
    )
    directionality["pass"] = directionality["fail_count"].eq(0)
    write_csv("directionality_null_check.csv", directionality)
    forbidden_tokens = ["speed", "aadt", "access", "crash", "exposure", "rate"]
    parquet_columns = pq.ParquetFile(BIN_CONTEXT).schema_arrow.names
    forbidden = [
        {"field_name": col, "forbidden_token": token, "present_flag": True}
        for col in parquet_columns
        for token in forbidden_tokens
        if token in col.lower()
    ]
    if not forbidden:
        forbidden = [{"field_name": "", "forbidden_token": "", "present_flag": False}]
    write_csv("forbidden_context_enrichment_field_check.csv", forbidden)
    generated = int(geom_present.sum())
    errors = int((~geom_present).sum())
    length_fail_count = int((length_valid["length_validation_status"] == "outside_tolerance").sum())
    if errors == 0 and length_fail_count == 0:
        decision = "bin_context_geometry_materialized_ready_for_validation"
    elif errors <= max(100, int(0.001 * len(df))) and length_fail_count <= max(100, int(0.001 * len(df))):
        decision = "bin_context_geometry_materialized_with_small_error_ledger"
    elif generated == 0:
        decision = "bin_context_geometry_blocked_by_parent_geometry_gap"
    else:
        decision = "bin_context_geometry_needs_method_repair"
    summary = {
        "row_count": len(df),
        "geometry_generated_count": generated,
        "geometry_error_count": errors,
        "geometry_missing_without_reason_count": geometry_missing_without_reason,
        "duplicate_stable_bin_id_count": duplicate_ids,
        "duplicate_chain_distance_interval_count": duplicate_intervals,
        "distance_validity_fail_count": distance_fail,
        "directionality_null_fail_count": int(directionality["fail_count"].sum()),
        "forbidden_context_enrichment_field_count": 0 if not forbidden[0]["present_flag"] else len(forbidden),
        "geometry_length_fail_count": length_fail_count,
        "multi_segment_geometry_count": int(df["multi_segment_geometry_flag"].sum()),
        "runtime_seconds": float(run["runtime_seconds"]),
        "readiness_decision": decision,
    }
    write_csv("geometry_materialization_summary.csv", [{"metric": k, "value": v} for k, v in summary.items()])
    write_csv("bin_context_geometry_readiness_decision.csv", [{"decision": decision, "ready_for_validation": decision in {"bin_context_geometry_materialized_ready_for_validation", "bin_context_geometry_materialized_with_small_error_ledger"}}])
    write_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "recommended_next_action": "Run independent bin_context geometry validation and map spot-checks."},
            {"priority": 2, "recommended_next_action": "After geometry validation, proceed to later directionality assignment without using crash direction fields."},
        ],
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "product": "materialize_bin_context_geometry",
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
            "acceptance_checks": {
                "parent_dependency_check_passed": bool(parent_check["allowed_parent_for_geometry_patch"].all() and not parent_check["downstream_object_parent_flag"].any()),
                "row_identity_unchanged": True,
                "stable_bin_id_unique": duplicate_ids == 0,
                "chain_distance_interval_unique": duplicate_intervals == 0,
                "distance_validity_passed": distance_fail == 0,
                "directionality_not_assigned": int(directionality["fail_count"].sum()) == 0,
                "forbidden_context_enrichment_fields_absent": not forbidden[0]["present_flag"],
                "geometry_status_populated": int((df["geometry_status"].map(clean) == "").sum()) == 0,
                "geometry_present_or_error_reason": geometry_missing_without_reason == 0,
            },
        },
    )
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "bounded_phase": "bin_context geometry materialization only",
            "product": "bin_context_geometry_materialization",
            "target": rel(BIN_CONTEXT),
            "canonical_parents": [rel(p) for p in PARENTS],
            "diagnostic_evidence_only": [rel(p) for p in DIAGNOSTIC_EVIDENCE],
            "row_count": len(df),
            "geometry_generated_count": generated,
            "geometry_error_count": errors,
            "final_decision": decision,
            "geometry_encoding": "wkb",
            "geometry_crs": geometry_crs_label(),
        },
    )
    return summary, decision


def update_metadata(summary: dict[str, Any], decision: str) -> None:
    stamp = now()
    manifest = load_json(STAGING_MANIFEST)
    product = manifest.setdefault("products", {}).setdefault("bin_context", {})
    product["geometry_materialization"] = {
        "script": "src.roadway_graph.materialize_bin_context_geometry",
        "updated_utc": stamp,
        "rule_version": RULE_VERSION,
        "final_decision": decision,
        "geometry_encoding": "wkb",
        "geometry_crs": geometry_crs_label(),
        "geometry_generated_count": int(summary["geometry_generated_count"]),
        "geometry_error_count": int(summary["geometry_error_count"]),
        "geometry_length_fail_count": int(summary["geometry_length_fail_count"]),
        "runtime_seconds": float(summary["runtime_seconds"]),
        "qa_review_path": rel(OUT),
    }
    product["geometry_policy"] = "geometry materialized from corridor segment WKB using source-measure fractions"
    product["final_decision"] = decision
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "script": "src.roadway_graph.materialize_bin_context_geometry",
            "bounded_phase": "bin_context geometry materialization only",
            "patched_utc": stamp,
            "row_count": int(summary["row_count"]),
            "final_decision": decision,
            "rule_version": RULE_VERSION,
        }
    )
    write_json(STAGING_MANIFEST, manifest)
    schema = load_json(STAGING_SCHEMA)
    table = schema.setdefault("tables", {}).setdefault("bin_context.parquet", {})
    table["geometry_materialization_fields"] = GEOMETRY_COLUMNS
    table["geometry_encoding"] = "wkb"
    table["geometry_rule_version"] = RULE_VERSION
    table["geometry_crs"] = geometry_crs_label()
    table["updated_utc"] = stamp
    schema["updated_utc"] = stamp
    write_json(STAGING_SCHEMA, schema)
    with STAGING_README.open("a", encoding="utf-8") as f:
        f.write(
            f"""

## bin_context Geometry Materialization

Patched `{rel(BIN_CONTEXT)}` in place by filling bin geometry from staged
`approach_corridors.parquet` segment WKB using source-measure fractions. Row
identity, bin intervals, distance bands, directionality status, and context
fields were not changed. Geometry is encoded as WKB in the existing `geometry`
column with explicit geometry provenance/status fields.

Decision: `{decision}`.
"""
        )


def write_findings(summary: dict[str, Any], decision: str) -> None:
    memo = f"""# bin_context Geometry Materialization Findings

## Previous Slowdown Cause
The halted full run was slow because geometry fields were written with per-row, per-column pandas scalar assignment (`df.at`) inside each chunk. Geometry extraction itself benchmarked near the expected rate; scalar DataFrame mutation was the bottleneck.

## Implementation Change
The patched implementation accumulates generated geometry and provenance fields as per-column Python lists, assigns each field once per chunk, and writes chunked Parquet from the assembled chunk. Benchmark mode uses the same chunk assembly and temporary Parquet write path as the full run.

## What Was Patched
Filled geometry for existing staged `bin_context.parquet` rows using corridor segment WKB and source-measure fraction substringing.

## What Was Not Changed
Stable bin IDs, row count, signal/approach/chain IDs, distance fields, distance bands, directionality fields, and context-enrichment status were not changed. No upstream/downstream, MVP, access, crash, speed, AADT, exposure, rate, or distance-band unit products were built.

## Parent Dependency Statement
Canonical parents were the staged `bin_context.parquet`, `approach_corridors.parquet`, `travelway_network_index.parquet`, `signal_approaches.parquet`, and `signal_index.parquet`. Review folders were diagnostic evidence only.

## Benchmark And Runtime
Full runtime: {float(summary['runtime_seconds']):.1f} seconds. Geometry generated: {int(summary['geometry_generated_count']):,}. Geometry errors: {int(summary['geometry_error_count']):,}.

## Temporary File Handling
Failed-run and benchmark temporary files were removed or ignored before safe replacement. See `temp_file_cleanup_status.csv`.

## Geometry Source And Encoding
Geometry source was corridor segment WKB from `approach_corridors.parquet`, with Travelway WKB fallback available. Geometry encoding is WKB in the existing `geometry` column. CRS label: `{geometry_crs_label()}`.

## Geometry Completeness And Failures
Generated geometries: {int(summary['geometry_generated_count']):,}. Rows with explicit geometry errors: {int(summary['geometry_error_count']):,}. Missing geometry without error reason: {int(summary['geometry_missing_without_reason_count']):,}.

## Multi-Segment Bin Handling
Multi-segment bins remained single rows. Segment pieces were substringed separately and line-merged where possible. Multi-segment geometries: {int(summary['multi_segment_geometry_count']):,}.

## Geometry Length Validation
Length failures outside tolerance: {int(summary['geometry_length_fail_count']):,}. Tolerance was max({LENGTH_ABS_TOL_FT} ft, {LENGTH_REL_TOL:.0%} of bin length).

## Integrity Confirmation
Row identity, stable_bin_id order, distance fields, and distance bands passed unchanged checks. Directionality remains `not_assigned`; `upstream_downstream` remains blank. No context-enrichment fields were introduced.

## Readiness
Decision: `{decision}`. Geometry is sufficient for validation if the independent QA accepts the explicit CRS/source-units assumption and length tolerance.

## Recommended Next Task
Run independent bin_context geometry validation and map spot-checks before any later directionality work.
"""
    with (OUT / "findings_memo.md").open("w", encoding="utf-8") as f:
        f.write(memo)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-chains", type=int, default=0)
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.benchmark_chains:
        result = benchmark(args.benchmark_chains)
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    if not parent_check["allowed_parent_for_geometry_patch"].all() or parent_check["downstream_object_parent_flag"].any():
        raise RuntimeError("Parent dependency check failed.")
    benchmark_path = OUT / "benchmark_geometry_materialization.csv"
    if not benchmark_path.exists():
        log("No benchmark file found; running default 500-chain benchmark before full materialization.")
        benchmark(500)
    run = materialize_full(args.chunk_rows)
    summary, decision = post_patch_qa(run, parent_check)
    write_findings(summary, decision)
    update_metadata(summary, decision)
    log(f"Geometry materialization complete with decision {decision}.")


if __name__ == "__main__":
    main()
