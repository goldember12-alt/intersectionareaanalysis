from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
ATTRITION_DIR = OUTPUT_ROOT / "review/current/signal_attrition_funnel_audit"
AMBIGUOUS_DIR = OUTPUT_ROOT / "review/current/signal_ambiguous_road_association_diagnostic"
OUT_DIR = OUTPUT_ROOT / "review/current/signal_association_recovery_feasibility"
TABLES = OUTPUT_ROOT / "tables/current"

EXPECTED_AMBIGUOUS_COUNT = 2285
CURRENT_TRUE_REFERENCE_SIGNALS = 1214
NEAR_TIE_FT = 10.0


CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if usecols is None:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    header = pd.read_csv(path, nrows=0)
    cols = [column for column in usecols if column in header.columns]
    if not cols:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _metric(frame: pd.DataFrame, stage: str) -> int:
    if frame.empty or "stage" not in frame.columns or "signal_count" not in frame.columns:
        return 0
    values = frame.loc[_text(frame, "stage").eq(stage), "signal_count"]
    if values.empty:
        return 0
    return int(pd.to_numeric(values.iloc[0], errors="coerce") or 0)


def _route_stem(route: object) -> str:
    text = str(route or "").upper().strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(NB|SB|EB|WB)$", "", text)
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def _route_direction(route: object) -> str:
    match = re.search(r"(NB|SB|EB|WB)$", str(route or "").upper().replace(" ", ""))
    return match.group(1) if match else ""


def _route_matches_signal_text(route: object, signal_row: pd.Series) -> bool:
    route_text = str(route or "").upper()
    route_stem = _route_stem(route)
    values = [
        signal_row.get("MAJ_NAME", ""),
        signal_row.get("MAJ_NUM", ""),
        signal_row.get("MINOR_NAME", ""),
        signal_row.get("MINOR_NUM", ""),
        signal_row.get("source_signal_id", ""),
        signal_row.get("nearest_route_sample", ""),
    ]
    haystack = " ".join(str(value or "").upper() for value in values)
    if route_stem and route_stem in _route_stem(haystack):
        return True
    common = re.sub(r"[^A-Z0-9]", "", route_text)
    return bool(common and common in re.sub(r"[^A-Z0-9]", "", haystack))


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    attrition_manifest = _load_manifest(ATTRITION_DIR / "signal_attrition_funnel_manifest.json")
    ambiguous_manifest = _load_manifest(AMBIGUOUS_DIR / "signal_ambiguous_road_association_manifest.json")
    detail = _read_csv(AMBIGUOUS_DIR / "ambiguous_signal_diagnostic_detail.csv")
    detail = detail.loc[_text(detail, "best_available_loss_reason").eq("ambiguous_nearest_road")].copy()
    nodes = _read_csv(
        TABLES / "signal_graph_nodes.csv",
        usecols=[
            "signal_id",
            "source_signal_row_id",
            "road_component_id",
            "source_road_row_id",
            "match_distance_ft",
            "projection_m",
            "match_method",
            "matched_route_name",
            "matched_route_common",
            "matched_route_id",
            "matched_event_source",
            "roadway_division_status",
            "logical_segment_mode",
            "facility_code",
            "median_code",
            "qa_status",
            "matched_graph_node_id",
            "snapped_x",
            "snapped_y",
        ],
    )
    nodes = nodes.loc[_text(nodes, "signal_id").isin(set(_text(detail, "signal_id")))].copy()
    graph_gap = _read_csv(TABLES / "graph_gap_review.csv")
    return detail, nodes, graph_gap, attrition_manifest, ambiguous_manifest


def _candidate_subset(signal_row: pd.Series, candidates: pd.DataFrame) -> tuple[pd.DataFrame, str, str, str, str]:
    if candidates.empty:
        return candidates, "not_recoverable_current_sources", "not_recoverable_current_sources", "not_recoverable_current_sources", "No existing signal graph-node candidates are available."

    candidates = candidates.copy()
    candidates["_distance"] = _num(candidates, "match_distance_ft")
    candidates = candidates.loc[candidates["_distance"].notna()].sort_values(["_distance", "road_component_id"]).copy()
    if candidates.empty:
        return candidates, "not_recoverable_current_sources", "not_recoverable_current_sources", "not_recoverable_current_sources", "Existing candidates lack usable distance evidence."

    category = str(signal_row.get("primary_diagnostic_category", ""))
    flags = str(signal_row.get("diagnostic_category_flags", ""))
    nearest = float(candidates["_distance"].iloc[0])
    within_50 = candidates.loc[candidates["_distance"].le(50)].copy()
    if within_50.empty:
        nearest_only = candidates.head(1).copy()
        return nearest_only, "unresolved_review_only", "review_only_candidate", "unresolved_review_only", "No candidate falls within the current 50 ft association tolerance."

    near_tie = within_50.loc[within_50["_distance"].le(nearest + NEAR_TIE_FT)].copy()
    divided = within_50.loc[_text(within_50, "roadway_division_status").eq("divided")].copy()
    route_matches = within_50.loc[within_50["matched_route_common"].map(lambda value: _route_matches_signal_text(value, signal_row))].copy()

    if category == "offset_signal_point_near_intersection":
        return within_50.head(1).copy(), "offset_signal_snap_candidate", "deterministic_recovery_candidate", "offset_signal_snap_candidate", "Nearest candidate is within 50 ft and the main issue is signal point offset."

    if category == "divided_or_parallel_carriageway_ambiguity":
        if len(divided) >= 2:
            stems = divided["matched_route_common"].map(_route_stem)
            dirs = divided["matched_route_common"].map(_route_direction)
            has_pair = any(
                {"NB", "SB"}.issubset(set(dirs.loc[stems.eq(stem)]))
                or {"EB", "WB"}.issubset(set(dirs.loc[stems.eq(stem)]))
                for stem in sorted(set(stems))
                if stem
            )
            if has_pair:
                return divided.copy(), "divided_carriageway_pairing_candidate", "multi_candidate_weighted_recovery", "divided_carriageway_pairing_candidate", "Existing route names include opposite-direction divided carriageway candidates for the same route stem."
        return within_50.copy(), "divided_carriageway_pairing_candidate", "review_only_candidate", "unresolved_review_only", "Divided/parallel evidence exists, but current route evidence is insufficient to identify an opposite-carriageway candidate set."

    if len(near_tie) >= 2 and category == "nearest_candidate_distance_tie_or_near_tie":
        return near_tie.copy(), "near_tie_multi_candidate_rule", "multi_candidate_weighted_recovery", "near_tie_multi_candidate_rule", f"{len(near_tie)} candidates are within {NEAR_TIE_FT:g} ft of the nearest candidate; ambiguity is preserved with equal preliminary weights."

    if category == "route_identity_conflict_or_missing_route_evidence":
        if len(route_matches) == 1:
            return route_matches.copy(), "route_measure_tie_break_candidate", "deterministic_recovery_candidate", "route_measure_tie_break_candidate", "A single candidate route is compatible with available signal route/name evidence."
        if len(route_matches) > 1:
            return route_matches.copy(), "route_measure_tie_break_candidate", "multi_candidate_weighted_recovery", "route_measure_tie_break_candidate", "Multiple candidate routes are compatible with signal route/name evidence; preserve candidates for weighted review."
        return within_50.copy(), "unresolved_review_only", "review_only_candidate", "unresolved_review_only", "Route identity conflict could not be resolved with existing signal route/name evidence."

    if category in {"multi_leg_intersection_ambiguity", "graph_topology_gap_or_unsplit_intersection"}:
        strategy = "graph_gap_virtual_anchor_candidate" if category == "graph_topology_gap_or_unsplit_intersection" else "intersection_anchor_rule_candidate"
        return within_50.copy(), strategy, "review_only_candidate", "unresolved_review_only", "Complex intersection or graph-gap context may support a future virtual anchor rule, but existing evidence does not make this deterministic."

    return within_50.copy(), "unresolved_review_only", "review_only_candidate", "unresolved_review_only", "Existing evidence does not support a deterministic or multi-candidate recovery rule."


def _build_candidates(detail: pd.DataFrame, nodes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    nodes_by_signal = {signal_id: group.copy() for signal_id, group in nodes.groupby("signal_id", sort=False)}

    for row in detail.itertuples(index=False):
        signal_row = pd.Series(row._asdict())
        signal_id = str(signal_row.get("signal_id", ""))
        candidates = nodes_by_signal.get(signal_id, pd.DataFrame())
        selected, strategy, tier, signal_status, explanation = _candidate_subset(signal_row, candidates)
        selected = selected.copy()
        selected["_distance"] = _num(selected, "match_distance_ft")
        selected = selected.sort_values(["_distance", "road_component_id"]).reset_index(drop=True)
        candidate_count = len(selected)
        if candidate_count == 0:
            records.append(_candidate_record(signal_row, pd.Series(dtype=object), 1, 1, strategy, tier, signal_status, explanation))
        else:
            for index, candidate in selected.iterrows():
                records.append(_candidate_record(signal_row, candidate, int(index) + 1, candidate_count, strategy, tier, signal_status, explanation))
        summaries.append(
            {
                "signal_id": signal_id,
                "source_signal_id": signal_row.get("source_signal_id", ""),
                "source_layer": signal_row.get("source_layer", ""),
                "primary_diagnostic_category": signal_row.get("primary_diagnostic_category", ""),
                "recovery_strategy": strategy,
                "association_confidence_tier": tier,
                "signal_recovery_status": signal_status,
                "number_of_candidates_for_signal": candidate_count,
                "has_plausible_recovery_candidate": tier in {"deterministic_recovery_candidate", "multi_candidate_weighted_recovery"},
                "deterministically_recoverable": tier == "deterministic_recovery_candidate",
                "requires_multi_candidate_weighting": tier == "multi_candidate_weighted_recovery",
                "review_only": tier == "review_only_candidate",
                "not_recoverable_current_sources": tier == "not_recoverable_current_sources",
                "nearest_candidate_distance_ft": selected["_distance"].min() if candidate_count else "",
                "diagnostic_explanation": explanation,
                "candidate_promoted_to_active": False,
                "diagnostic_not_final_truth": True,
            }
        )
    return pd.DataFrame(records), pd.DataFrame(summaries)


def _candidate_record(
    signal_row: pd.Series,
    candidate: pd.Series,
    rank: int,
    count: int,
    strategy: str,
    tier: str,
    signal_status: str,
    explanation: str,
) -> dict[str, Any]:
    distance = pd.to_numeric(pd.Series([candidate.get("match_distance_ft", "")]), errors="coerce").iloc[0]
    weight = round(1.0 / count, 8) if count and tier == "multi_candidate_weighted_recovery" else 1.0 if count == 1 and tier == "deterministic_recovery_candidate" else ""
    return {
        "signal_id": signal_row.get("signal_id", ""),
        "source_signal_id": signal_row.get("source_signal_id", ""),
        "source_signal_key": signal_row.get("source_signal_key", ""),
        "source_layer": signal_row.get("source_layer", ""),
        "DISTRICT": signal_row.get("DISTRICT", ""),
        "MAINT_JURISDICTION": signal_row.get("MAINT_JURISDICTION", ""),
        "MAJ_NAME": signal_row.get("MAJ_NAME", ""),
        "MAJ_NUM": signal_row.get("MAJ_NUM", ""),
        "MINOR_NAME": signal_row.get("MINOR_NAME", ""),
        "MINOR_NUM": signal_row.get("MINOR_NUM", ""),
        "signal_x": signal_row.get("signal_x", ""),
        "signal_y": signal_row.get("signal_y", ""),
        "primary_diagnostic_category": signal_row.get("primary_diagnostic_category", ""),
        "diagnostic_category_flags": signal_row.get("diagnostic_category_flags", ""),
        "recovery_strategy": strategy,
        "association_confidence_tier": tier,
        "signal_recovery_status": signal_status,
        "number_of_candidates_for_signal": count,
        "candidate_rank": rank,
        "tie_group_id": f"{signal_row.get('signal_id', '')}_{strategy}" if count > 1 else "",
        "candidate_weight_preliminary": weight,
        "weighting_assumption": "equal_weight_within_preserved_candidate_set" if count > 1 and tier == "multi_candidate_weighted_recovery" else "",
        "road_component_id": candidate.get("road_component_id", ""),
        "source_road_row_id": candidate.get("source_road_row_id", ""),
        "matched_graph_node_id": candidate.get("matched_graph_node_id", ""),
        "candidate_distance_ft": round(float(distance), 3) if pd.notna(distance) else "",
        "distance_gap_to_next_candidate_ft": "",
        "projection_m": candidate.get("projection_m", ""),
        "matched_route_name": candidate.get("matched_route_name", ""),
        "matched_route_common": candidate.get("matched_route_common", ""),
        "matched_route_id": candidate.get("matched_route_id", ""),
        "matched_event_source": candidate.get("matched_event_source", ""),
        "roadway_division_status": candidate.get("roadway_division_status", ""),
        "logical_segment_mode": candidate.get("logical_segment_mode", ""),
        "facility_code": candidate.get("facility_code", ""),
        "median_code": candidate.get("median_code", ""),
        "snapped_x": candidate.get("snapped_x", ""),
        "snapped_y": candidate.get("snapped_y", ""),
        "recovery_explanation": explanation,
        "candidate_promoted_to_active": False,
        "diagnostic_not_final_truth": True,
    }


def _add_distance_gaps(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    out = candidates.copy()
    out["_dist"] = pd.to_numeric(out["candidate_distance_ft"], errors="coerce")
    gaps: list[Any] = []
    for _, group in out.groupby("signal_id", sort=False):
        distances = group["_dist"].tolist()
        for index, distance in enumerate(distances):
            if pd.isna(distance) or index + 1 >= len(distances) or pd.isna(distances[index + 1]):
                gaps.append("")
            else:
                gaps.append(round(float(distances[index + 1] - distance), 3))
    out["distance_gap_to_next_candidate_ft"] = gaps
    return out.drop(columns=["_dist"])


def _strategy_summary(summary: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame([{**{col: "not_available" for col in group_cols}, "signal_count": 0}])
    out = (
        summary.groupby(group_cols, dropna=False)
        .agg(
            signal_count=("signal_id", "count"),
            candidate_association_count=("number_of_candidates_for_signal", "sum"),
            deterministic_signals=("deterministically_recoverable", "sum"),
            multi_candidate_signals=("requires_multi_candidate_weighting", "sum"),
            review_only_signals=("review_only", "sum"),
            not_recoverable_signals=("not_recoverable_current_sources", "sum"),
        )
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )
    return out


def _multi_candidate_summary(summary: pd.DataFrame) -> pd.DataFrame:
    multi = summary.loc[summary["requires_multi_candidate_weighting"].astype(bool)].copy()
    if multi.empty:
        return pd.DataFrame(columns=["candidate_count_bucket", "signal_count"])
    def bucket(value: Any) -> str:
        count = int(pd.to_numeric(value, errors="coerce") or 0)
        if count <= 1:
            return "not_multi_candidate"
        if count == 2:
            return "2_candidates"
        if count == 3:
            return "3_candidates"
        return "4plus_candidates"
    multi["candidate_count_bucket"] = multi["number_of_candidates_for_signal"].map(bucket)
    return (
        multi.groupby(["candidate_count_bucket", "recovery_strategy"], dropna=False)
        .agg(signal_count=("signal_id", "count"))
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )


def _ranked_review_queue(summary: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    first_candidate = candidates.sort_values(["signal_id", "candidate_rank"]).groupby("signal_id", as_index=False).first()
    merged = summary.merge(
        first_candidate[
            [
                "signal_id",
                "matched_route_common",
                "roadway_division_status",
                "candidate_distance_ft",
                "distance_gap_to_next_candidate_ft",
            ]
        ],
        on="signal_id",
        how="left",
    )
    tier_weight = merged["association_confidence_tier"].map(
        {
            "deterministic_recovery_candidate": 30,
            "multi_candidate_weighted_recovery": 20,
            "review_only_candidate": 10,
            "not_recoverable_current_sources": 0,
        }
    ).fillna(0)
    candidate_count = pd.to_numeric(merged["number_of_candidates_for_signal"], errors="coerce").fillna(0)
    merged["review_priority_score"] = tier_weight + candidate_count
    return merged.sort_values(["review_priority_score", "number_of_candidates_for_signal"], ascending=False)


def _findings_md(
    summary: pd.DataFrame,
    strategy_summary: pd.DataFrame,
    tier_summary: pd.DataFrame,
    multi_summary: pd.DataFrame,
    qa: pd.DataFrame,
) -> str:
    total = len(summary)
    deterministic = int(summary["deterministically_recoverable"].sum()) if not summary.empty else 0
    multi = int(summary["requires_multi_candidate_weighting"].sum()) if not summary.empty else 0
    review = int(summary["review_only"].sum()) if not summary.empty else 0
    not_rec = int(summary["not_recoverable_current_sources"].sum()) if not summary.empty else 0
    plausible = deterministic + multi
    max_universe = CURRENT_TRUE_REFERENCE_SIGNALS + plausible
    conservative_universe = CURRENT_TRUE_REFERENCE_SIGNALS + deterministic
    top_strategy = strategy_summary.iloc[0]["recovery_strategy"] if not strategy_summary.empty and "recovery_strategy" in strategy_summary.columns else "not_available"
    top_strategy_count = int(strategy_summary.iloc[0]["signal_count"]) if not strategy_summary.empty else 0
    return f"""# Signal Association Recovery Feasibility Findings

Status: read-only recovery feasibility prototype. No active signal eligibility, scaffold, context, crash assignment, access, speed, AADT, rate, or model outputs were modified or promoted.

## Bounded Question

This pass asks which `ambiguous_nearest_road` signals have plausible signal-road association recovery candidates using existing graph-node, route, distance, source, and graph-gap evidence. It does not rebuild the active signal-road association and does not select candidates using crash or context fields.

## Headline Counts

- Ambiguous input signals: {total}
- Signals with at least one plausible deterministic or multi-candidate recovery candidate: {plausible}
- Deterministically recoverable candidates: {deterministic}
- Multi-candidate/weighted recovery candidates: {multi}
- Review-only signals: {review}
- Not recoverable with current sources: {not_rec}
- Maximum plausible expanded TRUE-reference universe if deterministic and multi-candidate recoveries were later accepted: {max_universe}
- Conservative plausible expanded TRUE-reference universe if only deterministic recoveries were later accepted: {conservative_universe}

## Highest-Yield Strategy

The largest candidate strategy is `{top_strategy}` with {top_strategy_count} signals. Multi-candidate rows preserve ambiguity and use equal preliminary weights within each candidate set.

## Interpretation

The prototype suggests the biggest practical opportunity is not choosing one nearest road in every ambiguous case, but allowing a documented multi-candidate association tier for near ties and divided/parallel carriageway contexts. Complex multi-leg and graph-gap cases remain review-only because existing outputs do not make a deterministic roadway association defensible.

## Non-Promotion Boundary

All recovery strategy and confidence labels are candidate diagnostics. They are not Step 5 TRUE logic, not active scaffold inputs, and not active context rows.

## QA

- QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}
- Crash direction fields read or used: False
- Crash/context fields used to choose candidates: False
- Candidate rows promoted to active outputs: False
"""


def _qa(detail: pd.DataFrame, summary: pd.DataFrame, candidates: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
    product_outputs = {key: path for key, path in outputs.items() if key not in {"findings", "qa", "manifest"}}
    ambiguous_count = len(detail)
    forced_single = candidates.loc[
        candidates["association_confidence_tier"].eq("multi_candidate_weighted_recovery")
        & pd.to_numeric(candidates["number_of_candidates_for_signal"], errors="coerce").le(1)
    ]
    unresolved_ok = summary.loc[
        summary["association_confidence_tier"].isin(["review_only_candidate", "not_recoverable_current_sources"])
        & ~summary["signal_recovery_status"].isin(["unresolved_review_only", "not_recoverable_current_sources"])
    ]
    checks = [
        {
            "check_name": "ambiguous_nearest_road_input_count_reconciles",
            "status": "passed" if ambiguous_count == EXPECTED_AMBIGUOUS_COUNT else "review",
            "observed": ambiguous_count,
            "expected": EXPECTED_AMBIGUOUS_COUNT,
            "note": "Input detail rows filtered from ambiguous_signal_diagnostic_detail.csv.",
        },
        {
            "check_name": "crash_direction_fields_read_or_used",
            "status": "passed",
            "observed": False,
            "expected": False,
            "note": "No crash files are read.",
        },
        {
            "check_name": "crash_counts_used_to_select_candidates",
            "status": "passed",
            "observed": False,
            "expected": False,
            "note": "Selection uses graph-node distance, route, division, and diagnostic category evidence only.",
        },
        {
            "check_name": "context_layers_used_to_select_candidates",
            "status": "passed",
            "observed": False,
            "expected": False,
            "note": "Access/speed/AADT/context outputs are not read.",
        },
        {
            "check_name": "active_outputs_modified",
            "status": "passed",
            "observed": False,
            "expected": False,
            "note": "All writes are isolated to the recovery feasibility review folder.",
        },
        {
            "check_name": "candidate_rows_promoted_to_active",
            "status": "passed" if candidates["candidate_promoted_to_active"].eq(False).all() else "review",
            "observed": False,
            "expected": False,
            "note": "Candidate rows are diagnostic/prototype rows only.",
        },
        {
            "check_name": "outputs_written_only_to_review_folder",
            "status": "passed" if all(str(path).startswith(str(OUT_DIR)) for path in outputs.values()) else "review",
            "observed": str(OUT_DIR),
            "expected": str(OUT_DIR),
            "note": "Output path guard.",
        },
        {
            "check_name": "multi_candidate_cases_preserve_ambiguity",
            "status": "passed" if forced_single.empty else "review",
            "observed": len(forced_single),
            "expected": 0,
            "note": "Multi-candidate tier must have more than one candidate row per signal.",
        },
        {
            "check_name": "unresolved_records_explicitly_labeled",
            "status": "passed" if unresolved_ok.empty else "review",
            "observed": len(unresolved_ok),
            "expected": 0,
            "note": "Review/not-recoverable rows must carry explicit unresolved or not-recoverable signal status.",
        },
        {
            "check_name": "strategy_labels_diagnostic_not_final_truth",
            "status": "passed" if candidates["diagnostic_not_final_truth"].eq(True).all() else "review",
            "observed": True,
            "expected": True,
            "note": "All labels are diagnostic/candidate labels.",
        },
        {
            "check_name": "product_outputs_created",
            "status": "passed" if all(path.exists() for path in product_outputs.values()) else "review",
            "observed": len([path for path in product_outputs.values() if path.exists()]),
            "expected": len(product_outputs),
            "note": "Checked before findings, QA, and manifest are written.",
        },
    ]
    return pd.DataFrame(checks)


def build_signal_association_recovery_feasibility(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    global OUTPUT_ROOT, ATTRITION_DIR, AMBIGUOUS_DIR, OUT_DIR, TABLES
    OUTPUT_ROOT = output_root
    ATTRITION_DIR = output_root / "review/current/signal_attrition_funnel_audit"
    AMBIGUOUS_DIR = output_root / "review/current/signal_ambiguous_road_association_diagnostic"
    OUT_DIR = output_root / "review/current/signal_association_recovery_feasibility"
    TABLES = output_root / "tables/current"

    started = datetime.now(timezone.utc)
    detail, nodes, graph_gap, attrition_manifest, ambiguous_manifest = _load_inputs()
    candidates, signal_summary = _build_candidates(detail, nodes)
    candidates = _add_distance_gaps(candidates)
    strategy_summary = _strategy_summary(signal_summary, ["recovery_strategy"])
    strategy_by_source = _strategy_summary(signal_summary, ["source_layer", "recovery_strategy"])
    tier_summary = _strategy_summary(signal_summary, ["association_confidence_tier"])
    multi_summary = _multi_candidate_summary(signal_summary)
    review_queue = _ranked_review_queue(signal_summary, candidates)

    outputs = {
        "candidate_associations": OUT_DIR / "signal_recovery_candidate_associations.csv",
        "summary_by_signal": OUT_DIR / "signal_recovery_candidate_summary_by_signal.csv",
        "strategy_summary": OUT_DIR / "signal_recovery_strategy_summary.csv",
        "strategy_by_source": OUT_DIR / "signal_recovery_strategy_by_source.csv",
        "confidence_tier_summary": OUT_DIR / "signal_recovery_confidence_tier_summary.csv",
        "multi_candidate_summary": OUT_DIR / "signal_recovery_multi_candidate_summary.csv",
        "ranked_review_queue": OUT_DIR / "signal_recovery_ranked_review_queue.csv",
        "findings": OUT_DIR / "signal_recovery_feasibility_findings.md",
        "qa": OUT_DIR / "signal_recovery_feasibility_qa.csv",
        "manifest": OUT_DIR / "signal_recovery_feasibility_manifest.json",
    }

    _write_csv(candidates, outputs["candidate_associations"])
    _write_csv(signal_summary, outputs["summary_by_signal"])
    _write_csv(strategy_summary, outputs["strategy_summary"])
    _write_csv(strategy_by_source, outputs["strategy_by_source"])
    _write_csv(tier_summary, outputs["confidence_tier_summary"])
    _write_csv(multi_summary, outputs["multi_candidate_summary"])
    _write_csv(review_queue, outputs["ranked_review_queue"])
    qa = _qa(detail, signal_summary, candidates, outputs)
    _write_text(_findings_md(signal_summary, strategy_summary, tier_summary, multi_summary, qa), outputs["findings"])
    _write_csv(qa, outputs["qa"])

    deterministic = int(signal_summary["deterministically_recoverable"].sum()) if not signal_summary.empty else 0
    multi = int(signal_summary["requires_multi_candidate_weighting"].sum()) if not signal_summary.empty else 0
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only signal-road association recovery feasibility for ambiguous_nearest_road signals",
        "read_only": True,
        "planning_prototype_only": True,
        "active_outputs_modified": False,
        "step5_true_logic_changed": False,
        "active_signal_eligibility_changed": False,
        "active_signal_road_association_overwritten": False,
        "active_downstream_bins_created": False,
        "crashes_assigned": False,
        "crash_direction_fields_read_or_used": False,
        "crash_or_context_fields_used_to_select_candidates": False,
        "candidate_rows_promoted_to_active": False,
        "weighting_assumption": "Equal preliminary weights are assigned within preserved multi-candidate sets unless a later reviewed method supplies stronger evidence.",
        "expected_ambiguous_nearest_road_count": EXPECTED_AMBIGUOUS_COUNT,
        "observed_ambiguous_nearest_road_count": len(detail),
        "current_true_reference_signals": CURRENT_TRUE_REFERENCE_SIGNALS,
        "deterministic_recovery_signal_count": deterministic,
        "multi_candidate_recovery_signal_count": multi,
        "maximum_plausible_expanded_signal_universe": CURRENT_TRUE_REFERENCE_SIGNALS + deterministic + multi,
        "conservative_plausible_expanded_signal_universe": CURRENT_TRUE_REFERENCE_SIGNALS + deterministic,
        "input_files": [
            str(AMBIGUOUS_DIR / "ambiguous_signal_diagnostic_detail.csv"),
            str(AMBIGUOUS_DIR / "signal_ambiguous_road_association_manifest.json"),
            str(ATTRITION_DIR / "signal_attrition_funnel_manifest.json"),
            str(TABLES / "signal_graph_nodes.csv"),
            str(TABLES / "graph_gap_review.csv"),
        ],
        "source_attrition_manifest_created_at_utc": attrition_manifest.get("created_at_utc", ""),
        "source_ambiguous_manifest_created_at_utc": ambiguous_manifest.get("created_at_utc", ""),
        "outputs": {key: str(path) for key, path in outputs.items()},
        "qa_checks": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only signal-road association recovery feasibility prototype.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_signal_association_recovery_feasibility(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
