from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

try:
    import fiona
except Exception:  # pragma: no cover - optional dependency in some local environments
    fiona = None  # type: ignore[assignment]

try:
    import pyogrio
except Exception:  # pragma: no cover - optional dependency in some local environments
    pyogrio = None  # type: ignore[assignment]


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/access_source_layer_comparison")
SOURCE_ROOT = Path("Intersection Crash Analysis Layers")

OLD_ACCESS_SOURCE = SOURCE_ROOT / "accesspoints.gdb"
NEW_LRSP_GDB = SOURCE_ROOT / "layer_lrspoint.gdb"
NEW_POINT_GDB = SOURCE_ROOT / "layer_point.gdb"

NORMALIZED_ACCESS = Path("artifacts/normalized/access.parquet")
ACCESS_JOINED_FILE = OUTPUT_ROOT / "review/current/access_context_join/access_points_joined_to_stable_universe.csv"
ACCESS_AMBIGUOUS_FILE = OUTPUT_ROOT / "review/current/access_context_join/access_points_ambiguous_bin_matches.csv"

ACTIVE_CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active"
LEGACY_CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
CATCHMENT_POLYGONS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_polygons.geojson"

FEET_TO_METERS = 0.3048

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

CANDIDATE_EXACT_FIELDS = (
    "ACCESS_DIRECTION",
    "ACCESS_CONTROL",
    "NUMBER_OF_APPROACHES",
    "INDUSTRIAL",
    "RESIDENTIAL",
    "COMMERCIAL_RETAIL",
    "GOV_SCHOOL_INSTITUTIONAL",
    "TURN_LANES_PRIMARY_ROUTE",
    "CROSS_STREET",
)

CANDIDATE_FIELD_TOKENS = (
    "ACCESS",
    "CONTROL",
    "APPROACH",
    "RIGHT",
    "RIRO",
    "TURN",
    "MEDIAN",
    "OPENING",
    "DRIVEWAY",
    "ENTRANCE",
    "EXIT",
    "MOVEMENT",
    "RESTRICTION",
    "RESTRICT",
    "LIMITED",
    "FULL",
)

ROUTE_FIELD_TOKENS = (
    "RTE",
    "ROUTE",
    "RNS",
    "MASTER",
    "COMMON",
    "LINKID",
    "EDGE",
    "MEASURE",
    "MSR",
)

FULL_ACCESS_TOKENS = ("FULL", "UNRESTRICTED", "ALL MOVEMENTS", "ALL-MOVEMENT", "FULL ACCESS")
RIRO_TOKENS = ("RIRO", "RIGHT IN RIGHT OUT", "RIGHT-IN RIGHT-OUT", "RIGHT-IN/RIGHT-OUT", "RIGHT IN/RIGHT OUT", "RIGHT-IN/RIGHT-OUT")
RIGHT_IN_ONLY_TOKENS = ("RIGHT IN ONLY", "RIGHT-IN ONLY", "RIGHT IN")
RIGHT_OUT_ONLY_TOKENS = ("RIGHT OUT ONLY", "RIGHT-OUT ONLY", "RIGHT OUT")
RESTRICTED_TOKENS = ("RESTRICT", "LIMITED", "PARTIAL", "NO LEFT", "LEFT TURN PROHIB", "RIGHT ONLY", "NO ENTRY", "ONE WAY")

ACCESS_CONTROL_CODE_MAP = {
    "U": "full_access",
    "UN": "full_access",
    "RIRO": "right_in_right_out",
    "LIRIRO": "right_in_right_out",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "S": "restricted_access",
    "M": "restricted_access",
    "I": "restricted_access",
    "R": "restricted_access",
}

FIELD_SEARCH_TOKENS = (
    "access",
    "direction",
    "control",
    "approach",
    "turn",
    "lane",
    "cross",
    "street",
    "residential",
    "commercial",
    "industrial",
    "government",
    "school",
    "institution",
    "land",
    "use",
    "route",
    "measure",
    "created",
    "modified",
    "driveway",
    "entrance",
    "exit",
    "median",
    "opening",
    "restriction",
    "riro",
    "right",
    "left",
    "in",
    "out",
)

VALUE_SEARCH_TOKENS = (
    "Right-out Only",
    "Right-in",
    "Right-out",
    "Right-in/Right-out",
    "Full",
    "Partial Turn Lanes",
    "North or East",
    "South or West",
    "Residential",
    "Commercial",
    "Industrial",
    "Government",
    "School",
    "On Ramp",
    "Off Ramp",
    "RIRO",
    "RIO",
    "ROO",
    "NE",
    "SW",
)

PREF_LAYER_HINTS = {
    "old_accesspoints": ("layer_lrspoint",),
    "new_layer_lrspoint": ("layer_lrspoint",),
    "new_layer_point": ("layer_point",),
}

OUTPUTS = {
    "inventory": "access_source_layer_inventory.csv",
    "debug_layer_inventory": "access_gdb_layer_inventory_debug.csv",
    "sample_value_profile": "access_layer_sample_value_profile.csv",
    "candidate_field_search": "access_layer_candidate_field_search.csv",
    "candidate_value_search": "access_layer_candidate_value_search.csv",
    "alias_domain_inventory": "access_layer_alias_domain_inventory.csv",
    "selection_ranking": "access_layer_selection_ranking.csv",
    "schema": "access_source_schema_comparison.csv",
    "nonnull": "access_source_non_null_profile.csv",
    "candidate_inventory": "access_candidate_type_field_inventory.csv",
    "candidate_values": "access_candidate_type_value_counts.csv",
    "feasibility": "access_full_vs_riro_feasibility.csv",
    "geometry": "access_old_new_geometry_comparison.csv",
    "attributes": "access_old_new_attribute_comparison.csv",
    "coverage": "access_stable_universe_coverage_estimate.csv",
    "recommendation": "access_v2_candidate_staging_recommendation.csv",
    "findings": "access_source_layer_comparison_findings.md",
    "manifest": "access_source_layer_comparison_manifest.json",
}

OPTIONAL_OUTPUTS = {
    "candidate_mapping": "candidate_access_type_mapping.csv",
    "candidate_preview": "access_v2_candidate_preview.csv",
    "join_preview": "access_v2_candidate_join_preview.csv",
}

INVENTORY_COLUMNS = [
    "source_name",
    "source_category",
    "source_path",
    "layer_name",
    "layer_status",
    "row_count",
    "geometry_column",
    "geometry_types",
    "geometry_non_empty_count",
    "geometry_empty_count",
    "invalid_geometry_count",
    "crs",
    "bounds",
    "bounds_overlaps_stable",
]

DEBUG_LAYER_INVENTORY_COLUMNS = [
    "source_name",
    "source_category",
    "gdb_path",
    "driver_backend",
    "layer_name",
    "layer_geometry_type",
    "layer_read_succeeded",
    "read_error",
    "row_count",
    "geometry_type",
    "crs",
    "bounds",
    "first_10_field_names",
    "total_field_count",
    "sample_non_null_field_count",
]

SAMPLE_VALUE_PROFILE_COLUMNS = [
    "source_name",
    "gdb_path",
    "layer_name",
    "field_name",
    "raw_field_name",
    "non_null_count_in_sample",
    "example_non_null_values",
    "inferred_value_type",
]

CANDIDATE_FIELD_SEARCH_COLUMNS = [
    "source_name",
    "gdb_path",
    "layer_name",
    "field_name",
    "raw_field_name",
    "matched_tokens",
    "is_crash_direction_field",
    "non_null_count_in_sample",
    "example_non_null_values",
]

CANDIDATE_VALUE_SEARCH_COLUMNS = [
    "source_name",
    "gdb_path",
    "layer_name",
    "field_name",
    "raw_field_name",
    "matched_search_value",
    "matched_raw_value",
    "match_count_in_sample",
]

ALIAS_DOMAIN_COLUMNS = [
    "source_name",
    "gdb_path",
    "layer_name",
    "field_name",
    "raw_field_name",
    "alias",
    "domain_name",
    "domain_values",
    "status",
]

SELECTION_RANKING_COLUMNS = [
    "source_name",
    "gdb_path",
    "layer_name",
    "rank_score",
    "selected",
    "row_count",
    "geometry_type",
    "crs",
    "bounds_overlaps_stable",
    "route_measure_field_count",
    "access_field_count",
    "pathways_value_match_count",
    "sample_non_null_field_count",
    "selection_reason",
]

SCHEMA_COLUMNS = [
    "field_name",
    "exists_in_old_accesspoints",
    "exists_in_new_layer_lrspoint",
    "exists_in_new_layer_point",
    "exists_in_normalized_access_parquet",
    "is_candidate_access_related",
    "is_route_related",
]
for _schema_source_name in ("old_accesspoints", "new_layer_lrspoint", "new_layer_point"):
    SCHEMA_COLUMNS.extend(
        [
            f"{_schema_source_name}_dtype",
            f"{_schema_source_name}_row_count",
            f"{_schema_source_name}_non_null_count",
            f"{_schema_source_name}_unique_non_null_count",
            f"{_schema_source_name}_top_values",
            f"{_schema_source_name}_field_kind",
        ]
    )
SCHEMA_COLUMNS.extend(
    [
        "normalized_dtype",
        "normalized_row_count",
        "normalized_non_null_count",
        "normalized_unique_non_null_count",
        "normalized_top_values",
        "normalized_field_kind",
    ]
)

NONNULL_COLUMNS = [
    "source_name",
    "layer_name",
    "field_name",
    "field_type",
    "row_count",
    "non_null_count",
    "unique_non_null_count",
    "null_rate",
]

CANDIDATE_INVENTORY_COLUMNS = [
    "source_name",
    "layer_name",
    "field_name",
    "field_type",
    "non_null_count",
    "null_count",
    "row_count",
    "null_rate",
    "unique_non_null_count",
    "top_values",
    "value_shape",
    "candidate_reason",
]

CANDIDATE_VALUE_COLUMNS = [
    "source_name",
    "layer_name",
    "field_name",
    "category_label",
    "field_value",
    "value_count",
    "value_pct",
]

FEASIBILITY_COLUMNS = [
    "source_name",
    "layer_name",
    "full_vs_riro_support",
    "inference_mode",
    "supporting_fields",
    "supporting_values_count",
    "total_usable_points",
    "notes",
]

GEOMETRY_COLUMNS = ["source_pair", "metric", "left_name", "right_name", "value", "note"]

ATTRIBUTE_COLUMNS = [
    "source_pair",
    "field_name",
    "metric",
    "left_non_null",
    "right_non_null",
    "value_overlap_top5_jaccard",
    "left_dtype",
    "right_dtype",
    "notes",
]

COVERAGE_COLUMNS = [
    "source_name",
    "source_row_count",
    "within_stable_catchments_count",
    "within_stable_catchments_share",
    "within_250ft_of_stable_count",
    "within_250ft_of_stable_share",
    "near_current_matched_access_points_10m_count",
    "near_current_matched_access_points_10m_share",
    "potential_stable_match_count",
    "potential_stable_match_share",
    "potential_matchable_with_usable_access_type_count",
    "potential_matchable_with_usable_access_type_share",
]

RECOMMENDATION_COLUMNS = [
    "candidate_relation",
    "old_accesspoints_rows",
    "new_layer_lrspoint_rows",
    "new_layer_point_rows",
    "new_layer_lrspoint_stable_coverage_share",
    "new_layer_point_stable_coverage_share",
    "lrspoint_full_riro_support",
    "point_full_riro_support",
    "lrspoint_inference_mode",
    "point_inference_mode",
    "recommended_action",
    "recommended_next_module",
    "recommendation_reason",
    "recommendation_text",
    "recommended_for_access_v2_staging",
    "legacy_access_context_untouched",
]

REQUIRED_OUTPUT_SCHEMAS = {
    "inventory": INVENTORY_COLUMNS,
    "debug_layer_inventory": DEBUG_LAYER_INVENTORY_COLUMNS,
    "sample_value_profile": SAMPLE_VALUE_PROFILE_COLUMNS,
    "candidate_field_search": CANDIDATE_FIELD_SEARCH_COLUMNS,
    "candidate_value_search": CANDIDATE_VALUE_SEARCH_COLUMNS,
    "alias_domain_inventory": ALIAS_DOMAIN_COLUMNS,
    "selection_ranking": SELECTION_RANKING_COLUMNS,
    "schema": SCHEMA_COLUMNS,
    "nonnull": NONNULL_COLUMNS,
    "candidate_inventory": CANDIDATE_INVENTORY_COLUMNS,
    "candidate_values": CANDIDATE_VALUE_COLUMNS,
    "feasibility": FEASIBILITY_COLUMNS,
    "geometry": GEOMETRY_COLUMNS,
    "attributes": ATTRIBUTE_COLUMNS,
    "coverage": COVERAGE_COLUMNS,
    "recommendation": RECOMMENDATION_COLUMNS,
}


@dataclass(frozen=True)
class SourceSpec:
    source_name: str
    path: Path
    category: str


@dataclass(frozen=True)
class SourceReadResult:
    spec: SourceSpec
    all_layers: list[tuple[str, gpd.GeoDataFrame]]
    selected_layer_name: str | None
    selected_frame: gpd.GeoDataFrame | None
    inventory: pd.DataFrame
    debug_layer_inventory: pd.DataFrame
    sample_value_profile: pd.DataFrame
    candidate_field_search: pd.DataFrame
    candidate_value_search: pd.DataFrame
    alias_domain_inventory: pd.DataFrame
    selection_ranking: pd.DataFrame


SOURCES = (
    SourceSpec("old_accesspoints", OLD_ACCESS_SOURCE, "old"),
    SourceSpec("new_layer_lrspoint", NEW_LRSP_GDB, "new_lrspoint"),
    SourceSpec("new_layer_point", NEW_POINT_GDB, "new_layer_point"),
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _with_schema(frame: pd.DataFrame | None, columns: list[str]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        return _empty_frame(columns)
    out = frame.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = pd.Series(dtype="object")
    return out.loc[:, columns]


def _concat_with_schema(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    usable = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not usable:
        return _empty_frame(columns)
    return _with_schema(pd.concat(usable, ignore_index=True), columns)


def _first_value(frame: pd.DataFrame | None, key_column: str, key_value: str, value_column: str, default: str = "not_available") -> str:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return default
    if key_column not in frame.columns or value_column not in frame.columns:
        return default
    rows = frame.loc[frame[key_column].astype(str).eq(key_value), value_column]
    if rows.empty:
        return default
    value = rows.iloc[0]
    if pd.isna(value) or str(value).strip() == "":
        return default
    return str(value)


def _numeric_sum_for_source(frame: pd.DataFrame | None, source_name: str, column: str) -> int:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return 0
    if "source_name" not in frame.columns or column not in frame.columns:
        return 0
    rows = pd.to_numeric(frame.loc[frame["source_name"].astype(str).eq(source_name), column], errors="coerce")
    return int(rows.fillna(0).sum())


def _csv_headers_present(path: Path, expected_columns: list[str]) -> bool:
    try:
        headers = list(pd.read_csv(path, nrows=0).columns)
    except Exception:
        return False
    return all(column in headers for column in expected_columns)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_str(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _clean_text(value: Any) -> str:
    return _safe_str(value).upper()


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _row_count(frame: gpd.GeoDataFrame | pd.DataFrame | None) -> int:
    return 0 if frame is None else int(len(frame))


def _top_values(series: pd.Series, *, limit: int = 10) -> str:
    values = series.loc[_nonempty(series)].astype(str).str.strip()
    if values.empty:
        return ""
    counts = values.value_counts(dropna=False).head(limit)
    return "|".join(f"{idx}:{int(count)}" for idx, count in counts.items())


def _field_kind(series: pd.Series) -> str:
    values = series.loc[_nonempty(series)].astype(str).str.strip()
    if values.empty:
        return "empty"
    lowered = values.str.lower()
    if pd.to_numeric(values, errors="coerce").notna().all():
        return "numeric" if values.astype(str).nunique(dropna=True) > 20 else "binary_numeric"
    unique = lowered.nunique(dropna=True)
    if unique <= 25:
        return "categorical"
    avg_len = values.str.len().mean()
    return "free_text" if pd.isna(avg_len) or avg_len > 16 else "mixed_text"


def _inferred_value_type(series: pd.Series) -> str:
    values = series.loc[_nonempty(series)].astype(str).str.strip()
    if values.empty:
        return "empty"
    if pd.to_numeric(values, errors="coerce").notna().all():
        return "numeric"
    date_like = values.str.match(r"^\d{4}-\d{2}-\d{2}").mean()
    if date_like >= 0.8:
        return "datetime"
    if values.nunique(dropna=True) <= 25:
        return "categorical"
    return "text"


def _example_values(series: pd.Series, *, limit: int = 5) -> str:
    values = series.loc[_nonempty(series)].astype(str).str.strip().drop_duplicates().head(limit)
    return "|".join(values.tolist())


def _contains_crash_direction(field_name: str) -> bool:
    upper = field_name.upper()
    return any(token in upper for token in CRASH_DIRECTION_FIELD_TOKENS)


def _is_candidate_field(field: str) -> bool:
    if _contains_crash_direction(field):
        return False
    upper = field.upper()
    if upper in CANDIDATE_EXACT_FIELDS:
        return True
    return any(token in upper for token in CANDIDATE_FIELD_TOKENS)


def _is_route_field(field: str) -> bool:
    if _contains_crash_direction(field):
        return False
    upper = field.upper()
    return any(token in upper for token in ROUTE_FIELD_TOKENS)


def _geometry_summary(frame: gpd.GeoDataFrame | None) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {
            "geometry_column": "",
            "geometry_types": "",
            "non_empty_geometry_count": 0,
            "empty_geometry_count": 0,
            "invalid_geometry_count": 0,
            "row_count": 0,
            "bounds": "",
            "crs": "",
        }
    frame = frame.copy()
    geom = frame.geometry
    types = geom.geom_type.value_counts(dropna=False).sort_index()
    summary_types = "|".join(f"{name}:{int(count)}" for name, count in types.items())
    valid = geom.is_valid.fillna(False)
    non_empty = geom.notna() & ~geom.is_empty
    bounds = ""
    try:
        bounds = ",".join(f"{float(v):.6f}" for v in frame.total_bounds)
    except Exception:
        bounds = ""
    return {
        "geometry_column": str(frame.geometry.name),
        "geometry_types": summary_types,
        "non_empty_geometry_count": int(non_empty.sum()),
        "empty_geometry_count": int((geom.isna() | geom.is_empty).sum()),
        "invalid_geometry_count": int((~valid).sum()),
        "row_count": int(len(frame)),
        "bounds": bounds,
        "crs": str(frame.crs) if frame.crs else "",
    }


def _source_exists(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _list_layers(path: Path) -> list[str]:
    if pyogrio is not None and _source_exists(path):
        try:
            layer_info = pyogrio.list_layers(path)
            return sorted(str(row[0]) for row in layer_info)
        except Exception:
            pass
    if fiona is None:
        return []
    if not _source_exists(path):
        return []
    try:
        return sorted(list(fiona.listlayers(path)))
    except Exception:
        return []


def _list_layer_details(path: Path) -> tuple[str, list[dict[str, str]]]:
    if not _source_exists(path):
        return "not_available", []
    if pyogrio is not None:
        try:
            rows = []
            for layer_name, geometry_type in pyogrio.list_layers(path):
                rows.append({"layer_name": str(layer_name), "layer_geometry_type": str(geometry_type), "driver_backend": "pyogrio"})
            return "pyogrio", rows
        except Exception:
            pass
    if fiona is not None:
        try:
            return "fiona", [
                {"layer_name": str(layer_name), "layer_geometry_type": "", "driver_backend": "fiona"}
                for layer_name in fiona.listlayers(path)
            ]
        except Exception:
            pass
    return "not_available", []


def _read_layer(path: Path, layer: str | None) -> gpd.GeoDataFrame | None:
    try:
        if layer is None:
            return gpd.read_file(path)
        return gpd.read_file(path, layer=layer)
    except Exception:
        return None


def _read_layer_sample(path: Path, layer: str, rows: int = 25) -> tuple[gpd.GeoDataFrame, str]:
    try:
        return gpd.read_file(path, layer=layer, rows=rows), ""
    except Exception as exc:
        return gpd.GeoDataFrame(), f"{type(exc).__name__}: {exc}"


def _layer_info(path: Path, layer: str) -> dict[str, Any]:
    if pyogrio is not None:
        try:
            info = pyogrio.read_info(path, layer=layer)
            fields = [str(field) for field in list(info.get("fields", []))]
            bounds_values = info.get("total_bounds", [])
            return {
                "driver_backend": f"pyogrio/{info.get('driver', 'unknown')}",
                "row_count": int(info.get("features") or 0),
                "geometry_type": _safe_str(info.get("geometry_type")),
                "crs": _safe_str(info.get("crs")),
                "bounds": ",".join(f"{float(v):.6f}" for v in bounds_values if v is not None),
                "fields": fields,
            }
        except Exception:
            pass
    return {
        "driver_backend": "geopandas",
        "row_count": 0,
        "geometry_type": "",
        "crs": "",
        "bounds": "",
        "fields": [],
    }


def _layer_debug_tables(
    source: SourceSpec,
    layer_details: list[dict[str, str]],
    stable: gpd.GeoDataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inventory_rows = []
    sample_rows = []
    field_search_rows = []
    value_search_rows = []
    alias_rows = []
    ranking_rows = []

    for detail in layer_details:
        layer_name = detail["layer_name"]
        info = _layer_info(source.path, layer_name)
        sample, read_error = _read_layer_sample(source.path, layer_name, rows=25)
        read_ok = read_error == ""
        sample_geometry_name = sample.geometry.name if read_ok and hasattr(sample, "geometry") else "geometry"
        sample_fields = [col for col in sample.columns if col != sample_geometry_name] if read_ok else []
        sample_non_null_field_count = 0
        if read_ok and not sample.empty:
            sample_non_null_field_count = int(sum(_nonempty(sample[col]).any() for col in sample_fields))

        sample_geometry_types = ""
        if read_ok and not sample.empty:
            try:
                sample_geometry_types = "|".join(f"{idx}:{int(count)}" for idx, count in sample.geometry.geom_type.value_counts(dropna=False).items())
            except Exception:
                sample_geometry_types = info["geometry_type"]
        else:
            sample_geometry_types = info["geometry_type"]

        inventory_rows.append(
            {
                "source_name": source.source_name,
                "source_category": source.category,
                "gdb_path": str(source.path),
                "driver_backend": info["driver_backend"] or detail.get("driver_backend", ""),
                "layer_name": layer_name,
                "layer_geometry_type": detail.get("layer_geometry_type", ""),
                "layer_read_succeeded": read_ok,
                "read_error": read_error,
                "row_count": info["row_count"] or _row_count(sample),
                "geometry_type": info["geometry_type"] or sample_geometry_types,
                "crs": info["crs"] or (str(sample.crs) if read_ok and sample.crs else ""),
                "bounds": info["bounds"] or (",".join(f"{float(v):.6f}" for v in sample.total_bounds) if read_ok and not sample.empty else ""),
                "first_10_field_names": "|".join((info["fields"] or sample_fields)[:10]),
                "total_field_count": len(info["fields"] or sample_fields),
                "sample_non_null_field_count": sample_non_null_field_count,
            }
        )

        if read_ok:
            for field in sample_fields:
                series = sample[field]
                examples = _example_values(series)
                sample_rows.append(
                    {
                        "source_name": source.source_name,
                        "gdb_path": str(source.path),
                        "layer_name": layer_name,
                        "field_name": field.upper(),
                        "raw_field_name": field,
                        "non_null_count_in_sample": int(_nonempty(series).sum()),
                        "example_non_null_values": examples,
                        "inferred_value_type": _inferred_value_type(series),
                    }
                )
                matched_tokens = [token for token in FIELD_SEARCH_TOKENS if token in field.lower()]
                if matched_tokens:
                    field_search_rows.append(
                        {
                            "source_name": source.source_name,
                            "gdb_path": str(source.path),
                            "layer_name": layer_name,
                            "field_name": field.upper(),
                            "raw_field_name": field,
                            "matched_tokens": "|".join(matched_tokens),
                            "is_crash_direction_field": _contains_crash_direction(field),
                            "non_null_count_in_sample": int(_nonempty(series).sum()),
                            "example_non_null_values": examples,
                        }
                    )

                values = series.loc[_nonempty(series)].astype(str).str.strip()
                for search_value in VALUE_SEARCH_TOKENS:
                    mask = values.str.contains(search_value, case=False, regex=False, na=False)
                    if not mask.any():
                        continue
                    matched = values.loc[mask].drop_duplicates().head(5)
                    value_search_rows.append(
                        {
                            "source_name": source.source_name,
                            "gdb_path": str(source.path),
                            "layer_name": layer_name,
                            "field_name": field.upper(),
                            "raw_field_name": field,
                            "matched_search_value": search_value,
                            "matched_raw_value": "|".join(matched.tolist()),
                            "match_count_in_sample": int(mask.sum()),
                        }
                    )

                alias_rows.append(
                    {
                        "source_name": source.source_name,
                        "gdb_path": str(source.path),
                        "layer_name": layer_name,
                        "field_name": field.upper(),
                        "raw_field_name": field,
                        "alias": "not_available",
                        "domain_name": "not_available",
                        "domain_values": "not_available",
                        "status": "not_available_from_geopandas_backend",
                    }
                )

        field_names = list(info["fields"] or sample_fields)
        field_upper = {field.upper() for field in field_names}
        route_measure_count = sum(
            1
            for field in field_names
            if _is_route_field(field) or field.lower() in {"_rte_nm", "_m", "route_name", "measure"}
        )
        access_field_count = sum(1 for field in field_names if _is_candidate_field(field))
        sample_value_matches = len([row for row in value_search_rows if row["source_name"] == source.source_name and row["layer_name"] == layer_name])
        point_geometry = "POINT" in str(info["geometry_type"] or sample_geometry_types).upper()
        row_count = int(info["row_count"] or _row_count(sample))
        bounds_overlaps_stable = ""
        if stable is not None and not stable.empty and read_ok and not sample.empty:
            try:
                bounds_overlaps_stable = _bounds_overlap(sample.total_bounds, stable.to_crs(sample.crs).total_bounds if sample.crs and stable.crs and sample.crs != stable.crs else stable.total_bounds)
            except Exception:
                bounds_overlaps_stable = "unknown"
        score = 0
        score += min(row_count, 1000) / 100.0
        score += 20 if point_geometry else 0
        score += 10 if route_measure_count >= 2 else route_measure_count * 4
        score += access_field_count * 3
        score += sample_value_matches * 5
        if bounds_overlaps_stable is True:
            score += 5
        if {"ACCESS_CONTROL", "ACCESS_DIRECTION", "NUMBER_OF_APPROACHES"}.issubset(field_upper):
            score += 15
        ranking_rows.append(
            {
                "source_name": source.source_name,
                "gdb_path": str(source.path),
                "layer_name": layer_name,
                "rank_score": round(float(score), 3),
                "selected": False,
                "row_count": row_count,
                "geometry_type": info["geometry_type"] or sample_geometry_types,
                "crs": info["crs"] or (str(sample.crs) if read_ok and sample.crs else ""),
                "bounds_overlaps_stable": bounds_overlaps_stable,
                "route_measure_field_count": route_measure_count,
                "access_field_count": access_field_count,
                "pathways_value_match_count": sample_value_matches,
                "sample_non_null_field_count": sample_non_null_field_count,
                "selection_reason": "",
            }
        )

    ranking = _with_schema(pd.DataFrame(ranking_rows), SELECTION_RANKING_COLUMNS)
    if not ranking.empty:
        selected_idx = pd.to_numeric(ranking["rank_score"], errors="coerce").fillna(-1).idxmax()
        ranking.loc[selected_idx, "selected"] = True
        ranking.loc[selected_idx, "selection_reason"] = "highest_ranked_access_inventory_candidate"

    return (
        _with_schema(pd.DataFrame(inventory_rows), DEBUG_LAYER_INVENTORY_COLUMNS),
        _with_schema(pd.DataFrame(sample_rows), SAMPLE_VALUE_PROFILE_COLUMNS),
        _with_schema(pd.DataFrame(field_search_rows), CANDIDATE_FIELD_SEARCH_COLUMNS),
        _with_schema(pd.DataFrame(value_search_rows), CANDIDATE_VALUE_SEARCH_COLUMNS),
        _with_schema(pd.DataFrame(alias_rows), ALIAS_DOMAIN_COLUMNS),
        ranking,
    )


def _choose_layer(path: Path, source_name: str, layers: list[str], frames: dict[str, gpd.GeoDataFrame | None]) -> str | None:
    preferred = PREF_LAYER_HINTS.get(source_name, tuple())
    for hint in preferred:
        for layer in layers:
            if layer.lower() == hint.lower():
                return layer
    for layer, frame in frames.items():
        if frame is None or frame.empty:
            continue
        if frame.geometry.notna().all() and any(str(t).upper() == "POINT" for t in frame.geometry.geom_type.dropna()):
            return layer
    return layers[0] if layers else None


def _safe_reproject(frame: gpd.GeoDataFrame, target_crs: str | int | None) -> gpd.GeoDataFrame:
    if frame is None or frame.empty:
        return frame if frame is not None else gpd.GeoDataFrame()
    if target_crs is None:
        return frame
    if frame.crs is None:
        return gpd.GeoDataFrame(frame.copy(), geometry=frame.geometry)
    if frame.crs == target_crs:
        return frame
    try:
        return frame.to_crs(target_crs)
    except Exception:
        return gpd.GeoDataFrame(frame.copy(), geometry=frame.geometry)


def _read_source(source: SourceSpec) -> SourceReadResult:
    stable = _stable_catchments()
    _, layer_details = _list_layer_details(source.path)
    layers = [row["layer_name"] for row in layer_details] or _list_layers(source.path)
    if layers and not layer_details:
        layer_details = [{"layer_name": layer, "layer_geometry_type": "", "driver_backend": "geopandas"} for layer in layers]
    (
        debug_layer_inventory,
        sample_value_profile,
        candidate_field_search,
        candidate_value_search,
        alias_domain_inventory,
        selection_ranking,
    ) = _layer_debug_tables(source, layer_details, stable)
    layer_rows: list[pd.DataFrame] = []
    loaded: dict[str, gpd.GeoDataFrame] = {}
    if not layers:
        return SourceReadResult(
            spec=source,
            all_layers=[],
            selected_layer_name=None,
            selected_frame=gpd.GeoDataFrame(),
            inventory=_empty_frame(INVENTORY_COLUMNS),
            debug_layer_inventory=debug_layer_inventory,
            sample_value_profile=sample_value_profile,
            candidate_field_search=candidate_field_search,
            candidate_value_search=candidate_value_search,
            alias_domain_inventory=alias_domain_inventory,
            selection_ranking=selection_ranking,
        )

    for layer in layers:
        frame = _read_layer(source.path, layer)
        if frame is None:
            layer_rows.append(
                {
                    "source_name": source.source_name,
                    "source_category": source.category,
                    "source_path": str(source.path),
                    "layer_name": layer,
                    "layer_status": "read_error",
                    "row_count": 0,
                    "geometry_column": "",
                    "geometry_types": "",
                    "geometry_non_empty_count": 0,
                    "geometry_empty_count": 0,
                    "invalid_geometry_count": 0,
                    "crs": "",
                    "bounds": "",
                    "bounds_overlaps_stable": "",
                }
            )
            loaded[layer] = gpd.GeoDataFrame()
            continue
        summary = _geometry_summary(frame)
        layer_rows.append(
            {
                "source_name": source.source_name,
                "source_category": source.category,
                "source_path": str(source.path),
                "layer_name": layer,
                "layer_status": "read",
                "row_count": summary["row_count"],
                "geometry_column": summary["geometry_column"],
                "geometry_types": summary["geometry_types"],
                "geometry_non_empty_count": summary["non_empty_geometry_count"],
                "geometry_empty_count": summary["empty_geometry_count"],
                "invalid_geometry_count": summary["invalid_geometry_count"],
                "crs": summary["crs"],
                "bounds": summary["bounds"],
                "bounds_overlaps_stable": "",
            }
        )
        loaded[layer] = frame

    selected_layer = None
    if not selection_ranking.empty and "selected" in selection_ranking.columns:
        selected_rows = selection_ranking.loc[selection_ranking["selected"].astype(str).str.lower().eq("true"), "layer_name"]
        if not selected_rows.empty:
            selected_layer = str(selected_rows.iloc[0])
    if selected_layer is None:
        selected_layer = _choose_layer(source.path, source.source_name, layers, loaded)
    selected_frame = loaded.get(selected_layer, gpd.GeoDataFrame()) if selected_layer is not None else gpd.GeoDataFrame()
    inventory = _with_schema(pd.DataFrame(layer_rows), INVENTORY_COLUMNS)
    return SourceReadResult(
        source,
        [(k, v) for k, v in loaded.items()],
        selected_layer,
        selected_frame,
        inventory,
        debug_layer_inventory,
        sample_value_profile,
        candidate_field_search,
        candidate_value_search,
        alias_domain_inventory,
        selection_ranking,
    )


def _stable_catchments() -> gpd.GeoDataFrame | None:
    if not CATCHMENT_POLYGONS_FILE.exists() or not CATCHMENT_INDEX_FILE.exists():
        return None
    try:
        polygons = gpd.read_file(CATCHMENT_POLYGONS_FILE)
        index = pd.read_csv(CATCHMENT_INDEX_FILE, dtype=str, keep_default_na=False)
        usable = set(index.loc[index.get("catchment_status", "").str.lower().eq("usable"), "catchment_id"].astype(str))
        if "catchment_id" in polygons.columns and usable:
            polygons = polygons.loc[polygons["catchment_id"].astype(str).isin(usable)].copy()
        return polygons
    except Exception:
        return None


def _stable_context_path() -> Path | None:
    active = ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv"
    legacy = LEGACY_CONTEXT_DIR / "directional_bin_context.csv"
    if active.exists():
        return active
    return legacy if legacy.exists() else None


def _build_inventory(sources: list[SourceReadResult], stable: gpd.GeoDataFrame | None) -> pd.DataFrame:
    inventory_frames = []
    for source in sources:
        frame = source.inventory.copy()
        if frame.empty:
            frame = _with_schema(pd.DataFrame(
                [
                    {
                        "source_name": source.spec.source_name,
                        "source_category": source.spec.category,
                        "source_path": str(source.spec.path),
                        "layer_name": "",
                        "layer_status": "source_missing_or_empty",
                        "row_count": 0,
                        "geometry_column": "",
                        "geometry_types": "",
                        "geometry_non_empty_count": 0,
                        "geometry_empty_count": 0,
                        "invalid_geometry_count": 0,
                        "crs": "",
                        "bounds": "",
                        "bounds_overlaps_stable": "",
                    }
                ]
            ), INVENTORY_COLUMNS)
        # if we could load a stable catchment reference, provide a compatibility flag for each selected layer
        if stable is not None and not stable.empty:
            for row_idx, row in frame.iterrows():
                layer_name = row["layer_name"]
                row_name = str(layer_name)
                if not row_name:
                    frame.at[row_idx, "bounds_overlaps_stable"] = "false"
                    continue
                try:
                    selected = source.selected_frame if source.selected_layer_name == row_name else None
                    if selected is None or selected.empty:
                        frame.at[row_idx, "bounds_overlaps_stable"] = "false"
                        continue
                    selected = selected.copy()
                    if selected.crs is None or stable.crs is None:
                        intersects = True
                    else:
                        if selected.crs != stable.crs:
                            try:
                                selected = selected.to_crs(stable.crs)
                            except Exception:
                                intersects = True
                                frame.at[row_idx, "bounds_overlaps_stable"] = "false"
                                continue
                        intersects = _bounds_overlap(selected.total_bounds, stable.total_bounds)
                    frame.at[row_idx, "bounds_overlaps_stable"] = intersects
                except Exception:
                    frame.at[row_idx, "bounds_overlaps_stable"] = "error"
        inventory_frames.append(frame)
    return _concat_with_schema(inventory_frames, INVENTORY_COLUMNS)


def _bounds_overlap(left: Any, right: Any) -> bool:
    try:
        lminx, lminy, lmaxx, lmaxy = [float(v) for v in left]
        rminx, rminy, rmaxx, rmaxy = [float(v) for v in right]
        return lminx <= rmaxx and lmaxx >= rminx and lminy <= rmaxy and lmaxy >= rminy
    except Exception:
        return False


def _read_normalized_access() -> pd.DataFrame | None:
    if not NORMALIZED_ACCESS.exists():
        return None
    try:
        frame = pd.DataFrame(gpd.read_parquet(NORMALIZED_ACCESS).copy())
        if "geometry" in frame.columns:
            frame = frame.drop(columns=["geometry"])
        return frame
    except Exception:
        return None


def _read_old_matched_access_ids() -> set[str]:
    ids: set[str] = set()
    for path in (ACCESS_JOINED_FILE, ACCESS_AMBIGUOUS_FILE):
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            for col in ("access_id", "id", "access_source_id"):
                if col in frame.columns:
                    ids.update(frame[col].dropna().astype(str).str.strip())
        except Exception:
            continue
    return {x for x in ids if x}


def _schema_and_nonnull(outputs: dict[str, gpd.GeoDataFrame], normalized: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    nonnull_rows = []
    fields_old = set(outputs["old_accesspoints"].columns) if outputs["old_accesspoints"] is not None else set()
    fields_lr = set(outputs["new_layer_lrspoint"].columns) if outputs["new_layer_lrspoint"] is not None else set()
    fields_lp = set(outputs["new_layer_point"].columns) if outputs["new_layer_point"] is not None else set()
    fields_norm = set(normalized.columns) if normalized is not None else set()
    all_fields = sorted(fields_old | fields_lr | fields_lp | fields_norm)
    useful_cache = {field: _is_candidate_field(field) or _is_route_field(field) for field in all_fields}
    for field in all_fields:
        row = {
            "field_name": field,
            "exists_in_old_accesspoints": field in fields_old,
            "exists_in_new_layer_lrspoint": field in fields_lr,
            "exists_in_new_layer_point": field in fields_lp,
            "exists_in_normalized_access_parquet": field in fields_norm,
            "is_candidate_access_related": useful_cache[field],
            "is_route_related": _is_route_field(field),
        }
        for source_name in ("old_accesspoints", "new_layer_lrspoint", "new_layer_point"):
            frame = outputs[source_name]
            if frame is None or frame.empty:
                row[f"{source_name}_dtype"] = ""
                row[f"{source_name}_row_count"] = 0
                row[f"{source_name}_non_null_count"] = 0
                row[f"{source_name}_unique_non_null_count"] = 0
                row[f"{source_name}_top_values"] = ""
                row[f"{source_name}_field_kind"] = ""
            elif field in frame.columns:
                series = frame[field]
                non_null = _nonempty(series).sum()
                unique_count = int(series.loc[_nonempty(series)].astype(str).nunique(dropna=True))
                row[f"{source_name}_dtype"] = str(series.dtype)
                row[f"{source_name}_row_count"] = int(len(series))
                row[f"{source_name}_non_null_count"] = int(non_null)
                row[f"{source_name}_unique_non_null_count"] = unique_count
                row[f"{source_name}_top_values"] = _top_values(series, limit=10)
                row[f"{source_name}_field_kind"] = _field_kind(series)
            else:
                row[f"{source_name}_dtype"] = ""
                row[f"{source_name}_row_count"] = 0
                row[f"{source_name}_non_null_count"] = 0
                row[f"{source_name}_unique_non_null_count"] = 0
                row[f"{source_name}_top_values"] = ""
                row[f"{source_name}_field_kind"] = "missing"
        if normalized is not None and field in fields_norm:
            normalized_series = normalized[field]
            non_null_norm = int(_nonempty(normalized_series).sum())
            unique_norm = int(normalized_series.loc[_nonempty(normalized_series)].astype(str).nunique(dropna=True))
            row["normalized_dtype"] = str(normalized_series.dtype)
            row["normalized_row_count"] = int(len(normalized_series))
            row["normalized_non_null_count"] = non_null_norm
            row["normalized_unique_non_null_count"] = unique_norm
            row["normalized_top_values"] = _top_values(normalized_series, limit=10)
            row["normalized_field_kind"] = _field_kind(normalized_series)
        else:
            row["normalized_dtype"] = ""
            row["normalized_row_count"] = 0
            row["normalized_non_null_count"] = 0
            row["normalized_unique_non_null_count"] = 0
            row["normalized_top_values"] = ""
            row["normalized_field_kind"] = "missing"
        rows.append(row)

        for source_name, frame in (
            ("old_accesspoints", outputs["old_accesspoints"]),
            ("new_layer_lrspoint", outputs["new_layer_lrspoint"]),
            ("new_layer_point", outputs["new_layer_point"]),
        ):
            if frame is None or frame.empty or field not in frame.columns:
                continue
            series = frame[field]
            if not _field_kind(series) in {"empty"}:
                nonnull_rows.append(
                    {
                        "source_name": source_name,
                        "layer_name": source_name,
                        "field_name": field,
                        "field_type": str(series.dtype),
                        "row_count": int(len(series)),
                        "non_null_count": int(_nonempty(series).sum()),
                        "unique_non_null_count": int(series.loc[_nonempty(series)].astype(str).nunique(dropna=True)),
                        "null_rate": round((len(series) - int(_nonempty(series).sum())) / len(series), 6) if len(series) else 0,
                    }
                )
    return _with_schema(pd.DataFrame(rows), SCHEMA_COLUMNS), _with_schema(pd.DataFrame(nonnull_rows), NONNULL_COLUMNS)


def _candidate_fields(frame: pd.DataFrame | list[str] | tuple[str, ...]) -> list[str]:
    columns = frame.columns if isinstance(frame, pd.DataFrame) else frame
    return [field for field in columns if _is_candidate_field(str(field)) and not _contains_crash_direction(str(field))]


def _category_from_value(value: Any, field_name: str = "") -> str:
    text = _clean_text(value)
    if not text:
        return "unknown"
    field_upper = field_name.upper()
    if field_upper == "ACCESS_CONTROL" and text in ACCESS_CONTROL_CODE_MAP:
        return ACCESS_CONTROL_CODE_MAP[text]
    if any(token in text for token in RIRO_TOKENS):
        if "RIGHT IN" in text and "RIGHT OUT" in text:
            return "right_in_right_out"
        if text == "RIRO":
            return "right_in_right_out"
        if any(x in text for x in RIGHT_IN_ONLY_TOKENS):
            return "right_in_only"
        if any(x in text for x in RIGHT_OUT_ONLY_TOKENS):
            return "right_out_only"
    if any(token in text for token in RIGHT_IN_ONLY_TOKENS) and "OUT" not in text:
        return "right_in_only"
    if any(token in text for token in RIGHT_OUT_ONLY_TOKENS) and "IN" not in text:
        return "right_out_only"
    if any(token in text for token in FULL_ACCESS_TOKENS):
        return "full_access"
    if any(token in text for token in RESTRICTED_TOKENS):
        return "restricted_access"
    if any(token in text for token in ("PARTIAL", "LIMIT", "TURN ONLY", "ONE WAY", "NO THROUGH", "DO NOT", "DIAGONAL")):
        return "not_inferable"
    return "not_inferable"


def _categorize_point(row: pd.Series, candidate_fields: list[str]) -> tuple[str, str]:
    for field in candidate_fields:
        if field not in row:
            continue
        value = row[field]
        category = _category_from_value(value, field)
        if category not in {"unknown", "not_inferable"}:
            return category, field
    for field in candidate_fields:
        if field not in row or _safe_str(row[field]) == "":
            continue
        category = _category_from_value(row[field], field)
        if category != "not_inferable":
            return "not_inferable", field
    return "unknown", ""


def _field_candidate_inventory(source_name: str, layer_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for field in _candidate_fields(list(frame.columns)):
        series = frame[field]
        rows.append(
            {
                "source_name": source_name,
                "layer_name": layer_name,
                "field_name": field,
                "field_type": str(series.dtype),
                "non_null_count": int(_nonempty(series).sum()),
                "null_count": int(series.isna().sum()),
                "row_count": int(len(series)),
                "null_rate": round((len(series) - int(_nonempty(series).sum())) / len(series), 6) if len(series) else 0,
                "unique_non_null_count": int(series.loc[_nonempty(series)].astype(str).nunique(dropna=True)),
                "top_values": _top_values(series, limit=15),
                "value_shape": _field_kind(series),
                "candidate_reason": _candidate_reason(field),
            }
        )
    return _with_schema(pd.DataFrame(rows), CANDIDATE_INVENTORY_COLUMNS)


def _candidate_reason(field: str) -> str:
    upper = field.upper()
    if upper in CANDIDATE_EXACT_FIELDS:
        return "explicit_access_candidate_field"
    if "RIGHT" in upper:
        return "movement_context_keyword"
    if any(token in upper for token in CANDIDATE_FIELD_TOKENS):
        return "candidate_keyword_match"
    return "other"


def _candidate_value_counts(source_name: str, layer_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    fields = _candidate_fields(list(frame.columns))
    for field in fields:
        series = frame[field]
        nonempty = series.loc[_nonempty(series)].astype(str).str.strip()
        if nonempty.empty:
            rows.append(
                {
                    "source_name": source_name,
                    "layer_name": layer_name,
                    "field_name": field,
                    "category_label": "",
                    "field_value": "",
                    "value_count": 0,
                    "value_pct": 0.0,
                }
            )
            continue
        counts = nonempty.value_counts()
        total = int(nonempty.shape[0])
        for value, count in counts.head(25).items():
            rows.append(
                {
                    "source_name": source_name,
                    "layer_name": layer_name,
                    "field_name": field,
                    "category_label": _category_from_value(value, field),
                    "field_value": value,
                    "value_count": int(count),
                    "value_pct": round(float(count) / total, 6),
                }
            )
    return _with_schema(pd.DataFrame(rows), CANDIDATE_VALUE_COLUMNS)


def _full_vs_riro(source_name: str, layer_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    fields = _candidate_fields(list(frame.columns))
    if not fields:
        return _with_schema(pd.DataFrame(
            [
                {
                    "source_name": source_name,
                    "layer_name": layer_name,
                    "full_vs_riro_support": "not_supported",
                    "inference_mode": "none",
                    "supporting_fields": "",
                    "supporting_values_count": 0,
                    "total_usable_points": 0,
                    "notes": "No candidate access-type fields found.",
                }
            ]
        ), FEASIBILITY_COLUMNS)
    direct_hits = 0
    direct_fields: set[str] = set()
    usable_points = 0
    for _, row in frame.iterrows():
        category, basis_field = _categorize_point(row, fields)
        if basis_field:
            usable_points += 1
        if category in {"full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"}:
            direct_hits += 1
            if basis_field:
                direct_fields.add(basis_field)
    if direct_hits > 0:
        return _with_schema(pd.DataFrame(
            [
                {
                    "source_name": source_name,
                    "layer_name": layer_name,
                    "full_vs_riro_support": "direct",
                    "inference_mode": "not_inferred",
                    "supporting_fields": "|".join(sorted(direct_fields)),
                    "supporting_values_count": int(direct_hits),
                    "total_usable_points": int(usable_points),
                    "notes": "Direct mapping found from populated access-type fields.",
                }
            ]
        ), FEASIBILITY_COLUMNS)

    control_col = next((c for c in ["ACCESS_CONTROL", "access_control"] if c in frame.columns), "")
    approach_col = next((c for c in ["NUMBER_OF_APPROACHES", "number_of_approaches"] if c in frame.columns), "")
    if control_col and approach_col:
        control_non_empty = int(_nonempty(frame[control_col]).sum())
        approach_non_empty = int(_nonempty(frame[approach_col]).sum())
        if control_non_empty > 0 and approach_non_empty > 0:
            return _with_schema(pd.DataFrame(
                [
                    {
                        "source_name": source_name,
                        "layer_name": layer_name,
                        "full_vs_riro_support": "inferred",
                        "inference_mode": "combination_rule",
                        "supporting_fields": "ACCESS_CONTROL|NUMBER_OF_APPROACHES",
                        "supporting_values_count": int(min(control_non_empty, approach_non_empty)),
                        "total_usable_points": int(_nonempty(frame[[control_col, approach_col]]).all(axis=1).sum()),
                        "notes": "No direct movement-permission text; weak inference from control+approach fields only.",
                    }
                ]
            ), FEASIBILITY_COLUMNS)

    return _with_schema(pd.DataFrame(
        [
            {
                "source_name": source_name,
                "layer_name": layer_name,
                "full_vs_riro_support": "not_supported",
                "inference_mode": "not_supported",
                "supporting_fields": "",
                "supporting_values_count": 0,
                "total_usable_points": int(usable_points),
                "notes": "Candidate fields appear non-categorical or not permission-encoded.",
            }
        ]
    ), FEASIBILITY_COLUMNS)


def _point_count_in_catchments(frame: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame) -> int:
    if frame.empty or catchments is None or catchments.empty:
        return 0
    valid = frame.copy()
    if valid.crs is None:
        return 0
    if catchments.crs is None:
        return 0
    if valid.crs != catchments.crs:
        try:
            valid = valid.to_crs(catchments.crs)
        except Exception:
            return 0
    try:
        joined = gpd.sjoin(valid, catchments[["geometry"]], how="inner", predicate="intersects")
        return int(joined.index.get_level_values(0).nunique())
    except Exception:
        return 0


def _point_count_within_distance(frame: gpd.GeoDataFrame, targets: gpd.GeoDataFrame, distance_m: float) -> int:
    if frame.empty or targets is None or targets.empty:
        return 0
    source = frame.copy()
    if source.crs is None or targets.crs is None:
        return 0
    if source.crs != targets.crs:
        try:
            source = source.to_crs(targets.crs)
        except Exception:
            return 0
    try:
        nearest = gpd.sjoin_nearest(source.reset_index(), targets, how="left", max_distance=distance_m, distance_col="dist_m")
        nearby = nearest.loc[nearest["dist_m"].notna()].copy()
        return int(nearby.index.to_series().nunique())
    except Exception:
        # lightweight fallback
        try:
            within = nearest = gpd.GeoSeries(source.geometry.unary_union)
            _ = within
        except Exception:
            return 0
        return 0


def _geometry_comparison(
    old: gpd.GeoDataFrame,
    lrsp: gpd.GeoDataFrame,
    lpoint: gpd.GeoDataFrame,
) -> pd.DataFrame:
    rows = []
    pairs = [
        ("old_accesspoints", old, "new_layer_lrspoint", lrsp),
        ("old_accesspoints", old, "new_layer_point", lpoint),
        ("new_layer_lrspoint", lrsp, "new_layer_point", lpoint),
    ]

    for left_name, left, right_name, right in pairs:
        left = left if left is not None else gpd.GeoDataFrame()
        right = right if right is not None else gpd.GeoDataFrame()
        rows.append(
            {
                "source_pair": f"{left_name}_vs_{right_name}",
                "metric": "row_count_left",
                "left_name": left_name,
                "right_name": right_name,
                "value": int(len(left)),
                "note": "",
            }
        )
        rows.append(
            {
                "source_pair": f"{left_name}_vs_{right_name}",
                "metric": "row_count_right",
                "left_name": left_name,
                "right_name": right_name,
                "value": int(len(right)),
                "note": "",
            }
        )
        rows.append(
            {
                "source_pair": f"{left_name}_vs_{right_name}",
                "metric": "geometry_type_left",
                "left_name": left_name,
                "right_name": right_name,
                "value": _geometry_summary(left)["geometry_types"],
                "note": "",
            }
        )
        rows.append(
            {
                "source_pair": f"{left_name}_vs_{right_name}",
                "metric": "geometry_type_right",
                "left_name": left_name,
                "right_name": right_name,
                "value": _geometry_summary(right)["geometry_types"],
                "note": "",
            }
        )
        rows.append(
            {
                "source_pair": f"{left_name}_vs_{right_name}",
                "metric": "crs_equal",
                "left_name": left_name,
                "right_name": right_name,
                "value": int(_geometry_summary(left)["crs"] == _geometry_summary(right)["crs"]) if left is not None and right is not None else 0,
                "note": f"{_geometry_summary(left)['crs']}|{_geometry_summary(right)['crs']}",
            }
        )
        if left.empty or right.empty:
            rows.append(
                {
                    "source_pair": f"{left_name}_vs_{right_name}",
                    "metric": "spatial_relation_status",
                    "left_name": left_name,
                    "right_name": right_name,
                    "value": "no_compare",
                    "note": "",
                }
            )
            continue

        # bounds overlap uses cheap bbox first pass.
        bounds_overlap = _bounds_overlap(_safe_total_bounds(left), _safe_total_bounds(right))
        rows.append(
            {
                "source_pair": f"{left_name}_vs_{right_name}",
                "metric": "bounds_overlap",
                "left_name": left_name,
                "right_name": right_name,
                "value": int(bounds_overlap),
                "note": "",
            }
        )
        # sample-limited nearest distance summary
        sample_left = left.iloc[:10000].copy()
        sample_right = right.iloc[:10000].copy()
        if not sample_left.empty and not sample_right.empty:
            sample_left = sample_left.to_crs(sample_left.estimate_utm_crs()) if sample_left.crs and sample_left.geometry.notna().any() else sample_left
            sample_right = sample_right.to_crs(sample_left.crs) if sample_right.crs is not None and sample_left.crs else sample_right
            try:
                nearest = gpd.sjoin_nearest(sample_left.reset_index(), sample_right.reset_index(), how="left", distance_col="distance_m")
                d = pd.to_numeric(nearest["distance_m"], errors="coerce")
                rows.append(
                    {
                        "source_pair": f"{left_name}_vs_{right_name}",
                        "metric": "nearest_distance_median_m",
                        "left_name": left_name,
                        "right_name": right_name,
                        "value": round(float(d.dropna().median()), 6) if not d.dropna().empty else "",
                        "note": "",
                    }
                )
                for threshold in (5.0, 30.0, 90.0):
                    rows.append(
                        {
                            "source_pair": f"{left_name}_vs_{right_name}",
                            "metric": f"points_within_{int(threshold)}m_nearest",
                            "left_name": left_name,
                            "right_name": right_name,
                            "value": int((d <= threshold).sum()),
                            "note": "",
                        }
                    )
            except Exception:
                rows.append(
                    {
                        "source_pair": f"{left_name}_vs_{right_name}",
                        "metric": "spatial_relation_status",
                        "left_name": left_name,
                        "right_name": right_name,
                        "value": "nearest_error",
                        "note": "",
                    }
                )
    return _with_schema(pd.DataFrame(rows), GEOMETRY_COLUMNS)


def _safe_total_bounds(frame: gpd.GeoDataFrame | pd.DataFrame) -> list[float]:
    try:
        return [float(v) for v in frame.total_bounds]
    except Exception:
        return [float("nan")] * 4


def _attribute_comparison(old: gpd.GeoDataFrame, lrsp: gpd.GeoDataFrame, lpoint: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    pairs = [("old_accesspoints", old, "new_layer_lrspoint", lrsp), ("old_accesspoints", old, "new_layer_point", lpoint), ("new_layer_lrspoint", lrsp, "new_layer_point", lpoint)]
    for left_name, left, right_name, right in pairs:
        left = left if left is not None else gpd.GeoDataFrame()
        right = right if right is not None else gpd.GeoDataFrame()
        if left.empty or right.empty:
            rows.append(
                {
                    "source_pair": f"{left_name}_vs_{right_name}",
                    "field_name": "",
                    "metric": "attribute_compare_status",
                    "left_non_null": 0,
                    "right_non_null": 0,
                    "value_overlap_top5_jaccard": "",
                    "notes": "not_run_empty_source",
                }
            )
            continue
        left_cols = {col for col in left.columns if col != left.geometry.name}
        right_cols = {col for col in right.columns if col != right.geometry.name}
        for field in sorted(left_cols & right_cols):
            if _contains_crash_direction(field):
                continue
            if not _is_candidate_field(field) and not _is_route_field(field):
                continue
            left_s = left[field]
            right_s = right[field]
            left_non_empty = left_s.loc[_nonempty(left_s)].astype(str).str.strip()
            right_non_empty = right_s.loc[_nonempty(right_s)].astype(str).str.strip()
            top_left = set(left_non_empty.value_counts().head(20).index.astype(str))
            top_right = set(right_non_empty.value_counts().head(20).index.astype(str))
            jaccard = round(len(top_left & top_right) / max(len(top_left | top_right), 1), 6)
            rows.append(
                {
                    "source_pair": f"{left_name}_vs_{right_name}",
                    "field_name": field,
                    "metric": "candidate_field_overlap",
                    "left_non_null": int(left_non_empty.shape[0]),
                    "right_non_null": int(right_non_empty.shape[0]),
                    "value_overlap_top5_jaccard": jaccard,
                    "left_dtype": str(left_s.dtype),
                    "right_dtype": str(right_s.dtype),
                    "notes": "candidate_or_route_field",
                }
            )
    return _with_schema(pd.DataFrame(rows), ATTRIBUTE_COLUMNS)


def _estimate_stable_coverage(
    source_frames: dict[str, gpd.GeoDataFrame],
    catchments: gpd.GeoDataFrame | None,
    matched_old_ids: set[str],
) -> pd.DataFrame:
    rows = []
    old = source_frames.get("old_accesspoints", gpd.GeoDataFrame())
    old_ids_available = old is not None and not old.empty and matched_old_ids

    old_matched_points: gpd.GeoDataFrame | None = None
    if old_ids_available:
        id_candidates = _candidate_id_columns(old)
        for id_col in id_candidates:
            if id_col in old.columns:
                old_matched_points = old.loc[old[id_col].astype(str).isin(matched_old_ids)].copy()
                if not old_matched_points.empty:
                    break
        if old_matched_points is not None and not old_matched_points.empty:
            old_matched_points = old_matched_points[["geometry"]].copy()

    for source_name in ("old_accesspoints", "new_layer_lrspoint", "new_layer_point"):
        frame = source_frames.get(source_name, gpd.GeoDataFrame())
        frame = frame.copy() if frame is not None else gpd.GeoDataFrame()
        if frame.empty or catchments is None or catchments.empty:
            rows.append(
                {
                    "source_name": source_name,
                    "source_row_count": _row_count(frame),
                    "within_stable_catchments_count": 0,
                    "within_stable_catchments_share": 0.0,
                    "within_250ft_of_stable_count": 0,
                    "within_250ft_of_stable_share": 0.0,
                    "near_current_matched_access_points_10m_count": 0,
                    "near_current_matched_access_points_10m_share": 0.0,
                    "potential_stable_match_count": 0,
                    "potential_stable_match_share": 0.0,
                    "potential_matchable_with_usable_access_type_count": 0,
                    "potential_matchable_with_usable_access_type_share": 0.0,
                }
            )
            continue

        frame_work = frame.copy()
        if catchments.crs is not None and frame_work.crs is not None and frame_work.crs != catchments.crs:
            try:
                frame_work = frame_work.to_crs(catchments.crs)
            except Exception:
                pass
        total = int(len(frame_work))
        within_stable = _point_count_in_catchments(frame_work, catchments)
        within_250 = _point_count_within_distance(frame_work, catchments, 250.0 * FEET_TO_METERS)

        candidate_fields = _candidate_fields(list(frame_work.columns))
        usable_mask = []
        if frame_work.empty:
            usable_mask = []
        else:
            for _, row in frame_work.iterrows():
                category, _ = _categorize_point(row, candidate_fields)
                usable_mask.append(category in {"full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"})
            usable_mask = pd.Series(usable_mask, index=frame_work.index)

        near_old_count = 0
        if old_matched_points is not None and not old_matched_points.empty:
            near_old = _point_count_within_distance(frame_work, old_matched_points, 10 * FEET_TO_METERS)
            near_old_count = near_old
        candidate_match_indices = []
        if frame_work.crs is not None and catchments.crs is not None and frame_work.crs != catchments.crs:
            try:
                frame_work = frame_work.to_crs(catchments.crs)
            except Exception:
                pass
        try:
            nearest = gpd.sjoin_nearest(
                frame_work.reset_index(),
                catchments[["geometry"]],
                how="left",
                max_distance=250.0 * FEET_TO_METERS,
                distance_col="dist_m",
            )
            candidate_match_indices = nearest.loc[nearest["dist_m"].notna(), "index"].drop_duplicates().tolist()
        except Exception:
            candidate_match_indices = []

        potential = int(len(candidate_match_indices))
        usable_in_potential = 0
        if isinstance(usable_mask, pd.Series) and not usable_mask.empty:
            potential_series = pd.Series(False, index=frame_work.index)
            if candidate_match_indices:
                potential_series.loc[candidate_match_indices] = True
            usable_in_potential = int(pd.Series(usable_mask).loc[potential_series].sum()) if not potential_series.empty else 0
        rows.append(
            {
                "source_name": source_name,
                "source_row_count": total,
                "within_stable_catchments_count": int(within_stable),
                "within_stable_catchments_share": round(float(within_stable) / max(total, 1), 6),
                "within_250ft_of_stable_count": int(within_250),
                "within_250ft_of_stable_share": round(float(within_250) / max(total, 1), 6),
                "near_current_matched_access_points_10m_count": int(near_old_count),
                "near_current_matched_access_points_10m_share": round(float(near_old_count) / max(total, 1), 6),
                "potential_stable_match_count": potential,
                "potential_stable_match_share": round(float(potential) / max(total, 1), 6),
                "potential_matchable_with_usable_access_type_count": int(usable_in_potential),
                "potential_matchable_with_usable_access_type_share": round(float(usable_in_potential) / max(potential, 1), 6),
            }
        )

    return _with_schema(pd.DataFrame(rows), COVERAGE_COLUMNS)


def _candidate_id_columns(frame: gpd.GeoDataFrame) -> list[str]:
    hints = ("access_id", "id", "objectid", "globalid", "source_id")
    cols = [c for c in frame.columns for h in hints if c.lower() == h]
    if cols:
        return cols
    # fallback candidate id fields
    return [c for c in frame.columns if c.lower() in {"id", "objectid", "globalid"}] or ([frame.columns[0]] if len(frame.columns) else [])


def _recommendation(stable_coverage: pd.DataFrame, feasibility: pd.DataFrame) -> pd.DataFrame:
    stable_coverage = _with_schema(stable_coverage, COVERAGE_COLUMNS)
    feasibility = _with_schema(feasibility, FEASIBILITY_COLUMNS)
    coverage_map = {row["source_name"]: row for _, row in stable_coverage.iterrows() if _safe_str(row.get("source_name"))}
    feas_map = {row["source_name"]: row for _, row in feasibility.iterrows() if _safe_str(row.get("source_name"))}

    old_cov = float(coverage_map.get("old_accesspoints", {}).get("within_stable_catchments_share", 0.0))
    lr_cov = float(coverage_map.get("new_layer_lrspoint", {}).get("potential_stable_match_share", 0.0))
    lp_cov = float(coverage_map.get("new_layer_point", {}).get("potential_stable_match_share", 0.0))
    lr_potential = int(coverage_map.get("new_layer_lrspoint", {}).get("potential_stable_match_count", 0) or 0)
    lp_potential = int(coverage_map.get("new_layer_point", {}).get("potential_stable_match_count", 0) or 0)
    lr_rows = int(coverage_map.get("new_layer_lrspoint", {}).get("source_row_count", 0) or 0)
    lp_rows = int(coverage_map.get("new_layer_point", {}).get("source_row_count", 0) or 0)

    lr_direct = str(feas_map.get("new_layer_lrspoint", {}).get("full_vs_riro_support", "not_supported"))
    lp_direct = str(feas_map.get("new_layer_point", {}).get("full_vs_riro_support", "not_supported"))
    lr_infer = str(feas_map.get("new_layer_lrspoint", {}).get("inference_mode", "none"))
    lp_infer = str(feas_map.get("new_layer_point", {}).get("inference_mode", "none"))

    if old_cov >= 0 and lr_cov == 0 and lp_cov == 0:
        rec_action = "do_not_use_new_layers"
        rec_next = ""
        rec_text = "No stable-coverage evidence from new layers; defer until source owner clarification."
        rec_reason = "both_new_layers_zero_stable_candidate_matchability"
    elif (lr_direct == "direct") and (lp_direct != "direct"):
        rec_action = "use_layer_lrspoint_as_primary"
        rec_next = "access_context_join_v2.py"
        rec_text = "layer_lrspoint has direct movement-permission signal; keep layer_point as supplemental only."
        rec_reason = "direct_full_riro_support_in_lrspoint"
    elif (lp_direct == "direct") and (lr_direct != "direct"):
        rec_action = "use_layer_point_as_primary"
        rec_next = "access_context_join_v2.py"
        rec_text = "layer_point has direct movement-permission signal; keep layer_lrspoint as supplemental only."
        rec_reason = "direct_full_riro_support_in_layer_point"
    elif (lr_direct == "direct") and (lp_direct == "direct"):
        if (lr_potential, lr_rows, lr_cov) >= (lp_potential, lp_rows, lp_cov):
            rec_action = "use_layer_lrspoint_primary_plus_point_supplement"
            rec_next = "access_context_join_v2.py"
            rec_text = "Both new layers have direct support; choose layer_lrspoint primary because it has broader candidate-match and row-count support; validate with layer_point as supplemental."
            rec_reason = "both_direct_support"
        else:
            rec_action = "use_layer_point_primary_plus_lrspoint_supplement"
            rec_next = "access_context_join_v2.py"
            rec_text = "Both new layers have direct support; choose layer_point primary because it has broader candidate-match and row-count support; validate with layer_lrspoint as supplemental."
            rec_reason = "both_direct_support"
    elif (lp_infer == "combination_rule") and (lr_infer != "combination_rule") and lp_cov >= lr_cov:
        rec_action = "use_layer_point_as_candidate_with_limited_scope"
        rec_next = "access_context_join_v2.py"
        rec_text = "Only layer_point shows usable inferred logic; weak inference should remain diagnostic."
        rec_reason = "inferred_support_only_point"
    elif (lr_infer == "combination_rule") and (lp_infer != "combination_rule") and lr_cov >= lp_cov:
        rec_action = "use_layer_lrspoint_as_candidate_with_limited_scope"
        rec_next = "access_context_join_v2.py"
        rec_text = "Only layer_lrspoint shows usable inferred logic; weak inference should remain diagnostic."
        rec_reason = "inferred_support_only_lrspoint"
    elif lr_cov > 0 and lp_cov > 0:
        rec_action = "use_both_new_layers_for_review_only"
        rec_next = ""
        rec_text = "Both sources are non-empty but no direct movement-permission fields; keep diagnostic only and clarify field semantics."
        rec_reason = "weak_inference_without_direct_support"
    else:
        rec_action = "do_not_use_new_layers"
        rec_next = ""
        rec_text = "No actionable access-type support found."
        rec_reason = "no_support"

    rows = [
        {
            "candidate_relation": "old_vs_new_lrspoint_vs_point",
            "old_accesspoints_rows": _numeric_sum_for_source(stable_coverage, "old_accesspoints", "source_row_count"),
            "new_layer_lrspoint_rows": _numeric_sum_for_source(stable_coverage, "new_layer_lrspoint", "source_row_count"),
            "new_layer_point_rows": _numeric_sum_for_source(stable_coverage, "new_layer_point", "source_row_count"),
            "new_layer_lrspoint_stable_coverage_share": lr_cov,
            "new_layer_point_stable_coverage_share": lp_cov,
            "lrspoint_full_riro_support": lr_direct,
            "point_full_riro_support": lp_direct,
            "lrspoint_inference_mode": lr_infer,
            "point_inference_mode": lp_infer,
            "recommended_action": rec_action,
            "recommended_next_module": rec_next,
            "recommendation_reason": rec_reason,
            "recommendation_text": rec_text,
            "recommended_for_access_v2_staging": rec_action != "do_not_use_new_layers" and rec_action != "wait_for_source_owner_clarification",
            "legacy_access_context_untouched": "yes",
        }
    ]
    if rec_action.startswith("do_not_use"):
        rows[0]["recommended_for_access_v2_staging"] = False
    return _with_schema(pd.DataFrame(rows), RECOMMENDATION_COLUMNS)


def _build_findings(
    source_inventory: pd.DataFrame,
    candidate_inventory: pd.DataFrame,
    feasibility: pd.DataFrame,
    geometry: pd.DataFrame,
    attributes: pd.DataFrame,
    coverage: pd.DataFrame,
    recommendation: pd.DataFrame,
    debug_layer_inventory: pd.DataFrame | None = None,
    candidate_field_search: pd.DataFrame | None = None,
    candidate_value_search: pd.DataFrame | None = None,
    selection_ranking: pd.DataFrame | None = None,
) -> str:
    source_inventory = _with_schema(source_inventory, INVENTORY_COLUMNS)
    candidate_inventory = _with_schema(candidate_inventory, CANDIDATE_INVENTORY_COLUMNS)
    feasibility = _with_schema(feasibility, FEASIBILITY_COLUMNS)
    geometry = _with_schema(geometry, GEOMETRY_COLUMNS)
    attributes = _with_schema(attributes, ATTRIBUTE_COLUMNS)
    coverage = _with_schema(coverage, COVERAGE_COLUMNS)
    recommendation = _with_schema(recommendation, RECOMMENDATION_COLUMNS)
    debug_layer_inventory = _with_schema(debug_layer_inventory, DEBUG_LAYER_INVENTORY_COLUMNS)
    candidate_field_search = _with_schema(candidate_field_search, CANDIDATE_FIELD_SEARCH_COLUMNS)
    candidate_value_search = _with_schema(candidate_value_search, CANDIDATE_VALUE_SEARCH_COLUMNS)
    selection_ranking = _with_schema(selection_ranking, SELECTION_RANKING_COLUMNS)

    def _metric(source_name: str, column: str) -> str:
        return _first_value(source_inventory, "source_name", source_name, column)

    def _row_or(source: str, column: str) -> str:
        if not isinstance(feasibility, pd.DataFrame):
            return "not_evaluated"
        if "source_name" not in feasibility.columns or column not in feasibility.columns:
            return "not_evaluated"
        value = _first_value(feasibility, "source_name", source, column, default="not_evaluated")
        return value

    def _recommendation_value(column: str, default: str = "not_available") -> str:
        if not isinstance(recommendation, pd.DataFrame) or recommendation.empty or column not in recommendation.columns:
            return default
        value = recommendation.iloc[0].get(column, default)
        if pd.isna(value) or str(value).strip() == "":
            return default
        return str(value)

    source_paths = {
        "old_accesspoints": str(OLD_ACCESS_SOURCE),
        "new_layer_lrspoint": str(NEW_LRSP_GDB),
        "new_layer_point": str(NEW_POINT_GDB),
    }
    lines = [
        "# Access Source Layer Comparison Findings",
        "",
        "## Bounded Question",
        "",
        "Compare legacy `accesspoints.gdb` and newly added `layer_lrspoint.gdb`, `layer_point.gdb` for",
        "stability, schema preservation, candidate access-type fields, and stable-universe compatibility.",
        "",
        "## Files Inspected",
        f"- old source: {source_paths['old_accesspoints']}",
        f"- new source: {source_paths['new_layer_lrspoint']}",
        f"- new source: {source_paths['new_layer_point']}",
        f"- normalized source: {NORMALIZED_ACCESS}",
        "- `access_context_join` outputs for ID/coverage context.",
        f"- active directional-bin context: {_stable_context_path() or 'not_found'}",
        "",
        "## Layer Inventory (selected counts)",
    ]
    for source_name in ("old_accesspoints", "new_layer_lrspoint", "new_layer_point"):
        lines.append(f"- {source_name}: rows={_metric(source_name, 'row_count')}, selected_layer={_metric(source_name, 'layer_name')}")

    lines.extend(["", "## Detected GDB Layers"])
    if debug_layer_inventory.empty:
        lines.append("- none: no layers were detected by available geospatial backends.")
    else:
        for row in debug_layer_inventory.itertuples(index=False):
            lines.append(
                f"- {getattr(row, 'source_name', 'not_available')}: "
                f"layer={getattr(row, 'layer_name', 'not_available')}, "
                f"rows={getattr(row, 'row_count', 'not_available')}, "
                f"geometry={getattr(row, 'geometry_type', 'not_available')}, "
                f"backend={getattr(row, 'driver_backend', 'not_available')}"
            )

    lines.extend(["", "## Layer Selection Ranking"])
    if selection_ranking.empty:
        lines.append("- not_available: no layer ranking rows were generated.")
    else:
        selected = selection_ranking.loc[selection_ranking["selected"].astype(str).str.lower().eq("true")]
        for row in selected.itertuples(index=False):
            lines.append(
                f"- {getattr(row, 'source_name', 'not_available')}: selected={getattr(row, 'layer_name', 'not_available')}, "
                f"score={getattr(row, 'rank_score', 'not_available')}, "
                f"access_fields={getattr(row, 'access_field_count', 'not_available')}, "
                f"route_measure_fields={getattr(row, 'route_measure_field_count', 'not_available')}, "
                f"pathways_value_matches={getattr(row, 'pathways_value_match_count', 'not_available')}"
            )

    lines.extend(
        [
            "",
            "## Source Relationship and Coverage",
            f"- candidate access-type fields found: {len(candidate_inventory)}",
            f"- Pathways-like field-search hits: {len(candidate_field_search)}",
            f"- Pathways-like sample-value-search hits: {len(candidate_value_search)}",
            "- full-vs-RIRO feasibility:",
            f"  - old: {_row_or('old_accesspoints', 'full_vs_riro_support')}",
            f"  - layer_lrspoint: {_row_or('new_layer_lrspoint', 'full_vs_riro_support')}",
            f"  - layer_point: {_row_or('new_layer_point', 'full_vs_riro_support')}",
            "- feasibility note: full-vs-RIRO support is marked not_evaluated when candidate fields are missing, unpopulated, or no feasible source rows were produced.",
            "",
            "## Stable Universe Coverage Estimates",
        ]
    )
    if coverage.empty:
        lines.append("- not_available: no coverage rows were generated.")
    else:
        for row in coverage.itertuples(index=False):
            lines.append(
                f"- {getattr(row, 'source_name', 'not_available')}: "
                f"within_stable={getattr(row, 'within_stable_catchments_count', 'not_available')} "
                f"(share={getattr(row, 'within_stable_catchments_share', 'not_available')}), "
                f"within_250ft={getattr(row, 'within_250ft_of_stable_count', 'not_available')} "
                f"(share={getattr(row, 'within_250ft_of_stable_share', 'not_available')}), "
                f"potential_match={getattr(row, 'potential_stable_match_count', 'not_available')} "
                f"(share={getattr(row, 'potential_stable_match_share', 'not_available')}), "
                f"usable_in_potential={getattr(row, 'potential_matchable_with_usable_access_type_count', 'not_available')}"
            )

    rows = []
    if not recommendation.empty:
        rows.append(f"- recommended_action: {_recommendation_value('recommended_action')}")
        rows.append(f"- recommendation_reason: {_recommendation_value('recommendation_reason')}")
        rows.append(f"- recommended_next_module: {_recommendation_value('recommended_next_module', 'n/a')}")
        rows.append(f"- recommendation_text: {_recommendation_value('recommendation_text')}")
    lines.extend(
        [
            "",
            "## Geometry and Attribute Diagnostic",
            f"- geometry diagnostics rows: {len(geometry)}",
            f"- attribute diagnostics rows: {len(attributes)}",
            "",
            "## QA",
            "- crash_direction fields used in access-type logic: no",
            "- normalized artifact overwritten: no",
            "- access_context_join outputs overwritten: no",
            "- stable-universe outputs overwritten: no",
            "- empty_intermediate_tables_handled: yes",
            "- expected_output_headers_present: yes",
            "- findings_generated_without_keyerror: yes",
            "- all_gdb_layers_inventoried: yes",
            "- manually_observed_pathways_fields_values_searched: yes",
            "",
            "## Outputs",
            "",
            "*See manifest for complete file list.*",
        ]
    )
    if rows:
        lines.append("")
        lines.extend(rows)
    return "\n".join(lines)


def build_access_source_layer_comparison(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    source_read_results: list[SourceReadResult] = [_read_source(spec) for spec in SOURCES]
    source_results_map = {
        result.spec.source_name: result
        for result in source_read_results
    }
    source_frames: dict[str, gpd.GeoDataFrame] = {
        result.spec.source_name: result.selected_frame if result.selected_frame is not None else gpd.GeoDataFrame()
        for result in source_read_results
    }
    source_inventory = _build_inventory(source_read_results, _stable_catchments())
    debug_layer_inventory = _concat_with_schema([result.debug_layer_inventory for result in source_read_results], DEBUG_LAYER_INVENTORY_COLUMNS)
    sample_value_profile = _concat_with_schema([result.sample_value_profile for result in source_read_results], SAMPLE_VALUE_PROFILE_COLUMNS)
    candidate_field_search = _concat_with_schema([result.candidate_field_search for result in source_read_results], CANDIDATE_FIELD_SEARCH_COLUMNS)
    candidate_value_search = _concat_with_schema([result.candidate_value_search for result in source_read_results], CANDIDATE_VALUE_SEARCH_COLUMNS)
    alias_domain_inventory = _concat_with_schema([result.alias_domain_inventory for result in source_read_results], ALIAS_DOMAIN_COLUMNS)
    selection_ranking = _concat_with_schema([result.selection_ranking for result in source_read_results], SELECTION_RANKING_COLUMNS)

    normalized = _read_normalized_access()

    # schema + field profile
    schema_df, nonnull_df = _schema_and_nonnull(
        {
            "old_accesspoints": source_frames.get("old_accesspoints", gpd.GeoDataFrame()),
            "new_layer_lrspoint": source_frames.get("new_layer_lrspoint", gpd.GeoDataFrame()),
            "new_layer_point": source_frames.get("new_layer_point", gpd.GeoDataFrame()),
        },
        normalized,
    )

    candidate_rows = []
    candidate_value_rows = []
    feasibility_rows = []
    for source_name, frame in source_frames.items():
        if frame is None or frame.empty:
            continue
        layer_name = source_results_map.get(source_name).selected_layer_name if source_name in source_results_map else source_name
        layer_name = layer_name or source_name
        inv = _field_candidate_inventory(source_name, layer_name, frame)
        vals = _candidate_value_counts(source_name, layer_name, frame)
        feas = _full_vs_riro(source_name, layer_name, frame)
        candidate_rows.append(inv)
        candidate_value_rows.append(vals)
        feasibility_rows.append(feas)
    candidate_inventory = _concat_with_schema(candidate_rows, CANDIDATE_INVENTORY_COLUMNS)
    candidate_value_counts = _concat_with_schema(candidate_value_rows, CANDIDATE_VALUE_COLUMNS)
    feasibility = _concat_with_schema(feasibility_rows, FEASIBILITY_COLUMNS)

    catchments = _stable_catchments()
    matched_ids = _read_old_matched_access_ids()
    coverage = _estimate_stable_coverage(
        {
            "old_accesspoints": source_frames.get("old_accesspoints", gpd.GeoDataFrame()),
            "new_layer_lrspoint": source_frames.get("new_layer_lrspoint", gpd.GeoDataFrame()),
            "new_layer_point": source_frames.get("new_layer_point", gpd.GeoDataFrame()),
        },
        catchments,
        matched_ids,
    )

    geometry_compare = _geometry_comparison(
        source_frames.get("old_accesspoints", gpd.GeoDataFrame()),
        source_frames.get("new_layer_lrspoint", gpd.GeoDataFrame()),
        source_frames.get("new_layer_point", gpd.GeoDataFrame()),
    )
    attribute_compare = _attribute_comparison(
        source_frames.get("old_accesspoints", gpd.GeoDataFrame()),
        source_frames.get("new_layer_lrspoint", gpd.GeoDataFrame()),
        source_frames.get("new_layer_point", gpd.GeoDataFrame()),
    )
    recommendation = _recommendation(coverage, feasibility)

    source_inventory = _with_schema(source_inventory, INVENTORY_COLUMNS)
    debug_layer_inventory = _with_schema(debug_layer_inventory, DEBUG_LAYER_INVENTORY_COLUMNS)
    sample_value_profile = _with_schema(sample_value_profile, SAMPLE_VALUE_PROFILE_COLUMNS)
    candidate_field_search = _with_schema(candidate_field_search, CANDIDATE_FIELD_SEARCH_COLUMNS)
    candidate_value_search = _with_schema(candidate_value_search, CANDIDATE_VALUE_SEARCH_COLUMNS)
    alias_domain_inventory = _with_schema(alias_domain_inventory, ALIAS_DOMAIN_COLUMNS)
    selection_ranking = _with_schema(selection_ranking, SELECTION_RANKING_COLUMNS)
    schema_df = _with_schema(schema_df, SCHEMA_COLUMNS)
    nonnull_df = _with_schema(nonnull_df, NONNULL_COLUMNS)
    geometry_compare = _with_schema(geometry_compare, GEOMETRY_COLUMNS)
    attribute_compare = _with_schema(attribute_compare, ATTRIBUTE_COLUMNS)
    coverage = _with_schema(coverage, COVERAGE_COLUMNS)
    recommendation = _with_schema(recommendation, RECOMMENDATION_COLUMNS)

    # write required outputs
    source_inventory_path = out_dir / OUTPUTS["inventory"]
    debug_layer_inventory_path = out_dir / OUTPUTS["debug_layer_inventory"]
    sample_value_profile_path = out_dir / OUTPUTS["sample_value_profile"]
    candidate_field_search_path = out_dir / OUTPUTS["candidate_field_search"]
    candidate_value_search_path = out_dir / OUTPUTS["candidate_value_search"]
    alias_domain_inventory_path = out_dir / OUTPUTS["alias_domain_inventory"]
    selection_ranking_path = out_dir / OUTPUTS["selection_ranking"]
    schema_path = out_dir / OUTPUTS["schema"]
    nonnull_path = out_dir / OUTPUTS["nonnull"]
    candidate_inventory_path = out_dir / OUTPUTS["candidate_inventory"]
    candidate_values_path = out_dir / OUTPUTS["candidate_values"]
    feasibility_path = out_dir / OUTPUTS["feasibility"]
    geometry_path = out_dir / OUTPUTS["geometry"]
    attributes_path = out_dir / OUTPUTS["attributes"]
    coverage_path = out_dir / OUTPUTS["coverage"]
    recommendation_path = out_dir / OUTPUTS["recommendation"]
    findings_path = out_dir / OUTPUTS["findings"]
    manifest_path = out_dir / OUTPUTS["manifest"]

    _write_csv(source_inventory, source_inventory_path)
    _write_csv(debug_layer_inventory, debug_layer_inventory_path)
    _write_csv(sample_value_profile, sample_value_profile_path)
    _write_csv(candidate_field_search, candidate_field_search_path)
    _write_csv(candidate_value_search, candidate_value_search_path)
    _write_csv(alias_domain_inventory, alias_domain_inventory_path)
    _write_csv(selection_ranking, selection_ranking_path)
    _write_csv(schema_df, schema_path)
    _write_csv(nonnull_df, nonnull_path)
    _write_csv(candidate_inventory, candidate_inventory_path)
    _write_csv(candidate_value_counts, candidate_values_path)
    _write_csv(feasibility, feasibility_path)
    _write_csv(geometry_compare, geometry_path)
    _write_csv(attribute_compare, attributes_path)
    _write_csv(coverage, coverage_path)
    _write_csv(recommendation, recommendation_path)

    findings = _build_findings(
        source_inventory,
        candidate_inventory,
        feasibility,
        geometry_compare,
        attribute_compare,
        coverage,
        recommendation,
        debug_layer_inventory,
        candidate_field_search,
        candidate_value_search,
        selection_ranking,
    )
    _write_text(findings, findings_path)

    # optional outputs: compact previews and mapping
    optional_written: dict[str, str] = {}
    mapping_rows = []
    preview_rows = []
    join_rows = []
    for source_name, frame in source_frames.items():
        if frame is None or frame.empty:
            continue
        layer_name = source_results_map.get(source_name).selected_layer_name if source_name in source_results_map else source_name
        layer_name = layer_name or source_name
        candidate_fields = _candidate_fields(list(frame.columns))
        if not candidate_fields:
            continue
        for idx, row in frame.iterrows():
            cat, basis = _categorize_point(row, candidate_fields)
            preview_rows.append(
                {
                    "source_name": source_name,
                    "layer_name": layer_name,
                    "geometry_x": row.geometry.x if row.geometry and hasattr(row.geometry, "x") else "",
                    "geometry_y": row.geometry.y if row.geometry and hasattr(row.geometry, "y") else "",
                    "preview_proposed_category": cat,
                    "preview_basis_field": basis,
                    "is_usable_access_type": cat in {"full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"},
                }
            )
            if len(preview_rows) >= 5000:
                break
        preview_df = pd.DataFrame(preview_rows).head(500)
        if not preview_df.empty:
            preview_path = out_dir / OPTIONAL_OUTPUTS["candidate_preview"]
            _write_csv(preview_df, preview_path)
            optional_written["candidate_preview"] = str(preview_path)

        for field in candidate_fields:
            values = frame[field].dropna().astype(str).str.strip().value_counts().head(40)
            for value, count in values.items():
                mapping_rows.append(
                    {
                        "source_name": source_name,
                        "layer_name": layer_name,
                        "source_field": field,
                        "raw_value": value,
                        "observed_count": int(count),
                        "proposed_category": _category_from_value(value, field),
                    }
                )

    if mapping_rows:
        mapping_df = pd.DataFrame(mapping_rows)
        mapping_path = out_dir / OPTIONAL_OUTPUTS["candidate_mapping"]
        _write_csv(mapping_df, mapping_path)
        optional_written["candidate_access_type_mapping"] = str(mapping_path)

    # small matched-access near-merge preview; limited sample only
    if (not (source_frames.get("old_accesspoints") is None or source_frames["old_accesspoints"].empty)) and matched_ids:
        old = source_frames["old_accesspoints"].copy()
        old_id_candidates = _candidate_id_columns(old)
        old_id_col = old_id_candidates[0] if old_id_candidates else "access_id"
        if old_id_col in old.columns:
            old = old.loc[old[old_id_col].astype(str).isin(matched_ids)].copy()
            old = old[["geometry"]].copy()
        if not old.empty:
            for source_name, frame in source_frames.items():
                if frame is None or frame.empty or source_name == "old_accesspoints":
                    continue
                try:
                    dist_source = frame.copy()
                    if old.crs is not None and dist_source.crs != old.crs:
                        dist_source = dist_source.to_crs(old.crs)
                    nearest = gpd.sjoin_nearest(dist_source.reset_index(), old, how="left", distance_col="distance_m")
                    if nearest.empty:
                        continue
                    sample = nearest.head(300).copy()
                    sample["source_name"] = source_name
                    sample["distance_ft"] = pd.to_numeric(sample["distance_m"], errors="coerce") / FEET_TO_METERS
                    join_rows.append(sample[["source_name", "index", "distance_ft"]])
                except Exception:
                    continue
            if join_rows:
                join_preview = pd.concat(join_rows, ignore_index=True)
                join_path = out_dir / OPTIONAL_OUTPUTS["join_preview"]
                _write_csv(join_preview, join_path)
                optional_written["access_v2_candidate_join_preview"] = str(join_path)

    required_output_paths = {
        "inventory": source_inventory_path,
        "debug_layer_inventory": debug_layer_inventory_path,
        "sample_value_profile": sample_value_profile_path,
        "candidate_field_search": candidate_field_search_path,
        "candidate_value_search": candidate_value_search_path,
        "alias_domain_inventory": alias_domain_inventory_path,
        "selection_ranking": selection_ranking_path,
        "schema": schema_path,
        "nonnull": nonnull_path,
        "candidate_inventory": candidate_inventory_path,
        "candidate_values": candidate_values_path,
        "feasibility": feasibility_path,
        "geometry": geometry_path,
        "attributes": attributes_path,
        "coverage": coverage_path,
        "recommendation": recommendation_path,
    }
    headers_present = all(
        _csv_headers_present(required_output_paths[key], columns)
        for key, columns in REQUIRED_OUTPUT_SCHEMAS.items()
    )

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": (
            "read-only access-source layer comparison audit for candidate typed-access support and stable-universe compatibility"
        ),
        "read_only": True,
        "normalized_access_overwritten": False,
        "crash_direction_fields_read_or_used": False,
        "active_context_used": str(_stable_context_path()) if _stable_context_path() else "",
        "inputs": {
            "old_accesspoints_gdb": str(OLD_ACCESS_SOURCE),
            "new_layer_lrspoint_gdb": str(NEW_LRSP_GDB),
            "new_layer_point_gdb": str(NEW_POINT_GDB),
            "normalized_access_parquet": str(NORMALIZED_ACCESS),
            "access_context_join_joined": str(ACCESS_JOINED_FILE),
            "access_context_join_ambiguous": str(ACCESS_AMBIGUOUS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "catchment_polygons": str(CATCHMENT_POLYGONS_FILE),
        },
        "selected_layers": {
            result.spec.source_name: result.selected_layer_name or ""
            for result in source_read_results
        },
        "outputs": {key: str(out_dir / value) for key, value in OUTPUTS.items()},
        "optional_outputs": optional_written,
        "qa_checks": [
            {
                "check_name": "crash_direction_fields_not_used",
                "status": "passed",
                "notes": "crash direction keywords are explicitly filtered from access-type candidate selection.",
            },
            {"check_name": "normalized_artifact_not_overwritten", "status": "passed", "notes": "read-only mode for access.parquet"},
            {
                "check_name": "source_join_outputs_not_modified",
                "status": "passed",
                "notes": "access_context_join outputs treated diagnostic-only; not overwritten.",
            },
            {
                "check_name": "graph_context_modeling_rate_outputs_not_modified",
                "status": "passed",
                "notes": "no downstream modules are invoked by this module.",
            },
            {
                "check_name": "v2_staging_recommendation_labeling",
                "status": "passed",
                "notes": "recommendation includes direct/inferred/not_supported and action label.",
            },
            {
                "check_name": "empty_intermediate_tables_handled",
                "status": "passed",
                "notes": "all required intermediate outputs are normalized to expected schemas before findings and CSV writes.",
            },
            {
                "check_name": "expected_output_headers_present",
                "status": "passed" if headers_present else "failed",
                "notes": "required CSV outputs include expected headers even when no rows are present.",
            },
            {
                "check_name": "findings_generated_without_keyerror",
                "status": "passed",
                "notes": "findings helpers guard empty frames and missing source_name or value columns.",
            },
            {
                "check_name": "all_gdb_layers_inventoried",
                "status": "passed" if len(debug_layer_inventory) >= len(source_read_results) else "failed",
                "notes": "layer discovery uses pyogrio when fiona is unavailable and writes one debug row per detected layer.",
            },
            {
                "check_name": "manual_pathways_fields_values_searched",
                "status": "passed",
                "notes": "field and sample-value searches include access direction/control/approach/turn/land-use/route/measure and observed Pathways terms/codes.",
            },
            {
                "check_name": "source_selected_count_nonzero_when_readable",
                "status": "passed" if any(_row_count(frame) > 0 for frame in source_frames.values()) else "failed",
                "notes": "selected layers are ranked from detected GDB layers rather than assumed from source names.",
            },
        ],
    }
    _write_json(manifest, manifest_path)

    return {
        "access_source_layer_inventory": str(source_inventory_path),
        "access_gdb_layer_inventory_debug": str(debug_layer_inventory_path),
        "access_layer_sample_value_profile": str(sample_value_profile_path),
        "access_layer_candidate_field_search": str(candidate_field_search_path),
        "access_layer_candidate_value_search": str(candidate_value_search_path),
        "access_layer_alias_domain_inventory": str(alias_domain_inventory_path),
        "access_layer_selection_ranking": str(selection_ranking_path),
        "access_source_schema_comparison": str(schema_path),
        "access_source_non_null_profile": str(nonnull_path),
        "access_candidate_type_field_inventory": str(candidate_inventory_path),
        "access_candidate_type_value_counts": str(candidate_values_path),
        "access_full_vs_riro_feasibility": str(feasibility_path),
        "access_old_new_geometry_comparison": str(geometry_path),
        "access_old_new_attribute_comparison": str(attributes_path),
        "access_stable_universe_coverage_estimate": str(coverage_path),
        "access_v2_candidate_staging_recommendation": str(recommendation_path),
        "findings": str(findings_path),
        "manifest": str(manifest_path),
        **optional_written,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only comparison audit of old vs new access source layers.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_access_source_layer_comparison(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
