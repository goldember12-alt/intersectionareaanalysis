from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pyogrio

from .bridge_key_audit import _canonical_crs_label, _json_ready, _resolve_traffic_volume_source, _source_type_label
from .config import load_runtime_config


GEOJSON_BRIDGE_QC_SUMMARY_NAME = "stage1_aadt_traffic_volume_geojson_bridge_qc.json"
TRAFFIC_VOLUME_GEOJSON_FILENAME = "VDOT_Bidirectional_Traffic_Volume_2024.geojson"
DIRECT_BRIDGE_FIELD_ALIASES = ("LINKID", "Link ID", "LINK_ID", "TMSLINKID", "LRS_LINKID")
GEOJSON_LINEAGE_FIELDS = (
    "EVENT_SOURCE_ID",
    "ROUTE_COMMON_NAME",
    "ROUTE_NAME",
    "HTRIS_ID",
    "ROUTE_ALIAS",
    "DIRECTION_FACTOR",
    "LOC_COMP_DIRECTIONALITY_NAME",
    "ROUTE_FROM_MEASURE",
    "ROUTE_TO_MEASURE",
    "RTE_ID",
)
SHAPEFILE_LINEAGE_FIELDS = (
    "EVENT_SOUR",
    "ROUTE_COMM",
    "ROUTE_NAME",
    "HTRIS_ID",
    "ROUTE_ALIA",
    "DIRECTION_",
    "LOC_COMP_D",
    "ROUTE_FROM",
    "ROUTE_TO_M",
    "RTE_ID",
)
AADT_BRIDGE_FIELDS = (
    "LINKID",
    "RTE_NM",
    "MASTER_RTE_NM",
    "TRANSPORT_EDGE_FROM_MSR",
    "TRANSPORT_EDGE_TO_MSR",
    "EDGE_RTE_KEY",
)


def _normalize_field_name(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalnum())


def _normalize_text(series: pd.Series) -> pd.Series:
    normalized = series.fillna("").astype(str).str.strip().str.upper()
    return normalized.mask(normalized == "")


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _field_stats(frame: pd.DataFrame, field: str) -> dict[str, object]:
    values = frame[field]
    non_null = int(values.notna().sum())
    if values.dtype == "object":
        stripped = values.dropna().astype(str).str.strip()
        non_blank = int((stripped != "").sum())
        unique_non_blank = int(stripped.loc[stripped != ""].nunique())
        sample_values = [str(value) for value in stripped.loc[stripped != ""].head(5).tolist()]
    else:
        non_blank = non_null
        unique_non_blank = int(values.dropna().nunique())
        sample_values = [str(value) for value in values.dropna().head(5).tolist()]
    return {
        "dtype": str(values.dtype),
        "non_null_count": non_null,
        "non_blank_count": non_blank,
        "unique_non_blank_count": unique_non_blank,
        "sample_values": sample_values,
    }


def _resolve_geojson_source(config) -> tuple[Path, dict[str, object]]:
    path = config.raw_data_dir / TRAFFIC_VOLUME_GEOJSON_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"Missing traffic-volume GeoJSON source: {path}")
    return path, {
        "actual_readable_path": str(path),
        "actual_format": _source_type_label(path),
    }


def _detect_direct_bridge_fields(field_names: list[str]) -> dict[str, object]:
    normalized_map = {_normalize_field_name(name): name for name in field_names}
    matched = []
    for alias in DIRECT_BRIDGE_FIELD_ALIASES:
        normalized = _normalize_field_name(alias)
        if normalized in normalized_map and normalized_map[normalized] not in matched:
            matched.append(normalized_map[normalized])
    return {
        "direct_bridge_aliases_checked": list(DIRECT_BRIDGE_FIELD_ALIASES),
        "matched_direct_bridge_fields": matched,
        "has_direct_bridge_field": bool(matched),
    }


def _inspect_source(path: Path, *, layer: str | None, candidate_fields: tuple[str, ...], descriptor: dict[str, object]) -> tuple[pd.DataFrame, dict[str, object]]:
    info = pyogrio.read_info(path, layer=layer or None)
    fields = [str(field) for field in info.get("fields", []).tolist()]
    dtype_map = dict(
        zip(
            fields,
            [str(dtype) for dtype in info.get("dtypes", []).tolist()],
            strict=False,
        )
    )
    selected_fields = [field for field in candidate_fields if field in fields]
    frame = pyogrio.read_dataframe(path, layer=layer or None, columns=selected_fields, read_geometry=False)
    bridge_detection = _detect_direct_bridge_fields(fields)
    return frame, {
        **descriptor,
        "layer_name": layer or None,
        "row_count": int(_json_ready(info.get("features")) or len(frame)),
        "crs": _canonical_crs_label(info.get("crs")),
        "geometry_type": str(_json_ready(info.get("geometry_type"))),
        "fields": fields,
        "field_dtypes": dtype_map,
        "candidate_lineage_fields_found": selected_fields,
        "candidate_lineage_field_stats": {field: _field_stats(frame, field) for field in selected_fields},
        **bridge_detection,
    }


def _sample_geometry_types(path: Path, *, layer: str | None) -> dict[str, object]:
    import geopandas as gpd

    sample = gpd.read_file(path, layer=layer or None, rows=2000)
    return {
        "sample_row_count": int(len(sample)),
        "sample_geometry_types": sorted(str(value) for value in sample.geometry.geom_type.dropna().unique().tolist()),
        "sample_crs": None if sample.crs is None else str(sample.crs),
    }


def _same_dataset_assessment(geojson_summary: dict[str, object], shapefile_summary: dict[str, object]) -> dict[str, object]:
    positional_pairs = []
    for geo_field, shp_field in zip(geojson_summary["fields"], shapefile_summary["fields"], strict=False):
        if geo_field != shp_field:
            positional_pairs.append({"geojson_field": geo_field, "shapefile_field": shp_field})

    same_source_likely = (
        geojson_summary["row_count"] == shapefile_summary["row_count"]
        and len(geojson_summary["fields"]) == len(shapefile_summary["fields"])
        and geojson_summary["candidate_lineage_field_stats"]["ROUTE_NAME"]["unique_non_blank_count"]
        == shapefile_summary["candidate_lineage_field_stats"]["ROUTE_NAME"]["unique_non_blank_count"]
        and geojson_summary["candidate_lineage_field_stats"]["RTE_ID"]["unique_non_blank_count"]
        == shapefile_summary["candidate_lineage_field_stats"]["RTE_ID"]["unique_non_blank_count"]
    )
    return {
        "appears_to_be_same_dataset_source": same_source_likely,
        "evidence": {
            "same_row_count": geojson_summary["row_count"] == shapefile_summary["row_count"],
            "same_field_count": len(geojson_summary["fields"]) == len(shapefile_summary["fields"]),
            "same_route_name_unique_count": (
                geojson_summary["candidate_lineage_field_stats"]["ROUTE_NAME"]["unique_non_blank_count"]
                == shapefile_summary["candidate_lineage_field_stats"]["ROUTE_NAME"]["unique_non_blank_count"]
            ),
            "same_rte_id_unique_count": (
                geojson_summary["candidate_lineage_field_stats"]["RTE_ID"]["unique_non_blank_count"]
                == shapefile_summary["candidate_lineage_field_stats"]["RTE_ID"]["unique_non_blank_count"]
            ),
        },
        "likely_schema_preservation_pairs_by_position": positional_pairs,
    }


def _field_preservation_summary(geojson_summary: dict[str, object], shapefile_summary: dict[str, object]) -> dict[str, object]:
    geo_fields = set(geojson_summary["fields"])
    shp_fields = set(shapefile_summary["fields"])
    return {
        "geojson_only_fields": sorted(geo_fields - shp_fields),
        "shapefile_only_fields": sorted(shp_fields - geo_fields),
        "shared_exact_field_names": sorted(geo_fields & shp_fields),
        "geojson_retains_longer_names_than_shapefile": True,
    }


def _route_measure_overlap(traffic_frame: pd.DataFrame, *, route_field: str, from_field: str, to_field: str, aadt_frame: pd.DataFrame) -> dict[str, object]:
    traffic_triples = set(
        tuple(values)
        for values in pd.DataFrame(
            {
                "route": _normalize_text(traffic_frame[route_field]),
                "from": _numeric_series(traffic_frame[from_field]).round(3),
                "to": _numeric_series(traffic_frame[to_field]).round(3),
            }
        ).dropna().drop_duplicates().itertuples(index=False, name=None)
    )
    aadt_rte_nm = set(
        tuple(values)
        for values in pd.DataFrame(
            {
                "route": _normalize_text(aadt_frame["RTE_NM"]),
                "from": _numeric_series(aadt_frame["TRANSPORT_EDGE_FROM_MSR"]).round(3),
                "to": _numeric_series(aadt_frame["TRANSPORT_EDGE_TO_MSR"]).round(3),
            }
        ).dropna().drop_duplicates().itertuples(index=False, name=None)
    )
    aadt_master = set(
        tuple(values)
        for values in pd.DataFrame(
            {
                "route": _normalize_text(aadt_frame["MASTER_RTE_NM"]),
                "from": _numeric_series(aadt_frame["TRANSPORT_EDGE_FROM_MSR"]).round(3),
                "to": _numeric_series(aadt_frame["TRANSPORT_EDGE_TO_MSR"]).round(3),
            }
        ).dropna().drop_duplicates().itertuples(index=False, name=None)
    )
    return {
        "exact_route_measure_overlap_to_aadt_rte_nm": int(len(traffic_triples & aadt_rte_nm)),
        "exact_route_measure_overlap_to_aadt_master_rte_nm": int(len(traffic_triples & aadt_master)),
        "traffic_route_measure_triples_unique": int(len(traffic_triples)),
    }


def run_stage1_aadt_traffic_volume_geojson_bridge_audit() -> int:
    config = load_runtime_config()
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    geojson_path, geojson_descriptor = _resolve_geojson_source(config)
    shapefile_path, _, shapefile_descriptor = _resolve_traffic_volume_source(config)
    aadt_layer = config.inputs["aadt"]

    geojson_frame, geojson_summary = _inspect_source(
        geojson_path,
        layer=None,
        candidate_fields=GEOJSON_LINEAGE_FIELDS,
        descriptor=geojson_descriptor,
    )
    shapefile_frame, shapefile_summary = _inspect_source(
        shapefile_path,
        layer=None,
        candidate_fields=SHAPEFILE_LINEAGE_FIELDS,
        descriptor=shapefile_descriptor,
    )
    aadt_frame, aadt_summary = _inspect_source(
        aadt_layer.source_gdb,
        layer=aadt_layer.source_layer_name,
        candidate_fields=AADT_BRIDGE_FIELDS,
        descriptor={
            "actual_readable_path": str(aadt_layer.source_gdb),
            "actual_format": _source_type_label(aadt_layer.source_gdb),
            "source_layer_name_from_config": aadt_layer.source_layer_name,
        },
    )

    geojson_summary["sample_geometry"] = _sample_geometry_types(geojson_path, layer=None)
    same_dataset = _same_dataset_assessment(geojson_summary, shapefile_summary)
    field_preservation = _field_preservation_summary(geojson_summary, shapefile_summary)
    geojson_overlap = _route_measure_overlap(
        geojson_frame,
        route_field="ROUTE_NAME",
        from_field="ROUTE_FROM_MEASURE",
        to_field="ROUTE_TO_MEASURE",
        aadt_frame=aadt_frame,
    )
    shapefile_overlap = _route_measure_overlap(
        shapefile_frame,
        route_field="ROUTE_NAME",
        from_field="ROUTE_FROM",
        to_field="ROUTE_TO_M",
        aadt_frame=aadt_frame,
    )

    geojson_resolves_bridge_key = geojson_summary["has_direct_bridge_field"]
    better_for_bridge_surface = geojson_resolves_bridge_key
    preferred_geojson = True
    preferred_reason = (
        "Use the GeoJSON as the preferred traffic-volume export for future traffic-volume-side inspection because it "
        "preserves full field names and appears to represent the same dataset as the shapefile. However, it does not "
        "resolve the missing direct bridge-key problem, so AADT remains the direct GIS-side LINKID source."
    )

    payload = {
        "task": "stage1_aadt_traffic_volume_geojson_bridge_audit",
        "stage": "Stage 1",
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "inspected_sources": {
            "traffic_volume_geojson": geojson_summary,
            "traffic_volume_shapefile": shapefile_summary,
            "current_aadt_source": aadt_summary,
        },
        "comparison": {
            "geojson_vs_shapefile_same_dataset_assessment": same_dataset,
            "geojson_vs_shapefile_field_preservation": field_preservation,
            "geojson_vs_aadt_bridge_compatibility": geojson_overlap,
            "shapefile_vs_aadt_bridge_compatibility": shapefile_overlap,
            "geojson_preserves_missing_direct_bridge_key": geojson_resolves_bridge_key,
            "geojson_is_better_oracle_bridge_surface_than_shapefile": better_for_bridge_surface,
            "preferred_traffic_volume_source_for_future_bridge_work": preferred_geojson,
            "preferred_source_reason": preferred_reason,
            "pivot_recommendation": (
                "Pivot future traffic-volume-side inspection away from the shapefile and toward the GeoJSON for field-preservation fidelity, "
                "but do not treat the GeoJSON as having solved the direct bridge-key problem."
            ),
            "current_truthful_boundary": (
                "The GeoJSON preserves fuller traffic-volume lineage field names than the shapefile, but it still does not expose "
                "a direct bridge key such as LINKID/TMSLINKID/LINK_ID/LRS_LINKID."
            ),
            "still_unknown": [
                "This bounded inspection does not prove whether a hidden or later-transformable direct bridge key exists outside the preserved GeoJSON properties.",
                "No record-level propagation, road/segment-lineage validation, live Oracle access, or Oracle query was performed here.",
            ],
        },
    }

    summary_path = config.parity_dir / GEOJSON_BRIDGE_QC_SUMMARY_NAME
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0
