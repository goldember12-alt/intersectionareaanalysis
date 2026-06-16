from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
SPEED_V3_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v3_route_assisted"
OUTPUT_DIR = OUTPUT_ROOT / "review/current/speed_context_v3_readiness_qa"

BIN_CONTEXT_FILE = SPEED_V3_DIR / "directional_bin_speed_context_v3.csv"
CRASH_CONTEXT_FILE = SPEED_V3_DIR / "directional_crash_speed_context_v3.csv"
JOIN_SUMMARY_FILE = SPEED_V3_DIR / "speed_context_v3_summary.csv"
PAIRED_QA_FILE = SPEED_V3_DIR / "speed_paired_pseudo_direction_consistency_qa_v3.csv"
CRASH_READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"

LEGACY_STABLE_STATUS = "stable_speed_assigned_route_match"
STABLE_SINGLE_STATUS = "stable_single_speed"
STABLE_WEIGHTED_STATUS = "stable_weighted_speed_transition"
REVIEW_UNRESOLVED_STATUS = "review_unresolved_speed_conflict"
MISSING_STATUS = "missing_no_route_compatible_speed"
ROUTE_MISMATCH_STATUS = "review_route_mismatch"
ROUTE_MISSING_STATUS = "review_route_missing"
EXPECTED_STATUSES = {
    STABLE_SINGLE_STATUS,
    STABLE_WEIGHTED_STATUS,
    REVIEW_UNRESOLVED_STATUS,
    MISSING_STATUS,
    ROUTE_MISMATCH_STATUS,
    ROUTE_MISSING_STATUS,
}
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)


def _read_csv(path: Path, *, guard_crash_direction_fields: bool = False) -> pd.DataFrame:
    if guard_crash_direction_fields:
        header = pd.read_csv(path, nrows=0).columns.tolist()
        blocked = [column for column in header if any(token in column.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)]
        if blocked:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _distance_window(frame: pd.DataFrame) -> pd.Series:
    if "distance_window" in frame.columns:
        values = frame["distance_window"].fillna("").astype(str)
        return values.replace(
            {
                "high_priority_0_1000ft": "0_to_1000ft",
                "sensitivity_1000_2500ft": "1000_to_2500ft",
            }
        )
    midpoint = _num(frame, "bin_midpoint_ft_from_reference_signal")
    return pd.Series(
        pd.NA,
        index=frame.index,
        dtype="object",
    ).mask(midpoint.le(1000), "0_to_1000ft").mask(midpoint.gt(1000) & midpoint.le(2500), "1000_to_2500ft").fillna("outside_0_to_2500ft")


def _share(count: int, total: int) -> float:
    return round(count / total, 6) if total else 0.0


def _coverage_by(bin_context: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    work = bin_context.copy()
    grouped = (
        work.groupby(columns, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            stable_speed_bin_count=("is_stable_speed_context", "sum"),
            stable_single_speed_bin_count=("is_stable_single_speed_context", "sum"),
            stable_weighted_transition_bin_count=("is_stable_weighted_speed_context", "sum"),
            review_unresolved_conflict_bin_count=("is_review_speed_context", "sum"),
            missing_speed_bin_count=("is_missing_speed_context", "sum"),
            weighted_speed_bin_count=("weighted_speed_context_flag_bool", "sum"),
            severe_conflict_bin_count=("is_severe_conflict", "sum"),
        )
        .reset_index()
    )
    grouped["stable_speed_share"] = grouped.apply(lambda row: _share(int(row["stable_speed_bin_count"]), int(row["bin_count"])), axis=1)
    grouped["missing_speed_share"] = grouped.apply(lambda row: _share(int(row["missing_speed_bin_count"]), int(row["bin_count"])), axis=1)
    return grouped.sort_values(columns)


def _crash_context_by_window(crash_context: pd.DataFrame) -> pd.DataFrame:
    columns = ["qa_distance_window", "signal_relative_direction", "roadway_representation_type"]
    grouped = (
        crash_context.groupby(columns, dropna=False)
        .agg(
            crash_count=("crash_id", "nunique"),
            crashes_inheriting_stable_speed=("is_stable_speed_context", "sum"),
            crashes_inheriting_stable_weighted_speed=("is_stable_weighted_speed_context", "sum"),
            crashes_inheriting_review_unresolved_conflict_speed=("is_review_speed_context", "sum"),
            crashes_inheriting_missing_speed=("is_missing_speed_context", "sum"),
        )
        .reset_index()
    )
    grouped["stable_speed_crash_share"] = grouped.apply(lambda row: _share(int(row["crashes_inheriting_stable_speed"]), int(row["crash_count"])), axis=1)
    return grouped.sort_values(columns)


def _crash_context_by_posted_speed(crash_context: pd.DataFrame) -> pd.DataFrame:
    work = crash_context.copy()
    speed_field = "posted_car_speed_limit_context_value" if "posted_car_speed_limit_context_value" in work.columns else "dominant_car_speed_limit"
    work["posted_speed_value"] = work[speed_field].where(work[speed_field].astype(str).ne(""), "missing_or_review")
    columns = ["qa_distance_window", "signal_relative_direction", "roadway_representation_type", "posted_speed_value"]
    grouped = (
        work.groupby(columns, dropna=False)
        .agg(
            crash_count=("crash_id", "nunique"),
            stable_speed_crash_count=("is_stable_speed_context", "sum"),
        )
        .reset_index()
    )
    return grouped.sort_values(["qa_distance_window", "signal_relative_direction", "roadway_representation_type", "posted_speed_value"])


def _missing_diagnostic(bin_context: pd.DataFrame) -> pd.DataFrame:
    missing = bin_context.loc[bin_context["is_missing_speed_context"]].copy()
    if missing.empty:
        return pd.DataFrame(columns=["qa_distance_window", "roadway_representation_type", "reference_signal_id", "far_anchor_type", "missing_speed_bin_count"])
    return (
        missing.groupby(["qa_distance_window", "roadway_representation_type", "reference_signal_id", "far_anchor_type"], dropna=False)
        .agg(
            missing_speed_bin_count=("reference_directional_bin_id", "nunique"),
            affected_source_bin_count=("source_bin_key", "nunique"),
        )
        .reset_index()
        .sort_values(["missing_speed_bin_count", "reference_signal_id"], ascending=[False, True])
    )


def _conflict_diagnostic(bin_context: pd.DataFrame) -> pd.DataFrame:
    conflicts = bin_context.loc[bin_context["is_review_speed_context"]].copy()
    transitions = bin_context.loc[bin_context["is_stable_weighted_speed_context"]].copy()
    frames = []
    if not conflicts.empty:
        conflicts["speed_spread_mph"] = _num(conflicts, "speed_spread_mph")
        pattern = (
            conflicts.groupby(["speed_candidate_values", "speed_spread_mph", "severe_conflict_spread_ge_15mph"], dropna=False)
            .agg(
                conflict_bin_count=("reference_directional_bin_id", "nunique"),
                affected_reference_signal_count=("reference_signal_id", "nunique"),
            )
            .reset_index()
            .sort_values(["conflict_bin_count", "speed_spread_mph"], ascending=[False, False])
        )
        top_signals = (
            conflicts.groupby(["reference_signal_id"], dropna=False)
            .agg(
                conflict_bin_count=("reference_directional_bin_id", "nunique"),
                severe_conflict_bin_count=("is_severe_conflict", "sum"),
            )
            .reset_index()
            .sort_values(["severe_conflict_bin_count", "conflict_bin_count"], ascending=[False, False])
        )
        pattern["diagnostic_type"] = "review_unresolved_candidate_speed_pattern"
        top_signals["diagnostic_type"] = "top_reference_signal_with_review_unresolved_conflict"
        frames.extend([pattern.head(50), top_signals.head(50)])
    if not transitions.empty:
        transitions["transition_pattern"] = "car:" + transitions["car_speed_candidate_values"].astype(str) + ";truck:" + transitions["truck_speed_candidate_values"].astype(str)
        transition_patterns = (
            transitions.groupby(["transition_pattern", "weighted_speed_method"], dropna=False)
            .agg(
                conflict_bin_count=("reference_directional_bin_id", "nunique"),
                affected_reference_signal_count=("reference_signal_id", "nunique"),
            )
            .reset_index()
            .rename(columns={"transition_pattern": "speed_candidate_values"})
            .sort_values("conflict_bin_count", ascending=False)
        )
        transition_patterns["diagnostic_type"] = "stable_weighted_transition_pattern"
        transition_patterns["severe_conflict_spread_ge_15mph"] = False
        frames.append(transition_patterns.head(50))
    if not frames:
        return pd.DataFrame(columns=["diagnostic_type", "speed_candidate_values", "conflict_bin_count"])
    out = pd.concat(frames, ignore_index=True, sort=False)
    for column in [
        "reference_signal_id",
        "speed_candidate_values",
        "speed_spread_mph",
        "severe_conflict_spread_ge_15mph",
        "conflict_bin_count",
        "severe_conflict_bin_count",
        "affected_reference_signal_count",
        "weighted_speed_method",
    ]:
        if column not in out.columns:
            out[column] = ""
    columns = [
        "diagnostic_type",
        "reference_signal_id",
        "speed_candidate_values",
        "speed_spread_mph",
        "severe_conflict_spread_ge_15mph",
        "conflict_bin_count",
        "severe_conflict_bin_count",
        "affected_reference_signal_count",
        "weighted_speed_method",
    ]
    return out[columns]


def _severe_conflict_queue(bin_context: pd.DataFrame) -> pd.DataFrame:
    severe = bin_context.loc[bin_context["is_severe_conflict"]].copy()
    if severe.empty:
        return pd.DataFrame()
    severe["speed_spread_mph"] = _num(severe, "speed_spread_mph")
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "source_bin_key",
        "qa_distance_window",
        "signal_relative_direction",
        "roadway_representation_type",
        "far_anchor_type",
        "speed_candidate_values",
        "speed_spread_mph",
        "nearest_speed_distance_ft",
        "nearest_speed_record_id",
        "stable_route_name_raw",
        "speed_route_name_raw",
    ]
    return severe[[c for c in columns if c in severe.columns]].sort_values(
        ["speed_spread_mph", "reference_signal_id", "reference_directional_bin_id"],
        ascending=[False, True, True],
    )


def _status_closure_qa(bin_context: pd.DataFrame, paired_qa: pd.DataFrame) -> pd.DataFrame:
    status_counts = bin_context.groupby("refined_speed_context_status", dropna=False).size().reset_index(name="bin_count")
    status_counts = status_counts.rename(columns={"refined_speed_context_status": "speed_context_status"})
    status_counts["qa_check"] = "status_count"
    status_counts["passed"] = status_counts["speed_context_status"].isin(EXPECTED_STATUSES)
    total_rows = len(bin_context)
    counted_rows = int(status_counts["bin_count"].sum())
    closure = pd.DataFrame(
        [
            {
                "qa_check": "status_counts_close_to_total",
                "speed_context_status": "all",
                "bin_count": counted_rows,
                "passed": counted_rows == total_rows,
                "expected": total_rows,
            },
            {
                "qa_check": "known_status_vocabulary_only",
                "speed_context_status": "all",
                "bin_count": counted_rows,
                "passed": bool(status_counts["passed"].all()),
                "expected": "|".join(sorted(EXPECTED_STATUSES)),
            },
            {
                "qa_check": "paired_pseudo_direction_inconsistencies",
                "speed_context_status": "paired_qa",
                "bin_count": int(pd.to_numeric(paired_qa.get("inconsistent_context_across_pair", pd.Series(dtype=str)).astype(str).map({"True": 1, "False": 0}), errors="coerce").fillna(0).sum()) if not paired_qa.empty else 0,
                "passed": int((paired_qa.get("inconsistent_context_across_pair", pd.Series(dtype=str)).astype(str) == "True").sum()) == 0 if not paired_qa.empty else True,
                "expected": 0,
            },
        ]
    )
    status_counts["expected"] = "known_status"
    return pd.concat([status_counts[["qa_check", "speed_context_status", "bin_count", "passed", "expected"]], closure], ignore_index=True, sort=False)


def _readiness_summary(bin_context: pd.DataFrame, crash_context: pd.DataFrame, status_qa: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "main_0_2500ft_bins", "value": "", "count": len(bin_context)},
        {"metric": "stable_speed_context_bins", "value": "route_matched", "count": int(bin_context["is_stable_speed_context"].sum())},
        {"metric": "stable_single_speed_bins", "value": "", "count": int(bin_context["is_stable_single_speed_context"].sum())},
        {"metric": "stable_weighted_transition_bins", "value": "equal_weight_route_transition", "count": int(bin_context["is_stable_weighted_speed_context"].sum())},
        {"metric": "review_speed_context_bins", "value": "review_unresolved_speed_conflict", "count": int(bin_context["is_review_speed_context"].sum())},
        {"metric": "missing_speed_context_bins", "value": "no_route_compatible_match", "count": int(bin_context["is_missing_speed_context"].sum())},
        {"metric": "severe_conflict_bins_spread_ge_15mph", "value": "", "count": int(bin_context["is_severe_conflict"].sum())},
        {"metric": "crashes_inheriting_stable_v3_speed_context", "value": "", "count": int(crash_context["is_stable_speed_context"].sum())},
        {"metric": "crashes_inheriting_stable_weighted_v3_speed_context", "value": "", "count": int(crash_context["is_stable_weighted_speed_context"].sum())},
        {"metric": "reference_signals_with_stable_v3_speed_context", "value": "", "count": int(bin_context.loc[bin_context["is_stable_speed_context"], "reference_signal_id"].nunique())},
        {"metric": "newly_recovered_by_refined_route_normalization_bins", "value": "", "count": int((bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["is_stable_speed_context"]).sum()) if "route_recovered_by_refined_normalization" in bin_context.columns else 0},
        {"metric": "newly_recovered_by_refined_route_normalization_bins_0_1000ft", "value": "", "count": int((bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["is_stable_speed_context"] & bin_context["qa_distance_window"].eq("0_to_1000ft")).sum()) if "route_recovered_by_refined_normalization" in bin_context.columns else 0},
        {"metric": "newly_recovered_by_refined_route_normalization_bins_1000_2500ft", "value": "", "count": int((bin_context["route_recovered_by_refined_normalization"].astype(str).str.lower().eq("true") & bin_context["is_stable_speed_context"] & bin_context["qa_distance_window"].eq("1000_to_2500ft")).sum()) if "route_recovered_by_refined_normalization" in bin_context.columns else 0},
        {"metric": "paired_pseudo_direction_inconsistencies", "value": "", "count": int(status_qa.loc[status_qa["qa_check"].eq("paired_pseudo_direction_inconsistencies"), "bin_count"].iloc[0])},
        {"metric": "crash_direction_fields_read_or_used", "value": "False", "count": ""},
        {"metric": "speed_join_logic_changed", "value": "False", "count": ""},
        {"metric": "scaffold_catchment_assignment_access_logic_changed", "value": "False", "count": ""},
        {"metric": "nearest_any_run_or_used", "value": "False", "count": ""},
        {"metric": "recommended_combined_context_use", "value": "ready_for_flagged_combined_context_table_after_review", "count": ""},
    ]
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, coverage_window: pd.DataFrame, crash_window: pd.DataFrame, conflict: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def count(metric: str) -> str:
        row = summary.loc[summary["metric"].eq(metric)]
        return "0" if row.empty else str(row.iloc[0]["count"])

    stable_by_window = coverage_window[["qa_distance_window", "stable_speed_bin_count", "stable_weighted_transition_bin_count", "missing_speed_bin_count", "review_unresolved_conflict_bin_count"]].to_dict(orient="records")
    crashes_by_window = crash_window.groupby("qa_distance_window", dropna=False)["crashes_inheriting_stable_speed"].sum().reset_index().to_dict(orient="records")
    top_transitions = conflict.loc[conflict["diagnostic_type"].eq("stable_weighted_transition_pattern")].head(10).to_dict(orient="records") if not conflict.empty else []
    top_conflicts = conflict.loc[conflict["diagnostic_type"].eq("review_unresolved_candidate_speed_pattern")].head(10).to_dict(orient="records") if not conflict.empty else []
    return "\n".join(
        [
            "# Speed Context v3 Readiness QA",
            "",
            "## Bounded Question",
            "",
            "Read-only readiness QA for route-assisted posted-speed context v3, with nearest-any skipped.",
            "",
            "## Recommendation",
            "",
            "- Use `stable_speed_context` where refined status is `stable_single_speed` or `stable_weighted_speed_transition`.",
            "- Use `review_speed_context` where refined status is `review_unresolved_speed_conflict`.",
            "- Use `missing_speed_context` where refined status is `missing_no_route_compatible_speed`.",
            "- Do not promote nearest-any fallback into stable context from this QA.",
            "",
            "## Summary",
            "",
            f"- stable route-matched bins: {count('stable_speed_context_bins')}",
            f"- stable single-speed bins: {count('stable_single_speed_bins')}",
            f"- stable weighted transition bins: {count('stable_weighted_transition_bins')}",
            f"- missing/no route-compatible bins: {count('missing_speed_context_bins')}",
            f"- review unresolved conflict bins: {count('review_speed_context_bins')}",
            f"- severe conflicts >= 15 mph: {count('severe_conflict_bins_spread_ge_15mph')}",
            f"- newly recovered by refined route normalization bins: {count('newly_recovered_by_refined_route_normalization_bins')}",
            f"- crashes inheriting stable v3 speed context: {count('crashes_inheriting_stable_v3_speed_context')}",
            f"- reference signals with stable v3 speed context: {count('reference_signals_with_stable_v3_speed_context')}",
            f"- paired pseudo-direction inconsistencies: {count('paired_pseudo_direction_inconsistencies')}",
            "",
            "## Window Summaries",
            "",
            f"- bins by window: `{stable_by_window}`",
            f"- crashes inheriting stable speed by window: `{crashes_by_window}`",
            "",
            "## Top Weighted Transition Patterns",
            "",
            f"`{top_transitions}`",
            "",
            "## Top Review Conflict Patterns",
            "",
            f"`{top_conflicts}`",
            "",
            "## Discipline Checks",
            "",
            "- crash direction fields read or used: False",
            "- speed join logic changed: False",
            "- scaffold/catchment/assignment/access logic changed: False",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
        ]
    )


def build_speed_context_v3_readiness_qa(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    out_dir = output_root / "review/current/speed_context_v3_readiness_qa"
    bin_context = _read_csv(output_root / "review/current/speed_context_join_v3_route_assisted/directional_bin_speed_context_v3.csv")
    crash_context = _read_csv(output_root / "review/current/speed_context_join_v3_route_assisted/directional_crash_speed_context_v3.csv")
    paired_qa = _read_csv(output_root / "review/current/speed_context_join_v3_route_assisted/speed_paired_pseudo_direction_consistency_qa_v3.csv")
    join_summary = _read_csv(output_root / "review/current/speed_context_join_v3_route_assisted/speed_context_v3_summary.csv")
    crash_readiness = _read_csv(output_root / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv", guard_crash_direction_fields=True)

    bin_context["qa_distance_window"] = _distance_window(bin_context)
    if "refined_speed_context_status" not in bin_context.columns:
        bin_context["refined_speed_context_status"] = bin_context["speed_context_status"].replace({LEGACY_STABLE_STATUS: STABLE_SINGLE_STATUS, "ambiguous_conflicting_speed_values": REVIEW_UNRESOLVED_STATUS, "no_speed_nearby_or_route_compatible": MISSING_STATUS})
    bin_context["is_stable_single_speed_context"] = bin_context["refined_speed_context_status"].eq(STABLE_SINGLE_STATUS)
    bin_context["is_stable_weighted_speed_context"] = bin_context["refined_speed_context_status"].eq(STABLE_WEIGHTED_STATUS)
    bin_context["is_stable_speed_context"] = bin_context["refined_speed_context_status"].isin([STABLE_SINGLE_STATUS, STABLE_WEIGHTED_STATUS])
    bin_context["is_review_speed_context"] = bin_context["refined_speed_context_status"].eq(REVIEW_UNRESOLVED_STATUS)
    bin_context["is_missing_speed_context"] = bin_context["refined_speed_context_status"].eq(MISSING_STATUS)
    bin_context["is_severe_conflict"] = bin_context["severe_conflict_spread_ge_15mph"].astype(str).str.lower().eq("true")
    bin_context["weighted_speed_context_flag_bool"] = bin_context.get("weighted_speed_context_flag", pd.Series(False, index=bin_context.index)).astype(str).str.lower().eq("true")

    crash_context = crash_context.merge(
        bin_context[["reference_directional_bin_id", "roadway_representation_type", "far_anchor_type"]],
        on="reference_directional_bin_id",
        how="left",
    )
    crash_context["qa_distance_window"] = _distance_window(crash_context)
    if "refined_speed_context_status" not in crash_context.columns:
        crash_context["refined_speed_context_status"] = crash_context["speed_context_status"].replace({LEGACY_STABLE_STATUS: STABLE_SINGLE_STATUS, "ambiguous_conflicting_speed_values": REVIEW_UNRESOLVED_STATUS, "no_speed_nearby_or_route_compatible": MISSING_STATUS})
    crash_context["is_stable_single_speed_context"] = crash_context["refined_speed_context_status"].eq(STABLE_SINGLE_STATUS)
    crash_context["is_stable_weighted_speed_context"] = crash_context["refined_speed_context_status"].eq(STABLE_WEIGHTED_STATUS)
    crash_context["is_stable_speed_context"] = crash_context["refined_speed_context_status"].isin([STABLE_SINGLE_STATUS, STABLE_WEIGHTED_STATUS])
    crash_context["is_review_speed_context"] = crash_context["refined_speed_context_status"].eq(REVIEW_UNRESOLVED_STATUS)
    crash_context["is_missing_speed_context"] = crash_context["refined_speed_context_status"].eq(MISSING_STATUS)

    coverage_window = _coverage_by(bin_context, ["qa_distance_window"])
    coverage_representation = _coverage_by(bin_context, ["qa_distance_window", "roadway_representation_type"])
    coverage_direction = _coverage_by(bin_context, ["qa_distance_window", "signal_relative_direction"])
    coverage_signal = _coverage_by(bin_context, ["reference_signal_id"])
    missing = _missing_diagnostic(bin_context)
    conflict = _conflict_diagnostic(bin_context)
    severe_queue = _severe_conflict_queue(bin_context)
    crash_window = _crash_context_by_window(crash_context)
    crash_speed = _crash_context_by_posted_speed(crash_context)
    status_qa = _status_closure_qa(bin_context, paired_qa)
    summary = _readiness_summary(bin_context, crash_context, status_qa)

    outputs = {
        "summary_csv": out_dir / "speed_context_v3_readiness_summary.csv",
        "coverage_by_distance_window_csv": out_dir / "speed_v3_coverage_by_distance_window.csv",
        "coverage_by_roadway_representation_csv": out_dir / "speed_v3_coverage_by_roadway_representation.csv",
        "coverage_by_signal_relative_direction_csv": out_dir / "speed_v3_coverage_by_signal_relative_direction.csv",
        "coverage_by_reference_signal_csv": out_dir / "speed_v3_coverage_by_reference_signal.csv",
        "crash_context_by_window_csv": out_dir / "speed_v3_crash_context_by_window.csv",
        "crash_context_by_posted_speed_csv": out_dir / "speed_v3_crash_context_by_posted_speed.csv",
        "missing_context_diagnostic_csv": out_dir / "speed_v3_missing_context_diagnostic.csv",
        "conflict_context_diagnostic_csv": out_dir / "speed_v3_conflict_context_diagnostic.csv",
        "severe_conflict_review_queue_csv": out_dir / "speed_v3_severe_conflict_review_queue.csv",
        "status_closure_qa_csv": out_dir / "speed_v3_status_closure_qa.csv",
        "findings_md": out_dir / "speed_context_v3_readiness_findings.md",
        "manifest_json": out_dir / "speed_context_v3_readiness_manifest.json",
    }

    _write_csv(summary, outputs["summary_csv"])
    _write_csv(coverage_window, outputs["coverage_by_distance_window_csv"])
    _write_csv(coverage_representation, outputs["coverage_by_roadway_representation_csv"])
    _write_csv(coverage_direction, outputs["coverage_by_signal_relative_direction_csv"])
    _write_csv(coverage_signal, outputs["coverage_by_reference_signal_csv"])
    _write_csv(crash_window, outputs["crash_context_by_window_csv"])
    _write_csv(crash_speed, outputs["crash_context_by_posted_speed_csv"])
    _write_csv(missing, outputs["missing_context_diagnostic_csv"])
    _write_csv(conflict, outputs["conflict_context_diagnostic_csv"])
    _write_csv(severe_queue, outputs["severe_conflict_review_queue_csv"])
    _write_csv(status_qa, outputs["status_closure_qa_csv"])
    _write_text(_findings(summary, coverage_window, crash_window, conflict, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only readiness QA for route-assisted posted-speed context v3 with nearest-any skipped",
        "nearest_any_run_or_used": False,
        "crash_direction_fields_read_or_used": False,
        "speed_join_logic_changed": False,
        "speed_context_refinement": "weighted same-route transition summaries and bounded exact-key route-name normalization refinement",
        "scaffold_catchment_assignment_access_logic_changed": False,
        "access_context_changed": False,
        "combined_context_table_created": False,
        "schema_changes_documented": [
            "weighted_car_speed_limit",
            "weighted_truck_speed_limit",
            "posted_car_speed_limit_context_value",
            "posted_truck_speed_limit_context_value",
            "car_speed_candidate_values",
            "truck_speed_candidate_values",
            "car_speed_spread_mph",
            "truck_speed_spread_mph",
            "speed_transition_within_bin_flag",
            "weighted_speed_context_flag",
            "weighted_speed_method",
            "refined_speed_context_status",
            "refined_speed_context_confidence",
        ],
        "inputs": {
            "directional_bin_speed_context_v3": str(BIN_CONTEXT_FILE),
            "directional_crash_speed_context_v3": str(CRASH_CONTEXT_FILE),
            "speed_context_v3_summary": str(JOIN_SUMMARY_FILE),
            "speed_paired_pseudo_direction_consistency_qa_v3": str(PAIRED_QA_FILE),
            "crash_directional_assignment_readiness_by_crash": str(CRASH_READINESS_FILE),
        },
        "input_row_counts": {
            "directional_bin_speed_context_v3": len(bin_context),
            "directional_crash_speed_context_v3": len(crash_context),
            "speed_context_v3_summary": len(join_summary),
            "speed_paired_pseudo_direction_consistency_qa_v3": len(paired_qa),
            "crash_directional_assignment_readiness_by_crash": len(crash_readiness),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "status_closure_qa": status_qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only readiness QA for route-assisted posted-speed context v3.")
    parser.parse_args()
    outputs = build_speed_context_v3_readiness_qa()
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
