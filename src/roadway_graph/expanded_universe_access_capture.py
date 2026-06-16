from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_capture"

REFRESH_DIR = OUTPUT_ROOT / "review/current/expanded_universe_refresh_and_709_plan"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"
CONTEXT_347_DIR = OUTPUT_ROOT / "review/current/review_only_347_context_refresh"
DESIGN_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_design_diagnostic"

ACTIVE_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_bin_context_active.csv"
ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")
ACCESS_V1_DIR = OUTPUT_ROOT / "review/current/access_context_join"
ACCESS_V2_DIR = OUTPUT_ROOT / "review/current/access_context_join_v2"
ACCESS_MULTI_DIR = OUTPUT_ROOT / "review/current/access_v2_signal_relative_multi_assignment"
ACCESS_FANOUT_DIR = OUTPUT_ROOT / "review/current/access_v2_route_identity_fanout_diagnostic"

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
    REFRESH_DIR: ["refreshed_represented_signal_universe.csv", "refreshed_represented_universe_summary.csv"],
    FREEZE_DIR: [
        "frozen_candidate_bin_universe.csv",
        "frozen_candidate_signal_universe.csv",
        "frozen_candidate_access_crash_injection_readiness.csv",
    ],
    CONTEXT_347_DIR: ["review_only_347_context_bin_detail.csv", "review_only_347_context_signal_summary.csv"],
    DESIGN_DIR: [
        "access_target_universe.csv",
        "untyped_access_design_detail.csv",
        "typed_access_v2_design_detail.csv",
        "access_strategy_comparison.csv",
        "expanded_universe_access_design_manifest.json",
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


def _read_parquet(path: Path, *, columns: list[str]) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    blocked = [column for column in columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash/direction fields from {path}: {blocked}")
    try:
        out = pd.read_parquet(path, columns=columns)
    except Exception:
        out = pd.read_parquet(path)
        out = out[[column for column in columns if column in out.columns]].copy()
    out = out.drop(columns=[column for column in out.columns if _blocked_column(column)], errors="ignore")
    for column in out.columns:
        if column != "geometry":
            out[column] = out[column].astype("string").fillna("")
    _checkpoint(f"read_complete {path.name}", len(out))
    return out.drop(columns=["geometry"], errors="ignore")


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
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


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


def _distance_band(start_ft: pd.Series, end_ft: pd.Series) -> pd.Series:
    midpoint = (pd.to_numeric(start_ft, errors="coerce") + pd.to_numeric(end_ft, errors="coerce")) / 2
    return pd.cut(
        midpoint,
        bins=[-0.001, 250, 500, 1000, 1500, 2500],
        labels=["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"],
    ).astype("string").fillna("outside_0_2500ft")


def _missing_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    for path in [ACTIVE_CONTEXT_FILE, ACCESS_V1_FILE, ACCESS_V2_FILE]:
        if not path.exists():
            missing.append(str(path))
    return missing


def _load_inputs() -> dict[str, pd.DataFrame]:
    active_cols = [
        "reference_directional_bin_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "signal_relative_direction",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "far_anchor_type",
        "segment_length_ft",
        "source_route_key_v2",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "catchment_status",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
    ]
    frozen_bin_cols = [
        "frozen_candidate_bin_id",
        "frozen_candidate_signal_id",
        "candidate_bin_id",
        "candidate_signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_association_id",
        "recovery_strategy",
        "association_confidence_tier",
        "candidate_rank",
        "candidate_weight",
        "tie_group_id",
        "road_component_id",
        "graph_edge_id",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "distance_from_signal_start_ft",
        "distance_from_signal_end_ft",
        "bin_length_ft",
        "analysis_window",
        "scaffold_completeness_tier",
        "strict_active_overlap_status",
        "roadway_division_status",
        "route_id",
        "route_common",
        "route_name",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "speed_ready_review_only_flag",
        "aadt_ready_review_only_flag",
        "exposure_ready_review_only_flag",
        "speed_aadt_ready_review_only_flag",
        "has_roadway_context",
        "multi_candidate_weighted_flag",
        "review_only_flag",
        "recommended_bin_universe_tier",
    ]
    review_bin_cols = [
        "review_only_347_bin_id",
        "candidate_bin_id",
        "signal_id",
        "candidate_signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_association_id",
        "recovery_strategy",
        "association_confidence_tier",
        "candidate_rank",
        "candidate_weight",
        "tie_group_id",
        "road_component_id",
        "graph_edge_id",
        "source_road_row_id",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "candidate_bin_start_ft",
        "candidate_bin_end_ft",
        "candidate_bin_length_ft",
        "analysis_window",
        "scaffold_completeness_tier",
        "strict_active_overlap_status",
        "roadway_division_status",
        "route_id",
        "route_common",
        "route_name",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "partial_one_sided_flag",
        "has_roadway_context",
        "has_speed",
        "has_aadt",
        "has_exposure",
        "review_only_flag",
    ]
    return {
        "signals": _read_csv(REFRESH_DIR / "refreshed_represented_signal_universe.csv"),
        "refresh_summary": _read_csv(REFRESH_DIR / "refreshed_represented_universe_summary.csv"),
        "frozen_signals": _read_csv(FREEZE_DIR / "frozen_candidate_signal_universe.csv"),
        "readiness": _read_csv(FREEZE_DIR / "frozen_candidate_access_crash_injection_readiness.csv"),
        "frozen_bins": _read_csv(FREEZE_DIR / "frozen_candidate_bin_universe.csv", usecols=frozen_bin_cols),
        "review_347_bins": _read_csv(CONTEXT_347_DIR / "review_only_347_context_bin_detail.csv", usecols=review_bin_cols),
        "review_347_signals": _read_csv(CONTEXT_347_DIR / "review_only_347_context_signal_summary.csv"),
        "design_target": _read_csv(DESIGN_DIR / "access_target_universe.csv"),
        "design_untyped": _read_csv(DESIGN_DIR / "untyped_access_design_detail.csv"),
        "design_typed": _read_csv(DESIGN_DIR / "typed_access_v2_design_detail.csv"),
        "design_strategy": _read_csv(DESIGN_DIR / "access_strategy_comparison.csv"),
        "active_bins": _read_csv(ACTIVE_CONTEXT_FILE, usecols=active_cols),
        "access_v1": _read_parquet(ACCESS_V1_FILE, columns=["id", "_rte_nm", "_m", "Stage1_SourceGDB", "Stage1_SourceLayer"]),
        "access_v2": _read_parquet(
            ACCESS_V2_FILE,
            columns=[
                "access_v2_source_priority",
                "access_v2_source_row_id",
                "access_v2_source_gdb",
                "access_v2_source_layer",
                "route_name",
                "route_measure",
                "access_control_category",
                "access_control_code",
                "access_direction_normalized",
            ],
        ),
        "active_untyped_joined": _read_csv(ACCESS_V1_DIR / "access_points_joined_to_stable_universe.csv"),
        "active_untyped_ambiguous": _read_csv(ACCESS_V1_DIR / "access_points_ambiguous_bin_matches.csv"),
        "active_typed_joined": _read_csv(ACCESS_V2_DIR / "access_v2_points_joined_to_stable_universe.csv"),
        "active_typed_ambiguous": _read_csv(ACCESS_V2_DIR / "access_v2_points_ambiguous_bin_matches.csv"),
        "prior_typed_multi": _read_csv(ACCESS_MULTI_DIR / "access_v2_multi_assignment_candidates.csv"),
        "prior_fanout": _read_csv(ACCESS_FANOUT_DIR / "access_v2_route_compatible_decomposition.csv"),
    }


def _prepare_access_sources(inputs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    v1 = inputs["access_v1"].copy()
    v1["access_point_id"] = np.where(_text(v1, "id").ne(""), _text(v1, "id"), v1.index.astype(str))
    v1["route_name"] = _text(v1, "_rte_nm")
    v1["route_measure_num"] = _num(v1, "_m")
    v1["route_key"] = v1["route_name"].map(_route_key)
    v1["source_layer_name"] = _text(v1, "Stage1_SourceLayer")
    v1 = v1.loc[v1["route_key"].ne("") & v1["route_measure_num"].notna()].copy()

    v2 = inputs["access_v2"].copy()
    v2["access_point_id"] = _text(v2, "access_v2_source_priority") + ":" + _text(v2, "access_v2_source_row_id")
    v2["route_name"] = _text(v2, "route_name")
    v2["route_measure_num"] = _num(v2, "route_measure")
    v2["route_key"] = v2["route_name"].map(_route_key)
    v2["access_control_category"] = _text(v2, "access_control_category").replace("", "unknown")
    v2.loc[~v2["access_control_category"].isin(TYPED_CATEGORIES), "access_control_category"] = "other_review"
    v2["source_layer_name"] = _text(v2, "access_v2_source_layer")
    v2 = v2.loc[v2["route_key"].ne("") & v2["route_measure_num"].notna()].copy()
    return v1, v2


def _represented_keys(signals: pd.DataFrame) -> tuple[set[str], set[str], set[str]]:
    target_ids = set(_text(signals, "candidate_signal_id_refreshed")) | set(_text(signals, "prior_candidate_signal_id"))
    source_ids = set(_text(signals, "source_signal_id"))
    strict_ids = {value for value in target_ids if value.startswith("signal_")}
    return target_ids, source_ids, strict_ids


def _build_candidate_bins(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    target_ids, source_ids, _ = _represented_keys(inputs["signals"])
    frozen = inputs["frozen_bins"].copy()
    frozen["target_bin_source"] = "expanded_candidate_universe_freeze"
    frozen["target_bin_id"] = _text(frozen, "frozen_candidate_bin_id")
    frozen["target_signal_id"] = _text(frozen, "candidate_signal_id")
    frozen["distance_start_ft"] = _num(frozen, "distance_from_signal_start_ft")
    frozen["distance_end_ft"] = _num(frozen, "distance_from_signal_end_ft")
    frozen["partial_one_sided_flag"] = ""
    frozen["source_road_row_id"] = ""
    frozen["speed_ready_flag"] = _text(frozen, "speed_ready_review_only_flag")
    frozen["aadt_ready_flag"] = _text(frozen, "aadt_ready_review_only_flag")
    frozen["speed_aadt_ready_flag"] = _text(frozen, "speed_aadt_ready_review_only_flag")

    review = inputs["review_347_bins"].copy()
    review["target_bin_source"] = "review_only_347_context_refresh"
    review["target_bin_id"] = _text(review, "review_only_347_bin_id")
    review["target_signal_id"] = _text(review, "signal_id")
    review["frozen_candidate_bin_id"] = ""
    review["frozen_candidate_signal_id"] = ""
    review["distance_start_ft"] = _num(review, "candidate_bin_start_ft")
    review["distance_end_ft"] = _num(review, "candidate_bin_end_ft")
    review["speed_ready_flag"] = _text(review, "has_speed")
    review["aadt_ready_flag"] = _text(review, "has_aadt")
    review["speed_aadt_ready_flag"] = (_flag(review, "has_speed") & _flag(review, "has_aadt")).astype(str)
    review["multi_candidate_weighted_flag"] = ""
    review["recommended_bin_universe_tier"] = "review_only_347_addition"

    common = [
        "target_bin_source",
        "target_bin_id",
        "frozen_candidate_bin_id",
        "frozen_candidate_signal_id",
        "candidate_bin_id",
        "target_signal_id",
        "candidate_signal_id",
        "source_signal_id",
        "source_layer",
        "candidate_association_id",
        "recovery_strategy",
        "association_confidence_tier",
        "candidate_rank",
        "candidate_weight",
        "tie_group_id",
        "road_component_id",
        "graph_edge_id",
        "source_road_row_id",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "distance_start_ft",
        "distance_end_ft",
        "analysis_window",
        "scaffold_completeness_tier",
        "strict_active_overlap_status",
        "roadway_division_status",
        "route_id",
        "route_common",
        "route_name",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "partial_one_sided_flag",
        "has_roadway_context",
        "speed_ready_flag",
        "aadt_ready_flag",
        "speed_aadt_ready_flag",
        "multi_candidate_weighted_flag",
        "review_only_flag",
        "recommended_bin_universe_tier",
    ]
    bins = pd.concat([frozen.reindex(columns=common), review.reindex(columns=common)], ignore_index=True)
    bins = bins.loc[
        _text(bins, "target_signal_id").isin(target_ids)
        | _text(bins, "candidate_signal_id").isin(target_ids)
        | _text(bins, "source_signal_id").isin(source_ids)
    ].copy()
    bins["route_key"] = _text(bins, "normalized_candidate_route_key")
    bins.loc[bins["route_key"].eq(""), "route_key"] = _text(bins.loc[bins["route_key"].eq("")], "candidate_route_name_rns_norm")
    bins.loc[bins["route_key"].eq(""), "route_key"] = _text(bins.loc[bins["route_key"].eq("")], "route_name")
    bins["route_key"] = bins["route_key"].map(_route_key)
    bins["measure_low"] = pd.concat([_num(bins, "candidate_measure_min"), _num(bins, "candidate_measure_max")], axis=1).min(axis=1)
    bins["measure_high"] = pd.concat([_num(bins, "candidate_measure_min"), _num(bins, "candidate_measure_max")], axis=1).max(axis=1)
    bins["route_measure_ready"] = bins["route_key"].ne("") & bins["measure_low"].notna() & bins["measure_high"].notna()
    bins["distance_band"] = _distance_band(bins["distance_start_ft"], bins["distance_end_ft"])
    bins["candidate_weight_num"] = _num(bins, "candidate_weight").fillna(1.0)
    bins.loc[bins["candidate_weight_num"].le(0), "candidate_weight_num"] = 1.0
    bins["assignment_geometry_status"] = "candidate_route_measure_only_no_catchment_geometry"
    return bins


def _build_active_bins(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    _, _, strict_ids = _represented_keys(inputs["signals"])
    active = inputs["active_bins"].copy()
    active = active.loc[_text(active, "reference_signal_id").isin(strict_ids)].copy()
    out = pd.DataFrame()
    out["target_bin_source"] = "strict_active_existing_context"
    out["target_bin_id"] = _text(active, "reference_directional_bin_id")
    out["frozen_candidate_bin_id"] = ""
    out["frozen_candidate_signal_id"] = "strict_baseline_" + _text(active, "reference_signal_id")
    out["candidate_bin_id"] = ""
    out["target_signal_id"] = _text(active, "reference_signal_id")
    out["candidate_signal_id"] = _text(active, "reference_signal_id")
    out["source_signal_id"] = ""
    out["source_layer"] = ""
    out["candidate_association_id"] = ""
    out["recovery_strategy"] = "strict_active_baseline"
    out["association_confidence_tier"] = "strict_active_baseline"
    out["candidate_rank"] = ""
    out["candidate_weight"] = "1"
    out["tie_group_id"] = ""
    out["road_component_id"] = ""
    out["graph_edge_id"] = ""
    out["source_road_row_id"] = ""
    out["signal_relative_direction_label"] = _text(active, "signal_relative_direction")
    out["direction_confidence_status"] = "strict_active_roadway_derived"
    out["distance_start_ft"] = _num(active, "bin_start_ft_from_reference_signal")
    out["distance_end_ft"] = _num(active, "bin_end_ft_from_reference_signal")
    out["analysis_window"] = _text(active, "distance_window").replace(
        {"high_priority_0_1000ft": "0_1000", "sensitivity_1000_2500ft": "1000_2500"}
    )
    out["scaffold_completeness_tier"] = "strict_active"
    out["strict_active_overlap_status"] = "strict_active_baseline"
    out["roadway_division_status"] = _text(active, "roadway_representation_type")
    out["route_id"] = ""
    out["route_common"] = ""
    out["route_name"] = ""
    out["normalized_candidate_route_key"] = _text(active, "source_route_key_v2")
    out["candidate_route_name_rns_norm"] = ""
    out["candidate_measure_min"] = _num(active, "source_RTE_FROM_M").astype("string").fillna("")
    out["candidate_measure_max"] = _num(active, "source_RTE_TO_MSR").astype("string").fillna("")
    out["candidate_midpoint_measure"] = ""
    out["candidate_measure_length"] = ""
    out["partial_one_sided_flag"] = "False"
    out["has_roadway_context"] = "True"
    out["speed_ready_flag"] = ""
    out["aadt_ready_flag"] = ""
    out["speed_aadt_ready_flag"] = ""
    out["multi_candidate_weighted_flag"] = "False"
    out["review_only_flag"] = "False"
    out["recommended_bin_universe_tier"] = "strict_active_baseline"
    out["route_key"] = _text(active, "source_route_key_v2").map(_route_key)
    out["measure_low"] = pd.concat([_num(active, "source_RTE_FROM_M"), _num(active, "source_RTE_TO_MSR")], axis=1).min(axis=1)
    out["measure_high"] = pd.concat([_num(active, "source_RTE_FROM_M"), _num(active, "source_RTE_TO_MSR")], axis=1).max(axis=1)
    out["route_measure_ready"] = out["route_key"].ne("") & out["measure_low"].notna() & out["measure_high"].notna()
    out["distance_band"] = _distance_band(out["distance_start_ft"], out["distance_end_ft"])
    out["candidate_weight_num"] = 1.0
    out["assignment_geometry_status"] = "active_existing_geometry_catchment_available"
    return out.drop_duplicates("target_bin_id")


def _build_access_target_bins(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    target = inputs["design_target"].copy()
    signal_meta = target[
        [
            "dedup_signal_key",
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
            "represented_source",
            "review_only_addition_status",
            "refreshed_universe_tier",
        ]
    ].drop_duplicates("candidate_signal_id_refreshed")
    bins = pd.concat([_build_active_bins(inputs), _build_candidate_bins(inputs)], ignore_index=True, sort=False)
    bins = bins.merge(signal_meta, left_on="target_signal_id", right_on="candidate_signal_id_refreshed", how="left", suffixes=("", "_signal"))
    for col in ["source_signal_id", "source_layer", "frozen_candidate_signal_id"]:
        signal_col = f"{col}_signal"
        if signal_col in bins.columns:
            bins[col] = _text(bins, col)
            bins.loc[bins[col].eq(""), col] = _text(bins.loc[bins[col].eq("")], signal_col)
    bins["target_bin_review_only_status"] = np.where(bins["target_bin_source"].eq("strict_active_existing_context"), "strict_active_provenance_review_copy", "review_only_candidate_bin")
    bins["distance_length_ft"] = (pd.to_numeric(bins["distance_end_ft"], errors="coerce") - pd.to_numeric(bins["distance_start_ft"], errors="coerce")).abs()
    return bins.drop_duplicates("target_bin_id")


def _interval_assignments(
    bins: pd.DataFrame,
    points: pd.DataFrame,
    *,
    layer: str,
    source_method: str,
    category_col: str | None = None,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    ready = bins.loc[bins["route_measure_ready"]].copy()
    if ready.empty or points.empty:
        return pd.DataFrame()
    point_groups = {key: group.sort_values("route_measure_num") for key, group in points.groupby("route_key", dropna=False)}
    for route_key, bin_group in ready.groupby("route_key", dropna=False):
        p = point_groups.get(route_key)
        if p is None or p.empty or route_key == "":
            continue
        measures = p["route_measure_num"].to_numpy(dtype=float)
        for bin_row in bin_group.itertuples(index=False):
            low = float(bin_row.measure_low)
            high = float(bin_row.measure_high)
            left = np.searchsorted(measures, low, side="left")
            right = np.searchsorted(measures, high, side="right")
            if right <= left:
                continue
            matched = p.iloc[left:right].copy()
            matched["target_bin_id"] = bin_row.target_bin_id
            matched["target_signal_id"] = bin_row.target_signal_id
            matched["signal_relative_direction"] = bin_row.signal_relative_direction_label
            matched["analysis_window"] = bin_row.analysis_window
            matched["distance_band"] = bin_row.distance_band
            matched["distance_length_ft"] = bin_row.distance_length_ft
            matched["candidate_weight_num"] = bin_row.candidate_weight_num
            matched["tie_group_id"] = bin_row.tie_group_id
            matched["target_bin_source"] = bin_row.target_bin_source
            matched["assignment_method"] = source_method
            matched["route_measure_match_status"] = "route_measure_point_contained_in_bin_interval"
            matched["assignment_confidence_status"] = "review_only_route_measure_interval_capture"
            matched["missing_uncertain_reason"] = ""
            rows.append(matched)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True, sort=False)
    out["access_layer"] = layer
    out["access_product_unweighted"] = f"{layer}_unweighted_double_counted"
    out["access_product_weighted"] = f"{layer}_source_preserving_weighted"
    if category_col is None:
        out["access_control_category"] = "untyped"
    else:
        out["access_control_category"] = _text(out, category_col).replace("", "unknown")
    return out


def _active_geometry_assignments(frame: pd.DataFrame, bins: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    if layer == "untyped":
        work["access_point_id"] = _text(work, "access_id")
        work["route_name"] = _text(work, "_rte_nm")
        work["access_control_category"] = "untyped"
    else:
        work["access_point_id"] = _text(work, "access_v2_source_priority") + ":" + _text(work, "access_v2_source_row_id")
        work.loc[work["access_point_id"].eq(":"), "access_point_id"] = _text(work.loc[work["access_point_id"].eq(":")], "access_v2_uid")
        work["route_name"] = _text(work, "route_name")
        work["access_control_category"] = _text(work, "access_control_category").replace("", "unknown")
        work.loc[~work["access_control_category"].isin(TYPED_CATEGORIES), "access_control_category"] = "other_review"
    work = work.rename(columns={"reference_directional_bin_id": "target_bin_id", "reference_signal_id": "target_signal_id"})
    keep = [
        "access_point_id",
        "target_bin_id",
        "target_signal_id",
        "route_name",
        "access_control_category",
        "signal_relative_direction",
        "nearest_access_distance_ft",
        "access_match_status",
        "matched_bin_count",
    ]
    work = work[[c for c in keep if c in work.columns]].copy()
    work = work.merge(
        bins[
            [
                "target_bin_id",
                "analysis_window",
                "distance_band",
                "distance_length_ft",
                "candidate_weight_num",
                "tie_group_id",
                "target_bin_source",
            ]
        ],
        on="target_bin_id",
        how="left",
    )
    work = work.loc[work["target_signal_id"].isin(set(_text(bins, "target_signal_id")))].copy()
    work["access_layer"] = layer
    work["access_product_unweighted"] = f"{layer}_unweighted_double_counted"
    work["access_product_weighted"] = f"{layer}_source_preserving_weighted"
    work["assignment_method"] = "existing_active_geometry_catchment"
    work["route_measure_match_status"] = "geometry_catchment_assignment_from_prior_active_output"
    work["assignment_confidence_status"] = "existing_active_access_context_provenance"
    work["missing_uncertain_reason"] = ""
    work["candidate_weight_num"] = pd.to_numeric(work["candidate_weight_num"], errors="coerce").fillna(1.0)
    return work


def _finalize_assignments(frame: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["access_point_id"] = _text(out, "access_point_id")
    out = out.loc[out["access_point_id"].ne("") & _text(out, "target_bin_id").ne("")].copy()
    out = out.drop_duplicates(["access_point_id", "target_bin_id", "access_layer", "access_control_category", "assignment_method"])
    fanout = out.groupby("access_point_id", dropna=False)["target_bin_id"].nunique().rename("assignment_fanout_count").reset_index()
    out = out.merge(fanout, on="access_point_id", how="left")
    out["assignment_fanout_count"] = pd.to_numeric(out["assignment_fanout_count"], errors="coerce").fillna(1)
    out["unweighted_access_count"] = 1.0
    out["source_preserving_weighted_access_count"] = 1.0 / out["assignment_fanout_count"]
    out["candidate_source_weighted_access_count"] = out["source_preserving_weighted_access_count"] * pd.to_numeric(out["candidate_weight_num"], errors="coerce").fillna(1.0)
    out["multi_assignment_flag"] = out["assignment_fanout_count"].gt(1)
    out["review_only_assignment_status"] = "review_only_not_active_not_promoted"
    out["not_active"] = True
    out["not_policy_ready"] = True
    keep = [
        "access_layer",
        "access_product_unweighted",
        "access_product_weighted",
        "access_point_id",
        "access_control_category",
        "route_name",
        "route_key",
        "route_measure_num",
        "target_signal_id",
        "target_bin_id",
        "target_bin_source",
        "signal_relative_direction",
        "analysis_window",
        "distance_band",
        "distance_length_ft",
        "assignment_method",
        "route_measure_match_status",
        "assignment_confidence_status",
        "missing_uncertain_reason",
        "assignment_fanout_count",
        "multi_assignment_flag",
        "unweighted_access_count",
        "source_preserving_weighted_access_count",
        "candidate_source_weighted_access_count",
        "candidate_weight_num",
        "tie_group_id",
        "review_only_assignment_status",
        "not_active",
        "not_policy_ready",
    ]
    for col in keep:
        if col not in out.columns:
            out[col] = ""
    return out[keep].copy()


def _capture_untyped(inputs: dict[str, pd.DataFrame], bins: pd.DataFrame, access_v1: pd.DataFrame) -> pd.DataFrame:
    active = pd.concat(
        [
            _active_geometry_assignments(inputs["active_untyped_joined"], bins, layer="untyped"),
            _active_geometry_assignments(inputs["active_untyped_ambiguous"], bins, layer="untyped"),
        ],
        ignore_index=True,
        sort=False,
    )
    candidate_bins = bins.loc[~bins["target_bin_source"].eq("strict_active_existing_context")].copy()
    interval = _interval_assignments(candidate_bins, access_v1, layer="untyped", source_method="route_measure_point_containment_or_fanout")
    return _finalize_assignments(pd.concat([active, interval], ignore_index=True, sort=False), layer="untyped")


def _capture_typed(inputs: dict[str, pd.DataFrame], bins: pd.DataFrame, access_v2: pd.DataFrame) -> pd.DataFrame:
    active = pd.concat(
        [
            _active_geometry_assignments(inputs["active_typed_joined"], bins, layer="typed_v2"),
            _active_geometry_assignments(inputs["active_typed_ambiguous"], bins, layer="typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    candidate_bins = bins.loc[~bins["target_bin_source"].eq("strict_active_existing_context")].copy()
    interval = _interval_assignments(
        candidate_bins,
        access_v2,
        layer="typed_v2",
        source_method="route_measure_point_containment_or_weighted_fanout",
        category_col="access_control_category",
    )
    return _finalize_assignments(pd.concat([active, interval], ignore_index=True, sort=False), layer="typed_v2")


def _summary(frame: pd.DataFrame, bins: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    specs = [
        ("bin", ["target_signal_id", "target_bin_id", "signal_relative_direction", "analysis_window", "distance_band"]),
        ("signal_window", ["target_signal_id", "signal_relative_direction", "analysis_window"]),
        ("signal", ["target_signal_id"]),
    ]
    length_by_bin = bins.set_index("target_bin_id")["distance_length_ft"].to_dict()
    for grain, group_cols in specs:
        work = frame.copy()
        grouped = (
            work.groupby(group_cols, dropna=False)
            .agg(
                source_access_point_count=("access_point_id", "nunique"),
                unweighted_access_count=("unweighted_access_count", "sum"),
                weighted_access_count=("source_preserving_weighted_access_count", "sum"),
                candidate_source_weighted_access_count=("candidate_source_weighted_access_count", "sum"),
                assignment_count=("access_point_id", "size"),
                max_assignment_fanout=("assignment_fanout_count", "max"),
                multi_assignment_count=("multi_assignment_flag", "sum"),
                assignment_methods=("assignment_method", _collapse),
                route_measure_match_status=("route_measure_match_status", _collapse),
                assignment_confidence_status=("assignment_confidence_status", _collapse),
                missing_uncertain_reason=("missing_uncertain_reason", _collapse),
            )
            .reset_index()
        )
        if grain == "bin":
            grouped["represented_length_ft"] = grouped["target_bin_id"].map(length_by_bin)
        else:
            length_cols = group_cols.copy()
            length_base = bins.groupby(length_cols, dropna=False)["distance_length_ft"].sum().reset_index(name="represented_length_ft") if all(c in bins.columns for c in length_cols) else pd.DataFrame()
            grouped = grouped.merge(length_base, on=length_cols, how="left") if not length_base.empty else grouped
        if "represented_length_ft" not in grouped.columns:
            grouped["represented_length_ft"] = 0
        grouped["represented_length_ft"] = pd.to_numeric(grouped["represented_length_ft"], errors="coerce").fillna(0)
        grouped["access_density_per_1000ft_unweighted"] = np.where(
            grouped["represented_length_ft"].gt(0),
            grouped["unweighted_access_count"] / grouped["represented_length_ft"] * 1000,
            np.nan,
        )
        grouped["access_density_per_1000ft_weighted"] = np.where(
            grouped["represented_length_ft"].gt(0),
            grouped["weighted_access_count"] / grouped["represented_length_ft"] * 1000,
            np.nan,
        )
        grouped["summary_grain"] = grain
        grouped["access_layer"] = layer
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _coverage(untyped: pd.DataFrame, typed: pd.DataFrame, bins: pd.DataFrame, design_untyped: pd.DataFrame, design_typed: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for layer, frame, design in [("untyped", untyped, design_untyped), ("typed_v2", typed, design_typed)]:
        signal_any = set(_text(frame, "target_signal_id"))
        window_0_1000 = set(frame.loc[_text(frame, "analysis_window").isin({"0_1000", "high_priority_0_1000ft"}), "target_signal_id"].fillna("").astype(str))
        full_attempted = (
            set(design.loc[_flag(design, "full_attempted_0_2500_speed_aadt_ready"), "target_signal_id"].fillna("").astype(str))
            if "full_attempted_0_2500_speed_aadt_ready" in design.columns and "target_signal_id" in design.columns
            else set()
        )
        if "geometry_required_signal" in design.columns:
            geometry_needed = int(_flag(design, "geometry_required_signal").sum())
        elif "recommended_typed_access_assignment_method" in design.columns:
            method_text = _text(design, "recommended_typed_access_assignment_method")
            geometry_needed = int(method_text.str.contains("geometry|sparse_zero_review", case=False, regex=True, na=False).sum())
        else:
            geometry_needed = 0
        rows.extend(
            [
                {"access_layer": layer, "metric": "signals_with_any_access_assignment", "count": len(signal_any), "note": "Deduplicated target_signal_id count."},
                {"access_layer": layer, "metric": "signals_with_0_1000ft_access_assignment", "count": len(window_0_1000), "note": "Signals with assignment in 0-1,000 ft analysis window."},
                {
                    "access_layer": layer,
                    "metric": "full_attempted_0_2500ft_signals_with_access_assignment",
                    "count": len(signal_any & full_attempted) if full_attempted else 0,
                    "note": "Intersection of assignment signals with full attempted 0-2,500 ft readiness flag.",
                },
                {"access_layer": layer, "metric": "bins_with_access_assignment", "count": int(_text(frame, "target_bin_id").nunique()), "note": "Deduplicated bin count."},
                {
                    "access_layer": layer,
                    "metric": "signal_windows_with_access_assignment",
                    "count": int(frame[["target_signal_id", "signal_relative_direction", "analysis_window"]].drop_duplicates().shape[0]) if not frame.empty else 0,
                    "note": "Signal-direction-window count.",
                },
                {
                    "access_layer": layer,
                    "metric": "signals_with_fanout_multi_assignment",
                    "count": int(frame.loc[frame["multi_assignment_flag"].astype(bool), "target_signal_id"].fillna("").astype(str).nunique()) if not frame.empty else 0,
                    "note": "Signals with at least one access point assigned to multiple contexts.",
                },
                {
                    "access_layer": layer,
                    "metric": "signals_requiring_geometry_catchment_for_more_trusted_assignment",
                    "count": geometry_needed,
                    "note": "Design diagnostic geometry/catchment-needed or sparse-zero-review signal count.",
                },
                {"access_layer": layer, "metric": "unweighted_assignment_total", "count": round(float(pd.to_numeric(frame.get("unweighted_access_count"), errors="coerce").fillna(0).sum()), 6), "note": "Double-counted assignment total."},
                {"access_layer": layer, "metric": "source_preserving_weighted_assignment_total", "count": round(float(pd.to_numeric(frame.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6), "note": "Each source access point sums to one across its assignment fanout."},
            ]
        )
    return pd.DataFrame(rows)


def _fanout_summary(untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        if frame.empty:
            rows.append({"access_layer": layer, "assignment_fanout_count": 0, "source_access_point_count": 0, "assignment_count": 0, "unweighted_access_count": 0, "weighted_access_count": 0})
            continue
        by_point = frame.drop_duplicates(["access_point_id", "assignment_fanout_count"]).copy()
        dist = by_point.groupby("assignment_fanout_count", dropna=False)["access_point_id"].nunique().reset_index(name="source_access_point_count")
        assign = frame.groupby("assignment_fanout_count", dropna=False).agg(
            assignment_count=("access_point_id", "size"),
            unweighted_access_count=("unweighted_access_count", "sum"),
            weighted_access_count=("source_preserving_weighted_access_count", "sum"),
        ).reset_index()
        out = dist.merge(assign, on="assignment_fanout_count", how="outer")
        out["access_layer"] = layer
        rows.extend(out.to_dict("records"))
    return pd.DataFrame(rows)


def _typed_category_summary(typed: pd.DataFrame) -> pd.DataFrame:
    if typed.empty:
        return pd.DataFrame(columns=["access_control_category", "source_access_point_count", "assignment_count", "signals_with_category", "unweighted_access_count", "weighted_access_count"])
    return (
        typed.groupby("access_control_category", dropna=False)
        .agg(
            source_access_point_count=("access_point_id", "nunique"),
            assignment_count=("access_point_id", "size"),
            signals_with_category=("target_signal_id", "nunique"),
            unweighted_access_count=("unweighted_access_count", "sum"),
            weighted_access_count=("source_preserving_weighted_access_count", "sum"),
        )
        .reset_index()
    )


def _missingness(untyped: pd.DataFrame, typed: pd.DataFrame, bins: pd.DataFrame, design_untyped: pd.DataFrame, design_typed: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for layer, frame, design in [("untyped", untyped, design_untyped), ("typed_v2", typed, design_typed)]:
        assigned_bins = set(_text(frame, "target_bin_id"))
        assigned_signals = set(_text(frame, "target_signal_id"))
        bins_without_assignment = bins.loc[~_text(bins, "target_bin_id").isin(assigned_bins)].copy()
        signals_without_assignment = bins.loc[~_text(bins, "target_signal_id").isin(assigned_signals)].copy()
        rows.extend(
            [
                {
                    "access_layer": layer,
                    "missingness_reason": "target_bins_without_access_assignment",
                    "signal_count": int(_text(bins_without_assignment, "target_signal_id").nunique()),
                    "bin_count": int(len(bins_without_assignment)),
                    "note": "No access point captured for bin.",
                },
                {
                    "access_layer": layer,
                    "missingness_reason": "target_signals_without_access_assignment",
                    "signal_count": int(_text(signals_without_assignment, "target_signal_id").nunique()),
                    "bin_count": "",
                    "note": "No access point captured for signal.",
                },
            ]
        )
        if layer == "untyped" and "missing_or_uncertain_signal" in design.columns:
            rows.append({"access_layer": layer, "missingness_reason": "design_missing_or_uncertain_signal", "signal_count": int(_flag(design, "missing_or_uncertain_signal").sum()), "bin_count": "", "note": "Design diagnostic had no existing output and no route/measure-compatible untyped point evidence."})
        if layer == "typed_v2" and "likely_sparse_or_source_limited_case" in design.columns:
            rows.append({"access_layer": layer, "missingness_reason": "typed_v2_sparse_or_source_limited", "signal_count": int(_flag(design, "likely_sparse_or_source_limited_case").sum()), "bin_count": "", "note": "Plausible target but no typed v2 category evidence in design diagnostic."})
    return pd.DataFrame(rows)


def _review_queue(untyped: pd.DataFrame, typed: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([untyped, typed], ignore_index=True, sort=False)
    if combined.empty:
        return pd.DataFrame()
    summary = (
        combined.groupby(["target_signal_id", "access_layer"], dropna=False)
        .agg(
            source_access_point_count=("access_point_id", "nunique"),
            assignment_count=("access_point_id", "size"),
            max_assignment_fanout=("assignment_fanout_count", "max"),
            multi_assignment_count=("multi_assignment_flag", "sum"),
            assignment_methods=("assignment_method", _collapse),
            unweighted_access_count=("unweighted_access_count", "sum"),
            weighted_access_count=("source_preserving_weighted_access_count", "sum"),
        )
        .reset_index()
    )
    bin_status = bins.groupby("target_signal_id", dropna=False).agg(
        target_bin_count=("target_bin_id", "nunique"),
        route_measure_ready_bins=("route_measure_ready", "sum"),
        geometry_status=("assignment_geometry_status", _collapse),
    ).reset_index()
    summary = summary.merge(bin_status, on="target_signal_id", how="left")
    summary["review_priority_score"] = (
        pd.to_numeric(summary["max_assignment_fanout"], errors="coerce").fillna(0) * 10
        + pd.to_numeric(summary["multi_assignment_count"], errors="coerce").fillna(0)
        + np.where(summary["geometry_status"].astype(str).str.contains("no_catchment", na=False), 25, 0)
    )
    return summary.sort_values(["review_priority_score", "assignment_count"], ascending=[False, False]).head(20000)


def _qa(target_bins: pd.DataFrame, untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "This module writes only to expanded_universe_access_capture review folder."),
        ("no_candidates_promoted", "pass", "All assignments are review-only and not active/not policy-ready."),
        ("no_crash_records_read", "pass", "Input list excludes crash record files and guarded readers reject crash columns."),
        ("no_crash_direction_fields_read_or_used", "pass", "Guarded readers reject crash direction tokens; signal-relative scaffold labels are retained."),
        ("no_crash_assignment_or_catchments", "pass", "No crash assignment or crash catchment generation is performed."),
        ("no_rates_or_models", "pass", "Only access counts/densities per 1,000 ft are reported; no crash rates or models are computed."),
        ("typed_and_untyped_access_separate", "pass", "Untyped and typed v2 assignment details and summaries are separate."),
        ("unweighted_and_weighted_assignments_separate", "pass", "Unweighted and source-preserving weighted columns/products are both retained."),
        ("multi_context_access_assignment_allowed", "pass", "Fanout is preserved; source-preserving weight is 1 divided by assignment fanout."),
        ("deduped_signal_counts_separate_from_bin_counts", "pass", f"target_signals={target_bins['target_signal_id'].nunique()}; target_bins={len(target_bins)}."),
        ("outputs_written_only_to_review_folder", "pass", str(OUT_DIR)),
        ("represented_universe_signal_count", "pass" if target_bins["target_signal_id"].nunique() == 2739 else "review", str(target_bins["target_signal_id"].nunique())),
        ("untyped_assignment_rows_present", "pass" if len(untyped) > 0 else "review", str(len(untyped))),
        ("typed_assignment_rows_present", "pass" if len(typed) > 0 else "review", str(len(typed))),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(coverage: pd.DataFrame, fanout: pd.DataFrame, typed_categories: pd.DataFrame, missing: pd.DataFrame) -> str:
    def metric(layer: str, name: str) -> float:
        rows = coverage.loc[coverage["access_layer"].eq(layer) & coverage["metric"].eq(name), "count"]
        return float(rows.iloc[0]) if not rows.empty else 0.0

    untyped_signals = int(metric("untyped", "signals_with_any_access_assignment"))
    typed_signals = int(metric("typed_v2", "signals_with_any_access_assignment"))
    untyped_1000 = int(metric("untyped", "signals_with_0_1000ft_access_assignment"))
    typed_1000 = int(metric("typed_v2", "signals_with_0_1000ft_access_assignment"))
    untyped_unweighted = metric("untyped", "unweighted_assignment_total")
    untyped_weighted = metric("untyped", "source_preserving_weighted_assignment_total")
    typed_unweighted = metric("typed_v2", "unweighted_assignment_total")
    typed_weighted = metric("typed_v2", "source_preserving_weighted_assignment_total")
    untyped_fanout = int(metric("untyped", "signals_with_fanout_multi_assignment"))
    typed_fanout = int(metric("typed_v2", "signals_with_fanout_multi_assignment"))
    category_lines = "\n".join(
        f"- {row.access_control_category}: {int(row.signals_with_category)} signals, {int(row.assignment_count)} assignments"
        for row in typed_categories.itertuples(index=False)
    )
    missing_lines = "\n".join(
        f"- {row.access_layer} / {row.missingness_reason}: {row.signal_count} signals"
        for row in missing.itertuples(index=False)
    )
    return f"""# Expanded Universe Access Capture Findings

**Bounded question:** review-only access capture for the 2,739-signal expanded represented universe, preserving separate untyped and typed v2 layers and both unweighted and source-preserving weighted counts.

## Direct Answers

1. Untyped access assignment reached **{untyped_signals:,} signals**.
2. Typed v2 access assignment reached **{typed_signals:,} signals**.
3. Untyped access in the 0-1,000 ft window reached **{untyped_1000:,} signals**.
4. Typed v2 access in the 0-1,000 ft window reached **{typed_1000:,} signals**.
5. Untyped fanout/multi-assignment occurs on **{untyped_fanout:,} signals**.
6. Typed v2 fanout/multi-assignment occurs on **{typed_fanout:,} signals**.
7. High-level unweighted vs weighted totals: untyped **{untyped_unweighted:,.2f} unweighted** vs **{untyped_weighted:,.2f} weighted**; typed v2 **{typed_unweighted:,.2f} unweighted** vs **{typed_weighted:,.2f} weighted**.
8. Typed category coverage:
{category_lines if category_lines else "- No typed category assignments captured."}
9. Missing or geometry-dependent cases:
{missing_lines if missing_lines else "- No missingness rows produced."}
10. Next access pass: build review-only candidate access catchments for expanded candidate bins, then compare the four preserved products before choosing any primary access metric.

## Guardrails

This capture does not modify active outputs, promote candidates, read crash records, use crash direction fields, assign crashes, create crash catchments, calculate rates, or run models.
"""


def _manifest(started: str, inputs: dict[str, pd.DataFrame], outputs: list[str]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.expanded_universe_access_capture",
        "bounded_question": "review-only expanded-universe access capture with separate untyped/typed and unweighted/weighted products",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
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
    access_v1, access_v2 = _prepare_access_sources(inputs)
    target_bins = _build_access_target_bins(inputs)
    untyped = _capture_untyped(inputs, target_bins, access_v1)
    typed = _capture_typed(inputs, target_bins, access_v2)
    untyped_summary = _summary(untyped, target_bins, layer="untyped")
    typed_summary = _summary(typed, target_bins, layer="typed_v2")
    coverage = _coverage(untyped, typed, target_bins, inputs["design_untyped"], inputs["design_typed"])
    fanout = _fanout_summary(untyped, typed)
    typed_categories = _typed_category_summary(typed)
    missingness = _missingness(untyped, typed, target_bins, inputs["design_untyped"], inputs["design_typed"])
    review_queue = _review_queue(untyped, typed, target_bins)
    qa = _qa(target_bins, untyped, typed)
    findings = _findings(coverage, fanout, typed_categories, missingness)

    outputs = {
        "access_target_bins.csv": target_bins,
        "untyped_access_assignment_detail.csv": untyped,
        "untyped_access_signal_window_summary.csv": untyped_summary,
        "typed_v2_access_assignment_detail.csv": typed,
        "typed_v2_access_signal_window_summary.csv": typed_summary,
        "access_product_coverage_summary.csv": coverage,
        "access_assignment_fanout_summary.csv": fanout,
        "typed_v2_access_category_summary.csv": typed_categories,
        "access_missingness_summary.csv": missingness,
        "access_ranked_review_queue.csv": review_queue,
        "expanded_universe_access_capture_qa.csv": qa,
    }
    for name, frame in outputs.items():
        _write_csv(frame, OUT_DIR / name)
    _write_text(findings, OUT_DIR / "expanded_universe_access_capture_findings.md")
    output_names = list(outputs) + ["expanded_universe_access_capture_findings.md", "expanded_universe_access_capture_manifest.json", "run_progress_log.txt"]
    _write_json(_manifest(started, inputs, output_names), OUT_DIR / "expanded_universe_access_capture_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
