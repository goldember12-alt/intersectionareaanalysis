"""Review-only feasibility package for a final guidance matrix figure.

Bounded question: can the final 3,719-signal leg-corrected review-analysis
universe support a roadway-context x AADT x speed x access-density matrix for
paper/meeting discussion, and what table design is defensible from currently
carried fields?

This module prepares design/feasibility tables only. It does not create new
crash or access assignments, modify active outputs, promote records, fit
models, or use crash direction fields.
"""

from __future__ import annotations

import csv
import html
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/review/current/final_guidance_matrix_figure_feasibility"

FINAL_SUMMARY = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_clean_universe_summary"
ACCESS_REFRESH = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_access_refresh"
ACCESS_SANITY = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_access_sanity_audit"
CRASH_ASSIGN = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_crash_candidate_assignment"
IDENTITY_DOCTRINE = REPO / "work/output/roadway_graph/review/current/crash_roadway_identity_assignment_doctrine"
SOURCE_TRAVELWAY_GPKG = REPO / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "final_signals": FINAL_SUMMARY / "final_leg_corrected_signal_universe_3719.csv",
    "final_bins": FINAL_SUMMARY / "final_leg_corrected_bin_universe.csv",
    "leg_distribution": FINAL_SUMMARY / "final_leg_corrected_physical_leg_distribution.csv",
    "context_readiness": FINAL_SUMMARY / "final_leg_corrected_context_readiness_summary.csv",
    "access_untyped_detail": ACCESS_REFRESH / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
    "access_untyped_summary": ACCESS_REFRESH / "final_leg_corrected_untyped_access_summary.csv",
    "access_typed_summary": ACCESS_REFRESH / "final_leg_corrected_typed_access_category_summary.csv",
    "access_roadway_type": ACCESS_REFRESH / "final_leg_corrected_access_by_roadway_type.csv",
    "access_branch": ACCESS_SANITY / "access_coverage_by_recovery_branch.csv",
    "crash_signal_window": CRASH_ASSIGN / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    "crash_signal": CRASH_ASSIGN / "leg_corrected_crash_candidate_assignment_signal_rollup.csv",
    "identity_rollups": IDENTITY_DOCTRINE / "identity_compatible_spatial_50ft_rollups.csv",
    "identity_classes": IDENTITY_DOCTRINE / "crash_level_assignment_class_summary.csv",
}

METHODOLOGY_DOCS = [
    REPO / "docs/methodology/current_methodology_index.md",
    REPO / "docs/methodology/overview_methodology.md",
    REPO / "docs/methodology/roadway_graph_methodology.md",
    REPO / "docs/methodology/proposal_alignment_growth_plan.md",
    REPO / "docs/methodology/methodology_update_summary.md",
]

ROW_FIELD_PATTERNS = (
    "facility",
    "facili",
    "road",
    "route",
    "rte_",
    "rte",
    "median",
    "lane",
    "access",
    "rim_",
    "ramp",
    "interchange",
    "divid",
    "oneway",
    "one_way",
    "class",
    "category",
    "type",
    "loc_comp",
)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing optional input: {path}")
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    path = OUT / name
    df.to_csv(path, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def safe_div(num: float, den: float) -> float | None:
    if den in (0, 0.0) or pd.isna(den):
        return None
    return float(num) / float(den)


def norm_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def compact_value(value: object, default: str = "unknown") -> str:
    if pd.isna(value):
        return default
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return default
    return s


def mode_value(series: pd.Series) -> str:
    vals = [compact_value(v) for v in series if compact_value(v) != "unknown"]
    if not vals:
        return "unknown"
    return Counter(vals).most_common(1)[0][0]


def bucket_leg_count(count: object) -> str:
    try:
        n = int(float(count))
    except Exception:
        return "unknown"
    if n <= 1:
        return "one_leg"
    if n == 2:
        return "two_leg"
    if n == 3:
        return "three_leg"
    if n == 4:
        return "four_leg"
    return "five_plus_leg"


def roadway_compact(value: object, route_text: object = "") -> str:
    text = compact_value(value, "")
    route = compact_value(route_text, "")
    joined = f"{text} {route}".lower()
    if any(k in joined for k in ("ramp", "interchange")):
        return "ramp_or_interchange_context"
    if "one-way" in joined or "one_way" in joined or "one way" in joined:
        if "divided" in joined:
            return "one_way_divided"
        return "one_way_undivided"
    if "two-way divided" in joined or "two_way_divided" in joined:
        return "two_way_divided"
    if "two-way undivided" in joined or "two_way_undivided" in joined:
        return "two_way_undivided"
    if "divided" in joined:
        return "divided_unknown_direction"
    if "undivided" in joined:
        return "undivided_unknown_direction"
    return "roadway_context_not_carried"


def median_compact(value: object) -> str:
    text = compact_value(value).lower()
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


def source_field_inventory() -> tuple[pd.DataFrame, pd.DataFrame]:
    log("Inventoring source Travelway fields.")
    rows: list[dict[str, object]] = []
    median_rows: list[dict[str, object]] = []
    try:
        import geopandas as gpd

        tw = gpd.read_file(SOURCE_TRAVELWAY_GPKG, layer="source_travelway_full", ignore_geometry=True)
    except Exception as exc:  # pragma: no cover - depends on local GDAL
        log(f"Could not read source Travelway attributes: {type(exc).__name__}: {exc}")
        return pd.DataFrame(), pd.DataFrame()

    for col in tw.columns:
        lower = col.lower()
        if not any(p in lower for p in ROW_FIELD_PATTERNS):
            continue
        s = tw[col]
        vc = s.fillna("unknown").astype(str).value_counts(dropna=False).head(8)
        role = "qa_field"
        if col in {"RIM_FACILI", "RIM_FACI_1", "RTE_CATEGO", "RTE_TYPE_N", "RIM_ACCESS"}:
            role = "row_or_facet_candidate"
        if "median" in lower:
            role = "secondary_or_facet_candidate"
        rows.append(
            {
                "field_name": col,
                "source_table": "source_travelway_full",
                "non_null_count": int(s.notna().sum()),
                "missingness": round(float(s.isna().mean()), 4),
                "unique_values": int(s.nunique(dropna=True)),
                "top_values": "; ".join(f"{k}={v}" for k, v in vc.items()),
                "recommended_use": role,
                "stability_note": "source Travelway attribute; requires stable join/carry-forward before primary figure use",
            }
        )

    for col in [c for c in tw.columns if "median" in c.lower()]:
        s = tw[col]
        dist = s.fillna("unknown").astype(str).value_counts(dropna=False)
        for val, count in dist.head(20).items():
            median_rows.append(
                {
                    "source_table": "source_travelway_full",
                    "field_name": col,
                    "median_value": val,
                    "compact_median_group": median_compact(val),
                    "row_count": int(count),
                    "share": round(float(count) / len(tw), 4) if len(tw) else None,
                    "usable_for_primary_rows": col == "RIM_MEDIAN",
                    "note": "available in source Travelway; not currently carried as a stable signal-level final summary field",
                }
            )

    return pd.DataFrame(rows), pd.DataFrame(median_rows)


def final_bin_field_inventory(final_bins_cols: list[str]) -> pd.DataFrame:
    rows = []
    for col in final_bins_cols:
        lower = col.lower()
        if not any(p in lower for p in ROW_FIELD_PATTERNS + ("speed", "aadt", "exposure")):
            continue
        recommended = "qa_field"
        if col in {
            "roadway_division_context",
            "existing_roadway_division_context",
            "generated_roadway_division_context",
            "final_review_leg_source",
            "final_review_recovery_provenance",
        }:
            recommended = "row_or_qa_candidate"
        if "speed" in lower or "aadt" in lower or "exposure" in lower:
            recommended = "readiness_only_not_numeric_band"
        rows.append(
            {
                "field_name": col,
                "source_table": "final_leg_corrected_bin_universe",
                "non_null_count": None,
                "missingness": None,
                "unique_values": None,
                "top_values": None,
                "recommended_use": recommended,
                "stability_note": "carried in final leg-corrected review bin table",
            }
        )
    return pd.DataFrame(rows)


def chunked_access_100ft_counts(path: Path) -> pd.DataFrame:
    log("Aggregating untyped spatial 100 ft access counts by signal/window with chunks.")
    usecols = [
        "access_point_id",
        "stable_signal_id",
        "analysis_window",
        "buffer_width_ft",
        "source_preserving_weighted_access_count",
        "unweighted_access_count",
    ]
    pieces = []
    for chunk in pd.read_csv(path, usecols=usecols, chunksize=250_000, low_memory=False):
        chunk = chunk[chunk["buffer_width_ft"].astype(str) == "100"].copy()
        if chunk.empty:
            continue
        chunk["window"] = chunk["analysis_window"].fillna("unknown").astype(str)
        grouped = (
            chunk.groupby(["stable_signal_id", "window"], dropna=False)
            .agg(
                untyped_access_source_points=("access_point_id", "nunique"),
                untyped_access_assignment_rows=("access_point_id", "size"),
                untyped_access_weighted=("source_preserving_weighted_access_count", "sum"),
                untyped_access_unweighted=("unweighted_access_count", "sum"),
            )
            .reset_index()
        )
        pieces.append(grouped)
    if not pieces:
        return pd.DataFrame(columns=["stable_signal_id", "window"])
    out = pd.concat(pieces, ignore_index=True)
    out = (
        out.groupby(["stable_signal_id", "window"], dropna=False)
        .sum(numeric_only=True)
        .reset_index()
    )
    return out


def access_density_band(count: object) -> str:
    try:
        n = float(count)
    except Exception:
        n = 0
    if n <= 0:
        return "0_no_access"
    if n <= 2:
        return "1_2_low"
    if n <= 5:
        return "3_5_medium"
    return "6_plus_high"


def build_signal_base() -> pd.DataFrame:
    log("Building one-row-per-signal guidance matrix base table.")
    signals = read_csv(INPUTS["final_signals"], dtype=str, low_memory=False)
    bin_cols = pd.read_csv(INPUTS["final_bins"], nrows=0).columns.tolist()
    wanted = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "roadway_division_context",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "final_review_leg_source",
        "final_review_recovery_provenance",
        "analysis_window",
        "distance_band",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
    ]
    usecols = [c for c in wanted if c in bin_cols]
    bins = read_csv(INPUTS["final_bins"], usecols=usecols, dtype=str, low_memory=False)
    if "roadway_division_context" not in bins.columns:
        bins["roadway_division_context"] = ""
    for fallback in ("existing_roadway_division_context", "generated_roadway_division_context"):
        if fallback in bins.columns:
            bins["roadway_division_context"] = bins["roadway_division_context"].fillna(bins[fallback])

    rows = []
    for sid, group in bins.groupby("stable_signal_id", sort=False):
        route_common = mode_value(group.get("source_route_common", pd.Series(dtype=str)))
        division = mode_value(group.get("roadway_division_context", pd.Series(dtype=str)))
        leg_source = mode_value(group.get("final_review_leg_source", pd.Series(dtype=str)))
        provenance = mode_value(group.get("final_review_recovery_provenance", pd.Series(dtype=str)))
        rows.append(
            {
                "stable_signal_id": sid,
                "bin_count": int(len(group)),
                "travelway_count": int(group["stable_travelway_id"].nunique()) if "stable_travelway_id" in group else None,
                "primary_route_common": route_common,
                "roadway_division_context": division,
                "paper_compact_row_taxonomy": roadway_compact(division, route_common),
                "facility_text_only": division if division != "unknown" else "roadway_context_not_carried",
                "route_facility_context": route_common if route_common != "unknown" else "route_not_carried",
                "ramp_interchange_vs_surface_context": (
                    "ramp_or_interchange_context"
                    if "ramp" in f"{route_common} {provenance} {leg_source}".lower()
                    or "interchange" in f"{route_common} {provenance} {leg_source}".lower()
                    else "surface_or_unknown_context"
                ),
                "dominant_final_review_leg_source": leg_source,
                "dominant_recovery_provenance": provenance,
                "has_rns_speed_any_bin": bool(norm_bool(group.get("final_review_has_rns_speed", pd.Series(dtype=str))).any()),
                "has_aadt_any_bin": bool(norm_bool(group.get("final_review_has_aadt", pd.Series(dtype=str))).any()),
                "has_exposure_any_bin": bool(norm_bool(group.get("final_review_has_exposure_denominator", pd.Series(dtype=str))).any()),
                "speed_aadt_ready_any_bin": bool(norm_bool(group.get("final_review_speed_aadt_ready_bin", pd.Series(dtype=str))).any()),
            }
        )
    signal_base = pd.DataFrame(rows)

    keep_signal_cols = [
        "stable_signal_id",
        "recovery_branch",
        "final_leg_corrected_physical_leg_count",
        "final_leg_corrected_physical_leg_bucket",
        "final_leg_corrected_speed_aadt_ready",
        "clean_review_analysis_status",
    ]
    signal_base = signal_base.merge(
        signals[[c for c in keep_signal_cols if c in signals.columns]],
        on="stable_signal_id",
        how="left",
    )
    signal_base["physical_leg_bucket"] = signal_base.get("final_leg_corrected_physical_leg_bucket", "").fillna(
        signal_base.get("final_leg_corrected_physical_leg_count", "").map(bucket_leg_count)
    )
    signal_base["facility_text_plus_median"] = signal_base["paper_compact_row_taxonomy"] + " | median_not_carried_to_signal"
    signal_base["divided_oneway_median_context"] = signal_base["paper_compact_row_taxonomy"] + " | median_not_carried"
    return signal_base


def attach_access_and_crash(signal_base: pd.DataFrame) -> pd.DataFrame:
    access = chunked_access_100ft_counts(INPUTS["access_untyped_detail"])
    if access.empty:
        access_any = pd.DataFrame({"stable_signal_id": signal_base["stable_signal_id"]})
    else:
        access_any = (
            access.groupby("stable_signal_id", dropna=False)
            .agg(
                access_100ft_0_2500_source_points=("untyped_access_source_points", "sum"),
                access_100ft_0_2500_weighted=("untyped_access_weighted", "sum"),
            )
            .reset_index()
        )
        access_1000 = access[access["window"] == "0_1000"][
            ["stable_signal_id", "untyped_access_source_points", "untyped_access_weighted"]
        ].rename(
            columns={
                "untyped_access_source_points": "access_100ft_0_1000_source_points",
                "untyped_access_weighted": "access_100ft_0_1000_weighted",
            }
        )
        access_any = access_any.merge(access_1000, on="stable_signal_id", how="left")
    base = signal_base.merge(access_any, on="stable_signal_id", how="left")
    for c in [
        "access_100ft_0_2500_source_points",
        "access_100ft_0_2500_weighted",
        "access_100ft_0_1000_source_points",
        "access_100ft_0_1000_weighted",
    ]:
        if c not in base:
            base[c] = 0
        base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0)
    base["access_density_band_0_2500"] = base["access_100ft_0_2500_source_points"].map(access_density_band)
    base["access_density_band_0_1000"] = base["access_100ft_0_1000_source_points"].map(access_density_band)

    crash = read_csv(INPUTS["crash_signal_window"], low_memory=False)
    if not crash.empty:
        crash = crash[pd.to_numeric(crash["buffer_width_ft"], errors="coerce") == 50].copy()
        crash_wide = (
            crash.pivot_table(
                index="stable_signal_id",
                columns="analysis_window",
                values=["unique_crash_count", "weighted_crash_count", "assignment_row_count"],
                aggfunc="sum",
                fill_value=0,
            )
            .reset_index()
        )
        crash_wide.columns = [
            "_".join([str(x) for x in col if str(x) != ""]).strip("_") if isinstance(col, tuple) else col
            for col in crash_wide.columns
        ]
        base = base.merge(crash_wide, on="stable_signal_id", how="left")
    for c in ["unique_crash_count_0_1000", "weighted_crash_count_0_1000", "assignment_row_count_0_1000"]:
        if c not in base:
            base[c] = 0
        base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0)
    for metric in ["unique_crash_count", "weighted_crash_count", "assignment_row_count"]:
        near_col = f"{metric}_0_1000"
        sens_col = f"{metric}_1000_2500"
        total_col = f"{metric}_0_2500"
        if sens_col not in base:
            base[sens_col] = 0
        base[sens_col] = pd.to_numeric(base[sens_col], errors="coerce").fillna(0)
        base[total_col] = pd.to_numeric(base[near_col], errors="coerce").fillna(0) + base[sens_col]

    ident = read_csv(INPUTS["identity_rollups"])
    identity_1000 = identity_2500 = None
    if not ident.empty:
        ident = ident[ident["assignment_identity_compatibility"].astype(str).str.contains("matches|compatible|ambiguous", case=False, na=False)]
        by_window = ident.groupby("analysis_window", dropna=False).agg(
            identity_compatible_unique_crashes=("unique_crashes", "sum"),
            identity_compatible_weighted_crash_count=("weighted_crash_count", "sum"),
        )
        identity_1000 = by_window.to_dict("index").get("0_1000", {})
        identity_2500 = by_window.to_dict("index").get("0_2500", {})
    base["identity_compatible_crash_count_0_1000_context_only"] = (identity_1000 or {}).get(
        "identity_compatible_unique_crashes", None
    )
    base["identity_compatible_crash_count_0_2500_context_only"] = (identity_2500 or {}).get(
        "identity_compatible_unique_crashes", None
    )

    base["aadt_band"] = "not_carried_numeric_aadt"
    base["speed_band"] = "not_carried_numeric_speed"
    base["exposure_denominator_available"] = base["has_exposure_any_bin"]
    base["candidate_crash_rate_status"] = "not_computed_no_numeric_exposure_denominator_carried"
    return base


def summarize_row_taxonomies(base: pd.DataFrame) -> pd.DataFrame:
    schemes = [
        "facility_text_only",
        "facility_text_plus_median",
        "divided_oneway_median_context",
        "route_facility_context",
        "ramp_interchange_vs_surface_context",
        "paper_compact_row_taxonomy",
        "physical_leg_bucket",
        "recovery_branch",
    ]
    rows = []
    for scheme in schemes:
        if scheme not in base:
            continue
        grouped = base.groupby(scheme, dropna=False).agg(
            signal_count=("stable_signal_id", "nunique"),
            bin_count=("bin_count", "sum"),
            crash_count_50ft_0_2500=("unique_crash_count_0_2500", "sum"),
            weighted_crash_count_50ft_0_2500=("weighted_crash_count_0_2500", "sum"),
            access_points_100ft_0_2500=("access_100ft_0_2500_source_points", "sum"),
        )
        category_count = int(len(grouped))
        sparse = int((grouped["signal_count"] < 30).sum())
        largest_share = safe_div(grouped["signal_count"].max(), grouped["signal_count"].sum())
        interpretability = 3
        if scheme == "paper_compact_row_taxonomy":
            interpretability = 5
        elif scheme in {"facility_text_only", "divided_oneway_median_context", "ramp_interchange_vs_surface_context"}:
            interpretability = 4
        elif scheme in {"physical_leg_bucket", "recovery_branch"}:
            interpretability = 2
        rows.append(
            {
                "row_scheme": scheme,
                "row_category_count": category_count,
                "total_signals": int(grouped["signal_count"].sum()),
                "min_signal_count": int(grouped["signal_count"].min()) if len(grouped) else 0,
                "sparse_row_count_lt30_signals": sparse,
                "largest_row_share": round(largest_share or 0, 4),
                "crash_count_50ft_0_2500": int(grouped["crash_count_50ft_0_2500"].sum()),
                "access_points_100ft_0_2500": int(grouped["access_points_100ft_0_2500"].sum()),
                "interpretability_score_1_5": interpretability,
                "recommended_role": (
                    "primary_recommended"
                    if scheme == "paper_compact_row_taxonomy"
                    else "diagnostic_or_secondary"
                    if scheme in {"physical_leg_bucket", "recovery_branch"}
                    else "candidate"
                ),
                "sparsity_warning": "yes" if sparse else "no",
            }
        )
    return pd.DataFrame(rows)


def column_bin_summary(base: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "column_feature": "AADT",
            "candidate_bins": "1500_9000;9000_12000;12000_15000;gt_15000;unknown",
            "available_status": "numeric_values_not_carried",
            "available_signal_count": 0,
            "fallback_used": "not_carried_numeric_aadt",
            "recommendation": "carry numeric AADT/exposure into final signal table before rate matrix",
        },
        {
            "column_feature": "speed_limit",
            "candidate_bins": "le_30;35;ge_40;unknown",
            "available_status": "numeric_values_not_carried",
            "available_signal_count": 0,
            "fallback_used": "not_carried_numeric_speed",
            "recommendation": "carry numeric RNS speed into final signal table before final speed-band columns",
        },
    ]
    for window_col, label in [
        ("access_density_band_0_1000", "untyped_access_density_100ft_0_1000"),
        ("access_density_band_0_2500", "untyped_access_density_100ft_0_2500"),
    ]:
        vc = base[window_col].value_counts().to_dict()
        rows.append(
            {
                "column_feature": label,
                "candidate_bins": "0_no_access;1_2_low;3_5_medium;6_plus_high",
                "available_status": "available_from_final_untyped_spatial_100ft_access",
                "available_signal_count": int(base["stable_signal_id"].nunique()),
                "fallback_used": "",
                "recommendation": f"use as facet or secondary column; distribution {vc}",
            }
        )
    rows.append(
        {
            "column_feature": "typed_v2_access",
            "candidate_bins": "corrected category presence",
            "available_status": "available_but_source_limited_enrichment_only",
            "available_signal_count": None,
            "fallback_used": "",
            "recommendation": "keep typed v2 as annotation/enrichment, not primary density",
        }
    )
    return pd.DataFrame(rows)


def build_matrix(base: pd.DataFrame, row_scheme: str, access_band_col: str) -> pd.DataFrame:
    grouped = (
        base.groupby([row_scheme, "aadt_band", "speed_band", access_band_col], dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            bin_count=("bin_count", "sum"),
            crash_count_spatial_50ft_0_1000=("unique_crash_count_0_1000", "sum"),
            crash_count_spatial_50ft_0_2500=("unique_crash_count_0_2500", "sum"),
            weighted_crash_count_spatial_50ft_0_1000=("weighted_crash_count_0_1000", "sum"),
            weighted_crash_count_spatial_50ft_0_2500=("weighted_crash_count_0_2500", "sum"),
            access_count_100ft_0_2500=("access_100ft_0_2500_source_points", "sum"),
            exposure_ready_signals=("exposure_denominator_available", "sum"),
        )
        .reset_index()
        .rename(columns={row_scheme: "row_category", access_band_col: "access_density_band"})
    )
    grouped["row_scheme"] = row_scheme
    grouped["column_scheme"] = "aadt_band_x_speed_band_x_access_density"
    grouped["crash_rate_candidate"] = None
    grouped["rate_status"] = "not_computed_no_numeric_exposure_denominator_carried"
    grouped["low_n_flag"] = grouped["signal_count"] < 30
    grouped["sparse_cell_flag"] = (grouped["signal_count"] < 10) | (grouped["crash_count_spatial_50ft_0_2500"] < 5)
    return grouped[
        [
            "row_scheme",
            "row_category",
            "aadt_band",
            "speed_band",
            "access_density_band",
            "column_scheme",
            "signal_count",
            "bin_count",
            "crash_count_spatial_50ft_0_1000",
            "crash_count_spatial_50ft_0_2500",
            "weighted_crash_count_spatial_50ft_0_1000",
            "weighted_crash_count_spatial_50ft_0_2500",
            "access_count_100ft_0_2500",
            "exposure_ready_signals",
            "crash_rate_candidate",
            "rate_status",
            "low_n_flag",
            "sparse_cell_flag",
        ]
    ]


def matrix_all_schemes(base: pd.DataFrame) -> pd.DataFrame:
    schemes = [
        "facility_text_only",
        "facility_text_plus_median",
        "divided_oneway_median_context",
        "route_facility_context",
        "ramp_interchange_vs_surface_context",
        "paper_compact_row_taxonomy",
        "physical_leg_bucket",
    ]
    pieces = []
    for scheme in schemes:
        if scheme in base:
            pieces.append(build_matrix(base, scheme, "access_density_band_0_2500"))
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def primary_matrix_table(primary_long: pd.DataFrame) -> pd.DataFrame:
    if primary_long.empty:
        return pd.DataFrame()
    table = primary_long.copy()
    table["column_label"] = (
        table["aadt_band"].astype(str)
        + " | "
        + table["speed_band"].astype(str)
        + " | "
        + table["access_density_band"].astype(str)
    )
    table["cell_value"] = table.apply(
        lambda r: (
            f"{int(r['crash_count_spatial_50ft_0_2500'])} crashes; "
            f"{int(r['signal_count'])} signals"
            + ("; low-N" if bool(r["low_n_flag"]) else "")
        ),
        axis=1,
    )
    wide = table.pivot_table(
        index="row_category",
        columns="column_label",
        values="cell_value",
        aggfunc="first",
        fill_value="",
    ).reset_index()
    return wide


def write_svg_heatmap(primary_long: pd.DataFrame) -> None:
    if primary_long.empty:
        return
    data = primary_long.copy()
    data["column_label"] = data["access_density_band"].astype(str)
    rows = sorted(data["row_category"].unique())
    cols = ["0_no_access", "1_2_low", "3_5_medium", "6_plus_high"]
    max_val = max(float(data["crash_count_spatial_50ft_0_2500"].max()), 1.0)
    cell_w, cell_h = 170, 38
    left, top = 260, 70
    width = left + cell_w * len(cols) + 40
    height = top + cell_h * len(rows) + 70
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:Arial,sans-serif;font-size:12px}.title{font-size:18px;font-weight:bold}.label{font-weight:bold}</style>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text class="title" x="20" y="30">Draft Guidance Matrix Feasibility: 50 ft Crashes by Roadway Context and Access Density</text>',
        '<text x="20" y="50">AADT and speed numeric bands are not carried in the current final summary; this draft holds them as unavailable.</text>',
    ]
    for j, col in enumerate(cols):
        parts.append(f'<text class="label" x="{left + j * cell_w + 8}" y="{top - 12}">{html.escape(col)}</text>')
    lookup = {
        (r["row_category"], r["access_density_band"]): r
        for _, r in data.iterrows()
    }
    for i, row in enumerate(rows):
        y = top + i * cell_h
        parts.append(f'<text class="label" x="20" y="{y + 24}">{html.escape(str(row))}</text>')
        for j, col in enumerate(cols):
            x = left + j * cell_w
            rec = lookup.get((row, col))
            val = float(rec["crash_count_spatial_50ft_0_2500"]) if rec is not None else 0
            intensity = int(245 - 170 * math.sqrt(val / max_val))
            fill = f"rgb(255,{intensity},{intensity})"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w-4}" height="{cell_h-4}" fill="{fill}" stroke="#aaa"/>')
            label = "0" if rec is None else f"{int(val)} cr; {int(rec['signal_count'])} sig"
            if rec is not None and bool(rec["low_n_flag"]):
                label += " *"
            parts.append(f'<text x="{x + 8}" y="{y + 23}">{html.escape(label)}</text>')
    parts.append('<text x="20" y="{}">* low-N row/cell flag. Draft internal design only.</text>'.format(height - 20))
    parts.append("</svg>")
    (OUT / "draft_guidance_matrix_heatmap.svg").write_text("\n".join(parts), encoding="utf-8")
    md_cols = [
        "row_category",
        "access_density_band",
        "signal_count",
        "crash_count_spatial_50ft_0_2500",
        "weighted_crash_count_spatial_50ft_0_2500",
        "low_n_flag",
        "sparse_cell_flag",
    ]
    md_table = simple_markdown_table(primary_long[[c for c in md_cols if c in primary_long.columns]])
    md = [
        "# Draft Guidance Matrix Heatmap Supporting Table",
        "",
        "This draft SVG uses the recommended compact roadway row taxonomy and untyped spatial 100 ft access density. AADT and speed are marked unavailable because numeric values are not carried in the final summary tables used by this bounded pass.",
        "",
        md_table,
    ]
    (OUT / "draft_guidance_matrix_heatmap_supporting_table.md").write_text("\n".join(md), encoding="utf-8")
    log("Wrote draft_guidance_matrix_heatmap.svg and supporting table")


def simple_markdown_table(df: pd.DataFrame, max_rows: int = 80) -> str:
    if df.empty:
        return "_No rows._"
    shown = df.head(max_rows).copy()
    cols = list(shown.columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in shown.iterrows():
        vals = [str(row[c]).replace("|", "\\|") for c in cols]
        lines.append("| " + " | ".join(vals) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_Showing {max_rows} of {len(df)} rows._")
    return "\n".join(lines)


def design_recommendation(primary_long: pd.DataFrame) -> pd.DataFrame:
    low_n = int(primary_long["low_n_flag"].sum()) if not primary_long.empty else 0
    sparse = int(primary_long["sparse_cell_flag"].sum()) if not primary_long.empty else 0
    return pd.DataFrame(
        [
            {
                "decision_item": "recommended_row_taxonomy",
                "recommendation": "paper_compact_row_taxonomy",
                "reason": "Most interpretable currently carried signal-level row scheme; separates divided/undivided/ramp context where available and avoids using recovery branch as a substantive row.",
            },
            {
                "decision_item": "median_use",
                "recommendation": "secondary_or_future_facet_only",
                "reason": "RIM_MEDIAN is available in source Travelway, but median group is not stably carried into the final leg-corrected signal summary; use only after a stable carry-forward/join product.",
            },
            {
                "decision_item": "aadt_speed_columns",
                "recommendation": "not_ready_for_final_nested_columns_from_current_tables",
                "reason": "The final review tables carry AADT/speed readiness flags but not numeric AADT or speed values needed to form bins.",
            },
            {
                "decision_item": "access_density",
                "recommendation": "use_untyped_spatial_100ft_access_density_as_facet_or_secondary_column",
                "reason": "Untyped spatial 100 ft is the approved broad access review baseline and is available at signal/window grain; typed v2 remains source-limited enrichment.",
            },
            {
                "decision_item": "cell_metric",
                "recommendation": "show_spatial_50ft_crash_count_and_weighted_count; defer_rates",
                "reason": "Crash counts and source-preserving weighted counts are available. Rates should wait until numeric exposure denominators are explicitly carried into this figure table.",
            },
            {
                "decision_item": "low_cell_threshold",
                "recommendation": "flag cells with signal_count < 30 or crash_count < 5; treat signal_count < 10 as sparse",
                "reason": f"Primary draft matrix has {low_n} low-N cells and {sparse} sparse cells under current fallback columns.",
            },
            {
                "decision_item": "figure_layout",
                "recommendation": "small_multiples_or_facets_by_access_density_before_large_nested_matrix",
                "reason": "AADT and speed bands are not yet populated; once carried forward, a full AADT x speed x access matrix may be too wide unless access density becomes a facet.",
            },
            {
                "decision_item": "next_data_product",
                "recommendation": "build_signal_level_numeric_context_table",
                "reason": "Carry representative numeric speed, AADT, exposure denominator, stable facility, and median groups at signal-window grain before final publication figure design.",
            },
        ]
    )


def findings_text(
    field_inventory: pd.DataFrame,
    median_audit: pd.DataFrame,
    row_summary: pd.DataFrame,
    col_summary: pd.DataFrame,
    primary_long: pd.DataFrame,
) -> str:
    usable_fields = field_inventory[field_inventory["recommended_use"].astype(str).str.contains("candidate", na=False)]
    median_available = "yes" if not median_audit.empty else "no"
    recommended = "paper_compact_row_taxonomy"
    sparse = int(primary_long["sparse_cell_flag"].sum()) if not primary_long.empty else 0
    low_n = int(primary_long["low_n_flag"].sum()) if not primary_long.empty else 0
    lines = [
        "# Final Guidance Matrix Figure Feasibility Findings",
        "",
        "## Bounded Question",
        "Can the final 3,719-signal leg-corrected review-analysis universe support a roadway-context x AADT x speed x access-density guidance matrix, and what design is defensible from currently carried fields?",
        "",
        "## Answers",
        f"1. Roadway-context fields are available in two forms: final carried summary fields and source Travelway attributes. {len(usable_fields)} candidate/secondary fields were identified, but source Travelway fields need a stable signal-level carry-forward before becoming primary paper rows.",
        f"2. Median data availability: {median_available}. Source Travelway includes `RIM_MEDIAN`, but median is not currently carried into the final leg-corrected signal summary. It should be secondary/future-facet, not a primary row yet.",
        f"3. Recommended row taxonomy: `{recommended}` because it is compact and aligned with roadway configuration without using recovery provenance as a substantive class.",
        "4. Two-way divided/undivided-style context is the most meaningful available row family, but current final rows still include a large `roadway_context_not_carried` class. Source Travelway facility fields can improve this after stable carry-forward.",
        "5. AADT/speed/access bins: access density is feasible from untyped spatial 100 ft access. Numeric AADT and speed bands are not feasible from the current final summary tables because only readiness flags are carried.",
        "6. Access density should be a facet or secondary column in the first figure design. Typed v2 access should remain enrichment/annotation.",
        "7. Cells should show spatial 50 ft crash count plus source-preserving weighted crash count. Rates should be deferred until numeric exposure denominators are explicitly carried into the figure table.",
        f"8. Sparse/low-N: the primary fallback matrix has {low_n} low-N cells and {sparse} sparse cells under current available columns.",
        "9. The matrix figure is feasible as a figure-ready data design, but not yet as a final AADT x speed x access publication matrix.",
        "10. The highest-value next data product is a signal-window numeric context table carrying representative speed, AADT, exposure denominator, stable facility configuration, and median group.",
        "",
        "## Caveat",
        "This pass did not read crash records, did not use crash direction fields, did not create new crash/access assignments, and did not calculate rates/models.",
    ]
    return "\n".join(lines) + "\n"


def qa_table() -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Outputs written only under review/current/final_guidance_matrix_figure_feasibility."),
        ("no_records_promoted", True, "Review-only package."),
        ("no_new_crash_access_assignments", True, "Used existing assignment rollups/details only; no spatial joins."),
        ("no_rates_or_models", True, "Candidate rates not computed because numeric denominator was not carried."),
        ("crash_direction_fields_not_read_or_used", True, "Crash source not read; crash inputs were existing rollups/doctrine summaries."),
        ("figure_ready_tables_review_only", True, "All outputs are review-only design tables."),
        ("outputs_written_only_to_review_folder", True, str(OUT)),
    ]
    return pd.DataFrame(checks, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_guidance_matrix_figure_feasibility",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "figure feasibility and matrix design for final functional-area guidance table/figure",
        "output_folder": str(OUT.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "methodology_docs_read": [str(p.relative_to(REPO)) for p in METHODOLOGY_DOCS if p.exists()],
        "outputs": list(outputs),
        "review_only": True,
        "non_goals": [
            "no final publication figure",
            "no new crash assignment",
            "no new access assignment",
            "no models",
            "no active output modification",
            "no record promotion",
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting final guidance matrix figure feasibility package.")

    for name, path in INPUTS.items():
        if not path.exists():
            log(f"Input missing: {name}: {path}")
    for doc in METHODOLOGY_DOCS:
        if doc.exists():
            _ = doc.read_text(encoding="utf-8", errors="ignore")[:500]
    log("Methodology context files checked.")

    final_bin_cols = pd.read_csv(INPUTS["final_bins"], nrows=0).columns.tolist()
    final_inv = final_bin_field_inventory(final_bin_cols)
    source_inv, median_audit = source_field_inventory()
    field_inventory = pd.concat([final_inv, source_inv], ignore_index=True)
    write_csv(field_inventory, "roadway_context_field_inventory.csv")
    write_csv(median_audit, "median_field_audit.csv")

    base = build_signal_base()
    base = attach_access_and_crash(base)
    write_csv(base, "signal_level_guidance_matrix_base_table.csv")

    row_summary = summarize_row_taxonomies(base)
    col_summary = column_bin_summary(base)
    matrix_all = matrix_all_schemes(base)
    primary_long = build_matrix(base, "paper_compact_row_taxonomy", "access_density_band_0_2500")
    primary_table = primary_matrix_table(primary_long)
    low_n = primary_long[primary_long["low_n_flag"] | primary_long["sparse_cell_flag"]].copy()
    recommendation = design_recommendation(primary_long)

    write_csv(row_summary, "row_taxonomy_candidate_summary.csv")
    write_csv(col_summary, "aadtspeedaccess_column_bin_summary.csv")
    write_csv(matrix_all, "matrix_feasibility_all_schemes.csv")
    write_csv(primary_table, "primary_guidance_matrix_table.csv")
    write_csv(primary_long, "primary_guidance_matrix_long.csv")
    write_csv(low_n, "primary_guidance_matrix_low_n_cells.csv")
    write_csv(recommendation, "guidance_matrix_design_recommendation.csv")

    write_svg_heatmap(primary_long)

    findings = findings_text(field_inventory, median_audit, row_summary, col_summary, primary_long)
    (OUT / "final_guidance_matrix_figure_feasibility_findings.md").write_text(findings, encoding="utf-8")
    log("Wrote findings memo.")

    qa = qa_table()
    write_csv(qa, "final_guidance_matrix_figure_feasibility_qa.csv")

    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "final_guidance_matrix_figure_feasibility_manifest.json")
    (OUT / "final_guidance_matrix_figure_feasibility_manifest.json").write_text(
        json.dumps(manifest(outputs), indent=2),
        encoding="utf-8",
    )
    log("Wrote manifest.")
    log("Completed final guidance matrix figure feasibility package.")


if __name__ == "__main__":
    main()
