from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from geopandas.array import GeometryDtype
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import linemerge

from .config import load_runtime_config


METERS_TO_FEET = 3.28084
OUTPUT_FOLDER_NAME = "context_enrichment"
TABLES_CURRENT_SUBDIR = ("tables", "current")
TABLES_HISTORY_SUBDIR = ("tables", "history")
REVIEW_CURRENT_SUBDIR = ("review", "current")
REVIEW_HISTORY_SUBDIR = ("review", "history")
REVIEW_GEOJSON_CURRENT_SUBDIR = ("review", "geojson", "current")
REVIEW_GEOJSON_HISTORY_SUBDIR = ("review", "geojson", "history")
RUNS_CURRENT_SUBDIR = ("runs", "current")
RUNS_HISTORY_SUBDIR = ("runs", "history")

ACCESS_MAX_TO_ROW_DISTANCE_FT = 60.0
ACCESS_MEASURE_TOLERANCE_MI = 0.005
ACCESS_NEAR_SIGNAL_THRESHOLD_FT = 65.6
MIN_RU_DOMINANT_COUNT = 3
MIN_RU_DOMINANT_SHARE = 0.67

APPROACH_ROW_REQUIRED_FIELDS = [
    "StudyAreaID",
    "Signal_RowID",
    "REG_SIGNAL_ID",
    "SIGNAL_NO",
    "SignalLabel",
    "SignalRouteName",
    "StudyAreaType",
    "StudyRoad_RowID",
    "ApproachLengthMeters",
    "AssignedSpeedMph",
    "SpeedAssignmentSource",
]
STUDY_AREA_REQUIRED_FIELDS = [
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
    "StudyAreaType",
    "ApproachRowCount",
]
CLASSIFIED_ALL_REQUIRED_FIELDS = [
    "Crash_RowID",
    "StudyAreaID",
    "Signal_RowID",
    "StudyRoad_RowID",
    "AttachedRoadGeometry",
    "SignalGeometry",
    "SignalRelativeClassification",
]
CLASSIFIED_HIGH_CONFIDENCE_REQUIRED_FIELDS = [
    "Crash_RowID",
    "StudyAreaID",
    "Signal_RowID",
    "StudyRoad_RowID",
]
SIGNALS_REQUIRED_FIELDS = [
    "Signal_RowID",
    "StudyAreaID",
    "FlowDirection",
    "FlowProvenance",
    "FlowDirectionUsed",
    "FlowProvenanceUsed",
    "AssignedSpeedMph",
    "ApproachLengthMeters",
]
CRASH_CLASSIFICATION_REQUIRED_FIELDS = [
    "Crash_RowID",
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CrashRouteName",
    "CrashRouteMeasure",
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
    "StudyRoad_RowID",
    "AttachedRoad_RTE_NM",
    "AttachedRoad_RTE_COMMON",
    "AttachedRoad_FROM_MEASURE",
    "AttachedRoad_TO_MEASURE",
    "FlowDirection",
    "FlowProvenance",
    "AttachmentStatus",
    "AttachmentMethod",
    "AttachmentConfidence",
    "CrashToAttachedRowDistanceMeters",
    "FlowStatus",
    "FlowDirectionUsed",
    "FlowProvenanceUsed",
    "SignalProjectionMeters",
    "CrashProjectionMeters",
    "AttachedRowLengthMeters",
    "SignalRelativeClassification",
    "ClassificationMethod",
    "ClassificationReason",
    "HasUsableClassification",
    "IsUnresolved",
    "ClassificationStatus",
    "SignalRelativeClass",
    "UnresolvedReason",
]
SIGNAL_SUMMARY_REQUIRED_FIELDS = [
    "StudyAreaID",
    "Signal_RowID",
    "REG_SIGNAL_ID",
    "SIGNAL_NO",
    "SignalLabel",
    "SignalRouteName",
    "FlowDirectionUsed",
    "FlowProvenanceUsed",
    "StudyAreaCrashCount",
    "UpstreamCrashCount",
    "DownstreamCrashCount",
    "UnresolvedCrashCount",
    "HighAttachmentCount",
    "MediumAttachmentCount",
    "AmbiguousSignalCount",
]
STUDY_ROADS_REQUIRED_FIELDS = [
    "RTE_NM",
    "FROM_MEASURE",
    "TO_MEASURE",
    "RTE_ID",
    "RTE_COMMON",
    "RIM_FACILI",
    "RIM_MEDIAN",
]
AADT_REQUIRED_FIELDS = [
    "RTE_NM",
    "MASTER_RTE_NM",
    "LINKID",
    "AADT",
    "AADT_YR",
    "AADT_QUALITY",
    "AAWDT",
    "AAWDT_QUALITY",
    "DIRECTION_FACTOR",
    "DIRECTIONALITY",
    "TRANSPORT_EDGE_FROM_MSR",
    "TRANSPORT_EDGE_TO_MSR",
    "EDGE_RTE_KEY",
    "MPO_DSC",
]
ACCESS_REQUIRED_FIELDS = [
    "id",
    "_rte_nm",
    "_m",
    "NUMBER_OF_APPROACHES",
    "ACCESS_CONTROL",
    "ACCESS_DIRECTION",
    "COMMERCIAL_RETAIL",
    "RESIDENTIAL",
    "INDUSTRIAL",
    "GOV_SCHOOL_INSTITUTIONAL",
    "TURN_LANES_PRIMARY_ROUTE",
]
CRASH_AREA_TYPE_REQUIRED_FIELDS = ["DOCUMENT_NBR", "AREA_TYPE"]


@dataclass(frozen=True)
class ResolvedPaths:
    prototype_root: Path
    study_slice_root: Path
    normalized_root: Path
    output_root: Path
    run_label: str | None
    working_crs: str


@dataclass(frozen=True)
class LoadedInputs:
    source_paths: dict[str, Path]
    approach_rows: gpd.GeoDataFrame
    study_areas: gpd.GeoDataFrame
    classified_all: gpd.GeoDataFrame
    classified_high_confidence: gpd.GeoDataFrame
    signals: gpd.GeoDataFrame
    crash_classifications: pd.DataFrame
    signal_summary: pd.DataFrame
    study_roads: gpd.GeoDataFrame
    aadt: gpd.GeoDataFrame
    access: gpd.GeoDataFrame
    crash_area_type: pd.DataFrame


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


def _prepare_geojson_export(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
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
        has_geometry = series.map(
            lambda value: hasattr(value, "geom_type") if value is not None and not pd.isna(value) else False
        )
        if bool(has_geometry.any()):
            export[column] = series.map(
                lambda value: value.wkt if value is not None and not pd.isna(value) and hasattr(value, "wkt") else None
            )
    return export


def _write_geojson_frame(frame: gpd.GeoDataFrame, path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    export = _prepare_geojson_export(frame)
    resolved.write_text(export.to_json(drop_id=True), encoding="utf-8")
    return resolved


def _normalize_route_name(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = " ".join(str(value).strip().split())
    return normalized or None


def _to_int64(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _to_bool_series(series: pd.Series) -> pd.Series:
    normalized = series.map(lambda value: "" if pd.isna(value) else str(value).strip().lower())
    return normalized.isin({"true", "1", "yes", "y", "t"})


def _int_or_na(value: object):
    if value is None or pd.isna(value):
        return pd.NA
    return int(value)


def _require_existing_path(path: Path, label: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Missing required documented input for {label}: {path}")
    return path


def _require_fields(frame: pd.DataFrame, required_fields: list[str], label: str) -> None:
    missing = [field for field in required_fields if field not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required documented fields: {missing}")


def _load_geojson(path: Path, label: str, required_fields: list[str], target_crs: str) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"{label} has no CRS: {path}")
    frame = frame.to_crs(target_crs)
    _require_fields(frame, required_fields, label)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs)


def _load_csv(path: Path, label: str, required_fields: list[str]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    _require_fields(frame, required_fields, label)
    return frame


def _load_parquet_dataframe(path: Path, label: str, required_fields: list[str]) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    _require_fields(frame, required_fields, label)
    return frame


def _load_parquet_geodataframe(path: Path, label: str, required_fields: list[str], target_crs: str) -> gpd.GeoDataFrame:
    frame = gpd.read_parquet(path)
    if frame.crs is None:
        raise ValueError(f"{label} has no CRS: {path}")
    frame = frame.to_crs(target_crs)
    _require_fields(frame, required_fields, label)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs)


def _resolve_paths(args: argparse.Namespace) -> ResolvedPaths:
    config = load_runtime_config()
    prototype_root = Path(args.prototype_root) if args.prototype_root else config.output_dir / "upstream_downstream_prototype"
    study_slice_root = Path(args.study_slice_root) if args.study_slice_root else config.output_dir / "stage1b_study_slice"
    normalized_root = Path(args.normalized_root) if args.normalized_root else config.normalized_dir
    output_root = Path(args.output_root) if args.output_root else config.output_dir / OUTPUT_FOLDER_NAME
    return ResolvedPaths(
        prototype_root=prototype_root,
        study_slice_root=study_slice_root,
        normalized_root=normalized_root,
        output_root=output_root,
        run_label=args.run_label,
        working_crs=config.working_crs,
    )


def _documented_source_paths(paths: ResolvedPaths) -> dict[str, Path]:
    return {
        "approach_rows": paths.prototype_root / "review" / "geojson" / "current" / "approach_rows.geojson",
        "study_areas_approach_shaped": paths.prototype_root / "review" / "geojson" / "current" / "study_areas__approach_shaped.geojson",
        "classified_all": paths.prototype_root / "review" / "geojson" / "current" / "classified_all.geojson",
        "classified_high_confidence": paths.prototype_root / "review" / "geojson" / "current" / "classified_high_confidence.geojson",
        "signals": paths.prototype_root / "review" / "geojson" / "current" / "signals.geojson",
        "crash_classifications": paths.prototype_root / "tables" / "current" / "crash_signal_classification__approach_shaped.csv",
        "signal_summary": paths.prototype_root / "tables" / "current" / "signal_study_area_summary__approach_shaped.csv",
        "study_roads": paths.study_slice_root / "Study_Roads_Divided.parquet",
        "aadt": paths.normalized_root / "aadt.parquet",
        "access": paths.normalized_root / "access.parquet",
        "crash_area_type": paths.normalized_root / "crashes.parquet",
    }


def _load_inputs(paths: ResolvedPaths) -> LoadedInputs:
    source_paths = {name: _require_existing_path(path, name) for name, path in _documented_source_paths(paths).items()}

    approach_rows = _load_geojson(
        source_paths["approach_rows"],
        "approach_rows.geojson",
        APPROACH_ROW_REQUIRED_FIELDS,
        paths.working_crs,
    )
    study_areas = _load_geojson(
        source_paths["study_areas_approach_shaped"],
        "study_areas__approach_shaped.geojson",
        STUDY_AREA_REQUIRED_FIELDS,
        paths.working_crs,
    )
    classified_all = _load_geojson(
        source_paths["classified_all"],
        "classified_all.geojson",
        CLASSIFIED_ALL_REQUIRED_FIELDS,
        paths.working_crs,
    )
    classified_high_confidence = _load_geojson(
        source_paths["classified_high_confidence"],
        "classified_high_confidence.geojson",
        CLASSIFIED_HIGH_CONFIDENCE_REQUIRED_FIELDS,
        paths.working_crs,
    )
    signals = _load_geojson(
        source_paths["signals"],
        "signals.geojson",
        SIGNALS_REQUIRED_FIELDS,
        paths.working_crs,
    )
    crash_classifications = _load_csv(
        source_paths["crash_classifications"],
        "crash_signal_classification__approach_shaped.csv",
        CRASH_CLASSIFICATION_REQUIRED_FIELDS,
    )
    signal_summary = _load_csv(
        source_paths["signal_summary"],
        "signal_study_area_summary__approach_shaped.csv",
        SIGNAL_SUMMARY_REQUIRED_FIELDS,
    )

    raw_study_roads = _load_parquet_geodataframe(
        source_paths["study_roads"],
        "Study_Roads_Divided.parquet",
        STUDY_ROADS_REQUIRED_FIELDS,
        paths.working_crs,
    )
    study_roads = raw_study_roads.reset_index(names="StudyRoad_RowID")
    study_roads["StudyRoad_RowID"] = study_roads["StudyRoad_RowID"].astype(int)

    aadt = _load_parquet_geodataframe(source_paths["aadt"], "aadt.parquet", AADT_REQUIRED_FIELDS, paths.working_crs)
    access = _load_parquet_geodataframe(source_paths["access"], "access.parquet", ACCESS_REQUIRED_FIELDS, paths.working_crs)
    crash_area_type = _load_parquet_dataframe(
        source_paths["crash_area_type"],
        "crashes.parquet",
        CRASH_AREA_TYPE_REQUIRED_FIELDS,
    )[CRASH_AREA_TYPE_REQUIRED_FIELDS].copy()

    for frame in (approach_rows, study_areas, classified_all, classified_high_confidence, signals):
        frame["StudyAreaID"] = frame["StudyAreaID"].astype(str)
    for frame in (approach_rows, study_areas, signals):
        frame["Signal_RowID"] = _to_int64(frame["Signal_RowID"])
    for frame in (approach_rows, classified_all, classified_high_confidence):
        frame["StudyRoad_RowID"] = _to_int64(frame["StudyRoad_RowID"])
    for frame in (classified_all, classified_high_confidence):
        frame["Crash_RowID"] = _to_int64(frame["Crash_RowID"])

    crash_classifications["StudyAreaID"] = crash_classifications["StudyAreaID"].astype(str)
    crash_classifications["Signal_RowID"] = _to_int64(crash_classifications["Signal_RowID"])
    crash_classifications["StudyRoad_RowID"] = _to_int64(crash_classifications["StudyRoad_RowID"])
    crash_classifications["Crash_RowID"] = _to_int64(crash_classifications["Crash_RowID"])
    signal_summary["StudyAreaID"] = signal_summary["StudyAreaID"].astype(str)
    signal_summary["Signal_RowID"] = _to_int64(signal_summary["Signal_RowID"])

    access["Access_PointID"] = access["id"].astype(str)
    access["Access_Route_Normalized"] = access["_rte_nm"].map(_normalize_route_name)
    access["Access_Measure_Numeric"] = _to_numeric(access["_m"])

    aadt["AADT_SourceRoute_Normalized"] = aadt["RTE_NM"].map(_normalize_route_name)
    aadt["AADT_MasterRoute_Normalized"] = aadt["MASTER_RTE_NM"].map(_normalize_route_name)

    crash_area_type["DOCUMENT_NBR"] = crash_area_type["DOCUMENT_NBR"].astype(str)
    crash_area_type = crash_area_type.drop_duplicates(subset=["DOCUMENT_NBR"], keep="first").copy()

    return LoadedInputs(
        source_paths=source_paths,
        approach_rows=approach_rows,
        study_areas=study_areas,
        classified_all=classified_all,
        classified_high_confidence=classified_high_confidence,
        signals=signals,
        crash_classifications=crash_classifications,
        signal_summary=signal_summary,
        study_roads=study_roads,
        aadt=aadt,
        access=access,
        crash_area_type=crash_area_type,
    )


def _duplicate_key_rows(frame: pd.DataFrame, keys: list[str]) -> pd.Series:
    return frame.duplicated(subset=keys, keep=False)


def _build_approach_row_context_base(inputs: LoadedInputs) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    study_area_context = inputs.study_areas[
        [
            "StudyAreaID",
            "FlowDirection",
            "FlowProvenance",
            "StudyAreaBufferMeters",
        ]
    ].drop_duplicates(subset=["StudyAreaID"])
    road_context = inputs.study_roads[
        [
            "StudyRoad_RowID",
            "RTE_NM",
            "FROM_MEASURE",
            "TO_MEASURE",
            "RTE_ID",
            "RTE_COMMON",
            "RIM_FACILI",
            "RIM_MEDIAN",
        ]
    ].rename(
        columns={
            "RTE_NM": "ApproachRoad_RTE_NM",
            "FROM_MEASURE": "ApproachRoad_FROM_MEASURE",
            "TO_MEASURE": "ApproachRoad_TO_MEASURE",
            "RTE_ID": "ApproachRoad_RTE_ID",
            "RTE_COMMON": "ApproachRoad_RTE_COMMON",
            "RIM_FACILI": "ApproachRoad_Facility",
            "RIM_MEDIAN": "ApproachRoad_Median",
        }
    )

    base = (
        inputs.approach_rows.drop(columns=["geometry"])
        .merge(study_area_context, on="StudyAreaID", how="left", validate="many_to_one")
        .merge(road_context, on="StudyRoad_RowID", how="left", validate="many_to_one")
    )
    duplicate_mask = _duplicate_key_rows(base, ["StudyAreaID", "StudyRoad_RowID"])
    base["BaseJoinStatus"] = "ready"
    base["BaseJoinReason"] = "all_required_joins_present"

    missing_signal_mask = base["FlowDirection"].isna() | base["FlowProvenance"].isna() | base["StudyAreaBufferMeters"].isna()
    missing_road_mask = (
        base["ApproachRoad_RTE_NM"].isna()
        | base["ApproachRoad_FROM_MEASURE"].isna()
        | base["ApproachRoad_TO_MEASURE"].isna()
    )

    base.loc[missing_signal_mask, "BaseJoinStatus"] = "missing_signal_context"
    base.loc[missing_signal_mask, "BaseJoinReason"] = "missing_study_area_join"
    base.loc[~missing_signal_mask & missing_road_mask, "BaseJoinStatus"] = "missing_study_road_context"
    base.loc[~missing_signal_mask & missing_road_mask, "BaseJoinReason"] = "missing_study_road_join"
    base.loc[duplicate_mask, "BaseJoinStatus"] = "duplicate_key_conflict"
    base.loc[duplicate_mask, "BaseJoinReason"] = "duplicate_studyarea_row_key"

    geometry = inputs.approach_rows[["StudyAreaID", "StudyRoad_RowID", "geometry"]].copy()
    base_geo = geometry.merge(base, on=["StudyAreaID", "StudyRoad_RowID"], how="left", validate="one_to_one")
    return base, gpd.GeoDataFrame(base_geo, geometry="geometry", crs=inputs.approach_rows.crs)


def _build_signal_study_area_context_base(inputs: LoadedInputs) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    summary = inputs.signal_summary.copy()
    duplicate_ids = summary.loc[summary.duplicated(subset=["StudyAreaID"], keep=False), "StudyAreaID"].drop_duplicates().tolist()
    if duplicate_ids:
        duplicate_group_sizes = summary.groupby("StudyAreaID", dropna=False).size()
        unexpected_sizes = duplicate_group_sizes.loc[duplicate_ids]
        unexpected_sizes = unexpected_sizes.loc[~unexpected_sizes.eq(2)]
        if not unexpected_sizes.empty:
            raise ValueError(
                "signal_study_area_summary__approach_shaped.csv has unexpected duplicate StudyAreaID multiplicity: "
                + ", ".join(f"{study_area_id}={count}" for study_area_id, count in unexpected_sizes.items())
            )
        identifier_fields = ["Signal_RowID", "REG_SIGNAL_ID", "SIGNAL_NO", "SignalLabel", "SignalRouteName"]
        conflicting_ids: list[str] = []
        for study_area_id in duplicate_ids:
            duplicate_group = summary.loc[summary["StudyAreaID"].eq(study_area_id), identifier_fields]
            if int(duplicate_group.nunique(dropna=False).max()) > 1:
                conflicting_ids.append(str(study_area_id))
        if conflicting_ids:
            raise ValueError(
                "signal_study_area_summary__approach_shaped.csv has conflicting duplicate StudyAreaID rows: "
                + ", ".join(conflicting_ids)
            )
        summary = (
            summary.groupby(identifier_fields + ["StudyAreaID"], dropna=False, as_index=False)
            .agg(
                FlowDirectionUsed=("FlowDirectionUsed", lambda values: next((value for value in values if pd.notna(value)), pd.NA)),
                FlowProvenanceUsed=("FlowProvenanceUsed", lambda values: next((value for value in values if pd.notna(value)), pd.NA)),
                StudyAreaCrashCount=("StudyAreaCrashCount", "sum"),
                UpstreamCrashCount=("UpstreamCrashCount", "sum"),
                DownstreamCrashCount=("DownstreamCrashCount", "sum"),
                UnresolvedCrashCount=("UnresolvedCrashCount", "sum"),
                HighAttachmentCount=("HighAttachmentCount", "sum"),
                MediumAttachmentCount=("MediumAttachmentCount", "sum"),
                AmbiguousSignalCount=("AmbiguousSignalCount", "sum"),
            )
            .copy()
        )

    study_area_context = inputs.study_areas[
        [
            "StudyAreaID",
            "StudyAreaType",
            "FlowDirection",
            "FlowProvenance",
            "StudyAreaBufferMeters",
            "ApproachLengthMeters",
            "AssignedSpeedMph",
            "SpeedAssignmentSource",
            "ApproachRowCount",
        ]
    ].drop_duplicates(subset=["StudyAreaID"])

    base = summary.merge(study_area_context, on="StudyAreaID", how="left", validate="one_to_one").rename(
        columns={
            "StudyAreaCrashCount": "Prototype_StudyAreaCrashCount",
            "UpstreamCrashCount": "Prototype_UpstreamCrashCount",
            "DownstreamCrashCount": "Prototype_DownstreamCrashCount",
            "UnresolvedCrashCount": "Prototype_UnresolvedCrashCount",
            "HighAttachmentCount": "Prototype_HighAttachmentCount",
            "MediumAttachmentCount": "Prototype_MediumAttachmentCount",
            "AmbiguousSignalCount": "Prototype_AmbiguousSignalCount",
        }
    )
    base_geo = inputs.study_areas[["StudyAreaID", "geometry"]].drop_duplicates(subset=["StudyAreaID"]).merge(
        base,
        on="StudyAreaID",
        how="left",
        validate="one_to_one",
    )
    return base, gpd.GeoDataFrame(base_geo, geometry="geometry", crs=inputs.study_areas.crs)


def _normalize_line_geometry(geometry) -> LineString | None:
    if geometry is None:
        return None
    if isinstance(geometry, LineString):
        return geometry if not geometry.is_empty and geometry.length > 0 else None
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
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


def _build_aadt_candidates(
    approach_row_base: pd.DataFrame,
    approach_row_geometry: gpd.GeoDataFrame,
    aadt: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    geom = approach_row_geometry[
        ["StudyAreaID", "StudyRoad_RowID", "Signal_RowID", "SignalRouteName", "ApproachLengthMeters", "geometry"]
    ].copy()
    geom["SignalRouteName_Normalized"] = geom["SignalRouteName"].map(_normalize_route_name)
    joined = gpd.sjoin(geom, aadt, how="inner", predicate="intersects")
    if joined.empty:
        return (
            pd.DataFrame(),
            pd.DataFrame(
                columns=[
                    "StudyAreaID",
                    "StudyRoad_RowID",
                    "AADT_CandidateCount",
                    "AADT_SelectionRule",
                    "AADT_Status",
                    "AADT_Reason",
                    "AADT_Value",
                    "AADT_Year",
                    "AADT_Quality",
                    "AADT_SourceRoute",
                    "AADT_MasterRoute",
                    "AADT_LinkID",
                    "AADT_Directionality",
                    "AADT_DirectionFactor",
                    "AADT_OverlapLengthFt",
                    "AADT_OverlapShare",
                    "AADT_RouteSupportTier",
                ]
            ),
        )

    joined["AADTGeometry"] = joined["index_right"].map(aadt.geometry)
    intersections = joined.geometry.intersection(gpd.GeoSeries(joined["AADTGeometry"], index=joined.index, crs=aadt.crs))
    joined["AADT_OverlapLengthFt"] = intersections.length * METERS_TO_FEET
    joined = joined.loc[joined["AADT_OverlapLengthFt"] > 0].copy()
    if joined.empty:
        return (
            pd.DataFrame(),
            pd.DataFrame(
                columns=[
                    "StudyAreaID",
                    "StudyRoad_RowID",
                    "AADT_CandidateCount",
                    "AADT_SelectionRule",
                    "AADT_Status",
                    "AADT_Reason",
                    "AADT_Value",
                    "AADT_Year",
                    "AADT_Quality",
                    "AADT_SourceRoute",
                    "AADT_MasterRoute",
                    "AADT_LinkID",
                    "AADT_Directionality",
                    "AADT_DirectionFactor",
                    "AADT_OverlapLengthFt",
                    "AADT_OverlapShare",
                    "AADT_RouteSupportTier",
                ]
            ),
        )

    joined["AADT_OverlapShare"] = joined["AADT_OverlapLengthFt"] / (joined["ApproachLengthMeters"] * METERS_TO_FEET)
    joined["AADT_Value_Numeric"] = _to_numeric(joined["AADT"])
    joined["AADT_Year_Numeric"] = _to_numeric(joined["AADT_YR"])
    joined["AADT_RouteSupportTier"] = "unsupported"
    joined.loc[
        joined["SignalRouteName_Normalized"].eq(joined["AADT_SourceRoute_Normalized"]),
        "AADT_RouteSupportTier",
    ] = "rte_nm_exact"
    joined.loc[
        ~joined["SignalRouteName_Normalized"].eq(joined["AADT_SourceRoute_Normalized"])
        & joined["SignalRouteName_Normalized"].eq(joined["AADT_MasterRoute_Normalized"]),
        "AADT_RouteSupportTier",
    ] = "master_rte_exact"

    candidate_columns = [
        "StudyAreaID",
        "StudyRoad_RowID",
        "Signal_RowID",
        "SignalRouteName",
        "RTE_NM",
        "MASTER_RTE_NM",
        "LINKID",
        "AADT",
        "AADT_YR",
        "AADT_QUALITY",
        "DIRECTIONALITY",
        "DIRECTION_FACTOR",
        "AADT_OverlapLengthFt",
        "AADT_OverlapShare",
        "AADT_RouteSupportTier",
        "AADT_Value_Numeric",
        "AADT_Year_Numeric",
    ]
    candidates = joined[candidate_columns].rename(
        columns={
            "RTE_NM": "AADT_SourceRoute",
            "MASTER_RTE_NM": "AADT_MasterRoute",
            "LINKID": "AADT_LinkID",
            "AADT": "AADT_Value",
            "AADT_YR": "AADT_Year",
            "AADT_QUALITY": "AADT_Quality",
            "DIRECTIONALITY": "AADT_Directionality",
            "DIRECTION_FACTOR": "AADT_DirectionFactor",
        }
    ).copy()

    row_level_results: list[dict[str, object]] = []
    candidate_records: list[pd.DataFrame] = []
    key_columns = ["StudyAreaID", "StudyRoad_RowID"]
    for (study_area_id, study_road_row_id), group in candidates.groupby(key_columns, dropna=False):
        group = group.sort_values(
            ["AADT_RouteSupportTier", "AADT_Year_Numeric", "AADT_OverlapLengthFt"],
            ascending=[True, False, False],
        ).copy()
        total_candidates = int(len(group))
        group["AADT_CandidateCount"] = total_candidates
        group["AADT_Selected"] = False
        group["AADT_RowStatus"] = None
        group["AADT_RowReason"] = None

        supported = group.loc[group["AADT_RouteSupportTier"].ne("unsupported")].copy()
        if supported.empty:
            status = "no_route_supported_candidate"
            reason = "only_unsupported_route_candidates"
            selection_rule = "intersects_but_no_exact_route_support"
            selected_row = None
        else:
            positive = supported.loc[supported["AADT_Value_Numeric"].gt(0)].copy()
            if positive.empty:
                status = "invalid_value"
                reason = "all_route_supported_candidates_invalid_aadt"
                selection_rule = "route_supported_candidates_without_positive_aadt"
                selected_row = None
            else:
                non_null_year = positive.loc[positive["AADT_Year_Numeric"].notna()].copy()
                if not non_null_year.empty:
                    latest_year = non_null_year["AADT_Year_Numeric"].max()
                    filtered = positive.loc[positive["AADT_Year_Numeric"].eq(latest_year)].copy()
                    selection_rule = "route_supported_positive_aadt_latest_year_overlap"
                else:
                    filtered = positive.copy()
                    selection_rule = "route_supported_positive_aadt_no_nonnull_year_overlap"
                max_overlap = filtered["AADT_OverlapLengthFt"].max()
                winners = filtered.loc[filtered["AADT_OverlapLengthFt"].eq(max_overlap)].copy()
                if len(winners) == 1:
                    status = "matched"
                    reason = "unique_best_overlap_latest_year"
                    selected_row = winners.iloc[0]
                    selection_rule = f"{selection_rule}_unique_best"
                else:
                    status = "ambiguous"
                    reason = "tie_after_latest_year_filter"
                    selected_row = None
                    selection_rule = f"{selection_rule}_tie"

        group["AADT_RowStatus"] = status
        group["AADT_RowReason"] = reason
        if selected_row is not None:
            selected_mask = (
                group["AADT_LinkID"].astype(str).eq(str(selected_row["AADT_LinkID"]))
                & group["AADT_OverlapLengthFt"].eq(selected_row["AADT_OverlapLengthFt"])
                & group["AADT_RouteSupportTier"].eq(selected_row["AADT_RouteSupportTier"])
            )
            group.loc[selected_mask, "AADT_Selected"] = True

        if selected_row is None:
            selected_payload = {
                "AADT_Value": None,
                "AADT_Year": None,
                "AADT_Quality": None,
                "AADT_SourceRoute": None,
                "AADT_MasterRoute": None,
                "AADT_LinkID": None,
                "AADT_Directionality": None,
                "AADT_DirectionFactor": None,
                "AADT_OverlapLengthFt": None,
                "AADT_OverlapShare": None,
                "AADT_RouteSupportTier": None,
            }
        else:
            selected_payload = {
                "AADT_Value": selected_row["AADT_Value"],
                "AADT_Year": selected_row["AADT_Year"],
                "AADT_Quality": selected_row["AADT_Quality"],
                "AADT_SourceRoute": selected_row["AADT_SourceRoute"],
                "AADT_MasterRoute": selected_row["AADT_MasterRoute"],
                "AADT_LinkID": selected_row["AADT_LinkID"],
                "AADT_Directionality": selected_row["AADT_Directionality"],
                "AADT_DirectionFactor": selected_row["AADT_DirectionFactor"],
                "AADT_OverlapLengthFt": selected_row["AADT_OverlapLengthFt"],
                "AADT_OverlapShare": selected_row["AADT_OverlapShare"],
                "AADT_RouteSupportTier": selected_row["AADT_RouteSupportTier"],
            }

        row_level_results.append(
            {
                "StudyAreaID": study_area_id,
                "StudyRoad_RowID": study_road_row_id,
                "AADT_CandidateCount": total_candidates,
                "AADT_SelectionRule": selection_rule,
                "AADT_Status": status,
                "AADT_Reason": reason,
                **selected_payload,
            }
        )
        candidate_records.append(group)

    candidate_output = pd.concat(candidate_records, ignore_index=True) if candidate_records else pd.DataFrame()
    row_selection = pd.DataFrame(row_level_results)
    if not candidate_output.empty:
        candidate_output = candidate_output.sort_values(
            ["StudyAreaID", "StudyRoad_RowID", "AADT_Selected", "AADT_OverlapLengthFt"],
            ascending=[True, True, False, False],
        ).reset_index(drop=True)
    return candidate_output, row_selection


def _aadt_no_candidate_rows(
    approach_row_base: pd.DataFrame,
    aadt_row_selection: pd.DataFrame,
    approach_row_geometry: gpd.GeoDataFrame,
) -> pd.DataFrame:
    merged = approach_row_base[["StudyAreaID", "StudyRoad_RowID"]].merge(
        aadt_row_selection,
        on=["StudyAreaID", "StudyRoad_RowID"],
        how="left",
        validate="one_to_one",
    )
    missing_geometry_keys = set(
        approach_row_geometry.loc[approach_row_geometry["geometry"].isna(), ["StudyAreaID", "StudyRoad_RowID"]].itertuples(index=False, name=None)
    )
    no_selection_mask = merged["AADT_Status"].isna()
    merged.loc[no_selection_mask, "AADT_CandidateCount"] = 0
    merged.loc[no_selection_mask, "AADT_SelectionRule"] = "no_aadt_intersection"
    merged.loc[no_selection_mask, "AADT_Status"] = "no_candidate"
    merged.loc[no_selection_mask, "AADT_Reason"] = "no_aadt_intersection"
    for study_area_id, study_road_row_id in missing_geometry_keys:
        key_mask = merged["StudyAreaID"].eq(study_area_id) & merged["StudyRoad_RowID"].eq(study_road_row_id)
        merged.loc[key_mask, "AADT_Status"] = "unresolved"
        merged.loc[key_mask, "AADT_Reason"] = "missing_approach_geometry"
        merged.loc[key_mask, "AADT_SelectionRule"] = "missing_approach_geometry"
    return merged


def _aggregate_signal_aadt(approach_enriched: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for study_area_id, group in approach_enriched.groupby("StudyAreaID", dropna=False):
        matched = group.loc[group["AADT_Status"].eq("matched")].copy()
        matched_count = int(len(matched))
        ambiguous_count = int(group["AADT_Status"].eq("ambiguous").sum())
        unresolved_count = int((~group["AADT_Status"].isin(["matched", "ambiguous"])).sum())
        if matched_count:
            weights = _to_numeric(matched["AADT_OverlapLengthFt"])
            values = _to_numeric(matched["AADT_Value"])
            valid_weight_mask = weights.gt(0) & values.notna()
            if bool(valid_weight_mask.any()):
                weighted_mean = float((values.loc[valid_weight_mask] * weights.loc[valid_weight_mask]).sum() / weights.loc[valid_weight_mask].sum())
            else:
                weighted_mean = None
            min_value = float(values.min()) if values.notna().any() else None
            max_value = float(values.max()) if values.notna().any() else None
            latest_year = float(_to_numeric(matched["AADT_Year"]).max()) if _to_numeric(matched["AADT_Year"]).notna().any() else None
        else:
            weighted_mean = None
            min_value = None
            max_value = None
            latest_year = None

        rows.append(
            {
                "StudyAreaID": study_area_id,
                "AADT_MatchedApproachRowCount": matched_count,
                "AADT_AmbiguousApproachRowCount": ambiguous_count,
                "AADT_UnresolvedApproachRowCount": unresolved_count,
                "AADT_WeightedMean": weighted_mean,
                "AADT_Min": min_value,
                "AADT_Max": max_value,
                "AADT_LatestYear": latest_year,
                "AADT_MatchShare": round(matched_count / max(int(len(group)), 1), 4),
            }
        )
    return pd.DataFrame(rows)


def _ordered_measure_range(from_measure: object, to_measure: object) -> tuple[float | None, float | None]:
    start = pd.to_numeric(pd.Series([from_measure]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([to_measure]), errors="coerce").iloc[0]
    if pd.isna(start) or pd.isna(end):
        return None, None
    return (float(start), float(end)) if float(start) <= float(end) else (float(end), float(start))


def _list_to_pipe(values: list[object]) -> str | None:
    cleaned = [str(value) for value in values if value is not None and str(value).strip()]
    if not cleaned:
        return None
    return "|".join(cleaned)


def _build_access_assignment_points(
    approach_row_base: pd.DataFrame,
    approach_row_geometry: gpd.GeoDataFrame,
    signal_study_area_base: pd.DataFrame,
    study_area_geometry: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    access: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    signal_geom = signals[["StudyAreaID", "geometry"]].drop_duplicates(subset=["StudyAreaID"]).rename(columns={"geometry": "Signal_Point_Geometry"})
    study_area_context = study_area_geometry[["StudyAreaID", "Signal_RowID", "geometry"]].drop_duplicates(subset=["StudyAreaID"])
    study_area_signal = study_area_context.merge(signal_geom, on="StudyAreaID", how="left", validate="one_to_one")

    access_in_study_areas = gpd.sjoin(
        access[["Access_PointID", "_rte_nm", "_m", "Access_Route_Normalized", "Access_Measure_Numeric", "geometry"]].copy(),
        study_area_signal,
        how="inner",
        predicate="intersects",
    ).drop(columns=["index_right"])
    if access_in_study_areas.empty:
        empty_df = pd.DataFrame(
            columns=[
                "Access_PointID",
                "StudyAreaID",
                "Signal_RowID",
                "StudyRoad_RowID",
                "Access_Route",
                "Access_Measure",
                "Access_ToRowDistanceFt",
                "Access_ProjectionFt",
                "Access_SignalProjectionFt",
                "Access_SignalRelativePosition",
                "Access_AssignmentStatus",
                "Access_AssignmentReason",
                "Access_AssignmentRule",
            ]
        )
        empty_geo = gpd.GeoDataFrame(empty_df.copy(), geometry=gpd.GeoSeries([], crs=access.crs), crs=access.crs)
        return empty_df, empty_geo

    row_context = approach_row_geometry[
        [
            "StudyAreaID",
            "StudyRoad_RowID",
            "Signal_RowID",
            "ApproachRoad_RTE_NM",
            "ApproachRoad_FROM_MEASURE",
            "ApproachRoad_TO_MEASURE",
            "FlowDirection",
            "geometry",
        ]
    ].copy()
    rows_by_study_area = {
        study_area_id: frame.copy()
        for study_area_id, frame in row_context.groupby("StudyAreaID", dropna=False)
    }
    signal_point_by_study_area = {
        str(row.StudyAreaID): row.Signal_Point_Geometry
        for row in study_area_signal.itertuples(index=False)
    }

    final_records: list[dict[str, object]] = []
    final_geometries: list[object] = []

    for _, record in access_in_study_areas.iterrows():
        study_area_id = str(record["StudyAreaID"])
        candidate_rows = rows_by_study_area.get(study_area_id)
        signal_point = signal_point_by_study_area.get(study_area_id)
        if candidate_rows is None or candidate_rows.empty:
            final_records.append(
                {
                    "Access_PointID": str(record["Access_PointID"]),
                    "StudyAreaID": study_area_id,
                    "Signal_RowID": _int_or_na(record["Signal_RowID"]),
                    "StudyRoad_RowID": pd.NA,
                    "Access_Route": record["_rte_nm"],
                    "Access_Measure": record["_m"],
                    "Access_ToRowDistanceFt": None,
                    "Access_ProjectionFt": None,
                    "Access_SignalProjectionFt": None,
                    "Access_SignalRelativePosition": "unresolved",
                    "Access_AssignmentStatus": "unresolved",
                    "Access_AssignmentReason": "missing_flow_or_projection",
                    "Access_AssignmentRule": "documented_study_area_candidate_rows_required",
                    "RouteSupportedStudyRoadRowIDs": None,
                    "MeasureSupportedStudyRoadRowIDs": None,
                    "DistancePassedStudyRoadRowIDs": None,
                    "AmbiguousStudyRoadRowIDs": None,
                }
            )
            final_geometries.append(record["geometry"])
            continue

        evaluations: list[dict[str, object]] = []
        overall_distances_ft: list[float] = []
        normalized_access_route = _normalize_route_name(record["_rte_nm"])
        access_measure = pd.to_numeric(pd.Series([record["_m"]]), errors="coerce").iloc[0]

        for _, row in candidate_rows.iterrows():
            line = _normalize_line_geometry(row["geometry"])
            distance_ft = None
            if line is not None:
                distance_ft = float(record["geometry"].distance(line) * METERS_TO_FEET)
                overall_distances_ft.append(distance_ft)
            route_supported = normalized_access_route is not None and normalized_access_route == _normalize_route_name(row["ApproachRoad_RTE_NM"])
            row_from_measure, row_to_measure = _ordered_measure_range(row["ApproachRoad_FROM_MEASURE"], row["ApproachRoad_TO_MEASURE"])
            measure_supported = (
                route_supported
                and row_from_measure is not None
                and row_to_measure is not None
                and not pd.isna(access_measure)
                and float(access_measure) >= row_from_measure - ACCESS_MEASURE_TOLERANCE_MI
                and float(access_measure) <= row_to_measure + ACCESS_MEASURE_TOLERANCE_MI
            )
            distance_supported = measure_supported and line is not None and distance_ft is not None and distance_ft <= ACCESS_MAX_TO_ROW_DISTANCE_FT
            evaluations.append(
                {
                    "StudyRoad_RowID": int(row["StudyRoad_RowID"]),
                    "LineGeometry": line,
                    "FlowDirection": row["FlowDirection"],
                    "route_supported": route_supported,
                    "measure_supported": measure_supported,
                    "distance_supported": distance_supported,
                    "distance_ft": distance_ft,
                }
            )

        route_supported_rows = [item["StudyRoad_RowID"] for item in evaluations if item["route_supported"]]
        measure_supported_rows = [item["StudyRoad_RowID"] for item in evaluations if item["measure_supported"]]
        distance_supported_rows = [item["StudyRoad_RowID"] for item in evaluations if item["distance_supported"]]
        route_supported_eval = [item for item in evaluations if item["route_supported"]]
        measure_supported_eval = [item for item in evaluations if item["measure_supported"]]
        distance_supported_eval = [item for item in evaluations if item["distance_supported"]]
        overall_nearest_distance_ft = min(overall_distances_ft) if overall_distances_ft else None
        route_supported_nearest_distance_ft = min((item["distance_ft"] for item in route_supported_eval if item["distance_ft"] is not None), default=None)
        distance_pass_nearest_ft = min((item["distance_ft"] for item in distance_supported_eval if item["distance_ft"] is not None), default=None)

        final_record = {
            "Access_PointID": str(record["Access_PointID"]),
            "StudyAreaID": study_area_id,
            "Signal_RowID": _int_or_na(record["Signal_RowID"]),
            "StudyRoad_RowID": pd.NA,
            "Access_Route": record["_rte_nm"],
            "Access_Measure": record["_m"],
            "Access_ToRowDistanceFt": overall_nearest_distance_ft,
            "Access_ProjectionFt": None,
            "Access_SignalProjectionFt": None,
            "Access_SignalRelativePosition": "unresolved",
            "Access_AssignmentStatus": "unresolved",
            "Access_AssignmentReason": "missing_flow_or_projection",
            "Access_AssignmentRule": "route_exact_measure_tolerance_distance_60ft_signal_compare_65_6ft",
            "RouteSupportedStudyRoadRowIDs": _list_to_pipe(route_supported_rows),
            "MeasureSupportedStudyRoadRowIDs": _list_to_pipe(measure_supported_rows),
            "DistancePassedStudyRoadRowIDs": _list_to_pipe(distance_supported_rows),
            "AmbiguousStudyRoadRowIDs": None,
        }

        if not route_supported_eval:
            final_record["Access_AssignmentStatus"] = "route_conflict"
            final_record["Access_AssignmentReason"] = "route_name_not_exact_match"
            final_record["Access_AssignmentRule"] = "exact_route_support_required"
        elif not measure_supported_eval:
            final_record["Access_AssignmentStatus"] = "measure_conflict"
            final_record["Access_AssignmentReason"] = "measure_outside_row_range_tolerance"
            final_record["Access_AssignmentRule"] = "exact_route_support_plus_measure_tolerance"
            final_record["Access_ToRowDistanceFt"] = route_supported_nearest_distance_ft
        elif not distance_supported_eval:
            final_record["Access_AssignmentStatus"] = "too_far"
            final_record["Access_AssignmentReason"] = "distance_exceeds_60ft"
            final_record["Access_AssignmentRule"] = "exact_route_measure_support_plus_distance_60ft"
            final_record["Access_ToRowDistanceFt"] = route_supported_nearest_distance_ft
        elif len(distance_supported_eval) > 1:
            final_record["Access_AssignmentStatus"] = "ambiguous"
            final_record["Access_AssignmentReason"] = "multiple_rows_passed_thresholds"
            final_record["Access_AssignmentRule"] = "multiple_route_measure_distance_candidates"
            final_record["Access_ToRowDistanceFt"] = distance_pass_nearest_ft
            final_record["AmbiguousStudyRoadRowIDs"] = _list_to_pipe(distance_supported_rows)
        else:
            winner = distance_supported_eval[0]
            final_record["StudyRoad_RowID"] = int(winner["StudyRoad_RowID"])
            final_record["Access_ToRowDistanceFt"] = winner["distance_ft"]
            line = winner["LineGeometry"]
            flow_follows_geometry = _flow_matches_line_direction(line, winner["FlowDirection"])
            if line is None or signal_point is None or flow_follows_geometry is None:
                final_record["Access_AssignmentStatus"] = "unresolved"
                final_record["Access_AssignmentReason"] = "missing_flow_or_projection"
                final_record["Access_AssignmentRule"] = "matched_row_requires_clear_line_orientation"
            else:
                point_projection_m = float(line.project(record["geometry"]))
                signal_projection_m = float(line.project(signal_point))
                point_projection_ft = point_projection_m * METERS_TO_FEET
                signal_projection_ft = signal_projection_m * METERS_TO_FEET
                final_record["Access_ProjectionFt"] = point_projection_ft
                final_record["Access_SignalProjectionFt"] = signal_projection_ft
                delta_ft = point_projection_ft - signal_projection_ft
                if abs(delta_ft) <= ACCESS_NEAR_SIGNAL_THRESHOLD_FT:
                    final_record["Access_AssignmentStatus"] = "near_signal"
                    final_record["Access_AssignmentReason"] = "projection_within_65_6ft_of_signal"
                    final_record["Access_AssignmentRule"] = "matched_row_projection_compare_65_6ft"
                    final_record["Access_SignalRelativePosition"] = "near_signal"
                else:
                    if flow_follows_geometry:
                        position = "upstream" if point_projection_ft < signal_projection_ft else "downstream"
                    else:
                        position = "upstream" if point_projection_ft > signal_projection_ft else "downstream"
                    final_record["Access_AssignmentStatus"] = "matched"
                    final_record["Access_AssignmentReason"] = "unique_route_measure_spatial_match"
                    final_record["Access_AssignmentRule"] = "exact_route_measure_distance_unique_row_project_compare"
                    final_record["Access_SignalRelativePosition"] = position

        final_records.append(final_record)
        final_geometries.append(record["geometry"])

    final_points = pd.DataFrame(final_records)
    final_geo = gpd.GeoDataFrame(final_points.copy(), geometry=gpd.GeoSeries(final_geometries, crs=access.crs), crs=access.crs)
    return final_points, final_geo


def _count_pipe_membership(series: pd.Series, value: int) -> int:
    token = str(value)
    count = 0
    for item in series.fillna("").tolist():
        text = str(item)
        if text and token in text.split("|"):
            count += 1
    return count


def _aggregate_access_to_rows(
    approach_enriched: pd.DataFrame,
    access_points: pd.DataFrame,
) -> pd.DataFrame:
    study_area_totals = access_points.groupby("StudyAreaID", dropna=False)["Access_PointID"].nunique().to_dict()
    row_records: list[dict[str, object]] = []
    for row in approach_enriched.itertuples(index=False):
        study_area_id = str(row.StudyAreaID)
        row_id = int(row.StudyRoad_RowID)
        points_for_row = access_points.loc[access_points["StudyRoad_RowID"].eq(row_id)].copy()
        total_assigned = int(len(points_for_row))
        upstream_count = int(points_for_row["Access_SignalRelativePosition"].eq("upstream").sum())
        downstream_count = int(points_for_row["Access_SignalRelativePosition"].eq("downstream").sum())
        near_signal_count = int(points_for_row["Access_SignalRelativePosition"].eq("near_signal").sum())
        unresolved_count = int(
            (
                points_for_row["Access_SignalRelativePosition"].eq("unresolved")
                & points_for_row["Access_AssignmentStatus"].ne("ambiguous")
            ).sum()
        )
        ambiguous_count = _count_pipe_membership(access_points["AmbiguousStudyRoadRowIDs"], row_id)
        total_points_in_study_area = int(study_area_totals.get(study_area_id, 0))
        route_supported_points = _count_pipe_membership(access_points.loc[access_points["StudyAreaID"].eq(study_area_id), "RouteSupportedStudyRoadRowIDs"], row_id)
        route_share = round(route_supported_points / total_points_in_study_area, 4) if total_points_in_study_area else 0.0
        length_ft = float(row.ApproachLengthMeters) * METERS_TO_FEET if pd.notna(row.ApproachLengthMeters) else None
        density = (total_assigned / (length_ft / 1000.0)) if length_ft and length_ft > 0 else None

        if total_points_in_study_area == 0:
            status = "no_candidate_points"
            reason = "no_access_points_in_study_area"
        elif total_assigned == 0 and ambiguous_count == 0:
            status = "unresolved"
            reason = "other_access_processing_failure"
        elif ambiguous_count > 0 or unresolved_count > 0:
            status = "partial"
            reason = "contains_ambiguous_or_unresolved_points"
        else:
            status = "matched"
            reason = "all_candidate_points_resolved"

        row_records.append(
            {
                "StudyAreaID": study_area_id,
                "StudyRoad_RowID": row_id,
                "Access_Count_Total": total_assigned,
                "Access_Count_Upstream": upstream_count,
                "Access_Count_Downstream": downstream_count,
                "Access_Count_NearSignal": near_signal_count,
                "Access_Count_Unresolved": unresolved_count,
                "Access_Density_Per1000Ft": density,
                "Access_MatchedRouteShare": route_share,
                "Access_AmbiguousCount": ambiguous_count,
                "Access_Status": status,
                "Access_Reason": reason,
            }
        )
    return pd.DataFrame(row_records)


def _aggregate_access_to_signals(
    signal_base: pd.DataFrame,
    approach_enriched: pd.DataFrame,
    access_points: pd.DataFrame,
) -> pd.DataFrame:
    approach_length_by_study_area = approach_enriched.groupby("StudyAreaID", dropna=False)["ApproachLengthMeters"].sum().to_dict()
    records: list[dict[str, object]] = []
    for row in signal_base.itertuples(index=False):
        study_area_id = str(row.StudyAreaID)
        points = access_points.loc[access_points["StudyAreaID"].eq(study_area_id)].copy()
        total_count = int(points["Access_PointID"].nunique())
        upstream_count = int(points["Access_SignalRelativePosition"].eq("upstream").sum())
        downstream_count = int(points["Access_SignalRelativePosition"].eq("downstream").sum())
        near_signal_count = int(points["Access_SignalRelativePosition"].eq("near_signal").sum())
        unresolved_count = int(
            (
                points["Access_SignalRelativePosition"].eq("unresolved")
                & points["Access_AssignmentStatus"].ne("ambiguous")
            ).sum()
        )
        ambiguous_count = int(points["Access_AssignmentStatus"].eq("ambiguous").sum())
        total_length_ft = float(approach_length_by_study_area.get(study_area_id, 0.0)) * METERS_TO_FEET
        density = (total_count / (total_length_ft / 1000.0)) if total_length_ft > 0 else None

        if total_count == 0:
            status = "no_candidate_points"
            reason = "no_access_points_in_study_area"
        elif ambiguous_count > 0 or unresolved_count > 0:
            status = "partial"
            reason = "contains_ambiguous_or_unresolved_points"
        else:
            status = "matched"
            reason = "all_candidate_points_resolved"

        records.append(
            {
                "StudyAreaID": study_area_id,
                "Access_Count_Total": total_count,
                "Access_Count_Upstream": upstream_count,
                "Access_Count_Downstream": downstream_count,
                "Access_Count_NearSignal": near_signal_count,
                "Access_Count_Unresolved": unresolved_count,
                "Access_Density_Per1000Ft": density,
                "Access_AmbiguousCount": ambiguous_count,
                "Access_Status": status,
                "Access_Reason": reason,
            }
        )
    return pd.DataFrame(records)


def _classify_rural_urban(area_type: object) -> tuple[str, str]:
    if area_type == "Rural":
        return "rural", "assigned"
    if area_type == "Urban":
        return "urban", "assigned"
    return "unresolved", "unresolved"


def _derive_ru_context(counts: pd.Series, total_rows: int) -> tuple[str, float | None, str, str]:
    rural_count = int(counts.get("rural", 0))
    urban_count = int(counts.get("urban", 0))
    unresolved_count = int(counts.get("unresolved", 0))
    assigned_count = rural_count + urban_count

    if total_rows == 0:
        return "unresolved", None, "no_classified_crash_context", "no_attached_classified_crashes"
    if assigned_count == 0:
        return "unresolved", None, "unresolved", "all_attached_crashes_missing_area_type"

    dominant_class = "rural" if rural_count >= urban_count else "urban"
    dominant_count = max(rural_count, urban_count)
    dominant_share = round(dominant_count / assigned_count, 4) if assigned_count else None

    if assigned_count >= MIN_RU_DOMINANT_COUNT and dominant_share is not None and dominant_share >= MIN_RU_DOMINANT_SHARE:
        return dominant_class, dominant_share, "assigned", "dominant_share_ge_0_67_with_min3"
    if rural_count > 0 and urban_count > 0:
        return "mixed", dominant_share, "mixed", "both_rural_and_urban_present_without_dominance"
    return "unresolved", dominant_share, "unresolved", "both_rural_and_urban_present_without_dominance"


def _build_rural_urban_outputs(
    crash_classifications: pd.DataFrame,
    crash_area_type: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    crash_context = crash_classifications.copy()
    crash_context["DOCUMENT_NBR"] = crash_context["DOCUMENT_NBR"].astype(str)
    crash_context = crash_context.merge(
        crash_area_type,
        on="DOCUMENT_NBR",
        how="left",
        validate="many_to_one",
    )
    crash_context[["Crash_RuralUrbanClass", "Crash_RuralUrbanStatus"]] = crash_context["AREA_TYPE"].apply(_classify_rural_urban).apply(pd.Series)
    crash_context = crash_context.rename(columns={"AREA_TYPE": "Crash_AreaType"})

    row_records: list[dict[str, object]] = []
    for (study_area_id, study_road_row_id), group in crash_context.groupby(["StudyAreaID", "StudyRoad_RowID"], dropna=False):
        counts = group["Crash_RuralUrbanClass"].value_counts(dropna=False)
        dominant_class, dominant_share, status, reason = _derive_ru_context(counts, len(group))
        row_records.append(
            {
                "StudyAreaID": study_area_id,
                "StudyRoad_RowID": study_road_row_id,
                "RU_CrashContext_RuralCount": int(counts.get("rural", 0)),
                "RU_CrashContext_UrbanCount": int(counts.get("urban", 0)),
                "RU_CrashContext_UnresolvedCount": int(counts.get("unresolved", 0)),
                "RU_CrashContext_DominantClass": dominant_class,
                "RU_CrashContext_DominantShare": dominant_share,
                "RU_ContextStatus": status,
                "RU_ContextReason": reason,
            }
        )

    signal_records: list[dict[str, object]] = []
    for study_area_id, group in crash_context.groupby("StudyAreaID", dropna=False):
        counts = group["Crash_RuralUrbanClass"].value_counts(dropna=False)
        dominant_class, dominant_share, status, reason = _derive_ru_context(counts, len(group))
        signal_records.append(
            {
                "StudyAreaID": study_area_id,
                "RU_CrashContext_RuralCount": int(counts.get("rural", 0)),
                "RU_CrashContext_UrbanCount": int(counts.get("urban", 0)),
                "RU_CrashContext_UnresolvedCount": int(counts.get("unresolved", 0)),
                "RU_CrashContext_DominantClass": dominant_class,
                "RU_CrashContext_DominantShare": dominant_share,
                "RU_ContextStatus": status,
                "RU_ContextReason": reason,
            }
        )

    return crash_context, pd.DataFrame(row_records), pd.DataFrame(signal_records)


def _build_classified_crash_context_enriched(
    crash_context: pd.DataFrame,
    approach_enriched: pd.DataFrame,
    signal_enriched: pd.DataFrame,
) -> pd.DataFrame:
    row_columns = [
        "StudyAreaID",
        "StudyRoad_RowID",
        "ApproachRoad_RTE_NM",
        "ApproachRoad_RTE_COMMON",
        "ApproachRoad_FROM_MEASURE",
        "ApproachRoad_TO_MEASURE",
        "AADT_Value",
        "AADT_Year",
        "AADT_Quality",
        "AADT_SourceRoute",
        "AADT_MasterRoute",
        "AADT_LinkID",
        "AADT_Directionality",
        "AADT_DirectionFactor",
        "AADT_OverlapLengthFt",
        "AADT_OverlapShare",
        "AADT_CandidateCount",
        "AADT_RouteSupportTier",
        "AADT_SelectionRule",
        "AADT_Status",
        "AADT_Reason",
        "Access_Count_Total",
        "Access_Count_Upstream",
        "Access_Count_Downstream",
        "Access_Count_NearSignal",
        "Access_Count_Unresolved",
        "Access_Density_Per1000Ft",
        "Access_MatchedRouteShare",
        "Access_AmbiguousCount",
        "Access_Status",
        "Access_Reason",
        "RU_CrashContext_RuralCount",
        "RU_CrashContext_UrbanCount",
        "RU_CrashContext_UnresolvedCount",
        "RU_CrashContext_DominantClass",
        "RU_CrashContext_DominantShare",
        "RU_ContextStatus",
        "RU_ContextReason",
    ]
    signal_columns = [
        "StudyAreaID",
        "AADT_MatchedApproachRowCount",
        "AADT_AmbiguousApproachRowCount",
        "AADT_UnresolvedApproachRowCount",
        "AADT_WeightedMean",
        "AADT_Min",
        "AADT_Max",
        "AADT_LatestYear",
        "AADT_MatchShare",
        "Access_Count_Total",
        "Access_Count_Upstream",
        "Access_Count_Downstream",
        "Access_Count_NearSignal",
        "Access_Count_Unresolved",
        "Access_Density_Per1000Ft",
        "Access_AmbiguousCount",
        "Access_Status",
        "Access_Reason",
        "RU_CrashContext_RuralCount",
        "RU_CrashContext_UrbanCount",
        "RU_CrashContext_UnresolvedCount",
        "RU_CrashContext_DominantClass",
        "RU_CrashContext_DominantShare",
        "RU_ContextStatus",
        "RU_ContextReason",
    ]
    signal_context = signal_enriched[signal_columns].rename(
        columns={
            "AADT_MatchedApproachRowCount": "Signal_AADT_MatchedApproachRowCount",
            "AADT_AmbiguousApproachRowCount": "Signal_AADT_AmbiguousApproachRowCount",
            "AADT_UnresolvedApproachRowCount": "Signal_AADT_UnresolvedApproachRowCount",
            "AADT_WeightedMean": "Signal_AADT_WeightedMean",
            "AADT_Min": "Signal_AADT_Min",
            "AADT_Max": "Signal_AADT_Max",
            "AADT_LatestYear": "Signal_AADT_LatestYear",
            "AADT_MatchShare": "Signal_AADT_MatchShare",
            "Access_Count_Total": "Signal_Access_Count_Total",
            "Access_Count_Upstream": "Signal_Access_Count_Upstream",
            "Access_Count_Downstream": "Signal_Access_Count_Downstream",
            "Access_Count_NearSignal": "Signal_Access_Count_NearSignal",
            "Access_Count_Unresolved": "Signal_Access_Count_Unresolved",
            "Access_Density_Per1000Ft": "Signal_Access_Density_Per1000Ft",
            "Access_AmbiguousCount": "Signal_Access_AmbiguousCount",
            "Access_Status": "Signal_Access_Status",
            "Access_Reason": "Signal_Access_Reason",
            "RU_CrashContext_RuralCount": "Signal_RU_CrashContext_RuralCount",
            "RU_CrashContext_UrbanCount": "Signal_RU_CrashContext_UrbanCount",
            "RU_CrashContext_UnresolvedCount": "Signal_RU_CrashContext_UnresolvedCount",
            "RU_CrashContext_DominantClass": "Signal_RU_CrashContext_DominantClass",
            "RU_CrashContext_DominantShare": "Signal_RU_CrashContext_DominantShare",
            "RU_ContextStatus": "Signal_RU_ContextStatus",
            "RU_ContextReason": "Signal_RU_ContextReason",
        }
    )

    enriched = crash_context.merge(
        approach_enriched[row_columns],
        on=["StudyAreaID", "StudyRoad_RowID"],
        how="left",
        validate="many_to_one",
    ).merge(
        signal_context,
        on="StudyAreaID",
        how="left",
        validate="many_to_one",
    )
    enriched["ContextJoinStatus"] = "ready"
    enriched["ContextJoinReason"] = "all_required_joins_present"
    missing_row_context = enriched["AADT_Status"].isna() | enriched["Access_Status"].isna()
    missing_signal_context = enriched["Signal_AADT_MatchedApproachRowCount"].isna() | enriched["Signal_Access_Status"].isna()
    enriched.loc[missing_row_context, "ContextJoinStatus"] = "unresolved"
    enriched.loc[missing_row_context, "ContextJoinReason"] = "missing_study_road_join"
    enriched.loc[~missing_row_context & missing_signal_context, "ContextJoinStatus"] = "unresolved"
    enriched.loc[~missing_row_context & missing_signal_context, "ContextJoinReason"] = "missing_study_area_join"
    return enriched


def _json_ready_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict(orient="records")


def _build_aadt_candidate_generation_diagnostics(
    approach_row_geometry: gpd.GeoDataFrame,
    aadt: gpd.GeoDataFrame,
) -> dict[str, object]:
    geom = approach_row_geometry[
        ["StudyAreaID", "StudyRoad_RowID", "SignalRouteName", "ApproachLengthMeters", "geometry"]
    ].copy()
    geom["SignalRouteName_Normalized"] = geom["SignalRouteName"].map(_normalize_route_name)
    aadt_view = aadt[
        [
            "RTE_NM",
            "MASTER_RTE_NM",
            "LINKID",
            "AADT_SourceRoute_Normalized",
            "AADT_MasterRoute_Normalized",
            "geometry",
        ]
    ].copy()

    bbox_geom = geom[["StudyAreaID", "StudyRoad_RowID", "SignalRouteName", "SignalRouteName_Normalized", "geometry"]].copy()
    bbox_geom["geometry"] = bbox_geom.geometry.bounds.apply(lambda row: box(row.minx, row.miny, row.maxx, row.maxy), axis=1)
    bbox_geom = gpd.GeoDataFrame(bbox_geom, geometry="geometry", crs=geom.crs)

    bbox_join = gpd.sjoin(bbox_geom, aadt_view, how="inner", predicate="intersects")
    bbox_join["RouteSupported"] = False
    if not bbox_join.empty:
        bbox_join["RouteSupported"] = (
            bbox_join["SignalRouteName_Normalized"].eq(bbox_join["AADT_SourceRoute_Normalized"])
            | bbox_join["SignalRouteName_Normalized"].eq(bbox_join["AADT_MasterRoute_Normalized"])
        )
    bbox_route_supported = bbox_join.loc[bbox_join["RouteSupported"]].copy()

    exact_join = gpd.sjoin(geom, aadt_view, how="inner", predicate="intersects")
    exact_join["RouteSupported"] = False
    intersection_geom_types_all: dict[str, int] = {}
    intersection_geom_types_route_supported: dict[str, int] = {}
    positive_overlap_supported_keys: set[tuple[str, int]] = set()
    if not exact_join.empty:
        exact_join["RouteSupported"] = (
            exact_join["SignalRouteName_Normalized"].eq(exact_join["AADT_SourceRoute_Normalized"])
            | exact_join["SignalRouteName_Normalized"].eq(exact_join["AADT_MasterRoute_Normalized"])
        )
        exact_join["AADTGeometry"] = exact_join["index_right"].map(aadt.geometry)
        intersections = exact_join.geometry.intersection(
            gpd.GeoSeries(exact_join["AADTGeometry"], index=exact_join.index, crs=aadt.crs)
        )
        exact_join["AADT_OverlapLengthFt"] = intersections.length * METERS_TO_FEET
        intersection_geom_types_all = {
            str(key): int(value) for key, value in intersections.geom_type.value_counts(dropna=False).to_dict().items()
        }
        intersection_geom_types_route_supported = {
            str(key): int(value)
            for key, value in intersections.loc[exact_join["RouteSupported"]].geom_type.value_counts(dropna=False).to_dict().items()
        }
        positive_overlap_supported_keys = set(
            exact_join.loc[
                exact_join["RouteSupported"] & exact_join["AADT_OverlapLengthFt"].gt(0),
                ["StudyAreaID", "StudyRoad_RowID"],
            ].itertuples(index=False, name=None)
        )
    else:
        exact_join["AADT_OverlapLengthFt"] = pd.Series(dtype="float64")

    failed_examples: list[dict[str, object]] = []
    for (study_area_id, study_road_row_id), group in bbox_route_supported.groupby(["StudyAreaID", "StudyRoad_RowID"], dropna=False):
        if (study_area_id, study_road_row_id) in positive_overlap_supported_keys:
            continue
        approach_geom = geom.loc[
            geom["StudyAreaID"].eq(study_area_id) & geom["StudyRoad_RowID"].eq(study_road_row_id),
            "geometry",
        ].iloc[0]
        candidate_geometries = gpd.GeoSeries(group["index_right"].map(aadt.geometry), index=group.index, crs=aadt.crs)
        distances_ft = candidate_geometries.distance(approach_geom) * METERS_TO_FEET
        best_position = int(distances_ft.to_numpy().argmin())
        best = group.iloc[best_position]
        failed_examples.append(
            {
                "StudyAreaID": str(study_area_id),
                "StudyRoad_RowID": int(study_road_row_id),
                "SignalRouteName": best["SignalRouteName"],
                "AADT_RTE_NM": best["RTE_NM"],
                "AADT_MASTER_RTE_NM": best["MASTER_RTE_NM"],
                "AADT_LINKID": str(best["LINKID"]),
                "nearest_candidate_distance_ft": round(float(distances_ft.iloc[best_position]), 4),
            }
        )
        if len(failed_examples) >= 8:
            break

    approach_routes = sorted({value for value in geom["SignalRouteName_Normalized"].dropna().unique().tolist()})
    aadt_source_routes = {value for value in aadt["AADT_SourceRoute_Normalized"].dropna().unique().tolist()}
    aadt_master_routes = {value for value in aadt["AADT_MasterRoute_Normalized"].dropna().unique().tolist()}

    return {
        "approach_geometry_notnull_count": int(geom.geometry.notna().sum()),
        "approach_geometry_valid_count": int(geom.geometry.is_valid.fillna(False).sum()),
        "aadt_geometry_notnull_count": int(aadt.geometry.notna().sum()),
        "aadt_geometry_valid_count": int(aadt.geometry.is_valid.fillna(False).sum()),
        "working_crs_approach_rows": str(geom.crs),
        "working_crs_aadt": str(aadt.crs),
        "bbox_join_pair_count_all_routes": int(len(bbox_join)),
        "bbox_join_approach_count_all_routes": int(
            bbox_join[["StudyAreaID", "StudyRoad_RowID"]].drop_duplicates().shape[0]
        )
        if not bbox_join.empty
        else 0,
        "bbox_join_pair_count_route_supported": int(len(bbox_route_supported)),
        "bbox_join_approach_count_route_supported": int(
            bbox_route_supported[["StudyAreaID", "StudyRoad_RowID"]].drop_duplicates().shape[0]
        )
        if not bbox_route_supported.empty
        else 0,
        "exact_intersection_pair_count_all_routes": int(len(exact_join)),
        "exact_intersection_approach_count_all_routes": int(
            exact_join[["StudyAreaID", "StudyRoad_RowID"]].drop_duplicates().shape[0]
        )
        if not exact_join.empty
        else 0,
        "exact_intersection_pair_count_route_supported": int(exact_join["RouteSupported"].sum()) if not exact_join.empty else 0,
        "exact_intersection_approach_count_route_supported": int(
            exact_join.loc[exact_join["RouteSupported"], ["StudyAreaID", "StudyRoad_RowID"]].drop_duplicates().shape[0]
        )
        if not exact_join.empty
        else 0,
        "positive_overlap_pair_count_all_routes": int(exact_join["AADT_OverlapLengthFt"].gt(0).sum()) if not exact_join.empty else 0,
        "positive_overlap_pair_count_route_supported": int(
            (exact_join["RouteSupported"] & exact_join["AADT_OverlapLengthFt"].gt(0)).sum()
        )
        if not exact_join.empty
        else 0,
        "intersection_geometry_types_all_routes": intersection_geom_types_all,
        "intersection_geometry_types_route_supported": intersection_geom_types_route_supported,
        "route_names_present_in_aadt_source_examples": [value for value in approach_routes if value in aadt_source_routes][:12],
        "route_names_present_in_aadt_master_examples": [value for value in approach_routes if value in aadt_master_routes][:12],
        "route_names_missing_from_both_aadt_fields_examples": [
            value for value in approach_routes if value not in aadt_source_routes and value not in aadt_master_routes
        ][:12],
        "failed_route_supported_overlap_examples": failed_examples,
    }


def _build_signal_summary_duplicate_diagnostics(
    signal_summary: pd.DataFrame,
    crash_classifications: pd.DataFrame,
) -> dict[str, object]:
    duplicate_mask = signal_summary.duplicated(subset=["StudyAreaID"], keep=False)
    duplicates = signal_summary.loc[duplicate_mask].copy()
    if duplicates.empty:
        return {
            "duplicated_row_count": 0,
            "duplicated_studyarea_count": 0,
            "duplicate_group_size_distribution": {},
            "duplicated_studyarea_ids": [],
            "identifier_conflict_count": 0,
            "identifier_conflict_ids": [],
            "count_sum_matches_crash_rows_count": 0,
            "unresolved_sum_matches_crash_rows_count": 0,
            "high_attachment_sum_matches_crash_rows_count": 0,
            "medium_attachment_sum_matches_crash_rows_count": 0,
            "ambiguous_signal_sum_matches_crash_rows_count": 0,
            "collapsed_row_count": int(signal_summary["StudyAreaID"].nunique()),
            "field_disagreement_group_counts": {},
            "example_duplicate_groups": [],
        }

    identifier_fields = ["Signal_RowID", "REG_SIGNAL_ID", "SIGNAL_NO", "SignalLabel", "SignalRouteName"]
    duplicate_group_sizes = duplicates.groupby("StudyAreaID", dropna=False).size()
    field_disagreement_group_counts = {
        field: int(duplicates.groupby("StudyAreaID", dropna=False)[field].nunique(dropna=False).gt(1).sum())
        for field in (
            identifier_fields
            + [
                "FlowDirectionUsed",
                "FlowProvenanceUsed",
                "StudyAreaCrashCount",
                "UpstreamCrashCount",
                "DownstreamCrashCount",
                "UnresolvedCrashCount",
                "HighAttachmentCount",
                "MediumAttachmentCount",
                "AmbiguousSignalCount",
            ]
        )
    }
    identifier_conflict_ids = [
        str(study_area_id)
        for study_area_id, group in duplicates.groupby("StudyAreaID", dropna=False)
        if int(group[identifier_fields].nunique(dropna=False).max()) > 1
    ]

    crash_rows = crash_classifications.copy()
    crash_rows["IsUnresolved_Bool"] = _to_bool_series(crash_rows["IsUnresolved"])
    crash_rows["AttachmentConfidence_Normalized"] = crash_rows["AttachmentConfidence"].astype(str).str.strip().str.lower()
    crash_rows["ClassificationStatus_Normalized"] = crash_rows["ClassificationStatus"].astype(str).str.strip().str.lower()
    crash_totals = crash_rows.groupby("StudyAreaID", dropna=False).agg(
        CrashRowCount=("Crash_RowID", "size"),
        UnresolvedCrashRowCount=("IsUnresolved_Bool", "sum"),
        HighAttachmentRowCount=("AttachmentConfidence_Normalized", lambda values: int(values.eq("high").sum())),
        MediumAttachmentRowCount=("AttachmentConfidence_Normalized", lambda values: int(values.eq("medium").sum())),
        AmbiguousSignalRowCount=("ClassificationStatus_Normalized", lambda values: int(values.eq("ambiguous_signal").sum())),
    )

    duplicate_sums = duplicates.groupby("StudyAreaID", dropna=False).agg(
        SummedStudyAreaCrashCount=("StudyAreaCrashCount", "sum"),
        SummedUnresolvedCrashCount=("UnresolvedCrashCount", "sum"),
        SummedHighAttachmentCount=("HighAttachmentCount", "sum"),
        SummedMediumAttachmentCount=("MediumAttachmentCount", "sum"),
        SummedAmbiguousSignalCount=("AmbiguousSignalCount", "sum"),
    )
    diagnostic_compare = duplicate_sums.join(crash_totals, how="left")

    example_duplicate_groups: list[dict[str, object]] = []
    for study_area_id, group in duplicates.groupby("StudyAreaID", dropna=False):
        if len(example_duplicate_groups) >= 8:
            break
        differing_fields = [
            field
            for field in field_disagreement_group_counts
            if group[field].nunique(dropna=False) > 1
        ]
        example_duplicate_groups.append(
            {
                "StudyAreaID": str(study_area_id),
                "row_count": int(len(group)),
                "differing_fields": differing_fields,
                "rows": _json_ready_records(
                    group[
                        [
                            "FlowDirectionUsed",
                            "FlowProvenanceUsed",
                            "StudyAreaCrashCount",
                            "UpstreamCrashCount",
                            "DownstreamCrashCount",
                            "UnresolvedCrashCount",
                            "HighAttachmentCount",
                            "MediumAttachmentCount",
                            "AmbiguousSignalCount",
                        ]
                    ]
                ),
            }
        )

    return {
        "duplicated_row_count": int(len(duplicates)),
        "duplicated_studyarea_count": int(duplicates["StudyAreaID"].nunique()),
        "duplicate_group_size_distribution": {
            str(key): int(value) for key, value in duplicate_group_sizes.value_counts().sort_index().to_dict().items()
        },
        "duplicated_studyarea_ids": sorted(duplicates["StudyAreaID"].drop_duplicates().tolist()),
        "identifier_conflict_count": int(len(identifier_conflict_ids)),
        "identifier_conflict_ids": identifier_conflict_ids,
        "count_sum_matches_crash_rows_count": int(
            diagnostic_compare["SummedStudyAreaCrashCount"].eq(diagnostic_compare["CrashRowCount"]).sum()
        ),
        "unresolved_sum_matches_crash_rows_count": int(
            diagnostic_compare["SummedUnresolvedCrashCount"].eq(diagnostic_compare["UnresolvedCrashRowCount"]).sum()
        ),
        "high_attachment_sum_matches_crash_rows_count": int(
            diagnostic_compare["SummedHighAttachmentCount"].eq(diagnostic_compare["HighAttachmentRowCount"]).sum()
        ),
        "medium_attachment_sum_matches_crash_rows_count": int(
            diagnostic_compare["SummedMediumAttachmentCount"].eq(diagnostic_compare["MediumAttachmentRowCount"]).sum()
        ),
        "ambiguous_signal_sum_matches_crash_rows_count": int(
            diagnostic_compare["SummedAmbiguousSignalCount"].eq(diagnostic_compare["AmbiguousSignalRowCount"]).sum()
        ),
        "collapsed_row_count": int(signal_summary["StudyAreaID"].nunique()),
        "field_disagreement_group_counts": field_disagreement_group_counts,
        "example_duplicate_groups": example_duplicate_groups,
    }


def _build_validation_metrics(
    inputs: LoadedInputs,
    approach_row_base: pd.DataFrame,
    signal_base: pd.DataFrame,
    aadt_candidates: pd.DataFrame,
    approach_enriched: pd.DataFrame,
    access_points: pd.DataFrame,
    crash_context_enriched: pd.DataFrame,
    signal_enriched: pd.DataFrame,
) -> dict[str, object]:
    selected_aadt = approach_enriched.loc[approach_enriched["AADT_Status"].eq("matched")].copy()
    aadt_year_distribution = (
        selected_aadt["AADT_Year"].fillna("<null>").value_counts(dropna=False).sort_index().to_dict()
        if not selected_aadt.empty
        else {}
    )
    aadt_quality_distribution = (
        selected_aadt["AADT_Quality"].fillna("<null>").value_counts(dropna=False).sort_index().to_dict()
        if not selected_aadt.empty
        else {}
    )
    aadt_overlap_distribution = {
        "min": float(selected_aadt["AADT_OverlapShare"].min()) if not selected_aadt.empty else None,
        "median": float(selected_aadt["AADT_OverlapShare"].median()) if not selected_aadt.empty else None,
        "max": float(selected_aadt["AADT_OverlapShare"].max()) if not selected_aadt.empty else None,
    }
    ru_dominant_distribution = signal_enriched["RU_CrashContext_DominantClass"].fillna("<null>").value_counts(dropna=False).to_dict()

    signal_aadt_states = signal_enriched.loc[signal_enriched["AADT_MatchedApproachRowCount"].gt(0), "StudyAreaID"].astype(str)
    aadt_ambiguous_or_unresolved = signal_enriched.loc[
        signal_enriched["AADT_AmbiguousApproachRowCount"].gt(0) | signal_enriched["AADT_UnresolvedApproachRowCount"].gt(0),
        "StudyAreaID",
    ].astype(str)
    access_positive = signal_enriched.loc[signal_enriched["Access_Count_Total"].gt(0), "StudyAreaID"].astype(str)

    spot_check_ids: list[str] = []
    if not signal_aadt_states.empty:
        spot_check_ids.append(signal_aadt_states.sort_values().iloc[0])
    remaining = [value for value in aadt_ambiguous_or_unresolved.sort_values().tolist() if value not in spot_check_ids]
    if remaining:
        spot_check_ids.append(remaining[0])
    remaining = [value for value in access_positive.sort_values().tolist() if value not in spot_check_ids]
    if remaining:
        spot_check_ids.append(remaining[0])

    return {
        "source_row_counts": {
            "approach_rows": int(len(inputs.approach_rows)),
            "study_areas": int(len(inputs.study_areas)),
            "classified_all_geojson": int(len(inputs.classified_all)),
            "classified_high_confidence_geojson": int(len(inputs.classified_high_confidence)),
            "crash_classification_rows": int(len(inputs.crash_classifications)),
            "signal_summary_rows": int(len(inputs.signal_summary)),
            "aadt_rows": int(len(inputs.aadt)),
            "access_rows": int(len(inputs.access)),
            "crash_area_type_rows": int(len(inputs.crash_area_type)),
        },
        "field_validation": {
            "approach_row_base_row_count_matches_source": int(len(approach_row_base)) == int(len(inputs.approach_rows)),
            "signal_base_row_count_matches_source": int(len(signal_base)) == int(len(inputs.signal_summary)),
            "approach_row_duplicate_key_count": int(_duplicate_key_rows(approach_row_base, ["StudyAreaID", "StudyRoad_RowID"]).sum()),
            "signal_base_duplicate_key_count": int(_duplicate_key_rows(signal_base, ["StudyAreaID"]).sum()),
            "approach_rows_with_successful_road_range_joins": int(approach_row_base["BaseJoinStatus"].eq("ready").sum()),
        },
        "aadt": {
            "approach_rows_with_any_candidate": int(aadt_candidates[["StudyAreaID", "StudyRoad_RowID"]].drop_duplicates().shape[0]) if not aadt_candidates.empty else 0,
            "approach_rows_with_selected_aadt": int(approach_enriched["AADT_Status"].eq("matched").sum()),
            "status_counts": approach_enriched["AADT_Status"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "reason_counts": approach_enriched["AADT_Reason"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "year_distribution_selected": aadt_year_distribution,
            "quality_distribution_selected": aadt_quality_distribution,
            "overlap_share_distribution_selected": aadt_overlap_distribution,
            "study_areas_with_selected_aadt": int(signal_enriched["AADT_MatchedApproachRowCount"].gt(0).sum()),
            "candidate_generation_diagnostics": _build_aadt_candidate_generation_diagnostics(
                approach_row_geometry=inputs.approach_rows,
                aadt=inputs.aadt,
            ),
        },
        "access": {
            "candidate_access_points_in_study_areas": int(len(access_points)),
            "assignment_status_counts": access_points["Access_AssignmentStatus"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "assignment_reason_counts": access_points["Access_AssignmentReason"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "distance_distribution_ft": {
                "min": float(access_points["Access_ToRowDistanceFt"].dropna().min()) if access_points["Access_ToRowDistanceFt"].dropna().any() else None,
                "median": float(access_points["Access_ToRowDistanceFt"].dropna().median()) if access_points["Access_ToRowDistanceFt"].dropna().any() else None,
                "max": float(access_points["Access_ToRowDistanceFt"].dropna().max()) if access_points["Access_ToRowDistanceFt"].dropna().any() else None,
            },
            "near_signal_count": int(access_points["Access_AssignmentStatus"].eq("near_signal").sum()),
            "approach_rows_with_nonzero_access_density": int(approach_enriched["Access_Density_Per1000Ft"].fillna(0).gt(0).sum()),
        },
        "rural_urban": {
            "crash_area_type_completeness_source": round(inputs.crash_area_type["AREA_TYPE"].notna().mean(), 4),
            "crash_area_type_completeness_enriched": round(crash_context_enriched["Crash_AreaType"].notna().mean(), 4),
            "dominant_class_distribution_by_signal": ru_dominant_distribution,
        },
        "signal_summary_duplicates": _build_signal_summary_duplicate_diagnostics(
            signal_summary=inputs.signal_summary,
            crash_classifications=inputs.crash_classifications,
        ),
        "required_spot_check_signal_ids": spot_check_ids,
    }


def _build_methodology_markdown(paths: ResolvedPaths, source_paths: dict[str, Path]) -> str:
    lines = [
        "# Context Enrichment Methodology",
        "",
        "This run implements the bounded direct-entry context-enrichment slice documented in `docs/workflow/enrichment_plan.md` and `docs/workflow/context_enrichment_implementation_memo.md`.",
        "",
        "## Scope",
        "- study-area type: `approach_shaped` only",
        "- enrichment units: approach rows, signal study areas, and classified crashes",
        "- AADT selection: exact route support, positive AADT, latest non-null year, unique best overlap",
        "- access assignment: exact route support, measure tolerance `0.005` miles, row distance `<= 60.0` feet, near-signal threshold `<= 65.6` feet",
        "- rural/urban: crash-context aggregation only from crash `AREA_TYPE`",
        "",
        "## Source files",
    ]
    for name, path in source_paths.items():
        lines.append(f"- `{name}`: `{path}`")
    lines.extend(
        [
            "",
            "## Reserved direct-entry command",
            f"- `<bootstrap-reported-python> -m src.active.context_enrichment{' --run-label ' + paths.run_label if paths.run_label else ''}`",
            "",
            "## Explicit exclusions",
            "- no Oracle",
            "- no `EDGE_RTE_KEY` fallback",
            "- no undocumented `AADT_QUALITY` ranking",
            "- no suburban classification",
            "- no statewide segment enrichment",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_validation_summary_markdown(validation: dict[str, object]) -> str:
    source_counts = validation["source_row_counts"]
    field_validation = validation["field_validation"]
    aadt = validation["aadt"]
    access = validation["access"]
    rural_urban = validation["rural_urban"]
    signal_summary_duplicates = validation["signal_summary_duplicates"]
    spot_checks = validation["required_spot_check_signal_ids"]
    aadt_diagnostics = aadt["candidate_generation_diagnostics"]

    lines = [
        "# Context Enrichment Validation Summary",
        "",
        "## Source row counts",
    ]
    for key, value in source_counts.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Base-table validation",
            f"- approach-row base row count matches source: `{field_validation['approach_row_base_row_count_matches_source']}`",
            f"- signal base row count matches source: `{field_validation['signal_base_row_count_matches_source']}`",
            f"- approach-row duplicate key count: `{field_validation['approach_row_duplicate_key_count']}`",
            f"- signal-base duplicate key count: `{field_validation['signal_base_duplicate_key_count']}`",
            f"- approach rows with successful road-range joins: `{field_validation['approach_rows_with_successful_road_range_joins']}`",
            "",
            "## AADT",
            f"- approach rows with any AADT candidate: `{aadt['approach_rows_with_any_candidate']}`",
            f"- approach rows with selected AADT: `{aadt['approach_rows_with_selected_aadt']}`",
            f"- study areas with selected AADT: `{aadt['study_areas_with_selected_aadt']}`",
            f"- AADT status counts: `{json.dumps(aadt['status_counts'], sort_keys=True)}`",
            f"- AADT reason counts: `{json.dumps(aadt['reason_counts'], sort_keys=True)}`",
            f"- AADT selected year distribution: `{json.dumps(aadt['year_distribution_selected'], sort_keys=True)}`",
            f"- AADT selected quality distribution: `{json.dumps(aadt['quality_distribution_selected'], sort_keys=True)}`",
            f"- AADT overlap-share distribution: `{json.dumps(aadt['overlap_share_distribution_selected'], sort_keys=True)}`",
            f"- AADT candidate-generation diagnostics: `{json.dumps(aadt_diagnostics, sort_keys=True)}`",
            "",
            "## Access",
            f"- candidate access points in study areas: `{access['candidate_access_points_in_study_areas']}`",
            f"- access assignment status counts: `{json.dumps(access['assignment_status_counts'], sort_keys=True)}`",
            f"- access assignment reason counts: `{json.dumps(access['assignment_reason_counts'], sort_keys=True)}`",
            f"- access distance distribution (ft): `{json.dumps(access['distance_distribution_ft'], sort_keys=True)}`",
            f"- near-signal access point count: `{access['near_signal_count']}`",
            f"- approach rows with nonzero access density: `{access['approach_rows_with_nonzero_access_density']}`",
            "",
            "## Rural/Urban",
            f"- crash `AREA_TYPE` completeness in normalized source: `{rural_urban['crash_area_type_completeness_source']}`",
            f"- crash `AREA_TYPE` completeness in enriched classified-crash output: `{rural_urban['crash_area_type_completeness_enriched']}`",
            f"- dominant-class distribution by signal: `{json.dumps(rural_urban['dominant_class_distribution_by_signal'], sort_keys=True)}`",
            "",
            "## Signal Summary Duplicates",
            f"- duplicated source rows: `{signal_summary_duplicates['duplicated_row_count']}`",
            f"- duplicated `StudyAreaID` count: `{signal_summary_duplicates['duplicated_studyarea_count']}`",
            f"- duplicate group size distribution: `{json.dumps(signal_summary_duplicates['duplicate_group_size_distribution'], sort_keys=True)}`",
            f"- identifier conflict count: `{signal_summary_duplicates['identifier_conflict_count']}`",
            f"- additive total-count matches against crash rows: `{signal_summary_duplicates['count_sum_matches_crash_rows_count']}`",
            f"- additive unresolved-count matches against crash rows: `{signal_summary_duplicates['unresolved_sum_matches_crash_rows_count']}`",
            f"- additive high-attachment matches against crash rows: `{signal_summary_duplicates['high_attachment_sum_matches_crash_rows_count']}`",
            f"- additive medium-attachment matches against crash rows: `{signal_summary_duplicates['medium_attachment_sum_matches_crash_rows_count']}`",
            f"- additive ambiguous-signal matches against crash rows: `{signal_summary_duplicates['ambiguous_signal_sum_matches_crash_rows_count']}`",
            f"- duplicate field disagreement counts: `{json.dumps(signal_summary_duplicates['field_disagreement_group_counts'], sort_keys=True)}`",
            "",
            "## Required spot checks",
        ]
    )
    if spot_checks:
        for signal_id in spot_checks:
            lines.append(f"- `{signal_id}`")
    else:
        lines.append("- none available from this run")
    return "\n".join(lines) + "\n"


def _build_output_layout_readme(output_files: dict[str, str], output_dir: Path) -> str:
    current_sections = [
        ("tables/current", TABLES_CURRENT_SUBDIR),
        ("review/current", REVIEW_CURRENT_SUBDIR),
        ("review/geojson/current", REVIEW_GEOJSON_CURRENT_SUBDIR),
        ("runs/current", RUNS_CURRENT_SUBDIR),
    ]
    lines = [
        "# Context Enrichment Outputs",
        "",
        "This output folder contains the bounded context-enrichment slice for the current divided-road, signal-centered workflow.",
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
            "- `tables/history/`, `review/history/`, `review/geojson/history/`, and `runs/history/` hold timestamped fallback writes when stable targets cannot be replaced.",
            "- Active downstream consumers should prefer the stable `current/` paths.",
        ]
    )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded direct-entry context enrichment for the current signal-centered upstream/downstream workflow. "
            "This is not a statewide segment enrichment pipeline."
        )
    )
    parser.add_argument("--prototype-root", default=None, help="Override the upstream/downstream prototype root.")
    parser.add_argument("--study-slice-root", default=None, help="Override the stage1b study-slice root.")
    parser.add_argument("--normalized-root", default=None, help="Override the normalized artifact root.")
    parser.add_argument("--output-root", default=None, help="Override the context-enrichment output root.")
    parser.add_argument("--run-label", default=None, help="Optional run label copied into run metadata.")
    return parser.parse_args(argv)


def run_context_enrichment(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = _resolve_paths(args)
    inputs = _load_inputs(paths)

    output_dir = paths.output_root
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_current_dir = _output_subdir(output_dir, *TABLES_CURRENT_SUBDIR)
    tables_history_dir = _output_subdir(output_dir, *TABLES_HISTORY_SUBDIR)
    review_current_dir = _output_subdir(output_dir, *REVIEW_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_HISTORY_SUBDIR)
    review_geojson_current_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_CURRENT_SUBDIR)
    review_geojson_history_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_HISTORY_SUBDIR)
    runs_current_dir = _output_subdir(output_dir, *RUNS_CURRENT_SUBDIR)
    runs_history_dir = _output_subdir(output_dir, *RUNS_HISTORY_SUBDIR)

    approach_row_base, approach_row_geometry = _build_approach_row_context_base(inputs)
    signal_base, signal_geometry = _build_signal_study_area_context_base(inputs)

    aadt_candidates, aadt_row_selection = _build_aadt_candidates(approach_row_base, approach_row_geometry, inputs.aadt)
    aadt_all_rows = _aadt_no_candidate_rows(approach_row_base, aadt_row_selection, approach_row_geometry)
    approach_with_aadt = approach_row_base.merge(
        aadt_all_rows,
        on=["StudyAreaID", "StudyRoad_RowID"],
        how="left",
        validate="one_to_one",
    )
    signal_aadt = _aggregate_signal_aadt(approach_with_aadt)

    access_points, access_points_geo = _build_access_assignment_points(
        approach_with_aadt,
        approach_row_geometry,
        signal_base,
        signal_geometry,
        inputs.signals,
        inputs.access,
    )
    access_row_agg = _aggregate_access_to_rows(approach_with_aadt, access_points)
    access_signal_agg = _aggregate_access_to_signals(signal_base, approach_with_aadt, access_points)

    crash_context, ru_row, ru_signal = _build_rural_urban_outputs(inputs.crash_classifications, inputs.crash_area_type)

    approach_enriched = (
        approach_with_aadt.merge(access_row_agg, on=["StudyAreaID", "StudyRoad_RowID"], how="left", validate="one_to_one")
        .merge(ru_row, on=["StudyAreaID", "StudyRoad_RowID"], how="left", validate="one_to_one")
    )
    signal_enriched = (
        signal_base.merge(signal_aadt, on="StudyAreaID", how="left", validate="one_to_one")
        .merge(access_signal_agg, on="StudyAreaID", how="left", validate="one_to_one")
        .merge(ru_signal, on="StudyAreaID", how="left", validate="one_to_one")
    )
    crash_context_enriched = _build_classified_crash_context_enriched(crash_context, approach_enriched, signal_enriched)

    validation = _build_validation_metrics(
        inputs,
        approach_row_base,
        signal_base,
        aadt_candidates,
        approach_enriched,
        access_points,
        crash_context_enriched,
        signal_enriched,
    )

    approach_review = approach_row_geometry[["StudyAreaID", "StudyRoad_RowID", "geometry"]].merge(
        approach_enriched,
        on=["StudyAreaID", "StudyRoad_RowID"],
        how="left",
        validate="one_to_one",
    )
    signal_review = signal_geometry[["StudyAreaID", "geometry"]].merge(
        signal_enriched,
        on="StudyAreaID",
        how="left",
        validate="one_to_one",
    )
    high_conf_review = inputs.classified_high_confidence[["Crash_RowID", "geometry"]].merge(
        crash_context_enriched,
        on="Crash_RowID",
        how="left",
        validate="one_to_one",
    )
    aadt_ambiguous_review = approach_review.loc[approach_review["AADT_Status"].eq("ambiguous")].copy()

    output_files = {
        "approach_row_context_base": str(
            _write_csv_frame(
                approach_row_base,
                tables_current_dir / "approach_row_context_base.csv",
                history_dir=tables_history_dir,
            )
        ),
        "approach_row_context_enriched": str(
            _write_csv_frame(
                approach_enriched,
                tables_current_dir / "approach_row_context_enriched.csv",
                history_dir=tables_history_dir,
            )
        ),
        "signal_study_area_context_base": str(
            _write_csv_frame(
                signal_base,
                tables_current_dir / "signal_study_area_context_base.csv",
                history_dir=tables_history_dir,
            )
        ),
        "signal_study_area_context_enriched": str(
            _write_csv_frame(
                signal_enriched,
                tables_current_dir / "signal_study_area_context_enriched.csv",
                history_dir=tables_history_dir,
            )
        ),
        "classified_crash_context_enriched": str(
            _write_csv_frame(
                crash_context_enriched,
                tables_current_dir / "classified_crash_context_enriched.csv",
                history_dir=tables_history_dir,
            )
        ),
        "aadt_match_candidates": str(
            _write_csv_frame(
                aadt_candidates,
                tables_current_dir / "aadt_match_candidates.csv",
                history_dir=tables_history_dir,
            )
        ),
        "access_assignment_points": str(
            _write_csv_frame(
                access_points,
                tables_current_dir / "access_assignment_points.csv",
                history_dir=tables_history_dir,
            )
        ),
        "rural_urban_crash_context_summary": str(
            _write_csv_frame(
                signal_enriched[
                    [
                        "StudyAreaID",
                        "Signal_RowID",
                        "SignalLabel",
                        "SignalRouteName",
                        "RU_CrashContext_RuralCount",
                        "RU_CrashContext_UrbanCount",
                        "RU_CrashContext_UnresolvedCount",
                        "RU_CrashContext_DominantClass",
                        "RU_CrashContext_DominantShare",
                        "RU_ContextStatus",
                        "RU_ContextReason",
                    ]
                ],
                tables_current_dir / "rural_urban_crash_context_summary.csv",
                history_dir=tables_history_dir,
            )
        ),
        "context_enrichment_methodology": str(
            _write_text_file(
                _build_methodology_markdown(paths, inputs.source_paths),
                review_current_dir / "context_enrichment_methodology.md",
                history_dir=review_history_dir,
            )
        ),
        "context_enrichment_validation_summary": str(
            _write_text_file(
                _build_validation_summary_markdown(validation),
                review_current_dir / "context_enrichment_validation_summary.md",
                history_dir=review_history_dir,
            )
        ),
        "approach_row_context_enriched_geojson": str(
            _write_geojson_frame(
                gpd.GeoDataFrame(approach_review, geometry="geometry", crs=approach_row_geometry.crs),
                review_geojson_current_dir / "approach_row_context_enriched.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
        "signal_study_area_context_enriched_geojson": str(
            _write_geojson_frame(
                gpd.GeoDataFrame(signal_review, geometry="geometry", crs=signal_geometry.crs),
                review_geojson_current_dir / "signal_study_area_context_enriched.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
        "classified_crash_context_high_confidence_geojson": str(
            _write_geojson_frame(
                gpd.GeoDataFrame(high_conf_review, geometry="geometry", crs=inputs.classified_high_confidence.crs),
                review_geojson_current_dir / "classified_crash_context_high_confidence.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
        "access_assignment_points_geojson": str(
            _write_geojson_frame(
                gpd.GeoDataFrame(access_points_geo, geometry="geometry", crs=inputs.access.crs),
                review_geojson_current_dir / "access_assignment_points.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
        "aadt_ambiguous_rows_geojson": str(
            _write_geojson_frame(
                gpd.GeoDataFrame(aadt_ambiguous_review, geometry="geometry", crs=approach_row_geometry.crs),
                review_geojson_current_dir / "aadt_ambiguous_rows.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
    }

    run_summary = {
        "interpreter": sys.executable,
        "command": "python -m src.active.context_enrichment",
        "run_label": paths.run_label,
        "working_crs": paths.working_crs,
        "source_paths": {key: str(value) for key, value in inputs.source_paths.items()},
        "validation": validation,
        "output_files": output_files.copy(),
        "assumptions": [
            "AADT_QUALITY is reported but not ranked because the contract does not document a trustworthy ordering.",
            "When all route-supported positive AADT candidates have null years, selection falls through to unique-best-overlap without inventing a year ranking.",
            "Sparse same-class rural/urban crash context below the minimum dominant-count threshold is treated as unresolved.",
        ],
    }
    run_summary_path = _write_json_object(
        run_summary,
        runs_current_dir / "context_enrichment_run_summary.json",
        history_dir=runs_history_dir,
    )
    output_files["context_enrichment_run_summary"] = str(run_summary_path)
    readme_path = _write_text_file(
        _build_output_layout_readme(output_files, output_dir),
        output_dir / "README.md",
    )
    output_files["readme"] = str(readme_path)
    run_summary["output_files"] = output_files
    run_summary_path.write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    print(json.dumps(run_summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_context_enrichment(argv)


if __name__ == "__main__":
    raise SystemExit(main())
