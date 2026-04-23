from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from .config import InputLayer, load_runtime_config


DEPENDENCIES = ("pandas", "geopandas", "shapely", "pyproj", "pyogrio", "pyarrow")
STAGING_SUMMARY_NAME = "stage1_input_manifest.json"
NORMALIZED_SUMMARY_NAME = "stage1_normalized_manifest.json"
PARITY_SUMMARY_NAME = "stage1_parity_manifest.json"

KEY_FIELD_CANDIDATES = {
    "roads": ["RTE_NM", "RTE_ID"],
    "signals": ["REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "INTNUM"],
    "crashes": ["DOCUMENT_NBR"],
    "aadt": ["LINKID", "MASTER_RTE_NM", "RTE_NM"],
}

ACTIVE_COMMANDS = (
    "bootstrap",
    "stage-inputs",
    "normalize-stage",
    "build-study-slice",
    "enrich-study-signals-nearest-road",
    "check-parity",
    "inspect-aadt-traffic-volume-bridge",
    "inspect-aadt-traffic-volume-geojson-bridge",
)


def _active_inputs(config) -> dict[str, InputLayer]:
    return {key: layer for key, layer in config.inputs.items() if layer.active_stage}


def _optional_diagnostic_inputs(config) -> dict[str, InputLayer]:
    return {key: layer for key, layer in config.inputs.items() if not layer.active_stage}


def _find_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _dependency_status() -> tuple[dict[str, bool], list[str]]:
    status = {name: _find_module(name) for name in DEPENDENCIES}
    missing = [name for name, installed in status.items() if not installed]
    return status, missing


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


def _gdb_layer_status(layer: InputLayer) -> dict[str, object]:
    status: dict[str, object] = {
        "source_gdb_exists": layer.source_gdb.exists(),
        "layer_name": layer.layer_name,
        "source_layer_name": layer.source_layer_name,
        "layer_list_checked_with": None,
        "layer_present": None,
        "first_read_checked_with": None,
        "first_read_ok": None,
    }
    if not layer.source_gdb.exists():
        return status

    if _find_module("pyogrio"):
        try:
            from pyogrio import list_layers

            status["layer_list_checked_with"] = "pyogrio"
            available = {name for name, _geom in list_layers(str(layer.source_gdb))}
            status["available_layers"] = sorted(available)
            status["layer_present"] = layer.source_layer_name in available
        except Exception as exc:  # pragma: no cover - defensive bootstrap reporting
            status["layer_list_checked_with"] = "pyogrio"
            status["layer_check_error"] = str(exc)
            return status

    elif _find_module("fiona"):
        try:
            import fiona

            status["layer_list_checked_with"] = "fiona"
            available = set(fiona.listlayers(str(layer.source_gdb)))
            status["available_layers"] = sorted(available)
            status["layer_present"] = layer.source_layer_name in available
        except Exception as exc:  # pragma: no cover - defensive bootstrap reporting
            status["layer_list_checked_with"] = "fiona"
            status["layer_check_error"] = str(exc)
            return status

    if status["layer_present"] is not True:
        return status

    if _find_module("geopandas"):
        try:
            import geopandas as gpd

            status["first_read_checked_with"] = "geopandas"
            sample = gpd.read_file(layer.source_gdb, layer=layer.source_layer_name, rows=1)
            status["first_read_ok"] = True
            status["sample_row_count"] = int(len(sample))
            status["sample_columns"] = list(sample.columns)
            if not sample.empty:
                status["sample_geometry_type"] = str(sample.geometry.iloc[0].geom_type)
                status["sample_crs"] = None if sample.crs is None else str(sample.crs)
            return status
        except Exception as exc:  # pragma: no cover - defensive bootstrap reporting
            status["first_read_checked_with"] = "geopandas"
            status["first_read_ok"] = False
            status["first_read_error"] = str(exc)
            return status

    return status


def _bootstrap_payload() -> tuple[dict[str, object], list[str], dict[str, dict[str, object]]]:
    config = load_runtime_config()
    dependency_status, missing = _dependency_status()

    input_status = {}
    for key, layer in _active_inputs(config).items():
        input_status[key] = {
            "layer_name": layer.layer_name,
            "source_layer_name": layer.source_layer_name,
            "source_gdb": str(layer.source_gdb),
            "derived": layer.derived,
            "active_stage": layer.active_stage,
            "notes": layer.notes,
            **_gdb_layer_status(layer),
        }

    optional_diagnostic_status = {}
    for key, layer in _optional_diagnostic_inputs(config).items():
        optional_diagnostic_status[key] = {
            "layer_name": layer.layer_name,
            "source_layer_name": layer.source_layer_name,
            "source_gdb": str(layer.source_gdb),
            "derived": layer.derived,
            "active_stage": layer.active_stage,
            "notes": layer.notes,
            "source_gdb_exists": layer.source_gdb.exists(),
        }

    payload = {
        "interpreter": sys.executable,
        "python_version": sys.version.splitlines()[0],
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "working_crs": config.working_crs,
        "stage1_entrypoint": config.stage1_entrypoint,
        "raw_data_dir_exists": config.raw_data_dir.exists(),
        "staging_dir": str(config.staging_dir),
        "normalized_dir": str(config.normalized_dir),
        "output_dir": str(config.output_dir),
        "parity_dir": str(config.parity_dir),
        "active_input_keys": sorted(input_status.keys()),
        "optional_diagnostic_input_keys": sorted(optional_diagnostic_status.keys()),
        "supplemental_traffic_volume": {
            "geojson_path": str(config.supplemental_traffic_volume.geojson_path),
            "geojson_exists": config.supplemental_traffic_volume.geojson_path.exists(),
            "shapefile_dir": str(config.supplemental_traffic_volume.shapefile_dir),
            "shapefile_dir_exists": config.supplemental_traffic_volume.shapefile_dir.exists(),
        },
        "dependency_status": dependency_status,
        "missing_dependencies": missing,
        "inputs": input_status,
        "optional_diagnostics": optional_diagnostic_status,
    }
    return payload, missing, input_status


def run_bootstrap_check(print_payload: bool = True) -> int:
    payload, missing, input_status = _bootstrap_payload()

    if print_payload:
        print(json.dumps(payload, indent=2))

    if missing:
        print(
            "\nActive slice bootstrap detected missing open-source runtime dependencies.",
            file=sys.stderr,
        )
        return 1

    unresolved_layers = [
        key for key, status in input_status.items()
        if status["source_gdb_exists"] and status.get("layer_present") is False
    ]
    if unresolved_layers:
        print(
            "\nStage 1 bootstrap found configured inputs whose layer names were not present in the configured source geodatabases: "
            + ", ".join(unresolved_layers),
            file=sys.stderr,
        )
        return 2

    unreadable_layers = [
        key for key, status in input_status.items()
        if status["source_gdb_exists"] and status.get("layer_present") is True and status.get("first_read_ok") is False
    ]
    if unreadable_layers:
        print(
            "\nStage 1 bootstrap found configured inputs that could be discovered but not read: "
            + ", ".join(unreadable_layers),
            file=sys.stderr,
        )
        return 3

    return 0


def _read_canonical_layer(layer: InputLayer) -> tuple[object, dict[str, object]]:
    import geopandas as gpd
    import pandas as pd

    source_specs = layer.merge_sources or ((layer.source_gdb, layer.source_layer_name),)
    frames = []
    source_counts = []
    target_crs = None

    for source_gdb, source_layer_name in source_specs:
        gdf = gpd.read_file(source_gdb, layer=source_layer_name)
        row_count = int(len(gdf))
        source_counts.append(
            {
                "source_gdb": str(source_gdb),
                "source_layer_name": source_layer_name,
                "row_count": row_count,
                "crs": None if gdf.crs is None else str(gdf.crs),
            }
        )
        if row_count == 0:
            continue
        if target_crs is None and gdf.crs is not None:
            target_crs = gdf.crs
        if target_crs is not None and gdf.crs is not None and gdf.crs != target_crs:
            gdf = gdf.to_crs(target_crs)
        gdf["Stage1_SourceGDB"] = source_gdb.name
        gdf["Stage1_SourceLayer"] = source_layer_name
        frames.append(gdf)

    if frames:
        merged_df = pd.concat(frames, ignore_index=True, sort=False)
        merged = gpd.GeoDataFrame(merged_df, geometry="geometry", crs=target_crs)
    else:
        merged = gpd.GeoDataFrame({"Stage1_SourceGDB": [], "Stage1_SourceLayer": []}, geometry=[], crs=target_crs)

    metadata = {
        "source_mode": "merged" if layer.merge_sources else "single",
        "source_counts": source_counts,
        "non_empty_source_count": int(sum(1 for item in source_counts if item["row_count"] > 0)),
    }
    return merged, metadata


def _stage_single_layer(layer: InputLayer, target_path: Path, layer_key: str) -> dict[str, object]:
    gdf, source_metadata = _read_canonical_layer(layer)
    gdf.to_parquet(target_path, index=False)

    summary: dict[str, object] = {
        "logical_layer_name": layer.layer_name,
        "source_layer_name": layer.source_layer_name,
        "source_gdb": str(layer.source_gdb),
        "staged_dataset": str(target_path),
        "staged_layer_name": None,
        "row_count": int(len(gdf)),
        "null_geometry_count": int(gdf.geometry.isna().sum()),
        "columns": list(gdf.columns),
        "non_geometry_columns": [c for c in gdf.columns if c != gdf.geometry.name],
        "geometry_column": gdf.geometry.name,
        "crs": None if gdf.crs is None else str(gdf.crs),
        "derived": layer.derived,
        "notes": layer.notes,
        **source_metadata,
    }
    if not gdf.empty:
        summary["geometry_types"] = sorted({str(v) for v in gdf.geometry.geom_type.dropna().unique().tolist()})
        bounds = gdf.total_bounds.tolist()
        summary["total_bounds"] = [float(v) for v in bounds]
    else:
        summary["geometry_types"] = []
        summary["total_bounds"] = None
    return summary


def run_stage_inputs() -> int:
    check_code = run_bootstrap_check(print_payload=False)
    if check_code != 0:
        return check_code

    config = load_runtime_config()
    config.staging_dir.mkdir(parents=True, exist_ok=True)
    summary_path = config.staging_dir / STAGING_SUMMARY_NAME

    for old_name in ("stage1_inputs.gpkg", "stage1_inputs.gpkg-wal", "stage1_inputs.gpkg-shm", "stage1_inputs.gpkg-journal"):
        old_path = config.staging_dir / old_name
        if old_path.exists():
            try:
                old_path.unlink()
            except PermissionError:
                pass

    staged = {}
    for key, layer in _active_inputs(config).items():
        target_path = config.staging_dir / f"{key}.parquet"
        if target_path.exists():
            target_path.unlink()
        staged[key] = _stage_single_layer(layer, target_path, key)

    manifest = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "staging_dir": str(config.staging_dir),
        "staging_format": "GeoParquet (one file per layer)",
        "layers": staged,
    }
    summary_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


def _normalize_single_layer(layer_key: str, source_path: Path, working_crs: str) -> tuple[object, dict[str, object]]:
    import geopandas as gpd
    import pandas as pd

    gdf = gpd.read_parquet(source_path)
    before_rows = int(len(gdf))
    before_null_geometry = int(gdf.geometry.isna().sum())
    before_crs = None if gdf.crs is None else str(gdf.crs)

    year_filter_applied = False
    year_filter_field = None
    rows_after_year_filter = before_rows

    if layer_key == "crashes":
        year_filter_applied = True
        year_filter_field = "CRASH_YEAR"
        years = pd.to_numeric(gdf["CRASH_YEAR"], errors="coerce")
        gdf = gdf.loc[years.between(2022, 2024, inclusive="both")].copy()
        rows_after_year_filter = int(len(gdf))

    null_geometry_before_drop = int(gdf.geometry.isna().sum())
    if null_geometry_before_drop:
        gdf = gdf.loc[gdf.geometry.notna()].copy()

    if gdf.crs is None:
        raise ValueError(f"Layer '{layer_key}' has no CRS; cannot normalize to {working_crs}.")

    if str(gdf.crs) != working_crs:
        gdf = gdf.to_crs(working_crs)

    after_rows = int(len(gdf))
    after_null_geometry = int(gdf.geometry.isna().sum())
    after_crs = None if gdf.crs is None else str(gdf.crs)

    summary = {
        "source_dataset": str(source_path),
        "before_rows": before_rows,
        "before_crs": before_crs,
        "before_null_geometry_count": before_null_geometry,
        "year_filter_applied": year_filter_applied,
        "year_filter_field": year_filter_field,
        "year_filter_start": 2022 if year_filter_applied else None,
        "year_filter_end": 2024 if year_filter_applied else None,
        "rows_after_year_filter": rows_after_year_filter,
        "null_geometry_count_before_drop": null_geometry_before_drop,
        "after_rows": after_rows,
        "after_crs": after_crs,
        "after_null_geometry_count": after_null_geometry,
        "dropped_by_year_filter": before_rows - rows_after_year_filter if year_filter_applied else 0,
        "dropped_by_null_geometry": rows_after_year_filter - after_rows,
    }
    return gdf, summary


def _text_is_present(series) -> int:
    values = series.dropna().astype(str).str.strip()
    return int((values != "").sum())


def _dataset_metrics(layer_key: str, gdf) -> dict[str, object]:
    metrics = {
        "row_count": int(len(gdf)),
        "null_geometry_count": int(gdf.geometry.isna().sum()),
        "crs": _canonical_crs_label(gdf.crs),
        "columns": list(gdf.columns),
        "geometry_column": gdf.geometry.name,
        "geometry_types": sorted({str(v) for v in gdf.geometry.geom_type.dropna().unique().tolist()}),
        "total_bounds": None,
        "key_fields": {},
    }
    if metrics["row_count"] and metrics["null_geometry_count"] < metrics["row_count"]:
        bounds = gdf.loc[gdf.geometry.notna()].total_bounds.tolist()
        metrics["total_bounds"] = [float(v) for v in bounds]
    for field in KEY_FIELD_CANDIDATES.get(layer_key, []):
        if field in gdf.columns:
            metrics["key_fields"][field] = {
                "present": True,
                "non_null_count": int(gdf[field].notna().sum()),
                "non_blank_count": _text_is_present(gdf[field]),
            }
        else:
            metrics["key_fields"][field] = {
                "present": False,
                "non_null_count": 0,
                "non_blank_count": 0,
            }
    return metrics


def _compare_metrics(left: dict[str, object], right: dict[str, object], *, allow_row_drop: bool = False) -> dict[str, object]:
    left_fields = set(left["columns"])
    right_fields = set(right["columns"])
    key_field_deltas = {}
    all_key_fields = sorted(set(left.get("key_fields", {}).keys()) | set(right.get("key_fields", {}).keys()))
    for field in all_key_fields:
        l = left.get("key_fields", {}).get(field, {"present": False, "non_null_count": 0, "non_blank_count": 0})
        r = right.get("key_fields", {}).get(field, {"present": False, "non_null_count": 0, "non_blank_count": 0})
        key_field_deltas[field] = {
            "left_present": l["present"],
            "right_present": r["present"],
            "non_null_delta": int(r["non_null_count"]) - int(l["non_null_count"]),
            "non_blank_delta": int(r["non_blank_count"]) - int(l["non_blank_count"]),
        }

    return {
        "row_count_left": left["row_count"],
        "row_count_right": right["row_count"],
        "row_count_delta": int(right["row_count"]) - int(left["row_count"]),
        "row_count_match": left["row_count"] == right["row_count"],
        "row_count_nonincreasing_ok": int(right["row_count"]) <= int(left["row_count"]) if allow_row_drop else left["row_count"] == right["row_count"],
        "null_geometry_left": left["null_geometry_count"],
        "null_geometry_right": right["null_geometry_count"],
        "null_geometry_delta": int(right["null_geometry_count"]) - int(left["null_geometry_count"]),
        "crs_left": left["crs"],
        "crs_right": right["crs"],
        "crs_match": left["crs"] == right["crs"],
        "geometry_types_left": left["geometry_types"],
        "geometry_types_right": right["geometry_types"],
        "geometry_types_match": left["geometry_types"] == right["geometry_types"],
        "fields_missing_from_right": sorted(left_fields - right_fields),
        "fields_added_in_right": sorted(right_fields - left_fields),
        "key_field_deltas": key_field_deltas,
        "bounds_left": left["total_bounds"],
        "bounds_right": right["total_bounds"],
    }


def _read_legacy_available_outputs(config) -> dict[str, object]:
    legacy_candidates = [
        config.repo_root / "CrashIntersectionAnalysis.gdb",
        config.repo_root / "IntersectionCrashAnalysis.gdb",
        config.repo_root / "thirdstep_work.gdb",
    ]
    available = [str(path) for path in legacy_candidates if path.exists()]
    return {
        "searched_locations": [str(path) for path in legacy_candidates],
        "available_locations": available,
        "comparisons": {},
        "status": "unavailable" if not available else "available_but_not_implemented",
        "notes": (
            "No repo-local legacy ArcPy staged or working geodatabase outputs were found."
            if not available
            else "Legacy geodatabases exist, but layer-level comparison targets are intentionally out of the reduced active slice."
        ),
    }


def run_check_parity() -> int:
    check_code = run_bootstrap_check(print_payload=False)
    if check_code != 0:
        return check_code

    import geopandas as gpd

    config = load_runtime_config()
    config.parity_dir.mkdir(parents=True, exist_ok=True)
    parity_path = config.parity_dir / PARITY_SUMMARY_NAME

    stage_manifest_path = config.staging_dir / STAGING_SUMMARY_NAME
    normalized_manifest_path = config.normalized_dir / NORMALIZED_SUMMARY_NAME
    if not stage_manifest_path.exists():
        raise FileNotFoundError(f"Missing staging manifest: {stage_manifest_path}")
    if not normalized_manifest_path.exists():
        raise FileNotFoundError(f"Missing normalized manifest: {normalized_manifest_path}")

    stage_manifest = json.loads(stage_manifest_path.read_text(encoding="utf-8"))
    normalized_manifest = json.loads(normalized_manifest_path.read_text(encoding="utf-8"))

    raw_vs_staged = {}
    staged_vs_normalized = {}

    for key, layer in _active_inputs(config).items():
        raw_expected_gdf, _ = _read_canonical_layer(layer)
        staged_path = config.staging_dir / f"{key}.parquet"
        normalized_path = config.normalized_dir / f"{key}.parquet"
        staged_gdf = gpd.read_parquet(staged_path)
        normalized_gdf = gpd.read_parquet(normalized_path)

        raw_metrics = _dataset_metrics(key, raw_expected_gdf)
        staged_metrics = _dataset_metrics(key, staged_gdf)
        normalized_metrics = _dataset_metrics(key, normalized_gdf)

        stage_manifest_layer = stage_manifest["layers"][key]
        normalized_manifest_layer = normalized_manifest["layers"][key]
        stage_manifest_crs = _canonical_crs_label(stage_manifest_layer["crs"])
        normalized_manifest_after_crs = _canonical_crs_label(normalized_manifest_layer["after_crs"])

        raw_vs_staged[key] = {
            "left_label": "raw_source",
            "right_label": "staged_raw_canonical",
            "comparison": _compare_metrics(raw_metrics, staged_metrics, allow_row_drop=False),
            "manifest_consistency": {
                "staged_row_count_matches_manifest": staged_metrics["row_count"] == stage_manifest_layer["row_count"],
                "staged_null_geometry_matches_manifest": staged_metrics["null_geometry_count"] == stage_manifest_layer["null_geometry_count"],
                "staged_crs_matches_manifest": staged_metrics["crs"] == stage_manifest_crs,
                "staged_columns_match_manifest": staged_metrics["columns"] == stage_manifest_layer["columns"],
            },
        }

        staged_vs_normalized[key] = {
            "left_label": "staged_raw_canonical",
            "right_label": "normalized_analysis_ready",
            "comparison": _compare_metrics(staged_metrics, normalized_metrics, allow_row_drop=True),
            "expected_changes": {
                "year_filter_expected": key == "crashes",
                "working_crs_expected": config.working_crs,
                "null_geometry_drop_expected": staged_metrics["null_geometry_count"] > 0,
            },
            "manifest_consistency": {
                "normalized_before_rows_match_staged": normalized_manifest_layer["before_rows"] == staged_metrics["row_count"],
                "normalized_after_rows_match_dataset": normalized_manifest_layer["after_rows"] == normalized_metrics["row_count"],
                "normalized_after_nulls_match_dataset": normalized_manifest_layer["after_null_geometry_count"] == normalized_metrics["null_geometry_count"],
                "normalized_after_crs_matches_dataset": normalized_manifest_after_crs == normalized_metrics["crs"],
            },
        }

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "parity_dir": str(config.parity_dir),
        "working_crs": config.working_crs,
        "comparison_boundaries": {
            "raw_vs_staged_raw_canonical": raw_vs_staged,
            "staged_raw_canonical_vs_normalized": staged_vs_normalized,
            "normalized_vs_legacy_arcpy": _read_legacy_available_outputs(config),
        },
    }
    parity_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_normalize_stage() -> int:
    check_code = run_bootstrap_check(print_payload=False)
    if check_code != 0:
        return check_code

    config = load_runtime_config()
    config.normalized_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.normalized_dir / NORMALIZED_SUMMARY_NAME

    normalized = {}
    for key in _active_inputs(config).keys():
        source_path = config.staging_dir / f"{key}.parquet"
        if not source_path.exists():
            raise FileNotFoundError(f"Missing staged source file for normalization: {source_path}")
        target_path = config.normalized_dir / f"{key}.parquet"
        if target_path.exists():
            target_path.unlink()
        gdf, summary = _normalize_single_layer(key, source_path, config.working_crs)
        gdf.to_parquet(target_path, index=False)
        summary["normalized_dataset"] = str(target_path)
        normalized[key] = summary

    manifest = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "staging_dir": str(config.staging_dir),
        "normalized_dir": str(config.normalized_dir),
        "working_crs": config.working_crs,
        "layers": normalized,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reduced active src.active entrypoint for the bounded divided-road study-slice workflow. "
            "Legacy Oracle, bridge-propagation, and Stage 1C branch commands are preserved under legacy/."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="bootstrap",
        choices=ACTIVE_COMMANDS,
        help=(
            "bootstrap checks runtime and configured input readiness; "
            "stage-inputs writes staged raw/canonical inputs; "
            "normalize-stage writes normalized inputs; "
            "build-study-slice writes Study_Roads_Divided and Study_Signals; "
            "enrich-study-signals-nearest-road writes Study_Signals_NearestRoad; "
            "check-parity writes stage1_parity_manifest.json under work/parity; "
            "inspect-aadt-traffic-volume-bridge and inspect-aadt-traffic-volume-geojson-bridge remain transitional diagnostics."
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        return run_bootstrap_check(print_payload=True)
    if args.command == "stage-inputs":
        return run_stage_inputs()
    if args.command == "normalize-stage":
        return run_normalize_stage()
    if args.command == "build-study-slice":
        from .study_slice import run_stage1b_study_slice

        return run_stage1b_study_slice()
    if args.command == "enrich-study-signals-nearest-road":
        from .study_slice import run_stage1b_signal_nearest_road

        return run_stage1b_signal_nearest_road()
    if args.command == "check-parity":
        return run_check_parity()
    if args.command == "inspect-aadt-traffic-volume-bridge":
        from ..transitional.bridge_key_audit import run_stage1_aadt_traffic_volume_bridge_audit

        return run_stage1_aadt_traffic_volume_bridge_audit()
    if args.command == "inspect-aadt-traffic-volume-geojson-bridge":
        from ..transitional.bridge_key_geojson_audit import run_stage1_aadt_traffic_volume_geojson_bridge_audit

        return run_stage1_aadt_traffic_volume_geojson_bridge_audit()
    raise SystemExit(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
