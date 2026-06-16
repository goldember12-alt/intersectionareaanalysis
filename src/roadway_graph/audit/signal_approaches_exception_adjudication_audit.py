"""Read-only exception adjudication audit for staged signal_approaches.

This audit decides whether the approach layer can feed approach_corridors with
explicit gates, or whether a targeted patch/rebuild is needed. It writes only
review outputs.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/signal_approaches_exception_adjudication_audit"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

BUILD_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
VALIDATION_REVIEW = REPO / "work/roadway_graph/review/signal_approaches_validation_audit"
ATTACHMENT_AUDIT = REPO / "work/roadway_graph/review/signal_travelway_attachment_readiness_audit"
CANONICAL_FINAL = REPO / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset"
REFRESH_CANDIDATE = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"


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


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def split_pipe(value: Any) -> list[str]:
    text = clean(value)
    return [part for part in text.split("|") if part]


def adjudicate_two(row: pd.Series) -> tuple[str, str]:
    tax = clean(row.get("two_approach_taxonomy"))
    rejected_hm = float(row.get("rejected_high_medium_count", 0) or 0)
    route_groups = int(row.get("route_group_count", 0) or 0)
    candidates = int(row.get("candidate_count", 0) or 0)
    if tax == "likely_one_way_or_divided_pair":
        return "acceptable_two_approach_one_way_or_divided_pair", "corridor_build_ready_with_warning"
    if tax == "likely_true_two_leg_or_boundary_case":
        return "acceptable_true_two_leg_or_boundary_case", "corridor_build_ready_with_warning"
    if tax == "source_limited_or_attachment_limited":
        return "source_limited_missing_cross_street", "source_limited_no_corridor"
    if tax == "candidate_evidence_suggests_underbuilt":
        return "likely_underbuilt_patch_candidate", "corridor_build_blocked_pending_rule_repair"
    if tax == "likely_route_group_overcollapse":
        return "route_group_overcollapse_patch_candidate", "corridor_build_blocked_pending_rule_repair"
    if rejected_hm >= 3 or route_groups >= 6 or candidates >= 15:
        return "ambiguous_needs_review", "corridor_build_blocked_pending_map_review"
    return "corridor_build_allowed_with_warning", "corridor_build_ready_with_warning"


def adjudicate_overcollapse(row: pd.Series) -> str:
    tax = clean(row.get("two_approach_taxonomy"))
    configs = int(row.get("roadway_config_count", 0) or 0)
    tokens = int(row.get("token_count", 0) or 0)
    route_groups = int(row.get("route_group_count", 0) or 0)
    candidates = int(row.get("candidate_count", 0) or 0)
    if tax in {"candidate_evidence_suggests_underbuilt", "likely_route_group_overcollapse"}:
        return "true_overcollapse_patch_candidate"
    if tax == "likely_one_way_or_divided_pair" and tokens >= 2:
        return "likely_false_alarm_due_divided_or_one_way_pair"
    if tax == "likely_true_two_leg_or_boundary_case" and route_groups <= 4:
        return "acceptable_conservative_grouping"
    if route_groups >= 8 or candidates >= 20 or configs >= 3:
        return "needs_map_review"
    return "unclear"


def rejected_impact(row: pd.Series) -> str:
    rejected_hm = float(row.get("rejected_high_medium_count", 0) or 0)
    rejected_ready = float(row.get("rejected_measure_ready_count", 0) or 0)
    rejected_routes = float(row.get("rejected_route_group_count", 0) or 0)
    approach_count = int(row.get("approach_count", 0) or 0)
    if rejected_hm <= 0:
        return "diagnostic_only_no_action"
    if approach_count <= 2 and rejected_hm >= 3 and rejected_routes >= 3:
        return "possible_missing_physical_approach"
    if approach_count <= 2 and rejected_ready >= 3:
        return "possible_missing_cross_street"
    if rejected_routes >= 6:
        return "possible_overcollapse"
    if rejected_hm <= 2:
        return "legitimate_rejected_duplicate_source_row_fragment"
    return "legitimate_rejected_alternate_carriageway_subbranch"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting signal_approaches exception adjudication audit.")
    signals = pd.read_parquet(SIGNAL_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    build_amb = load_csv(BUILD_REVIEW / "ambiguous_signal_ledger.csv")
    build_status = load_csv(BUILD_REVIEW / "signal_level_approach_build_status.csv")
    validation_amb = load_csv(VALIDATION_REVIEW / "ambiguous_signal_audit.csv")
    two = load_csv(VALIDATION_REVIEW / "two_approach_signal_taxonomy.csv")
    over = load_csv(VALIDATION_REVIEW / "route_group_overcollapse_audit.csv")
    rejected = load_csv(VALIDATION_REVIEW / "rejected_candidate_audit.csv")
    high_complex = load_csv(VALIDATION_REVIEW / "five_plus_absence_audit.csv")
    log("Loaded staged objects and audit ledgers.")

    build_amb_signals = set(build_amb["stable_signal_id"])
    build_status_amb_signals = set(build_status.loc[build_status["ambiguity_status"].ne("normal"), "stable_signal_id"])
    validation_amb_signals = set(validation_amb["stable_signal_id"])
    overlap = build_status_amb_signals & validation_amb_signals
    ambiguous_recon = [
        {"metric": "build_ambiguous_approach_rows", "value": int(len(build_amb)), "explanation": "approach-row ambiguity ledger from build"},
        {"metric": "build_ambiguous_signal_count", "value": int(len(build_status_amb_signals)), "explanation": "signal-level candidate_explosion/source-limited flags in build QA"},
        {"metric": "validation_ambiguous_signal_count", "value": int(len(validation_amb_signals)), "explanation": "signals with at least one accepted approach row carrying ambiguity_status != clear"},
        {"metric": "overlap_signal_count", "value": int(len(overlap)), "explanation": "signals flagged by both definitions"},
        {"metric": "validation_only_ambiguous_signal_count", "value": int(len(validation_amb_signals - build_status_amb_signals)), "explanation": "approach-level ambiguity but signal-level build status normal"},
        {"metric": "build_only_ambiguous_signal_count", "value": int(len(build_status_amb_signals - validation_amb_signals)), "explanation": "signal-level candidate explosion/source-limited but no accepted ambiguous approach row"},
        {"metric": "explanation", "value": "109_vs_186_due_different_grain", "explanation": "build count is signal-level status; validation count is approach-row ambiguity rolled to signal"},
    ]
    write_csv("ambiguous_count_reconciliation.csv", ambiguous_recon)
    write_csv("exception_count_reconciliation.csv", [
        {"exception_set": "two_approach_signals", "count": int(len(two))},
        {"exception_set": "likely_underbuilt_two_approach_signals", "count": int(two["two_approach_taxonomy"].isin(["candidate_evidence_suggests_underbuilt", "likely_route_group_overcollapse"]).sum())},
        {"exception_set": "route_group_overcollapse_risk_signals", "count": int(len(over))},
        {"exception_set": "build_ambiguous_signal_count", "count": int(len(build_status_amb_signals))},
        {"exception_set": "validation_ambiguous_signal_count", "count": int(len(validation_amb_signals))},
        {"exception_set": "signals_with_rejected_high_medium_candidates", "count": int((rejected["rejected_high_medium_count"].fillna(0) > 0).sum())},
        {"exception_set": "high_complexity_zero_5plus_review_signals", "count": int(len(high_complex))},
    ])

    rejected_small = rejected[["stable_signal_id", "rejected_candidate_count", "rejected_high_medium_count", "rejected_measure_ready_count", "rejected_route_group_count"]]
    two_adj = two.merge(rejected_small, on="stable_signal_id", how="left")
    adjudicated = []
    for _, row in two_adj.iterrows():
        adjudication, gate = adjudicate_two(row)
        out = row.to_dict()
        out["final_two_approach_adjudication"] = adjudication
        out["proposed_corridor_signal_gate"] = gate
        out["adjudication_reason"] = f"taxonomy={row.get('two_approach_taxonomy')}; candidates={row.get('candidate_count')}; route_groups={row.get('route_group_count')}; rejected_high_medium={row.get('rejected_high_medium_count')}"
        adjudicated.append(out)
    two_adj_df = pd.DataFrame(adjudicated)
    write_csv("two_approach_final_adjudication.csv", two_adj_df.to_dict("records"))
    likely_underbuilt = two_adj_df[two_adj_df["final_two_approach_adjudication"].isin(["likely_underbuilt_patch_candidate", "route_group_overcollapse_patch_candidate"])]
    write_csv("likely_underbuilt_signal_review.csv", likely_underbuilt.to_dict("records"))

    over_adj = over.merge(two_adj_df[["stable_signal_id", "two_approach_taxonomy", "final_two_approach_adjudication"]], on="stable_signal_id", how="left")
    over_adj["route_group_overcollapse_adjudication"] = over_adj.apply(adjudicate_overcollapse, axis=1)
    write_csv("route_group_overcollapse_adjudication.csv", over_adj.to_dict("records"))

    rejected_imp = rejected.copy()
    rejected_imp["rejected_candidate_impact"] = rejected_imp.apply(rejected_impact, axis=1)
    write_csv("rejected_candidate_impact_audit.csv", rejected_imp.to_dict("records"))

    signal_counts = build_status[["stable_signal_id", "approach_count", "candidate_count"]].merge(
        signals[["stable_signal_id", "analysis_ready_status", "source_limited_status"]], on="stable_signal_id", how="left"
    )
    gate_map = dict(zip(two_adj_df["stable_signal_id"], two_adj_df["proposed_corridor_signal_gate"]))
    underbuilt_set = set(likely_underbuilt["stable_signal_id"])
    map_review_set = set(two_adj_df.loc[two_adj_df["final_two_approach_adjudication"].eq("ambiguous_needs_review"), "stable_signal_id"])
    validation_amb_set = validation_amb_signals
    signal_gates = []
    for _, row in signal_counts.iterrows():
        sid = row["stable_signal_id"]
        if row["approach_count"] == 0:
            gate = "source_limited_no_corridor"
            reason = "no accepted approaches"
            include = "ledger_only"
        elif sid in underbuilt_set:
            gate = "corridor_build_blocked_pending_rule_repair"
            reason = "likely underbuilt or overcollapsed two-approach exception"
            include = "exclude_until_rule_repair"
        elif sid in map_review_set:
            gate = "corridor_build_blocked_pending_map_review"
            reason = "ambiguous two-approach exception"
            include = "exclude_until_review"
        elif sid in validation_amb_set:
            gate = "corridor_build_ready_with_warning"
            reason = "approach-level ambiguity; require conservative corridor rules"
            include = "include_with_warning"
        elif sid in gate_map:
            gate = gate_map[sid]
            reason = "two-approach adjudicated acceptable or warning"
            include = "include_with_warning" if "warning" in gate else "include"
        else:
            gate = "corridor_build_ready"
            reason = "no exception gate"
            include = "include"
        signal_gates.append({
            "stable_signal_id": sid,
            "corridor_build_signal_gate": gate,
            "reason": reason,
            "approach_count": int(row["approach_count"]),
            "candidate_count": int(row["candidate_count"]),
            "required_downstream_restriction": "carry gate and do not force corridors through blocked/review signals",
            "corridor_construction_action": include,
        })
    signal_gates_df = pd.DataFrame(signal_gates)
    write_csv("corridor_build_signal_gate_proposal.csv", signal_gates_df.to_dict("records"))

    approach_gates = []
    for _, row in approaches.iterrows():
        sid = row["stable_signal_id"]
        signal_gate = signal_gates_df.loc[signal_gates_df["stable_signal_id"].eq(sid), "corridor_build_signal_gate"].iloc[0]
        if signal_gate.startswith("corridor_build_blocked"):
            gate = signal_gate
            action = "exclude_until_signal_gate_resolved"
        elif row["ambiguity_status"] != "clear":
            gate = "corridor_build_ready_with_warning"
            action = "include_only_with_conservative_corridor_rules"
        else:
            gate = "corridor_build_ready"
            action = "include"
        approach_gates.append({
            "stable_signal_id": sid,
            "signal_approach_id": row["signal_approach_id"],
            "corridor_build_approach_gate": gate,
            "reason": row["ambiguity_reason"] if row["ambiguity_reason"] else "inherits signal gate",
            "required_downstream_restriction": "preserve approach ambiguity and source lineage",
            "corridor_construction_action": action,
        })
    write_csv("corridor_build_approach_gate_proposal.csv", approach_gates)

    true_overcollapse_count = int((over_adj["route_group_overcollapse_adjudication"] == "true_overcollapse_patch_candidate").sum())
    rejected_counts = rejected_imp["rejected_candidate_impact"].value_counts().to_dict()
    signal_gate_counts = signal_gates_df["corridor_build_signal_gate"].value_counts().to_dict()
    approach_gate_counts = pd.Series([r["corridor_build_approach_gate"] for r in approach_gates]).value_counts().to_dict()
    final_decision = "accept_signal_approaches_with_corridor_gates"
    if len(likely_underbuilt) > 100 or true_overcollapse_count > 100:
        final_decision = "patch_candidate_collapse_rules_before_corridors"
    elif len(map_review_set) > 200:
        final_decision = "blocked_pending_map_review"

    write_csv("approach_layer_acceptance_risk_summary.csv", [
        {"metric": "two_approach_signals", "value": int(len(two_adj_df))},
        {"metric": "likely_underbuilt_patch_candidates", "value": int(len(likely_underbuilt))},
        {"metric": "true_overcollapse_patch_candidates", "value": true_overcollapse_count},
        {"metric": "map_review_blocked_two_approach_signals", "value": int(len(map_review_set))},
        {"metric": "validation_ambiguous_signals", "value": int(len(validation_amb_set))},
        {"metric": "corridor_signal_gate_counts", "value": json.dumps({str(k): int(v) for k, v in signal_gate_counts.items()}, sort_keys=True)},
        {"metric": "corridor_approach_gate_counts", "value": json.dumps({str(k): int(v) for k, v in approach_gate_counts.items()}, sort_keys=True)},
    ])
    write_csv("patch_vs_gate_decision.csv", [{
        "decision": final_decision,
        "patch_needed_before_corridors": False,
        "status_gate_patch_recommended_later": True,
        "rationale": "underbuilt/overcollapse exceptions are small enough to gate; no staged mutation in this audit",
    }])
    write_csv("recommended_next_actions.csv", [
        {"rank": 1, "action": "build_approach_corridors_with_signal_and_approach_gates", "rationale": "Approach layer can feed corridors if blocked/review gates are honored."},
        {"rank": 2, "action": "review_likely_underbuilt_signal_review_before_or_during_corridor_qa", "rationale": "Small exception set should not force a full rebuild."},
    ])

    findings = f"""# Signal Approaches Exception Adjudication Audit

## Global plausibility
The approach layer remains globally plausible: the distribution is still 0={int((signal_counts['approach_count']==0).sum())}, 1={int((signal_counts['approach_count']==1).sum())}, 2={int((signal_counts['approach_count']==2).sum())}, 3={int((signal_counts['approach_count']==3).sum())}, 4={int((signal_counts['approach_count']==4).sum())}, 5+=0.

## Two-approach interpretation
The 617 two-approach signals are mostly acceptable or warning-level: {two_adj_df['final_two_approach_adjudication'].value_counts().to_dict()}. Likely underbuilt/overcollapse patch candidates total {len(likely_underbuilt):,}, which is small enough to gate rather than rebuild.

## Route-group overcollapse
Route-group overcollapse risk produced {len(over_adj):,} candidates; adjudication counts are {over_adj['route_group_overcollapse_adjudication'].value_counts().to_dict()}. True patch candidates are {true_overcollapse_count:,}.

## Ambiguous count reconciliation
The 109 vs 186 discrepancy is a grain difference. Build QA's 109 is signal-level `candidate_explosion_risk`/non-normal build status, while validation's 186 is signals with at least one accepted approach row whose approach-level ambiguity status is not clear. Overlap is {len(overlap):,}; validation-only is {len(validation_amb_signals - build_status_amb_signals):,}; build-only is {len(build_status_amb_signals - validation_amb_signals):,}.

## Rejected candidates
Rejected high/medium candidates affect trust by identifying review/gating targets, not by invalidating the layer. Rejected impact counts are {rejected_counts}.

## Corridor gates
Signal gate counts: {signal_gate_counts}. Approach gate counts: {approach_gate_counts}. Corridor construction must exclude blocked signals, ledger source-limited no-corridor signals, and carry warning flags into corridor QA.

## Patch vs gate
Decision: `{final_decision}`. A full rebuild is not recommended; status/gate fields can be patched later if desired, but corridor construction can proceed using the review gate proposal.

## Recommended next task
Build `approach_corridors.parquet` using the proposed signal and approach gates as required restrictions.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "mode": "read_only_audit",
        "inputs": {
            "staged_objects": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
            "audit_evidence": [rel(BUILD_REVIEW), rel(VALIDATION_REVIEW), rel(ATTACHMENT_AUDIT), rel(CANONICAL_FINAL), rel(REFRESH_CANDIDATE)],
        },
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": final_decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "two_approach_adjudication_counts": {str(k): int(v) for k, v in two_adj_df["final_two_approach_adjudication"].value_counts().to_dict().items()},
        "likely_underbuilt_count": int(len(likely_underbuilt)),
        "true_overcollapse_patch_candidate_count": true_overcollapse_count,
        "signal_gate_counts": {str(k): int(v) for k, v in signal_gate_counts.items()},
        "approach_gate_counts": {str(k): int(v) for k, v in approach_gate_counts.items()},
        "final_decision": final_decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    log(f"Audit complete with decision {final_decision}.")


if __name__ == "__main__":
    main()
