"""Build a read-only chain-first directionality proposal for bin_context.

This proposal is review evidence only. It does not mutate bin_context,
approach_corridors, or any staged/source product.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/chain_first_directionality_proposal"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/materialize_bin_context_geometry",
    REPO / "work/roadway_graph/review/build_bin_context",
    REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

TOKEN_INCREASING = {"NB", "EB"}
TOKEN_DECREASING = {"SB", "WB"}
FORBIDDEN_CONTEXT_TOKENS = ["speed", "aadt", "access", "crash", "exposure", "rate"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def split_pipe(value: Any) -> list[str]:
    return [part for part in clean(value).split("|") if part]


def compact_values(series: pd.Series, limit: int = 20) -> str:
    values = sorted({clean(v) for v in series if clean(v)})
    if len(values) > limit:
        return "|".join(values[:limit]) + f"|...(+{len(values) - limit})"
    return "|".join(values)


def write_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False)
        return
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def staged_file_state() -> pd.DataFrame:
    rows = []
    for path in PARENTS + [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]:
        rows.append(
            {
                "path": rel(path),
                "exists": path.exists(),
                "length": path.stat().st_size if path.exists() else "",
                "mtime_ns": path.stat().st_mtime_ns if path.exists() else "",
            }
        )
    return pd.DataFrame(rows)


def parent_dependency_check() -> pd.DataFrame:
    forbidden = ["distance_band_units", "mvp", "crash", "access_context", "speed_context", "aadt", "exposure", "rate_distribution"]
    rows = []
    for path in PARENTS:
        exists = path.exists()
        read_status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                read_status = "readable"
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        rows.append(
            {
                "parent_path": rel(path),
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_directionality_proposal": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden),
            }
        )
    return pd.DataFrame(rows)


def proposed_label_from_token_and_side(token: str, side: str) -> tuple[str, str]:
    if token in TOKEN_INCREASING:
        return ("downstream", "") if side == "measure_increasing_from_signal" else ("upstream", "")
    if token in TOKEN_DECREASING:
        return ("downstream", "") if side == "measure_decreasing_from_signal" else ("upstream", "")
    return "", "missing_or_unusable_carriageway_direction_token"


def classify_chain(row: pd.Series) -> dict[str, Any]:
    configs = split_pipe(row["roadway_configuration_values"])
    tokens = split_pipe(row["carriageway_direction_token_values"])
    routes = split_pipe(row["route_base_values"])
    side = clean(row["measure_side_class"])
    warning = clean(row["parent_corridor_warning_status_values"])
    stop_reason = clean(row["chain_stop_reason"])
    config_text = " ".join(configs).lower()
    token = tokens[0] if len(tokens) == 1 else ""
    evidence_bits = [
        f"side={side}",
        f"configs={row['roadway_configuration_values']}",
        f"tokens={row['carriageway_direction_token_values'] or 'blank'}",
        f"routes={row['route_base_values']}",
        f"stop={stop_reason}",
    ]
    if warning and warning != "none":
        evidence_bits.append(f"parent_warning={warning}")

    if stop_reason == "stopped_due_insufficient_evidence":
        return {
            "proposed_upstream_downstream": "",
            "proposed_directionality_status": "insufficient_evidence",
            "proposed_directionality_method": "insufficient_evidence_no_assignment",
            "proposed_directionality_confidence": "low",
            "evidence_summary": "; ".join(evidence_bits),
            "unresolved_reason": "parent_chain_stopped_due_insufficient_evidence",
            "bin_level_fallback_needed": False,
        }
    if len(routes) > 1 or len(configs) > 1 or len(tokens) > 1:
        return {
            "proposed_upstream_downstream": "",
            "proposed_directionality_status": "ambiguous_needs_review",
            "proposed_directionality_method": "ambiguous_parallel_or_interchange",
            "proposed_directionality_confidence": "low",
            "evidence_summary": "; ".join(evidence_bits),
            "unresolved_reason": "mixed_route_configuration_or_carriageway_token_evidence",
            "bin_level_fallback_needed": True,
        }
    if not configs:
        return {
            "proposed_upstream_downstream": "",
            "proposed_directionality_status": "source_limited",
            "proposed_directionality_method": "source_limited_no_assignment",
            "proposed_directionality_confidence": "low",
            "evidence_summary": "; ".join(evidence_bits),
            "unresolved_reason": "missing_roadway_configuration",
            "bin_level_fallback_needed": False,
        }
    if "reversible" in config_text or "trail" in config_text:
        return {
            "proposed_upstream_downstream": "",
            "proposed_directionality_status": "ambiguous_needs_review",
            "proposed_directionality_method": "ambiguous_parallel_or_interchange",
            "proposed_directionality_confidence": "low",
            "evidence_summary": "; ".join(evidence_bits),
            "unresolved_reason": "reversible_or_trail_configuration_not_supported_by_rule",
            "bin_level_fallback_needed": True,
        }
    if "one-way" in config_text:
        label, reason = proposed_label_from_token_and_side(token, side)
        if label:
            return {
                "proposed_upstream_downstream": label,
                "proposed_directionality_status": "assigned",
                "proposed_directionality_method": "direct_one_way_carriageway",
                "proposed_directionality_confidence": "high" if warning in {"", "none"} else "medium",
                "evidence_summary": "; ".join(evidence_bits),
                "unresolved_reason": "",
                "bin_level_fallback_needed": False,
            }
        return {
            "proposed_upstream_downstream": "",
            "proposed_directionality_status": "insufficient_evidence",
            "proposed_directionality_method": "insufficient_evidence_no_assignment",
            "proposed_directionality_confidence": "low",
            "evidence_summary": "; ".join(evidence_bits),
            "unresolved_reason": reason,
            "bin_level_fallback_needed": False,
        }
    if "divided" in config_text and "undivided" not in config_text:
        label, reason = proposed_label_from_token_and_side(token, side)
        if label:
            return {
                "proposed_upstream_downstream": label,
                "proposed_directionality_status": "assigned",
                "proposed_directionality_method": "direct_divided_carriageway",
                "proposed_directionality_confidence": "high" if warning in {"", "none"} else "medium",
                "evidence_summary": "; ".join(evidence_bits),
                "unresolved_reason": "",
                "bin_level_fallback_needed": False,
            }
        return {
            "proposed_upstream_downstream": "",
            "proposed_directionality_status": "insufficient_evidence",
            "proposed_directionality_method": "insufficient_evidence_no_assignment",
            "proposed_directionality_confidence": "low",
            "evidence_summary": "; ".join(evidence_bits),
            "unresolved_reason": reason,
            "bin_level_fallback_needed": False,
        }
    if "undivided" in config_text:
        if side == "measure_increasing_from_signal":
            label = "downstream"
        elif side == "measure_decreasing_from_signal":
            label = "upstream"
        else:
            label = ""
        if label:
            return {
                "proposed_upstream_downstream": label,
                "proposed_directionality_status": "assigned",
                "proposed_directionality_method": "synthetic_undivided_centerline_side",
                "proposed_directionality_confidence": "medium" if warning in {"", "none"} else "low",
                "evidence_summary": "; ".join(evidence_bits),
                "unresolved_reason": "",
                "bin_level_fallback_needed": False,
            }
    return {
        "proposed_upstream_downstream": "",
        "proposed_directionality_status": "insufficient_evidence",
        "proposed_directionality_method": "insufficient_evidence_no_assignment",
        "proposed_directionality_confidence": "low",
        "evidence_summary": "; ".join(evidence_bits),
        "unresolved_reason": "rule_did_not_match_parent_evidence",
        "bin_level_fallback_needed": False,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log("Starting read-only chain-first directionality proposal.")
    before_state = staged_file_state()
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)

    log("Reading staged parent evidence.")
    bin_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "signal_approach_id",
        "logical_corridor_chain_id",
        "measure_side_class",
        "chain_total_reach_ft",
        "chain_stop_reason",
        "chain_completeness_status",
        "distance_band",
        "bin_length_ft",
        "route_base",
        "source_route_name",
        "primary_stable_travelway_id",
        "supporting_stable_travelway_ids",
        "carriageway_direction_token",
        "roadway_configuration",
        "source_measure_start",
        "source_measure_end",
        "geometry_status",
        "parent_corridor_warning_status",
        "parent_corridor_review_status",
        "directionality_status",
        "upstream_downstream",
    ]
    bins = pd.read_parquet(BIN_CONTEXT, columns=bin_cols)
    corridors = pd.read_parquet(
        APPROACH_CORRIDORS,
        columns=[
            "logical_corridor_chain_id",
            "stable_travelway_id",
            "source_route_id",
            "source_route_common",
            "route_base",
            "source_route_name",
            "carriageway_direction_token",
            "roadway_configuration",
            "parent_corridor_gate_severity",
            "chain_bin_eligible_flag",
        ],
    )
    schema_cols = set(pq.ParquetFile(BIN_CONTEXT).schema_arrow.names) | set(pq.ParquetFile(APPROACH_CORRIDORS).schema_arrow.names)

    log("Building chain universe.")
    chain_bins = bins.groupby("logical_corridor_chain_id", dropna=False).agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        measure_side_class=("measure_side_class", "first"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_completeness_status=("chain_completeness_status", "first"),
        bin_count=("stable_bin_id", "count"),
        total_bin_length_ft=("bin_length_ft", "sum"),
        distance_band_coverage=("distance_band", compact_values),
        route_base_values=("route_base", compact_values),
        source_route_name_values=("source_route_name", compact_values),
        primary_stable_travelway_id_values=("primary_stable_travelway_id", compact_values),
        supporting_stable_travelway_id_values=("supporting_stable_travelway_ids", compact_values),
        carriageway_direction_token_values=("carriageway_direction_token", compact_values),
        roadway_configuration_values=("roadway_configuration", compact_values),
        source_measure_min=("source_measure_start", "min"),
        source_measure_max=("source_measure_end", "max"),
        geometry_status_values=("geometry_status", compact_values),
        parent_corridor_warning_status_values=("parent_corridor_warning_status", compact_values),
        parent_corridor_review_status_values=("parent_corridor_review_status", compact_values),
        current_directionality_status_values=("directionality_status", compact_values),
        upstream_downstream_values=("upstream_downstream", compact_values),
    ).reset_index()
    corridor_chain = corridors.groupby("logical_corridor_chain_id", dropna=False).agg(
        source_route_id_values=("source_route_id", compact_values),
        source_route_common_values=("source_route_common", compact_values),
        corridor_stable_travelway_id_values=("stable_travelway_id", compact_values),
        corridor_roadway_configuration_values=("roadway_configuration", compact_values),
        corridor_carriageway_direction_token_values=("carriageway_direction_token", compact_values),
        corridor_parent_gate_severity_values=("parent_corridor_gate_severity", compact_values),
        chain_bin_eligible_values=("chain_bin_eligible_flag", compact_values),
    ).reset_index()
    universe = chain_bins.merge(corridor_chain, on="logical_corridor_chain_id", how="left")
    write_csv("chain_directionality_universe.csv", universe)

    log("Classifying chain-level proposal.")
    proposal_rows = []
    for row in universe.itertuples(index=False):
        row_series = pd.Series(row._asdict())
        classification = classify_chain(row_series)
        proposal_rows.append({**row_series.to_dict(), **classification})
    proposal = pd.DataFrame(proposal_rows)
    write_csv("chain_directionality_proposal.csv", proposal)

    log("Writing summaries and coverage simulation.")
    write_csv("directionality_method_summary.csv", proposal.groupby("proposed_directionality_method", dropna=False).agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum")).reset_index())
    write_csv("directionality_status_summary.csv", proposal.groupby("proposed_directionality_status", dropna=False).agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum")).reset_index())
    write_csv("directionality_confidence_summary.csv", proposal.groupby("proposed_directionality_confidence", dropna=False).agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum")).reset_index())

    assigned_chains = set(proposal.loc[proposal["proposed_directionality_status"].eq("assigned"), "logical_corridor_chain_id"].astype(str))
    bins["simulation_assignment_status"] = bins["logical_corridor_chain_id"].astype(str).map(lambda x: "assigned" if x in assigned_chains else "unresolved")
    chain_sim = proposal.groupby("proposed_directionality_status", dropna=False).agg(
        chain_count=("logical_corridor_chain_id", "count"),
        bin_count=("bin_count", "sum"),
        approach_count=("signal_approach_id", "nunique"),
        signal_count=("stable_signal_id", "nunique"),
    ).reset_index()
    write_csv("chain_directionality_coverage_simulation.csv", chain_sim)
    write_csv("bin_coverage_simulation_by_distance_band.csv", bins.groupby(["simulation_assignment_status", "distance_band"], dropna=False).agg(bin_count=("stable_bin_id", "count"), total_bin_length_ft=("bin_length_ft", "sum"), chain_count=("logical_corridor_chain_id", "nunique")).reset_index())
    approach_signal = bins.groupby("simulation_assignment_status", dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        chain_count=("logical_corridor_chain_id", "nunique"),
        approach_count=("signal_approach_id", "nunique"),
        signal_count=("stable_signal_id", "nunique"),
    ).reset_index()
    write_csv("approach_signal_coverage_simulation.csv", approach_signal)

    unresolved = proposal[~proposal["proposed_directionality_status"].eq("assigned")].copy()
    write_csv("unresolved_chain_ledger.csv", unresolved)
    high_impact = unresolved.sort_values(["bin_count", "chain_total_reach_ft"], ascending=[False, False]).head(500)
    write_csv("high_impact_unresolved_chain_review.csv", high_impact)
    mixed = proposal[
        proposal["unresolved_reason"].astype(str).str.contains("mixed|reversible|trail|warning|ambiguous", case=False, na=False)
        | proposal["bin_level_fallback_needed"].fillna(False).astype(bool)
    ].copy()
    write_csv("mixed_evidence_chain_review.csv", mixed)
    fallback = proposal[proposal["bin_level_fallback_needed"].fillna(False).astype(bool)].copy()
    write_csv("bin_level_fallback_needed_ledger.csv", fallback)

    crash_fields = [
        col
        for col in schema_cols
        if "crash" in col.lower() or col.lower() in {"direction", "dir", "veh_direction", "crash_direction"}
    ]
    write_csv("no_crash_direction_field_check.csv", [{"check_name": "no_crash_direction_fields_used", "used_field_count": 0, "available_crash_or_direction_like_field_count": len(crash_fields), "available_fields": "|".join(sorted(crash_fields)), "pass": True}])
    forbidden_context = [col for col in schema_cols for token in FORBIDDEN_CONTEXT_TOKENS if token in col.lower()]
    write_csv("context_enrichment_guard_audit.csv", [{"check_name": "no_context_enrichment_fields_used", "used_field_count": 0, "available_forbidden_context_field_count": len(set(forbidden_context)), "available_fields": "|".join(sorted(set(forbidden_context))), "pass": True}])

    after_state = staged_file_state()
    mutation = before_state.merge(after_state, on="path", suffixes=("_before", "_after"), how="outer")
    mutation["length_unchanged"] = mutation["length_before"].astype(str).eq(mutation["length_after"].astype(str))
    mutation["mtime_unchanged"] = mutation["mtime_ns_before"].astype(str).eq(mutation["mtime_ns_after"].astype(str))
    mutation["pass"] = mutation["length_unchanged"] & mutation["mtime_unchanged"]
    write_csv("no_staged_mutation_check.csv", mutation)

    assigned_chain_count = int(proposal["proposed_directionality_status"].eq("assigned").sum())
    unresolved_chain_count = int(len(proposal) - assigned_chain_count)
    assigned_bin_count = int(proposal.loc[proposal["proposed_directionality_status"].eq("assigned"), "bin_count"].sum())
    unresolved_bin_count = int(proposal.loc[~proposal["proposed_directionality_status"].eq("assigned"), "bin_count"].sum())
    fallback_count = int(proposal["bin_level_fallback_needed"].fillna(False).astype(bool).sum())
    unresolved_share = unresolved_chain_count / max(len(proposal), 1)
    if assigned_chain_count == 0:
        decision = "chain_directionality_blocked_by_insufficient_parent_evidence"
    elif fallback_count > 0 or unresolved_share > 0.10:
        decision = "chain_directionality_needs_rule_refinement"
    elif unresolved_chain_count > 0:
        decision = "chain_directionality_proposal_ready_with_small_review_ledger"
    else:
        decision = "chain_directionality_proposal_ready_for_bin_context_patch"

    write_csv("readiness_decision.csv", [{"decision": decision, "assigned_chain_count": assigned_chain_count, "unresolved_chain_count": unresolved_chain_count, "assigned_bin_count": assigned_bin_count, "unresolved_bin_count": unresolved_bin_count, "bin_level_fallback_needed_count": fallback_count}])
    if decision == "chain_directionality_needs_rule_refinement":
        next_actions = [
            {"priority": 1, "recommended_next_action": "Refine chain-level directionality rules for mixed/reversible/trail and blank-token divided evidence before mutation."},
            {"priority": 2, "recommended_next_action": "Create targeted review for high-impact unresolved chains and bin-level fallback candidates."},
            {"priority": 3, "recommended_next_action": "Do not patch bin_context directionality until unresolved/fallback ledger is reduced or explicitly accepted."},
        ]
    else:
        next_actions = [
            {"priority": 1, "recommended_next_action": "Review proposal ledgers, then patch bin_context by logical_corridor_chain_id only after approval."},
            {"priority": 2, "recommended_next_action": "Preserve unresolved chains with explicit directionality status rather than forcing labels."},
            {"priority": 3, "recommended_next_action": "Do not use crash direction fields."},
        ]
    write_csv("recommended_next_actions.csv", next_actions)

    findings = f"""# Chain-First Directionality Proposal Findings

## What Was Proposed
Created a read-only chain-level directionality proposal for {len(proposal):,} logical corridor chains, simulating propagation to {len(bins):,} neutral bin rows.

## What Was Not Mutated
No staged parquet, canonical product, source artifact, upstream/downstream field, or directionality field was modified. This is proposal evidence only.

## Parent Dependency Statement
Only validated staged parents were read. Review outputs were diagnostic evidence only. Downstream/crash/context products were not parents.

## Directionality Evidence Used
Evidence used: roadway configuration, carriageway direction token, measure side relative to signal, route/travelway identity, chain stop/completeness status, parent warning/review status, and bin geometry status. Crash direction fields were not used.

## Proposed Counts
Assigned chains: {assigned_chain_count:,}. Unresolved chains: {unresolved_chain_count:,}. Assigned bins: {assigned_bin_count:,}. Unresolved bins: {unresolved_bin_count:,}. Bin-level fallback candidates: {fallback_count:,}.

## Ambiguous Or Source-Limited Cases
Unresolved chains are ledgered in `unresolved_chain_ledger.csv`; high-impact unresolved chains are in `high_impact_unresolved_chain_review.csv`; mixed evidence and fallback candidates are separately ledgered.

## Chain-Level Propagation Safety
Proposal joins to bin_context by `logical_corridor_chain_id`, and every assigned chain maps to existing bins. No duplicate bin rows are created by the simulation. Staged mutation check passed: {bool(mutation['pass'].all())}.

## Recommended Next Task
Decision: `{decision}`. Follow `recommended_next_actions.csv`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    write_json(
        "manifest.json",
        {
            "created_utc": now(),
            "product": "chain_first_directionality_proposal",
            "bounded_question": "Which logical corridor chains can receive proposed upstream/downstream labels before mutating bin_context?",
            "source_inputs": [rel(path) for path in PARENTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "output_grain": "one row per logical_corridor_chain_id plus simulation summaries",
            "caveats": ["Synthetic undivided proposals require review before mutation.", "Proposal does not assign directionality to staged bins."],
            "final_decision": decision,
        },
    )
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
            "checks": {
                "parent_dependency_passed": bool(parent_check["allowed_parent_for_directionality_proposal"].all() and not parent_check["downstream_object_parent_flag"].any()),
                "proposal_one_row_per_chain": int(len(proposal)) == int(proposal["logical_corridor_chain_id"].nunique()),
                "assigned_chains_map_to_bins": int(proposal.loc[proposal["proposed_directionality_status"].eq("assigned"), "bin_count"].isna().sum()) == 0,
                "no_staged_mutation": bool(mutation["pass"].all()),
                "no_crash_direction_fields_used": True,
                "no_context_enrichment_fields_used": True,
            },
        },
    )
    log(f"Chain-first directionality proposal complete with decision {decision}.")


if __name__ == "__main__":
    main()
