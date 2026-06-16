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
OUT_DIR = OUTPUT_ROOT / "review/current/stable_lineage_final_access_rerun"

STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
PRIOR_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_rerun_with_source_accounting"
HYBRID_DIR = OUTPUT_ROOT / "review/current/final_access_hybrid_source_travelway_diagnostic"
PRIOR_TRAVELWAY_DIR = OUTPUT_ROOT / "review/current/final_access_travelway_normalization_test"
LINEAGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

FEET_PER_METER = 3.280839895
BUFFER_WIDTHS_FT = [35, 50, 75, 100]
SPATIAL_BASELINE_WIDTH_FT = 100
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
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_generation_lineage_audit.csv",
    STABLE_DIR / "stable_lineage_previous_vs_regenerated_comparison.csv",
    STABLE_DIR / "stable_lineage_previously_unmatched_recovery_summary.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_physical_leg_distribution.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_access_readiness_decision.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    PRIOR_ACCESS_DIR / "final_cleaned_untyped_access_assignment_detail.csv",
    PRIOR_ACCESS_DIR / "final_cleaned_typed_v2_access_assignment_detail.csv",
    PRIOR_ACCESS_DIR / "final_cleaned_access_product_coverage_summary.csv",
    PRIOR_ACCESS_DIR / "final_access_source_point_accounting.csv",
    PRIOR_ACCESS_DIR / "final_access_rerun_with_source_accounting_manifest.json",
    HYBRID_DIR / "hybrid_access_signal_leg_relation.csv",
    HYBRID_DIR / "hybrid_access_travelway_match_detail.csv",
    HYBRID_DIR / "hybrid_access_manifest.json",
    PRIOR_TRAVELWAY_DIR / "untyped_travelway_normalized_assignment_detail.csv",
    PRIOR_TRAVELWAY_DIR / "typed_v2_travelway_normalized_assignment_detail.csv",
    PRIOR_TRAVELWAY_DIR / "travelway_normalized_access_product_coverage_summary.csv",
    PRIOR_TRAVELWAY_DIR / "travelway_normalized_vs_spatial_comparison.csv",
    PRIOR_TRAVELWAY_DIR / "final_access_travelway_normalization_manifest.json",
    LINEAGE_DIR / "source_travelway_stable_identity.csv",
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
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
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


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = []
    for value in values.dropna().astype(str):
        if value.strip() and value not in items:
            items.append(value)
        if len(items) >= limit:
            break
    return "|".join(items)


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


def _parse_wkt(value: Any):
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    try:
        return wkt.loads(text)
    except Exception:
        return None


def _source_travelway_local_id_to_stable(source_id: Any) -> str:
    text = str(source_id or "")
    match = re.search(r"source_travelway_0*([0-9]+)$", text)
    if not match:
        return ""
    return str(int(match.group(1)) + 1)


def _read_access(path: Path, *, layer: str) -> gpd.GeoDataFrame:
    _checkpoint(f"read_start {path.name}")
    access = gpd.read_parquet(path)
    access = access.drop(columns=[column for column in access.columns if _blocked_column(column)], errors="ignore")
    if access.crs is None:
        access = access.set_crs("EPSG:3968", allow_override=True)
    access = access.to_crs("EPSG:3968")
    if layer == "typed_v2":
        access["access_point_id"] = access.get("access_v2_source_priority", "").astype(str) + ":" + access.get("access_v2_source_row_id", "").astype(str)
        access.loc[access["access_point_id"].eq(":"), "access_point_id"] = access.loc[access["access_point_id"].eq(":"), "id"].astype(str)
        access["route_name"] = access.get("route_name", "").astype(str)
        access["route_measure"] = access.get("route_measure", "").astype(str)
        access["source_dataset"] = access.get("access_v2_source_gdb", "").astype(str)
        access["source_layer"] = access.get("access_v2_source_layer", "").astype(str)
        access["access_control_category"] = access.get("access_control_category", "").astype(str).replace("", "unknown")
        access.loc[~access["access_control_category"].isin(TYPED_CATEGORIES), "access_control_category"] = "other_review"
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["route_name"] = access.get("_rte_nm", "").astype(str)
        access["route_measure"] = access.get("_m", "").astype(str)
        access["source_dataset"] = access.get("Stage1_SourceGDB", "").astype(str)
        access["source_layer"] = access.get("Stage1_SourceLayer", "").astype(str)
        access["access_control_category"] = "untyped"
    access["access_layer"] = layer
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
    ]
    out = access[keep].copy()
    out = out.loc[out["access_point_id"].astype(str).str.strip().ne("")]
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _build_target() -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    target = _read_csv(STABLE_DIR / "stable_lineage_represented_bin_universe.csv")
    target["physical_leg_id"] = _text(target, "physical_leg_id_final")
    target["carriageway_subbranch_id"] = _text(target, "carriageway_subbranch_id_final")
    target["geometry_wkt_final"] = _text(target, "geometry_wkt_cleaned").where(_text(target, "geometry_wkt_cleaned").ne(""), _text(target, "geometry_wkt"))
    target["geometry_available"] = _text(target, "geometry_wkt_final").str.strip().ne("")
    target["distance_length_ft"] = (_num(target, "distance_end_ft") - _num(target, "distance_start_ft")).abs()
    target["distance_length_ft"] = target["distance_length_ft"].where(target["distance_length_ft"].gt(0), 50.0)
    target["candidate_weight_num"] = pd.to_numeric(_text(target, "candidate_weight_num"), errors="coerce").fillna(1.0)
    target["route_key"] = _text(target, "source_route_name").map(_route_key).where(_text(target, "source_route_name").ne(""), _text(target, "route_facility_fields").map(_route_key))
    target["review_only_flag"] = "true"

    geom = target.loc[target["geometry_available"]].copy()
    geom["geometry"] = geom["geometry_wkt_final"].map(_parse_wkt)
    lines = gpd.GeoDataFrame(geom, geometry="geometry", crs="EPSG:3968")
    lines = lines.loc[lines.geometry.notna() & ~lines.geometry.is_empty].copy()
    _checkpoint("stable_target_geometry", len(lines), note=f"signals={_text(lines, 'target_signal_id').nunique():,}")
    return target, lines


def _target_output(target: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "stable_travelway_id",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "geometry_hash",
        "lineage_match_method",
        "lineage_confidence",
        "target_signal_id",
        "target_bin_id",
        "source_signal_layer",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt_final",
        "geometry_available",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "final_alignment_class",
        "final_physical_leg_class",
        "speed_aadt_ready_bin",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "review_only_recovery_provenance",
        "recovery_stream",
        "recovery_class",
        "lineage_persistence_mode",
        "lineage_candidate_match_count",
        "lineage_conflict_fanout_flag",
        "review_only_flag",
    ]
    return target[[col for col in keep if col in target.columns]].copy()


def _assign_spatial_for_width(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str, width_ft: int) -> pd.DataFrame:
    if lines.empty or access.empty:
        return pd.DataFrame()
    line_cols = [
        "stable_travelway_id",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "lineage_match_method",
        "lineage_confidence",
        "target_signal_id",
        "target_bin_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "analysis_window",
        "distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "distance_length_ft",
        "candidate_weight_num",
        "final_alignment_class",
        "final_physical_leg_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
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
    out = out.drop_duplicates(["access_point_id", "stable_bin_id", "access_control_category"])
    fanout = out.groupby("access_point_id", dropna=False)["stable_bin_id"].nunique().rename("assignment_fanout_count").reset_index()
    out = out.merge(fanout, on="access_point_id", how="left")
    out["assignment_fanout_count"] = pd.to_numeric(out["assignment_fanout_count"], errors="coerce").fillna(1.0)
    out["buffer_width_ft"] = width_ft
    out["access_layer"] = layer
    out["assignment_method"] = "spatial_catchment"
    out["multi_assignment_flag"] = out["assignment_fanout_count"].gt(1)
    out["unweighted_access_count"] = 1.0
    out["source_preserving_weighted_access_count"] = 1.0 / out["assignment_fanout_count"]
    out["review_only_flag"] = "true"
    return out


def _assign_spatial(lines: gpd.GeoDataFrame, access: gpd.GeoDataFrame, *, layer: str) -> pd.DataFrame:
    parts = []
    for width in BUFFER_WIDTHS_FT:
        _checkpoint("spatial_assignment_start", note=f"{layer} width_ft={width}")
        parts.append(_assign_spatial_for_width(lines, access, layer=layer, width_ft=width))
    return pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()


def _stable_source_match_table() -> pd.DataFrame:
    source = _read_csv(LINEAGE_DIR / "source_travelway_stable_identity.csv", usecols=["stable_travelway_id", "source_feature_local_fid", "source_route_id", "source_route_name", "source_route_common"])
    hybrid = _read_csv(HYBRID_DIR / "hybrid_access_travelway_match_detail.csv")
    hybrid["source_feature_local_fid"] = _text(hybrid, "source_travelway_id").map(_source_travelway_local_id_to_stable)
    out = hybrid.merge(source, on="source_feature_local_fid", how="left", suffixes=("", "_stable"))
    out["source_stable_travelway_id"] = _text(out, "stable_travelway_id")
    out["access_source_route_key"] = _text(out, "RTE_NM").map(_route_key).where(_text(out, "RTE_NM").ne(""), _text(out, "RTE_COMMON").map(_route_key))
    return out.drop(columns=["stable_travelway_id"], errors="ignore")


def _quality(row: pd.Series) -> str:
    if str(row.get("grade_mainline_holdout_flag", "")).lower() == "true":
        return "blocked_grade_or_mainline"
    if str(row.get("source_limited_holdout_flag", "")).lower() == "true" or str(row.get("still_insufficient_evidence_flag", "")).lower() == "true":
        return "manual_review_needed"
    if str(row.get("source_stable_travelway_id", "")) and str(row.get("source_stable_travelway_id", "")) == str(row.get("stable_travelway_id", "")):
        return "high_confidence_source_travelway_match"
    if str(row.get("lineage_confidence", "")).startswith("high") and "matches" in str(row.get("route_facility_compatibility", "")):
        return "medium_confidence_route_facility_match"
    if str(row.get("source_travelway_route_represented_flag", "")).lower() == "true":
        return "low_confidence_route_family_only"
    return "manual_review_needed"


def _build_travelway_assignments(target: pd.DataFrame, layer: str) -> pd.DataFrame:
    relation = _read_csv(HYBRID_DIR / "hybrid_access_signal_leg_relation.csv")
    relation = relation.loc[_text(relation, "access_layer").eq(layer)].copy()
    source_match = _stable_source_match_table()
    relation = relation.merge(
        source_match[
            [
                col
                for col in [
                    "access_point_id",
                    "access_layer",
                    "source_stable_travelway_id",
                    "source_feature_local_fid",
                    "source_route_id",
                    "source_route_name",
                    "source_route_common",
                    "source_travelway_match_method",
                    "source_travelway_match_confidence",
                    "source_travelway_match_distance_ft",
                    "route_facility_compatibility",
                ]
                if col in source_match.columns
            ]
        ],
        on=["access_point_id", "access_layer"],
        how="left",
        suffixes=("", "_source_match"),
    )
    target_keep = target[
        [
            col
            for col in [
                "target_bin_id",
                "stable_bin_id",
                "stable_travelway_id",
                "stable_signal_id",
                "source_signal_id",
                "source_route_id",
                "source_route_name",
                "source_route_common",
                "source_measure_start",
                "source_measure_end",
                "lineage_match_method",
                "lineage_confidence",
                "physical_leg_id",
                "carriageway_subbranch_id",
                "distance_start_ft",
                "distance_end_ft",
                "distance_band",
                "analysis_window",
                "final_alignment_class",
                "final_physical_leg_class",
                "source_limited_holdout_flag",
                "grade_mainline_holdout_flag",
                "still_insufficient_evidence_flag",
                "speed_aadt_ready_bin",
                "review_only_recovery_provenance",
            ]
            if col in target.columns
        ]
    ].drop_duplicates("target_bin_id")
    relation = relation.merge(target_keep, on="target_bin_id", how="left", suffixes=("", "_target"))
    direct = _text(relation, "source_stable_travelway_id").ne("") & _text(relation, "source_stable_travelway_id").eq(_text(relation, "stable_travelway_id"))
    route_compatible = _text(relation, "route_facility_compatibility").str.contains("match", case=False, regex=False)
    route_measure = pd.to_numeric(_text(relation, "route_measure"), errors="coerce")
    source_measure_start = pd.to_numeric(_text(relation, "source_measure_start"), errors="coerce")
    source_measure_end = pd.to_numeric(_text(relation, "source_measure_end"), errors="coerce")
    min_measure = np.minimum(source_measure_start, source_measure_end)
    max_measure = np.maximum(source_measure_start, source_measure_end)
    route_measure_overlap = route_compatible & route_measure.notna() & min_measure.notna() & max_measure.notna() & route_measure.between(min_measure, max_measure)
    relation["stable_travelway_assignment_match_class"] = np.select(
        [
            direct,
            route_measure_overlap,
            route_compatible,
            _bool_text(relation, "captured_100ft"),
        ],
        [
            "direct_stable_travelway_id",
            "route_measure_overlap",
            "route_facility_compatible",
            "spatial_catchment_only",
        ],
        default="unmatched_or_out_of_scope",
    )
    relation["route_normalized_quality_class"] = relation.apply(_quality, axis=1)
    relation["route_normalized_assignment_status"] = np.where(
        relation["stable_travelway_assignment_match_class"].isin(["direct_stable_travelway_id", "route_measure_overlap", "route_facility_compatible"])
        & relation["route_normalized_quality_class"].isin(["high_confidence_source_travelway_match", "medium_confidence_route_facility_match", "low_confidence_route_family_only"]),
        "assigned_review_only",
        "blocked_review_only",
    )
    assigned = relation.loc[relation["route_normalized_assignment_status"].eq("assigned_review_only")].copy()
    fanout = assigned.groupby("access_point_id", dropna=False)["stable_bin_id"].nunique().rename("route_normalized_fanout_count").reset_index()
    relation = relation.merge(fanout, on="access_point_id", how="left")
    relation["route_normalized_fanout_count"] = pd.to_numeric(relation["route_normalized_fanout_count"], errors="coerce").fillna(0)
    relation["unweighted_access_count"] = np.where(relation["route_normalized_assignment_status"].eq("assigned_review_only"), 1.0, 0.0)
    relation["source_preserving_weighted_access_count"] = np.where(
        relation["route_normalized_assignment_status"].eq("assigned_review_only") & relation["route_normalized_fanout_count"].gt(0),
        1.0 / relation["route_normalized_fanout_count"],
        0.0,
    )
    relation["review_only_flag"] = "true"
    keep = [
        "access_point_id",
        "access_layer",
        "access_control_category",
        "route_name",
        "route_measure",
        "route_key",
        "source_layer",
        "target_signal_id",
        "target_bin_id",
        "stable_bin_id",
        "stable_signal_id",
        "stable_travelway_id",
        "source_stable_travelway_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "analysis_window",
        "distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "source_travelway_id",
        "source_feature_local_fid",
        "source_travelway_match_distance_ft",
        "source_travelway_match_method",
        "source_travelway_match_confidence",
        "route_facility_compatibility",
        "source_measure_start",
        "source_measure_end",
        "stable_travelway_assignment_match_class",
        "route_normalized_assignment_status",
        "route_normalized_quality_class",
        "route_normalized_fanout_count",
        "unweighted_access_count",
        "source_preserving_weighted_access_count",
        "lineage_match_method",
        "lineage_confidence",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "speed_aadt_ready_bin",
        "review_only_flag",
    ]
    return relation[[col for col in keep if col in relation.columns]].copy()


def _assigned(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[_text(frame, "route_normalized_assignment_status").eq("assigned_review_only")].copy()


def _spatial_coverage(untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        for width in BUFFER_WIDTHS_FT:
            sub = frame.loc[pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(width)] if not frame.empty else pd.DataFrame()
            rows.extend(
                [
                    {"product": "spatial", "access_layer": layer, "window": "any", "buffer_width_ft": width, "metric": "signals_with_access", "count": int(_text(sub, "target_signal_id").nunique()) if not sub.empty else 0},
                    {"product": "spatial", "access_layer": layer, "window": "0_1000", "buffer_width_ft": width, "metric": "signals_with_access", "count": int(_text(sub.loc[_text(sub, "analysis_window").eq("0_1000")], "target_signal_id").nunique()) if not sub.empty else 0},
                    {"product": "spatial", "access_layer": layer, "window": "any", "buffer_width_ft": width, "metric": "source_points_captured", "count": int(_text(sub, "access_point_id").nunique()) if not sub.empty else 0},
                    {"product": "spatial", "access_layer": layer, "window": "any", "buffer_width_ft": width, "metric": "assignment_rows", "count": int(len(sub)) if not sub.empty else 0},
                    {"product": "spatial", "access_layer": layer, "window": "any", "buffer_width_ft": width, "metric": "weighted_assignment_total", "count": round(float(pd.to_numeric(sub.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6) if not sub.empty else 0},
                ]
            )
    return pd.DataFrame(rows)


def _travelway_coverage(untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        assigned = _assigned(frame)
        for window in ["any", "0_1000", "1000_2500"]:
            sub = assigned if window == "any" else assigned.loc[_text(assigned, "analysis_window").eq(window)]
            rows.extend(
                [
                    {"product": "travelway_normalized", "access_layer": layer, "window": window, "buffer_width_ft": "", "metric": "signals_with_access", "count": int(_text(sub, "target_signal_id").nunique())},
                    {"product": "travelway_normalized", "access_layer": layer, "window": window, "buffer_width_ft": "", "metric": "source_points_captured", "count": int(_text(sub, "access_point_id").nunique())},
                    {"product": "travelway_normalized", "access_layer": layer, "window": window, "buffer_width_ft": "", "metric": "assignment_rows", "count": int(len(sub))},
                    {"product": "travelway_normalized", "access_layer": layer, "window": window, "buffer_width_ft": "", "metric": "weighted_assignment_total", "count": round(float(pd.to_numeric(sub.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6)},
                ]
            )
    return pd.DataFrame(rows)


def _signal_window_summary(spatial: pd.DataFrame, travelway: pd.DataFrame, layer: str) -> pd.DataFrame:
    rows = []
    spatial_100 = spatial.loc[pd.to_numeric(spatial.get("buffer_width_ft"), errors="coerce").eq(SPATIAL_BASELINE_WIDTH_FT)].copy()
    if not spatial_100.empty:
        s = spatial_100.groupby(["target_signal_id", "analysis_window"], dropna=False).agg(
            spatial_source_points=("access_point_id", "nunique"),
            spatial_assignment_rows=("access_point_id", "size"),
            spatial_weighted_total=("source_preserving_weighted_access_count", "sum"),
            final_alignment_class=("final_alignment_class", "first"),
        ).reset_index()
        s["access_layer"] = layer
        s["product"] = "spatial_100ft"
        rows.append(s)
    assigned = _assigned(travelway)
    if not assigned.empty:
        t = assigned.groupby(["target_signal_id", "analysis_window"], dropna=False).agg(
            travelway_source_points=("access_point_id", "nunique"),
            travelway_assignment_rows=("access_point_id", "size"),
            travelway_weighted_total=("source_preserving_weighted_access_count", "sum"),
            final_alignment_class=("final_alignment_class", "first"),
        ).reset_index()
        t["access_layer"] = layer
        t["product"] = "travelway_normalized"
        rows.append(t)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _source_accounting(access: gpd.GeoDataFrame, spatial: pd.DataFrame, travelway: pd.DataFrame, target: pd.DataFrame, layer: str) -> pd.DataFrame:
    source_points = set(_text(access, "access_point_id"))
    target_stable = {value for value in _text(target, "stable_travelway_id") if value}
    tw_assigned = _assigned(travelway)
    spatial_by_width = {
        width: set(_text(spatial.loc[pd.to_numeric(spatial.get("buffer_width_ft"), errors="coerce").eq(width)], "access_point_id")) if not spatial.empty else set()
        for width in BUFFER_WIDTHS_FT
    }
    tw_points = set(_text(tw_assigned, "access_point_id"))
    source_match = _stable_source_match_table()
    layer_match = source_match.loc[_text(source_match, "access_layer").eq(layer)].copy()
    on_represented = set(_text(layer_match.loc[_text(layer_match, "source_stable_travelway_id").isin(target_stable)], "access_point_id"))
    rows = []
    for width in BUFFER_WIDTHS_FT:
        spatial_points = spatial_by_width[width]
        rows.append(
            {
                "access_layer": layer,
                "buffer_width_ft": width,
                "total_source_points": len(source_points),
                "source_points_with_geometry": int(access["has_geometry"].sum()),
                "spatial_captured_source_points": len(spatial_points),
                "travelway_captured_source_points": len(tw_points),
                "captured_by_both": len(spatial_points & tw_points),
                "captured_by_spatial_only": len(spatial_points - tw_points),
                "captured_by_travelway_only": len(tw_points - spatial_points),
                "uncaptured_by_either": len(source_points - (spatial_points | tw_points)),
                "uncaptured_but_on_represented_stable_travelway_ids": len((source_points - (spatial_points | tw_points)) & on_represented),
                "uncaptured_on_travelway_not_represented": len((source_points - (spatial_points | tw_points)) - on_represented),
                "outside_signal_relevant_scope_estimate": len((source_points - (spatial_points | tw_points)) - on_represented),
            }
        )
    return pd.DataFrame(rows)


def _spatial_vs_travelway(untyped_spatial: pd.DataFrame, typed_spatial: pd.DataFrame, untyped_tw: pd.DataFrame, typed_tw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer, spatial, tw in [("untyped", untyped_spatial, untyped_tw), ("typed_v2", typed_spatial, typed_tw)]:
        spatial_100 = spatial.loc[pd.to_numeric(spatial.get("buffer_width_ft"), errors="coerce").eq(SPATIAL_BASELINE_WIDTH_FT)] if not spatial.empty else pd.DataFrame()
        tw_assigned = _assigned(tw)
        sp_points = set(_text(spatial_100, "access_point_id"))
        tw_points = set(_text(tw_assigned, "access_point_id"))
        sp_signals = set(_text(spatial_100, "target_signal_id"))
        tw_signals = set(_text(tw_assigned, "target_signal_id"))
        rows.extend(
            [
                {"access_layer": layer, "comparison_metric": "source_points_spatial_only", "count": len(sp_points - tw_points)},
                {"access_layer": layer, "comparison_metric": "source_points_travelway_only", "count": len(tw_points - sp_points)},
                {"access_layer": layer, "comparison_metric": "source_points_both", "count": len(sp_points & tw_points)},
                {"access_layer": layer, "comparison_metric": "signals_spatial_only", "count": len(sp_signals - tw_signals)},
                {"access_layer": layer, "comparison_metric": "signals_travelway_only", "count": len(tw_signals - sp_signals)},
                {"access_layer": layer, "comparison_metric": "signals_both", "count": len(sp_signals & tw_signals)},
            ]
        )
    return pd.DataFrame(rows)


def _by_scaffold_qa(spatial: pd.DataFrame, travelway: pd.DataFrame, layer: str) -> pd.DataFrame:
    frames = []
    spatial_100 = spatial.loc[pd.to_numeric(spatial.get("buffer_width_ft"), errors="coerce").eq(SPATIAL_BASELINE_WIDTH_FT)].copy() if not spatial.empty else pd.DataFrame()
    tw_assigned = _assigned(travelway)
    for product, frame in [("spatial_100ft", spatial_100), ("travelway_normalized", tw_assigned)]:
        if frame.empty:
            continue
        for field in ["final_alignment_class", "source_limited_holdout_flag", "grade_mainline_holdout_flag", "still_insufficient_evidence_flag", "final_physical_leg_class", "physical_leg_id", "carriageway_subbranch_id", "lineage_confidence"]:
            if field not in frame.columns:
                continue
            grouped = frame.groupby(field, dropna=False).agg(
                signal_count=("target_signal_id", "nunique"),
                source_point_count=("access_point_id", "nunique"),
                assignment_count=("access_point_id", "size"),
                weighted_assignment_total=("source_preserving_weighted_access_count", "sum"),
            ).reset_index().rename(columns={field: "qa_value"})
            grouped["qa_field"] = field
            grouped["access_layer"] = layer
            grouped["product"] = product
            frames.append(grouped)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _prior_metric(frame: pd.DataFrame, layer: str, metric: str, width: int | None = None, window: str | None = None) -> float:
    if frame.empty:
        return np.nan
    sub = frame.loc[_text(frame, "access_layer").eq(layer)]
    if width is not None and "buffer_width_ft" in sub.columns:
        sub = sub.loc[pd.to_numeric(sub["buffer_width_ft"], errors="coerce").eq(width)]
    if window is not None:
        if "window" in sub.columns:
            sub = sub.loc[_text(sub, "window").eq(window)]
        elif "analysis_window" in sub.columns:
            sub = sub.loc[_text(sub, "analysis_window").eq(window)]
    if "metric" in sub.columns:
        sub = sub.loc[_text(sub, "metric").eq(metric)]
        col = "count"
    elif "comparison_metric" in sub.columns:
        sub = sub.loc[_text(sub, "comparison_metric").eq(metric)]
        col = "count"
    else:
        return np.nan
    return float(sub[col].iloc[0]) if not sub.empty else np.nan


def _prior_comparison(coverage: pd.DataFrame) -> pd.DataFrame:
    prior_spatial = _read_csv(PRIOR_ACCESS_DIR / "final_cleaned_access_product_coverage_summary.csv")
    prior_tw = _read_csv(PRIOR_TRAVELWAY_DIR / "travelway_normalized_access_product_coverage_summary.csv")
    rows = []
    for layer in ["untyped", "typed_v2"]:
        for width in BUFFER_WIDTHS_FT:
            new_spatial = _prior_metric(coverage.loc[coverage["product"].eq("spatial")], layer, "signals_with_access", width=width, window="any")
            old_spatial = _prior_metric(prior_spatial, layer, "signals_with_access", width=width)
            rows.append(
                {
                    "access_layer": layer,
                    "product": "spatial",
                    "buffer_width_ft": width,
                    "prior_signal_coverage": old_spatial,
                    "stable_lineage_signal_coverage": new_spatial,
                    "signal_coverage_delta": new_spatial - old_spatial if np.isfinite(old_spatial) and np.isfinite(new_spatial) else "",
                }
            )
        new_tw = _prior_metric(coverage.loc[coverage["product"].eq("travelway_normalized")], layer, "signals_with_access", window="any")
        old_tw = _prior_metric(prior_tw, layer, "signals_with_access", window="any")
        rows.append(
            {
                "access_layer": layer,
                "product": "travelway_normalized",
                "buffer_width_ft": "",
                "prior_signal_coverage": old_tw,
                "stable_lineage_signal_coverage": new_tw,
                "signal_coverage_delta": new_tw - old_tw if np.isfinite(old_tw) and np.isfinite(new_tw) else "",
            }
        )
    return pd.DataFrame(rows)


def _target_validation(target: pd.DataFrame) -> pd.DataFrame:
    required = [
        "stable_travelway_id",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "geometry_hash",
        "lineage_match_method",
        "lineage_confidence",
    ]
    rows = [
        {"metric": "target_signals", "count": int(_text(target, "target_signal_id").nunique())},
        {"metric": "target_bins", "count": int(len(target))},
        {"metric": "bins_with_geometry", "count": int(target["geometry_available"].sum())},
        {"metric": "high_confidence_stable_lineage_bins", "count": int(_text(target, "lineage_confidence").str.startswith("high").sum())},
        {"metric": "low_confidence_stable_lineage_bins", "count": int(_text(target, "lineage_confidence").str.startswith("low").sum())},
        {"metric": "unmatched_lineage_bins", "count": int(_text(target, "lineage_confidence").eq("unmatched").sum())},
    ]
    for field in required:
        rows.append({"metric": f"missing_required_field_{field}", "count": int(_text(target, field).str.strip().eq("").sum())})
    return pd.DataFrame(rows)


def _qa(target: pd.DataFrame, spatial: pd.DataFrame, travelway: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to stable_lineage_final_access_rerun review folder."),
            ("no_candidates_promoted", True, "No promotion outputs are written."),
            ("no_crash_records_read", True, "No crash files are read."),
            ("no_crash_direction_fields_read_or_used", True, "CSV/parquet readers drop/block crash field tokens."),
            ("no_crash_assignment_or_catchments", True, "No crash assignment/catchment outputs are produced."),
            ("no_rates_or_models", True, "No rate/model calculations are performed."),
            ("typed_and_untyped_separate", True, "Separate typed v2 and untyped outputs are written."),
            ("weighted_and_unweighted_separate", {"unweighted_access_count", "source_preserving_weighted_access_count"}.issubset(spatial.columns) and {"unweighted_access_count", "source_preserving_weighted_access_count"}.issubset(travelway.columns), "Both assignment families carry separate count fields."),
            ("stable_travelway_id_carried", "stable_travelway_id" in target.columns and "stable_travelway_id" in spatial.columns and "stable_travelway_id" in travelway.columns, "Stable lineage is present in target and assignment outputs."),
            ("source_point_counts_separate_from_assignment_counts", True, "Source accounting table separates source points from assignment rows."),
            ("outputs_review_only", True, "All outputs are review-only."),
        ],
        columns=["qa_check", "passed", "detail"],
    )


def _findings(target: pd.DataFrame, coverage: pd.DataFrame, accounting: pd.DataFrame, comparison: pd.DataFrame) -> str:
    def metric(product: str, layer: str, metric_name: str, width: int | None = None, window: str = "any") -> int:
        sub = coverage.loc[(coverage["product"].eq(product)) & (coverage["access_layer"].eq(layer)) & (coverage["metric"].eq(metric_name)) & (coverage["window"].eq(window))]
        if width is not None:
            sub = sub.loc[pd.to_numeric(sub["buffer_width_ft"], errors="coerce").eq(width)]
        return int(float(sub["count"].iloc[0])) if not sub.empty else 0

    def acct(layer: str, field: str) -> int:
        sub = accounting.loc[accounting["access_layer"].eq(layer) & accounting["buffer_width_ft"].eq(SPATIAL_BASELINE_WIDTH_FT)]
        return int(sub[field].iloc[0]) if not sub.empty else 0

    def spatial_lines(layer: str) -> str:
        return "\n".join(f"- {width} ft: {metric('spatial', layer, 'signals_with_access', width):,} signals" for width in BUFFER_WIDTHS_FT)

    comp_lines = "\n".join(
        f"- {row.access_layer} {row.product} {row.buffer_width_ft}: prior {row.prior_signal_coverage}, stable-lineage {row.stable_lineage_signal_coverage}, delta {row.signal_coverage_delta}"
        for row in comparison.itertuples(index=False)
    )
    return f"""# Stable-Lineage Final Access Rerun Findings

## Bounded Question

Rebuild the final access target from the stable-lineage represented bin universe and rerun review-only spatial and Travelway-normalized access products with native `stable_travelway_id` carried into target and assignment outputs.

## Target Validation

- Target signals: {int(_text(target, 'target_signal_id').nunique()):,}
- Target bins: {len(target):,}
- Bins with geometry: {int(target['geometry_available'].sum()):,}
- High-confidence stable Travelway lineage bins: {int(_text(target, 'lineage_confidence').str.startswith('high').sum()):,}
- Low-confidence bins: {int(_text(target, 'lineage_confidence').str.startswith('low').sum()):,}
- Unmatched lineage bins: {int(_text(target, 'lineage_confidence').eq('unmatched').sum()):,}

## Spatial Access Coverage

Untyped:
{spatial_lines('untyped')}

Typed v2:
{spatial_lines('typed_v2')}

## Stable Travelway-Normalized Coverage

- Untyped source points captured by stable Travelway-normalized assignment: {metric('travelway_normalized', 'untyped', 'source_points_captured'):,}
- Typed v2 source points captured by stable Travelway-normalized assignment: {metric('travelway_normalized', 'typed_v2', 'source_points_captured'):,}
- Untyped signals with stable Travelway-normalized access: {metric('travelway_normalized', 'untyped', 'signals_with_access'):,}
- Typed v2 signals with stable Travelway-normalized access: {metric('travelway_normalized', 'typed_v2', 'signals_with_access'):,}

## Source-Point Accounting At 100 ft Baseline

- Untyped captured by spatial only: {acct('untyped', 'captured_by_spatial_only'):,}
- Untyped captured by Travelway only: {acct('untyped', 'captured_by_travelway_only'):,}
- Untyped uncaptured by either but on represented stable Travelway IDs: {acct('untyped', 'uncaptured_but_on_represented_stable_travelway_ids'):,}
- Typed v2 captured by spatial only: {acct('typed_v2', 'captured_by_spatial_only'):,}
- Typed v2 captured by Travelway only: {acct('typed_v2', 'captured_by_travelway_only'):,}
- Typed v2 uncaptured by either but on represented stable Travelway IDs: {acct('typed_v2', 'uncaptured_but_on_represented_stable_travelway_ids'):,}

## Prior Comparison

{comp_lines}

## Interpretation

Stable Travelway lineage materially improves interpretability because assignments can now cite native stable source Travelway IDs rather than retrospective best-effort lineage. Coverage changes should be interpreted cautiously because the Travelway-normalized product remains a review-only assignment test with fanout and confidence controls.

## Recommendation

Carry the stable-lineage access target and assignment products forward as review-only context products. The next bounded access step should refine Travelway-normalized confidence/fanout and decide whether source points on represented stable Travelway IDs but uncaptured by either product are assignment limitations or source/scope limitations. Do not choose a final primary access metric yet.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    started = datetime.now(timezone.utc)
    _checkpoint("run_start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    target, lines = _build_target()
    target_out = _target_output(target)
    untyped_access = _read_access(ACCESS_V1_FILE, layer="untyped")
    typed_access = _read_access(ACCESS_V2_FILE, layer="typed_v2")
    untyped_spatial = _assign_spatial(lines, untyped_access, layer="untyped")
    typed_spatial = _assign_spatial(lines, typed_access, layer="typed_v2")
    untyped_tw = _build_travelway_assignments(target, "untyped")
    typed_tw = _build_travelway_assignments(target, "typed_v2")
    spatial_summary = _spatial_coverage(untyped_spatial, typed_spatial)
    tw_summary = _travelway_coverage(untyped_tw, typed_tw)
    coverage = pd.concat([spatial_summary, tw_summary], ignore_index=True, sort=False)
    signal_window = pd.concat(
        [
            _signal_window_summary(untyped_spatial, untyped_tw, "untyped"),
            _signal_window_summary(typed_spatial, typed_tw, "typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    accounting = pd.concat(
        [
            _source_accounting(untyped_access, untyped_spatial, untyped_tw, target, "untyped"),
            _source_accounting(typed_access, typed_spatial, typed_tw, target, "typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    spatial_vs_tw = _spatial_vs_travelway(untyped_spatial, typed_spatial, untyped_tw, typed_tw)
    scaffold_qa = pd.concat(
        [
            _by_scaffold_qa(untyped_spatial, untyped_tw, "untyped"),
            _by_scaffold_qa(typed_spatial, typed_tw, "typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    prior = _prior_comparison(coverage)
    validation = _target_validation(target)
    qa = _qa(target_out, pd.concat([untyped_spatial, typed_spatial], ignore_index=True, sort=False), pd.concat([untyped_tw, typed_tw], ignore_index=True, sort=False))

    outputs = {
        "stable_lineage_final_access_target_bins.csv": target_out,
        "stable_lineage_untyped_spatial_assignment_detail.csv": untyped_spatial,
        "stable_lineage_typed_v2_spatial_assignment_detail.csv": typed_spatial,
        "stable_lineage_untyped_travelway_assignment_detail.csv": untyped_tw,
        "stable_lineage_typed_v2_travelway_assignment_detail.csv": typed_tw,
        "stable_lineage_access_signal_window_summary.csv": signal_window,
        "stable_lineage_access_product_coverage_summary.csv": coverage,
        "stable_lineage_access_source_point_accounting.csv": accounting,
        "stable_lineage_access_spatial_vs_travelway_comparison.csv": spatial_vs_tw,
        "stable_lineage_access_by_scaffold_qa_summary.csv": scaffold_qa,
        "stable_lineage_access_vs_prior_comparison.csv": prior,
        "stable_lineage_final_access_target_validation.csv": validation,
        "stable_lineage_final_access_rerun_qa.csv": qa,
    }
    for name, frame in outputs.items():
        _write_csv(frame, name)
    _write_text(_findings(target, coverage, accounting, prior), "stable_lineage_final_access_rerun_findings.md")

    manifest = {
        "created_at_utc": _now(),
        "started_at_utc": started.isoformat(),
        "script": "src.roadway_graph.stable_lineage_final_access_rerun",
        "bounded_question": "Review-only final access target rebuild and spatial/Travelway access rerun from stable-lineage represented bins.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "stable_lineage_scaffold_regeneration": str(STABLE_DIR),
            "final_signal_leg_universe_overview": str(FINAL_OVERVIEW_DIR),
            "prior_final_access": str(PRIOR_ACCESS_DIR),
            "hybrid_access_diagnostic": str(HYBRID_DIR),
            "prior_travelway_normalization_test": str(PRIOR_TRAVELWAY_DIR),
            "stable_generation_manifest": _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json"),
        },
        "metrics": {
            "target_signals": int(_text(target, "target_signal_id").nunique()),
            "target_bins": int(len(target)),
            "target_bins_with_geometry": int(target["geometry_available"].sum()),
            "high_confidence_stable_lineage_bins": int(_text(target, "lineage_confidence").str.startswith("high").sum()),
            "low_confidence_stable_lineage_bins": int(_text(target, "lineage_confidence").str.startswith("low").sum()),
            "unmatched_lineage_bins": int(_text(target, "lineage_confidence").eq("unmatched").sum()),
            "untyped_spatial_assignment_rows": int(len(untyped_spatial)),
            "typed_v2_spatial_assignment_rows": int(len(typed_spatial)),
            "untyped_travelway_candidate_rows": int(len(untyped_tw)),
            "typed_v2_travelway_candidate_rows": int(len(typed_tw)),
            "untyped_travelway_assigned_source_points": int(_text(_assigned(untyped_tw), "access_point_id").nunique()),
            "typed_v2_travelway_assigned_source_points": int(_text(_assigned(typed_tw), "access_point_id").nunique()),
        },
        "outputs": list(outputs) + ["stable_lineage_final_access_rerun_findings.md", "stable_lineage_final_access_rerun_manifest.json", "run_progress_log.txt"],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_direction_fields_read": False,
            "crash_assignment_or_catchments": False,
            "rates_or_models": False,
            "final_primary_access_metric_chosen": False,
        },
    }
    _write_json(manifest, "stable_lineage_final_access_rerun_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
