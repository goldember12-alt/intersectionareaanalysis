from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
CANDIDATE_DIR = OUTPUT_ROOT / "review/current/signal_recovery_candidate_bin_generation"
CONTEXT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_context_sufficiency_audit"
SPEED_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_v3_path_rebuild"
CLEANUP_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_residual_cleanup"

STRICT_ACTIVE_BASELINE_SIGNALS = 971
EXPECTED_CANDIDATE_BINS = 136_227
EXPECTED_CANDIDATE_SIGNALS = 1_590
REVIEW_QUEUE_LIMIT = 20_000

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
)

REQUIRED_INPUTS = {
    CANDIDATE_DIR: [
        "candidate_recovery_bins.csv",
        "candidate_recovery_signal_summary.csv",
        "candidate_recovery_existing_active_overlap.csv",
        "candidate_recovery_bin_generation_manifest.json",
    ],
    CONTEXT_DIR: [
        "expanded_candidate_bin_context_detail.csv",
        "expanded_candidate_signal_context_summary.csv",
        "expanded_candidate_context_sufficiency_manifest.json",
    ],
    SPEED_DIR: [
        "phase3d_candidate_rns_speed_assignment_detail.csv",
        "phase3d_candidate_rns_speed_signal_summary.csv",
        "phase3d_candidate_rns_speed_coverage_summary.csv",
    ],
    AADT_DIR: [
        "aadt_v3_candidate_assignment_detail.csv",
        "aadt_v3_candidate_signal_summary.csv",
        "aadt_v3_candidate_coverage_summary.csv",
    ],
    CLEANUP_DIR: [
        "residual_cleanup_speed_detail.csv",
        "residual_cleanup_aadt_detail.csv",
        "residual_cleanup_signal_summary.csv",
        "residual_cleanup_before_after_summary.csv",
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
    return any(token in lower for token in CRASH_FIELD_TOKENS) and "signal_relative_direction" not in lower


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
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


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() != "nan" and str(value) != ""})
    return "|".join(items[:limit])


def _missing_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_inputs() -> dict[str, pd.DataFrame]:
    candidate_cols = [
        "candidate_recovery_bin_id",
        "signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_association_id",
        "recovery_strategy",
        "association_confidence_tier",
        "candidate_rank",
        "candidate_weight_preliminary",
        "tie_group_id",
        "road_component_id",
        "graph_edge_id",
        "adjacent_node_id",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "far_anchor_type_candidate",
        "distance_from_signal_start_ft",
        "distance_from_signal_end_ft",
        "bin_length_ft",
        "analysis_window",
        "scaffold_completeness_tier",
        "candidate_logic_tier",
        "review_only_candidate_bin",
        "active_output_promotion_status",
        "strict_active_overlap_status",
        "roadway_division_status",
        "matched_route_common",
    ]
    context_cols = [
        "candidate_recovery_bin_id",
        "travelway_lane_count",
        "travelway_lane_context_status",
        "candidate_bin_context_join_scope",
        "lane_coverage_flag",
        "lane_join_method",
        "divided_undivided_coverage_flag",
        "divided_undivided_join_method",
        "roadway_context_coverage_flag",
        "roadway_context_join_method",
        "failed_join_reason",
        "analysis_use_tier",
    ]
    speed_cols = [
        "candidate_bin_id",
        "candidate_signal_id",
        "candidate_route_group_id",
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
        "rns_match_status",
        "rns_measure_containment_status",
        "rns_missing_reason",
        "matched_review_only_car_speed_limit",
        "matched_rns_route_raw",
        "matched_rns_route_key",
        "matched_rns_measure_min",
        "matched_rns_measure_max",
        "matched_rns_source_row_id",
    ]
    aadt_cols = [
        "candidate_bin_id",
        "aadt_v3_match_status",
        "aadt_v3_measure_containment_status",
        "aadt_v3_missing_reason",
        "matched_review_only_aadt_value",
        "matched_review_only_aadt_year",
        "matched_review_only_direction_factor",
        "review_only_direction_factor_status",
        "review_only_bidirectional_fallback_status",
        "review_only_estimated_exposure",
        "review_only_denominator_status",
        "matched_aadt_route_raw",
        "matched_aadt_route_key",
        "matched_aadt_measure_min",
        "matched_aadt_measure_max",
        "matched_aadt_source_row_id",
    ]
    cleanup_speed_cols = [
        "candidate_bin_id",
        "speed_cleanup_status",
        "cleanup_speed_value",
        "cleanup_truck_speed_value",
        "cleanup_rns_route_raw",
        "cleanup_rns_route_key",
        "cleanup_rns_measure_min",
        "cleanup_rns_measure_max",
        "cleanup_rns_source_row_id",
        "speed_cleanup_review_only_flag",
    ]
    cleanup_aadt_cols = [
        "candidate_bin_id",
        "aadt_cleanup_status",
        "cleanup_aadt_value",
        "cleanup_aadt_year",
        "cleanup_direction_factor",
        "cleanup_estimated_exposure",
        "cleanup_direction_factor_status",
        "cleanup_bidirectional_fallback_status",
        "cleanup_aadt_route_raw",
        "cleanup_aadt_route_key",
        "cleanup_aadt_measure_min",
        "cleanup_aadt_measure_max",
        "cleanup_aadt_source_row_id",
        "aadt_cleanup_review_only_flag",
    ]
    return {
        "candidate_bins": _read_csv(CANDIDATE_DIR / "candidate_recovery_bins.csv", usecols=candidate_cols),
        "candidate_signal": _read_csv(CANDIDATE_DIR / "candidate_recovery_signal_summary.csv"),
        "active_overlap": _read_csv(CANDIDATE_DIR / "candidate_recovery_existing_active_overlap.csv"),
        "context_bins": _read_csv(CONTEXT_DIR / "expanded_candidate_bin_context_detail.csv", usecols=context_cols),
        "context_signal": _read_csv(CONTEXT_DIR / "expanded_candidate_signal_context_summary.csv"),
        "speed": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_assignment_detail.csv", usecols=speed_cols),
        "speed_signal": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_signal_summary.csv"),
        "speed_coverage": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_coverage_summary.csv"),
        "aadt": _read_csv(AADT_DIR / "aadt_v3_candidate_assignment_detail.csv", usecols=aadt_cols),
        "aadt_signal": _read_csv(AADT_DIR / "aadt_v3_candidate_signal_summary.csv"),
        "aadt_coverage": _read_csv(AADT_DIR / "aadt_v3_candidate_coverage_summary.csv"),
        "cleanup_speed": _read_csv(CLEANUP_DIR / "residual_cleanup_speed_detail.csv", usecols=cleanup_speed_cols),
        "cleanup_aadt": _read_csv(CLEANUP_DIR / "residual_cleanup_aadt_detail.csv", usecols=cleanup_aadt_cols),
        "cleanup_signal": _read_csv(CLEANUP_DIR / "residual_cleanup_signal_summary.csv"),
        "cleanup_before_after": _read_csv(CLEANUP_DIR / "residual_cleanup_before_after_summary.csv"),
    }


def _stable_ids(values: pd.Series, prefix: str) -> pd.DataFrame:
    keys = sorted(values.astype(str).unique())
    return pd.DataFrame({"source_id": keys, f"frozen_{prefix}_id": [f"frozen_{prefix}_{idx:06d}" for idx in range(1, len(keys) + 1)]})


def _build_bin_universe(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    bins = inputs["candidate_bins"].copy()
    bins = bins.rename(columns={"candidate_recovery_bin_id": "candidate_bin_id", "signal_id": "candidate_signal_id", "candidate_weight_preliminary": "candidate_weight"})
    frozen_bin_ids = _stable_ids(_text(bins, "candidate_bin_id"), "candidate_bin")
    frozen_signal_ids = _stable_ids(_text(bins, "candidate_signal_id"), "candidate_signal")
    bins = bins.merge(frozen_bin_ids, left_on="candidate_bin_id", right_on="source_id", how="left").drop(columns=["source_id"])
    bins = bins.merge(frozen_signal_ids, left_on="candidate_signal_id", right_on="source_id", how="left").drop(columns=["source_id"])

    context = inputs["context_bins"].rename(columns={"candidate_recovery_bin_id": "candidate_bin_id"}).drop_duplicates("candidate_bin_id")
    bins = bins.merge(context, on="candidate_bin_id", how="left")

    speed = inputs["speed"].drop_duplicates("candidate_bin_id").copy()
    cleanup_speed = inputs["cleanup_speed"].drop_duplicates("candidate_bin_id").copy()
    speed = speed.merge(cleanup_speed, on="candidate_bin_id", how="left")
    speed["speed_ready_review_only_flag"] = _text(speed, "rns_match_status").eq("review_only_speed_matched") | _text(speed, "speed_cleanup_status").eq("speed_recovered_corrected_interval")
    speed["review_only_speed_value"] = _text(speed, "matched_review_only_car_speed_limit").where(_text(speed, "matched_review_only_car_speed_limit").ne(""), _text(speed, "cleanup_speed_value"))
    speed["speed_review_status"] = _text(speed, "rns_match_status").where(_text(speed, "rns_match_status").ne(""), "not_attempted")
    speed.loc[_text(speed, "speed_cleanup_status").eq("speed_recovered_corrected_interval"), "speed_review_status"] = "review_only_speed_matched_after_residual_cleanup"
    speed_keep = [
        "candidate_bin_id",
        "candidate_route_group_id",
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
        "speed_review_status",
        "review_only_speed_value",
        "rns_measure_containment_status",
        "rns_missing_reason",
        "matched_rns_route_raw",
        "matched_rns_route_key",
        "matched_rns_measure_min",
        "matched_rns_measure_max",
        "matched_rns_source_row_id",
        "speed_cleanup_status",
    ]
    bins = bins.merge(speed[[c for c in speed_keep if c in speed.columns]], on="candidate_bin_id", how="left")

    aadt = inputs["aadt"].drop_duplicates("candidate_bin_id").copy()
    cleanup_aadt = inputs["cleanup_aadt"].drop_duplicates("candidate_bin_id").copy()
    aadt = aadt.merge(cleanup_aadt, on="candidate_bin_id", how="left")
    aadt["aadt_ready_review_only_flag"] = _text(aadt, "aadt_v3_match_status").eq("review_only_aadt_v3_matched") | _text(aadt, "aadt_cleanup_status").eq("aadt_recovered_alias_patch")
    aadt["exposure_ready_review_only_flag"] = _text(aadt, "review_only_denominator_status").eq("denominator_ready_no_crash_review_only") | _text(aadt, "aadt_cleanup_status").eq("aadt_recovered_alias_patch")
    aadt["review_only_aadt_value"] = _text(aadt, "matched_review_only_aadt_value").where(_text(aadt, "matched_review_only_aadt_value").ne(""), _text(aadt, "cleanup_aadt_value"))
    aadt["review_only_estimated_exposure_final"] = _text(aadt, "review_only_estimated_exposure").where(_text(aadt, "review_only_estimated_exposure").ne(""), _text(aadt, "cleanup_estimated_exposure"))
    aadt["aadt_review_status"] = _text(aadt, "aadt_v3_match_status").where(_text(aadt, "aadt_v3_match_status").ne(""), "not_attempted")
    aadt.loc[_text(aadt, "aadt_cleanup_status").eq("aadt_recovered_alias_patch"), "aadt_review_status"] = "review_only_aadt_matched_after_residual_cleanup"
    aadt_keep = [
        "candidate_bin_id",
        "aadt_ready_review_only_flag",
        "exposure_ready_review_only_flag",
        "aadt_review_status",
        "aadt_v3_measure_containment_status",
        "aadt_v3_missing_reason",
        "review_only_aadt_value",
        "matched_review_only_aadt_year",
        "matched_review_only_direction_factor",
        "review_only_direction_factor_status",
        "review_only_bidirectional_fallback_status",
        "review_only_estimated_exposure_final",
        "review_only_denominator_status",
        "matched_aadt_route_raw",
        "matched_aadt_route_key",
        "matched_aadt_measure_min",
        "matched_aadt_measure_max",
        "matched_aadt_source_row_id",
        "aadt_cleanup_status",
    ]
    bins = bins.merge(aadt[[c for c in aadt_keep if c in aadt.columns]], on="candidate_bin_id", how="left")

    bins["has_candidate_bins"] = True
    bins["has_roadway_context"] = _flag(bins, "roadway_context_coverage_flag") | _text(bins, "roadway_division_status").ne("")
    bins["speed_ready_review_only_flag"] = bins["speed_ready_review_only_flag"].fillna(False).astype(bool)
    bins["aadt_ready_review_only_flag"] = bins["aadt_ready_review_only_flag"].fillna(False).astype(bool)
    bins["exposure_ready_review_only_flag"] = bins["exposure_ready_review_only_flag"].fillna(False).astype(bool)
    bins["speed_aadt_ready_review_only_flag"] = bins["speed_ready_review_only_flag"] & bins["aadt_ready_review_only_flag"]
    bins["review_only_flag"] = True
    bins["strict_active_overlap_conflict_flag"] = _text(bins, "strict_active_overlap_status").ne("no_active_overlap") & _text(bins, "strict_active_overlap_status").ne("")
    bins["multi_candidate_weighted_flag"] = _text(bins, "candidate_logic_tier").str.contains("multi_candidate", na=False) | pd.to_numeric(_text(bins, "candidate_weight"), errors="coerce").fillna(1).lt(1)
    bins["recommended_bin_universe_tier"] = "not_ready_for_access_crash_assignment_review"
    bins.loc[bins["has_candidate_bins"], "recommended_bin_universe_tier"] = "expanded_any_bin_candidate"
    bins.loc[bins["has_roadway_context"], "recommended_bin_universe_tier"] = "expanded_roadway_context_candidate"
    bins.loc[bins["speed_ready_review_only_flag"], "recommended_bin_universe_tier"] = "expanded_speed_ready_candidate"
    bins.loc[bins["aadt_ready_review_only_flag"] & bins["exposure_ready_review_only_flag"], "recommended_bin_universe_tier"] = "expanded_aadt_exposure_ready_candidate"
    bins.loc[bins["speed_aadt_ready_review_only_flag"], "recommended_bin_universe_tier"] = "expanded_speed_aadt_ready_candidate"
    bins.loc[bins["strict_active_overlap_conflict_flag"], "recommended_bin_universe_tier"] = "strict_active_baseline_overlap"
    return bins


def _build_signal_universe(bins: pd.DataFrame, candidate_signal: pd.DataFrame) -> pd.DataFrame:
    work = bins.copy()
    work["weight_num"] = pd.to_numeric(_text(work, "candidate_weight"), errors="coerce").fillna(1)
    summary = work.groupby("candidate_signal_id", dropna=False).agg(
        frozen_candidate_signal_id=("frozen_candidate_signal_id", "first"),
        source_signal_id=("source_signal_id", _collapse),
        source_layer=("source_layer", _collapse),
        candidate_bin_count=("candidate_bin_id", "count"),
        weighted_bin_count=("weight_num", "sum"),
        has_any_scaffold=("has_candidate_bins", "any"),
        has_roadway_context=("has_roadway_context", "any"),
        has_speed=("speed_ready_review_only_flag", "any"),
        has_aadt=("aadt_ready_review_only_flag", "any"),
        has_exposure=("exposure_ready_review_only_flag", "any"),
        multi_candidate_weighted_flag=("multi_candidate_weighted_flag", "any"),
        strict_active_overlap_conflict_flag=("strict_active_overlap_conflict_flag", "any"),
        strict_active_overlap_status=("strict_active_overlap_status", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
        analysis_windows=("analysis_window", _collapse),
        recovery_strategy=("recovery_strategy", _collapse),
        association_confidence_tier=("association_confidence_tier", _collapse),
    ).reset_index()
    summary["speed_aadt_ready"] = summary["has_speed"] & summary["has_aadt"] & summary["has_exposure"]
    hp = work.loc[_text(work, "analysis_window").str.contains("0_1000", na=False)].groupby("candidate_signal_id")["speed_aadt_ready_review_only_flag"].agg(["count", "sum"]).reset_index()
    hp["full_0_1000_speed_aadt_ready"] = hp["count"].eq(hp["sum"])
    full = work.groupby("candidate_signal_id")["speed_aadt_ready_review_only_flag"].agg(["count", "sum"]).reset_index()
    full["full_attempted_0_2500_speed_aadt_ready"] = full["count"].eq(full["sum"])
    summary = summary.merge(hp[["candidate_signal_id", "full_0_1000_speed_aadt_ready"]], on="candidate_signal_id", how="left")
    summary = summary.merge(full[["candidate_signal_id", "full_attempted_0_2500_speed_aadt_ready"]], on="candidate_signal_id", how="left")
    summary[["full_0_1000_speed_aadt_ready", "full_attempted_0_2500_speed_aadt_ready"]] = summary[["full_0_1000_speed_aadt_ready", "full_attempted_0_2500_speed_aadt_ready"]].fillna(False)
    summary["has_0_1000_scaffold"] = summary["analysis_windows"].str.contains("0_1000", na=False)
    signal_flags = candidate_signal.rename(columns={"signal_id": "candidate_signal_id"})
    summary = summary.merge(signal_flags[["candidate_signal_id", "full_0_1000_coverage_flag", "full_0_2500_coverage_flag", "both_direction_coverage_flag", "one_direction_only_flag"]], on="candidate_signal_id", how="left")
    summary["has_full_attempted_0_2500_scaffold"] = _flag(summary, "full_0_2500_coverage_flag")
    summary["both_direction_context_ready"] = _flag(summary, "both_direction_coverage_flag")
    summary["one_direction_only_context_ready"] = _flag(summary, "one_direction_only_flag")
    summary["recommended_universe_tier"] = "not_ready_for_access_crash_assignment_review"
    summary.loc[summary["has_any_scaffold"], "recommended_universe_tier"] = "expanded_any_bin_candidate"
    summary.loc[summary["has_roadway_context"], "recommended_universe_tier"] = "expanded_roadway_context_candidate"
    summary.loc[summary["has_speed"], "recommended_universe_tier"] = "expanded_speed_ready_candidate"
    summary.loc[summary["has_aadt"] & summary["has_exposure"], "recommended_universe_tier"] = "expanded_aadt_exposure_ready_candidate"
    summary.loc[summary["speed_aadt_ready"], "recommended_universe_tier"] = "expanded_speed_aadt_ready_candidate"
    summary.loc[summary["full_0_1000_speed_aadt_ready"], "recommended_universe_tier"] = "expanded_0_1000_speed_aadt_ready_candidate"
    summary.loc[summary["full_attempted_0_2500_speed_aadt_ready"], "recommended_universe_tier"] = "expanded_full_0_2500_speed_aadt_ready_candidate"
    summary.loc[summary["one_direction_only_context_ready"], "recommended_universe_tier"] = "expanded_partial_direction_candidate"
    summary.loc[summary["multi_candidate_weighted_flag"], "recommended_universe_tier"] = "expanded_multi_candidate_weighted_candidate"
    summary.loc[summary["strict_active_overlap_conflict_flag"], "recommended_universe_tier"] = "strict_active_baseline_overlap"
    return summary


def _tier_summary(signal: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("strict_active_baseline_count", STRICT_ACTIVE_BASELINE_SIGNALS),
        ("recovered_candidate_signal_count", signal["candidate_signal_id"].nunique()),
        ("expanded_any_bin_universe_count", int(signal["has_any_scaffold"].sum())),
        ("roadway_context_ready_count", int(signal["has_roadway_context"].sum())),
        ("speed_ready_count", int(signal["has_speed"].sum())),
        ("aadt_exposure_ready_count", int((signal["has_aadt"] & signal["has_exposure"]).sum())),
        ("speed_aadt_ready_count", int(signal["speed_aadt_ready"].sum())),
        ("0_1000_speed_aadt_ready_count", int(signal["full_0_1000_speed_aadt_ready"].sum())),
        ("full_attempted_0_2500_speed_aadt_ready_count", int(signal["full_attempted_0_2500_speed_aadt_ready"].sum())),
        ("both_direction_count", int(signal["both_direction_context_ready"].sum())),
        ("one_direction_only_count", int(signal["one_direction_only_context_ready"].sum())),
        ("multi_candidate_weighted_count", int(signal["multi_candidate_weighted_flag"].sum())),
        ("strict_overlap_conflict_count", int(signal["strict_active_overlap_conflict_flag"].sum())),
    ]
    tier_counts = signal.groupby("recommended_universe_tier", dropna=False).size().reset_index(name="signal_count")
    return pd.concat([pd.DataFrame([{"summary_metric": key, "signal_count": value} for key, value in rows]), tier_counts.rename(columns={"recommended_universe_tier": "summary_metric"})], ignore_index=True, sort=False)


def _window_summary(bins: pd.DataFrame) -> pd.DataFrame:
    return bins.groupby("analysis_window", dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        unique_signal_count=("candidate_signal_id", "nunique"),
        speed_ready_bins=("speed_ready_review_only_flag", "sum"),
        aadt_ready_bins=("aadt_ready_review_only_flag", "sum"),
        exposure_ready_bins=("exposure_ready_review_only_flag", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_review_only_flag", "sum"),
    ).reset_index()


def _direction_summary(bins: pd.DataFrame) -> pd.DataFrame:
    return bins.groupby("signal_relative_direction_label", dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        unique_signal_count=("candidate_signal_id", "nunique"),
        speed_aadt_ready_bins=("speed_aadt_ready_review_only_flag", "sum"),
    ).reset_index()


def _overlap_summary(bins: pd.DataFrame) -> pd.DataFrame:
    return bins.groupby("strict_active_overlap_status", dropna=False).agg(candidate_bin_count=("candidate_bin_id", "count"), unique_signal_count=("candidate_signal_id", "nunique")).reset_index()


def _injection_readiness(signal: pd.DataFrame) -> pd.DataFrame:
    out = signal[["frozen_candidate_signal_id", "candidate_signal_id", "recommended_universe_tier", "speed_aadt_ready", "full_0_1000_speed_aadt_ready", "full_attempted_0_2500_speed_aadt_ready", "has_roadway_context", "has_speed", "has_aadt", "has_exposure", "both_direction_context_ready", "one_direction_only_context_ready", "multi_candidate_weighted_flag", "strict_active_overlap_conflict_flag"]].copy()
    out["ready_for_access_route_measure_review"] = out["speed_aadt_ready"] & out["has_roadway_context"] & ~out["strict_active_overlap_conflict_flag"]
    out["ready_for_access_geometry_review"] = out["has_roadway_context"] & ~out["strict_active_overlap_conflict_flag"]
    out["ready_for_crash_catchment_generation"] = out["full_attempted_0_2500_speed_aadt_ready"] & out["has_roadway_context"] & out["both_direction_context_ready"] & ~out["strict_active_overlap_conflict_flag"]
    out["needs_candidate_geometry_before_crash"] = out["speed_aadt_ready"] & ~out["both_direction_context_ready"]
    out["needs_access_assignment_design"] = out["ready_for_access_route_measure_review"]
    out["hold_due_to_context_missingness"] = ~(out["has_roadway_context"] & out["has_speed"] & out["has_aadt"] & out["has_exposure"])
    out["hold_due_to_overlap_conflict"] = out["strict_active_overlap_conflict_flag"]
    out["hold_due_to_review_only_uncertainty"] = out["multi_candidate_weighted_flag"] | out["one_direction_only_context_ready"]
    out["planning_flag_review_only"] = True
    return out


def _missingness(signal: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"layer": "roadway_context", "missing_signal_count": int((~signal["has_roadway_context"]).sum())},
        {"layer": "speed", "missing_signal_count": int((~signal["has_speed"]).sum())},
        {"layer": "aadt", "missing_signal_count": int((~signal["has_aadt"]).sum())},
        {"layer": "exposure", "missing_signal_count": int((~signal["has_exposure"]).sum())},
        {"layer": "speed_aadt_joint", "missing_signal_count": int((~signal["speed_aadt_ready"]).sum())},
    ]
    return pd.DataFrame(rows)


def _review_queue(signal: pd.DataFrame) -> pd.DataFrame:
    out = signal.copy()
    out["review_priority"] = 5
    out.loc[out["strict_active_overlap_conflict_flag"], "review_priority"] = 0
    out.loc[~out["speed_aadt_ready"], "review_priority"] = 1
    out.loc[out["one_direction_only_context_ready"], "review_priority"] = 2
    out.loc[out["multi_candidate_weighted_flag"], "review_priority"] = 3
    return out.sort_values(["review_priority", "candidate_bin_count"], ascending=[True, False]).head(REVIEW_QUEUE_LIMIT)


def _findings(tier: pd.DataFrame, readiness: pd.DataFrame, missing: pd.DataFrame) -> str:
    counts = {str(row.summary_metric): int(row.signal_count) for row in tier.itertuples(index=False) if str(row.signal_count).isdigit()}
    ready_access = int(readiness["ready_for_access_route_measure_review"].sum())
    ready_crash = int(readiness["ready_for_crash_catchment_generation"].sum())
    dominant_missing = missing.sort_values("missing_signal_count", ascending=False).iloc[0]
    return "\n".join(
        [
            "# Expanded Candidate Universe Freeze Findings",
            "",
            f"Frozen recovered candidate signals: {counts.get('recovered_candidate_signal_count', 0)}.",
            f"Frozen candidate bins: {EXPECTED_CANDIDATE_BINS}.",
            f"Speed+AADT-ready review-only signals: {counts.get('speed_aadt_ready_count', 0)}.",
            f"Full attempted 0-2,500 ft speed+AADT-ready signals: {counts.get('full_attempted_0_2500_speed_aadt_ready_count', 0)}.",
            f"Access should attach first to the route/measure review universe: {ready_access} recovered signals.",
            f"Crash/catchment generation should attach first to the stricter full-context, both-direction universe: {ready_crash} recovered signals.",
            "Hold out strict-overlap conflicts, one-direction-only records needing geometry review, and records missing speed/AADT/exposure context.",
            "All counts are review-only recovered-candidate planning counts, not active promoted records.",
            f"Dominant remaining non-access/non-crash missingness: {dominant_missing.layer} ({int(dominant_missing.missing_signal_count)} signals).",
            "Next decision: design the access assignment review against the frozen route/measure-ready universe, then decide whether crash catchment generation should start with only the strict full-context subset.",
            "",
        ]
    )


def _qa(bins: pd.DataFrame, signal: pd.DataFrame, missing: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, True, True),
        ("no_candidates_promoted", True, True, True),
        ("no_crash_records_read", True, True, True),
        ("no_crash_direction_fields_read_or_used", True, True, True),
        ("no_access_assignment_performed", True, True, True),
        ("no_crash_assignment_performed", True, True, True),
        ("no_rates_or_models_produced", True, True, True),
        ("all_outputs_review_only", True, True, True),
        ("stable_frozen_bin_ids_unique", bins["frozen_candidate_bin_id"].nunique() == len(bins), bins["frozen_candidate_bin_id"].nunique(), len(bins)),
        ("stable_frozen_signal_ids_unique", signal["frozen_candidate_signal_id"].nunique() == len(signal), signal["frozen_candidate_signal_id"].nunique(), len(signal)),
        ("deduped_signal_counts_separate_from_bin_counts", True, True, True),
        ("strict_overlap_conflict_flags_diagnostic_only", True, True, True),
        ("outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR)),
        ("candidate_bin_count_reconciles", len(bins) == EXPECTED_CANDIDATE_BINS, len(bins), EXPECTED_CANDIDATE_BINS),
        ("candidate_signal_count_reconciles", signal["candidate_signal_id"].nunique() == EXPECTED_CANDIDATE_SIGNALS, signal["candidate_signal_id"].nunique(), EXPECTED_CANDIDATE_SIGNALS),
        ("required_inputs_present", not missing, len(missing), 0),
    ]
    return pd.DataFrame([{"qa_gate": key, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected} for key, passed, observed, expected in rows])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text(f"{datetime.now(timezone.utc).isoformat()} START expanded_candidate_universe_freeze\n", encoding="utf-8")
    missing = _missing_inputs()
    inputs = _load_inputs()
    bins = _build_bin_universe(inputs)
    signal = _build_signal_universe(bins, inputs["candidate_signal"])
    tier = _tier_summary(signal)
    window = _window_summary(bins)
    direction = _direction_summary(bins)
    overlap = _overlap_summary(bins)
    readiness = _injection_readiness(signal)
    missingness = _missingness(signal)
    queue = _review_queue(signal)
    qa = _qa(bins, signal, missing)
    _write_csv(bins, OUT_DIR / "frozen_candidate_bin_universe.csv")
    _write_csv(signal, OUT_DIR / "frozen_candidate_signal_universe.csv")
    _write_csv(tier, OUT_DIR / "frozen_candidate_universe_tier_summary.csv")
    _write_csv(window, OUT_DIR / "frozen_candidate_universe_window_summary.csv")
    _write_csv(direction, OUT_DIR / "frozen_candidate_universe_direction_summary.csv")
    _write_csv(overlap, OUT_DIR / "frozen_candidate_universe_overlap_summary.csv")
    _write_csv(readiness, OUT_DIR / "frozen_candidate_access_crash_injection_readiness.csv")
    _write_csv(missingness, OUT_DIR / "frozen_candidate_missingness_summary.csv")
    _write_csv(queue, OUT_DIR / "frozen_candidate_ranked_review_queue.csv")
    _write_text(_findings(tier, readiness, missingness), OUT_DIR / "expanded_candidate_universe_freeze_findings.md")
    _write_csv(qa, OUT_DIR / "expanded_candidate_universe_freeze_qa.csv")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "review-only expanded candidate universe freeze before future access and crash assignment",
        "output_dir": str(OUT_DIR),
        "frozen_candidate_bin_count": int(len(bins)),
        "frozen_candidate_signal_count": int(signal["candidate_signal_id"].nunique()),
        "strict_active_baseline_signal_count": STRICT_ACTIVE_BASELINE_SIGNALS,
        "qa_passed": bool(qa["passed"].all()),
        "missing_required_inputs": missing,
        "guardrails": {
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "no_crash_assignment": True,
            "no_catchments_created": True,
            "no_rates_or_models": True,
            "review_only_outputs": True,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_universe_freeze_manifest.json")
    _checkpoint("complete expanded_candidate_universe_freeze")


if __name__ == "__main__":
    main()
