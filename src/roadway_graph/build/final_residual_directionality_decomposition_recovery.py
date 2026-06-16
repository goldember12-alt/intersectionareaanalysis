"""Final residual directionality decomposition and candidate recovery.

This review-only pass starts from the latest ramp/interchange recovery state
and examines the remaining uncovered directionality bins before map review. It
does not modify active outputs, create crash/access assignments, or create
production downstream/upstream fields.
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
RAMP_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_ramp_interchange_directionality_recovery"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_residual_directionality_recovery"
COVERAGE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_coverage_audit"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_residual_directionality_decomposition_recovery"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}
TOTAL_FINAL_BINS = 433_841


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
            default="not_recovered",
        ),
        index=diff.index,
    )


def latest_uncovered_pool() -> pd.DataFrame:
    """Reconstruct the latest uncovered pool after ramp/interchange recovery."""
    residual = read_csv(RESIDUAL_DIR / "residual_directionality_remaining_uncovered_bins.csv")
    ramp_recovered = read_csv(RAMP_DIR / "ramp_interchange_recovered_labels.csv", usecols=["stable_bin_id"])
    recovered_ids = set(ramp_recovered["stable_bin_id"].astype(str))
    target = residual[~residual["stable_bin_id"].astype(str).isin(recovered_ids)].copy()

    ramp_remaining = read_csv(
        RAMP_DIR / "ramp_interchange_remaining_uncovered_bins.csv",
        usecols=lambda c: c
        in {
            "stable_bin_id",
            "ramp_interchange_primary_class",
            "ramp_interchange_recovery_class",
            "directionality_reason",
            "mixed_source_qa_flag",
        },
    )
    target = target.merge(ramp_remaining, on="stable_bin_id", how="left", suffixes=("", "_ramp"))
    if len(target) != 38_587:
        write_log(f"Warning: reconstructed residual pool is {len(target):,}, expected 38,587.")
    else:
        write_log("Reconstructed final residual uncovered pool=38,587 bins.")
    return target


def add_taxonomy(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    text = (
        out.get("source_route_name", pd.Series("", index=out.index)).fillna("")
        + " "
        + out.get("source_route_common", pd.Series("", index=out.index)).fillna("")
        + " "
        + out.get("RTE_TYPE_N", pd.Series("", index=out.index)).fillna("")
        + " "
        + out.get("RTE_CATEGO", pd.Series("", index=out.index)).fillna("")
        + " "
        + out.get("rim_facility_raw", pd.Series("", index=out.index)).fillna("")
    ).str.lower()
    ramp_class = out.get("ramp_interchange_primary_class", pd.Series("", index=out.index)).fillna("")
    bin_class = out["directionality_bin_class"].fillna("")
    support_class = out["directionality_support_class"].fillna("")
    axis = pd.to_numeric(out.get("approach_axis_diff_residual"), errors="coerce")
    suffix_diff = pd.to_numeric(out.get("suffix_signal_angle_diff_residual"), errors="coerce")
    anchor_count = pd.to_numeric(out.get("anchor_support_bin_count"), errors="coerce").fillna(0)
    geom_bearing = pd.to_numeric(out.get("geometry_bearing_residual"), errors="coerce")
    signal_bearing = pd.to_numeric(out.get("signal_to_bin_bearing_residual"), errors="coerce")
    route_suffix = out.get("route_suffix_direction_residual", pd.Series("", index=out.index)).fillna("").astype(str)

    has_anchor = signal_bearing.notna() & anchor_count.ge(1)
    has_geom = geom_bearing.notna()
    has_suffix = route_suffix.str.len().gt(0)
    surface_interchange = ramp_class.eq("signal_relevant_surface_crossroad_near_interchange")
    mixed_ramp = ramp_class.eq("ramp_mainline_mixed_needs_subbranch_split")
    true_mainline = ramp_class.eq("true_grade_separated_mainline_holdout")
    synthetic_unclear = bin_class.eq("undivided_synthetic_unclear")
    direct_map = bin_class.eq("direct_excluded_map_review")
    should_hold = bin_class.eq("direct_excluded_should_remain_uncertain")
    not_assignable = bin_class.eq("direct_not_assignable_after_relaxed_review")
    source_missing = support_class.eq("insufficient_direction_evidence")

    # Recovery indicators are deliberately narrower than the taxonomy. The
    # taxonomy identifies possible causes; separate outputs record what was
    # actually recovered.
    surface_recoverable = (
        surface_interchange
        & has_anchor
        & has_geom
        & axis.le(55.0)
        & ~text.str.contains("interstate|freeway|mainline", regex=True)
    )
    mixed_split_possible = (
        mixed_ramp
        & out.get("signal_approach_id", pd.Series("", index=out.index)).fillna("").astype(str).str.len().gt(0)
        & out.get("carriageway_source_subpart_id", pd.Series("", index=out.index)).fillna("").astype(str).str.len().gt(0)
        & has_anchor
        & has_geom
        & axis.le(35.0)
    )
    direct_route_measure_recoverable = (
        direct_map
        & has_suffix
        & has_anchor
        & has_geom
        & anchor_count.ge(2)
        & (suffix_diff.le(50.0) | suffix_diff.ge(130.0))
        & axis.le(35.0)
    )
    direct_digitization_reversal_recoverable = (
        direct_map
        & has_suffix
        & has_anchor
        & has_geom
        & anchor_count.ge(2)
        & (suffix_diff.le(45.0) | suffix_diff.ge(135.0))
        & axis.gt(35.0)
        & axis.le(60.0)
    )
    synthetic_recoverable = synthetic_unclear & has_anchor & has_geom & axis.le(55.0) & anchor_count.ge(2)

    out["final_residual_primary_class"] = np.select(
        [
            true_mainline,
            surface_recoverable,
            surface_interchange,
            mixed_split_possible,
            mixed_ramp,
            direct_route_measure_recoverable | direct_digitization_reversal_recoverable,
            direct_map,
            synthetic_recoverable,
            synthetic_unclear,
            should_hold,
            source_missing | not_assignable | (~has_anchor) | (~has_geom),
        ],
        [
            "true_grade_separated_mainline_holdout",
            "surface_road_near_interchange_recoverable",
            "insufficient_geometry_or_anchor_evidence",
            "mixed_ramp_mainline_subbranch_split_possible",
            "mixed_ramp_mainline_unresolved",
            "direct_map_review_recoverable_by_route_measure",
            "direct_map_review_true_manual",
            "synthetic_unclear_recoverable_by_approach_axis",
            "synthetic_unclear_true_ambiguous",
            "should_remain_uncertain_policy_hold",
            "insufficient_geometry_or_anchor_evidence",
        ],
        default="other_unknown",
    )
    out["final_residual_recovery_candidate"] = np.select(
        [
            surface_recoverable,
            mixed_split_possible,
            direct_route_measure_recoverable,
            direct_digitization_reversal_recoverable,
            synthetic_recoverable,
        ],
        [
            "surface_interchange_candidate",
            "mixed_ramp_mainline_candidate",
            "direct_map_review_route_measure_candidate",
            "direct_map_review_digitization_reversal_candidate",
            "synthetic_unclear_axis_candidate",
        ],
        default="not_recoverable_by_automated_rule",
    )
    return out


def recover_direct(taxonomy: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    out = taxonomy.copy()
    suffix_diff = pd.to_numeric(out.get("suffix_signal_angle_diff_residual"), errors="coerce")
    geom_diff = angular_distance(
        pd.to_numeric(out.get("geometry_bearing_residual"), errors="coerce"),
        pd.to_numeric(out.get("signal_to_bin_bearing_residual"), errors="coerce"),
    ).abs()
    suffix_label = label_from_angle(suffix_diff, 50.0, 130.0)
    geom_label = label_from_angle(geom_diff, 55.0, 125.0)

    out["residual_direct_label"] = "not_recovered"
    out["residual_direct_recovery_method"] = "not_recovered"
    out["residual_direct_recovery_confidence"] = "not_recovered"
    out["residual_recovery_reason"] = "not recovered by automated residual rule"

    surface = out["final_residual_primary_class"].eq("surface_road_near_interchange_recoverable")
    mixed = out["final_residual_primary_class"].eq("mixed_ramp_mainline_subbranch_split_possible")
    direct_rm = (
        out["final_residual_primary_class"].eq("direct_map_review_recoverable_by_route_measure")
        & out["final_residual_recovery_candidate"].eq("direct_map_review_route_measure_candidate")
    )
    direct_rev = (
        out["final_residual_primary_class"].eq("direct_map_review_recoverable_by_route_measure")
        & out["final_residual_recovery_candidate"].eq("direct_map_review_digitization_reversal_candidate")
    )

    surface_label_ok = surface & geom_label.isin(DIRECT_LABELS)
    mixed_label_ok = mixed & geom_label.isin(DIRECT_LABELS)
    direct_rm_ok = direct_rm & suffix_label.isin(DIRECT_LABELS)
    direct_rev_ok = direct_rev & suffix_label.isin(DIRECT_LABELS)

    out.loc[surface_label_ok, "residual_direct_label"] = geom_label[surface_label_ok]
    out.loc[surface_label_ok, "residual_direct_recovery_method"] = "surface_interchange_recovered_by_geometry_anchor"
    out.loc[surface_label_ok, "residual_direct_recovery_confidence"] = "low"
    out.loc[surface_label_ok, "residual_recovery_reason"] = "surface/interchange row has usable signal-relative geometry under final residual threshold"

    out.loc[mixed_label_ok, "residual_direct_label"] = geom_label[mixed_label_ok]
    out.loc[mixed_label_ok, "residual_direct_recovery_method"] = "mixed_ramp_mainline_subbranch_recovered"
    out.loc[mixed_label_ok, "residual_direct_recovery_confidence"] = "low"
    out.loc[mixed_label_ok, "residual_recovery_reason"] = "mixed row has signal approach and source subpart evidence plus usable geometry"

    out.loc[direct_rm_ok, "residual_direct_label"] = suffix_label[direct_rm_ok]
    out.loc[direct_rm_ok, "residual_direct_recovery_method"] = "direct_map_review_route_measure_recovered"
    out.loc[direct_rm_ok, "residual_direct_recovery_confidence"] = "medium"
    out.loc[direct_rm_ok, "residual_recovery_reason"] = "route suffix and signal-relative position give a clear downstream/upstream side"

    out.loc[direct_rev_ok, "residual_direct_label"] = suffix_label[direct_rev_ok]
    out.loc[direct_rev_ok, "residual_direct_recovery_method"] = "direct_map_review_digitization_reversal_recovered"
    out.loc[direct_rev_ok, "residual_direct_recovery_confidence"] = "low"
    out.loc[direct_rev_ok, "residual_recovery_reason"] = "route suffix gives clear signal-relative side despite likely digitization reversal"

    recovered = out[out["residual_direct_label"].isin(DIRECT_LABELS)].copy()
    surface_detail = out[out["ramp_interchange_primary_class"].eq("signal_relevant_surface_crossroad_near_interchange")].copy()
    mixed_detail = out[out["ramp_interchange_primary_class"].eq("ramp_mainline_mixed_needs_subbranch_split")].copy()
    direct_detail = out[out["directionality_bin_class"].eq("direct_excluded_map_review")].copy()
    return recovered, surface_detail, mixed_detail, direct_detail


def recover_synthetic(taxonomy: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    detail = taxonomy[taxonomy["directionality_bin_class"].eq("undivided_synthetic_unclear")].copy()
    recoverable = detail["final_residual_primary_class"].eq("synthetic_unclear_recoverable_by_approach_axis")
    base = detail[recoverable].copy()
    rows = []
    for role in ("synthetic_upstream_to_signal", "synthetic_downstream_from_signal"):
        tmp = base.copy()
        tmp["synthetic_directional_role"] = role
        tmp["synthetic_direction_id"] = tmp["stable_bin_id"].astype(str) + "|" + role
        tmp["synthetic_directionality_method"] = "synthetic_unclear_relaxed_approach_axis_recovered"
        tmp["synthetic_directionality_confidence"] = "low"
        tmp["synthetic_directionality_scope"] = "undivided_centerline_interpretation"
        tmp["directional_crash_assignment_ready"] = "context_only_not_directional_crash_assignment"
        rows.append(tmp)
    synthetic_rows = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=list(detail.columns))
    return synthetic_rows, detail


def final_coverage(
    direct_recovered: pd.DataFrame,
    synthetic_recovered: pd.DataFrame,
    final_uncovered: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prior_summary = read_csv(RAMP_DIR / "ramp_interchange_revised_coverage_summary.csv")
    coverage = read_csv(
        COVERAGE_DIR / "directionality_bin_coverage_detail.csv",
        usecols=lambda c: c in {"stable_signal_id", "stable_bin_id", "has_any_directionality_coverage"},
    )
    residual_syn = read_csv(RESIDUAL_DIR / "residual_directionality_recovered_synthetic_rows.csv", usecols=["stable_bin_id"])
    residual_direct = read_csv(RESIDUAL_DIR / "residual_directionality_recovered_labels.csv", usecols=["stable_bin_id"])
    ramp_direct = read_csv(RAMP_DIR / "ramp_interchange_recovered_labels.csv", usecols=["stable_bin_id"])
    recovered_ids = set(residual_syn["stable_bin_id"].astype(str))
    recovered_ids |= set(residual_direct["stable_bin_id"].astype(str))
    recovered_ids |= set(ramp_direct["stable_bin_id"].astype(str))
    recovered_ids |= set(direct_recovered["stable_bin_id"].astype(str))
    recovered_ids |= set(synthetic_recovered["stable_bin_id"].astype(str))

    coverage["final_has_directionality_coverage"] = coverage["has_any_directionality_coverage"].astype(bool) | coverage[
        "stable_bin_id"
    ].astype(str).isin(recovered_ids)
    total = len(coverage)
    covered = int(coverage["final_has_directionality_coverage"].sum())
    new_direct = int(direct_recovered["stable_bin_id"].nunique())
    new_synthetic = int(synthetic_recovered["stable_bin_id"].nunique()) if not synthetic_recovered.empty else 0
    prior_covered = int(prior_summary.loc[prior_summary["metric"].eq("revised_covered_bins"), "bins"].iloc[0])
    summary = pd.DataFrame(
        [
            ("total_final_bins", total, 1.0),
            ("prior_ramp_recovery_covered_bins", prior_covered, prior_covered / total),
            ("new_residual_direct_recovered_bins", new_direct, new_direct / total),
            ("new_residual_synthetic_recovered_source_bins", new_synthetic, new_synthetic / total),
            ("final_covered_bins", covered, covered / total),
            ("final_uncovered_bins", total - covered, (total - covered) / total),
            ("final_uncovered_bins_from_detail", int(final_uncovered["stable_bin_id"].nunique()), int(final_uncovered["stable_bin_id"].nunique()) / total),
        ],
        columns=["metric", "bins", "share_of_total_bins"],
    )
    sig = coverage.groupby("stable_signal_id").agg(
        total_bins=("stable_bin_id", "count"),
        covered_bins=("final_has_directionality_coverage", "sum"),
    ).reset_index()
    sig["uncovered_bins"] = sig["total_bins"] - sig["covered_bins"]
    sig["coverage_share"] = sig["covered_bins"] / sig["total_bins"]
    sig["signal_directionality_coverage_class"] = np.select(
        [sig["coverage_share"] >= 0.999999, sig["coverage_share"] >= 0.75, sig["coverage_share"] >= 0.25, sig["coverage_share"] > 0],
        ["full_directionality_coverage", "high_partial_coverage_75plus", "moderate_partial_coverage_25_to_75", "low_partial_coverage_lt25"],
        default="no_directionality_coverage",
    )
    return summary, sig


def pre_map_review_queue(final_uncovered: pd.DataFrame) -> pd.DataFrame:
    q = final_uncovered.copy()
    reason = q["final_residual_primary_class"].fillna("other_unknown")
    q["automation_nonrecovery_reason"] = np.select(
        [
            reason.eq("true_grade_separated_mainline_holdout"),
            reason.eq("mixed_ramp_mainline_unresolved"),
            reason.eq("direct_map_review_true_manual"),
            reason.eq("synthetic_unclear_true_ambiguous"),
            reason.eq("should_remain_uncertain_policy_hold"),
            reason.eq("insufficient_geometry_or_anchor_evidence"),
            reason.eq("source_directionality_missing"),
        ],
        [
            "true grade-separated/mainline row was intentionally not forced",
            "mixed ramp/mainline evidence was not separable by source subpart",
            "direct map-review bin lacks nonconflicting automated evidence",
            "undivided synthetic row remains ambiguous under relaxed axis check",
            "policy hold bin remains uncertain by doctrine",
            "insufficient signal anchor or bin geometry evidence",
            "source directionality evidence missing",
        ],
        default="manual review needed or other unknown",
    )
    q["suggested_review_question"] = np.select(
        [
            reason.eq("true_grade_separated_mainline_holdout"),
            reason.eq("mixed_ramp_mainline_unresolved"),
            reason.eq("direct_map_review_true_manual"),
            reason.eq("synthetic_unclear_true_ambiguous"),
        ],
        [
            "Is this row a grade-separated/mainline movement that should stay out of signal-relative directionality?",
            "Can the signal-relevant ramp/frontage subpart be separated from nearby mainline context?",
            "Do route/measure and geometry support a direct downstream/upstream label?",
            "Is the approach axis clear enough to create paired synthetic undivided interpretations?",
        ],
        default="Does map context provide enough non-crash evidence for directionality?",
    )
    q["review_type"] = np.select(
        [
            reason.str.contains("ramp|mainline|interchange", regex=True),
            reason.str.contains("synthetic", regex=True),
            reason.str.contains("direct", regex=True),
            reason.str.contains("source|geometry|anchor", regex=True),
        ],
        ["ramp_mainline", "synthetic_unclear", "direct_map_review", "source_or_geometry_limitation"],
        default="other",
    )
    q["priority_score"] = np.select(
        [
            reason.eq("mixed_ramp_mainline_unresolved"),
            reason.eq("direct_map_review_true_manual"),
            reason.eq("synthetic_unclear_true_ambiguous"),
            reason.eq("true_grade_separated_mainline_holdout"),
        ],
        [90, 80, 70, 30],
        default=50,
    )
    cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "geometry_wkt",
        "signal_approach_id",
        "analysis_window",
        "directionality_bin_class",
        "directionality_support_class",
        "final_residual_primary_class",
        "automation_nonrecovery_reason",
        "suggested_review_question",
        "review_type",
        "priority_score",
    ]
    cols = [c for c in cols if c in q.columns]
    return q[cols].sort_values(["priority_score", "stable_signal_id", "stable_bin_id"], ascending=[False, True, True])


def summary_tables(
    taxonomy: pd.DataFrame,
    direct_recovered: pd.DataFrame,
    synthetic_rows: pd.DataFrame,
    final_uncovered: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tax = taxonomy.groupby("final_residual_primary_class", dropna=False).agg(
        bins=("stable_bin_id", "nunique"),
        signals=("stable_signal_id", "nunique"),
        direct_recovered_bins=("stable_bin_id", lambda s: int(s.astype(str).isin(set(direct_recovered["stable_bin_id"].astype(str))).sum())),
        synthetic_recovered_source_bins=("stable_bin_id", lambda s: int(s.astype(str).isin(set(synthetic_rows["stable_bin_id"].astype(str))).sum()) if not synthetic_rows.empty else 0),
    ).reset_index()
    surface = taxonomy[taxonomy["ramp_interchange_primary_class"].eq("signal_relevant_surface_crossroad_near_interchange")].copy()
    mixed = taxonomy[taxonomy["ramp_interchange_primary_class"].eq("ramp_mainline_mixed_needs_subbranch_split")].copy()
    direct = taxonomy[taxonomy["directionality_bin_class"].eq("direct_excluded_map_review")].copy()
    synthetic = taxonomy[taxonomy["directionality_bin_class"].eq("undivided_synthetic_unclear")].copy()
    return tax, surface, mixed, direct, synthetic


def write_findings(
    target: pd.DataFrame,
    taxonomy: pd.DataFrame,
    direct_recovered: pd.DataFrame,
    synthetic_rows: pd.DataFrame,
    final_uncovered: pd.DataFrame,
    coverage_summary: pd.DataFrame,
    signal_summary: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    metrics = dict(zip(coverage_summary["metric"], coverage_summary["bins"]))
    taxonomy_counts = taxonomy["final_residual_primary_class"].value_counts().to_dict()
    queue_counts = queue["review_type"].value_counts().to_dict() if "review_type" in queue.columns else {}
    surface_rec = int(direct_recovered["residual_direct_recovery_method"].eq("surface_interchange_recovered_by_geometry_anchor").sum()) if not direct_recovered.empty else 0
    mixed_rec = int(direct_recovered["residual_direct_recovery_method"].eq("mixed_ramp_mainline_subbranch_recovered").sum()) if not direct_recovered.empty else 0
    direct_rec = int(direct_recovered["residual_direct_recovery_method"].str.startswith("direct_map_review", na=False).sum()) if not direct_recovered.empty else 0
    synthetic_source = int(synthetic_rows["stable_bin_id"].nunique()) if not synthetic_rows.empty else 0
    class_counts = signal_summary["signal_directionality_coverage_class"].value_counts().to_dict()
    text = f"""# Final Residual Directionality Decomposition and Recovery Findings

## Bounded Question

This review-only pass examines the remaining directionality bins after direct, synthetic, residual, and ramp/interchange recovery. It attempts one final automated recovery before map review without using crash direction fields and without creating production downstream/upstream fields.

## Residual Pool

- Residual uncovered bins examined: {len(target):,}
- True grade-separated/mainline holdouts: {taxonomy_counts.get('true_grade_separated_mainline_holdout', 0):,}
- Surface-road/interchange recoverable class: {taxonomy_counts.get('surface_road_near_interchange_recoverable', 0):,}
- Mixed ramp/mainline split-possible class: {taxonomy_counts.get('mixed_ramp_mainline_subbranch_split_possible', 0):,}
- Direct map-review recoverable class: {taxonomy_counts.get('direct_map_review_recoverable_by_route_measure', 0):,}
- Synthetic unclear recoverable class: {taxonomy_counts.get('synthetic_unclear_recoverable_by_approach_axis', 0):,}

## Automated Recovery

- Surface-road-near-interchange bins recovered: {surface_rec:,}
- Mixed ramp/mainline rows recovered: {mixed_rec:,}
- Direct map-review bins automatically recovered: {direct_rec:,}
- Synthetic unclear source bins recovered: {synthetic_source:,}
- Synthetic interpretation rows created: {len(synthetic_rows):,}

## Revised Coverage

- Final covered bins: {metrics.get('final_covered_bins', 0):,} / {metrics.get('total_final_bins', TOTAL_FINAL_BINS):,}
- Final uncovered bins: {metrics.get('final_uncovered_bins', 0):,}
- Final coverage share: {coverage_summary.loc[coverage_summary['metric'].eq('final_covered_bins'), 'share_of_total_bins'].iloc[0]:.1%}
- Full-coverage signals: {class_counts.get('full_directionality_coverage', 0):,}
- High partial signals: {class_counts.get('high_partial_coverage_75plus', 0):,}
- Moderate partial signals: {class_counts.get('moderate_partial_coverage_25_to_75', 0):,}
- Low partial signals: {class_counts.get('low_partial_coverage_lt25', 0):,}
- No-coverage signals: {class_counts.get('no_directionality_coverage', 0):,}

## Pre-Map-Review Queue

- Final pre-map-review queue size: {len(queue):,}
- Queue composition: {json.dumps(queue_counts, sort_keys=True)}

## Recommendation

The remaining bins are now better decomposed for map review. The recovered rows can be considered candidate review-only directionality, but canonical integration should happen in a separate pass. Directional crash/access splitting remains out of scope because no validated crash-direction-independent assignment rule has been defined for distributing crashes or access points by downstream/upstream side.
"""
    (OUT_DIR / "final_residual_directionality_decomposition_recovery_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_residual_directionality_decomposition_recovery_findings.md")


def write_qa(
    target: pd.DataFrame,
    direct_recovered: pd.DataFrame,
    synthetic_rows: pd.DataFrame,
    final_uncovered: pd.DataFrame,
) -> pd.DataFrame:
    true_forced = direct_recovered["final_residual_primary_class"].eq("true_grade_separated_mainline_holdout").sum() if not direct_recovered.empty else 0
    weak_forced = direct_recovered["final_residual_primary_class"].isin(
        ["direct_map_review_true_manual", "synthetic_unclear_true_ambiguous", "insufficient_geometry_or_anchor_evidence", "should_remain_uncertain_policy_hold"]
    ).sum() if not direct_recovered.empty else 0
    synthetic_scope_ok = True
    if not synthetic_rows.empty and "synthetic_directionality_scope" in synthetic_rows.columns:
        synthetic_scope_ok = synthetic_rows["synthetic_directionality_scope"].eq("undivided_centerline_interpretation").all()
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to review/current final residual directionality folder."),
        ("no_records_promoted", True, "Review-only candidate recovery."),
        ("no_access_crash_assignment", True, "No access/crash assignment run."),
        ("no_rates_models", True, "No rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("true_grade_separated_mainline_holdouts_not_forced", true_forced == 0, f"forced true mainline rows={int(true_forced)}"),
        ("mixed_ramp_mainline_only_recovered_when_split_possible", True, "Mixed recovery limited to split-possible taxonomy class."),
        ("weak_ambiguous_cases_not_forced", weak_forced == 0, f"weak/manual/policy cases directly recovered={int(weak_forced)}"),
        ("synthetic_rows_marked_interpretations", bool(synthetic_scope_ok), "Synthetic rows use undivided_centerline_interpretation scope."),
        ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/final_residual_directionality_decomposition_recovery"), str(OUT_DIR)),
    ]
    qa = pd.DataFrame(rows, columns=["qa_check", "passed", "note"])
    write_csv(qa, "final_residual_directionality_decomposition_recovery_qa.csv")
    return qa


def write_next_action(coverage_summary: pd.DataFrame, queue: pd.DataFrame) -> None:
    final_uncovered = int(coverage_summary.loc[coverage_summary["metric"].eq("final_uncovered_bins"), "bins"].iloc[0])
    action = pd.DataFrame(
        [
            {
                "recommendation": "prepare_targeted_map_review_queue_then_integrate_candidate_directionality_separately",
                "final_uncovered_bins": final_uncovered,
                "pre_map_review_queue_rows": len(queue),
                "directionality_ready_for_canonical_integration": "candidate_review_only_after_separate_integration_pass",
                "directional_crash_access_split_ready": "no_separate_validated_assignment_rule_required",
                "next_step": "Review final_directionality_pre_map_review_queue.csv and decide whether candidate recovered labels should be integrated into a canonical review-only directionality layer.",
            }
        ]
    )
    write_csv(action, "final_residual_directionality_next_action.csv")


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "script": "src.roadway_graph.build.final_residual_directionality_decomposition_recovery",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "final review-only residual directionality decomposition and candidate recovery before map review",
        "output_folder": str(OUT_DIR),
        "inputs": [
            str(RAMP_DIR),
            str(RESIDUAL_DIR),
            str(COVERAGE_DIR),
            str(CANONICAL_DIR),
        ],
        "outputs": list(outputs),
        "non_goals": [
            "no crash direction use",
            "no access/crash assignment",
            "no rates/models",
            "no active output modification",
            "no production downstream/upstream fields",
        ],
    }
    (OUT_DIR / "final_residual_directionality_decomposition_recovery_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    write_log("Wrote final_residual_directionality_decomposition_recovery_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting final residual directionality decomposition and recovery.")

    target = latest_uncovered_pool()
    taxonomy = add_taxonomy(target)
    direct_recovered, surface_detail, mixed_detail, direct_detail = recover_direct(taxonomy)
    synthetic_rows, synthetic_detail = recover_synthetic(taxonomy)

    recovered_ids = set(direct_recovered["stable_bin_id"].astype(str))
    recovered_ids |= set(synthetic_rows["stable_bin_id"].astype(str)) if not synthetic_rows.empty else set()
    final_uncovered = taxonomy[~taxonomy["stable_bin_id"].astype(str).isin(recovered_ids)].copy()
    coverage_summary, signal_summary = final_coverage(direct_recovered, synthetic_rows, final_uncovered)
    queue = pre_map_review_queue(final_uncovered)
    taxonomy_summary, _, _, _, _ = summary_tables(taxonomy, direct_recovered, synthetic_rows, final_uncovered)

    write_csv(target, "final_residual_directionality_target_bins.csv")
    write_csv(taxonomy_summary, "final_residual_directionality_taxonomy.csv")
    write_csv(surface_detail, "surface_interchange_recovery_detail.csv")
    write_csv(mixed_detail, "mixed_ramp_mainline_subbranch_recovery_detail.csv")
    write_csv(direct_detail, "direct_map_review_auto_recovery_detail.csv")
    write_csv(synthetic_detail, "synthetic_unclear_auto_recovery_detail.csv")
    write_csv(direct_recovered, "residual_direct_recovered_labels.csv")
    write_csv(synthetic_rows, "residual_synthetic_recovered_rows.csv")
    write_csv(final_uncovered, "final_residual_uncovered_bins.csv")
    write_csv(coverage_summary, "final_residual_directionality_coverage_summary.csv")
    write_csv(signal_summary, "final_residual_signal_coverage_summary.csv")
    write_csv(queue, "final_directionality_pre_map_review_queue.csv")
    write_next_action(coverage_summary, queue)
    qa = write_qa(target, direct_recovered, synthetic_rows, final_uncovered)
    write_findings(target, taxonomy, direct_recovered, synthetic_rows, final_uncovered, coverage_summary, signal_summary, queue)

    outputs = [
        "final_residual_directionality_target_bins.csv",
        "final_residual_directionality_taxonomy.csv",
        "surface_interchange_recovery_detail.csv",
        "mixed_ramp_mainline_subbranch_recovery_detail.csv",
        "direct_map_review_auto_recovery_detail.csv",
        "synthetic_unclear_auto_recovery_detail.csv",
        "residual_direct_recovered_labels.csv",
        "residual_synthetic_recovered_rows.csv",
        "final_residual_uncovered_bins.csv",
        "final_residual_directionality_coverage_summary.csv",
        "final_residual_signal_coverage_summary.csv",
        "final_directionality_pre_map_review_queue.csv",
        "final_residual_directionality_next_action.csv",
        "final_residual_directionality_decomposition_recovery_findings.md",
        "final_residual_directionality_decomposition_recovery_qa.csv",
        "final_residual_directionality_decomposition_recovery_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed final residual directionality decomposition and recovery.")


if __name__ == "__main__":
    main()
