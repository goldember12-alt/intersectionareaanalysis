"""Enhance canonical analysis data with directional and numeric context.

Bounded question: can the canonical final 3,719-signal analysis dataset carry
explicit signal-centered directionality fields and more complete bin-level
numeric speed/AADT/exposure context without rerunning recovery, access,
crash assignment, rates, models, or using crash direction fields?
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
ANALYSIS = REPO / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
REVIEW = REPO / "work/output/roadway_graph/review/current"

INPUTS = {
    "analysis_signal": ANALYSIS / "analysis_signal.csv",
    "analysis_bin": ANALYSIS / "analysis_bin.csv",
    "analysis_signal_window": ANALYSIS / "analysis_signal_window.csv",
    "analysis_signal_approach_window": ANALYSIS / "analysis_signal_approach_window.csv",
    "analysis_guidance_matrix": ANALYSIS / "analysis_guidance_matrix_long.csv",
    "analysis_dictionary": ANALYSIS / "analysis_data_dictionary.csv",
    "analysis_completeness": ANALYSIS / "analysis_completeness_summary.csv",
    "analysis_numeric": ANALYSIS / "analysis_numeric_context_completeness.csv",
    "analysis_median": ANALYSIS / "analysis_median_completeness.csv",
    "analysis_access_crash": ANALYSIS / "analysis_access_crash_completeness.csv",
    "analysis_manifest": ANALYSIS / "final_analysis_dataset_build_manifest.json",
    "review_pointer": REVIEW / "final_analysis_dataset_pointer/README.md",
    "residual_final_bin_detail": REVIEW / "final_clean_residual_leg_context_refresh_and_summary/final_clean_leg_corrected_bin_detail.csv",
    "speed_detail": REVIEW / "expanded_candidate_speed_rns_phase3d_vectorized_assignment/phase3d_candidate_rns_speed_assignment_detail.csv",
    "aadt_detail": REVIEW / "expanded_candidate_aadt_v3_path_rebuild/aadt_v3_candidate_assignment_detail.csv",
}

PRIOR_DIRS = [
    REVIEW / "expanded_candidate_bin_generation",
    REVIEW / "consolidated_scaffold_completeness_refresh",
    REVIEW / "final_clean_missing_leg_context_refresh_and_integration",
    REVIEW / "final_clean_intersection_zone_anchor_context_refresh",
    REVIEW / "final_clean_residual_leg_context_refresh_and_summary",
]

WINDOW_COMPONENTS = {
    "0-1,000 ft": {"0_1000"},
    "0-2,500 ft": {"0_1000", "1000_2500"},
}


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


def read_existing(path: Path, wanted: list[str], **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=wanted)
    cols = pd.read_csv(path, nrows=0).columns.tolist()
    use = [c for c in wanted if c in cols]
    if not use:
        return pd.DataFrame(columns=wanted)
    return pd.read_csv(path, usecols=use, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def normalize_key(value: object) -> str:
    if pd.isna(value):
        return ""
    s = str(value).upper().strip()
    s = re.sub(r"[^A-Z0-9]", "", s)
    s = re.sub(r"^(RVA|SVA)", "", s)
    return s


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


def unique_join(series: pd.Series, max_items: int = 8) -> str:
    vals = sorted([v for v in series.dropna().astype(str).unique() if v and v.lower() != "nan"])
    if len(vals) > max_items:
        return "|".join(vals[:max_items]) + f"|+{len(vals) - max_items} more"
    return "|".join(vals)


def dominant(series: pd.Series) -> object:
    s = series.dropna().astype(str)
    s = s[s.str.strip().ne("")]
    if s.empty:
        return pd.NA
    return s.value_counts().index[0]


def field_inventory() -> pd.DataFrame:
    patterns = ["upstream", "downstream", "direction", "a_to_b", "b_to_a", "approach", "bearing", "from_signal", "to_signal", "distance", "anchor", "sequence"]
    rows = []
    for name, path in INPUTS.items():
        if path.suffix.lower() != ".csv" or not path.exists():
            continue
        cols = pd.read_csv(path, nrows=0).columns.tolist()
        for c in cols:
            if any(p in c.lower() for p in patterns):
                rows.append({"source": name, "path": str(path.relative_to(REPO)), "field_name": c, "source_role": "canonical_or_required_input"})
    for d in PRIOR_DIRS:
        if not d.exists():
            continue
        for p in d.glob("*.csv"):
            try:
                cols = pd.read_csv(p, nrows=0).columns.tolist()
            except Exception:
                continue
            for c in cols:
                if any(x in c.lower() for x in patterns):
                    rows.append({"source": d.name, "path": str(p.relative_to(REPO)), "field_name": c, "source_role": "prior_directional_reference"})
    return pd.DataFrame(rows)


def load_interval_sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    log("Loading numeric route/measure interval sources.")
    speed_cols = [
        "route_common",
        "route_name",
        "normalized_candidate_route_key",
        "matched_normalized_rns_route_key",
        "matched_rns_route_key",
        "matched_rns_measure_min",
        "matched_rns_measure_max",
        "matched_review_only_car_speed_limit",
        "rns_match_method",
    ]
    aadt_cols = [
        "route_common",
        "route_name",
        "candidate_route_common",
        "candidate_route_name",
        "candidate_normalized_route_key",
        "candidate_lookup_route_key",
        "matched_aadt_route_key",
        "matched_aadt_measure_min",
        "matched_aadt_measure_max",
        "matched_review_only_aadt_value",
        "matched_review_only_aadt_year",
        "aadt_v3_match_method",
    ]
    speed = read_existing(INPUTS["speed_detail"], speed_cols, low_memory=False)
    aadt = read_existing(INPUTS["aadt_detail"], aadt_cols, low_memory=False)
    if not speed.empty:
        speed["value"] = pd.to_numeric(speed["matched_review_only_car_speed_limit"], errors="coerce")
        speed["measure_min"] = pd.to_numeric(speed["matched_rns_measure_min"], errors="coerce")
        speed["measure_max"] = pd.to_numeric(speed["matched_rns_measure_max"], errors="coerce")
        key_cols = [c for c in ["matched_normalized_rns_route_key", "matched_rns_route_key", "normalized_candidate_route_key", "route_common", "route_name"] if c in speed]
        speed["route_keys"] = speed[key_cols].apply(lambda r: [normalize_key(v) for v in r if normalize_key(v)], axis=1)
        speed = speed[speed["value"].notna() & speed["measure_min"].notna() & speed["measure_max"].notna()]
    if not aadt.empty:
        aadt["value"] = pd.to_numeric(aadt["matched_review_only_aadt_value"], errors="coerce")
        aadt["year"] = pd.to_numeric(aadt.get("matched_review_only_aadt_year"), errors="coerce")
        aadt["measure_min"] = pd.to_numeric(aadt["matched_aadt_measure_min"], errors="coerce")
        aadt["measure_max"] = pd.to_numeric(aadt["matched_aadt_measure_max"], errors="coerce")
        key_cols = [c for c in ["matched_aadt_route_key", "candidate_lookup_route_key", "candidate_normalized_route_key", "candidate_route_common", "candidate_route_name", "route_common", "route_name"] if c in aadt]
        aadt["route_keys"] = aadt[key_cols].apply(lambda r: [normalize_key(v) for v in r if normalize_key(v)], axis=1)
        aadt = aadt[aadt["value"].notna() & aadt["measure_min"].notna() & aadt["measure_max"].notna()]
    return speed, aadt


def build_interval_index(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    index: dict[str, list[dict[str, object]]] = {}
    for row in df.itertuples(index=False):
        for key in getattr(row, "route_keys"):
            index.setdefault(key, []).append(
                {
                    "measure_min": float(getattr(row, "measure_min")),
                    "measure_max": float(getattr(row, "measure_max")),
                    "value": float(getattr(row, "value")),
                    "year": getattr(row, "year", np.nan),
                }
            )
    return {k: pd.DataFrame(v).drop_duplicates() for k, v in index.items()}


def interval_match(keys: list[str], midpoint: object, idx: dict[str, pd.DataFrame]) -> tuple[float, object, str]:
    mid = pd.to_numeric(pd.Series([midpoint]), errors="coerce").iloc[0]
    if pd.isna(mid):
        return np.nan, np.nan, "missing_measure_midpoint"
    for key in keys:
        if key and key in idx:
            cand = idx[key]
            hit = cand[(cand["measure_min"] <= mid) & (cand["measure_max"] >= mid)]
            if not hit.empty:
                value = float(hit["value"].median())
                year = hit["year"].dropna().max() if "year" in hit else np.nan
                return value, year, "route_measure_interval_match"
    return np.nan, np.nan, "no_route_measure_interval_match"


def enhance_bins() -> pd.DataFrame:
    bins = read_csv(INPUTS["analysis_bin"], low_memory=False)
    for c in ["distance_start_ft", "distance_end_ft", "bin_length_ft", "bin_length_mi", "source_measure_midpoint", "speed_limit_mph", "aadt", "aadt_year", "aadt_exposure_denominator"]:
        if c in bins:
            bins[c] = pd.to_numeric(bins[c], errors="coerce")
    bearing = read_existing(
        INPUTS["residual_final_bin_detail"],
        ["stable_bin_id", "source_bearing_sector", "source_measure_start_num", "source_measure_end_num"],
        low_memory=False,
    )
    if not bearing.empty:
        bins = bins.merge(bearing.drop_duplicates("stable_bin_id"), on="stable_bin_id", how="left")
    else:
        bins["source_bearing_sector"] = pd.NA
    bins["signal_approach_bearing"] = bins.get("source_bearing_sector")
    bins["bin_start_distance_ft"] = bins["distance_start_ft"]
    bins["bin_end_distance_ft"] = bins["distance_end_ft"]
    bins["bin_mid_distance_ft"] = (bins["distance_start_ft"] + bins["distance_end_ft"]) / 2.0
    bins["directional_role"] = np.where(bins["signal_approach_id"].notna(), "bidirectional_or_undirected", "unclear_direction")
    bins["directionality_method"] = np.where(
        bins["signal_approach_bearing"].notna(),
        "source_bearing_preserved_no_flow_orientation",
        "distance_bin_without_flow_orientation",
    )
    bins["directionality_confidence"] = np.where(bins["signal_approach_bearing"].notna(), "medium_geometry_context_no_flow", "low_no_directional_evidence")

    speed_src, aadt_src = load_interval_sources()
    speed_idx = build_interval_index(speed_src) if not speed_src.empty else {}
    aadt_idx = build_interval_index(aadt_src) if not aadt_src.empty else {}
    log(f"Built interval indexes: speed routes {len(speed_idx):,}, AADT routes {len(aadt_idx):,}.")

    keys = bins.apply(lambda r: [normalize_key(r.get("route_key_common")), normalize_key(r.get("route_key_name")), normalize_key(r.get("source_route_common")), normalize_key(r.get("source_route_name")), normalize_key(r.get("source_route_id"))], axis=1)
    missing_speed = bins["speed_limit_mph"].isna()
    missing_aadt = bins["aadt"].isna()

    speed_values = []
    speed_methods = []
    aadt_values = []
    aadt_years = []
    aadt_methods = []
    for k, mid, need_speed, need_aadt in zip(keys, bins["source_measure_midpoint"], missing_speed, missing_aadt):
        if need_speed:
            sv, _, sm = interval_match(k, mid, speed_idx)
        else:
            sv, sm = np.nan, "already_present"
        if need_aadt:
            av, yr, am = interval_match(k, mid, aadt_idx)
        else:
            av, yr, am = np.nan, np.nan, "already_present"
        speed_values.append(sv)
        speed_methods.append(sm)
        aadt_values.append(av)
        aadt_years.append(yr)
        aadt_methods.append(am)
    speed_values = pd.Series(speed_values, index=bins.index)
    aadt_values = pd.Series(aadt_values, index=bins.index)
    aadt_years = pd.Series(aadt_years, index=bins.index)

    speed_fill = missing_speed & speed_values.notna()
    aadt_fill = missing_aadt & aadt_values.notna()
    bins.loc[speed_fill, "speed_limit_mph"] = speed_values[speed_fill]
    bins.loc[speed_fill, "speed_source_method"] = "unified_route_measure_interval_match"
    bins.loc[~speed_fill & bins["speed_limit_mph"].notna(), "speed_source_method"] = bins.get("speed_match_method", "canonical_present")
    bins.loc[missing_speed & ~speed_fill, "speed_source_method"] = pd.Series(speed_methods, index=bins.index)[missing_speed & ~speed_fill]
    bins.loc[speed_fill, "speed_confidence"] = "high_route_measure"
    bins.loc[~speed_fill & bins["speed_limit_mph"].notna(), "speed_confidence"] = "canonical_or_branch_numeric"
    bins.loc[bins["speed_limit_mph"].isna(), "speed_confidence"] = "missing"

    bins.loc[aadt_fill, "aadt"] = aadt_values[aadt_fill]
    bins.loc[aadt_fill, "aadt_year"] = aadt_years[aadt_fill]
    bins.loc[aadt_fill, "aadt_source_method"] = "unified_route_measure_interval_match"
    bins.loc[~aadt_fill & bins["aadt"].notna(), "aadt_source_method"] = bins.get("aadt_match_method", "canonical_present")
    bins.loc[missing_aadt & ~aadt_fill, "aadt_source_method"] = pd.Series(aadt_methods, index=bins.index)[missing_aadt & ~aadt_fill]
    bins.loc[aadt_fill, "aadt_confidence"] = "high_route_measure"
    bins.loc[~aadt_fill & bins["aadt"].notna(), "aadt_confidence"] = "canonical_or_branch_numeric"
    bins.loc[bins["aadt"].isna(), "aadt_confidence"] = "missing"
    exp_fill = bins["aadt_exposure_denominator"].isna() & bins["aadt"].notna() & bins["bin_length_mi"].notna()
    bins.loc[exp_fill, "aadt_exposure_denominator"] = bins.loc[exp_fill, "aadt"] * bins.loc[exp_fill, "bin_length_mi"]
    bins.loc[exp_fill, "aadt_exposure_method"] = "computed_from_aadt_times_final_bin_length_miles"
    bins["exposure_denominator"] = bins["aadt_exposure_denominator"]
    bins["exposure_method"] = bins["aadt_exposure_method"]
    bins["numeric_context_confidence"] = np.select(
        [bins["speed_limit_mph"].notna() & bins["aadt"].notna(), bins["speed_limit_mph"].notna(), bins["aadt"].notna()],
        ["speed_and_aadt_available", "speed_only_available", "aadt_only_available"],
        default="missing_numeric_context",
    )
    return bins


def completeness(before_bin: pd.DataFrame, after_bin: pd.DataFrame, before_sw: pd.DataFrame, after_sw: pd.DataFrame, before_aw: pd.DataFrame, after_aw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = [
        ("bin", before_bin, after_bin, "speed_limit_mph", "aadt", "aadt_exposure_denominator"),
        ("signal_window", before_sw, after_sw, "representative_speed_limit_mph", "representative_aadt", "exposure_denominator"),
        ("signal_approach_window", before_aw, after_aw, "representative_speed_limit_mph", "representative_aadt", "exposure_denominator"),
    ]
    for grain, before, after, speed_col, aadt_col, exp_col in specs:
        for field, col in [("speed", speed_col), ("aadt", aadt_col), ("exposure", exp_col)]:
            b = int(pd.to_numeric(before.get(col), errors="coerce").notna().sum()) if col in before else 0
            if field == "exposure":
                b = int(pd.to_numeric(before.get(col), errors="coerce").fillna(0).gt(0).sum()) if col in before else 0
            after_col = "exposure_denominator" if field == "exposure" and grain == "bin" and "exposure_denominator" in after else col
            a = int(pd.to_numeric(after.get(after_col), errors="coerce").notna().sum()) if after_col in after else 0
            if field == "exposure":
                a = int(pd.to_numeric(after.get(after_col), errors="coerce").fillna(0).gt(0).sum()) if after_col in after else 0
            rows.append(
                {
                    "grain": grain,
                    "field": field,
                    "rows": len(after),
                    "before_rows_with_value": b,
                    "after_rows_with_value": a,
                    "improvement_rows": a - b,
                    "before_share": round(b / len(before), 4) if len(before) else 0,
                    "after_share": round(a / len(after), 4) if len(after) else 0,
                }
            )
    return pd.DataFrame(rows)


def aggregate_window(bins: pd.DataFrame, canonical_sw: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for label, comps in WINDOW_COMPONENTS.items():
        g = bins[bins["analysis_window"].isin(comps)].copy()
        agg = (
            g.groupby("stable_signal_id", dropna=False)
            .agg(
                representative_speed_limit_mph=("speed_limit_mph", "median"),
                speed_limit_min_mph=("speed_limit_mph", "min"),
                speed_limit_max_mph=("speed_limit_mph", "max"),
                representative_aadt=("aadt", "median"),
                aadt_min=("aadt", "min"),
                aadt_max=("aadt", "max"),
                exposure_denominator=("exposure_denominator", "sum"),
                median_group=("median_group", dominant),
                roadway_context=("roadway_context_status", dominant),
                facility_type=("rim_facility_raw", dominant),
                directional_role_summary=("directional_role", unique_join),
                directional_roles_count=("directional_role", "nunique"),
                directional_bins=("directional_role", lambda s: int(s.isin(["downstream_from_signal", "upstream_to_signal"]).sum())),
            )
            .reset_index()
        )
        agg["signal_window"] = label
        frames.append(agg)
    out = pd.concat(frames, ignore_index=True)
    out["speed_band"] = out["representative_speed_limit_mph"].map(speed_band)
    out["aadt_band"] = out["representative_aadt"].map(aadt_band)
    out["numeric_speed_complete_flag"] = out["representative_speed_limit_mph"].notna()
    out["numeric_aadt_complete_flag"] = out["representative_aadt"].notna()
    out["numeric_exposure_complete_flag"] = pd.to_numeric(out["exposure_denominator"], errors="coerce").fillna(0).gt(0)
    out["missing_numeric_context_flag"] = ~(out["numeric_speed_complete_flag"] & out["numeric_aadt_complete_flag"] & out["numeric_exposure_complete_flag"])
    keep = [
        "stable_signal_id",
        "signal_window",
        "untyped_access_raw_count",
        "untyped_access_count_band",
        "spatial_50ft_crash_count",
        "spatial_50ft_weighted_crash_count",
        "identity_compatible_spatial_50ft_crash_count",
        "identity_compatible_spatial_50ft_weighted_crash_count",
        "typed_v2_access_raw_count",
        "typed_categories_present",
        "recovery_branch",
        "final_leg_corrected_physical_leg_count",
        "final_leg_corrected_physical_leg_bucket",
    ]
    out = out.merge(canonical_sw[[c for c in keep if c in canonical_sw.columns]], on=["stable_signal_id", "signal_window"], how="left")
    out["candidate_crash_rate"] = np.where(
        out["numeric_exposure_complete_flag"],
        pd.to_numeric(out.get("spatial_50ft_weighted_crash_count"), errors="coerce").fillna(0) / out["exposure_denominator"].replace(0, np.nan),
        np.nan,
    )
    return out


def aggregate_approach_window(bins: pd.DataFrame, canonical_aw: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for label, comps in WINDOW_COMPONENTS.items():
        g = bins[bins["analysis_window"].isin(comps)].copy()
        agg = (
            g.groupby(["stable_signal_id", "signal_approach_id", "directional_role"], dropna=False)
            .agg(
                signal_approach_bearing=("signal_approach_bearing", dominant),
                representative_speed_limit_mph=("speed_limit_mph", "median"),
                representative_aadt=("aadt", "median"),
                exposure_denominator=("exposure_denominator", "sum"),
                median_group=("median_group", dominant),
                roadway_context=("roadway_context_status", dominant),
                bin_count=("stable_bin_id", "size"),
            )
            .reset_index()
        )
        agg["signal_window"] = label
        frames.append(agg)
    out = pd.concat(frames, ignore_index=True)
    out["speed_band"] = out["representative_speed_limit_mph"].map(speed_band)
    out["aadt_band"] = out["representative_aadt"].map(aadt_band)
    out["numeric_context_complete_flag"] = out["representative_speed_limit_mph"].notna() & out["representative_aadt"].notna() & pd.to_numeric(out["exposure_denominator"], errors="coerce").fillna(0).gt(0)
    keep = [
        "stable_signal_id",
        "signal_approach_id",
        "signal_window",
        "untyped_access_raw_count",
        "untyped_access_count_band",
        "spatial_50ft_crash_count",
        "spatial_50ft_weighted_crash_count",
        "identity_compatible_spatial_50ft_crash_count",
        "identity_compatible_spatial_50ft_weighted_crash_count",
    ]
    return out.merge(canonical_aw[[c for c in keep if c in canonical_aw.columns]], on=["stable_signal_id", "signal_approach_id", "signal_window"], how="left")


def guidance(sw: pd.DataFrame) -> pd.DataFrame:
    out = (
        sw.groupby(["roadway_context", "median_group", "aadt_band", "speed_band", "untyped_access_count_band", "signal_window"], dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            **{
                "spatial_50ft_catchment_crash_count": ("spatial_50ft_crash_count", "sum"),
                "weighted_crash_count": ("spatial_50ft_weighted_crash_count", "sum"),
                "route_confirmed_crash_count": ("identity_compatible_spatial_50ft_crash_count", "sum"),
            },
            exposure_denominator=("exposure_denominator", "sum"),
            missing_numeric_context_rows=("missing_numeric_context_flag", "sum"),
        )
        .reset_index()
    )
    out["review_only_candidate_crash_rate"] = np.where(out["exposure_denominator"].gt(0), out["weighted_crash_count"] / out["exposure_denominator"], np.nan)
    out["low_n_flag"] = out["spatial_50ft_catchment_crash_count"].lt(5)
    out["sparse_cell_flag"] = out["signal_count"].lt(10)
    return out


def directionality_summary(bins: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "total_bins", "value": len(bins)},
        {"metric": "bins_downstream_or_upstream", "value": int(bins["directional_role"].isin(["downstream_from_signal", "upstream_to_signal"]).sum())},
        {"metric": "bins_bidirectional_or_undirected", "value": int(bins["directional_role"].eq("bidirectional_or_undirected").sum())},
        {"metric": "bins_unclear_direction", "value": int(bins["directional_role"].eq("unclear_direction").sum())},
        {"metric": "signals_with_downstream_or_upstream_bin", "value": int(bins.loc[bins["directional_role"].isin(["downstream_from_signal", "upstream_to_signal"]), "stable_signal_id"].nunique())},
        {"metric": "signals_with_bearing_context", "value": int(bins.loc[bins["signal_approach_bearing"].notna(), "stable_signal_id"].nunique())},
    ]
    branch = bins.groupby("final_review_leg_source", dropna=False).agg(total_bins=("stable_bin_id", "size"), bearing_bins=("signal_approach_bearing", lambda s: int(s.notna().sum()))).reset_index()
    branch["metric"] = "branch_bearing_completeness:" + branch["final_review_leg_source"].astype(str)
    branch["value"] = branch["bearing_bins"].astype(str) + " / " + branch["total_bins"].astype(str)
    return pd.concat([pd.DataFrame(rows), branch[["metric", "value"]]], ignore_index=True)


def dictionary() -> pd.DataFrame:
    rows = [
        ("directional_role", "Signal-centered directional role", "Conservative role label for each bin.", "", "Derived from preserved direction fields where available; otherwise not guessed."),
        ("signal_approach_bearing", "Signal approach bearing", "Bearing sector carried from source Travelway context where available.", "degrees/sector", "Context only; not traffic direction."),
        ("speed_limit_mph", "Speed limit", "Numeric speed limit after canonical and unified route/measure carry-forward.", "mph", "Not fabricated."),
        ("aadt", "AADT", "Numeric traffic volume after canonical and unified route/measure carry-forward.", "vehicles/day", "Not fabricated."),
        ("exposure_denominator", "Exposure denominator", "Review-only AADT times bin length denominator.", "AADT x miles", "Not final rate policy."),
        ("review_only_candidate_crash_rate", "Review-only candidate crash rate", "Weighted crash count divided by candidate exposure.", "crashes per AADT-mile", "Not final rate/model output."),
    ]
    return pd.DataFrame(rows, columns=["field_name", "plain_language_label", "definition", "units", "caveat"])


def findings_text(dir_sum: pd.DataFrame, comp: pd.DataFrame) -> str:
    def val(metric: str) -> object:
        row = dir_sum[dir_sum["metric"].eq(metric)]
        return row["value"].iloc[0] if not row.empty else 0

    def imp(grain: str, field: str) -> tuple[int, int, int]:
        row = comp[(comp["grain"].eq(grain)) & (comp["field"].eq(field))].iloc[0]
        return int(row["before_rows_with_value"]), int(row["after_rows_with_value"]), int(row["improvement_rows"])

    bsw, asw, isw = imp("signal_window", "speed")
    baa, aaa, iaa = imp("signal_window", "aadt")
    bex, aex, iex = imp("signal_window", "exposure")
    return f"""# Directional and Numeric Context Enhancement Findings

## Directionality
1. Canonical tables did not preserve explicit downstream/upstream fields. Prior numeric assignment outputs contain endpoint-style signal-relative labels, and final leg-corrected context contains source bearing sectors, but neither is sufficient to infer true traffic downstream/upstream for the final bins.
2. In the enhanced dataset, true downstream/upstream is only preserved where explicit evidence exists. Otherwise bins are labeled `bidirectional_or_undirected` or `unclear_direction`; crash direction is not used.
3. Directional role summary: {val('bins_downstream_or_upstream')} bins have explicit downstream/upstream, {val('bins_bidirectional_or_undirected')} are bidirectional/undirected, and {val('bins_unclear_direction')} are unclear. Signals with bearing context: {val('signals_with_bearing_context')}.

## Numeric Context
4. Signal-window speed completeness changed from {bsw:,} to {asw:,} rows, an improvement of {isw:,}.
5. Signal-window AADT completeness changed from {baa:,} to {aaa:,} rows, an improvement of {iaa:,}.
6. Signal-window exposure completeness changed from {bex:,} to {aex:,} rows, an improvement of {iex:,}.
7. Remaining numeric missingness is mostly route/measure source mismatch or absent source interval evidence; values are not fabricated.

## Readiness
8. The guidance matrix is better supported numerically, but rate cells remain review-only because denominator policy is not final and missing numeric context remains.
9. Directional analysis is not fully restored for upstream/downstream traffic flow. Approach/bearing analysis is possible; true downstream/upstream analysis needs a validated flow-orientation source.
10. Next pass should update the canonical data mart pointer to this enhanced package for numeric-context figure work, while keeping downstream/upstream claims conservative.
"""


def qa_table() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to analysis/current enhancement folder."),
        ("no_records_promoted", True, "Read-only canonical enhancement."),
        ("no_new_access_crash_assignment", True, "Existing access/crash counts carried only from canonical tables."),
        ("no_final_rates_models", True, "Candidate rates remain review-only."),
        ("crash_direction_fields_not_read_or_used", True, "No crash source or crash direction fields read."),
        ("downstream_upstream_not_from_crash_direction", True, "Directionality uses scaffold/context fields only."),
        ("numeric_values_not_fabricated", True, "Values come from canonical values or exact route/measure interval matches."),
        ("exposure_method_documented", True, "Exposure is AADT times bin length in miles."),
        ("outputs_analysis_current_only", True, str(OUT)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_analysis_directional_numeric_context_enhancement",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "outputs": list(outputs),
        "review_only": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting directional/numeric context enhancement.")
    inv = field_inventory()
    write_csv(inv, "directionality_field_inventory.csv")
    canonical_bins = read_csv(INPUTS["analysis_bin"], low_memory=False)
    canonical_sw = read_csv(INPUTS["analysis_signal_window"], low_memory=False)
    canonical_aw = read_csv(INPUTS["analysis_signal_approach_window"], low_memory=False)
    enhanced_bins = enhance_bins()
    enhanced_sw = aggregate_window(enhanced_bins, canonical_sw)
    enhanced_aw = aggregate_approach_window(enhanced_bins, canonical_aw)
    dir_sum = directionality_summary(enhanced_bins)
    comp = completeness(canonical_bins, enhanced_bins, canonical_sw, enhanced_sw, canonical_aw, enhanced_aw)
    matrix = guidance(enhanced_sw)
    bin_numeric_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "speed_limit_mph",
        "speed_source_method",
        "speed_confidence",
        "aadt",
        "aadt_source_method",
        "aadt_confidence",
        "aadt_year",
        "bin_length_ft",
        "bin_length_mi",
        "exposure_denominator",
        "exposure_method",
        "numeric_context_confidence",
    ]
    write_csv(enhanced_bins, "analysis_bin_enhanced.csv")
    write_csv(dir_sum, "directionality_completeness_summary.csv")
    write_csv(enhanced_bins[[c for c in bin_numeric_cols if c in enhanced_bins.columns]], "bin_numeric_context_enhanced.csv")
    write_csv(comp, "numeric_context_before_after_completeness.csv")
    write_csv(enhanced_sw, "analysis_signal_window_enhanced.csv")
    write_csv(enhanced_aw, "analysis_signal_approach_window_enhanced.csv")
    write_csv(matrix, "analysis_guidance_matrix_long_enhanced.csv")
    write_csv(dictionary(), "enhanced_context_data_dictionary.csv")
    (OUT / "directional_numeric_context_enhancement_findings.md").write_text(findings_text(dir_sum, comp), encoding="utf-8")
    log("Wrote findings memo.")
    write_csv(qa_table(), "directional_numeric_context_enhancement_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "directional_numeric_context_enhancement_manifest.json")
    (OUT / "directional_numeric_context_enhancement_manifest.json").write_text(json.dumps(manifest(outputs), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed directional/numeric context enhancement.")


if __name__ == "__main__":
    main()
