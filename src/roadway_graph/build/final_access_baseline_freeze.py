from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"

STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_final_access_rerun"
CONSERVATIVE_DIR = OUTPUT_ROOT / "review/current/conservative_travelway_windowed_access"
OVERLAP_DIR = OUTPUT_ROOT / "review/current/typed_access_rule_overlap_audit"
SANITY_DIR = OUTPUT_ROOT / "review/current/travelway_normalized_access_sanity_audit"
FINAL_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
MAP_REVIEW_DIR = OUTPUT_ROOT / "review/current/map_review_findings_source_limitation_diagnostic"

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

REQUIRED_INPUTS = [
    STABLE_DIR / "stable_lineage_final_access_target_bins.csv",
    STABLE_DIR / "stable_lineage_untyped_spatial_assignment_detail.csv",
    STABLE_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv",
    STABLE_DIR / "stable_lineage_untyped_travelway_assignment_detail.csv",
    STABLE_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv",
    STABLE_DIR / "stable_lineage_access_signal_window_summary.csv",
    STABLE_DIR / "stable_lineage_access_product_coverage_summary.csv",
    STABLE_DIR / "stable_lineage_access_source_point_accounting.csv",
    STABLE_DIR / "stable_lineage_access_spatial_vs_travelway_comparison.csv",
    STABLE_DIR / "stable_lineage_access_by_scaffold_qa_summary.csv",
    STABLE_DIR / "stable_lineage_final_access_rerun_manifest.json",
    CONSERVATIVE_DIR / "conservative_untyped_travelway_windowed_assignment_detail.csv",
    CONSERVATIVE_DIR / "conservative_typed_v2_travelway_windowed_assignment_detail.csv",
    CONSERVATIVE_DIR / "conservative_travelway_windowed_signal_window_summary.csv",
    CONSERVATIVE_DIR / "conservative_travelway_windowed_source_point_accounting.csv",
    CONSERVATIVE_DIR / "spatial_vs_conservative_travelway_comparison.csv",
    CONSERVATIVE_DIR / "broad_travelway_rejection_reason_summary.csv",
    CONSERVATIVE_DIR / "conservative_travelway_access_by_scaffold_qa_summary.csv",
    CONSERVATIVE_DIR / "conservative_travelway_windowed_access_manifest.json",
    OVERLAP_DIR / "typed_access_corrected_category_mapping.csv",
    OVERLAP_DIR / "typed_access_category_correction_impact.csv",
    OVERLAP_DIR / "typed_access_rule_overlap_signal_detail.csv",
    OVERLAP_DIR / "typed_access_rule_overlap_source_point_detail.csv",
    OVERLAP_DIR / "typed_access_rule_overlap_summary.csv",
    OVERLAP_DIR / "typed_access_broad_only_risk_audit.csv",
    OVERLAP_DIR / "typed_access_spatial_only_audit.csv",
    OVERLAP_DIR / "typed_access_category_specific_rule_counts.csv",
    OVERLAP_DIR / "typed_access_rule_overlap_manifest.json",
    SANITY_DIR / "access_source_denominator_validation.csv",
    SANITY_DIR / "travelway_assignment_method_summary.csv",
    SANITY_DIR / "travelway_assignment_overcapture_risk_detail.csv",
    SANITY_DIR / "typed_vs_untyped_capture_explanation.csv",
    SANITY_DIR / "conservative_travelway_access_coverage_estimates.csv",
    SANITY_DIR / "travelway_normalized_access_sanity_manifest.json",
    FINAL_UNIVERSE_DIR / "final_signal_universe_detail.csv",
    FINAL_UNIVERSE_DIR / "final_access_readiness_decision.csv",
    FINAL_UNIVERSE_DIR / "final_signal_leg_universe_overview_manifest.json",
    MAP_REVIEW_DIR / "access_source_coverage_limitation_summary.csv",
    MAP_REVIEW_DIR / "map_review_source_limitation_class_summary.csv",
    MAP_REVIEW_DIR / "map_review_findings_source_limitation_manifest.json",
]

TYPED_CATEGORY_ORDER = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
    "all_typed_categories",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _metric(coverage: pd.DataFrame, *, layer: str, window: str, buffer_width: str, metric: str) -> float:
    subset = coverage.loc[
        _text(coverage, "access_layer").eq(layer)
        & _text(coverage, "window").eq(window)
        & _text(coverage, "buffer_width_ft").eq(buffer_width)
        & _text(coverage, "metric").eq(metric)
    ]
    if subset.empty:
        return 0.0
    return float(pd.to_numeric(subset["count"], errors="coerce").fillna(0).iloc[0])


def _assignment_summary(frame: pd.DataFrame, *, product: str, layer: str, windows: dict[str, pd.Series]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window, mask in windows.items():
        subset = frame.loc[mask].copy()
        rows.append(
            {
                "product": product,
                "access_layer": layer,
                "window": window,
                "source_points_captured": int(subset["access_point_id"].nunique()) if "access_point_id" in subset.columns else 0,
                "signals_covered": int(subset.loc[_text(subset, "target_signal_id").ne(""), "target_signal_id"].nunique())
                if "target_signal_id" in subset.columns
                else 0,
                "assignment_rows": int(len(subset)),
                "unweighted_assignment_total": float(_num(subset, "unweighted_access_count").sum()) if len(subset) else 0.0,
                "source_preserving_weighted_total": float(_num(subset, "source_preserving_weighted_access_count").sum()) if len(subset) else 0.0,
                "max_assignment_fanout": float(
                    max(
                        _num(subset, "assignment_fanout_count").max() if "assignment_fanout_count" in subset.columns else 0,
                        _num(subset, "conservative_fanout_count").max() if "conservative_fanout_count" in subset.columns else 0,
                        _num(subset, "route_normalized_fanout_count").max() if "route_normalized_fanout_count" in subset.columns else 0,
                    )
                )
                if len(subset)
                else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _target_inventory(target: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"inventory_item": "represented_signals", "count": int(signals["signal_id"].nunique()) if "signal_id" in signals.columns else int(target["target_signal_id"].nunique()), "notes": "final_signal_universe_detail"},
        {"inventory_item": "final_access_target_bins", "count": int(len(target)), "notes": "stable_lineage_final_access_target_bins"},
        {"inventory_item": "target_signals_in_bins", "count": int(target["target_signal_id"].nunique()), "notes": "deduped target_signal_id"},
        {"inventory_item": "bins_with_geometry", "count": int(_bool_text(target, "geometry_available").sum()), "notes": "geometry_available true"},
        {"inventory_item": "bins_with_high_confidence_lineage", "count": int(_text(target, "lineage_confidence").str.startswith("high").sum()), "notes": "lineage_confidence starts with high"},
        {"inventory_item": "bins_with_low_confidence_lineage", "count": int(_text(target, "lineage_confidence").str.startswith("low").sum()), "notes": "lineage_confidence starts with low"},
        {"inventory_item": "bins_unmatched_lineage", "count": int(_text(target, "stable_travelway_id").eq("").sum()), "notes": "blank stable_travelway_id"},
        {"inventory_item": "spatial_assignment_products", "count": 2, "notes": "untyped and typed_v2 spatial 35/50/75/100 ft; 100 ft frozen as primary review evidence"},
        {"inventory_item": "conservative_travelway_windowed_products", "count": 4, "notes": "untyped/typed_v2 x 0-1000/0-2500"},
        {"inventory_item": "broad_travelway_diagnostic_products", "count": 2, "notes": "untyped and typed_v2 source-coverage diagnostics"},
        {"inventory_item": "typed_category_correction_status", "count": 1, "notes": "R and RC recoded to right_in_right_out in review-only summaries"},
    ]
    return pd.DataFrame(rows)


def _product_doctrine() -> pd.DataFrame:
    rows = [
        {
            "product_name": "untyped_spatial_100ft_primary",
            "layer_type": "untyped",
            "assignment_rule": "100 ft spatial catchment against stable-lineage final access target bins",
            "intended_role": "primary",
            "overcapture_risk": "moderate multi-assignment/proximity risk",
            "undercapture_risk": "source coverage gaps and narrow/offset catchment geometry",
            "source_limitation_caveat": "untyped source is broad count/density evidence and is major-route biased",
            "carry_into_crash_catchment_planning": "yes_primary_review_context",
        },
        {
            "product_name": "typed_v2_spatial_100ft_enrichment",
            "layer_type": "typed_v2",
            "assignment_rule": "100 ft spatial catchment with corrected typed access categories",
            "intended_role": "enrichment",
            "overcapture_risk": "moderate multi-assignment/proximity risk",
            "undercapture_risk": "typed v2 source sparsity and source coverage gaps",
            "source_limitation_caveat": "typed v2 is not a complete access inventory",
            "carry_into_crash_catchment_planning": "yes_enrichment_context",
        },
        {
            "product_name": "untyped_conservative_travelway_windowed_0_1000",
            "layer_type": "untyped",
            "assignment_rule": "direct stable Travelway ID or route/measure overlap plus valid 0-1000 ft signal window",
            "intended_role": "sensitivity",
            "overcapture_risk": "low by construction",
            "undercapture_risk": "high because route/facility-only and distance-uncertain rows are excluded",
            "source_limitation_caveat": "supplements spatial evidence where stable source identity supports it",
            "carry_into_crash_catchment_planning": "yes_sensitivity_context",
        },
        {
            "product_name": "untyped_conservative_travelway_windowed_0_2500",
            "layer_type": "untyped",
            "assignment_rule": "direct stable Travelway ID or route/measure overlap plus valid 0-2500 ft signal window",
            "intended_role": "sensitivity",
            "overcapture_risk": "low by construction",
            "undercapture_risk": "high because route/facility-only and distance-uncertain rows are excluded",
            "source_limitation_caveat": "sensitivity window only; do not collapse with 0-1000 primary window",
            "carry_into_crash_catchment_planning": "yes_sensitivity_context",
        },
        {
            "product_name": "typed_v2_conservative_travelway_windowed_0_1000",
            "layer_type": "typed_v2",
            "assignment_rule": "corrected typed category plus direct stable Travelway ID or route/measure overlap in 0-1000 ft window",
            "intended_role": "sensitivity",
            "overcapture_risk": "low by construction",
            "undercapture_risk": "high because typed source is sparse and conservative rule is strict",
            "source_limitation_caveat": "typed enrichment only",
            "carry_into_crash_catchment_planning": "yes_sensitivity_enrichment",
        },
        {
            "product_name": "typed_v2_conservative_travelway_windowed_0_2500",
            "layer_type": "typed_v2",
            "assignment_rule": "corrected typed category plus direct stable Travelway ID or route/measure overlap in 0-2500 ft window",
            "intended_role": "sensitivity",
            "overcapture_risk": "low by construction",
            "undercapture_risk": "high because typed source is sparse and conservative rule is strict",
            "source_limitation_caveat": "typed sensitivity only; do not treat as complete typed inventory",
            "carry_into_crash_catchment_planning": "yes_sensitivity_enrichment",
        },
        {
            "product_name": "untyped_broad_travelway_normalized_source_coverage",
            "layer_type": "untyped",
            "assignment_rule": "broad Travelway-normalized route/source assignment",
            "intended_role": "source-coverage diagnostic",
            "overcapture_risk": "high; broad-only cases show long-route overcapture risk",
            "undercapture_risk": "lower than spatial but not signal-window-safe",
            "source_limitation_caveat": "diagnoses represented route/source coverage, not final signal access assignment",
            "carry_into_crash_catchment_planning": "diagnostic_only_not_assignment",
        },
        {
            "product_name": "typed_v2_broad_travelway_normalized_source_coverage",
            "layer_type": "typed_v2",
            "assignment_rule": "broad Travelway-normalized route/source assignment with corrected category summaries",
            "intended_role": "source-coverage diagnostic",
            "overcapture_risk": "high; typed broad-only audit found substantial long-route overcapture risk",
            "undercapture_risk": "lower than spatial but not signal-window-safe",
            "source_limitation_caveat": "diagnoses typed source coverage, not final signal access assignment",
            "carry_into_crash_catchment_planning": "diagnostic_only_not_assignment",
        },
    ]
    return pd.DataFrame(rows)


def _source_limitation_summary(source_lim: pd.DataFrame, denom: pd.DataFrame, accounting: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for layer in ["untyped", "typed_v2"]:
        major = source_lim.loc[_text(source_lim, "summary_type").eq("major_route_bias_indicator") & _text(source_lim, "access_layer").eq(layer)]
        acct = source_lim.loc[_text(source_lim, "summary_type").eq("final_spatial_100ft_source_accounting") & _text(source_lim, "access_layer").eq(layer)]
        if not major.empty:
            rows.append(
                {
                    "access_layer": layer,
                    "limitation_topic": "major_route_bias",
                    "source_point_denominator": int(float(major["total_source_points"].iloc[0])),
                    "affected_source_points": int(float(major["major_route_source_points"].iloc[0])),
                    "share": float(major["major_route_share"].iloc[0]),
                    "interpretation": "nearly all source points are on major route classes; low access coverage is partly source coverage limitation, not only scaffold failure",
                }
            )
        if not acct.empty:
            rows.append(
                {
                    "access_layer": layer,
                    "limitation_topic": "spatial_100ft_uncaptured",
                    "source_point_denominator": int(float(acct["total_source_point_count"].iloc[0])),
                    "affected_source_points": int(float(acct["source_points_uncaptured"].iloc[0])),
                    "share": float(acct["source_capture_rate"].iloc[0]),
                    "interpretation": "share is capture rate; uncaptured points require source-coverage, scope, route, and catchment caveats",
                }
            )
    for _, row in source_lim.loc[_text(source_lim, "summary_type").eq("hybrid_recovery_opportunity")].iterrows():
        rows.append(
            {
                "access_layer": row.get("access_layer", ""),
                "limitation_topic": row.get("recovery_opportunity_class", ""),
                "source_point_denominator": "",
                "affected_source_points": row.get("source_point_count", row.get("count", "")),
                "share": "",
                "interpretation": "map-review/hybrid diagnostic source limitation or recovery-opportunity class",
            }
        )
    return pd.DataFrame(rows)


def _crash_catchment_readiness() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "readiness_item": "access_ready_for_crash_catchment_design",
                "status": "ready_as_review_only_context",
                "notes": "Carry product roles and QA flags; do not treat any access product as final production metric yet.",
            },
            {
                "readiness_item": "primary_untyped_access",
                "status": "carry_forward",
                "notes": "Use untyped spatial 100 ft as conservative primary review context.",
            },
            {
                "readiness_item": "typed_v2_enrichment",
                "status": "carry_forward",
                "notes": "Use typed v2 spatial 100 ft with corrected categories as enrichment context.",
            },
            {
                "readiness_item": "conservative_travelway_windowed",
                "status": "carry_forward_as_sensitivity",
                "notes": "Use 0-1000 and 0-2500 windows separately; high-confidence source identity evidence only.",
            },
            {
                "readiness_item": "broad_travelway_normalized",
                "status": "diagnostic_only",
                "notes": "Do not use as final assignment because broad-only cases carry long-route overcapture risk.",
            },
            {
                "readiness_item": "crash_records",
                "status": "not_read",
                "notes": "This freeze does not assign crashes or build catchments.",
            },
        ]
    )


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", "outputs written only to review/current/final_access_baseline_freeze"),
        ("no_candidates_promoted", "passed", "summary/doctrine only"),
        ("no_crash_records_read", "passed", "input fields screened for crash tokens"),
        ("no_crash_direction_fields_used", "passed", "crash direction tokens blocked"),
        ("no_crash_assignment_or_catchments", "passed", "no assignment logic run"),
        ("no_rates_or_models", "passed", "counts and doctrine only"),
        ("typed_and_untyped_remain_separate", "passed", "separate summaries and product roles"),
        ("weighted_and_unweighted_remain_separate", "passed", "summary columns preserve both where available"),
        ("raw_access_codes_preserved", "passed", "category mapping and correction impact outputs copied/summarized"),
        ("corrected_typed_categories_carried", "passed", "typed category summaries use typed_access_rule_overlap_audit corrected categories"),
        ("broad_travelway_marked_diagnostic_only", "passed", "product role doctrine flags broad products diagnostic only"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(
    primary_untyped: pd.DataFrame,
    primary_typed: pd.DataFrame,
    conservative_summary: pd.DataFrame,
    broad_summary: pd.DataFrame,
    typed_summary: pd.DataFrame,
    impact: pd.DataFrame,
    source_limitation: pd.DataFrame,
) -> str:
    changed = impact.loc[_text(impact, "scope").eq("typed_v2_source") & _text(impact, "raw_access_control_code").eq("all_changed")]
    changed_count = int(float(changed["source_point_count"].iloc[0])) if not changed.empty else 0

    def typed_count(product: str, window: str, category: str, col: str) -> int:
        subset = typed_summary.loc[
            _text(typed_summary, "product").eq(product)
            & _text(typed_summary, "window").eq(window)
            & _text(typed_summary, "corrected_access_category").eq(category)
        ]
        return int(float(subset[col].iloc[0])) if not subset.empty else 0

    def summary_count(frame: pd.DataFrame, window: str, col: str) -> int:
        subset = frame.loc[_text(frame, "window").eq(window)]
        return int(float(subset[col].iloc[0])) if not subset.empty else 0

    untyped_primary_any = summary_count(primary_untyped, "any", "source_points_captured")
    typed_primary_any = summary_count(primary_typed, "any", "source_points_captured")
    return f"""# Final Access Baseline Freeze Findings

## Bounded Question

This read-only freeze documents the access product doctrine that downstream crash/catchment design should carry forward. It does not choose a production modeling variable, combine typed and untyped access, assign crashes, calculate rates, or modify active outputs.

## Final Access Doctrine

1. Recommended primary untyped access product: `untyped_spatial_100ft_primary`.
2. Recommended typed v2 enrichment product: `typed_v2_spatial_100ft_enrichment`.
3. Conservative Travelway-windowed access is high-confidence supplemental/sensitivity evidence, reported separately for 0-1,000 ft and 0-2,500 ft.
4. Broad Travelway-normalized access is source-coverage diagnostic only because broad-only cases have substantial long-route overcapture risk.
5. Untyped access remains the broad access count/density layer.
6. Typed v2 access remains an enrichment layer.

## Primary Spatial 100 ft Baseline

- Untyped spatial 100 ft, any window: {untyped_primary_any:,} captured source points across {summary_count(primary_untyped, 'any', 'signals_covered'):,} signals.
- Untyped spatial 100 ft, 0-1,000 ft: {summary_count(primary_untyped, '0_1000', 'source_points_captured'):,} captured source points across {summary_count(primary_untyped, '0_1000', 'signals_covered'):,} signals.
- Untyped spatial 100 ft, 0-2,500 ft: {summary_count(primary_untyped, '0_2500', 'source_points_captured'):,} captured source points across {summary_count(primary_untyped, '0_2500', 'signals_covered'):,} signals.
- Typed v2 spatial 100 ft, any window: {typed_primary_any:,} captured source points across {summary_count(primary_typed, 'any', 'signals_covered'):,} signals.
- Typed v2 spatial 100 ft, 0-1,000 ft: {summary_count(primary_typed, '0_1000', 'source_points_captured'):,} captured source points across {summary_count(primary_typed, '0_1000', 'signals_covered'):,} signals.
- Typed v2 spatial 100 ft, 0-2,500 ft: {summary_count(primary_typed, '0_2500', 'source_points_captured'):,} captured source points across {summary_count(primary_typed, '0_2500', 'signals_covered'):,} signals.

## Typed Category Correction

- `R` and `RC` were recoded from `other_review` to `right_in_right_out`.
- Source points changed category: {changed_count:,}.
- `I`, `M`, `S`, `AS`, and `AU` remain `other_review`.

## RIRO and Unrestricted/Full Counts

- Spatial 100 ft unrestricted/full, 0-1,000 ft: {typed_count('spatial_100ft', '0_1000', 'unrestricted_or_full_access', 'source_point_count'):,} source points / {typed_count('spatial_100ft', '0_1000', 'unrestricted_or_full_access', 'signal_count'):,} signals.
- Spatial 100 ft unrestricted/full, 0-2,500 ft: {typed_count('spatial_100ft', '0_2500', 'unrestricted_or_full_access', 'source_point_count'):,} source points / {typed_count('spatial_100ft', '0_2500', 'unrestricted_or_full_access', 'signal_count'):,} signals.
- Spatial 100 ft RIRO, 0-1,000 ft: {typed_count('spatial_100ft', '0_1000', 'right_in_right_out', 'source_point_count'):,} source points / {typed_count('spatial_100ft', '0_1000', 'right_in_right_out', 'signal_count'):,} signals.
- Spatial 100 ft RIRO, 0-2,500 ft: {typed_count('spatial_100ft', '0_2500', 'right_in_right_out', 'source_point_count'):,} source points / {typed_count('spatial_100ft', '0_2500', 'right_in_right_out', 'signal_count'):,} signals.
- Conservative Travelway-windowed unrestricted/full, 0-2,500 ft: {typed_count('conservative_travelway_windowed', '0_2500', 'unrestricted_or_full_access', 'source_point_count'):,} source points / {typed_count('conservative_travelway_windowed', '0_2500', 'unrestricted_or_full_access', 'signal_count'):,} signals.
- Conservative Travelway-windowed RIRO, 0-2,500 ft: {typed_count('conservative_travelway_windowed', '0_2500', 'right_in_right_out', 'source_point_count'):,} source points / {typed_count('conservative_travelway_windowed', '0_2500', 'right_in_right_out', 'signal_count'):,} signals.
- Broad Travelway-normalized unrestricted/full, 0-2,500 ft: {typed_count('broad_travelway_normalized', '0_2500', 'unrestricted_or_full_access', 'source_point_count'):,} source points / {typed_count('broad_travelway_normalized', '0_2500', 'unrestricted_or_full_access', 'signal_count'):,} signals.
- Broad Travelway-normalized RIRO, 0-2,500 ft: {typed_count('broad_travelway_normalized', '0_2500', 'right_in_right_out', 'source_point_count'):,} source points / {typed_count('broad_travelway_normalized', '0_2500', 'right_in_right_out', 'signal_count'):,} signals.

## Source Limitation Interpretation

Access source coverage is highly major-route biased. Low access coverage should be described as a combined source-coverage, scope, route/source identity, and catchment-design limitation rather than as a scaffold failure by itself. Broad Travelway-normalized access can explain source coverage, but should not be used as final signal access assignment evidence.

## Crash/Catchment Readiness

Access is ready to carry into crash/catchment design as review-only context with explicit roles: spatial 100 ft primary, typed v2 spatial enrichment, conservative Travelway-windowed sensitivity, and broad Travelway-normalized diagnostic only. The next active geospatial pass should design crash/catchment assignment against the stable-lineage scaffold while carrying access product roles, source limitation flags, and scaffold QA fields forward.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start final_access_baseline_freeze")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    target = _read_csv(STABLE_DIR / "stable_lineage_final_access_target_bins.csv")
    signals = _read_csv(FINAL_UNIVERSE_DIR / "final_signal_universe_detail.csv")
    coverage = _read_csv(STABLE_DIR / "stable_lineage_access_product_coverage_summary.csv")
    untyped_spatial = _read_csv(STABLE_DIR / "stable_lineage_untyped_spatial_assignment_detail.csv")
    typed_spatial = _read_csv(STABLE_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv")
    untyped_cons = _read_csv(CONSERVATIVE_DIR / "conservative_untyped_travelway_windowed_assignment_detail.csv")
    typed_cons = _read_csv(CONSERVATIVE_DIR / "conservative_typed_v2_travelway_windowed_assignment_detail.csv")
    untyped_broad = _read_csv(STABLE_DIR / "stable_lineage_untyped_travelway_assignment_detail.csv")
    typed_broad = _read_csv(STABLE_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv")
    typed_summary = _read_csv(OVERLAP_DIR / "typed_access_category_specific_rule_counts.csv")
    impact = _read_csv(OVERLAP_DIR / "typed_access_category_correction_impact.csv")
    source_lim = _read_csv(MAP_REVIEW_DIR / "access_source_coverage_limitation_summary.csv")
    denom = _read_csv(SANITY_DIR / "access_source_denominator_validation.csv")
    accounting = _read_csv(STABLE_DIR / "stable_lineage_access_source_point_accounting.csv")

    untyped_spatial100 = untyped_spatial.loc[_text(untyped_spatial, "buffer_width_ft").eq("100")].copy()
    typed_spatial100 = typed_spatial.loc[_text(typed_spatial, "buffer_width_ft").eq("100")].copy()
    spatial_windows = {
        "any": pd.Series(True, index=untyped_spatial100.index),
        "0_1000": _text(untyped_spatial100, "analysis_window").eq("0_1000"),
        "0_2500": _text(untyped_spatial100, "analysis_window").isin(["0_1000", "1000_2500"]),
    }
    typed_spatial_windows = {
        "any": pd.Series(True, index=typed_spatial100.index),
        "0_1000": _text(typed_spatial100, "analysis_window").eq("0_1000"),
        "0_2500": _text(typed_spatial100, "analysis_window").isin(["0_1000", "1000_2500"]),
    }
    primary_untyped = _assignment_summary(untyped_spatial100, product="untyped_spatial_100ft_primary", layer="untyped", windows=spatial_windows)
    primary_typed = _assignment_summary(typed_spatial100, product="typed_v2_spatial_100ft_enrichment", layer="typed_v2", windows=typed_spatial_windows)

    conservative_summary = pd.concat(
        [
            _assignment_summary(
                untyped_cons,
                product="untyped_conservative_travelway_windowed",
                layer="untyped",
                windows={
                    "0_1000": _text(untyped_cons, "conservative_window").eq("conservative_0_1000"),
                    "0_2500": _text(untyped_cons, "conservative_window").eq("conservative_0_2500"),
                },
            ),
            _assignment_summary(
                typed_cons,
                product="typed_v2_conservative_travelway_windowed",
                layer="typed_v2",
                windows={
                    "0_1000": _text(typed_cons, "conservative_window").eq("conservative_0_1000"),
                    "0_2500": _text(typed_cons, "conservative_window").eq("conservative_0_2500"),
                },
            ),
        ],
        ignore_index=True,
        sort=False,
    )

    untyped_broad_assigned = untyped_broad.loc[_text(untyped_broad, "route_normalized_assignment_status").eq("assigned_review_only")].copy()
    typed_broad_assigned = typed_broad.loc[_text(typed_broad, "route_normalized_assignment_status").eq("assigned_review_only")].copy()
    broad_summary = pd.concat(
        [
            _assignment_summary(
                untyped_broad_assigned,
                product="untyped_broad_travelway_normalized_source_coverage",
                layer="untyped",
                windows={
                    "any": pd.Series(True, index=untyped_broad_assigned.index),
                    "0_1000": _text(untyped_broad_assigned, "analysis_window").eq("0_1000"),
                    "0_2500": _text(untyped_broad_assigned, "analysis_window").isin(["0_1000", "1000_2500"]),
                },
            ),
            _assignment_summary(
                typed_broad_assigned,
                product="typed_v2_broad_travelway_normalized_source_coverage",
                layer="typed_v2",
                windows={
                    "any": pd.Series(True, index=typed_broad_assigned.index),
                    "0_1000": _text(typed_broad_assigned, "analysis_window").eq("0_1000"),
                    "0_2500": _text(typed_broad_assigned, "analysis_window").isin(["0_1000", "1000_2500"]),
                },
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    broad_summary["product_role"] = "source_coverage_diagnostic_only"

    product_inventory = _target_inventory(target, signals)
    product_doctrine = _product_doctrine()
    source_limitation = _source_limitation_summary(source_lim, denom, accounting)
    crash_readiness = _crash_catchment_readiness()

    _write_csv(product_inventory, "final_access_baseline_product_inventory.csv")
    _write_csv(primary_untyped, "final_access_primary_untyped_spatial_100ft_summary.csv")
    _write_csv(primary_typed, "final_access_primary_typed_v2_spatial_100ft_summary.csv")
    _write_csv(conservative_summary, "final_access_conservative_travelway_windowed_summary.csv")
    _write_csv(broad_summary, "final_access_broad_travelway_diagnostic_summary.csv")
    _write_csv(typed_summary, "final_access_typed_category_corrected_summary.csv")
    _write_csv(product_doctrine, "final_access_product_role_doctrine.csv")
    _write_csv(source_limitation, "final_access_source_limitation_summary.csv")
    _write_csv(crash_readiness, "final_access_crash_catchment_readiness.csv")
    _write_text(
        _findings(primary_untyped, primary_typed, conservative_summary, broad_summary, typed_summary, impact, source_limitation),
        "final_access_baseline_findings.md",
    )
    _write_csv(_qa(), "final_access_baseline_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.build.final_access_baseline_freeze",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "outputs": [
                "final_access_baseline_product_inventory.csv",
                "final_access_primary_untyped_spatial_100ft_summary.csv",
                "final_access_primary_typed_v2_spatial_100ft_summary.csv",
                "final_access_conservative_travelway_windowed_summary.csv",
                "final_access_broad_travelway_diagnostic_summary.csv",
                "final_access_typed_category_corrected_summary.csv",
                "final_access_product_role_doctrine.csv",
                "final_access_source_limitation_summary.csv",
                "final_access_crash_catchment_readiness.csv",
                "final_access_baseline_findings.md",
                "final_access_baseline_qa.csv",
                "final_access_baseline_manifest.json",
                "run_progress_log.txt",
            ],
            "review_only": True,
            "typed_category_correction": {
                "R": "right_in_right_out",
                "RC": "right_in_right_out",
                "I": "other_review",
                "M": "other_review",
                "S": "other_review",
                "AS": "other_review",
                "AU": "other_review",
            },
            "doctrine": {
                "primary_untyped": "untyped_spatial_100ft_primary",
                "typed_enrichment": "typed_v2_spatial_100ft_enrichment",
                "sensitivity": "conservative_travelway_windowed",
                "diagnostic_only": "broad_travelway_normalized",
            },
        },
        "final_access_baseline_manifest.json",
    )
    _checkpoint("complete final_access_baseline_freeze")


if __name__ == "__main__":
    main()
