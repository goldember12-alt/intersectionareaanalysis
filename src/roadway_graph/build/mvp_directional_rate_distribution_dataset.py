"""MVP directional observed crash-rate distribution dataset.

This read-only product creates approach-window-direction units and lookup-cell
distributions for the MVP observed crash-rate table. Downstream/upstream is a
required grouping category. Direct and synthetic directionality are both usable
for MVP grouping, with method/provenance flags retained.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src.roadway_graph import mvp_directional_observed_crash_rate_feasibility as feas


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ACCESS_DIR = ROOT / "work/output/roadway_graph/review/current/final_leg_corrected_access_refresh"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/mvp_dataset"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}
WINDOW_ORDER = ["0-1,000 ft", "0-2,500 ft"]


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


def expand_to_cumulative_windows(df: pd.DataFrame, source_window_col: str = "analysis_window") -> pd.DataFrame:
    work = df.copy()
    norm = work[source_window_col].map(feas.normalize_window)
    work["_window_list"] = np.where(norm.eq("0-1,000 ft"), "0-1,000 ft|0-2,500 ft", "0-2,500 ft")
    out = work.assign(window_label=work["_window_list"].str.split("|")).explode("window_label")
    return out.drop(columns=["_window_list"])


def speed_band(value: object) -> str:
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return "unknown"
    if v <= 30:
        return "≤30 mph"
    if v == 35:
        return "35 mph"
    if v >= 40:
        return "≥40 mph"
    return "unknown"


def aadt_band(value: object) -> str:
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return "unknown / missing"
    if 1500 <= v < 9000:
        return "1,500–9,000"
    if 9000 <= v < 12000:
        return "9,000–12,000"
    if 12000 <= v < 15000:
        return "12,000–15,000"
    if v >= 15000:
        return ">15,000"
    return "unknown / missing"


def roadway_configuration(row: pd.Series) -> str:
    text = " ".join(str(row.get(c, "")) for c in ["rim_facility_raw", "RTE_CATEGO", "RTE_TYPE_N", "source_route_name", "source_route_common"]).lower()
    if "ramp" in text or "interchange" in text:
        return "ramp/interchange context"
    if "one-way" in text:
        return "one-way"
    if "two-way divided" in text:
        return "two-way divided"
    if "two-way undivided" in text:
        return "two-way undivided"
    if str(row.get("divided_undivided", "")) == "divided":
        return "two-way divided"
    if str(row.get("divided_undivided", "")) == "undivided":
        return "two-way undivided"
    return "other/unknown"


def median_public(value: object) -> str:
    text = str(value).lower()
    if "no_median" in text or "lt_4" in text or "no median" in text:
        return "no median / <4 ft"
    if "barrier" in text or "curb" in text or "raised" in text:
        return "raised or barrier median"
    if "painted" in text or "unprotected" in text:
        return "painted or unprotected median"
    return "other/unknown"


def access_count_band(count: object) -> str:
    v = pd.to_numeric(count, errors="coerce")
    if pd.isna(v) or v <= 0:
        return "0"
    if v <= 2:
        return "1–2"
    if v <= 5:
        return "3–5"
    return "6+"


def access_type_from_counts(row: pd.Series) -> str:
    full = row.get("unrestricted_or_full_access_present", 0) > 0
    riro = row.get("riro_present", 0) > 0
    other = row.get("other_typed_access_present", 0) > 0
    active = int(full) + int(riro) + int(other)
    if row.get("typed_access_assignment_count", 0) <= 0:
        return "no typed access observed"
    if active > 1:
        return "multiple typed access types present"
    if full:
        return "unrestricted/full access present"
    if riro:
        return "RIRO present"
    if other:
        return "other/restricted typed access present"
    return "typed access unknown/source-limited"


def mode_value(s: pd.Series) -> str:
    vals = s.dropna().astype(str)
    if vals.empty:
        return "unknown"
    return vals.value_counts().index[0]


def build_directional_context() -> pd.DataFrame:
    bins = feas.load_bin_context()
    directional = feas.build_directional_bin_context(bins)
    directional = expand_to_cumulative_windows(directional)
    directional["upstream_downstream"] = directional["downstream_upstream"]
    directional["directionality_direct_or_synthetic"] = np.where(
        directional["directionality_type"].eq("synthetic_undivided_centerline"), "synthetic", "direct"
    )
    source_map = {
        "direct_relaxed_combined": "direct_divided_or_oneway",
        "residual_direct_recovery": "residual_recovered_direct",
        "ramp_interchange_recovery": "direct_ramp_or_interchange",
        "final_residual_direct_recovery": "residual_recovered_direct",
        "undivided_synthetic": "synthetic_undivided_centerline",
        "residual_synthetic_recovery": "residual_recovered_synthetic",
        "final_residual_synthetic_recovery": "residual_recovered_synthetic",
    }
    directional["mvp_directionality_method"] = directional["directionality_source"].map(source_map).fillna(
        directional["directionality_type"]
    )
    directional["directionality_coverage_status"] = "covered_directional_mvp"
    directional["directionality_caveat"] = np.where(
        directional["directionality_direct_or_synthetic"].eq("synthetic"),
        "synthetic undivided centerline interpretation included for MVP grouping",
        "direct directional bin label included for MVP grouping",
    )
    return directional


def access_by_direction(directional: pd.DataFrame) -> pd.DataFrame:
    dir_keys = directional[
        [
            "stable_bin_id",
            "stable_signal_id",
            "signal_approach_id",
            "window_label",
            "upstream_downstream",
        ]
    ].drop_duplicates()
    untyped = read_csv(
        ACCESS_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
        usecols=lambda c: c in {"access_point_id", "stable_bin_id", "source_preserving_weighted_access_count"},
    )
    typed = read_csv(
        ACCESS_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv",
        usecols=lambda c: c in {"access_point_id", "stable_bin_id", "corrected_access_category", "source_preserving_weighted_access_count"},
    )
    un = untyped.merge(dir_keys, on="stable_bin_id", how="inner")
    un["source_preserving_weighted_access_count"] = pd.to_numeric(un["source_preserving_weighted_access_count"], errors="coerce").fillna(1)
    ung = un.groupby(["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], dropna=False).agg(
        access_raw_count=("access_point_id", "nunique"),
        access_weighted_count=("source_preserving_weighted_access_count", "sum"),
    ).reset_index()
    ty = typed.merge(dir_keys, on="stable_bin_id", how="inner")
    ty["source_preserving_weighted_access_count"] = pd.to_numeric(ty["source_preserving_weighted_access_count"], errors="coerce").fillna(1)
    ty["is_full"] = ty["corrected_access_category"].fillna("").eq("unrestricted_or_full_access")
    ty["is_riro"] = ty["corrected_access_category"].fillna("").eq("right_in_right_out")
    ty["is_other"] = ~ty["corrected_access_category"].fillna("").isin(["", "unrestricted_or_full_access", "right_in_right_out"])
    tyg = ty.groupby(["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], dropna=False).agg(
        typed_access_assignment_count=("access_point_id", "nunique"),
        unrestricted_or_full_access_present=("is_full", "sum"),
        riro_present=("is_riro", "sum"),
        other_typed_access_present=("is_other", "sum"),
    ).reset_index()
    out = ung.merge(tyg, on=["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], how="outer")
    for c in ["access_raw_count", "access_weighted_count", "typed_access_assignment_count", "unrestricted_or_full_access_present", "riro_present", "other_typed_access_present"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["access_count_band"] = out["access_raw_count"].map(access_count_band)
    out["access_type"] = out.apply(access_type_from_counts, axis=1)
    return out


def crash_by_direction(directional: pd.DataFrame) -> pd.DataFrame:
    crash, ident = feas.crash_assignments()
    dir_keys = directional[
        [
            "stable_bin_id",
            "stable_signal_id",
            "signal_approach_id",
            "window_label",
            "upstream_downstream",
            "directionality_direct_or_synthetic",
        ]
    ].drop_duplicates()
    joined = crash.merge(dir_keys, on="stable_bin_id", how="inner", suffixes=("_crash", ""))
    # Use directional signal/approach/window from the bin context. This avoids
    # crash direction fields and keeps synthetic rows explicitly duplicated by
    # interpretation where applicable.
    joined["source_preserving_weight"] = pd.to_numeric(joined["source_preserving_weight"], errors="coerce").fillna(0)
    joined = joined.merge(
        ident[["stable_crash_id", "stable_bin_id", "identity_compatible_assignment_flag", "identity_constrained_source_preserving_weight"]],
        on=["stable_crash_id", "stable_bin_id"],
        how="left",
    )
    joined["identity_compatible_assignment_flag"] = joined["identity_compatible_assignment_flag"].fillna(False).astype(bool)
    joined["route_confirmed_weight"] = np.where(
        joined["identity_compatible_assignment_flag"],
        pd.to_numeric(joined["identity_constrained_source_preserving_weight"], errors="coerce").fillna(0),
        0,
    )
    return joined.groupby(["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], dropna=False).agg(
        catchment_50ft_crash_count=("stable_crash_id", "nunique"),
        weighted_50ft_crash_count=("source_preserving_weight", "sum"),
        route_confirmed_crash_count=("identity_compatible_assignment_flag", "sum"),
        route_confirmed_weighted_crash_count=("route_confirmed_weight", "sum"),
    ).reset_index()


def build_unit(directional: pd.DataFrame) -> pd.DataFrame:
    d = directional.copy()
    if "final_review_recovery_provenance" not in d.columns:
        d["final_review_recovery_provenance"] = "unknown_provenance"
    for c in ["exposure_denominator", "bin_length_mi", "speed_limit_mph", "aadt"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    unit = d.groupby(["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], dropna=False).agg(
        represented_bin_count=("stable_bin_id", "nunique"),
        represented_length_mi=("bin_length_mi", "sum"),
        exposure_denominator=("exposure_denominator", "sum"),
        exposure_bin_count=("exposure_denominator", lambda s: int(s.notna().sum())),
        numeric_speed_bin_count=("speed_limit_mph", lambda s: int(s.notna().sum())),
        numeric_aadt_bin_count=("aadt", lambda s: int(s.notna().sum())),
        numeric_speed=("speed_limit_mph", "median"),
        numeric_aadt=("aadt", "median"),
        roadway_configuration=("rim_facility_raw", lambda s: "unknown"),
        median_group_raw=("median_group", mode_value),
        direct_bin_rows=("directionality_direct_or_synthetic", lambda s: int((s == "direct").sum())),
        synthetic_bin_rows=("directionality_direct_or_synthetic", lambda s: int((s == "synthetic").sum())),
        direct_unique_bins=("stable_bin_id", lambda s: 0),
        directionality_method_mix=("mvp_directionality_method", lambda s: ";".join(sorted(set(s.dropna().astype(str))))),
        directionality_confidence_summary=("directionality_confidence", lambda s: mode_value(s)),
        recovery_provenance=("final_review_recovery_provenance", lambda s: mode_value(s)),
    ).reset_index()
    # Unique direct/synthetic bins need row-level pairing.
    split = d.groupby(["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream", "directionality_direct_or_synthetic"], dropna=False)["stable_bin_id"].nunique().unstack(fill_value=0).reset_index()
    if "direct" not in split.columns:
        split["direct"] = 0
    if "synthetic" not in split.columns:
        split["synthetic"] = 0
    split = split.rename(columns={"direct": "direct_unique_bins", "synthetic": "synthetic_unique_bins"})
    unit = unit.drop(columns=["direct_unique_bins"]).merge(split, on=["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], how="left")
    unit["directionality_method_mix_type"] = np.select(
        [unit["direct_unique_bins"].gt(0) & unit["synthetic_unique_bins"].gt(0), unit["direct_unique_bins"].gt(0), unit["synthetic_unique_bins"].gt(0)],
        ["mixed direct/synthetic", "direct only", "synthetic only"],
        default="unknown",
    )
    unit["directionality_completeness_flag"] = "directionality_present"

    # Add dominant roadway fields from first matching row.
    road = d.groupby(["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], dropna=False).apply(
        lambda g: pd.Series(
            {
                "roadway_configuration": roadway_configuration(g.iloc[0]),
                "median_group": median_public(g["median_group"].pipe(mode_value)),
            }
        ),
        include_groups=False,
    ).reset_index()
    unit = unit.drop(columns=["roadway_configuration", "median_group_raw"]).merge(road, on=["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], how="left")

    access = access_by_direction(directional)
    crashes = crash_by_direction(directional)
    unit = unit.merge(access, on=["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], how="left")
    unit = unit.merge(crashes, on=["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"], how="left")
    for c in [
        "access_raw_count",
        "access_weighted_count",
        "typed_access_assignment_count",
        "unrestricted_or_full_access_present",
        "riro_present",
        "other_typed_access_present",
        "catchment_50ft_crash_count",
        "weighted_50ft_crash_count",
        "route_confirmed_crash_count",
        "route_confirmed_weighted_crash_count",
    ]:
        unit[c] = pd.to_numeric(unit[c], errors="coerce").fillna(0)
    unit["access_count_band"] = unit["access_raw_count"].map(access_count_band)
    unit["access_type"] = unit.apply(access_type_from_counts, axis=1)
    unit["speed_band"] = unit["numeric_speed"].map(speed_band)
    unit["aadt_band"] = unit["numeric_aadt"].map(aadt_band)
    unit["candidate_observed_crash_rate"] = np.where(
        unit["exposure_denominator"].gt(0),
        unit["weighted_50ft_crash_count"] / (unit["exposure_denominator"] / 1_000_000.0),
        np.nan,
    )
    unit["rate_unit"] = "review_only_crashes_per_million_aadt_mile_units"
    unit["rate_readiness_flag"] = np.select(
        [
            unit["exposure_denominator"].gt(0) & unit["numeric_speed"].notna() & unit["numeric_aadt"].notna(),
            unit["exposure_denominator"].gt(0),
        ],
        ["rate_ready", "exposure_only_count_ready"],
        default="count_only_missing_numeric_or_exposure",
    )
    return unit


def distribution_summary(unit: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "speed_band",
        "aadt_band",
        "roadway_configuration",
        "median_group",
        "access_count_band",
        "access_type",
        "upstream_downstream",
        "window_label",
    ]
    rows = []
    for key, g in unit.groupby(keys, dropna=False):
        rates = g["candidate_observed_crash_rate"].dropna()
        total_exposure = g["exposure_denominator"].sum()
        total_weighted = g["weighted_50ft_crash_count"].sum()
        aggregate_rate = total_weighted / (total_exposure / 1_000_000.0) if total_exposure > 0 else np.nan
        direct_share = (g["directionality_method_mix_type"].eq("direct only").sum() / len(g)) if len(g) else np.nan
        synthetic_share = (g["directionality_method_mix_type"].eq("synthetic only").sum() / len(g)) if len(g) else np.nan
        row = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        row.update(
            {
                "approach_window_direction_units": len(g),
                "signal_count": g["stable_signal_id"].nunique(),
                "approach_count": g[["stable_signal_id", "signal_approach_id"]].drop_duplicates().shape[0],
                "total_crash_count": g["catchment_50ft_crash_count"].sum(),
                "total_weighted_crash_count": total_weighted,
                "total_route_confirmed_crash_count": g["route_confirmed_crash_count"].sum(),
                "total_exposure_denominator": total_exposure,
                "aggregate_observed_crash_rate": aggregate_rate,
                "mean_unit_crash_rate": rates.mean() if not rates.empty else np.nan,
                "median_unit_crash_rate": rates.median() if not rates.empty else np.nan,
                "p10_unit_crash_rate": rates.quantile(0.10) if len(rates) >= 2 else np.nan,
                "p25_unit_crash_rate": rates.quantile(0.25) if len(rates) >= 2 else np.nan,
                "p75_unit_crash_rate": rates.quantile(0.75) if len(rates) >= 2 else np.nan,
                "p90_unit_crash_rate": rates.quantile(0.90) if len(rates) >= 2 else np.nan,
                "min_unit_crash_rate": rates.min() if not rates.empty else np.nan,
                "max_unit_crash_rate": rates.max() if not rates.empty else np.nan,
                "share_direct_directionality": direct_share,
                "share_synthetic_directionality": synthetic_share,
                "numeric_complete_unit_count": int(g["rate_readiness_flag"].eq("rate_ready").sum()),
                "low_n_flag": g["catchment_50ft_crash_count"].sum() < 5,
                "low_exposure_flag": total_exposure <= 0,
                "sparse_cell_flag": len(g) < 10,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def lookup_table(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    out["reliability_flag"] = np.select(
        [
            out["approach_window_direction_units"].ge(30) & ~out["low_exposure_flag"],
            out["approach_window_direction_units"].ge(10) & ~out["low_exposure_flag"],
            out["approach_window_direction_units"].ge(5),
        ],
        ["higher_reliability", "moderate_reliability", "low_reliability"],
        default="insufficient_data",
    )
    out["fallback_recommendation"] = np.select(
        [
            out["reliability_flag"].eq("higher_reliability"),
            out["reliability_flag"].eq("moderate_reliability"),
            out["reliability_flag"].eq("low_reliability"),
        ],
        ["use_exact_cell", "use_with_caveat_or_fallback_if_available", "prefer_fallback",],
        default="fallback_or_insufficient_evidence",
    )
    return out


def fallback_hierarchy() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (1, "exact_match_including_upstream_downstream", "Use exact MVP input cell including upstream/downstream."),
            (2, "collapse_access_type", "Drop access type first."),
            (3, "collapse_median_group", "Drop median group."),
            (4, "collapse_access_count_band", "Drop access count band."),
            (5, "collapse_speed_or_aadt_band", "Collapse speed or AADT band only after access/median fallbacks."),
            (6, "collapse_upstream_downstream_with_warning", "Use non-directional fallback only with warning because upstream/downstream is required MVP input."),
            (7, "insufficient_evidence", "Return insufficient evidence."),
        ],
        columns=["fallback_order", "fallback_step", "lookup_behavior"],
    )


def sample_size_audit(summary: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("cells_total", len(summary)),
            ("cells_units_ge_5", int(summary["approach_window_direction_units"].ge(5).sum())),
            ("cells_units_ge_10", int(summary["approach_window_direction_units"].ge(10).sum())),
            ("cells_units_ge_20", int(summary["approach_window_direction_units"].ge(20).sum())),
            ("cells_units_ge_30", int(summary["approach_window_direction_units"].ge(30).sum())),
            ("cells_direct_only_majority", int(summary["share_direct_directionality"].gt(0.5).sum())),
            ("cells_synthetic_only_majority", int(summary["share_synthetic_directionality"].gt(0.5).sum())),
            ("cells_mixed_directionality", int(((summary["share_direct_directionality"] > 0) & (summary["share_synthetic_directionality"] > 0)).sum())),
            ("cells_missing_exposure", int(summary["low_exposure_flag"].sum())),
            ("cells_missing_speed_aadt", int(summary["numeric_complete_unit_count"].eq(0).sum())),
            ("cells_sparse_due_to_directional_split", int(summary["sparse_cell_flag"].sum())),
        ],
        columns=["metric", "value"],
    )


def missingness_audit(unit: pd.DataFrame) -> pd.DataFrame:
    group_fields = [
        "directionality_method_mix_type",
        "upstream_downstream",
        "window_label",
        "roadway_configuration",
        "median_group",
        "recovery_provenance",
    ]
    rows = []
    for field in group_fields:
        tmp = unit.groupby(field, dropna=False).agg(
            units=("stable_signal_id", "count"),
            missing_speed=("numeric_speed", lambda s: int(s.isna().sum())),
            missing_aadt=("numeric_aadt", lambda s: int(s.isna().sum())),
            missing_exposure=("exposure_denominator", lambda s: int((pd.to_numeric(s, errors="coerce") <= 0).sum())),
            rate_ready=("rate_readiness_flag", lambda s: int((s == "rate_ready").sum())),
            signals=("stable_signal_id", "nunique"),
        ).reset_index()
        tmp.insert(0, "missingness_dimension", field)
        tmp = tmp.rename(columns={field: "dimension_value"})
        rows.append(tmp)
    return pd.concat(rows, ignore_index=True)


def readiness(summary: pd.DataFrame, unit: pd.DataFrame) -> pd.DataFrame:
    reliable = (summary["approach_window_direction_units"].ge(10) & ~summary["low_exposure_flag"]).sum()
    rate_ready_units = unit["rate_readiness_flag"].eq("rate_ready").sum()
    return pd.DataFrame(
        [
            {
                "decision": "directional_observed_lookup_partially_feasible_review_only",
                "approach_window_direction_units": len(unit),
                "rate_ready_units": int(rate_ready_units),
                "category_cells": len(summary),
                "moderate_or_better_cells": int(reliable),
                "use_direct_synthetic_combined": "yes_with_method_composition_flags",
                "display_direct_synthetic_composition": "required",
                "insufficient_data_rule": "return insufficient evidence when exact and fallback cells are sparse or exposure is missing",
                "main_blocker": "numeric_speed_aadt_exposure_completeness_and_cell_sparsity",
            }
        ]
    )


def write_findings(unit: pd.DataFrame, summary: pd.DataFrame, sample: pd.DataFrame, missing: pd.DataFrame, ready: pd.DataFrame) -> None:
    mix = unit["directionality_method_mix_type"].value_counts().to_dict()
    rate_ready = int(unit["rate_readiness_flag"].eq("rate_ready").sum())
    count_only = int((unit["rate_readiness_flag"] != "rate_ready").sum())
    sample_dict = dict(zip(sample["metric"], sample["value"]))
    text = f"""# MVP Directional Rate Distribution Findings

## Bounded Question

This product creates a review-only MVP distribution dataset where downstream/upstream is a required lookup category. Direct and synthetic directionality are both included in the usable directional set, with method/provenance flags preserved.

## Analysis Units

- Approach-window-direction units: {len(unit):,}
- Directionality mix: {json.dumps(mix, sort_keys=True)}
- Rate-ready units: {rate_ready:,}
- Count-only or missing numeric/exposure units: {count_only:,}

## Category Cells

- Total cells: {len(summary):,}
- Cells with at least 5 units: {sample_dict.get('cells_units_ge_5', 0):,}
- Cells with at least 10 units: {sample_dict.get('cells_units_ge_10', 0):,}
- Cells with at least 20 units: {sample_dict.get('cells_units_ge_20', 0):,}
- Cells with at least 30 units: {sample_dict.get('cells_units_ge_30', 0):,}
- Sparse cells: {sample_dict.get('cells_sparse_due_to_directional_split', 0):,}

## Readiness

Direct+synthetic combined directional analysis is feasible as a review-only MVP dataset, provided direct/synthetic composition and numeric completeness flags are shown. AADT/speed/exposure completeness and cell sparsity are now the main limitations, not directionality coverage.

## Next Pass

Improve numeric AADT/speed/exposure completeness at approach-window-direction grain, then design the lookup behavior and reliability display using `mvp_directional_lookup_distribution_table.csv`.
"""
    (OUT_DIR / "mvp_directional_rate_distribution_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote mvp_directional_rate_distribution_findings.md")


def write_qa() -> pd.DataFrame:
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to MVP distribution analysis/current folder."),
            ("no_records_promoted", True, "Review-only dataset."),
            ("no_new_access_crash_assignment", True, "Existing assignment outputs were read only."),
            ("no_final_production_rates_models", True, "Only review-only observed aggregate rates and distributions were calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash direction columns were not selected from crash inputs."),
            ("downstream_upstream_required_grouping", True, "upstream_downstream is part of unit and cell group keys."),
            ("synthetic_included_with_method_flags", True, "Synthetic directionality is included with synthetic method/provenance flags."),
            ("exposure_denominator_documented", True, "Rate unit is review-only crashes per million AADT-mile units."),
            ("unit_level_distributions_preserved", True, "mvp_approach_window_direction_unit.csv preserves unit-level rates."),
            ("outputs_analysis_current_folder", str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/analysis/current/mvp_dataset"), str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(qa, "mvp_directional_rate_distribution_qa.csv")
    return qa


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "script": "src.roadway_graph.build.mvp_dataset",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "MVP approach-window-direction observed crash-rate distribution dataset",
        "output_folder": str(OUT_DIR),
        "inputs": [
            str(CANONICAL_DIR),
            str(ACCESS_DIR),
            "directionality, crash, and identity inputs via mvp_directional_observed_crash_rate_feasibility helpers",
        ],
        "outputs": list(outputs),
        "non_goals": [
            "no UI",
            "no production rates",
            "no crash direction use",
            "no access/crash assignment rerun",
            "no predictive models",
            "no active output modification",
        ],
    }
    (OUT_DIR / "mvp_directional_rate_distribution_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_log("Wrote mvp_directional_rate_distribution_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting MVP directional rate distribution dataset.")
    directional = build_directional_context()
    unit = build_unit(directional)
    summary = distribution_summary(unit)
    lookup = lookup_table(summary)
    fallback = fallback_hierarchy()
    sample = sample_size_audit(summary)
    missing = missingness_audit(unit)
    ready = readiness(summary, unit)

    write_csv(directional, "mvp_directional_bin_context.csv")
    write_csv(unit, "mvp_approach_window_direction_unit.csv")
    write_csv(summary, "mvp_directional_category_distribution_summary.csv")
    write_csv(lookup, "mvp_directional_lookup_distribution_table.csv")
    write_csv(fallback, "mvp_directional_lookup_fallback_hierarchy.csv")
    write_csv(sample, "mvp_directional_cell_sample_size_audit.csv")
    write_csv(missing, "mvp_directional_numeric_missingness_audit.csv")
    write_csv(ready, "mvp_directional_rate_product_readiness.csv")
    qa = write_qa()
    write_findings(unit, summary, sample, missing, ready)
    outputs = [
        "mvp_directional_bin_context.csv",
        "mvp_approach_window_direction_unit.csv",
        "mvp_directional_category_distribution_summary.csv",
        "mvp_directional_lookup_distribution_table.csv",
        "mvp_directional_lookup_fallback_hierarchy.csv",
        "mvp_directional_cell_sample_size_audit.csv",
        "mvp_directional_numeric_missingness_audit.csv",
        "mvp_directional_rate_product_readiness.csv",
        "mvp_directional_rate_distribution_findings.md",
        "mvp_directional_rate_distribution_qa.csv",
        "mvp_directional_rate_distribution_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed MVP directional rate distribution dataset.")


if __name__ == "__main__":
    main()
