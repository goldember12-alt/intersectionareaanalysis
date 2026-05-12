from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import Point


OUTPUT_ROOT = Path("work/output/directed_segments")
TABLES_CURRENT = Path("tables/current")
REVIEW_CURRENT = Path("review/current")
REVIEW_GEOJSON_CURRENT = Path("review/geojson/current")


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _clean_review_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    cleaned.columns = [str(column).strip() for column in cleaned.columns]
    drop_columns = [
        column
        for column in cleaned.columns
        if column == "" or column.startswith("Unnamed:")
    ]
    if drop_columns:
        cleaned = cleaned.drop(columns=drop_columns)
    return cleaned


def _read_geojson_or_csv(geojson_path: Path, csv_path: Path, crs: object | None = None) -> gpd.GeoDataFrame:
    if geojson_path.exists():
        return gpd.read_file(geojson_path)

    frame = _read_csv(csv_path)
    if "geometry" not in frame.columns:
        raise ValueError(f"No geometry column found in {csv_path}")
    geometries = frame["geometry"].apply(lambda value: wkt.loads(value) if str(value).strip() else None)
    frame = frame.drop(columns=["geometry"])
    return gpd.GeoDataFrame(frame, geometry=geometries, crs=crs)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        return path
    frame.to_file(path, driver="GeoJSON")
    return path


def _join_review_to_leg_geometry(review: pd.DataFrame, legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    review = _clean_review_frame(review)
    leg_columns = [column for column in legs.columns if column not in review.columns and column != "geometry"]
    merged = review.merge(
        legs[["directed_leg_id", *leg_columns, "geometry"]],
        on="directed_leg_id",
        how="left",
    )
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=legs.crs)


def _read_bins_for_leg_ids(path: Path, directed_leg_ids: set[str], crs: object) -> gpd.GeoDataFrame:
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=50_000):
        selected = chunk.loc[chunk["directed_leg_id"].isin(directed_leg_ids)].copy()
        if not selected.empty:
            chunks.append(selected)

    if not chunks:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=crs)

    frame = pd.concat(chunks, ignore_index=True)
    geometries = frame["geometry"].apply(lambda value: wkt.loads(value) if str(value).strip() else None)
    frame = frame.drop(columns=["geometry"])
    return gpd.GeoDataFrame(frame, geometry=geometries, crs=crs)


def _point_from_lookup(anchor_type: str, anchor_id: str, signals: gpd.GeoDataFrame, access: gpd.GeoDataFrame) -> tuple[Point | None, str]:
    if anchor_type == "signal" and anchor_id:
        matches = signals.loc[signals["signal_id"].astype(str).eq(anchor_id)]
        if not matches.empty:
            return matches.geometry.iloc[0], "signal_nodes"
    if anchor_type == "access" and anchor_id and not access.empty:
        matches = access.loc[access["access_anchor_id"].astype(str).eq(anchor_id)]
        if not matches.empty:
            return matches.geometry.iloc[0], "access_anchors_used"
    return None, ""


def _point_from_leg_geometry(geometry: object, anchor_role: str) -> tuple[Point | None, str]:
    if geometry is None:
        return None, ""
    try:
        if geometry.is_empty:
            return None, ""
        coords = list(geometry.coords)
        if not coords:
            return None, ""
        coord = coords[0] if anchor_role == "from" else coords[-1]
        return Point(coord), f"{anchor_role}_geometry_endpoint"
    except (AttributeError, NotImplementedError, TypeError):
        return None, ""


def _zero_or_invalid_points(
    legs: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    access: gpd.GeoDataFrame,
    unresolved_rows: list[dict[str, object]],
) -> gpd.GeoDataFrame:
    is_invalid = ~legs.geometry.is_valid
    is_empty = legs.geometry.is_empty
    is_zero_status = legs["qa_orientation_status"].astype(str).eq("unresolved_zero_length_geometry")
    selected = legs.loc[is_zero_status | is_invalid | is_empty].copy()

    records: list[dict[str, object]] = []
    geometries: list[Point] = []
    for row in selected.itertuples(index=False):
        row_dict = row._asdict()
        row_geometry = row_dict.pop("geometry", None)
        point, source = _point_from_lookup("signal", str(row_dict.get("reference_signal_id", "")), signals, access)
        if point is None:
            point, source = _point_from_lookup(
                str(row_dict.get("from_anchor_type", "")),
                str(row_dict.get("from_anchor_id", "")),
                signals,
                access,
            )
        if point is None:
            point, source = _point_from_leg_geometry(row_geometry, "from")
        if point is None:
            unresolved_rows.append(
                {
                    "layer_filename": "zero_length_or_invalid_geometry_review.geojson",
                    "directed_leg_id": row_dict.get("directed_leg_id", ""),
                    "reason": "no signal, anchor, or line endpoint geometry available",
                }
            )
            continue
        row_dict["gis_review_geometry_type"] = "anchor_point"
        row_dict["gis_review_geometry_source"] = source
        row_dict["gis_review_invalid_line_geometry"] = bool(row_geometry is not None and not row_geometry.is_valid)
        records.append(row_dict)
        geometries.append(point)

    return gpd.GeoDataFrame(records, geometry=geometries, crs=legs.crs)


def _review_anchor_points(
    legs: gpd.GeoDataFrame,
    reviewed_leg_ids: Iterable[str],
    signals: gpd.GeoDataFrame,
    access: gpd.GeoDataFrame,
    unresolved_rows: list[dict[str, object]],
) -> gpd.GeoDataFrame:
    selected = legs.loc[legs["directed_leg_id"].astype(str).isin(set(reviewed_leg_ids))].copy()
    records: list[dict[str, object]] = []
    geometries: list[Point] = []

    for row in selected.itertuples(index=False):
        row_dict = row._asdict()
        row_geometry = row_dict.pop("geometry", None)
        for role in ("from", "to"):
            anchor_type = str(row_dict.get(f"{role}_anchor_type", ""))
            anchor_id = str(row_dict.get(f"{role}_anchor_id", ""))
            point, source = _point_from_lookup(anchor_type, anchor_id, signals, access)
            if point is None:
                point, source = _point_from_leg_geometry(row_geometry, role)
            if point is None:
                unresolved_rows.append(
                    {
                        "layer_filename": "review_anchor_points.geojson",
                        "directed_leg_id": row_dict.get("directed_leg_id", ""),
                        "reason": f"no point geometry available for {role} anchor {anchor_type}:{anchor_id}",
                    }
                )
                continue
            records.append(
                {
                    "directed_leg_id": row_dict.get("directed_leg_id", ""),
                    "reference_signal_id": row_dict.get("reference_signal_id", ""),
                    "anchor_role": role,
                    "anchor_type": anchor_type,
                    "anchor_id": anchor_id,
                    "leg_type": row_dict.get("leg_type", ""),
                    "qa_orientation_status": row_dict.get("qa_orientation_status", ""),
                    "geometry_status": row_dict.get("geometry_status", ""),
                    "geometry_reason": row_dict.get("geometry_reason", ""),
                    "problem_flags": row_dict.get("problem_flags", ""),
                    "route_name": row_dict.get("route_name", ""),
                    "route_common": row_dict.get("route_common", ""),
                    "anchor_geometry_source": source,
                }
            )
            geometries.append(point)

    return gpd.GeoDataFrame(records, geometry=geometries, crs=legs.crs)


def _flag_examples(frame: gpd.GeoDataFrame, examples: pd.DataFrame, field_name: str) -> gpd.GeoDataFrame:
    out = frame.copy()
    example_ids = set(_clean_review_frame(examples)["directed_leg_id"].astype(str))
    out[field_name] = out["directed_leg_id"].astype(str).isin(example_ids)
    return out


def build_qgis_review_layers(output_root: Path = OUTPUT_ROOT) -> dict[str, int]:
    root = output_root
    tables = root / TABLES_CURRENT
    review = root / REVIEW_CURRENT
    geojson = root / REVIEW_GEOJSON_CURRENT
    geojson.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)

    legs = _read_geojson_or_csv(
        geojson / "directed_signal_legs.geojson",
        tables / "directed_signal_legs.csv",
    )
    signals = _read_geojson_or_csv(
        geojson / "signal_nodes.geojson",
        tables / "signal_nodes.csv",
        crs=legs.crs,
    )
    access_geojson = geojson / "access_anchors_used.geojson"
    access = gpd.read_file(access_geojson) if access_geojson.exists() else gpd.GeoDataFrame(columns=["access_anchor_id", "geometry"], geometry="geometry", crs=legs.crs)

    manual = _clean_review_frame(_read_csv(review / "manual_orientation_review_sample.csv"))
    road_endpoint_examples = _clean_review_frame(_read_csv(review / "road_endpoint_leg_examples.csv"))
    signal_to_access_examples = _clean_review_frame(_read_csv(review / "signal_to_access_leg_examples.csv"))

    unresolved_rows: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []

    def write_layer(filename: str, frame: gpd.GeoDataFrame, intended_use: str, join_key: str, notes: str) -> None:
        path = geojson / filename
        missing_geometry = frame.geometry.isna() if "geometry" in frame else pd.Series([], dtype=bool)
        if len(missing_geometry) and bool(missing_geometry.any()):
            id_column = "directed_leg_id" if "directed_leg_id" in frame.columns else ""
            for row in frame.loc[missing_geometry].itertuples(index=False):
                row_dict = row._asdict()
                directed_leg_id = row_dict.get(id_column, "") if id_column else ""
                reason = "missing geometry after CSV/GeoJSON join"
                if directed_leg_id and not str(directed_leg_id).startswith("dleg_"):
                    reason = "malformed or unmatched directed_leg_id; source row appears to be a CSV continuation row"
                unresolved_rows.append(
                    {
                        "layer_filename": filename,
                        "directed_leg_id": directed_leg_id,
                        "reason": reason,
                    }
                )
            frame = frame.loc[~missing_geometry].copy()
        _write_geojson(frame, path)
        inventory.append(
            {
                "layer_filename": filename,
                "feature_count": len(frame),
                "intended_qgis_use": intended_use,
                "join_key": join_key,
                "notes": notes,
            }
        )

    manual_legs = _join_review_to_leg_geometry(manual, legs)
    write_layer(
        "manual_orientation_review_sample_legs.geojson",
        manual_legs,
        "Inspect the directed leg geometries selected for manual orientation QA.",
        "directed_leg_id",
        "Sample only; preserves named manual review columns and joins leg geometry.",
    )

    manual_ids = set(manual["directed_leg_id"].astype(str))
    manual_bins = _read_bins_for_leg_ids(tables / "directed_signal_leg_bins_50ft.csv", manual_ids, legs.crs)
    qa_columns = [
        "directed_leg_id",
        "orientation_method",
        "qa_orientation_status",
        "geometry_status",
        "geometry_reason",
        "problem_flags",
        "length_ft",
        "route_name",
        "route_common",
    ]
    leg_qa = legs[[column for column in qa_columns if column in legs.columns]].drop_duplicates("directed_leg_id")
    manual_bins = manual_bins.merge(leg_qa, on="directed_leg_id", how="left")
    manual_review_fields = manual[["directed_leg_id", "review_group", "notes", "manual_review_status"]].drop_duplicates("directed_leg_id")
    manual_bins = manual_bins.merge(manual_review_fields, on="directed_leg_id", how="left")
    write_layer(
        "manual_orientation_review_sample_bins.geojson",
        manual_bins,
        "Inspect 50-foot bins for the manually sampled directed legs.",
        "directed_leg_id; bin_id",
        "Sample only; bins are limited to directed_leg_id values in manual_orientation_review_sample.csv.",
    )

    fallback_legs = legs.loc[legs["qa_orientation_status"].astype(str).eq("review_geometry_fallback")].copy()
    write_layer(
        "geometry_fallback_review_legs.geojson",
        fallback_legs,
        "Review direct anchor-line fallback legs against the roadway network.",
        "directed_leg_id",
        "Full category for qa_orientation_status=review_geometry_fallback.",
    )

    zero_invalid = _zero_or_invalid_points(legs, signals, access, unresolved_rows)
    write_layer(
        "zero_length_or_invalid_geometry_review.geojson",
        zero_invalid,
        "Locate zero-length or invalid leg cases using source signal or anchor points.",
        "directed_leg_id",
        "Full category for unresolved_zero_length_geometry or invalid/empty geometry; point geometry is used for QGIS location.",
    )

    short_legs = legs.loc[legs["qa_orientation_status"].astype(str).eq("review_short_leg")].copy()
    write_layer(
        "short_leg_review.geojson",
        short_legs,
        "Inspect legs shorter than 50 feet for duplicate anchors, tiny fragments, or valid near-signal spans.",
        "directed_leg_id",
        "Full category for qa_orientation_status=review_short_leg.",
    )

    endpoint_legs = legs.loc[legs["leg_type"].astype(str).eq("signal_to_road_endpoint")].copy()
    endpoint_legs = _flag_examples(endpoint_legs, road_endpoint_examples, "road_endpoint_example_row")
    write_layer(
        "endpoint_leg_review.geojson",
        endpoint_legs,
        "Review signal-to-road-endpoint support legs, especially fallback, zero-length, and long endpoint cases.",
        "directed_leg_id",
        "Full signal_to_road_endpoint category; road_endpoint_example_row marks rows from road_endpoint_leg_examples.csv.",
    )

    access_legs = legs.loc[legs["leg_type"].astype(str).eq("signal_to_access")].copy()
    access_legs = _flag_examples(access_legs, signal_to_access_examples, "signal_to_access_example_row")
    write_layer(
        "signal_to_access_leg_review.geojson",
        access_legs,
        "Review signal-to-access terminus legs for access-spacing scaffold plausibility.",
        "directed_leg_id",
        "Full signal_to_access category; signal_to_access_example_row marks rows from signal_to_access_leg_examples.csv.",
    )

    reviewed_leg_ids = set(manual_ids)
    for frame in [fallback_legs, short_legs, endpoint_legs, access_legs, zero_invalid]:
        if "directed_leg_id" in frame.columns:
            reviewed_leg_ids.update(frame["directed_leg_id"].astype(str))
    anchor_points = _review_anchor_points(legs, reviewed_leg_ids, signals, access, unresolved_rows)
    write_layer(
        "review_anchor_points.geojson",
        anchor_points,
        "Display from/to anchors for reviewed legs and support visual joins to leg layers.",
        "directed_leg_id; anchor_id",
        "Anchor points for all legs included in the review layers; endpoint anchors are derived from leg geometry endpoints when no point table exists.",
    )

    inventory_frame = pd.DataFrame(inventory)
    inventory_frame.to_csv(review / "qgis_review_layer_inventory.csv", index=False)

    unresolved_frame = pd.DataFrame(unresolved_rows, columns=["layer_filename", "directed_leg_id", "reason"])
    unresolved_frame.to_csv(review / "gis_export_unresolved_rows.csv", index=False)

    return {row["layer_filename"]: int(row["feature_count"]) for row in inventory}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build QGIS review GeoJSON layers from directed signal-leg outputs.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)

    counts = build_qgis_review_layers(args.output_root)
    for filename, count in counts.items():
        print(f"{filename}: {count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
