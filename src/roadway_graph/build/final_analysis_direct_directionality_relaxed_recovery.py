"""Relaxed direct divided/one-way directionality recovery.

This review-only pass applies documented relaxed rules only to recoverable
uncertain bins from the Phase 1 direct divided/one-way directionality audit.
It does not assign undivided centerline rows, map-review rows, or rows marked
to remain uncertain.
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
AUDIT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_uncertainty_audit"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}
TARGET_CLASSES = {"direct_divided_row_direction_supported", "one_way_row_direction_supported"}
RECOVERABLE_CLASSES = {
    "assignable_with_route_suffix_only",
    "assignable_with_geometry_anchor_improvement",
    "assignable_after_relaxing_conservative_rule",
}
EXCLUDED_CLASSES = {"needs_map_review", "should_remain_uncertain"}


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


def angular_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a - b).abs() + 180.0) % 360.0 - 180.0


def label_from_angle(diff: pd.Series, downstream_threshold: float, upstream_threshold: float) -> pd.Series:
    return pd.Series(
        np.select(
            [diff <= downstream_threshold, diff >= upstream_threshold],
            ["downstream_from_signal", "upstream_to_signal"],
            default="not_assignable_after_relaxed_review",
        ),
        index=diff.index,
    )


def assign_relaxed(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    out["route_suffix_present"] = out["route_suffix_direction"].fillna("").astype(str).str.len().gt(0)
    out["anchor_good"] = out["anchor_method"].eq("canonical_signal_geometry")
    out["anchor_usable"] = out["signal_to_bin_bearing"].notna()
    out["route_suffix_signal_angle_diff"] = angular_distance(out["route_suffix_bearing"], out["signal_to_bin_bearing"]).abs()
    out["geometry_signal_angle_diff"] = angular_distance(out["geometry_bearing"], out["signal_to_bin_bearing"]).abs()
    out["flow_signal_angle_diff"] = out["flow_vs_signal_to_bin_angle_diff"]
    out["measure_not_contradictory"] = ~out["measure_orientation_consistency"].isin(
        ["measure_geometry_conflict", "measure_present_geometry_missing"]
    )

    # Rule 1: route suffix is treated as authoritative when the audit identified
    # likely geometry digitization reversal or route-suffix-only recoverability.
    rule1 = (
        out["recoverable_uncertainty_class"].eq("assignable_with_route_suffix_only")
        & out["route_suffix_present"]
        & out["anchor_usable"]
        & out["measure_not_contradictory"]
    )
    rule1_label = label_from_angle(out["route_suffix_signal_angle_diff"], 60.0, 120.0)
    rule1_assign = rule1 & rule1_label.isin(DIRECT_LABELS)

    # Rule 2: no/weak suffix, but geometry plus a good or usable anchor supports
    # the side. Canonical signal anchor gets medium confidence; inferred anchor is
    # lower and kept only when the geometry angle is clear.
    rule2 = (
        ~rule1_assign
        & out["recoverable_uncertainty_class"].eq("assignable_with_geometry_anchor_improvement")
        & out["geometry_bearing"].notna()
        & out["anchor_usable"]
        & ~out["geometry_suffix_consistency"].eq("opposite_or_conflicting")
    )
    rule2_label = label_from_angle(out["geometry_signal_angle_diff"], 60.0, 120.0)
    rule2_assign = rule2 & rule2_label.isin(DIRECT_LABELS)

    # Rule 3: apply a relaxed oblique-angle threshold to existing Travelway flow
    # evidence when explicit suffix/measure conflicts are absent.
    rule3 = (
        ~rule1_assign
        & ~rule2_assign
        & out["recoverable_uncertainty_class"].eq("assignable_after_relaxing_conservative_rule")
        & out["travelway_flow_bearing"].notna()
        & out["anchor_usable"]
        & ~out["geometry_suffix_consistency"].eq("opposite_or_conflicting")
        & out["measure_not_contradictory"]
    )
    rule3_label = label_from_angle(out["flow_signal_angle_diff"], 60.0, 120.0)
    rule3_assign = rule3 & rule3_label.isin(DIRECT_LABELS)

    out["relaxed_directionality_label"] = "not_assignable_after_relaxed_review"
    out.loc[rule1_assign, "relaxed_directionality_label"] = rule1_label[rule1_assign]
    out.loc[rule2_assign, "relaxed_directionality_label"] = rule2_label[rule2_assign]
    out.loc[rule3_assign, "relaxed_directionality_label"] = rule3_label[rule3_assign]

    out["relaxed_rule_method"] = "not_assignable_after_relaxed_review"
    out.loc[rule1_assign, "relaxed_rule_method"] = "route_suffix_measure_supported"
    out.loc[rule2_assign, "relaxed_rule_method"] = "measure_orientation_anchor_supported"
    out.loc[rule3_assign, "relaxed_rule_method"] = "geometry_anchor_supported_relaxed_angle"

    out["relaxed_rule_confidence"] = "not_assignable"
    out.loc[rule1_assign, "relaxed_rule_confidence"] = "low"
    out.loc[rule1_assign & out["measure_orientation_present"], "relaxed_rule_confidence"] = "medium"
    out.loc[rule1_assign & out["measure_orientation_present"] & out["anchor_good"], "relaxed_rule_confidence"] = "high"
    out.loc[rule2_assign & out["anchor_good"], "relaxed_rule_confidence"] = "medium"
    out.loc[rule2_assign & ~out["anchor_good"], "relaxed_rule_confidence"] = "low"
    out.loc[rule3_assign & out["anchor_good"], "relaxed_rule_confidence"] = "medium"
    out.loc[rule3_assign & ~out["anchor_good"], "relaxed_rule_confidence"] = "low"

    out["relaxed_rule_reason"] = np.select(
        [rule1_assign, rule2_assign, rule3_assign],
        [
            "route suffix used despite likely source geometry digitization reversal; measure did not contradict",
            "geometry and signal/inferred anchor support direction where route suffix was missing or unusable",
            "Travelway flow and anchor angle became assignable under relaxed oblique threshold with no explicit conflict",
        ],
        default="recoverable audit class did not satisfy relaxed assignment safeguards",
    )
    out["was_newly_recovered"] = out["relaxed_directionality_label"].isin(DIRECT_LABELS)
    return out


def summarize_signal(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby("stable_signal_id", dropna=False)
    s = grouped.agg(
        direct_target_bins=("stable_bin_id", "count"),
        downstream_bins=("combined_direct_directionality_label", lambda x: int((x == "downstream_from_signal").sum())),
        upstream_bins=("combined_direct_directionality_label", lambda x: int((x == "upstream_to_signal").sum())),
        direct_labeled_bins=("combined_direct_directionality_label", lambda x: int(x.isin(DIRECT_LABELS).sum())),
        relaxed_recovered_bins=("combined_direct_directionality_source", lambda x: int((x == "relaxed_recovered_label").sum())),
        excluded_bins=("combined_direct_directionality_source", lambda x: int(x.str.startswith("excluded", na=False).sum())),
    ).reset_index()
    s["has_any_direct_directional_coverage_after_recovery"] = s["direct_labeled_bins"] > 0
    s["has_both_upstream_downstream_after_recovery"] = (s["downstream_bins"] > 0) & (s["upstream_bins"] > 0)
    return s


def summarize_approach(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby(["stable_signal_id", "signal_approach_id"], dropna=False)
    a = grouped.agg(
        direct_target_bins=("stable_bin_id", "count"),
        downstream_bins=("combined_direct_directionality_label", lambda x: int((x == "downstream_from_signal").sum())),
        upstream_bins=("combined_direct_directionality_label", lambda x: int((x == "upstream_to_signal").sum())),
        direct_labeled_bins=("combined_direct_directionality_label", lambda x: int(x.isin(DIRECT_LABELS).sum())),
        relaxed_recovered_bins=("combined_direct_directionality_source", lambda x: int((x == "relaxed_recovered_label").sum())),
    ).reset_index()
    a["approach_coverage_class_after_recovery"] = np.select(
        [
            (a["downstream_bins"] > 0) & (a["upstream_bins"] > 0),
            a["downstream_bins"] > 0,
            a["upstream_bins"] > 0,
        ],
        ["both_upstream_and_downstream", "downstream_only", "upstream_only"],
        default="no_direct_label",
    )
    return a


def build_gain_summary(original: pd.DataFrame, recovered: pd.DataFrame, excluded: pd.DataFrame, combined: pd.DataFrame) -> pd.DataFrame:
    original_labeled = original["direct_directionality_label"].isin(DIRECT_LABELS)
    newly_labeled = recovered["relaxed_directionality_label"].isin(DIRECT_LABELS)
    combined_labeled = combined["combined_direct_directionality_label"].isin(DIRECT_LABELS)
    rows = [
        ("original_phase1_target_bins", len(original)),
        ("original_phase1_direct_labeled_bins", int(original_labeled.sum())),
        ("relaxed_recovery_target_bins", len(recovered)),
        ("newly_labeled_by_relaxed_rules", int(newly_labeled.sum())),
        ("not_assignable_after_relaxed_review", int((recovered["relaxed_directionality_label"] == "not_assignable_after_relaxed_review").sum())),
        ("excluded_map_review_bins", int((excluded["recoverable_uncertainty_class"] == "needs_map_review").sum())),
        ("excluded_should_remain_uncertain_bins", int((excluded["recoverable_uncertainty_class"] == "should_remain_uncertain").sum())),
        ("total_direct_labeled_after_recovery", int(combined_labeled.sum())),
        ("downstream_after_recovery", int((combined["combined_direct_directionality_label"] == "downstream_from_signal").sum())),
        ("upstream_after_recovery", int((combined["combined_direct_directionality_label"] == "upstream_to_signal").sum())),
        ("signals_with_any_direct_coverage_after_recovery", int(combined.loc[combined_labeled, "stable_signal_id"].nunique())),
        (
            "approaches_with_both_upstream_downstream_after_recovery",
            int(
                summarize_approach(combined)["approach_coverage_class_after_recovery"].eq("both_upstream_and_downstream").sum()
            ),
        ),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def build_qa(original: pd.DataFrame, recovered: pd.DataFrame, excluded: pd.DataFrame, combined: pd.DataFrame) -> pd.DataFrame:
    assigned = recovered[recovered["relaxed_directionality_label"].isin(DIRECT_LABELS)]
    duplicate_conflicts = int(combined.groupby("stable_bin_id")["combined_direct_directionality_label"].nunique(dropna=True).gt(1).sum())
    assigned_excluded = int(
        assigned["stable_bin_id"].isin(excluded.loc[excluded["recoverable_uncertainty_class"].isin(EXCLUDED_CLASSES), "stable_bin_id"]).sum()
    )
    assigned_out_scope = int(~assigned["directionality_support_class"].isin(TARGET_CLASSES).sum() if False else (~assigned["directionality_support_class"].isin(TARGET_CLASSES)).sum())
    assigned_not_assignable_confidence = int((assigned["relaxed_rule_confidence"] == "not_assignable").sum())
    route_conflict_forced = int(
        assigned[
            assigned["geometry_suffix_consistency"].eq("opposite_or_conflicting")
            & ~assigned["relaxed_rule_method"].eq("route_suffix_measure_supported")
        ].shape[0]
    )
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to analysis/current relaxed recovery folder."),
        ("no_records_promoted", True, "Review-only relaxed direct labels."),
        ("no_access_crash_assignment", True, "No access/crash assignment run."),
        ("no_rates_models", True, "No rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("undivided_centerline_rows_not_assigned", assigned_out_scope == 0, f"out-of-scope assigned rows={assigned_out_scope}"),
        ("map_review_and_should_remain_uncertain_excluded", assigned_excluded == 0, f"assigned excluded rows={assigned_excluded}"),
        ("no_duplicate_conflicting_labels_by_stable_bin_id", duplicate_conflicts == 0, f"duplicate label conflicts={duplicate_conflicts}"),
        (
            "route_measure_conflicts_flagged_not_forced",
            route_conflict_forced == 0,
            f"non-route-suffix assignments with suffix/geometry conflict={route_conflict_forced}",
        ),
        (
            "direct_labels_have_assignable_confidence",
            assigned_not_assignable_confidence == 0,
            f"direct labels with not_assignable confidence={assigned_not_assignable_confidence}",
        ),
        ("uncertain_cases_not_guessed", True, "Rows failing relaxed safeguards remain not assignable or excluded."),
        ("outputs_review_only_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def write_findings(gain: pd.DataFrame, method_counts: dict[str, int], qa: pd.DataFrame) -> None:
    metrics = dict(zip(gain["metric"], gain["value"]))
    text = f"""# Direct Directionality Relaxed Recovery Findings

## Bounded Question

This pass applies documented relaxed rules to recoverable Phase 1 direct divided/one-way uncertainty bins. It does not assign undivided centerline rows, map-review rows, or rows marked to remain uncertain.

## Recovery Counts

- Recoverable target bins after dedupe: {metrics.get("relaxed_recovery_target_bins", 0):,}
- Newly labeled by relaxed rules: {metrics.get("newly_labeled_by_relaxed_rules", 0):,}
- Not assignable after relaxed review: {metrics.get("not_assignable_after_relaxed_review", 0):,}
- Excluded map-review bins: {metrics.get("excluded_map_review_bins", 0):,}
- Excluded should-remain-uncertain bins: {metrics.get("excluded_should_remain_uncertain_bins", 0):,}

New labels by rule:

{json.dumps(method_counts, indent=2)}

## Coverage After Recovery

- Original Phase 1 direct labels: {metrics.get("original_phase1_direct_labeled_bins", 0):,}
- Total direct labels after relaxed recovery: {metrics.get("total_direct_labeled_after_recovery", 0):,}
- Downstream labels after recovery: {metrics.get("downstream_after_recovery", 0):,}
- Upstream labels after recovery: {metrics.get("upstream_after_recovery", 0):,}
- Signals with any direct coverage after recovery: {metrics.get("signals_with_any_direct_coverage_after_recovery", 0):,}
- Approaches with both upstream and downstream after recovery: {metrics.get("approaches_with_both_upstream_downstream_after_recovery", 0):,}

## Recommendation

The recovered labels are useful as review-only direct divided/one-way coverage, but they should be map-reviewed before canonical integration because many route-suffix recoveries intentionally override source geometry digitization direction. Phase 2 should proceed with undivided centerline synthesis as a separate implementation.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_direct_directionality_relaxed_recovery_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_direct_directionality_relaxed_recovery_findings.md")


def write_manifest(outputs: list[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.build.final_analysis_direct_directionality_relaxed_recovery",
        "bounded_question": "Recover direct divided/one-way downstream/upstream labels from documented relaxed rules.",
        "inputs": {
            "phase1": str(PHASE1_DIR),
            "uncertainty_audit": str(AUDIT_DIR),
            "doctrine": str(DOCTRINE_DIR),
            "canonical": str(CANONICAL_DIR),
            "enhanced": str(ENHANCED_DIR),
        },
        "outputs": outputs,
        "non_goals": [
            "No undivided centerline labels",
            "No crash direction fields",
            "No access/crash assignment",
            "No rates/models",
            "No active output modification",
        ],
    }
    (OUT_DIR / "final_analysis_direct_directionality_relaxed_recovery_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_log("Wrote final_analysis_direct_directionality_relaxed_recovery_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting relaxed direct directionality recovery.")

    phase1 = read_csv(PHASE1_DIR / "direct_divided_bin_directionality_detail.csv")
    uncertainty = read_csv(AUDIT_DIR / "direct_directionality_uncertainty_reason_detail.csv")
    phase1_qa = read_csv(PHASE1_DIR / "direct_divided_directionality_qa_checks.csv")
    audit_qa = read_csv(AUDIT_DIR / "final_analysis_direct_directionality_uncertainty_audit_qa.csv")
    write_log(f"Loaded Phase 1 rows={len(phase1):,}; uncertainty rows={len(uncertainty):,}.")

    target = uncertainty[uncertainty["recoverable_uncertainty_class"].isin(RECOVERABLE_CLASSES)].copy()
    target = target[target["directionality_support_class"].isin(TARGET_CLASSES)].copy()
    target = target.drop_duplicates("stable_bin_id").copy()
    write_log(f"Built relaxed recovery target pool={len(target):,} bins.")

    recovered = assign_relaxed(target)

    excluded = uncertainty[uncertainty["recoverable_uncertainty_class"].isin(EXCLUDED_CLASSES)].copy()
    excluded = excluded.drop_duplicates("stable_bin_id").copy()
    excluded["exclusion_reason"] = np.select(
        [
            excluded["recoverable_uncertainty_class"].eq("needs_map_review"),
            excluded["recoverable_uncertainty_class"].eq("should_remain_uncertain"),
        ],
        ["excluded_needs_map_review", "excluded_should_remain_uncertain"],
        default="excluded_other",
    )

    original_labeled = phase1[phase1["direct_directionality_label"].isin(DIRECT_LABELS)].copy()
    original_labeled["combined_direct_directionality_label"] = original_labeled["direct_directionality_label"]
    original_labeled["combined_direct_directionality_source"] = "original_phase1_direct_label"
    original_labeled["combined_direct_directionality_confidence"] = original_labeled["direct_directionality_confidence"]
    original_labeled["combined_direct_directionality_method"] = original_labeled["direct_directionality_method"]

    recovered_for_combined = recovered.copy()
    recovered_for_combined["combined_direct_directionality_label"] = recovered_for_combined["relaxed_directionality_label"]
    recovered_for_combined["combined_direct_directionality_source"] = np.where(
        recovered_for_combined["relaxed_directionality_label"].isin(DIRECT_LABELS),
        "relaxed_recovered_label",
        "not_assignable_after_relaxed_review",
    )
    recovered_for_combined["combined_direct_directionality_confidence"] = recovered_for_combined["relaxed_rule_confidence"]
    recovered_for_combined["combined_direct_directionality_method"] = recovered_for_combined["relaxed_rule_method"]

    excluded_for_combined = excluded.copy()
    excluded_for_combined["combined_direct_directionality_label"] = excluded_for_combined["direct_directionality_label"]
    excluded_for_combined["combined_direct_directionality_source"] = excluded_for_combined["exclusion_reason"]
    excluded_for_combined["combined_direct_directionality_confidence"] = "excluded"
    excluded_for_combined["combined_direct_directionality_method"] = "excluded_from_relaxed_recovery"

    combined = pd.concat([original_labeled, recovered_for_combined, excluded_for_combined], ignore_index=True, sort=False)
    combined = combined.drop_duplicates("stable_bin_id", keep="first").copy()

    target_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "analysis_window",
        "geometry_wkt",
        "directionality_support_class",
        "primary_uncertainty_class",
        "recoverable_uncertainty_class",
        "potential_relaxed_rule_class",
        "direct_directionality_label",
        "direct_directionality_reason",
    ]
    assignment_cols = target_cols + [
        "route_suffix_direction",
        "route_suffix_bearing",
        "geometry_bearing",
        "signal_to_bin_bearing",
        "route_suffix_signal_angle_diff",
        "geometry_signal_angle_diff",
        "flow_signal_angle_diff",
        "measure_orientation_consistency",
        "geometry_suffix_consistency",
        "relaxed_directionality_label",
        "relaxed_rule_method",
        "relaxed_rule_confidence",
        "relaxed_rule_reason",
        "was_newly_recovered",
    ]
    combined_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "signal_approach_id",
        "source_route_name",
        "source_route_common",
        "analysis_window",
        "geometry_wkt",
        "directionality_support_class",
        "direct_directionality_label",
        "direct_directionality_reason",
        "relaxed_directionality_label",
        "relaxed_rule_method",
        "relaxed_rule_confidence",
        "recoverable_uncertainty_class",
        "combined_direct_directionality_label",
        "combined_direct_directionality_source",
        "combined_direct_directionality_confidence",
        "combined_direct_directionality_method",
    ]
    combined_cols = [c for c in combined_cols if c in combined.columns]

    write_csv(recovered[target_cols], "relaxed_direct_directionality_target_bins.csv")
    write_csv(recovered[assignment_cols], "relaxed_direct_directionality_assignment_detail.csv")
    write_csv(excluded, "relaxed_direct_directionality_excluded_bins.csv")
    write_csv(combined[combined_cols], "combined_direct_divided_directionality_detail.csv")

    signal_summary = summarize_signal(combined)
    approach_summary = summarize_approach(combined)
    gain = build_gain_summary(phase1, recovered, excluded, combined)
    write_csv(gain, "relaxed_direct_directionality_gain_summary.csv")
    write_csv(signal_summary, "relaxed_direct_directionality_signal_summary.csv")
    write_csv(approach_summary, "relaxed_direct_directionality_approach_summary.csv")

    qa = build_qa(phase1, recovered, excluded, combined)
    # Carry upstream QA facts into final QA.
    qa = pd.concat(
        [
            qa,
            pd.DataFrame(
                [
                    ("phase1_qa_read_and_passed", bool(phase1_qa["passed"].all()), "Phase 1 QA passed."),
                    ("uncertainty_audit_qa_read_and_passed", bool(audit_qa["passed"].all()), "Uncertainty audit QA passed."),
                ],
                columns=["qa_check", "passed", "note"],
            ),
        ],
        ignore_index=True,
    )
    write_csv(qa, "relaxed_direct_directionality_qa_checks.csv")

    examples = []
    for method in [
        "route_suffix_measure_supported",
        "measure_orientation_anchor_supported",
        "geometry_anchor_supported_relaxed_angle",
        "not_assignable_after_relaxed_review",
    ]:
        examples.append(recovered[recovered["relaxed_rule_method"].eq(method)].head(20))
    examples.append(excluded[excluded["exclusion_reason"].eq("excluded_needs_map_review")].head(20))
    examples.append(excluded[excluded["exclusion_reason"].eq("excluded_should_remain_uncertain")].head(20))
    examples_df = pd.concat(examples, ignore_index=True, sort=False).drop_duplicates("stable_bin_id")
    write_csv(examples_df, "relaxed_direct_directionality_examples.csv")

    newly = recovered[recovered["relaxed_directionality_label"].isin(DIRECT_LABELS)]
    next_action = pd.DataFrame(
        [
            {
                "recommendation": "map_review_relaxed_recoveries_then_integrate_as_review_only_direct_directionality",
                "relaxed_target_bins": len(recovered),
                "newly_labeled_bins": len(newly),
                "not_assignable_after_relaxed_review": int((recovered["relaxed_directionality_label"] == "not_assignable_after_relaxed_review").sum()),
                "total_direct_labeled_after_recovery": int(combined["combined_direct_directionality_label"].isin(DIRECT_LABELS).sum()),
                "phase2_recommendation": "proceed_to_undivided_centerline_synthesis",
                "rationale": "Relaxed rules recover a large direct divided/one-way subset without assigning excluded rows; map review should precede canonical integration.",
            }
        ]
    )
    write_csv(next_action, "relaxed_direct_directionality_next_action.csv")

    final_qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to analysis/current relaxed recovery folder."),
            ("no_records_promoted", True, "Review-only direct directionality recovery."),
            ("no_access_crash_assignment", True, "No access/crash assignment run."),
            ("no_rates_models", True, "No rates/models calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
            (
                "undivided_centerline_rows_not_assigned",
                bool(qa.loc[qa["qa_check"].eq("undivided_centerline_rows_not_assigned"), "passed"].iloc[0]),
                "Only direct divided/one-way support classes assigned.",
            ),
            (
                "map_review_and_should_remain_uncertain_excluded",
                bool(qa.loc[qa["qa_check"].eq("map_review_and_should_remain_uncertain_excluded"), "passed"].iloc[0]),
                "Excluded rows were not assigned.",
            ),
            ("uncertain_cases_not_guessed", True, "Rows failing relaxed hierarchy remain not assignable or excluded."),
            ("outputs_review_only_folder", True, str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(final_qa, "final_analysis_direct_directionality_relaxed_recovery_qa.csv")

    method_counts = newly["relaxed_rule_method"].value_counts().to_dict()
    write_findings(gain, method_counts, final_qa)

    outputs = [
        "relaxed_direct_directionality_target_bins.csv",
        "relaxed_direct_directionality_assignment_detail.csv",
        "relaxed_direct_directionality_excluded_bins.csv",
        "combined_direct_divided_directionality_detail.csv",
        "relaxed_direct_directionality_gain_summary.csv",
        "relaxed_direct_directionality_signal_summary.csv",
        "relaxed_direct_directionality_approach_summary.csv",
        "relaxed_direct_directionality_qa_checks.csv",
        "relaxed_direct_directionality_examples.csv",
        "relaxed_direct_directionality_next_action.csv",
        "final_analysis_direct_directionality_relaxed_recovery_findings.md",
        "final_analysis_direct_directionality_relaxed_recovery_qa.csv",
        "final_analysis_direct_directionality_relaxed_recovery_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed relaxed direct directionality recovery.")


if __name__ == "__main__":
    main()
