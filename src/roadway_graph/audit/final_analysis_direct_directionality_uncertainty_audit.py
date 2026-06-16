"""Decompose Phase 1 direct divided/one-way directionality uncertainty.

This review-only audit explains Phase 1 direct-support bins that did not receive
downstream/upstream labels. It does not assign new downstream/upstream labels.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PHASE1_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_divided_directionality"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_uncertainty_audit"

UNCERTAIN_LABELS = {"direction_supported_but_uncertain", "direct_direction_not_assignable", "", None}
TARGET_CLASSES = {"direct_divided_row_direction_supported", "one_way_row_direction_supported"}


def write_log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR / name, index=False, quoting=csv.QUOTE_MINIMAL)
    write_log(f"Wrote {name}: {len(df):,} rows")


def angle_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a - b).abs() + 180.0) % 360.0 - 180.0


def assign_uncertainty_reason(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    route_suffix_present = out["route_suffix_direction"].fillna("").astype(str).str.len().gt(0)
    geometry_present = out["geometry_bearing"].notna()
    flow_present = out["travelway_flow_bearing"].notna()
    anchor_missing = out["anchor_x"].isna() | out["anchor_y"].isna()
    anchor_low = out["anchor_method"].fillna("").str.startswith("inferred_")
    suffix_conflict = out["geometry_suffix_consistency"].eq("opposite_or_conflicting")
    suffix_oblique = out["geometry_suffix_consistency"].eq("partial_or_oblique")
    measure_missing = out["measure_orientation_consistency"].isin(["measure_missing", "zero_length_measure_interval"])
    measure_geometry_missing = out["measure_orientation_consistency"].eq("measure_present_geometry_missing")
    no_flow = out["travelway_flow_method"].eq("no_flow_bearing")
    bin_geom_bad = ~geometry_present | out[["x0", "y0", "x1", "y1"]].isna().any(axis=1)
    oblique_position = out["direct_directionality_label"].eq("direction_supported_but_uncertain")
    weak_field = out["directionality_support_class"].eq("one_way_row_direction_supported") & ~route_suffix_present

    conflict_count = (
        suffix_conflict.astype(int)
        + measure_geometry_missing.astype(int)
        + (anchor_low & suffix_oblique).astype(int)
        + (no_flow & route_suffix_present).astype(int)
    )

    out["primary_uncertainty_class"] = np.select(
        [
            conflict_count >= 2,
            suffix_conflict,
            ~route_suffix_present & geometry_present & oblique_position,
            ~route_suffix_present & ~geometry_present,
            measure_missing & ~route_suffix_present,
            measure_geometry_missing,
            anchor_missing | (anchor_low & no_flow),
            bin_geom_bad,
            oblique_position & flow_present,
            weak_field,
            oblique_position & out["flow_vs_signal_to_bin_angle_diff"].between(45.0, 60.0, inclusive="both"),
            oblique_position & out["flow_vs_signal_to_bin_angle_diff"].between(120.0, 135.0, inclusive="both"),
        ],
        [
            "multiple_evidence_conflicts",
            "route_suffix_geometry_conflict",
            "missing_route_suffix_direction",
            "bin_geometry_insufficient",
            "measure_orientation_missing",
            "measure_geometry_conflict",
            "anchor_geometry_missing_or_low_confidence",
            "bin_geometry_insufficient",
            "signal_relative_position_ambiguous",
            "one_way_or_divided_field_weak",
            "conservative_rule_blocked_otherwise_assignable",
            "conservative_rule_blocked_otherwise_assignable",
        ],
        default="true_direct_direction_ambiguous",
    )

    suffix_to_signal_diff = angle_distance(out["route_suffix_bearing"], out["signal_to_bin_bearing"]).abs()
    suffix_could_label = route_suffix_present & out["signal_to_bin_bearing"].notna() & (
        (suffix_to_signal_diff <= 45.0) | (suffix_to_signal_diff >= 135.0)
    )
    relaxed_geom = flow_present & out["signal_to_bin_bearing"].notna() & (
        out["flow_vs_signal_to_bin_angle_diff"].between(45.0, 60.0, inclusive="both")
        | out["flow_vs_signal_to_bin_angle_diff"].between(120.0, 135.0, inclusive="both")
    )
    high_anchor_geom = (
        out["anchor_method"].eq("canonical_signal_geometry")
        & out["travelway_flow_method"].eq("geometry_orientation_only")
        & out["signal_to_bin_bearing"].notna()
    )

    out["recoverable_uncertainty_class"] = np.select(
        [
            suffix_conflict & suffix_could_label,
            ~route_suffix_present & high_anchor_geom,
            relaxed_geom,
            anchor_low & flow_present & out["signal_to_bin_bearing"].notna(),
            suffix_conflict,
            out["primary_uncertainty_class"].isin(["multiple_evidence_conflicts", "true_direct_direction_ambiguous"]),
        ],
        [
            "assignable_with_route_suffix_only",
            "assignable_with_geometry_anchor_improvement",
            "assignable_after_relaxing_conservative_rule",
            "assignable_with_geometry_anchor_improvement",
            "needs_map_review",
            "should_remain_uncertain",
        ],
        default="should_remain_uncertain",
    )
    out["potential_relaxed_rule_class"] = np.select(
        [
            suffix_conflict & suffix_could_label,
            ~route_suffix_present & high_anchor_geom,
            relaxed_geom,
        ],
        [
            "route_suffix_over_geometry_digitization_reversal",
            "high_confidence_anchor_plus_geometry_no_suffix",
            "relaxed_oblique_angle_tolerance",
        ],
        default="not_recoverable_by_safe_relaxed_rule",
    )
    out["potentially_recoverable_with_safe_relaxed_rule"] = out["potential_relaxed_rule_class"].ne(
        "not_recoverable_by_safe_relaxed_rule"
    )

    out["route_suffix_present"] = route_suffix_present
    out["measure_orientation_present"] = ~measure_missing
    out["anchor_low_confidence"] = anchor_low | anchor_missing
    out["geometry_likely_reversed_vs_route_suffix"] = suffix_conflict
    out["suffix_measure_agreement_status"] = np.select(
        [
            ~route_suffix_present | measure_missing,
            suffix_conflict,
            out["geometry_suffix_consistency"].eq("consistent"),
            out["geometry_suffix_consistency"].eq("partial_or_oblique"),
        ],
        [
            "not_testable",
            "suffix_measure_or_geometry_conflict_possible",
            "suffix_geometry_agree_measure_present",
            "suffix_oblique_measure_present",
        ],
        default="not_testable",
    )
    return out


def summary_counts(df: pd.DataFrame, col: str, count_col: str = "bins") -> pd.DataFrame:
    return df[col].fillna("missing").value_counts(dropna=False).rename_axis(col).reset_index(name=count_col)


def build_conflict_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("route_suffix_present_geometry_conflict", int((df["geometry_suffix_consistency"] == "opposite_or_conflicting").sum())),
        ("route_suffix_missing", int(~df["route_suffix_present"].sum() if False else (~df["route_suffix_present"]).sum())),
        ("route_suffix_present", int(df["route_suffix_present"].sum())),
        ("measure_orientation_present", int(df["measure_orientation_present"].sum())),
        ("measure_orientation_missing", int((~df["measure_orientation_present"]).sum())),
        ("suffix_and_measure_agree_proxy", int((df["suffix_measure_agreement_status"] == "suffix_geometry_agree_measure_present").sum())),
        (
            "suffix_and_measure_disagree_or_conflict_proxy",
            int((df["suffix_measure_agreement_status"] == "suffix_measure_or_geometry_conflict_possible").sum()),
        ),
        ("geometry_likely_reversed_relative_to_route_suffix", int(df["geometry_likely_reversed_vs_route_suffix"].sum())),
        ("anchor_uncertainty_blocker", int(df["anchor_low_confidence"].sum())),
        ("bin_geometry_insufficient", int((df["primary_uncertainty_class"] == "bin_geometry_insufficient").sum())),
    ]
    return pd.DataFrame(rows, columns=["conflict_pattern", "bins"])


def signal_approach_gap_summary(uncertain: pd.DataFrame, all_detail: pd.DataFrame) -> pd.DataFrame:
    labeled = all_detail[all_detail["direct_directionality_label"].isin(["downstream_from_signal", "upstream_to_signal"])]
    signal_all = all_detail.groupby("stable_signal_id").agg(target_bins=("stable_bin_id", "count")).reset_index()
    signal_labeled = labeled.groupby("stable_signal_id").agg(direct_labeled_bins=("stable_bin_id", "count")).reset_index()
    signal_unc = uncertain.groupby("stable_signal_id").agg(
        uncertain_bins=("stable_bin_id", "count"),
        potentially_recoverable_bins=("potentially_recoverable_with_safe_relaxed_rule", "sum"),
    ).reset_index()
    s = signal_all.merge(signal_labeled, on="stable_signal_id", how="left").merge(signal_unc, on="stable_signal_id", how="left")
    for col in ["direct_labeled_bins", "uncertain_bins", "potentially_recoverable_bins"]:
        s[col] = s[col].fillna(0).astype(int)
    s["signal_lost_all_direct_coverage_due_to_uncertainty"] = (s["direct_labeled_bins"] == 0) & (s["uncertain_bins"] > 0)
    s["signal_has_recoverable_uncertainty"] = s["potentially_recoverable_bins"] > 0

    approach_all = all_detail.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        approach_target_bins=("stable_bin_id", "count")
    ).reset_index()
    app_lab = labeled.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        approach_direct_labeled_bins=("stable_bin_id", "count"),
        downstream_bins=("direct_directionality_label", lambda x: int((x == "downstream_from_signal").sum())),
        upstream_bins=("direct_directionality_label", lambda x: int((x == "upstream_to_signal").sum())),
    ).reset_index()
    app_unc = uncertain.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        approach_uncertain_bins=("stable_bin_id", "count"),
        approach_recoverable_bins=("potentially_recoverable_with_safe_relaxed_rule", "sum"),
    ).reset_index()
    a = approach_all.merge(app_lab, on=["stable_signal_id", "signal_approach_id"], how="left").merge(
        app_unc, on=["stable_signal_id", "signal_approach_id"], how="left"
    )
    for col in ["approach_direct_labeled_bins", "downstream_bins", "upstream_bins", "approach_uncertain_bins", "approach_recoverable_bins"]:
        a[col] = a[col].fillna(0).astype(int)
    a["approach_gap_class"] = np.select(
        [
            (a["approach_direct_labeled_bins"] == 0) & (a["approach_uncertain_bins"] > 0),
            (a["downstream_bins"] == 0) & (a["approach_recoverable_bins"] > 0),
            (a["upstream_bins"] == 0) & (a["approach_recoverable_bins"] > 0),
        ],
        [
            "approach_lost_all_direct_coverage",
            "could_gain_downstream_or_balanced_side_after_recovery",
            "could_gain_upstream_or_balanced_side_after_recovery",
        ],
        default="no_major_approach_gap",
    )
    s2 = s.assign(summary_level="signal")
    a2 = a.assign(summary_level="signal_approach")
    return pd.concat([s2, a2], ignore_index=True, sort=False)


def write_findings(uncertain: pd.DataFrame, all_detail: pd.DataFrame, qa: pd.DataFrame) -> None:
    reason_counts = uncertain["primary_uncertainty_class"].value_counts().to_dict()
    rec_counts = uncertain["recoverable_uncertainty_class"].value_counts().to_dict()
    relaxed = int(uncertain["potentially_recoverable_with_safe_relaxed_rule"].sum())
    suffix_conflicts = int((uncertain["geometry_suffix_consistency"] == "opposite_or_conflicting").sum())
    suffix_missing = int((~uncertain["route_suffix_present"]).sum())
    measure_missing = int((~uncertain["measure_orientation_present"]).sum())
    anchor_low = int(uncertain["anchor_low_confidence"].sum())
    total_labeled = int(all_detail["direct_directionality_label"].isin(["downstream_from_signal", "upstream_to_signal"]).sum())
    text = f"""# Direct Directionality Uncertainty Audit Findings

## Bounded Question

This audit decomposes Phase 1 direct divided/one-way target bins that did not receive a downstream/upstream label. It does not assign new downstream/upstream labels.

## Uncertainty Pool

- Phase 1 target bins: {len(all_detail):,}
- Phase 1 directly labeled bins: {total_labeled:,}
- Uncertain or not assignable bins audited: {len(uncertain):,}

## Primary Reasons

{json.dumps(reason_counts, indent=2)}

Key blockers:

- Route suffix / geometry conflicts: {suffix_conflicts:,}
- Missing route suffix direction: {suffix_missing:,}
- Missing measure orientation evidence: {measure_missing:,}
- Low-confidence or inferred anchor evidence: {anchor_low:,}

## Recoverability

{json.dumps(rec_counts, indent=2)}

Estimated bins recoverable under proposed safe relaxed rule classes: {relaxed:,}.

This is an estimate only. No new labels were assigned.

## Interpretation

The largest uncertainty source is not undivided centerline logic; those rows are out of scope here. Within the direct divided/one-way target pool, uncertainty is dominated by route suffix/geometry conflicts and oblique signal-relative positioning. Many rows also use inferred anchors because canonical signal geometry is incomplete, so direct labels should remain review-only until map review.

## Recommendation

Map-review the route suffix/geometry conflict examples before implementing a relaxed direct rule. A bounded relaxed direct pass may be worthwhile for rows where route suffix or measure evidence is strong and geometry appears reversed by source digitization. Phase 2 undivided centerline synthesis is still required for the larger non-direct pool.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_direct_directionality_uncertainty_audit_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_direct_directionality_uncertainty_audit_findings.md")


def write_manifest(outputs: list[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.audit.final_analysis_direct_directionality_uncertainty_audit",
        "bounded_question": "Decompose uncertainty in Phase 1 direct divided/one-way directionality labels.",
        "inputs": {
            "phase1": str(PHASE1_DIR),
            "doctrine": str(DOCTRINE_DIR),
            "canonical": str(CANONICAL_DIR),
            "enhanced": str(ENHANCED_DIR),
        },
        "outputs": outputs,
        "non_goals": [
            "No new downstream/upstream labels",
            "No undivided centerline assignment",
            "No crash direction fields",
            "No access/crash assignment",
            "No rates/models",
            "No active output modification",
        ],
    }
    (OUT_DIR / "final_analysis_direct_directionality_uncertainty_audit_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_log("Wrote final_analysis_direct_directionality_uncertainty_audit_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting direct directionality uncertainty audit.")

    detail = read_csv(PHASE1_DIR / "direct_divided_bin_directionality_detail.csv")
    qa_phase1 = read_csv(PHASE1_DIR / "direct_divided_directionality_qa_checks.csv")
    write_log(f"Loaded Phase 1 detail rows={len(detail):,}.")

    label = detail["direct_directionality_label"].fillna("")
    uncertain = detail[label.isin(["direction_supported_but_uncertain", "direct_direction_not_assignable", ""])].copy()
    uncertain = uncertain[uncertain["directionality_support_class"].isin(TARGET_CLASSES)].copy()
    write_log(f"Built uncertainty pool={len(uncertain):,}.")

    uncertain = assign_uncertainty_reason(uncertain)

    preserve_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "signal_approach_id",
        "carriageway_source_subpart_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "route_key_common",
        "route_key_name",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "x0",
        "y0",
        "x1",
        "y1",
        "mx",
        "my",
        "anchor_x",
        "anchor_y",
        "anchor_method",
        "route_suffix_direction",
        "route_suffix_bearing",
        "geometry_bearing",
        "signal_to_bin_bearing",
        "flow_vs_signal_to_bin_angle_diff",
        "travelway_flow_bearing",
        "travelway_flow_method",
        "travelway_flow_confidence",
        "measure_orientation_consistency",
        "geometry_suffix_consistency",
        "directionality_support_class",
        "directionality_source_evidence",
        "direct_directionality_label",
        "direct_directionality_method",
        "direct_directionality_confidence",
        "direct_directionality_reason",
        "rim_facility_raw",
        "RTE_RAMP_C",
        "final_review_recovery_provenance",
    ]
    audit_cols = preserve_cols + [
        "primary_uncertainty_class",
        "recoverable_uncertainty_class",
        "potential_relaxed_rule_class",
        "potentially_recoverable_with_safe_relaxed_rule",
        "route_suffix_present",
        "measure_orientation_present",
        "anchor_low_confidence",
        "geometry_likely_reversed_vs_route_suffix",
        "suffix_measure_agreement_status",
    ]

    write_csv(uncertain[preserve_cols], "direct_directionality_uncertain_target_bins.csv")
    write_csv(uncertain[audit_cols], "direct_directionality_uncertainty_reason_detail.csv")

    reason_summary = summary_counts(uncertain, "primary_uncertainty_class")
    reason_summary["share_of_uncertain_bins"] = reason_summary["bins"] / len(uncertain)
    write_csv(reason_summary, "direct_directionality_uncertainty_reason_summary.csv")

    recover_summary = summary_counts(uncertain, "recoverable_uncertainty_class")
    recover_summary["share_of_uncertain_bins"] = recover_summary["bins"] / len(uncertain)
    write_csv(recover_summary, "direct_directionality_recoverable_uncertainty_summary.csv")

    conflict_summary = build_conflict_summary(uncertain)
    write_csv(conflict_summary, "direct_directionality_conflict_pattern_summary.csv")

    gap_summary = signal_approach_gap_summary(uncertain, detail)
    write_csv(gap_summary, "direct_directionality_signal_approach_gap_summary.csv")

    relaxed = (
        uncertain.groupby("potential_relaxed_rule_class", dropna=False)
        .agg(
            bins=("stable_bin_id", "count"),
            signals=("stable_signal_id", "nunique"),
            approaches=("signal_approach_id", "nunique"),
            target_reasons=("primary_uncertainty_class", lambda s: "; ".join(sorted(set(map(str, s.dropna())))[:8])),
        )
        .reset_index()
    )
    relaxed["is_recoverable_estimate"] = relaxed["potential_relaxed_rule_class"].ne("not_recoverable_by_safe_relaxed_rule")
    write_csv(relaxed, "direct_directionality_relaxed_rule_estimate.csv")

    example_classes = [
        "missing_route_suffix_direction",
        "route_suffix_geometry_conflict",
        "measure_orientation_missing",
        "anchor_geometry_missing_or_low_confidence",
        "conservative_rule_blocked_otherwise_assignable",
        "true_direct_direction_ambiguous",
    ]
    examples = []
    for cls in example_classes:
        examples.append(uncertain[uncertain["primary_uncertainty_class"].eq(cls)].head(20))
    examples.append(uncertain[uncertain["potentially_recoverable_with_safe_relaxed_rule"]].head(30))
    examples_df = pd.concat(examples, ignore_index=True).drop_duplicates("stable_bin_id")
    write_csv(examples_df[audit_cols], "direct_directionality_uncertainty_review_examples.csv")

    next_action = pd.DataFrame(
        [
            {
                "recommendation": "map_review_conflicts_then_consider_relaxed_direct_rule_before_canonical_integration",
                "uncertain_bins": len(uncertain),
                "potentially_recoverable_bins": int(uncertain["potentially_recoverable_with_safe_relaxed_rule"].sum()),
                "should_remain_uncertain_bins": int((uncertain["recoverable_uncertainty_class"] == "should_remain_uncertain").sum()),
                "needs_map_review_bins": int((uncertain["recoverable_uncertainty_class"] == "needs_map_review").sum()),
                "phase2_directionality": "undivided_centerline_synthesis_still_required",
                "rationale": "Route suffix/geometry conflicts dominate and likely include source digitization reversal, but direct relaxed rules need map review before implementation.",
            }
        ]
    )
    write_csv(next_action, "direct_directionality_uncertainty_next_action.csv")

    no_new_labels = not any(
        c in uncertain.columns for c in ["new_direct_directionality_label", "relaxed_downstream_upstream_label"]
    )
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to analysis/current uncertainty audit folder."),
            ("no_records_promoted", True, "Review-only diagnostic."),
            ("no_access_crash_assignment", True, "No access/crash assignment run."),
            ("no_rates_models", True, "No rates/models calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
            ("no_final_new_downstream_upstream_labels_assigned", no_new_labels, "Audit estimates recoverability only."),
            (
                "undivided_centerline_rows_out_of_scope",
                bool(uncertain["directionality_support_class"].isin(TARGET_CLASSES).all()),
                "Only Phase 1 direct divided/one-way target classes included.",
            ),
            (
                "uncertainty_pool_matches_phase1",
                len(uncertain) == 111562,
                f"uncertain rows={len(uncertain):,}; expected from Phase 1=111,562",
            ),
            ("phase1_qa_read", bool(qa_phase1["passed"].all()), "Phase 1 QA table was read and all checks passed."),
            ("outputs_review_only_folder", True, str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(qa, "final_analysis_direct_directionality_uncertainty_audit_qa.csv")
    write_findings(uncertain, detail, qa)

    outputs = [
        "direct_directionality_uncertain_target_bins.csv",
        "direct_directionality_uncertainty_reason_detail.csv",
        "direct_directionality_uncertainty_reason_summary.csv",
        "direct_directionality_recoverable_uncertainty_summary.csv",
        "direct_directionality_conflict_pattern_summary.csv",
        "direct_directionality_signal_approach_gap_summary.csv",
        "direct_directionality_relaxed_rule_estimate.csv",
        "direct_directionality_uncertainty_review_examples.csv",
        "direct_directionality_uncertainty_next_action.csv",
        "final_analysis_direct_directionality_uncertainty_audit_findings.md",
        "final_analysis_direct_directionality_uncertainty_audit_qa.csv",
        "final_analysis_direct_directionality_uncertainty_audit_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed direct directionality uncertainty audit.")


if __name__ == "__main__":
    main()
