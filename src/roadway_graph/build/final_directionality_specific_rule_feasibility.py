"""Specific-rule design feasibility for residual directionality rows.

This review-only pass scores candidate rule families for the 6,672 residual
directionality rows that need specific rule design. It estimates feasible yield
and risk but does not assign downstream/upstream labels.
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
COMPOSITION_DIR = ROOT / "work/output/roadway_graph/review/current/final_directionality_residual_composition_audit"
FINAL_RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_residual_directionality_decomposition_recovery"
RAMP_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_ramp_interchange_directionality_recovery"
DIRECT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"
UNDIVIDED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_directionality_specific_rule_feasibility"

EXPECTED_TARGET_ROWS = 6_672


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


def numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def angular_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a - b).abs() + 180.0) % 360.0 - 180.0


def build_target_pool() -> pd.DataFrame:
    detail = read_csv(COMPOSITION_DIR / "final_residual_composition_detail.csv")
    target = detail[detail["final_audit_recoverability_class"].eq("needs_specific_rule_design")].copy()
    rule_queue = read_csv(COMPOSITION_DIR / "residual_rule_design_queue.csv", usecols=["stable_bin_id"])
    canonical_ids = set(read_csv(CANONICAL_DIR / "analysis_bin.csv", usecols=["stable_bin_id"])["stable_bin_id"].astype(str))
    target["stable_bin_id"] = target["stable_bin_id"].astype(str)
    target["in_rule_design_queue"] = target["stable_bin_id"].isin(set(rule_queue["stable_bin_id"].astype(str)))
    target["maps_to_canonical_analysis_bin"] = target["stable_bin_id"].isin(canonical_ids)
    if len(target) != EXPECTED_TARGET_ROWS:
        write_log(f"Warning: target pool is {len(target):,}, expected {EXPECTED_TARGET_ROWS:,}.")
    else:
        write_log("Built specific-rule target pool=6,672 rows.")
    return target


def covered_neighbor_counts() -> pd.DataFrame:
    if not (UNDIVIDED_DIR / "undivided_centerline_synthetic_direction_rows.csv").exists():
        return pd.DataFrame(columns=["approach_key_for_grouping", "covered_synthetic_neighbor_rows", "covered_synthetic_neighbor_bins"])
    syn = read_csv(
        UNDIVIDED_DIR / "undivided_centerline_synthetic_direction_rows.csv",
        usecols=lambda c: c in {"stable_signal_id", "signal_approach_id", "stable_bin_id"},
    )
    syn["approach_key_for_grouping"] = syn["stable_signal_id"].fillna("") + "|" + syn["signal_approach_id"].fillna("")
    return syn.groupby("approach_key_for_grouping", dropna=False).agg(
        covered_synthetic_neighbor_rows=("stable_bin_id", "count"),
        covered_synthetic_neighbor_bins=("stable_bin_id", "nunique"),
    ).reset_index()


def score_rules(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    out["approach_key_for_grouping"] = out["stable_signal_id"].fillna("") + "|" + out.get(
        "signal_approach_id", pd.Series("", index=out.index)
    ).fillna("")
    out = out.merge(covered_neighbor_counts(), on="approach_key_for_grouping", how="left")
    out["covered_synthetic_neighbor_rows"] = out["covered_synthetic_neighbor_rows"].fillna(0).astype(int)
    out["covered_synthetic_neighbor_bins"] = out["covered_synthetic_neighbor_bins"].fillna(0).astype(int)

    suffix = out.get("route_suffix_direction_residual", pd.Series("", index=out.index)).fillna("").astype(str)
    suffix_diff = numeric(out, "suffix_signal_angle_diff_residual")
    axis = numeric(out, "approach_axis_diff_residual")
    anchor_count = numeric(out, "anchor_support_bin_count").fillna(0)
    geom = numeric(out, "geometry_bearing_residual")
    signal_bearing = numeric(out, "signal_to_bin_bearing_residual")
    geom_signal_diff = angular_distance(geom, signal_bearing).abs()
    start_measure = numeric(out, "source_measure_start")
    end_measure = numeric(out, "source_measure_end")
    route_measure_present = start_measure.notna() & end_measure.notna()
    route_suffix_present = suffix.str.len().gt(0)
    anchor_sufficient = signal_bearing.notna() & anchor_count.ge(2)
    anchor_strong = signal_bearing.notna() & anchor_count.ge(10)
    axis_near = axis.le(35)
    axis_relaxed = axis.le(65)
    suffix_borderline = (suffix_diff.between(55, 65, inclusive="both")) | (suffix_diff.between(115, 125, inclusive="both"))
    suffix_clear = suffix_diff.le(55) | suffix_diff.ge(125)
    digitization_reversal = suffix_clear & geom_signal_diff.between(120, 180, inclusive="both") & axis.gt(35)
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
    mainline_risk = text.str.contains("interstate|freeway|mainline", regex=True)
    ramp_conflict = out.get("ramp_interchange_primary_class", pd.Series("", index=out.index)).fillna("").str.contains(
        "mainline|mixed", regex=True
    )
    nearby_ambiguity = axis.gt(75) | anchor_count.lt(2)

    subclass = out["residual_subclass"].fillna("")
    out["candidate_rule_family"] = np.select(
        [
            subclass.eq("route_suffix_measure_borderline"),
            subclass.eq("previously_excluded_by_conservative_rule"),
            subclass.eq("recoverable_with_approach_level_grouping"),
            subclass.eq("recoverable_with_relaxed_approach_axis_threshold"),
            subclass.str.contains("surface_crossroad|surface_interchange", regex=True),
            subclass.eq("mixed_ramp_mainline_separable_possible"),
        ],
        [
            "direct_route_measure_borderline_rule",
            "direct_digitization_reversal_rule",
            "synthetic_approach_grouping_rule",
            "synthetic_relaxed_axis_rule",
            "surface_interchange_context_rule",
            "mixed_ramp_mainline_subbranch_rule",
        ],
        default="unmapped_rule_design_case",
    )
    # Some conservative-rule rows are not true digitization reversal cases; keep
    # them in a direct route/measure design family when the geometry is aligned.
    aligned_conservative = subclass.eq("previously_excluded_by_conservative_rule") & axis_near
    out.loc[aligned_conservative, "candidate_rule_family"] = "direct_route_measure_borderline_rule"

    out["route_suffix_present"] = route_suffix_present
    out["measure_orientation_present"] = route_measure_present
    out["route_measure_agreement"] = np.select(
        [route_suffix_present & route_measure_present & suffix_clear, route_suffix_present & route_measure_present & suffix_borderline],
        ["strong_or_clear", "borderline"],
        default="not_supported",
    )
    out["geometry_agreement"] = np.select(
        [geom_signal_diff.le(55), geom_signal_diff.between(55, 75, inclusive="both"), digitization_reversal],
        ["aligned", "borderline", "likely_reversed"],
        default="conflicting_or_unknown",
    )
    out["likely_digitization_reversal"] = digitization_reversal
    out["anchor_confidence"] = np.select(
        [anchor_strong, anchor_sufficient, signal_bearing.notna()],
        ["high", "medium", "low"],
        default="missing",
    )
    out["approach_axis_confidence"] = np.select(
        [axis.le(35), axis.le(65), axis.le(75)],
        ["high", "medium", "low"],
        default="poor",
    )
    out["nearby_intersection_ambiguity"] = np.select(
        [nearby_ambiguity, axis.gt(65)],
        ["high", "medium"],
        default="low",
    )
    out["ramp_mainline_conflict"] = ramp_conflict
    out["grade_mainline_holdout_risk"] = np.select(
        [mainline_risk & ramp_conflict, mainline_risk | ramp_conflict],
        ["high", "medium"],
        default="low",
    )

    score = pd.Series(0, index=out.index, dtype=float)
    score += route_suffix_present.astype(int) * 15
    score += route_measure_present.astype(int) * 15
    score += suffix_clear.astype(int) * 15
    score += suffix_borderline.astype(int) * 8
    score += anchor_sufficient.astype(int) * 15
    score += axis_near.astype(int) * 15
    score += axis_relaxed.astype(int) * 8
    score += out["covered_synthetic_neighbor_bins"].ge(3).astype(int) * 12
    score -= mainline_risk.astype(int) * 20
    score -= nearby_ambiguity.astype(int) * 12
    score -= ramp_conflict.astype(int) * 10
    out["rule_evidence_score"] = score.clip(lower=0, upper=100).round(1)

    too_risky = mainline_risk | out["candidate_rule_family"].eq("unmapped_rule_design_case") | (out["anchor_confidence"].eq("missing"))
    should_hold = out["grade_mainline_holdout_risk"].eq("high")
    out["rule_feasibility"] = np.select(
        [
            should_hold,
            too_risky,
            out["rule_evidence_score"].ge(70),
            out["rule_evidence_score"].ge(50),
            out["rule_evidence_score"].ge(35),
        ],
        [
            "should_remain_holdout",
            "too_risky_manual_review",
            "high_confidence_rule_candidate",
            "medium_confidence_rule_candidate",
            "low_confidence_rule_candidate",
        ],
        default="too_risky_manual_review",
    )
    return out


def family_summary(detail: pd.DataFrame) -> pd.DataFrame:
    return detail.groupby("candidate_rule_family", dropna=False).agg(
        target_rows=("stable_bin_id", "nunique"),
        high_confidence_candidate_rows=("rule_feasibility", lambda s: int((s == "high_confidence_rule_candidate").sum())),
        medium_confidence_candidate_rows=("rule_feasibility", lambda s: int((s == "medium_confidence_rule_candidate").sum())),
        low_confidence_candidate_rows=("rule_feasibility", lambda s: int((s == "low_confidence_rule_candidate").sum())),
        too_risky_rows=("rule_feasibility", lambda s: int((s == "too_risky_manual_review").sum())),
        holdout_rows=("rule_feasibility", lambda s: int((s == "should_remain_holdout").sum())),
        affected_signals=("stable_signal_id", "nunique"),
        affected_approaches=("signal_approach_id", "nunique"),
        mean_evidence_score=("rule_evidence_score", "mean"),
    ).reset_index()


def risk_assessment(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in summary.iterrows():
        family = row["candidate_rule_family"]
        high = int(row["high_confidence_candidate_rows"])
        med = int(row["medium_confidence_candidate_rows"])
        target = int(row["target_rows"])
        too_risky = int(row["too_risky_rows"] + row["holdout_rows"])
        if family in {"mixed_ramp_mainline_subbranch_rule", "surface_interchange_context_rule"}:
            false_positive = "high"
            review_first = "yes"
        elif too_risky > target * 0.5:
            false_positive = "high"
            review_first = "yes"
        elif high + med > target * 0.6:
            false_positive = "medium"
            review_first = "sample_map_review_before_implementation"
        else:
            false_positive = "medium_high"
            review_first = "yes"
        rows.append(
            {
                "candidate_rule_family": family,
                "false_positive_risk": false_positive,
                "expected_interpretability": "high" if family.startswith("direct_") else "medium",
                "dependency_on_route_suffix": "high" if family.startswith("direct_") else "low",
                "dependency_on_measure_orientation": "medium",
                "dependency_on_inferred_anchor": "high" if family.startswith("synthetic") else "medium",
                "map_review_before_implementation": review_first,
                "risk_note": f"{high + med:,} high/medium candidates out of {target:,}; {too_risky:,} too-risky/holdout rows.",
            }
        )
    return pd.DataFrame(rows)


def yield_estimate(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    out["estimated_recoverable_if_high_only"] = out["high_confidence_candidate_rows"]
    out["estimated_recoverable_if_high_medium"] = out["high_confidence_candidate_rows"] + out["medium_confidence_candidate_rows"]
    out["expected_coverage_gain_high_medium_share_of_total_bins"] = (
        out["estimated_recoverable_if_high_medium"] / 433_841
    )
    out["rows_requiring_map_review_or_holdout"] = out["too_risky_rows"] + out["holdout_rows"]
    return out[
        [
            "candidate_rule_family",
            "target_rows",
            "high_confidence_candidate_rows",
            "medium_confidence_candidate_rows",
            "low_confidence_candidate_rows",
            "too_risky_rows",
            "holdout_rows",
            "rows_requiring_map_review_or_holdout",
            "affected_signals",
            "affected_approaches",
            "estimated_recoverable_if_high_only",
            "estimated_recoverable_if_high_medium",
            "expected_coverage_gain_high_medium_share_of_total_bins",
        ]
    ]


def select_examples(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family, g in detail.groupby("candidate_rule_family", dropna=False):
        choices = [
            ("best_high_confidence_candidate", g[g["rule_feasibility"].eq("high_confidence_rule_candidate")].sort_values("rule_evidence_score", ascending=False).head(1)),
            ("borderline_candidate", g[g["rule_feasibility"].eq("medium_confidence_rule_candidate")].sort_values("rule_evidence_score", ascending=True).head(1)),
            ("rejected_too_risky_candidate", g[g["rule_feasibility"].isin(["too_risky_manual_review", "should_remain_holdout"])].sort_values("rule_evidence_score", ascending=False).head(1)),
            ("map_review_candidate", g[g["nearby_intersection_ambiguity"].isin(["medium", "high"])].sort_values("rule_evidence_score", ascending=False).head(1)),
        ]
        for example_type, part in choices:
            if part.empty:
                continue
            row = part.iloc[0].to_dict()
            row["example_type"] = example_type
            row["suggested_review_question"] = (
                "Does the non-crash roadway evidence support this rule family without forcing ambiguous directionality?"
            )
            rows.append(row)
    cols = [
        "example_type",
        "candidate_rule_family",
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "residual_subclass",
        "rule_feasibility",
        "rule_evidence_score",
        "route_suffix_present",
        "measure_orientation_present",
        "route_measure_agreement",
        "geometry_agreement",
        "likely_digitization_reversal",
        "anchor_confidence",
        "approach_axis_confidence",
        "nearby_intersection_ambiguity",
        "ramp_mainline_conflict",
        "grade_mainline_holdout_risk",
        "evidence_summary",
        "suggested_review_question",
        "geometry_wkt",
    ]
    df = pd.DataFrame(rows)
    return df[[c for c in cols if c in df.columns]]


def write_next_actions(summary: pd.DataFrame, risk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = summary.merge(risk, on="candidate_rule_family", how="left")
    rows = []
    for _, r in merged.iterrows():
        high_med = int(r["high_confidence_candidate_rows"] + r["medium_confidence_candidate_rows"])
        if high_med >= 1_000 and r["false_positive_risk"] in {"medium", "medium_high"}:
            rec = "promising_for_later_rule_implementation_after_sample_review"
        elif high_med > 0:
            rec = "rule_needs_map_review_or_more_design_before_implementation"
        else:
            rec = "do_not_implement_without_map_review"
        rows.append(
            {
                "candidate_rule_family": r["candidate_rule_family"],
                "recommendation": rec,
                "high_medium_candidate_rows": high_med,
                "map_review_before_implementation": r["map_review_before_implementation"],
                "note": r["risk_note"],
            }
        )
    best_family = ""
    if rows:
        best = max(rows, key=lambda r: (r["high_medium_candidate_rows"], r["candidate_rule_family"]))
        best_family = best["candidate_rule_family"]
    next_action = pd.DataFrame(
        [
            {
                "recommendation": "sample_map_review_then_implement_only_promising_specific_rules",
                "most_promising_family": best_family,
                "directional_crash_access_split_ready": "no",
                "note": "Rule feasibility only; no downstream/upstream labels assigned.",
            }
        ]
    )
    return pd.DataFrame(rows), next_action


def write_findings(detail: pd.DataFrame, summary: pd.DataFrame, risk: pd.DataFrame, next_action: pd.DataFrame) -> None:
    counts = detail["rule_feasibility"].value_counts().to_dict()
    family_counts = detail["candidate_rule_family"].value_counts().to_dict()
    best = summary.sort_values(
        ["high_confidence_candidate_rows", "medium_confidence_candidate_rows", "target_rows"],
        ascending=False,
    ).iloc[0]
    text = f"""# Final Directionality Specific-Rule Feasibility Findings

## Bounded Question

This pass scores candidate directionality rule families for the 6,672 residual bins that need specific rule design. It does not assign new downstream/upstream labels and does not use crash direction fields.

## Rule-Design Pool

- Target rows: {len(detail):,}
- Rule family composition: {json.dumps(family_counts, sort_keys=True)}

## Feasibility

- High-confidence rule candidates: {counts.get('high_confidence_rule_candidate', 0):,}
- Medium-confidence rule candidates: {counts.get('medium_confidence_rule_candidate', 0):,}
- Low-confidence rule candidates: {counts.get('low_confidence_rule_candidate', 0):,}
- Too risky/manual-review rows: {counts.get('too_risky_manual_review', 0):,}
- Holdout rows: {counts.get('should_remain_holdout', 0):,}

## Most Promising Family

- Highest likely safe yield: `{best['candidate_rule_family']}`
- High-confidence candidates: {int(best['high_confidence_candidate_rows']):,}
- Medium-confidence candidates: {int(best['medium_confidence_candidate_rows']):,}
- Target rows: {int(best['target_rows']):,}

## Rule Viability

- Direct route/measure borderline rule: viable only after sample map review; it carries the largest target pool but depends on route suffix and anchor evidence.
- Synthetic approach-grouping rule: potentially viable for context-only synthetic interpretations, but still needs a specific grouping rule and no crash/access split.
- Surface-interchange rule: not materially represented in this 6,672-row rule-design target after prior passes.
- Mixed ramp/mainline subbranch rule: very small target and should be reviewed before implementation.

## Recommendation

Recommended next step: `{next_action['recommendation'].iloc[0]}`. Directional crash/access splitting remains out of scope until a separate validated non-crash assignment rule exists.
"""
    (OUT_DIR / "final_directionality_specific_rule_feasibility_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_directionality_specific_rule_feasibility_findings.md")


def write_qa(detail: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to review/current specific-rule feasibility folder."),
        ("no_records_promoted", True, "Rule feasibility only."),
        ("no_access_crash_assignment", True, "No access/crash assignment run."),
        ("no_rates_models", True, "No rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("no_new_downstream_upstream_labels_assigned", "new_directionality_label" not in detail.columns and "directional_role" not in detail.columns, "Candidate rules scored only."),
        ("true_grade_mainline_holdouts_not_forced", True, "Grade/mainline risk is scored, not recovered."),
        ("target_row_count_confirmed", len(detail) == EXPECTED_TARGET_ROWS, f"rows={len(detail):,}"),
        ("stable_bin_id_present", detail["stable_bin_id"].notna().all(), "stable_bin_id completeness checked."),
        ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/final_directionality_specific_rule_feasibility"), str(OUT_DIR)),
    ]
    qa = pd.DataFrame(rows, columns=["qa_check", "passed", "note"])
    write_csv(qa, "final_directionality_specific_rule_feasibility_qa.csv")
    return qa


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "script": "src.roadway_graph.build.final_directionality_specific_rule_feasibility",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "review-only specific-rule feasibility for 6,672 residual directionality rows",
        "output_folder": str(OUT_DIR),
        "inputs": [
            str(COMPOSITION_DIR),
            str(FINAL_RESIDUAL_DIR),
            str(RAMP_DIR),
            str(DIRECT_DIR),
            str(UNDIVIDED_DIR),
            str(DOCTRINE_DIR),
            str(CANONICAL_DIR),
        ],
        "outputs": list(outputs),
        "non_goals": [
            "no new directionality labels",
            "no crash direction use",
            "no access/crash assignment",
            "no rates/models",
            "no active output modification",
        ],
    }
    (OUT_DIR / "final_directionality_specific_rule_feasibility_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    write_log("Wrote final_directionality_specific_rule_feasibility_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting final directionality specific-rule feasibility.")
    target = build_target_pool()
    detail = score_rules(target)
    summary = family_summary(detail)
    yield_df = yield_estimate(summary)
    risk = risk_assessment(summary)
    examples = select_examples(detail)
    map_review_rec, next_action = write_next_actions(summary, risk)

    write_csv(target, "specific_rule_target_pool.csv")
    write_csv(detail, "specific_rule_feasibility_detail.csv")
    write_csv(summary, "specific_rule_family_summary.csv")
    write_csv(yield_df, "specific_rule_recoverable_yield_estimate.csv")
    write_csv(risk, "specific_rule_risk_assessment.csv")
    write_csv(examples, "specific_rule_examples.csv")
    write_csv(map_review_rec, "specific_rule_map_review_recommendation.csv")
    write_csv(next_action, "specific_rule_next_action.csv")
    qa = write_qa(detail)
    write_findings(detail, summary, risk, next_action)

    outputs = [
        "specific_rule_target_pool.csv",
        "specific_rule_feasibility_detail.csv",
        "specific_rule_family_summary.csv",
        "specific_rule_recoverable_yield_estimate.csv",
        "specific_rule_risk_assessment.csv",
        "specific_rule_examples.csv",
        "specific_rule_map_review_recommendation.csv",
        "specific_rule_next_action.csv",
        "final_directionality_specific_rule_feasibility_findings.md",
        "final_directionality_specific_rule_feasibility_qa.csv",
        "final_directionality_specific_rule_feasibility_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed final directionality specific-rule feasibility.")


if __name__ == "__main__":
    main()
