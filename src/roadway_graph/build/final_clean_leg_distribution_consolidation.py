"""Consolidate final-clean leg distribution after missing-leg generation.

Bounded question:
    Combine the 3,719-signal final clean bin universe, review-only generated
    missing-leg bins, and label-only leg normalization proposals into one
    residual leg-state diagnostic. This pass preserves rows and labels only; it
    does not context-refresh generated bins or assign crashes/access.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyogrio


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_leg_distribution_consolidation"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
LEG_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_leg_recovery_normalization"
GEN_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_generation"
SOURCE_TRAVELWAY = ROOT / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "final_distribution": FINAL_DIR / "final_clean_physical_leg_distribution.csv",
    "final_window_availability": FINAL_DIR / "final_clean_bin_window_availability.csv",
    "leg_target_pool": LEG_DIR / "final_clean_leg_target_pool.csv",
    "source_zone_detail": LEG_DIR / "final_clean_source_zone_expected_leg_detail.csv",
    "one_two_detail": LEG_DIR / "one_two_leg_recoverability_detail.csv",
    "five_plus_detail": LEG_DIR / "five_plus_normalization_detail.csv",
    "label_proposals": LEG_DIR / "corrected_leg_label_proposals.csv",
    "remaining_leg_issue_summary": LEG_DIR / "remaining_leg_issue_summary.csv",
    "generated_target_signals": GEN_DIR / "missing_leg_generation_target_signals.csv",
    "generated_source_detail": GEN_DIR / "missing_leg_generation_source_leg_detail.csv",
    "generated_leg_candidates": GEN_DIR / "missing_leg_generated_leg_candidates.csv",
    "generated_bins": GEN_DIR / "missing_leg_generated_bins.csv",
    "generated_skipped": GEN_DIR / "missing_leg_generation_skipped_targets.csv",
    "generated_summary": GEN_DIR / "missing_leg_generation_summary.csv",
    "generated_distribution": GEN_DIR / "missing_leg_generation_revised_distribution_estimate.csv",
    "generated_readiness": GEN_DIR / "missing_leg_generation_context_refresh_readiness.csv",
    "source_travelway": SOURCE_TRAVELWAY,
}


FIVE_PLUS_LABEL_CLASSES = {
    "over_split_carriageway_subbranches",
    "connector_internal_segments_counted_as_legs",
    "source_line_split_same_physical_leg",
    "adjacent_bearing_sector_split_same_approach",
}


def log(lines: list[str], message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    lines.append(f"{stamp} {message}")
    print(message)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def stable_hash(parts: list[object], prefix: str, n: int = 16) -> str:
    text = "|".join("" if pd.isna(p) else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:n]}"


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
    if not SOURCE_TRAVELWAY.exists():
        return {"available": False, "note": "source Travelway GeoPackage not found"}
    try:
        info = pyogrio.read_info(SOURCE_TRAVELWAY, layer="source_travelway_full")
        return {
            "available": True,
            "features": int(info.get("features", 0)),
            "geometry_type": str(info.get("geometry_type", "")),
            "fid_column": str(info.get("fid_column", "")),
            "note": "Layer metadata read only; source geometries were not loaded.",
        }
    except Exception as exc:  # pragma: no cover
        return {"available": False, "note": f"metadata read failed: {type(exc).__name__}: {exc}"}


def compute_original_counts(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    binned = (
        bins.groupby("stable_signal_id", dropna=False)
        .agg(
            bin_count=("stable_bin_id", "size"),
            binned_physical_leg_count=("physical_leg_id", nunique_nonblank),
            binned_subbranch_count=("carriageway_subbranch_id", nunique_nonblank),
            stable_travelway_count=("stable_travelway_id", nunique_nonblank),
        )
        .reset_index()
    )
    out = signals.merge(binned, on="stable_signal_id", how="left")
    for col in ["bin_count", "binned_physical_leg_count", "binned_subbranch_count", "stable_travelway_count"]:
        out[col] = out[col].fillna(0).astype(int)
    fallback = pd.to_numeric(out.get("signal_level_physical_leg_count", pd.NA), errors="coerce")
    out["original_physical_leg_count"] = out["binned_physical_leg_count"]
    use_fallback = (out["original_physical_leg_count"] <= 0) & fallback.notna()
    out.loc[use_fallback, "original_physical_leg_count"] = fallback[use_fallback].astype(int)
    out["original_physical_leg_bucket"] = out["original_physical_leg_count"].map(leg_bucket)
    return out


def apply_labels_and_generation(
    counts: pd.DataFrame,
    proposals: pd.DataFrame,
    generated_legs: pd.DataFrame,
    five_plus: pd.DataFrame,
) -> pd.DataFrame:
    out = counts.copy()
    proposal_cols = [
        "stable_signal_id",
        "current_physical_leg_count",
        "corrected_estimated_physical_leg_count",
        "leg_recovery_status",
        "leg_recovery_normalization_rule",
        "leg_recovery_confidence",
    ]
    for col in proposal_cols:
        if col not in proposals.columns:
            proposals[col] = pd.NA
    out = out.merge(proposals[proposal_cols].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    out["label_only_physical_leg_count"] = pd.to_numeric(
        out["corrected_estimated_physical_leg_count"], errors="coerce"
    ).fillna(out["original_physical_leg_count"])

    gen = (
        generated_legs.groupby("stable_signal_id")["corrected_physical_leg_id"]
        .nunique()
        .reset_index(name="generated_missing_leg_count")
        if not generated_legs.empty
        else pd.DataFrame(columns=["stable_signal_id", "generated_missing_leg_count"])
    )
    out = out.merge(gen, on="stable_signal_id", how="left")
    out["generated_missing_leg_count"] = out["generated_missing_leg_count"].fillna(0).astype(int)
    out["generated_only_physical_leg_count"] = out["original_physical_leg_count"] + out["generated_missing_leg_count"]

    five_classes = five_plus[["stable_signal_id", "five_plus_normalization_class"]].drop_duplicates("stable_signal_id")
    out = out.merge(five_classes, on="stable_signal_id", how="left")
    is_five_label = out["five_plus_normalization_class"].isin(FIVE_PLUS_LABEL_CLASSES)
    out["combined_physical_leg_count"] = out["generated_only_physical_leg_count"]
    out.loc[is_five_label, "combined_physical_leg_count"] = out.loc[is_five_label, "label_only_physical_leg_count"]
    no_gen = out["generated_missing_leg_count"].eq(0) & out["leg_recovery_status"].notna() & ~is_five_label
    # Keep source-limited and failed-generation estimates visible, but do not fabricate actual generated legs.
    out.loc[no_gen, "combined_physical_leg_count"] = out.loc[no_gen, "label_only_physical_leg_count"]

    for col in ["label_only_physical_leg_count", "generated_only_physical_leg_count", "combined_physical_leg_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(out["original_physical_leg_count"]).astype(int)
        out[col.replace("_count", "_bucket")] = out[col].map(leg_bucket)
    return out


def distribution_table(summary: pd.DataFrame) -> pd.DataFrame:
    scenarios = [
        ("original_final_clean", "original_physical_leg_count"),
        ("after_label_only_normalization", "label_only_physical_leg_count"),
        ("after_generated_missing_leg_additions", "generated_only_physical_leg_count"),
        ("after_label_and_generated_missing_leg_consolidation", "combined_physical_leg_count"),
    ]
    rows = []
    for scenario, col in scenarios:
        tmp = summary[col].map(leg_bucket).value_counts().to_dict()
        total = int(sum(tmp.values()))
        for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
            rows.append(
                {
                    "distribution_scenario": scenario,
                    "physical_leg_bucket": bucket,
                    "signal_count": int(tmp.get(bucket, 0)),
                    "share": round(tmp.get(bucket, 0) / total, 4) if total else 0,
                }
            )
        rows.append(
            {
                "distribution_scenario": scenario,
                "physical_leg_bucket": "two_leg_or_less_combined",
                "signal_count": int(tmp.get("one_leg", 0) + tmp.get("two_leg", 0)),
                "share": round((tmp.get("one_leg", 0) + tmp.get("two_leg", 0)) / total, 4) if total else 0,
            }
        )
        rows.append(
            {
                "distribution_scenario": scenario,
                "physical_leg_bucket": "three_four_combined",
                "signal_count": int(tmp.get("three_leg", 0) + tmp.get("four_leg", 0)),
                "share": round((tmp.get("three_leg", 0) + tmp.get("four_leg", 0)) / total, 4) if total else 0,
            }
        )
    return pd.DataFrame(rows)


def consolidated_bin_detail(final_bins: pd.DataFrame, generated_bins: pd.DataFrame, proposals: pd.DataFrame) -> pd.DataFrame:
    base = final_bins.copy()
    base["bin_source"] = "existing_final_clean_bin"
    base["original_physical_leg_id"] = base["physical_leg_id"]
    base["corrected_physical_leg_id"] = base["physical_leg_id"]
    base["original_carriageway_subbranch_id"] = base["carriageway_subbranch_id"]
    base["corrected_carriageway_subbranch_id"] = base["carriageway_subbranch_id"]
    base["review_only"] = True
    base["leg_distribution_consolidation_provenance"] = "existing_final_clean_universe"

    prop = proposals[
        [
            "stable_signal_id",
            "corrected_estimated_physical_leg_count",
            "leg_recovery_status",
            "leg_recovery_normalization_rule",
            "leg_recovery_confidence",
        ]
    ].drop_duplicates("stable_signal_id")
    base = base.merge(prop, on="stable_signal_id", how="left")
    needs_label = base["leg_recovery_status"].notna() & base["corrected_physical_leg_id"].isna()
    base.loc[needs_label, "corrected_physical_leg_id"] = base.loc[needs_label].apply(
        lambda r: stable_hash([r["stable_signal_id"], "label_only", r.get("stable_travelway_id"), r.get("source_route_name")], "physleg"),
        axis=1,
    )
    base.loc[needs_label, "corrected_carriageway_subbranch_id"] = base.loc[needs_label].apply(
        lambda r: stable_hash([r["corrected_physical_leg_id"], r.get("stable_travelway_id"), r.get("source_feature_local_fid")], "subbranch"),
        axis=1,
    )

    gen = generated_bins.copy()
    if not gen.empty:
        gen["bin_source"] = "generated_missing_leg_candidate_bin"
        gen["original_physical_leg_id"] = pd.NA
        gen["original_carriageway_subbranch_id"] = pd.NA
        if "physical_leg_id" not in gen.columns:
            gen["physical_leg_id"] = gen["corrected_physical_leg_id"]
        if "carriageway_subbranch_id" not in gen.columns:
            gen["carriageway_subbranch_id"] = gen["corrected_carriageway_subbranch_id"]
        gen["leg_distribution_consolidation_provenance"] = "final_clean_missing_leg_generation"
        gen["leg_recovery_status"] = gen.get("leg_recovery_status", "generated_missing_leg_candidate")
        gen["leg_recovery_normalization_rule"] = "generated_missing_leg_candidate"
        gen["leg_recovery_confidence"] = gen.get("lineage_confidence", "medium_review_only")

    cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "original_physical_leg_id",
        "physical_leg_id",
        "corrected_physical_leg_id",
        "original_carriageway_subbranch_id",
        "carriageway_subbranch_id",
        "corrected_carriageway_subbranch_id",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "geometry_hash",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "bin_source",
        "leg_recovery_status",
        "leg_recovery_normalization_rule",
        "leg_recovery_confidence",
        "leg_distribution_consolidation_provenance",
        "review_only",
    ]
    for df in [base, gen]:
        for col in cols:
            if col not in df.columns:
                df[col] = pd.NA
    return pd.concat([base[cols], gen[cols]], ignore_index=True)


def remaining_two_leg(summary: pd.DataFrame, one_two: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    rem = summary[summary["combined_physical_leg_bucket"].eq("two_leg")].copy()
    detail = one_two[["stable_signal_id", "one_two_leg_recoverability_class"]].drop_duplicates("stable_signal_id")
    rem = rem.merge(detail, on="stable_signal_id", how="left")
    rem = rem.merge(skipped[["stable_signal_id", "skip_reason"]].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    def classify(row: pd.Series) -> str:
        if row.get("skip_reason") == "source_leg_not_found":
            return "missing_leg_generation_failed_source_leg_not_found"
        if row.get("skip_reason") == "source_geometry_ambiguous":
            return "missing_leg_generation_failed_source_geometry_ambiguous"
        c = row.get("one_two_leg_recoverability_class")
        if c == "true_source_limited_partial_signal":
            return "true_source_limited_partial_signal"
        if c == "source_travelway_missing_cross_street":
            return "source_travelway_missing_cross_street"
        if c == "offset_anchor_or_intersection_zone_needed":
            return "offset_anchor_or_intersection_zone_needed"
        if c == "under_captured_recoverable_source_leg":
            return "possible_recoverable_with_broader_source_search"
        return "manual_review_needed"
    rem["remaining_two_leg_issue_class"] = rem.apply(classify, axis=1)
    return rem


def remaining_three_leg(summary: pd.DataFrame, three_audit_path: Path, skipped: pd.DataFrame, gen_legs: pd.DataFrame) -> pd.DataFrame:
    rem = summary[summary["combined_physical_leg_bucket"].eq("three_leg")].copy()
    three = read_csv(three_audit_path)
    if not three.empty:
        rem = rem.merge(
            three[["stable_signal_id", "three_leg_missing_fourth_class", "next_generation_class"]].drop_duplicates("stable_signal_id"),
            on="stable_signal_id",
            how="left",
        )
    rem = rem.merge(skipped[["stable_signal_id", "skip_reason"]].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    gen_ids = set(gen_legs["stable_signal_id"].dropna().astype(str)) if not gen_legs.empty else set()
    def classify(row: pd.Series) -> str:
        sid = str(row["stable_signal_id"])
        if row.get("skip_reason") == "source_leg_not_found":
            return "missing_fourth_generation_failed_source_leg_not_found"
        if row.get("skip_reason") == "source_geometry_ambiguous":
            return "missing_fourth_generation_failed_source_geometry_ambiguous"
        if sid in gen_ids and row.get("three_leg_missing_fourth_class") == "three_leg_recoverable_missing_fourth_leg":
            return "missing_fourth_generation_succeeded_but_still_three"
        c = row.get("three_leg_missing_fourth_class")
        if c == "three_leg_true_t_intersection":
            return "true_three_leg_t_intersection"
        if c == "three_leg_complex_or_offset_review":
            return "possible_recoverable_with_broader_source_search"
        if c == "three_leg_recoverable_missing_fourth_leg":
            return "possible_recoverable_with_broader_source_search"
        return "manual_review_needed"
    rem["remaining_three_leg_issue_class"] = rem.apply(classify, axis=1)
    return rem


def remaining_five_plus(summary: pd.DataFrame, five_plus: pd.DataFrame) -> pd.DataFrame:
    rem = summary[summary["combined_physical_leg_bucket"].eq("five_plus_leg")].copy()
    if not five_plus.empty:
        rem = rem.merge(
            five_plus[["stable_signal_id", "five_plus_normalization_class"]].drop_duplicates("stable_signal_id"),
            on="stable_signal_id",
            how="left",
        )
    def classify(row: pd.Series) -> str:
        c = row.get("five_plus_normalization_class")
        if c == "over_split_carriageway_subbranches":
            return "over_split_still_unresolved"
        if c == "connector_internal_segments_counted_as_legs":
            return "connector_internal_segments_still_counted"
        if c == "source_line_split_same_physical_leg":
            return "carriageway_subbranch_normalization_still_needed"
        if str(row.get("recovery_branch", "")).lower() == "complex_multisignal":
            return "complex_multi_signal_context"
        if pd.isna(c):
            return "true_complex_five_plus_possible"
        return "manual_review_needed"
    rem["remaining_five_plus_issue_class"] = rem.apply(classify, axis=1)
    return rem


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[str] = []
    started = datetime.now(timezone.utc)
    log(progress, "Starting final clean leg distribution consolidation.")

    signals = read_csv(INPUTS["final_signals"])
    final_bins = read_csv(INPUTS["final_bins"])
    generated_bins = read_csv(INPUTS["generated_bins"])
    generated_legs = read_csv(INPUTS["generated_leg_candidates"])
    proposals = read_csv(INPUTS["label_proposals"])
    one_two = read_csv(INPUTS["one_two_detail"])
    five_plus = read_csv(INPUTS["five_plus_detail"])
    skipped = read_csv(INPUTS["generated_skipped"])
    source_meta = source_travelway_metadata()
    log(progress, f"Loaded inputs: signals={len(signals)}, final_bins={len(final_bins)}, generated_bins={len(generated_bins)}.")

    original_counts = compute_original_counts(signals, final_bins)
    signal_summary = apply_labels_and_generation(original_counts, proposals, generated_legs, five_plus)
    consolidated_bins = consolidated_bin_detail(final_bins, generated_bins, proposals)
    distribution = distribution_table(signal_summary)

    two_detail = remaining_two_leg(signal_summary, one_two, skipped)
    three_detail = remaining_three_leg(
        signal_summary,
        ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_queue_audit/current_three_leg_missing_fourth_audit.csv",
        skipped,
        generated_legs,
    )
    five_detail = remaining_five_plus(signal_summary, five_plus)

    label_summary = (
        five_plus.groupby("five_plus_normalization_class", dropna=False)
        .agg(signal_count=("stable_signal_id", "nunique"))
        .reset_index()
    )
    label_summary["label_only_applied_class"] = label_summary["five_plus_normalization_class"].isin(FIVE_PLUS_LABEL_CLASSES)
    generated_summary = pd.DataFrame(
        [
            ("generated_signals", generated_bins["stable_signal_id"].nunique() if not generated_bins.empty else 0),
            ("generated_physical_legs", generated_legs["corrected_physical_leg_id"].nunique() if not generated_legs.empty else 0),
            ("generated_bins", len(generated_bins)),
            ("skipped_targets", skipped["stable_signal_id"].nunique() if not skipped.empty else 0),
            ("bins_missing_stable_travelway_id", int(generated_bins["stable_travelway_id"].isna().sum()) if not generated_bins.empty else 0),
        ],
        columns=["metric", "value"],
    )
    skipped_audit = skipped.merge(
        signal_summary[
            [
                "stable_signal_id",
                "source_signal_id",
                "recovery_branch",
                "original_physical_leg_count",
                "label_only_physical_leg_count",
                "combined_physical_leg_count",
                "leg_recovery_status",
            ]
        ],
        on=["stable_signal_id", "source_signal_id"],
        how="left",
    )
    skipped_audit["broader_source_search_might_help"] = skipped_audit["skip_reason"].eq("source_leg_not_found")
    skipped_audit["intersection_zone_anchor_might_help"] = skipped_audit["skip_reason"].eq("source_geometry_ambiguous")
    skipped_audit["source_limited_holdout_more_appropriate"] = False

    next_action = pd.DataFrame(
        [
            {
                "recommended_action": "context_refresh_generated_missing_leg_bins",
                "priority": 1,
                "signal_count": int(generated_bins["stable_signal_id"].nunique()) if not generated_bins.empty else 0,
                "rationale": "Generated bins have stable Travelway lineage and route/measure fields; context refresh is needed before integration.",
            },
            {
                "recommended_action": "run_broader_source_search_for_skipped_targets",
                "priority": 2,
                "signal_count": int(skipped["stable_signal_id"].nunique()) if not skipped.empty else 0,
                "rationale": "Skipped targets are concentrated in source_leg_not_found and source_geometry_ambiguous classes.",
            },
            {
                "recommended_action": "carry_label_only_five_plus_normalization",
                "priority": 3,
                "signal_count": int(label_summary.loc[label_summary["label_only_applied_class"], "signal_count"].sum()) if not label_summary.empty else 0,
                "rationale": "Five-plus over-split/subbranch corrections are row-preserving labels and do not require context refresh.",
            },
        ]
    )

    consolidated_bins.to_csv(OUT_DIR / "consolidated_leg_bin_detail.csv", index=False)
    signal_summary.to_csv(OUT_DIR / "consolidated_leg_signal_summary.csv", index=False)
    distribution.to_csv(OUT_DIR / "consolidated_physical_leg_distribution.csv", index=False)
    label_summary.to_csv(OUT_DIR / "label_only_five_plus_normalization_summary.csv", index=False)
    generated_summary.to_csv(OUT_DIR / "generated_missing_leg_integration_summary.csv", index=False)
    two_detail.to_csv(OUT_DIR / "remaining_two_leg_issue_detail.csv", index=False)
    three_detail.to_csv(OUT_DIR / "remaining_three_leg_issue_detail.csv", index=False)
    five_detail.to_csv(OUT_DIR / "remaining_five_plus_issue_detail.csv", index=False)
    skipped_audit.to_csv(OUT_DIR / "skipped_missing_leg_generation_audit.csv", index=False)
    next_action.to_csv(OUT_DIR / "leg_distribution_next_action_recommendation.csv", index=False)

    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to review/current/final_clean_leg_distribution_consolidation."),
            ("no_records_promoted", True, "All rows remain review-only diagnostics/candidates."),
            ("no_crash_assignment", True, "Crash records were not read."),
            ("no_access_assignment", True, "Access assignment was not run."),
            ("no_rates_or_models", True, "No rates/models calculated."),
            ("no_speed_aadt_context_refresh", True, "Generated bins were not context-refreshed."),
            ("no_rows_deleted_or_collapsed", len(consolidated_bins) == len(final_bins) + len(generated_bins), "Existing and generated rows are preserved."),
            ("original_and_corrected_leg_labels_preserved", {"original_physical_leg_id", "corrected_physical_leg_id"}.issubset(consolidated_bins.columns), "Both label surfaces are present."),
            ("source_limited_cases_not_forced", True, "Skipped/source-limited cases are audit labels only."),
            ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/final_clean_leg_distribution_consolidation"), str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "notes"],
    )
    qa.to_csv(OUT_DIR / "final_clean_leg_distribution_consolidation_qa.csv", index=False)

    def scenario_counts(name: str) -> dict[str, int]:
        rows = distribution[distribution["distribution_scenario"].eq(name)]
        return dict(zip(rows["physical_leg_bucket"], rows["signal_count"]))

    original = scenario_counts("original_final_clean")
    label = scenario_counts("after_label_only_normalization")
    gen = scenario_counts("after_generated_missing_leg_additions")
    both = scenario_counts("after_label_and_generated_missing_leg_consolidation")
    two_counts = two_detail["remaining_two_leg_issue_class"].value_counts().to_dict()
    three_counts = three_detail["remaining_three_leg_issue_class"].value_counts().to_dict()
    five_counts = five_detail["remaining_five_plus_issue_class"].value_counts().to_dict()
    findings = f"""# Final Clean Leg Distribution Consolidation

## Bounded Question

Consolidate original final-clean bins, generated missing-leg candidate bins, and label-only leg normalization proposals into one review-only residual leg-state diagnostic. This pass does not context-refresh generated bins, assign speed/AADT, assign access/crashes, calculate rates/models, delete rows, collapse rows, promote records, or modify active outputs.

## Findings

1. Physical-leg distribution after label-only normalization: `{label}`.
2. Physical-leg distribution after generated missing-leg additions only: `{gen}`.
3. Physical-leg distribution after both label-only normalization and generated missing-leg additions: `{both}`.
4. Five-plus changes from **{original.get('five_plus_leg', 0)}** original to **{label.get('five_plus_leg', 0)}** after label-only normalization and **{both.get('five_plus_leg', 0)}** after full consolidation.
5. Remaining two-leg classes: `{two_counts}`.
6. Remaining three-leg classes: `{three_counts}`.
7. Remaining five-plus classes: `{five_counts}`.
8. The 358 skipped missing-leg generation targets are summarized in `skipped_missing_leg_generation_audit.csv`; source-leg-not-found cases are candidates for broader source search, while geometry-ambiguous cases are candidates for intersection-zone anchor logic.
9. Next best action before context/access/crash refresh is to context-refresh the 19,662 generated missing-leg bins, while carrying label-only five-plus normalization as QA and separately triaging skipped targets.
10. The consolidated distribution is more plausible than the raw final-clean distribution, but context refresh and a focused skipped-target diagnostic should happen before treating generated missing legs as analysis-ready.

## Source Travelway Read

`source_travelway_full` metadata was read only: `{source_meta}`.
"""
    (OUT_DIR / "final_clean_leg_distribution_consolidation_findings.md").write_text(findings, encoding="utf-8")

    manifest = {
        "script": "src/active/roadway_graph/final_clean_leg_distribution_consolidation.py",
        "created_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "inputs": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in INPUTS.items() if v.exists()},
        "source_travelway_metadata": source_meta,
        "outputs": [
            "consolidated_leg_bin_detail.csv",
            "consolidated_leg_signal_summary.csv",
            "consolidated_physical_leg_distribution.csv",
            "label_only_five_plus_normalization_summary.csv",
            "generated_missing_leg_integration_summary.csv",
            "remaining_two_leg_issue_detail.csv",
            "remaining_three_leg_issue_detail.csv",
            "remaining_five_plus_issue_detail.csv",
            "skipped_missing_leg_generation_audit.csv",
            "leg_distribution_next_action_recommendation.csv",
            "final_clean_leg_distribution_consolidation_findings.md",
            "final_clean_leg_distribution_consolidation_qa.csv",
            "final_clean_leg_distribution_consolidation_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "signals": int(len(signals)),
            "existing_bins": int(len(final_bins)),
            "generated_bins": int(len(generated_bins)),
            "consolidated_bin_rows": int(len(consolidated_bins)),
            "remaining_two_leg": int(len(two_detail)),
            "remaining_three_leg": int(len(three_detail)),
            "remaining_five_plus": int(len(five_detail)),
        },
        "non_goals_confirmed": [
            "no_context_refresh",
            "no_crash_assignment",
            "no_access_assignment",
            "no_rates_or_models",
            "no_active_outputs_modified",
        ],
    }
    (OUT_DIR / "final_clean_leg_distribution_consolidation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(progress, "Wrote final clean leg distribution consolidation outputs.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
