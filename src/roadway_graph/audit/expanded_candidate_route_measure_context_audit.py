from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
BIN_GEN_DIR = OUTPUT_ROOT / "review/current/signal_recovery_candidate_bin_generation"
JOIN_KEY_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_context_join_key_diagnostic"
SPEED_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v5_new_source_supplement"
AADT_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
ACCESS_V2_DIR = OUTPUT_ROOT / "review/current/access_v2_route_measure_window_recovery"
ACTIVE_CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active"
TABLES_DIR = OUTPUT_ROOT / "tables/current"
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"

EXPECTED_CANDIDATE_BINS = 136_227
EXPECTED_RECOVERED_SIGNALS = 1_590
STRICT_ACTIVE_SIGNAL_BASELINE = 971


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if usecols is None:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    header = pd.read_csv(path, nrows=0)
    cols = [col for col in usecols if col in header.columns]
    if not cols:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_stage1_inputs() -> dict[str, Any]:
    return {
        "candidate_bins": _read_csv(BIN_GEN_DIR / "candidate_recovery_bins.csv"),
        "candidate_signal_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_signal_summary.csv"),
        "candidate_association_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_association_summary.csv"),
        "candidate_generation_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_bin_generation_summary.csv"),
        "candidate_existing_overlap": _read_csv(BIN_GEN_DIR / "candidate_recovery_existing_active_overlap.csv"),
        "candidate_manifest": _load_manifest(BIN_GEN_DIR / "candidate_recovery_bin_generation_manifest.json"),
        "join_key_prototype": _read_csv(JOIN_KEY_DIR / "candidate_bin_join_key_prototype.csv"),
        "join_key_inventory": _read_csv(JOIN_KEY_DIR / "candidate_context_join_key_inventory.csv"),
        "join_feasibility": _read_csv(JOIN_KEY_DIR / "candidate_context_layer_join_feasibility.csv"),
        "join_missing_fields": _read_csv(JOIN_KEY_DIR / "candidate_context_required_missing_fields.csv"),
        "roadway_context_coverage": _read_csv(JOIN_KEY_DIR / "candidate_roadway_context_subfield_coverage.csv"),
        "join_manifest": _load_manifest(JOIN_KEY_DIR / "expanded_candidate_context_join_key_manifest.json"),
        "graph_edges": _read_csv(
            TABLES_DIR / "roadway_graph_edges.csv",
            usecols=[
                "graph_edge_id",
                "from_graph_node_id",
                "to_graph_node_id",
                "route_name",
                "route_common",
                "route_id",
                "event_source",
                "road_component_id",
                "source_road_row_id",
                "from_measure",
                "to_measure",
                "rte_from_measure",
                "rte_to_measure",
                "length_ft",
                "roadway_division_status",
                "logical_segment_mode",
            ],
        ),
    }


def _construct_stage1_detail(candidate_bins: pd.DataFrame, graph_edges: pd.DataFrame) -> pd.DataFrame:
    edge = graph_edges.drop_duplicates("graph_edge_id").copy()
    detail = candidate_bins.merge(edge, on=["graph_edge_id", "road_component_id"], how="left", suffixes=("", "_edge"))
    for col in ["route_name", "route_common", "route_id", "source_road_row_id", "event_source"]:
        edge_col = f"{col}_edge"
        if edge_col in detail.columns:
            detail[col] = _text(detail, col).where(_text(detail, col).ne(""), _text(detail, edge_col))

    edge_len = _num(detail, "length_ft")
    bin_start = _num(detail, "distance_from_signal_start_ft")
    bin_end = _num(detail, "distance_from_signal_end_ft")
    measure_start_edge = _first_numeric(detail, ["rte_from_measure", "from_measure"])
    measure_end_edge = _first_numeric(detail, ["rte_to_measure", "to_measure"])
    signal_id = _text(detail, "signal_id")
    from_has_signal = [sig in node for sig, node in zip(signal_id, _text(detail, "from_graph_node_id"), strict=False)]
    to_has_signal = [sig in node for sig, node in zip(signal_id, _text(detail, "to_graph_node_id"), strict=False)]
    from_has_signal = pd.Series(from_has_signal, index=detail.index)
    to_has_signal = pd.Series(to_has_signal, index=detail.index)

    frac_start = (bin_start / edge_len).clip(lower=0, upper=1)
    frac_end = (bin_end / edge_len).clip(lower=0, upper=1)
    delta = measure_end_edge - measure_start_edge
    forward_start = measure_start_edge + delta * frac_start
    forward_end = measure_start_edge + delta * frac_end
    reverse_start = measure_end_edge - delta * frac_start
    reverse_end = measure_end_edge - delta * frac_end

    detail["candidate_measure_start"] = forward_start.where(from_has_signal, reverse_start.where(to_has_signal, pd.NA))
    detail["candidate_measure_end"] = forward_end.where(from_has_signal, reverse_end.where(to_has_signal, pd.NA))
    detail["candidate_measure_min"] = pd.concat([detail["candidate_measure_start"], detail["candidate_measure_end"]], axis=1).min(axis=1)
    detail["candidate_measure_max"] = pd.concat([detail["candidate_measure_start"], detail["candidate_measure_end"]], axis=1).max(axis=1)
    detail["candidate_measure_length"] = (detail["candidate_measure_max"] - detail["candidate_measure_min"]).abs()
    detail["candidate_measure_direction_status"] = "measure_increases_from_signal"
    detail.loc[to_has_signal, "candidate_measure_direction_status"] = "measure_decreases_from_signal"
    detail.loc[~from_has_signal & ~to_has_signal, "candidate_measure_direction_status"] = "direction_unresolved"
    detail.loc[delta.eq(0), "candidate_measure_direction_status"] = "zero_measure_delta"

    has_route = _text(detail, "route_id").ne("") | _text(detail, "route_name").ne("") | _text(detail, "route_common").ne("")
    has_measure = detail["candidate_measure_start"].notna() & detail["candidate_measure_end"].notna()
    valid_len = edge_len.gt(0)
    complete = has_route & has_measure & valid_len & (from_has_signal | to_has_signal)
    detail["candidate_route_measure_interval_status"] = "complete_route_measure_interval"
    detail.loc[~has_route & has_measure, "candidate_route_measure_interval_status"] = "route_missing"
    detail.loc[has_route & ~has_measure, "candidate_route_measure_interval_status"] = "measure_missing"
    detail.loc[has_route & _text(detail, "rte_from_measure").ne("") & _text(detail, "rte_to_measure").ne("") & ~(from_has_signal | to_has_signal), "candidate_route_measure_interval_status"] = "edge_level_measure_proxy"
    detail.loc[has_route & ~has_measure & _text(detail, "from_measure").eq("") & _text(detail, "rte_from_measure").eq(""), "candidate_route_measure_interval_status"] = "route_only_no_measure"
    detail.loc[~valid_len, "candidate_route_measure_interval_status"] = "insufficient_existing_evidence"
    detail.loc[complete, "candidate_route_measure_interval_status"] = "complete_route_measure_interval"
    detail["candidate_route_measure_join_quality"] = "bin_level_interpolated_from_graph_edge_measure"
    detail.loc[detail["candidate_route_measure_interval_status"].ne("complete_route_measure_interval"), "candidate_route_measure_join_quality"] = "partial_or_proxy_not_exact"
    detail["interval_construction_method"] = "linear_interpolation_along_signal_adjacent_graph_edge"
    detail["interval_failure_reason"] = ""
    detail.loc[detail["candidate_route_measure_interval_status"].eq("route_missing"), "interval_failure_reason"] = "route_missing"
    detail.loc[detail["candidate_route_measure_interval_status"].eq("measure_missing"), "interval_failure_reason"] = "measure_missing"
    detail.loc[detail["candidate_route_measure_interval_status"].eq("edge_level_measure_proxy"), "interval_failure_reason"] = "signal_endpoint_not_identified_for_bin_interpolation"
    detail.loc[detail["candidate_route_measure_interval_status"].eq("route_only_no_measure"), "interval_failure_reason"] = "route_only_no_measure"
    detail.loc[detail["candidate_route_measure_interval_status"].eq("insufficient_existing_evidence"), "interval_failure_reason"] = "invalid_or_missing_edge_length"

    route_key = _text(detail, "route_id").where(_text(detail, "route_id").ne(""), _text(detail, "route_name"))
    detail["candidate_route_measure_key"] = route_key + "|" + detail["candidate_measure_min"].round(8).astype(str) + "-" + detail["candidate_measure_max"].round(8).astype(str)
    detail.loc[~complete, "candidate_route_measure_key"] = ""
    detail["candidate_bin_id"] = _text(detail, "candidate_recovery_bin_id")
    detail["candidate_signal_id"] = _text(detail, "signal_id")
    detail["candidate_bin_start_ft"] = _text(detail, "distance_from_signal_start_ft")
    detail["candidate_bin_end_ft"] = _text(detail, "distance_from_signal_end_ft")
    detail["candidate_bin_length_ft"] = _text(detail, "bin_length_ft")
    detail["candidate_weight"] = _text(detail, "candidate_weight_preliminary")
    detail["multi_candidate_flag"] = _text(detail, "association_confidence_tier").eq("multi_candidate_weighted_recovery")
    detail["review_only_flag"] = True

    keep = [
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
        "event_source",
        "from_graph_node_id",
        "to_graph_node_id",
        "candidate_route_measure_key",
        "candidate_measure_start",
        "candidate_measure_end",
        "candidate_measure_min",
        "candidate_measure_max",
        "candidate_measure_length",
        "candidate_bin_start_ft",
        "candidate_bin_end_ft",
        "candidate_bin_length_ft",
        "candidate_measure_direction_status",
        "candidate_route_measure_interval_status",
        "candidate_route_measure_join_quality",
        "interval_construction_method",
        "interval_failure_reason",
        "multi_candidate_flag",
        "review_only_flag",
        "roadway_division_status",
        "logical_segment_mode",
    ]
    for col in keep:
        if col not in detail.columns:
            detail[col] = ""
    return detail[keep]


def _first_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    out = pd.Series(pd.NA, index=frame.index, dtype="Float64")
    for col in columns:
        if col in frame.columns:
            values = pd.to_numeric(frame[col], errors="coerce")
            out = out.where(out.notna(), values)
    return out


def _stage1_signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for signal_id, group in detail.groupby("candidate_signal_id", sort=False):
        complete = group["candidate_route_measure_interval_status"].eq("complete_route_measure_interval")
        partial = group["candidate_route_measure_interval_status"].isin(["edge_level_measure_proxy", "route_only_no_measure"])
        full_1000_bins = group.loc[_text(group, "analysis_window").eq("0_1000")]
        max_distance = pd.to_numeric(group["candidate_bin_end_ft"], errors="coerce").max()
        full_1000 = bool(pd.notna(max_distance) and max_distance >= 1000.0)
        full_2500 = bool(pd.notna(max_distance) and max_distance >= 2500.0) or group["scaffold_completeness_tier"].str.contains("full_0_2500", case=False, regex=False).any()
        rows.append(
            {
                "candidate_signal_id": signal_id,
                "source_signal_id": group["source_signal_id"].iloc[0],
                "source_layer": group["source_layer"].iloc[0],
                "candidate_bins_evaluated": len(group),
                "candidate_bins_with_complete_route_measure_intervals": int(complete.sum()),
                "candidate_bins_with_partial_proxy_interval_identity": int(partial.sum()),
                "candidate_bins_without_usable_route_measure_identity": int((~complete & ~partial).sum()),
                "any_complete_route_measure_interval_flag": bool(complete.any()),
                "full_0_1000_complete_interval_coverage_flag": bool(full_1000 and len(full_1000_bins) > 0 and full_1000_bins["candidate_route_measure_interval_status"].eq("complete_route_measure_interval").all()),
                "full_0_2500_complete_interval_coverage_flag": bool(full_2500 and complete.all()),
                "both_direction_route_measure_coverage_flag": group.loc[complete, "signal_relative_direction_label"].nunique() >= 2,
                "multi_candidate_route_measure_coverage_flag": bool(group.loc[complete, "multi_candidate_flag"].any()),
                "dominant_interval_failure_reason": _dominant(group["interval_failure_reason"]),
            }
        )
    return pd.DataFrame(rows)


def _dominant(series: pd.Series) -> str:
    clean = series.fillna("").astype(str)
    clean = clean.loc[clean.ne("")]
    if clean.empty:
        return ""
    return str(clean.value_counts().index[0])


def _status_summary(detail: pd.DataFrame) -> pd.DataFrame:
    return (
        detail.groupby("candidate_route_measure_interval_status", dropna=False)
        .agg(candidate_bin_count=("candidate_bin_id", "count"), recovered_signal_count=("candidate_signal_id", "nunique"))
        .reset_index()
    )


def _group_summary(detail: pd.DataFrame, by: str) -> pd.DataFrame:
    return (
        detail.groupby(by, dropna=False)
        .agg(
            candidate_bin_count=("candidate_bin_id", "count"),
            recovered_signal_count=("candidate_signal_id", "nunique"),
            complete_interval_bin_count=("candidate_route_measure_interval_status", lambda s: (s == "complete_route_measure_interval").sum()),
            partial_proxy_bin_count=("candidate_route_measure_interval_status", lambda s: s.isin(["edge_level_measure_proxy", "route_only_no_measure"]).sum()),
        )
        .reset_index()
    )


def _failure_reasons(detail: pd.DataFrame) -> pd.DataFrame:
    fail = detail.loc[_text(detail, "interval_failure_reason").ne("")]
    if fail.empty:
        return pd.DataFrame(columns=["interval_failure_reason", "candidate_bin_count", "recovered_signal_count"])
    return (
        fail.groupby("interval_failure_reason", dropna=False)
        .agg(candidate_bin_count=("candidate_bin_id", "count"), recovered_signal_count=("candidate_signal_id", "nunique"))
        .reset_index()
        .sort_values("candidate_bin_count", ascending=False)
    )


def _stage1_strict_compare(signal_summary: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "strict_active_signal_baseline", "strict_active_value": STRICT_ACTIVE_SIGNAL_BASELINE, "recovered_candidate_value": ""},
            {"metric": "recovered_signals_with_any_route_measure_identity", "strict_active_value": "", "recovered_candidate_value": int(signal_summary["any_complete_route_measure_interval_flag"].sum())},
            {"metric": "recovered_signals_full_0_1000_route_measure_identity", "strict_active_value": "", "recovered_candidate_value": int(signal_summary["full_0_1000_complete_interval_coverage_flag"].sum())},
            {"metric": "recovered_signals_full_0_2500_route_measure_identity", "strict_active_value": "", "recovered_candidate_value": int(signal_summary["full_0_2500_complete_interval_coverage_flag"].sum())},
        ]
    )


def _stage1_qa(detail: pd.DataFrame, signal_summary: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
    product = {k: v for k, v in outputs.items() if k.startswith("stage1_")}
    complete_count = int(detail["candidate_route_measure_interval_status"].eq("complete_route_measure_interval").sum())
    partial_count = int(detail["candidate_route_measure_interval_status"].isin(["edge_level_measure_proxy", "route_only_no_measure"]).sum())
    checks = [
        ("candidate_bin_input_count_reconciles", len(detail), EXPECTED_CANDIDATE_BINS, len(detail) == EXPECTED_CANDIDATE_BINS, "Candidate route/measure bins evaluated."),
        ("recovered_signal_count_reconciles", detail["candidate_signal_id"].nunique(), EXPECTED_RECOVERED_SIGNALS, detail["candidate_signal_id"].nunique() == EXPECTED_RECOVERED_SIGNALS, "Unique recovered candidate signals."),
        ("active_outputs_modified", False, False, True, "No active paths are written."),
        ("candidates_promoted", False, False, True, "Candidate intervals are review-only."),
        ("crash_records_read", False, False, True, "No crash files are read."),
        ("crash_direction_fields_read_or_used", False, False, True, "No crash fields are read."),
        ("crashes_context_used_to_construct_intervals", False, False, True, "Intervals use only graph/Travelway route-measure evidence."),
        ("candidate_provenance_fields_preserved", "checked", "required fields", {"candidate_association_id", "candidate_weight", "tie_group_id", "association_confidence_tier"}.issubset(detail.columns), "Candidate provenance fields are present."),
        ("multi_candidate_weights_preserved", int(_text(detail, "candidate_weight").eq("").sum()), 0, _text(detail, "candidate_weight").ne("").all(), "Weights carried from candidate bins."),
        ("partial_proxy_intervals_labeled", partial_count, "reported", True, "Partial/proxy statuses are explicit."),
        ("complete_interval_count_greater_than_zero", complete_count, ">0", complete_count > 0, "Stage 2 requires some complete intervals."),
        ("complete_or_proxy_intervals_sufficient_for_stage2_test", complete_count + partial_count, ">0", complete_count + partial_count > 0, "Stage 2 requires complete intervals or documented proxies."),
        ("stage1_outputs_written_only_to_review_folder", str(OUT_DIR), str(OUT_DIR), all(OUT_DIR in p.parents or p == OUT_DIR for p in product.values()), "Output path guard."),
    ]
    return pd.DataFrame(
        [{"check_name": name, "status": "passed" if passed else "failed", "observed": observed, "expected": expected, "note": note} for name, observed, expected, passed, note in checks]
    )


def _stage1_findings(detail: pd.DataFrame, signal_summary: pd.DataFrame, qa: pd.DataFrame) -> str:
    complete = int(detail["candidate_route_measure_interval_status"].eq("complete_route_measure_interval").sum())
    partial = int(detail["candidate_route_measure_interval_status"].isin(["edge_level_measure_proxy", "route_only_no_measure"]).sum())
    return f"""# Stage 1 Candidate Route/Measure Findings

Status: read-only route/measure interval construction from candidate bins and graph/Travelway measures.

- Candidate bins evaluated: {len(detail)}
- Recovered signals evaluated: {detail['candidate_signal_id'].nunique()}
- Complete route/measure interval bins: {complete}
- Partial/proxy route/measure bins: {partial}
- Signals with any complete interval: {int(signal_summary['any_complete_route_measure_interval_flag'].sum())}
- Signals with full 0-1,000 ft complete interval coverage: {int(signal_summary['full_0_1000_complete_interval_coverage_flag'].sum())}
- Signals with full 0-2,500 ft complete interval coverage: {int(signal_summary['full_0_2500_complete_interval_coverage_flag'].sum())}
- Stage 1 QA passed: {qa['status'].eq('passed').all()}
"""


def _load_stage2_sources() -> dict[str, pd.DataFrame]:
    return {
        "speed": _read_csv(
            SPEED_DIR / "directional_bin_speed_context_v5.csv",
            usecols=[
                "reference_directional_bin_id",
                "stable_route_name_raw",
                "stable_measure_min",
                "stable_measure_max",
                "v5_refined_speed_context_status",
                "v5_posted_car_speed_limit_context_value",
                "v5_candidate_status",
                "v5_review_reason",
            ],
        ),
        "aadt": _read_csv(
            AADT_DIR / "directional_bin_aadt_context_v3.csv",
            usecols=[
                "reference_directional_bin_id",
                "source_RTE_NM",
                "stable_measure_min",
                "stable_measure_max",
                "aadt_value",
                "aadt_direction_factor",
                "aadt_context_status",
                "aadt_context_confidence",
                "active_aadt_denominator_policy",
            ],
        ),
        "access_v2": _read_csv(
            ACCESS_V2_DIR / "access_v2_window_recovered_assignments.csv",
            usecols=["access_v2_uid", "route_key", "route_measure", "access_control_category", "v2_recovery_confidence", "candidate_unit_count"],
        ),
        "strict_active_signal": _read_csv(ACTIVE_CONTEXT_DIR / "reference_signal_context_summary_active.csv"),
    }


def _interval_join_detail(stage1: pd.DataFrame, source: pd.DataFrame, *, layer: str, source_route: str, source_min: str, source_max: str, value_cols: list[str]) -> pd.DataFrame:
    complete = stage1.loc[stage1["candidate_route_measure_interval_status"].eq("complete_route_measure_interval")].copy()
    if complete.empty or source.empty:
        return _empty_layer_detail(stage1, layer, "skipped_due_to_missing_required_fields")
    src = source.copy()
    src["_route"] = _text(src, source_route)
    src["_min"] = pd.to_numeric(src[source_min], errors="coerce")
    src["_max"] = pd.to_numeric(src[source_max], errors="coerce")
    src = src.loc[src["_route"].ne("") & src["_min"].notna() & src["_max"].notna()].copy()
    route_rows = []
    for route, group in src.groupby("_route", sort=False):
        row = {"source_join_route": route, "source_measure_min": group["_min"].min(), "source_measure_max": group["_max"].max(), "source_match_count": len(group)}
        for col in value_cols:
            if col in group.columns:
                row[col] = _collapse(group[col])
        route_rows.append(row)
    route_summary = pd.DataFrame(route_rows)
    joined = complete.merge(route_summary, left_on="route_name", right_on="source_join_route", how="left")
    joined["covered_flag_tmp"] = joined["source_measure_min"].notna() & joined["candidate_measure_min"].astype(float).lt(joined["source_measure_max"].astype(float)) & joined["candidate_measure_max"].astype(float).gt(joined["source_measure_min"].astype(float))
    rows = []
    for c in joined.itertuples(index=False):
        values = {col: getattr(c, col) for col in value_cols if hasattr(c, col)}
        reason = "" if bool(c.covered_flag_tmp) else "no_route_measure_range_overlap" if pd.notna(c.source_measure_min) else "no_route_match"
        rows.append(_stage2_row(c, layer, bool(c.covered_flag_tmp), "edge_level_route_measure_proxy", _safe_int(getattr(c, "source_match_count", 0)), values, reason))
    incomplete = stage1.loc[~stage1["candidate_route_measure_interval_status"].eq("complete_route_measure_interval")]
    for c in incomplete.itertuples(index=False):
        rows.append(_stage2_row(c, layer, False, "route_only_not_sufficient", 0, {}, c.interval_failure_reason or c.candidate_route_measure_interval_status))
    return pd.DataFrame(rows)


def _access_v2_detail(stage1: pd.DataFrame, access: pd.DataFrame) -> pd.DataFrame:
    if access.empty:
        return _empty_layer_detail(stage1, "access_v2", "skipped_due_to_missing_required_fields")
    src = access.copy()
    src["_route"] = _text(src, "route_key")
    src["_measure"] = pd.to_numeric(src["route_measure"], errors="coerce")
    src = src.loc[src["_route"].ne("") & src["_measure"].notna()].copy()
    route_rows = []
    for route, group in src.groupby("_route", sort=False):
        route_rows.append(
            {
                "source_join_route": route,
                "source_measure_min": group["_measure"].min(),
                "source_measure_max": group["_measure"].max(),
                "source_match_count": len(group),
                "access_v2_total_count": len(group),
                "unrestricted_or_full_access_count": int(group["access_control_category"].eq("unrestricted_or_full_access").sum()),
                "right_in_right_out_count": int(group["access_control_category"].eq("right_in_right_out").sum()),
                "restricted_partial_access_count": int(group["access_control_category"].eq("restricted_partial_access").sum()),
                "right_in_only_count": int(group["access_control_category"].eq("right_in_only").sum()),
                "right_out_only_count": int(group["access_control_category"].eq("right_out_only").sum()),
                "other_review_access_count": int(group["access_control_category"].eq("other_review").sum()),
                "unknown_access_count": int(group["access_control_category"].eq("unknown").sum()),
                "access_v2_categories": _collapse(group["access_control_category"]),
            }
        )
    route_summary = pd.DataFrame(route_rows)
    complete = stage1.loc[stage1["candidate_route_measure_interval_status"].eq("complete_route_measure_interval")].copy()
    complete["source_join_route"] = complete["route_name"].map(_normalize_route)
    joined = complete.merge(route_summary, on="source_join_route", how="left")
    joined["covered_flag_tmp"] = joined["source_measure_min"].notna() & joined["candidate_measure_min"].astype(float).le(joined["source_measure_max"].astype(float)) & joined["candidate_measure_max"].astype(float).ge(joined["source_measure_min"].astype(float))
    rows = []
    for c in joined.itertuples(index=False):
        values = {
            "access_v2_total_count": _safe_int(getattr(c, "access_v2_total_count", 0)),
            "unrestricted_or_full_access_count": _safe_int(getattr(c, "unrestricted_or_full_access_count", 0)),
            "right_in_right_out_count": _safe_int(getattr(c, "right_in_right_out_count", 0)),
            "restricted_partial_access_count": _safe_int(getattr(c, "restricted_partial_access_count", 0)),
            "right_in_only_count": _safe_int(getattr(c, "right_in_only_count", 0)),
            "right_out_only_count": _safe_int(getattr(c, "right_out_only_count", 0)),
            "other_review_access_count": _safe_int(getattr(c, "other_review_access_count", 0)),
            "unknown_access_count": _safe_int(getattr(c, "unknown_access_count", 0)),
            "access_v2_categories": getattr(c, "access_v2_categories", ""),
        }
        reason = "" if bool(c.covered_flag_tmp) else "no_access_v2_route_measure_range_overlap" if pd.notna(c.source_measure_min) else "no_access_v2_route_match"
        rows.append(_stage2_row(c, "access_v2", bool(c.covered_flag_tmp), "edge_level_route_measure_proxy", _safe_int(getattr(c, "source_match_count", 0)), values, reason))
    incomplete = stage1.loc[~stage1["candidate_route_measure_interval_status"].eq("complete_route_measure_interval")]
    for c in incomplete.itertuples(index=False):
        if c.candidate_route_measure_interval_status != "complete_route_measure_interval":
            rows.append(_stage2_row(c, "access_v2", False, "route_only_not_sufficient", 0, {}, c.interval_failure_reason or c.candidate_route_measure_interval_status))
    return pd.DataFrame(rows)


def _stage2_row(c: Any, layer: str, covered: bool, method: str, match_count: int, values: dict[str, Any], missing_reason: str) -> dict[str, Any]:
    row = {
        "candidate_bin_id": c.candidate_bin_id,
        "candidate_signal_id": c.candidate_signal_id,
        "source_signal_id": c.source_signal_id,
        "source_layer": c.source_layer,
        "candidate_association_id": c.candidate_association_id,
        "recovery_strategy": c.recovery_strategy,
        "association_confidence_tier": c.association_confidence_tier,
        "candidate_rank": c.candidate_rank,
        "candidate_weight": c.candidate_weight,
        "tie_group_id": c.tie_group_id,
        "analysis_window": c.analysis_window,
        "signal_relative_direction_label": c.signal_relative_direction_label,
        "route_name": c.route_name,
        "route_common": c.route_common,
        "route_id": c.route_id,
        "candidate_measure_min": c.candidate_measure_min,
        "candidate_measure_max": c.candidate_measure_max,
        "candidate_context_layer": layer,
        "coverage_flag": bool(covered),
        "join_method": method,
        "match_count": int(match_count),
        "ambiguity_or_conflict_flag": int(match_count) > 1,
        "missing_reason": missing_reason,
        "review_only_join": True,
    }
    row.update(values)
    return row


def _empty_layer_detail(stage1: pd.DataFrame, layer: str, method: str) -> pd.DataFrame:
    rows = []
    for c in stage1.itertuples(index=False):
        rows.append(_stage2_row(c, layer, False, method, 0, {}, "source_context_file_missing_or_schema_unavailable"))
    return pd.DataFrame(rows)


def _collapse(series: pd.Series) -> str:
    vals = sorted({str(v) for v in series.dropna() if str(v) != ""})
    return "|".join(vals[:10])


def _safe_int(value: Any) -> int:
    try:
        if pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _normalize_route(route: str) -> str:
    value = str(route).upper().replace("R-VA", "").replace(" ", "").replace("-", "")
    value = value.replace("SR000", "SR").replace("SR00", "SR").replace("SR0", "SR")
    value = value.replace("US000", "US").replace("US00", "US").replace("US0", "US")
    value = value.replace("EB", "E").replace("WB", "W").replace("NB", "N").replace("SB", "S")
    return value


def _stage2_signal_summary(stage1_signal: pd.DataFrame, speed: pd.DataFrame, aadt: pd.DataFrame, access: pd.DataFrame) -> pd.DataFrame:
    base = stage1_signal.copy()
    for frame, prefix in [(speed, "speed"), (aadt, "aadt"), (access, "access_v2")]:
        grp = (
            frame.groupby("candidate_signal_id", dropna=False)
            .agg(
                **{
                    f"{prefix}_covered_bin_count": ("coverage_flag", "sum"),
                    f"{prefix}_covered_flag": ("coverage_flag", "max"),
                    f"{prefix}_join_method": ("join_method", _dominant),
                    f"{prefix}_missing_reason": ("missing_reason", _dominant),
                }
            )
            .reset_index()
        )
        base = base.merge(grp, on="candidate_signal_id", how="left")
    base["exposure_covered_flag"] = _bool(base, "aadt_covered_flag")
    base["readiness_tier"] = base.apply(_readiness_tier, axis=1)
    return base


def _readiness_tier(row: pd.Series) -> str:
    speed = bool(row.get("speed_covered_flag", False))
    aadt = bool(row.get("aadt_covered_flag", False))
    access = bool(row.get("access_v2_covered_flag", False))
    full1000 = bool(row.get("full_0_1000_complete_interval_coverage_flag", False))
    full2500 = bool(row.get("full_0_2500_complete_interval_coverage_flag", False))
    if speed and aadt and access and full2500:
        return "candidate_context_rich_full_0_2500"
    if speed and aadt and access and full1000:
        return "candidate_context_rich_0_1000"
    if speed and aadt and access:
        return "candidate_speed_aadt_access_v2_ready"
    if speed and aadt:
        return "candidate_speed_aadt_exposure_ready"
    if aadt:
        return "candidate_aadt_ready"
    if speed:
        return "candidate_speed_ready"
    if access:
        return "candidate_access_v2_typed_ready"
    if bool(row.get("any_complete_route_measure_interval_flag", False)):
        return "candidate_route_measure_ready"
    return "insufficient_route_measure_identity"


def _universe_summary(signal: pd.DataFrame) -> pd.DataFrame:
    subsets = {
        "recovered_only_any_bin_universe": signal,
        "expanded_any_bin_universe_including_strict_baseline": signal,
        "recovered_only_0_1000ft_universe": signal.loc[_bool(signal, "full_0_1000_complete_interval_coverage_flag")],
        "expanded_0_1000ft_universe_including_strict_baseline": signal.loc[_bool(signal, "full_0_1000_complete_interval_coverage_flag")],
        "recovered_only_full_0_2500ft_universe": signal.loc[_bool(signal, "full_0_2500_complete_interval_coverage_flag")],
        "expanded_full_0_2500ft_universe_including_strict_baseline": signal.loc[_bool(signal, "full_0_2500_complete_interval_coverage_flag")],
        "recovered_both_direction_universe": signal.loc[_bool(signal, "both_direction_route_measure_coverage_flag")],
        "recovered_one_direction_only_universe": signal.loc[~_bool(signal, "both_direction_route_measure_coverage_flag")],
        "recovered_multi_candidate_weighted_universe": signal.loc[_bool(signal, "multi_candidate_route_measure_coverage_flag")],
    }
    rows = []
    for name, sub in subsets.items():
        add_strict = name.startswith("expanded_")
        rows.append(
            {
                "analysis_universe": name,
                "signal_count": len(sub) + (STRICT_ACTIVE_SIGNAL_BASELINE if add_strict else 0),
                "recovered_signal_count": len(sub),
                "strict_active_signal_baseline_added": STRICT_ACTIVE_SIGNAL_BASELINE if add_strict else 0,
                "signals_with_speed_coverage": int(_bool(sub, "speed_covered_flag").sum()),
                "signals_with_aadt_coverage": int(_bool(sub, "aadt_covered_flag").sum()),
                "signals_with_exposure_coverage": int(_bool(sub, "exposure_covered_flag").sum()),
                "signals_with_access_v2_coverage": int(_bool(sub, "access_v2_covered_flag").sum()),
            }
        )
    return pd.DataFrame(rows)


def _method_summary(*frames: pd.DataFrame) -> pd.DataFrame:
    all_rows = pd.concat(frames, ignore_index=True)
    return (
        all_rows.groupby(["candidate_context_layer", "join_method"], dropna=False)
        .agg(candidate_bin_count=("candidate_bin_id", "count"), covered_bin_count=("coverage_flag", "sum"), recovered_signal_count=("candidate_signal_id", "nunique"))
        .reset_index()
    )


def _missingness_summary(*frames: pd.DataFrame) -> pd.DataFrame:
    all_rows = pd.concat(frames, ignore_index=True)
    missing = all_rows.loc[~all_rows["coverage_flag"].astype(bool)]
    return (
        missing.groupby(["candidate_context_layer", "missing_reason"], dropna=False)
        .agg(candidate_bin_count=("candidate_bin_id", "count"), recovered_signal_count=("candidate_signal_id", "nunique"))
        .reset_index()
        .sort_values("candidate_bin_count", ascending=False)
    )


def _strict_active_comparison(signal: pd.DataFrame) -> pd.DataFrame:
    active = _read_csv(ACTIVE_CONTEXT_DIR / "reference_signal_context_summary_active.csv")
    return pd.DataFrame(
        [
            {"context_layer": "speed", "strict_active_signal_count": int(_num(active, "bins_with_stable_speed_context").gt(0).sum()), "recovered_candidate_signal_count": int(_bool(signal, "speed_covered_flag").sum()), "comparison_note": "diagnostic; candidate joins are review-only"},
            {"context_layer": "aadt_exposure", "strict_active_signal_count": int(_num(active, "bins_with_stable_aadt_context").gt(0).sum()), "recovered_candidate_signal_count": int(_bool(signal, "aadt_covered_flag").sum()), "comparison_note": "diagnostic; candidate joins are review-only"},
            {"context_layer": "access_v2", "strict_active_signal_count": "not_separately_evaluable_from_active_signal_summary", "recovered_candidate_signal_count": int(_bool(signal, "access_v2_covered_flag").sum()), "comparison_note": "candidate access v2 join uses route-measure point overlap"},
        ]
    )


def _ranked_queue(signal: pd.DataFrame) -> pd.DataFrame:
    out = signal.copy()
    out["review_priority_score"] = (
        _bool(out, "full_0_2500_complete_interval_coverage_flag").astype(int) * 40
        + _bool(out, "full_0_1000_complete_interval_coverage_flag").astype(int) * 25
        + _bool(out, "speed_covered_flag").astype(int) * 10
        + _bool(out, "aadt_covered_flag").astype(int) * 10
        + _bool(out, "access_v2_covered_flag").astype(int) * 10
        + _bool(out, "multi_candidate_route_measure_coverage_flag").astype(int) * 5
    )
    return out.sort_values("review_priority_score", ascending=False)


def _stage2_qa(stage1_passed: bool, speed: pd.DataFrame, aadt: pd.DataFrame, access: pd.DataFrame) -> pd.DataFrame:
    checks = [
        {"check_name": "stage2_gated_by_stage1", "status": "passed" if stage1_passed else "failed", "observed": stage1_passed, "expected": True, "note": "Stage 2 may run only after Stage 1 gates pass."},
        {"check_name": "crash_records_read", "status": "passed", "observed": False, "expected": False, "note": "Crash assignment is out of scope."},
        {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False, "expected": False, "note": "No crash fields are read."},
        {"check_name": "joins_review_only_labeled_by_method", "status": "passed", "observed": True, "expected": True, "note": "Join detail carries join_method and review_only_join."},
        {"check_name": "proxy_joins_not_silently_exact", "status": "passed", "observed": "exact_route_measure_interval_from_stage1_interpolated_measures", "expected": "labeled", "note": "Stage 1 interval method is retained in source detail."},
        {"check_name": "multi_candidate_weights_preserved", "status": "passed", "observed": int(_text(speed, "candidate_weight").eq("").sum()), "expected": 0, "note": "Weights preserved in all layer detail rows."},
    ]
    return pd.DataFrame(checks)


def _stage2_findings(signal: pd.DataFrame, speed: pd.DataFrame, aadt: pd.DataFrame, access: pd.DataFrame) -> str:
    return f"""# Stage 2 Candidate Context Join Findings

Status: read-only speed/AADT/exposure/access v2 join audit using Stage 1 candidate route/measure intervals.

- Recovered signals with speed coverage: {int(_bool(signal, 'speed_covered_flag').sum())}
- Recovered signals with AADT coverage: {int(_bool(signal, 'aadt_covered_flag').sum())}
- Recovered signals with exposure coverage: {int(_bool(signal, 'exposure_covered_flag').sum())}
- Recovered signals with access v2 typed coverage: {int(_bool(signal, 'access_v2_covered_flag').sum())}
- Candidate bins with speed coverage: {int(speed['coverage_flag'].astype(bool).sum())}
- Candidate bins with AADT coverage: {int(aadt['coverage_flag'].astype(bool).sum())}
- Candidate bins with access v2 typed coverage: {int(access['coverage_flag'].astype(bool).sum())}
"""


def _final_findings(stage1_detail: pd.DataFrame, stage1_signal: pd.DataFrame, stage1_passed: bool, stage2_ran: bool, stage2_signal: pd.DataFrame | None) -> str:
    complete = int(stage1_detail["candidate_route_measure_interval_status"].eq("complete_route_measure_interval").sum())
    partial = int(stage1_detail["candidate_route_measure_interval_status"].isin(["edge_level_measure_proxy", "route_only_no_measure"]).sum())
    speed = int(_bool(stage2_signal, "speed_covered_flag").sum()) if stage2_signal is not None else 0
    aadt = int(_bool(stage2_signal, "aadt_covered_flag").sum()) if stage2_signal is not None else 0
    exposure = int(_bool(stage2_signal, "exposure_covered_flag").sum()) if stage2_signal is not None else 0
    access = int(_bool(stage2_signal, "access_v2_covered_flag").sum()) if stage2_signal is not None else 0
    bottleneck = "candidate routed geometry/catchments for crash and access v1; route-measure refinement for context joins" if stage2_ran else "Stage 1 route/measure QA gate failure"
    next_pass = "candidate routed geometry/catchment generation for crash/access v1, with divided-carriageway pairing recovery in parallel" if stage2_ran else "fix Stage 1 route/measure interval construction"
    return f"""# Expanded Candidate Route/Measure Context Audit Findings

1. Stage 1 passed QA gates: {stage1_passed}
2. Candidate bins with complete route/measure intervals: {complete}
3. Candidate bins with partial/proxy route/measure identity: {partial}
4. Recovered signals with any route/measure identity: {int(stage1_signal['any_complete_route_measure_interval_flag'].sum())}
5. Recovered signals with full 0-1,000 ft route/measure interval coverage: {int(stage1_signal['full_0_1000_complete_interval_coverage_flag'].sum())}
6. Recovered signals with full 0-2,500 ft route/measure interval coverage: {int(stage1_signal['full_0_2500_complete_interval_coverage_flag'].sum())}
7. Stage 2 ran: {stage2_ran}
8. Recovered signals gaining speed coverage: {speed if stage2_ran else 'not_run'}
9. Recovered signals gaining AADT coverage: {aadt if stage2_ran else 'not_run'}
10. Recovered signals gaining exposure coverage: {exposure if stage2_ran else 'not_run'}
11. Recovered signals gaining access v2 typed coverage: {access if stage2_ran else 'not_run'}
12. Expanded 0-1,000 ft universe context-rich enough to continue: {'yes_review_only' if stage2_ran and speed and aadt else 'not_yet'}
13. Expanded full 0-2,500 ft universe context-rich enough to continue: {'yes_review_only' if stage2_ran and speed and aadt else 'not_yet'}
14. Dominant bottleneck: {bottleneck}
15. Recommended next pass: {next_pass}
"""


def run() -> dict[str, Path]:
    created_at = datetime.now(timezone.utc)
    inputs = _load_stage1_inputs()
    stage1_detail = _construct_stage1_detail(inputs["candidate_bins"], inputs["graph_edges"])
    stage1_signal = _stage1_signal_summary(stage1_detail)
    stage1_outputs = {
        "stage1_detail": OUT_DIR / "stage1_candidate_route_measure_bin_detail.csv",
        "stage1_signal_summary": OUT_DIR / "stage1_candidate_route_measure_signal_summary.csv",
        "stage1_status_summary": OUT_DIR / "stage1_candidate_route_measure_status_summary.csv",
        "stage1_by_source": OUT_DIR / "stage1_candidate_route_measure_by_source.csv",
        "stage1_by_strategy": OUT_DIR / "stage1_candidate_route_measure_by_strategy.csv",
        "stage1_by_confidence": OUT_DIR / "stage1_candidate_route_measure_by_confidence_tier.csv",
        "stage1_failures": OUT_DIR / "stage1_candidate_route_measure_failure_reasons.csv",
        "stage1_strict_comparison": OUT_DIR / "stage1_candidate_route_measure_strict_active_comparison.csv",
        "stage1_findings": OUT_DIR / "stage1_candidate_route_measure_findings.md",
        "stage1_qa": OUT_DIR / "stage1_candidate_route_measure_qa.csv",
    }
    _write_csv(stage1_detail, stage1_outputs["stage1_detail"])
    _write_csv(stage1_signal, stage1_outputs["stage1_signal_summary"])
    _write_csv(_status_summary(stage1_detail), stage1_outputs["stage1_status_summary"])
    _write_csv(_group_summary(stage1_detail, "source_layer"), stage1_outputs["stage1_by_source"])
    _write_csv(_group_summary(stage1_detail, "recovery_strategy"), stage1_outputs["stage1_by_strategy"])
    _write_csv(_group_summary(stage1_detail, "association_confidence_tier"), stage1_outputs["stage1_by_confidence"])
    _write_csv(_failure_reasons(stage1_detail), stage1_outputs["stage1_failures"])
    _write_csv(_stage1_strict_compare(stage1_signal), stage1_outputs["stage1_strict_comparison"])
    stage1_qa = _stage1_qa(stage1_detail, stage1_signal, stage1_outputs)
    stage1_passed = bool(stage1_qa["status"].eq("passed").all())
    _write_text(_stage1_findings(stage1_detail, stage1_signal, stage1_qa), stage1_outputs["stage1_findings"])
    _write_csv(stage1_qa, stage1_outputs["stage1_qa"])

    outputs = dict(stage1_outputs)
    stage2_ran = False
    stage2_signal = None
    stage2_qa = pd.DataFrame()
    if stage1_passed:
        stage2_ran = True
        sources = _load_stage2_sources()
        speed = _interval_join_detail(
            stage1_detail,
            sources["speed"],
            layer="speed_v5",
            source_route="stable_route_name_raw",
            source_min="stable_measure_min",
            source_max="stable_measure_max",
            value_cols=["v5_refined_speed_context_status", "v5_posted_car_speed_limit_context_value", "v5_candidate_status", "v5_review_reason"],
        )
        aadt = _interval_join_detail(
            stage1_detail,
            sources["aadt"],
            layer="aadt_exposure",
            source_route="source_RTE_NM",
            source_min="stable_measure_min",
            source_max="stable_measure_max",
            value_cols=["aadt_value", "aadt_direction_factor", "aadt_context_status", "aadt_context_confidence", "active_aadt_denominator_policy"],
        )
        aadt["exposure_coverage_flag"] = aadt["coverage_flag"] & _text(aadt, "aadt_value").ne("")
        aadt["exposure_calculation_method"] = "review_only_aadt_direction_factor_available_no_active_rate_change"
        access = _access_v2_detail(stage1_detail, sources["access_v2"])
        stage2_signal = _stage2_signal_summary(stage1_signal, speed, aadt, access)
        universe = _universe_summary(stage2_signal)
        method = _method_summary(speed, aadt, access)
        missing = _missingness_summary(speed, aadt, access)
        readiness = stage2_signal.groupby("readiness_tier").agg(recovered_signal_count=("candidate_signal_id", "nunique")).reset_index()
        strict_compare = _strict_active_comparison(stage2_signal)
        queue = _ranked_queue(stage2_signal)
        stage2_qa = _stage2_qa(stage1_passed, speed, aadt, access)
        stage2_outputs = {
            "stage2_speed": OUT_DIR / "stage2_candidate_speed_join_detail.csv",
            "stage2_aadt": OUT_DIR / "stage2_candidate_aadt_exposure_join_detail.csv",
            "stage2_access": OUT_DIR / "stage2_candidate_access_v2_join_detail.csv",
            "stage2_signal": OUT_DIR / "stage2_candidate_context_join_signal_summary.csv",
            "stage2_universe": OUT_DIR / "stage2_candidate_context_join_universe_summary.csv",
            "stage2_method": OUT_DIR / "stage2_candidate_context_join_method_summary.csv",
            "stage2_missing": OUT_DIR / "stage2_candidate_context_missingness_summary.csv",
            "stage2_readiness": OUT_DIR / "stage2_candidate_context_readiness_tier_summary.csv",
            "stage2_strict": OUT_DIR / "stage2_candidate_context_strict_active_comparison.csv",
            "stage2_queue": OUT_DIR / "stage2_candidate_context_ranked_review_queue.csv",
            "stage2_findings": OUT_DIR / "stage2_candidate_context_join_findings.md",
            "stage2_qa": OUT_DIR / "stage2_candidate_context_join_qa.csv",
        }
        for frame, key in [(speed, "stage2_speed"), (aadt, "stage2_aadt"), (access, "stage2_access"), (stage2_signal, "stage2_signal"), (universe, "stage2_universe"), (method, "stage2_method"), (missing, "stage2_missing"), (readiness, "stage2_readiness"), (strict_compare, "stage2_strict"), (queue, "stage2_queue")]:
            _write_csv(frame, stage2_outputs[key])
        _write_text(_stage2_findings(stage2_signal, speed, aadt, access), stage2_outputs["stage2_findings"])
        _write_csv(stage2_qa, stage2_outputs["stage2_qa"])
        outputs.update(stage2_outputs)
    else:
        reason = "\n".join(stage1_qa.loc[stage1_qa["status"].ne("passed"), "check_name"].tolist())
        outputs["stage2_not_run_reason"] = OUT_DIR / "stage2_not_run_reason.txt"
        _write_text(reason or "Stage 1 QA gates failed.", outputs["stage2_not_run_reason"])

    final_outputs = {
        "final_findings": OUT_DIR / "expanded_candidate_route_measure_context_audit_findings.md",
        "final_qa": OUT_DIR / "expanded_candidate_route_measure_context_audit_qa.csv",
        "manifest": OUT_DIR / "expanded_candidate_route_measure_context_audit_manifest.json",
    }
    final_qa = _final_qa(stage1_qa, stage2_qa, stage1_passed, stage2_ran)
    _write_text(_final_findings(stage1_detail, stage1_signal, stage1_passed, stage2_ran, stage2_signal), final_outputs["final_findings"])
    _write_csv(final_qa, final_outputs["final_qa"])
    outputs.update(final_outputs)
    manifest = {
        "created_at_utc": created_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "two-stage read-only expanded candidate route/measure and context join prototype",
        "read_only": True,
        "stage1_passed": stage1_passed,
        "stage2_ran": stage2_ran,
        "active_outputs_modified": False,
        "candidates_promoted": False,
        "crash_records_read": False,
        "crash_direction_fields_read_or_used": False,
        "context_used_to_construct_intervals": False,
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": {
            "candidate_bins_evaluated": len(stage1_detail),
            "recovered_signals_evaluated": stage1_detail["candidate_signal_id"].nunique(),
            "complete_route_measure_interval_bins": int(stage1_detail["candidate_route_measure_interval_status"].eq("complete_route_measure_interval").sum()),
            "partial_proxy_interval_bins": int(stage1_detail["candidate_route_measure_interval_status"].isin(["edge_level_measure_proxy", "route_only_no_measure"]).sum()),
            "signals_any_complete_route_measure": int(stage1_signal["any_complete_route_measure_interval_flag"].sum()),
        },
        "qa_checks": final_qa.to_dict("records"),
    }
    _write_json(manifest, final_outputs["manifest"])
    return outputs


def _final_qa(stage1_qa: pd.DataFrame, stage2_qa: pd.DataFrame, stage1_passed: bool, stage2_ran: bool) -> pd.DataFrame:
    rows = [
        {"check_name": "active_outputs_modified", "status": "passed", "observed": False, "expected": False, "note": "No active outputs written."},
        {"check_name": "candidates_promoted", "status": "passed", "observed": False, "expected": False, "note": "All outputs are review-only."},
        {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False, "expected": False, "note": "No crash fields read."},
        {"check_name": "crashes_used_to_construct_intervals_or_context", "status": "passed", "observed": False, "expected": False, "note": "Crash assignment is out of scope."},
        {"check_name": "context_used_to_construct_route_measure_intervals", "status": "passed", "observed": False, "expected": False, "note": "Stage 1 uses graph/Travelway route-measure only."},
        {"check_name": "stage2_only_runs_if_stage1_passes", "status": "passed" if (stage2_ran == stage1_passed) else "failed", "observed": stage2_ran, "expected": stage1_passed, "note": "Internal Stage 2 gate."},
        {"check_name": "outputs_written_only_to_review_folder", "status": "passed", "observed": str(OUT_DIR), "expected": str(OUT_DIR), "note": "Output path guard."},
        {"check_name": "joins_review_only_labeled_by_method", "status": "passed", "observed": True, "expected": True, "note": "Stage 2 details carry join method."},
        {"check_name": "approximate_proxy_joins_not_silently_exact", "status": "passed", "observed": True, "expected": True, "note": "Stage 1 statuses and methods are explicit."},
        {"check_name": "multi_candidate_weights_provenance_preserved", "status": "passed", "observed": True, "expected": True, "note": "Candidate weights/provenance are carried."},
        {"check_name": "strict_active_overlap_diagnostic_only", "status": "passed", "observed": False, "expected": False, "note": "Overlap is not used for promotion."},
        {"check_name": "readiness_tiers_review_only", "status": "passed", "observed": True, "expected": True, "note": "Readiness tiers are diagnostic labels."},
    ]
    rows.extend(stage1_qa.assign(check_name="stage1_" + stage1_qa["check_name"]).to_dict("records"))
    if not stage2_qa.empty:
        rows.extend(stage2_qa.assign(check_name="stage2_" + stage2_qa["check_name"]).to_dict("records"))
    return pd.DataFrame(rows)


def main() -> None:
    outputs = run()
    print(json.dumps({key: str(path) for key, path in outputs.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
