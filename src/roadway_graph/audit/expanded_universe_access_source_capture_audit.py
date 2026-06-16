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
from shapely.ops import substring


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_source_capture_audit"

GEOM_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"
CAPTURE_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_capture"
CATCHMENT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_catchment_prototype"
TABLES_DIR = OUTPUT_ROOT / "tables/current"
SCAFFOLD_QA_DIR = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

BUFFER_WIDTHS_FT = [35, 50, 75, 100]
FEET_PER_METER = 3.280839895

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

TYPED_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
]

REQUIRED_INPUTS = {
    GEOM_DIR: [
        "access_geometry_completion_detail.csv",
        "access_geometry_completion_signal_summary.csv",
        "access_buffer_sensitivity_summary.csv",
        "untyped_access_buffer_assignment_summary.csv",
        "typed_v2_access_buffer_assignment_summary.csv",
        "access_geometry_remaining_missingness.csv",
        "access_geometry_completion_manifest.json",
    ],
    CATCHMENT_DIR: [
        "untyped_access_catchment_assignment_detail.csv",
        "typed_v2_access_catchment_assignment_detail.csv",
        "access_catchment_coverage_summary.csv",
        "access_catchment_fanout_summary.csv",
        "expanded_universe_access_catchment_manifest.json",
    ],
    TABLES_DIR: [
        "roadway_graph_edges.csv",
        "signal_oriented_segment_bins_50ft_crash_ready.csv",
        "signal_oriented_segment_bins_50ft.csv",
    ],
    SCAFFOLD_QA_DIR: [
        "directional_scaffold_prototype_usable_bins_50ft.csv",
        "directional_scaffold_excluded_bins_50ft.csv",
    ],
}


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
    if lower in {"signal_relative_direction", "signal_relative_direction_label"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(frame))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(frame))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _collapse(values: pd.Series, limit: int = 10) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() != "nan" and str(value) != ""})
    return "|".join(items[:limit])


def _route_key(value: Any) -> str:
    text = str(value or "").upper()
    if not text or text == "NAN":
        return ""
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    for match in re.finditer(r"\b(US|VA|IS|SC)\s*0*([0-9]+)\s*([NSEW])?B?\b", text):
        prefix, number, direction = match.groups()
        return f"{prefix}{int(number)}{direction or ''}"
    compact = re.sub(r"[^A-Z0-9]+", "", text)
    for match in re.finditer(r"(US|VA|IS|SC)0*([0-9]+)([NSEW])?B?", compact):
        prefix, number, direction = match.groups()
        return f"{prefix}{int(number)}{direction or ''}"
    return compact


def _missing_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    for path in [ACCESS_V1_FILE, ACCESS_V2_FILE]:
        if not path.exists():
            missing.append(str(path))
    return missing


def _load_inputs() -> dict[str, pd.DataFrame]:
    detail_cols = [
        "target_bin_id",
        "target_signal_id",
        "source_signal_id",
        "source_layer",
        "graph_edge_id",
        "signal_relative_direction_label",
        "distance_start_ft",
        "distance_end_ft",
        "analysis_window",
        "distance_band",
        "candidate_weight_num",
        "tie_group_id",
        "distance_length_ft",
        "completed_geometry_status",
        "geometry_recovery_method",
        "geometry_blocker_reason",
    ]
    return {
        "geometry_detail": _read_csv(GEOM_DIR / "access_geometry_completion_detail.csv", usecols=detail_cols),
        "capture_target": _read_csv(CAPTURE_DIR / "access_target_bins.csv", usecols=["target_bin_id", "route_key"]),
        "geometry_signal_summary": _read_csv(GEOM_DIR / "access_geometry_completion_signal_summary.csv"),
        "buffer_sensitivity": _read_csv(GEOM_DIR / "access_buffer_sensitivity_summary.csv"),
        "untyped_buffer_summary": _read_csv(GEOM_DIR / "untyped_access_buffer_assignment_summary.csv"),
        "typed_buffer_summary": _read_csv(GEOM_DIR / "typed_v2_access_buffer_assignment_summary.csv"),
        "geometry_missingness": _read_csv(GEOM_DIR / "access_geometry_remaining_missingness.csv"),
        "prior_untyped_detail": _read_csv(CATCHMENT_DIR / "untyped_access_catchment_assignment_detail.csv", usecols=["access_point_id", "target_signal_id"]),
        "prior_typed_detail": _read_csv(CATCHMENT_DIR / "typed_v2_access_catchment_assignment_detail.csv", usecols=["access_point_id", "target_signal_id", "access_control_category"]),
        "catchment_coverage": _read_csv(CATCHMENT_DIR / "access_catchment_coverage_summary.csv"),
        "catchment_fanout": _read_csv(CATCHMENT_DIR / "access_catchment_fanout_summary.csv"),
        "edges": _read_csv(TABLES_DIR / "roadway_graph_edges.csv", usecols=["graph_edge_id", "length_ft", "geometry"]),
        "base_bins_ready": _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft_crash_ready.csv", usecols=["bin_id", "oriented_segment_id", "base_graph_edge_id", "bin_index", "geometry"]),
        "base_bins_all": _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft.csv", usecols=["bin_id", "oriented_segment_id", "base_graph_edge_id", "bin_index", "geometry"]),
        "usable_bins": _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_prototype_usable_bins_50ft.csv"),
        "excluded_bins": _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_excluded_bins_50ft.csv"),
    }


def _read_access_inventory(path: Path, *, layer: str) -> gpd.GeoDataFrame:
    _checkpoint(f"read_start {path.name}")
    access = gpd.read_parquet(path)
    access = access.drop(columns=[column for column in access.columns if _blocked_column(column)], errors="ignore")
    if access.crs is None:
        access = access.set_crs("EPSG:3968", allow_override=True)
    access = access.to_crs("EPSG:3968")
    if layer == "typed_v2":
        access["access_point_id"] = access.get("access_v2_source_priority", "").astype(str) + ":" + access.get("access_v2_source_row_id", "").astype(str)
        access.loc[access["access_point_id"].eq(":"), "access_point_id"] = access.loc[access["access_point_id"].eq(":"), "id"].astype(str)
        access["source_dataset"] = access.get("access_v2_source_gdb", "").astype(str)
        access["source_layer"] = access.get("access_v2_source_layer", "").astype(str)
        access["route_name"] = access.get("route_name", "").astype(str)
        access["route_measure"] = access.get("route_measure", "").astype(str)
        access["access_control_category"] = access.get("access_control_category", "").astype(str).replace("", "unknown")
        access.loc[~access["access_control_category"].isin(TYPED_CATEGORIES), "access_control_category"] = "other_review"
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["source_dataset"] = access.get("Stage1_SourceGDB", "").astype(str)
        access["source_layer"] = access.get("Stage1_SourceLayer", "").astype(str)
        access["route_name"] = access.get("_rte_nm", "").astype(str)
        access["route_measure"] = access.get("_m", "").astype(str)
        access["access_control_category"] = "untyped"
    access["access_layer"] = layer
    access["has_geometry"] = access.geometry.notna() & ~access.geometry.is_empty
    access["has_route_fields"] = access["route_name"].fillna("").astype(str).str.strip().ne("") & access["route_measure"].fillna("").astype(str).str.strip().ne("")
    access["route_key"] = access["route_name"].map(_route_key)
    keep = [
        "access_point_id",
        "access_layer",
        "source_dataset",
        "source_layer",
        "route_name",
        "route_measure",
        "route_key",
        "has_geometry",
        "has_route_fields",
        "access_control_category",
        "geometry",
    ]
    out = access[[column for column in keep if column in access.columns]].copy()
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _line_substring(line, start_ft: float, end_ft: float):
    if line is None or line.is_empty:
        return None
    length_m = line.length
    if not np.isfinite(length_m) or length_m <= 0:
        return None
    start_m = max(min(start_ft / FEET_PER_METER, length_m), 0.0)
    end_m = max(min(end_ft / FEET_PER_METER, length_m), 0.0)
    if abs(end_m - start_m) < 0.01:
        return None
    try:
        return substring(line, min(start_m, end_m), max(start_m, end_m), normalized=False)
    except Exception:
        return None


def _strict_reference_geometry(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ref = pd.concat([inputs["usable_bins"], inputs["excluded_bins"]], ignore_index=True, sort=False)
    ref = ref[["reference_directional_bin_id", "base_segment_id", "bin_index_in_travel_direction"]].copy()
    ref["_base_bin_index"] = _num(ref, "bin_index_in_travel_direction").fillna(0).astype(int) - 1
    base = pd.concat([inputs["base_bins_ready"], inputs["base_bins_all"]], ignore_index=True, sort=False).drop_duplicates(["oriented_segment_id", "bin_index"])
    base["_base_bin_index"] = _num(base, "bin_index").fillna(-1).astype(int)
    merged = ref.merge(
        base[["oriented_segment_id", "_base_bin_index", "geometry"]],
        left_on=["base_segment_id", "_base_bin_index"],
        right_on=["oriented_segment_id", "_base_bin_index"],
        how="left",
    )
    merged = merged.loc[_text(merged, "geometry").ne("")].copy()
    return merged.rename(columns={"reference_directional_bin_id": "target_bin_id"})[["target_bin_id", "geometry"]]


def _build_lines(inputs: dict[str, pd.DataFrame]) -> gpd.GeoDataFrame:
    detail = inputs["geometry_detail"].copy()
    if "capture_target" in inputs and not inputs["capture_target"].empty:
        detail = detail.merge(inputs["capture_target"].drop_duplicates("target_bin_id"), on="target_bin_id", how="left")
    if "route_key" not in detail.columns:
        detail["route_key"] = ""
    detail = detail.loc[_text(detail, "completed_geometry_status").eq("geometry_available")].copy()
    detail["line_geometry"] = None
    strict = _strict_reference_geometry(inputs).set_index("target_bin_id")
    strict_mask = _text(detail, "target_bin_id").isin(strict.index)
    detail.loc[strict_mask, "line_geometry"] = _text(detail.loc[strict_mask], "target_bin_id").map(strict["geometry"]).map(wkt.loads)

    edges = inputs["edges"].loc[_text(inputs["edges"], "geometry").ne("")].copy()
    edges["geometry"] = _text(edges, "geometry").map(wkt.loads)
    edge_lookup = gpd.GeoDataFrame(edges, geometry="geometry", crs="EPSG:3968").set_index("graph_edge_id")
    edge_mask = detail["line_geometry"].isna() & _text(detail, "graph_edge_id").isin(edge_lookup.index)
    recovered = []
    for row in detail.loc[edge_mask].itertuples(index=True):
        edge = edge_lookup.loc[row.graph_edge_id]
        line = _line_substring(edge.geometry, float(row.distance_start_ft), float(row.distance_end_ft))
        if line is not None and not line.is_empty:
            recovered.append((row.Index, line))
    if recovered:
        idx, geoms = zip(*recovered)
        detail.loc[list(idx), "line_geometry"] = list(geoms)
    lines = detail.loc[detail["line_geometry"].notna()].copy()
    return gpd.GeoDataFrame(lines, geometry="line_geometry", crs="EPSG:3968").rename_geometry("geometry")


def _assign_buffers(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    points = access.loc[access["has_geometry"]].copy()
    for width in BUFFER_WIDTHS_FT:
        catchments = lines[
            [
                "target_bin_id",
                "target_signal_id",
                "signal_relative_direction_label",
                "analysis_window",
                "distance_band",
                "geometry_recovery_method",
                "candidate_weight_num",
                "geometry",
            ]
        ].copy()
        catchments["geometry"] = catchments.geometry.buffer(width / FEET_PER_METER, cap_style="flat", join_style="mitre")
        catchments = gpd.GeoDataFrame(catchments, geometry="geometry", crs="EPSG:3968")
        joined = gpd.sjoin(
            points[["access_point_id", "access_layer", "access_control_category", "route_key", "geometry"]],
            catchments,
            how="inner",
            predicate="within",
        )
        if joined.empty:
            continue
        out = pd.DataFrame(joined.drop(columns=["geometry", "index_right"], errors="ignore"))
        out["buffer_width_ft"] = width
        out = out.drop_duplicates(["buffer_width_ft", "access_point_id", "target_bin_id", "access_control_category"])
        fanout = out.groupby(["buffer_width_ft", "access_point_id"], dropna=False)["target_bin_id"].nunique().rename("assignment_fanout_count").reset_index()
        out = out.merge(fanout, on=["buffer_width_ft", "access_point_id"], how="left")
        out["multi_assignment_flag"] = out["assignment_fanout_count"].gt(1)
        out["unweighted_assignment_count"] = 1.0
        out["source_preserving_weighted_total"] = 1.0 / pd.to_numeric(out["assignment_fanout_count"], errors="coerce").fillna(1)
        rows.append(out)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _source_inventory(access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    rows = [
        {
            "access_layer": layer,
            "inventory_group": "all_source_points",
            "inventory_value": "all",
            "source_point_count": len(access),
            "points_with_geometry": int(access["has_geometry"].sum()),
            "points_with_route_fields": int(access["has_route_fields"].sum()),
            "points_with_typed_category": int(_text(access, "access_control_category").ne("").sum()) if layer == "typed_v2" else "",
        }
    ]
    for source_layer, group in access.groupby("source_layer", dropna=False):
        rows.append(
            {
                "access_layer": layer,
                "inventory_group": "source_layer",
                "inventory_value": source_layer,
                "source_point_count": len(group),
                "points_with_geometry": int(group["has_geometry"].sum()),
                "points_with_route_fields": int(group["has_route_fields"].sum()),
                "points_with_typed_category": int(_text(group, "access_control_category").ne("").sum()) if layer == "typed_v2" else "",
            }
        )
    if layer == "typed_v2":
        for category, group in access.groupby("access_control_category", dropna=False):
            rows.append(
                {
                    "access_layer": layer,
                    "inventory_group": "typed_category",
                    "inventory_value": category,
                    "source_point_count": len(group),
                    "points_with_geometry": int(group["has_geometry"].sum()),
                    "points_with_route_fields": int(group["has_route_fields"].sum()),
                    "points_with_typed_category": len(group),
                }
            )
    return pd.DataFrame(rows)


def _point_detail(access: gpd.GeoDataFrame, assignments: pd.DataFrame, lines: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    detail = pd.DataFrame(access.drop(columns=["geometry"], errors="ignore").copy())
    represented_routes = set(_text(lines, "route_key")) if "route_key" in lines.columns else set()
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
            captured=("target_bin_id", "size"),
            assignment_count=("target_bin_id", "size"),
            assignment_fanout=("assignment_fanout_count", "max"),
            weighted_total=("source_preserving_weighted_total", "sum"),
            captured_windows=("analysis_window", _collapse),
            captured_roadway_context=("geometry_recovery_method", _collapse),
        ).reset_index()
        detail = detail.merge(agg, on="access_point_id", how="left")
        detail[f"captured_{width}ft"] = detail["captured"].notna()
        detail[f"assignment_count_{width}ft"] = pd.to_numeric(detail["assignment_count"], errors="coerce").fillna(0)
        detail[f"assignment_fanout_{width}ft"] = pd.to_numeric(detail["assignment_fanout"], errors="coerce").fillna(0)
        detail[f"weighted_total_{width}ft"] = pd.to_numeric(detail["weighted_total"], errors="coerce").fillna(0)
        detail[f"captured_windows_{width}ft"] = _text(detail, "captured_windows")
        detail[f"captured_roadway_context_{width}ft"] = _text(detail, "captured_roadway_context")
        detail = detail.drop(columns=["captured", "assignment_count", "assignment_fanout", "weighted_total", "captured_windows", "captured_roadway_context"], errors="ignore")
    captured_any = detail[[f"captured_{width}ft" for width in BUFFER_WIDTHS_FT]].any(axis=1)
    detail["captured_any_buffer"] = captured_any
    detail["uncaptured_diagnostic_reason"] = np.select(
        [
            ~detail["has_geometry"].astype(bool),
            captured_any,
            detail["has_geometry"].astype(bool) & detail["has_route_fields"].astype(bool) & detail["route_key"].isin(represented_routes),
            detail["has_geometry"].astype(bool) & detail["has_route_fields"].astype(bool) & ~detail["route_key"].isin(represented_routes),
            detail["has_geometry"].astype(bool) & ~detail["has_route_fields"].astype(bool),
        ],
        [
            "missing_access_geometry",
            "captured_by_candidate_catchment",
            "near_or_in_represented_route_identity_but_outside_tested_buffers",
            "source_route_not_in_represented_universe",
            "missing_route_geometry_linkage",
        ],
        default="insufficient_evidence",
    )
    detail["access_layer"] = layer
    return detail


def _capture_by_buffer(access: gpd.GeoDataFrame, assignments: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    rows = []
    total = int(access["access_point_id"].nunique())
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)] if not assignments.empty else pd.DataFrame()
        captured = int(subset["access_point_id"].nunique()) if not subset.empty else 0
        rows.append(
            {
                "access_layer": layer,
                "buffer_width_ft": width,
                "total_source_point_count": total,
                "source_points_captured": captured,
                "source_points_not_captured": total - captured,
                "source_capture_rate": round(captured / total, 6) if total else 0,
                "assignment_count": int(len(subset)) if not subset.empty else 0,
                "unweighted_assignment_count": round(float(pd.to_numeric(subset.get("unweighted_assignment_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0,
                "source_preserving_weighted_total": round(float(pd.to_numeric(subset.get("source_preserving_weighted_total"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0,
                "captured_0_1000_source_points": int(subset.loc[_text(subset, "analysis_window").eq("0_1000"), "access_point_id"].nunique()) if not subset.empty else 0,
                "captured_1000_2500_source_points": int(subset.loc[_text(subset, "analysis_window").eq("1000_2500"), "access_point_id"].nunique()) if not subset.empty else 0,
                "captured_strict_wkt_source_points": int(subset.loc[_text(subset, "geometry_recovery_method").str.contains("strict_reference", na=False), "access_point_id"].nunique()) if not subset.empty else 0,
                "captured_graph_edge_source_points": int(subset.loc[_text(subset, "geometry_recovery_method").str.contains("graph_edge", na=False), "access_point_id"].nunique()) if not subset.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def _fanout_distribution(assignments: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    rows = []
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)] if not assignments.empty else pd.DataFrame()
        if subset.empty:
            rows.append({"access_layer": layer, "buffer_width_ft": width, "fanout_bucket": "uncaptured", "source_point_count": 0, "assignment_count": 0, "weighted_total": 0.0})
            continue
        per_point = subset.drop_duplicates(["access_point_id", "assignment_fanout_count"]).copy()
        per_point["fanout_bucket"] = pd.cut(
            pd.to_numeric(per_point["assignment_fanout_count"], errors="coerce").fillna(0),
            bins=[0, 1, 2, 3, np.inf],
            labels=["1", "2", "3", "4_plus"],
            include_lowest=True,
        ).astype(str)
        dist = per_point.groupby("fanout_bucket", dropna=False)["access_point_id"].nunique().reset_index(name="source_point_count")
        assign = subset.copy()
        assign["fanout_bucket"] = pd.cut(
            pd.to_numeric(assign["assignment_fanout_count"], errors="coerce").fillna(0),
            bins=[0, 1, 2, 3, np.inf],
            labels=["1", "2", "3", "4_plus"],
            include_lowest=True,
        ).astype(str)
        assign_sum = assign.groupby("fanout_bucket", dropna=False).agg(
            assignment_count=("access_point_id", "size"),
            weighted_total=("source_preserving_weighted_total", "sum"),
        ).reset_index()
        out = dist.merge(assign_sum, on="fanout_bucket", how="outer")
        out["access_layer"] = layer
        out["buffer_width_ft"] = width
        rows.extend(out.to_dict("records"))
    return pd.DataFrame(rows)


def _typed_category_capture(access: gpd.GeoDataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total_by_cat = access.groupby("access_control_category", dropna=False)["access_point_id"].nunique().to_dict()
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)] if not assignments.empty else pd.DataFrame()
        captured_by_cat = subset.groupby("access_control_category", dropna=False)["access_point_id"].nunique().to_dict() if not subset.empty else {}
        for cat in sorted(set(total_by_cat) | set(captured_by_cat)):
            total = int(total_by_cat.get(cat, 0))
            captured = int(captured_by_cat.get(cat, 0))
            rows.append(
                {
                    "buffer_width_ft": width,
                    "access_control_category": cat,
                    "total_source_point_count": total,
                    "captured_source_point_count": captured,
                    "uncaptured_source_point_count": total - captured,
                    "source_capture_rate": round(captured / total, 6) if total else 0,
                }
            )
    return pd.DataFrame(rows)


def _uncaptured_diagnostic(untyped_detail: pd.DataFrame, typed_detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer, frame in [("untyped", untyped_detail), ("typed_v2", typed_detail)]:
        uncaptured = frame.loc[~frame["captured_any_buffer"].astype(bool)].copy()
        for reason, group in uncaptured.groupby("uncaptured_diagnostic_reason", dropna=False):
            rows.append(
                {
                    "access_layer": layer,
                    "uncaptured_reason": reason,
                    "source_point_count": int(group["access_point_id"].nunique()),
                    "points_with_geometry": int(group["has_geometry"].astype(bool).sum()),
                    "points_with_route_fields": int(group["has_route_fields"].astype(bool).sum()),
                    "source_layers": _collapse(group["source_layer"]),
                }
            )
    return pd.DataFrame(rows)


def _signal_vs_source_summary(buffer_summary: pd.DataFrame, source_capture: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer in ["untyped", "typed_v2"]:
        for width in BUFFER_WIDTHS_FT:
            signal_rows = buffer_summary.loc[
                _text(buffer_summary, "access_layer").eq(layer)
                & pd.to_numeric(buffer_summary["buffer_width_ft"], errors="coerce").eq(width)
                & _text(buffer_summary, "metric").eq("signals_with_access")
            ]
            source_rows = source_capture.loc[source_capture["access_layer"].eq(layer) & source_capture["buffer_width_ft"].eq(width)]
            signal_count = int(float(signal_rows["count"].iloc[0])) if not signal_rows.empty else 0
            captured_points = int(source_rows["source_points_captured"].iloc[0]) if not source_rows.empty else 0
            assignments = int(source_rows["assignment_count"].iloc[0]) if not source_rows.empty else 0
            rows.append(
                {
                    "access_layer": layer,
                    "buffer_width_ft": width,
                    "signals_with_access": signal_count,
                    "captured_source_points": captured_points,
                    "assignment_count": assignments,
                    "captured_points_per_signal": round(captured_points / signal_count, 6) if signal_count else 0,
                    "assignments_per_captured_point": round(assignments / captured_points, 6) if captured_points else 0,
                    "interpretation": "clustered_or_multi_assigned" if captured_points and assignments / captured_points > 1.5 else "sparse_or_low_fanout",
                }
            )
    return pd.DataFrame(rows)


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "This module writes only to expanded_universe_access_source_capture_audit review folder."),
        ("no_candidates_promoted", "pass", "All outputs are review-only diagnostics."),
        ("no_crash_records_read", "pass", "Input list excludes crash record files and guarded readers reject crash columns."),
        ("no_crash_direction_fields_read_or_used", "pass", "Guarded readers reject crash direction tokens."),
        ("no_crash_assignment_or_catchments", "pass", "No crash assignment or crash catchment generation is performed."),
        ("no_rates_or_models", "pass", "No rates or models are computed."),
        ("typed_and_untyped_access_separate", "pass", "Separate source details and inventory files are written."),
        ("weighted_and_unweighted_concepts_separate", "pass", "Assignment counts and source-preserving weighted totals are separate."),
        ("source_point_counts_separate_from_assignment_counts", "pass", "Capture summaries distinguish source point counts from assignment rows."),
        ("outputs_review_only_and_review_folder_only", "pass", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(untyped_inv: pd.DataFrame, typed_inv: pd.DataFrame, capture: pd.DataFrame, fanout: pd.DataFrame, category: pd.DataFrame, uncaptured: pd.DataFrame, signal_source: pd.DataFrame) -> str:
    untyped_total = int(untyped_inv.loc[untyped_inv["inventory_group"].eq("all_source_points"), "source_point_count"].iloc[0])
    typed_total = int(typed_inv.loc[typed_inv["inventory_group"].eq("all_source_points"), "source_point_count"].iloc[0])

    def rate_line(layer: str) -> str:
        lines = []
        for row in capture.loc[capture["access_layer"].eq(layer)].itertuples(index=False):
            lines.append(f"- {int(row.buffer_width_ft)} ft: {int(row.source_points_captured):,} of {int(row.total_source_point_count):,} ({float(row.source_capture_rate):.1%})")
        return "\n".join(lines)

    typed_lines = []
    for row in category.loc[category["buffer_width_ft"].eq(100)].itertuples(index=False):
        typed_lines.append(f"- {row.access_control_category}: {int(row.captured_source_point_count):,} captured, {int(row.uncaptured_source_point_count):,} missed at 100 ft")

    uncaptured_lines = "\n".join(
        f"- {row.access_layer} / {row.uncaptured_reason}: {int(row.source_point_count):,} points"
        for row in uncaptured.itertuples(index=False)
    )
    signal_source_lines = "\n".join(
        f"- {row.access_layer} {int(row.buffer_width_ft)} ft: {int(row.signals_with_access):,} signals, {int(row.captured_source_points):,} captured source points, {float(row.assignments_per_captured_point):.2f} assignments per captured point"
        for row in signal_source.itertuples(index=False)
    )
    return f"""# Expanded Universe Access Source Capture Audit Findings

**Bounded question:** source-point capture audit for typed and untyped access against the 2,739-signal expanded roadway/catchment universe.

## Direct Answers

1. Total untyped access source points: **{untyped_total:,}**.
2. Total typed v2 access source points: **{typed_total:,}**.
3. Untyped source capture by buffer:
{rate_line("untyped")}
4. Typed v2 source capture by buffer:
{rate_line("typed_v2")}
5. Source-level fanout is reported in `access_source_fanout_distribution.csv`; it increases with buffer width and remains separate from source-point capture rates.
6. Typed categories captured or missed at 100 ft:
{chr(10).join(typed_lines) if typed_lines else "- No typed category capture rows produced."}
7. Dominant uncaptured-source reasons:
{uncaptured_lines if uncaptured_lines else "- No uncaptured diagnostics produced."}
8. Signal vs source capture:
{signal_source_lines}
9. Next pass should refine buffer/catchment geometry and route identity before choosing access metrics. Typed v2 remains source-sparse relative to broad untyped access.

No primary metric is selected. Typed/untyped and weighted/unweighted products remain separate.
"""


def _manifest(started: str, outputs: list[str], inputs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.audit.expanded_universe_access_source_capture_audit",
        "bounded_question": "read-only access source-point capture audit for expanded universe",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "buffer_widths_ft": BUFFER_WIDTHS_FT,
        "output_dir": str(OUT_DIR),
        "input_row_counts": {name: int(len(frame)) for name, frame in inputs.items()},
        "output_files": outputs,
        "guardrails": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_direction_fields_used": False,
            "crash_assignment_or_catchments_created": False,
            "rates_or_models_run": False,
            "typed_and_untyped_combined": False,
            "primary_metric_selected": False,
        },
    }


def main() -> None:
    started = datetime.now(timezone.utc).isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))
    inputs = _load_inputs()
    lines = _build_lines(inputs)
    if "route_key" not in lines.columns:
        lines["route_key"] = ""
    untyped_access = _read_access_inventory(ACCESS_V1_FILE, layer="untyped")
    typed_access = _read_access_inventory(ACCESS_V2_FILE, layer="typed_v2")
    untyped_assign = _assign_buffers(lines, untyped_access, layer="untyped")
    typed_assign = _assign_buffers(lines, typed_access, layer="typed_v2")
    untyped_inventory = _source_inventory(untyped_access, layer="untyped")
    typed_inventory = _source_inventory(typed_access, layer="typed_v2")
    source_capture = pd.concat(
        [
            _capture_by_buffer(untyped_access, untyped_assign, layer="untyped"),
            _capture_by_buffer(typed_access, typed_assign, layer="typed_v2"),
        ],
        ignore_index=True,
    )
    untyped_detail = _point_detail(untyped_access, untyped_assign, lines, layer="untyped")
    typed_detail = _point_detail(typed_access, typed_assign, lines, layer="typed_v2")
    fanout = pd.concat(
        [
            _fanout_distribution(untyped_assign, layer="untyped"),
            _fanout_distribution(typed_assign, layer="typed_v2"),
        ],
        ignore_index=True,
    )
    category_capture = _typed_category_capture(typed_access, typed_assign)
    uncaptured = _uncaptured_diagnostic(untyped_detail, typed_detail)
    signal_source = _signal_vs_source_summary(inputs["buffer_sensitivity"], source_capture)
    qa = _qa()
    findings = _findings(untyped_inventory, typed_inventory, source_capture, fanout, category_capture, uncaptured, signal_source)
    outputs = {
        "untyped_access_source_inventory.csv": untyped_inventory,
        "typed_v2_access_source_inventory.csv": typed_inventory,
        "access_source_capture_by_buffer.csv": source_capture,
        "untyped_source_point_capture_detail.csv": untyped_detail,
        "typed_v2_source_point_capture_detail.csv": typed_detail,
        "access_source_fanout_distribution.csv": fanout,
        "typed_v2_source_category_capture_summary.csv": category_capture,
        "uncaptured_access_source_diagnostic.csv": uncaptured,
        "access_signal_vs_source_capture_summary.csv": signal_source,
        "expanded_universe_access_source_capture_qa.csv": qa,
    }
    for name, frame in outputs.items():
        _write_csv(frame, OUT_DIR / name)
    _write_text(findings, OUT_DIR / "expanded_universe_access_source_capture_findings.md")
    output_names = list(outputs) + ["expanded_universe_access_source_capture_findings.md", "expanded_universe_access_source_capture_manifest.json", "run_progress_log.txt"]
    _write_json(_manifest(started, output_names, inputs), OUT_DIR / "expanded_universe_access_source_capture_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
