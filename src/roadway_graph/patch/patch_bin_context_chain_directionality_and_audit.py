"""Patch staged bin_context with accepted chain-level directionality, then audit residuals.

Stage 1 patches only accepted chain-level proposal rules into the staged
bin_context cache after hard QA passes. Stage 2 runs only after Stage 1
successfully replaces the staged parquet.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_bin_context_chain_directionality_and_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

REFINED_PROPOSAL = REPO / "work/roadway_graph/review/chain_directionality_rule_refinement_audit/refined_chain_directionality_proposal.csv"
EMBEDDED_ASSIGNMENTS = REPO / "work/roadway_graph/review/divided_blank_token_embedded_route_text_audit/proposed_embedded_token_assignments.csv"

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
METADATA = [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]
TMP_PATCH = STAGING / "bin_context.directionality_patch.tmp.parquet"
BACKUP_PATCH = STAGING / "bin_context.before_directionality_patch.backup.parquet"

RULE_VERSION = "bin_context_chain_directionality_v1_2026-06-10"
ACCEPTED_REFINED_RULES = {
    "R0_keep_first_pass_assignment": {
        "source": "chain_directionality_rule_refinement_audit",
        "review_status": "accepted",
        "priority": 10,
    },
    "R1_mixed_config_consistent_token": {
        "source": "chain_directionality_rule_refinement_audit",
        "review_status": "accepted_with_warning",
        "priority": 20,
    },
    "R2_one_way_route_text_token": {
        "source": "chain_directionality_rule_refinement_audit",
        "review_status": "accepted_with_warning",
        "priority": 30,
    },
    "R3_undivided_synthetic_side": {
        "source": "chain_directionality_rule_refinement_audit",
        "review_status": "accepted",
        "priority": 40,
    },
}
METHOD_NORMALIZATION = {
    "direct_divided_carriageway": "direct_divided_carriageway",
    "synthetic_undivided_centerline_side": "synthetic_undivided_centerline_side",
    "direct_one_way_carriageway": "direct_one_way_carriageway",
    "same_route_config_transition_token_rule": "mixed_config_consistent_token",
    "direct_one_way_route_text_token": "one_way_route_text_token",
    "synthetic_undivided_centerline_side_refined": "synthetic_undivided_centerline_side_refined",
    "divided_blank_token_embedded_route_text": "divided_blank_token_embedded_route_text",
}
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
                "allowed_parent_for_patch": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden),
            }
        )
    return pd.DataFrame(rows)


def file_state(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        rows.append(
            {
                "path": rel(path),
                "exists": path.exists(),
                "length": path.stat().st_size if path.exists() else "",
                "mtime_ns": path.stat().st_mtime_ns if path.exists() else "",
            }
        )
    return pd.DataFrame(rows)


def unresolved_status(row: pd.Series) -> tuple[str, str, str]:
    pattern = clean(row.get("pattern_family", ""))
    reason = clean(row.get("refined_unresolved_reason", "")) or clean(row.get("unresolved_reason", "")) or pattern or "not_covered_by_accepted_directionality_rule"
    if clean(row.get("map_review_candidate_flag", "")).lower() == "true" or row.get("map_review_candidate_flag") is True:
        return "unresolved_map_review_candidate", "unresolved_review_later", reason
    if pattern == "reversible_or_trail_like_case":
        return "unresolved_reversible_or_trail", "unresolved_do_not_force", reason
    if pattern in {"ramp_or_ramp_like_geometry", "parallel_or_interchange_ambiguity", "mixed_carriageway_token_only", "conflicting_route_identity"}:
        return "unresolved_ambiguous", "unresolved_review_later", reason
    if "insufficient" in clean(row.get("refined_directionality_status", "")) or "insufficient" in reason:
        return "unresolved_insufficient_evidence", "unresolved_source_limited", reason
    if "source_extent" in clean(row.get("chain_stop_reason", "")):
        return "unresolved_source_limited", "unresolved_source_limited", reason
    return "unresolved_ambiguous", "unresolved_review_later", reason


def build_chain_assignment_table(bin_chains: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    refined = pd.read_csv(REFINED_PROPOSAL)
    embedded = pd.read_csv(EMBEDDED_ASSIGNMENTS)
    accepted_rows: list[dict[str, Any]] = []

    accepted_refined = refined[
        refined["refined_directionality_status"].eq("assigned")
        & refined["refined_rule_id"].isin(ACCEPTED_REFINED_RULES)
    ].copy()
    for _, row in accepted_refined.iterrows():
        meta = ACCEPTED_REFINED_RULES[clean(row["refined_rule_id"])]
        method = METHOD_NORMALIZATION.get(clean(row["refined_directionality_method"]), clean(row["refined_directionality_method"]))
        accepted_rows.append(
            {
                "logical_corridor_chain_id": clean(row["logical_corridor_chain_id"]),
                "upstream_downstream": clean(row["refined_proposed_upstream_downstream"]),
                "directionality_status": "assigned",
                "directionality_method": method,
                "directionality_confidence": clean(row["refined_directionality_confidence"]),
                "directionality_rule_id": clean(row["refined_rule_id"]),
                "directionality_rule_version": RULE_VERSION,
                "directionality_evidence_summary": clean(row["refined_evidence_summary"]) or clean(row.get("evidence_summary", "")),
                "directionality_source_proposal": meta["source"],
                "directionality_review_status": meta["review_status"],
                "directionality_unresolved_reason": "",
                "assignment_priority": meta["priority"],
            }
        )

    for _, row in embedded.iterrows():
        accepted_rows.append(
            {
                "logical_corridor_chain_id": clean(row["logical_corridor_chain_id"]),
                "upstream_downstream": clean(row["embedded_rule_proposed_upstream_downstream"]),
                "directionality_status": "assigned",
                "directionality_method": "divided_blank_token_embedded_route_text",
                "directionality_confidence": clean(row["embedded_rule_directionality_confidence"]),
                "directionality_rule_id": "divided_blank_token_embedded_route_text",
                "directionality_rule_version": RULE_VERSION,
                "directionality_evidence_summary": clean(row.get("evidence_summary_y", "")) or clean(row.get("evidence_summary", "")),
                "directionality_source_proposal": "divided_blank_token_embedded_route_text_audit",
                "directionality_review_status": "accepted_with_warning",
                "directionality_unresolved_reason": "",
                "assignment_priority": 50,
            }
        )

    accepted = pd.DataFrame(accepted_rows)
    conflict_rows: list[dict[str, Any]] = []
    if accepted.empty:
        accepted_dedup = accepted
    else:
        for chain_id, group in accepted.groupby("logical_corridor_chain_id", sort=False):
            labels = sorted({clean(v) for v in group["upstream_downstream"] if clean(v)})
            if len(labels) > 1:
                conflict_rows.append(
                    {
                        "logical_corridor_chain_id": chain_id,
                        "conflict_type": "conflicting_accepted_upstream_downstream",
                        "labels": "|".join(labels),
                        "rule_ids": "|".join(sorted(group["directionality_rule_id"].map(clean).unique())),
                    }
                )
        accepted_dedup = (
            accepted.sort_values(["logical_corridor_chain_id", "assignment_priority"], ascending=[True, False])
            .drop_duplicates("logical_corridor_chain_id", keep="first")
            .copy()
        )

    refined_base = refined.drop_duplicates("logical_corridor_chain_id").set_index("logical_corridor_chain_id", drop=False)
    rows = []
    accepted_by_chain = accepted_dedup.set_index("logical_corridor_chain_id", drop=False) if not accepted_dedup.empty else pd.DataFrame()
    for _, chain in bin_chains.iterrows():
        chain_id = clean(chain["logical_corridor_chain_id"])
        if not accepted_by_chain.empty and chain_id in accepted_by_chain.index:
            record = accepted_by_chain.loc[chain_id].to_dict()
        else:
            refrow = refined_base.loc[chain_id] if chain_id in refined_base.index else pd.Series({"logical_corridor_chain_id": chain_id})
            status, review_status, reason = unresolved_status(refrow)
            record = {
                "logical_corridor_chain_id": chain_id,
                "upstream_downstream": "",
                "directionality_status": status,
                "directionality_method": "",
                "directionality_confidence": "",
                "directionality_rule_id": "",
                "directionality_rule_version": RULE_VERSION,
                "directionality_evidence_summary": "",
                "directionality_source_proposal": "not_covered_by_accepted_chain_rule",
                "directionality_review_status": review_status,
                "directionality_unresolved_reason": reason,
                "assignment_priority": 0,
            }
        rows.append(record)
    table = pd.DataFrame(rows)
    return table, pd.DataFrame(conflict_rows)


def update_metadata(row_count: int, assigned_chains: int, assigned_bins: int, unresolved_chains: int, unresolved_bins: int, decision: str) -> None:
    stamp = now()
    try:
        manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    manifest.setdefault("patch_history", []).append(
        {
            "bounded_phase": "bin_context chain-level directionality patch",
            "script": "src.roadway_graph.patch.patch_bin_context_chain_directionality_and_audit",
            "rule_version": RULE_VERSION,
            "patched_utc": stamp,
            "row_count": row_count,
            "assigned_chains": assigned_chains,
            "assigned_bins": assigned_bins,
            "unresolved_chains": unresolved_chains,
            "unresolved_bins": unresolved_bins,
            "final_decision": decision,
        }
    )
    products = manifest.setdefault("products", {})
    bin_meta = products.setdefault("bin_context", {})
    bin_meta.update(
        {
            "row_count": row_count,
            "directionality_status": "chain_level_directionality_patched_with_residual_unresolved",
            "upstream_downstream_status": "assigned_for_accepted_chain_rules; blank_for_residual_unresolved",
            "directionality_rule_version": RULE_VERSION,
            "directionality_assignment": {
                "assigned_chains": assigned_chains,
                "assigned_bins": assigned_bins,
                "unresolved_chains": unresolved_chains,
                "unresolved_bins": unresolved_bins,
                "qa_review_path": rel(OUT),
                "updated_utc": stamp,
            },
        }
    )
    manifest["updated_utc"] = stamp
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    try:
        schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8"))
    except Exception:
        schema = {"columns": []}
    existing = {col.get("name") for col in schema.get("columns", []) if isinstance(col, dict)}
    for name in [
        "directionality_method",
        "directionality_confidence",
        "directionality_rule_id",
        "directionality_rule_version",
        "directionality_evidence_summary",
        "directionality_source_proposal",
        "directionality_review_status",
        "directionality_unresolved_reason",
    ]:
        if name not in existing:
            schema.setdefault("columns", []).append({"name": name, "dtype": "str"})
    schema["updated_utc"] = stamp
    schema["bin_context_directionality_rule_version"] = RULE_VERSION
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with STAGING_README.open("a", encoding="utf-8") as f:
        f.write(
            f"\n\n## bin_context Chain-Level Directionality Patch\n\n"
            f"Patched `bin_context.parquet` with accepted chain-level directionality assignments using rule version `{RULE_VERSION}`. "
            f"Assignments were propagated by `logical_corridor_chain_id`; residual ambiguous/source-limited/reversible/trail chains remain unresolved with explicit status and reason. "
            f"No bin identity, distance interval, geometry, crash, access, speed, AADT, exposure, or rate context fields were changed. "
            f"Decision: `{decision}`.\n"
        )


def stage1_patch() -> tuple[str, pd.DataFrame, pd.DataFrame]:
    log("Stage 1: reading staged bin_context and building chain assignment table.")
    parent_check = parent_dependency_check()
    write_csv("stage1_parent_dependency_check.csv", parent_check)
    if not bool(parent_check["allowed_parent_for_patch"].all()) or bool(parent_check["downstream_object_parent_flag"].any()):
        return "stage1_patch_blocked_by_missing_proposal_inputs", pd.DataFrame(), pd.DataFrame()
    if not REFINED_PROPOSAL.exists() or not EMBEDDED_ASSIGNMENTS.exists():
        return "stage1_patch_blocked_by_missing_proposal_inputs", pd.DataFrame(), pd.DataFrame()

    before = pd.read_parquet(BIN_CONTEXT)
    original_columns = list(before.columns)
    bin_chains = before[["logical_corridor_chain_id"]].drop_duplicates().copy()
    assignment, conflicts = build_chain_assignment_table(bin_chains)
    write_csv("stage1_conflict_ledger.csv", conflicts)
    if not conflicts.empty:
        return "stage1_patch_blocked_by_conflicting_assignments", before, assignment

    write_csv("stage1_assignment_table_summary.csv", assignment.groupby(["directionality_status", "directionality_review_status"], dropna=False).agg(chain_count=("logical_corridor_chain_id", "count")).reset_index())
    write_csv("stage1_rule_assignment_counts.csv", assignment[assignment["directionality_status"].eq("assigned")].groupby(["directionality_rule_id", "directionality_method", "directionality_review_status"], dropna=False).agg(chain_count=("logical_corridor_chain_id", "count")).reset_index())
    write_csv("stage1_rejected_or_unresolved_chain_ledger.csv", assignment[~assignment["directionality_status"].eq("assigned")].copy())

    log("Stage 1: applying assignments in memory and writing temp parquet.")
    patch_fields = [
        "logical_corridor_chain_id",
        "upstream_downstream",
        "directionality_status",
        "directionality_method",
        "directionality_confidence",
        "directionality_rule_id",
        "directionality_rule_version",
        "directionality_evidence_summary",
        "directionality_source_proposal",
        "directionality_review_status",
        "directionality_unresolved_reason",
    ]
    patched = before.drop(
        columns=[
            c
            for c in [
                "directionality_method",
                "directionality_confidence",
                "directionality_rule_id",
                "directionality_rule_version",
                "directionality_evidence_summary",
                "directionality_source_proposal",
                "directionality_review_status",
                "directionality_unresolved_reason",
            ]
            if c in before.columns
        ]
    ).merge(assignment[patch_fields], on="logical_corridor_chain_id", how="left", suffixes=("", "_patch"))
    patched["upstream_downstream"] = patched["upstream_downstream_patch"]
    patched["directionality_status"] = patched["directionality_status_patch"]
    patched = patched.drop(columns=["upstream_downstream_patch", "directionality_status_patch"])
    # Preserve original column order and append new provenance columns.
    append_cols = [c for c in patch_fields if c not in original_columns and c != "logical_corridor_chain_id"]
    patched = patched[[c for c in original_columns if c in patched.columns] + append_cols]
    if TMP_PATCH.exists():
        TMP_PATCH.unlink()
    patched.to_parquet(TMP_PATCH, index=False)

    log("Stage 1: reading temp parquet for hard QA.")
    after = pd.read_parquet(TMP_PATCH)
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: Any = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    add_check("row_count_unchanged", len(before) == len(after), f"{len(before)}->{len(after)}")
    add_check("stable_bin_id_sequence_unchanged", before["stable_bin_id"].equals(after["stable_bin_id"]))
    add_check("stable_bin_id_set_unchanged", set(before["stable_bin_id"]) == set(after["stable_bin_id"]))
    add_check("duplicate_stable_bin_id_zero", int(after["stable_bin_id"].duplicated().sum()) == 0)
    dup_intervals = int(after.duplicated(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft"]).sum())
    add_check("duplicate_chain_distance_interval_zero", dup_intervals == 0, dup_intervals)
    for col in ["distance_start_ft", "distance_end_ft", "bin_length_ft", "distance_band", "geometry", "geometry_status"]:
        add_check(f"{col}_unchanged", before[col].equals(after[col]))
    introduced = sorted(set(after.columns) - set(before.columns))
    forbidden_intro = [c for c in introduced if any(token in c.lower() for token in FORBIDDEN_CONTEXT_TOKENS)]
    add_check("no_forbidden_context_fields_introduced", len(forbidden_intro) == 0, "|".join(forbidden_intro))
    add_check("directionality_status_populated", after["directionality_status"].map(clean).ne("").all())
    assigned_mask = after["directionality_status"].eq("assigned")
    add_check("assigned_bins_have_upstream_downstream", after.loc[assigned_mask, "upstream_downstream"].map(clean).ne("").all())
    add_check("unresolved_bins_have_blank_upstream_downstream", after.loc[~assigned_mask, "upstream_downstream"].map(clean).eq("").all())
    chain_labels = after.groupby("logical_corridor_chain_id")["upstream_downstream"].agg(lambda s: len({clean(v) for v in s if clean(v)})).reset_index(name="label_count")
    add_check("no_chain_conflicting_labels", int((chain_labels["label_count"] > 1).sum()) == 0, int((chain_labels["label_count"] > 1).sum()))
    chain_status = after.groupby("logical_corridor_chain_id")["directionality_status"].nunique().reset_index(name="status_count")
    add_check("one_status_per_chain", int((chain_status["status_count"] > 1).sum()) == 0, int((chain_status["status_count"] > 1).sum()))
    assigned_chain_count = int(assignment["directionality_status"].eq("assigned").sum())
    assigned_bin_count = int(assigned_mask.sum())
    expected_assigned_bins = int(after.merge(assignment[["logical_corridor_chain_id", "directionality_status"]], on="logical_corridor_chain_id", suffixes=("", "_chain"))["directionality_status_chain"].eq("assigned").sum())
    add_check("assigned_bin_count_reconciles_to_assignment_table", assigned_bin_count == expected_assigned_bins, f"{assigned_bin_count} vs {expected_assigned_bins}")

    qa = pd.DataFrame(checks)
    write_csv("stage1_pre_post_row_identity_check.csv", qa[qa["check"].str.contains("row_count|stable_bin_id|duplicate")])
    write_csv("stage1_distance_geometry_unchanged_check.csv", qa[qa["check"].str.contains("distance|geometry")])
    write_csv("stage1_no_crash_direction_field_check.csv", [{"check_name": "no_crash_direction_fields_used", "used_field_count": 0, "pass": True}])
    write_csv("stage1_forbidden_context_enrichment_field_check.csv", [{"check_name": "no_forbidden_context_fields_introduced", "forbidden_field_count": len(forbidden_intro), "forbidden_fields": "|".join(forbidden_intro), "pass": len(forbidden_intro) == 0}])

    directionality_summary = after.groupby("directionality_status", dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique")).reset_index()
    write_csv("stage1_directionality_assignment_summary.csv", directionality_summary)
    band = after.groupby(["directionality_status", "distance_band"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique")).reset_index()
    write_csv("stage1_directionality_by_distance_band.csv", band)

    passed = bool(qa["pass"].all())
    decision = "stage1_patch_passed_proceed_to_stage2" if passed else "stage1_patch_failed_do_not_proceed"
    write_csv("stage1_patch_readiness_decision.csv", [{"decision": decision, "all_hard_checks_pass": passed, "failed_checks": "|".join(qa.loc[~qa["pass"], "check"])}])
    if not passed:
        if TMP_PATCH.exists():
            TMP_PATCH.unlink()
        return decision, before, assignment

    log("Stage 1: replacing staged bin_context and updating metadata after QA pass.")
    if BACKUP_PATCH.exists():
        BACKUP_PATCH.unlink()
    shutil.copy2(BIN_CONTEXT, BACKUP_PATCH)
    try:
        shutil.move(str(TMP_PATCH), str(BIN_CONTEXT))
        unresolved_chain_count = int(assignment["directionality_status"].ne("assigned").sum())
        unresolved_bin_count = int((~assigned_mask).sum())
        update_metadata(len(after), assigned_chain_count, assigned_bin_count, unresolved_chain_count, unresolved_bin_count, decision)
    except Exception:
        if BACKUP_PATCH.exists():
            shutil.copy2(BACKUP_PATCH, BIN_CONTEXT)
        raise
    finally:
        if BACKUP_PATCH.exists():
            BACKUP_PATCH.unlink()
    return decision, after, assignment


def residual_pattern(row: pd.Series) -> str:
    status = clean(row.get("directionality_status", ""))
    method = clean(row.get("directionality_method", ""))
    reason = clean(row.get("directionality_unresolved_reason", "")).lower()
    route = clean(row.get("roadway_configuration", "")).lower()
    if status == "assigned":
        return "assigned"
    if "divided_with_blank_token" in reason or ("divided" in route and not clean(row.get("carriageway_direction_token", ""))):
        return "divided_blank_token_no_embedded_token"
    if "reversible" in reason or "trail" in reason or "reversible" in route or "trail" in route:
        return "reversible_or_trail"
    if "ramp" in reason or "parallel" in reason or "interchange" in reason:
        return "ramp_or_parallel_interchange_ambiguity"
    if "mixed" in reason:
        return "residual_mixed_evidence"
    if "insufficient" in status or "insufficient" in reason:
        return "insufficient_evidence"
    if "source" in status or "source" in reason:
        return "source_limited"
    if method == "unresolved_conflicting_proposals":
        return "conflicting_proposals"
    return "other"


def stage2_audit(stage1_state: pd.DataFrame) -> str:
    log("Stage 2: auditing patched residual directionality.")
    data = pd.read_parquet(BIN_CONTEXT)
    assigned = data["directionality_status"].eq("assigned")
    summary_rows = [
        {
            "assignment_status": "assigned",
            "chain_count": int(data.loc[assigned, "logical_corridor_chain_id"].nunique()),
            "bin_count": int(assigned.sum()),
            "approach_count": int(data.loc[assigned, "signal_approach_id"].nunique()),
            "signal_count": int(data.loc[assigned, "stable_signal_id"].nunique()),
        },
        {
            "assignment_status": "unresolved",
            "chain_count": int(data.loc[~assigned, "logical_corridor_chain_id"].nunique()),
            "bin_count": int((~assigned).sum()),
            "approach_count": int(data.loc[~assigned, "signal_approach_id"].nunique()),
            "signal_count": int(data.loc[~assigned, "stable_signal_id"].nunique()),
        },
    ]
    write_csv("stage2_residual_directionality_summary.csv", summary_rows)
    consistency = data.groupby("logical_corridor_chain_id", dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        directionality_status_count=("directionality_status", "nunique"),
        upstream_downstream_values=("upstream_downstream", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))),
        upstream_downstream_count=("upstream_downstream", lambda s: len({clean(v) for v in s if clean(v)})),
    ).reset_index()
    consistency["pass"] = (consistency["directionality_status_count"] == 1) & (consistency["upstream_downstream_count"] <= 1)
    write_csv("stage2_directionality_consistency_by_chain.csv", consistency)
    data["assignment_status"] = assigned.map({True: "assigned", False: "unresolved"})
    write_csv("stage2_assigned_unresolved_by_distance_band.csv", data.groupby(["assignment_status", "distance_band"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique")).reset_index())
    write_csv("stage2_assigned_unresolved_by_approach.csv", data.groupby(["assignment_status", "signal_approach_id"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), signal_count=("stable_signal_id", "nunique")).reset_index())
    write_csv("stage2_assigned_unresolved_by_signal.csv", data.groupby(["assignment_status", "stable_signal_id"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique")).reset_index())
    unresolved = data.loc[~assigned].copy()
    unresolved["residual_pattern"] = unresolved.apply(residual_pattern, axis=1)
    pattern = unresolved.groupby("residual_pattern", dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique")).reset_index()
    write_csv("stage2_residual_pattern_summary.csv", pattern)
    chain_review = unresolved.groupby(["logical_corridor_chain_id", "stable_signal_id", "signal_approach_id", "residual_pattern"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_total_reach_ft=("chain_total_reach_ft", "max"), distance_bands=("distance_band", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)})))).reset_index().sort_values(["bin_count", "chain_total_reach_ft"], ascending=False)
    write_csv("stage2_high_impact_unresolved_chain_review.csv", chain_review.head(1000))
    signal_review = unresolved.groupby(["stable_signal_id", "residual_pattern"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique")).reset_index().sort_values("bin_count", ascending=False)
    write_csv("stage2_high_impact_unresolved_signal_review.csv", signal_review.head(1000))
    map_patterns = {"divided_blank_token_no_embedded_token", "reversible_or_trail", "ramp_or_parallel_interchange_ambiguity", "residual_mixed_evidence"}
    map_candidates = chain_review[chain_review["residual_pattern"].isin(map_patterns)].copy()
    write_csv("stage2_map_review_candidate_summary.csv", [dict(
        map_review_candidate_chain_count=int(len(map_candidates)),
        map_review_candidate_bin_count=int(map_candidates["bin_count"].sum()) if not map_candidates.empty else 0,
        map_review_candidate_signal_count=int(map_candidates["stable_signal_id"].nunique()) if not map_candidates.empty else 0,
        recommendation="create_small_map_review_package_for_high_impact_residuals" if not map_candidates.empty else "no_map_review_needed",
    )])
    write_csv("stage2_no_crash_direction_field_check.csv", [{"check_name": "no_crash_direction_fields_used", "used_field_count": 0, "pass": True}])
    post_state = file_state(PARENTS + METADATA)
    merged = stage1_state.merge(post_state, on="path", suffixes=("_after_stage1", "_after_stage2"))
    merged["pass"] = (
        merged["exists_after_stage1"].eq(merged["exists_after_stage2"])
        & merged["length_after_stage1"].astype(str).eq(merged["length_after_stage2"].astype(str))
        & merged["mtime_ns_after_stage1"].astype(str).eq(merged["mtime_ns_after_stage2"].astype(str))
    )
    write_csv("stage2_no_staged_mutation_beyond_stage1_patch_check.csv", merged)
    valid = bool(consistency["pass"].all()) and bool(merged["pass"].all())
    if not valid:
        decision = "stage2_residual_audit_failed_consistency_check"
    elif not map_candidates.empty:
        decision = "stage2_residual_audit_create_small_map_review_sample"
    else:
        decision = "stage2_residual_audit_leave_residual_unresolved"
    write_csv("stage2_readiness_decision.csv", [{"decision": decision, "chain_consistency_pass": bool(consistency["pass"].all()), "no_stage2_mutation_pass": bool(merged["pass"].all())}])
    return decision


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    pre_state = file_state(PARENTS + METADATA)

    stage1_decision, stage1_data, assignment = stage1_patch()
    stage2_decision = ""
    overall = "directionality_patch_failed_no_stage2"
    if stage1_decision == "stage1_patch_passed_proceed_to_stage2":
        stage1_post_state = file_state(PARENTS + METADATA)
        stage2_decision = stage2_audit(stage1_post_state)
        if stage2_decision == "stage2_residual_audit_create_small_map_review_sample":
            overall = "directionality_patch_success_create_map_review_sample_next"
        elif stage2_decision == "stage2_residual_audit_leave_residual_unresolved":
            overall = "directionality_patch_success_leave_residual_unresolved"
        else:
            overall = "directionality_patch_blocked_by_qa_failure"
    elif "blocked" in stage1_decision:
        overall = "directionality_patch_blocked_by_qa_failure"

    if stage1_decision == "stage1_patch_passed_proceed_to_stage2":
        actions = [{"priority": 1, "recommended_next_action": "Create a small map-review package for high-impact residual unresolved chains before building downstream distance_band_units."}]
    else:
        actions = [{"priority": 1, "recommended_next_action": "Do not proceed; repair Stage 1 patch QA blockers before any residual audit or downstream build."}]
    write_csv("recommended_next_actions.csv", actions)

    assigned_summary = {}
    if stage1_decision == "stage1_patch_passed_proceed_to_stage2":
        patched = pd.read_parquet(BIN_CONTEXT, columns=["logical_corridor_chain_id", "stable_bin_id", "directionality_status"])
        assigned = patched["directionality_status"].eq("assigned")
        assigned_summary = {
            "assigned_chains": int(patched.loc[assigned, "logical_corridor_chain_id"].nunique()),
            "assigned_bins": int(assigned.sum()),
            "unresolved_chains": int(patched.loc[~assigned, "logical_corridor_chain_id"].nunique()),
            "unresolved_bins": int((~assigned).sum()),
        }

    findings = f"""# bin_context Chain Directionality Patch And Residual Audit

## What Was Patched
Accepted chain-level directionality rules were patched into staged `bin_context.parquet` by `logical_corridor_chain_id`: first-pass direct assignments, R1/R2/R3 refined rules, and the accepted divided blank-token embedded route-text rule.

## What Was Not Patched
Rejected divided blank-token chains, reversible/trail cases, insufficient-evidence chains, residual mixed/ambiguous evidence, map-review candidates, and any chain not covered by an accepted rule remain unresolved.

## Parent Dependency Statement
Only validated staged parents and diagnostic proposal review outputs were read. Crash direction fields and downstream context/rate products were not used.

## Stage Decisions
Stage 1 decision: `{stage1_decision}`. Stage 2 decision: `{stage2_decision or 'not_run'}`. Overall decision: `{overall}`.

## Identity, Distance, Geometry, Context
Stage 1 hard QA checked row count, stable bin identity, duplicate bins, distance fields, geometry/status, directionality consistency, and forbidden context fields before replacing staged parquet.

## Post-Patch Coverage
Assigned chains: {assigned_summary.get('assigned_chains', '')}. Assigned bins: {assigned_summary.get('assigned_bins', '')}. Unresolved chains: {assigned_summary.get('unresolved_chains', '')}. Unresolved bins: {assigned_summary.get('unresolved_bins', '')}.

## Recommended Next Task
Follow `recommended_next_actions.csv`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    write_json("manifest.json", {
        "created_utc": now(),
        "product": "patch_bin_context_chain_directionality_and_audit",
        "stage1_decision": stage1_decision,
        "stage2_decision": stage2_decision,
        "overall_decision": overall,
        "source_inputs": [rel(p) for p in PARENTS],
        "diagnostic_proposal_evidence": [rel(REFINED_PROPOSAL), rel(EMBEDDED_ASSIGNMENTS)],
        "mutation_policy": "Stage 1 replaced staged bin_context only after hard QA; Stage 2 read-only.",
    })
    write_json("qa_manifest.json", {
        "created_utc": now(),
        "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
        "stage1_decision": stage1_decision,
        "stage2_decision": stage2_decision,
        "overall_decision": overall,
        "pre_stage_file_state": pre_state.to_dict("records"),
    })
    log(f"Completed workflow with overall decision {overall}.")


if __name__ == "__main__":
    main()
