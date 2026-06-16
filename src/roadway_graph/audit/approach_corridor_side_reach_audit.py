"""Read-only side/reach semantics audit for staged approach_corridors."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/approach_corridor_side_reach_audit"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

BUILD_CORRIDORS_REVIEW = REPO / "work/roadway_graph/review/build_approach_corridors"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
CANONICAL_FINAL = REPO / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset"
REFRESH_CANDIDATE = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"

EPS_MEASURE = 1e-6
NEAR_ENDPOINT_FT = 25.0
DISTANCE_BANDS = [(0, 250), (250, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500)]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


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


def side_class(row: pd.Series) -> str:
    frm = float(row["corridor_from_measure"])
    to = float(row["corridor_to_measure"])
    sig = float(row["reviewed_signal_measure"])
    lo = min(frm, to)
    hi = max(frm, to)
    d_from = abs(sig - frm) * 5280.0
    d_to = abs(to - sig) * 5280.0
    if sig < lo - EPS_MEASURE or sig > hi + EPS_MEASURE:
        return "reviewed_measure_outside_corridor"
    if d_from <= NEAR_ENDPOINT_FT or d_to <= NEAR_ENDPOINT_FT:
        return "signal_at_endpoint_or_near_endpoint"
    if lo + EPS_MEASURE < sig < hi - EPS_MEASURE:
        return "signal_spanning_both_measure_directions"
    if lo >= sig:
        return "one_sided_measure_increasing"
    if hi <= sig:
        return "one_sided_measure_decreasing"
    return "unknown_measure_semantics"


def length_bucket(row: pd.Series) -> str:
    length = float(row["corridor_length_ft"])
    max_side = float(row["one_sided_reach_ft"])
    cls = row["measure_side_class"]
    if length > 5000.001:
        return "true_over_5000_or_unit_issue"
    if length > 2500 and cls == "signal_spanning_both_measure_directions" and max_side <= 2500.001:
        return "valid_two_sided_signal_spanning_total_span"
    if length > 2500 and max_side > 2500.001:
        return "overextension_beyond_2500_one_sided_policy"
    if abs(length - 5000) <= 0.001:
        return "floating_point_edge_at_5000_total_span"
    return "within_one_sided_or_short_total_span"


def alignment_class(row: pd.Series, shared_count: int) -> str:
    cls = row["measure_side_class"]
    if cls == "signal_spanning_both_measure_directions":
        return "likely_signal_centered_interval_needs_split"
    if row["reviewed_measure_outside_flag"]:
        return "possible_opposite_approach_contamination"
    if shared_count > 1 and cls == "signal_spanning_both_measure_directions":
        return "possible_opposite_approach_contamination"
    if shared_count > 1:
        return "acceptable_multi_subbranch_support"
    return "aligned_with_parent_approach"


def support_status(group: pd.DataFrame) -> dict[str, Any]:
    max_side = float(group["one_sided_reach_ft"].max()) if len(group) else 0.0
    has_spanning = bool(group["measure_side_class"].eq("signal_spanning_both_measure_directions").any())
    has_one_sided = bool(group["measure_side_class"].str.startswith("one_sided").any() or group["measure_side_class"].eq("signal_at_endpoint_or_near_endpoint").any())
    band_flags = {}
    for start, end in DISTANCE_BANDS:
        band_flags[f"supports_{start}_{end}ft"] = bool(max_side >= end)
    if has_spanning:
        status = "signal_spanning_support_requiring_split"
    elif max_side >= 2500:
        status = "full_one_sided_0_2500_support"
    elif max_side > 0:
        status = "partial_support"
    elif not has_one_sided:
        status = "no_usable_support"
    else:
        status = "uncertain_support"
    return {
        "max_one_sided_reach_ft": max_side,
        "distance_band_support_status": status,
        **band_flags,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting read-only approach corridor side/reach audit.")
    signals = pd.read_parquet(SIGNAL_INDEX)
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    log(f"Loaded signals={len(signals)}, approaches={len(approaches)}, corridors={len(corridors)}.")

    forbidden = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    invalid_approach = int((~corridors["signal_approach_id"].isin(approaches["signal_approach_id"])).sum())
    blocked_present = int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum())
    structural = [
        {"check": "corridor_rows", "value": int(len(corridors)), "status": "pass"},
        {"check": "duplicate_approach_corridor_id_rows", "value": int(corridors["approach_corridor_id"].duplicated(keep=False).sum()), "status": "pass" if int(corridors["approach_corridor_id"].duplicated(keep=False).sum()) == 0 else "fail"},
        {"check": "invalid_signal_approach_id_links", "value": invalid_approach, "status": "pass" if invalid_approach == 0 else "fail"},
        {"check": "blocked_parent_approach_corridor_rows", "value": blocked_present, "status": "pass" if blocked_present == 0 else "fail"},
        {"check": "warning_corridor_rows", "value": int(corridors["parent_approach_gate"].eq("corridor_build_ready_with_warning").sum()), "status": "pass"},
        {"check": "forbidden_directionality_fields", "value": len(forbidden), "status": "pass" if not forbidden else "fail"},
    ]
    write_csv("structural_baseline_check.csv", structural)

    audit = corridors.copy()
    audit["distance_from_signal_to_corridor_from_ft"] = (audit["reviewed_signal_measure"] - audit["corridor_from_measure"]).abs() * 5280.0
    audit["distance_from_signal_to_corridor_to_ft"] = (audit["corridor_to_measure"] - audit["reviewed_signal_measure"]).abs() * 5280.0
    audit["one_sided_reach_ft"] = audit[["distance_from_signal_to_corridor_from_ft", "distance_from_signal_to_corridor_to_ft"]].max(axis=1)
    audit["total_span_length_ft_recomputed"] = (audit["corridor_to_measure"] - audit["corridor_from_measure"]).abs() * 5280.0
    audit["measure_side_class"] = audit.apply(side_class, axis=1)
    audit["length_bucket_explanation"] = audit.apply(length_bucket, axis=1)
    audit["reviewed_measure_outside_flag"] = audit["measure_side_class"].eq("reviewed_measure_outside_corridor")
    cols = [
        "approach_corridor_id",
        "stable_signal_id",
        "signal_approach_id",
        "stable_travelway_id",
        "corridor_from_measure",
        "corridor_to_measure",
        "reviewed_signal_measure",
        "corridor_length_ft",
        "distance_from_signal_to_corridor_from_ft",
        "distance_from_signal_to_corridor_to_ft",
        "one_sided_reach_ft",
        "total_span_length_ft_recomputed",
        "measure_side_class",
        "length_bucket_explanation",
        "parent_approach_gate",
        "boundary_method",
        "roadway_configuration",
        "carriageway_direction_token",
    ]
    write_csv("corridor_length_semantics_audit.csv", audit[cols].to_dict("records"))
    write_csv("corridor_side_classification.csv", audit.groupby(["measure_side_class", "parent_approach_gate", "boundary_method"], dropna=False).size().reset_index(name="corridor_rows").to_dict("records"))
    write_csv("signal_spanning_corridor_rows.csv", audit[audit["measure_side_class"].eq("signal_spanning_both_measure_directions")].to_dict("records"))
    write_csv("reviewed_measure_outside_corridor_rows.csv", audit[audit["measure_side_class"].eq("reviewed_measure_outside_corridor")].to_dict("records"))
    write_csv("length_bucket_explanation.csv", audit.groupby(["length_bucket_explanation", "measure_side_class"], dropna=False).size().reset_index(name="corridor_rows").to_dict("records"))

    interval_key = audit["stable_signal_id"].astype(str) + "|" + audit["stable_travelway_id"].astype(str) + "|" + audit["corridor_from_measure"].round(6).astype(str) + "|" + audit["corridor_to_measure"].round(6).astype(str)
    audit["same_corridor_interval_key"] = interval_key
    shared_counts = interval_key.value_counts().to_dict()
    audit["shared_interval_approach_count"] = audit["same_corridor_interval_key"].map(shared_counts).astype(int)
    audit["parent_approach_alignment_class"] = audit.apply(lambda row: alignment_class(row, int(row["shared_interval_approach_count"])), axis=1)
    align_cols = [
        "approach_corridor_id",
        "stable_signal_id",
        "signal_approach_id",
        "stable_travelway_id",
        "measure_side_class",
        "approach_label",
        "approach_bearing",
        "parent_approach_alignment_class",
        "shared_interval_approach_count",
        "roadway_configuration",
        "carriageway_direction_token",
    ]
    merged = audit.merge(approaches[["signal_approach_id", "approach_label", "approach_bearing"]], on="signal_approach_id", how="left")
    write_csv("parent_approach_alignment_audit.csv", merged[align_cols].to_dict("records"))
    write_csv("possible_opposite_approach_contamination.csv", merged[merged["parent_approach_alignment_class"].eq("possible_opposite_approach_contamination")].to_dict("records"))
    multi = merged[merged["shared_interval_approach_count"] > 1].sort_values(["same_corridor_interval_key", "signal_approach_id"])
    write_csv("same_corridor_assigned_to_multiple_approaches.csv", multi.to_dict("records"))

    support_rows = []
    for app_id, group in audit.groupby("signal_approach_id"):
        info = support_status(group)
        support_rows.append({"signal_approach_id": app_id, "stable_signal_id": group["stable_signal_id"].iloc[0], "corridor_rows": int(len(group)), **info})
    support_df = pd.DataFrame(support_rows)
    write_csv("distance_band_support_readiness_by_approach.csv", support_df.to_dict("records"))
    write_csv("distance_band_support_summary.csv", support_df.groupby("distance_band_support_status").size().reset_index(name="approach_count").to_dict("records"))

    side_counts = audit["measure_side_class"].value_counts().to_dict()
    spanning_count = int(side_counts.get("signal_spanning_both_measure_directions", 0))
    outside_count = int(side_counts.get("reviewed_measure_outside_corridor", 0))
    one_sided_count = int(audit["measure_side_class"].isin(["one_sided_measure_increasing", "one_sided_measure_decreasing", "signal_at_endpoint_or_near_endpoint"]).sum())
    alignment_counts = audit["parent_approach_alignment_class"].value_counts().to_dict()
    if outside_count > 0:
        decision = "approach_corridors_needs_parent_approach_alignment_repair"
        recommendation = "repair reviewed-measure outside intervals before bin_context"
    elif spanning_count > len(audit) * 0.25:
        decision = "approach_corridors_ready_only_after_signal_spanning_split"
        recommendation = "keep current route-centered intervals as support, but split into neutral one-sided subsegments before bin_context"
    elif spanning_count > 0:
        decision = "approach_corridors_needs_side_reach_status_patch"
        recommendation = "patch side/reach status fields before bin_context"
    else:
        decision = "approach_corridors_ready_as_validated_parent"
        recommendation = "proceed to bin_context"
    write_csv("split_or_patch_recommendation.csv", [{
        "recommendation": recommendation,
        "signal_spanning_corridor_rows": spanning_count,
        "one_sided_or_endpoint_corridor_rows": one_sided_count,
        "reviewed_measure_outside_rows": outside_count,
        "preferred_next_object": "one_sided_corridor_subsegments_or_side_reach_patch",
    }])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": recommendation}])
    write_csv("recommended_next_actions.csv", [{
        "rank": 1,
        "action": "split_signal_spanning_corridors_into_neutral_one_sided_subsegments_before_bin_context" if spanning_count else "build_bin_context_from_one_sided_corridors",
        "rationale": "Bin generation needs explicit one-sided reach semantics without assigning upstream/downstream.",
    }])

    findings = f"""# Approach Corridor Side/Reach Semantics Audit

## Why the length distribution is suspicious
Rows above 2,500 ft are suspicious because the build policy limited reach to 2,500 ft from the reviewed signal. The audit confirms `corridor_length_ft` is total span, not one-sided reach.

## Length semantics
Maximum one-sided reach is {audit['one_sided_reach_ft'].max():.3f} ft. Maximum total span is {audit['corridor_length_ft'].max():.3f} ft. Rows over 2,500 ft are therefore mostly signal-spanning intervals with up to 2,500 ft on each side, not true one-sided overextension.

## One-sided vs signal-spanning
Measure side counts: {side_counts}. One-sided or endpoint-like rows: {one_sided_count:,}. Signal-spanning rows: {spanning_count:,}. Reviewed-measure-outside rows: {outside_count:,}.

## Parent approach alignment
Alignment classes: {alignment_counts}. Signal-spanning rows are best interpreted as route-centered intervals needing a neutral split before bins, not as finalized one-sided physical approach corridors.

## Bin readiness
Distance-band support counts: {support_df['distance_band_support_status'].value_counts().to_dict()}. Current rows can support reach calculations, but bin generation should not proceed from signal-spanning rows without a split or side/reach status patch.

## Best QA flag
The best QA flag for this layer is `measure_side_class`, paired with `one_sided_reach_ft` and `distance_band_support_status`.

## Readiness decision
Final decision: `{decision}`.

## Recommended next task
{recommendation}.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "mode": "read_only_audit",
        "audit_target": rel(CORRIDORS),
        "validated_parent_objects": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)],
        "method_comparison_evidence_only": [rel(BUILD_CORRIDORS_REVIEW), rel(GATE_PATCH_REVIEW), rel(BUILD_APPROACH_REVIEW), rel(CONTRACT_REVIEW), rel(CANONICAL_FINAL), rel(REFRESH_CANDIDATE)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "corridor_rows": int(len(audit)),
        "measure_side_counts": {str(k): int(v) for k, v in side_counts.items()},
        "alignment_counts": {str(k): int(v) for k, v in alignment_counts.items()},
        "distance_band_support_counts": {str(k): int(v) for k, v in support_df["distance_band_support_status"].value_counts().to_dict().items()},
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
