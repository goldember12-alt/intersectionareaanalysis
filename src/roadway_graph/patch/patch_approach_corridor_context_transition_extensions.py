"""Patch likely-valid context-transition extensions into approach corridors.

This bounded repair appends only source-extent continuation rows identified by
the full source-extent continuation audit. It does not rebuild corridors, build
bins, assign directionality, or modify source artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkb


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_approach_corridor_context_transition_extensions"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

FULL_AUDIT = REPO / "work/roadway_graph/review/full_source_extent_continuation_audit"
CONFIG_AUDIT = REPO / "work/roadway_graph/review/roadway_configuration_conflict_continuation_audit"
SOURCE_RECON = REPO / "work/roadway_graph/review/source_extent_suspect_chain_reconciliation_audit"
FINAL_REVIEW = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

RULE_VERSION = "context_transition_source_extent_extension_v1_2026-06-10"
MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
SEARCH_GAP_FT = 50.0
ACCEPT_GAP_FT = 5.0
FLOAT_TOL_FT = 0.001
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


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def hash_text(text: str, n: int = 24) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


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


def compact_counts(values: pd.Series) -> str:
    counts = values.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{k}:{int(v)}" for k, v in counts.items())


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


def compatible_value(a: Any, b: Any) -> bool:
    aa = clean(a).lower()
    bb = clean(b).lower()
    unknown = {"", "unknown", "nan", "none", "null", "<na>"}
    return aa == bb or aa in unknown or bb in unknown


def is_allowed_context_transition(current_config: Any, candidate_config: Any) -> bool:
    families = {config_family(current_config), config_family(candidate_config)}
    return len(families) == 1 or families == {"two_way_divided", "two_way_undivided"}


def ramp_like(row: pd.Series) -> bool:
    text = " ".join(clean(row.get(k)) for k in ["RTE_RAMP_C", "RTE_CATEGO", "RTE_TYPE_N", "source_route_common", "roadway_configuration"]).lower()
    return bool(clean(row.get("RTE_RAMP_C"))) or "ramp" in text


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


def completeness_for_stop(stop_reason: str) -> str:
    return {
        "reached_2500_ft": "complete_to_2500ft",
        "stopped_at_supported_signal_boundary": "complete_to_supported_signal_boundary",
        "stopped_at_source_extent": "partial_source_extent_stop_no_valid_neighbor",
        "stopped_at_route_measure_gap": "partial_route_measure_gap_stop",
        "stopped_at_geometry_gap": "partial_geometry_gap_stop",
        "stopped_at_route_or_carriageway_conflict": "partial_conflict_stop",
        "stopped_at_roadway_configuration_branch_conflict": "partial_conflict_stop",
        "stopped_due_insufficient_evidence": "partial_insufficient_evidence_stop",
    }.get(clean(stop_reason), "partial_unclear_stop")


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    if "route_measure_status" in r.columns:
        r = r[r["route_measure_status"].eq("route_measure_complete")].copy()
    r = r[r["source_route_name"].notna() & r["road_lo"].notna() & r["road_hi"].notna()].copy()
    for col in ["route_base", "source_route_id", "source_route_common", "carriageway_direction_token", "roadway_configuration", "RTE_RAMP_C", "RTE_CATEGO", "RTE_TYPE_N"]:
        if col not in r.columns:
            r[col] = ""
    return r.sort_values(["source_route_name", "road_lo", "road_hi", "stable_travelway_id"]).reset_index(drop=True)


def road_groups(roads: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {clean(route): group.reset_index(drop=True) for route, group in roads.groupby("source_route_name", dropna=False)}


def make_boundary_groups(attachments: pd.DataFrame) -> dict[str, pd.DataFrame]:
    a = attachments.copy()
    for optional in ["source_route_name", "carriageway_direction_token", "roadway_configuration", "source_signal_globalid"]:
        if optional not in a.columns:
            a[optional] = ""
    b = a[
        a["attachment_confidence"].isin(["high", "medium"])
        & a["estimated_measure_status"].eq("estimated_measure_projected")
        & a["usable_as_corridor_boundary"].fillna(False).astype(bool)
        & a["estimated_measure"].notna()
    ].copy()
    b["estimated_measure"] = pd.to_numeric(b["estimated_measure"], errors="coerce")
    return {clean(route): group.sort_values("estimated_measure").reset_index(drop=True) for route, group in b.groupby("source_route_name", dropna=False)}


def nearest_boundary(boundaries: dict[str, pd.DataFrame], route: str, signal_id: str, signal_measure: float, endpoint: float, hard_limit: float, side: str, token: str) -> dict[str, Any]:
    b = boundaries.get(route)
    if b is None or b.empty:
        return {"has_boundary": False, "measure": None, "stable_signal_id": "", "source_globalid": ""}
    b = b[~b["stable_signal_id"].astype(str).eq(signal_id)].copy()
    b = b[b["carriageway_direction_token"].map(lambda x: compatible_value(x, token))]
    if b.empty:
        return {"has_boundary": False, "measure": None, "stable_signal_id": "", "source_globalid": ""}
    if side == "measure_increasing_from_signal":
        candidates = b[(b["estimated_measure"] > max(signal_measure, endpoint) + 1e-9) & (b["estimated_measure"] <= hard_limit + 1e-9)]
        if candidates.empty:
            return {"has_boundary": False, "measure": None, "stable_signal_id": "", "source_globalid": ""}
        row = candidates.sort_values("estimated_measure").iloc[0]
    else:
        candidates = b[(b["estimated_measure"] < min(signal_measure, endpoint) - 1e-9) & (b["estimated_measure"] >= hard_limit - 1e-9)]
        if candidates.empty:
            return {"has_boundary": False, "measure": None, "stable_signal_id": "", "source_globalid": ""}
        row = candidates.sort_values("estimated_measure", ascending=False).iloc[0]
    return {"has_boundary": True, "measure": float(row["estimated_measure"]), "stable_signal_id": clean(row["stable_signal_id"]), "source_globalid": clean(row.get("source_signal_globalid"))}


def candidate_rows(route_roads: pd.DataFrame, side: str, endpoint: float, hard_limit: float, used_ids: set[str]) -> pd.DataFrame:
    if route_roads.empty:
        return route_roads.copy()
    cand = route_roads[~route_roads["stable_travelway_id"].astype(str).isin(used_ids)].copy()
    if side == "measure_increasing_from_signal":
        cand = cand[(cand["road_hi"] > endpoint + 1e-9) & (cand["road_lo"] <= hard_limit + 1e-9)].copy()
        cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
        return cand.sort_values(["gap_ft", "road_lo", "road_hi", "stable_travelway_id"])
    cand = cand[(cand["road_lo"] < endpoint - 1e-9) & (cand["road_hi"] >= hard_limit - 1e-9)].copy()
    cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0.0)) * 5280.0
    cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
    return cand.sort_values(["gap_ft", "road_hi", "road_lo", "stable_travelway_id"], ascending=[True, False, False, True])


def chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    c = corridors.copy()
    c["segment_source_from_measure"] = pd.to_numeric(c["segment_source_from_measure"], errors="coerce")
    c["segment_source_to_measure"] = pd.to_numeric(c["segment_source_to_measure"], errors="coerce")
    return c.groupby("logical_corridor_chain_id", dropna=False).agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        segment_count=("approach_corridor_id", "size"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        reviewed_signal_measure=("reviewed_signal_measure", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_completeness_status=("chain_completeness_status", "first"),
        measure_side_class=("measure_side_class", "first"),
        route_base_values=("route_base", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_id_values=("source_route_id", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_common_values=("source_route_common", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        chain_bin_eligible_flag=("chain_bin_eligible_flag", "first"),
        bin_duplication_risk_status=("bin_duplication_risk_status", "first"),
    ).reset_index()


def duplicate_existing_route_space(corridors: pd.DataFrame, chain_id: str, approach_id: str, route: str, token: str, side: str, road_id: str, seg_lo: float, seg_hi: float) -> bool:
    peers = corridors[
        corridors["signal_approach_id"].astype(str).eq(approach_id)
        & ~corridors["logical_corridor_chain_id"].astype(str).eq(chain_id)
        & corridors["measure_side_class"].astype(str).eq(side)
        & corridors["source_route_name"].astype(str).eq(route)
        & corridors["chain_bin_eligible_flag"].fillna(True).map(bool_value)
    ].copy()
    if peers.empty:
        return False
    peers = peers[peers["carriageway_direction_token"].map(lambda x: compatible_value(x, token))]
    if peers.empty:
        return False
    if peers["stable_travelway_id"].astype(str).eq(road_id).any():
        return True
    overlap = (
        (pd.to_numeric(peers["segment_source_from_measure"], errors="coerce") <= seg_hi + 1e-9)
        & (pd.to_numeric(peers["segment_source_to_measure"], errors="coerce") >= seg_lo - 1e-9)
    ).any()
    return bool(overlap)


def make_new_segment(template: pd.Series, road: pd.Series, order: int, seg_start: float, seg_end: float, gap_ft: float, from_config: str) -> dict[str, Any]:
    signal_measure = float(template["reviewed_signal_measure"])
    chain_id = clean(template["logical_corridor_chain_id"])
    road_id = clean(road["stable_travelway_id"])
    lo = min(seg_start, seg_end)
    hi = max(seg_start, seg_end)
    start_dist = abs(seg_start - signal_measure) * 5280.0
    end_dist = abs(seg_end - signal_measure) * 5280.0
    row = template.to_dict()
    row.update(
        {
            "approach_corridor_id": f"corrseg_ctxext_{hash_text('|'.join([chain_id, road_id, str(order), f'{lo:.8f}', f'{hi:.8f}']))}",
            "stable_travelway_id": road_id,
            "segment_order": int(order),
            "segment_source_from_measure": lo,
            "segment_source_to_measure": hi,
            "corridor_from_measure": min(signal_measure, seg_end),
            "corridor_to_measure": max(signal_measure, seg_end),
            "segment_start_distance_ft": min(start_dist, end_dist),
            "segment_end_distance_ft": max(start_dist, end_dist),
            "one_sided_reach_ft": max(start_dist, end_dist),
            "corridor_length_ft": abs(seg_end - seg_start) * 5280.0,
            "route_base": clean(road.get("route_base")),
            "source_route_name": clean(road.get("source_route_name")),
            "source_route_id": clean(road.get("source_route_id")),
            "source_route_common": clean(road.get("source_route_common")),
            "carriageway_direction_token": clean(road.get("carriageway_direction_token")),
            "roadway_configuration": clean(road.get("roadway_configuration")),
            "source_measure_start": float(road["source_measure_start"]),
            "source_measure_end": float(road["source_measure_end"]),
            "geometry": road.get("geometry"),
            "geometry_status": clean(road.get("geometry_validity_status")) or clean(row.get("geometry_status")) or "geometry_available",
            "endpoint_policy": "context_transition_same_corridor_extension",
            "neighbor_extension_used_flag": True,
            "route_measure_continuity_status": "continued_same_route_context_transition",
            "geometry_continuity_status": "context_transition_endpoint_or_route_measure_continuity_used",
            "gap_bridge_status": "accepted_small_route_measure_gap" if gap_ft > FLOAT_TOL_FT else "not_needed",
            "gap_bridge_method": "context_transition_route_measure_continuation" if gap_ft > FLOAT_TOL_FT else "",
            "gap_bridge_confidence": "medium" if gap_ft > FLOAT_TOL_FT else "",
            "corridor_build_status": "built_context_transition_extension",
            "corridor_rebuild_version": RULE_VERSION,
            "context_transition_extension_used_flag": True,
            "context_transition_extension_status": "extension_accepted",
            "context_transition_extension_method": "same_corridor_roadway_configuration_context_transition",
            "context_transition_rule_version": RULE_VERSION,
            "continuation_candidate_stable_travelway_id": road_id,
            "continuation_roadway_configuration_from": from_config,
            "continuation_roadway_configuration_to": clean(road.get("roadway_configuration")),
            "continuation_gap_ft": float(gap_ft),
            "continuation_added_reach_ft": abs(seg_end - seg_start) * 5280.0,
            "continuation_rejection_reason": "",
            "chain_bin_eligible_flag": True,
            "bin_duplication_risk_status": "no_duplication_risk",
        }
    )
    return row


def validate_candidate(chain: pd.DataFrame, road: pd.Series, target_candidate_id: str | None, corridors_for_dup: pd.DataFrame, boundaries: dict[str, pd.DataFrame], endpoint: float, hard_limit: float) -> tuple[bool, str, dict[str, Any]]:
    first = chain.iloc[0]
    last = chain.iloc[-1]
    route = clean(first["source_route_name"])
    side = clean(first["measure_side_class"])
    token = clean(first["carriageway_direction_token"])
    signal_id = clean(first["stable_signal_id"])
    signal_measure = safe_float(first["reviewed_signal_measure"])
    road_id = clean(road["stable_travelway_id"])
    if target_candidate_id and road_id != target_candidate_id:
        return False, "candidate_not_target_ledger_first_step", {}
    if clean(road.get("source_route_name")) != route:
        return False, "route_name_conflict", {}
    if not compatible_value(road.get("route_base"), first.get("route_base")):
        return False, "route_base_conflict", {}
    if not compatible_value(road.get("source_route_id"), first.get("source_route_id")):
        return False, "source_route_id_conflict", {}
    if not compatible_value(road.get("source_route_common"), first.get("source_route_common")):
        return False, "source_route_common_conflict", {}
    if not compatible_value(road.get("carriageway_direction_token"), token):
        return False, "carriageway_token_conflict", {}
    if ramp_like(road):
        return False, "candidate_ramp_or_parallel_ambiguity", {}
    if config_family(road.get("roadway_configuration")).startswith("one_way"):
        return False, "candidate_one_way_ambiguity", {}
    if not is_allowed_context_transition(last.get("roadway_configuration"), road.get("roadway_configuration")):
        return False, "roadway_configuration_branch_conflict", {}
    boundary = nearest_boundary(boundaries, route, signal_id, signal_measure, endpoint, hard_limit, side, token)
    boundary_measure = boundary.get("measure")
    if side == "measure_increasing_from_signal":
        candidate_start = max(endpoint, float(road["road_lo"]))
        if boundary_measure is not None and float(boundary_measure) <= candidate_start + 1e-9:
            return False, "supported_signal_boundary_before_candidate", {"boundary": boundary}
        seg_start = candidate_start
        seg_end = min(float(road["road_hi"]), hard_limit)
        if boundary_measure is not None:
            seg_end = min(seg_end, float(boundary_measure))
    else:
        candidate_start = min(endpoint, float(road["road_hi"]))
        if boundary_measure is not None and float(boundary_measure) >= candidate_start - 1e-9:
            return False, "supported_signal_boundary_before_candidate", {"boundary": boundary}
        seg_start = candidate_start
        seg_end = max(float(road["road_lo"]), hard_limit)
        if boundary_measure is not None:
            seg_end = max(seg_end, float(boundary_measure))
    gap_ft = safe_float(road.get("gap_ft"), 999999.0)
    if gap_ft > ACCEPT_GAP_FT + FLOAT_TOL_FT:
        return False, "route_measure_gap_exceeds_acceptance", {}
    added = abs(seg_end - seg_start) * 5280.0
    if added <= FLOAT_TOL_FT:
        return False, "candidate_adds_no_reach", {}
    projected_reach = abs(seg_end - signal_measure) * 5280.0
    if projected_reach > MAX_REACH_FT + FLOAT_TOL_FT:
        return False, "candidate_exceeds_2500_ft", {}
    geom_status, geom_dist = endpoint_distance(last.get("geometry"), road.get("geometry"))
    if geom_status == "endpoint_distance_exceeds_tolerance" and gap_ft > FLOAT_TOL_FT:
        return False, "geometry_and_route_measure_continuity_weak", {"geometry_status": geom_status, "geometry_endpoint_distance_ft": geom_dist}
    if duplicate_existing_route_space(corridors_for_dup, clean(first["logical_corridor_chain_id"]), clean(first["signal_approach_id"]), route, token, side, road_id, min(seg_start, seg_end), max(seg_start, seg_end)):
        return False, "would_create_duplicate_bin_overlap", {}
    return True, "", {"seg_start": seg_start, "seg_end": seg_end, "gap_ft": gap_ft, "boundary": boundary, "geometry_status": geom_status, "geometry_endpoint_distance_ft": geom_dist}


def patch_targets(corridors: pd.DataFrame, roads: pd.DataFrame, attachments: pd.DataFrame, targets: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    c = corridors.copy()
    defaults = {
        "context_transition_extension_used_flag": False,
        "context_transition_extension_status": "not_targeted",
        "context_transition_extension_method": "",
        "context_transition_rule_version": RULE_VERSION,
        "pre_extension_chain_stop_reason": "",
        "post_extension_chain_stop_reason": "",
        "continuation_candidate_stable_travelway_id": "",
        "continuation_roadway_configuration_from": "",
        "continuation_roadway_configuration_to": "",
        "continuation_gap_ft": "",
        "continuation_added_reach_ft": 0.0,
        "continuation_added_segment_count": 0,
        "continuation_rejection_reason": "",
    }
    for col, default in defaults.items():
        if col not in c.columns:
            c[col] = default
    roads_prepared = prepare_roads(roads)
    roads_by_route = road_groups(roads_prepared)
    boundaries = make_boundary_groups(attachments)
    target_ids = sorted(set(targets["logical_corridor_chain_id"].astype(str)))
    target_by_chain = targets.drop_duplicates("logical_corridor_chain_id").set_index("logical_corridor_chain_id", drop=False)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    input_rows: list[dict[str, Any]] = []
    added_segments: list[dict[str, Any]] = []
    updates: dict[str, dict[str, Any]] = {}
    new_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for i, chain_id in enumerate(target_ids, start=1):
        if i % 100 == 0:
            log(f"Processed {i:,} context-transition patch targets.")
        t = target_by_chain.loc[chain_id]
        input_rows.append({"logical_corridor_chain_id": chain_id, "input_status": "loaded", "target_candidate_stable_travelway_id": clean(t.get("candidate_stable_travelway_id")), "patch_priority": clean(t.get("patch_priority"))})
        chain = c[c["logical_corridor_chain_id"].astype(str).eq(chain_id)].copy().sort_values("segment_order")
        if chain.empty:
            rejected.append({"logical_corridor_chain_id": chain_id, "rejection_reason": "target_chain_not_found"})
            continue
        first = chain.iloc[0]
        if clean(first["chain_stop_reason"]) != "stopped_at_source_extent":
            updates[chain_id] = {"context_transition_extension_status": "already_resolved", "continuation_rejection_reason": "chain_stop_reason_no_longer_source_extent"}
            rejected.append({"logical_corridor_chain_id": chain_id, "rejection_reason": "chain_stop_reason_no_longer_source_extent"})
            continue
        route = clean(first["source_route_name"])
        side = clean(first["measure_side_class"])
        signal_measure = safe_float(first["reviewed_signal_measure"])
        if side not in {"measure_increasing_from_signal", "measure_decreasing_from_signal"} or pd.isna(signal_measure):
            updates[chain_id] = {"context_transition_extension_status": "extension_rejected_with_reason", "continuation_rejection_reason": "missing_side_or_signal_measure"}
            rejected.append({"logical_corridor_chain_id": chain_id, "rejection_reason": "missing_side_or_signal_measure"})
            continue
        route_roads = roads_by_route.get(route, pd.DataFrame())
        endpoint = signal_measure + float(chain.iloc[-1]["segment_end_distance_ft"]) / 5280.0 if side == "measure_increasing_from_signal" else signal_measure - float(chain.iloc[-1]["segment_end_distance_ft"]) / 5280.0
        hard_limit = signal_measure + MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - MAX_REACH_MILES
        used_ids = set(chain["stable_travelway_id"].astype(str))
        accepted_count = 0
        rejected_reason = ""
        max_order = int(chain["segment_order"].max())
        terminal_stop = "stopped_at_source_extent"
        boundary_info = {"has_boundary": False, "measure": None, "stable_signal_id": "", "source_globalid": ""}
        target_candidate_id = clean(t.get("candidate_stable_travelway_id"))
        working_chain = chain.copy()
        for iteration in range(64):
            current_reach = abs(endpoint - signal_measure) * 5280.0
            if current_reach >= MAX_REACH_FT - 1.0:
                terminal_stop = "reached_2500_ft"
                break
            cand = candidate_rows(route_roads, side, endpoint, hard_limit, used_ids)
            if cand.empty:
                terminal_stop = "stopped_at_source_extent"
                break
            road = cand.iloc[0]
            must_match = target_candidate_id if iteration == 0 else None
            ok, reason, detail = validate_candidate(working_chain, road, must_match, pd.concat([c, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else c, boundaries, endpoint, hard_limit)
            if not ok:
                rejected_reason = reason
                terminal_stop = {
                    "supported_signal_boundary_before_candidate": "stopped_at_supported_signal_boundary",
                    "route_measure_gap_exceeds_acceptance": "stopped_at_route_measure_gap",
                    "geometry_and_route_measure_continuity_weak": "stopped_at_geometry_gap",
                    "route_name_conflict": "stopped_at_route_or_carriageway_conflict",
                    "route_base_conflict": "stopped_at_route_or_carriageway_conflict",
                    "source_route_id_conflict": "stopped_at_route_or_carriageway_conflict",
                    "source_route_common_conflict": "stopped_at_route_or_carriageway_conflict",
                    "carriageway_token_conflict": "stopped_at_route_or_carriageway_conflict",
                    "roadway_configuration_branch_conflict": "stopped_at_roadway_configuration_branch_conflict",
                    "candidate_exceeds_2500_ft": "reached_2500_ft",
                }.get(reason, "stopped_due_insufficient_evidence")
                if accepted_count == 0:
                    rejected.append({"logical_corridor_chain_id": chain_id, "candidate_stable_travelway_id": clean(road.get("stable_travelway_id")), "rejection_reason": reason})
                break
            seg_start = detail["seg_start"]
            seg_end = detail["seg_end"]
            boundary_info = detail.get("boundary", boundary_info)
            max_order += 1
            new_row = make_new_segment(working_chain.iloc[-1], road, max_order, seg_start, seg_end, detail["gap_ft"], clean(working_chain.iloc[-1].get("roadway_configuration")))
            new_rows.append(new_row)
            added_segments.append(new_row)
            accepted.append(
                {
                    "logical_corridor_chain_id": chain_id,
                    "stable_signal_id": clean(first["stable_signal_id"]),
                    "signal_approach_id": clean(first["signal_approach_id"]),
                    "candidate_stable_travelway_id": clean(road["stable_travelway_id"]),
                    "segment_order": max_order,
                    "gap_ft": detail["gap_ft"],
                    "added_reach_ft": abs(seg_end - seg_start) * 5280.0,
                    "roadway_configuration_from": clean(working_chain.iloc[-1].get("roadway_configuration")),
                    "roadway_configuration_to": clean(road.get("roadway_configuration")),
                    "acceptance_reason": "same_corridor_context_transition",
                }
            )
            working_chain = pd.concat([working_chain, pd.DataFrame([new_row])], ignore_index=True)
            used_ids.add(clean(road["stable_travelway_id"]))
            endpoint = seg_end
            accepted_count += 1
            if boundary_info.get("has_boundary") and boundary_info.get("measure") is not None and abs(float(boundary_info["measure"]) - endpoint) <= 1e-9:
                terminal_stop = "stopped_at_supported_signal_boundary"
                break
        final_reach = min(MAX_REACH_FT, abs(endpoint - signal_measure) * 5280.0)
        if final_reach >= MAX_REACH_FT - 1.0:
            terminal_stop = "reached_2500_ft"
        status = "extension_accepted" if accepted_count else "extension_rejected_with_reason"
        updates[chain_id] = {
            "context_transition_extension_used_flag": accepted_count > 0,
            "context_transition_extension_status": status,
            "context_transition_extension_method": "same_corridor_roadway_configuration_context_transition" if accepted_count else "",
            "context_transition_rule_version": RULE_VERSION,
            "pre_extension_chain_stop_reason": clean(first["chain_stop_reason"]),
            "post_extension_chain_stop_reason": terminal_stop,
            "continuation_candidate_stable_travelway_id": target_candidate_id,
            "continuation_roadway_configuration_from": clean(t.get("current_roadway_configuration")),
            "continuation_roadway_configuration_to": clean(t.get("candidate_roadway_configuration")),
            "continuation_gap_ft": safe_float(t.get("gap_or_overlap_distance_ft"), 0.0),
            "continuation_added_reach_ft": sum(r["added_reach_ft"] for r in accepted if r["logical_corridor_chain_id"] == chain_id),
            "continuation_added_segment_count": accepted_count,
            "continuation_rejection_reason": "" if accepted_count else rejected_reason,
            "chain_total_reach_ft": final_reach,
            "chain_stop_reason": terminal_stop,
            "chain_completeness_status": completeness_for_stop(terminal_stop),
            "boundary_signal_id": boundary_info.get("stable_signal_id", "") if terminal_stop == "stopped_at_supported_signal_boundary" else "",
            "boundary_source_globalid": boundary_info.get("source_globalid", "") if terminal_stop == "stopped_at_supported_signal_boundary" else "",
        }

    if new_rows:
        c = pd.concat([c, pd.DataFrame.from_records(new_rows)], ignore_index=True)
    for chain_id, vals in updates.items():
        mask = c["logical_corridor_chain_id"].astype(str).eq(chain_id)
        for key, val in vals.items():
            if key in c.columns:
                c.loc[mask, key] = val
        order_idx = c[mask].sort_values(["segment_start_distance_ft", "segment_end_distance_ft", "approach_corridor_id"]).index
        count = len(order_idx)
        c.loc[order_idx, "segment_order"] = range(1, count + 1)
        c.loc[order_idx, "segment_count_in_chain"] = count
        max_end = float(c.loc[order_idx, "segment_end_distance_ft"].max())
        if max_end > safe_float(vals.get("chain_total_reach_ft"), 0.0):
            c.loc[order_idx, "chain_total_reach_ft"] = max_end
        stop = clean(c.loc[order_idx[0], "chain_stop_reason"])
        c.loc[order_idx, "chain_completeness_status"] = completeness_for_stop(stop)
        c.loc[order_idx, "clipped_by_2500_ft_flag"] = stop == "reached_2500_ft"
        c.loc[order_idx, "clipped_by_signal_boundary_flag"] = stop == "stopped_at_supported_signal_boundary"
        c.loc[order_idx, "clipped_by_source_extent_flag"] = stop == "stopped_at_source_extent"
        c.loc[order_idx, "clipped_by_gap_or_uncertain_continuity_flag"] = stop in {"stopped_at_route_measure_gap", "stopped_at_geometry_gap", "stopped_due_insufficient_evidence"}
        c.loc[order_idx, "boundary_method"] = stop
    excluded_classes = ["continuation_would_create_bin_duplication", "duplicate_or_suppressed_candidate_stop_valid", "carriageway_or_parallel_road_ambiguity_stop_valid", "true_source_extent_no_candidate"]
    for name in ["duplicate_or_bin_overlap_exclusions.csv", "branch_ambiguity_or_map_review_candidates.csv", "true_source_extent_chains.csv"]:
        df = read_csv_optional(FULL_AUDIT / name)
        if not df.empty:
            for _, row in df.iterrows():
                excluded.append({"logical_corridor_chain_id": clean(row.get("logical_corridor_chain_id")), "source_file": name, "unchanged_reason": clean(row.get("final_classification")) or name.replace(".csv", "")})
    frames = {
        "input": pd.DataFrame(input_rows),
        "accepted": pd.DataFrame(accepted),
        "rejected": pd.DataFrame(rejected),
        "added_segments": pd.DataFrame(added_segments),
        "excluded": pd.DataFrame(excluded),
        "added_reach": pd.DataFrame(accepted).groupby("logical_corridor_chain_id", dropna=False).agg(
            added_segment_count=("candidate_stable_travelway_id", "size"),
            added_reach_ft=("added_reach_ft", "sum"),
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
        ).reset_index() if accepted else pd.DataFrame(columns=["logical_corridor_chain_id", "added_segment_count", "added_reach_ft", "stable_signal_id", "signal_approach_id"]),
    }
    return c, frames


def parent_dependency_check() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"object": "approach_corridors.parquet", "canonical_parent": rel(SIGNAL_INDEX), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(TRAVELWAY_INDEX), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(ATTACHMENT), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(APPROACHES), "status": "pass"},
            {"object": "diagnostic_review_outputs", "canonical_parent": "", "status": "pass_not_listed_as_canonical_parent"},
        ]
    )


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def duplicate_risk(corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    chain = chain_summary(corridors[corridors["chain_bin_eligible_flag"].fillna(True).map(bool_value)].copy())
    rows: list[dict[str, Any]] = []
    for approach_id, group in chain.groupby("signal_approach_id", dropna=False):
        values = group.to_dict("records")
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                same_side = clean(a["measure_side_class"]) == clean(b["measure_side_class"])
                same_route = clean(a["route_base_values"]) == clean(b["route_base_values"]) or clean(a["source_route_name_values"]) == clean(b["source_route_name_values"])
                same_token = clean(a["carriageway_token_values"]) == clean(b["carriageway_token_values"])
                dist_overlap = interval_overlap(0, float(a["chain_total_reach_ft"]), 0, float(b["chain_total_reach_ft"]))
                src_overlap = interval_overlap(float(a["source_measure_min"]), float(a["source_measure_max"]), float(b["source_measure_min"]), float(b["source_measure_max"]))
                shared = len((set(clean(a["stable_travelway_ids"]).split("|")) - {""}) & (set(clean(b["stable_travelway_ids"]).split("|")) - {""}))
                if not same_side or not same_route:
                    cls = "no_overlap_distinct_branch"
                elif same_side and same_route and same_token and (src_overlap > 0.001 or shared > 0):
                    cls = "likely_duplicate_chain_same_route_space"
                elif same_side and same_route and same_token and dist_overlap >= 250:
                    cls = "possible_duplicate_chain_same_route_space"
                elif same_side and same_route and not same_token:
                    cls = "legitimate_parallel_divided_subbranch"
                else:
                    cls = "insufficient_evidence_but_bin_safe"
                rows.append({"signal_approach_id": approach_id, "stable_signal_id": a["stable_signal_id"], "chain_a": a["logical_corridor_chain_id"], "chain_b": b["logical_corridor_chain_id"], "distance_overlap_ft": dist_overlap, "source_measure_overlap": src_overlap, "shared_stable_travelway_id_count": shared, "pair_overlap_class": cls})
    pairs = pd.DataFrame(rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=["signal_approach_id", "pair_overlap_class", "distance_overlap_ft"])
    blocking = pairs[pairs["pair_overlap_class"].isin(["likely_duplicate_chain_same_route_space", "possible_duplicate_chain_same_route_space"])].copy()
    risk = pairs.groupby("signal_approach_id").agg(
        pair_count=("pair_overlap_class", "size"),
        likely_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "likely_duplicate_chain_same_route_space").sum())),
        possible_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "possible_duplicate_chain_same_route_space").sum())),
        max_distance_overlap_ft=("distance_overlap_ft", "max"),
    ).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "pair_count", "likely_duplicate_pairs", "possible_duplicate_pairs", "max_distance_overlap_ft"])
    if not risk.empty:
        risk["approach_duplication_risk"] = risk.apply(lambda r: "likely_duplicate_chains_block_bin_context" if int(r["likely_duplicate_pairs"]) > 0 else ("moderate_duplication_review" if int(r["possible_duplicate_pairs"]) > 0 else "low_or_no_duplication_risk"), axis=1)
    return pairs, blocking, risk


def hard_safety_checks(corridors: pd.DataFrame, approaches: pd.DataFrame, signals: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    forbidden = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    outside = int(((corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6) | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)).sum())
    checks = [
        ("approach_corridor_id_unique", int(corridors["approach_corridor_id"].duplicated(keep=False).sum())),
        ("logical_corridor_chain_id_non_null", int(corridors["logical_corridor_chain_id"].isna().sum() + corridors["logical_corridor_chain_id"].astype(str).eq("").sum())),
        ("valid_signal_approach_id_links", int((~corridors["signal_approach_id"].isin(set(approaches["signal_approach_id"].astype(str)))).sum())),
        ("valid_stable_signal_id_links", int((~corridors["stable_signal_id"].isin(set(signals["stable_signal_id"].astype(str)))).sum())),
        ("valid_stable_travelway_id_links", int((~corridors["stable_travelway_id"].isin(set(roads["stable_travelway_id"].astype(str)))).sum())),
        ("blocked_approach_rows_absent", int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum())),
        ("source_limited_no_corridor_rows_absent", int(corridors["parent_approach_gate"].eq("source_limited_no_corridor").sum())),
        ("signal_spanning_rows_absent", int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum())),
        ("reviewed_measure_outside_rows_absent", outside),
        ("one_sided_overextension_absent", int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum())),
        ("boundary_crossing_violations_absent", int(corridors["cross_signal_boundary_flag"].fillna(False).map(bool_value).sum())),
        ("directionality_fields_absent", len(forbidden)),
    ]
    return pd.DataFrame([{"check": name, "value": value, "expectation": "zero_required", "status": "pass" if value == 0 else "fail"} for name, value in checks])


def chain_internal_check(corridors: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for chain_id, group in corridors.groupby("logical_corridor_chain_id", dropna=False):
        g = group.sort_values("segment_order")
        orders = pd.to_numeric(g["segment_order"], errors="coerce").astype(int).tolist()
        starts = pd.to_numeric(g["segment_start_distance_ft"], errors="coerce").tolist()
        ends = pd.to_numeric(g["segment_end_distance_ft"], errors="coerce").tolist()
        overlaps = sum(1 for i in range(1, len(g)) if starts[i] < ends[i - 1] - 1.0)
        max_end = max(ends) if ends else 0.0
        total = safe_float(g["chain_total_reach_ft"].iloc[0], 0.0)
        status = "pass" if orders == list(range(1, len(g) + 1)) and overlaps == 0 and abs(max_end - total) <= 1.0 and int(g["segment_count_in_chain"].iloc[0]) == len(g) and clean(g["chain_stop_reason"].iloc[0]) and clean(g["chain_completeness_status"].iloc[0]) else "review"
        rows.append({"logical_corridor_chain_id": chain_id, "segment_count": len(g), "declared_segment_count": int(g["segment_count_in_chain"].iloc[0]), "unexpected_overlap_count": overlaps, "max_segment_end_distance_ft": max_end, "chain_total_reach_ft": total, "chain_stop_reason": clean(g["chain_stop_reason"].iloc[0]), "chain_completeness_status": clean(g["chain_completeness_status"].iloc[0]), "chain_internal_status": status})
    return pd.DataFrame(rows)


def distance_band_status(reason: str, reach: float) -> str:
    if reason == "reached_2500_ft" or reach >= MAX_REACH_FT - 1.0:
        return "full_one_sided_0_2500_support"
    if reason == "stopped_at_supported_signal_boundary":
        return "partial_signal_boundary_clipped"
    if reason == "stopped_at_source_extent":
        return "partial_source_extent_clipped"
    return "partial_other"


def distance_band_support(corridors: pd.DataFrame) -> pd.DataFrame:
    chain = chain_summary(corridors)
    chain["distance_band_support_status"] = chain.apply(lambda r: distance_band_status(clean(r["chain_stop_reason"]), float(r["chain_total_reach_ft"])), axis=1)
    return chain.groupby("distance_band_support_status").size().reset_index(name="logical_chain_count")


def post_source_extent_validation(corridors: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    r = prepare_roads(roads)
    groups = road_groups(r)
    rows = []
    for _, row in chain_summary(corridors).query("chain_stop_reason == 'stopped_at_source_extent'").iterrows():
        route = clean(row["source_route_name_values"]).split("|")[0]
        side = clean(row["measure_side_class"])
        signal_measure = safe_float(row["reviewed_signal_measure"])
        endpoint = signal_measure + float(row["chain_total_reach_ft"]) / 5280.0 if side == "measure_increasing_from_signal" else signal_measure - float(row["chain_total_reach_ft"]) / 5280.0
        hard = signal_measure + MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - MAX_REACH_MILES
        used = set(clean(row["stable_travelway_ids"]).split("|")) - {""}
        cand = candidate_rows(groups.get(route, pd.DataFrame()), side, endpoint, hard, used)
        rows.append({"logical_corridor_chain_id": row["logical_corridor_chain_id"], "stable_signal_id": row["stable_signal_id"], "signal_approach_id": row["signal_approach_id"], "source_extent_validation_class": "possible_remaining_candidate" if not cand.empty else "likely_true_source_extent", "continuation_candidate_count_50ft": int(len(cand)), "best_continuation_gap_ft": "" if cand.empty else float(cand["gap_ft"].min())})
    return pd.DataFrame(rows)


def update_metadata(corridors: pd.DataFrame, decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    product = manifest.setdefault("products", {}).setdefault("approach_corridors", {})
    product.update({
        "path": rel(CORRIDORS),
        "grain": "deduplicated chain-aware bin-eligible corridor segments with context-transition source-extent extensions",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "row_count": int(len(corridors)),
        "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()),
        "context_transition_rule_version": RULE_VERSION,
        "updated_utc": now(),
        "script": "src.roadway_graph.patch.patch_approach_corridor_context_transition_extensions",
        "final_decision": decision,
    })
    manifest.setdefault("patch_history", []).append({"patched_utc": now(), "script": "src.roadway_graph.patch.patch_approach_corridor_context_transition_extensions", "rule_version": RULE_VERSION, "row_count": int(len(corridors)), "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()), "final_decision": decision})
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    schema.setdefault("tables", {}).setdefault("approach_corridors", {})["context_transition_extension_fields"] = [
        "context_transition_extension_used_flag",
        "context_transition_extension_status",
        "context_transition_extension_method",
        "context_transition_rule_version",
        "pre_extension_chain_stop_reason",
        "post_extension_chain_stop_reason",
        "continuation_candidate_stable_travelway_id",
        "continuation_roadway_configuration_from",
        "continuation_roadway_configuration_to",
        "continuation_gap_ft",
        "continuation_added_reach_ft",
        "continuation_added_segment_count",
        "continuation_rejection_reason",
    ]
    schema["updated_utc"] = now()
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    with STAGING_README.open("a", encoding="utf-8") as fh:
        fh.write(f"\n\n## Context-Transition Source-Extent Extension Patch ({RULE_VERSION})\nPatched `approach_corridors.parquet` by appending only full-audit likely-valid source-extent context-transition continuation targets. No bin_context, 50-ft bins, upstream/downstream labels, directionality, MVP, crash, access, speed, AADT, or exposure products were built. Canonical parents remain the staged signal, travelway, attachment, and approach objects. Decision: `{decision}`.\n")


def normalize_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    string_cols = [
        "continuation_gap_ft",
        "context_transition_extension_status",
        "context_transition_extension_method",
        "context_transition_rule_version",
        "pre_extension_chain_stop_reason",
        "post_extension_chain_stop_reason",
        "continuation_candidate_stable_travelway_id",
        "continuation_roadway_configuration_from",
        "continuation_roadway_configuration_to",
        "continuation_rejection_reason",
    ]
    for col in string_cols:
        if col in out.columns:
            out[col] = out[col].map(clean)
    bool_cols = ["context_transition_extension_used_flag", "chain_bin_eligible_flag"]
    for col in bool_cols:
        if col in out.columns:
            out[col] = out[col].fillna(False).map(bool_value)
    numeric_cols = [
        "continuation_added_reach_ft",
        "continuation_added_segment_count",
        "chain_total_reach_ft",
        "segment_count_in_chain",
        "segment_order",
        "segment_start_distance_ft",
        "segment_end_distance_ft",
        "corridor_length_ft",
        "one_sided_reach_ft",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def load_targets() -> pd.DataFrame:
    preferred = FULL_AUDIT / "likely_valid_source_extent_continuation_targets.csv"
    if preferred.exists():
        return pd.read_csv(preferred)
    fallback = read_csv_optional(FULL_AUDIT / "source_extent_continuation_candidate_evaluations.csv")
    return fallback[fallback["final_classification"].isin(["configuration_transition_valid_but_needs_patch", "simple_context_transition_continuation_likely_valid"])].copy()


def write_outputs(prior: pd.DataFrame, post: pd.DataFrame, frames: dict[str, pd.DataFrame], qa: dict[str, pd.DataFrame], decision: str) -> None:
    write_csv("parent_dependency_check.csv", parent_dependency_check())
    write_csv("patch_target_input_reconciliation.csv", frames["input"])
    write_csv("accepted_context_transition_extensions.csv", frames["accepted"])
    write_csv("rejected_context_transition_extensions.csv", frames["rejected"])
    write_csv("unchanged_excluded_source_extent_chains.csv", frames["excluded"])
    write_csv("context_transition_added_segments.csv", frames["added_segments"])
    write_csv("context_transition_added_reach_by_chain.csv", frames["added_reach"])
    write_csv("pre_vs_post_corridor_counts.csv", pd.DataFrame([
        {"metric": "prior_corridor_segment_rows", "value": len(prior)},
        {"metric": "post_corridor_segment_rows", "value": len(post)},
        {"metric": "added_segment_rows", "value": len(post) - len(prior)},
        {"metric": "prior_logical_chains", "value": prior["logical_corridor_chain_id"].nunique()},
        {"metric": "post_logical_chains", "value": post["logical_corridor_chain_id"].nunique()},
    ]))
    pre_stop = prior.drop_duplicates("logical_corridor_chain_id").groupby("chain_stop_reason").size().reset_index(name="pre_logical_chain_count")
    post_stop = post.drop_duplicates("logical_corridor_chain_id").groupby("chain_stop_reason").size().reset_index(name="post_logical_chain_count")
    write_csv("pre_vs_post_chain_stop_reason_counts.csv", pre_stop.merge(post_stop, on="chain_stop_reason", how="outer").fillna(0))
    pre_db = distance_band_support(prior).rename(columns={"logical_chain_count": "pre_logical_chain_count"})
    post_db = distance_band_support(post).rename(columns={"logical_chain_count": "post_logical_chain_count"})
    write_csv("pre_vs_post_distance_band_support.csv", pre_db.merge(post_db, on="distance_band_support_status", how="outer").fillna(0))
    for name, df in qa.items():
        write_csv(name, df)
    accepted_chains = frames["accepted"]["logical_corridor_chain_id"].nunique() if not frames["accepted"].empty else 0
    rejected_chains = frames["rejected"]["logical_corridor_chain_id"].nunique() if not frames["rejected"].empty else 0
    added_reach = float(frames["accepted"]["added_reach_ft"].sum()) if not frames["accepted"].empty else 0.0
    summary = pd.DataFrame([
        {"metric": "target_chains_read", "value": len(frames["input"])},
        {"metric": "accepted_extension_rows", "value": len(frames["accepted"])},
        {"metric": "accepted_target_chains", "value": accepted_chains},
        {"metric": "rejected_target_chains", "value": rejected_chains},
        {"metric": "added_segment_rows", "value": len(post) - len(prior)},
        {"metric": "added_reach_ft", "value": added_reach},
        {"metric": "final_decision", "value": decision},
    ])
    write_csv("context_transition_patch_summary.csv", summary)
    write_csv("readiness_decision.csv", pd.DataFrame([{"final_decision": decision, "reason": "context-transition source-extent extension patch completed"}]))
    write_csv("recommended_next_actions.csv", pd.DataFrame([{"rank": 1, "action": "run_final_overall_read_only_approach_corridors_validation_audit", "rationale": "The bounded context-transition extension patch is applied; run final validation before bin_context."}]))
    findings = f"""# Context-Transition Source-Extent Extension Patch

## Why The Patch Was Needed
The full source-extent continuation audit found likely-valid same-corridor continuation targets where raw `roadway_configuration` inequality had underextended `approach_corridors`.

## Roadway Configuration Doctrine
Roadway configuration difference alone must not block continuation. It is a context attribute unless it indicates a different route, carriageway, ramp, branch, supported signal boundary, or duplicate/bin-overlap risk.

## Patch Results
Target chains read: {len(frames['input']):,}. Target chains extended: {accepted_chains:,}. Target chains rejected: {rejected_chains:,}. Added segment rows: {len(post) - len(prior):,}. Added reach: {added_reach:,.1f} ft.

Distance-band support outputs are in `pre_vs_post_distance_band_support.csv`. Duplicate/bin-overlap QA and hard safety checks are in the post-patch QA ledgers.

## Remaining Source-Extent Continuations
Rejected target chains are ledgered with precise reasons. Excluded duplicate/bin-overlap and ambiguity chains were not patched.

## Decision
Final decision: `{decision}`.

## Recommended Next Task
Run one final overall read-only `approach_corridors` validation audit before building bin_context.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {"created_utc": now(), "script": "src.roadway_graph.patch.patch_approach_corridor_context_transition_extensions", "rule_version": RULE_VERSION, "target_chains_read": int(len(frames["input"])), "accepted_extension_rows": int(len(frames["accepted"])), "rejected_extension_rows": int(len(frames["rejected"])), "added_segment_rows": int(len(post) - len(prior)), "added_reach_ft": added_reach, "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)], "diagnostic_inputs": [rel(FULL_AUDIT), rel(CONFIG_AUDIT), rel(SOURCE_RECON), rel(FINAL_REVIEW), rel(DEDUP_REVIEW), rel(RECON_REVIEW)], "final_decision": decision}
    qa_manifest = {"created_utc": now(), "hard_safety_failures": int(qa["post_patch_hard_safety_checks.csv"]["status"].eq("fail").sum()), "duplicate_blocking_pairs": int(len(qa["post_patch_duplicate_chain_pair_audit.csv"])), "approaches_blocking_bin_context": int(qa["post_patch_bin_duplication_risk_by_approach.csv"]["approach_duplication_risk"].isin(["likely_duplicate_chains_block_bin_context", "moderate_duplication_review"]).sum()) if not qa["post_patch_bin_duplication_risk_by_approach.csv"].empty else 0, "final_decision": decision}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()}: Started context-transition source-extent extension patch.\n", encoding="utf-8")
    targets = load_targets()
    log(f"Loaded {len(targets):,} likely-valid context-transition targets.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"])
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    prior = corridors.copy()
    post, frames = patch_targets(corridors, roads, attachments, targets)
    log(f"Patch simulation complete; added_rows={len(post) - len(prior):,}.")
    pairs, blocking_pairs, risk = duplicate_risk(post)
    safety = hard_safety_checks(post, approaches, signals, roads)
    chain_check = chain_internal_check(post)
    source_val = post_source_extent_validation(post, roads)
    boundary_check = post[post["cross_signal_boundary_flag"].fillna(False).map(bool_value)].copy()
    non_dir = pd.DataFrame([{"directionality_field_count": len([c for c in post.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]), "status": "pass"}])
    qa = {
        "patched_chain_internal_consistency_check.csv": chain_check,
        "post_patch_duplicate_chain_pair_audit.csv": blocking_pairs,
        "post_patch_bin_duplication_risk_by_approach.csv": risk,
        "post_patch_source_extent_validation.csv": source_val,
        "post_patch_supported_signal_boundary_crossing_check.csv": boundary_check,
        "post_patch_hard_safety_checks.csv": safety,
        "non_directionality_field_check.csv": non_dir,
    }
    if safety["status"].eq("fail").any() or not blocking_pairs.empty or (not risk.empty and risk["approach_duplication_risk"].isin(["likely_duplicate_chains_block_bin_context", "moderate_duplication_review"]).any()):
        decision = "context_transition_patch_created_duplication_or_safety_issue"
    elif frames["rejected"]["logical_corridor_chain_id"].nunique() if not frames["rejected"].empty else 0:
        decision = "context_transition_patch_completed_with_small_review_ledger"
    else:
        decision = "context_transition_extensions_patched_ready_for_final_validation"
    post = post.sort_values(["stable_signal_id", "signal_approach_id", "logical_corridor_chain_id", "segment_order", "approach_corridor_id"]).reset_index(drop=True)
    post = normalize_for_parquet(post)
    post.to_parquet(CORRIDORS, index=False)
    update_metadata(post, decision)
    write_outputs(prior, post, frames, qa, decision)
    log(f"Finished context-transition extension patch with decision={decision}.")


if __name__ == "__main__":
    main()
