from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
NORMALIZED_ROOT = Path("artifacts/normalized")
FEET_PER_METER = 3.280839895
SEARCH_RADIUS_FT = 75.0


def _read_wkt_csv(path: Path, crs) -> gpd.GeoDataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame["geometry"] = frame["geometry"].map(wkt.loads)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=crs)


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns and isinstance(frame, gpd.GeoDataFrame):
        out["geometry"] = frame.geometry.to_wkt()
    out.to_csv(path, index=False)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    else:
        frame.to_file(path, driver="GeoJSON")


def _crash_id_series(crashes: gpd.GeoDataFrame) -> pd.Series:
    if "DOCUMENT_NBR" in crashes.columns:
        base = crashes["DOCUMENT_NBR"].astype(str)
    else:
        base = pd.Series([f"crash_{idx:08d}" for idx in range(len(crashes))], index=crashes.index)
    if base.duplicated().any():
        return base + "_" + crashes.groupby(base).cumcount().astype(str)
    return base


def _direction_inventory(crashes: gpd.GeoDataFrame) -> pd.DataFrame:
    candidates = []
    terms = ("DIR", "DIRECT", "RTE_NM", "ROADWAY_DESCRIPTION", "RD_TYPE", "MAINLINE")
    for column in crashes.columns:
        if column == "geometry":
            continue
        upper = column.upper()
        if any(term in upper for term in terms):
            values = crashes[column]
            candidates.append(
                {
                    "field_name": column,
                    "non_null_count": int(values.notna().sum()),
                    "distinct_non_null_count": int(values.dropna().astype(str).nunique()),
                    "sample_values": " | ".join(values.dropna().astype(str).drop_duplicates().head(8)),
                    "direction_use_status": "support_only_not_used"
                    if column in {"RTE_NM", "ROADWAY_DESCRIPTION", "RD_TYPE", "MAINLINE_YN"}
                    else "candidate_name_only_not_validated",
                    "notes": "No field is treated as a validated crash travel-direction source in this prototype.",
                }
            )
    return pd.DataFrame(candidates)


def _distance_band(distance_ft: float) -> str:
    if distance_ft <= 10:
        return "0_to_10ft"
    if distance_ft <= 25:
        return "10_to_25ft"
    if distance_ft <= 50:
        return "25_to_50ft"
    if distance_ft <= 75:
        return "50_to_75ft"
    return "over_75ft"


def build_crash_assignment(
    *,
    normalized_root: Path = NORMALIZED_ROOT,
    output_root: Path = OUTPUT_ROOT,
    search_radius_ft: float = SEARCH_RADIUS_FT,
) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    geojson = output_root / "review/geojson/current"
    crashes = gpd.read_parquet(normalized_root / "crashes.parquet")
    crashes = crashes.loc[crashes.geometry.notna() & ~crashes.geometry.is_empty].copy()
    crashes = crashes.reset_index(drop=True)
    crashes["crash_id"] = _crash_id_series(crashes)

    segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_crash_ready.csv", crashes.crs)
    bins = _read_wkt_csv(tables / "signal_oriented_segment_bins_50ft_crash_ready.csv", crashes.crs)
    segment_ids = set(segments["oriented_segment_id"])
    bins = bins.loc[bins["oriented_segment_id"].isin(segment_ids)].copy()

    max_distance = search_radius_ft / FEET_PER_METER
    crash_points = crashes[["crash_id", "geometry"]].copy()
    nearest = gpd.sjoin_nearest(
        crash_points,
        bins[["bin_id", "oriented_segment_id", "geometry"]],
        how="left",
        max_distance=max_distance,
        distance_col="distance_to_bin_m",
    )
    nearest["candidate_count"] = nearest.groupby("crash_id")["bin_id"].transform("count")
    nearest["assignment_confidence"] = "high"
    nearest.loc[nearest["bin_id"].isna(), "assignment_confidence"] = "unresolved"
    nearest.loc[nearest["candidate_count"].fillna(0).gt(1), "assignment_confidence"] = "ambiguous"

    assigned_nearest = nearest.loc[nearest["assignment_confidence"].eq("high")].copy()
    assigned_nearest = assigned_nearest.drop(columns=["index_right"], errors="ignore")
    assigned = assigned_nearest.merge(
        bins.drop(columns="geometry"),
        on=["bin_id", "oriented_segment_id"],
        how="left",
        suffixes=("", "_bin"),
    ).merge(
        segments.drop(columns="geometry"),
        on="oriented_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    assigned["distance_to_bin_ft"] = pd.to_numeric(assigned["distance_to_bin_m"], errors="coerce") * FEET_PER_METER
    assigned["distance_to_segment_ft"] = assigned["distance_to_bin_ft"]
    assigned["distance_band"] = assigned["distance_to_bin_ft"].map(_distance_band)
    assigned["crash_direction_raw"] = ""
    assigned["crash_direction_source_field"] = ""
    assigned["event_direction_interpretation"] = "unresolved"
    assigned["direction_match_status"] = "not_evaluated"
    assigned["upstream_downstream_status"] = "unresolved"
    assigned["true_vehicle_direction_inferred"] = False
    assigned["assignment_confidence"] = "high"

    crash_attr_cols = [column for column in ["DOCUMENT_NBR", "CRASH_YEAR", "CRASH_DT", "RTE_NM", "RNS_MP", "NODE", "OFFSET"] if column in crashes.columns]
    assigned = assigned.merge(crashes[["crash_id", *crash_attr_cols]], on="crash_id", how="left")
    assigned_gdf = gpd.GeoDataFrame(assigned, geometry="geometry", crs=crashes.crs)

    unresolved_ids = set(crashes["crash_id"]) - set(assigned_gdf["crash_id"])
    unresolved = crashes.loc[crashes["crash_id"].isin(unresolved_ids), ["crash_id", *crash_attr_cols, "geometry"]].copy()
    ambiguous_ids = set(nearest.loc[nearest["assignment_confidence"].eq("ambiguous"), "crash_id"])
    unresolved["unresolved_reason"] = "outside_search_radius"
    unresolved.loc[unresolved["crash_id"].isin(ambiguous_ids), "unresolved_reason"] = "ambiguous_multiple_equidistant_bins"
    unresolved["nearest_search_radius_ft"] = search_radius_ft
    unresolved_gdf = gpd.GeoDataFrame(unresolved, geometry="geometry", crs=crashes.crs)

    assignment_cols = [
        "crash_id",
        "oriented_segment_id",
        "segment_family_id",
        "base_graph_edge_id",
        "bin_id",
        "bin_index",
        "bin_start_ft",
        "bin_end_ft",
        "bin_midpoint_ft",
        "reference_signal_id",
        "downstream_of_signal_id",
        "upstream_of_signal_id",
        "from_anchor_id",
        "to_anchor_id",
        "opposite_anchor_type",
        "opposite_anchor_id",
        "roadway_directionality_type",
        "orientation_record_type",
        "physical_directional_carriageway",
        "undivided_event_direction_requires_crash_direction",
        "crash_direction_raw",
        "crash_direction_source_field",
        "event_direction_interpretation",
        "direction_match_status",
        "upstream_downstream_status",
        "assignment_confidence",
        "distance_to_segment_ft",
        "distance_to_bin_ft",
        "distance_band",
        "true_vehicle_direction_inferred",
        *crash_attr_cols,
        "geometry",
    ]
    assigned_out = assigned_gdf[[column for column in assignment_cols if column in assigned_gdf.columns]].copy()

    _write_csv(assigned_out, tables / "crash_oriented_segment_bin_assignment.csv")
    _write_csv(unresolved_gdf, tables / "crash_oriented_segment_assignment_unresolved.csv")
    _write_geojson(assigned_out, geojson / "crash_assigned_to_oriented_segments.geojson")
    _write_geojson(unresolved_gdf, geojson / "crash_assignment_unresolved.geojson")

    inventory = _direction_inventory(crashes)
    _write_csv(inventory, review / "crash_direction_field_inventory.csv")

    summary_rows = [
        {"metric": "total_crash_records_considered", "value": len(crashes), "notes": "Normalized crash rows with usable point geometry."},
        {"metric": "assigned_crashes", "value": len(assigned_out), "notes": f"Nearest crash-ready bin within {search_radius_ft} ft."},
        {"metric": "unresolved_crashes", "value": len(unresolved_gdf), "notes": "Outside search radius or ambiguous nearest-bin match."},
        {"metric": "search_radius_ft", "value": search_radius_ft, "notes": "Maximum nearest-bin assignment distance."},
        {
            "metric": "assigned_to_non_crash_ready_segments",
            "value": int((~assigned_out["oriented_segment_id"].isin(segment_ids)).sum()) if not assigned_out.empty else 0,
            "notes": "Expected 0.",
        },
        {
            "metric": "assigned_to_non_crash_ready_bins",
            "value": int((~assigned_out["bin_id"].isin(set(bins["bin_id"]))).sum()) if not assigned_out.empty else 0,
            "notes": "Expected 0.",
        },
        {
            "metric": "true_vehicle_direction_inferred_not_false",
            "value": int(assigned_out["true_vehicle_direction_inferred"].astype(str).str.upper().ne("FALSE").sum()) if not assigned_out.empty else 0,
            "notes": "Expected 0.",
        },
        {
            "metric": "event_direction_unresolved_rows",
            "value": int(assigned_out["event_direction_interpretation"].eq("unresolved").sum()) if not assigned_out.empty else 0,
            "notes": "Direction interpretation is not forced in this prototype.",
        },
        {
            "metric": "upstream_downstream_not_unresolved_when_event_unresolved",
            "value": int(
                (
                    assigned_out["event_direction_interpretation"].eq("unresolved")
                    & ~assigned_out["upstream_downstream_status"].eq("unresolved")
                ).sum()
            )
            if not assigned_out.empty
            else 0,
            "notes": "Expected 0.",
        },
    ]
    _write_csv(pd.DataFrame(summary_rows), review / "crash_assignment_summary.csv")

    def grouped(frame: pd.DataFrame, columns: list[str], count_name: str = "crash_count") -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=[*columns, count_name])
        return frame.groupby(columns, dropna=False).size().reset_index(name=count_name).sort_values(count_name, ascending=False)

    by_direction = pd.concat(
        [
            grouped(assigned_out, ["roadway_directionality_type"]),
            grouped(assigned_out, ["orientation_record_type"]),
            grouped(assigned_out, ["roadway_directionality_type", "direction_match_status"]),
            grouped(assigned_out, ["roadway_directionality_type", "event_direction_interpretation"]),
        ],
        ignore_index=True,
        sort=False,
    )
    _write_csv(by_direction, review / "crash_assignment_by_directionality_type.csv")

    by_bin = pd.concat(
        [
            grouped(assigned_out, ["bin_index"]),
            grouped(assigned_out, ["distance_band"]),
            grouped(assigned_out, ["assignment_confidence"]),
        ],
        ignore_index=True,
        sort=False,
    )
    _write_csv(by_bin, review / "crash_assignment_by_bin_summary.csv")
    _write_csv(grouped(unresolved_gdf, ["unresolved_reason"]), review / "crash_assignment_unresolved_summary.csv")

    problem_rows = []
    if not assigned_out.empty:
        bad = assigned_out.loc[
            (~assigned_out["oriented_segment_id"].isin(segment_ids))
            | (~assigned_out["bin_id"].isin(set(bins["bin_id"])))
            | assigned_out["true_vehicle_direction_inferred"].astype(str).str.upper().ne("FALSE")
            | (
                assigned_out["event_direction_interpretation"].eq("unresolved")
                & ~assigned_out["upstream_downstream_status"].eq("unresolved")
            )
        ].copy()
        if not bad.empty:
            bad["problem_flags"] = "assignment_invariant_failed"
            problem_rows.append(bad)
    problem_frame = pd.concat(problem_rows, ignore_index=True) if problem_rows else pd.DataFrame(columns=["problem_flags"])
    _write_csv(problem_frame, review / "crash_assignment_problem_rows.csv")

    outputs = {
        "assigned_csv": str(tables / "crash_oriented_segment_bin_assignment.csv"),
        "unresolved_csv": str(tables / "crash_oriented_segment_assignment_unresolved.csv"),
        "summary_csv": str(review / "crash_assignment_summary.csv"),
        "assigned_geojson": str(geojson / "crash_assigned_to_oriented_segments.geojson"),
        "unresolved_geojson": str(geojson / "crash_assignment_unresolved.geojson"),
    }
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assign crashes conservatively to Step 5 crash-ready oriented segment bins.")
    parser.add_argument("--normalized-root", type=Path, default=NORMALIZED_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--search-radius-ft", type=float, default=SEARCH_RADIUS_FT)
    args = parser.parse_args(argv)
    outputs = build_crash_assignment(
        normalized_root=args.normalized_root,
        output_root=args.output_root,
        search_radius_ft=args.search_radius_ft,
    )
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
