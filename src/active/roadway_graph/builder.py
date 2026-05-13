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


def _adjacent_count_band(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    if value in (3, 4):
        return "3-4"
    return "more_than_4"


def _normalize_manual_signal_id(raw_value: object) -> str:
    text = "" if raw_value is None or pd.isna(raw_value) else str(raw_value).strip()
    if text.startswith("signal_"):
        return text
    if re.fullmatch(r"\d+", text):
        return _signal_id(int(text))
    return text


def _source_signal_id(row: pd.Series) -> object:
    for column in ("source_signal_id", "REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "source_signal_row_id"):
        if column in row.index:
            value = row.get(column)
            if value is not None and not pd.isna(value) and str(value).strip():
                return value
    return None


def _read_manual_signal_diagnosis(review_current: Path) -> pd.DataFrame:
    path = review_current / "manual_review_signal_classification.csv"
    if not path.exists():
        return pd.DataFrame()
    manual = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "signal_id" not in manual.columns:
        return pd.DataFrame()
    manual = manual.copy()
    manual["signal_id"] = manual["signal_id"].map(_normalize_manual_signal_id)
    return manual


def _bool_text(value: object) -> bool:
    return str(value).strip().upper() == "TRUE"


def _build_signal_step5_eligibility(
    signals: gpd.GeoDataFrame,
    adjacent: gpd.GeoDataFrame,
    gap_review: gpd.GeoDataFrame,
    manual: pd.DataFrame,
) -> gpd.GeoDataFrame:
    adjacent_counts = adjacent.groupby("signal_id").size().rename("observed_adjacent_edge_count") if not adjacent.empty else pd.Series(dtype="int64")
    if adjacent.empty:
        divided_counts = pd.Series(dtype="int64", name="observed_divided_edge_count")
        undivided_counts = pd.Series(dtype="int64", name="observed_undivided_edge_count")
    else:
        divided_counts = (
            adjacent.loc[adjacent["roadway_division_status"].isin(["divided", "likely_divided"])]
            .groupby("signal_id")
            .size()
            .rename("observed_divided_edge_count")
        )
        undivided_counts = (
            adjacent.loc[adjacent["roadway_division_status"].eq("undivided")]
            .groupby("signal_id")
            .size()
            .rename("observed_undivided_edge_count")
        )

    gap_lookup = {}
    if not gap_review.empty:
        for row in gap_review.itertuples(index=False):
            gap_lookup[str(row.signal_id)] = {
                "issue_flags": str(getattr(row, "issue_flags", "") or ""),
                "matched_branch_count": getattr(row, "matched_branch_count", ""),
                "min_match_distance_ft": getattr(row, "min_match_distance_ft", ""),
            }

    manual_lookup = {}
    if not manual.empty:
        for row in manual.itertuples(index=False):
            row_dict = row._asdict()
            manual_lookup[str(row_dict.get("signal_id", ""))] = row_dict

    records: list[dict[str, object]] = []
    geometries: list[Point] = []
    for signal in signals.itertuples(index=False):
        signal_id = str(signal.signal_id)
        count = int(adjacent_counts.get(signal_id, 0))
        divided_count = int(divided_counts.get(signal_id, 0))
        undivided_count = int(undivided_counts.get(signal_id, 0))
        gap = gap_lookup.get(signal_id, {})
        manual_row = manual_lookup.get(signal_id, {})
        manual_class = str(manual_row.get("primary_diagnosis", "") or "")

        source_complete = "TRUE"
        usable = "TRUE"
        exclusion_reason = ""
        manual_promotion_allowed = "FALSE"
        requires_manual_review = "FALSE"
        notes: list[str] = []

        if count == 0:
            source_complete = "FALSE"
            usable = "FALSE"
            exclusion_reason = "adjacent_leg_count_zero"
            manual_promotion_allowed = "TRUE"
            requires_manual_review = "TRUE"
            notes.append("Zero adjacent graph edges; excluded by default before Step 5.")
        elif count == 1:
            source_complete = "FALSE"
            usable = "FALSE"
            exclusion_reason = "adjacent_leg_count_one"
            manual_promotion_allowed = "TRUE"
            requires_manual_review = "TRUE"
            notes.append("One adjacent graph edge; excluded by default before Step 5.")
        elif count == 2:
            source_complete = "UNKNOWN"
            usable = "CONDITIONAL"
            exclusion_reason = "two_edge_suspect_review_required"
            manual_promotion_allowed = "TRUE"
            requires_manual_review = "TRUE"
            notes.append("Two-edge signal; suspect unless confirmed as a valid two-legged or one-roadway analysis case.")
        elif count > 4:
            source_complete = "UNKNOWN"
            usable = "CONDITIONAL"
            exclusion_reason = "high_adjacent_edge_count_review_required"
            manual_promotion_allowed = "TRUE"
            requires_manual_review = "TRUE"
            notes.append("More than four adjacent graph edges; review required before Step 5.")

        if gap:
            issue_flags = str(gap.get("issue_flags", "") or "")
            if usable == "TRUE":
                source_complete = "UNKNOWN"
                usable = "CONDITIONAL"
                exclusion_reason = "graph_gap_review_required"
                manual_promotion_allowed = "TRUE"
                requires_manual_review = "TRUE"
            notes.append(f"Graph gap/count review flags: {issue_flags}.")

        if manual_row:
            manual_note = str(manual_row.get("manual_notes", "") or "")
            if manual_note:
                notes.append(f"Manual review: {manual_note}")
            if _bool_text(manual_row.get("source_roadway_incomplete", "")):
                source_complete = "FALSE"
                usable = "FALSE"
                exclusion_reason = "source_roadway_incomplete"
                manual_promotion_allowed = "TRUE"
                requires_manual_review = "TRUE"
            elif _bool_text(manual_row.get("signal_location_questionable", "")):
                source_complete = "UNKNOWN"
                usable = "FALSE"
                exclusion_reason = "signal_location_questionable"
                manual_promotion_allowed = "TRUE"
                requires_manual_review = "TRUE"
            elif _bool_text(manual_row.get("edge_termination_too_far", "")):
                if usable != "FALSE":
                    source_complete = "TRUE" if source_complete == "TRUE" else source_complete
                    usable = "CONDITIONAL"
                    exclusion_reason = "edge_termination_rule_unresolved"
                    manual_promotion_allowed = "TRUE"
                    requires_manual_review = "TRUE"

        if usable == "TRUE":
            notes.append("Eligible for future Step 5 input gating; no true vehicle direction is inferred.")

        signal_series = pd.Series(signal._asdict())
        records.append(
            {
                "signal_id": signal_id,
                "source_signal_id": _source_signal_id(signal_series),
                "source_signal_row_id": getattr(signal, "source_signal_row_id", None),
                "observed_adjacent_edge_count": count,
                "observed_divided_edge_count": divided_count,
                "observed_undivided_edge_count": undivided_count,
                "adjacent_edge_count_band": _adjacent_count_band(count),
                "graph_gap_flag": "TRUE" if gap else "FALSE",
                "graph_gap_issue_flags": str(gap.get("issue_flags", "") or ""),
                "source_roadway_complete_enough": source_complete,
                "usable_for_step5": usable,
                "step5_exclusion_reason": exclusion_reason,
                "manual_review_status": str(manual_row.get("manual_review_status", "") or ""),
                "manual_diagnosis_class": manual_class,
                "manual_promotion_allowed": manual_promotion_allowed,
                "requires_manual_review": requires_manual_review,
                "notes": " ".join(notes),
            }
        )
        geometries.append(signal.geometry)

    return gpd.GeoDataFrame(records, geometry=geometries, crs=signals.crs)


def _node_type_lookup(nodes: gpd.GeoDataFrame) -> dict[str, str]:
    if nodes.empty:
        return {}
    return {str(row.graph_node_id): str(row.node_type) for row in nodes.itertuples(index=False)}


def _edge_anchor_type(from_type: str, to_type: str) -> str:
    types = [from_type, to_type]
    if types.count("signal") == 2:
        return "signal_to_signal"
    if "road_intersection" in types:
        return "road_intersection"
    if "road_endpoint" in types:
        return "road_endpoint"
    if "signal" in types:
        return "signal"
    return "unknown"


def _edge_termination_status(anchor_type: str) -> str:
    if anchor_type == "signal_to_signal":
        return "valid_signal_anchor"
    if anchor_type == "road_intersection":
        return "valid_non_signalized_intersection_anchor"
    if anchor_type == "road_endpoint":
        return "valid_roadway_endpoint_anchor"
    return "unresolved"


def _roadway_directionality_type(status: object) -> str:
    text = str(status or "").strip()
    if text in {"divided", "likely_divided"}:
        return "divided"
    if text == "undivided":
        return "undivided"
    return "unknown"


def _build_edges_eligible(
    edges: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    adjacent: gpd.GeoDataFrame,
    signal_eligibility: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if edges.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=nodes.crs if not nodes.empty else None)

    signal_status = signal_eligibility[["signal_id", "usable_for_step5", "step5_exclusion_reason", "requires_manual_review"]].copy()
    if adjacent.empty:
        edge_signal_summary = pd.DataFrame(columns=["graph_edge_id", "adjacent_step5_signal_ids", "edge_signal_usable_for_step5", "edge_signal_reasons"])
    else:
        edge_signal_rows = pd.DataFrame(adjacent[["graph_edge_id", "signal_id"]].drop_duplicates()).merge(signal_status, on="signal_id", how="left")

        def summarize_signal_status(group: pd.DataFrame) -> pd.Series:
            statuses = set(group["usable_for_step5"].fillna("FALSE").astype(str))
            if "TRUE" in statuses:
                usable = "TRUE"
            elif "CONDITIONAL" in statuses:
                usable = "CONDITIONAL"
            else:
                usable = "FALSE"
            reasons = sorted({str(value) for value in group["step5_exclusion_reason"].fillna("").astype(str) if str(value)})
            if not reasons and usable == "FALSE":
                reasons = ["no_eligible_adjacent_signal"]
            return pd.Series(
                {
                    "adjacent_step5_signal_ids": ";".join(sorted(group["signal_id"].astype(str).unique())),
                    "edge_signal_usable_for_step5": usable,
                    "edge_signal_reasons": ";".join(reasons),
                }
            )

        edge_signal_summary = edge_signal_rows.groupby("graph_edge_id", sort=False).apply(summarize_signal_status).reset_index()

    node_types = _node_type_lookup(nodes)
    frame = edges.copy()
    frame["from_node_id"] = frame["from_graph_node_id"]
    frame["to_node_id"] = frame["to_graph_node_id"]
    frame["from_node_type"] = frame["from_node_id"].astype(str).map(node_types).fillna("unknown")
    frame["to_node_type"] = frame["to_node_id"].astype(str).map(node_types).fillna("unknown")
    frame["roadway_directionality_type"] = frame["roadway_division_status"].map(_roadway_directionality_type)
    frame["edge_termination_anchor_type"] = [
        _edge_anchor_type(from_type, to_type) for from_type, to_type in zip(frame["from_node_type"], frame["to_node_type"])
    ]
    frame["edge_termination_status"] = frame["edge_termination_anchor_type"].map(_edge_termination_status)
    frame["intermediate_intersection_crossed_flag"] = "UNKNOWN"
    frame["intermediate_intersection_crossed_note"] = "Not derivable from current graph output; future termination logic must test first valid roadway-network anchor."
    frame = frame.merge(edge_signal_summary, on="graph_edge_id", how="left")
    frame["usable_for_step5"] = frame["edge_signal_usable_for_step5"].fillna("FALSE")
    frame["step5_exclusion_reason"] = frame["edge_signal_reasons"].fillna("no_eligible_adjacent_signal")
    frame.loc[frame["usable_for_step5"].eq("TRUE"), "step5_exclusion_reason"] = ""
    frame["requires_manual_review"] = frame["usable_for_step5"].map(lambda value: "FALSE" if value == "TRUE" else "TRUE")
    frame["adjacent_step5_signal_ids"] = frame["adjacent_step5_signal_ids"].fillna("")

    required = [
        "graph_edge_id",
        "from_node_id",
        "to_node_id",
        "roadway_directionality_type",
        "edge_termination_status",
        "edge_termination_anchor_type",
        "intermediate_intersection_crossed_flag",
        "usable_for_step5",
        "step5_exclusion_reason",
        "requires_manual_review",
        "adjacent_step5_signal_ids",
        "route_name",
        "route_common",
        "road_component_id",
        "roadway_division_status",
        "length_ft",
        "geometry",
    ]
    available = [column for column in required if column in frame.columns]
    return gpd.GeoDataFrame(frame[available].copy(), geometry="geometry", crs=edges.crs)


def _step5_summary(signal_eligibility: gpd.GeoDataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add_counts(group_name: str, column: str) -> None:
        counts = signal_eligibility[column].fillna("").astype(str).replace("", "blank").value_counts(dropna=False)
        for value, count in counts.items():
            rows.append({"summary_group": group_name, "summary_value": value, "signal_count": int(count)})

    add_counts("usable_for_step5", "usable_for_step5")
    add_counts("step5_exclusion_reason", "step5_exclusion_reason")
    add_counts("source_roadway_complete_enough", "source_roadway_complete_enough")
    add_counts("manual_diagnosis_class", "manual_diagnosis_class")
    add_counts("adjacent_edge_count_band", "adjacent_edge_count_band")
    return pd.DataFrame(rows)


def _termination_anchor_type(node_type: object) -> str:
    text = str(node_type or "")
    if text == "signal":
        return "signalized_intersection"
    if text == "road_intersection":
        return "non_signalized_roadway_intersection"
    if text == "road_endpoint":
        return "road_endpoint_dead_end"
    return "unresolved_cutoff"


def _termination_status(anchor_type: str, refined: bool) -> str:
    if refined and anchor_type == "non_signalized_roadway_intersection":
        return "refined_to_first_non_signalized_intersection"
    if anchor_type == "signalized_intersection":
        return "terminated_at_signalized_intersection"
    if anchor_type == "non_signalized_roadway_intersection":
        return "terminated_at_non_signalized_roadway_intersection"
    if anchor_type == "road_endpoint_dead_end":
        return "terminated_at_road_endpoint_dead_end"
    return "unresolved_or_cutoff_review_only"


def _manual_termination_issue_signal_ids(review_current: Path) -> set[str]:
    path = review_current / "manual_review_signal_classification.csv"
    if not path.exists():
        return set()
    manual = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not {"signal_id", "edge_termination_too_far"}.issubset(manual.columns):
        return set()
    rows = manual.loc[manual["edge_termination_too_far"].astype(str).str.upper().eq("TRUE")]
    return {_normalize_manual_signal_id(value) for value in rows["signal_id"]}


def _refine_signal_adjacent_edge_termination(
    adjacent: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    *,
    review_current: Path,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    if adjacent.empty:
        empty = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=adjacent.crs)
        return empty, empty.copy(), empty.copy()

    intersection_nodes = nodes.loc[nodes["node_type"].eq("road_intersection")].copy() if not nodes.empty else nodes.head(0).copy()
    node_lookup = {str(row.graph_node_id): row for row in nodes.itertuples(index=False)} if not nodes.empty else {}
    manual_issue_ids = _manual_termination_issue_signal_ids(review_current)
    tolerance_m = 3.0 / FEET_PER_METER
    min_interior_m = MIN_SPLIT_SEPARATION_FT / FEET_PER_METER
    short_fragment_ft = 25.0

    if not intersection_nodes.empty:
        intersection_nodes = intersection_nodes.reset_index(drop=True)
        tree = STRtree(intersection_nodes.geometry.values)
    else:
        tree = None

    adjacent_records: list[dict[str, object]] = []
    adjacent_geometries: list[LineString] = []
    edge_records: list[dict[str, object]] = []
    edge_geometries: list[LineString] = []
    example_records: list[dict[str, object]] = []

    def first_intersection(line: LineString, current_anchor_id: str) -> tuple[str, Point, float] | None:
        if tree is None or line.length <= min_interior_m * 2:
            return None
        candidate_indices = tree.query(line.buffer(tolerance_m), predicate="intersects")
        candidates: list[tuple[float, str, Point]] = []
        for idx in candidate_indices:
            node = intersection_nodes.iloc[int(idx)]
            node_id = str(node.graph_node_id)
            if node_id == current_anchor_id:
                continue
            point = node.geometry
            if line.distance(point) > tolerance_m:
                continue
            projection_m = float(line.project(point))
            if projection_m <= min_interior_m or projection_m >= line.length - min_interior_m:
                continue
            candidates.append((projection_m, node_id, point))
        if not candidates:
            return None
        projection_m, node_id, point = min(candidates, key=lambda item: item[0])
        return node_id, point, projection_m

    for row in adjacent.itertuples(index=False):
        row_dict = row._asdict()
        line = row.geometry
        current_anchor_id = str(row_dict.get("adjacent_node_id", ""))
        current_node = node_lookup.get(current_anchor_id)
        current_node_type = str(getattr(current_node, "node_type", row_dict.get("adjacent_node_type", "")) or "")
        current_anchor_type = _termination_anchor_type(current_node_type)
        first_anchor = first_intersection(line, current_anchor_id)

        pre_length_ft = float(row_dict.get("length_ft") or 0.0)
        refined = first_anchor is not None
        if refined:
            anchor_id, _anchor_point, projection_m = first_anchor
            refined_line = _line_substring(line, 0.0, projection_m)
            anchor_type = "non_signalized_roadway_intersection"
            anchor_node_type = "road_intersection"
            reason = "first_existing_road_intersection_node_along_signal_adjacent_edge"
        else:
            anchor_id = current_anchor_id
            refined_line = line
            anchor_type = current_anchor_type
            anchor_node_type = current_node_type
            reason = "current_endpoint_is_first_supported_graph_anchor_or_no_supported_intermediate_intersection_found"

        post_length_ft = refined_line.length * FEET_PER_METER
        zero_length = post_length_ft <= 1.0
        suspicious_short = 1.0 < post_length_ft < short_fragment_ft
        new_suspicious_short = refined and pre_length_ft >= short_fragment_ft and post_length_ft < short_fragment_ft
        refined_edge_id = f"rget_{_slugify(row.signal_id)}_{_slugify(row.graph_edge_id)}"
        termination_status = _termination_status(anchor_type, refined)
        requires_review = bool(zero_length or suspicious_short)
        remaining_crossed = False
        remaining_anchor = first_intersection(refined_line, str(anchor_id))
        if remaining_anchor is not None:
            remaining_crossed = True
            requires_review = True

        adjacent_out = dict(row_dict)
        adjacent_out["original_graph_edge_id"] = row.graph_edge_id
        adjacent_out["graph_edge_id"] = refined_edge_id
        adjacent_out["refined_edge_id"] = refined_edge_id
        adjacent_out["adjacent_node_id"] = anchor_id
        adjacent_out["adjacent_node_type"] = anchor_node_type
        adjacent_out["pre_refinement_length_ft"] = pre_length_ft
        adjacent_out["post_refinement_length_ft"] = post_length_ft
        adjacent_out["length_ft"] = post_length_ft
        adjacent_out["edge_termination_status"] = termination_status
        adjacent_out["edge_termination_anchor_type"] = anchor_type
        adjacent_out["edge_termination_anchor_id"] = anchor_id
        adjacent_out["edge_termination_reason"] = reason
        adjacent_out["intermediate_intersection_crossed_flag"] = "TRUE" if refined else "FALSE"
        adjacent_out["remaining_intermediate_intersection_crossed_flag"] = "TRUE" if remaining_crossed else "FALSE"
        adjacent_out["termination_refinement_applied"] = "TRUE" if refined else "FALSE"
        adjacent_out["manual_edge_termination_issue_signal"] = "TRUE" if row.signal_id in manual_issue_ids else "FALSE"
        adjacent_out["zero_length_after_refinement"] = "TRUE" if zero_length else "FALSE"
        adjacent_out["suspicious_short_segment_after_refinement"] = "TRUE" if suspicious_short else "FALSE"
        adjacent_out["new_suspicious_short_segment_created"] = "TRUE" if new_suspicious_short else "FALSE"
        adjacent_out["requires_manual_review"] = "TRUE" if requires_review else "FALSE"
        adjacent_records.append(adjacent_out)
        adjacent_geometries.append(refined_line)

        edge_records.append(
            {
                "graph_edge_id": refined_edge_id,
                "original_graph_edge_id": row.graph_edge_id,
                "from_graph_node_id": row.signal_graph_node_id,
                "to_graph_node_id": anchor_id,
                "signal_id": row.signal_id,
                "signal_graph_node_id": row.signal_graph_node_id,
                "route_name": row.route_name,
                "route_common": row.route_common,
                "route_id": row.route_id,
                "event_source": row.event_source,
                "road_component_id": row.road_component_id,
                "roadway_division_status": row.roadway_division_status,
                "logical_segment_mode": row.logical_segment_mode,
                "facility_code": row.facility_code,
                "median_code": row.median_code,
                "roadway_directionality_type": _roadway_directionality_type(row.roadway_division_status),
                "length_ft": post_length_ft,
                "pre_refinement_length_ft": pre_length_ft,
                "post_refinement_length_ft": post_length_ft,
                "edge_termination_status": termination_status,
                "edge_termination_anchor_type": anchor_type,
                "edge_termination_anchor_id": anchor_id,
                "edge_termination_reason": reason,
                "intermediate_intersection_crossed_flag": "TRUE" if refined else "FALSE",
                "remaining_intermediate_intersection_crossed_flag": "TRUE" if remaining_crossed else "FALSE",
                "termination_refinement_applied": "TRUE" if refined else "FALSE",
                "new_suspicious_short_segment_created": "TRUE" if new_suspicious_short else "FALSE",
                "requires_manual_review": "TRUE" if requires_review else "FALSE",
                "true_vehicle_direction_inferred": False,
            }
        )
        edge_geometries.append(refined_line)

        if refined or remaining_crossed or row.signal_id in manual_issue_ids or zero_length or suspicious_short:
            example_records.append(
                {
                    "signal_id": row.signal_id,
                    "refined_edge_id": refined_edge_id,
                    "original_graph_edge_id": row.graph_edge_id,
                    "route_name": row.route_name,
                    "route_common": row.route_common,
                    "termination_refinement_applied": "TRUE" if refined else "FALSE",
                    "edge_termination_status": termination_status,
                    "edge_termination_anchor_type": anchor_type,
                    "edge_termination_anchor_id": anchor_id,
                    "pre_refinement_length_ft": pre_length_ft,
                    "post_refinement_length_ft": post_length_ft,
                    "length_delta_ft": pre_length_ft - post_length_ft,
                    "remaining_intermediate_intersection_crossed_flag": "TRUE" if remaining_crossed else "FALSE",
                    "manual_edge_termination_issue_signal": "TRUE" if row.signal_id in manual_issue_ids else "FALSE",
                    "zero_length_after_refinement": "TRUE" if zero_length else "FALSE",
                    "suspicious_short_segment_after_refinement": "TRUE" if suspicious_short else "FALSE",
                    "new_suspicious_short_segment_created": "TRUE" if new_suspicious_short else "FALSE",
                    "requires_manual_review": "TRUE" if requires_review else "FALSE",
                }
            )

    refined_adjacent = gpd.GeoDataFrame(adjacent_records, geometry=adjacent_geometries, crs=adjacent.crs)
    refined_edges = gpd.GeoDataFrame(edge_records, geometry=edge_geometries, crs=adjacent.crs)
    examples = pd.DataFrame(example_records)
    return refined_edges, refined_adjacent, examples


def _build_refined_edges_eligible(refined_edges: gpd.GeoDataFrame, signal_eligibility: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if refined_edges.empty:
        return refined_edges.copy()
    signal_status = signal_eligibility[["signal_id", "usable_for_step5", "step5_exclusion_reason"]].copy()
    out = refined_edges.merge(signal_status, on="signal_id", how="left", suffixes=("", "_signal_gate"))
    out["usable_for_step5"] = out["usable_for_step5"].fillna("FALSE")
    out["step5_exclusion_reason"] = out["step5_exclusion_reason"].fillna("no_eligible_adjacent_signal")
    out.loc[out["usable_for_step5"].eq("TRUE"), "step5_exclusion_reason"] = ""
    out["requires_manual_review"] = out.apply(
        lambda row: "TRUE"
        if str(row.get("requires_manual_review", "")) == "TRUE" or str(row.get("usable_for_step5", "")) != "TRUE"
        else "FALSE",
        axis=1,
    )
    columns = [
        "graph_edge_id",
        "original_graph_edge_id",
        "from_graph_node_id",
        "to_graph_node_id",
        "signal_id",
        "roadway_directionality_type",
        "edge_termination_status",
        "edge_termination_anchor_type",
        "edge_termination_anchor_id",
        "edge_termination_reason",
        "intermediate_intersection_crossed_flag",
        "remaining_intermediate_intersection_crossed_flag",
        "pre_refinement_length_ft",
        "post_refinement_length_ft",
        "termination_refinement_applied",
        "usable_for_step5",
        "step5_exclusion_reason",
        "requires_manual_review",
        "route_name",
        "route_common",
        "road_component_id",
        "roadway_division_status",
        "geometry",
    ]
    return gpd.GeoDataFrame(out[[column for column in columns if column in out.columns]].copy(), geometry="geometry", crs=refined_edges.crs)


def _termination_refinement_summary(
    adjacent: gpd.GeoDataFrame,
    refined_adjacent: gpd.GeoDataFrame,
    bins: gpd.GeoDataFrame,
    refined_bins: gpd.GeoDataFrame,
    signal_eligibility: gpd.GeoDataFrame,
    refined_edges_eligible: gpd.GeoDataFrame,
    first_prototype_signals: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str) -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    add("base_signal_adjacent_edge_rows", len(adjacent), "Original signal-adjacent edge rows.")
    add("refined_signal_adjacent_edge_rows", len(refined_adjacent), "Candidate refined signal-adjacent edge rows.")
    add(
        "termination_refinement_applied_edges",
        int(refined_adjacent["termination_refinement_applied"].eq("TRUE").sum()) if not refined_adjacent.empty else 0,
        "Edges shortened to an existing intermediate road_intersection graph node.",
    )
    add(
        "remaining_intermediate_intersection_crossed_edges",
        int(refined_adjacent["remaining_intermediate_intersection_crossed_flag"].eq("TRUE").sum()) if not refined_adjacent.empty else 0,
        "Refined candidate rows that still appear to contain a supported intermediate intersection.",
    )
    add("base_50ft_bin_rows", len(bins), "Original 50-foot bin rows.")
    add("refined_50ft_bin_rows", len(refined_bins), "50-foot bin rows after candidate termination refinement.")
    add("bin_row_delta", len(refined_bins) - len(bins), "Refined bins minus base bins.")
    add(
        "zero_length_after_refinement_edges",
        int(refined_adjacent["zero_length_after_refinement"].eq("TRUE").sum()) if not refined_adjacent.empty else 0,
        "Rows with post-refinement length <= 1 foot.",
    )
    add(
        "suspicious_short_segment_after_refinement_edges",
        int(refined_adjacent["suspicious_short_segment_after_refinement"].eq("TRUE").sum()) if not refined_adjacent.empty else 0,
        "Rows with post-refinement length between 1 and 25 feet.",
    )
    add(
        "new_suspicious_short_segment_created_edges",
        int(refined_adjacent["new_suspicious_short_segment_created"].eq("TRUE").sum()) if not refined_adjacent.empty else 0,
        "Rows shortened by refinement from >=25 feet to <25 feet.",
    )

    if not refined_adjacent.empty:
        for anchor_type, count in refined_adjacent["edge_termination_anchor_type"].value_counts().items():
            add(f"refined_termination_anchor_type_{anchor_type}", int(count), "Refined edge termination anchor type count.")
        for status, count in refined_adjacent["edge_termination_status"].value_counts().items():
            add(f"refined_termination_status_{status}", int(count), "Refined edge termination status count.")

    before_counts = signal_eligibility["usable_for_step5"].value_counts()
    for status in ["TRUE", "CONDITIONAL", "FALSE"]:
        add(f"signal_gate_before_{status}", int(before_counts.get(status, 0)), "Signal eligibility before termination refinement.")
        add(
            f"signal_gate_after_{status}",
            int(before_counts.get(status, 0)),
            "Signal-level eligibility is not promoted by this review-only termination refinement.",
        )

    if not first_prototype_signals.empty:
        first_ids = set(first_prototype_signals["signal_id"].astype(str))
        changed = signal_eligibility.loc[signal_eligibility["signal_id"].astype(str).isin(first_ids)]
        add(
            "first_prototype_input_signals_changed_eligibility",
            0,
            f"{len(changed)} first-prototype TRUE input signals retained their signal-level eligibility status.",
        )
    return pd.DataFrame(rows)


def _step5_before_after_refinement(signal_eligibility: gpd.GeoDataFrame) -> pd.DataFrame:
    counts = signal_eligibility["usable_for_step5"].value_counts()
    rows = []
    for status in ["TRUE", "CONDITIONAL", "FALSE"]:
        before = int(counts.get(status, 0))
        rows.append(
            {
                "usable_for_step5": status,
                "before_signal_count": before,
                "after_signal_count": before,
                "delta": 0,
                "notes": "Termination refinement outputs are review-only candidates and do not promote or demote signal-level Step 5 eligibility.",
            }
        )
    return pd.DataFrame(rows)


def _extract_signal_id_from_node_id(node_id: object) -> str:
    match = re.search(r"signal_\d{6}", str(node_id or ""))
    return match.group(0) if match else ""


def _step5_anchor_type(node_type: object) -> str:
    text = str(node_type or "")
    if text == "signal":
        return "signalized_intersection"
    if text == "road_intersection":
        return "non_signalized_roadway_intersection"
    if text == "road_endpoint":
        return "road_endpoint_dead_end"
    return "unresolved"


def _build_step5_oriented_segments(
    first_prototype_signals: pd.DataFrame,
    adjacent: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if first_prototype_signals.empty or adjacent.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=adjacent.crs)

    true_signal_ids = set(first_prototype_signals["signal_id"].astype(str))
    source_signal_lookup = {
        str(row.signal_id): str(getattr(row, "source_signal_id", "") or "")
        for row in first_prototype_signals.itertuples(index=False)
    }
    work = adjacent.loc[adjacent["signal_id"].astype(str).isin(true_signal_ids)].copy()
    if work.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=adjacent.crs)

    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    short_ft = 50.0

    for graph_edge_id, group in work.groupby("graph_edge_id", sort=True):
        group = group.sort_values(["signal_id", "leg_index"]).copy()
        first = group.iloc[0]
        roadway_type = _roadway_directionality_type(first["roadway_division_status"])
        segment_family_id = f"segfam_{_slugify(graph_edge_id)}"

        if roadway_type == "undivided":
            signal_ids = list(group["signal_id"].astype(str).drop_duplicates())
            row = group.iloc[0]
            adjacent_signal_id = _extract_signal_id_from_node_id(row["adjacent_node_id"])
            to_signal_id = ""
            if len(signal_ids) > 1:
                to_signal_id = signal_ids[1]
            elif adjacent_signal_id in true_signal_ids:
                to_signal_id = adjacent_signal_id
            length_ft = float(row["length_ft"])
            requires_review = length_ft <= 0 or length_ft < short_ft or str(row["roadway_division_status"]) != "undivided"
            records.append(
                {
                    "oriented_segment_id": f"oseg_{_slugify(graph_edge_id)}_undivided_centerline",
                    "segment_family_id": segment_family_id,
                    "base_graph_edge_id": graph_edge_id,
                    "source_signal_id": source_signal_lookup.get(str(row["signal_id"]), ""),
                    "from_anchor_type": "signalized_intersection",
                    "from_anchor_id": row["signal_graph_node_id"],
                    "to_anchor_type": _step5_anchor_type(row["adjacent_node_type"]),
                    "to_anchor_id": row["adjacent_node_id"],
                    "from_signal_id": row["signal_id"],
                    "to_signal_id": to_signal_id,
                    "downstream_of_signal_id": "",
                    "upstream_of_signal_id": "",
                    "roadway_directionality_type": roadway_type,
                    "orientation_record_type": "undivided_logical_centerline",
                    "true_vehicle_direction_inferred": False,
                    "segment_orientation_only": True,
                    "physical_directional_carriageway": False,
                    "undivided_event_direction_requires_crash_direction": True,
                    "route_name": row["route_name"],
                    "route_common": row["route_common"],
                    "route_id": row["route_id"],
                    "event_source": row["event_source"],
                    "road_component_id": row["road_component_id"],
                    "roadway_division_status": row["roadway_division_status"],
                    "logical_segment_mode": row["logical_segment_mode"],
                    "length_ft": length_ft,
                    "bin_count": max(1, int(math.ceil(length_ft / BIN_LENGTH_FT))) if length_ft > 0 else 0,
                    "qa_status": "undivided_centerline_geometry_only_requires_later_crash_direction",
                    "requires_manual_review": requires_review,
                    "usable_for_later_crash_assignment": not requires_review,
                }
            )
            geometries.append(row.geometry)
            continue

        for ordinal, row in enumerate(group.itertuples(index=False), start=1):
            row_dict = row._asdict()
            signal_id = str(row.signal_id)
            adjacent_signal_id = _extract_signal_id_from_node_id(row.adjacent_node_id)
            adjacent_signal_is_true = adjacent_signal_id in true_signal_ids
            length_ft = float(row.length_ft)
            requires_review = length_ft <= 0 or length_ft < short_ft

            if roadway_type == "unknown":
                orientation_type = "review_only"
                requires_review = True
                qa_status = "unknown_roadway_directionality_review_required"
            elif row.adjacent_node_type == "signal" and adjacent_signal_is_true and len(group["signal_id"].astype(str).drop_duplicates()) >= 2:
                orientation_type = "divided_oriented_candidate" if ordinal == 1 else "reciprocal_orientation_candidate"
                qa_status = "divided_paired_geometry_orientation_candidate_no_true_vehicle_direction"
            elif row.adjacent_node_type in {"road_intersection", "road_endpoint"}:
                orientation_type = "endpoint_oriented_candidate"
                qa_status = "divided_oriented_to_non_signal_or_endpoint_anchor_no_true_vehicle_direction"
            else:
                orientation_type = "review_only"
                requires_review = True
                qa_status = "divided_unpaired_or_non_true_signal_anchor_review_required"

            records.append(
                {
                    "oriented_segment_id": f"oseg_{_slugify(graph_edge_id)}_{_slugify(signal_id)}_{ordinal:02d}",
                    "segment_family_id": segment_family_id,
                    "base_graph_edge_id": graph_edge_id,
                    "source_signal_id": source_signal_lookup.get(signal_id, ""),
                    "from_anchor_type": "signalized_intersection",
                    "from_anchor_id": row.signal_graph_node_id,
                    "to_anchor_type": _step5_anchor_type(row.adjacent_node_type),
                    "to_anchor_id": row.adjacent_node_id,
                    "from_signal_id": signal_id,
                    "to_signal_id": adjacent_signal_id if adjacent_signal_is_true else "",
                    "downstream_of_signal_id": signal_id if orientation_type != "review_only" else "",
                    "upstream_of_signal_id": adjacent_signal_id if adjacent_signal_is_true and orientation_type != "review_only" else "",
                    "roadway_directionality_type": roadway_type,
                    "orientation_record_type": orientation_type,
                    "true_vehicle_direction_inferred": False,
                    "segment_orientation_only": True,
                    "physical_directional_carriageway": roadway_type == "divided",
                    "undivided_event_direction_requires_crash_direction": False,
                    "route_name": row.route_name,
                    "route_common": row.route_common,
                    "route_id": row.route_id,
                    "event_source": row.event_source,
                    "road_component_id": row.road_component_id,
                    "roadway_division_status": row.roadway_division_status,
                    "logical_segment_mode": row.logical_segment_mode,
                    "length_ft": length_ft,
                    "bin_count": max(1, int(math.ceil(length_ft / BIN_LENGTH_FT))) if length_ft > 0 else 0,
                    "qa_status": qa_status,
                    "requires_manual_review": requires_review,
                    "usable_for_later_crash_assignment": not requires_review and orientation_type != "review_only",
                }
            )
            geometries.append(row.geometry)

    return gpd.GeoDataFrame(records, geometry=geometries, crs=adjacent.crs)


def _build_oriented_segment_bins(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    for row in segments.itertuples(index=False):
        length_ft = float(row.length_ft)
        if length_ft <= 0 or row.geometry is None or row.geometry.is_empty:
            continue
        bin_count = max(1, int(math.ceil(length_ft / BIN_LENGTH_FT)))
        for bin_index in range(bin_count):
            start_ft = bin_index * BIN_LENGTH_FT
            end_ft = min(length_ft, (bin_index + 1) * BIN_LENGTH_FT)
            midpoint_ft = (start_ft + end_ft) / 2.0
            geometry = _line_substring(row.geometry, start_ft / FEET_PER_METER, end_ft / FEET_PER_METER)
            records.append(
                {
                    "oriented_segment_id": row.oriented_segment_id,
                    "segment_family_id": row.segment_family_id,
                    "base_graph_edge_id": row.base_graph_edge_id,
                    "bin_id": f"{row.oriented_segment_id}_bin_{bin_index:04d}",
                    "bin_index": bin_index,
                    "bin_start_ft": start_ft,
                    "bin_end_ft": end_ft,
                    "bin_midpoint_ft": midpoint_ft,
                    "from_anchor_id": row.from_anchor_id,
                    "to_anchor_id": row.to_anchor_id,
                    "downstream_of_signal_id": row.downstream_of_signal_id,
                    "upstream_of_signal_id": row.upstream_of_signal_id,
                    "roadway_directionality_type": row.roadway_directionality_type,
                    "orientation_record_type": row.orientation_record_type,
                    "true_vehicle_direction_inferred": False,
                    "physical_directional_carriageway": row.physical_directional_carriageway,
                    "undivided_event_direction_requires_crash_direction": row.undivided_event_direction_requires_crash_direction,
                }
            )
            geometries.append(geometry)
    if not records:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=segments.crs)
    return gpd.GeoDataFrame(records, geometry=geometries, crs=segments.crs)


def _step5_oriented_segment_reviews(
    first_prototype_signals: pd.DataFrame,
    signal_eligibility: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    bins: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    true_ids = set(first_prototype_signals["signal_id"].astype(str)) if not first_prototype_signals.empty else set()
    all_non_true_ids = set(signal_eligibility.loc[~signal_eligibility["usable_for_step5"].eq("TRUE"), "signal_id"].astype(str))
    represented_ids: set[str] = set()
    if not segments.empty:
        represented_ids.update(segments["from_signal_id"].fillna("").astype(str).loc[segments["from_signal_id"].fillna("").astype(str).ne("")])
        represented_ids.update(segments["to_signal_id"].fillna("").astype(str).loc[segments["to_signal_id"].fillna("").astype(str).ne("")])

    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str) -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    add("true_input_signal_count", len(true_ids), "Signals from step5_first_prototype_input_signals.csv.")
    add("true_input_signals_represented", len(true_ids & represented_ids), "TRUE input signals appearing as from/to signal ids in oriented segments.")
    add("oriented_segment_rows", len(segments), "Total oriented segment prototype rows.")
    add("oriented_segment_bin_rows_50ft", len(bins), "50-foot bins generated from oriented segment rows.")
    add("non_true_signals_entered_prototype", len(represented_ids & all_non_true_ids), "FALSE/CONDITIONAL signal ids represented in the prototype; expected 0.")
    add(
        "zero_length_segments",
        int((pd.to_numeric(segments["length_ft"], errors="coerce") <= 0).sum()) if not segments.empty else 0,
        "Segments with non-positive length.",
    )
    add(
        "suspicious_short_segments_under_50ft",
        int(((pd.to_numeric(segments["length_ft"], errors="coerce") > 0) & (pd.to_numeric(segments["length_ft"], errors="coerce") < 50)).sum())
        if not segments.empty
        else 0,
        "Segments shorter than one 50-foot bin.",
    )
    add(
        "true_vehicle_direction_inferred_rows",
        int(segments["true_vehicle_direction_inferred"].astype(str).str.upper().ne("FALSE").sum()) if not segments.empty else 0,
        "Expected 0.",
    )
    add(
        "undivided_physical_directional_carriageway_true_rows",
        int(
            (
                segments["roadway_directionality_type"].eq("undivided")
                & segments["physical_directional_carriageway"].astype(str).str.upper().eq("TRUE")
            ).sum()
        )
        if not segments.empty
        else 0,
        "Expected 0.",
    )
    add(
        "undivided_requires_crash_direction_false_rows",
        int(
            (
                segments["roadway_directionality_type"].eq("undivided")
                & segments["undivided_event_direction_requires_crash_direction"].astype(str).str.upper().ne("TRUE")
            ).sum()
        )
        if not segments.empty
        else 0,
        "Expected 0.",
    )
    add(
        "endpoint_or_review_only_segments",
        int(segments["orientation_record_type"].isin(["endpoint_oriented_candidate", "review_only"]).sum()) if not segments.empty else 0,
        "Endpoint-oriented or review-only segment rows.",
    )

    if not segments.empty:
        for value, count in segments["roadway_directionality_type"].value_counts().items():
            add(f"segments_by_roadway_directionality_type_{value}", int(count), "Oriented segment rows by roadway source directionality class.")
        for value, count in segments["orientation_record_type"].value_counts().items():
            add(f"segments_by_orientation_record_type_{value}", int(count), "Oriented segment rows by orientation record type.")

    problem_records: list[dict[str, object]] = []
    if not segments.empty:
        for row in segments.itertuples(index=False):
            problems: list[str] = []
            length_ft = float(row.length_ft)
            if row.from_signal_id in all_non_true_ids or row.to_signal_id in all_non_true_ids:
                problems.append("non_true_signal_represented")
            if length_ft <= 0:
                problems.append("zero_length")
            elif length_ft < 50:
                problems.append("suspicious_short_under_50ft")
            if str(row.true_vehicle_direction_inferred).upper() != "FALSE":
                problems.append("true_vehicle_direction_inferred_not_false")
            if row.roadway_directionality_type == "undivided" and str(row.physical_directional_carriageway).upper() == "TRUE":
                problems.append("undivided_marked_physical_directional_carriageway")
            if row.roadway_directionality_type == "undivided" and str(row.undivided_event_direction_requires_crash_direction).upper() != "TRUE":
                problems.append("undivided_not_marked_requires_crash_direction")
            if row.orientation_record_type == "review_only":
                problems.append("review_only")
            if problems:
                problem_records.append(
                    {
                        "oriented_segment_id": row.oriented_segment_id,
                        "segment_family_id": row.segment_family_id,
                        "base_graph_edge_id": row.base_graph_edge_id,
                        "from_signal_id": row.from_signal_id,
                        "to_signal_id": row.to_signal_id,
                        "roadway_directionality_type": row.roadway_directionality_type,
                        "orientation_record_type": row.orientation_record_type,
                        "length_ft": row.length_ft,
                        "problem_flags": ";".join(problems),
                    }
                )

    problem_rows = pd.DataFrame(problem_records)

    if segments.empty:
        pairing_summary = pd.DataFrame()
    else:
        pairing_records = []
        for family_id, group in segments.groupby("segment_family_id", sort=True):
            roadway_types = sorted(group["roadway_directionality_type"].astype(str).unique())
            orientation_types = sorted(group["orientation_record_type"].astype(str).unique())
            is_divided = "divided" in roadway_types
            paired = is_divided and len(group) >= 2 and {
                "divided_oriented_candidate",
                "reciprocal_orientation_candidate",
            }.issubset(set(orientation_types))
            pairing_records.append(
                {
                    "segment_family_id": family_id,
                    "roadway_directionality_type": ";".join(roadway_types),
                    "orientation_record_types": ";".join(orientation_types),
                    "segment_record_count": len(group),
                    "divided_family_has_paired_reciprocal_records": paired,
                    "divided_family_missing_reciprocal_records": bool(is_divided and not paired),
                    "undivided_family_record_count": len(group) if "undivided" in roadway_types else 0,
                    "undivided_incorrectly_duplicated": bool("undivided" in roadway_types and len(group) > 1),
                }
            )
        pairing_summary = pd.DataFrame(pairing_records)

    coverage_records = []
    for row in first_prototype_signals.itertuples(index=False):
        signal_id = str(row.signal_id)
        from_count = int(segments["from_signal_id"].astype(str).eq(signal_id).sum()) if not segments.empty else 0
        to_count = int(segments["to_signal_id"].astype(str).eq(signal_id).sum()) if not segments.empty else 0
        coverage_records.append(
            {
                "signal_id": signal_id,
                "source_signal_id": getattr(row, "source_signal_id", ""),
                "represented_in_oriented_segments": from_count + to_count > 0,
                "from_signal_segment_count": from_count,
                "to_signal_segment_count": to_count,
                "total_signal_segment_count": from_count + to_count,
            }
        )
    coverage = pd.DataFrame(coverage_records)
    return pd.DataFrame(rows), problem_rows, pairing_summary, coverage


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
    manual_diagnosis = _read_manual_signal_diagnosis(layout.review_current)
    signal_step5_eligibility = _build_signal_step5_eligibility(signal_points, adjacent, gap_review, manual_diagnosis)
    roadway_graph_edges_eligible = _build_edges_eligible(edges, nodes, adjacent, signal_step5_eligibility)
    first_prototype_path = layout.review_current / "step5_first_prototype_input_signals.csv"
    first_prototype_signals = pd.read_csv(first_prototype_path, dtype=str, keep_default_na=False) if first_prototype_path.exists() else pd.DataFrame()
    if first_prototype_signals.empty:
        first_prototype_signals = pd.DataFrame(
            _to_csv_frame(signal_step5_eligibility.loc[signal_step5_eligibility["usable_for_step5"].eq("TRUE")])
        )
    oriented_segments = _build_step5_oriented_segments(first_prototype_signals, adjacent)
    oriented_segment_bins = _build_oriented_segment_bins(oriented_segments)
    (
        oriented_segment_summary,
        oriented_segment_problem_rows,
        oriented_segment_pairing_summary,
        oriented_segment_signal_coverage,
    ) = _step5_oriented_segment_reviews(
        first_prototype_signals,
        signal_step5_eligibility,
        oriented_segments,
        oriented_segment_bins,
    )
    refined_edges, refined_adjacent, termination_examples = _refine_signal_adjacent_edge_termination(
        adjacent,
        nodes,
        review_current=layout.review_current,
    )
    refined_bins = _build_bins(refined_adjacent)
    refined_edges_eligible = _build_refined_edges_eligible(refined_edges, signal_step5_eligibility)
    termination_summary = _termination_refinement_summary(
        adjacent,
        refined_adjacent,
        bins,
        refined_bins,
        signal_step5_eligibility,
        refined_edges_eligible,
        first_prototype_signals,
    )
    step5_before_after_refinement = _step5_before_after_refinement(signal_step5_eligibility)
    if termination_examples.empty:
        remaining_termination_candidates = termination_examples.copy()
        before_after_examples = termination_examples.copy()
    else:
        before_after_examples = termination_examples.sort_values(
            ["termination_refinement_applied", "length_delta_ft"],
            ascending=[False, False],
        ).copy()
        remaining_termination_candidates = termination_examples.loc[
            termination_examples["remaining_intermediate_intersection_crossed_flag"].eq("TRUE")
            | termination_examples["manual_edge_termination_issue_signal"].eq("TRUE")
            | termination_examples["zero_length_after_refinement"].eq("TRUE")
            | termination_examples["suspicious_short_segment_after_refinement"].eq("TRUE")
            | termination_examples["new_suspicious_short_segment_created"].eq("TRUE")
        ].copy()
    if not remaining_termination_candidates.empty and not refined_adjacent.empty:
        remaining_termination_candidates_geo = refined_adjacent.merge(
            remaining_termination_candidates.drop(columns=["geometry"], errors="ignore"),
            on=["signal_id", "refined_edge_id", "original_graph_edge_id"],
            how="inner",
            suffixes=("", "_review"),
        )
    else:
        remaining_termination_candidates_geo = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=adjacent.crs)
    step5_eligibility_summary = _step5_summary(signal_step5_eligibility)
    step5_excluded_signals = signal_step5_eligibility.loc[signal_step5_eligibility["usable_for_step5"].eq("FALSE")].copy()
    step5_candidate_signals = signal_step5_eligibility.loc[signal_step5_eligibility["usable_for_step5"].isin(["TRUE", "CONDITIONAL"])].copy()
    step5_candidate_edges = roadway_graph_edges_eligible.loc[roadway_graph_edges_eligible["usable_for_step5"].isin(["TRUE", "CONDITIONAL"])].copy()
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
        "signal_step5_eligibility_csv": (signal_step5_eligibility, layout.tables_current / "signal_step5_eligibility.csv"),
        "roadway_graph_edges_eligible_csv": (roadway_graph_edges_eligible, layout.tables_current / "roadway_graph_edges_eligible.csv"),
        "roadway_graph_edges_termination_refined_csv": (
            refined_edges,
            layout.tables_current / "roadway_graph_edges_termination_refined.csv",
        ),
        "signal_adjacent_edges_termination_refined_csv": (
            refined_adjacent,
            layout.tables_current / "signal_adjacent_edges_termination_refined.csv",
        ),
        "signal_graph_edge_bins_50ft_termination_refined_csv": (
            refined_bins,
            layout.tables_current / "signal_graph_edge_bins_50ft_termination_refined.csv",
        ),
        "roadway_graph_edges_eligible_termination_refined_csv": (
            refined_edges_eligible,
            layout.tables_current / "roadway_graph_edges_eligible_termination_refined.csv",
        ),
        "signal_oriented_roadway_segments_csv": (
            oriented_segments,
            layout.tables_current / "signal_oriented_roadway_segments.csv",
        ),
        "signal_oriented_segment_bins_50ft_csv": (
            oriented_segment_bins,
            layout.tables_current / "signal_oriented_segment_bins_50ft.csv",
        ),
    }
    for key, (frame, path) in table_outputs.items():
        outputs[key] = str(_write_csv_frame(_to_csv_frame(frame), path))

    review_outputs = {
        "graph_build_summary_csv": (build_summary, layout.review_current / "graph_build_summary.csv"),
        "signal_adjacent_edge_count_summary_csv": (count_summary, layout.review_current / "signal_adjacent_edge_count_summary.csv"),
        "sample_signal_graph_review_csv": (sample_review, layout.review_current / "sample_signal_graph_review.csv"),
        "step5_eligibility_summary_csv": (step5_eligibility_summary, layout.review_current / "step5_eligibility_summary.csv"),
        "step5_excluded_signals_csv": (step5_excluded_signals, layout.review_current / "step5_excluded_signals.csv"),
        "step5_candidate_signals_csv": (step5_candidate_signals, layout.review_current / "step5_candidate_signals.csv"),
        "edge_termination_refinement_summary_csv": (
            termination_summary,
            layout.review_current / "edge_termination_refinement_summary.csv",
        ),
        "edge_termination_before_after_examples_csv": (
            before_after_examples,
            layout.review_current / "edge_termination_before_after_examples.csv",
        ),
        "remaining_edge_termination_issue_candidates_csv": (
            remaining_termination_candidates,
            layout.review_current / "remaining_edge_termination_issue_candidates.csv",
        ),
        "step5_eligibility_before_after_termination_refinement_csv": (
            step5_before_after_refinement,
            layout.review_current / "step5_eligibility_before_after_termination_refinement.csv",
        ),
        "step5_oriented_segment_summary_csv": (
            oriented_segment_summary,
            layout.review_current / "step5_oriented_segment_summary.csv",
        ),
        "step5_oriented_segment_problem_rows_csv": (
            oriented_segment_problem_rows,
            layout.review_current / "step5_oriented_segment_problem_rows.csv",
        ),
        "step5_oriented_segment_pairing_summary_csv": (
            oriented_segment_pairing_summary,
            layout.review_current / "step5_oriented_segment_pairing_summary.csv",
        ),
        "step5_oriented_segment_signal_coverage_csv": (
            oriented_segment_signal_coverage,
            layout.review_current / "step5_oriented_segment_signal_coverage.csv",
        ),
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
        "step5_candidate_signals_geojson": (step5_candidate_signals, layout.review_geojson_current / "step5_candidate_signals.geojson"),
        "step5_excluded_signals_geojson": (step5_excluded_signals, layout.review_geojson_current / "step5_excluded_signals.geojson"),
        "step5_candidate_edges_geojson": (step5_candidate_edges, layout.review_geojson_current / "step5_candidate_edges.geojson"),
        "edge_termination_refined_edges_geojson": (
            refined_edges,
            layout.review_geojson_current / "edge_termination_refined_edges.geojson",
        ),
        "remaining_edge_termination_issue_candidates_geojson": (
            remaining_termination_candidates_geo,
            layout.review_geojson_current / "remaining_edge_termination_issue_candidates.geojson",
        ),
        "signal_oriented_roadway_segments_geojson": (
            oriented_segments,
            layout.review_geojson_current / "signal_oriented_roadway_segments.geojson",
        ),
        "signal_oriented_segment_bins_50ft_geojson": (
            oriented_segment_bins,
            layout.review_geojson_current / "signal_oriented_segment_bins_50ft.geojson",
        ),
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
