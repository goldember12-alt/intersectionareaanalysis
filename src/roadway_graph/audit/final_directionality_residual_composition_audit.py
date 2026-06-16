"""Final directionality residual composition audit.

This review-only audit decomposes the remaining residual directionality queue
before map review. It estimates possible future automated recovery classes but
does not assign new downstream/upstream labels.
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
FINAL_RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_residual_directionality_decomposition_recovery"
RAMP_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_ramp_interchange_directionality_recovery"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_residual_directionality_recovery"
COVERAGE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_coverage_audit"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_directionality_residual_composition_audit"

EXPECTED_RESIDUAL_BINS = 34_358


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


def bool_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return df[col].fillna("").astype(str).str.lower().isin({"true", "1", "yes"})


def numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def build_residual_pool() -> pd.DataFrame:
    residual = read_csv(FINAL_RESIDUAL_DIR / "final_residual_uncovered_bins.csv")
    queue = read_csv(FINAL_RESIDUAL_DIR / "final_directionality_pre_map_review_queue.csv")
    canonical_ids = set(read_csv(CANONICAL_DIR / "analysis_bin.csv", usecols=["stable_bin_id"])["stable_bin_id"].astype(str))
    covered = read_csv(COVERAGE_DIR / "directionality_bin_coverage_detail.csv", usecols=["stable_bin_id", "has_any_directionality_coverage"])
    initially_covered_ids = set(
        covered.loc[covered["has_any_directionality_coverage"].astype(bool), "stable_bin_id"].astype(str)
    )

    residual["stable_bin_id"] = residual["stable_bin_id"].astype(str)
    queue["stable_bin_id"] = queue["stable_bin_id"].astype(str)
    residual["maps_to_canonical_analysis_bin"] = residual["stable_bin_id"].isin(canonical_ids)
    residual["initially_covered_in_coverage_audit"] = residual["stable_bin_id"].isin(initially_covered_ids)
    queue_cols = [
        "stable_bin_id",
        "automation_nonrecovery_reason",
        "suggested_review_question",
        "review_type",
        "priority_score",
    ]
    queue_cols = [c for c in queue_cols if c in queue.columns]
    residual = residual.merge(queue[queue_cols], on="stable_bin_id", how="left", suffixes=("", "_queue"))
    if len(residual) != EXPECTED_RESIDUAL_BINS:
        write_log(f"Warning: residual pool is {len(residual):,}, expected {EXPECTED_RESIDUAL_BINS:,}.")
    else:
        write_log(f"Built exact residual pool={len(residual):,} bins.")
    return residual


def add_decomposition(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    primary = out["final_residual_primary_class"].fillna("")
    bin_class = out["directionality_bin_class"].fillna("")
    support = out["directionality_support_class"].fillna("")
    map_priority = out.get("map_review_priority", pd.Series("", index=out.index)).fillna("")
    ramp_class = out.get("ramp_interchange_primary_class", pd.Series("", index=out.index)).fillna("")
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
    suffix = out.get("route_suffix_direction_residual", pd.Series("", index=out.index)).fillna("").astype(str)
    suffix_diff = numeric(out, "suffix_signal_angle_diff_residual")
    axis = numeric(out, "approach_axis_diff_residual")
    anchor_count = numeric(out, "anchor_support_bin_count").fillna(0)
    geom_bearing = numeric(out, "geometry_bearing_residual")
    signal_bearing = numeric(out, "signal_to_bin_bearing_residual")
    start_measure = numeric(out, "source_measure_start")
    end_measure = numeric(out, "source_measure_end")

    has_suffix = suffix.str.len().gt(0)
    suffix_clear = suffix_diff.le(55) | suffix_diff.ge(125)
    suffix_borderline = (suffix_diff.gt(55) & suffix_diff.le(65)) | (suffix_diff.ge(115) & suffix_diff.lt(125))
    has_anchor = signal_bearing.notna() & anchor_count.ge(1)
    good_anchor = signal_bearing.notna() & anchor_count.ge(2)
    has_geom = geom_bearing.notna()
    route_measure_present = start_measure.notna() & end_measure.notna()
    route_measure_missing = ~route_measure_present
    stable_tw_missing = out.get("stable_travelway_id", pd.Series("", index=out.index)).fillna("").astype(str).str.len().eq(0)
    source_geometry_missing = out.get("geometry_wkt", pd.Series("", index=out.index)).fillna("").astype(str).str.len().eq(0)
    signal_anchor_missing = ~has_anchor
    likely_mainline = text.str.contains("interstate|freeway|mainline", regex=True)
    frontage_service = text.str.contains("frontage|service|collector|dist/coll|cd road", regex=True)
    ramp_coded = out.get("RTE_RAMP_C", pd.Series("", index=out.index)).fillna("").astype(str).str.strip().ne("")
    one_way = out.get("rim_facility_raw", pd.Series("", index=out.index)).fillna("").str.contains("One-Way", case=False, regex=False)

    out["residual_subclass"] = "true_manual_review"

    other_mask = out.get("review_type", pd.Series("", index=out.index)).fillna("").eq("other")
    out.loc[other_mask & primary.eq("should_remain_uncertain_policy_hold"), "residual_subclass"] = "explicit_policy_hold"
    out.loc[other_mask & signal_anchor_missing, "residual_subclass"] = "insufficient_anchor_evidence"
    out.loc[other_mask & route_measure_missing & ~signal_anchor_missing, "residual_subclass"] = "insufficient_route_measure_evidence"
    out.loc[other_mask & has_suffix & ~suffix_clear & ~suffix_borderline, "residual_subclass"] = "geometry_or_suffix_conflict"
    out.loc[other_mask & support.eq("insufficient_direction_evidence"), "residual_subclass"] = "unsupported_facility_or_context"
    out.loc[other_mask & bin_class.eq("direct_excluded_should_remain_uncertain") & suffix_borderline, "residual_subclass"] = "previously_excluded_by_conservative_rule"
    out.loc[other_mask & has_suffix & suffix_clear & good_anchor & has_geom, "residual_subclass"] = "possible_recoverable_with_stronger_route_measure_rule"
    out.loc[other_mask & primary.eq("other_unknown"), "residual_subclass"] = "unknown_due_to_missing_fields"

    direct_mask = out.get("review_type", pd.Series("", index=out.index)).fillna("").eq("direct_map_review")
    out.loc[direct_mask & has_suffix & suffix_clear & route_measure_present & good_anchor, "residual_subclass"] = "route_measure_evidence_strong_candidate"
    out.loc[direct_mask & has_suffix & suffix_clear & route_measure_present & good_anchor & axis.gt(35), "residual_subclass"] = "likely_source_digitization_reversal"
    out.loc[direct_mask & has_suffix & suffix_borderline, "residual_subclass"] = "route_suffix_measure_borderline"
    out.loc[direct_mask & signal_anchor_missing, "residual_subclass"] = "anchor_evidence_weak"
    out.loc[direct_mask & has_suffix & ~suffix_clear & ~suffix_borderline, "residual_subclass"] = "geometry_evidence_conflicts"
    out.loc[direct_mask & primary.eq("direct_map_review_true_manual"), "residual_subclass"] = np.where(
        out.loc[direct_mask & primary.eq("direct_map_review_true_manual"), "residual_subclass"].eq("true_manual_review"),
        "true_manual_review",
        out.loc[direct_mask & primary.eq("direct_map_review_true_manual"), "residual_subclass"],
    )

    ramp_mask = out.get("review_type", pd.Series("", index=out.index)).fillna("").eq("ramp_mainline")
    out.loc[ramp_mask & primary.eq("true_grade_separated_mainline_holdout"), "residual_subclass"] = "true_grade_separated_freeway_mainline_holdout"
    out.loc[ramp_mask & ramp_class.eq("signal_relevant_ramp_terminal_leg"), "residual_subclass"] = "signal_relevant_ramp_terminal_leg_remaining"
    out.loc[ramp_mask & frontage_service, "residual_subclass"] = "signal_relevant_frontage_or_service_road_remaining"
    out.loc[ramp_mask & ramp_class.eq("signal_relevant_surface_crossroad_near_interchange"), "residual_subclass"] = "signal_relevant_surface_crossroad_near_interchange_remaining"
    out.loc[ramp_mask & primary.eq("mixed_ramp_mainline_unresolved") & out.get("signal_approach_id", pd.Series("", index=out.index)).fillna("").astype(str).str.len().gt(0) & out.get("carriageway_source_subpart_id", pd.Series("", index=out.index)).fillna("").astype(str).str.len().gt(0), "residual_subclass"] = "mixed_ramp_mainline_separable_possible"
    out.loc[ramp_mask & primary.eq("mixed_ramp_mainline_unresolved") & out["residual_subclass"].eq("true_manual_review"), "residual_subclass"] = "mixed_ramp_mainline_not_separable"
    out.loc[ramp_mask & (signal_anchor_missing | ~has_geom) & ~primary.eq("true_grade_separated_mainline_holdout"), "residual_subclass"] = "insufficient_ramp_direction_evidence"
    out.loc[ramp_mask & likely_mainline & primary.eq("true_grade_separated_mainline_holdout"), "residual_subclass"] = "true_grade_separated_freeway_mainline_holdout"
    out.loc[ramp_mask & ramp_coded & one_way & ~likely_mainline & good_anchor & has_geom & out["residual_subclass"].eq("true_manual_review"), "residual_subclass"] = "signal_relevant_ramp_terminal_leg_remaining"

    synthetic_mask = out.get("review_type", pd.Series("", index=out.index)).fillna("").eq("synthetic_unclear")
    out.loc[synthetic_mask & good_anchor & has_geom & axis.le(65), "residual_subclass"] = "recoverable_with_approach_level_grouping"
    out.loc[synthetic_mask & has_anchor & has_geom & axis.gt(65) & axis.le(75), "residual_subclass"] = "recoverable_with_relaxed_approach_axis_threshold"
    out.loc[synthetic_mask & signal_anchor_missing, "residual_subclass"] = "insufficient_anchor_evidence"
    out.loc[synthetic_mask & has_anchor & axis.gt(75), "residual_subclass"] = "nearby_intersection_or_axis_ambiguity"
    out.loc[synthetic_mask & primary.eq("synthetic_unclear_true_ambiguous") & out["residual_subclass"].eq("true_manual_review"), "residual_subclass"] = "true_bidirectional_undirected_hold"

    source_mask = out.get("review_type", pd.Series("", index=out.index)).fillna("").eq("source_or_geometry_limitation")
    out.loc[source_mask & source_geometry_missing, "residual_subclass"] = "source_geometry_missing"
    out.loc[source_mask & route_measure_missing & ~source_geometry_missing, "residual_subclass"] = "route_measure_missing"
    out.loc[source_mask & stable_tw_missing, "residual_subclass"] = "stable_travelway_id_missing"
    out.loc[source_mask & signal_anchor_missing & ~source_geometry_missing, "residual_subclass"] = "signal_anchor_missing"
    out.loc[source_mask & support.eq("insufficient_direction_evidence"), "residual_subclass"] = "source_row_not_direction_supporting"
    out.loc[source_mask & has_suffix & route_measure_present & has_geom & ~signal_anchor_missing, "residual_subclass"] = "likely_recoverable_with_alternate_source_field"
    out.loc[source_mask & out["residual_subclass"].eq("true_manual_review"), "residual_subclass"] = "true_source_limitation"

    automatable = out["residual_subclass"].isin(
        {
            "route_measure_evidence_strong_candidate",
            "likely_source_digitization_reversal",
            "possible_recoverable_with_stronger_route_measure_rule",
        }
    )
    rule_design = out["residual_subclass"].isin(
        {
            "previously_excluded_by_conservative_rule",
            "route_suffix_measure_borderline",
            "signal_relevant_ramp_terminal_leg_remaining",
            "signal_relevant_frontage_or_service_road_remaining",
            "signal_relevant_surface_crossroad_near_interchange_remaining",
            "mixed_ramp_mainline_separable_possible",
            "recoverable_with_approach_level_grouping",
            "recoverable_with_relaxed_approach_axis_threshold",
            "likely_recoverable_with_alternate_source_field",
        }
    )
    true_holdout = out["residual_subclass"].isin(
        {
            "true_grade_separated_freeway_mainline_holdout",
            "explicit_policy_hold",
            "true_bidirectional_undirected_hold",
        }
    )
    source_limitation = out["residual_subclass"].isin(
        {
            "source_geometry_missing",
            "route_measure_missing",
            "stable_travelway_id_missing",
            "signal_anchor_missing",
            "source_row_not_direction_supporting",
            "true_source_limitation",
            "insufficient_anchor_evidence",
            "insufficient_route_measure_evidence",
            "insufficient_ramp_direction_evidence",
        }
    )
    unknown = out["residual_subclass"].isin({"unknown_due_to_missing_fields"})
    out["final_audit_recoverability_class"] = np.select(
        [automatable, rule_design, source_limitation, true_holdout, unknown],
        [
            "automatable_recovery_candidate",
            "needs_specific_rule_design",
            "true_source_or_geometry_limitation",
            "policy_hold_or_not_directionally_applicable",
            "unknown_needs_data_debug",
        ],
        default="map_review_candidate",
    )
    out.loc[out["residual_subclass"].eq("true_grade_separated_freeway_mainline_holdout"), "final_audit_recoverability_class"] = "true_grade_or_mainline_holdout"

    out["evidence_summary"] = (
        "subclass="
        + out["residual_subclass"].fillna("")
        + "; support="
        + support.astype(str)
        + "; axis_diff="
        + axis.round(1).astype(str)
        + "; suffix="
        + suffix.astype(str)
        + "; suffix_diff="
        + suffix_diff.round(1).astype(str)
        + "; anchor="
        + out.get("anchor_method_residual", pd.Series("", index=out.index)).fillna("").astype(str)
    )
    out["suggested_action"] = np.select(
        [
            out["final_audit_recoverability_class"].eq("automatable_recovery_candidate"),
            out["final_audit_recoverability_class"].eq("needs_specific_rule_design"),
            out["final_audit_recoverability_class"].eq("map_review_candidate"),
            out["final_audit_recoverability_class"].isin({"true_grade_or_mainline_holdout", "policy_hold_or_not_directionally_applicable"}),
            out["final_audit_recoverability_class"].eq("true_source_or_geometry_limitation"),
        ],
        [
            "candidate for a targeted automated recovery pass",
            "design a more specific non-crash directionality rule before recovery",
            "include in targeted map review",
            "carry as explicit holdout unless doctrine changes",
            "carry as source/geometry limitation or debug missing fields",
        ],
        default="data debug",
    )
    out["map_review_required"] = out["final_audit_recoverability_class"].eq("map_review_candidate")
    out["audit_priority_score"] = np.select(
        [
            out["final_audit_recoverability_class"].eq("automatable_recovery_candidate"),
            out["final_audit_recoverability_class"].eq("needs_specific_rule_design"),
            out["final_audit_recoverability_class"].eq("map_review_candidate"),
            out["final_audit_recoverability_class"].eq("unknown_needs_data_debug"),
        ],
        [95, 85, 75, 65],
        default=35,
    )
    return out


def group_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return df.groupby(group_cols, dropna=False).agg(
        bins=("stable_bin_id", "nunique"),
        signals=("stable_signal_id", "nunique"),
        automatable=("final_audit_recoverability_class", lambda s: int((s == "automatable_recovery_candidate").sum())),
        rule_design=("final_audit_recoverability_class", lambda s: int((s == "needs_specific_rule_design").sum())),
        map_review=("final_audit_recoverability_class", lambda s: int((s == "map_review_candidate").sum())),
        true_holdout=("final_audit_recoverability_class", lambda s: int(s.isin(["true_grade_or_mainline_holdout", "policy_hold_or_not_directionally_applicable"]).sum())),
        source_limitation=("final_audit_recoverability_class", lambda s: int((s == "true_source_or_geometry_limitation").sum())),
        unknown_debug=("final_audit_recoverability_class", lambda s: int((s == "unknown_needs_data_debug").sum())),
    ).reset_index()


def queue(df: pd.DataFrame, classes: set[str]) -> pd.DataFrame:
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
        "review_type",
        "final_residual_primary_class",
        "residual_subclass",
        "final_audit_recoverability_class",
        "evidence_summary",
        "suggested_action",
        "audit_priority_score",
        "map_review_required",
    ]
    cols = [c for c in cols if c in df.columns]
    out = df[df["final_audit_recoverability_class"].isin(classes)].copy()
    return out[cols].sort_values(["audit_priority_score", "stable_signal_id", "stable_bin_id"], ascending=[False, True, True])


def write_recommendation(detail: pd.DataFrame) -> pd.DataFrame:
    counts = detail["final_audit_recoverability_class"].value_counts()
    automatable = int(counts.get("automatable_recovery_candidate", 0))
    rule_design = int(counts.get("needs_specific_rule_design", 0))
    map_review = int(counts.get("map_review_candidate", 0))
    true_holdouts = int(counts.get("true_grade_or_mainline_holdout", 0) + counts.get("policy_hold_or_not_directionally_applicable", 0))
    if automatable + rule_design > 5_000:
        rec = "run_targeted_automated_recovery_or_rule_design_before_map_review"
    elif map_review > automatable + rule_design:
        rec = "prepare_targeted_map_review_package"
    else:
        rec = "canonical_integration_with_holdout_flags_then_targeted_review"
    row = pd.DataFrame(
        [
            {
                "recommendation": rec,
                "automatable_recovery_candidates": automatable,
                "needs_specific_rule_design": rule_design,
                "map_review_candidates": map_review,
                "true_holdouts_or_policy_holds": true_holdouts,
                "directional_crash_access_split_ready": "no",
                "note": "Audit only; no new downstream/upstream labels were assigned.",
            }
        ]
    )
    write_csv(row, "final_residual_directionality_next_step_recommendation.csv")
    return row


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    work = df.reset_index()
    work.columns = [str(c) for c in work.columns]
    rows = ["| " + " | ".join(work.columns) + " |", "| " + " | ".join(["---"] * len(work.columns)) + " |"]
    for _, row in work.iterrows():
        values = [str(row[c]) for c in work.columns]
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def write_findings(detail: pd.DataFrame, recommendation: pd.DataFrame) -> None:
    counts = detail["final_audit_recoverability_class"].value_counts().to_dict()
    subclasses = detail["residual_subclass"].value_counts().head(20).to_dict()
    by_review = detail.groupby("review_type", dropna=False)["final_audit_recoverability_class"].value_counts().unstack(fill_value=0)
    text = f"""# Final Directionality Residual Composition Audit Findings

## Bounded Question

This pass decomposes the final 34,358 uncovered directionality bins before map review. It estimates future recovery opportunities but does not assign new downstream/upstream labels.

## Residual Composition

- Residual bins audited: {len(detail):,}
- Automatable recovery candidates: {counts.get('automatable_recovery_candidate', 0):,}
- Needs specific rule design: {counts.get('needs_specific_rule_design', 0):,}
- Map-review candidates: {counts.get('map_review_candidate', 0):,}
- True source/geometry limitations: {counts.get('true_source_or_geometry_limitation', 0):,}
- True grade/mainline holdouts: {counts.get('true_grade_or_mainline_holdout', 0):,}
- Policy hold or not directionally applicable: {counts.get('policy_hold_or_not_directionally_applicable', 0):,}
- Unknown/data-debug rows: {counts.get('unknown_needs_data_debug', 0):,}

## What Is Inside The Vague Residual

Top residual subclasses: {json.dumps(subclasses, sort_keys=True)}

## Crosswalk By Original Review Type

{markdown_table(by_review)}

## Recommendation

Recommended next step: `{recommendation['recommendation'].iloc[0]}`.

Directional crash/access splitting is still inappropriate without a separate validated crash-direction-independent assignment rule.
"""
    (OUT_DIR / "final_directionality_residual_composition_audit_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_directionality_residual_composition_audit_findings.md")


def write_qa(detail: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to review/current composition audit folder."),
        ("no_records_promoted", True, "Audit-only package."),
        ("no_access_crash_assignment", True, "No access/crash assignment run."),
        ("no_rates_models", True, "No rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("no_new_downstream_upstream_labels_assigned", "directional_role" not in detail.columns and "new_directionality_label" not in detail.columns, "Audit estimates candidates only."),
        ("residual_row_count_confirmed", len(detail) == EXPECTED_RESIDUAL_BINS, f"rows={len(detail):,}"),
        ("stable_bin_id_present", detail["stable_bin_id"].notna().all(), "stable_bin_id completeness checked."),
        ("maps_to_canonical_where_available", bool(detail["maps_to_canonical_analysis_bin"].all()), f"missing canonical ids={int((~detail['maps_to_canonical_analysis_bin']).sum())}"),
        ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/final_directionality_residual_composition_audit"), str(OUT_DIR)),
    ]
    qa = pd.DataFrame(rows, columns=["qa_check", "passed", "note"])
    write_csv(qa, "final_directionality_residual_composition_audit_qa.csv")
    return qa


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "script": "src.roadway_graph.audit.final_directionality_residual_composition_audit",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "final review-only residual directionality composition audit before map review",
        "output_folder": str(OUT_DIR),
        "inputs": [
            str(FINAL_RESIDUAL_DIR),
            str(RAMP_DIR),
            str(RESIDUAL_DIR),
            str(COVERAGE_DIR),
            str(CANONICAL_DIR),
        ],
        "outputs": list(outputs),
        "non_goals": [
            "no crash direction use",
            "no new downstream/upstream labels",
            "no access/crash assignment",
            "no rates/models",
            "no active output modification",
        ],
    }
    (OUT_DIR / "final_directionality_residual_composition_audit_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    write_log("Wrote final_directionality_residual_composition_audit_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting final directionality residual composition audit.")
    residual = build_residual_pool()
    detail = add_decomposition(residual)

    write_csv(detail, "final_residual_composition_detail.csv")
    write_csv(group_summary(detail, ["final_audit_recoverability_class"]), "final_residual_composition_summary.csv")
    write_csv(group_summary(detail[detail["review_type"].eq("other")], ["residual_subclass", "final_audit_recoverability_class"]), "other_policy_residual_decomposition.csv")
    write_csv(group_summary(detail[detail["review_type"].eq("direct_map_review")], ["residual_subclass", "final_audit_recoverability_class"]), "direct_map_review_residual_decomposition.csv")
    write_csv(group_summary(detail[detail["review_type"].eq("ramp_mainline")], ["residual_subclass", "final_audit_recoverability_class"]), "ramp_mainline_residual_decomposition.csv")
    write_csv(group_summary(detail[detail["review_type"].eq("synthetic_unclear")], ["residual_subclass", "final_audit_recoverability_class"]), "synthetic_unclear_residual_decomposition.csv")
    write_csv(group_summary(detail[detail["review_type"].eq("source_or_geometry_limitation")], ["residual_subclass", "final_audit_recoverability_class"]), "source_geometry_limitation_decomposition.csv")

    write_csv(queue(detail, {"automatable_recovery_candidate"}), "residual_automatable_recovery_queue.csv")
    write_csv(queue(detail, {"needs_specific_rule_design"}), "residual_rule_design_queue.csv")
    write_csv(queue(detail, {"map_review_candidate", "unknown_needs_data_debug"}), "residual_map_review_candidate_queue.csv")
    write_csv(queue(detail, {"true_grade_or_mainline_holdout", "policy_hold_or_not_directionally_applicable", "true_source_or_geometry_limitation"}), "residual_true_holdout_queue.csv")
    recommendation = write_recommendation(detail)
    qa = write_qa(detail)
    write_findings(detail, recommendation)

    outputs = [
        "final_residual_composition_detail.csv",
        "final_residual_composition_summary.csv",
        "other_policy_residual_decomposition.csv",
        "direct_map_review_residual_decomposition.csv",
        "ramp_mainline_residual_decomposition.csv",
        "synthetic_unclear_residual_decomposition.csv",
        "source_geometry_limitation_decomposition.csv",
        "residual_automatable_recovery_queue.csv",
        "residual_rule_design_queue.csv",
        "residual_map_review_candidate_queue.csv",
        "residual_true_holdout_queue.csv",
        "final_residual_directionality_next_step_recommendation.csv",
        "final_directionality_residual_composition_audit_findings.md",
        "final_directionality_residual_composition_audit_qa.csv",
        "final_directionality_residual_composition_audit_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed final directionality residual composition audit.")


if __name__ == "__main__":
    main()
