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
from shapely.ops import substring, unary_union


ROOT = Path("work/output/roadway_graph")
OUT = ROOT / "review/current/offset_intersection_zone_scaffold_recovery"
OFFSET_DIAG = ROOT / "review/current/offset_signal_intersection_anchor_diagnostic"
OFFSET_GPKG = OFFSET_DIAG / "offset_anchor_review.gpkg"
MAP_REVIEW_GPKG = ROOT / "map_review/current/intersection_zone_recovery_review/intersection_zone_recovery_review.gpkg"

CRS = "EPSG:3968"
PRIMARY_RADIUS_FT = 175
BIN_SIZE_FT = 50
MAX_RECOVERY_FT = 1000
FEET_PER_METER = 3.280839895
SECTOR_WIDTH = 45

TARGET_CLASSES = {
    "offset_anchor_high_confidence_recovery_candidate",
    "offset_anchor_medium_confidence_review_candidate",
}

CRASH_FIELD_TOKENS = (
    "crash_id",
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)


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
    if lower in {"signal_relative_direction_label", "direction_confidence_status", "true_vehicle_direction_inferred"}:
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


def _read_layer(path: Path, layer: str) -> gpd.GeoDataFrame:
    _checkpoint(f"read_layer_start {layer}")
    frame = gpd.read_file(path, layer=layer)
    if frame.crs is None:
        raise ValueError(f"Layer {layer} in {path} has unknown CRS")
    _check_columns(list(frame.columns), f"{path}:{layer}")
    frame = frame.to_crs(CRS)
    _checkpoint(f"read_layer_complete {layer}", len(frame))
    return frame


def _text(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="string")
    return frame[column].fillna(default).astype(str).str.strip()


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _collapse(values: pd.Series, limit: int = 12) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


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


def _sector_short(sector: str) -> str:
    parts = str(sector).split("_")
    if len(parts) >= 2 and parts[0] == "sector":
        return f"sector_{parts[1]}"
    return str(sector)


def _route_key_from_source(row: pd.Series) -> str:
    for column in ["RTE_COMMON", "RTE_NM", "RIM_FACI_1", "RTE_ID"]:
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _route_key_from_candidate(row: pd.Series) -> str:
    for column in ["route_or_facility_label", "route_or_facility_key"]:
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


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
    return max(parts, key=lambda item: item.length)


def _distance_band(end_ft: int) -> str:
    if end_ft <= 250:
        return "0_250ft"
    if end_ft <= 500:
        return "250_500ft"
    if end_ft <= 750:
        return "500_750ft"
    return "750_1000ft"


def _source_line_id(row: pd.Series, fallback: int) -> str:
    parts = [
        str(row.get("EVENT_SOUR", "")).strip(),
        str(row.get("RTE_NM", "")).strip(),
        str(row.get("RTE_ID", "")).strip(),
        str(row.get("FROM_MEASURE", "")).strip(),
        str(row.get("TO_MEASURE", "")).strip(),
    ]
    text = "_".join(part for part in parts if part)
    return text if text else f"offset_source_line_{fallback:06d}"


def _source_sector_table(source_lines: gpd.GeoDataFrame, centers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    center_lookup = centers.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for idx, row in source_lines.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", ""))
        center = center_lookup.get(signal_id)
        if center is None:
            continue
        bearing = _bearing_from_point(center, row.geometry)
        sector = _bearing_sector(bearing)
        rows.append(
            {
                "signal_id": signal_id,
                "source_line_id": _source_line_id(row, idx),
                "source_zone_row_id": idx,
                "physical_leg_bearing_group": sector,
                "physical_leg_bearing_group_short": _sector_short(sector),
                "bearing_degrees_from_intersection_center": round(float(bearing), 3) if np.isfinite(bearing) else "",
                "source_route_key": _route_key_from_source(row),
                "source_route_key_normalized": _normalize_key(_route_key_from_source(row)),
                "source_rte_nm": str(row.get("RTE_NM", "")).strip(),
                "source_rte_common": str(row.get("RTE_COMMON", "")).strip(),
                "source_rte_id": str(row.get("RTE_ID", "")).strip(),
                "source_facility": str(row.get("RIM_FACI_1", "")).strip(),
                "source_from_measure": str(row.get("FROM_MEASURE", "")).strip(),
                "source_to_measure": str(row.get("TO_MEASURE", "")).strip(),
            }
        )
        geoms.append(row.geometry)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _candidate_sector_table(candidate_lines: gpd.GeoDataFrame, centers: gpd.GeoDataFrame) -> pd.DataFrame:
    center_lookup = centers.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    for idx, row in candidate_lines.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", ""))
        center = center_lookup.get(signal_id)
        if center is None:
            continue
        bearing = _bearing_from_point(center, row.geometry)
        sector = _bearing_sector(bearing)
        route = _route_key_from_candidate(row)
        rows.append(
            {
                "signal_id": signal_id,
                "candidate_zone_row_id": idx,
                "candidate_bearing_group": sector,
                "candidate_bearing_group_short": _sector_short(sector),
                "candidate_route_key": route,
                "candidate_route_key_normalized": _normalize_key(route),
                "target_bin_id": str(row.get("target_bin_id", "")).strip(),
            }
        )
    return pd.DataFrame(rows)


def _graph_sector_table(graph_lines: gpd.GeoDataFrame, centers: gpd.GeoDataFrame) -> pd.DataFrame:
    center_lookup = centers.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    for idx, row in graph_lines.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", ""))
        center = center_lookup.get(signal_id)
        if center is None:
            continue
        bearing = _bearing_from_point(center, row.geometry)
        sector = _bearing_sector(bearing)
        route = str(row.get("route_common", "") or row.get("route_name", "") or row.get("route_id", "")).strip()
        rows.append(
            {
                "signal_id": signal_id,
                "graph_zone_row_id": idx,
                "graph_bearing_group": sector,
                "graph_bearing_group_short": _sector_short(sector),
                "graph_route_key": route,
                "graph_route_key_normalized": _normalize_key(route),
            }
        )
    return pd.DataFrame(rows)


def _route_name_change_diagnostic(source_sectors: gpd.GeoDataFrame) -> pd.DataFrame:
    if source_sectors.empty:
        return pd.DataFrame()
    rows = []
    for (signal_id, sector), group in source_sectors.groupby(["signal_id", "physical_leg_bearing_group"], dropna=False):
        routes = sorted({r for r in group["source_route_key"].astype(str) if r.strip()})
        norm_routes = sorted({r for r in group["source_route_key_normalized"].astype(str) if r.strip()})
        geom_union = unary_union([geom for geom in group.geometry if geom is not None and not geom.is_empty])
        source_split = len(group) > 1
        route_change = len(norm_routes) > 1
        rows.append(
            {
                "signal_id": signal_id,
                "physical_leg_bearing_group": sector,
                "source_line_count_in_bearing_group": len(group),
                "source_route_keys": "|".join(routes),
                "source_route_key_count": len(norm_routes),
                "same_route_facility_on_both_sides": route_change is False and len(group) > 1,
                "route_facility_changes_across_intersection": route_change,
                "route_key_differs_but_geometry_continuous": route_change and geom_union.length > 0,
                "source_line_split_at_intersection": source_split,
                "name_facility_discontinuity_may_explain_missed_scaffold_leg": route_change,
            }
        )
    return pd.DataFrame(rows)


def _build_leg_candidates(
    targets: pd.DataFrame,
    source_sectors: gpd.GeoDataFrame,
    candidate_sectors: pd.DataFrame,
    graph_sectors: pd.DataFrame,
    centers: gpd.GeoDataFrame,
    signal_points: gpd.GeoDataFrame,
    route_diag: pd.DataFrame,
) -> gpd.GeoDataFrame:
    target_lookup = targets.drop_duplicates("signal_id").set_index("signal_id").to_dict(orient="index")
    center_lookup = centers.drop_duplicates("signal_id").set_index("signal_id").geometry
    signal_lookup = signal_points.drop_duplicates("signal_id").set_index("signal_id").geometry
    cand_by_signal = {
        sid: set(group["candidate_bearing_group_short"].dropna().astype(str))
        for sid, group in candidate_sectors.groupby("signal_id", dropna=False)
    }
    cand_routes_by_signal = {
        sid: set(group["candidate_route_key_normalized"].dropna().astype(str))
        for sid, group in candidate_sectors.groupby("signal_id", dropna=False)
    }
    graph_by_signal = {
        sid: set(group["graph_bearing_group_short"].dropna().astype(str))
        for sid, group in graph_sectors.groupby("signal_id", dropna=False)
    }
    route_lookup = {
        (str(row.signal_id), str(row.physical_leg_bearing_group)): row._asdict()
        for row in route_diag.itertuples(index=False)
    }
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    grouped = source_sectors.groupby(["signal_id", "physical_leg_bearing_group"], dropna=False)
    for (signal_id, sector), group in grouped:
        if signal_id not in target_lookup:
            continue
        short_sector = _sector_short(str(sector))
        candidate_sector_represented = short_sector in cand_by_signal.get(signal_id, set())
        graph_sector_represented = short_sector in graph_by_signal.get(signal_id, set())
        source_routes = {r for r in group["source_route_key_normalized"].dropna().astype(str) if r}
        candidate_route_overlap = bool(source_routes & cand_routes_by_signal.get(signal_id, set()))
        existing_overlap_status = "not_represented_by_candidate_bearing_group"
        if candidate_sector_represented and candidate_route_overlap:
            existing_overlap_status = "represented_by_candidate_bearing_and_route"
        elif candidate_sector_represented:
            existing_overlap_status = "bearing_represented_route_gap"
        elif candidate_route_overlap:
            existing_overlap_status = "route_represented_bearing_gap"
        should_recover = existing_overlap_status in {
            "not_represented_by_candidate_bearing_group",
            "bearing_represented_route_gap",
            "route_represented_bearing_gap",
        }
        if not should_recover:
            continue
        geom = unary_union([g for g in group.geometry if g is not None and not g.is_empty])
        target = target_lookup[signal_id]
        route_info = route_lookup.get((signal_id, str(sector)), {})
        center = center_lookup.get(signal_id)
        signal_pt = signal_lookup.get(signal_id)
        rows.append(
            {
                "signal_id": signal_id,
                "source_signal_id": target.get("source_signal_id", ""),
                "offset_anchor_class": target.get("offset_anchor_class", ""),
                "recovery_confidence": "high" if "high" in str(target.get("offset_anchor_class", "")) else "medium",
                "original_signal_x": round(float(signal_pt.x), 3) if signal_pt is not None else "",
                "original_signal_y": round(float(signal_pt.y), 3) if signal_pt is not None else "",
                "intersection_anchor_x": round(float(center.x), 3) if center is not None else "",
                "intersection_anchor_y": round(float(center.y), 3) if center is not None else "",
                "signal_to_intersection_anchor_ft": target.get("signal_to_inferred_center_ft", ""),
                "physical_leg_bearing_group": sector,
                "physical_leg_bearing_group_short": short_sector,
                "source_line_ids": _collapse(group["source_line_id"]),
                "source_route_keys": _collapse(group["source_route_key"]),
                "source_route_key_normalized": _collapse(group["source_route_key_normalized"]),
                "source_line_count": len(group),
                "graph_bearing_group_represented": graph_sector_represented,
                "candidate_bearing_group_represented": candidate_sector_represented,
                "candidate_route_overlap": candidate_route_overlap,
                "existing_candidate_bin_overlap_status": existing_overlap_status,
                "route_facility_changes_across_intersection": bool(route_info.get("route_facility_changes_across_intersection", False)),
                "route_key_differs_but_geometry_continuous": bool(route_info.get("route_key_differs_but_geometry_continuous", False)),
                "source_line_split_at_intersection": bool(route_info.get("source_line_split_at_intersection", False)),
                "name_facility_discontinuity_may_explain_missed_scaffold_leg": bool(
                    route_info.get("name_facility_discontinuity_may_explain_missed_scaffold_leg", False)
                ),
                "review_only": True,
                "recovery_method": "intersection_zone_anchor_source_geometry_bearing_group",
            }
        )
        geoms.append(geom)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _generate_bins(leg_candidates: gpd.GeoDataFrame, centers: gpd.GeoDataFrame, signal_points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if leg_candidates.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=CRS)
    center_lookup = centers.drop_duplicates("signal_id").set_index("signal_id").geometry
    signal_lookup = signal_points.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for leg_idx, row in leg_candidates.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", ""))
        center = center_lookup.get(signal_id)
        if center is None:
            continue
        line = _longest_line(row.geometry)
        if line is None or line.length <= 0:
            continue
        center_measure = float(line.project(center))
        centroid_measure = float(line.project(row.geometry.centroid))
        direction = 1 if centroid_measure >= center_measure else -1
        for start_ft in range(0, MAX_RECOVERY_FT, BIN_SIZE_FT):
            end_ft = min(start_ft + BIN_SIZE_FT, MAX_RECOVERY_FT)
            start_m = start_ft / FEET_PER_METER
            end_m = end_ft / FEET_PER_METER
            if direction > 0:
                a = min(max(center_measure + start_m, 0.0), line.length)
                b = min(max(center_measure + end_m, 0.0), line.length)
            else:
                a = min(max(center_measure - end_m, 0.0), line.length)
                b = min(max(center_measure - start_m, 0.0), line.length)
            if math.isclose(a, b):
                continue
            segment = substring(line, min(a, b), max(a, b))
            if segment.is_empty or segment.length * FEET_PER_METER < 10:
                continue
            signal_pt = signal_lookup.get(signal_id)
            rows.append(
                {
                    "signal_id": signal_id,
                    "source_signal_id": row.get("source_signal_id", ""),
                    "offset_zone_recovered_bin_id": f"offset_zone_{signal_id}_{row.get('physical_leg_bearing_group_short', 'sector_unknown')}_leg{leg_idx:04d}_bin{len(rows):06d}",
                    "offset_zone_recovered_leg_id": f"offset_zone_{signal_id}_{row.get('physical_leg_bearing_group_short', 'sector_unknown')}_leg{leg_idx:04d}",
                    "offset_anchor_class": row.get("offset_anchor_class", ""),
                    "recovery_confidence": row.get("recovery_confidence", ""),
                    "original_signal_x": round(float(signal_pt.x), 3) if signal_pt is not None else "",
                    "original_signal_y": round(float(signal_pt.y), 3) if signal_pt is not None else "",
                    "intersection_anchor_x": row.get("intersection_anchor_x", ""),
                    "intersection_anchor_y": row.get("intersection_anchor_y", ""),
                    "signal_to_intersection_anchor_ft": row.get("signal_to_intersection_anchor_ft", ""),
                    "source_line_ids": row.get("source_line_ids", ""),
                    "physical_leg_bearing_group": row.get("physical_leg_bearing_group", ""),
                    "source_route_keys": row.get("source_route_keys", ""),
                    "distance_start_ft": start_ft,
                    "distance_end_ft": end_ft,
                    "distance_band": _distance_band(end_ft),
                    "route_facility_changes_across_intersection": row.get("route_facility_changes_across_intersection", False),
                    "name_facility_discontinuity_may_explain_missed_scaffold_leg": row.get(
                        "name_facility_discontinuity_may_explain_missed_scaffold_leg", False
                    ),
                    "existing_candidate_bin_overlap_status": row.get("existing_candidate_bin_overlap_status", ""),
                    "review_only": True,
                }
            )
            geoms.append(segment)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _signal_summary(targets: pd.DataFrame, legs: gpd.GeoDataFrame, bins: gpd.GeoDataFrame, route_diag: pd.DataFrame) -> pd.DataFrame:
    rows = []
    leg_counts = legs.groupby("signal_id").size() if not legs.empty else pd.Series(dtype=int)
    bin_counts = bins.groupby("signal_id").size() if not bins.empty else pd.Series(dtype=int)
    route_counts = route_diag.groupby("signal_id").agg(
        route_facility_name_change_leg_groups=("route_facility_changes_across_intersection", "sum"),
        name_change_may_explain_missed_scaffold_leg_groups=("name_facility_discontinuity_may_explain_missed_scaffold_leg", "sum"),
    ) if not route_diag.empty else pd.DataFrame()
    for row in targets.itertuples(index=False):
        signal_id = str(row.signal_id)
        route_row = route_counts.loc[signal_id] if signal_id in route_counts.index else None
        rows.append(
            {
                "signal_id": signal_id,
                "source_signal_id": getattr(row, "source_signal_id", ""),
                "offset_anchor_class": getattr(row, "offset_anchor_class", ""),
                "signal_to_inferred_center_ft": getattr(row, "signal_to_inferred_center_ft", ""),
                "source_leg_count": getattr(row, "source_leg_count", ""),
                "graph_reference_leg_count": getattr(row, "graph_reference_leg_count", ""),
                "candidate_bin_leg_count": getattr(row, "candidate_bin_leg_count", ""),
                "recovered_leg_count": int(leg_counts.get(signal_id, 0)),
                "recovered_bin_count": int(bin_counts.get(signal_id, 0)),
                "has_recovered_bins": int(bin_counts.get(signal_id, 0)) > 0,
                "route_facility_name_change_leg_groups": int(route_row["route_facility_name_change_leg_groups"]) if route_row is not None else 0,
                "name_change_may_explain_missed_scaffold_leg_groups": int(route_row["name_change_may_explain_missed_scaffold_leg_groups"]) if route_row is not None else 0,
                "needs_mapped_review_before_refresh": True,
                "signal_002466_seed_case": signal_id == "signal_002466",
            }
        )
    return pd.DataFrame(rows)


def _recovery_summary(targets: pd.DataFrame, legs: gpd.GeoDataFrame, bins: gpd.GeoDataFrame, signal_summary: pd.DataFrame, route_diag: pd.DataFrame) -> pd.DataFrame:
    band_counts = bins["distance_band"].value_counts().to_dict() if not bins.empty else {}
    rows = [
        ("signals_attempted", len(targets), "High/medium offset-anchor candidates only."),
        ("signals_with_recovered_legs", int(signal_summary["recovered_leg_count"].gt(0).sum()), "Signals with at least one review-only recovered leg candidate."),
        ("recovered_physical_legs", len(legs), "Review-only recovered source/bearing leg candidates."),
        ("recovered_bins", len(bins), "Review-only 50-ft bins to 1,000 ft where geometry supports them."),
        ("signals_with_recovered_bins", int(signal_summary["recovered_bin_count"].gt(0).sum()), "Signals with at least one generated recovered bin."),
        ("signals_with_route_facility_name_changes", int(signal_summary["route_facility_name_change_leg_groups"].gt(0).sum()), "Signals with any source leg bearing group containing multiple route/facility keys."),
        ("signals_where_name_change_may_explain_missed_scaffold", int(signal_summary["name_change_may_explain_missed_scaffold_leg_groups"].gt(0).sum()), "Signals where route/facility discontinuity may explain missed/split scaffold."),
        ("signal_002466_recovered_leg_count", int(signal_summary.loc[signal_summary["signal_id"].eq("signal_002466"), "recovered_leg_count"].sum()), "Seed case recovered legs."),
        ("signal_002466_recovered_bin_count", int(signal_summary.loc[signal_summary["signal_id"].eq("signal_002466"), "recovered_bin_count"].sum()), "Seed case recovered bins."),
    ]
    for band in ["0_250ft", "250_500ft", "500_750ft", "750_1000ft"]:
        rows.append((f"recovered_bins_{band}", int(band_counts.get(band, 0)), "Recovered bins by distance band."))
    return pd.DataFrame(rows, columns=["metric", "value", "note"])


def _review_queue(signal_summary: pd.DataFrame) -> pd.DataFrame:
    queue = signal_summary.copy()
    queue["review_priority"] = 3
    queue.loc[queue["signal_002466_seed_case"], "review_priority"] = 1
    queue.loc[queue["recovered_leg_count"].gt(0) & queue["name_change_may_explain_missed_scaffold_leg_groups"].gt(0), "review_priority"] = 2
    queue["recommended_review_question"] = np.where(
        queue["signal_002466_seed_case"],
        "Does the intersection-zone anchor recover the manually observed missing leg pattern?",
        np.where(
            queue["recovered_leg_count"].gt(0),
            "Do recovered source/bearing legs represent defensible scaffold additions?",
            "Why did this high/medium offset candidate not produce recovered legs?",
        ),
    )
    return queue.sort_values(["review_priority", "signal_id"])


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_csv {path.name}", len(frame))


def _write_layer(gdf: gpd.GeoDataFrame, gpkg: Path, layer: str) -> None:
    frame = gdf.copy()
    if frame.empty:
        frame = gpd.GeoDataFrame(frame, geometry="geometry", crs=CRS)
    if frame.crs is None:
        frame = frame.set_crs(CRS)
    else:
        frame = frame.to_crs(CRS)
    frame.to_file(gpkg, layer=layer, driver="GPKG")
    _checkpoint(f"write_layer {layer}", len(frame))


def _write_findings(summary: pd.DataFrame) -> None:
    values = dict(zip(summary["metric"], summary["value"], strict=False))
    text = f"""# Offset / Intersection-Zone Scaffold Recovery Findings

Status: REVIEW-ONLY. This prototype targets only high/medium offset-anchor candidates and writes provisional recovered source-leg and 0-1,000 ft bin records. It does not modify active scaffold, promote candidates, assign access/crashes, calculate rates, or run models.

## Bounded Question

Can intersection-zone anchors recover source Travelway legs missed by signal-point-anchored candidate bins, and do route/facility name changes help explain the missed or split legs?

## Answers

1. High/medium candidates attempted: {values.get('signals_attempted', 0)}; signals producing recovered legs: {values.get('signals_with_recovered_legs', 0)}.
2. Provisional 0-1,000 ft bins generated: {values.get('recovered_bins', 0)}.
3. Signals with route/facility name changes across source leg groups: {values.get('signals_with_route_facility_name_changes', 0)}.
4. Signals where route/facility discontinuity may explain missed scaffold: {values.get('signals_where_name_change_may_explain_missed_scaffold', 0)}.
5. `signal_002466` recovered legs: {values.get('signal_002466_recovered_leg_count', 0)}; recovered bins: {values.get('signal_002466_recovered_bin_count', 0)}.
6. These recovered bins should not feed a refreshed universe until map review confirms the anchor and leg grouping.
7. A separate route-name-change diagnostic is still useful if many recovered legs carry route/facility discontinuity flags.

## Caution

Leg grouping is geometry/bearing-first. Route and facility names are preserved and diagnosed but are not the sole grouping key. Recovered bins are provisional review records only.
"""
    (OUT / "offset_zone_scaffold_recovery_findings.md").write_text(text, encoding="utf-8")
    _checkpoint("write_findings")


def _write_qa(targets: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "Writes only to review/current/offset_intersection_zone_scaffold_recovery/."),
        ("no_candidates_promoted", "pass", "Recovered legs/bins are marked review-only."),
        ("no_access_crash_assignment", "pass", "No access or crash sources are read or assigned."),
        ("no_rates_or_models", "pass", "No rates, denominators, regression, or models are run."),
        ("only_high_medium_offset_candidates_targeted", "pass" if set(targets["offset_anchor_class"].unique()).issubset(TARGET_CLASSES) else "fail", "|".join(sorted(targets["offset_anchor_class"].unique()))),
        ("source_graph_candidate_separate", "pass", "Source Travelway, graph/reference, and candidate bins are separate inputs/layers."),
        ("route_names_not_only_grouping_criterion", "pass", "Leg grouping uses source geometry bearing groups from intersection-zone center."),
        ("recovered_bins_review_only", "pass", "Output records include review_only=True."),
        ("outputs_review_folder_only", "pass", str(OUT)),
    ]
    qa = pd.DataFrame(rows, columns=["qa_check", "status", "note"])
    _write_csv(qa, OUT / "offset_zone_scaffold_recovery_qa.csv")
    return qa


def _write_manifest(outputs: list[str], summary: pd.DataFrame, qa: pd.DataFrame) -> None:
    manifest = {
        "script": "src/active/roadway_graph/offset_intersection_zone_scaffold_recovery.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT),
        "bounded_question": "read-only offset/intersection-zone scaffold recovery prototype for high/medium offset-anchor candidates",
        "parameters": {"primary_radius_ft": PRIMARY_RADIUS_FT, "bin_size_ft": BIN_SIZE_FT, "max_recovery_ft": MAX_RECOVERY_FT, "bearing_sector_width": SECTOR_WIDTH},
        "inputs": {"offset_diagnostic": str(OFFSET_DIAG), "offset_review_gpkg": str(OFFSET_GPKG), "map_review_gpkg": str(MAP_REVIEW_GPKG)},
        "summary": summary.to_dict(orient="records"),
        "outputs": outputs,
        "qa": qa.to_dict(orient="records"),
        "non_goals_confirmed": ["no active scaffold modification", "no candidate promotion", "no access/crash assignment", "no rates/models"],
    }
    (OUT / "offset_zone_scaffold_recovery_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _checkpoint("write_manifest")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start", note="offset intersection-zone scaffold recovery prototype")

    detail = _read_csv(OFFSET_DIAG / "offset_anchor_candidate_detail.csv")
    _read_csv(OFFSET_DIAG / "offset_anchor_class_summary.csv")
    _read_csv(OFFSET_DIAG / "offset_anchor_recovery_estimate.csv")
    _read_csv(OFFSET_DIAG / "offset_anchor_ranked_review_queue.csv")
    targets = detail[detail["offset_anchor_class"].isin(TARGET_CLASSES)].copy()
    _checkpoint("target_filter", len(targets))

    centers = _read_layer(OFFSET_GPKG, "inferred_intersection_zone_centers")
    source_zone = _read_layer(OFFSET_GPKG, "source_travelway_zone_lines")
    graph_zone = _read_layer(OFFSET_GPKG, "graph_reference_zone_lines")
    candidate_zone = _read_layer(OFFSET_GPKG, "current_candidate_bin_zone_lines")
    signal_points = _read_layer(MAP_REVIEW_GPKG, "all_review_signal_points")
    existing_candidate_bins = _read_layer(MAP_REVIEW_GPKG, "existing_candidate_bins")

    target_ids = set(targets["signal_id"].astype(str))
    centers = centers[centers["signal_id"].isin(target_ids)].copy()
    source_zone = source_zone[source_zone["signal_id"].isin(target_ids)].copy()
    graph_zone = graph_zone[graph_zone["signal_id"].isin(target_ids)].copy()
    candidate_zone = candidate_zone[candidate_zone["signal_id"].isin(target_ids)].copy()
    signal_points = signal_points[signal_points["signal_id"].isin(target_ids)].copy()
    existing_candidate_bins = existing_candidate_bins[existing_candidate_bins["signal_id"].isin(target_ids)].copy()

    source_sectors = _source_sector_table(source_zone, centers)
    candidate_sectors = _candidate_sector_table(candidate_zone, centers)
    graph_sectors = _graph_sector_table(graph_zone, centers)
    route_diag = _route_name_change_diagnostic(source_sectors)
    legs = _build_leg_candidates(targets, source_sectors, candidate_sectors, graph_sectors, centers, signal_points, route_diag)
    bins = _generate_bins(legs, centers, signal_points)
    sig_summary = _signal_summary(targets, legs, bins, route_diag)
    rec_summary = _recovery_summary(targets, legs, bins, sig_summary, route_diag)
    queue = _review_queue(sig_summary)

    _write_csv(pd.DataFrame(legs.drop(columns="geometry")), OUT / "offset_zone_recovered_leg_candidates.csv")
    _write_csv(pd.DataFrame(bins.drop(columns="geometry")), OUT / "offset_zone_recovered_bins.csv")
    _write_csv(route_diag, OUT / "offset_zone_route_name_change_diagnostic.csv")
    _write_csv(sig_summary, OUT / "offset_zone_signal_summary.csv")
    _write_csv(rec_summary, OUT / "offset_zone_recovery_summary.csv")
    _write_csv(queue, OUT / "offset_zone_review_queue.csv")

    gpkg = OUT / "offset_zone_scaffold_recovery.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    _write_layer(legs, gpkg, "offset_zone_recovered_leg_candidates")
    _write_layer(bins, gpkg, "offset_zone_recovered_bins")
    _write_layer(centers, gpkg, "intersection_zone_anchor_points")
    _write_layer(signal_points, gpkg, "original_signal_points")
    _write_layer(source_zone, gpkg, "source_travelway_zone_lines")
    _write_layer(graph_zone, gpkg, "graph_reference_zone_lines")
    _write_layer(existing_candidate_bins, gpkg, "existing_candidate_bins")

    _write_findings(rec_summary)
    qa = _write_qa(targets)
    outputs = [
        "offset_zone_recovered_leg_candidates.csv",
        "offset_zone_recovered_bins.csv",
        "offset_zone_route_name_change_diagnostic.csv",
        "offset_zone_signal_summary.csv",
        "offset_zone_recovery_summary.csv",
        "offset_zone_review_queue.csv",
        "offset_zone_scaffold_recovery.gpkg",
        "offset_zone_scaffold_recovery_findings.md",
        "offset_zone_scaffold_recovery_qa.csv",
        "offset_zone_scaffold_recovery_manifest.json",
        "run_progress_log.txt",
    ]
    _write_manifest(outputs, rec_summary, qa)
    _checkpoint("complete", rows=len(targets))


if __name__ == "__main__":
    main()
