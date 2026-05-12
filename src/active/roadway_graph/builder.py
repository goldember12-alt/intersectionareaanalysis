from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree


OUTPUT_FOLDER_NAME = "roadway_graph"
TABLES_CURRENT_SUBDIR = ("tables", "current")
REVIEW_CURRENT_SUBDIR = ("review", "current")
REVIEW_GEOJSON_CURRENT_SUBDIR = ("review", "geojson", "current")
RUNS_CURRENT_SUBDIR = ("runs", "current")

FEET_PER_METER = 3.280839895
BIN_LENGTH_FT = 50.0
SIGNAL_ROAD_MATCH_TOLERANCE_FT = 75.0
SNAP_DISTANCE_REVIEW_FT = 50.0
SUSPICIOUS_HIGH_ADJACENT_EDGE_COUNT = 8
MIN_SPLIT_SEPARATION_FT = 5.0

ROAD_FIELDS = [
    "RTE_NM",
    "RTE_ID",
    "EVENT_SOUR",
    "RTE_COMMON",
    "FROM_MEASURE",
    "TO_MEASURE",
    "RTE_FROM_M",
    "RTE_TO_MSR",
    "RIM_FACILI",
    "RIM_MEDIAN",
    "RIM_COUPLE",
    "RTE_CATEGO",
    "RTE_TYPE_N",
    "RTE_RAMP_C",
    "RIM_ACCESS",
    "Stage1_SourceGDB",
    "Stage1_SourceLayer",
]


@dataclass(frozen=True)
class OutputLayout:
    root: Path
    tables_current: Path
    review_current: Path
    review_geojson_current: Path
    runs_current: Path


def _output_subdir(output_dir: Path, *parts: str) -> Path:
    path = output_dir.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_layout(root: Path) -> OutputLayout:
    root.mkdir(parents=True, exist_ok=True)
    return OutputLayout(
        root=root,
        tables_current=_output_subdir(root, *TABLES_CURRENT_SUBDIR),
        review_current=_output_subdir(root, *REVIEW_CURRENT_SUBDIR),
        review_geojson_current=_output_subdir(root, *REVIEW_GEOJSON_CURRENT_SUBDIR),
        runs_current=_output_subdir(root, *RUNS_CURRENT_SUBDIR),
    )


def _write_csv_frame(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _write_geojson_frame(frame: gpd.GeoDataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        return path
    frame.to_file(path, driver="GeoJSON")
    return path


def _write_json_object(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _slugify(raw_value: object) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", str(raw_value).strip()).strip("_").lower()
    return slug or "unknown"


def _clean_text(raw_value: object) -> str | None:
    if raw_value is None or pd.isna(raw_value):
        return None
    text = str(raw_value).strip()
    return text or None


def _leading_code(raw_value: object) -> str:
    text = "" if raw_value is None or pd.isna(raw_value) else str(raw_value)
    match = re.match(r"\s*([0-9]+)", text)
    return match.group(1) if match else ""


def _coord_key(point: Point | tuple[float, float], precision: int = 2) -> str:
    if isinstance(point, Point):
        x = point.x
        y = point.y
    else:
        x, y = point[:2]
    return f"{round(float(x), precision):.{precision}f}_{round(float(y), precision):.{precision}f}"


def _reverse_line(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def _line_endpoint(line: LineString, side: str) -> Point:
    coord = line.coords[0] if side == "start" else line.coords[-1]
    return Point(coord)


def _line_substring(line: LineString, start_m: float, end_m: float) -> LineString:
    low = max(0.0, min(float(start_m), float(end_m)))
    high = min(float(line.length), max(float(start_m), float(end_m)))
    if high <= low:
        point = line.interpolate(low)
        return LineString([point, point])
    segment = substring(line, low, high)
    if isinstance(segment, Point):
        return LineString([segment, segment])
    if not isinstance(segment, LineString):
        return LineString(list(segment.geoms[0].coords))
    return segment


def _azimuth_degrees(from_point: Point, to_point: Point) -> float:
    dx = to_point.x - from_point.x
    dy = to_point.y - from_point.y
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _division_status(row: pd.Series) -> tuple[str, str, str, str, bool, bool]:
    facility_code = _leading_code(row.get("RIM_FACILI"))
    median_code = _leading_code(row.get("RIM_MEDIAN"))
    rim_couple = str(row.get("RIM_COUPLE", "") or "").strip().upper()
    if facility_code in {"2", "4"}:
        status = "divided"
        logical_mode = "divided_source_carriageway"
        is_divided = True
        is_undivided = False
    elif facility_code in {"1", "3"}:
        status = "undivided"
        logical_mode = "undivided_centerline_or_logical_segment"
        is_divided = False
        is_undivided = True
    elif median_code in {"2", "3", "4", "6", "7"} or rim_couple == "Y":
        status = "likely_divided"
        logical_mode = "likely_divided_review"
        is_divided = True
        is_undivided = False
    else:
        status = "unknown"
        logical_mode = "unknown_review"
        is_divided = False
        is_undivided = False
    return status, logical_mode, facility_code, median_code, is_divided, is_undivided


def _signal_id(row_index: int) -> str:
    return f"signal_{row_index:06d}"


def _prepare_roads(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    available_fields = [field for field in ROAD_FIELDS if field in roads.columns]
    prepared = roads[available_fields + ["geometry"]].copy()
    prepared = prepared.loc[prepared.geometry.notna() & ~prepared.geometry.is_empty].copy()
    prepared = prepared.reset_index(names="source_road_row_id")
    exploded = prepared.explode(index_parts=True, ignore_index=False).reset_index(names=["road_source_index", "geometry_part_index"])
    exploded = exploded.loc[exploded.geometry.notna() & ~exploded.geometry.is_empty].copy()
    exploded = exploded.loc[exploded.geometry.geom_type == "LineString"].copy()
    exploded = exploded.reset_index(drop=True)
    exploded["road_component_id"] = [f"rc_{idx:07d}" for idx in exploded.index]
    for column in ("FROM_MEASURE", "TO_MEASURE", "RTE_FROM_M", "RTE_TO_MSR", "Shape_Length"):
        if column in exploded.columns:
            exploded[column] = pd.to_numeric(exploded[column], errors="coerce")
    division = exploded.apply(_division_status, axis=1, result_type="expand")
    division.columns = [
        "roadway_division_status",
        "logical_segment_mode",
        "facility_code",
        "median_code",
        "is_divided_source",
        "is_undivided_source",
    ]
    exploded = pd.concat([exploded, division], axis=1)
    exploded["component_length_ft"] = exploded.geometry.length * FEET_PER_METER
    return gpd.GeoDataFrame(exploded, geometry="geometry", crs=roads.crs)


def _prepare_signals(signals: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    prepared = signals.copy().reset_index(names="source_signal_row_id")
    prepared = prepared.loc[prepared.geometry.notna() & ~prepared.geometry.is_empty].copy()
    prepared["signal_id"] = prepared["source_signal_row_id"].apply(lambda value: _signal_id(int(value)))
    return gpd.GeoDataFrame(prepared, geometry="geometry", crs=signals.crs)


def _associate_signals_to_roads(
    signals: gpd.GeoDataFrame,
    road_components: gpd.GeoDataFrame,
    tolerance_ft: float,
) -> gpd.GeoDataFrame:
    tolerance_m = tolerance_ft / FEET_PER_METER
    tree = STRtree(road_components.geometry.values)
    records: list[dict[str, object]] = []
    geometries: list[Point] = []
    component_lookup = road_components.reset_index(drop=True)

    for signal in signals.itertuples(index=False):
        point = signal.geometry
        candidate_indices = tree.query(point.buffer(tolerance_m), predicate="intersects")
        for component_index in candidate_indices:
            road = component_lookup.iloc[int(component_index)]
            distance_m = road.geometry.distance(point)
            if distance_m > tolerance_m:
                continue
            projection_m = float(road.geometry.project(point))
            snapped = road.geometry.interpolate(projection_m)
            records.append(
                {
                    "signal_id": signal.signal_id,
                    "source_signal_row_id": signal.source_signal_row_id,
                    "road_component_id": road.road_component_id,
                    "source_road_row_id": int(road.source_road_row_id),
                    "match_distance_ft": distance_m * FEET_PER_METER,
                    "projection_m": projection_m,
                    "match_method": "nearby_full_travelway_component_projection",
                    "matched_route_name": _clean_text(road.get("RTE_NM")),
                    "matched_route_common": _clean_text(road.get("RTE_COMMON")),
                    "matched_route_id": _clean_text(road.get("RTE_ID")),
                    "matched_event_source": _clean_text(road.get("EVENT_SOUR")),
                    "roadway_division_status": road.roadway_division_status,
                    "logical_segment_mode": road.logical_segment_mode,
                    "facility_code": road.facility_code,
                    "median_code": road.median_code,
                    "qa_status": "matched_within_tolerance"
                    if distance_m * FEET_PER_METER <= SNAP_DISTANCE_REVIEW_FT
                    else "review_snap_distance_over_50ft",
                }
            )
            geometries.append(snapped)

    if not records:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=signals.crs)
    associations = gpd.GeoDataFrame(records, geometry=geometries, crs=signals.crs)
    associations = associations.sort_values(["signal_id", "match_distance_ft", "road_component_id"]).reset_index(drop=True)
    associations["signal_graph_node_id"] = [
        f"sgn_{_slugify(row.signal_id)}_{_slugify(row.road_component_id)}" for row in associations.itertuples(index=False)
    ]
    return associations


def _endpoint_node_id(endpoint_key: str) -> str:
    return f"rn_{_slugify(endpoint_key)}"


def _build_graph(
    signals: gpd.GeoDataFrame,
    road_components: gpd.GeoDataFrame,
    associations: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    endpoint_records: dict[str, dict[str, object]] = {}
    endpoint_use_counts: dict[str, int] = {}
    for road in road_components.itertuples(index=False):
        for side in ("start", "end"):
            key = _coord_key(_line_endpoint(road.geometry, side))
            endpoint_use_counts[key] = endpoint_use_counts.get(key, 0) + 1

    for road in road_components.itertuples(index=False):
        for side in ("start", "end"):
            point = _line_endpoint(road.geometry, side)
            key = _coord_key(point)
            if key not in endpoint_records:
                endpoint_records[key] = {
                    "graph_node_id": _endpoint_node_id(key),
                    "node_type": "road_intersection" if endpoint_use_counts.get(key, 0) > 1 else "road_endpoint",
                    "signal_id": None,
                    "source_signal_row_id": None,
                    "road_component_id": None,
                    "source_road_row_id": None,
                    "route_name": None,
                    "route_common": None,
                    "route_id": None,
                    "event_source": None,
                    "qa_status": "coordinate_endpoint_shared_by_multiple_components"
                    if endpoint_use_counts.get(key, 0) > 1
                    else "component_endpoint",
                    "geometry": point,
                }

    road_lookup = road_components.set_index("road_component_id", drop=False)
    signal_node_records: dict[str, dict[str, object]] = {}
    edge_records: dict[str, dict[str, object]] = {}
    edge_geometries: dict[str, LineString] = {}
    adjacent_records: list[dict[str, object]] = []
    adjacent_geometries: list[LineString] = []
    min_sep_m = MIN_SPLIT_SEPARATION_FT / FEET_PER_METER

    for assoc in associations.itertuples(index=False):
        signal_node_records[assoc.signal_graph_node_id] = {
            "graph_node_id": assoc.signal_graph_node_id,
            "node_type": "signal",
            "signal_id": assoc.signal_id,
            "source_signal_row_id": assoc.source_signal_row_id,
            "road_component_id": assoc.road_component_id,
            "source_road_row_id": assoc.source_road_row_id,
            "route_name": assoc.matched_route_name,
            "route_common": assoc.matched_route_common,
            "route_id": assoc.matched_route_id,
            "event_source": assoc.matched_event_source,
            "qa_status": assoc.qa_status,
            "geometry": assoc.geometry,
        }

    for signal in signals.itertuples(index=False):
        if signal.signal_id in set(associations["signal_id"]) if not associations.empty else False:
            continue
        node_id = f"unresolved_{_slugify(signal.signal_id)}"
        signal_node_records[node_id] = {
            "graph_node_id": node_id,
            "node_type": "unresolved",
            "signal_id": signal.signal_id,
            "source_signal_row_id": signal.source_signal_row_id,
            "road_component_id": None,
            "source_road_row_id": None,
            "route_name": None,
            "route_common": None,
            "route_id": None,
            "event_source": None,
            "qa_status": "no_full_travelway_component_within_tolerance",
            "geometry": signal.geometry,
        }

    if associations.empty:
        nodes = gpd.GeoDataFrame(list(signal_node_records.values()), geometry="geometry", crs=signals.crs)
        empty_edges = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=signals.crs)
        return nodes, empty_edges, empty_edges.copy(), empty_edges.copy(), empty_edges.copy()

    grouped = associations.groupby("road_component_id", sort=True)
    for road_component_id, group in grouped:
        road = road_lookup.loc[road_component_id]
        line: LineString = road.geometry
        route_name = _clean_text(road.get("RTE_NM"))
        route_common = _clean_text(road.get("RTE_COMMON"))
        route_id = _clean_text(road.get("RTE_ID"))
        event_source = _clean_text(road.get("EVENT_SOUR"))
        group = group.sort_values(["projection_m", "signal_id", "signal_graph_node_id"]).reset_index(drop=True)

        split_points = [
            {
                "projection_m": float(row.projection_m),
                "graph_node_id": row.signal_graph_node_id,
                "signal_id": row.signal_id,
                "geometry": row.geometry,
            }
            for row in group.itertuples(index=False)
        ]
        for split in split_points:
            current_m = split["projection_m"]
            lower_candidates = [candidate for candidate in split_points if candidate["projection_m"] < current_m - min_sep_m]
            higher_candidates = [candidate for candidate in split_points if candidate["projection_m"] > current_m + min_sep_m]
            neighbor_specs: list[tuple[str, float, str, str, Point]] = []
            if lower_candidates:
                lower = max(lower_candidates, key=lambda item: item["projection_m"])
                neighbor_specs.append(("lower_signal", lower["projection_m"], lower["graph_node_id"], "signal", lower["geometry"]))
            elif current_m > min_sep_m:
                endpoint = _line_endpoint(line, "start")
                key = _coord_key(endpoint)
                neighbor_specs.append(("lower_endpoint", 0.0, _endpoint_node_id(key), endpoint_records[key]["node_type"], endpoint))
            if higher_candidates:
                higher = min(higher_candidates, key=lambda item: item["projection_m"])
                neighbor_specs.append(("higher_signal", higher["projection_m"], higher["graph_node_id"], "signal", higher["geometry"]))
            elif line.length - current_m > min_sep_m:
                endpoint = _line_endpoint(line, "end")
                key = _coord_key(endpoint)
                neighbor_specs.append(("higher_endpoint", float(line.length), _endpoint_node_id(key), endpoint_records[key]["node_type"], endpoint))

            for side_label, neighbor_m, neighbor_node_id, neighbor_type, neighbor_point in neighbor_specs:
                low_m = min(current_m, neighbor_m)
                high_m = max(current_m, neighbor_m)
                low_node = split["graph_node_id"] if current_m <= neighbor_m else neighbor_node_id
                high_node = neighbor_node_id if current_m <= neighbor_m else split["graph_node_id"]
                graph_edge_id = f"rge_{_slugify(road_component_id)}_{_slugify(low_node)}_{_slugify(high_node)}"
                edge_geometry = _line_substring(line, low_m, high_m)
                length_ft = edge_geometry.length * FEET_PER_METER
                if graph_edge_id not in edge_records:
                    edge_records[graph_edge_id] = {
                        "graph_edge_id": graph_edge_id,
                        "from_graph_node_id": low_node,
                        "to_graph_node_id": high_node,
                        "route_name": route_name,
                        "route_common": route_common,
                        "route_id": route_id,
                        "event_source": event_source,
                        "road_component_id": road_component_id,
                        "source_road_row_id": int(road.source_road_row_id),
                        "source_geometry_part_index": int(road.geometry_part_index),
                        "from_measure": road.get("FROM_MEASURE"),
                        "to_measure": road.get("TO_MEASURE"),
                        "rte_from_measure": road.get("RTE_FROM_M"),
                        "rte_to_measure": road.get("RTE_TO_MSR"),
                        "facility_code": road.facility_code,
                        "facility_text": _clean_text(road.get("RIM_FACILI")),
                        "median_code": road.median_code,
                        "median_text": _clean_text(road.get("RIM_MEDIAN")),
                        "roadway_division_status": road.roadway_division_status,
                        "logical_segment_mode": road.logical_segment_mode,
                        "is_divided_source": bool(road.is_divided_source),
                        "is_undivided_source": bool(road.is_undivided_source),
                        "rte_category": _clean_text(road.get("RTE_CATEGO")),
                        "rte_type_name": _clean_text(road.get("RTE_TYPE_N")),
                        "rte_ramp_code": _clean_text(road.get("RTE_RAMP_C")),
                        "rim_access": _clean_text(road.get("RIM_ACCESS")),
                        "length_ft": length_ft,
                        "geometry_status": "source_component_substring",
                        "qa_status": "signal_adjacent_graph_edge",
                        "problem_flags": "" if length_ft > 0 else "zero_length",
                        "true_vehicle_direction_inferred": False,
                    }
                    edge_geometries[graph_edge_id] = edge_geometry

                signal_point = split["geometry"]
                adjacent_geometry = edge_geometry
                if Point(adjacent_geometry.coords[0]).distance(signal_point) > Point(adjacent_geometry.coords[-1]).distance(signal_point):
                    adjacent_geometry = _reverse_line(adjacent_geometry)
                adjacent_records.append(
                    {
                        "signal_id": split["signal_id"],
                        "signal_graph_node_id": split["graph_node_id"],
                        "graph_edge_id": graph_edge_id,
                        "adjacent_node_id": neighbor_node_id,
                        "adjacent_node_type": neighbor_type,
                        "adjacent_side_label": side_label,
                        "bearing_degrees": _azimuth_degrees(signal_point, neighbor_point),
                        "route_name": route_name,
                        "route_common": route_common,
                        "route_id": route_id,
                        "event_source": event_source,
                        "road_component_id": road_component_id,
                        "roadway_division_status": road.roadway_division_status,
                        "logical_segment_mode": road.logical_segment_mode,
                        "facility_code": road.facility_code,
                        "median_code": road.median_code,
                        "length_ft": length_ft,
                        "geometry_status": "signal_to_adjacent_anchor_substring",
                        "qa_status": "adjacent_graph_edge",
                        "true_vehicle_direction_inferred": False,
                    }
                )
                adjacent_geometries.append(adjacent_geometry)

    edge_frame = pd.DataFrame(list(edge_records.values()))
    edge_geometry = [edge_geometries[row.graph_edge_id] for row in edge_frame.itertuples(index=False)] if not edge_frame.empty else []
    edges = gpd.GeoDataFrame(edge_frame, geometry=edge_geometry, crs=signals.crs)

    adjacent = gpd.GeoDataFrame(adjacent_records, geometry=adjacent_geometries, crs=signals.crs)
    if not adjacent.empty:
        adjacent = adjacent.sort_values(["signal_id", "bearing_degrees", "graph_edge_id"]).reset_index(drop=True)
        adjacent["leg_index"] = adjacent.groupby("signal_id").cumcount() + 1

    used_endpoint_ids = set()
    if not edges.empty:
        used_endpoint_ids.update(edges["from_graph_node_id"].astype(str).loc[edges["from_graph_node_id"].astype(str).str.startswith("rn_")])
        used_endpoint_ids.update(edges["to_graph_node_id"].astype(str).loc[edges["to_graph_node_id"].astype(str).str.startswith("rn_")])
    endpoint_node_records = [record for record in endpoint_records.values() if record["graph_node_id"] in used_endpoint_ids]
    nodes = gpd.GeoDataFrame(
        [*signal_node_records.values(), *endpoint_node_records],
        geometry="geometry",
        crs=signals.crs,
    )

    signal_graph = associations.copy()
    signal_graph = signal_graph.rename(columns={"signal_graph_node_id": "matched_graph_node_id"})
    signal_graph["snapped_x"] = signal_graph.geometry.x
    signal_graph["snapped_y"] = signal_graph.geometry.y
    matched_signal_ids = set(signal_graph["signal_id"].astype(str))
    unresolved_rows = []
    for signal in signals.itertuples(index=False):
        if signal.signal_id not in matched_signal_ids:
            unresolved_rows.append(
                {
                    "signal_id": signal.signal_id,
                    "source_signal_row_id": signal.source_signal_row_id,
                    "road_component_id": None,
                    "source_road_row_id": None,
                    "match_distance_ft": None,
                    "projection_m": None,
                    "match_method": "no_full_travelway_component_within_tolerance",
                    "matched_route_name": None,
                    "matched_route_common": None,
                    "matched_route_id": None,
                    "matched_event_source": None,
                    "roadway_division_status": None,
                    "logical_segment_mode": None,
                    "facility_code": None,
                    "median_code": None,
                    "qa_status": "review_no_adjacent_road_component",
                    "matched_graph_node_id": f"unresolved_{_slugify(signal.signal_id)}",
                    "snapped_x": signal.geometry.x,
                    "snapped_y": signal.geometry.y,
                    "geometry": signal.geometry,
                }
            )
    if unresolved_rows:
        signal_graph = pd.concat(
            [signal_graph, gpd.GeoDataFrame(unresolved_rows, geometry="geometry", crs=signals.crs)],
            ignore_index=True,
        )
    signal_graph = gpd.GeoDataFrame(signal_graph, geometry="geometry", crs=signals.crs)
    return nodes, edges, signal_graph, adjacent, road_components


def _build_bins(adjacent: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    for row in adjacent.itertuples(index=False):
        length_ft = float(row.length_ft)
        if length_ft <= 0 or row.geometry is None or row.geometry.is_empty:
            continue
        bin_count = max(1, int(math.ceil(length_ft / BIN_LENGTH_FT)))
        for bin_index in range(bin_count):
            start_ft = bin_index * BIN_LENGTH_FT
            end_ft = min(length_ft, (bin_index + 1) * BIN_LENGTH_FT)
            start_m = start_ft / FEET_PER_METER
            end_m = end_ft / FEET_PER_METER
            geometry = _line_substring(row.geometry, start_m, end_m)
            records.append(
                {
                    "bin_id": f"{row.signal_id}_{row.graph_edge_id}_bin_{bin_index:04d}",
                    "signal_id": row.signal_id,
                    "signal_graph_node_id": row.signal_graph_node_id,
                    "graph_edge_id": row.graph_edge_id,
                    "bin_index": bin_index,
                    "bin_start_ft": start_ft,
                    "bin_end_ft": end_ft,
                    "route_name": row.route_name,
                    "route_common": row.route_common,
                    "route_id": row.route_id,
                    "roadway_division_status": row.roadway_division_status,
                    "true_vehicle_direction_inferred": False,
                }
            )
            geometries.append(geometry)
    if not records:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=adjacent.crs)
    return gpd.GeoDataFrame(records, geometry=geometries, crs=adjacent.crs)


def _graph_gap_review(signals: gpd.GeoDataFrame, signal_graph: gpd.GeoDataFrame, adjacent: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    adjacent_counts = adjacent.groupby("signal_id").size().rename("adjacent_edge_count") if not adjacent.empty else pd.Series(dtype="int64")
    branch_counts = signal_graph.loc[signal_graph["qa_status"] != "review_no_adjacent_road_component"].groupby("signal_id").size().rename("matched_branch_count")
    min_dist = pd.to_numeric(signal_graph["match_distance_ft"], errors="coerce").groupby(signal_graph["signal_id"]).min().rename("min_match_distance_ft")
    route_samples = (
        signal_graph.groupby("signal_id")["matched_route_name"]
        .apply(lambda values: " | ".join([str(value) for value in values.dropna().astype(str).drop_duplicates().head(6)]))
        .rename("matched_route_sample")
    )
    rows: list[dict[str, object]] = []
    geometries: list[Point] = []
    for signal in signals.itertuples(index=False):
        count = int(adjacent_counts.get(signal.signal_id, 0))
        branches = int(branch_counts.get(signal.signal_id, 0))
        distance = min_dist.get(signal.signal_id, math.nan)
        issues: list[str] = []
        if count == 0:
            issues.append("zero_adjacent_edges")
        if count == 1:
            issues.append("one_adjacent_edge")
        if count > SUSPICIOUS_HIGH_ADJACENT_EDGE_COUNT:
            issues.append("suspiciously_high_adjacent_edge_count")
        if pd.notna(distance) and float(distance) > SNAP_DISTANCE_REVIEW_FT:
            issues.append("snapped_distance_exceeds_50ft")
        if branches > 1 and count <= 2:
            issues.append("candidate_nearest_roads_not_split_or_intersected_correctly")
        route_sample = route_samples.get(signal.signal_id, "")
        if ("RMP" in str(route_sample).upper() or "IS" in str(route_sample).upper()) and count > 4:
            issues.append("candidate_grade_separation_or_geometry_fragment_issue")
        if not issues:
            continue
        rows.append(
            {
                "signal_id": signal.signal_id,
                "source_signal_row_id": signal.source_signal_row_id,
                "adjacent_edge_count": count,
                "matched_branch_count": branches,
                "min_match_distance_ft": None if pd.isna(distance) else float(distance),
                "issue_flags": ";".join(issues),
                "matched_route_sample": route_sample,
                "qa_status": "review_graph_gap_or_count",
            }
        )
        geometries.append(signal.geometry)
    if not rows:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=signals.crs)
    return gpd.GeoDataFrame(rows, geometry=geometries, crs=signals.crs)


def _summary_tables(
    roads: gpd.GeoDataFrame,
    road_components: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    edges: gpd.GeoDataFrame,
    signal_graph: gpd.GeoDataFrame,
    adjacent: gpd.GeoDataFrame,
    bins: gpd.GeoDataFrame,
    gap_review: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    build_summary = pd.DataFrame(
        [
            {"metric": "normalized_roads_input_rows", "value": len(roads), "notes": "Full Travelway normalized roads; divided and undivided retained."},
            {"metric": "road_components_after_explode", "value": len(road_components), "notes": "LineString components used for prototype graph adjacency."},
            {"metric": "normalized_signal_input_rows", "value": len(signals), "notes": "Signal points from artifacts/normalized/signals.parquet."},
            {"metric": "roadway_graph_node_rows", "value": len(nodes), "notes": "Signal, endpoint, intersection, and unresolved graph nodes."},
            {"metric": "roadway_graph_edge_rows", "value": len(edges), "notes": "Signal-adjacent graph foundation edges."},
            {"metric": "signal_graph_node_rows", "value": len(signal_graph), "notes": "One row per signal-road component association plus unresolved signals."},
            {"metric": "signal_adjacent_edge_rows", "value": len(adjacent), "notes": "One row per edge adjacent to each signal graph node."},
            {"metric": "signal_graph_edge_bin_rows_50ft", "value": len(bins), "notes": "50-foot bins along signal-adjacent graph edge geometry."},
            {"metric": "graph_gap_review_rows", "value": len(gap_review), "notes": "Signals requiring graph QA review."},
            {"metric": "crash_data_used", "value": False, "notes": "Crash data is not read by this workflow."},
            {"metric": "true_vehicle_direction_inferred", "value": False, "notes": "All direction fields remain descriptive/source geometry only."},
        ]
    )

    if adjacent.empty:
        count_summary = pd.DataFrame(columns=["adjacent_edge_count_band", "signal_count"])
    else:
        counts = adjacent.groupby("signal_id").size()
        all_counts = pd.Series(0, index=signals["signal_id"].astype(str))
        all_counts.update(counts)

        def band(value: int) -> str:
            if value == 0:
                return "0"
            if value == 1:
                return "1"
            if value == 2:
                return "2"
            if value in (3, 4):
                return "3-4"
            return "more_than_4"

        count_summary = (
            all_counts.astype(int)
            .map(band)
            .value_counts()
            .rename_axis("adjacent_edge_count_band")
            .reset_index(name="signal_count")
            .sort_values("adjacent_edge_count_band")
        )

    sample_parts = []
    if not adjacent.empty:
        counts = adjacent.groupby("signal_id").size().rename("adjacent_edge_count")
    else:
        counts = pd.Series(dtype="int64", name="adjacent_edge_count")
    signal_base = signals[["signal_id", "source_signal_row_id", "REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "MAJ_NAME", "MINOR_NAME", "geometry"]].copy()
    signal_base["adjacent_edge_count"] = signal_base["signal_id"].map(counts).fillna(0).astype(int)
    signal_base["sample_reason"] = signal_base["adjacent_edge_count"].map(
        lambda value: "zero_adjacent_edges"
        if value == 0
        else "one_adjacent_edge"
        if value == 1
        else "two_adjacent_edges"
        if value == 2
        else "three_to_four_adjacent_edges"
        if value in (3, 4)
        else "more_than_four_adjacent_edges"
    )
    for reason in [
        "zero_adjacent_edges",
        "one_adjacent_edge",
        "two_adjacent_edges",
        "three_to_four_adjacent_edges",
        "more_than_four_adjacent_edges",
    ]:
        sample_parts.append(signal_base.loc[signal_base["sample_reason"] == reason].head(10))
    if not adjacent.empty:
        divided_ids = set(adjacent.loc[adjacent["roadway_division_status"].isin(["divided", "likely_divided"]), "signal_id"].head(10))
        undivided_ids = set(adjacent.loc[adjacent["roadway_division_status"].eq("undivided"), "signal_id"].head(10))
        divided_sample = signal_base.loc[signal_base["signal_id"].isin(divided_ids)].copy()
        divided_sample["sample_reason"] = "divided_roadway_example"
        undivided_sample = signal_base.loc[signal_base["signal_id"].isin(undivided_ids)].copy()
        undivided_sample["sample_reason"] = "undivided_roadway_example"
        sample_parts.extend([divided_sample, undivided_sample])
    sample = pd.concat(sample_parts, ignore_index=True) if sample_parts else signal_base.head(0)
    sample = sample.drop_duplicates(["signal_id", "sample_reason"]).copy()
    return build_summary, count_summary, sample


def _to_csv_frame(frame: gpd.GeoDataFrame | pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns:
        out["geometry"] = frame.geometry.to_wkt() if isinstance(frame, gpd.GeoDataFrame) else out["geometry"]
    return out


def build_roadway_graph(
    *,
    normalized_root: Path,
    output_root: Path,
    signal_road_tolerance_ft: float = SIGNAL_ROAD_MATCH_TOLERANCE_FT,
) -> dict[str, str]:
    layout = _build_layout(output_root)
    roads = gpd.read_parquet(normalized_root / "roads.parquet")
    signals = gpd.read_parquet(normalized_root / "signals.parquet")
    if roads.crs != signals.crs:
        signals = signals.to_crs(roads.crs)

    road_components = _prepare_roads(roads)
    signal_points = _prepare_signals(signals)
    associations = _associate_signals_to_roads(signal_points, road_components, signal_road_tolerance_ft)
    nodes, edges, signal_graph, adjacent, _ = _build_graph(signal_points, road_components, associations)
    bins = _build_bins(adjacent)
    gap_review = _graph_gap_review(signal_points, signal_graph, adjacent)
    divided_candidates = edges.loc[edges["roadway_division_status"].isin(["divided", "likely_divided"])].copy() if not edges.empty else edges.copy()
    undivided_candidates = edges.loc[edges["roadway_division_status"].eq("undivided")].copy() if not edges.empty else edges.copy()
    build_summary, count_summary, sample_review = _summary_tables(
        roads,
        road_components,
        signal_points,
        nodes,
        edges,
        signal_graph,
        adjacent,
        bins,
        gap_review,
    )

    outputs: dict[str, str] = {}
    table_outputs = {
        "roadway_graph_nodes_csv": (nodes, layout.tables_current / "roadway_graph_nodes.csv"),
        "roadway_graph_edges_csv": (edges, layout.tables_current / "roadway_graph_edges.csv"),
        "signal_graph_nodes_csv": (signal_graph, layout.tables_current / "signal_graph_nodes.csv"),
        "signal_adjacent_edges_csv": (adjacent, layout.tables_current / "signal_adjacent_edges.csv"),
        "signal_graph_edge_bins_50ft_csv": (bins, layout.tables_current / "signal_graph_edge_bins_50ft.csv"),
        "graph_gap_review_csv": (gap_review, layout.tables_current / "graph_gap_review.csv"),
        "divided_edge_directional_candidates_csv": (divided_candidates, layout.tables_current / "divided_edge_directional_candidates.csv"),
        "undivided_edge_candidates_csv": (undivided_candidates, layout.tables_current / "undivided_edge_candidates.csv"),
    }
    for key, (frame, path) in table_outputs.items():
        outputs[key] = str(_write_csv_frame(_to_csv_frame(frame), path))

    review_outputs = {
        "graph_build_summary_csv": (build_summary, layout.review_current / "graph_build_summary.csv"),
        "signal_adjacent_edge_count_summary_csv": (count_summary, layout.review_current / "signal_adjacent_edge_count_summary.csv"),
        "sample_signal_graph_review_csv": (sample_review, layout.review_current / "sample_signal_graph_review.csv"),
    }
    for key, (frame, path) in review_outputs.items():
        outputs[key] = str(_write_csv_frame(_to_csv_frame(frame), path))

    geojson_outputs = {
        "roadway_graph_nodes_geojson": (nodes, layout.review_geojson_current / "roadway_graph_nodes.geojson"),
        "roadway_graph_edges_geojson": (edges, layout.review_geojson_current / "roadway_graph_edges.geojson"),
        "signal_graph_nodes_geojson": (signal_graph, layout.review_geojson_current / "signal_graph_nodes.geojson"),
        "signal_adjacent_edges_geojson": (adjacent, layout.review_geojson_current / "signal_adjacent_edges.geojson"),
        "signal_graph_edge_bins_50ft_geojson": (bins, layout.review_geojson_current / "signal_graph_edge_bins_50ft.geojson"),
        "graph_gap_review_geojson": (gap_review, layout.review_geojson_current / "graph_gap_review.geojson"),
        "divided_edge_directional_candidates_geojson": (
            divided_candidates,
            layout.review_geojson_current / "divided_edge_directional_candidates.geojson",
        ),
        "undivided_edge_candidates_geojson": (undivided_candidates, layout.review_geojson_current / "undivided_edge_candidates.geojson"),
    }
    for key, (frame, path) in geojson_outputs.items():
        outputs[key] = str(_write_geojson_frame(frame, path))

    run_summary = {
        "task": "full-roadway signal-adjacent graph foundation prototype",
        "run_timestamp": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "roads": str(normalized_root / "roads.parquet"),
            "signals": str(normalized_root / "signals.parquet"),
            "crash_data_used": False,
        },
        "scope": {
            "roadway_base": "full normalized Travelway roads; divided and undivided retained",
            "directionality": "source geometry order and signal adjacency only; no true vehicle direction inferred",
            "access_points_used": False,
            "crash_assignment_performed": False,
        },
        "parameters": {
            "signal_road_match_tolerance_ft": signal_road_tolerance_ft,
            "bin_length_ft": BIN_LENGTH_FT,
            "snap_distance_review_ft": SNAP_DISTANCE_REVIEW_FT,
        },
        "counts": {row.metric: row.value for row in build_summary.itertuples(index=False)},
        "outputs": outputs,
    }
    outputs["run_summary_json"] = str(_write_json_object(run_summary, layout.runs_current / "run_summary.json"))
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a full-roadway signal-adjacent graph foundation prototype.")
    parser.add_argument("--normalized-root", type=Path, default=Path("artifacts/normalized"))
    parser.add_argument("--output-root", type=Path, default=Path("work/output") / OUTPUT_FOLDER_NAME)
    parser.add_argument("--signal-road-tolerance-ft", type=float, default=SIGNAL_ROAD_MATCH_TOLERANCE_FT)
    args = parser.parse_args(argv)

    outputs = build_roadway_graph(
        normalized_root=args.normalized_root,
        output_root=args.output_root,
        signal_road_tolerance_ft=args.signal_road_tolerance_ft,
    )
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

