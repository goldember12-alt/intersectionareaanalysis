"""Audit the final-clean missing-leg recovery queue.

Bounded question:
    Reconcile the 677 one/two-leg recoverable missing-leg queue, audit current
    three-leg signals for possible missing fourth legs, and define the exact
    queue for a later source-Travelway missing-leg generation pass.

This pass is read-only. It does not generate bins, assign crashes/access,
calculate rates/models, promote records, or modify active outputs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_queue_audit"
LEG_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_leg_recovery_normalization"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
SOURCE_TRAVELWAY_GPKG = ROOT / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "one_two_detail": LEG_DIR / "one_two_leg_recoverability_detail.csv",
    "proposals": LEG_DIR / "corrected_leg_label_proposals.csv",
    "missing_leg_summary": LEG_DIR / "missing_leg_candidate_recovery_summary.csv",
    "revised_distribution": LEG_DIR / "revised_physical_leg_distribution_estimate.csv",
    "leg_manifest": LEG_DIR / "final_clean_universe_leg_recovery_manifest.json",
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "final_leg_distribution": FINAL_DIR / "final_clean_physical_leg_distribution.csv",
    "final_manifest": FINAL_DIR / "final_clean_universe_context_summary_manifest.json",
    "expected_leg_detail": ROOT
    / "work/output/roadway_graph/review/current/full_universe_expected_leg_expansion/full_universe_expected_leg_detail.csv",
}


def log(lines: list[str], message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    lines.append(f"{stamp} {message}")
    print(message)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def leg_bucket(count: int | float) -> str:
    if pd.isna(count) or int(count) <= 0:
        return "zero_or_unknown_leg"
    count = int(count)
    if count == 1:
        return "one_leg"
    if count == 2:
        return "two_leg"
    if count == 3:
        return "three_leg"
    if count == 4:
        return "four_leg"
    return "five_plus_leg"


def nunique_nonblank(s: pd.Series) -> int:
    ss = s.dropna().astype(str)
    ss = ss[(ss != "") & (ss != "nan") & (ss != "<NA>")]
    return int(ss.nunique())


def source_travelway_metadata() -> dict[str, object]:
    if not SOURCE_TRAVELWAY_GPKG.exists():
        return {"available": False, "note": "source Travelway GeoPackage not found"}
    try:
        import pyogrio

        info = pyogrio.read_info(SOURCE_TRAVELWAY_GPKG, layer="source_travelway_full")
        return {
            "available": True,
            "features": int(info.get("features", 0)),
            "geometry_type": str(info.get("geometry_type", "")),
            "fid_column": str(info.get("fid_column", "")),
            "fields": list(map(str, info.get("fields", []))),
            "note": "Layer metadata read only; source geometries were not loaded in this audit.",
        }
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"available": False, "note": f"source Travelway metadata read failed: {type(exc).__name__}: {exc}"}


def compute_current_features(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    grouped = bins.groupby("stable_signal_id", dropna=False).agg(
        bin_count=("stable_bin_id", "size"),
        binned_physical_leg_count=("physical_leg_id", nunique_nonblank),
        stable_travelway_count=("stable_travelway_id", nunique_nonblank),
        source_route_count=("source_route_name", nunique_nonblank),
        source_feature_count=("source_feature_local_fid", nunique_nonblank),
        carriageway_subbranch_count=("carriageway_subbranch_id", nunique_nonblank),
    )
    features = signals.merge(grouped.reset_index(), on="stable_signal_id", how="left")
    for col in [
        "bin_count",
        "binned_physical_leg_count",
        "stable_travelway_count",
        "source_route_count",
        "source_feature_count",
        "carriageway_subbranch_count",
    ]:
        features[col] = features[col].fillna(0).astype(int)
    fallback = pd.to_numeric(features.get("signal_level_physical_leg_count", pd.NA), errors="coerce")
    features["current_physical_leg_count"] = features["binned_physical_leg_count"]
    use_fallback = (features["current_physical_leg_count"] <= 0) & fallback.notna()
    features.loc[use_fallback, "current_physical_leg_count"] = fallback[use_fallback].astype(int)
    features["current_physical_leg_bucket"] = features["current_physical_leg_count"].map(leg_bucket)
    return features


def add_expected_evidence(features: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    if expected.empty:
        return features
    keep = [
        c
        for c in [
            "source_signal_id_x",
            "source_layer_x",
            "source_line_count",
            "source_bearing_count",
            "source_bearing_groups",
            "source_route_group_count",
            "source_route_groups",
            "source_divided_subbranch_count",
            "source_zone_evidence_status",
            "expected_physical_leg_count",
            "expected_physical_leg_class",
            "expected_intersection_type",
            "missing_physical_leg_count",
            "extra_physical_leg_count",
            "alignment_class",
            "likely_recovery_action",
            "likely_additional_bins_if_recovered",
        ]
        if c in expected.columns
    ]
    expected = expected[keep].drop_duplicates("source_signal_id_x")
    return features.merge(
        expected,
        left_on="source_signal_id",
        right_on="source_signal_id_x",
        how="left",
        suffixes=("", "_expected"),
    )


def reconcile_677(one_two: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = one_two[
        one_two["one_two_leg_recoverability_class"].eq("under_captured_recoverable_source_leg")
    ].copy()
    q["proposed_revised_physical_leg_count"] = pd.to_numeric(
        q["estimated_leg_count_after_recovery"], errors="coerce"
    ).fillna(q["current_physical_leg_count"])
    q["current_leg_bucket"] = q["current_physical_leg_count"].map(leg_bucket)
    q["revised_leg_bucket_after_recovery"] = q["proposed_revised_physical_leg_count"].map(leg_bucket)
    q["missing_leg_count_to_generate"] = (
        q["proposed_revised_physical_leg_count"] - q["current_physical_leg_count"]
    ).clip(lower=0).astype(int)
    q["recovery_requires_new_missing_leg_bins"] = q["missing_leg_count_to_generate"] > 0
    q["recovery_is_label_only"] = False
    q["generation_recommendation"] = "ready_for_source_travelway_missing_leg_generation"
    q.loc[q["source_bearing_count"].isna(), "generation_recommendation"] = (
        "ready_but_needs_source_travelway_geometry_lookup"
    )
    cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "recovery_branch",
        "current_physical_leg_count",
        "expected_physical_leg_count",
        "source_bearing_count",
        "source_bearing_groups",
        "source_route_group_count",
        "source_route_groups",
        "source_line_count",
        "source_divided_subbranch_count",
        "missing_physical_leg_count",
        "proposed_revised_physical_leg_count",
        "current_leg_bucket",
        "revised_leg_bucket_after_recovery",
        "missing_leg_count_to_generate",
        "recovery_requires_new_missing_leg_bins",
        "recovery_is_label_only",
        "generation_recommendation",
        "leg_recovery_confidence",
        "classification_reason",
    ]
    for col in cols:
        if col not in q.columns:
            q[col] = pd.NA
    transition = (
        q.groupby(["current_leg_bucket", "revised_leg_bucket_after_recovery"], dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            missing_leg_count_to_generate=("missing_leg_count_to_generate", "sum"),
        )
        .reset_index()
    )
    transition["transition_scope"] = "recoverable_677_only"
    return q[cols], transition


def explain_one_two_transition(one_two: pd.DataFrame, q677: pd.DataFrame, proposals: pd.DataFrame) -> pd.DataFrame:
    all_q = one_two.copy()
    all_q["estimated_bucket"] = pd.to_numeric(
        all_q["estimated_leg_count_after_recovery"], errors="coerce"
    ).fillna(all_q["current_physical_leg_count"]).map(leg_bucket)
    rows = []
    rows.append(
        {
            "metric": "current_one_two_leg_targets",
            "signal_count": int(len(all_q)),
            "notes": "All current one/two-leg records in the prior target pool.",
        }
    )
    rows.append(
        {
            "metric": "current_one_two_recoverable_677",
            "signal_count": int(len(q677)),
            "notes": "Subset classified under_captured_recoverable_source_leg.",
        }
    )
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        rows.append(
            {
                "metric": f"recoverable_677_moves_to_{bucket}",
                "signal_count": int(q677["revised_leg_bucket_after_recovery"].eq(bucket).sum()),
                "notes": "Bucket after proposed recovery estimate for the 677 subset.",
            }
        )
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        rows.append(
            {
                "metric": f"all_one_two_targets_estimated_as_{bucket}",
                "signal_count": int(all_q["estimated_bucket"].eq(bucket).sum()),
                "notes": "Explains revised one/two counts after applying all one/two target estimates, not only the 677 subset.",
            }
        )
    if not proposals.empty:
        p = proposals.copy()
        p["corrected_bucket"] = pd.to_numeric(
            p["corrected_estimated_physical_leg_count"], errors="coerce"
        ).map(leg_bucket)
        non_one_two = p[~pd.to_numeric(p["current_physical_leg_count"], errors="coerce").isin([1, 2])]
        for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
            rows.append(
                {
                    "metric": f"non_one_two_label_proposals_estimated_as_{bucket}",
                    "signal_count": int(non_one_two["corrected_bucket"].eq(bucket).sum()),
                    "notes": "Additional label-only normalization proposals outside the current one/two target pool; these close the 46/382 revised distribution reconciliation.",
                }
            )
    return pd.DataFrame(rows)


def classify_three_leg(row: pd.Series) -> tuple[str, str, int, str]:
    expected = pd.to_numeric(row.get("expected_physical_leg_count", pd.NA), errors="coerce")
    source_bearing = pd.to_numeric(row.get("source_bearing_count", pd.NA), errors="coerce")
    route_count = int(row.get("source_route_count", 0))
    stable_tw = int(row.get("stable_travelway_count", 0))
    qa = str(row.get("qa_flags", "")).lower()
    branch = str(row.get("recovery_branch", "")).lower()

    if pd.notna(expected) and expected >= 4:
        if pd.notna(source_bearing) and source_bearing >= 4:
            return (
                "three_leg_recoverable_missing_fourth_leg",
                "Prior source-zone expected/source-bearing evidence supports a fourth leg.",
                int(min(expected, 4)),
                "three_leg_missing_fourth_ready",
            )
        return (
            "three_leg_complex_or_offset_review",
            "Expected count exceeds current three legs, but source-bearing evidence is not strong enough for direct generation.",
            int(min(expected, 4)),
            "needs_intersection_zone_anchor_before_generation",
        )
    if pd.notna(expected) and expected <= 3:
        return ("three_leg_true_t_intersection", "Prior expected-leg model does not support a fourth leg.", 3, "source_limited_do_not_force")
    if route_count >= 4 or stable_tw >= 4:
        if "complex" in qa or "offset" in branch:
            return (
                "three_leg_complex_or_offset_review",
                "Stable lineage has four-plus Travelway/route identities but branch/QA indicates complex or offset context.",
                4,
                "needs_intersection_zone_anchor_before_generation",
            )
        return (
            "three_leg_recoverable_missing_fourth_leg",
            "Stable lineage proxy has four-plus Travelway/route identities.",
            4,
            "three_leg_missing_fourth_ready",
        )
    if route_count <= 3 and stable_tw <= 3:
        return ("three_leg_true_t_intersection", "Stable lineage has no evidence for a fourth approach.", 3, "source_limited_do_not_force")
    return ("three_leg_uncertain", "Insufficient expected-leg evidence.", 3, "manual_review_needed")


def audit_three_leg(features: pd.DataFrame) -> pd.DataFrame:
    three = features[features["current_physical_leg_bucket"].eq("three_leg")].copy()
    vals = three.apply(classify_three_leg, axis=1, result_type="expand")
    three[
        [
            "three_leg_missing_fourth_class",
            "classification_reason",
            "estimated_physical_leg_count_after_audit",
            "next_generation_class",
        ]
    ] = vals
    three["estimated_missing_leg_count"] = (
        three["estimated_physical_leg_count_after_audit"] - three["current_physical_leg_count"]
    ).clip(lower=0).astype(int)
    return three


def build_generation_queue(q677: pd.DataFrame, three: pd.DataFrame, one_two: pd.DataFrame) -> pd.DataFrame:
    q1 = q677.copy()
    q1["next_generation_class"] = "ready_for_source_travelway_missing_leg_generation"
    q1.loc[q1["generation_recommendation"].eq("ready_but_needs_source_travelway_geometry_lookup"), "next_generation_class"] = (
        "needs_intersection_zone_anchor_before_generation"
    )
    q1["queue_source"] = "recoverable_677_under_captured_one_two"
    q1["estimated_missing_leg_count"] = q1["missing_leg_count_to_generate"]

    three_q = three[
        three["three_leg_missing_fourth_class"].isin(
            ["three_leg_recoverable_missing_fourth_leg", "three_leg_complex_or_offset_review"]
        )
    ].copy()
    three_q["queue_source"] = "current_three_leg_missing_fourth_audit"
    three_q["current_leg_bucket"] = "three_leg"
    three_q["revised_leg_bucket_after_recovery"] = three_q["estimated_physical_leg_count_after_audit"].map(leg_bucket)
    three_q["generation_recommendation"] = three_q["next_generation_class"]
    three_q["missing_leg_count_to_generate"] = three_q["estimated_missing_leg_count"]

    cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "recovery_branch",
        "queue_source",
        "current_physical_leg_count",
        "expected_physical_leg_count",
        "source_bearing_count",
        "source_route_group_count",
        "stable_travelway_count",
        "source_route_count",
        "current_leg_bucket",
        "revised_leg_bucket_after_recovery",
        "missing_leg_count_to_generate",
        "next_generation_class",
        "generation_recommendation",
    ]
    q = pd.concat([q1, three_q], ignore_index=True, sort=False)
    for col in cols:
        if col not in q.columns:
            q[col] = pd.NA

    source_limited = one_two[
        one_two["one_two_leg_recoverability_class"].isin(
            ["true_source_limited_partial_signal", "source_travelway_missing_cross_street"]
        )
    ].copy()
    source_limited["queue_source"] = "source_limited_one_two_reference_only"
    source_limited["next_generation_class"] = "source_limited_do_not_force"
    source_limited["generation_recommendation"] = "source_limited_do_not_force"
    source_limited["current_leg_bucket"] = source_limited["current_physical_leg_count"].map(leg_bucket)
    source_limited["revised_leg_bucket_after_recovery"] = source_limited["estimated_leg_count_after_recovery"].map(leg_bucket)
    source_limited["missing_leg_count_to_generate"] = 0
    q = pd.concat([q[cols], source_limited[cols]], ignore_index=True, sort=False)
    return q[cols]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[str] = []
    started = datetime.now(timezone.utc)
    log(progress, "Starting missing-leg queue audit.")

    one_two = read_csv(INPUTS["one_two_detail"])
    proposals = read_csv(INPUTS["proposals"])
    signals = read_csv(INPUTS["final_signals"])
    bins = read_csv(INPUTS["final_bins"])
    expected = read_csv(INPUTS["expected_leg_detail"])
    source_meta = source_travelway_metadata()
    log(progress, f"Loaded one/two detail={len(one_two)}, final signals={len(signals)}, final bins={len(bins)}.")

    features = compute_current_features(signals, bins)
    features = add_expected_evidence(features, expected)
    q677, transition_677 = reconcile_677(one_two)
    transition_explain = explain_one_two_transition(one_two, q677, proposals)
    transition = pd.concat(
        [
            transition_677,
            transition_explain.rename(columns={"metric": "current_leg_bucket", "notes": "transition_scope"}).assign(
                revised_leg_bucket_after_recovery=pd.NA,
                missing_leg_count_to_generate=pd.NA,
            )[
                [
                    "current_leg_bucket",
                    "revised_leg_bucket_after_recovery",
                    "signal_count",
                    "missing_leg_count_to_generate",
                    "transition_scope",
                ]
            ],
        ],
        ignore_index=True,
        sort=False,
    )

    three = audit_three_leg(features)
    queue = build_generation_queue(q677, three, one_two)
    queue_summary = (
        queue.groupby(["next_generation_class", "queue_source"], dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            estimated_missing_leg_count=("missing_leg_count_to_generate", "sum"),
        )
        .reset_index()
    )

    q677.to_csv(OUT_DIR / "recoverable_677_queue_reconciliation.csv", index=False)
    transition.to_csv(OUT_DIR / "recoverable_677_distribution_transition.csv", index=False)
    three.to_csv(OUT_DIR / "current_three_leg_missing_fourth_audit.csv", index=False)
    queue.to_csv(OUT_DIR / "missing_leg_generation_target_queue.csv", index=False)
    queue_summary.to_csv(OUT_DIR / "missing_leg_generation_target_summary.csv", index=False)

    three_counts = three["three_leg_missing_fourth_class"].value_counts().to_dict()
    q_counts = queue_summary.set_index(["next_generation_class", "queue_source"])["signal_count"].to_dict()
    ready_queue = int(
        queue.loc[
            queue["next_generation_class"].isin(
                ["ready_for_source_travelway_missing_leg_generation", "three_leg_missing_fourth_ready"]
            ),
            "stable_signal_id",
        ].nunique()
    )
    all_generation = int(
        queue.loc[
            ~queue["next_generation_class"].eq("source_limited_do_not_force"),
            "stable_signal_id",
        ].nunique()
    )

    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to review/current/final_clean_missing_leg_queue_audit."),
            ("no_records_promoted", True, "All outputs are audit queues."),
            ("no_crash_assignment", True, "Crash records were not read."),
            ("no_access_assignment", True, "Access assignment was not run."),
            ("no_rates_or_models", True, "No rates/models calculated."),
            ("no_new_bins_generated", True, "missing_leg_candidate_recovery_bins is not created by this pass."),
            ("crash_direction_fields_not_used", True, "No crash fields were read."),
            ("source_limited_cases_not_forced", True, "Source-limited classes are marked do_not_force."),
            ("source_travelway_read_bounded", bool(source_meta.get("available")), source_meta.get("note")),
            ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/final_clean_missing_leg_queue_audit"), str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "notes"],
    )
    qa.to_csv(OUT_DIR / "missing_leg_queue_audit_qa.csv", index=False)

    findings = f"""# Missing-Leg Queue Audit

## Bounded Question

Reconcile the 677 one/two-leg recoverable missing-leg queue and audit current three-leg signals for possible missing fourth legs. This pass does not generate bins, rerun context, assign access/crashes, calculate rates/models, or modify active outputs.

## Findings

1. The **677** count comes directly from `one_two_leg_recoverability_detail.csv` records classified as `under_captured_recoverable_source_leg`.
2. The 677 map into revised buckets as shown in `recoverable_677_distribution_transition.csv`. They are a subset of the full one/two target pool, so the revised one/two counts also include source-limited, offset/intersection-zone-needed, and ramp/partial classes.
3. All **{len(q677):,}** records in the 677 queue require actual missing-leg bin generation before they can be treated as geometry-complete. The prior revised distribution was a label-only estimate, not generated scaffold.
4. Label-only corrections for the 677 queue are **0**; label-only normalization mainly applies to five-plus over-split/subbranch cases.
5. Current three-leg audit classes are `{three_counts}`.
6. Additional three-leg missing-fourth generation candidates are included in `missing_leg_generation_target_queue.csv`.
7. Ready high-confidence generation target count is **{ready_queue:,}** signals; broader generation/review target count excluding source-limited do-not-force records is **{all_generation:,}** signals.
8. Next pass should generate bins for the high-confidence ready queue first: the 677 under-captured one/two queue plus three-leg missing-fourth-ready records. Offset/complex/intersection-zone-needed records should be a separate subpass or map-review/geospatial-anchor pass.

## Source Travelway Read

`source_travelway_full` metadata was read from the map-review GeoPackage: `{source_meta}`. Full source geometries were not loaded because this is an audit-only pass.
"""
    (OUT_DIR / "missing_leg_queue_audit_findings.md").write_text(findings, encoding="utf-8")

    manifest = {
        "script": "src/active/roadway_graph/final_clean_missing_leg_queue_audit.py",
        "created_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "inputs": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in INPUTS.items() if v.exists()},
        "source_travelway_metadata": source_meta,
        "outputs": [
            "recoverable_677_queue_reconciliation.csv",
            "recoverable_677_distribution_transition.csv",
            "current_three_leg_missing_fourth_audit.csv",
            "missing_leg_generation_target_queue.csv",
            "missing_leg_generation_target_summary.csv",
            "missing_leg_queue_audit_findings.md",
            "missing_leg_queue_audit_qa.csv",
            "missing_leg_queue_audit_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "recoverable_677_queue": int(len(q677)),
            "current_three_leg_signals_audited": int(len(three)),
            "ready_high_confidence_generation_targets": int(ready_queue),
            "broader_generation_or_anchor_review_targets": int(all_generation),
            "source_limited_reference_records": int(queue["next_generation_class"].eq("source_limited_do_not_force").sum()),
        },
        "non_goals_confirmed": [
            "no_missing_leg_bins_generated",
            "no_context_refresh",
            "no_access_assignment",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_active_outputs_modified",
        ],
    }
    (OUT_DIR / "missing_leg_queue_audit_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(progress, "Wrote missing-leg queue audit outputs.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
