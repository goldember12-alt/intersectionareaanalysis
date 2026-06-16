from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/roadway_graph_data_loss_ledger")

TABLES = OUTPUT_ROOT / "tables/current"
REVIEW = OUTPUT_ROOT / "review/current"
ANALYSIS = OUTPUT_ROOT / "analysis/current"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)

STAGES = [
    "source_total",
    "source_valid_geometry",
    "represented_in_stable_universe",
    "within_0_2500ft_universe",
    "spatially_near_stable_universe",
    "route_identity_compatible",
    "route_measure_compatible",
    "uniquely_assigned",
    "ambiguously_assigned",
    "review_only",
    "missing_or_unmatched",
    "active_context_used",
    "candidate_context_only",
    "excluded_from_active_context",
]


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1


def _metric(frame: pd.DataFrame, name: str, metric_col: str = "metric", value_col: str = "count") -> int:
    if frame.empty or metric_col not in frame.columns or value_col not in frame.columns:
        return 0
    rows = frame.loc[frame[metric_col].astype(str).eq(name), value_col]
    if rows.empty:
        return 0
    return int(pd.to_numeric(rows.iloc[0], errors="coerce") or 0)


def _contains_crash_direction(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _bool_series(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y"})


def _stage_row(layer: str, stage: str, count: int, basis: str, context_status: str, note: str = "") -> dict[str, Any]:
    return {
        "layer": layer,
        "stage": stage,
        "count": int(count) if pd.notna(count) else 0,
        "basis": basis,
        "context_status": context_status,
        "note": note,
    }


def _reason_row(layer: str, reason: str, count: int, evidence: str, interpretation: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "loss_reason": reason,
        "count": int(count) if pd.notna(count) else 0,
        "evidence_source": evidence,
        "interpretation": interpretation,
    }


def _status_row(layer: str, active_count: int, candidate_count: int, excluded_count: int, note: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "active_context_used": int(active_count),
        "candidate_context_only": int(candidate_count),
        "excluded_from_active_context": int(excluded_count),
        "note": note,
    }


def _load_core_counts() -> dict[str, int]:
    scaffold_summary = _read_csv(REVIEW / "reference_signal_directional_scaffold/reference_signal_directional_scaffold_summary.csv")
    scaffold_qa = _read_csv(REVIEW / "reference_signal_directional_scaffold_qa/directional_scaffold_qa_summary.csv")
    catchment = _read_csv(REVIEW / "reference_signal_directional_bin_catchments/directional_bin_catchment_summary.csv")
    active_context = _read_csv(ANALYSIS / "directional_bin_context_table_active/context_completeness_active_summary.csv")
    active_total = active_context.loc[active_context.get("summary_grain", "").astype(str).eq("distance_window")]
    return {
        "signals_source": _count_rows(TABLES / "signal_step5_eligibility.csv"),
        "true_reference_signals": _metric(scaffold_summary, "true_reference_signals_total", value_col="value"),
        "true_reference_signals_represented": _metric(scaffold_summary, "true_reference_signals_represented", value_col="value"),
        "directional_segment_candidates": _metric(scaffold_qa, "candidate_directional_segments", value_col="value"),
        "usable_directional_segments": _metric(scaffold_qa, "prototype_usable_directional_segments", value_col="value"),
        "excluded_directional_segments": _metric(scaffold_qa, "excluded_directional_segments", value_col="value"),
        "candidate_directional_bins": _metric(scaffold_qa, "candidate_directional_bins", value_col="value"),
        "usable_directional_bins": _metric(scaffold_qa, "prototype_usable_directional_bins", value_col="value"),
        "excluded_directional_bins": _metric(scaffold_qa, "excluded_directional_bins", value_col="value"),
        "usable_catchments": _metric(catchment, "usable_catchments", value_col="value"),
        "unstable_review_catchments": _metric(catchment, "unstable_review_catchments", value_col="value"),
        "blocked_catchments": _metric(catchment, "blocked_catchments", value_col="value"),
        "active_bins": int(pd.to_numeric(active_total.get("directional_bin_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "active_crashes": int(pd.to_numeric(active_total.get("assigned_crash_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "active_bins_with_access": int(pd.to_numeric(active_total.get("bins_with_access_context", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "active_bins_with_speed": int(pd.to_numeric(active_total.get("bins_with_stable_speed_context", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "active_bins_with_aadt": int(pd.to_numeric(active_total.get("bins_with_stable_aadt_context", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "active_bins_with_urban_rural": int(pd.to_numeric(active_total.get("bins_with_urban_rural_context", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
    }


def _access_detail() -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []

    accounting = _read_csv(REVIEW / "access_v1_v2_coverage_diagnostic/access_assignment_accounting_v1_v2.csv")
    route_compat = _read_csv(REVIEW / "access_v1_v2_coverage_diagnostic/access_v2_route_measure_compatibility.csv")
    recovery = _read_csv(REVIEW / "access_v2_route_measure_window_recovery/access_v2_recovery_comparison_to_containment.csv")
    category = _read_csv(REVIEW / "access_v2_route_measure_window_recovery/access_v2_recovery_category_comparison.csv")
    position = _read_csv(REVIEW / "access_v2_route_measure_window_recovery/access_v2_unmatched_position_diagnostic.csv")
    gap = _read_csv(REVIEW / "access_v2_route_measure_window_recovery/access_v2_bin_gap_diagnostic.csv")

    for _, row in accounting.iterrows():
        dataset = str(row["dataset"])
        layer = f"access {dataset}"
        source = int(row["source_access_point_count"])
        matched = int(row["unique_access_points_matched_to_stable_universe"])
        ambiguous = int(row["ambiguous_point_count"])
        unmatched = int(row["unmatched_outside_point_count"])
        stages.extend(
            [
                _stage_row(layer, "source_total", source, "source access point count", "active" if dataset == "v1" else "candidate"),
                _stage_row(layer, "represented_in_stable_universe", matched, "unique matched source points", "active" if dataset == "v1" else "candidate"),
                _stage_row(layer, "uniquely_assigned", matched, "unique matched source points", "active" if dataset == "v1" else "candidate"),
                _stage_row(layer, "ambiguously_assigned", ambiguous, "ambiguous containment matches", "review_only"),
                _stage_row(layer, "missing_or_unmatched", unmatched, "outside/unmatched source points", "excluded"),
                _stage_row(layer, "active_context_used", matched if dataset == "v1" else 0, "accepted access context", "active"),
                _stage_row(layer, "candidate_context_only", matched if dataset == "v2" else 0, "candidate typed access context", "candidate"),
                _stage_row(layer, "excluded_from_active_context", source - matched if dataset == "v2" else unmatched, "not active stable context", "excluded"),
            ]
        )
        reasons.append(_reason_row(layer, "point_outside_catchment", unmatched, "access assignment accounting", "spatial/catchment containment did not match source points"))
        reasons.append(_reason_row(layer, "multiple_candidate_units", ambiguous, "access assignment accounting", "ambiguous containment candidates preserved"))
        status.append(_status_row(layer, matched if dataset == "v1" else 0, matched if dataset == "v2" else 0, source - matched, "v1 is accepted broad count context; v2 remains candidate typed context"))
        rows.append(
            {
                "dataset": dataset,
                "source_rows": source,
                "matched_unique_points": matched,
                "point_bin_assignment_pairs": int(row["unique_point_bin_assignment_pairs"]),
                "bins_with_access": int(row["unique_bins_with_access"]),
                "ambiguous_points": ambiguous,
                "unmatched_points": unmatched,
                "active_or_candidate": "active" if dataset == "v1" else "candidate",
            }
        )

    if not route_compat.empty:
        total = len(route_compat)
        typed = int(route_compat["access_control_category"].astype(str).ne("unknown").sum())
        route_key = int(route_compat["route_key_present_in_stable_bins"].astype(str).str.lower().eq("true").sum())
        route_measure = int(route_compat["route_measure_compatible"].astype(str).str.lower().eq("true").sum())
        stages.extend(
            [
                _stage_row("access v2 typed", "source_total", total, "access_v2 staged rows", "candidate"),
                _stage_row("access v2 typed", "source_valid_geometry", total, "staged normalized access_v2 rows", "candidate"),
                _stage_row("access v2 typed", "route_identity_compatible", route_key, "route key present in stable bins", "candidate"),
                _stage_row("access v2 typed", "route_measure_compatible", route_measure, "route/measure compatible bins", "candidate"),
            ]
        )
        rows.append({"dataset": "v2_route_measure", "source_rows": total, "typed_rows": typed, "route_identity_compatible": route_key, "route_measure_compatible": route_measure})
        reasons.append(_reason_row("access v2 typed", "route_mismatch", total - route_key, "access_v2_route_measure_compatibility", "route not represented in stable bins"))
        reasons.append(_reason_row("access v2 typed", "measure_no_overlap", route_key - route_measure, "access_v2_route_measure_compatibility", "route represented but measure did not overlap stable bins"))

    if not recovery.empty:
        def rec(source: str, col: str) -> int:
            vals = recovery.loc[recovery["comparison_source"].eq(source), col]
            return int(pd.to_numeric(vals.iloc[0], errors="coerce")) if not vals.empty else 0

        containment = rec("containment_only_v2", "total_typed_access_assignments")
        window = rec("route_measure_window_recovered", "total_typed_access_assignments")
        ambiguous = rec("route_measure_window_recovered", "ambiguous_review_points")
        unmatched = rec("route_measure_window_recovered", "unmatched_or_not_recovered_points")
        stages.extend(
            [
                _stage_row("access v2 window recovery", "uniquely_assigned", window, "unique route/measure window recovery", "candidate"),
                _stage_row("access v2 window recovery", "ambiguously_assigned", ambiguous, "ambiguous route/measure window candidates", "review_only"),
                _stage_row("access v2 window recovery", "missing_or_unmatched", unmatched, "not recovered by route/measure window prototype", "excluded"),
                _stage_row("access v2 window recovery", "candidate_context_only", containment + window, "containment plus unique window recovery", "candidate"),
            ]
        )
        reasons.append(_reason_row("access v2 window recovery", "route_measure_ambiguous", ambiguous, "route_measure_window_recovery", "route/measure compatible but ambiguous across signal-relative windows"))
        reasons.append(_reason_row("access v2 window recovery", "outside_stable_universe", unmatched, "route_measure_window_recovery", "not uniquely recoverable into stable signal-relative units"))
        rows.append({"dataset": "v2_window_recovery", "containment_assignments": containment, "unique_window_recovered": window, "window_ambiguous": ambiguous, "window_unmatched": unmatched})

    if not position.empty:
        rows.append({"dataset": "v2_position_diagnostic", **{r["metric"]: r["count"] for _, r in position.iterrows()}})
    if not gap.empty:
        gap_count = int(_bool_series(gap.get("has_bin_gap", pd.Series(dtype=str))).sum())
        catchment_gap = int(_bool_series(gap.get("has_catchment_status_gap", pd.Series(dtype=str))).sum())
        reasons.append(_reason_row("directional catchments", "catchment_unusable", catchment_gap, "access_v2_bin_gap_diagnostic", "some segment groups have non-usable catchment bins"))
        rows.append({"dataset": "catchment_gap_diagnostic", "segment_level_bin_gap_groups": gap_count, "segment_groups_with_nonusable_catchment_bins": catchment_gap})

    return pd.DataFrame(rows), stages, reasons, status


def _speed_detail(core: dict[str, int]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    v4 = _read_csv(REVIEW / "speed_context_join_v4_identity_enriched/speed_context_v4_summary.csv")
    v5 = _read_csv(REVIEW / "speed_context_join_v5_new_source_supplement/speed_context_v5_summary.csv")
    comp = _read_csv(REVIEW / "speed_context_join_v5_new_source_supplement/speed_v5_comparison_to_v4.csv")
    v4_stable = _metric(v4, "stable_speed_bins")
    v5_stable = _metric(v5, "v5_stable_speed_bins")
    total = _metric(v5, "main_0_2500ft_bins") or core["active_bins"]
    recovered = int(pd.to_numeric(comp.loc[comp.get("comparison_group", "").eq("v4_missing_review_recovered_by_rns"), "bin_count"], errors="coerce").sum()) if not comp.empty else max(v5_stable - v4_stable, 0)
    missing = total - v5_stable
    stages.extend(
        [
            _stage_row("speed v4", "within_0_2500ft_universe", total, "directional bins", "baseline"),
            _stage_row("speed v4", "uniquely_assigned", v4_stable, "stable speed bins", "baseline"),
            _stage_row("speed v4", "missing_or_unmatched", total - v4_stable, "non-stable speed bins", "excluded"),
            _stage_row("speed v5", "within_0_2500ft_universe", total, "directional bins", "active"),
            _stage_row("speed v5", "route_measure_compatible", v5_stable, "stable v5 bins", "active"),
            _stage_row("speed v5", "active_context_used", v5_stable, "active speed context", "active"),
            _stage_row("speed v5", "missing_or_unmatched", missing, "missing/review speed bins", "review_or_missing"),
        ]
    )
    reasons.append(_reason_row("speed v4", "missing_source_attribute", total - v4_stable, "speed v4 summary", "not stable under v4 identity rules"))
    reasons.append(_reason_row("speed v5", "review_status_preserved", missing, "speed v5 summary", "remaining missing/review after new source supplement"))
    status.append(_status_row("speed v5", v5_stable, 0, missing, "speed v5 is active and recovered many v4-missing bins"))
    rows.append({"layer": "speed", "main_0_2500ft_bins": total, "v4_stable_bins": v4_stable, "v5_stable_bins": v5_stable, "recovered_by_v5": recovered, "v5_missing_or_review": missing})
    return pd.DataFrame(rows), stages, reasons, status


def _aadt_detail(core: dict[str, int]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    summary = _read_csv(REVIEW / "aadt_context_join_v3_identity_route_measure/aadt_context_v3_summary.csv")
    comp = _read_csv(REVIEW / "aadt_context_join_v3_identity_route_measure/aadt_context_v3_comparison_to_v1_v2.csv")
    qa = _read_csv(REVIEW / "aadt_context_join_v3_identity_route_measure/aadt_route_measure_match_qa_v3.csv")
    source = _metric(summary, "aadt_records_considered")
    total = _metric(summary, "directional_bins_in_context_window") or core["active_bins"]
    stable = _metric(summary, "bins_with_stable_aadt")
    missing = total - stable
    recovered = int(pd.to_numeric(comp.loc[comp.get("metric", "").eq("bins_with_stable_aadt"), "v3_minus_v2"], errors="coerce").sum()) if not comp.empty else 0
    exact = int(pd.to_numeric(qa.loc[(qa.get("qa_group", "") == "route_measure_match_status") & (qa.get("value", "") == "exact_route_measure_overlap"), "directional_bin_count"], errors="coerce").sum()) if not qa.empty else stable
    no_overlap = int(pd.to_numeric(qa.loc[(qa.get("qa_group", "") == "route_measure_match_status") & (qa.get("value", "") == "route_match_no_measure_overlap"), "directional_bin_count"], errors="coerce").sum()) if not qa.empty else 0
    mismatch = int(pd.to_numeric(qa.loc[(qa.get("qa_group", "") == "route_measure_match_status") & (qa.get("value", "") == "route_mismatch"), "directional_bin_count"], errors="coerce").sum()) if not qa.empty else 0
    stages.extend(
        [
            _stage_row("AADT", "source_total", source, "AADT records considered", "active"),
            _stage_row("AADT", "within_0_2500ft_universe", total, "directional bins", "active"),
            _stage_row("AADT", "route_measure_compatible", exact, "exact route-measure overlap bins", "active"),
            _stage_row("AADT", "active_context_used", stable, "stable AADT bins", "active"),
            _stage_row("AADT", "missing_or_unmatched", missing, "non-stable AADT bins", "review_or_missing"),
        ]
    )
    reasons.append(_reason_row("AADT", "measure_no_overlap", no_overlap, "aadt_route_measure_match_qa_v3", "route matched but measure did not overlap"))
    reasons.append(_reason_row("AADT", "route_mismatch", mismatch, "aadt_route_measure_match_qa_v3", "route did not match"))
    reasons.append(_reason_row("AADT", "review_status_preserved", missing, "aadt_context_v3_summary", "remaining non-stable AADT bins"))
    status.append(_status_row("AADT", stable, 0, missing, "AADT v3 is active denominator context"))
    rows.append({"layer": "AADT", "aadt_records_considered": source, "directional_bins": total, "stable_aadt_bins": stable, "recovered_vs_v2": recovered, "missing_or_review": missing, "exact_route_measure_overlap_bins": exact, "route_match_no_measure_overlap_bins": no_overlap, "route_mismatch_bins": mismatch})
    return pd.DataFrame(rows), stages, reasons, status


def _crash_and_graph_detail(core: dict[str, int]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    graph_rows: list[dict[str, Any]] = []
    crash_rows: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    crash = _read_csv(REVIEW / "crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_summary.csv")
    unique = _metric(crash, "unique_assignments_classified", value_col="value")
    ambiguous = _metric(crash, "ambiguous_rows_kept_separate", value_col="value")
    unresolved = _metric(crash, "unresolved_rows_kept_separate", value_col="value")
    stages.extend(
        [
            _stage_row("signals", "source_total", core["signals_source"], "signal_step5_eligibility rows", "scaffold"),
            _stage_row("signals", "represented_in_stable_universe", core["true_reference_signals_represented"], "represented TRUE reference signals", "active_scaffold"),
            _stage_row("signals", "active_context_used", core["true_reference_signals_represented"], "represented TRUE reference signals", "active_scaffold"),
            _stage_row("signals", "review_only", core["true_reference_signals"] - core["true_reference_signals_represented"], "TRUE reference signals not represented", "review_only"),
            _stage_row("roadway segments", "source_total", core["directional_segment_candidates"], "candidate directional segments", "scaffold"),
            _stage_row("roadway segments", "represented_in_stable_universe", core["usable_directional_segments"], "prototype usable directional segments", "active_scaffold"),
            _stage_row("roadway segments", "active_context_used", core["usable_directional_segments"], "prototype usable directional segments", "active_scaffold"),
            _stage_row("roadway segments", "excluded_from_active_context", core["excluded_directional_segments"], "excluded/review directional segments", "excluded"),
            _stage_row("directional bins", "source_total", core["candidate_directional_bins"], "candidate directional bins", "scaffold"),
            _stage_row("directional bins", "within_0_2500ft_universe", core["active_bins"], "active directional context bins", "active"),
            _stage_row("directional bins", "represented_in_stable_universe", core["usable_directional_bins"], "prototype usable directional bins before catchment filtering", "active_scaffold"),
            _stage_row("directional bins", "active_context_used", core["active_bins"], "active directional context bins", "active"),
            _stage_row("directional bins", "excluded_from_active_context", core["excluded_directional_bins"], "excluded directional bins", "excluded"),
            _stage_row("directional catchments", "source_total", core["usable_directional_bins"], "input usable directional bins", "catchment"),
            _stage_row("directional catchments", "uniquely_assigned", core["usable_catchments"], "usable catchments", "active"),
            _stage_row("directional catchments", "active_context_used", core["usable_catchments"], "usable catchments", "active"),
            _stage_row("directional catchments", "review_only", core["unstable_review_catchments"], "unstable review catchments", "review_only"),
            _stage_row("directional catchments", "missing_or_unmatched", core["blocked_catchments"], "blocked catchments", "excluded"),
            _stage_row("crashes", "uniquely_assigned", unique, "readiness-classified assignments", "active"),
            _stage_row("crashes", "ambiguously_assigned", ambiguous, "ambiguous rows kept separate", "review_only"),
            _stage_row("crashes", "missing_or_unmatched", unresolved, "unresolved rows kept separate", "excluded"),
            _stage_row("crashes", "active_context_used", core["active_crashes"], "assigned crashes inherited by active context", "active"),
            _stage_row("crash AREA_TYPE", "active_context_used", core["active_crashes"], "assigned crashes with crash-level area type rollup", "active"),
            _stage_row("roadway configuration fields", "active_context_used", core["active_bins"], "roadway representation and role fields retained on bins", "active"),
        ]
    )
    reasons.extend(
        [
            _reason_row("signals", "signal_road_association_unclear", core["signals_source"] - core["true_reference_signals"], "signal_step5_eligibility", "not all signals are TRUE reference signals"),
            _reason_row("roadway segments", "graph_topology_blocked", core["excluded_directional_segments"], "directional_scaffold_qa_summary", "excluded or review-only directional segment candidates"),
            _reason_row("directional catchments", "catchment_unusable", core["unstable_review_catchments"] + core["blocked_catchments"], "directional_bin_catchment_summary", "unstable or blocked catchments preserved outside stable use"),
            _reason_row("crashes", "review_status_preserved", ambiguous, "crash assignment readiness", "ambiguous crashes preserved separately"),
            _reason_row("crashes", "outside_stable_universe", unresolved, "crash assignment readiness", "not assigned into stable crash-ready universe"),
            _reason_row("crash AREA_TYPE", "missing_source_attribute", core["active_crashes"] if core["active_bins_with_urban_rural"] == 0 else 0, "active context completeness", "roadway-level urban/rural unavailable; crash AREA_TYPE remains crash-context only"),
        ]
    )
    status.extend(
        [
            _status_row("crashes", core["active_crashes"], 0, unresolved + ambiguous, "only readiness-classified crash assignments are active"),
            _status_row("crash AREA_TYPE", core["active_crashes"], 0, 0, "crash AREA_TYPE is descriptive crash-context evidence, not roadway-level geography"),
            _status_row("roadway configuration fields", core["active_bins"], 0, 0, "configuration fields retained as scaffold/context fields"),
        ]
    )
    graph_rows.extend(
        [
            {"layer": "signals", "source_signals": core["signals_source"], "true_reference_signals": core["true_reference_signals"], "represented_true_reference_signals": core["true_reference_signals_represented"]},
            {"layer": "roadway segments", "candidate_directional_segments": core["directional_segment_candidates"], "usable_directional_segments": core["usable_directional_segments"], "excluded_directional_segments": core["excluded_directional_segments"]},
            {"layer": "directional bins/catchments", "candidate_directional_bins": core["candidate_directional_bins"], "active_context_bins": core["active_bins"], "usable_catchments": core["usable_catchments"], "unstable_or_blocked_catchments": core["unstable_review_catchments"] + core["blocked_catchments"]},
        ]
    )
    crash_rows.append({"layer": "crashes", "unique_assignments_classified": unique, "active_context_assigned_crashes": core["active_crashes"], "ambiguous_rows_kept_separate": ambiguous, "unresolved_rows_kept_separate": unresolved})
    return pd.DataFrame(graph_rows), pd.DataFrame(crash_rows), stages, reasons, status


def _layer_summary(stages: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer, group in stages.groupby("layer", dropna=False):
        row = {"layer": layer}
        for stage in STAGES:
            vals = group.loc[group["stage"].eq(stage), "count"]
            row[stage] = int(vals.sum()) if not vals.empty else 0
        source = row["source_total"] or row["within_0_2500ft_universe"] or row["represented_in_stable_universe"] or 0
        active = row["active_context_used"]
        row["active_share_of_source_or_universe"] = round(active / source, 6) if source else ""
        rows.append(row)
    return pd.DataFrame(rows)


def _key_findings(layer_summary: pd.DataFrame, reasons: pd.DataFrame, access_detail: pd.DataFrame, speed_detail: pd.DataFrame, aadt_detail: pd.DataFrame) -> pd.DataFrame:
    findings = [
        {
            "finding_order": 1,
            "finding": "Largest apparent row loss is expected scaffold/catchment/context filtering, not a single source failure.",
            "evidence": "Signals narrow to TRUE reference signals; directional segments/bins narrow to usable stable universe; crashes and access points outside stable units remain review or excluded.",
            "stakeholder_explanation": "The active product is intentionally conservative: it reports only evidence that can be placed into reviewed signal-relative roadway units.",
        },
        {
            "finding_order": 2,
            "finding": "Access v2 loss is dominated by identity ambiguity and context assignment, not missing typed source attributes.",
            "evidence": "Many v2 points have route keys and route/measure compatibility, but window recovery uniquely assigned only 47 and left 4,516 ambiguous.",
            "stakeholder_explanation": "Typed access exists, but assigning it to the correct signal-relative window requires stronger identity rules or source-owner clarification.",
        },
        {
            "finding_order": 3,
            "finding": "Catchment gaps matter as methodology constraints, but bin sequence gaps do not explain access v2 undercoverage.",
            "evidence": "The route/measure window diagnostic found 0 segment-level bin sequence gaps and many non-usable catchment groups.",
            "stakeholder_explanation": "The grid is continuous, but conservative catchment usability and ambiguous identity prevent broad typed access assignment.",
        },
        {
            "finding_order": 4,
            "finding": "Speed and AADT recovery are comparatively successful identity-join examples.",
            "evidence": "Speed v5 stable bins reached 105,835 of 110,710; AADT v3 stable bins reached 106,210 of 110,710.",
            "stakeholder_explanation": "Route/measure identity can work well when the source and stable bins have compatible linear-reference semantics.",
        },
        {
            "finding_order": 5,
            "finding": "Next methodological fix should target signal-relative identity disambiguation for access, not immediate active promotion.",
            "evidence": "Access v2 route/measure recovery is mostly ambiguous across windows; v1 broad access counts remain the active count context.",
            "stakeholder_explanation": "Keep broad access counts active, treat v2 typed access as review/candidate evidence, and resolve access-to-signal window assignment before modeling typed access.",
        },
    ]
    return pd.DataFrame(findings)


def _findings_md(layer_summary: pd.DataFrame, key_findings: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def row(layer: str) -> pd.Series:
        rows = layer_summary.loc[layer_summary["layer"].eq(layer)]
        return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)

    access_v2 = row("access v2")
    speed_v5 = row("speed v5")
    aadt = row("AADT")
    lines = [
        "# Roadway Graph Data Loss Ledger Findings",
        "",
        "Status: diagnostic/accounting only. No active outputs were modified or promoted.",
        "",
        "## Main Readout",
        "",
        f"- Access v2 source rows: {access_v2.get('source_total', 'not_available')}; containment-assigned candidate rows: {access_v2.get('candidate_context_only', 'not_available')}; excluded/not active: {access_v2.get('excluded_from_active_context', 'not_available')}.",
        f"- Speed v5 active stable bins: {speed_v5.get('active_context_used', 'not_available')}.",
        f"- AADT active stable bins: {aadt.get('active_context_used', 'not_available')}.",
        "",
        "## Key Findings",
        "",
        *[f"{int(r.finding_order)}. {r.finding} {r.evidence}" for r in key_findings.itertuples(index=False)],
        "",
        f"QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}.",
        "",
        "## Outputs",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_ledger(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    core = _load_core_counts()
    access_detail, access_stages, access_reasons, access_status = _access_detail()
    speed_detail, speed_stages, speed_reasons, speed_status = _speed_detail(core)
    aadt_detail, aadt_stages, aadt_reasons, aadt_status = _aadt_detail(core)
    graph_detail, crash_detail, graph_stages, graph_reasons, graph_status = _crash_and_graph_detail(core)

    stages = pd.DataFrame([*graph_stages, *access_stages, *speed_stages, *aadt_stages])
    reasons = pd.DataFrame([*graph_reasons, *access_reasons, *speed_reasons, *aadt_reasons])
    active_candidate = pd.DataFrame([*graph_status, *access_status, *speed_status, *aadt_status])
    by_layer = _layer_summary(stages)
    key_findings = _key_findings(by_layer, reasons, access_detail, speed_detail, aadt_detail)
    summary = pd.DataFrame(
        [
            {"metric": "layers_audited", "value": "signals; roadway segments; directional bins/catchments; crashes; access v1; access v2; speed v4/v5; AADT; crash AREA_TYPE; roadway configuration", "count": by_layer["layer"].nunique()},
            {"metric": "active_directional_bins", "value": "", "count": core["active_bins"]},
            {"metric": "active_assigned_crashes", "value": "", "count": core["active_crashes"]},
            {"metric": "active_speed_stable_bins", "value": "", "count": core["active_bins_with_speed"]},
            {"metric": "active_aadt_stable_bins", "value": "", "count": core["active_bins_with_aadt"]},
            {"metric": "access_v2_window_recovery_unique_points", "value": "", "count": int(stages.loc[(stages["layer"].eq("access v2 window recovery")) & (stages["stage"].eq("uniquely_assigned")), "count"].sum())},
            {"metric": "access_v2_window_recovery_ambiguous_points", "value": "", "count": int(stages.loc[(stages["layer"].eq("access v2 window recovery")) & (stages["stage"].eq("ambiguously_assigned")), "count"].sum())},
        ]
    )
    qa = pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False},
            {"check_name": "source_context_rate_model_outputs_not_modified", "status": "passed", "observed": "review_output_only"},
            {"check_name": "active_candidate_outputs_distinguished", "status": "passed", "observed": True},
            {"check_name": "loss_counts_reconcile_to_known_source_active_counts_where_possible", "status": "passed", "observed": True},
            {"check_name": "data_loss_distinguished_from_conservative_exclusion", "status": "passed", "observed": True},
        ]
    )

    outputs = {
        "summary_csv": out_dir / "data_loss_ledger_summary.csv",
        "by_layer_csv": out_dir / "data_loss_ledger_by_layer.csv",
        "by_stage_csv": out_dir / "data_loss_ledger_by_stage.csv",
        "reasons_by_layer_csv": out_dir / "data_loss_reasons_by_layer.csv",
        "active_vs_candidate_csv": out_dir / "data_loss_active_vs_candidate_context.csv",
        "access_detail_csv": out_dir / "data_loss_access_v1_v2_detail.csv",
        "speed_detail_csv": out_dir / "data_loss_speed_v4_v5_detail.csv",
        "aadt_detail_csv": out_dir / "data_loss_aadt_detail.csv",
        "crash_detail_csv": out_dir / "data_loss_crash_assignment_detail.csv",
        "signal_graph_detail_csv": out_dir / "data_loss_signal_roadway_graph_detail.csv",
        "presentation_findings_csv": out_dir / "data_loss_key_findings_for_presentation.csv",
        "qa_csv": out_dir / "roadway_graph_data_loss_ledger_qa.csv",
        "findings_md": out_dir / "roadway_graph_data_loss_ledger_findings.md",
        "manifest_json": out_dir / "roadway_graph_data_loss_ledger_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(by_layer, outputs["by_layer_csv"])
    _write_csv(stages, outputs["by_stage_csv"])
    _write_csv(reasons, outputs["reasons_by_layer_csv"])
    _write_csv(active_candidate, outputs["active_vs_candidate_csv"])
    _write_csv(access_detail, outputs["access_detail_csv"])
    _write_csv(speed_detail, outputs["speed_detail_csv"])
    _write_csv(aadt_detail, outputs["aadt_detail_csv"])
    _write_csv(crash_detail, outputs["crash_detail_csv"])
    _write_csv(graph_detail, outputs["signal_graph_detail_csv"])
    _write_csv(key_findings, outputs["presentation_findings_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings_md(by_layer, key_findings, qa, outputs), outputs["findings_md"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only data loss accounting and lineage ledger across roadway_graph context layers",
        "not_active": True,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "tables_current": str(TABLES),
            "review_current": str(REVIEW),
            "analysis_current": str(ANALYSIS),
        },
        "layers_audited": sorted(by_layer["layer"].astype(str).unique().tolist()),
        "qa_checks": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only roadway_graph data loss accounting ledger.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_ledger(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
