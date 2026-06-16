"""Build Phase C.2 staged approach_corridors from validated gated parents.

This layer creates neutral, source-rooted corridor intervals for accepted signal
approaches. It does not build bins and does not assign upstream/downstream or
directionality.
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
OUT = REPO / "work/roadway_graph/review/build_approach_corridors"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
EXCEPTION_AUDIT = REPO / "work/roadway_graph/review/signal_approaches_exception_adjudication_audit"
VALIDATION_AUDIT = REPO / "work/roadway_graph/review/signal_approaches_validation_audit"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
TRAVELWAY_READINESS_REVIEW = REPO / "work/roadway_graph/review/travelway_network_index_readiness_audit"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
CANONICAL_FINAL = REPO / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset"
REFRESH_CANDIDATE = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"

MAX_CORRIDOR_DISTANCE_FT = 2500.0
MEASURE_MILES_LIMIT = MAX_CORRIDOR_DISTANCE_FT / 5280.0


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


def corridor_geometry(row: pd.Series, from_measure: float, to_measure: float) -> tuple[Any, str]:
    geom = load_wkb(row.get("geometry"))
    if geom is None:
        return None, "missing_or_unparseable_parent_travelway_geometry"
    start = float(row["source_measure_start"])
    end = float(row["source_measure_end"])
    if start == end:
        return row.get("geometry"), "source_row_geometry_zero_measure_interval"
    lo = min(start, end)
    hi = max(start, end)
    if hi <= lo:
        return row.get("geometry"), "source_row_geometry_invalid_measure_interval"
    f0 = max(0.0, min(1.0, (min(from_measure, to_measure) - lo) / (hi - lo)))
    f1 = max(0.0, min(1.0, (max(from_measure, to_measure) - lo) / (hi - lo)))
    try:
        sub = substring(geom, f0, f1, normalized=True)
        if sub.is_empty:
            return row.get("geometry"), "source_row_geometry_substring_empty_fallback"
        return wkb.dumps(sub), "derived_travelway_measure_interval_geometry"
    except Exception:
        return row.get("geometry"), "source_row_geometry_substring_failed_fallback"


def endpoint_bounds(
    attachment_boundaries: pd.DataFrame,
    stable_signal_id: str,
    stable_travelway_id: str,
    signal_measure: float,
    initial_from: float,
    initial_to: float,
) -> dict[str, Any]:
    same = attachment_boundaries[
        attachment_boundaries["stable_travelway_id"].eq(stable_travelway_id)
        & attachment_boundaries["estimated_measure"].notna()
        & ~attachment_boundaries["stable_signal_id"].eq(stable_signal_id)
    ].copy()
    same_measure = same[(same["estimated_measure"] - signal_measure).abs() <= 1e-6]
    if not same_measure.empty:
        return {
            "from_measure": initial_from,
            "to_measure": initial_to,
            "before_id": "",
            "after_id": "",
            "before_globalid": "",
            "after_globalid": "",
            "clipped_by_signal": False,
            "boundary_method": "same_measure_signal_boundary_conflict",
            "cross_violation": True,
            "same_measure_conflict": True,
            "same_measure_conflict_ids": "|".join(sorted(set(same_measure["stable_signal_id"].astype(str)))),
        }
    if same.empty:
        return {
            "from_measure": initial_from,
            "to_measure": initial_to,
            "before_id": "",
            "after_id": "",
            "before_globalid": "",
            "after_globalid": "",
            "clipped_by_signal": False,
            "boundary_method": "signal_to_2500ft_or_source_extent",
            "cross_violation": False,
            "same_measure_conflict": False,
            "same_measure_conflict_ids": "",
        }
    lo = min(initial_from, initial_to)
    hi = max(initial_from, initial_to)
    before = same[(same["estimated_measure"] < signal_measure) & (same["estimated_measure"] >= lo)].sort_values("estimated_measure", ascending=False)
    after = same[(same["estimated_measure"] > signal_measure) & (same["estimated_measure"] <= hi)].sort_values("estimated_measure")
    from_m = initial_from
    to_m = initial_to
    clipped = False
    before_id = before_gid = after_id = after_gid = ""
    if not before.empty:
        row = before.iloc[0]
        before_id = clean(row.get("stable_signal_id"))
        before_gid = clean(row.get("source_signal_globalid"))
        if from_m < signal_measure:
            from_m = max(from_m, float(row["estimated_measure"]))
            clipped = True
    if not after.empty:
        row = after.iloc[0]
        after_id = clean(row.get("stable_signal_id"))
        after_gid = clean(row.get("source_signal_globalid"))
        if to_m > signal_measure:
            to_m = min(to_m, float(row["estimated_measure"]))
            clipped = True
    boundary_method = "source_signal_boundary_clip" if clipped else "signal_to_2500ft_or_source_extent"
    crossing = bool(
        ((same["estimated_measure"] > min(from_m, to_m)) & (same["estimated_measure"] < max(from_m, to_m)) & ~same["stable_signal_id"].eq(stable_signal_id)).any()
    )
    return {
        "from_measure": from_m,
        "to_measure": to_m,
        "before_id": before_id,
        "after_id": after_id,
        "before_globalid": before_gid,
        "after_globalid": after_gid,
        "clipped_by_signal": clipped,
        "boundary_method": boundary_method,
        "cross_violation": crossing,
        "same_measure_conflict": False,
        "same_measure_conflict_ids": "",
    }


def build_corridors(
    signals: pd.DataFrame,
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
    rows: list[dict[str, Any]] = []
    no_corridor: list[dict[str, Any]] = []
    boundary_audit: list[dict[str, Any]] = []
    continuity_rows: list[dict[str, Any]] = []
    for _, app in include.iterrows():
        support_ids = split_pipe(app.get("supporting_attachment_ids"))
        support = attachments_by_id.loc[[sid for sid in support_ids if sid in attachments_by_id.index]].copy() if support_ids else pd.DataFrame()
        if support.empty:
            no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "no_corridor_reason": "missing_supporting_attachment_rows"})
            continue
        support = support[
            support["attachment_confidence"].isin(["high", "medium"])
            & support["estimated_measure_status"].eq("estimated_measure_projected")
            & support["usable_as_corridor_boundary"].fillna(False).astype(bool)
        ]
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
            signal_measure = float(group.sort_values(["point_to_line_distance_ft", "candidate_rank_for_signal"]).iloc[0]["estimated_measure"])
            source_lo = min(float(source_start), float(source_end))
            source_hi = max(float(source_start), float(source_end))
            initial_from = max(source_lo, signal_measure - MEASURE_MILES_LIMIT)
            initial_to = min(source_hi, signal_measure + MEASURE_MILES_LIMIT)
            clipped_2500 = (initial_from > source_lo) or (initial_to < source_hi)
            clipped_source = (initial_from == source_lo) or (initial_to == source_hi)
            bounds = endpoint_bounds(boundary_candidates, app["stable_signal_id"], stable_travelway_id, signal_measure, initial_from, initial_to)
            if bounds.get("same_measure_conflict"):
                no_corridor.append(
                    {
                        "signal_approach_id": app["signal_approach_id"],
                        "stable_signal_id": app["stable_signal_id"],
                        "stable_travelway_id": stable_travelway_id,
                        "no_corridor_reason": "same_measure_supported_signal_boundary_conflict",
                        "conflicting_boundary_signal_ids": bounds.get("same_measure_conflict_ids", ""),
                    }
                )
                continue
            corridor_from = float(bounds["from_measure"])
            corridor_to = float(bounds["to_measure"])
            if corridor_to <= corridor_from:
                no_corridor.append({"signal_approach_id": app["signal_approach_id"], "stable_signal_id": app["stable_signal_id"], "stable_travelway_id": stable_travelway_id, "no_corridor_reason": "boundary_clip_removed_interval"})
                continue
            geom, geom_status = corridor_geometry(road, corridor_from, corridor_to)
            length_ft = abs(corridor_to - corridor_from) * 5280.0
            corridor_id = f"corr_{hash_text('|'.join([app['signal_approach_id'], stable_travelway_id, f'{corridor_from:.6f}', f'{corridor_to:.6f}']))}"
            warning = clean(app.get("corridor_restriction_notes")) if app["corridor_build_gate"] == "corridor_build_ready_with_warning" else ""
            rows.append(
                {
                    "approach_corridor_id": corridor_id,
                    "stable_signal_id": app["stable_signal_id"],
                    "signal_approach_id": app["signal_approach_id"],
                    "stable_travelway_id": stable_travelway_id,
                    "corridor_from_measure": corridor_from,
                    "corridor_to_measure": corridor_to,
                    "reviewed_signal_measure": signal_measure,
                    "corridor_confidence": "high" if app["corridor_build_gate"] == "corridor_build_ready" and not bounds["clipped_by_signal"] else "medium",
                    "corridor_measure_direction_label": "both_measure_directions",
                    "corridor_length_ft": length_ft,
                    "before_endpoint_signal_id": bounds["before_id"],
                    "after_endpoint_signal_id": bounds["after_id"],
                    "before_endpoint_source_globalid": bounds["before_globalid"],
                    "after_endpoint_source_globalid": bounds["after_globalid"],
                    "endpoint_source_only_used": False,
                    "clipped_by_2500_ft_flag": bool(clipped_2500),
                    "clipped_by_signal_boundary_flag": bool(bounds["clipped_by_signal"]),
                    "clipped_by_source_extent_flag": bool(clipped_source),
                    "clipped_by_gap_or_uncertain_continuity_flag": False,
                    "geometry": geom,
                    "geometry_status": geom_status,
                    "route_base": clean(road.get("route_base")),
                    "source_route_name": clean(road.get("source_route_name")),
                    "carriageway_direction_token": clean(road.get("carriageway_direction_token")),
                    "roadway_configuration": clean(road.get("roadway_configuration")),
                    "source_measure_start": float(source_start),
                    "source_measure_end": float(source_end),
                    "endpoint_policy": "nearest_same_travelway_signal_else_2500ft_or_source_extent",
                    "boundary_method": bounds["boundary_method"],
                    "source_only_endpoint_flag": False,
                    "cross_signal_boundary_flag": bool(bounds["cross_violation"]),
                    "route_measure_continuity_status": "route_measure_complete_single_source_row",
                    "gap_bridge_status": "not_attempted",
                    "gap_bridge_method": "",
                    "gap_bridge_confidence": "",
                    "no_corridor_reason": "",
                    "parent_approach_gate": app["corridor_build_gate"],
                    "parent_corridor_gate_severity": app["corridor_gate_severity"],
                    "warning_provenance": warning,
                    "corridor_build_status": "corridor_built",
                    "supporting_attachment_ids": "|".join(group["attachment_id"].astype(str).tolist()),
                }
            )
            boundary_audit.append(
                {
                    "approach_corridor_id": corridor_id,
                    "stable_signal_id": app["stable_signal_id"],
                    "signal_approach_id": app["signal_approach_id"],
                    "stable_travelway_id": stable_travelway_id,
                    "boundary_method": bounds["boundary_method"],
                    "before_endpoint_signal_id": bounds["before_id"],
                    "after_endpoint_signal_id": bounds["after_id"],
                    "cross_signal_boundary_flag": bool(bounds["cross_violation"]),
                }
            )
            continuity_rows.append(
                {
                    "approach_corridor_id": corridor_id,
                    "stable_travelway_id": stable_travelway_id,
                    "route_measure_continuity_status": "route_measure_complete_single_source_row",
                    "gap_bridge_status": "not_attempted",
                    "corridor_length_ft": length_ft,
                }
            )
    frames = {
        "blocked": blocked,
        "no_corridor": pd.DataFrame.from_records(no_corridor),
        "boundary_audit": pd.DataFrame.from_records(boundary_audit),
        "continuity": pd.DataFrame.from_records(continuity_rows),
    }
    return pd.DataFrame.from_records(rows), frames


def update_metadata(corridors: pd.DataFrame, decision: str) -> None:
    product = {
        "path": rel(APPROACH_CORRIDORS),
        "grain": "one row per extended corridor segment per signal approach and supporting Travelway subbranch",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "method_comparison_evidence_only": [rel(GATE_PATCH_REVIEW), rel(EXCEPTION_AUDIT), rel(VALIDATION_AUDIT), rel(BUILD_APPROACH_REVIEW), rel(TRAVELWAY_READINESS_REVIEW), rel(CONTRACT_REVIEW), rel(CANONICAL_FINAL), rel(REFRESH_CANDIDATE)],
        "row_count": int(len(corridors)),
        "created_utc": now(),
        "script": "src.roadway_graph.build.build_approach_corridors",
        "final_decision": decision,
    }
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {})["approach_corridors"] = product
    manifest["phase_c2_approach_corridors_built"] = True
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    schema.setdefault("tables", {})["approach_corridors.parquet"] = {
        "grain": product["grain"],
        "canonical_parent": product["canonical_parents"],
        "required_columns": [
            "approach_corridor_id",
            "stable_signal_id",
            "signal_approach_id",
            "stable_travelway_id",
            "corridor_from_measure",
            "corridor_to_measure",
            "reviewed_signal_measure",
            "corridor_confidence",
        ],
        "forbidden_fields": "No upstream/downstream/directionality assignment fields.",
    }
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    addition = """

## Phase C.2 approach_corridors

Built `approach_corridors.parquet` from validated signal, Travelway,
attachment, and gated approach parent objects. Corridors are neutral
route/measure intervals and do not assign upstream/downstream, directionality,
or bins. Blocking approach gates were excluded; warning gates were carried as
provenance.
"""
    existing = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else ""
    if "## Phase C.2 approach_corridors" not in existing:
        STAGING_README.write_text(existing.rstrip() + addition, encoding="utf-8")


def write_qa(
    signals: pd.DataFrame,
    approaches: pd.DataFrame,
    corridors: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    decision: str,
) -> None:
    corridors.to_parquet(APPROACH_CORRIDORS, index=False)
    write_csv("parent_dependency_check.csv", [
        {"object": "approach_corridors", "dependency": rel(SIGNAL_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(ATTACHMENT), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(APPROACHES), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(GATE_PATCH_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(CANONICAL_FINAL), "dependency_role": "comparison_evidence_only", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(REFRESH_CANDIDATE), "dependency_role": "comparison_evidence_only", "allowed": True},
    ])
    duplicate_ids = int(corridors["approach_corridor_id"].duplicated(keep=False).sum()) if not corridors.empty else 0
    write_csv("approach_corridor_id_uniqueness_check.csv", [{"corridor_rows": int(len(corridors)), "duplicate_approach_corridor_id_rows": duplicate_ids, "status": "pass" if duplicate_ids == 0 else "fail"}])
    write_csv("corridor_rows_by_parent_gate.csv", corridors.groupby("parent_approach_gate").size().reset_index(name="corridor_rows").to_dict("records") if not corridors.empty else [])
    write_csv("excluded_blocked_approach_ledger.csv", frames["blocked"].to_dict("records"))
    no_approach_signals = set(approaches["stable_signal_id"]) ^ set(signals["stable_signal_id"])
    source_limited = signals[signals["stable_signal_id"].isin(no_approach_signals)]
    write_csv("source_limited_no_corridor_signal_ledger.csv", source_limited.to_dict("records"))
    app_counts = approaches[["signal_approach_id", "stable_signal_id", "corridor_build_gate"]].merge(corridors.groupby("signal_approach_id").size().reset_index(name="corridor_count"), on="signal_approach_id", how="left")
    app_counts["corridor_count"] = app_counts["corridor_count"].fillna(0).astype(int)
    write_csv("approach_to_corridor_reconciliation.csv", app_counts.to_dict("records"))
    sig_counts = app_counts.groupby("stable_signal_id").agg(approach_count=("signal_approach_id", "size"), corridor_count=("corridor_count", "sum")).reset_index()
    write_csv("signal_to_corridor_reconciliation.csv", sig_counts.to_dict("records"))
    if not corridors.empty:
        bins = pd.cut(corridors["corridor_length_ft"], bins=[0, 100, 500, 1000, 2500, 5000, 100000], labels=["0_100", "100_500", "500_1000", "1000_2500", "2500_5000", "over_5000"], include_lowest=True)
        write_csv("corridor_length_distribution.csv", bins.value_counts().sort_index().reset_index(name="corridor_rows").rename(columns={"corridor_length_ft": "length_bucket"}).to_dict("records"))
        write_csv("corridor_endpoint_policy_summary.csv", corridors.groupby(["endpoint_policy", "boundary_method"], dropna=False).size().reset_index(name="corridor_rows").to_dict("records"))
    else:
        write_csv("corridor_length_distribution.csv", [])
        write_csv("corridor_endpoint_policy_summary.csv", [])
    write_csv("signal_boundary_stop_audit.csv", frames["boundary_audit"].to_dict("records"))
    violations = corridors[corridors["cross_signal_boundary_flag"]] if not corridors.empty else corridors
    write_csv("possible_boundary_crossing_violations.csv", violations.to_dict("records") if not violations.empty else [])
    write_csv("route_measure_continuity_audit.csv", frames["continuity"].to_dict("records"))
    limited = frames["no_corridor"][frames["no_corridor"].get("no_corridor_reason", pd.Series(dtype=str)).astype(str).str.contains("route_measure_limited|invalid_source_measure", na=False)] if not frames["no_corridor"].empty else pd.DataFrame()
    write_csv("route_measure_limited_corridor_ledger.csv", limited.to_dict("records") if not limited.empty else [])
    write_csv("gap_bridge_attempts.csv", [])
    write_csv("gap_bridge_rejections.csv", [])
    write_csv("gap_bridge_summary.csv", [{"gap_bridge_attempts": 0, "accepted_gap_bridges": 0, "policy": "no gap bridges attempted in conservative Phase C.2 build"}])
    warning_apps = approaches[approaches["corridor_build_gate"].eq("corridor_build_ready_with_warning")]
    warning_out = warning_apps[["signal_approach_id", "stable_signal_id", "corridor_build_gate", "corridor_gate_severity", "corridor_restriction_notes"]].merge(app_counts[["signal_approach_id", "corridor_count"]], on="signal_approach_id", how="left")
    write_csv("warning_approach_corridor_outcomes.csv", warning_out.to_dict("records"))
    write_csv("multi_corridor_per_approach_audit.csv", app_counts[app_counts["corridor_count"] > 1].to_dict("records"))
    write_csv("high_corridor_count_approach_review.csv", app_counts.sort_values("corridor_count", ascending=False).head(500).to_dict("records"))
    write_csv("no_corridor_approach_ledger.csv", pd.concat([frames["no_corridor"], app_counts[(app_counts["corridor_count"] == 0) & ~app_counts["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")]], ignore_index=True).to_dict("records"))
    forbidden = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    write_csv("non_directionality_field_check.csv", [{"forbidden_directionality_field_count": len(forbidden), "forbidden_fields": "|".join(forbidden), "status": "pass" if not forbidden else "fail"}])
    write_csv("old_canonical_corridor_or_bin_comparison.csv", [{"path": rel(CANONICAL_FINAL), "role": "comparison_evidence_only", "used_as_parent": False}, {"path": rel(REFRESH_CANDIDATE), "role": "comparison_evidence_only", "used_as_parent": False}])
    write_csv("approach_corridors_build_summary.csv", [
        {"metric": "corridor_rows_written", "value": int(len(corridors))},
        {"metric": "approaches_with_corridors", "value": int(app_counts["corridor_count"].gt(0).sum())},
        {"metric": "blocked_approaches_excluded", "value": int(len(frames["blocked"]))},
        {"metric": "source_limited_no_corridor_signals", "value": int(len(source_limited))},
        {"metric": "possible_boundary_crossing_violations", "value": int(len(violations))},
        {"metric": "gap_bridge_attempts", "value": 0},
        {"metric": "final_decision", "value": decision},
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "corridors built from gated approaches with no boundary crossings or gap bridges"}])
    write_csv("recommended_next_actions.csv", [{"rank": 1, "action": "validate_approach_corridors_then_build_bin_context", "rationale": "Corridors are neutral intervals; next bin build should respect no-directionality and gate provenance."}])


def write_findings(corridors: pd.DataFrame, approaches: pd.DataFrame, frames: dict[str, pd.DataFrame], decision: str) -> None:
    boundary_violations = int(corridors["cross_signal_boundary_flag"].sum()) if not corridors.empty else 0
    warning_count = int((corridors["parent_approach_gate"] == "corridor_build_ready_with_warning").sum()) if not corridors.empty else 0
    text = f"""# Approach Corridors Build

## What was built
Built `approach_corridors.parquet`, a neutral source-rooted corridor interval table with one row per signal approach and supporting Travelway subbranch/interval.

## What was not built
No bins, upstream/downstream labels, directionality, distance-band units, MVP, speed/AADT/exposure, access, crash, or rate products were built.

## Parent dependency statement
Canonical parents are staged `signal_index`, `travelway_network_index`, `signal_travelway_attachment`, and gated `signal_approaches`. Old products were comparison/method evidence only.

## Blocked and warning approaches
Blocked approaches excluded: {len(frames['blocked']):,}. Warning approach corridor rows carried forward: {warning_count:,}. Warning approaches are not failures.

## Boundary policy
Corridors start from reviewed signal measure on supporting Travelway evidence and are clipped by source row extent, a 2,500 ft measure limit, and same-Travelway supported signal boundaries when present.

## Boundary crossings
Possible supported signal boundary crossings detected: {boundary_violations:,}.

## Route/measure continuity and gaps
This conservative build uses only single source-row route/measure-complete Travelway evidence. No gap bridges were attempted or accepted.

## Corridor subbranches
Corridor rows are subbranch/interval evidence and are not physical approach identities. A single physical approach can have multiple corridor rows.

## Non-directionality confirmation
No upstream/downstream or directionality fields were assigned.

## Readiness decision
Final decision: `{decision}`.

## Recommended next task
Validate this corridor layer, then build `bin_context` from corridor intervals while preserving gate and warning provenance.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting Phase C.2 approach_corridors build.")
    signals = pd.read_parquet(SIGNAL_INDEX)
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    log(f"Loaded signals={len(signals)}, roads={len(roads)}, attachments={len(attachments)}, approaches={len(approaches)}.")
    corridors, frames = build_corridors(signals, roads, attachments, approaches)
    duplicate_ids = int(corridors["approach_corridor_id"].duplicated(keep=False).sum()) if not corridors.empty else 0
    boundary_violations = int(corridors["cross_signal_boundary_flag"].sum()) if not corridors.empty else 0
    too_long = int((corridors["corridor_length_ft"] > (MAX_CORRIDOR_DISTANCE_FT * 2 + 1)).sum()) if not corridors.empty else 0
    if duplicate_ids or boundary_violations:
        decision = "approach_corridors_built_but_needs_boundary_review"
    elif too_long:
        decision = "approach_corridors_needs_route_measure_repair"
    elif corridors.empty:
        decision = "approach_corridors_should_be_rebuilt"
    else:
        decision = "approach_corridors_ready_as_validated_parent"
    write_qa(signals, approaches, corridors, frames, decision)
    update_metadata(corridors, decision)
    write_findings(corridors, approaches, frames, decision)
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "staged_product": rel(APPROACH_CORRIDORS),
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "method_comparison_evidence_only": [rel(GATE_PATCH_REVIEW), rel(EXCEPTION_AUDIT), rel(VALIDATION_AUDIT), rel(BUILD_APPROACH_REVIEW), rel(TRAVELWAY_READINESS_REVIEW), rel(CONTRACT_REVIEW), rel(CANONICAL_FINAL), rel(REFRESH_CANDIDATE)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    app_counts = approaches[["signal_approach_id", "corridor_build_gate"]].merge(corridors.groupby("signal_approach_id").size().reset_index(name="corridor_count"), on="signal_approach_id", how="left")
    app_counts["corridor_count"] = app_counts["corridor_count"].fillna(0).astype(int)
    qa = {
        "created_at": now(),
        "corridor_rows": int(len(corridors)),
        "approaches_with_corridors": int(app_counts["corridor_count"].gt(0).sum()),
        "blocked_approaches_excluded": int(len(frames["blocked"])),
        "possible_boundary_crossing_violations": boundary_violations,
        "gap_bridge_attempts": 0,
        "accepted_gap_bridges": 0,
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    log(f"Build complete with decision {decision}.")


if __name__ == "__main__":
    main()
