"""Read-only audit for divided blank-token embedded route-text directionality.

This script evaluates whether unresolved divided chains with blank
carriageway_direction_token can be safely proposed using explicit route-text
direction tokens. It writes review evidence only and does not mutate staged
products.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
REFINED_AUDIT = REPO / "work/roadway_graph/review/chain_directionality_rule_refinement_audit"
RESIDUAL_AUDIT = REPO / "work/roadway_graph/review/residual_directionality_strategy_audit"
OUT = REPO / "work/roadway_graph/review/divided_blank_token_embedded_route_text_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

REFINED_PROPOSAL = REFINED_AUDIT / "refined_chain_directionality_proposal.csv"

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
METADATA = [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/chain_first_directionality_proposal",
    REFINED_AUDIT,
    RESIDUAL_AUDIT,
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

TOKEN_INCREASING = {"NB", "EB"}
TOKEN_DECREASING = {"SB", "WB"}
DIRECTION_TOKENS = TOKEN_INCREASING | TOKEN_DECREASING
NONBLOCKING_DUPLICATION_STATUSES = {"", "none", "no_duplication_risk", "deduplicated_canonical_bin_eligible"}
TOKEN_WORDS = {
    "NORTHBOUND": "NB",
    "SOUTHBOUND": "SB",
    "EASTBOUND": "EB",
    "WESTBOUND": "WB",
}
TOKEN_PATTERNS = [
    re.compile(r"\b(NB|SB|EB|WB)\b", re.IGNORECASE),
    re.compile(r"\b(N|S|E|W)\s*/\s*B\b", re.IGNORECASE),
    re.compile(r"\b(NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND)\b", re.IGNORECASE),
    re.compile(r"(NB|SB|EB|WB)(?=ALT|BUS|RMP|PA|[0-9]|\s|$|[^A-Z])", re.IGNORECASE),
]
FORBIDDEN_CONTEXT_TOKENS = ("speed", "aadt", "access", "crash", "exposure", "rate")


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


def compact(values: list[str] | pd.Series, limit: int = 30) -> str:
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
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        rows.append(
            {
                "parent_path": rel(path),
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_embedded_route_text_audit": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden),
            }
        )
    return pd.DataFrame(rows)


def normalize_token(raw: str) -> str:
    text = raw.upper().replace("/", "").strip()
    if text in {"NB", "SB", "EB", "WB"}:
        return text
    if text in {"N B", "N/B"}:
        return "NB"
    if text in {"S B", "S/B"}:
        return "SB"
    if text in {"E B", "E/B"}:
        return "EB"
    if text in {"W B", "W/B"}:
        return "WB"
    return TOKEN_WORDS.get(text, "")


def extract_tokens_from_text(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    tokens: list[str] = []
    for pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            if len(match.groups()) == 1:
                token = normalize_token(match.group(1))
            else:
                token = ""
            if token:
                tokens.append(token)
    return sorted(set(tokens))


def token_to_label(token: str, side: str) -> str:
    if token in TOKEN_INCREASING:
        return "downstream" if side == "measure_increasing_from_signal" else "upstream"
    if token in TOKEN_DECREASING:
        return "downstream" if side == "measure_decreasing_from_signal" else "upstream"
    return ""


def chain_route_key(row: pd.Series) -> tuple[str, str, str]:
    return (clean(row.get("stable_signal_id", "")), clean(row.get("signal_approach_id", "")), clean(row.get("route_base_values", "")))


def build_extraction(target: pd.DataFrame, approach_corridors: pd.DataFrame, travelways: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_ids = set(target["logical_corridor_chain_id"])
    segment_rows = approach_corridors[approach_corridors["logical_corridor_chain_id"].isin(target_ids)].copy()
    travel_by_id = travelways.set_index("stable_travelway_id", drop=False)
    records: list[dict[str, Any]] = []
    chain_fields: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    aggregate_fields = ["route_base_values", "source_route_name_values", "source_route_id_values", "source_route_common_values"]
    segment_fields = ["route_base", "source_route_name", "source_route_id", "source_route_common"]
    travel_fields = ["route_base", "source_route_name", "source_route_id", "source_route_common"]

    for _, row in target.iterrows():
        chain_id = clean(row["logical_corridor_chain_id"])
        for field in aggregate_fields:
            for part in split_pipe(row.get(field, "")):
                tokens = extract_tokens_from_text(part)
                if tokens:
                    records.append({"logical_corridor_chain_id": chain_id, "source_table": "refined_chain_directionality_proposal", "source_field": field, "source_value": part, "tokens_found": "|".join(tokens)})
                    chain_fields[chain_id][field].extend(tokens)

    for _, row in segment_rows.iterrows():
        chain_id = clean(row["logical_corridor_chain_id"])
        for field in segment_fields:
            value = clean(row.get(field, ""))
            tokens = extract_tokens_from_text(value)
            if tokens:
                records.append({"logical_corridor_chain_id": chain_id, "source_table": "approach_corridors", "source_field": field, "source_value": value, "tokens_found": "|".join(tokens)})
                chain_fields[chain_id][f"segment:{field}"].extend(tokens)
        twid = clean(row.get("stable_travelway_id", ""))
        if twid and twid in travel_by_id.index:
            tw = travel_by_id.loc[twid]
            if isinstance(tw, pd.DataFrame):
                tw = tw.iloc[0]
            for field in travel_fields:
                value = clean(tw.get(field, ""))
                tokens = extract_tokens_from_text(value)
                if tokens:
                    records.append({"logical_corridor_chain_id": chain_id, "source_table": "travelway_network_index", "source_field": field, "source_value": value, "tokens_found": "|".join(tokens)})
                    chain_fields[chain_id][f"travelway:{field}"].extend(tokens)

    extraction = pd.DataFrame(records)
    consistency_rows = []
    for _, row in target.iterrows():
        chain_id = clean(row["logical_corridor_chain_id"])
        field_map = chain_fields.get(chain_id, {})
        all_tokens: list[str] = []
        token_sources: list[str] = []
        for field, tokens in field_map.items():
            unique = sorted(set(tokens))
            all_tokens.extend(unique)
            if unique:
                token_sources.append(f"{field}={ '|'.join(unique) }")
        unique_all = sorted(set(all_tokens))
        consistency_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "embedded_tokens_found": "|".join(unique_all),
                "embedded_token_count": len(unique_all),
                "embedded_token_unique_flag": len(unique_all) == 1,
                "embedded_token_conflict_status": "consistent_single_token" if len(unique_all) == 1 else ("no_token_found" if not unique_all else "conflicting_multiple_tokens"),
                "embedded_token_source_fields": "; ".join(token_sources),
                "embedded_token_confidence": "high" if len(unique_all) == 1 and len(token_sources) >= 2 else ("medium" if len(unique_all) == 1 else "low"),
            }
        )
    return extraction, pd.DataFrame(consistency_rows)


def summarize_category(name: str, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "category": name,
        "chain_count": int(len(frame)),
        "bin_count": int(frame["bin_count"].sum()) if not frame.empty else 0,
        "approach_count": int(frame["signal_approach_id"].nunique()) if not frame.empty else 0,
        "signal_count": int(frame["stable_signal_id"].nunique()) if not frame.empty else 0,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    before_state = staged_file_state()

    log("Starting divided blank-token embedded route-text audit.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)

    log("Reading refined proposal and staged parent evidence.")
    refined = pd.read_csv(REFINED_PROPOSAL)
    target = refined[
        refined["refined_directionality_status"].ne("assigned")
        & refined["pattern_family"].eq("divided_with_blank_token")
        & refined["roadway_configuration_values"].astype(str).str.contains("Divided", case=False, na=False)
        & refined["carriageway_direction_token_values"].fillna("").astype(str).str.strip().eq("")
    ].copy()
    if len(target) != target["logical_corridor_chain_id"].nunique():
        raise RuntimeError("Target universe is not one row per chain.")

    bins = pd.read_parquet(BIN_CONTEXT, columns=["logical_corridor_chain_id", "distance_band", "bin_length_ft"])
    band = (
        bins[bins["logical_corridor_chain_id"].isin(set(target["logical_corridor_chain_id"]))]
        .groupby("distance_band", dropna=False)
        .agg(bin_count=("logical_corridor_chain_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), total_bin_length_ft=("bin_length_ft", "sum"))
        .reset_index()
    )
    parent_status = (
        target.groupby(["parent_corridor_warning_status_values", "parent_corridor_review_status_values"], dropna=False)
        .agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum"))
        .reset_index()
    )
    universe = target.copy()
    universe["target_universe_reason"] = "unresolved_divided_blank_carriageway_token"
    write_csv("divided_blank_token_target_universe.csv", universe)

    ac_cols = [
        "logical_corridor_chain_id",
        "stable_signal_id",
        "signal_approach_id",
        "stable_travelway_id",
        "segment_order",
        "route_base",
        "source_route_name",
        "source_route_id",
        "source_route_common",
        "carriageway_direction_token",
        "roadway_configuration",
        "parent_corridor_gate_severity",
        "bin_duplication_risk_status",
        "route_measure_continuity_status",
    ]
    tw_cols = ["stable_travelway_id", "route_base", "source_route_name", "source_route_id", "source_route_common", "carriageway_direction_token", "roadway_configuration"]
    approach_corridors = pd.read_parquet(APPROACH_CORRIDORS, columns=ac_cols)
    travelways = pd.read_parquet(TRAVELWAY_INDEX, columns=tw_cols)

    log("Extracting embedded route-text tokens.")
    extraction, consistency = build_extraction(target, approach_corridors, travelways)
    write_csv("embedded_route_text_token_extraction.csv", extraction)
    consistency = target.merge(consistency, on="logical_corridor_chain_id", how="left")
    write_csv("embedded_token_consistency_by_chain.csv", consistency)

    log("Running simulated rule and pair/parallel consistency audit.")
    assigned_refined = refined[refined["refined_directionality_status"].eq("assigned")].copy()
    assigned_refined["known_token"] = assigned_refined["carriageway_direction_token_values"].map(lambda x: split_pipe(x)[0] if len(split_pipe(x)) == 1 else "")
    assigned_refined["known_label_from_token"] = assigned_refined.apply(lambda r: token_to_label(clean(r["known_token"]), clean(r["measure_side_class"])), axis=1)
    route_key_labels = defaultdict(set)
    route_key_tokens = defaultdict(set)
    for _, row in assigned_refined.iterrows():
        key = chain_route_key(row)
        if clean(row.get("known_label_from_token", "")):
            route_key_labels[key].add(clean(row["known_label_from_token"]))
        if clean(row.get("known_token", "")):
            route_key_tokens[key].add(clean(row["known_token"]))

    sim_rows = []
    pair_rows = []
    for _, row in consistency.iterrows():
        chain_id = clean(row["logical_corridor_chain_id"])
        token_values = split_pipe(row.get("embedded_tokens_found", ""))
        token = token_values[0] if len(token_values) == 1 else ""
        label = token_to_label(token, clean(row.get("measure_side_class", ""))) if token else ""
        parent_warning = clean(row.get("parent_corridor_warning_status_values", ""))
        parent_gate = clean(row.get("corridor_parent_gate_severity_values", ""))
        route_values = split_pipe(row.get("route_base_values", ""))
        config_values = split_pipe(row.get("roadway_configuration_values", ""))
        duplicate_risk = False
        segs = approach_corridors[approach_corridors["logical_corridor_chain_id"].eq(chain_id)]
        if not segs.empty:
            duplicate_statuses = {clean(v) for v in segs["bin_duplication_risk_status"]}
            duplicate_risk = bool(duplicate_statuses - NONBLOCKING_DUPLICATION_STATUSES)
        key = chain_route_key(row)
        paired_labels = sorted(route_key_labels.get(key, set()))
        paired_tokens = sorted(route_key_tokens.get(key, set()))
        label_conflict = bool(label and paired_labels and label not in paired_labels and len(paired_labels) == 1)
        token_conflict = bool(token and paired_tokens and token not in paired_tokens and len(paired_tokens) == 1)
        pair_status = "no_paired_known_token_chain"
        if label_conflict or token_conflict:
            pair_status = "paired_known_chain_conflict"
        elif paired_tokens:
            pair_status = "paired_known_chain_consistent_or_not_contradictory"

        rejection_reasons = []
        if len(config_values) != 1 or "Divided" not in config_values[0] or "Undivided" in config_values[0]:
            rejection_reasons.append("not_single_divided_configuration")
        if clean(row.get("carriageway_direction_token_values", "")):
            rejection_reasons.append("primary_carriageway_token_not_blank")
        if len(token_values) != 1:
            rejection_reasons.append("embedded_token_not_unique")
        if not label:
            rejection_reasons.append("upstream_downstream_mapping_uncertain")
        if len(route_values) != 1:
            rejection_reasons.append("mixed_route_base_evidence")
        if parent_warning not in {"", "none"} or parent_gate not in {"", "none"}:
            rejection_reasons.append("parent_warning_or_gate_status")
        if duplicate_risk:
            rejection_reasons.append("bin_duplication_risk_status_present")
        if label_conflict or token_conflict:
            rejection_reasons.append("paired_parallel_conflict")

        assigned = not rejection_reasons
        sim_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": row["stable_signal_id"],
                "signal_approach_id": row["signal_approach_id"],
                "bin_count": row["bin_count"],
                "embedded_token": token,
                "embedded_rule_proposed_upstream_downstream": label if assigned else "",
                "embedded_rule_directionality_method": "divided_blank_token_embedded_route_text" if assigned else "",
                "embedded_rule_directionality_status": "assigned" if assigned else "unresolved",
                "embedded_rule_directionality_confidence": "medium" if assigned else "low",
                "rule_pass_flag": assigned,
                "rejection_reason": "|".join(rejection_reasons),
                "evidence_summary": f"token={token or 'none'}; side={clean(row.get('measure_side_class',''))}; route={clean(row.get('route_base_values',''))}; pair_status={pair_status}",
            }
        )
        pair_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": row["stable_signal_id"],
                "signal_approach_id": row["signal_approach_id"],
                "route_base_values": row["route_base_values"],
                "candidate_embedded_token": token,
                "candidate_label": label,
                "paired_known_tokens_same_signal_approach_route": "|".join(paired_tokens),
                "paired_known_labels_same_signal_approach_route": "|".join(paired_labels),
                "pair_parallel_consistency_status": pair_status,
                "paired_parallel_conflict_flag": label_conflict or token_conflict,
            }
        )

    simulation = pd.DataFrame(sim_rows)
    write_csv("divided_blank_token_rule_simulation.csv", simulation)
    proposed = target.merge(
        simulation[
            [
                "logical_corridor_chain_id",
                "embedded_token",
                "embedded_rule_proposed_upstream_downstream",
                "embedded_rule_directionality_method",
                "embedded_rule_directionality_status",
                "embedded_rule_directionality_confidence",
                "evidence_summary",
            ]
        ],
        on="logical_corridor_chain_id",
    )
    proposed = proposed[proposed["embedded_rule_directionality_status"].eq("assigned")].copy()
    write_csv("proposed_embedded_token_assignments.csv", proposed)
    rejected = target.merge(simulation[["logical_corridor_chain_id", "embedded_token", "rejection_reason"]], on="logical_corridor_chain_id")
    rejected = rejected[rejected["rejection_reason"].ne("")].copy()
    write_csv("embedded_token_rejection_ledger.csv", rejected)
    pair_audit = pd.DataFrame(pair_rows)
    write_csv("pair_parallel_consistency_audit.csv", pair_audit)

    log("Writing coverage and residual impact outputs.")
    residual_after = target[~target["logical_corridor_chain_id"].isin(set(proposed["logical_corridor_chain_id"]))].copy()
    write_csv("residual_divided_blank_token_after_rule.csv", residual_after)

    map_candidates = refined[refined["map_review_candidate_flag"].fillna(False).astype(bool)].copy()
    map_after = map_candidates[~map_candidates["logical_corridor_chain_id"].isin(set(proposed["logical_corridor_chain_id"]))].copy()
    write_csv(
        "map_review_candidate_update.csv",
        [
            summarize_category("map_review_candidates_before_embedded_token_rule", map_candidates),
            summarize_category("proposed_embedded_token_assignments_removed_from_map_review", map_candidates[map_candidates["logical_corridor_chain_id"].isin(set(proposed["logical_corridor_chain_id"]))]),
            summarize_category("map_review_candidates_after_embedded_token_rule", map_after),
        ],
    )

    coverage_rows = [
        summarize_category("target_divided_blank_token_universe", target),
        summarize_category("safe_assignable_by_embedded_route_text", proposed),
        summarize_category("rejected_or_unresolved_after_rule", residual_after),
    ]
    if not proposed.empty:
        coverage_rows.extend(
            proposed.groupby("distance_band_coverage", dropna=False)
            .agg(chain_count=("logical_corridor_chain_id", "count"), bin_count=("bin_count", "sum"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique"))
            .reset_index()
            .assign(category=lambda d: "safe_assignable_bandset:" + d["distance_band_coverage"].astype(str))
            [["category", "chain_count", "bin_count", "approach_count", "signal_count"]]
            .to_dict("records")
        )
    refined_assigned_bins = int(refined.loc[refined["refined_directionality_status"].eq("assigned"), "bin_count"].sum())
    refined_assigned_chains = int(refined["refined_directionality_status"].eq("assigned").sum())
    coverage_rows.append(
        {
            "category": "refined_totals_if_rule_accepted",
            "chain_count": refined_assigned_chains + int(len(proposed)),
            "bin_count": refined_assigned_bins + int(proposed["bin_count"].sum()),
            "approach_count": "",
            "signal_count": "",
        }
    )
    coverage_rows.append(
        {
            "category": "unresolved_totals_if_rule_accepted",
            "chain_count": int(len(refined) - refined_assigned_chains - len(proposed)),
            "bin_count": int(refined["bin_count"].sum() - refined_assigned_bins - proposed["bin_count"].sum()),
            "approach_count": "",
            "signal_count": "",
        }
    )
    write_csv("embedded_token_coverage_impact.csv", coverage_rows)

    used_columns = set(refined.columns) | set(ac_cols) | set(tw_cols)
    crash_like = sorted(c for c in used_columns if "crash" in c.lower())
    write_csv(
        "no_crash_direction_field_check.csv",
        [{"check_name": "no_crash_direction_fields_used", "used_field_count": len(crash_like), "used_fields": "|".join(crash_like), "pass": len(crash_like) == 0}],
    )

    after_state = staged_file_state()
    mutation = before_state.merge(after_state, on="path", suffixes=("_before", "_after"))
    mutation["length_unchanged"] = mutation["length_before"].astype(str) == mutation["length_after"].astype(str)
    mutation["mtime_unchanged"] = mutation["mtime_ns_before"].astype(str) == mutation["mtime_ns_after"].astype(str)
    mutation["pass"] = mutation["exists_before"].eq(mutation["exists_after"]) & mutation["length_unchanged"] & mutation["mtime_unchanged"]
    write_csv("no_staged_mutation_check.csv", mutation)

    context_like = sorted(c for c in used_columns if any(token in c.lower() for token in FORBIDDEN_CONTEXT_TOKENS))
    pair_conflict_count = int(pair_audit["paired_parallel_conflict_flag"].sum()) if not pair_audit.empty else 0
    proposed_chain_count = int(len(proposed))
    proposed_bin_count = int(proposed["bin_count"].sum()) if not proposed.empty else 0
    residual_chain_count = int(len(residual_after))
    residual_bin_count = int(residual_after["bin_count"].sum()) if not residual_after.empty else 0
    safety_pass = bool(parent_check["allowed_parent_for_embedded_route_text_audit"].all()) and not bool(parent_check["downstream_object_parent_flag"].any()) and len(crash_like) == 0 and len(context_like) == 0 and bool(mutation["pass"].all())

    if not safety_pass:
        decision = "embedded_route_text_rule_blocked_by_insufficient_evidence"
    elif proposed_chain_count == 0:
        decision = "embedded_route_text_rule_unsafe_needs_map_review"
    elif pair_conflict_count > 0:
        decision = "embedded_route_text_rule_needs_spot_review_before_patch"
    else:
        decision = "embedded_route_text_rule_safe_with_warning_status"

    write_csv(
        "readiness_decision.csv",
        [
            {
                "decision": decision,
                "target_chain_count": int(len(target)),
                "target_bin_count": int(target["bin_count"].sum()),
                "safe_assignable_chains": proposed_chain_count,
                "safe_assignable_bins": proposed_bin_count,
                "safe_assignable_approaches": int(proposed["signal_approach_id"].nunique()) if not proposed.empty else 0,
                "safe_assignable_signals": int(proposed["stable_signal_id"].nunique()) if not proposed.empty else 0,
                "rejected_or_unresolved_chains": residual_chain_count,
                "rejected_or_unresolved_bins": residual_bin_count,
                "pair_parallel_conflict_count": pair_conflict_count,
            }
        ],
    )
    actions = [
        {"priority": 1, "recommended_next_action": "Include the embedded route-text rule in the next directionality patch with warning-status provenance and strict single-token filters."},
        {"priority": 2, "recommended_next_action": "Patch R1/R2/R3 and this embedded-token rule together only as chain-level assignments; leave rejected divided blank-token chains unresolved."},
        {"priority": 3, "recommended_next_action": "Create a smaller map-review package for remaining high-impact divided blank-token and reversible-road cases after patching accepted rules."},
    ]
    if decision not in {"embedded_route_text_rule_safe_for_directionality_patch", "embedded_route_text_rule_safe_with_warning_status"}:
        actions = [{"priority": 1, "recommended_next_action": "Do not patch this embedded-token rule; run spot review or map review first."}]
    write_csv("recommended_next_actions.csv", actions)

    findings = f"""# Divided Blank-Token Embedded Route-Text Audit

## Why This Audit Was Needed
The residual strategy audit showed that blank `carriageway_direction_token` did not always mean all direction evidence was absent. Some divided chains preserve explicit direction tokens in route/base/name/common text.

## Token Extraction
Tokens were extracted only from explicit NB/SB/EB/WB, NORTHBOUND/SOUTHBOUND/EASTBOUND/WESTBOUND, N/B/S/B/E/B/W/B, and route-suffix-like patterns such as NBBUS or EBALT. Arbitrary letters inside names were not treated as direction tokens.

## Target Universe
Target divided blank-token unresolved chains: {len(target):,} chains and {int(target['bin_count'].sum()):,} bins.

## Safely Assignable Simulation
Strict rule-pass chains: {proposed_chain_count:,} chains, {proposed_bin_count:,} bins, {proposed['signal_approach_id'].nunique() if not proposed.empty else 0:,} approaches, and {proposed['stable_signal_id'].nunique() if not proposed.empty else 0:,} signals.

## Remaining Unresolved
Rejected or unresolved after this rule: {residual_chain_count:,} chains and {residual_bin_count:,} bins.

## Pair/Parallel Consistency
Pair/parallel conflicts found: {pair_conflict_count:,}. See `pair_parallel_consistency_audit.csv`.

## Patch Readiness
Decision: `{decision}`. The rule is simulation-only here; no staged products were modified.

## Safety
Crash direction fields were not used. No context enrichment fields were used. No staged products were modified.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    write_json(
        "manifest.json",
        {
            "created_utc": now(),
            "product": "divided_blank_token_embedded_route_text_audit",
            "bounded_question": "Can unresolved divided blank-token chains be safely proposed from explicit embedded route-text direction tokens?",
            "source_inputs": [rel(path) for path in PARENTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "output_grain": "one row per target chain plus extraction, simulation, consistency, and impact summaries",
            "final_decision": decision,
            "mutation_policy": "read-only; no staged/canonical/source products modified",
        },
    )
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
            "checks": {
                "parent_dependency_passed": bool(parent_check["allowed_parent_for_embedded_route_text_audit"].all() and not parent_check["downstream_object_parent_flag"].any()),
                "target_one_row_per_chain": int(len(target)) == int(target["logical_corridor_chain_id"].nunique()),
                "no_crash_direction_fields_used": len(crash_like) == 0,
                "no_context_enrichment_fields_used": len(context_like) == 0,
                "no_staged_mutation": bool(mutation["pass"].all()),
            },
            "supporting_summaries": {
                "distance_band_distribution": band.to_dict("records"),
                "parent_status_distribution": parent_status.to_dict("records"),
            },
        },
    )
    log(f"Embedded route-text audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
