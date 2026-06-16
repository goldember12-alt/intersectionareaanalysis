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
OUT = ROOT / "review/current/intersection_zone_missing_leg_recovery_candidates"
TRIAGE = ROOT / "review/current/under_captured_recovery_triage_and_two_leg_audit"
MAP_REVIEW_GPKG = ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg"

CRS = "EPSG:3968"
PRIMARY_RADIUS_FT = 175.0
BIN_SIZE_FT = 50.0
MAX_PRIORITY_FT = 1000.0
MAX_SENSITIVITY_FT = 2500.0
SECTOR_WIDTH = 45
TARGET_CLASS = "ready_for_intersection_zone_missing_leg_recovery"

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

REQUIRED_INPUTS = [
    TRIAGE / "under_captured_975_detail.csv",
    TRIAGE / "under_captured_recovery_class_summary.csv",
    TRIAGE / "under_captured_recovery_potential_estimate.csv",
    TRIAGE / "under_captured_recovery_triage_manifest.json",
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


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_gpkg(frame: gpd.GeoDataFrame, layer: str) -> Path:
    path = OUT / "intersection_zone_missing_leg_recovery_candidates.gpkg"
    if frame.empty:
        _checkpoint(f"skip_empty_layer {layer}", 0)
        return path
    frame.to_file(path, layer=layer, driver="GPKG")
    _checkpoint(f"write_gpkg_layer {layer}", len(frame))
    return path


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
        if text and text not in seen:
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
    if projection <= 0:
        available_forward = line.length
        available_backward = 0.0
    elif projection >= line.length:
        available_forward = 0.0
        available_backward = line.length
    else:
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
    # Reverse so distance increases away from the signal/zone anchor.
    segment = substring(line, start, projection)
    coords = list(segment.coords)
    return LineString(list(reversed(coords))) if len(coords) >= 2 else None


def _bin_geometries(path: LineString, max_distance: float) -> list[tuple[float, float, LineString]]:
    rows: list[tuple[float, float, LineString]] = []
    usable = min(path.length, max_distance)
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


def _selected_signals(triage: pd.DataFrame) -> pd.DataFrame:
    selected = triage.loc[triage["under_capture_triage_class"].eq(TARGET_CLASS)].copy()
    selected["missing_physical_leg_count"] = selected["calibrated_missing_leg_count"].map(_int)
    selected["recovery_rule"] = "intersection_zone_missing_leg_recovery"
    selected["recovery_subreason"] = "source_zone_leg_present_but_scaffold_absent"
    selected["confidence_tier"] = "clean_triage_low_risk_review_candidate"
    return selected


def _source_zone_table(
    selected: pd.DataFrame,
    signal_points: gpd.GeoDataFrame,
    source: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    points = signal_points.loc[signal_points["signal_id"].isin(set(selected["signal_id"]))].copy()
    points = points[["signal_id", "source_signal_id", "source_layer", "geometry"]].drop_duplicates("signal_id")
    zones = points.copy()
    zones["geometry"] = zones.geometry.buffer(PRIMARY_RADIUS_FT)
    joined = gpd.sjoin(source.reset_index(drop=True), zones[["signal_id", "geometry"]], how="inner", predicate="intersects")
    if joined.empty:
        return gpd.GeoDataFrame(columns=["signal_id", "source_bearing_sector", "geometry"], geometry="geometry", crs=CRS)
    point_lookup = points.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for idx, row in joined.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", "")).strip()
        anchor = point_lookup.get(signal_id)
        line = _longest_line(row.geometry)
        if anchor is None or line is None:
            continue
        bearing = _bearing_from_point(anchor, line)
        sector = _bearing_sector(bearing)
        rows.append(
            {
                "signal_id": signal_id,
                "source_zone_row_id": idx,
                "source_line_id": _source_line_id(row, idx),
                "source_bearing_sector": sector,
                "source_bearing_degrees": round(float(bearing), 3) if np.isfinite(bearing) else "",
                "source_route_key": _route_key_from_source(row),
                "source_route_key_normalized": _normalize_key(_route_key_from_source(row)),
                "source_rte_nm": str(row.get("RTE_NM", "")).strip(),
                "source_rte_common": str(row.get("RTE_COMMON", "")).strip(),
                "source_rte_id": str(row.get("RTE_ID", "")).strip(),
                "source_facility": str(row.get("RIM_FACI_1", "")).strip(),
                "source_event_source": str(row.get("EVENT_SOUR", "")).strip(),
                "source_from_measure": str(row.get("FROM_MEASURE", "")).strip(),
                "source_to_measure": str(row.get("TO_MEASURE", "")).strip(),
                "source_zone_intersection_length_ft": round(float(row.geometry.intersection(zones.loc[zones["signal_id"].eq(signal_id)].iloc[0].geometry).length), 3),
                "source_line_total_length_ft": round(float(row.geometry.length), 3),
            }
        )
        geoms.append(row.geometry)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _candidate_sector_table(selected: pd.DataFrame, signal_points: gpd.GeoDataFrame, candidate_bins: gpd.GeoDataFrame) -> pd.DataFrame:
    bins = candidate_bins.loc[candidate_bins["signal_id"].isin(set(selected["signal_id"]))].copy()
    if bins.empty:
        return pd.DataFrame(columns=["signal_id", "candidate_bearing_sector"])
    point_lookup = signal_points.drop_duplicates("signal_id").set_index("signal_id").geometry
    rows: list[dict[str, Any]] = []
    for idx, row in bins.reset_index(drop=True).iterrows():
        signal_id = str(row.get("signal_id", "")).strip()
        anchor = point_lookup.get(signal_id)
        line = _longest_line(row.geometry)
        if anchor is None or line is None:
            continue
        bearing = _bearing_from_point(anchor, line)
        rows.append(
            {
                "signal_id": signal_id,
                "candidate_zone_row_id": idx,
                "candidate_bearing_sector": _bearing_sector(bearing),
                "candidate_bearing_degrees": round(float(bearing), 3) if np.isfinite(bearing) else "",
                "candidate_route_key": str(row.get("route_or_facility_key", "")).strip(),
                "candidate_bin_id": str(row.get("target_bin_id", "")).strip(),
                "candidate_physical_leg_cluster_id": str(row.get("physical_leg_cluster_id", "")).strip(),
                "candidate_association_id": str(row.get("candidate_association_id", "")).strip(),
            }
        )
    return pd.DataFrame(rows)


def _build_leg_candidates(
    selected: pd.DataFrame,
    source_zone: gpd.GeoDataFrame,
    candidate_sectors: pd.DataFrame,
    signal_points: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    existing_by_signal = (
        candidate_sectors.groupby("signal_id")["candidate_bearing_sector"].apply(lambda values: set(values.dropna().astype(str))).to_dict()
        if not candidate_sectors.empty
        else {}
    )
    point_lookup = signal_points.drop_duplicates("signal_id").set_index("signal_id").geometry
    selected_lookup = selected.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")

    leg_rows: list[dict[str, Any]] = []
    leg_geoms: list[Any] = []
    skipped: list[dict[str, Any]] = []

    for signal_id, group in source_zone.groupby("signal_id", sort=False):
        triage = selected_lookup.get(signal_id, {})
        missing_count = _int(triage.get("missing_physical_leg_count"))
        existing = existing_by_signal.get(signal_id, set())
        source_sectors = [sector for sector in group["source_bearing_sector"].dropna().astype(str).unique().tolist() if sector != "unknown"]
        missing_sectors = [sector for sector in source_sectors if sector not in existing]
        if missing_count <= 0:
            skipped.append({"signal_id": signal_id, "skip_reason": "no_missing_leg_count", "missing_sector_count": len(missing_sectors), "calibrated_missing_leg_count": missing_count})
            continue
        if not missing_sectors:
            skipped.append({"signal_id": signal_id, "skip_reason": "no_source_sector_absent_from_candidate_bins", "missing_sector_count": 0, "calibrated_missing_leg_count": missing_count})
            continue

        sector_stats = (
            group.loc[group["source_bearing_sector"].isin(missing_sectors)]
            .groupby("source_bearing_sector", dropna=False)
            .agg(
                source_line_count=("source_line_id", "nunique"),
                source_route_group_count=("source_route_key_normalized", "nunique"),
                source_route_keys=("source_route_key", lambda values: _collapse(values)),
                source_line_ids=("source_line_id", lambda values: _collapse(values)),
                source_zone_intersection_length_ft=("source_zone_intersection_length_ft", "sum"),
                source_line_total_length_ft=("source_line_total_length_ft", "max"),
            )
            .reset_index()
        )
        sector_stats = sector_stats.sort_values(
            ["source_zone_intersection_length_ft", "source_line_total_length_ft", "source_line_count"],
            ascending=[False, False, False],
        )
        selected_sectors = sector_stats.head(missing_count).copy()
        if len(missing_sectors) > missing_count:
            selection_status = "more_absent_source_sectors_than_calibrated_missing_count_selected_top_length"
        elif len(missing_sectors) < missing_count:
            selection_status = "fewer_absent_source_sectors_than_calibrated_missing_count_partial_recovery"
        else:
            selection_status = "absent_source_sector_count_matches_calibrated_missing_count"

        for leg_index, row in selected_sectors.reset_index(drop=True).iterrows():
            sector = str(row["source_bearing_sector"])
            sector_lines = group.loc[group["source_bearing_sector"].eq(sector)].copy()
            if sector_lines.empty:
                continue
            source_line = sector_lines.sort_values(["source_zone_intersection_length_ft", "source_line_total_length_ft"], ascending=False).iloc[0]
            line = _longest_line(source_line.geometry)
            anchor = point_lookup.get(signal_id)
            outward = _outward_segment(line, anchor, MAX_SENSITIVITY_FT) if line is not None and anchor is not None else None
            if outward is None:
                skipped.append(
                    {
                        "signal_id": signal_id,
                        "candidate_missing_leg_id": f"missing_leg::{signal_id}::{sector}",
                        "skip_reason": "source_line_could_not_generate_outward_segment",
                        "missing_sector_count": len(missing_sectors),
                        "calibrated_missing_leg_count": missing_count,
                    }
                )
                continue
            leg_rows.append(
                {
                    "candidate_missing_leg_id": f"missing_leg::{signal_id}::{leg_index + 1:02d}::{sector}",
                    "signal_id": signal_id,
                    "source_signal_id": triage.get("source_signal_id_x", ""),
                    "source_layer": triage.get("source_layer_x", ""),
                    "source_bearing_sector": sector,
                    "source_line_ids": row["source_line_ids"],
                    "primary_source_line_id": source_line["source_line_id"],
                    "source_route_keys": row["source_route_keys"],
                    "source_route_group_count": int(row["source_route_group_count"]),
                    "candidate_existing_sector_count": len(existing),
                    "source_absent_sector_count": len(missing_sectors),
                    "calibrated_expected_physical_leg_count": triage.get("calibrated_expected_physical_leg_count", ""),
                    "current_refreshed_physical_leg_count": triage.get("current_refreshed_physical_leg_count", ""),
                    "calibrated_missing_leg_count": missing_count,
                    "source_bearing_count": triage.get("source_bearing_count", ""),
                    "source_bearing_groups": triage.get("source_bearing_groups", ""),
                    "recovery_rule": "intersection_zone_missing_leg_recovery",
                    "recovery_subreason": "source_zone_leg_present_but_scaffold_absent",
                    "selection_status": selection_status,
                    "confidence_tier": "clean_triage_low_risk_review_candidate",
                    "review_only": True,
                    "candidate_promoted": False,
                    "candidate_generation_method": "source_travelway_175ft_zone_missing_bearing_sector",
                    "available_recovered_length_ft": round(float(outward.length), 3),
                    "generates_full_0_1000ft_window": bool(outward.length >= MAX_PRIORITY_FT - 0.01),
                    "generates_1000_2500ft_sensitivity": bool(outward.length > MAX_PRIORITY_FT + 0.01),
                }
            )
            leg_geoms.append(outward)

    selected_ids = set(selected["signal_id"])
    seen_ids = set(source_zone["signal_id"]) if not source_zone.empty else set()
    for signal_id in sorted(selected_ids - seen_ids):
        skipped.append({"signal_id": signal_id, "skip_reason": "no_source_travelway_line_intersected_175ft_zone", "missing_sector_count": 0, "calibrated_missing_leg_count": selected_lookup.get(signal_id, {}).get("missing_physical_leg_count", "")})

    legs = gpd.GeoDataFrame(leg_rows, geometry=leg_geoms, crs=CRS)
    skipped_frame = pd.DataFrame(skipped)
    return legs, skipped_frame


def _build_bins(legs: gpd.GeoDataFrame, max_distance: float, window_name: str) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for _, leg in legs.iterrows():
        path = _longest_line(leg.geometry)
        if path is None:
            continue
        for bin_index, (start, end, geom) in enumerate(_bin_geometries(path, max_distance), start=1):
            if window_name == "0_1000" and start >= 1000:
                continue
            if window_name == "1000_2500" and end <= 1000:
                continue
            if window_name == "1000_2500" and start < 1000:
                continue
            rows.append(
                {
                    "candidate_missing_leg_bin_id": f"{leg['candidate_missing_leg_id']}::bin_{int(start):04d}_{int(end):04d}",
                    "candidate_missing_leg_id": leg["candidate_missing_leg_id"],
                    "signal_id": leg["signal_id"],
                    "source_signal_id": leg["source_signal_id"],
                    "source_layer": leg["source_layer"],
                    "source_bearing_sector": leg["source_bearing_sector"],
                    "primary_source_line_id": leg["primary_source_line_id"],
                    "source_route_keys": leg["source_route_keys"],
                    "distance_start_ft": start,
                    "distance_end_ft": end,
                    "bin_length_ft": round(end - start, 3),
                    "distance_band": _distance_band(end),
                    "analysis_window": _analysis_window(start, end),
                    "recovery_rule": leg["recovery_rule"],
                    "recovery_subreason": leg["recovery_subreason"],
                    "confidence_tier": leg["confidence_tier"],
                    "review_only": True,
                    "candidate_promoted": False,
                    "partial_bin_flag": bool((end - start) < BIN_SIZE_FT - 0.01),
                    "candidate_generation_method": "source_travelway_outward_substring_50ft_bins",
                }
            )
            geoms.append(geom)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def _signal_summary(selected: pd.DataFrame, legs: gpd.GeoDataFrame, bins_0_1000: gpd.GeoDataFrame, bins_1000_2500: gpd.GeoDataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "signal_id",
        "source_signal_id_x",
        "source_layer_x",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "calibrated_missing_leg_count",
        "source_bearing_count",
        "candidate_branch_count",
        "carriageway_subbranch_count",
        "source_bearing_groups",
        "source_route_groups",
        "under_capture_triage_class",
    ]
    summary = selected[[column for column in base_cols if column in selected.columns]].copy()
    if not legs.empty:
        leg_counts = legs.groupby("signal_id").agg(
            recovered_candidate_leg_count=("candidate_missing_leg_id", "nunique"),
            recovered_full_0_1000_leg_count=("generates_full_0_1000ft_window", "sum"),
            recovered_sensitivity_leg_count=("generates_1000_2500ft_sensitivity", "sum"),
            recovery_selection_statuses=("selection_status", lambda values: _collapse(values)),
        ).reset_index()
        summary = summary.merge(leg_counts, on="signal_id", how="left")
    if not bins_0_1000.empty:
        bin_counts = bins_0_1000.groupby("signal_id").size().reset_index(name="candidate_bins_0_1000")
        summary = summary.merge(bin_counts, on="signal_id", how="left")
    if not bins_1000_2500.empty:
        sens_counts = bins_1000_2500.groupby("signal_id").size().reset_index(name="candidate_bins_1000_2500")
        summary = summary.merge(sens_counts, on="signal_id", how="left")
    if not skipped.empty:
        skip_counts = skipped.groupby("signal_id").agg(skipped_target_count=("signal_id", "size"), skip_reasons=("skip_reason", lambda values: _collapse(values))).reset_index()
        summary = summary.merge(skip_counts, on="signal_id", how="left")
    for column in ["recovered_candidate_leg_count", "recovered_full_0_1000_leg_count", "recovered_sensitivity_leg_count", "candidate_bins_0_1000", "candidate_bins_1000_2500", "skipped_target_count"]:
        if column not in summary.columns:
            summary[column] = 0
        summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0).astype(int)
    summary["candidate_generation_status"] = np.where(
        summary["recovered_candidate_leg_count"].gt(0),
        "candidate_generated",
        "no_candidate_generated_review_needed",
    )
    return summary.sort_values(["candidate_generation_status", "calibrated_missing_leg_count"], ascending=[True, False])


def _qa_summary(selected: pd.DataFrame, legs: gpd.GeoDataFrame, bins_0_1000: gpd.GeoDataFrame, bins_1000_2500: gpd.GeoDataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    expected = 263
    duplicate_legs = 0 if legs.empty else int(legs["candidate_missing_leg_id"].duplicated().sum())
    selected_count = int(selected["signal_id"].nunique())
    generated_signal_count = 0 if legs.empty else int(legs["signal_id"].nunique())
    skipped_signal_count = int(selected_count - generated_signal_count)
    return pd.DataFrame(
        [
            {"qa_check": "expected_ready_class_signal_count_from_prior_audit", "passed": selected_count == expected, "observed": selected_count, "expected": expected, "note": "Count differs only if upstream triage output changed."},
            {"qa_check": "selected_only_ready_for_intersection_zone_missing_leg_recovery", "passed": bool(selected["under_capture_triage_class"].eq(TARGET_CLASS).all()), "observed": int((~selected["under_capture_triage_class"].eq(TARGET_CLASS)).sum()), "expected": 0, "note": "No other under-capture classes targeted."},
            {"qa_check": "candidate_recovered_physical_legs", "passed": len(legs) > 0, "observed": int(len(legs)), "expected": "positive", "note": "Review-only candidate legs generated from absent source bearing sectors."},
            {"qa_check": "candidate_bins_0_1000", "passed": len(bins_0_1000) > 0, "observed": int(len(bins_0_1000)), "expected": "positive", "note": "50-ft review-only bins for priority window."},
            {"qa_check": "candidate_bins_1000_2500_sensitivity", "passed": True, "observed": int(len(bins_1000_2500)), "expected": "optional", "note": "Generated as sensitivity only where source geometry supports it."},
            {"qa_check": "signals_with_no_candidate_generated_reported", "passed": True, "observed": skipped_signal_count, "expected": "reported", "note": "Nonzero means source/candidate sector evidence was insufficient for some selected signals; targets are preserved for review instead of fabricated."},
            {"qa_check": "duplicate_candidate_leg_ids", "passed": duplicate_legs == 0, "observed": duplicate_legs, "expected": 0, "note": "Candidate leg IDs should be unique."},
            {"qa_check": "records_review_only_not_promoted", "passed": bool(legs.empty or (legs["review_only"].eq(True).all() and legs["candidate_promoted"].eq(False).all())), "observed": 0, "expected": 0, "note": "No active scaffold promotion occurs."},
            {"qa_check": "no_access_crash_rates_models", "passed": True, "observed": 0, "expected": 0, "note": "Script reads only triage and roadway/source geometry packages."},
            {"qa_check": "outputs_written_only_to_review_folder", "passed": str(OUT).replace('\\', '/').endswith("review/current/intersection_zone_missing_leg_recovery_candidates"), "observed": str(OUT), "expected": "review/current/intersection_zone_missing_leg_recovery_candidates", "note": "Review-only output folder."},
        ]
    )


def _readme(summary: pd.DataFrame, qa: pd.DataFrame, sensitivity_generated: bool) -> str:
    selected = int(qa.loc[qa["qa_check"].eq("expected_ready_class_signal_count_from_prior_audit"), "observed"].iloc[0])
    legs = int(qa.loc[qa["qa_check"].eq("candidate_recovered_physical_legs"), "observed"].iloc[0])
    bins = int(qa.loc[qa["qa_check"].eq("candidate_bins_0_1000"), "observed"].iloc[0])
    skipped = int(qa.loc[qa["qa_check"].eq("signals_with_no_candidate_generated_reported"), "observed"].iloc[0])
    lines = [
        "# Intersection-Zone Missing-Leg Recovery Candidates",
        "",
        "Bounded question: generate review-only candidate missing physical legs and 50-ft bins for the clean `ready_for_intersection_zone_missing_leg_recovery` pool.",
        "",
        "This package does not promote candidates, modify active scaffold, assign access or crashes, calculate rates, or run models.",
        "",
        "## Counts",
        "",
        f"- Ready-class signals expected from triage: 263.",
        f"- Selected signals loaded by this script: {selected:,}.",
        f"- Candidate recovered physical legs: {legs:,}.",
        f"- Candidate 0-1,000 ft bins: {bins:,}.",
        f"- Signals with no candidate generated: {skipped:,}.",
        f"- 1,000-2,500 ft sensitivity bins generated: {'yes' if sensitivity_generated else 'no'}.",
        "",
        "## Recovery Rule",
        "",
        "`intersection_zone_missing_leg_recovery` selects source Travelway bearing sectors inside a 175-ft signal zone that are absent from current candidate-bin bearing sectors. Candidate bins are generated as source-geometry substrings outward from the signal point at 50-ft intervals.",
        "",
        "## Deferred Classes",
        "",
        "This pass intentionally defers divided carriageway/subbranch normalization, route/facility discontinuity handling, offset-anchor recovery, and suspicious two-leg-or-less cases.",
    ]
    return "\n".join(lines) + "\n"


def _manifest(outputs: list[Path], row_counts: dict[str, int], started: str) -> dict[str, Any]:
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "started_utc": started,
        "script": "src/active/roadway_graph/intersection_zone_missing_leg_recovery_candidates.py",
        "output_dir": str(OUT),
        "read_only_review_candidate_outputs": True,
        "candidate_generation_scope": TARGET_CLASS,
        "primary_radius_ft": PRIMARY_RADIUS_FT,
        "bin_size_ft": BIN_SIZE_FT,
        "priority_window_ft": [0, 1000],
        "sensitivity_window_ft": [1000, 2500],
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [str(path) for path in outputs],
        "row_counts": row_counts,
        "non_goals_confirmed": [
            "no_access_assignment",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_candidate_promotion",
            "no_active_scaffold_modification",
            "no_two_leg_or_less_recovery",
            "no_offset_anchor_recovery",
            "no_route_facility_discontinuity_recovery",
            "no_divided_subbranch_normalization",
        ],
    }


def main() -> None:
    started = datetime.now(timezone.utc).isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    missing_inputs = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing_inputs))

    triage = _read_csv(TRIAGE / "under_captured_975_detail.csv")
    selected = _selected_signals(triage)
    _checkpoint("selected_ready_class_signals", selected["signal_id"].nunique())

    signal_points = _read_layer(MAP_REVIEW_GPKG, "review_signal_points")
    candidate_bins = _read_layer(MAP_REVIEW_GPKG, "review_candidate_bins")
    source = _read_layer(MAP_REVIEW_GPKG, "source_travelway_full")

    selected_ids = set(selected["signal_id"])
    signal_points = signal_points.loc[signal_points["signal_id"].isin(selected_ids)].copy()
    source_zone = _source_zone_table(selected, signal_points, source)
    candidate_sectors = _candidate_sector_table(selected, signal_points, candidate_bins)
    legs, skipped = _build_leg_candidates(selected, source_zone, candidate_sectors, signal_points)
    bins_0_1000 = _build_bins(legs, MAX_PRIORITY_FT, "0_1000")
    bins_1000_2500 = _build_bins(legs, MAX_SENSITIVITY_FT, "1000_2500")
    signal_summary = _signal_summary(selected, legs, bins_0_1000, bins_1000_2500, skipped)
    qa = _qa_summary(selected, legs, bins_0_1000, bins_1000_2500, skipped)

    outputs: list[Path] = []
    leg_csv = OUT / "recovered_missing_physical_leg_candidates.csv"
    pd.DataFrame(legs.drop(columns="geometry", errors="ignore")).to_csv(leg_csv, index=False)
    outputs.append(leg_csv)
    _checkpoint("write recovered_missing_physical_leg_candidates.csv", len(legs))

    bins_0_csv = OUT / "recovered_missing_leg_candidate_bins_0_1000.csv"
    pd.DataFrame(bins_0_1000.drop(columns="geometry", errors="ignore")).to_csv(bins_0_csv, index=False)
    outputs.append(bins_0_csv)
    _checkpoint("write recovered_missing_leg_candidate_bins_0_1000.csv", len(bins_0_1000))

    bins_sens_csv = OUT / "recovered_missing_leg_candidate_bins_1000_2500.csv"
    pd.DataFrame(bins_1000_2500.drop(columns="geometry", errors="ignore")).to_csv(bins_sens_csv, index=False)
    outputs.append(bins_sens_csv)
    _checkpoint("write recovered_missing_leg_candidate_bins_1000_2500.csv", len(bins_1000_2500))

    outputs.append(_write_csv(signal_summary, "selected_signal_summary.csv"))
    outputs.append(_write_csv(qa, "candidate_generation_qa_summary.csv"))
    outputs.append(_write_csv(skipped, "skipped_or_conflicting_recovery_targets.csv"))

    gpkg = _write_gpkg(legs, "recovered_missing_physical_leg_candidates")
    _write_gpkg(bins_0_1000, "recovered_missing_leg_candidate_bins_0_1000")
    _write_gpkg(bins_1000_2500, "recovered_missing_leg_candidate_bins_1000_2500")
    outputs.append(gpkg)

    readme_path = OUT / "README.md"
    readme_path.write_text(_readme(signal_summary, qa, not bins_1000_2500.empty), encoding="utf-8")
    outputs.append(readme_path)
    _checkpoint("write README.md")

    row_counts = {
        "selected_signals": int(selected["signal_id"].nunique()),
        "candidate_recovered_legs": int(len(legs)),
        "candidate_bins_0_1000": int(len(bins_0_1000)),
        "candidate_bins_1000_2500": int(len(bins_1000_2500)),
        "signals_with_candidates": int(legs["signal_id"].nunique()) if not legs.empty else 0,
        "signals_with_no_candidates": int(selected["signal_id"].nunique() - (legs["signal_id"].nunique() if not legs.empty else 0)),
        "skipped_or_conflicting_records": int(len(skipped)),
    }
    manifest_path = OUT / "intersection_zone_missing_leg_recovery_candidates_manifest.json"
    manifest_path.write_text(json.dumps(_manifest(outputs, row_counts, started), indent=2), encoding="utf-8")
    outputs.append(manifest_path)
    _checkpoint("write manifest")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
