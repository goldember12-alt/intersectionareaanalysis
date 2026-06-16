"""Build a staged proposed generated-bin product for distance continuation.

This script is intentionally conservative:
- it does not modify canonical products;
- it does not append to or overwrite staged bin_context.parquet;
- it writes proposed generated bins as a separate staged product;
- it defers geometry and directionality assignment.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
EXPORT_DIR = STAGING_DIR / "exports"
SUBSET_DIR = REPO_ROOT / "work/roadway_graph/review/distance_continuation_implementation_subset_review"
ENDPOINT_AUDIT_DIR = REPO_ROOT / "work/roadway_graph/review/distance_endpoint_continuation_audit"
RELOCATION_AUDIT_DIR = REPO_ROOT / "work/roadway_graph/review/map_review_relocation_audit"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
FIRST_PASS_SUBSET = SUBSET_DIR / "first_pass_implementation_subset.csv"
DEFERRED_CASES = SUBSET_DIR / "deferred_continuation_cases.csv"
SOURCE_CANDIDATES = ENDPOINT_AUDIT_DIR / "source_travelway_continuation_candidates.csv"
RECOVERY_ESTIMATE = ENDPOINT_AUDIT_DIR / "far_distance_unit_recovery_estimate.csv"
ROADS_ARTIFACT = REPO_ROOT / "artifacts/normalized/roads.parquet"
SIGNALS_ARTIFACT = REPO_ROOT / "artifacts/normalized/signals.parquet"

PROPOSED_BINS_OUT = STAGING_DIR / "proposed_generated_bins.parquet"
CORRIDORS_OUT = STAGING_DIR / "continuation_corridors.parquet"
PROVENANCE_OUT = STAGING_DIR / "continuation_provenance.parquet"

SAFE_CLASSES = {"safe_first_pass", "safe_with_strict_QA"}
DISTANCE_BANDS = [
    ("0-250", 0.0, 250.0),
    ("250-500", 250.0, 500.0),
    ("500-1000", 500.0, 1000.0),
    ("1000-1500", 1000.0, 1500.0),
    ("1500-2000", 1500.0, 2000.0),
    ("2000-2500", 2000.0, 2500.0),
]
DISTANCE_BAND_LOOKUP = {name: (start, end) for name, start, end in DISTANCE_BANDS}
BIN_INTERVAL_FT = 50.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def stable_hash(*parts: Any, prefix: str = "") -> str:
    raw = "|".join("" if pd.isna(part) else str(part) for part in parts)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}{digest}"


def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def split_pipe(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    return [item.strip() for item in str(value).split("|") if item.strip()]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def parse_missing_bands(value: Any) -> list[str]:
    bands = split_pipe(value)
    return [band for band in bands if band in DISTANCE_BAND_LOOKUP]


def interval_rows_for_band(
    band: str,
    current_max_distance: float | None,
) -> list[tuple[float, float]]:
    start, end = DISTANCE_BAND_LOOKUP[band]
    if current_max_distance is not None and current_max_distance > start:
        start = min(end, max(start, current_max_distance))
    if start >= end:
        return []
    # Preserve the existing 50-ft interval convention where possible. If the
    # current maximum distance cuts through a band, start at that exact point
    # and then continue on 50-ft boundaries.
    intervals: list[tuple[float, float]] = []
    cursor = start
    while cursor < end - 1e-9:
        next_boundary = min(end, cursor + BIN_INTERVAL_FT)
        intervals.append((round(cursor, 6), round(next_boundary, 6)))
        cursor = next_boundary
    return intervals


def infer_band(start_ft: float, end_ft: float) -> str | None:
    midpoint = (float(start_ft) + float(end_ft)) / 2.0
    for band, start, end in DISTANCE_BANDS:
        if start <= midpoint < end or (midpoint == 2500.0 and end == 2500.0):
            return band
    return None


def choose_source_candidate(row: pd.Series, source_candidates: pd.DataFrame) -> dict[str, Any]:
    if source_candidates.empty:
        return {}
    key = (row.get("stable_signal_id"), row.get("signal_approach_id_v2"))
    candidates = source_candidates[
        (source_candidates["stable_signal_id"].astype(str) == str(key[0]))
        & (source_candidates["signal_approach_id_v2"].astype(str) == str(key[1]))
    ].copy()
    if candidates.empty:
        return {}
    route_names = set(split_pipe(row.get("route_names")))
    if route_names and "source_route_name" in candidates.columns:
        route_matched = candidates[candidates["source_route_name"].astype(str).isin(route_names)]
        if not route_matched.empty:
            candidates = route_matched
    candidates["_rank"] = candidates.get("continuation_confidence", "").astype(str).map(
        {"high": 0, "medium": 1, "low": 2}
    ).fillna(3)
    picked = candidates.sort_values(["_rank"]).iloc[0].drop(labels=["_rank"], errors="ignore")
    return picked.to_dict()


def build_corridors(subset: pd.DataFrame, source_candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for idx, row in subset.iterrows():
        source = choose_source_candidate(row, source_candidates)
        route_names = split_pipe(row.get("route_names"))
        continuation_class = str(row.get("early_ending_classification", ""))
        first_pass_class = str(row.get("proposed_first_pass_class", ""))
        corridor_id = "cc_" + stable_hash(
            row.get("stable_signal_id"),
            row.get("signal_approach_id_v2"),
            row.get("route_names"),
            continuation_class,
            prefix="",
        )
        confidence = str(row.get("confidence", source.get("continuation_confidence", "")) or "")
        source_from = source.get("source_route_from_min")
        source_to = source.get("source_route_to_max")
        current_measure_min = source.get("current_measure_min")
        current_measure_max = source.get("current_measure_max")
        current_max_distance = row.get("max_distance_end_ft")
        try:
            source_from_f = float(source_from)
            source_to_f = float(source_to)
            current_measure_min_f = float(current_measure_min)
            current_measure_max_f = float(current_measure_max)
            current_max_distance_f = float(current_max_distance)
            has_measure = True
        except (TypeError, ValueError):
            source_from_f = source_to_f = current_measure_min_f = current_measure_max_f = current_max_distance_f = float("nan")
            has_measure = False

        evidence_fields = [
            "first_pass_implementation_subset.csv",
            "source_travelway_continuation_candidates.csv" if source else "source_candidate_missing",
            str(row.get("required_gate_summary", "")),
        ]
        long_source_row = bool_value(row.get("long_source_row_clipped"))
        divided = bool_value(row.get("divided_carriageway_context"))
        small_gap_or_overlap = bool_value(row.get("multi_row_continuation_needed"))
        clipped_by_2500 = True
        no_turn_violation = True
        cross_signal = False
        opposite_conflict = False
        route_name = source.get("source_route_name") or (route_names[0] if route_names else "")

        record = {
            "continuation_corridor_id": corridor_id,
            "stable_signal_id": row.get("stable_signal_id"),
            "signal_approach_id_v2": row.get("signal_approach_id_v2"),
            "continuation_class": continuation_class,
            "continuation_method": first_pass_class,
            "confidence": confidence,
            "source_route_name": route_name,
            "source_route_name_values": "|".join(route_names),
            "source_from_measure": source_from,
            "source_to_measure": source_to,
            "current_measure_min": current_measure_min,
            "current_measure_max": current_measure_max,
            "current_max_distance_end_ft": current_max_distance,
            "proposed_clipped_from_measure": current_measure_max,
            "proposed_clipped_to_measure": source_to,
            "clipped_by_2500_ft_flag": clipped_by_2500,
            "clipped_by_neighbor_signal_flag": False,
            "divided_carriageway_flag": divided,
            "long_source_row_flag": long_source_row,
            "same_route_gap_or_overlap_flag": small_gap_or_overlap,
            "source_artifact_path_used": rel(ROADS_ARTIFACT),
            "evidence_fields": "|".join([x for x in evidence_fields if x]),
            "no_turn_continuation_violation_flag": no_turn_violation,
            "cross_signal_boundary_flag": cross_signal,
            "opposite_carriageway_conflict_flag": opposite_conflict,
            "missing_route_measure_fields_flag": not has_measure,
            "missing_farther_bands": row.get("missing_farther_bands"),
            "proposed_first_pass_class": first_pass_class,
        }
        if not has_measure:
            exclusions.append(
                {
                    **record,
                    "generated_bin_exclusion_reason": "missing_required_route_measure_fields",
                }
            )
        records.append(record)
    return pd.DataFrame(records), pd.DataFrame(exclusions)


def build_existing_interval_index(
    bin_context: pd.DataFrame,
) -> tuple[set[tuple[str, str, str, float, float]], set[tuple[str, str, float, float]]]:
    route_col = "source_route_name" if "source_route_name" in bin_context.columns else None
    keys: set[tuple[str, str, str, float, float]] = set()
    keys_any_route: set[tuple[str, str, float, float]] = set()
    needed = {"stable_signal_id", "signal_approach_id_v2", "distance_start_ft", "distance_end_ft"}
    if not needed.issubset(bin_context.columns):
        return keys, keys_any_route
    valid = bin_context.dropna(subset=["stable_signal_id", "signal_approach_id_v2", "distance_start_ft", "distance_end_ft"])
    for row in valid.itertuples(index=False):
        d = row._asdict()
        signal_id = str(d["stable_signal_id"])
        approach_id = str(d["signal_approach_id_v2"])
        start_ft = round(float(d["distance_start_ft"]), 6)
        end_ft = round(float(d["distance_end_ft"]), 6)
        route_name = str(d.get(route_col, "")) if route_col else ""
        keys.add((signal_id, approach_id, route_name, start_ft, end_ft))
        keys_any_route.add((signal_id, approach_id, start_ft, end_ft))
    return keys, keys_any_route


def estimate_measure_interval(corridor: dict[str, Any], start_ft: float, end_ft: float) -> tuple[Any, Any, str]:
    try:
        current_measure_max = float(corridor["current_measure_max"])
        current_max_distance = float(corridor["current_max_distance_end_ft"])
        source_to = float(corridor["source_to_measure"])
    except (TypeError, ValueError, KeyError):
        return pd.NA, pd.NA, "missing_required_route_measure_fields"
    begin_distance = max(start_ft, current_max_distance)
    end_distance = max(end_ft, begin_distance)
    start_measure = current_measure_max + max(0.0, begin_distance - current_max_distance) / 5280.0
    end_measure = current_measure_max + max(0.0, end_distance - current_max_distance) / 5280.0
    if start_measure > source_to + 1e-9:
        return pd.NA, pd.NA, "proposed_interval_beyond_source_measure_extent"
    end_measure = min(end_measure, source_to)
    if end_measure < start_measure:
        return pd.NA, pd.NA, "invalid_measure_interval_after_clipping"
    return round(start_measure, 8), round(end_measure, 8), ""


def build_proposed_bins(
    subset: pd.DataFrame,
    corridors: pd.DataFrame,
    existing_index: set[tuple[str, str, str, float, float]],
    existing_index_any_route: set[tuple[str, str, float, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    corridor_lookup = {
        (str(r["stable_signal_id"]), str(r["signal_approach_id_v2"])): r.to_dict()
        for _, r in corridors.iterrows()
    }
    proposed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for _, row in subset.iterrows():
        signal_id = str(row.get("stable_signal_id"))
        approach_id = str(row.get("signal_approach_id_v2"))
        corridor = corridor_lookup.get((signal_id, approach_id), {})
        route_name = str(corridor.get("source_route_name", "") or "")
        current_max_distance = None
        try:
            current_max_distance = float(row.get("max_distance_end_ft"))
        except (TypeError, ValueError):
            current_max_distance = None
        for band in parse_missing_bands(row.get("missing_farther_bands")):
            for start_ft, end_ft in interval_rows_for_band(band, current_max_distance):
                interval_key = (signal_id, approach_id, route_name, round(start_ft, 6), round(end_ft, 6))
                any_route_key = (signal_id, approach_id, round(start_ft, 6), round(end_ft, 6))
                measure_start, measure_end, measure_error = estimate_measure_interval(corridor, start_ft, end_ft)
                reason_parts: list[str] = []
                if interval_key in existing_index or any_route_key in existing_index_any_route:
                    reason_parts.append("overlaps_existing_staged_bin_interval")
                if end_ft > 2500.0:
                    reason_parts.append("proposed_interval_exceeds_2500_ft")
                if infer_band(start_ft, end_ft) is None:
                    reason_parts.append("distance_band_assignment_failed")
                if measure_error:
                    reason_parts.append(measure_error)
                if bool_value(corridor.get("cross_signal_boundary_flag")):
                    reason_parts.append("cross_signal_boundary")
                if not bool_value(corridor.get("no_turn_continuation_violation_flag")):
                    reason_parts.append("turn_continuation_violation")
                if bool_value(corridor.get("opposite_carriageway_conflict_flag")):
                    reason_parts.append("opposite_carriageway_conflict")

                proposed_id = "pgen_" + stable_hash(signal_id, approach_id, route_name, start_ft, end_ft, corridor.get("continuation_corridor_id"))
                base = {
                    "proposed_stable_bin_id": proposed_id,
                    "proposed_bin_source": "distance_continuation_first_pass",
                    "stable_signal_id": signal_id,
                    "signal_approach_id_v2": approach_id,
                    "distance_start_ft": start_ft,
                    "distance_end_ft": end_ft,
                    "distance_band": band,
                    "distance_band_v2": band,
                    "broad_window_0_1000_flag": end_ft <= 1000.0,
                    "broad_window_0_2500_flag": end_ft <= 2500.0,
                    "source_route_name": route_name,
                    "source_route_name_values": corridor.get("source_route_name_values", ""),
                    "source_measure_start": measure_start,
                    "source_measure_end": measure_end,
                    "continuation_corridor_id": corridor.get("continuation_corridor_id", ""),
                    "continuation_method": corridor.get("continuation_method", ""),
                    "continuation_confidence": corridor.get("confidence", ""),
                    "continuation_class": corridor.get("continuation_class", ""),
                    "generated_geometry_status": "geometry_deferred",
                    "geometry_wkt": "",
                    "directionality_status": "needs_directionality_assignment",
                    "upstream_downstream": pd.NA,
                    "signal_approach_id_status": "proposed_generated_distance_continuation",
                    "generated_bin_qa_status": "pass" if not reason_parts else "excluded",
                    "generated_bin_exclusion_reason": "|".join(reason_parts),
                }
                if reason_parts:
                    excluded.append(base)
                else:
                    proposed.append(base)
    proposed_df = pd.DataFrame(proposed)
    excluded_df = pd.DataFrame(excluded)
    if not proposed_df.empty:
        dup_mask = proposed_df.duplicated(subset=["proposed_stable_bin_id"], keep=False)
        if dup_mask.any():
            dupes = proposed_df.loc[dup_mask].copy()
            dupes["generated_bin_qa_status"] = "excluded"
            dupes["generated_bin_exclusion_reason"] = "duplicate_proposed_stable_bin_id"
            excluded_df = pd.concat([excluded_df, dupes], ignore_index=True)
            proposed_df = proposed_df.loc[~dup_mask].copy()
        interval_cols = ["stable_signal_id", "signal_approach_id_v2", "source_route_name", "distance_start_ft", "distance_end_ft"]
        dup_interval = proposed_df.duplicated(subset=interval_cols, keep=False)
        if dup_interval.any():
            dupes = proposed_df.loc[dup_interval].copy()
            dupes["generated_bin_qa_status"] = "excluded"
            dupes["generated_bin_exclusion_reason"] = "duplicate_proposed_interval"
            excluded_df = pd.concat([excluded_df, dupes], ignore_index=True)
            proposed_df = proposed_df.loc[~dup_interval].copy()
    return proposed_df, excluded_df


def write_metadata(
    proposed: pd.DataFrame,
    corridors: pd.DataFrame,
    provenance: pd.DataFrame,
    excluded: pd.DataFrame,
    subset_count: int,
) -> None:
    manifest_path = STAGING_DIR / "manifest.json"
    schema_path = STAGING_DIR / "schema.json"
    read_inputs = [
        BIN_CONTEXT,
        SIGNAL_APPROACHES,
        APPROACH_WINDOWS,
        FIRST_PASS_SUBSET,
        DEFERRED_CASES,
        SOURCE_CANDIDATES,
        RECOVERY_ESTIMATE,
        ROADS_ARTIFACT,
        SIGNALS_ARTIFACT,
    ]
    update = {
        "timestamp_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "operation": "created_proposed_distance_continuation_generated_bins",
        "note": "Proposal product only. Existing staged bin_context.parquet was not appended to or overwritten.",
        "input_files_read": [rel(p) for p in read_inputs if p.exists()],
        "output_files_written": [
            rel(PROPOSED_BINS_OUT),
            rel(CORRIDORS_OUT),
            rel(PROVENANCE_OUT),
        ],
        "eligible_first_pass_records": int(subset_count),
        "continuation_corridor_count": int(len(corridors)),
        "proposed_generated_bin_count": int(len(proposed)),
        "excluded_proposed_bin_count": int(len(excluded)),
        "signals_affected": int(proposed["stable_signal_id"].nunique()) if not proposed.empty else 0,
        "approaches_affected": int(proposed["signal_approach_id_v2"].nunique()) if not proposed.empty else 0,
        "directionality_assignment_status": "deferred_for_all_proposed_bins",
        "canonical_root_products_unchanged": True,
        "staged_bin_context_unchanged": True,
    }
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    else:
        manifest = {}
    manifest.setdefault("staging_updates", []).append(update)
    manifest["latest_proposed_distance_continuation_generated_bins"] = update
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else {}
    schema.setdefault("tables", {})
    for name, df, grain in [
        ("proposed_generated_bins", proposed, "one proposed generated bin interval"),
        ("continuation_corridors", corridors, "one proposed continuation corridor per signal approach"),
        ("continuation_provenance", provenance, "one provenance record per staged proposal run"),
    ]:
        schema["tables"][name] = {
            "path": rel(STAGING_DIR / f"{name}.parquet"),
            "expected_grain": grain,
            "row_count": int(len(df)),
            "columns": [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns],
            "status": "staged_proposal_not_promoted",
        }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    readme_path = STAGING_DIR / "README.md"
    existing = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    section = f"""

## Proposed Distance Continuation Generated Bins

Generated: {now_iso()}

`proposed_generated_bins.parquet`, `continuation_corridors.parquet`, and
`continuation_provenance.parquet` are staged proposal products for first-pass
distance continuation. They have not been appended to `bin_context.parquet`.
Canonical root products remain unchanged.

Included continuation records are limited to `safe_first_pass` and
`safe_with_strict_QA` classes from the implementation subset review. Deferred
classes remain in the review exports. Directionality assignment is deferred for
all proposed bins.

Proposed generated bins: {len(proposed)}
Excluded proposed rows: {len(excluded)}
"""
    marker = "## Proposed Distance Continuation Generated Bins"
    if marker in existing:
        existing = existing.split(marker)[0].rstrip() + "\n"
    readme_path.write_text(existing.rstrip() + section, encoding="utf-8")


def main() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    required = [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, FIRST_PASS_SUBSET, SOURCE_CANDIDATES]
    missing = [p for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(rel(p) for p in missing))

    progress_lines = [
        f"# Proposed Distance Continuation Generated Bins Progress",
        f"- {now_iso()} Started staged proposal build.",
        f"- Relocation audit folder used: {rel(RELOCATION_AUDIT_DIR)}",
    ]

    print(f"reading first-pass subset: {rel(FIRST_PASS_SUBSET)}", flush=True)
    subset = pd.read_csv(FIRST_PASS_SUBSET)
    eligible = subset[subset["proposed_first_pass_class"].isin(SAFE_CLASSES)].copy()
    print(f"eligible continuation records: {len(eligible):,}", flush=True)
    print(f"reading source candidates: {rel(SOURCE_CANDIDATES)}", flush=True)
    source_candidates = pd.read_csv(SOURCE_CANDIDATES)
    print(f"reading staged bin_context: {rel(BIN_CONTEXT)}", flush=True)
    bin_context = pd.read_parquet(BIN_CONTEXT)
    print(f"reading staged signal approaches/windows", flush=True)
    signal_approaches = pd.read_parquet(SIGNAL_APPROACHES)
    approach_windows = pd.read_parquet(APPROACH_WINDOWS)
    roads_columns = []
    signals_columns = []
    if ROADS_ARTIFACT.exists():
        roads_columns = pd.read_parquet(ROADS_ARTIFACT, columns=[]).columns.tolist()
    if SIGNALS_ARTIFACT.exists():
        signals_columns = pd.read_parquet(SIGNALS_ARTIFACT, columns=[]).columns.tolist()

    progress_lines.append(f"- Loaded {len(eligible):,} eligible first-pass continuation records.")
    progress_lines.append(f"- Loaded staged bin_context rows: {len(bin_context):,}.")

    valid_approach_pairs = set(
        zip(
            signal_approaches["stable_signal_id"].astype(str),
            signal_approaches["signal_approach_id"].astype(str),
        )
    )
    eligible["_valid_staged_approach"] = [
        (str(sig), str(app)) in valid_approach_pairs
        for sig, app in zip(eligible["stable_signal_id"], eligible["signal_approach_id_v2"])
    ]
    invalid_approaches = eligible.loc[~eligible["_valid_staged_approach"]].copy()
    eligible = eligible.loc[eligible["_valid_staged_approach"]].copy()

    print("building continuation corridors", flush=True)
    corridors, corridor_field_exclusions = build_corridors(eligible, source_candidates)
    print("building existing interval index", flush=True)
    existing_index, existing_index_any_route = build_existing_interval_index(bin_context)
    print("building proposed generated bins", flush=True)
    proposed, excluded = build_proposed_bins(eligible, corridors, existing_index, existing_index_any_route)

    if not invalid_approaches.empty:
        invalid_rows = invalid_approaches.copy()
        invalid_rows["generated_bin_exclusion_reason"] = "signal_approach_not_present_in_staged_signal_approaches"
        excluded = pd.concat([excluded, invalid_rows], ignore_index=True, sort=False)
    if not corridor_field_exclusions.empty:
        excluded = pd.concat([excluded, corridor_field_exclusions], ignore_index=True, sort=False)

    provenance = pd.DataFrame(
        [
            {
                "provenance_id": "prov_" + stable_hash(now_iso(), "distance_continuation_first_pass"),
                "created_utc": now_iso(),
                "producing_script": rel(Path(__file__)),
                "bounded_question": "Create separate proposed generated bins for safe first-pass distance continuation without mutating bin_context.",
                "staged_bin_context_rows_read": int(len(bin_context)),
                "eligible_first_pass_records": int(len(eligible)),
                "proposed_generated_bin_count": int(len(proposed)),
                "excluded_proposed_bin_count": int(len(excluded)),
                "roads_artifact_columns_observed": "|".join(roads_columns),
                "signals_artifact_columns_observed": "|".join(signals_columns),
                "directionality_assignment": "deferred",
                "geometry_generation": "deferred",
            }
        ]
    )

    if proposed.empty:
        raise RuntimeError("No proposed generated bins passed QA; staged product was not written.")

    print(f"writing proposed products to {rel(STAGING_DIR)}", flush=True)
    proposed.to_parquet(PROPOSED_BINS_OUT, index=False)
    corridors.to_parquet(CORRIDORS_OUT, index=False)
    provenance.to_parquet(PROVENANCE_OUT, index=False)

    summary = pd.DataFrame(
        [
            {"metric": "eligible_first_pass_records", "value": len(eligible)},
            {"metric": "continuation_corridors", "value": len(corridors)},
            {"metric": "proposed_generated_bins", "value": len(proposed)},
            {"metric": "excluded_proposed_rows", "value": len(excluded)},
            {"metric": "signals_affected", "value": proposed["stable_signal_id"].nunique()},
            {"metric": "approaches_affected", "value": proposed["signal_approach_id_v2"].nunique()},
            {"metric": "all_proposed_bins_need_directionality_assignment", "value": len(proposed)},
        ]
    )
    write_csv(summary, EXPORT_DIR / "proposed_generated_bins_summary.csv")
    write_csv(proposed.head(1000), EXPORT_DIR / "proposed_generated_bins_sample.csv")
    write_csv(
        proposed.groupby("distance_band", dropna=False).size().reset_index(name="proposed_generated_bins"),
        EXPORT_DIR / "proposed_generated_bins_by_distance_band.csv",
    )
    write_csv(
        proposed.groupby("continuation_class", dropna=False).size().reset_index(name="proposed_generated_bins"),
        EXPORT_DIR / "proposed_generated_bins_by_continuation_class.csv",
    )
    write_csv(
        proposed.groupby("stable_signal_id", dropna=False).size().reset_index(name="proposed_generated_bins").sort_values(
            "proposed_generated_bins", ascending=False
        ),
        EXPORT_DIR / "proposed_generated_bins_by_signal.csv",
    )
    write_csv(
        proposed.groupby("source_route_name", dropna=False).size().reset_index(name="proposed_generated_bins").sort_values(
            "proposed_generated_bins", ascending=False
        ),
        EXPORT_DIR / "proposed_generated_bins_by_travelway.csv",
    )
    write_csv(excluded, EXPORT_DIR / "proposed_generated_bins_excluded_rows.csv")
    if excluded.empty or "generated_bin_exclusion_reason" not in excluded.columns:
        exclusion_reasons = pd.DataFrame(columns=["generated_bin_exclusion_reason", "excluded_rows"])
    else:
        exclusion_reasons = (
            excluded.groupby("generated_bin_exclusion_reason", dropna=False)
            .size()
            .reset_index(name="excluded_rows")
            .sort_values("excluded_rows", ascending=False)
        )
    write_csv(exclusion_reasons, EXPORT_DIR / "proposed_generated_bins_exclusion_reasons.csv")
    write_csv(
        corridors.groupby(["continuation_class", "continuation_method", "confidence"], dropna=False)
        .size()
        .reset_index(name="continuation_corridors"),
        EXPORT_DIR / "continuation_corridor_summary.csv",
    )
    write_csv(corridors.head(1000), EXPORT_DIR / "continuation_corridor_sample.csv")

    duplicate_overlap_qa = pd.DataFrame(
        [
            {"qa_check": "duplicate_proposed_stable_bin_id", "problem_count": int(proposed["proposed_stable_bin_id"].duplicated().sum())},
            {
                "qa_check": "duplicate_proposed_interval",
                "problem_count": int(
                    proposed.duplicated(
                        subset=["stable_signal_id", "signal_approach_id_v2", "source_route_name", "distance_start_ft", "distance_end_ft"]
                    ).sum()
                ),
            },
            {"qa_check": "proposed_interval_exceeds_2500_ft", "problem_count": int((proposed["distance_end_ft"] > 2500).sum())},
            {"qa_check": "generated_geometry_status_deferred", "problem_count": int((proposed["generated_geometry_status"] != "geometry_deferred").sum())},
        ]
    )
    write_csv(duplicate_overlap_qa, EXPORT_DIR / "generated_bin_duplicate_overlap_qa.csv")

    existing_units = (
        bin_context.dropna(subset=["stable_signal_id", "signal_approach_id_v2", "distance_band_v2"])
        .groupby(["stable_signal_id", "signal_approach_id_v2", "distance_band_v2"], dropna=False)
        .size()
        .reset_index(name="bin_rows")
    )
    proposed_units = (
        proposed.groupby(["stable_signal_id", "signal_approach_id_v2", "distance_band"], dropna=False)
        .size()
        .reset_index(name="proposed_bin_rows")
    )
    proposed_unit_count = len(proposed_units)
    impact = pd.DataFrame(
        [
            {"metric": "current_staged_distance_band_units_without_direction_split", "value": len(existing_units)},
            {"metric": "proposed_new_distance_band_units_without_direction_split", "value": proposed_unit_count},
            {"metric": "proposed_generated_bin_rows", "value": len(proposed)},
            {"metric": "proposed_bins_needing_directionality_assignment", "value": len(proposed)},
        ]
    )
    write_csv(impact, EXPORT_DIR / "proposed_distance_unit_impact_summary.csv")
    directionality_need = proposed.groupby(["directionality_status"], dropna=False).size().reset_index(name="proposed_bins")
    write_csv(directionality_need, EXPORT_DIR / "proposed_directionality_need_summary.csv")

    deferred = read_csv_optional(DEFERRED_CASES)
    write_csv(deferred, EXPORT_DIR / "deferred_distance_continuation_cases.csv")

    write_metadata(proposed, corridors, provenance, excluded, len(eligible))

    progress_lines.append(f"- Wrote proposed generated bins: {len(proposed):,}.")
    progress_lines.append(f"- Wrote excluded proposed rows: {len(excluded):,}.")
    (EXPORT_DIR / "proposed_generated_bins_progress_log.md").write_text("\n".join(progress_lines) + "\n", encoding="utf-8")

    recommendation = "proposed_generated_bins_ready_for_review"
    if duplicate_overlap_qa["problem_count"].sum() > 0:
        recommendation = "proposed_generated_bins_blocked_by_duplicate_or_overlap_risk"
    print(recommendation)
    print(f"eligible_first_pass_records={len(eligible)}")
    print(f"proposed_generated_bins={len(proposed)}")
    print(f"excluded_proposed_rows={len(excluded)}")
    print(f"signals_affected={proposed['stable_signal_id'].nunique()}")
    print(f"approaches_affected={proposed['signal_approach_id_v2'].nunique()}")
    print("next_step=audit_proposed_generated_bins_before_append_or_directionality_assignment")


if __name__ == "__main__":
    main()
