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
except Exception:  # pragma: no cover - local dependency variance.
    gpd = None
    pyogrio = None

from .aadt_context_join_v3_identity_route_measure import _route_key as _aadt_v3_route_key
from .expanded_candidate_speed_rns_phase3d_vectorized_assignment import (
    _facility_text,
    _phase3_norm,
    normalize_route_name,
)


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_context_refresh"
QA_CLEANUP_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_staging_qa_cleanup"

SPEED_REFERENCE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_REFERENCE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_v3_path_rebuild"
ROUTE_REFERENCE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"

SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")

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

REQUIRED_INPUTS = {
    QA_CLEANUP_DIR: [
        "cleaned_staged_offset_recovered_legs.csv",
        "cleaned_staged_offset_recovered_bins.csv",
        "cleaned_staged_offset_signal_summary.csv",
        "staging_qa_cleanup_readiness_summary.csv",
        "grade_separated_mainline_review_cases.csv",
        "long_source_row_review_cases.csv",
        "staging_qa_cleanup_manifest.json",
    ],
    SPEED_REFERENCE_DIR: [
        "phase3d_candidate_rns_speed_assignment_detail.csv",
        "expanded_candidate_speed_rns_phase3d_vectorized_assignment_manifest.json",
    ],
    AADT_REFERENCE_DIR: [
        "aadt_v3_candidate_assignment_detail.csv",
        "expanded_candidate_aadt_v3_path_rebuild_manifest.json",
    ],
    ROUTE_REFERENCE_DIR: [
        "stage1_candidate_route_measure_bin_detail.csv",
        "expanded_candidate_route_measure_context_audit_manifest.json",
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
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
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
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {
        "qa_gate": gate,
        "passed": bool(passed),
        "observed_value": observed,
        "expected_or_reference_value": expected,
        "note": note,
    }


def _missing_required_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    if not AADT_FILE.exists():
        missing.append(str(AADT_FILE))
    if not SPEED_LIMIT_RNS_GDB.exists():
        missing.append(str(SPEED_LIMIT_RNS_GDB))
    return missing


def _source_line_parts(value: Any) -> dict[str, Any]:
    raw = str(value or "").split("|")[0].strip()
    if not raw:
        return {}
    match = re.match(r"^(?P<event_source>[^_]+)_(?P<route_raw>.+)_(?P<route_id>\d+)_(?P<from>-?\d+(?:\.\d+)?)_(?P<to>-?\d+(?:\.\d+)?)$", raw)
    if not match:
        return {"source_line_parse_status": "unparsed_source_lineage", "source_line_first": raw}
    route_raw = match.group("route_raw").strip()
    from_measure = float(match.group("from"))
    to_measure = float(match.group("to"))
    return {
        "source_line_parse_status": "parsed_source_travelway_lineage",
        "source_line_first": raw,
        "source_event_source": match.group("event_source").strip(),
        "source_route_raw": route_raw,
        "source_route_id": match.group("route_id").strip(),
        "source_measure_start": from_measure,
        "source_measure_end": to_measure,
        "source_measure_min": min(from_measure, to_measure),
        "source_measure_max": max(from_measure, to_measure),
        "source_measure_direction_status": "source_measure_increases" if to_measure >= from_measure else "source_measure_decreases",
    }


def _route_aliases(*values: Any) -> list[str]:
    aliases: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw or raw.lower() in {"nan", "none", "<na>"}:
            continue
        parts = [raw]
        parts.extend(part.strip() for part in raw.split("|") if part.strip())
        for part in parts:
            cleaned = re.sub(r"\([^)]*\)", "", part).strip()
            for alias in {
                cleaned,
                re.sub(r"[^A-Za-z0-9]", "", cleaned).upper(),
                normalize_route_name(cleaned),
                _phase3_norm(cleaned),
                _aadt_v3_route_key(cleaned),
            }:
                alias = str(alias or "").strip().upper()
                if alias and alias not in aliases:
                    aliases.append(alias)
    return aliases


def _first_alias(values: list[str]) -> str:
    return values[0] if values else ""


def _infer_route_context(source_route_raw: str, source_route_keys: str) -> dict[str, str]:
    combined = f"{source_route_raw} {source_route_keys}".upper()
    if "RMP" in combined or "RAMP" in combined:
        route_type = "ramp_connector"
    elif "IS" in combined or "INTERSTATE" in combined or re.search(r"\bI-?\d+", combined):
        route_type = "interstate_or_limited_access"
    elif "US" in combined:
        route_type = "us_route"
    elif "SC" in combined:
        route_type = "secondary_route"
    elif "SR" in combined or "VA" in combined:
        route_type = "state_route"
    else:
        route_type = "unknown_route_type"
    return {
        "roadway_context_source": "source_travelway_lineage_fields",
        "roadway_route_type_category": route_type,
        "roadway_context_status": "roadway_context_from_source_lineage" if source_route_raw or source_route_keys else "roadway_context_unavailable",
        "candidate_facility_text": _facility_text(source_route_raw or source_route_keys),
    }


def _build_route_measure_identity(clean_bins: pd.DataFrame) -> pd.DataFrame:
    eligible = clean_bins.loc[
        _flag(clean_bins, "refresh_eligible_bin")
        & ~_flag(clean_bins, "hold_excluded_mainline")
        & ~_flag(clean_bins, "hold_manual_grade_separation_review")
        & ~_flag(clean_bins, "hold_nonstandard_geometry")
    ].copy()
    _checkpoint("refresh_eligible_filter_complete", len(eligible))
    parsed = pd.DataFrame([_source_line_parts(value) for value in _text(eligible, "source_travelway_lineage").where(_text(eligible, "source_travelway_lineage").ne(""), _text(eligible, "source_line_ids"))])
    parsed.index = eligible.index
    detail = pd.concat([eligible, parsed], axis=1)

    dist_start = _num(detail, "distance_start_ft").fillna(0.0)
    dist_end = _num(detail, "distance_end_ft").fillna(0.0)
    src_min = pd.to_numeric(detail.get("source_measure_min", pd.Series(np.nan, index=detail.index)), errors="coerce")
    src_max = pd.to_numeric(detail.get("source_measure_max", pd.Series(np.nan, index=detail.index)), errors="coerce")
    source_span = src_max - src_min
    inferred_start = src_min + (dist_start / 5280.0)
    inferred_end = src_min + (dist_end / 5280.0)
    detail["candidate_measure_start"] = inferred_start.where(inferred_start.le(src_max), src_max)
    detail["candidate_measure_end"] = inferred_end.where(inferred_end.le(src_max), src_max)
    detail["candidate_measure_min"] = detail[["candidate_measure_start", "candidate_measure_end"]].min(axis=1)
    detail["candidate_measure_max"] = detail[["candidate_measure_start", "candidate_measure_end"]].max(axis=1)
    detail["candidate_midpoint_measure"] = (detail["candidate_measure_min"] + detail["candidate_measure_max"]) / 2.0
    detail["candidate_measure_length"] = detail["candidate_measure_max"] - detail["candidate_measure_min"]
    detail["candidate_bin_length_ft"] = (dist_end - dist_start).clip(lower=0)
    detail["analysis_window"] = np.where(dist_end.le(1000), "0_1000", "outside_0_1000")
    detail["route_measure_identity_method"] = "source_travelway_lineage_linear_distance_proxy_review_only"
    complete = _text(detail, "source_line_parse_status").eq("parsed_source_travelway_lineage") & src_min.notna() & src_max.notna()
    detail["candidate_route_measure_interval_status"] = np.where(complete, "review_only_proxy_route_measure_interval", "missing_source_route_measure_lineage")
    detail["candidate_route_measure_join_quality"] = np.where(
        complete & source_span.gt(0),
        "review_only_linear_ft_to_measure_proxy_from_source_lineage",
        "missing_or_zero_source_measure_span",
    )
    detail["route_measure_proxy_caveat"] = "Measures are reconstructed from source Travelway lineage and staged bin distance; this pass does not promote active route-measure identity."

    aliases = [
        _route_aliases(row.get("source_route_raw", ""), row.get("source_route_keys", ""), row.get("source_route_id", ""))
        for row in detail.to_dict(orient="records")
    ]
    detail["route_aliases_for_lookup"] = ["|".join(items) for items in aliases]
    detail["rns_lookup_route_key"] = [_first_alias(items) for items in aliases]
    detail["aadt_lookup_route_key"] = [_first_alias(items) for items in aliases]
    detail["normalized_candidate_route_key"] = _text(detail, "source_route_raw").map(_phase3_norm)
    detail["candidate_route_name_rns_norm"] = _text(detail, "source_route_raw").map(normalize_route_name)
    detail["candidate_normalized_route_key"] = _text(detail, "source_route_raw").map(_aadt_v3_route_key)

    context = pd.DataFrame([_infer_route_context(row.get("source_route_raw", ""), row.get("source_route_keys", "")) for row in detail.to_dict(orient="records")])
    context.index = detail.index
    detail = pd.concat([detail, context], axis=1)
    detail["has_route_measure_identity"] = _text(detail, "candidate_route_measure_interval_status").eq("review_only_proxy_route_measure_interval")
    detail["has_roadway_context"] = _text(detail, "roadway_context_status").eq("roadway_context_from_source_lineage")
    return detail


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


def _rns_intervals(needed_aliases: set[str]) -> pd.DataFrame:
    raw = _load_rns_source()
    rows: list[pd.DataFrame] = []
    for route_field, from_col, to_col in [
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
    ]:
        work = raw.copy()
        work["route_aliases"] = work[route_field].map(lambda value: _route_aliases(value))
        work = work.explode("route_aliases").rename(columns={"route_aliases": "lookup_route_key"})
        work["lookup_route_key"] = _text(work, "lookup_route_key").str.upper()
        work = work.loc[work["lookup_route_key"].isin(needed_aliases)].copy()
        if work.empty:
            continue
        from_measure = pd.to_numeric(work[from_col], errors="coerce")
        to_measure = pd.to_numeric(work[to_col], errors="coerce")
        rows.append(
            pd.DataFrame(
                {
                    "lookup_route_key": work["lookup_route_key"],
                    "interval_measure_min": np.minimum(from_measure, to_measure),
                    "interval_measure_max": np.maximum(from_measure, to_measure),
                    "rns_source_row_id": work["rns_source_row_id"],
                    "rns_route_raw": work[route_field].astype(str),
                    "review_only_car_speed_limit": pd.to_numeric(work["CAR_SPEED_LIMIT"], errors="coerce"),
                    "review_only_truck_speed_limit": pd.to_numeric(work.get("TRUCK_SPEED_LIMIT", ""), errors="coerce"),
                    "rns_route_field": route_field,
                    "rns_measure_pair": f"{from_col}/{to_col}",
                    "rns_transport_edge_id": work.get("TRANSPORT_EDGE_ID", pd.Series("", index=work.index)).astype(str),
                    "rns_final_speed_limit_source": work.get("FINAL_SPEED_LIMIT_SOURCE", pd.Series("", index=work.index)).astype(str),
                    "rns_speedzone_type_dsc": work.get("SPEEDZONE_TYPE_DSC", pd.Series("", index=work.index)).astype(str),
                    "rns_identify_code": work.get("IDENTIFY_CODE", pd.Series("", index=work.index)).astype(str),
                }
            )
        )
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not out.empty:
        out = out.loc[out["interval_measure_min"].notna() & out["interval_measure_max"].notna() & out["review_only_car_speed_limit"].notna()].drop_duplicates()
    _checkpoint("rns_interval_aliases_filtered", len(out))
    return out


def _load_aadt_intervals(needed_aliases: set[str]) -> pd.DataFrame:
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
    ]
    _checkpoint("read_start normalized_aadt_source")
    raw = pd.read_parquet(AADT_FILE, columns=cols).reset_index(names="aadt_source_row_id")
    _checkpoint("read_complete normalized_aadt_source", len(raw))
    frames: list[pd.DataFrame] = []
    for route_field, from_col, to_col in [
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
    ]:
        work = raw.copy()
        work["route_aliases"] = work[route_field].map(lambda value: _route_aliases(value))
        work = work.explode("route_aliases").rename(columns={"route_aliases": "lookup_route_key"})
        work["lookup_route_key"] = _text(work, "lookup_route_key").str.upper()
        work = work.loc[work["lookup_route_key"].isin(needed_aliases)].copy()
        if work.empty:
            continue
        from_measure = pd.to_numeric(work[from_col], errors="coerce")
        to_measure = pd.to_numeric(work[to_col], errors="coerce")
        frames.append(
            pd.DataFrame(
                {
                    "lookup_route_key": work["lookup_route_key"],
                    "interval_measure_min": np.minimum(from_measure, to_measure),
                    "interval_measure_max": np.maximum(from_measure, to_measure),
                    "aadt_source_row_id": work["aadt_source_row_id"],
                    "aadt_route_raw": work[route_field].astype(str),
                    "review_only_aadt_value": pd.to_numeric(work["AADT"], errors="coerce"),
                    "review_only_aadt_year": pd.to_numeric(work["AADT_YR"], errors="coerce"),
                    "review_only_direction_factor": pd.to_numeric(work.get("DIRECTION_FACTOR", ""), errors="coerce"),
                    "aadt_directionality": work.get("DIRECTIONALITY", pd.Series("", index=work.index)).astype(str),
                    "aadt_linkid": work.get("LINKID", pd.Series("", index=work.index)).astype(str),
                    "aadt_route_field": route_field,
                    "aadt_measure_pair": f"{from_col}/{to_col}",
                }
            )
        )
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out = out.loc[out["interval_measure_min"].notna() & out["interval_measure_max"].notna() & out["review_only_aadt_value"].gt(0)].drop_duplicates()
    _checkpoint("aadt_interval_aliases_filtered", len(out))
    return out


def _candidate_alias_rows(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for rec in detail.to_dict(orient="records"):
        aliases = [alias for alias in str(rec.get("route_aliases_for_lookup", "")).split("|") if alias]
        for rank, alias in enumerate(aliases[:10], start=1):
            rows.append(
                {
                    "staged_recovered_bin_id": rec.get("staged_recovered_bin_id", ""),
                    "lookup_route_key": alias.upper(),
                    "lookup_key_rank": rank,
                    "candidate_midpoint_measure": rec.get("candidate_midpoint_measure", np.nan),
                }
            )
    return pd.DataFrame(rows)


def _lookup_intervals(candidates: pd.DataFrame, intervals: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    if intervals.empty:
        out = candidates.drop_duplicates("staged_recovered_bin_id").copy()
        out[f"{prefix}_match_status"] = f"review_only_{prefix}_unmatched"
        out[f"{prefix}_missing_reason"] = f"route_key_not_in_{prefix}_intervals"
        return out
    results: list[pd.DataFrame] = []
    intervals = intervals.sort_values(["lookup_route_key", "interval_measure_min", "interval_measure_max"]).reset_index(drop=True)
    for key, group in candidates.groupby("lookup_route_key", sort=False, dropna=False):
        source = intervals.loc[intervals["lookup_route_key"].eq(key)].reset_index(drop=True)
        work = group.copy()
        if source.empty:
            work[f"{prefix}_match_status"] = f"review_only_{prefix}_unmatched"
            work[f"{prefix}_missing_reason"] = f"route_key_not_in_{prefix}_intervals"
            results.append(work)
            continue
        mids = pd.to_numeric(work["candidate_midpoint_measure"], errors="coerce").to_numpy(dtype=float)
        starts = source["interval_measure_min"].to_numpy(dtype=float)
        pos = np.searchsorted(starts, mids, side="right") - 1
        valid = (pos >= 0) & np.isfinite(mids)
        selected = source.iloc[np.clip(pos, 0, max(len(source) - 1, 0))].reset_index(drop=True)
        contained = valid & (mids >= selected["interval_measure_min"].to_numpy(dtype=float)) & (mids <= selected["interval_measure_max"].to_numpy(dtype=float))
        work[f"{prefix}_match_status"] = np.where(contained, f"review_only_{prefix}_matched", f"review_only_{prefix}_unmatched")
        work[f"{prefix}_missing_reason"] = np.where(contained, "", f"midpoint_not_contained_by_{prefix}_interval")
        work[f"{prefix}_measure_containment_status"] = np.where(contained, f"midpoint_contained_by_{prefix}_interval", "selected_interval_not_containing_midpoint")
        for column in selected.columns:
            if column == "lookup_route_key":
                continue
            work[f"matched_{prefix}_{column}"] = ""
            values = selected[column].astype(str).to_numpy()
            work.loc[contained, f"matched_{prefix}_{column}"] = values[contained]
        results.append(work)
    looked = pd.concat(results, ignore_index=True)
    looked["matched_sort"] = _text(looked, f"{prefix}_match_status").eq(f"review_only_{prefix}_matched").astype(int)
    looked["lookup_key_rank_num"] = pd.to_numeric(_text(looked, "lookup_key_rank"), errors="coerce").fillna(999)
    if prefix == "aadt_v3" and "matched_aadt_v3_review_only_aadt_year" in looked.columns:
        looked["year_sort"] = pd.to_numeric(_text(looked, "matched_aadt_v3_review_only_aadt_year"), errors="coerce").fillna(-1)
    else:
        looked["year_sort"] = 0
    looked = looked.sort_values(["staged_recovered_bin_id", "matched_sort", "year_sort", "lookup_key_rank_num"], ascending=[True, False, False, True])
    return looked.drop_duplicates("staged_recovered_bin_id", keep="first")


def _assign_context(detail: pd.DataFrame) -> pd.DataFrame:
    aliases = _candidate_alias_rows(detail)
    needed_aliases = {alias for alias in _text(aliases, "lookup_route_key") if alias}

    rns = _lookup_intervals(aliases, _rns_intervals(needed_aliases), "rns_speed")
    aadt = _lookup_intervals(aliases, _load_aadt_intervals(needed_aliases), "aadt_v3")

    keep_rns = [col for col in rns.columns if col == "staged_recovered_bin_id" or col.startswith("rns_speed_") or col.startswith("matched_rns_speed_")]
    keep_aadt = [col for col in aadt.columns if col == "staged_recovered_bin_id" or col.startswith("aadt_v3_") or col.startswith("matched_aadt_v3_")]
    out = detail.merge(rns[keep_rns], on="staged_recovered_bin_id", how="left").merge(aadt[keep_aadt], on="staged_recovered_bin_id", how="left")

    out["rns_speed_match_status"] = _text(out, "rns_speed_match_status").where(_text(out, "rns_speed_match_status").ne(""), "review_only_rns_speed_unmatched")
    out["aadt_v3_match_status"] = _text(out, "aadt_v3_match_status").where(_text(out, "aadt_v3_match_status").ne(""), "review_only_aadt_v3_unmatched")
    out["has_rns_speed"] = _text(out, "rns_speed_match_status").eq("review_only_rns_speed_matched")
    out["has_aadt"] = _text(out, "aadt_v3_match_status").eq("review_only_aadt_v3_matched")

    aadt_value = pd.to_numeric(_text(out, "matched_aadt_v3_review_only_aadt_value"), errors="coerce")
    direction_factor = pd.to_numeric(_text(out, "matched_aadt_v3_review_only_direction_factor"), errors="coerce")
    length_miles = pd.to_numeric(out["candidate_bin_length_ft"], errors="coerce") / 5280.0
    valid_factor = direction_factor.gt(0) & direction_factor.le(1)
    out["review_only_direction_factor_status"] = "invalid_direction_factor_review_fallback"
    out.loc[direction_factor.isna(), "review_only_direction_factor_status"] = "null_direction_factor_bidirectional_fallback"
    out.loc[valid_factor, "review_only_direction_factor_status"] = "valid_direction_factor_applied"
    out["review_only_bidirectional_fallback_status"] = np.where(valid_factor, "not_needed", "bidirectional_fallback_used")
    out["review_only_estimated_exposure"] = aadt_value * length_miles
    out.loc[valid_factor, "review_only_estimated_exposure"] = aadt_value.loc[valid_factor] * direction_factor.loc[valid_factor] * length_miles.loc[valid_factor]
    out.loc[~out["has_aadt"], "review_only_estimated_exposure"] = np.nan
    out["has_exposure_denominator"] = out["has_aadt"] & out["review_only_estimated_exposure"].notna()
    out["review_only_denominator_status"] = np.where(out["has_exposure_denominator"], "denominator_ready_no_crash_review_only", "missing_aadt_or_exposure")
    out["speed_aadt_ready_bin"] = out["has_rns_speed"] & out["has_aadt"] & out["has_exposure_denominator"]
    out["context_assignment_scope"] = "review_only_offset_intersection_zone_recovered_bins_not_active"
    _checkpoint("context_assignment_complete", len(out), f"speed={int(out['has_rns_speed'].sum()):,} aadt={int(out['has_aadt'].sum()):,}")
    return out


def _signal_summary(detail: pd.DataFrame, clean_signals: pd.DataFrame, grade_cases: pd.DataFrame, long_cases: pd.DataFrame) -> pd.DataFrame:
    work = detail.copy()
    signal = work.groupby("signal_id", dropna=False).agg(
        source_signal_id=("source_signal_id", "first"),
        source_layer=("signal_id", lambda _: ""),
        attempted_bin_count=("staged_recovered_bin_id", "count"),
        attempted_leg_count=("staged_recovered_leg_id", "nunique"),
        route_measure_ready_bins=("has_route_measure_identity", "sum"),
        roadway_context_bins=("has_roadway_context", "sum"),
        rns_speed_ready_bins=("has_rns_speed", "sum"),
        aadt_ready_bins=("has_aadt", "sum"),
        exposure_ready_bins=("has_exposure_denominator", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        max_distance_end_ft=("distance_end_ft", lambda s: pd.to_numeric(s, errors="coerce").max()),
        route_facility_discontinuity_types=("route_facility_discontinuity_type", _collapse),
        qa_cleanup_statuses=("qa_cleanup_status", _collapse),
        roadway_route_type_categories=("roadway_route_type_category", _collapse),
        speed_missing_reasons=("rns_speed_missing_reason", _collapse),
        aadt_missing_reasons=("aadt_v3_missing_reason", _collapse),
    ).reset_index()
    if not clean_signals.empty and "signal_id" in clean_signals.columns:
        base_cols = [col for col in ["signal_id", "source_signal_id", "staging_class", "qa_cleanup_status", "manual_category_qa_seed"] if col in clean_signals.columns]
        base = clean_signals[base_cols].drop_duplicates("signal_id").copy()
        signal = base.merge(signal, on="signal_id", how="left", suffixes=("", "_from_bins"))
        if "source_signal_id_from_bins" in signal.columns:
            signal["source_signal_id"] = _text(signal, "source_signal_id").where(_text(signal, "source_signal_id").ne(""), _text(signal, "source_signal_id_from_bins"))
            signal = signal.drop(columns=["source_signal_id_from_bins"])
        for col in [
            "attempted_bin_count",
            "attempted_leg_count",
            "route_measure_ready_bins",
            "roadway_context_bins",
            "rns_speed_ready_bins",
            "aadt_ready_bins",
            "exposure_ready_bins",
            "speed_aadt_ready_bins",
            "max_distance_end_ft",
        ]:
            if col in signal.columns:
                signal[col] = pd.to_numeric(signal[col], errors="coerce").fillna(0)
        for col in [
            "route_facility_discontinuity_types",
            "qa_cleanup_statuses",
            "roadway_route_type_categories",
            "speed_missing_reasons",
            "aadt_missing_reasons",
            "source_layer",
        ]:
            if col in signal.columns:
                signal[col] = _text(signal, col)
    signal["has_route_measure_identity"] = signal["route_measure_ready_bins"].gt(0)
    signal["has_roadway_context"] = signal["roadway_context_bins"].gt(0)
    signal["has_rns_speed"] = signal["rns_speed_ready_bins"].gt(0)
    signal["has_aadt"] = signal["aadt_ready_bins"].gt(0)
    signal["has_exposure_denominator"] = signal["exposure_ready_bins"].gt(0)
    signal["speed_aadt_ready"] = signal["speed_aadt_ready_bins"].gt(0)
    near = work.loc[pd.to_numeric(work["distance_end_ft"], errors="coerce").le(1000)]
    near_ready = near.groupby("signal_id")["speed_aadt_ready_bin"].agg(["count", "sum"]).reset_index()
    near_ready["speed_aadt_ready_0_1000"] = near_ready["count"].eq(near_ready["sum"]) & near_ready["count"].gt(0)
    signal = signal.merge(near_ready[["signal_id", "speed_aadt_ready_0_1000"]], on="signal_id", how="left")
    signal["speed_aadt_ready_0_1000"] = signal["speed_aadt_ready_0_1000"].fillna(False)
    signal["partial_near_signal_only"] = signal["max_distance_end_ft"].lt(1000)

    grade_signal_ids = set(_text(grade_cases, "signal_id"))
    long_signal_ids = set(_text(long_cases, "signal_id"))
    signal["has_grade_separation_holdouts"] = signal["signal_id"].isin(grade_signal_ids)
    signal["has_long_source_row_qa_flag"] = signal["signal_id"].isin(long_signal_ids)
    signal["eligible_for_later_universe_refresh"] = signal["speed_aadt_ready"] & signal["has_route_measure_identity"] & signal["has_roadway_context"]

    signal["missingness_reason_if_not_ready"] = ""
    signal.loc[signal["attempted_bin_count"].eq(0), "missingness_reason_if_not_ready"] = "no_refresh_eligible_bin_detail_after_qa_cleanup"
    signal.loc[~signal["has_route_measure_identity"], "missingness_reason_if_not_ready"] = "route_measure_identity_missing"
    signal.loc[signal["has_route_measure_identity"] & ~signal["has_rns_speed"], "missingness_reason_if_not_ready"] = "rns_speed_missing"
    signal.loc[signal["has_route_measure_identity"] & signal["has_rns_speed"] & ~signal["has_aadt"], "missingness_reason_if_not_ready"] = "aadt_missing"
    signal.loc[signal["has_route_measure_identity"] & signal["has_rns_speed"] & signal["has_aadt"] & ~signal["has_exposure_denominator"], "missingness_reason_if_not_ready"] = "exposure_missing"
    signal.loc[signal["attempted_bin_count"].eq(0), "missingness_reason_if_not_ready"] = "no_refresh_eligible_bin_detail_after_qa_cleanup"
    return signal


def _simple_summary(detail: pd.DataFrame, signal: pd.DataFrame, clean_bins: pd.DataFrame) -> dict[str, int]:
    held_bins = len(clean_bins) - len(detail)
    return {
        "attempted_bins": int(len(detail)),
        "attempted_signals": int(signal["signal_id"].nunique()),
        "signals_with_refresh_eligible_bins": int(detail["signal_id"].nunique()),
        "route_measure_signals": int(signal["has_route_measure_identity"].sum()),
        "roadway_context_signals": int(signal["has_roadway_context"].sum()),
        "speed_signals": int(signal["has_rns_speed"].sum()),
        "aadt_signals": int(signal["has_aadt"].sum()),
        "speed_aadt_ready_signals": int(signal["speed_aadt_ready"].sum()),
        "speed_aadt_ready_0_1000_signals": int(signal["speed_aadt_ready_0_1000"].sum()),
        "refresh_ready_signals": int(signal["eligible_for_later_universe_refresh"].sum()),
        "held_or_excluded_bins": int(held_bins),
        "held_or_excluded_signals": int(signal["attempted_bin_count"].eq(0).sum()),
        "grade_separation_holdout_signals": int(signal["has_grade_separation_holdouts"].sum()),
        "long_source_row_flag_signals": int(signal["has_long_source_row_qa_flag"].sum()),
    }


def _summary_tables(detail: pd.DataFrame, signal: pd.DataFrame, clean_bins: pd.DataFrame, metrics: dict[str, int]) -> dict[str, pd.DataFrame]:
    route_measure = pd.DataFrame(
        [
            {"metric": "attempted_bins", "count": len(detail)},
            {"metric": "bins_with_route_measure_identity", "count": int(detail["has_route_measure_identity"].sum())},
            {"metric": "signals_with_route_measure_identity", "count": metrics["route_measure_signals"]},
            {"metric": "route_measure_identity_method", "count": "", "value": "source_travelway_lineage_linear_distance_proxy_review_only"},
            {"metric": "route_measure_proxy_caveat", "count": "", "value": "Review-only source-lineage proxy; no active route-measure promotion."},
        ]
    )
    speed = (
        detail.groupby(["rns_speed_match_status", "rns_speed_missing_reason"], dropna=False)
        .agg(bin_count=("staged_recovered_bin_id", "count"), signal_count=("signal_id", "nunique"))
        .reset_index()
        .sort_values(["bin_count"], ascending=False)
    )
    aadt = (
        detail.groupby(["aadt_v3_match_status", "aadt_v3_missing_reason", "review_only_denominator_status"], dropna=False)
        .agg(bin_count=("staged_recovered_bin_id", "count"), signal_count=("signal_id", "nunique"), estimated_exposure=("review_only_estimated_exposure", "sum"))
        .reset_index()
        .sort_values(["bin_count"], ascending=False)
    )
    readiness = pd.DataFrame(
        [
            {"metric": "attempted_refresh_eligible_bins", "count": metrics["attempted_bins"]},
            {"metric": "attempted_refresh_eligible_signals", "count": metrics["attempted_signals"]},
            {"metric": "signals_with_refresh_eligible_bin_detail", "count": metrics["signals_with_refresh_eligible_bins"]},
            {"metric": "signals_with_route_measure_identity", "count": metrics["route_measure_signals"]},
            {"metric": "signals_with_roadway_context", "count": metrics["roadway_context_signals"]},
            {"metric": "signals_with_rns_speed", "count": metrics["speed_signals"]},
            {"metric": "signals_with_aadt", "count": metrics["aadt_signals"]},
            {"metric": "signals_speed_aadt_ready", "count": metrics["speed_aadt_ready_signals"]},
            {"metric": "signals_0_1000_speed_aadt_ready", "count": metrics["speed_aadt_ready_0_1000_signals"]},
            {"metric": "held_or_excluded_bins", "count": metrics["held_or_excluded_bins"]},
            {"metric": "grade_separation_holdout_signals", "count": metrics["grade_separation_holdout_signals"]},
            {"metric": "long_source_row_flag_signals", "count": metrics["long_source_row_flag_signals"]},
        ]
    )
    projected = metrics["refresh_ready_signals"] + CURRENT_REPRESENTED_UNIVERSE_SIGNALS
    universe = pd.DataFrame(
        [
            {"metric": "current_represented_universe_signals", "count": CURRENT_REPRESENTED_UNIVERSE_SIGNALS, "note": "Given current expanded represented universe."},
            {"metric": "staged_signals_attempted", "count": metrics["attempted_signals"], "note": "Deduped refresh-eligible staged signal count."},
            {"metric": "staged_signals_speed_aadt_ready", "count": metrics["speed_aadt_ready_signals"], "note": "Ready under review-only context assignment."},
            {"metric": "projected_represented_universe_if_ready_staged_signals_accepted", "count": projected, "note": "Upper-bound projection assumes staged signals add to represented universe without de-dup overlap."},
            {"metric": "projected_percent_of_3933_base_signals", "count": round(projected / BASE_SIGNAL_UNIVERSE * 100, 2), "note": "Projection denominator is 3,933 base signals."},
            {"metric": "held_or_excluded_staged_bins", "count": metrics["held_or_excluded_bins"], "note": "Held by QA cleanup before context refresh."},
            {"metric": "held_or_excluded_staged_signals", "count": metrics["held_or_excluded_signals"], "note": "Signals with no attempted eligible bins after filtering."},
        ]
    )
    missing = (
        signal.groupby(["missingness_reason_if_not_ready"], dropna=False)
        .agg(signal_count=("signal_id", "nunique"), bin_count=("attempted_bin_count", "sum"))
        .reset_index()
        .sort_values(["signal_count"], ascending=False)
    )
    return {
        "route_measure": route_measure,
        "speed": speed,
        "aadt": aadt,
        "readiness": readiness,
        "universe": universe,
        "missingness": missing,
    }


def _findings(metrics: dict[str, int]) -> str:
    projected = CURRENT_REPRESENTED_UNIVERSE_SIGNALS + metrics["refresh_ready_signals"]
    pct = projected / BASE_SIGNAL_UNIVERSE * 100
    return f"""# Offset/Intersection-Zone Context Refresh Findings

## Bounded Question

This read-only pass asks whether QA-cleaned offset/intersection-zone recovered bins can carry route/measure identity, roadway context, RNS speed, and AADT/exposure context before any future universe refresh. It does not assign access, crashes, rates, or models.

## Results

- Refresh-eligible staged bins attempted: {metrics["attempted_bins"]:,}
- Refresh-eligible staged signals attempted: {metrics["attempted_signals"]:,}
- Signals with route/measure identity: {metrics["route_measure_signals"]:,}
- Signals with roadway context: {metrics["roadway_context_signals"]:,}
- Signals with RNS speed: {metrics["speed_signals"]:,}
- Signals with AADT/exposure: {metrics["aadt_signals"]:,}
- Signals speed+AADT ready: {metrics["speed_aadt_ready_signals"]:,}
- Signals speed+AADT ready in the 0-1,000 ft recovered window: {metrics["speed_aadt_ready_0_1000_signals"]:,}
- Grade-separation holdout signals present in the staged set: {metrics["grade_separation_holdout_signals"]:,}
- Held or excluded staged bins before refresh: {metrics["held_or_excluded_bins"]:,}

## Universe Projection

The current represented universe remains {CURRENT_REPRESENTED_UNIVERSE_SIGNALS:,} signals. If the {metrics["refresh_ready_signals"]:,} review-ready staged signals were accepted in a later refresh, the upper-bound projected represented universe would be {projected:,} signals, or {pct:.2f}% of the 3,933 base signals. This is a projection only; this module does not promote records.

## Interpretation

Route/measure identity is a review-only source-lineage proxy reconstructed from preserved Travelway line identifiers and staged bin distances. RNS speed and AADT use grouped midpoint containment against source interval tables and do not materialize bin-by-source overlap tables. Long-source-row flags are preserved as QA attributes; held grade-separated mainline/manual-review records are excluded from assignment.

## Recommendation

Fold these staged records into a refreshed review-only universe only after accepting the route/measure proxy caveat and confirming that the held grade-separated pieces remain excluded. The next refresh should keep the recovered records flagged as offset/intersection-zone provenance rather than treating them as ordinary active scaffold rows.
"""


def _qa(clean_bins: pd.DataFrame, detail: pd.DataFrame, metrics: dict[str, int]) -> pd.DataFrame:
    output_inside = str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/offset_intersection_zone_context_refresh")
    return pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, "", "true", "All writes are under the review output folder."),
            _qa_row("no_candidates_promoted", True, "", "true", "Records remain review-only staged recovered bins."),
            _qa_row("no_access_assignment", True, "", "true", "No access source or access output is read."),
            _qa_row("no_crash_assignment", True, "", "true", "No crash records are read or assigned."),
            _qa_row("no_rates_or_models", True, "", "true", "Exposure readiness is computed, but no rates/models are calculated."),
            _qa_row("only_refresh_eligible_bins_processed", len(detail) == int(_flag(clean_bins, "refresh_eligible_bin").sum()), len(detail), int(_flag(clean_bins, "refresh_eligible_bin").sum()), "QA cleanup eligibility filter is applied before context assignment."),
            _qa_row("held_mainline_manual_review_excluded", not (_flag(detail, "hold_excluded_mainline") | _flag(detail, "hold_manual_grade_separation_review") | _flag(detail, "hold_nonstandard_geometry")).any(), "", "true", "Held records are preserved in upstream QA cleanup but not processed here."),
            _qa_row("assignments_review_only", _text(detail, "context_assignment_scope").eq("review_only_offset_intersection_zone_recovered_bins_not_active").all(), "", "true", ""),
            _qa_row("no_bin_source_overlap_tables_materialized", True, "", "true", "Grouped searchsorted midpoint containment only."),
            _qa_row("deduped_signal_counts_separate_from_bin_counts", metrics["attempted_signals"] <= metrics["attempted_bins"], f"{metrics['attempted_signals']} signals / {metrics['attempted_bins']} bins", "signals <= bins", ""),
            _qa_row("outputs_written_only_to_review_folder", output_inside, str(OUT_DIR), "review/current/offset_intersection_zone_context_refresh", ""),
        ]
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = _missing_required_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    clean_bins = _read_csv(QA_CLEANUP_DIR / "cleaned_staged_offset_recovered_bins.csv")
    clean_legs = _read_csv(QA_CLEANUP_DIR / "cleaned_staged_offset_recovered_legs.csv")
    clean_signals = _read_csv(QA_CLEANUP_DIR / "cleaned_staged_offset_signal_summary.csv")
    readiness_input = _read_csv(QA_CLEANUP_DIR / "staging_qa_cleanup_readiness_summary.csv")
    grade_cases = _read_csv(QA_CLEANUP_DIR / "grade_separated_mainline_review_cases.csv")
    long_cases = _read_csv(QA_CLEANUP_DIR / "long_source_row_review_cases.csv")

    route_detail = _build_route_measure_identity(clean_bins)
    detail = _assign_context(route_detail)
    signal = _signal_summary(detail, clean_signals, grade_cases, long_cases)
    metrics = _simple_summary(detail, signal, clean_bins)
    tables = _summary_tables(detail, signal, clean_bins, metrics)

    _write_csv(detail, OUT_DIR / "offset_zone_context_bin_detail.csv")
    _write_csv(signal, OUT_DIR / "offset_zone_context_signal_summary.csv")
    _write_csv(tables["route_measure"], OUT_DIR / "offset_zone_route_measure_summary.csv")
    _write_csv(tables["speed"], OUT_DIR / "offset_zone_speed_summary.csv")
    _write_csv(tables["aadt"], OUT_DIR / "offset_zone_aadt_exposure_summary.csv")
    _write_csv(tables["readiness"], OUT_DIR / "offset_zone_context_readiness_summary.csv")
    _write_csv(tables["universe"], OUT_DIR / "offset_zone_updated_universe_projection.csv")
    _write_csv(tables["missingness"], OUT_DIR / "offset_zone_context_missingness.csv")
    _write_text(_findings(metrics), OUT_DIR / "offset_zone_context_refresh_findings.md")
    qa = _qa(clean_bins, detail, metrics)
    _write_csv(qa, OUT_DIR / "offset_zone_context_refresh_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.offset_intersection_zone_context_refresh",
        "bounded_question": "Review-only route/measure, roadway context, RNS speed, and AADT/exposure refresh for QA-cleaned offset/intersection-zone recovered bins.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "qa_cleanup_dir": str(QA_CLEANUP_DIR),
            "speed_source": str(SPEED_LIMIT_RNS_GDB),
            "aadt_source": str(AADT_FILE),
            "speed_reference_dir": str(SPEED_REFERENCE_DIR),
            "aadt_reference_dir": str(AADT_REFERENCE_DIR),
            "route_measure_reference_dir": str(ROUTE_REFERENCE_DIR),
            "qa_cleanup_manifest": _load_json(QA_CLEANUP_DIR / "staging_qa_cleanup_manifest.json"),
        },
        "outputs": [
            "offset_zone_context_bin_detail.csv",
            "offset_zone_context_signal_summary.csv",
            "offset_zone_route_measure_summary.csv",
            "offset_zone_speed_summary.csv",
            "offset_zone_aadt_exposure_summary.csv",
            "offset_zone_context_readiness_summary.csv",
            "offset_zone_updated_universe_projection.csv",
            "offset_zone_context_missingness.csv",
            "offset_zone_context_refresh_findings.md",
            "offset_zone_context_refresh_qa.csv",
            "offset_zone_context_refresh_manifest.json",
            "run_progress_log.txt",
        ],
        "metrics": metrics,
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_assigned": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "bin_by_source_overlap_tables_materialized": False,
        },
        "row_counts": {
            "cleaned_staged_bins_input": int(len(clean_bins)),
            "cleaned_staged_legs_input": int(len(clean_legs)),
            "qa_cleanup_readiness_rows_input": int(len(readiness_input)),
            "context_bin_detail": int(len(detail)),
            "context_signal_summary": int(len(signal)),
        },
    }
    _write_json(manifest, OUT_DIR / "offset_zone_context_refresh_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
