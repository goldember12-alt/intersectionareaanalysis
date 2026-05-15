from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .crash_assignment_interpretation_readiness import (
    QA_DIR,
    READINESS_DIR,
    _caveat_class,
    _confidence_tier,
    _distance_band,
    _serious_caveat,
)
from .crash_assignment_qa import (
    OUTPUT_ROOT,
    FEET_PER_METER,
    _build_segment_enrichment,
    _num,
    _read_csv,
    _read_wkt_csv,
    _text,
    _truthy,
    _write_csv,
    _write_json,
    _write_text,
)


PACKET_DIR = Path("review/current/crash_assignment_mapless_review_packets")
CANDIDATE_RADIUS_FT = 75.0


PACKET_COLUMNS = [
    "case_id",
    "case_family",
    "crash_id",
    "reference_signal_id",
    "segment_id",
    "bin_id",
    "assignment_distance_ft",
    "nearest_distance_ft",
    "distance_tier",
    "confidence_tier",
    "geometry_caveat_class",
    "recovery_source",
    "crash_route_name",
    "segment_route_name",
    "segment_route_common",
    "anchor_from_type",
    "anchor_to_type",
    "opposite_anchor_type",
    "nearest_candidate_bin_count",
    "nearest_candidate_segment_count",
    "nearest_1_distance_ft",
    "nearest_2_distance_ft",
    "nearest_3_distance_ft",
    "distance_gap_1_to_2",
    "same_reference_signal_candidate_count",
    "same_road_candidate_count",
    "divided_or_parallel_flag",
    "endpoint_issue_flags",
    "signal_association_flag",
    "low_confidence_divided_flag",
    "why_flagged",
    "recommended_review_action",
]


def _prepare_assigned(output_root: Path) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    assigned = _read_wkt_csv(tables / "crash_oriented_segment_bin_assignment.csv")
    segment_enrichment, _eligibility = _build_segment_enrichment(tables, review)
    out = pd.DataFrame(assigned.drop(columns=["geometry"], errors="ignore")).merge(
        segment_enrichment.drop(columns=["geometry"], errors="ignore"),
        on="oriented_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    out["distance_to_bin_ft_num"] = _num(out, "distance_to_bin_ft")
    out["geometry_caveat_class"] = out.apply(_caveat_class, axis=1)
    out["serious_geometry_caveat"] = out.apply(_serious_caveat, axis=1)
    out["assignment_confidence_tier"] = out.apply(_confidence_tier, axis=1)
    out["assignment_distance_readiness_band"] = out["distance_to_bin_ft_num"].map(_distance_band)
    out["signal_association_flag"] = _text(out, "bounded_scaffold_source").str.contains("signal_association_tolerance", na=False)
    out["low_confidence_divided_flag"] = _text(out, "recovery_status").eq("recovered_low_review_only")
    geometry = assigned[["crash_id", "geometry"]].copy()
    return gpd.GeoDataFrame(out.merge(geometry, on="crash_id", how="left"), geometry="geometry", crs=assigned.crs), segment_enrichment


def _prepare_bins(output_root: Path, segment_enrichment: pd.DataFrame, crs) -> gpd.GeoDataFrame:
    tables = output_root / "tables/current"
    bins = _read_wkt_csv(tables / "signal_oriented_segment_bins_50ft_crash_ready.csv", crs=crs)
    keep = [
        "oriented_segment_id",
        "reference_signal_id",
        "route_name",
        "route_common",
        "roadway_directionality_type",
        "orientation_record_type",
        "bounded_scaffold_source",
    ]
    present = [column for column in keep if column in segment_enrichment.columns]
    enriched = bins.merge(segment_enrichment[present].drop_duplicates("oriented_segment_id"), on="oriented_segment_id", how="left", suffixes=("", "_segment"))
    if "reference_signal_id" not in enriched.columns:
        enriched["reference_signal_id"] = _text(enriched, "downstream_of_signal_id")
    if "route_common" not in enriched.columns:
        enriched["route_common"] = ""
    return gpd.GeoDataFrame(enriched, geometry="geometry", crs=crs)


def _candidate_metrics(cases: gpd.GeoDataFrame, bins: gpd.GeoDataFrame, *, radius_ft: float = CANDIDATE_RADIUS_FT) -> pd.DataFrame:
    if cases.empty or bins.empty:
        return pd.DataFrame(columns=["crash_id"])
    radius = radius_ft / FEET_PER_METER
    rows: list[dict[str, object]] = []
    sindex = bins.sindex
    for row in cases.itertuples(index=False):
        geom = getattr(row, "geometry", None)
        crash_id = str(getattr(row, "crash_id", ""))
        if geom is None or geom.is_empty:
            rows.append({"crash_id": crash_id})
            continue
        idxs = list(sindex.query(geom.buffer(radius)))
        candidates = bins.iloc[idxs].copy() if idxs else bins.iloc[[]].copy()
        if not candidates.empty:
            candidates["candidate_distance_ft"] = candidates.geometry.distance(geom) * FEET_PER_METER
            candidates = candidates.loc[candidates["candidate_distance_ft"].le(radius_ft + 1e-9)].copy()
            candidates = candidates.sort_values(["candidate_distance_ft", "bin_id"])
        distances = list(candidates["candidate_distance_ft"].head(3).round(3)) if not candidates.empty else []
        ref = str(getattr(row, "reference_signal_id", ""))
        route = str(getattr(row, "segment_route_common", "")) or str(getattr(row, "route_common", ""))
        candidate_segments = candidates["oriented_segment_id"].astype(str).nunique() if "oriented_segment_id" in candidates.columns else 0
        same_ref = int(candidates["reference_signal_id"].astype(str).eq(ref).sum()) if ref and "reference_signal_id" in candidates.columns else 0
        same_road = int(candidates["route_common"].astype(str).eq(route).sum()) if route and "route_common" in candidates.columns else 0
        divided = candidates.get("roadway_directionality_type", pd.Series(dtype=str)).astype(str).eq("divided").any() if not candidates.empty else False
        rows.append(
            {
                "crash_id": crash_id,
                "nearest_candidate_bin_count": int(len(candidates)),
                "nearest_candidate_segment_count": int(candidate_segments),
                "nearest_1_distance_ft": distances[0] if len(distances) > 0 else "",
                "nearest_2_distance_ft": distances[1] if len(distances) > 1 else "",
                "nearest_3_distance_ft": distances[2] if len(distances) > 2 else "",
                "distance_gap_1_to_2": round(distances[1] - distances[0], 3) if len(distances) > 1 else "",
                "same_reference_signal_candidate_count": same_ref,
                "same_road_candidate_count": same_road,
                "divided_or_parallel_flag": "TRUE" if divided or candidate_segments > 1 else "FALSE",
            }
        )
    return pd.DataFrame(rows)


def _assigned_packet_base(frame: gpd.GeoDataFrame, case_family: str, why: str) -> pd.DataFrame:
    out = pd.DataFrame(frame.drop(columns=["geometry"], errors="ignore")).copy()
    out["case_family"] = case_family
    out["case_id"] = [f"{case_family}_{idx:06d}" for idx in range(1, len(out) + 1)]
    out["segment_id"] = _text(out, "oriented_segment_id")
    out["assignment_distance_ft"] = _num(out, "distance_to_bin_ft").round(3)
    out["nearest_distance_ft"] = ""
    out["distance_tier"] = _text(out, "assignment_distance_readiness_band")
    out["confidence_tier"] = _text(out, "assignment_confidence_tier")
    out["recovery_source"] = _text(out, "bounded_scaffold_source")
    out["crash_route_name"] = _text(out, "RTE_NM")
    out["segment_route_name"] = _text(out, "route_name")
    out["segment_route_common"] = _text(out, "route_common")
    out["anchor_from_type"] = _text(out, "from_anchor_type")
    out["anchor_to_type"] = _text(out, "to_anchor_type")
    out["endpoint_issue_flags"] = _text(out, "endpoint_qa_categories")
    out["signal_association_flag"] = _truthy(_text(out, "signal_association_tolerance_segment")).map({True: "TRUE", False: "FALSE"})
    out["low_confidence_divided_flag"] = _text(out, "recovery_status").eq("recovered_low_review_only").map({True: "TRUE", False: "FALSE"})
    out["why_flagged"] = why
    out["recommended_review_action"] = out.apply(_recommended_action, axis=1)
    return out


def _recommended_action(row: pd.Series) -> str:
    family = str(row.get("case_family", ""))
    assignment_distance = pd.to_numeric(pd.Series([row.get("assignment_distance_ft", "")]), errors="coerce").iloc[0]
    nearest_distance = pd.to_numeric(pd.Series([row.get("nearest_distance_ft", "")]), errors="coerce").iloc[0]
    distance = assignment_distance if pd.notna(assignment_distance) else nearest_distance
    caveat = str(row.get("geometry_caveat_class", ""))
    signal = str(row.get("signal_association_flag", "")).upper() == "TRUE"
    low_divided = str(row.get("low_confidence_divided_flag", "")).upper() == "TRUE"
    divided_parallel = str(row.get("divided_or_parallel_flag", "")).upper() == "TRUE"

    if family.startswith("unresolved"):
        if pd.notna(distance) and distance <= 25:
            return "possible_assignment_logic_issue"
        return "unresolved_near_scaffold_assignment_gap"
    if low_divided:
        return "exclude_from_directional_now"
    if signal:
        if pd.notna(distance) and distance > 70:
            return "exclude_from_directional_now"
        return "review_signal_association"
    if caveat == "review_required_unknown_endpoint_junction":
        return "review_unknown_endpoint"
    if pd.notna(distance) and distance > 70:
        return "possible_assignment_logic_issue"
    if divided_parallel:
        return "review_parallel_or_divided_ambiguity"
    if pd.notna(distance) and distance > 50:
        return "keep_spatial_exclude_directional"
    if "review_required" in caveat:
        return "keep_spatial_exclude_directional"
    return "keep_spatial_only"


def _finalize_packet(packet: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    if packet.empty:
        return pd.DataFrame(columns=PACKET_COLUMNS)
    out = packet.merge(metrics.drop_duplicates("crash_id"), on="crash_id", how="left", suffixes=("", "_candidate"))
    out["recommended_review_action"] = out.apply(_recommended_action, axis=1)
    for column in PACKET_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[PACKET_COLUMNS].copy()


def _unresolved_packet_base(unresolved_near: pd.DataFrame, unresolved: gpd.GeoDataFrame, case_family: str, max_distance_ft: float, why: str) -> gpd.GeoDataFrame:
    rows = unresolved_near.loc[_num(unresolved_near, "nearest_scaffold_distance_ft").le(max_distance_ft)].copy()
    rows = rows.merge(pd.DataFrame(unresolved[["crash_id", "RTE_NM", "geometry"]]), on="crash_id", how="left")
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=unresolved.crs)
    out["case_family"] = case_family
    out["case_id"] = [f"{case_family}_{idx:06d}" for idx in range(1, len(out) + 1)]
    out["reference_signal_id"] = ""
    out["segment_id"] = _text(out, "oriented_segment_id")
    out["assignment_distance_ft"] = ""
    out["nearest_distance_ft"] = _num(out, "nearest_scaffold_distance_ft").round(3)
    out["distance_tier"] = _text(out, "nearest_scaffold_distance_band")
    out["confidence_tier"] = _text(out, "unresolved_review_priority")
    out["geometry_caveat_class"] = "unresolved_near_scaffold"
    out["recovery_source"] = ""
    out["crash_route_name"] = _text(out, "RTE_NM")
    out["segment_route_name"] = ""
    out["segment_route_common"] = ""
    out["anchor_from_type"] = ""
    out["anchor_to_type"] = ""
    out["opposite_anchor_type"] = ""
    out["endpoint_issue_flags"] = ""
    out["signal_association_flag"] = "FALSE"
    out["low_confidence_divided_flag"] = "FALSE"
    out["why_flagged"] = why
    return out


def _summary_rows(packets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for family, frame in packets.items():
        rows.append(
            {
                "case_family": family,
                "packet_rows": len(frame),
                "unique_crashes": frame["crash_id"].nunique() if "crash_id" in frame.columns else 0,
                "possible_assignment_logic_issue_rows": int(_text(frame, "recommended_review_action").eq("possible_assignment_logic_issue").sum()) if not frame.empty else 0,
                "review_signal_association_rows": int(_text(frame, "recommended_review_action").eq("review_signal_association").sum()) if not frame.empty else 0,
                "exclude_from_directional_now_rows": int(_text(frame, "recommended_review_action").eq("exclude_from_directional_now").sum()) if not frame.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, action_summary: pd.DataFrame, signal_actions: dict[str, int], possible_gap_count: int) -> str:
    family_lines = "\n".join(f"- {row.case_family}: {int(row.packet_rows)} rows" for row in summary.itertuples(index=False))
    action_lines = "\n".join(f"- {row.recommended_review_action}: {int(row.case_rows)} rows" for row in action_summary.itertuples(index=False))
    return f"""# Crash Assignment Mapless Review Packets

**Status:** Read-only tabular review packets for crash assignment interpretation readiness.

## Bounded Question

This module prepares mapless/Codex-native review packets because GIS inspection is not currently available. It classifies and ranks existing assigned and unresolved-near-scaffold records without changing crash assignment, scaffold construction, geometry, direction, or upstream/downstream status.

## Packet Families

{family_lines}

## Recommended Actions

{action_lines}

## Key Interpretation

- Possible unresolved-within-75-ft assignment logic gaps: {possible_gap_count}
- Signal-association action counts: keep={signal_actions.get("keep_spatial_only", 0)}, review={signal_actions.get("review_signal_association", 0)}, exclude={signal_actions.get("exclude_from_directional_now", 0)}

These packets support review prioritization only. Nothing in this output is ready for upstream/downstream interpretation.
"""


def build_mapless_review_packets(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / "tables/current"
    qa_dir = output_root / QA_DIR
    readiness_dir = output_root / READINESS_DIR
    out_dir = output_root / PACKET_DIR

    assigned, segment_enrichment = _prepare_assigned(output_root)
    unresolved = _read_wkt_csv(tables / "crash_oriented_segment_assignment_unresolved.csv", crs=assigned.crs)
    bins = _prepare_bins(output_root, segment_enrichment, assigned.crs)
    unresolved_near = _read_csv(readiness_dir / "unresolved_near_scaffold_ranked_review_queue.csv")
    recovered_signal_queue = _read_csv(readiness_dir / "signal_association_recovered_case_review_queue.csv")

    high_priority = assigned.loc[_text(assigned, "assignment_confidence_tier").eq("high_priority_review_distance_over_70ft")].copy()
    assigned_50_70 = assigned.loc[_text(assigned, "assignment_confidence_tier").eq("low_confidence_review_distance_50_to_70ft")].copy()
    unknown_endpoint = assigned.loc[_text(assigned, "geometry_caveat_class").eq("review_required_unknown_endpoint_junction")].copy()
    signal_assoc = assigned.loc[_truthy(_text(assigned, "signal_association_tolerance_segment"))].copy()
    low_conf_divided = assigned.loc[_text(assigned, "geometry_caveat_class").eq("high_risk_low_confidence_divided_recovery")].copy()

    packet_specs = [
        ("high_priority_assigned_distance", high_priority, "assigned crash is more than 70 ft from its assigned crash-ready bin"),
        ("assigned_50_70ft", assigned_50_70, "assigned crash is 50-70 ft from its assigned crash-ready bin"),
        ("unknown_endpoint", unknown_endpoint, "assigned crash lands on a segment with unknown endpoint/junction issue"),
        ("signal_association", signal_assoc, "assigned crash lands on a signal-association-tolerance scaffold segment"),
        ("low_confidence_divided", low_conf_divided, "assigned crash lands on low-confidence divided recovery review-only segment"),
    ]

    packets: dict[str, pd.DataFrame] = {}
    for family, frame, why in packet_specs:
        base = _assigned_packet_base(frame.sort_values(["distance_to_bin_ft_num", "crash_id"], ascending=[False, True]), family, why)
        metrics = _candidate_metrics(frame, bins)
        packets[family] = _finalize_packet(base, metrics)

    unresolved_75_base = _unresolved_packet_base(
        unresolved_near,
        unresolved,
        "unresolved_within_75ft",
        75.0,
        "unresolved crash is within 75 ft of at least one crash-ready bin",
    )
    unresolved_25_base = _unresolved_packet_base(
        unresolved_near,
        unresolved,
        "unresolved_within_25ft",
        25.0,
        "unresolved crash is within 25 ft of at least one crash-ready bin",
    )
    for family, base in [("unresolved_within_75ft", unresolved_75_base), ("unresolved_within_25ft", unresolved_25_base)]:
        metrics = _candidate_metrics(base, bins)
        packet = pd.DataFrame(base.drop(columns=["geometry"], errors="ignore")).merge(metrics.drop_duplicates("crash_id"), on="crash_id", how="left", suffixes=("", "_candidate"))
        packet["recommended_review_action"] = packet.apply(_recommended_action, axis=1)
        for column in PACKET_COLUMNS:
            if column not in packet.columns:
                packet[column] = ""
        packets[family] = packet[PACKET_COLUMNS].copy()

    outputs = {
        "high_priority_assigned_distance": out_dir / "high_priority_assigned_distance_case_packets.csv",
        "assigned_50_70ft": out_dir / "assigned_50_70ft_case_packets.csv",
        "unknown_endpoint": out_dir / "unknown_endpoint_case_packets.csv",
        "signal_association": out_dir / "signal_association_case_packets.csv",
        "low_confidence_divided": out_dir / "low_confidence_divided_case_packets.csv",
        "unresolved_within_75ft": out_dir / "unresolved_within_75ft_case_packets.csv",
        "unresolved_within_25ft": out_dir / "unresolved_within_25ft_case_packets.csv",
    }
    for key, path in outputs.items():
        _write_csv(packets[key], path)

    packet_summary = _summary_rows(packets)
    _write_csv(packet_summary, out_dir / "mapless_review_packet_summary.csv")
    all_packets = pd.concat(packets.values(), ignore_index=True, sort=False) if packets else pd.DataFrame(columns=PACKET_COLUMNS)
    action_summary = (
        all_packets.groupby(["recommended_review_action", "case_family"], dropna=False)
        .size()
        .reset_index(name="case_rows")
        .sort_values(["case_rows", "recommended_review_action"], ascending=[False, True])
    )
    _write_csv(action_summary, out_dir / "mapless_review_recommended_actions.csv")

    signal_actions = _text(packets["signal_association"], "recommended_review_action").value_counts().to_dict()
    possible_gap_count = int(
        packets["unresolved_within_75ft"]["recommended_review_action"].eq("possible_assignment_logic_issue").sum()
    )
    _write_text(_findings(packet_summary, action_summary, {str(k): int(v) for k, v in signal_actions.items()}, possible_gap_count), out_dir / "mapless_review_findings.md")

    input_files = [
        tables / "crash_oriented_segment_bin_assignment.csv",
        tables / "crash_oriented_segment_assignment_unresolved.csv",
        tables / "signal_oriented_segment_bins_50ft_crash_ready.csv",
        tables / "signal_oriented_roadway_segments_crash_ready.csv",
        qa_dir / "crash_assignment_qa_summary.csv",
        readiness_dir / "assignment_confidence_tiers.csv",
        readiness_dir / "unresolved_near_scaffold_ranked_review_queue.csv",
        readiness_dir / "signal_association_recovered_case_review_queue.csv",
    ]
    output_files = [
        out_dir / "mapless_review_packet_summary.csv",
        *outputs.values(),
        out_dir / "mapless_review_recommended_actions.csv",
        out_dir / "mapless_review_findings.md",
        out_dir / "mapless_review_manifest.json",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Mapless tabular review packets for crash assignment interpretation readiness.",
        "read_only": True,
        "raw_crash_data_read": False,
        "crash_direction_fields_used": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
        "upstream_downstream_inferred": False,
        "candidate_metrics_are_review_diagnostics_not_reassignment": True,
        "input_files": [str(path) for path in input_files if path.exists()],
        "output_files": [str(path) for path in output_files],
        "packet_counts": {row["case_family"]: int(row["packet_rows"]) for _, row in packet_summary.iterrows()},
        "recommended_action_counts": {
            f"{row['recommended_review_action']}|{row['case_family']}": int(row["case_rows"])
            for _, row in action_summary.iterrows()
        },
        "unresolved_within_75ft_possible_assignment_logic_issue_rows": possible_gap_count,
        "signal_association_action_counts": {str(k): int(v) for k, v in signal_actions.items()},
        "top_recovered_signal_cases": recovered_signal_queue.head(10).to_dict(orient="records") if not recovered_signal_queue.empty else [],
    }
    _write_json(manifest, out_dir / "mapless_review_manifest.json")
    return {path.stem: str(path) for path in output_files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build mapless crash-assignment review packets without GIS or assignment changes.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_mapless_review_packets(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
