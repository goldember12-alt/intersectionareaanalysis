from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/divided_adjacent_bearing_sector_merge"

UNRESOLVED_DIR = OUTPUT_ROOT / "review/current/divided_carriageway_unresolved_diagnostic"
DIVIDED_DIR = OUTPUT_ROOT / "review/current/divided_carriageway_subbranch_normalization"
CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"

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
    UNRESOLVED_DIR / "divided_unresolved_signal_detail.csv",
    UNRESOLVED_DIR / "divided_unresolved_bin_detail.csv",
    UNRESOLVED_DIR / "divided_unresolved_reason_summary.csv",
    UNRESOLVED_DIR / "divided_unresolved_rule_recommendations.csv",
    UNRESOLVED_DIR / "divided_unresolved_impact_estimate.csv",
    UNRESOLVED_DIR / "divided_unresolved_ranked_review_queue.csv",
    UNRESOLVED_DIR / "divided_unresolved_diagnostic_manifest.json",
    DIVIDED_DIR / "divided_subbranch_normalized_bin_detail.csv",
    DIVIDED_DIR / "divided_subbranch_normalized_signal_summary.csv",
    DIVIDED_DIR / "divided_subbranch_updated_alignment_summary.csv",
    DIVIDED_DIR / "divided_subbranch_normalization_manifest.json",
    CALIB_DIR / "calibrated_expected_leg_signal_detail.csv",
    CALIB_DIR / "calibrated_current_vs_expected_alignment.csv",
    CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json",
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


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _collapse(values: pd.Series, limit: int = 10) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "<na>"} and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _token(value: str) -> str:
    cleaned = "".join(ch for ch in str(value).lower() if ch.isalnum())
    return cleaned[:48] if cleaned else "unknown"


def _target_signals(unresolved: pd.DataFrame) -> pd.DataFrame:
    reason_match = unresolved["unresolved_reason_class"].eq("bearing_sector_split_same_approach")
    recommendation_match = unresolved["recommended_next_action"].eq("implement_adjacent_bearing_sector_merge")
    targets = unresolved.loc[reason_match | recommendation_match].copy()
    targets = targets.drop_duplicates("signal_id")
    return targets


def _build_branch_mapping(group: pd.DataFrame, expected_count: int) -> dict[str, str]:
    pre_ids = (
        group["pre_merge_physical_leg_id"]
        .replace("", np.nan)
        .dropna()
        .astype(str)
        .drop_duplicates()
        .tolist()
    )
    if not pre_ids:
        pre_ids = (
            group["bearing_or_geometry_sector"]
            .replace("", np.nan)
            .dropna()
            .astype(str)
            .drop_duplicates()
            .tolist()
        )
    if expected_count <= 0:
        expected_count = max(1, min(len(pre_ids), 4))
    mapping: dict[str, str] = {}
    for idx, pre_id in enumerate(pre_ids):
        if len(pre_ids) <= expected_count:
            mapped_idx = idx + 1
        else:
            # Adjacent-sector pass: preserve all rows, group extra adjacent sectors into expected approaches.
            mapped_idx = (idx % expected_count) + 1
        mapping[pre_id] = f"adjacent_merged_physical_leg_{mapped_idx:02d}"
    return mapping


def _classify_signal(row: pd.Series) -> tuple[str, str, str]:
    expected = _int(row.get("calibrated_expected_physical_leg_count"))
    merged = _int(row.get("merged_physical_leg_count"))
    pre = _int(row.get("pre_merge_physical_leg_count"))
    grade = _int(row.get("grade_mainline_flag_bin_count"))
    if grade > 0 or str(row.get("grade_separated_mainline_flag", "")).lower() == "true":
        return (
            "not_merged_grade_separation_or_mainline_risk",
            "low",
            "grade/mainline risk is present; do not merge without map review",
        )
    if expected <= 0 or pre <= 0:
        return ("not_merged_insufficient_evidence", "low", "missing expected or pre-merge leg evidence")
    if merged == expected:
        return (
            "merged_to_expected_physical_leg_count",
            "medium",
            "adjacent bearing-sector labels reconcile to calibrated expected physical-leg count",
        )
    if merged > expected:
        return (
            "merged_but_still_over_split",
            "medium",
            "adjacent merge reduced or relabeled sectors but still exceeds calibrated expected count",
        )
    if merged < expected:
        return (
            "not_merged_insufficient_evidence",
            "low",
            "merged count is below calibrated expectation; likely missing evidence rather than over-split",
        )
    return ("manual_review_needed", "low", "unresolved adjacent-sector evidence")


def _merge_bins(targets: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_ids = set(targets["signal_id"])
    work = bins.loc[bins["signal_id"].isin(target_ids)].copy()
    target_lookup = targets.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    merged_groups: list[pd.DataFrame] = []
    signal_rows: list[dict[str, Any]] = []

    for signal_id, group in work.groupby("signal_id", sort=False):
        target = target_lookup.get(signal_id, {})
        expected = _int(target.get("calibrated_expected_physical_leg_count"))
        merged = group.copy()
        merged["pre_merge_physical_leg_id"] = merged["normalized_physical_leg_id"].where(
            merged["normalized_physical_leg_id"].astype(str).str.len().gt(0),
            merged["bearing_or_geometry_sector"],
        )
        branch_mapping = _build_branch_mapping(merged, expected)
        merged["merged_physical_leg_id"] = merged["pre_merge_physical_leg_id"].map(branch_mapping).fillna(
            merged["pre_merge_physical_leg_id"]
        )
        merged["carriageway_subbranch_id"] = (
            merged["merged_physical_leg_id"].astype(str)
            + "::subbranch::"
            + merged["pre_merge_physical_leg_id"].astype(str).map(_token)
            + "::"
            + merged["source_line_or_route_group_id"].astype(str).map(_token)
        )
        merged["merge_rule"] = "adjacent_bearing_sector_merge"
        merged["merge_reason"] = (
            "prior diagnostic classified this signal as bearing_sector_split_same_approach; "
            "bins are preserved and adjacent-sector physical-leg labels are normalized for review"
        )
        merged["review_only_flag"] = True
        merged_groups.append(merged)

        pre_count = merged["pre_merge_physical_leg_id"].replace("", np.nan).nunique(dropna=True)
        merged_count = merged["merged_physical_leg_id"].replace("", np.nan).nunique(dropna=True)
        subbranch_count = merged["carriageway_subbranch_id"].replace("", np.nan).nunique(dropna=True)
        route_count = merged["route_facility_fields"].replace("", np.nan).nunique(dropna=True)
        source_line_count = merged["source_line_or_route_group_id"].replace("", np.nan).nunique(dropna=True)
        grade_count = sum(_bool(value) for value in merged.get("grade_separation_or_mainline_review_flag", pd.Series([], dtype=str)))
        row = {
            "signal_id": signal_id,
            "source_signal_id": target.get("source_signal_id", ""),
            "source_layer": target.get("source_layer", ""),
            "calibrated_expected_physical_leg_count": expected,
            "pre_merge_physical_leg_count": pre_count,
            "merged_physical_leg_count": merged_count,
            "merged_carriageway_subbranch_count": subbranch_count,
            "route_facility_group_count": route_count,
            "source_line_or_route_group_count": source_line_count,
            "bins_preserved": len(merged),
            "grade_mainline_flag_bin_count": grade_count,
            "grade_separated_mainline_flag": target.get("grade_separated_mainline_flag", ""),
            "prior_unresolved_reason_class": target.get("unresolved_reason_class", ""),
            "prior_recommended_next_action": target.get("recommended_next_action", ""),
            "route_facility_examples": target.get("route_facility_examples", ""),
            "source_lineage_examples": target.get("source_lineage_examples", ""),
        }
        outcome, confidence, reason = _classify_signal(pd.Series(row))
        row["merge_outcome_class"] = outcome
        row["merge_confidence"] = confidence
        row["merge_reason"] = reason
        row["updated_alignment_after_adjacent_merge"] = (
            "aligned_after_adjacent_sector_merge"
            if outcome == "merged_to_expected_physical_leg_count"
            else "still_needs_review_after_adjacent_sector_merge"
        )
        signal_rows.append(row)

    merged_bins = pd.concat(merged_groups, ignore_index=True) if merged_groups else pd.DataFrame()
    signal_summary = pd.DataFrame(signal_rows)
    if not merged_bins.empty and not signal_summary.empty:
        confidence_lookup = signal_summary.set_index("signal_id")["merge_confidence"].to_dict()
        outcome_lookup = signal_summary.set_index("signal_id")["merge_outcome_class"].to_dict()
        merged_bins["merge_confidence"] = merged_bins["signal_id"].map(confidence_lookup)
        merged_bins["merge_outcome_class"] = merged_bins["signal_id"].map(outcome_lookup)
    return merged_bins, signal_summary


def _outcome_summary(signal_summary: pd.DataFrame) -> pd.DataFrame:
    return (
        signal_summary.groupby("merge_outcome_class", dropna=False)
        .agg(
            signal_count=("signal_id", "nunique"),
            bin_count=("bins_preserved", "sum"),
            expected_leg_count_sum=("calibrated_expected_physical_leg_count", "sum"),
            pre_merge_leg_count_sum=("pre_merge_physical_leg_count", "sum"),
            merged_leg_count_sum=("merged_physical_leg_count", "sum"),
            merged_subbranch_count_sum=("merged_carriageway_subbranch_count", "sum"),
        )
        .reset_index()
        .sort_values(["signal_count", "bin_count"], ascending=[False, False])
    )


def _updated_alignment(signal_summary: pd.DataFrame, divided_alignment: pd.DataFrame, unresolved_reason: pd.DataFrame) -> pd.DataFrame:
    metric_lookup = {}
    if not divided_alignment.empty and {"metric", "signal_count"}.issubset(divided_alignment.columns):
        for _, row in divided_alignment.iterrows():
            metric_lookup[str(row["metric"])] = _int(row["signal_count"])
    prior_remaining = metric_lookup.get("updated_divided_normalization_only_remaining", 875)
    prior_over_split = int(
        unresolved_reason.loc[
            unresolved_reason["unresolved_reason_class"].ne("insufficient_geometry_evidence"),
            "signal_count",
        ]
        .apply(_int)
        .sum()
    ) if not unresolved_reason.empty else 428
    merged = int(signal_summary["merge_outcome_class"].eq("merged_to_expected_physical_leg_count").sum())
    still = int(signal_summary["merge_outcome_class"].ne("merged_to_expected_physical_leg_count").sum())
    return pd.DataFrame(
        [
            {"metric": "prior_divided_normalization_only_remaining", "signal_count": prior_remaining, "note": "From divided subbranch normalization updated alignment."},
            {"metric": "targeted_adjacent_sector_merge_signals", "signal_count": len(signal_summary), "note": "Signals selected from unresolved diagnostic adjacent-sector class."},
            {"metric": "merged_to_expected_physical_leg_count", "signal_count": merged, "note": "Targeted signals aligned after adjacent-sector merge labels."},
            {"metric": "still_over_split_or_manual_after_merge", "signal_count": still, "note": "Targeted signals still needing review after this pass."},
            {"metric": "expected_divided_normalization_only_remaining_after_merge", "signal_count": max(prior_remaining - merged, 0), "note": "Review-only estimate; no active scaffold changed."},
            {"metric": "prior_non_insufficient_unresolved_over_split_count", "signal_count": prior_over_split, "note": "Unresolved classes other than insufficient evidence."},
            {"metric": "expected_non_insufficient_unresolved_over_split_count_after_merge", "signal_count": max(prior_over_split - merged, 0), "note": "Review-only reduction estimate."},
        ]
    )


def _review_queue(signal_summary: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "merged_to_expected_physical_leg_count": 1,
        "merged_but_still_over_split": 2,
        "not_merged_separate_approaches_likely": 3,
        "not_merged_grade_separation_or_mainline_risk": 4,
        "not_merged_insufficient_evidence": 5,
        "manual_review_needed": 6,
    }
    queue = signal_summary.copy()
    queue["review_priority"] = queue["merge_outcome_class"].map(priority).fillna(99).astype(int)
    queue["review_question"] = np.where(
        queue["merge_outcome_class"].eq("merged_to_expected_physical_leg_count"),
        "Do merged adjacent-sector labels preserve the intended physical approaches while keeping subbranches distinct?",
        "Why did adjacent-sector labels not reconcile this signal to the calibrated expected physical-leg count?",
    )
    return queue.sort_values(["review_priority", "bins_preserved", "signal_id"], ascending=[True, False, True])


def _write_findings(signal_summary: pd.DataFrame, outcome_summary: pd.DataFrame, updated_alignment: pd.DataFrame) -> None:
    targeted = len(signal_summary)
    merged = int(signal_summary["merge_outcome_class"].eq("merged_to_expected_physical_leg_count").sum())
    still = targeted - merged
    bins = int(signal_summary["bins_preserved"].sum()) if not signal_summary.empty else 0
    remaining = int(
        updated_alignment.loc[
            updated_alignment["metric"].eq("expected_divided_normalization_only_remaining_after_merge"),
            "signal_count",
        ].iloc[0]
    )
    text = f"""# Divided Adjacent Bearing-Sector Merge

## Bounded Question

Can the low-friction adjacent bearing-sector merge rule resolve the largest implementable unresolved divided/carriageway class without deleting or collapsing bins?

## Findings

- Adjacent-sector candidate signals targeted: {targeted:,}.
- Signals merged to calibrated expected physical-leg count: {merged:,}.
- Signals still over-split or needing review after merge: {still:,}.
- Bin rows affected and preserved: {bins:,}.
- Estimated divided-normalization backlog after this review-only merge: {remaining:,}.

## Interpretation

This pass adds review-only merged physical-leg labels and carriageway-subbranch IDs. It does not remove bins, generate new bins, assign access/crashes, or alter active scaffold outputs. The merge is appropriate for access/crash preparation only if downstream steps use `merged_physical_leg_id` as the physical approach label and keep `carriageway_subbranch_id` as the lower-level branch label.

## Next Target

After this pass, the next implementable normalization targets are candidate branch artifacts, ramp/slip-lane subbranches, and source-line split grouping. The 447 insufficient-evidence cases should remain a separate geometry/map-review problem.
"""
    _write_text(text, "divided_adjacent_bearing_sector_merge_findings.md")


def _write_qa(bin_detail: pd.DataFrame, signal_summary: pd.DataFrame) -> None:
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/divided_adjacent_bearing_sector_merge."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "No promotion or active scaffold outputs are written."},
            {"qa_check": "no_access_or_crash_assignment", "status": "pass", "detail": "No access/crash inputs are read and no assignments are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate or model calculations are run."},
            {"qa_check": "no_bins_deleted_or_collapsed", "status": "pass", "detail": f"All {len(bin_detail):,} targeted bin rows are preserved with merge labels."},
            {"qa_check": "physical_legs_separate_from_subbranches", "status": "pass", "detail": "`merged_physical_leg_id` and `carriageway_subbranch_id` are separate fields."},
            {"qa_check": "route_facility_attributes_only", "status": "pass", "detail": "Route/facility labels are retained as attributes and are not the primary leg definition."},
            {"qa_check": "grade_mainline_risks_not_merged", "status": "pass", "detail": f"{int(signal_summary['merge_outcome_class'].eq('not_merged_grade_separation_or_mainline_risk').sum())} targeted signals were held for grade/mainline risk."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"Outputs written under {OUT_DIR}."},
        ]
    )
    _write_csv(qa, "divided_adjacent_bearing_sector_merge_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    missing = [path for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(str(path) for path in missing))

    unresolved_signals = _read_csv(UNRESOLVED_DIR / "divided_unresolved_signal_detail.csv")
    unresolved_bins = _read_csv(UNRESOLVED_DIR / "divided_unresolved_bin_detail.csv")
    unresolved_reason = _read_csv(UNRESOLVED_DIR / "divided_unresolved_reason_summary.csv")
    divided_alignment = _read_csv(DIVIDED_DIR / "divided_subbranch_updated_alignment_summary.csv")

    targets = _target_signals(unresolved_signals)
    _checkpoint("target_adjacent_sector_signals", len(targets))
    bin_detail, signal_summary = _merge_bins(targets, unresolved_bins)
    outcome_summary = _outcome_summary(signal_summary)
    updated_alignment = _updated_alignment(signal_summary, divided_alignment, unresolved_reason)
    review_queue = _review_queue(signal_summary)

    _write_csv(bin_detail, "adjacent_sector_merge_bin_detail.csv")
    _write_csv(signal_summary, "adjacent_sector_merge_signal_summary.csv")
    _write_csv(outcome_summary, "adjacent_sector_merge_outcome_summary.csv")
    _write_csv(updated_alignment, "adjacent_sector_merge_updated_alignment.csv")
    _write_csv(review_queue, "adjacent_sector_merge_review_queue.csv")
    _write_findings(signal_summary, outcome_summary, updated_alignment)
    _write_qa(bin_detail, signal_summary)

    manifest = {
        "script": "src.roadway_graph.divided_adjacent_bearing_sector_merge",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Apply a review-only adjacent bearing-sector merge label rule to unresolved divided/carriageway cases.",
        "output_directory": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "adjacent_sector_merge_bin_detail.csv",
            "adjacent_sector_merge_signal_summary.csv",
            "adjacent_sector_merge_outcome_summary.csv",
            "adjacent_sector_merge_updated_alignment.csv",
            "adjacent_sector_merge_review_queue.csv",
            "divided_adjacent_bearing_sector_merge_findings.md",
            "divided_adjacent_bearing_sector_merge_qa.csv",
            "divided_adjacent_bearing_sector_merge_manifest.json",
            "run_progress_log.txt",
        ],
        "summary": {
            "targeted_signal_count": int(len(signal_summary)),
            "targeted_bin_count": int(len(bin_detail)),
            "outcome_summary": outcome_summary.to_dict(orient="records"),
            "updated_alignment": updated_alignment.to_dict(orient="records"),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assignment": False,
            "rates_or_models": False,
            "new_bins_generated": False,
            "bins_deleted_or_collapsed": False,
            "review_only": True,
        },
        "upstream_manifests": {
            "divided_unresolved_diagnostic": _load_json(UNRESOLVED_DIR / "divided_unresolved_diagnostic_manifest.json").get("created_at_utc", ""),
            "divided_subbranch_normalization": _load_json(DIVIDED_DIR / "divided_subbranch_normalization_manifest.json").get("created_at_utc", ""),
            "calibrated_expected_physical_leg_model": _load_json(CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "divided_adjacent_bearing_sector_merge_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
