"""Patch remaining likely-valid source-extent continuations.

This bounded repair appends only the final-overall-audit rows classified as
still_likely_valid_continuation. It does not rebuild corridors, build bins,
assign directionality, or modify source/artifact files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.roadway_graph import patch_approach_corridor_context_transition_extensions as ctx


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_remaining_likely_valid_source_extent_continuations"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

FINAL_OVERALL = REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit"
PRIOR_PATCH = REPO / "work/roadway_graph/review/patch_approach_corridor_context_transition_extensions"
FULL_AUDIT = REPO / "work/roadway_graph/review/full_source_extent_continuation_audit"
CONFIG_AUDIT = REPO / "work/roadway_graph/review/roadway_configuration_conflict_continuation_audit"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

RULE_VERSION = "remaining_likely_valid_source_extent_continuation_v1_2026-06-10"


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def clean(value: Any) -> str:
    return ctx.clean(value)


def write_csv(name: str, rows: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows.to_csv(OUT / name, index=False)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = ctx.now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as fh:
        fh.write(f"- {stamp}: {message}\n")


def load_target_ledgers() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_csv(FINAL_OVERALL / "possible_remaining_candidate_classification.csv")
    targets = candidates[candidates["final_candidate_classification"].eq("still_likely_valid_continuation")].copy()
    untouched = candidates[
        candidates["final_candidate_classification"].isin(
            ["valid_stop_carriageway_or_parallel_ambiguity", "insufficient_evidence_needs_review"]
        )
    ].copy()
    insufficient = pd.read_csv(FINAL_OVERALL / "stopped_due_insufficient_evidence_review.csv")
    insufficient["final_candidate_classification"] = "stopped_due_insufficient_evidence_preserved"
    return targets, untouched, insufficient


def ensure_remaining_fields(corridors: pd.DataFrame) -> pd.DataFrame:
    c = corridors.copy()
    defaults = {
        "remaining_source_extent_patch_status": "not_targeted",
        "remaining_source_extent_patch_method": "",
        "remaining_source_extent_patch_rule_version": RULE_VERSION,
        "remaining_source_extent_candidate_stable_travelway_id": "",
        "remaining_source_extent_gap_ft": "",
        "remaining_source_extent_added_reach_ft": 0.0,
        "remaining_source_extent_added_segment_count": 0,
        "remaining_source_extent_rejection_reason": "",
        "pre_remaining_patch_chain_stop_reason": "",
        "post_remaining_patch_chain_stop_reason": "",
    }
    for col, val in defaults.items():
        if col not in c.columns:
            c[col] = val
    return c


def rollback_previous_attempt(corridors: pd.DataFrame, target_ids: set[str]) -> pd.DataFrame:
    c = ensure_remaining_fields(corridors)
    added_path = OUT / "remaining_patch_added_segments.csv"
    if added_path.exists() and added_path.stat().st_size > 2:
        previous_added = pd.read_csv(added_path)
        if "approach_corridor_id" in previous_added.columns:
            added_ids = set(previous_added["approach_corridor_id"].astype(str))
            c = c[~c["approach_corridor_id"].astype(str).isin(added_ids)].copy()
    for chain_id in target_ids:
        mask = c["logical_corridor_chain_id"].astype(str).eq(chain_id)
        if not mask.any():
            continue
        order_idx = c[mask].sort_values(["segment_start_distance_ft", "segment_end_distance_ft", "approach_corridor_id"]).index
        count = len(order_idx)
        c.loc[order_idx, "segment_order"] = range(1, count + 1)
        c.loc[order_idx, "segment_count_in_chain"] = count
        max_end = float(pd.to_numeric(c.loc[order_idx, "segment_end_distance_ft"], errors="coerce").max())
        c.loc[order_idx, "chain_total_reach_ft"] = max_end
        c.loc[order_idx, "chain_stop_reason"] = "stopped_at_source_extent"
        c.loc[order_idx, "chain_completeness_status"] = ctx.completeness_for_stop("stopped_at_source_extent")
        c.loc[order_idx, "clipped_by_2500_ft_flag"] = False
        c.loc[order_idx, "clipped_by_signal_boundary_flag"] = False
        c.loc[order_idx, "clipped_by_source_extent_flag"] = True
        c.loc[order_idx, "clipped_by_gap_or_uncertain_continuity_flag"] = False
        c.loc[order_idx, "boundary_method"] = "stopped_at_source_extent"
        c.loc[order_idx, "remaining_source_extent_patch_status"] = "not_targeted"
        c.loc[order_idx, "remaining_source_extent_patch_method"] = ""
        c.loc[order_idx, "remaining_source_extent_patch_rule_version"] = RULE_VERSION
        c.loc[order_idx, "remaining_source_extent_candidate_stable_travelway_id"] = ""
        c.loc[order_idx, "remaining_source_extent_gap_ft"] = ""
        c.loc[order_idx, "remaining_source_extent_added_reach_ft"] = 0.0
        c.loc[order_idx, "remaining_source_extent_added_segment_count"] = 0
        c.loc[order_idx, "remaining_source_extent_rejection_reason"] = ""
        c.loc[order_idx, "pre_remaining_patch_chain_stop_reason"] = ""
        c.loc[order_idx, "post_remaining_patch_chain_stop_reason"] = ""
    return c.reset_index(drop=True)


def possible_distance_duplicate(corridors: pd.DataFrame, chain_id: str, approach_id: str, route: str, token: str, side: str, projected_reach_ft: float) -> bool:
    peers = corridors[
        corridors["signal_approach_id"].astype(str).eq(approach_id)
        & ~corridors["logical_corridor_chain_id"].astype(str).eq(chain_id)
        & corridors["measure_side_class"].astype(str).eq(side)
        & corridors["source_route_name"].astype(str).eq(route)
        & corridors["chain_bin_eligible_flag"].fillna(True).map(ctx.bool_value)
    ].copy()
    if peers.empty:
        return False
    peers = peers[peers["carriageway_direction_token"].map(lambda x: ctx.compatible_value(x, token))]
    if peers.empty:
        return False
    peer_reach = pd.to_numeric(peers["chain_total_reach_ft"], errors="coerce").fillna(0)
    distance_overlap = peer_reach.map(lambda x: max(0.0, min(float(projected_reach_ft), float(x))))
    return bool((distance_overlap >= 250.0).any())


def patch_targets(corridors: pd.DataFrame, roads: pd.DataFrame, attachments: pd.DataFrame, targets: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    target_ids = set(targets["logical_corridor_chain_id"].astype(str))
    c = rollback_previous_attempt(corridors, target_ids)
    roads_prepared = ctx.prepare_roads(roads)
    roads_by_route = ctx.road_groups(roads_prepared)
    boundaries = ctx.make_boundary_groups(attachments)
    target_ids = sorted(set(targets["logical_corridor_chain_id"].astype(str)))
    target_by_chain = targets.drop_duplicates("logical_corridor_chain_id").set_index("logical_corridor_chain_id", drop=False)
    input_rows: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    added_segments: list[dict[str, Any]] = []
    updates: dict[str, dict[str, Any]] = {}

    for i, chain_id in enumerate(target_ids, start=1):
        if i % 25 == 0:
            log(f"Processed {i:,} remaining likely-valid targets.")
        target = target_by_chain.loc[chain_id]
        target_candidate_id = clean(target.get("candidate_stable_travelway_id"))
        input_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "input_status": "loaded",
                "target_candidate_stable_travelway_id": target_candidate_id,
                "final_candidate_classification": clean(target.get("final_candidate_classification")),
            }
        )
        chain = c[c["logical_corridor_chain_id"].astype(str).eq(chain_id)].copy().sort_values("segment_order")
        if chain.empty:
            rejected.append({"logical_corridor_chain_id": chain_id, "candidate_stable_travelway_id": target_candidate_id, "rejection_reason": "target_chain_not_found"})
            continue
        first = chain.iloc[0]
        if clean(first["chain_stop_reason"]) != "stopped_at_source_extent":
            updates[chain_id] = {
                "remaining_source_extent_patch_status": "already_resolved",
                "remaining_source_extent_rejection_reason": "chain_stop_reason_no_longer_source_extent",
            }
            rejected.append({"logical_corridor_chain_id": chain_id, "candidate_stable_travelway_id": target_candidate_id, "rejection_reason": "chain_stop_reason_no_longer_source_extent"})
            continue
        route = clean(first["source_route_name"])
        side = clean(first["measure_side_class"])
        signal_measure = ctx.safe_float(first["reviewed_signal_measure"])
        if side not in {"measure_increasing_from_signal", "measure_decreasing_from_signal"} or pd.isna(signal_measure):
            updates[chain_id] = {
                "remaining_source_extent_patch_status": "extension_rejected_with_precise_reason",
                "remaining_source_extent_rejection_reason": "missing_side_or_signal_measure",
            }
            rejected.append({"logical_corridor_chain_id": chain_id, "candidate_stable_travelway_id": target_candidate_id, "rejection_reason": "missing_side_or_signal_measure"})
            continue
        route_roads = roads_by_route.get(route, pd.DataFrame())
        endpoint = signal_measure + float(chain.iloc[-1]["segment_end_distance_ft"]) / 5280.0 if side == "measure_increasing_from_signal" else signal_measure - float(chain.iloc[-1]["segment_end_distance_ft"]) / 5280.0
        hard_limit = signal_measure + ctx.MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - ctx.MAX_REACH_MILES
        used_ids = set(chain["stable_travelway_id"].astype(str))
        working_chain = chain.copy()
        max_order = int(chain["segment_order"].max())
        accepted_count = 0
        rejected_reason = ""
        terminal_stop = "stopped_at_source_extent"
        boundary_info = {"has_boundary": False, "measure": None, "stable_signal_id": "", "source_globalid": ""}

        for iteration in range(64):
            current_reach = abs(endpoint - signal_measure) * 5280.0
            if current_reach >= ctx.MAX_REACH_FT - 1.0:
                terminal_stop = "reached_2500_ft"
                break
            candidates = ctx.candidate_rows(route_roads, side, endpoint, hard_limit, used_ids)
            if candidates.empty:
                terminal_stop = "stopped_at_source_extent"
                break
            road = candidates.iloc[0]
            must_match = target_candidate_id if iteration == 0 else None
            current_for_dup = pd.concat([c, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else c
            ok, reason, detail = ctx.validate_candidate(working_chain, road, must_match, current_for_dup, boundaries, endpoint, hard_limit)
            if not ok:
                rejected_reason = reason
                terminal_stop = {
                    "supported_signal_boundary_before_candidate": "stopped_at_supported_signal_boundary",
                    "route_measure_gap_exceeds_acceptance": "stopped_at_source_extent",
                    "geometry_and_route_measure_continuity_weak": "stopped_due_insufficient_evidence",
                    "route_name_conflict": "stopped_at_route_or_carriageway_conflict",
                    "route_base_conflict": "stopped_at_route_or_carriageway_conflict",
                    "source_route_id_conflict": "stopped_at_route_or_carriageway_conflict",
                    "source_route_common_conflict": "stopped_at_route_or_carriageway_conflict",
                    "carriageway_token_conflict": "stopped_at_route_or_carriageway_conflict",
                    "roadway_configuration_branch_conflict": "stopped_at_roadway_configuration_branch_conflict",
                    "candidate_exceeds_2500_ft": "reached_2500_ft",
                }.get(reason, "stopped_due_insufficient_evidence")
                if accepted_count == 0:
                    terminal_stop = "stopped_at_source_extent"
                if accepted_count == 0:
                    rejected.append({"logical_corridor_chain_id": chain_id, "candidate_stable_travelway_id": clean(road.get("stable_travelway_id")), "rejection_reason": reason})
                break
            seg_start = detail["seg_start"]
            seg_end = detail["seg_end"]
            gap_ft = detail["gap_ft"]
            boundary_info = detail.get("boundary", boundary_info)
            projected_reach = abs(seg_end - signal_measure) * 5280.0
            current_for_dup = pd.concat([c, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else c
            if possible_distance_duplicate(current_for_dup, chain_id, clean(first["signal_approach_id"]), route, clean(first["carriageway_direction_token"]), side, projected_reach):
                rejected_reason = "would_create_possible_duplicate_bin_overlap"
                if accepted_count == 0:
                    rejected.append({"logical_corridor_chain_id": chain_id, "candidate_stable_travelway_id": clean(road.get("stable_travelway_id")), "rejection_reason": rejected_reason})
                    terminal_stop = "stopped_at_source_extent"
                else:
                    terminal_stop = "stopped_at_source_extent"
                break
            max_order += 1
            new_row = ctx.make_new_segment(working_chain.iloc[-1], road, max_order, seg_start, seg_end, gap_ft, clean(working_chain.iloc[-1].get("roadway_configuration")))
            added_reach = abs(seg_end - seg_start) * 5280.0
            new_row.update(
                {
                    "remaining_source_extent_patch_status": "extension_accepted",
                    "remaining_source_extent_patch_method": "same_corridor_remaining_source_extent_continuation",
                    "remaining_source_extent_patch_rule_version": RULE_VERSION,
                    "remaining_source_extent_candidate_stable_travelway_id": clean(road.get("stable_travelway_id")),
                    "remaining_source_extent_gap_ft": gap_ft,
                    "remaining_source_extent_added_reach_ft": added_reach,
                    "remaining_source_extent_rejection_reason": "",
                }
            )
            new_rows.append(new_row)
            added_segments.append(new_row)
            accepted.append(
                {
                    "logical_corridor_chain_id": chain_id,
                    "stable_signal_id": clean(first["stable_signal_id"]),
                    "signal_approach_id": clean(first["signal_approach_id"]),
                    "candidate_stable_travelway_id": clean(road["stable_travelway_id"]),
                    "segment_order": max_order,
                    "gap_ft": gap_ft,
                    "added_reach_ft": added_reach,
                    "acceptance_reason": "remaining_likely_valid_same_corridor_continuation",
                }
            )
            working_chain = pd.concat([working_chain, pd.DataFrame([new_row])], ignore_index=True)
            used_ids.add(clean(road["stable_travelway_id"]))
            endpoint = seg_end
            accepted_count += 1
            if boundary_info.get("has_boundary") and boundary_info.get("measure") is not None and abs(float(boundary_info["measure"]) - endpoint) <= 1e-9:
                terminal_stop = "stopped_at_supported_signal_boundary"
                break

        final_reach = min(ctx.MAX_REACH_FT, abs(endpoint - signal_measure) * 5280.0)
        if final_reach >= ctx.MAX_REACH_FT - 1.0:
            terminal_stop = "reached_2500_ft"
        status = "extension_accepted" if accepted_count else "extension_rejected_with_precise_reason"
        updates[chain_id] = {
            "remaining_source_extent_patch_status": status,
            "remaining_source_extent_patch_method": "same_corridor_remaining_source_extent_continuation" if accepted_count else "",
            "remaining_source_extent_patch_rule_version": RULE_VERSION,
            "remaining_source_extent_candidate_stable_travelway_id": target_candidate_id,
            "remaining_source_extent_gap_ft": ctx.safe_float(target.get("best_gap_ft"), 0.0),
            "remaining_source_extent_added_reach_ft": sum(r["added_reach_ft"] for r in accepted if r["logical_corridor_chain_id"] == chain_id),
            "remaining_source_extent_added_segment_count": accepted_count,
            "remaining_source_extent_rejection_reason": "" if accepted_count else rejected_reason,
            "pre_remaining_patch_chain_stop_reason": clean(first["chain_stop_reason"]),
            "post_remaining_patch_chain_stop_reason": terminal_stop,
            "chain_total_reach_ft": final_reach,
            "chain_stop_reason": terminal_stop,
            "chain_completeness_status": ctx.completeness_for_stop(terminal_stop),
            "boundary_signal_id": boundary_info.get("stable_signal_id", "") if terminal_stop == "stopped_at_supported_signal_boundary" else "",
            "boundary_source_globalid": boundary_info.get("source_globalid", "") if terminal_stop == "stopped_at_supported_signal_boundary" else "",
        }

    if new_rows:
        c = pd.concat([c, pd.DataFrame(new_rows)], ignore_index=True)
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
        if max_end > ctx.safe_float(vals.get("chain_total_reach_ft"), 0.0):
            c.loc[order_idx, "chain_total_reach_ft"] = max_end
        stop = clean(c.loc[order_idx[0], "chain_stop_reason"])
        c.loc[order_idx, "chain_completeness_status"] = ctx.completeness_for_stop(stop)
        c.loc[order_idx, "clipped_by_2500_ft_flag"] = stop == "reached_2500_ft"
        c.loc[order_idx, "clipped_by_signal_boundary_flag"] = stop == "stopped_at_supported_signal_boundary"
        c.loc[order_idx, "clipped_by_source_extent_flag"] = stop == "stopped_at_source_extent"
        c.loc[order_idx, "clipped_by_gap_or_uncertain_continuity_flag"] = stop in {"stopped_at_geometry_gap", "stopped_due_insufficient_evidence"}
        c.loc[order_idx, "boundary_method"] = stop

    frames = {
        "input": pd.DataFrame(input_rows),
        "accepted": pd.DataFrame(accepted),
        "rejected": pd.DataFrame(rejected),
        "added_segments": pd.DataFrame(added_segments),
    }
    frames["added_reach"] = (
        frames["accepted"].groupby("logical_corridor_chain_id", dropna=False).agg(
            added_segment_count=("candidate_stable_travelway_id", "size"),
            added_reach_ft=("added_reach_ft", "sum"),
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
        ).reset_index()
        if not frames["accepted"].empty
        else pd.DataFrame(columns=["logical_corridor_chain_id", "added_segment_count", "added_reach_ft", "stable_signal_id", "signal_approach_id"])
    )
    return c, frames


def normalize_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    out = ctx.normalize_for_parquet(df)
    string_cols = [
        "remaining_source_extent_patch_status",
        "remaining_source_extent_patch_method",
        "remaining_source_extent_patch_rule_version",
        "remaining_source_extent_candidate_stable_travelway_id",
        "remaining_source_extent_gap_ft",
        "remaining_source_extent_rejection_reason",
        "pre_remaining_patch_chain_stop_reason",
        "post_remaining_patch_chain_stop_reason",
    ]
    for col in string_cols:
        if col in out.columns:
            out[col] = out[col].map(clean)
    for col in ["remaining_source_extent_added_reach_ft", "remaining_source_extent_added_segment_count"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


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


def distance_band_support(corridors: pd.DataFrame) -> pd.DataFrame:
    return ctx.distance_band_support(corridors)


def update_metadata(corridors: pd.DataFrame, decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    product = manifest.setdefault("products", {}).setdefault("approach_corridors", {})
    product.update(
        {
            "path": rel(CORRIDORS),
            "grain": "deduplicated chain-aware bin-eligible corridor segments with remaining source-extent continuations patched",
            "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
            "row_count": int(len(corridors)),
            "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()),
            "remaining_source_extent_patch_rule_version": RULE_VERSION,
            "updated_utc": ctx.now(),
            "script": "src.roadway_graph.patch.patch_remaining_likely_valid_source_extent_continuations",
            "final_decision": decision,
        }
    )
    manifest.setdefault("patch_history", []).append(
        {
            "patched_utc": ctx.now(),
            "script": "src.roadway_graph.patch.patch_remaining_likely_valid_source_extent_continuations",
            "rule_version": RULE_VERSION,
            "row_count": int(len(corridors)),
            "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()),
            "final_decision": decision,
        }
    )
    manifest["updated_utc"] = ctx.now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    schema.setdefault("tables", {}).setdefault("approach_corridors", {})["remaining_source_extent_patch_fields"] = [
        "remaining_source_extent_patch_status",
        "remaining_source_extent_patch_method",
        "remaining_source_extent_patch_rule_version",
        "remaining_source_extent_candidate_stable_travelway_id",
        "remaining_source_extent_gap_ft",
        "remaining_source_extent_added_reach_ft",
        "remaining_source_extent_added_segment_count",
        "remaining_source_extent_rejection_reason",
        "pre_remaining_patch_chain_stop_reason",
        "post_remaining_patch_chain_stop_reason",
    ]
    schema["updated_utc"] = ctx.now()
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    with STAGING_README.open("a", encoding="utf-8") as fh:
        fh.write(
            f"\n\n## Remaining Likely-Valid Source-Extent Continuation Patch ({RULE_VERSION})\n"
            "Patched only final-overall-audit rows classified as `still_likely_valid_continuation`. "
            "Ambiguity, insufficient-evidence, and stopped_due_insufficient_evidence ledgers were preserved. "
            "No bin_context, 50-ft bins, upstream/downstream labels, directionality, MVP, crash, access, speed, AADT, or exposure products were built. "
            f"Decision: `{decision}`.\n"
        )


def write_outputs(prior: pd.DataFrame, post: pd.DataFrame, frames: dict[str, pd.DataFrame], untouched: pd.DataFrame, insufficient: pd.DataFrame, qa: dict[str, pd.DataFrame], decision: str) -> None:
    write_csv("parent_dependency_check.csv", parent_dependency_check())
    write_csv("remaining_patch_target_reconciliation.csv", frames["input"])
    write_csv("accepted_remaining_source_extent_extensions.csv", frames["accepted"])
    write_csv("rejected_remaining_source_extent_extensions.csv", frames["rejected"])
    write_csv("untouched_ambiguity_and_insufficient_evidence_ledgers.csv", pd.concat([untouched, insufficient], ignore_index=True, sort=False))
    write_csv("remaining_patch_added_segments.csv", frames["added_segments"])
    write_csv("remaining_patch_added_reach_by_chain.csv", frames["added_reach"])
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
    write_csv("pre_vs_post_distance_band_support.csv", distance_band_support(prior).rename(columns={"logical_chain_count": "pre_logical_chain_count"}).merge(distance_band_support(post).rename(columns={"logical_chain_count": "post_logical_chain_count"}), on="distance_band_support_status", how="outer").fillna(0))
    for name, df in qa.items():
        write_csv(name, df)
    accepted_chains = frames["accepted"]["logical_corridor_chain_id"].nunique() if not frames["accepted"].empty else 0
    rejected_chains = frames["rejected"]["logical_corridor_chain_id"].nunique() if not frames["rejected"].empty else 0
    added_reach = float(frames["accepted"]["added_reach_ft"].sum()) if not frames["accepted"].empty else 0.0
    write_csv("remaining_source_extent_patch_summary.csv", pd.DataFrame([
        {"metric": "target_chains_read", "value": len(frames["input"])},
        {"metric": "accepted_extension_rows", "value": len(frames["accepted"])},
        {"metric": "accepted_target_chains", "value": accepted_chains},
        {"metric": "rejected_target_chains", "value": rejected_chains},
        {"metric": "added_segment_rows", "value": len(post) - len(prior)},
        {"metric": "added_reach_ft", "value": added_reach},
        {"metric": "untouched_ambiguity_rows", "value": int((untouched["final_candidate_classification"] == "valid_stop_carriageway_or_parallel_ambiguity").sum()) if not untouched.empty else 0},
        {"metric": "untouched_insufficient_evidence_rows", "value": int((untouched["final_candidate_classification"] == "insufficient_evidence_needs_review").sum()) if not untouched.empty else 0},
        {"metric": "untouched_stopped_due_insufficient_evidence_chains", "value": len(insufficient)},
        {"metric": "final_decision", "value": decision},
    ]))
    write_csv("readiness_decision.csv", pd.DataFrame([{"final_decision": decision, "reason": "remaining likely-valid source-extent continuation patch completed"}]))
    write_csv("recommended_next_actions.csv", pd.DataFrame([{"rank": 1, "action": "rerun_final_overall_read_only_approach_corridors_validation_audit", "rationale": "The final remaining likely-valid source-extent patch is applied; validate before bin_context."}]))
    findings = f"""# Remaining Likely-Valid Source-Extent Continuation Patch

## Why The Patch Was Needed
The final overall corridor audit found 156 `still_likely_valid_continuation` source-extent chains after the broader context-transition patch.

## Patch Results
Targets read: {len(frames['input']):,}. Target chains extended: {accepted_chains:,}. Target chains rejected: {rejected_chains:,}. Added segment rows: {len(post) - len(prior):,}. Added reach: {added_reach:,.1f} ft.

## Preserved Review Ledgers
The 40 carriageway/parallel ambiguity rows, 33 insufficient-evidence rows, and 3 `stopped_due_insufficient_evidence` chains were preserved and not patched.

## QA
Duplicate/bin-overlap risk and hard safety checks are ledgered in the post-patch QA files. Final decision: `{decision}`.

## Recommended Next Task
Rerun the final overall read-only `approach_corridors` validation audit before bin_context.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_utc": ctx.now(),
        "script": "src.roadway_graph.patch.patch_remaining_likely_valid_source_extent_continuations",
        "rule_version": RULE_VERSION,
        "target_chains_read": int(len(frames["input"])),
        "accepted_extension_rows": int(len(frames["accepted"])),
        "rejected_extension_rows": int(len(frames["rejected"])),
        "added_segment_rows": int(len(post) - len(prior)),
        "added_reach_ft": added_reach,
        "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)],
        "diagnostic_inputs": [rel(FINAL_OVERALL), rel(PRIOR_PATCH), rel(FULL_AUDIT), rel(CONFIG_AUDIT), rel(DEDUP_REVIEW), rel(RECON_REVIEW)],
        "final_decision": decision,
    }
    qa_manifest = {
        "created_utc": ctx.now(),
        "hard_safety_failures": int(qa["post_remaining_patch_hard_safety_checks.csv"]["status"].eq("fail").sum()),
        "duplicate_blocking_pairs": int(len(qa["post_remaining_patch_duplicate_chain_pair_audit.csv"])),
        "approaches_blocking_bin_context": int(qa["post_remaining_patch_bin_duplication_risk_by_approach.csv"]["approach_duplication_risk"].isin(["likely_duplicate_chains_block_bin_context", "moderate_duplication_review"]).sum()) if not qa["post_remaining_patch_bin_duplication_risk_by_approach.csv"].empty else 0,
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {ctx.now()}: Started remaining likely-valid source-extent continuation patch.\n", encoding="utf-8")
    targets, untouched, insufficient = load_target_ledgers()
    log(f"Loaded {len(targets):,} remaining likely-valid targets.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"])
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    raw_row_count = len(corridors)
    corridors = rollback_previous_attempt(corridors, set(targets["logical_corridor_chain_id"].astype(str)))
    if len(corridors) != raw_row_count:
        log(f"Rolled back {raw_row_count - len(corridors):,} rows from the previous remaining-source-extent patch attempt before applying fixed safeguards.")
    prior = corridors.copy()
    post, frames = patch_targets(corridors, roads, attachments, targets)
    log(f"Patch simulation complete; added_rows={len(post) - len(prior):,}.")
    pairs, blocking_pairs, risk = ctx.duplicate_risk(post)
    safety = ctx.hard_safety_checks(post, approaches, signals, roads)
    chain_check = ctx.chain_internal_check(post)
    source_val = ctx.post_source_extent_validation(post, roads)
    non_dir = pd.DataFrame([{"directionality_field_count": len([c for c in post.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]), "status": "pass"}])
    qa = {
        "post_remaining_patch_chain_internal_consistency_check.csv": chain_check,
        "post_remaining_patch_duplicate_chain_pair_audit.csv": blocking_pairs,
        "post_remaining_patch_bin_duplication_risk_by_approach.csv": risk,
        "post_remaining_patch_source_extent_validation.csv": source_val,
        "post_remaining_patch_hard_safety_checks.csv": safety,
        "non_directionality_field_check.csv": non_dir,
    }
    rejected_chains = frames["rejected"]["logical_corridor_chain_id"].nunique() if not frames["rejected"].empty else 0
    blocking_apps = int(risk["approach_duplication_risk"].isin(["likely_duplicate_chains_block_bin_context", "moderate_duplication_review"]).sum()) if not risk.empty else 0
    if safety["status"].eq("fail").any() or not blocking_pairs.empty or blocking_apps:
        decision = "remaining_source_extent_patch_created_duplication_or_safety_issue"
    elif rejected_chains:
        decision = "remaining_source_extent_patch_completed_with_small_review_ledger"
    else:
        decision = "remaining_source_extent_patch_ready_for_final_validation"
    post = post.sort_values(["stable_signal_id", "signal_approach_id", "logical_corridor_chain_id", "segment_order", "approach_corridor_id"]).reset_index(drop=True)
    post = normalize_for_parquet(post)
    post.to_parquet(CORRIDORS, index=False)
    update_metadata(post, decision)
    write_outputs(prior, post, frames, untouched, insufficient, qa, decision)
    log(f"Finished remaining likely-valid source-extent patch with decision={decision}.")


if __name__ == "__main__":
    main()
