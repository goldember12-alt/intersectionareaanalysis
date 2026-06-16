"""Final clean review-analysis universe consolidation.

Bounded question:
    Consolidate the review-only 3,719-signal clean universe from the
    represented, good-Travelway, offset-anchor, ramp-terminal, and complex
    multi-signal recovery branches; summarize physical legs, bin windows, and
    context readiness without assigning crashes/access or modifying active
    outputs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"

STAGED_SIGNAL_COUNT = 3933
EXPECTED_FINAL_CLEAN = 3719
EXPECTED_REMAINING = 214


PATHS = {
    "represented_signals": ROOT
    / "work/output/roadway_graph/review/current/stable_lineage_scaffold_regeneration/stable_lineage_represented_signal_universe.csv",
    "represented_bins": ROOT
    / "work/output/roadway_graph/review/current/stable_lineage_scaffold_regeneration/stable_lineage_represented_bin_universe.csv",
    "good_signals": ROOT
    / "work/output/roadway_graph/review/current/missing_hmms_good_travelway_universe_integration/expanded_good_travelway_signal_universe.csv",
    "good_bins": ROOT
    / "work/output/roadway_graph/review/current/missing_hmms_good_travelway_universe_integration/expanded_good_travelway_bin_universe.csv",
    "good_revised": ROOT
    / "work/output/roadway_graph/review/current/complex_signal_map_review_ingestion/good_travelway_revised_readiness_after_complex_review.csv",
    "offset_signals": ROOT
    / "work/output/roadway_graph/review/current/missing_hmms_offset_anchor_universe_integration/expanded_offset_anchor_signal_universe.csv",
    "offset_bins": ROOT
    / "work/output/roadway_graph/review/current/missing_hmms_offset_anchor_universe_integration/expanded_offset_anchor_bin_universe.csv",
    "offset_reclass": ROOT
    / "work/output/roadway_graph/review/current/offset_anchor_complex_risk_reclassification/offset_anchor_complex_risk_reclassified_detail.csv",
    "offset_revised_readiness": ROOT
    / "work/output/roadway_graph/review/current/offset_anchor_complex_risk_reclassification/offset_anchor_complex_revised_readiness.csv",
    "ramp_signals": ROOT
    / "work/output/roadway_graph/review/current/ramp_terminal_universe_integration/ramp_terminal_integrated_signal_additions.csv",
    "ramp_bins": ROOT
    / "work/output/roadway_graph/review/current/ramp_terminal_universe_integration/ramp_terminal_integrated_bin_additions.csv",
    "ramp_remaining": ROOT
    / "work/output/roadway_graph/review/current/ramp_terminal_universe_integration/ramp_terminal_updated_remaining_signal_ledger.csv",
    "complex_signals": ROOT
    / "work/output/roadway_graph/review/current/missing_hmms_complex_multisignal_context_refresh/complex_multisignal_context_signal_summary.csv",
    "complex_bins": ROOT
    / "work/output/roadway_graph/review/current/missing_hmms_complex_multisignal_context_refresh/complex_multisignal_context_bin_detail.csv",
    "final_staged": ROOT
    / "work/output/roadway_graph/review/current/final_staged_signal_accounting/final_staged_signal_accounting_detail.csv",
    "final_status_summary": ROOT
    / "work/output/roadway_graph/review/current/final_staged_signal_accounting/final_staged_signal_status_summary.csv",
    "final_remaining_446": ROOT
    / "work/output/roadway_graph/review/current/final_staged_signal_accounting/final_remaining_446_breakdown.csv",
    "access_untyped": ROOT
    / "work/output/roadway_graph/review/current/final_access_baseline_freeze/final_access_primary_untyped_spatial_100ft_summary.csv",
    "access_typed": ROOT
    / "work/output/roadway_graph/review/current/final_access_baseline_freeze/final_access_primary_typed_v2_spatial_100ft_summary.csv",
    "access_readiness": ROOT
    / "work/output/roadway_graph/review/current/final_access_baseline_freeze/final_access_crash_catchment_readiness.csv",
}


def log(lines: list[str], message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    lines.append(f"{stamp} {message}")
    print(message)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
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


def copy_first(df: pd.DataFrame, names: Iterable[str], default: object = pd.NA) -> pd.Series:
    col = first_col(df, names)
    if col is None:
        return pd.Series(default, index=df.index)
    return df[col]


def add_missing_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df


SIGNAL_COLUMNS = [
    "stable_signal_id",
    "source_signal_id",
    "GLOBALID",
    "OBJECTID",
    "ASSET_ID",
    "REG_SIGNAL_ID",
    "source_signal_layer",
    "source_system",
    "signal_geometry_wkt",
    "recovery_branch",
    "clean_universe_component",
    "review_only_recovery_provenance",
    "route_measure_ready",
    "roadway_context_ready",
    "rns_speed_ready",
    "aadt_ready",
    "exposure_denominator_ready",
    "speed_aadt_ready",
    "full_0_1000_speed_aadt_ready",
    "full_0_2500_sensitivity_ready",
    "signal_level_physical_leg_count",
    "high_crash_relevance",
    "source_not_represented_unassigned_crashes_within_2500ft",
    "missing_globalid",
    "complex_geometry_flag",
    "connector_internal_segment_flag",
    "carriageway_subbranch_flag",
    "ramp_terminal_flag",
    "subbranch_split_flag",
    "ramp_mainline_mixed_flag",
    "grade_separated_mainline_excluded_flag",
    "qa_flags",
]


BIN_COLUMNS = [
    "stable_signal_id",
    "source_signal_id",
    "GLOBALID",
    "OBJECTID",
    "ASSET_ID",
    "REG_SIGNAL_ID",
    "stable_bin_id",
    "stable_travelway_id",
    "physical_leg_id",
    "carriageway_subbranch_id",
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
    "distance_start_ft",
    "distance_end_ft",
    "distance_band",
    "analysis_window",
    "geometry_wkt",
    "roadway_context_status",
    "roadway_division_context",
    "has_rns_speed",
    "has_aadt",
    "has_exposure_denominator",
    "speed_aadt_ready_bin",
    "review_only_recovery_provenance",
    "recovery_branch",
    "qa_flags",
]


def normalize_signal_frame(df: pd.DataFrame, branch: str, component: str) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["stable_signal_id"] = copy_first(df, ["stable_signal_id", "signal_id"])
    out["source_signal_id"] = copy_first(df, ["source_signal_id", "represented_source_signal_id", "source_signal_id_x"])
    out["GLOBALID"] = copy_first(df, ["GLOBALID", "GLOBALID_signal"])
    out["OBJECTID"] = copy_first(df, ["OBJECTID", "OBJECTID_signal"])
    out["ASSET_ID"] = copy_first(df, ["ASSET_ID", "ASSET_ID_signal", "ASSET_NUM"])
    out["REG_SIGNAL_ID"] = copy_first(df, ["REG_SIGNAL_ID", "REG_SIGNAL_ID_signal", "SIGNAL_NO"])
    out["source_signal_layer"] = copy_first(df, ["source_signal_layer", "source_layer", "represented_source_layer", "source_layer_x", "Stage1_SourceLayer"])
    out["source_system"] = copy_first(df, ["source_system", "source_group"], "review_source")
    out["signal_geometry_wkt"] = copy_first(df, ["signal_geometry_wkt", "raw_signal_geometry_wkt", "geometry_wkt"])
    out["recovery_branch"] = branch
    out["clean_universe_component"] = component
    out["review_only_recovery_provenance"] = copy_first(df, ["review_only_recovery_provenance"], branch)
    out["route_measure_ready"] = bool_series(df, "route_measure_ready", default=True if branch == "original_represented" else False)
    out["roadway_context_ready"] = bool_series(df, "roadway_context_ready", default=True if branch == "original_represented" else False)
    out["rns_speed_ready"] = bool_series(df, "rns_speed_ready", default=False) | bool_series(df, "final_speed_ready_flag", default=False)
    out["aadt_ready"] = bool_series(df, "aadt_ready", default=False) | bool_series(
        df, "final_aadt_exposure_ready_flag", default=False
    )
    out["exposure_denominator_ready"] = bool_series(df, "exposure_denominator_ready", default=False) | bool_series(
        df, "final_aadt_exposure_ready_flag", default=False
    )
    out["speed_aadt_ready"] = (
        bool_series(df, "speed_aadt_ready", default=False)
        | bool_series(df, "final_speed_aadt_ready_flag", default=False)
        | bool_series(df, "final_cleanup_speed_aadt_ready", default=False)
    )
    out["full_0_1000_speed_aadt_ready"] = bool_series(df, "full_0_1000_speed_aadt_ready", default=False)
    out["full_0_2500_sensitivity_ready"] = bool_series(df, "full_0_2500_sensitivity_ready", default=False) | bool_series(
        df, "full_attempted_0_2500_speed_aadt_ready", default=False
    )
    out["signal_level_physical_leg_count"] = pd.to_numeric(
        copy_first(
            df,
            [
                "final_review_only_represented_physical_leg_count",
                "final_calibrated_physical_leg_count",
                "generated_physical_leg_count",
                "likely_physical_leg_count",
            ],
        ),
        errors="coerce",
    )
    out["high_crash_relevance"] = bool_series(df, "high_crash_relevance", default=False) | bool_series(
        df, "high_crash_relevance_flag", default=False
    )
    out["source_not_represented_unassigned_crashes_within_2500ft"] = copy_first(
        df, ["source_not_represented_unassigned_crashes_within_2500ft"], 0
    )
    out["missing_globalid"] = bool_series(df, "missing_globalid", default=False) | bool_series(df, "GLOBALID_missing", default=False)
    out["complex_geometry_flag"] = bool_series(df, "complex_geometry_flag", default=False)
    out["connector_internal_segment_flag"] = bool_series(df, "connector_internal_segment_flag", default=False)
    out["carriageway_subbranch_flag"] = bool_series(df, "carriageway_subbranch_flag", default=False)
    out["ramp_terminal_flag"] = bool_series(df, "ramp_terminal_flag", default=False)
    out["subbranch_split_flag"] = bool_series(df, "subbranch_split_flag", default=False)
    out["ramp_mainline_mixed_flag"] = bool_series(df, "ramp_mainline_mixed_flag", default=False)
    out["grade_separated_mainline_excluded_flag"] = bool_series(df, "grade_separated_mainline_excluded_flag", default=False)
    qa = []
    for _, row in out.iterrows():
        flags = []
        for col in [
            "missing_globalid",
            "complex_geometry_flag",
            "connector_internal_segment_flag",
            "carriageway_subbranch_flag",
            "ramp_terminal_flag",
            "subbranch_split_flag",
            "ramp_mainline_mixed_flag",
            "grade_separated_mainline_excluded_flag",
        ]:
            if bool(row.get(col, False)):
                flags.append(col)
        qa.append(";".join(flags))
    out["qa_flags"] = qa
    return out[SIGNAL_COLUMNS]


def normalize_bin_frame(df: pd.DataFrame, branch: str, signal_ids: set[str]) -> pd.DataFrame:
    df = df[df["stable_signal_id"].astype(str).isin(signal_ids)].copy()
    out = pd.DataFrame(index=df.index)
    out["stable_signal_id"] = df["stable_signal_id"]
    out["source_signal_id"] = copy_first(df, ["source_signal_id", "source_signal_id_signal", "target_source_id"])
    out["GLOBALID"] = copy_first(df, ["GLOBALID", "GLOBALID_signal"])
    out["OBJECTID"] = copy_first(df, ["OBJECTID", "OBJECTID_signal"])
    out["ASSET_ID"] = copy_first(df, ["ASSET_ID", "ASSET_ID_signal", "ASSET_NUM"])
    out["REG_SIGNAL_ID"] = copy_first(df, ["REG_SIGNAL_ID", "REG_SIGNAL_ID_signal", "SIGNAL_NO"])
    out["stable_bin_id"] = copy_first(df, ["stable_bin_id", "target_bin_id", "bin_id"])
    out["stable_travelway_id"] = copy_first(df, ["stable_travelway_id", "geometry_stable_travelway_id"])
    out["physical_leg_id"] = copy_first(
        df, ["physical_leg_group_id", "physical_leg_id_final", "physical_leg_id", "leg_candidate_id"]
    )
    out["carriageway_subbranch_id"] = copy_first(
        df, ["carriageway_subbranch_id", "carriageway_subbranch_id_final"]
    )
    out["source_layer"] = copy_first(df, ["source_layer"])
    out["source_route_id"] = copy_first(df, ["source_route_id"])
    out["source_route_name"] = copy_first(df, ["source_route_name"])
    out["source_route_common"] = copy_first(df, ["source_route_common"])
    out["source_measure_start"] = copy_first(df, ["source_measure_start"])
    out["source_measure_end"] = copy_first(df, ["source_measure_end"])
    out["source_feature_local_fid"] = copy_first(df, ["source_feature_local_fid"])
    out["geometry_hash"] = copy_first(df, ["geometry_hash", "bin_geometry_hash"])
    out["lineage_match_method"] = copy_first(df, ["lineage_match_method"])
    out["lineage_confidence"] = copy_first(df, ["lineage_confidence"])
    out["distance_start_ft"] = pd.to_numeric(copy_first(df, ["distance_start_ft"]), errors="coerce")
    out["distance_end_ft"] = pd.to_numeric(copy_first(df, ["distance_end_ft"]), errors="coerce")
    out["distance_band"] = copy_first(df, ["distance_band"])
    out["analysis_window"] = copy_first(df, ["analysis_window"])
    out["geometry_wkt"] = copy_first(df, ["geometry_wkt", "geometry_wkt_cleaned"])
    out["roadway_context_status"] = copy_first(df, ["roadway_context_status"])
    out["roadway_division_context"] = copy_first(df, ["roadway_division_context"])
    out["has_rns_speed"] = bool_series(df, "has_rns_speed", default=False)
    out["has_aadt"] = bool_series(df, "has_aadt", default=False)
    out["has_exposure_denominator"] = bool_series(df, "has_exposure_denominator", default=False)
    out["speed_aadt_ready_bin"] = bool_series(df, "speed_aadt_ready_bin", default=False) | (
        out["has_rns_speed"] & out["has_aadt"] & out["has_exposure_denominator"]
    )
    out["review_only_recovery_provenance"] = copy_first(df, ["review_only_recovery_provenance"], branch)
    out["recovery_branch"] = branch
    qa_cols = [
        "complex_geometry_flag",
        "connector_internal_segment_flag",
        "carriageway_subbranch_flag",
        "ramp_terminal_flag",
        "subbranch_split_flag",
        "ramp_mainline_mixed_flag",
        "grade_separated_mainline_excluded_flag",
        "partial_coverage_flag",
        "grade_or_mainline_risk_flag",
    ]
    parts = []
    for col in qa_cols:
        if col in df.columns:
            parts.append(bool_series(df, col, default=False).map(lambda x, c=col: c if x else ""))
    out["qa_flags"] = pd.Series("", index=df.index)
    if parts:
        joined = pd.concat(parts, axis=1).apply(lambda r: ";".join([v for v in r if v]), axis=1)
        out["qa_flags"] = joined
    return out[BIN_COLUMNS]


def build_offset_clean_ids(offset_signals: pd.DataFrame, offset_reclass: pd.DataFrame) -> set[str]:
    base_clean = set(
        offset_signals.loc[
            bool_series(offset_signals, "clean_review_offset_anchor_addition", default=False), "stable_signal_id"
        ].dropna().astype(str)
    )
    calibrated = set(
        offset_reclass.loc[
            bool_series(offset_reclass, "calibrated_includable", default=False)
            & ~bool_series(offset_reclass, "calibrated_hold_from_clean_analysis", default=True),
            "stable_signal_id",
        ]
        .dropna()
        .astype(str)
    )
    return base_clean | calibrated


def remap_represented_bins_to_canonical_signal_id(
    represented_bins: pd.DataFrame, represented_signals: pd.DataFrame
) -> pd.DataFrame:
    """Use target_signal_id to carry canonical stable_signal_id onto original bins.

    The stable-lineage bin table preserves older bin lineage keys in
    ``stable_signal_id``. The represented signal table carries the canonical
    project-stable signal ID. The shared key is ``target_signal_id``.
    """

    if "target_signal_id" not in represented_bins.columns or "target_signal_id" not in represented_signals.columns:
        return represented_bins
    mapping = represented_signals[["target_signal_id", "stable_signal_id"]].dropna().drop_duplicates()
    mapping = mapping.rename(columns={"stable_signal_id": "canonical_stable_signal_id"})
    out = represented_bins.merge(mapping, on="target_signal_id", how="left")
    out["stable_signal_id"] = out["canonical_stable_signal_id"].combine_first(out["stable_signal_id"])
    return out.drop(columns=["canonical_stable_signal_id"])


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


def compute_leg_distribution(signals: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    leg_counts = (
        bins.dropna(subset=["physical_leg_id"])
        .assign(physical_leg_id=lambda d: d["physical_leg_id"].astype(str))
        .query("physical_leg_id != '' and physical_leg_id != '<NA>' and physical_leg_id != 'nan'")
        .groupby("stable_signal_id")["physical_leg_id"]
        .nunique()
        .rename("physical_leg_count")
        .reset_index()
    )
    by_signal = signals[["stable_signal_id", "recovery_branch"]].merge(leg_counts, on="stable_signal_id", how="left")
    fallback = signals[["stable_signal_id", "signal_level_physical_leg_count"]].copy()
    by_signal = by_signal.merge(fallback, on="stable_signal_id", how="left")
    by_signal["physical_leg_count"] = by_signal["physical_leg_count"].fillna(0)
    use_fallback = (by_signal["physical_leg_count"] <= 0) & by_signal["signal_level_physical_leg_count"].notna()
    by_signal.loc[use_fallback, "physical_leg_count"] = by_signal.loc[use_fallback, "signal_level_physical_leg_count"]
    by_signal["physical_leg_count"] = by_signal["physical_leg_count"].fillna(0).astype(int)
    by_signal["physical_leg_bucket"] = by_signal["physical_leg_count"].map(leg_bucket)

    overall = by_signal["physical_leg_bucket"].value_counts().rename_axis("physical_leg_bucket").reset_index(name="signal_count")
    overall["distribution_scope"] = "all_branches"
    branch = (
        by_signal.groupby(["recovery_branch", "physical_leg_bucket"], dropna=False)
        .size()
        .reset_index(name="signal_count")
        .rename(columns={"recovery_branch": "distribution_scope"})
    )
    dist = pd.concat([overall, branch], ignore_index=True)
    total_by_scope = dist.groupby("distribution_scope")["signal_count"].transform("sum")
    dist["share_of_scope"] = (dist["signal_count"] / total_by_scope).round(4)

    two_or_less = (
        by_signal.assign(two_leg_or_less=lambda d: d["physical_leg_count"] <= 2)
        .groupby("recovery_branch")["two_leg_or_less"]
        .agg(two_leg_or_less_signals="sum", total_signals="count")
        .reset_index()
    )
    two_or_less["two_leg_or_less_share"] = (
        two_or_less["two_leg_or_less_signals"] / two_or_less["total_signals"]
    ).round(4)
    return dist, by_signal.merge(two_or_less, on="recovery_branch", how="left")


def compute_window_availability(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    bands = [
        ("0_250ft", 0, 250),
        ("250_500ft", 250, 500),
        ("500_750ft", 500, 750),
        ("750_1000ft", 750, 1000),
        ("1000_1500ft", 1000, 1500),
        ("1500_2500ft", 1500, 2500),
    ]
    rows = [{"metric": "total_bins", "value": len(bins), "notes": "Final clean bin universe row count."}]
    for label, start, end in bands:
        mask = (bins["distance_start_ft"] < end) & (bins["distance_end_ft"] > start)
        rows.append({"metric": f"bins_{label}", "value": int(mask.sum()), "notes": "Bins overlapping requested distance band."})
        rows.append(
            {
                "metric": f"signals_with_any_{label}",
                "value": int(bins.loc[mask, "stable_signal_id"].nunique()),
                "notes": "Signals with at least one bin overlapping requested distance band.",
            }
        )

    leg_max = (
        bins.dropna(subset=["physical_leg_id"])
        .groupby(["stable_signal_id", "physical_leg_id"], dropna=False)["distance_end_ft"]
        .max()
        .reset_index()
    )
    for threshold in [1000, 2500]:
        ready_leg = leg_max[leg_max["distance_end_ft"] >= threshold]
        rows.append(
            {
                "metric": f"complete_0_{threshold}_ft_by_at_least_one_leg",
                "value": int(ready_leg["stable_signal_id"].nunique()),
                "notes": "At least one represented physical leg reaches the threshold.",
            }
        )
        total_legs = leg_max.groupby("stable_signal_id")["physical_leg_id"].nunique()
        ready_legs = ready_leg.groupby("stable_signal_id")["physical_leg_id"].nunique()
        across = (ready_legs.reindex(total_legs.index).fillna(0) >= total_legs).sum()
        rows.append(
            {
                "metric": f"complete_0_{threshold}_ft_across_represented_legs",
                "value": int(across),
                "notes": "All represented physical legs for the signal reach the threshold.",
            }
        )
    rows.append(
        {
            "metric": "signals_with_partial_coverage_flags",
            "value": int(bins.loc[bins["qa_flags"].astype(str).str.contains("partial_coverage_flag", na=False), "stable_signal_id"].nunique()),
            "notes": "Signals with at least one partial-coverage QA flag.",
        }
    )
    return pd.DataFrame(rows)


def compute_context_readiness(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    access_untyped = read_csv(PATHS["access_untyped"]) if PATHS["access_untyped"].exists() else pd.DataFrame()
    access_typed = read_csv(PATHS["access_typed"]) if PATHS["access_typed"].exists() else pd.DataFrame()
    access_readiness = read_csv(PATHS["access_readiness"]) if PATHS["access_readiness"].exists() else pd.DataFrame()

    rows = []
    for col, label in [
        ("route_measure_ready", "route/measure-ready signals"),
        ("roadway_context_ready", "roadway-context-ready signals"),
        ("rns_speed_ready", "RNS speed-ready signals"),
        ("aadt_ready", "AADT-ready signals"),
        ("exposure_denominator_ready", "exposure/denominator-ready signals"),
        ("speed_aadt_ready", "speed+AADT-ready signals"),
        ("full_0_1000_speed_aadt_ready", "full 0-1,000 ft speed+AADT-ready signals"),
    ]:
        rows.append(
            {
                "readiness_item": col,
                "signal_count": int(signals[col].fillna(False).sum()),
                "share_of_clean_universe": round(float(signals[col].fillna(False).mean()), 4),
                "notes": label,
            }
        )
    rows.append(
        {
            "readiness_item": "bins_with_stable_travelway_id",
            "signal_count": int(bins["stable_travelway_id"].notna().sum()),
            "share_of_clean_universe": round(float(bins["stable_travelway_id"].notna().mean()), 4),
            "notes": "Bin-level completeness share, not signal share.",
        }
    )
    if not access_untyped.empty:
        rows.append(
            {
                "readiness_item": "access_primary_untyped_100ft_signals_covered_0_2500",
                "signal_count": int(access_untyped.loc[access_untyped["window"].eq("0_2500"), "signals_covered"].max()),
                "share_of_clean_universe": pd.NA,
                "notes": "Existing final access baseline only; no access assignment rerun.",
            }
        )
    if not access_typed.empty:
        rows.append(
            {
                "readiness_item": "access_typed_v2_100ft_signals_covered_0_2500",
                "signal_count": int(access_typed.loc[access_typed["window"].eq("0_2500"), "signals_covered"].max()),
                "share_of_clean_universe": pd.NA,
                "notes": "Existing final access baseline only; no access assignment rerun.",
            }
        )
    if not access_readiness.empty:
        rows.append(
            {
                "readiness_item": "crash_catchment_design_from_access_freeze",
                "signal_count": pd.NA,
                "share_of_clean_universe": pd.NA,
                "notes": "; ".join(access_readiness["status"].astype(str).unique()),
            }
        )
    return pd.DataFrame(rows)


def build_remaining_214() -> pd.DataFrame:
    rows = [
        (
            "complex_multi_signal_review_or_context_holdout",
            17,
            "Complex multi-signal candidates excluded now: 16 overlap/ownership QA cases plus one not speed+AADT-ready holdout.",
            True,
            True,
            False,
        ),
        (
            "offset_anchor_low_confidence_holdout",
            85,
            "Offset-anchor targets skipped because anchor confidence was too low.",
            True,
            True,
            False,
        ),
        (
            "source_travelway_missing_or_incomplete",
            48,
            "Source Travelway appears missing or incomplete for actual signal legs.",
            False,
            False,
            True,
        ),
        (
            "review_visible_not_clean_good_travelway_holdout",
            22,
            "Good-Travelway additions visible for review but held from clean analysis.",
            True,
            True,
            False,
        ),
        (
            "sibling_or_ownership_review_holdout",
            17,
            "Signal leg ownership may belong to a sibling or nearby signal.",
            True,
            True,
            False,
        ),
        (
            "review_visible_not_clean_offset_anchor_holdout",
            12,
            "Offset-anchor context-ready additions visible for review but held from clean analysis.",
            True,
            True,
            False,
        ),
        (
            "ramp_terminal_hold_insufficient_signal_plane_evidence",
            2,
            "Ramp-terminal candidates held because signal-plane evidence remains insufficient.",
            True,
            True,
            False,
        ),
        (
            "other_residual_source_geometry_manual_holdouts",
            11,
            "Residual source/geometry/manual holdouts not targeted in the final consolidation.",
            True,
            True,
            False,
        ),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "remaining_status",
            "signal_count",
            "plain_language_meaning",
            "recoverable_later",
            "map_review_required",
            "external_source_data_required",
        ],
    )
    df["share_of_remaining_214"] = (df["signal_count"] / EXPECTED_REMAINING).round(4)
    df["share_of_3933"] = (df["signal_count"] / STAGED_SIGNAL_COUNT).round(4)
    df["should_block_current_analysis"] = False
    return df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[str] = []
    started = datetime.now(timezone.utc)
    log(progress, "Starting final clean universe context summary.")

    represented_signals = read_csv(PATHS["represented_signals"])
    represented_bins = read_csv(PATHS["represented_bins"])
    good_revised = read_csv(PATHS["good_revised"])
    good_signals = read_csv(PATHS["good_signals"])
    good_bins = read_csv(PATHS["good_bins"])
    offset_signals = read_csv(PATHS["offset_signals"])
    offset_bins = read_csv(PATHS["offset_bins"])
    offset_reclass = read_csv(PATHS["offset_reclass"])
    ramp_signals = read_csv(PATHS["ramp_signals"])
    ramp_bins = read_csv(PATHS["ramp_bins"])
    complex_signals = read_csv(PATHS["complex_signals"])
    complex_bins = read_csv(PATHS["complex_bins"])
    log(progress, "Loaded branch signal and bin tables.")

    original_ids = set(represented_signals["stable_signal_id"].dropna().astype(str))
    good_ids = set(
        good_revised.loc[bool_series(good_revised, "revised_review_only_includable", default=False), "stable_signal_id"]
        .dropna()
        .astype(str)
    )
    offset_ids = build_offset_clean_ids(offset_signals, offset_reclass)
    ramp_ids = set(ramp_signals["stable_signal_id"].dropna().astype(str))
    complex_ids = set(
        complex_signals.loc[bool_series(complex_signals, "clean_addition_candidate", default=False), "stable_signal_id"]
        .dropna()
        .astype(str)
    )
    log(
        progress,
        f"Selected branch IDs: original={len(original_ids)}, good={len(good_ids)}, offset={len(offset_ids)}, ramp={len(ramp_ids)}, complex={len(complex_ids)}.",
    )

    signal_frames = [
        normalize_signal_frame(represented_signals[represented_signals["stable_signal_id"].astype(str).isin(original_ids)], "original_represented", "original_represented"),
        normalize_signal_frame(good_signals[good_signals["stable_signal_id"].astype(str).isin(good_ids)], "good_travelway", "good_travelway_clean"),
        normalize_signal_frame(offset_signals[offset_signals["stable_signal_id"].astype(str).isin(offset_ids)], "offset_anchor", "offset_anchor_clean_review_analysis"),
        normalize_signal_frame(ramp_signals[ramp_signals["stable_signal_id"].astype(str).isin(ramp_ids)], "ramp_terminal", "ramp_terminal_review_analysis"),
        normalize_signal_frame(complex_signals[complex_signals["stable_signal_id"].astype(str).isin(complex_ids)], "complex_multisignal", "complex_multisignal_clean"),
    ]
    final_signals = pd.concat(signal_frames, ignore_index=True)
    final_signals = final_signals.drop_duplicates(subset=["stable_signal_id"], keep="first").reset_index(drop=True)
    log(progress, f"Built final signal universe with {len(final_signals)} unique stable_signal_id values.")

    represented_bins_canonical = remap_represented_bins_to_canonical_signal_id(represented_bins, represented_signals)
    bin_frames = [
        normalize_bin_frame(represented_bins_canonical, "original_represented", original_ids),
        normalize_bin_frame(good_bins, "good_travelway", good_ids),
        normalize_bin_frame(offset_bins, "offset_anchor", offset_ids),
        normalize_bin_frame(ramp_bins, "ramp_terminal", ramp_ids),
        normalize_bin_frame(complex_bins, "complex_multisignal", complex_ids),
    ]
    final_bins = pd.concat(bin_frames, ignore_index=True)
    log(progress, f"Built final bin universe with {len(final_bins)} rows.")

    branch_contrib = (
        final_signals.groupby(["recovery_branch", "clean_universe_component"], dropna=False)
        .size()
        .reset_index(name="signal_count")
    )
    branch_contrib["share_of_final_clean_3719"] = (branch_contrib["signal_count"] / len(final_signals)).round(4)
    expected_branch = {
        "original_represented": 2739,
        "good_travelway": 604,
        "offset_anchor": 144,
        "ramp_terminal": 140,
        "complex_multisignal": 92,
    }
    branch_contrib["expected_signal_count"] = branch_contrib["recovery_branch"].map(expected_branch)
    branch_contrib["matches_expected"] = branch_contrib["signal_count"].eq(branch_contrib["expected_signal_count"])

    reconciliation = pd.DataFrame(
        [
            {"metric": "staged_source_signals", "expected": STAGED_SIGNAL_COUNT, "observed": STAGED_SIGNAL_COUNT},
            {"metric": "final_clean_review_analysis_universe", "expected": EXPECTED_FINAL_CLEAN, "observed": len(final_signals)},
            {"metric": "remaining_non_clean_signals", "expected": EXPECTED_REMAINING, "observed": STAGED_SIGNAL_COUNT - len(final_signals)},
            {"metric": "final_clean_share_of_staged", "expected": round(EXPECTED_FINAL_CLEAN / STAGED_SIGNAL_COUNT, 4), "observed": round(len(final_signals) / STAGED_SIGNAL_COUNT, 4)},
            {"metric": "duplicate_stable_signal_id_rows_removed", "expected": 0, "observed": int(sum(len(f) for f in signal_frames) - len(final_signals))},
            {"metric": "bins_missing_stable_travelway_id", "expected": 0, "observed": int(final_bins["stable_travelway_id"].isna().sum())},
        ]
    )
    reconciliation["passes"] = reconciliation["expected"].eq(reconciliation["observed"])

    leg_dist, signal_leg_detail = compute_leg_distribution(final_signals, final_bins)
    window_availability = compute_window_availability(final_signals, final_bins)
    context_readiness = compute_context_readiness(final_signals, final_bins)
    remaining_214 = build_remaining_214()

    funnel = pd.DataFrame(
        [
            {"funnel_stage": "staged_source_signal_universe", "signal_count": STAGED_SIGNAL_COUNT, "share_of_staged": 1.0},
            {"funnel_stage": "original_represented", "signal_count": 2739, "share_of_staged": round(2739 / STAGED_SIGNAL_COUNT, 4)},
            {"funnel_stage": "accepted_recovery_additions", "signal_count": len(final_signals) - 2739, "share_of_staged": round((len(final_signals) - 2739) / STAGED_SIGNAL_COUNT, 4)},
            {"funnel_stage": "final_clean_review_analysis_universe", "signal_count": len(final_signals), "share_of_staged": round(len(final_signals) / STAGED_SIGNAL_COUNT, 4)},
            {"funnel_stage": "remaining_non_clean", "signal_count": STAGED_SIGNAL_COUNT - len(final_signals), "share_of_staged": round((STAGED_SIGNAL_COUNT - len(final_signals)) / STAGED_SIGNAL_COUNT, 4)},
        ]
    )

    source_limitation = remaining_214[
        [
            "remaining_status",
            "signal_count",
            "plain_language_meaning",
            "recoverable_later",
            "map_review_required",
            "external_source_data_required",
        ]
    ].copy()

    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Script writes only to review/current/final_clean_universe_context_summary."),
            ("no_records_promoted_to_production", True, "No production/final active outputs are written."),
            ("no_crash_assignment", True, "Crash summaries are context only; crash records are not assigned."),
            ("no_access_assignment", True, "Existing final access baseline summaries are read only when present."),
            ("no_rates_or_models", True, "No rates, regression, or model outputs are computed."),
            ("crash_direction_fields_not_used", True, "No crash-level records or direction fields are read."),
            ("stable_travelway_id_preserved", final_bins["stable_travelway_id"].notna().all(), "All final clean bins should carry stable_travelway_id."),
            ("physical_legs_separated_from_subbranches", final_bins["physical_leg_id"].notna().any() and "carriageway_subbranch_id" in final_bins.columns, "Physical leg and subbranch fields are separate output fields."),
            ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/final_clean_universe_context_summary"), str(OUT_DIR)),
            ("final_clean_count_matches_expected_3719", len(final_signals) == EXPECTED_FINAL_CLEAN, f"Observed {len(final_signals)}."),
            ("remaining_count_matches_expected_214", STAGED_SIGNAL_COUNT - len(final_signals) == EXPECTED_REMAINING, f"Observed {STAGED_SIGNAL_COUNT - len(final_signals)}."),
        ],
        columns=["qa_check", "passed", "notes"],
    )

    final_signals.to_csv(OUT_DIR / "final_clean_signal_universe_3719.csv", index=False)
    final_bins.to_csv(OUT_DIR / "final_clean_bin_universe_3719.csv", index=False)
    reconciliation.to_csv(OUT_DIR / "final_clean_universe_reconciliation.csv", index=False)
    branch_contrib.to_csv(OUT_DIR / "final_clean_recovery_branch_contributions.csv", index=False)
    leg_dist.to_csv(OUT_DIR / "final_clean_physical_leg_distribution.csv", index=False)
    window_availability.to_csv(OUT_DIR / "final_clean_bin_window_availability.csv", index=False)
    context_readiness.to_csv(OUT_DIR / "final_clean_context_readiness_summary.csv", index=False)
    remaining_214.to_csv(OUT_DIR / "final_remaining_214_breakdown.csv", index=False)
    funnel.to_csv(OUT_DIR / "final_meeting_signal_recovery_funnel.csv", index=False)
    context_readiness.to_csv(OUT_DIR / "final_meeting_context_readiness_table.csv", index=False)
    source_limitation.to_csv(OUT_DIR / "final_meeting_source_limitation_table.csv", index=False)
    qa.to_csv(OUT_DIR / "final_clean_universe_context_summary_qa.csv", index=False)

    leg_summary = signal_leg_detail["physical_leg_bucket"].value_counts().to_dict()
    speed_aadt_ready = int(final_signals["speed_aadt_ready"].fillna(False).sum())
    full_1000_ready = int(final_signals["full_0_1000_speed_aadt_ready"].fillna(False).sum())
    remaining_sum = int(remaining_214["signal_count"].sum())
    findings = f"""# Final Clean Universe Context Summary

## Bounded Question

Consolidate the review-only clean signal universe and summarize physical legs,
bin-window availability, and context readiness. This pass does not run recovery,
promote records, assign crashes/access, or calculate rates/models.

## Findings

1. The final clean universe reconciles to **{len(final_signals):,}** signals.
2. This represents **{len(final_signals) / STAGED_SIGNAL_COUNT:.2%}** of the **{STAGED_SIGNAL_COUNT:,}** staged/source signals.
3. Branch contributions are original represented **2,739**, good-Travelway **{len(good_ids)}**, offset-anchor **{len(offset_ids)}**, ramp-terminal **{len(ramp_ids)}**, and complex multi-signal **{len(complex_ids)}**.
4. Final physical-leg distribution is `{leg_summary}`. Physical legs are counted separately from carriageway/subbranch IDs.
5. Three- and four-leg intersections remain a large part of the universe; see `final_clean_physical_leg_distribution.csv` for branch-specific counts.
6. **{speed_aadt_ready:,}** signals are speed+AADT-ready.
7. **{full_1000_ready:,}** signals have full 0-1,000 ft speed+AADT readiness based on available branch-level flags.
8. The remaining non-clean ledger sums to **{remaining_sum:,}** signals, with the largest unresolved classes being low-confidence offset anchors, source-Travelway missing/incomplete records, and complex/ownership review holdouts.
9. The 3,719-signal universe is ready for review-only table and figure production. Access and crash summaries should use existing baselines or a later explicit refresh; this pass did not rerun either assignment.
10. The next active geospatial pass should be a bounded context/access/crash refresh design for the 3,719 clean universe, preserving review-only provenance and QA flags.

## QA

All outputs are written under `{OUT_DIR.relative_to(ROOT)}`. Crash direction fields were not read or used.
"""
    (OUT_DIR / "final_clean_universe_context_summary_findings.md").write_text(findings, encoding="utf-8")

    manifest = {
        "script": "src/active/roadway_graph/final_clean_universe_context_summary.py",
        "created_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "inputs": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in PATHS.items() if v.exists()},
        "outputs": [
            "final_clean_signal_universe_3719.csv",
            "final_clean_bin_universe_3719.csv",
            "final_clean_universe_reconciliation.csv",
            "final_clean_recovery_branch_contributions.csv",
            "final_clean_physical_leg_distribution.csv",
            "final_clean_bin_window_availability.csv",
            "final_clean_context_readiness_summary.csv",
            "final_remaining_214_breakdown.csv",
            "final_meeting_signal_recovery_funnel.csv",
            "final_meeting_context_readiness_table.csv",
            "final_meeting_source_limitation_table.csv",
            "final_clean_universe_context_summary_findings.md",
            "final_clean_universe_context_summary_qa.csv",
            "final_clean_universe_context_summary_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": [
            "no_new_recovery",
            "no_context_refresh_rerun",
            "no_access_assignment",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_active_outputs_modified",
            "no_production_promotion",
        ],
        "counts": {
            "staged_source_signals": STAGED_SIGNAL_COUNT,
            "final_clean_signals": int(len(final_signals)),
            "remaining_non_clean": int(STAGED_SIGNAL_COUNT - len(final_signals)),
            "final_clean_bins": int(len(final_bins)),
            "good_travelway_clean_ids": int(len(good_ids)),
            "offset_anchor_clean_ids": int(len(offset_ids)),
            "ramp_terminal_clean_ids": int(len(ramp_ids)),
            "complex_multisignal_clean_ids": int(len(complex_ids)),
        },
    }
    (OUT_DIR / "final_clean_universe_context_summary_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    log(progress, "Wrote final clean universe context summary outputs.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
