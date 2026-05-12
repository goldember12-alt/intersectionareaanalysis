from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time

import geopandas as gpd
import pandas as pd
from geopandas.array import GeometryDtype
from shapely.geometry import LineString, MultiLineString
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
OUTPUT_REPLACE_RETRIES = 3
OUTPUT_REPLACE_RETRY_SECONDS = 0.5

ACCESS_MAX_TO_ROW_DISTANCE_FT = 60.0
ACCESS_MEASURE_TOLERANCE_MI = 0.005
ACCESS_NEAR_SIGNAL_THRESHOLD_FT = 65.6
ACCESS_SAME_CORRIDOR_FAMILY_TABLE = Path("docs/workflow/context_enrichment_access_same_corridor_seed_families.csv")
ACCESS_SAME_CORRIDOR_RULE = "reviewed_family_local_distance_unique_row_project_compare"
ACCESS_SAME_CORRIDOR_DISTANCE_TIE_TOLERANCE_FT = 0.01
AADT_LOCAL_DISTANCE_MAX_FT = 3.0
DISTANCE_BAND_WIDTH_FT = 50.0
DISTANCE_BAND_FAMILY = "fixed_50ft_from_signal_within_study_area"
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
ACCESS_SAME_CORRIDOR_FAMILY_REQUIRED_FIELDS = [
    "FamilyKey",
    "ReviewDecision",
    "AccessRouteNorm",
    "StudyRouteNorm",
    "LocalDistanceMaxFt",
]


@dataclass(frozen=True)
class ResolvedPaths:
    prototype_root: Path
    study_slice_root: Path
    normalized_root: Path
    output_root: Path
    same_corridor_family_table: Path
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
    same_corridor_family_table: pd.DataFrame


def _output_subdir(output_dir: Path, *parts: str) -> Path:
    path = output_dir.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_output_path(path: Path, history_dir: Path | None = None) -> Path:
    return path


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
    resolved = _prepare_output_path(path, history_dir=history_dir)
    frame.to_csv(resolved, index=False)
    _copy_output_to_history(resolved, history_dir)
    return resolved


def _write_json_object(payload: dict[str, object], path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _copy_output_to_history(resolved, history_dir)
    return resolved


def _write_text_file(content: str, path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    resolved.write_text(content, encoding="utf-8")
    _copy_output_to_history(resolved, history_dir)
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
    _copy_output_to_history(resolved, history_dir)
    return resolved


def _normalize_route_name(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = " ".join(str(value).strip().split())
    return normalized or None


def _distance_band_start_ft(distance_ft: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([distance_ft]), errors="coerce").iloc[0]
    if pd.isna(numeric) or float(numeric) < 0:
        return None
    return float(int(float(numeric) // DISTANCE_BAND_WIDTH_FT) * int(DISTANCE_BAND_WIDTH_FT))


def _distance_band_fields(distance_ft: object) -> dict[str, object]:
    start_ft = _distance_band_start_ft(distance_ft)
    if start_ft is None:
        return {
            "DistanceBandFamily": None,
            "DistanceBandStartFt": None,
            "DistanceBandEndFt": None,
            "DistanceBandLabel": None,
        }
    end_ft = float(start_ft + DISTANCE_BAND_WIDTH_FT)
    return {
        "DistanceBandFamily": DISTANCE_BAND_FAMILY,
        "DistanceBandStartFt": start_ft,
        "DistanceBandEndFt": end_ft,
        "DistanceBandLabel": f"{int(start_ft)}-{int(end_ft)}",
    }


def _study_area_band_records(signal_base: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    id_columns = [
        "StudyAreaID",
        "Signal_RowID",
        "REG_SIGNAL_ID",
        "SIGNAL_NO",
        "SignalLabel",
        "SignalRouteName",
    ]
    for row in signal_base[id_columns + ["ApproachLengthMeters"]].itertuples(index=False):
        length_numeric = pd.to_numeric(pd.Series([row.ApproachLengthMeters]), errors="coerce").iloc[0]
        if pd.isna(length_numeric) or float(length_numeric) <= 0:
            continue
        approach_length_ft = float(length_numeric) * METERS_TO_FEET
        band_end_ceiling = int(max(DISTANCE_BAND_WIDTH_FT, DISTANCE_BAND_WIDTH_FT * ((int(approach_length_ft - 1e-9) // int(DISTANCE_BAND_WIDTH_FT)) + 1)))
        for band_start_ft in range(0, band_end_ceiling, int(DISTANCE_BAND_WIDTH_FT)):
            band_end_ft = float(band_start_ft + int(DISTANCE_BAND_WIDTH_FT))
            records.append(
                {
                    "StudyAreaID": str(row.StudyAreaID),
                    "Signal_RowID": _int_or_na(row.Signal_RowID),
                    "REG_SIGNAL_ID": row.REG_SIGNAL_ID,
                    "SIGNAL_NO": row.SIGNAL_NO,
                    "SignalLabel": row.SignalLabel,
                    "SignalRouteName": row.SignalRouteName,
                    "StudyAreaApproachLengthFt": approach_length_ft,
                    "DistanceBandFamily": DISTANCE_BAND_FAMILY,
                    "DistanceBandStartFt": float(band_start_ft),
                    "DistanceBandEndFt": band_end_ft,
                    "DistanceBandLabel": f"{band_start_ft}-{int(band_end_ft)}",
                }
            )
    return pd.DataFrame(records)


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


def _load_same_corridor_family_table(path: Path) -> pd.DataFrame:
    frame = _load_csv(path, "context_enrichment_access_same_corridor_seed_families.csv", ACCESS_SAME_CORRIDOR_FAMILY_REQUIRED_FIELDS)
    frame = frame.copy()
    frame["FamilyKey"] = frame["FamilyKey"].astype(str)
    frame["ReviewDecision"] = frame["ReviewDecision"].astype(str).str.strip().str.lower()
    frame["AccessRouteNorm"] = frame["AccessRouteNorm"].map(_normalize_route_name)
    frame["StudyRouteNorm"] = frame["StudyRouteNorm"].map(_normalize_route_name)
    frame["LocalDistanceMaxFt"] = _to_numeric(frame["LocalDistanceMaxFt"])
    valid_decisions = {"include", "exclude"}
    invalid_decisions = sorted(set(frame["ReviewDecision"]) - valid_decisions)
    if invalid_decisions:
        raise ValueError(f"Same-corridor family table contains unsupported ReviewDecision values: {invalid_decisions}")
    duplicate_pairs = frame.duplicated(subset=["ReviewDecision", "AccessRouteNorm", "StudyRouteNorm"], keep=False)
    if bool(duplicate_pairs.any()):
        raise ValueError("Same-corridor family table contains duplicate review rows for the same decision and route pair.")
    include_missing_threshold = frame["ReviewDecision"].eq("include") & (
        frame["LocalDistanceMaxFt"].isna() | frame["LocalDistanceMaxFt"].le(0)
    )
    if bool(include_missing_threshold.any()):
        raise ValueError("Included same-corridor families require a positive LocalDistanceMaxFt.")
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
    repo_root = Path(__file__).resolve().parents[2]
    prototype_root = Path(args.prototype_root) if args.prototype_root else config.output_dir / "upstream_downstream_prototype"
    study_slice_root = Path(args.study_slice_root) if args.study_slice_root else config.output_dir / "stage1b_study_slice"
    normalized_root = Path(args.normalized_root) if args.normalized_root else config.normalized_dir
    output_root = Path(args.output_root) if args.output_root else config.output_dir / OUTPUT_FOLDER_NAME
    same_corridor_family_table = (
        Path(args.same_corridor_family_table)
        if args.same_corridor_family_table
        else repo_root / ACCESS_SAME_CORRIDOR_FAMILY_TABLE
    )
    return ResolvedPaths(
        prototype_root=prototype_root,
        study_slice_root=study_slice_root,
        normalized_root=normalized_root,
        output_root=output_root,
        same_corridor_family_table=same_corridor_family_table,
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
        "same_corridor_access_family_table": paths.same_corridor_family_table,
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
    same_corridor_family_table = _load_same_corridor_family_table(source_paths["same_corridor_access_family_table"])

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
        same_corridor_family_table=same_corridor_family_table,
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
        raise ValueError(
            "signal_study_area_summary__approach_shaped.csv must be one row per StudyAreaID after the upstream summary fix; "
            "unexpected duplicates remain for: "
            + ", ".join(str(value) for value in duplicate_ids)
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


def _same_corridor_candidate_decision(
    evaluations: list[dict[str, object]],
    *,
    signal_projection_supported: bool = True,
    distance_tie_tolerance_ft: float = ACCESS_SAME_CORRIDOR_DISTANCE_TIE_TOLERANCE_FT,
) -> dict[str, object]:
    approved_route_present = any(bool(item.get("approved_pair")) for item in evaluations)
    if not approved_route_present:
        return {
            "status": "approved_study_route_not_present",
            "reason": "approved_family_route_absent_in_study_area",
            "winner": None,
        }

    approved_within_threshold = [item for item in evaluations if bool(item.get("within_threshold"))]
    if not approved_within_threshold:
        return {
            "status": "no_local_geometry_support",
            "reason": "approved_family_row_outside_local_threshold",
            "winner": None,
        }
    if len(approved_within_threshold) > 1:
        return {
            "status": "ambiguous_local_geometry",
            "reason": "multiple_approved_rows_within_threshold",
            "winner": None,
        }

    ordered_evaluations = sorted(
        [item for item in evaluations if item.get("distance_ft") is not None],
        key=lambda item: (float(item["distance_ft"]), int(item["StudyRoad_RowID"])),
    )
    if not ordered_evaluations:
        return {
            "status": "no_local_geometry_support",
            "reason": "no_usable_candidate_geometry",
            "winner": None,
        }

    winner = approved_within_threshold[0]
    overall_nearest = ordered_evaluations[0]
    overall_second = ordered_evaluations[1] if len(ordered_evaluations) > 1 else None
    if int(overall_nearest["StudyRoad_RowID"]) != int(winner["StudyRoad_RowID"]):
        return {
            "status": "nearest_row_not_approved_pair",
            "reason": "nearest_row_not_in_reviewed_family",
            "winner": None,
        }
    if (
        overall_second is not None
        and abs(float(overall_second["distance_ft"]) - float(overall_nearest["distance_ft"]))
        <= distance_tie_tolerance_ft
    ):
        return {
            "status": "ambiguous_nearest_row",
            "reason": "nearest_row_tie_within_0_01ft",
            "winner": None,
        }
    if not signal_projection_supported:
        return {
            "status": "missing_flow_or_projection",
            "reason": "missing_flow_or_projection",
            "winner": None,
        }
    return {
        "status": "candidate_supported",
        "reason": "reviewed_family_unique_local_geometry_supported",
        "winner": winner,
    }


def _populate_access_signal_distance_fields(final_record: dict[str, object]) -> None:
    projection_ft = pd.to_numeric(pd.Series([final_record.get("Access_ProjectionFt")]), errors="coerce").iloc[0]
    signal_projection_ft = pd.to_numeric(pd.Series([final_record.get("Access_SignalProjectionFt")]), errors="coerce").iloc[0]
    if pd.isna(projection_ft) or pd.isna(signal_projection_ft):
        return
    distance_ft = abs(float(projection_ft) - float(signal_projection_ft))
    final_record["Access_DistanceFromSignalFt"] = distance_ft
    position = final_record.get("Access_SignalRelativePosition")
    if position == "downstream":
        band_fields = _distance_band_fields(distance_ft)
        final_record["Access_SignalOffsetFt"] = distance_ft
        final_record["Access_DownstreamDistanceFt"] = distance_ft
        final_record["Access_DistanceBandFamily"] = band_fields["DistanceBandFamily"]
        final_record["Access_DistanceBandStartFt"] = band_fields["DistanceBandStartFt"]
        final_record["Access_DistanceBandEndFt"] = band_fields["DistanceBandEndFt"]
        final_record["Access_DistanceBandLabel"] = band_fields["DistanceBandLabel"]
    elif position == "upstream":
        final_record["Access_SignalOffsetFt"] = -distance_ft


def _build_aadt_candidates(
    approach_row_base: pd.DataFrame,
    approach_row_geometry: gpd.GeoDataFrame,
    aadt: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    key_columns = ["StudyAreaID", "StudyRoad_RowID"]
    support_rank = {"master_rte_exact": 1, "rte_nm_exact": 2}
    selection_columns = [
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
        "AADT_RouteSupportEvidence",
        "AADT_MeasureOverlapMiles",
        "AADT_LocalGeometryDistanceFt",
    ]

    geom = approach_row_geometry[
        ["StudyAreaID", "StudyRoad_RowID", "Signal_RowID", "SignalRouteName", "ApproachLengthMeters", "geometry"]
    ].copy().merge(
        approach_row_base[["StudyAreaID", "StudyRoad_RowID", "ApproachRoad_FROM_MEASURE", "ApproachRoad_TO_MEASURE"]],
        on=key_columns,
        how="left",
        validate="one_to_one",
    )
    geom["SignalRouteName_Normalized"] = geom["SignalRouteName"].map(_normalize_route_name)

    aadt_fields = [
        "RTE_NM",
        "MASTER_RTE_NM",
        "LINKID",
        "AADT",
        "AADT_YR",
        "AADT_QUALITY",
        "DIRECTIONALITY",
        "DIRECTION_FACTOR",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "AADT_SourceRoute_Normalized",
        "AADT_MasterRoute_Normalized",
        "geometry",
    ]
    aadt_view = aadt[aadt_fields].copy()
    aadt_view["AADT_Value_Numeric"] = _to_numeric(aadt_view["AADT"])
    aadt_view["AADT_Year_Numeric"] = _to_numeric(aadt_view["AADT_YR"])

    source_merge = geom.merge(
        aadt_view,
        left_on="SignalRouteName_Normalized",
        right_on="AADT_SourceRoute_Normalized",
        how="left",
    )
    source_merge["AADT_RouteSupportTier"] = "rte_nm_exact"
    source_merge["AADT_RouteSupportEvidence"] = "rte_nm_exact"

    master_merge = geom.merge(
        aadt_view,
        left_on="SignalRouteName_Normalized",
        right_on="AADT_MasterRoute_Normalized",
        how="left",
    )
    master_merge = master_merge.loc[
        ~master_merge["SignalRouteName_Normalized"].eq(master_merge["AADT_SourceRoute_Normalized"])
    ].copy()
    master_merge["AADT_RouteSupportTier"] = "master_rte_exact"
    master_merge["AADT_RouteSupportEvidence"] = "master_rte_exact"

    route_supported = pd.concat([source_merge, master_merge], ignore_index=True)
    route_supported = route_supported.loc[route_supported["LINKID"].notna()].copy()
    diagnostics = {
        "approach_geometry_notnull_count": int(geom.geometry.notna().sum()),
        "approach_geometry_valid_count": int(geom.geometry.is_valid.fillna(False).sum()),
        "aadt_geometry_notnull_count": int(aadt.geometry.notna().sum()),
        "aadt_geometry_valid_count": int(aadt.geometry.is_valid.fillna(False).sum()),
        "working_crs_approach_rows": str(geom.crs),
        "working_crs_aadt": str(aadt.crs),
        "route_supported_candidate_pair_count": int(len(route_supported)),
        "route_supported_candidate_row_count": int(route_supported[key_columns].drop_duplicates().shape[0]) if not route_supported.empty else 0,
    }

    if route_supported.empty:
        row_selection = pd.DataFrame(
            [
                {
                    "StudyAreaID": row["StudyAreaID"],
                    "StudyRoad_RowID": row["StudyRoad_RowID"],
                    "AADT_CandidateCount": 0,
                    "AADT_SelectionRule": "route_exact_measure_overlap_local_3ft_required",
                    "AADT_Status": "no_route_supported_candidate",
                    "AADT_Reason": "no_exact_route_supported_candidate",
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
                    "AADT_RouteSupportEvidence": None,
                    "AADT_MeasureOverlapMiles": None,
                    "AADT_LocalGeometryDistanceFt": None,
                }
                for _, row in geom.iterrows()
            ]
        )
        diagnostics.update(
            {
                "measure_supported_candidate_pair_count": 0,
                "measure_supported_candidate_row_count": 0,
                "local_support_candidate_pair_count": 0,
                "local_support_candidate_row_count": 0,
                "local_distance_threshold_ft": AADT_LOCAL_DISTANCE_MAX_FT,
                "measure_overlap_distribution_local_candidates": {"min": None, "median": None, "max": None},
                "local_distance_distribution_local_candidates": {"min": None, "median": None, "max": None},
                "matched_example_rows": [],
                "ambiguous_example_rows": [],
            }
        )
        return pd.DataFrame(columns=selection_columns + ["AADT_Selected", "AADT_RowStatus", "AADT_RowReason"]), row_selection, diagnostics

    route_supported["AADT_MeasureOverlapMiles"] = route_supported.apply(
        lambda row: _measure_overlap_amount(
            row["ApproachRoad_FROM_MEASURE"],
            row["ApproachRoad_TO_MEASURE"],
            row["TRANSPORT_EDGE_FROM_MSR"],
            row["TRANSPORT_EDGE_TO_MSR"],
        ),
        axis=1,
    )
    measure_supported = route_supported.loc[route_supported["AADT_MeasureOverlapMiles"].fillna(0).gt(0)].copy()
    diagnostics["measure_supported_candidate_pair_count"] = int(len(measure_supported))
    diagnostics["measure_supported_candidate_row_count"] = (
        int(measure_supported[key_columns].drop_duplicates().shape[0]) if not measure_supported.empty else 0
    )

    if not measure_supported.empty:
        measure_supported["AADT_LocalGeometryDistanceFt"] = (
            gpd.GeoSeries(measure_supported["geometry_x"], index=measure_supported.index, crs=geom.crs).distance(
                gpd.GeoSeries(measure_supported["geometry_y"], index=measure_supported.index, crs=aadt.crs)
            )
            * METERS_TO_FEET
        )
    else:
        measure_supported["AADT_LocalGeometryDistanceFt"] = pd.Series(dtype="float64")
    local_supported = measure_supported.loc[measure_supported["AADT_LocalGeometryDistanceFt"].le(AADT_LOCAL_DISTANCE_MAX_FT)].copy()
    diagnostics["local_support_candidate_pair_count"] = int(len(local_supported))
    diagnostics["local_support_candidate_row_count"] = (
        int(local_supported[key_columns].drop_duplicates().shape[0]) if not local_supported.empty else 0
    )
    diagnostics["local_distance_threshold_ft"] = AADT_LOCAL_DISTANCE_MAX_FT
    diagnostics["measure_overlap_distribution_local_candidates"] = {
        "min": float(local_supported["AADT_MeasureOverlapMiles"].min()) if not local_supported.empty else None,
        "median": float(local_supported["AADT_MeasureOverlapMiles"].median()) if not local_supported.empty else None,
        "max": float(local_supported["AADT_MeasureOverlapMiles"].max()) if not local_supported.empty else None,
    }
    diagnostics["local_distance_distribution_local_candidates"] = {
        "min": float(local_supported["AADT_LocalGeometryDistanceFt"].min()) if not local_supported.empty else None,
        "median": float(local_supported["AADT_LocalGeometryDistanceFt"].median()) if not local_supported.empty else None,
        "max": float(local_supported["AADT_LocalGeometryDistanceFt"].max()) if not local_supported.empty else None,
    }

    if not local_supported.empty:
        local_supported["AADT_RouteSupportRank"] = local_supported["AADT_RouteSupportTier"].map(support_rank).fillna(0).astype(int)
        dedupe_fields = [
            "StudyAreaID",
            "StudyRoad_RowID",
            "Signal_RowID",
            "SignalRouteName",
            "LINKID",
            "AADT",
            "AADT_YR",
            "AADT_QUALITY",
            "DIRECTIONALITY",
            "DIRECTION_FACTOR",
            "AADT_Value_Numeric",
            "AADT_Year_Numeric",
            "AADT_MeasureOverlapMiles",
            "AADT_LocalGeometryDistanceFt",
        ]
        candidates = (
            local_supported.groupby(dedupe_fields, dropna=False, as_index=False)
            .agg(
                AADT_SourceRoute=("RTE_NM", lambda values: _list_to_pipe(pd.Series(values).dropna().drop_duplicates().tolist())),
                AADT_MasterRoute=("MASTER_RTE_NM", lambda values: _list_to_pipe(pd.Series(values).dropna().drop_duplicates().tolist())),
                AADT_RouteSupportEvidence=("AADT_RouteSupportEvidence", lambda values: _list_to_pipe(pd.Series(values).dropna().drop_duplicates().tolist())),
                AADT_RouteSupportRank=("AADT_RouteSupportRank", "max"),
            )
            .rename(
                columns={
                    "LINKID": "AADT_LinkID",
                    "AADT": "AADT_Value",
                    "AADT_YR": "AADT_Year",
                    "AADT_QUALITY": "AADT_Quality",
                    "DIRECTIONALITY": "AADT_Directionality",
                    "DIRECTION_FACTOR": "AADT_DirectionFactor",
                }
            )
        )
        candidates["AADT_RouteSupportTier"] = candidates["AADT_RouteSupportRank"].map({1: "master_rte_exact", 2: "rte_nm_exact"})
        candidates = candidates.merge(
            geom[["StudyAreaID", "StudyRoad_RowID", "ApproachLengthMeters"]].drop_duplicates(subset=key_columns),
            on=key_columns,
            how="left",
            validate="many_to_one",
        )
        candidates["AADT_OverlapLengthFt"] = candidates["AADT_MeasureOverlapMiles"] * 5280.0
        candidates["AADT_OverlapShare"] = candidates.apply(
            lambda row: (
                row["AADT_OverlapLengthFt"] / (float(row["ApproachLengthMeters"]) * METERS_TO_FEET)
                if pd.notna(row["AADT_OverlapLengthFt"])
                and pd.notna(row["ApproachLengthMeters"])
                and float(row["ApproachLengthMeters"]) > 0
                else None
            ),
            axis=1,
        )
    else:
        candidates = pd.DataFrame(
            columns=[
                "StudyAreaID",
                "StudyRoad_RowID",
                "Signal_RowID",
                "SignalRouteName",
                "AADT_LinkID",
                "AADT_Value",
                "AADT_Year",
                "AADT_Quality",
                "AADT_Directionality",
                "AADT_DirectionFactor",
                "AADT_Value_Numeric",
                "AADT_Year_Numeric",
                "AADT_MeasureOverlapMiles",
                "AADT_LocalGeometryDistanceFt",
                "AADT_OverlapLengthFt",
                "AADT_OverlapShare",
                "AADT_SourceRoute",
                "AADT_MasterRoute",
                "AADT_RouteSupportEvidence",
                "AADT_RouteSupportRank",
                "AADT_RouteSupportTier",
            ]
        )

    row_level_results: list[dict[str, object]] = []
    candidate_records: list[pd.DataFrame] = []
    matched_examples: list[dict[str, object]] = []
    ambiguous_examples: list[dict[str, object]] = []
    route_counts = route_supported.groupby(key_columns, dropna=False).size().to_dict()
    measure_counts = measure_supported.groupby(key_columns, dropna=False).size().to_dict() if not measure_supported.empty else {}
    local_counts = candidates.groupby(key_columns, dropna=False).size().to_dict() if not candidates.empty else {}

    for _, approach_row in geom.iterrows():
        key = (approach_row["StudyAreaID"], approach_row["StudyRoad_RowID"])
        route_count = int(route_counts.get(key, 0))
        measure_count = int(measure_counts.get(key, 0))
        local_count = int(local_counts.get(key, 0))
        group = candidates.loc[
            candidates["StudyAreaID"].eq(approach_row["StudyAreaID"])
            & candidates["StudyRoad_RowID"].eq(approach_row["StudyRoad_RowID"])
        ].copy()
        group["AADT_CandidateCount"] = local_count
        group["AADT_Selected"] = False
        group["AADT_RowStatus"] = None
        group["AADT_RowReason"] = None
        group["AADT_SelectionRule"] = None
        selected_row = None

        if approach_row["geometry"] is None or (hasattr(approach_row["geometry"], "is_empty") and approach_row["geometry"].is_empty):
            status = "unresolved"
            reason = "missing_approach_geometry"
            selection_rule = "missing_approach_geometry"
        elif route_count == 0:
            status = "no_route_supported_candidate"
            reason = "no_exact_route_supported_candidate"
            selection_rule = "route_exact_required"
        elif measure_count == 0:
            status = "no_candidate"
            reason = "no_positive_measure_overlap_candidate"
            selection_rule = "route_exact_positive_measure_overlap_required"
        elif local_count == 0:
            status = "no_candidate"
            reason = "no_local_geometry_support_candidate"
            selection_rule = "route_exact_measure_overlap_local_3ft_required"
        else:
            positive = group.loc[group["AADT_Value_Numeric"].gt(0)].copy()
            if positive.empty:
                status = "invalid_value"
                reason = "all_rule_supported_candidates_invalid_aadt"
                selection_rule = "route_measure_local_candidates_without_positive_aadt"
            else:
                filtered = positive.copy()
                if filtered["AADT_Year_Numeric"].notna().any():
                    latest_year = filtered.loc[filtered["AADT_Year_Numeric"].notna(), "AADT_Year_Numeric"].max()
                    filtered = filtered.loc[filtered["AADT_Year_Numeric"].eq(latest_year)].copy()
                    selection_rule = "route_exact_measure_overlap_local_3ft_latest_year_support_measure_distance"
                else:
                    selection_rule = "route_exact_measure_overlap_local_3ft_no_nonnull_year_support_measure_distance"
                strongest_support = int(filtered["AADT_RouteSupportRank"].max())
                filtered = filtered.loc[filtered["AADT_RouteSupportRank"].eq(strongest_support)].copy()
                max_measure_overlap = filtered["AADT_MeasureOverlapMiles"].max()
                filtered = filtered.loc[filtered["AADT_MeasureOverlapMiles"].eq(max_measure_overlap)].copy()
                min_distance = filtered["AADT_LocalGeometryDistanceFt"].min()
                winners = filtered.loc[filtered["AADT_LocalGeometryDistanceFt"].eq(min_distance)].copy()
                if len(winners) == 1:
                    status = "matched"
                    reason = "unique_best_measure_distance_latest_year"
                    selected_row = winners.iloc[0]
                    selection_rule = f"{selection_rule}_unique_best"
                else:
                    status = "ambiguous"
                    reason = "tie_after_latest_year_measure_distance_filter"
                    selection_rule = f"{selection_rule}_tie"

        group["AADT_RowStatus"] = status
        group["AADT_RowReason"] = reason
        group["AADT_SelectionRule"] = selection_rule
        if selected_row is not None:
            selected_mask = (
                group["AADT_LinkID"].astype(str).eq(str(selected_row["AADT_LinkID"]))
                & group["AADT_MeasureOverlapMiles"].eq(selected_row["AADT_MeasureOverlapMiles"])
                & group["AADT_LocalGeometryDistanceFt"].eq(selected_row["AADT_LocalGeometryDistanceFt"])
                & group["AADT_RouteSupportTier"].eq(selected_row["AADT_RouteSupportTier"])
            )
            group.loc[selected_mask, "AADT_Selected"] = True
            if len(matched_examples) < 5:
                matched_examples.append(
                    {
                        "StudyAreaID": str(selected_row["StudyAreaID"]),
                        "StudyRoad_RowID": int(selected_row["StudyRoad_RowID"]),
                        "AADT_LinkID": str(selected_row["AADT_LinkID"]),
                        "AADT_Year": _int_or_na(selected_row["AADT_Year"]),
                        "AADT_MeasureOverlapMiles": round(float(selected_row["AADT_MeasureOverlapMiles"]), 6),
                        "AADT_LocalGeometryDistanceFt": round(float(selected_row["AADT_LocalGeometryDistanceFt"]), 4),
                    }
                )
        elif status == "ambiguous" and len(ambiguous_examples) < 5:
            ambiguous_examples.append(
                {
                    "StudyAreaID": str(approach_row["StudyAreaID"]),
                    "StudyRoad_RowID": int(approach_row["StudyRoad_RowID"]),
                    "AADT_CandidateCount": local_count,
                }
            )

        if not group.empty:
            candidate_records.append(group)

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
                "AADT_RouteSupportEvidence": None,
                "AADT_MeasureOverlapMiles": None,
                "AADT_LocalGeometryDistanceFt": None,
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
                "AADT_RouteSupportEvidence": selected_row["AADT_RouteSupportEvidence"],
                "AADT_MeasureOverlapMiles": selected_row["AADT_MeasureOverlapMiles"],
                "AADT_LocalGeometryDistanceFt": selected_row["AADT_LocalGeometryDistanceFt"],
            }

        row_level_results.append(
            {
                "StudyAreaID": approach_row["StudyAreaID"],
                "StudyRoad_RowID": approach_row["StudyRoad_RowID"],
                "AADT_CandidateCount": local_count,
                "AADT_SelectionRule": selection_rule,
                "AADT_Status": status,
                "AADT_Reason": reason,
                **selected_payload,
            }
        )

    candidate_output = pd.concat(candidate_records, ignore_index=True) if candidate_records else pd.DataFrame()
    row_selection = pd.DataFrame(row_level_results)
    if not candidate_output.empty:
        candidate_output = candidate_output.sort_values(
            ["StudyAreaID", "StudyRoad_RowID", "AADT_Selected", "AADT_Year_Numeric", "AADT_MeasureOverlapMiles", "AADT_LocalGeometryDistanceFt"],
            ascending=[True, True, False, False, False, True],
        ).reset_index(drop=True)
        candidate_output = candidate_output[
            [
                "StudyAreaID",
                "StudyRoad_RowID",
                "Signal_RowID",
                "SignalRouteName",
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
                "AADT_RouteSupportEvidence",
                "AADT_MeasureOverlapMiles",
                "AADT_LocalGeometryDistanceFt",
                "AADT_CandidateCount",
                "AADT_Selected",
                "AADT_SelectionRule",
                "AADT_RowStatus",
                "AADT_RowReason",
            ]
        ].copy()

    diagnostics["matched_example_rows"] = matched_examples
    diagnostics["ambiguous_example_rows"] = ambiguous_examples
    return candidate_output, row_selection, diagnostics


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
    merged.loc[no_selection_mask, "AADT_SelectionRule"] = "missing_aadt_selection_record"
    merged.loc[no_selection_mask, "AADT_Status"] = "unresolved"
    merged.loc[no_selection_mask, "AADT_Reason"] = "missing_aadt_selection_record"
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
            weights = _to_numeric(matched["AADT_MeasureOverlapMiles"])
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


def _measure_overlap_amount(
    first_from: object,
    first_to: object,
    second_from: object,
    second_to: object,
) -> float | None:
    first_start, first_end = _ordered_measure_range(first_from, first_to)
    second_start, second_end = _ordered_measure_range(second_from, second_to)
    if first_start is None or first_end is None or second_start is None or second_end is None:
        return None
    return max(0.0, min(first_end, second_end) - max(first_start, second_start))


def _list_to_pipe(values: list[object]) -> str | None:
    cleaned = [str(value) for value in values if value is not None and str(value).strip()]
    if not cleaned:
        return None
    return "|".join(cleaned)


def _apply_reviewed_same_corridor_overlay(
    *,
    final_record: dict[str, object],
    record: pd.Series,
    candidate_rows: pd.DataFrame,
    signal_point,
    normalized_access_route: str | None,
    include_routes_by_access: dict[str, pd.DataFrame],
    excluded_routes_by_access: dict[str, pd.DataFrame],
) -> None:
    include_rows = include_routes_by_access.get(normalized_access_route)
    exclude_rows = excluded_routes_by_access.get(normalized_access_route)
    if include_rows is None or include_rows.empty:
        if exclude_rows is not None and not exclude_rows.empty:
            final_record["Access_SameCorridorReviewStatus"] = "family_excluded"
            final_record["Access_SameCorridorRefusalReason"] = "review_table_excluded_for_production"
            final_record["Access_SameCorridorFamilyKey"] = _list_to_pipe(exclude_rows["FamilyKey"].astype(str).tolist())
        else:
            final_record["Access_SameCorridorReviewStatus"] = "no_reviewed_family"
            final_record["Access_SameCorridorRefusalReason"] = "no_reviewed_same_corridor_family"
        return

    final_record["Access_SameCorridorReviewStatus"] = "evaluated"
    final_record["Access_SameCorridorFamilyKey"] = _list_to_pipe(include_rows["FamilyKey"].astype(str).tolist())
    if len(include_rows) == 1:
        final_record["Access_SameCorridorLocalDistanceMaxFt"] = float(include_rows.iloc[0]["LocalDistanceMaxFt"])

    evaluations: list[dict[str, object]] = []
    for _, row in candidate_rows.iterrows():
        line = _normalize_line_geometry(row["geometry"])
        distance_ft = float(record["geometry"].distance(row["geometry"]) * METERS_TO_FEET) if line is not None else None
        candidate_route = row["Approach_Route_Normalized"]
        matching_family = include_rows.loc[include_rows["StudyRouteNorm"].eq(candidate_route)].copy()
        approved_pair = not matching_family.empty
        family_key = str(matching_family.iloc[0]["FamilyKey"]) if approved_pair else None
        local_distance_max_ft = float(matching_family.iloc[0]["LocalDistanceMaxFt"]) if approved_pair else None
        within_threshold = approved_pair and distance_ft is not None and distance_ft <= local_distance_max_ft
        evaluations.append(
            {
                "StudyRoad_RowID": int(row["StudyRoad_RowID"]),
                "LineGeometry": line,
                "FlowDirection": row["FlowDirection"],
                "distance_ft": distance_ft,
                "family_key": family_key,
                "local_distance_max_ft": local_distance_max_ft,
                "approved_pair": approved_pair,
                "within_threshold": within_threshold,
            }
        )

    approved_within_threshold = [item for item in evaluations if bool(item.get("within_threshold"))]
    nearest_distances = sorted([float(item["distance_ft"]) for item in evaluations if item.get("distance_ft") is not None])
    final_record["Access_SameCorridorApprovedRowsWithinThreshold"] = int(len(approved_within_threshold))
    final_record["Access_SameCorridorSecondNearestDistanceFt"] = nearest_distances[1] if len(nearest_distances) > 1 else None
    final_record["SameCorridorSupportedStudyRoadRowIDs"] = _list_to_pipe(
        [item["StudyRoad_RowID"] for item in approved_within_threshold]
    )

    decision = _same_corridor_candidate_decision(evaluations)
    if decision["status"] != "candidate_supported":
        final_record["Access_SameCorridorReviewStatus"] = decision["status"]
        final_record["Access_SameCorridorRefusalReason"] = decision["reason"]
        final_record["Access_AssignmentReason"] = decision["reason"]
        final_record["Access_AssignmentRule"] = "reviewed_family_local_distance_refusal_after_exact_route_conflict"
        return

    winner = decision["winner"]
    line = winner["LineGeometry"]
    flow_follows_geometry = _flow_matches_line_direction(line, winner["FlowDirection"])
    if signal_point is None or line is None or flow_follows_geometry is None:
        final_record["Access_SameCorridorReviewStatus"] = "missing_flow_or_projection"
        final_record["Access_SameCorridorRefusalReason"] = "missing_flow_or_projection"
        final_record["Access_AssignmentReason"] = "missing_flow_or_projection"
        final_record["Access_AssignmentRule"] = "reviewed_family_local_distance_refusal_after_exact_route_conflict"
        return

    point_projection_ft = float(line.project(record["geometry"]) * METERS_TO_FEET)
    signal_projection_ft = float(line.project(signal_point) * METERS_TO_FEET)
    final_record["StudyRoad_RowID"] = int(winner["StudyRoad_RowID"])
    final_record["Access_ToRowDistanceFt"] = winner["distance_ft"]
    final_record["Access_ProjectionFt"] = point_projection_ft
    final_record["Access_SignalProjectionFt"] = signal_projection_ft
    final_record["Access_SameCorridorFamilyKey"] = winner["family_key"]
    final_record["Access_SameCorridorLocalDistanceMaxFt"] = winner["local_distance_max_ft"]
    final_record["Access_SameCorridorReviewStatus"] = "recovered"
    final_record["Access_SameCorridorRefusalReason"] = None
    final_record["Access_AssignmentRule"] = ACCESS_SAME_CORRIDOR_RULE
    delta_ft = point_projection_ft - signal_projection_ft
    if abs(delta_ft) <= ACCESS_NEAR_SIGNAL_THRESHOLD_FT:
        final_record["Access_AssignmentStatus"] = "near_signal"
        final_record["Access_AssignmentReason"] = "reviewed_same_corridor_projection_within_65_6ft_of_signal"
        final_record["Access_SignalRelativePosition"] = "near_signal"
        _populate_access_signal_distance_fields(final_record)
        return

    if flow_follows_geometry:
        position = "upstream" if point_projection_ft < signal_projection_ft else "downstream"
    else:
        position = "upstream" if point_projection_ft > signal_projection_ft else "downstream"
    final_record["Access_AssignmentStatus"] = "matched"
    final_record["Access_AssignmentReason"] = "reviewed_same_corridor_unique_local_projection_match"
    final_record["Access_SignalRelativePosition"] = position
    _populate_access_signal_distance_fields(final_record)


def _build_access_assignment_points(
    approach_row_base: pd.DataFrame,
    approach_row_geometry: gpd.GeoDataFrame,
    signal_study_area_base: pd.DataFrame,
    study_area_geometry: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    access: gpd.GeoDataFrame,
    same_corridor_family_table: pd.DataFrame,
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
                "Access_DistanceFromSignalFt",
                "Access_SignalOffsetFt",
                "Access_DownstreamDistanceFt",
                "Access_DistanceBandFamily",
                "Access_DistanceBandStartFt",
                "Access_DistanceBandEndFt",
                "Access_DistanceBandLabel",
                "Access_SignalRelativePosition",
                "Access_AssignmentStatus",
                "Access_AssignmentReason",
                "Access_AssignmentRule",
                "Access_SameCorridorReviewStatus",
                "Access_SameCorridorRefusalReason",
                "Access_SameCorridorFamilyKey",
                "Access_SameCorridorLocalDistanceMaxFt",
                "Access_SameCorridorSecondNearestDistanceFt",
                "Access_SameCorridorApprovedRowsWithinThreshold",
                "SameCorridorSupportedStudyRoadRowIDs",
            ]
        )
        empty_geo = gpd.GeoDataFrame(empty_df.copy(), geometry=gpd.GeoSeries([], crs=access.crs), crs=access.crs)
        return empty_df, empty_geo

    include_families = same_corridor_family_table.loc[same_corridor_family_table["ReviewDecision"].eq("include")].copy()
    exclude_families = same_corridor_family_table.loc[same_corridor_family_table["ReviewDecision"].eq("exclude")].copy()
    include_routes_by_access = {
        access_route: frame.copy()
        for access_route, frame in include_families.groupby("AccessRouteNorm", dropna=False)
    }
    excluded_routes_by_access = {
        access_route: frame.copy()
        for access_route, frame in exclude_families.groupby("AccessRouteNorm", dropna=False)
    }

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
    row_context["Approach_Route_Normalized"] = row_context["ApproachRoad_RTE_NM"].map(_normalize_route_name)
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
                    "Access_DistanceFromSignalFt": None,
                    "Access_SignalOffsetFt": None,
                    "Access_DownstreamDistanceFt": None,
                    "Access_DistanceBandFamily": None,
                    "Access_DistanceBandStartFt": None,
                    "Access_DistanceBandEndFt": None,
                    "Access_DistanceBandLabel": None,
                    "Access_SignalRelativePosition": "unresolved",
                    "Access_AssignmentStatus": "unresolved",
                    "Access_AssignmentReason": "missing_flow_or_projection",
                    "Access_AssignmentRule": "documented_study_area_candidate_rows_required",
                    "Access_SameCorridorReviewStatus": "not_evaluated_missing_candidate_rows",
                    "Access_SameCorridorRefusalReason": None,
                    "Access_SameCorridorFamilyKey": None,
                    "Access_SameCorridorLocalDistanceMaxFt": None,
                    "Access_SameCorridorSecondNearestDistanceFt": None,
                    "Access_SameCorridorApprovedRowsWithinThreshold": 0,
                    "RouteSupportedStudyRoadRowIDs": None,
                    "MeasureSupportedStudyRoadRowIDs": None,
                    "DistancePassedStudyRoadRowIDs": None,
                    "AmbiguousStudyRoadRowIDs": None,
                    "SameCorridorSupportedStudyRoadRowIDs": None,
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
            "Access_DistanceFromSignalFt": None,
            "Access_SignalOffsetFt": None,
            "Access_DownstreamDistanceFt": None,
            "Access_DistanceBandFamily": None,
            "Access_DistanceBandStartFt": None,
            "Access_DistanceBandEndFt": None,
            "Access_DistanceBandLabel": None,
            "Access_SignalRelativePosition": "unresolved",
            "Access_AssignmentStatus": "unresolved",
            "Access_AssignmentReason": "missing_flow_or_projection",
            "Access_AssignmentRule": "route_exact_measure_tolerance_distance_60ft_signal_compare_65_6ft",
            "Access_SameCorridorReviewStatus": "not_evaluated",
            "Access_SameCorridorRefusalReason": None,
            "Access_SameCorridorFamilyKey": None,
            "Access_SameCorridorLocalDistanceMaxFt": None,
            "Access_SameCorridorSecondNearestDistanceFt": None,
            "Access_SameCorridorApprovedRowsWithinThreshold": 0,
            "RouteSupportedStudyRoadRowIDs": _list_to_pipe(route_supported_rows),
            "MeasureSupportedStudyRoadRowIDs": _list_to_pipe(measure_supported_rows),
            "DistancePassedStudyRoadRowIDs": _list_to_pipe(distance_supported_rows),
            "AmbiguousStudyRoadRowIDs": None,
            "SameCorridorSupportedStudyRoadRowIDs": None,
        }

        if not route_supported_eval:
            final_record["Access_AssignmentStatus"] = "route_conflict"
            final_record["Access_AssignmentReason"] = "route_name_not_exact_match"
            final_record["Access_AssignmentRule"] = "exact_route_support_required"
            _apply_reviewed_same_corridor_overlay(
                final_record=final_record,
                record=record,
                candidate_rows=candidate_rows,
                signal_point=signal_point,
                normalized_access_route=normalized_access_route,
                include_routes_by_access=include_routes_by_access,
                excluded_routes_by_access=excluded_routes_by_access,
            )
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
                _populate_access_signal_distance_fields(final_record)

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
    study_area_unassigned_counts = (
        access_points.assign(
            HasUnassignedStatus=~access_points["Access_AssignmentStatus"].isin(["matched", "near_signal"])
        )
        .groupby("StudyAreaID", dropna=False)["HasUnassignedStatus"]
        .sum()
        .to_dict()
    )
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
        study_area_unassigned_count = int(study_area_unassigned_counts.get(study_area_id, 0))

        if total_points_in_study_area == 0:
            status = "no_candidate_points"
            reason = "no_access_points_in_study_area"
        elif ambiguous_count > 0 or unresolved_count > 0:
            status = "partial"
            reason = "contains_ambiguous_or_unresolved_points"
        elif total_assigned == 0 and study_area_unassigned_count > 0:
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


def _route_direction_token(route_name: object) -> str | None:
    normalized = _normalize_route_name(route_name)
    if normalized is None:
        return None
    match = re.search(r"(NB|SB|EB|WB)(?=ALT|\b|$)", normalized)
    return match.group(1) if match else None


def _route_without_direction_token(route_name: object) -> str | None:
    normalized = _normalize_route_name(route_name)
    if normalized is None:
        return None
    return re.sub(r"(NB|SB|EB|WB)(?=ALT|\b|$)", "", normalized)


def _has_opposite_direction_warning(access_route: object, study_route: object) -> bool:
    access_direction = _route_direction_token(access_route)
    study_direction = _route_direction_token(study_route)
    if access_direction is None or study_direction is None:
        return False
    if {access_direction, study_direction} not in ({"NB", "SB"}, {"EB", "WB"}):
        return False
    return _route_without_direction_token(access_route) == _route_without_direction_token(study_route)


def _nearest_row_review_record(
    family_table: pd.DataFrame,
    access_route_norm: object,
    study_route_norm: object,
) -> dict[str, object]:
    exact_pair = family_table.loc[
        family_table["AccessRouteNorm"].eq(access_route_norm)
        & family_table["StudyRouteNorm"].eq(study_route_norm)
    ].copy()
    access_family = family_table.loc[family_table["AccessRouteNorm"].eq(access_route_norm)].copy()
    if not exact_pair.empty:
        row = exact_pair.iloc[0]
        return {
            "HasCurrentReviewedFamily": True,
            "CurrentReviewDecision": row["ReviewDecision"],
            "CurrentRefusalRisk": row["ReviewReason"] if "ReviewReason" in row.index else None,
            "CurrentFamilyKey": row["FamilyKey"],
        }
    if not access_family.empty:
        decisions = _list_to_pipe(access_family["ReviewDecision"].astype(str).drop_duplicates().tolist())
        reasons = _list_to_pipe(access_family["ReviewReason"].astype(str).drop_duplicates().tolist()) if "ReviewReason" in access_family.columns else None
        return {
            "HasCurrentReviewedFamily": False,
            "CurrentReviewDecision": f"access_route_reviewed_elsewhere:{decisions}",
            "CurrentRefusalRisk": reasons,
            "CurrentFamilyKey": _list_to_pipe(access_family["FamilyKey"].astype(str).tolist()),
        }
    return {
        "HasCurrentReviewedFamily": False,
        "CurrentReviewDecision": None,
        "CurrentRefusalRisk": None,
        "CurrentFamilyKey": None,
    }


def _review_bucket_from_route_conflict(row: pd.Series) -> tuple[str, int, str]:
    review_status = row.get("ExistingSameCorridorReviewStatus")
    current_decision = row.get("CurrentReviewDecision")
    conflict_count = int(row.get("ConflictPointCount") or 0)
    distinct_signal_count = int(row.get("DistinctSignalCount") or 0)
    nearest_distance = pd.to_numeric(pd.Series([row.get("NearestDistanceFt")]), errors="coerce").iloc[0]
    median_distance = pd.to_numeric(pd.Series([row.get("MedianDistanceFt")]), errors="coerce").iloc[0]
    within_5_count = int(row.get("Within5FtCount") or 0)
    measure_compatible = bool(row.get("MeasureCompatibleIfRouteIgnored"))
    opposite_warning = bool(row.get("OppositeDirectionWarning"))

    if (
        opposite_warning
        or review_status == "family_excluded"
        or str(current_decision).strip().lower() == "exclude"
    ):
        return (
            "likely_wrong_carriageway_or_parallel_facility",
            5,
            "retain_refusal_wrong_carriageway_or_parallel_risk",
        )
    if review_status == "approved_study_route_not_present":
        return (
            "candidate_direction_variant",
            2,
            "review_family_table_coverage_for_missing_carriageway",
        )
    if (
        conflict_count >= 2
        and (distinct_signal_count >= 2 or within_5_count >= 2)
        and within_5_count >= 2
        and pd.notna(median_distance)
        and float(median_distance) <= 5.0
    ):
        return (
            "candidate_same_corridor_alias",
            1,
            "review_repeated_near_zero_family_for_explicit_include",
        )
    if measure_compatible and pd.notna(nearest_distance) and float(nearest_distance) <= ACCESS_MAX_TO_ROW_DISTANCE_FT:
        return (
            "candidate_measure_supported_but_unreviewed",
            3,
            "review_measure_supported_local_route_conflict",
        )
    if pd.notna(nearest_distance) and float(nearest_distance) <= ACCESS_MAX_TO_ROW_DISTANCE_FT and conflict_count == 1:
        return (
            "likely_cross_street_or_local_access",
            4,
            "inspect_one_off_local_geometry_before_any_promotion",
        )
    return (
        "insufficient_evidence",
        6,
        "retain_unresolved_pending_repeated_or_reviewed_evidence",
    )


def _build_access_route_conflict_diagnostics(
    access_points: pd.DataFrame,
    access_points_geo: gpd.GeoDataFrame,
    approach_row_geometry: gpd.GeoDataFrame,
    same_corridor_family_table: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, gpd.GeoDataFrame]:
    required_columns = [
        "Access_PointID",
        "StudyAreaID",
        "Signal_RowID",
        "Access_Route",
        "NearestStudyRoad_RowID",
        "NearestStudyRoute",
        "NearestStudyRouteCommon",
        "NearestDistanceFt",
        "SignalRouteName",
        "FlowDirection",
        "Access_Measure",
        "NearestRowFromMeasure",
        "NearestRowToMeasure",
        "MeasureCompatibleIfRouteIgnored",
        "ReviewBucket",
        "ReviewPriority",
        "ExistingSameCorridorReviewStatus",
        "ExistingSameCorridorRefusalReason",
        "AccessRouteNorm",
        "StudyRouteNorm",
        "SecondNearestStudyRoad_RowID",
        "SecondNearestDistanceFt",
        "NearestDistanceGapFt",
        "OppositeDirectionWarning",
        "HasCurrentReviewedFamily",
        "CurrentReviewDecision",
        "CurrentRefusalRisk",
        "CandidatePromotionRecommendation",
        "NearestStudyRoadGeometry",
    ]

    route_conflicts = access_points_geo.loc[
        access_points_geo["Access_AssignmentStatus"].eq("route_conflict")
    ].copy()
    if route_conflicts.empty:
        empty = pd.DataFrame(columns=required_columns)
        empty_geo = gpd.GeoDataFrame(empty.copy(), geometry=gpd.GeoSeries([], crs=access_points_geo.crs), crs=access_points_geo.crs)
        family_columns = [
            "AccessRouteNorm",
            "StudyRouteNorm",
            "ConflictPointCount",
            "DistinctSignalCount",
            "MinDistanceFt",
            "MedianDistanceFt",
            "MaxDistanceFt",
            "NearZeroCount",
            "Within5FtCount",
            "Within15FtCount",
            "Within30FtCount",
            "Within60FtCount",
            "HasCurrentReviewedFamily",
            "CurrentReviewDecision",
            "CurrentRefusalRisk",
            "DominantReviewBucket",
            "MinReviewPriority",
        ]
        return empty.drop(columns=["NearestStudyRoadGeometry"]), pd.DataFrame(columns=family_columns), empty_geo

    row_context = approach_row_geometry[
        [
            "StudyAreaID",
            "StudyRoad_RowID",
            "SignalRouteName",
            "ApproachRoad_RTE_NM",
            "ApproachRoad_RTE_COMMON",
            "ApproachRoad_FROM_MEASURE",
            "ApproachRoad_TO_MEASURE",
            "FlowDirection",
            "geometry",
        ]
    ].copy()
    row_context["StudyRouteNorm"] = row_context["ApproachRoad_RTE_NM"].map(_normalize_route_name)
    rows_by_study_area = {
        str(study_area_id): frame.copy()
        for study_area_id, frame in row_context.groupby("StudyAreaID", dropna=False)
    }

    records: list[dict[str, object]] = []
    geometries: list[object] = []
    for _, point in route_conflicts.iterrows():
        study_area_id = str(point["StudyAreaID"])
        candidate_rows = rows_by_study_area.get(study_area_id, pd.DataFrame())
        access_route_norm = _normalize_route_name(point["Access_Route"])
        access_measure = pd.to_numeric(pd.Series([point["Access_Measure"]]), errors="coerce").iloc[0]
        nearest_candidates: list[dict[str, object]] = []
        for _, row in candidate_rows.iterrows():
            line = _normalize_line_geometry(row["geometry"])
            distance_ft = float(point.geometry.distance(line) * METERS_TO_FEET) if line is not None else None
            from_measure, to_measure = _ordered_measure_range(
                row["ApproachRoad_FROM_MEASURE"],
                row["ApproachRoad_TO_MEASURE"],
            )
            measure_compatible = (
                from_measure is not None
                and to_measure is not None
                and not pd.isna(access_measure)
                and float(access_measure) >= from_measure - ACCESS_MEASURE_TOLERANCE_MI
                and float(access_measure) <= to_measure + ACCESS_MEASURE_TOLERANCE_MI
            )
            nearest_candidates.append(
                {
                    "StudyRoad_RowID": int(row["StudyRoad_RowID"]),
                    "SignalRouteName": row["SignalRouteName"],
                    "StudyRouteNorm": row["StudyRouteNorm"],
                    "ApproachRoad_RTE_NM": row["ApproachRoad_RTE_NM"],
                    "ApproachRoad_RTE_COMMON": row["ApproachRoad_RTE_COMMON"],
                    "ApproachRoad_FROM_MEASURE": row["ApproachRoad_FROM_MEASURE"],
                    "ApproachRoad_TO_MEASURE": row["ApproachRoad_TO_MEASURE"],
                    "FlowDirection": row["FlowDirection"],
                    "LineGeometry": line,
                    "DistanceFt": distance_ft,
                    "MeasureCompatibleIfRouteIgnored": measure_compatible,
                }
            )

        nearest_candidates = sorted(
            [item for item in nearest_candidates if item["DistanceFt"] is not None],
            key=lambda item: (float(item["DistanceFt"]), int(item["StudyRoad_RowID"])),
        )
        nearest = nearest_candidates[0] if nearest_candidates else {}
        second_nearest = nearest_candidates[1] if len(nearest_candidates) > 1 else {}
        nearest_distance = nearest.get("DistanceFt")
        second_distance = second_nearest.get("DistanceFt")
        review = _nearest_row_review_record(
            same_corridor_family_table,
            access_route_norm,
            nearest.get("StudyRouteNorm"),
        )
        record = {
            "Access_PointID": point["Access_PointID"],
            "StudyAreaID": study_area_id,
            "Signal_RowID": _int_or_na(point["Signal_RowID"]),
            "Access_Route": point["Access_Route"],
            "NearestStudyRoad_RowID": nearest.get("StudyRoad_RowID"),
            "NearestStudyRoute": nearest.get("ApproachRoad_RTE_NM"),
            "NearestStudyRouteCommon": nearest.get("ApproachRoad_RTE_COMMON"),
            "NearestDistanceFt": nearest_distance,
            "SignalRouteName": nearest.get("SignalRouteName"),
            "FlowDirection": nearest.get("FlowDirection"),
            "Access_Measure": point["Access_Measure"],
            "NearestRowFromMeasure": nearest.get("ApproachRoad_FROM_MEASURE"),
            "NearestRowToMeasure": nearest.get("ApproachRoad_TO_MEASURE"),
            "MeasureCompatibleIfRouteIgnored": bool(nearest.get("MeasureCompatibleIfRouteIgnored", False)),
            "ReviewBucket": None,
            "ReviewPriority": None,
            "ExistingSameCorridorReviewStatus": point.get("Access_SameCorridorReviewStatus"),
            "ExistingSameCorridorRefusalReason": point.get("Access_SameCorridorRefusalReason"),
            "AccessRouteNorm": access_route_norm,
            "StudyRouteNorm": nearest.get("StudyRouteNorm"),
            "SecondNearestStudyRoad_RowID": second_nearest.get("StudyRoad_RowID"),
            "SecondNearestDistanceFt": second_distance,
            "NearestDistanceGapFt": (
                float(second_distance) - float(nearest_distance)
                if second_distance is not None and nearest_distance is not None
                else None
            ),
            "OppositeDirectionWarning": _has_opposite_direction_warning(access_route_norm, nearest.get("StudyRouteNorm")),
            "HasCurrentReviewedFamily": review["HasCurrentReviewedFamily"],
            "CurrentReviewDecision": review["CurrentReviewDecision"],
            "CurrentRefusalRisk": review["CurrentRefusalRisk"],
            "CurrentFamilyKey": review["CurrentFamilyKey"],
            "CandidatePromotionRecommendation": None,
            "NearestStudyRoadGeometry": nearest.get("LineGeometry"),
        }
        records.append(record)
        geometries.append(point.geometry)

    diagnostics = pd.DataFrame(records)
    family_stats = (
        diagnostics.groupby(["AccessRouteNorm", "StudyRouteNorm"], dropna=False)
        .agg(
            ConflictPointCount=("Access_PointID", "size"),
            DistinctSignalCount=("StudyAreaID", "nunique"),
            MinDistanceFt=("NearestDistanceFt", "min"),
            MedianDistanceFt=("NearestDistanceFt", "median"),
            MaxDistanceFt=("NearestDistanceFt", "max"),
            NearZeroCount=("NearestDistanceFt", lambda values: int(pd.to_numeric(values, errors="coerce").le(0.5).sum())),
            Within5FtCount=("NearestDistanceFt", lambda values: int(pd.to_numeric(values, errors="coerce").le(5.0).sum())),
            Within15FtCount=("NearestDistanceFt", lambda values: int(pd.to_numeric(values, errors="coerce").le(15.0).sum())),
            Within30FtCount=("NearestDistanceFt", lambda values: int(pd.to_numeric(values, errors="coerce").le(30.0).sum())),
            Within60FtCount=("NearestDistanceFt", lambda values: int(pd.to_numeric(values, errors="coerce").le(60.0).sum())),
            HasCurrentReviewedFamily=("HasCurrentReviewedFamily", "max"),
            CurrentReviewDecision=("CurrentReviewDecision", lambda values: _list_to_pipe(pd.Series(values).dropna().drop_duplicates().tolist())),
            CurrentRefusalRisk=("CurrentRefusalRisk", lambda values: _list_to_pipe(pd.Series(values).dropna().drop_duplicates().tolist())),
        )
        .reset_index()
    )
    diagnostics = diagnostics.merge(
        family_stats[
            [
                "AccessRouteNorm",
                "StudyRouteNorm",
                "ConflictPointCount",
                "DistinctSignalCount",
                "MedianDistanceFt",
                "Within5FtCount",
            ]
        ],
        on=["AccessRouteNorm", "StudyRouteNorm"],
        how="left",
        validate="many_to_one",
    )
    bucket_results = diagnostics.apply(_review_bucket_from_route_conflict, axis=1)
    diagnostics["ReviewBucket"] = bucket_results.map(lambda value: value[0])
    diagnostics["ReviewPriority"] = bucket_results.map(lambda value: value[1])
    diagnostics["CandidatePromotionRecommendation"] = bucket_results.map(lambda value: value[2])
    family_bucket = (
        diagnostics.sort_values(["AccessRouteNorm", "StudyRouteNorm", "ReviewPriority"])
        .groupby(["AccessRouteNorm", "StudyRouteNorm"], dropna=False)
        .agg(
            DominantReviewBucket=("ReviewBucket", "first"),
            MinReviewPriority=("ReviewPriority", "min"),
        )
        .reset_index()
    )
    family_summary = family_stats.merge(
        family_bucket,
        on=["AccessRouteNorm", "StudyRouteNorm"],
        how="left",
        validate="one_to_one",
    ).sort_values(
        ["MinReviewPriority", "Within5FtCount", "ConflictPointCount", "MedianDistanceFt"],
        ascending=[True, False, False, True],
    )

    output_columns = required_columns + [
        "CurrentFamilyKey",
        "ConflictPointCount",
        "DistinctSignalCount",
        "MedianDistanceFt",
        "Within5FtCount",
    ]
    diagnostics_geo = gpd.GeoDataFrame(
        diagnostics[output_columns].copy(),
        geometry=gpd.GeoSeries(geometries, crs=access_points_geo.crs),
        crs=access_points_geo.crs,
    )
    diagnostics_table = diagnostics_geo.drop(columns=["geometry", "NearestStudyRoadGeometry"])
    family_summary["HasCurrentReviewedFamily"] = family_summary["HasCurrentReviewedFamily"].astype(bool)
    return diagnostics_table, family_summary.reset_index(drop=True), diagnostics_geo


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
    return "unresolved", dominant_share, "unresolved", "fewer_than_3_classified_crashes"


def _fill_missing_ru_context(frame: pd.DataFrame) -> pd.DataFrame:
    completed = frame.copy()
    count_columns = [
        "RU_CrashContext_RuralCount",
        "RU_CrashContext_UrbanCount",
        "RU_CrashContext_UnresolvedCount",
    ]
    for column in count_columns:
        completed[column] = completed[column].fillna(0).astype(int)
    completed["RU_CrashContext_DominantClass"] = completed["RU_CrashContext_DominantClass"].fillna("unresolved")
    completed["RU_ContextStatus"] = completed["RU_ContextStatus"].fillna("no_classified_crash_context")
    completed["RU_ContextReason"] = completed["RU_ContextReason"].fillna("no_attached_classified_crashes")
    return completed


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


def _append_crash_distance_fields(crash_context: pd.DataFrame) -> pd.DataFrame:
    enriched = crash_context.copy()
    signal_projection_ft = _to_numeric(enriched["SignalProjectionMeters"]) * METERS_TO_FEET
    crash_projection_ft = _to_numeric(enriched["CrashProjectionMeters"]) * METERS_TO_FEET
    distance_ft = (crash_projection_ft - signal_projection_ft).abs()

    enriched["Crash_DistanceFromSignalFt"] = pd.NA
    enriched["Crash_SignalOffsetFt"] = pd.NA
    enriched["Crash_DownstreamDistanceFt"] = pd.NA
    enriched["Crash_DistanceBandFamily"] = pd.NA
    enriched["Crash_DistanceBandStartFt"] = pd.NA
    enriched["Crash_DistanceBandEndFt"] = pd.NA
    enriched["Crash_DistanceBandLabel"] = pd.NA

    downstream_mask = (
        enriched["SignalRelativeClassification"].eq("downstream")
        & signal_projection_ft.notna()
        & crash_projection_ft.notna()
    )
    upstream_mask = (
        enriched["SignalRelativeClassification"].eq("upstream")
        & signal_projection_ft.notna()
        & crash_projection_ft.notna()
    )

    enriched.loc[downstream_mask | upstream_mask, "Crash_DistanceFromSignalFt"] = distance_ft.loc[downstream_mask | upstream_mask]
    enriched.loc[downstream_mask, "Crash_SignalOffsetFt"] = distance_ft.loc[downstream_mask]
    enriched.loc[upstream_mask, "Crash_SignalOffsetFt"] = -distance_ft.loc[upstream_mask]
    enriched.loc[downstream_mask, "Crash_DownstreamDistanceFt"] = distance_ft.loc[downstream_mask]

    downstream_distances = enriched.loc[downstream_mask, "Crash_DownstreamDistanceFt"]
    if not downstream_distances.empty:
        band_fields = downstream_distances.map(_distance_band_fields)
        enriched.loc[downstream_mask, "Crash_DistanceBandFamily"] = band_fields.map(lambda value: value["DistanceBandFamily"])
        enriched.loc[downstream_mask, "Crash_DistanceBandStartFt"] = band_fields.map(lambda value: value["DistanceBandStartFt"])
        enriched.loc[downstream_mask, "Crash_DistanceBandEndFt"] = band_fields.map(lambda value: value["DistanceBandEndFt"])
        enriched.loc[downstream_mask, "Crash_DistanceBandLabel"] = band_fields.map(lambda value: value["DistanceBandLabel"])

    return enriched


def _build_signal_downstream_distance_band_summary(
    signal_base: pd.DataFrame,
    access_points: pd.DataFrame,
    crash_context_enriched: pd.DataFrame,
) -> pd.DataFrame:
    band_spine = _study_area_band_records(signal_base)
    if band_spine.empty:
        return pd.DataFrame(
            columns=[
                "StudyAreaID",
                "Signal_RowID",
                "REG_SIGNAL_ID",
                "SIGNAL_NO",
                "SignalLabel",
                "SignalRouteName",
                "StudyAreaApproachLengthFt",
                "DistanceBandFamily",
                "DistanceBandStartFt",
                "DistanceBandEndFt",
                "DistanceBandLabel",
                "DownstreamAccessCount",
                "DownstreamCrashCount",
            ]
        )

    access_counts = (
        access_points.loc[
            access_points["Access_SignalRelativePosition"].eq("downstream")
            & access_points["Access_DistanceBandLabel"].notna(),
            ["StudyAreaID", "Access_DistanceBandFamily", "Access_DistanceBandStartFt", "Access_DistanceBandEndFt", "Access_DistanceBandLabel", "Access_PointID"],
        ]
        .groupby(
            ["StudyAreaID", "Access_DistanceBandFamily", "Access_DistanceBandStartFt", "Access_DistanceBandEndFt", "Access_DistanceBandLabel"],
            dropna=False,
        )["Access_PointID"]
        .nunique()
        .reset_index(name="DownstreamAccessCount")
        .rename(
            columns={
                "Access_DistanceBandFamily": "DistanceBandFamily",
                "Access_DistanceBandStartFt": "DistanceBandStartFt",
                "Access_DistanceBandEndFt": "DistanceBandEndFt",
                "Access_DistanceBandLabel": "DistanceBandLabel",
            }
        )
    )
    crash_counts = (
        crash_context_enriched.loc[
            crash_context_enriched["SignalRelativeClassification"].eq("downstream")
            & crash_context_enriched["Crash_DistanceBandLabel"].notna(),
            ["StudyAreaID", "Crash_DistanceBandFamily", "Crash_DistanceBandStartFt", "Crash_DistanceBandEndFt", "Crash_DistanceBandLabel", "Crash_RowID"],
        ]
        .groupby(
            ["StudyAreaID", "Crash_DistanceBandFamily", "Crash_DistanceBandStartFt", "Crash_DistanceBandEndFt", "Crash_DistanceBandLabel"],
            dropna=False,
        )["Crash_RowID"]
        .nunique()
        .reset_index(name="DownstreamCrashCount")
        .rename(
            columns={
                "Crash_DistanceBandFamily": "DistanceBandFamily",
                "Crash_DistanceBandStartFt": "DistanceBandStartFt",
                "Crash_DistanceBandEndFt": "DistanceBandEndFt",
                "Crash_DistanceBandLabel": "DistanceBandLabel",
            }
        )
    )

    summary = band_spine.merge(
        access_counts,
        on=["StudyAreaID", "DistanceBandFamily", "DistanceBandStartFt", "DistanceBandEndFt", "DistanceBandLabel"],
        how="left",
        validate="one_to_one",
    ).merge(
        crash_counts,
        on=["StudyAreaID", "DistanceBandFamily", "DistanceBandStartFt", "DistanceBandEndFt", "DistanceBandLabel"],
        how="left",
        validate="one_to_one",
    )
    summary["DownstreamAccessCount"] = summary["DownstreamAccessCount"].fillna(0).astype(int)
    summary["DownstreamCrashCount"] = summary["DownstreamCrashCount"].fillna(0).astype(int)
    return summary.sort_values(["StudyAreaID", "DistanceBandStartFt"]).reset_index(drop=True)


def _build_classified_crash_context_enriched(
    crash_context: pd.DataFrame,
    approach_enriched: pd.DataFrame,
    signal_enriched: pd.DataFrame,
) -> pd.DataFrame:
    crash_context = _append_crash_distance_fields(crash_context)
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
        "AADT_RouteSupportEvidence",
        "AADT_MeasureOverlapMiles",
        "AADT_LocalGeometryDistanceFt",
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
    aadt_diagnostics: dict[str, object],
    approach_enriched: pd.DataFrame,
    access_points: pd.DataFrame,
    access_route_conflict_diagnostics: pd.DataFrame,
    access_route_conflict_family_summary: pd.DataFrame,
    crash_context_enriched: pd.DataFrame,
    signal_enriched: pd.DataFrame,
    signal_downstream_distance_bands: pd.DataFrame,
) -> dict[str, object]:
    selected_aadt = approach_enriched.loc[approach_enriched["AADT_Status"].eq("matched")].copy()
    matched_access = access_points.loc[access_points["Access_AssignmentStatus"].isin(["matched", "near_signal"])].copy()
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
    aadt_measure_overlap_distribution = {
        "min": float(selected_aadt["AADT_MeasureOverlapMiles"].min()) if not selected_aadt.empty else None,
        "median": float(selected_aadt["AADT_MeasureOverlapMiles"].median()) if not selected_aadt.empty else None,
        "max": float(selected_aadt["AADT_MeasureOverlapMiles"].max()) if not selected_aadt.empty else None,
    }
    aadt_local_distance_distribution = {
        "min": float(selected_aadt["AADT_LocalGeometryDistanceFt"].min()) if not selected_aadt.empty else None,
        "median": float(selected_aadt["AADT_LocalGeometryDistanceFt"].median()) if not selected_aadt.empty else None,
        "max": float(selected_aadt["AADT_LocalGeometryDistanceFt"].max()) if not selected_aadt.empty else None,
    }
    ru_signal_dominant_distribution = signal_enriched["RU_CrashContext_DominantClass"].fillna("<null>").value_counts(dropna=False).to_dict()
    ru_row_dominant_distribution = approach_enriched["RU_CrashContext_DominantClass"].fillna("<null>").value_counts(dropna=False).to_dict()
    access_route_supported_candidate_point_count = int(access_points["RouteSupportedStudyRoadRowIDs"].fillna("").astype(str).ne("").sum())
    access_measure_supported_candidate_point_count = int(access_points["MeasureSupportedStudyRoadRowIDs"].fillna("").astype(str).ne("").sum())
    access_distance_supported_candidate_point_count = int(access_points["DistancePassedStudyRoadRowIDs"].fillna("").astype(str).ne("").sum())
    route_conflict_nearest_distance = (
        pd.to_numeric(access_route_conflict_diagnostics["NearestDistanceFt"], errors="coerce")
        if not access_route_conflict_diagnostics.empty
        else pd.Series(dtype="float64")
    )

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
            "measure_overlap_distribution_selected": aadt_measure_overlap_distribution,
            "local_geometry_distance_distribution_selected": aadt_local_distance_distribution,
            "study_areas_with_selected_aadt": int(signal_enriched["AADT_MatchedApproachRowCount"].gt(0).sum()),
            "candidate_generation_diagnostics": aadt_diagnostics,
        },
        "access": {
            "candidate_access_points_in_study_areas": int(len(access_points)),
            "route_supported_candidate_point_count": access_route_supported_candidate_point_count,
            "measure_supported_candidate_point_count": access_measure_supported_candidate_point_count,
            "distance_supported_candidate_point_count": access_distance_supported_candidate_point_count,
            "assignment_status_counts": access_points["Access_AssignmentStatus"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "assignment_reason_counts": access_points["Access_AssignmentReason"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "signal_relative_position_counts": access_points["Access_SignalRelativePosition"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "approach_row_status_counts": approach_enriched["Access_Status"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "signal_status_counts": signal_enriched["Access_Status"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "distance_distribution_ft": {
                "min": float(access_points["Access_ToRowDistanceFt"].dropna().min()) if access_points["Access_ToRowDistanceFt"].dropna().any() else None,
                "median": float(access_points["Access_ToRowDistanceFt"].dropna().median()) if access_points["Access_ToRowDistanceFt"].dropna().any() else None,
                "max": float(access_points["Access_ToRowDistanceFt"].dropna().max()) if access_points["Access_ToRowDistanceFt"].dropna().any() else None,
            },
            "matched_distance_distribution_ft": {
                "min": float(matched_access["Access_ToRowDistanceFt"].min()) if not matched_access.empty else None,
                "median": float(matched_access["Access_ToRowDistanceFt"].median()) if not matched_access.empty else None,
                "max": float(matched_access["Access_ToRowDistanceFt"].max()) if not matched_access.empty else None,
            },
            "near_signal_count": int(access_points["Access_AssignmentStatus"].eq("near_signal").sum()),
            "unresolved_point_count": int(access_points["Access_AssignmentStatus"].eq("unresolved").sum()),
            "approach_rows_with_nonzero_access_density": int(approach_enriched["Access_Density_Per1000Ft"].fillna(0).gt(0).sum()),
            "route_conflict_diagnostic_row_count": int(len(access_route_conflict_diagnostics)),
            "route_conflict_family_count": int(len(access_route_conflict_family_summary)),
            "route_conflict_review_status_counts": (
                access_route_conflict_diagnostics["ExistingSameCorridorReviewStatus"].fillna("<null>").value_counts(dropna=False).to_dict()
                if not access_route_conflict_diagnostics.empty
                else {}
            ),
            "route_conflict_review_bucket_counts": (
                access_route_conflict_diagnostics["ReviewBucket"].fillna("<null>").value_counts(dropna=False).to_dict()
                if not access_route_conflict_diagnostics.empty
                else {}
            ),
            "route_conflicts_within_5ft_nearest_row": int(route_conflict_nearest_distance.le(5.0).sum()),
            "route_conflicts_within_60ft_nearest_row": int(route_conflict_nearest_distance.le(ACCESS_MAX_TO_ROW_DISTANCE_FT).sum()),
            "route_conflict_high_priority_family_count": (
                int(access_route_conflict_family_summary["MinReviewPriority"].le(2).sum())
                if not access_route_conflict_family_summary.empty
                else 0
            ),
        },
        "downstream_distance_bands": {
            "band_family": DISTANCE_BAND_FAMILY,
            "signal_band_row_count": int(len(signal_downstream_distance_bands)),
            "signals_with_band_rows": int(signal_downstream_distance_bands["StudyAreaID"].nunique()) if not signal_downstream_distance_bands.empty else 0,
            "downstream_access_points_with_bands": int(access_points["Access_DistanceBandLabel"].notna().sum()),
            "downstream_crashes_with_bands": int(crash_context_enriched["Crash_DistanceBandLabel"].notna().sum()),
            "bands_with_downstream_access": int(signal_downstream_distance_bands["DownstreamAccessCount"].gt(0).sum()) if not signal_downstream_distance_bands.empty else 0,
            "bands_with_downstream_crashes": int(signal_downstream_distance_bands["DownstreamCrashCount"].gt(0).sum()) if not signal_downstream_distance_bands.empty else 0,
            "max_downstream_access_distance_ft": float(access_points["Access_DownstreamDistanceFt"].dropna().max()) if access_points["Access_DownstreamDistanceFt"].notna().any() else None,
            "max_downstream_crash_distance_ft": float(crash_context_enriched["Crash_DownstreamDistanceFt"].dropna().max()) if crash_context_enriched["Crash_DownstreamDistanceFt"].notna().any() else None,
        },
        "rural_urban": {
            "crash_area_type_completeness_source": round(inputs.crash_area_type["AREA_TYPE"].notna().mean(), 4),
            "crash_area_type_completeness_enriched": round(crash_context_enriched["Crash_AreaType"].notna().mean(), 4),
            "signal_status_counts": signal_enriched["RU_ContextStatus"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "signal_reason_counts": signal_enriched["RU_ContextReason"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "signal_dominant_class_distribution": ru_signal_dominant_distribution,
            "approach_row_status_counts": approach_enriched["RU_ContextStatus"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "approach_row_reason_counts": approach_enriched["RU_ContextReason"].fillna("<null>").value_counts(dropna=False).to_dict(),
            "approach_row_dominant_class_distribution": ru_row_dominant_distribution,
            "approach_rows_without_classified_crash_context": int(approach_enriched["RU_ContextStatus"].eq("no_classified_crash_context").sum()),
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
        "- AADT selection: exact route support, positive measure overlap, local geometry distance `<= 3.0` feet, positive AADT, latest non-null year, unique best candidate",
        "- access assignment: exact route support, measure tolerance `0.005` miles, row distance `<= 60.0` feet, near-signal threshold `<= 65.6` feet",
        "- reviewed same-corridor access overlay: after exact-route `route_conflict`, recover only `ReviewDecision = include` families with one approved route row within the reviewed local threshold and no nearer/tied non-approved row",
        "- route-conflict diagnostics: advisory review buckets and family summaries only; these outputs do not change production access assignment",
        f"- downstream distance outputs: descriptive fixed `{int(DISTANCE_BAND_WIDTH_FT)}`-foot bins from the signal within the current approach-shaped study area only; not a downstream boundary rule",
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
            "- no fuzzy access route matching or unreviewed same-corridor aliases",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_validation_summary_markdown(validation: dict[str, object]) -> str:
    source_counts = validation["source_row_counts"]
    field_validation = validation["field_validation"]
    aadt = validation["aadt"]
    access = validation["access"]
    downstream_distance_bands = validation["downstream_distance_bands"]
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
            f"- route-supported candidate rows: `{aadt_diagnostics['route_supported_candidate_row_count']}`",
            f"- positive-measure-overlap candidate rows: `{aadt_diagnostics['measure_supported_candidate_row_count']}`",
            f"- local-support candidate rows (<= {aadt_diagnostics['local_distance_threshold_ft']} ft): `{aadt_diagnostics['local_support_candidate_row_count']}`",
            f"- AADT selected year distribution: `{json.dumps(aadt['year_distribution_selected'], sort_keys=True)}`",
            f"- AADT selected quality distribution: `{json.dumps(aadt['quality_distribution_selected'], sort_keys=True)}`",
            f"- AADT selected measure-overlap distribution: `{json.dumps(aadt['measure_overlap_distribution_selected'], sort_keys=True)}`",
            f"- AADT selected local-distance distribution: `{json.dumps(aadt['local_geometry_distance_distribution_selected'], sort_keys=True)}`",
            f"- AADT candidate-generation diagnostics: `{json.dumps(aadt_diagnostics, sort_keys=True)}`",
            "",
            "## Access",
            f"- candidate access points in study areas: `{access['candidate_access_points_in_study_areas']}`",
            f"- route-supported candidate points: `{access['route_supported_candidate_point_count']}`",
            f"- measure-supported candidate points: `{access['measure_supported_candidate_point_count']}`",
            f"- distance-supported candidate points (<= 60 ft): `{access['distance_supported_candidate_point_count']}`",
            f"- access assignment status counts: `{json.dumps(access['assignment_status_counts'], sort_keys=True)}`",
            f"- access assignment reason counts: `{json.dumps(access['assignment_reason_counts'], sort_keys=True)}`",
            f"- access signal-relative position counts: `{json.dumps(access['signal_relative_position_counts'], sort_keys=True)}`",
            f"- approach-row access status counts: `{json.dumps(access['approach_row_status_counts'], sort_keys=True)}`",
            f"- signal access status counts: `{json.dumps(access['signal_status_counts'], sort_keys=True)}`",
            f"- access distance distribution (ft): `{json.dumps(access['distance_distribution_ft'], sort_keys=True)}`",
            f"- matched/near-signal distance distribution (ft): `{json.dumps(access['matched_distance_distribution_ft'], sort_keys=True)}`",
            f"- near-signal access point count: `{access['near_signal_count']}`",
            f"- unresolved access point count: `{access['unresolved_point_count']}`",
            f"- approach rows with nonzero access density: `{access['approach_rows_with_nonzero_access_density']}`",
            f"- route-conflict diagnostic rows: `{access['route_conflict_diagnostic_row_count']}`",
            f"- route-conflict family rows: `{access['route_conflict_family_count']}`",
            f"- route-conflict reviewed-family status counts: `{json.dumps(access['route_conflict_review_status_counts'], sort_keys=True)}`",
            f"- route-conflict review-bucket counts: `{json.dumps(access['route_conflict_review_bucket_counts'], sort_keys=True)}`",
            f"- route conflicts within 5 ft of nearest study row: `{access['route_conflicts_within_5ft_nearest_row']}`",
            f"- route conflicts within 60 ft of nearest study row: `{access['route_conflicts_within_60ft_nearest_row']}`",
            f"- high-priority route-conflict family count: `{access['route_conflict_high_priority_family_count']}`",
            "",
            "## Downstream Distance Bands",
            f"- band family: `{downstream_distance_bands['band_family']}`",
            f"- signal-band rows: `{downstream_distance_bands['signal_band_row_count']}`",
            f"- signals with band rows: `{downstream_distance_bands['signals_with_band_rows']}`",
            f"- downstream access points with band assignments: `{downstream_distance_bands['downstream_access_points_with_bands']}`",
            f"- downstream crashes with band assignments: `{downstream_distance_bands['downstream_crashes_with_bands']}`",
            f"- bands with downstream access: `{downstream_distance_bands['bands_with_downstream_access']}`",
            f"- bands with downstream crashes: `{downstream_distance_bands['bands_with_downstream_crashes']}`",
            f"- max downstream access distance (ft): `{downstream_distance_bands['max_downstream_access_distance_ft']}`",
            f"- max downstream crash distance (ft): `{downstream_distance_bands['max_downstream_crash_distance_ft']}`",
            "",
            "## Rural/Urban",
            f"- crash `AREA_TYPE` completeness in normalized source: `{rural_urban['crash_area_type_completeness_source']}`",
            f"- crash `AREA_TYPE` completeness in enriched classified-crash output: `{rural_urban['crash_area_type_completeness_enriched']}`",
            f"- signal RU status counts: `{json.dumps(rural_urban['signal_status_counts'], sort_keys=True)}`",
            f"- signal RU reason counts: `{json.dumps(rural_urban['signal_reason_counts'], sort_keys=True)}`",
            f"- dominant-class distribution by signal: `{json.dumps(rural_urban['signal_dominant_class_distribution'], sort_keys=True)}`",
            f"- approach-row RU status counts: `{json.dumps(rural_urban['approach_row_status_counts'], sort_keys=True)}`",
            f"- approach-row RU reason counts: `{json.dumps(rural_urban['approach_row_reason_counts'], sort_keys=True)}`",
            f"- dominant-class distribution by approach row: `{json.dumps(rural_urban['approach_row_dominant_class_distribution'], sort_keys=True)}`",
            f"- approach rows without classified crash context: `{rural_urban['approach_rows_without_classified_crash_context']}`",
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
            "- `tables/history/`, `review/history/`, `review/geojson/history/`, and `runs/history/` hold timestamped copies of each successful run.",
            "- Active downstream consumers should prefer the stable `current/` paths.",
            "- If a `current/` artifact cannot be replaced because it is locked, the timestamped `history/` copy is the retained run artifact until `current/` is manually cleared and rerun.",
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
    parser.add_argument(
        "--same-corridor-family-table",
        default=None,
        help="Override the reviewed same-corridor access family table.",
    )
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

    aadt_candidates, aadt_row_selection, aadt_diagnostics = _build_aadt_candidates(approach_row_base, approach_row_geometry, inputs.aadt)
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
        inputs.same_corridor_family_table,
    )
    access_route_conflict_diagnostics, access_route_conflict_family_summary, access_route_conflict_geo = (
        _build_access_route_conflict_diagnostics(
            access_points,
            access_points_geo,
            approach_row_geometry,
            inputs.same_corridor_family_table,
        )
    )
    access_row_agg = _aggregate_access_to_rows(approach_with_aadt, access_points)
    access_signal_agg = _aggregate_access_to_signals(signal_base, approach_with_aadt, access_points)

    crash_context, ru_row, ru_signal = _build_rural_urban_outputs(inputs.crash_classifications, inputs.crash_area_type)

    approach_enriched = (
        approach_with_aadt.merge(access_row_agg, on=["StudyAreaID", "StudyRoad_RowID"], how="left", validate="one_to_one")
        .merge(ru_row, on=["StudyAreaID", "StudyRoad_RowID"], how="left", validate="one_to_one")
    )
    approach_enriched = _fill_missing_ru_context(approach_enriched)
    signal_enriched = (
        signal_base.merge(signal_aadt, on="StudyAreaID", how="left", validate="one_to_one")
        .merge(access_signal_agg, on="StudyAreaID", how="left", validate="one_to_one")
        .merge(ru_signal, on="StudyAreaID", how="left", validate="one_to_one")
    )
    signal_enriched = _fill_missing_ru_context(signal_enriched)
    crash_context_enriched = _build_classified_crash_context_enriched(crash_context, approach_enriched, signal_enriched)
    signal_downstream_distance_bands = _build_signal_downstream_distance_band_summary(
        signal_base,
        access_points,
        crash_context_enriched,
    )

    validation = _build_validation_metrics(
        inputs,
        approach_row_base,
        signal_base,
        aadt_candidates,
        aadt_diagnostics,
        approach_enriched,
        access_points,
        access_route_conflict_diagnostics,
        access_route_conflict_family_summary,
        crash_context_enriched,
        signal_enriched,
        signal_downstream_distance_bands,
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
        "access_route_conflict_diagnostics": str(
            _write_csv_frame(
                access_route_conflict_diagnostics,
                tables_current_dir / "access_route_conflict_diagnostics.csv",
                history_dir=tables_history_dir,
            )
        ),
        "access_route_conflict_family_summary": str(
            _write_csv_frame(
                access_route_conflict_family_summary,
                tables_current_dir / "access_route_conflict_family_summary.csv",
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
        "signal_downstream_distance_band_summary": str(
            _write_csv_frame(
                signal_downstream_distance_bands,
                tables_current_dir / "signal_downstream_distance_band_summary.csv",
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
        "access_route_conflict_candidates_geojson": str(
            _write_geojson_frame(
                gpd.GeoDataFrame(access_route_conflict_geo, geometry="geometry", crs=inputs.access.crs),
                review_geojson_current_dir / "access_route_conflict_candidates.geojson",
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
            "AADT matching uses exact route support plus positive measure overlap and local geometry distance <= 3.0 feet; it does not fall back to proximity-only or measure-only support.",
            "When all rule-supported positive AADT candidates have null years, selection falls through to route support, measure overlap, and local distance without inventing a year ranking.",
            "Sparse same-class rural/urban crash context below the minimum dominant-count threshold is treated as unresolved.",
            "Route-conflict review buckets are diagnostic only and do not auto-recover unreviewed access-route mismatches.",
            f"Downstream distance bands are descriptive {int(DISTANCE_BAND_WIDTH_FT)}-foot bins within the current approach-shaped study area, not a limiting-value or next-signal boundary.",
        ],
    }
    run_summary_path = runs_current_dir / "context_enrichment_run_summary.json"
    output_files["context_enrichment_run_summary"] = str(run_summary_path)
    readme_path = _write_text_file(
        _build_output_layout_readme(output_files, output_dir),
        output_dir / "README.md",
    )
    output_files["readme"] = str(readme_path)
    run_summary["output_files"] = output_files
    _write_json_object(
        run_summary,
        runs_current_dir / "context_enrichment_run_summary.json",
        history_dir=runs_history_dir,
    )
    print(json.dumps(run_summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_context_enrichment(argv)


if __name__ == "__main__":
    raise SystemExit(main())
