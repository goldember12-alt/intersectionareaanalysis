"""Read-only audit of chain directionality rule refinements.

This script evaluates safer refinements to the first-pass chain-level
directionality proposal. It writes review evidence only and does not mutate
staged cache products.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
FIRST_PASS = REPO / "work/roadway_graph/review/chain_first_directionality_proposal"
OUT = REPO / "work/roadway_graph/review/chain_directionality_rule_refinement_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

FIRST_PASS_PROPOSAL = FIRST_PASS / "chain_directionality_proposal.csv"
FIRST_PASS_UNIVERSE = FIRST_PASS / "chain_directionality_universe.csv"

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
METADATA = [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]
DIAGNOSTIC_EVIDENCE = [
    FIRST_PASS,
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/materialize_bin_context_geometry",
    REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

TOKEN_INCREASING = {"NB", "EB"}
TOKEN_DECREASING = {"SB", "WB"}
DIRECTION_TOKENS = TOKEN_INCREASING | TOKEN_DECREASING
FORBIDDEN_CONTEXT_TOKENS = ("speed", "aadt", "access", "crash", "exposure", "rate")
ROUTE_TOKEN_RE = re.compile(r"(?:^|[^A-Z])(NB|SB|EB|WB)(?:$|[^A-Z])")
ROUTE_SUFFIX_RE = re.compile(r"(NB|SB|EB|WB)$")


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


def compact_values(values: pd.Series | list[Any], limit: int = 25) -> str:
    found = sorted({clean(v) for v in values if clean(v)})
    if len(found) > limit:
        return "|".join(found[:limit]) + f"|...(+{len(found) - limit})"
    return "|".join(found)


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
    for path in PARENTS + METADATA:
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
    forbidden = ("distance_band_units", "mvp", "crash", "access_context", "speed_context", "aadt", "exposure", "rate")
    rows = []
    for path in PARENTS:
        exists = path.exists()
        read_status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                read_status = "readable"
            except Exception as exc:  # pragma: no cover - defensive diagnostic
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        rows.append(
            {
                "parent_path": rel(path),
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_rule_refinement_audit": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden),
            }
        )
    return pd.DataFrame(rows)


def token_to_label(token: str, side: str) -> str:
    if token in TOKEN_INCREASING:
        return "downstream" if side == "measure_increasing_from_signal" else "upstream"
    if token in TOKEN_DECREASING:
        return "downstream" if side == "measure_decreasing_from_signal" else "upstream"
    return ""


def synthetic_side_label(side: str) -> str:
    if side == "measure_increasing_from_signal":
        return "downstream"
    if side == "measure_decreasing_from_signal":
        return "upstream"
    return ""


def infer_route_text_tokens(row: pd.Series) -> str:
    tokens: list[str] = []
    for col in ("source_route_name_values", "route_base_values", "source_route_common_values"):
        for part in split_pipe(row.get(col, "")):
            text = part.strip()
            for match in ROUTE_TOKEN_RE.finditer(text):
                tokens.append(match.group(1))
            suffix = ROUTE_SUFFIX_RE.search(text)
            if suffix:
                tokens.append(suffix.group(1))
    return "|".join(sorted(set(tokens)))


def first_nonblank_by_order(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns or frame.empty:
        return ""
    ordered = frame.sort_values(["segment_start_distance_ft", "segment_order"], na_position="last")
    for value in ordered[column]:
        text = clean(value)
        if text:
            return text
    return ""


def length_dominant(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns or frame.empty:
        return ""
    tmp = frame[[column, "segment_length_ft"]].copy()
    tmp[column] = tmp[column].map(clean)
    tmp = tmp[tmp[column] != ""]
    if tmp.empty:
        return ""
    grouped = tmp.groupby(column, dropna=False)["segment_length_ft"].sum().sort_values(ascending=False)
    return str(grouped.index[0])


def build_segment_summary(approach_corridors: pd.DataFrame, unresolved_ids: set[str]) -> pd.DataFrame:
    seg = approach_corridors[approach_corridors["logical_corridor_chain_id"].isin(unresolved_ids)].copy()
    if seg.empty:
        return pd.DataFrame(columns=["logical_corridor_chain_id"])
    seg["segment_length_ft"] = (
        pd.to_numeric(seg["segment_end_distance_ft"], errors="coerce")
        - pd.to_numeric(seg["segment_start_distance_ft"], errors="coerce")
    ).clip(lower=0)
    rows: list[dict[str, Any]] = []
    for chain_id, group in seg.groupby("logical_corridor_chain_id", sort=False):
        configs = [clean(v) for v in group["roadway_configuration"] if clean(v)]
        tokens = [clean(v) for v in group["carriageway_direction_token"] if clean(v)]
        routes = [clean(v) for v in group["route_base"] if clean(v)]
        names = [clean(v) for v in group["source_route_name"] if clean(v)]
        rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "segment_count": int(len(group)),
                "stable_travelway_id_count": int(group["stable_travelway_id"].map(clean).replace("", pd.NA).nunique(dropna=True)),
                "configuration_count": len(set(configs)),
                "token_count": len(set(tokens)),
                "route_base_count": len(set(routes)),
                "source_route_name_count": len(set(names)),
                "dominant_roadway_configuration": length_dominant(group, "roadway_configuration"),
                "nearest_signal_roadway_configuration": first_nonblank_by_order(group, "roadway_configuration"),
                "dominant_carriageway_token": length_dominant(group, "carriageway_direction_token"),
                "nearest_signal_carriageway_token": first_nonblank_by_order(group, "carriageway_direction_token"),
                "route_base_values_segment": compact_values(group["route_base"]),
                "source_route_name_values_segment": compact_values(group["source_route_name"]),
                "roadway_configuration_values_segment": compact_values(group["roadway_configuration"]),
                "carriageway_direction_token_values_segment": compact_values(group["carriageway_direction_token"]),
                "measure_side_values_segment": compact_values(group["measure_side_class"]),
                "parent_gate_severity_values_segment": compact_values(group["parent_corridor_gate_severity"]),
                "route_measure_continuity_values": compact_values(group["route_measure_continuity_status"]),
                "geometry_continuity_values": compact_values(group["geometry_continuity_status"]),
                "min_segment_start_distance_ft": float(pd.to_numeric(group["segment_start_distance_ft"], errors="coerce").min()),
                "max_segment_end_distance_ft": float(pd.to_numeric(group["segment_end_distance_ft"], errors="coerce").max()),
            }
        )
    return pd.DataFrame(rows)


def pattern_family(row: pd.Series) -> str:
    configs = split_pipe(row.get("roadway_configuration_values", ""))
    tokens = split_pipe(row.get("carriageway_direction_token_values", ""))
    routes = split_pipe(row.get("route_base_values", ""))
    config_text = " ".join(configs).lower()
    token_text = clean(row.get("carriageway_direction_token_values", ""))
    route_text_token = clean(row.get("route_text_token", ""))
    stop_reason = clean(row.get("chain_stop_reason", ""))
    source_names = clean(row.get("source_route_name_values", "")).lower()
    route_bases = clean(row.get("route_base_values", "")).lower()

    if "reversible" in config_text or "trail" in config_text:
        return "reversible_or_trail_like_case"
    if stop_reason == "stopped_due_insufficient_evidence":
        return "insufficient_route_measure_evidence"
    if len(routes) > 1:
        return "conflicting_route_identity"
    if len(configs) > 1 and len(tokens) > 1:
        return "parallel_or_interchange_ambiguity"
    if len(configs) > 1:
        return "mixed_roadway_configuration_only"
    if len(tokens) > 1:
        return "mixed_carriageway_token_only"
    if "rmp" in source_names or "ramp" in source_names or "rmp" in route_bases:
        if not token_text and not route_text_token and "one-way" in config_text:
            return "ramp_or_ramp_like_geometry"
    if not token_text and "divided" in config_text and "undivided" not in config_text:
        return "divided_with_blank_token"
    if "one-way" in config_text and (not token_text or "|" in token_text):
        return "one_way_with_blank_or_mixed_token"
    if not token_text:
        return "blank_or_unknown_carriageway_token"
    if "undivided" in config_text and clean(row.get("measure_side_class", "")) == "":
        return "undivided_synthetic_side_missing"
    if clean(row.get("geometry_status_values", "")) == "":
        return "geometry_missing_or_unusable"
    if clean(row.get("parent_corridor_warning_status_values", "")) not in {"", "none"}:
        return "parent_warning_or_ambiguous_approach"
    if stop_reason == "stopped_at_source_extent" or float(row.get("chain_total_reach_ft", 0) or 0) < 250:
        return "low_evidence_source_extent_or_short_chain"
    return "other_uncategorized"


def apply_refined_rule(row: pd.Series) -> dict[str, Any]:
    first_status = clean(row.get("proposed_directionality_status", ""))
    first_label = clean(row.get("proposed_upstream_downstream", ""))
    side = clean(row.get("measure_side_class", ""))
    configs = split_pipe(row.get("roadway_configuration_values", ""))
    tokens = split_pipe(row.get("carriageway_direction_token_values", ""))
    config_text = " ".join(configs).lower()
    route_text_token = clean(row.get("route_text_token", ""))
    route_text_tokens = split_pipe(route_text_token)
    pattern = clean(row.get("pattern_family", ""))

    if first_status == "assigned":
        return {
            "refined_proposed_upstream_downstream": first_label,
            "refined_directionality_status": "assigned",
            "refined_directionality_method": clean(row.get("proposed_directionality_method", "")),
            "refined_directionality_confidence": clean(row.get("proposed_directionality_confidence", "")),
            "refined_rule_id": "R0_keep_first_pass_assignment",
            "refined_evidence_summary": "First-pass assignment retained.",
            "refined_unresolved_reason": "",
            "refined_bin_level_fallback_needed": False,
            "map_review_candidate_flag": False,
        }

    # R1: same route branch, mixed divided/undivided source segmentation, one nonblank token.
    if (
        pattern == "mixed_roadway_configuration_only"
        and len(tokens) == 1
        and tokens[0] in DIRECTION_TOKENS
        and len(split_pipe(row.get("route_base_values", ""))) <= 1
    ):
        label = token_to_label(tokens[0], side)
        if label:
            return {
                "refined_proposed_upstream_downstream": label,
                "refined_directionality_status": "assigned",
                "refined_directionality_method": "same_route_config_transition_token_rule",
                "refined_directionality_confidence": "medium",
                "refined_rule_id": "R1_mixed_config_consistent_token",
                "refined_evidence_summary": "Mixed roadway configuration allowed because route identity and carriageway token are consistent.",
                "refined_unresolved_reason": "",
                "refined_bin_level_fallback_needed": False,
                "map_review_candidate_flag": False,
            }

    # R2: one-way/ramp routes with missing carriageway token, but route text has exactly one direction token.
    if (
        "one-way" in config_text
        and not tokens
        and len(route_text_tokens) == 1
        and route_text_tokens[0] in DIRECTION_TOKENS
    ):
        label = token_to_label(route_text_tokens[0], side)
        if label:
            return {
                "refined_proposed_upstream_downstream": label,
                "refined_directionality_status": "assigned",
                "refined_directionality_method": "direct_one_way_route_text_token",
                "refined_directionality_confidence": "medium",
                "refined_rule_id": "R2_one_way_route_text_token",
                "refined_evidence_summary": "One-way configuration had blank token, but route/base/name text carries a single direction token.",
                "refined_unresolved_reason": "",
                "refined_bin_level_fallback_needed": False,
                "map_review_candidate_flag": False,
            }

    # R3: two-way undivided can use synthetic side even if a token was present but not needed.
    if (
        len(configs) == 1
        and "two-way undivided" in config_text
        and "reversible" not in config_text
    ):
        label = synthetic_side_label(side)
        if label:
            return {
                "refined_proposed_upstream_downstream": label,
                "refined_directionality_status": "assigned",
                "refined_directionality_method": "synthetic_undivided_centerline_side_refined",
                "refined_directionality_confidence": "medium",
                "refined_rule_id": "R3_undivided_synthetic_side",
                "refined_evidence_summary": "Two-way undivided chain assigned synthetically by neutral measure side.",
                "refined_unresolved_reason": "",
                "refined_bin_level_fallback_needed": False,
                "map_review_candidate_flag": False,
            }

    map_review = pattern in {
        "parallel_or_interchange_ambiguity",
        "reversible_or_trail_like_case",
        "mixed_carriageway_token_only",
        "conflicting_route_identity",
    } or bool(row.get("bin_count", 0) >= 40 and pattern in {"mixed_roadway_configuration_only", "divided_with_blank_token"})
    fallback = pattern in {"parallel_or_interchange_ambiguity", "mixed_carriageway_token_only", "conflicting_route_identity"}
    status = "ambiguous_needs_review" if map_review else "insufficient_evidence"
    return {
        "refined_proposed_upstream_downstream": "",
        "refined_directionality_status": status,
        "refined_directionality_method": "unresolved_after_refinement",
        "refined_directionality_confidence": "low",
        "refined_rule_id": "R9_preserve_unresolved",
        "refined_evidence_summary": f"Preserved unresolved; pattern={pattern}.",
        "refined_unresolved_reason": pattern,
        "refined_bin_level_fallback_needed": fallback,
        "map_review_candidate_flag": map_review,
    }


def summarize_counts(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        frame.groupby(group_cols, dropna=False)
        .agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum"))
        .reset_index()
        .sort_values(["bin_count", "chain_count"], ascending=False)
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    before_state = staged_file_state()

    log("Starting read-only chain directionality rule refinement audit.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)

    log("Reading first-pass proposal and staged segment evidence.")
    proposal = pd.read_csv(FIRST_PASS_PROPOSAL)
    universe = pd.read_csv(FIRST_PASS_UNIVERSE)
    if len(proposal) != proposal["logical_corridor_chain_id"].nunique():
        raise RuntimeError("First-pass proposal is not one row per logical_corridor_chain_id.")
    if len(universe) != universe["logical_corridor_chain_id"].nunique():
        raise RuntimeError("First-pass universe is not one row per logical_corridor_chain_id.")

    unresolved_ids = set(proposal.loc[proposal["proposed_directionality_status"] != "assigned", "logical_corridor_chain_id"])
    ac_cols = [
        "logical_corridor_chain_id",
        "stable_travelway_id",
        "segment_order",
        "segment_start_distance_ft",
        "segment_end_distance_ft",
        "measure_side_class",
        "route_base",
        "source_route_name",
        "source_route_id",
        "source_route_common",
        "carriageway_direction_token",
        "roadway_configuration",
        "parent_corridor_gate_severity",
        "route_measure_continuity_status",
        "geometry_continuity_status",
    ]
    approach_corridors = pd.read_parquet(APPROACH_CORRIDORS, columns=ac_cols)

    log("Building unresolved segment evidence summaries.")
    segment_summary = build_segment_summary(approach_corridors, unresolved_ids)
    proposal["route_text_token"] = proposal.apply(infer_route_text_tokens, axis=1)
    unresolved = proposal[proposal["logical_corridor_chain_id"].isin(unresolved_ids)].merge(
        segment_summary, on="logical_corridor_chain_id", how="left"
    )
    unresolved["pattern_family"] = unresolved.apply(pattern_family, axis=1)
    write_csv(
        "unresolved_segment_evidence_summary.csv",
        unresolved[
            [
                "logical_corridor_chain_id",
                "stable_signal_id",
                "signal_approach_id",
                "bin_count",
                "measure_side_class",
                "chain_stop_reason",
                "first_pass_status" if False else "proposed_directionality_status",
                "unresolved_reason",
                "pattern_family",
                "segment_count",
                "stable_travelway_id_count",
                "configuration_count",
                "token_count",
                "route_base_count",
                "dominant_roadway_configuration",
                "nearest_signal_roadway_configuration",
                "dominant_carriageway_token",
                "nearest_signal_carriageway_token",
                "route_text_token",
                "route_base_values_segment",
                "source_route_name_values_segment",
                "route_measure_continuity_values",
                "geometry_continuity_values",
            ]
        ],
    )
    pattern_audit = summarize_counts(unresolved, ["pattern_family"])
    write_csv("unresolved_pattern_audit.csv", pattern_audit)

    log("Applying refined chain-level rules in simulation only.")
    proposal = proposal.merge(
        unresolved[["logical_corridor_chain_id", "pattern_family"]], on="logical_corridor_chain_id", how="left"
    )
    proposal["pattern_family"] = proposal["pattern_family"].fillna("")
    refined_records = proposal.apply(apply_refined_rule, axis=1, result_type="expand")
    refined = pd.concat([proposal, refined_records], axis=1)
    write_csv("refined_chain_directionality_proposal.csv", refined)

    first_assigned = proposal["proposed_directionality_status"].eq("assigned")
    refined_assigned = refined["refined_directionality_status"].eq("assigned")
    newly_assigned = refined[~first_assigned & refined_assigned].copy()
    still_unresolved = refined[~refined_assigned].copy()
    changed = refined[
        (refined["proposed_directionality_status"] != refined["refined_directionality_status"])
        | (refined["proposed_directionality_method"] != refined["refined_directionality_method"])
        | (refined["proposed_upstream_downstream"].fillna("") != refined["refined_proposed_upstream_downstream"].fillna(""))
    ].copy()

    candidate_rows = [
        {
            "rule_id": "R1_mixed_config_consistent_token",
            "applicability_condition": "mixed roadway configuration, one route identity, one nonblank carriageway token",
            "chains_affected": int((newly_assigned["refined_rule_id"] == "R1_mixed_config_consistent_token").sum()),
            "bins_affected": int(newly_assigned.loc[newly_assigned["refined_rule_id"] == "R1_mixed_config_consistent_token", "bin_count"].sum()),
            "estimated_confidence": "medium",
            "false_positive_risk": "moderate_low",
            "safe_or_unsafe": "safe_for_simulation_candidate",
            "reason": "Configuration changes appear to be branch/source segmentation while route and carriageway token stay consistent.",
        },
        {
            "rule_id": "R2_one_way_route_text_token",
            "applicability_condition": "one-way configuration, blank carriageway token, exactly one route/base/name direction token",
            "chains_affected": int((newly_assigned["refined_rule_id"] == "R2_one_way_route_text_token").sum()),
            "bins_affected": int(newly_assigned.loc[newly_assigned["refined_rule_id"] == "R2_one_way_route_text_token", "bin_count"].sum()),
            "estimated_confidence": "medium",
            "false_positive_risk": "moderate",
            "safe_or_unsafe": "safe_for_simulation_candidate",
            "reason": "The direction token comes from staged route identity text, not crash evidence.",
        },
        {
            "rule_id": "R3_undivided_synthetic_side",
            "applicability_condition": "single two-way undivided configuration with usable measure side",
            "chains_affected": int((newly_assigned["refined_rule_id"] == "R3_undivided_synthetic_side").sum()),
            "bins_affected": int(newly_assigned.loc[newly_assigned["refined_rule_id"] == "R3_undivided_synthetic_side", "bin_count"].sum()),
            "estimated_confidence": "medium",
            "false_positive_risk": "low",
            "safe_or_unsafe": "safe_for_simulation_candidate",
            "reason": "Synthetic undivided assignment follows the established measure-side doctrine.",
        },
        {
            "rule_id": "R4_divided_blank_token_pairing",
            "applicability_condition": "divided configuration with blank token and no single route-text token",
            "chains_affected": int((still_unresolved["pattern_family"] == "divided_with_blank_token").sum()),
            "bins_affected": int(still_unresolved.loc[still_unresolved["pattern_family"] == "divided_with_blank_token", "bin_count"].sum()),
            "estimated_confidence": "low",
            "false_positive_risk": "high_without_parallel_pairing_audit",
            "safe_or_unsafe": "unsafe_without_additional_review",
            "reason": "Divided travel direction cannot be recovered from measure side alone.",
        },
        {
            "rule_id": "R5_reversible_trail",
            "applicability_condition": "reversible/trail/nonstandard roadway configuration",
            "chains_affected": int((still_unresolved["pattern_family"] == "reversible_or_trail_like_case").sum()),
            "bins_affected": int(still_unresolved.loc[still_unresolved["pattern_family"] == "reversible_or_trail_like_case", "bin_count"].sum()),
            "estimated_confidence": "low",
            "false_positive_risk": "high",
            "safe_or_unsafe": "unsafe_preserve_unresolved",
            "reason": "Reversible/trail cases need explicit manual or specialized rule evidence.",
        },
    ]
    candidates = pd.DataFrame(candidate_rows)
    write_csv("rule_refinement_candidates.csv", candidates)
    write_csv("rule_refinement_impact_summary.csv", candidates[["rule_id", "chains_affected", "bins_affected", "estimated_confidence", "false_positive_risk", "safe_or_unsafe"]])

    log("Writing comparison, fallback, and coverage summaries.")
    comparison_rows = [
        {"metric": "first_pass_assigned_chains", "value": int(first_assigned.sum())},
        {"metric": "first_pass_assigned_bins", "value": int(proposal.loc[first_assigned, "bin_count"].sum())},
        {"metric": "refined_assigned_chains", "value": int(refined_assigned.sum())},
        {"metric": "refined_assigned_bins", "value": int(refined.loc[refined_assigned, "bin_count"].sum())},
        {"metric": "newly_assigned_chains", "value": int(len(newly_assigned))},
        {"metric": "newly_assigned_bins", "value": int(newly_assigned["bin_count"].sum())},
        {"metric": "still_unresolved_chains", "value": int(len(still_unresolved))},
        {"metric": "still_unresolved_bins", "value": int(still_unresolved["bin_count"].sum())},
        {"metric": "changed_chain_records", "value": int(len(changed))},
    ]
    transition = (
        refined.groupby(
            [
                "proposed_directionality_status",
                "proposed_directionality_method",
                "refined_directionality_status",
                "refined_directionality_method",
                "refined_rule_id",
            ],
            dropna=False,
        )
        .agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum"))
        .reset_index()
    )
    metric_df = pd.DataFrame(comparison_rows)
    metric_df["comparison_type"] = "metric"
    transition["comparison_type"] = "status_method_transition"
    write_csv("first_pass_vs_refined_comparison.csv", pd.concat([metric_df, transition], ignore_index=True, sort=False))

    write_csv("refined_directionality_method_summary.csv", summarize_counts(refined, ["refined_directionality_method"]))
    write_csv("refined_directionality_status_summary.csv", summarize_counts(refined, ["refined_directionality_status"]))

    bin_cols = ["logical_corridor_chain_id", "distance_band", "bin_length_ft"]
    bins = pd.read_parquet(BIN_CONTEXT, columns=bin_cols)
    assigned_chain_set = set(refined.loc[refined_assigned, "logical_corridor_chain_id"])
    bins["refined_assignment_status"] = bins["logical_corridor_chain_id"].isin(assigned_chain_set).map(
        {True: "assigned", False: "unresolved"}
    )
    band_summary = (
        bins.groupby(["refined_assignment_status", "distance_band"], dropna=False)
        .agg(bin_count=("logical_corridor_chain_id", "count"), total_bin_length_ft=("bin_length_ft", "sum"), chain_count=("logical_corridor_chain_id", "nunique"))
        .reset_index()
        .sort_values(["refined_assignment_status", "distance_band"])
    )
    write_csv("refined_bin_coverage_by_distance_band.csv", band_summary)

    fallback = refined[refined["proposed_directionality_status"].ne("assigned")].copy()
    fallback["first_pass_fallback_needed"] = fallback["bin_level_fallback_needed"].fillna(False)
    fallback["refined_chain_level_resolved"] = fallback["refined_directionality_status"].eq("assigned")
    fallback["refined_fallback_needed"] = fallback["refined_bin_level_fallback_needed"].fillna(False)
    fallback["fallback_analysis_reason"] = fallback.apply(
        lambda r: "resolved_by_refined_chain_rule"
        if r["refined_chain_level_resolved"]
        else ("true_segment_conflict_or_route_conflict" if r["refined_fallback_needed"] else "preserve_chain_unresolved_without_bin_split"),
        axis=1,
    )
    write_csv(
        "bin_level_fallback_analysis.csv",
        fallback[
            [
                "logical_corridor_chain_id",
                "stable_signal_id",
                "signal_approach_id",
                "bin_count",
                "pattern_family",
                "proposed_directionality_status",
                "refined_directionality_status",
                "refined_rule_id",
                "first_pass_fallback_needed",
                "refined_chain_level_resolved",
                "refined_fallback_needed",
                "fallback_analysis_reason",
            ]
        ],
    )

    write_csv("still_unresolved_chain_ledger.csv", still_unresolved.sort_values("bin_count", ascending=False))
    write_csv("high_impact_unresolved_chain_review.csv", still_unresolved.sort_values(["bin_count", "chain_total_reach_ft"], ascending=False).head(1000))
    write_csv("map_review_candidate_chains.csv", still_unresolved[still_unresolved["map_review_candidate_flag"].fillna(False)].sort_values("bin_count", ascending=False))

    used_columns = set(proposal.columns) | set(ac_cols) | set(bin_cols)
    crash_like = sorted([c for c in used_columns if "crash" in c.lower()])
    write_csv(
        "no_crash_direction_field_check.csv",
        [
            {
                "check_name": "no_crash_direction_fields_used",
                "used_field_count": len(crash_like),
                "used_fields": "|".join(crash_like),
                "pass": len(crash_like) == 0,
            }
        ],
    )

    context_like = sorted([c for c in used_columns if any(token in c.lower() for token in FORBIDDEN_CONTEXT_TOKENS)])
    safety_checks = {
        "proposal_one_row_per_chain": int(len(refined)) == int(refined["logical_corridor_chain_id"].nunique()),
        "refined_joinable_to_bins": set(refined["logical_corridor_chain_id"]).issuperset(set(bins["logical_corridor_chain_id"].unique())),
        "no_context_enrichment_fields_used": len(context_like) == 0,
        "no_crash_direction_fields_used": len(crash_like) == 0,
    }

    after_state = staged_file_state()
    mutation = before_state.merge(after_state, on="path", suffixes=("_before", "_after"))
    mutation["length_unchanged"] = mutation["length_before"].astype(str) == mutation["length_after"].astype(str)
    mutation["mtime_unchanged"] = mutation["mtime_ns_before"].astype(str) == mutation["mtime_ns_after"].astype(str)
    mutation["pass"] = mutation["exists_before"].eq(mutation["exists_after"]) & mutation["length_unchanged"] & mutation["mtime_unchanged"]
    write_csv("no_staged_mutation_check.csv", mutation)
    safety_checks["no_staged_mutation"] = bool(mutation["pass"].all())

    refined_assigned_chains = int(refined_assigned.sum())
    refined_assigned_bins = int(refined.loc[refined_assigned, "bin_count"].sum())
    still_unresolved_chains = int(len(still_unresolved))
    still_unresolved_bins = int(still_unresolved["bin_count"].sum())
    fallback_count = int(still_unresolved["refined_bin_level_fallback_needed"].fillna(False).sum())
    map_review_count = int(still_unresolved["map_review_candidate_flag"].fillna(False).sum())
    newly_assigned_bins = int(newly_assigned["bin_count"].sum())

    unresolved_bin_share = still_unresolved_bins / max(int(refined["bin_count"].sum()), 1)
    if not all(safety_checks.values()):
        decision = "directionality_blocked_by_insufficient_parent_evidence"
    elif still_unresolved_chains == 0:
        decision = "refined_chain_directionality_ready_for_bin_context_patch"
    elif unresolved_bin_share <= 0.02 and fallback_count <= 250:
        decision = "refined_chain_directionality_ready_with_small_review_ledger"
    elif map_review_count > 0 and newly_assigned_bins > 0:
        decision = "directionality_needs_targeted_map_review_sample"
    elif newly_assigned_bins > 0:
        decision = "directionality_needs_additional_rule_refinement"
    else:
        decision = "directionality_should_remain_partial_for_now"

    write_csv(
        "readiness_decision.csv",
        [
            {
                "decision": decision,
                "first_pass_assigned_chains": int(first_assigned.sum()),
                "first_pass_assigned_bins": int(proposal.loc[first_assigned, "bin_count"].sum()),
                "refined_assigned_chains": refined_assigned_chains,
                "refined_assigned_bins": refined_assigned_bins,
                "newly_assigned_chains": int(len(newly_assigned)),
                "newly_assigned_bins": newly_assigned_bins,
                "still_unresolved_chains": still_unresolved_chains,
                "still_unresolved_bins": still_unresolved_bins,
                "bin_level_fallback_needed_count": fallback_count,
                "map_review_candidate_count": map_review_count,
                "unresolved_bin_share": unresolved_bin_share,
            }
        ],
    )

    if decision in {"directionality_needs_targeted_map_review_sample", "directionality_needs_additional_rule_refinement"}:
        actions = [
            {"priority": 1, "recommended_next_action": "Run a targeted map-review/sample audit for remaining high-impact divided blank-token and reversible/trail chains."},
            {"priority": 2, "recommended_next_action": "Accept R1/R2/R3 as candidate chain-level rules only after review, then rerun proposal simulation."},
            {"priority": 3, "recommended_next_action": "Do not patch bin_context until the residual unresolved/fallback ledger is explicitly accepted or reduced."},
        ]
    elif decision == "refined_chain_directionality_ready_with_small_review_ledger":
        actions = [
            {"priority": 1, "recommended_next_action": "Prepare a read-only patch plan for accepted refined chain-level assignments and preserve the small review ledger."},
            {"priority": 2, "recommended_next_action": "Keep unresolved chains unassigned with explicit provenance."},
        ]
    else:
        actions = [
            {"priority": 1, "recommended_next_action": "Do not patch bin_context; parent evidence remains insufficient for safe broad directionality assignment."}
        ]
    write_csv("recommended_next_actions.csv", actions)

    findings = f"""# Chain Directionality Rule Refinement Audit

## Why This Audit Was Needed
The first-pass proposal assigned most chains but left {len(unresolved_ids):,} chains and {int(proposal.loc[proposal['proposed_directionality_status'] != 'assigned', 'bin_count'].sum()):,} bins unresolved. Because unresolved bins were fairly consistent across distance bands, the likely blocker was evidence/rule class rather than distance-band geometry.

## Main Unresolved Pattern Families
See `unresolved_pattern_audit.csv`. The largest families were mixed roadway-configuration evidence, blank divided/one-way token evidence, reversible/trail cases, and source-limited chains.

## Safe Rule Refinement Candidates
R1 assigns same-route mixed divided/undivided transitions when one carriageway token is consistent. R2 assigns one-way blank-token chains only when route/base/name text carries exactly one directional token. R3 preserves synthetic two-way undivided side assignment. These are simulation candidates only.

## Unsafe Rules
Divided blank-token chains without a route-text token remain unsafe because divided travel direction cannot be recovered from measure side alone. Reversible/trail cases remain unsafe without specialized/manual evidence.

## First-Pass Vs Refined Coverage
First pass assigned {int(first_assigned.sum()):,} chains and {int(proposal.loc[first_assigned, 'bin_count'].sum()):,} bins. The refined simulation assigns {refined_assigned_chains:,} chains and {refined_assigned_bins:,} bins, adding {int(len(newly_assigned)):,} chains and {newly_assigned_bins:,} bins.

## Bin-Level Fallback
Remaining fallback-needed chains: {fallback_count:,}. Many first-pass fallback cases were resolved by chain-level rules, so bin-level fallback should remain an exception path only.

## Remaining Unresolved Or Map Review Cases
Still unresolved: {still_unresolved_chains:,} chains and {still_unresolved_bins:,} bins. Map-review candidates: {map_review_count:,}. High-impact cases are ledgered in `high_impact_unresolved_chain_review.csv`.

## Safety Confirmations
No staged parquet or metadata was modified. No upstream/downstream or directionality fields were written. Crash direction fields and context enrichment fields were not used.

## Readiness
Decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    write_json(
        "manifest.json",
        {
            "created_utc": now(),
            "product": "chain_directionality_rule_refinement_audit",
            "bounded_question": "Why first-pass chains remained unresolved and which refinements are safe to simulate.",
            "source_inputs": [rel(path) for path in PARENTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "output_grain": "one row per logical_corridor_chain_id for refined proposal; supporting summaries by rule/pattern/band",
            "final_decision": decision,
            "mutation_policy": "read-only; no staged/canonical/source products modified",
        },
    )
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
            "checks": safety_checks,
        },
    )

    log(f"Rule refinement audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
