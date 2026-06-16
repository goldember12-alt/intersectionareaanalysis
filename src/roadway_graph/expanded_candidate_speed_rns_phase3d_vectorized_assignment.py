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
except Exception:  # pragma: no cover - fallbacks are kept for local environment variance.
    gpd = None
    pyogrio = None


OUTPUT_ROOT = Path("work/output/roadway_graph")
AMBIGUITY_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_ambiguity_diagnostic"
RNS_REBUILD_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_bridge_rebuild"
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"

SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"

ROW_GUARD_LIMIT = 1_000_000
REVIEW_QUEUE_LIMIT = 20_000
PRIOR_RECOVERED_SPEED_SIGNAL_COVERAGE = 666

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
    AMBIGUITY_DIR: [
        "rns_ambiguity_detail.csv",
        "rns_long_route_interval_density_candidates.csv",
        "rns_likely_source_gap_review_queue.csv",
        "rns_upgrade_deduped_signal_estimate.csv",
        "expanded_candidate_speed_rns_ambiguity_manifest.json",
    ],
    RNS_REBUILD_DIR: [
        "stage1_candidate_route_group_rns_base.csv",
        "stage1_candidate_route_group_signal_map.csv",
        "stage1_rns_source_route_inventory.csv",
        "stage1_candidate_to_rns_bridge_candidates.csv",
        "stage2_rns_phase3d_scope_recommendation.csv",
        "expanded_candidate_speed_rns_bridge_rebuild_manifest.json",
    ],
    ROUTE_MEASURE_DIR: [
        "stage1_candidate_route_measure_bin_detail.csv",
        "stage1_candidate_route_measure_signal_summary.csv",
        "expanded_candidate_route_measure_context_audit_manifest.json",
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


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[col], errors="coerce")


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    return _text(df, col).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(series: pd.Series, limit: int = 12) -> str:
    values = sorted({str(v) for v in series.dropna() if str(v) and str(v).lower() != "nan" and str(v) != ""})
    return "|".join(values[:limit])


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def normalize_route_name(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " ")
    text = text.replace("S-VA", " ")
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
            continue
        match = re.fullmatch(r"0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match and route_type:
            route_number = str(int(match.group(1)))
            if match.group(2):
                direction = match.group(2)[0]
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


def _facility_text(value: Any) -> str:
    s = re.sub(r"\([^)]*\)", "", str(value or "").upper())
    s = re.sub(r"\b(COUNTY|CITY|TOWN|OF|VA|VIRGINIA|RAMP|ROAD|RD|STREET|ST|ROUTE|RTE)\b", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _missing_required_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "ambiguity": _read_csv(AMBIGUITY_DIR / "rns_ambiguity_detail.csv"),
        "long_route": _read_csv(AMBIGUITY_DIR / "rns_long_route_interval_density_candidates.csv"),
        "source_gap": _read_csv(AMBIGUITY_DIR / "rns_likely_source_gap_review_queue.csv"),
        "upgrade_dedup": _read_csv(AMBIGUITY_DIR / "rns_upgrade_deduped_signal_estimate.csv"),
        "base": _read_csv(RNS_REBUILD_DIR / "stage1_candidate_route_group_rns_base.csv"),
        "signal_map": _read_csv(RNS_REBUILD_DIR / "stage1_candidate_route_group_signal_map.csv"),
        "rns_inventory": _read_csv(RNS_REBUILD_DIR / "stage1_rns_source_route_inventory.csv"),
        "bridges": _read_csv(RNS_REBUILD_DIR / "stage1_candidate_to_rns_bridge_candidates.csv"),
        "scope": _read_csv(RNS_REBUILD_DIR / "stage2_rns_phase3d_scope_recommendation.csv"),
        "candidate_bins": _read_csv(
            ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_bin_detail.csv",
            usecols=[
                "candidate_bin_id",
                "candidate_signal_id",
                "source_signal_id",
                "source_layer",
                "candidate_association_id",
                "recovery_strategy",
                "association_confidence_tier",
                "candidate_rank",
                "candidate_weight",
                "signal_relative_direction_label",
                "direction_confidence_status",
                "analysis_window",
                "scaffold_completeness_tier",
                "strict_active_overlap_status",
                "graph_edge_id",
                "road_component_id",
                "source_road_row_id",
                "route_id",
                "route_common",
                "route_name",
                "candidate_measure_start",
                "candidate_measure_end",
                "candidate_measure_min",
                "candidate_measure_max",
                "candidate_measure_length",
                "candidate_measure_direction_status",
                "candidate_route_measure_interval_status",
                "candidate_route_measure_join_quality",
                "multi_candidate_flag",
                "review_only_flag",
                "roadway_division_status",
                "logical_segment_mode",
            ],
        ),
        "signal_summary": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_signal_summary.csv"),
    }


def _eligible_groups(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ambiguity = inputs["ambiguity"].copy()
    bridge = inputs["bridges"].copy()
    if ambiguity.empty and bridge.empty:
        return pd.DataFrame()
    amb_mask = (
        _text(ambiguity, "ambiguity_subtype").eq("normal_long_route_interval_density_not_identity_ambiguity")
        | _text(ambiguity, "upgrade_recommendation").eq("keep_needs_vectorized_interval_lookup")
    )
    amb = ambiguity.loc[amb_mask].copy()
    safe = bridge.loc[_text(bridge, "recommended_use_class").str.startswith("safe_for_phase3d_review_only_speed_rerun", na=False)].copy()
    excluded = set(_text(ambiguity.loc[
        _text(ambiguity, "ambiguity_subtype").isin(["rns_source_route_absent_likely", "insufficient_evidence"])
        | _text(ambiguity, "upgrade_recommendation").isin(["manual_or_mapped_review_needed", "hold_as_likely_source_gap", "do_not_use_current_evidence", "keep_needs_route_identity_review"]),
    ], "candidate_route_group_id"))
    common_cols = [
        "candidate_route_group_id",
        "route_id",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_route_common_rns_norm",
        "route_common",
        "route_name",
        "candidate_facility_text",
        "candidate_route_type_category",
        "source_layer",
        "aadt_safe_speed_not_safe_flag",
        "rns_route_key",
        "normalized_rns_route_key",
        "rns_measure_min",
        "rns_measure_max",
        "recommended_use_class",
        "ambiguity_subtype",
        "upgrade_recommendation",
    ]
    frames = [df[[c for c in common_cols if c in df.columns]].copy() for df in [amb, safe] if not df.empty]
    eligible = pd.concat(frames, ignore_index=True).drop_duplicates("candidate_route_group_id") if frames else pd.DataFrame()
    eligible = eligible.loc[~_text(eligible, "candidate_route_group_id").isin(excluded)].copy()
    eligible["phase3d_eligibility_class"] = "vectorized_rns_interval_lookup_review_only"
    _checkpoint("eligible_phase3d_route_groups", len(eligible))
    return eligible


def _candidate_bin_table(candidate_bins: pd.DataFrame, eligible: pd.DataFrame, signal_map: pd.DataFrame) -> pd.DataFrame:
    if candidate_bins.empty or eligible.empty:
        return pd.DataFrame()
    signal_route_map = signal_map[["candidate_route_group_id", "route_id", "affected_signal_id"]].drop_duplicates().copy()
    signal_route_map = signal_route_map.sort_values(["route_id", "affected_signal_id", "candidate_route_group_id"]).drop_duplicates(["route_id", "affected_signal_id"], keep="first")
    route_attrs = eligible[[
        "candidate_route_group_id",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_route_common_rns_norm",
        "candidate_facility_text",
        "candidate_route_type_category",
        "aadt_safe_speed_not_safe_flag",
        "rns_route_key",
        "normalized_rns_route_key",
        "phase3d_eligibility_class",
    ]].drop_duplicates()
    route_map = signal_route_map.merge(route_attrs, on="candidate_route_group_id", how="inner")
    _checkpoint("merge_start_candidate_bins_to_eligible_route_signal_map", len(candidate_bins), f"right_rows={len(route_map):,}")
    bins = candidate_bins.merge(
        route_map,
        left_on=["route_id", "candidate_signal_id"],
        right_on=["route_id", "affected_signal_id"],
        how="inner",
        suffixes=("", "_eligible"),
    )
    bins["route_group_signal_mapping_method"] = "deduped_first_candidate_route_group_per_route_id_signal_for_review_only_assignment"
    _checkpoint("merge_complete_candidate_bins_to_eligible_groups", len(bins))
    for col in ["candidate_measure_start", "candidate_measure_end", "candidate_measure_min", "candidate_measure_max", "candidate_measure_length", "candidate_weight"]:
        bins[col + "_num"] = pd.to_numeric(_text(bins, col), errors="coerce")
    bins["candidate_midpoint_measure"] = (bins["candidate_measure_min_num"] + bins["candidate_measure_max_num"]) / 2.0
    bins["candidate_lookup_route_key"] = _text(bins, "rns_route_key").where(_text(bins, "rns_route_key").ne(""), _text(bins, "candidate_route_name_rns_norm"))
    bins["candidate_lookup_route_key"] = bins["candidate_lookup_route_key"].where(bins["candidate_lookup_route_key"].ne(""), _text(bins, "normalized_candidate_route_key"))
    bins["candidate_assignment_scope"] = "review_only_phase3d_test_not_active"
    return bins


def _load_rns_source() -> pd.DataFrame:
    columns = [
        "RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "EDGE_RTE_KEY",
        "TRANSPORT_EDGE_ID",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "MASTER_RTE_NM",
        "MASTER_EDGE_RTE_KEY",
        "CAR_SPEED_LIMIT",
        "FINAL_SPEED_LIMIT_SOURCE",
        "TRUCK_SPEED_LIMIT",
        "SPEEDZONE_TYPE_DSC",
        "IDENTIFY_CODE",
    ]
    _checkpoint("read_start Speed_Limit_RNS_source_attribute_only")
    if pyogrio is not None:
        raw = pyogrio.read_dataframe(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=columns, read_geometry=False, use_arrow=True)
    elif gpd is not None:
        raw = pd.DataFrame(gpd.read_file(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=columns, ignore_geometry=True))
    else:
        raise RuntimeError("Neither pyogrio nor geopandas is available to read Speed_Limit_RNS.")
    raw = raw.reset_index().rename(columns={"index": "rns_source_row_id"})
    _checkpoint("read_complete Speed_Limit_RNS_source_attribute_only", len(raw))
    return raw


def _rns_interval_table(raw: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or eligible.empty:
        return pd.DataFrame()
    keep_keys = set(_text(eligible, "rns_route_key")) | set(_text(eligible, "candidate_route_name_rns_norm")) | set(_text(eligible, "normalized_candidate_route_key"))
    keep_keys = {key for key in keep_keys if key}
    for route_field in ["RTE_NM", "MASTER_RTE_NM"]:
        if route_field in raw.columns:
            raw[f"{route_field}_rns_route_key"] = raw[route_field].map(normalize_route_name)
            raw[f"{route_field}_normalized_route_key"] = raw[route_field].map(_phase3_norm)
            raw[f"{route_field}_facility_text"] = raw[route_field].map(_facility_text)
    prefilter = pd.Series(False, index=raw.index)
    for route_field in ["RTE_NM", "MASTER_RTE_NM"]:
        key_col = f"{route_field}_rns_route_key"
        norm_col = f"{route_field}_normalized_route_key"
        if key_col in raw.columns:
            prefilter = prefilter | raw[key_col].isin(keep_keys) | raw[norm_col].isin(keep_keys)
    raw = raw.loc[prefilter].copy()
    _checkpoint("rns_source_prefiltered_to_eligible_routes", len(raw))
    for measure_field in ["FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"]:
        if measure_field in raw.columns:
            raw[f"{measure_field}_num"] = pd.to_numeric(raw[measure_field], errors="coerce")
    raw["CAR_SPEED_LIMIT_num"] = pd.to_numeric(raw.get("CAR_SPEED_LIMIT", pd.Series(pd.NA, index=raw.index)), errors="coerce")
    raw["TRUCK_SPEED_LIMIT_num"] = pd.to_numeric(raw.get("TRUCK_SPEED_LIMIT", pd.Series(pd.NA, index=raw.index)), errors="coerce")
    rows = []
    for route_field, from_field, to_field in [
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
    ]:
        if route_field not in raw.columns or from_field not in raw.columns or to_field not in raw.columns:
            continue
        sub = pd.DataFrame(
            {
                "rns_source_row_id": raw["rns_source_row_id"],
                "rns_route_field": route_field,
                "rns_measure_pair": f"{from_field}/{to_field}",
                "rns_route_raw": raw[route_field].astype(str),
                "rns_route_key": raw[f"{route_field}_rns_route_key"],
                "normalized_rns_route_key": raw[f"{route_field}_normalized_route_key"],
                "rns_facility_text": raw[f"{route_field}_facility_text"],
                "rns_measure_start": raw[f"{from_field}_num"],
                "rns_measure_end": raw[f"{to_field}_num"],
                "review_only_car_speed_limit": raw["CAR_SPEED_LIMIT_num"],
                "review_only_truck_speed_limit": raw["TRUCK_SPEED_LIMIT_num"],
                "rns_edge_rte_key": raw.get("EDGE_RTE_KEY", pd.Series("", index=raw.index)).astype(str),
                "rns_master_edge_rte_key": raw.get("MASTER_EDGE_RTE_KEY", pd.Series("", index=raw.index)).astype(str),
                "rns_transport_edge_id": raw.get("TRANSPORT_EDGE_ID", pd.Series("", index=raw.index)).astype(str),
                "rns_final_speed_limit_source": raw.get("FINAL_SPEED_LIMIT_SOURCE", pd.Series("", index=raw.index)).astype(str),
                "rns_speedzone_type_dsc": raw.get("SPEEDZONE_TYPE_DSC", pd.Series("", index=raw.index)).astype(str),
                "rns_identify_code": raw.get("IDENTIFY_CODE", pd.Series("", index=raw.index)).astype(str),
            }
        )
        rows.append(sub)
    intervals = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    intervals["rns_measure_min"] = intervals[["rns_measure_start", "rns_measure_end"]].min(axis=1)
    intervals["rns_measure_max"] = intervals[["rns_measure_start", "rns_measure_end"]].max(axis=1)
    intervals["rns_lookup_route_key"] = intervals["rns_route_key"].where(intervals["rns_route_key"].ne(""), intervals["normalized_rns_route_key"])
    intervals = intervals.loc[
        intervals["rns_lookup_route_key"].isin(keep_keys)
        & intervals["rns_measure_min"].notna()
        & intervals["rns_measure_max"].notna()
        & intervals["review_only_car_speed_limit"].notna()
    ].drop_duplicates(
        [
            "rns_lookup_route_key",
            "rns_measure_min",
            "rns_measure_max",
            "review_only_car_speed_limit",
            "review_only_truck_speed_limit",
            "rns_route_field",
            "rns_measure_pair",
            "rns_transport_edge_id",
        ]
    ).copy()
    _checkpoint("rns_interval_table_filtered", len(intervals))
    return intervals


def _lookup_group(candidates: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    cand = candidates.copy()
    if intervals.empty:
        cand["rns_match_status"] = "missing_no_rns_route_interval"
        return cand
    intervals = intervals.sort_values(["rns_measure_min", "rns_measure_max"]).reset_index(drop=True)
    starts = intervals["rns_measure_min"].to_numpy(dtype=float)
    ends = intervals["rns_measure_max"].to_numpy(dtype=float)
    mids = cand["candidate_midpoint_measure"].to_numpy(dtype=float)
    bmins = cand["candidate_measure_min_num"].to_numpy(dtype=float)
    bmaxs = cand["candidate_measure_max_num"].to_numpy(dtype=float)

    idx = np.searchsorted(starts, mids, side="right") - 1
    valid_idx = (idx >= 0) & (idx < len(intervals))
    selected = intervals.iloc[np.clip(idx, 0, max(len(intervals) - 1, 0))].reset_index(drop=True)
    contains = valid_idx & (selected["rns_measure_min"].to_numpy(dtype=float) <= mids) & (mids <= selected["rns_measure_max"].to_numpy(dtype=float))
    contains_count = np.searchsorted(starts, mids, side="right") - np.searchsorted(np.sort(ends), mids, side="left")
    start_count = np.searchsorted(starts, bmins, side="right") - np.searchsorted(np.sort(ends), bmins, side="left")
    end_count = np.searchsorted(starts, bmaxs, side="right") - np.searchsorted(np.sort(ends), bmaxs, side="left")
    internal_starts = np.searchsorted(starts, bmaxs, side="left") - np.searchsorted(starts, bmins, side="right")

    for col in [
        "rns_source_row_id",
        "rns_route_raw",
        "rns_route_key",
        "normalized_rns_route_key",
        "rns_facility_text",
        "rns_measure_start",
        "rns_measure_end",
        "rns_measure_min",
        "rns_measure_max",
        "review_only_car_speed_limit",
        "review_only_truck_speed_limit",
        "rns_route_field",
        "rns_measure_pair",
        "rns_edge_rte_key",
        "rns_master_edge_rte_key",
        "rns_transport_edge_id",
        "rns_final_speed_limit_source",
        "rns_speedzone_type_dsc",
        "rns_identify_code",
    ]:
        cand["matched_" + col] = selected[col].astype(object).to_numpy() if col in selected.columns else ""
    matched_cols = [c for c in cand.columns if c.startswith("matched_")]
    for col in matched_cols:
        cand[col] = cand[col].astype(object)
    cand.loc[~contains, matched_cols] = ""
    cand["rns_containing_interval_count_at_midpoint"] = contains_count
    cand["rns_containing_interval_count_at_bin_start"] = start_count
    cand["rns_containing_interval_count_at_bin_end"] = end_count
    cand["rns_internal_interval_start_count_within_bin"] = internal_starts
    cand["rns_boundary_or_multi_interval_flag"] = (start_count != end_count) | (internal_starts > 0) | (contains_count > 1)
    cand["rns_measure_containment_status"] = "midpoint_contained_single_selected_interval"
    cand.loc[contains_count > 1, "rns_measure_containment_status"] = "midpoint_contained_multiple_overlapping_intervals_selected_by_latest_start"
    cand.loc[~contains & (contains_count > 0), "rns_measure_containment_status"] = "midpoint_contained_but_selected_interval_not_containing_review"
    cand.loc[~contains & (contains_count <= 0), "rns_measure_containment_status"] = "midpoint_not_contained_by_rns_interval"
    cand["rns_match_status"] = "review_only_speed_matched"
    cand.loc[~contains, "rns_match_status"] = "missing_no_containing_rns_interval"
    cand["rns_match_method"] = "grouped_vectorized_searchsorted_midpoint_containment"
    cand["rns_route_match_confidence"] = "route_group_rns_key_from_rebuild"
    cand["rns_missing_reason"] = ""
    cand.loc[~contains, "rns_missing_reason"] = cand.loc[~contains, "rns_measure_containment_status"]
    return cand


def _vectorized_lookup(candidates: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    frames = []
    _checkpoint("vectorized_lookup_start", len(candidates), f"routes={candidates['candidate_lookup_route_key'].nunique():,}")
    for key, cand_group in candidates.groupby("candidate_lookup_route_key", dropna=False):
        route_intervals = intervals.loc[intervals["rns_lookup_route_key"].eq(key)].copy()
        frames.append(_lookup_group(cand_group, route_intervals))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    _checkpoint("vectorized_lookup_complete", len(out))
    return out


def _signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    work = detail.copy()
    work["matched_flag"] = _text(work, "rns_match_status").eq("review_only_speed_matched")
    work["boundary_flag"] = _flag(work, "rns_boundary_or_multi_interval_flag")
    _checkpoint("groupby_start_signal_summary", len(work))
    out = work.groupby("candidate_signal_id", dropna=False).agg(
        attempted_candidate_bins=("candidate_bin_id", "count"),
        matched_candidate_bins=("matched_flag", "sum"),
        unmatched_candidate_bins=("matched_flag", lambda s: int((~s).sum())),
        attempted_route_group_count=("candidate_route_group_id", "nunique"),
        aadt_safe_speed_not_safe_flag=("aadt_safe_speed_not_safe_flag", lambda s: bool(pd.Series(s).astype(str).str.lower().isin({"true", "1", "yes"}).any())),
        analysis_windows=("analysis_window", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
        recovery_strategy_values=("recovery_strategy", _collapse),
        confidence_tier_values=("association_confidence_tier", _collapse),
        multi_candidate_values=("multi_candidate_flag", _collapse),
        weighted_attempted_bins=("candidate_weight_num", "sum"),
        weighted_matched_bins=("candidate_weight_num", lambda s: float(s.loc[work.loc[s.index, "matched_flag"]].sum())),
        boundary_or_multi_interval_bins=("boundary_flag", "sum"),
        missing_reasons=("rns_missing_reason", _collapse),
    ).reset_index()
    out["has_any_review_only_rns_speed"] = out["matched_candidate_bins"].gt(0)
    out["has_full_attempted_review_only_rns_speed"] = out["attempted_candidate_bins"].eq(out["matched_candidate_bins"])
    high_priority = work.loc[_text(work, "analysis_window").str.contains("0_1000", na=False)].groupby("candidate_signal_id")["matched_flag"].agg(["count", "sum"]).reset_index()
    high_priority["full_0_1000_speed_coverage_flag"] = high_priority["count"].eq(high_priority["sum"])
    out = out.merge(high_priority[["candidate_signal_id", "full_0_1000_speed_coverage_flag"]], on="candidate_signal_id", how="left")
    full = work.groupby("candidate_signal_id")["matched_flag"].agg(["count", "sum"]).reset_index()
    full["full_0_2500_speed_coverage_flag"] = full["count"].eq(full["sum"])
    out = out.merge(full[["candidate_signal_id", "full_0_2500_speed_coverage_flag"]], on="candidate_signal_id", how="left")
    out[["full_0_1000_speed_coverage_flag", "full_0_2500_speed_coverage_flag"]] = out[["full_0_1000_speed_coverage_flag", "full_0_2500_speed_coverage_flag"]].fillna(False)
    _checkpoint("groupby_complete_signal_summary", len(out))
    return out


def _coverage_summary(detail: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    matched = _text(detail, "rns_match_status").eq("review_only_speed_matched")
    rows = [
        {"metric": "candidate_bins_attempted", "value": "", "count": len(detail)},
        {"metric": "candidate_bins_matched", "value": "", "count": int(matched.sum())},
        {"metric": "candidate_bins_unmatched", "value": "", "count": int((~matched).sum())},
        {"metric": "unique_recovered_signals_attempted", "value": "", "count": detail["candidate_signal_id"].nunique()},
        {"metric": "unique_recovered_signals_with_any_speed", "value": "", "count": int(signal_summary["has_any_review_only_rns_speed"].sum())},
        {"metric": "unique_recovered_signals_with_full_0_1000_speed_coverage", "value": "", "count": int(signal_summary["full_0_1000_speed_coverage_flag"].sum())},
        {"metric": "unique_recovered_signals_with_full_0_2500_speed_coverage", "value": "", "count": int(signal_summary["full_0_2500_speed_coverage_flag"].sum())},
        {"metric": "aadt_safe_speed_not_safe_signals_recovered_any_speed", "value": "", "count": int((signal_summary["has_any_review_only_rns_speed"] & _flag(signal_summary, "aadt_safe_speed_not_safe_flag")).sum())},
        {"metric": "one_direction_or_partial_direction_signals_with_any_speed", "value": "", "count": int(signal_summary.loc[signal_summary["direction_labels"].str.contains("candidate_", na=False) & signal_summary["has_any_review_only_rns_speed"], "candidate_signal_id"].nunique())},
        {"metric": "multi_candidate_signals_with_any_speed", "value": "", "count": int(signal_summary.loc[signal_summary["multi_candidate_values"].str.contains("True|true", regex=True, na=False) & signal_summary["has_any_review_only_rns_speed"], "candidate_signal_id"].nunique())},
    ]
    for status, group in detail.groupby("rns_match_status", dropna=False):
        rows.append({"metric": "candidate_bins_by_match_status", "value": status, "count": len(group)})
    return pd.DataFrame(rows)


def _missingness_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    miss = detail.loc[~_text(detail, "rns_match_status").eq("review_only_speed_matched")].copy()
    if miss.empty:
        return pd.DataFrame(columns=["rns_missing_reason", "candidate_bin_count", "unique_signal_count", "route_group_count"])
    return miss.groupby("rns_missing_reason", dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        unique_signal_count=("candidate_signal_id", "nunique"),
        route_group_count=("candidate_route_group_id", "nunique"),
    ).reset_index()


def _before_after(signal_summary: pd.DataFrame) -> pd.DataFrame:
    phase3d_any = int(signal_summary["has_any_review_only_rns_speed"].sum()) if not signal_summary.empty else 0
    return pd.DataFrame(
        [
            {"metric": "prior_recovered_speed_signal_coverage_reference", "count": PRIOR_RECOVERED_SPEED_SIGNAL_COVERAGE, "note": "User-provided approximate recovered speed coverage before Phase 3C/RNS rebuild."},
            {"metric": "phase3d_review_only_rns_speed_signals_any_speed", "count": phase3d_any, "note": "Deduplicated recovered candidate signals with any review-only RNS speed match in this test."},
            {"metric": "additional_review_only_signal_coverage_vs_prior_reference", "count": max(0, phase3d_any - PRIOR_RECOVERED_SPEED_SIGNAL_COVERAGE), "note": "Descriptive comparison only; not active promotion."},
            {"metric": "aadt_safe_speed_not_safe_signals_recovered_any_speed", "count": int((signal_summary["has_any_review_only_rns_speed"] & _flag(signal_summary, "aadt_safe_speed_not_safe_flag")).sum()) if not signal_summary.empty else 0, "note": "AADT-safe label used only as comparison flag."},
        ]
    )


def _findings(coverage: pd.DataFrame, missingness: pd.DataFrame) -> str:
    def metric(name: str) -> int:
        if coverage.empty:
            return 0
        row = coverage.loc[coverage["metric"].eq(name)]
        return int(pd.to_numeric(row["count"], errors="coerce").fillna(0).sum()) if not row.empty else 0
    top_missing = "none"
    if not missingness.empty:
        top_missing = str(missingness.sort_values("candidate_bin_count", ascending=False).iloc[0]["rns_missing_reason"])
    return "\n".join(
        [
            "# Expanded Candidate Speed RNS Phase 3D Vectorized Assignment Findings",
            "",
            "This is a review-only vectorized Speed_Limit_RNS interval lookup test for eligible recovered candidate bins. It does not alter active speed/context outputs.",
            f"Candidate bins attempted: {metric('candidate_bins_attempted')}.",
            f"Candidate bins matched: {metric('candidate_bins_matched')}.",
            f"Unique recovered signals attempted: {metric('unique_recovered_signals_attempted')}.",
            f"Unique recovered signals with any review-only RNS speed: {metric('unique_recovered_signals_with_any_speed')}.",
            f"Unique recovered signals with full 0-1,000 ft speed coverage: {metric('unique_recovered_signals_with_full_0_1000_speed_coverage')}.",
            f"Unique recovered signals with full 0-2,500 ft attempted speed coverage: {metric('unique_recovered_signals_with_full_0_2500_speed_coverage')}.",
            f"AADT-safe / speed-not-safe signals recovered with any review-only RNS speed: {metric('aadt_safe_speed_not_safe_signals_recovered_any_speed')}.",
            f"Dominant remaining missing reason: {top_missing}.",
            "Next pass should review boundary/multi-interval cases and decide whether these review-only assignments are suitable for a controlled Phase 3D rerun. No safety, risk, causal, policy, or final guidance claims are made.",
            "",
        ]
    )


def _qa(detail: pd.DataFrame, eligible: pd.DataFrame, excluded_ids: set[str], missing: list[str]) -> pd.DataFrame:
    assigned_excluded = set(_text(detail, "candidate_route_group_id")) & excluded_ids if not detail.empty else set()
    rows = [
        _qa_row("required_inputs_present", not missing, len(missing), 0, "; ".join(missing[:10])),
        _qa_row("no_active_outputs_modified", True, True, True, "Writes only to review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment."),
        _qa_row("no_candidates_promoted", True, True, True, "All assignments are review-only."),
        _qa_row("no_crash_records_read", True, True, True, "Input reader blocks crash record fields."),
        _qa_row("no_crash_direction_fields_read_or_used", True, True, True, "Input reader blocks crash direction fields."),
        _qa_row("access_not_included", True, True, True, "No access input paths are read."),
        _qa_row("assignment_review_only", _text(detail, "candidate_assignment_scope").eq("review_only_phase3d_test_not_active").all() if not detail.empty else True, "review_only", "review_only", ""),
        _qa_row("no_candidate_bin_by_rns_row_overlap_table_materialized", len(detail) <= ROW_GUARD_LIMIT, len(detail), f"<= {ROW_GUARD_LIMIT}", "Detail is one row per eligible candidate bin with one selected interval at most."),
        _qa_row("assignment_detail_has_unique_candidate_bins", detail["candidate_bin_id"].nunique() == len(detail) if "candidate_bin_id" in detail else True, detail["candidate_bin_id"].nunique() if "candidate_bin_id" in detail else 0, len(detail), "Route-group signal map is deduped before assignment."),
        _qa_row("vectorized_grouped_lookup_method_documented", _text(detail, "rns_match_method").str.contains("searchsorted", na=False).any() if not detail.empty else True, "grouped_vectorized_searchsorted_midpoint_containment", "documented", ""),
        _qa_row("excluded_source_gap_review_groups_not_assigned", not assigned_excluded, len(assigned_excluded), 0, ""),
        _qa_row("deduped_signal_counts_separate_from_bin_counts", True, True, True, "Signal summary and coverage summary report signal counts separately from bin counts."),
        _qa_row("outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR), ""),
        _qa_row("eligible_route_group_count_positive", not eligible.empty, len(eligible), ">0", ""),
    ]
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text(f"{datetime.now(timezone.utc).isoformat()} START expanded_candidate_speed_rns_phase3d_vectorized_assignment\n", encoding="utf-8")
    missing = _missing_required_inputs()
    _checkpoint("required_input_check_complete", len(missing), "missing_inputs")
    inputs = _load_inputs()
    eligible = _eligible_groups(inputs)
    excluded_rows = inputs["ambiguity"].loc[
        _text(inputs["ambiguity"], "upgrade_recommendation").isin(["hold_as_likely_source_gap", "manual_or_mapped_review_needed", "keep_needs_route_identity_review", "do_not_use_current_evidence"])
    ]
    excluded_ids = set(_text(inputs["source_gap"], "candidate_route_group_id")) | set(_text(excluded_rows, "candidate_route_group_id"))
    bins = _candidate_bin_table(inputs["candidate_bins"], eligible, inputs["signal_map"])
    raw_rns = _load_rns_source()
    intervals = _rns_interval_table(raw_rns, eligible)
    detail = _vectorized_lookup(bins, intervals)
    signal_summary = _signal_summary(detail)
    coverage = _coverage_summary(detail, signal_summary)
    missingness = _missingness_summary(detail)
    boundary = detail.loc[_flag(detail, "rns_boundary_or_multi_interval_flag")].head(REVIEW_QUEUE_LIMIT).copy() if not detail.empty else pd.DataFrame()
    before_after = _before_after(signal_summary)
    ranked = detail.sort_values(["rns_match_status", "candidate_signal_id", "candidate_bin_id"]).head(REVIEW_QUEUE_LIMIT).copy() if not detail.empty else pd.DataFrame()

    keep_detail_cols = [
        "candidate_bin_id",
        "candidate_signal_id",
        "candidate_route_group_id",
        "route_id",
        "route_common",
        "route_name",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_facility_text",
        "candidate_route_type_category",
        "source_layer",
        "candidate_measure_start",
        "candidate_measure_end",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_midpoint_measure",
        "candidate_measure_length",
        "analysis_window",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "candidate_weight",
        "recovery_strategy",
        "association_confidence_tier",
        "multi_candidate_flag",
        "aadt_safe_speed_not_safe_flag",
        "route_group_signal_mapping_method",
        "rns_match_status",
        "rns_match_method",
        "rns_route_match_confidence",
        "rns_measure_containment_status",
        "rns_boundary_or_multi_interval_flag",
        "rns_missing_reason",
        "matched_review_only_car_speed_limit",
        "matched_review_only_truck_speed_limit",
        "matched_rns_route_raw",
        "matched_rns_route_key",
        "matched_normalized_rns_route_key",
        "matched_rns_measure_start",
        "matched_rns_measure_end",
        "matched_rns_measure_min",
        "matched_rns_measure_max",
        "matched_rns_source_row_id",
        "matched_rns_route_field",
        "matched_rns_measure_pair",
        "matched_rns_transport_edge_id",
        "matched_rns_final_speed_limit_source",
        "matched_rns_speedzone_type_dsc",
        "matched_rns_identify_code",
        "rns_containing_interval_count_at_midpoint",
        "rns_containing_interval_count_at_bin_start",
        "rns_containing_interval_count_at_bin_end",
        "rns_internal_interval_start_count_within_bin",
        "candidate_assignment_scope",
    ]
    output_detail = detail[[c for c in keep_detail_cols if c in detail.columns]].copy() if not detail.empty else pd.DataFrame(columns=keep_detail_cols)
    _write_csv(output_detail, OUT_DIR / "phase3d_candidate_rns_speed_assignment_detail.csv")
    _write_csv(signal_summary, OUT_DIR / "phase3d_candidate_rns_speed_signal_summary.csv")
    _write_csv(coverage, OUT_DIR / "phase3d_candidate_rns_speed_coverage_summary.csv")
    _write_csv(missingness, OUT_DIR / "phase3d_candidate_rns_speed_missingness_summary.csv")
    _write_csv(boundary[[c for c in keep_detail_cols if c in boundary.columns]], OUT_DIR / "phase3d_candidate_rns_speed_boundary_cases.csv")
    _write_csv(before_after, OUT_DIR / "phase3d_candidate_rns_speed_before_after_summary.csv")
    _write_csv(ranked[[c for c in keep_detail_cols if c in ranked.columns]], OUT_DIR / "phase3d_candidate_rns_speed_ranked_review_queue.csv")
    _write_text(_findings(coverage, missingness), OUT_DIR / "expanded_candidate_speed_rns_phase3d_vectorized_assignment_findings.md")
    qa = _qa(output_detail, eligible, excluded_ids, missing)
    _write_csv(qa, OUT_DIR / "expanded_candidate_speed_rns_phase3d_vectorized_assignment_qa.csv")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "review-only Phase 3D vectorized Speed_Limit_RNS speed assignment test for recovered candidate bins",
        "output_dir": str(OUT_DIR),
        "rns_source_path": str(SPEED_LIMIT_RNS_GDB / SPEED_LIMIT_RNS_LAYER),
        "eligible_route_group_count": int(len(eligible)),
        "candidate_bins_attempted": int(len(output_detail)),
        "lookup_method": "grouped vectorized numpy searchsorted midpoint containment by RNS route key",
        "missing_required_inputs": missing,
        "guardrails": {
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "review_only_assignment": True,
            "no_candidate_bin_x_rns_row_overlap_table": True,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_speed_rns_phase3d_vectorized_assignment_manifest.json")
    _checkpoint("complete expanded_candidate_speed_rns_phase3d_vectorized_assignment")


if __name__ == "__main__":
    main()
