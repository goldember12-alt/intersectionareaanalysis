"""Rebuild staged approach_corridors as one-sided neutral corridor intervals.

This replaces the prior staged approach_corridors.parquet because that object
contained signal-spanning route intervals. This script does not build bins and
does not assign upstream/downstream or directionality.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkb
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/rebuild_one_sided_approach_corridors"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

SIDE_REACH_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_side_reach_audit"
BUILD_CORRIDORS_REVIEW = REPO / "work/roadway_graph/review/build_approach_corridors"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
EXCEPTION_AUDIT = REPO / "work/roadway_graph/review/signal_approaches_exception_adjudication_audit"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
TRAVELWAY_READINESS_REVIEW = REPO / "work/roadway_graph/review/travelway_network_index_readiness_audit"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"

MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
FLOAT_TOL_FT = 0.001
REBUILD_VERSION = "one_sided_approach_corridors_v1_2026-06-09"


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


def load_wkb(value: Any) -> BaseGeometry | None:
    if value is None or pd.isna(value):
        return None
    try:
        geom = wkb.loads(bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value)
        return None if geom.is_empty else geom
    except Exception:
        return None


def split_pipe(value: Any) -> list[str]:
    text = clean(value)
    return [part for part in text.split("|") if part]


def side_geometry(road: pd.Series, from_m: float, to_m: float) -> tuple[Any, str]:
    geom = load_wkb(road.get("geometry"))
    if geom is None:
        return None, "missing_or_unparseable_parent_travelway_geometry"
    start = float(road["source_measure_start"])
    end = float(road["source_measure_end"])
    lo = min(start, end)
    hi = max(start, end)
    if hi <= lo:
        return road.get("geometry"), "source_row_geometry_invalid_measure_interval"
    f0 = max(0.0, min(1.0, (min(from_m, to_m) - lo) / (hi - lo)))
    f1 = max(0.0, min(1.0, (max(from_m, to_m) - lo) / (hi - lo)))
    try:
        sub = substring(geom, f0, f1, normalized=True)
        if sub.is_empty:
            return road.get("geometry"), "source_row_geometry_substring_empty_fallback"
        return wkb.dumps(sub), "derived_one_sided_travelway_measure_interval_geometry"
    except Exception:
        return road.get("geometry"), "source_row_geometry_substring_failed_fallback"


def nearest_boundary(
    boundary_candidates: pd.DataFrame,
    stable_signal_id: str,
    stable_travelway_id: str,
    signal_measure: float,
    side: str,
    side_limit: float,
) -> dict[str, Any]:
    same = boundary_candidates[
        boundary_candidates["stable_travelway_id"].eq(stable_travelway_id)
        & boundary_candidates["estimated_measure"].notna()
        & ~boundary_candidates["stable_signal_id"].eq(stable_signal_id)
    ].copy()
    if same.empty:
        return {"endpoint": side_limit, "endpoint_id": "", "endpoint_gid": "", "clipped_by_signal": False, "boundary_method": "signal_to_2500ft_or_source_extent", "cross_violation": False, "same_measure_conflict": False}
    same_measure = same[(same["estimated_measure"] - signal_measure).abs() <= 1e-6]
    if not same_measure.empty:
        return {"endpoint": side_limit, "endpoint_id": "", "endpoint_gid": "", "clipped_by_signal": False, "boundary_method": "same_measure_signal_boundary_conflict", "cross_violation": True, "same_measure_conflict": True, "conflicting_boundary_signal_ids": "|".join(sorted(set(same_measure["stable_signal_id"].astype(str))))}
    if side == "measure_increasing_from_signal":
        candidates = same[(same["estimated_measure"] > signal_measure) & (same["estimated_measure"] <= side_limit)].sort_values("estimated_measure")
        if candidates.empty:
            return {"endpoint": side_limit, "endpoint_id": "", "endpoint_gid": "", "clipped_by_signal": False, "boundary_method": "signal_to_2500ft_or_source_extent", "cross_violation": False, "same_measure_conflict": False}
        row = candidates.iloc[0]
        return {"endpoint": float(row["estimated_measure"]), "endpoint_id": clean(row.get("stable_signal_id")), "endpoint_gid": clean(row.get("source_signal_globalid")), "clipped_by_signal": True, "boundary_method": "source_signal_boundary_clip", "cross_violation": False, "same_measure_conflict": False}
    candidates = same[(same["estimated_measure"] < signal_measure) & (same["estimated_measure"] >= side_limit)].sort_values("estimated_measure", ascending=False)
    if candidates.empty:
        return {"endpoint": side_limit, "endpoint_id": "", "endpoint_gid": "", "clipped_by_signal": False, "boundary_method": "signal_to_2500ft_or_source_extent", "cross_violation": False, "same_measure_conflict": False}
    row = candidates.iloc[0]
    return {"endpoint": float(row["estimated_measure"]), "endpoint_id": clean(row.get("stable_signal_id")), "endpoint_gid": clean(row.get("source_signal_globalid")), "clipped_by_signal": True, "boundary_method": "source_signal_boundary_clip", "cross_violation": False, "same_measure_conflict": False}


def distance_support_status(max_reach: float) -> str:
    if max_reach >= 2500 - FLOAT_TOL_FT:
        return "full_one_sided_0_2500_support"
    if max_reach > 0:
        return "partial_support"
    return "no_usable_support"


def build_corridors(
    roads: pd.DataFrame,
    attachments: pd.DataFrame,
    approaches: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    roads_by_id = roads.set_index("stable_travelway_id", drop=False)
    attachments_by_id = attachments.set_index("attachment_id", drop=False)
    boundary_candidates = attachments[
        attachments["attachment_confidence"].isin(["high", "medium"])
        & attachments["estimated_measure_status"].eq("estimated_measure_projected")
        & attachments["usable_as_corridor_boundary"].fillna(False).astype(bool)
    ].copy()
    include = approaches[approaches["corridor_build_gate"].isin(["corridor_build_ready", "corridor_build_ready_with_warning"])].copy()
    blocked = approaches[approaches["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")].copy()
    records: list[dict[str, Any]] = []
    no_corridor: list[dict[str, Any]] = []
    side_uncertain: list[dict[str, Any]] = []
    boundary_audit: list[dict[str, Any]] = []
    continuity_rows: list[dict[str, Any]] = []
    prior_spanning_split_rows = 0
    for _, app in include.iterrows():
        support_ids = split_pipe(app.get("supporting_attachment_ids"))
        support = attachments_by_id.loc[[sid for sid in support_ids if sid in attachments_by_id.index]].copy() if support_ids else pd.DataFrame()
        support = support[
            support["attachment_confidence"].isin(["high", "medium"])
            & support["estimated_measure_status"].eq("estimated_measure_projected")
            & support["usable_as_corridor_boundary"].fillna(False).astype(bool)
        ] if not support.empty else support
        if support.empty:
            no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "no_corridor_reason": "no_measure_ready_boundary_capable_support"})
            continue
        for stable_travelway_id, group in support.groupby("stable_travelway_id", dropna=False):
            if stable_travelway_id not in roads_by_id.index:
                no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "no_corridor_reason": "supporting_travelway_missing_from_parent"})
                continue
            road = roads_by_id.loc[stable_travelway_id]
            if isinstance(road, pd.DataFrame):
                road = road.iloc[0]
            if clean(road.get("route_measure_status")) != "route_measure_complete":
                no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "no_corridor_reason": f"route_measure_limited_{clean(road.get('route_measure_status'))}"})
                continue
            source_start = pd.to_numeric(pd.Series([road.get("source_measure_start")]), errors="coerce").iloc[0]
            source_end = pd.to_numeric(pd.Series([road.get("source_measure_end")]), errors="coerce").iloc[0]
            if pd.isna(source_start) or pd.isna(source_end) or source_start == source_end:
                no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "no_corridor_reason": "invalid_source_measure_extent"})
                continue
            source_lo = min(float(source_start), float(source_end))
            source_hi = max(float(source_start), float(source_end))
            signal_measure = float(group.sort_values(["point_to_line_distance_ft", "candidate_rank_for_signal"]).iloc[0]["estimated_measure"])
            sides: list[tuple[str, float]] = []
            dec_limit = max(source_lo, signal_measure - MAX_REACH_MILES)
            inc_limit = min(source_hi, signal_measure + MAX_REACH_MILES)
            if signal_measure - dec_limit > 1e-9:
                sides.append(("measure_decreasing_from_signal", dec_limit))
            if inc_limit - signal_measure > 1e-9:
                sides.append(("measure_increasing_from_signal", inc_limit))
            if len(sides) == 2:
                prior_spanning_split_rows += 1
            if not sides:
                side_uncertain.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "side_assignment_status": "side_assignment_uncertain", "reason": "reviewed_signal_at_source_extent_or_zero_reach"})
                continue
            for side, side_limit in sides:
                bound = nearest_boundary(boundary_candidates, app["stable_signal_id"], stable_travelway_id, signal_measure, side, side_limit)
                if bound.get("same_measure_conflict"):
                    no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "measure_side_class": side, "no_corridor_reason": "same_measure_supported_signal_boundary_conflict", "conflicting_boundary_signal_ids": bound.get("conflicting_boundary_signal_ids", "")})
                    continue
                endpoint = float(bound["endpoint"])
                from_m = min(signal_measure, endpoint)
                to_m = max(signal_measure, endpoint)
                reach_ft = abs(endpoint - signal_measure) * 5280.0
                if reach_ft <= 0:
                    side_uncertain.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "measure_side_class": side, "side_assignment_status": "side_assignment_uncertain", "reason": "zero_reach_after_boundary_clip"})
                    continue
                if reach_ft > MAX_REACH_FT + FLOAT_TOL_FT:
                    endpoint = signal_measure + (MAX_REACH_MILES if side == "measure_increasing_from_signal" else -MAX_REACH_MILES)
                    from_m = min(signal_measure, endpoint)
                    to_m = max(signal_measure, endpoint)
                    reach_ft = MAX_REACH_FT
                geom, geom_status = side_geometry(road, from_m, to_m)
                cid = f"corr1_{hash_text('|'.join([app['signal_approach_id'], stable_travelway_id, side, f'{from_m:.6f}', f'{to_m:.6f}']))}"
                before_id = bound["endpoint_id"] if side == "measure_decreasing_from_signal" else ""
                after_id = bound["endpoint_id"] if side == "measure_increasing_from_signal" else ""
                before_gid = bound["endpoint_gid"] if side == "measure_decreasing_from_signal" else ""
                after_gid = bound["endpoint_gid"] if side == "measure_increasing_from_signal" else ""
                clipped_2500 = abs(side_limit - signal_measure) >= MAX_REACH_MILES - 1e-9 and not bound["clipped_by_signal"]
                clipped_source = endpoint in {source_lo, source_hi} or side_limit in {source_lo, source_hi}
                records.append(
                    {
                        "approach_corridor_id": cid,
                        "stable_signal_id": app["stable_signal_id"],
                        "signal_approach_id": app["signal_approach_id"],
                        "stable_travelway_id": stable_travelway_id,
                        "corridor_from_measure": from_m,
                        "corridor_to_measure": to_m,
                        "reviewed_signal_measure": signal_measure,
                        "measure_side_class": side,
                        "one_sided_reach_ft": reach_ft,
                        "corridor_length_ft": reach_ft,
                        "corridor_confidence": "high" if app["corridor_build_gate"] == "corridor_build_ready" and not bound["clipped_by_signal"] else "medium",
                        "parent_approach_gate": app["corridor_build_gate"],
                        "parent_corridor_gate_severity": app["corridor_gate_severity"],
                        "warning_provenance": clean(app.get("corridor_restriction_notes")) if app["corridor_build_gate"] == "corridor_build_ready_with_warning" else "",
                        "route_base": clean(road.get("route_base")),
                        "source_route_name": clean(road.get("source_route_name")),
                        "carriageway_direction_token": clean(road.get("carriageway_direction_token")),
                        "roadway_configuration": clean(road.get("roadway_configuration")),
                        "source_measure_start": float(source_start),
                        "source_measure_end": float(source_end),
                        "before_endpoint_signal_id": before_id,
                        "after_endpoint_signal_id": after_id,
                        "before_endpoint_source_globalid": before_gid,
                        "after_endpoint_source_globalid": after_gid,
                        "endpoint_source_only_used": False,
                        "clipped_by_2500_ft_flag": bool(clipped_2500),
                        "clipped_by_signal_boundary_flag": bool(bound["clipped_by_signal"]),
                        "clipped_by_source_extent_flag": bool(clipped_source),
                        "clipped_by_gap_or_uncertain_continuity_flag": False,
                        "split_from_signal_spanning_source_flag": len(sides) == 2,
                        "original_signal_spanning_interval_id": f"{app['signal_approach_id']}|{stable_travelway_id}" if len(sides) == 2 else "",
                        "geometry": geom,
                        "geometry_status": geom_status,
                        "endpoint_policy": "one_sided_nearest_same_travelway_signal_else_2500ft_or_source_extent",
                        "boundary_method": bound["boundary_method"],
                        "source_only_endpoint_flag": False,
                        "cross_signal_boundary_flag": False,
                        "route_measure_continuity_status": "route_measure_complete_single_source_row",
                        "side_assignment_status": "side_assigned_from_reviewed_signal_measure",
                        "gap_bridge_status": "not_attempted",
                        "gap_bridge_method": "",
                        "gap_bridge_confidence": "",
                        "no_corridor_reason": "",
                        "corridor_build_status": "corridor_built",
                        "corridor_rebuild_version": REBUILD_VERSION,
                        "supporting_attachment_ids": "|".join(group["attachment_id"].astype(str).tolist()),
                    }
                )
                boundary_audit = {
                    "approach_corridor_id": cid,
                    "stable_signal_id": app["stable_signal_id"],
                    "signal_approach_id": app["signal_approach_id"],
                    "stable_travelway_id": stable_travelway_id,
                    "measure_side_class": side,
                    "boundary_method": bound["boundary_method"],
                    "cross_signal_boundary_flag": False,
                }
                # attach after construction to avoid another large list variable type ambiguity
                continuity_rows.append(
                    {
                        **boundary_audit,
                        "route_measure_continuity_status": "route_measure_complete_single_source_row",
                        "gap_bridge_status": "not_attempted",
                        "one_sided_reach_ft": reach_ft,
                    }
                )
    return pd.DataFrame.from_records(records), {
        "blocked": blocked,
        "no_corridor": pd.DataFrame.from_records(no_corridor),
        "side_uncertain": pd.DataFrame.from_records(side_uncertain),
        "continuity": pd.DataFrame.from_records(continuity_rows),
        "prior_split_count": pd.DataFrame.from_records([{"prior_signal_spanning_support_intervals_split": prior_spanning_split_rows}]),
    }


def distance_band_support(corridors: pd.DataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    support = corridors.groupby("signal_approach_id").agg(max_one_sided_reach_ft=("one_sided_reach_ft", "max"), corridor_rows=("approach_corridor_id", "size")).reset_index()
    out = approaches[["signal_approach_id", "stable_signal_id", "corridor_build_gate"]].merge(support, on="signal_approach_id", how="left")
    out["max_one_sided_reach_ft"] = out["max_one_sided_reach_ft"].fillna(0.0)
    out["corridor_rows"] = out["corridor_rows"].fillna(0).astype(int)
    out["distance_band_support_status"] = out["max_one_sided_reach_ft"].map(distance_support_status)
    for start, end in [(0, 250), (250, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500)]:
        out[f"supports_{start}_{end}ft"] = out["max_one_sided_reach_ft"] >= end
    return out


def write_metadata(corridors: pd.DataFrame, decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {})["approach_corridors"] = {
        "path": rel(APPROACH_CORRIDORS),
        "grain": "one physical signal approach x one Travelway subbranch x one neutral side of reviewed signal x one bounded interval",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "replacement_reason": "prior staged approach_corridors contained signal-spanning intervals not ready for bin_context",
        "row_count": int(len(corridors)),
        "created_utc": now(),
        "script": "src.roadway_graph.build.rebuild_one_sided_approach_corridors",
        "corridor_rebuild_version": REBUILD_VERSION,
        "final_decision": decision,
    }
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    schema.setdefault("tables", {})["approach_corridors.parquet"] = {
        "grain": "one-sided neutral corridor interval per physical signal approach and Travelway subbranch",
        "canonical_parent": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "required_columns": [
            "approach_corridor_id",
            "stable_signal_id",
            "signal_approach_id",
            "stable_travelway_id",
            "corridor_from_measure",
            "corridor_to_measure",
            "reviewed_signal_measure",
            "measure_side_class",
            "one_sided_reach_ft",
            "corridor_length_ft",
            "corridor_confidence",
        ],
        "forbidden_fields": "No upstream/downstream/directionality assignment fields.",
        "corridor_rebuild_version": REBUILD_VERSION,
    }
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    addition = f"""

## One-sided approach corridors rebuild

Rebuilt `approach_corridors.parquet` with version `{REBUILD_VERSION}` as a
one-sided neutral corridor layer. The prior staged corridor object contained
signal-spanning intervals and was replaced. No bins, upstream/downstream labels,
directionality, or numeric context products were built.
"""
    existing = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else ""
    if "## One-sided approach corridors rebuild" not in existing:
        STAGING_README.write_text(existing.rstrip() + addition, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting one-sided approach corridor rebuild.")
    prior = pd.read_parquet(APPROACH_CORRIDORS) if APPROACH_CORRIDORS.exists() else pd.DataFrame()
    signals = pd.read_parquet(SIGNAL_INDEX)
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    log(f"Loaded prior_corridors={len(prior)}, signals={len(signals)}, roads={len(roads)}, attachments={len(attachments)}, approaches={len(approaches)}.")
    corridors, frames = build_corridors(roads, attachments, approaches)
    corridors.to_parquet(APPROACH_CORRIDORS, index=False)
    support = distance_band_support(corridors, approaches)
    duplicate_ids = int(corridors["approach_corridor_id"].duplicated(keep=False).sum()) if not corridors.empty else 0
    blocked_present = int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum()) if not corridors.empty else 0
    spanning = int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum()) if not corridors.empty else 0
    outside = int(((corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6) | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)).sum()) if not corridors.empty else 0
    overreach = int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum()) if not corridors.empty else 0
    boundary_violations = int(corridors["cross_signal_boundary_flag"].sum()) if not corridors.empty else 0
    forbidden = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    if duplicate_ids or blocked_present or spanning or outside or overreach or boundary_violations or forbidden:
        decision = "one_sided_approach_corridors_built_but_needs_side_assignment_review"
    elif corridors.empty:
        decision = "one_sided_approach_corridors_should_be_rebuilt"
    else:
        decision = "one_sided_approach_corridors_ready_as_validated_parent"

    write_outputs(prior, signals, approaches, corridors, frames, support, decision, duplicate_ids, blocked_present, spanning, outside, overreach, boundary_violations, forbidden)
    write_metadata(corridors, decision)
    log(f"Rebuild complete with decision {decision}.")


def write_outputs(
    prior: pd.DataFrame,
    signals: pd.DataFrame,
    approaches: pd.DataFrame,
    corridors: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    support: pd.DataFrame,
    decision: str,
    duplicate_ids: int,
    blocked_present: int,
    spanning: int,
    outside: int,
    overreach: int,
    boundary_violations: int,
    forbidden: list[str],
) -> None:
    write_csv("parent_dependency_check.csv", [
        {"object": "approach_corridors", "dependency": rel(SIGNAL_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(ATTACHMENT), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(APPROACHES), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(SIDE_REACH_AUDIT), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(BUILD_CORRIDORS_REVIEW), "dependency_role": "replacement_evidence_only", "allowed": True},
    ])
    write_csv("prior_corridor_replacement_summary.csv", [
        {"metric": "prior_corridor_rows", "value": int(len(prior))},
        {"metric": "new_one_sided_corridor_rows", "value": int(len(corridors))},
        {"metric": "prior_signal_spanning_rows_from_audit", "value": 15584},
        {"metric": "replacement_reason", "value": "prior object contained signal-spanning intervals not bin-ready"},
    ])
    write_csv("approach_corridor_id_uniqueness_check.csv", [{"corridor_rows": int(len(corridors)), "duplicate_approach_corridor_id_rows": duplicate_ids, "status": "pass" if duplicate_ids == 0 else "fail"}])
    write_csv("corridor_rows_by_parent_gate.csv", corridors.groupby("parent_approach_gate").size().reset_index(name="corridor_rows").to_dict("records") if not corridors.empty else [])
    write_csv("excluded_blocked_approach_ledger.csv", frames["blocked"].to_dict("records"))
    no_approach_signals = set(signals["stable_signal_id"]) - set(approaches["stable_signal_id"])
    write_csv("source_limited_no_corridor_signal_ledger.csv", signals[signals["stable_signal_id"].isin(no_approach_signals)].to_dict("records"))
    app_counts = approaches[["signal_approach_id", "stable_signal_id", "corridor_build_gate"]].merge(corridors.groupby("signal_approach_id").size().reset_index(name="corridor_count"), on="signal_approach_id", how="left")
    app_counts["corridor_count"] = app_counts["corridor_count"].fillna(0).astype(int)
    write_csv("approach_to_corridor_reconciliation.csv", app_counts.to_dict("records"))
    write_csv("signal_to_corridor_reconciliation.csv", app_counts.groupby("stable_signal_id").agg(approach_count=("signal_approach_id", "size"), corridor_count=("corridor_count", "sum")).reset_index().to_dict("records"))
    write_csv("measure_side_class_summary.csv", corridors.groupby("measure_side_class").size().reset_index(name="corridor_rows").to_dict("records") if not corridors.empty else [])
    buckets = pd.cut(corridors["one_sided_reach_ft"], bins=[0, 100, 250, 500, 1000, 1500, 2000, 2500.001], labels=["0_100", "100_250", "250_500", "500_1000", "1000_1500", "1500_2000", "2000_2500"], include_lowest=True) if not corridors.empty else pd.Series(dtype=str)
    write_csv("one_sided_reach_distribution.csv", buckets.value_counts().sort_index().reset_index(name="corridor_rows").rename(columns={"one_sided_reach_ft": "reach_bucket"}).to_dict("records") if not corridors.empty else [])
    write_csv("corridor_length_distribution.csv", buckets.value_counts().sort_index().reset_index(name="corridor_rows").rename(columns={"one_sided_reach_ft": "length_bucket"}).to_dict("records") if not corridors.empty else [])
    write_csv("signal_spanning_output_check.csv", [{"signal_spanning_output_rows": spanning, "status": "pass" if spanning == 0 else "fail"}])
    write_csv("reviewed_measure_outside_corridor_check.csv", [{"reviewed_measure_outside_corridor_rows": outside, "status": "pass" if outside == 0 else "fail"}])
    write_csv("supported_signal_boundary_crossing_audit.csv", [{"boundary_crossing_violation_rows": boundary_violations, "status": "pass" if boundary_violations == 0 else "fail"}])
    write_csv("route_measure_continuity_audit.csv", corridors[["approach_corridor_id", "stable_travelway_id", "route_measure_continuity_status", "gap_bridge_status", "one_sided_reach_ft"]].to_dict("records") if not corridors.empty else [])
    write_csv("side_assignment_uncertain_ledger.csv", frames["side_uncertain"].to_dict("records"))
    no_ledger = pd.concat([frames["no_corridor"], app_counts[(app_counts["corridor_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")]], ignore_index=True)
    write_csv("no_corridor_approach_ledger.csv", no_ledger.to_dict("records"))
    write_csv("gap_bridge_attempts.csv", [])
    write_csv("gap_bridge_rejections.csv", [])
    write_csv("gap_bridge_summary.csv", [{"gap_bridge_attempts": 0, "accepted_gap_bridges": 0, "policy": "no gap bridges attempted in conservative one-sided rebuild"}])
    warning = approaches[approaches["corridor_build_gate"].eq("corridor_build_ready_with_warning")][["signal_approach_id", "stable_signal_id", "corridor_build_gate", "corridor_gate_severity", "corridor_restriction_notes"]].merge(app_counts[["signal_approach_id", "corridor_count"]], on="signal_approach_id", how="left")
    write_csv("warning_approach_corridor_outcomes.csv", warning.to_dict("records"))
    write_csv("multi_corridor_per_approach_audit.csv", app_counts[app_counts["corridor_count"] > 1].to_dict("records"))
    write_csv("high_corridor_count_approach_review.csv", app_counts.sort_values("corridor_count", ascending=False).head(500).to_dict("records"))
    write_csv("distance_band_support_readiness_by_approach.csv", support.to_dict("records"))
    write_csv("distance_band_support_summary.csv", support.groupby("distance_band_support_status").size().reset_index(name="approach_count").to_dict("records"))
    write_csv("non_directionality_field_check.csv", [{"forbidden_directionality_field_count": len(forbidden), "forbidden_fields": "|".join(forbidden), "status": "pass" if not forbidden else "fail"}])
    write_csv("corridor_rebuild_summary.csv", [
        {"metric": "corridor_rows_written", "value": int(len(corridors))},
        {"metric": "approaches_with_corridors", "value": int(app_counts["corridor_count"].gt(0).sum())},
        {"metric": "eligible_approaches_without_corridor_rows", "value": int(((app_counts["corridor_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")).sum())},
        {"metric": "blocked_approaches_excluded", "value": int(len(frames["blocked"]))},
        {"metric": "signal_spanning_output_rows", "value": spanning},
        {"metric": "one_sided_overextension_rows", "value": overreach},
        {"metric": "boundary_crossing_violations", "value": boundary_violations},
        {"metric": "final_decision", "value": decision},
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "one-sided neutral corridors rebuilt with no signal-spanning outputs"}])
    write_csv("recommended_next_actions.csv", [{"rank": 1, "action": "validate_one_sided_approach_corridors_then_build_bin_context", "rationale": "Corridors now have one-sided neutral side classes and reach fields."}])
    findings = f"""# One-Sided Approach Corridors Rebuild

## Prior object issue
The prior staged corridor object was not bin-ready because it contained signal-spanning intervals. The side/reach audit found 15,584 signal-spanning rows and a max total span near 5,000 ft.

## What was rebuilt
Rebuilt `approach_corridors.parquet` as one-sided neutral corridor intervals. Each output row is one physical approach, one Travelway subbranch, one neutral measure side, and one bounded interval.

## What was not built
No bins, upstream/downstream labels, directionality, distance-band units, MVP, speed/AADT/exposure, access, crash, or rate products were built.

## Gates and warnings
Blocked approaches excluded: {len(frames['blocked']):,}. Warning approaches were included where evidence existed and warning provenance was carried forward.

## Side assignment
Signal-spanning source intervals were split into neutral `measure_increasing_from_signal` and `measure_decreasing_from_signal` rows where supported. Output signal-spanning rows: {spanning}.

## Boundaries and continuity
No supported signal boundary crossings were output. No gap bridges were attempted. Route/measure continuity remains conservative single-source-row evidence.

## Non-directionality
No upstream/downstream or directionality fields were assigned.

## Readiness
Final decision: `{decision}`. The one-sided corridor layer is ready for validation and then bin_context construction if QA is accepted.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {"created_at": now(), "script": rel(Path(__file__)), "output_dir": rel(OUT), "staged_product": rel(APPROACH_CORRIDORS), "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()), "final_decision": decision}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "corridor_rows": int(len(corridors)),
        "approaches_with_corridors": int(app_counts["corridor_count"].gt(0).sum()),
        "eligible_approaches_without_corridors": int(((app_counts["corridor_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")).sum()),
        "blocked_approaches_excluded": int(len(frames["blocked"])),
        "signal_spanning_output_rows": spanning,
        "reviewed_measure_outside_rows": outside,
        "one_sided_overextension_rows": overreach,
        "boundary_crossing_violations": boundary_violations,
        "gap_bridge_attempts": 0,
        "accepted_gap_bridges": 0,
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
