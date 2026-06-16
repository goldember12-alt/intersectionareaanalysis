from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
RECOVERY_DIR = OUTPUT_ROOT / "review/current/signal_association_recovery_feasibility"
ATTRITION_DIR = OUTPUT_ROOT / "review/current/signal_attrition_funnel_audit"
OUT_DIR = OUTPUT_ROOT / "review/current/signal_recovery_scaffold_feasibility"
TABLES = OUTPUT_ROOT / "tables/current"
ANALYSIS = OUTPUT_ROOT / "analysis/current"

EXPECTED_PLAUSIBLE_RECOVERY_SIGNALS = 1590
CURRENT_TRUE_REFERENCE_SIGNALS = 1214
STRICT_ACTIVE_CONTEXT_SIGNALS = 971

VALID_FAR_ANCHOR_TYPES = {"signal", "road_intersection", "road_endpoint"}


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
    vals = frame.loc[_text(frame, "stage").eq(stage), "signal_count"]
    if vals.empty:
        return 0
    return int(pd.to_numeric(vals.iloc[0], errors="coerce") or 0)


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    manifest = _load_manifest(RECOVERY_DIR / "signal_recovery_feasibility_manifest.json")
    candidates = _read_csv(RECOVERY_DIR / "signal_recovery_candidate_associations.csv")
    signal_summary = _read_csv(RECOVERY_DIR / "signal_recovery_candidate_summary_by_signal.csv")
    adjacent = _read_csv(
        TABLES / "signal_adjacent_edges.csv",
        usecols=[
            "signal_id",
            "signal_graph_node_id",
            "graph_edge_id",
            "adjacent_node_id",
            "adjacent_node_type",
            "adjacent_side_label",
            "route_name",
            "route_common",
            "route_id",
            "event_source",
            "road_component_id",
            "roadway_division_status",
            "logical_segment_mode",
            "length_ft",
            "geometry_status",
            "qa_status",
            "true_vehicle_direction_inferred",
        ],
    )
    active_context = _read_csv(
        ANALYSIS / "directional_bin_context_table_active/reference_signal_context_summary_active.csv",
        usecols=["reference_signal_id", "directional_bin_count"],
    )
    return candidates, signal_summary, adjacent, active_context, manifest


def _edge_summary(adjacent: pd.DataFrame) -> pd.DataFrame:
    if adjacent.empty:
        return pd.DataFrame()
    adjacent = adjacent.copy()
    adjacent["_length"] = _num(adjacent, "length_ft")
    grouped = (
        adjacent.groupby(["signal_id", "road_component_id"], dropna=False)
        .agg(
            adjacent_graph_edge_count=("graph_edge_id", "nunique"),
            candidate_max_edge_length_ft=("_length", "max"),
            candidate_total_edge_length_ft=("_length", "sum"),
            candidate_side_count=("adjacent_side_label", lambda values: int(values.astype(str).loc[values.astype(str).ne("")].nunique())),
            adjacent_side_labels=("adjacent_side_label", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
            far_anchor_type_candidate=("adjacent_node_type", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
            far_anchor_id_sample=("adjacent_node_id", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")]))[:5])),
            graph_edge_id_sample=("graph_edge_id", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")]))[:5])),
            edge_route_sample=("route_common", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")]))[:5])),
            edge_geometry_status_sample=("geometry_status", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
            edge_qa_status_sample=("qa_status", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
        )
        .reset_index()
    )
    grouped["candidate_max_edge_length_ft"] = pd.to_numeric(grouped["candidate_max_edge_length_ft"], errors="coerce").round(3)
    grouped["candidate_total_edge_length_ft"] = pd.to_numeric(grouped["candidate_total_edge_length_ft"], errors="coerce").round(3)
    return grouped


def _defensible_anchor(anchor_types: str) -> bool:
    values = {value.strip() for value in str(anchor_types or "").split("|") if value.strip()}
    return bool(values & VALID_FAR_ANCHOR_TYPES)


def _candidate_label(row: pd.Series) -> tuple[str, str, str, bool, bool, bool, bool, str]:
    tier = str(row.get("association_confidence_tier", ""))
    if tier in {"review_only_candidate", "not_recoverable_current_sources"}:
        return "review_only_not_tested", "review_only", "review_only_not_tested", False, False, False, False, "Review-only or not-recoverable recovery tier was not tested for active-style scaffold feasibility."

    if not str(row.get("road_component_id", "")):
        return "blocked_candidate_geometry_missing", "blocked", "geometry_missing", False, False, False, False, "Candidate road component identifier is missing."

    edge_count_raw = pd.to_numeric(row.get("adjacent_graph_edge_count", 0), errors="coerce")
    edge_count = int(edge_count_raw) if pd.notna(edge_count_raw) else 0
    max_len = pd.to_numeric(row.get("candidate_max_edge_length_ft", ""), errors="coerce")
    anchor_ok = _defensible_anchor(str(row.get("far_anchor_type_candidate", "")))
    if edge_count == 0 or pd.isna(max_len):
        return "blocked_no_graph_path", "blocked", "no graph path", False, False, False, False, "No existing signal-adjacent graph edge matched this candidate association."
    if not anchor_ok:
        return "blocked_no_defensible_anchor", "blocked", "no defensible far anchor", False, False, False, False, "Existing graph edge lacks a defensible far-anchor type."

    graph_gap_like = str(row.get("recovery_strategy", "")) == "graph_gap_virtual_anchor_candidate"
    if graph_gap_like:
        return "blocked_graph_gap", "blocked", "graph gap", False, False, False, False, "Graph-gap virtual anchor candidates remain review-only until mapped review defines a defensible anchor rule."

    direction_count_raw = pd.to_numeric(row.get("candidate_side_count", 0), errors="coerce")
    direction_count = int(direction_count_raw) if pd.notna(direction_count_raw) else 0
    both_directions = direction_count >= 2 or edge_count >= 2
    one_direction = not both_directions
    has_1000 = float(max_len) >= 1000
    has_2500 = float(max_len) >= 2500
    any_buildable = float(max_len) > 0

    if tier == "multi_candidate_weighted_recovery" and any_buildable:
        return "buildable_multi_candidate_preserved", "buildable", "multi-candidate ambiguity preserved", any_buildable, has_1000, has_2500, one_direction, "Candidate is buildable but remains one of multiple preserved signal-road candidates."
    if has_2500:
        return "buildable_full_0_2500", "buildable", "", True, True, True, one_direction, "Existing graph edge length supports a full 0-2,500 ft candidate path."
    if has_1000:
        return "buildable_0_1000_only", "buildable", "", True, True, False, one_direction, "Existing graph edge length supports at least 0-1,000 ft but not full 0-2,500 ft coverage."
    if float(max_len) > 0:
        return "buildable_partial_under_1000", "buildable", "", True, False, False, one_direction, "Existing graph edge is buildable but shorter than 1,000 ft."
    return "insufficient_existing_evidence", "blocked", "insufficient existing evidence", False, False, False, False, "Existing outputs do not support a scaffold feasibility label."


def _build_candidate_detail(candidates: pd.DataFrame, adjacent: pd.DataFrame, active_context: pd.DataFrame) -> pd.DataFrame:
    edge = _edge_summary(adjacent)
    out = candidates.merge(edge, on=["signal_id", "road_component_id"], how="left")
    active_signals = set(_text(active_context, "reference_signal_id"))
    out["overlaps_existing_strict_active_signal_scaffold"] = _text(out, "signal_id").isin(active_signals)
    labels = out.apply(_candidate_label, axis=1, result_type="expand")
    labels.columns = [
        "candidate_feasibility_label",
        "candidate_feasibility_status",
        "failure_reason",
        "supports_any_buildable_scaffold",
        "supports_0_1000ft_path",
        "supports_full_0_2500ft_path",
        "one_direction_only_scaffold",
        "scaffold_feasibility_explanation",
    ]
    out = pd.concat([out, labels], axis=1)
    out["supports_1000_2500ft_path"] = out["supports_full_0_2500ft_path"]
    out["supports_both_signal_relative_directions"] = ~out["one_direction_only_scaffold"] & out["supports_any_buildable_scaffold"]
    out["buildable_distance_range_ft"] = out["candidate_max_edge_length_ft"].fillna("")
    out["buildable_direction_status"] = "not_buildable"
    out.loc[out["supports_both_signal_relative_directions"].eq(True), "buildable_direction_status"] = "both_directions_candidate"
    out.loc[out["one_direction_only_scaffold"].eq(True), "buildable_direction_status"] = "one_direction_only_candidate"
    out.loc[out["association_confidence_tier"].eq("multi_candidate_weighted_recovery") & out["supports_any_buildable_scaffold"].eq(True), "buildable_direction_status"] = out["buildable_direction_status"] + "_multi_candidate_preserved"
    out["candidate_promoted_to_active"] = False
    out["diagnostic_not_final_truth"] = True
    return out


def _signal_tier(group: pd.DataFrame) -> str:
    if bool(group["overlaps_existing_strict_active_signal_scaffold"].any()):
        return "strict_existing_active_signal"
    if bool(group["supports_any_buildable_scaffold"].any()):
        if bool(group["association_confidence_tier"].eq("multi_candidate_weighted_recovery").any()):
            return "expanded_multi_candidate_scaffold_candidate"
        if bool(group["association_confidence_tier"].eq("deterministic_recovery_candidate").any()):
            return "expanded_deterministic_scaffold_candidate"
        return "expanded_partial_scaffold_candidate"
    if bool(group["association_confidence_tier"].eq("review_only_candidate").any()):
        return "review_only_scaffold_candidate"
    return "not_buildable_current_graph"


def _signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal_id, group in detail.groupby("signal_id", sort=False):
        first = group.iloc[0]
        rows.append(
            {
                "signal_id": signal_id,
                "source_signal_id": first.get("source_signal_id", ""),
                "source_layer": first.get("source_layer", ""),
                "primary_recovery_strategy": first.get("recovery_strategy", ""),
                "primary_confidence_tier": first.get("association_confidence_tier", ""),
                "candidate_association_count": len(group),
                "buildable_candidate_count": int(group["supports_any_buildable_scaffold"].sum()),
                "has_any_buildable_scaffold": bool(group["supports_any_buildable_scaffold"].any()),
                "has_0_1000ft_scaffold": bool(group["supports_0_1000ft_path"].any()),
                "has_1000_2500ft_scaffold": bool(group["supports_1000_2500ft_path"].any()),
                "has_full_0_2500ft_scaffold": bool(group["supports_full_0_2500ft_path"].any()),
                "has_one_direction_only_scaffold": bool(group["one_direction_only_scaffold"].any()),
                "requires_multi_candidate_preservation": bool(group["association_confidence_tier"].eq("multi_candidate_weighted_recovery").any()),
                "overlaps_existing_strict_active_signal_scaffold": bool(group["overlaps_existing_strict_active_signal_scaffold"].any()),
                "signal_scaffold_tier": _signal_tier(group),
                "dominant_failure_reason": _dominant_failure(group),
                "candidate_promoted_to_active": False,
                "diagnostic_not_final_truth": True,
            }
        )
    return pd.DataFrame(rows)


def _dominant_failure(group: pd.DataFrame) -> str:
    failures = _text(group, "failure_reason")
    failures = failures.loc[failures.ne("")]
    if failures.empty:
        return ""
    return str(failures.value_counts().index[0])


def _count_bool(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].astype(bool).sum())


def _summary_table(signal_summary: pd.DataFrame, attrition_summary: pd.DataFrame) -> pd.DataFrame:
    strict_active = _metric(attrition_summary, "TRUE_signals_represented_in_active_0_2500ft_context_table") or STRICT_ACTIVE_CONTEXT_SIGNALS
    true_count = _metric(attrition_summary, "TRUE_reference_signals") or CURRENT_TRUE_REFERENCE_SIGNALS
    any_buildable = _count_bool(signal_summary, "has_any_buildable_scaffold")
    full = _count_bool(signal_summary, "has_full_0_2500ft_scaffold")
    thousand = _count_bool(signal_summary, "has_0_1000ft_scaffold")
    one_dir = _count_bool(signal_summary, "has_one_direction_only_scaffold")
    multi = _count_bool(signal_summary, "requires_multi_candidate_preservation")
    deterministic_buildable = int(
        signal_summary["signal_scaffold_tier"].eq("expanded_deterministic_scaffold_candidate").sum()
    )
    max_universe = strict_active + any_buildable
    conservative_universe = strict_active + deterministic_buildable
    expanded_vs_true = true_count + any_buildable
    return pd.DataFrame(
        [
            {"metric": "existing_strict_active_context_signals", "value": strict_active},
            {"metric": "current_step5_true_reference_signals", "value": true_count},
            {"metric": "recovery_candidate_signals_tested", "value": len(signal_summary)},
            {"metric": "candidate_signals_with_any_buildable_scaffold", "value": any_buildable},
            {"metric": "candidate_signals_with_full_0_2500ft_scaffold", "value": full},
            {"metric": "candidate_signals_with_0_1000ft_scaffold", "value": thousand},
            {"metric": "candidate_signals_with_one_direction_only_scaffold", "value": one_dir},
            {"metric": "candidate_signals_requiring_multi_candidate_preservation", "value": multi},
            {"metric": "candidate_signals_blocked_or_review_only", "value": len(signal_summary) - any_buildable},
            {"metric": "maximum_possible_expanded_scaffold_signal_universe_vs_strict_active", "value": max_universe},
            {"metric": "conservative_deterministic_expanded_scaffold_signal_universe_vs_strict_active", "value": conservative_universe},
            {"metric": "expanded_scaffold_universe_if_added_to_current_true_reference_count", "value": expanded_vs_true},
        ]
    )


def _group_summary(signal_summary: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if signal_summary.empty:
        return pd.DataFrame([{**{col: "not_available" for col in group_cols}, "signal_count": 0}])
    return (
        signal_summary.groupby(group_cols, dropna=False)
        .agg(
            signal_count=("signal_id", "count"),
            any_buildable_scaffold=("has_any_buildable_scaffold", "sum"),
            full_0_2500_scaffold=("has_full_0_2500ft_scaffold", "sum"),
            scaffold_0_1000=("has_0_1000ft_scaffold", "sum"),
            one_direction_only=("has_one_direction_only_scaffold", "sum"),
            multi_candidate_preserved=("requires_multi_candidate_preservation", "sum"),
        )
        .reset_index()
        .sort_values("any_buildable_scaffold", ascending=False)
    )


def _failure_reasons(candidate_detail: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    candidate_fail = (
        candidate_detail.loc[~candidate_detail["supports_any_buildable_scaffold"].astype(bool)]
        .groupby(["failure_reason", "candidate_feasibility_label"], dropna=False)
        .agg(candidate_count=("signal_id", "count"), unique_signal_count=("signal_id", "nunique"))
        .reset_index()
        .sort_values("candidate_count", ascending=False)
    )
    signal_fail = (
        signal_summary.loc[~signal_summary["has_any_buildable_scaffold"].astype(bool)]
        .groupby("dominant_failure_reason", dropna=False)
        .agg(blocked_signal_count=("signal_id", "count"))
        .reset_index()
        .rename(columns={"dominant_failure_reason": "failure_reason"})
    )
    return candidate_fail.merge(signal_fail, on="failure_reason", how="left")


def _multi_summary(signal_summary: pd.DataFrame, candidate_detail: pd.DataFrame) -> pd.DataFrame:
    multi = signal_summary.loc[signal_summary["requires_multi_candidate_preservation"].astype(bool)].copy()
    if multi.empty:
        return pd.DataFrame(columns=["candidate_count_bucket", "signal_count"])
    def bucket(value: Any) -> str:
        count = int(pd.to_numeric(value, errors="coerce") or 0)
        if count == 2:
            return "2_candidates"
        if count == 3:
            return "3_candidates"
        if count >= 4:
            return "4plus_candidates"
        return "not_multi_candidate"
    multi["candidate_count_bucket"] = multi["candidate_association_count"].map(bucket)
    return (
        multi.groupby(["candidate_count_bucket", "has_any_buildable_scaffold", "has_full_0_2500ft_scaffold"], dropna=False)
        .agg(signal_count=("signal_id", "count"))
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )


def _active_overlap(candidate_detail: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "road_component_id",
        "recovery_strategy",
        "association_confidence_tier",
        "candidate_feasibility_label",
        "overlaps_existing_strict_active_signal_scaffold",
        "candidate_promoted_to_active",
    ]
    overlap = candidate_detail.loc[candidate_detail["overlaps_existing_strict_active_signal_scaffold"].astype(bool)]
    if overlap.empty:
        return pd.DataFrame(columns=cols + ["overlap_note"])
    out = overlap[[col for col in cols if col in overlap.columns]].copy()
    out["overlap_note"] = "diagnostic_only_overlap_with_existing_strict_active_signal"
    return out


def _review_queue(signal_summary: pd.DataFrame, candidate_detail: pd.DataFrame) -> pd.DataFrame:
    first = candidate_detail.sort_values(["signal_id", "candidate_rank"]).groupby("signal_id", as_index=False).first()
    queue = signal_summary.merge(
        first[
            [
                "signal_id",
                "matched_route_common",
                "roadway_division_status",
                "candidate_distance_ft",
                "candidate_max_edge_length_ft",
                "far_anchor_type_candidate",
                "candidate_feasibility_label",
                "failure_reason",
            ]
        ],
        on="signal_id",
        how="left",
    )
    queue["review_queue_type"] = "mapped_review_before_promotion"
    queue.loc[queue["requires_multi_candidate_preservation"].astype(bool) & queue["has_any_buildable_scaffold"].astype(bool), "review_queue_type"] = "highest_value_buildable_multi_candidate"
    queue.loc[queue["has_full_0_2500ft_scaffold"].astype(bool), "review_queue_type"] = "full_0_2500ft_scaffold_candidate"
    queue.loc[queue["has_one_direction_only_scaffold"].astype(bool), "review_queue_type"] = "one_direction_only_candidate"
    queue.loc[queue["dominant_failure_reason"].eq("graph gap"), "review_queue_type"] = "graph_gap_blocked_candidate"
    queue.loc[queue["overlaps_existing_strict_active_signal_scaffold"].astype(bool), "review_queue_type"] = "strict_active_overlap_or_conflict"
    queue["review_priority_score"] = (
        queue["has_any_buildable_scaffold"].astype(int) * 50
        + queue["has_full_0_2500ft_scaffold"].astype(int) * 25
        + queue["requires_multi_candidate_preservation"].astype(int) * 10
        + queue["has_one_direction_only_scaffold"].astype(int) * 5
        + pd.to_numeric(queue["candidate_association_count"], errors="coerce").fillna(0)
    )
    return queue.sort_values(["review_priority_score", "candidate_association_count"], ascending=False)


def _findings(summary: pd.DataFrame, by_strategy: pd.DataFrame, failures: pd.DataFrame, qa: pd.DataFrame) -> str:
    metrics = {row.metric: int(row.value) for row in summary.itertuples(index=False)}
    gain_vs_active = metrics["maximum_possible_expanded_scaffold_signal_universe_vs_strict_active"] - metrics["existing_strict_active_context_signals"]
    gain_vs_true = metrics["expanded_scaffold_universe_if_added_to_current_true_reference_count"] - metrics["current_step5_true_reference_signals"]
    top_strategy = by_strategy.iloc[0]["primary_recovery_strategy"] if not by_strategy.empty else "not_available"
    top_strategy_gain = int(by_strategy.iloc[0]["any_buildable_scaffold"]) if not by_strategy.empty else 0
    failure_text = "; ".join(
        f"{row.failure_reason}: {int(row.unique_signal_count)} signals"
        for row in failures.head(5).itertuples(index=False)
        if str(row.failure_reason)
    )
    return f"""# Signal Recovery Scaffold Feasibility Findings

Status: read-only scaffold-feasibility prototype. No active Step 5 logic, scaffold, context, crash assignment, access, speed, AADT, rate, or model outputs were modified or promoted.

## Bounded Question

This pass tests whether signal-road association recovery candidates can produce roadway-derived scaffold evidence using existing signal-adjacent graph edges and defensible far-anchor types. It does not create active geometry, bins, crash assignments, or context rows.

## Required Findings

1. Recovery candidate signals tested: {metrics['recovery_candidate_signals_tested']}
2. Signals that can produce any scaffold: {metrics['candidate_signals_with_any_buildable_scaffold']}
3. Signals that can produce full 0-2,500 ft scaffold: {metrics['candidate_signals_with_full_0_2500ft_scaffold']}
4. Signals that can produce at least 0-1,000 ft scaffold: {metrics['candidate_signals_with_0_1000ft_scaffold']}
5. One-direction-only but potentially useful signals: {metrics['candidate_signals_with_one_direction_only_scaffold']}
6. Signals requiring multi-candidate scaffold preservation: {metrics['candidate_signals_requiring_multi_candidate_preservation']}
7. Blocked or review-only signals: {metrics['candidate_signals_blocked_or_review_only']}; dominant blockers: {failure_text or 'none'}
8. Maximum scaffold universe compared with strict 971 active context signals: {metrics['maximum_possible_expanded_scaffold_signal_universe_vs_strict_active']} (+{gain_vs_active})
9. Maximum scaffold universe compared with 1,214 current TRUE reference signals if added later: {metrics['expanded_scaffold_universe_if_added_to_current_true_reference_count']} (+{gain_vs_true})
10. Largest practical scaffold gain strategy: `{top_strategy}` with {top_strategy_gain} buildable signals
11. Next test before active promotion: mapped review of buildable multi-candidate and full-coverage candidates, then a separate reviewed rule for graph-gap/virtual-anchor cases.

## Interpretation

The main feasibility gain comes from preserving near-tie multi-candidate associations long enough to test graph-derived scaffold, rather than forcing one nearest road. Review-only graph-gap, divided-pairing, and intersection-anchor candidates remain diagnostic until mapped review proves a defensible rule.

## QA

- QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}
- Crash records/direction fields used: False
- Access/speed/AADT/rate/model outputs used: False
- Candidate rows promoted: False
"""


def _qa(
    candidate_input: pd.DataFrame,
    signal_input: pd.DataFrame,
    candidate_detail: pd.DataFrame,
    signal_summary: pd.DataFrame,
    outputs: dict[str, Path],
) -> pd.DataFrame:
    plausible_count = int(signal_input["has_plausible_recovery_candidate"].astype(str).str.lower().eq("true").sum()) if not signal_input.empty else 0
    product_outputs = {key: path for key, path in outputs.items() if key not in {"findings", "qa", "manifest"}}
    multi_forced = signal_summary.loc[
        signal_summary["requires_multi_candidate_preservation"].astype(bool)
        & pd.to_numeric(signal_summary["candidate_association_count"], errors="coerce").le(1)
    ]
    review_promoted = candidate_detail.loc[
        candidate_detail["association_confidence_tier"].isin(["review_only_candidate", "not_recoverable_current_sources"])
        & candidate_detail["supports_any_buildable_scaffold"].astype(bool)
    ]
    overlap_promoted = candidate_detail.loc[
        candidate_detail["overlaps_existing_strict_active_signal_scaffold"].astype(bool)
        & candidate_detail["candidate_promoted_to_active"].astype(str).str.lower().eq("true")
    ]
    checks = [
        {"check_name": "candidate_association_input_count", "status": "passed", "observed": len(candidate_input), "expected": "reported", "note": "Candidate rows loaded from recovery feasibility output."},
        {"check_name": "candidate_association_unique_signal_count", "status": "passed", "observed": candidate_input["signal_id"].nunique(), "expected": "reported", "note": "Unique signals loaded from candidate associations."},
        {"check_name": "plausible_recovery_candidate_signal_count_reconciles", "status": "passed" if plausible_count == EXPECTED_PLAUSIBLE_RECOVERY_SIGNALS else "review", "observed": plausible_count, "expected": EXPECTED_PLAUSIBLE_RECOVERY_SIGNALS, "note": "Plausible deterministic + multi-candidate signal count from recovery summary."},
        {"check_name": "crash_records_read", "status": "passed", "observed": False, "expected": False, "note": "No crash files are read."},
        {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False, "expected": False, "note": "No crash fields are read."},
        {"check_name": "crash_counts_used_for_candidate_selection_or_scaffold_feasibility", "status": "passed", "observed": False, "expected": False, "note": "Scaffold feasibility uses graph-edge and anchor evidence only."},
        {"check_name": "access_speed_aadt_rate_model_outputs_used", "status": "passed", "observed": False, "expected": False, "note": "No access, speed, AADT, rate, or model outputs are read."},
        {"check_name": "active_outputs_modified", "status": "passed", "observed": False, "expected": False, "note": "All writes are isolated to review folder."},
        {"check_name": "candidates_promoted_to_active_scaffold_context", "status": "passed" if candidate_detail["candidate_promoted_to_active"].eq(False).all() else "review", "observed": False, "expected": False, "note": "No candidate promotion performed."},
        {"check_name": "outputs_written_only_to_review_folder", "status": "passed" if all(str(path).startswith(str(OUT_DIR)) for path in outputs.values()) else "review", "observed": str(OUT_DIR), "expected": str(OUT_DIR), "note": "Output path guard."},
        {"check_name": "multi_candidate_cases_preserve_ambiguity", "status": "passed" if multi_forced.empty else "review", "observed": len(multi_forced), "expected": 0, "note": "Multi-candidate signals must retain multiple candidate rows."},
        {"check_name": "review_only_or_unresolved_not_silently_promoted", "status": "passed" if review_promoted.empty else "review", "observed": len(review_promoted), "expected": 0, "note": "Review-only recovery tiers are not marked buildable."},
        {"check_name": "strict_active_overlap_checks_diagnostic_only", "status": "passed" if overlap_promoted.empty else "review", "observed": len(overlap_promoted), "expected": 0, "note": "Overlap/conflict check is diagnostic only."},
        {"check_name": "scaffold_feasibility_labels_diagnostic_not_final_truth", "status": "passed" if candidate_detail["diagnostic_not_final_truth"].eq(True).all() else "review", "observed": True, "expected": True, "note": "All feasibility labels are candidate diagnostics."},
        {"check_name": "product_outputs_created", "status": "passed" if all(path.exists() for path in product_outputs.values()) else "review", "observed": len([path for path in product_outputs.values() if path.exists()]), "expected": len(product_outputs), "note": "Checked before findings, QA, and manifest write."},
    ]
    return pd.DataFrame(checks)


def build_signal_recovery_scaffold_feasibility(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    global OUTPUT_ROOT, RECOVERY_DIR, ATTRITION_DIR, OUT_DIR, TABLES, ANALYSIS
    OUTPUT_ROOT = output_root
    RECOVERY_DIR = output_root / "review/current/signal_association_recovery_feasibility"
    ATTRITION_DIR = output_root / "review/current/signal_attrition_funnel_audit"
    OUT_DIR = output_root / "review/current/signal_recovery_scaffold_feasibility"
    TABLES = output_root / "tables/current"
    ANALYSIS = output_root / "analysis/current"

    started = datetime.now(timezone.utc)
    candidate_input, signal_input, adjacent, active_context, recovery_manifest = _load_inputs()
    attrition_summary = _read_csv(ATTRITION_DIR / "signal_attrition_funnel_summary.csv")
    candidate_detail = _build_candidate_detail(candidate_input, adjacent, active_context)
    signal_summary = _signal_summary(candidate_detail)
    feasibility_summary = _summary_table(signal_summary, attrition_summary)
    by_strategy = _group_summary(signal_summary, ["primary_recovery_strategy"])
    by_source = _group_summary(signal_summary, ["source_layer"])
    by_tier = _group_summary(signal_summary, ["primary_confidence_tier"])
    failures = _failure_reasons(candidate_detail, signal_summary)
    multi = _multi_summary(signal_summary, candidate_detail)
    overlap = _active_overlap(candidate_detail)
    review_queue = _review_queue(signal_summary, candidate_detail)

    outputs = {
        "candidate_detail": OUT_DIR / "signal_recovery_scaffold_candidate_detail.csv",
        "signal_summary": OUT_DIR / "signal_recovery_scaffold_signal_summary.csv",
        "feasibility_summary": OUT_DIR / "signal_recovery_scaffold_feasibility_summary.csv",
        "by_strategy": OUT_DIR / "signal_recovery_scaffold_by_strategy.csv",
        "by_source": OUT_DIR / "signal_recovery_scaffold_by_source.csv",
        "by_confidence_tier": OUT_DIR / "signal_recovery_scaffold_by_confidence_tier.csv",
        "failure_reasons": OUT_DIR / "signal_recovery_scaffold_failure_reasons.csv",
        "multi_candidate_summary": OUT_DIR / "signal_recovery_scaffold_multi_candidate_summary.csv",
        "existing_active_overlap": OUT_DIR / "signal_recovery_scaffold_existing_active_overlap.csv",
        "ranked_review_queue": OUT_DIR / "signal_recovery_scaffold_ranked_review_queue.csv",
        "findings": OUT_DIR / "signal_recovery_scaffold_findings.md",
        "qa": OUT_DIR / "signal_recovery_scaffold_qa.csv",
        "manifest": OUT_DIR / "signal_recovery_scaffold_manifest.json",
    }

    _write_csv(candidate_detail, outputs["candidate_detail"])
    _write_csv(signal_summary, outputs["signal_summary"])
    _write_csv(feasibility_summary, outputs["feasibility_summary"])
    _write_csv(by_strategy, outputs["by_strategy"])
    _write_csv(by_source, outputs["by_source"])
    _write_csv(by_tier, outputs["by_confidence_tier"])
    _write_csv(failures, outputs["failure_reasons"])
    _write_csv(multi, outputs["multi_candidate_summary"])
    _write_csv(overlap, outputs["existing_active_overlap"])
    _write_csv(review_queue, outputs["ranked_review_queue"])
    qa = _qa(candidate_input, signal_input, candidate_detail, signal_summary, outputs)
    _write_text(_findings(feasibility_summary, by_strategy, failures, qa), outputs["findings"])
    _write_csv(qa, outputs["qa"])

    metrics = {row.metric: int(row.value) for row in feasibility_summary.itertuples(index=False)}
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only expanded scaffold feasibility from signal-road recovery candidates",
        "read_only": True,
        "scaffold_feasibility_only": True,
        "active_outputs_modified": False,
        "step5_true_logic_changed": False,
        "active_signal_eligibility_changed": False,
        "active_signal_road_association_overwritten": False,
        "active_downstream_bins_created": False,
        "crashes_assigned": False,
        "crash_records_read": False,
        "crash_direction_fields_read_or_used": False,
        "crash_or_context_fields_used_to_select_candidates_or_evaluate_scaffold": False,
        "access_speed_aadt_rate_model_outputs_read": False,
        "candidate_rows_promoted_to_active": False,
        "input_files": [
            str(RECOVERY_DIR / "signal_recovery_candidate_associations.csv"),
            str(RECOVERY_DIR / "signal_recovery_candidate_summary_by_signal.csv"),
            str(RECOVERY_DIR / "signal_recovery_feasibility_manifest.json"),
            str(TABLES / "signal_adjacent_edges.csv"),
            str(ATTRITION_DIR / "signal_attrition_funnel_summary.csv"),
            str(ANALYSIS / "directional_bin_context_table_active/reference_signal_context_summary_active.csv"),
        ],
        "source_recovery_manifest_created_at_utc": recovery_manifest.get("created_at_utc", ""),
        "summary_metrics": metrics,
        "outputs": {key: str(path) for key, path in outputs.items()},
        "qa_checks": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only expanded scaffold feasibility from signal recovery candidates.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_signal_recovery_scaffold_feasibility(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
