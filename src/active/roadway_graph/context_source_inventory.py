from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .crs_utils import WORKING_CRS_AUTHORITY, apply_authoritative_crs, coordinate_profile, crs_to_string


REPO_ROOT = Path(".")
OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/context_source_inventory")
NORMALIZED_ROOT = Path("artifacts/normalized")
STAGE1B_ROOT = Path("work/output/stage1b_study_slice")

ACCESS_FILE = NORMALIZED_ROOT / "access.parquet"
SPEED_FILE = NORMALIZED_ROOT / "speed.parquet"
SIGNAL_SPEED_CONTEXT_FILE = STAGE1B_ROOT / "Study_Signals_SpeedContext.parquet"

READINESS_FILE = OUTPUT_ROOT / "review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
CATCHMENT_POLYGONS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_polygons.geojson"
CATCHMENT_CRS_METADATA_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_crs_metadata.json"
ASSIGNMENTS_FILE = OUTPUT_ROOT / "review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignments.csv"

FEET_TO_METERS = 0.3048
PROXIMITY_THRESHOLDS_FT = [100, 250]
SPEED_SEARCH_ROOTS = [Path("artifacts"), Path("work/output")]
SPEED_NAME_TOKENS = ("speed", "posted", "postedspeed", "speedlimit", "SpeedContext")
GEOMETRY_NAMES = {"geometry", "geom", "shape", "wkb_geometry"}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_table(path: Path) -> pd.DataFrame | gpd.GeoDataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            return gpd.read_parquet(path)
        except Exception:
            return pd.read_parquet(path)
    if suffix in {".geojson", ".json", ".gpkg", ".shp"}:
        return gpd.read_file(path)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _as_geodataframe(frame: pd.DataFrame | gpd.GeoDataFrame) -> gpd.GeoDataFrame | None:
    if isinstance(frame, gpd.GeoDataFrame):
        return frame
    for column in frame.columns:
        if column.lower() in GEOMETRY_NAMES:
            try:
                return gpd.GeoDataFrame(frame.copy(), geometry=column)
            except Exception:
                return None
    return None


def _schema_frame(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
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


def _sample_values(series: pd.Series, limit: int = 5) -> str:
    values = []
    for value in series.dropna().astype(str):
        if value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return " | ".join(values)


def _geometry_columns(frame: pd.DataFrame | gpd.GeoDataFrame) -> list[str]:
    columns = []
    if isinstance(frame, gpd.GeoDataFrame):
        columns.append(str(frame.geometry.name))
    for column in frame.columns:
        if column.lower() in GEOMETRY_NAMES and column not in columns:
            columns.append(column)
    return columns


def _geometry_qa(frame: pd.DataFrame | gpd.GeoDataFrame, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    geo = _as_geodataframe(frame)
    if geo is None:
        qa = pd.DataFrame(
            [
                {
                    "dataset": dataset,
                    "geometry_column": "",
                    "row_count": len(frame),
                    "geometry_null_count": "",
                    "geometry_empty_count": "",
                    "geometry_valid_count": "",
                    "geometry_invalid_count": "",
                    "crs": "",
                    "geometry_type": "no_geometry_detected",
                    "geometry_type_count": len(frame),
                }
            ]
        )
        return qa, pd.DataFrame([{"dataset": dataset, "crs": "", "minx": "", "miny": "", "maxx": "", "maxy": ""}])

    geometry = geo.geometry
    geometry_type_counts = geometry.geom_type.fillna("<null>").value_counts(dropna=False).reset_index()
    geometry_type_counts.columns = ["geometry_type", "geometry_type_count"]
    geometry_type_counts.insert(0, "dataset", dataset)
    geometry_type_counts.insert(1, "geometry_column", str(geo.geometry.name))
    geometry_type_counts.insert(2, "row_count", len(geo))
    geometry_type_counts.insert(3, "geometry_null_count", int(geometry.isna().sum()))
    geometry_type_counts.insert(4, "geometry_empty_count", int(geometry.is_empty.fillna(False).sum()))
    geometry_type_counts.insert(5, "geometry_valid_count", int(geometry.is_valid.fillna(False).sum()))
    geometry_type_counts.insert(6, "geometry_invalid_count", int((~geometry.is_valid.fillna(False)).sum()))
    geometry_type_counts.insert(7, "crs", crs_to_string(geo.crs))
    bounds = pd.DataFrame([coordinate_profile(geo, dataset)])
    return geometry_type_counts, bounds


def _field_role_candidates(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        lower = column.lower()
        roles = _candidate_roles_for_column(lower)
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
                "method_note": "role inferred from field name only; not used for upstream/downstream",
            }
        )
    return pd.DataFrame(rows)


def _candidate_roles_for_column(lower: str) -> list[str]:
    roles: list[str] = []
    if (
        lower in {"id", "_editid", "_featureid", "objectid", "event_source_id", "source_id", "linkid"}
        or lower.endswith("_id")
        or lower.endswith("id")
        and lower not in {"residential"}
    ):
        roles.append("likely_id")
    if any(token in lower for token in ("route", "rte", "road", "street", "name", "common")):
        roles.append("likely_route_or_road_name")
    if (
        lower in {"_m", "m", "measure"}
        or "measure" in lower
        or "msr" in lower
        or lower in {"route_from_measure", "route_to_measure", "from_measure", "to_measure"}
    ):
        roles.append("likely_measure")
    if any(
        token in lower
        for token in (
            "access",
            "commercial",
            "retail",
            "residential",
            "industrial",
            "school",
            "institutional",
            "approach",
            "turn_lane",
            "control",
        )
    ):
        roles.append("likely_access_type_or_category")
    if (
        any(token in lower for token in ("direction", "left", "right"))
        or lower in {"dir", "side", "nb", "sb", "eb", "wb"}
        or "side_of" in lower
    ):
        roles.append("likely_side_or_direction_context")
    if any(token in lower for token in ("speed", "limit", "mph", "truck", "car")):
        roles.append("likely_speed_context")
    if lower in GEOMETRY_NAMES or lower.endswith("geometrytype"):
        roles.append("likely_geometry")
    return roles


def _duplicate_null_qa(frame: pd.DataFrame | gpd.GeoDataFrame, dataset: str, role_candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    id_columns = (
        role_candidates.loc[role_candidates["candidate_roles"].str.contains("likely_id", na=False), "column_name"].tolist()
        if not role_candidates.empty
        else []
    )
    for column in id_columns + _geometry_columns(frame):
        if column not in frame.columns:
            continue
        series = frame[column]
        rows.append(
            {
                "dataset": dataset,
                "field_name": column,
                "field_kind": "geometry" if column in _geometry_columns(frame) else "likely_id",
                "row_count": len(frame),
                "null_count": int(series.isna().sum()),
                "duplicate_non_null_count": int(series.dropna().duplicated().sum()),
                "unique_non_null_count": int(series.dropna().nunique()),
            }
        )
    return pd.DataFrame(rows)


def _load_access(path: Path) -> gpd.GeoDataFrame | None:
    if not path.exists():
        return None
    frame = _read_table(path)
    geo = _as_geodataframe(frame)
    return geo


def _stable_bounds_and_crs() -> tuple[pd.DataFrame, gpd.GeoDataFrame | None, str]:
    if not CATCHMENT_POLYGONS_FILE.exists():
        return pd.DataFrame(), None, "catchment_polygons_missing"
    catchments = gpd.read_file(CATCHMENT_POLYGONS_FILE)
    catchments, crs_status, _ = apply_authoritative_crs(catchments, metadata_path=CATCHMENT_CRS_METADATA_FILE)
    usable = catchments
    if "catchment_status" in usable.columns:
        usable = usable.loc[usable["catchment_status"].eq("usable")].copy()
    bounds = pd.DataFrame([coordinate_profile(usable, "stable_usable_directional_catchments")])
    bounds["crs_status"] = crs_status
    return bounds, usable, crs_status


def _access_crs_sanity(access: gpd.GeoDataFrame | None, stable_bounds: pd.DataFrame, stable_status: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if access is None:
        return pd.DataFrame(
            [
                {
                    "dataset": "access",
                    "check_name": "access_source_exists",
                    "status": "missing",
                    "details": str(ACCESS_FILE),
                }
            ]
        )
    rows.append({**coordinate_profile(access, "access_source"), "check_name": "access_coordinate_profile", "status": "reported"})
    if not stable_bounds.empty:
        stable = stable_bounds.iloc[0].to_dict()
        access_bounds = access.total_bounds if not access.empty else [None, None, None, None]
        overlaps = False
        if access.crs is not None and len(access) > 0:
            try:
                access_projected = access.to_crs(WORKING_CRS_AUTHORITY)
                ab = access_projected.total_bounds
                overlaps = _bounds_overlap(ab, [stable["minx"], stable["miny"], stable["maxx"], stable["maxy"]])
            except Exception:
                overlaps = _bounds_overlap(access_bounds, [stable["minx"], stable["miny"], stable["maxx"], stable["maxy"]])
        else:
            overlaps = _bounds_overlap(access_bounds, [stable["minx"], stable["miny"], stable["maxx"], stable["maxy"]])
        rows.append(
            {
                "dataset": "access_source_vs_stable_universe",
                "check_name": "coordinate_range_overlap_with_stable_catchments",
                "status": "compatible_range" if overlaps else "range_mismatch_or_unverified",
                "access_crs": crs_to_string(access.crs),
                "stable_crs": stable.get("crs", ""),
                "stable_crs_status": stable_status,
                "details": "Compared access coordinate bounds to usable directional catchment bounds.",
            }
        )
    return pd.DataFrame(rows)


def _bounds_overlap(left: Any, right: Any) -> bool:
    try:
        lminx, lminy, lmaxx, lmaxy = [float(v) for v in left]
        rminx, rminy, rmaxx, rmaxy = [float(v) for v in right]
    except Exception:
        return False
    return lminx <= rmaxx and lmaxx >= rminx and lminy <= rmaxy and lmaxy >= rminy


def _window_from_bin_midpoint(value: Any) -> str:
    distance = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(distance):
        return "unknown"
    if distance <= 1000:
        return "high_priority_0_1000ft"
    if distance <= 2500:
        return "sensitivity_1000_2500ft"
    return "review_only_over_2500ft"


def _access_proximity_diagnostic(access: gpd.GeoDataFrame | None, catchments: gpd.GeoDataFrame | None) -> pd.DataFrame:
    if access is None:
        return pd.DataFrame([{"metric": "proximity_diagnostic_status", "value": "not_run_access_missing", "count": ""}])
    if catchments is None or catchments.empty:
        return pd.DataFrame([{"metric": "proximity_diagnostic_status", "value": "not_run_stable_catchment_geometry_missing", "count": ""}])
    if access.crs is None:
        if _bounds_overlap(access.total_bounds, catchments.total_bounds):
            access_working = access.set_crs(catchments.crs)
            access_crs_status = "missing_crs_set_to_stable_for_diagnostic_because_bounds_overlap"
        else:
            return pd.DataFrame([{"metric": "proximity_diagnostic_status", "value": "not_run_access_crs_missing_and_bounds_do_not_overlap", "count": ""}])
    else:
        access_working = access.to_crs(catchments.crs)
        access_crs_status = "reprojected_to_stable_crs_for_diagnostic"
    access_valid = access_working.loc[access_working.geometry.notna() & ~access_working.geometry.is_empty].copy()
    catchment_keep = [
        c
        for c in [
            "catchment_id",
            "reference_directional_bin_id",
            "reference_signal_id",
            "signal_relative_direction",
            "roadway_representation_type",
            "bin_start_ft_from_reference_signal",
            "bin_end_ft_from_reference_signal",
        ]
        if c in catchments.columns
    ]
    catchment_small = catchments[catchment_keep + ["geometry"]].copy()
    if "bin_start_ft_from_reference_signal" in catchment_small.columns and "bin_end_ft_from_reference_signal" in catchment_small.columns:
        start = pd.to_numeric(catchment_small["bin_start_ft_from_reference_signal"], errors="coerce")
        end = pd.to_numeric(catchment_small["bin_end_ft_from_reference_signal"], errors="coerce")
        catchment_small["bin_midpoint_ft_from_reference_signal"] = (start + end) / 2.0
    else:
        catchment_small["bin_midpoint_ft_from_reference_signal"] = pd.NA
    rows: list[dict[str, Any]] = [
        {"metric": "proximity_diagnostic_status", "value": "completed_diagnostic_only_not_join", "count": ""},
        {"metric": "access_crs_handling", "value": access_crs_status, "count": ""},
        {"metric": "access_features_considered", "value": "", "count": len(access_valid)},
        {"metric": "usable_directional_catchments_considered", "value": "", "count": len(catchment_small)},
    ]
    if access_valid.empty or catchment_small.empty:
        return pd.DataFrame(rows)

    nearest = gpd.sjoin_nearest(
        access_valid.reset_index(names="access_source_index"),
        catchment_small,
        how="left",
        max_distance=max(PROXIMITY_THRESHOLDS_FT) * FEET_TO_METERS,
        distance_col="nearest_catchment_distance_m",
    )
    nearest["nearest_catchment_distance_ft"] = pd.to_numeric(nearest["nearest_catchment_distance_m"], errors="coerce") / FEET_TO_METERS
    matched = nearest.loc[nearest["nearest_catchment_distance_ft"].notna()].copy()
    for threshold in PROXIMITY_THRESHOLDS_FT:
        count = int(matched.loc[matched["nearest_catchment_distance_ft"].le(threshold), "access_source_index"].nunique())
        rows.append({"metric": f"access_features_within_{threshold}ft_of_usable_directional_catchment", "value": "", "count": count})
    matched["analysis_window"] = matched["bin_midpoint_ft_from_reference_signal"].map(_window_from_bin_midpoint)
    for window in ["high_priority_0_1000ft", "sensitivity_1000_2500ft", "review_only_over_2500ft", "unknown"]:
        count = int(matched.loc[matched["analysis_window"].eq(window), "access_source_index"].nunique())
        rows.append({"metric": f"access_features_nearest_to_{window}_stable_universe_within_250ft", "value": "", "count": count})
    if "signal_relative_direction" in matched.columns:
        for direction, group in matched.groupby("signal_relative_direction", dropna=False):
            rows.append(
                {
                    "metric": "access_features_nearest_to_stable_universe_by_signal_relative_direction_within_250ft",
                    "value": direction,
                    "count": int(group["access_source_index"].nunique()),
                }
            )
    return pd.DataFrame(rows)


def _candidate_speed_files() -> pd.DataFrame:
    rows = []
    expected = [SPEED_FILE, SIGNAL_SPEED_CONTEXT_FILE]
    for path in expected:
        rows.append(
            {
                "path": str(path),
                "file_name": path.name,
                "exists": path.exists(),
                "source_kind": "expected",
                "size_bytes": path.stat().st_size if path.exists() else "",
                "extension": path.suffix.lower(),
            }
        )
    seen = {path.resolve() for path in expected if path.exists()}
    for root in SPEED_SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if _is_relative_to(path, OUTPUT_ROOT / OUTPUT_DIR):
                continue
            name = path.name
            if not any(token.lower() in name.lower() for token in SPEED_NAME_TOKENS):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            rows.append(
                {
                    "path": str(path),
                    "file_name": path.name,
                    "exists": True,
                    "source_kind": "candidate_name_match",
                    "size_bytes": path.stat().st_size,
                    "extension": path.suffix.lower(),
                }
            )
    return pd.DataFrame(rows).sort_values(["source_kind", "path"], ascending=[False, True])


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _inspect_speed_candidates(speed_inventory: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = speed_inventory.loc[
        speed_inventory["exists"].eq(True)
        & speed_inventory["extension"].isin([".parquet", ".csv", ".geojson", ".json", ".gpkg", ".shp"])
    ].copy()
    schema_frames = []
    geometry_frames = []
    crs_frames = []
    role_frames = []
    for row in candidates.itertuples(index=False):
        path = Path(row.path)
        try:
            frame = _read_table(path)
        except Exception as exc:
            schema_frames.append(pd.DataFrame([{"dataset": str(path), "column_name": "<read_error>", "dtype": type(exc).__name__, "non_null_count": "", "null_count": "", "null_share": "", "sample_values": str(exc)}]))
            continue
        dataset = str(path)
        schema_frames.append(_schema_frame(frame, dataset))
        geometry, bounds = _geometry_qa(frame, dataset)
        geometry_frames.append(geometry)
        crs_frames.append(bounds)
        role_frames.append(_field_role_candidates(frame, dataset))
    return (
        pd.concat(schema_frames, ignore_index=True) if schema_frames else pd.DataFrame(),
        pd.concat(geometry_frames, ignore_index=True) if geometry_frames else pd.DataFrame(),
        pd.concat(crs_frames, ignore_index=True) if crs_frames else pd.DataFrame(),
        pd.concat(role_frames, ignore_index=True) if role_frames else pd.DataFrame(),
    )


def build_context_source_inventory(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    out_dir = output_root / OUTPUT_DIR
    started = datetime.now(timezone.utc)
    access = _load_access(ACCESS_FILE)
    access_exists = ACCESS_FILE.exists()
    access_frame: pd.DataFrame | gpd.GeoDataFrame = access if access is not None else pd.DataFrame()
    stable_bounds, stable_catchments, stable_crs_status = _stable_bounds_and_crs()

    access_schema = _schema_frame(access_frame, "access") if access_exists else pd.DataFrame()
    access_geometry_qa, access_bounds = _geometry_qa(access_frame, "access") if access_exists else (pd.DataFrame(), pd.DataFrame())
    access_crs_sanity = _access_crs_sanity(access, stable_bounds, stable_crs_status)
    access_roles = _field_role_candidates(access_frame, "access") if access_exists else pd.DataFrame()
    access_dup_null = _duplicate_null_qa(access_frame, "access", access_roles) if access_exists else pd.DataFrame()
    access_proximity = _access_proximity_diagnostic(access, stable_catchments)

    speed_inventory = pd.DataFrame(
        [
            {"source_name": "artifacts_normalized_speed_parquet", "path": str(SPEED_FILE), "exists": SPEED_FILE.exists(), "expected": True},
            {
                "source_name": "stage1b_study_signals_speed_context",
                "path": str(SIGNAL_SPEED_CONTEXT_FILE),
                "exists": SIGNAL_SPEED_CONTEXT_FILE.exists(),
                "expected": True,
            },
        ]
    )
    speed_candidates = _candidate_speed_files()
    speed_schema, speed_geometry, speed_crs, speed_roles = _inspect_speed_candidates(speed_candidates)

    stable_inputs = [
        READINESS_FILE,
        USABLE_BINS_FILE,
        CATCHMENT_INDEX_FILE,
        CATCHMENT_POLYGONS_FILE,
        ASSIGNMENTS_FILE,
    ]
    stable_rows = []
    for path in stable_inputs:
        stable_rows.append(
            {
                "source_name": path.name,
                "path": str(path),
                "exists": path.exists(),
                "row_count": _csv_row_count(path) if path.exists() and path.suffix.lower() == ".csv" else "",
                "role": "stable_universe_compatibility_check_only",
            }
        )

    summary = pd.DataFrame(
        [
            {
                "metric": "bounded_question",
                "value": "Stage A source inventory and schema audit for access and speed context",
                "count": "",
            },
            {"metric": "access_parquet_exists", "value": access_exists, "count": ""},
            {"metric": "access_row_count", "value": "", "count": len(access_frame) if access_exists else 0},
            {"metric": "speed_parquet_exists", "value": SPEED_FILE.exists(), "count": ""},
            {"metric": "study_signals_speed_context_exists", "value": SIGNAL_SPEED_CONTEXT_FILE.exists(), "count": ""},
            {
                "metric": "candidate_speed_files_found_elsewhere",
                "value": "",
                "count": int(speed_candidates.loc[speed_candidates["source_kind"].eq("candidate_name_match")].shape[0]) if not speed_candidates.empty else 0,
            },
            {"metric": "stable_universe_inputs_checked", "value": "", "count": len(stable_inputs)},
            {"metric": "access_or_speed_joins_implemented", "value": False, "count": ""},
            {"metric": "scaffold_catchment_assignment_readiness_logic_changed", "value": False, "count": ""},
            {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        ]
    )

    outputs = {
        "summary_csv": out_dir / "context_source_inventory_summary.csv",
        "access_schema_csv": out_dir / "access_source_schema.csv",
        "access_geometry_qa_csv": out_dir / "access_source_geometry_qa.csv",
        "access_crs_sanity_csv": out_dir / "access_source_crs_sanity.csv",
        "access_field_roles_csv": out_dir / "access_source_field_role_candidates.csv",
        "access_duplicate_null_qa_csv": out_dir / "access_source_duplicate_null_qa.csv",
        "access_proximity_csv": out_dir / "access_source_stable_universe_proximity_diagnostic.csv",
        "speed_inventory_csv": out_dir / "speed_source_inventory.csv",
        "speed_missing_or_candidate_csv": out_dir / "speed_source_missing_or_candidate_files.csv",
        "findings_md": out_dir / "context_source_inventory_findings.md",
        "manifest_json": out_dir / "context_source_inventory_manifest.json",
    }
    optional_outputs = {}
    if not speed_schema.empty or not speed_geometry.empty or not speed_crs.empty or not speed_roles.empty:
        optional_outputs = {
            "speed_schema_csv": out_dir / "speed_source_schema.csv",
            "speed_geometry_qa_csv": out_dir / "speed_source_geometry_qa.csv",
            "speed_crs_sanity_csv": out_dir / "speed_source_crs_sanity.csv",
            "speed_field_roles_csv": out_dir / "speed_source_field_role_candidates.csv",
        }

    _write_csv(summary, outputs["summary_csv"])
    _write_csv(access_schema, outputs["access_schema_csv"])
    _write_csv(access_geometry_qa, outputs["access_geometry_qa_csv"])
    _write_csv(access_crs_sanity, outputs["access_crs_sanity_csv"])
    _write_csv(access_roles, outputs["access_field_roles_csv"])
    _write_csv(access_dup_null, outputs["access_duplicate_null_qa_csv"])
    _write_csv(access_proximity, outputs["access_proximity_csv"])
    _write_csv(speed_inventory, outputs["speed_inventory_csv"])
    _write_csv(speed_candidates, outputs["speed_missing_or_candidate_csv"])
    if optional_outputs:
        _write_csv(speed_schema, optional_outputs["speed_schema_csv"])
        _write_csv(speed_geometry, optional_outputs["speed_geometry_qa_csv"])
        _write_csv(speed_crs, optional_outputs["speed_crs_sanity_csv"])
        _write_csv(speed_roles, optional_outputs["speed_field_roles_csv"])

    all_outputs = {**outputs, **optional_outputs}
    findings = _findings(
        access=access,
        access_geometry_qa=access_geometry_qa,
        access_crs_sanity=access_crs_sanity,
        access_roles=access_roles,
        access_proximity=access_proximity,
        speed_inventory=speed_inventory,
        speed_candidates=speed_candidates,
        stable_rows=pd.DataFrame(stable_rows),
        outputs=all_outputs,
    )
    _write_text(findings, outputs["findings_md"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Step 6 Stage A read-only context source inventory and schema audit",
        "access_or_speed_joins_implemented": False,
        "scaffold_catchment_assignment_readiness_logic_changed": False,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "access": str(ACCESS_FILE),
            "speed": str(SPEED_FILE),
            "signal_speed_context": str(SIGNAL_SPEED_CONTEXT_FILE),
            "stable_universe": [str(path) for path in stable_inputs],
        },
        "stable_input_status": stable_rows,
        "outputs": {key: str(path) for key, path in all_outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in all_outputs.items()}


def _csv_row_count(path: Path) -> int:
    try:
        return max(sum(1 for _ in path.open("r", encoding="utf-8")) - 1, 0)
    except UnicodeDecodeError:
        return max(sum(1 for _ in path.open("r")) - 1, 0)


def _first_role_columns(roles: pd.DataFrame, role: str) -> str:
    if roles.empty:
        return ""
    matched = roles.loc[roles["candidate_roles"].str.contains(role, na=False), "column_name"].tolist()
    return ", ".join(matched[:12])


def _findings(
    *,
    access: gpd.GeoDataFrame | None,
    access_geometry_qa: pd.DataFrame,
    access_crs_sanity: pd.DataFrame,
    access_roles: pd.DataFrame,
    access_proximity: pd.DataFrame,
    speed_inventory: pd.DataFrame,
    speed_candidates: pd.DataFrame,
    stable_rows: pd.DataFrame,
    outputs: dict[str, Path],
) -> str:
    access_exists = access is not None
    access_row_count = len(access) if access is not None else 0
    access_crs = crs_to_string(access.crs) if access is not None else ""
    geometry_types = "none"
    if not access_geometry_qa.empty and "geometry_type" in access_geometry_qa.columns:
        geometry_types = "; ".join(
            f"{row.geometry_type}={row.geometry_type_count}" for row in access_geometry_qa.itertuples(index=False)
        )
    crs_status = "not_available"
    if not access_crs_sanity.empty and "check_name" in access_crs_sanity.columns:
        matched = access_crs_sanity.loc[access_crs_sanity["check_name"].eq("coordinate_range_overlap_with_stable_catchments")]
        if not matched.empty:
            crs_status = str(matched.iloc[0].get("status", ""))
    speed_parquet_exists = bool(speed_inventory.loc[speed_inventory["source_name"].eq("artifacts_normalized_speed_parquet"), "exists"].iloc[0])
    speed_context_exists = bool(speed_inventory.loc[speed_inventory["source_name"].eq("stage1b_study_signals_speed_context"), "exists"].iloc[0])
    candidate_count = int(speed_candidates.loc[speed_candidates["source_kind"].eq("candidate_name_match")].shape[0]) if not speed_candidates.empty else 0
    proximity_lines = []
    if not access_proximity.empty:
        for row in access_proximity.itertuples(index=False):
            proximity_lines.append(f"- {row.metric}: {row.value} {row.count}".rstrip())
    lines = [
        "# Context Source Inventory Findings",
        "",
        "## Bounded Question",
        "",
        "Step 6 Stage A inventory and schema audit for access and speed context sources. This module does not implement access or speed joins.",
        "",
        "## Files Inspected",
        "",
        "- `artifacts/normalized/access.parquet`",
        "- `artifacts/normalized/speed.parquet`",
        "- `work/output/stage1b_study_slice/Study_Signals_SpeedContext.parquet`",
        "- speed-name candidates under `artifacts/` and `work/output/`",
        *[f"- `{row.path}` ({'present' if row.exists else 'missing'})" for row in stable_rows.itertuples(index=False)],
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
        "## Access Source",
        "",
        f"- `access.parquet` exists: {access_exists}",
        f"- access row count: {access_row_count}",
        f"- access CRS: {access_crs or 'missing'}",
        f"- access geometry types: {geometry_types}",
        f"- coordinate compatibility with stable universe: {crs_status}",
        f"- likely ID fields: {_first_role_columns(access_roles, 'likely_id') or 'none_detected'}",
        f"- likely route/road/name fields: {_first_role_columns(access_roles, 'likely_route_or_road_name') or 'none_detected'}",
        f"- likely access type/category fields: {_first_role_columns(access_roles, 'likely_access_type_or_category') or 'none_detected'}",
        f"- side/direction context fields found but not used for upstream/downstream: {_first_role_columns(access_roles, 'likely_side_or_direction_context') or 'none_detected'}",
        "",
        "## Access Proximity Diagnostic",
        "",
        *(proximity_lines or ["- not run"]),
        "",
        "These counts are diagnostic only. They are not access assignments and do not alter the stable universe.",
        "",
        "## Speed Source",
        "",
        f"- `speed.parquet` exists: {speed_parquet_exists}",
        f"- `Study_Signals_SpeedContext.parquet` exists: {speed_context_exists}",
        f"- candidate speed-name files found elsewhere: {candidate_count}",
        "",
        "No final speed join rule is designed here because Stage A only records source availability and schema basics.",
        "",
        "## Methodological Boundary Checks",
        "",
        "- access joins implemented: False",
        "- speed joins implemented: False",
        "- scaffold construction modified: False",
        "- directional catchments modified: False",
        "- crash assignment or readiness modified: False",
        "- crash direction fields read or used: False",
        "",
        "## Recommended Next Step",
        "",
        "- If access geometry and CRS are usable, implement the bounded access context join as the next available context layer.",
        "- If speed remains missing, recover or restage a posted-speed source before implementing speed context.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only source inventory and schema audit for roadway_graph context enrichment.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_context_source_inventory(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
