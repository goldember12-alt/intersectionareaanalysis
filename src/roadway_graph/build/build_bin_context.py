"""Build Phase C.3 staged neutral bin_context from approach_corridors.

This cache layer creates neutral 50-ft chain-distance bins from validated,
chain-aware approach corridors. It does not assign upstream/downstream or
directionality and does not enrich with speed, AADT, access, crash, exposure,
or rate context.

The hot path intentionally avoids per-bin pandas work. Parent corridor rows are
preprocessed once into ordered Python segment records, then each chain is
scanned with a moving segment pointer. Physical bin geometry is deferred by
default for this neutral layer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/build_bin_context"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/patch_remaining_likely_valid_source_extent_continuations",
    REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit",
    REPO / "work/roadway_graph/review/patch_approach_corridor_context_transition_extensions",
    REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains",
    REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS]

BUILD_VERSION = "bin_context_neutral_chain_distance_v2_2026-06-10"
BIN_LENGTH_FT = 50.0
MAX_DISTANCE_FT = 2500.0
FLOAT_TOL_FT = 1e-6
DEFAULT_CHUNK_ROWS = 200_000

DISTANCE_BANDS: list[tuple[float, float, str]] = [
    (0.0, 250.0, "0-250"),
    (250.0, 500.0, "250-500"),
    (500.0, 1000.0, "500-1,000"),
    (1000.0, 1500.0, "1,000-1,500"),
    (1500.0, 2000.0, "1,500-2,000"),
    (2000.0, 2500.0, "2,000-2,500"),
]

REQUIRED_CORRIDOR_COLUMNS = [
    "logical_corridor_chain_id",
    "approach_corridor_id",
    "stable_signal_id",
    "signal_approach_id",
    "stable_travelway_id",
    "segment_order",
    "segment_start_distance_ft",
    "segment_end_distance_ft",
    "chain_total_reach_ft",
    "measure_side_class",
    "chain_stop_reason",
    "chain_completeness_status",
    "chain_bin_eligible_flag",
]

BIN_COLUMNS = [
    "stable_bin_id",
    "stable_signal_id",
    "signal_approach_id",
    "logical_corridor_chain_id",
    "distance_start_ft",
    "distance_end_ft",
    "bin_length_ft",
    "distance_band",
    "measure_side_class",
    "chain_total_reach_ft",
    "chain_stop_reason",
    "chain_completeness_status",
    "bin_origin",
    "bin_context_build_status",
    "primary_approach_corridor_id",
    "supporting_approach_corridor_ids",
    "supporting_stable_travelway_ids",
    "segment_overlap_count",
    "segment_boundary_crossing_flag",
    "primary_stable_travelway_id",
    "route_base",
    "source_route_name",
    "carriageway_direction_token",
    "roadway_configuration",
    "source_measure_start",
    "source_measure_end",
    "source_measure_midpoint",
    "source_measure_status",
    "geometry",
    "geometry_status",
    "chain_bin_eligible_flag",
    "bin_eligible_flag",
    "final_partial_bin_flag",
    "bin_distance_status",
    "distance_band_status",
    "multi_segment_bin_status",
    "lineage_confidence",
    "parent_corridor_stop_reason",
    "parent_corridor_warning_status",
    "parent_corridor_review_status",
    "directionality_status",
    "upstream_downstream",
]

BIN_SCHEMA = pa.schema(
    [
        pa.field("stable_bin_id", pa.string()),
        pa.field("stable_signal_id", pa.string()),
        pa.field("signal_approach_id", pa.string()),
        pa.field("logical_corridor_chain_id", pa.string()),
        pa.field("distance_start_ft", pa.float64()),
        pa.field("distance_end_ft", pa.float64()),
        pa.field("bin_length_ft", pa.float64()),
        pa.field("distance_band", pa.string()),
        pa.field("measure_side_class", pa.string()),
        pa.field("chain_total_reach_ft", pa.float64()),
        pa.field("chain_stop_reason", pa.string()),
        pa.field("chain_completeness_status", pa.string()),
        pa.field("bin_origin", pa.string()),
        pa.field("bin_context_build_status", pa.string()),
        pa.field("primary_approach_corridor_id", pa.string()),
        pa.field("supporting_approach_corridor_ids", pa.string()),
        pa.field("supporting_stable_travelway_ids", pa.string()),
        pa.field("segment_overlap_count", pa.int64()),
        pa.field("segment_boundary_crossing_flag", pa.bool_()),
        pa.field("primary_stable_travelway_id", pa.string()),
        pa.field("route_base", pa.string()),
        pa.field("source_route_name", pa.string()),
        pa.field("carriageway_direction_token", pa.string()),
        pa.field("roadway_configuration", pa.string()),
        pa.field("source_measure_start", pa.float64()),
        pa.field("source_measure_end", pa.float64()),
        pa.field("source_measure_midpoint", pa.float64()),
        pa.field("source_measure_status", pa.string()),
        pa.field("geometry", pa.binary()),
        pa.field("geometry_status", pa.string()),
        pa.field("chain_bin_eligible_flag", pa.bool_()),
        pa.field("bin_eligible_flag", pa.bool_()),
        pa.field("final_partial_bin_flag", pa.bool_()),
        pa.field("bin_distance_status", pa.string()),
        pa.field("distance_band_status", pa.string()),
        pa.field("multi_segment_bin_status", pa.string()),
        pa.field("lineage_confidence", pa.string()),
        pa.field("parent_corridor_stop_reason", pa.string()),
        pa.field("parent_corridor_warning_status", pa.string()),
        pa.field("parent_corridor_review_status", pa.string()),
        pa.field("directionality_status", pa.string()),
        pa.field("upstream_downstream", pa.string()),
    ]
)


@dataclass(slots=True)
class Segment:
    approach_corridor_id: str
    stable_travelway_id: str
    segment_order: int
    start_ft: float
    end_ft: float
    reviewed_signal_measure: float | None
    route_base: str
    source_route_name: str
    carriageway_direction_token: str
    roadway_configuration: str
    source_measure_start_parent: float | None
    source_measure_end_parent: float | None
    segment_source_from_measure: float | None
    segment_source_to_measure: float | None


@dataclass(slots=True)
class Chain:
    logical_corridor_chain_id: str
    stable_signal_id: str
    signal_approach_id: str
    measure_side_class: str
    chain_total_reach_ft: float
    chain_stop_reason: str
    chain_completeness_status: str
    chain_bin_eligible_flag: bool
    parent_corridor_warning_status: str
    parent_corridor_review_status: str
    segments: list[Segment]

    @property
    def used_for_bin_context(self) -> bool:
        return bool(self.chain_bin_eligible_flag and self.chain_total_reach_ft > FLOAT_TOL_FT and self.segments)


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


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) else result


def hash_text(text: str, length: int = 24) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


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
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        backup = OUT / f"{path.name}.invalid_after_failed_bin_context_metadata_write"
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        rel_path = rel(path)
        try:
            prior = subprocess.check_output(["git", "show", f"HEAD:{rel_path}"], cwd=REPO, text=True)
            return json.loads(prior)
        except Exception as exc:
            if path == STAGING_MANIFEST:
                log(f"{rel_path} is invalid JSON and is not tracked in HEAD; reconstructing minimal staging manifest from current staged products.")
                return default_staging_manifest()
            raise RuntimeError(f"{rel_path} is invalid JSON and could not be restored from HEAD") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, dict):
        return {str(key): json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows) if path.exists() else 0


def default_staging_manifest() -> dict[str, Any]:
    return {
        "created_utc": now(),
        "updated_utc": now(),
        "bounded_phase": "staging_manifest_reconstructed_after_failed_bin_context_metadata_write",
        "forbidden_parent_statement": "No downstream bin/distance-band/directionality/context/MVP/crash/access/rate objects were used as canonical parents.",
        "phase_b1_status_patch_applied": True,
        "phase_b2_travelway_network_index_built": TRAVELWAY_INDEX.exists(),
        "phase_b3_signal_travelway_attachment_built": (STAGING / "signal_travelway_attachment.parquet").exists(),
        "phase_c1_signal_approaches_built": SIGNAL_APPROACHES.exists(),
        "phase_c2_approach_corridors_built": APPROACH_CORRIDORS.exists(),
        "phase_c3_bin_context_built": BIN_CONTEXT.exists(),
        "products": {
            "signal_index": {
                "path": rel(SIGNAL_INDEX),
                "row_count": parquet_row_count(SIGNAL_INDEX),
                "canonical_parents": ["artifacts/normalized/signals.parquet"],
                "grain": "one row per source signal row",
            },
            "travelway_network_index": {
                "path": rel(TRAVELWAY_INDEX),
                "row_count": parquet_row_count(TRAVELWAY_INDEX),
                "canonical_parents": ["artifacts/normalized/roads.parquet"],
                "grain": "one row per source Travelway/roads artifact row",
            },
            "signal_travelway_attachment": {
                "path": rel(STAGING / "signal_travelway_attachment.parquet"),
                "row_count": parquet_row_count(STAGING / "signal_travelway_attachment.parquet"),
                "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX)],
                "grain": "one row per signal-to-Travelway spatial projection candidate within 250 ft",
            },
            "signal_approaches": {
                "path": rel(SIGNAL_APPROACHES),
                "row_count": parquet_row_count(SIGNAL_APPROACHES),
                "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(STAGING / "signal_travelway_attachment.parquet")],
                "grain": "one row per physical signal approach arm per stable signal",
            },
            "approach_corridors": {
                "path": rel(APPROACH_CORRIDORS),
                "row_count": parquet_row_count(APPROACH_CORRIDORS),
                "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(STAGING / "signal_travelway_attachment.parquet"), rel(SIGNAL_APPROACHES)],
                "grain": "chain-aware one-sided corridor segments",
            },
        },
        "manifest_repair_note": "Prior manifest JSON was invalid after a failed Phase C.3 metadata write; invalid copy preserved in work/roadway_graph/review/build_bin_context/.",
    }


def parent_dependency_check() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in PARENTS:
        exists = path.exists()
        row_count: int | str = ""
        read_status = "not_read_missing"
        if exists:
            try:
                row_count = pq.ParquetFile(path).metadata.num_rows
                read_status = "readable"
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        downstream = any(
            token in lowered
            for token in [
                "bin_context",
                "distance_band_units",
                "mvp",
                "crash",
                "access_context",
                "speed_context",
                "aadt",
                "exposure",
                "rate_distribution",
            ]
        )
        rows.append(
            {
                "parent_path": rel(path),
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_bin_context": exists and read_status == "readable",
                "downstream_object_parent_flag": downstream,
            }
        )
    return pd.DataFrame(rows)


def distance_band_for_interval(start_ft: float, end_ft: float) -> tuple[str, str]:
    end_probe = max(start_ft, end_ft - FLOAT_TOL_FT)
    for lo, hi, label in DISTANCE_BANDS:
        if start_ft >= lo - FLOAT_TOL_FT and start_ft < hi - FLOAT_TOL_FT:
            if end_probe < hi + FLOAT_TOL_FT:
                return label, "valid_single_band"
            return label, "crosses_distance_band_boundary"
    return "", "start_outside_supported_bands"


def make_stable_bin_id(chain: Chain, start_ft: float, end_ft: float) -> str:
    key = "|".join(
        [
            BUILD_VERSION,
            chain.stable_signal_id,
            chain.signal_approach_id,
            chain.logical_corridor_chain_id,
            f"{start_ft:.6f}",
            f"{end_ft:.6f}",
            chain.measure_side_class,
        ]
    )
    return f"bin_{hash_text(key, 28)}"


def measure_at_distance(segment: Segment, side: str, distance_ft: float) -> float | None:
    if segment.reviewed_signal_measure is None:
        return None
    if side == "measure_increasing_from_signal":
        value = segment.reviewed_signal_measure + (distance_ft / 5280.0)
    elif side == "measure_decreasing_from_signal":
        value = segment.reviewed_signal_measure - (distance_ft / 5280.0)
    else:
        return None
    if segment.segment_source_from_measure is not None and segment.segment_source_to_measure is not None:
        lo = min(segment.segment_source_from_measure, segment.segment_source_to_measure)
        hi = max(segment.segment_source_from_measure, segment.segment_source_to_measure)
        value = max(lo, min(hi, value))
    return value


def prepare_corridors(corridors: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REQUIRED_CORRIDOR_COLUMNS if col not in corridors.columns]
    if missing:
        raise RuntimeError(f"approach_corridors is missing required columns: {missing}")
    c = corridors.copy()
    numeric_cols = [
        "segment_order",
        "segment_start_distance_ft",
        "segment_end_distance_ft",
        "chain_total_reach_ft",
        "reviewed_signal_measure",
        "source_measure_start",
        "source_measure_end",
        "segment_source_from_measure",
        "segment_source_to_measure",
    ]
    for col in numeric_cols:
        if col in c.columns:
            c[col] = pd.to_numeric(c[col], errors="coerce")
    c["chain_bin_eligible_bool"] = c["chain_bin_eligible_flag"].map(bool_value)
    sort_cols = ["logical_corridor_chain_id", "segment_start_distance_ft", "segment_end_distance_ft", "segment_order", "approach_corridor_id"]
    return c.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


def corridor_value(row: Any, name: str, default: Any = "") -> Any:
    return getattr(row, name) if hasattr(row, name) else default


def build_chain_structures(corridors: pd.DataFrame, benchmark_chain_limit: int | None = None) -> list[Chain]:
    chains: list[Chain] = []
    current_id: str | None = None
    current_segments: list[Segment] = []
    first_row: Any | None = None
    max_reach = 0.0
    eligible = True

    def flush() -> bool:
        nonlocal current_id, current_segments, first_row, max_reach, eligible
        if current_id is None or first_row is None:
            return True
        chain = Chain(
            logical_corridor_chain_id=current_id,
            stable_signal_id=clean(corridor_value(first_row, "stable_signal_id")),
            signal_approach_id=clean(corridor_value(first_row, "signal_approach_id")),
            measure_side_class=clean(corridor_value(first_row, "measure_side_class")),
            chain_total_reach_ft=max_reach,
            chain_stop_reason=clean(corridor_value(first_row, "chain_stop_reason")),
            chain_completeness_status=clean(corridor_value(first_row, "chain_completeness_status")),
            chain_bin_eligible_flag=eligible,
            parent_corridor_warning_status=clean(corridor_value(first_row, "parent_corridor_gate_severity")) or "none",
            parent_corridor_review_status=clean(corridor_value(first_row, "chain_completeness_status")),
            segments=current_segments,
        )
        chains.append(chain)
        if benchmark_chain_limit is not None and sum(1 for item in chains if item.used_for_bin_context) >= benchmark_chain_limit:
            return False
        current_id = None
        current_segments = []
        first_row = None
        max_reach = 0.0
        eligible = True
        return True

    for row in corridors.itertuples(index=False):
        chain_id = clean(corridor_value(row, "logical_corridor_chain_id"))
        if current_id is not None and chain_id != current_id:
            if not flush():
                break
        if current_id is None:
            current_id = chain_id
            first_row = row
            current_segments = []
            max_reach = 0.0
            eligible = True
        reach = float_or_none(corridor_value(row, "chain_total_reach_ft"))
        if reach is not None:
            max_reach = max(max_reach, reach)
        eligible = eligible and bool_value(corridor_value(row, "chain_bin_eligible_flag"))
        start_ft = float_or_none(corridor_value(row, "segment_start_distance_ft"))
        end_ft = float_or_none(corridor_value(row, "segment_end_distance_ft"))
        if start_ft is None or end_ft is None or end_ft <= start_ft + FLOAT_TOL_FT:
            continue
        current_segments.append(
            Segment(
                approach_corridor_id=clean(corridor_value(row, "approach_corridor_id")),
                stable_travelway_id=clean(corridor_value(row, "stable_travelway_id")),
                segment_order=int(float_or_none(corridor_value(row, "segment_order")) or 0),
                start_ft=start_ft,
                end_ft=end_ft,
                reviewed_signal_measure=float_or_none(corridor_value(row, "reviewed_signal_measure")),
                route_base=clean(corridor_value(row, "route_base")),
                source_route_name=clean(corridor_value(row, "source_route_name")),
                carriageway_direction_token=clean(corridor_value(row, "carriageway_direction_token")),
                roadway_configuration=clean(corridor_value(row, "roadway_configuration")),
                source_measure_start_parent=float_or_none(corridor_value(row, "source_measure_start")),
                source_measure_end_parent=float_or_none(corridor_value(row, "source_measure_end")),
                segment_source_from_measure=float_or_none(corridor_value(row, "segment_source_from_measure")),
                segment_source_to_measure=float_or_none(corridor_value(row, "segment_source_to_measure")),
            )
        )
    else:
        flush()
    return chains


def chain_ledger(chains: Iterable[Chain]) -> pd.DataFrame:
    rows = []
    for chain in chains:
        rows.append(
            {
                "logical_corridor_chain_id": chain.logical_corridor_chain_id,
                "stable_signal_id": chain.stable_signal_id,
                "signal_approach_id": chain.signal_approach_id,
                "measure_side_class": chain.measure_side_class,
                "chain_total_reach_ft": chain.chain_total_reach_ft,
                "chain_stop_reason": chain.chain_stop_reason,
                "chain_completeness_status": chain.chain_completeness_status,
                "chain_bin_eligible_flag": chain.chain_bin_eligible_flag,
                "chain_segment_count": len(chain.segments),
                "used_for_bin_context": chain.used_for_bin_context,
                "bin_build_exclusion_reason": "" if chain.used_for_bin_context else "non_bin_eligible_or_nonpositive_reach",
            }
        )
    return pd.DataFrame(rows)


def row_for_bin(chain: Chain, start_ft: float, end_ft: float, ptr_start: int) -> tuple[dict[str, Any], int]:
    segments = chain.segments
    ptr = ptr_start
    while ptr < len(segments) and segments[ptr].end_ft <= start_ft + FLOAT_TOL_FT:
        ptr += 1
    overlaps: list[tuple[Segment, float, float, float]] = []
    j = ptr
    while j < len(segments) and segments[j].start_ft < end_ft - FLOAT_TOL_FT:
        seg = segments[j]
        overlap_start = max(start_ft, seg.start_ft)
        overlap_end = min(end_ft, seg.end_ft)
        overlap_len = overlap_end - overlap_start
        if overlap_len > FLOAT_TOL_FT:
            overlaps.append((seg, overlap_len, overlap_start, overlap_end))
        j += 1
    if overlaps:
        primary = max(overlaps, key=lambda item: (item[1], -item[0].segment_order, item[0].approach_corridor_id))[0]
        first = overlaps[0][0]
        last = overlaps[-1][0]
        supporting_corridor_ids = "|".join(item[0].approach_corridor_id for item in overlaps)
        supporting_travelway_ids = "|".join(dict.fromkeys(item[0].stable_travelway_id for item in overlaps))
        segment_overlap_count = len(overlaps)
        m_start = measure_at_distance(first, chain.measure_side_class, start_ft)
        m_end = measure_at_distance(last, chain.measure_side_class, end_ft)
        midpoint_ft = (start_ft + end_ft) / 2.0
        midpoint_segment = first
        for seg, _length, overlap_start, overlap_end in overlaps:
            if overlap_start <= midpoint_ft + FLOAT_TOL_FT and overlap_end >= midpoint_ft - FLOAT_TOL_FT:
                midpoint_segment = seg
                break
        m_mid = measure_at_distance(midpoint_segment, chain.measure_side_class, midpoint_ft)
    else:
        primary = segments[min(ptr, len(segments) - 1)]
        supporting_corridor_ids = ""
        supporting_travelway_ids = ""
        segment_overlap_count = 0
        m_start = m_end = m_mid = None

    distance_band, distance_band_status = distance_band_for_interval(start_ft, end_ft)
    bin_length = end_ft - start_ft
    multi_segment = segment_overlap_count > 1
    if segment_overlap_count == 0:
        source_measure_status = "missing_segment_overlap"
        multi_segment_status = "missing_segment_overlap"
        lineage_confidence = "low"
    elif multi_segment:
        source_measure_status = "derived_multi_segment_chain_distance_measure"
        multi_segment_status = "multi_segment_bin_evidence_preserved"
        lineage_confidence = "medium"
    else:
        source_measure_status = "derived_single_segment_chain_distance_measure"
        multi_segment_status = "single_segment_bin"
        lineage_confidence = "medium"

    record = {
        "stable_bin_id": make_stable_bin_id(chain, start_ft, end_ft),
        "stable_signal_id": chain.stable_signal_id,
        "signal_approach_id": chain.signal_approach_id,
        "logical_corridor_chain_id": chain.logical_corridor_chain_id,
        "distance_start_ft": start_ft,
        "distance_end_ft": end_ft,
        "bin_length_ft": bin_length,
        "distance_band": distance_band,
        "measure_side_class": chain.measure_side_class,
        "chain_total_reach_ft": chain.chain_total_reach_ft,
        "chain_stop_reason": chain.chain_stop_reason,
        "chain_completeness_status": chain.chain_completeness_status,
        "bin_origin": "generated_from_chain_aware_approach_corridors",
        "bin_context_build_status": "built_neutral_bin_context",
        "primary_approach_corridor_id": primary.approach_corridor_id,
        "supporting_approach_corridor_ids": supporting_corridor_ids,
        "supporting_stable_travelway_ids": supporting_travelway_ids,
        "segment_overlap_count": segment_overlap_count,
        "segment_boundary_crossing_flag": multi_segment,
        "primary_stable_travelway_id": primary.stable_travelway_id,
        "route_base": primary.route_base,
        "source_route_name": primary.source_route_name,
        "carriageway_direction_token": primary.carriageway_direction_token,
        "roadway_configuration": primary.roadway_configuration,
        "source_measure_start": m_start,
        "source_measure_end": m_end,
        "source_measure_midpoint": m_mid,
        "source_measure_status": source_measure_status,
        "geometry": None,
        "geometry_status": "geometry_deferred_for_performance",
        "chain_bin_eligible_flag": chain.chain_bin_eligible_flag,
        "bin_eligible_flag": True,
        "final_partial_bin_flag": bin_length < BIN_LENGTH_FT - FLOAT_TOL_FT,
        "bin_distance_status": "valid_chain_distance_interval"
        if start_ft >= -FLOAT_TOL_FT
        and end_ft <= chain.chain_total_reach_ft + FLOAT_TOL_FT
        and end_ft <= MAX_DISTANCE_FT + FLOAT_TOL_FT
        and end_ft > start_ft + FLOAT_TOL_FT
        else "invalid_chain_distance_interval",
        "distance_band_status": distance_band_status,
        "multi_segment_bin_status": multi_segment_status,
        "lineage_confidence": lineage_confidence,
        "parent_corridor_stop_reason": chain.chain_stop_reason,
        "parent_corridor_warning_status": chain.parent_corridor_warning_status,
        "parent_corridor_review_status": chain.parent_corridor_review_status,
        "directionality_status": "not_assigned",
        "upstream_downstream": "",
    }
    return record, ptr


def iter_bin_rows(chains: Iterable[Chain]) -> Iterator[dict[str, Any]]:
    for chain in chains:
        if not chain.used_for_bin_context:
            continue
        reach = min(chain.chain_total_reach_ft, MAX_DISTANCE_FT)
        bin_count = int(math.ceil((reach - FLOAT_TOL_FT) / BIN_LENGTH_FT))
        ptr = 0
        for i in range(bin_count):
            start_ft = round(i * BIN_LENGTH_FT, 6)
            if start_ft >= reach - FLOAT_TOL_FT:
                continue
            end_ft = min(round(start_ft + BIN_LENGTH_FT, 6), reach)
            if end_ft <= start_ft + FLOAT_TOL_FT:
                continue
            row, ptr = row_for_bin(chain, start_ft, end_ft, ptr)
            yield row


def chunked_rows(rows: Iterator[dict[str, Any]], chunk_size: int) -> Iterator[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def write_parquet_stream(chains: list[Chain], path: Path, chunk_size: int = DEFAULT_CHUNK_ROWS) -> dict[str, Any]:
    tmp_path = path.with_name(path.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    writer: pq.ParquetWriter | None = None
    row_count = 0
    chunk_count = 0
    start_time = time.perf_counter()
    try:
        for chunk in chunked_rows(iter_bin_rows(chains), chunk_size):
            df = pd.DataFrame.from_records(chunk, columns=BIN_COLUMNS)
            table = pa.Table.from_pandas(df, schema=BIN_SCHEMA, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(tmp_path, BIN_SCHEMA, compression="snappy")
            writer.write_table(table)
            row_count += len(chunk)
            chunk_count += 1
            elapsed = time.perf_counter() - start_time
            log(f"Wrote bin_context chunk {chunk_count:,}: {row_count:,} rows total at {row_count / max(elapsed, 1e-9):,.0f} bins/sec.")
    finally:
        if writer is not None:
            writer.close()
    tmp_path.replace(path)
    return {"row_count": row_count, "chunk_count": chunk_count, "runtime_seconds": time.perf_counter() - start_time}


def expected_bin_count(reach_ft: float) -> int:
    if reach_ft <= FLOAT_TOL_FT:
        return 0
    return int(math.ceil((min(reach_ft, MAX_DISTANCE_FT) - FLOAT_TOL_FT) / BIN_LENGTH_FT))


def rows_to_dataframe(chains: list[Chain]) -> pd.DataFrame:
    return pd.DataFrame.from_records(iter_bin_rows(chains), columns=BIN_COLUMNS)


def readiness_decision(bin_context: pd.DataFrame, parent_check: pd.DataFrame) -> str:
    if not parent_check["allowed_parent_for_bin_context"].all() or parent_check["downstream_object_parent_flag"].any():
        return "bin_context_needs_parent_corridor_repair"
    if bin_context.empty:
        return "bin_context_should_be_rebuilt"
    if len(bin_context) - bin_context["stable_bin_id"].nunique(dropna=False):
        return "bin_context_needs_duplicate_bin_repair"
    duplicate_intervals = (
        bin_context.groupby(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    if int((duplicate_intervals["n"] > 1).sum()):
        return "bin_context_needs_duplicate_bin_repair"
    distance_fail = (
        (bin_context["distance_start_ft"] < -FLOAT_TOL_FT)
        | (bin_context["distance_end_ft"] > bin_context["chain_total_reach_ft"] + FLOAT_TOL_FT)
        | (bin_context["distance_end_ft"] > MAX_DISTANCE_FT + FLOAT_TOL_FT)
        | (bin_context["bin_length_ft"] <= FLOAT_TOL_FT)
        | (bin_context["distance_band"].map(clean) == "")
    )
    if bool(distance_fail.any()):
        return "bin_context_needs_distance_or_band_repair"
    return "bin_context_built_with_geometry_limitations_ready_for_validation"


def write_qa_outputs(bin_context: pd.DataFrame, chains: list[Chain], approaches: pd.DataFrame, parent_check: pd.DataFrame, decision: str) -> dict[str, Any]:
    write_csv("parent_dependency_check.csv", parent_check)
    ledger = chain_ledger(chains)
    write_csv("excluded_non_bin_eligible_chain_ledger.csv", ledger[~ledger["used_for_bin_context"]])

    represented_eligible = set(ledger.loc[ledger["used_for_bin_context"], "signal_approach_id"].astype(str))
    no_bin = approaches[~approaches["signal_approach_id"].astype(str).isin(represented_eligible)].copy()
    keep_cols = [
        col
        for col in [
            "stable_signal_id",
            "signal_approach_id",
            "corridor_build_gate",
            "corridor_build_allowed_flag",
            "corridor_gate_severity",
            "corridor_gate_reason",
            "corridor_restriction_notes",
        ]
        if col in no_bin.columns
    ]
    no_bin_out = no_bin[keep_cols].copy() if keep_cols else pd.DataFrame()
    if not no_bin_out.empty:
        no_bin_out["no_bin_reason"] = no_bin_out.get("corridor_build_gate", "").map(clean)
    write_csv("no_bin_chain_ledger.csv", no_bin_out)

    duplicate_id_count = int(len(bin_context) - bin_context["stable_bin_id"].nunique(dropna=False))
    write_csv(
        "stable_bin_id_uniqueness_check.csv",
        [{"check_name": "stable_bin_id_unique", "bin_rows": len(bin_context), "duplicate_stable_bin_id_count": duplicate_id_count, "pass": duplicate_id_count == 0}],
    )

    interval_dupes = (
        bin_context.groupby(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    duplicate_interval_count = int((interval_dupes["row_count"] > 1).sum()) if not interval_dupes.empty else 0
    write_csv(
        "duplicate_chain_distance_interval_check.csv",
        [{"check_name": "logical_chain_distance_interval_unique", "duplicate_chain_distance_interval_count": duplicate_interval_count, "pass": duplicate_interval_count == 0}],
    )

    distance_checks = [
        {"check_name": "no_negative_start_distance", "fail_count": int((bin_context["distance_start_ft"] < -FLOAT_TOL_FT).sum())},
        {"check_name": "no_end_beyond_chain_total_reach", "fail_count": int((bin_context["distance_end_ft"] > bin_context["chain_total_reach_ft"] + FLOAT_TOL_FT).sum())},
        {"check_name": "no_end_beyond_2500_ft", "fail_count": int((bin_context["distance_end_ft"] > MAX_DISTANCE_FT + FLOAT_TOL_FT).sum())},
        {"check_name": "no_zero_or_negative_length_bins", "fail_count": int((bin_context["bin_length_ft"] <= FLOAT_TOL_FT).sum())},
        {"check_name": "distance_band_populated", "fail_count": int((bin_context["distance_band"].map(clean) == "").sum())},
    ]
    for row in distance_checks:
        row["pass"] = row["fail_count"] == 0
    distance_validity = pd.DataFrame(distance_checks)
    write_csv("bin_distance_validity_check.csv", distance_validity)

    expected = ledger[ledger["used_for_bin_context"]].copy()
    actual = bin_context.groupby("logical_corridor_chain_id", dropna=False).agg(
        actual_bin_count=("stable_bin_id", "count"),
        actual_total_bin_length_ft=("bin_length_ft", "sum"),
        min_distance_start_ft=("distance_start_ft", "min"),
        max_distance_end_ft=("distance_end_ft", "max"),
    )
    recon_chain = expected.set_index("logical_corridor_chain_id", drop=False).join(actual, how="left")
    recon_chain["actual_bin_count"] = recon_chain["actual_bin_count"].fillna(0).astype(int)
    recon_chain["actual_total_bin_length_ft"] = recon_chain["actual_total_bin_length_ft"].fillna(0.0)
    recon_chain["expected_bin_count"] = recon_chain["chain_total_reach_ft"].map(expected_bin_count)
    recon_chain["expected_total_bin_length_ft"] = recon_chain["chain_total_reach_ft"].clip(upper=MAX_DISTANCE_FT)
    recon_chain["bin_count_difference"] = recon_chain["actual_bin_count"] - recon_chain["expected_bin_count"]
    recon_chain["bin_length_difference_ft"] = recon_chain["actual_total_bin_length_ft"] - recon_chain["expected_total_bin_length_ft"]
    recon_chain["reconciliation_status"] = recon_chain.apply(
        lambda r: "reconciled"
        if int(r["bin_count_difference"]) == 0 and abs(float(r["bin_length_difference_ft"])) <= 0.001
        else "needs_review",
        axis=1,
    )
    write_csv("bin_count_reconciliation_by_chain.csv", recon_chain.reset_index(drop=True))
    write_csv(
        "bin_count_reconciliation_by_approach.csv",
        recon_chain.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
            logical_chain_count=("logical_corridor_chain_id", "count"),
            expected_bin_count=("expected_bin_count", "sum"),
            actual_bin_count=("actual_bin_count", "sum"),
            unreconciled_chain_count=("reconciliation_status", lambda s: int((s != "reconciled").sum())),
        ).reset_index(),
    )
    write_csv(
        "bin_count_reconciliation_by_signal.csv",
        recon_chain.groupby("stable_signal_id", dropna=False).agg(
            signal_approach_count=("signal_approach_id", "nunique"),
            logical_chain_count=("logical_corridor_chain_id", "count"),
            expected_bin_count=("expected_bin_count", "sum"),
            actual_bin_count=("actual_bin_count", "sum"),
            unreconciled_chain_count=("reconciliation_status", lambda s: int((s != "reconciled").sum())),
        ).reset_index(),
    )

    bands = bin_context.groupby("distance_band", dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        total_bin_length_ft=("bin_length_ft", "sum"),
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        signal_approach_count=("signal_approach_id", "nunique"),
        stable_signal_count=("stable_signal_id", "nunique"),
    ).reset_index()
    write_csv("bins_by_distance_band.csv", bands)
    write_csv(
        "distance_band_coverage_by_chain.csv",
        bin_context.groupby(["stable_signal_id", "signal_approach_id", "logical_corridor_chain_id", "distance_band"], dropna=False).agg(
            bin_count=("stable_bin_id", "count"),
            total_bin_length_ft=("bin_length_ft", "sum"),
            min_distance_start_ft=("distance_start_ft", "min"),
            max_distance_end_ft=("distance_end_ft", "max"),
        ).reset_index(),
    )
    write_csv(
        "distance_band_coverage_by_approach.csv",
        bin_context.groupby(["stable_signal_id", "signal_approach_id", "distance_band"], dropna=False).agg(
            bin_count=("stable_bin_id", "count"),
            total_bin_length_ft=("bin_length_ft", "sum"),
            logical_chain_count=("logical_corridor_chain_id", "nunique"),
        ).reset_index(),
    )
    write_csv(
        "distance_band_coverage_by_signal.csv",
        bin_context.groupby(["stable_signal_id", "distance_band"], dropna=False).agg(
            bin_count=("stable_bin_id", "count"),
            total_bin_length_ft=("bin_length_ft", "sum"),
            signal_approach_count=("signal_approach_id", "nunique"),
            logical_chain_count=("logical_corridor_chain_id", "nunique"),
        ).reset_index(),
    )
    write_csv(
        "final_partial_bin_summary.csv",
        bin_context.groupby(["final_partial_bin_flag", "distance_band"], dropna=False).agg(
            bin_count=("stable_bin_id", "count"),
            total_bin_length_ft=("bin_length_ft", "sum"),
            logical_chain_count=("logical_corridor_chain_id", "nunique"),
        ).reset_index(),
    )
    write_csv(
        "multi_segment_bin_summary.csv",
        bin_context.groupby(["multi_segment_bin_status", "segment_boundary_crossing_flag"], dropna=False).agg(
            bin_count=("stable_bin_id", "count"),
            logical_chain_count=("logical_corridor_chain_id", "nunique"),
            total_bin_length_ft=("bin_length_ft", "sum"),
        ).reset_index(),
    )
    write_csv("multi_segment_bin_detail_sample.csv", bin_context[bin_context["segment_overlap_count"] > 1].head(1000).drop(columns=["geometry"], errors="ignore"))
    write_csv("source_measure_status_summary.csv", bin_context.groupby("source_measure_status", dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())
    geometry_summary = bin_context.groupby("geometry_status", dropna=False).agg(bin_count=("stable_bin_id", "count"), logical_chain_count=("logical_corridor_chain_id", "nunique")).reset_index()
    write_csv("geometry_status_summary.csv", geometry_summary)
    write_csv("parent_chain_stop_reason_bin_summary.csv", bin_context.groupby(["parent_corridor_stop_reason", "chain_completeness_status"], dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())
    write_csv("parent_warning_review_status_bin_summary.csv", bin_context.groupby(["parent_corridor_warning_status", "parent_corridor_review_status"], dropna=False).agg(bin_count=("stable_bin_id", "count")).reset_index())

    directionality_null = pd.DataFrame(
        [
            {"check_name": "directionality_status_not_assigned", "fail_count": int((bin_context["directionality_status"] != "not_assigned").sum())},
            {"check_name": "upstream_downstream_null_or_blank", "fail_count": int((bin_context["upstream_downstream"].map(clean) != "").sum())},
        ]
    )
    directionality_null["pass"] = directionality_null["fail_count"].eq(0)
    write_csv("directionality_null_check.csv", directionality_null)

    forbidden_tokens = ["speed", "aadt", "access", "crash", "exposure", "rate"]
    forbidden = [
        {"field_name": col, "forbidden_token": token, "present_flag": True}
        for col in bin_context.columns
        for token in forbidden_tokens
        if token in col.lower()
    ]
    if not forbidden:
        forbidden = [{"field_name": "", "forbidden_token": "", "present_flag": False}]
    write_csv("forbidden_context_enrichment_field_check.csv", forbidden)

    qa = {
        "logical_chains_used": int(ledger["used_for_bin_context"].sum()),
        "bin_rows_generated": int(len(bin_context)),
        "duplicate_stable_bin_id_count": duplicate_id_count,
        "duplicate_chain_distance_interval_count": duplicate_interval_count,
        "distance_validity_fail_count": int(distance_validity["fail_count"].sum()),
        "unreconciled_chain_count": int((recon_chain["reconciliation_status"] != "reconciled").sum()),
        "multi_segment_bin_count": int((bin_context["segment_overlap_count"] > 1).sum()),
        "final_partial_bin_count": int(bin_context["final_partial_bin_flag"].sum()),
        "directionality_null_fail_count": int(directionality_null["fail_count"].sum()),
        "forbidden_context_enrichment_field_count": 0 if not forbidden[0]["present_flag"] else len(forbidden),
        "geometry_deferred": True,
    }
    summary_rows = [{"metric": key, "value": value} for key, value in qa.items()]
    summary_rows.append({"metric": "readiness_decision", "value": decision})
    write_csv("bin_context_build_summary.csv", summary_rows)
    write_csv("bin_context_readiness_decision.csv", [{"decision": decision, "ready_for_validation": decision.endswith("ready_for_validation")}])
    write_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "recommended_next_action": "Run independent bin_context validation audit against staged approach_corridors before directionality assignment."},
            {"priority": 2, "recommended_next_action": "Build the later directionality layer only after the neutral bin surface is validated."},
            {"priority": 3, "recommended_next_action": "Add optional geometry generation as a separate bounded task if map review requires physical bin geometries."},
        ],
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "product": "build_bin_context",
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
            "acceptance_checks": {
                "parent_dependency_check_passed": bool(parent_check["allowed_parent_for_bin_context"].all() and not parent_check["downstream_object_parent_flag"].any()),
                "stable_bin_id_unique": duplicate_id_count == 0,
                "chain_distance_interval_unique": duplicate_interval_count == 0,
                "distance_validity_passed": int(distance_validity["fail_count"].sum()) == 0,
                "bin_count_reconciliation_passed": int((recon_chain["reconciliation_status"] != "reconciled").sum()) == 0,
                "directionality_not_assigned": int(directionality_null["fail_count"].sum()) == 0,
                "forbidden_context_enrichment_fields_absent": not forbidden[0]["present_flag"],
                "geometry_deferred_for_performance": True,
            },
        },
    )
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "bounded_phase": "Phase C.3 only",
            "product": "bin_context",
            "path": rel(BIN_CONTEXT),
            "script": "src.roadway_graph.build.build_bin_context",
            "canonical_parents": [rel(p) for p in PARENTS],
            "diagnostic_evidence_only": [rel(p) for p in DIAGNOSTIC_EVIDENCE],
            "row_count": int(len(bin_context)),
            "logical_chains_used": qa["logical_chains_used"],
            "final_decision": decision,
            "geometry_policy": "Physical bin geometry deferred for performance; source-distance and segment lineage are preserved.",
        },
    )
    return {"bands": bands, "geometry_summary": geometry_summary, **qa}


def update_staging_metadata(bin_context: pd.DataFrame, decision: str, qa: dict[str, Any], write_stats: dict[str, Any]) -> None:
    stamp = now()
    qa_summary = json_safe(
        {
            key: value
            for key, value in qa.items()
            if key not in {"bands", "geometry_summary"}
        }
    )
    manifest = load_json(STAGING_MANIFEST)
    products = manifest.setdefault("products", {})
    products["bin_context"] = {
        "path": rel(BIN_CONTEXT),
        "script": "src.roadway_graph.build.build_bin_context",
        "canonical_parents": [rel(p) for p in PARENTS],
        "diagnostic_evidence_only": [rel(p) for p in DIAGNOSTIC_EVIDENCE],
        "grain": "one row per logical_corridor_chain_id x neutral 50-ft bin interval",
        "row_count": int(len(bin_context)),
        "logical_chain_count": int(bin_context["logical_corridor_chain_id"].nunique()) if not bin_context.empty else 0,
        "build_version": BUILD_VERSION,
        "final_decision": decision,
        "updated_utc": stamp,
        "directionality_status": "not_assigned",
        "upstream_downstream_status": "blank",
        "context_enrichment_status": "not_performed",
        "geometry_policy": "geometry deferred for performance",
        "chunked_write_stats": json_safe(write_stats),
        "qa_review_path": rel(OUT),
        "qa_summary": qa_summary,
    }
    manifest["phase_c3_bin_context_built"] = True
    manifest["updated_utc"] = stamp
    manifest["forbidden_parent_statement"] = "No downstream bin/distance-band/directionality/context/MVP/crash/access/rate objects were used as canonical parents."
    manifest.setdefault("patch_history", []).append(
        {
            "script": "src.roadway_graph.build.build_bin_context",
            "bounded_phase": "Phase C.3 neutral bin_context build only",
            "patched_utc": stamp,
            "row_count": int(len(bin_context)),
            "logical_chain_count": int(bin_context["logical_corridor_chain_id"].nunique()) if not bin_context.empty else 0,
            "final_decision": decision,
            "build_version": BUILD_VERSION,
            "geometry_policy": "geometry_deferred_for_performance",
        }
    )
    write_json(STAGING_MANIFEST, manifest)

    schema = load_json(STAGING_SCHEMA)
    schema.setdefault("tables", {})["bin_context.parquet"] = {
        "canonical_parent": [rel(p) for p in PARENTS],
        "build_version": BUILD_VERSION,
        "grain": "one row per logical_corridor_chain_id x neutral 50-ft bin interval",
        "required_columns": [col for col in BIN_COLUMNS if col != "geometry"],
        "geometry_column": "geometry",
        "geometry_policy": "physical bin geometry deferred by default; geometry_status records deferral",
        "distance_bands": [label for _, _, label in DISTANCE_BANDS],
        "forbidden_fields": "No upstream/downstream assignment and no speed/AADT/access/crash/exposure/rate enrichment fields.",
        "updated_utc": stamp,
    }
    schema["updated_utc"] = stamp
    write_json(STAGING_SCHEMA, schema)

    with STAGING_README.open("a", encoding="utf-8") as f:
        f.write(
            f"""

## Phase C.3 bin_context

Built `{rel(BIN_CONTEXT)}` from validated staged parent objects `signal_index.parquet`,
`travelway_network_index.parquet`, `signal_approaches.parquet`, and
`approach_corridors.parquet` only. The table is a neutral 50-ft bin surface at
`logical_corridor_chain_id x distance interval` grain.

No upstream/downstream labels, directionality, distance-band units, MVP,
speed/AADT/exposure, access, crash, or rate products were built. Physical bin
geometry is deferred for performance; segment-distance, source-measure, and
supporting corridor lineage are preserved.

Decision: `{decision}`.
"""
        )


def write_findings_memo(qa: dict[str, Any], decision: str) -> None:
    bands = qa["bands"]
    band_lines = "\n".join(f"- {row.distance_band}: {int(row.bin_count):,} bins, {float(row.total_bin_length_ft):,.1f} ft" for row in bands.itertuples(index=False))
    geometry_lines = "\n".join(f"- {row.geometry_status}: {int(row.bin_count):,} bins" for row in qa["geometry_summary"].itertuples(index=False))
    runtime = qa.get("runtime_summary", {})
    runtime_lines = "\n".join(
        [
            f"- Chunked write runtime: {float(runtime.get('runtime_seconds', 0.0)):.1f} seconds",
            f"- Parquet chunks written: {int(runtime.get('chunk_count', 0)):,}",
            f"- Rows written during stream: {int(runtime.get('row_count', 0)):,}",
        ]
    )
    memo = f"""# Phase C.3 bin_context Build Findings

## What Was Built
Built staged `bin_context.parquet` as one neutral row per logical corridor chain by 50-ft chain-distance bin interval. Logical chains used: {qa['logical_chains_used']:,}. Bins generated: {qa['bin_rows_generated']:,}.

## What Was Not Built
No upstream/downstream assignment, directionality, distance-band units, MVP, speed/AADT/exposure, access, crash, rate, or other context-enrichment products were built.

## Parent Dependency Statement
Canonical parents were only the four validated staged objects: `signal_index.parquet`, `travelway_network_index.parquet`, `signal_approaches.parquet`, and `approach_corridors.parquet`. Named review folders were diagnostic evidence only, not parents.

## Runtime Summary
{runtime_lines}

## Bin Count Reconciliation
Duplicate stable bin IDs: {qa['duplicate_stable_bin_id_count']:,}. Duplicate chain-distance intervals: {qa['duplicate_chain_distance_interval_count']:,}. Distance validity failures: {qa['distance_validity_fail_count']:,}. Unreconciled chains: {qa['unreconciled_chain_count']:,}.

## Distance-Band Coverage
{band_lines}

## Partial Chains And Final Partial Bins
Bins stop at the lesser of `chain_total_reach_ft` and 2,500 ft. Final intervals shorter than 50 ft were retained with `final_partial_bin_flag = true`. Final partial bins: {qa['final_partial_bin_count']:,}.

## Multi-Segment Bins
Bins crossing Travelway/source-row segment boundaries were kept as one bin row with supporting segment IDs and stable Travelway IDs. Multi-segment bins: {qa['multi_segment_bin_count']:,}.

## Geometry Generation Status
Physical bin geometry was deferred for performance in this neutral cache layer. Geometry can be added later as a bounded geometry task if needed.
{geometry_lines}

## Directionality And Context
`directionality_status` is `not_assigned` for every bin and `upstream_downstream` is blank for every bin. No context-enrichment fields were created; forbidden context-enrichment field count: {qa['forbidden_context_enrichment_field_count']:,}.

## Readiness
Decision: `{decision}`. The staged bin_context is ready for independent validation before any later directionality work.

## Recommended Next Task
Run an independent bin_context validation audit against staged `approach_corridors.parquet`, then build the later directionality layer only after this neutral bin surface is accepted.
"""
    with (OUT / "findings_memo.md").open("w", encoding="utf-8") as f:
        f.write(memo)


def run_benchmark(limit: int) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"Starting bounded benchmark for {limit:,} bin-eligible chains; staged parquet and metadata will not be written.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    if not parent_check["allowed_parent_for_bin_context"].all() or parent_check["downstream_object_parent_flag"].any():
        raise RuntimeError("Parent dependency check failed; benchmark refused.")
    prep_start = time.perf_counter()
    corridors = prepare_corridors(pd.read_parquet(APPROACH_CORRIDORS))
    chains = build_chain_structures(corridors, benchmark_chain_limit=limit)
    used = [chain for chain in chains if chain.used_for_bin_context]
    prep_seconds = time.perf_counter() - prep_start
    start = time.perf_counter()
    rows = 0
    for _row in iter_bin_rows(used):
        rows += 1
    runtime = time.perf_counter() - start
    full_chain_count = int(corridors["logical_corridor_chain_id"].nunique())
    full_expected_rows = sum(expected_bin_count(chain.chain_total_reach_ft) for chain in build_chain_structures(corridors) if chain.used_for_bin_context)
    bins_per_sec = rows / max(runtime, 1e-9)
    projected_generation_seconds = full_expected_rows / max(bins_per_sec, 1e-9)
    result = {
        "benchmark_chain_count": len(used),
        "rows_generated": rows,
        "prep_runtime_seconds": round(prep_seconds, 3),
        "generation_runtime_seconds": round(runtime, 3),
        "bins_per_sec": round(bins_per_sec, 1),
        "chains_per_sec": round(len(used) / max(runtime, 1e-9), 1),
        "full_logical_chain_count_parent": full_chain_count,
        "projected_full_rows": full_expected_rows,
        "projected_generation_seconds": round(projected_generation_seconds, 1),
        "projected_generation_minutes": round(projected_generation_seconds / 60.0, 2),
        "geometry_mode": "deferred",
        "staged_parquet_written": False,
        "schema_or_output_differences": "geometry remains present but null with geometry_status=geometry_deferred_for_performance; stable output columns otherwise preserved",
        "process_rss_mb": "",
    }
    write_csv(f"benchmark_{limit}_chains.csv", [result])
    log(f"Benchmark complete for {len(used):,} chains and {rows:,} rows at {bins_per_sec:,.0f} bins/sec.")
    return result


def run_full_build(chunk_size: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    if not parent_check["allowed_parent_for_bin_context"].all() or parent_check["downstream_object_parent_flag"].any():
        raise RuntimeError("Parent dependency check failed; refusing to build bin_context.")
    log("Reading validated staged parent objects.")
    approaches = pd.read_parquet(SIGNAL_APPROACHES)
    corridors = prepare_corridors(pd.read_parquet(APPROACH_CORRIDORS))
    chains = build_chain_structures(corridors)
    used_count = sum(1 for chain in chains if chain.used_for_bin_context)
    log(f"Prepared {len(chains):,} logical chains; {used_count:,} are bin-eligible.")
    log(f"Writing chunked staged bin_context to {rel(BIN_CONTEXT)} with geometry deferred.")
    write_stats = write_parquet_stream([chain for chain in chains if chain.used_for_bin_context], BIN_CONTEXT, chunk_size=chunk_size)
    log("Reading completed staged bin_context for QA.")
    bin_context = pd.read_parquet(BIN_CONTEXT)
    decision = readiness_decision(bin_context, parent_check)
    qa = write_qa_outputs(bin_context, chains, approaches, parent_check, decision)
    qa["runtime_summary"] = write_stats
    write_findings_memo(qa, decision)
    update_staging_metadata(bin_context, decision, qa, write_stats)
    log(f"Phase C.3 neutral bin_context build complete with decision {decision}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-chains", type=int, default=0, help="Generate rows for the first N bin-eligible chains without writing staged parquet or metadata.")
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS, help="Rows per chunk for the full Parquet writer.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.benchmark_chains:
        result = run_benchmark(args.benchmark_chains)
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    run_full_build(chunk_size=args.chunk_rows)


if __name__ == "__main__":
    main()
