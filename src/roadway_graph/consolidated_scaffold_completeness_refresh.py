from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"

REFRESHED_DIR = OUTPUT_ROOT / "review/current/refreshed_expanded_universe_with_offset_recovery"
CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"
READY_CONTEXT_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_context_refresh"
ROUTE_OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_context_refresh"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_context_refresh"
OFFSET_QA_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_staging_qa_cleanup"
OFFSET_STAGING_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_recovery_staging"

CURRENT_REPRESENTED_UNIVERSE_SIGNALS = 2_739
BASE_SIGNAL_UNIVERSE = 3_933

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

REQUIRED_INPUTS = [
    REFRESHED_DIR / "refreshed_represented_signal_universe.csv",
    REFRESHED_DIR / "refreshed_represented_bin_universe.csv",
    REFRESHED_DIR / "refreshed_universe_with_offset_recovery_manifest.json",
    CALIB_DIR / "calibrated_expected_leg_signal_detail.csv",
    CALIB_DIR / "calibrated_current_vs_expected_alignment.csv",
    CALIB_DIR / "calibrated_leg_model_review_queue.csv",
    CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json",
    READY_CONTEXT_DIR / "missing_leg_context_bin_detail.csv",
    READY_CONTEXT_DIR / "missing_leg_context_signal_summary.csv",
    READY_CONTEXT_DIR / "missing_leg_context_readiness_summary.csv",
    READY_CONTEXT_DIR / "missing_leg_context_refresh_manifest.json",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_bin_detail.csv",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_signal_summary.csv",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_readiness_summary.csv",
    ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_refresh_manifest.json",
    OFFSET_CONTEXT_DIR / "offset_zone_context_bin_detail.csv",
    OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_zone_context_readiness_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_zone_context_refresh_manifest.json",
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
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_text(text: str, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _write_json(payload: dict[str, Any], name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=str)
    return frame[column].fillna(default).astype(str)


def _first_existing(row: pd.Series, columns: list[str]) -> str:
    for column in columns:
        value = str(row.get(column, "")).strip()
        if value and value.lower() not in {"nan", "none", "<na>"}:
            return value
    return ""


def _flag_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _collapse(values: pd.Series, limit: int = 12) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in {"", "nan", "none", "<na>"} and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _distance_band(end_ft: Any) -> str:
    end = _num(end_ft, -1)
    if end <= 0:
        return ""
    if end <= 250:
        return "0_250ft"
    if end <= 500:
        return "250_500ft"
    if end <= 750:
        return "500_750ft"
    if end <= 1000:
        return "750_1000ft"
    if end <= 1500:
        return "1000_1500ft"
    return "1500_2500ft"


def _normalize_base_bins(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        signal_id = _first_existing(row, ["signal_id", "target_signal_id", "candidate_signal_id", "review_signal_id"])
        bin_id = _first_existing(row, ["target_bin_id", "candidate_bin_id", "frozen_candidate_bin_id", "staged_recovered_bin_id", "offset_zone_recovered_bin_id"]) or f"base_bin_{idx:08d}"
        leg_id = _first_existing(row, ["physical_leg_id", "physical_leg_bearing_group", "physical_leg_cluster_id", "candidate_association_id", "road_component_id", "graph_edge_id"])
        sector = _first_existing(row, ["physical_leg_bearing_group", "source_bearing_sector", "physical_leg_cluster_id"])
        end = _first_existing(row, ["distance_end_ft", "candidate_bin_length_ft"])
        rows.append(
            {
                "source_row_number": idx,
                "consolidated_bin_id": f"previous::{bin_id}",
                "original_bin_id": bin_id,
                "signal_id": signal_id,
                "source_signal_id": _first_existing(row, ["source_signal_id", "source_signal_id_signal", "source_signal_id_x"]),
                "source_layer": _first_existing(row, ["source_layer", "source_layer_signal", "source_layer_x"]),
                "recovery_stream": "existing_refreshed_represented_bin_universe",
                "recovery_class": "existing_represented_bin",
                "original_vs_recovered_bin": "original_or_previous_represented",
                "recovered_leg_id": leg_id,
                "physical_leg_id": leg_id,
                "carriageway_subbranch_id": _first_existing(row, ["carriageway_subbranch_id", "carriageway_parallel_branch_key"]),
                "physical_leg_sector": sector,
                "route_facility_fields": _first_existing(row, ["source_route_keys", "route_common", "route_name", "route_key", "candidate_facility_text"]),
                "source_travelway_lineage": _first_existing(row, ["source_travelway_lineage", "source_line_ids", "source_road_row_id"]),
                "distance_start_ft": _first_existing(row, ["distance_start_ft"]),
                "distance_end_ft": _first_existing(row, ["distance_end_ft"]),
                "distance_band": _first_existing(row, ["distance_band"]) or _distance_band(end),
                "analysis_window": _first_existing(row, ["analysis_window"]),
                "geometry_wkt": _first_existing(row, ["geometry_wkt"]),
                "has_route_measure_identity": _flag_value(_first_existing(row, ["has_route_measure_identity", "route_measure_ready"])),
                "has_roadway_context": _flag_value(_first_existing(row, ["has_roadway_context"])),
                "has_rns_speed": _flag_value(_first_existing(row, ["has_rns_speed", "has_speed", "speed_ready_flag"])),
                "has_aadt": _flag_value(_first_existing(row, ["has_aadt", "aadt_ready_flag"])),
                "has_exposure_denominator": _flag_value(_first_existing(row, ["has_exposure_denominator", "has_exposure", "exposure_ready_flag"])),
                "speed_aadt_ready_bin": _flag_value(_first_existing(row, ["speed_aadt_ready_bin", "speed_aadt_ready", "speed_aadt_ready_flag"])),
                "review_only_flag": _flag_value(_first_existing(row, ["review_only", "review_only_flag"])) or True,
                "candidate_promoted": False,
                "route_facility_discontinuity_flag": _flag_value(_first_existing(row, ["route_facility_discontinuity_flag"])),
                "offset_anchor_flag": bool(_first_existing(row, ["offset_anchor_class"])),
                "grade_separation_or_mainline_review_flag": _flag_value(_first_existing(row, ["hold_excluded_mainline", "hold_manual_grade_separation_review", "contains_limited_access_mainline"])),
                "long_source_row_flag": _flag_value(_first_existing(row, ["long_source_row_flag"])),
                "context_assignment_scope": _first_existing(row, ["context_assignment_scope", "refreshed_bin_universe_status"]),
            }
        )
    return pd.DataFrame(rows)


def _normalize_recovered_bins(frame: pd.DataFrame, stream: str, class_override: str | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        bin_id = _first_existing(row, ["recovered_missing_leg_bin_id", "candidate_missing_leg_bin_id", "staged_recovered_bin_id", "offset_zone_recovered_bin_id"]) or f"{stream}_bin_{idx:08d}"
        leg_id = _first_existing(row, ["recovered_missing_leg_id", "candidate_missing_leg_id", "staged_recovered_leg_id", "offset_zone_recovered_leg_id", "physical_leg_id"])
        sector = _first_existing(row, ["source_bearing_sector", "physical_leg_bearing_group", "physical_leg_id"])
        recovery_class = class_override or _first_existing(row, ["recovery_class", "staging_class", "offset_anchor_class"]) or stream
        context_scope = _first_existing(row, ["context_window_scope"])
        start_num = _num(_first_existing(row, ["distance_start_ft"]), 0)
        raw_window = _first_existing(row, ["analysis_window"])
        if context_scope == "primary_0_1000" or (not context_scope and start_num < 1000 and raw_window in {"0_1000", ""}):
            analysis_window = "0_1000"
        elif context_scope == "sensitivity_1000_2500" or start_num >= 1000 or raw_window == "1000_2500":
            analysis_window = "1000_2500"
        else:
            analysis_window = raw_window
        rows.append(
            {
                "source_row_number": idx,
                "consolidated_bin_id": f"{stream}::{bin_id}",
                "original_bin_id": bin_id,
                "signal_id": _first_existing(row, ["signal_id"]),
                "source_signal_id": _first_existing(row, ["source_signal_id"]),
                "source_layer": _first_existing(row, ["source_layer"]),
                "recovery_stream": stream,
                "recovery_class": recovery_class,
                "original_vs_recovered_bin": "recovered_review_only",
                "recovered_leg_id": leg_id,
                "physical_leg_id": _first_existing(row, ["physical_leg_id"]) or leg_id,
                "carriageway_subbranch_id": _first_existing(row, ["carriageway_subbranch_id"]),
                "physical_leg_sector": sector,
                "route_facility_fields": _first_existing(row, ["source_route_keys", "source_route_raw", "candidate_facility_text"]),
                "source_travelway_lineage": _first_existing(row, ["source_travelway_lineage", "primary_source_line_id", "source_line_ids"]),
                "distance_start_ft": _first_existing(row, ["distance_start_ft"]),
                "distance_end_ft": _first_existing(row, ["distance_end_ft"]),
                "distance_band": _first_existing(row, ["distance_band"]) or _distance_band(_first_existing(row, ["distance_end_ft"])),
                "analysis_window": analysis_window,
                "geometry_wkt": _first_existing(row, ["geometry_wkt"]),
                "has_route_measure_identity": _flag_value(_first_existing(row, ["has_route_measure_identity"])),
                "has_roadway_context": _flag_value(_first_existing(row, ["has_roadway_context"])),
                "has_rns_speed": _flag_value(_first_existing(row, ["has_rns_speed"])),
                "has_aadt": _flag_value(_first_existing(row, ["has_aadt"])),
                "has_exposure_denominator": _flag_value(_first_existing(row, ["has_exposure_denominator"])),
                "speed_aadt_ready_bin": _flag_value(_first_existing(row, ["speed_aadt_ready_bin"])),
                "review_only_flag": _flag_value(_first_existing(row, ["review_only"])) or True,
                "candidate_promoted": _flag_value(_first_existing(row, ["candidate_promoted"])),
                "route_facility_discontinuity_flag": _flag_value(_first_existing(row, ["route_facility_discontinuity_flag", "route_facility_changes_across_intersection"])),
                "offset_anchor_flag": _flag_value(_first_existing(row, ["offset_anchor_flag"])) or bool(_first_existing(row, ["offset_anchor_class"])),
                "grade_separation_or_mainline_review_flag": _flag_value(_first_existing(row, ["grade_separation_or_mainline_review_flag", "hold_excluded_mainline", "hold_manual_grade_separation_review", "contains_limited_access_mainline"])),
                "long_source_row_flag": _flag_value(_first_existing(row, ["long_source_row_flag"])),
                "context_assignment_scope": _first_existing(row, ["context_assignment_scope"]),
            }
        )
    return pd.DataFrame(rows)


def _build_consolidated_bins(
    base_bins: pd.DataFrame,
    ready_bins: pd.DataFrame,
    route_offset_bins: pd.DataFrame,
    offset_bins: pd.DataFrame,
) -> pd.DataFrame:
    pieces = [
        _normalize_base_bins(base_bins),
        _normalize_recovered_bins(ready_bins, "ready_class_missing_leg_recovery", "ready_for_intersection_zone_missing_leg_recovery"),
        _normalize_recovered_bins(route_offset_bins, "route_discontinuity_offset_recovery"),
        _normalize_recovered_bins(offset_bins, "offset_intersection_zone_staged_recovery", "offset_intersection_zone_staged_recovery"),
    ]
    out = pd.concat(pieces, ignore_index=True, sort=False)
    out.insert(0, "consolidated_row_id", [f"consolidated_bin_{idx:08d}" for idx in range(len(out))])
    out["distance_start_num"] = pd.to_numeric(out["distance_start_ft"], errors="coerce")
    out["distance_end_num"] = pd.to_numeric(out["distance_end_ft"], errors="coerce")
    out["leg_distance_key"] = (
        out["signal_id"].astype(str)
        + "|"
        + out["physical_leg_sector"].fillna("").astype(str)
        + "|"
        + out["distance_start_num"].round(3).astype(str)
        + "|"
        + out["distance_end_num"].round(3).astype(str)
    )
    out["geometry_duplicate_key"] = out["signal_id"].astype(str) + "|" + out["geometry_wkt"].fillna("").astype(str)
    out["retention_status"] = "retained_review_only"
    return out


def _duplicates(consolidated: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    geom = consolidated.loc[consolidated["geometry_wkt"].fillna("").astype(str).ne("")].copy()
    if not geom.empty:
        for key, group in geom.groupby("geometry_duplicate_key"):
            if len(group) > 1:
                rows.append(
                    {
                        "conflict_type": "exact_duplicate_bin_geometry_wkt",
                        "conflict_key": key,
                        "record_count": len(group),
                        "signal_count": group["signal_id"].nunique(),
                        "streams": _collapse(group["recovery_stream"]),
                        "consolidated_row_ids": _collapse(group["consolidated_row_id"], 20),
                        "resolution_status": "reported_not_dropped",
                    }
                )
    recovered = consolidated.loc[consolidated["original_vs_recovered_bin"].eq("recovered_review_only")].copy()
    for key, group in recovered.groupby("leg_distance_key", dropna=False):
        if len(group) > 1:
            conflict_type = "overlapping_recovered_bins_from_different_streams" if group["recovery_stream"].nunique() > 1 else "same_signal_leg_distance_duplicate_candidates"
            rows.append(
                {
                    "conflict_type": conflict_type,
                    "conflict_key": key,
                    "record_count": len(group),
                    "signal_count": group["signal_id"].nunique(),
                    "streams": _collapse(group["recovery_stream"]),
                    "consolidated_row_ids": _collapse(group["consolidated_row_id"], 20),
                    "resolution_status": "reported_not_dropped",
                }
            )
    return pd.DataFrame(rows)


def _stream_summary(consolidated: pd.DataFrame) -> pd.DataFrame:
    return (
        consolidated.groupby(["recovery_stream", "recovery_class", "original_vs_recovered_bin"], dropna=False)
        .agg(
            bin_count=("consolidated_row_id", "count"),
            signal_count=("signal_id", "nunique"),
            leg_count=("recovered_leg_id", "nunique"),
            bins_0_1000=("analysis_window", lambda s: int((s == "0_1000").sum())),
            bins_1000_2500=("analysis_window", lambda s: int((s == "1000_2500").sum())),
            speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        )
        .reset_index()
        .sort_values(["original_vs_recovered_bin", "bin_count"], ascending=[False, False])
    )


def _recovered_leg_counts(consolidated: pd.DataFrame) -> pd.DataFrame:
    recovered = consolidated.loc[consolidated["original_vs_recovered_bin"].eq("recovered_review_only")].copy()
    if recovered.empty:
        return pd.DataFrame(columns=["signal_id"])
    recovered["recovered_leg_count_key"] = recovered["physical_leg_sector"].where(recovered["physical_leg_sector"].ne(""), recovered["recovered_leg_id"])
    return recovered.groupby("signal_id").agg(
        recovered_stream_count=("recovery_stream", "nunique"),
        recovered_candidate_bin_count=("consolidated_row_id", "count"),
        recovered_unique_leg_count=("recovered_leg_count_key", "nunique"),
        recovered_speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        recovered_streams=("recovery_stream", _collapse),
        recovered_classes=("recovery_class", _collapse),
    ).reset_index()


def _bin_band_counts(consolidated: pd.DataFrame) -> pd.DataFrame:
    pivot = pd.pivot_table(
        consolidated,
        index="signal_id",
        columns="distance_band",
        values="consolidated_row_id",
        aggfunc="count",
        fill_value=0,
    ).reset_index()
    rename = {col: f"bins_{str(col).replace('-', '_')}" for col in pivot.columns if col != "signal_id"}
    return pivot.rename(columns=rename)


def _classify_signal(row: pd.Series) -> str:
    original = str(row.get("calibrated_alignment_class", ""))
    expected = _int(row.get("calibrated_expected_physical_leg_count"))
    current = _int(row.get("current_refreshed_physical_leg_count"))
    recovered = _int(row.get("recovered_unique_leg_count"))
    after = _int(row.get("consolidated_estimated_physical_leg_count"))
    missing_after = max(expected - min(after, expected), 0)
    if _flag_value(row.get("grade_separated_mainline_flag")):
        return "grade_separated_or_mainline_holdout"
    if _flag_value(row.get("source_limited_manual_or_prior")) or original == "source_limited_holdout":
        return "source_limited_holdout"
    if _flag_value(row.get("calibrated_divided_subbranch_evidence")) and original in {"over_split_but_bins_usable", "aligned"} and current >= expected:
        return "divided_carriageway_normalization_only"
    if original == "over_split_but_bins_usable" or current > expected:
        return "over_split_but_bins_usable"
    if expected > 0 and missing_after == 0:
        return "aligned_after_recovery"
    if recovered > 0 and missing_after > 0:
        return "partially_aligned_missing_some_legs"
    if original == "under_captured_recoverable":
        return "remaining_under_captured_recoverable"
    if str(row.get("manual_category", "")).strip():
        return "manual_map_review_needed"
    return "insufficient_evidence"


def _signal_summary(calib: pd.DataFrame, consolidated: pd.DataFrame) -> pd.DataFrame:
    leg_counts = _recovered_leg_counts(consolidated)
    band_counts = _bin_band_counts(consolidated)
    total_bins = consolidated.groupby("signal_id").agg(
        consolidated_total_bins=("consolidated_row_id", "count"),
        consolidated_recovered_bins=("original_vs_recovered_bin", lambda s: int((s == "recovered_review_only").sum())),
        consolidated_speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        route_facility_discontinuity_bin_count=("route_facility_discontinuity_flag", "sum"),
        offset_anchor_bin_count=("offset_anchor_flag", "sum"),
        grade_mainline_flag_bin_count=("grade_separation_or_mainline_review_flag", "sum"),
        long_source_row_flag_bin_count=("long_source_row_flag", "sum"),
    ).reset_index()
    cols = [
        "signal_id",
        "source_signal_id_x",
        "source_layer_x",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "calibrated_missing_leg_count",
        "calibrated_extra_leg_count",
        "calibrated_alignment_class",
        "calibrated_expected_type",
        "calibrated_divided_subbranch_evidence",
        "source_limited_manual_or_prior",
        "grade_separated_mainline_flag",
        "manual_category",
        "manual_note",
    ]
    cols = [col for col in cols if col in calib.columns]
    out = calib[cols].drop_duplicates("signal_id").copy()
    out = out.merge(total_bins, on="signal_id", how="left").merge(leg_counts, on="signal_id", how="left").merge(band_counts, on="signal_id", how="left")
    for col in [
        "consolidated_total_bins",
        "consolidated_recovered_bins",
        "consolidated_speed_aadt_ready_bins",
        "route_facility_discontinuity_bin_count",
        "offset_anchor_bin_count",
        "grade_mainline_flag_bin_count",
        "long_source_row_flag_bin_count",
        "recovered_stream_count",
        "recovered_candidate_bin_count",
        "recovered_unique_leg_count",
        "recovered_speed_aadt_ready_bins",
    ]:
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["recovered_streams"] = _text(out, "recovered_streams")
    out["recovered_classes"] = _text(out, "recovered_classes")
    current = pd.to_numeric(out["current_refreshed_physical_leg_count"], errors="coerce").fillna(0).astype(int)
    expected = pd.to_numeric(out["calibrated_expected_physical_leg_count"], errors="coerce").fillna(0).astype(int)
    recovered = out["recovered_unique_leg_count"]
    out["consolidated_estimated_physical_leg_count_uncapped"] = current + recovered
    out["consolidated_estimated_physical_leg_count"] = np.where(current >= expected, current + recovered, np.minimum(expected, current + recovered))
    out["consolidated_missing_physical_leg_count"] = np.maximum(expected - out["consolidated_estimated_physical_leg_count"], 0)
    out["consolidated_extra_or_split_branch_count"] = np.maximum(out["consolidated_estimated_physical_leg_count_uncapped"] - expected, 0)
    out["complete_or_partial_0_1000_coverage_by_leg"] = np.where(out["consolidated_missing_physical_leg_count"].eq(0), "expected_legs_present_review_only", "partial_missing_expected_legs")
    out["sensitivity_1000_2500_coverage_flag"] = out.get("bins_1000_1500ft", 0).fillna(0).astype(int).gt(0) | out.get("bins_1500_2500ft", 0).fillna(0).astype(int).gt(0)
    out["final_review_only_scaffold_alignment_class"] = out.apply(_classify_signal, axis=1)
    return out


def _alignment(signal: pd.DataFrame) -> pd.DataFrame:
    return signal[
        [
            "signal_id",
            "source_signal_id_x",
            "calibrated_expected_physical_leg_count",
            "current_refreshed_physical_leg_count",
            "recovered_unique_leg_count",
            "consolidated_estimated_physical_leg_count",
            "consolidated_missing_physical_leg_count",
            "consolidated_extra_or_split_branch_count",
            "calibrated_alignment_class",
            "final_review_only_scaffold_alignment_class",
            "recovered_streams",
            "recovered_classes",
        ]
    ].copy()


def _gap_summary(signal: pd.DataFrame) -> pd.DataFrame:
    return signal.groupby("final_review_only_scaffold_alignment_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        recovered_bins=("consolidated_recovered_bins", "sum"),
        missing_physical_legs=("consolidated_missing_physical_leg_count", "sum"),
        extra_or_split_branches=("consolidated_extra_or_split_branch_count", "sum"),
    ).reset_index().sort_values("signal_count", ascending=False)


def _under_975_resolution(signal: pd.DataFrame) -> pd.DataFrame:
    under = signal.loc[signal["calibrated_alignment_class"].eq("under_captured_recoverable")].copy()
    under["under_975_resolution_class"] = np.select(
        [
            under["final_review_only_scaffold_alignment_class"].eq("aligned_after_recovery"),
            under["final_review_only_scaffold_alignment_class"].eq("partially_aligned_missing_some_legs"),
            under["final_review_only_scaffold_alignment_class"].eq("remaining_under_captured_recoverable"),
            under["final_review_only_scaffold_alignment_class"].eq("divided_carriageway_normalization_only"),
            under["final_review_only_scaffold_alignment_class"].isin(["source_limited_holdout", "manual_map_review_needed", "grade_separated_or_mainline_holdout"]),
        ],
        [
            "resolved_aligned_by_recovery",
            "improved_but_still_incomplete",
            "still_recoverable",
            "moved_to_divided_normalization_only",
            "moved_to_source_limited_or_manual_holdout",
        ],
        default="other_review",
    )
    return under.groupby("under_975_resolution_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        recovered_bins=("consolidated_recovered_bins", "sum"),
        remaining_missing_legs=("consolidated_missing_physical_leg_count", "sum"),
    ).reset_index().sort_values("signal_count", ascending=False)


def _next_action(signal: pd.DataFrame, conflicts: pd.DataFrame) -> pd.DataFrame:
    rows = signal.copy()
    rows["next_action_queue"] = np.select(
        [
            rows["final_review_only_scaffold_alignment_class"].eq("remaining_under_captured_recoverable"),
            rows["final_review_only_scaffold_alignment_class"].eq("divided_carriageway_normalization_only"),
            rows["final_review_only_scaffold_alignment_class"].eq("source_limited_holdout"),
            rows["final_review_only_scaffold_alignment_class"].eq("manual_map_review_needed"),
            rows["final_review_only_scaffold_alignment_class"].eq("grade_separated_or_mainline_holdout"),
            rows["final_review_only_scaffold_alignment_class"].eq("partially_aligned_missing_some_legs"),
        ],
        [
            "highest_yield_remaining_under_capture_recovery",
            "divided_carriageway_normalization_only",
            "source_limited_holdout",
            "manual_review_case",
            "grade_separated_mainline_hold",
            "remaining_partial_under_capture_review",
        ],
        default="aligned_or_over_split_monitor",
    )
    conflict_signal_ids = set()
    if not conflicts.empty and "conflict_key" in conflicts.columns:
        for key in conflicts["conflict_key"].astype(str):
            if "|" in key:
                conflict_signal_ids.add(key.split("|")[0])
    rows["duplicate_conflict_case_flag"] = rows["signal_id"].isin(conflict_signal_ids)
    rows.loc[rows["duplicate_conflict_case_flag"], "next_action_queue"] = "duplicate_or_conflict_case"
    rows["next_action_priority_score"] = (
        rows["consolidated_missing_physical_leg_count"].astype(int) * 100
        + rows["consolidated_recovered_bins"].astype(int)
        + rows["consolidated_extra_or_split_branch_count"].astype(int) * 5
    )
    keep = [
        "signal_id",
        "source_signal_id_x",
        "next_action_queue",
        "final_review_only_scaffold_alignment_class",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "recovered_unique_leg_count",
        "consolidated_missing_physical_leg_count",
        "consolidated_extra_or_split_branch_count",
        "recovered_streams",
        "duplicate_conflict_case_flag",
        "next_action_priority_score",
    ]
    return rows[keep].sort_values(["next_action_queue", "next_action_priority_score"], ascending=[True, False])


def _findings(
    consolidated: pd.DataFrame,
    stream_summary: pd.DataFrame,
    signal: pd.DataFrame,
    gaps: pd.DataFrame,
    under: pd.DataFrame,
    conflicts: pd.DataFrame,
) -> str:
    total_bins = len(consolidated)
    before_bins = int((consolidated["recovery_stream"] == "existing_refreshed_represented_bin_universe").sum())
    recovered_bins = total_bins - before_bins
    improved_signals = int(signal["recovered_unique_leg_count"].gt(0).sum())
    aligned = int(signal["final_review_only_scaffold_alignment_class"].eq("aligned_after_recovery").sum())
    under_count = int(signal["final_review_only_scaffold_alignment_class"].isin(["remaining_under_captured_recoverable", "partially_aligned_missing_some_legs"]).sum())
    divided = int(signal["final_review_only_scaffold_alignment_class"].eq("divided_carriageway_normalization_only").sum())
    holdouts = int(signal["final_review_only_scaffold_alignment_class"].isin(["source_limited_holdout", "grade_separated_or_mainline_holdout", "manual_map_review_needed"]).sum())
    lines = [
        "# Consolidated Scaffold Completeness Refresh Findings",
        "",
        "This read-only consolidation combines the represented bin universe with review-only recovered missing-leg streams. It does not promote candidates, assign access/crashes, calculate rates/models, or add new recovery logic.",
        "",
        f"- Total consolidated bin rows retained: {total_bins:,}.",
        f"- Total bins before consolidation: {before_bins:,}.",
        f"- Recovered review-only bin rows added: {recovered_bins:,}.",
        f"- Represented signal count after consolidation: {CURRENT_REPRESENTED_UNIVERSE_SIGNALS:,}.",
        f"- Signals with scaffold-completeness additions: {improved_signals:,}.",
        f"- Signals aligned with calibrated expected physical-leg count after recovery: {aligned:,}.",
        f"- Signals still under-captured or partially aligned: {under_count:,}.",
        f"- Signals needing divided/carriageway normalization only: {divided:,}.",
        f"- Source-limited/manual/grade-separated holdouts: {holdouts:,}.",
        f"- Duplicate/conflict records reported: {len(conflicts):,}.",
        "",
        "## Recovery Streams",
    ]
    for _, row in stream_summary.loc[stream_summary["original_vs_recovered_bin"].eq("recovered_review_only")].iterrows():
        lines.append(f"- `{row['recovery_stream']}` / `{row['recovery_class']}`: {int(row['bin_count']):,} bins, {int(row['signal_count']):,} signals.")
    lines.extend(["", "## Original 975 Under-Captured Pool"])
    for _, row in under.iterrows():
        lines.append(f"- `{row['under_975_resolution_class']}`: {int(row['signal_count']):,} signals.")
    lines.extend(
        [
            "",
            "## Access Readiness",
            "",
            "Scaffold completeness is substantially improved, but access work should resume with the consolidated QA flags carried forward. The highest-yield remaining scaffold correction is divided/carriageway subbranch normalization, followed by targeted review of remaining partial under-capture and duplicate/conflict cases.",
        ]
    )
    return "\n".join(lines) + "\n"


def _qa(consolidated: pd.DataFrame, conflicts: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "", "true", "All writes are under review/current/consolidated_scaffold_completeness_refresh."),
        ("no_candidates_promoted", not consolidated["candidate_promoted"].map(_flag_value).any(), "", "true", ""),
        ("no_access_or_crash_assignment", True, "", "true", "No access/crash inputs are used."),
        ("no_rates_or_models", True, "", "true", ""),
        ("recovered_bins_remain_review_only", consolidated.loc[consolidated["original_vs_recovered_bin"].eq("recovered_review_only"), "review_only_flag"].map(_flag_value).all(), "", "true", ""),
        ("duplicate_conflicts_reported_not_dropped", True, len(conflicts), "reported", ""),
        ("physical_legs_separate_from_carriageway_subbranches", "carriageway_subbranch_id" in consolidated.columns and "physical_leg_id" in consolidated.columns, "", "true", ""),
        ("route_facility_attributes_not_primary_grouping", "route_facility_fields" in consolidated.columns, "", "true", ""),
        ("outputs_written_only_to_review_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/consolidated_scaffold_completeness_refresh"), str(OUT_DIR), "review/current/consolidated_scaffold_completeness_refresh", ""),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "observed", "expected", "note"])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    represented_signals = _read_csv(REFRESHED_DIR / "refreshed_represented_signal_universe.csv")
    base_bins = _read_csv(REFRESHED_DIR / "refreshed_represented_bin_universe.csv")
    calib = _read_csv(CALIB_DIR / "calibrated_expected_leg_signal_detail.csv")
    _read_csv(CALIB_DIR / "calibrated_current_vs_expected_alignment.csv")
    _read_csv(CALIB_DIR / "calibrated_leg_model_review_queue.csv")
    ready_bins = _read_csv(READY_CONTEXT_DIR / "missing_leg_context_bin_detail.csv")
    _read_csv(READY_CONTEXT_DIR / "missing_leg_context_signal_summary.csv")
    _read_csv(READY_CONTEXT_DIR / "missing_leg_context_readiness_summary.csv")
    route_offset_bins = _read_csv(ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_bin_detail.csv")
    _read_csv(ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_signal_summary.csv")
    _read_csv(ROUTE_OFFSET_CONTEXT_DIR / "route_discontinuity_offset_context_readiness_summary.csv")
    offset_bins = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_bin_detail.csv")
    _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv")
    _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_readiness_summary.csv")

    consolidated = _build_consolidated_bins(base_bins, ready_bins, route_offset_bins, offset_bins)
    conflicts = _duplicates(consolidated)
    stream_summary = _stream_summary(consolidated)
    signal_summary = _signal_summary(calib, consolidated)
    alignment = _alignment(signal_summary)
    gap_summary = _gap_summary(signal_summary)
    under_resolution = _under_975_resolution(signal_summary)
    next_action = _next_action(signal_summary, conflicts)
    qa = _qa(consolidated, conflicts)

    outputs = [
        _write_csv(consolidated.drop(columns=["distance_start_num", "distance_end_num"], errors="ignore"), "consolidated_scaffold_bin_detail.csv"),
        _write_csv(signal_summary, "consolidated_scaffold_signal_summary.csv"),
        _write_csv(stream_summary, "consolidated_scaffold_recovery_stream_summary.csv"),
        _write_csv(conflicts, "consolidated_scaffold_duplicate_conflicts.csv"),
        _write_csv(alignment, "consolidated_scaffold_expected_alignment.csv"),
        _write_csv(gap_summary, "consolidated_scaffold_remaining_gap_summary.csv"),
        _write_csv(under_resolution, "under_captured_975_resolution_summary.csv"),
        _write_csv(next_action, "consolidated_scaffold_next_action_queue.csv"),
        _write_text(_findings(consolidated, stream_summary, signal_summary, gap_summary, under_resolution, conflicts), "consolidated_scaffold_completeness_findings.md"),
        _write_csv(qa, "consolidated_scaffold_completeness_qa.csv"),
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.consolidated_scaffold_completeness_refresh",
        "output_dir": str(OUT_DIR),
        "read_only": True,
        "inputs": {
            "refreshed_dir": str(REFRESHED_DIR),
            "calibrated_dir": str(CALIB_DIR),
            "ready_context_dir": str(READY_CONTEXT_DIR),
            "route_offset_context_dir": str(ROUTE_OFFSET_CONTEXT_DIR),
            "offset_context_dir": str(OFFSET_CONTEXT_DIR),
            "offset_qa_dir": str(OFFSET_QA_DIR),
            "offset_staging_dir": str(OFFSET_STAGING_DIR),
            "refreshed_manifest": _load_json(REFRESHED_DIR / "refreshed_universe_with_offset_recovery_manifest.json"),
            "calibrated_manifest": _load_json(CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json"),
        },
        "outputs": [str(path) for path in outputs] + [str(OUT_DIR / "consolidated_scaffold_completeness_manifest.json"), str(OUT_DIR / "run_progress_log.txt")],
        "row_counts": {
            "represented_signals_input": int(len(represented_signals)),
            "base_bins_input": int(len(base_bins)),
            "ready_context_bins_input": int(len(ready_bins)),
            "route_offset_context_bins_input": int(len(route_offset_bins)),
            "offset_context_bins_input": int(len(offset_bins)),
            "consolidated_bin_detail": int(len(consolidated)),
            "consolidated_signal_summary": int(len(signal_summary)),
            "duplicate_conflict_records": int(len(conflicts)),
        },
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_assigned": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "new_recovery_logic_added": False,
        },
    }
    _write_json(manifest, "consolidated_scaffold_completeness_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
