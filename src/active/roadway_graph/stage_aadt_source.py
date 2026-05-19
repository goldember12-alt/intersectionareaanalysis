from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from .crs_utils import WORKING_CRS_AUTHORITY, coordinate_profile, crs_matches, crs_to_string


RAW_AADT_GDB = Path("Intersection Crash Analysis Layers/New_AADT.gdb")
EXPECTED_LAYER = "New_AADT"
NORMALIZED_AADT_FILE = Path("artifacts/normalized/aadt.parquet")
OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/aadt_source_staging")
STABLE_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/catchment_crs_coordinate_sanity.csv"

SEARCH_ROOTS = (
    Path("Intersection Crash Analysis Layers"),
    Path("artifacts/staging"),
    Path("artifacts/normalized"),
)
SOURCE_NAME_TOKENS = (
    "aadt",
    "traffic",
    "volume",
    "daily",
    "count",
    "roadway_volume",
    "roadway volume",
    "new_aadt",
)
AADT_VALUE_FIELD_TOKENS = ("aadt", "aawdt", "volume", "traffic", "adt")
YEAR_FIELD_TOKENS = ("yr", "year")
ROUTE_FIELD_TOKENS = ("route", "rte", "road", "street", "name", "master", "edge_rte")
MEASURE_FIELD_TOKENS = ("measure", "msr")
DIRECTION_FIELD_TOKENS = ("direction", "dir", "factor", "nb", "sb", "eb", "wb")
ID_FIELD_NAMES = {"event_source_id", "event_location_id", "event_component_id", "objectid", "source_id", "id", "linkid", "edge_rte_key"}
GEOMETRY_FIELD_NAMES = {"geometry", "shape", "geom", "wkb_geometry"}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sample_values(series: pd.Series, limit: int = 5) -> str:
    values: list[str] = []
    for value in series.dropna().astype(str):
        if value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return " | ".join(values)


def _matches_source_name(path: Path) -> bool:
    lower = path.name.lower()
    return any(token in lower for token in SOURCE_NAME_TOKENS)


def _candidate_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.is_dir() and suffix == ".gdb":
        return "filegdb"
    if path.is_dir():
        return "directory"
    if suffix == ".parquet":
        return "parquet"
    if suffix in {".shp", ".geojson", ".json", ".gpkg", ".gdb"}:
        return suffix.lstrip(".")
    return "file"


def _find_candidate_paths() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in SEARCH_ROOTS:
        if not root.exists():
            rows.append(
                {
                    "inventory_item": "search_root",
                    "path": str(root),
                    "exists": False,
                    "candidate_kind": "",
                    "layer_name": "",
                    "geometry_type": "",
                    "selected_source": False,
                    "selected_layer": False,
                    "row_count": "",
                    "read_status": "missing",
                    "notes": "",
                }
            )
            continue
        rows.append(
            {
                "inventory_item": "search_root",
                "path": str(root),
                "exists": True,
                "candidate_kind": "directory",
                "layer_name": "",
                "geometry_type": "",
                "selected_source": False,
                "selected_layer": False,
                "row_count": "",
                "read_status": "searched",
                "notes": "searched for AADT, traffic, volume, daily, count, and roadway-volume names",
            }
        )
        for path in root.rglob("*"):
            if not _matches_source_name(path):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "inventory_item": "candidate_path",
                    "path": str(path),
                    "exists": path.exists(),
                    "candidate_kind": _candidate_kind(path),
                    "layer_name": "",
                    "geometry_type": "",
                    "selected_source": path == RAW_AADT_GDB,
                    "selected_layer": False,
                    "row_count": "",
                    "read_status": "found",
                    "notes": "",
                }
            )
    return pd.DataFrame(rows)


def _list_layers(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["path", "layer_name", "geometry_type", "selected_layer", "selection_reason", "layer_error"])
    try:
        layers = pyogrio.list_layers(path)
    except Exception as exc:
        return pd.DataFrame(
            [
                {
                    "path": str(path),
                    "layer_name": "",
                    "geometry_type": "",
                    "selected_layer": False,
                    "selection_reason": "",
                    "layer_error": f"{type(exc).__name__}: {exc}",
                }
            ]
        )
    rows = []
    for layer_name, geometry_type in layers:
        layer = str(layer_name)
        selected = path == RAW_AADT_GDB and layer == EXPECTED_LAYER
        rows.append(
            {
                "path": str(path),
                "layer_name": layer,
                "geometry_type": str(geometry_type),
                "selected_layer": selected,
                "selection_reason": "expected_aadt_layer_name" if selected else "",
                "layer_error": "",
            }
        )
    return pd.DataFrame(rows)


def _inspect_candidate_layers(candidates: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if candidates.empty:
        return pd.DataFrame()
    for row in candidates.loc[candidates["inventory_item"].eq("candidate_path")].itertuples(index=False):
        path = Path(str(row.path))
        if row.candidate_kind in {"filegdb", "gpkg"} or path == RAW_AADT_GDB:
            frames.append(_list_layers(path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _select_layer(layers: pd.DataFrame) -> str | None:
    if layers.empty:
        return None
    expected = layers.loc[layers["path"].eq(str(RAW_AADT_GDB)) & layers["layer_name"].eq(EXPECTED_LAYER)]
    if not expected.empty:
        return EXPECTED_LAYER
    aadt_named = layers.loc[layers["layer_name"].str.contains("aadt", case=False, na=False)]
    if not aadt_named.empty:
        return str(aadt_named.iloc[0]["layer_name"])
    if len(layers) == 1 and str(layers.iloc[0].get("layer_error", "")) == "":
        return str(layers.iloc[0]["layer_name"])
    return None


def _schema(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        series = frame[column]
        rows.append(
            {
                "dataset": dataset,
                "column_name": column,
                "dtype": str(series.dtype),
                "non_null_count": int(series.notna().sum()),
                "null_count": int(series.isna().sum()),
                "null_share": round(float(series.isna().mean()), 6) if len(series) else 0.0,
                "sample_values": _sample_values(series),
            }
        )
    return pd.DataFrame(rows)


def _field_roles(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        lower = column.lower()
        roles: list[str] = []
        if lower in ID_FIELD_NAMES or lower.endswith("_id") or lower.endswith("id"):
            roles.append("likely_source_id")
        if lower in {"aadt", "aawdt"}:
            roles.append("likely_aadt_value" if lower == "aadt" else "likely_aawdt_value")
        elif any(token in lower for token in AADT_VALUE_FIELD_TOKENS):
            roles.append("likely_volume_metadata")
        if any(token in lower for token in YEAR_FIELD_TOKENS):
            roles.append("likely_year")
        if any(token in lower for token in ROUTE_FIELD_TOKENS):
            roles.append("likely_route_or_road_name")
        if any(token in lower for token in MEASURE_FIELD_TOKENS):
            roles.append("likely_route_measure_or_extent")
        if any(token in lower for token in DIRECTION_FIELD_TOKENS):
            roles.append("likely_directionality")
        if lower in GEOMETRY_FIELD_NAMES:
            roles.append("likely_geometry")
        if not roles:
            continue
        rows.append(
            {
                "dataset": dataset,
                "column_name": column,
                "candidate_roles": "|".join(roles),
                "dtype": str(frame[column].dtype),
                "non_null_count": int(frame[column].notna().sum()),
                "sample_values": _sample_values(frame[column]),
                "method_note": "role inferred from field name and source schema only; no AADT-to-bin join performed",
            }
        )
    return pd.DataFrame(rows)


def _geometry_qa(frame: gpd.GeoDataFrame, dataset: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            [
                {
                    "dataset": dataset,
                    "geometry_column": str(frame.geometry.name),
                    "row_count": 0,
                    "geometry_null_count": 0,
                    "geometry_empty_count": 0,
                    "geometry_valid_count": 0,
                    "geometry_invalid_count": 0,
                    "crs": crs_to_string(frame.crs),
                    "geometry_type": "",
                    "geometry_type_count": 0,
                }
            ]
        )
    geometry = frame.geometry
    non_null_geometry = geometry.dropna()
    counts = geometry.geom_type.fillna("<null>").value_counts(dropna=False).reset_index()
    counts.columns = ["geometry_type", "geometry_type_count"]
    counts.insert(0, "dataset", dataset)
    counts.insert(1, "geometry_column", str(frame.geometry.name))
    counts.insert(2, "row_count", len(frame))
    counts.insert(3, "geometry_null_count", int(geometry.isna().sum()))
    counts.insert(4, "geometry_empty_count", int(geometry.is_empty.fillna(False).sum()))
    counts.insert(5, "geometry_valid_count", int(non_null_geometry.is_valid.sum()))
    counts.insert(6, "geometry_invalid_count", int((~non_null_geometry.is_valid).sum()))
    counts.insert(7, "crs", crs_to_string(frame.crs))
    return counts


def _crs_sanity(raw: gpd.GeoDataFrame | None, normalized: gpd.GeoDataFrame | None) -> pd.DataFrame:
    rows = []
    if raw is not None:
        rows.append({**coordinate_profile(raw, "aadt_source_raw"), "stage": "raw_source"})
    if normalized is not None:
        rows.append({**coordinate_profile(normalized, "aadt_normalized"), "stage": "normalized_artifact"})
    stable_bounds = _stable_bounds()
    if normalized is not None and stable_bounds:
        overlaps = _bounds_overlap(normalized.total_bounds, [stable_bounds["minx"], stable_bounds["miny"], stable_bounds["maxx"], stable_bounds["maxy"]])
        rows.append(
            {
                "dataset": "aadt_vs_stable_roadway_graph_universe",
                "crs": crs_to_string(normalized.crs),
                "minx": "",
                "miny": "",
                "maxx": "",
                "maxy": "",
                "bounds_look_geographic": "",
                "coordinates_appear_projected": "",
                "stage": "compatibility_check",
                "stable_crs": stable_bounds.get("crs", ""),
                "stable_bounds_overlap": overlaps,
                "normalized_crs_matches_stable": crs_matches(normalized.crs, stable_bounds.get("crs", WORKING_CRS_AUTHORITY)),
            }
        )
    return pd.DataFrame(rows)


def _stable_bounds() -> dict[str, Any]:
    if not STABLE_CRS_SANITY_FILE.exists():
        return {}
    stable = pd.read_csv(STABLE_CRS_SANITY_FILE)
    row = stable.loc[stable["dataset"].eq("catchments_after_geojson_reload")]
    if row.empty:
        row = stable.head(1)
    if row.empty:
        return {}
    return row.iloc[0].to_dict()


def _bounds_overlap(left: Any, right: Any) -> bool:
    try:
        lminx, lminy, lmaxx, lmaxy = [float(v) for v in left]
        rminx, rminy, rmaxx, rmaxy = [float(v) for v in right]
    except Exception:
        return False
    return lminx <= rmaxx and lmaxx >= rminx and lminy <= rmaxy and lmaxy >= rminy


def _duplicate_null_qa(frame: pd.DataFrame, roles: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if roles.empty:
        return pd.DataFrame()
    tracked = roles.loc[
        roles["candidate_roles"].str.contains(
            "likely_source_id|likely_aadt_value|likely_aawdt_value|likely_year|likely_route_or_road_name|likely_route_measure_or_extent|likely_directionality|likely_geometry",
            regex=True,
            na=False,
        ),
        "column_name",
    ].drop_duplicates()
    rows = []
    for column in tracked:
        if column not in frame.columns:
            continue
        series = frame[column]
        rows.append(
            {
                "dataset": dataset,
                "field_name": column,
                "field_roles": roles.loc[roles["column_name"].eq(column), "candidate_roles"].iloc[0],
                "row_count": len(frame),
                "null_count": int(series.isna().sum()),
                "duplicate_non_null_count": int(series.dropna().duplicated().sum()),
                "unique_non_null_count": int(series.dropna().nunique()),
            }
        )
    return pd.DataFrame(rows)


def _normalize_aadt_source(frame: gpd.GeoDataFrame, *, source_layer: str) -> gpd.GeoDataFrame:
    normalized = frame.copy()
    source_crs = crs_to_string(normalized.crs)
    normalized["Stage1_SourceGDB"] = str(RAW_AADT_GDB)
    normalized["Stage1_SourceLayer"] = source_layer
    normalized["Stage1_SourceCRS"] = source_crs
    normalized["Stage1_NormalizedCRS"] = WORKING_CRS_AUTHORITY
    if normalized.crs is None:
        raise ValueError("Selected AADT layer has no CRS; refusing to write normalized AADT artifact.")
    normalized = normalized.to_crs(WORKING_CRS_AUTHORITY)
    return normalized


def build_aadt_source_staging(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    candidates = _find_candidate_paths()
    layer_inventory = _inspect_candidate_layers(candidates)
    selected_layer = _select_layer(layer_inventory)
    raw: gpd.GeoDataFrame | None = None
    normalized: gpd.GeoDataFrame | None = None
    read_error = ""
    normalized_written = False
    if RAW_AADT_GDB.exists() and selected_layer:
        try:
            raw = pyogrio.read_dataframe(RAW_AADT_GDB, layer=selected_layer)
            normalized = _normalize_aadt_source(raw, source_layer=selected_layer)
            NORMALIZED_AADT_FILE.parent.mkdir(parents=True, exist_ok=True)
            normalized.to_parquet(NORMALIZED_AADT_FILE, index=False)
            normalized_written = True
        except Exception as exc:
            read_error = f"{type(exc).__name__}: {exc}"

    dataset = "aadt_source"
    schema = _schema(raw, dataset) if raw is not None else pd.DataFrame()
    geometry_qa = _geometry_qa(raw, dataset) if raw is not None else pd.DataFrame()
    crs_sanity = _crs_sanity(raw, normalized)
    roles = _field_roles(raw, dataset) if raw is not None else pd.DataFrame()
    dup_null = _duplicate_null_qa(raw, roles, dataset) if raw is not None else pd.DataFrame()
    inventory = _inventory(candidates, layer_inventory, selected_layer, raw, normalized_written, read_error)
    summary = _summary(inventory, raw, roles, normalized_written)
    qa = _qa(inventory, layer_inventory, selected_layer, raw, geometry_qa, crs_sanity, roles, normalized_written)

    outputs = {
        "inventory_csv": out_dir / "aadt_source_inventory.csv",
        "schema_csv": out_dir / "aadt_source_schema.csv",
        "geometry_qa_csv": out_dir / "aadt_source_geometry_qa.csv",
        "crs_sanity_csv": out_dir / "aadt_source_crs_sanity.csv",
        "field_roles_csv": out_dir / "aadt_source_field_role_candidates.csv",
        "duplicate_null_qa_csv": out_dir / "aadt_source_duplicate_null_qa.csv",
        "findings_md": out_dir / "aadt_source_staging_findings.md",
        "manifest_json": out_dir / "aadt_source_staging_manifest.json",
    }
    _write_csv(inventory, outputs["inventory_csv"])
    _write_csv(schema, outputs["schema_csv"])
    _write_csv(geometry_qa, outputs["geometry_qa_csv"])
    _write_csv(crs_sanity, outputs["crs_sanity_csv"])
    _write_csv(roles, outputs["field_roles_csv"])
    _write_csv(dup_null, outputs["duplicate_null_qa_csv"])
    _write_text(_findings(inventory, summary, qa, outputs, selected_layer, normalized_written), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "AADT source inventory and normalized source staging only",
        "candidate_aadt_files_found": _candidate_file_list(inventory),
        "source_gdb": str(RAW_AADT_GDB),
        "selected_layer": selected_layer or "",
        "normalized_aadt_artifact": str(NORMALIZED_AADT_FILE),
        "normalized_aadt_artifact_written": normalized_written,
        "crash_data_read": False,
        "aadt_to_bin_join_implemented": False,
        "roadway_graph_scaffold_changed": False,
        "directional_bin_context_tables_changed": False,
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def _inventory(
    candidates: pd.DataFrame,
    layers: pd.DataFrame,
    selected_layer: str | None,
    raw: gpd.GeoDataFrame | None,
    normalized_written: bool,
    read_error: str,
) -> pd.DataFrame:
    rows = candidates.to_dict(orient="records") if not candidates.empty else []
    if not layers.empty:
        for row in layers.itertuples(index=False):
            is_selected = str(row.path) == str(RAW_AADT_GDB) and row.layer_name == selected_layer
            rows.append(
                {
                    "inventory_item": "candidate_layer",
                    "path": row.path,
                    "exists": Path(str(row.path)).exists(),
                    "candidate_kind": "geospatial_layer",
                    "layer_name": row.layer_name,
                    "geometry_type": row.geometry_type,
                    "selected_source": str(row.path) == str(RAW_AADT_GDB),
                    "selected_layer": is_selected,
                    "row_count": len(raw) if is_selected and raw is not None else "",
                    "read_status": "read" if is_selected and raw is not None else ("read_error" if is_selected and read_error else "not_selected"),
                    "notes": read_error if is_selected and read_error else (row.layer_error or row.selection_reason),
                }
            )
    if RAW_AADT_GDB.exists() and layers.empty:
        rows.append(
            {
                "inventory_item": "candidate_layer",
                "path": str(RAW_AADT_GDB),
                "exists": True,
                "candidate_kind": "filegdb_layer",
                "layer_name": "",
                "geometry_type": "",
                "selected_source": True,
                "selected_layer": False,
                "row_count": "",
                "read_status": "no_layers_found",
                "notes": read_error,
            }
        )
    rows.append(
        {
            "inventory_item": "normalized_artifact",
            "path": str(NORMALIZED_AADT_FILE),
            "exists": NORMALIZED_AADT_FILE.exists(),
            "candidate_kind": "parquet",
            "layer_name": selected_layer or "",
            "geometry_type": "",
            "selected_source": False,
            "selected_layer": False,
            "row_count": len(raw) if normalized_written and raw is not None else "",
            "read_status": "written" if normalized_written else "not_written",
            "notes": "source staged only; no AADT-to-bin join",
        }
    )
    return pd.DataFrame(rows)


def _summary(inventory: pd.DataFrame, raw: gpd.GeoDataFrame | None, roles: pd.DataFrame, normalized_written: bool) -> pd.DataFrame:
    aadt_fields = _role_columns(roles, "likely_aadt_value")
    year_fields = _role_columns(roles, "likely_year")
    route_fields = _role_columns(roles, "likely_route_or_road_name")
    direction_fields = _role_columns(roles, "likely_directionality")
    id_fields = _role_columns(roles, "likely_source_id")
    rows = [
        {"metric": "candidate_paths_found", "value": "", "count": int(inventory.loc[inventory["inventory_item"].eq("candidate_path")].shape[0])},
        {"metric": "source_filegdb_exists", "value": bool(RAW_AADT_GDB.exists()), "count": ""},
        {"metric": "layers_found", "value": "", "count": int(inventory.loc[inventory["inventory_item"].eq("candidate_layer")].shape[0])},
        {"metric": "selected_aadt_layer", "value": _selected_layer_from_inventory(inventory), "count": ""},
        {"metric": "selected_layer_row_count", "value": "", "count": len(raw) if raw is not None else 0},
        {"metric": "selected_layer_crs", "value": crs_to_string(raw.crs) if raw is not None else "", "count": ""},
        {"metric": "likely_aadt_fields", "value": "|".join(aadt_fields), "count": len(aadt_fields)},
        {"metric": "likely_year_fields", "value": "|".join(year_fields), "count": len(year_fields)},
        {"metric": "likely_route_road_fields", "value": "|".join(route_fields), "count": len(route_fields)},
        {"metric": "likely_directionality_fields", "value": "|".join(direction_fields), "count": len(direction_fields)},
        {"metric": "likely_id_fields", "value": "|".join(id_fields), "count": len(id_fields)},
        {"metric": "normalized_aadt_parquet_created", "value": normalized_written, "count": ""},
        {"metric": "crash_data_read", "value": False, "count": ""},
        {"metric": "aadt_to_bin_join_implemented", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _selected_layer_from_inventory(inventory: pd.DataFrame) -> str:
    selected = inventory.loc[inventory["selected_layer"].eq(True), "layer_name"]
    return str(selected.iloc[0]) if not selected.empty else ""


def _role_columns(roles: pd.DataFrame, role: str) -> list[str]:
    if roles.empty:
        return []
    return roles.loc[roles["candidate_roles"].str.contains(role, na=False), "column_name"].tolist()


def _qa(
    inventory: pd.DataFrame,
    layers: pd.DataFrame,
    selected_layer: str | None,
    raw: gpd.GeoDataFrame | None,
    geometry_qa: pd.DataFrame,
    crs_sanity: pd.DataFrame,
    roles: pd.DataFrame,
    normalized_written: bool,
) -> pd.DataFrame:
    aadt_fields = _role_columns(roles, "likely_aadt_value")
    year_fields = _role_columns(roles, "likely_year")
    route_fields = _role_columns(roles, "likely_route_or_road_name")
    geometry_valid = True
    if not geometry_qa.empty and "geometry_invalid_count" in geometry_qa.columns:
        geometry_valid = int(pd.to_numeric(geometry_qa["geometry_invalid_count"], errors="coerce").fillna(0).sum()) == 0
    crs_compatible = False
    if not crs_sanity.empty and "normalized_crs_matches_stable" in crs_sanity.columns:
        values = crs_sanity["normalized_crs_matches_stable"].dropna().astype(str).str.lower()
        crs_compatible = values.isin(["true"]).any()
    rows = [
        {"check_name": "candidate_paths_found", "passed": bool(inventory.loc[inventory["inventory_item"].eq("candidate_path")].shape[0]), "observed": int(inventory.loc[inventory["inventory_item"].eq("candidate_path")].shape[0]), "expected": ">0"},
        {"check_name": "source_filegdb_exists", "passed": RAW_AADT_GDB.exists(), "observed": RAW_AADT_GDB.exists(), "expected": True},
        {"check_name": "layers_found", "passed": not layers.empty, "observed": len(layers), "expected": ">0"},
        {"check_name": "selected_aadt_layer", "passed": bool(selected_layer), "observed": selected_layer or "", "expected": EXPECTED_LAYER},
        {"check_name": "selected_layer_row_count", "passed": raw is not None and len(raw) > 0, "observed": len(raw) if raw is not None else 0, "expected": ">0"},
        {"check_name": "geometry_validity", "passed": geometry_valid, "observed": "see aadt_source_geometry_qa.csv", "expected": "0 invalid geometries"},
        {"check_name": "crs_coordinate_compatibility_with_stable_graph", "passed": crs_compatible, "observed": "see aadt_source_crs_sanity.csv", "expected": WORKING_CRS_AUTHORITY},
        {"check_name": "likely_aadt_value_fields_found", "passed": bool(aadt_fields), "observed": "|".join(aadt_fields), "expected": "AADT"},
        {"check_name": "likely_year_fields_found", "passed": bool(year_fields), "observed": "|".join(year_fields), "expected": "AADT_YR"},
        {"check_name": "likely_route_road_fields_found", "passed": bool(route_fields), "observed": "|".join(route_fields), "expected": "RTE_NM and/or MASTER_RTE_NM"},
        {"check_name": "normalized_artifact_written", "passed": normalized_written, "observed": NORMALIZED_AADT_FILE.exists(), "expected": True},
        {"check_name": "crash_data_read", "passed": True, "observed": False, "expected": False},
        {"check_name": "aadt_to_bin_join_implemented", "passed": True, "observed": False, "expected": False},
    ]
    return pd.DataFrame(rows)


def _candidate_file_list(inventory: pd.DataFrame) -> list[str]:
    if inventory.empty:
        return []
    return inventory.loc[inventory["inventory_item"].eq("candidate_path"), "path"].astype(str).tolist()


def _metric(summary: pd.DataFrame, name: str, *, prefer_count: bool = True) -> Any:
    matched = summary.loc[summary["metric"].eq(name)]
    if matched.empty:
        return ""
    row = matched.iloc[0]
    if prefer_count and str(row["count"]) != "":
        return row["count"]
    return row["value"]


def _findings(
    inventory: pd.DataFrame,
    summary: pd.DataFrame,
    qa: pd.DataFrame,
    outputs: dict[str, Path],
    selected_layer: str | None,
    normalized_written: bool,
) -> str:
    geometry_type = ""
    selected_inventory = inventory.loc[inventory["selected_layer"].eq(True)]
    if not selected_inventory.empty:
        geometry_type = str(selected_inventory.iloc[0].get("geometry_type", ""))
    failed = qa.loc[~qa["passed"].astype(bool)] if not qa.empty else pd.DataFrame()
    candidates = _candidate_file_list(inventory)
    lines = [
        "# AADT Source Staging Findings",
        "",
        "## Bounded Question",
        "",
        "Find, inspect, and stage the AADT source only. No AADT-to-directional-bin context join is implemented.",
        "",
        "## Candidate Files Found",
        "",
        *(f"- `{path}`" for path in candidates),
        "",
        "## Selected Source",
        "",
        f"- selected source: `{RAW_AADT_GDB}`",
        f"- selected layer: `{selected_layer or ''}`",
        f"- row count: {_metric(summary, 'selected_layer_row_count')}",
        f"- CRS: {_metric(summary, 'selected_layer_crs', prefer_count=False)}",
        f"- geometry type: {geometry_type}",
        f"- likely AADT fields: {_metric(summary, 'likely_aadt_fields', prefer_count=False)}",
        f"- likely year fields: {_metric(summary, 'likely_year_fields', prefer_count=False)}",
        f"- likely route/road fields: {_metric(summary, 'likely_route_road_fields', prefer_count=False)}",
        f"- likely directionality fields: {_metric(summary, 'likely_directionality_fields', prefer_count=False)}",
        f"- likely source ID fields: {_metric(summary, 'likely_id_fields', prefer_count=False)}",
        "",
        "## Normalized Artifact",
        "",
        f"- `artifacts/normalized/aadt.parquet` created: {normalized_written}",
        "- normalized geometry CRS: EPSG:3968 when written",
        "- source GDB, layer, source CRS, and normalized CRS metadata fields are preserved on each row",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
        "## Boundary Checks",
        "",
        "- crash data read: False",
        "- crash direction fields read or used: False",
        "- AADT-to-bin join implemented: False",
        "- directional bin context table modified: False",
        "- roadway graph scaffold modified: False",
        f"- QA checks passed: {int(qa['passed'].astype(bool).sum()) if not qa.empty else 0} of {len(qa)}",
        *(["- Failed checks: " + ", ".join(failed["check_name"].astype(str).tolist())] if not failed.empty else []),
        "",
        "## Recommended Next Step",
        "",
        "Implement a separate read-only AADT-to-directional-bin context join using `artifacts/normalized/aadt.parquet`, exact route support, documented route measures, local geometry-distance QA, and explicit unresolved/ambiguous statuses.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory and stage the AADT source for later roadway_graph context enrichment.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_aadt_source_staging(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
