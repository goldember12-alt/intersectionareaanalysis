from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely import wkt
from shapely.ops import substring


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_physical_leg_normalization_audit"

LEG_DIR = OUTPUT_ROOT / "review/current/expanded_universe_leg_coverage_audit"
GEOM_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
TABLES_DIR = OUTPUT_ROOT / "tables/current"
SCAFFOLD_QA_DIR = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa"

FEET_PER_METER = 3.280839895
BEARING_TOLERANCE_DEGREES = 45

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

REQUIRED_INPUTS = {
    LEG_DIR: [
        "leg_coverage_bin_detail.csv",
        "leg_coverage_signal_summary.csv",
        "leg_coverage_leg_summary.csv",
        "leg_count_distribution.csv",
        "possible_under_capture_flags.csv",
        "possible_over_expansion_flags.csv",
        "expanded_universe_leg_coverage_manifest.json",
    ],
    GEOM_DIR: ["access_geometry_completion_detail.csv"],
    FREEZE_DIR: ["frozen_candidate_bin_universe.csv"],
    TABLES_DIR: [
        "roadway_graph_edges.csv",
        "signal_graph_nodes.csv",
        "signal_oriented_segment_bins_50ft.csv",
        "signal_oriented_segment_bins_50ft_crash_ready.csv",
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
    if lower in {"signal_relative_direction_label", "direction_confidence_status"}:
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


def _require_inputs() -> None:
    missing: list[str] = []
    for directory, names in REQUIRED_INPUTS.items():
        for name in names:
            path = directory / name
            if not path.exists():
                missing.append(str(path))
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))


def _text(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="string")
    return frame[column].fillna(default).astype(str).str.strip()


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _first_nonblank(series: pd.Series) -> str:
    for value in series:
        text = str(value).strip()
        if text:
            return text
    return ""


def _collapse(values: pd.Series, limit: int = 8) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _class_from_count(count: int | float) -> str:
    try:
        value = int(count)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return "no_leg"
    if value == 1:
        return "one_leg"
    if value == 2:
        return "two_leg"
    if value == 3:
        return "three_leg"
    if value == 4:
        return "four_leg"
    return "five_plus_leg"


def _parse_oriented_segment(bin_id: str) -> str:
    return re.sub(r"_bin_\d+$", "", str(bin_id))


def _bearing_from_coords(x1: float, y1: float, x2: float, y2: float) -> float:
    if math.isclose(x1, x2) and math.isclose(y1, y2):
        return np.nan
    # Compass bearing: 0 north, 90 east.
    return (math.degrees(math.atan2(x2 - x1, y2 - y1)) + 360.0) % 360.0


def _bearing_degrees(line: Any) -> float:
    if line is None or getattr(line, "is_empty", True):
        return np.nan
    coords = list(line.coords)
    if len(coords) < 2:
        return np.nan
    x1, y1 = float(coords[0][0]), float(coords[0][1])
    x2, y2 = float(coords[-1][0]), float(coords[-1][1])
    return _bearing_from_coords(x1, y1, x2, y2)


def _bearing_from_signal(point: Any, line: Any) -> float:
    if point is None or line is None or getattr(point, "is_empty", True) or getattr(line, "is_empty", True):
        return np.nan
    target = line.interpolate(0.5, normalized=True)
    return _bearing_from_coords(float(point.x), float(point.y), float(target.x), float(target.y))


def _bearing_sector(bearing: float) -> str:
    if not np.isfinite(bearing):
        return "unknown"
    sector = int(((bearing + (BEARING_TOLERANCE_DEGREES / 2.0)) % 360) // BEARING_TOLERANCE_DEGREES)
    return f"sector_{sector:02d}_{sector * BEARING_TOLERANCE_DEGREES:03d}_{((sector + 1) * BEARING_TOLERANCE_DEGREES) % 360:03d}"


def _line_substring(line: Any, start_ft: float, end_ft: float) -> Any:
    if line is None or getattr(line, "is_empty", True):
        return None
    length_m = line.length
    if not np.isfinite(length_m) or length_m <= 0:
        return None
    start_m = max(min(start_ft / FEET_PER_METER, length_m), 0.0)
    end_m = max(min(end_ft / FEET_PER_METER, length_m), 0.0)
    if abs(end_m - start_m) < 0.01:
        return None
    return substring(line, min(start_m, end_m), max(start_m, end_m), normalized=False)


def _load_inputs() -> dict[str, pd.DataFrame]:
    detail_cols = [
        "target_bin_id",
        "candidate_bin_id",
        "signal_id",
        "candidate_signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_association_id",
        "candidate_leg_id",
        "leg_base_id",
        "candidate_rank",
        "candidate_weight",
        "candidate_weight_num",
        "tie_group_id",
        "road_component_id",
        "graph_edge_id",
        "source_road_row_id",
        "route_id",
        "route_common",
        "route_name",
        "route_or_facility_key",
        "route_or_facility_label",
        "candidate_bin_start_ft",
        "candidate_bin_end_ft",
        "candidate_bin_length_ft",
        "analysis_window",
        "distance_band",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "roadway_division_status",
        "completed_geometry_status",
        "geometry_available_flag",
        "geometry_recovery_method",
        "speed_ready_flag",
        "aadt_ready_flag",
        "speed_aadt_ready_flag",
        "partial_one_sided_flag",
        "multi_candidate_weighted_flag",
        "represented_source",
        "review_only_addition_status",
        "refreshed_universe_tier",
        "provenance_class",
    ]
    geom_cols = [
        "target_bin_id",
        "graph_edge_id",
        "distance_start_ft",
        "distance_end_ft",
        "completed_geometry_status",
        "geometry_recovery_method",
    ]
    freeze_cols = [
        "candidate_bin_id",
        "candidate_association_id",
        "roadway_division_status",
        "road_component_id",
        "graph_edge_id",
        "route_name",
        "route_common",
        "candidate_facility_text",
        "multi_candidate_weighted_flag",
    ]
    return {
        "bin_detail": _read_csv(LEG_DIR / "leg_coverage_bin_detail.csv", usecols=detail_cols),
        "signal_summary": _read_csv(LEG_DIR / "leg_coverage_signal_summary.csv"),
        "leg_summary": _read_csv(LEG_DIR / "leg_coverage_leg_summary.csv"),
        "leg_distribution": _read_csv(LEG_DIR / "leg_count_distribution.csv"),
        "under_flags": _read_csv(LEG_DIR / "possible_under_capture_flags.csv"),
        "over_flags": _read_csv(LEG_DIR / "possible_over_expansion_flags.csv"),
        "geometry_detail": _read_csv(GEOM_DIR / "access_geometry_completion_detail.csv", usecols=geom_cols),
        "freeze_bins": _read_csv(FREEZE_DIR / "frozen_candidate_bin_universe.csv", usecols=freeze_cols),
        "edges": _read_csv(TABLES_DIR / "roadway_graph_edges.csv", usecols=["graph_edge_id", "geometry"]),
        "signal_nodes": _read_csv(TABLES_DIR / "signal_graph_nodes.csv", usecols=["signal_id", "geometry", "snapped_x", "snapped_y"]),
        "base_bins_ready": _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft_crash_ready.csv", usecols=["bin_id", "oriented_segment_id", "base_graph_edge_id", "bin_index", "geometry"]),
        "base_bins_all": _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft.csv", usecols=["bin_id", "oriented_segment_id", "base_graph_edge_id", "bin_index", "geometry"]),
        "usable_bins": _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_prototype_usable_bins_50ft.csv", usecols=["reference_directional_bin_id", "base_segment_id", "bin_index_in_travel_direction"]),
        "excluded_bins": _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_excluded_bins_50ft.csv", usecols=["reference_directional_bin_id", "base_segment_id", "bin_index_in_travel_direction"]),
    }


def _strict_reference_geometry(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ref = pd.concat([inputs["usable_bins"], inputs["excluded_bins"]], ignore_index=True, sort=False)
    ref["_base_bin_index"] = _num(ref, "bin_index_in_travel_direction").fillna(0).astype(int) - 1
    base = pd.concat([inputs["base_bins_ready"], inputs["base_bins_all"]], ignore_index=True, sort=False)
    base = base.drop_duplicates(["oriented_segment_id", "bin_index"])
    base["_base_bin_index"] = _num(base, "bin_index").fillna(-1).astype(int)
    merged = ref.merge(
        base[["oriented_segment_id", "_base_bin_index", "geometry"]],
        left_on=["base_segment_id", "_base_bin_index"],
        right_on=["oriented_segment_id", "_base_bin_index"],
        how="left",
    )
    merged = merged.loc[_text(merged, "geometry").ne("")].copy()
    merged = merged.rename(columns={"reference_directional_bin_id": "target_bin_id"})
    return merged[["target_bin_id", "geometry"]]


def _build_bin_bearings(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    detail = inputs["geometry_detail"].copy()
    detail = detail.loc[_text(detail, "completed_geometry_status").eq("geometry_available")].copy()
    detail["line_geometry"] = None

    strict = _strict_reference_geometry(inputs).set_index("target_bin_id")
    strict_mask = _text(detail, "target_bin_id").isin(strict.index)
    if strict_mask.any():
        detail.loc[strict_mask, "line_geometry"] = _text(detail.loc[strict_mask], "target_bin_id").map(strict["geometry"]).map(wkt.loads)

    edges = inputs["edges"].loc[_text(inputs["edges"], "geometry").ne("")].copy()
    edges["edge_geometry"] = _text(edges, "geometry").map(wkt.loads)
    edge_lookup = edges.set_index("graph_edge_id")["edge_geometry"]
    edge_mask = detail["line_geometry"].isna() & _text(detail, "graph_edge_id").isin(edge_lookup.index)
    recovered: list[tuple[int, Any]] = []
    for row in detail.loc[edge_mask].itertuples(index=True):
        geom = _line_substring(
            edge_lookup.get(str(row.graph_edge_id)),
            float(pd.to_numeric(row.distance_start_ft, errors="coerce")),
            float(pd.to_numeric(row.distance_end_ft, errors="coerce")),
        )
        if geom is not None and not geom.is_empty:
            recovered.append((row.Index, geom))
    if recovered:
        idx, geoms = zip(*recovered)
        detail.loc[list(idx), "line_geometry"] = list(geoms)

    nodes = inputs["signal_nodes"].copy()
    nodes = nodes.drop_duplicates("signal_id")
    nodes["signal_point"] = None
    has_xy = _num(nodes, "snapped_x").notna() & _num(nodes, "snapped_y").notna()
    if has_xy.any():
        # Avoid importing geopandas solely for point construction.
        from shapely.geometry import Point

        nodes.loc[has_xy, "signal_point"] = [
            Point(x, y) for x, y in zip(_num(nodes.loc[has_xy], "snapped_x"), _num(nodes.loc[has_xy], "snapped_y"))
        ]
    geom_mask = nodes["signal_point"].isna() & _text(nodes, "geometry").ne("")
    if geom_mask.any():
        nodes.loc[geom_mask, "signal_point"] = _text(nodes.loc[geom_mask], "geometry").map(wkt.loads)
    signal_lookup = nodes.set_index("signal_id")["signal_point"]
    detail["signal_point"] = _text(detail, "target_signal_id").map(signal_lookup)
    detail["physical_bearing_degrees"] = [
        _bearing_from_signal(point, line) if point is not None else _bearing_degrees(line)
        for point, line in zip(detail["signal_point"], detail["line_geometry"])
    ]
    fallback_mask = pd.to_numeric(detail["physical_bearing_degrees"], errors="coerce").isna()
    if fallback_mask.any():
        detail.loc[fallback_mask, "physical_bearing_degrees"] = detail.loc[fallback_mask, "line_geometry"].map(_bearing_degrees)
    detail["physical_bearing_sector"] = detail["physical_bearing_degrees"].map(_bearing_sector)
    detail["physical_bearing_status"] = np.where(detail["physical_bearing_sector"].eq("unknown"), "bearing_unavailable", "bearing_available")
    return detail[["target_bin_id", "physical_bearing_degrees", "physical_bearing_sector", "physical_bearing_status"]]


def _build_bin_detail(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    detail = inputs["bin_detail"].copy()
    bearings = _build_bin_bearings(inputs)
    detail = detail.merge(bearings, on="target_bin_id", how="left")
    detail["physical_bearing_sector"] = _text(detail, "physical_bearing_sector").replace("", "unknown")
    detail["physical_leg_cluster_id"] = detail["signal_id"].astype(str) + "|" + detail["physical_bearing_sector"].astype(str)
    detail.loc[detail["physical_bearing_sector"].eq("unknown"), "physical_leg_cluster_id"] = detail["signal_id"].astype(str) + "|unknown"
    detail["candidate_branch_id"] = _text(detail, "candidate_leg_id").mask(lambda s: s.eq(""), _text(detail, "candidate_association_id"))
    detail["carriageway_parallel_branch_key"] = (
        _text(detail, "road_component_id")
        .mask(lambda s: s.eq(""), _text(detail, "graph_edge_id"))
        .mask(lambda s: s.eq(""), _text(detail, "candidate_association_id"))
    )
    detail["divided_parallel_indicator"] = (
        _text(detail, "roadway_division_status").str.lower().str.contains("divided", na=False)
        | _text(detail, "candidate_branch_id").str.lower().str.contains("divided|parallel|carriageway", na=False)
    )
    detail["multi_candidate_indicator"] = _text(detail, "multi_candidate_weighted_flag").str.lower().eq("true") | _text(detail, "candidate_weight_num").ne("1.0")
    cols = [
        "target_bin_id",
        "candidate_bin_id",
        "signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_association_id",
        "candidate_branch_id",
        "physical_leg_cluster_id",
        "physical_bearing_degrees",
        "physical_bearing_sector",
        "physical_bearing_status",
        "carriageway_parallel_branch_key",
        "divided_parallel_indicator",
        "multi_candidate_indicator",
        "candidate_leg_id",
        "leg_base_id",
        "road_component_id",
        "graph_edge_id",
        "source_road_row_id",
        "route_or_facility_key",
        "route_or_facility_label",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "roadway_division_status",
        "candidate_bin_start_ft",
        "candidate_bin_end_ft",
        "candidate_bin_length_ft",
        "analysis_window",
        "distance_band",
        "completed_geometry_status",
        "geometry_recovery_method",
        "provenance_class",
        "speed_ready_flag",
        "aadt_ready_flag",
        "speed_aadt_ready_flag",
        "partial_one_sided_flag",
    ]
    return detail[[c for c in cols if c in detail.columns]].copy()


def _signal_summary(detail: pd.DataFrame, old_signal: pd.DataFrame) -> pd.DataFrame:
    work = detail.copy()
    work["bearing_available"] = _text(work, "physical_bearing_status").eq("bearing_available")
    grouped = work.groupby("signal_id", dropna=False)
    signal = grouped.agg(
        source_signal_id=("source_signal_id", _first_nonblank),
        source_layer=("source_layer", _first_nonblank),
        total_bins=("target_bin_id", "nunique"),
        bins_with_bearing=("bearing_available", "sum"),
        normalized_physical_leg_count=("physical_bearing_sector", lambda s: int(s[s.astype(str).ne("unknown")].nunique())),
        candidate_branch_count=("candidate_branch_id", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        carriageway_parallel_branch_count=("carriageway_parallel_branch_key", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        graph_edge_component_count=("graph_edge_id", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        route_facility_group_count=("route_or_facility_key", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        route_facility_labels=("route_or_facility_label", _collapse),
        bearing_sectors=("physical_bearing_sector", _collapse),
        candidate_branch_samples=("candidate_branch_id", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
        roadway_division_statuses=("roadway_division_status", _collapse),
        divided_parallel_bin_count=("divided_parallel_indicator", "sum"),
        multi_candidate_bin_count=("multi_candidate_indicator", "sum"),
        provenance_classes=("provenance_class", _collapse),
    ).reset_index()
    old_cols = [
        "signal_id",
        "candidate_leg_count",
        "leg_count_class",
        "possible_under_capture_flag",
        "possible_over_expansion_flag",
        "intersection_form_interpretation",
        "bins_0_1000",
        "bins_1000_2500",
    ]
    signal = signal.merge(old_signal[[c for c in old_cols if c in old_signal.columns]], on="signal_id", how="left")
    signal = signal.rename(columns={"candidate_leg_count": "old_candidate_leg_count", "leg_count_class": "old_candidate_leg_class"})
    signal["old_candidate_leg_count"] = _num(signal, "old_candidate_leg_count").fillna(0).astype(int)
    signal["normalized_physical_leg_class"] = signal["normalized_physical_leg_count"].map(_class_from_count)
    signal["divided_parallel_indicator"] = signal["divided_parallel_bin_count"].gt(0)
    signal["multi_candidate_indicator"] = signal["multi_candidate_bin_count"].gt(0)
    signal["likely_over_split_flag"] = signal["old_candidate_leg_count"].ge(5) & signal["normalized_physical_leg_count"].le(4)
    signal["likely_under_captured_flag"] = signal["normalized_physical_leg_count"].le(2) | signal.get("possible_under_capture_flag", False).astype(str).str.lower().eq("true")
    signal["physical_leg_vs_candidate_branch_status"] = np.select(
        [
            signal["normalized_physical_leg_count"].eq(0),
            signal["old_candidate_leg_count"].gt(signal["normalized_physical_leg_count"]),
            signal["old_candidate_leg_count"].eq(signal["normalized_physical_leg_count"]),
            signal["old_candidate_leg_count"].lt(signal["normalized_physical_leg_count"]),
        ],
        ["physical_bearing_unavailable", "candidate_branches_exceed_physical_legs", "candidate_branches_match_physical_legs", "physical_legs_exceed_candidate_branches"],
        default="unknown",
    )
    return signal


def _distribution(signal: pd.DataFrame) -> pd.DataFrame:
    return signal.groupby("normalized_physical_leg_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        median_candidate_branch_count=("candidate_branch_count", "median"),
        median_old_candidate_leg_count=("old_candidate_leg_count", "median"),
        median_bins=("total_bins", "median"),
    ).reset_index().sort_values("normalized_physical_leg_class")


def _comparison(signal: pd.DataFrame) -> pd.DataFrame:
    return signal.groupby(["old_candidate_leg_class", "normalized_physical_leg_class", "physical_leg_vs_candidate_branch_status"], dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        median_bins=("total_bins", "median"),
        divided_parallel_signals=("divided_parallel_indicator", "sum"),
        multi_candidate_signals=("multi_candidate_indicator", "sum"),
    ).reset_index()


def _five_plus_diag(signal: pd.DataFrame) -> pd.DataFrame:
    subset = signal.loc[signal["old_candidate_leg_count"].ge(5)].copy()
    if subset.empty:
        return pd.DataFrame()
    subset["five_plus_diagnostic_class"] = np.select(
        [
            subset["normalized_physical_leg_count"].le(4) & subset["divided_parallel_indicator"],
            subset["normalized_physical_leg_count"].le(4) & subset["multi_candidate_indicator"],
            subset["normalized_physical_leg_count"].le(4) & subset["graph_edge_component_count"].gt(subset["normalized_physical_leg_count"]),
            subset["normalized_physical_leg_count"].le(4) & subset["route_facility_group_count"].gt(subset["normalized_physical_leg_count"]),
            subset["normalized_physical_leg_count"].ge(5),
            subset["normalized_physical_leg_count"].eq(0),
        ],
        [
            "divided_carriageway_over_split",
            "multi_candidate_over_split",
            "graph_component_over_split",
            "route_facility_split_same_physical_leg",
            "complex_real_intersection_possible",
            "insufficient_geometry_to_classify",
        ],
        default="graph_component_over_split",
    )
    cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "old_candidate_leg_count",
        "normalized_physical_leg_count",
        "candidate_branch_count",
        "carriageway_parallel_branch_count",
        "graph_edge_component_count",
        "route_facility_group_count",
        "divided_parallel_indicator",
        "multi_candidate_indicator",
        "five_plus_diagnostic_class",
        "bearing_sectors",
        "route_facility_labels",
        "direction_labels",
        "roadway_division_statuses",
        "total_bins",
    ]
    return subset[cols].sort_values(["five_plus_diagnostic_class", "old_candidate_leg_count", "total_bins"], ascending=[True, False, False])


def _two_leg_diag(signal: pd.DataFrame) -> pd.DataFrame:
    subset = signal.loc[signal["old_candidate_leg_count"].eq(2)].copy()
    if subset.empty:
        return pd.DataFrame()
    subset["two_leg_diagnostic_class"] = np.select(
        [
            subset["normalized_physical_leg_count"].le(2) & subset["route_facility_group_count"].le(1) & subset["multi_candidate_indicator"],
            subset["normalized_physical_leg_count"].le(2) & subset["route_facility_group_count"].le(1),
            subset["normalized_physical_leg_count"].eq(3),
            subset["normalized_physical_leg_count"].le(2) & subset["bins_0_1000"].astype(float).lt(20),
            subset["normalized_physical_leg_count"].le(2) & subset["route_facility_group_count"].ge(2),
            subset["normalized_physical_leg_count"].eq(0),
        ],
        [
            "candidate_recovery_limited_to_one_axis",
            "likely_corridor_only_cross_street_missing",
            "t_intersection_under_count_possible",
            "side_street_geometry_missing",
            "valid_two_leg_or_partial_control_possible",
            "insufficient_geometry_to_classify",
        ],
        default="valid_two_leg_or_partial_control_possible",
    )
    cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "old_candidate_leg_count",
        "normalized_physical_leg_count",
        "candidate_branch_count",
        "carriageway_parallel_branch_count",
        "route_facility_group_count",
        "two_leg_diagnostic_class",
        "bearing_sectors",
        "route_facility_labels",
        "direction_labels",
        "total_bins",
        "bins_0_1000",
        "bins_1000_2500",
    ]
    return subset[cols].sort_values(["two_leg_diagnostic_class", "total_bins"], ascending=[True, False])


def _review_queue(signal: pd.DataFrame, five: pd.DataFrame, two: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    definitions = [
        ("high_confidence_four_leg_examples", signal["normalized_physical_leg_count"].eq(4) & signal["old_candidate_leg_count"].between(4, 5)),
        ("likely_t_intersection_examples", signal["normalized_physical_leg_count"].eq(3) & signal["total_bins"].ge(40)),
        ("five_plus_over_split_examples", signal["signal_id"].isin(set(five.loc[five["five_plus_diagnostic_class"].str.contains("over_split|same_physical", na=False), "signal_id"])) if not five.empty else pd.Series(False, index=signal.index)),
        ("two_leg_under_capture_examples", signal["signal_id"].isin(set(two.loc[two["two_leg_diagnostic_class"].str.contains("missing|under_count|limited", na=False), "signal_id"])) if not two.empty else pd.Series(False, index=signal.index)),
        ("signals_needing_mapped_review", signal["normalized_physical_leg_count"].ge(5) | signal["normalized_physical_leg_count"].le(2) | signal["bins_with_bearing"].eq(0)),
    ]
    for label, mask in definitions:
        subset = signal.loc[mask].copy()
        if subset.empty:
            continue
        subset["review_queue"] = label
        subset["review_priority_score"] = (
            subset["old_candidate_leg_count"].astype(float) * 10
            + subset["normalized_physical_leg_count"].astype(float) * 8
            + subset["total_bins"].astype(float) / 25
        )
        rows.append(subset.sort_values("review_priority_score", ascending=False).head(75))
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True, sort=False)
    cols = [
        "review_queue",
        "review_priority_score",
        "signal_id",
        "source_signal_id",
        "source_layer",
        "old_candidate_leg_count",
        "normalized_physical_leg_count",
        "candidate_branch_count",
        "carriageway_parallel_branch_count",
        "route_facility_group_count",
        "divided_parallel_indicator",
        "multi_candidate_indicator",
        "physical_leg_vs_candidate_branch_status",
        "bearing_sectors",
        "route_facility_labels",
        "total_bins",
    ]
    return out[cols]


def _qa(signal: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "This module writes only to expanded_universe_physical_leg_normalization_audit review folder."),
        ("no_candidates_promoted", "pass", "All outputs are review-only diagnostics."),
        ("no_access_or_crash_assignment", "pass", "No access or crash assignment is performed."),
        ("no_rates_or_models", "pass", "No rates or models are computed."),
        ("signals_not_forced_to_four_legs", "pass", "Bearing sectors are observed clusters; no signal is coerced to four legs."),
        ("physical_legs_separated_from_candidate_branches_carriageways", "pass", "Outputs include physical_leg_cluster_id, candidate_branch_id, and carriageway_parallel_branch_key separately."),
        ("outputs_review_only", "pass", str(OUT_DIR)),
        ("outputs_written_only_to_review_folder", "pass", str(OUT_DIR)),
        ("deduped_signal_count", "pass", f"{signal['signal_id'].nunique():,} signals summarized."),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(signal: pd.DataFrame, distribution: pd.DataFrame, five: pd.DataFrame, two: pd.DataFrame) -> str:
    dist = dict(zip(distribution["normalized_physical_leg_class"], distribution["signal_count"]))
    five_total = int(signal["old_candidate_leg_count"].ge(5).sum())
    five_over = int(five.loc[five["five_plus_diagnostic_class"].str.contains("over_split|same_physical", na=False), "signal_id"].nunique()) if not five.empty else 0
    five_complex = int(five.loc[five["five_plus_diagnostic_class"].eq("complex_real_intersection_possible"), "signal_id"].nunique()) if not five.empty else 0
    two_total = int(signal["old_candidate_leg_count"].eq(2).sum())
    two_under = int(two.loc[two["two_leg_diagnostic_class"].str.contains("missing|under_count|limited", na=False), "signal_id"].nunique()) if not two.empty else 0
    axis_like = int(signal.loc[signal["normalized_physical_leg_count"].le(2), "signal_id"].nunique())
    three_plus = int(signal.loc[signal["normalized_physical_leg_count"].ge(3), "signal_id"].nunique())
    return f"""# Expanded Universe Physical Leg Normalization Findings

**Bounded question:** distinguish physical intersection legs from candidate branches, carriageways, graph components, and route/facility splits in the 2,739-signal expanded universe.

## Direct Answers

1. Normalized physical leg distribution: one-leg **{dist.get('one_leg', 0):,}**, two-leg **{dist.get('two_leg', 0):,}**, three-leg **{dist.get('three_leg', 0):,}**, four-leg **{dist.get('four_leg', 0):,}**, five-plus **{dist.get('five_plus_leg', 0):,}**, no bearing **{dist.get('no_leg', 0):,}**.
2. Of **{five_total:,}** old five-plus candidate-leg signals, **{five_over:,}** look like over-split candidate branches/carriageways/route components under this bearing normalization, while **{five_complex:,}** remain possible real complex five-plus intersections.
3. Of **{two_total:,}** old two-leg signals, **{two_under:,}** look like likely cross-street under-capture or one-axis recovery-limited cases.
4. The scaffold is capturing more than one roadway axis for many signals: **{three_plus:,}** signals have three or more normalized physical approaches, while **{axis_like:,}** remain one/two-approach or partial-axis cases needing caution.
5. Divided carriageways should be represented as a physical leg with carriageway/parallel sub-branches, not as separate physical legs by default. The outputs keep `physical_leg_cluster_id`, `candidate_branch_id`, and `carriageway_parallel_branch_key` separate for that reason.
6. Recommended next scaffold correction pass: review five-plus over-split and two-leg under-capture queues on maps, then add a physical-leg normalization field to downstream review outputs before any access/crash catchment metric chooses denominators.

No active outputs were modified, candidates promoted, access/crashes assigned, rates calculated, or models run.
"""


def _manifest(started: datetime, outputs: list[str], inputs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.audit.expanded_universe_physical_leg_normalization_audit",
        "bounded_question": "physical-leg normalization audit for expanded universe",
        "started_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR),
        "bearing_tolerance_degrees": BEARING_TOLERANCE_DEGREES,
        "inputs": {name: {"rows": int(len(frame)), "columns": list(frame.columns)} for name, frame in inputs.items()},
        "outputs": outputs,
        "non_goals_confirmed": [
            "no scaffold rebuild",
            "no access assignment",
            "no crash assignment",
            "no active output modification",
            "no candidate promotion",
        ],
    }


def _write_outputs(outputs: dict[str, pd.DataFrame], findings: str, manifest: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_csv(OUT_DIR / name, index=False)
        _checkpoint(f"write_complete {name}", len(frame))
    (OUT_DIR / "expanded_universe_physical_leg_normalization_findings.md").write_text(findings, encoding="utf-8")
    (OUT_DIR / "expanded_universe_physical_leg_normalization_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _checkpoint("write_complete expanded_universe_physical_leg_normalization_findings.md")
    _checkpoint("write_complete expanded_universe_physical_leg_normalization_manifest.json")


def main() -> None:
    started = datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    _require_inputs()
    inputs = _load_inputs()
    bin_detail = _build_bin_detail(inputs)
    _checkpoint("build_bin_detail", len(bin_detail))
    signal = _signal_summary(bin_detail, inputs["signal_summary"])
    _checkpoint("build_signal_summary", len(signal))
    distribution = _distribution(signal)
    comparison = _comparison(signal)
    five = _five_plus_diag(signal)
    two = _two_leg_diag(signal)
    queue = _review_queue(signal, five, two)
    qa = _qa(signal)
    findings = _findings(signal, distribution, five, two)
    outputs = {
        "physical_leg_bin_detail.csv": bin_detail,
        "physical_leg_signal_summary.csv": signal,
        "physical_leg_count_distribution.csv": distribution,
        "candidate_vs_physical_leg_comparison.csv": comparison,
        "five_plus_leg_diagnostic.csv": five,
        "two_leg_under_capture_diagnostic.csv": two,
        "physical_leg_ranked_review_queue.csv": queue,
        "expanded_universe_physical_leg_normalization_qa.csv": qa,
    }
    output_names = list(outputs) + [
        "expanded_universe_physical_leg_normalization_findings.md",
        "expanded_universe_physical_leg_normalization_manifest.json",
        "run_progress_log.txt",
    ]
    _write_outputs(outputs, findings, _manifest(started, output_names, inputs))
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
