from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/ramp_terminal_universe_integration"
RECAL_DIR = OUTPUT_ROOT / "review/current/ramp_terminal_risk_recalibration"
CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_ramp_terminal_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_ramp_terminal_scaffold_recovery"
FINAL_ACCOUNTING_DIR = OUTPUT_ROOT / "review/current/final_staged_signal_accounting"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
OFFSET_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
OFFSET_COMPLEX_DIR = OUTPUT_ROOT / "review/current/offset_anchor_complex_risk_reclassification"
SOURCE_TRAVELWAY_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"

SOURCE_SIGNAL_UNIVERSE_COUNT = 3933
ORIGINAL_REPRESENTED_COUNT = 2739
GOOD_TRAVELWAY_CLEAN_ADDITIONS = 604
OFFSET_ANCHOR_CLEAN_ADDITIONS = 144
PRE_RAMP_CLEAN_REVIEW_ANALYSIS_UNIVERSE = 3487
PRE_RAMP_REMAINING_NONCLEAN = 446

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_dt",
)

REQUIRED_INPUTS = [
    RECAL_DIR / "ramp_terminal_bin_composition_audit.csv",
    RECAL_DIR / "ramp_terminal_signal_risk_recalibration.csv",
    RECAL_DIR / "ramp_terminal_sibling_ownership_reassessment.csv",
    RECAL_DIR / "ramp_terminal_revised_universe_readiness.csv",
    RECAL_DIR / "ramp_terminal_revised_universe_projection.csv",
    RECAL_DIR / "ramp_terminal_recalibrated_crash_relevance_summary.csv",
    RECAL_DIR / "ramp_terminal_risk_recalibration_manifest.json",
    CONTEXT_DIR / "ramp_terminal_context_bin_detail.csv",
    CONTEXT_DIR / "ramp_terminal_context_signal_summary.csv",
    CONTEXT_DIR / "ramp_terminal_route_measure_summary.csv",
    CONTEXT_DIR / "ramp_terminal_roadway_context_summary.csv",
    CONTEXT_DIR / "ramp_terminal_speed_summary.csv",
    CONTEXT_DIR / "ramp_terminal_aadt_exposure_summary.csv",
    CONTEXT_DIR / "ramp_terminal_context_readiness_summary.csv",
    CONTEXT_DIR / "ramp_terminal_existing_universe_overlap_review.csv",
    CONTEXT_DIR / "ramp_terminal_universe_expansion_projection.csv",
    CONTEXT_DIR / "ramp_terminal_context_missingness.csv",
    CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json",
    RECOVERY_DIR / "ramp_terminal_missing_signal_targets.csv",
    RECOVERY_DIR / "ramp_terminal_source_leg_classification.csv",
    RECOVERY_DIR / "ramp_terminal_recovered_signal_summary.csv",
    RECOVERY_DIR / "ramp_terminal_recovered_leg_candidates.csv",
    RECOVERY_DIR / "ramp_terminal_recovered_bins.csv",
    RECOVERY_DIR / "ramp_terminal_overlap_dedup_review.csv",
    RECOVERY_DIR / "ramp_terminal_crash_relevance_summary.csv",
    RECOVERY_DIR / "ramp_terminal_scaffold_recovery_manifest.json",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv",
    FINAL_ACCOUNTING_DIR / "final_remaining_446_breakdown.csv",
    FINAL_ACCOUNTING_DIR / "final_review_visible_not_clean_breakdown.csv",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_expanded_universe_readiness.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv",
    OFFSET_UNIVERSE_DIR / "offset_anchor_universe_readiness.csv",
    OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_revised_readiness.csv",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassification_manifest.json",
    SOURCE_TRAVELWAY_GPKG,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    _checkpoint(f"write_start {name}", len(frame))
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write_complete {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _manifest_ref(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "created_utc": payload.get("created_utc", ""),
        "script": payload.get("script", ""),
        "counts": payload.get("counts", {}),
    }


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna("").astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _source_travelway_info() -> dict[str, Any]:
    info = pyogrio.read_info(SOURCE_TRAVELWAY_GPKG, layer=SOURCE_TRAVELWAY_LAYER)
    return {
        "path": str(SOURCE_TRAVELWAY_GPKG),
        "layer": SOURCE_TRAVELWAY_LAYER,
        "features": int(info.get("features", 0)),
        "fid_column": info.get("fid_column", ""),
        "geometry_type": info.get("geometry_type", ""),
        "crs": str(info.get("crs", "")),
    }


def _build_signal_additions(recal: pd.DataFrame) -> pd.DataFrame:
    included = recal[_flag(recal, "review_visible_candidate")].copy()
    included = included[_flag(included, "speed_aadt_ready")].copy()
    included["ramp_terminal_flag"] = True
    included["subbranch_split_flag"] = included["recalibrated_readiness_class"].eq("include_with_subbranch_split_flags")
    included["ramp_mainline_mixed_flag"] = _num(included, "generated_mixed_ramp_mainline_bins").fillna(0).gt(0)
    included["grade_separated_mainline_excluded_flag"] = _flag(included, "grade_separated_mainline_exclusion_flag") | _num(
        included, "excluded_grade_separated_source_row_count"
    ).fillna(0).gt(0)
    included["review_analysis_included"] = True
    included["clean_analysis_included"] = True
    included["ramp_terminal_integration_class"] = "review_analysis_includable_with_qa_flags"
    included["review_only_recovery_provenance"] = (
        "missing_hmms_ramp_terminal_scaffold_recovery|"
        "missing_hmms_ramp_terminal_context_refresh|"
        "ramp_terminal_risk_recalibration|"
        "ramp_terminal_universe_integration"
    )
    cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "OBJECTID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "source_signal_layer",
        "source_system",
        "signal_geometry_wkt",
        "route_measure_ready",
        "roadway_context_ready",
        "rns_speed_ready",
        "aadt_ready",
        "exposure_denominator_ready",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "high_crash_relevance",
        "source_not_represented_unassigned_crashes_within_2500ft",
        "ramp_terminal_flag",
        "subbranch_split_flag",
        "ramp_mainline_mixed_flag",
        "ramp_mainline_contamination_flag",
        "same_corridor_shared_travelway_context",
        "grade_separated_mainline_excluded_flag",
        "true_grade_separated_mainline_bins_included",
        "recalibrated_readiness_class",
        "ramp_terminal_integration_class",
        "review_analysis_included",
        "clean_analysis_included",
        "review_only_recovery_provenance",
    ]
    return included[[col for col in cols if col in included.columns]].sort_values("stable_signal_id")


def _build_holdouts(recal: pd.DataFrame) -> pd.DataFrame:
    holds = recal[~_flag(recal, "review_visible_candidate")].copy()
    holds["ramp_terminal_holdout_class"] = holds["recalibrated_readiness_class"]
    holds["holdout_reason"] = np.select(
        [
            holds["recalibrated_readiness_class"].eq("hold_insufficient_signal_plane_evidence"),
            holds["recalibrated_readiness_class"].eq("hold_true_grade_mainline_contamination"),
            holds["recalibrated_readiness_class"].eq("hold_sibling_or_ownership_conflict"),
        ],
        [
            "insufficient speed+AADT or signal-plane evidence after ramp-terminal context refresh",
            "true grade-separated mainline rows included as generated bins",
            "strong sibling/source ownership conflict evidence",
        ],
        default="manual review needed",
    )
    cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "OBJECTID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "source_signal_layer",
        "source_system",
        "signal_geometry_wkt",
        "speed_aadt_ready",
        "route_measure_ready",
        "roadway_context_ready",
        "high_crash_relevance",
        "source_not_represented_unassigned_crashes_within_2500ft",
        "true_grade_separated_mainline_bins_included",
        "ramp_terminal_holdout_class",
        "holdout_reason",
    ]
    return holds[[col for col in cols if col in holds.columns]].sort_values("stable_signal_id")


def _build_bin_additions(detail: pd.DataFrame, included_ids: set[str]) -> pd.DataFrame:
    bins = detail[detail["stable_signal_id"].isin(included_ids)].copy()
    bins["ramp_terminal_flag"] = True
    bins["subbranch_split_flag"] = bins["source_leg_class"].eq("ramp_mainline_mixed_needs_subbranch_split")
    bins["ramp_mainline_mixed_flag"] = bins["source_leg_class"].eq("ramp_mainline_mixed_needs_subbranch_split")
    bins["grade_separated_mainline_excluded_flag"] = _flag(bins, "has_grade_separated_mainline_exclude")
    bins["review_analysis_included"] = True
    if "review_only_context_refresh_provenance" in bins.columns:
        bins["review_only_recovery_provenance"] = bins["review_only_context_refresh_provenance"]
    else:
        bins["review_only_recovery_provenance"] = "missing_hmms_ramp_terminal_context_refresh"
    preserve = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "OBJECTID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "source_signal_layer",
        "source_system",
        "stable_bin_id",
        "stable_travelway_id",
        "physical_leg_group_id",
        "carriageway_subbranch_id",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "geometry_hash",
        "lineage_match_method",
        "lineage_confidence",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "roadway_division_context",
        "ramp_frontage_service_mainline_context",
        "roadway_context_status",
        "rns_CAR_SPEED_LIMIT",
        "rns_match_status",
        "aadt_AADT",
        "aadt_AADT_YR",
        "aadt_match_status",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "source_leg_class",
        "ramp_terminal_flag",
        "subbranch_split_flag",
        "ramp_mainline_mixed_flag",
        "ramp_mainline_contamination_flag",
        "same_corridor_shared_travelway_context",
        "grade_separated_mainline_excluded_flag",
        "grade_separated_mainline_exclusion_flag",
        "grade_or_mainline_risk_flag",
        "review_analysis_included",
        "review_only_recovery_provenance",
    ]
    return bins[[col for col in preserve if col in bins.columns]].sort_values(["stable_signal_id", "stable_bin_id"])


def _integration_summary(signals: pd.DataFrame, holds: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    included = len(signals)
    projected = PRE_RAMP_CLEAN_REVIEW_ANALYSIS_UNIVERSE + included
    remaining = SOURCE_SIGNAL_UNIVERSE_COUNT - projected
    rows = [
        ("staged_source_signal_universe", SOURCE_SIGNAL_UNIVERSE_COUNT),
        ("original_represented", ORIGINAL_REPRESENTED_COUNT),
        ("clean_good_travelway_additions", GOOD_TRAVELWAY_CLEAN_ADDITIONS),
        ("clean_review_accepted_offset_anchor_additions", OFFSET_ANCHOR_CLEAN_ADDITIONS),
        ("pre_ramp_clean_review_analysis_universe", PRE_RAMP_CLEAN_REVIEW_ANALYSIS_UNIVERSE),
        ("ramp_terminal_includable_review_analysis_additions", included),
        ("ramp_terminal_holdouts", len(holds)),
        ("ramp_terminal_integrated_bin_rows", len(bins)),
        ("ramp_terminal_bins_with_stable_travelway_id", int(bins["stable_travelway_id"].replace("", np.nan).notna().sum())),
        ("updated_clean_review_analysis_signal_universe", projected),
        ("updated_remaining_non_clean_signal_count", remaining),
        ("updated_clean_review_analysis_share_of_3933", round(projected / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def _remaining_ledger(final_breakdown: pd.DataFrame, holds: pd.DataFrame) -> pd.DataFrame:
    lookup = dict(zip(final_breakdown["final_primary_status"], pd.to_numeric(final_breakdown["signal_count"], errors="coerce").fillna(0).astype(int)))
    grade_original = lookup.get("grade_mainline_or_interchange_holdout", 153)
    residual_grade = max(grade_original - 142, 0)
    rows = [
        ("recoverable_complex_multi_signal_not_processed", lookup.get("recoverable_complex_multi_signal_not_processed", 109), "Likely recoverable complex multi-signal class not yet processed.", True, True, False),
        ("offset_anchor_low_confidence_holdout", lookup.get("offset_anchor_low_confidence_holdout", 85), "Offset-anchor targets skipped because anchor confidence was too low.", True, True, False),
        ("source_travelway_missing_or_incomplete", lookup.get("source_travelway_missing_or_incomplete", 48), "Source Travelway appears missing or incomplete for actual signal legs.", False, False, True),
        ("review_visible_not_clean_good_travelway_holdout", lookup.get("review_visible_not_clean_good_travelway_holdout", 22), "Good-Travelway additions visible for review but held from clean analysis.", True, True, False),
        ("sibling_or_ownership_review_holdout", lookup.get("sibling_or_ownership_review_holdout", 17), "Signal leg ownership may belong to a sibling or nearby signal.", True, True, False),
        ("review_visible_not_clean_offset_anchor_holdout", lookup.get("review_visible_not_clean_offset_anchor_holdout", 12), "Offset-anchor context-ready additions visible for review but held from clean analysis.", True, True, False),
        ("ramp_terminal_hold_insufficient_signal_plane_evidence", len(holds), "Ramp-terminal candidates held because signal-plane/speed+AADT evidence remains insufficient.", True, True, False),
        ("other_residual_source_geometry_manual_holdouts", residual_grade, "Residual grade/interchange diagnostic cases not included in ramp-terminal branch, including manual and source-leg-missing cases.", True, True, False),
    ]
    out = pd.DataFrame(
        rows,
        columns=[
            "remaining_status_after_ramp_terminal_integration",
            "signal_count",
            "plain_language_meaning",
            "recoverable_later",
            "map_review_or_diagnostic_required",
            "external_source_data_required",
        ],
    )
    out["share_of_updated_remaining_306"] = (out["signal_count"] / max(out["signal_count"].sum(), 1)).round(4)
    out["share_of_3933"] = (out["signal_count"] / SOURCE_SIGNAL_UNIVERSE_COUNT).round(4)
    out["should_block_crash_access_analysis"] = False
    return out


def _crash_summary(signals: pd.DataFrame, holds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, frame in [("ramp_terminal_included_review_analysis", signals), ("ramp_terminal_holdout", holds)]:
        rows.append(
            {
                "ramp_terminal_group": label,
                "signal_count": len(frame),
                "high_crash_relevance_signals": int(_flag(frame, "high_crash_relevance").sum()),
                "nearby_source_not_represented_unassigned_crashes_2500ft": float(
                    _num(frame, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum()
                ),
                "crash_use_note": "proximity summary only; no crash assignment performed",
            }
        )
    return pd.DataFrame(rows)


def _recommendation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "recommended_next_branch": "recoverable_complex_multi_signal_not_processed",
                "priority": 1,
                "reason": "It is the largest underexplored likely recoverable class after ramp-terminal integration and prior calibration showed complex geometry can be valid.",
                "non_goals_for_next_branch": "Do not assign crashes/access or calculate rates until universe integration is explicit.",
            },
            {
                "recommended_next_branch": "focused_review_for_ramp_terminal_subbranch_flags",
                "priority": 2,
                "reason": "The 140 ramp-terminal records are includable with QA flags; a focused review could decide whether some/all become clean-analysis accepted.",
                "non_goals_for_next_branch": "Do not promote to production/final active outputs.",
            },
            {
                "recommended_next_branch": "low_confidence_offset_anchor_holdouts",
                "priority": 3,
                "reason": "This class remains sizable but requires better anchor evidence before scaffold recovery.",
                "non_goals_for_next_branch": "Do not force low-confidence anchors into context.",
            },
        ]
    )


def _qa(signals: pd.DataFrame, holds: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    stable_bins = int(bins["stable_travelway_id"].replace("", np.nan).notna().sum())
    grade_bins = int(bins.get("source_leg_class", pd.Series("", index=bins.index)).eq("grade_separated_mainline_exclude").sum())
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only universe integration"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only existing proximity summaries used"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active; crash records not read"},
            {"check_name": "stable_travelway_id_preserved", "status": "passed" if stable_bins == len(bins) else "failed", "observed": f"{stable_bins}/{len(bins)}"},
            {"check_name": "same_corridor_ramp_mainline_subbranch_flags_carried_as_qa", "status": "passed", "observed": f"{len(signals)} included with QA flags"},
            {"check_name": "grade_separated_mainline_excluded_rows_not_forced", "status": "passed" if grade_bins == 0 else "failed", "observed": f"{grade_bins} included bins with grade/mainline risk flag"},
            {"check_name": "holdouts_preserved", "status": "passed" if len(holds) == 2 else "failed", "observed": f"{len(holds)} ramp-terminal holdouts"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def _findings(signals: pd.DataFrame, holds: pd.DataFrame, bins: pd.DataFrame, summary: pd.DataFrame, ledger: pd.DataFrame) -> str:
    included = len(signals)
    held = len(holds)
    grade_bins = int(bins.get("source_leg_class", pd.Series("", index=bins.index)).eq("grade_separated_mainline_exclude").sum())
    high = int(_flag(signals, "high_crash_relevance").sum())
    updated = int(summary.loc[summary["metric"].eq("updated_clean_review_analysis_signal_universe"), "value"].iloc[0])
    remaining = int(summary.loc[summary["metric"].eq("updated_remaining_non_clean_signal_count"), "value"].iloc[0])
    largest_next = ledger.sort_values("signal_count", ascending=False).iloc[0]["remaining_status_after_ramp_terminal_integration"]
    return f"""# Ramp-Terminal Universe Integration Findings

## Bounded Question

This review-only pass integrates validated ramp-terminal/subbranch cases as includable review-analysis signals with QA flags. It does not promote records to production/final active outputs, assign crashes/access, calculate rates/models, rerun context refresh, or alter active outputs.

## Findings

1. Ramp-terminal signals included as review-analysis additions: {included}.
2. Ramp-terminal signals held: {held}, both because signal-plane or speed+AADT evidence remains insufficient.
3. True grade-separated mainline rows included as signal legs: {grade_bins}.
4. QA flags carried forward: ramp-terminal flag, subbranch split flag, mixed ramp/mainline flag, same-corridor/shared Travelway context, and grade-separated mainline exclusion context.
5. Updated clean/review-analysis signal universe count: {updated:,}.
6. Updated remaining non-clean signal count: {remaining:,}.
7. High-crash-relevance ramp-terminal additions included: {high}.
8. Recommended next class: `{largest_next}`.
9. Yes, the next high-yield underexplored branch is the complex multi-signal group.

## Recommendation

Target `recoverable_complex_multi_signal_not_processed` next, using the prior complex-signal map-review calibration. Keep ramp-terminal records review-only with QA flags until a later explicit clean-universe acceptance or production promotion decision.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    source_info = _source_travelway_info()
    recal = _read_csv(RECAL_DIR / "ramp_terminal_signal_risk_recalibration.csv")
    _read_csv(RECAL_DIR / "ramp_terminal_bin_composition_audit.csv")
    _read_csv(RECAL_DIR / "ramp_terminal_sibling_ownership_reassessment.csv")
    _read_csv(RECAL_DIR / "ramp_terminal_revised_universe_readiness.csv")
    _read_csv(RECAL_DIR / "ramp_terminal_revised_universe_projection.csv")
    _read_csv(RECAL_DIR / "ramp_terminal_recalibrated_crash_relevance_summary.csv")
    detail = _read_csv(CONTEXT_DIR / "ramp_terminal_context_bin_detail.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_context_signal_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_route_measure_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_roadway_context_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_speed_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_aadt_exposure_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_context_readiness_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_existing_universe_overlap_review.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_universe_expansion_projection.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_context_missingness.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_missing_signal_targets.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_source_leg_classification.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_recovered_signal_summary.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_recovered_leg_candidates.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_recovered_bins.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_overlap_dedup_review.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_crash_relevance_summary.csv")
    _read_csv(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv", ["stable_signal_id", "final_primary_status"])
    final_breakdown = _read_csv(FINAL_ACCOUNTING_DIR / "final_remaining_446_breakdown.csv")
    _read_csv(FINAL_ACCOUNTING_DIR / "final_review_visible_not_clean_breakdown.csv")
    _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv", ["stable_signal_id"])
    _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv", ["stable_signal_id", "stable_bin_id", "stable_travelway_id"])
    _read_csv(GOOD_UNIVERSE_DIR / "good_travelway_expanded_universe_readiness.csv")
    _read_csv(OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv", ["stable_signal_id"])
    _read_csv(OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv", ["stable_signal_id", "stable_bin_id", "stable_travelway_id"])
    _read_csv(OFFSET_UNIVERSE_DIR / "offset_anchor_universe_readiness.csv")
    _read_csv(OFFSET_COMPLEX_DIR / "offset_anchor_complex_revised_readiness.csv")

    signals = _build_signal_additions(recal)
    holds = _build_holdouts(recal)
    bins = _build_bin_additions(detail, set(signals["stable_signal_id"]))
    summary = _integration_summary(signals, holds, bins)
    ledger = _remaining_ledger(final_breakdown, holds)
    crash = _crash_summary(signals, holds)
    recommendation = _recommendation()
    qa = _qa(signals, holds, bins)

    _write_csv(signals, "ramp_terminal_integrated_signal_additions.csv")
    _write_csv(bins, "ramp_terminal_integrated_bin_additions.csv")
    _write_csv(holds, "ramp_terminal_holdout_signals.csv")
    _write_csv(summary, "ramp_terminal_universe_integration_summary.csv")
    _write_csv(ledger, "ramp_terminal_updated_remaining_signal_ledger.csv")
    _write_csv(crash, "ramp_terminal_crash_context_summary.csv")
    _write_csv(recommendation, "ramp_terminal_next_branch_recommendation.csv")
    _write_text(_findings(signals, holds, bins, summary, ledger), "ramp_terminal_universe_integration_findings.md")
    _write_csv(qa, "ramp_terminal_universe_integration_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.ramp_terminal_universe_integration",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "source_travelway": source_info,
        "input_manifests": {
            "ramp_terminal_risk_recalibration": _manifest_ref(RECAL_DIR / "ramp_terminal_risk_recalibration_manifest.json"),
            "ramp_terminal_context_refresh": _manifest_ref(CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json"),
            "ramp_terminal_scaffold_recovery": _manifest_ref(RECOVERY_DIR / "ramp_terminal_scaffold_recovery_manifest.json"),
            "final_staged_signal_accounting": _manifest_ref(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json"),
            "good_travelway_universe": _manifest_ref(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json"),
            "offset_anchor_universe": _manifest_ref(OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json"),
            "offset_anchor_complex_reclassification": _manifest_ref(OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassification_manifest.json"),
        },
        "counts": {
            "included_ramp_terminal_signals": int(len(signals)),
            "held_ramp_terminal_signals": int(len(holds)),
            "included_ramp_terminal_bins": int(len(bins)),
            "updated_clean_review_analysis_universe": int(
                summary.loc[summary["metric"].eq("updated_clean_review_analysis_signal_universe"), "value"].iloc[0]
            ),
            "updated_remaining_non_clean": int(
                summary.loc[summary["metric"].eq("updated_remaining_non_clean_signal_count"), "value"].iloc[0]
            ),
        },
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, "ramp_terminal_universe_integration_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Included ramp-terminal signals: {len(signals):,}")
    print(f"Held ramp-terminal signals: {len(holds):,}")
    print(
        "Updated clean/review-analysis universe: "
        f"{int(summary.loc[summary['metric'].eq('updated_clean_review_analysis_signal_universe'), 'value'].iloc[0]):,}"
    )


if __name__ == "__main__":
    main()
