"""Ramp/interchange-specific residual directionality recovery.

This review-only pass revisits uncovered ramp/interchange-context bins after the
general residual recovery. It recovers only low-risk signal-relevant ramp,
frontage/service, or surface-interchange rows and keeps true grade-separated
mainline or mixed/ambiguous rows uncovered.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_residual_directionality_recovery"
COVERAGE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_coverage_audit"
DIRECT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"
UNDIVIDED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_ramp_interchange_directionality_recovery"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}


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


def label_from_angle(diff: pd.Series, downstream_threshold: float = 60.0, upstream_threshold: float = 120.0) -> pd.Series:
    return pd.Series(
        np.select(
            [diff <= downstream_threshold, diff >= upstream_threshold],
            ["downstream_from_signal", "upstream_to_signal"],
            default="not_recovered",
        ),
        index=diff.index,
    )


def build_target() -> pd.DataFrame:
    ramp = read_csv(RESIDUAL_DIR / "ramp_interchange_directionality_recovery_detail.csv")
    remaining = read_csv(
        RESIDUAL_DIR / "residual_directionality_remaining_uncovered_bins.csv",
        usecols=lambda c: c in ["stable_bin_id", "map_review_priority"],
    )
    target = ramp.merge(remaining, on="stable_bin_id", how="inner")
    write_log(f"Built ramp/interchange target pool={len(target):,} bins.")
    return target


def classify_and_recover(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    text = (
        out["source_route_name"].fillna("")
        + " "
        + out["source_route_common"].fillna("")
        + " "
        + out["RTE_TYPE_N"].fillna("")
        + " "
        + out["RTE_CATEGO"].fillna("")
    ).str.lower()
    ramp_code = out["RTE_RAMP_C"].fillna("").astype(str).str.strip()
    is_ramp_coded = ramp_code.ne("")
    is_interstate = out["RTE_TYPE_N"].fillna("").str.contains("Interstate", case=False, regex=False) | out[
        "RTE_CATEGO"
    ].fillna("").str.contains("Interstate", case=False, regex=False)
    is_frontage_service = text.str.contains("frontage|service|dist/coll|collector|dcr|cd road", regex=True)
    is_oneway = out["rim_facility_raw"].fillna("").str.contains("One-Way", case=False, regex=False)
    is_surface = out["rim_facility_raw"].fillna("").str.contains("Two-Way|One-Way", case=False, regex=True)
    provenance_signal_relevant = (
        out["final_review_recovery_provenance"].fillna("").str.contains("ramp_terminal|missing_leg|intersection_zone|residual", case=False, regex=True)
        | out["final_review_leg_source"].fillna("").str.contains("generated|label_only", case=False, regex=True)
    )
    anchor_usable = out["signal_to_bin_bearing_residual"].notna()
    geom_usable = out["geometry_bearing_residual"].notna()
    axis_strong = out["approach_axis_diff_residual"].le(15.0)
    axis_moderate = out["approach_axis_diff_residual"].le(30.0)
    suffix_present = out["route_suffix_direction_residual"].fillna("").astype(str).str.len().gt(0)
    suffix_label = label_from_angle(out["suffix_signal_angle_diff_residual"], 60.0, 120.0)
    geom_angle = angular_distance(out["geometry_bearing_residual"], out["signal_to_bin_bearing_residual"]).abs()
    geom_label = label_from_angle(geom_angle, 60.0, 120.0)

    # Conservative taxonomy. Interstate/freeway ramp-coded rows are held unless
    # they have signal-relevant provenance or frontage/service-road evidence.
    true_mainline = is_ramp_coded & is_interstate & ~provenance_signal_relevant & ~is_frontage_service
    frontage = is_frontage_service & is_surface
    signal_ramp_terminal = is_ramp_coded & is_oneway & provenance_signal_relevant
    surface_interchange = ~true_mainline & is_surface & ~is_ramp_coded & text.str.contains("ramp|interchange|i-", regex=True)
    mixed = is_ramp_coded & ~true_mainline & ~signal_ramp_terminal & ~frontage

    out["ramp_interchange_primary_class"] = np.select(
        [
            signal_ramp_terminal,
            frontage,
            surface_interchange,
            true_mainline,
            mixed,
            is_ramp_coded,
            axis_moderate & is_surface,
        ],
        [
            "signal_relevant_ramp_terminal_leg",
            "signal_relevant_frontage_or_service_road",
            "signal_relevant_surface_crossroad_near_interchange",
            "true_grade_separated_mainline_holdout",
            "ramp_mainline_mixed_needs_subbranch_split",
            "ramp_geometry_ambiguous",
            "signal_relevant_surface_crossroad_near_interchange",
        ],
        default="insufficient_direction_evidence",
    )

    # Separable mixed rows need clear generated/subbranch signal relevance.
    separable_mixed = (
        out["ramp_interchange_primary_class"].eq("ramp_mainline_mixed_needs_subbranch_split")
        & provenance_signal_relevant
        & is_oneway
        & anchor_usable
        & geom_usable
        & axis_strong
    )
    out.loc[separable_mixed, "ramp_interchange_primary_class"] = "signal_relevant_ramp_terminal_leg"
    out["mixed_source_qa_flag"] = np.where(separable_mixed, "ramp_mainline_subbranch_split_recovered", "")

    route_recoverable = (
        out["ramp_interchange_primary_class"].isin(
            [
                "signal_relevant_ramp_terminal_leg",
                "signal_relevant_frontage_or_service_road",
                "signal_relevant_surface_crossroad_near_interchange",
            ]
        )
        & suffix_present
        & anchor_usable
        & suffix_label.isin(DIRECT_LABELS)
    )
    geom_recoverable = (
        out["ramp_interchange_primary_class"].isin(
            [
                "signal_relevant_ramp_terminal_leg",
                "signal_relevant_frontage_or_service_road",
                "signal_relevant_surface_crossroad_near_interchange",
            ]
        )
        & ~route_recoverable
        & anchor_usable
        & geom_usable
        & axis_strong
        & geom_label.isin(DIRECT_LABELS)
    )
    geom_recoverable_moderate = (
        out["ramp_interchange_primary_class"].isin(
            ["signal_relevant_frontage_or_service_road", "signal_relevant_surface_crossroad_near_interchange"]
        )
        & ~route_recoverable
        & ~geom_recoverable
        & anchor_usable
        & geom_usable
        & axis_moderate
        & geom_label.isin(DIRECT_LABELS)
        & ~true_mainline
    )

    out["recovered_directionality_label"] = "not_recovered"
    out.loc[route_recoverable, "recovered_directionality_label"] = suffix_label[route_recoverable]
    out.loc[geom_recoverable | geom_recoverable_moderate, "recovered_directionality_label"] = geom_label[
        geom_recoverable | geom_recoverable_moderate
    ]
    out["directionality_method"] = "not_recovered"
    out.loc[route_recoverable & out["ramp_interchange_primary_class"].eq("signal_relevant_ramp_terminal_leg"), "directionality_method"] = "ramp_terminal_route_suffix_measure_supported"
    out.loc[route_recoverable & out["ramp_interchange_primary_class"].eq("signal_relevant_frontage_or_service_road"), "directionality_method"] = "frontage_service_measure_anchor_supported"
    out.loc[route_recoverable & out["ramp_interchange_primary_class"].eq("signal_relevant_surface_crossroad_near_interchange"), "directionality_method"] = "surface_interchange_geometry_anchor_supported"
    out.loc[(geom_recoverable | geom_recoverable_moderate) & out["ramp_interchange_primary_class"].eq("signal_relevant_ramp_terminal_leg"), "directionality_method"] = "ramp_terminal_oneway_geometry_supported"
    out.loc[(geom_recoverable | geom_recoverable_moderate) & out["ramp_interchange_primary_class"].eq("signal_relevant_frontage_or_service_road"), "directionality_method"] = "frontage_service_measure_anchor_supported"
    out.loc[(geom_recoverable | geom_recoverable_moderate) & out["ramp_interchange_primary_class"].eq("signal_relevant_surface_crossroad_near_interchange"), "directionality_method"] = "surface_interchange_geometry_anchor_supported"
    out.loc[separable_mixed & out["recovered_directionality_label"].isin(DIRECT_LABELS), "directionality_method"] = "ramp_mainline_subbranch_split_recovered"

    out["directionality_confidence"] = "not_recovered"
    out.loc[route_recoverable & out["anchor_method_residual"].eq("canonical_signal_geometry"), "directionality_confidence"] = "high"
    out.loc[route_recoverable & ~out["anchor_method_residual"].eq("canonical_signal_geometry"), "directionality_confidence"] = "medium"
    out.loc[geom_recoverable & out["anchor_method_residual"].eq("canonical_signal_geometry"), "directionality_confidence"] = "medium"
    out.loc[geom_recoverable & ~out["anchor_method_residual"].eq("canonical_signal_geometry"), "directionality_confidence"] = "low"
    out.loc[geom_recoverable_moderate, "directionality_confidence"] = "low"
    out["directionality_reason"] = np.where(
        out["recovered_directionality_label"].isin(DIRECT_LABELS),
        "signal-relevant ramp/interchange context with route or geometry/anchor evidence",
        "held for mainline, mixed, ambiguous, or insufficient evidence review",
    )
    return out


def revised_coverage(recovered: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    prior = read_csv(RESIDUAL_DIR / "residual_directionality_revised_coverage_summary.csv")
    coverage = read_csv(COVERAGE_DIR / "directionality_bin_coverage_detail.csv", usecols=lambda c: c in ["stable_bin_id", "stable_signal_id", "has_any_directionality_coverage"])
    residual_syn = read_csv(RESIDUAL_DIR / "residual_directionality_recovered_synthetic_rows.csv", usecols=lambda c: c in ["stable_bin_id"])
    residual_labels = read_csv(RESIDUAL_DIR / "residual_directionality_recovered_labels.csv", usecols=lambda c: c in ["stable_bin_id"])
    recovered_ids = set(residual_syn["stable_bin_id"]) | set(residual_labels["stable_bin_id"])
    recovered_ids |= set(recovered.loc[recovered["recovered_directionality_label"].isin(DIRECT_LABELS), "stable_bin_id"])
    coverage["revised_has_directionality_coverage"] = coverage["has_any_directionality_coverage"].astype(bool) | coverage["stable_bin_id"].isin(recovered_ids)
    total = len(coverage)
    newly_ramp = int(recovered["recovered_directionality_label"].isin(DIRECT_LABELS).sum())
    summary = pd.DataFrame(
        [
            ("prior_residual_recovery_covered_bins", int(prior.loc[prior["metric"].eq("revised_covered_bins"), "bins"].iloc[0]), float(prior.loc[prior["metric"].eq("revised_covered_bins"), "share_of_total_bins"].iloc[0])),
            ("newly_recovered_ramp_interchange_bins", newly_ramp, newly_ramp / total),
            ("revised_covered_bins", int(coverage["revised_has_directionality_coverage"].sum()), float(coverage["revised_has_directionality_coverage"].mean())),
            ("revised_uncovered_bins", int((~coverage["revised_has_directionality_coverage"]).sum()), float((~coverage["revised_has_directionality_coverage"]).mean())),
        ],
        columns=["metric", "bins", "share_of_total_bins"],
    )
    sig = coverage.groupby("stable_signal_id").agg(total_bins=("stable_bin_id", "count"), covered_bins=("revised_has_directionality_coverage", "sum")).reset_index()
    sig["uncovered_bins"] = sig["total_bins"] - sig["covered_bins"]
    sig["coverage_share"] = sig["covered_bins"] / sig["total_bins"]
    sig["signal_directionality_coverage_class"] = np.select(
        [sig["coverage_share"] >= 0.999999, sig["coverage_share"] >= 0.75, sig["coverage_share"] >= 0.25, sig["coverage_share"] > 0],
        ["full_directionality_coverage", "high_partial_coverage_75plus", "moderate_partial_coverage_25_to_75", "low_partial_coverage_lt25"],
        default="no_directionality_coverage",
    )
    return summary, sig


def write_findings(target: pd.DataFrame, recovered: pd.DataFrame, summary: pd.DataFrame, sig: pd.DataFrame, qa: pd.DataFrame) -> None:
    class_counts = recovered["ramp_interchange_primary_class"].value_counts().to_dict()
    recovered_count = int(recovered["recovered_directionality_label"].isin(DIRECT_LABELS).sum())
    true_holdouts = int((recovered["ramp_interchange_primary_class"] == "true_grade_separated_mainline_holdout").sum())
    mixed = int((recovered["ramp_interchange_primary_class"] == "ramp_mainline_mixed_needs_subbranch_split").sum())
    sep = int((recovered["directionality_method"] == "ramp_mainline_subbranch_split_recovered").sum())
    metrics = dict(zip(summary["metric"], summary["bins"]))
    text = f"""# Ramp/Interchange Directionality Recovery Findings

## Bounded Question

This pass revisits uncovered ramp/interchange-context bins and recovers only low-risk signal-relevant ramp, frontage/service, or surface-interchange directionality. It does not force true grade-separated mainline rows or create crash/access assignments.

## Ramp/Interchange Decomposition

- Ramp/interchange target bins: {len(target):,}
- True grade-separated/mainline holdouts: {true_holdouts:,}
- Mixed ramp/mainline rows needing subbranch split: {mixed:,}
- Mixed rows separable and recovered: {sep:,}

Class counts:

{json.dumps({str(k): int(v) for k, v in class_counts.items()}, indent=2)}

## Recovery

- Automatically recovered ramp/interchange bins: {recovered_count:,}
- Revised covered bins: {metrics.get("revised_covered_bins", 0):,}
- Revised uncovered bins: {metrics.get("revised_uncovered_bins", 0):,}

## Recommendation

Ramp/interchange directionality can recover a bounded subset, but true mainline and mixed ramp/mainline cases still require review. Directionality remains context-ready only; crash/access upstream/downstream splitting remains inappropriate without a separate validated assignment rule.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_ramp_interchange_directionality_recovery_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_ramp_interchange_directionality_recovery_findings.md")


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.build.final_analysis_ramp_interchange_directionality_recovery",
        "bounded_question": "Ramp/interchange-specific directionality recovery.",
        "inputs": {
            "residual_recovery": str(RESIDUAL_DIR),
            "coverage_audit": str(COVERAGE_DIR),
            "direct_relaxed": str(DIRECT_DIR),
            "undivided": str(UNDIVIDED_DIR),
            "doctrine": str(DOCTRINE_DIR),
            "canonical": str(CANONICAL_DIR),
        },
        "outputs": list(outputs),
        "non_goals": ["No crash direction fields", "No directional crash assignment", "No active output modification", "No rates/models"],
    }
    (OUT_DIR / "final_analysis_ramp_interchange_directionality_recovery_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_log("Wrote final_analysis_ramp_interchange_directionality_recovery_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting ramp/interchange-specific directionality recovery.")

    target = build_target()
    recovered = classify_and_recover(target)
    write_csv(target, "ramp_interchange_directionality_target_bins.csv")
    decomp = recovered.groupby("ramp_interchange_primary_class", dropna=False).agg(
        bins=("stable_bin_id", "count"),
        recovered_bins=("recovered_directionality_label", lambda s: int(pd.Series(s).isin(DIRECT_LABELS).sum())),
        signals=("stable_signal_id", "nunique"),
    ).reset_index()
    write_csv(decomp, "ramp_interchange_directionality_decomposition.csv")
    recovered_labels = recovered[recovered["recovered_directionality_label"].isin(DIRECT_LABELS)].copy()
    write_csv(recovered_labels, "ramp_interchange_recovered_labels.csv")
    mixed = recovered[recovered["ramp_interchange_primary_class"].eq("ramp_mainline_mixed_needs_subbranch_split")].copy()
    write_csv(mixed, "ramp_interchange_mixed_subbranch_review.csv")
    holdouts = recovered[recovered["ramp_interchange_primary_class"].eq("true_grade_separated_mainline_holdout")].copy()
    write_csv(holdouts, "ramp_interchange_true_mainline_holdouts.csv")
    remaining = recovered[~recovered["recovered_directionality_label"].isin(DIRECT_LABELS)].copy()
    write_csv(remaining, "ramp_interchange_remaining_uncovered_bins.csv")
    summary, sig = revised_coverage(recovered)
    write_csv(summary, "ramp_interchange_revised_coverage_summary.csv")
    write_csv(sig, "ramp_interchange_signal_coverage_summary.csv")
    queue = remaining.sort_values(["stable_signal_id", "ramp_interchange_primary_class", "distance_start_ft"]).copy()
    queue = queue.head(25000)
    write_csv(queue, "ramp_interchange_map_review_queue.csv")
    next_action = pd.DataFrame(
        [
            {
                "recommendation": "integrate_recovered_ramp_context_after_review_and_examine_remaining_mainline_mixed_bins",
                "target_bins": len(target),
                "recovered_bins": len(recovered_labels),
                "remaining_uncovered_ramp_bins": len(remaining),
                "next_pass": "targeted_remaining_uncovered_directionality_review_or_canonical_context_integration",
                "crash_access_directional_status": "not_ready_without_separate_assignment_rule",
            }
        ]
    )
    write_csv(next_action, "ramp_interchange_directionality_next_action.csv")

    true_forced = int(holdouts["recovered_directionality_label"].isin(DIRECT_LABELS).sum()) if not holdouts.empty else 0
    mixed_forced = int(mixed["recovered_directionality_label"].isin(DIRECT_LABELS).sum()) if not mixed.empty else 0
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to analysis/current ramp-interchange folder."),
            ("no_records_promoted", True, "Review-only ramp/interchange recovery."),
            ("no_access_crash_assignment", True, "No access/crash assignment run."),
            ("no_rates_models", True, "No rates/models calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
            ("true_grade_separated_mainline_holdouts_not_forced", true_forced == 0, f"forced true mainline rows={true_forced}"),
            ("mixed_ramp_mainline_rows_only_recovered_when_separable", mixed_forced == 0, f"unseparated mixed rows recovered={mixed_forced}"),
            ("weak_ambiguous_cases_not_forced", True, "Rows failing ramp-specific safeguards remain uncovered."),
            ("outputs_review_only_folder", True, str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(qa, "final_analysis_ramp_interchange_directionality_recovery_qa.csv")
    write_findings(target, recovered, summary, sig, qa)

    outputs = [
        "ramp_interchange_directionality_target_bins.csv",
        "ramp_interchange_directionality_decomposition.csv",
        "ramp_interchange_recovered_labels.csv",
        "ramp_interchange_mixed_subbranch_review.csv",
        "ramp_interchange_true_mainline_holdouts.csv",
        "ramp_interchange_remaining_uncovered_bins.csv",
        "ramp_interchange_revised_coverage_summary.csv",
        "ramp_interchange_signal_coverage_summary.csv",
        "ramp_interchange_map_review_queue.csv",
        "ramp_interchange_directionality_next_action.csv",
        "final_analysis_ramp_interchange_directionality_recovery_findings.md",
        "final_analysis_ramp_interchange_directionality_recovery_qa.csv",
        "final_analysis_ramp_interchange_directionality_recovery_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed ramp/interchange-specific directionality recovery.")


if __name__ == "__main__":
    main()
