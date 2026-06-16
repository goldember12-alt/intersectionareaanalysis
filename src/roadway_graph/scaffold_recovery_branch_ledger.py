from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/scaffold_recovery_branch_ledger"

CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"
CONSOLIDATED_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"
FINAL_DIR = OUTPUT_ROOT / "review/current/final_implementable_scaffold_cleanup"
RICHER_DIR = OUTPUT_ROOT / "review/current/insufficient_geometry_evidence_richer_diagnostic"
DIVIDED_DIR = OUTPUT_ROOT / "review/current/divided_carriageway_subbranch_normalization"
ADJACENT_DIR = OUTPUT_ROOT / "review/current/divided_adjacent_bearing_sector_merge"
REMAINING_DIR = OUTPUT_ROOT / "review/current/divided_remaining_implementable_normalization"
RAMP_DIR = OUTPUT_ROOT / "review/current/ramp_slip_lane_unresolved_diagnostic"
READY_CAND_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_recovery_candidates"
READY_CONTEXT_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_context_refresh"
ROUTE_OFFSET_RECOVERY_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_missing_leg_recovery"
ROUTE_OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_context_refresh"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_context_refresh"

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    CALIB_DIR / "calibrated_expected_leg_signal_detail.csv",
    CALIB_DIR / "calibrated_current_vs_expected_alignment.csv",
    CALIB_DIR / "calibrated_expected_leg_distribution.csv",
    CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json",
    CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_expected_alignment.csv",
    CONSOLIDATED_DIR / "under_captured_975_resolution_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json",
    READY_CAND_DIR / "selected_signal_summary.csv",
    READY_CAND_DIR / "candidate_generation_qa_summary.csv",
    READY_CAND_DIR / "skipped_or_conflicting_recovery_targets.csv",
    READY_CAND_DIR / "intersection_zone_missing_leg_recovery_candidates_manifest.json",
    READY_CONTEXT_DIR / "missing_leg_context_signal_summary.csv",
    READY_CONTEXT_DIR / "missing_leg_context_readiness_summary.csv",
    READY_CONTEXT_DIR / "missing_leg_context_refresh_manifest.json",
    ROUTE_OFFSET_RECOVERY_DIR / "route_discontinuity_offset_recovery_summary.csv",
    ROUTE_OFFSET_RECOVERY_DIR / "route_discontinuity_offset_skipped_targets.csv",
    ROUTE_OFFSET_RECOVERY_DIR / "route_discontinuity_offset_recovery_manifest.json",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_signal_summary.csv",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_readiness_summary.csv",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_refresh_manifest.json",
    OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_zone_context_readiness_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_zone_context_refresh_manifest.json",
    DIVIDED_DIR / "divided_subbranch_normalized_signal_summary.csv",
    DIVIDED_DIR / "divided_subbranch_updated_alignment_summary.csv",
    DIVIDED_DIR / "divided_subbranch_normalization_manifest.json",
    ADJACENT_DIR / "adjacent_sector_merge_signal_summary.csv",
    ADJACENT_DIR / "adjacent_sector_merge_updated_alignment.csv",
    ADJACENT_DIR / "divided_adjacent_bearing_sector_merge_manifest.json",
    REMAINING_DIR / "remaining_normalization_signal_summary.csv",
    REMAINING_DIR / "remaining_normalization_updated_alignment.csv",
    REMAINING_DIR / "divided_remaining_implementable_normalization_manifest.json",
    RAMP_DIR / "ramp_slip_unresolved_detail.csv",
    RAMP_DIR / "ramp_slip_lane_unresolved_manifest.json",
    RICHER_DIR / "richer_geometry_signal_detail.csv",
    RICHER_DIR / "richer_geometry_reclassification_summary.csv",
    RICHER_DIR / "richer_geometry_implementation_potential.csv",
    RICHER_DIR / "insufficient_geometry_evidence_richer_manifest.json",
    FINAL_DIR / "final_cleanup_signal_summary.csv",
    FINAL_DIR / "final_cleanup_impact_summary.csv",
    FINAL_DIR / "final_unrecovered_source_limitation_ledger.csv",
    FINAL_DIR / "final_implementable_scaffold_cleanup_manifest.json",
]


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    if lower == "true_vehicle_direction_inferred":
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_text(text: str, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _write_json(payload: dict[str, Any], name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(round(float(text))) if text else default
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _metric(frame: pd.DataFrame, metric: str, default: int = 0) -> int:
    if frame.empty or "metric" not in frame.columns:
        return default
    values = frame.loc[frame["metric"].eq(metric), "value" if "value" in frame.columns else "signal_count"]
    return _int(values.iloc[0], default) if not values.empty else default


def _summary_value(frame: pd.DataFrame, column: str, where_col: str, where_value: str) -> int:
    if frame.empty or column not in frame.columns or where_col not in frame.columns:
        return 0
    values = frame.loc[frame[where_col].eq(where_value), column]
    return _int(values.iloc[0], 0) if not values.empty else 0


def _build_signal_ledger(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    consolidated = data["consolidated_signal"].copy()
    base_cols = [
        "signal_id",
        "source_signal_id_x",
        "source_layer_x",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "consolidated_estimated_physical_leg_count",
        "calibrated_alignment_class",
        "final_review_only_scaffold_alignment_class",
        "consolidated_total_bins",
        "consolidated_recovered_bins",
        "consolidated_speed_aadt_ready_bins",
    ]
    ledger = consolidated[[column for column in base_cols if column in consolidated.columns]].copy()
    ledger = ledger.rename(
        columns={
            "source_signal_id_x": "source_signal_id",
            "source_layer_x": "source_layer",
            "current_refreshed_physical_leg_count": "represented_physical_leg_count_before_recovery",
            "consolidated_estimated_physical_leg_count": "latest_known_physical_leg_count_after_recovery",
            "calibrated_alignment_class": "original_alignment_class",
            "final_review_only_scaffold_alignment_class": "consolidated_alignment_class",
        }
    )
    ledger["branch_assignments"] = ""
    ledger["recovery_streams_applied"] = ""
    ledger["generated_bins_count"] = 0
    ledger["normalized_bin_count"] = 0
    ledger["speed_aadt_context_refresh_status"] = ""
    ledger["final_source_data_limitation_flag"] = False
    ledger["final_holdout_flag"] = False

    branch_sets: dict[str, set[str]] = {"A": set(), "B": set(), "C": set()}
    stream_map: dict[str, list[str]] = {}
    generated_bins: dict[str, int] = {}
    normalized_bins: dict[str, int] = {}
    context_ready: dict[str, list[str]] = {}

    def mark(signal_ids: set[str], branch: str, stream: str) -> None:
        branch_sets[branch].update(signal_ids)
        for sid in signal_ids:
            stream_map.setdefault(sid, []).append(stream)

    ready_context = data["ready_context"]
    route_offset_context = data["route_offset_context"]
    offset_context = data["offset_context"]
    final_signal = data["final_signal"]

    mark(set(ready_context["signal_id"]), "A", "ready_class_missing_leg_context_refresh")
    mark(set(route_offset_context["signal_id"]), "A", "route_discontinuity_offset_context_refresh")
    mark(set(offset_context["signal_id"]), "A", "offset_intersection_zone_context_refresh")
    missing_final = set(final_signal.loc[final_signal["final_cleanup_class"].eq("missing_leg_recovery_candidate_generated"), "signal_id"])
    mark(missing_final, "A", "final_cleanup_missing_leg_candidates_pending_context")

    for frame, bin_col, label in [
        (ready_context, "attempted_bin_count", "ready_class"),
        (route_offset_context, "attempted_bin_count", "route_offset"),
        (offset_context, "attempted_bin_count", "offset_zone"),
    ]:
        for _, row in frame.iterrows():
            sid = row["signal_id"]
            generated_bins[sid] = generated_bins.get(sid, 0) + _int(row.get(bin_col))
            if _bool(row.get("speed_aadt_ready")):
                context_ready.setdefault(sid, []).append(f"{label}_speed_aadt_ready")

    final_bins = final_signal.loc[final_signal["final_cleanup_class"].eq("missing_leg_recovery_candidate_generated")]
    for _, row in final_bins.iterrows():
        sid = row["signal_id"]
        generated_bins[sid] = generated_bins.get(sid, 0) + _int(row.get("recovered_leg_count")) * 20
        context_ready.setdefault(sid, []).append("final_cleanup_needs_context_refresh")

    divided = data["divided_signal"]
    adjacent = data["adjacent_signal"]
    remaining = data["remaining_signal"]
    divided_final = set(final_signal.loc[final_signal["final_cleanup_class"].eq("divided_subbranch_normalized"), "signal_id"])
    mark(set(divided["signal_id"]), "B", "divided_subbranch_normalization")
    mark(set(adjacent["signal_id"]), "B", "adjacent_bearing_sector_merge")
    mark(set(remaining["signal_id"]), "B", "remaining_implementable_normalization")
    mark(divided_final, "B", "final_cleanup_divided_subbranch_normalization")
    for frame, count_col in [
        (divided, "bin_count_preserved"),
        (adjacent, "bins_preserved"),
        (remaining, "bins_preserved"),
    ]:
        if count_col in frame.columns:
            for _, row in frame.iterrows():
                sid = row["signal_id"]
                normalized_bins[sid] = normalized_bins.get(sid, 0) + _int(row.get(count_col))
    for _, row in final_signal.loc[final_signal["final_cleanup_class"].eq("divided_subbranch_normalized")].iterrows():
        sid = row["signal_id"]
        normalized_bins[sid] = normalized_bins.get(sid, 0) + _int(row.get("bins_preserved_or_generated"))

    richer = data["richer_signal"]
    branch_c_classes = {
        "source_limited_holdout",
        "grade_separated_or_mainline_contamination",
        "still_insufficient_geometry_evidence",
    }
    branch_c = set(richer.loc[richer["richer_geometry_reclassification"].isin(branch_c_classes), "signal_id"])
    mark(branch_c, "C", "richer_geometry_source_limitation_or_holdout")
    for _, row in final_signal.loc[final_signal["final_cleanup_class"].isin(branch_c_classes)].iterrows():
        sid = row["signal_id"]
        stream_map.setdefault(sid, []).append("final_source_limitation_ledger")

    def branches_for_signal(sid: str) -> str:
        return "|".join(branch for branch, ids in branch_sets.items() if sid in ids)

    ledger["branch_assignments"] = ledger["signal_id"].map(branches_for_signal)
    ledger["recovery_streams_applied"] = ledger["signal_id"].map(lambda sid: "|".join(dict.fromkeys(stream_map.get(sid, []))))
    ledger["generated_bins_count"] = ledger["signal_id"].map(lambda sid: generated_bins.get(sid, 0)).astype(int)
    ledger["normalized_bin_count"] = ledger["signal_id"].map(lambda sid: normalized_bins.get(sid, 0)).astype(int)
    ledger["speed_aadt_context_refresh_status"] = ledger["signal_id"].map(lambda sid: "|".join(context_ready.get(sid, [])))
    ledger["final_source_data_limitation_flag"] = ledger["signal_id"].isin(branch_c)
    ledger["final_holdout_flag"] = ledger["final_source_data_limitation_flag"]
    ledger["latest_alignment_holdout_class"] = ledger.apply(_final_residual_class, axis=1)
    return ledger


def _final_residual_class(row: pd.Series) -> str:
    streams = str(row.get("recovery_streams_applied", ""))
    branch = str(row.get("branch_assignments", ""))
    consolidated_class = str(row.get("consolidated_alignment_class", ""))
    if row.get("final_source_data_limitation_flag") is True:
        if "grade" in streams or "grade" in consolidated_class:
            return "grade_separated_or_mainline_holdout"
        if "still_insufficient" in streams:
            return "still_insufficient_geometry_evidence"
        return "source_limited_holdout"
    if "final_cleanup_needs_context_refresh" in str(row.get("speed_aadt_context_refresh_status", "")):
        return "needs_final_context_refresh"
    if "A" in branch or "B" in branch:
        return "improved_scaffold_completeness"
    if consolidated_class in {"aligned_after_recovery", "over_split_but_bins_usable"}:
        return "resolved_or_aligned"
    if consolidated_class == "remaining_under_captured_recoverable":
        return "remaining_under_captured_recoverable"
    if consolidated_class == "divided_carriageway_normalization_only":
        return "remaining_divided_normalization_only"
    return "resolved_or_aligned"


def _branch_summaries(data: dict[str, pd.DataFrame], ledger: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ready_candidates = data["ready_candidates"]
    ready_context = data["ready_context"]
    route_offset_recovery = data["route_offset_recovery"]
    route_offset_context = data["route_offset_context"]
    offset_context = data["offset_context"]
    final_impact = data["final_impact"]

    a_rows = [
        {"metric": "starting_direct_recovery_pool", "signal_count": 263 + 189 + 147, "note": "Ready-class, route/facility+offset, and offset/intersection-zone direct recovery streams; not deduped."},
        {"metric": "ready_class_targeted", "signal_count": ready_candidates["signal_id"].nunique(), "note": "ready_for_intersection_zone_missing_leg_recovery selected signal summary."},
        {"metric": "ready_class_context_refreshed", "signal_count": ready_context["signal_id"].nunique(), "note": "Generated ready-class candidates processed through context refresh."},
        {"metric": "route_facility_offset_targeted", "signal_count": _summary_value(route_offset_recovery, "target_signal_count", "recovery_class", "total"), "note": "Route/facility discontinuity plus offset-anchor missing-leg recovery."},
        {"metric": "route_facility_offset_context_refreshed", "signal_count": route_offset_context["signal_id"].nunique(), "note": "Generated route/facility and offset-anchor candidates context refreshed."},
        {"metric": "offset_zone_context_refreshed", "signal_count": offset_context["signal_id"].nunique(), "note": "Offset/intersection-zone staged recovery context refresh."},
        {"metric": "final_cleanup_missing_leg_signals_pending_context", "signal_count": _metric(final_impact, "missing_leg_recovered_signals"), "note": "Final cleanup generated missing-leg candidates; context refresh not yet run."},
    ]
    branch_a = pd.DataFrame(a_rows)
    branch_a["branch_status_class"] = "branch_complete_pending_final_context_refresh"

    divided_alignment = data["divided_alignment"]
    adjacent_alignment = data["adjacent_alignment"]
    remaining_alignment = data["remaining_alignment"]
    b_rows = [
        {"metric": "starting_divided_normalization_only", "signal_count": _summary_value(divided_alignment, "signal_count", "metric", "starting_divided_carriageway_normalization_only"), "note": "Initial Branch B target set."},
        {"metric": "divided_subbranch_normalized_successfully", "signal_count": _summary_value(divided_alignment, "signal_count", "metric", "normalized_successfully"), "note": "First divided subbranch normalization pass."},
        {"metric": "adjacent_sector_merged", "signal_count": _summary_value(adjacent_alignment, "signal_count", "metric", "merged_to_expected_physical_leg_count"), "note": "Adjacent bearing-sector merge pass."},
        {"metric": "remaining_implementable_normalized", "signal_count": _summary_value(remaining_alignment, "signal_count", "metric", "normalized_to_expected_physical_leg_count"), "note": "Candidate branch, source-line split, and ramp/slip partial pass."},
        {"metric": "final_divided_subbranch_normalized", "signal_count": _metric(final_impact, "normalized_divided_subbranch_signals"), "note": "Final cleanup divided/subbranch labels."},
        {"metric": "remaining_divided_or_geometry_backlog_after_final_cleanup", "signal_count": _metric(final_impact, "remaining_source_data_limitation_signals"), "note": "No low-risk Branch B normalization remains; residuals are Branch C/holdout."},
    ]
    branch_b = pd.DataFrame(b_rows)
    branch_b["branch_status_class"] = "branch_complete"

    ledger_source = data["source_ledger"]
    c_rows = [
        {"metric": "branch_c_target_pool", "signal_count": data["richer_signal"]["signal_id"].nunique(), "note": "Insufficient-geometry plus ramp/slip unresolved target pool."},
        {"metric": "implementable_cases_extracted", "signal_count": _metric(final_impact, "normalized_divided_subbranch_signals") + _metric(final_impact, "missing_leg_recovered_signals"), "note": "Branch C cases extracted and completed by final cleanup."},
        {"metric": "source_limited_holdout", "signal_count": _summary_value(ledger_source, "signal_count", "unrecovered_class", "source_limited_holdout"), "note": "Source Travelway evidence below expected physical-leg count."},
        {"metric": "grade_separated_or_mainline_holdout", "signal_count": _summary_value(ledger_source, "signal_count", "unrecovered_class", "grade_separated_or_mainline_contamination"), "note": "2D proximity risky for signal-control plane."},
        {"metric": "still_insufficient_geometry_evidence", "signal_count": _summary_value(ledger_source, "signal_count", "unrecovered_class", "still_insufficient_geometry_evidence"), "note": "Ambiguous after richer geometry diagnostic."},
    ]
    branch_c = pd.DataFrame(c_rows)
    branch_c["branch_status_class"] = "branch_open_manual_or_external_data_only"

    summary = pd.DataFrame(
        [
            {"branch": "A_direct_missing_leg_recovery", "branch_status_class": "branch_complete_pending_final_context_refresh", "starting_pool": 263 + 189 + 147, "completed_or_context_refreshed_signals": ready_context["signal_id"].nunique() + route_offset_context["signal_id"].nunique() + offset_context["signal_id"].nunique(), "open_implementable_work": _metric(final_impact, "missing_leg_recovered_signals"), "remaining_holdout_or_manual": 0},
            {"branch": "B_divided_carriageway_normalization", "branch_status_class": "branch_complete", "starting_pool": _summary_value(divided_alignment, "signal_count", "metric", "starting_divided_carriageway_normalization_only"), "completed_or_context_refreshed_signals": _summary_value(divided_alignment, "signal_count", "metric", "normalized_successfully") + _summary_value(adjacent_alignment, "signal_count", "metric", "merged_to_expected_physical_leg_count") + _summary_value(remaining_alignment, "signal_count", "metric", "normalized_to_expected_physical_leg_count") + _metric(final_impact, "normalized_divided_subbranch_signals"), "open_implementable_work": 0, "remaining_holdout_or_manual": _metric(final_impact, "remaining_source_data_limitation_signals")},
            {"branch": "C_source_limitation_holdout", "branch_status_class": "branch_open_manual_or_external_data_only", "starting_pool": data["richer_signal"]["signal_id"].nunique(), "completed_or_context_refreshed_signals": _metric(final_impact, "normalized_divided_subbranch_signals") + _metric(final_impact, "missing_leg_recovered_signals"), "open_implementable_work": 0, "remaining_holdout_or_manual": _metric(final_impact, "remaining_source_data_limitation_signals")},
        ]
    )
    return summary, branch_a, branch_b, branch_c


def _residual_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    return (
        ledger.groupby("latest_alignment_holdout_class", dropna=False)
        .agg(
            signal_count=("signal_id", "nunique"),
            generated_bins=("generated_bins_count", "sum"),
            normalized_bins=("normalized_bin_count", "sum"),
        )
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )


def _exhaustion_decision(branch_summary: pd.DataFrame, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    final_impact = data["final_impact"]
    pending = _metric(final_impact, "missing_leg_recovered_signals")
    return pd.DataFrame(
        [
            {
                "decision_area": "next_pass",
                "recommended_next_pass": "final_context_refresh_for_final_cleanup_bins",
                "reason": f"{pending} final cleanup missing-leg signals have review-only generated bins that still need route/measure, roadway context, speed, and AADT refresh.",
            },
            {
                "decision_area": "scaffold_recovery_exhaustion",
                "recommended_next_pass": "then_resume_access_catchment_work",
                "reason": "Branch B low-risk normalization is complete and Branch C residuals are source/manual holdouts; access can resume after final cleanup bins get context readiness.",
            },
            {
                "decision_area": "manual_or_external_data",
                "recommended_next_pass": "do_not_force_remaining_holdouts",
                "reason": "Remaining losses are source-limited, grade/mainline, or still-insufficient geometry evidence classes.",
            },
        ]
    )


def _write_findings(branch_summary: pd.DataFrame, branch_c: pd.DataFrame, final_impact: pd.DataFrame) -> None:
    pending = _metric(final_impact, "missing_leg_recovered_signals")
    holdouts = _metric(final_impact, "remaining_source_data_limitation_signals")
    text = f"""# Scaffold Recovery Branch Ledger

## Bounded Question

Where are we in the scaffold-recovery decision tree, and is the remaining work implementable or source/manual holdout?

## Decision Tree

- Branch A: direct missing-leg recovery.
- Branch B: divided/carriageway and over-split normalization.
- Branch C: insufficient geometry, source limitation, grade/mainline, and manual holdout.

## Branch Status

- Branch A is complete pending final context refresh: the final cleanup generated missing-leg candidates for {pending:,} signals, but those bins still need route/measure, roadway context, speed, and AADT refresh.
- Branch B is complete for low-risk implementable normalization rules.
- Branch C has been reduced to source/manual holdouts, with {holdouts:,} source/data limitation signals ledgered.

## Next Action

Run final context refresh for the final cleanup missing-leg bins. After that, scaffold recovery is exhausted enough to resume access/catchment work with source-limitation and grade/mainline QA flags carried forward.
"""
    _write_text(text, "scaffold_recovery_branch_ledger_findings.md")


def _write_qa(ledger: pd.DataFrame) -> None:
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/scaffold_recovery_branch_ledger."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "Ledger/audit only; no promotion is performed."},
            {"qa_check": "no_access_or_crash_assignment", "status": "pass", "detail": "No access/crash inputs are read and no assignments are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate or model calculations are run."},
            {"qa_check": "no_new_bins_generated", "status": "pass", "detail": "This script only reads existing recovery outputs and writes ledger summaries."},
            {"qa_check": "deduped_signal_counts_separate", "status": "pass", "detail": f"Signal ledger contains {ledger['signal_id'].nunique():,} deduplicated signals; bin counts are separate columns."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"Outputs written under {OUT_DIR}."},
        ]
    )
    _write_csv(qa, "scaffold_recovery_branch_ledger_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = [path for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(str(path) for path in missing))

    data = {
        "calib_signal": _read_csv(CALIB_DIR / "calibrated_expected_leg_signal_detail.csv"),
        "calib_alignment": _read_csv(CALIB_DIR / "calibrated_current_vs_expected_alignment.csv"),
        "calib_distribution": _read_csv(CALIB_DIR / "calibrated_expected_leg_distribution.csv"),
        "consolidated_signal": _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv"),
        "consolidated_alignment": _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_expected_alignment.csv"),
        "under_captured_resolution": _read_csv(CONSOLIDATED_DIR / "under_captured_975_resolution_summary.csv"),
        "ready_candidates": _read_csv(READY_CAND_DIR / "selected_signal_summary.csv"),
        "ready_context": _read_csv(READY_CONTEXT_DIR / "missing_leg_context_signal_summary.csv"),
        "route_offset_recovery": _read_csv(ROUTE_OFFSET_RECOVERY_DIR / "route_discontinuity_offset_recovery_summary.csv"),
        "route_offset_context": _read_csv(ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_signal_summary.csv"),
        "offset_context": _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv"),
        "divided_signal": _read_csv(DIVIDED_DIR / "divided_subbranch_normalized_signal_summary.csv"),
        "divided_alignment": _read_csv(DIVIDED_DIR / "divided_subbranch_updated_alignment_summary.csv"),
        "adjacent_signal": _read_csv(ADJACENT_DIR / "adjacent_sector_merge_signal_summary.csv"),
        "adjacent_alignment": _read_csv(ADJACENT_DIR / "adjacent_sector_merge_updated_alignment.csv"),
        "remaining_signal": _read_csv(REMAINING_DIR / "remaining_normalization_signal_summary.csv"),
        "remaining_alignment": _read_csv(REMAINING_DIR / "remaining_normalization_updated_alignment.csv"),
        "ramp_detail": _read_csv(RAMP_DIR / "ramp_slip_unresolved_detail.csv"),
        "richer_signal": _read_csv(RICHER_DIR / "richer_geometry_signal_detail.csv"),
        "richer_potential": _read_csv(RICHER_DIR / "richer_geometry_implementation_potential.csv"),
        "final_signal": _read_csv(FINAL_DIR / "final_cleanup_signal_summary.csv"),
        "final_impact": _read_csv(FINAL_DIR / "final_cleanup_impact_summary.csv"),
        "source_ledger": _read_csv(FINAL_DIR / "final_unrecovered_source_limitation_ledger.csv"),
    }

    ledger = _build_signal_ledger(data)
    branch_summary, branch_a, branch_b, branch_c = _branch_summaries(data, ledger)
    residual = _residual_summary(ledger)
    decision = _exhaustion_decision(branch_summary, data)

    _write_csv(ledger, "scaffold_recovery_branch_ledger_signal_detail.csv")
    _write_csv(branch_summary, "scaffold_recovery_branch_summary.csv")
    _write_csv(branch_a, "branch_a_direct_missing_leg_summary.csv")
    _write_csv(branch_b, "branch_b_divided_normalization_summary.csv")
    _write_csv(branch_c, "branch_c_source_limitation_summary.csv")
    _write_csv(residual, "final_recovery_residual_class_summary.csv")
    _write_csv(decision, "scaffold_recovery_exhaustion_decision.csv")
    _write_findings(branch_summary, branch_c, data["final_impact"])
    _write_qa(ledger)

    manifest = {
        "script": "src.roadway_graph.scaffold_recovery_branch_ledger",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Audit scaffold-recovery branch completion and residual source/data limitations.",
        "output_directory": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "scaffold_recovery_branch_ledger_signal_detail.csv",
            "scaffold_recovery_branch_summary.csv",
            "branch_a_direct_missing_leg_summary.csv",
            "branch_b_divided_normalization_summary.csv",
            "branch_c_source_limitation_summary.csv",
            "final_recovery_residual_class_summary.csv",
            "scaffold_recovery_exhaustion_decision.csv",
            "scaffold_recovery_branch_ledger_findings.md",
            "scaffold_recovery_branch_ledger_qa.csv",
            "scaffold_recovery_branch_ledger_manifest.json",
            "run_progress_log.txt",
        ],
        "summary": {
            "represented_signal_count": int(ledger["signal_id"].nunique()),
            "branch_summary": branch_summary.to_dict(orient="records"),
            "residual_summary": residual.to_dict(orient="records"),
            "recommended_next_pass": "final_context_refresh_for_final_cleanup_bins",
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assignment": False,
            "rates_or_models": False,
            "new_bins_generated": False,
            "ledger_audit_only": True,
            "review_only": True,
        },
        "upstream_manifests": {
            "calibrated_expected": _load_json(CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json").get("created_at_utc", ""),
            "consolidated_scaffold": _load_json(CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json").get("created_at_utc", ""),
            "final_cleanup": _load_json(FINAL_DIR / "final_implementable_scaffold_cleanup_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "scaffold_recovery_branch_ledger_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
