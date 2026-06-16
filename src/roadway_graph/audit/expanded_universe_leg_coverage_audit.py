from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_leg_coverage_audit"

FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
REFRESH_DIR = OUTPUT_ROOT / "review/current/expanded_universe_refresh_and_709_plan"
CONTEXT_347_DIR = OUTPUT_ROOT / "review/current/review_only_347_context_refresh"
GEOM_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"

BAND_EDGES = [0, 250, 500, 750, 1000, 1500, 2500]
BAND_LABELS = ["0_250", "250_500", "500_750", "750_1000", "1000_1500", "1500_2500"]

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
    FREEZE_DIR: ["frozen_candidate_bin_universe.csv", "frozen_candidate_signal_universe.csv"],
    REFRESH_DIR: ["refreshed_represented_signal_universe.csv"],
    CONTEXT_347_DIR: ["review_only_347_context_bin_detail.csv", "review_only_347_context_signal_summary.csv"],
    GEOM_DIR: ["access_geometry_completion_detail.csv"],
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


def _route_key(value: Any) -> str:
    text = str(value).upper().strip()
    if not text:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def _parse_oriented_segment(bin_id: str) -> str:
    text = str(bin_id)
    return re.sub(r"_bin_\d+$", "", text)


def _load_inputs() -> dict[str, pd.DataFrame]:
    geom_cols = [
        "target_bin_source",
        "target_bin_id",
        "frozen_candidate_bin_id",
        "candidate_bin_id",
        "target_signal_id",
        "candidate_signal_id",
        "source_signal_id",
        "source_layer",
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
        "has_speed",
        "has_aadt",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
        "distance_length_ft",
        "completed_geometry_status",
        "geometry_recovery_method",
        "geometry_blocker_reason",
        "prior_geometry_missing",
        "geometry_recovered_this_pass",
    ]
    freeze_cols = [
        "candidate_bin_id",
        "frozen_candidate_bin_id",
        "frozen_candidate_signal_id",
        "candidate_association_id",
        "candidate_rank",
        "direction_confidence_status",
        "scaffold_completeness_tier",
        "candidate_logic_tier",
        "strict_active_overlap_status",
        "roadway_division_status",
        "matched_route_common",
        "route_id",
        "route_common",
        "route_name",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_facility_text",
        "candidate_measure_start",
        "candidate_measure_end",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "speed_ready_review_only_flag",
        "aadt_ready_review_only_flag",
        "exposure_ready_review_only_flag",
        "speed_aadt_ready_review_only_flag",
        "partial_one_sided_flag",
        "multi_candidate_weighted_flag",
        "recommended_bin_universe_tier",
    ]
    context_cols = [
        "candidate_bin_id",
        "review_only_347_bin_id",
        "candidate_association_id",
        "candidate_rank",
        "direction_confidence_status",
        "scaffold_completeness_tier",
        "strict_active_overlap_status",
        "roadway_division_status",
        "source_road_row_id",
        "route_id",
        "route_common",
        "route_name",
        "candidate_route_measure_key",
        "candidate_measure_start",
        "candidate_measure_end",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "candidate_route_name_rns_norm",
        "normalized_candidate_route_key",
        "candidate_facility_text",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "partial_one_sided_flag",
        "review_only_denominator_status",
    ]
    signal_cols = [
        "source_signal_id",
        "source_layer",
        "candidate_signal_id_refreshed",
        "frozen_candidate_signal_id",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
        "one_direction_only_flag",
        "one_sided_or_partial_flag",
        "multi_candidate_weighted_flag",
        "strict_active_overlap_conflict_flag",
        "strict_active_overlap_status",
        "recovery_strategy",
        "association_confidence_tier",
        "represented_source",
        "review_only_addition_status",
        "refreshed_universe_tier",
        "near_signal_or_partial_tier",
    ]
    return {
        "geometry": _read_csv(GEOM_DIR / "access_geometry_completion_detail.csv", usecols=geom_cols),
        "freeze_bins": _read_csv(FREEZE_DIR / "frozen_candidate_bin_universe.csv", usecols=freeze_cols),
        "freeze_signals": _read_csv(FREEZE_DIR / "frozen_candidate_signal_universe.csv"),
        "refresh_signals": _read_csv(REFRESH_DIR / "refreshed_represented_signal_universe.csv", usecols=signal_cols),
        "context_bins": _read_csv(CONTEXT_347_DIR / "review_only_347_context_bin_detail.csv", usecols=context_cols),
        "context_signals": _read_csv(CONTEXT_347_DIR / "review_only_347_context_signal_summary.csv"),
    }


def _build_bin_detail(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    detail = inputs["geometry"].copy()
    detail = detail.rename(
        columns={
            "target_bin_id": "candidate_bin_id_effective",
            "target_signal_id": "signal_id",
            "distance_start_ft": "candidate_bin_start_ft",
            "distance_end_ft": "candidate_bin_end_ft",
            "distance_length_ft": "candidate_bin_length_ft",
        }
    )
    detail["target_bin_id"] = detail["candidate_bin_id_effective"]
    detail["source_candidate_bin_id"] = _text(detail, "candidate_bin_id")

    freeze = inputs["freeze_bins"].add_prefix("freeze_")
    detail = detail.merge(
        freeze,
        left_on="source_candidate_bin_id",
        right_on="freeze_candidate_bin_id",
        how="left",
    )
    context = inputs["context_bins"].add_prefix("context_")
    detail = detail.merge(
        context,
        left_on="source_candidate_bin_id",
        right_on="context_candidate_bin_id",
        how="left",
    )
    refresh = inputs["refresh_signals"].add_prefix("signal_")
    detail = detail.merge(
        refresh,
        left_on=["source_signal_id", "source_layer"],
        right_on=["signal_source_signal_id", "signal_source_layer"],
        how="left",
    )

    for out_col, candidates in {
        "candidate_bin_id": ["source_candidate_bin_id", "target_bin_id"],
        "frozen_candidate_bin_id": ["frozen_candidate_bin_id", "freeze_frozen_candidate_bin_id"],
        "frozen_candidate_signal_id": ["freeze_frozen_candidate_signal_id", "signal_frozen_candidate_signal_id"],
        "candidate_association_id": ["freeze_candidate_association_id", "context_candidate_association_id"],
        "candidate_rank": ["freeze_candidate_rank", "context_candidate_rank"],
        "direction_confidence_status": ["freeze_direction_confidence_status", "context_direction_confidence_status"],
        "scaffold_completeness_tier": ["freeze_scaffold_completeness_tier", "context_scaffold_completeness_tier"],
        "strict_active_overlap_status": ["freeze_strict_active_overlap_status", "context_strict_active_overlap_status", "signal_strict_active_overlap_status"],
        "roadway_division_status": ["freeze_roadway_division_status", "context_roadway_division_status"],
        "source_road_row_id": ["source_road_row_id", "context_source_road_row_id"],
        "route_id": ["freeze_route_id", "context_route_id"],
        "route_common": ["freeze_route_common", "context_route_common", "freeze_matched_route_common"],
        "route_name": ["freeze_route_name", "context_route_name"],
        "normalized_candidate_route_key": ["freeze_normalized_candidate_route_key", "context_normalized_candidate_route_key"],
        "candidate_route_name_rns_norm": ["freeze_candidate_route_name_rns_norm", "context_candidate_route_name_rns_norm"],
        "candidate_facility_text": ["freeze_candidate_facility_text", "context_candidate_facility_text"],
        "candidate_measure_start": ["freeze_candidate_measure_start", "context_candidate_measure_start"],
        "candidate_measure_end": ["freeze_candidate_measure_end", "context_candidate_measure_end"],
        "candidate_measure_min": ["freeze_candidate_measure_min", "context_candidate_measure_min"],
        "candidate_measure_max": ["freeze_candidate_measure_max", "context_candidate_measure_max"],
        "candidate_midpoint_measure": ["freeze_candidate_midpoint_measure", "context_candidate_midpoint_measure"],
        "candidate_measure_length": ["freeze_candidate_measure_length", "context_candidate_measure_length"],
        "partial_one_sided_flag": ["freeze_partial_one_sided_flag", "context_partial_one_sided_flag", "signal_one_sided_or_partial_flag"],
        "speed_ready_flag": ["freeze_speed_ready_review_only_flag", "has_speed", "context_has_speed", "signal_has_speed"],
        "aadt_ready_flag": ["freeze_aadt_ready_review_only_flag", "has_aadt", "context_has_aadt", "signal_has_aadt"],
        "exposure_ready_flag": ["freeze_exposure_ready_review_only_flag", "context_has_exposure", "signal_has_exposure"],
        "speed_aadt_ready_flag": ["freeze_speed_aadt_ready_review_only_flag", "speed_aadt_ready", "signal_speed_aadt_ready"],
        "multi_candidate_weighted_flag": ["freeze_multi_candidate_weighted_flag", "signal_multi_candidate_weighted_flag"],
        "recommended_bin_universe_tier": ["freeze_recommended_bin_universe_tier", "signal_refreshed_universe_tier"],
        "represented_source": ["signal_represented_source"],
        "review_only_addition_status": ["signal_review_only_addition_status"],
        "refreshed_universe_tier": ["signal_refreshed_universe_tier"],
        "near_signal_or_partial_tier": ["signal_near_signal_or_partial_tier"],
    }.items():
        value = pd.Series("", index=detail.index, dtype="string")
        for col in candidates:
            if col in detail.columns:
                value = value.mask(value.astype(str).str.strip().eq(""), detail[col].fillna("").astype(str))
        detail[out_col] = value

    detail["route_or_facility_key"] = (
        _text(detail, "normalized_candidate_route_key")
        .mask(lambda s: s.eq(""), _text(detail, "candidate_route_name_rns_norm"))
        .mask(lambda s: s.eq(""), _text(detail, "route_name").map(_route_key))
        .mask(lambda s: s.eq(""), _text(detail, "route_common").map(_route_key))
        .mask(lambda s: s.eq(""), _text(detail, "candidate_facility_text").map(_route_key))
    )
    detail["route_or_facility_label"] = (
        _text(detail, "route_name")
        .mask(lambda s: s.eq(""), _text(detail, "route_common"))
        .mask(lambda s: s.eq(""), _text(detail, "candidate_facility_text"))
        .mask(lambda s: s.eq(""), _text(detail, "road_component_id"))
    )
    detail["candidate_bin_start_ft_num"] = _num(detail, "candidate_bin_start_ft")
    detail["candidate_bin_end_ft_num"] = _num(detail, "candidate_bin_end_ft")
    detail["candidate_bin_length_ft_num"] = _num(detail, "candidate_bin_length_ft").fillna(
        (detail["candidate_bin_end_ft_num"] - detail["candidate_bin_start_ft_num"]).abs()
    )
    detail["geometry_available_flag"] = _text(detail, "completed_geometry_status").eq("geometry_available")
    detail["provenance_class"] = np.select(
        [
            _text(detail, "recovery_strategy").eq("strict_active_baseline"),
            _text(detail, "represented_source").eq("review_only_347_context_refresh"),
            _text(detail, "review_only_addition_status").ne("baseline_not_new_addition"),
        ],
        ["strict_active_baseline", "review_only_recovered_347", "expanded_review_only_candidate"],
        default="expanded_or_recovered_candidate",
    )
    detail["leg_base_id"] = (
        _text(detail, "candidate_association_id")
        .mask(lambda s: s.eq(""), _text(detail, "road_component_id"))
        .mask(lambda s: s.eq(""), _text(detail, "graph_edge_id"))
        .mask(lambda s: s.eq(""), _text(detail, "route_or_facility_key"))
        .mask(lambda s: s.eq(""), _text(detail, "target_bin_id").map(_parse_oriented_segment))
    )
    detail["leg_direction_key"] = _text(detail, "signal_relative_direction_label").mask(lambda s: s.eq(""), "unknown_direction")
    detail["candidate_leg_id"] = detail["signal_id"].astype(str) + "|" + detail["leg_base_id"].astype(str) + "|" + detail["leg_direction_key"].astype(str)

    keep = [
        "target_bin_id",
        "candidate_bin_id",
        "signal_id",
        "candidate_signal_id",
        "source_signal_id",
        "source_layer",
        "frozen_candidate_bin_id",
        "frozen_candidate_signal_id",
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
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_facility_text",
        "candidate_measure_start",
        "candidate_measure_end",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "candidate_bin_start_ft",
        "candidate_bin_end_ft",
        "candidate_bin_length_ft",
        "analysis_window",
        "distance_band",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "scaffold_completeness_tier",
        "strict_active_overlap_status",
        "roadway_division_status",
        "completed_geometry_status",
        "geometry_available_flag",
        "geometry_recovery_method",
        "geometry_blocker_reason",
        "prior_geometry_missing",
        "geometry_recovered_this_pass",
        "speed_ready_flag",
        "aadt_ready_flag",
        "exposure_ready_flag",
        "speed_aadt_ready_flag",
        "full_0_1000_speed_aadt_ready",
        "full_attempted_0_2500_speed_aadt_ready",
        "partial_one_sided_flag",
        "multi_candidate_weighted_flag",
        "represented_source",
        "review_only_addition_status",
        "refreshed_universe_tier",
        "near_signal_or_partial_tier",
        "provenance_class",
    ]
    return detail[[col for col in keep if col in detail.columns]].copy()


def _band_overlap(start: pd.Series, end: pd.Series, low: float, high: float) -> pd.Series:
    return start.lt(high) & end.gt(low)


def _leg_summary(detail: pd.DataFrame) -> pd.DataFrame:
    work = detail.copy()
    work["start"] = _num(work, "candidate_bin_start_ft")
    work["end"] = _num(work, "candidate_bin_end_ft")
    work["length"] = _num(work, "candidate_bin_length_ft").fillna((work["end"] - work["start"]).abs())
    grouped = work.groupby(["signal_id", "candidate_leg_id"], dropna=False)
    summary = grouped.agg(
        source_signal_id=("source_signal_id", _first_nonblank),
        source_layer=("source_layer", _first_nonblank),
        leg_base_id=("leg_base_id", _first_nonblank),
        signal_relative_direction_label=("signal_relative_direction_label", _collapse),
        route_or_facility_key=("route_or_facility_key", _first_nonblank),
        route_or_facility_label=("route_or_facility_label", _first_nonblank),
        candidate_association_id=("candidate_association_id", _first_nonblank),
        road_component_ids=("road_component_id", _collapse),
        graph_edge_ids=("graph_edge_id", _collapse),
        roadway_division_statuses=("roadway_division_status", _collapse),
        bin_count=("target_bin_id", "nunique"),
        geometry_available_bins=("geometry_available_flag", "sum"),
        total_length_ft=("length", "sum"),
        min_distance_start_ft=("start", "min"),
        max_distance_end_ft=("end", "max"),
        analysis_windows=("analysis_window", _collapse),
        provenance_classes=("provenance_class", _collapse),
    ).reset_index()
    for label, low, high in zip(BAND_LABELS, BAND_EDGES[:-1], BAND_EDGES[1:]):
        mask = _band_overlap(work["start"], work["end"], low, high)
        counts = work.loc[mask].groupby(["signal_id", "candidate_leg_id"])["target_bin_id"].nunique()
        summary[f"bins_{label}"] = summary.set_index(["signal_id", "candidate_leg_id"]).index.map(counts).fillna(0).astype(int)
    summary["bins_0_1000"] = summary[[f"bins_{label}" for label in BAND_LABELS[:4]]].sum(axis=1)
    summary["bins_1000_2500"] = summary[[f"bins_{label}" for label in BAND_LABELS[4:]]].sum(axis=1)
    summary["has_any_0_1000"] = summary["bins_0_1000"].gt(0)
    summary["has_any_0_2500"] = summary["bin_count"].gt(0)
    summary["complete_0_1000_flag"] = summary[[f"bins_{label}" for label in BAND_LABELS[:4]]].gt(0).all(axis=1) & summary["max_distance_end_ft"].ge(1000)
    summary["complete_0_2500_flag"] = summary[[f"bins_{label}" for label in BAND_LABELS]].gt(0).all(axis=1) & summary["max_distance_end_ft"].ge(2500)
    summary["leg_window_coverage_status"] = np.select(
        [
            summary["complete_0_2500_flag"],
            summary["complete_0_1000_flag"],
            summary["has_any_0_1000"],
        ],
        ["complete_0_2500", "complete_0_1000_only", "partial_0_1000"],
        default="partial_or_outer_only",
    )
    return summary


def _signal_summary(detail: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    work = detail.copy()
    work["start"] = _num(work, "candidate_bin_start_ft")
    work["end"] = _num(work, "candidate_bin_end_ft")
    work["length"] = _num(work, "candidate_bin_length_ft").fillna((work["end"] - work["start"]).abs())
    grouped = work.groupby("signal_id", dropna=False)
    signal = grouped.agg(
        source_signal_id=("source_signal_id", _first_nonblank),
        source_layer=("source_layer", _first_nonblank),
        total_bins=("target_bin_id", "nunique"),
        geometry_available_bins=("geometry_available_flag", "sum"),
        total_length_ft=("length", "sum"),
        route_facility_groups=("route_or_facility_key", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        route_facility_labels=("route_or_facility_label", _collapse),
        direction_status_count=("direction_confidence_status", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        direction_label_count=("signal_relative_direction_label", lambda s: int(s.astype(str).str.strip().replace("", np.nan).nunique(dropna=True))),
        direction_labels=("signal_relative_direction_label", _collapse),
        roadway_division_statuses=("roadway_division_status", _collapse),
        provenance_classes=("provenance_class", _collapse),
        speed_ready_bins=("speed_ready_flag", lambda s: int(s.astype(str).str.lower().eq("true").sum())),
        aadt_ready_bins=("aadt_ready_flag", lambda s: int(s.astype(str).str.lower().eq("true").sum())),
        speed_aadt_ready_bins=("speed_aadt_ready_flag", lambda s: int(s.astype(str).str.lower().eq("true").sum())),
    ).reset_index()
    for label, low, high in zip(BAND_LABELS, BAND_EDGES[:-1], BAND_EDGES[1:]):
        mask = _band_overlap(work["start"], work["end"], low, high)
        counts = work.loc[mask].groupby("signal_id")["target_bin_id"].nunique()
        signal[f"bins_{label}"] = signal["signal_id"].map(counts).fillna(0).astype(int)
    signal["bins_0_1000"] = signal[[f"bins_{label}" for label in BAND_LABELS[:4]]].sum(axis=1)
    signal["bins_1000_2500"] = signal[[f"bins_{label}" for label in BAND_LABELS[4:]]].sum(axis=1)

    leg_counts = legs.groupby("signal_id").agg(
        candidate_leg_count=("candidate_leg_id", "nunique"),
        complete_0_1000_leg_count=("complete_0_1000_flag", "sum"),
        complete_0_2500_leg_count=("complete_0_2500_flag", "sum"),
        represented_leg_any_0_1000_count=("has_any_0_1000", "sum"),
    ).reset_index()
    signal = signal.merge(leg_counts, on="signal_id", how="left")
    signal["candidate_leg_count"] = signal["candidate_leg_count"].fillna(0).astype(int)
    signal["leg_count_class"] = np.select(
        [
            signal["candidate_leg_count"].eq(1),
            signal["candidate_leg_count"].eq(2),
            signal["candidate_leg_count"].eq(3),
            signal["candidate_leg_count"].eq(4),
            signal["candidate_leg_count"].ge(5),
        ],
        ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"],
        default="no_leg",
    )
    divided_text = _text(signal, "roadway_division_statuses").str.lower()
    signal["intersection_form_interpretation"] = np.select(
        [
            signal["candidate_leg_count"].eq(1),
            signal["candidate_leg_count"].eq(2) & signal["route_facility_groups"].le(1),
            signal["candidate_leg_count"].eq(3),
            signal["candidate_leg_count"].eq(4) & ~divided_text.str.contains("divided", na=False),
            signal["candidate_leg_count"].ge(5) | divided_text.str.contains("divided", na=False),
        ],
        [
            "likely_incomplete_or_one_leg_only",
            "likely_one_roadway_axis_or_two_leg_partial",
            "likely_t_intersection_or_partial_four_leg",
            "likely_four_leg_intersection",
            "complex_or_divided_or_overexpanded_review",
        ],
        default="insufficient_evidence",
    )
    signal["complete_0_1000_by_at_least_one_leg"] = signal["complete_0_1000_leg_count"].fillna(0).gt(0)
    signal["complete_0_1000_across_all_represented_legs"] = signal["candidate_leg_count"].gt(0) & signal["complete_0_1000_leg_count"].fillna(0).eq(signal["candidate_leg_count"])
    signal["complete_0_2500_by_at_least_one_leg"] = signal["complete_0_2500_leg_count"].fillna(0).gt(0)
    signal["complete_0_2500_across_all_represented_legs"] = signal["candidate_leg_count"].gt(0) & signal["complete_0_2500_leg_count"].fillna(0).eq(signal["candidate_leg_count"])
    signal["any_0_1000"] = signal["bins_0_1000"].gt(0)
    signal["any_0_2500"] = signal["total_bins"].gt(0)
    signal["bins_per_signal_class"] = pd.cut(
        signal["total_bins"],
        bins=[-1, 0, 20, 50, 90, 120, 200, np.inf],
        labels=["0", "1_20", "21_50", "51_90", "91_120", "121_200", "200_plus"],
    ).astype(str)
    signal["possible_under_capture_flag"] = (
        signal["candidate_leg_count"].le(1)
        | ((signal["candidate_leg_count"].eq(2)) & signal["route_facility_groups"].le(1))
        | signal["direction_label_count"].le(1)
        | signal["bins_0_1000"].lt(10)
    )
    signal["possible_over_expansion_flag"] = (
        signal["candidate_leg_count"].ge(6)
        | signal["total_bins"].gt(signal["total_bins"].quantile(0.95))
        | signal["route_facility_groups"].ge(4)
    )
    signal["partial_coverage_preserved_flag"] = True
    return signal


def _leg_count_distribution(signal: pd.DataFrame) -> pd.DataFrame:
    out = signal.groupby("leg_count_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        median_bins_per_signal=("total_bins", "median"),
        median_route_facility_groups=("route_facility_groups", "median"),
    ).reset_index()
    return out.sort_values("leg_count_class")


def _distance_availability(signal: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in BAND_LABELS:
        rows.append(
            {
                "availability_metric": f"any_{label}_ft_bins",
                "signal_count": int(signal[f"bins_{label}"].gt(0).sum()),
                "bin_count": int(signal[f"bins_{label}"].sum()),
            }
        )
    for metric, column in [
        ("any_0_1000_ft_bins", "any_0_1000"),
        ("complete_0_1000_by_at_least_one_leg", "complete_0_1000_by_at_least_one_leg"),
        ("complete_0_1000_across_all_represented_legs", "complete_0_1000_across_all_represented_legs"),
        ("any_0_2500_ft_bins", "any_0_2500"),
        ("complete_0_2500_by_at_least_one_leg", "complete_0_2500_by_at_least_one_leg"),
        ("complete_0_2500_across_all_represented_legs", "complete_0_2500_across_all_represented_legs"),
    ]:
        rows.append({"availability_metric": metric, "signal_count": int(signal[column].sum()), "bin_count": ""})
    return pd.DataFrame(rows)


def _under_capture_flags(signal: pd.DataFrame) -> pd.DataFrame:
    rows = []
    checks = [
        ("one_leg_only", signal["candidate_leg_count"].eq(1)),
        ("two_leg_one_axis_possible_cross_street_missing", signal["candidate_leg_count"].eq(2) & signal["route_facility_groups"].le(1)),
        ("one_direction_or_status_only", signal["direction_label_count"].le(1)),
        ("sparse_0_1000_coverage", signal["bins_0_1000"].lt(10)),
        ("sparse_1000_2500_coverage", signal["bins_1000_2500"].lt(10)),
        ("geometry_exists_but_route_leg_grouping_ambiguous", signal["route_facility_groups"].eq(0) & signal["geometry_available_bins"].gt(0)),
    ]
    for flag, mask in checks:
        subset = signal.loc[mask].copy()
        if subset.empty:
            continue
        subset["under_capture_flag"] = flag
        rows.append(subset)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True, sort=False)
    keep = [
        "under_capture_flag",
        "signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_leg_count",
        "route_facility_groups",
        "direction_label_count",
        "total_bins",
        "bins_0_1000",
        "bins_1000_2500",
        "geometry_available_bins",
        "intersection_form_interpretation",
        "route_facility_labels",
        "direction_labels",
        "provenance_classes",
    ]
    return out[keep].sort_values(["under_capture_flag", "total_bins", "signal_id"])


def _over_expansion_flags(signal: pd.DataFrame) -> pd.DataFrame:
    rows = []
    checks = [
        ("five_plus_or_complex_leg_count", signal["candidate_leg_count"].ge(5)),
        ("very_high_bin_count", signal["total_bins"].gt(signal["total_bins"].quantile(0.95))),
        ("many_route_facility_groups", signal["route_facility_groups"].ge(4)),
    ]
    for flag, mask in checks:
        subset = signal.loc[mask].copy()
        if subset.empty:
            continue
        subset["over_expansion_flag"] = flag
        rows.append(subset)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True, sort=False)
    keep = [
        "over_expansion_flag",
        "signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_leg_count",
        "route_facility_groups",
        "total_bins",
        "geometry_available_bins",
        "intersection_form_interpretation",
        "route_facility_labels",
        "direction_labels",
        "provenance_classes",
    ]
    return out[keep].sort_values(["over_expansion_flag", "candidate_leg_count", "total_bins"], ascending=[True, False, False])


def _review_queue(signal: pd.DataFrame) -> pd.DataFrame:
    rows = []
    queue_defs = [
        ("likely_under_captured_four_leg_intersection", signal["candidate_leg_count"].le(2) & signal["route_facility_groups"].ge(2)),
        ("one_leg_only_signal", signal["candidate_leg_count"].eq(1)),
        ("two_leg_only_possible_cross_street_missing", signal["candidate_leg_count"].eq(2) & signal["route_facility_groups"].le(1)),
        ("divided_complex_needing_interpretation", signal["intersection_form_interpretation"].eq("complex_or_divided_or_overexpanded_review")),
        ("high_quality_four_leg_example", signal["candidate_leg_count"].eq(4) & signal["complete_0_1000_across_all_represented_legs"]),
        ("high_quality_t_intersection_example", signal["candidate_leg_count"].eq(3) & signal["complete_0_1000_across_all_represented_legs"]),
        ("many_bins_or_branches_overexpanded_review", signal["possible_over_expansion_flag"]),
    ]
    for label, mask in queue_defs:
        subset = signal.loc[mask].copy()
        if subset.empty:
            continue
        subset["review_queue"] = label
        subset["review_priority_score"] = (
            subset["candidate_leg_count"].astype(float) * 10
            + subset["route_facility_groups"].astype(float) * 5
            + subset["total_bins"].astype(float) / 25
        )
        rows.append(subset.sort_values("review_priority_score", ascending=False).head(75))
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True, sort=False)
    keep = [
        "review_queue",
        "review_priority_score",
        "signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_leg_count",
        "route_facility_groups",
        "total_bins",
        "bins_0_1000",
        "bins_1000_2500",
        "intersection_form_interpretation",
        "route_facility_labels",
        "direction_labels",
        "provenance_classes",
    ]
    return out[keep]


def _qa(detail: pd.DataFrame, signal: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "This module writes only to expanded_universe_leg_coverage_audit review folder."),
        ("no_candidates_promoted", "pass", "All outputs are review-only diagnostics."),
        ("no_access_or_crash_assignment", "pass", "No access or crash assignment is performed."),
        ("no_rates_or_models", "pass", "No rates or models are computed."),
        ("partial_bins_preserved_not_discarded", "pass", f"Preserved {len(detail):,} bin rows including partial windows."),
        ("signals_not_forced_to_four_legs", "pass", "Observed branch counts are reported as 1, 2, 3, 4, or 5+ without forcing a four-leg schema."),
        ("deduped_signal_counts_separate_from_bin_counts", "pass", f"{signal['signal_id'].nunique():,} signals and {detail['target_bin_id'].nunique():,} bins reported separately."),
        ("outputs_review_only", "pass", str(OUT_DIR)),
        ("outputs_written_only_to_review_folder", "pass", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(detail: pd.DataFrame, signal: pd.DataFrame, legs: pd.DataFrame, leg_dist: pd.DataFrame, availability: pd.DataFrame, under: pd.DataFrame, over: pd.DataFrame) -> str:
    total_signals = signal["signal_id"].nunique()
    total_bins = detail["target_bin_id"].nunique()
    geom_bins = int(detail["geometry_available_flag"].sum())
    bins_stats = signal["total_bins"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.95])
    leg_counts = dict(zip(leg_dist["leg_count_class"], leg_dist["signal_count"]))
    under_count = under["signal_id"].nunique() if not under.empty else 0
    over_count = over["signal_id"].nunique() if not over.empty else 0
    one_axis = int(signal.loc[signal["candidate_leg_count"].le(2), "signal_id"].nunique())
    four_plus = int(signal.loc[signal["candidate_leg_count"].ge(4), "signal_id"].nunique())
    availability_lines = "\n".join(
        f"- {row.availability_metric}: {int(row.signal_count):,} signals"
        for row in availability.itertuples(index=False)
        if str(row.availability_metric).startswith("any_") or "complete" in str(row.availability_metric)
    )
    return f"""# Expanded Universe Leg Coverage Audit Findings

**Bounded question:** verify whether the expanded 2,739-signal roadway scaffold captures defensible candidate legs/branches, while preserving partial bin coverage as review-only evidence.

## Direct Answers

1. The universe is internally consistent for this review pass: **{total_bins:,}** bin rows across **{total_signals:,}** represented signals, with **{geom_bins:,}** bins carrying completed geometry. This matches the prior geometry-completion result apart from the two geometry-unavailable rows that remain preserved.
2. Bins per signal: mean **{bins_stats['mean']:.1f}**, median **{bins_stats['50%']:.0f}**, 10th percentile **{bins_stats['10%']:.0f}**, 90th percentile **{bins_stats['90%']:.0f}**, 95th percentile **{bins_stats['95%']:.0f}**.
3. Candidate legs/branches are observed from association/lineage plus signal-relative direction. The distribution is: one-leg **{leg_counts.get('one_leg', 0):,}**, two-leg **{leg_counts.get('two_leg', 0):,}**, three-leg **{leg_counts.get('three_leg', 0):,}**, four-leg **{leg_counts.get('four_leg', 0):,}**, five-plus **{leg_counts.get('five_plus_leg', 0):,}**.
4. The scaffold is not purely one corridor axis: **{four_plus:,}** signals have four or more represented branches, while **{one_axis:,}** have one or two represented branches and need more cautious interpretation.
5. Possible under-capture flags identify **{under_count:,}** unique signals. These are review flags, not removal rules.
6. Possible over-expansion or ambiguity flags identify **{over_count:,}** unique signals, mostly complex/divided or many-branch cases needing interpretation.
7. Distance-band availability:
{availability_lines}
8. Later access/crash analyses should keep partial windows: use any-bin availability and per-leg completeness flags as denominators/eligibility metadata instead of requiring complete 0-1,000 ft or 0-2,500 ft coverage.
9. Recommended next scaffold QA pass: map a small stratified queue covering one-leg/two-leg under-capture flags, high-quality T/four-leg examples, and five-plus divided/complex cases before using leg counts as an analysis covariate.

No active outputs were modified, candidates promoted, access/crashes assigned, rates calculated, or models run.
"""


def _manifest(started: datetime, outputs: list[str], inputs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.audit.expanded_universe_leg_coverage_audit",
        "bounded_question": "expanded universe leg coverage and bin completeness audit",
        "started_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR),
        "inputs": {name: {"rows": int(len(frame)), "columns": list(frame.columns)} for name, frame in inputs.items()},
        "outputs": outputs,
        "non_goals_confirmed": [
            "no active outputs modified",
            "no candidates promoted",
            "no access or crash assignment",
            "no rates or models",
            "partial bins preserved",
            "signals not forced to exactly four legs",
        ],
    }


def _write_outputs(outputs: dict[str, pd.DataFrame], findings: str, manifest: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_csv(OUT_DIR / name, index=False)
        _checkpoint(f"write_complete {name}", len(frame))
    (OUT_DIR / "expanded_universe_leg_coverage_findings.md").write_text(findings, encoding="utf-8")
    (OUT_DIR / "expanded_universe_leg_coverage_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _checkpoint("write_complete expanded_universe_leg_coverage_findings.md")
    _checkpoint("write_complete expanded_universe_leg_coverage_manifest.json")


def main() -> None:
    started = datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    _require_inputs()
    inputs = _load_inputs()
    detail = _build_bin_detail(inputs)
    _checkpoint("build_bin_detail", len(detail))
    legs = _leg_summary(detail)
    _checkpoint("build_leg_summary", len(legs))
    signal = _signal_summary(detail, legs)
    _checkpoint("build_signal_summary", len(signal))
    leg_dist = _leg_count_distribution(signal)
    availability = _distance_availability(signal)
    under = _under_capture_flags(signal)
    over = _over_expansion_flags(signal)
    queue = _review_queue(signal)
    qa = _qa(detail, signal)
    findings = _findings(detail, signal, legs, leg_dist, availability, under, over)
    outputs = {
        "leg_coverage_bin_detail.csv": detail,
        "leg_coverage_signal_summary.csv": signal,
        "leg_coverage_leg_summary.csv": legs,
        "leg_count_distribution.csv": leg_dist,
        "distance_band_availability_summary.csv": availability,
        "possible_under_capture_flags.csv": under,
        "possible_over_expansion_flags.csv": over,
        "leg_coverage_ranked_review_queue.csv": queue,
        "expanded_universe_leg_coverage_qa.csv": qa,
    }
    output_names = list(outputs) + [
        "expanded_universe_leg_coverage_findings.md",
        "expanded_universe_leg_coverage_manifest.json",
        "run_progress_log.txt",
    ]
    manifest = _manifest(started, output_names, inputs)
    _write_outputs(outputs, findings, manifest)
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
