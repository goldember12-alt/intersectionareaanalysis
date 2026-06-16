from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import CRS


WORKING_CRS_EPSG = 3968
WORKING_CRS_AUTHORITY = f"EPSG:{WORKING_CRS_EPSG}"
WORKING_CRS_NAME = "NAD83 / Virginia Lambert"
WORKING_CRS = CRS.from_epsg(WORKING_CRS_EPSG)
CATCHMENT_CRS_METADATA_FILE = "directional_bin_catchment_crs_metadata.json"


def geometry_bounds_are_geographic(bounds) -> bool:
    minx, miny, maxx, maxy = [float(value) for value in bounds]
    return -180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0 and -90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0


def crs_to_string(crs: Any) -> str:
    if crs is None:
        return ""
    parsed = CRS.from_user_input(crs)
    authority = parsed.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return parsed.name


def crs_matches(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return CRS.from_user_input(left) == CRS.from_user_input(right)


def coordinate_profile(frame: gpd.GeoDataFrame, dataset: str) -> dict[str, Any]:
    bounds = frame.total_bounds if not frame.empty else [None, None, None, None]
    if frame.empty:
        return {
            "dataset": dataset,
            "crs": crs_to_string(frame.crs),
            "minx": "",
            "miny": "",
            "maxx": "",
            "maxy": "",
            "bounds_look_geographic": "",
            "coordinates_appear_projected": "",
        }
    geographic = geometry_bounds_are_geographic(bounds)
    return {
        "dataset": dataset,
        "crs": crs_to_string(frame.crs),
        "minx": float(bounds[0]),
        "miny": float(bounds[1]),
        "maxx": float(bounds[2]),
        "maxy": float(bounds[3]),
        "bounds_look_geographic": geographic,
        "coordinates_appear_projected": not geographic,
    }


def authoritative_crs_metadata(*, source: str, geometry_format: str = "projected_coordinates") -> dict[str, Any]:
    return {
        "source": source,
        "authoritative_crs": WORKING_CRS_AUTHORITY,
        "authoritative_crs_epsg": WORKING_CRS_EPSG,
        "authoritative_crs_name": WORKING_CRS_NAME,
        "coordinate_units": "metre",
        "geometry_format": geometry_format,
        "coordinate_convention": "Coordinates are stored in the repository working projected CRS, not longitude/latitude.",
        "geojson_note": "GeoJSON coordinates are intentionally projected EPSG:3968 coordinates for local review/analysis consumers; downstream code must use this metadata if a driver reports a default geographic CRS.",
    }


def write_crs_metadata(path: Path, *, source: str, geometry_format: str = "projected_coordinates") -> dict[str, Any]:
    metadata = authoritative_crs_metadata(source=source, geometry_format=geometry_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def read_crs_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return authoritative_crs_metadata(source="repo_default_missing_metadata")
    return json.loads(path.read_text(encoding="utf-8"))


def apply_authoritative_crs(
    frame: gpd.GeoDataFrame,
    *,
    metadata_path: Path | None = None,
    fallback_crs: str = WORKING_CRS_AUTHORITY,
) -> tuple[gpd.GeoDataFrame, str, dict[str, Any]]:
    metadata = read_crs_metadata(metadata_path) if metadata_path is not None else authoritative_crs_metadata(source="repo_default")
    target_crs = metadata.get("authoritative_crs") or fallback_crs
    target = CRS.from_user_input(target_crs)
    declared = frame.crs
    projected_coords = not geometry_bounds_are_geographic(frame.total_bounds) if not frame.empty else True
    if declared is None:
        return frame.set_crs(target), "catchment_crs_missing_set_from_authoritative_metadata", metadata
    if crs_matches(declared, target):
        return frame, "catchment_crs_matches_authoritative_metadata", metadata
    if projected_coords:
        return frame.set_crs(target, allow_override=True), "catchment_crs_overridden_from_authoritative_metadata_projected_coordinates", metadata
    return frame.to_crs(target), "catchment_crs_reprojected_to_authoritative_metadata", metadata


def crs_sanity_frame(rows: list[dict[str, Any]], *, authoritative_crs: str = WORKING_CRS_AUTHORITY) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["authoritative_crs"] = authoritative_crs
    out["declared_matches_authoritative"] = out["crs"].map(lambda value: crs_matches(value, authoritative_crs) if value else False)
    out["crs_coordinate_range_consistent"] = out.apply(
        lambda row: bool(row["declared_matches_authoritative"]) and bool(row["coordinates_appear_projected"]),
        axis=1,
    )
    return out
