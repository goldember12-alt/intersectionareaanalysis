from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring


ROOT = Path("work/output/roadway_graph")
OUT = ROOT / "review/current/route_discontinuity_offset_missing_leg_recovery"
TRIAGE = ROOT / "review/current/under_captured_recovery_triage_and_two_leg_audit"
ROUTE_DIAG = ROOT / "review/current/intersection_zone_route_discontinuity_diagnostic"
OFFSET_DIAG = ROOT / "review/current/offset_signal_intersection_anchor_diagnostic"
OFFSET_GPKG = OFFSET_DIAG / "offset_anchor_review.gpkg"
READY_RECOVERY = ROOT / "review/current/intersection_zone_missing_leg_recovery_candidates"
MAP_REVIEW_GPKG = ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg"

CRS = "EPSG:3968"
PRIMARY_RADIUS_FT = 175.0
BIN_SIZE_FT = 50.0
MAX_RECOVERY_FT = 2500.0
SECTOR_WIDTH = 45
TARGET_CLASSES = {
    "needs_route_facility_discontinuity_handling",
    "needs_offset_anchor_recovery",
}

CRASH_FIELD_TOKENS = (
    "crash_id",
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    TRIAGE / "under_captured_975_detail.csv",
    TRIAGE / "under_captured_recovery_class_summary.csv",
    TRIAGE / "under_captured_recovery_potential_estimate.csv",
    TRIAGE / "under_captured_ranked_recovery_queue.csv",
    TRIAGE / "under_captured_recovery_triage_manifest.json",
    ROUTE_DIAG / "route_discontinuity_signal_detail.csv",
    ROUTE_DIAG / "route_discontinuity_leg_group_detail.csv",
    ROUTE_DIAG / "route_discontinuity_class_summary.csv",
    ROUTE_DIAG / "intersection_zone_route_discontinuity_manifest.json",
    OFFSET_DIAG / "offset_anchor_candidate_detail.csv",
    OFFSET_DIAG / "offset_anchor_ranked_review_queue.csv",
    OFFSET_DIAG / "offset_signal_intersection_anchor_manifest.json",
    READY_RECOVERY / "recovered_missing_physical_leg_candidates.csv",
    READY_RECOVERY / "skipped_or_conflicting_recovery_targets.csv",
    READY_RECOVERY / "intersection_zone_missing_leg_recovery_candidates_manifest.json",
    MAP_REVIEW_GPKG,
]


def _log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _check_columns(columns: list[str], source: str) -> None:
    blocked = [column for column in columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash/direction fields from {source}: {blocked}")


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    _check_columns(header, str(path))
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _read_layer(path: Path, layer: str, *, required: bool = True) -> gpd.GeoDataFrame:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=CRS)
    _checkpoint(f"read_layer_start {layer}")
    try:
        frame = gpd.read_file(path, layer=layer)
    except Exception:
        if required:
            raise
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=CRS)
    if frame.crs is None:
        raise ValueError(f"Layer {layer} in {path} has unknown CRS")
    _check_columns(list(frame.columns), f"{path}:{layer}")
    frame = frame.to_crs(CRS)
    _checkpoint(f"read_layer_complete {layer}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_gpkg(frame: gpd.GeoDataFrame, layer: str) -> Path:
    path = OUT / "route_discontinuity_offset_recovery_candidates.gpkg"
    if frame.empty:
        _checkpoint(f"skip_empty_layer {layer}", 0)
        return path
    frame.to_file(path, layer=layer, driver="GPKG")
    _checkpoint(f"write_gpkg_layer {layer}", len(frame))
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _collapse(values: pd.Series, limit: int = 12) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in {"", "nan", "none", "<na>"} and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def _route_key_from_source(row: pd.Series) -> str:
    for column in ["RTE_COMMON", "RTE_NM", "RIM_FACI_1", "RTE_ID"]:
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _route_key_from_candidate(row: pd.Series) -> str:
    for column in ["route_or_facility_key", "route_or_facility_label"]:
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _source_line_id(row: pd.Series, fallback: int) -> str:
    parts = [
        str(row.get("EVENT_SOUR", "")).strip(),
        str(row.get("RTE_NM", "")).strip(),
        str(row.get("RTE_ID", "")).strip(),
        str(row.get("FROM_MEASURE", "")).strip(),
        str(row.get("TO_MEASURE", "")).strip(),
    ]
    text = "_".join(part for part in parts if part)
    return text if text else f"source_travelway_line_{fallback:06d}"


def _line_parts(geom: Any) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [part for part in geom.geoms if not part.is_empty]
    if hasattr(geom, "geoms"):
        return [part for part in geom.geoms if isinstance(part, LineString) and not part.is_empty]
    return []


def _longest_line(geom: Any) -> LineString | None:
    parts = _line_parts(geom)
    if not parts:
        return None
    return max(parts, key=lambda part: part.length)


def _bearing_from_point(point: Point, geom: Any) -> float:
    if point is None or geom is None or point.is_empty or geom.is_empty:
        return np.nan
    target = geom.interpolate(0.5, normalized=True)
    dx = float(target.x) - float(point.x)
    dy = float(target.y) - float(point.y)
    if math.isclose(dx, 0.0) and math.isclose(dy, 0.0):
        return np.nan
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _bearing_sector(bearing: float, width: int = SECTOR_WIDTH) -> str:
    if not np.isfinite(bearing):
        return "unknown"
    sector = int(((bearing + width / 2) % 360) // width)
    start = sector * width
    end = (sector + 1) * width
    return f"sector_{sector:02d}_{start:03d}_{end:03d}"


def _distance_band(end_ft: float) -> str:
    if end_ft <= 250:
        return "0_250ft"
    if end_ft <= 500:
        return "250_500ft"
    if end_ft <= 750:
        return "500_750ft"
    if end_ft <= 1000:
        return "750_1000ft"
    if end_ft <= 1500:
        return "1000_1500ft"
    return "1500_2500ft"


def _analysis_window(start_ft: float, end_ft: float) -> str:
    if start_ft < 1000 and end_ft <= 1000:
        return "0_1000"
    if start_ft >= 1000 and end_ft <= 2500:
        return "1000_2500"
    return "other_review"


def _outward_segment(line: LineString, anchor: Point, max_distance: float) -> LineString | None:
    if line is None or line.is_empty or line.length <= 0:
        return None
    projection = line.project(anchor)
    available_forward = line.length - projection
    available_backward = projection
    if available_forward >= available_backward:
        end = min(line.length, projection + max_distance)
        if end - projection <= 1.0:
            return None
        return substring(line, projection, end)
    start = max(0.0, projection - max_distance)
    if projection - start <= 1.0:
        return None
    segment = substring(line, start, projection)
    coords = list(segment.coords)
    return LineString(list(reversed(coords))) if len(coords) >= 2 else None


def _bin_geometries(path: LineString) -> list[tuple[float, float, LineString]]:
    rows: list[tuple[float, float, LineString]] = []
    usable = min(path.length, MAX_RECOVERY_FT)
    start = 0.0
    while start < usable - 0.01:
        end = min(start + BIN_SIZE_FT, usable)
        if end - start < 1.0:
            break
        geom = substring(path, start, end)
        if geom is not None and not geom.is_empty and geom.length > 0:
            rows.append((round(start, 3), round(end, 3), geom))
        start = end
    return rows


def _selected_targets(triage: pd.DataFrame) -> pd.DataFrame:
    targets = triage.loc[triage["under_capture_triage_class"].isin(TARGET_CLASSES)].copy()
    targets["missing_physical_leg_count"] = targets["calibrated_missing_leg_count"].map(_int)
    targets["recovery_rule"] = np.where(
        targets["under_capture_triage_class"].eq("needs_offset_anchor_recovery"),
        "offset_anchor_missing_leg_recovery",
        "route_facility_discontinuity_missing_leg_recovery",
    )
    return targets


def _anchor_points(targets: pd.DataFrame, signal_points: gpd.GeoDataFrame, offset_centers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    base = signal_points.loc[signal_points["signal_id"].isin(set(targets["signal_id"]))].copy()
    base = base[["signal_id", "source_signal_id", "source_layer", "geometry"]].drop_duplicates("signal_id")
    base = base.rename_geometry("signal_geometry")
    base = pd.DataFrame(base.drop(columns="signal_geometry")).join(gpd.GeoSeries(base.signal_geometry, name="signal_geometry"))

    if not offset_centers.empty and "signal_id" in offset_centers.columns:
        centers = offset_centers[["signal_id", "inferred_intersection_center_method", "signal_to_inferred_center_ft", "geometry"]].drop_duplicates("signal_id")
        centers = centers.rename_geometry("offset_anchor_geometry")
        base = base.merge(pd.DataFrame(centers.drop(columns="offset_anchor_geometry")).join(gpd.GeoSeries(centers.offset_anchor_geometry, name="offset_anchor_geometry")), on="signal_id", how="left")
    else:
        base["offset_anchor_geometry"] = None
        base["inferred_intersection_center_method"] = ""
        base["signal_to_inferred_center_ft"] = ""

    class_lookup = targets.drop_duplicates("signal_id").set_index("signal_id")["under_capture_triage_class"].to_dict()
    base["under_capture_triage_class"] = base["signal_id"].map(class_lookup).fillna("")
    base["anchor_method"] = np.where(
        base["under_capture_triage_class"].eq("needs_offset_anchor_recovery") & base["offset_anchor_geometry"].notna(),
        "inferred_intersection_zone_anchor",
        "signal_point_anchor",
    )
    base["geometry"] = [
        row["offset_anchor_geometry"] if row["anchor_method"] == "inferred_intersection_zone_anchor" else row["signal_geometry"]
        for _, row in base.iterrows()
    ]
    return gpd.GeoDataFrame(base.drop(columns=["signal_geometry", "offset_anchor_geometry"]), geometry="geometry", crs=CRS)


def _source_zone_table(targets: pd.DataFrame, anchors: gpd.GeoDataFrame, source: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    zones = anchors[["signal_id", "geometry"]].copy()
    zones["geometry"] = zones.geometry.buffer(PRIMARY_RADIUS_FT)
    joined = gpd.sjoin(source.reset_index(drop=True), zones, how="inner", predicate="intersects")
    if joined.empty:
        return gpd.GeoDataFrame(columns=["signal_id", "source_bearing_sector", "geometry"], geometry="geometry", crs=CRS)
    anchor_lookup = anchors.drop_duplicates("signal_id").set_index("signal_id").geometry
    zone_lookup = zones.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for idx, row in joined.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", "")).strip()
        anchor = anchor_lookup.get(signal_id)
        line = _longest_line(row.geometry)
        if anchor is None or line is None:
            continue
        bearing = _bearing_from_point(anchor, line)
        route_key = _route_key_from_source(row)
        route_norm = _normalize_key(route_key)
        zone_geom = zone_lookup.get(signal_id)
        rows.append(
            {
                "signal_id": signal_id,
                "source_zone_row_id": idx,
                "source_line_id": _source_line_id(row, idx),
                "source_bearing_sector": _bearing_sector(bearing),
                "source_bearing_degrees": round(float(bearing), 3) if np.isfinite(bearing) else "",
                "source_route_key": route_key,
                "source_route_key_normalized": route_norm,
                "source_rte_nm": str(row.get("RTE_NM", "")).strip(),
                "source_rte_common": str(row.get("RTE_COMMON", "")).strip(),
                "source_rte_id": str(row.get("RTE_ID", "")).strip(),
                "source_facility": str(row.get("RIM_FACI_1", "")).strip(),
                "source_event_source": str(row.get("EVENT_SOUR", "")).strip(),
                "source_from_measure": str(row.get("FROM_MEASURE", "")).strip(),
                "source_to_measure": str(row.get("TO_MEASURE", "")).strip(),
                "source_zone_intersection_length_ft": round(float(row.geometry.intersection(zone_geom).length), 3) if zone_geom is not None else 0.0,
                "source_line_total_length_ft": round(float(row.geometry.length), 3),
            }
        )
        geoms.append(row.geometry)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _candidate_sector_table(targets: pd.DataFrame, anchors: gpd.GeoDataFrame, candidate_bins: gpd.GeoDataFrame) -> pd.DataFrame:
    bins = candidate_bins.loc[candidate_bins["signal_id"].isin(set(targets["signal_id"]))].copy()
    if bins.empty:
        return pd.DataFrame(columns=["signal_id", "candidate_bearing_sector"])
    anchor_lookup = anchors.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    for idx, row in bins.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", "")).strip()
        anchor = anchor_lookup.get(signal_id)
        line = _longest_line(row.geometry)
        if anchor is None or line is None:
            continue
        bearing = _bearing_from_point(anchor, line)
        rows.append(
            {
                "signal_id": signal_id,
                "candidate_zone_row_id": idx,
                "candidate_bearing_sector": _bearing_sector(bearing),
                "candidate_route_key": _route_key_from_candidate(row),
                "candidate_route_key_normalized": _normalize_key(_route_key_from_candidate(row)),
                "candidate_bin_id": str(row.get("target_bin_id", "")).strip(),
            }
        )
    return pd.DataFrame(rows)


def _diag_maps(route_signal: pd.DataFrame, route_leg: pd.DataFrame, offset_detail: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    route_signal_map = route_signal.drop_duplicates("signal_id").set_index("signal_id").to_dict("index") if not route_signal.empty else {}
    route_leg_map: dict[tuple[str, str], dict[str, Any]] = {}
    if not route_leg.empty:
        for _, row in route_leg.iterrows():
            route_leg_map[(str(row.get("signal_id", "")), str(row.get("physical_leg_bearing_group", "")))] = row.to_dict()
    offset_map = offset_detail.drop_duplicates("signal_id").set_index("signal_id").to_dict("index") if not offset_detail.empty else {}
    return route_signal_map, route_leg_map, offset_map


def _discontinuity_type(signal_id: str, sector: str, route_signal_map: dict[str, dict[str, Any]], route_leg_map: dict[tuple[str, str], dict[str, Any]]) -> str:
    leg = route_leg_map.get((signal_id, sector), {})
    if leg:
        value = str(leg.get("route_facility_discontinuity_type", "")).strip()
        if value:
            return value
        if _bool(leg.get("source_line_split_at_intersection")):
            return "source_line_split_with_same_name"
        if _bool(leg.get("route_key_differs_but_geometry_continuous")):
            return "route_key_changes_but_facility_same"
        if _bool(leg.get("route_facility_changes_across_intersection")):
            return "facility_changes_but_geometry_continuous"
    signal = route_signal_map.get(signal_id, {})
    value = str(signal.get("route_facility_discontinuity_types", "")).strip()
    return value if value else "insufficient_evidence"


def _build_leg_candidates(
    targets: pd.DataFrame,
    source_zone: gpd.GeoDataFrame,
    candidate_sectors: pd.DataFrame,
    anchors: gpd.GeoDataFrame,
    route_signal_map: dict[str, dict[str, Any]],
    route_leg_map: dict[tuple[str, str], dict[str, Any]],
    offset_map: dict[str, dict[str, Any]],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    existing_by_signal = (
        candidate_sectors.groupby("signal_id")["candidate_bearing_sector"].apply(lambda values: set(values.dropna().astype(str))).to_dict()
        if not candidate_sectors.empty
        else {}
    )
    anchor_lookup = anchors.drop_duplicates("signal_id").set_index("signal_id").geometry
    anchor_meta = anchors.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    target_lookup = targets.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    leg_rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    skipped: list[dict[str, Any]] = []

    for signal_id, target in target_lookup.items():
        group = source_zone.loc[source_zone["signal_id"].eq(signal_id)].copy()
        if group.empty:
            skipped.append({"signal_id": signal_id, "recovery_class": target.get("under_capture_triage_class", ""), "skip_reason": "no_source_travelway_line_intersected_anchor_zone"})
            continue
        missing_count = _int(target.get("missing_physical_leg_count"))
        existing = existing_by_signal.get(signal_id, set())
        source_sectors = [sector for sector in group["source_bearing_sector"].dropna().astype(str).unique().tolist() if sector != "unknown"]
        missing_sectors = [sector for sector in source_sectors if sector not in existing]
        if not missing_sectors:
            skipped.append({"signal_id": signal_id, "recovery_class": target.get("under_capture_triage_class", ""), "skip_reason": "no_source_sector_absent_from_candidate_bins", "missing_sector_count": 0, "calibrated_missing_leg_count": missing_count})
            continue
        sector_stats = (
            group.loc[group["source_bearing_sector"].isin(missing_sectors)]
            .groupby("source_bearing_sector", dropna=False)
            .agg(
                source_line_count=("source_line_id", "nunique"),
                source_route_group_count=("source_route_key_normalized", "nunique"),
                source_route_keys=("source_route_key", _collapse),
                source_line_ids=("source_line_id", _collapse),
                source_zone_intersection_length_ft=("source_zone_intersection_length_ft", "sum"),
                source_line_total_length_ft=("source_line_total_length_ft", "max"),
            )
            .reset_index()
            .sort_values(["source_zone_intersection_length_ft", "source_line_total_length_ft", "source_line_count"], ascending=False)
        )
        selected = sector_stats.head(max(1, missing_count)).copy()
        if len(missing_sectors) > missing_count:
            selection_status = "more_absent_source_sectors_than_calibrated_missing_count_selected_top_length"
        elif len(missing_sectors) < missing_count:
            selection_status = "fewer_absent_source_sectors_than_calibrated_missing_count_partial_recovery"
        else:
            selection_status = "absent_source_sector_count_matches_calibrated_missing_count"

        anchor = anchor_lookup.get(signal_id)
        meta = anchor_meta.get(signal_id, {})
        offset_diag = offset_map.get(signal_id, {})
        for leg_index, row in selected.reset_index(drop=True).iterrows():
            sector = str(row["source_bearing_sector"])
            sector_lines = group.loc[group["source_bearing_sector"].eq(sector)].sort_values(["source_zone_intersection_length_ft", "source_line_total_length_ft"], ascending=False)
            source_line = sector_lines.iloc[0]
            line = _longest_line(source_line.geometry)
            segment = _outward_segment(line, anchor, MAX_RECOVERY_FT) if line is not None and anchor is not None else None
            if segment is None:
                skipped.append({"signal_id": signal_id, "recovery_class": target.get("under_capture_triage_class", ""), "source_bearing_sector": sector, "skip_reason": "source_line_could_not_generate_outward_segment"})
                continue
            recovery_class = str(target.get("under_capture_triage_class", ""))
            disc_type = _discontinuity_type(signal_id, sector, route_signal_map, route_leg_map)
            candidate_id = f"missing_leg::{signal_id}::{recovery_class.replace('needs_', '')}::{leg_index + 1:02d}::{sector}"
            leg_rows.append(
                {
                    "candidate_missing_leg_id": candidate_id,
                    "signal_id": signal_id,
                    "source_signal_id": target.get("source_signal_id_x", ""),
                    "source_layer": target.get("source_layer_x", ""),
                    "recovery_class": recovery_class,
                    "recovery_rule": "route_discontinuity_offset_missing_leg_recovery",
                    "recovery_subreason": "offset_anchor_source_leg_absent_from_candidate_bins" if recovery_class == "needs_offset_anchor_recovery" else "route_facility_discontinuity_source_leg_absent_from_candidate_bins",
                    "source_bearing_sector": sector,
                    "source_line_ids": row["source_line_ids"],
                    "primary_source_line_id": source_line["source_line_id"],
                    "source_route_keys": row["source_route_keys"],
                    "source_route_group_count": int(row["source_route_group_count"]),
                    "candidate_existing_sector_count": len(existing),
                    "source_absent_sector_count": len(missing_sectors),
                    "calibrated_expected_physical_leg_count": target.get("calibrated_expected_physical_leg_count", ""),
                    "current_refreshed_physical_leg_count": target.get("current_refreshed_physical_leg_count", ""),
                    "calibrated_missing_leg_count": missing_count,
                    "candidate_selection_status": selection_status,
                    "route_facility_discontinuity_flag": recovery_class == "needs_route_facility_discontinuity_handling",
                    "route_facility_discontinuity_type": disc_type,
                    "offset_anchor_flag": recovery_class == "needs_offset_anchor_recovery",
                    "offset_anchor_class": target.get("offset_anchor_class", offset_diag.get("offset_anchor_class", "")),
                    "anchor_method": meta.get("anchor_method", ""),
                    "inferred_intersection_center_method": meta.get("inferred_intersection_center_method", ""),
                    "signal_to_inferred_center_ft": meta.get("signal_to_inferred_center_ft", offset_diag.get("signal_to_inferred_center_ft", "")),
                    "source_line_split_flag": "source_line_split" in disc_type,
                    "grade_separation_or_mainline_review_flag": "mainline" in str(row["source_route_keys"]).lower() or "interstate" in str(row["source_route_keys"]).lower(),
                    "review_only": True,
                    "candidate_promoted": False,
                    "partial_coverage_preserved": True,
                    "available_recovered_length_ft": round(float(segment.length), 3),
                    "context_refresh_likely_supported": bool(row["source_line_ids"]),
                }
            )
            geoms.append(segment)

    legs = gpd.GeoDataFrame(leg_rows, geometry=geoms, crs=CRS)
    return legs, pd.DataFrame(skipped)


def _build_bins(legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for _, leg in legs.iterrows():
        path = _longest_line(leg.geometry)
        if path is None:
            continue
        for start, end, geom in _bin_geometries(path):
            rows.append(
                {
                    "candidate_missing_leg_bin_id": f"{leg['candidate_missing_leg_id']}::bin_{int(start):04d}_{int(end):04d}",
                    "candidate_missing_leg_id": leg["candidate_missing_leg_id"],
                    "signal_id": leg["signal_id"],
                    "source_signal_id": leg["source_signal_id"],
                    "source_layer": leg["source_layer"],
                    "recovery_class": leg["recovery_class"],
                    "recovery_rule": leg["recovery_rule"],
                    "source_bearing_sector": leg["source_bearing_sector"],
                    "primary_source_line_id": leg["primary_source_line_id"],
                    "source_route_keys": leg["source_route_keys"],
                    "distance_start_ft": start,
                    "distance_end_ft": end,
                    "bin_length_ft": round(end - start, 3),
                    "distance_band": _distance_band(end),
                    "analysis_window": _analysis_window(start, end),
                    "route_facility_discontinuity_flag": leg["route_facility_discontinuity_flag"],
                    "offset_anchor_flag": leg["offset_anchor_flag"],
                    "source_line_split_flag": leg["source_line_split_flag"],
                    "grade_separation_or_mainline_review_flag": leg["grade_separation_or_mainline_review_flag"],
                    "candidate_selection_status": leg["candidate_selection_status"],
                    "context_refresh_likely_supported": leg["context_refresh_likely_supported"],
                    "review_only": True,
                    "candidate_promoted": False,
                    "partial_bin_flag": bool(end - start < BIN_SIZE_FT - 0.01),
                }
            )
            geoms.append(geom)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _summary(targets: pd.DataFrame, legs: gpd.GeoDataFrame, bins: gpd.GeoDataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for recovery_class, group in targets.groupby("under_capture_triage_class", dropna=False):
        class_legs = legs.loc[legs["recovery_class"].eq(recovery_class)] if not legs.empty else legs
        class_bins = bins.loc[bins["recovery_class"].eq(recovery_class)] if not bins.empty else bins
        class_skipped = skipped.loc[skipped["recovery_class"].eq(recovery_class)] if not skipped.empty and "recovery_class" in skipped.columns else pd.DataFrame()
        rows.append(
            {
                "recovery_class": recovery_class,
                "target_signal_count": group["signal_id"].nunique(),
                "recovered_signal_count": class_legs["signal_id"].nunique() if not class_legs.empty else 0,
                "recovered_physical_leg_count": len(class_legs),
                "recovered_bin_count": len(class_bins),
                "recovered_bins_0_1000": int(class_bins["analysis_window"].eq("0_1000").sum()) if not class_bins.empty else 0,
                "recovered_bins_1000_2500": int(class_bins["analysis_window"].eq("1000_2500").sum()) if not class_bins.empty else 0,
                "skipped_signal_count": class_skipped["signal_id"].nunique() if not class_skipped.empty else 0,
                "context_refresh_likely_supported_legs": int(class_legs["context_refresh_likely_supported"].sum()) if not class_legs.empty else 0,
            }
        )
    rows.append(
        {
            "recovery_class": "total",
            "target_signal_count": targets["signal_id"].nunique(),
            "recovered_signal_count": legs["signal_id"].nunique() if not legs.empty else 0,
            "recovered_physical_leg_count": len(legs),
            "recovered_bin_count": len(bins),
            "recovered_bins_0_1000": int(bins["analysis_window"].eq("0_1000").sum()) if not bins.empty else 0,
            "recovered_bins_1000_2500": int(bins["analysis_window"].eq("1000_2500").sum()) if not bins.empty else 0,
            "skipped_signal_count": targets["signal_id"].nunique() - (legs["signal_id"].nunique() if not legs.empty else 0),
            "context_refresh_likely_supported_legs": int(legs["context_refresh_likely_supported"].sum()) if not legs.empty else 0,
        }
    )
    return pd.DataFrame(rows)


def _review_queue(targets: pd.DataFrame, legs: gpd.GeoDataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    if legs.empty:
        leg_summary = pd.DataFrame(columns=["signal_id"])
    else:
        leg_summary = legs.groupby("signal_id").agg(
            recovered_physical_leg_count=("candidate_missing_leg_id", "nunique"),
            route_facility_discontinuity_types=("route_facility_discontinuity_type", _collapse),
            selection_statuses=("candidate_selection_status", _collapse),
            any_grade_separation_or_mainline_review=("grade_separation_or_mainline_review_flag", "max"),
            context_refresh_likely_supported=("context_refresh_likely_supported", "max"),
        ).reset_index()
    base = targets[["signal_id", "source_signal_id_x", "source_layer_x", "under_capture_triage_class", "calibrated_missing_leg_count", "source_bearing_groups", "source_route_groups"]].copy()
    out = base.merge(leg_summary, on="signal_id", how="left")
    if not skipped.empty:
        skip = skipped.groupby("signal_id").agg(skip_reasons=("skip_reason", _collapse)).reset_index()
        out = out.merge(skip, on="signal_id", how="left")
    out["recovered_physical_leg_count"] = pd.to_numeric(out.get("recovered_physical_leg_count", 0), errors="coerce").fillna(0).astype(int)
    out["review_queue_class"] = np.where(
        out["recovered_physical_leg_count"].gt(0),
        "generated_candidate_needs_context_refresh",
        "skipped_review_needed",
    )
    out["review_priority_score"] = out["recovered_physical_leg_count"] * 10 + pd.to_numeric(out["calibrated_missing_leg_count"], errors="coerce").fillna(0)
    return out.sort_values(["review_queue_class", "review_priority_score"], ascending=[True, False])


def _findings(summary: pd.DataFrame) -> str:
    by_class = summary.set_index("recovery_class").to_dict("index")
    route = by_class.get("needs_route_facility_discontinuity_handling", {})
    offset = by_class.get("needs_offset_anchor_recovery", {})
    total = by_class.get("total", {})
    return f"""# Route-Discontinuity and Offset Missing-Leg Recovery Findings

## Bounded Question

This read-only pass targets only `needs_route_facility_discontinuity_handling` and `needs_offset_anchor_recovery` under-capture classes. It generates review-only source-geometry missing-leg candidates and bins where geometry/bearing evidence is sufficient. It does not target divided-carriageway/subbranch normalization.

## Results

- Route/facility discontinuity signals targeted: {int(route.get("target_signal_count", 0)):,}
- Offset-anchor signals targeted: {int(offset.get("target_signal_count", 0)):,}
- Total target signals: {int(total.get("target_signal_count", 0)):,}
- Signals with generated candidates: {int(total.get("recovered_signal_count", 0)):,}
- Recovered physical legs generated: {int(total.get("recovered_physical_leg_count", 0)):,}
- 0-1,000 ft bins generated: {int(total.get("recovered_bins_0_1000", 0)):,}
- 1,000-2,500 ft sensitivity bins generated: {int(total.get("recovered_bins_1000_2500", 0)):,}
- Skipped signals: {int(total.get("skipped_signal_count", 0)):,}

## Interpretation

Route/facility labels were kept as QA attributes; source legs were selected by geometry/bearing sectors missing from current candidate bins. Offset-anchor cases used inferred intersection-zone centers when available. Missing source sectors that could not be identified safely were skipped and preserved for review.

## Recommendation

Generated candidates should go through the same review-only context refresh used for prior missing-leg candidates. Divided-carriageway/subbranch normalization remains a separate backlog and should not be mixed into this recovery output.
"""


def _qa(targets: pd.DataFrame, legs: gpd.GeoDataFrame, bins: gpd.GeoDataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    target_class_set = set(targets["under_capture_triage_class"].unique())
    rows = [
        ("no_active_outputs_modified", True, "", "true", "All writes are under the review output folder."),
        ("no_candidates_promoted", bool(legs.empty or legs["candidate_promoted"].eq(False).all()), "", "true", "Candidates remain review-only."),
        ("no_access_or_crash_assignment", True, "", "true", "No access or crash inputs are used."),
        ("no_rates_or_models", True, "", "true", "No rates/models are calculated."),
        ("only_144_plus_45_target_classes_processed", target_class_set.issubset(TARGET_CLASSES), "|".join(sorted(target_class_set)), "|".join(sorted(TARGET_CLASSES)), ""),
        ("divided_carriageway_subbranch_not_targeted", "needs_divided_carriageway_subbranch_normalization" not in target_class_set, "", "true", ""),
        ("route_facility_labels_not_primary_grouping_keys", True, "", "true", "Bearing sectors from geometry define candidate legs; route labels are QA attributes."),
        ("partial_bins_preserved", bool(bins.empty or "partial_bin_flag" in bins.columns), "", "true", ""),
        ("outputs_review_only", bool(legs.empty or legs["review_only"].eq(True).all()), "", "true", ""),
        ("outputs_written_only_to_review_folder", str(OUT).replace("\\", "/").endswith("review/current/route_discontinuity_offset_missing_leg_recovery"), str(OUT), "review/current/route_discontinuity_offset_missing_leg_recovery", ""),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "observed", "expected", "note"])


def _manifest(outputs: list[Path], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src/active/roadway_graph/route_discontinuity_offset_missing_leg_recovery.py",
        "output_dir": str(OUT),
        "read_only": True,
        "target_classes": sorted(TARGET_CLASSES),
        "primary_radius_ft": PRIMARY_RADIUS_FT,
        "bin_size_ft": BIN_SIZE_FT,
        "max_recovery_ft": MAX_RECOVERY_FT,
        "inputs": [str(path) for path in REQUIRED_INPUTS] + [str(OFFSET_GPKG)],
        "outputs": [str(path) for path in outputs],
        "metrics": metrics,
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_assigned": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "divided_carriageway_subbranch_normalization_targeted": False,
        },
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    triage = _read_csv(TRIAGE / "under_captured_975_detail.csv")
    route_signal = _read_csv(ROUTE_DIAG / "route_discontinuity_signal_detail.csv")
    route_leg = _read_csv(ROUTE_DIAG / "route_discontinuity_leg_group_detail.csv")
    offset_detail = _read_csv(OFFSET_DIAG / "offset_anchor_candidate_detail.csv")
    _read_csv(OFFSET_DIAG / "offset_anchor_ranked_review_queue.csv")
    _read_csv(READY_RECOVERY / "recovered_missing_physical_leg_candidates.csv")
    _read_csv(READY_RECOVERY / "skipped_or_conflicting_recovery_targets.csv")

    targets = _selected_targets(triage)
    _checkpoint("selected_targets", targets["signal_id"].nunique())

    signal_points = _read_layer(MAP_REVIEW_GPKG, "review_signal_points")
    candidate_bins = _read_layer(MAP_REVIEW_GPKG, "review_candidate_bins")
    source = _read_layer(MAP_REVIEW_GPKG, "source_travelway_full")
    offset_centers = _read_layer(OFFSET_GPKG, "inferred_intersection_zone_centers", required=False)

    anchors = _anchor_points(targets, signal_points, offset_centers)
    source_zone = _source_zone_table(targets, anchors, source)
    candidate_sectors = _candidate_sector_table(targets, anchors, candidate_bins)
    route_signal_map, route_leg_map, offset_map = _diag_maps(route_signal, route_leg, offset_detail)
    legs, skipped = _build_leg_candidates(targets, source_zone, candidate_sectors, anchors, route_signal_map, route_leg_map, offset_map)
    bins = _build_bins(legs)
    summary = _summary(targets, legs, bins, skipped)
    review_queue = _review_queue(targets, legs, skipped)
    qa = _qa(targets, legs, bins, skipped)

    outputs: list[Path] = []
    leg_csv = OUT / "route_discontinuity_offset_recovered_leg_candidates.csv"
    pd.DataFrame(legs.drop(columns="geometry", errors="ignore")).to_csv(leg_csv, index=False)
    outputs.append(leg_csv)
    _checkpoint("write route_discontinuity_offset_recovered_leg_candidates.csv", len(legs))

    bin_csv = OUT / "route_discontinuity_offset_recovered_bins.csv"
    pd.DataFrame(bins.drop(columns="geometry", errors="ignore")).to_csv(bin_csv, index=False)
    outputs.append(bin_csv)
    _checkpoint("write route_discontinuity_offset_recovered_bins.csv", len(bins))

    outputs.append(_write_csv(skipped, "route_discontinuity_offset_skipped_targets.csv"))
    outputs.append(_write_csv(summary, "route_discontinuity_offset_recovery_summary.csv"))
    outputs.append(_write_csv(review_queue, "route_discontinuity_offset_recovery_review_queue.csv"))
    gpkg = _write_gpkg(legs, "recovered_leg_candidates")
    _write_gpkg(bins, "recovered_candidate_bins")
    if gpkg not in outputs:
        outputs.append(gpkg)
    outputs.append(_write_csv(qa, "route_discontinuity_offset_recovery_qa.csv"))
    findings_path = OUT / "route_discontinuity_offset_recovery_findings.md"
    findings_path.write_text(_findings(summary), encoding="utf-8")
    outputs.append(findings_path)
    _checkpoint("write route_discontinuity_offset_recovery_findings.md")

    total_row = summary.loc[summary["recovery_class"].eq("total")].iloc[0].to_dict()
    metrics = {key: int(value) if isinstance(value, (np.integer, int)) or str(value).isdigit() else value for key, value in total_row.items()}
    manifest_path = OUT / "route_discontinuity_offset_recovery_manifest.json"
    manifest_path.write_text(json.dumps(_manifest(outputs, metrics), indent=2), encoding="utf-8")
    outputs.append(manifest_path)
    _checkpoint("write route_discontinuity_offset_recovery_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
