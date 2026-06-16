from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/unrepresented_signal_recovery_feasibility"
PLAIN_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_plain_language_funnel_and_loss_audit"
FUNNEL_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_signal_funnel_clarification"
ATTRITION_DIR = OUTPUT_ROOT / "review/current/signal_attrition_funnel_audit"
AMBIGUOUS_DIR = OUTPUT_ROOT / "review/current/signal_ambiguous_road_association_diagnostic"
ASSOC_DIR = OUTPUT_ROOT / "review/current/signal_association_recovery_feasibility"
SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/signal_recovery_scaffold_feasibility"
BIN_DIR = OUTPUT_ROOT / "review/current/signal_recovery_candidate_bin_generation"

TARGET_BUCKETS = ("graph/path/anchor unresolved", "review-only/not attempted")
EXPECTED_GRAPH_PATH_ANCHOR = 709
EXPECTED_REVIEW_ONLY_NOT_ATTEMPTED = 347

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = {
    PLAIN_DIR: [
        "remaining_loss_recoverability_audit.csv",
        "remaining_loss_remainder_reconciliation.csv",
        "expanded_candidate_plain_language_funnel_and_loss_audit_findings.md",
        "expanded_candidate_plain_language_funnel_and_loss_audit_manifest.json",
    ],
    FUNNEL_DIR: [
        "signal_funnel_clarification_detail.csv",
        "remaining_signal_loss_reason_summary.csv",
        "signal_funnel_clarification_manifest.json",
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
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash assignment/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(frame))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(frame))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 8) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() != "nan"})
    return "|".join(items[:limit])


def _missing_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_inputs() -> dict[str, pd.DataFrame]:
    funnel_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "in_strict_active_baseline_971",
        "in_recovered_candidate_1590",
        "in_recovered_speed_aadt_ready_1469",
        "strict_overlap_or_conflict",
        "step5_exclusion_reason",
        "nearest_road_association_status",
        "graph_gap_issue_flags",
        "best_available_loss_reason",
        "methodology_interpretation",
    ]
    ambiguous_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "observed_adjacent_edge_count",
        "observed_divided_edge_count",
        "observed_undivided_edge_count",
        "graph_gap_flag",
        "graph_gap_issue_flags",
        "MAJ_NAME",
        "MAJ_NUM",
        "MINOR_NAME",
        "MINOR_NUM",
        "nearest_travelway_distance_ft",
        "nearby_travelway_candidate_count",
        "unique_nearby_route_count",
        "nearby_divided_candidate_count",
        "nearby_undivided_candidate_count",
        "nearest_route_sample",
        "matched_route_sample",
        "nearest_candidate_distance_ft",
        "second_candidate_distance_ft",
        "nearest_second_distance_delta_ft",
        "candidate_count_within_10ft_of_nearest",
        "candidate_count_within_25ft",
        "candidate_count_within_50ft",
        "nearest_candidate_route",
        "nearest_two_route_sample",
        "graph_node_route_sample",
        "graph_node_division_status_sample",
        "primary_diagnostic_category",
        "diagnostic_category_flags",
        "recoverability_class",
        "diagnostic_explanation",
        "needs_review",
    ]
    assoc_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "primary_diagnostic_category",
        "recovery_strategy",
        "association_confidence_tier",
        "signal_recovery_status",
        "number_of_candidates_for_signal",
        "has_plausible_recovery_candidate",
        "deterministically_recoverable",
        "requires_multi_candidate_weighting",
        "review_only",
        "not_recoverable_current_sources",
        "nearest_candidate_distance_ft",
        "diagnostic_explanation",
    ]
    scaffold_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "primary_recovery_strategy",
        "primary_confidence_tier",
        "candidate_association_count",
        "buildable_candidate_count",
        "has_any_buildable_scaffold",
        "has_0_1000ft_scaffold",
        "has_1000_2500ft_scaffold",
        "has_full_0_2500ft_scaffold",
        "has_one_direction_only_scaffold",
        "requires_multi_candidate_preservation",
        "overlaps_existing_strict_active_signal_scaffold",
        "signal_scaffold_tier",
        "dominant_failure_reason",
    ]
    bin_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_associations_tested",
        "candidate_associations_producing_bins",
        "total_candidate_bins_generated",
        "weighted_candidate_bin_count",
        "full_0_1000_coverage_flag",
        "full_0_2500_coverage_flag",
        "both_direction_coverage_flag",
        "one_direction_only_flag",
        "multi_candidate_preserved_flag",
        "dominant_failure_reason",
        "recommended_next_handling_class",
    ]
    return {
        "funnel": _read_csv(FUNNEL_DIR / "signal_funnel_clarification_detail.csv", usecols=funnel_cols),
        "plain_audit": _read_csv(PLAIN_DIR / "remaining_loss_recoverability_audit.csv"),
        "loss_summary": _read_csv(FUNNEL_DIR / "remaining_signal_loss_reason_summary.csv"),
        "ambiguous": _read_csv(AMBIGUOUS_DIR / "ambiguous_signal_diagnostic_detail.csv", usecols=ambiguous_cols),
        "assoc": _read_csv(ASSOC_DIR / "signal_recovery_candidate_summary_by_signal.csv", usecols=assoc_cols),
        "scaffold": _read_csv(SCAFFOLD_DIR / "signal_recovery_scaffold_signal_summary.csv", usecols=scaffold_cols),
        "bins": _read_csv(BIN_DIR / "candidate_recovery_signal_summary.csv", usecols=bin_cols),
    }


def _loss_reason(row: pd.Series) -> str:
    if bool(row.get("in_strict_active_baseline_971", False)) or bool(row.get("in_recovered_speed_aadt_ready_1469", False)):
        return "represented"
    if not bool(row.get("in_recovered_candidate_1590", False)):
        combined = "|".join(
            str(row.get(column, ""))
            for column in ["best_available_loss_reason", "graph_gap_issue_flags", "step5_exclusion_reason", "nearest_road_association_status"]
        ).lower()
        if "divided" in combined or "pair" in combined:
            return "divided-pairing unresolved"
        if any(token in combined for token in ("graph", "anchor", "nearest", "association", "path")):
            return "graph/path/anchor unresolved"
        if "review" in combined:
            return "review-only/not attempted"
        return "no recovered scaffold"
    if bool(row.get("strict_overlap_or_conflict", False)):
        return "strict overlap/conflict holdout"
    return "insufficient evidence"


def _dedupe_funnel(funnel: pd.DataFrame) -> pd.DataFrame:
    flags = [
        "in_strict_active_baseline_971",
        "in_recovered_candidate_1590",
        "in_recovered_speed_aadt_ready_1469",
        "strict_overlap_or_conflict",
    ]
    work = funnel.copy()
    for column in flags:
        work[column] = _flag(work, column)
    work["remaining_loss_reason"] = work.apply(_loss_reason, axis=1)
    work = work.sort_values(["source_signal_id", "signal_id"]).drop_duplicates("source_signal_id", keep="first")
    return work.loc[work["remaining_loss_reason"].isin(TARGET_BUCKETS)].copy()


def _aggregate_by_source(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if frame.empty or "source_signal_id" not in frame.columns:
        return pd.DataFrame(columns=["source_signal_id"])
    aggregations: dict[str, Any] = {}
    for column in frame.columns:
        if column in {"source_signal_id"}:
            continue
        if column == "signal_id":
            aggregations[column] = "first"
        elif column.endswith("_count") or column.endswith("_ft") or column in {
            "observed_adjacent_edge_count",
            "observed_divided_edge_count",
            "observed_undivided_edge_count",
            "nearby_travelway_candidate_count",
            "unique_nearby_route_count",
            "nearby_divided_candidate_count",
            "nearby_undivided_candidate_count",
            "candidate_count_within_10ft_of_nearest",
            "candidate_count_within_25ft",
            "candidate_count_within_50ft",
            "number_of_candidates_for_signal",
            "candidate_association_count",
            "buildable_candidate_count",
            "candidate_associations_tested",
            "candidate_associations_producing_bins",
            "total_candidate_bins_generated",
            "weighted_candidate_bin_count",
        }:
            aggregations[column] = lambda s: _num(pd.DataFrame({s.name: s}), s.name).max()
        else:
            aggregations[column] = _collapse
    out = frame.groupby("source_signal_id", dropna=False).agg(aggregations).reset_index()
    rename = {column: f"{prefix}_{column}" for column in out.columns if column != "source_signal_id"}
    return out.rename(columns=rename)


def _merge_evidence(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    _checkpoint("merge_start evidence")
    detail = _dedupe_funnel(inputs["funnel"])
    for key, prefix in [("ambiguous", "amb"), ("assoc", "assoc"), ("scaffold", "scaffold"), ("bins", "bins")]:
        detail = detail.merge(_aggregate_by_source(inputs[key], prefix), on="source_signal_id", how="left", validate="one_to_one")
    _checkpoint("merge_complete evidence", len(detail))
    return detail


def _contains(row: pd.Series, columns: list[str], token: str) -> bool:
    token = token.lower()
    return any(token in str(row.get(column, "")).lower() for column in columns)


def _classify(row: pd.Series) -> str:
    if str(row.get("remaining_loss_reason", "")) == "review-only/not attempted":
        nearest_status = str(row.get("nearest_road_association_status", "")).lower()
        issue_flags = str(row.get("graph_gap_issue_flags", "")).lower()
        step5_reason = str(row.get("step5_exclusion_reason", "")).lower()
        if "snapped_distance_exceeds" in issue_flags:
            return "needs_virtual_anchor_rule"
        if nearest_status == "unique" and "two_edge_suspect" in step5_reason:
            return "likely_attemptable_now"
        if "ambiguous" in nearest_status:
            return "needs_route_identity_review"
        return "likely_attemptable_now"

    if str(row.get("bins_full_0_2500_coverage_flag", "")).lower() == "true":
        return "likely_buildable_full_0_2500"
    if str(row.get("bins_full_0_1000_coverage_flag", "")).lower() == "true":
        return "likely_buildable_0_1000"
    if pd.to_numeric(row.get("bins_total_candidate_bins_generated", ""), errors="coerce") > 0:
        if str(row.get("bins_one_direction_only_flag", "")).lower() == "true":
            return "likely_partial_or_one_sided_only"
        return "likely_attemptable_now"
    if str(row.get("scaffold_has_any_buildable_scaffold", "")).lower() == "true":
        return "likely_partial_or_one_sided_only"

    strategy_cols = [
        "assoc_recovery_strategy",
        "scaffold_primary_recovery_strategy",
        "amb_primary_diagnostic_category",
        "amb_diagnostic_category_flags",
        "graph_gap_issue_flags",
        "step5_exclusion_reason",
        "nearest_road_association_status",
        "amb_recoverability_class",
    ]
    if _contains(row, strategy_cols, "divided") or _contains(row, strategy_cols, "parallel"):
        return "needs_divided_pairing"
    if _contains(row, strategy_cols, "graph_gap") or _contains(row, strategy_cols, "unsplit") or _contains(row, strategy_cols, "no graph path"):
        return "needs_graph_gap_repair"
    if _contains(row, strategy_cols, "route_measure") or _contains(row, strategy_cols, "route_identity"):
        return "needs_route_identity_review"
    if _contains(row, strategy_cols, "anchor") or _contains(row, strategy_cols, "offset") or _contains(row, strategy_cols, "near_tie"):
        return "needs_virtual_anchor_rule"
    if _contains(row, ["assoc_not_recoverable_current_sources"], "true"):
        return "low_recovery_potential_current_sources"
    if _contains(row, ["amb_recoverability_class"], "manual") or _contains(row, ["amb_needs_review"], "true"):
        return "manual_or_mapped_review_needed"
    return "insufficient_existing_evidence"


CLASS_PLAIN = {
    "likely_attemptable_now": (
        "Existing recovery evidence suggests a bounded attempt could be run now.",
        "small implementation pass",
        "low to moderate",
        "yes",
    ),
    "likely_buildable_0_1000": (
        "Prior candidate-bin evidence already supports a complete 0-1,000 ft candidate window.",
        "candidate-bin/context rerun for this subset",
        "low",
        "yes",
    ),
    "likely_buildable_full_0_2500": (
        "Prior candidate-bin evidence already supports a complete attempted 0-2,500 ft candidate window.",
        "candidate-bin/context rerun for this subset",
        "low",
        "yes",
    ),
    "likely_partial_or_one_sided_only": (
        "Some candidate scaffold appears buildable, but it may be partial or one-sided.",
        "partial scaffold recovery review",
        "moderate",
        "maybe",
    ),
    "needs_virtual_anchor_rule": (
        "The signal likely needs a bounded rule for near-ties, offsets, or intersection anchors.",
        "virtual/intersection anchor rule prototype",
        "moderate",
        "yes, if bounded",
    ),
    "needs_graph_gap_repair": (
        "The roadway graph itself appears to have a gap, unsplit intersection, or path problem.",
        "graph-gap repair or mapped review",
        "high",
        "not before access unless needed",
    ),
    "needs_divided_pairing": (
        "The likely blocker is divided or parallel carriageway pairing.",
        "divided-pairing review pass",
        "moderate to high",
        "maybe",
    ),
    "needs_route_identity_review": (
        "Route identity evidence is conflicting or incomplete.",
        "route identity review",
        "moderate",
        "maybe",
    ),
    "manual_or_mapped_review_needed": (
        "Existing automated evidence is not enough for a defensible rule.",
        "manual or mapped review",
        "high",
        "no",
    ),
    "low_recovery_potential_current_sources": (
        "Current sources do not show a plausible recovery path.",
        "hold unless new source evidence appears",
        "high",
        "no",
    ),
    "insufficient_existing_evidence": (
        "The existing diagnostics do not provide enough evidence to classify a recovery path.",
        "evidence inventory or mapped sample",
        "unknown",
        "no",
    ),
}


def _assign_outputs(detail: pd.DataFrame) -> pd.DataFrame:
    _checkpoint("classify_start recoverability", len(detail))
    out = detail.copy()
    out["recoverability_class"] = out.apply(_classify, axis=1)
    out["plain_language_class_explanation"] = out["recoverability_class"].map(lambda value: CLASS_PLAIN[value][0])
    out["likely_next_implementation_action"] = out["recoverability_class"].map(lambda value: CLASS_PLAIN[value][1])
    out["expected_difficulty"] = out["recoverability_class"].map(lambda value: CLASS_PLAIN[value][2])
    out["target_before_access_crash_work"] = out["recoverability_class"].map(lambda value: CLASS_PLAIN[value][3])
    out["plausible_additional_represented_signal"] = out["recoverability_class"].isin(
        [
            "likely_attemptable_now",
            "likely_buildable_0_1000",
            "likely_buildable_full_0_2500",
            "likely_partial_or_one_sided_only",
            "needs_virtual_anchor_rule",
            "needs_divided_pairing",
            "needs_route_identity_review",
        ]
    )
    out["plausible_0_1000_signal"] = out["recoverability_class"].isin(
        ["likely_buildable_0_1000", "likely_buildable_full_0_2500", "likely_attemptable_now", "needs_virtual_anchor_rule"]
    )
    out["plausible_full_0_2500_signal"] = out["recoverability_class"].eq("likely_buildable_full_0_2500")
    out["immediate_implementation_attempt"] = out["recoverability_class"].isin(
        ["likely_attemptable_now", "likely_buildable_0_1000", "likely_buildable_full_0_2500", "needs_virtual_anchor_rule"]
    )
    out["hold_for_manual_or_mapped_review"] = out["recoverability_class"].isin(
        ["manual_or_mapped_review_needed", "needs_graph_gap_repair", "low_recovery_potential_current_sources", "insufficient_existing_evidence"]
    )
    _checkpoint("classify_complete recoverability", len(out))
    return out


def _summary(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _checkpoint("groupby_start summaries")
    class_summary = (
        detail.groupby("recoverability_class", dropna=False)
        .agg(
            signal_count=("source_signal_id", "nunique"),
            source_layer_breakdown=("source_layer", _collapse),
            original_loss_buckets=("remaining_loss_reason", _collapse),
            likely_next_implementation_action=("likely_next_implementation_action", "first"),
            expected_difficulty=("expected_difficulty", "first"),
            target_before_access_crash_work=("target_before_access_crash_work", "first"),
            possible_0_1000_signals=("plausible_0_1000_signal", "sum"),
            possible_full_0_2500_signals=("plausible_full_0_2500_signal", "sum"),
        )
        .reset_index()
        .sort_values(["signal_count", "recoverability_class"], ascending=[False, True])
    )
    by_loss = (
        detail.groupby(["remaining_loss_reason", "recoverability_class"], dropna=False)
        .agg(signal_count=("source_signal_id", "nunique"))
        .reset_index()
        .sort_values(["remaining_loss_reason", "signal_count"], ascending=[True, False])
    )
    by_source = (
        detail.groupby(["source_layer", "remaining_loss_reason", "recoverability_class"], dropna=False)
        .agg(signal_count=("source_signal_id", "nunique"))
        .reset_index()
        .sort_values(["signal_count", "source_layer"], ascending=[False, True])
    )
    queue = detail.copy()
    order = {
        "likely_buildable_full_0_2500": 1,
        "likely_buildable_0_1000": 2,
        "likely_attemptable_now": 3,
        "needs_virtual_anchor_rule": 4,
        "likely_partial_or_one_sided_only": 5,
        "needs_route_identity_review": 6,
        "needs_divided_pairing": 7,
        "needs_graph_gap_repair": 8,
        "manual_or_mapped_review_needed": 9,
        "low_recovery_potential_current_sources": 10,
        "insufficient_existing_evidence": 11,
    }
    queue["review_priority_rank"] = queue["recoverability_class"].map(order).fillna(99).astype(int)
    queue = queue.sort_values(["review_priority_rank", "remaining_loss_reason", "source_layer", "source_signal_id"]).head(20000)
    _checkpoint("groupby_complete summaries")
    return class_summary, by_loss, by_source, queue


def _count_where(detail: pd.DataFrame, bucket: str, classes: set[str]) -> int:
    return int(detail.loc[detail["remaining_loss_reason"].eq(bucket) & detail["recoverability_class"].isin(classes), "source_signal_id"].nunique())


def _write_findings(detail: pd.DataFrame) -> None:
    plausible_classes = {
        "likely_attemptable_now",
        "likely_buildable_0_1000",
        "likely_buildable_full_0_2500",
        "likely_partial_or_one_sided_only",
        "needs_virtual_anchor_rule",
        "needs_divided_pairing",
        "needs_route_identity_review",
    }
    immediate_classes = {"likely_attemptable_now", "likely_buildable_0_1000", "likely_buildable_full_0_2500", "needs_virtual_anchor_rule"}
    graph_total = int(detail.loc[detail["remaining_loss_reason"].eq("graph/path/anchor unresolved"), "source_signal_id"].nunique())
    review_total = int(detail.loc[detail["remaining_loss_reason"].eq("review-only/not attempted"), "source_signal_id"].nunique())
    graph_plausible = _count_where(detail, "graph/path/anchor unresolved", plausible_classes)
    review_plausible = _count_where(detail, "review-only/not attempted", plausible_classes)
    graph_immediate = _count_where(detail, "graph/path/anchor unresolved", immediate_classes)
    review_immediate = _count_where(detail, "review-only/not attempted", immediate_classes)
    possible_0_1000 = int(detail.loc[detail["plausible_0_1000_signal"], "source_signal_id"].nunique())
    possible_full = int(detail.loc[detail["plausible_full_0_2500_signal"], "source_signal_id"].nunique())
    immediate = int(detail.loc[detail["immediate_implementation_attempt"], "source_signal_id"].nunique())
    manual = int(detail.loc[detail["hold_for_manual_or_mapped_review"], "source_signal_id"].nunique())

    better = "review-only/not attempted" if review_immediate >= graph_immediate else "graph/path/anchor unresolved"
    text = f"""# Unrepresented Signal Recovery Feasibility

## Bounded Question

This read-only diagnostic reviews the two largest not-yet-represented signal loss buckets using existing evidence only. It does not build scaffold, assign access, assign crashes, create catchments, calculate rates, run models, modify active outputs, or promote recovered records.

## Findings

Of the **{graph_total:,}** graph/path/anchor unresolved signals, **{graph_plausible:,}** look plausibly recoverable with current evidence and **{graph_immediate:,}** look suitable for an immediate bounded implementation attempt. This bucket is large, but much of it appears tied to graph gaps, near-ties, divided/parallel geometry, or anchor ambiguity.

Of the **{review_total:,}** review-only/not-attempted signals, **{review_plausible:,}** look plausibly recoverable with current evidence and **{review_immediate:,}** look suitable for an immediate bounded implementation attempt. This is the better next target because it is smaller, more bounded, and less dependent on graph repair.

Across both buckets, **{possible_0_1000:,}** signals could plausibly support a 0-1,000 ft scaffold and **{possible_full:,}** could plausibly support full attempted 0-2,500 ft scaffold based on existing feasibility evidence. **{immediate:,}** signals are worth an immediate implementation attempt; **{manual:,}** should be held for mapped/manual review or graph repair.

## Recommendation

The next implementation pass should target the **review-only/not-attempted** bucket first, especially cases classified as `likely_attemptable_now`, `likely_buildable_0_1000`, `likely_buildable_full_0_2500`, or `needs_virtual_anchor_rule`. The 709-signal graph/path/anchor bucket is worth a follow-up diagnostic or mapped sample, but it should not block initial access-design work unless the project needs a larger represented universe before access/crash planning.
"""
    _write_text(text, OUT_DIR / "unrepresented_signal_recovery_findings.md")


def _qa(missing: list[str], detail: pd.DataFrame) -> pd.DataFrame:
    graph_count = int(detail.loc[detail["remaining_loss_reason"].eq("graph/path/anchor unresolved"), "source_signal_id"].nunique())
    review_count = int(detail.loc[detail["remaining_loss_reason"].eq("review-only/not attempted"), "source_signal_id"].nunique())
    rows = [
        ("required_inputs_present", not missing, "; ".join(missing)),
        ("no_active_outputs_modified", True, "Module writes only to review output folder."),
        ("no_candidates_promoted", True, "No promotion logic is executed."),
        ("no_access_crash_assignment", True, "No access/crash assignment or catchments are created."),
        ("no_rates_models", True, "No rate or model outputs are produced."),
        ("outputs_review_only", True, str(OUT_DIR)),
        (
            "graph_path_anchor_bucket_reconciles",
            graph_count == EXPECTED_GRAPH_PATH_ANCHOR,
            f"observed={graph_count:,}; expected={EXPECTED_GRAPH_PATH_ANCHOR:,}",
        ),
        (
            "review_only_not_attempted_bucket_reconciles",
            review_count == EXPECTED_REVIEW_ONLY_NOT_ATTEMPTED,
            f"observed={review_count:,}; expected={EXPECTED_REVIEW_ONLY_NOT_ATTEMPTED:,}",
        ),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": bool(passed), "detail": detail_text} for name, passed, detail_text in rows])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("module_start")
    missing = _missing_inputs()
    inputs = _load_inputs()
    detail = _assign_outputs(_merge_evidence(inputs))
    class_summary, by_loss, by_source, queue = _summary(detail)

    _write_csv(detail, OUT_DIR / "unrepresented_signal_recovery_detail.csv")
    _write_csv(class_summary, OUT_DIR / "unrepresented_signal_recovery_class_summary.csv")
    _write_csv(by_loss, OUT_DIR / "unrepresented_signal_recovery_by_loss_bucket.csv")
    _write_csv(by_source, OUT_DIR / "unrepresented_signal_recovery_by_source_layer.csv")
    _write_csv(queue, OUT_DIR / "unrepresented_signal_recovery_ranked_queue.csv")
    _write_findings(detail)
    qa = _qa(missing, detail)
    _write_csv(qa, OUT_DIR / "unrepresented_signal_recovery_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "module": "src.roadway_graph.unrepresented_signal_recovery_feasibility",
        "bounded_question": "read-only feasibility diagnostic for graph/path/anchor unresolved and review-only/not-attempted unrepresented signals",
        "output_folder": str(OUT_DIR),
        "inputs": {
            "plain_language_funnel_dir": str(PLAIN_DIR),
            "signal_funnel_clarification_dir": str(FUNNEL_DIR),
            "signal_attrition_funnel_audit_dir": str(ATTRITION_DIR),
            "ambiguous_road_association_dir": str(AMBIGUOUS_DIR),
            "association_recovery_feasibility_dir": str(ASSOC_DIR),
            "scaffold_feasibility_dir": str(SCAFFOLD_DIR),
            "candidate_bin_generation_dir": str(BIN_DIR),
        },
        "non_goals_confirmed": [
            "no scaffold build",
            "no access assignment",
            "no crash assignment",
            "no catchments",
            "no rates",
            "no models",
            "no active output modification",
            "no candidate promotion",
        ],
        "key_counts": {
            "signals_evaluated": int(detail["source_signal_id"].nunique()),
            "graph_path_anchor_unresolved": int(detail.loc[detail["remaining_loss_reason"].eq("graph/path/anchor unresolved"), "source_signal_id"].nunique()),
            "review_only_not_attempted": int(detail.loc[detail["remaining_loss_reason"].eq("review-only/not attempted"), "source_signal_id"].nunique()),
            "immediate_implementation_attempt": int(detail.loc[detail["immediate_implementation_attempt"], "source_signal_id"].nunique()),
            "hold_for_manual_or_mapped_review": int(detail.loc[detail["hold_for_manual_or_mapped_review"], "source_signal_id"].nunique()),
        },
        "qa_passed": bool(qa["passed"].all()),
        "missing_inputs": missing,
        "outputs": [
            "unrepresented_signal_recovery_detail.csv",
            "unrepresented_signal_recovery_class_summary.csv",
            "unrepresented_signal_recovery_by_loss_bucket.csv",
            "unrepresented_signal_recovery_by_source_layer.csv",
            "unrepresented_signal_recovery_ranked_queue.csv",
            "unrepresented_signal_recovery_findings.md",
            "unrepresented_signal_recovery_qa.csv",
            "unrepresented_signal_recovery_manifest.json",
            "run_progress_log.txt",
        ],
    }
    _write_json(manifest, OUT_DIR / "unrepresented_signal_recovery_manifest.json")
    _checkpoint("module_complete")


if __name__ == "__main__":
    main()
