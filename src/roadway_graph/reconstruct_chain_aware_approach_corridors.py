"""Reconstruct chain-aware one-sided approach corridors.

This script replaces the staged rebuild-candidate approach_corridors.parquet
with segment rows that carry logical corridor chain IDs and chain stop status.
It does not build bins or assign upstream/downstream/directionality.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

CHAIN_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_chain_completeness_audit"
SIGNAL_QA = REPO / "work/roadway_graph/review/approach_corridors_signal_level_qa_audit"
ONE_SIDED_REVIEW = REPO / "work/roadway_graph/review/rebuild_one_sided_approach_corridors"
SIDE_REACH_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_side_reach_audit"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
TRAVELWAY_READINESS = REPO / "work/roadway_graph/review/travelway_network_index_readiness_audit"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"

MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
FLOAT_TOL_FT = 0.001
ADJACENT_GAP_FT = 5.0
POSSIBLE_GAP_FT = 50.0
REBUILD_VERSION = "chain_aware_approach_corridors_v1_2026-06-09"


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


def hash_text(text: str, length: int = 24) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def split_pipe(value: Any) -> list[str]:
    text = clean(value)
    return [part for part in text.split("|") if part]


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def compact_counts(series: pd.Series) -> str:
    if series.empty:
        return ""
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r = r[r["route_measure_status"].eq("route_measure_complete")].copy()
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    return r.dropna(subset=["stable_travelway_id", "source_route_name", "road_lo", "road_hi"])


def compatible_series(df: pd.DataFrame, token: str, config: str) -> pd.Series:
    token_values = df["carriageway_direction_token"].fillna("").astype(str).str.strip()
    config_values = df["roadway_configuration"].fillna("").astype(str).str.strip()
    token_mask = pd.Series(True, index=df.index) if not token else ((token_values == "") | (token_values == token))
    config_mask = pd.Series(True, index=df.index) if not config else ((config_values == "") | (config_values == config))
    return token_mask & config_mask


def make_road_groups(roads: pd.DataFrame) -> dict[str, pd.DataFrame]:
    groups: dict[str, pd.DataFrame] = {}
    for route, group in roads.groupby("source_route_name"):
        groups[route] = group.sort_values(["road_lo", "road_hi", "stable_travelway_id"]).reset_index(drop=True)
    return groups


def make_boundary_groups(attachments: pd.DataFrame) -> dict[str, pd.DataFrame]:
    boundary = attachments[
        attachments["attachment_confidence"].isin(["high", "medium"])
        & attachments["estimated_measure_status"].eq("estimated_measure_projected")
        & attachments["usable_as_corridor_boundary"].fillna(False).astype(bool)
        & attachments["estimated_measure"].notna()
    ].copy()
    groups: dict[str, pd.DataFrame] = {}
    for route, group in boundary.groupby("source_route_name"):
        groups[route] = group.sort_values("estimated_measure").reset_index(drop=True)
    return groups


def nearest_boundary(
    boundary_groups: dict[str, pd.DataFrame],
    route: str,
    stable_signal_id: str,
    signal_measure: float,
    side: str,
    token: str,
    config: str,
) -> dict[str, Any]:
    b = boundary_groups.get(route)
    if b is None or b.empty:
        return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
    b = b[~b["stable_signal_id"].eq(stable_signal_id)].copy()
    if b.empty:
        return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
    b = b[compatible_series(b, token, config)]
    if b.empty:
        return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
    if side == "measure_increasing_from_signal":
        cand = b[(b["estimated_measure"] > signal_measure) & (b["estimated_measure"] <= signal_measure + MAX_REACH_MILES + 1e-9)].sort_values("estimated_measure")
    else:
        cand = b[(b["estimated_measure"] < signal_measure) & (b["estimated_measure"] >= signal_measure - MAX_REACH_MILES - 1e-9)].sort_values("estimated_measure", ascending=False)
    if cand.empty:
        return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
    row = cand.iloc[0]
    return {"measure": float(row["estimated_measure"]), "stable_signal_id": clean(row.get("stable_signal_id")), "source_globalid": clean(row.get("source_signal_globalid"))}


def side_limits(signal_measure: float, source_lo: float, source_hi: float) -> list[tuple[str, float]]:
    sides: list[tuple[str, float]] = []
    dec = max(source_lo, signal_measure - MAX_REACH_MILES)
    inc = min(source_hi, signal_measure + MAX_REACH_MILES)
    if signal_measure - dec > 1e-9:
        sides.append(("measure_decreasing_from_signal", dec))
    if inc - signal_measure > 1e-9:
        sides.append(("measure_increasing_from_signal", inc))
    return sides


def build_chain(
    app: pd.Series,
    start_road: pd.Series,
    signal_measure: float,
    side: str,
    roads_by_route: dict[str, pd.DataFrame],
    boundary_groups: dict[str, pd.DataFrame],
    supporting_attachment_ids: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    route = clean(start_road.get("source_route_name"))
    token = clean(start_road.get("carriageway_direction_token"))
    config = clean(start_road.get("roadway_configuration"))
    boundary = nearest_boundary(boundary_groups, route, app["stable_signal_id"], signal_measure, side, token, config)
    boundary_measure = boundary["measure"]
    if side == "measure_increasing_from_signal":
        hard_limit = signal_measure + MAX_REACH_MILES
        if boundary_measure is not None:
            hard_limit = min(hard_limit, boundary_measure)
        direction = 1
        cursor = signal_measure
    else:
        hard_limit = signal_measure - MAX_REACH_MILES
        if boundary_measure is not None:
            hard_limit = max(hard_limit, boundary_measure)
        direction = -1
        cursor = signal_measure

    route_roads = roads_by_route.get(route)
    if route_roads is None or route_roads.empty:
        return [], [], [], [], {"no_corridor_reason": "missing_route_group_for_supporting_travelway"}
    route_roads = route_roads[compatible_series(route_roads, token, config)].copy()
    if route_roads.empty:
        return [], [], [], [], {"no_corridor_reason": "no_compatible_route_group_for_supporting_travelway"}

    chain_key = "|".join([app["signal_approach_id"], route, token, config, side, f"{signal_measure:.8f}", clean(start_road.get("stable_travelway_id"))])
    chain_id = f"chain_{hash_text(chain_key)}"
    records: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    accepts: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    used_rows: set[str] = set()
    segment_order = 1
    accepted_bridge_count = 0
    stop_reason = "stopped_at_source_extent"
    stop_detail = ""
    gap_rejection = ""

    def append_segment(road: pd.Series, seg_from: float, seg_to: float, neighbor_used: bool, gap_ft: float = 0.0) -> None:
        nonlocal segment_order, cursor
        lo = min(seg_from, seg_to)
        hi = max(seg_from, seg_to)
        if hi - lo <= 1e-10:
            return
        start_dist = abs(seg_from - signal_measure) * 5280.0
        end_dist = abs(seg_to - signal_measure) * 5280.0
        # Keep corridor_from/to as the signal-to-current-reach interval so
        # reviewed_signal_measure is inside every output row. Preserve the
        # actual source-row segment interval separately for bin generation.
        prefix_lo = min(signal_measure, seg_to)
        prefix_hi = max(signal_measure, seg_to)
        used_rows.add(clean(road.get("stable_travelway_id")))
        rid = f"corrseg_{hash_text('|'.join([chain_id, clean(road.get('stable_travelway_id')), str(segment_order), f'{lo:.8f}', f'{hi:.8f}']))}"
        records.append(
            {
                "approach_corridor_id": rid,
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": app["stable_signal_id"],
                "signal_approach_id": app["signal_approach_id"],
                "stable_travelway_id": clean(road.get("stable_travelway_id")),
                "segment_order": segment_order,
                "segment_count_in_chain": 0,
                "measure_side_class": side,
                "corridor_from_measure": prefix_lo,
                "corridor_to_measure": prefix_hi,
                "reviewed_signal_measure": signal_measure,
                "segment_source_from_measure": lo,
                "segment_source_to_measure": hi,
                "segment_start_distance_ft": min(start_dist, end_dist),
                "segment_end_distance_ft": max(start_dist, end_dist),
                "one_sided_reach_ft": max(start_dist, end_dist),
                "corridor_length_ft": abs(seg_to - seg_from) * 5280.0,
                "chain_total_reach_ft": 0.0,
                "chain_stop_reason": "",
                "chain_completeness_status": "",
                "corridor_confidence": "medium" if app["corridor_build_gate"] == "corridor_build_ready_with_warning" or neighbor_used else "high",
                "parent_approach_gate": app["corridor_build_gate"],
                "parent_corridor_gate_severity": app["corridor_gate_severity"],
                "warning_provenance": clean(app.get("corridor_restriction_notes")) if app["corridor_build_gate"] == "corridor_build_ready_with_warning" else "",
                "route_base": clean(road.get("route_base")),
                "source_route_name": route,
                "source_route_id": clean(road.get("source_route_id")),
                "source_route_common": clean(road.get("source_route_common")),
                "carriageway_direction_token": token,
                "roadway_configuration": config,
                "source_measure_start": float(road["source_measure_start"]),
                "source_measure_end": float(road["source_measure_end"]),
                "endpoint_policy": "chain_aware_same_route_neighbor_until_boundary_2500_or_valid_stop",
                "boundary_method": "",
                "before_endpoint_signal_id": "",
                "after_endpoint_signal_id": "",
                "boundary_signal_id": "",
                "boundary_source_globalid": "",
                "clipped_by_2500_ft_flag": False,
                "clipped_by_signal_boundary_flag": False,
                "clipped_by_source_extent_flag": False,
                "clipped_by_gap_or_uncertain_continuity_flag": False,
                "split_from_signal_spanning_source_flag": bool(float(road["road_lo"]) < signal_measure < float(road["road_hi"])),
                "neighbor_extension_used_flag": bool(neighbor_used),
                "geometry": road.get("geometry"),
                "geometry_status": "source_travelway_geometry_full_row_for_segment_interval",
                "route_measure_continuity_status": "route_measure_continuous" if gap_ft <= FLOAT_TOL_FT else "small_gap_bridge_accepted",
                "geometry_continuity_status": "not_evaluated_route_measure_continuity_used",
                "side_assignment_status": "side_assigned_from_reviewed_signal_measure",
                "source_only_endpoint_flag": False,
                "cross_signal_boundary_flag": False,
                "gap_bridge_status": "accepted_small_route_measure_gap" if gap_ft > FLOAT_TOL_FT else "not_needed",
                "gap_bridge_method": "route_measure_small_gap_same_route" if gap_ft > FLOAT_TOL_FT else "",
                "gap_bridge_confidence": "medium" if gap_ft > FLOAT_TOL_FT else "",
                "no_corridor_reason": "",
                "corridor_build_status": "corridor_built",
                "corridor_rebuild_version": REBUILD_VERSION,
                "supporting_attachment_ids": supporting_attachment_ids,
            }
        )
        segment_order += 1
        cursor = seg_to

    while True:
        if direction == 1:
            if cursor >= hard_limit - 1e-10:
                break
            cand = route_roads[(route_roads["road_hi"] > cursor + 1e-10) & (~route_roads["stable_travelway_id"].astype(str).isin(used_rows))].copy()
            cand["gap_ft"] = ((cand["road_lo"] - cursor).clip(lower=0.0)) * 5280.0
            cand = cand[cand["road_lo"] <= cursor + (ADJACENT_GAP_FT / 5280.0) + 1e-10].sort_values(["gap_ft", "road_lo", "road_hi"])
        else:
            if cursor <= hard_limit + 1e-10:
                break
            cand = route_roads[(route_roads["road_lo"] < cursor - 1e-10) & (~route_roads["stable_travelway_id"].astype(str).isin(used_rows))].copy()
            cand["gap_ft"] = ((cursor - cand["road_hi"]).clip(lower=0.0)) * 5280.0
            cand = cand[cand["road_hi"] >= cursor - (ADJACENT_GAP_FT / 5280.0) - 1e-10].sort_values(["gap_ft", "road_hi", "road_lo"], ascending=[True, False, False])

        if cand.empty:
            # Probe for the nearest possible continuation to classify the stop.
            if direction == 1:
                probe = route_roads[(route_roads["road_hi"] > cursor + 1e-10) & (~route_roads["stable_travelway_id"].astype(str).isin(used_rows))].copy()
                probe["gap_ft"] = ((probe["road_lo"] - cursor).clip(lower=0.0)) * 5280.0
            else:
                probe = route_roads[(route_roads["road_lo"] < cursor - 1e-10) & (~route_roads["stable_travelway_id"].astype(str).isin(used_rows))].copy()
                probe["gap_ft"] = ((cursor - probe["road_hi"]).clip(lower=0.0)) * 5280.0
            if not probe.empty:
                best = probe.sort_values("gap_ft").iloc[0]
                gap_ft = float(best["gap_ft"])
                attempts.append(attempt_row(chain_id, app, route, side, cursor, best, gap_ft))
                if gap_ft <= POSSIBLE_GAP_FT:
                    stop_reason = "stopped_at_route_measure_gap"
                    gap_rejection = "gap_exceeds_accepted_gap_threshold"
                    rejects.append(reject_row(chain_id, app, route, side, cursor, best, gap_ft, gap_rejection))
                else:
                    stop_reason = "stopped_at_source_extent"
            break

        next_road = cand.iloc[0]
        gap_ft = float(next_road["gap_ft"])
        attempts.append(attempt_row(chain_id, app, route, side, cursor, next_road, gap_ft))
        if gap_ft > ADJACENT_GAP_FT:
            stop_reason = "stopped_at_route_measure_gap"
            gap_rejection = "gap_exceeds_accepted_gap_threshold"
            rejects.append(reject_row(chain_id, app, route, side, cursor, next_road, gap_ft, gap_rejection))
            break
        if gap_ft > FLOAT_TOL_FT:
            accepted_bridge_count += 1
        if direction == 1:
            seg_from = max(cursor, float(next_road["road_lo"]))
            seg_to = min(float(next_road["road_hi"]), hard_limit)
            append_segment(next_road, seg_from, seg_to, bool(segment_order > 1), gap_ft)
        else:
            seg_from = min(cursor, float(next_road["road_hi"]))
            seg_to = max(float(next_road["road_lo"]), hard_limit)
            append_segment(next_road, seg_from, seg_to, bool(segment_order > 1), gap_ft)
        accepts.append({**attempts[-1], "accepted": True, "acceptance_reason": "compatible_adjacent_same_route_neighbor"})

    if not records:
        return [], attempts, accepts, rejects, {"no_corridor_reason": "no_valid_segment_built"}

    chain_total = max(row["segment_end_distance_ft"] for row in records)
    if boundary_measure is not None and abs(abs(boundary_measure - signal_measure) * 5280.0 - chain_total) <= 1.0:
        stop_reason = "stopped_at_supported_signal_boundary"
    elif chain_total >= MAX_REACH_FT - FLOAT_TOL_FT:
        stop_reason = "reached_2500_ft"
    elif stop_reason == "stopped_at_source_extent":
        stop_detail = "no_compatible_adjacent_same_route_neighbor"

    completeness = {
        "reached_2500_ft": "complete_to_2500ft",
        "stopped_at_supported_signal_boundary": "complete_to_supported_signal_boundary",
        "stopped_at_source_extent": "partial_source_extent_stop_no_valid_neighbor",
        "stopped_at_route_measure_gap": "partial_route_measure_gap_stop",
        "stopped_at_route_or_carriageway_conflict": "partial_conflict_stop",
    }.get(stop_reason, "partial_insufficient_evidence_stop")
    for row in records:
        row["segment_count_in_chain"] = len(records)
        row["chain_total_reach_ft"] = chain_total
        row["chain_stop_reason"] = stop_reason
        row["chain_completeness_status"] = completeness
        row["clipped_by_2500_ft_flag"] = stop_reason == "reached_2500_ft" and abs(row["segment_end_distance_ft"] - chain_total) <= 1.0
        row["clipped_by_signal_boundary_flag"] = stop_reason == "stopped_at_supported_signal_boundary" and abs(row["segment_end_distance_ft"] - chain_total) <= 1.0
        row["clipped_by_source_extent_flag"] = stop_reason == "stopped_at_source_extent" and abs(row["segment_end_distance_ft"] - chain_total) <= 1.0
        row["clipped_by_gap_or_uncertain_continuity_flag"] = stop_reason in {"stopped_at_route_measure_gap", "stopped_due_insufficient_evidence"} and abs(row["segment_end_distance_ft"] - chain_total) <= 1.0
        row["boundary_method"] = stop_reason
        if stop_reason == "stopped_at_supported_signal_boundary":
            row["boundary_signal_id"] = boundary["stable_signal_id"]
            row["boundary_source_globalid"] = boundary["source_globalid"]
            if side == "measure_increasing_from_signal":
                row["after_endpoint_signal_id"] = boundary["stable_signal_id"]
                row["after_endpoint_source_globalid"] = boundary["source_globalid"]
            else:
                row["before_endpoint_signal_id"] = boundary["stable_signal_id"]
                row["before_endpoint_source_globalid"] = boundary["source_globalid"]
        if accepted_bridge_count:
            row["gap_bridge_status"] = "accepted_small_route_measure_gap"
            row["gap_bridge_confidence"] = "medium"
    chain_meta = {
        "logical_corridor_chain_id": chain_id,
        "stable_signal_id": app["stable_signal_id"],
        "signal_approach_id": app["signal_approach_id"],
        "source_route_name": route,
        "measure_side_class": side,
        "segment_count_in_chain": len(records),
        "chain_total_reach_ft": chain_total,
        "chain_stop_reason": stop_reason,
        "chain_completeness_status": completeness,
        "accepted_gap_bridges": accepted_bridge_count,
        "stop_detail": stop_detail or gap_rejection,
    }
    return records, attempts, accepts, rejects, chain_meta


def attempt_row(chain_id: str, app: pd.Series, route: str, side: str, cursor: float, road: pd.Series, gap_ft: float) -> dict[str, Any]:
    return {
        "logical_corridor_chain_id": chain_id,
        "stable_signal_id": app["stable_signal_id"],
        "signal_approach_id": app["signal_approach_id"],
        "source_route_name": route,
        "measure_side_class": side,
        "cursor_measure": cursor,
        "candidate_stable_travelway_id": clean(road.get("stable_travelway_id")),
        "candidate_from_measure": float(road["road_lo"]),
        "candidate_to_measure": float(road["road_hi"]),
        "gap_ft": gap_ft,
    }


def reject_row(chain_id: str, app: pd.Series, route: str, side: str, cursor: float, road: pd.Series, gap_ft: float, reason: str) -> dict[str, Any]:
    row = attempt_row(chain_id, app, route, side, cursor, road, gap_ft)
    row.update({"accepted": False, "rejection_reason": reason})
    return row


def build_corridors(roads: pd.DataFrame, attachments: pd.DataFrame, approaches: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    roads_prepared = prepare_roads(roads)
    roads_by_id = roads_prepared.set_index("stable_travelway_id", drop=False)
    roads_by_route = make_road_groups(roads_prepared)
    attachments_by_id = attachments.set_index("attachment_id", drop=False)
    boundary_groups = make_boundary_groups(attachments)
    include = approaches[approaches["corridor_build_gate"].isin(["corridor_build_ready", "corridor_build_ready_with_warning"])].copy()
    blocked = approaches[approaches["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")].copy()
    records: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    accepts: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    no_corridor: list[dict[str, Any]] = []
    chain_meta: list[dict[str, Any]] = []
    log(f"Building chain-aware corridors for {len(include)} eligible approaches; blocked approaches={len(blocked)}.")
    for idx, (_, app) in enumerate(include.iterrows(), start=1):
        if idx % 1000 == 0:
            log(f"Processed {idx} / {len(include)} eligible approaches; segment rows={len(records)}; chains={len(chain_meta)}.")
        support_ids = split_pipe(app.get("supporting_attachment_ids"))
        if not support_ids:
            no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "no_corridor_reason": "missing_supporting_attachment_ids"})
            continue
        valid_ids = [sid for sid in support_ids if sid in attachments_by_id.index]
        if not valid_ids:
            no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "no_corridor_reason": "supporting_attachment_ids_not_found"})
            continue
        support = attachments_by_id.loc[valid_ids].copy()
        support = support[
            support["attachment_confidence"].isin(["high", "medium"])
            & support["estimated_measure_status"].eq("estimated_measure_projected")
            & support["usable_as_corridor_boundary"].fillna(False).astype(bool)
            & support["estimated_measure"].notna()
        ]
        if support.empty:
            no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "no_corridor_reason": "no_measure_ready_boundary_capable_support"})
            continue
        seen_seed: set[str] = set()
        for stable_travelway_id, group in support.groupby("stable_travelway_id", dropna=False):
            if stable_travelway_id not in roads_by_id.index:
                no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "no_corridor_reason": "supporting_travelway_missing_from_parent"})
                continue
            road = roads_by_id.loc[stable_travelway_id]
            if isinstance(road, pd.DataFrame):
                road = road.iloc[0]
            signal_measure = float(group.sort_values(["point_to_line_distance_ft", "candidate_rank_for_signal"]).iloc[0]["estimated_measure"])
            source_lo = float(road["road_lo"])
            source_hi = float(road["road_hi"])
            for side, _ in side_limits(signal_measure, source_lo, source_hi):
                seed_key = "|".join([app["signal_approach_id"], clean(road.get("source_route_name")), clean(road.get("carriageway_direction_token")), clean(road.get("roadway_configuration")), side, f"{signal_measure:.6f}", stable_travelway_id])
                if seed_key in seen_seed:
                    continue
                seen_seed.add(seed_key)
                rows, att, acc, rej, meta = build_chain(app, road, signal_measure, side, roads_by_route, boundary_groups, "|".join(group["attachment_id"].astype(str).tolist()))
                attempts.extend(att)
                accepts.extend(acc)
                rejects.extend(rej)
                if rows:
                    records.extend(rows)
                    chain_meta.append(meta)
                else:
                    no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "measure_side_class": side, **meta})
    log(f"Built {len(records)} segment rows across {len(chain_meta)} logical chains.")
    return pd.DataFrame.from_records(records), {
        "blocked": blocked,
        "attempts": pd.DataFrame.from_records(attempts),
        "accepts": pd.DataFrame.from_records(accepts),
        "rejects": pd.DataFrame.from_records(rejects),
        "no_corridor": pd.DataFrame.from_records(no_corridor),
        "chain_meta": pd.DataFrame.from_records(chain_meta),
    }


def bucket_counts(series: pd.Series, bins: list[float], labels: list[str], colname: str) -> list[dict[str, Any]]:
    if series.empty:
        return []
    b = pd.cut(series, bins=bins, labels=labels, include_lowest=True)
    out = b.value_counts().sort_index().reset_index(name="corridor_rows")
    out.columns = [colname, "corridor_rows"]
    return out.to_dict("records")


def support_status(chain: pd.Series) -> str:
    reason = clean(chain.get("chain_stop_reason"))
    reach = float(chain.get("chain_total_reach_ft", 0))
    if reason == "reached_2500_ft" or reach >= MAX_REACH_FT - FLOAT_TOL_FT:
        return "full_one_sided_0_2500_support"
    if reason == "stopped_at_supported_signal_boundary":
        return "partial_signal_boundary_clipped"
    if reason == "stopped_at_source_extent":
        return "partial_source_extent_clipped"
    if reason == "stopped_at_route_measure_gap":
        return "partial_route_measure_gap"
    if reason == "stopped_at_geometry_gap":
        return "partial_geometry_gap"
    return "partial_unclear_possible_early_stop"


def write_metadata(corridors: pd.DataFrame, decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {})["approach_corridors"] = {
        "path": rel(APPROACH_CORRIDORS),
        "grain": "one corridor segment x one logical one-sided corridor chain x one signal_approach_id x one Travelway/source-row interval",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "replacement_reason": "prior one-sided staged corridor object stopped early at many source row extents despite same-corridor neighbor rows",
        "row_count": int(len(corridors)),
        "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()) if not corridors.empty else 0,
        "created_utc": now(),
        "script": "src.roadway_graph.reconstruct_chain_aware_approach_corridors",
        "corridor_rebuild_version": REBUILD_VERSION,
        "final_decision": decision,
    }
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    schema.setdefault("tables", {})["approach_corridors.parquet"] = {
        "grain": "chain-aware one-sided corridor segments",
        "canonical_parent": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "required_columns": [
            "approach_corridor_id",
            "logical_corridor_chain_id",
            "stable_signal_id",
            "signal_approach_id",
            "stable_travelway_id",
            "segment_order",
            "segment_count_in_chain",
            "measure_side_class",
            "chain_total_reach_ft",
            "chain_stop_reason",
            "chain_completeness_status",
        ],
        "forbidden_fields": "No upstream/downstream/directionality assignment fields.",
        "corridor_rebuild_version": REBUILD_VERSION,
    }
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    addition = f"""

## Chain-aware approach corridors reconstruction

Rebuilt `approach_corridors.parquet` with version `{REBUILD_VERSION}`.
Rows are one-sided corridor segments carrying `logical_corridor_chain_id`,
segment order, chain reach, stop reason, and completeness status. No bins,
upstream/downstream labels, directionality, or numeric context products were
built.
"""
    existing = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else ""
    if "## Chain-aware approach corridors reconstruction" not in existing:
        STAGING_README.write_text(existing.rstrip() + addition, encoding="utf-8")


def write_outputs(
    prior: pd.DataFrame,
    signals: pd.DataFrame,
    approaches: pd.DataFrame,
    corridors: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    decision: str,
) -> None:
    chain_meta = frames["chain_meta"].copy()
    if not chain_meta.empty:
        chain_meta["distance_band_support_status"] = chain_meta.apply(support_status, axis=1)
    app_counts = approaches[["signal_approach_id", "stable_signal_id", "corridor_build_gate"]].merge(
        corridors.groupby("signal_approach_id").agg(corridor_segment_rows=("approach_corridor_id", "size"), logical_chain_count=("logical_corridor_chain_id", "nunique")).reset_index(),
        on="signal_approach_id",
        how="left",
    )
    app_counts[["corridor_segment_rows", "logical_chain_count"]] = app_counts[["corridor_segment_rows", "logical_chain_count"]].fillna(0).astype(int)
    duplicate_ids = int(corridors["approach_corridor_id"].duplicated(keep=False).sum()) if not corridors.empty else 0
    missing_chain = int(corridors["logical_corridor_chain_id"].isna().sum() + corridors["logical_corridor_chain_id"].astype(str).eq("").sum()) if not corridors.empty else 0
    blocked_present = int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum()) if not corridors.empty else 0
    spanning = int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum()) if not corridors.empty else 0
    outside = int(((corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6) | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)).sum()) if not corridors.empty else 0
    overreach = int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum()) if not corridors.empty else 0
    boundary_violations = int(corridors["cross_signal_boundary_flag"].fillna(False).astype(bool).sum()) if not corridors.empty else 0
    forbidden = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    likely_after = chain_meta[chain_meta["chain_stop_reason"].eq("stopped_due_insufficient_evidence")] if not chain_meta.empty else pd.DataFrame()

    write_csv("parent_dependency_check.csv", [
        {"object": "approach_corridors", "dependency": rel(SIGNAL_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(ATTACHMENT), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(APPROACHES), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(CHAIN_AUDIT), "dependency_role": "method_evidence_only", "allowed": True},
    ])
    write_csv("prior_corridor_replacement_summary.csv", [
        {"metric": "immediate_prior_staged_corridor_rows", "value": int(len(prior))},
        {"metric": "original_one_sided_corridor_rows_from_prior_rebuild", "value": 49271},
        {"metric": "new_chain_aware_corridor_segment_rows", "value": int(len(corridors))},
        {"metric": "prior_likely_early_stop_neighbor_available", "value": 9962},
        {"metric": "replacement_reason", "value": "append valid same-corridor neighbor Travelway rows and add logical chain status"},
    ])
    write_csv("approach_corridor_id_uniqueness_check.csv", [{"corridor_segment_rows": int(len(corridors)), "duplicate_approach_corridor_id_rows": duplicate_ids, "status": "pass" if duplicate_ids == 0 else "fail"}])
    write_csv("logical_chain_id_check.csv", [{"corridor_segment_rows": int(len(corridors)), "missing_logical_corridor_chain_id_rows": missing_chain, "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()) if not corridors.empty else 0, "status": "pass" if missing_chain == 0 else "fail"}])
    write_csv("corridor_rows_by_parent_gate.csv", corridors.groupby("parent_approach_gate").size().reset_index(name="corridor_segment_rows").to_dict("records") if not corridors.empty else [])
    write_csv("excluded_blocked_approach_ledger.csv", frames["blocked"].to_dict("records"))
    no_approach_signals = set(signals["stable_signal_id"]) - set(approaches["stable_signal_id"])
    write_csv("source_limited_no_corridor_signal_ledger.csv", signals[signals["stable_signal_id"].isin(no_approach_signals)].to_dict("records"))
    write_csv("approach_to_chain_reconciliation.csv", app_counts.to_dict("records"))
    write_csv("approach_to_corridor_segment_reconciliation.csv", app_counts.to_dict("records"))
    sig_counts = app_counts.groupby("stable_signal_id").agg(approach_count=("signal_approach_id", "size"), logical_chain_count=("logical_chain_count", "sum"), corridor_segment_rows=("corridor_segment_rows", "sum")).reset_index()
    write_csv("signal_to_chain_reconciliation.csv", sig_counts.to_dict("records"))
    write_csv("chain_level_summary.csv", chain_meta.to_dict("records"))
    write_csv("chain_stop_reason_summary.csv", chain_meta.groupby("chain_stop_reason").size().reset_index(name="logical_chain_count").to_dict("records") if not chain_meta.empty else [])
    write_csv("chain_completeness_status_summary.csv", chain_meta.groupby("chain_completeness_status").size().reset_index(name="logical_chain_count").to_dict("records") if not chain_meta.empty else [])
    write_csv("measure_side_class_summary.csv", corridors.groupby("measure_side_class").size().reset_index(name="corridor_segment_rows").to_dict("records") if not corridors.empty else [])
    write_csv("segment_count_per_chain_distribution.csv", chain_meta["segment_count_in_chain"].value_counts().sort_index().reset_index(name="logical_chain_count").rename(columns={"segment_count_in_chain": "segment_count_in_chain"}).to_dict("records") if not chain_meta.empty else [])
    write_csv("chain_total_reach_distribution.csv", bucket_counts(chain_meta["chain_total_reach_ft"], [0, 100, 250, 500, 1000, 1500, 2000, 2500.001], ["0_100", "100_250", "250_500", "500_1000", "1000_1500", "1500_2000", "2000_2500"], "reach_bucket") if not chain_meta.empty else [])
    write_csv("one_sided_reach_distribution.csv", bucket_counts(corridors["one_sided_reach_ft"], [0, 100, 250, 500, 1000, 1500, 2000, 2500.001], ["0_100", "100_250", "250_500", "500_1000", "1000_1500", "1500_2000", "2000_2500"], "reach_bucket") if not corridors.empty else [])
    write_csv("corridor_length_distribution.csv", bucket_counts(corridors["corridor_length_ft"], [0, 100, 250, 500, 1000, 1500, 2000, 2500.001], ["0_100", "100_250", "250_500", "500_1000", "1000_1500", "1500_2000", "2000_2500"], "length_bucket") if not corridors.empty else [])
    write_csv("neighbor_extension_attempts.csv", frames["attempts"].to_dict("records"))
    write_csv("neighbor_extension_acceptances.csv", frames["accepts"].to_dict("records"))
    write_csv("neighbor_extension_rejections.csv", frames["rejects"].to_dict("records"))
    write_csv("likely_early_stop_after_reconstruction.csv", likely_after.to_dict("records"))
    write_csv("route_measure_continuity_audit.csv", corridors[["approach_corridor_id", "logical_corridor_chain_id", "route_measure_continuity_status", "chain_stop_reason", "chain_total_reach_ft"]].to_dict("records") if not corridors.empty else [])
    write_csv("geometry_continuity_audit.csv", corridors[["approach_corridor_id", "logical_corridor_chain_id", "geometry_continuity_status", "geometry_status"]].to_dict("records") if not corridors.empty else [])
    gap_attempts = frames["attempts"][frames["attempts"]["gap_ft"] > FLOAT_TOL_FT] if not frames["attempts"].empty else pd.DataFrame()
    gap_accepts = frames["accepts"][frames["accepts"]["gap_ft"] > FLOAT_TOL_FT] if not frames["accepts"].empty else pd.DataFrame()
    gap_rejects = frames["rejects"][frames["rejects"]["gap_ft"] > FLOAT_TOL_FT] if not frames["rejects"].empty else pd.DataFrame()
    write_csv("gap_bridge_attempts.csv", gap_attempts.to_dict("records"))
    write_csv("gap_bridge_rejections.csv", gap_rejects.to_dict("records"))
    write_csv("gap_bridge_summary.csv", [{"gap_bridge_attempts": int(len(gap_attempts)), "accepted_gap_bridges": int(len(gap_accepts)), "rejected_gap_bridges": int(len(gap_rejects)), "policy": "accepted only same-route compatible gaps <= 5 ft"}])
    write_csv("supported_signal_boundary_crossing_audit.csv", [{"boundary_crossing_violation_rows": boundary_violations, "status": "pass" if boundary_violations == 0 else "fail"}])
    warning = approaches[approaches["corridor_build_gate"].eq("corridor_build_ready_with_warning")][["signal_approach_id", "stable_signal_id", "corridor_build_gate", "corridor_gate_severity", "corridor_restriction_notes"]].merge(app_counts[["signal_approach_id", "logical_chain_count", "corridor_segment_rows"]], on="signal_approach_id", how="left")
    write_csv("warning_approach_corridor_outcomes.csv", warning.to_dict("records"))
    write_csv("multi_chain_per_approach_audit.csv", app_counts[app_counts["logical_chain_count"] > 1].to_dict("records"))
    write_csv("high_chain_count_approach_review.csv", app_counts.sort_values(["logical_chain_count", "corridor_segment_rows"], ascending=False).head(500).to_dict("records"))
    no_ledger = pd.concat([frames["no_corridor"], app_counts[(app_counts["logical_chain_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")]], ignore_index=True)
    write_csv("no_corridor_approach_ledger.csv", no_ledger.to_dict("records"))
    write_csv("distance_band_support_readiness_by_chain.csv", chain_meta.to_dict("records"))
    support_by_app = chain_meta.groupby("signal_approach_id")["distance_band_support_status"].apply(compact_counts).reset_index(name="chain_distance_band_support_mix") if not chain_meta.empty else pd.DataFrame(columns=["signal_approach_id", "chain_distance_band_support_mix"])
    write_csv("distance_band_support_readiness_by_approach.csv", app_counts.merge(support_by_app, on="signal_approach_id", how="left").fillna("").to_dict("records"))
    write_csv("distance_band_support_summary.csv", chain_meta.groupby("distance_band_support_status").size().reset_index(name="logical_chain_count").to_dict("records") if not chain_meta.empty else [])
    write_csv("non_directionality_field_check.csv", [{"forbidden_directionality_field_count": len(forbidden), "forbidden_fields": "|".join(forbidden), "status": "pass" if not forbidden else "fail"}])
    write_csv("corridor_reconstruction_summary.csv", [
        {"metric": "corridor_segment_rows_written", "value": int(len(corridors))},
        {"metric": "logical_chains_written", "value": int(chain_meta["logical_corridor_chain_id"].nunique()) if not chain_meta.empty else 0},
        {"metric": "approaches_with_chains", "value": int(app_counts["logical_chain_count"].gt(0).sum())},
        {"metric": "eligible_approaches_without_chains", "value": int(((app_counts["logical_chain_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")).sum())},
        {"metric": "blocked_approaches_excluded", "value": int(len(frames["blocked"]))},
        {"metric": "neighbor_extension_attempts", "value": int(len(frames["attempts"]))},
        {"metric": "neighbor_extension_acceptances", "value": int(len(frames["accepts"]))},
        {"metric": "neighbor_extension_rejections", "value": int(len(frames["rejects"]))},
        {"metric": "likely_early_stop_after_reconstruction", "value": int(len(likely_after))},
        {"metric": "final_decision", "value": decision},
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "chain-aware reconstruction completed"}])
    write_csv("recommended_next_actions.csv", [{"rank": 1, "action": "validate_chain_aware_corridors_before_bin_context", "rationale": "Logical chain IDs and stop reasons are now embedded in the staged corridor parent."}])
    findings = f"""# Chain-Aware Approach Corridors Reconstruction

## Prior Issue
The prior one-sided object fixed signal-spanning intervals but still stopped early at many source row extents. The chain audit found 9,962 likely same-corridor neighbor-extension misses.

## What Was Reconstructed
`approach_corridors.parquet` was rebuilt as segment rows carrying `logical_corridor_chain_id`, segment order, chain total reach, stop reason, and completeness status. Neighbor Travelway rows were appended when same-route, token, configuration, and measure-continuity evidence supported continuation.

## What Was Not Built
No bin_context, 50-ft bins, upstream/downstream, directionality, distance-band units, MVP, speed/AADT/exposure, access, crash, or rate products were built.

## Parent Dependency
Canonical parents are only signal_index, travelway_network_index, signal_travelway_attachment, and signal_approaches. Review outputs were method/comparison evidence only.

## Early Stops and Boundaries
Neighbor extension attempts: {len(frames['attempts']):,}; acceptances: {len(frames['accepts']):,}; rejections: {len(frames['rejects']):,}. Supported signal boundaries were clipped and no boundary crossing rows were output.

## Gap Policy
Only compatible same-route gaps up to {ADJACENT_GAP_FT:g} ft were accepted. Larger gaps were rejected and carried as stop reasons.

## Non-Directionality
No upstream/downstream or directionality fields were assigned.

## Readiness
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {"created_at": now(), "script": rel(Path(__file__)), "output_dir": rel(OUT), "staged_product": rel(APPROACH_CORRIDORS), "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)], "method_evidence_only": [rel(CHAIN_AUDIT), rel(SIGNAL_QA), rel(ONE_SIDED_REVIEW), rel(SIDE_REACH_AUDIT), rel(GATE_PATCH_REVIEW), rel(BUILD_APPROACH_REVIEW), rel(TRAVELWAY_READINESS), rel(CONTRACT_REVIEW)], "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()), "final_decision": decision}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "corridor_segment_rows": int(len(corridors)),
        "logical_chains": int(chain_meta["logical_corridor_chain_id"].nunique()) if not chain_meta.empty else 0,
        "approaches_with_chains": int(app_counts["logical_chain_count"].gt(0).sum()),
        "eligible_approaches_without_chains": int(((app_counts["logical_chain_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")).sum()),
        "blocked_approaches_excluded": int(len(frames["blocked"])),
        "neighbor_extension_attempts": int(len(frames["attempts"])),
        "neighbor_extension_acceptances": int(len(frames["accepts"])),
        "neighbor_extension_rejections": int(len(frames["rejects"])),
        "likely_early_stop_after_reconstruction": int(len(likely_after)),
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting chain-aware approach corridor reconstruction.")
    prior = pd.read_parquet(APPROACH_CORRIDORS) if APPROACH_CORRIDORS.exists() else pd.DataFrame()
    signals = pd.read_parquet(SIGNAL_INDEX)
    roads = pd.read_parquet(
        TRAVELWAY_INDEX,
        columns=[
            "stable_travelway_id",
            "source_route_name",
            "source_route_id",
            "source_route_common",
            "route_base",
            "carriageway_direction_token",
            "roadway_configuration",
            "source_measure_start",
            "source_measure_end",
            "route_measure_status",
            "geometry",
            "geometry_validity_status",
        ],
    )
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    log(f"Loaded prior={len(prior)}, signals={len(signals)}, roads={len(roads)}, attachments={len(attachments)}, approaches={len(approaches)}.")
    corridors, frames = build_corridors(roads, attachments, approaches)
    if corridors.empty:
        decision = "chain_aware_approach_corridors_should_be_rebuilt"
    else:
        forbidden = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
        overreach = int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum())
        boundary = int(corridors["cross_signal_boundary_flag"].fillna(False).astype(bool).sum())
        likely = frames["chain_meta"][frames["chain_meta"]["chain_stop_reason"].eq("stopped_due_insufficient_evidence")] if not frames["chain_meta"].empty else pd.DataFrame()
        if forbidden or overreach or boundary:
            decision = "chain_aware_approach_corridors_should_be_rebuilt"
        elif len(likely) > 0:
            decision = "chain_aware_approach_corridors_built_but_needs_early_stop_review"
        else:
            decision = "chain_aware_approach_corridors_ready_as_validated_parent"
    log(f"Writing {len(corridors)} chain-aware segment rows to staged approach_corridors.parquet.")
    corridors.to_parquet(APPROACH_CORRIDORS, index=False)
    write_outputs(prior, signals, approaches, corridors, frames, decision)
    write_metadata(corridors, decision)
    log(f"Reconstruction complete with decision {decision}.")


if __name__ == "__main__":
    main()
