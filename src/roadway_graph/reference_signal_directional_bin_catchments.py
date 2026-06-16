from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString, Polygon

from .crs_utils import (
    CATCHMENT_CRS_METADATA_FILE,
    WORKING_CRS_AUTHORITY,
    coordinate_profile,
    crs_sanity_frame,
    write_crs_metadata,
)


OUTPUT_ROOT = Path("work/output/roadway_graph")
QA_INPUT_DIR = Path("review/current/reference_signal_directional_scaffold_qa")
CATCHMENT_DIR = Path("review/current/reference_signal_directional_bin_catchments")

FEET_PER_METER = 3.280839895
CATCHMENT_WIDTH_FT = 35.0
MIN_LOCAL_VECTOR_FT = 10.0
SHARP_KINK_DEGREES = 45.0

USABLE_SEGMENTS = "directional_scaffold_prototype_usable_segments.csv"
USABLE_BINS = "directional_scaffold_prototype_usable_bins_50ft.csv"
BASE_BINS = "signal_oriented_segment_bins_50ft_crash_ready.csv"

INDEX_COLUMNS = [
    "catchment_id",
    "reference_directional_bin_id",
    "reference_directional_segment_id",
    "base_segment_id",
    "reference_signal_id",
    "far_anchor_id",
    "roadway_representation_type",
    "travel_direction",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_start_ft_from_reference_signal",
    "bin_end_ft_from_reference_signal",
    "catchment_method",
    "local_vector_method",
    "local_bearing_degrees",
    "side_relative_to_reference_to_anchor",
    "catchment_width_ft",
    "catchment_status",
    "catchment_confidence",
    "catchment_blocker_reason",
    "review_flag",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_wkt_csv(path: Path) -> gpd.GeoDataFrame:
    frame = _read_csv(path)
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=[], crs=WORKING_CRS_AUTHORITY)
    frame["geometry"] = frame["geometry"].map(lambda value: wkt.loads(value) if str(value).strip() else None)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=WORKING_CRS_AUTHORITY)


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns:
        out["geometry"] = out["geometry"].map(lambda geom: geom.wkt if hasattr(geom, "wkt") else "")
    out.to_csv(path, index=False)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        return
    frame.to_file(path, driver="GeoJSON")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _bearing_degrees(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return None
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _angular_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _line_coords_2d(geometry) -> list[tuple[float, float]]:
    if geometry is None or geometry.is_empty or not hasattr(geometry, "coords"):
        return []
    return [(float(coord[0]), float(coord[1])) for coord in geometry.coords]


def _oriented_bin_geometry(geometry, travel_direction: str):
    if geometry is None or geometry.is_empty:
        return geometry
    coords = _line_coords_2d(geometry)
    if len(coords) < 2:
        return geometry
    return LineString(coords)


def _side_polygon_from_local_vector(geometry, *, side: str, width_m: float):
    coords = _line_coords_2d(geometry)
    if len(coords) < 2:
        return None
    start = coords[0]
    end = coords[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return None
    ux = dx / length
    uy = dy / length
    if side == "left":
        px = -uy
        py = ux
    elif side == "right":
        px = uy
        py = -ux
    else:
        return None
    polygon = Polygon(
        [
            (start[0], start[1]),
            (end[0], end[1]),
            (end[0] + px * width_m, end[1] + py * width_m),
            (start[0] + px * width_m, start[1] + py * width_m),
            (start[0], start[1]),
        ]
    )
    return polygon if not polygon.is_empty else None


def _local_vector_qa(geometry) -> dict[str, object]:
    coords = _line_coords_2d(geometry)
    if len(coords) < 2:
        return {
            "local_vector_method": "line_endpoint_vector",
            "local_vector_length_ft": 0.0,
            "local_bearing_degrees": "",
            "max_internal_bearing_change_degrees": "",
            "local_vector_status": "blocked",
            "local_vector_blocker_reason": "invalid_or_empty_bin_geometry",
        }
    start = coords[0]
    end = coords[-1]
    length_ft = LineString(coords).length * FEET_PER_METER
    bearing = _bearing_degrees(start, end)
    segment_bearings = []
    for a, b in zip(coords[:-1], coords[1:]):
        seg_bearing = _bearing_degrees(a, b)
        if seg_bearing is not None:
            segment_bearings.append(seg_bearing)
    max_change = 0.0
    if len(segment_bearings) > 1:
        max_change = max(_angular_diff(a, b) for a, b in zip(segment_bearings[:-1], segment_bearings[1:]))
    reasons: list[str] = []
    if length_ft < MIN_LOCAL_VECTOR_FT or bearing is None:
        reasons.append("local_vector_too_short")
    if max_change > SHARP_KINK_DEGREES:
        reasons.append("sharp_bearing_change_or_kink")
    status = "usable" if not reasons else "unstable_review"
    return {
        "local_vector_method": "line_endpoint_vector",
        "local_vector_length_ft": round(length_ft, 3),
        "local_bearing_degrees": "" if bearing is None else round(bearing, 3),
        "max_internal_bearing_change_degrees": round(max_change, 3),
        "local_vector_status": status,
        "local_vector_blocker_reason": "|".join(reasons),
    }


def _merge_geometry(usable_bins: pd.DataFrame, base_bins: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    bins = usable_bins.copy()
    if "bin_index_in_travel_direction" in bins.columns:
        bins["_bin_index_zero_based"] = _num(bins, "bin_index_in_travel_direction").fillna(0).astype(int) - 1
    else:
        bins["_bin_index_zero_based"] = _num(bins, "bin_index_from_reference_signal").fillna(0).astype(int) - 1
    base = base_bins.copy()
    base["_bin_index_zero_based"] = _num(base, "bin_index").fillna(0).astype(int)
    keep = ["oriented_segment_id", "_bin_index_zero_based", "geometry"]
    merged = bins.merge(
        base[keep],
        left_on=["base_segment_id", "_bin_index_zero_based"],
        right_on=["oriented_segment_id", "_bin_index_zero_based"],
        how="left",
    )
    return gpd.GeoDataFrame(merged.drop(columns=["oriented_segment_id"], errors="ignore"), geometry="geometry", crs=base_bins.crs)


def _geometry_join_success_qa(usable_bins: pd.DataFrame, merged: gpd.GeoDataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for representation, group in merged.groupby("roadway_representation_type", dropna=False):
        has_geometry = group.geometry.notna() & ~group.geometry.is_empty
        rows.append(
            {
                "roadway_representation_type": representation,
                "input_rows": int(len(group)),
                "rows_with_source_bin_geometry": int(has_geometry.sum()),
                "rows_missing_source_bin_geometry": int((~has_geometry).sum()),
                "geometry_join_success_rate": round(float(has_geometry.mean()), 6) if len(group) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _build_catchments(usable_bins: pd.DataFrame, base_bins: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    merged = _merge_geometry(usable_bins, base_bins)
    geometry_join_qa = _geometry_join_success_qa(usable_bins, merged)
    max_bin = (
        merged.groupby("reference_directional_segment_id")["bin_index_from_reference_signal"]
        .apply(lambda values: pd.to_numeric(values, errors="coerce").max())
        .to_dict()
    )
    width_m = CATCHMENT_WIDTH_FT / FEET_PER_METER
    records: list[dict[str, object]] = []
    geometries = []
    vector_rows: list[dict[str, object]] = []
    polygon_stage_rows: list[dict[str, object]] = []

    for row in merged.itertuples(index=False):
        row_dict = row._asdict()
        geom = row_dict.get("geometry")
        representation = str(row_dict.get("roadway_representation_type", ""))
        travel_direction = str(row_dict.get("travel_direction", ""))
        local_geom = _oriented_bin_geometry(geom, travel_direction) if representation == "undivided_centerline_pseudo_direction" else geom
        vector = _local_vector_qa(local_geom)
        bin_index = int(pd.to_numeric(pd.Series([row_dict.get("bin_index_from_reference_signal")]), errors="coerce").fillna(0).iloc[0])
        segment_id = str(row_dict.get("reference_directional_segment_id", ""))
        near_anchor = bin_index == 1 or bin_index == int(max_bin.get(segment_id, 0))
        reasons = [reason for reason in str(vector["local_vector_blocker_reason"]).split("|") if reason]
        if near_anchor and representation == "undivided_centerline_pseudo_direction":
            reasons.append("near_reference_or_far_anchor")

        if representation == "divided_physical_carriageway":
            method = "divided_physical_bin_buffer"
            side = "both_sides_physical_bin"
            polygon = geom.buffer(width_m, cap_style=2, join_style=2) if geom is not None else None
        elif representation == "undivided_centerline_pseudo_direction":
            method = "undivided_local_vector_side_polygon_rectangle"
            # Use explicit 2D side polygons. This avoids fragile export behavior from
            # 3D single-sided buffers and keeps the side assignment tied to the local vector.
            if travel_direction == "reference_to_anchor":
                side = "right"
            else:
                side = "left"
            polygon = _side_polygon_from_local_vector(local_geom, side=side, width_m=width_m)
        else:
            method = "blocked"
            side = "blocked_or_unknown"
            polygon = None
            reasons.append("unsupported_roadway_representation_type")

        if polygon is None or polygon.is_empty:
            reasons.append("empty_catchment_geometry")
        catchment_id = f"catch_{row_dict.get('reference_directional_bin_id')}"
        polygon_stage_rows.append(
            {
                "catchment_id": catchment_id,
                "reference_directional_bin_id": row_dict.get("reference_directional_bin_id", ""),
                "roadway_representation_type": representation,
                "travel_direction": travel_direction,
                "source_geometry_present": geom is not None and not getattr(geom, "is_empty", True),
                "local_vector_status": vector["local_vector_status"],
                "constructed_polygon_present": polygon is not None and not getattr(polygon, "is_empty", True),
                "constructed_polygon_valid": bool(polygon.is_valid) if polygon is not None and not polygon.is_empty else False,
                "constructed_polygon_area_sq_m": round(float(polygon.area), 6) if polygon is not None and not polygon.is_empty else 0.0,
            }
        )

        status = "usable"
        if "empty_catchment_geometry" in reasons or "unsupported_roadway_representation_type" in reasons or "local_vector_too_short" in reasons:
            status = "blocked"
        elif reasons:
            status = "unstable_review"
        confidence = "high" if representation == "divided_physical_carriageway" and status == "usable" else "medium"
        if status == "unstable_review":
            confidence = "review"
        if status == "blocked":
            confidence = "blocked"

        record = {
            "catchment_id": catchment_id,
            "reference_directional_bin_id": row_dict.get("reference_directional_bin_id", ""),
            "reference_directional_segment_id": segment_id,
            "base_segment_id": row_dict.get("base_segment_id", ""),
            "reference_signal_id": row_dict.get("reference_signal_id", ""),
            "far_anchor_id": row_dict.get("far_anchor_id", ""),
            "roadway_representation_type": representation,
            "travel_direction": travel_direction,
            "signal_relative_direction": row_dict.get("signal_relative_direction", ""),
            "bin_index_from_reference_signal": row_dict.get("bin_index_from_reference_signal", ""),
            "bin_start_ft_from_reference_signal": row_dict.get("bin_start_ft_from_reference_signal", ""),
            "bin_end_ft_from_reference_signal": row_dict.get("bin_end_ft_from_reference_signal", ""),
            "catchment_method": method,
            "local_vector_method": vector["local_vector_method"],
            "local_bearing_degrees": vector["local_bearing_degrees"],
            "side_relative_to_reference_to_anchor": side,
            "catchment_width_ft": CATCHMENT_WIDTH_FT,
            "catchment_status": status,
            "catchment_confidence": confidence,
            "catchment_blocker_reason": "|".join(dict.fromkeys(reasons)),
            "review_flag": "TRUE" if status != "usable" else "FALSE",
        }
        records.append(record)
        geometries.append(polygon)
        vector_rows.append(
            {
                "catchment_id": catchment_id,
                "reference_directional_bin_id": record["reference_directional_bin_id"],
                "reference_directional_segment_id": segment_id,
                "roadway_representation_type": representation,
                "travel_direction": travel_direction,
                "bin_index_from_reference_signal": record["bin_index_from_reference_signal"],
                **vector,
                "near_reference_or_far_anchor": "TRUE" if near_anchor else "FALSE",
                "catchment_status": status,
                "catchment_blocker_reason": record["catchment_blocker_reason"],
            }
        )

    catchments = gpd.GeoDataFrame(records, geometry=geometries, crs=base_bins.crs)
    stage_counts = _catchment_geometry_stage_counts(merged, pd.DataFrame(vector_rows), pd.DataFrame(polygon_stage_rows), catchments)
    return catchments, pd.DataFrame(vector_rows), geometry_join_qa, pd.DataFrame(polygon_stage_rows), stage_counts


def _catchment_geometry_stage_counts(
    merged: gpd.GeoDataFrame,
    vector_qa: pd.DataFrame,
    polygon_qa: pd.DataFrame,
    catchments: gpd.GeoDataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for representation in sorted(set(_text(merged, "roadway_representation_type"))):
        merged_rep = merged.loc[_text(merged, "roadway_representation_type").eq(representation)]
        vector_rep = vector_qa.loc[_text(vector_qa, "roadway_representation_type").eq(representation)] if not vector_qa.empty else pd.DataFrame()
        polygon_rep = polygon_qa.loc[_text(polygon_qa, "roadway_representation_type").eq(representation)] if not polygon_qa.empty else pd.DataFrame()
        catchment_rep = catchments.loc[_text(catchments, "roadway_representation_type").eq(representation)] if not catchments.empty else gpd.GeoDataFrame()
        rows.extend(
            [
                {
                    "roadway_representation_type": representation,
                    "stage": "input_usable_bins",
                    "row_count": int(len(merged_rep)),
                    "nonempty_geometry_count": "",
                },
                {
                    "roadway_representation_type": representation,
                    "stage": "source_bin_geometry_after_join",
                    "row_count": int(len(merged_rep)),
                    "nonempty_geometry_count": int((merged_rep.geometry.notna() & ~merged_rep.geometry.is_empty).sum()),
                },
                {
                    "roadway_representation_type": representation,
                    "stage": "valid_local_vector",
                    "row_count": int(len(vector_rep)),
                    "nonempty_geometry_count": int(_text(vector_rep, "local_vector_status").eq("usable").sum()) if not vector_rep.empty else 0,
                },
                {
                    "roadway_representation_type": representation,
                    "stage": "constructed_polygon_before_export",
                    "row_count": int(len(polygon_rep)),
                    "nonempty_geometry_count": int(polygon_rep["constructed_polygon_present"].sum()) if not polygon_rep.empty else 0,
                },
                {
                    "roadway_representation_type": representation,
                    "stage": "final_catchment_geometry_before_export",
                    "row_count": int(len(catchment_rep)),
                    "nonempty_geometry_count": int((catchment_rep.geometry.notna() & ~catchment_rep.geometry.is_empty).sum()) if not catchment_rep.empty else 0,
                },
            ]
        )
    return pd.DataFrame(rows)


def _geojson_reload_stage_counts(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    reloaded = gpd.read_file(path)
    rows: list[dict[str, object]] = []
    for representation, group in reloaded.groupby("roadway_representation_type", dropna=False):
        rows.append(
            {
                "roadway_representation_type": representation,
                "stage": "nonempty_polygon_after_geojson_reload",
                "row_count": int(len(group)),
                "nonempty_geometry_count": int((group.geometry.notna() & ~group.geometry.is_empty).sum()),
            }
        )
    return pd.DataFrame(rows)


def _crs_coordinate_sanity(base_bins: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame, geojson_path: Path, metadata_path: Path) -> pd.DataFrame:
    rows = [
        coordinate_profile(base_bins, "source_crash_ready_bins_wkt"),
        coordinate_profile(catchments, "catchments_before_geojson_export"),
    ]
    if geojson_path.exists():
        reloaded = gpd.read_file(geojson_path)
        rows.append(coordinate_profile(reloaded, "catchments_after_geojson_reload"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    sanity = crs_sanity_frame(rows, authoritative_crs=str(metadata.get("authoritative_crs", WORKING_CRS_AUTHORITY)))
    sanity["metadata_file"] = str(metadata_path)
    return sanity


def _empty_geometry_counts_by_representation(catchments: gpd.GeoDataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    if catchments.empty:
        return counts
    for representation, group in catchments.groupby("roadway_representation_type", dropna=False):
        counts[str(representation)] = int((group.geometry.isna() | group.geometry.is_empty).sum())
    return counts


def _append_reason(existing: object, reason: str) -> str:
    reasons = [value for value in str(existing or "").split("|") if value]
    reasons.append(reason)
    return "|".join(dict.fromkeys(reasons))


def _overlap_keys(catchments: gpd.GeoDataFrame) -> list[dict[str, object]]:
    keys: list[dict[str, object]] = []
    undivided = catchments.loc[catchments["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    if undivided.empty:
        return keys
    for (base_segment_id, bin_index), group in undivided.groupby(["base_segment_id", "bin_index_from_reference_signal"], sort=False):
        if len(group) < 2:
            continue
        geoms = list(group.geometry)
        overlap_area = 0.0
        for i, geom_a in enumerate(geoms):
            for geom_b in geoms[i + 1 :]:
                if geom_a is not None and geom_b is not None:
                    overlap_area += geom_a.intersection(geom_b).area
        if overlap_area > 0.001:
            keys.append(
                {
                    "base_segment_id": base_segment_id,
                    "bin_index_from_reference_signal": bin_index,
                    "overlap_area_sq_m": round(overlap_area, 6),
                }
            )
    return keys


def _mark_overlap_unstable(catchments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = catchments.copy()
    for key in _overlap_keys(out):
        mask = (
            out["base_segment_id"].astype(str).eq(str(key["base_segment_id"]))
            & out["bin_index_from_reference_signal"].astype(str).eq(str(key["bin_index_from_reference_signal"]))
            & out["roadway_representation_type"].astype(str).eq("undivided_centerline_pseudo_direction")
        )
        out.loc[mask & out["catchment_status"].eq("usable"), "catchment_status"] = "unstable_review"
        out.loc[mask, "catchment_confidence"] = "review"
        out.loc[mask, "review_flag"] = "TRUE"
        out.loc[mask, "catchment_blocker_reason"] = out.loc[mask, "catchment_blocker_reason"].map(
            lambda value: _append_reason(value, "unexpected_side_catchment_overlap")
        )
    return out


def _overlap_qa(catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    if catchments.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    # Exhaustively check paired undivided side polygons for the same source bin. They should share a boundary but not area.
    for key in _overlap_keys(catchments):
        mask = (
            catchments["base_segment_id"].astype(str).eq(str(key["base_segment_id"]))
            & catchments["bin_index_from_reference_signal"].astype(str).eq(str(key["bin_index_from_reference_signal"]))
        )
        still_usable = int(catchments.loc[mask, "catchment_status"].astype(str).eq("usable").sum())
        rows.append(
            {
                "overlap_check": "same_base_bin_undivided_side_overlap",
                "base_segment_id": key["base_segment_id"],
                "bin_index_from_reference_signal": key["bin_index_from_reference_signal"],
                "reference_directional_bin_id": "",
                "overlap_area_sq_m": key["overlap_area_sq_m"],
                "qa_status": "fail" if still_usable else "flagged_review",
                "issue_count": still_usable,
            }
        )
    # Check duplicate catchment IDs and geometry empties as overlap-surface integrity issues.
    duplicate_ids = catchments["catchment_id"].duplicated().sum()
    rows.append(
        {
            "overlap_check": "catchment_id_duplicates",
            "reference_directional_bin_id": "",
            "overlap_area_sq_m": "",
            "qa_status": "pass" if duplicate_ids == 0 else "fail",
            "issue_count": int(duplicate_ids),
        }
    )
    empty_geoms = int(catchments.geometry.isna().sum() + catchments.geometry.is_empty.sum())
    rows.append(
        {
            "overlap_check": "empty_catchment_geometries",
            "reference_directional_bin_id": "",
            "overlap_area_sq_m": "",
            "qa_status": "pass" if empty_geoms == 0 else "fail",
            "issue_count": empty_geoms,
        }
    )
    return pd.DataFrame(rows)


def _summary(catchments: gpd.GeoDataFrame, input_bins: pd.DataFrame, overlap_qa: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    add("input_usable_directional_bins", len(input_bins), "Rows read from prototype usable directional bins.")
    add("catchments_created", len(catchments))
    add("usable_catchments", int(catchments["catchment_status"].eq("usable").sum()) if not catchments.empty else 0)
    add("unstable_review_catchments", int(catchments["catchment_status"].eq("unstable_review").sum()) if not catchments.empty else 0)
    add("blocked_catchments", int(catchments["catchment_status"].eq("blocked").sum()) if not catchments.empty else 0)
    add("downstream_catchments", int(catchments["signal_relative_direction"].eq("downstream_of_reference_signal").sum()) if not catchments.empty else 0)
    add("upstream_catchments", int(catchments["signal_relative_direction"].eq("upstream_of_reference_signal").sum()) if not catchments.empty else 0)
    add("divided_physical_catchments", int(catchments["roadway_representation_type"].eq("divided_physical_carriageway").sum()) if not catchments.empty else 0)
    add("undivided_pseudo_direction_catchments", int(catchments["roadway_representation_type"].eq("undivided_centerline_pseudo_direction").sum()) if not catchments.empty else 0)
    add("overlap_qa_fail_rows", int(overlap_qa["qa_status"].eq("fail").sum()) if not overlap_qa.empty and "qa_status" in overlap_qa.columns else 0)
    add("crash_data_read", "False")
    add("crash_direction_fields_used", "False")
    add("excluded_directional_bins_used", "False")
    if not catchments.empty:
        exploded = catchments.assign(catchment_blocker_reason=catchments["catchment_blocker_reason"].str.split("|")).explode("catchment_blocker_reason")
        exploded = exploded.loc[exploded["catchment_blocker_reason"].fillna("").astype(str).ne("")]
        for reason, count in exploded["catchment_blocker_reason"].value_counts().items():
            add(f"catchment_instability_reason_{reason}", int(count))
    return pd.DataFrame(rows)


def _aggregate(catchments: gpd.GeoDataFrame, group_column: str) -> pd.DataFrame:
    if catchments.empty or group_column not in catchments.columns:
        return pd.DataFrame()
    return (
        pd.DataFrame(catchments.drop(columns=["geometry"], errors="ignore"))
        .groupby(group_column, dropna=False)
        .agg(
            catchments=("catchment_id", "count"),
            usable=("catchment_status", lambda values: int(values.astype(str).eq("usable").sum())),
            unstable_review=("catchment_status", lambda values: int(values.astype(str).eq("unstable_review").sum())),
            blocked=("catchment_status", lambda values: int(values.astype(str).eq("blocked").sum())),
            downstream=("signal_relative_direction", lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum())),
            upstream=("signal_relative_direction", lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum())),
        )
        .reset_index()
        .sort_values("catchments", ascending=False)
    )


def _stage_value(stage_counts: pd.DataFrame, representation: str, stage: str) -> int:
    if stage_counts.empty:
        return 0
    mask = stage_counts["roadway_representation_type"].astype(str).eq(representation) & stage_counts["stage"].astype(str).eq(stage)
    if not mask.any():
        return 0
    value = stage_counts.loc[mask, "nonempty_geometry_count"].iloc[0]
    return int(pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0])


def _findings(summary_counts: dict[str, int], ready: bool, stage_counts: pd.DataFrame, empty_counts: dict[str, int]) -> str:
    recommendation = (
        "Usable catchments are ready for a later crash-point assignment prototype. Unstable_review and blocked catchments should stay excluded or review-only unless explicitly accepted after a separate audit."
        if ready
        else "Do not use catchments for crash-point assignment until blocked catchments or overlap failures are resolved."
    )
    return f"""# Reference-Signal Directional Bin Catchments Findings

**Status:** Roadway-only catchment surface for prototype usable directional bins.

## Bounded Question

This module creates directional catchment polygons from the conservative prototype usable reference-signal-centered directional bins. It does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crashes, modify scaffold construction, recover blocked records, force divided pairs, or perform crash analysis.

## Catchment Surface

- Input usable directional bins: {summary_counts["input_bins"]}
- Catchments created: {summary_counts["catchments"]}
- Usable catchments: {summary_counts["usable"]}
- Unstable/review catchments: {summary_counts["unstable"]}
- Blocked catchments: {summary_counts["blocked"]}
- Downstream catchments: {summary_counts["downstream"]}
- Upstream catchments: {summary_counts["upstream"]}
- Divided physical catchments: {summary_counts["divided"]}
- Undivided pseudo-direction catchments: {summary_counts["undivided"]}

Divided physical records use a conservative two-sided buffer around the physical directional bin geometry. Undivided centerline pseudo-direction records use explicit local-vector side polygons: right side for A->B downstream and left side for B->A upstream, following the existing roadway-geometry convention. Bins remain indexed from the TRUE reference signal A.

## Geometry Stage QA

- Input undivided usable rows: {summary_counts["undivided"]}
- Undivided rows with source bin geometry after join: {_stage_value(stage_counts, "undivided_centerline_pseudo_direction", "source_bin_geometry_after_join")}
- Undivided rows with valid local vector: {_stage_value(stage_counts, "undivided_centerline_pseudo_direction", "valid_local_vector")}
- Undivided rows with non-empty constructed polygon before export: {_stage_value(stage_counts, "undivided_centerline_pseudo_direction", "constructed_polygon_before_export")}
- Undivided rows with non-empty polygon after GeoJSON reload: {_stage_value(stage_counts, "undivided_centerline_pseudo_direction", "nonempty_polygon_after_geojson_reload")}
- Divided rows with non-empty polygon after GeoJSON reload: {_stage_value(stage_counts, "divided_physical_carriageway", "nonempty_polygon_after_geojson_reload")}
- Empty geometry counts by representation: {json.dumps(empty_counts, sort_keys=True)}

## QA Interpretation

Unstable/review catchments are retained and flagged when local geometry is near an anchor, too short, kinked, or otherwise unsuitable for forced side assignment. Crash direction fields are not used.

## CRS Convention

Catchment geometries are exported in the repository working projected CRS, `EPSG:3968` (`NAD83 / Virginia Lambert`) with metre coordinates. The companion `directional_bin_catchment_crs_metadata.json` is authoritative for downstream consumers if a GeoJSON reader reports a default geographic CRS.

## Recommendation

{recommendation}
"""


def build_directional_bin_catchments(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    qa_dir = output_root / QA_INPUT_DIR
    out_dir = output_root / CATCHMENT_DIR
    tables = output_root / "tables/current"

    usable_segments = _read_csv(qa_dir / USABLE_SEGMENTS)
    usable_bins = _read_csv(qa_dir / USABLE_BINS)
    base_bins = _read_wkt_csv(tables / BASE_BINS)
    usable_ids = set(_text(usable_segments, "reference_directional_segment_id"))
    usable_bins = usable_bins.loc[_text(usable_bins, "reference_directional_segment_id").isin(usable_ids)].copy()

    catchments, vector_qa, geometry_join_qa, undivided_polygon_qa, stage_counts = _build_catchments(usable_bins, base_bins)
    catchments = _mark_overlap_unstable(catchments)
    overlap_qa = _overlap_qa(catchments)
    stage_counts = _catchment_geometry_stage_counts(
        _merge_geometry(usable_bins, base_bins),
        vector_qa,
        undivided_polygon_qa,
        catchments,
    )
    summary = _summary(catchments, usable_bins, overlap_qa)

    index = pd.DataFrame(catchments.drop(columns=["geometry"], errors="ignore")).copy()
    for column in INDEX_COLUMNS:
        if column not in index.columns:
            index[column] = ""
    index = index[INDEX_COLUMNS].copy()

    output_files = {
        "summary": out_dir / "directional_bin_catchment_summary.csv",
        "index": out_dir / "directional_bin_catchment_index.csv",
        "geojson": out_dir / "directional_bin_catchment_polygons.geojson",
        "divided": out_dir / "divided_physical_catchment_bins.csv",
        "undivided": out_dir / "undivided_side_catchment_bins.csv",
        "blocked": out_dir / "catchment_blocked_or_unstable_bins.csv",
        "vector_qa": out_dir / "catchment_local_vector_qa.csv",
        "geometry_join_success": out_dir / "geometry_join_success_by_roadway_representation_type.csv",
        "geometry_stage_counts": out_dir / "catchment_geometry_stage_counts.csv",
        "undivided_polygon_qa": out_dir / "undivided_polygon_construction_qa.csv",
        "overlap_qa": out_dir / "catchment_overlap_qa.csv",
        "crs_metadata": out_dir / CATCHMENT_CRS_METADATA_FILE,
        "crs_coordinate_sanity": out_dir / "catchment_crs_coordinate_sanity.csv",
        "qa_signal": out_dir / "catchment_qa_by_reference_signal.csv",
        "qa_representation": out_dir / "catchment_qa_by_roadway_representation_type.csv",
        "findings": out_dir / "reference_signal_directional_bin_catchments_findings.md",
        "manifest": out_dir / "reference_signal_directional_bin_catchments_manifest.json",
    }

    _write_csv(summary, output_files["summary"])
    _write_csv(index, output_files["index"])
    crs_metadata = write_crs_metadata(output_files["crs_metadata"], source=str(output_files["geojson"]))
    _write_geojson(catchments, output_files["geojson"])
    _write_csv(index.loc[index["roadway_representation_type"].eq("divided_physical_carriageway")], output_files["divided"])
    _write_csv(index.loc[index["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")], output_files["undivided"])
    _write_csv(index.loc[~index["catchment_status"].eq("usable")], output_files["blocked"])
    _write_csv(vector_qa, output_files["vector_qa"])
    _write_csv(geometry_join_qa, output_files["geometry_join_success"])
    _write_csv(undivided_polygon_qa, output_files["undivided_polygon_qa"])
    _write_csv(overlap_qa, output_files["overlap_qa"])
    crs_sanity = _crs_coordinate_sanity(base_bins, catchments, output_files["geojson"], output_files["crs_metadata"])
    _write_csv(crs_sanity, output_files["crs_coordinate_sanity"])
    _write_csv(_aggregate(catchments, "reference_signal_id"), output_files["qa_signal"])
    _write_csv(_aggregate(catchments, "roadway_representation_type"), output_files["qa_representation"])
    reload_stage_counts = _geojson_reload_stage_counts(output_files["geojson"])
    stage_counts = pd.concat([stage_counts, reload_stage_counts], ignore_index=True) if not reload_stage_counts.empty else stage_counts
    _write_csv(stage_counts, output_files["geometry_stage_counts"])

    summary_counts = {
        "input_bins": len(usable_bins),
        "catchments": len(catchments),
        "usable": int(catchments["catchment_status"].eq("usable").sum()) if not catchments.empty else 0,
        "unstable": int(catchments["catchment_status"].eq("unstable_review").sum()) if not catchments.empty else 0,
        "blocked": int(catchments["catchment_status"].eq("blocked").sum()) if not catchments.empty else 0,
        "downstream": int(catchments["signal_relative_direction"].eq("downstream_of_reference_signal").sum()) if not catchments.empty else 0,
        "upstream": int(catchments["signal_relative_direction"].eq("upstream_of_reference_signal").sum()) if not catchments.empty else 0,
        "divided": int(catchments["roadway_representation_type"].eq("divided_physical_carriageway").sum()) if not catchments.empty else 0,
        "undivided": int(catchments["roadway_representation_type"].eq("undivided_centerline_pseudo_direction").sum()) if not catchments.empty else 0,
        "overlap_failures": int(overlap_qa["qa_status"].eq("fail").sum()) if not overlap_qa.empty and "qa_status" in overlap_qa.columns else 0,
    }
    empty_counts = _empty_geometry_counts_by_representation(catchments)
    ready = summary_counts["overlap_failures"] == 0 and summary_counts["usable"] > 0
    _write_text(_findings(summary_counts, ready, stage_counts, empty_counts), output_files["findings"])

    input_files = [
        qa_dir / USABLE_SEGMENTS,
        qa_dir / USABLE_BINS,
        tables / BASE_BINS,
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Roadway-only directional catchment polygons for prototype usable reference-signal directional bins.",
        "read_only": True,
        "raw_crash_data_read": False,
        "crash_assignment_outputs_read": False,
        "crash_direction_fields_used": False,
        "crash_distributions_used": False,
        "excluded_directional_bins_used": False,
        "scaffold_construction_changed": False,
        "prototype_usable_directional_scaffold_changed": False,
        "blocked_directional_records_recovered": False,
        "divided_pairs_forced": False,
        "catchment_width_ft": CATCHMENT_WIDTH_FT,
        "input_files": [str(path) for path in input_files if path.exists()],
        "output_files": [str(path) for path in output_files.values()],
        "crs": crs_metadata,
        "crs_coordinate_sanity": crs_sanity.to_dict(orient="records"),
        "summary_counts": summary_counts,
        "geometry_stage_counts": stage_counts.to_dict(orient="records"),
        "empty_geometry_counts_by_representation": empty_counts,
        "catchments_ready_for_later_crash_point_assignment_prototype": ready,
        "recommendation": "Use only usable catchments for later crash-point assignment; carry unstable_review and blocked catchments separately unless explicitly accepted after review.",
    }
    _write_json(manifest, output_files["manifest"])
    return {key: str(path) for key, path in output_files.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build roadway-only directional bin catchment polygons from prototype usable directional bins.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_directional_bin_catchments(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
