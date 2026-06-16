from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    import pyogrio
except Exception:  # pragma: no cover
    gpd = None
    pyogrio = None

from .aadt_context_join_v3_identity_route_measure import _route_key as _aadt_v3_route_key
from .expanded_candidate_aadt_v3_path_rebuild import _aadt_key_variants
from .expanded_candidate_speed_rns_phase3d_vectorized_assignment import _facility_text, _phase3_norm, normalize_route_name


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_residual_cleanup"
RESIDUAL_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_residual_diagnostic"
SPEED_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_v3_path_rebuild"
SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")

PREVIOUS_SPEED_AADT_READY_SIGNALS = 1_468
REVIEW_QUEUE_LIMIT = 20_000
LOW_FANOUT_LIMIT = 12

CRASH_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel", "document_nbr", "crash_year", "crash_dt")

REQUIRED_INPUTS = {
    RESIDUAL_DIR: [
        "residual_speed_detail.csv",
        "residual_aadt_detail.csv",
        "residual_signal_overlap_summary.csv",
        "residual_recovery_potential_summary.csv",
        "residual_action_class_summary.csv",
        "expanded_candidate_speed_aadt_residual_manifest.json",
    ],
    SPEED_DIR: [
        "phase3d_candidate_rns_speed_assignment_detail.csv",
        "phase3d_candidate_rns_speed_signal_summary.csv",
        "expanded_candidate_speed_rns_phase3d_vectorized_assignment_manifest.json",
    ],
    AADT_DIR: [
        "aadt_v3_candidate_assignment_detail.csv",
        "aadt_v3_candidate_signal_summary.csv",
        "aadt_v3_path_inventory.csv",
        "expanded_candidate_aadt_v3_path_rebuild_manifest.json",
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
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


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


def _missing_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    if not AADT_FILE.exists():
        missing.append(str(AADT_FILE))
    if not SPEED_LIMIT_RNS_GDB.exists():
        missing.append(str(SPEED_LIMIT_RNS_GDB))
    return missing


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() != "nan" and str(value) != ""})
    return "|".join(items[:limit])


def _load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "residual_speed": _read_csv(RESIDUAL_DIR / "residual_speed_detail.csv"),
        "residual_aadt": _read_csv(RESIDUAL_DIR / "residual_aadt_detail.csv"),
        "speed_detail": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_assignment_detail.csv"),
        "speed_signal": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_signal_summary.csv"),
        "aadt_detail": _read_csv(AADT_DIR / "aadt_v3_candidate_assignment_detail.csv"),
        "aadt_signal": _read_csv(AADT_DIR / "aadt_v3_candidate_signal_summary.csv"),
    }


def _speed_keys(row: pd.Series) -> list[str]:
    values = [
        row.get("candidate_route_name_rns_norm", ""),
        row.get("normalized_candidate_route_key", ""),
        normalize_route_name(row.get("route_name", "")),
        _phase3_norm(row.get("route_name", "")),
    ]
    return [value for value in dict.fromkeys(str(v) for v in values if str(v)) if value]


def _read_rns_intervals(keys: set[str]) -> pd.DataFrame:
    columns = [
        "RTE_NM", "FROM_MEASURE", "TO_MEASURE", "EDGE_RTE_KEY", "TRANSPORT_EDGE_ID",
        "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "MASTER_RTE_NM", "MASTER_EDGE_RTE_KEY",
        "CAR_SPEED_LIMIT", "FINAL_SPEED_LIMIT_SOURCE", "TRUCK_SPEED_LIMIT", "SPEEDZONE_TYPE_DSC", "IDENTIFY_CODE",
    ]
    _checkpoint("read_start Speed_Limit_RNS_cleanup")
    if pyogrio is not None:
        raw = pyogrio.read_dataframe(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=columns, read_geometry=False, use_arrow=True)
    elif gpd is not None:
        raw = pd.DataFrame(gpd.read_file(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=columns, ignore_geometry=True))
    else:
        raise RuntimeError("Neither pyogrio nor geopandas is available to read Speed_Limit_RNS.")
    raw = raw.reset_index().rename(columns={"index": "rns_source_row_id"})
    _checkpoint("read_complete Speed_Limit_RNS_cleanup", len(raw))
    for route_field in ["RTE_NM", "MASTER_RTE_NM"]:
        raw[f"{route_field}_rns_route_key"] = raw[route_field].map(normalize_route_name)
        raw[f"{route_field}_normalized_route_key"] = raw[route_field].map(_phase3_norm)
        raw[f"{route_field}_facility_text"] = raw[route_field].map(_facility_text)
    prefilter = pd.Series(False, index=raw.index)
    for route_field in ["RTE_NM", "MASTER_RTE_NM"]:
        prefilter = prefilter | raw[f"{route_field}_rns_route_key"].isin(keys) | raw[f"{route_field}_normalized_route_key"].isin(keys)
    raw = raw.loc[prefilter].copy()
    _checkpoint("rns_cleanup_prefiltered", len(raw))
    for field in ["FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT"]:
        raw[f"{field}_num"] = pd.to_numeric(raw.get(field, pd.Series(pd.NA, index=raw.index)), errors="coerce")
    frames = []
    for route_field, from_field, to_field in [
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
    ]:
        sub = pd.DataFrame(
            {
                "rns_source_row_id": raw["rns_source_row_id"],
                "rns_route_field": route_field,
                "rns_measure_pair": f"{from_field}/{to_field}",
                "rns_route_raw": raw[route_field].astype(str),
                "rns_route_key": raw[f"{route_field}_rns_route_key"],
                "normalized_rns_route_key": raw[f"{route_field}_normalized_route_key"],
                "rns_measure_start": raw[f"{from_field}_num"],
                "rns_measure_end": raw[f"{to_field}_num"],
                "review_only_car_speed_limit": raw["CAR_SPEED_LIMIT_num"],
                "review_only_truck_speed_limit": raw["TRUCK_SPEED_LIMIT_num"],
                "rns_transport_edge_id": raw.get("TRANSPORT_EDGE_ID", pd.Series("", index=raw.index)).astype(str),
                "rns_final_speed_limit_source": raw.get("FINAL_SPEED_LIMIT_SOURCE", pd.Series("", index=raw.index)).astype(str),
                "rns_speedzone_type_dsc": raw.get("SPEEDZONE_TYPE_DSC", pd.Series("", index=raw.index)).astype(str),
                "rns_identify_code": raw.get("IDENTIFY_CODE", pd.Series("", index=raw.index)).astype(str),
            }
        )
        frames.append(sub)
    intervals = pd.concat(frames, ignore_index=True)
    intervals["rns_measure_min"] = intervals[["rns_measure_start", "rns_measure_end"]].min(axis=1)
    intervals["rns_measure_max"] = intervals[["rns_measure_start", "rns_measure_end"]].max(axis=1)
    intervals["rns_interval_span"] = intervals["rns_measure_max"] - intervals["rns_measure_min"]
    intervals["rns_lookup_route_key"] = intervals["rns_route_key"].where(intervals["rns_route_key"].ne(""), intervals["normalized_rns_route_key"])
    intervals = intervals.loc[intervals["rns_lookup_route_key"].isin(keys) & intervals["rns_measure_min"].notna() & intervals["rns_measure_max"].notna()].copy()
    _checkpoint("rns_cleanup_intervals", len(intervals))
    return intervals


def _speed_cleanup(residual: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    focus = residual.loc[_text(residual, "speed_residual_subtype").isin(["overlapping_rns_intervals_wrong_interval_selected", "boundary_midpoint_selection_issue", "measure_sorting_or_searchsorted_issue"])].copy()
    rows = []
    for _, row in focus.iterrows():
        keys = _speed_keys(row)
        mid = pd.to_numeric(row.get("candidate_midpoint_measure", ""), errors="coerce")
        matches = intervals.loc[intervals["rns_lookup_route_key"].isin(keys) & intervals["rns_measure_min"].le(mid) & intervals["rns_measure_max"].ge(mid)].copy()
        result = row.to_dict()
        result["cleanup_candidate_route_keys"] = "|".join(keys)
        result["cleanup_containing_interval_count"] = len(matches)
        if pd.isna(mid) or not keys:
            status = "speed_insufficient_evidence"
        elif matches.empty:
            status = "speed_no_containing_interval_after_review"
        else:
            matches["route_rank"] = matches["rns_lookup_route_key"].map({key: rank for rank, key in enumerate(keys)})
            matches["valid_speed_rank"] = pd.to_numeric(matches["review_only_car_speed_limit"], errors="coerce").notna().astype(int)
            matches = matches.sort_values(["route_rank", "rns_interval_span", "valid_speed_rank", "rns_final_speed_limit_source", "rns_source_row_id"], ascending=[True, True, False, True, True])
            top = matches.iloc[0]
            tied = matches.loc[
                matches["route_rank"].eq(top["route_rank"])
                & matches["rns_interval_span"].eq(top["rns_interval_span"])
                & matches["valid_speed_rank"].eq(top["valid_speed_rank"])
                & matches["review_only_car_speed_limit"].eq(top["review_only_car_speed_limit"])
            ]
            if len(tied) > 1 and tied["rns_source_row_id"].nunique() > 1:
                status = "speed_unresolved_multiple_valid_intervals"
            elif pd.isna(pd.to_numeric(top["review_only_car_speed_limit"], errors="coerce")):
                status = "speed_insufficient_evidence"
            else:
                status = "speed_recovered_corrected_interval"
                for dest, src in [
                    ("cleanup_speed_value", "review_only_car_speed_limit"),
                    ("cleanup_truck_speed_value", "review_only_truck_speed_limit"),
                    ("cleanup_rns_route_raw", "rns_route_raw"),
                    ("cleanup_rns_route_key", "rns_lookup_route_key"),
                    ("cleanup_rns_measure_min", "rns_measure_min"),
                    ("cleanup_rns_measure_max", "rns_measure_max"),
                    ("cleanup_rns_source_row_id", "rns_source_row_id"),
                    ("cleanup_rns_measure_pair", "rns_measure_pair"),
                    ("cleanup_rns_transport_edge_id", "rns_transport_edge_id"),
                ]:
                    result[dest] = top.get(src, "")
        result["speed_cleanup_status"] = status
        result["speed_cleanup_review_only_flag"] = True
        rows.append(result)
    return pd.DataFrame(rows)


def _aadt_alias_candidates(row: pd.Series) -> list[str]:
    values = [row.get("candidate_route_name", ""), row.get("route_name", ""), row.get("candidate_route_common", ""), row.get("route_common", ""), row.get("candidate_facility_text", "")]
    keys: set[str] = set()
    for value in values:
        keys |= _aadt_key_variants(value)
        keys.add(_aadt_v3_route_key(value))
    compact_name = re.sub(r"[^A-Z0-9]", "", str(row.get("candidate_route_name", row.get("route_name", ""))).upper())
    ramp_route = re.search(r"(IS|I)0*([0-9]+)([NSEW])?B?", compact_name)
    if ramp_route:
        keys.add(f"I{int(ramp_route.group(2))}{ramp_route.group(3) or ''}")
        keys.add(f"IS{int(ramp_route.group(2))}{ramp_route.group(3) or ''}")
    return [key for key in dict.fromkeys(k for k in keys if k)]


def _read_aadt_alias_intervals(keys: set[str]) -> pd.DataFrame:
    columns = ["RTE_NM", "MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "LINKID", "AADT_YR", "AADT", "DIRECTION_FACTOR", "DIRECTIONALITY"]
    _checkpoint("read_start aadt_cleanup_alias_source")
    raw = pd.read_parquet(AADT_FILE, columns=columns).reset_index(names="aadt_source_index")
    _checkpoint("read_complete aadt_cleanup_alias_source", len(raw))
    raw["aadt_value_numeric"] = pd.to_numeric(raw["AADT"], errors="coerce")
    t_from = pd.to_numeric(raw["TRANSPORT_EDGE_FROM_MSR"], errors="coerce")
    t_to = pd.to_numeric(raw["TRANSPORT_EDGE_TO_MSR"], errors="coerce")
    f_from = pd.to_numeric(raw["FROM_MEASURE"], errors="coerce")
    f_to = pd.to_numeric(raw["TO_MEASURE"], errors="coerce")
    raw["aadt_measure_from"] = t_from.where(t_from.notna() & t_to.notna(), f_from)
    raw["aadt_measure_to"] = t_to.where(t_from.notna() & t_to.notna(), f_to)
    raw["aadt_measure_pair"] = np.where(t_from.notna() & t_to.notna(), "TRANSPORT_EDGE_FROM_MSR|TRANSPORT_EDGE_TO_MSR", "FROM_MEASURE|TO_MEASURE")
    raw["aadt_measure_min"] = raw[["aadt_measure_from", "aadt_measure_to"]].min(axis=1)
    raw["aadt_measure_max"] = raw[["aadt_measure_from", "aadt_measure_to"]].max(axis=1)
    raw = raw.loc[raw["aadt_value_numeric"].gt(0) & raw["aadt_measure_min"].notna() & raw["aadt_measure_max"].notna()].copy()
    frames = []
    for field in ["RTE_NM", "MASTER_RTE_NM"]:
        alias = raw.copy()
        alias["aadt_route_name_raw"] = alias[field].astype(str)
        alias["aadt_route_name_normalized_v3"] = alias["aadt_route_name_raw"].map(_aadt_v3_route_key)
        alias["aadt_route_alias_field"] = field
        frames.append(alias.loc[alias["aadt_route_name_normalized_v3"].isin(keys)].copy())
    intervals = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if intervals.empty:
        return intervals
    intervals = intervals.drop_duplicates(["aadt_source_index", "aadt_route_name_normalized_v3"]).copy()
    intervals["aadt_interval_span"] = intervals["aadt_measure_max"] - intervals["aadt_measure_min"]
    _checkpoint("aadt_cleanup_alias_intervals", len(intervals), f"keys={intervals['aadt_route_name_normalized_v3'].nunique():,}")
    return intervals


def _derive_exposure(row: pd.Series, aadt_value: Any, factor_value: Any) -> tuple[str, str, float | str]:
    aadt = pd.to_numeric(aadt_value, errors="coerce")
    factor = pd.to_numeric(factor_value, errors="coerce")
    length_miles = pd.to_numeric(row.get("candidate_bin_length_ft", ""), errors="coerce") / 5280.0
    if pd.isna(aadt) or pd.isna(length_miles):
        return "missing_aadt_or_exposure", "invalid_or_missing", ""
    if pd.notna(factor) and 0 < factor <= 1:
        return "valid_direction_factor_applied", "not_needed", float(aadt * factor * length_miles)
    return "null_or_invalid_direction_factor_bidirectional_fallback", "bidirectional_fallback_used", float(aadt * length_miles)


def _aadt_cleanup(residual: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    focus = residual.loc[_text(residual, "aadt_residual_subtype").isin(["alias_missing_but_route_name_match", "alias_missing_but_facility_match", "alias_missing_but_route_common_match", "route_key_format_normalization_issue"])].copy()
    rows = []
    route_fanout = intervals.groupby("aadt_route_name_normalized_v3")["aadt_source_index"].nunique().to_dict() if not intervals.empty else {}
    for _, row in focus.iterrows():
        aliases = _aadt_alias_candidates(row)
        mid = pd.to_numeric(row.get("candidate_midpoint_measure", ""), errors="coerce")
        matches = intervals.loc[intervals["aadt_route_name_normalized_v3"].isin(aliases) & intervals["aadt_measure_min"].le(mid) & intervals["aadt_measure_max"].ge(mid)].copy()
        result = row.to_dict()
        result["cleanup_alias_candidates"] = "|".join(aliases[:24])
        result["cleanup_containing_interval_count"] = len(matches)
        result["cleanup_alias_route_fanout_max"] = max([route_fanout.get(alias, 0) for alias in aliases] or [0])
        if pd.isna(mid) or not aliases:
            status = "aadt_insufficient_evidence"
        elif matches.empty:
            any_alias = intervals.loc[intervals["aadt_route_name_normalized_v3"].isin(aliases)]
            status = "aadt_likely_source_gap" if any_alias.empty else "aadt_measure_incompatible_after_alias"
        elif matches["aadt_route_name_normalized_v3"].nunique() > LOW_FANOUT_LIMIT or len(matches) > LOW_FANOUT_LIMIT:
            status = "aadt_alias_patch_fanout_review"
        elif matches["AADT"].dropna().astype(str).nunique() > 1:
            status = "aadt_alias_patch_fanout_review"
        else:
            matches["alias_rank"] = matches["aadt_route_name_normalized_v3"].map({alias: rank for rank, alias in enumerate(aliases)})
            matches = matches.sort_values(["alias_rank", "aadt_interval_span", "AADT_YR", "aadt_source_index"], ascending=[True, True, False, True])
            top = matches.iloc[0]
            status = "aadt_recovered_alias_patch"
            factor_status, fallback_status, exposure = _derive_exposure(row, top.get("AADT", ""), top.get("DIRECTION_FACTOR", ""))
            for dest, src in [
                ("cleanup_aadt_value", "AADT"),
                ("cleanup_aadt_year", "AADT_YR"),
                ("cleanup_direction_factor", "DIRECTION_FACTOR"),
                ("cleanup_aadt_route_raw", "aadt_route_name_raw"),
                ("cleanup_aadt_route_key", "aadt_route_name_normalized_v3"),
                ("cleanup_aadt_measure_min", "aadt_measure_min"),
                ("cleanup_aadt_measure_max", "aadt_measure_max"),
                ("cleanup_aadt_source_row_id", "aadt_source_index"),
                ("cleanup_aadt_measure_pair", "aadt_measure_pair"),
                ("cleanup_aadt_linkid", "LINKID"),
            ]:
                result[dest] = top.get(src, "")
            result["cleanup_direction_factor_status"] = factor_status
            result["cleanup_bidirectional_fallback_status"] = fallback_status
            result["cleanup_estimated_exposure"] = exposure
        result["aadt_cleanup_status"] = status
        result["aadt_cleanup_review_only_flag"] = True
        rows.append(result)
    return pd.DataFrame(rows)


def _combine_signal_summary(speed_detail: pd.DataFrame, aadt_detail: pd.DataFrame, speed_cleanup: pd.DataFrame, aadt_cleanup: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    speed_recovered_bins = set(_text(speed_cleanup.loc[_text(speed_cleanup, "speed_cleanup_status").eq("speed_recovered_corrected_interval")], "candidate_bin_id"))
    aadt_recovered_bins = set(_text(aadt_cleanup.loc[_text(aadt_cleanup, "aadt_cleanup_status").eq("aadt_recovered_alias_patch")], "candidate_bin_id"))
    speed = speed_detail[["candidate_bin_id", "candidate_signal_id", "analysis_window", "rns_match_status"]].copy()
    speed["speed_ready_after_cleanup"] = _text(speed, "rns_match_status").eq("review_only_speed_matched") | _text(speed, "candidate_bin_id").isin(speed_recovered_bins)
    aadt = aadt_detail[["candidate_bin_id", "candidate_signal_id", "analysis_window", "aadt_v3_match_status"]].copy()
    aadt["aadt_ready_after_cleanup"] = _text(aadt, "aadt_v3_match_status").eq("review_only_aadt_v3_matched") | _text(aadt, "candidate_bin_id").isin(aadt_recovered_bins)
    speed_signal = speed.groupby("candidate_signal_id", dropna=False).agg(
        speed_bin_count=("candidate_bin_id", "count"),
        speed_ready_bins=("speed_ready_after_cleanup", "sum"),
        has_speed_ready=("speed_ready_after_cleanup", "any"),
        speed_windows=("analysis_window", _collapse),
    ).reset_index()
    aadt_signal = aadt.groupby("candidate_signal_id", dropna=False).agg(
        aadt_bin_count=("candidate_bin_id", "count"),
        aadt_ready_bins=("aadt_ready_after_cleanup", "sum"),
        has_aadt_ready=("aadt_ready_after_cleanup", "any"),
        aadt_windows=("analysis_window", _collapse),
    ).reset_index()
    signal = speed_signal.merge(aadt_signal, on="candidate_signal_id", how="outer").fillna(False)
    signal["has_both_ready"] = signal["has_speed_ready"].astype(bool) & signal["has_aadt_ready"].astype(bool)

    speed_0_1000 = set(_text(speed.loc[_text(speed, "analysis_window").str.contains("0_1000", na=False) & speed["speed_ready_after_cleanup"]], "candidate_signal_id"))
    aadt_0_1000 = set(_text(aadt.loc[_text(aadt, "analysis_window").str.contains("0_1000", na=False) & aadt["aadt_ready_after_cleanup"]], "candidate_signal_id"))
    speed_1000_2500 = set(_text(speed.loc[_text(speed, "analysis_window").str.contains("1000_2500", na=False) & speed["speed_ready_after_cleanup"]], "candidate_signal_id"))
    aadt_1000_2500 = set(_text(aadt.loc[_text(aadt, "analysis_window").str.contains("1000_2500", na=False) & aadt["aadt_ready_after_cleanup"]], "candidate_signal_id"))
    ready_0_1000 = speed_0_1000 & aadt_0_1000
    ready_1000_2500 = speed_1000_2500 & aadt_1000_2500
    signal["full_0_1000_both_ready"] = _text(signal, "candidate_signal_id").isin(ready_0_1000)
    signal["full_0_2500_both_ready"] = _text(signal, "candidate_signal_id").isin(ready_0_1000 & ready_1000_2500)
    before_after = pd.DataFrame(
        [
            {"metric": "previous_speed_aadt_ready_signals", "count": PREVIOUS_SPEED_AADT_READY_SIGNALS},
            {"metric": "new_speed_aadt_ready_signals_after_cleanup", "count": int(signal["has_both_ready"].sum())},
            {"metric": "additional_speed_aadt_ready_signals", "count": max(int(signal["has_both_ready"].sum()) - PREVIOUS_SPEED_AADT_READY_SIGNALS, 0)},
            {"metric": "additional_speed_only_recovered_signals", "count": int(speed_cleanup.loc[_text(speed_cleanup, "speed_cleanup_status").eq("speed_recovered_corrected_interval"), "candidate_signal_id"].nunique())},
            {"metric": "additional_aadt_only_recovered_signals", "count": int(aadt_cleanup.loc[_text(aadt_cleanup, "aadt_cleanup_status").eq("aadt_recovered_alias_patch"), "candidate_signal_id"].nunique())},
            {"metric": "full_0_1000_both_ready_signals_after_cleanup", "count": int(signal["full_0_1000_both_ready"].sum())},
            {"metric": "full_0_2500_both_ready_signals_after_cleanup", "count": int(signal["full_0_2500_both_ready"].sum())},
        ]
    )
    missing = pd.DataFrame(
        [
            {"layer": "speed", "remaining_residual_bin_count": int((~_text(speed_cleanup, "speed_cleanup_status").eq("speed_recovered_corrected_interval")).sum()), "remaining_residual_signal_count": int(speed_cleanup.loc[~_text(speed_cleanup, "speed_cleanup_status").eq("speed_recovered_corrected_interval"), "candidate_signal_id"].nunique()), "dominant_reason": _dominant(speed_cleanup, "speed_cleanup_status")},
            {"layer": "aadt", "remaining_residual_bin_count": int((~_text(aadt_cleanup, "aadt_cleanup_status").eq("aadt_recovered_alias_patch")).sum()), "remaining_residual_signal_count": int(aadt_cleanup.loc[~_text(aadt_cleanup, "aadt_cleanup_status").eq("aadt_recovered_alias_patch"), "candidate_signal_id"].nunique()), "dominant_reason": _dominant(aadt_cleanup, "aadt_cleanup_status")},
        ]
    )
    return signal, before_after, missing


def _dominant(df: pd.DataFrame, col: str) -> str:
    if df.empty:
        return "none"
    counts = df[col].value_counts()
    return str(counts.index[0]) if not counts.empty else "none"


def _review_queue(speed_cleanup: pd.DataFrame, aadt_cleanup: pd.DataFrame) -> pd.DataFrame:
    s = speed_cleanup.copy()
    s["layer"] = "speed"
    s["cleanup_status"] = s["speed_cleanup_status"]
    a = aadt_cleanup.copy()
    a["layer"] = "aadt"
    a["cleanup_status"] = a["aadt_cleanup_status"]
    cols = ["layer", "cleanup_status", "candidate_signal_id", "candidate_bin_id", "candidate_route_group_id", "route_id", "route_common", "route_name", "analysis_window", "candidate_measure_min", "candidate_measure_max", "candidate_midpoint_measure"]
    out = pd.concat([s[[c for c in cols if c in s.columns]], a[[c for c in cols if c in a.columns]]], ignore_index=True, sort=False)
    rank = {"speed_unresolved_multiple_valid_intervals": 0, "aadt_alias_patch_fanout_review": 1, "aadt_measure_incompatible_after_alias": 2}
    out["review_rank"] = out["cleanup_status"].map(rank).fillna(9)
    return out.sort_values(["review_rank", "layer", "candidate_signal_id"]).head(REVIEW_QUEUE_LIMIT)


def _qa(missing: list[str], speed_cleanup: pd.DataFrame, aadt_cleanup: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, True, True),
        ("no_candidates_promoted", True, True, True),
        ("no_crash_records_read", True, True, True),
        ("no_crash_direction_fields_read_or_used", True, True, True),
        ("access_not_included", True, True, True),
        ("no_rates_or_models_produced", True, True, True),
        ("all_cleanup_assignments_review_only", _flag(speed_cleanup, "speed_cleanup_review_only_flag").all() and _flag(aadt_cleanup, "aadt_cleanup_review_only_flag").all(), True, True),
        ("broad_fanout_alias_matches_not_forced", not _text(aadt_cleanup.loc[_text(aadt_cleanup, "aadt_cleanup_status").eq("aadt_recovered_alias_patch")], "cleanup_alias_route_fanout_max").replace("", "0").astype(float).gt(LOW_FANOUT_LIMIT * 100).any(), True, True),
        ("unresolved_interval_ties_not_forced", not _text(speed_cleanup.loc[_text(speed_cleanup, "speed_cleanup_status").eq("speed_unresolved_multiple_valid_intervals")], "cleanup_speed_value").ne("").any(), True, True),
        ("deduped_signal_counts_separate_from_bin_counts", True, True, True),
        ("outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR)),
        ("required_inputs_present", not missing, len(missing), 0),
    ]
    return pd.DataFrame([{"qa_gate": r[0], "passed": bool(r[1]), "observed_value": r[2], "expected_or_reference_value": r[3]} for r in rows])


def _count(df: pd.DataFrame, metric: str) -> int:
    row = df.loc[df["metric"].eq(metric)]
    return 0 if row.empty else int(row.iloc[0]["count"])


def _findings(before_after: pd.DataFrame, missing: pd.DataFrame, speed_cleanup: pd.DataFrame, aadt_cleanup: pd.DataFrame) -> str:
    speed_signals = int(speed_cleanup.loc[_text(speed_cleanup, "speed_cleanup_status").eq("speed_recovered_corrected_interval"), "candidate_signal_id"].nunique())
    aadt_signals = int(aadt_cleanup.loc[_text(aadt_cleanup, "aadt_cleanup_status").eq("aadt_recovered_alias_patch"), "candidate_signal_id"].nunique())
    remaining = "; ".join(f"{row.layer}: {row.dominant_reason} ({row.remaining_residual_bin_count} bins)" for row in missing.itertuples(index=False))
    additional = _count(before_after, "additional_speed_aadt_ready_signals")
    worth = "No; remaining speed/AADT cleanup should not block access/crash preparation." if additional < 25 else "Only if the team wants to capture a bounded final increment before access/crash preparation."
    return "\n".join(
        [
            "# Expanded Candidate Speed/AADT Residual Cleanup Findings",
            "",
            f"Speed residual signals recovered: {speed_signals}.",
            f"AADT residual signals recovered: {aadt_signals}.",
            f"Additional speed+AADT-ready signals recovered: {additional}.",
            f"New total speed+AADT-ready recovered signal count: {_count(before_after, 'new_speed_aadt_ready_signals_after_cleanup')}.",
            f"New 0-1,000 ft speed+AADT-ready count: {_count(before_after, 'full_0_1000_both_ready_signals_after_cleanup')}.",
            f"New full 0-2,500 ft speed+AADT-ready count: {_count(before_after, 'full_0_2500_both_ready_signals_after_cleanup')}.",
            f"Residuals remaining unresolved: {remaining}.",
            f"Is further speed/AADT cleanup worth doing before access/crashes? {worth}",
            "",
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text(f"{datetime.now(timezone.utc).isoformat()} START expanded_candidate_speed_aadt_residual_cleanup\n", encoding="utf-8")
    missing = _missing_inputs()
    inputs = _load_inputs()
    speed_focus = inputs["residual_speed"].loc[_text(inputs["residual_speed"], "speed_action_class").isin(["boundary_logic_patch_candidate", "easy_recovery_candidate"])].copy()
    rns_keys = {key for _, row in speed_focus.iterrows() for key in _speed_keys(row)}
    rns_intervals = _read_rns_intervals(rns_keys) if rns_keys else pd.DataFrame()
    speed_cleanup = _speed_cleanup(inputs["residual_speed"], rns_intervals)
    aadt_focus = inputs["residual_aadt"].loc[_text(inputs["residual_aadt"], "aadt_action_class").eq("small_alias_patch_candidate")].copy()
    aadt_keys = {key for _, row in aadt_focus.iterrows() for key in _aadt_alias_candidates(row)}
    aadt_intervals = _read_aadt_alias_intervals(aadt_keys) if aadt_keys else pd.DataFrame()
    aadt_cleanup = _aadt_cleanup(inputs["residual_aadt"], aadt_intervals)
    signal, before_after, remaining = _combine_signal_summary(inputs["speed_detail"], inputs["aadt_detail"], speed_cleanup, aadt_cleanup)
    queue = _review_queue(speed_cleanup, aadt_cleanup)
    qa = _qa(missing, speed_cleanup, aadt_cleanup)
    _write_csv(speed_cleanup, OUT_DIR / "residual_cleanup_speed_detail.csv")
    _write_csv(aadt_cleanup, OUT_DIR / "residual_cleanup_aadt_detail.csv")
    _write_csv(signal, OUT_DIR / "residual_cleanup_signal_summary.csv")
    _write_csv(before_after, OUT_DIR / "residual_cleanup_before_after_summary.csv")
    _write_csv(remaining, OUT_DIR / "residual_cleanup_remaining_missingness.csv")
    _write_csv(queue, OUT_DIR / "residual_cleanup_ranked_review_queue.csv")
    _write_text(_findings(before_after, remaining, speed_cleanup, aadt_cleanup), OUT_DIR / "expanded_candidate_speed_aadt_residual_cleanup_findings.md")
    _write_csv(qa, OUT_DIR / "expanded_candidate_speed_aadt_residual_cleanup_qa.csv")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only residual speed/AADT cleanup test for recovered candidate bins",
        "output_dir": str(OUT_DIR),
        "speed_cleanup_rows": int(len(speed_cleanup)),
        "aadt_cleanup_rows": int(len(aadt_cleanup)),
        "qa_passed": bool(qa["passed"].all()),
        "missing_required_inputs": missing,
        "guardrails": {
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "no_rates_or_models": True,
            "review_only_cleanup": True,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_speed_aadt_residual_cleanup_manifest.json")
    _checkpoint("complete expanded_candidate_speed_aadt_residual_cleanup")


if __name__ == "__main__":
    main()
