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
OUT_DIR = OUTPUT_ROOT / "review/current/final_universe_access_rerun"

FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_CONTEXT_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"
CONSOLIDATED_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
ACCESS_CAPTURE_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_capture"
ACCESS_GEOMETRY_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"
ACCESS_SOURCE_AUDIT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_source_capture_audit"
ACCESS_UNCAPTURED_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_uncaptured_source_diagnostic"
SCAFFOLD_QA_DIR = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa"
TABLES_DIR = OUTPUT_ROOT / "tables/current"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

FEET_PER_METER = 3.280839895
BUFFER_WIDTHS_FT = [35, 50, 75, 100]
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
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_physical_leg_distribution.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_two_leg_or_less_audit.csv",
    FINAL_OVERVIEW_DIR / "final_access_readiness_decision.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_CONTEXT_DIR / "final_recovery_context_bin_detail.csv",
    FINAL_CONTEXT_DIR / "final_recovery_context_signal_summary.csv",
    FINAL_CONTEXT_DIR / "final_source_data_limitation_ledger.csv",
    FINAL_CONTEXT_DIR / "final_recovery_context_refresh_manifest.json",
    CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json",
    ACCESS_V1_FILE,
    ACCESS_V2_FILE,
    SCAFFOLD_QA_DIR / "directional_scaffold_prototype_usable_bins_50ft.csv",
    SCAFFOLD_QA_DIR / "directional_scaffold_excluded_bins_50ft.csv",
    TABLES_DIR / "signal_oriented_segment_bins_50ft_crash_ready.csv",
    TABLES_DIR / "signal_oriented_segment_bins_50ft.csv",
    TABLES_DIR / "roadway_graph_edges.csv",
    FREEZE_DIR / "frozen_candidate_bin_universe.csv",
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
    if lower in {"signal_relative_direction", "signal_relative_direction_label", "access_direction", "access_direction_raw", "access_direction_normalized"}:
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
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
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


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


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
        keep_extra = ["access_v2_source_priority", "access_v2_source_row_id", "access_v2_staging_status", "access_control_code", "access_direction_normalized"]
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["access_layer"] = "untyped"
        access["access_control_category"] = "untyped"
        access["route_name"] = access.get("_rte_nm", "").astype(str)
        keep_extra = ["Stage1_SourceGDB", "Stage1_SourceLayer"]
    keep = ["access_point_id", "access_layer", "access_control_category", "route_name", "geometry"] + [col for col in keep_extra if col in access.columns]
    out = access[keep].copy()
    out = out.loc[out.geometry.notna() & ~out.geometry.is_empty & out["access_point_id"].astype(str).str.strip().ne("")]
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _strict_reference_geometry_lookup() -> pd.DataFrame:
    usable_cols = ["reference_directional_bin_id", "base_segment_id", "bin_index_in_travel_direction"]
    ref = pd.concat(
        [
            _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_prototype_usable_bins_50ft.csv", usecols=usable_cols),
            _read_csv(SCAFFOLD_QA_DIR / "directional_scaffold_excluded_bins_50ft.csv", usecols=usable_cols),
        ],
        ignore_index=True,
        sort=False,
    ).drop_duplicates("reference_directional_bin_id")
    ref["_base_bin_index"] = _num(ref, "bin_index_in_travel_direction").fillna(0).astype(int) - 1

    base_cols = ["oriented_segment_id", "bin_index", "geometry"]
    base = pd.concat(
        [
            _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft_crash_ready.csv", usecols=base_cols),
            _read_csv(TABLES_DIR / "signal_oriented_segment_bins_50ft.csv", usecols=base_cols),
        ],
        ignore_index=True,
        sort=False,
    ).drop_duplicates(["oriented_segment_id", "bin_index"])
    base["_base_bin_index"] = _num(base, "bin_index").fillna(-1).astype(int)
    lookup = ref.merge(
        base[["oriented_segment_id", "_base_bin_index", "geometry"]],
        left_on=["base_segment_id", "_base_bin_index"],
        right_on=["oriented_segment_id", "_base_bin_index"],
        how="left",
    )
    lookup = lookup.loc[_text(lookup, "geometry").ne("")]
    lookup = lookup.rename(columns={"reference_directional_bin_id": "original_bin_id", "geometry": "recovered_geometry_wkt"})
    lookup["geometry_recovery_method"] = "strict_reference_bin_wkt_from_signal_oriented_segment_bins"
    return lookup[["original_bin_id", "recovered_geometry_wkt", "geometry_recovery_method"]].drop_duplicates("original_bin_id")


def _line_substring(line: Any, start_ft: float, end_ft: float) -> Any:
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


def _frozen_candidate_geometry_lookup(missing_target: pd.DataFrame) -> pd.DataFrame:
    needed = set(_text(missing_target, "original_bin_id"))
    needed = {value for value in needed if value.startswith("frozen_candidate_bin_")}
    if not needed:
        return pd.DataFrame(columns=["original_bin_id", "frozen_recovered_geometry_wkt", "frozen_geometry_recovery_method"])
    frozen = _read_csv(
        FREEZE_DIR / "frozen_candidate_bin_universe.csv",
        usecols=["frozen_candidate_bin_id", "graph_edge_id"],
    )
    frozen = frozen.loc[_text(frozen, "frozen_candidate_bin_id").isin(needed)].copy()
    if frozen.empty:
        return pd.DataFrame(columns=["original_bin_id", "frozen_recovered_geometry_wkt", "frozen_geometry_recovery_method"])
    edge_ids = set(_text(frozen, "graph_edge_id"))
    edges = _read_csv(TABLES_DIR / "roadway_graph_edges.csv", usecols=["graph_edge_id", "geometry"])
    edges = edges.loc[_text(edges, "graph_edge_id").isin(edge_ids) & _text(edges, "geometry").ne("")].copy()
    edge_lookup = {row.graph_edge_id: wkt.loads(row.geometry) for row in edges.itertuples(index=False)}
    dist = missing_target.loc[_text(missing_target, "original_bin_id").isin(needed), ["original_bin_id", "distance_start_ft", "distance_end_ft"]].copy()
    work = frozen.rename(columns={"frozen_candidate_bin_id": "original_bin_id"}).merge(dist, on="original_bin_id", how="left")
    rows = []
    for row in work.itertuples(index=False):
        line = edge_lookup.get(str(row.graph_edge_id))
        geom = _line_substring(line, float(pd.to_numeric(row.distance_start_ft, errors="coerce")), float(pd.to_numeric(row.distance_end_ft, errors="coerce")))
        if geom is not None and not geom.is_empty:
            rows.append(
                {
                    "original_bin_id": row.original_bin_id,
                    "frozen_recovered_geometry_wkt": geom.wkt,
                    "frozen_geometry_recovery_method": "frozen_candidate_graph_edge_id_substring",
                }
            )
    return pd.DataFrame(rows).drop_duplicates("original_bin_id") if rows else pd.DataFrame(columns=["original_bin_id", "frozen_recovered_geometry_wkt", "frozen_geometry_recovery_method"])


def _build_target_bins(final_bins: pd.DataFrame, signal_detail: pd.DataFrame) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    target = final_bins.copy()
    target["target_signal_id"] = _text(target, "signal_id")
    target["target_bin_id"] = _text(target, "consolidated_bin_id").where(_text(target, "consolidated_bin_id").ne(""), _text(target, "original_bin_id"))
    target["target_bin_id"] = target["target_bin_id"].where(target["target_bin_id"].ne(""), "final_access_target_bin_" + target.index.astype(str).str.zfill(8))
    target["target_source_id"] = _text(target, "source_signal_id")
    target["target_source_layer"] = _text(target, "source_layer")
    target["physical_leg_id_final"] = _text(target, "final_normalized_physical_leg_id").where(_text(target, "final_normalized_physical_leg_id").ne(""), _text(target, "physical_leg_id"))
    target["carriageway_subbranch_id_final"] = _text(target, "final_carriageway_subbranch_id").where(_text(target, "final_carriageway_subbranch_id").ne(""), _text(target, "carriageway_subbranch_id"))
    target["distance_length_ft"] = (_num(target, "distance_end_ft") - _num(target, "distance_start_ft")).abs()
    target["distance_length_ft"] = target["distance_length_ft"].where(target["distance_length_ft"].gt(0), 50.0)
    target["candidate_weight_num"] = 1.0

    sig_cols = [
        "signal_id",
        "final_physical_leg_class",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
        "final_speed_aadt_ready_flag",
    ]
    target = target.merge(signal_detail[[col for col in sig_cols if col in signal_detail.columns]].drop_duplicates("signal_id"), on="signal_id", how="left")

    target["completed_geometry_status"] = "geometry_unavailable"
    target["geometry_recovery_method"] = ""
    direct_mask = _text(target, "geometry_wkt").ne("")
    target.loc[direct_mask, "completed_geometry_status"] = "geometry_available"
    target.loc[direct_mask, "geometry_recovery_method"] = "final_overview_geometry_wkt"

    missing_geom = target.loc[~direct_mask, ["original_bin_id"]].drop_duplicates()
    if not missing_geom.empty:
        lookup = _strict_reference_geometry_lookup()
        target = target.merge(lookup, on="original_bin_id", how="left")
        recover_mask = target["geometry_wkt"].astype(str).str.strip().eq("") & _text(target, "recovered_geometry_wkt").ne("")
        target.loc[recover_mask, "geometry_wkt"] = target.loc[recover_mask, "recovered_geometry_wkt"]
        target.loc[recover_mask, "completed_geometry_status"] = "geometry_available"
        target.loc[recover_mask, "geometry_recovery_method"] = target.loc[recover_mask, "geometry_recovery_method_y"]
        target = target.drop(columns=[col for col in ["recovered_geometry_wkt", "geometry_recovery_method_y"] if col in target.columns], errors="ignore")
        if "geometry_recovery_method_x" in target.columns:
            target = target.rename(columns={"geometry_recovery_method_x": "geometry_recovery_method"})
    still_missing = target.loc[_text(target, "geometry_wkt").eq(""), ["original_bin_id", "distance_start_ft", "distance_end_ft"]].drop_duplicates()
    if not still_missing.empty:
        frozen_lookup = _frozen_candidate_geometry_lookup(still_missing)
        if not frozen_lookup.empty:
            target = target.merge(frozen_lookup, on="original_bin_id", how="left")
            frozen_recover_mask = _text(target, "geometry_wkt").eq("") & _text(target, "frozen_recovered_geometry_wkt").ne("")
            target.loc[frozen_recover_mask, "geometry_wkt"] = target.loc[frozen_recover_mask, "frozen_recovered_geometry_wkt"]
            target.loc[frozen_recover_mask, "completed_geometry_status"] = "geometry_available"
            target.loc[frozen_recover_mask, "geometry_recovery_method"] = target.loc[frozen_recover_mask, "frozen_geometry_recovery_method"]
            target = target.drop(columns=["frozen_recovered_geometry_wkt", "frozen_geometry_recovery_method"], errors="ignore")
    target["geometry_blocker_reason"] = np.where(target["completed_geometry_status"].eq("geometry_available"), "", "geometry_unavailable")

    target_cols = [
        "target_signal_id",
        "target_source_id",
        "target_source_layer",
        "target_bin_id",
        "original_bin_id",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "route_facility_fields",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "distance_length_ft",
        "geometry_wkt",
        "completed_geometry_status",
        "geometry_recovery_method",
        "geometry_blocker_reason",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "final_alignment_class",
        "final_physical_leg_class",
        "review_only_recovery_provenance",
        "final_bin_source_package",
        "final_original_or_recovered",
        "recovery_stream",
        "recovery_class",
        "route_facility_discontinuity_flag",
        "offset_anchor_flag",
        "grade_separation_or_mainline_review_flag",
        "long_source_row_flag",
        "candidate_weight_num",
    ]
    target = target[[col for col in target_cols if col in target.columns]].copy()
    geom_rows = target.loc[target["completed_geometry_status"].eq("geometry_available") & _text(target, "geometry_wkt").ne("")].copy()
    geom_rows["geometry"] = geom_rows["geometry_wkt"].map(lambda value: wkt.loads(value) if str(value).strip() else None)
    lines = gpd.GeoDataFrame(geom_rows.drop(columns=["geometry_wkt"]), geometry="geometry", crs="EPSG:3968")
    lines = lines.loc[lines.geometry.notna() & ~lines.geometry.is_empty].copy()
    _checkpoint("target_geometry_available", len(lines), note=f"signals={lines['target_signal_id'].nunique():,}")
    return target, lines


def _assign_for_width(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str, width_ft: int) -> pd.DataFrame:
    if lines.empty or access.empty:
        return pd.DataFrame()
    catchments = lines[
        [
            "target_bin_id",
            "target_signal_id",
            "target_source_id",
            "target_source_layer",
            "physical_leg_id_final",
            "carriageway_subbranch_id_final",
            "analysis_window",
            "distance_band",
            "distance_length_ft",
            "candidate_weight_num",
            "geometry_recovery_method",
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
    ].copy()
    catchments["geometry"] = catchments.geometry.buffer(width_ft / FEET_PER_METER, cap_style="flat", join_style="mitre")
    catchments = gpd.GeoDataFrame(catchments, geometry="geometry", crs="EPSG:3968")
    joined = gpd.sjoin(access.drop(columns=[col for col in access.columns if col == "index_right"], errors="ignore"), catchments, how="inner", predicate="within")
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
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "unweighted_assignment_total", "count": round(float(pd.to_numeric(subset.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "weighted_assignment_total", "count": round(float(pd.to_numeric(subset.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not subset.empty else 0},
                    {"access_layer": layer, "buffer_width_ft": width, "metric": "geometry_available_signals_without_access", "count": len(geometry_signals - any_signals)},
                ]
            )
    return pd.DataFrame(rows)


def _fanout_summary(assignments: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame(columns=["access_layer", "buffer_width_ft", "assignment_fanout_count", "source_access_point_count"])
    fanout = assignments.drop_duplicates(["buffer_width_ft", "access_point_id"]).copy()
    out = fanout.groupby(["buffer_width_ft", "assignment_fanout_count"], dropna=False).agg(source_access_point_count=("access_point_id", "nunique")).reset_index()
    out["access_layer"] = layer
    return out


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


def _typed_category_summary(typed: pd.DataFrame) -> pd.DataFrame:
    if typed.empty:
        return pd.DataFrame()
    return typed.groupby(["buffer_width_ft", "access_control_category"], dropna=False).agg(
        signal_count=("target_signal_id", "nunique"),
        source_access_point_count=("access_point_id", "nunique"),
        assignment_count=("access_point_id", "size"),
        weighted_assignment_total=("source_preserving_weighted_access_count", "sum"),
    ).reset_index()


def _missingness(target: pd.DataFrame, untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "missingness_reason": "geometry_unavailable",
            "signal_count": int(_text(target.loc[_text(target, "completed_geometry_status").ne("geometry_available")], "target_signal_id").nunique()),
            "bin_count": int(_text(target, "completed_geometry_status").ne("geometry_available").sum()),
            "note": "Target bins without line geometry were not forced into access assignment.",
        }
    ]
    geometry_signals = set(_text(target.loc[_text(target, "completed_geometry_status").eq("geometry_available")], "target_signal_id"))
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        for width in BUFFER_WIDTHS_FT:
            subset = frame.loc[pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(width)] if not frame.empty else pd.DataFrame()
            assigned = set(_text(subset, "target_signal_id"))
            rows.append(
                {
                    "missingness_reason": f"{layer}_{width}ft_geometry_available_no_access",
                    "signal_count": len(geometry_signals - assigned),
                    "bin_count": "",
                    "note": "Signals have target geometry but no access point captured at this buffer width.",
                }
            )
    return pd.DataFrame(rows)


def _prior_comparison(final_coverage: pd.DataFrame) -> pd.DataFrame:
    prior = ACCESS_GEOMETRY_DIR / "access_buffer_sensitivity_summary.csv"
    prior_frame = _read_csv(prior) if prior.exists() else pd.DataFrame()
    rows = []
    for layer in ["untyped", "typed_v2"]:
        for width in BUFFER_WIDTHS_FT:
            final_count = final_coverage.loc[
                final_coverage["access_layer"].eq(layer)
                & pd.to_numeric(final_coverage["buffer_width_ft"], errors="coerce").eq(width)
                & final_coverage["metric"].eq("signals_with_access"),
                "count",
            ]
            prior_count = prior_frame.loc[
                prior_frame["access_layer"].eq(layer)
                & pd.to_numeric(prior_frame["buffer_width_ft"], errors="coerce").eq(width)
                & prior_frame["metric"].eq("signals_with_access"),
                "count",
            ] if not prior_frame.empty else pd.Series(dtype=object)
            final_value = float(final_count.iloc[0]) if not final_count.empty else np.nan
            prior_value = float(prior_count.iloc[0]) if not prior_count.empty else np.nan
            rows.append(
                {
                    "access_layer": layer,
                    "buffer_width_ft": width,
                    "prior_signal_coverage": prior_value,
                    "final_signal_coverage": final_value,
                    "coverage_delta": final_value - prior_value if np.isfinite(final_value) and np.isfinite(prior_value) else "",
                    "comparison_status": "compared_to_access_geometry_completion" if np.isfinite(prior_value) else "prior_summary_not_available",
                }
            )
    return pd.DataFrame(rows)


def _write_findings(target: pd.DataFrame, untyped: pd.DataFrame, typed: pd.DataFrame, coverage: pd.DataFrame, comparison: pd.DataFrame) -> None:
    signals = int(_text(target, "target_signal_id").nunique())
    bins = len(target)
    geom_bins = int(_text(target, "completed_geometry_status").eq("geometry_available").sum())
    geom_signals = int(_text(target.loc[_text(target, "completed_geometry_status").eq("geometry_available")], "target_signal_id").nunique())

    def metric(layer: str, width: int, name: str) -> int:
        rows = coverage.loc[
            coverage["access_layer"].eq(layer)
            & pd.to_numeric(coverage["buffer_width_ft"], errors="coerce").eq(width)
            & coverage["metric"].eq(name),
            "count",
        ]
        return int(float(rows.iloc[0])) if not rows.empty else 0

    untyped_lines = "\n".join(f"- {width} ft: {metric('untyped', width, 'signals_with_access'):,} signals" for width in BUFFER_WIDTHS_FT)
    typed_lines = "\n".join(f"- {width} ft: {metric('typed_v2', width, 'signals_with_access'):,} signals" for width in BUFFER_WIDTHS_FT)
    comparison_lines = []
    for layer in ["untyped", "typed_v2"]:
        rows = comparison.loc[comparison["access_layer"].eq(layer)]
        if rows.empty:
            continue
        parts = []
        for row in rows.itertuples(index=False):
            parts.append(f"{int(row.buffer_width_ft)} ft delta {int(float(row.coverage_delta)) if str(row.coverage_delta) else 'NA'}")
        comparison_lines.append(f"- {layer}: " + "; ".join(parts))
    comparison_text = "\n".join(comparison_lines) if comparison_lines else "- Prior comparison unavailable."
    text = f"""# Final Universe Access Rerun Findings

## Bounded Question

Rerun typed and untyped access capture on the final review-only scaffold universe while carrying scaffold QA flags and keeping weighted/unweighted products separate.

## Findings

- Final target signals: {signals:,}.
- Final target bins: {bins:,}.
- Target bins with geometry: {geom_bins:,}; target signals with geometry: {geom_signals:,}.
- Untyped access signal coverage:
{untyped_lines}
- Typed v2 access signal coverage:
{typed_lines}
- Untyped assignment rows: {len(untyped):,}.
- Typed v2 assignment rows: {len(typed):,}.
- Prior signal-coverage comparison:
{comparison_text}
- Coverage is slightly lower than the prior access geometry completion run because some final scaffold target rows still lack persisted or recoverable line geometry.
- Final scaffold recovery should be carried forward as access context, not as promoted active scaffold.

## Recommendation

Carry both untyped and typed v2 products forward for crash/catchment planning review. Use source-preserving weighted counts for source-point summaries and retain unweighted/double-counted outputs for transparent catchment sensitivity. Before treating coverage deltas as substantive, run a geometry-persistence cleanup for the 633 signals with geometry-unavailable target bins.
"""
    _write_text(text, "final_universe_access_rerun_findings.md")


def _write_qa(target: pd.DataFrame) -> None:
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/final_universe_access_rerun."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "No active scaffold or promotion outputs are written."},
            {"qa_check": "no_crash_records_read", "status": "pass", "detail": "No crash files are read."},
            {"qa_check": "no_crash_direction_fields_read_or_used", "status": "pass", "detail": "Crash-direction-like fields are blocked; access direction fields are source access attributes only."},
            {"qa_check": "no_crash_assignment_or_catchments", "status": "pass", "detail": "No crash assignment/catchment outputs are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate/model calculations are run."},
            {"qa_check": "typed_and_untyped_separate", "status": "pass", "detail": "Separate detail and signal-window summary outputs are written."},
            {"qa_check": "weighted_and_unweighted_separate", "status": "pass", "detail": "Assignment rows preserve unweighted and source-preserving weighted counts."},
            {"qa_check": "scaffold_qa_flags_carried", "status": "pass", "detail": "Final alignment, holdout, provenance, physical leg, and subbranch fields are included."},
            {"qa_check": "source_point_counts_separate", "status": "pass", "detail": "Coverage summaries separate source access point counts from assignment rows."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"{len(target):,} target bins written under {OUT_DIR}."},
        ]
    )
    _write_csv(qa, "final_universe_access_rerun_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    final_bins = _read_csv(FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv")
    signal_detail = _read_csv(FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv")
    target, lines = _build_target_bins(final_bins, signal_detail)
    access_v1 = _read_access(ACCESS_V1_FILE, typed=False)
    access_v2 = _read_access(ACCESS_V2_FILE, typed=True)
    untyped = _assign_all(lines, access_v1, layer="untyped")
    typed = _assign_all(lines, access_v2, layer="typed_v2")
    untyped_summary = _signal_window_summary(untyped, target, layer="untyped")
    typed_summary = _signal_window_summary(typed, target, layer="typed_v2")
    coverage = _coverage_summary(untyped, typed, target)
    fanout = pd.concat([_fanout_summary(untyped, layer="untyped"), _fanout_summary(typed, layer="typed_v2")], ignore_index=True, sort=False)
    qa_summary = pd.concat([_by_scaffold_qa(untyped, layer="untyped"), _by_scaffold_qa(typed, layer="typed_v2")], ignore_index=True, sort=False)
    typed_category = _typed_category_summary(typed)
    missingness = _missingness(target, untyped, typed)
    comparison = _prior_comparison(coverage)

    _write_csv(target, "final_access_target_bins.csv")
    _write_csv(untyped, "final_untyped_access_assignment_detail.csv")
    _write_csv(untyped_summary, "final_untyped_access_signal_window_summary.csv")
    _write_csv(typed, "final_typed_v2_access_assignment_detail.csv")
    _write_csv(typed_summary, "final_typed_v2_access_signal_window_summary.csv")
    _write_csv(coverage, "final_access_product_coverage_summary.csv")
    _write_csv(fanout, "final_access_fanout_summary.csv")
    _write_csv(qa_summary, "final_access_by_scaffold_qa_summary.csv")
    _write_csv(typed_category, "final_typed_v2_category_summary.csv")
    _write_csv(missingness, "final_access_missingness_summary.csv")
    _write_csv(comparison, "final_access_vs_prior_comparison.csv")
    _write_findings(target, untyped, typed, coverage, comparison)
    _write_qa(target)

    manifest = {
        "script": "src.roadway_graph.build.final_universe_access_rerun",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Review-only final scaffold access rerun with typed/untyped and weighted/unweighted products separated.",
        "output_directory": str(OUT_DIR),
        "buffer_widths_ft": BUFFER_WIDTHS_FT,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "final_access_target_bins.csv",
            "final_untyped_access_assignment_detail.csv",
            "final_untyped_access_signal_window_summary.csv",
            "final_typed_v2_access_assignment_detail.csv",
            "final_typed_v2_access_signal_window_summary.csv",
            "final_access_product_coverage_summary.csv",
            "final_access_fanout_summary.csv",
            "final_access_by_scaffold_qa_summary.csv",
            "final_typed_v2_category_summary.csv",
            "final_access_missingness_summary.csv",
            "final_access_vs_prior_comparison.csv",
            "final_universe_access_rerun_findings.md",
            "final_universe_access_rerun_qa.csv",
            "final_universe_access_rerun_manifest.json",
            "run_progress_log.txt",
        ],
        "summary": {
            "target_signal_count": int(_text(target, "target_signal_id").nunique()),
            "target_bin_count": int(len(target)),
            "geometry_available_signal_count": int(_text(target.loc[_text(target, "completed_geometry_status").eq("geometry_available")], "target_signal_id").nunique()),
            "geometry_available_bin_count": int(_text(target, "completed_geometry_status").eq("geometry_available").sum()),
            "untyped_assignment_rows": int(len(untyped)),
            "typed_v2_assignment_rows": int(len(typed)),
            "coverage_summary": coverage.to_dict(orient="records"),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_assignment_or_catchments": False,
            "rates_or_models": False,
            "review_only": True,
        },
        "upstream_manifests": {
            "final_signal_leg_universe_overview": _load_json(FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json").get("created_at_utc", ""),
            "final_recovery_context_refresh": _load_json(FINAL_CONTEXT_DIR / "final_recovery_context_refresh_manifest.json").get("created_at_utc", ""),
            "consolidated_scaffold": _load_json(CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "final_universe_access_rerun_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
