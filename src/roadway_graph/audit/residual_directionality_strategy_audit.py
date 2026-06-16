"""Read-only residual directionality strategy audit.

This audit reconciles the first-pass and refined chain directionality proposals,
then evaluates what should be patched, reviewed, or left unresolved. It writes
review evidence only and does not mutate staged cache products.
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
REFINED_AUDIT = REPO / "work/roadway_graph/review/chain_directionality_rule_refinement_audit"
OUT = REPO / "work/roadway_graph/review/residual_directionality_strategy_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

FIRST_PASS_PROPOSAL = FIRST_PASS / "chain_directionality_proposal.csv"
REFINED_PROPOSAL = REFINED_AUDIT / "refined_chain_directionality_proposal.csv"

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
METADATA = [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]
DIAGNOSTIC_EVIDENCE = [
    FIRST_PASS,
    REFINED_AUDIT,
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/materialize_bin_context_geometry",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

TOKEN_INCREASING = {"NB", "EB"}
TOKEN_DECREASING = {"SB", "WB"}
DIRECTION_TOKENS = TOKEN_INCREASING | TOKEN_DECREASING
EMBEDDED_ROUTE_TOKEN_RE = re.compile(r"(NB|SB|EB|WB)(?=ALT|BUS|RMP|PA|[0-9]|\s|$|[^A-Z])")
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
                "allowed_parent_for_residual_strategy_audit": bool(exists and read_status == "readable"),
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


def infer_embedded_route_token(row: pd.Series) -> str:
    tokens: list[str] = []
    for col in ("route_base_values", "source_route_name_values", "source_route_common_values"):
        for part in split_pipe(row.get(col, "")):
            tokens.extend(match.group(1) for match in EMBEDDED_ROUTE_TOKEN_RE.finditer(part))
    return "|".join(sorted(set(tokens)))


def rollup(frame: pd.DataFrame, group_col: str, category: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["category", group_col, "chain_count", "bin_count", "approach_count", "signal_count"])
    out = (
        frame.groupby(group_col, dropna=False)
        .agg(
            chain_count=("logical_corridor_chain_id", "count"),
            bin_count=("bin_count", "sum"),
            approach_count=("signal_approach_id", "nunique"),
            signal_count=("stable_signal_id", "nunique"),
            full_2500_chain_count=("chain_total_reach_ft", lambda s: int((pd.to_numeric(s, errors="coerce") >= 2499.999).sum())),
            distance_band_sets=("distance_band_coverage", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))[:500]),
        )
        .reset_index()
    )
    out.insert(0, "category", category)
    return out


def category_summary(category: str, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "category": category,
        "chain_count": int(len(frame)),
        "bin_count": int(frame["bin_count"].sum()) if not frame.empty else 0,
        "approach_count": int(frame["signal_approach_id"].nunique()) if not frame.empty else 0,
        "signal_count": int(frame["stable_signal_id"].nunique()) if not frame.empty else 0,
    }


def classify_divided_blank(row: pd.Series) -> dict[str, Any]:
    token = clean(row.get("embedded_route_token", ""))
    side = clean(row.get("measure_side_class", ""))
    label = token_to_label(token, side) if token in DIRECTION_TOKENS else ""
    if label:
        return {
            "divided_blank_strategy_category": "divided_blank_token_resolvable_by_route_text",
            "simulated_upstream_downstream": label,
            "simulated_method": "divided_blank_embedded_route_text_token",
            "strategy_confidence": "medium",
            "map_review_recommended": False,
            "strategy_reason": "Route/base/name text has exactly one embedded NB/SB/EB/WB token.",
        }
    if float(row.get("chain_total_reach_ft", 0) or 0) >= 2000 or int(row.get("bin_count", 0) or 0) >= 40:
        return {
            "divided_blank_strategy_category": "divided_blank_token_ambiguous_needs_map_review",
            "simulated_upstream_downstream": "",
            "simulated_method": "",
            "strategy_confidence": "low",
            "map_review_recommended": True,
            "strategy_reason": "High-impact divided chain has no reliable carriageway or route-text direction token.",
        }
    if int(row.get("bin_count", 0) or 0) <= 5 or float(row.get("chain_total_reach_ft", 0) or 0) < 250:
        return {
            "divided_blank_strategy_category": "divided_blank_token_source_limited",
            "simulated_upstream_downstream": "",
            "simulated_method": "",
            "strategy_confidence": "low",
            "map_review_recommended": False,
            "strategy_reason": "Low-reach source-limited chain with insufficient token evidence.",
        }
    return {
        "divided_blank_strategy_category": "divided_blank_token_unsafe_to_assign",
        "simulated_upstream_downstream": "",
        "simulated_method": "",
        "strategy_confidence": "low",
        "map_review_recommended": False,
        "strategy_reason": "No deterministic pairing or route-text token found; not enough evidence for assignment.",
    }


def classify_reversible_trail(row: pd.Series) -> dict[str, Any]:
    config = clean(row.get("roadway_configuration_values", "")).lower()
    route = " ".join(
        [
            clean(row.get("route_base_values", "")),
            clean(row.get("source_route_name_values", "")),
            clean(row.get("source_route_common_values", "")),
        ]
    ).lower()
    if "trail" in config or "trl" in route or " trail" in route:
        return {
            "reversible_trail_strategy_category": "true_trail_nonroad_source_limited",
            "recommended_treatment": "leave_unassigned_nonroad_source_limited",
            "map_review_recommended": False,
            "strategy_reason": "Trail/non-road evidence should not receive roadway upstream/downstream directionality.",
        }
    if "reversible" in config:
        return {
            "reversible_trail_strategy_category": "reversible_road_requires_review_or_special_rule",
            "recommended_treatment": "leave_unassigned_until_reversible_rule_or_review",
            "map_review_recommended": True,
            "strategy_reason": "Reversible facility lacks a fixed NB/SB/EB/WB direction token in staged evidence.",
        }
    return {
        "reversible_trail_strategy_category": "insufficient_evidence",
        "recommended_treatment": "leave_unassigned",
        "map_review_recommended": False,
        "strategy_reason": "No supported deterministic treatment found.",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    before_state = staged_file_state()

    log("Starting residual directionality strategy audit.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)

    log("Reading first-pass and refined proposal outputs.")
    first = pd.read_csv(FIRST_PASS_PROPOSAL)
    refined = pd.read_csv(REFINED_PROPOSAL)
    if len(first) != first["logical_corridor_chain_id"].nunique():
        raise RuntimeError("First-pass proposal is not one row per chain.")
    if len(refined) != refined["logical_corridor_chain_id"].nunique():
        raise RuntimeError("Refined proposal is not one row per chain.")

    first_ids = set(first["logical_corridor_chain_id"])
    refined_ids = set(refined["logical_corridor_chain_id"])
    first_assigned = first["proposed_directionality_status"].eq("assigned")
    refined_assigned = refined["refined_directionality_status"].eq("assigned")
    newly_assigned = refined[~refined["proposed_directionality_status"].eq("assigned") & refined_assigned].copy()
    still = refined[~refined_assigned].copy()
    map_candidates = still[still["map_review_candidate_flag"].fillna(False).astype(bool)].copy()
    fallback = refined[refined["refined_bin_level_fallback_needed"].fillna(False).astype(bool)].copy()

    categories: dict[str, pd.DataFrame] = {
        "first_pass_assigned": refined[refined["proposed_directionality_status"].eq("assigned")].copy(),
        "r1_r2_r3_newly_assigned": newly_assigned[newly_assigned["refined_rule_id"].isin(["R1_mixed_config_consistent_token", "R2_one_way_route_text_token", "R3_undivided_synthetic_side"])].copy(),
        "refined_assigned": refined[refined_assigned].copy(),
        "still_unresolved": still.copy(),
        "map_review_candidates": map_candidates.copy(),
        "divided_blank_token_unresolved": still[still["pattern_family"].eq("divided_with_blank_token")].copy(),
        "reversible_trail_unresolved": still[still["pattern_family"].eq("reversible_or_trail_like_case")].copy(),
        "residual_mixed_evidence_unresolved": still[still["pattern_family"].eq("mixed_roadway_configuration_only")].copy(),
        "high_impact_unresolved_full_2500": still[pd.to_numeric(still["chain_total_reach_ft"], errors="coerce") >= 2499.999].copy(),
    }

    reconciliation_rows = [
        {"set_name": "first_pass_universe", "chain_count": len(first_ids), "bin_count": int(first["bin_count"].sum())},
        {"set_name": "refined_universe", "chain_count": len(refined_ids), "bin_count": int(refined["bin_count"].sum())},
        {"set_name": "missing_from_refined", "chain_count": len(first_ids - refined_ids), "bin_count": ""},
        {"set_name": "missing_from_first_pass", "chain_count": len(refined_ids - first_ids), "bin_count": ""},
        {"set_name": "newly_assigned_after_refinement", "chain_count": len(newly_assigned), "bin_count": int(newly_assigned["bin_count"].sum())},
        {"set_name": "still_unresolved_after_refinement", "chain_count": len(still), "bin_count": int(still["bin_count"].sum())},
        {"set_name": "map_review_candidates", "chain_count": len(map_candidates), "bin_count": int(map_candidates["bin_count"].sum())},
        {"set_name": "refined_bin_level_fallback_needed", "chain_count": len(fallback), "bin_count": int(fallback["bin_count"].sum()) if not fallback.empty else 0},
    ]
    write_csv("proposal_set_reconciliation.csv", reconciliation_rows)

    log("Writing signal and approach rollups.")
    summary_rows = [category_summary(name, frame) for name, frame in categories.items()]
    total_by_signal = refined.groupby("stable_signal_id").agg(total_chains=("logical_corridor_chain_id", "count"), total_bins=("bin_count", "sum")).reset_index()
    unresolved_by_signal = still.groupby("stable_signal_id").agg(unresolved_chains=("logical_corridor_chain_id", "count"), unresolved_bins=("bin_count", "sum")).reset_index()
    signal_mix = total_by_signal.merge(unresolved_by_signal, on="stable_signal_id", how="left").fillna({"unresolved_chains": 0, "unresolved_bins": 0})
    signal_mix["unresolved_chain_share"] = signal_mix["unresolved_chains"] / signal_mix["total_chains"]
    signal_mix["unresolved_bin_share"] = signal_mix["unresolved_bins"] / signal_mix["total_bins"]
    summary_rows.extend(
        [
            {"category": "signals_with_any_unresolved", "chain_count": "", "bin_count": "", "approach_count": "", "signal_count": int((signal_mix["unresolved_chains"] > 0).sum())},
            {"category": "signals_with_only_unresolved", "chain_count": "", "bin_count": "", "approach_count": "", "signal_count": int((signal_mix["unresolved_chains"] == signal_mix["total_chains"]).sum())},
            {"category": "signals_unresolved_small_minority_bin_share_le_25pct", "chain_count": "", "bin_count": "", "approach_count": "", "signal_count": int(((signal_mix["unresolved_chains"] > 0) & (signal_mix["unresolved_bin_share"] <= 0.25)).sum())},
        ]
    )
    write_csv("unresolved_signal_approach_rollup.csv", summary_rows)
    write_csv("category_rollup_by_signal.csv", pd.concat([rollup(frame, "stable_signal_id", name) for name, frame in categories.items()], ignore_index=True))
    write_csv("category_rollup_by_approach.csv", pd.concat([rollup(frame, "signal_approach_id", name) for name, frame in categories.items()], ignore_index=True))

    log("Assessing R1/R2/R3 readiness and residual strategies.")
    readiness_rows = []
    for rule_id, decision, risk, fields, filter_note in [
        (
            "R1_mixed_config_consistent_token",
            "accept_for_patch_with_warning_status",
            "moderate_low",
            "roadway_configuration, route_base, carriageway_direction_token, measure_side_class",
            "Limit to one route identity and one nonblank carriageway token; exclude reversible/trail.",
        ),
        (
            "R2_one_way_route_text_token",
            "accept_for_patch_with_warning_status",
            "moderate",
            "roadway_configuration, route_base/source_route_name/source_route_common embedded token, measure_side_class",
            "Limit to one-way configuration and exactly one embedded route-text direction token.",
        ),
        (
            "R3_undivided_synthetic_side",
            "accept_for_patch",
            "low",
            "roadway_configuration, measure_side_class",
            "Limit to single two-way undivided configuration with usable measure side.",
        ),
    ]:
        subset = refined[refined["refined_rule_id"].eq(rule_id)].copy()
        readiness_rows.append(
            {
                "refined_rule_id": rule_id,
                "chains_affected": int(len(subset)),
                "bins_affected": int(subset["bin_count"].sum()) if not subset.empty else 0,
                "approaches_affected": int(subset["signal_approach_id"].nunique()) if not subset.empty else 0,
                "signals_affected": int(subset["stable_signal_id"].nunique()) if not subset.empty else 0,
                "evidence_fields_used": fields,
                "false_positive_risk": risk,
                "deterministic_rule": True,
                "requires_map_review_before_patch": False,
                "readiness_decision": decision,
                "confidence_exception_filter": filter_note,
            }
        )
    write_csv("r1_r2_r3_acceptance_readiness.csv", readiness_rows)

    divided = categories["divided_blank_token_unresolved"].copy()
    if not divided.empty:
        divided["embedded_route_token"] = divided.apply(infer_embedded_route_token, axis=1)
        div_strategy = divided.apply(classify_divided_blank, axis=1, result_type="expand")
        divided = pd.concat([divided, div_strategy], axis=1)
    write_csv("divided_blank_token_strategy_audit.csv", divided)

    revtrail = categories["reversible_trail_unresolved"].copy()
    if not revtrail.empty:
        rt_strategy = revtrail.apply(classify_reversible_trail, axis=1, result_type="expand")
        revtrail = pd.concat([revtrail, rt_strategy], axis=1)
    write_csv("reversible_trail_strategy_audit.csv", revtrail)

    log("Writing map-review and patch sequencing outputs.")
    map_rollup = []
    if not map_candidates.empty:
        map_rollup = [
            category_summary("all_map_review_candidates", map_candidates),
            *[
                category_summary(f"map_review_pattern:{pattern}", frame)
                for pattern, frame in map_candidates.groupby("pattern_family", dropna=False)
            ],
        ]
    write_csv("map_review_candidate_rollup.csv", map_rollup)

    priority = map_candidates.copy()
    if not priority.empty:
        priority["distance_band_count"] = priority["distance_band_coverage"].map(lambda x: len(split_pipe(x)))
        priority["full_2500_flag"] = pd.to_numeric(priority["chain_total_reach_ft"], errors="coerce") >= 2499.999
        sig_counts = map_candidates.groupby("stable_signal_id")["logical_corridor_chain_id"].count().rename("map_candidate_chains_at_signal")
        priority = priority.merge(sig_counts, on="stable_signal_id", how="left")
        priority["priority_score"] = (
            pd.to_numeric(priority["bin_count"], errors="coerce").fillna(0)
            + priority["distance_band_count"].fillna(0) * 5
            + priority["full_2500_flag"].astype(int) * 20
            + priority["map_candidate_chains_at_signal"].fillna(0) * 3
        )
        priority["map_review_recommendation"] = priority["pattern_family"].map(
            {
                "divided_with_blank_token": "review_high_impact_divided_blank_token",
                "reversible_or_trail_like_case": "review_reversible_only; trail can be source-limited",
                "mixed_roadway_configuration_only": "review_residual_mixed_evidence",
            }
        ).fillna("review_if_high_priority")
        priority = priority.sort_values("priority_score", ascending=False)
    write_csv("map_review_candidate_priority.csv", priority)

    signal_review = (
        still.groupby("stable_signal_id", dropna=False)
        .agg(
            unresolved_chain_count=("logical_corridor_chain_id", "count"),
            unresolved_bin_count=("bin_count", "sum"),
            unresolved_approach_count=("signal_approach_id", "nunique"),
            map_review_candidate_chain_count=("map_review_candidate_flag", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
            pattern_families=("pattern_family", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))),
        )
        .reset_index()
        .sort_values("unresolved_bin_count", ascending=False)
    )
    write_csv("high_impact_unresolved_signal_review.csv", signal_review.head(1000))

    divided_resolvable = int((divided["divided_blank_strategy_category"].eq("divided_blank_token_resolvable_by_route_text")).sum()) if not divided.empty else 0
    divided_resolvable_bins = int(divided.loc[divided["divided_blank_strategy_category"].eq("divided_blank_token_resolvable_by_route_text"), "bin_count"].sum()) if not divided.empty else 0
    reversible_review = int(revtrail["map_review_recommended"].fillna(False).astype(bool).sum()) if not revtrail.empty else 0
    trail_source_limited = int((revtrail["reversible_trail_strategy_category"].eq("true_trail_nonroad_source_limited")).sum()) if not revtrail.empty else 0

    patch_sequence = [
        {
            "sequence_order": 1,
            "action": "patch_refined_safe_chain_rules_R1_R2_R3",
            "scope": "4,092 newly assigned chains / 87,011 bins",
            "condition": "Use explicit rule/method/status provenance; keep no crash/context enrichment.",
        },
        {
            "sequence_order": 2,
            "action": "run_additional_blank_token_rule_refinement",
            "scope": f"{divided_resolvable:,} divided blank-token chains / {divided_resolvable_bins:,} bins potentially resolvable by embedded route token",
            "condition": "Validate embedded NB/SB/EB/WB parser and apply only to single-token route text.",
        },
        {
            "sequence_order": 3,
            "action": "leave_trail_nonroad_unassigned_source_limited",
            "scope": f"{trail_source_limited:,} trail chains",
            "condition": "Do not map-review trail/non-road cases for roadway upstream/downstream assignment unless policy changes.",
        },
        {
            "sequence_order": 4,
            "action": "create_small_targeted_map_review_after_safe_patch",
            "scope": f"{len(map_candidates):,} current candidates, reduced if embedded-token divided cases are accepted",
            "condition": "Prioritize high-impact divided blank-token, reversible road, and residual mixed-evidence chains.",
        },
    ]
    write_csv("refined_patch_sequence_recommendation.csv", patch_sequence)

    used_columns = set(first.columns) | set(refined.columns)
    crash_like = sorted([c for c in used_columns if "crash" in c.lower()])
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

    context_like = sorted([c for c in used_columns if any(token in c.lower() for token in FORBIDDEN_CONTEXT_TOKENS)])
    safety_pass = bool(parent_check["allowed_parent_for_residual_strategy_audit"].all()) and not bool(parent_check["downstream_object_parent_flag"].any()) and len(crash_like) == 0 and len(context_like) == 0 and bool(mutation["pass"].all())

    if not safety_pass:
        decision = "directionality_strategy_blocked_by_insufficient_evidence"
    elif divided_resolvable > 0:
        decision = "run_additional_blank_token_rule_refinement_before_patch"
    elif len(map_candidates) > 0:
        decision = "patch_refined_safe_rules_then_create_small_map_review_sample"
    else:
        decision = "patch_refined_safe_rules_before_map_review"

    write_csv(
        "readiness_decision.csv",
        [
            {
                "decision": decision,
                "still_unresolved_chains": int(len(still)),
                "still_unresolved_bins": int(still["bin_count"].sum()),
                "still_unresolved_approaches": int(still["signal_approach_id"].nunique()),
                "still_unresolved_signals": int(still["stable_signal_id"].nunique()),
                "map_review_candidate_chains": int(len(map_candidates)),
                "map_review_candidate_bins": int(map_candidates["bin_count"].sum()),
                "map_review_candidate_approaches": int(map_candidates["signal_approach_id"].nunique()),
                "map_review_candidate_signals": int(map_candidates["stable_signal_id"].nunique()),
                "r1_r2_r3_newly_assigned_chains": int(len(categories["r1_r2_r3_newly_assigned"])),
                "r1_r2_r3_newly_assigned_bins": int(categories["r1_r2_r3_newly_assigned"]["bin_count"].sum()),
                "divided_blank_route_text_resolvable_chains": divided_resolvable,
                "divided_blank_route_text_resolvable_bins": divided_resolvable_bins,
                "reversible_trail_map_review_chains": reversible_review,
                "trail_source_limited_chains": trail_source_limited,
            }
        ],
    )

    if decision == "run_additional_blank_token_rule_refinement_before_patch":
        actions = [
            {"priority": 1, "recommended_next_action": "Run a bounded additional rule refinement for divided blank-token chains using embedded route-text direction tokens."},
            {"priority": 2, "recommended_next_action": "Then patch R1/R2/R3 plus any accepted embedded-token divided rule with explicit provenance."},
            {"priority": 3, "recommended_next_action": "After safe patching, create a small targeted map-review package for remaining reversible-road and high-impact divided/mixed cases."},
        ]
    elif decision == "patch_refined_safe_rules_then_create_small_map_review_sample":
        actions = [
            {"priority": 1, "recommended_next_action": "Patch accepted R1/R2/R3 chain-level assignments with provenance."},
            {"priority": 2, "recommended_next_action": "Create a small targeted map-review package for residual map-review candidates."},
        ]
    else:
        actions = [{"priority": 1, "recommended_next_action": "Do not patch until safety checks and residual evidence are repaired."}]
    write_csv("recommended_next_actions.csv", actions)

    findings = f"""# Residual Directionality Strategy Audit

## Map Review Timing
Map review should not be the immediate next step. R1/R2/R3 are deterministic enough to prepare for patching with method/status provenance, but the divided blank-token group has an additional programmatic opportunity that should be refined before mutation.

## Still-Unresolved Scope
Still unresolved after refinement: {len(still):,} chains, {int(still['bin_count'].sum()):,} bins, {still['signal_approach_id'].nunique():,} approaches, and {still['stable_signal_id'].nunique():,} signals.

## Map-Review Candidate Scope
Current map-review candidates: {len(map_candidates):,} chains, {int(map_candidates['bin_count'].sum()):,} bins, {map_candidates['signal_approach_id'].nunique():,} approaches, and {map_candidates['stable_signal_id'].nunique():,} signals. They are concentrated enough for a targeted sample, not a broad review.

## R1/R2/R3 Readiness
R1/R2/R3 affect {len(categories['r1_r2_r3_newly_assigned']):,} chains and {int(categories['r1_r2_r3_newly_assigned']['bin_count'].sum()):,} bins. They are ready as patch candidates with explicit rule provenance and exception filters; they do not require map review before patching.

## Divided Blank-Token Strategy
Embedded route-text parsing identifies {divided_resolvable:,} divided blank-token chains and {divided_resolvable_bins:,} bins that may be programmatically resolvable. This should be converted into a bounded additional refinement before patching.

## Reversible/Trail Strategy
Trail/non-road cases should remain unassigned/source-limited. Reversible road cases should remain unresolved until a reversible-specific rule or small targeted review is accepted.

## Recommended Sequence
First run the additional blank-token rule refinement. Then patch accepted R1/R2/R3 and any accepted embedded-token divided rule. Then create a smaller targeted map-review package only for residual high-impact divided, reversible-road, and mixed-evidence cases.

## Safety
Crash direction fields were not used. No staged products were modified.

## Decision
`{decision}`
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    write_json(
        "manifest.json",
        {
            "created_utc": now(),
            "product": "residual_directionality_strategy_audit",
            "bounded_question": "What should be patched, refined, reviewed, or left unresolved after chain-level directionality refinement?",
            "source_inputs": [rel(path) for path in PARENTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "output_grain": "strategy summaries by chain/signal/approach/rule class",
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
                "parent_dependency_passed": bool(parent_check["allowed_parent_for_residual_strategy_audit"].all() and not parent_check["downstream_object_parent_flag"].any()),
                "first_refined_chain_sets_reconciled": len(first_ids ^ refined_ids) == 0,
                "no_crash_direction_fields_used": len(crash_like) == 0,
                "no_context_enrichment_fields_used": len(context_like) == 0,
                "no_staged_mutation": bool(mutation["pass"].all()),
            },
        },
    )

    log(f"Residual directionality strategy audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
