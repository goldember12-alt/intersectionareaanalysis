from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import Point


OUTPUT_ROOT = Path("work/output/roadway_graph")
FEET_PER_METER = 3.280839895
SIDE_DISTANCE_TOLERANCE_FT = 6.0
UNDIVIDED_REVIEW_SAMPLE_SIZE = 250


def _read_wkt_csv(path: Path) -> gpd.GeoDataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame["geometry"] = frame["geometry"].map(wkt.loads)
    return gpd.GeoDataFrame(frame, geometry="geometry")


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


def _xy(point: tuple[float, ...]) -> tuple[float, float]:
    return float(point[0]), float(point[1])


def _line_endpoints(geometry) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    if geometry is None or geometry.is_empty or not hasattr(geometry, "coords"):
        return None, None
    coords = list(geometry.coords)
    if len(coords) < 2:
        return None, None
    return _xy(coords[0]), _xy(coords[-1])


def _line_midpoint(geometry) -> Point | None:
    if geometry is None or geometry.is_empty:
        return None
    try:
        return geometry.interpolate(0.5, normalized=True)
    except Exception:
        return None


def _bearing_degrees(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return None
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _signed_side(
    *,
    reference_start: tuple[float, float],
    reference_end: tuple[float, float],
    test_point: Point,
) -> tuple[str, float, float]:
    vx = reference_end[0] - reference_start[0]
    vy = reference_end[1] - reference_start[1]
    wx = test_point.x - reference_start[0]
    wy = test_point.y - reference_start[1]
    length = math.hypot(vx, vy)
    if length == 0:
        return "ambiguous", 0.0, 0.0
    signed = vx * wy - vy * wx
    distance_ft = abs(signed) / length * FEET_PER_METER
    tolerance = SIDE_DISTANCE_TOLERANCE_FT
    if distance_ft <= tolerance:
        return "center", signed, distance_ft
    # In an x-east/y-north plane, positive cross product is left of A->B.
    return ("left" if signed > 0 else "right"), signed, distance_ft


def _canonical_pair(row: pd.Series) -> str:
    return "||".join(sorted([str(row.get("from_anchor_id", "")), str(row.get("to_anchor_id", ""))]))


def _build_direction_groups(segments: gpd.GeoDataFrame) -> pd.Series:
    route = segments.get("route_common", pd.Series("", index=segments.index)).fillna("").astype(str)
    pair = segments.apply(_canonical_pair, axis=1)
    return pair + "||" + route


def _annotate_segments(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = segments.copy()
    for column in out.columns:
        if column != "geometry":
            out[column] = out[column].astype("object")
    out["geometric_direction_family_id"] = _build_direction_groups(out)
    out["reference_vector_bearing"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["reference_vector_length_ft"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["carriageway_side_of_reference"] = pd.Series(["unresolved"] * len(out), index=out.index, dtype=object)
    out["carriageway_side_distance_ft"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["geometric_movement_orientation"] = pd.Series(["unresolved"] * len(out), index=out.index, dtype=object)
    out["centerline_reference_orientation"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["right_side_event_candidate"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["left_side_event_candidate"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["geometric_direction_method"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["geometric_direction_confidence"] = pd.Series(["unresolved"] * len(out), index=out.index, dtype=object)
    out["geometric_direction_status"] = pd.Series(["unresolved"] * len(out), index=out.index, dtype=object)
    out["geometric_direction_problem_reason"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["roadway_geometric_direction_assigned"] = pd.Series([False] * len(out), index=out.index, dtype=object)
    out["true_vehicle_direction_inferred"] = pd.Series([False] * len(out), index=out.index, dtype=object)

    valid_endpoint = []
    for geometry in out.geometry:
        start, end = _line_endpoints(geometry)
        valid_endpoint.append(start is not None and end is not None)
    out["_valid_segment_geometry"] = valid_endpoint

    divided_mask = out["roadway_directionality_type"].eq("divided")
    undivided_mask = out["roadway_directionality_type"].eq("undivided")

    for family_id, group in out.loc[divided_mask].groupby("geometric_direction_family_id", sort=False):
        endpoints = []
        for idx, row in group.iterrows():
            start, end = _line_endpoints(row.geometry)
            if start is not None and end is not None:
                endpoints.append((idx, start, end))

        if not endpoints:
            out.loc[group.index, "geometric_direction_method"] = "divided_right_hand_side_rule"
            out.loc[group.index, "geometric_direction_problem_reason"] = "invalid_or_empty_geometry"
            continue

        # Reciprocal orientation records frequently carry the same physical carriageway in
        # opposite directions. Use one canonical row to define A->B, then classify all
        # candidate carriageways against a family-level midpoint reference.
        canonical_idx, canonical_start, canonical_end = endpoints[0]
        if len(endpoints) > 1:
            starts = []
            ends = []
            for _, start, end in endpoints:
                direct = math.hypot(start[0] - canonical_start[0], start[1] - canonical_start[1]) + math.hypot(
                    end[0] - canonical_end[0],
                    end[1] - canonical_end[1],
                )
                reverse = math.hypot(end[0] - canonical_start[0], end[1] - canonical_start[1]) + math.hypot(
                    start[0] - canonical_end[0],
                    start[1] - canonical_end[1],
                )
                if reverse < direct:
                    start, end = end, start
                starts.append(start)
                ends.append(end)
            reference_start = (sum(p[0] for p in starts) / len(starts), sum(p[1] for p in starts) / len(starts))
            reference_end = (sum(p[0] for p in ends) / len(ends), sum(p[1] for p in ends) / len(ends))
        else:
            reference_start = canonical_start
            reference_end = canonical_end

        bearing = _bearing_degrees(reference_start, reference_end)
        length_ft = math.hypot(reference_end[0] - reference_start[0], reference_end[1] - reference_start[1]) * FEET_PER_METER
        if bearing is None or length_ft == 0:
            out.loc[group.index, "geometric_direction_method"] = "divided_right_hand_side_rule"
            out.loc[group.index, "geometric_direction_problem_reason"] = "zero_length_reference_vector"
            continue

        if len(endpoints) < 2:
            out.loc[group.index, "reference_vector_bearing"] = round(bearing, 3)
            out.loc[group.index, "reference_vector_length_ft"] = round(length_ft, 3)
            out.loc[group.index, "geometric_direction_method"] = "divided_right_hand_side_rule"
            out.loc[group.index, "geometric_direction_problem_reason"] = "single_carriageway_no_side_reference"
            continue

        side_results: list[tuple[object, str, float | None]] = []
        for idx, row in group.iterrows():
            midpoint = _line_midpoint(row.geometry)
            if midpoint is None:
                side_results.append((idx, "ambiguous", None))
                continue
            side, _signed, distance_ft = _signed_side(
                reference_start=reference_start,
                reference_end=reference_end,
                test_point=midpoint,
            )
            side_results.append((idx, side, distance_ft))

        sides_present = {side for _, side, _ in side_results}
        if not {"left", "right"}.issubset(sides_present):
            for idx, side, distance_ft in side_results:
                out.at[idx, "reference_vector_bearing"] = round(bearing, 3)
                out.at[idx, "reference_vector_length_ft"] = round(length_ft, 3)
                out.at[idx, "geometric_direction_method"] = "divided_right_hand_side_rule"
                out.at[idx, "carriageway_side_of_reference"] = side
                out.at[idx, "carriageway_side_distance_ft"] = "" if distance_ft is None else round(distance_ft, 3)
                if side == "center":
                    out.at[idx, "geometric_direction_problem_reason"] = "geometry_too_close_to_reference_line"
                elif side in {"left", "right"}:
                    out.at[idx, "geometric_direction_problem_reason"] = "candidate_geometries_do_not_bracket_reference"
                else:
                    out.at[idx, "geometric_direction_problem_reason"] = "side_of_reference_ambiguous"
            continue

        for idx, row in group.iterrows():
            midpoint = _line_midpoint(row.geometry)
            out.at[idx, "reference_vector_bearing"] = round(bearing, 3)
            out.at[idx, "reference_vector_length_ft"] = round(length_ft, 3)
            out.at[idx, "geometric_direction_method"] = "divided_right_hand_side_rule"
            if midpoint is None:
                out.at[idx, "geometric_direction_problem_reason"] = "invalid_or_empty_geometry"
                continue
            side, _signed, distance_ft = _signed_side(
                reference_start=reference_start,
                reference_end=reference_end,
                test_point=midpoint,
            )
            out.at[idx, "carriageway_side_of_reference"] = side
            out.at[idx, "carriageway_side_distance_ft"] = round(distance_ft, 3)
            if side == "right":
                out.at[idx, "geometric_movement_orientation"] = "A_to_B"
                out.at[idx, "geometric_direction_confidence"] = "high" if len(endpoints) > 1 else "medium"
                out.at[idx, "geometric_direction_status"] = "assigned"
                out.at[idx, "roadway_geometric_direction_assigned"] = True
            elif side == "left":
                out.at[idx, "geometric_movement_orientation"] = "B_to_A"
                out.at[idx, "geometric_direction_confidence"] = "high" if len(endpoints) > 1 else "medium"
                out.at[idx, "geometric_direction_status"] = "assigned"
                out.at[idx, "roadway_geometric_direction_assigned"] = True
            elif side == "center":
                out.at[idx, "geometric_direction_problem_reason"] = "geometry_too_close_to_reference_line"
            else:
                out.at[idx, "geometric_direction_problem_reason"] = "side_of_reference_ambiguous"

    for idx, row in out.loc[undivided_mask].iterrows():
        start, end = _line_endpoints(row.geometry)
        out.at[idx, "geometric_direction_method"] = "undivided_centerline_side_rule"
        out.at[idx, "centerline_reference_orientation"] = "A_to_B"
        out.at[idx, "right_side_event_candidate"] = "A_to_B"
        out.at[idx, "left_side_event_candidate"] = "B_to_A"
        out.at[idx, "carriageway_side_of_reference"] = "centerline"
        out.at[idx, "geometric_movement_orientation"] = "unresolved"
        out.at[idx, "roadway_geometric_direction_assigned"] = False
        out.at[idx, "physical_directional_carriageway"] = False
        out.at[idx, "undivided_event_direction_requires_crash_direction"] = True
        if start is None or end is None:
            out.at[idx, "geometric_direction_status"] = "problem"
            out.at[idx, "geometric_direction_problem_reason"] = "invalid_or_empty_geometry"
            continue
        bearing = _bearing_degrees(start, end)
        length_ft = math.hypot(end[0] - start[0], end[1] - start[1]) * FEET_PER_METER
        out.at[idx, "reference_vector_bearing"] = "" if bearing is None else round(bearing, 3)
        out.at[idx, "reference_vector_length_ft"] = round(length_ft, 3)
        out.at[idx, "geometric_direction_confidence"] = "medium"
        out.at[idx, "geometric_direction_status"] = "prepared_for_centerline_side_interpretation"

    unknown_mask = ~(divided_mask | undivided_mask)
    out.loc[unknown_mask, "geometric_direction_method"] = "unresolved_unknown_directionality"
    out.loc[unknown_mask, "geometric_direction_problem_reason"] = "unknown_roadway_directionality_type"

    out = out.drop(columns=["_valid_segment_geometry"])
    return out


def _annotate_bins(bins: gpd.GeoDataFrame, segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    direction_cols = [
        "oriented_segment_id",
        "reference_signal_id",
        "opposite_anchor_type",
        "opposite_anchor_id",
        "geometric_direction_family_id",
        "reference_vector_bearing",
        "carriageway_side_of_reference",
        "carriageway_side_distance_ft",
        "geometric_movement_orientation",
        "centerline_reference_orientation",
        "right_side_event_candidate",
        "left_side_event_candidate",
        "geometric_direction_method",
        "geometric_direction_confidence",
        "geometric_direction_status",
        "geometric_direction_problem_reason",
        "roadway_geometric_direction_assigned",
    ]
    merged = bins.merge(
        pd.DataFrame(segments[direction_cols]),
        on="oriented_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    merged["true_vehicle_direction_inferred"] = False
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=bins.crs)


def _summary(segments: gpd.GeoDataFrame, bins: gpd.GeoDataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    divided = segments.loc[segments["roadway_directionality_type"].eq("divided")]
    undivided = segments.loc[segments["roadway_directionality_type"].eq("undivided")]
    add("crash_data_read", False, "This module reads only crash-ready Step 5 segment/bin outputs and roadway graph candidate tables.")
    add("geometric_direction_segment_rows", len(segments), "Crash-ready oriented segment rows annotated with geometric direction fields.")
    add("geometric_direction_bin_rows", len(bins), "Crash-ready 50-foot bin rows annotated from their parent segment.")
    add("divided_segment_rows", len(divided), "")
    add("undivided_segment_rows", len(undivided), "")
    for orientation, count in divided["geometric_movement_orientation"].value_counts(dropna=False).sort_index().items():
        add(f"divided_geometric_movement_orientation_{orientation}", int(count), "")
    add(
        "divided_families_with_both_A_to_B_and_B_to_A",
        int(
            divided.groupby("geometric_direction_family_id")["geometric_movement_orientation"]
            .agg(lambda values: {"A_to_B", "B_to_A"}.issubset(set(values)))
            .sum()
        )
        if not divided.empty
        else 0,
        "Uses derived anchor-pair/route geometry direction families.",
    )
    add(
        "divided_families_with_ambiguous_or_center_side",
        int(
            divided.groupby("geometric_direction_family_id")["carriageway_side_of_reference"]
            .agg(lambda values: any(value in {"ambiguous", "center", "unresolved"} for value in values))
            .sum()
        )
        if not divided.empty
        else 0,
        "",
    )
    add(
        "undivided_rows_prepared_for_centerline_side_interpretation",
        int(undivided["geometric_direction_status"].eq("prepared_for_centerline_side_interpretation").sum()),
        "Undivided roads remain one logical centerline, not duplicated directional carriageways.",
    )
    add(
        "undivided_physical_directional_carriageway_violations",
        int(undivided["physical_directional_carriageway"].astype(str).str.lower().eq("true").sum()),
        "",
    )
    add(
        "true_vehicle_direction_inferred_not_false",
        int(segments["true_vehicle_direction_inferred"].astype(str).str.lower().ne("false").sum()),
        "Hard check should remain zero.",
    )
    add(
        "problem_rows",
        int(segments["geometric_direction_problem_reason"].astype(str).ne("").sum()),
        "Rows where side cannot be assigned, geometry is too close to the reference line, or directionality is unknown.",
    )
    add(
        "too_close_to_reference_line_rows",
        int(segments["geometric_direction_problem_reason"].eq("geometry_too_close_to_reference_line").sum()),
        "",
    )
    return pd.DataFrame(rows)


def _divided_pairing_summary(segments: gpd.GeoDataFrame) -> pd.DataFrame:
    divided = segments.loc[segments["roadway_directionality_type"].eq("divided")].copy()
    if divided.empty:
        return pd.DataFrame()
    grouped = divided.groupby("geometric_direction_family_id", dropna=False)
    rows = []
    for family_id, group in grouped:
        orientations = set(group["geometric_movement_orientation"])
        sides = set(group["carriageway_side_of_reference"])
        rows.append(
            {
                "geometric_direction_family_id": family_id,
                "segment_family_count": int(group["segment_family_id"].nunique()),
                "oriented_segment_count": len(group),
                "route_common": " | ".join(sorted(set(group.get("route_common", pd.Series("", index=group.index)).astype(str)))[:4]),
                "reference_signal_count": int(group["reference_signal_id"].nunique()),
                "A_to_B_rows": int(group["geometric_movement_orientation"].eq("A_to_B").sum()),
                "B_to_A_rows": int(group["geometric_movement_orientation"].eq("B_to_A").sum()),
                "unresolved_rows": int(group["geometric_movement_orientation"].eq("unresolved").sum()),
                "has_both_A_to_B_and_B_to_A": {"A_to_B", "B_to_A"}.issubset(orientations),
                "has_ambiguous_or_center_side": any(side in {"ambiguous", "center", "unresolved"} for side in sides),
                "problem_reasons": " | ".join(
                    sorted(reason for reason in set(group["geometric_direction_problem_reason"].astype(str)) if reason)
                ),
            }
        )
    return pd.DataFrame(rows)


def _undivided_centerline_summary(segments: gpd.GeoDataFrame) -> pd.DataFrame:
    undivided = segments.loc[segments["roadway_directionality_type"].eq("undivided")].copy()
    if undivided.empty:
        return pd.DataFrame()
    return (
        undivided.groupby(["geometric_direction_status", "geometric_direction_confidence"], dropna=False)
        .size()
        .reset_index(name="segment_rows")
        .sort_values(["geometric_direction_status", "geometric_direction_confidence"])
    )


def _problem_rows(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mask = segments["geometric_direction_problem_reason"].astype(str).ne("")
    return segments.loc[mask].copy()


def build_geometric_direction_model(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    geojson = output_root / "review/geojson/current"

    # Read roadway graph candidate tables to keep the input contract explicit. They are
    # not used to infer direction beyond confirming that this model stays in the
    # roadway-geometry output family.
    divided_candidates_path = tables / "divided_edge_directional_candidates.csv"
    undivided_candidates_path = tables / "undivided_edge_candidates.csv"
    divided_candidate_rows = len(pd.read_csv(divided_candidates_path, usecols=["graph_edge_id"], dtype=str)) if divided_candidates_path.exists() else 0
    undivided_candidate_rows = len(pd.read_csv(undivided_candidates_path, usecols=["graph_edge_id"], dtype=str)) if undivided_candidates_path.exists() else 0

    segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_crash_ready.csv")
    bins = _read_wkt_csv(tables / "signal_oriented_segment_bins_50ft_crash_ready.csv")

    segment_direction = _annotate_segments(segments)
    bin_direction = _annotate_bins(bins, segment_direction)

    summary = _summary(segment_direction, bin_direction)
    summary = pd.concat(
        [
            summary,
            pd.DataFrame(
                [
                    {
                        "metric": "divided_edge_directional_candidate_rows_read",
                        "value": divided_candidate_rows,
                        "notes": "Roadway graph candidate table read for input-contract verification; crash records are not read.",
                    },
                    {
                        "metric": "undivided_edge_candidate_rows_read",
                        "value": undivided_candidate_rows,
                        "notes": "Roadway graph candidate table read for input-contract verification; crash records are not read.",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )

    divided_pairing = _divided_pairing_summary(segment_direction)
    undivided_summary = _undivided_centerline_summary(segment_direction)
    problems = _problem_rows(segment_direction)

    _write_csv(segment_direction, tables / "signal_oriented_roadway_segments_geometric_direction.csv")
    _write_csv(bin_direction, tables / "signal_oriented_segment_bins_geometric_direction.csv")
    _write_csv(summary, review / "geometric_direction_summary.csv")
    _write_csv(divided_pairing, review / "geometric_direction_divided_pairing_summary.csv")
    _write_csv(undivided_summary, review / "geometric_direction_undivided_centerline_summary.csv")
    _write_csv(problems, review / "geometric_direction_problem_rows.csv")

    divided_review = problems.loc[problems["roadway_directionality_type"].eq("divided")].copy()
    undivided_review = segment_direction.loc[segment_direction["roadway_directionality_type"].eq("undivided")].head(
        UNDIVIDED_REVIEW_SAMPLE_SIZE
    )
    _write_geojson(gpd.GeoDataFrame(divided_review, geometry="geometry"), geojson / "geometric_direction_divided_review.geojson")
    _write_geojson(
        gpd.GeoDataFrame(undivided_review, geometry="geometry"),
        geojson / "geometric_direction_undivided_review.geojson",
    )

    return {
        "segments_csv": str(tables / "signal_oriented_roadway_segments_geometric_direction.csv"),
        "bins_csv": str(tables / "signal_oriented_segment_bins_geometric_direction.csv"),
        "summary_csv": str(review / "geometric_direction_summary.csv"),
        "problem_rows_csv": str(review / "geometric_direction_problem_rows.csv"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build roadway-geometry-derived direction fields for Step 5 crash-ready segments.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_geometric_direction_model(output_root=args.output_root)
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
