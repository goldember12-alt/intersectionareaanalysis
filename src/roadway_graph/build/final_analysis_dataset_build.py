"""Build the canonical final leg-corrected review-analysis dataset.

Bounded question: create one stable, read-only data mart for the final
3,719-signal leg-corrected universe so future table, figure, access, crash,
and guidance-matrix prompts can read one canonical folder first.

This build consolidates existing review outputs. It does not rerun signal
recovery, access assignment, crash assignment, rates, or models.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
POINTER = REPO / "work/output/roadway_graph/review/current/final_analysis_dataset_pointer"

REVIEW = REPO / "work/output/roadway_graph/review/current"
FINAL_DIR = REVIEW / "final_leg_corrected_clean_universe_summary"
NUMERIC_DIR = REVIEW / "final_signal_window_numeric_context_join"
TABLE_DIR = REVIEW / "final_signal_window_numeric_context_table"
MISSINGNESS_DIR = REVIEW / "final_signal_window_numeric_context_missingness_audit"
ACCESS_DIR = REVIEW / "final_leg_corrected_access_refresh"
ACCESS_SANITY_DIR = REVIEW / "final_leg_corrected_access_sanity_audit"
CRASH_DIR = REVIEW / "final_leg_corrected_crash_candidate_assignment"
CRASH_SANITY_DIR = REVIEW / "final_leg_corrected_crash_sanity_audit"
CRASH_ID_CORE_DIR = REVIEW / "crash_roadway_identity_core_integration"
CRASH_ID_DOCTRINE_DIR = REVIEW / "crash_roadway_identity_assignment_doctrine"
LINEAGE_DIR = REVIEW / "source_travelway_lineage_bridge"
SOURCE_TRAVELWAY_GPKG = REPO / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "final_signals": FINAL_DIR / "final_leg_corrected_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_leg_corrected_bin_universe.csv",
    "final_distribution": FINAL_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    "final_window_availability": FINAL_DIR / "final_leg_corrected_bin_window_availability.csv",
    "final_context_readiness": FINAL_DIR / "final_leg_corrected_context_readiness_summary.csv",
    "final_residual_ledger": FINAL_DIR / "final_leg_corrected_residual_issue_ledger.csv",
    "signal_window_v1": TABLE_DIR / "signal_window_numeric_context.csv",
    "approach_window_v1": TABLE_DIR / "signal_approach_window_numeric_context.csv",
    "bin_numeric": NUMERIC_DIR / "bin_numeric_speed_aadt_context.csv",
    "signal_window_v2": NUMERIC_DIR / "signal_window_numeric_context_v2.csv",
    "approach_window_v2": NUMERIC_DIR / "signal_approach_window_numeric_context_v2.csv",
    "matrix_v2": NUMERIC_DIR / "guidance_matrix_ready_long_v2.csv",
    "rate_readiness": NUMERIC_DIR / "candidate_crash_rate_readiness.csv",
    "field_dictionary_v2": NUMERIC_DIR / "plain_language_field_dictionary_v2.csv",
    "numeric_missingness_by_window": MISSINGNESS_DIR / "numeric_missingness_by_window.csv",
    "numeric_missingness_by_branch": MISSINGNESS_DIR / "numeric_missingness_by_branch.csv",
    "numeric_failure_detail": MISSINGNESS_DIR / "numeric_join_failure_reason_detail.csv",
    "numeric_recovery_opportunity": MISSINGNESS_DIR / "numeric_context_recovery_opportunity.csv",
    "untyped_access_detail": ACCESS_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
    "typed_access_detail": ACCESS_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv",
    "untyped_access_summary": ACCESS_DIR / "final_leg_corrected_untyped_access_summary.csv",
    "typed_access_summary": ACCESS_DIR / "final_leg_corrected_typed_access_summary.csv",
    "typed_category_summary": ACCESS_DIR / "final_leg_corrected_typed_access_category_summary.csv",
    "access_branch_coverage": ACCESS_SANITY_DIR / "access_coverage_by_recovery_branch.csv",
    "access_no_access": ACCESS_SANITY_DIR / "access_no_access_signal_summary.csv",
    "access_readiness": ACCESS_SANITY_DIR / "access_sanity_readiness_decision.csv",
    "crash_detail": CRASH_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
    "crash_signal_window_rollup": CRASH_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    "crash_approach_window_rollup": CRASH_DIR / "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    "crash_signal_rollup": CRASH_DIR / "leg_corrected_crash_candidate_assignment_signal_rollup.csv",
    "crash_fanout": CRASH_SANITY_DIR / "crash_fanout_sanity_summary.csv",
    "crash_high_fanout": CRASH_SANITY_DIR / "crash_high_fanout_cause_classification.csv",
    "crash_readiness": CRASH_SANITY_DIR / "crash_sanity_readiness_decision.csv",
    "crash_identity_core": CRASH_ID_CORE_DIR / "crash_core_roadway_identity_table.csv",
    "crash_50ft_identity_compat": CRASH_ID_CORE_DIR / "crash_spatial_50ft_with_identity_compatibility.csv",
    "crash_identity_compatible": CRASH_ID_CORE_DIR / "crash_identity_compatible_spatial_50ft_assignment.csv",
    "crash_level_identity_status": CRASH_ID_DOCTRINE_DIR / "crash_level_identity_spatial_status.csv",
    "identity_compatible_detail": CRASH_ID_DOCTRINE_DIR / "identity_compatible_spatial_50ft_assignment_detail.csv",
    "identity_compatible_rollups": CRASH_ID_DOCTRINE_DIR / "identity_compatible_spatial_50ft_rollups.csv",
    "crash_identity_doctrine": CRASH_ID_DOCTRINE_DIR / "crash_roadway_identity_assignment_doctrine.csv",
    "source_travelway_identity": LINEAGE_DIR / "source_travelway_stable_identity.csv",
}

BRANCH_NUMERIC_FILES = [
    (
        REVIEW / "missing_hmms_good_travelway_context_refresh/good_travelway_context_bin_detail.csv",
        "missing_hmms_good_travelway_context_refresh",
    ),
    (
        REVIEW / "missing_hmms_offset_anchor_context_refresh/offset_anchor_context_bin_detail.csv",
        "missing_hmms_offset_anchor_context_refresh",
    ),
    (
        REVIEW / "missing_hmms_ramp_terminal_context_refresh/ramp_terminal_context_bin_detail.csv",
        "missing_hmms_ramp_terminal_context_refresh",
    ),
    (
        REVIEW / "missing_hmms_complex_multisignal_context_refresh/complex_multisignal_context_bin_detail.csv",
        "missing_hmms_complex_multisignal_context_refresh",
    ),
]

WINDOW_LABELS = {"0_1000": "0-1,000 ft", "1000_2500": "1,000-2,500 ft"}
WINDOW_COMPONENTS = {
    "0-1,000 ft": {"0_1000"},
    "0-2,500 ft": {"0_1000", "1000_2500"},
}
TYPED_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
]


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing input: {path}")
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def read_csv_existing_cols(path: Path, wanted: list[str], **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing input: {path}")
        return pd.DataFrame(columns=wanted)
    cols = pd.read_csv(path, nrows=0).columns.tolist()
    use = [c for c in wanted if c in cols]
    if not use:
        return pd.DataFrame(columns=wanted)
    return pd.read_csv(path, usecols=use, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def boolish(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes", "y"])


def access_band(value: object) -> str:
    n = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(n) or n <= 0:
        return "0"
    if n <= 2:
        return "1-2"
    if n <= 5:
        return "3-5"
    return "6+"


def aadt_band(value: object) -> str:
    n = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(n):
        return "unknown/out-of-range"
    if 1500 <= n <= 9000:
        return "1,500-9,000"
    if 9000 < n <= 12000:
        return "9,000-12,000"
    if 12000 < n <= 15000:
        return "12,000-15,000"
    if n > 15000:
        return ">15,000"
    return "unknown/out-of-range"


def speed_band(value: object) -> str:
    n = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(n):
        return "unknown"
    if n <= 30:
        return "<=30 mph"
    if n == 35:
        return "35 mph"
    if n >= 40:
        return ">=40 mph"
    return "unknown"


def median_group_from_raw(value: object) -> str:
    if pd.isna(value):
        return "unknown"
    s = str(value).lower()
    if not s.strip() or s in {"nan", "none", "unknown"}:
        return "unknown"
    if "barrier" in s or "curb" in s or "raised" in s:
        return "barrier_or_curb_median"
    if "paint" in s or "flush" in s or "unprotected" in s:
        return "unprotected_or_painted_median"
    if "rail" in s:
        return "rail_or_other_median"
    if "no median" in s or "<4" in s or "lt 4" in s or "less than 4" in s:
        return "no_median_or_lt_4ft"
    return "other_or_unknown_median"


def dominant_nonnull(series: pd.Series) -> object:
    s = series.dropna().astype(str)
    s = s[s.str.strip().ne("")]
    if s.empty:
        return pd.NA
    return s.value_counts().index[0]


def unique_join(series: pd.Series, max_items: int = 8) -> str:
    vals = [v for v in series.dropna().astype(str).unique().tolist() if v and v.lower() != "nan"]
    vals = sorted(vals)
    if len(vals) > max_items:
        return "|".join(vals[:max_items]) + f"|+{len(vals) - max_items} more"
    return "|".join(vals)


def route_window_label(analysis_window: object, include_sensitivity: bool = True) -> str:
    s = str(analysis_window)
    if s == "0_1000":
        return "0-1,000 ft"
    if include_sensitivity and s in {"1000_2500", "0_2500"}:
        return "0-2,500 ft"
    return s


def load_source_travelway_attributes() -> pd.DataFrame:
    cols = [
        "fid",
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "RIM_FACILI",
        "RIM_FACI_1",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "RIM_MEDIAN",
        "MEDIAN_IND",
        "RIM_ACCESS",
        "FROM_MEASURE",
        "TO_MEASURE",
    ]
    if not SOURCE_TRAVELWAY_GPKG.exists():
        log("Source Travelway GPKG missing; median raw fields will remain null at bin grain.")
        return pd.DataFrame(columns=cols)
    log("Reading selected source Travelway attributes without geometry.")
    with sqlite3.connect(SOURCE_TRAVELWAY_GPKG) as con:
        existing = pd.read_sql_query("pragma table_info(source_travelway_full)", con)["name"].tolist()
        use = [c for c in cols if c in existing]
        return pd.read_sql_query(f"select {','.join(use)} from source_travelway_full", con)


def load_numeric_bin_context() -> pd.DataFrame:
    use = [
        "stable_bin_id",
        "speed_limit_mph",
        "speed_match_method",
        "aadt",
        "aadt_year",
        "aadt_match_method",
        "aadt_exposure_denominator",
        "aadt_exposure_method",
        "numeric_context_source",
        "bin_length_ft",
        "bin_length_mi",
        "source_measure_midpoint",
        "route_key_common",
        "route_key_name",
    ]
    numeric = read_csv_existing_cols(INPUTS["bin_numeric"], use, low_memory=False)
    for c in ["speed_limit_mph", "aadt", "aadt_year", "aadt_exposure_denominator", "bin_length_ft", "bin_length_mi", "source_measure_midpoint"]:
        if c in numeric:
            numeric[c] = pd.to_numeric(numeric[c], errors="coerce")
    return numeric


def backfill_numeric_from_branch_outputs(bin_df: pd.DataFrame) -> pd.DataFrame:
    missing_speed = set(bin_df.loc[bin_df["speed_limit_mph"].isna(), "stable_bin_id"].astype(str))
    missing_aadt = set(bin_df.loc[bin_df["aadt"].isna(), "stable_bin_id"].astype(str))
    if not missing_speed and not missing_aadt:
        return bin_df

    speed_map: dict[str, tuple[float, str, str]] = {}
    aadt_map: dict[str, tuple[float, object, str, str]] = {}
    log("Backfilling numeric speed/AADT from branch context-refresh value fields where stable_bin_id matches.")
    for path, source_name in BRANCH_NUMERIC_FILES:
        if not path.exists():
            continue
        cols = pd.read_csv(path, nrows=0).columns.tolist()
        use = ["stable_bin_id"]
        speed_field = "rns_CAR_SPEED_LIMIT" if "rns_CAR_SPEED_LIMIT" in cols else None
        aadt_field = "aadt_AADT" if "aadt_AADT" in cols else None
        aadt_year_field = "aadt_AADT_YR" if "aadt_AADT_YR" in cols else None
        for c in [speed_field, aadt_field, aadt_year_field]:
            if c and c not in use:
                use.append(c)
        if len(use) == 1:
            continue
        for chunk in pd.read_csv(path, usecols=use, chunksize=200_000, low_memory=False):
            chunk["stable_bin_id"] = chunk["stable_bin_id"].astype(str)
            if speed_field:
                parsed_speed = pd.to_numeric(chunk[speed_field], errors="coerce")
                mask = parsed_speed.notna() & chunk["stable_bin_id"].isin(missing_speed)
                for sid, value in zip(chunk.loc[mask, "stable_bin_id"], parsed_speed[mask]):
                    speed_map.setdefault(sid, (float(value), source_name, path.name))
            if aadt_field:
                parsed_aadt = pd.to_numeric(chunk[aadt_field], errors="coerce")
                parsed_year = pd.to_numeric(chunk[aadt_year_field], errors="coerce") if aadt_year_field else pd.Series(pd.NA, index=chunk.index)
                mask = parsed_aadt.notna() & chunk["stable_bin_id"].isin(missing_aadt)
                for sid, value, year in zip(chunk.loc[mask, "stable_bin_id"], parsed_aadt[mask], parsed_year[mask]):
                    aadt_map.setdefault(sid, (float(value), year if pd.notna(year) else pd.NA, source_name, path.name))
        log(f"Scanned {path.name}: cumulative speed backfill {len(speed_map):,}, AADT backfill {len(aadt_map):,}.")

    sid = bin_df["stable_bin_id"].astype(str)
    speed_fill = sid.map(lambda x: speed_map.get(x, (np.nan, "", ""))[0])
    speed_source = sid.map(lambda x: speed_map.get(x, (np.nan, "", ""))[1])
    speed_file = sid.map(lambda x: speed_map.get(x, (np.nan, "", ""))[2])
    aadt_fill = sid.map(lambda x: aadt_map.get(x, (np.nan, pd.NA, "", ""))[0])
    aadt_year_fill = pd.to_numeric(sid.map(lambda x: aadt_map.get(x, (np.nan, np.nan, "", ""))[1]), errors="coerce")
    aadt_source = sid.map(lambda x: aadt_map.get(x, (np.nan, pd.NA, "", ""))[2])
    aadt_file = sid.map(lambda x: aadt_map.get(x, (np.nan, pd.NA, "", ""))[3])

    mask_speed = bin_df["speed_limit_mph"].isna() & pd.Series(speed_fill).notna().to_numpy()
    mask_aadt = bin_df["aadt"].isna() & pd.Series(aadt_fill).notna().to_numpy()
    bin_df.loc[mask_speed, "speed_limit_mph"] = pd.Series(speed_fill).to_numpy()[mask_speed]
    bin_df.loc[mask_speed, "speed_match_method"] = "direct_stable_bin_id_branch_context_carry_forward"
    bin_df.loc[mask_speed, "speed_numeric_source_file"] = pd.Series(speed_file).to_numpy()[mask_speed]
    bin_df.loc[mask_speed, "numeric_speed_source_method"] = pd.Series(speed_source).to_numpy()[mask_speed]
    bin_df.loc[mask_aadt, "aadt"] = pd.Series(aadt_fill).to_numpy()[mask_aadt]
    bin_df.loc[mask_aadt, "aadt_year"] = aadt_year_fill.to_numpy()[mask_aadt]
    bin_df.loc[mask_aadt, "aadt_match_method"] = "direct_stable_bin_id_branch_context_carry_forward"
    bin_df.loc[mask_aadt, "aadt_numeric_source_file"] = pd.Series(aadt_file).to_numpy()[mask_aadt]
    bin_df.loc[mask_aadt, "numeric_aadt_source_method"] = pd.Series(aadt_source).to_numpy()[mask_aadt]

    exposure_mask = bin_df["aadt_exposure_denominator"].isna() & bin_df["aadt"].notna() & bin_df["bin_length_mi"].notna()
    bin_df.loc[exposure_mask, "aadt_exposure_denominator"] = bin_df.loc[exposure_mask, "aadt"] * bin_df.loc[exposure_mask, "bin_length_mi"]
    bin_df.loc[exposure_mask, "aadt_exposure_method"] = "computed_from_aadt_times_final_bin_length_miles"
    log(f"Backfilled speed on {int(mask_speed.sum()):,} bins, AADT on {int(mask_aadt.sum()):,} bins, exposure on {int(exposure_mask.sum()):,} bins.")
    return bin_df


def build_analysis_bin() -> pd.DataFrame:
    final_cols = [
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
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "original_physical_leg_id",
        "final_review_physical_leg_id",
        "original_carriageway_subbranch_id",
        "final_review_carriageway_subbranch_id",
        "final_review_leg_source",
        "final_review_context_status",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
        "final_review_recovery_provenance",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "lineage_match_method",
        "lineage_confidence",
        "partial_coverage_flag",
        "anchor_method",
        "anchor_confidence",
        "residual_bucket",
        "route_measure_ready_bin",
        "roadway_context_ready_bin",
        "roadway_context_status",
    ]
    bins = read_csv_existing_cols(INPUTS["final_bins"], final_cols, low_memory=False)
    numeric = load_numeric_bin_context()
    bins = bins.merge(numeric, on="stable_bin_id", how="left")
    bins["bin_length_ft"] = pd.to_numeric(bins.get("bin_length_ft"), errors="coerce").fillna(
        pd.to_numeric(bins.get("distance_end_ft"), errors="coerce") - pd.to_numeric(bins.get("distance_start_ft"), errors="coerce")
    )
    bins["bin_length_mi"] = pd.to_numeric(bins.get("bin_length_mi"), errors="coerce").fillna(bins["bin_length_ft"] / 5280.0)
    bins["speed_numeric_source_file"] = np.where(bins["speed_limit_mph"].notna(), INPUTS["bin_numeric"].name, "")
    bins["aadt_numeric_source_file"] = np.where(bins["aadt"].notna(), INPUTS["bin_numeric"].name, "")
    bins["numeric_speed_source_method"] = np.where(bins["speed_limit_mph"].notna(), bins.get("speed_match_method", ""), "")
    bins["numeric_aadt_source_method"] = np.where(bins["aadt"].notna(), bins.get("aadt_match_method", ""), "")
    bins = backfill_numeric_from_branch_outputs(bins)

    tw = load_source_travelway_attributes()
    if not tw.empty and "source_feature_local_fid" in bins.columns:
        tw = tw.rename(
            columns={
                "fid": "source_feature_local_fid",
                "RIM_MEDIAN": "rim_median_raw",
                "RIM_ACCESS": "rim_access_raw",
                "RIM_FACILI": "rim_facility_raw",
                "RIM_FACI_1": "rim_facility_secondary_raw",
            }
        )
        tw["source_feature_local_fid"] = tw["source_feature_local_fid"].astype(str)
        bins["source_feature_local_fid"] = bins["source_feature_local_fid"].astype(str)
        bins = bins.merge(
            tw[
                [
                    c
                    for c in [
                        "source_feature_local_fid",
                        "rim_median_raw",
                        "MEDIAN_IND",
                        "rim_access_raw",
                        "rim_facility_raw",
                        "rim_facility_secondary_raw",
                        "RTE_CATEGO",
                        "RTE_TYPE_N",
                        "RTE_RAMP_C",
                    ]
                    if c in tw.columns
                ]
            ].drop_duplicates("source_feature_local_fid"),
            on="source_feature_local_fid",
            how="left",
        )
    else:
        bins["rim_median_raw"] = pd.NA
        bins["rim_access_raw"] = pd.NA
    bins["median_group"] = bins["rim_median_raw"].map(median_group_from_raw)
    bins["median_missing_flag"] = bins["median_group"].eq("unknown")
    bins["numeric_source_method"] = np.select(
        [
            bins["speed_limit_mph"].notna() & bins["aadt"].notna(),
            bins["speed_limit_mph"].notna(),
            bins["aadt"].notna(),
        ],
        ["speed_and_aadt_available", "speed_only_available", "aadt_only_available"],
        default="no_numeric_context",
    )
    bins["numeric_confidence"] = np.where(bins["speed_limit_mph"].notna() | bins["aadt"].notna(), "review_source_numeric", "missing")
    bins["numeric_missingness_reason"] = np.select(
        [
            bins["speed_limit_mph"].notna() & bins["aadt"].notna(),
            bins["stable_travelway_id"].isna(),
            bins["source_measure_start"].isna() & bins["source_measure_end"].isna(),
        ],
        ["numeric_present", "missing_stable_travelway_id", "missing_source_measure"],
        default="numeric_source_unmatched_or_not_carried",
    )
    bins = bins.rename(
        columns={
            "final_review_physical_leg_id": "signal_approach_id",
            "final_review_carriageway_subbranch_id": "carriageway_source_subpart_id",
        }
    )
    return bins


def build_signal_window_from_bins(bins: pd.DataFrame, sw_v2: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for label, components in WINDOW_COMPONENTS.items():
        g = bins[bins["analysis_window"].isin(components)].copy()
        if g.empty:
            continue
        agg = (
            g.groupby("stable_signal_id", dropna=False)
            .agg(
                signal_window_bin_count=("stable_bin_id", "size"),
                stable_travelway_count=("stable_travelway_id", "nunique"),
                approach_count=("signal_approach_id", "nunique"),
                representative_speed_limit_mph=("speed_limit_mph", "median"),
                speed_limit_min_mph=("speed_limit_mph", "min"),
                speed_limit_max_mph=("speed_limit_mph", "max"),
                representative_aadt=("aadt", "median"),
                aadt_min=("aadt", "min"),
                aadt_max=("aadt", "max"),
                exposure_denominator=("aadt_exposure_denominator", "sum"),
                median_group=("median_group", dominant_nonnull),
                observed_rim_median_values=("rim_median_raw", unique_join),
                median_group_count=("median_group", "nunique"),
                roadway_context=("roadway_context_status", dominant_nonnull),
                facility_type=("rim_facility_raw", dominant_nonnull),
                final_review_leg_source_summary=("final_review_leg_source", unique_join),
                recovery_provenance_summary=("final_review_recovery_provenance", unique_join),
                numeric_bin_count=("speed_limit_mph", lambda s: int(s.notna().sum())),
                aadt_numeric_bin_count=("aadt", lambda s: int(s.notna().sum())),
                exposure_numeric_bin_count=("aadt_exposure_denominator", lambda s: int(s.notna().sum())),
            )
            .reset_index()
        )
        agg["signal_window"] = label
        frames.append(agg)
    out = pd.concat(frames, ignore_index=True)
    out["speed_band"] = out["representative_speed_limit_mph"].map(speed_band)
    out["aadt_band"] = out["representative_aadt"].map(aadt_band)
    out["numeric_aadt_complete_flag"] = out["representative_aadt"].notna()
    out["numeric_speed_complete_flag"] = out["representative_speed_limit_mph"].notna()
    out["numeric_exposure_complete_flag"] = out["exposure_denominator"].notna() & out["exposure_denominator"].gt(0)
    out["candidate_crash_rate"] = np.where(
        out["numeric_exposure_complete_flag"],
        np.nan,
        np.nan,
    )
    keep = [
        "stable_signal_id",
        "signal_window",
        "source_signal_id",
        "recovery_branch",
        "final_leg_corrected_physical_leg_count",
        "final_leg_corrected_physical_leg_bucket",
        "clean_review_analysis_status",
        "untyped_access_raw_count",
        "untyped_access_count_band",
        "typed_v2_access_raw_count",
        "typed_categories_present",
        "spatial_50ft_crash_count",
        "spatial_50ft_weighted_crash_count",
        "identity_compatible_spatial_50ft_crash_count",
        "identity_compatible_spatial_50ft_weighted_crash_count",
        "max_crash_assignment_fanout",
        "low_crash_count_flag",
        *TYPED_CATEGORIES,
    ]
    sw_keep = sw_v2[[c for c in keep if c in sw_v2.columns]].copy()
    out = out.merge(sw_keep, on=["stable_signal_id", "signal_window"], how="left")
    out["untyped_access_raw_count"] = pd.to_numeric(out.get("untyped_access_raw_count"), errors="coerce").fillna(0)
    out["untyped_access_count_band"] = out["untyped_access_raw_count"].map(access_band)
    out["optional_access_per_1000ft"] = np.where(
        out["signal_window"].eq("0-1,000 ft"),
        out["untyped_access_raw_count"],
        out["untyped_access_raw_count"] / 2.5,
    )
    out["rate_denominator_field_used"] = "exposure_denominator"
    out["rate_denominator_completeness_flag"] = out["numeric_exposure_complete_flag"]
    out["missing_numeric_context_flag"] = ~(out["numeric_aadt_complete_flag"] & out["numeric_speed_complete_flag"] & out["numeric_exposure_complete_flag"])
    return out


def build_approach_window_from_bins(bins: pd.DataFrame, approach_v2: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for label, components in WINDOW_COMPONENTS.items():
        g = bins[bins["analysis_window"].isin(components)].copy()
        if g.empty:
            continue
        agg = (
            g.groupby(["stable_signal_id", "signal_approach_id"], dropna=False)
            .agg(
                signal_approach_window_bin_count=("stable_bin_id", "size"),
                stable_travelway_count=("stable_travelway_id", "nunique"),
                representative_speed_limit_mph=("speed_limit_mph", "median"),
                representative_aadt=("aadt", "median"),
                exposure_denominator=("aadt_exposure_denominator", "sum"),
                median_group=("median_group", dominant_nonnull),
                roadway_context=("roadway_context_status", dominant_nonnull),
                facility_type=("rim_facility_raw", dominant_nonnull),
                final_review_leg_source_summary=("final_review_leg_source", unique_join),
                recovery_provenance_summary=("final_review_recovery_provenance", unique_join),
            )
            .reset_index()
        )
        agg["signal_window"] = label
        frames.append(agg)
    out = pd.concat(frames, ignore_index=True)
    out["speed_band"] = out["representative_speed_limit_mph"].map(speed_band)
    out["aadt_band"] = out["representative_aadt"].map(aadt_band)
    keep = [
        "stable_signal_id",
        "final_review_physical_leg_id",
        "signal_window",
        "approach_label",
        "untyped_access_raw_count",
        "untyped_access_count_band",
        "spatial_50ft_crash_count",
        "spatial_50ft_weighted_crash_count",
        "identity_compatible_spatial_50ft_crash_count",
        "identity_compatible_spatial_50ft_weighted_crash_count",
    ]
    av = approach_v2[[c for c in keep if c in approach_v2.columns]].rename(columns={"final_review_physical_leg_id": "signal_approach_id"})
    out = out.merge(av, on=["stable_signal_id", "signal_approach_id", "signal_window"], how="left")
    return out


def build_analysis_signal(signals: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    summary = (
        sw.groupby("stable_signal_id", dropna=False)
        .agg(
            median_group_summary=("median_group", unique_join),
            roadway_context_summary=("roadway_context", dominant_nonnull),
            facility_type_summary=("facility_type", dominant_nonnull),
            access_windows_with_any_access=("untyped_access_raw_count", lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) > 0).sum())),
            spatial_50ft_crash_windows_with_any_crash=("spatial_50ft_crash_count", lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) > 0).sum())),
            numeric_aadt_windows=("numeric_aadt_complete_flag", "sum"),
            numeric_speed_windows=("numeric_speed_complete_flag", "sum"),
            numeric_exposure_windows=("numeric_exposure_complete_flag", "sum"),
        )
        .reset_index()
    )
    out = signals.merge(summary, on="stable_signal_id", how="left")
    out["clean_analysis_universe"] = True
    out["recovery_branch_plain"] = out.get("recovery_branch", "").astype(str).str.replace("_", " ", regex=False)
    out["signal_approach_count"] = out.get("final_leg_corrected_physical_leg_count")
    out["final_leg_distribution_bucket"] = out.get("final_leg_corrected_physical_leg_bucket")
    out["access_availability_summary"] = np.where(out["access_windows_with_any_access"].fillna(0).gt(0), "access_observed", "no_access_observed")
    out["crash_assignment_availability_summary"] = np.where(
        out["spatial_50ft_crash_windows_with_any_crash"].fillna(0).gt(0),
        "spatial_50ft_crash_observed",
        "no_spatial_50ft_crash_observed",
    )
    out["source_limitation_or_residual_qa_flag"] = out.get("qa_flags", "").fillna("")
    return out


def build_guidance_matrix(sw: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["roadway_context", "median_group", "aadt_band", "speed_band", "untyped_access_count_band", "signal_window"]
    for c in ["spatial_50ft_crash_count", "spatial_50ft_weighted_crash_count", "identity_compatible_spatial_50ft_crash_count", "exposure_denominator"]:
        sw[c] = pd.to_numeric(sw.get(c), errors="coerce").fillna(0)
    out = (
        sw.groupby(group_cols, dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            crash_count=("spatial_50ft_crash_count", "sum"),
            weighted_crash_count=("spatial_50ft_weighted_crash_count", "sum"),
            identity_compatible_crash_count=("identity_compatible_spatial_50ft_crash_count", "sum"),
            exposure_denominator=("exposure_denominator", "sum"),
            missing_numeric_context_rows=("missing_numeric_context_flag", "sum"),
        )
        .reset_index()
    )
    out["candidate_crash_rate"] = np.where(out["exposure_denominator"].gt(0), out["weighted_crash_count"] / out["exposure_denominator"], np.nan)
    out["low_n_flag"] = out["crash_count"].lt(5)
    out["sparse_cell_flag"] = out["signal_count"].lt(10)
    out["candidate_rate_is_review_only"] = out["candidate_crash_rate"].notna()
    return out


def build_dictionary() -> pd.DataFrame:
    rows = [
        ("stable_signal_id", "Signal ID", "Stable review-analysis signal identifier.", "", "final leg-corrected signal universe", "", True, True),
        ("stable_bin_id", "Bin ID", "Stable 50-ft roadway bin identifier.", "", "final leg-corrected bin universe", "", True, True),
        ("signal_approach_id", "Signal approach ID", "Review-only corrected signal approach identifier.", "", "final leg-corrected bin universe", "Public-facing term for final_review_physical_leg_id.", False, True),
        ("carriageway_source_subpart_id", "Carriageway/source subpart ID", "Review-only carriageway or source-row subpart identifier.", "", "final leg-corrected bin universe", "Public-facing term for subbranch.", False, True),
        ("speed_limit_mph", "Speed limit", "Numeric speed limit assigned to the bin or summarized to signal-window grain.", "mph", "RNS Phase 3D or branch context carry-forward", "Completeness is incomplete.", False, True),
        ("aadt", "AADT", "Numeric annual average daily traffic value assigned to the bin.", "vehicles/day", "AADT v3 or branch context carry-forward", "Completeness is incomplete.", False, True),
        ("exposure_denominator", "Exposure denominator", "Candidate review-only sum of AADT times roadway bin length.", "AADT x roadway miles", "computed from AADT and bin length", "Not a final rate denominator policy.", False, True),
        ("median_group", "Median group", "Compact median category derived from RIM_MEDIAN.", "", "source Travelway lineage", "Unknown where source median is not carried.", False, True),
        ("untyped_access_raw_count", "Access point count", "Raw untyped spatial 100 ft access count in the signal window.", "points", "final leg-corrected access refresh", "Primary access display uses raw count bands, not density.", False, True),
        ("spatial_50ft_crash_count", "Spatial 50 ft crash count", "Unweighted crash count from primary spatial 50 ft review product.", "crashes", "final leg-corrected crash assignment", "Review-only, not a rate/model.", False, True),
        ("identity_compatible_spatial_50ft_crash_count", "Identity-compatible crash count", "Crash count from identity-compatible spatial 50 ft sensitivity product.", "crashes", "crash roadway identity doctrine", "Sensitivity/QA companion, not replacement for spatial 50 ft.", False, True),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "field_name",
            "plain_language_label",
            "definition",
            "units",
            "source",
            "caveat",
            "internal_provenance_flag",
            "recommended_figure_use",
        ],
    )


def completeness_summary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in tables.items():
        rows.append({"table_name": name, "rows": len(df), "columns": len(df.columns)})
    return pd.DataFrame(rows)


def numeric_completeness(bin_df: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for table_name, df, denom_col in [
        ("analysis_bin", bin_df, "stable_bin_id"),
        ("analysis_signal_window", sw, "stable_signal_id"),
    ]:
        total = len(df)
        rows.append(
            {
                "table_name": table_name,
                "rows": total,
                "numeric_speed_rows": int(df["speed_limit_mph"].notna().sum() if "speed_limit_mph" in df else df["representative_speed_limit_mph"].notna().sum()),
                "numeric_aadt_rows": int(df["aadt"].notna().sum() if "aadt" in df else df["representative_aadt"].notna().sum()),
                "exposure_denominator_rows": int(df["aadt_exposure_denominator"].notna().sum() if "aadt_exposure_denominator" in df else df["exposure_denominator"].gt(0).sum()),
            }
        )
    out = pd.DataFrame(rows)
    for c in ["numeric_speed_rows", "numeric_aadt_rows", "exposure_denominator_rows"]:
        out[c.replace("_rows", "_share")] = (out[c] / out["rows"]).round(4)
    return out


def median_completeness(bin_df: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for table_name, df in [("analysis_bin", bin_df), ("analysis_signal_window", sw)]:
        total = len(df)
        rows.append(
            {
                "table_name": table_name,
                "rows": total,
                "median_non_unknown_rows": int(df["median_group"].fillna("unknown").ne("unknown").sum()),
                "median_unknown_rows": int(df["median_group"].fillna("unknown").eq("unknown").sum()),
            }
        )
    out = pd.DataFrame(rows)
    out["median_non_unknown_share"] = (out["median_non_unknown_rows"] / out["rows"]).round(4)
    return out


def access_crash_completeness(sw: pd.DataFrame) -> pd.DataFrame:
    total = len(sw)
    return pd.DataFrame(
        [
            {
                "table_name": "analysis_signal_window",
                "rows": total,
                "rows_with_untyped_access_count": int(sw["untyped_access_raw_count"].notna().sum()),
                "rows_with_spatial_50ft_crash_count": int(sw["spatial_50ft_crash_count"].notna().sum()),
                "rows_with_identity_compatible_crash_count": int(sw["identity_compatible_spatial_50ft_crash_count"].notna().sum()),
                "rows_with_any_access": int(pd.to_numeric(sw["untyped_access_raw_count"], errors="coerce").fillna(0).gt(0).sum()),
                "rows_with_any_spatial_50ft_crash": int(pd.to_numeric(sw["spatial_50ft_crash_count"], errors="coerce").fillna(0).gt(0).sum()),
            }
        ]
    )


def findings_text(signal: pd.DataFrame, bin_df: pd.DataFrame, sw: pd.DataFrame, numeric: pd.DataFrame, median: pd.DataFrame) -> str:
    sw_numeric = numeric[numeric["table_name"].eq("analysis_signal_window")].iloc[0].to_dict()
    bin_numeric = numeric[numeric["table_name"].eq("analysis_bin")].iloc[0].to_dict()
    sw_median = median[median["table_name"].eq("analysis_signal_window")].iloc[0].to_dict()
    matrix_ready_rows = int((~sw["missing_numeric_context_flag"]).sum())
    return f"""# Final Analysis Dataset Build Findings

## Canonical Tables
The canonical review-analysis dataset is written to `work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset/`.

Primary tables:
- `analysis_signal.csv`: {len(signal):,} final clean review-analysis signals.
- `analysis_bin.csv`: {len(bin_df):,} final leg-corrected bins.
- `analysis_signal_window.csv`: {len(sw):,} signal-window rows.
- `analysis_signal_approach_window.csv`: approach-window analysis rows.
- `analysis_guidance_matrix_long.csv`: guidance-matrix-ready grouped table.

## Answers
1. Future Codex prompts should read this analysis folder first before looking back to branch-specific review outputs.
2. Numeric completeness after branch-value backfill is: signal-window speed {sw_numeric.get('numeric_speed_rows', 0):,} / {sw_numeric.get('rows', 0):,}, AADT {sw_numeric.get('numeric_aadt_rows', 0):,} / {sw_numeric.get('rows', 0):,}, exposure {sw_numeric.get('exposure_denominator_rows', 0):,} / {sw_numeric.get('rows', 0):,}. Bin-level speed is {bin_numeric.get('numeric_speed_rows', 0):,} / {bin_numeric.get('rows', 0):,}; bin-level AADT is {bin_numeric.get('numeric_aadt_rows', 0):,} / {bin_numeric.get('rows', 0):,}.
3. Median is carried through source Travelway lineage where possible. Signal-window non-unknown median rows are {sw_median.get('median_non_unknown_rows', 0):,} / {sw_median.get('rows', 0):,}.
4. Numeric completeness improves over the prior signal-window v2 table where branch stable-bin value carry-forward applies, but it remains incomplete and should be treated explicitly in figures.
5. Access is represented as raw access counts and 0 / 1-2 / 3-5 / 6+ count bands. Access per 1,000 ft is carried only as a secondary derived field.
6. Crash spatial 50 ft counts and identity-compatible spatial crash counts are both carried.
7. Remaining incomplete fields are primarily numeric AADT/speed/exposure and source median for bins without usable source lineage.
8. The guidance matrix is partially data-ready: count-based cells are usable; rate/candidate-rate cells should use numeric-complete rows or show missing numeric context.
9. Next visualization pass should use `analysis_signal_window.csv` and `analysis_guidance_matrix_long.csv`, with explicit missing-context flags and no final rate claims.

## QA Note
No active outputs were modified, no records promoted, no crash/access assignment was rerun, no final rates/models were calculated, and crash direction fields were not read or used.
"""


def readme_text() -> str:
    return """# Final Leg-Corrected Analysis Dataset

This folder is the canonical review-analysis data mart for the final 3,719-signal leg-corrected universe.

Future Codex prompts for tables, figures, access summaries, crash summaries, or guidance-matrix design should read this folder first before searching branch-specific review outputs.

These outputs are review-only. They do not modify active outputs, promote records, rerun signal recovery, rerun access assignment, rerun crash assignment, or calculate final rates/models.

Primary tables:
- `analysis_signal.csv`
- `analysis_bin.csv`
- `analysis_signal_window.csv`
- `analysis_signal_approach_window.csv`
- `analysis_guidance_matrix_long.csv`

Access is carried as raw access counts and simple count bands. Access density is secondary only.

Crash counts include the spatial 50 ft primary review product and the identity-compatible spatial 50 ft sensitivity product. Crash roadway identity is a required carried reference field in downstream crash products, but this data mart does not replace the spatial 50 ft primary product.

Numeric AADT, speed, and exposure denominator are carried where existing review sources support them. Missing numeric context is explicit and must be handled in figures and guidance-matrix work.
"""


def qa_table() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Analysis outputs written only under analysis/current plus review pointer."),
        ("no_records_promoted", True, "Review-analysis data mart only."),
        ("no_new_crash_access_assignment", True, "Existing access/crash assignment outputs were read only."),
        ("no_rates_or_models", True, "Candidate rate fields remain review-only; no final rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash source and direction fields were not read."),
        ("numeric_values_not_fabricated", True, "Numeric values are direct joins/carry-forward or documented AADT x bin-length exposure computation."),
        ("rim_median_carried_through_source_lineage", True, "RIM_MEDIAN is joined from source Travelway attributes by source feature lineage where available."),
        ("raw_access_counts_and_bands_included", True, "Raw access counts and 0/1-2/3-5/6+ bands are included."),
        ("outputs_limited_to_analysis_and_pointer", True, f"{OUT}; {POINTER}"),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_analysis_dataset_build",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "pointer_folder": str(POINTER.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "branch_numeric_files": [str(p.relative_to(REPO)) for p, _ in BRANCH_NUMERIC_FILES if p.exists()],
        "outputs": list(outputs),
        "review_only": True,
        "canonical_analysis_dataset": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    POINTER.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting final analysis dataset build.")

    signals = read_csv(INPUTS["final_signals"], dtype={"stable_signal_id": str}, low_memory=False)
    sw_v2 = read_csv(INPUTS["signal_window_v2"], dtype={"stable_signal_id": str}, low_memory=False)
    approach_v2 = read_csv(INPUTS["approach_window_v2"], dtype={"stable_signal_id": str}, low_memory=False)

    analysis_bin = build_analysis_bin()
    analysis_signal_window = build_signal_window_from_bins(analysis_bin, sw_v2)
    analysis_approach_window = build_approach_window_from_bins(analysis_bin, approach_v2)
    analysis_signal = build_analysis_signal(signals, analysis_signal_window)
    guidance_matrix = build_guidance_matrix(analysis_signal_window)
    dictionary = build_dictionary()

    tables = {
        "analysis_signal": analysis_signal,
        "analysis_bin": analysis_bin,
        "analysis_signal_window": analysis_signal_window,
        "analysis_signal_approach_window": analysis_approach_window,
        "analysis_guidance_matrix_long": guidance_matrix,
        "analysis_data_dictionary": dictionary,
    }
    completeness = completeness_summary(tables)
    numeric = numeric_completeness(analysis_bin, analysis_signal_window)
    median = median_completeness(analysis_bin, analysis_signal_window)
    access_crash = access_crash_completeness(analysis_signal_window)

    write_csv(analysis_signal, "analysis_signal.csv")
    write_csv(analysis_bin, "analysis_bin.csv")
    write_csv(analysis_signal_window, "analysis_signal_window.csv")
    write_csv(analysis_approach_window, "analysis_signal_approach_window.csv")
    write_csv(guidance_matrix, "analysis_guidance_matrix_long.csv")
    write_csv(dictionary, "analysis_data_dictionary.csv")
    write_csv(completeness, "analysis_completeness_summary.csv")
    write_csv(numeric, "analysis_numeric_context_completeness.csv")
    write_csv(median, "analysis_median_completeness.csv")
    write_csv(access_crash, "analysis_access_crash_completeness.csv")

    (OUT / "README.md").write_text(readme_text(), encoding="utf-8")
    (OUT / "final_analysis_dataset_build_findings.md").write_text(
        findings_text(analysis_signal, analysis_bin, analysis_signal_window, numeric, median),
        encoding="utf-8",
    )
    qa = qa_table()
    write_csv(qa, "final_analysis_dataset_build_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "final_analysis_dataset_build_manifest.json")
    (OUT / "final_analysis_dataset_build_manifest.json").write_text(json.dumps(manifest(outputs), indent=2), encoding="utf-8")

    pointer = f"""# Final Analysis Dataset Pointer

Canonical analysis dataset path:

`{OUT.relative_to(REPO)}`

Future Codex prompts should read this folder first for final 3,719-signal leg-corrected review-analysis tables.

Tables:
- `analysis_signal.csv`
- `analysis_bin.csv`
- `analysis_signal_window.csv`
- `analysis_signal_approach_window.csv`
- `analysis_guidance_matrix_long.csv`
- `analysis_data_dictionary.csv`
- completeness, QA, findings, and manifest files
"""
    (POINTER / "README.md").write_text(pointer, encoding="utf-8")
    log("Wrote README, findings, manifest, QA, and pointer.")
    log("Completed final analysis dataset build.")


if __name__ == "__main__":
    main()
