from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from geopandas.array import GeometryDtype
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, substring, unary_union
import pyogrio

from .config import load_runtime_config
from .directionality_experiment import (
    EMPIRICAL_90_RULE_NAME,
    STRICT_RULE_NAME,
    _load_crashes,
    _load_signals,
    _load_study_roads,
)


OUTPUT_FOLDER_NAME = "upstream_downstream_prototype"
DIRECTIONALITY_OUTPUT_FOLDER_NAME = "directionality_experiment"
TABLES_CURRENT_SUBDIR = ("tables", "current")
TABLES_HISTORY_SUBDIR = ("tables", "history")
REVIEW_CURRENT_SUBDIR = ("review", "current")
REVIEW_HISTORY_SUBDIR = ("review", "history")
REVIEW_GEOJSON_CURRENT_SUBDIR = ("review", "geojson", "current")
REVIEW_GEOJSON_HISTORY_SUBDIR = ("review", "geojson", "history")
REVIEW_GEOPACKAGE_CURRENT_SUBDIR = ("review", "geopackage", "current")
REVIEW_GEOPACKAGE_HISTORY_SUBDIR = ("review", "geopackage", "history")
RUNS_CURRENT_SUBDIR = ("runs", "current")
RUNS_HISTORY_SUBDIR = ("runs", "history")
STUDY_AREA_BUFFER_METERS = 250.0
SIGNAL_AMBIGUITY_TOLERANCE_METERS = 15.0
CRASH_TO_ROW_HIGH_DISTANCE_METERS = 25.0
CRASH_TO_ROW_MAX_DISTANCE_METERS = 50.0
SAME_LOCATION_TOLERANCE_METERS = 5.0
APPROACH_ROW_SEARCH_METERS = 75.0
APPROACH_BUFFER_METERS = 18.0
SIGNAL_HUB_BUFFER_METERS = 20.0
SPEED_SEARCH_MAX_DISTANCE_METERS = 50.0
DEFAULT_SPEED_MPH = 35
CIRCLE_STUDY_AREA_TYPE = "circle250m"
APPROACH_STUDY_AREA_TYPE = "approach_shaped"
FLOW_PROVENANCE_CATEGORY = {
    STRICT_RULE_NAME: "strict_empirical",
    EMPIRICAL_90_RULE_NAME: "empirical90",
}
FUNCTIONAL_DISTANCES_FEET = {
    25: (155, 355),
    30: (200, 450),
    35: (250, 550),
    40: (305, 680),
    45: (360, 810),
    50: (425, 950),
    55: (495, 1100),
}


def _output_subdir(output_dir: Path, *parts: str) -> Path:
    path = output_dir.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_output_path(path: Path, history_dir: Path | None = None) -> Path:
    if not path.exists():
        return path
    try:
        path.unlink()
        return path
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if history_dir is not None:
            history_dir.mkdir(parents=True, exist_ok=True)
            return history_dir / f"{path.stem}_{stamp}{path.suffix}"
        return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def _write_csv_frame(frame: pd.DataFrame, path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    frame.to_csv(resolved, index=False)
    return resolved


def _write_json_object(payload: dict[str, object], path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return resolved


def _write_text_file(content: str, path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    resolved.write_text(content, encoding="utf-8")
    return resolved


def _prepare_export_frame(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    export = frame.copy()
    active_geometry = export.geometry.name
    for column in export.columns:
        if column == active_geometry:
            continue
        series = export[column]
        if isinstance(series.dtype, GeometryDtype):
            export[column] = series.to_wkt()
            continue
        if series.dtype != "object":
            continue
        has_geometry = series.map(lambda value: hasattr(value, "geom_type") if value is not None and not pd.isna(value) else False)
        if bool(has_geometry.any()):
            export[column] = series.map(
                lambda value: value.wkt if value is not None and not pd.isna(value) and hasattr(value, "wkt") else None
            )
    return export


def _write_review_geopackage(
    output_dir: Path,
    study_areas: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    attached_rows: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    unresolved: gpd.GeoDataFrame | None = None,
) -> Path | None:
    review_dir = _output_subdir(output_dir, *REVIEW_GEOPACKAGE_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_GEOPACKAGE_HISTORY_SUBDIR)
    gpkg_path = _prepare_output_path(review_dir / "review_layers.gpkg", history_dir=review_history_dir)
    if gpkg_path.exists():
        gpkg_path.unlink()
    first_layer = True
    try:
        layers: list[tuple[str, gpd.GeoDataFrame | None]] = [
            ("study_areas", study_areas),
            ("signals", signals),
            ("attached_rows", attached_rows),
            ("crashes", crashes),
            ("unresolved_crashes", unresolved),
        ]
        for layer_name, frame in layers:
            if frame is None or frame.empty:
                continue
            _prepare_export_frame(frame).to_file(
                gpkg_path,
                layer=layer_name,
                driver="GPKG",
                mode="w" if first_layer else "a",
            )
            first_layer = False
        return gpkg_path if not first_layer else None
    except Exception:
        if gpkg_path.exists():
            try:
                gpkg_path.unlink()
            except PermissionError:
                pass
        return None


def _write_review_geojson_layers(
    output_dir: Path,
    study_areas: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    attached_rows: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    unresolved: gpd.GeoDataFrame | None = None,
) -> dict[str, str]:
    review_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_HISTORY_SUBDIR)
    outputs: dict[str, str] = {}
    for layer_name, frame in (
        ("study_areas", study_areas),
        ("signals", signals),
        ("attached_rows", attached_rows),
        ("crashes", crashes),
        ("unresolved_crashes", unresolved),
    ):
        if frame is None or frame.empty:
            continue
        path = _prepare_output_path(review_dir / f"{layer_name}.geojson", history_dir=review_history_dir)
        _prepare_export_frame(frame).to_file(path, driver="GeoJSON")
        outputs[layer_name] = str(path)
    return outputs


def _latest_assignment_table_path(config) -> Path:
    directionality_output_dir = config.output_dir / DIRECTIONALITY_OUTPUT_FOLDER_NAME
    candidate_paths: list[Path] = []
    current_path = directionality_output_dir / "tables" / "current" / "expanded_scope" / "expanded_assignment_table.csv"
    if current_path.exists():
        candidate_paths.append(current_path)
    candidate_paths.extend((directionality_output_dir / "tables" / "history").rglob("expanded_assignment_table*.csv"))
    candidate_paths.extend(directionality_output_dir.glob("expanded_assignment_table*.csv"))
    candidates = sorted(candidate_paths, key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("No expanded directionality assignment table was found under work/output/directionality_experiment/.")
    return candidates[0]


def _signal_label(row: pd.Series) -> str:
    name_parts = [str(row.get("MAJ_NAME", "")).strip(), str(row.get("MINOR_NAME", "")).strip()]
    names = [part for part in name_parts if part and part.lower() != "nan"]
    if names:
        return " / ".join(names)
    for field in ("REG_SIGNAL_ID", "SIGNAL_NO", "INTNO"):
        value = row.get(field)
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip()
    return f"signal_{int(row['Signal_RowID'])}"


def _load_flow_assignments(config) -> tuple[pd.DataFrame, Path]:
    assignment_path = _latest_assignment_table_path(config)
    frame = pd.read_csv(
        assignment_path,
        usecols=[
            "StudyRoad_RowID",
            "RTE_NM",
            "WindowFromMeasure",
            "WindowToMeasure",
            "StrictUnanimousStatus",
            "StrictUnanimousAssignedDirection",
            "Empirical90PctStatus",
            "Empirical90PctAssignedDirection",
            "PrimaryDominantDirection",
            "PrimaryDominantShare",
            "PrimaryHasConflict",
            "ReviewPriorityClass",
            "ReviewPriorityReason",
        ],
    )
    frame["StudyRoad_RowID"] = pd.to_numeric(frame["StudyRoad_RowID"], errors="coerce").astype("Int64")
    frame["FlowDirection"] = None
    frame["FlowProvenance"] = "unresolved"
    strict_mask = frame["StrictUnanimousStatus"].eq("assigned")
    empirical_mask = ~strict_mask & frame["Empirical90PctStatus"].eq("assigned")
    frame.loc[strict_mask, "FlowDirection"] = frame.loc[strict_mask, "StrictUnanimousAssignedDirection"]
    frame.loc[strict_mask, "FlowProvenance"] = STRICT_RULE_NAME
    frame.loc[empirical_mask, "FlowDirection"] = frame.loc[empirical_mask, "Empirical90PctAssignedDirection"]
    frame.loc[empirical_mask, "FlowProvenance"] = EMPIRICAL_90_RULE_NAME
    frame["HasPrototypeFlow"] = frame["FlowDirection"].notna()
    return frame, assignment_path


def _load_speed_segments(config) -> gpd.GeoDataFrame:
    path = config.raw_data_dir / "postedspeedlimits.gdb"
    layer_name = "SDE_VDOT_SPEED_LIMIT_MSTR_RTE"
    frame = pyogrio.read_dataframe(
        path,
        layer=layer_name,
        columns=["CAR_SPEED_LIMIT"],
    )
    speed_segments = gpd.GeoDataFrame(frame, geometry="geometry")
    if speed_segments.crs is None:
        raise ValueError("Speed segments have no CRS; cannot build speed-informed study areas.")
    return speed_segments.to_crs(config.working_crs)


def _functional_distance_for_speed(speed_value: object) -> tuple[int, int, int, float]:
    speed = pd.to_numeric(pd.Series([speed_value]), errors="coerce").iloc[0]
    if pd.isna(speed) or float(speed) < 15:
        assigned_speed = DEFAULT_SPEED_MPH
    else:
        assigned_speed = int(round(float(speed)))
    lookup_speed = min(FUNCTIONAL_DISTANCES_FEET.keys(), key=lambda candidate: abs(candidate - assigned_speed))
    dist_lim_ft, dist_des_ft = FUNCTIONAL_DISTANCES_FEET[lookup_speed]
    return assigned_speed, int(dist_lim_ft), int(dist_des_ft), float(dist_des_ft) * 0.3048


def _attach_signal_speed(signal_frame: gpd.GeoDataFrame, speed_segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    speed_join = gpd.sjoin_nearest(
        signal_frame[["Signal_RowID", "geometry"]].copy(),
        speed_segments[["CAR_SPEED_LIMIT", "geometry"]].copy(),
        how="left",
        max_distance=SPEED_SEARCH_MAX_DISTANCE_METERS,
        distance_col="SpeedJoinDistanceMeters",
    ).drop(columns=["index_right"])
    speed_join = speed_join.sort_values(["Signal_RowID", "SpeedJoinDistanceMeters"]).drop_duplicates(
        subset=["Signal_RowID"],
        keep="first",
    )
    speed_join[["AssignedSpeedMph", "FunctionalDistLimFt", "FunctionalDistDesFt", "ApproachLengthMeters"]] = speed_join[
        "CAR_SPEED_LIMIT"
    ].apply(_functional_distance_for_speed).apply(pd.Series)
    speed_join["SpeedAssignmentSource"] = speed_join["CAR_SPEED_LIMIT"].map(
        lambda value: "raw_speed_join" if pd.notna(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]) else "default_speed"
    )
    merged = signal_frame.merge(
        speed_join[
            [
                "Signal_RowID",
                "CAR_SPEED_LIMIT",
                "AssignedSpeedMph",
                "FunctionalDistLimFt",
                "FunctionalDistDesFt",
                "ApproachLengthMeters",
                "SpeedAssignmentSource",
                "SpeedJoinDistanceMeters",
            ]
        ],
        on="Signal_RowID",
        how="left",
        validate="one_to_one",
    )
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=signal_frame.crs)


def _normalize_line_geometry(geometry) -> LineString | None:
    if geometry is None:
        return None
    geom = geometry
    if isinstance(geom, LineString):
        return geom if not geom.is_empty and geom.length > 0 else None
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged if merged.length > 0 else None
        if isinstance(merged, MultiLineString):
            parts = [part for part in merged.geoms if isinstance(part, LineString) and part.length > 0]
            if not parts:
                return None
            return max(parts, key=lambda part: part.length)
    return None


def _flow_matches_line_direction(line: LineString, cardinal_direction: object) -> bool | None:
    if line is None or cardinal_direction is None or pd.isna(cardinal_direction):
        return None
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    start_x, start_y = coords[0][:2]
    end_x, end_y = coords[-1][:2]
    direction = str(cardinal_direction).strip()
    if direction == "North":
        if end_y == start_y:
            return None
        return end_y > start_y
    if direction == "South":
        if end_y == start_y:
            return None
        return end_y < start_y
    if direction == "East":
        if end_x == start_x:
            return None
        return end_x > start_x
    if direction == "West":
        if end_x == start_x:
            return None
        return end_x < start_x
    return None


def _build_signal_prototype_frame(
    signals: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    flow_assignments: pd.DataFrame,
) -> gpd.GeoDataFrame:
    road_columns = roads.rename(
        columns={
            "RTE_NM": "AttachedRoad_RTE_NM",
            "RTE_COMMON": "AttachedRoad_RTE_COMMON",
            "FROM_MEASURE": "AttachedRoad_FROM_MEASURE",
            "TO_MEASURE": "AttachedRoad_TO_MEASURE",
            "geometry": "AttachedRoadGeometry",
        }
    )
    merged = signals.merge(
        flow_assignments,
        left_on="NearestRoad_RowID",
        right_on="StudyRoad_RowID",
        how="left",
        validate="many_to_one",
    ).merge(
        road_columns[
            [
                "StudyRoad_RowID",
                "AttachedRoad_RTE_NM",
                "AttachedRoad_RTE_COMMON",
                "AttachedRoad_FROM_MEASURE",
                "AttachedRoad_TO_MEASURE",
                "AttachedRoadGeometry",
            ]
        ],
        on="StudyRoad_RowID",
        how="left",
        validate="many_to_one",
    )
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=signals.crs)
    merged["SignalLabel"] = merged.apply(_signal_label, axis=1)
    merged["StudyAreaID"] = merged["Signal_RowID"].map(lambda value: f"signal_{int(value)}")
    merged["SignalRouteName"] = merged["NearestRoad_RTE_NM"]
    merged["FlowStatus"] = merged["HasPrototypeFlow"].fillna(False).map(lambda value: "assigned" if bool(value) else "unresolved")
    eligible = merged.loc[merged["HasPrototypeFlow"].fillna(False).astype(bool)].copy()
    eligible["StudyAreaBufferMeters"] = STUDY_AREA_BUFFER_METERS
    return eligible


def _build_circle_study_areas(signal_frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    study_areas = signal_frame[
        [
            "StudyAreaID",
            "Signal_RowID",
            "REG_SIGNAL_ID",
            "SIGNAL_NO",
            "SignalLabel",
            "SignalRouteName",
            "FlowDirection",
            "FlowProvenance",
            "StudyAreaBufferMeters",
            "AssignedSpeedMph",
            "ApproachLengthMeters",
            "SpeedAssignmentSource",
        ]
    ].copy()
    study_areas = gpd.GeoDataFrame(
        study_areas,
        geometry=signal_frame.geometry.buffer(STUDY_AREA_BUFFER_METERS),
        crs=signal_frame.crs,
    )
    study_areas["StudyAreaType"] = CIRCLE_STUDY_AREA_TYPE
    study_areas["ApproachRowCount"] = 0
    return study_areas


def _candidate_approach_rows(
    signal_row: pd.Series,
    route_groups: dict[str, gpd.GeoDataFrame],
) -> gpd.GeoDataFrame:
    route_rows = route_groups.get(str(signal_row["SignalRouteName"]), gpd.GeoDataFrame())
    if route_rows.empty:
        return route_rows
    signal_geom = signal_row.geometry
    distances = route_rows.geometry.distance(signal_geom)
    candidates = route_rows.loc[distances.le(APPROACH_ROW_SEARCH_METERS)].copy()
    if candidates.empty:
        attached = route_rows.loc[route_rows["StudyRoad_RowID"].eq(signal_row["StudyRoad_RowID"])].copy()
        if not attached.empty:
            candidates = attached
    elif not candidates["StudyRoad_RowID"].eq(signal_row["StudyRoad_RowID"]).any():
        attached = route_rows.loc[route_rows["StudyRoad_RowID"].eq(signal_row["StudyRoad_RowID"])].copy()
        if not attached.empty:
            candidates = pd.concat([candidates, attached], ignore_index=True)
            candidates = gpd.GeoDataFrame(candidates, geometry="geometry", crs=route_rows.crs)
    return candidates.drop_duplicates(subset=["StudyRoad_RowID"]).copy()


def _build_approach_shaped_study_areas(
    signal_frame: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    route_groups = {route_name: frame.copy() for route_name, frame in roads.groupby("RTE_NM", dropna=False)}
    study_area_rows: list[dict[str, object]] = []
    approach_row_records: list[dict[str, object]] = []

    for signal in signal_frame.itertuples(index=False):
        signal_series = pd.Series(signal._asdict())
        candidate_rows = _candidate_approach_rows(signal_series, route_groups)
        signal_segments = []
        for row in candidate_rows.itertuples(index=False):
            line = _normalize_line_geometry(row.geometry)
            if line is None:
                continue
            center = float(line.project(signal.geometry))
            half_length = float(signal.ApproachLengthMeters)
            start = max(0.0, center - half_length)
            end = min(float(line.length), center + half_length)
            if end <= start:
                continue
            segment = substring(line, start, end)
            if segment is None or segment.is_empty or getattr(segment, "length", 0.0) < 1.0:
                continue
            signal_segments.append(segment)
            approach_row_records.append(
                {
                    "StudyAreaID": signal.StudyAreaID,
                    "Signal_RowID": int(signal.Signal_RowID),
                    "REG_SIGNAL_ID": signal.REG_SIGNAL_ID,
                    "SIGNAL_NO": signal.SIGNAL_NO,
                    "SignalLabel": signal.SignalLabel,
                    "SignalRouteName": signal.SignalRouteName,
                    "StudyAreaType": APPROACH_STUDY_AREA_TYPE,
                    "StudyRoad_RowID": int(row.StudyRoad_RowID),
                    "ApproachLengthMeters": half_length,
                    "AssignedSpeedMph": int(signal.AssignedSpeedMph),
                    "SpeedAssignmentSource": signal.SpeedAssignmentSource,
                    "geometry": segment,
                }
            )

        if signal_segments:
            buffers = [segment.buffer(APPROACH_BUFFER_METERS, cap_style=2) for segment in signal_segments]
            buffers.append(signal.geometry.buffer(SIGNAL_HUB_BUFFER_METERS))
            study_geometry = unary_union(buffers)
        else:
            study_geometry = signal.geometry.buffer(SIGNAL_HUB_BUFFER_METERS)

        study_area_rows.append(
            {
                "StudyAreaID": signal.StudyAreaID,
                "Signal_RowID": int(signal.Signal_RowID),
                "REG_SIGNAL_ID": signal.REG_SIGNAL_ID,
                "SIGNAL_NO": signal.SIGNAL_NO,
                "SignalLabel": signal.SignalLabel,
                "SignalRouteName": signal.SignalRouteName,
                "FlowDirection": signal.FlowDirection,
                "FlowProvenance": signal.FlowProvenance,
                "StudyAreaBufferMeters": STUDY_AREA_BUFFER_METERS,
                "AssignedSpeedMph": int(signal.AssignedSpeedMph),
                "ApproachLengthMeters": float(signal.ApproachLengthMeters),
                "SpeedAssignmentSource": signal.SpeedAssignmentSource,
                "StudyAreaType": APPROACH_STUDY_AREA_TYPE,
                "ApproachRowCount": int(len(signal_segments)),
                "geometry": study_geometry,
            }
        )

    study_areas = gpd.GeoDataFrame(study_area_rows, geometry="geometry", crs=signal_frame.crs)
    approach_rows = gpd.GeoDataFrame(approach_row_records, geometry="geometry", crs=signal_frame.crs)
    return study_areas, approach_rows


def _summarize_signal_candidate_group(group: pd.DataFrame) -> dict[str, object]:
    overall = group.sort_values(["SignalDistanceMeters", "Signal_RowID"]).reset_index(drop=True)
    compatible = overall.loc[overall["RouteCompatible"]].reset_index(drop=True)
    selected = compatible.iloc[0] if not compatible.empty else overall.iloc[0]
    result = {
        "StudyAreaID": selected["StudyAreaID"],
        "StudyAreaType": selected["StudyAreaType"],
        "Signal_RowID": int(selected["Signal_RowID"]),
        "REG_SIGNAL_ID": selected["REG_SIGNAL_ID"],
        "SIGNAL_NO": selected["SIGNAL_NO"],
        "SignalLabel": selected["SignalLabel"],
        "SignalRouteName": selected["SignalRouteName"],
        "CandidateSignalCount": int(len(overall)),
        "CompatibleSignalCount": int(len(compatible)),
        "SignalDistanceMeters": float(selected["SignalDistanceMeters"]),
        "SignalAssociationMethod": "nearest_signal_in_study_area_same_route",
        "SignalAssociationStatus": "assigned",
        "SignalAssociationReason": "nearest same-route eligible signal within the study-area window",
        "SignalAmbiguityDeltaMeters": None,
        "StudyAreaBufferMeters": STUDY_AREA_BUFFER_METERS,
        "AssignedSpeedMph": int(selected["AssignedSpeedMph"]) if not pd.isna(selected["AssignedSpeedMph"]) else None,
        "ApproachLengthMeters": float(selected["ApproachLengthMeters"]) if not pd.isna(selected["ApproachLengthMeters"]) else None,
        "SpeedAssignmentSource": selected["SpeedAssignmentSource"],
        "StudyRoad_RowID": int(selected["StudyRoad_RowID"]) if not pd.isna(selected["StudyRoad_RowID"]) else None,
        "AttachedRoad_RTE_NM": selected["AttachedRoad_RTE_NM"],
        "AttachedRoad_RTE_COMMON": selected["AttachedRoad_RTE_COMMON"],
        "AttachedRoad_FROM_MEASURE": float(selected["AttachedRoad_FROM_MEASURE"]) if not pd.isna(selected["AttachedRoad_FROM_MEASURE"]) else None,
        "AttachedRoad_TO_MEASURE": float(selected["AttachedRoad_TO_MEASURE"]) if not pd.isna(selected["AttachedRoad_TO_MEASURE"]) else None,
        "AttachedRoadGeometry": selected["AttachedRoadGeometry"],
        "FlowDirection": selected["FlowDirection"],
        "FlowProvenance": selected["FlowProvenance"],
        "StrictUnanimousStatus": selected["StrictUnanimousStatus"],
        "Empirical90PctStatus": selected["Empirical90PctStatus"],
        "PrimaryDominantDirection": selected["PrimaryDominantDirection"],
        "PrimaryDominantShare": float(selected["PrimaryDominantShare"]) if not pd.isna(selected["PrimaryDominantShare"]) else None,
        "PrimaryHasConflict": bool(selected["PrimaryHasConflict"]) if not pd.isna(selected["PrimaryHasConflict"]) else False,
        "ReviewPriorityClass": selected["ReviewPriorityClass"],
        "ReviewPriorityReason": selected["ReviewPriorityReason"],
        "SignalGeometry": selected["SignalGeometry"],
    }
    if compatible.empty:
        result["SignalAssociationStatus"] = "unresolved"
        result["SignalAssociationReason"] = "study-area crash has no same-route eligible signal candidate"
        result["SignalAssociationMethod"] = "study_area_intersection_then_route_check"
        return result

    if len(compatible) > 1:
        ambiguity_delta = float(compatible.iloc[1]["SignalDistanceMeters"] - compatible.iloc[0]["SignalDistanceMeters"])
        result["SignalAmbiguityDeltaMeters"] = ambiguity_delta
        if ambiguity_delta <= SIGNAL_AMBIGUITY_TOLERANCE_METERS:
            result["SignalAssociationStatus"] = "unresolved"
            result["SignalAssociationReason"] = "multiple same-route signals are nearly equally near the crash"
            result["SignalAssociationMethod"] = "nearest_signal_same_route_ambiguous"
            return result
    return result


def _attach_crashes_to_signals(
    crashes: gpd.GeoDataFrame,
    signal_frame: gpd.GeoDataFrame,
    study_areas: gpd.GeoDataFrame,
) -> pd.DataFrame:
    crashes = crashes.reset_index(names="Crash_RowID").copy()
    crashes["Crash_RowID"] = crashes["Crash_RowID"].astype(int)

    study_area_columns = [
        "StudyAreaID",
        "StudyAreaType",
        "Signal_RowID",
        "REG_SIGNAL_ID",
        "SIGNAL_NO",
        "SignalLabel",
        "SignalRouteName",
        "AssignedSpeedMph",
        "ApproachLengthMeters",
        "SpeedAssignmentSource",
        "geometry",
    ]
    joined = gpd.sjoin(
        crashes,
        study_areas[study_area_columns],
        how="inner",
        predicate="within",
    ).drop(columns=["index_right"])
    if joined.empty:
        return pd.DataFrame()

    signal_lookup = signal_frame[
        [
            "Signal_RowID",
            "geometry",
            "StudyAreaID",
            "REG_SIGNAL_ID",
            "SIGNAL_NO",
            "SignalLabel",
            "SignalRouteName",
            "AssignedSpeedMph",
            "ApproachLengthMeters",
            "SpeedAssignmentSource",
            "StudyRoad_RowID",
            "AttachedRoad_RTE_NM",
            "AttachedRoad_RTE_COMMON",
            "AttachedRoad_FROM_MEASURE",
            "AttachedRoad_TO_MEASURE",
            "AttachedRoadGeometry",
            "FlowDirection",
            "FlowProvenance",
            "StrictUnanimousStatus",
            "Empirical90PctStatus",
            "PrimaryDominantDirection",
            "PrimaryDominantShare",
            "PrimaryHasConflict",
            "ReviewPriorityClass",
            "ReviewPriorityReason",
        ]
    ].rename(columns={"geometry": "SignalGeometry"})
    joined = joined.merge(
        signal_lookup,
        on=[
            "Signal_RowID",
            "StudyAreaID",
            "REG_SIGNAL_ID",
            "SIGNAL_NO",
            "SignalLabel",
            "SignalRouteName",
            "AssignedSpeedMph",
            "ApproachLengthMeters",
            "SpeedAssignmentSource",
        ],
        how="left",
        validate="many_to_one",
    )
    joined["RouteCompatible"] = joined["RTE_NM"].eq(joined["SignalRouteName"])
    joined["SignalDistanceMeters"] = joined.geometry.distance(gpd.GeoSeries(joined["SignalGeometry"], crs=signal_frame.crs))

    selected_rows: list[dict[str, object]] = []
    for _, group in joined.groupby("Crash_RowID", sort=False):
        base = group.iloc[0]
        crash_record = {
            "Crash_RowID": int(base["Crash_RowID"]),
            "DOCUMENT_NBR": base["DOCUMENT_NBR"],
            "CRASH_YEAR": int(base["CRASH_YEAR"]) if not pd.isna(base["CRASH_YEAR"]) else None,
            "CrashRouteName": base["RTE_NM"],
            "CrashRouteMeasure": float(base["RNS_MP"]) if not pd.isna(base["RNS_MP"]) else None,
            "geometry": base.geometry,
        }
        crash_record.update(_summarize_signal_candidate_group(group))
        selected_rows.append(crash_record)
    return pd.DataFrame(selected_rows)


def _attachment_confidence(distance_meters: float | None) -> str:
    if distance_meters is None:
        return "unresolved"
    if distance_meters <= CRASH_TO_ROW_HIGH_DISTANCE_METERS:
        return "high"
    if distance_meters <= CRASH_TO_ROW_MAX_DISTANCE_METERS:
        return "medium"
    return "unresolved"


def _classify_relative_position(row: pd.Series) -> dict[str, object]:
    if row["SignalAssociationStatus"] != "assigned":
        return {
            "AttachmentStatus": "unresolved",
            "AttachmentMethod": None,
            "AttachmentConfidence": "unresolved",
            "CrashToAttachedRowDistanceMeters": None,
            "FlowStatus": "unresolved",
            "FlowDirectionUsed": None,
            "FlowProvenanceUsed": None,
            "SignalProjectionMeters": None,
            "CrashProjectionMeters": None,
            "AttachedRowLengthMeters": None,
            "SignalRelativeClassification": "unresolved",
            "ClassificationMethod": None,
            "ClassificationReason": row["SignalAssociationReason"],
        }

    line = _normalize_line_geometry(row["AttachedRoadGeometry"])
    if line is None:
        return {
            "AttachmentStatus": "unresolved",
            "AttachmentMethod": "signal_nearest_road_row",
            "AttachmentConfidence": "unresolved",
            "CrashToAttachedRowDistanceMeters": None,
            "FlowStatus": "assigned" if pd.notna(row["FlowDirection"]) else "unresolved",
            "FlowDirectionUsed": row["FlowDirection"],
            "FlowProvenanceUsed": row["FlowProvenance"],
            "SignalProjectionMeters": None,
            "CrashProjectionMeters": None,
            "AttachedRowLengthMeters": None,
            "SignalRelativeClassification": "unresolved",
            "ClassificationMethod": None,
            "ClassificationReason": "attached row geometry is not usable as a single ordered line",
        }

    crash_to_row_distance = float(row["geometry"].distance(line))
    attachment_confidence = _attachment_confidence(crash_to_row_distance)
    if crash_to_row_distance > CRASH_TO_ROW_MAX_DISTANCE_METERS:
        return {
            "AttachmentStatus": "unresolved",
            "AttachmentMethod": "signal_nearest_road_row",
            "AttachmentConfidence": attachment_confidence,
            "CrashToAttachedRowDistanceMeters": crash_to_row_distance,
            "FlowStatus": "assigned" if pd.notna(row["FlowDirection"]) else "unresolved",
            "FlowDirectionUsed": row["FlowDirection"],
            "FlowProvenanceUsed": row["FlowProvenance"],
            "SignalProjectionMeters": None,
            "CrashProjectionMeters": None,
            "AttachedRowLengthMeters": float(line.length),
            "SignalRelativeClassification": "unresolved",
            "ClassificationMethod": None,
            "ClassificationReason": "crash is too far from the selected signal carriageway row",
        }

    if pd.isna(row["FlowDirection"]) or not str(row["FlowProvenance"]).strip():
        return {
            "AttachmentStatus": "assigned",
            "AttachmentMethod": "signal_nearest_road_row",
            "AttachmentConfidence": attachment_confidence,
            "CrashToAttachedRowDistanceMeters": crash_to_row_distance,
            "FlowStatus": "unresolved",
            "FlowDirectionUsed": None,
            "FlowProvenanceUsed": None,
            "SignalProjectionMeters": None,
            "CrashProjectionMeters": None,
            "AttachedRowLengthMeters": float(line.length),
            "SignalRelativeClassification": "unresolved",
            "ClassificationMethod": None,
            "ClassificationReason": "no strict or empirical90 local flow orientation is available for the attached row",
        }

    flow_follows_geometry = _flow_matches_line_direction(line, row["FlowDirection"])
    if flow_follows_geometry is None:
        return {
            "AttachmentStatus": "assigned",
            "AttachmentMethod": "signal_nearest_road_row",
            "AttachmentConfidence": attachment_confidence,
            "CrashToAttachedRowDistanceMeters": crash_to_row_distance,
            "FlowStatus": "assigned",
            "FlowDirectionUsed": row["FlowDirection"],
            "FlowProvenanceUsed": row["FlowProvenance"],
            "SignalProjectionMeters": None,
            "CrashProjectionMeters": None,
            "AttachedRowLengthMeters": float(line.length),
            "SignalRelativeClassification": "unresolved",
            "ClassificationMethod": None,
            "ClassificationReason": "the attached row geometry does not have a clear overall orientation for the assigned cardinal flow",
        }

    signal_projection = float(line.project(row["SignalGeometry"]))
    crash_projection = float(line.project(row["geometry"]))
    delta = crash_projection - signal_projection
    if abs(delta) <= SAME_LOCATION_TOLERANCE_METERS:
        classification = "unresolved"
        reason = "crash and signal project to nearly the same position on the attached row"
    else:
        if flow_follows_geometry:
            classification = "upstream" if crash_projection < signal_projection else "downstream"
        else:
            classification = "upstream" if crash_projection > signal_projection else "downstream"
        reason = "crash and signal were projected onto the same attached row and ordered along the empirically assigned flow"

    return {
        "AttachmentStatus": "assigned",
        "AttachmentMethod": "signal_nearest_road_row",
        "AttachmentConfidence": attachment_confidence,
        "CrashToAttachedRowDistanceMeters": crash_to_row_distance,
        "FlowStatus": "assigned",
        "FlowDirectionUsed": row["FlowDirection"],
        "FlowProvenanceUsed": row["FlowProvenance"],
        "SignalProjectionMeters": signal_projection,
        "CrashProjectionMeters": crash_projection,
        "AttachedRowLengthMeters": float(line.length),
        "SignalRelativeClassification": classification,
        "ClassificationMethod": "project_compare_along_attached_row",
        "ClassificationReason": reason,
    }


def _build_reason_summary(classifications: pd.DataFrame) -> pd.DataFrame:
    if classifications.empty:
        return pd.DataFrame(columns=["ClassificationReason", "CrashCount", "CrashRate"])
    total = max(int(len(classifications)), 1)
    summary = (
        classifications.groupby("ClassificationReason", dropna=False)
        .size()
        .reset_index(name="CrashCount")
        .sort_values(["CrashCount", "ClassificationReason"], ascending=[False, True])
    )
    summary["CrashRate"] = (summary["CrashCount"] / total).round(4)
    return summary


def _build_signal_summary(classifications: pd.DataFrame) -> pd.DataFrame:
    if classifications.empty:
        return pd.DataFrame()
    summary = (
        classifications.groupby(
            [
                "StudyAreaID",
                "Signal_RowID",
                "REG_SIGNAL_ID",
                "SIGNAL_NO",
                "SignalLabel",
                "SignalRouteName",
                "FlowDirectionUsed",
                "FlowProvenanceUsed",
            ],
            dropna=False,
        )
        .agg(
            StudyAreaCrashCount=("Crash_RowID", "size"),
            UpstreamCrashCount=("SignalRelativeClassification", lambda values: int(pd.Series(values).eq("upstream").sum())),
            DownstreamCrashCount=("SignalRelativeClassification", lambda values: int(pd.Series(values).eq("downstream").sum())),
            UnresolvedCrashCount=("SignalRelativeClassification", lambda values: int(pd.Series(values).eq("unresolved").sum())),
            HighAttachmentCount=("AttachmentConfidence", lambda values: int(pd.Series(values).eq("high").sum())),
            MediumAttachmentCount=("AttachmentConfidence", lambda values: int(pd.Series(values).eq("medium").sum())),
            AmbiguousSignalCount=("SignalAssociationReason", lambda values: int(pd.Series(values).eq("multiple same-route signals are nearly equally near the crash").sum())),
        )
        .reset_index()
        .sort_values(["StudyAreaCrashCount", "Signal_RowID"], ascending=[False, True])
    )
    return summary


def _build_prototype_summary(classifications: pd.DataFrame, eligible_signals: gpd.GeoDataFrame) -> dict[str, object]:
    total = int(len(classifications))
    class_counts = classifications["SignalRelativeClassification"].value_counts(dropna=False).to_dict() if total else {}
    flow_counts = classifications["FlowProvenanceUsed"].fillna("unresolved").value_counts(dropna=False).to_dict() if total else {}
    unresolved_reason_counts = (
        classifications.loc[classifications["SignalRelativeClassification"].eq("unresolved"), "ClassificationReason"]
        .value_counts(dropna=False)
        .to_dict()
        if total
        else {}
    )
    return {
        "eligible_signal_count": int(len(eligible_signals)),
        "study_area_buffer_meters": STUDY_AREA_BUFFER_METERS,
        "signal_ambiguity_tolerance_meters": SIGNAL_AMBIGUITY_TOLERANCE_METERS,
        "crash_to_row_high_distance_meters": CRASH_TO_ROW_HIGH_DISTANCE_METERS,
        "crash_to_row_max_distance_meters": CRASH_TO_ROW_MAX_DISTANCE_METERS,
        "same_location_tolerance_meters": SAME_LOCATION_TOLERANCE_METERS,
        "crashes_considered_in_study_areas": total,
        "classification_counts": {key: int(value) for key, value in class_counts.items()},
        "flow_provenance_counts": {str(key): int(value) for key, value in flow_counts.items()},
        "unresolved_reason_counts": {str(key): int(value) for key, value in unresolved_reason_counts.items()},
        "classified_rate": round(
            classifications["SignalRelativeClassification"].isin(["upstream", "downstream"]).sum() / total,
            4,
        )
        if total
        else 0.0,
    }


def _apply_review_fields(classifications: pd.DataFrame) -> pd.DataFrame:
    frame = classifications.copy()
    frame["ClassificationStatus"] = frame["SignalRelativeClassification"].map(
        lambda value: "classified" if value in {"upstream", "downstream"} else "unresolved"
    )
    frame["SignalRelativeClass"] = frame["SignalRelativeClassification"]
    frame["FlowProvenance"] = frame["FlowProvenanceUsed"].map(FLOW_PROVENANCE_CATEGORY).fillna("unresolved")
    frame["UnresolvedReason"] = frame["ClassificationReason"].where(frame["ClassificationStatus"].eq("unresolved"))

    def review_details(row: pd.Series) -> tuple[str, str]:
        if row["ClassificationStatus"] == "unresolved":
            return "unresolved_admitted", str(row["ClassificationReason"])
        if row["AttachmentConfidence"] == "high" and row["FlowProvenance"] == "strict_empirical":
            return "highest_confidence", "high attachment confidence with strict empirical flow provenance"
        if row["AttachmentConfidence"] == "medium" and row["FlowProvenance"] == "strict_empirical":
            return "edge_review", "classified with medium row-attachment confidence"
        if row["FlowProvenance"] == "empirical90":
            return "edge_review", "classified using the empirical90 flow relaxation"
        return "standard_classified", "classified with high attachment confidence and bounded empirical support"

    frame[["ReviewPriorityClass", "ReviewPriorityReason"]] = frame.apply(review_details, axis=1, result_type="expand")
    return frame


def _build_scope_summary(scope_name: str, classifications: pd.DataFrame, eligible_signals: gpd.GeoDataFrame) -> pd.DataFrame:
    summary = _build_prototype_summary(classifications, eligible_signals)
    no_same_route = int(
        classifications["ClassificationReason"].eq("study-area crash has no same-route eligible signal candidate").sum()
    )
    return pd.DataFrame(
        [
            {
                "StudyAreaType": scope_name,
                "EligibleSignalCount": int(summary["eligible_signal_count"]),
                "AdmittedCrashCount": int(summary["crashes_considered_in_study_areas"]),
                "UpstreamCount": int(summary["classification_counts"].get("upstream", 0)),
                "DownstreamCount": int(summary["classification_counts"].get("downstream", 0)),
                "UnresolvedCount": int(summary["classification_counts"].get("unresolved", 0)),
                "ClassifiedCount": int(summary["classification_counts"].get("upstream", 0) + summary["classification_counts"].get("downstream", 0)),
                "ClassifiedRate": float(summary["classified_rate"]),
                "NoSameRouteEligibleSignalCount": no_same_route,
                "NoSameRouteEligibleSignalRate": round(no_same_route / max(int(len(classifications)), 1), 4),
            }
        ]
    )


def _build_scope_results(
    scope_name: str,
    eligible_signals: gpd.GeoDataFrame,
    study_areas: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
) -> dict[str, object]:
    crash_signal_pairs = _attach_crashes_to_signals(crashes, eligible_signals, study_areas)
    if crash_signal_pairs.empty:
        classifications = pd.DataFrame()
    else:
        classifications = crash_signal_pairs.copy()
        derived = classifications.apply(_classify_relative_position, axis=1, result_type="expand")
        classifications = pd.concat([classifications, derived], axis=1)
        classifications["HasUsableClassification"] = classifications["SignalRelativeClassification"].isin(["upstream", "downstream"])
        classifications["IsUnresolved"] = classifications["SignalRelativeClassification"].eq("unresolved")
        classifications = _apply_review_fields(classifications.sort_values(["Signal_RowID", "Crash_RowID"]).reset_index(drop=True))
    return {
        "classifications": classifications,
        "signal_summary": _build_signal_summary(classifications),
        "reason_summary": _build_reason_summary(classifications),
        "scope_summary": _build_scope_summary(scope_name, classifications, eligible_signals),
        "prototype_summary": _build_prototype_summary(classifications, eligible_signals),
    }


def _build_scope_comparison(circle_results: dict[str, object], approach_results: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparison = pd.concat(
        [
            circle_results["scope_summary"],
            approach_results["scope_summary"],
        ],
        ignore_index=True,
    )
    circle_ids = set(circle_results["classifications"]["DOCUMENT_NBR"]) if not circle_results["classifications"].empty else set()
    approach_ids = set(approach_results["classifications"]["DOCUMENT_NBR"]) if not approach_results["classifications"].empty else set()
    admission = pd.DataFrame(
        [
            {"AdmissionComparison": "admitted_by_both", "CrashCount": int(len(circle_ids & approach_ids))},
            {"AdmissionComparison": "circle_only", "CrashCount": int(len(circle_ids - approach_ids))},
            {"AdmissionComparison": "approach_only", "CrashCount": int(len(approach_ids - circle_ids))},
        ]
    )
    return comparison, admission


def _build_strongest_classified_outputs(
    classifications: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    strongest = classifications.loc[
        classifications["ClassificationStatus"].eq("classified")
        & classifications["AttachmentConfidence"].eq("high")
        & classifications["FlowProvenance"].eq("strict_empirical")
    ].copy()
    strongest_summary = pd.DataFrame(
        [
            {
                "SubsetName": "strongest_classified",
                "CrashCount": int(len(strongest)),
                "UpstreamCount": int(strongest["SignalRelativeClass"].eq("upstream").sum()),
                "DownstreamCount": int(strongest["SignalRelativeClass"].eq("downstream").sum()),
                "SignalCount": int(strongest["Signal_RowID"].nunique()),
                "StudyAreaCount": int(strongest["StudyAreaID"].nunique()),
            }
        ]
    )
    strongest_by_signal = (
        strongest.groupby(["StudyAreaID", "Signal_RowID", "SignalLabel"], dropna=False)
        .agg(
            CrashCount=("Crash_RowID", "size"),
            UpstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("upstream").sum())),
            DownstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("downstream").sum())),
        )
        .reset_index()
        .sort_values(["CrashCount", "Signal_RowID"], ascending=[False, True])
    )
    skepticism_summary = pd.DataFrame(
        [
            {
                "EdgeCondition": "classified_with_empirical90",
                "CrashCount": int(
                    (
                        classifications["ClassificationStatus"].eq("classified")
                        & classifications["FlowProvenance"].eq("empirical90")
                    ).sum()
                ),
            },
            {
                "EdgeCondition": "classified_with_medium_attachment",
                "CrashCount": int(
                    (
                        classifications["ClassificationStatus"].eq("classified")
                        & classifications["AttachmentConfidence"].eq("medium")
                    ).sum()
                ),
            },
            {
                "EdgeCondition": "classified_edge_review_total",
                "CrashCount": int(classifications["ReviewPriorityClass"].eq("edge_review").sum()),
            },
        ]
    )
    return strongest, strongest_summary, strongest_by_signal, skepticism_summary


def _build_review_summary_markdown(
    comparison_summary: pd.DataFrame,
    approach_classifications: pd.DataFrame,
    strongest_summary: pd.DataFrame,
    skepticism_summary: pd.DataFrame,
) -> str:
    circle = comparison_summary.loc[comparison_summary["StudyAreaType"].eq(CIRCLE_STUDY_AREA_TYPE)].iloc[0]
    approach = comparison_summary.loc[comparison_summary["StudyAreaType"].eq(APPROACH_STUDY_AREA_TYPE)].iloc[0]
    strongest_row = strongest_summary.iloc[0]
    unresolved_reasons = (
        approach_classifications.loc[approach_classifications["SignalRelativeClassification"].eq("unresolved"), "ClassificationReason"]
        .value_counts(dropna=False)
        .head(5)
    )

    lines = [
        "# Upstream/Downstream Prototype Review Summary",
        "",
        "## Study-area comparison",
        f"- {CIRCLE_STUDY_AREA_TYPE}: admitted {int(circle['AdmittedCrashCount'])}, classified {int(circle['ClassifiedCount'])}, unresolved {int(circle['UnresolvedCount'])}, no-same-route bucket {int(circle['NoSameRouteEligibleSignalCount'])}",
        f"- {APPROACH_STUDY_AREA_TYPE}: admitted {int(approach['AdmittedCrashCount'])}, classified {int(approach['ClassifiedCount'])}, unresolved {int(approach['UnresolvedCount'])}, no-same-route bucket {int(approach['NoSameRouteEligibleSignalCount'])}",
        "",
        "## Strongest classified subset",
        f"- strongest classified crashes: {int(strongest_row['CrashCount'])}",
        f"- upstream: {int(strongest_row['UpstreamCount'])}",
        f"- downstream: {int(strongest_row['DownstreamCount'])}",
        f"- signals represented: {int(strongest_row['SignalCount'])}",
        "",
        "## Edge buckets among approach-shaped classified crashes",
    ]
    for row in skepticism_summary.itertuples(index=False):
        lines.append(f"- {row.EdgeCondition}: {int(row.CrashCount)}")
    lines.extend(
        [
            "",
            "## QGIS review order",
            "- Load `study_areas__approach_shaped`, `signals`, and `approach_rows` first to judge whether the admission geometry matches the signal approaches.",
            "- Then load `classified_high_confidence` to inspect likely true positives with the least manual filtering.",
            "- Then load `classified_edge_review` to inspect empirical90 and medium-attachment cases.",
            "- Then load `unresolved_admitted` to inspect what still gets admitted and why.",
            "",
            "## Top unresolved reasons in the approach-shaped run",
        ]
    )
    if unresolved_reasons.empty:
        lines.append("- none")
    else:
        for reason, count in unresolved_reasons.items():
            lines.append(f"- {reason}: {int(count)}")
    return "\n".join(lines) + "\n"


def _review_geojson_outputs(
    output_dir: Path,
    circle_study_areas: gpd.GeoDataFrame,
    approach_study_areas: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    approach_rows: gpd.GeoDataFrame,
    approach_classifications: gpd.GeoDataFrame,
) -> dict[str, str]:
    review_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_HISTORY_SUBDIR)
    outputs: dict[str, str] = {}
    layer_map = {
        "study_areas__circle250m": circle_study_areas,
        "study_areas__approach_shaped": approach_study_areas,
        "signals": signals,
        "approach_rows": approach_rows,
        "classified_all": approach_classifications.loc[approach_classifications["ClassificationStatus"].eq("classified")].copy(),
        "classified_high_confidence": approach_classifications.loc[approach_classifications["ReviewPriorityClass"].eq("highest_confidence")].copy(),
        "classified_edge_review": approach_classifications.loc[approach_classifications["ReviewPriorityClass"].eq("edge_review")].copy(),
        "unresolved_admitted": approach_classifications.loc[approach_classifications["ClassificationStatus"].eq("unresolved")].copy(),
    }
    for layer_name, frame in layer_map.items():
        if frame is None or frame.empty:
            continue
        path = _prepare_output_path(review_dir / f"{layer_name}.geojson", history_dir=review_history_dir)
        _prepare_export_frame(frame).to_file(path, driver="GeoJSON")
        outputs[layer_name] = str(path)
    return outputs


def _build_output_layout_readme(output_files: dict[str, str], output_dir: Path) -> str:
    current_sections = [
        ("tables/current", TABLES_CURRENT_SUBDIR),
        ("review/current", REVIEW_CURRENT_SUBDIR),
        ("review/geojson/current", REVIEW_GEOJSON_CURRENT_SUBDIR),
        ("runs/current", RUNS_CURRENT_SUBDIR),
    ]
    lines = [
        "# Upstream/Downstream Prototype Outputs",
        "",
        "This output folder is organized so active prototype deliverables stay separate from older or lock-fallback files.",
        "",
        "## Current outputs",
    ]
    for label, parts in current_sections:
        section_path = output_dir.joinpath(*parts)
        matching = sorted(
            str(Path(path).relative_to(output_dir))
            for path in output_files.values()
            if Path(path).exists() and section_path in Path(path).parents
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
            "- `tables/history/`, `review/history/`, `review/geojson/history/`, and `runs/history/` preserve older timestamped outputs and lock-fallback writes.",
            "- Files in `current/` are the active stable paths the prototype will try to replace on the next run.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_upstream_downstream_prototype() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / OUTPUT_FOLDER_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_current_dir = _output_subdir(output_dir, *TABLES_CURRENT_SUBDIR)
    tables_history_dir = _output_subdir(output_dir, *TABLES_HISTORY_SUBDIR)
    review_current_dir = _output_subdir(output_dir, *REVIEW_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_HISTORY_SUBDIR)
    runs_current_dir = _output_subdir(output_dir, *RUNS_CURRENT_SUBDIR)
    runs_history_dir = _output_subdir(output_dir, *RUNS_HISTORY_SUBDIR)

    flow_assignments, assignment_path = _load_flow_assignments(config)
    roads = _load_study_roads(config)
    signals = _load_signals(config)
    speed_segments = _load_speed_segments(config)
    crashes = _load_crashes(config)[["DOCUMENT_NBR", "CRASH_YEAR", "RTE_NM", "RNS_MP", "geometry"]].copy()

    signal_frame = _attach_signal_speed(_build_signal_prototype_frame(signals, roads, flow_assignments), speed_segments)
    circle_study_areas = _build_circle_study_areas(signal_frame)
    approach_study_areas, approach_rows = _build_approach_shaped_study_areas(signal_frame, roads)

    circle_results = _build_scope_results(CIRCLE_STUDY_AREA_TYPE, signal_frame, circle_study_areas, crashes)
    approach_results = _build_scope_results(APPROACH_STUDY_AREA_TYPE, signal_frame, approach_study_areas, crashes)
    comparison_summary, admission_comparison = _build_scope_comparison(circle_results, approach_results)
    strongest_classified, strongest_summary, strongest_by_signal, skepticism_summary = _build_strongest_classified_outputs(
        approach_results["classifications"]
    )
    review_summary = _build_review_summary_markdown(
        comparison_summary,
        approach_results["classifications"],
        strongest_summary,
        skepticism_summary,
    )

    signal_review = signal_frame.merge(
        approach_results["signal_summary"],
        on=["StudyAreaID", "Signal_RowID", "REG_SIGNAL_ID", "SIGNAL_NO", "SignalLabel", "SignalRouteName"],
        how="left",
    )
    for field in (
        "StudyAreaCrashCount",
        "UpstreamCrashCount",
        "DownstreamCrashCount",
        "UnresolvedCrashCount",
        "HighAttachmentCount",
        "MediumAttachmentCount",
        "AmbiguousSignalCount",
    ):
        if field in signal_review.columns:
            signal_review[field] = signal_review[field].fillna(0).astype(int)

    attached_row_summary = (
        approach_results["classifications"].groupby(
            ["StudyRoad_RowID", "AttachedRoad_RTE_NM", "FlowDirectionUsed", "FlowProvenanceUsed"],
            dropna=False,
        )
        .agg(
            CrashCount=("Crash_RowID", "size"),
            UpstreamCrashCount=("SignalRelativeClassification", lambda values: int(pd.Series(values).eq("upstream").sum())),
            DownstreamCrashCount=("SignalRelativeClassification", lambda values: int(pd.Series(values).eq("downstream").sum())),
            UnresolvedCrashCount=("SignalRelativeClassification", lambda values: int(pd.Series(values).eq("unresolved").sum())),
        )
        .reset_index()
    )
    attached_rows = roads.rename(
        columns={
            "RTE_NM": "AttachedRoad_RTE_NM",
            "FROM_MEASURE": "AttachedRoad_FROM_MEASURE",
            "TO_MEASURE": "AttachedRoad_TO_MEASURE",
        }
    ).merge(
        attached_row_summary,
        on=["StudyRoad_RowID", "AttachedRoad_RTE_NM"],
        how="inner",
    )
    attached_rows = gpd.GeoDataFrame(attached_rows, geometry="geometry", crs=roads.crs)

    study_area_review = approach_study_areas.merge(
        approach_results["signal_summary"][
            [
                "StudyAreaID",
                "StudyAreaCrashCount",
                "UpstreamCrashCount",
                "DownstreamCrashCount",
                "UnresolvedCrashCount",
            ]
        ],
        on="StudyAreaID",
        how="left",
    )
    for field in ("StudyAreaCrashCount", "UpstreamCrashCount", "DownstreamCrashCount", "UnresolvedCrashCount"):
        if field in study_area_review.columns:
            study_area_review[field] = study_area_review[field].fillna(0).astype(int)

    output_files = {
        "circle_classification_table": str(
            _write_csv_frame(
                circle_results["classifications"].drop(columns=["geometry", "AttachedRoadGeometry", "SignalGeometry"], errors="ignore"),
                tables_current_dir / "crash_signal_classification__circle250m.csv",
                history_dir=tables_history_dir,
            )
        ),
        "approach_classification_table": str(
            _write_csv_frame(
                approach_results["classifications"].drop(columns=["geometry", "AttachedRoadGeometry", "SignalGeometry"], errors="ignore"),
                tables_current_dir / "crash_signal_classification__approach_shaped.csv",
                history_dir=tables_history_dir,
            )
        ),
        "approach_signal_summary": str(
            _write_csv_frame(
                approach_results["signal_summary"],
                tables_current_dir / "signal_study_area_summary__approach_shaped.csv",
                history_dir=tables_history_dir,
            )
        ),
        "approach_reason_summary": str(
            _write_csv_frame(
                approach_results["reason_summary"],
                tables_current_dir / "classification_reason_summary__approach_shaped.csv",
                history_dir=tables_history_dir,
            )
        ),
        "study_area_behavior_comparison": str(
            _write_csv_frame(
                comparison_summary,
                tables_current_dir / "study_area_behavior_comparison.csv",
                history_dir=tables_history_dir,
            )
        ),
        "study_area_admission_comparison": str(
            _write_csv_frame(
                admission_comparison,
                tables_current_dir / "study_area_admission_comparison.csv",
                history_dir=tables_history_dir,
            )
        ),
        "strongest_classified_summary": str(
            _write_csv_frame(
                strongest_summary,
                tables_current_dir / "strongest_classified_summary.csv",
                history_dir=tables_history_dir,
            )
        ),
        "strongest_classified_by_signal": str(
            _write_csv_frame(
                strongest_by_signal,
                tables_current_dir / "strongest_classified_by_signal.csv",
                history_dir=tables_history_dir,
            )
        ),
        "classified_skepticism_summary": str(
            _write_csv_frame(
                skepticism_summary,
                tables_current_dir / "classified_skepticism_summary.csv",
                history_dir=tables_history_dir,
            )
        ),
        "review_summary": str(
            _write_text_file(
                review_summary,
                review_current_dir / "review_summary.md",
                history_dir=review_history_dir,
            )
        ),
    }

    geojson_outputs = _review_geojson_outputs(
        output_dir,
        circle_study_areas,
        study_area_review,
        signal_review,
        approach_rows,
        gpd.GeoDataFrame(approach_results["classifications"].copy(), geometry="geometry", crs=crashes.crs),
    )
    output_files.update({f"review_{key}_geojson": value for key, value in geojson_outputs.items()})

    run_summary = {
        "interpreter": sys.executable,
        "directionality_assignment_source": str(assignment_path),
        "output_dir": str(output_dir),
        "legacy_reference_used": {
            "path": str(config.repo_root / "legacy" / "arcpy" / "secondstep"),
            "concepts_taken": [
                "nearest speed assignment to signals",
                "default speed when no usable speed is nearby",
                "5 mph rounded lookup into AASHTO/VDOT functional distance bands",
                "desired functional distance used as an approach-length proxy",
            ],
            "concepts_not_revived": [
                "ArcPy workflow structure",
                "zone ladders and donut architecture",
                "broad legacy orchestration",
            ],
        },
        "prototype_definition": {
            "circle_baseline_rule": f"{int(STUDY_AREA_BUFFER_METERS)} meter circular study area around each eligible signal",
            "approach_shaped_rule": "same-route study-road segments near each eligible signal are clipped to a per-signal approach length, buffered, and unioned with a small hub buffer at the signal",
            "approach_row_search_meters": APPROACH_ROW_SEARCH_METERS,
            "approach_buffer_meters": APPROACH_BUFFER_METERS,
            "signal_hub_buffer_meters": SIGNAL_HUB_BUFFER_METERS,
            "speed_assignment_search_meters": SPEED_SEARCH_MAX_DISTANCE_METERS,
            "speed_default_mph": DEFAULT_SPEED_MPH,
            "speed_length_basis": "legacy desired functional distance lookup carried forward as a bounded approach-length proxy",
            "signal_association_rule": "for each crash in a study area, choose the nearest same-route eligible signal; leave unresolved when no same-route signal exists or when two same-route signals are within 15 meters of the same crash",
            "carriageway_attachment_rule": "attach the crash to the selected signal's own nearest study-road row and require crash-to-row distance <= 50 meters",
            "flow_hierarchy": [STRICT_RULE_NAME, EMPIRICAL_90_RULE_NAME],
            "flow_fallback_used": False,
            "ordering_rule": "project crash and signal onto the same attached row geometry and compare positions along the empirically assigned flow",
        },
        "comparison_summary": comparison_summary.to_dict(orient="records"),
        "approach_prototype_counts": approach_results["prototype_summary"],
        "strongest_classified_summary": strongest_summary.to_dict(orient="records"),
        "output_files": output_files,
    }
    output_files["run_summary"] = str(
        _write_json_object(
            run_summary,
            runs_current_dir / "run_summary.json",
            history_dir=runs_history_dir,
        )
    )
    output_files["readme"] = str(
        _write_text_file(
            _build_output_layout_readme(output_files, output_dir),
            output_dir / "README.md",
        )
    )
    print(json.dumps(run_summary, indent=2))
    return 0


def main() -> int:
    return run_upstream_downstream_prototype()


if __name__ == "__main__":
    raise SystemExit(main())
