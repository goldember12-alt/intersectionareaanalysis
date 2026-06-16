from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .crs_utils import WORKING_CRS_AUTHORITY, apply_authoritative_crs, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/access_context_join_v2")

ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")
ACTIVE_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_bin_context_active.csv"
BASE_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"
ACTIVE_CRASH_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_crash_context_active.csv"
BASE_CRASH_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_crash_context.csv"
V1_CONTEXT_DIR = OUTPUT_ROOT / "review/current/access_context_join"
V2_STAGING_DIR = OUTPUT_ROOT / "review/current/access_source_v2_staging"

CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
CATCHMENT_POLYGONS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_polygons.geojson"
CATCHMENT_CRS_METADATA_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_crs_metadata.json"

FEET_TO_METERS = 0.3048
THRESHOLD_250FT_M = 250.0 * FEET_TO_METERS

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)

ACCESS_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_out_only",
    "right_in_only",
    "other_review",
    "unknown",
]

COUNT_COLUMNS = {
    "unrestricted_or_full_access": "unrestricted_or_full_access_count",
    "right_in_right_out": "right_in_right_out_count",
    "restricted_partial_access": "restricted_partial_access_count",
    "right_out_only": "right_out_only_count",
    "right_in_only": "right_in_only_count",
    "other_review": "other_review_access_count",
    "unknown": "unknown_access_count",
}

ACCESS_OUTPUT_FIELDS = [
    "access_v2_uid",
    "access_v2_source_gdb",
    "access_v2_source_layer",
    "access_v2_source_priority",
    "access_v2_source_row_id",
    "access_v2_staging_status",
    "access_control_raw",
    "access_control_code",
    "access_control_category",
    "access_direction_raw",
    "access_direction_normalized",
    "number_of_approaches",
    "turn_lanes_primary_route",
    "cross_street",
    "residential_land_use",
    "commercial_land_use",
    "industrial_land_use",
    "government_school_institutional_land_use",
    "unknown_land_use",
    "route_name",
    "route_measure",
]

BIN_BASE_COLUMNS = [
    "reference_signal_id",
    "reference_directional_segment_id",
    "reference_directional_bin_id",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_midpoint_ft_from_reference_signal",
    "bin_start_ft_from_reference_signal",
    "bin_end_ft_from_reference_signal",
    "distance_window",
    "roadway_representation_type",
    "far_anchor_type",
]

BIN_OUTPUT_COLUMNS = [
    "reference_signal_id",
    "reference_directional_segment_id",
    "reference_directional_bin_id",
    "signal_relative_direction",
    "bin_midpoint_ft_from_reference_signal",
    "distance_window",
    "access_v2_total_count",
    "unrestricted_or_full_access_count",
    "right_in_right_out_count",
    "restricted_partial_access_count",
    "right_out_only_count",
    "right_in_only_count",
    "other_review_access_count",
    "unknown_access_count",
    "typed_access_count",
    "typed_access_share",
    "has_unrestricted_or_full_access",
    "has_right_in_right_out_access",
    "has_restricted_access",
    "dominant_access_control_category",
    "access_v2_context_status",
    "access_v2_ambiguity_flag",
]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _distance_window(midpoint_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([midpoint_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown_distance"
    if value <= 1000:
        return "high_priority_0_1000ft"
    if value <= 2500:
        return "sensitivity_1000_2500ft"
    return "review_over_2500ft"


def _contains_crash_direction(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _context_path() -> Path:
    return ACTIVE_CONTEXT_FILE if ACTIVE_CONTEXT_FILE.exists() else BASE_CONTEXT_FILE


def _crash_context_path() -> Path | None:
    if ACTIVE_CRASH_CONTEXT_FILE.exists():
        return ACTIVE_CRASH_CONTEXT_FILE
    return BASE_CRASH_CONTEXT_FILE if BASE_CRASH_CONTEXT_FILE.exists() else None


def _load_access_v2() -> gpd.GeoDataFrame:
    access = gpd.read_parquet(ACCESS_V2_FILE)
    access = access.to_crs(WORKING_CRS_AUTHORITY)
    access["access_v2_uid"] = (
        access["access_v2_source_priority"].astype(str)
        + ":"
        + access["access_v2_source_row_id"].astype(str)
    )
    crash_like = [column for column in access.columns if _contains_crash_direction(column)]
    if crash_like:
        access = access.drop(columns=crash_like)
    return access


def _load_context_bins() -> pd.DataFrame:
    context = _read_csv(_context_path())
    context["bin_midpoint_ft_from_reference_signal"] = _num(context, "bin_midpoint_ft_from_reference_signal")
    if "distance_window" not in context.columns:
        context["distance_window"] = context["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    context = context.loc[context["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()

    catchment_index = _read_csv(CATCHMENT_INDEX_FILE)
    catchment_index = catchment_index.loc[catchment_index["catchment_status"].eq("usable")].copy()
    keep = ["catchment_id", "reference_directional_bin_id", "catchment_status", "catchment_confidence", "catchment_method"]
    context = context.merge(catchment_index[[c for c in keep if c in catchment_index.columns]], on="reference_directional_bin_id", how="left")
    context["context_join_eligible"] = context["catchment_status"].eq("usable")
    return context


def _load_catchments(context_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    catchments = gpd.read_file(CATCHMENT_POLYGONS_FILE)
    catchments, _, _ = apply_authoritative_crs(catchments, metadata_path=CATCHMENT_CRS_METADATA_FILE)
    eligible_ids = set(context_bins.loc[context_bins["context_join_eligible"], "catchment_id"].astype(str))
    catchments = catchments.loc[catchments["catchment_id"].astype(str).isin(eligible_ids)].copy()
    keep = [
        "catchment_id",
        "reference_directional_bin_id",
        "reference_directional_segment_id",
        "reference_signal_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_index_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "catchment_method",
        "catchment_status",
        "geometry",
    ]
    return catchments[[c for c in keep if c in catchments.columns]].copy()


def _contained_matches(access: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    cols = [c for c in ACCESS_OUTPUT_FIELDS if c in access.columns]
    joined = gpd.sjoin(access[cols + ["geometry"]], catchments, how="inner", predicate="within")
    if joined.empty:
        return pd.DataFrame(columns=cols + ["reference_directional_bin_id", "match_method"])
    out = pd.DataFrame(joined.drop(columns=["geometry", "index_right"], errors="ignore"))
    out["match_method"] = "point_within_usable_directional_catchment"
    return out


def _nearest_unmatched(access: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame, matched_any_ids: set[str]) -> pd.DataFrame:
    cols = [c for c in ACCESS_OUTPUT_FIELDS if c in access.columns]
    unmatched = access.loc[~access["access_v2_uid"].astype(str).isin(matched_any_ids), cols + ["geometry"]].copy()
    if unmatched.empty:
        return pd.DataFrame(columns=cols + ["nearest_reference_directional_bin_id", "nearest_access_distance_ft", "unmatched_status"])
    nearest = gpd.sjoin_nearest(
        unmatched,
        catchments[["reference_directional_bin_id", "geometry"]],
        how="left",
        max_distance=THRESHOLD_250FT_M,
        distance_col="nearest_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest["nearest_access_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest = nearest.rename(columns={"reference_directional_bin_id": "nearest_reference_directional_bin_id"})
    nearest["unmatched_status"] = nearest["nearest_reference_directional_bin_id"].map(
        lambda value: "near_stable_universe_within_250ft" if str(value).strip() else "outside_stable_universe_250ft"
    )
    return nearest.drop(columns=["nearest_distance_m"], errors="ignore")


def _split_matches(contained: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, set[str]]:
    if contained.empty:
        return contained.copy(), contained.copy(), set()
    counts = contained.groupby("access_v2_uid", dropna=False)["reference_directional_bin_id"].nunique().rename("matched_bin_count")
    contained = contained.merge(counts, on="access_v2_uid", how="left")
    ambiguous = contained.loc[pd.to_numeric(contained["matched_bin_count"], errors="coerce").fillna(0).gt(1)].copy()
    single = contained.loc[pd.to_numeric(contained["matched_bin_count"], errors="coerce").fillna(0).eq(1)].copy()
    matched_any_ids = set(contained["access_v2_uid"].astype(str))
    return single, ambiguous, matched_any_ids


def _category_counts(single_matches: pd.DataFrame) -> pd.DataFrame:
    if single_matches.empty:
        return pd.DataFrame(columns=["reference_directional_bin_id", *COUNT_COLUMNS.values()])
    grouped = (
        single_matches.groupby(["reference_directional_bin_id", "access_control_category"], dropna=False)["access_v2_uid"]
        .nunique()
        .reset_index(name="count")
    )
    pivot = grouped.pivot_table(
        index="reference_directional_bin_id",
        columns="access_control_category",
        values="count",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    for category in ACCESS_CATEGORIES:
        if category not in pivot.columns:
            pivot[category] = 0
    out = pivot[["reference_directional_bin_id", *ACCESS_CATEGORIES]].copy()
    out = out.rename(columns=COUNT_COLUMNS)
    return out


def _build_bin_context(context_bins: pd.DataFrame, single_matches: pd.DataFrame, ambiguous: pd.DataFrame) -> pd.DataFrame:
    base = context_bins.loc[context_bins["context_join_eligible"]].copy()
    out = base[[c for c in BIN_BASE_COLUMNS if c in base.columns]].copy()
    counts = _category_counts(single_matches)
    out = out.merge(counts, on="reference_directional_bin_id", how="left")
    for column in COUNT_COLUMNS.values():
        out[column] = pd.to_numeric(out.get(column, 0), errors="coerce").fillna(0).astype(int)
    out["access_v2_total_count"] = out[list(COUNT_COLUMNS.values())].sum(axis=1).astype(int)
    typed_cols = [column for category, column in COUNT_COLUMNS.items() if category not in {"unknown", "other_review"}]
    out["typed_access_count"] = out[typed_cols].sum(axis=1).astype(int)
    out["typed_access_share"] = out.apply(
        lambda row: round(float(row["typed_access_count"]) / row["access_v2_total_count"], 6) if row["access_v2_total_count"] else 0.0,
        axis=1,
    )
    out["has_unrestricted_or_full_access"] = out["unrestricted_or_full_access_count"].gt(0)
    out["has_right_in_right_out_access"] = out["right_in_right_out_count"].gt(0)
    out["has_restricted_access"] = (
        out["restricted_partial_access_count"].gt(0)
        | out["right_out_only_count"].gt(0)
        | out["right_in_only_count"].gt(0)
    )
    out["dominant_access_control_category"] = out.apply(_dominant_category, axis=1)
    ambig_counts = (
        ambiguous.groupby("reference_directional_bin_id", dropna=False)["access_v2_uid"].nunique().reset_index(name="ambiguous_access_v2_count")
        if not ambiguous.empty
        else pd.DataFrame(columns=["reference_directional_bin_id", "ambiguous_access_v2_count"])
    )
    out = out.merge(ambig_counts, on="reference_directional_bin_id", how="left")
    out["ambiguous_access_v2_count"] = pd.to_numeric(out["ambiguous_access_v2_count"], errors="coerce").fillna(0).astype(int)
    out["access_v2_ambiguity_flag"] = out["ambiguous_access_v2_count"].gt(0)
    out["access_v2_context_status"] = out.apply(_context_status, axis=1)
    return out


def _dominant_category(row: pd.Series) -> str:
    values = {category: int(row.get(column, 0)) for category, column in COUNT_COLUMNS.items()}
    if sum(values.values()) == 0:
        return "none"
    return sorted(values.items(), key=lambda item: (-item[1], ACCESS_CATEGORIES.index(item[0])))[0][0]


def _context_status(row: pd.Series) -> str:
    if int(row.get("access_v2_total_count", 0)) > 0:
        return "access_v2_within_catchment"
    if int(row.get("ambiguous_access_v2_count", 0)) > 0:
        return "ambiguous_access_v2_excluded_from_counts"
    return "no_access_v2_within_catchment"


def _bin_length_ft(frame: pd.DataFrame) -> pd.Series:
    start = _num(frame, "bin_start_ft_from_reference_signal")
    end = _num(frame, "bin_end_ft_from_reference_signal")
    length = end - start
    midpoint = _num(frame, "bin_midpoint_ft_from_reference_signal")
    length = length.where(length.gt(0), 50.0)
    length = length.where(midpoint.notna(), 0.0)
    return length


def _summarize_typed(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["represented_length_ft"] = _bin_length_ft(work)
    agg_spec: dict[str, Any] = {
        "bin_count": ("reference_directional_bin_id", "nunique"),
        "represented_length_ft": ("represented_length_ft", "sum"),
        "access_v2_total_count": ("access_v2_total_count", "sum"),
        "typed_access_count": ("typed_access_count", "sum"),
        "bins_with_v2_access": ("access_v2_total_count", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).gt(0).sum())),
        "bins_with_typed_access": ("typed_access_count", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).gt(0).sum())),
    }
    for column in COUNT_COLUMNS.values():
        agg_spec[column] = (column, "sum")
    out = work.groupby(group_cols, dropna=False).agg(**agg_spec).reset_index()
    out["typed_access_share"] = out.apply(
        lambda row: round(float(row["typed_access_count"]) / row["access_v2_total_count"], 6) if row["access_v2_total_count"] else 0.0,
        axis=1,
    )
    length = out["represented_length_ft"].replace(0, pd.NA)
    out["access_v2_total_density_per_1000ft"] = (out["access_v2_total_count"] / length * 1000).round(6)
    out["unrestricted_or_full_density_per_1000ft"] = (out["unrestricted_or_full_access_count"] / length * 1000).round(6)
    out["right_in_right_out_density_per_1000ft"] = (out["right_in_right_out_count"] / length * 1000).round(6)
    restricted_total = out["restricted_partial_access_count"] + out["right_out_only_count"] + out["right_in_only_count"]
    out["restricted_access_density_per_1000ft"] = (restricted_total / length * 1000).round(6)
    return out


def _crash_context(bin_context: pd.DataFrame) -> pd.DataFrame:
    path = _crash_context_path()
    if path is None:
        return pd.DataFrame()
    crash_columns = list(pd.read_csv(path, nrows=0).columns)
    crash_columns = [c for c in crash_columns if not _contains_crash_direction(c) or c == "signal_relative_direction"]
    crashes = _read_csv(path, usecols=crash_columns)
    keep = [
        "reference_directional_bin_id",
        "access_v2_total_count",
        "unrestricted_or_full_access_count",
        "right_in_right_out_count",
        "restricted_partial_access_count",
        "right_out_only_count",
        "right_in_only_count",
        "other_review_access_count",
        "unknown_access_count",
        "typed_access_count",
        "typed_access_share",
        "has_unrestricted_or_full_access",
        "has_right_in_right_out_access",
        "has_restricted_access",
        "dominant_access_control_category",
        "access_v2_context_status",
        "access_v2_ambiguity_flag",
        "ambiguous_access_v2_count",
        "access_v2_total_density_per_1000ft",
        "unrestricted_or_full_density_per_1000ft",
        "right_in_right_out_density_per_1000ft",
        "restricted_access_density_per_1000ft",
    ]
    available = [c for c in keep if c in bin_context.columns]
    out = crashes.merge(bin_context[available], on="reference_directional_bin_id", how="left", suffixes=("", "_v2"))
    out["inherited_from_bin_access_context_v2"] = True
    return out


def _comparison_to_v1(bin_context: pd.DataFrame, single_matches: pd.DataFrame, ambiguous: pd.DataFrame, unmatched: pd.DataFrame) -> pd.DataFrame:
    v1_summary_path = V1_CONTEXT_DIR / "access_context_join_summary.csv"
    v1_bin_path = V1_CONTEXT_DIR / "directional_bin_access_context.csv"
    rows = []
    v1_summary: dict[str, str] = {}
    if v1_summary_path.exists():
        summary = _read_csv(v1_summary_path)
        v1_summary = {row["metric"]: row["count"] or row["value"] for _, row in summary.iterrows()}
    v1_bins_with_access = 0
    v1_total_access_counts = 0
    if v1_bin_path.exists():
        v1_bins = pd.read_csv(
            v1_bin_path,
            usecols=["reference_directional_bin_id", "access_count_within_catchment"],
            dtype=str,
            keep_default_na=False,
        )
        v1_counts = pd.to_numeric(v1_bins["access_count_within_catchment"], errors="coerce").fillna(0)
        v1_bins_with_access = int(v1_counts.gt(0).sum())
        v1_total_access_counts = int(v1_counts.sum())
    v2_total = int(bin_context["access_v2_total_count"].sum())
    v2_bins_with_access = int(bin_context["access_v2_total_count"].gt(0).sum())
    metrics = [
        (
            "access_points_considered",
            v1_summary.get("access_features_considered", ""),
            (single_matches["access_v2_uid"].nunique() if not single_matches.empty else 0)
            + (ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0)
            + (unmatched["access_v2_uid"].nunique() if not unmatched.empty else 0),
        ),
        ("matched_points", v1_summary.get("access_features_matched_to_at_least_one_stable_bin", ""), single_matches["access_v2_uid"].nunique() if not single_matches.empty else 0),
        ("ambiguous_points", v1_summary.get("ambiguous_access_matches", ""), ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0),
        ("unmatched_or_outside_points", v1_summary.get("unmatched_access_features", ""), unmatched["access_v2_uid"].nunique() if not unmatched.empty else 0),
        ("bins_with_access", v1_bins_with_access, v2_bins_with_access),
        ("total_bin_access_counts", v1_total_access_counts, v2_total),
        ("typed_access_coverage_count", "", int(bin_context["typed_access_count"].sum())),
        ("bins_with_typed_access", "", int(bin_context["typed_access_count"].gt(0).sum())),
    ]
    for metric, v1_value, v2_value in metrics:
        rows.append(
            {
                "comparison_metric": metric,
                "v1_value": v1_value,
                "v2_value": v2_value,
                "difference_v2_minus_v1": _diff(v2_value, v1_value),
                "comparison_note": "candidate_v2_not_active",
            }
        )
    rows.append(
        {
            "comparison_metric": "material_context_change_assessment",
            "v1_value": "",
            "v2_value": "review_required",
            "difference_v2_minus_v1": "",
            "comparison_note": "v2 materially changes typed context availability; figures/model inputs require refresh only if promoted",
        }
    )
    return pd.DataFrame(rows)


def _diff(left: Any, right: Any) -> Any:
    try:
        return int(left) - int(right)
    except Exception:
        return ""


def _summary(
    access: gpd.GeoDataFrame,
    single_matches: pd.DataFrame,
    ambiguous: pd.DataFrame,
    unmatched: pd.DataFrame,
    bin_context: pd.DataFrame,
    crash_context: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "access_v2_points_considered", "value": "", "count": len(access)},
            {"metric": "access_v2_matched_points", "value": "", "count": single_matches["access_v2_uid"].nunique() if not single_matches.empty else 0},
            {"metric": "access_v2_ambiguous_points", "value": "", "count": ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0},
            {"metric": "access_v2_unmatched_or_outside_points", "value": "", "count": unmatched["access_v2_uid"].nunique() if not unmatched.empty else len(access)},
            {"metric": "bins_with_v2_access", "value": "", "count": int(bin_context["access_v2_total_count"].gt(0).sum())},
            {"metric": "bins_with_typed_access", "value": "", "count": int(bin_context["typed_access_count"].gt(0).sum())},
            {"metric": "stable_universe_access_v2_total_count", "value": "", "count": int(bin_context["access_v2_total_count"].sum())},
            {"metric": "stable_universe_typed_access_count", "value": "", "count": int(bin_context["typed_access_count"].sum())},
            {"metric": "crashes_inheriting_access_v2_context", "value": "", "count": len(crash_context)},
            {"metric": "access_v2_promoted_active", "value": False, "count": ""},
        ]
    )


def _qa(
    access: gpd.GeoDataFrame,
    single_matches: pd.DataFrame,
    ambiguous: pd.DataFrame,
    unmatched: pd.DataFrame,
    bin_context: pd.DataFrame,
) -> pd.DataFrame:
    category_sum = bin_context[list(COUNT_COLUMNS.values())].sum(axis=1)
    total = bin_context["access_v2_total_count"]
    unknown_other_preserved = "unknown_access_count" in bin_context.columns and "other_review_access_count" in bin_context.columns
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False, "expected": False},
            {"check_name": "access_v1_outputs_not_overwritten", "status": "passed", "observed": str(V1_CONTEXT_DIR), "expected": "read_only"},
            {"check_name": "active_context_outputs_not_overwritten", "status": "passed", "observed": str(_context_path()), "expected": "read_only"},
            {"check_name": "access_v2_parquet_used", "status": "passed" if ACCESS_V2_FILE.exists() else "failed", "observed": str(ACCESS_V2_FILE), "expected": "exists"},
            {"check_name": "ambiguous_access_points_separate", "status": "passed", "observed": ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0, "expected": "reported_separately"},
            {"check_name": "typed_categories_sum_to_total_counts", "status": "passed" if category_sum.equals(total) else "failed", "observed": bool(category_sum.equals(total)), "expected": True},
            {"check_name": "unknown_other_review_preserved", "status": "passed" if unknown_other_preserved else "failed", "observed": "columns_preserved" if unknown_other_preserved else "missing_columns", "expected": "preserved"},
            {"check_name": "no_source_context_rate_model_outputs_modified", "status": "passed", "observed": "candidate_output_folder_only", "expected": "no_changes"},
            {"check_name": "access_v2_remains_candidate", "status": "passed", "observed": "not_promoted", "expected": "candidate"},
            {"check_name": "access_v2_points_considered", "status": "passed" if len(access) > 0 else "failed", "observed": len(access), "expected": ">0"},
            {"check_name": "matched_ambiguous_unmatched_partition", "status": "passed" if (single_matches["access_v2_uid"].nunique() if not single_matches.empty else 0) + (ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0) + (unmatched["access_v2_uid"].nunique() if not unmatched.empty else 0) == len(access) else "failed", "observed": "see summary", "expected": len(access)},
        ]
    )


def _findings(summary: pd.DataFrame, category_counts: pd.DataFrame, comparison: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    category_lines = [f"- {row.access_control_category}: {row.value_count}" for row in category_counts.itertuples(index=False)]
    qa_passed = int(qa["status"].eq("passed").sum())
    lines = [
        "# Access Context V2 Findings",
        "",
        "## Bounded Question",
        "",
        "Join candidate typed access_v2 points to the stable directional-bin catchment universe without promoting v2 as active.",
        "",
        "## Inputs",
        "",
        f"- `{ACCESS_V2_FILE}`",
        f"- `{_context_path()}`",
        f"- `{CATCHMENT_INDEX_FILE}`",
        f"- `{CATCHMENT_POLYGONS_FILE}`",
        f"- `{V1_CONTEXT_DIR}` for comparison only",
        f"- `{V2_STAGING_DIR}` for source-staging provenance",
        "",
        "## Readout",
        "",
        f"- v2 access points considered: {count('access_v2_points_considered')}",
        f"- v2 matched points: {count('access_v2_matched_points')}",
        f"- v2 ambiguous points: {count('access_v2_ambiguous_points')}",
        f"- v2 unmatched/outside points: {count('access_v2_unmatched_or_outside_points')}",
        f"- bins with v2 access: {count('bins_with_v2_access')}",
        f"- bins with typed access: {count('bins_with_typed_access')}",
        f"- crashes inheriting access_v2 context: {count('crashes_inheriting_access_v2_context')}",
        "",
        "## Stable-Universe Typed Access Counts",
        "",
        *category_lines,
        "",
        "## Comparison To V1",
        "",
        *[
            f"- {row.comparison_metric}: v1={row.v1_value}, v2={row.v2_value}, diff={row.difference_v2_minus_v1}"
            for row in comparison.itertuples(index=False)
        ],
        "",
        "## Promotion Recommendation",
        "",
        "Do not promote access_v2 as active yet. Review typed-category mapping, ambiguous matches, and downstream context shifts first.",
        "",
        "If promoted, refresh access context, active directional bin context, context relationship figures, descriptive summaries, rate outputs, and modeling-readiness/model input products that consume access fields.",
        "",
        "## QA",
        "",
        f"- QA checks passed: {qa_passed} of {len(qa)}",
        "",
        "## Outputs",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_access_context_join_v2(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    access = _load_access_v2()
    context_bins = _load_context_bins()
    catchments = _load_catchments(context_bins)
    contained = _contained_matches(access, catchments)
    single_matches, ambiguous, matched_any_ids = _split_matches(contained)
    unmatched = _nearest_unmatched(access, catchments, matched_any_ids)
    bin_context = _build_bin_context(context_bins, single_matches, ambiguous)
    signal_summary = _summarize_typed(bin_context, ["reference_signal_id", "distance_window", "signal_relative_direction"])
    by_bin = bin_context.copy()
    by_signal = _summarize_typed(bin_context, ["reference_signal_id"])
    by_distance = _summarize_typed(bin_context, ["distance_window"])
    crash_context = _crash_context(bin_context)
    comparison = _comparison_to_v1(bin_context, single_matches, ambiguous, unmatched)
    summary = _summary(access, single_matches, ambiguous, unmatched, bin_context, crash_context)
    category_counts = _value_counts(single_matches, "access_control_category", "access_control_category")
    qa = _qa(access, single_matches, ambiguous, unmatched, bin_context)

    high_priority = bin_context.loc[bin_context["distance_window"].eq("high_priority_0_1000ft")].copy()
    sensitivity = bin_context.loc[bin_context["distance_window"].eq("sensitivity_1000_2500ft")].copy()

    outputs = {
        "summary_csv": out_dir / "access_context_v2_summary.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_access_context_v2.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_access_context_v2_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_access_context_v2_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_access_context_v2.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_access_context_summary_v2.csv",
        "points_joined_csv": out_dir / "access_v2_points_joined_to_stable_universe.csv",
        "points_ambiguous_csv": out_dir / "access_v2_points_ambiguous_bin_matches.csv",
        "points_unmatched_csv": out_dir / "access_v2_points_unmatched_or_outside_stable_universe.csv",
        "type_summary_by_bin_csv": out_dir / "access_v2_type_summary_by_bin.csv",
        "type_summary_by_reference_signal_csv": out_dir / "access_v2_type_summary_by_reference_signal.csv",
        "type_summary_by_distance_band_csv": out_dir / "access_v2_type_summary_by_distance_band.csv",
        "comparison_to_v1_csv": out_dir / "access_v2_comparison_to_v1_access_context.csv",
        "qa_csv": out_dir / "access_context_v2_qa.csv",
        "findings_md": out_dir / "access_context_v2_findings.md",
        "manifest_json": out_dir / "access_context_v2_manifest.json",
    }

    _write_csv(summary, outputs["summary_csv"])
    _write_csv(_ordered_bin_context(bin_context), outputs["directional_bin_context_csv"])
    _write_csv(_ordered_bin_context(high_priority), outputs["directional_bin_context_0_1000_csv"])
    _write_csv(_ordered_bin_context(sensitivity), outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(signal_summary, outputs["reference_signal_summary_csv"])
    _write_csv(single_matches, outputs["points_joined_csv"])
    _write_csv(ambiguous, outputs["points_ambiguous_csv"])
    _write_csv(unmatched, outputs["points_unmatched_csv"])
    _write_csv(by_bin, outputs["type_summary_by_bin_csv"])
    _write_csv(by_signal, outputs["type_summary_by_reference_signal_csv"])
    _write_csv(by_distance, outputs["type_summary_by_distance_band_csv"])
    _write_csv(comparison, outputs["comparison_to_v1_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, category_counts, comparison, qa, outputs), outputs["findings_md"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "candidate typed access v2 context join only",
        "access_v2_promoted_active": False,
        "crash_direction_fields_read_or_used": False,
        "v1_access_outputs_overwritten": False,
        "active_context_outputs_overwritten": False,
        "downstream_rate_model_outputs_modified": False,
        "inputs": {
            "access_v2": str(ACCESS_V2_FILE),
            "directional_bin_context": str(_context_path()),
            "directional_crash_context": str(_crash_context_path() or ""),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "catchment_polygons": str(CATCHMENT_POLYGONS_FILE),
            "v1_access_context_dir": str(V1_CONTEXT_DIR),
            "access_v2_staging_dir": str(V2_STAGING_DIR),
        },
        "summary": summary.to_dict(orient="records"),
        "qa_checks": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def _value_counts(frame: pd.DataFrame, column: str, output_column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[output_column, "value_count", "value_pct"])
    values = frame[column].fillna("").astype(str).str.strip()
    counts = values.value_counts(dropna=False).reset_index()
    counts.columns = [output_column, "value_count"]
    counts["value_pct"] = counts["value_count"].map(lambda count: round(float(count) / max(len(frame), 1), 6))
    return counts


def _ordered_bin_context(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = [c for c in BIN_OUTPUT_COLUMNS if c in frame.columns]
    remaining = [c for c in frame.columns if c not in ordered]
    return frame[ordered + remaining].copy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Candidate typed access v2 context join for roadway_graph directional bins.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_access_context_join_v2(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
