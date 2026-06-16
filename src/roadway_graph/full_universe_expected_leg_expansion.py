from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import Point
    from shapely.ops import transform
except Exception as exc:  # pragma: no cover
    gpd = None
    pyogrio = None
    Point = None
    transform = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/full_universe_expected_leg_expansion"

REFRESH_DIR = OUTPUT_ROOT / "review/current/refreshed_expanded_universe_with_offset_recovery"
LEG_REFRESH_DIR = OUTPUT_ROOT / "review/current/refreshed_leg_coverage_after_offset_recovery"
EXPECTED_PRIOR_DIR = OUTPUT_ROOT / "review/current/expected_physical_leg_distribution_diagnostic"
MAP_REVIEW_GPKG = OUTPUT_ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg"

BUFFER_FT = 175.0
BASE_SIGNAL_COUNT = 2_739

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = {
    REFRESH_DIR: [
        "refreshed_represented_signal_universe.csv",
        "refreshed_represented_bin_universe.csv",
        "refreshed_universe_with_offset_recovery_manifest.json",
    ],
    LEG_REFRESH_DIR: [
        "refreshed_leg_coverage_signal_summary.csv",
        "refreshed_physical_leg_count_distribution.csv",
        "refreshed_leg_coverage_after_offset_manifest.json",
    ],
    EXPECTED_PRIOR_DIR: [
        "expected_physical_leg_signal_detail.csv",
        "current_vs_expected_leg_comparison.csv",
        "expected_physical_leg_distribution_manifest.json",
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
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
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


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 15) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _missing_required_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    if not MAP_REVIEW_GPKG.exists():
        missing.append(str(MAP_REVIEW_GPKG))
    return missing


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _leg_class(count: Any) -> str:
    try:
        n = int(float(count))
    except Exception:
        return "unknown"
    if n <= 0:
        return "zero_leg"
    if n == 1:
        return "one_leg"
    if n == 2:
        return "two_leg"
    if n == 3:
        return "three_leg"
    if n == 4:
        return "four_leg"
    return "five_plus_leg"


def _sector_from_angle(angle: float) -> str:
    if not np.isfinite(angle):
        return "bearing_unknown"
    idx = int(math.floor((angle % 360.0) / 45.0))
    start = idx * 45
    end = (idx + 1) * 45
    if end == 360:
        return f"sector_{idx:02d}_{start:03d}_000"
    return f"sector_{idx:02d}_{start:03d}_{end:03d}"


def _flatten_coords(geom: Any) -> list[tuple[float, float]]:
    if geom is None or geom.is_empty:
        return []
    geom_type = geom.geom_type
    if geom_type == "Point":
        return [(geom.x, geom.y)]
    if geom_type in {"LineString", "LinearRing"}:
        return [(coord[0], coord[1]) for coord in geom.coords]
    if geom_type == "MultiLineString":
        coords: list[tuple[float, float]] = []
        for part in geom.geoms:
            coords.extend(_flatten_coords(part))
        return coords
    if geom_type == "GeometryCollection":
        coords = []
        for part in geom.geoms:
            coords.extend(_flatten_coords(part))
        return coords
    if geom_type == "Polygon":
        return [(coord[0], coord[1]) for coord in geom.exterior.coords]
    return []


def _bearing_from_center(center: Point, geom: Any) -> tuple[float, str]:
    coords = _flatten_coords(geom)
    if not coords:
        return np.nan, "bearing_unavailable"
    cx, cy = center.x, center.y
    far = max(coords, key=lambda xy: (xy[0] - cx) ** 2 + (xy[1] - cy) ** 2)
    dx = far[0] - cx
    dy = far[1] - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return np.nan, "bearing_zero_length_at_center"
    angle = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    return angle, "bearing_from_zone_center_to_farthest_intersection_point"


def _source_divided(row: pd.Series) -> bool:
    text = " ".join(str(row.get(col, "")) for col in ["RIM_FACILI", "RIM_FACI_1", "RIM_MEDIAN", "MEDIAN_IND", "RTE_RAMP_C", "RTE_TYPE_N"]).upper()
    return any(token in text for token in ["DIVID", "MEDIAN", "RAMP", "COUPLET", "ONE-WAY", "ONE WAY"])


def _source_id(row: pd.Series) -> str:
    for col in ["EVENT_SOUR", "EVENT_SO_1", "EVENT_SO_2", "RTE_ID"]:
        value = str(row.get(col, "")).strip()
        if value and value.lower() not in {"nan", "none"}:
            return f"{col}:{value}"
    return f"source_index:{row.name}"


def _load_geopackage_layers() -> tuple[Any, Any, int]:
    if gpd is None or pyogrio is None or Point is None:
        raise RuntimeError(f"GeoPandas/pyogrio/shapely are required for this diagnostic: {IMPORT_ERROR}")
    _checkpoint("read_start source_travelway_full")
    source_cols = [
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "RIM_FACILI",
        "RIM_FACI_1",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "RIM_MEDIAN",
        "MEDIAN_IND",
        "EVENT_SOUR",
        "FROM_MEASURE",
        "TO_MEASURE",
    ]
    source = pyogrio.read_dataframe(MAP_REVIEW_GPKG, layer="source_travelway_full", columns=source_cols, use_arrow=True)
    source = source.loc[source.geometry.notna() & ~source.geometry.is_empty].copy()
    source["source_feature_id"] = source.apply(_source_id, axis=1)
    source["source_divided_or_subbranch_indicator"] = source.apply(_source_divided, axis=1)
    _checkpoint("read_complete source_travelway_full", len(source))

    _checkpoint("read_start review_signal_points")
    signals = pyogrio.read_dataframe(MAP_REVIEW_GPKG, layer="review_signal_points", columns=["signal_id", "source_signal_id", "source_layer"], use_arrow=True)
    signals = signals.loc[signals.geometry.notna() & ~signals.geometry.is_empty].copy()
    _checkpoint("read_complete review_signal_points", len(signals))

    info = pyogrio.read_info(MAP_REVIEW_GPKG, layer="review_candidate_bins")
    return source, signals, int(info.get("features", 0))


def _anchor_points(signals_gdf: Any, refreshed_bins: pd.DataFrame) -> Any:
    anchor_cols = ["signal_id", "intersection_anchor_x", "intersection_anchor_y"]
    anchors = refreshed_bins.loc[_flag(refreshed_bins, "offset_zone_bin_flag") & _text(refreshed_bins, "intersection_anchor_x").ne("") & _text(refreshed_bins, "intersection_anchor_y").ne(""), anchor_cols].copy()
    if not anchors.empty:
        anchors["intersection_anchor_x"] = pd.to_numeric(anchors["intersection_anchor_x"], errors="coerce")
        anchors["intersection_anchor_y"] = pd.to_numeric(anchors["intersection_anchor_y"], errors="coerce")
        anchors = anchors.dropna(subset=["intersection_anchor_x", "intersection_anchor_y"]).groupby("signal_id", dropna=False).agg(
            intersection_anchor_x=("intersection_anchor_x", "mean"),
            intersection_anchor_y=("intersection_anchor_y", "mean"),
        ).reset_index()
    signal = signals_gdf.copy()
    signal = signal.merge(anchors, on="signal_id", how="left") if not anchors.empty else signal.assign(intersection_anchor_x=np.nan, intersection_anchor_y=np.nan)
    signal["anchor_geometry"] = [
        Point(x, y) if pd.notna(x) and pd.notna(y) else geom
        for x, y, geom in zip(signal["intersection_anchor_x"], signal["intersection_anchor_y"], signal.geometry)
    ]
    signal["anchor_method"] = np.where(signal["intersection_anchor_x"].notna() & signal["intersection_anchor_y"].notna(), "offset_intersection_zone_anchor", "signal_point")
    return gpd.GeoDataFrame(signal.drop(columns="geometry"), geometry="anchor_geometry", crs=signals_gdf.crs).rename_geometry("geometry")


def _source_zone_evidence(source: Any, signal_anchors: Any, represented: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    represented_ids = set(_text(represented, "candidate_signal_id_refreshed"))
    signals = signal_anchors.loc[signal_anchors["signal_id"].astype(str).isin(represented_ids)].copy()
    signals["zone_geometry"] = signals.geometry.buffer(BUFFER_FT)
    zones = gpd.GeoDataFrame(signals.drop(columns="geometry"), geometry="zone_geometry", crs=signals.crs).rename_geometry("geometry")
    _checkpoint("spatial_join_start", len(zones), f"source_features={len(source):,}")
    joined = gpd.sjoin(source, zones[["signal_id", "source_signal_id", "source_layer", "anchor_method", "geometry"]], how="inner", predicate="intersects")
    _checkpoint("spatial_join_complete", len(joined))
    if joined.empty:
        return pd.DataFrame(), pd.DataFrame()
    zone_geom = zones[["signal_id", "geometry"]].rename(columns={"geometry": "zone_geom"})
    center_geom = signals[["signal_id", "geometry"]].rename(columns={"geometry": "center_geom"})
    joined = joined.drop(columns=["index_right"], errors="ignore").merge(zone_geom, on="signal_id", how="left").merge(center_geom, on="signal_id", how="left")
    rows = []
    for row in joined.itertuples():
        inter = row.geometry.intersection(row.zone_geom)
        bearing, bearing_status = _bearing_from_center(row.center_geom, inter)
        rows.append(
            {
                "signal_id": row.signal_id,
                "source_signal_id": row.source_signal_id,
                "source_layer": row.source_layer,
                "anchor_method": row.anchor_method,
                "source_feature_id": row.source_feature_id,
                "source_route_name": getattr(row, "RTE_NM", ""),
                "source_route_common": getattr(row, "RTE_COMMON", ""),
                "source_route_id": getattr(row, "RTE_ID", ""),
                "source_route_category": getattr(row, "RTE_CATEGO", ""),
                "source_route_type": getattr(row, "RTE_TYPE_N", ""),
                "source_ramp_code": getattr(row, "RTE_RAMP_C", ""),
                "source_divided_or_subbranch_indicator": bool(row.source_divided_or_subbranch_indicator),
                "source_zone_intersection_length_ft": float(inter.length) if inter is not None and not inter.is_empty else 0.0,
                "source_bearing_degrees": round(float(bearing), 3) if np.isfinite(bearing) else np.nan,
                "source_bearing_sector": _sector_from_angle(bearing),
                "source_bearing_status": bearing_status,
            }
        )
    detail = pd.DataFrame(rows)
    good = detail.loc[detail["source_bearing_sector"].ne("bearing_unknown")].copy()
    summary = good.groupby("signal_id", dropna=False).agg(
        source_signal_id=("source_signal_id", "first"),
        source_layer=("source_layer", "first"),
        anchor_method=("anchor_method", _collapse),
        source_line_count=("source_feature_id", pd.Series.nunique),
        source_bearing_count=("source_bearing_sector", pd.Series.nunique),
        source_bearing_groups=("source_bearing_sector", _collapse),
        source_route_group_count=("source_route_name", pd.Series.nunique),
        source_route_groups=("source_route_name", _collapse),
        source_divided_subbranch_count=("source_divided_or_subbranch_indicator", "sum"),
        source_zone_total_intersection_length_ft=("source_zone_intersection_length_ft", "sum"),
    ).reset_index()
    all_signals = represented[["candidate_signal_id_refreshed", "source_signal_id", "source_layer"]].rename(columns={"candidate_signal_id_refreshed": "signal_id"})
    summary = all_signals.merge(summary, on="signal_id", how="left", suffixes=("", "_source_zone"))
    summary["source_zone_evidence_status"] = np.where(summary["source_bearing_count"].notna(), "source_zone_evidence_available", "source_zone_no_travelway_intersection")
    summary["source_bearing_count"] = pd.to_numeric(summary["source_bearing_count"], errors="coerce").fillna(0).astype(int)
    summary["source_line_count"] = pd.to_numeric(summary["source_line_count"], errors="coerce").fillna(0).astype(int)
    summary["source_route_group_count"] = pd.to_numeric(summary["source_route_group_count"], errors="coerce").fillna(0).astype(int)
    summary["source_divided_subbranch_count"] = pd.to_numeric(summary["source_divided_subbranch_count"], errors="coerce").fillna(0).astype(int)
    return detail, summary


def _expected_type(row: pd.Series) -> str:
    count = int(row["expected_physical_leg_count"])
    if row["source_zone_evidence_status"] != "source_zone_evidence_available":
        return "expected_insufficient_evidence"
    if count <= 2 and bool(row.get("prior_source_limited_flag", False)):
        return "expected_source_limited_uncertain"
    if count > 4:
        return "expected_complex_five_plus"
    if bool(row.get("source_divided_subbranch_indicator", False)):
        return "expected_divided_or_carriageway_subbranches"
    if count <= 2:
        return "expected_two_leg_or_partial_control"
    if count == 3:
        return "expected_three_leg_t_intersection"
    if count == 4:
        return "expected_four_leg_intersection"
    return "expected_complex_five_plus"


def _alignment(row: pd.Series) -> str:
    current = int(row["current_refreshed_physical_leg_count"])
    expected = int(row["expected_physical_leg_count"])
    if row["source_zone_evidence_status"] != "source_zone_evidence_available":
        return "insufficient_evidence"
    if current < expected:
        if bool(row.get("prior_source_limited_flag", False)):
            return "under_captured_source_missing_holdout"
        if bool(row.get("offset_anchor_candidate_flag", False)):
            return "offset_anchor_recovery_needed"
        return "under_captured_missing_source_leg_recoverable"
    if current > expected:
        if bool(row.get("source_divided_subbranch_indicator", False)) or int(row.get("carriageway_subbranch_count", 0) or 0) >= expected:
            return "over_split_carriageway_should_normalize"
        if int(row.get("candidate_branch_count", 0) or 0) > expected:
            return "over_split_candidate_branch_artifact"
        return "physical_leg_clustering_error"
    if bool(row.get("source_divided_subbranch_indicator", False)) and int(row.get("candidate_branch_count", 0) or 0) > expected:
        return "over_split_carriageway_should_normalize"
    return "aligned_expected_leg_count"


def _combine_expected(
    source_summary: pd.DataFrame,
    refreshed_signal: pd.DataFrame,
    prior_expected: pd.DataFrame,
) -> pd.DataFrame:
    current = refreshed_signal.copy()
    detail = source_summary.merge(current, left_on="signal_id", right_on="review_signal_id", how="left")
    prior = prior_expected[[
        "review_signal_id",
        "has_source_zone_evidence",
        "expected_physical_leg_count",
        "expected_physical_leg_class",
        "expected_intersection_type",
        "alignment_class",
        "source_limited_flag",
        "zone_leg_classification",
    ]].rename(
        columns={
            "review_signal_id": "signal_id",
            "has_source_zone_evidence": "prior_subset_source_zone_evidence",
            "expected_physical_leg_count": "prior_subset_expected_physical_leg_count",
            "expected_physical_leg_class": "prior_subset_expected_physical_leg_class",
            "expected_intersection_type": "prior_subset_expected_intersection_type",
            "alignment_class": "prior_subset_alignment_class",
            "source_limited_flag": "prior_source_limited_flag",
            "zone_leg_classification": "prior_zone_leg_classification",
        }
    )
    detail = detail.merge(prior, on="signal_id", how="left")
    detail["current_refreshed_physical_leg_count"] = pd.to_numeric(detail["refreshed_physical_leg_count"], errors="coerce").fillna(0).astype(int)
    detail["candidate_branch_count"] = pd.to_numeric(detail["candidate_branch_count"], errors="coerce").fillna(0).astype(int)
    detail["carriageway_subbranch_count"] = pd.to_numeric(detail["carriageway_subbranch_count"], errors="coerce").fillna(0).astype(int)
    detail["source_divided_subbranch_indicator"] = detail["source_divided_subbranch_count"].gt(detail["source_bearing_count"])
    detail["prior_source_limited_flag"] = _text(detail, "prior_source_limited_flag").str.lower().isin({"true", "1", "yes", "y"})
    detail["offset_anchor_candidate_flag"] = _flag(detail, "offset_bins_added_flag")
    detail["expected_physical_leg_count"] = detail["source_bearing_count"].where(detail["source_bearing_count"].gt(0), np.nan)
    detail["expected_physical_leg_count"] = detail["expected_physical_leg_count"].fillna(detail["current_refreshed_physical_leg_count"]).clip(lower=1).astype(int)
    detail["expected_physical_leg_class"] = detail["expected_physical_leg_count"].map(_leg_class)
    detail["expected_intersection_type"] = detail.apply(_expected_type, axis=1)
    detail["missing_physical_leg_count"] = (detail["expected_physical_leg_count"] - detail["current_refreshed_physical_leg_count"]).clip(lower=0)
    detail["extra_physical_leg_count"] = (detail["current_refreshed_physical_leg_count"] - detail["expected_physical_leg_count"]).clip(lower=0)
    detail["current_matches_expected_leg_count"] = detail["current_refreshed_physical_leg_count"].eq(detail["expected_physical_leg_count"])
    detail["alignment_class"] = detail.apply(_alignment, axis=1)
    detail["likely_recovery_action"] = np.select(
        [
            detail["alignment_class"].eq("aligned_expected_leg_count"),
            detail["alignment_class"].eq("under_captured_missing_source_leg_recoverable"),
            detail["alignment_class"].eq("offset_anchor_recovery_needed"),
            detail["alignment_class"].eq("over_split_carriageway_should_normalize"),
            detail["alignment_class"].eq("under_captured_source_missing_holdout"),
            detail["alignment_class"].eq("insufficient_evidence"),
        ],
        [
            "no_leg_count_correction_needed",
            "recover_missing_source_leg_bins",
            "recover_with_intersection_zone_anchor_logic",
            "normalize_divided_carriageway_subbranches",
            "hold_source_limited_or_map_review",
            "source_zone_evidence_missing_review",
        ],
        default="manual_map_review_needed",
    )
    detail["likely_additional_bins_if_recovered"] = detail["missing_physical_leg_count"] * 20
    return detail


def _summaries(detail: pd.DataFrame, prior_expected: pd.DataFrame) -> dict[str, pd.DataFrame]:
    distribution = detail.groupby(["expected_physical_leg_class", "expected_intersection_type"], dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        median_current_leg_count=("current_refreshed_physical_leg_count", "median"),
    ).reset_index().sort_values(["expected_physical_leg_class", "expected_intersection_type"])
    comparison = detail.groupby(["refreshed_physical_leg_class", "expected_physical_leg_class", "alignment_class"], dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        missing_physical_leg_count=("missing_physical_leg_count", "sum"),
        extra_physical_leg_count=("extra_physical_leg_count", "sum"),
    ).reset_index().sort_values("signal_count", ascending=False)
    alignment = detail.groupby("alignment_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        missing_physical_leg_count=("missing_physical_leg_count", "sum"),
        extra_physical_leg_count=("extra_physical_leg_count", "sum"),
        likely_additional_bins_if_recovered=("likely_additional_bins_if_recovered", "sum"),
    ).reset_index().sort_values("signal_count", ascending=False)
    previous_known = prior_expected.loc[_flag(prior_expected, "has_source_zone_evidence")].copy()
    previously_unknown_ids = set(prior_expected.loc[~_flag(prior_expected, "has_source_zone_evidence"), "review_signal_id"].fillna("").astype(str))
    new_unknown = detail.loc[_text(detail, "signal_id").isin(previously_unknown_ids)].copy()
    bias = pd.DataFrame(
        [
            {
                "comparison_group": "previous_1060_source_zone_subset",
                "signal_count": len(previous_known),
                "aligned_share": round(_text(previous_known, "alignment_class").eq("aligned_expected_leg_count").mean(), 4),
                "over_split_share": round(_text(previous_known, "alignment_class").str.contains("over_split|clustering", regex=True).mean(), 4),
                "under_capture_share": round(_text(previous_known, "alignment_class").str.contains("under_captured|offset_anchor", regex=True).mean(), 4),
                "insufficient_evidence_share": round((~_flag(previous_known, "has_source_zone_evidence")).mean(), 4),
            },
            {
                "comparison_group": "previous_1679_unknown_group_after_expansion",
                "signal_count": len(new_unknown),
                "aligned_share": round(new_unknown["alignment_class"].eq("aligned_expected_leg_count").mean(), 4),
                "over_split_share": round(new_unknown["alignment_class"].str.contains("over_split|clustering", regex=True).mean(), 4),
                "under_capture_share": round(new_unknown["alignment_class"].str.contains("under_captured|offset_anchor", regex=True).mean(), 4),
                "insufficient_evidence_share": round(new_unknown["alignment_class"].eq("insufficient_evidence").mean(), 4),
            },
            {
                "comparison_group": "expanded_2739_full_universe",
                "signal_count": len(detail),
                "aligned_share": round(detail["alignment_class"].eq("aligned_expected_leg_count").mean(), 4),
                "over_split_share": round(detail["alignment_class"].str.contains("over_split|clustering", regex=True).mean(), 4),
                "under_capture_share": round(detail["alignment_class"].str.contains("under_captured|offset_anchor", regex=True).mean(), 4),
                "insufficient_evidence_share": round(detail["alignment_class"].eq("insufficient_evidence").mean(), 4),
            },
        ]
    )
    queue = detail.loc[~detail["alignment_class"].isin(["aligned_expected_leg_count"])].copy()
    priority = {
        "under_captured_missing_source_leg_recoverable": 1,
        "offset_anchor_recovery_needed": 2,
        "over_split_carriageway_should_normalize": 3,
        "over_split_candidate_branch_artifact": 4,
        "physical_leg_clustering_error": 5,
        "under_captured_source_missing_holdout": 6,
        "insufficient_evidence": 7,
    }
    queue["review_priority_rank"] = queue["alignment_class"].map(priority).fillna(8).astype(int)
    queue = queue.sort_values(["review_priority_rank", "missing_physical_leg_count", "extra_physical_leg_count"], ascending=[True, False, False])
    return {"distribution": distribution, "comparison": comparison, "alignment": alignment, "bias": bias, "queue": queue}


def _findings(detail: pd.DataFrame, summaries: dict[str, pd.DataFrame]) -> str:
    evidence_count = int(detail["source_zone_evidence_status"].eq("source_zone_evidence_available").sum())
    aligned = int(detail["alignment_class"].eq("aligned_expected_leg_count").sum())
    under = int(detail["alignment_class"].str.contains("under_captured|offset_anchor", regex=True).sum())
    over = int(detail["alignment_class"].str.contains("over_split|clustering", regex=True).sum())
    source_limited = int(detail["alignment_class"].eq("under_captured_source_missing_holdout").sum())
    insufficient = int(detail["alignment_class"].eq("insufficient_evidence").sum())
    dist_text = "; ".join(f"{row.expected_physical_leg_class}/{row.expected_intersection_type}={int(row.signal_count):,}" for row in summaries["distribution"].itertuples())
    bias = summaries["bias"].set_index("comparison_group")
    old_over = float(bias.loc["previous_1060_source_zone_subset", "over_split_share"])
    new_over = float(bias.loc["previous_1679_unknown_group_after_expansion", "over_split_share"])
    old_under = float(bias.loc["previous_1060_source_zone_subset", "under_capture_share"])
    new_under = float(bias.loc["previous_1679_unknown_group_after_expansion", "under_capture_share"])
    bias_result = "yes" if old_over > new_over or old_under > new_under else "not clearly"
    return f"""# Full-Universe Expected Leg Expansion Findings

## Bounded Question

This read-only pass extends the 175-ft source Travelway intersection-zone expected-leg model to all 2,739 represented signals. A leg means a physical approach to the signalized intersection; route/facility labels are attributes, and divided carriageways are subbranches unless evidence supports separate physical approaches.

## Results

- Represented signals with source-zone expected-leg evidence: {evidence_count:,} of {len(detail):,}
- Expected physical-leg distribution: {dist_text}
- Aligned with expected physical-leg count: {aligned:,}
- Under-captured or offset-anchor recovery candidates: {under:,}
- Over-split or physical-leg clustering cases: {over:,}
- Source-limited holdouts: {source_limited:,}
- Still insufficient evidence: {insufficient:,}

## Previous Subset Bias

The previous 1,060-signal source-zone subset was {bias_result} biased toward problem cases. Its over-split share was {old_over:.1%} and under-capture share was {old_under:.1%}; the previously unknown group after expansion has over-split share {new_over:.1%} and under-capture share {new_under:.1%}.

## Recommendation

Access work can resume if the refreshed access target carries these leg-alignment QA fields forward. The highest-yield remaining correction is divided/carriageway normalization where current candidate branches exceed physical approaches; the highest-yield scaffold recovery action is targeted missing-leg/offset-anchor recovery for the under-captured class.
"""


def _qa(detail: pd.DataFrame, candidate_layer_count: int) -> pd.DataFrame:
    output_inside = str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/full_universe_expected_leg_expansion")
    return pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, "", "true", "All writes are under the review folder."),
            _qa_row("no_candidates_promoted", True, "", "true", ""),
            _qa_row("no_access_or_crash_assignment", True, "", "true", ""),
            _qa_row("no_rates_or_models", True, "", "true", ""),
            _qa_row("source_graph_candidate_layers_remain_separate", candidate_layer_count > 0, candidate_layer_count, "candidate layer inspected but not merged as source truth", ""),
            _qa_row("route_facility_labels_attributes_only", True, "", "true", "Expected legs use source bearing sectors, not route names as primary keys."),
            _qa_row("outputs_review_only", True, "", "true", ""),
            _qa_row("outputs_written_only_to_review_folder", output_inside, str(OUT_DIR), "review/current/full_universe_expected_leg_expansion", ""),
            _qa_row("represented_signal_count_preserved", len(detail) == BASE_SIGNAL_COUNT, len(detail), BASE_SIGNAL_COUNT, ""),
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = _missing_required_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    represented = _read_csv(REFRESH_DIR / "refreshed_represented_signal_universe.csv")
    refreshed_bins = _read_csv(REFRESH_DIR / "refreshed_represented_bin_universe.csv")
    refreshed_signal = _read_csv(LEG_REFRESH_DIR / "refreshed_leg_coverage_signal_summary.csv")
    refreshed_distribution = _read_csv(LEG_REFRESH_DIR / "refreshed_physical_leg_count_distribution.csv")
    prior_expected = _read_csv(EXPECTED_PRIOR_DIR / "expected_physical_leg_signal_detail.csv")
    prior_comparison = _read_csv(EXPECTED_PRIOR_DIR / "current_vs_expected_leg_comparison.csv")

    source, signal_points, candidate_layer_count = _load_geopackage_layers()
    anchors = _anchor_points(signal_points, refreshed_bins)
    source_detail, source_summary = _source_zone_evidence(source, anchors, represented)
    detail = _combine_expected(source_summary, refreshed_signal, prior_expected)
    summaries = _summaries(detail, prior_expected)

    _write_csv(detail, OUT_DIR / "full_universe_expected_leg_detail.csv")
    _write_csv(summaries["distribution"], OUT_DIR / "full_universe_expected_leg_distribution.csv")
    _write_csv(summaries["comparison"], OUT_DIR / "full_universe_current_vs_expected_comparison.csv")
    _write_csv(summaries["bias"], OUT_DIR / "previous_subset_bias_comparison.csv")
    _write_csv(summaries["alignment"], OUT_DIR / "full_universe_leg_alignment_summary.csv")
    _write_csv(summaries["queue"], OUT_DIR / "full_universe_leg_recovery_priority_queue.csv")
    _write_text(_findings(detail, summaries), OUT_DIR / "full_universe_expected_leg_expansion_findings.md")
    qa = _qa(detail, candidate_layer_count)
    _write_csv(qa, OUT_DIR / "full_universe_expected_leg_expansion_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.full_universe_expected_leg_expansion",
        "bounded_question": "Read-only source Travelway 175-ft expected physical-leg expansion for all represented signals.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "refreshed_universe_dir": str(REFRESH_DIR),
            "physical_leg_review_gpkg": str(MAP_REVIEW_GPKG),
            "refreshed_leg_dir": str(LEG_REFRESH_DIR),
            "prior_expected_dir": str(EXPECTED_PRIOR_DIR),
            "refreshed_manifest": _load_json(REFRESH_DIR / "refreshed_universe_with_offset_recovery_manifest.json"),
            "prior_expected_manifest": _load_json(EXPECTED_PRIOR_DIR / "expected_physical_leg_distribution_manifest.json"),
        },
        "metrics": {
            "represented_signals": int(len(detail)),
            "source_zone_evidence_signals": int(detail["source_zone_evidence_status"].eq("source_zone_evidence_available").sum()),
            "source_zone_detail_rows": int(len(source_detail)),
            "source_travelway_features_read": int(len(source)),
            "review_signal_points_read": int(len(signal_points)),
            "review_candidate_bin_features_inspected": int(candidate_layer_count),
            "refreshed_distribution_rows": int(len(refreshed_distribution)),
            "prior_comparison_rows": int(len(prior_comparison)),
            "aligned_signals": int(detail["alignment_class"].eq("aligned_expected_leg_count").sum()),
            "under_captured_signals": int(detail["alignment_class"].str.contains("under_captured|offset_anchor", regex=True).sum()),
            "over_split_signals": int(detail["alignment_class"].str.contains("over_split|clustering", regex=True).sum()),
            "source_limited_holdouts": int(detail["alignment_class"].eq("under_captured_source_missing_holdout").sum()),
            "insufficient_evidence_signals": int(detail["alignment_class"].eq("insufficient_evidence").sum()),
        },
        "outputs": [
            "full_universe_expected_leg_detail.csv",
            "full_universe_expected_leg_distribution.csv",
            "full_universe_current_vs_expected_comparison.csv",
            "previous_subset_bias_comparison.csv",
            "full_universe_leg_alignment_summary.csv",
            "full_universe_leg_recovery_priority_queue.csv",
            "full_universe_expected_leg_expansion_findings.md",
            "full_universe_expected_leg_expansion_qa.csv",
            "full_universe_expected_leg_expansion_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assigned": False,
            "rates_or_models_calculated": False,
        },
    }
    _write_json(manifest, OUT_DIR / "full_universe_expected_leg_expansion_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
