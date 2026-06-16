"""Patch staged signal_index readiness/status fields only.

This bounded Phase B.1 repair consumes the accepted recommended_rule output
from signal_analysis_readiness_rule_discovery and updates only readiness,
status, and provenance fields in the fresh rebuild candidate signal_index.
It does not change source artifacts, canonical products, row identity,
stable_signal_id, geometry, or downstream cache objects.
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
SIGNAL_INDEX = STAGING / "signal_index.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"
SOURCE = REPO / "artifacts/normalized/signals.parquet"

DISCOVERY = REPO / "work/roadway_graph/review/signal_analysis_readiness_rule_discovery"
READINESS_AUDIT = REPO / "work/roadway_graph/review/signal_index_readiness_audit"
RULE_APPLICATION = DISCOVERY / "signal_readiness_rule_application.csv"
PRIOR_CROSSWALK = READINESS_AUDIT / "prior_to_new_stable_signal_crosswalk.csv"
OUT = REPO / "work/roadway_graph/review/patch_signal_index_readiness_status"

RULE_VERSION = "signal_analysis_readiness_recommended_rule_v1_2026-06-09"
EXPECTED_ROWS = 3933
EXPECTED_READY = 3912
EXPECTED_NOT_READY = 21
EXPECTED_CONFIDENCE = {"high": 3849, "medium": 63, "low": 21}


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


def nonblank(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>", "nat"])


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def load_recommended_rule() -> pd.DataFrame:
    app = pd.read_csv(RULE_APPLICATION)
    rec = app[app["readiness_rule_variant"].eq("recommended_rule")].copy()
    if len(rec) != EXPECTED_ROWS:
        raise ValueError(f"Recommended rule row count {len(rec)} != {EXPECTED_ROWS}")
    if rec["signal_index_row_id"].duplicated().any():
        raise ValueError("Recommended rule has duplicate signal_index_row_id values")
    return rec


def build_prior_crosswalk() -> pd.DataFrame:
    cw = pd.read_csv(PRIOR_CROSSWALK)
    matched = cw[cw["signal_index_stable_signal_id"].map(clean).ne("")].copy()
    if matched.empty:
        return pd.DataFrame(
            columns=[
                "stable_signal_id",
                "prior_canonical_match_status",
                "prior_canonical_match_method",
                "prior_canonical_stable_signal_id",
            ]
        )
    matched["match_rank"] = matched["one_to_one_status"].map({"matched_unique": 0, "matched_reused_signal_index_row": 1}).fillna(9)
    matched["confidence_rank"] = matched["match_confidence"].map({"high": 0, "medium": 1, "low": 2, "none": 9}).fillna(9)
    matched = matched.sort_values(["signal_index_stable_signal_id", "match_rank", "confidence_rank", "canonical_row_number"])
    grouped = (
        matched.groupby("signal_index_stable_signal_id", dropna=False)
        .agg(
            prior_canonical_match_status=("one_to_one_status", "first"),
            prior_canonical_match_method=("match_method", "first"),
            prior_canonical_stable_signal_id=("prior_canonical_stable_signal_id", "first"),
            prior_canonical_match_count=("prior_canonical_stable_signal_id", "count"),
        )
        .reset_index()
        .rename(columns={"signal_index_stable_signal_id": "stable_signal_id"})
    )
    return grouped


def patch_signal_index(original: pd.DataFrame, rec: pd.DataFrame, prior: pd.DataFrame) -> pd.DataFrame:
    patched = original.copy()
    join_cols = [
        "signal_index_row_id",
        "proposed_analysis_ready_status",
        "proposed_source_limited_status",
        "proposed_holdout_reason",
        "readiness_evidence_fields",
        "confidence",
        "nearest_travelway_distance_ft",
        "travelway_candidate_count_250ft",
        "unique_route_count_250ft",
        "nearest_route_name",
    ]
    merged = patched[["signal_index_row_id", "stable_signal_id"]].merge(rec[join_cols + ["stable_signal_id"]], on="signal_index_row_id", how="left", suffixes=("", "_rule"))
    if merged["proposed_analysis_ready_status"].isna().any():
        raise ValueError("Some signal_index rows lack recommended_rule status")
    if not merged["stable_signal_id"].eq(merged["stable_signal_id_rule"]).all():
        raise ValueError("Recommended rule stable_signal_id does not match signal_index for all rows")

    rule_by_id = rec.set_index("signal_index_row_id")
    patched["analysis_ready_status"] = patched["signal_index_row_id"].map(rule_by_id["proposed_analysis_ready_status"])
    patched["analysis_ready_rule"] = "recommended_rule"
    patched["analysis_ready_confidence"] = patched["signal_index_row_id"].map(rule_by_id["confidence"])
    patched["analysis_ready_evidence_fields"] = patched["signal_index_row_id"].map(rule_by_id["readiness_evidence_fields"])
    patched["readiness_rule_version"] = RULE_VERSION

    is_ready = patched["analysis_ready_status"].eq("analysis_ready")
    patched["source_limited_status"] = "not_source_limited"
    patched["source_limited_reason"] = ""
    patched["holdout_reason"] = ""
    patched.loc[~is_ready, "source_limited_status"] = "attachment_limited"
    patched.loc[~is_ready, "source_limited_reason"] = "no normalized Travelway within 250 ft under accepted source-rooted readiness rule"
    patched.loc[~is_ready, "holdout_reason"] = "not_analysis_ready_geometry_or_attachment_limited_pending_signal_travelway_attachment"

    patched["nearest_travelway_distance_ft_readiness"] = patched["signal_index_row_id"].map(rule_by_id["nearest_travelway_distance_ft"])
    patched["travelway_candidate_count_250ft_readiness"] = patched["signal_index_row_id"].map(rule_by_id["travelway_candidate_count_250ft"])
    patched["unique_route_count_250ft_readiness"] = patched["signal_index_row_id"].map(rule_by_id["unique_route_count_250ft"])
    patched["nearest_route_name_readiness"] = patched["signal_index_row_id"].map(rule_by_id["nearest_route_name"])

    patched = patched.merge(prior, on="stable_signal_id", how="left")
    patched["prior_canonical_match_status"] = patched["prior_canonical_match_status"].fillna("unmatched_to_prior_canonical")
    patched["prior_canonical_match_method"] = patched["prior_canonical_match_method"].fillna("")
    patched["prior_canonical_stable_signal_id"] = patched["prior_canonical_stable_signal_id"].fillna("")
    patched["prior_canonical_match_count"] = patched["prior_canonical_match_count"].fillna(0).astype(int)
    patched["signal_index_validation_status"] = "validated_parent_ready_phase_b1"
    return patched


def unchanged_checks(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, Any]:
    checks = {
        "row_count_before": len(before),
        "row_count_after": len(after),
        "row_count_unchanged": len(before) == len(after),
        "stable_signal_id_unchanged_all_rows": before["stable_signal_id"].reset_index(drop=True).equals(after["stable_signal_id"].reset_index(drop=True)),
        "stable_signal_id_duplicate_count_before": int(before["stable_signal_id"].duplicated().sum()),
        "stable_signal_id_duplicate_count_after": int(after["stable_signal_id"].duplicated().sum()),
        "source_row_number_unchanged_all_rows": before["source_row_number"].reset_index(drop=True).equals(after["source_row_number"].reset_index(drop=True)),
        "geometry_hash_unchanged_all_rows": before["signal_geometry_hash"].reset_index(drop=True).equals(after["signal_geometry_hash"].reset_index(drop=True)),
    }
    return checks


def update_metadata(patched: pd.DataFrame, checks: dict[str, Any], qa: dict[str, bool]) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8"))
    parents = manifest.get("parents", [])
    history = manifest.get("patch_history", [])
    history.append(
        {
            "patched_utc": now(),
            "script": "src.roadway_graph.patch.patch_signal_index_readiness_status",
            "bounded_phase": "Phase B.1 readiness/status repair only",
            "method_status_evidence": rel(DISCOVERY),
            "canonical_parents_unchanged": parents,
            "readiness_rule_version": RULE_VERSION,
            "analysis_ready_count": int(patched["analysis_ready_status"].eq("analysis_ready").sum()),
            "not_ready_count": int((~patched["analysis_ready_status"].eq("analysis_ready")).sum()),
        }
    )
    manifest.update(
        {
            "updated_utc": now(),
            "phase_b1_status_patch_applied": True,
            "readiness_rule_version": RULE_VERSION,
            "parents": parents,
            "method_or_status_evidence_only": sorted(set(manifest.get("comparison_or_method_evidence_only", []) + [rel(DISCOVERY), rel(READINESS_AUDIT)])),
            "analysis_ready_status_counts": patched["analysis_ready_status"].value_counts(dropna=False).to_dict(),
            "analysis_ready_confidence_counts": patched["analysis_ready_confidence"].value_counts(dropna=False).to_dict(),
            "signal_index_validation_status_counts": patched["signal_index_validation_status"].value_counts(dropna=False).to_dict(),
            "patch_acceptance": qa,
            "unchanged_checks": checks,
            "patch_history": history,
        }
    )
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8"))
    schema["updated_utc"] = now()
    schema["readiness_rule_version"] = RULE_VERSION
    schema["readiness_confidence_definition"] = {
        "high": "source-rooted identity and geometry present; nearest normalized Travelway within 175 ft with at least two Travelway candidates within 250 ft",
        "medium": "source-rooted identity and geometry present; normalized Travelway within 250 ft but conservative high-confidence proximity/candidate threshold not met",
        "low": "source-rooted identity and geometry present but no normalized Travelway within 250 ft; not analysis-ready until attachment/source review",
    }
    schema["columns"] = [{"name": col, "dtype": str(patched[col].dtype)} for col in patched.columns]
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

    readme = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else "# final_leg_corrected_analysis_dataset_rebuild_candidate\n"
    patch_section = f"""

## Phase B.1 Readiness Status Patch

Patched UTC: {now()}

Only readiness/status/provenance fields in `signal_index.parquet` were updated. Row identity, `stable_signal_id`, source row lineage, and geometry were not changed.

Canonical parent remains `artifacts/normalized/signals.parquet` only. `work/roadway_graph/review/signal_analysis_readiness_rule_discovery/` is method/status evidence, not a canonical parent.

Readiness rule version: `{RULE_VERSION}`

Confidence definitions:
- high: source-rooted identity and geometry present; nearest normalized Travelway within 175 ft with at least two Travelway candidates within 250 ft.
- medium: source-rooted identity and geometry present; normalized Travelway within 250 ft but conservative high-confidence proximity/candidate threshold not met.
- low: source-rooted identity and geometry present but no normalized Travelway within 250 ft; not analysis-ready until attachment/source review.
"""
    STAGING_README.write_text(readme.rstrip() + "\n" + patch_section, encoding="utf-8")


def findings_text(decision: str, ready: int, not_ready: int) -> str:
    return f"""# Signal Index Readiness Status Patch Findings

## What Was Patched

Only Phase B.1 readiness/status/provenance fields were patched in the staged `signal_index.parquet`: `analysis_ready_status`, `analysis_ready_rule`, `analysis_ready_confidence`, `analysis_ready_evidence_fields`, `source_limited_status`, `source_limited_reason`, `holdout_reason`, `readiness_rule_version`, prior canonical comparison fields, and `signal_index_validation_status`.

## What Was Not Changed

The patch did not change row count, `stable_signal_id`, source row numbers, source identifiers, geometry, geometry hashes, source artifacts, canonical products, or any downstream cache objects.

## Why stable_signal_id Does Not Equal Analysis Readiness

`stable_signal_id` is durable project identity for every source signal row. Analysis readiness is a separate eligibility/status field based on source-rooted identity, geometry, and nearby normalized Travelway evidence.

## Final Counts

- Analysis-ready rows: {ready:,}
- Not-ready / geometry-or-attachment-limited rows: {not_ready:,}

## Confidence Definitions

- high: source-rooted identity and geometry present; nearest normalized Travelway within 175 ft with at least two Travelway candidates within 250 ft.
- medium: source-rooted identity and geometry present; normalized Travelway within 250 ft but conservative high-confidence proximity/candidate threshold not met.
- low: source-rooted identity and geometry present but no normalized Travelway within 250 ft; not analysis-ready until attachment/source review.

## Interpreting The Old 3,719

The old 3,719 canonical signal count remains comparison/status evidence from a narrower prior pipeline. It is not used as a parent and does not overwrite source-rooted stable IDs. Prior canonical match fields are carried as provenance where the prior crosswalk found a match.

## Readiness Decision

Decision: `{decision}`.

## Recommended Next Implementation Task

Implement Phase B.2 only: build `travelway_network_index.parquet` from `artifacts/normalized/roads.parquet`. Do not build signal-to-Travelway attachment until both base indexes are validated.
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Started bounded Phase B.1 readiness/status patch.")

    before = pd.read_parquet(SIGNAL_INDEX)
    source = pd.read_parquet(SOURCE)
    rec = load_recommended_rule()
    prior = build_prior_crosswalk()
    log("Loaded staged signal_index, source parent, accepted readiness rule, and prior crosswalk evidence.")

    patched = patch_signal_index(before, rec, prior)
    checks = unchanged_checks(before, patched)
    ready = int(patched["analysis_ready_status"].eq("analysis_ready").sum())
    not_ready = int((~patched["analysis_ready_status"].eq("analysis_ready")).sum())
    conf_counts = patched["analysis_ready_confidence"].value_counts(dropna=False).to_dict()
    parent_manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8"))
    parents_before = parent_manifest.get("parents", [])
    parent_ok = parents_before == [rel(SOURCE)]
    no_downstream_parent = all("bin_context" not in p and "analysis_signal.csv" not in p and "projection" not in p for p in parents_before)

    qa = {
        "row_count_remains_3933": len(patched) == EXPECTED_ROWS and checks["row_count_unchanged"],
        "stable_signal_id_unchanged_all_rows": bool(checks["stable_signal_id_unchanged_all_rows"]),
        "duplicate_stable_signal_id_count_zero": checks["stable_signal_id_duplicate_count_after"] == 0,
        "analysis_ready_count_3912": ready == EXPECTED_READY,
        "not_ready_count_21": not_ready == EXPECTED_NOT_READY,
        "confidence_counts_reconcile": all(int(conf_counts.get(k, 0)) == v for k, v in EXPECTED_CONFIDENCE.items()),
        "geometry_hash_unchanged_all_rows": bool(checks["geometry_hash_unchanged_all_rows"]),
        "source_row_count_reconciles": len(source) == len(patched) == EXPECTED_ROWS,
        "manifest_parent_list_source_only": parent_ok,
        "no_downstream_parent_listed": no_downstream_parent,
    }
    decision = "signal_index_ready_as_validated_parent" if all(qa.values()) else "signal_index_patch_failed_row_or_id_change"
    if ready != EXPECTED_READY or not_ready != EXPECTED_NOT_READY:
        decision = "signal_index_patch_blocked_by_readiness_rule_gap"

    if decision == "signal_index_ready_as_validated_parent":
        patched.to_parquet(SIGNAL_INDEX, index=False)
        update_metadata(patched, checks, qa)
        log("Wrote patched staged signal_index and updated staging metadata.")
    else:
        log(f"Patch not written because decision was {decision}.")

    write_csv(
        "readiness_patch_summary.csv",
        [
            {
                "decision": decision,
                "row_count_before": len(before),
                "row_count_after": len(patched),
                "analysis_ready_count": ready,
                "not_ready_count": not_ready,
                "readiness_rule_version": RULE_VERSION,
            }
        ],
    )
    write_csv("readiness_status_counts_after_patch.csv", [{"analysis_ready_status": k, "row_count": int(v)} for k, v in patched["analysis_ready_status"].value_counts(dropna=False).items()])
    write_csv(
        "readiness_confidence_definition.csv",
        [
            {"confidence": "high", "definition": "source-rooted identity and geometry present; nearest normalized Travelway within 175 ft with at least two Travelway candidates within 250 ft", "row_count": int(conf_counts.get("high", 0))},
            {"confidence": "medium", "definition": "source-rooted identity and geometry present; normalized Travelway within 250 ft but conservative high-confidence proximity/candidate threshold not met", "row_count": int(conf_counts.get("medium", 0))},
            {"confidence": "low", "definition": "source-rooted identity and geometry present but no normalized Travelway within 250 ft; not analysis-ready until attachment/source review", "row_count": int(conf_counts.get("low", 0))},
        ],
    )
    no_geom_cols = [c for c in patched.columns if c != "geometry"]
    patched.loc[~patched["analysis_ready_status"].eq("analysis_ready"), no_geom_cols].to_csv(OUT / "patched_not_ready_signal_rows.csv", index=False)
    patched.loc[patched["analysis_ready_confidence"].eq("medium"), no_geom_cols].to_csv(OUT / "patched_medium_confidence_signal_rows.csv", index=False)
    write_csv("stable_signal_id_unchanged_check.csv", [checks])
    write_csv(
        "source_row_reconciliation_after_patch.csv",
        [
            {
                "check_name": "source_row_count_reconciles",
                "source_rows": len(source),
                "signal_index_rows_after_patch": len(patched),
                "difference": len(source) - len(patched),
                "status": "pass" if len(source) == len(patched) else "fail",
            },
            {
                "check_name": "source_row_number_unique",
                "source_rows": len(source),
                "signal_index_unique_source_row_numbers": int(patched["source_row_number"].nunique()),
                "difference": len(source) - int(patched["source_row_number"].nunique()),
                "status": "pass" if len(source) == int(patched["source_row_number"].nunique()) else "fail",
            },
        ],
    )
    write_csv(
        "parent_dependency_check_after_patch.csv",
        [
            {
                "dependency_type": "canonical_parent",
                "path": rel(SOURCE),
                "listed_in_manifest_parent": parent_ok,
                "allowed": True,
                "notes": "Canonical parent remains source signals artifact only.",
            },
            {
                "dependency_type": "method_status_evidence_only",
                "path": rel(DISCOVERY),
                "listed_in_manifest_parent": False,
                "allowed": True,
                "notes": "Accepted readiness audit used as status evidence, not canonical parent.",
            },
            {
                "dependency_type": "context_evidence_only",
                "path": rel(READINESS_AUDIT),
                "listed_in_manifest_parent": False,
                "allowed": True,
                "notes": "Prior crosswalk evidence used as provenance, not parent identity source.",
            },
        ],
    )
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "recommended_next_action": "implement_phase_b2_travelway_network_index_only",
                "rationale": "signal_index now preserves all source rows and has accepted readiness/status labels.",
                "do_not_do": "Do not build signal_travelway_attachment, approaches, corridors, bins, directionality, distance-band units, MVP, speed/AADT/exposure, access, or crash products yet.",
            }
        ],
    )

    qa_manifest = {
        "created_utc": now(),
        "decision": decision,
        "acceptance_tests": [{"acceptance_test": k, "status": "pass" if v else "fail"} for k, v in qa.items()],
        "counts": {
            "row_count_before": len(before),
            "row_count_after": len(patched),
            "analysis_ready_count": ready,
            "not_ready_count": not_ready,
            "confidence_counts": {str(k): int(v) for k, v in conf_counts.items()},
        },
    }
    manifest = {
        "created_utc": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "patched_staged_product": rel(SIGNAL_INDEX) if decision == "signal_index_ready_as_validated_parent" else "",
        "read_inputs": [rel(SIGNAL_INDEX), rel(STAGING_MANIFEST), rel(STAGING_SCHEMA), rel(STAGING_README), rel(SOURCE), rel(DISCOVERY), rel(READINESS_AUDIT)],
        "canonical_parent": [rel(SOURCE)],
        "method_status_evidence_only": [rel(DISCOVERY), rel(READINESS_AUDIT)],
        "no_downstream_objects_built": True,
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "findings_memo.md").write_text(findings_text(decision, ready, not_ready), encoding="utf-8")
    log("Completed bounded Phase B.1 readiness/status patch.")


if __name__ == "__main__":
    main()
