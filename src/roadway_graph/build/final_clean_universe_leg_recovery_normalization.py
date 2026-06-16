"""Review-only full-clean-universe physical-leg recovery/normalization diagnostic.

Bounded question:
    Diagnose implausible physical-leg counts in the 3,719-signal clean
    review-analysis universe, propose label-only leg normalization/recovery
    classes, and identify whether any missing-leg candidate bins can be created
    without forcing source-limited or ambiguous evidence.

This module writes only review outputs. It does not modify active outputs,
promote records, assign crashes/access, or calculate rates/models.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_leg_recovery_normalization"

FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
PRIOR_DIR = ROOT / "work/output/roadway_graph/review/current"

INPUTS = {
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "final_leg_distribution": FINAL_DIR / "final_clean_physical_leg_distribution.csv",
    "final_manifest": FINAL_DIR / "final_clean_universe_context_summary_manifest.json",
    "prior_leg_coverage": PRIOR_DIR / "expanded_universe_leg_coverage_audit/leg_coverage_signal_summary.csv",
    "prior_physical_leg_normalization": PRIOR_DIR
    / "expanded_universe_physical_leg_normalization_audit/physical_leg_signal_summary.csv",
    "prior_intersection_zone_detail": PRIOR_DIR
    / "intersection_zone_leg_source_graph_diagnostic/intersection_zone_leg_diagnostic_detail.csv",
    "prior_missing_leg_candidates": PRIOR_DIR
    / "intersection_zone_missing_leg_recovery_candidates/recovered_missing_physical_leg_candidates.csv",
    "prior_consolidated_alignment": PRIOR_DIR
    / "consolidated_scaffold_completeness_refresh/consolidated_scaffold_expected_alignment.csv",
    "prior_divided_subbranch": PRIOR_DIR
    / "divided_carriageway_subbranch_normalization/divided_subbranch_normalized_signal_summary.csv",
    "prior_adjacent_merge": PRIOR_DIR / "divided_adjacent_bearing_sector_merge/adjacent_sector_merge_signal_summary.csv",
    "prior_remaining_norm": PRIOR_DIR
    / "divided_remaining_implementable_normalization/remaining_normalization_signal_summary.csv",
    "prior_expected_leg": PRIOR_DIR / "full_universe_expected_leg_expansion/full_universe_expected_leg_detail.csv",
}


def log(lines: list[str], message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    lines.append(f"{stamp} {message}")
    print(message)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def bool_series(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index)
    s = df[col]
    if s.dtype == bool:
        return s.fillna(default)
    return (
        s.astype(str)
        .str.strip()
        .str.lower()
        .map({"true": True, "1": True, "yes": True, "y": True, "false": False, "0": False, "no": False, "n": False})
        .fillna(default)
    )


def first_col(df: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def first_value(row: pd.Series, names: Iterable[str], default: object = pd.NA) -> object:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return default


def stable_hash(parts: Iterable[object], prefix: str) -> str:
    text = "|".join("" if pd.isna(p) else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


def leg_bucket(count: int) -> str:
    if count <= 0:
        return "zero_or_unknown_leg"
    if count == 1:
        return "one_leg"
    if count == 2:
        return "two_leg"
    if count == 3:
        return "three_leg"
    if count == 4:
        return "four_leg"
    return "five_plus_leg"


def build_method_inventory() -> pd.DataFrame:
    rows = [
        (
            "intersection-zone source vs graph comparison",
            "intersection_zone_leg_source_graph_diagnostic",
            "Compare nearby source Travelway bearing groups to scaffold/candidate physical legs.",
            True,
            "Applicable as diagnostic evidence where prior source-zone rows exist; for newer branches use final stable Travelway/bin lineage as proxy.",
        ),
        (
            "source Travelway bearing-sector physical-leg grouping",
            "expanded_universe_physical_leg_normalization_audit",
            "Group source/candidate rows by physical bearing, not by every source row or carriageway branch.",
            True,
            "Applies to five-plus and two-leg suspicious classes.",
        ),
        (
            "missing source-leg recovery",
            "intersection_zone_missing_leg_recovery_candidates",
            "Generate candidate bins only when source Travelway has a clear absent bearing sector.",
            True,
            "Use as methodological reference; this pass does not force candidates without stable Travelway lineage.",
        ),
        (
            "offset/intersection-zone anchor recovery",
            "offset_intersection_zone_scaffold_recovery",
            "Use inferred intersection-zone anchors when raw signal points are offset from the signal plane.",
            True,
            "Relevant to offset-anchor branch QA and one/two-leg under-capture classes.",
        ),
        (
            "adjacent bearing-sector merge",
            "divided_adjacent_bearing_sector_merge",
            "Merge adjacent bearing sectors that represent one physical approach split by divided geometry/source segmentation.",
            True,
            "Applies to five-plus and four-leg-with-subbranch QA signals.",
        ),
        (
            "candidate branch over-split normalization",
            "expanded_universe_physical_leg_normalization_audit",
            "Separate candidate branches from normalized physical legs.",
            True,
            "Applies across all branches, especially recovered signals with source-row/subbranch splits.",
        ),
        (
            "source-line split same physical leg",
            "divided_remaining_implementable_normalization",
            "Treat multiple source rows on one approach as subbranches or same-leg splits.",
            True,
            "Applies to five-plus signals with high stable-Travelway/source-row counts.",
        ),
        (
            "divided/carriageway subbranch normalization",
            "divided_carriageway_subbranch_normalization",
            "Keep divided carriageways/subbranches separate from physical-leg counts.",
            True,
            "Applies directly to good-Travelway, ramp-terminal, and complex branches.",
        ),
        (
            "ramp-terminal subbranch handling",
            "ramp_terminal_universe_integration",
            "Treat ramp/frontage/surface subbranches as QA flags, not automatic exclusion.",
            True,
            "Applies to ramp-terminal branch; do not collapse rows, only label corrected physical legs.",
        ),
        (
            "complex connector/internal segment handling",
            "missing_hmms_complex_multisignal_context_refresh",
            "Preserve connector/internal segment QA; do not silently count internal connectors as independent physical legs.",
            True,
            "Applies to complex multi-signal branch and any high-row-count complex context.",
        ),
    ]
    return pd.DataFrame(
        rows,
        columns=["method_rule", "prior_reference", "rule_summary", "applicable_to_3719", "application_note"],
    )


def compute_signal_leg_features(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    bins = bins.copy()
    for col in ["physical_leg_id", "carriageway_subbranch_id", "stable_travelway_id", "source_feature_local_fid"]:
        if col not in bins.columns:
            bins[col] = pd.NA
    for col in ["distance_start_ft", "distance_end_ft"]:
        bins[col] = pd.to_numeric(bins[col], errors="coerce")

    def nunique_nonblank(s: pd.Series) -> int:
        ss = s.dropna().astype(str)
        ss = ss[(ss != "") & (ss != "nan") & (ss != "<NA>")]
        return int(ss.nunique())

    grouped = bins.groupby("stable_signal_id", dropna=False)
    feat = grouped.agg(
        bin_count=("stable_bin_id", "size"),
        candidate_physical_leg_count=("physical_leg_id", nunique_nonblank),
        carriageway_subbranch_count=("carriageway_subbranch_id", nunique_nonblank),
        stable_travelway_count=("stable_travelway_id", nunique_nonblank),
        source_feature_count=("source_feature_local_fid", nunique_nonblank),
        source_route_count=("source_route_name", nunique_nonblank),
        bins_0_1000=("distance_end_ft", lambda s: int((bins.loc[s.index, "distance_start_ft"].lt(1000) & bins.loc[s.index, "distance_end_ft"].gt(0)).sum())),
        bins_1000_2500=("distance_end_ft", lambda s: int((bins.loc[s.index, "distance_start_ft"].lt(2500) & bins.loc[s.index, "distance_end_ft"].gt(1000)).sum())),
    ).reset_index()
    qa_by_signal = (
        bins.groupby("stable_signal_id")["qa_flags"]
        .apply(lambda s: ";".join(sorted(set(";".join(s.dropna().astype(str)).split(";")) - {""})))
        .reset_index(name="bin_qa_flags")
    )
    feat = feat.merge(qa_by_signal, on="stable_signal_id", how="left")
    out = signals.merge(feat, on="stable_signal_id", how="left")
    numeric = [
        "bin_count",
        "candidate_physical_leg_count",
        "carriageway_subbranch_count",
        "stable_travelway_count",
        "source_feature_count",
        "source_route_count",
        "bins_0_1000",
        "bins_1000_2500",
    ]
    out[numeric] = out[numeric].fillna(0).astype(int)
    sig_level = pd.to_numeric(out.get("signal_level_physical_leg_count", pd.Series(pd.NA, index=out.index)), errors="coerce")
    out["current_physical_leg_count"] = out["candidate_physical_leg_count"]
    use_fallback = (out["current_physical_leg_count"] <= 0) & sig_level.notna()
    out.loc[use_fallback, "current_physical_leg_count"] = sig_level[use_fallback].astype(int)
    out["current_physical_leg_bucket"] = out["current_physical_leg_count"].map(leg_bucket)
    out["subbranch_ratio"] = (
        out["carriageway_subbranch_count"] / out["current_physical_leg_count"].replace({0: pd.NA})
    ).fillna(0)
    return out


def merge_prior_evidence(features: pd.DataFrame) -> pd.DataFrame:
    expected = read_csv(INPUTS["prior_expected_leg"])
    if not expected.empty:
        keep = [
            c
            for c in [
                "source_signal_id_x",
                "source_layer_x",
                "source_line_count",
                "source_bearing_count",
                "source_route_group_count",
                "source_divided_subbranch_count",
                "expected_physical_leg_count",
                "expected_physical_leg_class",
                "expected_intersection_type",
                "missing_physical_leg_count",
                "extra_physical_leg_count",
                "alignment_class",
                "likely_recovery_action",
            ]
            if c in expected.columns
        ]
        expected = expected[keep].drop_duplicates()
        features = features.merge(
            expected,
            left_on="source_signal_id",
            right_on="source_signal_id_x",
            how="left",
            suffixes=("", "_prior_expected"),
        )
    return features


def target_pool(features: pd.DataFrame) -> pd.DataFrame:
    qa = features["qa_flags"].fillna("").astype(str) + ";" + features["bin_qa_flags"].fillna("").astype(str)
    suspicious = features["current_physical_leg_bucket"].isin(["one_leg", "two_leg", "five_plus_leg"])
    compare = features["current_physical_leg_bucket"].isin(["three_leg", "four_leg"]) & qa.str.contains(
        "complex|subbranch|ramp|partial|grade|missing", case=False, na=False
    )
    out = features.loc[suspicious | compare].copy()
    out["target_pool_reason"] = "qa_flagged_three_four_leg_comparison"
    out.loc[features.loc[out.index, "current_physical_leg_bucket"].isin(["one_leg", "two_leg"]), "target_pool_reason"] = (
        "one_two_leg_suspicious"
    )
    out.loc[features.loc[out.index, "current_physical_leg_bucket"].eq("five_plus_leg"), "target_pool_reason"] = (
        "five_plus_suspicious"
    )
    return out


def classify_one_two(row: pd.Series) -> tuple[str, str, str, int]:
    branch = str(row.get("recovery_branch", ""))
    qa = f"{row.get('qa_flags','')};{row.get('bin_qa_flags','')}".lower()
    current = int(row.get("current_physical_leg_count", 0))
    expected = pd.to_numeric(row.get("expected_physical_leg_count", pd.NA), errors="coerce")
    source_bear = pd.to_numeric(row.get("source_bearing_count", pd.NA), errors="coerce")
    route_count = int(row.get("source_route_count", 0))
    tw_count = int(row.get("stable_travelway_count", 0))

    if "ramp_terminal" in branch or "ramp" in qa:
        return ("true_ramp_or_partial_control_signal", "Ramp-terminal/partial-control context is expected; do not force 3/4 legs.", "medium", current)
    if pd.notna(expected) and expected > current:
        return (
            "under_captured_recoverable_source_leg",
            "Prior source-zone expected-leg evidence exceeds current scaffold leg count; label-only estimate is capped at four unless a later source-geometry pass proves true five-plus geometry.",
            "high",
            int(min(expected, 4)),
        )
    if pd.notna(source_bear) and source_bear > current:
        return (
            "nearby_source_leg_not_binned",
            "Prior source bearing evidence exceeds current binned physical-leg count.",
            "medium",
            int(max(current, source_bear)),
        )
    if route_count >= 3 or tw_count >= 3:
        return (
            "offset_anchor_or_intersection_zone_needed",
            "Multiple source Travelway/route identities exist but current physical-leg count is low.",
            "medium",
            max(current, min(4, max(route_count, tw_count))),
        )
    if "missing" in qa or "source_limited" in qa:
        return ("source_travelway_missing_cross_street", "Source-limited or missing-leg QA is already present.", "medium", current)
    if current <= 2 and route_count <= 2 and tw_count <= 2:
        return ("true_source_limited_partial_signal", "Only one/two source Travelway identities are represented in stable lineage.", "medium", current)
    return ("manual_review_needed", "Low leg count cannot be explained from stable lineage alone.", "low", current)


def classify_five_plus(row: pd.Series) -> tuple[str, str, str, int]:
    branch = str(row.get("recovery_branch", ""))
    qa = f"{row.get('qa_flags','')};{row.get('bin_qa_flags','')}".lower()
    current = int(row.get("current_physical_leg_count", 0))
    subbranches = int(row.get("carriageway_subbranch_count", 0))
    routes = int(row.get("source_route_count", 0))
    source_features = int(row.get("source_feature_count", 0))
    expected = pd.to_numeric(row.get("expected_physical_leg_count", pd.NA), errors="coerce")

    if pd.notna(expected) and expected < current:
        return (
            "over_split_carriageway_subbranches",
            "Prior expected-leg model is lower than current binned physical-leg count.",
            "high",
            int(expected),
        )
    if "connector_internal_segment" in qa or "connector" in qa:
        return (
            "connector_internal_segments_counted_as_legs",
            "Connector/internal-segment QA suggests rows should support geometry but not independent physical-leg counts.",
            "medium",
            max(4, min(current, routes if routes > 0 else current)),
        )
    if subbranches >= current or subbranches >= 6:
        return (
            "over_split_carriageway_subbranches",
            "Subbranch count is high relative to physical-leg count; likely divided carriageway/source-row split.",
            "medium",
            max(4, min(current, routes if routes >= 3 else 4)),
        )
    if source_features > current * 2:
        return (
            "source_line_split_same_physical_leg",
            "Many source feature rows support fewer physical approaches.",
            "medium",
            max(4, min(current, routes if routes >= 3 else 4)),
        )
    if "complex_multisignal" in branch or "complex" in qa:
        return (
            "complex_but_valid_multi_branch_signal",
            "Complex branch/calibration says high row count can be valid but should carry QA.",
            "medium",
            current,
        )
    if "ramp_terminal" in branch or "ramp" in qa:
        return (
            "true_complex_five_plus_possible",
            "Ramp-terminal/subbranch context can legitimately produce many modeled branches.",
            "medium",
            current,
        )
    return ("manual_review_needed", "Five-plus count lacks enough diagnostic evidence for label-only normalization.", "low", current)


def build_details(targets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    one_two = targets[targets["current_physical_leg_bucket"].isin(["one_leg", "two_leg"])].copy()
    five = targets[targets["current_physical_leg_bucket"].eq("five_plus_leg")].copy()
    if not one_two.empty:
        vals = one_two.apply(classify_one_two, axis=1, result_type="expand")
        one_two[
            [
                "one_two_leg_recoverability_class",
                "classification_reason",
                "leg_recovery_confidence",
                "estimated_leg_count_after_recovery",
            ]
        ] = vals
    if not five.empty:
        vals = five.apply(classify_five_plus, axis=1, result_type="expand")
        five[
            [
                "five_plus_normalization_class",
                "classification_reason",
                "leg_recovery_confidence",
                "estimated_leg_count_after_normalization",
            ]
        ] = vals

    proposal_rows = []
    for _, row in one_two.iterrows():
        status = row["one_two_leg_recoverability_class"]
        corrected = int(row["estimated_leg_count_after_recovery"])
        proposal_rows.append(
            {
                "stable_signal_id": row["stable_signal_id"],
                "source_signal_id": row.get("source_signal_id"),
                "recovery_branch": row.get("recovery_branch"),
                "current_physical_leg_count": row["current_physical_leg_count"],
                "corrected_estimated_physical_leg_count": corrected,
                "leg_recovery_status": status,
                "leg_recovery_normalization_rule": "one_two_leg_source_zone_recovery_diagnostic",
                "leg_recovery_confidence": row["leg_recovery_confidence"],
                "corrected_physical_leg_id_rule": "retain_existing_ids_for_existing_bins; generate missing-leg ids only in later scaffold pass",
                "corrected_carriageway_subbranch_id_rule": "preserve_existing_subbranch_ids",
                "review_only": True,
            }
        )
    for _, row in five.iterrows():
        status = row["five_plus_normalization_class"]
        corrected = int(row["estimated_leg_count_after_normalization"])
        proposal_rows.append(
            {
                "stable_signal_id": row["stable_signal_id"],
                "source_signal_id": row.get("source_signal_id"),
                "recovery_branch": row.get("recovery_branch"),
                "current_physical_leg_count": row["current_physical_leg_count"],
                "corrected_estimated_physical_leg_count": corrected,
                "leg_recovery_status": status,
                "leg_recovery_normalization_rule": "five_plus_label_only_subbranch_connector_normalization",
                "leg_recovery_confidence": row["leg_recovery_confidence"],
                "corrected_physical_leg_id_rule": "label-only proposal; do not collapse/delete rows",
                "corrected_carriageway_subbranch_id_rule": "preserve_existing_subbranch_ids",
                "review_only": True,
            }
        )
    proposals = pd.DataFrame(proposal_rows)
    return one_two, five, proposals


def build_source_zone_detail(targets: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "stable_signal_id",
        "source_signal_id",
        "recovery_branch",
        "current_physical_leg_count",
        "current_physical_leg_bucket",
        "bin_count",
        "stable_travelway_count",
        "source_feature_count",
        "source_route_count",
        "carriageway_subbranch_count",
        "source_line_count",
        "source_bearing_count",
        "source_route_group_count",
        "source_divided_subbranch_count",
        "expected_physical_leg_count",
        "missing_physical_leg_count",
        "extra_physical_leg_count",
        "alignment_class",
        "likely_recovery_action",
        "qa_flags",
        "bin_qa_flags",
    ]
    for col in cols:
        if col not in targets.columns:
            targets[col] = pd.NA
    out = targets[cols].copy()
    out["source_zone_evidence_source"] = out["source_line_count"].notna().map(
        {True: "prior_source_zone_expected_leg_output", False: "final_clean_stable_travelway_bin_lineage_proxy"}
    )
    return out


def build_missing_leg_candidates(one_two: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    recoverable = one_two[
        one_two["one_two_leg_recoverability_class"].isin(
            ["under_captured_recoverable_source_leg", "nearby_source_leg_not_binned"]
        )
    ].copy()
    summary = recoverable[
        [
            "stable_signal_id",
            "source_signal_id",
            "recovery_branch",
            "current_physical_leg_count",
            "estimated_leg_count_after_recovery",
            "one_two_leg_recoverability_class",
            "leg_recovery_confidence",
        ]
    ].copy()
    summary["candidate_generation_status"] = "needs_bounded_scaffold_generation_pass"
    summary["reason_candidates_not_generated_here"] = (
        "This diagnostic does not have stable Travelway geometry for absent legs in the final-clean bin table; "
        "source-limited/ambiguous cases are not forced."
    )
    bins = pd.DataFrame(
        columns=[
            "stable_signal_id",
            "source_signal_id",
            "stable_bin_id",
            "stable_travelway_id",
            "source_layer",
            "source_route_id",
            "source_route_name",
            "source_route_common",
            "source_measure_start",
            "source_measure_end",
            "source_feature_local_fid",
            "geometry_hash",
            "lineage_match_method",
            "lineage_confidence",
            "corrected_physical_leg_id",
            "corrected_carriageway_subbranch_id",
            "distance_start_ft",
            "distance_end_ft",
            "distance_band",
            "analysis_window",
            "geometry_wkt",
            "leg_recovery_normalization_rule",
            "leg_recovery_confidence",
            "leg_recovery_status",
            "review_only",
        ]
    )
    return bins, summary


def distribution_from_counts(df: pd.DataFrame, count_col: str, scope: str) -> pd.DataFrame:
    tmp = df[[count_col]].copy()
    tmp["physical_leg_bucket"] = tmp[count_col].fillna(0).astype(int).map(leg_bucket)
    out = tmp["physical_leg_bucket"].value_counts().rename_axis("physical_leg_bucket").reset_index(name="signal_count")
    out["distribution_scenario"] = scope
    out["share"] = (out["signal_count"] / out["signal_count"].sum()).round(4)
    return out


def revised_distribution(features: pd.DataFrame, proposals: pd.DataFrame) -> pd.DataFrame:
    current = distribution_from_counts(features, "current_physical_leg_count", "current_final_clean_summary")
    label_counts = features[["stable_signal_id", "current_physical_leg_count"]].copy()
    prop = proposals[["stable_signal_id", "corrected_estimated_physical_leg_count"]].drop_duplicates()
    label_counts = label_counts.merge(prop, on="stable_signal_id", how="left")
    label_counts["after_label_only_normalization_count"] = label_counts[
        "corrected_estimated_physical_leg_count"
    ].fillna(label_counts["current_physical_leg_count"])
    label_dist = distribution_from_counts(
        label_counts, "after_label_only_normalization_count", "after_label_only_normalization"
    )
    # Candidate generation is intentionally empty in this pass unless stable absent-leg lineage is available.
    candidate_dist = label_dist.copy()
    candidate_dist["distribution_scenario"] = "after_label_normalization_plus_defensible_missing_leg_candidates"
    return pd.concat([current, label_dist, candidate_dist], ignore_index=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[str] = []
    started = datetime.now(timezone.utc)
    log(progress, "Starting final clean universe leg recovery/normalization diagnostic.")

    signals = read_csv(INPUTS["final_signals"])
    bins = read_csv(INPUTS["final_bins"])
    log(progress, f"Loaded final clean universe: {len(signals)} signals, {len(bins)} bins.")

    method_inventory = build_method_inventory()
    features = compute_signal_leg_features(signals, bins)
    features = merge_prior_evidence(features)
    targets = target_pool(features)
    source_zone = build_source_zone_detail(targets)
    one_two, five, proposals = build_details(targets)
    candidate_bins, candidate_summary = build_missing_leg_candidates(one_two)
    revised_dist = revised_distribution(features, proposals)

    remaining = pd.concat(
        [
            one_two.assign(issue_class=one_two.get("one_two_leg_recoverability_class", pd.NA)),
            five.assign(issue_class=five.get("five_plus_normalization_class", pd.NA)),
        ],
        ignore_index=True,
        sort=False,
    )
    remaining_summary = (
        remaining.groupby(["issue_class", "recovery_branch"], dropna=False)
        .size()
        .reset_index(name="signal_count")
        .sort_values(["issue_class", "recovery_branch"])
    )

    target_cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "recovery_branch",
        "clean_universe_component",
        "current_physical_leg_count",
        "current_physical_leg_bucket",
        "target_pool_reason",
        "bin_count",
        "stable_travelway_count",
        "source_feature_count",
        "source_route_count",
        "carriageway_subbranch_count",
        "qa_flags",
        "bin_qa_flags",
    ]
    for col in target_cols:
        if col not in targets.columns:
            targets[col] = pd.NA

    method_inventory.to_csv(OUT_DIR / "leg_recovery_method_inventory.csv", index=False)
    targets[target_cols].to_csv(OUT_DIR / "final_clean_leg_target_pool.csv", index=False)
    source_zone.to_csv(OUT_DIR / "final_clean_source_zone_expected_leg_detail.csv", index=False)
    one_two.to_csv(OUT_DIR / "one_two_leg_recoverability_detail.csv", index=False)
    five.to_csv(OUT_DIR / "five_plus_normalization_detail.csv", index=False)
    proposals.to_csv(OUT_DIR / "corrected_leg_label_proposals.csv", index=False)
    candidate_bins.to_csv(OUT_DIR / "missing_leg_candidate_recovery_bins.csv", index=False)
    candidate_summary.to_csv(OUT_DIR / "missing_leg_candidate_recovery_summary.csv", index=False)
    revised_dist.to_csv(OUT_DIR / "revised_physical_leg_distribution_estimate.csv", index=False)
    remaining_summary.to_csv(OUT_DIR / "remaining_leg_issue_summary.csv", index=False)

    current_counts = features["current_physical_leg_bucket"].value_counts().to_dict()
    revised_counts = (
        revised_dist.loc[revised_dist["distribution_scenario"].eq("after_label_only_normalization")]
        .set_index("physical_leg_bucket")["signal_count"]
        .to_dict()
    )
    one_two_counts = one_two.get("one_two_leg_recoverability_class", pd.Series(dtype=str)).value_counts().to_dict()
    five_counts = five.get("five_plus_normalization_class", pd.Series(dtype=str)).value_counts().to_dict()
    recoverable_missing = int(
        one_two.get("one_two_leg_recoverability_class", pd.Series(dtype=str))
        .isin(["under_captured_recoverable_source_leg", "nearby_source_leg_not_binned"])
        .sum()
    )
    label_normalized = int(len(proposals))

    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to review/current/final_clean_universe_leg_recovery_normalization."),
            ("no_records_promoted", True, "All outputs are proposals/diagnostics."),
            ("no_crash_assignment", True, "Crash records are not read or assigned."),
            ("no_access_assignment", True, "Access records are not read or assigned."),
            ("no_rates_or_models", True, "No rate/model calculations are performed."),
            ("crash_direction_fields_not_used", True, "No crash direction fields are read."),
            ("stable_travelway_id_preserved_on_generated_candidate_bins", True, "No candidate bins were generated without stable Travelway lineage."),
            ("physical_legs_separate_from_subbranches", True, "Corrected physical-leg and carriageway-subbranch rules are separate proposal fields."),
            ("source_limited_cases_not_forced", True, "Missing-leg candidate bins remain empty where absent-leg stable lineage is not defensible."),
            ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/final_clean_universe_leg_recovery_normalization"), str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "notes"],
    )
    qa.to_csv(OUT_DIR / "final_clean_universe_leg_recovery_qa.csv", index=False)

    findings = f"""# Final Clean Universe Leg Recovery Normalization

## Bounded Question

Diagnose implausible physical-leg counts in the 3,719-signal clean review-analysis universe and propose review-only leg recovery/normalization labels. This pass does not modify active outputs, promote records, assign crashes/access, calculate rates/models, or force source-limited cases.

## Findings

1. Applicable prior rules include source-vs-graph intersection-zone comparison, bearing-sector physical-leg grouping, missing source-leg recovery, adjacent-sector merge, source-line split normalization, divided/carriageway subbranch normalization, ramp-terminal subbranch handling, and complex connector/internal segment handling.
2. The high two-leg count is mostly a mixed condition: true ramp/partial-control cases, source-limited/proxy evidence, and under-capture candidates where prior expected/source bearing evidence exceeds current binned legs. Current one/two recoverability classes: `{one_two_counts}`.
3. One-/two-leg source-limited or partial classes are counted in `one_two_leg_recoverability_detail.csv`.
4. **{recoverable_missing:,}** one-/two-leg signals have recoverable missing-leg evidence from prior expected/source-zone outputs or stable lineage proxy evidence.
5. The five-plus count is driven by subbranch/source-row/connector complexity, not necessarily true five-leg intersections. Five-plus classes: `{five_counts}`.
6. Five-plus over-split/subbranch/source-line cases are listed in `five_plus_normalization_detail.csv`.
7. True complex five-plus possible cases remain review-only QA cases rather than forced collapses.
8. Current distribution is `{current_counts}`. Label-only revised distribution is `{revised_counts}`.
9. New missing-leg candidate bins generated in this pass: **{len(candidate_bins):,}**. Candidate generation is deferred when absent-leg stable Travelway geometry is not already defensible in final-clean lineage.
10. Next pass should create a bounded source-Travelway geospatial candidate-generation package for the recoverable one/two-leg queue, then context-refresh those candidates before any integration. Label-only five-plus normalization can be carried into meeting tables immediately as QA, not as row deletion/collapse.

## Notes

The final-clean bin table preserves stable Travelway lineage but does not contain full source-zone geometry for absent legs. This diagnostic therefore proposes labels and queues missing-leg candidates instead of fabricating new bins.
"""
    (OUT_DIR / "final_clean_universe_leg_recovery_findings.md").write_text(findings, encoding="utf-8")

    manifest = {
        "script": "src/active/roadway_graph/final_clean_universe_leg_recovery_normalization.py",
        "created_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "inputs": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in INPUTS.items() if v.exists()},
        "outputs": [
            "leg_recovery_method_inventory.csv",
            "final_clean_leg_target_pool.csv",
            "final_clean_source_zone_expected_leg_detail.csv",
            "one_two_leg_recoverability_detail.csv",
            "five_plus_normalization_detail.csv",
            "corrected_leg_label_proposals.csv",
            "missing_leg_candidate_recovery_bins.csv",
            "missing_leg_candidate_recovery_summary.csv",
            "revised_physical_leg_distribution_estimate.csv",
            "remaining_leg_issue_summary.csv",
            "final_clean_universe_leg_recovery_findings.md",
            "final_clean_universe_leg_recovery_qa.csv",
            "final_clean_universe_leg_recovery_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "final_clean_signals": int(len(signals)),
            "final_clean_bins": int(len(bins)),
            "target_pool_signals": int(len(targets)),
            "one_two_leg_targets": int(len(one_two)),
            "five_plus_targets": int(len(five)),
            "label_proposals": int(label_normalized),
            "recoverable_missing_leg_signals": int(recoverable_missing),
            "generated_missing_leg_candidate_bins": int(len(candidate_bins)),
        },
        "non_goals_confirmed": [
            "no_speed_aadt_rerun",
            "no_access_assignment",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_active_outputs_modified",
            "no_promotion",
        ],
    }
    (OUT_DIR / "final_clean_universe_leg_recovery_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    log(progress, "Wrote final clean universe leg recovery/normalization outputs.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
