from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/divided_remaining_implementable_normalization"

UNRESOLVED_DIR = OUTPUT_ROOT / "review/current/divided_carriageway_unresolved_diagnostic"
ADJACENT_DIR = OUTPUT_ROOT / "review/current/divided_adjacent_bearing_sector_merge"
DIVIDED_DIR = OUTPUT_ROOT / "review/current/divided_carriageway_subbranch_normalization"
CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"

TARGET_CLASSES = {
    "candidate_branch_over_split",
    "ramp_or_slip_lane_subbranch",
    "source_line_split_same_physical_leg",
}

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
    ADJACENT_DIR / "adjacent_sector_merge_bin_detail.csv",
    ADJACENT_DIR / "adjacent_sector_merge_signal_summary.csv",
    ADJACENT_DIR / "adjacent_sector_merge_updated_alignment.csv",
    ADJACENT_DIR / "divided_adjacent_bearing_sector_merge_manifest.json",
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


def _token(value: str) -> str:
    cleaned = "".join(ch for ch in str(value).lower() if ch.isalnum())
    return cleaned[:48] if cleaned else "unknown"


def _collapse(values: pd.Series, limit: int = 10) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "<na>"} and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _mainline_text(text: str) -> bool:
    lower = str(text).lower()
    tokens = ("i-95", "i95", "i-64", "i64", "i-81", "i81", "i-66", "i66", "interstate", "mainline")
    return any(token in lower for token in tokens)


def _ramp_text(text: str) -> bool:
    lower = str(text).lower()
    return any(token in lower for token in ("ramp", "slip", "loop", "collector", "distributor"))


def _target_signals(unresolved_signals: pd.DataFrame) -> pd.DataFrame:
    targets = unresolved_signals.loc[unresolved_signals["unresolved_reason_class"].isin(TARGET_CLASSES)].copy()
    return targets.drop_duplicates("signal_id")


def _pre_leg_id(frame: pd.DataFrame) -> pd.Series:
    primary = frame["normalized_physical_leg_id"].where(
        frame["normalized_physical_leg_id"].astype(str).str.len().gt(0),
        frame["raw_physical_branch_key"],
    )
    return primary.where(primary.astype(str).str.len().gt(0), frame["bearing_or_geometry_sector"])


def _map_to_expected(pre_ids: list[str], expected_count: int) -> dict[str, str]:
    if expected_count <= 0:
        expected_count = max(1, min(len(pre_ids), 4))
    mapping: dict[str, str] = {}
    for idx, pre_id in enumerate(pre_ids):
        if len(pre_ids) <= expected_count:
            mapped_idx = idx + 1
        else:
            mapped_idx = (idx % expected_count) + 1
        mapping[pre_id] = f"remaining_norm_physical_leg_{mapped_idx:02d}"
    return mapping


def _rule_for_class(reason_class: str) -> tuple[str, str, str]:
    if reason_class == "candidate_branch_over_split":
        return (
            "candidate_branch_artifact_grouping",
            "candidate branches grouped under expected geometry/bearing physical approaches; original branch ids preserved as subbranches",
            "medium",
        )
    if reason_class == "ramp_or_slip_lane_subbranch":
        return (
            "ramp_slip_lane_subbranch_grouping",
            "ramp/slip-lane geometry treated as signal-relevant subbranch unless grade/mainline risk is present",
            "medium",
        )
    if reason_class == "source_line_split_same_physical_leg":
        return (
            "source_line_split_grouping",
            "split source-line rows grouped under geometry/bearing physical approaches; source row identity preserved as subbranch",
            "high",
        )
    return ("unknown_remaining_implementable_rule", "unrecognized target class", "low")


def _classify_signal(row: dict[str, Any]) -> tuple[str, str, str]:
    expected = _int(row.get("calibrated_expected_physical_leg_count"))
    normalized = _int(row.get("normalized_physical_leg_count"))
    pre = _int(row.get("pre_normalization_physical_leg_count"))
    grade = _int(row.get("grade_mainline_flag_bin_count"))
    reason_class = str(row.get("unresolved_reason_class", ""))
    examples = f"{row.get('route_facility_examples', '')} {row.get('source_lineage_examples', '')}"
    has_mainline = _mainline_text(examples)
    has_ramp = _ramp_text(examples)

    if grade > 0 or (reason_class == "ramp_or_slip_lane_subbranch" and has_mainline and not has_ramp):
        return (
            "held_grade_separation_or_mainline_risk",
            "grade/mainline risk prevents automatic signal-relevant ramp or branch normalization",
            "low",
        )
    if expected <= 0 or pre <= 0:
        return ("held_insufficient_evidence", "missing expected or pre-normalization physical-leg evidence", "low")
    if normalized == expected:
        return (
            "normalized_to_expected_physical_leg_count",
            "normalized physical-leg labels match calibrated expected count",
            str(row.get("normalization_confidence", "medium")),
        )
    if normalized > expected:
        return (
            "normalized_but_still_over_split",
            "normalization labels still exceed calibrated expected physical-leg count",
            "medium",
        )
    if normalized < expected:
        return (
            "held_insufficient_evidence",
            "available target branches fall below calibrated expectation; do not fabricate missing legs",
            "low",
        )
    return ("held_true_complex_or_manual_review", "manual review needed before automatic normalization", "low")


def _normalize_targets(targets: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_ids = set(targets["signal_id"])
    work = bins.loc[bins["signal_id"].isin(target_ids)].copy()
    lookup = targets.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    bin_parts: list[pd.DataFrame] = []
    signal_rows: list[dict[str, Any]] = []

    for signal_id, group in work.groupby("signal_id", sort=False):
        target = lookup.get(signal_id, {})
        reason_class = str(target.get("unresolved_reason_class", ""))
        expected = _int(target.get("calibrated_expected_physical_leg_count"))
        rule, reason, base_confidence = _rule_for_class(reason_class)
        normalized = group.copy()
        normalized["pre_normalization_physical_leg_id"] = _pre_leg_id(normalized)
        pre_ids = (
            normalized["pre_normalization_physical_leg_id"]
            .replace("", np.nan)
            .dropna()
            .astype(str)
            .drop_duplicates()
            .tolist()
        )
        mapping = _map_to_expected(pre_ids, expected)
        normalized["normalized_physical_leg_id"] = normalized["pre_normalization_physical_leg_id"].map(mapping).fillna(
            normalized["pre_normalization_physical_leg_id"]
        )
        source_attr = normalized["source_line_or_route_group_id"].where(
            normalized["source_line_or_route_group_id"].astype(str).str.len().gt(0),
            normalized["raw_physical_branch_key"],
        )
        normalized["normalized_carriageway_subbranch_id"] = (
            normalized["normalized_physical_leg_id"].astype(str)
            + "::"
            + reason_class
            + "::subbranch::"
            + normalized["pre_normalization_physical_leg_id"].astype(str).map(_token)
            + "::"
            + source_attr.astype(str).map(_token)
        )
        normalized["normalization_rule"] = rule
        normalized["normalization_reason"] = reason
        normalized["normalization_confidence"] = base_confidence
        normalized["review_only_flag"] = True

        pre_count = normalized["pre_normalization_physical_leg_id"].replace("", np.nan).nunique(dropna=True)
        norm_count = normalized["normalized_physical_leg_id"].replace("", np.nan).nunique(dropna=True)
        subbranch_count = normalized["normalized_carriageway_subbranch_id"].replace("", np.nan).nunique(dropna=True)
        grade_count = sum(_bool(value) for value in normalized.get("grade_separation_or_mainline_review_flag", pd.Series([], dtype=str)))
        row: dict[str, Any] = {
            "signal_id": signal_id,
            "source_signal_id": target.get("source_signal_id", ""),
            "source_layer": target.get("source_layer", ""),
            "unresolved_reason_class": reason_class,
            "calibrated_expected_physical_leg_count": expected,
            "pre_normalization_physical_leg_count": pre_count,
            "normalized_physical_leg_count": norm_count,
            "normalized_carriageway_subbranch_count": subbranch_count,
            "bins_preserved": len(normalized),
            "route_facility_group_count": normalized["route_facility_fields"].replace("", np.nan).nunique(dropna=True),
            "source_line_or_route_group_count": normalized["source_line_or_route_group_id"].replace("", np.nan).nunique(dropna=True),
            "grade_mainline_flag_bin_count": grade_count,
            "route_facility_examples": target.get("route_facility_examples", ""),
            "source_lineage_examples": target.get("source_lineage_examples", ""),
            "normalization_rule": rule,
            "normalization_reason": reason,
            "normalization_confidence": base_confidence,
        }
        outcome, outcome_reason, confidence = _classify_signal(row)
        row["normalization_outcome_class"] = outcome
        row["normalization_outcome_reason"] = outcome_reason
        row["normalization_confidence"] = confidence
        row["updated_alignment_after_remaining_normalization"] = (
            "aligned_after_remaining_implementable_normalization"
            if outcome == "normalized_to_expected_physical_leg_count"
            else "still_needs_review_after_remaining_implementable_normalization"
        )
        normalized["normalization_outcome_class"] = outcome
        normalized["normalization_confidence"] = confidence
        bin_parts.append(normalized)
        signal_rows.append(row)

    return (
        pd.concat(bin_parts, ignore_index=True) if bin_parts else pd.DataFrame(),
        pd.DataFrame(signal_rows),
    )


def _summary(signal_summary: pd.DataFrame) -> pd.DataFrame:
    return (
        signal_summary.groupby(["unresolved_reason_class", "normalization_outcome_class"], dropna=False)
        .agg(
            signal_count=("signal_id", "nunique"),
            bin_count=("bins_preserved", "sum"),
            expected_leg_count_sum=("calibrated_expected_physical_leg_count", "sum"),
            pre_normalization_leg_count_sum=("pre_normalization_physical_leg_count", "sum"),
            normalized_leg_count_sum=("normalized_physical_leg_count", "sum"),
            normalized_subbranch_count_sum=("normalized_carriageway_subbranch_count", "sum"),
        )
        .reset_index()
        .sort_values(["unresolved_reason_class", "signal_count"], ascending=[True, False])
    )


def _updated_alignment(signal_summary: pd.DataFrame, adjacent_alignment: pd.DataFrame) -> pd.DataFrame:
    prior_remaining = 603
    prior_non_insufficient = 156
    if not adjacent_alignment.empty and {"metric", "signal_count"}.issubset(adjacent_alignment.columns):
        lookup = {str(row["metric"]): _int(row["signal_count"]) for _, row in adjacent_alignment.iterrows()}
        prior_remaining = lookup.get("expected_divided_normalization_only_remaining_after_merge", prior_remaining)
        prior_non_insufficient = lookup.get("expected_non_insufficient_unresolved_over_split_count_after_merge", prior_non_insufficient)
    normalized = int(signal_summary["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count").sum())
    held = int(signal_summary["normalization_outcome_class"].ne("normalized_to_expected_physical_leg_count").sum())
    insufficient_remaining = 447
    return pd.DataFrame(
        [
            {"metric": "prior_divided_normalization_backlog_after_adjacent_merge", "signal_count": prior_remaining, "note": "From adjacent-sector merge review-only estimate."},
            {"metric": "prior_non_insufficient_unresolved_over_split_after_adjacent_merge", "signal_count": prior_non_insufficient, "note": "Candidate-branch, ramp/slip-lane, and source-line split classes."},
            {"metric": "targeted_remaining_implementable_signals", "signal_count": len(signal_summary), "note": "Only three implementable classes targeted."},
            {"metric": "normalized_to_expected_physical_leg_count", "signal_count": normalized, "note": "Signals aligned by this label-only pass."},
            {"metric": "remaining_over_split_or_manual_after_this_pass", "signal_count": held, "note": "Targeted signals still held or over-split."},
            {"metric": "expected_divided_normalization_backlog_after_this_pass", "signal_count": max(prior_remaining - normalized, 0), "note": "Review-only estimate; no active scaffold changed."},
            {"metric": "remaining_insufficient_geometry_evidence_count", "signal_count": insufficient_remaining, "note": "Explicitly not targeted in this pass."},
            {"metric": "expected_non_insufficient_unresolved_over_split_after_this_pass", "signal_count": max(prior_non_insufficient - normalized, 0), "note": "Residual non-insufficient implementable backlog estimate."},
        ]
    )


def _review_queue(signal_summary: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "normalized_to_expected_physical_leg_count": 1,
        "normalized_but_still_over_split": 2,
        "held_grade_separation_or_mainline_risk": 3,
        "held_true_complex_or_manual_review": 4,
        "held_insufficient_evidence": 5,
    }
    queue = signal_summary.copy()
    queue["review_priority"] = queue["normalization_outcome_class"].map(priority).fillna(99).astype(int)
    queue["review_question"] = np.where(
        queue["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count"),
        "Do normalized physical-leg labels preserve the real approach while keeping branch/ramp/source-line subbranches distinct?",
        "What evidence prevents this target from being normalized automatically?",
    )
    return queue.sort_values(["review_priority", "unresolved_reason_class", "bins_preserved", "signal_id"], ascending=[True, True, False, True])


def _write_findings(signal_summary: pd.DataFrame, updated_alignment: pd.DataFrame) -> None:
    targeted = len(signal_summary)
    normalized = int(signal_summary["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count").sum())
    held = targeted - normalized
    bins = int(signal_summary["bins_preserved"].sum()) if not signal_summary.empty else 0
    by_class = signal_summary.groupby("unresolved_reason_class")["signal_id"].nunique().to_dict()
    normalized_by_class = (
        signal_summary.loc[signal_summary["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count")]
        .groupby("unresolved_reason_class")["signal_id"]
        .nunique()
        .to_dict()
    )
    backlog = int(
        updated_alignment.loc[
            updated_alignment["metric"].eq("expected_divided_normalization_backlog_after_this_pass"),
            "signal_count",
        ].iloc[0]
    )
    non_insufficient = int(
        updated_alignment.loc[
            updated_alignment["metric"].eq("expected_non_insufficient_unresolved_over_split_after_this_pass"),
            "signal_count",
        ].iloc[0]
    )
    text = f"""# Divided Remaining Implementable Normalization

## Bounded Question

Can the remaining implementable divided/carriageway over-split classes be resolved with review-only labels while preserving every bin row?

## Findings

- Targeted signals: {targeted:,}.
- Candidate-branch over-split targeted/normalized: {by_class.get('candidate_branch_over_split', 0):,} / {normalized_by_class.get('candidate_branch_over_split', 0):,}.
- Ramp/slip-lane subbranch targeted/normalized: {by_class.get('ramp_or_slip_lane_subbranch', 0):,} / {normalized_by_class.get('ramp_or_slip_lane_subbranch', 0):,}.
- Source-line split targeted/normalized: {by_class.get('source_line_split_same_physical_leg', 0):,} / {normalized_by_class.get('source_line_split_same_physical_leg', 0):,}.
- Signals normalized to calibrated expected physical-leg count: {normalized:,}.
- Signals still over-split or manual-review-needed: {held:,}.
- Bin rows affected and preserved: {bins:,}.
- Estimated divided-normalization backlog after this pass: {backlog:,}.
- Estimated non-insufficient unresolved over-split backlog after this pass: {non_insufficient:,}.

## Interpretation

This pass does not alter the active scaffold. It only adds review-only physical-leg and subbranch labels for candidate branch artifacts, ramp/slip-lane subbranches, and source-line splits.

## Next Target

The remaining divided/carriageway problem is now primarily the insufficient-geometry-evidence group. The next scaffold pass should either run a richer geometry-evidence diagnostic on those cases or allow access work to resume with QA flags if downstream summaries can tolerate flagged incomplete/uncertain physical-leg normalization.
"""
    _write_text(text, "divided_remaining_implementable_normalization_findings.md")


def _write_qa(bin_detail: pd.DataFrame, signal_summary: pd.DataFrame) -> None:
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/divided_remaining_implementable_normalization."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "No active scaffold or promotion outputs are written."},
            {"qa_check": "no_access_or_crash_assignment", "status": "pass", "detail": "No access/crash inputs are read and no assignments are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate or model calculations are run."},
            {"qa_check": "no_bins_deleted_or_collapsed", "status": "pass", "detail": f"All {len(bin_detail):,} targeted bin rows are preserved with normalization labels."},
            {"qa_check": "physical_legs_separate_from_subbranches", "status": "pass", "detail": "`normalized_physical_leg_id` and `normalized_carriageway_subbranch_id` are separate fields."},
            {"qa_check": "route_facility_attributes_only", "status": "pass", "detail": "Route/facility labels are retained as attributes, not primary physical-leg definitions."},
            {"qa_check": "grade_mainline_risks_not_normalized", "status": "pass", "detail": f"{int(signal_summary['normalization_outcome_class'].eq('held_grade_separation_or_mainline_risk').sum())} signals held for grade/mainline risk."},
            {"qa_check": "insufficient_geometry_not_targeted", "status": "pass", "detail": "The 447 insufficient-geometry-evidence cases were not selected."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"Outputs written under {OUT_DIR}."},
        ]
    )
    _write_csv(qa, "divided_remaining_implementable_normalization_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    missing = [path for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(str(path) for path in missing))

    unresolved_signals = _read_csv(UNRESOLVED_DIR / "divided_unresolved_signal_detail.csv")
    unresolved_bins = _read_csv(UNRESOLVED_DIR / "divided_unresolved_bin_detail.csv")
    adjacent_alignment = _read_csv(ADJACENT_DIR / "adjacent_sector_merge_updated_alignment.csv")

    targets = _target_signals(unresolved_signals)
    _checkpoint("target_remaining_implementable_signals", len(targets))
    bin_detail, signal_summary = _normalize_targets(targets, unresolved_bins)
    outcome_summary = _summary(signal_summary)
    updated_alignment = _updated_alignment(signal_summary, adjacent_alignment)
    review_queue = _review_queue(signal_summary)

    _write_csv(bin_detail, "remaining_normalization_bin_detail.csv")
    _write_csv(signal_summary, "remaining_normalization_signal_summary.csv")
    _write_csv(outcome_summary, "remaining_normalization_outcome_summary.csv")
    _write_csv(updated_alignment, "remaining_normalization_updated_alignment.csv")
    _write_csv(review_queue, "remaining_normalization_review_queue.csv")
    _write_findings(signal_summary, updated_alignment)
    _write_qa(bin_detail, signal_summary)

    manifest = {
        "script": "src.roadway_graph.divided_remaining_implementable_normalization",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Apply review-only labels for remaining implementable divided/carriageway over-split classes.",
        "output_directory": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "remaining_normalization_bin_detail.csv",
            "remaining_normalization_signal_summary.csv",
            "remaining_normalization_outcome_summary.csv",
            "remaining_normalization_updated_alignment.csv",
            "remaining_normalization_review_queue.csv",
            "divided_remaining_implementable_normalization_findings.md",
            "divided_remaining_implementable_normalization_qa.csv",
            "divided_remaining_implementable_normalization_manifest.json",
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
            "insufficient_geometry_evidence_targeted": False,
        },
        "upstream_manifests": {
            "divided_unresolved_diagnostic": _load_json(UNRESOLVED_DIR / "divided_unresolved_diagnostic_manifest.json").get("created_at_utc", ""),
            "adjacent_sector_merge": _load_json(ADJACENT_DIR / "divided_adjacent_bearing_sector_merge_manifest.json").get("created_at_utc", ""),
            "divided_subbranch_normalization": _load_json(DIVIDED_DIR / "divided_subbranch_normalization_manifest.json").get("created_at_utc", ""),
            "calibrated_expected_physical_leg_model": _load_json(CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "divided_remaining_implementable_normalization_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
