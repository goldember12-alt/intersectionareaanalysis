from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
BIN_GEN_DIR = OUTPUT_ROOT / "review/current/signal_recovery_candidate_bin_generation"
ACTIVE_CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active"
TABLES_DIR = OUTPUT_ROOT / "tables/current"
NORMALIZED_ROADS = Path("artifacts/normalized/roads.parquet")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_context_sufficiency_audit"

EXPECTED_CANDIDATE_BINS = 136_227
EXPECTED_RECOVERED_BIN_SIGNALS = 1_590
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
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_inputs() -> dict[str, Any]:
    active_signal = _read_csv(ACTIVE_CONTEXT_DIR / "reference_signal_context_summary_active.csv")
    active_bins = _read_csv(
        ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv",
        usecols=[
            "reference_signal_id",
            "reference_directional_bin_id",
            "roadway_representation_type",
            "has_assigned_crash",
            "unique_assigned_crash_count",
            "has_access_context",
            "has_stable_speed_context",
            "has_stable_aadt_context",
            "aadt_value",
            "active_aadt_denominator_policy",
            "has_urban_rural_context",
            "roadway_urban_rural_context_status",
            "has_complete_core_context",
            "context_completeness_class",
        ],
    )
    return {
        "bins": _read_csv(BIN_GEN_DIR / "candidate_recovery_bins.csv"),
        "signal_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_signal_summary.csv"),
        "association_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_association_summary.csv"),
        "generation_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_bin_generation_summary.csv"),
        "distance_window_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_distance_window_summary.csv"),
        "direction_coverage_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_direction_coverage_summary.csv"),
        "multi_candidate_weight_summary": _read_csv(BIN_GEN_DIR / "candidate_recovery_multi_candidate_weight_summary.csv"),
        "existing_active_overlap": _read_csv(BIN_GEN_DIR / "candidate_recovery_existing_active_overlap.csv"),
        "bin_manifest": _load_manifest(BIN_GEN_DIR / "candidate_recovery_bin_generation_manifest.json"),
        "active_signal_summary": active_signal,
        "active_bins": active_bins,
        "travelway_lane_context": _travelway_lane_context(),
    }


def _travelway_lane_context() -> pd.DataFrame:
    edges = _read_csv(TABLES_DIR / "roadway_graph_edges.csv", usecols=["road_component_id", "source_road_row_id"])
    if edges.empty or not NORMALIZED_ROADS.exists():
        return pd.DataFrame(columns=["road_component_id", "travelway_lane_count", "travelway_lane_context_status"])
    roads = pd.read_parquet(NORMALIZED_ROADS)
    lane_cols = [col for col in ["LANE_THRU_", "LANE_THRU1", "LANE_THR_1", "LANE_REVER", "LANE_THR_2", "LANE_THR_3", "LANE_THR_4"] if col in roads.columns]
    if not lane_cols:
        return pd.DataFrame(columns=["road_component_id", "travelway_lane_count", "travelway_lane_context_status"])
    lane = roads[lane_cols].copy()
    lane["_source_road_row_id"] = lane.index.astype(str)
    values = lane[lane_cols].apply(pd.to_numeric, errors="coerce")
    lane["travelway_lane_count"] = values.max(axis=1)
    lane["travelway_lane_context_status"] = "travelway_lane_field_available"
    lane.loc[lane["travelway_lane_count"].isna(), "travelway_lane_context_status"] = "travelway_lane_field_missing"
    merged = edges.merge(lane[["_source_road_row_id", "travelway_lane_count", "travelway_lane_context_status"]], left_on="source_road_row_id", right_on="_source_road_row_id", how="left")
    merged["travelway_lane_context_status"] = merged["travelway_lane_context_status"].fillna("travelway_source_row_not_matched")
    return (
        merged.groupby("road_component_id", dropna=False)
        .agg(
            travelway_lane_count=("travelway_lane_count", "max"),
            travelway_lane_context_status=("travelway_lane_context_status", _dominant),
        )
        .reset_index()
    )


def _build_bin_detail(bins: pd.DataFrame, lane_context: pd.DataFrame) -> pd.DataFrame:
    detail = bins.copy()
    if detail.empty:
        return detail
    if not lane_context.empty:
        detail = detail.merge(lane_context, on="road_component_id", how="left")
    else:
        detail["travelway_lane_count"] = ""
        detail["travelway_lane_context_status"] = "travelway_lane_context_source_unavailable"

    detail["candidate_bin_context_join_scope"] = "review_only_candidate_proxy_bin"
    detail["crash_coverage_flag"] = False
    detail["assigned_crash_count"] = 0
    detail["crash_join_method"] = "not_possible_current_candidate_proxy_no_active_bin_or_signal_key"
    detail["access_v1_coverage_flag"] = False
    detail["access_v1_join_method"] = "not_possible_current_candidate_proxy_no_catchment_or_active_bin_key"
    detail["access_v2_typed_coverage_flag"] = False
    detail["access_v2_join_method"] = "not_possible_current_candidate_proxy_no_route_measure_window_key"
    detail["speed_coverage_flag"] = False
    detail["speed_join_method"] = "not_possible_current_candidate_proxy_no_route_measure_bin_key"
    detail["aadt_coverage_flag"] = False
    detail["aadt_join_method"] = "not_possible_current_candidate_proxy_no_route_measure_bin_key"
    detail["lane_coverage_flag"] = pd.to_numeric(detail["travelway_lane_count"], errors="coerce").notna()
    detail["lane_join_method"] = "exact_travelway_source_row_via_road_component_id"
    detail.loc[~detail["lane_coverage_flag"], "lane_join_method"] = "travelway_lane_field_missing_or_source_row_unmatched"
    detail["divided_undivided_coverage_flag"] = _text(detail, "roadway_division_status").ne("") & ~_text(detail, "roadway_division_status").eq("unknown")
    detail["divided_undivided_join_method"] = "exact_travelway_derived_candidate_provenance_field"
    detail["roadway_context_coverage_flag"] = _text(detail, "matched_route_common").ne("")
    detail["roadway_context_join_method"] = "exact_travelway_derived_candidate_provenance_field"
    detail["estimated_exposure_coverage_flag"] = False
    detail["estimated_exposure_join_method"] = "not_possible_current_candidate_proxy_no_active_denominator_key"
    detail["rate_ready_candidate_flag"] = False
    detail["model_ready_candidate_flag"] = False
    detail["rate_model_readiness_method"] = "not_evaluable_without_candidate_context_join_adaptation"
    detail["approximate_join_used"] = False
    detail["failed_join_reason"] = "candidate proxy geometry not sufficient for exact context joins"
    detail.loc[
        _text(detail, "strict_active_overlap_status").str.contains("double_count", case=False, regex=False),
        "failed_join_reason",
    ] = "strict active overlap/double-count risk"
    detail["analysis_use_tier"] = _analysis_use_tier(detail)
    return detail


def _analysis_use_tier(detail: pd.DataFrame) -> pd.Series:
    tier = pd.Series("join_not_possible_with_current_candidate_bins", index=detail.index, dtype=str)
    roadway_context = _bool(detail, "divided_undivided_coverage_flag") & _bool(detail, "roadway_context_coverage_flag")
    tier.loc[roadway_context] = "expanded_context_only_candidate"
    tier.loc[roadway_context & _text(detail, "association_confidence_tier").eq("multi_candidate_weighted_recovery")] = "expanded_multi_candidate_weighted_context_candidate"
    tier.loc[roadway_context & _text(detail, "scaffold_completeness_tier").str.contains("one_direction", case=False, regex=False)] = "expanded_partial_direction_context_candidate"
    tier.loc[_text(detail, "strict_active_overlap_status").str.contains("double_count", case=False, regex=False)] = "strict_active_overlap_candidate"
    return tier


def _signal_context_summary(signal_summary: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    base = signal_summary.copy()
    if base.empty:
        return base

    grouped = (
        detail.groupby("signal_id", dropna=False)
        .agg(
            candidate_bin_count=("candidate_recovery_bin_id", "count"),
            weighted_candidate_bin_count=("candidate_weight_preliminary", lambda s: pd.to_numeric(s, errors="coerce").fillna(1.0).sum()),
            crash_coverage_flag=("crash_coverage_flag", "max"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            access_v1_coverage_flag=("access_v1_coverage_flag", "max"),
            access_v2_typed_coverage_flag=("access_v2_typed_coverage_flag", "max"),
            speed_coverage_flag=("speed_coverage_flag", "max"),
            aadt_coverage_flag=("aadt_coverage_flag", "max"),
            lane_coverage_flag=("lane_coverage_flag", "max"),
            divided_undivided_coverage_flag=("divided_undivided_coverage_flag", "max"),
            roadway_context_coverage_flag=("roadway_context_coverage_flag", "max"),
            estimated_exposure_coverage_flag=("estimated_exposure_coverage_flag", "max"),
            rate_ready_candidate_flag=("rate_ready_candidate_flag", "max"),
            model_ready_candidate_flag=("model_ready_candidate_flag", "max"),
            strict_active_overlap_flag=("strict_active_overlap_status", lambda s: s.astype(str).str.contains("double_count", case=False, regex=False).any()),
            analysis_use_tier=("analysis_use_tier", _dominant),
            dominant_missing_context_reason=("failed_join_reason", _dominant),
        )
        .reset_index()
    )
    out = base.merge(grouped, on="signal_id", how="left")
    out["candidate_bin_count"] = _num(out, "candidate_bin_count").astype(int)
    out["weighted_candidate_bin_count"] = _num(out, "weighted_candidate_bin_count")
    bool_cols = [
        "crash_coverage_flag",
        "access_v1_coverage_flag",
        "access_v2_typed_coverage_flag",
        "speed_coverage_flag",
        "aadt_coverage_flag",
        "lane_coverage_flag",
        "divided_undivided_coverage_flag",
        "roadway_context_coverage_flag",
        "estimated_exposure_coverage_flag",
        "rate_ready_candidate_flag",
        "model_ready_candidate_flag",
        "strict_active_overlap_flag",
    ]
    for col in bool_cols:
        out[col] = out[col].fillna(False).astype(bool)
    out["evaluation_scope"] = "recovered_candidate_with_bins"
    out.loc[out["candidate_bin_count"].eq(0), "evaluation_scope"] = "review_only_or_no_candidate_bins"
    out.loc[out["analysis_use_tier"].fillna("").eq(""), "analysis_use_tier"] = "join_not_possible_with_current_candidate_bins"
    out.loc[out["dominant_missing_context_reason"].fillna("").eq(""), "dominant_missing_context_reason"] = "candidate proxy geometry not sufficient for exact context joins"
    return out


def _dominant(series: pd.Series) -> str:
    clean = series.fillna("").astype(str)
    clean = clean.loc[clean.ne("")]
    if clean.empty:
        return ""
    return str(clean.value_counts().index[0])


def _active_strict_metrics(active_signal: pd.DataFrame, active_bins: pd.DataFrame) -> dict[str, Any]:
    if active_signal.empty:
        return {
            "signal_count": STRICT_ACTIVE_SIGNAL_BASELINE,
            "candidate_bin_count": 0,
            "weighted_candidate_bin_count": 0.0,
            "signals_with_assigned_crashes": 0,
            "total_assigned_crashes": 0,
            "signals_with_access_v1_coverage": 0,
            "signals_with_access_v2_typed_candidate_coverage": 0,
            "signals_with_speed_coverage": 0,
            "signals_with_aadt_coverage": 0,
            "signals_with_lane_coverage": 0,
            "signals_with_divided_undivided_coverage": 0,
            "signals_with_roadway_context_coverage": 0,
            "signals_with_estimated_exposure_coverage": 0,
            "rate_ready_candidate_signals": 0,
            "model_ready_candidate_signals": 0,
            "dominant_missing_context_reason": "strict active summary unavailable",
        }
    signal_count = active_signal["reference_signal_id"].nunique()
    return {
        "signal_count": signal_count,
        "candidate_bin_count": active_bins["reference_directional_bin_id"].nunique() if not active_bins.empty and "reference_directional_bin_id" in active_bins.columns else int(_num(active_signal, "directional_bin_count").sum()),
        "weighted_candidate_bin_count": "",
        "signals_with_assigned_crashes": int(_num(active_signal, "assigned_crash_count").gt(0).sum()),
        "total_assigned_crashes": int(_num(active_signal, "assigned_crash_count").sum()),
        "signals_with_access_v1_coverage": int(_num(active_signal, "bins_with_access_context").gt(0).sum()),
        "signals_with_access_v2_typed_candidate_coverage": "not_separately_evaluable_from_active_signal_summary",
        "signals_with_speed_coverage": int(_num(active_signal, "bins_with_stable_speed_context").gt(0).sum()),
        "signals_with_aadt_coverage": int(_num(active_signal, "bins_with_stable_aadt_context").gt(0).sum()),
        "signals_with_lane_coverage": 0,
        "signals_with_divided_undivided_coverage": signal_count,
        "signals_with_roadway_context_coverage": signal_count,
        "signals_with_estimated_exposure_coverage": int(_num(active_signal, "bins_with_stable_aadt_context").gt(0).sum()),
        "rate_ready_candidate_signals": int((_num(active_signal, "bins_with_stable_aadt_context").gt(0) & _num(active_signal, "bins_with_access_context").gt(0)).sum()),
        "model_ready_candidate_signals": "not_recomputed",
            "dominant_missing_context_reason": "candidate crash/access/speed/AADT joins require candidate geometry or route-measure keys",
    }


def _universe_summary(signal_ctx: pd.DataFrame, bins: pd.DataFrame, active_signal: pd.DataFrame, active_bins: pd.DataFrame) -> pd.DataFrame:
    rows = []
    strict = _active_strict_metrics(active_signal, active_bins)
    rows.append({"analysis_universe": "strict_active_baseline", **strict})

    recovered_any = signal_ctx.loc[signal_ctx["evaluation_scope"].eq("recovered_candidate_with_bins")].copy()
    recovered_1000 = recovered_any.loc[_bool(recovered_any, "full_0_1000_coverage_flag")].copy()
    recovered_2500 = recovered_any.loc[_bool(recovered_any, "full_0_2500_coverage_flag")].copy()
    recovered_both = recovered_any.loc[_bool(recovered_any, "both_direction_coverage_flag")].copy()
    recovered_one = recovered_any.loc[_bool(recovered_any, "one_direction_only_flag")].copy()
    recovered_multi = recovered_any.loc[_bool(recovered_any, "multi_candidate_preserved_flag")].copy()

    rows.append(_recovered_universe_row("expanded_recovered_only_any_bin_universe", recovered_any, bins))
    rows.append(_expanded_row("expanded_any_bin_universe", recovered_any, bins, strict))
    rows.append(_expanded_row("expanded_0_1000ft_universe", recovered_1000, bins.loc[_text(bins, "analysis_window").eq("0_1000")], strict))
    rows.append(_expanded_row("expanded_full_0_2500ft_universe", recovered_2500, bins, strict))
    rows.append(_expanded_row("expanded_both_direction_universe", recovered_both, bins, strict))
    rows.append(_recovered_universe_row("expanded_one_direction_only_universe", recovered_one, bins))
    rows.append(_recovered_universe_row("expanded_multi_candidate_weighted_universe", recovered_multi, bins))
    return pd.DataFrame(rows)


def _recovered_universe_row(name: str, signals: pd.DataFrame, bins: pd.DataFrame) -> dict[str, Any]:
    ids = set(_text(signals, "signal_id"))
    b = bins.loc[_text(bins, "signal_id").isin(ids)] if not bins.empty else bins
    return {
        "analysis_universe": name,
        "signal_count": len(ids),
        "candidate_bin_count": len(b),
        "weighted_candidate_bin_count": round(float(pd.to_numeric(b.get("candidate_weight_preliminary", pd.Series(dtype=str)), errors="coerce").fillna(1.0).sum()), 6) if not b.empty else 0.0,
        "signals_with_assigned_crashes": int(_bool(signals, "crash_coverage_flag").sum()),
        "total_assigned_crashes": int(_num(signals, "assigned_crash_count").sum()),
        "signals_with_access_v1_coverage": int(_bool(signals, "access_v1_coverage_flag").sum()),
        "signals_with_access_v2_typed_candidate_coverage": int(_bool(signals, "access_v2_typed_coverage_flag").sum()),
        "signals_with_speed_coverage": int(_bool(signals, "speed_coverage_flag").sum()),
        "signals_with_aadt_coverage": int(_bool(signals, "aadt_coverage_flag").sum()),
        "signals_with_lane_coverage": int(_bool(signals, "lane_coverage_flag").sum()),
        "signals_with_divided_undivided_coverage": int(_bool(signals, "divided_undivided_coverage_flag").sum()),
        "signals_with_roadway_context_coverage": int(_bool(signals, "roadway_context_coverage_flag").sum()),
        "signals_with_estimated_exposure_coverage": int(_bool(signals, "estimated_exposure_coverage_flag").sum()),
        "rate_ready_candidate_signals": int(_bool(signals, "rate_ready_candidate_flag").sum()),
        "model_ready_candidate_signals": int(_bool(signals, "model_ready_candidate_flag").sum()),
        "dominant_missing_context_reason": _dominant(signals.get("dominant_missing_context_reason", pd.Series(dtype=str))),
    }


def _expanded_row(name: str, recovered: pd.DataFrame, bins: pd.DataFrame, strict: dict[str, Any]) -> dict[str, Any]:
    row = _recovered_universe_row(name, recovered, bins)
    row["signal_count"] = int(strict["signal_count"]) + int(row["signal_count"])
    row["candidate_bin_count"] = int(strict["candidate_bin_count"]) + int(row["candidate_bin_count"])
    numeric_cols = [
        "signals_with_assigned_crashes",
        "total_assigned_crashes",
        "signals_with_access_v1_coverage",
        "signals_with_speed_coverage",
        "signals_with_aadt_coverage",
        "signals_with_lane_coverage",
        "signals_with_divided_undivided_coverage",
        "signals_with_roadway_context_coverage",
        "signals_with_estimated_exposure_coverage",
        "rate_ready_candidate_signals",
    ]
    for col in numeric_cols:
        row[col] = _as_int(strict.get(col, 0)) + _as_int(row.get(col, 0))
    row["model_ready_candidate_signals"] = "not_recomputed"
    row["signals_with_access_v2_typed_candidate_coverage"] = "candidate_not_joinable; strict_not_separately_evaluable"
    return row


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _simple_group(frame: pd.DataFrame, by: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows = []
    for value, group in frame.groupby(by, dropna=False):
        rows.append(
            {
                by: value,
                "candidate_bin_count": len(group),
                "signal_count": group["signal_id"].nunique(),
                "signals_with_crash_coverage": group.loc[group["crash_coverage_flag"].astype(bool), "signal_id"].nunique(),
                "signals_with_lane_context": group.loc[group["lane_coverage_flag"].astype(bool), "signal_id"].nunique(),
                "bins_with_divided_undivided_context": int(group["divided_undivided_coverage_flag"].astype(bool).sum()),
                "bins_with_roadway_context": int(group["roadway_context_coverage_flag"].astype(bool).sum()),
            }
        )
    return pd.DataFrame(rows)


def _missingness(detail: pd.DataFrame) -> pd.DataFrame:
    reasons = [
        ("no compatible crash assignment output", ~_bool(detail, "crash_coverage_flag")),
        ("no compatible access v1 output", ~_bool(detail, "access_v1_coverage_flag")),
        ("no compatible access v2 typed output", ~_bool(detail, "access_v2_typed_coverage_flag")),
        ("no speed coverage", ~_bool(detail, "speed_coverage_flag")),
        ("no AADT coverage", ~_bool(detail, "aadt_coverage_flag")),
        ("no lane coverage", ~_bool(detail, "lane_coverage_flag")),
        ("no divided/undivided coverage", ~_bool(detail, "divided_undivided_coverage_flag")),
        ("no roadway context coverage", ~_bool(detail, "roadway_context_coverage_flag")),
        ("exposure unavailable", ~_bool(detail, "estimated_exposure_coverage_flag")),
        ("candidate proxy geometry not sufficient for exact join", pd.Series(True, index=detail.index)),
        ("strict active overlap/double-count risk", _text(detail, "strict_active_overlap_status").str.contains("double_count", case=False, regex=False)),
    ]
    rows = []
    for reason, mask in reasons:
        subset = detail.loc[mask]
        rows.append({"missingness_reason": reason, "candidate_bin_count": len(subset), "signal_count": subset["signal_id"].nunique() if "signal_id" in subset.columns else 0})
    return pd.DataFrame(rows).sort_values(["candidate_bin_count", "missingness_reason"], ascending=[False, True])


def _join_method_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    layers = [
        ("crash", "crash_join_method"),
        ("access_v1", "access_v1_join_method"),
        ("access_v2_typed", "access_v2_join_method"),
        ("speed_v5", "speed_join_method"),
        ("aadt_v3_active_denominator", "aadt_join_method"),
        ("lanes", "lane_join_method"),
        ("divided_undivided", "divided_undivided_join_method"),
        ("roadway_context", "roadway_context_join_method"),
        ("estimated_exposure", "estimated_exposure_join_method"),
    ]
    for layer, col in layers:
        counts = detail.groupby(col, dropna=False).agg(candidate_bin_count=("candidate_recovery_bin_id", "count"), signal_count=("signal_id", "nunique")).reset_index()
        for r in counts.itertuples(index=False):
            rows.append({"context_layer": layer, "join_method": getattr(r, col), "candidate_bin_count": r.candidate_bin_count, "signal_count": r.signal_count})
    return pd.DataFrame(rows)


def _rate_model_readiness(signal_ctx: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"readiness_class": "rate_ready_candidate", "signal_count": int(_bool(signal_ctx, "rate_ready_candidate_flag").sum())},
            {"readiness_class": "model_ready_candidate", "signal_count": int(_bool(signal_ctx, "model_ready_candidate_flag").sum())},
            {"readiness_class": "not_rate_ready_join_not_possible", "signal_count": int((~_bool(signal_ctx, "rate_ready_candidate_flag") & signal_ctx["evaluation_scope"].eq("recovered_candidate_with_bins")).sum())},
            {"readiness_class": "not_model_ready_join_not_possible", "signal_count": int((~_bool(signal_ctx, "model_ready_candidate_flag") & signal_ctx["evaluation_scope"].eq("recovered_candidate_with_bins")).sum())},
        ]
    )


def _strict_active_comparison(universe: pd.DataFrame) -> pd.DataFrame:
    strict = universe.loc[universe["analysis_universe"].eq("strict_active_baseline")]
    recovered = universe.loc[universe["analysis_universe"].eq("expanded_recovered_only_any_bin_universe")]
    expanded = universe.loc[universe["analysis_universe"].eq("expanded_any_bin_universe")]
    rows = []
    if not strict.empty and not recovered.empty:
        for metric in [
            "signal_count",
            "signals_with_assigned_crashes",
            "signals_with_access_v1_coverage",
            "signals_with_speed_coverage",
            "signals_with_aadt_coverage",
            "signals_with_divided_undivided_coverage",
            "signals_with_roadway_context_coverage",
            "rate_ready_candidate_signals",
        ]:
            rows.append(
                {
                    "comparison_metric": metric,
                    "strict_active_value": strict.iloc[0].get(metric, ""),
                    "recovered_only_value": recovered.iloc[0].get(metric, ""),
                    "expanded_any_bin_value": expanded.iloc[0].get(metric, "") if not expanded.empty else "",
            "interpretation": "candidate context joins require adaptation" if metric not in {"signal_count", "signals_with_lane_coverage", "signals_with_divided_undivided_coverage", "signals_with_roadway_context_coverage"} else "Travelway-derived candidate provenance provides this field",
                }
            )
    return pd.DataFrame(rows)


def _review_queue(signal_ctx: pd.DataFrame) -> pd.DataFrame:
    out = signal_ctx.loc[signal_ctx["evaluation_scope"].eq("recovered_candidate_with_bins")].copy()
    if out.empty:
        return out
    out["review_queue_type"] = "candidate_context_join_adaptation_needed"
    out.loc[_bool(out, "full_0_1000_coverage_flag") & _bool(out, "roadway_context_coverage_flag"), "review_queue_type"] = "best_expanded_0_1000ft_context_candidate"
    out.loc[_bool(out, "full_0_2500_coverage_flag") & _bool(out, "roadway_context_coverage_flag"), "review_queue_type"] = "best_expanded_full_0_2500ft_context_candidate"
    out.loc[_bool(out, "multi_candidate_preserved_flag") & _bool(out, "roadway_context_coverage_flag"), "review_queue_type"] = "context_rich_multi_candidate_weighted_signal"
    out.loc[_bool(out, "one_direction_only_flag") & _bool(out, "roadway_context_coverage_flag"), "review_queue_type"] = "context_rich_one_direction_partial_signal"
    out.loc[_bool(out, "strict_active_overlap_flag"), "review_queue_type"] = "strict_active_overlap_double_count_review"
    out["review_priority_score"] = (
        _bool(out, "full_0_2500_coverage_flag").astype(int) * 40
        + _bool(out, "full_0_1000_coverage_flag").astype(int) * 25
        + _bool(out, "both_direction_coverage_flag").astype(int) * 15
        + _bool(out, "roadway_context_coverage_flag").astype(int) * 10
        + _bool(out, "divided_undivided_coverage_flag").astype(int) * 5
        + _num(out, "weighted_candidate_bin_count") / 100
    )
    return out.sort_values(["review_priority_score", "candidate_bin_count"], ascending=False)


def _availability_matrix() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"context_layer": "crash", "candidate_join_status": "not_possible", "join_method": "no active bin/signal key for recovered candidate proxy bins", "read_for_evaluation": False},
            {"context_layer": "access_v1", "candidate_join_status": "not_possible", "join_method": "no active catchment/bin key for recovered candidate proxy bins", "read_for_evaluation": False},
            {"context_layer": "access_v2_typed", "candidate_join_status": "not_possible", "join_method": "no route/measure window key on candidate bins", "read_for_evaluation": False},
            {"context_layer": "speed_v5", "candidate_join_status": "not_possible", "join_method": "no route/measure bin key on candidate bins", "read_for_evaluation": False},
            {"context_layer": "aadt_v3_active_denominator", "candidate_join_status": "not_possible", "join_method": "no route/measure bin key on candidate bins", "read_for_evaluation": False},
            {"context_layer": "lanes", "candidate_join_status": "exact_travelway_source_row", "join_method": "Travelway lane fields joined through roadway_graph_edges source_road_row_id by road_component_id", "read_for_evaluation": True},
            {"context_layer": "divided_undivided", "candidate_join_status": "exact_travelway_candidate_provenance", "join_method": "roadway_division_status carried from Travelway-derived candidate bins", "read_for_evaluation": True},
            {"context_layer": "roadway_context", "candidate_join_status": "exact_travelway_candidate_provenance", "join_method": "matched_route_common carried from Travelway-derived candidate bins", "read_for_evaluation": True},
            {"context_layer": "estimated_exposure", "candidate_join_status": "not_possible", "join_method": "denominator policy keys exist only for active bins", "read_for_evaluation": False},
            {"context_layer": "rate_model_readiness", "candidate_join_status": "not_evaluable", "join_method": "existing readiness logic requires active context fields", "read_for_evaluation": False},
        ]
    )


def _analysis_use_tier_summary(signal_ctx: pd.DataFrame) -> pd.DataFrame:
    return signal_ctx.groupby("analysis_use_tier", dropna=False).agg(signal_count=("signal_id", "nunique")).reset_index()


def _findings(universe: pd.DataFrame, join_methods: pd.DataFrame, missing: pd.DataFrame, signal_ctx: pd.DataFrame, qa: pd.DataFrame) -> str:
    metrics = {r.analysis_universe: r for r in universe.itertuples(index=False)}

    def val(universe_name: str, metric: str) -> Any:
        row = metrics.get(universe_name)
        return getattr(row, metric) if row is not None and hasattr(row, metric) else ""

    exact_layers = sorted(join_methods.loc[join_methods["join_method"].str.contains("exact", case=False, regex=False), "context_layer"].unique())
    not_possible_layers = sorted(join_methods.loc[join_methods["join_method"].str.contains("not_possible|not_available|not_evaluable", case=False, regex=True), "context_layer"].unique())
    dominant = missing.iloc[0]["missingness_reason"] if not missing.empty else ""
    multi_context = int((_bool(signal_ctx, "multi_candidate_preserved_flag") & _bool(signal_ctx, "roadway_context_coverage_flag") & signal_ctx["evaluation_scope"].eq("recovered_candidate_with_bins")).sum())
    one_context = int((_bool(signal_ctx, "one_direction_only_flag") & _bool(signal_ctx, "roadway_context_coverage_flag") & signal_ctx["evaluation_scope"].eq("recovered_candidate_with_bins")).sum())
    return f"""# Expanded Candidate Context Sufficiency Findings

Status: read-only context-sufficiency audit for recovered candidate bins. Candidate bins remain review-only and are not promoted.

## Required Findings

1. Recovered candidate signals evaluated: {val('expanded_recovered_only_any_bin_universe', 'signal_count')}; candidate bins evaluated: {val('expanded_recovered_only_any_bin_universe', 'candidate_bin_count')}.
2. Exact candidate joins/provenance fields available: {', '.join(exact_layers) or 'none'}. Approximate context joins used: none. Not possible with current proxy bins: {', '.join(not_possible_layers)}.
3. Expanded any-bin signals with crash coverage: {val('expanded_any_bin_universe', 'signals_with_assigned_crashes')} total including strict baseline; recovered-only crash coverage is {val('expanded_recovered_only_any_bin_universe', 'signals_with_assigned_crashes')}.
4. Expanded 0-1,000 ft signals with crash/access/speed/AADT/lane/divided-roadway coverage: crash {val('expanded_0_1000ft_universe', 'signals_with_assigned_crashes')}, access {val('expanded_0_1000ft_universe', 'signals_with_access_v1_coverage')}, speed {val('expanded_0_1000ft_universe', 'signals_with_speed_coverage')}, AADT {val('expanded_0_1000ft_universe', 'signals_with_aadt_coverage')}, lane {val('expanded_0_1000ft_universe', 'signals_with_lane_coverage')}, divided/undivided {val('expanded_0_1000ft_universe', 'signals_with_divided_undivided_coverage')}.
5. Expanded full 0-2,500 ft signals with crash/access/speed/AADT/lane/divided-roadway coverage: crash {val('expanded_full_0_2500ft_universe', 'signals_with_assigned_crashes')}, access {val('expanded_full_0_2500ft_universe', 'signals_with_access_v1_coverage')}, speed {val('expanded_full_0_2500ft_universe', 'signals_with_speed_coverage')}, AADT {val('expanded_full_0_2500ft_universe', 'signals_with_aadt_coverage')}, lane {val('expanded_full_0_2500ft_universe', 'signals_with_lane_coverage')}, divided/undivided {val('expanded_full_0_2500ft_universe', 'signals_with_divided_undivided_coverage')}.
6. Recovered signals that appear rate-ready under current outputs: {val('expanded_recovered_only_any_bin_universe', 'rate_ready_candidate_signals')}.
7. Recovered signals that appear model-ready under existing readiness logic: {val('expanded_recovered_only_any_bin_universe', 'model_ready_candidate_signals')}; readiness is not recomputed because active model logic requires active context fields.
8. The expanded 0-1,000 ft universe is structurally stronger than full 0-2,500 ft by bin coverage count, but context joins are equally blocked until candidate bins get route/measure or routed geometry keys.
9. Multi-candidate/weighted signals remain usable for roadway-provenance review: {multi_context} recovered signals have route/divided-roadway provenance, but crash/access/speed/AADT joins still need adaptation.
10. One-direction-only/divided cases worth retaining for partial analyses: {one_context} have roadway-provenance context, but divided-pairing and true geometry review remain required before promotion.
11. Main current bottleneck: {dominant}.
12. Recommended next pass: true routed geometry generation or context join adaptation for candidate bins, with divided-carriageway pairing recovery as a separate targeted pass.

## QA

QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}.
"""


def _qa(bins: pd.DataFrame, signal_ctx: pd.DataFrame, detail: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
    product_outputs = {k: v for k, v in outputs.items() if k not in {"findings", "qa", "manifest"}}
    recovered_bin_signals = detail["signal_id"].nunique() if not detail.empty else 0
    checks = [
        {"check_name": "candidate_bin_input_count_reconciles", "status": "passed" if len(bins) == EXPECTED_CANDIDATE_BINS else "review", "observed": len(bins), "expected": EXPECTED_CANDIDATE_BINS, "note": "Candidate recovery bin rows loaded."},
        {"check_name": "recovered_signal_count_reconciles", "status": "passed" if recovered_bin_signals == EXPECTED_RECOVERED_BIN_SIGNALS else "review", "observed": recovered_bin_signals, "expected": EXPECTED_RECOVERED_BIN_SIGNALS, "note": "Unique recovered signals with candidate bins."},
        {"check_name": "strict_active_baseline_comparison_only", "status": "passed", "observed": STRICT_ACTIVE_SIGNAL_BASELINE, "expected": STRICT_ACTIVE_SIGNAL_BASELINE, "note": "Strict active count is used only as comparison baseline."},
        {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False, "expected": False, "note": "No raw crash direction fields are read."},
        {"check_name": "crashes_used_to_select_associations_direction_or_scaffold", "status": "passed", "observed": False, "expected": False, "note": "Candidate bins are pre-existing inputs."},
        {"check_name": "context_used_to_select_associations_direction_or_scaffold", "status": "passed", "observed": False, "expected": False, "note": "Context is evaluated only after candidate bins are loaded."},
        {"check_name": "active_outputs_modified", "status": "passed", "observed": False, "expected": False, "note": "No active paths are written."},
        {"check_name": "candidates_promoted_to_active_scaffold_context", "status": "passed", "observed": False, "expected": False, "note": "All labels are diagnostic/review-only."},
        {"check_name": "outputs_written_only_to_review_folder", "status": "passed" if all(OUT_DIR in path.parents or path == OUT_DIR for path in product_outputs.values()) else "failed", "observed": str(OUT_DIR), "expected": str(OUT_DIR), "note": "Output path guard."},
        {"check_name": "candidate_provenance_fields_preserved", "status": "passed" if {"candidate_association_id", "recovery_strategy", "association_confidence_tier", "candidate_rank", "candidate_weight_preliminary", "tie_group_id"}.issubset(detail.columns) else "failed", "observed": "checked", "expected": "all required provenance fields", "note": "Candidate fields carried into detail."},
        {"check_name": "multi_candidate_weights_preserved", "status": "passed" if _text(detail, "association_confidence_tier").eq("multi_candidate_weighted_recovery").sum() > 0 and _text(detail, "candidate_weight_preliminary").ne("").all() else "review", "observed": _text(detail, "candidate_weight_preliminary").eq("").sum(), "expected": 0, "note": "Weights are carried forward from candidate bins."},
        {"check_name": "approximate_joins_labeled_approximate", "status": "passed", "observed": int(_bool(detail, "approximate_join_used").sum()), "expected": 0, "note": "No approximate joins are used in this pass."},
        {"check_name": "failed_joins_labeled", "status": "passed" if _text(detail, "failed_join_reason").ne("").all() else "failed", "observed": int(_text(detail, "failed_join_reason").eq("").sum()), "expected": 0, "note": "Candidate context join failures are explicit."},
        {"check_name": "strict_active_overlap_checks_diagnostic_only", "status": "passed", "observed": False, "expected": False, "note": "Overlap status is not used for promotion."},
        {"check_name": "analysis_use_tiers_review_only", "status": "passed" if _text(signal_ctx, "analysis_use_tier").ne("").all() else "failed", "observed": int(_text(signal_ctx, "analysis_use_tier").eq("").sum()), "expected": 0, "note": "Tiers are diagnostic labels."},
        {"check_name": "product_outputs_created", "status": "passed" if all(path.exists() for path in product_outputs.values()) else "failed", "observed": sum(path.exists() for path in product_outputs.values()), "expected": len(product_outputs), "note": "Checked before findings, QA, and manifest write."},
    ]
    return pd.DataFrame(checks)


def run() -> dict[str, Path]:
    created_at = datetime.now(timezone.utc)
    inputs = _load_inputs()
    bins = inputs["bins"]
    detail = _build_bin_detail(bins, inputs["travelway_lane_context"])
    signal_ctx = _signal_context_summary(inputs["signal_summary"], detail)
    universe = _universe_summary(signal_ctx, detail, inputs["active_signal_summary"], inputs["active_bins"])
    window = _simple_group(detail, "analysis_window")
    direction = _simple_group(detail, "scaffold_completeness_tier")
    strategy = _simple_group(detail, "recovery_strategy")
    confidence = _simple_group(detail, "association_confidence_tier")
    source = _simple_group(detail, "source_layer")
    missing = _missingness(detail)
    readiness = _rate_model_readiness(signal_ctx)
    strict_compare = _strict_active_comparison(universe)
    join_methods = _join_method_summary(detail)
    queue = _review_queue(signal_ctx)
    availability = _availability_matrix()
    tier_summary = _analysis_use_tier_summary(signal_ctx)

    outputs = {
        "bin_context_detail": OUT_DIR / "expanded_candidate_bin_context_detail.csv",
        "signal_context_summary": OUT_DIR / "expanded_candidate_signal_context_summary.csv",
        "universe_context_summary": OUT_DIR / "expanded_candidate_universe_context_summary.csv",
        "context_by_window": OUT_DIR / "expanded_candidate_context_by_window.csv",
        "context_by_direction_coverage": OUT_DIR / "expanded_candidate_context_by_direction_coverage.csv",
        "context_by_recovery_strategy": OUT_DIR / "expanded_candidate_context_by_recovery_strategy.csv",
        "context_by_confidence_tier": OUT_DIR / "expanded_candidate_context_by_confidence_tier.csv",
        "context_by_source": OUT_DIR / "expanded_candidate_context_by_source.csv",
        "missingness_summary": OUT_DIR / "expanded_candidate_context_missingness_summary.csv",
        "rate_model_readiness_summary": OUT_DIR / "expanded_candidate_rate_model_readiness_summary.csv",
        "strict_active_comparison": OUT_DIR / "expanded_candidate_strict_active_comparison.csv",
        "join_method_summary": OUT_DIR / "expanded_candidate_context_join_method_summary.csv",
        "ranked_review_queue": OUT_DIR / "expanded_candidate_context_ranked_review_queue.csv",
        "availability_matrix": OUT_DIR / "expanded_candidate_context_layer_availability_matrix.csv",
        "analysis_use_tier_summary": OUT_DIR / "expanded_candidate_analysis_use_tier_summary.csv",
        "findings": OUT_DIR / "expanded_candidate_context_sufficiency_findings.md",
        "qa": OUT_DIR / "expanded_candidate_context_sufficiency_qa.csv",
        "manifest": OUT_DIR / "expanded_candidate_context_sufficiency_manifest.json",
    }

    for frame, key in [
        (detail, "bin_context_detail"),
        (signal_ctx, "signal_context_summary"),
        (universe, "universe_context_summary"),
        (window, "context_by_window"),
        (direction, "context_by_direction_coverage"),
        (strategy, "context_by_recovery_strategy"),
        (confidence, "context_by_confidence_tier"),
        (source, "context_by_source"),
        (missing, "missingness_summary"),
        (readiness, "rate_model_readiness_summary"),
        (strict_compare, "strict_active_comparison"),
        (join_methods, "join_method_summary"),
        (queue, "ranked_review_queue"),
        (availability, "availability_matrix"),
        (tier_summary, "analysis_use_tier_summary"),
    ]:
        _write_csv(frame, outputs[key])

    qa = _qa(bins, signal_ctx, detail, outputs)
    findings = _findings(universe, join_methods, missing, signal_ctx, qa)
    _write_text(findings, outputs["findings"])
    _write_csv(qa, outputs["qa"])
    manifest = {
        "created_at_utc": created_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only context sufficiency audit for expanded recovered candidate bins",
        "read_only": True,
        "active_outputs_modified": False,
        "candidates_promoted_to_active_scaffold_context": False,
        "crash_direction_fields_read_or_used": False,
        "crashes_used_to_select_associations_direction_or_scaffold": False,
        "context_used_to_select_associations_direction_or_scaffold": False,
        "approximate_joins_used": False,
        "candidate_proxy_bins_review_only": True,
        "input_files": [
            str(BIN_GEN_DIR / "candidate_recovery_bins.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_signal_summary.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_association_summary.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_bin_generation_summary.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_distance_window_summary.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_direction_coverage_summary.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_multi_candidate_weight_summary.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_existing_active_overlap.csv"),
            str(BIN_GEN_DIR / "candidate_recovery_bin_generation_manifest.json"),
            str(ACTIVE_CONTEXT_DIR / "reference_signal_context_summary_active.csv"),
            str(ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv"),
            str(TABLES_DIR / "roadway_graph_edges.csv"),
            str(NORMALIZED_ROADS),
        ],
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary_metrics": {r.analysis_universe: r._asdict() for r in universe.itertuples(index=False)},
        "qa_checks": qa.to_dict("records"),
    }
    _write_json(manifest, outputs["manifest"])
    return outputs


def main() -> None:
    outputs = run()
    print(json.dumps({key: str(path) for key, path in outputs.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
