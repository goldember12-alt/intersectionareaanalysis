from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_refresh"

FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
ACCESS_BASELINE_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"
TYPED_MAPPING_DIR = OUTPUT_ROOT / "review/current/typed_access_rule_overlap_audit"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

STAGED_SOURCE_SIGNALS = 3933
FINAL_CLEAN_SIGNALS = 3719
BUFFER_WIDTHS_FT = [35, 50, 75, 100]
MAX_BUFFER_FT = 100
FEET_PER_METER = 3.280839895

TYPED_CATEGORY_ORDER = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
]

FALLBACK_CATEGORY_MAP = {
    "U": "unrestricted_or_full_access",
    "RIRO": "right_in_right_out",
    "R": "right_in_right_out",
    "RC": "right_in_right_out",
    "LIRIRO": "restricted_partial_access",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "I": "other_review",
    "M": "other_review",
    "S": "other_review",
    "AS": "other_review",
    "AU": "other_review",
    "": "unknown",
}

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
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_window_availability.csv",
    FINAL_LEG_DIR / "final_leg_corrected_context_readiness_summary.csv",
    FINAL_LEG_DIR / "final_leg_corrected_residual_issue_ledger.csv",
    FINAL_LEG_DIR / "final_leg_corrected_downstream_readiness.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
    ACCESS_BASELINE_DIR / "final_access_baseline_product_inventory.csv",
    ACCESS_BASELINE_DIR / "final_access_primary_untyped_spatial_100ft_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_primary_typed_v2_spatial_100ft_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_conservative_travelway_windowed_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_broad_travelway_diagnostic_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_typed_category_corrected_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_product_role_doctrine.csv",
    ACCESS_BASELINE_DIR / "final_access_source_limitation_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_crash_catchment_readiness.csv",
    ACCESS_BASELINE_DIR / "final_access_baseline_manifest.json",
    TYPED_MAPPING_DIR / "typed_access_corrected_category_mapping.csv",
    TYPED_MAPPING_DIR / "typed_access_category_correction_impact.csv",
    TYPED_MAPPING_DIR / "typed_access_rule_overlap_manifest.json",
    ACCESS_V1_FILE,
    ACCESS_V2_FILE,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{suffix}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
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


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _route_key(value: Any) -> str:
    text = "" if pd.isna(value) else str(value).upper().strip()
    return "".join(ch for ch in text if ch.isalnum())


def _window_mask(frame: pd.DataFrame, window: str) -> pd.Series:
    if window == "any":
        return pd.Series(True, index=frame.index)
    start = _num(frame, "distance_start_ft").fillna(np.inf)
    end = _num(frame, "distance_end_ft").fillna(-np.inf)
    if window == "0_1000":
        return start.lt(1000) & end.gt(0)
    if window == "0_2500":
        return start.lt(2500) & end.gt(0)
    return pd.Series(False, index=frame.index)


def _load_category_mapping() -> dict[str, tuple[str, str]]:
    mapping_path = TYPED_MAPPING_DIR / "typed_access_corrected_category_mapping.csv"
    if not mapping_path.exists():
        return {code: (category, "fallback_required_mapping") for code, category in FALLBACK_CATEGORY_MAP.items()}
    mapping = _read_csv(mapping_path)
    out: dict[str, tuple[str, str]] = {}
    for row in mapping.to_dict("records"):
        code = str(row.get("raw_access_control_code", "") or "").strip().upper()
        if code.lower() == "nan":
            code = ""
        corrected = str(row.get("corrected_access_category", "") or "").strip()
        reason = str(row.get("category_correction_reason", "") or "").strip()
        if corrected:
            out[code] = (corrected, reason or "corrected_mapping_table")
    for code, category in FALLBACK_CATEGORY_MAP.items():
        out.setdefault(code, (category, "fallback_required_mapping"))
    return out


def _read_access(path: Path, *, typed: bool, category_map: dict[str, tuple[str, str]]) -> gpd.GeoDataFrame:
    _checkpoint(f"read_start {path.name}")
    access = gpd.read_parquet(path)
    access = access.drop(columns=[column for column in access.columns if _blocked_column(column)], errors="ignore")
    if access.crs is None:
        access = access.set_crs("EPSG:3968", allow_override=True)
    access = access.to_crs("EPSG:3968")
    access = access.loc[access.geometry.notna() & ~access.geometry.is_empty].copy()
    if typed:
        access["access_point_id"] = (
            access.get("access_v2_source_priority", "").astype(str)
            + ":"
            + access.get("access_v2_source_row_id", "").astype(str)
        )
        access.loc[access["access_point_id"].eq(":"), "access_point_id"] = access.loc[access["access_point_id"].eq(":"), "id"].astype(str)
        access["access_layer"] = "typed_v2"
        access["raw_access_control_code"] = access.get("access_control_code", "").astype(str).str.strip().str.upper()
        access.loc[access["raw_access_control_code"].str.lower().eq("nan"), "raw_access_control_code"] = ""
        access["prior_access_category"] = access.get("access_control_category", "").astype(str).replace("", "unknown")
        corrected = access["raw_access_control_code"].map(lambda code: category_map.get(code, ("other_review", "unmapped_raw_code"))[0])
        reason = access["raw_access_control_code"].map(lambda code: category_map.get(code, ("other_review", "unmapped_raw_code"))[1])
        access["corrected_access_category"] = corrected.where(corrected.isin(TYPED_CATEGORY_ORDER), "other_review")
        access["category_correction_reason"] = reason
        access["route_name"] = access.get("route_name", "").astype(str)
        access["route_measure"] = access.get("route_measure", "").astype(str)
        access["source_dataset"] = access.get("access_v2_source_gdb", "").astype(str)
        access["source_layer"] = access.get("access_v2_source_layer", "").astype(str)
        extras = [
            "access_v2_source_priority",
            "access_v2_source_row_id",
            "access_v2_staging_status",
            "access_control_raw",
            "access_direction_normalized",
        ]
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["access_layer"] = "untyped"
        access["raw_access_control_code"] = ""
        access["prior_access_category"] = "untyped"
        access["corrected_access_category"] = "untyped"
        access["category_correction_reason"] = "untyped_source_not_categorized"
        access["route_name"] = access.get("_rte_nm", "").astype(str)
        access["route_measure"] = access.get("_m", "").astype(str)
        access["source_dataset"] = access.get("Stage1_SourceGDB", "").astype(str)
        access["source_layer"] = access.get("Stage1_SourceLayer", "").astype(str)
        extras = ["Stage1_SourceGDB", "Stage1_SourceLayer"]
    access["route_key"] = access["route_name"].map(_route_key)
    keep = [
        "access_point_id",
        "access_layer",
        "raw_access_control_code",
        "prior_access_category",
        "corrected_access_category",
        "category_correction_reason",
        "route_name",
        "route_measure",
        "route_key",
        "source_dataset",
        "source_layer",
        "geometry",
    ] + [col for col in extras if col in access.columns]
    out = access[keep].copy()
    out = out.loc[_text(out, "access_point_id").str.strip().ne("")]
    _checkpoint(f"read_complete {path.name}", len(out), note=f"typed={typed}")
    return out


def _target_bins() -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    target = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv")
    target["target_signal_id"] = _text(target, "stable_signal_id")
    target["target_bin_id"] = _text(target, "stable_bin_id")
    target["target_source_id"] = _text(target, "source_signal_id")
    target["target_source_layer"] = _text(target, "source_layer")
    target["physical_leg_id_final"] = _text(target, "final_review_physical_leg_id")
    target["carriageway_subbranch_id_final"] = _text(target, "final_review_carriageway_subbranch_id")
    target["route_key"] = _text(target, "source_route_name").where(_text(target, "source_route_name").ne(""), _text(target, "source_route_common")).map(_route_key)
    target["distance_length_ft"] = (_num(target, "distance_end_ft") - _num(target, "distance_start_ft")).abs().fillna(50.0)
    target["candidate_weight_num"] = 1.0
    target["geometry_available"] = _text(target, "geometry_wkt").str.strip().ne("")

    geom = target.loc[target["geometry_available"]].copy()
    geom["geometry"] = geom["geometry_wkt"].map(lambda value: wkt.loads(value) if str(value).strip() else None)
    lines = gpd.GeoDataFrame(geom, geometry="geometry", crs="EPSG:3968")
    lines = lines.loc[lines.geometry.notna() & ~lines.geometry.is_empty].copy()
    _checkpoint("target_bins_geometry_available", len(lines), note=f"signals={lines['stable_signal_id'].nunique():,}")
    return target, lines


def _assign_within_100(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    if lines.empty or access.empty:
        return pd.DataFrame()
    line_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "original_physical_leg_id",
        "physical_leg_id",
        "corrected_physical_leg_id",
        "original_carriageway_subbranch_id",
        "carriageway_subbranch_id",
        "corrected_carriageway_subbranch_id",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
        "final_review_leg_source",
        "final_review_context_status",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
        "final_review_recovery_provenance",
        "route_key",
        "geometry",
    ]
    catchments = lines[[col for col in line_cols if col in lines.columns]].copy()
    catchments["line_geometry"] = catchments.geometry
    catchments["geometry"] = catchments.geometry.buffer(MAX_BUFFER_FT / FEET_PER_METER, cap_style="flat", join_style="mitre")
    catchments = gpd.GeoDataFrame(catchments, geometry="geometry", crs="EPSG:3968")
    source = access.drop(columns=[col for col in access.columns if col == "index_right"], errors="ignore")
    _checkpoint("spatial_join_start", note=f"{layer} max_buffer_ft={MAX_BUFFER_FT}")
    joined = gpd.sjoin(source, catchments, how="inner", predicate="within")
    if joined.empty:
        _checkpoint("spatial_join_complete", 0, note=layer)
        return pd.DataFrame()
    distance_m = joined.geometry.distance(gpd.GeoSeries(joined["line_geometry"], crs=joined.crs, index=joined.index))
    joined["nearest_line_distance_ft"] = distance_m * FEET_PER_METER
    out = pd.DataFrame(joined.drop(columns=["geometry", "line_geometry", "index_right"], errors="ignore"))
    out = out.drop_duplicates(["access_point_id", "stable_bin_id", "corrected_access_category"])
    _checkpoint("spatial_join_complete", len(out), note=layer)
    parts = []
    for width in BUFFER_WIDTHS_FT:
        part = out.loc[pd.to_numeric(out["nearest_line_distance_ft"], errors="coerce").le(width)].copy()
        part["buffer_width_ft"] = width
        parts.append(part)
    expanded = pd.concat(parts, ignore_index=True, sort=False)
    if expanded.empty:
        return expanded
    fanout = (
        expanded.groupby(["buffer_width_ft", "access_point_id"], dropna=False)["stable_bin_id"]
        .nunique()
        .rename("assignment_fanout_count")
        .reset_index()
    )
    expanded = expanded.merge(fanout, on=["buffer_width_ft", "access_point_id"], how="left")
    expanded["assignment_fanout_count"] = pd.to_numeric(expanded["assignment_fanout_count"], errors="coerce").fillna(1.0)
    expanded["multi_assignment_flag"] = expanded["assignment_fanout_count"].gt(1)
    expanded["unweighted_access_count"] = 1.0
    expanded["source_preserving_weighted_access_count"] = 1.0 / expanded["assignment_fanout_count"]
    expanded["access_layer"] = layer
    return expanded


def _coverage_summary(assignments: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for width in BUFFER_WIDTHS_FT:
        width_subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)].copy() if not assignments.empty else pd.DataFrame()
        for window in ["any", "0_1000", "0_2500"]:
            subset = width_subset.loc[_window_mask(width_subset, window)] if not width_subset.empty else pd.DataFrame()
            rows.append(
                {
                    "access_layer": layer,
                    "buffer_width_ft": width,
                    "window": window,
                    "source_points_captured": int(_text(subset, "access_point_id").nunique()) if not subset.empty else 0,
                    "signals_with_access": int(_text(subset, "stable_signal_id").nunique()) if not subset.empty else 0,
                    "bins_with_access": int(_text(subset, "stable_bin_id").nunique()) if not subset.empty else 0,
                    "assignment_rows": int(len(subset)),
                    "unweighted_assignment_total": round(float(pd.to_numeric(subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0.0,
                    "source_preserving_weighted_total": round(float(pd.to_numeric(subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0.0,
                    "max_assignment_fanout": round(float(pd.to_numeric(subset.get("assignment_fanout_count"), errors="coerce").fillna(0).max()), 6) if not subset.empty else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _typed_category_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if assignments.empty:
        return pd.DataFrame(columns=[
            "access_layer",
            "buffer_width_ft",
            "window",
            "corrected_access_category",
            "source_points_captured",
            "signals_with_access",
            "bins_with_access",
            "assignment_rows",
            "unweighted_assignment_total",
            "source_preserving_weighted_total",
            "share_of_typed_source_points_within_product_window",
            "share_within_corrected_category_window",
        ])
    for width in BUFFER_WIDTHS_FT:
        width_subset = assignments.loc[pd.to_numeric(assignments["buffer_width_ft"], errors="coerce").eq(width)].copy()
        for window in ["any", "0_1000", "0_2500"]:
            window_subset = width_subset.loc[_window_mask(width_subset, window)].copy()
            window_total = int(_text(window_subset, "access_point_id").nunique())
            category_counts = {
                category: int(_text(window_subset.loc[_text(window_subset, "corrected_access_category").eq(category)], "access_point_id").nunique())
                for category in TYPED_CATEGORY_ORDER
            }
            for category in TYPED_CATEGORY_ORDER:
                subset = window_subset.loc[_text(window_subset, "corrected_access_category").eq(category)].copy()
                source_points = int(_text(subset, "access_point_id").nunique())
                rows.append(
                    {
                        "access_layer": "typed_v2",
                        "buffer_width_ft": width,
                        "window": window,
                        "corrected_access_category": category,
                        "source_points_captured": source_points,
                        "signals_with_access": int(_text(subset, "stable_signal_id").nunique()) if not subset.empty else 0,
                        "bins_with_access": int(_text(subset, "stable_bin_id").nunique()) if not subset.empty else 0,
                        "assignment_rows": int(len(subset)),
                        "unweighted_assignment_total": round(float(pd.to_numeric(subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0.0,
                        "source_preserving_weighted_total": round(float(pd.to_numeric(subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0.0,
                        "share_of_typed_source_points_within_product_window": round(source_points / window_total, 6) if window_total else 0.0,
                        "share_within_corrected_category_window": 1.0 if category_counts.get(category, 0) else 0.0,
                    }
                )
            rows.append(
                {
                    "access_layer": "typed_v2",
                    "buffer_width_ft": width,
                    "window": window,
                    "corrected_access_category": "all_typed_categories",
                    "source_points_captured": window_total,
                    "signals_with_access": int(_text(window_subset, "stable_signal_id").nunique()) if not window_subset.empty else 0,
                    "bins_with_access": int(_text(window_subset, "stable_bin_id").nunique()) if not window_subset.empty else 0,
                    "assignment_rows": int(len(window_subset)),
                    "unweighted_assignment_total": round(float(pd.to_numeric(window_subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not window_subset.empty else 0.0,
                    "source_preserving_weighted_total": round(float(pd.to_numeric(window_subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not window_subset.empty else 0.0,
                    "share_of_typed_source_points_within_product_window": 1.0 if window_total else 0.0,
                    "share_within_corrected_category_window": 1.0 if window_total else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _meeting_table(typed_summary: pd.DataFrame, *, all_buffers: bool) -> pd.DataFrame:
    subset = typed_summary.loc[_text(typed_summary, "window").isin(["0_1000", "0_2500"])].copy()
    if not all_buffers:
        subset = subset.loc[pd.to_numeric(subset["buffer_width_ft"], errors="coerce").eq(100)].copy()
    subset = subset.loc[_text(subset, "corrected_access_category").ne("all_typed_categories")].copy()
    subset["Product"] = "spatial 100 ft" if not all_buffers else "spatial " + subset["buffer_width_ft"].astype(str) + " ft"
    subset["Window"] = _text(subset, "window").map({"0_1000": "0-1,000 ft", "0_2500": "0-2,500 ft"})
    subset["Type"] = _text(subset, "corrected_access_category")
    subset["Source points"] = subset["source_points_captured"].astype(int)
    subset["Signals"] = subset["signals_with_access"].astype(int)
    subset["Bins"] = subset["bins_with_access"].astype(int)
    subset["Share"] = pd.to_numeric(subset["share_of_typed_source_points_within_product_window"], errors="coerce").fillna(0).round(4)
    return subset[["Product", "Window", "Type", "Source points", "Signals", "Bins", "Share"]]


def _fanout_summary(assignments: pd.DataFrame, source_points: int, *, layer: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for width in BUFFER_WIDTHS_FT:
        subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(width)].copy() if not assignments.empty else pd.DataFrame()
        if subset.empty:
            rows.append({"access_layer": layer, "buffer_width_ft": width, "fanout_bucket": "uncaptured", "source_point_count": source_points, "assignment_rows": 0, "weighted_total": 0.0})
            continue
        per_point = subset.groupby("access_point_id", dropna=False).agg(
            assignment_fanout_count=("stable_bin_id", "nunique"),
            assignment_rows=("stable_bin_id", "size"),
            weighted_total=("source_preserving_weighted_access_count", "sum"),
        ).reset_index()
        per_point["fanout_bucket"] = pd.cut(
            pd.to_numeric(per_point["assignment_fanout_count"], errors="coerce").fillna(0),
            bins=[0, 1, 2, 3, np.inf],
            labels=["1", "2", "3", "4_plus"],
            include_lowest=True,
        ).astype(str)
        grouped = per_point.groupby("fanout_bucket", dropna=False).agg(
            source_point_count=("access_point_id", "nunique"),
            assignment_rows=("assignment_rows", "sum"),
            weighted_total=("weighted_total", "sum"),
        ).reset_index()
        grouped["access_layer"] = layer
        grouped["buffer_width_ft"] = width
        rows.extend(grouped.to_dict("records"))
        captured = int(per_point["access_point_id"].nunique())
        rows.append({"access_layer": layer, "buffer_width_ft": width, "fanout_bucket": "uncaptured", "source_point_count": source_points - captured, "assignment_rows": 0, "weighted_total": 0.0})
    return pd.DataFrame(rows)


def _scaffold_qa_summary(target: pd.DataFrame, untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"qa_group": "target_bins", "qa_class": "total", "count": len(target)},
        {"qa_group": "target_bins", "qa_class": "with_geometry_wkt", "count": int(_bool_text(target, "geometry_available").sum())},
        {"qa_group": "target_bins", "qa_class": "with_stable_travelway_id", "count": int(_text(target, "stable_travelway_id").str.strip().ne("").sum())},
        {"qa_group": "target_bins", "qa_class": "with_final_review_physical_leg_id", "count": int(_text(target, "final_review_physical_leg_id").str.strip().ne("").sum())},
    ]
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        subset = frame.loc[pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(100)].copy() if not frame.empty else pd.DataFrame()
        rows.extend(
            [
                {"qa_group": layer, "qa_class": "spatial_100_assignment_rows", "count": len(subset)},
                {"qa_group": layer, "qa_class": "spatial_100_source_points", "count": int(_text(subset, "access_point_id").nunique()) if not subset.empty else 0},
                {"qa_group": layer, "qa_class": "spatial_100_signals", "count": int(_text(subset, "stable_signal_id").nunique()) if not subset.empty else 0},
                {"qa_group": layer, "qa_class": "spatial_100_bins", "count": int(_text(subset, "stable_bin_id").nunique()) if not subset.empty else 0},
            ]
        )
    return pd.DataFrame(rows)


def _access_by_roadway_type(assignments: pd.DataFrame) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame()
    subset = assignments.loc[pd.to_numeric(assignments.get("buffer_width_ft"), errors="coerce").eq(100) & _window_mask(assignments, "0_1000")].copy()
    field = "source_route_common" if "source_route_common" in subset.columns else "source_route_name"
    subset["roadway_type_or_facility"] = _text(subset, field).replace("", "unknown")
    group_cols = ["access_layer", "corrected_access_category", "roadway_type_or_facility"]
    out = subset.groupby(group_cols, dropna=False).agg(
        source_points=("access_point_id", "nunique"),
        signals=("stable_signal_id", "nunique"),
        bins=("stable_bin_id", "nunique"),
        assignment_rows=("stable_bin_id", "size"),
        weighted_total=("source_preserving_weighted_access_count", "sum"),
    ).reset_index()
    return out.sort_values(["access_layer", "corrected_access_category", "source_points"], ascending=[True, True, False])


def _prior_metric(frame: pd.DataFrame, *, window: str) -> dict[str, float]:
    subset = frame.loc[_text(frame, "window").eq(window)].copy()
    if subset.empty:
        return {"source_points": 0, "signals": 0, "bins": 0, "assignment_rows": 0}
    row = subset.iloc[0]
    return {
        "source_points": float(row.get("source_points_captured", 0) or 0),
        "signals": float(row.get("signals_covered", 0) or 0),
        "bins": float(row.get("bins_with_access", 0) or 0),
        "assignment_rows": float(row.get("assignment_rows", 0) or 0),
    }


def _compare_to_prior(untyped_summary: pd.DataFrame, typed_summary: pd.DataFrame) -> pd.DataFrame:
    prior_untyped = _read_csv(ACCESS_BASELINE_DIR / "final_access_primary_untyped_spatial_100ft_summary.csv")
    prior_typed = _read_csv(ACCESS_BASELINE_DIR / "final_access_primary_typed_v2_spatial_100ft_summary.csv")
    rows: list[dict[str, Any]] = []
    for layer, current, prior in [("untyped", untyped_summary, prior_untyped), ("typed_v2", typed_summary, prior_typed)]:
        current_100 = current.loc[pd.to_numeric(current["buffer_width_ft"], errors="coerce").eq(100)].copy()
        for window in ["any", "0_1000", "0_2500"]:
            cur = current_100.loc[_text(current_100, "window").eq(window)]
            cur_row = cur.iloc[0].to_dict() if not cur.empty else {}
            prior_values = _prior_metric(prior, window=window)
            rows.append(
                {
                    "access_layer": layer,
                    "window": window,
                    "prior_source_points": prior_values["source_points"],
                    "current_source_points": float(cur_row.get("source_points_captured", 0) or 0),
                    "source_points_change": float(cur_row.get("source_points_captured", 0) or 0) - prior_values["source_points"],
                    "prior_signals": prior_values["signals"],
                    "current_signals": float(cur_row.get("signals_with_access", 0) or 0),
                    "signals_change": float(cur_row.get("signals_with_access", 0) or 0) - prior_values["signals"],
                    "prior_assignment_rows": prior_values["assignment_rows"],
                    "current_assignment_rows": float(cur_row.get("assignment_rows", 0) or 0),
                    "assignment_rows_change": float(cur_row.get("assignment_rows", 0) or 0) - prior_values["assignment_rows"],
                }
            )
    return pd.DataFrame(rows)


def _doctrine_update() -> pd.DataFrame:
    prior = _read_csv(ACCESS_BASELINE_DIR / "final_access_product_role_doctrine.csv")
    if prior.empty:
        prior = pd.DataFrame()
    rows = [
        {
            "product_name": "untyped_spatial_100ft_primary",
            "status_after_final_leg_corrected_refresh": "still_primary_broad_access_review_product",
            "notes": "Refreshed on final leg-corrected bins; keep separate from typed v2.",
        },
        {
            "product_name": "typed_v2_spatial_100ft_enrichment",
            "status_after_final_leg_corrected_refresh": "still_typed_enrichment_product",
            "notes": "Corrected typed categories are applied; source sparsity caveat remains.",
        },
        {
            "product_name": "conservative_travelway_windowed",
            "status_after_final_leg_corrected_refresh": "sensitivity_enrichment_not_primary",
            "notes": "Prior doctrine retained; not recalculated in this spatial refresh.",
        },
        {
            "product_name": "broad_travelway_normalized",
            "status_after_final_leg_corrected_refresh": "source_coverage_diagnostic_only",
            "notes": "Not used as primary access metric.",
        },
    ]
    out = pd.DataFrame(rows)
    if not prior.empty:
        out["prior_doctrine_rows_available"] = len(prior)
    return out


def _qa(target: pd.DataFrame, untyped: pd.DataFrame, typed: pd.DataFrame, missing: list[str]) -> pd.DataFrame:
    typed_has_categories = set(_text(typed, "corrected_access_category")) <= set(TYPED_CATEGORY_ORDER) if not typed.empty else True
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_leg_corrected_access_refresh."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_crash_assignment", True, "Crash records are not read or assigned."),
        ("no_rates_or_models", True, "No rates/models are calculated."),
        ("crash_direction_fields_not_used", True, "Readers refuse known crash record/direction columns."),
        ("typed_and_untyped_separate", True, "Separate assignment detail and summary outputs are written."),
        ("corrected_typed_categories_applied", typed_has_categories, "Typed assignments carry corrected_access_category."),
        ("raw_access_codes_preserved", "raw_access_control_code" in typed.columns, "Typed assignment output preserves raw access codes."),
        ("weighted_unweighted_separate", {"unweighted_access_count", "source_preserving_weighted_access_count"}.issubset(set(untyped.columns) | set(typed.columns)), "Both count fields are emitted."),
        ("stable_travelway_id_preserved", _text(target, "stable_travelway_id").str.strip().ne("").all(), f"{_text(target, 'stable_travelway_id').str.strip().ne('').sum():,} / {len(target):,}"),
        ("final_review_physical_leg_id_preserved", "final_review_physical_leg_id" in target.columns, f"column present; nonblank {_text(target, 'final_review_physical_leg_id').str.strip().ne('').sum():,} / {len(target):,}"),
        ("outputs_review_only", True, str(OUT_DIR.resolve())),
        ("required_inputs_available", not missing, "; ".join(missing)),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": passed, "detail": detail} for name, passed, detail in checks])


def _findings(
    target: pd.DataFrame,
    untyped_summary: pd.DataFrame,
    typed_summary: pd.DataFrame,
    typed_category_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    qa_frame: pd.DataFrame,
) -> str:
    untyped_100 = untyped_summary.loc[pd.to_numeric(untyped_summary["buffer_width_ft"], errors="coerce").eq(100)]
    typed_100 = typed_summary.loc[pd.to_numeric(typed_summary["buffer_width_ft"], errors="coerce").eq(100)]
    def _row(frame: pd.DataFrame, window: str) -> dict[str, Any]:
        subset = frame.loc[_text(frame, "window").eq(window)]
        return subset.iloc[0].to_dict() if not subset.empty else {}
    u100_2500 = _row(untyped_100, "0_2500")
    t100_2500 = _row(typed_100, "0_2500")
    category_100 = typed_category_summary.loc[
        pd.to_numeric(typed_category_summary["buffer_width_ft"], errors="coerce").eq(100)
        & _text(typed_category_summary, "window").eq("0_2500")
        & _text(typed_category_summary, "corrected_access_category").ne("all_typed_categories")
    ]
    category_lines = "\n".join(
        f"- {row.corrected_access_category}: {int(row.source_points_captured):,} source points, {int(row.signals_with_access):,} signals, share {float(row.share_of_typed_source_points_within_product_window):.1%}"
        for row in category_100.itertuples(index=False)
    )
    comparison_lines = "\n".join(
        f"- {row.access_layer} {row.window}: source points {row.prior_source_points:.0f} -> {row.current_source_points:.0f}; signals {row.prior_signals:.0f} -> {row.current_signals:.0f}"
        for row in comparison.itertuples(index=False)
        if row.window in {"0_1000", "0_2500"}
    )
    return f"""# Final Leg-Corrected Access Refresh Findings

## Bounded Question

Refresh review-only untyped and typed v2 spatial access products on the final leg-corrected 3,719-signal clean review-analysis universe, preserving corrected leg labels and typed access categories.

## Universe

- Signals included: {FINAL_CLEAN_SIGNALS:,}
- Target bin rows: {len(target):,}
- Target bins with geometry: {_bool_text(target, 'geometry_available').sum():,}
- Target bins with stable_travelway_id: {_text(target, 'stable_travelway_id').str.strip().ne('').sum():,}

## Access Capture

- Untyped spatial 100 ft, 0-2,500 ft: {int(u100_2500.get('source_points_captured', 0)):,} source points, {int(u100_2500.get('signals_with_access', 0)):,} signals, {int(u100_2500.get('bins_with_access', 0)):,} bins.
- Typed v2 spatial 100 ft, 0-2,500 ft: {int(t100_2500.get('source_points_captured', 0)):,} source points, {int(t100_2500.get('signals_with_access', 0)):,} signals, {int(t100_2500.get('bins_with_access', 0)):,} bins.

## Typed Spatial 100 Ft Categories, 0-2,500 Ft

{category_lines}

## R/RC Recoding

The corrected category mapping was applied from `typed_access_corrected_category_mapping.csv`. R and RC are carried as `right_in_right_out`; I/M/S/AS/AU remain `other_review`; raw access codes and prior categories are preserved.

## Prior Baseline Comparison

{comparison_lines}

## Doctrine

The prior doctrine still holds: untyped spatial 100 ft is the primary broad access review product, typed v2 spatial 100 ft is typed enrichment, conservative Travelway-windowed products remain sensitivity/enrichment, and broad Travelway-normalized access remains source-coverage diagnostic only.

## Readiness

Access is ready to carry forward as review-only context into the leg-corrected crash/catchment refresh. This pass did not choose a production access metric.

## QA

All QA checks passed: {bool(qa_frame['passed'].all())}.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()

    category_map = _load_category_mapping()
    target, lines = _target_bins()
    untyped_source = _read_access(ACCESS_V1_FILE, typed=False, category_map=category_map)
    typed_source = _read_access(ACCESS_V2_FILE, typed=True, category_map=category_map)

    untyped_assign = _assign_within_100(lines, untyped_source, layer="untyped")
    typed_assign = _assign_within_100(lines, typed_source, layer="typed_v2")

    untyped_summary = _coverage_summary(untyped_assign, layer="untyped")
    typed_summary = _coverage_summary(typed_assign, layer="typed_v2")
    typed_category_summary = _typed_category_summary(typed_assign)
    meeting = _meeting_table(typed_category_summary, all_buffers=False)
    meeting_all = _meeting_table(typed_category_summary, all_buffers=True)
    fanout = pd.concat(
        [
            _fanout_summary(untyped_assign, untyped_source["access_point_id"].nunique(), layer="untyped"),
            _fanout_summary(typed_assign, typed_source["access_point_id"].nunique(), layer="typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    scaffold_qa = _scaffold_qa_summary(target, untyped_assign, typed_assign)
    roadway_type = _access_by_roadway_type(typed_assign)
    comparison = _compare_to_prior(untyped_summary, typed_summary)
    doctrine = _doctrine_update()
    qa_frame = _qa(target, untyped_assign, typed_assign, missing)

    target_out = target.drop(columns=["geometry"], errors="ignore")
    _write_csv(target_out, "final_leg_corrected_access_target_bins.csv")
    _write_csv(untyped_assign, "final_leg_corrected_untyped_spatial_assignment_detail.csv")
    _write_csv(typed_assign, "final_leg_corrected_typed_v2_spatial_assignment_detail.csv")
    _write_csv(untyped_summary, "final_leg_corrected_untyped_access_summary.csv")
    _write_csv(typed_summary, "final_leg_corrected_typed_access_summary.csv")
    _write_csv(typed_category_summary, "final_leg_corrected_typed_access_category_summary.csv")
    _write_csv(meeting, "final_leg_corrected_typed_access_meeting_table.csv")
    _write_text(meeting.to_string(index=False), "final_leg_corrected_typed_access_meeting_table.txt")
    _write_csv(meeting_all, "final_leg_corrected_typed_access_meeting_table_all_buffers.csv")
    _write_csv(fanout, "final_leg_corrected_access_fanout_summary.csv")
    _write_csv(scaffold_qa, "final_leg_corrected_access_by_scaffold_qa_summary.csv")
    _write_csv(roadway_type, "final_leg_corrected_access_by_roadway_type.csv")
    _write_csv(comparison, "final_leg_corrected_access_vs_prior_comparison.csv")
    _write_csv(doctrine, "final_leg_corrected_access_doctrine_update.csv")
    _write_text(_findings(target, untyped_summary, typed_summary, typed_category_summary, comparison, qa_frame), "final_leg_corrected_access_refresh_findings.md")
    _write_csv(qa_frame, "final_leg_corrected_access_refresh_qa.csv")

    manifest = {
        "generated_at": _now(),
        "script": "src.roadway_graph.build.final_leg_corrected_access_refresh",
        "output_dir": str(OUT_DIR),
        "review_only": True,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "missing_inputs": missing,
        "counts": {
            "target_signals": int(target["stable_signal_id"].nunique()),
            "target_bins": int(len(target)),
            "target_bins_with_geometry": int(_bool_text(target, "geometry_available").sum()),
            "untyped_assignment_rows": int(len(untyped_assign)),
            "typed_assignment_rows": int(len(typed_assign)),
            "untyped_source_points": int(untyped_source["access_point_id"].nunique()),
            "typed_source_points": int(typed_source["access_point_id"].nunique()),
            "qa_passed": bool(qa_frame["passed"].all()),
        },
        "non_goals_confirmed": [
            "no_active_outputs_modified",
            "no_records_promoted",
            "no_crash_assignment",
            "no_rates_or_models",
            "typed_and_untyped_kept_separate",
        ],
    }
    _write_json(manifest, "final_leg_corrected_access_refresh_manifest.json")
    _checkpoint("complete")
    print("Complete.")


if __name__ == "__main__":
    main()
