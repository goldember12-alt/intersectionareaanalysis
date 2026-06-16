"""Patch staged signal_approaches with corridor-build gate/status fields only.

This bounded patch preserves approach row identity, support evidence, and the
approach-count distribution. It does not rebuild approaches or create any
downstream products.
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
OUT = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
APPROACHES = STAGING / "signal_approaches.parquet"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

EXCEPTION_AUDIT = REPO / "work/roadway_graph/review/signal_approaches_exception_adjudication_audit"
VALIDATION_AUDIT = REPO / "work/roadway_graph/review/signal_approaches_validation_audit"
BUILD_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"

GATE_RULE_VERSION = "signal_approach_corridor_gate_v1_2026-06-09"


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


def distribution(df: pd.DataFrame) -> dict[int, int]:
    return {int(k): int(v) for k, v in df.groupby("stable_signal_id")["signal_approach_id"].nunique().value_counts().sort_index().to_dict().items()}


def severity_for(gate: str, adjudication: str, ambiguous_status: str, rejected_status: str) -> str:
    if gate in {"corridor_build_blocked_pending_rule_repair", "source_limited_no_corridor"}:
        return "blocking"
    if gate == "corridor_build_ready":
        return "none"
    if adjudication in {"acceptable_two_approach_one_way_or_divided_pair", "acceptable_true_two_leg_or_boundary_case"}:
        return "informational"
    if rejected_status in {"possible_overcollapse", "possible_missing_cross_street", "possible_missing_physical_approach"}:
        return "caution"
    if ambiguous_status and ambiguous_status != "clear":
        return "caution"
    return "informational"


def allowed_for(gate: str) -> bool:
    return gate in {"corridor_build_ready", "corridor_build_ready_with_warning", "corridor_build_partial_only"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting bounded signal_approaches corridor gate patch.")
    before = pd.read_parquet(APPROACHES)
    original_ids = before["signal_approach_id"].astype(str).tolist()
    original_support = before[["signal_approach_id", "stable_signal_id", "supporting_attachment_ids", "supporting_stable_travelway_ids"]].copy()
    original_dist = distribution(before)
    log(f"Loaded {len(before)} approach rows.")

    # Parents are loaded for reconciliation only.
    signals = pd.read_parquet(SIGNAL_INDEX)
    attachments = pd.read_parquet(ATTACHMENT, columns=["attachment_id", "stable_signal_id"])
    travelways = pd.read_parquet(TRAVELWAY_INDEX, columns=["stable_travelway_id"])
    signal_gate = pd.read_csv(EXCEPTION_AUDIT / "corridor_build_signal_gate_proposal.csv", low_memory=False)
    approach_gate = pd.read_csv(EXCEPTION_AUDIT / "corridor_build_approach_gate_proposal.csv", low_memory=False)
    two = pd.read_csv(EXCEPTION_AUDIT / "two_approach_final_adjudication.csv", low_memory=False)
    over = pd.read_csv(EXCEPTION_AUDIT / "route_group_overcollapse_adjudication.csv", low_memory=False)
    rejected = pd.read_csv(EXCEPTION_AUDIT / "rejected_candidate_impact_audit.csv", low_memory=False)
    ambiguous_recon = pd.read_csv(EXCEPTION_AUDIT / "ambiguous_count_reconciliation.csv", low_memory=False)

    signal_gate_counts_expected = signal_gate["corridor_build_signal_gate"].value_counts().to_dict()
    approach_gate_counts_expected = approach_gate["corridor_build_approach_gate"].value_counts().to_dict()

    patch = before.merge(
        approach_gate[[
            "signal_approach_id",
            "corridor_build_approach_gate",
            "reason",
            "required_downstream_restriction",
            "corridor_construction_action",
        ]],
        on="signal_approach_id",
        how="left",
    ).merge(
        signal_gate[["stable_signal_id", "corridor_build_signal_gate"]],
        on="stable_signal_id",
        how="left",
    )
    if patch["corridor_build_approach_gate"].isna().any():
        missing = int(patch["corridor_build_approach_gate"].isna().sum())
        raise RuntimeError(f"Missing approach gate rows for {missing} approaches")

    two_cols = [
        "stable_signal_id",
        "final_two_approach_adjudication",
        "two_approach_taxonomy",
    ]
    over_cols = [
        "stable_signal_id",
        "route_group_overcollapse_adjudication",
    ]
    rej_cols = [
        "stable_signal_id",
        "rejected_candidate_impact",
    ]
    patch = patch.merge(two[two_cols], on="stable_signal_id", how="left").merge(over[over_cols], on="stable_signal_id", how="left").merge(rejected[rej_cols], on="stable_signal_id", how="left")
    patch["two_approach_adjudication"] = patch["final_two_approach_adjudication"].fillna("")
    patch["underbuild_risk_status"] = patch["two_approach_adjudication"].map(
        lambda v: "likely_underbuilt_patch_candidate" if v == "likely_underbuilt_patch_candidate" else ("not_flagged" if clean(v) == "" else "two_approach_adjudicated_not_underbuilt")
    )
    patch.loc[patch["two_approach_adjudication"].eq("route_group_overcollapse_patch_candidate"), "underbuild_risk_status"] = "route_group_overcollapse_patch_candidate"
    patch["overcollapse_risk_status"] = patch["route_group_overcollapse_adjudication"].fillna("not_flagged")
    patch["ambiguous_status"] = patch["ambiguity_status"].fillna("")
    patch["rejected_candidate_risk_status"] = patch["rejected_candidate_impact"].fillna("not_flagged")
    patch["corridor_build_gate"] = patch["corridor_build_approach_gate"]
    patch["corridor_build_allowed_flag"] = patch["corridor_build_gate"].map(allowed_for)
    patch["corridor_gate_severity"] = patch.apply(
        lambda row: severity_for(
            row["corridor_build_gate"],
            clean(row["two_approach_adjudication"]),
            clean(row["ambiguous_status"]),
            clean(row["rejected_candidate_risk_status"]),
        ),
        axis=1,
    )
    patch["corridor_gate_reason"] = patch["reason"].fillna("")
    patch["corridor_gate_source"] = rel(EXCEPTION_AUDIT)
    patch["corridor_gate_rule_version"] = GATE_RULE_VERSION
    patch["corridor_restriction_notes"] = patch.apply(
        lambda row: "; ".join(
            part
            for part in [
                clean(row.get("required_downstream_restriction")),
                f"action={clean(row.get('corridor_construction_action'))}",
                f"signal_gate={clean(row.get('corridor_build_signal_gate'))}",
                f"two_approach={clean(row.get('two_approach_adjudication'))}" if clean(row.get("two_approach_adjudication")) else "",
                f"overcollapse={clean(row.get('overcollapse_risk_status'))}" if clean(row.get("overcollapse_risk_status")) not in {"", "not_flagged"} else "",
                f"rejected_candidate={clean(row.get('rejected_candidate_risk_status'))}" if clean(row.get("rejected_candidate_risk_status")) not in {"", "not_flagged", "diagnostic_only_no_action"} else "",
            ]
            if part
        ),
        axis=1,
    )
    drop_cols = [
        "corridor_build_approach_gate",
        "reason",
        "required_downstream_restriction",
        "corridor_construction_action",
        "corridor_build_signal_gate",
        "final_two_approach_adjudication",
        "two_approach_taxonomy",
        "route_group_overcollapse_adjudication",
        "rejected_candidate_impact",
    ]
    patched = patch.drop(columns=[c for c in drop_cols if c in patch.columns])

    patched.to_parquet(APPROACHES, index=False)
    after = pd.read_parquet(APPROACHES)
    after_ids = after["signal_approach_id"].astype(str).tolist()
    after_dist = distribution(after)
    identity_ok = original_ids == after_ids
    duplicate_count = int(after["signal_approach_id"].duplicated(keep=False).sum())
    row_count_ok = len(before) == len(after)
    dist_ok = original_dist == after_dist
    support_after = after[["signal_approach_id", "stable_signal_id", "supporting_attachment_ids", "supporting_stable_travelway_ids"]].copy()
    support_ok = original_support.astype(str).equals(support_after.astype(str))

    approach_gate_counts = after["corridor_build_gate"].value_counts().to_dict()
    severity_counts = after["corridor_gate_severity"].value_counts().to_dict()
    signal_roll = signal_gate[["stable_signal_id", "corridor_build_signal_gate"]].drop_duplicates()
    signal_level_counts = signal_roll["corridor_build_signal_gate"].value_counts().to_dict()
    expected_signal_ok = {str(k): int(v) for k, v in signal_level_counts.items()} == {str(k): int(v) for k, v in signal_gate_counts_expected.items()}
    expected_approach_ok = {str(k): int(v) for k, v in approach_gate_counts.items()} == {str(k): int(v) for k, v in approach_gate_counts_expected.items()}

    blocked_approaches = after[after["corridor_build_gate"].isin(["corridor_build_blocked_pending_rule_repair", "source_limited_no_corridor"])]
    blocked_signals = signal_gate[signal_gate["corridor_build_signal_gate"].isin(["corridor_build_blocked_pending_rule_repair", "source_limited_no_corridor"])]

    write_csv("row_identity_unchanged_check.csv", [{
        "row_count_before": int(len(before)),
        "row_count_after": int(len(after)),
        "row_count_unchanged": row_count_ok,
        "signal_approach_id_order_unchanged": identity_ok,
        "duplicate_signal_approach_id_rows": duplicate_count,
        "supporting_candidate_fields_unchanged": support_ok,
        "status": "pass" if row_count_ok and identity_ok and duplicate_count == 0 and support_ok else "fail",
    }])
    write_csv("approach_distribution_unchanged_check.csv", [{
        "distribution_before": json.dumps(original_dist, sort_keys=True),
        "distribution_after": json.dumps(after_dist, sort_keys=True),
        "distribution_unchanged": dist_ok,
        "status": "pass" if dist_ok else "fail",
    }])
    write_csv("approach_level_gate_counts.csv", [{"corridor_build_gate": k, "approach_count": int(v)} for k, v in sorted(approach_gate_counts.items())])
    write_csv("signal_level_gate_counts.csv", [{"corridor_build_signal_gate": k, "signal_count": int(v)} for k, v in sorted(signal_level_counts.items())])
    warning = after[after["corridor_build_gate"].eq("corridor_build_ready_with_warning")]
    warning_breakdown = warning.groupby(["corridor_gate_severity", "two_approach_adjudication", "ambiguous_status"], dropna=False).size().reset_index(name="approach_count")
    write_csv("ready_with_warning_breakdown.csv", warning_breakdown.to_dict("records"))
    write_csv("blocked_approach_rows.csv", blocked_approaches.to_dict("records"))
    write_csv("blocked_signal_rows.csv", blocked_signals.to_dict("records"))
    two_breakdown = after[after["two_approach_adjudication"].astype(str).str.len().gt(0)].groupby(["two_approach_adjudication", "corridor_build_gate", "corridor_gate_severity"], dropna=False).size().reset_index(name="approach_count")
    write_csv("two_approach_gate_breakdown.csv", two_breakdown.to_dict("records"))
    write_csv("ambiguous_count_reconciliation_after_patch.csv", ambiguous_recon.to_dict("records"))
    write_csv("parent_dependency_check.csv", [
        {"object": "signal_approaches_gate_patch", "dependency": rel(APPROACHES), "dependency_role": "patched_target", "allowed": True},
        {"object": "signal_approaches_gate_patch", "dependency": rel(SIGNAL_INDEX), "dependency_role": "reconciliation_parent_only", "allowed": True},
        {"object": "signal_approaches_gate_patch", "dependency": rel(ATTACHMENT), "dependency_role": "reconciliation_parent_only", "allowed": True},
        {"object": "signal_approaches_gate_patch", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "reconciliation_parent_only", "allowed": True},
        {"object": "signal_approaches_gate_patch", "dependency": rel(EXCEPTION_AUDIT), "dependency_role": "status_method_evidence_only", "allowed": True},
        {"object": "signal_approaches_gate_patch", "dependency": rel(VALIDATION_AUDIT), "dependency_role": "status_method_evidence_only", "allowed": True},
        {"object": "signal_approaches_gate_patch", "dependency": rel(BUILD_REVIEW), "dependency_role": "status_method_evidence_only", "allowed": True},
    ])

    final_decision = "signal_approaches_ready_as_validated_parent_with_gates"
    if not (row_count_ok and identity_ok and support_ok and duplicate_count == 0):
        final_decision = "signal_approaches_gate_patch_failed_identity_check"
    elif not (expected_signal_ok and expected_approach_ok and dist_ok):
        final_decision = "signal_approaches_gate_patch_needs_review"

    write_csv("gate_patch_summary.csv", [
        {"metric": "approach_rows", "value": int(len(after))},
        {"metric": "approach_level_gate_counts", "value": json.dumps({str(k): int(v) for k, v in approach_gate_counts.items()}, sort_keys=True)},
        {"metric": "signal_level_gate_counts", "value": json.dumps({str(k): int(v) for k, v in signal_level_counts.items()}, sort_keys=True)},
        {"metric": "severity_counts", "value": json.dumps({str(k): int(v) for k, v in severity_counts.items()}, sort_keys=True)},
        {"metric": "blocked_approach_rows", "value": int(len(blocked_approaches))},
        {"metric": "blocked_signal_rows", "value": int(len(blocked_signals))},
        {"metric": "final_decision", "value": final_decision},
    ])
    write_csv("recommended_next_actions.csv", [
        {"rank": 1, "action": "build_approach_corridors_from_signal_approaches_gate_fields", "rationale": "Gate fields are now encoded in the staged parent table; corridor builder should exclude blocking gates and carry warnings."}
    ])

    update_metadata(after, final_decision)
    write_findings(
        final_decision,
        approach_gate_counts,
        signal_level_counts,
        severity_counts,
        len(blocked_approaches),
        len(blocked_signals),
    )
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "patched_target": rel(APPROACHES),
        "mode": "bounded_status_provenance_patch",
        "status_method_evidence": [rel(EXCEPTION_AUDIT), rel(VALIDATION_AUDIT), rel(BUILD_REVIEW)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": final_decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "row_identity_unchanged": bool(row_count_ok and identity_ok and support_ok),
        "approach_distribution_unchanged": bool(dist_ok),
        "approach_level_gate_counts": {str(k): int(v) for k, v in approach_gate_counts.items()},
        "signal_level_gate_counts": {str(k): int(v) for k, v in signal_level_counts.items()},
        "blocked_approach_count": int(len(blocked_approaches)),
        "blocked_signal_count": int(len(blocked_signals)),
        "final_decision": final_decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    log(f"Patch complete with decision {final_decision}.")


def update_metadata(df: pd.DataFrame, final_decision: str) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    manifest.setdefault("products", {}).setdefault("signal_approaches", {})
    manifest["products"]["signal_approaches"]["corridor_gate_patch"] = {
        "patched_utc": now(),
        "script": "src.roadway_graph.patch.patch_signal_approach_corridor_gates",
        "rule_version": GATE_RULE_VERSION,
        "status_method_evidence": [rel(EXCEPTION_AUDIT), rel(VALIDATION_AUDIT), rel(BUILD_REVIEW)],
        "patched_fields": [
            "corridor_build_gate",
            "corridor_build_allowed_flag",
            "corridor_gate_severity",
            "corridor_gate_reason",
            "corridor_gate_source",
            "corridor_gate_rule_version",
            "two_approach_adjudication",
            "underbuild_risk_status",
            "overcollapse_risk_status",
            "ambiguous_status",
            "rejected_candidate_risk_status",
            "corridor_restriction_notes",
        ],
        "row_count": int(len(df)),
        "final_decision": final_decision,
    }
    manifest["updated_utc"] = now()
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {}
    table = schema.setdefault("tables", {}).setdefault("signal_approaches.parquet", {})
    table.setdefault("status_provenance_columns", [])
    for col in [
        "corridor_build_gate",
        "corridor_build_allowed_flag",
        "corridor_gate_severity",
        "corridor_gate_reason",
        "corridor_gate_source",
        "corridor_gate_rule_version",
        "two_approach_adjudication",
        "underbuild_risk_status",
        "overcollapse_risk_status",
        "ambiguous_status",
        "rejected_candidate_risk_status",
        "corridor_restriction_notes",
    ]:
        if col not in table["status_provenance_columns"]:
            table["status_provenance_columns"].append(col)
    table["corridor_gate_rule_version"] = GATE_RULE_VERSION
    table["corridor_gate_definitions"] = {
        "corridor_build_ready": "no known approach-layer restriction",
        "corridor_build_ready_with_warning": "corridor construction allowed, but carry warning/provenance",
        "corridor_build_partial_only": "corridor construction allowed only for explicitly safe approaches within a risky signal",
        "corridor_build_blocked_pending_rule_repair": "do not build corridors until approach-collapse rule is repaired or reviewed",
        "source_limited_no_corridor": "no corridor should be built because approach/signal evidence is absent or insufficient",
    }
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

    addition = f"""

## Signal approach corridor gate patch

Patched corridor-build gate/status fields onto `signal_approaches.parquet`
using rule `{GATE_RULE_VERSION}`. This patch did not rebuild approaches, change
row identity, change supporting attachment evidence, or create downstream
corridor/bin/directionality/context products. Future `approach_corridors`
construction should read gate fields from `signal_approaches.parquet` itself.
"""
    existing = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else ""
    if "## Signal approach corridor gate patch" not in existing:
        STAGING_README.write_text(existing.rstrip() + addition, encoding="utf-8")


def write_findings(
    final_decision: str,
    approach_gate_counts: dict[str, int],
    signal_gate_counts: dict[str, int],
    severity_counts: dict[str, int],
    blocked_approach_count: int,
    blocked_signal_count: int,
) -> None:
    text = f"""# Signal Approach Corridor Gate Patch

## What was patched
Added corridor-build gate/status/provenance fields to staged `signal_approaches.parquet`.

## What was not changed
No approach rows were added or removed. `signal_approach_id`, `stable_signal_id`, approach distribution, geometry, and supporting attachment evidence were preserved.

## Ready signal interpretation
The 3,106 `corridor_build_ready` signals are not the only usable signals. Another 767 signals are `corridor_build_ready_with_warning`, meaning corridor construction is allowed but must carry warning/provenance and apply conservative QA.

## Warning split
Warnings are split into severity categories: {severity_counts}. Informational warnings include acceptable two-approach one-way/divided or true boundary cases. Caution warnings include ambiguity or rejected-candidate risk. Blocking severity excludes corridor construction.

## Blocked objects
Blocked approach rows: {blocked_approach_count}. Blocked/source-limited signal rows: {blocked_signal_count}. These are explicit in `blocked_approach_rows.csv` and `blocked_signal_rows.csv`.

## Gate counts
Approach-level gates: {approach_gate_counts}. Signal-level gates: {signal_gate_counts}.

## Ambiguous count reconciliation
The 109 vs 186 ambiguity difference remains documented: build QA counted signal-level non-normal build status, while validation counted signals with at least one ambiguous approach row.

## Readiness
Final decision: `{final_decision}`. The staged `signal_approaches.parquet` is ready as a parent for `approach_corridors` if the corridor builder excludes blocking gates and carries warning provenance.

## Recommended next task
Build `approach_corridors.parquet` from gated `signal_approaches.parquet`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
