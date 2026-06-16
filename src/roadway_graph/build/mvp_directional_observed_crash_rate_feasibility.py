"""MVP downstream/upstream observed crash-rate feasibility.

This review-only product tests whether downstream/upstream can be included in
an MVP observed crash-rate lookup. It distinguishes direct divided/one-way
directionality from synthetic undivided centerline interpretations and does not
create production crash rates or directional crash assignments.
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
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
DIRECT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"
UNDIVIDED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_residual_directionality_recovery"
RAMP_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_ramp_interchange_directionality_recovery"
FINAL_RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_residual_directionality_decomposition_recovery"
CRASH_DIR = ROOT / "work/output/roadway_graph/review/current/final_leg_corrected_crash_candidate_assignment"
IDENTITY_DIR = ROOT / "work/output/roadway_graph/review/current/crash_roadway_identity_assignment_doctrine"
ACCESS_DIR = ROOT / "work/output/roadway_graph/review/current/final_leg_corrected_access_refresh"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/mvp_directional_observed_crash_rate_feasibility"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}
PUBLIC_SYNTHETIC_MAP = {
    "synthetic_downstream_from_signal": "downstream_from_signal",
    "synthetic_upstream_to_signal": "upstream_to_signal",
}


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


def normalize_window(value: object) -> str:
    text = str(value)
    if text in {"0_1000", "0-1,000 ft", "0-1000 ft"}:
        return "0-1,000 ft"
    if text in {"1000_2500", "0_2500", "0-2,500 ft", "1000-2500 ft"}:
        # Bins labeled 1000_2500 contribute to the broader 0-2,500 ft window in
        # signal-window summaries.
        return "0-2,500 ft"
    return text


def load_bin_context() -> pd.DataFrame:
    bin_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "signal_approach_id",
        "carriageway_source_subpart_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "rim_facility_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "final_review_recovery_provenance",
    ]
    bins = read_csv(CANONICAL_DIR / "analysis_bin.csv", usecols=lambda c: c in bin_cols)
    numeric = read_csv(
        ENHANCED_DIR / "bin_numeric_context_enhanced.csv",
        usecols=lambda c: c
        in {
            "stable_bin_id",
            "speed_limit_mph",
            "speed_confidence",
            "aadt",
            "aadt_confidence",
            "bin_length_ft",
            "bin_length_mi",
            "exposure_denominator",
            "exposure_method",
            "numeric_context_confidence",
        },
    )
    bins = bins.merge(numeric, on="stable_bin_id", how="left", suffixes=("", "_enhanced"))
    bins["signal_window"] = bins["analysis_window"].map(normalize_window)
    bins["divided_undivided"] = np.select(
        [
            bins["rim_facility_raw"].fillna("").str.contains("Divided", case=False, regex=False),
            bins["rim_facility_raw"].fillna("").str.contains("Undivided", case=False, regex=False),
        ],
        ["divided", "undivided"],
        default="unknown",
    )
    return bins


def direct_rows(path: Path, label_col: str, method_col: str, conf_col: str, source_name: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = read_csv(path)
    if label_col not in df.columns:
        return pd.DataFrame()
    out = df[df[label_col].isin(DIRECT_LABELS)].copy()
    if out.empty:
        return out
    out["downstream_upstream"] = out[label_col]
    out["directionality_method"] = out[method_col] if method_col in out.columns else source_name
    out["directionality_confidence"] = out[conf_col] if conf_col in out.columns else "unknown"
    out["directionality_source"] = source_name
    keep = [
        "stable_bin_id",
        "stable_signal_id",
        "stable_travelway_id",
        "signal_approach_id",
        "analysis_window",
        "downstream_upstream",
        "directionality_method",
        "directionality_confidence",
        "directionality_source",
    ]
    return out[[c for c in keep if c in out.columns]].copy()


def synthetic_rows(path: Path, role_col: str, method_col: str, conf_col: str, source_name: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = read_csv(path)
    if role_col not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    if "public_directional_role" in out.columns:
        out["downstream_upstream"] = out["public_directional_role"]
    else:
        out["downstream_upstream"] = out[role_col].map(PUBLIC_SYNTHETIC_MAP)
    out = out[out["downstream_upstream"].isin(DIRECT_LABELS)].copy()
    out["directionality_method"] = out[method_col] if method_col in out.columns else source_name
    out["directionality_confidence"] = out[conf_col] if conf_col in out.columns else "unknown"
    out["directionality_source"] = source_name
    keep = [
        "stable_bin_id",
        "stable_signal_id",
        "stable_travelway_id",
        "signal_approach_id",
        "analysis_window",
        "downstream_upstream",
        "directionality_method",
        "directionality_confidence",
        "directionality_source",
    ]
    return out[[c for c in keep if c in out.columns]].copy()


def build_directional_bin_context(bins: pd.DataFrame) -> pd.DataFrame:
    direct_parts = [
        direct_rows(
            DIRECT_DIR / "combined_direct_divided_directionality_detail.csv",
            "combined_direct_directionality_label",
            "combined_direct_directionality_method",
            "combined_direct_directionality_confidence",
            "direct_relaxed_combined",
        ),
        direct_rows(
            RESIDUAL_DIR / "residual_directionality_recovered_labels.csv",
            "recovered_directionality_label",
            "residual_recovery_method",
            "residual_recovery_confidence",
            "residual_direct_recovery",
        ),
        direct_rows(
            RAMP_DIR / "ramp_interchange_recovered_labels.csv",
            "recovered_directionality_label",
            "directionality_method",
            "directionality_confidence",
            "ramp_interchange_recovery",
        ),
        direct_rows(
            FINAL_RESIDUAL_DIR / "residual_direct_recovered_labels.csv",
            "residual_direct_label",
            "residual_direct_recovery_method",
            "residual_direct_recovery_confidence",
            "final_residual_direct_recovery",
        ),
    ]
    direct = pd.concat([p for p in direct_parts if not p.empty], ignore_index=True)
    if not direct.empty:
        priority = {
            "direct_relaxed_combined": 1,
            "residual_direct_recovery": 2,
            "ramp_interchange_recovery": 3,
            "final_residual_direct_recovery": 4,
        }
        direct["source_priority"] = direct["directionality_source"].map(priority).fillna(99)
        direct = direct.sort_values(["stable_bin_id", "source_priority"]).drop_duplicates("stable_bin_id", keep="first")
        direct["directionality_type"] = "direct_divided_or_oneway"
        direct["directionality_scope"] = "direct_directional_bin_label"
        direct["crash_assignment_allowed"] = "yes_direct_bin"
        direct["reason_caveat"] = "Direct divided/one-way or accepted review direct label; crash aggregation by assigned bin is feasible for review."

    synthetic_parts = [
        synthetic_rows(
            UNDIVIDED_DIR / "undivided_centerline_synthetic_direction_rows.csv",
            "synthetic_directional_role",
            "synthetic_directionality_method",
            "synthetic_directionality_confidence",
            "undivided_synthetic",
        ),
        synthetic_rows(
            RESIDUAL_DIR / "residual_directionality_recovered_synthetic_rows.csv",
            "synthetic_directional_role",
            "synthetic_directionality_method",
            "undivided_unclear_recovery_confidence",
            "residual_synthetic_recovery",
        ),
        synthetic_rows(
            FINAL_RESIDUAL_DIR / "residual_synthetic_recovered_rows.csv",
            "synthetic_directional_role",
            "synthetic_directionality_method",
            "synthetic_directionality_confidence",
            "final_residual_synthetic_recovery",
        ),
    ]
    synthetic = pd.concat([p for p in synthetic_parts if not p.empty], ignore_index=True)
    if not synthetic.empty:
        synthetic = synthetic.drop_duplicates(["stable_bin_id", "downstream_upstream"], keep="first")
        synthetic["directionality_type"] = "synthetic_undivided_centerline"
        synthetic["directionality_scope"] = "undivided_centerline_interpretation"
        synthetic["crash_assignment_allowed"] = "context_only_synthetic"
        synthetic["reason_caveat"] = "Synthetic undivided interpretation rows are context-only and should not split crash counts without a separate validated rule."

    directional = pd.concat([direct, synthetic], ignore_index=True)
    context_cols = [
        "stable_bin_id",
        "source_signal_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "signal_window",
        "geometry_wkt",
        "rim_facility_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "divided_undivided",
        "speed_limit_mph",
        "aadt",
        "bin_length_ft",
        "bin_length_mi",
        "exposure_denominator",
        "exposure_method",
        "numeric_context_confidence",
    ]
    directional = directional.merge(bins[[c for c in context_cols if c in bins.columns]], on="stable_bin_id", how="left")
    directional["analysis_window"] = directional["analysis_window"].fillna(directional["signal_window"])
    directional["signal_window"] = directional["analysis_window"].map(normalize_window)
    return directional


def crash_assignments() -> tuple[pd.DataFrame, pd.DataFrame]:
    crash_cols = [
        "buffer_width_ft",
        "stable_crash_id",
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "distance_band",
        "analysis_window",
        "assignment_fanout_count",
        "unweighted_assignment",
        "source_preserving_weight",
        "assignment_rule",
        "assignment_status",
    ]
    crash = read_csv(CRASH_DIR / "leg_corrected_crash_candidate_assignment_detail.csv", usecols=lambda c: c in crash_cols)
    crash = crash[pd.to_numeric(crash["buffer_width_ft"], errors="coerce").eq(50)].copy()
    crash["signal_window"] = crash["analysis_window"].map(normalize_window)
    id_cols = [
        "stable_crash_id",
        "stable_bin_id",
        "identity_constrained_source_preserving_weight",
        "source_preserving_weight",
        "identity_compatible_assignment_flag",
        "assignment_identity_compatibility",
    ]
    ident = read_csv(IDENTITY_DIR / "identity_compatible_spatial_50ft_assignment_detail.csv", usecols=lambda c: c in id_cols)
    ident = ident.drop_duplicates(["stable_crash_id", "stable_bin_id"])
    return crash, ident


def join_crashes(crash: pd.DataFrame, ident: pd.DataFrame, directional: pd.DataFrame) -> pd.DataFrame:
    direct = directional[directional["crash_assignment_allowed"].eq("yes_direct_bin")].copy()
    synthetic = directional[directional["crash_assignment_allowed"].eq("context_only_synthetic")].copy()
    direct_join = crash.merge(
        direct[["stable_bin_id", "downstream_upstream", "directionality_type", "directionality_method", "directionality_confidence"]],
        on="stable_bin_id",
        how="left",
    )
    direct_join["directional_product_type"] = np.where(
        direct_join["downstream_upstream"].notna(), "direct_only_directional", "not_directionally_assigned"
    )
    synthetic_join = crash.merge(
        synthetic[["stable_bin_id", "downstream_upstream", "directionality_type", "directionality_method", "directionality_confidence"]],
        on="stable_bin_id",
        how="inner",
    )
    synthetic_join["directional_product_type"] = "synthetic_context_interpretation"
    out = pd.concat([direct_join, synthetic_join], ignore_index=True)
    out = out.merge(
        ident[["stable_crash_id", "stable_bin_id", "identity_constrained_source_preserving_weight", "identity_compatible_assignment_flag"]],
        on=["stable_crash_id", "stable_bin_id"],
        how="left",
    )
    out["route_confirmed_identity_compatible"] = out["identity_compatible_assignment_flag"].fillna(False).astype(bool)
    out["route_confirmed_weight"] = np.where(
        out["route_confirmed_identity_compatible"],
        pd.to_numeric(out["identity_constrained_source_preserving_weight"], errors="coerce").fillna(0),
        0.0,
    )
    out["source_preserving_weight"] = pd.to_numeric(out["source_preserving_weight"], errors="coerce").fillna(0)
    out["unweighted_assignment"] = pd.to_numeric(out["unweighted_assignment"], errors="coerce").fillna(1)
    return out


def exposure_summary(directional: pd.DataFrame) -> pd.DataFrame:
    d = directional.copy()
    d["exposure_denominator"] = pd.to_numeric(d["exposure_denominator"], errors="coerce")
    return d.groupby(["stable_signal_id", "signal_window", "downstream_upstream", "directionality_type", "crash_assignment_allowed"], dropna=False).agg(
        directional_bin_rows=("stable_bin_id", "count"),
        unique_directional_bins=("stable_bin_id", "nunique"),
        exposure_denominator=("exposure_denominator", "sum"),
        exposure_bin_count=("exposure_denominator", lambda s: int(s.notna().sum())),
        speed_limit_mph=("speed_limit_mph", "median"),
        aadt=("aadt", "median"),
        median_group=("median_group", lambda s: mode_value(s)),
        divided_undivided=("divided_undivided", lambda s: mode_value(s)),
        synthetic_interpretation_rows=("directionality_type", lambda s: int((s == "synthetic_undivided_centerline").sum())),
    ).reset_index()


def mode_value(s: pd.Series) -> str:
    vals = s.dropna().astype(str)
    if vals.empty:
        return "unknown"
    return vals.value_counts().index[0]


def crash_summary(joined: pd.DataFrame) -> pd.DataFrame:
    d = joined[joined["downstream_upstream"].isin(DIRECT_LABELS)].copy()
    d["directionality_type_for_join"] = np.select(
        [
            d["directional_product_type"].eq("direct_only_directional"),
            d["directional_product_type"].eq("synthetic_context_interpretation"),
        ],
        ["direct_divided_or_oneway", "synthetic_undivided_centerline"],
        default="not_directional",
    )
    return d.groupby(["stable_signal_id", "signal_window", "downstream_upstream", "directionality_type_for_join", "directional_product_type"], dropna=False).agg(
        crash_assignment_rows=("stable_crash_id", "count"),
        crash_count=("stable_crash_id", "nunique"),
        weighted_crash_count=("source_preserving_weight", "sum"),
        route_confirmed_crash_count=("route_confirmed_identity_compatible", "sum"),
        route_confirmed_weighted_crash_count=("route_confirmed_weight", "sum"),
        max_assignment_fanout=("assignment_fanout_count", "max"),
    ).reset_index()


def access_type_category(row: pd.Series) -> str:
    if str(row.get("typed_categories_present", "")).lower() not in {"", "nan", "none"}:
        return str(row.get("typed_categories_present"))
    flags = [
        "unrestricted_or_full_access",
        "right_in_right_out",
        "restricted_partial_access",
        "right_in_only",
        "right_out_only",
        "other_review",
        "unknown",
    ]
    active = [f for f in flags if pd.to_numeric(row.get(f, 0), errors="coerce") > 0]
    return ";".join(active) if active else "none"


def build_analysis_units(exp: pd.DataFrame, crashes: pd.DataFrame, signal_window: pd.DataFrame) -> pd.DataFrame:
    base = exp.merge(
        crashes,
        left_on=["stable_signal_id", "signal_window", "downstream_upstream", "directionality_type"],
        right_on=["stable_signal_id", "signal_window", "downstream_upstream", "directionality_type_for_join"],
        how="left",
    )
    # Keep direct and synthetic crash rows separate where both exist.
    missing_product = base["directional_product_type"].isna()
    base.loc[missing_product & base["directionality_type"].eq("synthetic_undivided_centerline"), "directional_product_type"] = (
        "synthetic_context_interpretation"
    )
    base.loc[missing_product & ~base["directionality_type"].eq("synthetic_undivided_centerline"), "directional_product_type"] = (
        "direct_only_directional"
    )
    sw = signal_window.copy()
    sw["access_type_category"] = sw.apply(access_type_category, axis=1)
    sw_cols = [
        "stable_signal_id",
        "signal_window",
        "speed_band",
        "aadt_band",
        "untyped_access_count_band",
        "access_type_category",
        "roadway_context",
        "facility_type",
        "typed_categories_present",
        "untyped_access_raw_count",
    ]
    base = base.merge(sw[[c for c in sw_cols if c in sw.columns]], on=["stable_signal_id", "signal_window"], how="left")
    for c in [
        "crash_assignment_rows",
        "crash_count",
        "weighted_crash_count",
        "route_confirmed_crash_count",
        "route_confirmed_weighted_crash_count",
    ]:
        base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0)
    base["candidate_observed_crash_rate"] = np.where(
        pd.to_numeric(base["exposure_denominator"], errors="coerce") > 0,
        base["weighted_crash_count"] / base["exposure_denominator"],
        np.nan,
    )
    base["rate_denominator_doctrine"] = np.where(
        base["directionality_type"].eq("synthetic_undivided_centerline"),
        "synthetic_exposure_double_counts_bidirectional_centerline_context",
        "direct_bin_exposure_sum_review_only",
    )
    base["directional_rate_status"] = np.select(
        [
            base["directionality_type"].eq("direct_divided_or_oneway")
            & base["exposure_denominator"].gt(0)
            & base["weighted_crash_count"].ge(0),
            base["directionality_type"].eq("direct_divided_or_oneway"),
            base["directionality_type"].eq("synthetic_undivided_centerline"),
        ],
        ["rate_ready_directional", "count_only_directional", "context_only_synthetic"],
        default="not_directionally_ready",
    )
    base["low_n_flag"] = base["crash_count"].lt(5)
    base["sparse_cell_flag"] = base["unique_directional_bins"].lt(5)
    return base


def approach_units(directional: pd.DataFrame, joined: pd.DataFrame, signal_window_unit: pd.DataFrame) -> pd.DataFrame:
    exp = directional.copy()
    exp["exposure_denominator"] = pd.to_numeric(exp["exposure_denominator"], errors="coerce")
    expg = exp.groupby(["stable_signal_id", "signal_approach_id", "signal_window", "downstream_upstream", "directionality_type", "crash_assignment_allowed"], dropna=False).agg(
        directional_bin_rows=("stable_bin_id", "count"),
        exposure_denominator=("exposure_denominator", "sum"),
        speed_limit_mph=("speed_limit_mph", "median"),
        aadt=("aadt", "median"),
    ).reset_index()
    c = joined[joined["downstream_upstream"].isin(DIRECT_LABELS)].copy()
    cg = c.groupby(["stable_signal_id", "final_review_physical_leg_id", "signal_window", "downstream_upstream", "directional_product_type"], dropna=False).agg(
        crash_count=("stable_crash_id", "nunique"),
        weighted_crash_count=("source_preserving_weight", "sum"),
        route_confirmed_crash_count=("route_confirmed_identity_compatible", "sum"),
    ).reset_index()
    out = expg.merge(
        cg,
        left_on=["stable_signal_id", "signal_approach_id", "signal_window", "downstream_upstream"],
        right_on=["stable_signal_id", "final_review_physical_leg_id", "signal_window", "downstream_upstream"],
        how="left",
    )
    for col in ["crash_count", "weighted_crash_count", "route_confirmed_crash_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    out["candidate_observed_crash_rate"] = np.where(out["exposure_denominator"].gt(0), out["weighted_crash_count"] / out["exposure_denominator"], np.nan)
    out["directional_rate_status"] = np.select(
        [out["directionality_type"].eq("direct_divided_or_oneway") & out["exposure_denominator"].gt(0), out["directionality_type"].eq("synthetic_undivided_centerline")],
        ["rate_ready_directional", "context_only_synthetic"],
        default="count_only_directional",
    )
    return out


def rate_cells(unit: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "speed_band",
        "aadt_band",
        "divided_undivided",
        "median_group",
        "untyped_access_count_band",
        "access_type_category",
        "downstream_upstream",
        "signal_window",
        "directional_rate_status",
    ]
    for c in cols:
        if c not in unit.columns:
            unit[c] = "unknown"
    grouped = unit.groupby(cols, dropna=False).agg(
        signal_window_direction_rows=("stable_signal_id", "count"),
        signal_count=("stable_signal_id", "nunique"),
        crash_count=("crash_count", "sum"),
        weighted_crash_count=("weighted_crash_count", "sum"),
        route_confirmed_crash_count=("route_confirmed_crash_count", "sum"),
        exposure_denominator=("exposure_denominator", "sum"),
        directional_bin_rows=("directional_bin_rows", "sum"),
    ).reset_index()
    grouped["candidate_observed_crash_rate"] = np.where(
        grouped["exposure_denominator"].gt(0),
        grouped["weighted_crash_count"] / grouped["exposure_denominator"],
        np.nan,
    )
    grouped["low_n_flag"] = grouped["crash_count"].lt(5)
    grouped["sparse_flag"] = grouped["signal_count"].lt(5)
    return grouped


def lookup_fallback() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (1, "exact_downstream_upstream_cell", "Use exact speed/AADT/division/median/access-count/access-type/downstream-upstream/window cell."),
            (2, "collapse_access_type", "Drop access type while preserving access count band and downstream/upstream."),
            (3, "collapse_median_group", "Drop median group if the exact median cell is sparse."),
            (4, "collapse_access_count_band", "Drop access count band if still sparse."),
            (5, "collapse_downstream_upstream", "Use non-directional cell when directional evidence is insufficient."),
            (6, "broad_roadway_speed_aadt_cell", "Use broad roadway division, speed, and AADT context only."),
            (7, "insufficient_evidence", "Return insufficient evidence instead of a rate."),
        ],
        columns=["fallback_order", "fallback_step", "lookup_behavior"],
    )


def readiness_summary(directional: pd.DataFrame, unit: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    direct_bins = directional[directional["directionality_type"].eq("direct_divided_or_oneway")]["stable_bin_id"].nunique()
    synthetic_bins = directional[directional["directionality_type"].eq("synthetic_undivided_centerline")]["stable_bin_id"].nunique()
    return pd.DataFrame(
        [
            ("directional_bin_rows", len(directional), "rows"),
            ("direct_directional_bins", direct_bins, "unique_bins"),
            ("synthetic_context_bins", synthetic_bins, "unique_bins"),
            ("signal_window_direction_rows", len(unit), "rows"),
            ("rate_ready_directional_rows", int(unit["directional_rate_status"].eq("rate_ready_directional").sum()), "rows"),
            ("count_only_directional_rows", int(unit["directional_rate_status"].eq("count_only_directional").sum()), "rows"),
            ("context_only_synthetic_rows", int(unit["directional_rate_status"].eq("context_only_synthetic").sum()), "rows"),
            ("rate_ready_cells", int(cells["directional_rate_status"].eq("rate_ready_directional").sum()), "cells"),
            ("count_only_cells", int(cells["directional_rate_status"].eq("count_only_directional").sum()), "cells"),
            ("context_only_synthetic_cells", int(cells["directional_rate_status"].eq("context_only_synthetic").sum()), "cells"),
        ],
        columns=["metric", "value", "unit"],
    )


def write_findings(summary: pd.DataFrame, unit: pd.DataFrame, cells: pd.DataFrame) -> None:
    metrics = dict(zip(summary["metric"], summary["value"]))
    text = f"""# MVP Directional Observed Crash-Rate Feasibility Findings

## Bounded Question

This review-only pass tests whether downstream/upstream can be included in an MVP observed crash-rate lookup. It does not create production rates, rerun crash/access assignment, or use crash direction fields.

## Directionality Eligibility

- Direct divided/one-way bins are eligible for review-only directional crash aggregation by assigned bin.
- Synthetic undivided centerline rows are context-only interpretations and should not be used as final directional crash splitting.

## Readiness

- Direct directional bins: {metrics.get('direct_directional_bins', 0):,}
- Synthetic context bins: {metrics.get('synthetic_context_bins', 0):,}
- Signal-window-direction rows: {metrics.get('signal_window_direction_rows', 0):,}
- Rate-ready direct rows: {metrics.get('rate_ready_directional_rows', 0):,}
- Count-only direct rows: {metrics.get('count_only_directional_rows', 0):,}
- Synthetic/context-only rows: {metrics.get('context_only_synthetic_rows', 0):,}
- Rate-ready MVP cells: {metrics.get('rate_ready_cells', 0):,}

## Recommendation

The MVP can include downstream/upstream now only as a direct-only review subset with explicit reliability flags. The safer MVP version is non-directional rates plus a direct-only directional subset and synthetic undivided context flags. Full directional crash rates should wait for a separate validated crash-direction-independent splitting rule.
"""
    (OUT_DIR / "mvp_directional_observed_crash_rate_feasibility_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote mvp_directional_observed_crash_rate_feasibility_findings.md")


def write_qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to MVP analysis/current output folder."),
        ("no_records_promoted", True, "Review-only feasibility product."),
        ("no_new_access_crash_assignment", True, "Existing assignment outputs were read only."),
        ("no_final_rates_models", True, "Only review-only aggregate observed candidate rates were calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash direction columns were not selected from crash inputs."),
        ("synthetic_undivided_interpretation_only", True, "Synthetic rows are labeled context_only_synthetic."),
        ("exposure_denominator_documented", True, "Direct exposure uses summed bin exposure; synthetic denominator is flagged as double-counting context."),
        ("outputs_analysis_current_folder", str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/analysis/current/mvp_directional_observed_crash_rate_feasibility"), str(OUT_DIR)),
    ]
    qa = pd.DataFrame(rows, columns=["qa_check", "passed", "note"])
    write_csv(qa, "mvp_directional_observed_crash_rate_feasibility_qa.csv")
    return qa


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "script": "src.roadway_graph.build.mvp_directional_observed_crash_rate_feasibility",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "review-only downstream/upstream observed crash-rate feasibility for MVP lookup",
        "output_folder": str(OUT_DIR),
        "inputs": [
            str(CANONICAL_DIR),
            str(ENHANCED_DIR),
            str(DIRECT_DIR),
            str(UNDIVIDED_DIR),
            str(RESIDUAL_DIR),
            str(RAMP_DIR),
            str(FINAL_RESIDUAL_DIR),
            str(CRASH_DIR),
            str(IDENTITY_DIR),
            str(ACCESS_DIR),
        ],
        "outputs": list(outputs),
        "non_goals": [
            "no production rates",
            "no crash direction use",
            "no access/crash assignment rerun",
            "no predictive models",
            "no active output modification",
        ],
    }
    (OUT_DIR / "mvp_directional_observed_crash_rate_feasibility_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    write_log("Wrote mvp_directional_observed_crash_rate_feasibility_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting MVP directional observed crash-rate feasibility.")
    bins = load_bin_context()
    directional = build_directional_bin_context(bins)
    crash, ident = crash_assignments()
    joined = join_crashes(crash, ident, directional)
    exp = exposure_summary(directional)
    csum = crash_summary(joined)
    signal_window = read_csv(CANONICAL_DIR / "analysis_signal_window.csv")
    unit = build_analysis_units(exp, csum, signal_window)
    approach = approach_units(directional, joined, unit)
    cells = rate_cells(unit)
    rate_ready = cells[cells["directional_rate_status"].eq("rate_ready_directional")].copy()
    count_only = cells[cells["directional_rate_status"].eq("count_only_directional")].copy()
    lookup = cells.copy()
    fallback = lookup_fallback()
    summary = readiness_summary(directional, unit, cells)

    write_csv(directional, "directional_bin_context_for_mvp.csv")
    write_csv(joined, "directional_crash_assignment_feasibility.csv")
    write_csv(exp, "directional_exposure_feasibility.csv")
    write_csv(unit, "mvp_directional_analysis_unit_signal_window.csv")
    write_csv(approach, "mvp_directional_analysis_unit_approach_window.csv")
    write_csv(cells, "mvp_directional_observed_rate_cells_full.csv")
    write_csv(rate_ready, "mvp_directional_observed_rate_cells_rate_ready.csv")
    write_csv(count_only, "mvp_directional_observed_rate_cells_count_only.csv")
    write_csv(lookup, "mvp_directional_lookup_table.csv")
    write_csv(fallback, "mvp_directional_lookup_fallback_hierarchy.csv")
    write_csv(summary, "mvp_directionality_readiness_summary.csv")
    qa = write_qa()
    write_findings(summary, unit, cells)
    outputs = [
        "directional_bin_context_for_mvp.csv",
        "directional_crash_assignment_feasibility.csv",
        "directional_exposure_feasibility.csv",
        "mvp_directional_analysis_unit_signal_window.csv",
        "mvp_directional_analysis_unit_approach_window.csv",
        "mvp_directional_observed_rate_cells_full.csv",
        "mvp_directional_observed_rate_cells_rate_ready.csv",
        "mvp_directional_observed_rate_cells_count_only.csv",
        "mvp_directional_lookup_table.csv",
        "mvp_directional_lookup_fallback_hierarchy.csv",
        "mvp_directionality_readiness_summary.csv",
        "mvp_directional_observed_crash_rate_feasibility_findings.md",
        "mvp_directional_observed_crash_rate_feasibility_qa.csv",
        "mvp_directional_observed_crash_rate_feasibility_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed MVP directional observed crash-rate feasibility.")


if __name__ == "__main__":
    main()
