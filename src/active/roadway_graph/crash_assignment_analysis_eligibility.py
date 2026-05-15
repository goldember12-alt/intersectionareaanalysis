from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .crash_assignment_interpretation_readiness import (
    _caveat_class,
    _confidence_tier,
    _serious_caveat,
)
from .crash_assignment_qa import (
    OUTPUT_ROOT,
    _build_segment_enrichment,
    _num,
    _read_csv,
    _text,
    _write_csv,
    _write_json,
    _write_text,
)


ELIGIBILITY_DIR = Path("review/current/crash_assignment_analysis_eligibility")
MAPLESS_DIR = Path("review/current/crash_assignment_mapless_review_packets")

ASSIGNED_PACKET_FILES = {
    "high_priority_assigned_distance": "high_priority_assigned_distance_case_packets.csv",
    "assigned_50_70ft": "assigned_50_70ft_case_packets.csv",
    "unknown_endpoint": "unknown_endpoint_case_packets.csv",
    "signal_association": "signal_association_case_packets.csv",
    "low_confidence_divided": "low_confidence_divided_case_packets.csv",
}
UNRESOLVED_PACKET_FILE = "unresolved_within_75ft_case_packets.csv"

OUTPUT_COLUMNS = [
    "analysis_record_type",
    "crash_id",
    "reference_signal_id",
    "segment_id",
    "bin_id",
    "assignment_distance_ft",
    "nearest_scaffold_distance_ft",
    "confidence_tier",
    "geometry_caveat_class",
    "recovery_source",
    "mapless_case_families",
    "mapless_recommended_action",
    "anchor_relaxation_flag",
    "spatial_descriptive_eligible",
    "caveated_spatial_review",
    "directional_excluded_now",
    "manual_or_gis_review_priority",
    "possible_assignment_logic_issue",
    "unresolved_near_scaffold_assignment_gap",
    "primary_exclusion_reason",
    "secondary_exclusion_reasons",
    "recommended_next_action",
]


def _bool_text(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def _join_reasons(values: list[str]) -> str:
    return "|".join(dict.fromkeys(reason for reason in values if reason))


def _read_packet(path: Path) -> pd.DataFrame:
    packet = _read_csv(path)
    if packet.empty:
        return pd.DataFrame(columns=["crash_id", "case_family", "recommended_review_action"])
    keep = [column for column in ["crash_id", "case_family", "recommended_review_action"] if column in packet.columns]
    return packet[keep].copy()


def _packet_flags(mapless_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    assigned_packets = []
    for family, filename in ASSIGNED_PACKET_FILES.items():
        packet = _read_packet(mapless_dir / filename)
        if "case_family" not in packet.columns or packet["case_family"].eq("").all():
            packet["case_family"] = family
        assigned_packets.append(packet)

    assigned = pd.concat(assigned_packets, ignore_index=True, sort=False) if assigned_packets else pd.DataFrame()
    if assigned.empty:
        assigned_flags = pd.DataFrame(columns=["crash_id", "mapless_case_families", "mapless_recommended_action"])
    else:
        assigned_flags = (
            assigned.groupby("crash_id", dropna=False)
            .agg(
                mapless_case_families=("case_family", lambda values: _join_reasons(sorted(set(str(value) for value in values if str(value))))),
                mapless_recommended_action=("recommended_review_action", lambda values: _join_reasons(sorted(set(str(value) for value in values if str(value))))),
            )
            .reset_index()
        )

    unresolved = _read_packet(mapless_dir / UNRESOLVED_PACKET_FILE)
    if unresolved.empty:
        unresolved_flags = pd.DataFrame(columns=["crash_id", "mapless_case_families", "mapless_recommended_action"])
    else:
        unresolved_flags = (
            unresolved.groupby("crash_id", dropna=False)
            .agg(
                mapless_case_families=("case_family", lambda values: _join_reasons(sorted(set(str(value) for value in values if str(value))))),
                mapless_recommended_action=("recommended_review_action", lambda values: _join_reasons(sorted(set(str(value) for value in values if str(value))))),
            )
            .reset_index()
        )
    return assigned_flags, unresolved_flags


def _prepare_assigned(output_root: Path) -> pd.DataFrame:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    assigned = _read_csv(tables / "crash_oriented_segment_bin_assignment.csv")
    segment_enrichment, _eligibility = _build_segment_enrichment(tables, review)
    out = assigned.drop(columns=["geometry"], errors="ignore").merge(
        segment_enrichment.drop(columns=["geometry"], errors="ignore"),
        on="oriented_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    out["distance_to_bin_ft_num"] = _num(out, "distance_to_bin_ft")
    out["assignment_distance_ft_num"] = out["distance_to_bin_ft_num"]
    out["geometry_caveat_class"] = out.apply(_caveat_class, axis=1)
    out["serious_geometry_caveat"] = out.apply(_serious_caveat, axis=1)
    out["confidence_tier"] = out.apply(_confidence_tier, axis=1)
    return out


def _assigned_reason_flags(row: pd.Series) -> tuple[list[str], list[str]]:
    primary_candidates: list[str] = []
    secondary: list[str] = []
    actions = str(row.get("mapless_recommended_action", ""))
    families = str(row.get("mapless_case_families", ""))
    caveat = str(row.get("geometry_caveat_class", ""))
    tier = str(row.get("confidence_tier", ""))
    recovery = str(row.get("recovery_status", ""))
    source = str(row.get("bounded_scaffold_source", ""))
    distance = row.get("assignment_distance_ft_num")

    if "possible_assignment_logic_issue" in actions:
        primary_candidates.append("possible_assignment_logic_issue")
    if pd.notna(distance) and distance > 70:
        primary_candidates.append("assigned_distance_over_70ft")
    if "low_confidence_divided" in families or recovery == "recovered_low_review_only":
        primary_candidates.append("low_confidence_divided_recovery")
    if "signal_association" in families or "signal_association_tolerance" in source:
        primary_candidates.append("provisional_signal_association")
    if caveat == "review_required_unknown_endpoint_junction":
        primary_candidates.append("unknown_endpoint_review_required")
    if "review_parallel_or_divided_ambiguity" in actions:
        primary_candidates.append("parallel_or_divided_ambiguity")
    if pd.notna(distance) and 50 < distance <= 70:
        primary_candidates.append("assigned_distance_50_to_70ft")
    if bool(row.get("serious_geometry_caveat", False)):
        primary_candidates.append("serious_geometry_caveat")
    if caveat == "caveated_valid_dead_end_or_one_sided_boundary":
        secondary.append("valid_dead_end_or_one_sided_boundary")
    if caveat == "method_allowed_anchor_relaxation" or "anchor_relaxation" in source:
        secondary.append("method_allowed_anchor_relaxation")
    if tier.startswith("medium_confidence"):
        secondary.append("medium_confidence_spatial_assignment")
    if tier == "high_confidence_spatial_assignment":
        secondary.append("high_confidence_spatial_assignment")

    if not primary_candidates:
        primary_candidates.append("no_validated_upstream_downstream_interpretation")

    secondary.extend(reason for reason in primary_candidates[1:] if reason)
    return primary_candidates, secondary


def _classify_assigned(row: pd.Series) -> pd.Series:
    actions = str(row.get("mapless_recommended_action", ""))
    tier = str(row.get("confidence_tier", ""))
    caveat = str(row.get("geometry_caveat_class", ""))
    source = str(row.get("bounded_scaffold_source", ""))
    distance = row.get("assignment_distance_ft_num")
    serious = bool(row.get("serious_geometry_caveat", False))

    possible_logic = "possible_assignment_logic_issue" in actions
    manual_review = any(
        action in actions
        for action in [
            "review_unknown_endpoint",
            "review_parallel_or_divided_ambiguity",
            "review_signal_association",
            "exclude_from_directional_now",
            "possible_assignment_logic_issue",
        ]
    )
    high_distance = pd.notna(distance) and distance > 70
    distance_50_70 = pd.notna(distance) and 50 < distance <= 70
    provisional_signal = "signal_association_tolerance" in source
    low_conf_divided = caveat == "high_risk_low_confidence_divided_recovery"
    allowed_caveat = caveat in {
        "no_geometry_caveat",
        "method_allowed_anchor_relaxation",
        "caveated_valid_dead_end_or_one_sided_boundary",
    }
    high_or_medium = tier in {
        "high_confidence_spatial_assignment",
        "medium_confidence_spatial_assignment",
        "medium_confidence_caveated_spatial_assignment",
    }
    spatial_eligible = (
        high_or_medium
        and allowed_caveat
        and not serious
        and not provisional_signal
        and not low_conf_divided
        and not high_distance
        and not possible_logic
        and not distance_50_70
    )
    caveated_review = not spatial_eligible
    manual_review = manual_review or high_distance or low_conf_divided or provisional_signal or caveat == "review_required_unknown_endpoint_junction"

    primary, secondary = _assigned_reason_flags(row)
    recommended = "use_for_spatial_descriptive_only" if spatial_eligible else "hold_for_caveated_spatial_or_manual_review"
    if possible_logic:
        recommended = "audit_assignment_logic_before_analysis"
    elif manual_review:
        recommended = "manual_or_gis_review_before_analysis"

    return pd.Series(
        {
            "spatial_descriptive_eligible": _bool_text(spatial_eligible),
            "caveated_spatial_review": _bool_text(caveated_review),
            "directional_excluded_now": "TRUE",
            "manual_or_gis_review_priority": _bool_text(manual_review),
            "possible_assignment_logic_issue": _bool_text(possible_logic),
            "unresolved_near_scaffold_assignment_gap": "FALSE",
            "primary_exclusion_reason": primary[0],
            "secondary_exclusion_reasons": _join_reasons(secondary),
            "recommended_next_action": recommended,
        }
    )


def _assigned_output_rows(assigned: pd.DataFrame, packet_flags: pd.DataFrame) -> pd.DataFrame:
    out = assigned.merge(packet_flags, on="crash_id", how="left")
    out["mapless_case_families"] = _text(out, "mapless_case_families")
    out["mapless_recommended_action"] = _text(out, "mapless_recommended_action")
    classified = out.apply(_classify_assigned, axis=1)
    out = pd.concat([out, classified], axis=1)
    out["analysis_record_type"] = "assigned_spatial_crash"
    out["segment_id"] = _text(out, "oriented_segment_id")
    out["assignment_distance_ft"] = _num(out, "distance_to_bin_ft").round(3)
    out["nearest_scaffold_distance_ft"] = ""
    out["recovery_source"] = _text(out, "bounded_scaffold_source")
    out["anchor_relaxation_flag"] = out["recovery_source"].str.contains("anchor_relaxation", na=False).map(_bool_text)
    return out


def _unresolved_output_rows(mapless_dir: Path, packet_flags: pd.DataFrame) -> pd.DataFrame:
    packet = _read_csv(mapless_dir / UNRESOLVED_PACKET_FILE)
    if packet.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = packet.copy()
    out = out.drop(columns=["mapless_case_families", "mapless_recommended_action"], errors="ignore").merge(
        packet_flags,
        on="crash_id",
        how="left",
    )
    out["analysis_record_type"] = "unresolved_near_scaffold_gap"
    out["segment_id"] = _text(out, "segment_id")
    out["assignment_distance_ft"] = ""
    out["nearest_scaffold_distance_ft"] = _num(out, "nearest_distance_ft").round(3)
    out["confidence_tier"] = _text(out, "confidence_tier")
    out["recovery_source"] = _text(out, "recovery_source")
    out["anchor_relaxation_flag"] = "FALSE"
    out["spatial_descriptive_eligible"] = "FALSE"
    out["caveated_spatial_review"] = "FALSE"
    out["directional_excluded_now"] = "TRUE"
    out["manual_or_gis_review_priority"] = "TRUE"
    out["possible_assignment_logic_issue"] = _text(out, "mapless_recommended_action").str.contains("possible_assignment_logic_issue", na=False).map(_bool_text)
    out["unresolved_near_scaffold_assignment_gap"] = "TRUE"
    out["primary_exclusion_reason"] = "unresolved_near_scaffold_assignment_gap"
    out["secondary_exclusion_reasons"] = out["possible_assignment_logic_issue"].map(
        lambda value: "possible_assignment_logic_issue" if value == "TRUE" else ""
    )
    out["recommended_next_action"] = out["possible_assignment_logic_issue"].map(
        lambda value: "audit_unresolved_near_scaffold_assignment_gap" if value == "TRUE" else "review_unresolved_near_scaffold_gap"
    )
    return out


def _flag_count(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(_text(frame, column).eq("TRUE").sum())


def _summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    rows.append({"summary_type": "record_count", "name": "all_output_rows", "count": len(frame)})
    rows.append({"summary_type": "record_count", "name": "assigned_spatial_crash_rows", "count": int(_text(frame, "analysis_record_type").eq("assigned_spatial_crash").sum())})
    rows.append({"summary_type": "record_count", "name": "unresolved_near_scaffold_gap_rows", "count": int(_text(frame, "analysis_record_type").eq("unresolved_near_scaffold_gap").sum())})
    for column in [
        "spatial_descriptive_eligible",
        "caveated_spatial_review",
        "directional_excluded_now",
        "manual_or_gis_review_priority",
        "possible_assignment_logic_issue",
        "unresolved_near_scaffold_assignment_gap",
    ]:
        rows.append({"summary_type": "eligibility_flag", "name": column, "count": _flag_count(frame, column)})
    if "primary_exclusion_reason" in frame.columns:
        for reason, count in _text(frame, "primary_exclusion_reason").value_counts().items():
            rows.append({"summary_type": "primary_exclusion_reason", "name": reason, "count": int(count)})
    if "mapless_recommended_action" in frame.columns:
        exploded = frame.assign(mapless_recommended_action=_text(frame, "mapless_recommended_action").str.split("|")).explode("mapless_recommended_action")
        exploded = exploded.loc[_text(exploded, "mapless_recommended_action").ne("")]
        for action, count in _text(exploded, "mapless_recommended_action").value_counts().items():
            rows.append({"summary_type": "mapless_recommended_action", "name": action, "count": int(count)})
    return pd.DataFrame(rows)


def _aggregate(frame: pd.DataFrame, group_column: str) -> pd.DataFrame:
    if frame.empty or group_column not in frame.columns:
        return pd.DataFrame(columns=[group_column])
    out = (
        frame.groupby(group_column, dropna=False)
        .agg(
            output_rows=("crash_id", "count"),
            unique_crashes=("crash_id", "nunique"),
            spatial_descriptive_eligible=("spatial_descriptive_eligible", lambda values: int(values.astype(str).eq("TRUE").sum())),
            caveated_spatial_review=("caveated_spatial_review", lambda values: int(values.astype(str).eq("TRUE").sum())),
            directional_excluded_now=("directional_excluded_now", lambda values: int(values.astype(str).eq("TRUE").sum())),
            manual_or_gis_review_priority=("manual_or_gis_review_priority", lambda values: int(values.astype(str).eq("TRUE").sum())),
            possible_assignment_logic_issue=("possible_assignment_logic_issue", lambda values: int(values.astype(str).eq("TRUE").sum())),
            unresolved_near_scaffold_assignment_gap=("unresolved_near_scaffold_assignment_gap", lambda values: int(values.astype(str).eq("TRUE").sum())),
        )
        .reset_index()
        .sort_values(["manual_or_gis_review_priority", "possible_assignment_logic_issue", "output_rows"], ascending=[False, False, False])
    )
    return out


def _findings_markdown(summary_counts: dict[str, int]) -> str:
    return f"""# Crash Assignment Analysis Eligibility Findings

**Status:** Read-only gatekeeping layer for the current roadway_graph / Step 5 spatial crash assignment.

## Bounded Question

This module converts existing QA, interpretation-readiness, and mapless review packet outputs into conservative analysis eligibility flags. It does not construct roadway scaffold rows, assign crashes, alter assignment logic, infer direction, or classify upstream/downstream status.

## Spatial Descriptive Use

- Spatial descriptive eligible assigned crashes: {summary_counts["spatial_descriptive_eligible"]}
- Caveated spatial review assigned crashes: {summary_counts["caveated_spatial_review"]}
- Method-allowed anchor relaxation remains a traceable flag, not a directional interpretation.

Spatial descriptive eligible rows may support non-directional descriptive summaries of assigned crash occurrence against the current crash-ready scaffold. They should not be used as upstream/downstream, approaching/leaving, or vehicle-direction records.

## Review And Exclusion

- Directional excluded now rows: {summary_counts["directional_excluded_now"]}
- Manual or GIS review priority rows: {summary_counts["manual_or_gis_review_priority"]}
- Possible assignment logic issue rows: {summary_counts["possible_assignment_logic_issue"]}
- Unresolved near-scaffold assignment gaps: {summary_counts["unresolved_near_scaffold_assignment_gap"]}

Unknown endpoint cases, signal-association tolerance cases, low-confidence divided recovery rows, high-distance rows, and unresolved near-scaffold gaps remain blocked for directional analysis. This is a mapless conservative classification, not a manual map conclusion.

## Why Upstream/Downstream Is Still Blocked

The current crash assignment is spatial only. Upstream/downstream interpretation still needs a validated roadway-geometry direction method, accepted divided carriageway pairing where applicable, an explicit undivided-road event-direction method, and reviewed handling for high-priority caveats. Crash direction fields and crash distributions were not used here.

## Next Targeted Technical Audit

The next Codex-native audit should focus on possible assignment logic issue rows, especially assigned crashes over 70 ft and unresolved crashes within 25 ft of crash-ready bins. That audit should compare assignment tolerance, nearest-bin candidate ranking, and duplicate/parallel candidate behavior without repairing scaffold geometry or using crash direction fields.
"""


def build_analysis_eligibility(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    review = output_root / "review/current"
    tables = output_root / "tables/current"
    mapless_dir = output_root / MAPLESS_DIR
    out_dir = output_root / ELIGIBILITY_DIR

    assigned_packet_flags, unresolved_packet_flags = _packet_flags(mapless_dir)
    assigned = _assigned_output_rows(_prepare_assigned(output_root), assigned_packet_flags)
    unresolved_gap = _unresolved_output_rows(mapless_dir, unresolved_packet_flags)
    by_crash = pd.concat([assigned, unresolved_gap], ignore_index=True, sort=False)
    for column in OUTPUT_COLUMNS:
        if column not in by_crash.columns:
            by_crash[column] = ""
    by_crash = by_crash[OUTPUT_COLUMNS].copy()

    summary = _summary(by_crash)
    by_signal = _aggregate(by_crash.loc[_text(by_crash, "reference_signal_id").ne("")].copy(), "reference_signal_id")
    by_segment = _aggregate(by_crash.loc[_text(by_crash, "segment_id").ne("")].copy(), "segment_id")

    output_files = {
        "by_crash": out_dir / "crash_assignment_analysis_eligibility_by_crash.csv",
        "summary": out_dir / "crash_assignment_analysis_eligibility_summary.csv",
        "by_reference_signal": out_dir / "crash_assignment_analysis_eligibility_by_reference_signal.csv",
        "by_segment": out_dir / "crash_assignment_analysis_eligibility_by_segment.csv",
        "spatial_descriptive": out_dir / "spatial_descriptive_eligible_crashes.csv",
        "caveated": out_dir / "caveated_spatial_review_crashes.csv",
        "directional_excluded": out_dir / "directional_excluded_crashes.csv",
        "manual_review": out_dir / "manual_review_priority_cases.csv",
        "possible_logic": out_dir / "possible_assignment_logic_issue_cases.csv",
        "unresolved_gap": out_dir / "unresolved_near_scaffold_assignment_gap_cases.csv",
        "findings": out_dir / "crash_assignment_analysis_eligibility_findings.md",
        "manifest": out_dir / "crash_assignment_analysis_eligibility_manifest.json",
    }

    _write_csv(by_crash, output_files["by_crash"])
    _write_csv(summary, output_files["summary"])
    _write_csv(by_signal, output_files["by_reference_signal"])
    _write_csv(by_segment, output_files["by_segment"])
    _write_csv(by_crash.loc[_text(by_crash, "spatial_descriptive_eligible").eq("TRUE")], output_files["spatial_descriptive"])
    _write_csv(by_crash.loc[_text(by_crash, "caveated_spatial_review").eq("TRUE")], output_files["caveated"])
    _write_csv(by_crash.loc[_text(by_crash, "directional_excluded_now").eq("TRUE")], output_files["directional_excluded"])
    _write_csv(by_crash.loc[_text(by_crash, "manual_or_gis_review_priority").eq("TRUE")], output_files["manual_review"])
    _write_csv(by_crash.loc[_text(by_crash, "possible_assignment_logic_issue").eq("TRUE")], output_files["possible_logic"])
    _write_csv(by_crash.loc[_text(by_crash, "unresolved_near_scaffold_assignment_gap").eq("TRUE")], output_files["unresolved_gap"])

    summary_counts = {
        "spatial_descriptive_eligible": _flag_count(by_crash, "spatial_descriptive_eligible"),
        "caveated_spatial_review": _flag_count(by_crash, "caveated_spatial_review"),
        "directional_excluded_now": _flag_count(by_crash, "directional_excluded_now"),
        "manual_or_gis_review_priority": _flag_count(by_crash, "manual_or_gis_review_priority"),
        "possible_assignment_logic_issue": _flag_count(by_crash, "possible_assignment_logic_issue"),
        "unresolved_near_scaffold_assignment_gap": _flag_count(by_crash, "unresolved_near_scaffold_assignment_gap"),
    }
    _write_text(_findings_markdown(summary_counts), output_files["findings"])

    input_files = [
        tables / "crash_oriented_segment_bin_assignment.csv",
        tables / "signal_oriented_roadway_segments_crash_ready.csv",
        tables / "signal_step5_eligibility.csv",
        tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv",
        tables / "signal_oriented_roadway_segments_role_enriched.csv",
        review / "endpoint_junction_qa" / "endpoint_junction_qa_segment_flags.csv",
        mapless_dir / "mapless_review_recommended_actions.csv",
        *(mapless_dir / filename for filename in ASSIGNED_PACKET_FILES.values()),
        mapless_dir / UNRESOLVED_PACKET_FILE,
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Conservative analysis eligibility flags over existing roadway_graph spatial crash assignment outputs.",
        "read_only": True,
        "raw_crash_data_read": False,
        "current_assigned_crash_table_read": True,
        "current_unresolved_crash_assignment_table_read": False,
        "crash_direction_fields_used": False,
        "crash_distributions_used_for_direction": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
        "geometry_repair_performed": False,
        "upstream_downstream_inferred": False,
        "anything_ready_for_upstream_downstream_interpretation": False,
        "input_files": [str(path) for path in input_files if path.exists()],
        "output_files": [str(path) for path in output_files.values()],
        "summary_counts": summary_counts,
        "primary_exclusion_reason_counts": {
            str(row["name"]): int(row["count"])
            for _, row in summary.loc[summary["summary_type"].eq("primary_exclusion_reason")].iterrows()
        },
    }
    _write_json(manifest, output_files["manifest"])
    return {key: str(path) for key, path in output_files.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create conservative analysis eligibility flags over existing crash assignment QA outputs.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_analysis_eligibility(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
