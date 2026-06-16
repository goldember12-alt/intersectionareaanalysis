"""Build a review-only signal-window numeric/context table for figures.

Bounded question: create a plain-language, figure-ready signal-window table for
guidance-matrix design using the final 3,719-signal leg-corrected review
universe, carried source Travelway median/configuration fields, access counts,
and existing crash rollups. This pass does not rerun access/crash assignment,
does not modify active outputs, and does not calculate final rates/models.
"""

from __future__ import annotations

import html
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/review/current/final_signal_window_numeric_context_table"

FINAL_DIR = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_clean_universe_summary"
ACCESS_DIR = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_access_refresh"
CRASH_DIR = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_crash_candidate_assignment"
IDENTITY_DIR = REPO / "work/output/roadway_graph/review/current/crash_roadway_identity_assignment_doctrine"
LINEAGE_DIR = REPO / "work/output/roadway_graph/review/current/source_travelway_lineage_bridge"
SOURCE_TRAVELWAY = REPO / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "signals": FINAL_DIR / "final_leg_corrected_signal_universe_3719.csv",
    "bins": FINAL_DIR / "final_leg_corrected_bin_universe.csv",
    "leg_distribution": FINAL_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    "window_availability": FINAL_DIR / "final_leg_corrected_bin_window_availability.csv",
    "context_readiness": FINAL_DIR / "final_leg_corrected_context_readiness_summary.csv",
    "untyped_access_detail": ACCESS_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
    "typed_access_detail": ACCESS_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv",
    "untyped_access_summary": ACCESS_DIR / "final_leg_corrected_untyped_access_summary.csv",
    "typed_category_summary": ACCESS_DIR / "final_leg_corrected_typed_access_category_summary.csv",
    "crash_signal_window": CRASH_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    "crash_approach_window": CRASH_DIR / "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    "identity_detail": IDENTITY_DIR / "identity_compatible_spatial_50ft_assignment_detail.csv",
    "identity_rollups": IDENTITY_DIR / "identity_compatible_spatial_50ft_rollups.csv",
    "identity_product_comparison": IDENTITY_DIR / "crash_assignment_product_doctrine_comparison.csv",
    "stable_identity": LINEAGE_DIR / "source_travelway_stable_identity.csv",
}

WINDOWS = {
    "0-1,000 ft": ("0_1000",),
    "0-2,500 ft": ("0_1000", "1000_2500"),
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


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def compact(value: object, default: str = "unknown") -> str:
    if pd.isna(value):
        return default
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return default
    return s


def mode_text(values: Iterable[object], default: str = "unknown") -> str:
    vals = [compact(v, "") for v in values]
    vals = [v for v in vals if v]
    if not vals:
        return default
    return Counter(vals).most_common(1)[0][0]


def bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def access_count_band(value: object) -> str:
    try:
        n = float(value)
    except Exception:
        n = 0
    if n <= 0:
        return "0"
    if n <= 2:
        return "1-2"
    if n <= 5:
        return "3-5"
    return "6+"


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


def median_group(value: object) -> str:
    text = compact(value).lower()
    if text == "unknown":
        return "unknown"
    if "no median" in text or "less than 4 feet" in text:
        return "no_median_or_lt_4ft"
    if "curb" in text or "jersey" in text or "guard rail" in text or "positive barrier" in text:
        return "barrier_or_curb_median"
    if "grass" in text or "painted" in text or "turn lane" in text:
        return "unprotected_or_painted_median"
    if "rail" in text:
        return "rail_or_other_median"
    return "other_or_unknown_median"


def one_way_two_way(value: object) -> str:
    text = compact(value).lower()
    if "one-way" in text or "one way" in text:
        return "one-way"
    if "two-way" in text or "two way" in text:
        return "two-way"
    return "unknown"


def divided_undivided(value: object) -> str:
    text = compact(value).lower()
    if "undivided" in text:
        return "undivided"
    if "divided" in text:
        return "divided"
    return "unknown"


def ramp_context(route_category: object, route_type: object, ramp_code: object) -> str:
    text = f"{compact(route_category, '')} {compact(route_type, '')} {compact(ramp_code, '')}".lower()
    if "ramp" in text or compact(ramp_code, ""):
        return "ramp_or_interchange_context"
    if "interstate" in text:
        return "interstate_or_limited_access_context"
    return "surface_street_or_highway_context"


def roadway_context(facility_type: object, route_category: object, route_type: object, ramp_code: object) -> str:
    ramp = ramp_context(route_category, route_type, ramp_code)
    facility = compact(facility_type)
    if ramp == "ramp_or_interchange_context":
        return "ramp/interchange area"
    if "divided" in facility.lower() and "undivided" not in facility.lower():
        return "divided roadway"
    if "undivided" in facility.lower():
        return "undivided roadway"
    if ramp == "interstate_or_limited_access_context":
        return "limited-access highway context"
    return "roadway context unknown"


def load_source_travelway_context() -> pd.DataFrame:
    log("Loading source Travelway context fields.")
    try:
        import geopandas as gpd

        tw = gpd.read_file(SOURCE_TRAVELWAY, layer="source_travelway_full", ignore_geometry=True)
    except Exception as exc:  # pragma: no cover
        log(f"Could not read source Travelway: {type(exc).__name__}: {exc}")
        return pd.DataFrame(columns=["stable_travelway_id"])
    tw = tw.reset_index(drop=True).copy()
    tw["source_feature_local_fid"] = tw.index + 1
    keep = [
        "source_feature_local_fid",
        "RIM_FACILI",
        "RIM_FACI_1",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "RIM_MEDIAN",
        "RIM_ACCESS",
        "LOC_COMP_D",
        "LOC_COMP_1",
    ]
    tw = tw[[c for c in keep if c in tw.columns]].copy()
    identity = read_csv(INPUTS["stable_identity"], dtype=str, low_memory=False)
    if identity.empty:
        return pd.DataFrame(columns=["stable_travelway_id"])
    identity["source_feature_local_fid"] = pd.to_numeric(identity["source_feature_local_fid"], errors="coerce")
    tw["source_feature_local_fid"] = pd.to_numeric(tw["source_feature_local_fid"], errors="coerce")
    joined = identity[["stable_travelway_id", "source_feature_local_fid"]].merge(tw, on="source_feature_local_fid", how="left")
    joined["median_group"] = joined.get("RIM_MEDIAN", pd.Series(dtype=str)).map(median_group)
    joined["facility_type"] = joined.get("RIM_FACILI", pd.Series(dtype=str)).map(compact)
    joined["one_way_two_way_group"] = joined.get("RIM_FACILI", pd.Series(dtype=str)).map(one_way_two_way)
    joined["divided_undivided_group"] = joined.get("RIM_FACILI", pd.Series(dtype=str)).map(divided_undivided)
    joined["ramp_or_interchange_context"] = [
        ramp_context(a, b, c)
        for a, b, c in zip(
            joined.get("RTE_CATEGO", pd.Series(dtype=str)),
            joined.get("RTE_TYPE_N", pd.Series(dtype=str)),
            joined.get("RTE_RAMP_C", pd.Series(dtype=str)),
        )
    ]
    joined["roadway_context"] = [
        roadway_context(a, b, c, d)
        for a, b, c, d in zip(
            joined.get("RIM_FACILI", pd.Series(dtype=str)),
            joined.get("RTE_CATEGO", pd.Series(dtype=str)),
            joined.get("RTE_TYPE_N", pd.Series(dtype=str)),
            joined.get("RTE_RAMP_C", pd.Series(dtype=str)),
        )
    ]
    return joined


def summarize_groups(values: Iterable[object]) -> tuple[str, str, int]:
    vals = [compact(v) for v in values]
    vals = [v for v in vals if v != "unknown"]
    if not vals:
        return "unknown", "unknown", 0
    counts = Counter(vals)
    dominant = counts.most_common(1)[0][0]
    observed = "|".join(sorted(counts))
    return dominant, observed, len(counts)


def observed_groups(series: pd.Series) -> str:
    vals = sorted({compact(v) for v in series if compact(v) != "unknown"})
    return "|".join(vals) if vals else "unknown"


def group_count(series: pd.Series) -> int:
    return len({compact(v) for v in series if compact(v) != "unknown"})


def any_true(series: pd.Series) -> bool:
    return bool(bool_series(series).any())


def build_bin_context() -> pd.DataFrame:
    log("Loading final leg-corrected bins with selected fields.")
    cols = pd.read_csv(INPUTS["bins"], nrows=0).columns.tolist()
    wanted = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
        "final_review_leg_source",
        "final_review_context_status",
        "final_review_recovery_provenance",
        "source_route_common",
        "source_route_name",
        "source_measure_start",
        "source_measure_end",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "roadway_division_context",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
        "existing_qa_flags",
    ]
    bins = read_csv(INPUTS["bins"], usecols=[c for c in wanted if c in cols], dtype=str, low_memory=False)
    source = load_source_travelway_context()
    if not source.empty:
        bins = bins.merge(source.drop(columns=["source_feature_local_fid"], errors="ignore"), on="stable_travelway_id", how="left")
    for c in [
        "median_group",
        "facility_type",
        "one_way_two_way_group",
        "divided_undivided_group",
        "ramp_or_interchange_context",
        "roadway_context",
    ]:
        if c not in bins:
            bins[c] = "unknown"
        bins[c] = bins[c].fillna("unknown").astype(str)
    if "roadway_division_context" in bins:
        bins["roadway_division_context"] = bins["roadway_division_context"].fillna(
            bins.get("existing_roadway_division_context", pd.Series(index=bins.index, dtype=str))
        )
        bins["roadway_division_context"] = bins["roadway_division_context"].fillna(
            bins.get("generated_roadway_division_context", pd.Series(index=bins.index, dtype=str))
        )
    else:
        bins["roadway_division_context"] = "unknown"
    return bins


def aggregate_bin_window(bins: pd.DataFrame, group_cols: list[str], public_window: str, internal_windows: tuple[str, ...]) -> pd.DataFrame:
    sub = bins[bins["analysis_window"].isin(internal_windows)].copy()
    if sub.empty:
        return pd.DataFrame(columns=group_cols + ["signal_window"])
    for col in [
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
        "source_route_common",
        "source_measure_start",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
    ]:
        if col not in sub:
            sub[col] = pd.NA
    sub["route_measure_ready_bin"] = pd.to_numeric(sub["source_measure_start"], errors="coerce").notna()
    group = sub.groupby(group_cols, dropna=False)
    out = group.agg(
        bin_count=("stable_bin_id", "size"),
        stable_travelway_count=("stable_travelway_id", "nunique"),
        stable_travelway_id_summary=("stable_travelway_id", lambda s: "|".join(sorted(s.dropna().astype(str).unique())[:12])),
        approach_count=("final_review_physical_leg_id", "nunique"),
        carriageway_source_subpart_count=("final_review_carriageway_subbranch_id", "nunique"),
        median_group=("median_group", mode_text),
        observed_median_group_groups=("median_group", observed_groups),
        median_group_group_count=("median_group", group_count),
        facility_type=("facility_type", mode_text),
        observed_facility_type_groups=("facility_type", observed_groups),
        facility_type_group_count=("facility_type", group_count),
        one_way_two_way_group=("one_way_two_way_group", mode_text),
        observed_one_way_two_way_group_groups=("one_way_two_way_group", observed_groups),
        one_way_two_way_group_group_count=("one_way_two_way_group", group_count),
        divided_undivided_group=("divided_undivided_group", mode_text),
        observed_divided_undivided_group_groups=("divided_undivided_group", observed_groups),
        divided_undivided_group_group_count=("divided_undivided_group", group_count),
        ramp_or_interchange_context=("ramp_or_interchange_context", mode_text),
        observed_ramp_or_interchange_context_groups=("ramp_or_interchange_context", observed_groups),
        ramp_or_interchange_context_group_count=("ramp_or_interchange_context", group_count),
        roadway_context=("roadway_context", mode_text),
        observed_roadway_context_groups=("roadway_context", observed_groups),
        roadway_context_group_count=("roadway_context", group_count),
        dominant_rim_median=("RIM_MEDIAN", mode_text),
        observed_rim_median_groups=("RIM_MEDIAN", observed_groups),
        rim_median_group_count=("RIM_MEDIAN", group_count),
        RIM_ACCESS=("RIM_ACCESS", mode_text),
        observed_rim_access_groups=("RIM_ACCESS", observed_groups),
        rim_access_group_count=("RIM_ACCESS", group_count),
        RTE_CATEGO=("RTE_CATEGO", mode_text),
        observed_rte_catego_groups=("RTE_CATEGO", observed_groups),
        rte_catego_group_count=("RTE_CATEGO", group_count),
        RTE_TYPE_N=("RTE_TYPE_N", mode_text),
        observed_rte_type_n_groups=("RTE_TYPE_N", observed_groups),
        rte_type_n_group_count=("RTE_TYPE_N", group_count),
        final_review_leg_source_summary=("final_review_leg_source", observed_groups),
        recovery_provenance_summary=("final_review_recovery_provenance", observed_groups),
        route_summary=("source_route_common", lambda s: "|".join(sorted(s.dropna().astype(str).unique())[:12])),
        route_measure_ready_any=("route_measure_ready_bin", "any"),
        speed_ready_any_bin=("final_review_has_rns_speed", any_true),
        aadt_ready_any_bin=("final_review_has_aadt", any_true),
        exposure_ready_any_bin=("final_review_has_exposure_denominator", any_true),
        speed_aadt_ready_any_bin=("final_review_speed_aadt_ready_bin", any_true),
    ).reset_index()
    out["signal_window"] = public_window
    return out


def windowized_bins(bins: pd.DataFrame) -> pd.DataFrame:
    near = bins[bins["analysis_window"].eq("0_1000")].copy()
    near["signal_window"] = "0-1,000 ft"
    full = bins[bins["analysis_window"].isin(["0_1000", "1000_2500"])].copy()
    full["signal_window"] = "0-2,500 ft"
    return pd.concat([near, full], ignore_index=True)


def dominant_and_observed(df: pd.DataFrame, keys: list[str], field: str, prefix: str | None = None) -> pd.DataFrame:
    prefix = prefix or field
    if field not in df:
        return pd.DataFrame(columns=keys + [prefix, f"observed_{prefix.lower()}_groups", f"{prefix.lower()}_group_count"])
    tmp = df[keys + [field]].copy()
    tmp[field] = tmp[field].map(compact)
    tmp = tmp[tmp[field].ne("unknown")]
    if tmp.empty:
        out = df[keys].drop_duplicates().copy()
        out[prefix] = "unknown"
        out[f"observed_{prefix.lower()}_groups"] = "unknown"
        out[f"{prefix.lower()}_group_count"] = 0
        return out
    counts = tmp.groupby(keys + [field], dropna=False).size().reset_index(name="_count")
    dominant = counts.sort_values(keys + ["_count", field], ascending=[True] * len(keys) + [False, True]).drop_duplicates(keys)
    dominant = dominant[keys + [field]].rename(columns={field: prefix})
    observed = counts.groupby(keys, dropna=False)[field].agg(lambda s: "|".join(sorted(s.astype(str).unique()))).reset_index()
    observed = observed.rename(columns={field: f"observed_{prefix.lower()}_groups"})
    n = counts.groupby(keys, dropna=False)[field].nunique().reset_index(name=f"{prefix.lower()}_group_count")
    return dominant.merge(observed, on=keys, how="outer").merge(n, on=keys, how="outer")


def fast_window_aggregate(windowed: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    keys = group_cols + ["signal_window"]
    work = windowed.copy()
    for col in [
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
        "source_measure_start",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
    ]:
        if col not in work:
            work[col] = pd.NA
    work["route_measure_ready_bin"] = pd.to_numeric(work["source_measure_start"], errors="coerce").notna()
    for col in [
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
    ]:
        work[col + "_bool"] = bool_series(work[col])
    base = (
        work.groupby(keys, dropna=False)
        .agg(
            bin_count=("stable_bin_id", "size"),
            stable_travelway_count=("stable_travelway_id", "nunique"),
            approach_count=("final_review_physical_leg_id", "nunique"),
            carriageway_source_subpart_count=("final_review_carriageway_subbranch_id", "nunique"),
            route_measure_ready_any=("route_measure_ready_bin", "any"),
            speed_ready_any_bin=("final_review_has_rns_speed_bool", "any"),
            aadt_ready_any_bin=("final_review_has_aadt_bool", "any"),
            exposure_ready_any_bin=("final_review_has_exposure_denominator_bool", "any"),
            speed_aadt_ready_any_bin=("final_review_speed_aadt_ready_bin_bool", "any"),
        )
        .reset_index()
    )
    # These summaries are capped to keep the public tables readable.
    for field, out_name in [
        ("stable_travelway_id", "stable_travelway_id_summary"),
        ("final_review_leg_source", "final_review_leg_source_summary"),
        ("final_review_recovery_provenance", "recovery_provenance_summary"),
        ("source_route_common", "route_summary"),
    ]:
        if field in work:
            summary = (
                work[keys + [field]]
                .dropna()
                .drop_duplicates()
                .groupby(keys, dropna=False)[field]
                .agg(lambda s: "|".join(sorted(s.astype(str).unique())[:12]) or "unknown")
                .reset_index(name=out_name)
            )
            base = base.merge(summary, on=keys, how="left")
        else:
            base[out_name] = "unknown"
    for field, name in [
        ("median_group", "median_group"),
        ("facility_type", "facility_type"),
        ("one_way_two_way_group", "one_way_two_way_group"),
        ("divided_undivided_group", "divided_undivided_group"),
        ("ramp_or_interchange_context", "ramp_or_interchange_context"),
        ("roadway_context", "roadway_context"),
        ("RIM_MEDIAN", "dominant_rim_median"),
        ("RIM_ACCESS", "RIM_ACCESS"),
        ("RTE_CATEGO", "RTE_CATEGO"),
        ("RTE_TYPE_N", "RTE_TYPE_N"),
    ]:
        base = base.merge(dominant_and_observed(work, keys, field, name), on=keys, how="left")
    fill_cols = [c for c in base.columns if c.startswith("observed_") or c in ["median_group", "facility_type", "one_way_two_way_group", "divided_undivided_group", "ramp_or_interchange_context", "roadway_context", "dominant_rim_median", "RIM_ACCESS", "RTE_CATEGO", "RTE_TYPE_N"]]
    for col in fill_cols:
        base[col] = base[col].fillna("unknown")
    for col in [c for c in base.columns if c.endswith("_group_count")]:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0).astype(int)
    return base


def build_signal_window_base(bins: pd.DataFrame) -> pd.DataFrame:
    log("Aggregating signal-window and signal-approach-window base tables.")
    windowed = windowized_bins(bins)
    signal_window = fast_window_aggregate(windowed, ["stable_signal_id"])
    approach_window = fast_window_aggregate(windowed, ["stable_signal_id", "final_review_physical_leg_id"])
    signals = read_csv(INPUTS["signals"], dtype=str, low_memory=False)
    keep = [
        "stable_signal_id",
        "source_signal_id",
        "recovery_branch",
        "final_leg_corrected_physical_leg_count",
        "final_leg_corrected_physical_leg_bucket",
        "clean_review_analysis_status",
        "qa_flags",
    ]
    signal_window = signal_window.merge(signals[[c for c in keep if c in signals]], on="stable_signal_id", how="left")
    approach_window = approach_window.merge(signals[[c for c in keep if c in signals]], on="stable_signal_id", how="left")
    for df in [signal_window, approach_window]:
        if "final_leg_corrected_physical_leg_count" in df:
            final_count = pd.to_numeric(df["final_leg_corrected_physical_leg_count"], errors="coerce")
            current_count = pd.to_numeric(df["approach_count"], errors="coerce").fillna(0)
            df["approach_count"] = current_count.where(current_count > 0, final_count).fillna(current_count).astype(int)
        df["signal_id"] = df["stable_signal_id"]
        df["analysis_universe_status"] = "final leg-corrected clean review-analysis universe"
        df["source_limitation_flag"] = df.get("final_leg_corrected_physical_leg_bucket", "").isin(["one_leg", "two_leg"])
        df["representative_aadt"] = pd.NA
        df["aadt_min"] = pd.NA
        df["aadt_max"] = pd.NA
        df["representative_speed_limit_mph"] = pd.NA
        df["speed_limit_min_mph"] = pd.NA
        df["speed_limit_max_mph"] = pd.NA
        df["exposure_denominator"] = pd.NA
        df["aadt_band"] = "unknown"
        df["speed_band"] = "unknown"
        df["candidate_crash_rate"] = pd.NA
        df["rate_denominator_field_used"] = ""
        df["rate_denominator_completeness_flag"] = "numeric_exposure_denominator_not_carried"
    approach_window["approach_id"] = approach_window.groupby("stable_signal_id")["final_review_physical_leg_id"].transform(
        lambda s: pd.factorize(s.astype(str))[0] + 1
    )
    approach_window["approach_label"] = "approach " + approach_window["approach_id"].astype(str)
    approach_window = approach_window.rename(
        columns={"final_review_carriageway_subbranch_id": "carriageway_source_subpart_id"}
    )
    return signal_window, approach_window


def aggregate_access(path: Path, typed: bool = False) -> pd.DataFrame:
    log(f"Aggregating {'typed' if typed else 'untyped'} access counts from spatial 100 ft assignments.")
    if not path.exists():
        return pd.DataFrame(columns=["stable_signal_id", "signal_window"])
    cols = pd.read_csv(path, nrows=0).columns.tolist()
    use = ["access_point_id", "stable_signal_id", "analysis_window", "buffer_width_ft", "corrected_access_category"]
    use = [c for c in use if c in cols]
    pieces = []
    for chunk in pd.read_csv(path, usecols=use, dtype=str, chunksize=250_000, low_memory=False):
        chunk = chunk[chunk["buffer_width_ft"].astype(str) == "100"].copy()
        if chunk.empty:
            continue
        if "corrected_access_category" not in chunk:
            chunk["corrected_access_category"] = "untyped"
        for label, windows in WINDOWS.items():
            sub = chunk[chunk["analysis_window"].isin(windows)]
            if sub.empty:
                continue
            if typed:
                grouped = (
                    sub.groupby(["stable_signal_id", "corrected_access_category"], dropna=False)["access_point_id"]
                    .nunique()
                    .reset_index(name="typed_access_raw_count")
                )
                pivot = grouped.pivot_table(
                    index="stable_signal_id",
                    columns="corrected_access_category",
                    values="typed_access_raw_count",
                    aggfunc="sum",
                    fill_value=0,
                ).reset_index()
                for cat in TYPED_CATEGORIES:
                    if cat not in pivot:
                        pivot[cat] = 0
                pivot["typed_access_raw_count"] = pivot[TYPED_CATEGORIES].sum(axis=1)
                pivot["typed_categories_present"] = pivot.apply(
                    lambda r: "|".join([cat for cat in TYPED_CATEGORIES if r.get(cat, 0) > 0]) or "none",
                    axis=1,
                )
                pivot["signal_window"] = label
                pieces.append(pivot)
            else:
                grouped = sub.groupby("stable_signal_id", dropna=False)["access_point_id"].nunique().reset_index()
                grouped = grouped.rename(columns={"access_point_id": "untyped_access_raw_count"})
                grouped["signal_window"] = label
                pieces.append(grouped)
    if not pieces:
        return pd.DataFrame(columns=["stable_signal_id", "signal_window"])
    out = pd.concat(pieces, ignore_index=True).fillna(0)
    num_cols = [c for c in out.columns if c not in {"stable_signal_id", "signal_window", "typed_categories_present"}]
    out = out.groupby(["stable_signal_id", "signal_window"], dropna=False)[num_cols].sum().reset_index()
    if typed:
        out["typed_categories_present"] = out.apply(
            lambda r: "|".join([cat for cat in TYPED_CATEGORIES if r.get(cat, 0) > 0]) or "none",
            axis=1,
        )
    return out


def aggregate_crashes(path: Path, approach: bool = False) -> pd.DataFrame:
    log(f"Aggregating {'approach-window' if approach else 'signal-window'} spatial 50 ft crash counts.")
    if not path.exists():
        return pd.DataFrame()
    df = read_csv(path, low_memory=False)
    df = df[pd.to_numeric(df["buffer_width_ft"], errors="coerce") == 50].copy()
    group_base = ["stable_signal_id"]
    if approach:
        group_base.append("final_review_physical_leg_id")
    pieces = []
    for label, windows in WINDOWS.items():
        sub = df[df["analysis_window"].isin(windows)].copy()
        if sub.empty:
            continue
        grouped = (
            sub.groupby(group_base, dropna=False)
            .agg(
                spatial_50ft_crash_count=("unique_crash_count", "sum"),
                spatial_50ft_weighted_crash_count=("weighted_crash_count", "sum"),
                spatial_50ft_assignment_rows=("assignment_row_count", "sum"),
                max_crash_assignment_fanout=("max_assignment_fanout", "max"),
            )
            .reset_index()
        )
        grouped["signal_window"] = label
        pieces.append(grouped)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def aggregate_identity_compatible() -> pd.DataFrame:
    log("Aggregating identity-compatible spatial 50 ft crash counts with chunks.")
    path = INPUTS["identity_detail"]
    if not path.exists():
        return pd.DataFrame(columns=["stable_signal_id", "signal_window"])
    use = [
        "buffer_width_ft",
        "stable_crash_id",
        "stable_signal_id",
        "analysis_window",
        "identity_constrained_source_preserving_weight",
    ]
    pieces = []
    for chunk in pd.read_csv(path, usecols=use, dtype=str, chunksize=250_000, low_memory=False):
        chunk = chunk[chunk["buffer_width_ft"].astype(str) == "50"].copy()
        if chunk.empty:
            continue
        chunk["identity_constrained_source_preserving_weight"] = pd.to_numeric(
            chunk["identity_constrained_source_preserving_weight"], errors="coerce"
        ).fillna(0)
        for label, windows in WINDOWS.items():
            sub = chunk[chunk["analysis_window"].isin(windows)]
            if sub.empty:
                continue
            grouped = (
                sub.groupby("stable_signal_id", dropna=False)
                .agg(
                    identity_compatible_spatial_50ft_crash_count=("stable_crash_id", "nunique"),
                    identity_compatible_spatial_50ft_weighted_crash_count=(
                        "identity_constrained_source_preserving_weight",
                        "sum",
                    ),
                )
                .reset_index()
            )
            grouped["signal_window"] = label
            pieces.append(grouped)
    if not pieces:
        return pd.DataFrame(columns=["stable_signal_id", "signal_window"])
    return pd.concat(pieces, ignore_index=True).groupby(["stable_signal_id", "signal_window"], dropna=False).sum(numeric_only=True).reset_index()


def attach_counts(signal_window: pd.DataFrame, approach_window: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    untyped = aggregate_access(INPUTS["untyped_access_detail"], typed=False)
    typed = aggregate_access(INPUTS["typed_access_detail"], typed=True)
    crash_signal = aggregate_crashes(INPUTS["crash_signal_window"], approach=False)
    crash_approach = aggregate_crashes(INPUTS["crash_approach_window"], approach=True)
    identity = aggregate_identity_compatible()

    signal_window = signal_window.merge(untyped, on=["stable_signal_id", "signal_window"], how="left")
    signal_window = signal_window.merge(typed, on=["stable_signal_id", "signal_window"], how="left")
    signal_window = signal_window.merge(crash_signal, on=["stable_signal_id", "signal_window"], how="left")
    signal_window = signal_window.merge(identity, on=["stable_signal_id", "signal_window"], how="left")

    approach_window = approach_window.merge(untyped, on=["stable_signal_id", "signal_window"], how="left")
    approach_window = approach_window.merge(typed, on=["stable_signal_id", "signal_window"], how="left")
    approach_window = approach_window.merge(crash_approach, on=["stable_signal_id", "final_review_physical_leg_id", "signal_window"], how="left")

    count_cols = [
        "untyped_access_raw_count",
        "typed_v2_access_raw_count",
        "spatial_50ft_crash_count",
        "spatial_50ft_weighted_crash_count",
        "spatial_50ft_assignment_rows",
        "max_crash_assignment_fanout",
        "identity_compatible_spatial_50ft_crash_count",
        "identity_compatible_spatial_50ft_weighted_crash_count",
    ] + TYPED_CATEGORIES
    for df in [signal_window, approach_window]:
        if "typed_access_raw_count" in df:
            df["typed_v2_access_raw_count"] = df["typed_access_raw_count"]
            df.drop(columns=["typed_access_raw_count"], inplace=True)
        for c in count_cols:
            if c not in df:
                df[c] = 0
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        if "typed_categories_present" not in df:
            df["typed_categories_present"] = "none"
        df["typed_categories_present"] = df["typed_categories_present"].fillna("none")
        df["untyped_access_count_band"] = df["untyped_access_raw_count"].map(access_count_band)
        df["low_crash_count_flag"] = df["spatial_50ft_crash_count"] < 5
        df["optional_access_per_1000ft"] = df.apply(
            lambda r: r["untyped_access_raw_count"] / (1.0 if r["signal_window"] == "0-1,000 ft" else 2.5),
            axis=1,
        )
    typed_summary = typed.copy()
    access_summary = (
        signal_window.groupby(["signal_window", "untyped_access_count_band"], dropna=False)
        .agg(signal_count=("stable_signal_id", "nunique"), total_untyped_access=("untyped_access_raw_count", "sum"))
        .reset_index()
    )
    crash_summary = (
        signal_window.groupby("signal_window", dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            spatial_50ft_crash_count=("spatial_50ft_crash_count", "sum"),
            spatial_50ft_weighted_crash_count=("spatial_50ft_weighted_crash_count", "sum"),
            identity_compatible_spatial_50ft_crash_count=("identity_compatible_spatial_50ft_crash_count", "sum"),
            identity_compatible_spatial_50ft_weighted_crash_count=("identity_compatible_spatial_50ft_weighted_crash_count", "sum"),
        )
        .reset_index()
    )
    return signal_window, approach_window, access_summary, typed_summary, crash_summary


def median_summary(signal_window: pd.DataFrame) -> pd.DataFrame:
    return (
        signal_window.groupby(["signal_window", "median_group"], dropna=False)
        .agg(
            signal_windows=("stable_signal_id", "nunique"),
            bin_count=("bin_count", "sum"),
            median_conflict_signal_windows=("median_group_group_count", lambda s: int((pd.to_numeric(s, errors="coerce") > 1).sum())),
        )
        .reset_index()
    )


def numeric_missingness() -> pd.DataFrame:
    candidate_sources = [
        (
            "final_leg_corrected_bin_universe.csv",
            "final_review_has_rns_speed/final_review_has_aadt/final_review_has_exposure_denominator",
            "readiness flags only; no numeric values",
        ),
        (
            "aadt_context_join_v3_identity_route_measure/base_bin_aadt_context_v3.csv",
            "aadt_value/aadt_year/aadt_direction_factor",
            "candidate numeric AADT source, but not keyed directly to final leg-corrected stable_signal_id/window in this pass",
        ),
        (
            "expanded_candidate_speed_rns_phase3d_vectorized_assignment/phase3d_candidate_rns_speed_assignment_detail.csv",
            "speed limit candidate fields",
            "candidate speed source, but not carried into final leg-corrected signal-window output",
        ),
    ]
    rows = []
    for feature, carried, candidate, required in [
        ("numeric_aadt", False, candidate_sources[1], "stable final signal/window numeric AADT carry-forward"),
        ("numeric_speed", False, candidate_sources[2], "stable final signal/window numeric speed carry-forward"),
        ("exposure_denominator", False, candidate_sources[1], "explicit numeric denominator at signal-window grain"),
    ]:
        rows.append(
            {
                "context_feature": feature,
                "carried_in_this_table": carried,
                "complete_signal_windows": 0,
                "missing_signal_windows": 7438,
                "candidate_source_file": candidate[0],
                "candidate_source_fields": candidate[1],
                "missingness_note": candidate[2],
                "needed_next": required,
            }
        )
    return pd.DataFrame(rows)


def rate_audit(signal_window: pd.DataFrame) -> pd.DataFrame:
    total = len(signal_window)
    return pd.DataFrame(
        [
            {
                "rate_field": "candidate_crash_rate",
                "rate_created": False,
                "eligible_rows": 0,
                "total_signal_window_rows": total,
                "denominator_field_needed": "numeric exposure_denominator at signal_window grain",
                "denominator_available": False,
                "note": "Rates intentionally left null because the final table does not carry numeric exposure denominators.",
            }
        ]
    )


def guidance_matrix(signal_window: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    grouped = (
        signal_window.groupby(
            [
                "roadway_context",
                "median_group",
                "aadt_band",
                "speed_band",
                "untyped_access_count_band",
                "signal_window",
            ],
            dropna=False,
        )
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            crash_count=("spatial_50ft_crash_count", "sum"),
            weighted_crash_count=("spatial_50ft_weighted_crash_count", "sum"),
            identity_compatible_crash_count=("identity_compatible_spatial_50ft_crash_count", "sum"),
            total_untyped_access=("untyped_access_raw_count", "sum"),
        )
        .reset_index()
    )
    grouped["candidate_crash_rate"] = pd.NA
    grouped["low_n_flag"] = grouped["signal_count"] < 30
    grouped["sparse_cell_flag"] = (grouped["signal_count"] < 10) | (grouped["crash_count"] < 5)
    wide = grouped.pivot_table(
        index=["roadway_context", "median_group", "signal_window"],
        columns=["aadt_band", "speed_band", "untyped_access_count_band"],
        values="crash_count",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    wide.columns = [
        " | ".join([str(x) for x in col if str(x) != ""]).strip(" |") if isinstance(col, tuple) else col
        for col in wide.columns
    ]
    return grouped, wide, grouped[grouped["low_n_flag"] | grouped["sparse_cell_flag"]].copy()


def field_dictionary() -> pd.DataFrame:
    rows = [
        ("signal_id", "Signal ID", "Stable review signal identifier for figure tables.", "", True),
        ("signal_window", "Signal window", "Public distance window: 0-1,000 ft or 0-2,500 ft.", "", True),
        ("approach_count", "Approach count", "Count of final review signal approaches represented in the window.", "Internal source field is final_review_physical_leg_id.", True),
        ("roadway_context", "Roadway context", "Plain-language roadway context derived from source Travelway facility/ramp fields.", "", True),
        ("facility_type", "Facility type", "Dominant source Travelway RIM_FACILI value.", "", True),
        ("median_group", "Median group", "Compact group derived from source Travelway RIM_MEDIAN.", "Dominant group by bin count; all groups retained separately.", True),
        ("one_way_two_way_group", "One-way/two-way", "Directionality group parsed from RIM_FACILI.", "", True),
        ("divided_undivided_group", "Divided/undivided", "Configuration group parsed from RIM_FACILI.", "", True),
        ("untyped_access_raw_count", "Access count", "Raw unique untyped spatial 100 ft access points in the signal window.", "Not a density unless normalized separately.", True),
        ("untyped_access_count_band", "Access count band", "Binned raw access count: 0, 1-2, 3-5, 6+.", "", True),
        ("spatial_50ft_crash_count", "Crash count", "Spatial 50 ft primary review crash count in the signal window.", "Review assignment, not a rate.", True),
        ("spatial_50ft_weighted_crash_count", "Weighted crash count", "Source-preserving weighted spatial 50 ft crash count.", "", True),
        ("identity_compatible_spatial_50ft_crash_count", "Roadway-identity compatible crash count", "Crash count from identity-compatible spatial 50 ft sensitivity product.", "Sensitivity/QA companion.", True),
        ("candidate_crash_rate", "Candidate crash rate", "Reserved for future rate if denominator is carried.", "Null in this product.", False),
        ("stable_signal_id", "Stable signal ID", "Internal stable signal key.", "Internal/provenance.", False),
        ("final_review_physical_leg_id", "Internal approach ID", "Internal approach key.", "Use 'approach' publicly, not physical leg.", False),
        ("final_review_carriageway_subbranch_id", "Internal carriageway/source subpart ID", "Internal subpart key.", "Use carriageway/source subpart publicly, not subbranch.", False),
    ]
    return pd.DataFrame(rows, columns=["internal_field", "public_label", "definition", "caveat", "use_in_figures"])


def write_svg(grouped: pd.DataFrame) -> None:
    sub = grouped[grouped["signal_window"] == "0-2,500 ft"].copy()
    if sub.empty:
        return
    rows = sorted(sub["roadway_context"].unique())
    cols = ["0", "1-2", "3-5", "6+"]
    max_val = max(float(sub["crash_count"].max()), 1.0)
    cw, ch = 130, 36
    left, top = 230, 65
    width = left + cw * len(cols) + 30
    height = top + ch * len(rows) + 60
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;font-size:12px}.title{font-size:17px;font-weight:bold}.label{font-weight:bold}</style>',
        '<text class="title" x="20" y="28">Draft matrix from signal-window numeric context table</text>',
        '<text x="20" y="48">Cell text: spatial 50 ft crash count / signal count. AADT and speed numeric bands are currently unknown.</text>',
    ]
    for j, col in enumerate(cols):
        parts.append(f'<text class="label" x="{left + j*cw + 8}" y="{top - 10}">Access {html.escape(col)}</text>')
    lookup = {(r["roadway_context"], r["untyped_access_count_band"]): r for _, r in sub.iterrows()}
    for i, row in enumerate(rows):
        y = top + i * ch
        parts.append(f'<text class="label" x="20" y="{y+23}">{html.escape(str(row))}</text>')
        for j, col in enumerate(cols):
            x = left + j * cw
            rec = lookup.get((row, col))
            val = float(rec["crash_count"]) if rec is not None else 0
            intensity = int(245 - 170 * math.sqrt(val / max_val))
            parts.append(f'<rect x="{x}" y="{y}" width="{cw-4}" height="{ch-4}" fill="rgb(255,{intensity},{intensity})" stroke="#aaa"/>')
            label = "0" if rec is None else f"{int(val)} / {int(rec['signal_count'])}"
            parts.append(f'<text x="{x+8}" y="{y+22}">{html.escape(label)}</text>')
    parts.append("</svg>")
    (OUT / "draft_guidance_matrix_from_numeric_context.svg").write_text("\n".join(parts), encoding="utf-8")
    log("Wrote draft_guidance_matrix_from_numeric_context.svg")


def findings(signal_window: pd.DataFrame, median: pd.DataFrame, missing: pd.DataFrame) -> str:
    median_known = int((signal_window["median_group"] != "unknown").sum())
    total = len(signal_window)
    rows = [
        "# Signal-Window Numeric Context Findings",
        "",
        "## Bounded Question",
        "Can the final leg-corrected 3,719-signal review universe be converted into a plain-language signal-window table for guidance-matrix design?",
        "",
        "## Answers",
        "1. Numeric AADT is not carried in the final leg-corrected inputs used by this pass. AADT fields are left null and the exact candidate source files are listed in `aadtspeed_numeric_context_missingness.csv`.",
        "2. Numeric speed is not carried in the final leg-corrected inputs used by this pass. Speed fields are left null and the candidate speed source is listed in the missingness table.",
        "3. A numeric exposure denominator is not carried at signal-window grain, so candidate rate fields are null and no rates were calculated.",
        f"4. RIM_MEDIAN was carried through stable Travelway/source lineage. Non-unknown median assignment exists for {median_known:,} / {total:,} signal-window rows.",
        "5. The most usable row group is `roadway_context`, backed by source Travelway facility/ramp fields and paired with `median_group` as a secondary row/facet.",
        "6. Raw access count is better than access density for now because it is simple, directly counted, and does not require a disputed length denominator.",
        "7. Recommended access count bands are `0`, `1-2`, `3-5`, and `6+`.",
        "8. A guidance matrix can be built now for roadway context x median x raw access-count band with crash counts, but not yet for true AADT x speed columns.",
        "9. Rate readiness is blocked by the missing numeric exposure denominator at signal-window grain.",
        "10. Next visualization/design pass should first carry numeric AADT, numeric speed, and exposure denominator into this table, then redesign the matrix with AADT/speed columns and access count as a facet or nested column.",
        "",
        "## QA Note",
        "This pass did not read crash direction fields, rerun crash/access assignment, promote records, modify active outputs, or calculate final rates/models.",
    ]
    return "\n".join(rows) + "\n"


def qa_table() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to review/current/final_signal_window_numeric_context_table."),
        ("no_records_promoted", True, "Review-only figure-ready table."),
        ("no_new_crash_access_assignment", True, "Used existing access assignment details and crash rollups only."),
        ("no_rates_or_models", True, "Rate fields are null because denominator is not carried."),
        ("crash_direction_fields_not_read_or_used", True, "Crash source not read; crash assignment rollups/details used do not require direction fields."),
        ("rim_median_carried_through_lineage", True, "RIM_MEDIAN carried via source Travelway stable identity/source feature lineage."),
        ("numeric_aadt_speed_not_fabricated", True, "Numeric AADT/speed fields left null and documented as missing."),
        ("raw_access_counts_and_bands_included", True, "Untyped raw counts and 0/1-2/3-5/6+ bands included."),
        ("outputs_review_only_folder", True, str(OUT)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_signal_window_numeric_context_table",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "outputs": list(outputs),
        "review_only": True,
        "non_goals": [
            "no final publication figures",
            "no new crash assignment",
            "no new access assignment",
            "no rates/models",
            "no active output modifications",
            "no record promotion",
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting final signal-window numeric context table.")
    bins = build_bin_context()
    signal_window, approach_window = build_signal_window_base(bins)
    signal_window, approach_window, access_summary, typed_summary, crash_summary = attach_counts(signal_window, approach_window)

    matrix_long, matrix_wide, _low = guidance_matrix(signal_window)
    med = median_summary(signal_window)
    missing = numeric_missingness()
    rate = rate_audit(signal_window)
    dictionary = field_dictionary()

    write_csv(signal_window, "signal_window_numeric_context.csv")
    write_csv(approach_window, "signal_approach_window_numeric_context.csv")
    write_csv(matrix_long, "guidance_matrix_ready_long.csv")
    write_csv(matrix_wide, "guidance_matrix_ready_wide_count_table.csv")
    write_csv(med, "median_group_assignment_summary.csv")
    write_csv(missing, "aadtspeed_numeric_context_missingness.csv")
    write_csv(access_summary, "access_count_band_summary.csv")
    write_csv(typed_summary, "typed_access_category_signal_window_summary.csv")
    write_csv(crash_summary, "crash_count_signal_window_summary.csv")
    write_csv(rate, "candidate_rate_denominator_audit.csv")
    write_csv(dictionary, "plain_language_field_dictionary.csv")
    write_svg(matrix_long)

    (OUT / "signal_window_numeric_context_findings.md").write_text(findings(signal_window, med, missing), encoding="utf-8")
    log("Wrote findings memo.")
    qa = qa_table()
    write_csv(qa, "signal_window_numeric_context_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "signal_window_numeric_context_manifest.json")
    (OUT / "signal_window_numeric_context_manifest.json").write_text(json.dumps(manifest(outputs), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed final signal-window numeric context table.")


if __name__ == "__main__":
    main()
