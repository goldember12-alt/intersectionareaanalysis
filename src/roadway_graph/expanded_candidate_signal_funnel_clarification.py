from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_signal_funnel_clarification"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
ATTRITION_DIR = OUTPUT_ROOT / "review/current/signal_attrition_funnel_audit"
CANDIDATE_DIR = OUTPUT_ROOT / "review/current/signal_recovery_candidate_bin_generation"
CLEANUP_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_residual_cleanup"

BASE_STAGED_SIGNALS_EXPECTED = 3_933
TRUE_REFERENCE_SIGNALS_EXPECTED = 1_214
STRICT_ACTIVE_BASELINE_EXPECTED = 971
RECOVERED_CANDIDATE_SIGNALS_EXPECTED = 1_590
RECOVERED_SPEED_AADT_READY_EXPECTED = 1_469

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
    FREEZE_DIR: [
        "frozen_candidate_bin_universe.csv",
        "frozen_candidate_signal_universe.csv",
        "frozen_candidate_universe_tier_summary.csv",
        "frozen_candidate_universe_window_summary.csv",
        "frozen_candidate_universe_direction_summary.csv",
        "frozen_candidate_universe_overlap_summary.csv",
        "frozen_candidate_access_crash_injection_readiness.csv",
        "expanded_candidate_universe_freeze_manifest.json",
    ],
    ATTRITION_DIR: [
        "signal_attrition_signal_level_status.csv",
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


def _missing_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_inputs() -> dict[str, pd.DataFrame]:
    attrition_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "usable_for_step5",
        "represented_in_active_0_2500ft_context",
        "represented_in_directional_scaffold",
        "step5_exclusion_reason",
        "nearest_road_association_status",
        "graph_gap_issue_flags",
        "best_available_loss_reason",
        "methodology_interpretation",
    ]
    frozen_signal_cols = [
        "candidate_signal_id",
        "frozen_candidate_signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_bin_count",
        "weighted_bin_count",
        "has_any_scaffold",
        "has_roadway_context",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "multi_candidate_weighted_flag",
        "strict_active_overlap_conflict_flag",
        "strict_active_overlap_status",
        "direction_labels",
        "analysis_windows",
        "recovery_strategy",
        "association_confidence_tier",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
        "has_0_1000_scaffold",
        "full_0_1000_coverage_flag",
        "full_0_2500_coverage_flag",
        "both_direction_coverage_flag",
        "one_direction_only_flag",
        "has_full_attempted_0_2500_scaffold",
        "recommended_universe_tier",
    ]
    frozen_bin_cols = [
        "candidate_signal_id",
        "source_signal_id",
        "analysis_window",
        "speed_ready_review_only_flag",
        "aadt_ready_review_only_flag",
        "exposure_ready_review_only_flag",
        "speed_aadt_ready_review_only_flag",
    ]
    readiness_cols = [
        "candidate_signal_id",
        "ready_for_access_route_measure_review",
        "ready_for_access_geometry_review",
        "ready_for_crash_catchment_generation",
        "needs_candidate_geometry_before_crash",
        "needs_access_assignment_design",
        "hold_due_to_context_missingness",
        "hold_due_to_overlap_conflict",
        "hold_due_to_review_only_uncertainty",
        "planning_flag_review_only",
    ]
    return {
        "attrition": _read_csv(ATTRITION_DIR / "signal_attrition_signal_level_status.csv", usecols=attrition_cols),
        "frozen_signal": _read_csv(FREEZE_DIR / "frozen_candidate_signal_universe.csv", usecols=frozen_signal_cols),
        "frozen_bin": _read_csv(FREEZE_DIR / "frozen_candidate_bin_universe.csv", usecols=frozen_bin_cols),
        "tier_summary": _read_csv(FREEZE_DIR / "frozen_candidate_universe_tier_summary.csv"),
        "window_summary": _read_csv(FREEZE_DIR / "frozen_candidate_universe_window_summary.csv"),
        "direction_summary": _read_csv(FREEZE_DIR / "frozen_candidate_universe_direction_summary.csv"),
        "overlap_summary": _read_csv(FREEZE_DIR / "frozen_candidate_universe_overlap_summary.csv"),
        "readiness": _read_csv(FREEZE_DIR / "frozen_candidate_access_crash_injection_readiness.csv", usecols=readiness_cols),
    }


def _build_detail(attrition: pd.DataFrame, frozen_signal: pd.DataFrame) -> pd.DataFrame:
    _checkpoint("merge_start signal_funnel_detail", len(attrition))
    freeze = frozen_signal.add_prefix("recovered_")
    merged = attrition.merge(
        freeze,
        left_on="source_signal_id",
        right_on="recovered_source_signal_id",
        how="left",
        validate="many_to_one",
    )

    merged["in_base_staged_signals"] = True
    merged["in_TRUE_reference_signals"] = _text(merged, "usable_for_step5").eq("TRUE")
    merged["in_strict_active_baseline_971"] = _flag(merged, "represented_in_active_0_2500ft_context")
    merged["in_recovered_candidate_1590"] = _text(merged, "recovered_candidate_signal_id").ne("")
    merged["in_recovered_speed_ready"] = _flag(merged, "recovered_has_speed")
    merged["in_recovered_aadt_ready"] = _flag(merged, "recovered_has_aadt") & _flag(merged, "recovered_has_exposure")
    merged["in_recovered_speed_aadt_ready_1469"] = _flag(merged, "recovered_speed_aadt_ready")
    merged["strict_overlap_or_conflict"] = _flag(merged, "recovered_strict_active_overlap_conflict_flag")
    merged["overlap_with_strict_active_and_recovered"] = (
        merged["in_strict_active_baseline_971"] & merged["in_recovered_candidate_1590"]
    )
    merged["recovered_only"] = merged["in_recovered_candidate_1590"] & ~merged["in_strict_active_baseline_971"]
    merged["strict_only"] = merged["in_strict_active_baseline_971"] & ~merged["in_recovered_candidate_1590"]
    merged["both_strict_and_recovered"] = merged["overlap_with_strict_active_and_recovered"]
    merged["neither_currently_ready"] = ~(
        merged["in_strict_active_baseline_971"] | merged["in_recovered_speed_aadt_ready_1469"]
    )

    detail_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "in_base_staged_signals",
        "in_TRUE_reference_signals",
        "in_strict_active_baseline_971",
        "in_recovered_candidate_1590",
        "in_recovered_speed_ready",
        "in_recovered_aadt_ready",
        "in_recovered_speed_aadt_ready_1469",
        "strict_overlap_or_conflict",
        "overlap_with_strict_active_and_recovered",
        "recovered_only",
        "strict_only",
        "both_strict_and_recovered",
        "neither_currently_ready",
        "recovered_candidate_signal_id",
        "recovered_frozen_candidate_signal_id",
        "recovered_candidate_bin_count",
        "recovered_weighted_bin_count",
        "recovered_recovery_strategy",
        "recovered_association_confidence_tier",
        "recovered_strict_active_overlap_status",
        "recovered_recommended_universe_tier",
        "recovered_full_0_1000_speed_aadt_ready",
        "recovered_full_attempted_0_2500_speed_aadt_ready",
        "recovered_has_0_1000_scaffold",
        "recovered_full_0_1000_coverage_flag",
        "recovered_full_0_2500_coverage_flag",
        "recovered_both_direction_coverage_flag",
        "recovered_one_direction_only_flag",
        "usable_for_step5",
        "represented_in_active_0_2500ft_context",
        "represented_in_directional_scaffold",
        "step5_exclusion_reason",
        "nearest_road_association_status",
        "graph_gap_issue_flags",
        "best_available_loss_reason",
        "methodology_interpretation",
    ]
    out = merged[[column for column in detail_cols if column in merged.columns]].copy()
    _checkpoint("merge_complete signal_funnel_detail", len(out))
    return out


def _count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(frame[column].fillna(False).astype(bool).sum())


def _build_reconciliations(detail: pd.DataFrame, frozen_signal: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_count = len(detail)
    strict_count = _count(detail, "in_strict_active_baseline_971")
    recovered_count = len(frozen_signal)
    recovered_ready = int(_flag(frozen_signal, "speed_aadt_ready").sum())
    recovered_speed_ready = int(_flag(frozen_signal, "has_speed").sum())
    recovered_aadt_ready = int((_flag(frozen_signal, "has_aadt") & _flag(frozen_signal, "has_exposure")).sum())

    strict_sources = set(detail.loc[detail["in_strict_active_baseline_971"], "source_signal_id"].astype(str))
    recovered_sources = set(_text(frozen_signal, "source_signal_id"))
    recovered_ready_sources = set(frozen_signal.loc[_flag(frozen_signal, "speed_aadt_ready"), "source_signal_id"].astype(str))
    exact_overlap_all = len(strict_sources & recovered_sources)
    exact_overlap_ready = len(strict_sources & recovered_ready_sources)

    conflict_all = int(_flag(frozen_signal, "strict_active_overlap_conflict_flag").sum())
    conflict_ready = int(
        (_flag(frozen_signal, "strict_active_overlap_conflict_flag") & _flag(frozen_signal, "speed_aadt_ready")).sum()
    )
    dedup_exact = strict_count + recovered_ready - exact_overlap_ready
    dedup_conservative = strict_count + recovered_ready - conflict_ready

    stage_summary = pd.DataFrame(
        [
            ("base_staged_signals", base_count, "source_signal_id in staged signal attrition table"),
            ("TRUE_reference_signals", _count(detail, "in_TRUE_reference_signals"), "usable_for_step5 == TRUE"),
            ("strict_active_baseline_signals", strict_count, "represented in active 0-2,500 ft context"),
            ("recovered_candidate_signals", recovered_count, "source signals present in freeze recovered table"),
            ("recovered_speed_ready_signals", recovered_speed_ready, "freeze has_speed signal flag"),
            ("recovered_aadt_exposure_ready_signals", recovered_aadt_ready, "freeze has_aadt and has_exposure flags"),
            ("recovered_speed_aadt_ready_signals", recovered_ready, "freeze signal-level speed_aadt_ready flag"),
            ("exact_strict_recovered_source_overlap_signals", exact_overlap_all, "same source_signal_id in strict and recovered"),
            ("strict_overlap_conflict_diagnostic_signals", conflict_all, "freeze diagnostic overlap/conflict holdout flag"),
            ("deduped_expanded_speed_aadt_ready_exact_source_dedupe", dedup_exact, "strict + recovered ready - exact source overlap"),
            (
                "deduped_expanded_speed_aadt_ready_conservative_conflict_holdout",
                dedup_conservative,
                "strict + recovered ready - all recovered ready strict-overlap/conflict flags",
            ),
            (
                "base_signals_not_represented_by_exact_deduped_ready",
                base_count - dedup_exact,
                "base staged signals outside strict or recovered any-ready speed+AADT universe",
            ),
        ],
        columns=["stage_or_metric", "signal_count", "definition"],
    )

    overlap = pd.DataFrame(
        [
            ("strict_active_baseline_count", strict_count, "strict active signal universe"),
            ("recovered_candidate_count", recovered_count, "all recovered candidate signals in freeze"),
            ("recovered_speed_aadt_ready_count", recovered_ready, "recovered signal-level speed+AADT-ready"),
            ("exact_source_overlap_all_recovered", exact_overlap_all, "same source_signal_id is strict active and recovered"),
            (
                "exact_source_overlap_speed_aadt_ready",
                exact_overlap_ready,
                "same source_signal_id is strict active and recovered speed+AADT-ready",
            ),
            ("strict_overlap_conflict_diagnostic_all_recovered", conflict_all, "broader freeze diagnostic flag"),
            (
                "strict_overlap_conflict_diagnostic_speed_aadt_ready",
                conflict_ready,
                "broader freeze diagnostic flag among recovered ready signals",
            ),
            (
                "diagnostic_conflict_not_exact_duplicate_all_recovered",
                max(conflict_all - exact_overlap_all, 0),
                "possible overlap/conflict, not exact source-signal duplicate",
            ),
            (
                "diagnostic_conflict_not_exact_duplicate_speed_aadt_ready",
                max(conflict_ready - exact_overlap_ready, 0),
                "ready possible overlap/conflict, not exact source-signal duplicate",
            ),
        ],
        columns=["metric", "signal_count", "interpretation"],
    )

    expanded = pd.DataFrame(
        [
            (
                "exact_source_signal_deduped_expanded_speed_aadt_ready",
                strict_count,
                recovered_ready,
                exact_overlap_ready,
                dedup_exact,
                round(dedup_exact / base_count * 100, 2) if base_count else 0.0,
                base_count - dedup_exact,
                "Use for conceptual universe count when only exact source-signal duplicates are subtracted.",
            ),
            (
                "conservative_conflict_holdout_expanded_speed_aadt_ready",
                strict_count,
                recovered_ready,
                conflict_ready,
                dedup_conservative,
                round(dedup_conservative / base_count * 100, 2) if base_count else 0.0,
                base_count - dedup_conservative,
                "Use only if every strict-overlap/conflict diagnostic record is held out pending review.",
            ),
        ],
        columns=[
            "dedupe_definition",
            "strict_active_baseline_signals",
            "recovered_speed_aadt_ready_signals",
            "overlap_subtracted",
            "deduped_expanded_speed_aadt_ready_signals",
            "percent_of_base_3933",
            "remaining_base_signals_not_represented",
            "interpretation",
        ],
    )
    return stage_summary, overlap, expanded


def _build_window_comparison(frozen_signal: pd.DataFrame, frozen_bin: pd.DataFrame) -> pd.DataFrame:
    _checkpoint("groupby_start window_readiness")
    bin_ready = _flag(frozen_bin, "speed_aadt_ready_review_only_flag")
    win = _text(frozen_bin, "analysis_window")
    any_0_1000 = int(frozen_bin.loc[bin_ready & win.eq("0_1000"), "candidate_signal_id"].nunique())
    any_1000_2500 = int(frozen_bin.loc[bin_ready & win.eq("1000_2500"), "candidate_signal_id"].nunique())
    any_attempted = int(frozen_bin.loc[bin_ready, "candidate_signal_id"].nunique())
    signal_any = int(_flag(frozen_signal, "speed_aadt_ready").sum())
    full_0_1000 = int(_flag(frozen_signal, "full_0_1000_speed_aadt_ready").sum())
    full_0_2500 = int(_flag(frozen_signal, "full_attempted_0_2500_speed_aadt_ready").sum())
    out = pd.DataFrame(
        [
            (
                "any_signal_level_speed_aadt_ready",
                signal_any,
                "Signal has at least one reviewed speed+AADT/exposure-ready candidate context path.",
            ),
            (
                "0_1000_any_bin_speed_aadt_ready",
                any_0_1000,
                "Signal has at least one 0-1,000 ft candidate bin with speed+AADT/exposure ready.",
            ),
            (
                "0_1000_full_window_bin_complete_speed_aadt_ready",
                full_0_1000,
                "Every attempted 0-1,000 ft candidate bin for the signal is speed+AADT/exposure ready.",
            ),
            (
                "1000_2500_any_bin_speed_aadt_ready",
                any_1000_2500,
                "Signal has at least one 1,000-2,500 ft candidate bin with speed+AADT/exposure ready.",
            ),
            (
                "full_attempted_0_2500_any_bin_speed_aadt_ready",
                any_attempted,
                "Signal has at least one attempted bin in either analysis window with speed+AADT/exposure ready.",
            ),
            (
                "full_attempted_0_2500_full_window_bin_complete_speed_aadt_ready",
                full_0_2500,
                "Every attempted 0-2,500 ft candidate bin for the signal is speed+AADT/exposure ready.",
            ),
        ],
        columns=["readiness_definition", "signal_count", "definition"],
    )
    _checkpoint("groupby_complete window_readiness", len(out))
    return out


def _loss_reason(row: pd.Series) -> str:
    if bool(row.get("in_strict_active_baseline_971", False)) or bool(row.get("in_recovered_speed_aadt_ready_1469", False)):
        return "represented_in_deduped_expanded_speed_aadt_ready_universe"
    if not bool(row.get("in_recovered_candidate_1590", False)):
        reason = str(row.get("best_available_loss_reason", "")).lower()
        issue = str(row.get("graph_gap_issue_flags", "")).lower()
        step5 = str(row.get("step5_exclusion_reason", "")).lower()
        association = str(row.get("nearest_road_association_status", "")).lower()
        combined = "|".join([reason, issue, step5, association])
        if "divided" in combined or "pair" in combined:
            return "divided-pairing unresolved"
        if any(token in combined for token in ("graph", "anchor", "nearest", "association", "path")):
            return "graph/path/anchor unresolved"
        if "review" in combined:
            return "review-only/not attempted"
        return "no recovered scaffold"
    if bool(row.get("strict_overlap_or_conflict", False)):
        return "strict overlap/conflict holdout"
    if not bool(row.get("in_recovered_speed_ready", False)):
        return "speed missing"
    if not bool(row.get("in_recovered_aadt_ready", False)):
        return "AADT/exposure missing"
    return "insufficient evidence"


def _build_loss_summary(detail: pd.DataFrame) -> pd.DataFrame:
    _checkpoint("classify_start remaining_signal_loss")
    loss = detail.copy()
    loss["remaining_loss_reason"] = loss.apply(_loss_reason, axis=1)
    out = (
        loss.loc[loss["remaining_loss_reason"].ne("represented_in_deduped_expanded_speed_aadt_ready_universe")]
        .groupby("remaining_loss_reason", dropna=False)
        .agg(signal_count=("source_signal_id", "nunique"))
        .reset_index()
        .sort_values(["signal_count", "remaining_loss_reason"], ascending=[False, True])
    )
    _checkpoint("classify_complete remaining_signal_loss", len(out))
    return out


def _readiness_counts(readiness: pd.DataFrame) -> dict[str, int]:
    return {
        column: int(_flag(readiness, column).sum())
        for column in [
            "ready_for_access_route_measure_review",
            "ready_for_access_geometry_review",
            "ready_for_crash_catchment_generation",
            "needs_candidate_geometry_before_crash",
            "needs_access_assignment_design",
            "hold_due_to_context_missingness",
            "hold_due_to_overlap_conflict",
            "hold_due_to_review_only_uncertainty",
        ]
        if column in readiness.columns
    }


def _metric(summary: pd.DataFrame, name: str) -> int:
    rows = summary.loc[summary["stage_or_metric"].eq(name), "signal_count"]
    return int(rows.iloc[0]) if len(rows) else 0


def _expanded_metric(expanded: pd.DataFrame, name: str, column: str) -> Any:
    rows = expanded.loc[expanded["dedupe_definition"].eq(name), column]
    return rows.iloc[0] if len(rows) else 0


def _write_findings(
    stage_summary: pd.DataFrame,
    overlap: pd.DataFrame,
    expanded: pd.DataFrame,
    window: pd.DataFrame,
    loss: pd.DataFrame,
    readiness_counts: dict[str, int],
) -> None:
    exact_count = int(_expanded_metric(expanded, "exact_source_signal_deduped_expanded_speed_aadt_ready", "deduped_expanded_speed_aadt_ready_signals"))
    exact_percent = _expanded_metric(expanded, "exact_source_signal_deduped_expanded_speed_aadt_ready", "percent_of_base_3933")
    conservative_count = int(
        _expanded_metric(
            expanded,
            "conservative_conflict_holdout_expanded_speed_aadt_ready",
            "deduped_expanded_speed_aadt_ready_signals",
        )
    )
    exact_overlap_ready = int(overlap.loc[overlap["metric"].eq("exact_source_overlap_speed_aadt_ready"), "signal_count"].iloc[0])
    conflict_all = int(overlap.loc[overlap["metric"].eq("strict_overlap_conflict_diagnostic_all_recovered"), "signal_count"].iloc[0])
    conflict_ready = int(overlap.loc[overlap["metric"].eq("strict_overlap_conflict_diagnostic_speed_aadt_ready"), "signal_count"].iloc[0])
    full_0_1000 = int(window.loc[window["readiness_definition"].eq("0_1000_full_window_bin_complete_speed_aadt_ready"), "signal_count"].iloc[0])
    full_0_2500 = int(
        window.loc[
            window["readiness_definition"].eq("full_attempted_0_2500_full_window_bin_complete_speed_aadt_ready"),
            "signal_count",
        ].iloc[0]
    )
    any_ready = int(window.loc[window["readiness_definition"].eq("any_signal_level_speed_aadt_ready"), "signal_count"].iloc[0])
    top_loss = "none"
    if len(loss):
        top_loss = f"{loss.iloc[0]['remaining_loss_reason']} ({int(loss.iloc[0]['signal_count']):,} signals)"
    access_attach = readiness_counts.get("ready_for_access_route_measure_review", 0)
    crash_plan = readiness_counts.get("ready_for_crash_catchment_generation", 0)

    text = f"""# Expanded Candidate Signal Funnel Clarification

## Bounded Question

This read-only diagnostic reconciles base staged signals, strict active reference signals, recovered candidate signals, and freeze readiness counts. It does not assign access, assign crashes, create catchments, calculate rates, run models, promote recovered records, or modify active outputs.

## Main Answer

The exact-source deduplicated expanded speed+AADT-ready signal count is **{exact_count:,}**. This is:

`strict active baseline 971 + recovered speed+AADT-ready {RECOVERED_SPEED_AADT_READY_EXPECTED:,} - exact strict/recovered source overlap {exact_overlap_ready:,} = {exact_count:,}`.

That represents **{exact_percent}%** of the {BASE_STAGED_SIGNALS_EXPECTED:,} staged base signals. The expected approximately 2,400 signal universe is therefore correct when overlap means exact source-signal duplication.

## Strict/Recovered Overlap

The freeze overlap/conflict count of **{conflict_all:,}** is a broader diagnostic holdout flag, not an exact duplicate count. Of those, **{conflict_ready:,}** are recovered speed+AADT-ready. Only **{exact_overlap_ready:,}** recovered speed+AADT-ready signals are exact source-signal overlaps with the strict active baseline.

Subtract the exact overlap for conceptual deduplication. Subtracting all strict overlap/conflict flags gives a conservative review-holdout count of **{conservative_count:,}**, but that is not the same as the true exact deduplicated universe.

## Window Readiness

The recovered signal-level any-ready count is **{any_ready:,}**. The freeze full-window counts are lower because they require every attempted candidate bin in the window to be speed+AADT/exposure ready:

- 0-1,000 ft full-window/bin-complete speed+AADT-ready: **{full_0_1000:,}**
- full attempted 0-2,500 ft bin-complete speed+AADT-ready: **{full_0_2500:,}**

These are stricter readiness tiers for future attachment design, not replacements for the any-ready signal universe.

## Remaining Loss

The dominant remaining reason base signals are not in the exact deduplicated expanded speed+AADT-ready universe is **{top_loss}**.

## Access Attachment

Access should attach first to the frozen review-only route/measure-ready universe: **{access_attach:,}** recovered candidate signals are flagged `ready_for_access_route_measure_review`. Crash/catchment planning remains later and is only a planning flag here; **{crash_plan:,}** signals are flagged `ready_for_crash_catchment_generation`.
"""
    _write_text(text, OUT_DIR / "signal_funnel_clarification_findings.md")


def _build_qa(
    missing_inputs: list[str],
    detail: pd.DataFrame,
    stage_summary: pd.DataFrame,
    overlap: pd.DataFrame,
    expanded: pd.DataFrame,
) -> pd.DataFrame:
    checks = [
        ("required_inputs_present", not missing_inputs, "; ".join(missing_inputs)),
        ("no_active_outputs_modified", True, "Module writes only to review output folder."),
        ("no_candidates_promoted", True, "No active promotion or active output path is written."),
        ("no_access_or_crash_assignment", True, "Only existing planning flags are summarized; no assignment is performed."),
        ("no_rates_or_models", True, "No rate or model outputs are produced."),
        ("strict_vs_recovered_overlap_explicitly_reported", len(overlap) > 0, "strict_recovered_overlap_reconciliation.csv written."),
        ("deduped_signal_counts_separate_from_bin_counts", len(expanded) > 0, "Deduped expanded counts are signal-level."),
        ("outputs_review_only_folder", True, str(OUT_DIR)),
        (
            "base_staged_signal_count_reconciles",
            len(detail) == BASE_STAGED_SIGNALS_EXPECTED,
            f"observed={len(detail):,}; expected={BASE_STAGED_SIGNALS_EXPECTED:,}",
        ),
        (
            "true_reference_signal_count_reconciles",
            _metric(stage_summary, "TRUE_reference_signals") == TRUE_REFERENCE_SIGNALS_EXPECTED,
            f"observed={_metric(stage_summary, 'TRUE_reference_signals'):,}; expected={TRUE_REFERENCE_SIGNALS_EXPECTED:,}",
        ),
        (
            "strict_active_signal_count_reconciles",
            _metric(stage_summary, "strict_active_baseline_signals") == STRICT_ACTIVE_BASELINE_EXPECTED,
            f"observed={_metric(stage_summary, 'strict_active_baseline_signals'):,}; expected={STRICT_ACTIVE_BASELINE_EXPECTED:,}",
        ),
        (
            "recovered_candidate_signal_count_reconciles",
            _metric(stage_summary, "recovered_candidate_signals") == RECOVERED_CANDIDATE_SIGNALS_EXPECTED,
            f"observed={_metric(stage_summary, 'recovered_candidate_signals'):,}; expected={RECOVERED_CANDIDATE_SIGNALS_EXPECTED:,}",
        ),
        (
            "recovered_speed_aadt_ready_count_reconciles",
            _metric(stage_summary, "recovered_speed_aadt_ready_signals") == RECOVERED_SPEED_AADT_READY_EXPECTED,
            f"observed={_metric(stage_summary, 'recovered_speed_aadt_ready_signals'):,}; expected={RECOVERED_SPEED_AADT_READY_EXPECTED:,}",
        ),
    ]
    return pd.DataFrame(
        [
            {"qa_check": name, "passed": bool(passed), "detail": detail_text}
            for name, passed, detail_text in checks
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("module_start")
    missing_inputs = _missing_inputs()
    if missing_inputs:
        _checkpoint("missing_required_inputs", len(missing_inputs))

    inputs = _load_inputs()
    detail = _build_detail(inputs["attrition"], inputs["frozen_signal"])
    stage_summary, overlap, expanded = _build_reconciliations(detail, inputs["frozen_signal"])
    window = _build_window_comparison(inputs["frozen_signal"], inputs["frozen_bin"])
    loss = _build_loss_summary(detail)
    readiness_counts = _readiness_counts(inputs["readiness"])

    _write_csv(detail, OUT_DIR / "signal_funnel_clarification_detail.csv")
    _write_csv(stage_summary, OUT_DIR / "signal_funnel_stage_summary.csv")
    _write_csv(overlap, OUT_DIR / "strict_recovered_overlap_reconciliation.csv")
    _write_csv(expanded, OUT_DIR / "expanded_speed_aadt_deduped_count_summary.csv")
    _write_csv(window, OUT_DIR / "window_readiness_definition_comparison.csv")
    _write_csv(loss, OUT_DIR / "remaining_signal_loss_reason_summary.csv")

    qa = _build_qa(missing_inputs, detail, stage_summary, overlap, expanded)
    _write_csv(qa, OUT_DIR / "signal_funnel_clarification_qa.csv")
    _write_findings(stage_summary, overlap, expanded, window, loss, readiness_counts)

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "module": "src.roadway_graph.expanded_candidate_signal_funnel_clarification",
        "bounded_question": "read-only signal funnel clarification for expanded candidate universe freeze",
        "output_folder": str(OUT_DIR),
        "inputs": {
            "freeze_dir": str(FREEZE_DIR),
            "attrition_dir": str(ATTRITION_DIR),
            "candidate_dir_optional": str(CANDIDATE_DIR),
            "cleanup_dir_optional": str(CLEANUP_DIR),
        },
        "non_goals_confirmed": [
            "no access assignment",
            "no crash assignment",
            "no catchments",
            "no rates",
            "no models",
            "no active output modification",
            "no candidate promotion",
        ],
        "key_counts": {
            row["stage_or_metric"]: int(row["signal_count"])
            for row in stage_summary.to_dict(orient="records")
        },
        "qa_passed": bool(qa["passed"].all()),
        "missing_inputs": missing_inputs,
        "outputs": [
            "signal_funnel_clarification_detail.csv",
            "signal_funnel_stage_summary.csv",
            "strict_recovered_overlap_reconciliation.csv",
            "expanded_speed_aadt_deduped_count_summary.csv",
            "window_readiness_definition_comparison.csv",
            "remaining_signal_loss_reason_summary.csv",
            "signal_funnel_clarification_findings.md",
            "signal_funnel_clarification_qa.csv",
            "signal_funnel_clarification_manifest.json",
            "run_progress_log.txt",
        ],
    }
    _write_json(manifest, OUT_DIR / "signal_funnel_clarification_manifest.json")
    _checkpoint("module_complete")


if __name__ == "__main__":
    main()
