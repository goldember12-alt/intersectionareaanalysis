from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/under_captured_recovery_triage_and_two_leg_audit"

CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"
REFRESHED_LEG_DIR = OUTPUT_ROOT / "review/current/refreshed_leg_coverage_after_offset_recovery"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_context_refresh"
OFFSET_QA_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_staging_qa_cleanup"

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

REQUIRED_INPUTS = {
    CALIB_DIR: [
        "calibrated_expected_leg_signal_detail.csv",
        "calibrated_source_zone_line_classification.csv",
        "calibrated_expected_leg_distribution.csv",
        "calibrated_current_vs_expected_alignment.csv",
        "calibrated_leg_model_review_queue.csv",
        "calibrated_expected_physical_leg_model_manifest.json",
    ],
    REFRESHED_LEG_DIR: [
        "refreshed_leg_coverage_bin_detail.csv",
        "refreshed_leg_coverage_signal_summary.csv",
        "remaining_leg_capture_review_queue.csv",
        "refreshed_leg_coverage_after_offset_manifest.json",
    ],
    OFFSET_CONTEXT_DIR: [
        "offset_zone_context_bin_detail.csv",
        "offset_zone_context_signal_summary.csv",
        "offset_zone_context_refresh_manifest.json",
    ],
    OFFSET_QA_DIR: [
        "cleaned_staged_offset_recovered_legs.csv",
        "cleaned_staged_offset_recovered_bins.csv",
        "staging_qa_cleanup_readiness_summary.csv",
        "staging_qa_cleanup_manifest.json",
    ],
}


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
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0)
    blocked = [column for column in header.columns if _blocked_column(column)]
    if blocked:
        raise RuntimeError(f"Refusing to read crash-like fields from {path}: {blocked}")
    frame = pd.read_csv(path, low_memory=False)
    _checkpoint(f"read_done {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _contains(value: Any, token: str) -> bool:
    if pd.isna(value):
        return False
    return token.lower() in str(value).lower()


def _classify_under(row: pd.Series) -> str:
    manual = str(row.get("manual_category", "") or "").lower()
    offset_class = str(row.get("offset_anchor_class", "") or "").lower()
    recovery_action = str(row.get("likely_recovery_action", "") or "").lower()
    route_groups = _int(row.get("source_route_group_count"))
    source_bearings = _int(row.get("source_bearing_count"))
    current_legs = _int(row.get("current_refreshed_physical_leg_count", row.get("refreshed_physical_leg_count")))
    missing = _int(row.get("calibrated_missing_leg_count"))
    branch_count = _int(row.get("candidate_branch_count"))
    expected = _int(row.get("calibrated_expected_physical_leg_count"))

    if _bool(row.get("grade_separated_mainline_flag")) or "grade" in manual or "mainline" in manual:
        return "needs_grade_separation_or_mainline_exclusion"
    if "nonstandard" in manual or "unclear" in manual:
        return "needs_manual_map_review_before_recovery"
    if _bool(row.get("offset_high_medium_candidate")) or "offset_anchor_high" in offset_class or "offset_anchor_medium" in offset_class:
        return "needs_offset_anchor_recovery"
    if _bool(row.get("long_source_row_flag")):
        return "needs_manual_map_review_before_recovery"
    if _bool(row.get("calibrated_divided_subbranch_evidence")) and branch_count >= expected and missing <= 1:
        return "needs_divided_carriageway_subbranch_normalization"
    if "route_facility" in recovery_action or route_groups >= expected + 2:
        return "needs_route_facility_discontinuity_handling"
    if source_bearings >= expected and current_legs > 0 and missing > 0:
        return "ready_for_intersection_zone_missing_leg_recovery"
    if source_bearings > current_legs and current_legs == 0:
        return "needs_graph_reference_repair_from_source_travelway"
    if missing <= 0:
        return "likely_false_under_capture_due_to_expected_model"
    return "insufficient_evidence"


def _classify_two_leg(row: pd.Series) -> str:
    manual = str(row.get("manual_category", "") or "").lower()
    offset_class = str(row.get("offset_anchor_class", "") or "").lower()
    source_limited = _bool(row.get("source_limited_manual_or_prior"))
    source_bearings = _int(row.get("source_bearing_count"))
    calibrated_count = _int(row.get("calibrated_expected_physical_leg_count"))
    route_groups = _int(row.get("source_route_group_count"))
    line_count = _int(row.get("source_line_count"))

    if _bool(row.get("grade_separated_mainline_flag")) or "grade" in manual or "mainline" in manual:
        return "grade_separated_or_mainline_contamination"
    if "nonstandard" in manual:
        return "nonstandard_signal_control_geometry"
    if "source_missing" in manual or source_limited:
        return "source_travelway_missing_cross_street"
    if _bool(row.get("long_source_row_flag")):
        return "manual_review_needed"
    if "offset_anchor" in offset_class:
        return "signal_offset_or_zone_radius_issue"
    if source_bearings > calibrated_count or source_bearings >= 3:
        return "expected_model_missed_source_leg"
    if route_groups >= calibrated_count + 2 and line_count >= 3:
        return "route_facility_name_change_obscures_leg"
    if line_count <= 2 and source_bearings <= 2:
        return "legitimate_partial_or_ramp_signal_possible"
    if calibrated_count <= 1:
        return "insufficient_evidence"
    return "manual_review_needed"


def _difficulty(triage_class: str) -> str:
    if triage_class == "ready_for_intersection_zone_missing_leg_recovery":
        return "low"
    if triage_class in {"needs_offset_anchor_recovery", "needs_route_facility_discontinuity_handling"}:
        return "medium"
    if triage_class in {"needs_divided_carriageway_subbranch_normalization", "needs_graph_reference_repair_from_source_travelway"}:
        return "medium_high"
    if triage_class in {"needs_grade_separation_or_mainline_exclusion", "needs_manual_map_review_before_recovery"}:
        return "high_manual_review"
    return "unknown"


def _should_target_before_access(triage_class: str, missing_legs: int) -> bool:
    return triage_class in {
        "ready_for_intersection_zone_missing_leg_recovery",
        "needs_offset_anchor_recovery",
        "needs_route_facility_discontinuity_handling",
        "needs_graph_reference_repair_from_source_travelway",
    } and missing_legs >= 1


def _summarize_bins_by_signal(frame: pd.DataFrame, signal_col: str) -> pd.DataFrame:
    if frame.empty or signal_col not in frame.columns:
        return pd.DataFrame(columns=["signal_id"])
    work = frame.copy()
    if "distance_band" in work.columns:
        band_col = "distance_band"
    elif "analysis_window" in work.columns:
        band_col = "analysis_window"
    else:
        band_col = None
    aggregations: dict[str, tuple[str, str]] = {}
    if "staged_recovered_bin_id" in work.columns:
        aggregations["offset_staged_bin_count"] = ("staged_recovered_bin_id", "count")
    elif "offset_zone_recovered_bin_id" in work.columns:
        aggregations["offset_staged_bin_count"] = ("offset_zone_recovered_bin_id", "count")
    else:
        aggregations["offset_staged_bin_count"] = (signal_col, "count")
    if "speed_aadt_ready_bin" in work.columns:
        work["speed_aadt_ready_bin_bool"] = work["speed_aadt_ready_bin"].map(_bool)
        aggregations["offset_speed_aadt_ready_bins"] = ("speed_aadt_ready_bin_bool", "sum")
    grouped = work.groupby(signal_col, dropna=False).agg(**aggregations).reset_index()
    grouped = grouped.rename(columns={signal_col: "signal_id"})
    if band_col:
        band_counts = (
            work.groupby([signal_col, band_col], dropna=False)
            .size()
            .unstack(fill_value=0)
            .reset_index()
            .rename(columns={signal_col: "signal_id"})
        )
        band_counts.columns = [
            column if column == "signal_id" else f"offset_bins_{str(column).replace('-', '_')}"
            for column in band_counts.columns
        ]
        grouped = grouped.merge(band_counts, on="signal_id", how="left")
    return grouped


def _make_under_detail(calib: pd.DataFrame, offset_signal: pd.DataFrame, staged_bins: pd.DataFrame) -> pd.DataFrame:
    under = calib.loc[calib["calibrated_alignment_class"].eq("under_captured_recoverable")].copy()
    under["under_capture_triage_class"] = under.apply(_classify_under, axis=1)
    under["missing_physical_legs_for_triage"] = under["calibrated_missing_leg_count"].map(_int)
    under["likely_0_250ft_bins_if_recovered"] = under["missing_physical_legs_for_triage"] * 5
    under["likely_250_500ft_bins_if_recovered"] = under["missing_physical_legs_for_triage"] * 5
    under["likely_500_750ft_bins_if_recovered"] = under["missing_physical_legs_for_triage"] * 5
    under["likely_750_1000ft_bins_if_recovered"] = under["missing_physical_legs_for_triage"] * 5
    under["likely_0_1000ft_bins_if_recovered"] = under["missing_physical_legs_for_triage"] * 20
    under["route_measure_speed_aadt_refresh_likely_workable"] = under["under_capture_triage_class"].isin(
        {
            "ready_for_intersection_zone_missing_leg_recovery",
            "needs_offset_anchor_recovery",
            "needs_route_facility_discontinuity_handling",
            "needs_graph_reference_repair_from_source_travelway",
        }
    )
    under["implementation_difficulty"] = under["under_capture_triage_class"].map(_difficulty)
    under["target_before_access_or_crash_work"] = [
        _should_target_before_access(row["under_capture_triage_class"], _int(row["missing_physical_legs_for_triage"]))
        for _, row in under.iterrows()
    ]

    if not offset_signal.empty and "signal_id" in offset_signal.columns:
        keep = [
            column
            for column in [
                "signal_id",
                "attempted_bin_count",
                "attempted_leg_count",
                "speed_aadt_ready",
                "eligible_for_later_universe_refresh",
                "has_grade_separation_holdouts",
                "has_long_source_row_qa_flag",
                "route_facility_discontinuity_types",
                "qa_cleanup_statuses",
            ]
            if column in offset_signal.columns
        ]
        under = under.merge(offset_signal[keep].drop_duplicates("signal_id"), on="signal_id", how="left")

    bin_summary = _summarize_bins_by_signal(staged_bins, "signal_id")
    if not bin_summary.empty:
        under = under.merge(bin_summary, on="signal_id", how="left")

    detail_cols = [
        "signal_id",
        "source_signal_id_x",
        "source_layer_x",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "calibrated_missing_leg_count",
        "candidate_branch_count",
        "carriageway_subbranch_count",
        "source_bearing_count",
        "source_bearing_groups",
        "source_line_count",
        "source_route_group_count",
        "source_route_groups",
        "total_bins",
        "bins_0_250",
        "bins_250_500",
        "bins_500_750",
        "bins_750_1000",
        "bins_0_1000",
        "offset_bins_added_flag",
        "offset_added_physical_leg_flag",
        "offset_anchor_class",
        "offset_high_medium_candidate",
        "grade_separated_mainline_flag",
        "long_source_row_flag",
        "calibrated_divided_subbranch_evidence",
        "manual_category",
        "manual_note",
        "likely_recovery_action",
        "under_capture_triage_class",
        "likely_0_250ft_bins_if_recovered",
        "likely_250_500ft_bins_if_recovered",
        "likely_500_750ft_bins_if_recovered",
        "likely_750_1000ft_bins_if_recovered",
        "likely_0_1000ft_bins_if_recovered",
        "route_measure_speed_aadt_refresh_likely_workable",
        "implementation_difficulty",
        "target_before_access_or_crash_work",
        "route_facility_discontinuity_types",
        "qa_cleanup_statuses",
        "offset_staged_bin_count",
    ]
    detail_cols = [column for column in detail_cols if column in under.columns]
    return under[detail_cols].sort_values(
        ["target_before_access_or_crash_work", "calibrated_missing_leg_count", "source_bearing_count"],
        ascending=[False, False, False],
    )


def _make_two_leg_detail(calib: pd.DataFrame) -> pd.DataFrame:
    two = calib.loc[calib["calibrated_expected_physical_leg_class"].eq("two_leg_or_less")].copy()
    two["two_leg_or_less_audit_class"] = two.apply(_classify_two_leg, axis=1)
    two["two_leg_suspicious_for_recovery_backlog"] = two["two_leg_or_less_audit_class"].isin(
        {
            "expected_model_missed_source_leg",
            "signal_offset_or_zone_radius_issue",
            "route_facility_name_change_obscures_leg",
        }
    )
    two["two_leg_likely_holdout"] = two["two_leg_or_less_audit_class"].isin(
        {
            "legitimate_partial_or_ramp_signal_possible",
            "source_travelway_missing_cross_street",
            "grade_separated_or_mainline_contamination",
            "nonstandard_signal_control_geometry",
        }
    )
    two["estimated_missing_legs_if_reclassified"] = np.where(
        two["two_leg_suspicious_for_recovery_backlog"],
        np.maximum(1, two["source_bearing_count"].map(_int) - two["calibrated_expected_physical_leg_count"].map(_int)),
        0,
    )
    two["likely_0_1000ft_bins_if_reclassified"] = two["estimated_missing_legs_if_reclassified"] * 20

    cols = [
        "signal_id",
        "source_signal_id_x",
        "source_layer_x",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "source_bearing_count",
        "source_bearing_groups",
        "source_line_count",
        "source_route_group_count",
        "source_route_groups",
        "candidate_branch_count",
        "carriageway_subbranch_count",
        "total_bins",
        "manual_category",
        "manual_note",
        "offset_anchor_class",
        "grade_separated_mainline_flag",
        "long_source_row_flag",
        "source_limited_manual_or_prior",
        "calibration_rule",
        "two_leg_or_less_audit_class",
        "two_leg_suspicious_for_recovery_backlog",
        "two_leg_likely_holdout",
        "estimated_missing_legs_if_reclassified",
        "likely_0_1000ft_bins_if_reclassified",
    ]
    cols = [column for column in cols if column in two.columns]
    return two[cols].sort_values(
        ["two_leg_suspicious_for_recovery_backlog", "source_bearing_count", "source_route_group_count"],
        ascending=[False, False, False],
    )


def _summary(frame: pd.DataFrame, group_col: str, name_col: str = "signal_count") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[group_col, name_col])
    return frame.groupby(group_col, dropna=False).size().reset_index(name=name_col).sort_values(name_col, ascending=False)


def _make_potential(under_detail: pd.DataFrame) -> pd.DataFrame:
    if under_detail.empty:
        return pd.DataFrame()
    return (
        under_detail.groupby("under_capture_triage_class", dropna=False)
        .agg(
            signal_count=("signal_id", "nunique"),
            missing_physical_legs=("calibrated_missing_leg_count", "sum"),
            likely_0_250ft_bins=("likely_0_250ft_bins_if_recovered", "sum"),
            likely_250_500ft_bins=("likely_250_500ft_bins_if_recovered", "sum"),
            likely_500_750ft_bins=("likely_500_750ft_bins_if_recovered", "sum"),
            likely_750_1000ft_bins=("likely_750_1000ft_bins_if_recovered", "sum"),
            likely_0_1000ft_bins=("likely_0_1000ft_bins_if_recovered", "sum"),
            route_measure_speed_aadt_refresh_likely_workable=("route_measure_speed_aadt_refresh_likely_workable", "sum"),
            target_before_access_or_crash_work=("target_before_access_or_crash_work", "sum"),
        )
        .reset_index()
        .assign(
            expected_implementation_difficulty=lambda df: df["under_capture_triage_class"].map(_difficulty),
            target_before_access_or_crash_work=lambda df: df["target_before_access_or_crash_work"].astype(int),
        )
        .sort_values(["target_before_access_or_crash_work", "likely_0_1000ft_bins"], ascending=False)
    )


def _make_reclassification_summary(under_detail: pd.DataFrame, two_detail: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "comparison_item": "under_captured_recoverable_total",
            "signal_count": under_detail["signal_id"].nunique(),
            "leg_count": under_detail["calibrated_missing_leg_count"].map(_int).sum(),
            "interpretation": "Current calibrated under-capture pool.",
        },
        {
            "comparison_item": "under_captured_target_before_access",
            "signal_count": under_detail.loc[under_detail["target_before_access_or_crash_work"], "signal_id"].nunique(),
            "leg_count": under_detail.loc[under_detail["target_before_access_or_crash_work"], "calibrated_missing_leg_count"].map(_int).sum(),
            "interpretation": "Likely recovery targets worth resolving before access/crash work if schedule allows.",
        },
        {
            "comparison_item": "under_captured_downgrade_to_manual_or_hold",
            "signal_count": under_detail.loc[
                under_detail["under_capture_triage_class"].isin(
                    {
                        "needs_grade_separation_or_mainline_exclusion",
                        "needs_manual_map_review_before_recovery",
                        "likely_false_under_capture_due_to_expected_model",
                        "insufficient_evidence",
                    }
                ),
                "signal_id",
            ].nunique(),
            "leg_count": under_detail.loc[
                under_detail["under_capture_triage_class"].isin(
                    {
                        "needs_grade_separation_or_mainline_exclusion",
                        "needs_manual_map_review_before_recovery",
                        "likely_false_under_capture_due_to_expected_model",
                        "insufficient_evidence",
                    }
                ),
                "calibrated_missing_leg_count",
            ].map(_int).sum(),
            "interpretation": "Signals currently marked recoverable but not clean enough for automatic recovery.",
        },
        {
            "comparison_item": "two_leg_or_less_total",
            "signal_count": two_detail["signal_id"].nunique(),
            "leg_count": two_detail["estimated_missing_legs_if_reclassified"].map(_int).sum(),
            "interpretation": "Current calibrated expected two-leg-or-less pool.",
        },
        {
            "comparison_item": "two_leg_or_less_add_to_recovery_backlog",
            "signal_count": two_detail.loc[two_detail["two_leg_suspicious_for_recovery_backlog"], "signal_id"].nunique(),
            "leg_count": two_detail.loc[two_detail["two_leg_suspicious_for_recovery_backlog"], "estimated_missing_legs_if_reclassified"].map(_int).sum(),
            "interpretation": "Suspicious two-leg-or-less cases that likely reflect remaining data loss or expected-model under-capture.",
        },
        {
            "comparison_item": "two_leg_or_less_likely_holdout",
            "signal_count": two_detail.loc[two_detail["two_leg_likely_holdout"], "signal_id"].nunique(),
            "leg_count": two_detail.loc[two_detail["two_leg_likely_holdout"], "estimated_missing_legs_if_reclassified"].map(_int).sum(),
            "interpretation": "Likely true partial/source-limited/nonstandard cases, pending map review for edge cases.",
        },
    ]
    return pd.DataFrame(rows)


def _make_ranked_under(under_detail: pd.DataFrame) -> pd.DataFrame:
    if under_detail.empty:
        return under_detail
    priority = {
        "ready_for_intersection_zone_missing_leg_recovery": 1,
        "needs_offset_anchor_recovery": 2,
        "needs_route_facility_discontinuity_handling": 3,
        "needs_graph_reference_repair_from_source_travelway": 4,
        "needs_divided_carriageway_subbranch_normalization": 5,
        "needs_grade_separation_or_mainline_exclusion": 6,
        "needs_manual_map_review_before_recovery": 7,
        "likely_false_under_capture_due_to_expected_model": 8,
        "insufficient_evidence": 9,
    }
    ranked = under_detail.copy()
    ranked["review_queue"] = ranked["under_capture_triage_class"].map(
        {
            "ready_for_intersection_zone_missing_leg_recovery": "likely_easy_intersection_zone_missing_leg_recovery",
            "needs_offset_anchor_recovery": "likely_offset_anchor_recovery",
            "needs_route_facility_discontinuity_handling": "route_facility_discontinuity_recovery",
            "needs_divided_carriageway_subbranch_normalization": "divided_carriageway_normalization_case",
        }
    ).fillna("manual_or_lower_priority_under_capture_review")
    ranked["priority_sort"] = ranked["under_capture_triage_class"].map(priority).fillna(99)
    ranked = ranked.sort_values(
        ["priority_sort", "calibrated_missing_leg_count", "source_bearing_count"],
        ascending=[True, False, False],
    ).reset_index(drop=True)
    ranked.insert(0, "review_priority_rank", np.arange(1, len(ranked) + 1))
    return ranked.drop(columns=["priority_sort"])


def _make_ranked_two(two_detail: pd.DataFrame) -> pd.DataFrame:
    if two_detail.empty:
        return two_detail
    priority = {
        "expected_model_missed_source_leg": 1,
        "signal_offset_or_zone_radius_issue": 2,
        "route_facility_name_change_obscures_leg": 3,
        "manual_review_needed": 4,
        "source_travelway_missing_cross_street": 5,
        "legitimate_partial_or_ramp_signal_possible": 6,
        "nonstandard_signal_control_geometry": 7,
        "grade_separated_or_mainline_contamination": 8,
        "insufficient_evidence": 9,
    }
    ranked = two_detail.copy()
    ranked["review_queue"] = np.where(
        ranked["two_leg_suspicious_for_recovery_backlog"],
        "two_leg_or_less_suspicious_recovery_backlog_review",
        np.where(ranked["two_leg_likely_holdout"], "two_leg_or_less_likely_source_limited_holdout", "two_leg_or_less_manual_review"),
    )
    ranked["priority_sort"] = ranked["two_leg_or_less_audit_class"].map(priority).fillna(99)
    ranked = ranked.sort_values(
        ["priority_sort", "source_bearing_count", "source_route_group_count"],
        ascending=[True, False, False],
    ).reset_index(drop=True)
    ranked.insert(0, "review_priority_rank", np.arange(1, len(ranked) + 1))
    return ranked.drop(columns=["priority_sort"])


def _findings(
    under_detail: pd.DataFrame,
    potential: pd.DataFrame,
    two_detail: pd.DataFrame,
    two_summary: pd.DataFrame,
    reclass: pd.DataFrame,
) -> str:
    ready = int(
        under_detail.loc[
            under_detail["target_before_access_or_crash_work"],
            "signal_id",
        ].nunique()
    )
    under_total = int(under_detail["signal_id"].nunique())
    missing_legs = int(under_detail["calibrated_missing_leg_count"].map(_int).sum())
    likely_bins = int(under_detail["likely_0_1000ft_bins_if_recovered"].map(_int).sum())
    top_class = "none"
    if not potential.empty:
        top_class = str(potential.sort_values(["target_before_access_or_crash_work", "likely_0_1000ft_bins"], ascending=False).iloc[0]["under_capture_triage_class"])
    suspicious_two = int(two_detail.loc[two_detail["two_leg_suspicious_for_recovery_backlog"], "signal_id"].nunique())
    holdout_two = int(two_detail.loc[two_detail["two_leg_likely_holdout"], "signal_id"].nunique())
    two_total = int(two_detail["signal_id"].nunique())
    target_before_access = ready >= 500 or missing_legs >= 800
    access_text = (
        "Access work should wait for at least one more bounded recovery pass for the highest-yield classes."
        if target_before_access
        else "Access work can proceed with QA flags while lower-confidence recovery remains in review."
    )
    lines = [
        "# Under-Captured Recovery Triage and Two-Leg-Or-Less Audit",
        "",
        "Bounded question: among calibrated physical-leg results, which under-captured signals are ready for bounded scaffold recovery, and are expected two-leg-or-less cases legitimate or a remaining evidence failure?",
        "",
        "## Main Results",
        "",
        f"- Under-captured recoverable signals reviewed: {under_total:,}.",
        f"- Signals ready or likely workable for a bounded recovery implementation before access/crash work: {ready:,}.",
        f"- Dominant next recovery class: `{top_class}`.",
        f"- Plausible missing physical legs in the under-captured pool: {missing_legs:,}.",
        f"- Plausible 0-1,000 ft 50-ft bins if recovered: {likely_bins:,}.",
        f"- Expected two-leg-or-less cases audited: {two_total:,}.",
        f"- Suspicious two-leg-or-less cases that likely belong in a recovery/model-failure backlog: {suspicious_two:,}.",
        f"- Likely true partial/source-limited/nonstandard two-leg-or-less holdouts: {holdout_two:,}.",
        "",
        "## Recovery Mechanisms",
        "",
    ]
    if potential.empty:
        lines.append("- No under-captured recovery potential rows were produced.")
    else:
        for _, row in potential.iterrows():
            lines.append(
                f"- `{row['under_capture_triage_class']}`: {int(row['signal_count']):,} signals, "
                f"{int(row['missing_physical_legs']):,} missing legs, "
                f"{int(row['likely_0_1000ft_bins']):,} likely 0-1,000 ft bins."
            )
    lines.extend(["", "## Two-Leg-Or-Less Audit", ""])
    if two_summary.empty:
        lines.append("- No expected two-leg-or-less rows were found.")
    else:
        for _, row in two_summary.iterrows():
            lines.append(f"- `{row['two_leg_or_less_audit_class']}`: {int(row['signal_count']):,} signals.")
    lines.extend(
        [
            "",
            "## Reclassification",
            "",
        ]
    )
    for _, row in reclass.iterrows():
        lines.append(f"- `{row['comparison_item']}`: {int(row['signal_count']):,} signals; {row['interpretation']}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            access_text,
            "The next implementation should target the cleanest geometry/bearing-first missing-leg recovery class first, while routing grade-separated, long-row, and nonstandard cases to map review. Route/facility labels should remain QA attributes, not leg definitions.",
        ]
    )
    return "\n".join(lines) + "\n"


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Script writes only to review/current/under_captured_recovery_triage_and_two_leg_audit."),
        ("no_candidates_promoted", True, "No active candidate outputs are modified or promoted."),
        ("no_access_or_crash_assignment", True, "The pass reads leg/context diagnostics only and does not assign access or crashes."),
        ("no_rates_or_models", True, "No rate/model outputs are computed."),
        ("outputs_review_only", True, "All generated tables are triage/review diagnostics."),
        ("source_graph_candidate_separate", True, "Source Travelway evidence, candidate bins, and offset recovery status remain separate attributes."),
        ("route_facility_attributes_only", True, "Route/facility labels are triage attributes, not primary leg definitions."),
        ("deduped_signal_counts_separate_from_bins", True, "Summaries use signal counts separately from estimated bin counts."),
        ("outputs_written_only_to_review_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/under_captured_recovery_triage_and_two_leg_audit"), str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def _manifest(outputs: list[Path], inputs: list[Path], started: str, row_counts: dict[str, int]) -> dict[str, Any]:
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "started_utc": started,
        "script": "src/active/roadway_graph/under_captured_recovery_triage_and_two_leg_audit.py",
        "output_dir": str(OUT_DIR),
        "read_only": True,
        "non_goals_confirmed": [
            "no_active_outputs_modified",
            "no_candidates_promoted",
            "no_access_or_crash_assignment",
            "no_rates_or_models",
            "no_scaffold_rebuild",
            "no_universe_refresh",
        ],
        "inputs": [str(path) for path in inputs],
        "outputs": [str(path) for path in outputs],
        "row_counts": row_counts,
    }


def main() -> None:
    started = datetime.now(timezone.utc).isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    input_paths = [directory / name for directory, names in REQUIRED_INPUTS.items() for name in names]
    missing = [str(path) for path in input_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    calib = _read_csv(CALIB_DIR / "calibrated_expected_leg_signal_detail.csv")
    line_class = _read_csv(CALIB_DIR / "calibrated_source_zone_line_classification.csv")
    refreshed_signal = _read_csv(REFRESHED_LEG_DIR / "refreshed_leg_coverage_signal_summary.csv")
    offset_signal = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv")
    offset_bins = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_bin_detail.csv")
    staged_legs = _read_csv(OFFSET_QA_DIR / "cleaned_staged_offset_recovered_legs.csv")
    staged_bins = _read_csv(OFFSET_QA_DIR / "cleaned_staged_offset_recovered_bins.csv")

    if "signal_id" not in calib.columns:
        raise RuntimeError("calibrated_expected_leg_signal_detail.csv is missing signal_id")
    if "calibrated_alignment_class" not in calib.columns:
        raise RuntimeError("calibrated_expected_leg_signal_detail.csv is missing calibrated_alignment_class")

    # Touch optional frames in log and manifest without joining large duplicate detail unless needed.
    _checkpoint("line_class_rows_available", len(line_class))
    _checkpoint("refreshed_signal_rows_available", len(refreshed_signal))
    _checkpoint("staged_legs_rows_available", len(staged_legs))
    _checkpoint("offset_bins_rows_available", len(offset_bins))

    under_detail = _make_under_detail(calib, offset_signal, staged_bins)
    under_summary = _summary(under_detail, "under_capture_triage_class")
    potential = _make_potential(under_detail)
    two_detail = _make_two_leg_detail(calib)
    two_summary = _summary(two_detail, "two_leg_or_less_audit_class")
    reclass = _make_reclassification_summary(under_detail, two_detail)
    ranked_under = _make_ranked_under(under_detail)
    ranked_two = _make_ranked_two(two_detail)

    outputs = [
        _write_csv(under_detail, "under_captured_975_detail.csv"),
        _write_csv(under_summary, "under_captured_recovery_class_summary.csv"),
        _write_csv(potential, "under_captured_recovery_potential_estimate.csv"),
        _write_csv(two_detail, "two_leg_or_less_429_audit_detail.csv"),
        _write_csv(two_summary, "two_leg_or_less_class_summary.csv"),
        _write_csv(reclass, "under_capture_vs_two_leg_reclassification_summary.csv"),
        _write_csv(ranked_under, "under_captured_ranked_recovery_queue.csv"),
        _write_csv(ranked_two, "two_leg_or_less_ranked_review_queue.csv"),
    ]

    findings = _findings(under_detail, potential, two_detail, two_summary, reclass)
    findings_path = OUT_DIR / "under_captured_recovery_triage_findings.md"
    findings_path.write_text(findings, encoding="utf-8")
    outputs.append(findings_path)
    _checkpoint("write under_captured_recovery_triage_findings.md")

    qa = _qa()
    qa_path = _write_csv(qa, "under_captured_recovery_triage_qa.csv")
    outputs.append(qa_path)

    row_counts = {
        "calibrated_signals": int(len(calib)),
        "under_captured_975_detail": int(len(under_detail)),
        "two_leg_or_less_429_audit_detail": int(len(two_detail)),
        "under_captured_ranked_recovery_queue": int(len(ranked_under)),
        "two_leg_or_less_ranked_review_queue": int(len(ranked_two)),
    }
    manifest = _manifest(outputs, input_paths, started, row_counts)
    manifest_path = OUT_DIR / "under_captured_recovery_triage_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    outputs.append(manifest_path)
    _checkpoint("write under_captured_recovery_triage_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
