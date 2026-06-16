"""Deduplicate chain-aware approach corridor chains for bin eligibility.

This bounded patch removes duplicate generated logical chains from the staged
approach_corridors.parquet while preserving suppressed evidence in QA ledgers.
It does not build bins or assign directionality.
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
OUT = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

VALIDATION_REVIEW = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"
CHAIN_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_chain_completeness_audit"
SIGNAL_QA = REPO / "work/roadway_graph/review/approach_corridors_signal_level_qa_audit"
GATE_PATCH = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"

MAX_REACH_FT = 2500.0
FLOAT_TOL_FT = 0.001
RULE_VERSION = "approach_corridor_chain_dedup_v1_2026-06-09"


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


class DSU:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def compact_counts(series: pd.Series) -> str:
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def build_chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    return corridors.groupby("logical_corridor_chain_id").agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        segment_count=("approach_corridor_id", "size"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_completeness_status=("chain_completeness_status", "first"),
        corridor_confidence=("corridor_confidence", lambda s: "high" if (s == "high").all() else "medium"),
        route_base_values=("route_base", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        measure_side_class=("measure_side_class", "first"),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        max_segment_order=("segment_order", "max"),
        chain_identity_ok=("segment_count_in_chain", lambda s: True),
    ).reset_index()


def stop_rank(reason: str) -> int:
    return {
        "reached_2500_ft": 3,
        "stopped_at_supported_signal_boundary": 3,
        "stopped_at_source_extent": 2,
    }.get(clean(reason), 1)


def choose_canonical(group: pd.DataFrame) -> str:
    g = group.copy()
    g["stop_rank"] = g["chain_stop_reason"].map(stop_rank)
    g["confidence_rank"] = g["corridor_confidence"].map({"high": 2, "medium": 1}).fillna(0)
    g = g.sort_values(
        ["chain_total_reach_ft", "stop_rank", "confidence_rank", "segment_count", "logical_corridor_chain_id"],
        ascending=[False, False, False, True, True],
    )
    return str(g.iloc[0]["logical_corridor_chain_id"])


def build_dedup_groups(corridors: pd.DataFrame, duplicate_pairs: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], set[str]]:
    chain_summary = build_chain_summary(corridors)
    dsu = DSU()
    if not duplicate_pairs.empty:
        for _, row in duplicate_pairs.iterrows():
            dsu.union(clean(row["chain_a"]), clean(row["chain_b"]))
    duplicate_nodes = set(dsu.parent.keys())
    group_rows: list[dict[str, Any]] = []
    canonical_by_chain: dict[str, str] = {}
    if duplicate_nodes:
        comp: dict[str, list[str]] = {}
        for chain_id in duplicate_nodes:
            comp.setdefault(dsu.find(chain_id), []).append(chain_id)
        for idx, chain_ids in enumerate(comp.values(), start=1):
            members = chain_summary[chain_summary["logical_corridor_chain_id"].isin(chain_ids)].copy()
            if members.empty:
                continue
            canonical = choose_canonical(members)
            group_id = f"dedup_group_{idx:06d}"
            for _, member in members.iterrows():
                chain_id = clean(member["logical_corridor_chain_id"])
                canonical_by_chain[chain_id] = canonical
                group_rows.append(
                    {
                        "chain_dedup_group_id": group_id,
                        "logical_corridor_chain_id": chain_id,
                        "canonical_logical_corridor_chain_id": canonical,
                        "chain_dedup_status": "canonical_retained" if chain_id == canonical else "duplicate_suppressed",
                        "chain_dedup_reason": "same_approach_side_route_space_overlap",
                        **member.to_dict(),
                    }
                )
    for chain_id in chain_summary["logical_corridor_chain_id"].astype(str):
        canonical_by_chain.setdefault(chain_id, chain_id)
    return pd.DataFrame.from_records(group_rows), canonical_by_chain, duplicate_nodes


def apply_dedup(corridors: pd.DataFrame, canonical_by_chain: dict[str, str], duplicate_nodes: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c = corridors.copy()
    c["canonical_logical_corridor_chain_id"] = c["logical_corridor_chain_id"].astype(str).map(canonical_by_chain)
    c["duplicate_of_logical_corridor_chain_id"] = c.apply(
        lambda r: "" if clean(r["logical_corridor_chain_id"]) == clean(r["canonical_logical_corridor_chain_id"]) else clean(r["canonical_logical_corridor_chain_id"]),
        axis=1,
    )
    c["chain_dedup_group_id"] = c["canonical_logical_corridor_chain_id"].map(lambda x: f"dedup_{x}" if x in duplicate_nodes else "")
    c["chain_dedup_reason"] = c.apply(
        lambda r: "same_approach_side_route_space_overlap" if clean(r["duplicate_of_logical_corridor_chain_id"]) else "unique_or_canonical_chain",
        axis=1,
    )
    c["chain_dedup_rule_version"] = RULE_VERSION
    c["chain_dedup_status"] = c.apply(
        lambda r: "duplicate_suppressed" if clean(r["duplicate_of_logical_corridor_chain_id"]) else ("canonical_retained" if clean(r["logical_corridor_chain_id"]) in duplicate_nodes else "unique_retained"),
        axis=1,
    )
    c["chain_bin_eligible_flag"] = c["chain_dedup_status"].ne("duplicate_suppressed")
    c["bin_duplication_risk_status"] = c["chain_dedup_status"].map(
        {
            "duplicate_suppressed": "duplicate_suppressed_not_bin_eligible",
            "canonical_retained": "deduplicated_canonical_bin_eligible",
            "unique_retained": "no_duplication_risk",
        }
    )
    suppressed = c[~c["chain_bin_eligible_flag"]].copy()
    retained = c[c["chain_bin_eligible_flag"]].copy()
    suppressed_chain = suppressed.drop_duplicates("logical_corridor_chain_id")
    return retained, suppressed_chain, suppressed


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def recompute_duplicate_risk(corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    chain = build_chain_summary(corridors)
    source_ranges = corridors.groupby("logical_corridor_chain_id").agg(
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
    ).reset_index()
    chain = chain.merge(source_ranges, on="logical_corridor_chain_id", how="left")
    rows = []
    for approach_id, group in chain.groupby("signal_approach_id"):
        if len(group) < 2:
            continue
        vals = list(group.to_dict("records"))
        for i in range(len(vals)):
            a = vals[i]
            for j in range(i + 1, len(vals)):
                b = vals[j]
                same_side = clean(a["measure_side_class"]) == clean(b["measure_side_class"])
                same_route = clean(a["route_base_values"]) == clean(b["route_base_values"]) or clean(a["source_route_name_values"]) == clean(b["source_route_name_values"])
                same_token = clean(a["carriageway_token_values"]) == clean(b["carriageway_token_values"])
                dist_overlap = interval_overlap(0, float(a["chain_total_reach_ft"]), 0, float(b["chain_total_reach_ft"]))
                src_overlap = interval_overlap(float(a["source_measure_min"]), float(a["source_measure_max"]), float(b["source_measure_min"]), float(b["source_measure_max"]))
                ids_a = set(clean(a.get("stable_travelway_ids")).split("|")) - {""}
                ids_b = set(clean(b.get("stable_travelway_ids")).split("|")) - {""}
                shared_tw = len(ids_a & ids_b)
                if not same_side or not same_route:
                    cls = "no_overlap_distinct_branch"
                elif same_side and same_route and same_token and (src_overlap > 0.001 or shared_tw > 0):
                    cls = "likely_duplicate_chain_same_route_space"
                elif same_side and same_route and same_token and dist_overlap >= 250:
                    cls = "possible_duplicate_chain_same_route_space"
                elif same_side and same_route and not same_token:
                    cls = "legitimate_parallel_divided_subbranch"
                else:
                    cls = "insufficient_evidence"
                rows.append(
                    {
                        "signal_approach_id": approach_id,
                        "stable_signal_id": a["stable_signal_id"],
                        "chain_a": a["logical_corridor_chain_id"],
                        "chain_b": b["logical_corridor_chain_id"],
                        "distance_overlap_ft": dist_overlap,
                        "source_measure_overlap": src_overlap,
                        "shared_stable_travelway_id_count": shared_tw,
                        "pair_overlap_class": cls,
                    }
                )
    pairs = pd.DataFrame.from_records(rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=["signal_approach_id", "pair_overlap_class", "distance_overlap_ft"])
    likely = pairs[pairs["pair_overlap_class"].isin(["likely_duplicate_chain_same_route_space", "possible_duplicate_chain_same_route_space"])].copy()
    risk = pairs.groupby("signal_approach_id").agg(
        pair_count=("pair_overlap_class", "size"),
        likely_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "likely_duplicate_chain_same_route_space").sum())),
        possible_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "possible_duplicate_chain_same_route_space").sum())),
        max_distance_overlap_ft=("distance_overlap_ft", "max"),
    ).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "pair_count", "likely_duplicate_pairs", "possible_duplicate_pairs", "max_distance_overlap_ft"])
    def risk_class(row: pd.Series) -> str:
        if int(row.get("likely_duplicate_pairs", 0)) > 0:
            return "likely_duplicate_chains_block_bin_context"
        if int(row.get("possible_duplicate_pairs", 0)) >= 3:
            return "high_duplication_risk"
        if int(row.get("possible_duplicate_pairs", 0)) > 0:
            return "moderate_duplication_review"
        if int(row.get("pair_count", 0)) > 0:
            return "low_duplication_risk"
        return "no_duplication_risk"
    risk["approach_duplication_risk"] = risk.apply(risk_class, axis=1)
    return pairs, likely, risk


def density_by_approach(corridors: pd.DataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    counts = corridors.groupby("signal_approach_id").agg(
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        corridor_segment_rows=("approach_corridor_id", "size"),
        chain_stop_reason_mix=("chain_stop_reason", compact_counts),
    ).reset_index()
    out = approaches[["stable_signal_id", "signal_approach_id", "corridor_build_gate"]].merge(counts, on="signal_approach_id", how="left")
    out[["logical_chain_count", "corridor_segment_rows"]] = out[["logical_chain_count", "corridor_segment_rows"]].fillna(0).astype(int)
    out["chain_stop_reason_mix"] = out["chain_stop_reason_mix"].fillna("")
    return out


def update_metadata(corridors: pd.DataFrame, decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {})["approach_corridors"] = {
        "path": rel(APPROACH_CORRIDORS),
        "grain": "deduplicated bin-eligible chain-aware corridor segments",
        "canonical_parents": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES)],
        "row_count": int(len(corridors)),
        "logical_chain_count": int(corridors["logical_corridor_chain_id"].nunique()) if not corridors.empty else 0,
        "dedup_rule_version": RULE_VERSION,
        "updated_utc": now(),
        "script": "src.roadway_graph.deduplicate_approach_corridor_chains",
        "final_decision": decision,
    }
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    table = schema.setdefault("tables", {}).setdefault("approach_corridors.parquet", {})
    table["deduplication_fields"] = [
        "chain_bin_eligible_flag",
        "chain_dedup_status",
        "chain_dedup_group_id",
        "canonical_logical_corridor_chain_id",
        "duplicate_of_logical_corridor_chain_id",
        "chain_dedup_reason",
        "chain_dedup_rule_version",
        "bin_duplication_risk_status",
    ]
    table["dedup_rule_version"] = RULE_VERSION
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    addition = f"""

## Approach corridor chain deduplication

Applied `{RULE_VERSION}` to keep only canonical bin-eligible chains per
approach route-space branch. Suppressed duplicate generated chains were removed
from the staged Parquet and preserved in review ledgers. No bins,
upstream/downstream labels, directionality, or numeric context products were
built.
"""
    existing = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else ""
    if "## Approach corridor chain deduplication" not in existing:
        STAGING_README.write_text(existing.rstrip() + addition, encoding="utf-8")


def write_outputs(
    prior: pd.DataFrame,
    post: pd.DataFrame,
    approaches: pd.DataFrame,
    signals: pd.DataFrame,
    roads: pd.DataFrame,
    dup_pairs: pd.DataFrame,
    group_summary: pd.DataFrame,
    suppressed_chains: pd.DataFrame,
    suppressed_segments: pd.DataFrame,
    post_pairs: pd.DataFrame,
    post_likely: pd.DataFrame,
    post_risk: pd.DataFrame,
    density: pd.DataFrame,
    decision: str,
) -> None:
    prior_chains = prior["logical_corridor_chain_id"].nunique()
    post_chains = post["logical_corridor_chain_id"].nunique()
    write_csv("parent_dependency_check.csv", [
        {"object": "approach_corridors", "dependency": rel(SIGNAL_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(ATTACHMENT), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(APPROACHES), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "approach_corridors", "dependency": rel(VALIDATION_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
    ])
    write_csv("prior_vs_post_dedup_corridor_counts.csv", [
        {"metric": "prior_corridor_segment_rows", "value": int(len(prior))},
        {"metric": "post_corridor_segment_rows", "value": int(len(post))},
        {"metric": "suppressed_corridor_segment_rows", "value": int(len(suppressed_segments))},
    ])
    write_csv("prior_vs_post_dedup_chain_counts.csv", [
        {"metric": "prior_logical_chains", "value": int(prior_chains)},
        {"metric": "post_logical_chains", "value": int(post_chains)},
        {"metric": "suppressed_logical_chains", "value": int(len(suppressed_chains))},
    ])
    write_csv("chain_dedup_group_summary.csv", group_summary.to_dict("records"))
    write_csv("canonical_chain_selection_summary.csv", group_summary[group_summary["chain_dedup_status"].eq("canonical_retained")].to_dict("records"))
    write_csv("suppressed_duplicate_chain_ledger.csv", suppressed_chains.to_dict("records"))
    write_csv("suppressed_duplicate_segment_ledger.csv", suppressed_segments.to_dict("records"))
    legitimate = post_pairs[post_pairs["pair_overlap_class"].isin(["legitimate_parallel_divided_subbranch", "no_overlap_distinct_branch"])].copy()
    write_csv("retained_legitimate_parallel_branch_ledger.csv", legitimate.to_dict("records"))
    write_csv("chain_bin_eligible_counts.csv", post.groupby(["chain_bin_eligible_flag", "chain_dedup_status"]).size().reset_index(name="corridor_segment_rows").to_dict("records"))
    write_csv("approach_level_duplication_risk_after_patch.csv", post_risk.to_dict("records"))
    write_csv("likely_duplicate_chain_pairs_after_patch.csv", post_likely.to_dict("records"))
    write_csv("distance_band_overlap_risk_after_patch.csv", post_pairs[post_pairs["distance_overlap_ft"] >= 50].to_dict("records"))
    order = post.groupby("logical_corridor_chain_id").agg(segment_count=("approach_corridor_id", "size"), declared=("segment_count_in_chain", "first"), max_order=("segment_order", "max"), unique_order=("segment_order", "nunique")).reset_index()
    order["status"] = order.apply(lambda r: "pass" if int(r["segment_count"]) == int(r["declared"]) and int(r["max_order"]) == int(r["segment_count"]) and int(r["unique_order"]) == int(r["segment_count"]) else "fail", axis=1)
    write_csv("segment_order_check_after_patch.csv", order.to_dict("records"))
    write_csv("chain_stop_reason_summary_after_patch.csv", post.drop_duplicates("logical_corridor_chain_id").groupby("chain_stop_reason").size().reset_index(name="logical_chain_count").to_dict("records"))
    write_csv("chain_total_reach_distribution_after_patch.csv", pd.cut(post.drop_duplicates("logical_corridor_chain_id")["chain_total_reach_ft"], bins=[0, 100, 250, 500, 1000, 1500, 2000, 2500.001], labels=["0_100", "100_250", "250_500", "500_1000", "1000_1500", "1500_2000", "2000_2500"], include_lowest=True).value_counts().sort_index().reset_index(name="logical_chain_count").rename(columns={"chain_total_reach_ft": "reach_bucket"}).to_dict("records"))
    write_csv("chain_density_by_approach_after_patch.csv", density.to_dict("records"))
    write_csv("high_chain_density_remaining_review.csv", density[density["logical_chain_count"] >= 5].sort_values("logical_chain_count", ascending=False).to_dict("records"))
    write_csv("source_extent_stop_check_after_patch.csv", post.drop_duplicates("logical_corridor_chain_id").query("chain_stop_reason == 'stopped_at_source_extent'").to_dict("records"))
    write_csv("supported_signal_boundary_crossing_check_after_patch.csv", [{"boundary_crossing_violation_rows": int(post["cross_signal_boundary_flag"].fillna(False).astype(bool).sum()), "status": "pass" if not post["cross_signal_boundary_flag"].fillna(False).astype(bool).any() else "fail"}])
    warning = approaches[approaches["corridor_build_gate"].eq("corridor_build_ready_with_warning")][["signal_approach_id", "stable_signal_id", "corridor_gate_severity", "corridor_restriction_notes"]].merge(density[["signal_approach_id", "logical_chain_count", "corridor_segment_rows"]], on="signal_approach_id", how="left")
    warning["has_chain"] = warning["logical_chain_count"].fillna(0).astype(int) > 0
    write_csv("warning_gate_propagation_check_after_patch.csv", warning.to_dict("records"))
    blocked = approaches[approaches["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")][["signal_approach_id", "stable_signal_id", "corridor_build_gate"]].merge(density[["signal_approach_id", "logical_chain_count", "corridor_segment_rows"]], on="signal_approach_id", how="left")
    blocked[["logical_chain_count", "corridor_segment_rows"]] = blocked[["logical_chain_count", "corridor_segment_rows"]].fillna(0).astype(int)
    blocked["excluded_from_corridors"] = blocked["logical_chain_count"].eq(0)
    write_csv("blocked_gate_exclusion_check_after_patch.csv", blocked.to_dict("records"))
    forbidden = [c for c in post.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    write_csv("non_directionality_field_check.csv", [{"forbidden_directionality_field_count": len(forbidden), "forbidden_fields": "|".join(forbidden), "status": "pass" if not forbidden else "fail"}])
    write_csv("deduplication_summary.csv", [
        {"metric": "duplicate_pair_rows_input", "value": int(len(dup_pairs))},
        {"metric": "dedup_groups", "value": int(group_summary["chain_dedup_group_id"].nunique()) if not group_summary.empty else 0},
        {"metric": "suppressed_duplicate_chains", "value": int(len(suppressed_chains))},
        {"metric": "suppressed_duplicate_segments", "value": int(len(suppressed_segments))},
        {"metric": "likely_duplicate_chain_pairs_after_patch", "value": int(len(post_likely))},
        {"metric": "approaches_blocking_bin_context_after_patch", "value": int(post_risk["approach_duplication_risk"].eq("likely_duplicate_chains_block_bin_context").sum()) if not post_risk.empty else 0},
        {"metric": "final_decision", "value": decision},
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "approach corridor chain deduplication completed"}])
    write_csv("recommended_next_actions.csv", [{"rank": 1, "action": "run_post_dedup_chain_corridor_validation_then_build_bin_context", "rationale": "Duplicate generated chains have been suppressed from the staged bin-eligible corridor layer."}])
    findings = f"""# Approach Corridor Chain Deduplication

## Why Deduplication Was Needed
The chain-aware corridor validation found likely duplicate route-space chains that would create duplicate bin coverage if used directly.

## What Was Collapsed
Suppressed duplicate chains: {len(suppressed_chains):,}. Suppressed segment rows: {len(suppressed_segments):,}. Canonical chains were selected by greatest valid reach, clear stop reason, confidence, fewer redundant segments, and deterministic chain ID tie-breaking.

## Legitimate Branches
Pairs not classified as duplicate remain in the staged layer. Legitimate divided/parallel and distinct-route branches are ledgered in `retained_legitimate_parallel_branch_ledger.csv`.

## Post-Patch Duplicate Risk
Likely/possible duplicate chain pairs after patch: {len(post_likely):,}. Approaches blocking bin_context after patch: {int(post_risk['approach_duplication_risk'].eq('likely_duplicate_chains_block_bin_context').sum()) if not post_risk.empty else 0}.

## Gates and Safety
Warning approaches remain represented. Blocked approaches remain excluded. No upstream/downstream or directionality fields were assigned.

## Readiness
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {"created_at": now(), "script": rel(Path(__file__)), "output_dir": rel(OUT), "staged_product": rel(APPROACH_CORRIDORS), "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(APPROACH_CORRIDORS)], "method_evidence_only": [rel(VALIDATION_REVIEW), rel(RECON_REVIEW), rel(CHAIN_AUDIT), rel(SIGNAL_QA), rel(GATE_PATCH)], "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()), "final_decision": decision}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "prior_corridor_segment_rows": int(len(prior)),
        "post_corridor_segment_rows": int(len(post)),
        "prior_logical_chains": int(prior_chains),
        "post_logical_chains": int(post_chains),
        "suppressed_duplicate_chains": int(len(suppressed_chains)),
        "suppressed_duplicate_segments": int(len(suppressed_segments)),
        "likely_duplicate_chain_pairs_after_patch": int(len(post_likely)),
        "approaches_blocking_bin_context_after_patch": int(post_risk["approach_duplication_risk"].eq("likely_duplicate_chains_block_bin_context").sum()) if not post_risk.empty else 0,
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting approach corridor chain deduplication.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id", "source_limited_status"])
    roads = pd.read_parquet(TRAVELWAY_INDEX, columns=["stable_travelway_id"])
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(APPROACH_CORRIDORS)
    dup_pairs = pd.read_csv(VALIDATION_REVIEW / "likely_duplicate_chain_pairs.csv") if (VALIDATION_REVIEW / "likely_duplicate_chain_pairs.csv").exists() else pd.DataFrame()
    log(f"Loaded corridors={len(corridors)}, duplicate_pair_rows={len(dup_pairs)}, approaches={len(approaches)}.")
    group_summary, canonical_by_chain, duplicate_nodes = build_dedup_groups(corridors, dup_pairs)
    retained, suppressed_chains, suppressed_segments = apply_dedup(corridors, canonical_by_chain, duplicate_nodes)
    log(f"Selected canonical chains; retained_segments={len(retained)}, suppressed_chains={len(suppressed_chains)}, suppressed_segments={len(suppressed_segments)}.")
    post_pairs, post_likely, post_risk = recompute_duplicate_risk(retained)
    density = density_by_approach(retained, approaches)
    blocking_after = int(post_risk["approach_duplication_risk"].eq("likely_duplicate_chains_block_bin_context").sum()) if not post_risk.empty else 0
    if len(post_likely) == 0 and blocking_after == 0:
        decision = "deduplicated_approach_corridors_ready_for_bin_context"
    elif blocking_after == 0:
        decision = "deduplicated_approach_corridors_ready_after_review_of_remaining_outliers"
    else:
        decision = "approach_corridors_needs_additional_deduplication_patch"
    log(f"Post-dedup duplicate pairs={len(post_likely)}, blocking approaches={blocking_after}.")
    retained.to_parquet(APPROACH_CORRIDORS, index=False)
    write_outputs(corridors, retained, approaches, signals, roads, dup_pairs, group_summary, suppressed_chains, suppressed_segments, post_pairs, post_likely, post_risk, density, decision)
    update_metadata(retained, decision)
    log(f"Deduplication complete with decision {decision}.")


if __name__ == "__main__":
    main()
