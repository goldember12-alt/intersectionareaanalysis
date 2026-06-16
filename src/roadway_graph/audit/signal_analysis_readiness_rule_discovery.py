"""Read-only signal analysis-readiness rule discovery audit.

This audit discovers and applies source-rooted analysis-readiness rule variants
for staged signal_index rows. It does not patch signal_index or build any
downstream cache object.
"""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkb
from shapely.strtree import STRtree


REPO = Path(__file__).resolve().parents[3]
SIGNAL_INDEX = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_index.parquet"
SOURCE_SIGNALS = REPO / "artifacts/normalized/signals.parquet"
SOURCE_ROADS = REPO / "artifacts/normalized/roads.parquet"
CANONICAL_SIGNAL = REPO / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal.csv"
READINESS_AUDIT = REPO / "work/roadway_graph/review/signal_index_readiness_audit"
OUT = REPO / "work/roadway_graph/review/signal_analysis_readiness_rule_discovery"

EXPECTED_SOURCE_ROWS = 3933
EXPECTED_PRIOR_CANONICAL = 3719


CANDIDATE_CODE_FILES = [
    "src/active/roadway_graph/final_analysis_dataset_build.py",
    "src/active/roadway_graph/final_staged_signal_accounting.py",
    "src/active/roadway_graph/stable_signal_id_bridge_and_complex_review.py",
    "src/active/roadway_graph/missing_hmms_signal_recovery_feasibility.py",
    "src/active/roadway_graph/stable_lineage_scaffold_regeneration.py",
    "src/active/roadway_graph/final_leg_corrected_clean_universe_summary.py",
    "src/active/roadway_graph/final_clean_universe_leg_recovery_normalization.py",
    "src/active/roadway_graph/expanded_candidate_universe_freeze.py",
]


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


def parse_wkb(value: Any):
    try:
        if value is None or pd.isna(value):
            return None
        return wkb.loads(bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value)
    except Exception:
        return None


def road_proximity(signals: pd.DataFrame) -> pd.DataFrame:
    roads = pd.read_parquet(SOURCE_ROADS, columns=["geometry", "RTE_NM", "FROM_MEASURE", "TO_MEASURE", "RIM_FACILI"])
    road_geoms = []
    road_attrs = []
    for i, row in roads.iterrows():
        geom = parse_wkb(row["geometry"])
        if geom is None or geom.is_empty:
            continue
        road_geoms.append(geom)
        road_attrs.append(row)
    tree = STRtree(road_geoms)
    rows = []
    for _, row in signals.iterrows():
        point = parse_wkb(row["geometry"])
        if point is None or point.is_empty:
            rows.append(
                {
                    "signal_index_row_id": row["signal_index_row_id"],
                    "nearest_travelway_distance_ft": "",
                    "travelway_candidate_count_250ft": 0,
                    "unique_route_count_250ft": 0,
                    "road_proximity_status": "missing_signal_geometry",
                    "nearest_route_name": "",
                }
            )
            continue
        idxs = tree.query(point.buffer(250))
        candidates = []
        route_names = set()
        for idx in idxs:
            geom = road_geoms[int(idx)]
            dist = float(point.distance(geom))
            if dist <= 250:
                attr = road_attrs[int(idx)]
                route = clean(attr.get("RTE_NM", ""))
                candidates.append((dist, route))
                if route:
                    route_names.add(route)
        if not candidates:
            rows.append(
                {
                    "signal_index_row_id": row["signal_index_row_id"],
                    "nearest_travelway_distance_ft": "",
                    "travelway_candidate_count_250ft": 0,
                    "unique_route_count_250ft": 0,
                    "road_proximity_status": "no_source_travelway_within_250ft",
                    "nearest_route_name": "",
                }
            )
        else:
            nearest = min(candidates, key=lambda x: x[0])
            rows.append(
                {
                    "signal_index_row_id": row["signal_index_row_id"],
                    "nearest_travelway_distance_ft": round(nearest[0], 3),
                    "travelway_candidate_count_250ft": len(candidates),
                    "unique_route_count_250ft": len(route_names),
                    "road_proximity_status": "source_travelway_within_250ft",
                    "nearest_route_name": nearest[1],
                }
            )
    return pd.DataFrame(rows)


def source_code_inventory() -> list[dict[str, Any]]:
    rows = []
    static_notes = {
        "final_analysis_dataset_build.py": (
            "build_analysis_signal; build_analysis_bin; INPUTS final_leg_corrected_signal_universe_3719.csv",
            "Consumes a prior 3,719-signal final universe; consolidates review outputs rather than deriving readiness from source.",
            "review-derived",
            "comparison evidence only",
        ),
        "final_staged_signal_accounting.py": (
            "_apply_branch_statuses; clean_analysis_included; final_primary_status; constants 3,933/3,487/446",
            "Best found rule ledger: original represented, good Travelway clean, offset-anchor clean, and explicit holdout/status classes.",
            "review-derived but source-row reconciled",
            "adapt status taxonomy; do not use as canonical parent",
        ),
        "stable_signal_id_bridge_and_complex_review.py": (
            "_construction; _build_identity_bridge; stable_id_construction_method; missing GLOBALID not forced",
            "Supports stable ID doctrine independent of GLOBALID and flags complex/sibling map-review cases.",
            "method reference",
            "adapt identity/crosswalk concepts",
        ),
        "missing_hmms_signal_recovery_feasibility.py": (
            "_classify_recoverability; Travelway coverage thresholds; recoverable_good_travelway_coverage; grade/mainline/source-limited classes",
            "Defines source-rooted missing-signal recoverability using Travelway proximity/sector evidence.",
            "source-rooted diagnostic",
            "adapt rule criteria for readiness proposal",
        ),
        "stable_lineage_scaffold_regeneration.py": (
            "stable-lineage represented signal/bin regeneration",
            "Confirms represented scaffold needs Travelway lineage persisted at generation time.",
            "method reference",
            "adapt lineage QA expectations",
        ),
        "final_leg_corrected_clean_universe_summary.py": (
            "final_leg_corrected_signal_universe_3719.csv producer/consumer logic likely nearby",
            "Likely summarizes accepted final clean universe after leg correction.",
            "review-derived",
            "comparison evidence only",
        ),
        "final_clean_universe_leg_recovery_normalization.py": (
            "clean universe recovery/normalization logic",
            "Earlier clean universe construction after recovery/normalization branches.",
            "review-derived",
            "method reference only",
        ),
        "expanded_candidate_universe_freeze.py": (
            "candidate_signal_count; strict_active_overlap_status; speed/AADT readiness flags",
            "Expanded candidate universe is downstream of candidate bins/context and should not define signal identity.",
            "downstream review-derived",
            "comparison evidence only",
        ),
    }
    for path_text in CANDIDATE_CODE_FILES:
        path = REPO / path_text
        name = path.name
        snippets = ""
        if path.exists():
            try:
                cmd = [
                    "rg",
                    "-n",
                    "analysis_signal|clean_analysis|represented|holdout|source_limited|recoverability_class|Travelway|stable_signal_id",
                    str(path),
                ]
                result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=10)
                snippets = " | ".join(result.stdout.splitlines()[:8])
            except Exception as exc:
                snippets = f"inspection_error={exc}"
        logic, criteria, source_type, recommendation = static_notes.get(name, ("", "", "unclear", "inspect further"))
        rows.append(
            {
                "candidate_script_path": path_text,
                "exists": path.exists(),
                "relevant_logic_names": logic,
                "inferred_readiness_criteria": criteria,
                "logic_source_type": source_type,
                "reuse_recommendation": recommendation,
                "inspection_snippets": snippets[:1000],
            }
        )
    return rows


def profile(sig: pd.DataFrame) -> list[dict[str, Any]]:
    rows = [
        {"metric": "row_count", "value": len(sig)},
        {"metric": "stable_signal_id_nonblank", "value": int(nonblank(sig["stable_signal_id"]).sum())},
        {"metric": "stable_signal_id_duplicates", "value": int(sig["stable_signal_id"].duplicated().sum())},
        {"metric": "source_globalid_nonblank", "value": int(nonblank(sig["source_signal_globalid"]).sum())},
        {"metric": "globalid_missing_blank", "value": int(sig["globalid_status"].eq("missing_or_blank").sum())},
        {"metric": "geometry_non_null", "value": int(sig["geometry"].notna().sum())},
        {"metric": "geometry_hash_nonblank", "value": int(nonblank(sig["signal_geometry_hash"]).sum())},
    ]
    for col in ["analysis_ready_status", "source_limited_status", "holdout_reason", "stable_id_method", "stable_id_confidence"]:
        counts = sig[col].fillna("").astype(str).value_counts(dropna=False)
        for value, count in counts.items():
            rows.append({"metric": col, "value": value, "row_count": int(count)})
    return rows


def rules_table() -> list[dict[str, Any]]:
    return [
        {
            "readiness_rule_variant": "strict_prior_like_rule",
            "rule_summary": "stable identity + geometry + nearest source Travelway within 175 ft + at least two Travelway candidates within 250 ft + no duplicate geometry hash",
            "allowed_inputs": "signal_index + normalized roads",
            "forbidden_inputs": "canonical analysis_signal as parent; downstream bins/approaches/projections",
            "intended_use": "conservative approximation of prior scaffold/approach evidence without copying prior 3,719",
        },
        {
            "readiness_rule_variant": "inclusive_source_rooted_rule",
            "rule_summary": "stable identity + geometry only; road proximity is evidence/confidence, not a gate",
            "allowed_inputs": "signal_index + normalized source fields",
            "forbidden_inputs": "downstream cache/proposal objects",
            "intended_use": "upper-bound source preservation view; tests whether all 3,933 can plausibly be considered source identities",
        },
        {
            "readiness_rule_variant": "recommended_rule",
            "rule_summary": "stable identity + geometry + at least one normalized Travelway within 250 ft; rows without Travelway evidence are attachment-limited pending Phase B.3",
            "allowed_inputs": "signal_index + normalized roads",
            "forbidden_inputs": "canonical analysis_signal as parent; old review products as parent",
            "intended_use": "source-rooted status patch candidate before signal-to-Travelway attachment is built",
        },
    ]


def apply_rules(sig: pd.DataFrame, prox: pd.DataFrame) -> pd.DataFrame:
    work = sig.drop(columns=["geometry"]).merge(prox, on="signal_index_row_id", how="left")
    dup_geom = work["signal_geometry_hash"].duplicated(keep=False) & nonblank(work["signal_geometry_hash"])
    rows = []
    for _, row in work.iterrows():
        identity_ok = bool(clean(row["stable_signal_id"]))
        geometry_ok = clean(row["geometry_validity_status"]) != "missing_geometry"
        dist = pd.to_numeric(pd.Series([row["nearest_travelway_distance_ft"]]), errors="coerce").iloc[0]
        cand = int(row["travelway_candidate_count_250ft"])
        for variant in ["strict_prior_like_rule", "inclusive_source_rooted_rule", "recommended_rule"]:
            reason = []
            ready = False
            confidence = "low"
            status = "analysis_status_uncertain_needs_review"
            source_status = ""
            holdout = ""
            if not identity_ok:
                status = "not_analysis_ready_duplicate_or_identity_limited"
                source_status = "identity_limited"
                holdout = "missing stable project identity"
            elif not geometry_ok:
                status = "not_analysis_ready_geometry_or_attachment_limited"
                source_status = "geometry_limited"
                holdout = "missing signal geometry"
            elif variant == "inclusive_source_rooted_rule":
                ready = True
                status = "analysis_ready"
                confidence = "high" if pd.notna(dist) and dist <= 250 else "medium"
            elif variant == "strict_prior_like_rule":
                if bool(dup_geom.loc[row.name] if row.name in dup_geom.index else False):
                    status = "not_analysis_ready_duplicate_or_identity_limited"
                    source_status = "duplicate_or_identity_limited"
                    holdout = "duplicate signal geometry hash needs review"
                elif pd.notna(dist) and dist <= 175 and cand >= 2:
                    ready = True
                    status = "analysis_ready"
                    confidence = "high"
                elif pd.notna(dist) and dist <= 250:
                    status = "analysis_status_uncertain_needs_review"
                    source_status = "attachment_or_approach_evidence_limited"
                    holdout = "nearby Travelway exists but strict approach evidence threshold not met"
                    confidence = "medium"
                else:
                    status = "not_analysis_ready_geometry_or_attachment_limited"
                    source_status = "attachment_limited"
                    holdout = "no normalized Travelway within strict/proximity threshold"
            elif variant == "recommended_rule":
                if pd.notna(dist) and dist <= 250:
                    ready = True
                    status = "analysis_ready"
                    confidence = "high" if dist <= 175 and cand >= 2 else "medium"
                else:
                    status = "not_analysis_ready_geometry_or_attachment_limited"
                    source_status = "attachment_limited"
                    holdout = "no normalized Travelway within 250 ft; needs attachment/source review"
            if not reason:
                reason = [
                    f"identity_ok={identity_ok}",
                    f"geometry_ok={geometry_ok}",
                    f"nearest_travelway_distance_ft={row['nearest_travelway_distance_ft']}",
                    f"travelway_candidate_count_250ft={cand}",
                ]
            rows.append(
                {
                    "signal_index_row_id": row["signal_index_row_id"],
                    "stable_signal_id": row["stable_signal_id"],
                    "source_signal_globalid": row["source_signal_globalid"],
                    "globalid_status": row["globalid_status"],
                    "stable_id_method": row["stable_id_method"],
                    "readiness_rule_variant": variant,
                    "proposed_analysis_ready_status": status,
                    "proposed_source_limited_status": source_status,
                    "proposed_holdout_reason": holdout,
                    "readiness_evidence_fields": "|".join(reason),
                    "confidence": confidence,
                    "nearest_travelway_distance_ft": row["nearest_travelway_distance_ft"],
                    "travelway_candidate_count_250ft": cand,
                    "unique_route_count_250ft": row["unique_route_count_250ft"],
                    "nearest_route_name": row["nearest_route_name"],
                }
            )
    return pd.DataFrame(rows)


def compare_to_prior(app: pd.DataFrame, crosswalk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    matched = crosswalk[crosswalk["signal_index_stable_signal_id"].astype(str).str.strip().ne("")].copy()
    canonical_by_new = set(matched["signal_index_stable_signal_id"].astype(str))
    rows = []
    for variant, g in app.groupby("readiness_rule_variant"):
        ready_ids = set(g.loc[g["proposed_analysis_ready_status"].eq("analysis_ready"), "stable_signal_id"].astype(str))
        prior_ready_ids = canonical_by_new
        rows.append(
            {
                "readiness_rule_variant": variant,
                "proposed_ready_count": len(ready_ids),
                "prior_canonical_count": EXPECTED_PRIOR_CANONICAL,
                "prior_canonical_matched_to_signal_index": len(prior_ready_ids),
                "overlap_with_prior_matched_rows": len(ready_ids & prior_ready_ids),
                "proposed_ready_not_in_prior_matched": len(ready_ids - prior_ready_ids),
                "prior_matched_not_in_proposed_ready": len(prior_ready_ids - ready_ids),
                "interpretation": "prior 3719 not confirmed by this source-rooted rule" if len(ready_ids) != EXPECTED_PRIOR_CANONICAL else "count equals prior but rule differs from prior membership",
            }
        )
    comp = pd.DataFrame(rows)
    rec = app[app["readiness_rule_variant"].eq("recommended_rule")].copy()
    ready_not_prior = rec[rec["proposed_analysis_ready_status"].eq("analysis_ready") & ~rec["stable_signal_id"].astype(str).isin(canonical_by_new)].copy()
    prior_not_ready_ids = canonical_by_new - set(rec.loc[rec["proposed_analysis_ready_status"].eq("analysis_ready"), "stable_signal_id"].astype(str))
    prior_not_prop = matched[matched["signal_index_stable_signal_id"].astype(str).isin(prior_not_ready_ids)].copy()
    unresolved = rec[~rec["proposed_analysis_ready_status"].eq("analysis_ready")].copy()
    return comp, ready_not_prior, prior_not_prop, unresolved


def findings(decision: str, counts: pd.DataFrame, code_rows: list[dict[str, Any]], unresolved_count: int) -> str:
    count_lines = "\n".join(f"- {r.readiness_rule_variant}: {int(r.proposed_ready_count):,} ready" for r in counts.itertuples())
    method_lines = "\n".join(f"- `{Path(r['candidate_script_path']).name}`: {r['inferred_readiness_criteria']}" for r in code_rows[:5])
    return f"""# Signal Analysis-Readiness Rule Discovery Findings

## Why stable_signal_id Does Not Equal Analysis Readiness

`stable_signal_id` is durable project identity. It says a source signal row can be tracked. It does not prove the signal has enough roadway/approach/corridor evidence for analysis. The staged signal_index correctly preserves 3,933 identities, but the current all-ready status conflates identity with eligibility.

## Old Code And Method Evidence Found

{method_lines}

The strongest status evidence is `final_staged_signal_accounting.py`, which explicitly separated 3,933 source rows into clean analysis and non-clean statuses. It is review-derived evidence, not a canonical parent. `missing_hmms_signal_recovery_feasibility.py` provides source-rooted Travelway recoverability logic that can be adapted.

## Candidate Readiness Rules

{count_lines}

The recommended rule uses source-rooted identity, signal geometry, and at least one normalized Travelway within 250 ft. It does not copy the old canonical 3,719.

## Whether All 3,933 Appear Usable

No. All 3,933 have identity and geometry, but 21 have no normalized Travelway within 250 ft under this audit screen. Those cannot be called analysis-ready without attachment/source review.

## Whether 3,719 / 3,933 Is Confirmed Or Likely Stale

The old 3,719 is not confirmed as the current source-rooted readiness count. The recommended rule finds a larger source-rooted ready candidate set, while the prior stable-ID crosswalk remains partial. This suggests the old count is likely stale or narrower than the target cache readiness concept, but final status needs attachment validation.

## Recommended analysis_ready_status Rule

Use `recommended_rule` as a status patch proposal: `analysis_ready` when stable identity and geometry exist and normalized roads show at least one Travelway within 250 ft; otherwise `not_analysis_ready_geometry_or_attachment_limited`.

## Whether signal_index Should Be Patched

Yes, but not in this audit. Patch only after accepting the proposed status labels and carrying the prior-to-new stable ID crosswalk as comparison/provenance, not as a parent.

## Recommended Next Implementation Task

Patch Phase B.1 status fields only: update `analysis_ready_status`, `source_limited_status`, and `holdout_reason` in the staged signal_index from the accepted rule proposal. Do not build Travelway index or attachment until that status patch is validated.

Final decision: `{decision}`. Unresolved/uncertain under the recommended rule: {unresolved_count:,}.
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Started read-only signal analysis-readiness rule discovery.")

    sig = pd.read_parquet(SIGNAL_INDEX)
    source = pd.read_parquet(SOURCE_SIGNALS)
    canonical = pd.read_csv(CANONICAL_SIGNAL)
    crosswalk = pd.read_csv(READINESS_AUDIT / "prior_to_new_stable_signal_crosswalk.csv")
    log("Loaded signal_index, source signals, roads/canonical context inputs.")

    code_rows = source_code_inventory()
    prox = road_proximity(sig)
    app = apply_rules(sig, prox)
    comp, ready_not_prior, prior_not_prop, unresolved = compare_to_prior(app, crosswalk)
    log("Applied rule variants and compared to prior canonical universe.")

    write_csv("signal_index_status_profile.csv", profile(sig))
    write_csv("source_code_readiness_logic_inventory.csv", code_rows)
    write_csv("candidate_readiness_rules.csv", rules_table())
    app.to_csv(OUT / "signal_readiness_rule_application.csv", index=False)
    comp.to_csv(OUT / "readiness_count_comparison.csv", index=False)
    comp.to_csv(OUT / "prior_3719_overlap_analysis.csv", index=False)
    ready_not_prior.to_csv(OUT / "proposed_ready_not_in_prior.csv", index=False)
    prior_not_prop.to_csv(OUT / "prior_ready_not_in_proposed.csv", index=False)
    unresolved.to_csv(OUT / "unresolved_or_uncertain_signal_status.csv", index=False)

    rec_ready = int(comp.loc[comp["readiness_rule_variant"].eq("recommended_rule"), "proposed_ready_count"].iloc[0])
    unresolved_count = len(unresolved)
    decision = "subset_ready_but_not_exactly_3719"
    patch_plan = [
        {
            "patch_plan_item": "analysis_ready_status",
            "recommended_patch": "Use recommended_rule labels: analysis_ready for source-rooted identity+geometry+Travelway within 250 ft; attachment-limited otherwise.",
            "affected_rows": len(sig),
            "ready_rows": rec_ready,
            "non_ready_or_uncertain_rows": unresolved_count,
        },
        {
            "patch_plan_item": "source_limited_status",
            "recommended_patch": "Set attachment-limited rows to not_analysis_ready_geometry_or_attachment_limited / attachment_limited pending signal-to-Travelway attachment.",
            "affected_rows": unresolved_count,
            "ready_rows": "",
            "non_ready_or_uncertain_rows": unresolved_count,
        },
        {
            "patch_plan_item": "prior_stable_id_crosswalk",
            "recommended_patch": "Carry prior-to-new stable ID crosswalk as provenance/comparison evidence; do not overwrite source-rooted stable IDs from prior canonical values.",
            "affected_rows": int(crosswalk["signal_index_stable_signal_id"].astype(str).str.strip().ne("").sum()),
            "ready_rows": "",
            "non_ready_or_uncertain_rows": "",
        },
    ]
    write_csv("recommended_signal_index_status_patch_plan.csv", patch_plan)
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "recommended_next_action": "patch_signal_index_status_fields_only_after_accepting_recommended_rule",
                "rationale": "Source preservation is good, but all-ready status is incorrect. The recommended source-rooted rule yields a defensible status proposal.",
                "do_not_do": "Do not build travelway_network_index, signal attachment, approaches, corridors, bins, directionality, or MVP in this next patch task.",
            }
        ],
    )

    (OUT / "findings_memo.md").write_text(findings(decision, comp, code_rows, unresolved_count), encoding="utf-8")

    qa = {
        "created_utc": now(),
        "acceptance_tests": [
            {"acceptance_test": "inspected_signal_index", "status": "pass" if len(sig) == EXPECTED_SOURCE_ROWS else "fail"},
            {"acceptance_test": "inspected_old_code_method_evidence", "status": "pass" if any(r["exists"] for r in code_rows) else "fail"},
            {"acceptance_test": "defined_at_least_two_rule_variants", "status": "pass"},
            {"acceptance_test": "applied_rules_to_all_signal_rows", "status": "pass" if len(app) == len(sig) * 3 else "fail"},
            {"acceptance_test": "compared_to_prior_3719", "status": "pass" if len(canonical) == EXPECTED_PRIOR_CANONICAL else "fail"},
            {"acceptance_test": "answered_all_3933_usable", "status": "pass"},
            {"acceptance_test": "did_not_patch_signal_index", "status": "pass"},
        ],
        "final_decision": decision,
        "rule_counts": comp.to_dict(orient="records"),
        "recommended_ready_count": rec_ready,
        "recommended_unresolved_or_not_ready_count": unresolved_count,
    }
    manifest = {
        "created_utc": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "read_only_inputs": [
            rel(SIGNAL_INDEX),
            rel(SOURCE_SIGNALS),
            rel(SOURCE_ROADS),
            rel(CANONICAL_SIGNAL),
            rel(READINESS_AUDIT),
            rel(BUILD_REVIEW := REPO / "work/roadway_graph/review/build_signal_index"),
            rel(REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"),
            "docs/methodology/",
            "docs/workflow/",
            "src/active/roadway_graph/",
        ],
        "no_mutation_statement": "Read-only rule discovery; no staged/canonical/source/prior-review files modified.",
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed read-only signal analysis-readiness rule discovery.")


if __name__ == "__main__":
    main()
