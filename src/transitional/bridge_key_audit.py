from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pyogrio

from .config import RuntimeConfig, load_runtime_config


BRIDGE_KEY_AUDIT_SUMMARY_NAME = "stage1_aadt_traffic_volume_bridge_qc.json"
TRAFFIC_VOLUME_DIRNAME = "VDOT_Bidirectional_Traffic_Volume_2024 (1)"
DIRECT_BRIDGE_FIELDS = ("LINKID", "TMSLINKID", "LINK_ID", "LRS_LINKID")
ROUTE_IDENTITY_FIELDS = (
    "RTE_NM",
    "MASTER_RTE_NM",
    "ROUTE_NAME",
    "ROUTE_COMM",
    "ROUTE_ALIA",
    "RTE_ID",
    "EVENT_SOUR",
    "EDGE_RTE_KEY",
    "HTRIS_ID",
)
DIRECTION_FIELDS = ("LOC_COMP_D", "DIRECTIONALITY", "DIRECTION_")
MEASURE_FIELDS = (
    "FROM_MEASURE",
    "TO_MEASURE",
    "TRANSPORT_EDGE_FROM_MSR",
    "TRANSPORT_EDGE_TO_MSR",
    "ROUTE_FROM",
    "ROUTE_TO_M",
)
NODE_FIELDS = ("BEGINNODE", "ENDNODE", "FROM_NODE", "TO_NODE")


def _canonical_crs_label(crs_obj) -> str | None:
    if crs_obj is None:
        return None
    try:
        epsg = crs_obj.to_epsg()
    except Exception:
        epsg = None
    if epsg:
        return f"EPSG:{epsg}"
    return str(crs_obj)


def _json_ready(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _normalize_text_series(series: pd.Series) -> pd.Series:
    normalized = series.fillna("").astype(str).str.strip().str.upper()
    normalized = normalized.mask(normalized == "")
    return normalized


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
        "present": True,
        "dtype": str(values.dtype),
        "non_null_count": non_null,
        "non_blank_count": non_blank,
        "unique_non_blank_count": unique_non_blank,
        "sample_values": sample_values,
    }


def _candidate_field_summary(frame: pd.DataFrame, available_fields: list[str]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for field in available_fields:
        summary[field] = _field_stats(frame, field)
    return summary


def _source_type_label(path: Path) -> str:
    if path.suffix.lower() == ".shp":
        return "ESRI Shapefile"
    if path.suffix.lower() == ".gpkg":
        return "GeoPackage"
    if path.suffix.lower() in {".geojson", ".json"}:
        return "GeoJSON"
    if path.suffix.lower() == ".parquet":
        return "GeoParquet"
    if path.suffix.lower() == ".gdb" or path.name.endswith(".gdb"):
        return "FileGDB"
    return path.suffix or "unknown"


def _resolve_traffic_volume_source(config: RuntimeConfig) -> tuple[Path, str, dict[str, object]]:
    source_root = config.raw_data_dir / TRAFFIC_VOLUME_DIRNAME
    if not source_root.exists():
        raise FileNotFoundError(f"Missing traffic-volume source directory: {source_root}")

    shapefiles = sorted(source_root.glob("*.shp"))
    if len(shapefiles) != 1:
        raise FileNotFoundError(
            f"Expected exactly one shapefile in {source_root}, found {len(shapefiles)}"
        )

    resolved_path = shapefiles[0]
    return resolved_path, "", {
        "inspected_root": str(source_root),
        "actual_readable_path": str(resolved_path),
        "actual_format": _source_type_label(resolved_path),
        "component_files": sorted(item.name for item in source_root.iterdir()),
    }


def _inspect_source(path: Path, *, layer: str | None, descriptor: dict[str, object]) -> tuple[pd.DataFrame, dict[str, object]]:
    info = pyogrio.read_info(path, layer=layer or None)
    fields = [str(field) for field in info.get("fields", []).tolist()]
    dtypes = [str(dtype) for dtype in info.get("dtypes", []).tolist()]
    dtype_map = dict(zip(fields, dtypes, strict=False))

    candidate_fields = [
        field for field in (*DIRECT_BRIDGE_FIELDS, *ROUTE_IDENTITY_FIELDS, *DIRECTION_FIELDS, *MEASURE_FIELDS, *NODE_FIELDS)
        if field in fields
    ]
    frame = pyogrio.read_dataframe(path, layer=layer or None, columns=candidate_fields, read_geometry=False)

    summary = {
        **descriptor,
        "layer_name": layer or None,
        "row_count": int(_json_ready(info.get("features")) or len(frame)),
        "crs": _canonical_crs_label(info.get("crs")),
        "geometry_type": str(_json_ready(info.get("geometry_type"))),
        "fields": fields,
        "field_dtypes": dtype_map,
        "candidate_key_fields_found": candidate_fields,
        "candidate_key_field_stats": _candidate_field_summary(frame, candidate_fields),
    }
    return frame, summary


def _route_overlap_summary(traffic_frame: pd.DataFrame, aadt_frame: pd.DataFrame) -> dict[str, object]:
    summary: dict[str, object] = {}

    if "ROUTE_NAME" in traffic_frame.columns and "RTE_NM" in aadt_frame.columns:
        traffic_route_name = set(_normalize_text_series(traffic_frame["ROUTE_NAME"]).dropna().tolist())
        aadt_rte_nm = set(_normalize_text_series(aadt_frame["RTE_NM"]).dropna().tolist())
        summary["traffic_route_name_vs_aadt_rte_nm_common_unique"] = int(len(traffic_route_name & aadt_rte_nm))
        summary["traffic_route_name_unique"] = int(len(traffic_route_name))
        summary["aadt_rte_nm_unique"] = int(len(aadt_rte_nm))

    if "ROUTE_NAME" in traffic_frame.columns and "MASTER_RTE_NM" in aadt_frame.columns:
        traffic_route_name = set(_normalize_text_series(traffic_frame["ROUTE_NAME"]).dropna().tolist())
        aadt_master_rte = set(_normalize_text_series(aadt_frame["MASTER_RTE_NM"]).dropna().tolist())
        summary["traffic_route_name_vs_aadt_master_rte_nm_common_unique"] = int(len(traffic_route_name & aadt_master_rte))
        summary["aadt_master_rte_nm_unique"] = int(len(aadt_master_rte))

    traffic_measure_fields = {"ROUTE_NAME", "ROUTE_FROM", "ROUTE_TO_M"}
    aadt_measure_fields = {"RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"}
    if traffic_measure_fields.issubset(traffic_frame.columns) and aadt_measure_fields.issubset(aadt_frame.columns):
        traffic_triples = set(
            tuple(values)
            for values in pd.DataFrame(
                {
                    "route": _normalize_text_series(traffic_frame["ROUTE_NAME"]),
                    "from": _numeric_series(traffic_frame["ROUTE_FROM"]).round(3),
                    "to": _numeric_series(traffic_frame["ROUTE_TO_M"]).round(3),
                }
            ).dropna().drop_duplicates().itertuples(index=False, name=None)
        )
        aadt_triples = set(
            tuple(values)
            for values in pd.DataFrame(
                {
                    "route": _normalize_text_series(aadt_frame["RTE_NM"]),
                    "from": _numeric_series(aadt_frame["TRANSPORT_EDGE_FROM_MSR"]).round(3),
                    "to": _numeric_series(aadt_frame["TRANSPORT_EDGE_TO_MSR"]).round(3),
                }
            ).dropna().drop_duplicates().itertuples(index=False, name=None)
        )
        common = traffic_triples & aadt_triples
        summary["exact_route_measure_triple_overlap_common"] = int(len(common))
        summary["traffic_route_measure_triples_unique"] = int(len(traffic_triples))
        summary["aadt_route_measure_triples_unique"] = int(len(aadt_triples))
        summary["traffic_route_measure_overlap_share"] = (
            None if not traffic_triples else round(len(common) / len(traffic_triples), 4)
        )

    return summary


def _material_difference_summary(traffic_summary: dict[str, object], aadt_summary: dict[str, object]) -> dict[str, object]:
    same_row_count = traffic_summary["row_count"] == aadt_summary["row_count"]
    same_crs = traffic_summary["crs"] == aadt_summary["crs"]
    same_geometry = traffic_summary["geometry_type"] == aadt_summary["geometry_type"]
    shared_fields = sorted(set(traffic_summary["fields"]) & set(aadt_summary["fields"]))

    if same_row_count and same_crs and same_geometry and set(traffic_summary["fields"]) == set(aadt_summary["fields"]):
        classification = "same_or_nearly_same"
    elif same_crs and shared_fields:
        classification = "materially_different_but_partially_joinable"
    else:
        classification = "materially_different"

    return {
        "classification": classification,
        "same_row_count": same_row_count,
        "same_crs": same_crs,
        "same_geometry_type": same_geometry,
        "shared_field_names": shared_fields,
    }


def _bridge_status_summary(traffic_summary: dict[str, object], aadt_summary: dict[str, object], overlap: dict[str, object]) -> dict[str, object]:
    traffic_direct = [
        field
        for field in DIRECT_BRIDGE_FIELDS
        if traffic_summary["candidate_key_field_stats"].get(field, {}).get("non_blank_count", 0) > 0
    ]
    aadt_direct = [
        field
        for field in DIRECT_BRIDGE_FIELDS
        if aadt_summary["candidate_key_field_stats"].get(field, {}).get("non_blank_count", 0) > 0
    ]

    if traffic_direct:
        status = "present_in_new_traffic_volume_layer"
    elif aadt_direct and overlap.get("exact_route_measure_triple_overlap_common", 0) > 0:
        status = "present_in_current_aadt_source_and_partially_joinable_from_new_traffic_volume_layer"
    elif aadt_direct:
        status = "present_in_current_aadt_source_only"
    else:
        status = "absent_in_both_inspected_sources"

    return {
        "status": status,
        "traffic_volume_direct_bridge_fields": traffic_direct,
        "current_aadt_direct_bridge_fields": aadt_direct,
    }


def _insertion_recommendation(bridge_status: dict[str, object], traffic_summary: dict[str, object], overlap: dict[str, object]) -> dict[str, object]:
    traffic_has_road_lineage_fields = all(
        field in traffic_summary["candidate_key_fields_found"]
        for field in ("EVENT_SOUR", "RTE_ID", "ROUTE_NAME", "ROUTE_FROM", "ROUTE_TO_M")
    )
    overlap_count = int(overlap.get("exact_route_measure_triple_overlap_common", 0) or 0)

    if bridge_status["status"] == "present_in_current_aadt_source_and_partially_joinable_from_new_traffic_volume_layer" and traffic_has_road_lineage_fields:
        return {
            "recommended_insertion_boundary": "merged/base-layer output",
            "reason": (
                "The configured AADT source already carries the direct bridge key (`LINKID`), while the new "
                "traffic-volume layer carries road-lineage-compatible fields (`EVENT_SOUR`, `RTE_ID`, route name, "
                "and route measures) but no direct link-id field. A merged/base-layer bridge product is therefore "
                "the cleanest place to attach `LINKID` before later downstream segment propagation."
            ),
            "supporting_evidence": {
                "traffic_has_road_lineage_fields": traffic_has_road_lineage_fields,
                "exact_route_measure_triple_overlap_common": overlap_count,
            },
        }

    if bridge_status["status"] in {
        "present_in_current_aadt_source_only",
        "present_in_current_aadt_source_and_partially_joinable_from_new_traffic_volume_layer",
    }:
        return {
            "recommended_insertion_boundary": "AADT layer",
            "reason": (
                "The direct bridge key is currently evidenced only in the configured AADT source, so the earliest "
                "truthful insertion boundary is the AADT layer."
            ),
            "supporting_evidence": {
                "current_aadt_direct_bridge_fields": bridge_status["current_aadt_direct_bridge_fields"],
            },
        }

    if bridge_status["status"] == "present_in_new_traffic_volume_layer":
        return {
            "recommended_insertion_boundary": "merged/base-layer output",
            "reason": "The new traffic-volume layer itself carries a direct bridge key and should be integrated before segment lineage forks further.",
            "supporting_evidence": {
                "traffic_volume_direct_bridge_fields": bridge_status["traffic_volume_direct_bridge_fields"],
            },
        }

    return {
        "recommended_insertion_boundary": "not yet justified",
        "reason": "Neither inspected source shows a direct GIS-side Oracle bridge key strongly enough to justify pipeline insertion yet.",
        "supporting_evidence": {},
    }


def run_stage1_aadt_traffic_volume_bridge_audit() -> int:
    config = load_runtime_config()
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    traffic_path, traffic_layer, traffic_descriptor = _resolve_traffic_volume_source(config)
    aadt_layer = config.inputs["aadt"]
    aadt_descriptor = {
        "inspected_root": str(aadt_layer.source_gdb),
        "actual_readable_path": str(aadt_layer.source_gdb),
        "actual_format": _source_type_label(aadt_layer.source_gdb),
        "source_layer_name_from_config": aadt_layer.source_layer_name,
        "config_input_key": aadt_layer.key,
        "config_layer_name": aadt_layer.layer_name,
    }

    traffic_frame, traffic_summary = _inspect_source(traffic_path, layer=traffic_layer or None, descriptor=traffic_descriptor)
    aadt_frame, aadt_summary = _inspect_source(aadt_layer.source_gdb, layer=aadt_layer.source_layer_name, descriptor=aadt_descriptor)

    overlap_summary = _route_overlap_summary(traffic_frame, aadt_frame)
    material_difference = _material_difference_summary(traffic_summary, aadt_summary)
    bridge_status = _bridge_status_summary(traffic_summary, aadt_summary, overlap_summary)
    insertion = _insertion_recommendation(bridge_status, traffic_summary, overlap_summary)

    payload = {
        "task": "stage1_aadt_traffic_volume_bridge_audit",
        "stage": "Stage 1",
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "inspected_sources": {
            "new_traffic_volume_layer": traffic_summary,
            "current_aadt_source": aadt_summary,
        },
        "comparison": {
            "material_difference": material_difference,
            "route_and_measure_overlap": overlap_summary,
            "gis_side_oracle_bridge_key": bridge_status,
            "insertion_recommendation": insertion,
            "current_truthful_boundary": (
                "Schema/content inspection shows that the direct bridge key is present in the configured AADT source "
                "via `LINKID`, absent from the new traffic-volume layer as a direct field, and only partially joinable "
                "between the two sources based on route/measure evidence."
            ),
            "still_unknown": [
                "Schema and candidate-field overlap do not prove a one-to-one traffic-volume to AADT match.",
                "A later record-level or spatial comparison is still needed to confirm whether the bridge path can be carried cleanly into road or segment lineage without ambiguity.",
                "No live Oracle access or Oracle query was executed in this bounded audit.",
            ],
        },
    }

    summary_path = config.parity_dir / BRIDGE_KEY_AUDIT_SUMMARY_NAME
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0
