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
from shapely.ops import linemerge, substring, unary_union

from ..config import load_runtime_config


OUTPUT_FOLDER_NAME = "directed_segments"
TABLES_CURRENT_SUBDIR = ("tables", "current")
TABLES_HISTORY_SUBDIR = ("tables", "history")
REVIEW_CURRENT_SUBDIR = ("review", "current")
REVIEW_HISTORY_SUBDIR = ("review", "history")
REVIEW_GEOJSON_CURRENT_SUBDIR = ("review", "geojson", "current")
REVIEW_GEOJSON_HISTORY_SUBDIR = ("review", "geojson", "history")
RUNS_CURRENT_SUBDIR = ("runs", "current")
RUNS_HISTORY_SUBDIR = ("runs", "history")

FEET_PER_METER = 3.280839895
BIN_LENGTH_FT = 50.0
SHORT_LEG_FT = 50.0
SIGNAL_NEAR_ROAD_REVIEW_FT = 50.0
ACCESS_SEARCH_LIMIT_FT = 5280.0


@dataclass(frozen=True)
class OutputLayout:
    root: Path
    tables_current: Path
    tables_history: Path
    review_current: Path
    review_history: Path
    review_geojson_current: Path
    review_geojson_history: Path
    runs_current: Path
    runs_history: Path


def _output_subdir(output_dir: Path, *parts: str) -> Path:
    path = output_dir.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_layout(root: Path) -> OutputLayout:
    root.mkdir(parents=True, exist_ok=True)
    return OutputLayout(
        root=root,
        tables_current=_output_subdir(root, *TABLES_CURRENT_SUBDIR),
        tables_history=_output_subdir(root, *TABLES_HISTORY_SUBDIR),
        review_current=_output_subdir(root, *REVIEW_CURRENT_SUBDIR),
        review_history=_output_subdir(root, *REVIEW_HISTORY_SUBDIR),
        review_geojson_current=_output_subdir(root, *REVIEW_GEOJSON_CURRENT_SUBDIR),
        review_geojson_history=_output_subdir(root, *REVIEW_GEOJSON_HISTORY_SUBDIR),
        runs_current=_output_subdir(root, *RUNS_CURRENT_SUBDIR),
        runs_history=_output_subdir(root, *RUNS_HISTORY_SUBDIR),
    )


def _timestamped_history_path(path: Path, history_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = history_dir / f"{path.stem}_{stamp}{path.suffix}"
    counter = 1
    while candidate.exists():
        candidate = history_dir / f"{path.stem}_{stamp}_{counter}{path.suffix}"
        counter += 1
    return candidate


def _copy_output_to_history(path: Path, history_dir: Path | None = None) -> Path | None:
    if history_dir is None or not path.exists():
        return None
    history_dir.mkdir(parents=True, exist_ok=True)
    try:
        resolved_history_dir = history_dir.resolve()
        if resolved_history_dir == path.resolve().parent or resolved_history_dir in path.resolve().parents:
            return path
    except OSError:
        pass
    history_path = _timestamped_history_path(path, history_dir)
    history_path.write_bytes(path.read_bytes())
    return history_path


def _write_csv_frame(frame: pd.DataFrame, path: Path, history_dir: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _copy_output_to_history(path, history_dir)
    return path


def _write_geojson_frame(frame: gpd.GeoDataFrame, path: Path, history_dir: Path | None = None) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        _copy_output_to_history(path, history_dir)
        return path
    try:
        frame.to_file(path, driver="GeoJSON")
        _copy_output_to_history(path, history_dir)
        return path
    except PermissionError:
        if history_dir is None:
            raise
        history_dir.mkdir(parents=True, exist_ok=True)
        history_path = _timestamped_history_path(path, history_dir)
        frame.to_file(history_path, driver="GeoJSON")
        return history_path


def _write_json_object(payload: dict[str, object], path: Path, history_dir: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _copy_output_to_history(path, history_dir)
    return path


def _write_text_file(content: str, path: Path, history_dir: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _copy_output_to_history(path, history_dir)
    return path


def _slugify(raw_value: object) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", str(raw_value).strip()).strip("_").lower()
    return slug or "unknown"


def _clean_text(raw_value: object) -> str | None:
    if raw_value is None or pd.isna(raw_value):
        return None
    value = str(raw_value).strip()
    return value or None


def _safe_float(raw_value: object) -> float | None:
    value = pd.to_numeric(raw_value, errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _first_present(row: pd.Series, columns: Iterable[str]) -> str | None:
    for column in columns:
        if column in row:
            value = _clean_text(row[column])
            if value:
                return value
    return None


def _reverse_linestring(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def _as_linestring(geometry) -> LineString | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        if isinstance(merged, MultiLineString) and len(merged.geoms) == 1:
            return merged.geoms[0]
    return None


def _choose_linestring(geometry, start_point: Point, end_point: Point) -> tuple[LineString | None, str]:
    line = _as_linestring(geometry)
    if line is not None:
        return line, "single_linestring"
    if isinstance(geometry, MultiLineString):
        candidates = [part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty]
        if not candidates:
            return None, "no_linestring_component"
        ranked = sorted(candidates, key=lambda part: part.distance(start_point) + part.distance(end_point))
        return ranked[0], "selected_nearest_multiline_component"
    return None, "unsupported_geometry_type"


def _substring_between(line: LineString, start_point: Point, end_point: Point) -> tuple[LineString | None, str]:
    start_distance = line.project(start_point)
    end_distance = line.project(end_point)
    if math.isclose(start_distance, end_distance, abs_tol=0.001):
        return None, "projection_distances_equal"
    segment = substring(line, min(start_distance, end_distance), max(start_distance, end_distance))
    if not isinstance(segment, LineString) or segment.is_empty or segment.length <= 0:
        return None, "substring_not_linestring"
    if Point(segment.coords[0]).distance(start_point) > Point(segment.coords[-1]).distance(start_point):
        segment = _reverse_linestring(segment)
    return segment, "roadway_substring"


def _load_study_roads(study_slice_root: Path) -> gpd.GeoDataFrame:
    path = study_slice_root / "Study_Roads_Divided.parquet"
    roads = gpd.read_parquet(path).reset_index(names="StudyRoad_RowID")
    roads["StudyRoad_RowID"] = roads["StudyRoad_RowID"].astype(int)
    for column in ("FROM_MEASURE", "TO_MEASURE"):
        roads[column] = pd.to_numeric(roads[column], errors="coerce")
    return roads


def _load_study_signals(study_slice_root: Path) -> gpd.GeoDataFrame:
    path = study_slice_root / "Study_Signals_NearestRoad.parquet"
    signals = gpd.read_parquet(path)
    signals["Signal_RowID"] = pd.to_numeric(signals["Signal_RowID"], errors="coerce").astype("Int64")
    signals["NearestRoad_RowID"] = pd.to_numeric(signals["NearestRoad_RowID"], errors="coerce").astype("Int64")
    return signals


def _load_access_anchors(normalized_root: Path, target_crs) -> gpd.GeoDataFrame:
    path = normalized_root / "access.parquet"
    if not path.exists():
        empty = pd.DataFrame(columns=["access_anchor_id", "access_source_id", "route_name", "access_measure", "geometry"])
        return gpd.GeoDataFrame(empty, geometry="geometry", crs=target_crs)
    access = gpd.read_parquet(path)
    if access.crs != target_crs:
        access = access.to_crs(target_crs)
    access = access.loc[access["_rte_nm"].notna() & access["_m"].notna()].copy()
    access["access_measure"] = pd.to_numeric(access["_m"], errors="coerce")
    access = access.loc[access["access_measure"].notna() & access.geometry.notna() & ~access.geometry.is_empty].copy()
    access["access_source_id"] = access["id"].astype(str)
    access["access_anchor_id"] = "access_" + access["access_source_id"].map(_slugify)
    access["route_name"] = access["_rte_nm"].astype(str)
    keep = [
        "access_anchor_id",
        "access_source_id",
        "route_name",
        "access_measure",
        "ACCESS_DIRECTION",
        "ACCESS_CONTROL",
        "NUMBER_OF_APPROACHES",
        "geometry",
    ]
    return gpd.GeoDataFrame(access[[column for column in keep if column in access.columns]], geometry="geometry", crs=access.crs)


def _make_signal_nodes(signals: gpd.GeoDataFrame, roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    road_lookup = roads.set_index("StudyRoad_RowID", drop=False)
    records: list[dict[str, object]] = []
    geometry: list[Point] = []

    for row in signals.itertuples(index=False):
        source = pd.Series(row._asdict())
        signal_row_id = int(source["Signal_RowID"]) if not pd.isna(source["Signal_RowID"]) else None
        signal_id = f"signal_{signal_row_id:06d}" if signal_row_id is not None else f"signal_unknown_{len(records):06d}"
        point = source["geometry"]
        nearest_row_id = source["NearestRoad_RowID"]
        match_status = "usable"
        match_reason = "matched to nearest divided-road row"
        projected_measure = None
        projected_fraction = None
        snapped_point = None

        if point is None or point.is_empty:
            match_status = "rejected_invalid_signal_geometry"
            match_reason = "signal geometry is empty"
        elif pd.isna(nearest_row_id):
            match_status = "rejected_missing_nearest_road"
            match_reason = "nearest divided-road row is missing"
        elif int(nearest_row_id) not in road_lookup.index:
            match_status = "rejected_nearest_road_not_found"
            match_reason = "nearest divided-road row id is not present in Study_Roads_Divided"
        else:
            road_row = road_lookup.loc[int(nearest_row_id)]
            road_line, road_line_status = _choose_linestring(road_row.geometry, point, point)
            from_measure = _safe_float(source.get("NearestRoad_FROM_MEASURE"))
            to_measure = _safe_float(source.get("NearestRoad_TO_MEASURE"))
            if road_line is None or road_line.length <= 0:
                match_status = "rejected_invalid_nearest_road_geometry"
                match_reason = f"nearest road geometry cannot be reduced to a usable line: {road_line_status}"
            elif from_measure is None or to_measure is None:
                match_status = "rejected_missing_nearest_road_measure"
                match_reason = "nearest road measure range is missing"
            else:
                projection_distance = road_line.project(point)
                projected_fraction = projection_distance / road_line.length if road_line.length else None
                snapped_point = road_line.interpolate(projection_distance)
                projected_measure = from_measure + (to_measure - from_measure) * float(projected_fraction or 0.0)
                nearest_distance_ft = _safe_float(source.get("NearestRoad_Distance_FT"))
                if nearest_distance_ft is not None and nearest_distance_ft > SIGNAL_NEAR_ROAD_REVIEW_FT:
                    match_status = "usable_review_distance_over_50ft"
                    match_reason = "matched to nearest divided-road row but distance exceeds 50 feet"

        source_signal_id = _first_present(source, ("REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "ASSET_ID", "GLOBALID"))
        route_name = _clean_text(source.get("NearestRoad_RTE_NM"))
        route_id = _clean_text(source.get("NearestRoad_RTE_ID"))
        route_common = _clean_text(source.get("NearestRoad_RTE_COMMON"))
        carriageway_id = "|".join(part for part in (route_name, route_id) if part) or None
        records.append(
            {
                "signal_id": signal_id,
                "source_signal_id": source_signal_id,
                "signal_row_id": signal_row_id,
                "reg_signal_id": _clean_text(source.get("REG_SIGNAL_ID")),
                "signal_no": _clean_text(source.get("SIGNAL_NO")),
                "intno": _clean_text(source.get("INTNO")),
                "major_road_name": _clean_text(source.get("MAJ_NAME")),
                "minor_road_name": _clean_text(source.get("MINOR_NAME")),
                "route_name": route_name,
                "route_id": route_id,
                "route_common": route_common,
                "roadway_carriageway_id": carriageway_id,
                "nearest_road_row_id": None if pd.isna(nearest_row_id) else int(nearest_row_id),
                "nearest_road_distance_ft": _safe_float(source.get("NearestRoad_Distance_FT")),
                "nearest_road_tie_count": _safe_float(source.get("NearestRoad_TieCount")),
                "nearest_road_is_ambiguous": bool(source.get("NearestRoad_IsAmbiguous"))
                if "NearestRoad_IsAmbiguous" in source and not pd.isna(source.get("NearestRoad_IsAmbiguous"))
                else None,
                "nearest_road_tie_break_rule": _clean_text(source.get("NearestRoad_TieBreakRule")),
                "nearest_road_from_measure": _safe_float(source.get("NearestRoad_FROM_MEASURE")),
                "nearest_road_to_measure": _safe_float(source.get("NearestRoad_TO_MEASURE")),
                "route_measure_estimate": projected_measure,
                "road_projection_fraction": projected_fraction,
                "snapped_x": snapped_point.x if snapped_point is not None else None,
                "snapped_y": snapped_point.y if snapped_point is not None else None,
                "signal_road_match_status": match_status,
                "signal_road_match_reason": match_reason,
                "stage1_source_gdb": _clean_text(source.get("Stage1_SourceGDB")),
                "stage1_source_layer": _clean_text(source.get("Stage1_SourceLayer")),
            }
        )
        geometry.append(point if point is not None else Point())

    return gpd.GeoDataFrame(records, geometry=geometry, crs=signals.crs)


def _route_rows_for_group(roads: gpd.GeoDataFrame, route_name: object, route_id: object) -> gpd.GeoDataFrame:
    mask = roads["RTE_NM"].astype(str).eq(str(route_name))
    if route_id is not None and "RTE_ID" in roads.columns:
        mask &= roads["RTE_ID"].astype(str).eq(str(route_id))
    return roads.loc[mask].copy()


def _measure_overlap_rows(route_roads: gpd.GeoDataFrame, start_measure: float, end_measure: float) -> gpd.GeoDataFrame:
    low = min(start_measure, end_measure)
    high = max(start_measure, end_measure)
    mask = route_roads["FROM_MEASURE"].le(high) & route_roads["TO_MEASURE"].ge(low)
    return route_roads.loc[mask].sort_values(["FROM_MEASURE", "TO_MEASURE", "StudyRoad_RowID"]).copy()


def _anchor_point(anchor: pd.Series) -> Point:
    if not pd.isna(anchor.get("snapped_x")) and not pd.isna(anchor.get("snapped_y")):
        return Point(float(anchor["snapped_x"]), float(anchor["snapped_y"]))
    return anchor.geometry


def _access_anchor_to_series(access_row: pd.Series) -> pd.Series:
    return pd.Series(
        {
            "anchor_id": access_row["access_anchor_id"],
            "anchor_type": "access",
            "route_measure_estimate": float(access_row["access_measure"]),
            "geometry": access_row.geometry,
            "snapped_x": None,
            "snapped_y": None,
            "access_source_id": access_row["access_source_id"],
        }
    )


def _signal_anchor_to_series(signal_row: pd.Series) -> pd.Series:
    return pd.Series(
        {
            "anchor_id": signal_row["signal_id"],
            "anchor_type": "signal",
            "route_measure_estimate": float(signal_row["route_measure_estimate"]),
            "geometry": signal_row.geometry,
            "snapped_x": signal_row.get("snapped_x"),
            "snapped_y": signal_row.get("snapped_y"),
        }
    )


def _road_endpoint_anchor(route_roads: gpd.GeoDataFrame, side: str, route_name: object, crs) -> pd.Series | None:
    route_roads = route_roads.dropna(subset=["FROM_MEASURE", "TO_MEASURE"]).copy()
    if route_roads.empty:
        return None
    if side == "lower":
        road_row = route_roads.sort_values(["FROM_MEASURE", "TO_MEASURE"]).iloc[0]
        measure = float(road_row["FROM_MEASURE"])
        endpoint_index = 0
        suffix = "min_measure"
    else:
        road_row = route_roads.sort_values(["TO_MEASURE", "FROM_MEASURE"]).iloc[-1]
        measure = float(road_row["TO_MEASURE"])
        endpoint_index = -1
        suffix = "max_measure"
    line, _ = _choose_linestring(road_row.geometry, road_row.geometry.centroid, road_row.geometry.centroid)
    if line is None or line.is_empty:
        return None
    point = Point(line.coords[endpoint_index])
    return pd.Series(
        {
            "anchor_id": f"road_endpoint_{_slugify(route_name)}_{suffix}",
            "anchor_type": "road_endpoint",
            "route_measure_estimate": measure,
            "geometry": point,
            "snapped_x": point.x,
            "snapped_y": point.y,
        }
    )


def _geometry_between_anchors(
    route_roads: gpd.GeoDataFrame,
    from_anchor: pd.Series,
    to_anchor: pd.Series,
) -> tuple[LineString, str, str]:
    from_point = _anchor_point(from_anchor)
    to_point = _anchor_point(to_anchor)
    from_measure = float(from_anchor["route_measure_estimate"])
    to_measure = float(to_anchor["route_measure_estimate"])
    overlap_rows = _measure_overlap_rows(route_roads, from_measure, to_measure)
    if overlap_rows.empty:
        return LineString([from_point, to_point]), "fallback_direct_anchor_line", "no overlapping route rows"
    try:
        merged = linemerge(unary_union(list(overlap_rows.geometry)))
        line, line_status = _choose_linestring(merged, from_point, to_point)
        if line is None:
            return LineString([from_point, to_point]), "fallback_direct_anchor_line", line_status
        segment, segment_status = _substring_between(line, from_point, to_point)
        if segment is None:
            return LineString([from_point, to_point]), "fallback_direct_anchor_line", segment_status
        if Point(segment.coords[0]).distance(from_point) > Point(segment.coords[-1]).distance(from_point):
            segment = _reverse_linestring(segment)
        return segment, segment_status, line_status
    except Exception as exc:  # pragma: no cover - defensive geometry fallback
        return LineString([from_point, to_point]), "fallback_direct_anchor_line", f"geometry extraction failed: {exc}"


def _nearest_access_anchor(
    access_group: gpd.GeoDataFrame,
    signal_measure: float,
    side: str,
) -> pd.Series | None:
    if access_group.empty:
        return None
    if side == "lower":
        candidates = access_group.loc[access_group["access_measure"].lt(signal_measure)].copy()
        candidates["distance_measure_abs"] = signal_measure - candidates["access_measure"]
    else:
        candidates = access_group.loc[access_group["access_measure"].gt(signal_measure)].copy()
        candidates["distance_measure_abs"] = candidates["access_measure"] - signal_measure
    if candidates.empty:
        return None
    candidates["distance_ft_approx"] = candidates["distance_measure_abs"] * 5280.0
    candidates = candidates.loc[candidates["distance_ft_approx"].le(ACCESS_SEARCH_LIMIT_FT)]
    if candidates.empty:
        return None
    return candidates.sort_values(["distance_measure_abs", "access_anchor_id"]).iloc[0]


def _leg_record(
    *,
    reference_signal: pd.Series,
    from_anchor: pd.Series,
    to_anchor: pd.Series,
    leg_type: str,
    route_name: object,
    route_id: object,
    route_common: object,
    carriageway_id: object,
    geometry: LineString,
    geometry_status: str,
    geometry_reason: str,
    orientation_label: str,
    orientation_method: str,
) -> dict[str, object]:
    length_ft = geometry.length * FEET_PER_METER
    problem_flags: list[str] = []
    qa_orientation_status = "oriented_geometry_only"
    if length_ft <= 0:
        problem_flags.append("zero_length")
        qa_orientation_status = "unresolved_zero_length_geometry"
    elif length_ft < SHORT_LEG_FT:
        problem_flags.append("short_under_50ft")
        qa_orientation_status = "review_short_leg"
    if geometry_status.startswith("fallback"):
        problem_flags.append("geometry_fallback")
        if qa_orientation_status == "oriented_geometry_only":
            qa_orientation_status = "review_geometry_fallback"
    if leg_type in {"signal_to_road_endpoint", "signal_to_search_cutoff"} and qa_orientation_status == "oriented_geometry_only":
        qa_orientation_status = "support_only_endpoint_leg"

    directed_leg_id = (
        f"dleg_{_slugify(route_name)}_{_slugify(reference_signal['signal_id'])}_"
        f"{_slugify(str(from_anchor['anchor_id']))}_{_slugify(str(to_anchor['anchor_id']))}"
    )
    return {
        "directed_leg_id": directed_leg_id,
        "reference_signal_id": reference_signal["signal_id"],
        "from_anchor_type": from_anchor["anchor_type"],
        "from_anchor_id": from_anchor["anchor_id"],
        "to_anchor_type": to_anchor["anchor_type"],
        "to_anchor_id": to_anchor["anchor_id"],
        "leg_type": leg_type,
        "orientation_label": orientation_label,
        "orientation_method": orientation_method,
        "qa_orientation_status": qa_orientation_status,
        "route_id": route_id,
        "route_name": route_name,
        "route_common": route_common,
        "roadway_carriageway_id": carriageway_id,
        "length_ft": length_ft,
        "from_anchor_measure": float(from_anchor["route_measure_estimate"]),
        "to_anchor_measure": float(to_anchor["route_measure_estimate"]),
        "geometry_status": geometry_status,
        "geometry_reason": geometry_reason,
        "problem_flags": ";".join(problem_flags),
        "true_vehicle_direction_inferred": False,
        "geometry": geometry,
    }


def _build_directed_signal_legs(
    signal_nodes: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    access_anchors: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    usable = signal_nodes.loc[
        signal_nodes["signal_road_match_status"].astype(str).str.startswith("usable")
        & signal_nodes["route_measure_estimate"].notna()
        & signal_nodes["route_name"].notna()
    ].copy()
    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    access_used_records: dict[str, dict[str, object]] = {}
    access_by_route = {route: frame.copy() for route, frame in access_anchors.groupby("route_name", dropna=False)}

    group_fields = ["route_name", "route_id", "roadway_carriageway_id"]
    for group_key, group in usable.groupby(group_fields, dropna=False, sort=True):
        route_name, route_id, carriageway_id = group_key
        route_roads = _route_rows_for_group(roads, route_name, route_id)
        route_common = _clean_text(group["route_common"].dropna().iloc[0]) if group["route_common"].notna().any() else None
        group = group.sort_values(["route_measure_estimate", "signal_id"]).reset_index(drop=True)
        access_group = access_by_route.get(route_name, gpd.GeoDataFrame(columns=access_anchors.columns, geometry="geometry", crs=signal_nodes.crs))

        for index, signal_row in group.iterrows():
            reference_signal = signal_row
            signal_anchor = _signal_anchor_to_series(signal_row)
            neighbors = {
                "lower": group.iloc[index - 1] if index > 0 else None,
                "higher": group.iloc[index + 1] if index < len(group) - 1 else None,
            }
            for side, neighbor in neighbors.items():
                if neighbor is not None:
                    other_anchor = _signal_anchor_to_series(neighbor)
                    from_anchor = signal_anchor
                    to_anchor = other_anchor
                    leg_type = "signal_to_signal"
                    orientation_label = "from_anchor_to_to_anchor" if side == "higher" else "to_anchor_to_from_anchor"
                    orientation_method = f"signal_anchor_to_adjacent_signal_by_{side}_measure"
                else:
                    access_row = _nearest_access_anchor(access_group, float(signal_row["route_measure_estimate"]), side)
                    if access_row is not None:
                        other_anchor = _access_anchor_to_series(access_row)
                        from_anchor = signal_anchor
                        to_anchor = other_anchor
                        leg_type = "signal_to_access"
                        orientation_label = "from_anchor_to_to_anchor" if side == "higher" else "to_anchor_to_from_anchor"
                        orientation_method = f"signal_anchor_to_nearest_access_by_{side}_measure"
                        access_used_records[str(other_anchor["anchor_id"])] = {
                            "access_anchor_id": other_anchor["anchor_id"],
                            "access_source_id": other_anchor.get("access_source_id"),
                            "route_name": route_name,
                            "access_measure": float(other_anchor["route_measure_estimate"]),
                            "used_by_reference_signal_id": signal_row["signal_id"],
                            "used_side": side,
                            "geometry": access_row.geometry,
                        }
                    else:
                        endpoint_anchor = _road_endpoint_anchor(route_roads, side, route_name, signal_nodes.crs)
                        if endpoint_anchor is None:
                            continue
                        from_anchor = signal_anchor
                        to_anchor = endpoint_anchor
                        leg_type = "signal_to_road_endpoint"
                        orientation_label = "from_anchor_to_to_anchor" if side == "higher" else "to_anchor_to_from_anchor"
                        orientation_method = f"signal_anchor_to_road_endpoint_by_{side}_measure"

                geometry, geometry_status, geometry_reason = _geometry_between_anchors(route_roads, from_anchor, to_anchor)
                record = _leg_record(
                    reference_signal=reference_signal,
                    from_anchor=from_anchor,
                    to_anchor=to_anchor,
                    leg_type=leg_type,
                    route_name=route_name,
                    route_id=route_id,
                    route_common=route_common,
                    carriageway_id=carriageway_id,
                    geometry=geometry,
                    geometry_status=geometry_status,
                    geometry_reason=geometry_reason,
                    orientation_label=orientation_label,
                    orientation_method=orientation_method,
                )
                records.append(record)
                geometries.append(geometry)

    legs = gpd.GeoDataFrame(records, geometry=geometries, crs=signal_nodes.crs)
    if access_used_records:
        access_used = gpd.GeoDataFrame(
            list(access_used_records.values()),
            geometry="geometry",
            crs=signal_nodes.crs,
        )
    else:
        access_used = gpd.GeoDataFrame(
            columns=["access_anchor_id", "access_source_id", "route_name", "access_measure", "used_by_reference_signal_id", "used_side", "geometry"],
            geometry="geometry",
            crs=signal_nodes.crs,
        )
    return legs, access_used


def _build_bins(legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    for leg in legs.itertuples(index=False):
        leg_length_ft = float(leg.length_ft)
        if leg_length_ft <= 0 or leg.geometry is None or leg.geometry.is_empty:
            continue
        bin_count = max(1, int(math.ceil(leg_length_ft / BIN_LENGTH_FT)))
        for bin_index in range(bin_count):
            start_ft = bin_index * BIN_LENGTH_FT
            end_ft = min((bin_index + 1) * BIN_LENGTH_FT, leg_length_ft)
            bin_geometry = substring(leg.geometry, start_ft / FEET_PER_METER, end_ft / FEET_PER_METER)
            if not isinstance(bin_geometry, LineString) or bin_geometry.is_empty:
                continue
            records.append(
                {
                    "bin_id": f"{leg.directed_leg_id}_bin_{bin_index:04d}",
                    "directed_leg_id": leg.directed_leg_id,
                    "bin_index": bin_index,
                    "bin_start_ft": start_ft,
                    "bin_end_ft": end_ft,
                    "bin_midpoint_ft": start_ft + ((end_ft - start_ft) / 2.0),
                    "reference_signal_id": leg.reference_signal_id,
                    "from_anchor_type": leg.from_anchor_type,
                    "from_anchor_id": leg.from_anchor_id,
                    "to_anchor_type": leg.to_anchor_type,
                    "to_anchor_id": leg.to_anchor_id,
                    "leg_type": leg.leg_type,
                    "orientation_label": leg.orientation_label,
                }
            )
            geometries.append(bin_geometry)
    return gpd.GeoDataFrame(records, geometry=geometries, crs=legs.crs)


def _build_rejected_or_unresolved_signal_legs(signal_nodes: gpd.GeoDataFrame, legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    generated_signal_ids = set(legs["reference_signal_id"].dropna().astype(str)) if not legs.empty else set()
    rejected_nodes = signal_nodes.loc[~signal_nodes["signal_road_match_status"].astype(str).str.startswith("usable")].copy()
    unresolved_nodes = signal_nodes.loc[
        signal_nodes["signal_road_match_status"].astype(str).str.startswith("usable")
        & ~signal_nodes["signal_id"].astype(str).isin(generated_signal_ids)
    ].copy()
    if not unresolved_nodes.empty:
        unresolved_nodes["signal_road_match_status"] = "usable_no_signal_leg_generated"
        unresolved_nodes["signal_road_match_reason"] = "usable signal did not produce any signal leg"
    return gpd.GeoDataFrame(pd.concat([rejected_nodes, unresolved_nodes], ignore_index=True), geometry="geometry", crs=signal_nodes.crs)


def _build_orientation_review(legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if legs.empty:
        return legs.copy()
    mask = ~legs["qa_orientation_status"].eq("oriented_geometry_only")
    return legs.loc[mask].copy()


def _build_problem_legs(legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if legs.empty:
        return legs.copy()
    return legs.loc[legs["problem_flags"].fillna("").ne("")].copy()


def _summary_frame(name: str, values: dict[object, int]) -> pd.DataFrame:
    return pd.DataFrame({"summary": name, "category": [str(key) for key in values.keys()], "value": [int(value) for value in values.values()]})


def _build_anchor_summary(signal_nodes: gpd.GeoDataFrame, legs: gpd.GeoDataFrame, access_used: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = [
        {"summary": "count", "category": "signal_nodes", "value": len(signal_nodes)},
        {"summary": "count", "category": "directed_signal_legs", "value": len(legs)},
        {"summary": "count", "category": "access_anchors_used", "value": len(access_used)},
        {
            "summary": "count",
            "category": "signals_with_any_leg",
            "value": int(legs["reference_signal_id"].nunique()) if not legs.empty else 0,
        },
    ]
    parts = [pd.DataFrame(rows)]
    if not legs.empty:
        parts.append(_summary_frame("leg_type", legs["leg_type"].value_counts(dropna=False).to_dict()))
        parts.append(_summary_frame("to_anchor_type", legs["to_anchor_type"].value_counts(dropna=False).to_dict()))
        parts.append(_summary_frame("qa_orientation_status", legs["qa_orientation_status"].value_counts(dropna=False).to_dict()))
        parts.append(_summary_frame("orientation_method", legs["orientation_method"].value_counts(dropna=False).to_dict()))
    return pd.concat(parts, ignore_index=True)


def _build_signal_node_summary(signal_nodes: gpd.GeoDataFrame, unresolved: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "signal_node_rows", "value": len(signal_nodes)},
        {
            "metric": "usable_signal_node_rows",
            "value": int(signal_nodes["signal_road_match_status"].astype(str).str.startswith("usable").sum()),
        },
        {"metric": "rejected_or_unresolved_signal_rows", "value": len(unresolved)},
        {"metric": "unique_route_names", "value": int(signal_nodes["route_name"].nunique(dropna=True))},
    ]
    rows.extend(
        {"metric": f"match_status_{key}", "value": int(value)}
        for key, value in signal_nodes["signal_road_match_status"].value_counts(dropna=False).to_dict().items()
    )
    return pd.DataFrame(rows)


def _build_leg_summary(legs: gpd.GeoDataFrame, bins: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "directed_signal_leg_rows", "value": len(legs)},
        {"metric": "directed_signal_leg_bin_rows", "value": len(bins)},
        {"metric": "unique_route_names", "value": int(legs["route_name"].nunique(dropna=True)) if not legs.empty else 0},
        {"metric": "true_vehicle_direction_inferred_rows", "value": 0},
        {"metric": "short_under_50ft_rows", "value": int(legs["length_ft"].lt(SHORT_LEG_FT).sum()) if not legs.empty else 0},
    ]
    if not legs.empty:
        rows.extend(
            {"metric": f"leg_type_{key}", "value": int(value)}
            for key, value in legs["leg_type"].value_counts(dropna=False).to_dict().items()
        )
        rows.extend(
            {"metric": f"qa_orientation_status_{key}", "value": int(value)}
            for key, value in legs["qa_orientation_status"].value_counts(dropna=False).to_dict().items()
        )
        rows.extend(
            {"metric": f"geometry_status_{key}", "value": int(value)}
            for key, value in legs["geometry_status"].value_counts(dropna=False).to_dict().items()
        )
    return pd.DataFrame(rows)


def _build_readme(output_files: dict[str, str], output_root: Path) -> str:
    current_sections = [
        ("tables/current", TABLES_CURRENT_SUBDIR),
        ("review/current", REVIEW_CURRENT_SUBDIR),
        ("review/geojson/current", REVIEW_GEOJSON_CURRENT_SUBDIR),
        ("runs/current", RUNS_CURRENT_SUBDIR),
    ]
    lines = [
        "# Directed Signal-Leg Outputs",
        "",
        "This folder contains the road-network-first directed signal-leg workflow outputs.",
        "The workflow does not infer true vehicle travel direction. It only creates oriented A-to-B geometries so one anchor order can be distinguished from the reciprocal order.",
        "",
        "The older signal-pair-only outputs, if present in this folder, are superseded by `directed_signal_legs.csv` and `directed_signal_leg_bins_50ft.csv`.",
        "",
        "## Current outputs",
    ]
    for label, parts in current_sections:
        section_path = output_root.joinpath(*parts)
        matching = sorted(
            str(Path(path).relative_to(output_root))
            for path in output_files.values()
            if path and Path(path).exists() and section_path in Path(path).parents
        )
        lines.append(f"- `{label}`")
        if not matching:
            lines.append("  - none written in this run")
            continue
        for relative_path in matching:
            lines.append(f"  - `{relative_path}`")
    lines.extend(
        [
            "",
            "## History folders",
            "- `tables/history/`, `review/history/`, `review/geojson/history/`, and `runs/history/` preserve timestamped copies from each successful run.",
            "- Files in `current/` are the stable handoff paths.",
            "- `orientation_review.csv` is a geometry/orientation QA queue, not a vehicle-travel direction conflict table.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_directed_segment_workflow(
    *,
    study_slice_root: Path | None = None,
    normalized_root: Path | None = None,
    output_root: Path | None = None,
    run_label: str | None = None,
) -> int:
    config = load_runtime_config()
    resolved_study_slice_root = study_slice_root or config.output_dir / "stage1b_study_slice"
    resolved_normalized_root = normalized_root or config.normalized_dir
    resolved_output_root = output_root or config.output_dir / OUTPUT_FOLDER_NAME
    layout = _build_layout(resolved_output_root)

    roads = _load_study_roads(resolved_study_slice_root)
    signals = _load_study_signals(resolved_study_slice_root)
    signal_nodes = _make_signal_nodes(signals, roads)
    access_anchors = _load_access_anchors(resolved_normalized_root, signal_nodes.crs)
    directed_legs, access_used = _build_directed_signal_legs(signal_nodes, roads, access_anchors)
    bins = _build_bins(directed_legs)
    unresolved_legs = _build_rejected_or_unresolved_signal_legs(signal_nodes, directed_legs)
    orientation_review = _build_orientation_review(directed_legs)
    short_or_problem = _build_problem_legs(directed_legs)
    anchor_summary = _build_anchor_summary(signal_nodes, directed_legs, access_used)
    signal_node_summary = _build_signal_node_summary(signal_nodes, unresolved_legs)
    leg_summary = _build_leg_summary(directed_legs, bins)

    output_files: dict[str, str] = {}
    output_files["signal_nodes_csv"] = str(_write_csv_frame(signal_nodes, layout.tables_current / "signal_nodes.csv", layout.tables_history))
    output_files["directed_signal_legs_csv"] = str(
        _write_csv_frame(directed_legs, layout.tables_current / "directed_signal_legs.csv", layout.tables_history)
    )
    output_files["directed_signal_leg_bins_50ft_csv"] = str(
        _write_csv_frame(bins, layout.tables_current / "directed_signal_leg_bins_50ft.csv", layout.tables_history)
    )
    output_files["rejected_or_unresolved_signal_legs_csv"] = str(
        _write_csv_frame(unresolved_legs, layout.tables_current / "rejected_or_unresolved_signal_legs.csv", layout.tables_history)
    )
    output_files["orientation_review_csv"] = str(
        _write_csv_frame(orientation_review, layout.tables_current / "orientation_review.csv", layout.tables_history)
    )
    output_files["short_or_problem_legs_csv"] = str(
        _write_csv_frame(short_or_problem, layout.tables_current / "short_or_problem_legs.csv", layout.tables_history)
    )
    output_files["anchor_summary_csv"] = str(_write_csv_frame(anchor_summary, layout.tables_current / "anchor_summary.csv", layout.tables_history))
    output_files["signal_node_summary_csv"] = str(
        _write_csv_frame(signal_node_summary, layout.tables_current / "signal_node_summary.csv", layout.tables_history)
    )
    output_files["directed_signal_leg_summary_csv"] = str(
        _write_csv_frame(leg_summary, layout.tables_current / "directed_signal_leg_summary.csv", layout.tables_history)
    )

    geojson_outputs = {
        "signal_nodes_geojson": _write_geojson_frame(signal_nodes, layout.review_geojson_current / "signal_nodes.geojson", layout.review_geojson_history),
        "directed_signal_legs_geojson": _write_geojson_frame(
            directed_legs, layout.review_geojson_current / "directed_signal_legs.geojson", layout.review_geojson_history
        ),
        "directed_signal_leg_bins_50ft_geojson": _write_geojson_frame(
            bins, layout.review_geojson_current / "directed_signal_leg_bins_50ft.geojson", layout.review_geojson_history
        ),
        "rejected_or_unresolved_signal_legs_geojson": _write_geojson_frame(
            unresolved_legs, layout.review_geojson_current / "rejected_or_unresolved_signal_legs.geojson", layout.review_geojson_history
        ),
        "orientation_review_geojson": _write_geojson_frame(
            orientation_review, layout.review_geojson_current / "orientation_review.geojson", layout.review_geojson_history
        ),
        "access_anchors_used_geojson": _write_geojson_frame(
            access_used, layout.review_geojson_current / "access_anchors_used.geojson", layout.review_geojson_history
        ),
    }
    output_files.update({key: str(path) for key, path in geojson_outputs.items() if path is not None})

    superseded_note = _write_text_file(
        "The older signal-pair-only files `directed_signal_segments.*`, `directed_segment_bins_50ft.*`, "
        "`direction_conflict_review.*`, and `short_or_problem_segments.*` are superseded by the signal-leg outputs. "
        "They may remain in current folders as historical residue until a cleanup pass removes them.\n",
        layout.review_current / "superseded_signal_pair_outputs.txt",
        layout.review_history,
    )
    output_files["superseded_signal_pair_outputs_note"] = str(superseded_note)

    run_summary = {
        "task": "road-network-first oriented signal-leg and 50-foot bin workflow",
        "run_label": run_label,
        "run_timestamp": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "study_roads_divided": str(resolved_study_slice_root / "Study_Roads_Divided.parquet"),
            "study_signals_nearest_road": str(resolved_study_slice_root / "Study_Signals_NearestRoad.parquet"),
            "access_points": str(resolved_normalized_root / "access.parquet"),
            "crash_data_used": False,
        },
        "method_scope": {
            "roadway_scope": "divided roads from Study_Roads_Divided",
            "orientation_evidence": "fixed anchor order, route/carriageway grouping, roadway geometry, and route measure order only",
            "true_vehicle_direction_inferred": False,
            "crash_classification_logic_modified": False,
            "crash_direction_used": False,
            "supersedes": "older signal-pair-only directed_signal_segments output",
        },
        "counts": {
            "source_road_rows": int(len(roads)),
            "source_signal_rows": int(len(signals)),
            "source_access_rows": int(len(access_anchors)),
            "signal_node_rows": int(len(signal_nodes)),
            "directed_signal_leg_rows": int(len(directed_legs)),
            "directed_signal_leg_bin_rows": int(len(bins)),
            "access_anchors_used_rows": int(len(access_used)),
            "rejected_or_unresolved_signal_leg_rows": int(len(unresolved_legs)),
            "short_or_problem_leg_rows": int(len(short_or_problem)),
            "orientation_review_rows": int(len(orientation_review)),
        },
        "validation": {
            "checked": [
                "input row counts",
                "signal-road match status counts",
                "directed signal-leg counts",
                "50-foot bin counts",
                "anchor summary counts",
                "short/problem leg queue",
                "orientation review queue",
                "GeoJSON review layer export",
            ],
            "not_checked": [
                "manual map spot checks",
                "comparison to external roadway orientation source",
                "true vehicle travel direction",
                "crash assignment or crash classification validation",
            ],
        },
        "output_files": output_files,
    }
    output_files["run_summary_json"] = str(layout.runs_current / "run_summary.json")
    readme_path = _write_text_file(_build_readme(output_files, layout.root), layout.root / "README.md")
    output_files["readme"] = str(readme_path)
    run_summary["output_files"] = output_files
    _write_json_object(run_summary, layout.runs_current / "run_summary.json", layout.runs_history)
    print(json.dumps(run_summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build oriented signal-anchored divided-road legs and 50-foot bins.")
    parser.add_argument(
        "--study-slice-root",
        type=Path,
        default=None,
        help="Folder containing Study_Roads_Divided.parquet and Study_Signals_NearestRoad.parquet.",
    )
    parser.add_argument(
        "--normalized-root",
        type=Path,
        default=None,
        help="Folder containing normalized access.parquet. Defaults to artifacts/normalized.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Directed segment output root. Defaults to work/output/directed_segments.",
    )
    parser.add_argument("--run-label", default=None, help="Optional label stored in run_summary.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_directed_segment_workflow(
        study_slice_root=args.study_slice_root,
        normalized_root=args.normalized_root,
        output_root=args.output_root,
        run_label=args.run_label,
    )
