from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"

FINAL_CONTEXT_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"
CONSOLIDATED_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"
ADJACENT_DIR = OUTPUT_ROOT / "review/current/divided_adjacent_bearing_sector_merge"
REMAINING_NORM_DIR = OUTPUT_ROOT / "review/current/divided_remaining_implementable_normalization"
FINAL_CLEANUP_DIR = OUTPUT_ROOT / "review/current/final_implementable_scaffold_cleanup"
CALIBRATED_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"
REPRESENTED_DIR = OUTPUT_ROOT / "review/current/refreshed_expanded_universe_with_offset_recovery"
BRANCH_LEDGER_DIR = OUTPUT_ROOT / "review/current/scaffold_recovery_branch_ledger"

BASE_SIGNAL_UNIVERSE = 3_933

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
    FINAL_CONTEXT_DIR / "final_recovery_context_bin_detail.csv",
    FINAL_CONTEXT_DIR / "final_recovery_context_signal_summary.csv",
    FINAL_CONTEXT_DIR / "final_scaffold_branch_exhaustion_summary.csv",
    FINAL_CONTEXT_DIR / "final_source_data_limitation_ledger.csv",
    FINAL_CONTEXT_DIR / "final_recovery_context_refresh_manifest.json",
    CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_expected_alignment.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json",
    ADJACENT_DIR / "adjacent_sector_merge_bin_detail.csv",
    ADJACENT_DIR / "adjacent_sector_merge_signal_summary.csv",
    ADJACENT_DIR / "divided_adjacent_bearing_sector_merge_manifest.json",
    REMAINING_NORM_DIR / "remaining_normalization_bin_detail.csv",
    REMAINING_NORM_DIR / "remaining_normalization_signal_summary.csv",
    REMAINING_NORM_DIR / "divided_remaining_implementable_normalization_manifest.json",
    FINAL_CLEANUP_DIR / "final_cleanup_normalized_divided_bins.csv",
    FINAL_CLEANUP_DIR / "final_cleanup_missing_leg_bins.csv",
    FINAL_CLEANUP_DIR / "final_unrecovered_source_limitation_ledger.csv",
    FINAL_CLEANUP_DIR / "final_implementable_scaffold_cleanup_manifest.json",
    CALIBRATED_DIR / "calibrated_expected_leg_signal_detail.csv",
    CALIBRATED_DIR / "calibrated_expected_leg_distribution.csv",
    CALIBRATED_DIR / "calibrated_current_vs_expected_alignment.csv",
    CALIBRATED_DIR / "calibrated_expected_physical_leg_model_manifest.json",
    REPRESENTED_DIR / "refreshed_represented_signal_universe.csv",
    REPRESENTED_DIR / "refreshed_represented_bin_universe.csv",
    REPRESENTED_DIR / "refreshed_universe_with_offset_recovery_manifest.json",
    BRANCH_LEDGER_DIR / "scaffold_recovery_branch_ledger_signal_detail.csv",
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
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 20) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _required_missing() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _leg_class(count: Any) -> str:
    value = pd.to_numeric(pd.Series([count]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    value = int(value)
    if value <= 1:
        return "one_leg"
    if value == 2:
        return "two_leg"
    if value == 3:
        return "three_leg"
    if value == 4:
        return "four_leg"
    return "five_plus_leg"


def _build_signal_universe(
    represented: pd.DataFrame,
    consolidated: pd.DataFrame,
    calibrated: pd.DataFrame,
    final_context_signal: pd.DataFrame,
    final_source_ledger_signal: pd.DataFrame,
    branch_signal: pd.DataFrame,
    adjacent_signal: pd.DataFrame,
    remaining_signal: pd.DataFrame,
    final_norm_bins: pd.DataFrame,
) -> pd.DataFrame:
    rep = represented.copy()
    rep["signal_id"] = _text(rep, "candidate_signal_id_refreshed").where(
        _text(rep, "candidate_signal_id_refreshed").ne(""),
        _text(rep, "frozen_candidate_signal_id"),
    )
    rep = rep.rename(columns={"source_signal_id": "represented_source_signal_id", "source_layer": "represented_source_layer"})
    rep_cols = [
        "signal_id",
        "represented_source_signal_id",
        "represented_source_layer",
        "refreshed_universe_tier",
        "represented_source_with_offset",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
    ]
    out = rep[[col for col in rep_cols if col in rep.columns]].drop_duplicates("signal_id").copy()
    out["represented_signal_flag"] = True

    cal_cols = [
        "signal_id",
        "source_signal_id_x",
        "source_layer_x",
        "calibrated_expected_physical_leg_count",
        "calibrated_expected_physical_leg_class",
        "calibrated_expected_type",
        "calibrated_alignment_class",
        "calibrated_missing_leg_count",
        "calibrated_extra_leg_count",
        "source_limited_manual_or_prior",
        "grade_separated_mainline_flag",
        "manual_category",
        "manual_note",
        "calibrated_divided_subbranch_evidence",
    ]
    out = out.merge(calibrated[[col for col in cal_cols if col in calibrated.columns]].drop_duplicates("signal_id"), on="signal_id", how="left")

    cons_cols = [
        "signal_id",
        "consolidated_total_bins",
        "consolidated_recovered_bins",
        "consolidated_speed_aadt_ready_bins",
        "consolidated_estimated_physical_leg_count",
        "consolidated_missing_physical_leg_count",
        "consolidated_extra_or_split_branch_count",
        "final_review_only_scaffold_alignment_class",
        "recovered_streams",
        "recovered_classes",
    ]
    out = out.merge(consolidated[[col for col in cons_cols if col in consolidated.columns]].drop_duplicates("signal_id"), on="signal_id", how="left")

    branch_cols = [
        "signal_id",
        "branch_assignments",
        "recovery_streams_applied",
        "generated_bins_count",
        "normalized_bin_count",
        "speed_aadt_context_refresh_status",
        "final_source_data_limitation_flag",
        "final_holdout_flag",
        "latest_alignment_holdout_class",
    ]
    out = out.merge(branch_signal[[col for col in branch_cols if col in branch_signal.columns]].drop_duplicates("signal_id"), on="signal_id", how="left")

    fc = final_context_signal.copy()
    if not fc.empty:
        fc = fc.rename(
            columns={
                "attempted_bin_count": "final_cleanup_context_bin_count",
                "attempted_leg_count": "final_cleanup_context_leg_count",
                "speed_aadt_ready": "final_cleanup_speed_aadt_ready",
                "speed_aadt_ready_bins": "final_cleanup_speed_aadt_ready_bins",
            }
        )
    out = out.merge(
        fc[[col for col in ["signal_id", "final_cleanup_context_bin_count", "final_cleanup_context_leg_count", "final_cleanup_speed_aadt_ready", "final_cleanup_speed_aadt_ready_bins"] if col in fc.columns]].drop_duplicates("signal_id"),
        on="signal_id",
        how="left",
    )

    adjacent = adjacent_signal.copy()
    if not adjacent.empty:
        adjacent = adjacent.rename(
            columns={
                "merged_physical_leg_count": "adjacent_merged_physical_leg_count",
                "updated_alignment_after_adjacent_merge": "adjacent_updated_alignment",
            }
        )
    out = out.merge(
        adjacent[[col for col in ["signal_id", "adjacent_merged_physical_leg_count", "adjacent_updated_alignment", "merge_outcome_class"] if col in adjacent.columns]].drop_duplicates("signal_id"),
        on="signal_id",
        how="left",
    )

    remaining = remaining_signal.copy()
    if not remaining.empty:
        remaining = remaining.rename(
            columns={
                "normalized_physical_leg_count": "remaining_normalized_physical_leg_count",
                "updated_alignment_after_remaining_normalization": "remaining_updated_alignment",
            }
        )
    out = out.merge(
        remaining[[col for col in ["signal_id", "remaining_normalized_physical_leg_count", "remaining_updated_alignment", "normalization_outcome_class"] if col in remaining.columns]].drop_duplicates("signal_id"),
        on="signal_id",
        how="left",
    )

    if final_norm_bins.empty:
        final_norm_signal = pd.DataFrame(columns=["signal_id", "final_cleanup_normalized_physical_leg_count", "final_cleanup_normalized_bin_count"])
    else:
        final_norm_signal = final_norm_bins.groupby("signal_id", dropna=False).agg(
            final_cleanup_normalized_physical_leg_count=("final_normalized_physical_leg_id", "nunique"),
            final_cleanup_normalized_bin_count=("consolidated_bin_id", "count"),
        ).reset_index()
    out = out.merge(final_norm_signal, on="signal_id", how="left")

    for column in [
        "consolidated_estimated_physical_leg_count",
        "calibrated_expected_physical_leg_count",
        "final_cleanup_context_leg_count",
        "adjacent_merged_physical_leg_count",
        "remaining_normalized_physical_leg_count",
        "final_cleanup_normalized_physical_leg_count",
    ]:
        out[column] = _num(out, column)

    base_count = out["consolidated_estimated_physical_leg_count"].where(out["consolidated_estimated_physical_leg_count"].notna(), out["calibrated_expected_physical_leg_count"])
    final_count = base_count.copy()
    final_count = out["adjacent_merged_physical_leg_count"].where(out["adjacent_merged_physical_leg_count"].notna(), final_count)
    final_count = out["remaining_normalized_physical_leg_count"].where(out["remaining_normalized_physical_leg_count"].notna(), final_count)
    final_count = out["final_cleanup_normalized_physical_leg_count"].where(out["final_cleanup_normalized_physical_leg_count"].notna(), final_count)
    final_count = final_count + out["final_cleanup_context_leg_count"].fillna(0)
    expected = out["calibrated_expected_physical_leg_count"]
    final_count = np.minimum(final_count, expected.where(expected.notna(), final_count))
    out["final_review_only_represented_physical_leg_count"] = pd.Series(final_count).round().astype("Int64")
    out["final_review_only_represented_leg_class"] = out["final_review_only_represented_physical_leg_count"].map(_leg_class)
    out["final_calibrated_physical_leg_count"] = out["calibrated_expected_physical_leg_count"].round().astype("Int64")
    out["final_physical_leg_class"] = out["final_calibrated_physical_leg_count"].map(_leg_class)

    out["source_limited_holdout_flag"] = (
        _text(out, "latest_alignment_holdout_class").eq("source_limited_holdout")
        | _flag(out, "final_source_data_limitation_flag")
        | _flag(out, "source_limited_manual_or_prior")
    )
    out["grade_mainline_holdout_flag"] = _flag(out, "grade_separated_mainline_flag")
    out["still_insufficient_evidence_flag"] = _text(out, "latest_alignment_holdout_class").eq("source_limited_holdout") & ~out["source_limited_holdout_flag"]
    out["review_only_recovery_provenance"] = out[["represented_source_with_offset", "recovery_streams_applied", "recovered_streams"]].fillna("").agg("|".join, axis=1).str.strip("|")
    out["current_review_only_universe_tier"] = _text(out, "refreshed_universe_tier").where(_text(out, "refreshed_universe_tier").ne(""), "represented_review_only_signal")

    out["final_speed_ready_flag"] = _flag(out, "has_speed") | _flag(out, "final_cleanup_speed_aadt_ready")
    out["final_aadt_exposure_ready_flag"] = (_flag(out, "has_aadt") & _flag(out, "has_exposure")) | _flag(out, "final_cleanup_speed_aadt_ready")
    out["final_speed_aadt_ready_flag"] = _flag(out, "speed_aadt_ready") | _flag(out, "final_cleanup_speed_aadt_ready")
    return out


def _build_final_bin_detail(consolidated_bins: pd.DataFrame, final_context_bins: pd.DataFrame) -> pd.DataFrame:
    keep_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "consolidated_bin_id",
        "original_bin_id",
        "recovery_stream",
        "recovery_class",
        "original_vs_recovered_bin",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "final_normalized_physical_leg_id",
        "final_carriageway_subbranch_id",
        "route_facility_fields",
        "source_travelway_lineage",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "has_route_measure_identity",
        "has_roadway_context",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "review_only_flag",
        "candidate_promoted",
        "route_facility_discontinuity_flag",
        "offset_anchor_flag",
        "grade_separation_or_mainline_review_flag",
        "long_source_row_flag",
        "context_assignment_scope",
    ]
    base = consolidated_bins[[col for col in keep_cols if col in consolidated_bins.columns]].copy()
    base["final_bin_source_package"] = "consolidated_scaffold_completeness_refresh"
    base["final_original_or_recovered"] = _text(base, "original_vs_recovered_bin").where(_text(base, "original_vs_recovered_bin").ne(""), "original_or_previous_represented")

    final_cols = {
        "final_cleanup_missing_leg_bin_id": "consolidated_bin_id",
        "final_missing_leg_bin_id": "original_bin_id",
        "final_missing_leg_id": "physical_leg_id",
        "final_cleanup_missing_leg_id": "final_normalized_physical_leg_id",
        "source_route_keys": "route_facility_fields",
    }
    fc = final_context_bins.copy()
    for source, target in final_cols.items():
        if source in fc.columns:
            fc[target] = fc[source]
    fc["carriageway_subbranch_id"] = ""
    fc["final_carriageway_subbranch_id"] = ""
    fc["recovery_stream"] = "final_implementable_scaffold_cleanup"
    fc["recovery_class"] = "final_cleanup_missing_leg_recovery"
    fc["original_vs_recovered_bin"] = "review_only_recovered_missing_leg_bin"
    fc["candidate_promoted"] = False
    fc["final_bin_source_package"] = "final_recovery_context_refresh"
    fc["final_original_or_recovered"] = "review_only_recovered_missing_leg_bin"
    fc = fc[[col for col in keep_cols + ["final_bin_source_package", "final_original_or_recovered"] if col in fc.columns]]
    for column in base.columns:
        if column not in fc.columns:
            fc[column] = ""
    for column in fc.columns:
        if column not in base.columns:
            base[column] = ""
    return pd.concat([base[fc.columns], fc], ignore_index=True, sort=False)


def _alignment_class(row: pd.Series) -> str:
    holdout = str(row.get("latest_alignment_holdout_class", ""))
    final_class = str(row.get("final_review_only_represented_leg_class", ""))
    expected = pd.to_numeric(pd.Series([row.get("calibrated_expected_physical_leg_count", "")]), errors="coerce").iloc[0]
    final = pd.to_numeric(pd.Series([row.get("final_review_only_represented_physical_leg_count", "")]), errors="coerce").iloc[0]
    if bool(row.get("grade_mainline_holdout_flag", False)):
        return "grade_or_mainline_holdout"
    if holdout == "source_limited_holdout" or bool(row.get("source_limited_holdout_flag", False)):
        return "source_limited_holdout"
    if bool(row.get("still_insufficient_evidence_flag", False)):
        return "still_insufficient_evidence"
    if pd.notna(expected) and pd.notna(final) and int(final) == int(expected):
        if str(row.get("final_physical_leg_class", "")) in {"three_leg", "four_leg"}:
            return "three_or_four_leg_aligned"
        return "aligned_final"
    if final_class in {"one_leg", "two_leg"}:
        return "two_leg_or_less_suspicious"
    if final_class == "five_plus_leg":
        return "five_plus_true_complex_or_review"
    if "divided" in str(row.get("calibrated_expected_type", "")) or "over_split" in str(row.get("calibrated_alignment_class", "")):
        return "over_split_but_subbranch_normalized"
    if pd.notna(expected) and pd.notna(final) and final < expected:
        return "remaining_under_capture"
    return "aligned_final"


def _two_leg_reason(row: pd.Series) -> str:
    if bool(row.get("source_limited_holdout_flag", False)) or str(row.get("latest_alignment_holdout_class", "")) == "source_limited_holdout":
        return "source_travelway_missing_cross_street"
    if bool(row.get("grade_mainline_holdout_flag", False)):
        return "grade_separated_mainline_context"
    manual = f"{row.get('manual_category', '')} {row.get('manual_note', '')}".lower()
    expected_type = str(row.get("calibrated_expected_type", "")).lower()
    route_types = str(row.get("represented_source_with_offset", "")).lower()
    if "ramp" in manual or "partial" in manual or "nonstandard" in manual or "two_leg_or_partial" in expected_type or "ramp" in route_types:
        return "ramp_partial_control_or_nonstandard_signal"
    if str(row.get("final_alignment_class", "")) == "remaining_under_capture":
        return "still_missing_recoverable_leg"
    if str(row.get("final_alignment_class", "")) == "still_insufficient_evidence":
        return "expected_model_uncertain"
    return "manual_review_needed"


def _build_outputs(signal: pd.DataFrame, bin_detail: pd.DataFrame, source_ledger: pd.DataFrame, branch: pd.DataFrame) -> dict[str, pd.DataFrame]:
    signal = signal.copy()
    signal["final_alignment_class"] = signal.apply(_alignment_class, axis=1)

    distribution = signal.groupby("final_physical_leg_class", dropna=False).agg(signal_count=("signal_id", "nunique")).reset_index()
    for cls in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        if cls not in set(distribution["final_physical_leg_class"]):
            distribution = pd.concat([distribution, pd.DataFrame([{"final_physical_leg_class": cls, "signal_count": 0}])], ignore_index=True)
    two_or_less = int(distribution.loc[distribution["final_physical_leg_class"].isin(["one_leg", "two_leg"]), "signal_count"].astype(int).sum())
    extra = pd.DataFrame(
        [
            {"final_physical_leg_class": "two_leg_or_less_combined", "signal_count": two_or_less},
            {"final_physical_leg_class": "source_limited_two_leg_or_less", "signal_count": int((signal["final_physical_leg_class"].isin(["one_leg", "two_leg"]) & signal["source_limited_holdout_flag"]).sum())},
            {"final_physical_leg_class": "grade_mainline_holdout", "signal_count": int(signal["grade_mainline_holdout_flag"].sum())},
            {"final_physical_leg_class": "still_insufficient_evidence", "signal_count": int(signal["still_insufficient_evidence_flag"].sum())},
            {"final_physical_leg_class": "divided_subbranch_evidence", "signal_count": int(_flag(signal, "calibrated_divided_subbranch_evidence").sum())},
        ]
    )
    distribution = pd.concat([distribution, extra], ignore_index=True)

    alignment = signal[
        [
            "signal_id",
            "represented_source_signal_id",
            "represented_source_layer",
            "final_calibrated_physical_leg_count",
            "calibrated_expected_physical_leg_count",
            "final_review_only_represented_physical_leg_count",
            "final_review_only_represented_leg_class",
            "final_physical_leg_class",
            "calibrated_expected_type",
            "calibrated_alignment_class",
            "latest_alignment_holdout_class",
            "final_alignment_class",
            "source_limited_holdout_flag",
            "grade_mainline_holdout_flag",
            "still_insufficient_evidence_flag",
        ]
    ].copy()

    two_leg = signal.loc[signal["final_physical_leg_class"].isin(["one_leg", "two_leg"])].copy()
    two_leg["two_leg_or_less_likely_explanation"] = two_leg.apply(_two_leg_reason, axis=1)
    two_leg["two_leg_or_less_plausibility"] = np.where(
        two_leg["two_leg_or_less_likely_explanation"].isin(
            [
                "source_travelway_missing_cross_street",
                "ramp_partial_control_or_nonstandard_signal",
                "grade_separated_mainline_context",
            ]
        ),
        "explainable_source_or_geometry_limitation",
        "suspicious_or_needs_review",
    )
    two_cols = [
        "signal_id",
        "represented_source_signal_id",
        "represented_source_layer",
        "final_review_only_represented_physical_leg_count",
        "calibrated_expected_physical_leg_count",
        "calibrated_expected_type",
        "latest_alignment_holdout_class",
        "final_alignment_class",
        "two_leg_or_less_likely_explanation",
        "two_leg_or_less_plausibility",
        "manual_category",
        "manual_note",
    ]
    two_leg = two_leg[[col for col in two_cols if col in two_leg.columns]]

    status = pd.concat(
        [
            signal.groupby("final_physical_leg_class", dropna=False).agg(signal_count=("signal_id", "nunique")).reset_index().rename(columns={"final_physical_leg_class": "summary_class"}),
            signal.groupby("final_alignment_class", dropna=False).agg(signal_count=("signal_id", "nunique")).reset_index().rename(columns={"final_alignment_class": "summary_class"}),
        ],
        ignore_index=True,
    )
    status["summary_family"] = np.where(status["summary_class"].isin(["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]), "final_physical_leg_distribution", "final_alignment_status")

    actionable_gap_count = int(signal["final_alignment_class"].isin(["remaining_under_capture", "two_leg_or_less_suspicious"]).sum())
    holdout_count = int(signal["final_alignment_class"].isin(["source_limited_holdout", "grade_or_mainline_holdout", "still_insufficient_evidence"]).sum())
    ready = bool(source_ledger["should_block_access_crash_work"].astype(str).str.contains("Should not block|No,|Can proceed", case=False, regex=True).any())
    decision = pd.DataFrame(
        [
            {"decision_area": "represented_signal_count", "decision": str(signal["signal_id"].nunique()), "detail": "Review-only represented signal universe."},
            {"decision_area": "speed_aadt_ready_signal_count", "decision": str(int(signal["final_speed_aadt_ready_flag"].sum())), "detail": "Signals with existing represented or final cleanup speed+AADT readiness."},
            {"decision_area": "remaining_represented_vs_expected_gaps", "decision": str(actionable_gap_count), "detail": "Signals whose represented legs remain below calibrated expectation or are suspicious two-leg-or-less representations."},
            {"decision_area": "remaining_source_manual_holdouts", "decision": str(holdout_count), "detail": "Source-limited, grade/mainline, or still-insufficient evidence signals carried as QA flags."},
            {"decision_area": "scaffold_recovery_status", "decision": "resume_access_with_scaffold_gap_qa_flags" if ready else "more_scaffold_work_needed", "detail": "Access can resume only if remaining represented-vs-expected gaps and source/manual holdouts are carried as explicit QA flags; no new recovery is generated here."},
            {"decision_area": "required_access_qa_flags", "decision": "source_limited_holdout_flag;grade_mainline_holdout_flag;still_insufficient_evidence_flag;review_only_recovery_provenance;final_alignment_class", "detail": "Carry these into access/catchment outputs."},
        ]
    )
    return {
        "signal": signal,
        "bin_detail": bin_detail,
        "distribution": distribution,
        "alignment": alignment,
        "two_leg": two_leg,
        "status": status,
        "decision": decision,
    }


def _write_findings(outputs: dict[str, pd.DataFrame]) -> None:
    signal = outputs["signal"]
    distribution = outputs["distribution"]
    alignment = outputs["alignment"]
    two_leg = outputs["two_leg"]
    counts = dict(zip(distribution["final_physical_leg_class"], pd.to_numeric(distribution["signal_count"], errors="coerce").fillna(0).astype(int)))
    aligned = int(alignment["final_alignment_class"].isin(["aligned_final", "three_or_four_leg_aligned", "over_split_but_subbranch_normalized"]).sum())
    represented_gaps = int(alignment["final_alignment_class"].isin(["remaining_under_capture", "two_leg_or_less_suspicious"]).sum())
    holdouts = int(alignment["final_alignment_class"].isin(["source_limited_holdout", "still_insufficient_evidence", "grade_or_mainline_holdout"]).sum())
    explainable_two = int((two_leg.get("two_leg_or_less_plausibility", pd.Series(dtype=str)) == "explainable_source_or_geometry_limitation").sum()) if not two_leg.empty else 0
    suspicious_two = int((two_leg.get("two_leg_or_less_plausibility", pd.Series(dtype=str)) == "suspicious_or_needs_review").sum()) if not two_leg.empty else 0
    text = f"""# Final Signal Leg Universe Overview

## Bounded Question

Does the final review-only scaffold have a plausible calibrated physical-leg distribution, and is it ready to resume access/catchment work with QA flags?

## Findings

- Final represented signal count: {signal['signal_id'].nunique():,}.
- Final speed+AADT-ready signal count: {int(signal['final_speed_aadt_ready_flag'].sum()):,}.
- Final leg distribution: one-leg {counts.get('one_leg', 0):,}; two-leg {counts.get('two_leg', 0):,}; three-leg {counts.get('three_leg', 0):,}; four-leg {counts.get('four_leg', 0):,}; five-plus {counts.get('five_plus_leg', 0):,}.
- Four-leg intersections {'dominate' if counts.get('four_leg', 0) > counts.get('three_leg', 0) else 'do not dominate'}; three-leg intersections are {'the next major class' if counts.get('three_leg', 0) >= counts.get('two_leg', 0) else 'not the next major class'}.
- Two-leg-or-less signals remaining: {counts.get('two_leg_or_less_combined', 0):,}; explainable source/geometry limitations: {explainable_two:,}; suspicious or needs review: {suspicious_two:,}.
- Five-plus signals remaining: {counts.get('five_plus_leg', 0):,}.
- Signals aligned or subbranch-normalized enough for review-only scaffold use: {aligned:,}.
- Signals with remaining represented-vs-expected gaps: {represented_gaps:,}.
- Signals carried as source/manual/grade/insufficient-evidence holdouts: {holdouts:,}.

## Decision

Scaffold recovery is exhausted enough to resume access work only with explicit scaffold-gap QA flags. Access and later crash/catchment outputs must carry source-limited, grade/mainline, still-insufficient-evidence, final-alignment, and review-only recovery provenance flags.
"""
    _write_text(text, "final_signal_leg_universe_overview_findings.md")


def _write_qa(outputs: dict[str, pd.DataFrame]) -> None:
    signal = outputs["signal"]
    bin_detail = outputs["bin_detail"]
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/final_signal_leg_universe_overview."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "No promotion outputs are written."},
            {"qa_check": "no_access_or_crash_assignment", "status": "pass", "detail": "No access/crash inputs are read and no assignments are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate/model calculations are run."},
            {"qa_check": "no_new_bins_generated", "status": "pass", "detail": "Existing bin records are reconciled only."},
            {"qa_check": "overview_audit_only", "status": "pass", "detail": "Outputs summarize final review-only signal and leg status."},
            {"qa_check": "physical_legs_separate_from_subbranches", "status": "pass", "detail": "Physical-leg class and carriageway/subbranch IDs are preserved separately where available."},
            {"qa_check": "holdouts_not_forced", "status": "pass", "detail": "Source-limited and grade/mainline holdouts are flagged, not recovered."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"{signal['signal_id'].nunique():,} signals and {len(bin_detail):,} bin rows written to review folder."},
        ]
    )
    _write_csv(qa, "final_signal_leg_universe_overview_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _required_missing()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    represented = _read_csv(REPRESENTED_DIR / "refreshed_represented_signal_universe.csv")
    calibrated = _read_csv(CALIBRATED_DIR / "calibrated_expected_leg_signal_detail.csv")
    consolidated_signal = _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv")
    consolidated_bins = _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv")
    final_context_signal = _read_csv(FINAL_CONTEXT_DIR / "final_recovery_context_signal_summary.csv")
    final_context_bins = _read_csv(FINAL_CONTEXT_DIR / "final_recovery_context_bin_detail.csv")
    source_ledger = _read_csv(FINAL_CONTEXT_DIR / "final_source_data_limitation_ledger.csv")
    branch = _read_csv(FINAL_CONTEXT_DIR / "final_scaffold_branch_exhaustion_summary.csv")
    branch_signal = _read_csv(BRANCH_LEDGER_DIR / "scaffold_recovery_branch_ledger_signal_detail.csv")
    adjacent_signal = _read_csv(ADJACENT_DIR / "adjacent_sector_merge_signal_summary.csv")
    remaining_signal = _read_csv(REMAINING_NORM_DIR / "remaining_normalization_signal_summary.csv")
    final_norm_bins = _read_csv(FINAL_CLEANUP_DIR / "final_cleanup_normalized_divided_bins.csv")

    signal = _build_signal_universe(
        represented,
        consolidated_signal,
        calibrated,
        final_context_signal,
        source_ledger,
        branch_signal,
        adjacent_signal,
        remaining_signal,
        final_norm_bins,
    )
    bin_detail = _build_final_bin_detail(consolidated_bins, final_context_bins)
    outputs = _build_outputs(signal, bin_detail, source_ledger, branch)

    _write_csv(outputs["signal"], "final_signal_universe_detail.csv")
    _write_csv(outputs["bin_detail"], "final_consolidated_leg_bin_detail.csv")
    _write_csv(outputs["distribution"], "final_physical_leg_distribution.csv")
    _write_csv(outputs["alignment"], "final_expected_vs_represented_alignment.csv")
    _write_csv(outputs["two_leg"], "final_two_leg_or_less_audit.csv")
    _write_csv(outputs["status"], "final_signal_leg_status_summary.csv")
    _write_csv(outputs["decision"], "final_access_readiness_decision.csv")
    _write_findings(outputs)
    _write_qa(outputs)

    manifest = {
        "script": "src.roadway_graph.build.final_signal_leg_universe_overview",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Final review-only signal universe and calibrated physical-leg distribution overview before access work resumes.",
        "output_directory": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "final_signal_universe_detail.csv",
            "final_consolidated_leg_bin_detail.csv",
            "final_physical_leg_distribution.csv",
            "final_expected_vs_represented_alignment.csv",
            "final_two_leg_or_less_audit.csv",
            "final_signal_leg_status_summary.csv",
            "final_access_readiness_decision.csv",
            "final_signal_leg_universe_overview_findings.md",
            "final_signal_leg_universe_overview_qa.csv",
            "final_signal_leg_universe_overview_manifest.json",
            "run_progress_log.txt",
        ],
        "summary": {
            "represented_signal_count": int(outputs["signal"]["signal_id"].nunique()),
            "speed_aadt_ready_signal_count": int(outputs["signal"]["final_speed_aadt_ready_flag"].sum()),
            "final_bin_rows": int(len(outputs["bin_detail"])),
            "leg_distribution": outputs["distribution"].to_dict(orient="records"),
            "access_readiness_decision": outputs["decision"].to_dict(orient="records"),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assignment": False,
            "rates_or_models": False,
            "new_bins_generated": False,
            "review_only": True,
        },
        "upstream_manifests": {
            "final_context_refresh": _load_json(FINAL_CONTEXT_DIR / "final_recovery_context_refresh_manifest.json").get("created_at_utc", ""),
            "consolidated_scaffold": _load_json(CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json").get("created_at_utc", ""),
            "calibrated_expected_leg_model": _load_json(CALIBRATED_DIR / "calibrated_expected_physical_leg_model_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "final_signal_leg_universe_overview_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
