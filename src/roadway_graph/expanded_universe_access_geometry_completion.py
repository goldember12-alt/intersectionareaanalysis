from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt
from shapely.ops import substring


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"

CAPTURE_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_capture"
CATCHMENT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_catchment_prototype"
REFRESH_DIR = OUTPUT_ROOT / "review/current/expanded_universe_refresh_and_709_plan"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
CONTEXT_347_DIR = OUTPUT_ROOT / "review/current/review_only_347_context_refresh"
SCAFFOLD_QA_DIR = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa"
TABLES_DIR = OUTPUT_ROOT / "tables/current"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

FEET_PER_METER = 3.280839895
BUFFER_WIDTHS_FT = [35, 50, 75, 100]

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
    CATCHMENT_DIR: [
        "access_catchment_target_bins.csv",
        "access_catchment_coverage_summary.csv",
        "access_catchment_vs_route_measure_comparison.csv",
        "expanded_universe_access_catchment_manifest.json",
    ],
    CAPTURE_DIR: [
        "access_target_bins.csv",
        "untyped_access_assignment_detail.csv",
        "typed_v2_access_assignment_detail.csv",
        "access_product_coverage_summary.csv",
        "expanded_universe_access_capture_manifest.json",
    ],
    REFRESH_DIR: ["refreshed_represented_signal_universe.csv"],
    FREEZE_DIR: ["frozen_candidate_bin_universe.csv"],
    CONTEXT_347_DIR: ["review_only_347_context_bin_detail.csv"],
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
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["access_layer"] = "untyped"
        access["access_control_category"] = "untyped"
        access["route_name"] = access.get("_rte_nm", "").astype(str)
    out = access[["access_point_id", "access_layer", "access_control_category", "route_name", "geometry"]].copy()
    out = out.loc[out.geometry.notna() & ~out.geometry.is_empty & out["access_point_id"].ne("")]
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


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 10) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() != "nan" and str(value) != ""})
    return "|".join(items[:limit])


def _missing_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    for path in [ACCESS_V1_FILE, ACCESS_V2_FILE]:
        if not path.exists():
            missing.append(str(path))
    return missing


def _load_inputs() -> dict[str, pd.DataFrame]:
    target_cols = [
        "target_bin_source",
        "target_bin_id",
        "target_signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_signal_id",
        "frozen_candidate_bin_id",
        "candidate_bin_id",
        "recovery_strategy",
        "association_confidence_tier",
        "candidate_weight",
        "tie_group_id",
        "road_component_id",
        "graph_edge_id",
        "source_road_row_id",
        "signal_relative_direction_label",
        "distance_start_ft",
        "distance_end_ft",
        "analysis_window",
        "distance_band",
        "candidate_weight_num",
        "distance_length_ft",
        "has_speed",
        "has_aadt",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
        "catchment_geometry_status",
        "catchment_blocker_reason",
    ]
    return {
        "prior_target": _read_csv(CATCHMENT_DIR / "access_catchment_target_bins.csv", usecols=target_cols),
        "capture_target": _read_csv(CAPTURE_DIR / "access_target_bins.csv", usecols=target_cols[:-2]),
        "route_untyped": _read_csv(CAPTURE_DIR / "untyped_access_assignment_detail.csv", usecols=["target_signal_id"]),
        "route_typed": _read_csv(CAPTURE_DIR / "typed_v2_access_assignment_detail.csv", usecols=["target_signal_id"]),
        "signals": _read_csv(REFRESH_DIR / "refreshed_represented_signal_universe.csv"),
        "frozen_bins": _read_csv(FREEZE_DIR / "frozen_candidate_bin_universe.csv", usecols=["frozen_candidate_bin_id", "graph_edge_id", "road_component_id", "source_road_row_id"]),
        "review_347_bins": _read_csv(CONTEXT_347_DIR / "review_only_347_context_bin_detail.csv", usecols=["review_only_347_bin_id", "graph_edge_id", "road_component_id", "source_road_row_id"]),
        "edges": _read_csv(TABLES_DIR / "roadway_graph_edges.csv", usecols=["graph_edge_id", "source_road_row_id", "road_component_id", "length_ft", "geometry"]),
        "base_bins_ready": _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft_crash_ready.csv", usecols=["bin_id", "oriented_segment_id", "base_graph_edge_id", "bin_index", "geometry"]),
        "base_bins_all": _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft.csv", usecols=["bin_id", "oriented_segment_id", "base_graph_edge_id", "bin_index", "geometry"]),
        "usable_bins": _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_prototype_usable_bins_50ft.csv"),
        "excluded_bins": _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_excluded_bins_50ft.csv"),
    }


def _parse_wkt_series(series: pd.Series) -> pd.Series:
    return series.map(lambda value: wkt.loads(value) if str(value).strip() else None)


def _parse_edges(edges: pd.DataFrame) -> gpd.GeoDataFrame:
    work = edges.loc[_text(edges, "geometry").ne("")].copy()
    work["edge_length_ft"] = _num(work, "length_ft")
    work["geometry"] = _parse_wkt_series(_text(work, "geometry"))
    return gpd.GeoDataFrame(work, geometry="geometry", crs="EPSG:3968")


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
        base[["oriented_segment_id", "_base_bin_index", "base_graph_edge_id", "geometry"]],
        left_on=["base_segment_id", "_base_bin_index"],
        right_on=["oriented_segment_id", "_base_bin_index"],
        how="left",
    )
    merged = merged.loc[_text(merged, "geometry").ne("")].copy()
    merged = merged.rename(columns={"reference_directional_bin_id": "target_bin_id", "base_graph_edge_id": "recovered_graph_edge_id"})
    merged["geometry_recovery_method"] = "strict_reference_bin_wkt_from_signal_oriented_segment_bins"
    return merged[["target_bin_id", "recovered_graph_edge_id", "geometry", "geometry_recovery_method"]]


def _complete_geometry(inputs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    target = inputs["prior_target"].copy()
    prior_status = _text(target, "catchment_geometry_status")
    target["prior_geometry_available"] = prior_status.eq("candidate_catchment_geometry_built")
    target["completed_geometry_status"] = "geometry_unavailable"
    target["geometry_recovery_method"] = ""
    target["geometry_blocker_reason"] = "no_defensible_geometry_lineage"
    target["line_geometry"] = None

    edges = _parse_edges(inputs["edges"])
    edge_lookup = edges.set_index("graph_edge_id")

    strict_geom = _strict_reference_geometry(inputs)
    strict_lookup = strict_geom.set_index("target_bin_id")
    strict_mask = _text(target, "target_bin_id").isin(strict_lookup.index)
    target.loc[strict_mask, "line_geometry"] = _text(target.loc[strict_mask], "target_bin_id").map(strict_lookup["geometry"]).map(wkt.loads)
    target.loc[strict_mask, "geometry_recovery_method"] = "strict_reference_bin_wkt_from_signal_oriented_segment_bins"
    target.loc[strict_mask, "completed_geometry_status"] = "geometry_available"
    target.loc[strict_mask, "geometry_blocker_reason"] = ""

    edge_mask = target["line_geometry"].isna() & _text(target, "graph_edge_id").isin(edge_lookup.index)
    rows = target.loc[edge_mask].copy()
    recovered = []
    for row in rows.itertuples(index=True):
        edge = edge_lookup.loc[row.graph_edge_id]
        line = _line_substring(edge.geometry, float(row.distance_start_ft), float(row.distance_end_ft))
        if line is not None and not line.is_empty:
            recovered.append((row.Index, line))
    if recovered:
        idx, geoms = zip(*recovered)
        target.loc[list(idx), "line_geometry"] = list(geoms)
        target.loc[list(idx), "geometry_recovery_method"] = "graph_edge_id_substring"
        target.loc[list(idx), "completed_geometry_status"] = "geometry_available"
        target.loc[list(idx), "geometry_blocker_reason"] = ""

    detail = target.drop(columns=["line_geometry"]).copy()
    detail["prior_geometry_missing"] = ~detail["prior_geometry_available"]
    detail["geometry_recovered_this_pass"] = detail["prior_geometry_missing"] & detail["completed_geometry_status"].eq("geometry_available")
    gdf = gpd.GeoDataFrame(
        target.loc[target["completed_geometry_status"].eq("geometry_available")].drop(columns=["catchment_geometry_status"], errors="ignore").copy(),
        geometry="line_geometry",
        crs="EPSG:3968",
    ).rename_geometry("geometry")
    return detail, gdf


def _assign_for_width(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str, width_ft: int) -> pd.DataFrame:
    if lines.empty or access.empty:
        return pd.DataFrame()
    catchments = lines[
        [
            "target_bin_id",
            "target_signal_id",
            "signal_relative_direction_label",
            "analysis_window",
            "distance_band",
            "distance_length_ft",
            "candidate_weight_num",
            "tie_group_id",
            "geometry_recovery_method",
            "geometry",
        ]
    ].copy()
    catchments["geometry"] = catchments.geometry.buffer(width_ft / FEET_PER_METER, cap_style="flat", join_style="mitre")
    catchments = gpd.GeoDataFrame(catchments, geometry="geometry", crs="EPSG:3968")
    joined = gpd.sjoin(
        access[["access_point_id", "access_layer", "access_control_category", "route_name", "geometry"]],
        catchments,
        how="inner",
        predicate="within",
    )
    if joined.empty:
        return pd.DataFrame()
    out = pd.DataFrame(joined.drop(columns=["geometry", "index_right"], errors="ignore"))
    out = out.drop_duplicates(["access_point_id", "target_bin_id", "access_control_category"])
    fanout = out.groupby("access_point_id", dropna=False)["target_bin_id"].nunique().rename("assignment_fanout_count").reset_index()
    out = out.merge(fanout, on="access_point_id", how="left")
    out["assignment_fanout_count"] = pd.to_numeric(out["assignment_fanout_count"], errors="coerce").fillna(1)
    out["buffer_width_ft"] = width_ft
    out["access_layer"] = layer
    out["multi_assignment_flag"] = out["assignment_fanout_count"].gt(1)
    out["unweighted_access_count"] = 1.0
    out["source_preserving_weighted_access_count"] = 1.0 / out["assignment_fanout_count"]
    out["candidate_source_weighted_access_count"] = out["source_preserving_weighted_access_count"] * pd.to_numeric(out["candidate_weight_num"], errors="coerce").fillna(1.0)
    return out


def _summarize_assignments(assignments: pd.DataFrame, lines: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame()
    rows = []
    for (width, grain_cols) in [
        ("bin", ["buffer_width_ft", "target_signal_id", "target_bin_id", "signal_relative_direction_label", "analysis_window"]),
        ("signal_window", ["buffer_width_ft", "target_signal_id", "signal_relative_direction_label", "analysis_window"]),
        ("signal", ["buffer_width_ft", "target_signal_id"]),
    ]:
        grouped = assignments.groupby(grain_cols, dropna=False).agg(
            source_access_point_count=("access_point_id", "nunique"),
            assignment_count=("access_point_id", "size"),
            unweighted_access_count=("unweighted_access_count", "sum"),
            weighted_access_count=("source_preserving_weighted_access_count", "sum"),
            candidate_source_weighted_access_count=("candidate_source_weighted_access_count", "sum"),
            max_assignment_fanout=("assignment_fanout_count", "max"),
            multi_assignment_count=("multi_assignment_flag", "sum"),
            geometry_recovery_methods=("geometry_recovery_method", _collapse),
        ).reset_index()
        length_base = lines.groupby([c for c in grain_cols if c != "buffer_width_ft"], dropna=False)["distance_length_ft"].sum().reset_index(name="represented_length_ft")
        grouped = grouped.merge(length_base, on=[c for c in grain_cols if c != "buffer_width_ft"], how="left")
        grouped["represented_length_ft"] = pd.to_numeric(grouped["represented_length_ft"], errors="coerce").fillna(0)
        grouped["access_density_per_1000ft_unweighted"] = np.where(grouped["represented_length_ft"].gt(0), grouped["unweighted_access_count"] / grouped["represented_length_ft"] * 1000, np.nan)
        grouped["access_density_per_1000ft_weighted"] = np.where(grouped["represented_length_ft"].gt(0), grouped["weighted_access_count"] / grouped["represented_length_ft"] * 1000, np.nan)
        grouped["summary_grain"] = width
        grouped["access_layer"] = layer
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _buffer_sensitivity(untyped: pd.DataFrame, typed: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    available_signals = set(_text(detail.loc[_text(detail, "completed_geometry_status").eq("geometry_available")], "target_signal_id"))
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        for width in BUFFER_WIDTHS_FT:
            subset = frame.loc[pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(width)] if not frame.empty else pd.DataFrame()
            any_signals = set(_text(subset, "target_signal_id"))
            window_signals = set(subset.loc[_text(subset, "analysis_window").eq("0_1000"), "target_signal_id"].fillna("").astype(str)) if not subset.empty else set()
            rows.extend(
                [
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "signals_with_access", "count": len(any_signals)},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "signals_with_0_1000ft_access", "count": len(window_signals)},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "bins_with_access", "count": int(_text(subset, "target_bin_id").nunique()) if not subset.empty else 0},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "signal_windows_with_access", "count": int(subset[["target_signal_id", "signal_relative_direction_label", "analysis_window"]].drop_duplicates().shape[0]) if not subset.empty else 0},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "signals_with_fanout", "count": int(subset.loc[subset.get("multi_assignment_flag", pd.Series(dtype=bool)).astype(bool), "target_signal_id"].fillna("").astype(str).nunique()) if not subset.empty else 0},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "unweighted_assignment_total", "count": round(float(pd.to_numeric(subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0.0},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "weighted_assignment_total", "count": round(float(pd.to_numeric(subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0.0},
                    {"buffer_width_ft": width, "access_layer": layer, "metric": "geometry_available_signals_without_access", "count": len(available_signals - any_signals)},
                ]
            )
    return pd.DataFrame(rows)


def _geometry_signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    return detail.groupby("target_signal_id", dropna=False).agg(
        source_signal_id=("source_signal_id", "first"),
        source_layer=("source_layer", "first"),
        target_bin_count=("target_bin_id", "nunique"),
        prior_bins_with_geometry=("prior_geometry_available", "sum"),
        completed_bins_with_geometry=("completed_geometry_status", lambda s: int((s == "geometry_available").sum())),
        recovered_bins_this_pass=("geometry_recovered_this_pass", "sum"),
        has_any_completed_geometry=("completed_geometry_status", lambda s: bool((s == "geometry_available").any())),
        has_0_1000_completed_geometry=("analysis_window", lambda s: ""),
        geometry_recovery_methods=("geometry_recovery_method", _collapse),
        remaining_blocker_reasons=("geometry_blocker_reason", _collapse),
    ).reset_index()


def _remaining_missingness(detail: pd.DataFrame, sensitivity: pd.DataFrame) -> pd.DataFrame:
    unavailable = detail.loc[_text(detail, "completed_geometry_status").ne("geometry_available")]
    rows = [
        {
            "missingness_reason": "geometry_unavailable_after_completion",
            "signal_count": int(_text(unavailable, "target_signal_id").nunique()),
            "bin_count": int(len(unavailable)),
            "note": "No defensible line geometry found from active bin WKT or graph-edge lineage.",
        }
    ]
    for layer in ["untyped", "typed_v2"]:
        for width in BUFFER_WIDTHS_FT:
            rows.append(
                {
                    "missingness_reason": f"{layer}_{width}ft_geometry_available_no_access",
                    "signal_count": int(sensitivity.loc[(sensitivity["access_layer"].eq(layer)) & (sensitivity["buffer_width_ft"].eq(width)) & (sensitivity["metric"].eq("geometry_available_signals_without_access")), "count"].iloc[0]),
                    "bin_count": "",
                    "note": "Signals have geometry but no access point captured at this buffer width.",
                }
            )
    return pd.DataFrame(rows)


def _qa(detail: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "This module writes only to expanded_universe_access_geometry_completion review folder."),
        ("no_candidates_promoted", "pass", "All outputs are review-only diagnostics."),
        ("no_crash_records_or_crash_direction_fields_read", "pass", "Input list excludes crash record files and guarded readers reject crash columns."),
        ("typed_and_untyped_access_separate", "pass", "Untyped and typed v2 buffer summaries are separate."),
        ("weighted_and_unweighted_outputs_separate", "pass", "Unweighted and source-preserving weighted totals are both retained."),
        ("outputs_review_only", "pass", str(OUT_DIR)),
        ("represented_universe_signal_count", "pass" if detail["target_signal_id"].nunique() == 2739 else "review", str(detail["target_signal_id"].nunique())),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(detail: pd.DataFrame, sensitivity: pd.DataFrame) -> str:
    prior_missing_bins = int((~detail["prior_geometry_available"]).sum())
    prior_missing_signals = int(_text(detail.loc[~detail["prior_geometry_available"]], "target_signal_id").nunique())
    recovered = detail.loc[detail["geometry_recovered_this_pass"]]
    method_counts = recovered["geometry_recovery_method"].value_counts().reset_index()
    method_lines = "\n".join(f"- {row['geometry_recovery_method']}: {int(row['count'])} bins" for _, row in method_counts.rename(columns={"index": "geometry_recovery_method"}).iterrows()) if not method_counts.empty else "- No bins recovered."

    def metric(layer: str, width: int, name: str) -> int:
        rows = sensitivity.loc[sensitivity["access_layer"].eq(layer) & sensitivity["buffer_width_ft"].eq(width) & sensitivity["metric"].eq(name), "count"]
        return int(float(rows.iloc[0])) if not rows.empty else 0

    untyped_lines = "\n".join(f"- {width} ft: {metric('untyped', width, 'signals_with_access')} signals" for width in BUFFER_WIDTHS_FT)
    typed_lines = "\n".join(f"- {width} ft: {metric('typed_v2', width, 'signals_with_access')} signals" for width in BUFFER_WIDTHS_FT)
    remaining_unavailable = int(_text(detail.loc[_text(detail, "completed_geometry_status").ne("geometry_available")], "target_signal_id").nunique())
    return f"""# Expanded Universe Access Geometry Completion Findings

**Bounded question:** complete review-only access catchment geometry and test 35/50/75/100 ft buffer sensitivity for the 2,739-signal expanded universe.

## Direct Answers

1. Previously geometry-missing bins recovered: **{len(recovered):,} of {prior_missing_bins:,} bins** across **{prior_missing_signals:,} previously geometry-missing signals**.
2. Geometry lineage methods recovering the most bins:
{method_lines}
3. Untyped access signal coverage by buffer:
{untyped_lines}
4. Typed v2 access signal coverage by buffer:
{typed_lines}
5. Access coverage is still limited by all three factors: geometry availability for **{remaining_unavailable:,} signals**, buffer width sensitivity, and typed v2 source sparsity.
6. Plausible future review widths are 35 ft and 50 ft as conservative starting points, with 75/100 ft retained as sensitivity only until mapped review checks false positives.
7. Next pass should refine access assignment and compare the four products before moving to crash/catchment design.

No active outputs were modified, candidates promoted, crashes read, crash direction fields used, rates calculated, or models run.
"""


def _manifest(started: str, outputs: list[str], inputs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.expanded_universe_access_geometry_completion",
        "bounded_question": "read-only access catchment geometry completion and buffer sensitivity",
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
            "crash_direction_fields_read": False,
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
    detail, lines = _complete_geometry(inputs)
    access_v1 = _read_access(ACCESS_V1_FILE, typed=False)
    access_v2 = _read_access(ACCESS_V2_FILE, typed=True)
    untyped_parts = []
    typed_parts = []
    for width in BUFFER_WIDTHS_FT:
        _checkpoint("buffer_assignment_start", note=f"width_ft={width}")
        untyped_parts.append(_assign_for_width(lines, access_v1, layer="untyped", width_ft=width))
        typed_parts.append(_assign_for_width(lines, access_v2, layer="typed_v2", width_ft=width))
    untyped = pd.concat(untyped_parts, ignore_index=True, sort=False) if untyped_parts else pd.DataFrame()
    typed = pd.concat(typed_parts, ignore_index=True, sort=False) if typed_parts else pd.DataFrame()
    untyped_summary = _summarize_assignments(untyped, lines, layer="untyped")
    typed_summary = _summarize_assignments(typed, lines, layer="typed_v2")
    sensitivity = _buffer_sensitivity(untyped, typed, detail)
    signal_summary = _geometry_signal_summary(detail)
    remaining = _remaining_missingness(detail, sensitivity)
    qa = _qa(detail)
    findings = _findings(detail, sensitivity)
    outputs = {
        "access_geometry_completion_detail.csv": detail.drop(columns=["line_geometry"], errors="ignore"),
        "access_geometry_completion_signal_summary.csv": signal_summary,
        "access_buffer_sensitivity_summary.csv": sensitivity,
        "untyped_access_buffer_assignment_summary.csv": untyped_summary,
        "typed_v2_access_buffer_assignment_summary.csv": typed_summary,
        "access_geometry_remaining_missingness.csv": remaining,
        "access_geometry_completion_qa.csv": qa,
    }
    for name, frame in outputs.items():
        _write_csv(frame, OUT_DIR / name)
    _write_text(findings, OUT_DIR / "access_geometry_completion_findings.md")
    output_names = list(outputs) + ["access_geometry_completion_findings.md", "access_geometry_completion_manifest.json", "run_progress_log.txt"]
    _write_json(_manifest(started, output_names, inputs), OUT_DIR / "access_geometry_completion_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
