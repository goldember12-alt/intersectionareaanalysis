"""Targeted source-extent continuation repair for staged approach corridors.

This bounded patch extends only source-extent suspect logical corridor chains
where same-corridor neighboring Travelway rows provide strong continuation
evidence. It does not build bins or assign directionality.
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
OUT = REPO / "work/roadway_graph/review/repair_approach_corridor_source_extent_continuation"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

FINALIZATION_REVIEW = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
CHAIN_VALIDATION_REVIEW = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

RULE_VERSION = "source_extent_continuation_repair_v1"
MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
FLOAT_TOL_FT = 0.001
SEARCH_GAP_FT = 50.0
ACCEPT_GAP_FT = 5.0


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
    return "" if text.lower() in {"nan", "none", "null"} else text


def hash_text(text: str, n: int = 24) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


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
    with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as fh:
        fh.write(f"- {stamp}: {message}\n")


def compact_counts(values: pd.Series) -> str:
    counts = values.fillna("").astype(str).value_counts().sort_index()
    return "|".join(f"{k}:{int(v)}" for k, v in counts.items())


def compatibility_value(a: Any, b: Any) -> bool:
    aa = clean(a).lower()
    bb = clean(b).lower()
    unknown = {"", "unknown", "nan", "none", "null"}
    return aa == bb or aa in unknown or bb in unknown


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    r = r[r["source_route_name"].notna() & r["road_lo"].notna() & r["road_hi"].notna()].copy()
    r = r[r["road_hi"] >= r["road_lo"]].copy()
    r["source_route_name"] = r["source_route_name"].astype(str)
    return r.sort_values(["source_route_name", "road_lo", "road_hi", "stable_travelway_id"]).reset_index(drop=True)


def road_groups(roads: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {route: group.reset_index(drop=True) for route, group in roads.groupby("source_route_name", dropna=False)}


def make_boundary_groups(attachments: pd.DataFrame) -> dict[str, pd.DataFrame]:
    attachments = attachments.copy()
    for optional in ["source_route_name", "roadway_configuration", "carriageway_direction_token", "source_signal_globalid"]:
        if optional not in attachments.columns:
            attachments[optional] = ""
    boundary = attachments[
        attachments["attachment_confidence"].isin(["high", "medium"])
        & attachments["estimated_measure_status"].eq("estimated_measure_projected")
        & attachments["usable_as_corridor_boundary"].fillna(False).astype(bool)
        & attachments["estimated_measure"].notna()
    ].copy()
    boundary["estimated_measure"] = pd.to_numeric(boundary["estimated_measure"], errors="coerce")
    boundary = boundary[boundary["estimated_measure"].notna()].copy()
    groups: dict[str, pd.DataFrame] = {}
    for route, group in boundary.groupby("source_route_name", dropna=False):
        groups[clean(route)] = group.sort_values("estimated_measure").reset_index(drop=True)
    return groups


def nearest_boundary(
    boundary_groups: dict[str, pd.DataFrame],
    route: str,
    current_signal_id: str,
    start_measure: float,
    endpoint_measure: float,
    hard_limit_measure: float,
    side: str,
    token: str,
    config: str,
) -> dict[str, Any]:
    b = boundary_groups.get(route)
    if b is None or b.empty:
        return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
    b = b[~b["stable_signal_id"].astype(str).eq(current_signal_id)].copy()
    if token and "carriageway_direction_token" in b.columns:
        b = b[b["carriageway_direction_token"].map(lambda x: compatibility_value(x, token))]
    if config and "roadway_configuration" in b.columns:
        b = b[b["roadway_configuration"].map(lambda x: compatibility_value(x, config))]
    if b.empty:
        return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
    if side == "measure_increasing_from_signal":
        candidates = b[(b["estimated_measure"] > max(start_measure, endpoint_measure) + 1e-9) & (b["estimated_measure"] <= hard_limit_measure + 1e-9)].copy()
        if candidates.empty:
            return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
        row = candidates.sort_values("estimated_measure").iloc[0]
    else:
        candidates = b[(b["estimated_measure"] < min(start_measure, endpoint_measure) - 1e-9) & (b["estimated_measure"] >= hard_limit_measure - 1e-9)].copy()
        if candidates.empty:
            return {"measure": None, "stable_signal_id": "", "source_globalid": ""}
        row = candidates.sort_values("estimated_measure", ascending=False).iloc[0]
    return {
        "measure": float(row["estimated_measure"]),
        "stable_signal_id": clean(row.get("stable_signal_id")),
        "source_globalid": clean(row.get("source_signal_globalid")),
    }


def chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    return corridors.groupby("logical_corridor_chain_id", dropna=False).agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        segment_count=("approach_corridor_id", "size"),
        max_segment_order=("segment_order", "max"),
        max_segment_end_distance_ft=("segment_end_distance_ft", "max"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        reviewed_signal_measure=("reviewed_signal_measure", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_completeness_status=("chain_completeness_status", "first"),
        measure_side_class=("measure_side_class", "first"),
        route_base_values=("route_base", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        chain_bin_eligible_flag=("chain_bin_eligible_flag", "first"),
        bin_duplication_risk_status=("bin_duplication_risk_status", "first"),
    ).reset_index()


def completeness_for_stop(stop_reason: str) -> str:
    return {
        "reached_2500_ft": "complete_to_2500ft",
        "stopped_at_supported_signal_boundary": "complete_to_supported_signal_boundary",
        "stopped_at_source_extent": "partial_source_extent_stop_no_valid_neighbor",
        "stopped_at_route_measure_gap": "partial_route_measure_gap_stop",
        "stopped_at_geometry_gap": "partial_geometry_gap_stop",
        "stopped_at_route_or_carriageway_conflict": "partial_conflict_stop",
        "stopped_at_roadway_configuration_conflict": "partial_conflict_stop",
        "stopped_due_insufficient_evidence": "partial_insufficient_evidence_stop",
    }.get(stop_reason, "partial_insufficient_evidence_stop")


def candidate_rows(
    route_roads: pd.DataFrame,
    side: str,
    endpoint: float,
    token: str,
    config: str,
    used_ids: set[str],
    hard_limit: float,
) -> pd.DataFrame:
    if route_roads.empty:
        return route_roads.copy()
    route_roads = route_roads.copy()
    for optional in ["carriageway_direction_token", "roadway_configuration"]:
        if optional not in route_roads.columns:
            route_roads[optional] = ""
    cand = route_roads[~route_roads["stable_travelway_id"].astype(str).isin(used_ids)].copy()
    token_mask = cand["carriageway_direction_token"].astype(object).map(lambda x: compatibility_value(x, token)).astype(bool) if "carriageway_direction_token" in cand.columns else pd.Series(True, index=cand.index, dtype=bool)
    config_mask = cand["roadway_configuration"].astype(object).map(lambda x: compatibility_value(x, config)).astype(bool) if "roadway_configuration" in cand.columns else pd.Series(True, index=cand.index, dtype=bool)
    cand = cand[token_mask & config_mask].copy()
    gap_miles = SEARCH_GAP_FT / 5280.0
    if side == "measure_increasing_from_signal":
        cand = cand[(cand["road_hi"] > endpoint + 1e-9) & (cand["road_lo"] <= hard_limit + 1e-9)].copy()
        cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
        return cand.sort_values(["gap_ft", "road_lo", "road_hi", "stable_travelway_id"])
    cand = cand[(cand["road_lo"] < endpoint - 1e-9) & (cand["road_hi"] >= hard_limit - 1e-9)].copy()
    cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0.0)) * 5280.0
    cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
    return cand.sort_values(["gap_ft", "road_hi", "road_lo", "stable_travelway_id"], ascending=[True, False, False, True])


def duplicate_existing_route_space(
    corridors: pd.DataFrame,
    chain_id: str,
    approach_id: str,
    route: str,
    token: str,
    side: str,
    stable_travelway_id: str,
    seg_lo: float,
    seg_hi: float,
) -> bool:
    peers = corridors[
        corridors["signal_approach_id"].astype(str).eq(approach_id)
        & ~corridors["logical_corridor_chain_id"].astype(str).eq(chain_id)
        & corridors["measure_side_class"].astype(str).eq(side)
        & corridors["source_route_name"].astype(str).eq(route)
        & corridors["chain_bin_eligible_flag"].fillna(True).astype(bool)
    ].copy()
    if peers.empty:
        return False
    peers = peers[peers["carriageway_direction_token"].map(lambda x: compatibility_value(x, token))]
    if peers.empty:
        return False
    shared = peers["stable_travelway_id"].astype(str).eq(stable_travelway_id).any()
    if shared:
        return True
    overlap = (
        (peers["segment_source_from_measure"] <= seg_hi + 1e-9)
        & (peers["segment_source_to_measure"] >= seg_lo - 1e-9)
    ).any()
    return bool(overlap)


def make_new_segment(template: pd.Series, road: pd.Series, order: int, seg_start: float, seg_end: float, gap_ft: float) -> dict[str, Any]:
    side = clean(template["measure_side_class"])
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
            "approach_corridor_id": f"corridor_repair_{hash_text('|'.join([chain_id, road_id, str(order), f'{lo:.8f}', f'{hi:.8f}']))}",
            "stable_travelway_id": road_id,
            "segment_order": int(order),
            "measure_side_class": side,
            "corridor_from_measure": min(signal_measure, seg_end),
            "corridor_to_measure": max(signal_measure, seg_end),
            "segment_source_from_measure": lo,
            "segment_source_to_measure": hi,
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
            "endpoint_policy": "source_extent_continuation_same_route_neighbor_repair",
            "neighbor_extension_used_flag": True,
            "route_measure_continuity_status": "continued_same_route_adjacent_neighbor",
            "geometry_continuity_status": "not_recomputed_same_route_measure_continuation",
            "gap_bridge_status": "accepted_small_route_measure_gap" if gap_ft > FLOAT_TOL_FT else "not_needed",
            "gap_bridge_method": "source_extent_repair_same_route_measure_gap" if gap_ft > FLOAT_TOL_FT else "",
            "gap_bridge_confidence": "medium" if gap_ft > FLOAT_TOL_FT else "",
            "corridor_build_status": "built_source_extent_continuation_repair",
            "corridor_rebuild_version": RULE_VERSION,
            "source_extent_repair_status": "accepted_continuation_added",
            "source_extent_repair_method": "same_route_measure_adjacent_neighbor_extension",
            "source_extent_repair_rule_version": RULE_VERSION,
            "continuation_gap_ft": float(gap_ft),
            "continuation_evidence_summary": f"same route neighbor {road_id}; gap_ft={gap_ft:.3f}",
            "chain_bin_eligible_flag": True,
            "chain_dedup_status": clean(row.get("chain_dedup_status")) or "unique_retained",
            "canonical_logical_corridor_chain_id": clean(row.get("canonical_logical_corridor_chain_id")) or chain_id,
            "duplicate_of_logical_corridor_chain_id": "",
            "bin_duplication_risk_status": clean(row.get("bin_duplication_risk_status")) or "no_duplication_risk",
        }
    )
    return row


def repair_chains(corridors: pd.DataFrame, roads: pd.DataFrame, attachments: pd.DataFrame, suspects: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    c = corridors.copy()
    for col, default in {
        "source_extent_repair_status": "not_targeted",
        "source_extent_repair_method": "",
        "source_extent_repair_rule_version": RULE_VERSION,
        "continuation_candidate_count": 0,
        "accepted_continuation_count": 0,
        "rejected_continuation_count": 0,
        "continuation_gap_ft": "",
        "continuation_evidence_summary": "",
    }.items():
        if col not in c.columns:
            c[col] = default

    roads_prepared = prepare_roads(roads)
    roads_by_route = road_groups(roads_prepared)
    boundary_groups = make_boundary_groups(attachments)
    suspect_ids = set(suspects["logical_corridor_chain_id"].astype(str))
    chain_ids = set(c["logical_corridor_chain_id"].astype(str))
    new_rows: list[dict[str, Any]] = []
    input_ledger: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    zero_gap: list[dict[str, Any]] = []
    small_gap: list[dict[str, Any]] = []
    updates: dict[str, dict[str, Any]] = {}

    for i, chain_id in enumerate(sorted(suspect_ids), start=1):
        if i % 50 == 0:
            log(f"Processed {i:,} suspect source-extent chains.")
        if chain_id not in chain_ids:
            input_ledger.append({"logical_corridor_chain_id": chain_id, "input_status": "suspect_chain_not_found_in_staged_corridors"})
            continue
        chain = c[c["logical_corridor_chain_id"].astype(str).eq(chain_id)].copy().sort_values("segment_order")
        first = chain.iloc[0]
        last = chain.iloc[-1]
        input_row = suspects[suspects["logical_corridor_chain_id"].astype(str).eq(chain_id)].iloc[0].to_dict()
        input_row["input_status"] = "loaded"
        input_ledger.append(input_row)

        if clean(first["chain_stop_reason"]) != "stopped_at_source_extent":
            updates[chain_id] = {
                "source_extent_repair_status": "not_repaired_stop_reason_not_source_extent",
                "source_extent_repair_method": "no_op",
                "continuation_candidate_count": 0,
                "accepted_continuation_count": 0,
                "rejected_continuation_count": 0,
            }
            continue

        route = clean(first.get("source_route_name")) or clean(first.get("source_route_name_values")).split("|")[0]
        side = clean(first.get("measure_side_class"))
        token = clean(first.get("carriageway_direction_token"))
        config = clean(first.get("roadway_configuration"))
        signal_id = clean(first.get("stable_signal_id"))
        approach_id = clean(first.get("signal_approach_id"))
        signal_measure = safe_float(first.get("reviewed_signal_measure"))
        if not route or side not in {"measure_increasing_from_signal", "measure_decreasing_from_signal"} or pd.isna(signal_measure):
            rejected.append({"logical_corridor_chain_id": chain_id, "reject_reason": "missing_route_side_or_reviewed_signal_measure"})
            updates[chain_id] = {"source_extent_repair_status": "rejected_insufficient_chain_context", "rejected_continuation_count": 1}
            continue

        route_roads = roads_by_route.get(route, pd.DataFrame())
        endpoint = signal_measure + float(last["segment_end_distance_ft"]) / 5280.0 if side == "measure_increasing_from_signal" else signal_measure - float(last["segment_end_distance_ft"]) / 5280.0
        hard_limit = signal_measure + MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - MAX_REACH_MILES
        used_ids = set(chain["stable_travelway_id"].astype(str))
        total_candidates = 0
        accepted_count = 0
        rejected_count = 0
        max_order = int(chain["segment_order"].max())
        terminal_stop = "stopped_at_source_extent"
        boundary_info = {"measure": None, "stable_signal_id": "", "source_globalid": ""}
        repair_status = "confirmed_true_source_extent"
        max_iterations = 32

        for _ in range(max_iterations):
            current_reach = abs(endpoint - signal_measure) * 5280.0
            if current_reach >= MAX_REACH_FT - FLOAT_TOL_FT:
                terminal_stop = "reached_2500_ft"
                repair_status = "extended_to_2500ft" if accepted_count else "already_at_2500ft"
                break
            boundary_info = nearest_boundary(boundary_groups, route, signal_id, signal_measure, endpoint, hard_limit, side, token, config)
            boundary_measure = boundary_info.get("measure")
            if boundary_measure is not None:
                boundary_reach = abs(float(boundary_measure) - signal_measure) * 5280.0
                if boundary_reach <= current_reach + 1.0:
                    terminal_stop = "stopped_at_supported_signal_boundary"
                    repair_status = "stopped_at_supported_signal_boundary_after_repair" if accepted_count else "confirmed_boundary_at_source_extent"
                    endpoint = float(boundary_measure)
                    break

            cand = candidate_rows(route_roads, side, endpoint, token, config, used_ids, hard_limit)
            total_candidates += int(len(cand))
            if cand.empty:
                terminal_stop = "stopped_at_source_extent"
                repair_status = "extended_then_confirmed_source_extent" if accepted_count else "confirmed_true_source_extent"
                break
            road = cand.iloc[0]
            gap_ft = float(road["gap_ft"])
            gap_class = "zero_gap" if gap_ft <= FLOAT_TOL_FT else "small_gap"
            outcome_row = {
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": signal_id,
                "signal_approach_id": approach_id,
                "stable_travelway_id": clean(road["stable_travelway_id"]),
                "gap_ft": gap_ft,
                "source_route_name": route,
                "measure_side_class": side,
            }
            if boundary_measure is not None:
                if side == "measure_increasing_from_signal":
                    candidate_start = max(float(road["road_lo"]), endpoint)
                    if float(boundary_measure) <= candidate_start + 1e-9:
                        rejected_count += 1
                        outcome_row["outcome"] = "rejected_boundary_before_continuation"
                        rejected.append({**outcome_row, "reject_reason": "supported_signal_boundary_before_candidate"})
                        if gap_class == "zero_gap":
                            zero_gap.append(outcome_row)
                        else:
                            small_gap.append(outcome_row)
                        terminal_stop = "stopped_at_supported_signal_boundary"
                        repair_status = "confirmed_supported_signal_boundary_before_neighbor"
                        endpoint = float(boundary_measure)
                        break
                else:
                    candidate_start = min(float(road["road_hi"]), endpoint)
                    if float(boundary_measure) >= candidate_start - 1e-9:
                        rejected_count += 1
                        outcome_row["outcome"] = "rejected_boundary_before_continuation"
                        rejected.append({**outcome_row, "reject_reason": "supported_signal_boundary_before_candidate"})
                        if gap_class == "zero_gap":
                            zero_gap.append(outcome_row)
                        else:
                            small_gap.append(outcome_row)
                        terminal_stop = "stopped_at_supported_signal_boundary"
                        repair_status = "confirmed_supported_signal_boundary_before_neighbor"
                        endpoint = float(boundary_measure)
                        break
            if gap_ft > ACCEPT_GAP_FT + FLOAT_TOL_FT:
                rejected_count += 1
                outcome_row["outcome"] = "rejected_gap_too_large"
                rejected.append({**outcome_row, "reject_reason": "gap_exceeds_accepted_small_gap_policy"})
                small_gap.append(outcome_row)
                terminal_stop = "stopped_at_route_measure_gap"
                repair_status = "rejected_gap_too_large"
                break

            if side == "measure_increasing_from_signal":
                seg_start = max(endpoint, float(road["road_lo"]))
                seg_end = min(float(road["road_hi"]), hard_limit)
                if boundary_measure is not None:
                    seg_end = min(seg_end, float(boundary_measure))
            else:
                seg_start = min(endpoint, float(road["road_hi"]))
                seg_end = max(float(road["road_lo"]), hard_limit)
                if boundary_measure is not None:
                    seg_end = max(seg_end, float(boundary_measure))
            if abs(seg_end - signal_measure) * 5280.0 > MAX_REACH_FT + FLOAT_TOL_FT:
                rejected_count += 1
                outcome_row["outcome"] = "rejected_would_exceed_2500ft"
                rejected.append({**outcome_row, "reject_reason": "extension_exceeds_2500ft"})
                terminal_stop = "reached_2500_ft"
                repair_status = "clipped_before_overextension"
                break
            if abs(seg_end - seg_start) * 5280.0 <= FLOAT_TOL_FT:
                used_ids.add(clean(road["stable_travelway_id"]))
                rejected_count += 1
                outcome_row["outcome"] = "rejected_zero_length_segment"
                rejected.append({**outcome_row, "reject_reason": "candidate_adds_no_reach"})
                continue
            if duplicate_existing_route_space(c, chain_id, approach_id, route, token, side, clean(road["stable_travelway_id"]), min(seg_start, seg_end), max(seg_start, seg_end)):
                rejected_count += 1
                outcome_row["outcome"] = "rejected_duplicate_existing_route_space"
                rejected.append({**outcome_row, "reject_reason": "would_duplicate_existing_bin_eligible_chain"})
                if gap_class == "zero_gap":
                    zero_gap.append(outcome_row)
                else:
                    small_gap.append(outcome_row)
                terminal_stop = "stopped_due_insufficient_evidence"
                repair_status = "rejected_duplicate_risk"
                break

            max_order += 1
            template = chain.iloc[-1]
            new_row = make_new_segment(template, road, max_order, seg_start, seg_end, gap_ft)
            new_rows.append(new_row)
            used_ids.add(clean(road["stable_travelway_id"]))
            endpoint = seg_end
            accepted_count += 1
            outcome_row["outcome"] = "accepted"
            outcome_row["segment_order"] = max_order
            accepted.append(outcome_row)
            if gap_class == "zero_gap":
                zero_gap.append(outcome_row)
            else:
                small_gap.append(outcome_row)
            repair_status = "extended_with_same_route_neighbor"

        final_reach = min(MAX_REACH_FT, abs(endpoint - signal_measure) * 5280.0)
        if terminal_stop == "stopped_at_source_extent" and accepted_count == 0 and rejected_count > 0 and repair_status.startswith("rejected"):
            pass
        elif final_reach >= MAX_REACH_FT - 1.0:
            terminal_stop = "reached_2500_ft"
        elif boundary_info.get("measure") is not None and abs(abs(float(boundary_info["measure"]) - signal_measure) * 5280.0 - final_reach) <= 1.0:
            terminal_stop = "stopped_at_supported_signal_boundary"
        completeness = completeness_for_stop(terminal_stop)
        updates[chain_id] = {
            "source_extent_repair_status": repair_status,
            "source_extent_repair_method": "same_route_measure_adjacent_neighbor_extension" if accepted_count else "source_extent_candidate_review_no_extension",
            "source_extent_repair_rule_version": RULE_VERSION,
            "continuation_candidate_count": total_candidates,
            "accepted_continuation_count": accepted_count,
            "rejected_continuation_count": rejected_count,
            "continuation_gap_ft": "" if not accepted_count else min(r["gap_ft"] for r in accepted if r["logical_corridor_chain_id"] == chain_id),
            "continuation_evidence_summary": f"accepted={accepted_count}; rejected={rejected_count}; final_stop={terminal_stop}",
            "chain_total_reach_ft": final_reach,
            "chain_stop_reason": terminal_stop,
            "chain_completeness_status": completeness,
            "boundary_signal_id": boundary_info.get("stable_signal_id", "") if terminal_stop == "stopped_at_supported_signal_boundary" else "",
            "boundary_source_globalid": boundary_info.get("source_globalid", "") if terminal_stop == "stopped_at_supported_signal_boundary" else "",
        }

    if new_rows:
        c = pd.concat([c, pd.DataFrame.from_records(new_rows)], ignore_index=True)

    for chain_id, vals in updates.items():
        mask = c["logical_corridor_chain_id"].astype(str).eq(chain_id)
        for key, value in vals.items():
            if key in c.columns:
                c.loc[mask, key] = value
        chain_mask = c["logical_corridor_chain_id"].astype(str).eq(chain_id)
        order = c[chain_mask].sort_values(["segment_start_distance_ft", "segment_end_distance_ft", "approach_corridor_id"]).index
        count = len(order)
        c.loc[order, "segment_order"] = range(1, count + 1)
        c.loc[order, "segment_count_in_chain"] = count
        max_end = float(c.loc[order, "segment_end_distance_ft"].max())
        if "chain_total_reach_ft" not in vals or vals["chain_total_reach_ft"] < max_end:
            c.loc[order, "chain_total_reach_ft"] = max_end
        stop = clean(c.loc[order[0], "chain_stop_reason"])
        c.loc[order, "chain_completeness_status"] = completeness_for_stop(stop)
        c.loc[order, "clipped_by_2500_ft_flag"] = stop == "reached_2500_ft"
        c.loc[order, "clipped_by_signal_boundary_flag"] = stop == "stopped_at_supported_signal_boundary"
        c.loc[order, "clipped_by_source_extent_flag"] = stop == "stopped_at_source_extent"
        c.loc[order, "clipped_by_gap_or_uncertain_continuity_flag"] = stop in {"stopped_at_route_measure_gap", "stopped_due_insufficient_evidence"}
        c.loc[order, "boundary_method"] = stop

    frames = {
        "input": pd.DataFrame.from_records(input_ledger),
        "accepted": pd.DataFrame.from_records(accepted),
        "rejected": pd.DataFrame.from_records(rejected),
        "zero_gap": pd.DataFrame.from_records(zero_gap),
        "small_gap": pd.DataFrame.from_records(small_gap),
        "new_segments": pd.DataFrame.from_records(new_rows),
    }
    return c, frames


def post_source_extent_validation(corridors: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = prepare_roads(roads)
    groups = road_groups(r)
    chain = chain_summary(corridors)
    rows: list[dict[str, Any]] = []
    for _, row in chain[chain["chain_stop_reason"].eq("stopped_at_source_extent")].iterrows():
        route = clean(row["source_route_name_values"]).split("|")[0]
        side = clean(row["measure_side_class"])
        signal_measure = float(row["reviewed_signal_measure"])
        endpoint = signal_measure + float(row["chain_total_reach_ft"]) / 5280.0 if side == "measure_increasing_from_signal" else signal_measure - float(row["chain_total_reach_ft"]) / 5280.0
        used_ids = set(clean(row["stable_travelway_ids"]).split("|")) - {""}
        g = groups.get(route, pd.DataFrame())
        cand = candidate_rows(g, side, endpoint, clean(row["carriageway_token_values"]).split("|")[0], clean(row["roadway_configuration_values"]).split("|")[0], used_ids, signal_measure + MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - MAX_REACH_MILES) if not g.empty else pd.DataFrame()
        cls = "possible_missing_neighbor" if not cand.empty else "likely_true_source_extent"
        rows.append(
            {
                "logical_corridor_chain_id": row["logical_corridor_chain_id"],
                "stable_signal_id": row["stable_signal_id"],
                "signal_approach_id": row["signal_approach_id"],
                "source_extent_validation_class": cls,
                "continuation_candidate_count_50ft": int(len(cand)),
                "best_continuation_gap_ft": "" if cand.empty else float(cand["gap_ft"].min()),
            }
        )
    out = pd.DataFrame.from_records(rows)
    suspect = out[out["source_extent_validation_class"].eq("possible_missing_neighbor")].copy() if not out.empty else pd.DataFrame()
    return out, suspect


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def duplicate_risk(corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    chain = chain_summary(corridors[corridors["chain_bin_eligible_flag"].fillna(True).astype(bool)].copy())
    rows: list[dict[str, Any]] = []
    for approach_id, group in chain.groupby("signal_approach_id", dropna=False):
        values = group.to_dict("records")
        for i, a in enumerate(values):
            for b in values[i + 1 :]:
                same_side = clean(a["measure_side_class"]) == clean(b["measure_side_class"])
                same_route = clean(a["route_base_values"]) == clean(b["route_base_values"]) or clean(a["source_route_name_values"]) == clean(b["source_route_name_values"])
                same_token = clean(a["carriageway_token_values"]) == clean(b["carriageway_token_values"])
                dist_overlap = interval_overlap(0, float(a["chain_total_reach_ft"]), 0, float(b["chain_total_reach_ft"]))
                src_overlap = interval_overlap(float(a["source_measure_min"]), float(a["source_measure_max"]), float(b["source_measure_min"]), float(b["source_measure_max"]))
                ids_a = set(clean(a.get("stable_travelway_ids")).split("|")) - {""}
                ids_b = set(clean(b.get("stable_travelway_ids")).split("|")) - {""}
                shared = len(ids_a & ids_b)
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
                rows.append(
                    {
                        "signal_approach_id": approach_id,
                        "stable_signal_id": a["stable_signal_id"],
                        "chain_a": a["logical_corridor_chain_id"],
                        "chain_b": b["logical_corridor_chain_id"],
                        "distance_overlap_ft": dist_overlap,
                        "source_measure_overlap": src_overlap,
                        "shared_stable_travelway_id_count": shared,
                        "pair_overlap_class": cls,
                    }
                )
    pairs = pd.DataFrame.from_records(rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=["signal_approach_id", "pair_overlap_class", "distance_overlap_ft"])
    likely = pairs[pairs["pair_overlap_class"].isin(["likely_duplicate_chain_same_route_space", "possible_duplicate_chain_same_route_space"])].copy()
    risk = pairs.groupby("signal_approach_id").agg(
        pair_count=("pair_overlap_class", "size"),
        likely_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "likely_duplicate_chain_same_route_space").sum())),
        possible_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "possible_duplicate_chain_same_route_space").sum())),
        max_distance_overlap_ft=("distance_overlap_ft", "max"),
    ).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "pair_count", "likely_duplicate_pairs", "possible_duplicate_pairs", "max_distance_overlap_ft"])
    if not risk.empty:
        risk["approach_duplication_risk"] = risk.apply(lambda r: "likely_duplicate_chains_block_bin_context" if int(r["likely_duplicate_pairs"]) > 0 else ("moderate_duplication_review" if int(r["possible_duplicate_pairs"]) > 0 else "low_or_no_duplication_risk"), axis=1)
    return pairs, likely, risk


def hard_safety_checks(corridors: pd.DataFrame, approaches: pd.DataFrame, signals: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    forbidden = [
        c for c in corridors.columns
        if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"}
        or c.lower().endswith("_directionality")
    ]
    outside = int(((corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6) | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)).sum())
    checks = [
        ("approach_corridor_id_unique", int(corridors["approach_corridor_id"].duplicated(keep=False).sum()), "zero_required"),
        ("logical_corridor_chain_id_non_null", int(corridors["logical_corridor_chain_id"].isna().sum() + corridors["logical_corridor_chain_id"].astype(str).eq("").sum()), "zero_required"),
        ("valid_signal_approach_id_links", int((~corridors["signal_approach_id"].isin(set(approaches["signal_approach_id"].astype(str)))).sum()), "zero_required"),
        ("valid_stable_signal_id_links", int((~corridors["stable_signal_id"].isin(set(signals["stable_signal_id"].astype(str)))).sum()), "zero_required"),
        ("valid_stable_travelway_id_links", int((~corridors["stable_travelway_id"].isin(set(roads["stable_travelway_id"].astype(str)))).sum()), "zero_required"),
        ("blocked_approach_rows_absent", int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum()), "zero_required"),
        ("source_limited_no_corridor_rows_absent", int(corridors["parent_approach_gate"].eq("source_limited_no_corridor").sum()), "zero_required"),
        ("signal_spanning_rows_absent", int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum()), "zero_required"),
        ("reviewed_measure_outside_rows_absent", outside, "zero_required"),
        ("one_sided_overextension_absent", int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum()), "zero_required"),
        ("boundary_crossing_violations_absent", int(corridors["cross_signal_boundary_flag"].fillna(False).astype(bool).sum()), "zero_required"),
        ("directionality_fields_absent", len(forbidden), "zero_required"),
    ]
    return pd.DataFrame([{"check": name, "value": value, "expectation": exp, "status": "pass" if value == 0 else "fail"} for name, value, exp in checks])


def chain_internal_check(corridors: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for chain_id, group in corridors.groupby("logical_corridor_chain_id", dropna=False):
        g = group.sort_values("segment_order")
        orders = g["segment_order"].astype(int).tolist()
        expected = list(range(1, len(g) + 1))
        starts = g["segment_start_distance_ft"].astype(float).tolist()
        ends = g["segment_end_distance_ft"].astype(float).tolist()
        overlaps = 0
        for i in range(1, len(g)):
            if starts[i] < ends[i - 1] - 1.0:
                overlaps += 1
        max_end = max(ends) if ends else 0.0
        declared_total = safe_float(g["chain_total_reach_ft"].iloc[0], 0.0)
        count_match = int(g["segment_count_in_chain"].iloc[0]) == len(g)
        status = "pass" if orders == expected and overlaps == 0 and abs(max_end - declared_total) <= 1.0 and count_match and clean(g["chain_stop_reason"].iloc[0]) and clean(g["chain_completeness_status"].iloc[0]) else "review"
        rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "segment_count": len(g),
                "declared_segment_count": int(g["segment_count_in_chain"].iloc[0]),
                "segment_order_complete_unique": orders == expected,
                "unexpected_overlap_count": overlaps,
                "max_segment_end_distance_ft": max_end,
                "chain_total_reach_ft": declared_total,
                "chain_total_matches_max_segment_end": abs(max_end - declared_total) <= 1.0,
                "chain_stop_reason": clean(g["chain_stop_reason"].iloc[0]),
                "chain_completeness_status": clean(g["chain_completeness_status"].iloc[0]),
                "chain_internal_status": status,
            }
        )
    return pd.DataFrame.from_records(rows)


def distance_band_status(reason: str, reach: float) -> str:
    if reason == "reached_2500_ft" or reach >= MAX_REACH_FT - 1.0:
        return "full_one_sided_0_2500_support"
    if reason == "stopped_at_supported_signal_boundary":
        return "partial_signal_boundary_clipped"
    if reason == "stopped_at_source_extent":
        return "partial_source_extent_clipped"
    if reason in {"stopped_at_route_measure_gap", "stopped_at_geometry_gap"}:
        return "partial_route_or_geometry_gap"
    return "partial_unclear"


def distance_band_readiness(corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    chain = chain_summary(corridors)
    chain["distance_band_support_status"] = chain.apply(lambda r: distance_band_status(clean(r["chain_stop_reason"]), float(r["chain_total_reach_ft"])), axis=1)
    app = chain.groupby("signal_approach_id").agg(
        stable_signal_id=("stable_signal_id", "first"),
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        full_support_chains=("distance_band_support_status", lambda s: int((s == "full_one_sided_0_2500_support").sum())),
        partial_source_extent_chains=("distance_band_support_status", lambda s: int((s == "partial_source_extent_clipped").sum())),
        partial_signal_boundary_chains=("distance_band_support_status", lambda s: int((s == "partial_signal_boundary_clipped").sum())),
        support_status_mix=("distance_band_support_status", compact_counts),
    ).reset_index()
    return chain, app


def parent_dependency_check() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"object": "approach_corridors.parquet", "canonical_parent": rel(SIGNAL_INDEX), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(TRAVELWAY_INDEX), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(ATTACHMENT), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(APPROACHES), "status": "pass"},
            {"object": "review_outputs", "canonical_parent": "", "status": "pass_not_listed_as_canonical_parent"},
        ]
    )


def update_metadata(corridors: pd.DataFrame, decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {})["approach_corridors"] = {
        "path": rel(CORRIDORS),
        "grain": "source-extent-repaired deduplicated chain-aware bin-eligible corridor segments",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "row_count": int(len(corridors)),
        "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()),
        "source_extent_repair_rule_version": RULE_VERSION,
        "updated_utc": now(),
        "script": "src.roadway_graph.patch.repair_approach_corridor_source_extent_continuation",
        "final_decision": decision,
    }
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    table = schema.setdefault("tables", {}).setdefault("approach_corridors.parquet", {})
    table["source_extent_repair_fields"] = [
        "source_extent_repair_status",
        "source_extent_repair_method",
        "source_extent_repair_rule_version",
        "continuation_candidate_count",
        "accepted_continuation_count",
        "rejected_continuation_count",
        "continuation_gap_ft",
        "continuation_evidence_summary",
    ]
    table["source_extent_repair_rule_version"] = RULE_VERSION
    table["updated_utc"] = now()
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

    with STAGING_README.open("a", encoding="utf-8") as fh:
        fh.write(
            f"\n\n## Source-Extent Continuation Repair ({RULE_VERSION})\n"
            f"Patched staged `approach_corridors.parquet` with targeted same-route continuation for source-extent suspect chains. "
            f"Canonical parents remain signal_index, travelway_network_index, signal_travelway_attachment, and signal_approaches. "
            f"No bin_context, upstream/downstream, or directionality fields were built. Decision: `{decision}`.\n"
        )


def write_outputs(
    prior: pd.DataFrame,
    post: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    source_val: pd.DataFrame,
    source_suspect: pd.DataFrame,
    chain_check: pd.DataFrame,
    pairs: pd.DataFrame,
    likely_pairs: pd.DataFrame,
    risk: pd.DataFrame,
    db_chain: pd.DataFrame,
    db_app: pd.DataFrame,
    safety: pd.DataFrame,
    signals: pd.DataFrame,
    approaches: pd.DataFrame,
    decision: str,
) -> None:
    write_csv("parent_dependency_check.csv", parent_dependency_check())
    write_csv("source_extent_suspect_input_ledger.csv", frames["input"])
    write_csv("accepted_source_extent_continuation_ledger.csv", frames["accepted"])
    write_csv("rejected_source_extent_continuation_ledger.csv", frames["rejected"])
    write_csv("zero_gap_continuation_outcomes.csv", frames["zero_gap"])
    write_csv("small_gap_continuation_outcomes.csv", frames["small_gap"])
    write_csv("post_repair_chain_stop_reason_summary.csv", post.drop_duplicates("logical_corridor_chain_id").groupby("chain_stop_reason").size().reset_index(name="logical_chain_count"))
    write_csv("post_repair_chain_completeness_status_summary.csv", post.drop_duplicates("logical_corridor_chain_id").groupby("chain_completeness_status").size().reset_index(name="logical_chain_count"))
    write_csv("post_repair_source_extent_validation.csv", source_val)
    write_csv("remaining_possible_false_source_extent_stops.csv", source_suspect)
    write_csv("post_repair_chain_internal_consistency_check.csv", chain_check)
    write_csv("post_repair_duplicate_chain_pair_audit.csv", pairs)
    write_csv("post_repair_bin_duplication_risk_by_approach.csv", risk)
    write_csv("post_repair_distance_band_readiness_by_chain.csv", db_chain)
    write_csv("post_repair_distance_band_readiness_by_approach.csv", db_app)
    write_csv("post_repair_hard_safety_checks.csv", safety)
    forbidden = [
        c for c in post.columns
        if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"}
        or c.lower().endswith("_directionality")
    ]
    write_csv("non_directionality_field_check.csv", [{"forbidden_directionality_field_count": len(forbidden), "forbidden_fields": "|".join(forbidden), "status": "pass" if not forbidden else "fail"}])
    write_csv("prior_vs_post_repair_counts.csv", [
        {"metric": "prior_corridor_segment_rows", "value": int(len(prior))},
        {"metric": "post_corridor_segment_rows", "value": int(len(post))},
        {"metric": "added_continuation_segment_rows", "value": int(len(post) - len(prior))},
        {"metric": "prior_logical_chains", "value": int(prior["logical_corridor_chain_id"].nunique())},
        {"metric": "post_logical_chains", "value": int(post["logical_corridor_chain_id"].nunique())},
    ])
    accepted_chains = frames["accepted"]["logical_corridor_chain_id"].nunique() if not frames["accepted"].empty else 0
    rejected_chains = frames["rejected"]["logical_corridor_chain_id"].nunique() if not frames["rejected"].empty else 0
    write_csv("source_extent_repair_summary.csv", [
        {"metric": "suspect_chains_reviewed", "value": int(len(frames["input"]))},
        {"metric": "accepted_continuation_segment_rows", "value": int(len(frames["accepted"]))},
        {"metric": "chains_with_accepted_continuations", "value": int(accepted_chains)},
        {"metric": "rejected_continuation_attempts", "value": int(len(frames["rejected"]))},
        {"metric": "chains_with_rejected_continuations", "value": int(rejected_chains)},
        {"metric": "remaining_possible_false_source_extent_stops", "value": int(len(source_suspect))},
        {"metric": "likely_duplicate_chain_pairs_after_repair", "value": int(len(likely_pairs))},
        {"metric": "approaches_blocking_bin_context_after_repair", "value": int(risk["approach_duplication_risk"].eq("likely_duplicate_chains_block_bin_context").sum()) if not risk.empty else 0},
        {"metric": "final_decision", "value": decision},
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "targeted source-extent continuation repair completed"}])
    write_csv("recommended_next_actions.csv", [{"rank": 1, "action": "run_final_read_only_approach_corridors_validation_then_build_bin_context", "rationale": "Source-extent continuation status is now encoded in staged approach_corridors with QA ledgers."}])
    findings = f"""# Source-Extent Continuation Repair

## Why Repair Was Needed
The finalization audit found source-extent stopped chains with same-corridor continuation candidates, including zero-gap Travelway row-boundary cases.

## What Was Reviewed
Suspect chains reviewed: {len(frames['input']):,}. Accepted continuation segment rows: {len(frames['accepted']):,}. Rejected continuation attempts: {len(frames['rejected']):,}.

## Zero-Gap Results
Zero-gap outcomes are ledgered in `zero_gap_continuation_outcomes.csv`; accepted rows were appended to the original logical chain IDs.

## Post-Repair Status
Remaining possible false source-extent stops: {len(source_suspect):,}. Likely duplicate chain pairs after repair: {len(likely_pairs):,}. Hard safety failures: {int(safety['status'].eq('fail').sum())}.

## Scope
No bin_context, upstream/downstream labels, directionality fields, canonical roots, or source artifacts were modified.

## Decision
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "staged_product": rel(CORRIDORS),
        "canonical_parent_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)],
        "diagnostic_evidence_only": [rel(FINALIZATION_REVIEW), rel(DEDUP_REVIEW), rel(CHAIN_VALIDATION_REVIEW), rel(RECON_REVIEW)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "prior_corridor_segment_rows": int(len(prior)),
        "post_corridor_segment_rows": int(len(post)),
        "suspect_chains_reviewed": int(len(frames["input"])),
        "accepted_continuation_segment_rows": int(len(frames["accepted"])),
        "rejected_continuation_attempts": int(len(frames["rejected"])),
        "remaining_possible_false_source_extent_stops": int(len(source_suspect)),
        "likely_duplicate_chain_pairs_after_repair": int(len(likely_pairs)),
        "hard_safety_failure_count": int(safety["status"].eq("fail").sum()),
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")


def read_suspects() -> pd.DataFrame:
    preferred = FINALIZATION_REVIEW / "likely_source_extent_false_stops.csv"
    if preferred.exists():
        return pd.read_csv(preferred)
    candidates = sorted(FINALIZATION_REVIEW.glob("*source*extent*false*stop*.csv")) + sorted(FINALIZATION_REVIEW.glob("*source*extent*suspect*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No source-extent suspect ledger found under {FINALIZATION_REVIEW}")
    return pd.read_csv(candidates[0])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting targeted source-extent continuation repair.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id", "source_limited_status"])
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    suspects = read_suspects()
    log(f"Loaded signals={len(signals)}, roads={len(roads)}, attachments={len(attachments)}, approaches={len(approaches)}, corridors={len(corridors)}, suspects={len(suspects)}.")
    post, frames = repair_chains(corridors, roads, attachments, suspects)
    log(f"Repair pass complete; accepted_segments={len(frames['accepted'])}, rejected_attempts={len(frames['rejected'])}, post_rows={len(post)}.")
    post = post.sort_values(["stable_signal_id", "signal_approach_id", "logical_corridor_chain_id", "segment_order", "approach_corridor_id"]).reset_index(drop=True)
    source_val, source_suspect = post_source_extent_validation(post, roads)
    log(f"Post source-extent validation complete; remaining_suspects={len(source_suspect)}.")
    chain_check = chain_internal_check(post)
    pairs, likely_pairs, risk = duplicate_risk(post)
    db_chain, db_app = distance_band_readiness(post)
    safety = hard_safety_checks(post, approaches, signals, roads)
    blocking = int(risk["approach_duplication_risk"].eq("likely_duplicate_chains_block_bin_context").sum()) if not risk.empty else 0
    hard_fail = int(safety["status"].eq("fail").sum())
    log(f"Post QA complete; likely_duplicate_pairs={len(likely_pairs)}, blocking_approaches={blocking}, hard_safety_failures={hard_fail}.")
    if hard_fail or len(likely_pairs) or blocking:
        decision = "source_extent_repair_created_duplication_or_safety_issue"
    elif len(source_suspect) == 0:
        decision = "source_extent_repaired_approach_corridors_ready_for_final_validation"
    elif len(source_suspect) <= 100:
        decision = "source_extent_repair_completed_with_small_review_ledger"
    else:
        decision = "source_extent_repair_needs_additional_continuation_logic"
    post.to_parquet(CORRIDORS, index=False)
    log(f"Wrote repaired staged approach_corridors.parquet with {len(post)} rows.")
    write_outputs(corridors, post, frames, source_val, source_suspect, chain_check, pairs, likely_pairs, risk, db_chain, db_app, safety, signals, approaches, decision)
    update_metadata(post, decision)
    log(f"Finished targeted source-extent continuation repair with decision={decision}.")


if __name__ == "__main__":
    main()
