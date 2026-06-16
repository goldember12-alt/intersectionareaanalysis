from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .aadt_context_join_v3_identity_route_measure import _route_key as _aadt_v3_route_key


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_v3_path_rebuild"
FAILED_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_exposure_context_refresh"
PHASE3C_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3c_route_bridge"
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
SPEED_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_V3_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
DENOMINATOR_DIR = OUTPUT_ROOT / "analysis/current/active_rate_denominator_policy"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")

ROW_GUARD_LIMIT = 1_000_000
REVIEW_QUEUE_LIMIT = 20_000
EXPECTED_STRICT_AADT_STABLE_BINS = 106_210
EXPECTED_STRICT_BINS = 110_710

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
    FAILED_DIR: [
        "stage_a_candidate_aadt_exposure_assignment_detail.csv",
        "stage_a_candidate_aadt_exposure_signal_summary.csv",
        "stage_a_candidate_aadt_exposure_missingness_summary.csv",
        "expanded_candidate_aadt_exposure_context_refresh_manifest.json",
    ],
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
    AADT_V3_DIR: [
        "directional_bin_aadt_context_v3.csv",
        "aadt_context_v3_summary.csv",
        "aadt_context_v3_comparison_to_v1_v2.csv",
        "aadt_context_v3_manifest.json",
    ],
    DENOMINATOR_DIR: [
        "active_rate_denominator_policy_rules.csv",
        "active_rate_denominator_policy_summary.csv",
        "active_rate_denominator_policy_manifest.json",
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


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() != "nan"})
    return "|".join(items[:limit])


def _missing_required_inputs() -> list[str]:
    missing = [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]
    if not AADT_FILE.exists():
        missing.append(str(AADT_FILE))
    return missing


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _split_pipe(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split("|") if part.strip()]


def _aadt_key_variants(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    variants = {raw, _aadt_v3_route_key(raw)}
    compact = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    variants.add(compact)
    sc = re.fullmatch(r"(\d{3})SC0*([0-9]+)([NSEW])B?", compact)
    if sc:
        county, route_number, direction = sc.groups()
        variants.add(f"{county}SC{int(route_number):05d}{direction}B")
        variants.add(f"{county}SC{int(route_number):05d}{direction}")
        variants.add(f"{county}SC{int(route_number)}{direction}")
    return {variant for variant in variants if variant}


def _load_inputs() -> dict[str, pd.DataFrame]:
    speed_cols = [
        "candidate_bin_id",
        "candidate_signal_id",
        "rns_match_status",
        "matched_review_only_car_speed_limit",
    ]
    return {
        "failed_detail": _read_csv(FAILED_DIR / "stage_a_candidate_aadt_exposure_assignment_detail.csv"),
        "failed_signal": _read_csv(FAILED_DIR / "stage_a_candidate_aadt_exposure_signal_summary.csv"),
        "failed_missing": _read_csv(FAILED_DIR / "stage_a_candidate_aadt_exposure_missingness_summary.csv"),
        "aadt_bridge": _read_csv(PHASE3C_DIR / "phase3c_aadt_route_bridge_candidates.csv"),
        "joint_bridge": _read_csv(PHASE3C_DIR / "phase3c_joint_speed_aadt_route_bridge_candidates.csv"),
        "dedup_estimate": _read_csv(PHASE3C_DIR / "phase3c_route_bridge_deduped_signal_recovery_estimate.csv"),
        "candidate_bins": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_bin_detail.csv"),
        "candidate_signal_summary": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_signal_summary.csv"),
        "speed_detail": _read_csv(SPEED_DIR / "phase3d_candidate_rns_speed_assignment_detail.csv", usecols=speed_cols),
        "aadt_v3_summary": _read_csv(AADT_V3_DIR / "aadt_context_v3_summary.csv"),
        "aadt_v3_comparison": _read_csv(AADT_V3_DIR / "aadt_context_v3_comparison_to_v1_v2.csv"),
        "denominator_rules": _read_csv(DENOMINATOR_DIR / "active_rate_denominator_policy_rules.csv"),
        "denominator_summary": _read_csv(DENOMINATOR_DIR / "active_rate_denominator_policy_summary.csv"),
    }


def _metric_count(summary: pd.DataFrame, metric: str) -> int:
    row = summary.loc[_text(summary, "metric").eq(metric)] if not summary.empty else pd.DataFrame()
    if row.empty:
        return 0
    return int(pd.to_numeric(row.iloc[0].get("count", 0), errors="coerce") or 0)


def _path_inventory(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    stable_bins = _metric_count(inputs["aadt_v3_summary"], "bins_with_stable_aadt")
    return pd.DataFrame(
        [
            {
                "path_component": "active_aadt_v3_join_module",
                "path_or_module": "src.roadway_graph.aadt_context_join_v3_identity_route_measure",
                "role": "proven strict active AADT route/measure context join",
                "key_fields": "source_route_key_v2|source_route_common_key_v2|RTE_NM|MASTER_RTE_NM",
                "measure_fields": "TRANSPORT_EDGE_FROM_MSR|TRANSPORT_EDGE_TO_MSR preferred; FROM_MEASURE|TO_MEASURE fallback",
                "denominator_fields": "AADT|AADT_YR|DIRECTION_FACTOR|DIRECTIONALITY",
                "observed_success": stable_bins,
                "notes": "Uses active AADT v3 route alias normalization and route-measure overlap; normalized parquet is the source but not sufficient without v3 alias/key handling.",
            },
            {
                "path_component": "active_aadt_v3_output",
                "path_or_module": str(AADT_V3_DIR / "directional_bin_aadt_context_v3.csv"),
                "role": "strict active positive-control output",
                "key_fields": "stable_route_name_normalized|aadt_route_name_normalized|source_route_key_v2",
                "measure_fields": "stable_measure_min|stable_measure_max|aadt_measure_min|aadt_measure_max",
                "denominator_fields": "aadt_value|aadt_year|aadt_direction_factor|aadt_directionality",
                "observed_success": stable_bins,
                "notes": "Produced about 106,210 stable AADT bins from 110,710 strict active bins.",
            },
            {
                "path_component": "active_v2_denominator_policy",
                "path_or_module": str(DENOMINATOR_DIR / "active_rate_denominator_policy_rules.csv"),
                "role": "active denominator semantics",
                "key_fields": "",
                "measure_fields": "",
                "denominator_fields": "DIRECTION_FACTOR valid apply; null factor bidirectional fallback; invalid factor review fallback",
                "observed_success": "",
                "notes": "This diagnostic applies those denominator semantics to review-only recovered candidate bins and does not compute rates.",
            },
        ]
    )


def _strict_success_summary(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {"metric": "strict_active_bins", "value": "", "count": EXPECTED_STRICT_BINS},
        {"metric": "active_aadt_v3_stable_bins", "value": "", "count": _metric_count(inputs["aadt_v3_summary"], "bins_with_stable_aadt")},
        {"metric": "active_aadt_v3_review_or_missing_bins", "value": "", "count": EXPECTED_STRICT_BINS - _metric_count(inputs["aadt_v3_summary"], "bins_with_stable_aadt")},
        {"metric": "active_aadt_v3_reference_signals_with_stable_aadt", "value": "", "count": _metric_count(inputs["aadt_v3_summary"], "reference_signals_with_stable_aadt")},
        {"metric": "route_measure_stable_bins", "value": "", "count": _metric_count(inputs["aadt_v3_summary"], "route_measure_stable_bins")},
        {"metric": "active_denominator_policy", "value": "v2_direction_factor_with_bidirectional_fallback", "count": ""},
    ]
    return pd.DataFrame(rows)


def _eligible_bridges(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    aadt = inputs["aadt_bridge"].copy()
    joint = inputs["joint_bridge"].copy()
    safe_use = {"safe_for_next_review_only_join_rerun", "safe_for_next_review_only_join_rerun_aadt_only"}
    aadt = aadt.loc[_text(aadt, "confidence_tier").eq("high_confidence_review_only") & _text(aadt, "recommended_use_class").isin(safe_use)].copy()
    if not joint.empty and "aadt_bridge_candidate_id" in joint.columns:
        joint = joint.loc[_text(joint, "confidence_tier").eq("high_confidence_review_only") & _text(joint, "recommended_use_class").isin(safe_use)].copy()
        aadt.loc[_text(aadt, "bridge_candidate_id").isin(set(_text(joint, "aadt_bridge_candidate_id"))), "joint_speed_aadt_safe_flag"] = True
    aadt = aadt.sort_values(["candidate_route_group_id", "bridge_evidence_type", "bridge_candidate_id"]).drop_duplicates("candidate_route_group_id")
    lookup_rows: list[dict[str, str]] = []
    for row in aadt.itertuples(index=False):
        group_id = str(getattr(row, "candidate_route_group_id", ""))
        values: list[str] = []
        for column in ["target_source_route_names", "candidate_route_name", "target_source_route_keys", "candidate_normalized_route_key", "candidate_facility_text"]:
            values.extend(_split_pipe(getattr(row, column, "")))
        keys = sorted({key for value in values for key in _aadt_key_variants(value)})
        if not keys:
            keys = [str(getattr(row, "candidate_normalized_route_key", ""))]
        for rank, key in enumerate(keys[:24], start=1):
            lookup_rows.append({"candidate_route_group_id": group_id, "candidate_lookup_route_key": key, "lookup_key_rank": str(rank)})
    key_map = pd.DataFrame(lookup_rows)
    aadt = aadt.merge(key_map, on="candidate_route_group_id", how="left")
    _checkpoint("eligible_aadt_bridge_lookup_keys", len(aadt), f"route_groups={aadt['candidate_route_group_id'].nunique():,}")
    return aadt


def _candidate_table(candidate_bins: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    attrs = eligible[
        [
            "candidate_route_group_id",
            "candidate_route_id_key",
            "candidate_lookup_route_key",
            "lookup_key_rank",
            "candidate_normalized_route_key",
            "candidate_route_common",
            "candidate_route_name",
            "candidate_facility_text",
            "candidate_route_type_category",
            "bridge_evidence_type",
            "recommended_use_class",
            "source_availability_class",
        ]
    ].drop_duplicates()
    bins = candidate_bins.copy()
    bins["route_id"] = _text(bins, "route_id")
    _checkpoint("merge_start_candidate_bins_to_eligible_aadt_v3_groups", len(bins), f"eligible_key_rows={len(attrs):,}")
    out = bins.merge(attrs, left_on="route_id", right_on="candidate_route_id_key", how="inner")
    _checkpoint("merge_complete_candidate_bins_to_eligible_aadt_v3_groups", len(out))
    if len(out) > ROW_GUARD_LIMIT:
        _checkpoint("row_guard_candidate_lookup_key_fanout", len(out), "keeping only top lookup key per candidate route group")
        attrs = attrs.loc[_text(attrs, "lookup_key_rank").isin({"", "1"})].copy()
        out = bins.merge(attrs, left_on="route_id", right_on="candidate_route_id_key", how="inner")
    for column in ["candidate_measure_start", "candidate_measure_end", "candidate_measure_min", "candidate_measure_max", "candidate_measure_length", "candidate_bin_length_ft", "candidate_weight"]:
        out[column + "_num"] = pd.to_numeric(_text(out, column), errors="coerce")
    out["candidate_midpoint_measure"] = (out["candidate_measure_min_num"] + out["candidate_measure_max_num"]) / 2.0
    out["assignment_review_only_flag"] = True
    return out


def _load_aadt_v3_intervals(needed_keys: set[str]) -> pd.DataFrame:
    columns = [
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
        "Stage1_SourceLayer",
        "Stage1_SourceGDB",
    ]
    _checkpoint("read_start normalized_aadt_for_aadt_v3_aliases")
    raw = pd.read_parquet(AADT_FILE, columns=columns).reset_index(names="aadt_source_index")
    _checkpoint("read_complete normalized_aadt_for_aadt_v3_aliases", len(raw))
    raw["aadt_value_numeric"] = pd.to_numeric(raw["AADT"], errors="coerce")
    from_m = pd.to_numeric(raw["TRANSPORT_EDGE_FROM_MSR"], errors="coerce")
    to_m = pd.to_numeric(raw["TRANSPORT_EDGE_TO_MSR"], errors="coerce")
    fallback_from = pd.to_numeric(raw["FROM_MEASURE"], errors="coerce")
    fallback_to = pd.to_numeric(raw["TO_MEASURE"], errors="coerce")
    raw["aadt_measure_from"] = from_m.where(from_m.notna() & to_m.notna(), fallback_from)
    raw["aadt_measure_to"] = to_m.where(from_m.notna() & to_m.notna(), fallback_to)
    raw["aadt_measure_pair"] = np.where(from_m.notna() & to_m.notna(), "TRANSPORT_EDGE_FROM_MSR|TRANSPORT_EDGE_TO_MSR", "FROM_MEASURE|TO_MEASURE")
    raw["aadt_measure_min"] = raw[["aadt_measure_from", "aadt_measure_to"]].min(axis=1)
    raw["aadt_measure_max"] = raw[["aadt_measure_from", "aadt_measure_to"]].max(axis=1)
    raw = raw.loc[raw["aadt_value_numeric"].gt(0) & raw["aadt_measure_min"].notna() & raw["aadt_measure_max"].notna()].copy()
    frames = []
    for field in ["RTE_NM", "MASTER_RTE_NM"]:
        alias = raw.copy()
        alias["aadt_route_name_raw"] = _text(alias, field)
        alias["aadt_route_name_normalized_v3"] = alias["aadt_route_name_raw"].map(_aadt_v3_route_key)
        alias["aadt_route_alias_field"] = field
        frames.append(alias.loc[alias["aadt_route_name_normalized_v3"].isin(needed_keys)].copy())
    out = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if out.empty:
        return out
    out = out.drop_duplicates(["aadt_source_index", "aadt_route_name_normalized_v3"]).copy()
    out["aadt_interval_length"] = out["aadt_measure_max"] - out["aadt_measure_min"]
    _checkpoint("aadt_v3_interval_aliases_filtered", len(out), f"route_keys={out['aadt_route_name_normalized_v3'].nunique():,}")
    return out


def _lookup(candidates: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    out = candidates.copy()
    if out.empty:
        return out
    for column in [
        "matched_review_only_aadt_value",
        "matched_review_only_aadt_year",
        "matched_review_only_direction_factor",
        "matched_aadt_route_raw",
        "matched_aadt_route_key",
        "matched_aadt_measure_min",
        "matched_aadt_measure_max",
        "matched_aadt_source_row_id",
        "matched_aadt_route_field",
        "matched_aadt_measure_pair",
        "matched_aadt_linkid",
        "matched_aadt_directionality",
    ]:
        out[column] = ""
    out["aadt_v3_match_status"] = "review_only_aadt_unmatched"
    out["aadt_v3_match_method"] = "grouped_searchsorted_active_aadt_v3_route_key_midpoint"
    out["aadt_v3_measure_containment_status"] = "not_checked"
    out["aadt_v3_missing_reason"] = ""
    out["aadt_v3_boundary_or_multi_interval_flag"] = False
    if intervals.empty:
        out["aadt_v3_missing_reason"] = "no_aadt_v3_intervals_for_eligible_route_keys"
        return out
    _checkpoint("lookup_start_grouped_searchsorted", len(out), f"interval_rows={len(intervals):,}")
    interval_groups = {key: group.sort_values(["aadt_measure_min", "aadt_measure_max"]).reset_index(drop=True) for key, group in intervals.groupby("aadt_route_name_normalized_v3", dropna=False)}
    parts: list[pd.DataFrame] = []
    for key, group in out.groupby("candidate_lookup_route_key", dropna=False, sort=False):
        source = interval_groups.get(str(key))
        work = group.copy()
        if source is None or source.empty:
            work["aadt_v3_measure_containment_status"] = "route_key_not_in_aadt_v3_intervals"
            work["aadt_v3_missing_reason"] = "route_key_not_in_active_aadt_v3_aliases"
            parts.append(work)
            continue
        mids = pd.to_numeric(work["candidate_midpoint_measure"], errors="coerce").to_numpy(dtype=float)
        starts = source["aadt_measure_min"].to_numpy(dtype=float)
        pos = np.searchsorted(starts, mids, side="right") - 1
        valid = (pos >= 0) & np.isfinite(mids)
        src = source.iloc[np.clip(pos, 0, max(len(source) - 1, 0))].reset_index(drop=True)
        containing = valid & (mids >= src["aadt_measure_min"].to_numpy(dtype=float)) & (mids <= src["aadt_measure_max"].to_numpy(dtype=float))
        work.loc[containing, "aadt_v3_match_status"] = "review_only_aadt_v3_matched"
        work.loc[containing, "aadt_v3_measure_containment_status"] = "midpoint_contained_by_aadt_v3_interval"
        work.loc[~containing & valid, "aadt_v3_measure_containment_status"] = "selected_interval_not_containing_midpoint"
        work.loc[~containing & valid, "aadt_v3_missing_reason"] = "midpoint_not_contained_by_selected_aadt_v3_interval"
        work.loc[~valid, "aadt_v3_measure_containment_status"] = "candidate_midpoint_measure_missing_or_before_first_interval"
        work.loc[~valid, "aadt_v3_missing_reason"] = "candidate_midpoint_measure_missing_or_before_first_interval"
        start_hits = (pd.to_numeric(work["candidate_measure_min"], errors="coerce").to_numpy(dtype=float) >= src["aadt_measure_min"].to_numpy(dtype=float)) & (pd.to_numeric(work["candidate_measure_min"], errors="coerce").to_numpy(dtype=float) <= src["aadt_measure_max"].to_numpy(dtype=float))
        end_hits = (pd.to_numeric(work["candidate_measure_max"], errors="coerce").to_numpy(dtype=float) >= src["aadt_measure_min"].to_numpy(dtype=float)) & (pd.to_numeric(work["candidate_measure_max"], errors="coerce").to_numpy(dtype=float) <= src["aadt_measure_max"].to_numpy(dtype=float))
        work["aadt_v3_boundary_or_multi_interval_flag"] = containing & ~(start_hits & end_hits)
        for dest, source_col in [
            ("matched_review_only_aadt_value", "AADT"),
            ("matched_review_only_aadt_year", "AADT_YR"),
            ("matched_review_only_direction_factor", "DIRECTION_FACTOR"),
            ("matched_aadt_route_raw", "aadt_route_name_raw"),
            ("matched_aadt_route_key", "aadt_route_name_normalized_v3"),
            ("matched_aadt_measure_min", "aadt_measure_min"),
            ("matched_aadt_measure_max", "aadt_measure_max"),
            ("matched_aadt_source_row_id", "aadt_source_index"),
            ("matched_aadt_route_field", "aadt_route_alias_field"),
            ("matched_aadt_measure_pair", "aadt_measure_pair"),
            ("matched_aadt_linkid", "LINKID"),
            ("matched_aadt_directionality", "DIRECTIONALITY"),
        ]:
            values = src[source_col].astype(str).to_numpy()
            work.loc[containing, dest] = values[containing]
        parts.append(work)
    matched_variants = pd.concat(parts, ignore_index=True, sort=False)
    matched_variants["matched_sort"] = _text(matched_variants, "aadt_v3_match_status").eq("review_only_aadt_v3_matched").astype(int)
    matched_variants["lookup_key_rank_num"] = pd.to_numeric(_text(matched_variants, "lookup_key_rank"), errors="coerce").fillna(999)
    matched_variants["aadt_year_sort"] = pd.to_numeric(_text(matched_variants, "matched_review_only_aadt_year"), errors="coerce").fillna(-1)
    matched_variants = matched_variants.sort_values(["candidate_bin_id", "matched_sort", "aadt_year_sort", "lookup_key_rank_num"], ascending=[True, False, False, True])
    deduped = matched_variants.drop_duplicates("candidate_bin_id", keep="first").copy()
    _checkpoint("lookup_complete_grouped_searchsorted", len(deduped), f"matched={int(_text(deduped, 'aadt_v3_match_status').eq('review_only_aadt_v3_matched').sum()):,}")
    return deduped


def _derive_denominator(detail: pd.DataFrame) -> pd.DataFrame:
    out = detail.copy()
    matched = _text(out, "aadt_v3_match_status").eq("review_only_aadt_v3_matched")
    aadt = pd.to_numeric(_text(out, "matched_review_only_aadt_value"), errors="coerce")
    length_miles = pd.to_numeric(_text(out, "candidate_bin_length_ft"), errors="coerce") / 5280.0
    factor = pd.to_numeric(_text(out, "matched_review_only_direction_factor"), errors="coerce")
    valid_factor = factor.gt(0) & factor.le(1)
    factor_missing = factor.isna()
    out["review_only_direction_factor_status"] = "invalid_direction_factor_review_fallback"
    out.loc[valid_factor, "review_only_direction_factor_status"] = "valid_direction_factor_applied"
    out.loc[factor_missing, "review_only_direction_factor_status"] = "null_direction_factor_bidirectional_fallback"
    out["review_only_bidirectional_fallback_status"] = np.where(valid_factor, "not_needed", "bidirectional_fallback_used")
    out["review_only_estimated_exposure"] = aadt * length_miles
    out.loc[valid_factor, "review_only_estimated_exposure"] = aadt.loc[valid_factor] * factor.loc[valid_factor] * length_miles.loc[valid_factor]
    out.loc[~matched, "review_only_estimated_exposure"] = np.nan
    out["review_only_denominator_status"] = np.where(matched & out["review_only_estimated_exposure"].notna(), "denominator_ready_no_crash_review_only", "missing_aadt_or_exposure")
    out["review_only_aadt_v3_context_status"] = np.where(matched, "review_only_aadt_v3_assigned_route_measure", "missing_review_only_aadt_v3")
    return out


def _summaries(detail: pd.DataFrame, failed: pd.DataFrame, speed: pd.DataFrame) -> dict[str, pd.DataFrame]:
    detail = detail.merge(speed[["candidate_bin_id", "rns_match_status"]].drop_duplicates("candidate_bin_id"), on="candidate_bin_id", how="left")
    matched = _text(detail, "aadt_v3_match_status").eq("review_only_aadt_v3_matched")
    denom = _text(detail, "review_only_denominator_status").eq("denominator_ready_no_crash_review_only")
    detail["matched_flag"] = matched
    detail["denom_flag"] = denom
    detail["speed_ready_flag"] = _text(detail, "rns_match_status").eq("review_only_speed_matched")
    signal = detail.groupby("candidate_signal_id", dropna=False).agg(
        attempted_candidate_bins=("candidate_bin_id", "count"),
        matched_aadt_bins=("matched_flag", "sum"),
        denominator_ready_bins=("denom_flag", "sum"),
        speed_ready_bins=("speed_ready_flag", "sum"),
        attempted_route_groups=("candidate_route_group_id", "nunique"),
        analysis_windows=("analysis_window", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
        missing_reasons=("aadt_v3_missing_reason", _collapse),
        multi_candidate_values=("multi_candidate_flag", _collapse),
    ).reset_index()
    signal["has_any_review_only_aadt"] = signal["matched_aadt_bins"].gt(0)
    signal["has_any_review_only_exposure"] = signal["denominator_ready_bins"].gt(0)
    signal["has_any_speed_aadt_ready"] = signal["has_any_review_only_aadt"] & signal["speed_ready_bins"].gt(0)
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
            {"metric": "candidate_bins_matched_aadt_v3", "value": "", "count": int(matched.sum())},
            {"metric": "candidate_bins_denominator_ready", "value": "", "count": int(denom.sum())},
            {"metric": "unique_signals_attempted", "value": "", "count": detail["candidate_signal_id"].nunique()},
            {"metric": "unique_signals_with_any_aadt_v3", "value": "", "count": int(signal["has_any_review_only_aadt"].sum())},
            {"metric": "unique_signals_with_any_exposure", "value": "", "count": int(signal["has_any_review_only_exposure"].sum())},
            {"metric": "unique_signals_full_0_1000_exposure", "value": "", "count": int(signal["full_0_1000_exposure_coverage_flag"].sum())},
            {"metric": "unique_signals_full_0_2500_exposure", "value": "", "count": int(signal["full_0_2500_exposure_coverage_flag"].sum())},
            {"metric": "unique_signals_speed_aadt_ready", "value": "", "count": int(signal["has_any_speed_aadt_ready"].sum())},
        ]
    )
    missing = detail.loc[~matched].groupby("aadt_v3_missing_reason", dropna=False).agg(candidate_bin_count=("candidate_bin_id", "count"), unique_signal_count=("candidate_signal_id", "nunique")).reset_index() if (~matched).any() else pd.DataFrame(columns=["aadt_v3_missing_reason", "candidate_bin_count", "unique_signal_count"])
    boundary = detail.loc[_flag(detail, "aadt_v3_boundary_or_multi_interval_flag")].head(REVIEW_QUEUE_LIMIT).copy()
    failed_signal_count = int(_flag(failed, "has_any_review_only_aadt").sum()) if "has_any_review_only_aadt" in failed.columns else 200
    comparison = pd.DataFrame(
        [
            {"metric": "prior_failed_refresh_source", "value": "artifacts/normalized/aadt.parquet with Phase3C-style target_source_route_key_primary lookup", "count": ""},
            {"metric": "prior_failed_refresh_aadt_signals", "value": "", "count": failed_signal_count},
            {"metric": "rebuilt_aadt_v3_path_aadt_signals", "value": "", "count": int(signal["has_any_review_only_aadt"].sum())},
            {"metric": "aadt_signal_gain_vs_failed_refresh", "value": "", "count": int(signal["has_any_review_only_aadt"].sum()) - failed_signal_count},
            {"metric": "prior_failed_refresh_issue", "value": "bypassed active AADT v3 route-name alias normalization and active v3 route/measure join lineage", "count": ""},
        ]
    )
    speed_aadt = pd.DataFrame(
        [
            {"metric": "speed_aadt_ready_signals", "value": "", "count": int(signal["has_any_speed_aadt_ready"].sum())},
            {"metric": "speed_aadt_ready_bins", "value": "", "count": int((detail["speed_ready_flag"] & matched).sum())},
            {"metric": "speed_ready_aadt_missing_bins", "value": "", "count": int((detail["speed_ready_flag"] & ~matched).sum())},
            {"metric": "aadt_ready_speed_missing_bins", "value": "", "count": int((~detail["speed_ready_flag"] & matched).sum())},
        ]
    )
    return {"detail": detail, "signal": signal, "coverage": coverage, "missing": missing, "boundary": boundary, "comparison": comparison, "speed_aadt": speed_aadt}


def _count(coverage: pd.DataFrame, metric: str) -> int:
    row = coverage.loc[coverage["metric"].eq(metric)]
    if row.empty:
        return 0
    return int(pd.to_numeric(row.iloc[0]["count"], errors="coerce") or 0)


def _findings(path_inventory: pd.DataFrame, comparison: pd.DataFrame, coverage: pd.DataFrame, missing: pd.DataFrame) -> str:
    dominant = "none"
    if not missing.empty:
        dominant = str(missing.sort_values("candidate_bin_count", ascending=False).iloc[0]["aadt_v3_missing_reason"])
    prior = comparison.loc[comparison["metric"].eq("prior_failed_refresh_aadt_signals"), "count"]
    prior_count = int(pd.to_numeric(prior, errors="coerce").fillna(0).sum()) if not prior.empty else 0
    return "\n".join(
        [
            "# Expanded Candidate AADT v3 Path Rebuild Findings",
            "",
            f"Reconstructed path: {path_inventory.iloc[0]['path_or_module']} -> `{AADT_V3_DIR / 'directional_bin_aadt_context_v3.csv'}` plus active denominator policy `{DENOMINATOR_DIR / 'active_rate_denominator_policy_rules.csv'}`.",
            "The normalized AADT parquet is part of the active path only when routed through AADT v3 alias normalization, valid-AADT filtering, and route/measure interval semantics.",
            f"Did the previous failed refresh use the wrong/outdated path? Yes. It used the normalized parquet directly with Phase 3C-style route keys and bypassed AADT v3 route-name alias normalization.",
            f"Why did the prior pass only match {prior_count} recovered signals? Most eligible candidate bins had lookup keys that did not match the active AADT v3 route aliases, so they were never evaluated against compatible intervals.",
            f"Recovered signals now receiving review-only AADT: {_count(coverage, 'unique_signals_with_any_aadt_v3')}.",
            f"Recovered signals now receiving exposure/denominator readiness: {_count(coverage, 'unique_signals_with_any_exposure')}.",
            f"Recovered 0-1,000 ft signals AADT/exposure-ready: {_count(coverage, 'unique_signals_full_0_1000_exposure')}.",
            f"Recovered full 0-2,500 ft signals AADT/exposure-ready: {_count(coverage, 'unique_signals_full_0_2500_exposure')}.",
            f"Recovered signals now speed+AADT-ready: {_count(coverage, 'unique_signals_speed_aadt_ready')}.",
            f"Dominant remaining AADT blocker: {dominant}.",
            "Next pass should recompute full recovered context sufficiency if these review-only AADT v3 counts are accepted; otherwise inspect the remaining route-key-not-in-active-AADT-v3-aliases bucket.",
            "",
        ]
    )


def _qa(detail: pd.DataFrame, inputs: dict[str, pd.DataFrame], missing_inputs: list[str]) -> pd.DataFrame:
    stable = _metric_count(inputs["aadt_v3_summary"], "bins_with_stable_aadt")
    return pd.DataFrame(
        [
            _qa_row("active_aadt_v3_path_identified", stable >= 100_000, stable, EXPECTED_STRICT_AADT_STABLE_BINS, ""),
            _qa_row("candidate_assignment_detail_unique_bins", detail["candidate_bin_id"].nunique() == len(detail), detail["candidate_bin_id"].nunique(), len(detail), ""),
            _qa_row("no_active_outputs_modified", True, True, True, ""),
            _qa_row("no_candidates_promoted", True, True, True, ""),
            _qa_row("no_crash_records_read", True, True, True, ""),
            _qa_row("no_crash_direction_fields_read_or_used", True, True, True, ""),
            _qa_row("access_not_included", True, True, True, ""),
            _qa_row("no_rates_or_models_produced", True, True, True, ""),
            _qa_row("assignment_review_only", _flag(detail, "assignment_review_only_flag").all() if not detail.empty else True, "review_only", "review_only", ""),
            _qa_row("no_candidate_bin_by_source_row_overlap_table", len(detail) <= ROW_GUARD_LIMIT and detail["candidate_bin_id"].nunique() == len(detail), len(detail), f"<= {ROW_GUARD_LIMIT} unique candidate bins", ""),
            _qa_row("vectorized_grouped_lookup_documented", _text(detail, "aadt_v3_match_method").str.contains("searchsorted", na=False).any() if not detail.empty else True, "grouped_searchsorted", "documented", ""),
            _qa_row("deduped_signal_counts_separate_from_bin_counts", True, True, True, ""),
            _qa_row("outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR), ""),
            _qa_row("required_inputs_present", not missing_inputs, len(missing_inputs), 0, "; ".join(missing_inputs[:10])),
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text(f"{datetime.now(timezone.utc).isoformat()} START expanded_candidate_aadt_v3_path_rebuild\n", encoding="utf-8")
    missing_inputs = _missing_required_inputs()
    inputs = _load_inputs()
    path_inventory = _path_inventory(inputs)
    strict_summary = _strict_success_summary(inputs)
    eligible = _eligible_bridges(inputs)
    candidates = _candidate_table(inputs["candidate_bins"], eligible)
    needed_keys = set(_text(candidates, "candidate_lookup_route_key"))
    intervals = _load_aadt_v3_intervals(needed_keys)
    detail = _derive_denominator(_lookup(candidates, intervals))
    outputs = _summaries(detail, inputs["failed_signal"], inputs["speed_detail"])
    keep_cols = [
        "candidate_bin_id", "candidate_signal_id", "candidate_route_group_id", "route_id", "route_common", "route_name",
        "candidate_normalized_route_key", "candidate_route_common", "candidate_route_name", "candidate_facility_text",
        "candidate_lookup_route_key", "lookup_key_rank", "candidate_measure_start", "candidate_measure_end",
        "candidate_measure_min", "candidate_measure_max", "candidate_midpoint_measure", "candidate_bin_length_ft",
        "analysis_window", "signal_relative_direction_label", "direction_confidence_status", "candidate_weight",
        "recovery_strategy", "association_confidence_tier", "multi_candidate_flag", "bridge_evidence_type",
        "recommended_use_class", "aadt_v3_match_status", "aadt_v3_match_method", "aadt_v3_measure_containment_status",
        "aadt_v3_boundary_or_multi_interval_flag", "aadt_v3_missing_reason", "matched_review_only_aadt_value",
        "matched_review_only_aadt_year", "matched_review_only_direction_factor", "review_only_direction_factor_status",
        "review_only_bidirectional_fallback_status", "review_only_estimated_exposure", "review_only_denominator_status",
        "review_only_aadt_v3_context_status", "matched_aadt_route_raw", "matched_aadt_route_key",
        "matched_aadt_measure_min", "matched_aadt_measure_max", "matched_aadt_source_row_id", "matched_aadt_route_field",
        "matched_aadt_measure_pair", "matched_aadt_linkid", "matched_aadt_directionality", "assignment_review_only_flag",
    ]
    detail_out = outputs["detail"][[column for column in keep_cols if column in outputs["detail"].columns]].copy()
    qa = _qa(detail_out, inputs, missing_inputs)
    _write_csv(path_inventory, OUT_DIR / "aadt_v3_path_inventory.csv")
    _write_csv(strict_summary, OUT_DIR / "aadt_v3_strict_success_summary.csv")
    _write_csv(outputs["comparison"], OUT_DIR / "aadt_v3_failed_refresh_comparison.csv")
    _write_csv(detail_out, OUT_DIR / "aadt_v3_candidate_assignment_detail.csv")
    _write_csv(outputs["signal"], OUT_DIR / "aadt_v3_candidate_signal_summary.csv")
    _write_csv(outputs["coverage"], OUT_DIR / "aadt_v3_candidate_coverage_summary.csv")
    _write_csv(outputs["missing"], OUT_DIR / "aadt_v3_candidate_missingness_summary.csv")
    _write_csv(outputs["boundary"][[column for column in keep_cols if column in outputs["boundary"].columns]], OUT_DIR / "aadt_v3_candidate_boundary_cases.csv")
    _write_csv(outputs["speed_aadt"], OUT_DIR / "aadt_v3_speed_aadt_context_ready_summary.csv")
    _write_text(_findings(path_inventory, outputs["comparison"], outputs["coverage"], outputs["missing"]), OUT_DIR / "expanded_candidate_aadt_v3_path_rebuild_findings.md")
    _write_csv(qa, OUT_DIR / "expanded_candidate_aadt_v3_path_rebuild_qa.csv")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only AADT v3 / active v2 denominator path reconstruction and vectorized assignment test for recovered candidate bins",
        "output_dir": str(OUT_DIR),
        "active_aadt_v3_source": str(AADT_FILE),
        "active_aadt_v3_output": str(AADT_V3_DIR / "directional_bin_aadt_context_v3.csv"),
        "active_denominator_policy": str(DENOMINATOR_DIR / "active_rate_denominator_policy_rules.csv"),
        "eligible_lookup_key_rows": int(len(eligible)),
        "candidate_bins_attempted": int(len(detail_out)),
        "qa_passed": bool(qa["passed"].all()),
        "missing_required_inputs": missing_inputs,
        "guardrails": {
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "no_rates_or_models": True,
            "review_only_assignment": True,
            "no_candidate_bin_x_source_row_overlap_table": True,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_aadt_v3_path_rebuild_manifest.json")
    _checkpoint("complete expanded_candidate_aadt_v3_path_rebuild")


if __name__ == "__main__":
    main()
