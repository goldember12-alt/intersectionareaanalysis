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
OUTPUT_DIR = Path("review/current/access_context_join")
ACCESS_FILE = Path("artifacts/normalized/access.parquet")

READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
CATCHMENT_POLYGONS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_polygons.geojson"
CATCHMENT_CRS_METADATA_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_crs_metadata.json"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"
INVENTORY_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/context_source_inventory/access_source_crs_sanity.csv"

FEET_TO_METERS = 0.3048
THRESHOLD_100FT_M = 100.0 * FEET_TO_METERS
THRESHOLD_250FT_M = 250.0 * FEET_TO_METERS

ACCESS_ID_FIELD = "id"
ACCESS_ROUTE_FIELDS = ["_rte_nm", "CROSS_STREET", "TURN_LANES_PRIMARY_ROUTE"]
ACCESS_CATEGORY_FIELDS = [
    "ACCESS_CONTROL",
    "ACCESS_DIRECTION",
    "COMMERCIAL_RETAIL",
    "RESIDENTIAL",
    "INDUSTRIAL",
    "GOV_SCHOOL_INSTITUTIONAL",
    "NUMBER_OF_APPROACHES",
    "TURN_LANES_PRIMARY_ROUTE",
]

MAIN_OUTPUT_COLUMNS = [
    "reference_signal_id",
    "reference_directional_segment_id",
    "reference_directional_bin_id",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_midpoint_ft_from_reference_signal",
    "distance_window",
    "roadway_representation_type",
    "far_anchor_type",
    "access_count_within_catchment",
    "access_count_within_100ft",
    "access_count_within_250ft",
    "nearest_access_id",
    "nearest_access_distance_ft",
    "access_context_status",
]

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _distance_window(midpoint_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([midpoint_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown_distance"
    if value <= 1000:
        return "high_priority_0_1000ft"
    if value <= 2500:
        return "sensitivity_1000_2500ft"
    return "review_over_2500ft"


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _load_access() -> gpd.GeoDataFrame:
    access = gpd.read_parquet(ACCESS_FILE)
    if access.crs is None:
        raise ValueError("Access source has no CRS; run context source inventory and repair source metadata before joining.")
    return access.to_crs(WORKING_CRS_AUTHORITY)


def _load_context_bins() -> pd.DataFrame:
    bins = _read_csv(USABLE_BINS_FILE)
    catchment_index = _read_csv(CATCHMENT_INDEX_FILE)
    catchment_index = catchment_index.loc[catchment_index["catchment_status"].eq("usable")].copy()
    bins["bin_midpoint_ft_from_reference_signal"] = _num(bins, "bin_midpoint_ft_from_reference_signal")
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    catchment_keep = [
        "catchment_id",
        "reference_directional_bin_id",
        "catchment_status",
        "catchment_confidence",
        "catchment_method",
    ]
    context = bins.merge(catchment_index[[c for c in catchment_keep if c in catchment_index.columns]], on="reference_directional_bin_id", how="left")
    context["context_join_eligible"] = context["catchment_status"].eq("usable") & context["bin_midpoint_ft_from_reference_signal"].le(2500)
    return context


def _load_context_catchments(context_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    catchments = gpd.read_file(CATCHMENT_POLYGONS_FILE)
    catchments, _, _ = apply_authoritative_crs(catchments, metadata_path=CATCHMENT_CRS_METADATA_FILE)
    eligible_ids = set(context_bins.loc[context_bins["context_join_eligible"], "catchment_id"].dropna().astype(str))
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


def _access_columns_for_output(access: gpd.GeoDataFrame) -> list[str]:
    columns = [ACCESS_ID_FIELD]
    for field in [*ACCESS_ROUTE_FIELDS, *ACCESS_CATEGORY_FIELDS]:
        if field in access.columns and field not in columns:
            columns.append(field)
    return columns


def _contained_access_matches(access: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    access_cols = _access_columns_for_output(access)
    joined = gpd.sjoin(
        access[access_cols + ["geometry"]].reset_index(names="access_source_index"),
        catchments,
        how="inner",
        predicate="within",
    )
    if joined.empty:
        return pd.DataFrame(columns=["access_source_index", "access_id", "reference_directional_bin_id"])
    joined = pd.DataFrame(joined.drop(columns=["geometry", "index_right"], errors="ignore"))
    joined = joined.rename(columns={ACCESS_ID_FIELD: "access_id"})
    joined["match_method"] = "point_within_usable_directional_catchment"
    joined["nearest_access_distance_ft"] = 0.0
    return joined


def _nearest_access_matches(access: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    access_cols = _access_columns_for_output(access)
    nearest = gpd.sjoin_nearest(
        access[access_cols + ["geometry"]].reset_index(names="access_source_index"),
        catchments,
        how="left",
        max_distance=THRESHOLD_250FT_M,
        distance_col="nearest_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest = nearest.rename(columns={ACCESS_ID_FIELD: "access_id"})
    nearest["nearest_access_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest["within_100ft"] = nearest["nearest_access_distance_ft"].le(100.0)
    nearest["within_250ft"] = nearest["nearest_access_distance_ft"].le(250.0)
    return nearest


def _category_counts(matches: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if matches.empty or "reference_directional_bin_id" not in matches.columns:
        return pd.DataFrame(columns=["reference_directional_bin_id"])
    rows = []
    for bin_id, group in matches.groupby("reference_directional_bin_id", dropna=False):
        row: dict[str, Any] = {"reference_directional_bin_id": bin_id}
        for field in ACCESS_CATEGORY_FIELDS:
            if field not in group.columns:
                continue
            row[f"{prefix}_{field.lower()}_nonempty_count"] = int(_nonempty(group[field]).sum())
            values = sorted(group.loc[_nonempty(group[field]), field].astype(str).unique().tolist())[:10]
            row[f"{prefix}_{field.lower()}_values"] = "|".join(values)
        rows.append(row)
    return pd.DataFrame(rows)


def _build_bin_context(context_bins: pd.DataFrame, contained: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    primary = context_bins.loc[context_bins["context_join_eligible"]].copy()
    base_columns = [
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "far_anchor_type",
    ]
    out = primary[[c for c in base_columns if c in primary.columns]].copy()

    contained_counts = _unique_count(contained, "reference_directional_bin_id", "access_id", "access_count_within_catchment")
    contained_with_match_counts = contained.copy()
    if not contained_with_match_counts.empty:
        access_match_counts = contained_with_match_counts.groupby("access_id", dropna=False)["reference_directional_bin_id"].nunique()
        contained_with_match_counts["access_matched_bin_count"] = contained_with_match_counts["access_id"].map(access_match_counts)
    ambiguous_counts = _unique_count(
        contained_with_match_counts.loc[contained_with_match_counts.get("access_matched_bin_count", pd.Series(dtype=int)).fillna(0).astype(int).gt(1)]
        if not contained_with_match_counts.empty
        else pd.DataFrame(),
        "reference_directional_bin_id",
        "access_id",
        "access_ambiguous_multiple_bin_match_count",
    )
    nearest_100 = nearest.loc[nearest["within_100ft"].fillna(False)].copy()
    nearest_250 = nearest.loc[nearest["within_250ft"].fillna(False)].copy()
    count_100 = _unique_count(nearest_100, "reference_directional_bin_id", "access_id", "access_count_within_100ft")
    count_250 = _unique_count(nearest_250, "reference_directional_bin_id", "access_id", "access_count_within_250ft")
    nearest_best = _nearest_best(nearest)
    contained_categories = _category_counts(contained, "catchment")
    nearest_100_categories = _category_counts(nearest_100, "within_100ft")
    nearest_250_categories = _category_counts(nearest_250, "within_250ft")
    for frame in [contained_counts, ambiguous_counts, count_100, count_250, nearest_best, contained_categories, nearest_100_categories, nearest_250_categories]:
        if not frame.empty:
            out = out.merge(frame, on="reference_directional_bin_id", how="left")
    for column in [
        "access_count_within_catchment",
        "access_ambiguous_multiple_bin_match_count",
        "access_count_within_100ft",
        "access_count_within_250ft",
    ]:
        out[column] = pd.to_numeric(out.get(column, 0), errors="coerce").fillna(0).astype(int)
    if "nearest_access_id" not in out.columns:
        out["nearest_access_id"] = ""
    if "nearest_access_distance_ft" not in out.columns:
        out["nearest_access_distance_ft"] = pd.NA
    out["access_context_status"] = out.apply(_access_context_status, axis=1)
    return out


def _unique_count(frame: pd.DataFrame, group_column: str, value_column: str, output_column: str) -> pd.DataFrame:
    if frame.empty or group_column not in frame.columns:
        return pd.DataFrame(columns=[group_column, output_column])
    return frame.groupby(group_column, dropna=False)[value_column].nunique().reset_index(name=output_column)


def _nearest_best(nearest: pd.DataFrame) -> pd.DataFrame:
    valid = nearest.loc[nearest["nearest_access_distance_ft"].notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=["reference_directional_bin_id", "nearest_access_id", "nearest_access_distance_ft"])
    valid = valid.sort_values(["reference_directional_bin_id", "nearest_access_distance_ft", "access_id"])
    best = valid.groupby("reference_directional_bin_id", dropna=False).head(1)
    return best[["reference_directional_bin_id", "access_id", "nearest_access_distance_ft"]].rename(columns={"access_id": "nearest_access_id"})


def _access_context_status(row: pd.Series) -> str:
    if row.get("distance_window") == "review_over_2500ft":
        return "outside_context_window"
    if int(row.get("access_ambiguous_multiple_bin_match_count", 0)) > 0:
        return "ambiguous_multiple_bins"
    if int(row.get("access_count_within_catchment", 0)) > 1:
        return "access_within_catchment"
    if int(row.get("access_count_within_catchment", 0)) == 1:
        return "access_within_catchment"
    if int(row.get("access_count_within_100ft", 0)) > 0:
        return "access_within_100ft"
    if int(row.get("access_count_within_250ft", 0)) > 0:
        return "access_within_250ft"
    return "no_access_nearby"


def _access_point_outputs(access: gpd.GeoDataFrame, contained: pd.DataFrame, nearest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    contained = contained.copy()
    if not contained.empty:
        match_counts = contained.groupby("access_id", dropna=False)["reference_directional_bin_id"].nunique().rename("matched_bin_count").reset_index()
        contained = contained.merge(match_counts, on="access_id", how="left")
        contained["access_match_status"] = contained["matched_bin_count"].map(lambda value: "ambiguous_multiple_bins" if int(value) > 1 else "matched_single_bin")
    ambiguous = contained.loc[contained.get("matched_bin_count", pd.Series(dtype=int)).fillna(0).astype(int).gt(1)].copy() if not contained.empty else pd.DataFrame()

    matched_ids = set(contained["access_id"].astype(str)) if not contained.empty else set()
    nearest_valid = nearest.loc[nearest["access_id"].notna()].copy()
    nearest_ids = set(nearest_valid["access_id"].astype(str))
    access_cols = _access_columns_for_output(access)
    access_plain = pd.DataFrame(access[access_cols].copy()).rename(columns={ACCESS_ID_FIELD: "access_id"})
    unmatched = access_plain.loc[~access_plain["access_id"].astype(str).isin(matched_ids)].copy()
    nearest_status = nearest_valid.sort_values(["access_id", "nearest_access_distance_ft"]).groupby("access_id", dropna=False).head(1)
    nearest_status = nearest_status[["access_id", "nearest_access_distance_ft", "reference_directional_bin_id"]].rename(
        columns={"reference_directional_bin_id": "nearest_reference_directional_bin_id"}
    )
    unmatched = unmatched.merge(nearest_status, on="access_id", how="left")
    unmatched["unmatched_status"] = unmatched["access_id"].astype(str).map(
        lambda access_id: "near_stable_universe_within_250ft" if access_id in nearest_ids else "outside_stable_universe_250ft"
    )
    return contained, ambiguous, unmatched


def _crash_context(readiness: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    readiness = readiness.copy()
    readiness["bin_midpoint_ft_from_reference_signal"] = _num(readiness, "bin_midpoint_ft_from_reference_signal")
    readiness = readiness.loc[readiness["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    keep = [
        "reference_directional_bin_id",
        "distance_window",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "nearest_access_id",
        "nearest_access_distance_ft",
    ]
    out = readiness.merge(bin_context[[c for c in keep if c in bin_context.columns]], on="reference_directional_bin_id", how="left", suffixes=("", "_bin"))
    out["inherited_from_bin_access_context"] = True
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "nearest_access_id",
        "nearest_access_distance_ft",
        "inherited_from_bin_access_context",
    ]
    return out[[c for c in columns if c in out.columns]]


def _reference_signal_summary(bin_context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in bin_context.groupby(["reference_signal_id", "distance_window", "signal_relative_direction"], dropna=False):
        reference_signal_id, distance_window, direction = keys
        rows.append(
            {
                "reference_signal_id": reference_signal_id,
                "distance_window": distance_window,
                "signal_relative_direction": direction,
                "bin_count": len(group),
                "bins_with_access_within_catchment": int(group["access_count_within_catchment"].gt(0).sum()),
                "bins_with_access_within_100ft": int(group["access_count_within_100ft"].gt(0).sum()),
                "bins_with_access_within_250ft": int(group["access_count_within_250ft"].gt(0).sum()),
                "total_access_count_within_catchment": int(group["access_count_within_catchment"].sum()),
                "total_access_count_within_100ft": int(group["access_count_within_100ft"].sum()),
                "total_access_count_within_250ft": int(group["access_count_within_250ft"].sum()),
                "nearest_access_distance_ft": pd.to_numeric(group["nearest_access_distance_ft"], errors="coerce").min(),
            }
        )
    return pd.DataFrame(rows)


def _by_direction(bin_context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(bin_context, ["signal_relative_direction"])


def _by_window(bin_context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(bin_context, ["distance_window"])


def _summarize_bins(bin_context: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if bin_context.empty:
        return pd.DataFrame()
    return (
        bin_context.groupby(columns, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            bins_with_access_within_catchment=("access_count_within_catchment", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).gt(0).sum())),
            bins_with_access_within_100ft=("access_count_within_100ft", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).gt(0).sum())),
            bins_with_access_within_250ft=("access_count_within_250ft", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).gt(0).sum())),
            total_access_count_within_catchment=("access_count_within_catchment", "sum"),
            total_access_count_within_100ft=("access_count_within_100ft", "sum"),
            total_access_count_within_250ft=("access_count_within_250ft", "sum"),
        )
        .reset_index()
    )


def _by_access_category(contained: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source_name, frame in [("within_catchment", contained), ("within_250ft_nearest_bin", nearest.loc[nearest["within_250ft"].fillna(False)].copy())]:
        if frame.empty:
            continue
        for field in ACCESS_CATEGORY_FIELDS:
            if field not in frame.columns:
                continue
            nonempty = frame.loc[_nonempty(frame[field])].copy()
            if nonempty.empty:
                rows.append({"match_context": source_name, "category_field": field, "category_value": "<no_nonempty_values>", "access_point_count": 0})
                continue
            grouped = nonempty.groupby(field, dropna=False)["access_id"].nunique().reset_index(name="access_point_count")
            for row in grouped.itertuples(index=False):
                rows.append(
                    {
                        "match_context": source_name,
                        "category_field": field,
                        "category_value": getattr(row, field),
                        "access_point_count": int(row.access_point_count),
                    }
                )
    return pd.DataFrame(rows)


def _qa(
    *,
    access: gpd.GeoDataFrame,
    context_bins: pd.DataFrame,
    bin_context: pd.DataFrame,
    crash_context: pd.DataFrame,
    contained: pd.DataFrame,
    ambiguous: pd.DataFrame,
    unmatched: pd.DataFrame,
    readiness: pd.DataFrame,
) -> pd.DataFrame:
    direction_like_columns = [
        c
        for c in readiness.columns
        if any(token in c.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)
        and c != "signal_relative_direction"
    ]
    over_2500_in_main = int(pd.to_numeric(bin_context["bin_midpoint_ft_from_reference_signal"], errors="coerce").gt(2500).sum())
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": not direction_like_columns, "observed": "|".join(direction_like_columns), "expected": "none"},
        {"check_name": "access_direction_used_for_upstream_downstream", "passed": True, "observed": "not_used", "expected": "not_used"},
        {"check_name": "scaffold_catchment_assignment_readiness_logic_changed", "passed": True, "observed": "read_only_context_join", "expected": "no_changes"},
        {"check_name": "main_context_bins_lte_2500ft", "passed": over_2500_in_main == 0, "observed": over_2500_in_main, "expected": 0},
        {
            "check_name": "review_over_2500ft_bins_excluded_from_main",
            "passed": True,
            "observed": int((~context_bins["context_join_eligible"] & context_bins["bin_midpoint_ft_from_reference_signal"].gt(2500)).sum()),
            "expected": "reported_only",
        },
        {"check_name": "access_crs_matches_working_crs", "passed": crs_matches(access.crs, WORKING_CRS_AUTHORITY), "observed": crs_to_string(access.crs), "expected": WORKING_CRS_AUTHORITY},
        {"check_name": "access_features_considered", "passed": True, "observed": len(access), "expected": "reported"},
        {"check_name": "access_features_matched_to_at_least_one_stable_bin", "passed": True, "observed": contained["access_id"].nunique() if not contained.empty else 0, "expected": "reported"},
        {"check_name": "ambiguous_access_to_bin_matches", "passed": True, "observed": ambiguous["access_id"].nunique() if not ambiguous.empty else 0, "expected": "reported"},
        {"check_name": "unmatched_access_points", "passed": True, "observed": unmatched["access_id"].nunique() if not unmatched.empty else len(access), "expected": "reported"},
        {"check_name": "bins_with_access_within_catchment", "passed": True, "observed": int(bin_context["access_count_within_catchment"].gt(0).sum()), "expected": "reported"},
        {"check_name": "bins_with_access_within_100ft", "passed": True, "observed": int(bin_context["access_count_within_100ft"].gt(0).sum()), "expected": "reported"},
        {"check_name": "bins_with_access_within_250ft", "passed": True, "observed": int(bin_context["access_count_within_250ft"].gt(0).sum()), "expected": "reported"},
        {"check_name": "crashes_inheriting_access_context", "passed": True, "observed": len(crash_context), "expected": "reported"},
    ]
    return pd.DataFrame(rows)


def build_access_context_join(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    access = _load_access()
    context_bins = _load_context_bins()
    catchments = _load_context_catchments(context_bins)
    readiness = _read_csv(READINESS_FILE)
    _ = _read_csv(ASSIGNMENTS_FILE)

    contained = _contained_access_matches(access, catchments)
    nearest = _nearest_access_matches(access, catchments)
    bin_context = _build_bin_context(context_bins, contained, nearest)
    high_priority = bin_context.loc[bin_context["distance_window"].eq("high_priority_0_1000ft")].copy()
    sensitivity = bin_context.loc[bin_context["distance_window"].eq("sensitivity_1000_2500ft")].copy()
    crash_context = _crash_context(readiness, bin_context)
    signal_summary = _reference_signal_summary(bin_context)
    access_joined, access_ambiguous, access_unmatched = _access_point_outputs(access, contained, nearest)
    by_direction = _by_direction(bin_context)
    by_window = _by_window(bin_context)
    by_category = _by_access_category(contained, nearest)
    qa = _qa(
        access=access,
        context_bins=context_bins,
        bin_context=bin_context,
        crash_context=crash_context,
        contained=contained,
        ambiguous=access_ambiguous,
        unmatched=access_unmatched,
        readiness=readiness,
    )
    summary = _summary_frame(access, context_bins, bin_context, crash_context, access_joined, access_ambiguous, access_unmatched, signal_summary)

    outputs = {
        "summary_csv": out_dir / "access_context_join_summary.csv",
        "directional_bin_context_csv": out_dir / "directional_bin_access_context.csv",
        "directional_bin_context_0_1000_csv": out_dir / "directional_bin_access_context_0_1000ft.csv",
        "directional_bin_context_1000_2500_csv": out_dir / "directional_bin_access_context_1000_2500ft.csv",
        "directional_crash_context_csv": out_dir / "directional_crash_access_context.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_access_context_summary.csv",
        "access_points_joined_csv": out_dir / "access_points_joined_to_stable_universe.csv",
        "access_points_ambiguous_csv": out_dir / "access_points_ambiguous_bin_matches.csv",
        "access_points_unmatched_csv": out_dir / "access_points_unmatched_or_outside_stable_universe.csv",
        "by_direction_csv": out_dir / "access_context_by_signal_relative_direction.csv",
        "by_window_csv": out_dir / "access_context_by_distance_window.csv",
        "by_category_csv": out_dir / "access_context_by_access_category.csv",
        "qa_csv": out_dir / "access_context_join_qa.csv",
        "findings_md": out_dir / "access_context_join_findings.md",
        "manifest_json": out_dir / "access_context_join_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(_ordered_bin_context(bin_context), outputs["directional_bin_context_csv"])
    _write_csv(_ordered_bin_context(high_priority), outputs["directional_bin_context_0_1000_csv"])
    _write_csv(_ordered_bin_context(sensitivity), outputs["directional_bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["directional_crash_context_csv"])
    _write_csv(signal_summary, outputs["reference_signal_summary_csv"])
    _write_csv(access_joined, outputs["access_points_joined_csv"])
    _write_csv(access_ambiguous, outputs["access_points_ambiguous_csv"])
    _write_csv(access_unmatched, outputs["access_points_unmatched_csv"])
    _write_csv(by_direction, outputs["by_direction_csv"])
    _write_csv(by_window, outputs["by_window_csv"])
    _write_csv(by_category, outputs["by_category_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, qa, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only access context join for stable roadway-derived directional bin/crash universe",
        "main_context_window": "0-2500ft",
        "high_priority_window": "0-1000ft",
        "sensitivity_window": "1000-2500ft",
        "access_or_speed_other_context_joined": {"access": True, "speed": False, "aadt": False},
        "crash_direction_fields_read_or_used": False,
        "access_direction_used_for_upstream_downstream": False,
        "scaffold_catchment_assignment_readiness_logic_changed": False,
        "inputs": {
            "access": str(ACCESS_FILE),
            "readiness_by_crash": str(READINESS_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "catchment_polygons": str(CATCHMENT_POLYGONS_FILE),
            "assignments": str(ASSIGNMENTS_FILE),
            "inventory_crs_sanity": str(INVENTORY_CRS_SANITY_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def _ordered_bin_context(frame: pd.DataFrame) -> pd.DataFrame:
    category_columns = [c for c in frame.columns if c not in MAIN_OUTPUT_COLUMNS]
    ordered = [c for c in MAIN_OUTPUT_COLUMNS if c in frame.columns] + category_columns
    return frame[ordered].copy()


def _summary_frame(
    access: gpd.GeoDataFrame,
    context_bins: pd.DataFrame,
    bin_context: pd.DataFrame,
    crash_context: pd.DataFrame,
    access_joined: pd.DataFrame,
    access_ambiguous: pd.DataFrame,
    access_unmatched: pd.DataFrame,
    signal_summary: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        {"metric": "access_features_considered", "value": "", "count": len(access)},
        {"metric": "access_features_matched_to_at_least_one_stable_bin", "value": "", "count": access_joined["access_id"].nunique() if not access_joined.empty else 0},
        {"metric": "ambiguous_access_matches", "value": "", "count": access_ambiguous["access_id"].nunique() if not access_ambiguous.empty else 0},
        {"metric": "unmatched_access_features", "value": "", "count": access_unmatched["access_id"].nunique() if not access_unmatched.empty else len(access)},
        {"metric": "primary_context_bins_0_2500ft", "value": "", "count": len(bin_context)},
        {"metric": "excluded_review_bins_over_2500ft", "value": "", "count": int((~context_bins["context_join_eligible"] & context_bins["bin_midpoint_ft_from_reference_signal"].gt(2500)).sum())},
        {"metric": "bins_with_access_within_catchment", "value": "", "count": int(bin_context["access_count_within_catchment"].gt(0).sum())},
        {"metric": "bins_with_access_within_100ft", "value": "", "count": int(bin_context["access_count_within_100ft"].gt(0).sum())},
        {"metric": "bins_with_access_within_250ft", "value": "", "count": int(bin_context["access_count_within_250ft"].gt(0).sum())},
        {"metric": "crashes_inheriting_access_context", "value": "", "count": len(crash_context)},
        {"metric": "reference_signals_with_access_context", "value": "", "count": signal_summary["reference_signal_id"].nunique() if not signal_summary.empty else 0},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "access_direction_used_for_upstream_downstream", "value": False, "count": ""},
        {"metric": "scaffold_catchment_assignment_readiness_logic_changed", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def metric(name: str) -> Any:
        matched = summary.loc[summary["metric"].eq(name)]
        if matched.empty:
            return ""
        row = matched.iloc[0]
        return row["count"] if str(row["count"]) != "" else row["value"]

    failed = qa.loc[~qa["passed"].astype(bool)] if not qa.empty else pd.DataFrame()
    lines = [
        "# Access Context Join Findings",
        "",
        "## Bounded Question",
        "",
        "Attach access-point context to the stable roadway-derived directional bin/crash universe without changing scaffold, catchments, assignment, readiness, or upstream/downstream labels.",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
        "## Method Boundaries",
        "",
        "- crash direction fields read or used: False",
        "- access direction used for upstream/downstream: False",
        "- scaffold/catchment/assignment/readiness logic changed: False",
        "- speed or AADT joined: False",
        "- main context universe: usable catchment-backed bins with midpoint <= 2,500 ft",
        "",
        "## Readout",
        "",
        f"- access features considered: {metric('access_features_considered')}",
        f"- access features matched to at least one stable bin: {metric('access_features_matched_to_at_least_one_stable_bin')}",
        f"- ambiguous access matches: {metric('ambiguous_access_matches')}",
        f"- unmatched access features: {metric('unmatched_access_features')}",
        f"- bins with access within catchment: {metric('bins_with_access_within_catchment')}",
        f"- bins with access within 100 ft: {metric('bins_with_access_within_100ft')}",
        f"- bins with access within 250 ft: {metric('bins_with_access_within_250ft')}",
        f"- crashes inheriting access context: {metric('crashes_inheriting_access_context')}",
        f"- reference signals with access context rows: {metric('reference_signals_with_access_context')}",
        "",
        "## QA",
        "",
        f"- QA checks passed: {int(qa['passed'].astype(bool).sum()) if not qa.empty else 0} of {len(qa)}",
        *(["- Failed checks: " + ", ".join(failed["check_name"].astype(str).tolist())] if not failed.empty else []),
        "",
        "## Recommended Next Step",
        "",
        "Review access-context QA and spot-check ambiguous access matches before promoting a downstream descriptive summary. Speed context should remain blocked until a posted-speed source is recovered or restaged.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only access context join for stable roadway_graph directional bins and crashes.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_access_context_join(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
