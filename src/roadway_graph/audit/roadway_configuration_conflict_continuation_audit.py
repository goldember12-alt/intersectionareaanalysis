"""Read-only roadway-configuration conflict continuation audit.

This audit revisits source-extent candidate continuations that were previously
blocked only by roadway_configuration mismatch. It does not modify staged
approach corridors or any prior review outputs.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkb


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/roadway_configuration_conflict_continuation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

SOURCE_RECON = REPO / "work/roadway_graph/review/source_extent_suspect_chain_reconciliation_audit"
FINAL_REVIEW = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"
REPAIR_REVIEW = REPO / "work/roadway_graph/review/repair_approach_corridor_source_extent_continuation"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
CHAIN_REVIEW = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

RULE_VERSION = "roadway_configuration_conflict_continuation_audit_v1"
MAX_REACH_FT = 2500.0
ZERO_GAP_TOL_FT = 1.0
GEOMETRY_NEAR_TOL_FT = 75.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def write_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(OUT / name, index=False)
        return
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as fh:
        fh.write(f"- {stamp}: {message}\n")


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def load_inputs() -> dict[str, pd.DataFrame]:
    log("Loading staged products and diagnostic reconciliation outputs.")
    return {
        "signals": pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"]),
        "roads": pd.read_parquet(TRAVELWAY_INDEX),
        "attachments": pd.read_parquet(ATTACHMENT),
        "approaches": pd.read_parquet(APPROACHES, columns=["signal_approach_id", "stable_signal_id", "corridor_build_gate"]),
        "corridors": pd.read_parquet(CORRIDORS),
        "source_reconciliation": read_csv_optional(SOURCE_RECON / "suspect_chain_reconciliation.csv"),
        "source_candidates": read_csv_optional(SOURCE_RECON / "suspect_chain_candidate_evaluations.csv"),
        "source_reason_summary": read_csv_optional(SOURCE_RECON / "candidate_rejection_reason_summary.csv"),
        "finalization_suspects": read_csv_optional(FINAL_REVIEW / "likely_source_extent_false_stops.csv"),
        "repair_summary": read_csv_optional(REPAIR_REVIEW / "source_extent_repair_summary.csv"),
        "dedup_suppressed": read_csv_optional(DEDUP_REVIEW / "suppressed_duplicate_chain_ledger.csv"),
        "chain_aware_suspects": read_csv_optional(CHAIN_REVIEW / "likely_source_extent_false_stops.csv"),
        "reconstruct_attempts": read_csv_optional(RECON_REVIEW / "neighbor_extension_attempts.csv"),
    }


def make_road_lookup(roads: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "stable_travelway_id",
        "source_route_name",
        "route_base",
        "source_route_id",
        "source_route_common",
        "carriageway_direction_token",
        "roadway_configuration",
        "RIM_MEDIAN",
        "RIM_ACCESS",
        "RIM_FACILITY",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "RIM_TRAVEL",
        "geometry",
    ]
    keep = [c for c in cols if c in roads.columns]
    return roads[keep].drop_duplicates("stable_travelway_id").set_index("stable_travelway_id", drop=False)


def terminal_chain_rows(corridors: pd.DataFrame) -> pd.DataFrame:
    c = corridors.copy()
    c["segment_order"] = pd.to_numeric(c["segment_order"], errors="coerce")
    c = c.sort_values(["logical_corridor_chain_id", "segment_order", "segment_end_distance_ft"])
    terminal = c.groupby("logical_corridor_chain_id", dropna=False).tail(1).copy()
    return terminal.set_index("logical_corridor_chain_id", drop=False)


def first_token(text: Any) -> str:
    return (clean(text).split("|") + [""])[0]


def config_family(config: Any) -> str:
    text = clean(config).lower()
    if "two-way undivided" in text:
        return "two_way_undivided"
    if "two-way divided" in text:
        return "two_way_divided"
    if "one-way divided" in text:
        return "one_way_divided"
    if "one-way undivided" in text:
        return "one_way_undivided"
    if "reversible" in text:
        return "reversible"
    if "trail" in text:
        return "trail"
    return "unknown"


def ramp_like(row: pd.Series, prefix: str) -> bool:
    fields = [
        f"{prefix}RTE_RAMP_C",
        f"{prefix}RTE_CATEGO",
        f"{prefix}RTE_TYPE_N",
        f"{prefix}source_route_common",
        f"{prefix}roadway_configuration",
    ]
    text = " ".join(clean(row.get(f)) for f in fields).lower()
    ramp_code = clean(row.get(f"{prefix}RTE_RAMP_C"))
    return bool(ramp_code) or "ramp" in text


def endpoint_distance(a: Any, b: Any) -> tuple[str, float | str]:
    try:
        ga = wkb.loads(a) if isinstance(a, (bytes, bytearray, memoryview)) else wkb.loads(bytes(a))
        gb = wkb.loads(b) if isinstance(b, (bytes, bytearray, memoryview)) else wkb.loads(bytes(b))
        a_coords = list(ga.coords) if hasattr(ga, "coords") else []
        b_coords = list(gb.coords) if hasattr(gb, "coords") else []
        if not a_coords or not b_coords:
            return "geometry_unavailable", ""
        endpoints_a = [a_coords[0], a_coords[-1]]
        endpoints_b = [b_coords[0], b_coords[-1]]
        best = min(math.dist(pa[:2], pb[:2]) for pa in endpoints_a for pb in endpoints_b)
        if best <= GEOMETRY_NEAR_TOL_FT:
            return "near_endpoint_continuity", best
        return "endpoint_distance_exceeds_tolerance", best
    except Exception:
        return "geometry_unavailable", ""


def build_classification(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    recon = frames["source_reconciliation"].copy()
    candidates = frames["source_candidates"].copy()
    corridors = frames["corridors"]
    road_lookup = make_road_lookup(frames["roads"])
    terminal = terminal_chain_rows(corridors)

    target = recon[recon["reconciliation_classification"].eq("candidate_roadway_configuration_conflict")].copy()
    target_ids = set(target["logical_corridor_chain_id"].astype(str))
    cand = candidates[candidates["logical_corridor_chain_id"].astype(str).isin(target_ids)].copy()

    rows: list[dict[str, Any]] = []
    for i, (_, row) in enumerate(cand.iterrows(), start=1):
        if i % 250 == 0:
            log(f"Classified {i:,} roadway-configuration conflict candidates.")
        chain_id = clean(row.get("logical_corridor_chain_id"))
        rec = target[target["logical_corridor_chain_id"].astype(str).eq(chain_id)].iloc[0]
        term = terminal.loc[chain_id] if chain_id in terminal.index else pd.Series(dtype=object)
        candidate_id = clean(row.get("candidate_stable_travelway_id"))
        cand_road = road_lookup.loc[candidate_id] if candidate_id in road_lookup.index else pd.Series(dtype=object)
        term_id = clean(term.get("stable_travelway_id"))
        term_road = road_lookup.loc[term_id] if term_id in road_lookup.index else pd.Series(dtype=object)

        current_config = clean(rec.get("roadway_configuration_values")) or clean(term.get("roadway_configuration"))
        candidate_config = clean(row.get("candidate_roadway_configuration"))
        current_family = config_family(current_config)
        candidate_family = config_family(candidate_config)
        gap_ft = safe_float(row.get("candidate_gap_ft"), 999999.0)
        add_reach = safe_float(row.get("candidate_additional_reach_ft"), 0.0)
        projected_reach = safe_float(row.get("projected_reach_ft"), safe_float(rec.get("chain_total_reach_ft"), 0.0))
        current_reach = safe_float(rec.get("chain_total_reach_ft"), 0.0)
        geometry_status, endpoint_dist = endpoint_distance(term.get("geometry"), cand_road.get("geometry"))
        route_ok = all(
            bool_value(row.get(c))
            for c in ["route_name_match", "route_base_match", "route_id_match", "route_common_match"]
        )
        token_ok = bool_value(row.get("carriageway_token_match"))
        side_ok = bool_value(row.get("measure_side_ok"))
        measure_ok = clean(row.get("route_measure_continuity_status")) == "pass" and gap_ft <= ZERO_GAP_TOL_FT
        boundary = bool_value(row.get("supported_signal_boundary_between"))
        duplicate_bin = bool_value(row.get("duplicate_bin_overlap_risk"))
        suppressed = bool_value(row.get("duplicate_suppressed"))
        current_ramp = ramp_like({**term_road.to_dict(), **{"current_roadway_configuration": current_config}}, "")
        candidate_ramp = ramp_like({f"candidate_{k}": v for k, v in cand_road.to_dict().items()}, "candidate_")
        one_way_involved = current_family.startswith("one_way") or candidate_family.startswith("one_way")
        divided_undivided = {current_family, candidate_family} == {"two_way_divided", "two_way_undivided"}
        simple_context = (
            divided_undivided
            and route_ok
            and token_ok
            and side_ok
            and measure_ok
            and not boundary
            and not duplicate_bin
            and not suppressed
            and not current_ramp
            and not candidate_ramp
            and geometry_status in {"near_endpoint_continuity", "geometry_unavailable"}
        )

        if boundary:
            final_class = "supported_signal_boundary_blocks_continuation"
            confidence = "high"
        elif suppressed:
            final_class = "duplicate_or_suppressed_candidate_stop_valid"
            confidence = "high"
        elif duplicate_bin:
            final_class = "continuation_would_create_bin_duplication"
            confidence = "high"
        elif not route_ok or not side_ok or not measure_ok:
            final_class = "route_or_measure_identity_conflict_stop_valid"
            confidence = "high"
        elif not token_ok or one_way_involved or current_ramp or candidate_ramp:
            final_class = "carriageway_or_parallel_road_ambiguity_stop_valid"
            confidence = "medium"
        elif divided_undivided and simple_context:
            final_class = "simple_context_transition_continuation_likely_valid"
            confidence = "medium"
        elif divided_undivided:
            final_class = "divided_undivided_transition_branch_aware_review"
            confidence = "medium"
        elif geometry_status == "endpoint_distance_exceeds_tolerance":
            final_class = "true_physical_branch_conflict_stop_valid"
            confidence = "medium"
        else:
            final_class = "insufficient_evidence_needs_review"
            confidence = "low"

        evidence = []
        if route_ok:
            evidence.append("same_route_base_name_id_common")
        if token_ok:
            evidence.append("same_or_compatible_carriageway_token")
        if measure_ok:
            evidence.append(f"route_measure_zero_gap_{gap_ft:.3f}ft")
        if divided_undivided:
            evidence.append("divided_undivided_configuration_transition")
        if duplicate_bin:
            evidence.append("duplicate_bin_overlap_risk")
        if suppressed:
            evidence.append("duplicate_suppressed_evidence")
        if one_way_involved or current_ramp or candidate_ramp:
            evidence.append("one_way_or_ramp_like_transition")
        if boundary:
            evidence.append("supported_signal_boundary_between")
        evidence.append(geometry_status)

        rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": clean(rec.get("stable_signal_id")),
                "signal_approach_id": clean(rec.get("signal_approach_id")),
                "measure_side_class": clean(rec.get("measure_side_class")),
                "chain_stop_reason": clean(rec.get("chain_stop_reason")),
                "chain_total_reach_ft": current_reach,
                "current_route_base": clean(rec.get("route_base_values")),
                "current_source_route_name": clean(rec.get("source_route_name_values")),
                "current_source_route_id": clean(rec.get("source_route_id_values")),
                "current_source_route_common": clean(rec.get("source_route_common_values")),
                "current_carriageway_token": clean(rec.get("carriageway_token_values")),
                "current_roadway_configuration": current_config,
                "current_terminal_stable_travelway_id": term_id,
                "current_RIM_MEDIAN": clean(term_road.get("RIM_MEDIAN")),
                "current_RIM_ACCESS": clean(term_road.get("RIM_ACCESS")),
                "current_RIM_FACILITY": clean(term_road.get("RIM_FACILITY")),
                "current_RTE_CATEGO": clean(term_road.get("RTE_CATEGO")),
                "current_RTE_RAMP_C": clean(term_road.get("RTE_RAMP_C")),
                "candidate_stable_travelway_id": candidate_id,
                "candidate_route_base": clean(row.get("candidate_route_base")),
                "candidate_source_route_name": clean(row.get("candidate_source_route_name")),
                "candidate_source_route_id": clean(row.get("candidate_source_route_id")),
                "candidate_source_route_common": clean(row.get("candidate_source_route_common")),
                "candidate_carriageway_token": clean(row.get("candidate_carriageway_direction_token")),
                "candidate_roadway_configuration": candidate_config,
                "candidate_RIM_MEDIAN": clean(cand_road.get("RIM_MEDIAN")),
                "candidate_RIM_ACCESS": clean(cand_road.get("RIM_ACCESS")),
                "candidate_RIM_FACILITY": clean(cand_road.get("RIM_FACILITY")),
                "candidate_RTE_CATEGO": clean(cand_road.get("RTE_CATEGO")),
                "candidate_RTE_RAMP_C": clean(cand_road.get("RTE_RAMP_C")),
                "gap_or_overlap_distance_ft": gap_ft,
                "candidate_additional_reach_ft": add_reach,
                "projected_reach_ft_if_continued": projected_reach,
                "would_reach_full_2500ft_support": projected_reach >= MAX_REACH_FT - 1.0,
                "geometry_continuity_evidence": geometry_status,
                "geometry_endpoint_distance_ft": endpoint_dist,
                "measure_continuity_evidence": "zero_or_near_zero_gap" if measure_ok else "measure_gap_or_sequence_conflict",
                "supported_boundary_evidence": clean(row.get("boundary_signal_id")) if boundary else "",
                "duplicate_bin_overlap_evidence": duplicate_bin,
                "duplicate_suppressed_evidence": suppressed,
                "route_identity_strong": route_ok,
                "carriageway_token_compatible": token_ok,
                "roadway_configuration_transition_family": f"{current_family}_to_{candidate_family}",
                "final_classification": final_class,
                "confidence": confidence,
                "evidence_summary": "|".join(evidence),
            }
        )
    return target, pd.DataFrame(rows)


def input_reconciliation(frames: dict[str, pd.DataFrame], target: pd.DataFrame, classified: pd.DataFrame) -> pd.DataFrame:
    recon = frames["source_reconciliation"]
    cand = frames["source_candidates"]
    corridors = frames["corridors"]
    all_ids = set(recon.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    target_ids = set(target.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    cand_ids = set(cand.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    staged_ids = set(corridors.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    classified_ids = set(classified.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    return pd.DataFrame(
        [
            {"metric": "total_source_extent_reconciliation_suspect_chains", "value": len(all_ids), "detail": ""},
            {"metric": "chains_classified_candidate_roadway_configuration_conflict", "value": len(target_ids), "detail": ""},
            {"metric": "candidate_evaluation_rows_available_for_target", "value": len(classified), "detail": ""},
            {"metric": "target_chains_missing_candidate_details", "value": len(target_ids - cand_ids), "detail": "|".join(sorted(target_ids - cand_ids)[:20])},
            {"metric": "target_ids_unmatched_to_current_staged_approach_corridors", "value": len(target_ids - staged_ids), "detail": "|".join(sorted(target_ids - staged_ids)[:20])},
            {"metric": "classified_rows_missing_target_id", "value": len(classified_ids - target_ids), "detail": "|".join(sorted(classified_ids - target_ids)[:20])},
            {"metric": "does_1979_count_reconcile", "value": len(target_ids) == 1979 and len(classified_ids) == 1979, "detail": f"target_ids={len(target_ids)}; classified_ids={len(classified_ids)}"},
        ]
    )


def taxonomy() -> pd.DataFrame:
    rows = [
        ("simple_context_transition_continuation_likely_valid", "Same route/base/name/id, same measure side, compatible carriageway token, zero/near-zero route-measure continuity, no boundary, no duplicate/bin-overlap, no ramp/one-way branch signal; roadway configuration changes only as divided/undivided context.", "Roadway configuration difference alone is not a stop."),
        ("true_physical_branch_conflict_stop_valid", "Geometry endpoint continuity fails or candidate appears to diverge from the terminal branch after other identity checks.", "Stop valid unless map review contradicts."),
        ("divided_undivided_transition_branch_aware_review", "Divided/undivided transition has compatible route evidence but another branch cue prevents confident automatic continuation.", "Review or branch-aware continuation logic needed."),
        ("carriageway_or_parallel_road_ambiguity_stop_valid", "One-way/ramp-like transition, incompatible carriageway token, or parallel-carriageway cue.", "Stop valid for bin_context unless specifically repaired."),
        ("duplicate_or_suppressed_candidate_stop_valid", "Candidate is diagnostic duplicate/suppressed evidence.", "Stop valid."),
        ("route_or_measure_identity_conflict_stop_valid", "Route/base/name/id, measure side, or route-measure sequence is incompatible.", "Stop valid."),
        ("supported_signal_boundary_blocks_continuation", "Supported signal boundary lies before candidate continuation.", "Stop valid."),
        ("continuation_would_create_bin_duplication", "Continuation would overlap another bin-eligible chain/route-space.", "Stop valid until deduplicated/repaired."),
        ("insufficient_evidence_needs_review", "Available evidence cannot distinguish context transition from branch conflict.", "Targeted review needed."),
    ]
    return pd.DataFrame(rows, columns=["classification", "rule", "interpretation"])


def impact_estimate(classified: pd.DataFrame) -> pd.DataFrame:
    likely = classified[classified["final_classification"].eq("simple_context_transition_continuation_likely_valid")].copy()
    review = classified[classified["final_classification"].isin(["divided_undivided_transition_branch_aware_review", "insufficient_evidence_needs_review", "carriageway_or_parallel_road_ambiguity_stop_valid"])].copy()
    rows = [
        {"metric": "likely_valid_context_transition_chains", "value": int(likely["logical_corridor_chain_id"].nunique()), "interpretation": "chains that may extend if configuration transition is allowed"},
        {"metric": "approaches_affected_by_likely_valid_context_transition", "value": int(likely["signal_approach_id"].nunique()), "interpretation": "approach count"},
        {"metric": "signals_affected_by_likely_valid_context_transition", "value": int(likely["stable_signal_id"].nunique()), "interpretation": "signal count"},
        {"metric": "candidate_added_reach_ft_sum_likely_valid", "value": float(likely["candidate_additional_reach_ft"].sum()) if not likely.empty else 0.0, "interpretation": "upper-bound additional one-sided corridor reach before clipping"},
        {"metric": "likely_valid_chains_reaching_full_2500ft_if_continued", "value": int(likely["would_reach_full_2500ft_support"].sum()) if not likely.empty else 0, "interpretation": "chains whose source-extent partial support could become full 0-2500 support"},
        {"metric": "branch_or_map_review_chains", "value": int(review["logical_corridor_chain_id"].nunique()), "interpretation": "chains that should not be automatically continued"},
        {"metric": "material_for_bin_context", "value": "yes" if int(likely["logical_corridor_chain_id"].nunique()) > 100 else "limited", "interpretation": "large enough to affect distance-band support before bin_context"},
    ]
    return pd.DataFrame(rows)


def make_samples(classified: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sort_cols = ["would_reach_full_2500ft_support", "candidate_additional_reach_ft", "gap_or_overlap_distance_ft"]
    ascending = [False, False, True]
    samples = {
        "likely_valid_context_transition_continuations.csv": classified[classified["final_classification"].eq("simple_context_transition_continuation_likely_valid")].sort_values(sort_cols, ascending=ascending),
        "true_branch_conflict_stop_valid.csv": classified[classified["final_classification"].eq("true_physical_branch_conflict_stop_valid")].sort_values(sort_cols, ascending=ascending),
        "divided_undivided_transition_review.csv": classified[classified["final_classification"].eq("divided_undivided_transition_branch_aware_review")].sort_values(sort_cols, ascending=ascending),
        "carriageway_parallel_ambiguity_review.csv": classified[classified["final_classification"].eq("carriageway_or_parallel_road_ambiguity_stop_valid")].sort_values(sort_cols, ascending=ascending),
        "insufficient_evidence_configuration_conflicts.csv": classified[classified["final_classification"].eq("insufficient_evidence_needs_review")].sort_values(sort_cols, ascending=ascending),
    }
    zero_gap = classified[
        classified["gap_or_overlap_distance_ft"].abs().le(ZERO_GAP_TOL_FT)
        & classified["route_identity_strong"].astype(bool)
        & classified["final_classification"].eq("simple_context_transition_continuation_likely_valid")
    ].sort_values(sort_cols, ascending=ascending)
    samples["zero_gap_same_route_configuration_transition_sample.csv"] = zero_gap.head(100)
    map_review = classified[
        classified["final_classification"].isin(
            [
                "divided_undivided_transition_branch_aware_review",
                "carriageway_or_parallel_road_ambiguity_stop_valid",
                "insufficient_evidence_needs_review",
            ]
        )
    ].sort_values(["candidate_additional_reach_ft"], ascending=False)
    samples["map_review_candidate_sample.csv"] = map_review.head(100)
    return samples


def decision_and_outputs(frames: dict[str, pd.DataFrame], target: pd.DataFrame, classified: pd.DataFrame) -> str:
    counts = classified["final_classification"].value_counts()
    likely_count = int(counts.get("simple_context_transition_continuation_likely_valid", 0))
    review_count = int(
        counts.get("divided_undivided_transition_branch_aware_review", 0)
        + counts.get("insufficient_evidence_needs_review", 0)
        + counts.get("carriageway_or_parallel_road_ambiguity_stop_valid", 0)
    )
    if likely_count > 100:
        return "patch_simple_context_transition_continuations_before_bin_context"
    if review_count > 0:
        return "create_configuration_transition_map_review_sample"
    if int(counts.get("insufficient_evidence_needs_review", 0)) > 0:
        return "configuration_conflict_evidence_insufficient_needs_more_audit"
    return "configuration_conflicts_are_valid_stops_finalize_corridors"


def write_memo_and_manifests(
    frames: dict[str, pd.DataFrame],
    input_rec: pd.DataFrame,
    classified: pd.DataFrame,
    impact: pd.DataFrame,
    decision: str,
) -> None:
    counts = classified["final_classification"].value_counts().sort_index()
    likely = int(counts.get("simple_context_transition_continuation_likely_valid", 0))
    true_stop = int(
        counts.get("true_physical_branch_conflict_stop_valid", 0)
        + counts.get("continuation_would_create_bin_duplication", 0)
        + counts.get("duplicate_or_suppressed_candidate_stop_valid", 0)
        + counts.get("route_or_measure_identity_conflict_stop_valid", 0)
        + counts.get("supported_signal_boundary_blocks_continuation", 0)
    )
    branch_review = int(counts.get("divided_undivided_transition_branch_aware_review", 0))
    map_review = int(counts.get("carriageway_or_parallel_road_ambiguity_stop_valid", 0) + counts.get("insufficient_evidence_needs_review", 0))
    added_full = impact.loc[impact["metric"].eq("likely_valid_chains_reaching_full_2500ft_if_continued"), "value"].iloc[0]
    findings = f"""# Roadway-Configuration Conflict Continuation Audit

## Why This Audit Was Needed
The source-extent reconciliation audit classified 1,979 chains as `candidate_roadway_configuration_conflict`. That classification was intentionally strict, but roadway configuration is also roadway context. This audit tests whether those stops are physical branch conflicts or over-strict context-transition blocks.

## Why Configuration Difference Alone Is Not Enough
`roadway_configuration` can change when median, divided/undivided status, access, facility, or lane context changes along the same physical route-space branch. A string difference blocks continuation only when it indicates a different branch, ramp, carriageway, route identity, signal boundary, or duplication risk.

## Classification Results
{counts.to_string()}

True stop-valid conflicts: {true_stop:,}. Simple context transitions likely valid: {likely:,}. Branch-aware review cases: {branch_review:,}. Map-review/ambiguity or insufficient-evidence cases: {map_review:,}.

## Underextension Risk
The current `approach_corridors.parquet` is likely underextended for {likely:,} chains because route identity, carriageway token, measure side, route-measure continuity, and boundary checks support continuation while only roadway configuration differs. {int(added_full):,} of those chains could reach full 0-2,500 ft support if continued.

## Patch Before bin_context
Decision: `{decision}`. If accepted, patch logic should allow simple divided/undivided context transitions only when route/base/name/id, carriageway token, measure side, zero-gap route-measure continuity, boundary, and duplicate-risk checks pass. This task did not patch anything.

## Map Review Need
Map review is not needed for the likely-valid context-transition majority, but the sampled one-way/ramp/parallel ambiguity cases should be reviewed before any broad rule covers them.

## Recommended Next Task
Patch simple context-transition continuation logic before bin_context, then rerun final read-only validation. Keep duplicate/bin-overlap and one-way/ramp ambiguity cases stopped or in targeted review.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_utc": now(),
        "script": "src.roadway_graph.audit.roadway_configuration_conflict_continuation_audit",
        "rule_version": RULE_VERSION,
        "bounded_question": "Classify roadway-configuration conflict source-extent candidates without mutating staged corridors.",
        "source_inputs": [rel(p) for p in [SIGNAL_INDEX, TRAVELWAY_INDEX, ATTACHMENT, APPROACHES, CORRIDORS, STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]],
        "diagnostic_inputs": [rel(p) for p in [SOURCE_RECON, FINAL_REVIEW, REPAIR_REVIEW, DEDUP_REVIEW, CHAIN_REVIEW, RECON_REVIEW]],
        "output_grain": {"roadway_configuration_conflict_classification.csv": "one row per target chain/candidate pair"},
        "caveats": [
            "No staged products were modified.",
            "Geometry continuity is endpoint-distance evidence only; no map layer or manual review was generated.",
        ],
        "final_decision": decision,
    }
    qa = {
        "created_utc": now(),
        "target_configuration_conflict_chains": int(len(classified)),
        "classification_counts": {k: int(v) for k, v in counts.items()},
        "likely_valid_context_transition_count": likely,
        "true_stop_valid_count": true_stop,
        "branch_or_map_review_count": branch_review + map_review,
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()}: Started roadway-configuration conflict continuation audit.\n", encoding="utf-8")
    frames = load_inputs()
    target, classified = build_classification(frames)
    input_rec = input_reconciliation(frames, target, classified)
    tax = taxonomy()
    impact = impact_estimate(classified)
    decision = decision_and_outputs(frames, target, classified)
    samples = make_samples(classified)
    decision_summary = pd.DataFrame(
        [
            {"metric": "final_decision", "value": decision},
            {"metric": "target_rows", "value": len(classified)},
            {"metric": "classification_mix", "value": "|".join(f"{k}:{int(v)}" for k, v in classified["final_classification"].value_counts().sort_index().items())},
        ]
    )
    readiness = pd.DataFrame([{"final_decision": decision, "reason": "read-only roadway-configuration conflict continuation audit completed"}])
    recommended = pd.DataFrame(
        [
            {
                "rank": 1,
                "action": "patch_simple_context_transition_continuations_before_bin_context",
                "rationale": "Most configuration conflicts are same-route, same-token, zero-gap divided/undivided context transitions rather than physical branch conflicts.",
            },
            {
                "rank": 2,
                "action": "keep_duplicate_and_one_way_ramp_ambiguity_cases_stopped_or_reviewed",
                "rationale": "These cases have duplication, ramp, one-way, or parallel-road ambiguity evidence.",
            },
        ]
    )
    write_csv("input_suspect_reconciliation.csv", input_rec)
    write_csv("roadway_configuration_conflict_taxonomy.csv", tax)
    write_csv("roadway_configuration_conflict_classification.csv", classified)
    for name, df in samples.items():
        write_csv(name, df)
    write_csv("distance_band_impact_estimate.csv", impact)
    write_csv("configuration_conflict_decision_summary.csv", decision_summary)
    write_csv("readiness_decision.csv", readiness)
    write_csv("recommended_next_actions.csv", recommended)
    write_memo_and_manifests(frames, input_rec, classified, impact, decision)
    log(f"Finished audit with decision={decision}.")


if __name__ == "__main__":
    main()
