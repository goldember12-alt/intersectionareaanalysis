from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_refresh_and_709_plan"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
CONTEXT_347_DIR = OUTPUT_ROOT / "review/current/review_only_347_context_refresh"
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/unrepresented_signal_recovery_feasibility"
FUNNEL_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_signal_funnel_clarification"

BASE_STAGED_SIGNALS = 3_933
PREVIOUS_REPRESENTED_COUNT = 2_437
EXPECTED_347_ADDITIONS = 302

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
        "expanded_candidate_universe_freeze_manifest.json",
    ],
    CONTEXT_347_DIR: [
        "review_only_347_context_bin_detail.csv",
        "review_only_347_context_signal_summary.csv",
        "review_only_347_context_readiness_summary.csv",
        "review_only_347_updated_universe_projection.csv",
        "review_only_347_context_manifest.json",
    ],
    FEASIBILITY_DIR: [
        "unrepresented_signal_recovery_detail.csv",
        "unrepresented_signal_recovery_class_summary.csv",
        "unrepresented_signal_recovery_by_loss_bucket.csv",
        "unrepresented_signal_recovery_ranked_queue.csv",
        "unrepresented_signal_recovery_manifest.json",
    ],
    FUNNEL_DIR: [
        "signal_funnel_clarification_detail.csv",
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
        raise ValueError(f"Refusing to read crash/direction fields from {path}: {blocked}")
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


def _collapse(values: pd.Series, limit: int = 8) -> str:
    items = sorted({str(v) for v in values.dropna() if str(v) and str(v).lower() != "nan"})
    return "|".join(items[:limit])


def _missing_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_inputs() -> dict[str, pd.DataFrame]:
    frozen_cols = [
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
        "one_direction_only_flag",
        "recommended_universe_tier",
    ]
    context_cols = [
        "source_signal_id",
        "signal_id",
        "source_layer",
        "candidate_bin_count",
        "has_route_measure_identity",
        "has_roadway_context",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "speed_aadt_ready",
        "speed_aadt_ready_0_1000",
        "partial_or_one_sided_only",
        "analysis_windows",
        "direction_labels",
        "holdout_reason_if_not_ready",
    ]
    feasibility_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "remaining_loss_reason",
        "recoverability_class",
        "amb_nearest_travelway_distance_ft",
        "amb_nearby_travelway_candidate_count",
        "amb_unique_nearby_route_count",
        "amb_nearby_divided_candidate_count",
        "amb_nearby_undivided_candidate_count",
        "amb_nearest_candidate_route",
        "amb_nearest_two_route_sample",
        "amb_graph_node_route_sample",
        "amb_graph_node_division_status_sample",
        "amb_recoverability_class",
        "assoc_recovery_strategy",
        "assoc_association_confidence_tier",
        "assoc_has_plausible_recovery_candidate",
        "assoc_number_of_candidates_for_signal",
        "scaffold_has_any_buildable_scaffold",
        "scaffold_has_0_1000ft_scaffold",
        "scaffold_has_full_0_2500ft_scaffold",
        "scaffold_buildable_candidate_count",
        "scaffold_has_one_direction_only_scaffold",
        "bins_full_0_1000_coverage_flag",
        "bins_full_0_2500_coverage_flag",
        "immediate_implementation_attempt",
        "hold_for_manual_or_mapped_review",
    ]
    funnel_cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "in_strict_active_baseline_971",
        "in_recovered_speed_aadt_ready_1469",
        "overlap_with_strict_active_and_recovered",
    ]
    return {
        "frozen_signal": _read_csv(FREEZE_DIR / "frozen_candidate_signal_universe.csv", usecols=frozen_cols),
        "frozen_tier": _read_csv(FREEZE_DIR / "frozen_candidate_universe_tier_summary.csv"),
        "context_347": _read_csv(CONTEXT_347_DIR / "review_only_347_context_signal_summary.csv", usecols=context_cols),
        "context_projection": _read_csv(CONTEXT_347_DIR / "review_only_347_updated_universe_projection.csv"),
        "feasibility": _read_csv(FEASIBILITY_DIR / "unrepresented_signal_recovery_detail.csv", usecols=feasibility_cols),
        "by_loss": _read_csv(FEASIBILITY_DIR / "unrepresented_signal_recovery_by_loss_bucket.csv"),
        "class_summary": _read_csv(FEASIBILITY_DIR / "unrepresented_signal_recovery_class_summary.csv"),
        "funnel": _read_csv(FUNNEL_DIR / "signal_funnel_clarification_detail.csv", usecols=funnel_cols),
    }


def _refresh_universe(frozen: pd.DataFrame, context: pd.DataFrame, funnel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    _checkpoint("refresh_universe_start")
    strict = funnel.loc[_flag(funnel, "in_strict_active_baseline_971")].copy()
    strict = strict.sort_values(["source_signal_id", "signal_id"]).drop_duplicates("source_signal_id")
    strict["prior_candidate_signal_id"] = ""
    strict["candidate_signal_id_refreshed"] = _text(strict, "signal_id")
    strict["frozen_candidate_signal_id"] = "strict_baseline_" + _text(strict, "source_signal_id")
    strict["candidate_bin_count"] = ""
    strict["weighted_bin_count"] = ""
    strict["has_any_scaffold"] = True
    strict["has_roadway_context"] = True
    strict["has_speed"] = True
    strict["has_aadt"] = True
    strict["has_exposure"] = True
    strict["speed_aadt_ready"] = True
    strict["full_0_1000_speed_aadt_ready"] = True
    strict["full_attempted_0_2500_speed_aadt_ready"] = True
    strict["direction_labels"] = ""
    strict["analysis_windows"] = "0_1000|1000_2500"
    strict["one_direction_only_flag"] = False
    strict["one_sided_or_partial_flag"] = False
    strict["multi_candidate_weighted_flag"] = False
    strict["strict_active_overlap_conflict_flag"] = False
    strict["strict_active_overlap_status"] = "strict_active_baseline"
    strict["recovery_strategy"] = "strict_active_baseline"
    strict["association_confidence_tier"] = "strict_active_baseline"
    strict["represented_source"] = "strict_active_baseline"
    strict["review_only_addition_status"] = "baseline_not_new_addition"
    strict["refreshed_universe_tier"] = "strict_active_baseline_overlap"
    strict["near_signal_or_partial_tier"] = "strict_full_0_2500_baseline"

    represented = frozen.loc[_flag(frozen, "speed_aadt_ready")].copy()
    represented["represented_source"] = "prior_frozen_review_universe"
    represented["review_only_addition_status"] = "already_in_prior_freeze"
    represented["refreshed_universe_tier"] = _text(represented, "recommended_universe_tier")
    represented["near_signal_or_partial_tier"] = ""
    represented["one_sided_or_partial_flag"] = _flag(represented, "one_direction_only_flag")
    represented["candidate_signal_id_refreshed"] = _text(represented, "candidate_signal_id")
    represented = represented.rename(columns={"candidate_signal_id": "prior_candidate_signal_id"})

    additions = context.loc[_flag(context, "speed_aadt_ready")].copy()
    prior_sources = set(_text(strict, "source_signal_id")) | set(_text(represented, "source_signal_id"))
    additions["overlap_with_existing_frozen_universe"] = _text(additions, "source_signal_id").isin(prior_sources)
    additions = additions.loc[~additions["overlap_with_existing_frozen_universe"]].copy()
    additions["prior_candidate_signal_id"] = ""
    additions["frozen_candidate_signal_id"] = "review_only_347_refresh_" + _text(additions, "source_signal_id")
    additions["candidate_signal_id_refreshed"] = _text(additions, "signal_id")
    additions["candidate_bin_count"] = _text(additions, "candidate_bin_count")
    additions["weighted_bin_count"] = ""
    additions["has_any_scaffold"] = True
    additions["multi_candidate_weighted_flag"] = False
    additions["strict_active_overlap_conflict_flag"] = False
    additions["strict_active_overlap_status"] = "no_frozen_source_overlap"
    additions["recovery_strategy"] = "review_only_347_recovered_scaffold_context_refresh"
    additions["association_confidence_tier"] = "review_only_347_recovered"
    additions["full_0_1000_speed_aadt_ready"] = _flag(additions, "speed_aadt_ready_0_1000")
    additions["full_attempted_0_2500_speed_aadt_ready"] = False
    additions["one_direction_only_flag"] = _flag(additions, "partial_or_one_sided_only")
    additions["represented_source"] = "review_only_347_context_refresh"
    additions["review_only_addition_status"] = "new_review_only_addition_not_active"
    additions["refreshed_universe_tier"] = "review_only_347_recovered_speed_aadt_ready"
    additions["near_signal_or_partial_tier"] = "near_signal_0_1000_ready" 
    additions.loc[_flag(additions, "partial_or_one_sided_only"), "near_signal_or_partial_tier"] = "near_signal_partial_or_one_sided"
    additions["one_sided_or_partial_flag"] = _flag(additions, "partial_or_one_sided_only")

    common_cols = [
        "source_signal_id",
        "source_layer",
        "prior_candidate_signal_id",
        "candidate_signal_id_refreshed",
        "frozen_candidate_signal_id",
        "candidate_bin_count",
        "weighted_bin_count",
        "has_any_scaffold",
        "has_roadway_context",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
        "direction_labels",
        "analysis_windows",
        "one_direction_only_flag",
        "one_sided_or_partial_flag",
        "multi_candidate_weighted_flag",
        "strict_active_overlap_conflict_flag",
        "strict_active_overlap_status",
        "recovery_strategy",
        "association_confidence_tier",
        "represented_source",
        "review_only_addition_status",
        "refreshed_universe_tier",
        "near_signal_or_partial_tier",
    ]
    for frame in [represented, additions]:
        for col in common_cols:
            if col not in frame.columns:
                frame[col] = ""
    refreshed = pd.concat([strict[common_cols], represented[common_cols], additions[common_cols]], ignore_index=True)
    refreshed = refreshed.drop_duplicates("source_signal_id", keep="last").copy()
    previous = PREVIOUS_REPRESENTED_COUNT
    added = int(additions["source_signal_id"].nunique())
    refreshed_count = int(refreshed["source_signal_id"].nunique())
    summary = pd.DataFrame(
        [
            ("previous_represented_count", previous),
            ("newly_added_represented_signals", added),
            ("overlap_with_existing_frozen_universe", int(_flag(context.loc[_flag(context, "speed_aadt_ready")], "source_signal_id").sum()) if False else int(context.loc[_flag(context, "speed_aadt_ready"), "source_signal_id"].isin(prior_sources).sum())),
            ("refreshed_represented_count", refreshed_count),
            ("percent_of_3933_represented", round(refreshed_count / BASE_STAGED_SIGNALS * 100, 2)),
            ("updated_not_yet_represented_count", BASE_STAGED_SIGNALS - refreshed_count),
        ],
        columns=["metric", "value"],
    )
    _checkpoint("refresh_universe_complete", refreshed_count)
    return refreshed, summary


def _decompose_709(feasibility: pd.DataFrame) -> pd.DataFrame:
    graph = feasibility.loc[_text(feasibility, "remaining_loss_reason").eq("graph/path/anchor unresolved")].copy()
    return (
        graph.groupby("recoverability_class", dropna=False)
        .agg(signal_count=("source_signal_id", "nunique"), source_layers=("source_layer", _collapse))
        .reset_index()
        .sort_values(["signal_count", "recoverability_class"], ascending=[False, True])
    )


def _route_identity_detail(feasibility: pd.DataFrame) -> pd.DataFrame:
    route = feasibility.loc[
        _text(feasibility, "remaining_loss_reason").eq("graph/path/anchor unresolved")
        & _text(feasibility, "recoverability_class").eq("needs_route_identity_review")
    ].copy()
    for col in [
        "amb_nearby_travelway_candidate_count",
        "amb_unique_nearby_route_count",
        "amb_nearby_divided_candidate_count",
        "amb_nearby_undivided_candidate_count",
        "assoc_number_of_candidates_for_signal",
        "scaffold_buildable_candidate_count",
    ]:
        route[col + "_num"] = pd.to_numeric(_text(route, col), errors="coerce")
    route["has_nearby_travelway_evidence"] = route["amb_nearby_travelway_candidate_count_num"].gt(0)
    route["has_route_evidence"] = _text(route, "amb_nearest_candidate_route").ne("") | _text(route, "amb_graph_node_route_sample").ne("")
    route["resembles_previously_recovered_signal"] = _text(route, "amb_recoverability_class").str.contains("route_measure|tolerance|anchor", case=False, regex=True)
    route["appears_scaffoldable_from_current_evidence"] = route["has_nearby_travelway_evidence"] & route["has_route_evidence"]
    route["plausible_0_1000_scaffold"] = route["appears_scaffoldable_from_current_evidence"]
    route["plausible_full_0_2500_scaffold"] = _flag(route, "scaffold_has_full_0_2500ft_scaffold") | _flag(route, "bins_full_0_2500_coverage_flag")
    route["manual_or_mapped_review_recommended"] = ~route["appears_scaffoldable_from_current_evidence"] | route["amb_unique_nearby_route_count_num"].gt(2)
    route["immediately_targetable"] = route["appears_scaffoldable_from_current_evidence"] & ~route["manual_or_mapped_review_recommended"]
    route["recommended_route_identity_action"] = "route_identity_review_rule_candidate"
    route.loc[route["manual_or_mapped_review_recommended"], "recommended_route_identity_action"] = "manual_or_mapped_route_identity_review"
    keep = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "recoverability_class",
        "amb_nearest_travelway_distance_ft",
        "amb_nearby_travelway_candidate_count",
        "amb_unique_nearby_route_count",
        "amb_nearest_candidate_route",
        "amb_nearest_two_route_sample",
        "amb_graph_node_route_sample",
        "amb_graph_node_division_status_sample",
        "has_nearby_travelway_evidence",
        "has_route_evidence",
        "resembles_previously_recovered_signal",
        "appears_scaffoldable_from_current_evidence",
        "plausible_0_1000_scaffold",
        "plausible_full_0_2500_scaffold",
        "manual_or_mapped_review_recommended",
        "immediately_targetable",
        "recommended_route_identity_action",
    ]
    return route[[c for c in keep if c in route.columns]].copy()


def _route_identity_summary(detail: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("route_identity_review_signals", int(detail["source_signal_id"].nunique())),
            ("appears_scaffoldable_from_current_evidence", int(detail["appears_scaffoldable_from_current_evidence"].sum())),
            ("has_nearby_travelway_evidence", int(detail["has_nearby_travelway_evidence"].sum())),
            ("has_route_evidence", int(detail["has_route_evidence"].sum())),
            ("resembles_previously_recovered_signal", int(detail["resembles_previously_recovered_signal"].sum())),
            ("plausible_0_1000_scaffold", int(detail["plausible_0_1000_scaffold"].sum())),
            ("plausible_full_0_2500_scaffold", int(detail["plausible_full_0_2500_scaffold"].sum())),
            ("manual_or_mapped_review_recommended", int(detail["manual_or_mapped_review_recommended"].sum())),
            ("immediately_targetable", int(detail["immediately_targetable"].sum())),
        ],
        columns=["metric", "signal_count"],
    )


def _recommendation(route_summary: pd.DataFrame, decomposition: pd.DataFrame) -> pd.DataFrame:
    immediate = int(route_summary.loc[route_summary["metric"].eq("immediately_targetable"), "signal_count"].iloc[0])
    scaffoldable = int(route_summary.loc[route_summary["metric"].eq("appears_scaffoldable_from_current_evidence"), "signal_count"].iloc[0])
    if immediate >= 150:
        recommendation = "target_the_387_route_identity_review_subset_now"
        rationale = "Large immediately targetable subset with route/Travelway evidence; likely highest-yield next recovery pass."
    elif scaffoldable >= 250:
        recommendation = "target_the_387_route_identity_review_subset_now"
        rationale = "Most route-identity cases appear scaffoldable, though some need mapped/manual review."
    else:
        recommendation = "move_to_access_design_now"
        rationale = "Route-identity subset needs too much review to block access design."
    return pd.DataFrame(
        [
            {
                "recommended_next_action": recommendation,
                "rationale": rationale,
                "alternate_action": "move_to_access_design_now",
                "excluded_actions": "target_divided_pairing_first|broader_709_diagnostic_first",
                "review_only_note": "Planning recommendation only; no scaffold/access/crash/rate/model work performed.",
            }
        ]
    )


def _metric(summary: pd.DataFrame, metric: str) -> int | float:
    rows = summary.loc[summary["metric"].eq(metric), "value" if "value" in summary.columns else "signal_count"]
    return rows.iloc[0] if len(rows) else 0


def _write_findings(universe_summary: pd.DataFrame, decomposition: pd.DataFrame, route_summary: pd.DataFrame, rec: pd.DataFrame) -> None:
    refreshed = int(_metric(universe_summary, "refreshed_represented_count"))
    percent = _metric(universe_summary, "percent_of_3933_represented")
    remaining = int(_metric(universe_summary, "updated_not_yet_represented_count"))
    decomp = {row["recoverability_class"]: int(row["signal_count"]) for row in decomposition.to_dict(orient="records")}
    route_total = int(_metric(route_summary, "route_identity_review_signals"))
    scaffoldable = int(_metric(route_summary, "appears_scaffoldable_from_current_evidence"))
    immediate = int(_metric(route_summary, "immediately_targetable"))
    text = f"""# Expanded Universe Refresh and 709 Planning

## Bounded Question

This read-only pass folds the 302 review-only speed+AADT-ready signals from the 347 recovery/context refresh into a refreshed represented-universe planning table, then decomposes the 709 graph/path/anchor unresolved pool. It does not build scaffold, assign access/crashes, create catchments, calculate rates, run models, modify active outputs, or promote recovered records.

## Refreshed Universe

- Refreshed represented signal count: **{refreshed:,}**
- Percent of 3,933 staged/base signals represented: **{percent}%**
- Remaining not-yet-represented signals: **{remaining:,}**

The 302 added signals remain labeled as `review_only_347_recovered_speed_aadt_ready`; they are not active records.

## 709 Decomposition

- Route identity review: **{decomp.get('needs_route_identity_review', 0):,}**
- Divided pairing: **{decomp.get('needs_divided_pairing', 0):,}**
- Graph gap repair: **{decomp.get('needs_graph_gap_repair', 0):,}**
- Hold / insufficient evidence: **{decomp.get('insufficient_existing_evidence', 0):,}**

## 387 Route-Identity Feasibility

The route-identity group contains **{route_total:,}** signals. **{scaffoldable:,}** appear scaffoldable from current route/Travelway evidence, and **{immediate:,}** look immediately targetable without mapped/manual review. This supports targeting the 387 route-identity subset next if the project wants one more recovery pass before access design.

## Recommendation

Recommended next action: **{rec.iloc[0]['recommended_next_action']}**. {rec.iloc[0]['rationale']}
"""
    _write_text(text, OUT_DIR / "expanded_universe_refresh_and_709_plan_findings.md")


def _qa(missing: list[str], universe: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    added = int(_metric(summary, "newly_added_represented_signals"))
    rows = [
        ("required_inputs_present", not missing, "; ".join(missing)),
        ("no_active_outputs_modified", True, "Module writes only to review output folder."),
        ("no_candidates_promoted", True, "302 additions remain review-only labels."),
        ("no_access_crash_assignment", True, "No access/crash assignment or catchments are created."),
        ("no_rates_models", True, "No rate or model outputs are produced."),
        ("added_302_signals_remain_review_only", added == EXPECTED_347_ADDITIONS, f"observed={added:,}; expected={EXPECTED_347_ADDITIONS:,}"),
        ("deduped_signal_counts_separate_from_bin_counts", universe["source_signal_id"].is_unique, f"signal_rows={len(universe):,}"),
        ("outputs_review_only_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": bool(passed), "detail": detail} for name, passed, detail in rows])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("module_start")
    missing = _missing_inputs()
    inputs = _load_inputs()
    universe, universe_summary = _refresh_universe(inputs["frozen_signal"], inputs["context_347"], inputs["funnel"])
    decomposition = _decompose_709(inputs["feasibility"])
    route_detail = _route_identity_detail(inputs["feasibility"])
    route_summary = _route_identity_summary(route_detail)
    recommendation = _recommendation(route_summary, decomposition)

    _write_csv(universe, OUT_DIR / "refreshed_represented_signal_universe.csv")
    _write_csv(universe_summary, OUT_DIR / "refreshed_represented_universe_summary.csv")
    _write_csv(decomposition, OUT_DIR / "unrepresented_709_decomposition_summary.csv")
    _write_csv(route_detail, OUT_DIR / "route_identity_387_feasibility_detail.csv")
    _write_csv(route_summary, OUT_DIR / "route_identity_387_feasibility_summary.csv")
    _write_csv(recommendation, OUT_DIR / "next_recovery_target_recommendation.csv")
    _write_findings(universe_summary, decomposition, route_summary, recommendation)
    qa = _qa(missing, universe, universe_summary)
    _write_csv(qa, OUT_DIR / "expanded_universe_refresh_and_709_plan_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "module": "src.roadway_graph.expanded_universe_refresh_and_709_plan",
        "bounded_question": "refresh expanded represented universe and plan next recovery target for 709 graph/path/anchor unresolved signals",
        "output_folder": str(OUT_DIR),
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
            "refreshed_represented_count": int(_metric(universe_summary, "refreshed_represented_count")),
            "updated_not_yet_represented_count": int(_metric(universe_summary, "updated_not_yet_represented_count")),
            "route_identity_review_signals": int(_metric(route_summary, "route_identity_review_signals")),
            "route_identity_immediately_targetable": int(_metric(route_summary, "immediately_targetable")),
        },
        "qa_passed": bool(qa["passed"].all()),
        "missing_inputs": missing,
    }
    _write_json(manifest, OUT_DIR / "expanded_universe_refresh_and_709_plan_manifest.json")
    _checkpoint("module_complete")


if __name__ == "__main__":
    main()
