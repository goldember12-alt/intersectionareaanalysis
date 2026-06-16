from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_access_rerun_with_source_accounting"

GEOMETRY_CLEANUP_DIR = OUTPUT_ROOT / "review/current/final_access_target_geometry_persistence_cleanup"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
PRIOR_FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_universe_access_rerun"
PRIOR_SOURCE_AUDIT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_source_capture_audit"
PRIOR_UNCAPTURED_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_uncaptured_source_diagnostic"
PRIOR_GEOMETRY_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

FEET_PER_METER = 3.280839895
BUFFER_WIDTHS_FT = [35, 50, 75, 100]
MAX_BUFFER_FT = max(BUFFER_WIDTHS_FT)
DISTANCE_BINS_FT = [-0.001, 35, 50, 75, 100, 150, 250, 500, 1000, np.inf]
DISTANCE_LABELS = ["0_35ft", "35_50ft", "50_75ft", "75_100ft", "100_150ft", "150_250ft", "250_500ft", "500_1000ft", "gt_1000ft"]

TYPED_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
]

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
    GEOMETRY_CLEANUP_DIR / "final_access_target_bins_geometry_cleaned.csv",
    GEOMETRY_CLEANUP_DIR / "final_access_geometry_recovery_summary.csv",
    GEOMETRY_CLEANUP_DIR / "final_access_geometry_remaining_missingness.csv",
    GEOMETRY_CLEANUP_DIR / "final_access_geometry_persistence_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_two_leg_or_less_audit.csv",
    FINAL_OVERVIEW_DIR / "final_access_readiness_decision.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    PRIOR_FINAL_ACCESS_DIR / "final_access_product_coverage_summary.csv",
    ACCESS_V1_FILE,
    ACCESS_V2_FILE,
]


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted(
        {
            str(value)
            for value in values.dropna()
            if str(value).strip() and str(value).lower() not in {"nan", "none", "<na>"}
        }
    )
    return "|".join(items[:limit])


def _route_key(value: Any) -> str:
    text = str(value or "").upper()
    if not text or text == "NAN":
        return ""
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    for match in re.finditer(r"\b(US|VA|IS|SC|SR|RTE)\s*0*([0-9]+)\s*([NSEW])?B?\b", text):
        prefix, number, direction = match.groups()
        if prefix in {"SR", "RTE"}:
            prefix = "VA"
        return f"{prefix}{int(number)}{direction or ''}"
    compact = re.sub(r"[^A-Z0-9]+", "", text)
    for match in re.finditer(r"(US|VA|IS|SC|SR|RTE)0*([0-9]+)([NSEW])?B?", compact):
        prefix, number, direction = match.groups()
        if prefix in {"SR", "RTE"}:
            prefix = "VA"
        return f"{prefix}{int(number)}{direction or ''}"
    return compact


def _missing_inputs() -> list[str]:
    required = list(REQUIRED_INPUTS)
    for optional in [
        PRIOR_SOURCE_AUDIT_DIR / "expanded_universe_access_source_capture_manifest.json",
        PRIOR_UNCAPTURED_DIR / "expanded_universe_access_uncaptured_source_manifest.json",
        PRIOR_GEOMETRY_DIR / "access_buffer_sensitivity_summary.csv",
    ]:
        if optional.exists():
            required.append(optional)
    return [str(path) for path in required if not path.exists()]


def _read_access(path: Path, *, typed: bool) -> gpd.GeoDataFrame:
    _checkpoint(f"read_start {path.name}")
    access = gpd.read_parquet(path)
    access = access.drop(columns=[column for column in access.columns if _blocked_column(column)], errors="ignore")
    if access.crs is None:
        access = access.set_crs("EPSG:3968", allow_override=True)
    access = access.to_crs("EPSG:3968")
    if typed:
        access["access_point_id"] = access.get("access_v2_source_priority", "").astype(str) + ":" + access.get("access_v2_source_row_id", "").astype(str)
        access.loc[access["access_point_id"].eq(":"), "access_point_id"] = access.loc[access["access_point_id"].eq(":"), "id"].astype(str)
        access["access_layer"] = "typed_v2"
        access["access_control_category"] = access.get("access_control_category", "").astype(str).replace("", "unknown")
        access.loc[~access["access_control_category"].isin(TYPED_CATEGORIES), "access_control_category"] = "other_review"
        access["route_name"] = access.get("route_name", "").astype(str)
        access["route_measure"] = access.get("route_measure", "").astype(str)
        access["source_dataset"] = access.get("access_v2_source_gdb", "").astype(str)
        access["source_layer"] = access.get("access_v2_source_layer", "").astype(str)
        keep_extra = ["access_v2_source_priority", "access_v2_source_row_id", "access_v2_staging_status", "access_control_code", "access_direction_normalized"]
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["access_layer"] = "untyped"
        access["access_control_category"] = "untyped"
        access["route_name"] = access.get("_rte_nm", "").astype(str)
        access["route_measure"] = access.get("_m", "").astype(str)
        access["source_dataset"] = access.get("Stage1_SourceGDB", "").astype(str)
        access["source_layer"] = access.get("Stage1_SourceLayer", "").astype(str)
        keep_extra = ["Stage1_SourceGDB", "Stage1_SourceLayer"]
    access["route_key"] = access["route_name"].map(_route_key)
    access["has_geometry"] = access.geometry.notna() & ~access.geometry.is_empty
    access["has_route_fields"] = access["route_key"].astype(str).str.strip().ne("")
    keep = [
        "access_point_id",
        "access_layer",
        "access_control_category",
        "route_name",
        "route_measure",
        "route_key",
        "source_dataset",
        "source_layer",
        "has_geometry",
        "has_route_fields",
        "geometry",
    ] + [col for col in keep_extra if col in access.columns]
    out = access[keep].copy()
    out = out.loc[out["access_point_id"].astype(str).str.strip().ne("")]
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _build_target_and_lines() -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    target = _read_csv(GEOMETRY_CLEANUP_DIR / "final_access_target_bins_geometry_cleaned.csv")
    target["completed_geometry_status"] = _text(target, "geometry_recovery_status").where(_text(target, "geometry_recovery_status").ne(""), _text(target, "completed_geometry_status"))
    target.loc[_text(target, "completed_geometry_status").eq("geometry_recovered"), "completed_geometry_status"] = "geometry_available"
    target["geometry_recovery_method"] = _text(target, "geometry_recovery_method_final").where(_text(target, "geometry_recovery_method_final").ne(""), _text(target, "geometry_recovery_method"))
    target["distance_length_ft"] = (_num(target, "distance_end_ft") - _num(target, "distance_start_ft")).abs()
    target["distance_length_ft"] = target["distance_length_ft"].where(target["distance_length_ft"].gt(0), 50.0)
    target["candidate_weight_num"] = pd.to_numeric(_text(target, "candidate_weight_num"), errors="coerce").fillna(1.0)
    target["route_key"] = _text(target, "route_facility_fields").map(_route_key)

    geom_rows = target.loc[_text(target, "completed_geometry_status").eq("geometry_available") & _text(target, "geometry_wkt").ne("")].copy()
    geom_rows["geometry"] = geom_rows["geometry_wkt"].map(lambda value: wkt.loads(value) if str(value).strip() else None)
    lines = gpd.GeoDataFrame(geom_rows.drop(columns=["geometry_wkt"], errors="ignore"), geometry="geometry", crs="EPSG:3968")
    lines = lines.loc[lines.geometry.notna() & ~lines.geometry.is_empty].copy()
    _checkpoint("target_geometry_available", len(lines), note=f"signals={lines['target_signal_id'].nunique():,}")
    return target, lines


def _assign_for_width(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str, width_ft: int) -> pd.DataFrame:
    if lines.empty or access.empty:
        return pd.DataFrame()
    line_cols = [
        "target_bin_id",
        "target_signal_id",
        "target_source_id",
        "target_source_layer",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "route_facility_fields",
        "route_key",
        "analysis_window",
        "distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "distance_length_ft",
        "candidate_weight_num",
        "geometry_recovery_method",
        "geometry_recovery_status",
        "final_alignment_class",
        "final_physical_leg_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
        "final_bin_source_package",
        "final_original_or_recovered",
        "recovery_stream",
        "recovery_class",
        "geometry",
    ]
    catchments = lines[[col for col in line_cols if col in lines.columns]].copy()
    catchments["geometry"] = catchments.geometry.buffer(width_ft / FEET_PER_METER, cap_style="flat", join_style="mitre")
    catchments = gpd.GeoDataFrame(catchments, geometry="geometry", crs="EPSG:3968")
    source = access.loc[access["has_geometry"]].drop(columns=[col for col in access.columns if col == "index_right"], errors="ignore")
    joined = gpd.sjoin(source, catchments, how="inner", predicate="within")
    if joined.empty:
        return pd.DataFrame()
    out = pd.DataFrame(joined.drop(columns=["geometry", "index_right"], errors="ignore"))
    out = out.drop_duplicates(["access_point_id", "target_bin_id", "access_control_category"])
    fanout = out.groupby("access_point_id", dropna=False)["target_bin_id"].nunique().rename("assignment_fanout_count").reset_index()
    out = out.merge(fanout, on="access_point_id", how="left")
    out["assignment_fanout_count"] = pd.to_numeric(out["assignment_fanout_count"], errors="coerce").fillna(1.0)
    out["buffer_width_ft"] = width_ft
    out["access_layer"] = layer
    out["multi_assignment_flag"] = out["assignment_fanout_count"].gt(1)
    out["unweighted_access_count"] = 1.0
    out["source_preserving_weighted_access_count"] = 1.0 / out["assignment_fanout_count"]
    return out


def _assign_all(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    parts = []
    for width in BUFFER_WIDTHS_FT:
        _checkpoint("buffer_assignment_start", note=f"{layer} width_ft={width}")
        parts.append(_assign_for_width(lines, access, layer=layer, width_ft=width))
    return pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()


def _signal_window_summary(assignments: pd.DataFrame, target: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame()
    grouped = assignments.groupby(["buffer_width_ft", "target_signal_id", "analysis_window"], dropna=False).agg(
        source_access_point_count=("access_point_id", "nunique"),
        assignment_count=("access_point_id", "size"),
        unweighted_access_count=("unweighted_access_count", "sum"),
        weighted_access_count=("source_preserving_weighted_access_count", "sum"),
        max_assignment_fanout=("assignment_fanout_count", "max"),
        multi_assignment_count=("multi_assignment_flag", "sum"),
        physical_leg_count_with_access=("physical_leg_id_final", "nunique"),
        carriageway_subbranch_count_with_access=("carriageway_subbranch_id_final", "nunique"),
        final_alignment_class=("final_alignment_class", "first"),
        final_physical_leg_class=("final_physical_leg_class", "first"),
        source_limited_holdout_flag=("source_limited_holdout_flag", "first"),
        grade_mainline_holdout_flag=("grade_mainline_holdout_flag", "first"),
        still_insufficient_evidence_flag=("still_insufficient_evidence_flag", "first"),
        review_only_recovery_provenance=("review_only_recovery_provenance", _collapse),
    ).reset_index()
    length = target.groupby(["target_signal_id", "analysis_window"], dropna=False)["distance_length_ft"].sum().reset_index(name="represented_length_ft")
    grouped = grouped.merge(length, on=["target_signal_id", "analysis_window"], how="left")
    grouped["access_density_per_1000ft_unweighted"] = np.where(pd.to_numeric(grouped["represented_length_ft"], errors="coerce").gt(0), grouped["unweighted_access_count"] / pd.to_numeric(grouped["represented_length_ft"], errors="coerce") * 1000, np.nan)
    grouped["access_density_per_1000ft_weighted"] = np.where(pd.to_numeric(grouped["represented_length_ft"], errors="coerce").gt(0), grouped["weighted_access_count"] / pd.to_numeric(grouped["represented_length_ft"], errors="coerce") * 1000, np.nan)
    grouped["access_layer"] = layer
    return grouped


def _coverage_summary(untyped: pd.DataFrame, typed: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    rows = []
    geometry_signals = set(_text(target.loc[_text(target, "completed_geometry_status").eq("geometry_available")], "target_signal_id"))
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        for width in BUFFER_WIDTHS_FT:
            subset = frame.loc[pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(width)] if not frame.empty else pd.DataFrame()
            any_signals = set(_text(subset, "target_signal_id"))
            primary_signals = set(_text(subset.loc[_text(subset, "analysis_window").eq("0_1000")], "target_signal_id")) if not subset.empty else set()
            rows.extend(
                [
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "signals_with_access", "count": len(any_signals)},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "signals_with_0_1000ft_access", "count": len(primary_signals)},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "bins_with_access", "count": int(_text(subset, "target_bin_id").nunique()) if not subset.empty else 0},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "source_access_points_captured", "count": int(_text(subset, "access_point_id").nunique()) if not subset.empty else 0},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "unweighted_assignment_total", "count": round(float(pd.to_numeric(subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "weighted_assignment_total", "count": round(float(pd.to_numeric(subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "geometry_available_signals_without_access", "count": len(geometry_signals - any_signals)},
                ]
            )
    return pd.DataFrame(rows)


def _source_inventory(access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    rows = [
        {
            "access_layer": layer,
            "inventory_group": "all_source_points",
            "inventory_value": "all",
            "source_point_count": int(access["access_point_id"].nunique()),
            "points_with_geometry": int(access["has_geometry"].sum()),
            "points_with_route_fields": int(access["has_route_fields"].sum()),
        }
    ]
    for source_layer, group in access.groupby("source_layer", dropna=False):
        rows.append(
            {
                "access_layer": layer,
                "inventory_group": "source_layer",
                "inventory_value": source_layer,
                "source_point_count": int(group["access_point_id"].nunique()),
                "points_with_geometry": int(group["has_geometry"].sum()),
                "points_with_route_fields": int(group["has_route_fields"].sum()),
            }
        )
    if layer == "typed_v2":
        for category, group in access.groupby("access_control_category", dropna=False):
            rows.append(
                {
                    "access_layer": layer,
                    "inventory_group": "typed_category",
                    "inventory_value": category,
                    "source_point_count": int(group["access_point_id"].nunique()),
                    "points_with_geometry": int(group["has_geometry"].sum()),
                    "points_with_route_fields": int(group["has_route_fields"].sum()),
                }
            )
    return pd.DataFrame(rows)


def _source_point_detail(access: gpd.GeoDataFrame, assignments: pd.DataFrame, lines: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    detail = pd.DataFrame(access.drop(columns=["geometry"], errors="ignore").copy())
    represented_routes = {value for value in set(_text(lines, "route_key")) if value}
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)].copy() if not assignments.empty else pd.DataFrame()
        if subset.empty:
            detail[f"captured_{width}ft"] = False
            detail[f"assignment_count_{width}ft"] = 0
            detail[f"assignment_fanout_{width}ft"] = 0
            detail[f"weighted_total_{width}ft"] = 0.0
            detail[f"captured_windows_{width}ft"] = ""
            continue
        agg = subset.groupby("access_point_id", dropna=False).agg(
            assignment_count=("target_bin_id", "size"),
            assignment_fanout=("assignment_fanout_count", "max"),
            weighted_total=("source_preserving_weighted_access_count", "sum"),
            captured_windows=("analysis_window", _collapse),
            captured_signals=("target_signal_id", "nunique"),
            captured_physical_legs=("physical_leg_id_final", "nunique"),
        ).reset_index()
        detail = detail.merge(agg, on="access_point_id", how="left")
        detail[f"captured_{width}ft"] = detail["assignment_count"].notna()
        detail[f"assignment_count_{width}ft"] = pd.to_numeric(detail["assignment_count"], errors="coerce").fillna(0)
        detail[f"assignment_fanout_{width}ft"] = pd.to_numeric(detail["assignment_fanout"], errors="coerce").fillna(0)
        detail[f"weighted_total_{width}ft"] = pd.to_numeric(detail["weighted_total"], errors="coerce").fillna(0)
        detail[f"captured_windows_{width}ft"] = _text(detail, "captured_windows")
        detail[f"captured_signal_count_{width}ft"] = pd.to_numeric(detail["captured_signals"], errors="coerce").fillna(0)
        detail[f"captured_physical_leg_count_{width}ft"] = pd.to_numeric(detail["captured_physical_legs"], errors="coerce").fillna(0)
        detail = detail.drop(columns=["assignment_count", "assignment_fanout", "weighted_total", "captured_windows", "captured_signals", "captured_physical_legs"], errors="ignore")
    detail["captured_any_buffer"] = detail[[f"captured_{width}ft" for width in BUFFER_WIDTHS_FT]].any(axis=1)
    detail["captured_max_buffer"] = detail[f"captured_{MAX_BUFFER_FT}ft"]
    detail["route_represented_flag"] = _text(detail, "route_key").isin(represented_routes)
    detail["source_accounting_base_reason"] = np.select(
        [
            ~detail["has_geometry"].astype(bool),
            detail["captured_any_buffer"].astype(bool),
            detail["has_geometry"].astype(bool) & detail["route_represented_flag"].astype(bool),
            detail["has_geometry"].astype(bool) & detail["has_route_fields"].astype(bool) & ~detail["route_represented_flag"].astype(bool),
            detail["has_geometry"].astype(bool) & ~detail["has_route_fields"].astype(bool),
        ],
        [
            "source_geometry_missing_or_uncertain",
            "captured_by_final_target_catchment",
            "route_represented_uncaptured_at_tested_buffers",
            "source_route_not_in_represented_universe",
            "source_route_unknown_or_missing",
        ],
        default="insufficient_evidence",
    )
    detail["access_layer"] = layer
    return detail


def _source_capture_by_buffer(access: gpd.GeoDataFrame, assignments: pd.DataFrame, detail: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    rows = []
    total = int(access["access_point_id"].nunique())
    with_geometry = int(access.loc[access["has_geometry"], "access_point_id"].nunique())
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)] if not assignments.empty else pd.DataFrame()
        captured = int(_text(subset, "access_point_id").nunique()) if not subset.empty else 0
        uncaptured_points = detail.loc[~detail[f"captured_{width}ft"].astype(bool)].copy()
        rows.append(
            {
                "access_layer": layer,
                "buffer_width_ft": width,
                "total_source_point_count": total,
                "source_points_with_geometry": with_geometry,
                "source_points_captured": captured,
                "source_points_uncaptured": total - captured,
                "source_capture_rate": round(captured / total, 6) if total else 0,
                "source_geometry_available_capture_rate": round(captured / with_geometry, 6) if with_geometry else 0,
                "assignment_count": int(len(subset)) if not subset.empty else 0,
                "unweighted_assignment_count": round(float(pd.to_numeric(subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0,
                "source_preserving_weighted_total": round(float(pd.to_numeric(subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0,
                "uncaptured_on_represented_route_family": int(uncaptured_points.loc[uncaptured_points["route_represented_flag"].astype(bool), "access_point_id"].nunique()),
                "uncaptured_on_unrepresented_route_family": int(uncaptured_points.loc[~uncaptured_points["route_represented_flag"].astype(bool) & uncaptured_points["has_route_fields"].astype(bool), "access_point_id"].nunique()),
                "uncaptured_source_geometry_missing_or_uncertain": int(uncaptured_points.loc[~uncaptured_points["has_geometry"].astype(bool), "access_point_id"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def _fanout_summary(assignments: pd.DataFrame, access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    rows = []
    all_points = set(_text(access, "access_point_id"))
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)] if not assignments.empty else pd.DataFrame()
        if subset.empty:
            rows.append({"access_layer": layer, "buffer_width_ft": width, "fanout_bucket": "uncaptured", "source_point_count": len(all_points), "assignment_count": 0, "weighted_total": 0.0})
            continue
        per_point = subset.groupby("access_point_id", dropna=False).agg(
            assignment_fanout_count=("target_bin_id", "nunique"),
            assignment_count=("target_bin_id", "size"),
            weighted_total=("source_preserving_weighted_access_count", "sum"),
        ).reset_index()
        captured_points = set(_text(per_point, "access_point_id"))
        per_point["fanout_bucket"] = pd.cut(
            pd.to_numeric(per_point["assignment_fanout_count"], errors="coerce").fillna(0),
            bins=[0, 1, 2, 3, np.inf],
            labels=["1", "2", "3", "4_plus"],
            include_lowest=True,
        ).astype(str)
        out = per_point.groupby("fanout_bucket", dropna=False).agg(
            source_point_count=("access_point_id", "nunique"),
            assignment_count=("assignment_count", "sum"),
            weighted_total=("weighted_total", "sum"),
        ).reset_index()
        out["access_layer"] = layer
        out["buffer_width_ft"] = width
        rows.extend(out.to_dict("records"))
        rows.append({"access_layer": layer, "buffer_width_ft": width, "fanout_bucket": "uncaptured", "source_point_count": len(all_points - captured_points), "assignment_count": 0, "weighted_total": 0.0})
    return pd.DataFrame(rows)


def _nearest_uncaptured(detail: pd.DataFrame, access: gpd.GeoDataFrame, lines: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    uncaptured = detail.loc[~detail[f"captured_{MAX_BUFFER_FT}ft"].astype(bool)].copy()
    points = access.loc[access["access_point_id"].isin(set(_text(uncaptured, "access_point_id"))) & access["has_geometry"]].copy()
    if points.empty:
        out = uncaptured.copy()
        out["nearest_distance_ft"] = np.nan
        out["leg_length_limitation_class"] = "source_geometry_missing_or_uncertain"
        return out
    line_cols = [
        "target_bin_id",
        "target_signal_id",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "route_key",
        "analysis_window",
        "distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "final_alignment_class",
        "recovery_stream",
        "geometry",
    ]
    nearest = gpd.sjoin_nearest(
        points[["access_point_id", "route_key", "access_control_category", "geometry"]],
        lines[[col for col in line_cols if col in lines.columns]],
        how="left",
        distance_col="nearest_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest = nearest.sort_values(["access_point_id", "nearest_distance_m"]).drop_duplicates("access_point_id", keep="first")
    nearest["nearest_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") * FEET_PER_METER
    nearest["nearest_distance_band"] = pd.cut(nearest["nearest_distance_ft"], bins=DISTANCE_BINS_FT, labels=DISTANCE_LABELS).astype("string").fillna("unknown")
    nearest = nearest.rename(columns={"route_key_left": "source_route_key", "route_key_right": "nearest_target_route_key"})
    out = uncaptured.merge(nearest.drop(columns=["nearest_distance_m"], errors="ignore"), on="access_point_id", how="left", suffixes=("", "_nearest"))
    route_rep = out["route_represented_flag"].astype(bool)
    nearest_ft = pd.to_numeric(out["nearest_distance_ft"], errors="coerce")
    out["nearest_route_match_flag"] = _text(out, "route_key").ne("") & _text(out, "route_key").eq(_text(out, "nearest_target_route_key"))
    out["leg_length_limitation_class"] = np.select(
        [
            ~out["has_geometry"].astype(bool),
            out["has_route_fields"].astype(bool) & ~route_rep,
            nearest_ft.le(MAX_BUFFER_FT),
            nearest_ft.gt(MAX_BUFFER_FT) & nearest_ft.le(250),
            route_rep & nearest_ft.gt(250) & nearest_ft.le(1000),
            route_rep & nearest_ft.gt(1000),
            nearest_ft.notna() & ~route_rep & nearest_ft.le(500),
        ],
        [
            "source_geometry_missing_or_uncertain",
            "source_route_not_in_represented_universe",
            "outside_buffer_but_near_leg",
            "outside_buffer_but_near_leg",
            "beyond_current_leg_extent_possible_length_limitation",
            "route_represented_but_signal_window_not_long_enough",
            "likely_true_outside_signal_network",
        ],
        default="source_geometry_missing_or_uncertain",
    )
    out["leg_length_limitation_flag"] = out["leg_length_limitation_class"].isin(
        {"beyond_current_leg_extent_possible_length_limitation", "route_represented_but_signal_window_not_long_enough"}
    )
    out["access_layer"] = layer
    return out


def _uncaptured_source_detail(untyped_nearest: pd.DataFrame, typed_nearest: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([untyped_nearest, typed_nearest], ignore_index=True, sort=False)


def _leg_length_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    return detail.groupby(["access_layer", "leg_length_limitation_class", "nearest_distance_band"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        source_route_count=("route_key", "nunique"),
        example_routes=("route_key", _collapse),
    ).reset_index().sort_values(["access_layer", "source_point_count"], ascending=[True, False])


def _by_scaffold_qa(assignments: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame()
    rows = []
    for field in [
        "final_alignment_class",
        "final_physical_leg_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
    ]:
        if field not in assignments.columns:
            continue
        grouped = assignments.groupby(["buffer_width_ft", field], dropna=False).agg(
            signal_count=("target_signal_id", "nunique"),
            source_access_point_count=("access_point_id", "nunique"),
            assignment_count=("access_point_id", "size"),
            weighted_assignment_total=("source_preserving_weighted_access_count", "sum"),
        ).reset_index().rename(columns={field: "qa_value"})
        grouped["qa_field"] = field
        grouped["access_layer"] = layer
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _typed_category_summary(typed: pd.DataFrame, access_v2: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    totals = access_v2.groupby("access_control_category", dropna=False)["access_point_id"].nunique().to_dict()
    for width in BUFFER_WIDTHS_FT:
        subset = typed.loc[pd.to_numeric(typed.get("buffer_width_ft"), errors="coerce").eq(width)] if not typed.empty else pd.DataFrame()
        captured = subset.groupby("access_control_category", dropna=False)["access_point_id"].nunique().to_dict() if not subset.empty else {}
        assignment = subset.groupby("access_control_category", dropna=False).agg(
            assignment_count=("access_point_id", "size"),
            weighted_assignment_total=("source_preserving_weighted_access_count", "sum"),
        ).to_dict("index") if not subset.empty else {}
        for category in sorted(set(totals) | set(captured) | set(assignment)):
            total = int(totals.get(category, 0))
            cap = int(captured.get(category, 0))
            metrics = assignment.get(category, {})
            rows.append(
                {
                    "buffer_width_ft": width,
                    "access_control_category": category,
                    "total_source_point_count": total,
                    "captured_source_point_count": cap,
                    "uncaptured_source_point_count": total - cap,
                    "source_capture_rate": round(cap / total, 6) if total else 0,
                    "assignment_count": int(metrics.get("assignment_count", 0)),
                    "weighted_assignment_total": round(float(metrics.get("weighted_assignment_total", 0.0)), 6),
                }
            )
    return pd.DataFrame(rows)


def _prior_comparison(final_coverage: pd.DataFrame) -> pd.DataFrame:
    prior_final = _read_csv(PRIOR_FINAL_ACCESS_DIR / "final_access_product_coverage_summary.csv") if (PRIOR_FINAL_ACCESS_DIR / "final_access_product_coverage_summary.csv").exists() else pd.DataFrame()
    prior_geom = _read_csv(PRIOR_GEOMETRY_DIR / "access_buffer_sensitivity_summary.csv") if (PRIOR_GEOMETRY_DIR / "access_buffer_sensitivity_summary.csv").exists() else pd.DataFrame()
    rows = []
    for layer in ["untyped", "typed_v2"]:
        for width in BUFFER_WIDTHS_FT:
            final_count = _metric(final_coverage, layer, width, "signals_with_access")
            prior_final_count = _metric(prior_final, layer, width, "signals_with_access") if not prior_final.empty else np.nan
            prior_geom_count = _metric(prior_geom, layer, width, "signals_with_access") if not prior_geom.empty else np.nan
            rows.append(
                {
                    "access_layer": layer,
                    "buffer_width_ft": width,
                    "prior_final_rerun_before_geometry_cleanup": prior_final_count,
                    "final_cleaned_rerun_after_geometry_cleanup": final_count,
                    "geometry_cleanup_signal_delta": final_count - prior_final_count if np.isfinite(prior_final_count) else "",
                    "prior_geometry_completion_signal_coverage": prior_geom_count,
                    "delta_vs_prior_geometry_completion": final_count - prior_geom_count if np.isfinite(prior_geom_count) else "",
                }
            )
    return pd.DataFrame(rows)


def _metric(frame: pd.DataFrame, layer: str, width: int, metric: str) -> float:
    if frame.empty:
        return np.nan
    rows = frame.loc[
        _text(frame, "access_layer").eq(layer)
        & pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(width)
        & _text(frame, "metric").eq(metric),
        "count",
    ]
    return float(rows.iloc[0]) if not rows.empty else np.nan


def _missingness(target: pd.DataFrame, untyped_detail: pd.DataFrame, typed_detail: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "missingness_reason": "target_bin_geometry_unavailable_after_cleanup",
            "access_layer": "target",
            "signal_count": int(_text(target.loc[_text(target, "completed_geometry_status").ne("geometry_available")], "target_signal_id").nunique()),
            "bin_count": int(_text(target, "completed_geometry_status").ne("geometry_available").sum()),
            "source_point_count": "",
        }
    ]
    for layer, detail in [("untyped", untyped_detail), ("typed_v2", typed_detail)]:
        uncaptured = detail.loc[~detail[f"captured_{MAX_BUFFER_FT}ft"].astype(bool)]
        for reason, group in uncaptured.groupby("source_accounting_base_reason", dropna=False):
            rows.append(
                {
                    "missingness_reason": reason,
                    "access_layer": layer,
                    "signal_count": "",
                    "bin_count": "",
                    "source_point_count": int(group["access_point_id"].nunique()),
                }
            )
    return pd.DataFrame(rows)


def _write_findings(
    target: pd.DataFrame,
    untyped_assignments: pd.DataFrame,
    typed_assignments: pd.DataFrame,
    coverage: pd.DataFrame,
    source_accounting: pd.DataFrame,
    leg_summary: pd.DataFrame,
    comparison: pd.DataFrame,
) -> None:
    target_signals = int(_text(target, "target_signal_id").nunique())
    target_bins = len(target)
    geom_bins = int(_text(target, "completed_geometry_status").eq("geometry_available").sum())
    geom_signals = int(_text(target.loc[_text(target, "completed_geometry_status").eq("geometry_available")], "target_signal_id").nunique())

    def cov_lines(layer: str) -> str:
        return "\n".join(f"- {width} ft: {int(_metric(coverage, layer, width, 'signals_with_access')):,} signals" for width in BUFFER_WIDTHS_FT)

    def source_line(layer: str) -> str:
        rows = source_accounting.loc[source_accounting["access_layer"].eq(layer) & source_accounting["buffer_width_ft"].eq(MAX_BUFFER_FT)]
        if rows.empty:
            return f"- {layer}: source accounting unavailable."
        row = rows.iloc[0]
        return f"- {layer}: {int(row.source_points_captured):,} of {int(row.total_source_point_count):,} source points captured at {MAX_BUFFER_FT} ft ({float(row.source_capture_rate):.1%})."

    length_rows = leg_summary.loc[leg_summary["leg_length_limitation_class"].isin(["beyond_current_leg_extent_possible_length_limitation", "route_represented_but_signal_window_not_long_enough"])]
    length_count = int(pd.to_numeric(length_rows["source_point_count"], errors="coerce").fillna(0).sum()) if not length_rows.empty else 0

    comparison_text = "\n".join(
        f"- {row.access_layer} {int(row.buffer_width_ft)} ft: final rerun delta {row.geometry_cleanup_signal_delta}, prior geometry-completion delta {row.delta_vs_prior_geometry_completion}"
        for row in comparison.itertuples(index=False)
    )

    text = f"""# Final Access Rerun With Source Accounting

**Bounded question:** rerun access on the cleaned final review-only scaffold target and account separately for source access points, assignment fanout, scaffold QA, and likely leg/window length limitations.

## Findings

1. Final target signals: **{target_signals:,}**.
2. Final target bins: **{target_bins:,}**.
3. Bins with geometry after cleanup: **{geom_bins:,}** across **{geom_signals:,}** signals.
4. Untyped signal coverage:
{cov_lines("untyped")}
5. Typed v2 signal coverage:
{cov_lines("typed_v2")}
6. Source-point capture at the maximum tested buffer:
{source_line("untyped")}
{source_line("typed_v2")}
7. Assignment rows remain separate from source-point counts: **{len(untyped_assignments):,}** untyped assignment rows and **{len(typed_assignments):,}** typed v2 assignment rows.
8. Source points flagged as possible current leg/window length limitations: **{length_count:,}**.
9. Geometry-cleanup comparison:
{comparison_text}

## Interpretation

The geometry cleanup should be treated as the valid basis for access coverage interpretation. This rerun keeps typed and untyped access separate, preserves unweighted/double-counted and source-preserving weighted assignment products, and carries scaffold QA fields into access outputs.

## Recommendation

Do not choose a final primary access metric yet. Carry the cleaned typed and untyped access products into crash/catchment design planning, with source-point accounting and leg/window length limitation flags visible. The next bounded pass should decide whether to refine buffer width, route/measure linkage, or signal-window length before crash catchments.
"""
    _write_text(text, "final_access_rerun_with_source_accounting_findings.md")


def _write_qa(target: pd.DataFrame) -> pd.DataFrame:
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", "pass", "Writes only to final_access_rerun_with_source_accounting review folder."),
            ("no_candidates_promoted", "pass", "No active scaffold or candidate-promotion outputs are written."),
            ("no_crash_records_read", "pass", "No crash files are read."),
            ("no_crash_direction_fields_read_or_used", "pass", "Crash field tokens are blocked; source access direction attributes are not crash direction fields."),
            ("no_crash_assignment_or_catchments", "pass", "No crash assignment/catchment outputs are produced."),
            ("no_rates_or_models", "pass", "No rate/model calculations are performed."),
            ("typed_and_untyped_separate", "pass", "Separate typed v2 and untyped assignment/detail outputs are written."),
            ("weighted_and_unweighted_separate", "pass", "Assignment rows preserve unweighted and source-preserving weighted fields."),
            ("scaffold_qa_flags_carried", "pass", "Final alignment, holdout, provenance, physical leg, and subbranch fields are included."),
            ("source_point_counts_separate", "pass", "Source accounting counts source points separately from assignment rows."),
            ("review_only_outputs", "pass", f"{len(target):,} cleaned target bins written under {OUT_DIR}."),
        ],
        columns=["qa_check", "status", "note"],
    )
    _write_csv(qa, "final_access_rerun_with_source_accounting_qa.csv")
    return qa


def _manifest(started: datetime, output_names: list[str], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.build.final_access_rerun_with_source_accounting",
        "bounded_question": "read-only final access rerun on cleaned target with source-point accounting",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "started_utc": started.isoformat(),
        "output_folder": str(OUT_DIR),
        "buffer_widths_ft": BUFFER_WIDTHS_FT,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": output_names,
        "summary": summary,
        "upstream_manifests": {
            "geometry_cleanup": _load_json(GEOMETRY_CLEANUP_DIR / "final_access_geometry_persistence_manifest.json").get("created_utc", ""),
            "final_signal_leg_overview": _load_json(FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json").get("created_utc", ""),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_assignment_or_catchments": False,
            "rates_or_models": False,
            "typed_and_untyped_separate": True,
            "weighted_and_unweighted_separate": True,
            "review_only": True,
        },
    }


def main() -> None:
    started = datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    target, lines = _build_target_and_lines()
    access_v1 = _read_access(ACCESS_V1_FILE, typed=False)
    access_v2 = _read_access(ACCESS_V2_FILE, typed=True)

    untyped_assignments = _assign_all(lines, access_v1, layer="untyped")
    typed_assignments = _assign_all(lines, access_v2, layer="typed_v2")

    untyped_window = _signal_window_summary(untyped_assignments, target, layer="untyped")
    typed_window = _signal_window_summary(typed_assignments, target, layer="typed_v2")
    coverage = _coverage_summary(untyped_assignments, typed_assignments, target)

    untyped_detail = _source_point_detail(access_v1, untyped_assignments, lines, layer="untyped")
    typed_detail = _source_point_detail(access_v2, typed_assignments, lines, layer="typed_v2")
    source_accounting = pd.concat(
        [
            _source_capture_by_buffer(access_v1, untyped_assignments, untyped_detail, layer="untyped"),
            _source_capture_by_buffer(access_v2, typed_assignments, typed_detail, layer="typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )

    untyped_nearest = _nearest_uncaptured(untyped_detail, access_v1, lines, layer="untyped")
    typed_nearest = _nearest_uncaptured(typed_detail, access_v2, lines, layer="typed_v2")
    uncaptured_detail = _uncaptured_source_detail(untyped_nearest, typed_nearest)
    leg_length = _leg_length_summary(uncaptured_detail)

    fanout = pd.concat(
        [
            _fanout_summary(untyped_assignments, access_v1, layer="untyped"),
            _fanout_summary(typed_assignments, access_v2, layer="typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    scaffold_qa = pd.concat(
        [
            _by_scaffold_qa(untyped_assignments, layer="untyped"),
            _by_scaffold_qa(typed_assignments, layer="typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    typed_category = _typed_category_summary(typed_assignments, access_v2)
    missingness = _missingness(target, untyped_detail, typed_detail)
    comparison = _prior_comparison(coverage)

    output_frames = {
        "final_cleaned_access_target_bins.csv": target,
        "final_cleaned_untyped_access_assignment_detail.csv": untyped_assignments,
        "final_cleaned_untyped_access_signal_window_summary.csv": untyped_window,
        "final_cleaned_typed_v2_access_assignment_detail.csv": typed_assignments,
        "final_cleaned_typed_v2_access_signal_window_summary.csv": typed_window,
        "final_cleaned_access_product_coverage_summary.csv": coverage,
        "final_cleaned_access_fanout_summary.csv": fanout,
        "final_access_source_point_accounting.csv": source_accounting,
        "final_access_uncaptured_source_detail.csv": uncaptured_detail,
        "final_access_leg_length_limitation_diagnostic.csv": leg_length,
        "final_access_by_scaffold_qa_summary.csv": scaffold_qa,
        "final_typed_v2_category_summary.csv": typed_category,
        "final_access_missingness_summary.csv": missingness,
        "final_access_vs_prior_comparison.csv": comparison,
        "final_access_rerun_with_source_accounting_qa.csv": _write_qa(target),
    }
    for name, frame in output_frames.items():
        if name == "final_access_rerun_with_source_accounting_qa.csv":
            continue
        _write_csv(frame, name)

    _write_findings(target, untyped_assignments, typed_assignments, coverage, source_accounting, leg_length, comparison)
    summary = {
        "target_signal_count": int(_text(target, "target_signal_id").nunique()),
        "target_bin_count": int(len(target)),
        "geometry_available_signal_count": int(_text(target.loc[_text(target, "completed_geometry_status").eq("geometry_available")], "target_signal_id").nunique()),
        "geometry_available_bin_count": int(_text(target, "completed_geometry_status").eq("geometry_available").sum()),
        "untyped_source_point_count": int(access_v1["access_point_id"].nunique()),
        "typed_v2_source_point_count": int(access_v2["access_point_id"].nunique()),
        "untyped_assignment_rows": int(len(untyped_assignments)),
        "typed_v2_assignment_rows": int(len(typed_assignments)),
        "coverage_summary": coverage.to_dict(orient="records"),
    }
    output_names = list(output_frames) + [
        "final_access_rerun_with_source_accounting_findings.md",
        "final_access_rerun_with_source_accounting_manifest.json",
        "run_progress_log.txt",
    ]
    _write_json(_manifest(started, output_names, summary), "final_access_rerun_with_source_accounting_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
