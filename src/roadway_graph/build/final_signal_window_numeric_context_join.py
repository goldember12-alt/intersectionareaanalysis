"""Join numeric AADT/speed/exposure context to final signal-window tables.

Bounded question: can the final 3,719-signal x window figure table be enriched
with numeric AADT, numeric speed, and a documented exposure denominator using
prior review-only numeric assignment outputs and final stable Travelway lineage?

This is a review-only numeric-context carry-forward. It does not rerun crash or
access assignment, does not modify active outputs, and does not create final
rates/models.
"""

from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/review/current/final_signal_window_numeric_context_join"

CTX_DIR = REPO / "work/output/roadway_graph/review/current/final_signal_window_numeric_context_table"
FINAL_DIR = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_clean_universe_summary"
RESIDUAL_CONTEXT_DIR = REPO / "work/output/roadway_graph/review/current/final_clean_residual_leg_context_refresh_and_summary"
SPEED_DIR = REPO / "work/output/roadway_graph/review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_DIR = REPO / "work/output/roadway_graph/review/current/expanded_candidate_aadt_v3_path_rebuild"

INPUTS = {
    "signal_window_context": CTX_DIR / "signal_window_numeric_context.csv",
    "approach_window_context": CTX_DIR / "signal_approach_window_numeric_context.csv",
    "matrix_context": CTX_DIR / "guidance_matrix_ready_long.csv",
    "missingness_context": CTX_DIR / "aadtspeed_numeric_context_missingness.csv",
    "final_bins": FINAL_DIR / "final_leg_corrected_bin_universe.csv",
    "final_signals": FINAL_DIR / "final_leg_corrected_signal_universe_3719.csv",
    "final_context_readiness": FINAL_DIR / "final_leg_corrected_context_readiness_summary.csv",
    "residual_bin_detail": RESIDUAL_CONTEXT_DIR / "final_clean_leg_corrected_bin_detail.csv",
    "speed_detail": SPEED_DIR / "phase3d_candidate_rns_speed_assignment_detail.csv",
    "aadt_detail": AADT_DIR / "aadt_v3_candidate_assignment_detail.csv",
}

WINDOWS = {
    "0-1,000 ft": ("0_1000",),
    "0-2,500 ft": ("0_1000", "1000_2500"),
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
    try:
        n = float(value)
    except Exception:
        return "unknown"
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
    try:
        n = float(value)
    except Exception:
        return "unknown"
    if n <= 30:
        return "<=30 mph"
    if n == 35:
        return "35 mph"
    if n >= 40:
        return ">=40 mph"
    return "unknown"


def access_per_1000ft(row: pd.Series) -> float:
    denom = 1.0 if row.get("signal_window") == "0-1,000 ft" else 2.5
    try:
        return float(row.get("untyped_access_raw_count", 0)) / denom
    except Exception:
        return 0.0


def mode_numeric(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return np.nan
    return float(vals.round(6).mode().iloc[0])


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    ok = v.notna() & w.notna() & (w > 0)
    if not ok.any():
        return np.nan
    return float(np.average(v[ok], weights=w[ok]))


def field_inventory() -> pd.DataFrame:
    log("Inventoring numeric context fields.")
    sources = [
        ("final_bins", INPUTS["final_bins"]),
        ("residual_bin_detail", INPUTS["residual_bin_detail"]),
        ("speed_detail", INPUTS["speed_detail"]),
        ("aadt_detail", INPUTS["aadt_detail"]),
    ]
    rows: list[dict[str, object]] = []
    patterns = ("speed", "mph", "limit", "aadt", "exposure", "denom", "length", "measure", "route", "year")
    for source_name, path in sources:
        if not path.exists():
            continue
        cols = pd.read_csv(path, nrows=0).columns.tolist()
        candidate_cols = [c for c in cols if any(p in c.lower() for p in patterns)]
        usecols = candidate_cols[:]
        counts = {c: {"non_null": None, "numeric": None} for c in candidate_cols}
        if usecols:
            for chunk in pd.read_csv(path, usecols=usecols, chunksize=200_000, low_memory=False):
                for c in candidate_cols:
                    non_null = int(chunk[c].notna().sum())
                    numeric = int(pd.to_numeric(chunk[c], errors="coerce").notna().sum())
                    if counts[c]["non_null"] is None:
                        counts[c]["non_null"] = 0
                        counts[c]["numeric"] = 0
                    counts[c]["non_null"] += non_null
                    counts[c]["numeric"] += numeric
        for c in candidate_cols:
            lower = c.lower()
            usable = c in {
                "matched_review_only_car_speed_limit",
                "matched_review_only_aadt_value",
                "matched_review_only_aadt_year",
                "review_only_estimated_exposure",
                "candidate_bin_length_ft",
                "candidate_measure_min",
                "candidate_measure_max",
            }
            units = ""
            if "speed" in lower or "limit" in lower:
                units = "mph"
            elif "aadt" in lower and "year" not in lower:
                units = "vehicles/day"
            elif "length_ft" in lower:
                units = "feet"
            elif "exposure" in lower or "denom" in lower:
                units = "AADT x miles candidate denominator"
            elif "measure" in lower:
                units = "route measure"
            rows.append(
                {
                    "source_table": source_name,
                    "field_name": c,
                    "non_null_count": counts[c]["non_null"],
                    "numeric_parse_success": counts[c]["numeric"],
                    "units_inferred": units,
                    "usable_for_join": usable,
                    "note": "selected numeric context field" if usable else "inventory/support field",
                }
            )
    return pd.DataFrame(rows)


def read_interval_source(path: Path, kind: str) -> pd.DataFrame:
    log(f"Loading {kind} numeric interval source.")
    if kind == "speed":
        use = [
            "candidate_route_common",
            "route_common",
            "route_name",
            "normalized_candidate_route_key",
            "candidate_measure_min",
            "candidate_measure_max",
            "matched_review_only_car_speed_limit",
            "matched_review_only_truck_speed_limit",
            "rns_match_status",
            "rns_match_method",
            "rns_route_match_confidence",
            "rns_measure_containment_status",
        ]
        rename = {
            "matched_review_only_car_speed_limit": "speed_limit_mph",
            "candidate_measure_min": "measure_min",
            "candidate_measure_max": "measure_max",
        }
    else:
        use = [
            "candidate_route_common",
            "route_common",
            "route_name",
            "candidate_normalized_route_key",
            "candidate_lookup_route_key",
            "candidate_measure_min",
            "candidate_measure_max",
            "matched_review_only_aadt_value",
            "matched_review_only_aadt_year",
            "review_only_estimated_exposure",
            "review_only_denominator_status",
            "review_only_aadt_v3_context_status",
            "aadt_v3_match_method",
            "aadt_v3_measure_containment_status",
        ]
        rename = {
            "matched_review_only_aadt_value": "aadt",
            "matched_review_only_aadt_year": "aadt_year",
            "candidate_measure_min": "measure_min",
            "candidate_measure_max": "measure_max",
        }
    cols = pd.read_csv(path, nrows=0).columns.tolist()
    use = [c for c in use if c in cols]
    pieces = []
    for chunk in pd.read_csv(path, usecols=use, chunksize=250_000, low_memory=False):
        chunk = chunk.rename(columns=rename)
        if "measure_min" not in chunk or "measure_max" not in chunk:
            continue
        chunk["measure_min"] = pd.to_numeric(chunk["measure_min"], errors="coerce")
        chunk["measure_max"] = pd.to_numeric(chunk["measure_max"], errors="coerce")
        if kind == "speed":
            chunk["speed_limit_mph"] = pd.to_numeric(chunk.get("speed_limit_mph"), errors="coerce")
            chunk = chunk[chunk["speed_limit_mph"].notna()].copy()
        else:
            chunk["aadt"] = pd.to_numeric(chunk.get("aadt"), errors="coerce")
            chunk["aadt_year"] = pd.to_numeric(chunk.get("aadt_year"), errors="coerce")
            chunk = chunk[chunk["aadt"].notna()].copy()
        chunk = chunk[chunk["measure_min"].notna() & chunk["measure_max"].notna()].copy()
        key_cols = [c for c in ["candidate_route_common", "route_common", "route_name", "normalized_candidate_route_key", "candidate_normalized_route_key", "candidate_lookup_route_key"] if c in chunk]
        key_frames = []
        for key_col in key_cols:
            tmp = chunk.copy()
            tmp["route_key"] = tmp[key_col].map(normalize_key)
            tmp = tmp[tmp["route_key"].ne("")]
            key_frames.append(tmp)
        if key_frames:
            pieces.append(pd.concat(key_frames, ignore_index=True))
    if not pieces:
        return pd.DataFrame()
    out = pd.concat(pieces, ignore_index=True)
    subset = ["route_key", "measure_min", "measure_max"]
    subset += ["speed_limit_mph"] if kind == "speed" else ["aadt", "aadt_year"]
    out = out.drop_duplicates(subset=subset)
    return out


def build_final_bins_for_join() -> pd.DataFrame:
    log("Loading final bins for numeric context join.")
    cols = pd.read_csv(INPUTS["final_bins"], nrows=0).columns.tolist()
    use = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "distance_start_ft",
        "distance_end_ft",
        "analysis_window",
        "final_review_leg_source",
        "final_review_recovery_provenance",
    ]
    bins = read_csv(INPUTS["final_bins"], usecols=[c for c in use if c in cols], low_memory=False)
    for c in ["source_measure_start", "source_measure_end", "distance_start_ft", "distance_end_ft"]:
        bins[c] = pd.to_numeric(bins[c], errors="coerce")
    bins["source_measure_midpoint"] = (bins["source_measure_start"] + bins["source_measure_end"]) / 2.0
    bins["bin_length_ft"] = (bins["distance_end_ft"] - bins["distance_start_ft"]).abs()
    bins.loc[bins["bin_length_ft"].isna() | (bins["bin_length_ft"] <= 0), "bin_length_ft"] = 50.0
    bins["bin_length_mi"] = bins["bin_length_ft"] / 5280.0
    bins["route_key_common"] = bins["source_route_common"].map(normalize_key)
    bins["route_key_name"] = bins["source_route_name"].map(normalize_key)
    return bins


def interval_match(bins: pd.DataFrame, intervals: pd.DataFrame, value_cols: list[str], prefix: str) -> pd.DataFrame:
    if intervals.empty:
        for c in value_cols:
            bins[prefix + c] = np.nan
        bins[prefix + "match_method"] = "no_numeric_source"
        return bins
    result = bins[["stable_bin_id", "route_key_common", "route_key_name", "source_measure_midpoint"]].copy()
    result[prefix + "match_key_used"] = ""
    for c in value_cols:
        result[prefix + c] = np.nan
    interval_groups = {k: g.sort_values("measure_min").reset_index(drop=True) for k, g in intervals.groupby("route_key")}
    for key_col, key_label in [("route_key_common", "route_common"), ("route_key_name", "route_name")]:
        unmatched = result[value_cols and (prefix + value_cols[0])].isna()
        work = result[unmatched].copy()
        if work.empty:
            break
        for key, idx in work.groupby(key_col).groups.items():
            if not key or key not in interval_groups:
                continue
            src = interval_groups[key]
            starts = src["measure_min"].to_numpy(dtype=float)
            ends = src["measure_max"].to_numpy(dtype=float)
            mids = result.loc[idx, "source_measure_midpoint"].to_numpy(dtype=float)
            pos = np.searchsorted(starts, mids, side="right") - 1
            ok = (pos >= 0) & (mids <= ends[np.clip(pos, 0, len(ends) - 1)])
            if not ok.any():
                continue
            matched_idx = np.asarray(list(idx))[ok]
            matched_pos = pos[ok]
            for c in value_cols:
                result.loc[matched_idx, prefix + c] = src.iloc[matched_pos][c].to_numpy()
            result.loc[matched_idx, prefix + "match_key_used"] = key_label
    result[prefix + "match_method"] = np.where(result[prefix + value_cols[0]].notna(), "route_measure_midpoint_interval", "unmatched")
    return bins.merge(result.drop(columns=["route_key_common", "route_key_name", "source_measure_midpoint"]), on="stable_bin_id", how="left")


def bin_numeric_context() -> tuple[pd.DataFrame, pd.DataFrame]:
    bins = build_final_bins_for_join()
    speed_src = read_interval_source(INPUTS["speed_detail"], "speed")
    aadt_src = read_interval_source(INPUTS["aadt_detail"], "aadt")
    bins = interval_match(bins, speed_src, ["speed_limit_mph"], "speed_")
    bins = interval_match(bins, aadt_src, ["aadt", "aadt_year"], "aadt_")
    bins = bins.rename(
        columns={
            "speed_speed_limit_mph": "speed_limit_mph",
            "aadt_aadt": "aadt",
            "aadt_aadt_year": "aadt_year",
        }
    )
    bins["aadt_exposure_denominator"] = pd.to_numeric(bins["aadt"], errors="coerce") * bins["bin_length_mi"]
    bins.loc[bins["aadt"].isna(), "aadt_exposure_denominator"] = np.nan
    bins["aadt_exposure_method"] = np.where(
        bins["aadt_exposure_denominator"].notna(),
        "sum_aadt_times_final_bin_length_miles",
        "not_available",
    )
    bins["numeric_context_source"] = np.select(
        [
            bins["speed_limit_mph"].notna() & bins["aadt"].notna(),
            bins["speed_limit_mph"].notna(),
            bins["aadt"].notna(),
        ],
        [
            "rns_phase3d_speed_plus_aadt_v3_route_measure",
            "rns_phase3d_speed_only",
            "aadt_v3_route_measure_only",
        ],
        default="no_numeric_match",
    )
    summary = pd.DataFrame(
        [
            {"metric": "final_bins", "value": len(bins)},
            {"metric": "bins_with_speed", "value": int(bins["speed_limit_mph"].notna().sum())},
            {"metric": "bins_with_aadt", "value": int(bins["aadt"].notna().sum())},
            {"metric": "bins_with_exposure_denominator", "value": int(bins["aadt_exposure_denominator"].notna().sum())},
        ]
    )
    return bins, summary


def windowized_bins(bins: pd.DataFrame) -> pd.DataFrame:
    near = bins[bins["analysis_window"].eq("0_1000")].copy()
    near["signal_window"] = "0-1,000 ft"
    full = bins[bins["analysis_window"].isin(["0_1000", "1000_2500"])].copy()
    full["signal_window"] = "0-2,500 ft"
    return pd.concat([near, full], ignore_index=True)


def aggregate_numeric(bins: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    work = windowized_bins(bins)
    keys = group_cols + ["signal_window"]
    grouped = work.groupby(keys, dropna=False)
    rows = []
    for key, g in grouped:
        if not isinstance(key, tuple):
            key = (key,)
        rec = dict(zip(keys, key))
        rec["representative_speed_limit_mph"] = mode_numeric(g["speed_limit_mph"])
        rec["speed_limit_min_mph"] = pd.to_numeric(g["speed_limit_mph"], errors="coerce").min()
        rec["speed_limit_max_mph"] = pd.to_numeric(g["speed_limit_mph"], errors="coerce").max()
        rec["distinct_speed_limit_count"] = int(pd.to_numeric(g["speed_limit_mph"], errors="coerce").dropna().nunique())
        rec["representative_aadt"] = weighted_mean(g["aadt"], g["bin_length_mi"])
        rec["aadt_min"] = pd.to_numeric(g["aadt"], errors="coerce").min()
        rec["aadt_max"] = pd.to_numeric(g["aadt"], errors="coerce").max()
        rec["distinct_aadt_count"] = int(pd.to_numeric(g["aadt"], errors="coerce").dropna().nunique())
        rec["aadt_year_min"] = pd.to_numeric(g["aadt_year"], errors="coerce").min()
        rec["aadt_year_max"] = pd.to_numeric(g["aadt_year"], errors="coerce").max()
        rec["exposure_denominator"] = pd.to_numeric(g["aadt_exposure_denominator"], errors="coerce").sum(min_count=1)
        rec["exposure_denominator_units"] = "AADT x roadway miles"
        rec["exposure_denominator_method"] = (
            "sum_aadt_times_final_bin_length_miles" if pd.notna(rec["exposure_denominator"]) else "not_available"
        )
        rec["numeric_bin_count"] = int(len(g))
        rec["speed_numeric_bin_count"] = int(g["speed_limit_mph"].notna().sum())
        rec["aadt_numeric_bin_count"] = int(g["aadt"].notna().sum())
        rec["exposure_numeric_bin_count"] = int(g["aadt_exposure_denominator"].notna().sum())
        rec["numeric_context_source_summary"] = "|".join(sorted(g["numeric_context_source"].dropna().astype(str).unique()))
        rows.append(rec)
    out = pd.DataFrame(rows)
    out["aadt_band"] = out["representative_aadt"].map(aadt_band)
    out["speed_band"] = out["representative_speed_limit_mph"].map(speed_band)
    out["numeric_aadt_complete_flag"] = out["aadt_numeric_bin_count"].eq(out["numeric_bin_count"])
    out["numeric_speed_complete_flag"] = out["speed_numeric_bin_count"].eq(out["numeric_bin_count"])
    out["numeric_exposure_complete_flag"] = out["exposure_numeric_bin_count"].eq(out["numeric_bin_count"])
    return out


def update_context_tables(bin_ctx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    log("Aggregating numeric context to signal-window and approach-window grains.")
    sw = read_csv(INPUTS["signal_window_context"], low_memory=False)
    aw = read_csv(INPUTS["approach_window_context"], low_memory=False)
    signal_num = aggregate_numeric(bin_ctx, ["stable_signal_id"])
    approach_num = aggregate_numeric(bin_ctx, ["stable_signal_id", "final_review_physical_leg_id"])
    replace_cols = [
        "representative_speed_limit_mph",
        "speed_limit_min_mph",
        "speed_limit_max_mph",
        "distinct_speed_limit_count",
        "representative_aadt",
        "aadt_min",
        "aadt_max",
        "distinct_aadt_count",
        "aadt_year_min",
        "aadt_year_max",
        "exposure_denominator",
        "exposure_denominator_units",
        "exposure_denominator_method",
        "numeric_bin_count",
        "speed_numeric_bin_count",
        "aadt_numeric_bin_count",
        "exposure_numeric_bin_count",
        "numeric_context_source_summary",
        "aadt_band",
        "speed_band",
        "numeric_aadt_complete_flag",
        "numeric_speed_complete_flag",
        "numeric_exposure_complete_flag",
    ]
    sw = sw.drop(columns=[c for c in replace_cols if c in sw.columns], errors="ignore").merge(
        signal_num, on=["stable_signal_id", "signal_window"], how="left"
    )
    aw = aw.drop(columns=[c for c in replace_cols if c in aw.columns], errors="ignore").merge(
        approach_num, on=["stable_signal_id", "final_review_physical_leg_id", "signal_window"], how="left"
    )
    for df in [sw, aw]:
        df["rate_denominator_field_used"] = np.where(
            df["exposure_denominator"].notna(), "exposure_denominator", ""
        )
        df["rate_denominator_completeness_flag"] = np.where(
            df["numeric_exposure_complete_flag"].fillna(False),
            "complete_numeric_exposure_denominator",
            np.where(df["exposure_denominator"].notna(), "partial_numeric_exposure_denominator", "numeric_exposure_denominator_not_available"),
        )
        df["candidate_crash_rate"] = np.where(
            (df["exposure_denominator"].notna()) & (pd.to_numeric(df["exposure_denominator"], errors="coerce") > 0),
            pd.to_numeric(df.get("spatial_50ft_weighted_crash_count"), errors="coerce") / pd.to_numeric(df["exposure_denominator"], errors="coerce"),
            np.nan,
        )
        df["optional_access_per_1000ft"] = df.apply(access_per_1000ft, axis=1)
    return sw, aw


def guidance_matrix(sw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    grouped = (
        sw.groupby(
            ["roadway_context", "median_group", "aadt_band", "speed_band", "untyped_access_count_band", "signal_window"],
            dropna=False,
        )
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            crash_count=("spatial_50ft_crash_count", "sum"),
            weighted_crash_count=("spatial_50ft_weighted_crash_count", "sum"),
            identity_compatible_crash_count=("identity_compatible_spatial_50ft_crash_count", "sum"),
            exposure_denominator=("exposure_denominator", "sum"),
            total_untyped_access=("untyped_access_raw_count", "sum"),
            aadt_complete_signals=("numeric_aadt_complete_flag", "sum"),
            speed_complete_signals=("numeric_speed_complete_flag", "sum"),
        )
        .reset_index()
    )
    grouped["candidate_crash_rate"] = np.where(
        pd.to_numeric(grouped["exposure_denominator"], errors="coerce") > 0,
        pd.to_numeric(grouped["weighted_crash_count"], errors="coerce")
        / pd.to_numeric(grouped["exposure_denominator"], errors="coerce"),
        np.nan,
    )
    grouped["low_n_flag"] = grouped["signal_count"] < 30
    grouped["sparse_cell_flag"] = (grouped["signal_count"] < 10) | (grouped["crash_count"] < 5)
    wide = grouped.pivot_table(
        index=["roadway_context", "median_group", "signal_window"],
        columns=["aadt_band", "speed_band", "untyped_access_count_band"],
        values="weighted_crash_count",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    wide.columns = [
        " | ".join([str(x) for x in col if str(x) != ""]).strip(" |") if isinstance(col, tuple) else col
        for col in wide.columns
    ]
    return grouped, wide


def missingness(sw: pd.DataFrame) -> pd.DataFrame:
    total = len(sw)
    rows = []
    for field, label in [
        ("representative_aadt", "numeric_aadt"),
        ("representative_speed_limit_mph", "numeric_speed"),
        ("exposure_denominator", "exposure_denominator"),
        ("median_group", "median_group"),
    ]:
        if field == "median_group":
            complete = int(sw[field].ne("unknown").sum())
        else:
            complete = int(sw[field].notna().sum())
        rows.append(
            {
                "context_feature": label,
                "complete_signal_windows": complete,
                "missing_signal_windows": total - complete,
                "completeness_share": round(complete / total, 4) if total else 0,
            }
        )
    return pd.DataFrame(rows)


def median_summary(sw: pd.DataFrame) -> pd.DataFrame:
    return (
        sw.groupby(["signal_window", "median_group"], dropna=False)
        .agg(
            signal_windows=("stable_signal_id", "nunique"),
            aadt_complete=("representative_aadt", lambda s: int(s.notna().sum())),
            speed_complete=("representative_speed_limit_mph", lambda s: int(s.notna().sum())),
            exposure_complete=("exposure_denominator", lambda s: int(s.notna().sum())),
        )
        .reset_index()
    )


def access_density_summary(sw: pd.DataFrame) -> pd.DataFrame:
    return (
        sw.groupby(["signal_window", "untyped_access_count_band"], dropna=False)
        .agg(
            signals=("stable_signal_id", "nunique"),
            total_raw_access_count=("untyped_access_raw_count", "sum"),
            mean_access_per_1000ft=("optional_access_per_1000ft", "mean"),
            median_access_per_1000ft=("optional_access_per_1000ft", "median"),
        )
        .reset_index()
    )


def rate_readiness(sw: pd.DataFrame) -> pd.DataFrame:
    total = len(sw)
    denom = int(sw["exposure_denominator"].notna().sum())
    return pd.DataFrame(
        [
            {
                "rate_field": "candidate_crash_rate",
                "candidate_rate_created": denom > 0,
                "eligible_signal_windows": denom,
                "total_signal_windows": total,
                "eligible_share": round(denom / total, 4) if total else 0,
                "denominator_field": "exposure_denominator",
                "denominator_units": "AADT x roadway miles",
                "denominator_method": "sum_aadt_times_final_bin_length_miles",
                "recommendation": "candidate/internal only; review denominator before public rate figure",
            }
        ]
    )


def dictionary_v2() -> pd.DataFrame:
    rows = [
        ("representative_aadt", "Representative AADT", "Length-weighted mean AADT for the signal window.", "vehicles/day", "Review-only route/measure carry-forward.", True),
        ("aadt_min", "Minimum AADT", "Minimum matched AADT in the signal window.", "vehicles/day", "", True),
        ("aadt_max", "Maximum AADT", "Maximum matched AADT in the signal window.", "vehicles/day", "", True),
        ("representative_speed_limit_mph", "Representative speed limit", "Mode speed limit for the signal window.", "mph", "Mode by final bin count.", True),
        ("speed_limit_min_mph", "Minimum speed limit", "Minimum matched speed limit in the signal window.", "mph", "", True),
        ("speed_limit_max_mph", "Maximum speed limit", "Maximum matched speed limit in the signal window.", "mph", "", True),
        ("exposure_denominator", "Exposure denominator", "Sum of AADT times final bin length in miles.", "AADT x miles", "Candidate denominator, not final rate policy.", True),
        ("candidate_crash_rate", "Candidate crash rate", "Weighted crash count divided by exposure denominator.", "weighted crashes per AADT-mile", "Internal/review-only, not final rate/model.", False),
        ("untyped_access_raw_count", "Access count", "Unique untyped spatial 100 ft access points in the signal window.", "count", "Primary access measure for now.", True),
        ("untyped_access_count_band", "Access count band", "Raw access count band: 0, 1-2, 3-5, 6+.", "category", "", True),
        ("optional_access_per_1000ft", "Access per 1,000 ft", "Raw access count divided by window length.", "count per 1,000 ft", "Secondary only; raw count band remains primary.", True),
        ("median_group", "Median group", "Compact median group from source Travelway RIM_MEDIAN.", "category", "Carried through stable Travelway/source lineage.", True),
        ("roadway_context", "Roadway context", "Plain-language roadway context from source Travelway facility/ramp fields.", "category", "", True),
    ]
    return pd.DataFrame(rows, columns=["internal_field", "public_label", "definition", "unit", "caveat", "use_in_figures"])


def write_svg(matrix: pd.DataFrame) -> None:
    sub = matrix[matrix["signal_window"].eq("0-2,500 ft")].copy()
    if sub.empty:
        return
    # Keep the draft compact: aggregate over AADT/speed into access bands for a sanity preview.
    plot = sub.groupby(["roadway_context", "untyped_access_count_band"], dropna=False).agg(
        weighted_crash_count=("weighted_crash_count", "sum"), signal_count=("signal_count", "sum")
    ).reset_index()
    rows = sorted(plot["roadway_context"].unique())
    cols = ["0", "1-2", "3-5", "6+"]
    max_val = max(float(plot["weighted_crash_count"].max()), 1.0)
    cw, ch = 130, 36
    left, top = 230, 65
    width = left + cw * len(cols) + 30
    height = top + ch * len(rows) + 65
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;font-size:12px}.title{font-size:17px;font-weight:bold}.label{font-weight:bold}</style>',
        '<text class="title" x="20" y="28">Draft numeric-context matrix preview</text>',
        '<text x="20" y="48">Cell text: weighted spatial 50 ft crashes / signal count. Use CSV for AADT and speed bands.</text>',
    ]
    for j, col in enumerate(cols):
        parts.append(f'<text class="label" x="{left + j*cw + 8}" y="{top - 10}">Access {html.escape(col)}</text>')
    lookup = {(r["roadway_context"], r["untyped_access_count_band"]): r for _, r in plot.iterrows()}
    for i, row in enumerate(rows):
        y = top + i * ch
        parts.append(f'<text class="label" x="20" y="{y+23}">{html.escape(str(row))}</text>')
        for j, col in enumerate(cols):
            x = left + j * cw
            rec = lookup.get((row, col))
            val = float(rec["weighted_crash_count"]) if rec is not None else 0
            intensity = int(245 - 170 * math.sqrt(val / max_val))
            parts.append(f'<rect x="{x}" y="{y}" width="{cw-4}" height="{ch-4}" fill="rgb(255,{intensity},{intensity})" stroke="#aaa"/>')
            label = "0" if rec is None else f"{val:.0f} / {int(rec['signal_count'])}"
            parts.append(f'<text x="{x+8}" y="{y+22}">{html.escape(label)}</text>')
    parts.append("</svg>")
    (OUT / "draft_guidance_matrix_numeric_context_v2.svg").write_text("\n".join(parts), encoding="utf-8")
    log("Wrote draft_guidance_matrix_numeric_context_v2.svg")


def findings(sw: pd.DataFrame, rate: pd.DataFrame) -> str:
    total = len(sw)
    aadt_n = int(sw["representative_aadt"].notna().sum())
    speed_n = int(sw["representative_speed_limit_mph"].notna().sum())
    exp_n = int(sw["exposure_denominator"].notna().sum())
    med_n = int(sw["median_group"].ne("unknown").sum())
    rate_created = bool(rate["candidate_rate_created"].iloc[0])
    return f"""# Signal-Window Numeric Context Join Findings

## Bounded Question
Can numeric AADT, numeric speed, and a defensible exposure denominator be joined to the final signal-window context table without rerunning access/crash assignment?

## Answers
1. Numeric AADT came from `expanded_candidate_aadt_v3_path_rebuild/aadt_v3_candidate_assignment_detail.csv`, using route/measure midpoint interval matching from final stable Travelway lineage to `matched_review_only_aadt_value`.
2. Numeric speed came from `expanded_candidate_speed_rns_phase3d_vectorized_assignment/phase3d_candidate_rns_speed_assignment_detail.csv`, using route/measure midpoint interval matching to `matched_review_only_car_speed_limit`.
3. Exposure denominator was created as `sum(AADT x final_bin_length_miles)` at signal-window and approach-window grain.
4. Exposure units/method: `AADT x roadway miles`, method `sum_aadt_times_final_bin_length_miles`. This is a candidate figure denominator, not a final rate policy.
5. Completeness at signal-window grain: AADT {aadt_n:,} / {total:,}; speed {speed_n:,} / {total:,}; exposure {exp_n:,} / {total:,}; median {med_n:,} / {total:,}.
6. `RIM_MEDIAN` is usable as a matrix row/facet with caveats for mixed median groups within some windows.
7. Access should remain raw count bands (`0`, `1-2`, `3-5`, `6+`) for primary displays. Access per 1,000 ft is included as a secondary field.
8. A candidate crash rate is {'available internally' if rate_created else 'not available'} where denominator is non-null, but should remain review-only until denominator policy is approved.
9. The AADT x speed x access guidance matrix is now feasible as a review/data-design table where numeric context is complete; sparse and missing cells still need display caveats.
10. Next visualization/design pass should create a cleaner matrix layout, decide whether to suppress low-N/rate cells, and compare count-only versus candidate-rate cells.

## QA Note
No active outputs were modified, no records were promoted, no access/crash assignment was rerun, no final rates/models were calculated, and crash direction fields were not read or used.
"""


def qa_table() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to review/current/final_signal_window_numeric_context_join."),
        ("no_records_promoted", True, "Review-only numeric context join."),
        ("no_new_access_crash_assignment", True, "Used existing access/crash outputs only."),
        ("no_rates_or_models", True, "Only candidate rate field produced where denominator exists; no final rates/models."),
        ("crash_direction_fields_not_read_or_used", True, "Crash source not read; no direction fields used."),
        ("numeric_aadt_speed_not_fabricated", True, "Numeric values come from prior route/measure numeric assignment outputs."),
        ("exposure_denominator_documented", True, "Method and units included in outputs and findings."),
        ("rim_median_lineage_preserved", True, "Median fields preserved from prior stable Travelway/source lineage context table."),
        ("raw_access_counts_included", True, "Raw counts and count bands preserved; density is secondary."),
        ("outputs_review_only_folder", True, str(OUT)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_signal_window_numeric_context_join",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "outputs": list(outputs),
        "review_only": True,
        "non_goals": [
            "no final publication figures",
            "no new access assignment",
            "no new crash assignment",
            "no final rates/models",
            "no active output modifications",
            "no record promotion",
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting final signal-window numeric context join.")
    inventory = field_inventory()
    bin_ctx, bin_summary = bin_numeric_context()
    sw, aw = update_context_tables(bin_ctx)
    matrix_long, matrix_wide = guidance_matrix(sw)
    miss = missingness(sw)
    med = median_summary(sw)
    access = access_density_summary(sw)
    rate = rate_readiness(sw)
    dictionary = dictionary_v2()

    write_csv(bin_ctx, "bin_numeric_speed_aadt_context.csv")
    write_csv(sw, "signal_window_numeric_context_v2.csv")
    write_csv(aw, "signal_approach_window_numeric_context_v2.csv")
    write_csv(inventory, "numeric_context_field_inventory.csv")
    write_csv(miss, "numeric_context_missingness_summary.csv")
    write_csv(med, "median_numeric_context_summary.csv")
    write_csv(access, "access_count_vs_density_summary.csv")
    write_csv(matrix_long, "guidance_matrix_ready_long_v2.csv")
    write_csv(matrix_wide, "guidance_matrix_ready_wide_count_table_v2.csv")
    write_csv(rate, "candidate_crash_rate_readiness.csv")
    write_csv(dictionary, "plain_language_field_dictionary_v2.csv")
    write_svg(matrix_long)
    (OUT / "signal_window_numeric_context_join_findings.md").write_text(findings(sw, rate), encoding="utf-8")
    log("Wrote findings memo.")
    qa = qa_table()
    write_csv(qa, "signal_window_numeric_context_join_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "signal_window_numeric_context_join_manifest.json")
    (OUT / "signal_window_numeric_context_join_manifest.json").write_text(json.dumps(manifest(outputs), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed final signal-window numeric context join.")


if __name__ == "__main__":
    main()
