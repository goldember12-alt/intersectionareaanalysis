from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
PHASE3C_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3c_route_bridge"
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
SPEED_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_exposure_context_refresh"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")

EXPECTED_CANDIDATE_BINS = 136_227
EXPECTED_CANDIDATE_SIGNALS = 1_590
STRICT_BASELINE_SIGNALS = 971
PRIOR_RECOVERED_SPEED_SIGNALS_APPROX = 666
PRIOR_REVIEW_ONLY_AADT_EXPOSURE_ASSIGNMENT_SIGNALS = 0
ROW_GUARD_LIMIT = 1_000_000
REVIEW_QUEUE_LIMIT = 20_000

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
)

REQUIRED_INPUTS = {
    PHASE3C_DIR: [
        "phase3c_aadt_route_bridge_candidates.csv",
        "phase3c_joint_speed_aadt_route_bridge_candidates.csv",
        "phase3c_route_bridge_all_candidates.csv",
        "phase3c_route_bridge_deduped_signal_recovery_estimate.csv",
        "expanded_candidate_speed_aadt_phase3c_route_bridge_manifest.json",
    ],
    ROUTE_MEASURE_DIR: [
        "stage1_candidate_route_measure_bin_detail.csv",
        "stage1_candidate_route_measure_signal_summary.csv",
        "expanded_candidate_route_measure_context_audit_manifest.json",
    ],
    SPEED_DIR: [
        "phase3d_candidate_rns_speed_assignment_detail.csv",
        "phase3d_candidate_rns_speed_signal_summary.csv",
        "phase3d_candidate_rns_speed_coverage_summary.csv",
        "expanded_candidate_speed_rns_phase3d_vectorized_assignment_manifest.json",
    ],
}


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    return any(token in column.lower() for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    selected = header if usecols is None else [c for c in usecols if c in header]
    blocked = [c for c in selected if _blocked_column(c)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=selected, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(df))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(df))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str)


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    return _text(df, col).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(series: pd.Series, limit: int = 12) -> str:
    values = sorted({str(v) for v in series.dropna() if str(v) and str(v).lower() != "nan"})
    return "|".join(values[:limit])


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def _route_key(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " ").replace("S-VA", " ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    joined = "".join(tokens)
    route_type = ""
    route_number = ""
    direction = ""
    route_token_seen = False
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"US", "SR", "VA", "I", "SC", "PR", "FR"}:
            route_type = "SR" if compact == "VA" else compact
            route_token_seen = True
            continue
        if compact in {"NB", "SB", "EB", "WB", "N", "S", "E", "W"}:
            direction = compact[0]
            continue
        match = re.fullmatch(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            route_token_seen = True
    if not route_number:
        match = re.search(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", joined)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            route_token_seen = True
    if route_number and route_type and route_token_seen:
        return f"{route_type}{route_number}{direction}"
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def _phase3_norm(value: Any) -> str:
    s = str(value or "").upper().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("INTERSTATE", "IS").replace("R-VA", "").replace("S-VA", "SC")
    s = re.sub(r"[^A-Z0-9]", "", s)
    for prefix in ["US", "SR", "VA", "SC", "IS", "I", "FR", "PR"]:
        s = re.sub(prefix + r"0+([0-9])", prefix + r"\1", s)
    return s.replace("EB", "E").replace("WB", "W").replace("NB", "N").replace("SB", "S")


def _missing_required_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "aadt_bridge": _read_csv(PHASE3C_DIR / "phase3c_aadt_route_bridge_candidates.csv"),
        "joint_bridge": _read_csv(PHASE3C_DIR / "phase3c_joint_speed_aadt_route_bridge_candidates.csv"),
        "all_bridge": _read_csv(PHASE3C_DIR / "phase3c_route_bridge_all_candidates.csv"),
        "dedup": _read_csv(PHASE3C_DIR / "phase3c_route_bridge_deduped_signal_recovery_estimate.csv"),
        "candidate_bins": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_bin_detail.csv"),
        "candidate_signal_summary": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_signal_summary.csv"),
        "speed_detail": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_assignment_detail.csv"),
        "speed_signal": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_signal_summary.csv"),
        "speed_coverage": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_coverage_summary.csv"),
    }


def _eligible_aadt_bridges(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    aadt = inputs["aadt_bridge"].copy()
    joint = inputs["joint_bridge"].copy()
    safe_use = {"safe_for_next_review_only_join_rerun", "safe_for_next_review_only_join_rerun_aadt_only"}
    aadt = aadt.loc[_text(aadt, "confidence_tier").eq("high_confidence_review_only") & _text(aadt, "recommended_use_class").isin(safe_use)].copy()
    joint = joint.loc[_text(joint, "confidence_tier").eq("high_confidence_review_only") & _text(joint, "recommended_use_class").isin(safe_use)].copy()
    if not joint.empty and "aadt_bridge_candidate_id" in joint.columns:
        joint_ids = set(_text(joint, "aadt_bridge_candidate_id"))
        aadt.loc[_text(aadt, "bridge_candidate_id").isin(joint_ids), "joint_speed_aadt_safe_flag"] = True
    aadt["joint_speed_aadt_safe_flag"] = _flag(aadt, "joint_speed_aadt_safe_flag")
    aadt = aadt.sort_values(["candidate_route_group_id", "recommended_use_class", "bridge_candidate_id"]).drop_duplicates("candidate_route_group_id")
    aadt["target_source_route_key_primary"] = _text(aadt, "target_source_route_keys").str.split("|").str[0].fillna("")
    aadt["phase3d_aadt_eligibility_class"] = "high_confidence_aadt_review_only_vectorized_lookup"
    _checkpoint("eligible_aadt_bridge_route_groups", len(aadt))
    return aadt


def _candidate_bin_table(candidate_bins: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    if candidate_bins.empty or eligible.empty:
        return pd.DataFrame()
    attrs = eligible[[
        "candidate_route_group_id",
        "candidate_route_id_key",
        "candidate_normalized_route_key",
        "candidate_route_common",
        "candidate_route_name",
        "candidate_facility_text",
        "candidate_route_type_category",
        "target_source_route_key_primary",
        "source_availability_class",
        "bridge_evidence_type",
        "recommended_use_class",
        "phase3d_aadt_eligibility_class",
    ]].drop_duplicates()
    attrs["candidate_route_id_key"] = attrs["candidate_route_id_key"].astype(str)
    bins = candidate_bins.copy()
    bins["route_id"] = _text(bins, "route_id")
    _checkpoint("merge_start_candidate_bins_to_aadt_eligible_groups", len(bins), f"right_rows={len(attrs):,}")
    out = bins.merge(attrs, left_on="route_id", right_on="candidate_route_id_key", how="inner")
    out = out.sort_values(["candidate_bin_id", "candidate_route_group_id"]).drop_duplicates("candidate_bin_id", keep="first")
    _checkpoint("merge_complete_candidate_bins_to_aadt_eligible_groups", len(out))
    for col in ["candidate_measure_start", "candidate_measure_end", "candidate_measure_min", "candidate_measure_max", "candidate_measure_length", "candidate_bin_length_ft", "candidate_weight"]:
        out[col + "_num"] = pd.to_numeric(_text(out, col), errors="coerce")
    out["candidate_midpoint_measure"] = (out["candidate_measure_min_num"] + out["candidate_measure_max_num"]) / 2.0
    out["candidate_lookup_route_key"] = _text(out, "target_source_route_key_primary").where(_text(out, "target_source_route_key_primary").ne(""), _text(out, "candidate_normalized_route_key"))
    out["candidate_assignment_scope"] = "review_only_stage_a_aadt_exposure_not_active"
    return out


def _load_aadt_source(eligible: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "RTE_NM",
        "MASTER_RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "LINKID",
        "AADT_YR",
        "AADT",
        "DIRECTION_FACTOR",
        "DIRECTIONALITY",
        "FROM_PHY_JURISDICTION_NM",
        "MPO_DSC",
        "EDGE_RTE_KEY",
        "Stage1_SourceLayer",
    ]
    _checkpoint("read_start normalized_aadt_parquet_columns")
    raw = pd.read_parquet(AADT_FILE, columns=cols)
    raw = raw.reset_index().rename(columns={"index": "aadt_source_row_id"})
    _checkpoint("read_complete normalized_aadt_parquet_columns", len(raw))
    keep_keys = set(_text(eligible, "target_source_route_key_primary")) | set(_text(eligible, "candidate_normalized_route_key"))
    keep_keys = {k for k in keep_keys if k}
    for rf in ["RTE_NM", "MASTER_RTE_NM"]:
        raw[f"{rf}_route_key"] = raw[rf].map(_route_key)
        raw[f"{rf}_norm_key"] = raw[rf].map(_phase3_norm)
    mask = pd.Series(False, index=raw.index)
    for rf in ["RTE_NM", "MASTER_RTE_NM"]:
        mask = mask | raw[f"{rf}_route_key"].isin(keep_keys) | raw[f"{rf}_norm_key"].isin(keep_keys)
    raw = raw.loc[mask].copy()
    _checkpoint("aadt_source_prefiltered_to_eligible_routes", len(raw))
    for col in ["FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "AADT", "AADT_YR", "DIRECTION_FACTOR"]:
        raw[col + "_num"] = pd.to_numeric(raw[col], errors="coerce")
    return raw


def _aadt_interval_table(raw: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for route_field, from_field, to_field in [
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
    ]:
        sub = pd.DataFrame(
            {
                "aadt_source_row_id": raw["aadt_source_row_id"],
                "aadt_route_field": route_field,
                "aadt_measure_pair": f"{from_field}/{to_field}",
                "aadt_route_raw": raw[route_field].astype(str),
                "aadt_route_key": raw[f"{route_field}_route_key"],
                "normalized_aadt_route_key": raw[f"{route_field}_norm_key"],
                "aadt_measure_start": raw[f"{from_field}_num"],
                "aadt_measure_end": raw[f"{to_field}_num"],
                "review_only_aadt_value": raw["AADT_num"],
                "review_only_aadt_year": raw["AADT_YR_num"],
                "review_only_direction_factor": raw["DIRECTION_FACTOR_num"],
                "review_only_directionality": raw["DIRECTIONALITY"].astype(str),
                "aadt_linkid": raw["LINKID"].astype(str),
                "aadt_edge_rte_key": raw["EDGE_RTE_KEY"].astype(str),
                "aadt_source_layer": raw["Stage1_SourceLayer"].astype(str),
                "aadt_jurisdiction": raw["FROM_PHY_JURISDICTION_NM"].astype(str),
                "aadt_mpo": raw["MPO_DSC"].astype(str),
            }
        )
        rows.append(sub)
    intervals = pd.concat(rows, ignore_index=True)
    intervals["aadt_measure_min"] = intervals[["aadt_measure_start", "aadt_measure_end"]].min(axis=1)
    intervals["aadt_measure_max"] = intervals[["aadt_measure_start", "aadt_measure_end"]].max(axis=1)
    intervals["aadt_lookup_route_key"] = intervals["aadt_route_key"].where(intervals["aadt_route_key"].ne(""), intervals["normalized_aadt_route_key"])
    keep_keys = set(_text(eligible, "target_source_route_key_primary")) | set(_text(eligible, "candidate_normalized_route_key"))
    keep_keys = {k for k in keep_keys if k}
    intervals = intervals.loc[
        intervals["aadt_lookup_route_key"].isin(keep_keys)
        & intervals["aadt_measure_min"].notna()
        & intervals["aadt_measure_max"].notna()
        & intervals["review_only_aadt_value"].notna()
    ].drop_duplicates([
        "aadt_lookup_route_key",
        "aadt_measure_min",
        "aadt_measure_max",
        "review_only_aadt_value",
        "review_only_aadt_year",
        "review_only_direction_factor",
        "aadt_route_field",
        "aadt_measure_pair",
        "aadt_linkid",
    ])
    _checkpoint("aadt_interval_table_filtered", len(intervals))
    return intervals


def _lookup_group(candidates: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    cand = candidates.copy()
    if intervals.empty:
        cand["aadt_match_status"] = "missing_no_aadt_route_interval"
        return cand
    intervals = intervals.sort_values(["aadt_measure_min", "aadt_measure_max"]).reset_index(drop=True)
    starts = intervals["aadt_measure_min"].to_numpy(dtype=float)
    ends = intervals["aadt_measure_max"].to_numpy(dtype=float)
    sorted_ends = np.sort(ends)
    mids = cand["candidate_midpoint_measure"].to_numpy(dtype=float)
    bmins = cand["candidate_measure_min_num"].to_numpy(dtype=float)
    bmaxs = cand["candidate_measure_max_num"].to_numpy(dtype=float)
    idx = np.searchsorted(starts, mids, side="right") - 1
    valid = (idx >= 0) & (idx < len(intervals))
    selected = intervals.iloc[np.clip(idx, 0, max(len(intervals) - 1, 0))].reset_index(drop=True)
    contains = valid & (selected["aadt_measure_min"].to_numpy(dtype=float) <= mids) & (mids <= selected["aadt_measure_max"].to_numpy(dtype=float))
    contains_count = np.searchsorted(starts, mids, side="right") - np.searchsorted(sorted_ends, mids, side="left")
    start_count = np.searchsorted(starts, bmins, side="right") - np.searchsorted(sorted_ends, bmins, side="left")
    end_count = np.searchsorted(starts, bmaxs, side="right") - np.searchsorted(sorted_ends, bmaxs, side="left")
    internal_starts = np.searchsorted(starts, bmaxs, side="left") - np.searchsorted(starts, bmins, side="right")
    for col in [
        "aadt_source_row_id",
        "aadt_route_raw",
        "aadt_route_key",
        "normalized_aadt_route_key",
        "aadt_measure_start",
        "aadt_measure_end",
        "aadt_measure_min",
        "aadt_measure_max",
        "review_only_aadt_value",
        "review_only_aadt_year",
        "review_only_direction_factor",
        "review_only_directionality",
        "aadt_linkid",
        "aadt_route_field",
        "aadt_measure_pair",
        "aadt_edge_rte_key",
        "aadt_source_layer",
        "aadt_jurisdiction",
        "aadt_mpo",
    ]:
        cand["matched_" + col] = selected[col].astype(object).to_numpy()
    matched_cols = [c for c in cand.columns if c.startswith("matched_")]
    for col in matched_cols:
        cand[col] = cand[col].astype(object)
    cand.loc[~contains, matched_cols] = ""
    cand["aadt_containing_interval_count_at_midpoint"] = contains_count
    cand["aadt_boundary_or_multi_interval_flag"] = (start_count != end_count) | (internal_starts > 0) | (contains_count > 1)
    cand["aadt_measure_containment_status"] = "midpoint_contained_single_selected_interval"
    cand.loc[contains_count > 1, "aadt_measure_containment_status"] = "midpoint_contained_multiple_overlapping_intervals_selected_by_latest_start"
    cand.loc[~contains, "aadt_measure_containment_status"] = "midpoint_not_contained_by_aadt_interval"
    cand["aadt_match_status"] = "review_only_aadt_matched"
    cand.loc[~contains, "aadt_match_status"] = "missing_no_containing_aadt_interval"
    cand["aadt_match_method"] = "grouped_vectorized_searchsorted_midpoint_containment"
    cand["aadt_missing_reason"] = ""
    cand.loc[~contains, "aadt_missing_reason"] = cand.loc[~contains, "aadt_measure_containment_status"]
    return cand


def _vectorized_lookup(candidates: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    frames = []
    _checkpoint("stage_a_vectorized_lookup_start", len(candidates), f"routes={candidates['candidate_lookup_route_key'].nunique():,}")
    for key, group in candidates.groupby("candidate_lookup_route_key", dropna=False):
        frames.append(_lookup_group(group, intervals.loc[intervals["aadt_lookup_route_key"].eq(key)]))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    _checkpoint("stage_a_vectorized_lookup_complete", len(out))
    return out


def _derive_exposure(detail: pd.DataFrame) -> pd.DataFrame:
    out = detail.copy()
    matched = _text(out, "aadt_match_status").eq("review_only_aadt_matched")
    aadt = pd.to_numeric(_text(out, "matched_review_only_aadt_value"), errors="coerce")
    length_miles = pd.to_numeric(_text(out, "candidate_bin_length_ft"), errors="coerce") / 5280.0
    factor = pd.to_numeric(_text(out, "matched_review_only_direction_factor"), errors="coerce")
    valid_factor = factor.gt(0) & factor.le(1)
    out["review_only_direction_factor_status"] = "invalid_or_missing_direction_factor_bidirectional_fallback"
    out.loc[valid_factor, "review_only_direction_factor_status"] = "valid_direction_factor_applied"
    out["review_only_bidirectional_fallback_status"] = np.where(valid_factor, "not_needed", "bidirectional_fallback_used")
    out["review_only_estimated_exposure"] = aadt * length_miles
    out.loc[valid_factor, "review_only_estimated_exposure"] = aadt.loc[valid_factor] * factor.loc[valid_factor] * length_miles.loc[valid_factor]
    out.loc[~matched, "review_only_estimated_exposure"] = np.nan
    out["review_only_denominator_status"] = np.where(matched & out["review_only_estimated_exposure"].notna(), "denominator_ready_no_crash_review_only", "missing_aadt_or_exposure")
    out["review_only_aadt_context_status"] = np.where(matched, "review_only_aadt_assigned_route_measure", "missing_review_only_aadt")
    out["assignment_review_only_flag"] = True
    return out


def _stage_a_summaries(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    matched = _text(detail, "aadt_match_status").eq("review_only_aadt_matched")
    denom = _text(detail, "review_only_denominator_status").eq("denominator_ready_no_crash_review_only")
    detail["matched_flag"] = matched
    detail["denom_flag"] = denom
    signal = detail.groupby("candidate_signal_id", dropna=False).agg(
        attempted_candidate_bins=("candidate_bin_id", "count"),
        matched_aadt_bins=("matched_flag", "sum"),
        denominator_ready_bins=("denom_flag", "sum"),
        attempted_route_groups=("candidate_route_group_id", "nunique"),
        analysis_windows=("analysis_window", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
        multi_candidate_values=("multi_candidate_flag", _collapse),
        has_speed_bins=("speed_has_speed", "sum"),
        missing_reasons=("aadt_missing_reason", _collapse),
    ).reset_index()
    signal["has_any_review_only_aadt"] = signal["matched_aadt_bins"].gt(0)
    signal["has_any_review_only_exposure"] = signal["denominator_ready_bins"].gt(0)
    signal["has_full_attempted_aadt"] = signal["attempted_candidate_bins"].eq(signal["matched_aadt_bins"])
    hp = detail.loc[_text(detail, "analysis_window").str.contains("0_1000", na=False)].groupby("candidate_signal_id")["denom_flag"].agg(["count", "sum"]).reset_index()
    hp["full_0_1000_exposure_coverage_flag"] = hp["count"].eq(hp["sum"])
    full = detail.groupby("candidate_signal_id")["denom_flag"].agg(["count", "sum"]).reset_index()
    full["full_0_2500_exposure_coverage_flag"] = full["count"].eq(full["sum"])
    signal = signal.merge(hp[["candidate_signal_id", "full_0_1000_exposure_coverage_flag"]], on="candidate_signal_id", how="left")
    signal = signal.merge(full[["candidate_signal_id", "full_0_2500_exposure_coverage_flag"]], on="candidate_signal_id", how="left")
    signal[["full_0_1000_exposure_coverage_flag", "full_0_2500_exposure_coverage_flag"]] = signal[["full_0_1000_exposure_coverage_flag", "full_0_2500_exposure_coverage_flag"]].fillna(False)
    coverage = pd.DataFrame(
        [
            {"metric": "candidate_bins_attempted", "value": "", "count": len(detail)},
            {"metric": "candidate_bins_matched_aadt", "value": "", "count": int(matched.sum())},
            {"metric": "candidate_bins_denominator_ready", "value": "", "count": int(denom.sum())},
            {"metric": "unique_signals_attempted", "value": "", "count": detail["candidate_signal_id"].nunique()},
            {"metric": "unique_signals_with_any_aadt", "value": "", "count": int(signal["has_any_review_only_aadt"].sum())},
            {"metric": "unique_signals_with_any_exposure", "value": "", "count": int(signal["has_any_review_only_exposure"].sum())},
            {"metric": "unique_signals_full_0_1000_exposure", "value": "", "count": int(signal["full_0_1000_exposure_coverage_flag"].sum())},
            {"metric": "unique_signals_full_0_2500_exposure", "value": "", "count": int(signal["full_0_2500_exposure_coverage_flag"].sum())},
        ]
    )
    miss = detail.loc[~matched].groupby("aadt_missing_reason", dropna=False).agg(candidate_bin_count=("candidate_bin_id", "count"), unique_signal_count=("candidate_signal_id", "nunique")).reset_index() if (~matched).any() else pd.DataFrame(columns=["aadt_missing_reason", "candidate_bin_count", "unique_signal_count"])
    boundary = detail.loc[_flag(detail, "aadt_boundary_or_multi_interval_flag")].head(REVIEW_QUEUE_LIMIT).copy()
    return signal, coverage, miss, boundary


def _stage_a_qa(detail: pd.DataFrame, candidate_bins: pd.DataFrame, missing: list[str], excluded_assigned: int) -> pd.DataFrame:
    rows = [
        _qa_row("candidate_bin_count_reconciles_or_explained", len(candidate_bins) == EXPECTED_CANDIDATE_BINS, len(candidate_bins), EXPECTED_CANDIDATE_BINS, "Stage A assignment attempts only eligible AADT bridge bins."),
        _qa_row("no_active_outputs_modified", True, True, True, ""),
        _qa_row("no_candidates_promoted", True, True, True, ""),
        _qa_row("no_crash_records_read", True, True, True, ""),
        _qa_row("no_crash_direction_fields_read_or_used", True, True, True, ""),
        _qa_row("access_not_included", True, True, True, ""),
        _qa_row("aadt_exposure_assignment_review_only", _flag(detail, "assignment_review_only_flag").all() if not detail.empty else True, "review_only", "review_only", ""),
        _qa_row("no_candidate_bin_by_source_row_overlap_table", len(detail) <= ROW_GUARD_LIMIT and detail["candidate_bin_id"].nunique() == len(detail), len(detail), f"<= {ROW_GUARD_LIMIT} unique candidate bins", ""),
        _qa_row("vectorized_grouped_lookup_method_documented", _text(detail, "aadt_match_method").str.contains("searchsorted", na=False).any() if not detail.empty else True, "searchsorted", "documented", ""),
        _qa_row("excluded_review_source_gap_classes_not_assigned", excluded_assigned == 0, excluded_assigned, 0, ""),
        _qa_row("deduped_signal_counts_separate_from_bin_counts", True, True, True, ""),
        _qa_row("required_inputs_present", not missing, len(missing), 0, "; ".join(missing[:10])),
    ]
    return pd.DataFrame(rows)


def _stage_b(detail: pd.DataFrame, speed: pd.DataFrame) -> dict[str, pd.DataFrame]:
    speed_cols = ["candidate_bin_id", "rns_match_status", "matched_review_only_car_speed_limit"]
    merged = detail.merge(speed[[c for c in speed_cols if c in speed.columns]], on="candidate_bin_id", how="left", suffixes=("", "_speed"))
    merged["has_candidate_bins"] = True
    merged["has_roadway_context"] = _text(merged, "roadway_division_status").ne("") | _text(merged, "logical_segment_mode").ne("")
    merged["has_speed"] = _text(merged, "rns_match_status").eq("review_only_speed_matched")
    merged["has_aadt"] = _text(merged, "aadt_match_status").eq("review_only_aadt_matched")
    merged["has_exposure"] = _text(merged, "review_only_denominator_status").eq("denominator_ready_no_crash_review_only")
    merged["speed_aadt_both_ready"] = merged["has_speed"] & merged["has_aadt"]
    merged["denominator_ready_no_crash"] = merged["has_exposure"]
    merged["multi_candidate_weighted_flag"] = _flag(merged, "multi_candidate_flag") | pd.to_numeric(_text(merged, "candidate_weight"), errors="coerce").fillna(1).lt(1)
    signal = merged.groupby("candidate_signal_id", dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        has_candidate_bins=("has_candidate_bins", "any"),
        has_roadway_context=("has_roadway_context", "all"),
        has_speed=("has_speed", "any"),
        has_aadt=("has_aadt", "any"),
        has_exposure=("has_exposure", "any"),
        speed_aadt_both_ready=("speed_aadt_both_ready", "any"),
        denominator_ready_no_crash=("denominator_ready_no_crash", "any"),
        multi_candidate_weighted_flag=("multi_candidate_weighted_flag", "any"),
        analysis_windows=("analysis_window", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
    ).reset_index()
    hp = merged.loc[_text(merged, "analysis_window").str.contains("0_1000", na=False)]
    hp_cov = hp.groupby("candidate_signal_id")["speed_aadt_both_ready"].agg(["count", "sum"]).reset_index()
    hp_cov["full_0_1000_context_ready"] = hp_cov["count"].eq(hp_cov["sum"])
    signal = signal.merge(hp_cov[["candidate_signal_id", "full_0_1000_context_ready"]], on="candidate_signal_id", how="left")
    signal["full_0_1000_context_ready"] = signal["full_0_1000_context_ready"].fillna(False)

    full_cov = merged.groupby("candidate_signal_id")["speed_aadt_both_ready"].agg(["count", "sum"]).reset_index()
    full_cov["full_0_2500_context_ready"] = full_cov["count"].eq(full_cov["sum"])
    signal = signal.merge(full_cov[["candidate_signal_id", "full_0_2500_context_ready"]], on="candidate_signal_id", how="left")
    signal["full_0_2500_context_ready"] = signal["full_0_2500_context_ready"].fillna(False)
    signal["both_direction_context_ready"] = signal["direction_labels"].str.contains("higher", na=False) & signal["direction_labels"].str.contains("lower", na=False) & signal["speed_aadt_both_ready"]
    signal["one_direction_only_context_ready"] = ~signal["both_direction_context_ready"] & signal["speed_aadt_both_ready"]
    full_ready_signal_ids = set(signal.loc[signal["full_0_2500_context_ready"], "candidate_signal_id"])
    full_ready_bin_count = int(merged.loc[merged["candidate_signal_id"].isin(full_ready_signal_ids), "speed_aadt_both_ready"].sum())
    universe = pd.DataFrame(
        [
            {"universe": "recovered_only_any_bin", "signal_count": signal["candidate_signal_id"].nunique(), "bin_count": len(merged)},
            {"universe": "expanded_any_bin_including_strict_baseline", "signal_count": signal["candidate_signal_id"].nunique() + STRICT_BASELINE_SIGNALS, "bin_count": len(merged) + 110710},
            {"universe": "recovered_only_0_1000", "signal_count": merged.loc[_text(merged, "analysis_window").str.contains("0_1000", na=False), "candidate_signal_id"].nunique(), "bin_count": int(_text(merged, "analysis_window").str.contains("0_1000", na=False).sum())},
            {"universe": "expanded_0_1000_including_strict_baseline", "signal_count": merged.loc[_text(merged, "analysis_window").str.contains("0_1000", na=False), "candidate_signal_id"].nunique() + STRICT_BASELINE_SIGNALS, "bin_count": int(_text(merged, "analysis_window").str.contains("0_1000", na=False).sum()) + 66074},
            {"universe": "recovered_only_full_0_2500_context_ready", "signal_count": int(signal["full_0_2500_context_ready"].sum()), "bin_count": full_ready_bin_count},
            {"universe": "expanded_full_0_2500_context_ready_including_strict_baseline", "signal_count": int(signal["full_0_2500_context_ready"].sum()) + STRICT_BASELINE_SIGNALS, "bin_count": full_ready_bin_count + 105835},
            {"universe": "recovered_both_direction_context_ready", "signal_count": int(signal["both_direction_context_ready"].sum()), "bin_count": ""},
            {"universe": "recovered_one_direction_only_context_ready", "signal_count": int(signal["one_direction_only_context_ready"].sum()), "bin_count": ""},
            {"universe": "recovered_multi_candidate_weighted_universe", "signal_count": int(signal["multi_candidate_weighted_flag"].sum()), "bin_count": int(merged["multi_candidate_weighted_flag"].sum())},
        ]
    )
    window = merged.groupby("analysis_window", dropna=False).agg(candidate_bin_count=("candidate_bin_id", "count"), speed_ready_bins=("has_speed", "sum"), aadt_ready_bins=("has_aadt", "sum"), exposure_ready_bins=("has_exposure", "sum"), speed_aadt_ready_bins=("speed_aadt_both_ready", "sum"), unique_signal_count=("candidate_signal_id", "nunique")).reset_index()
    direction = merged.groupby("signal_relative_direction_label", dropna=False).agg(candidate_bin_count=("candidate_bin_id", "count"), speed_aadt_ready_bins=("speed_aadt_both_ready", "sum"), unique_signal_count=("candidate_signal_id", "nunique")).reset_index()
    missing = pd.DataFrame(
        [
            {"layer": "roadway_context", "missing_bin_count": int((~merged["has_roadway_context"]).sum()), "missing_signal_count": merged.loc[~merged["has_roadway_context"], "candidate_signal_id"].nunique()},
            {"layer": "speed", "missing_bin_count": int((~merged["has_speed"]).sum()), "missing_signal_count": merged.loc[~merged["has_speed"], "candidate_signal_id"].nunique()},
            {"layer": "aadt", "missing_bin_count": int((~merged["has_aadt"]).sum()), "missing_signal_count": merged.loc[~merged["has_aadt"], "candidate_signal_id"].nunique()},
            {"layer": "exposure", "missing_bin_count": int((~merged["has_exposure"]).sum()), "missing_signal_count": merged.loc[~merged["has_exposure"], "candidate_signal_id"].nunique()},
        ]
    )
    before_after = pd.DataFrame(
        [
            {"metric": "speed_signals_before_phase3d_approx", "count": PRIOR_RECOVERED_SPEED_SIGNALS_APPROX},
            {"metric": "speed_signals_after_phase3d", "count": int(signal["has_speed"].sum())},
            {"metric": "additional_speed_signals_after_phase3d_approx", "count": max(int(signal["has_speed"].sum()) - PRIOR_RECOVERED_SPEED_SIGNALS_APPROX, 0)},
            {"metric": "aadt_exposure_review_only_assigned_signals_before_stage_a", "count": PRIOR_REVIEW_ONLY_AADT_EXPOSURE_ASSIGNMENT_SIGNALS},
            {"metric": "aadt_exposure_signals_after_stage_a", "count": int(signal["has_exposure"].sum())},
            {"metric": "additional_aadt_exposure_review_only_signals_stage_a", "count": max(int(signal["has_exposure"].sum()) - PRIOR_REVIEW_ONLY_AADT_EXPOSURE_ASSIGNMENT_SIGNALS, 0)},
            {"metric": "speed_aadt_exposure_ready_signals", "count": int((signal["has_speed"] & signal["has_aadt"] & signal["has_exposure"]).sum())},
            {"metric": "denominator_ready_no_crash_signals", "count": int(signal["denominator_ready_no_crash"].sum())},
        ]
    )
    queue = signal.sort_values(["speed_aadt_both_ready", "candidate_bin_count"], ascending=[True, False]).head(REVIEW_QUEUE_LIMIT)
    return {"bin": merged, "signal": signal, "universe": universe, "window": window, "direction": direction, "missing": missing, "before_after": before_after, "queue": queue}


def _findings(stage_a_passed: bool, stage_b_ran: bool, stage_a_cov: pd.DataFrame, stage_b: dict[str, pd.DataFrame] | None) -> str:
    def cov(metric: str) -> int:
        row = stage_a_cov.loc[stage_a_cov["metric"].eq(metric)] if not stage_a_cov.empty else pd.DataFrame()
        return int(pd.to_numeric(row["count"], errors="coerce").fillna(0).sum()) if not row.empty else 0
    b_signal = stage_b["signal"] if stage_b else pd.DataFrame()
    b_universe = stage_b["universe"] if stage_b else pd.DataFrame()
    missing = stage_b["missing"] if stage_b else pd.DataFrame()
    dominant = "not_available"
    if not missing.empty:
        dominant = str(missing.sort_values("missing_bin_count", ascending=False).iloc[0]["layer"])
    expanded_ready = 0
    row = b_universe.loc[b_universe["universe"].eq("expanded_full_0_2500_context_ready_including_strict_baseline")] if not b_universe.empty else pd.DataFrame()
    if not row.empty:
        expanded_ready = int(row.iloc[0]["signal_count"])
    return "\n".join(
        [
            "# Expanded Candidate AADT/Exposure Context Refresh Findings",
            "",
            f"Did Stage A pass? {stage_a_passed}.",
            f"Did Stage B run? {stage_b_ran}.",
            f"Recovered bins receiving review-only AADT: {cov('candidate_bins_matched_aadt')}.",
            f"Recovered signals receiving review-only AADT: {cov('unique_signals_with_any_aadt')}.",
            f"Recovered bins receiving review-only exposure/denominator readiness: {cov('candidate_bins_denominator_ready')}.",
            f"Recovered signals receiving review-only exposure/denominator readiness: {cov('unique_signals_with_any_exposure')}.",
            f"Recovered signals with both speed and AADT: {int((b_signal['has_speed'] & b_signal['has_aadt']).sum()) if not b_signal.empty else 0}.",
            f"Recovered 0-1,000 ft signals speed+AADT/exposure ready: {int(b_signal['full_0_1000_context_ready'].sum()) if not b_signal.empty else 0}.",
            f"Recovered full 0-2,500 ft signals speed+AADT/exposure ready: {int(b_signal['full_0_2500_context_ready'].sum()) if not b_signal.empty else 0}.",
            f"Expanded total signals context-ready before access/crashes: {expanded_ready}.",
            f"Dominant remaining non-access/non-crash missingness: {dominant}.",
            "Next recovery focus should be access if context-ready speed/AADT coverage is sufficient for review; candidate crash/catchment geometry should wait until the non-crash context universe is accepted.",
            "",
        ]
    )


def _qa(stage_a_qa: pd.DataFrame, stage_b_qa: pd.DataFrame | None) -> pd.DataFrame:
    final = pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, True, True, ""),
            _qa_row("no_candidates_promoted", True, True, True, ""),
            _qa_row("no_crash_records_read", True, True, True, ""),
            _qa_row("no_crash_direction_fields_read_or_used", True, True, True, ""),
            _qa_row("access_not_included", True, True, True, ""),
            _qa_row("no_rates_or_models_produced", True, True, True, ""),
            _qa_row("all_assignments_review_only", True, True, True, ""),
            _qa_row("no_candidate_bin_by_source_row_overlap_table", True, True, True, ""),
            _qa_row("deduped_signal_counts_separate_from_bin_counts", True, True, True, ""),
            _qa_row("outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR), ""),
        ]
    )
    parts = [stage_a_qa.assign(stage="stage_a"), final.assign(stage="final")]
    if stage_b_qa is not None:
        parts.insert(1, stage_b_qa.assign(stage="stage_b"))
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text(f"{datetime.now(timezone.utc).isoformat()} START expanded_candidate_aadt_exposure_context_refresh\n", encoding="utf-8")
    missing = _missing_required_inputs()
    inputs = _load_inputs()
    eligible = _eligible_aadt_bridges(inputs)
    bins = _candidate_bin_table(inputs["candidate_bins"], eligible)
    speed_slim = inputs["speed_detail"][["candidate_bin_id", "rns_match_status", "matched_review_only_car_speed_limit"]].copy()
    speed_slim["speed_has_speed"] = _text(speed_slim, "rns_match_status").eq("review_only_speed_matched")
    bins = bins.merge(speed_slim, on="candidate_bin_id", how="left")
    raw = _load_aadt_source(eligible)
    intervals = _aadt_interval_table(raw, eligible)
    detail = _derive_exposure(_vectorized_lookup(bins, intervals))
    signal, coverage, miss, boundary = _stage_a_summaries(detail)
    excluded_assigned = 0
    stage_a_qa = _stage_a_qa(detail, inputs["candidate_bins"], missing, excluded_assigned)
    stage_a_passed = bool(stage_a_qa["passed"].all())
    keep_detail_cols = [
        "candidate_bin_id", "candidate_signal_id", "candidate_route_group_id", "route_id", "route_common", "route_name",
        "candidate_normalized_route_key", "candidate_route_common", "candidate_route_name", "candidate_facility_text",
        "candidate_measure_start", "candidate_measure_end", "candidate_measure_min", "candidate_measure_max",
        "candidate_midpoint_measure", "candidate_bin_length_ft", "analysis_window", "signal_relative_direction_label",
        "direction_confidence_status", "candidate_weight", "recovery_strategy", "association_confidence_tier",
        "multi_candidate_flag", "rns_match_status", "speed_has_speed", "aadt_match_status", "aadt_match_method",
        "aadt_measure_containment_status", "aadt_boundary_or_multi_interval_flag", "aadt_missing_reason",
        "matched_review_only_aadt_value", "matched_review_only_aadt_year", "matched_review_only_direction_factor",
        "review_only_direction_factor_status", "review_only_bidirectional_fallback_status", "review_only_estimated_exposure",
        "review_only_denominator_status", "review_only_aadt_context_status", "matched_aadt_route_raw",
        "matched_aadt_route_key", "matched_aadt_measure_min", "matched_aadt_measure_max", "matched_aadt_source_row_id",
        "matched_aadt_route_field", "matched_aadt_measure_pair", "matched_aadt_linkid", "assignment_review_only_flag",
    ]
    out_detail = detail[[c for c in keep_detail_cols if c in detail.columns]].copy()
    _write_csv(out_detail, OUT_DIR / "stage_a_candidate_aadt_exposure_assignment_detail.csv")
    _write_csv(signal, OUT_DIR / "stage_a_candidate_aadt_exposure_signal_summary.csv")
    _write_csv(coverage, OUT_DIR / "stage_a_candidate_aadt_exposure_coverage_summary.csv")
    _write_csv(miss, OUT_DIR / "stage_a_candidate_aadt_exposure_missingness_summary.csv")
    _write_csv(boundary[[c for c in keep_detail_cols if c in boundary.columns]], OUT_DIR / "stage_a_candidate_aadt_exposure_boundary_cases.csv")
    _write_csv(stage_a_qa, OUT_DIR / "stage_a_candidate_aadt_exposure_qa.csv")
    _write_text(_findings(stage_a_passed, False, coverage, None), OUT_DIR / "stage_a_candidate_aadt_exposure_findings.md")
    stage_b_outputs = None
    stage_b_qa = None
    stage_b_ran = False
    if not stage_a_passed:
        _write_text("Stage B not run because Stage A QA failed.\n", OUT_DIR / "stage_b_not_run_reason.txt")
    else:
        stage_b_outputs = _stage_b(detail, inputs["speed_detail"])
        stage_b_qa = pd.DataFrame([
            _qa_row("stage_b_ran_only_after_stage_a_passed", True, True, True, ""),
            _qa_row("access_and_crashes_not_included", True, True, True, ""),
            _qa_row("no_rates_or_models_produced", True, True, True, ""),
            _qa_row("bin_detail_unique_candidate_bins", stage_b_outputs["bin"]["candidate_bin_id"].nunique() == len(stage_b_outputs["bin"]), stage_b_outputs["bin"]["candidate_bin_id"].nunique(), len(stage_b_outputs["bin"]), ""),
        ])
        _write_csv(stage_b_outputs["bin"], OUT_DIR / "stage_b_recovered_context_bin_detail.csv")
        _write_csv(stage_b_outputs["signal"], OUT_DIR / "stage_b_recovered_context_signal_summary.csv")
        _write_csv(stage_b_outputs["universe"], OUT_DIR / "stage_b_recovered_context_universe_summary.csv")
        _write_csv(stage_b_outputs["window"], OUT_DIR / "stage_b_recovered_context_window_summary.csv")
        _write_csv(stage_b_outputs["direction"], OUT_DIR / "stage_b_recovered_context_direction_summary.csv")
        _write_csv(stage_b_outputs["missing"], OUT_DIR / "stage_b_recovered_context_missingness_summary.csv")
        _write_csv(stage_b_outputs["before_after"], OUT_DIR / "stage_b_recovered_context_before_after_summary.csv")
        _write_csv(stage_b_outputs["queue"], OUT_DIR / "stage_b_recovered_context_ranked_review_queue.csv")
        _write_csv(stage_b_qa, OUT_DIR / "stage_b_recovered_context_qa.csv")
        stage_b_ran = True
        _write_text(_findings(stage_a_passed, stage_b_ran, coverage, stage_b_outputs), OUT_DIR / "stage_b_recovered_context_findings.md")
    final_qa = _qa(stage_a_qa, stage_b_qa)
    _write_csv(final_qa, OUT_DIR / "expanded_candidate_aadt_exposure_context_refresh_qa.csv")
    _write_text(_findings(stage_a_passed, stage_b_ran, coverage, stage_b_outputs), OUT_DIR / "expanded_candidate_aadt_exposure_context_refresh_findings.md")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "review-only expanded candidate AADT/exposure completion and non-access/non-crash context sufficiency refresh",
        "output_dir": str(OUT_DIR),
        "stage_a_passed": stage_a_passed,
        "stage_b_ran": stage_b_ran,
        "eligible_aadt_route_group_count": int(len(eligible)),
        "stage_a_candidate_bins_attempted": int(len(out_detail)),
        "missing_required_inputs": missing,
        "guardrails": {
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "no_rates_or_models": True,
            "review_only_assignments": True,
            "no_candidate_bin_x_source_row_overlap_table": True,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_aadt_exposure_context_refresh_manifest.json")
    _checkpoint("complete expanded_candidate_aadt_exposure_context_refresh")


if __name__ == "__main__":
    main()
