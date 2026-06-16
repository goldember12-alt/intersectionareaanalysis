"""Build the Phase B.3 staged signal_travelway_attachment cache object.

Canonical parents for this relationship object are only:
- staged signal_index.parquet
- staged travelway_network_index.parquet

This script does not build approaches, corridors, bins, directionality, numeric
context, crash products, access products, or MVP products.
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
from shapely.strtree import STRtree


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/build_signal_travelway_attachment"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
SIGNAL_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_index_readiness_status"
TRAVELWAY_READINESS_REVIEW = REPO / "work/roadway_graph/review/travelway_network_index_readiness_audit"
SIGNAL_RULE_REVIEW = REPO / "work/roadway_graph/review/signal_analysis_readiness_rule_discovery"

SEARCH_DISTANCE_FT = 250.0
HIGH_DISTANCE_FT = 50.0
MEDIUM_DISTANCE_FT = 175.0


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


def nonblank(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>", "nat"])


def hash_text(text: str, length: int | None = None) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest if length is None else digest[:length]


def load_wkb(value: Any) -> BaseGeometry | None:
    if value is None or pd.isna(value):
        return None
    try:
        payload = bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value
        geom = wkb.loads(payload)
        return None if geom.is_empty else geom
    except Exception:
        return None


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def projected_measure(
    line: BaseGeometry,
    point: BaseGeometry,
    source_measure_start: Any,
    source_measure_end: Any,
    route_measure_status: str,
) -> tuple[float | None, float | None, float | None, str]:
    line_length = float(getattr(line, "length", 0.0) or 0.0)
    if line_length <= 0:
        return None, None, None, "geometry_length_missing_or_zero"
    projected_distance = float(line.project(point))
    fraction = max(0.0, min(1.0, projected_distance / line_length))
    if route_measure_status != "route_measure_complete":
        return projected_distance, fraction, None, f"route_measure_limited_{route_measure_status}"
    start = pd.to_numeric(pd.Series([source_measure_start]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([source_measure_end]), errors="coerce").iloc[0]
    if pd.isna(start) or pd.isna(end):
        return projected_distance, fraction, None, "missing_numeric_measure"
    return projected_distance, fraction, float(start + (end - start) * fraction), "estimated_measure_projected"


def confidence_and_status(distance_ft: float, rank: int, estimated_measure_status: str, geometry_status: str) -> tuple[str, str, bool]:
    valid_geometry = geometry_status == "present_valid_geometry"
    measure_projected = estimated_measure_status == "estimated_measure_projected"
    if distance_ft <= HIGH_DISTANCE_FT and rank <= 5 and valid_geometry and measure_projected:
        return "high", "accepted_spatial_candidate", True
    if distance_ft <= MEDIUM_DISTANCE_FT and rank <= 20 and valid_geometry:
        status = "accepted_spatial_candidate" if measure_projected else "accepted_spatial_candidate_measure_limited"
        return "medium", status, bool(measure_projected)
    status = "accepted_low_confidence_spatial_candidate" if measure_projected else "accepted_low_confidence_spatial_candidate_measure_limited"
    return "low", status, False


def build_candidates(signals: pd.DataFrame, travelways: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    log("Parsing Travelway WKB geometries.")
    road_geoms: list[BaseGeometry] = []
    road_source_indices: list[int] = []
    for idx, value in travelways["geometry"].items():
        geom = load_wkb(value)
        if geom is not None:
            road_geoms.append(geom)
            road_source_indices.append(idx)
    if not road_geoms:
        raise RuntimeError("No parseable Travelway geometries found.")
    tree = STRtree(road_geoms)
    log(f"Built spatial index for {len(road_geoms)} Travelway geometries.")

    candidate_records: list[dict[str, Any]] = []
    no_candidate_records: list[dict[str, Any]] = []
    for signal_ord, (_, sig) in enumerate(signals.iterrows()):
        point = load_wkb(sig.get("geometry"))
        if point is None:
            no_candidate_records.append(
                {
                    "stable_signal_id": clean(sig.get("stable_signal_id")),
                    "signal_index_row_id": clean(sig.get("signal_index_row_id")),
                    "analysis_ready_status": clean(sig.get("analysis_ready_status")),
                    "no_attachment_reason": "missing_or_unparseable_signal_geometry",
                    "nearest_stable_travelway_id": "",
                    "nearest_distance_ft": "",
                }
            )
            continue
        candidate_tree_indices = tree.query(point.buffer(SEARCH_DISTANCE_FT))
        scoped_candidates: list[tuple[float, int, BaseGeometry]] = []
        for tree_idx in candidate_tree_indices:
            geom = road_geoms[int(tree_idx)]
            distance = float(point.distance(geom))
            if distance <= SEARCH_DISTANCE_FT:
                scoped_candidates.append((distance, road_source_indices[int(tree_idx)], geom))
        if not scoped_candidates:
            nearest_tree_idx = int(tree.nearest(point))
            nearest_geom = road_geoms[nearest_tree_idx]
            nearest_source_idx = road_source_indices[nearest_tree_idx]
            nearest_row = travelways.loc[nearest_source_idx]
            no_candidate_records.append(
                {
                    "stable_signal_id": clean(sig.get("stable_signal_id")),
                    "signal_index_row_id": clean(sig.get("signal_index_row_id")),
                    "analysis_ready_status": clean(sig.get("analysis_ready_status")),
                    "source_limited_status": clean(sig.get("source_limited_status")),
                    "source_limited_reason": clean(sig.get("source_limited_reason")),
                    "no_attachment_reason": f"no_travelway_within_{int(SEARCH_DISTANCE_FT)}ft",
                    "nearest_stable_travelway_id": clean(nearest_row.get("stable_travelway_id")),
                    "nearest_travelway_index_row_id": clean(nearest_row.get("travelway_index_row_id")),
                    "nearest_source_route_name": clean(nearest_row.get("source_route_name")),
                    "nearest_distance_ft": round(float(point.distance(nearest_geom)), 3),
                }
            )
            continue
        scoped_candidates.sort(key=lambda item: (item[0], clean(travelways.loc[item[1]].get("stable_travelway_id"))))
        for rank, (distance, road_idx, geom) in enumerate(scoped_candidates, start=1):
            road = travelways.loc[road_idx]
            projected_distance, fraction, measure, measure_status = projected_measure(
                geom,
                point,
                road.get("source_measure_start"),
                road.get("source_measure_end"),
                clean(road.get("route_measure_status")),
            )
            confidence, status, usable_boundary = confidence_and_status(
                distance,
                rank,
                measure_status,
                clean(road.get("geometry_validity_status")),
            )
            basis = "|".join(
                [
                    clean(sig.get("stable_signal_id")),
                    clean(road.get("stable_travelway_id")),
                    clean(sig.get("signal_index_row_id")),
                    clean(road.get("travelway_index_row_id")),
                    f"{distance:.6f}",
                    str(rank),
                ]
            )
            candidate_records.append(
                {
                    "attachment_id": f"sta_{hash_text(basis, 24)}",
                    "stable_signal_id": clean(sig.get("stable_signal_id")),
                    "stable_travelway_id": clean(road.get("stable_travelway_id")),
                    "signal_index_row_id": clean(sig.get("signal_index_row_id")),
                    "travelway_index_row_id": clean(road.get("travelway_index_row_id")),
                    "point_to_line_distance_ft": round(distance, 6),
                    "projected_distance_along_geometry": projected_distance,
                    "projected_fraction": fraction,
                    "estimated_measure": measure,
                    "estimated_measure_status": measure_status,
                    "attachment_confidence": confidence,
                    "attachment_status": status,
                    "attachment_method": f"spatial_index_wkb_projection_within_{int(SEARCH_DISTANCE_FT)}ft",
                    "candidate_rank_for_signal": rank,
                    "candidate_rank_for_signal_route": 0,
                    "usable_as_corridor_boundary": usable_boundary,
                    "no_attachment_reason": "",
                    "source_signal_globalid": clean(sig.get("source_signal_globalid")),
                    "signal_geometry_hash": clean(sig.get("signal_geometry_hash")),
                    "source_layer": clean(road.get("source_layer")),
                    "source_route_name": clean(road.get("source_route_name")),
                    "source_route_id": clean(road.get("source_route_id")),
                    "source_route_common": clean(road.get("source_route_common")),
                    "source_measure_start": road.get("source_measure_start"),
                    "source_measure_end": road.get("source_measure_end"),
                    "route_measure_status": clean(road.get("route_measure_status")),
                    "roadway_configuration": clean(road.get("roadway_configuration")),
                    "carriageway_direction_token": clean(road.get("carriageway_direction_token")),
                    "travelway_geometry_hash": clean(road.get("geometry_hash")),
                    "analysis_ready_status": clean(sig.get("analysis_ready_status")),
                    "source_limited_status": clean(sig.get("source_limited_status")),
                    "source_limited_reason": clean(sig.get("source_limited_reason")),
                }
            )
        if signal_ord and signal_ord % 500 == 0:
            log(f"Processed {signal_ord} signals.")

    candidates = pd.DataFrame.from_records(candidate_records)
    if not candidates.empty:
        candidates["candidate_rank_for_signal_route"] = (
            candidates.sort_values(["stable_signal_id", "source_route_name", "point_to_line_distance_ft", "stable_travelway_id"])
            .groupby(["stable_signal_id", "source_route_name"], dropna=False)
            .cumcount()
            + 1
        )
    return candidates, pd.DataFrame.from_records(no_candidate_records)


def count_rows(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    if df.empty:
        return [{**{col: "<none>" for col in cols}, "row_count": 0}]
    return df.groupby(cols, dropna=False).size().reset_index(name="row_count").to_dict("records")


def write_qa(signals: pd.DataFrame, travelways: pd.DataFrame, candidates: pd.DataFrame, no_candidates: pd.DataFrame, decision: str) -> None:
    ready_counts = signals["analysis_ready_status"].value_counts(dropna=False).to_dict()
    candidate_signal_ids = set(candidates["stable_signal_id"]) if not candidates.empty else set()
    no_candidate_signal_ids = set(no_candidates["stable_signal_id"]) if not no_candidates.empty else set()
    attempted_count = int(signals["stable_signal_id"].nunique())
    candidate_count_by_signal = (
        candidates.groupby("stable_signal_id").size().reset_index(name="candidate_count")
        if not candidates.empty
        else pd.DataFrame(columns=["stable_signal_id", "candidate_count"])
    )
    all_counts = signals[["stable_signal_id", "analysis_ready_status", "analysis_ready_confidence", "source_limited_status"]].merge(
        candidate_count_by_signal, on="stable_signal_id", how="left"
    )
    all_counts["candidate_count"] = all_counts["candidate_count"].fillna(0).astype(int)
    write_csv("candidate_count_by_signal.csv", all_counts.to_dict("records"))
    dist = all_counts["candidate_count"].value_counts().sort_index().reset_index()
    dist.columns = ["candidate_count", "signal_count"]
    write_csv("candidate_count_distribution.csv", dist.to_dict("records"))
    write_csv("no_candidate_signal_ledger.csv", no_candidates.to_dict("records"))
    write_csv("attachment_confidence_summary.csv", count_rows(candidates, ["attachment_confidence"]))
    write_csv("attachment_status_summary.csv", count_rows(candidates, ["attachment_status"]))
    write_csv("estimated_measure_status_summary.csv", count_rows(candidates, ["estimated_measure_status"]))
    route_limited = candidates[candidates["route_measure_status"].ne("route_measure_complete")] if not candidates.empty else candidates
    write_csv("route_measure_limited_candidate_summary.csv", count_rows(route_limited, ["route_measure_status", "estimated_measure_status"]))
    high_counts = all_counts[all_counts["candidate_count"] >= 25].sort_values("candidate_count", ascending=False)
    write_csv("high_candidate_count_signals.csv", high_counts.head(500).to_dict("records"))
    readiness = all_counts.copy()
    readiness["attachment_result"] = readiness["candidate_count"].map(lambda x: "has_candidate" if x else "no_candidate")
    write_csv(
        "signal_index_readiness_vs_attachment_result.csv",
        readiness.groupby(["analysis_ready_status", "analysis_ready_confidence", "source_limited_status", "attachment_result"], dropna=False)
        .size()
        .reset_index(name="signal_count")
        .to_dict("records"),
    )
    parent_rows = [
        {"object": "signal_travelway_attachment", "dependency": rel(SIGNAL_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "signal_travelway_attachment", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "signal_travelway_attachment", "dependency": rel(CONTRACT_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_travelway_attachment", "dependency": rel(SIGNAL_PATCH_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_travelway_attachment", "dependency": rel(TRAVELWAY_READINESS_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_travelway_attachment", "dependency": rel(SIGNAL_RULE_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
    ]
    write_csv("parent_dependency_check.csv", parent_rows)
    duplicate_attachments = int(candidates["attachment_id"].duplicated(keep=False).sum()) if not candidates.empty else 0
    write_csv(
        "attachment_id_uniqueness_check.csv",
        [
            {
                "candidate_rows": int(len(candidates)),
                "attachment_id_non_null": int(nonblank(candidates["attachment_id"]).sum()) if not candidates.empty else 0,
                "duplicate_attachment_id_rows": duplicate_attachments,
                "status": "pass" if duplicate_attachments == 0 else "fail",
            }
        ],
    )
    attempted = signals[["stable_signal_id", "signal_index_row_id", "analysis_ready_status", "analysis_ready_confidence"]].copy()
    attempted["attempt_status"] = "attempted"
    attempted["attachment_candidate_count"] = attempted["stable_signal_id"].map(all_counts.set_index("stable_signal_id")["candidate_count"])
    write_csv("signal_attempt_reconciliation.csv", attempted.to_dict("records"))
    write_csv(
        "signal_travelway_attachment_build_summary.csv",
        [
            {"metric": "signals_attempted", "value": attempted_count},
            {"metric": "candidate_rows_written", "value": int(len(candidates))},
            {"metric": "no_candidate_signals", "value": int(len(no_candidate_signal_ids))},
            {"metric": "analysis_ready_signals", "value": int(ready_counts.get("analysis_ready", 0))},
            {
                "metric": "not_analysis_ready_geometry_or_attachment_limited_signals",
                "value": int(ready_counts.get("not_analysis_ready_geometry_or_attachment_limited", 0)),
            },
            {"metric": "estimated_measure_populated_rows", "value": int(candidates["estimated_measure"].notna().sum()) if not candidates.empty else 0},
            {"metric": "usable_as_corridor_boundary_rows", "value": int(candidates["usable_as_corridor_boundary"].sum()) if not candidates.empty else 0},
            {"metric": "final_decision", "value": decision},
        ],
    )


def update_metadata(candidates: pd.DataFrame, no_candidates: pd.DataFrame, decision: str) -> None:
    product = {
        "path": rel(ATTACHMENT),
        "grain": "one row per signal-to-Travelway spatial projection candidate within 250 ft",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX)],
        "method_evidence_only": [rel(CONTRACT_REVIEW), rel(SIGNAL_PATCH_REVIEW), rel(TRAVELWAY_READINESS_REVIEW), rel(SIGNAL_RULE_REVIEW)],
        "row_count": int(len(candidates)),
        "created_utc": now(),
        "script": "src.roadway_graph.build.build_signal_travelway_attachment",
        "search_distance_ft": SEARCH_DISTANCE_FT,
        "confidence_definition": {
            "high": "distance <= 50 ft, candidate rank <= 5, valid Travelway geometry, and projected route measure available",
            "medium": "distance <= 175 ft, candidate rank <= 20, valid Travelway geometry, but not all high criteria met",
            "low": "within 250 ft but outside high/medium criteria or route/measure-limited",
        },
        "no_candidate_signal_count": int(len(no_candidates)),
        "final_decision": decision,
    }
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {})
    manifest["products"]["signal_travelway_attachment"] = product
    manifest["phase_b3_signal_travelway_attachment_built"] = True
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    schema.setdefault("tables", {})
    schema["tables"]["signal_travelway_attachment.parquet"] = {
        "grain": "one row per accepted signal-to-Travelway spatial projection candidate",
        "canonical_parent": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX)],
        "required_columns": [
            "attachment_id",
            "stable_signal_id",
            "stable_travelway_id",
            "signal_index_row_id",
            "travelway_index_row_id",
            "point_to_line_distance_ft",
            "projected_distance_along_geometry",
            "projected_fraction",
            "estimated_measure",
            "estimated_measure_status",
            "attachment_confidence",
            "attachment_status",
            "attachment_method",
            "candidate_rank_for_signal",
            "candidate_rank_for_signal_route",
            "usable_as_corridor_boundary",
            "no_attachment_reason",
        ],
        "confidence_definition": product["confidence_definition"],
        "forbidden_dependencies": "No downstream approach/corridor/bin/directionality/context/crash/access/MVP objects.",
    }
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

    readme_addition = f"""

## Phase B.3 signal_travelway_attachment

Built `{rel(ATTACHMENT)}` from validated parent objects `signal_index.parquet` and
`travelway_network_index.parquet` only. The table is candidate projection
evidence, not an approach layer: multiple Travelway candidates per signal are
allowed, no approach IDs are assigned, and no upstream/downstream values are
assigned.

Candidate generation uses WKB geometry and a Shapely spatial index with a
{int(SEARCH_DISTANCE_FT)} ft search threshold in the parent coordinate units.
Confidence is deterministic: high means <= {int(HIGH_DISTANCE_FT)} ft, rank <= 5,
valid geometry, and projected measure available; medium means <=
{int(MEDIUM_DISTANCE_FT)} ft, rank <= 20, and valid geometry; low means within
{int(SEARCH_DISTANCE_FT)} ft but outside high/medium criteria or measure-limited.
"""
    existing = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else ""
    if "## Phase B.3 signal_travelway_attachment" not in existing:
        STAGING_README.write_text(existing.rstrip() + readme_addition, encoding="utf-8")


def write_findings(signals: pd.DataFrame, candidates: pd.DataFrame, no_candidates: pd.DataFrame, decision: str) -> None:
    ready = signals["analysis_ready_status"].value_counts().to_dict()
    confidence_counts = candidates["attachment_confidence"].value_counts().to_dict() if not candidates.empty else {}
    status_counts = candidates["attachment_status"].value_counts().to_dict() if not candidates.empty else {}
    estimated_measure_count = int(candidates["estimated_measure"].notna().sum()) if not candidates.empty else 0
    route_limited_count = int(candidates["route_measure_status"].ne("route_measure_complete").sum()) if not candidates.empty else 0
    text = f"""# Signal Travelway Attachment Build

## What was built
Built `signal_travelway_attachment.parquet`, a source-rooted candidate projection table linking staged signal_index rows to nearby staged Travelway rows.

## What was not built
No approaches, corridors, bins, directionality, distance-band units, MVP, speed/AADT/exposure, access, or crash products were built.

## Parent dependency statement
Canonical parents are only `signal_index.parquet` and `travelway_network_index.parquet`. Review outputs were used only as method/status evidence.

## Candidate generation policy
All {len(signals):,} signals were attempted. Travelway candidates within {int(SEARCH_DISTANCE_FT)} ft of each signal point were retained. Signals with no candidate inside the threshold were preserved in the no-candidate ledger with nearest-road diagnostics.

## Confidence definitions
High: distance <= {int(HIGH_DISTANCE_FT)} ft, rank <= 5, valid Travelway geometry, and projected route measure available.
Medium: distance <= {int(MEDIUM_DISTANCE_FT)} ft, rank <= 20, and valid Travelway geometry, but not all high criteria met.
Low: within {int(SEARCH_DISTANCE_FT)} ft but outside high/medium criteria or route/measure-limited.

## Results
Signals attempted: {len(signals):,}.
Candidate rows: {len(candidates):,}.
No-candidate signals: {len(no_candidates):,}.
Estimated measure populated rows: {estimated_measure_count:,}.
Route/measure-limited candidate rows: {route_limited_count:,}.

Attachment confidence counts: {confidence_counts}.
Attachment status counts: {status_counts}.

## Signal readiness behavior
Signal index readiness groups: {ready}. The 3,912 analysis-ready and 21 attachment-limited groups are summarized separately in `signal_index_readiness_vs_attachment_result.csv`. Attachment evidence is reported here but does not patch signal_index.

## Route/measure implications
Route/measure-limited Travelway rows were retained as spatial candidates when geometrically valid. They are not full corridor-boundary evidence unless projected measure is available.

## Readiness decision
Final decision: `{decision}`.

## Recommended next task
Build `signal_approaches.parquet` from validated base indexes and this candidate attachment table, with explicit candidate selection and ambiguity rules.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting Phase B.3 signal_travelway_attachment build.")
    signals = pd.read_parquet(SIGNAL_INDEX)
    travelways = pd.read_parquet(TRAVELWAY_INDEX)
    log(f"Loaded signal rows={len(signals)} and Travelway rows={len(travelways)}.")
    candidates, no_candidates = build_candidates(signals, travelways)
    log(f"Built candidate rows={len(candidates)} and no-candidate signals={len(no_candidates)}.")

    duplicate_attachment_ids = int(candidates["attachment_id"].duplicated(keep=False).sum()) if not candidates.empty else 0
    missing_measure_when_ready = (
        int(candidates.loc[candidates["estimated_measure_status"].eq("estimated_measure_projected"), "estimated_measure"].isna().sum())
        if not candidates.empty
        else 0
    )
    invalid_parent_links = 0
    if not candidates.empty:
        invalid_parent_links += int((~candidates["stable_signal_id"].isin(signals["stable_signal_id"])).sum())
        invalid_parent_links += int((~candidates["stable_travelway_id"].isin(travelways["stable_travelway_id"])).sum())
    if invalid_parent_links:
        decision = "signal_travelway_attachment_needs_parent_data_repair"
    elif duplicate_attachment_ids:
        decision = "signal_travelway_attachment_needs_candidate_rule_repair"
    elif missing_measure_when_ready:
        decision = "signal_travelway_attachment_needs_measure_projection_repair"
    elif len(candidates) == 0:
        decision = "signal_travelway_attachment_blocked_by_geometry_or_crs_issue"
    else:
        decision = "signal_travelway_attachment_ready_as_validated_parent"

    candidates.to_parquet(ATTACHMENT, index=False)
    log(f"Wrote {rel(ATTACHMENT)}.")
    write_qa(signals, travelways, candidates, no_candidates, decision)
    write_findings(signals, candidates, no_candidates, decision)
    update_metadata(candidates, no_candidates, decision)

    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "staged_product": rel(ATTACHMENT),
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX)],
        "method_evidence_only": [rel(CONTRACT_REVIEW), rel(SIGNAL_PATCH_REVIEW), rel(TRAVELWAY_READINESS_REVIEW), rel(SIGNAL_RULE_REVIEW)],
        "search_distance_ft": SEARCH_DISTANCE_FT,
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa_manifest = {
        "created_at": now(),
        "signals_attempted": int(signals["stable_signal_id"].nunique()),
        "candidate_rows": int(len(candidates)),
        "no_candidate_signals": int(len(no_candidates)),
        "duplicate_attachment_id_rows": duplicate_attachment_ids,
        "invalid_parent_link_count": invalid_parent_links,
        "estimated_measure_projected_rows": int(candidates["estimated_measure"].notna().sum()) if not candidates.empty else 0,
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2), encoding="utf-8")
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "rank": 1,
                "action": "build_signal_approaches_from_validated_attachment_candidates",
                "rationale": "Attachment candidates are source-rooted and parent-linked; next layer should select/cluster candidates into physical approaches.",
            }
        ],
    )
    log(f"Build complete with decision {decision}.")


if __name__ == "__main__":
    main()
