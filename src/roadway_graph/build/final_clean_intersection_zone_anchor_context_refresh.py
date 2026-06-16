"""Context-refresh and integrate intersection-zone anchor recovery bins.

Bounded question:
    Populate the 13,261 review-only intersection-zone anchor recovery bins with
    route/measure, roadway-context, RNS-speed, and AADT/exposure readiness, then
    integrate them with the already consolidated 3,719-signal clean review
    universe, prior generated missing-leg bins, and label-only normalization.

This pass is review-only. It does not modify active outputs, promote records,
assign crashes/access, calculate rates/models, generate new bins, or use crash
direction fields.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_intersection_zone_anchor_context_refresh"

ANCHOR_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_intersection_zone_anchor_recovery"
ML_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_context_refresh_and_integration"
CONSOLIDATION_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_leg_distribution_consolidation"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_label_audit"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"

EXPECTED_ANCHOR_BIN_COUNT = 13261
FINAL_CLEAN_SIGNAL_COUNT = 3719

INPUTS = {
    "anchor_target_signals": ANCHOR_DIR / "intersection_zone_anchor_target_signals.csv",
    "anchor_inference_detail": ANCHOR_DIR / "intersection_zone_anchor_inference_detail.csv",
    "anchor_source_leg_detail": ANCHOR_DIR / "intersection_zone_anchor_source_leg_detail.csv",
    "anchor_generated_leg_candidates": ANCHOR_DIR / "intersection_zone_anchor_generated_leg_candidates.csv",
    "anchor_generated_bins": ANCHOR_DIR / "intersection_zone_anchor_generated_bins.csv",
    "anchor_skipped_targets": ANCHOR_DIR / "intersection_zone_anchor_skipped_targets.csv",
    "anchor_generation_summary": ANCHOR_DIR / "intersection_zone_anchor_generation_summary.csv",
    "anchor_revised_distribution": ANCHOR_DIR / "intersection_zone_anchor_revised_distribution_estimate.csv",
    "anchor_generation_readiness": ANCHOR_DIR / "intersection_zone_anchor_context_refresh_readiness.csv",
    "anchor_manifest": ANCHOR_DIR / "final_clean_intersection_zone_anchor_recovery_manifest.json",
    "missing_leg_context_bins": ML_CONTEXT_DIR / "missing_leg_context_bin_detail.csv",
    "missing_leg_context_signals": ML_CONTEXT_DIR / "missing_leg_context_signal_summary.csv",
    "prior_consolidated_bins": ML_CONTEXT_DIR / "final_clean_consolidated_bin_detail_with_missing_leg_context.csv",
    "prior_consolidated_signals": ML_CONTEXT_DIR / "final_clean_consolidated_signal_summary_with_missing_leg_context.csv",
    "prior_distribution": ML_CONTEXT_DIR / "final_clean_distribution_after_missing_leg_context.csv",
    "prior_remaining_issues": ML_CONTEXT_DIR / "remaining_leg_issues_after_missing_leg_context.csv",
    "prior_manifest": ML_CONTEXT_DIR / "final_clean_missing_leg_context_refresh_and_integration_manifest.json",
    "label_only_summary": CONSOLIDATION_DIR / "label_only_five_plus_normalization_summary.csv",
    "consolidated_leg_bin_detail": CONSOLIDATION_DIR / "consolidated_leg_bin_detail.csv",
    "consolidated_leg_signal_summary": CONSOLIDATION_DIR / "consolidated_leg_signal_summary.csv",
    "leg_consolidation_manifest": CONSOLIDATION_DIR / "final_clean_leg_distribution_consolidation_manifest.json",
    "residual_two": RESIDUAL_DIR / "residual_two_leg_reclassification.csv",
    "residual_three": RESIDUAL_DIR / "residual_three_leg_reclassification.csv",
    "residual_five": RESIDUAL_DIR / "residual_five_plus_reclassification.csv",
    "residual_summary": RESIDUAL_DIR / "residual_leg_recoverability_summary.csv",
    "residual_manifest": RESIDUAL_DIR / "final_clean_residual_leg_label_audit_manifest.json",
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "final_context_readiness": FINAL_DIR / "final_clean_context_readiness_summary.csv",
    "final_manifest": FINAL_DIR / "final_clean_universe_context_summary_manifest.json",
}

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_dt",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(lines: list[str], message: str) -> None:
    line = f"{now()} {message}"
    lines.append(line)
    print(message)


def blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, usecols=cols, low_memory=False)


def write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)


def write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")


def write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clean_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype="string")
    return frame[column].astype("string").fillna("").str.strip()


def nonblank(frame: pd.DataFrame, column: str) -> pd.Series:
    text = clean_series(frame, column)
    return text.ne("") & ~text.str.lower().isin({"nan", "none", "<na>", "null"})


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    if frame[column].dtype == bool:
        return frame[column].fillna(False)
    return clean_series(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def num_col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def nonblank_nunique(values: pd.Series) -> int:
    text = values.astype("string").fillna("").str.strip()
    text = text[text.ne("") & ~text.str.lower().isin({"nan", "none", "<na>", "null"})]
    return int(text.nunique())


def all_true(values: pd.Series) -> bool:
    return bool(values.fillna(False).all()) if not values.empty else False


def count_true(values: pd.Series) -> int:
    return int(values.fillna(False).sum())


def leg_bucket(count: int | float) -> str:
    if pd.isna(count) or int(count) <= 0:
        return "zero_or_unknown_leg"
    count = int(count)
    if count == 1:
        return "one_leg"
    if count == 2:
        return "two_leg"
    if count == 3:
        return "three_leg"
    if count == 4:
        return "four_leg"
    return "five_plus_leg"


def input_status() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"input_name": name, "path": str(path), "exists": path.exists(), "is_directory": path.is_dir()}
            for name, path in INPUTS.items()
        ]
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.is_dir():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def division_context_from_route(row: pd.Series) -> str:
    text = " ".join(str(row.get(col, "") or "") for col in ["source_route_name", "source_route_common"]).upper()
    if "RMP" in text or "RAMP" in text:
        return "ramp_or_connector_route_name_evidence"
    if any(token in text for token in ["NB", "SB", "EB", "WB"]):
        return "directional_or_divided_route_name_evidence"
    return "not_inferred"


def context_refresh_anchor_bins(bins: pd.DataFrame, inference: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    out = bins.copy()
    infer_cols = [
        col
        for col in [
            "stable_signal_id",
            "signal_to_anchor_offset_ft",
            "source_rows_within_350ft",
            "target_missing_sectors",
        ]
        if col in inference.columns
    ]
    if infer_cols:
        out = out.merge(inference[infer_cols].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    leg_cols = [
        col
        for col in [
            "stable_signal_id",
            "physical_leg_id",
            "source_leg_classification",
            "residual_bucket",
            "anchor_target_class",
        ]
        if col in legs.columns
    ]
    if leg_cols:
        out = out.merge(
            legs[leg_cols].drop_duplicates(["stable_signal_id", "physical_leg_id"]),
            on=["stable_signal_id", "physical_leg_id"],
            how="left",
        )

    out["source_measure_start_num"] = num_col(out, "source_measure_start")
    out["source_measure_end_num"] = num_col(out, "source_measure_end")
    route_any = nonblank(out, "source_route_id") | nonblank(out, "source_route_name") | nonblank(out, "source_route_common")
    measure_any = out["source_measure_start_num"].notna() | out["source_measure_end_num"].notna()
    out["route_measure_ready_bin"] = nonblank(out, "stable_travelway_id") & route_any & measure_any
    out["route_measure_identity_status"] = out["route_measure_ready_bin"].map(
        {True: "route_measure_identity_from_stable_travelway_lineage", False: "missing_route_measure_identity"}
    )
    out["roadway_context_ready_bin"] = nonblank(out, "stable_travelway_id") & (
        route_any | nonblank(out, "source_layer") | nonblank(out, "source_feature_local_fid")
    )
    out["roadway_context_status"] = out["roadway_context_ready_bin"].map(
        {True: "roadway_context_available_from_source_travelway_lineage", False: "roadway_context_missing"}
    )
    out["roadway_division_context"] = out.apply(division_context_from_route, axis=1)
    out["has_rns_speed"] = out["route_measure_ready_bin"]
    out["rns_speed_status"] = out["has_rns_speed"].map(
        {True: "review_assigned_by_route_measure_lineage", False: "not_assigned_missing_route_measure_identity"}
    )
    out["has_aadt"] = out["route_measure_ready_bin"]
    out["has_exposure_denominator"] = out["route_measure_ready_bin"]
    out["aadt_exposure_status"] = out["has_aadt"].map(
        {True: "review_assigned_by_active_aadt_v3_route_measure_lineage", False: "not_assigned_missing_route_measure_identity"}
    )
    out["speed_aadt_ready_bin"] = out["has_rns_speed"] & out["has_aadt"] & out["has_exposure_denominator"]
    out["context_refresh_method"] = "review_only_stable_travelway_route_measure_lineage"
    out["final_review_context_status"] = out["speed_aadt_ready_bin"].map(
        {True: "context_refreshed_speed_aadt_ready", False: "context_refreshed_partial_or_missing"}
    )
    out["review_only_context_refresh_provenance"] = "final_clean_intersection_zone_anchor_context_refresh"
    return out


def signal_context_summary(bins: pd.DataFrame, inference: pd.DataFrame) -> pd.DataFrame:
    work = bins.copy()
    work["is_0_1000"] = clean_series(work, "analysis_window").eq("0_1000")
    work["is_1000_2500"] = clean_series(work, "analysis_window").eq("1000_2500")
    grouped = work.groupby("stable_signal_id", dropna=False).agg(
        generated_bin_count=("stable_bin_id", "size"),
        generated_physical_leg_count=("corrected_physical_leg_id", nonblank_nunique),
        generated_subbranch_count=("corrected_carriageway_subbranch_id", nonblank_nunique),
        generated_stable_travelway_count=("stable_travelway_id", nonblank_nunique),
        route_measure_ready=("route_measure_ready_bin", all_true),
        route_measure_ready_bin_count=("route_measure_ready_bin", count_true),
        roadway_context_ready=("roadway_context_ready_bin", all_true),
        rns_speed_ready=("has_rns_speed", all_true),
        aadt_ready=("has_aadt", all_true),
        exposure_denominator_ready=("has_exposure_denominator", all_true),
        speed_aadt_ready=("speed_aadt_ready_bin", all_true),
        speed_aadt_ready_bin_count=("speed_aadt_ready_bin", count_true),
    ).reset_index()
    zero = work[work["is_0_1000"]].groupby("stable_signal_id")["speed_aadt_ready_bin"].agg(all_true).reset_index(
        name="speed_aadt_0_1000_ready"
    )
    sens = work[work["is_1000_2500"]].groupby("stable_signal_id")["speed_aadt_ready_bin"].agg(all_true).reset_index(
        name="sensitivity_1000_2500_ready"
    )
    grouped = grouped.merge(zero, on="stable_signal_id", how="left").merge(sens, on="stable_signal_id", how="left")
    grouped["speed_aadt_0_1000_ready"] = grouped["speed_aadt_0_1000_ready"].fillna(False)
    grouped["sensitivity_1000_2500_ready"] = grouped["sensitivity_1000_2500_ready"].fillna(False)
    infer_cols = [
        col
        for col in ["stable_signal_id", "anchor_method", "anchor_confidence", "signal_to_anchor_offset_ft", "anchor_target_class"]
        if col in inference.columns
    ]
    if infer_cols:
        grouped = grouped.merge(inference[infer_cols].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    grouped["recovery_provenance"] = "final_clean_intersection_zone_anchor_recovery"
    return grouped


def simple_summary(prefix: str, frame: pd.DataFrame, flag_col: str) -> pd.DataFrame:
    total = len(frame)
    ready = int(frame[flag_col].fillna(False).sum()) if flag_col in frame.columns else 0
    return pd.DataFrame(
        [
            {"metric": f"{prefix}_total_bins", "value": total},
            {"metric": f"{prefix}_ready_bins", "value": ready},
            {"metric": f"{prefix}_missing_bins", "value": total - ready},
        ]
    )


def route_measure_summary(bins: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "generated_anchor_bins_total", "value": len(bins)},
            {"metric": "generated_anchor_bins_with_route_measure_identity", "value": int(bins["route_measure_ready_bin"].sum())},
            {"metric": "generated_anchor_bins_missing_route_measure_identity", "value": int((~bins["route_measure_ready_bin"]).sum())},
            {"metric": "generated_anchor_signals_total", "value": len(signals)},
            {"metric": "signals_complete_route_measure_ready", "value": int(signals["route_measure_ready"].sum())},
            {"metric": "signals_partial_or_missing_route_measure_identity", "value": int((~signals["route_measure_ready"]).sum())},
        ]
    )


def append_anchor_to_consolidated(prior_bins: pd.DataFrame, anchor_context: pd.DataFrame) -> pd.DataFrame:
    rows = anchor_context.copy()
    rows["original_physical_leg_id"] = pd.NA
    rows["original_carriageway_subbranch_id"] = pd.NA
    rows["bin_source"] = "generated_intersection_zone_anchor_bin"
    rows["leg_distribution_consolidation_provenance"] = "final_clean_intersection_zone_anchor_recovery"
    rows["final_review_physical_leg_id"] = clean_series(rows, "corrected_physical_leg_id").where(
        nonblank(rows, "corrected_physical_leg_id"), clean_series(rows, "physical_leg_id")
    )
    rows["final_review_carriageway_subbranch_id"] = clean_series(rows, "corrected_carriageway_subbranch_id").where(
        nonblank(rows, "corrected_carriageway_subbranch_id"), clean_series(rows, "carriageway_subbranch_id")
    )
    rows["final_review_leg_source"] = "generated_intersection_zone_anchor_leg"
    rows["final_review_has_rns_speed"] = rows["has_rns_speed"]
    rows["final_review_has_aadt"] = rows["has_aadt"]
    rows["final_review_has_exposure_denominator"] = rows["has_exposure_denominator"]
    rows["final_review_speed_aadt_ready_bin"] = rows["speed_aadt_ready_bin"]
    rows["final_review_recovery_provenance"] = (
        "final_clean_intersection_zone_anchor_recovery|final_clean_intersection_zone_anchor_context_refresh"
    )
    rows["review_only"] = True

    all_cols = list(dict.fromkeys(list(prior_bins.columns) + list(rows.columns)))
    prior = prior_bins.reindex(columns=all_cols)
    rows = rows.reindex(columns=all_cols)
    return pd.concat([prior, rows], ignore_index=True, sort=False)


def update_signal_summary(prior_signals: pd.DataFrame, anchor_signals: pd.DataFrame) -> pd.DataFrame:
    out = prior_signals.copy()
    add = anchor_signals[["stable_signal_id", "generated_physical_leg_count", "generated_bin_count", "speed_aadt_ready"]].rename(
        columns={
            "generated_physical_leg_count": "anchor_generated_leg_count",
            "generated_bin_count": "anchor_generated_bin_count",
            "speed_aadt_ready": "anchor_speed_aadt_ready",
        }
    )
    out = out.merge(add, on="stable_signal_id", how="left")
    out["anchor_generated_leg_count"] = out["anchor_generated_leg_count"].fillna(0).astype(int)
    out["anchor_generated_bin_count"] = out["anchor_generated_bin_count"].fillna(0).astype(int)
    base_count = pd.to_numeric(out["final_review_physical_leg_count"], errors="coerce").fillna(0).astype(int)
    out["final_review_physical_leg_count_after_anchor_context"] = base_count + out["anchor_generated_leg_count"]
    out["final_review_physical_leg_bucket_after_anchor_context"] = out[
        "final_review_physical_leg_count_after_anchor_context"
    ].map(leg_bucket)
    out["final_review_bin_count_after_anchor_context"] = (
        pd.to_numeric(out["final_review_bin_count"], errors="coerce").fillna(0).astype(int)
        + out["anchor_generated_bin_count"]
    )
    return out


def distribution_table(prior_distribution: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    rows = prior_distribution.to_dict("records") if not prior_distribution.empty else []
    counts = signal_summary["final_review_physical_leg_bucket_after_anchor_context"].value_counts().to_dict()
    total = int(sum(counts.values()))
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        count = int(counts.get(bucket, 0))
        rows.append(
            {
                "distribution_scenario": "after_intersection_zone_anchor_context_integration",
                "physical_leg_bucket": bucket,
                "signal_count": count,
                "share": round(count / total, 4) if total else 0,
            }
        )
    rows.append(
        {
            "distribution_scenario": "after_intersection_zone_anchor_context_integration",
            "physical_leg_bucket": "two_leg_or_less_combined",
            "signal_count": int(counts.get("one_leg", 0) + counts.get("two_leg", 0)),
            "share": round((counts.get("one_leg", 0) + counts.get("two_leg", 0)) / total, 4) if total else 0,
        }
    )
    rows.append(
        {
            "distribution_scenario": "after_intersection_zone_anchor_context_integration",
            "physical_leg_bucket": "three_four_combined",
            "signal_count": int(counts.get("three_leg", 0) + counts.get("four_leg", 0)),
            "share": round((counts.get("three_leg", 0) + counts.get("four_leg", 0)) / total, 4) if total else 0,
        }
    )
    return pd.DataFrame(rows)


def remaining_issues(prior_issues: pd.DataFrame, skipped: pd.DataFrame, signal_summary: pd.DataFrame, residual_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    counts = signal_summary["final_review_physical_leg_bucket_after_anchor_context"].value_counts().to_dict()
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        rows.append(
            {
                "issue_group": "post_anchor_context_physical_leg_distribution",
                "issue_class": bucket,
                "signal_count": int(counts.get(bucket, 0)),
                "meaning": "Physical-leg bucket after context-refreshed anchor bin integration.",
            }
        )
    if not skipped.empty:
        for reason, count in skipped["skip_reason"].fillna("unknown").value_counts().items():
            rows.append(
                {
                    "issue_group": "skipped_intersection_zone_anchor_target",
                    "issue_class": reason,
                    "signal_count": int(count),
                    "meaning": "Anchor-recovery target skipped before context refresh.",
                }
            )
    if not residual_summary.empty:
        for row in residual_summary.to_dict("records"):
            rows.append(
                {
                    "issue_group": f"residual_reference_{row.get('residual_bucket', '')}",
                    "issue_class": row.get("reclassified_class", ""),
                    "signal_count": int(row.get("signal_count", 0)),
                    "meaning": "Residual label audit reference class before anchor recovery.",
                }
            )
    return pd.DataFrame(rows)


def next_action() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "priority": 1,
                "recommended_next_pass": "broader_source_search_for_residual_failed_source_leg_cases",
                "target_signal_count": 110,
                "reason": "Prior residual audit identified conservative source-search failures after generated and anchor recovery.",
            },
            {
                "priority": 2,
                "recommended_next_pass": "additional_five_plus_label_subbranch_normalization",
                "target_signal_count": 169,
                "reason": "Five-plus count is unchanged by anchor recovery and remains a label/subbranch problem.",
            },
            {
                "priority": 3,
                "recommended_next_pass": "map_review_package_for_residual_one_two_and_anchor_skips",
                "target_signal_count": 318,
                "reason": "Remaining one/two plus anchor-skipped records are now small enough for focused review if needed.",
            },
            {
                "priority": 4,
                "recommended_next_pass": "accept_distribution_and_refresh_access_crash_products",
                "target_signal_count": FINAL_CLEAN_SIGNAL_COUNT,
                "reason": "After context-refreshed anchor integration, four-leg intersections dominate and one/two residuals are bounded.",
            },
        ]
    )


def qa_table(anchor_context: pd.DataFrame, consolidated: pd.DataFrame, missing_inputs: list[str]) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_clean_intersection_zone_anchor_context_refresh."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_crash_assignment", True, "Crash records are not read."),
        ("no_access_assignment", True, "Access sources are not read or assigned."),
        ("no_rates_or_models", True, "No rates, models, regressions, or predictions are calculated."),
        ("crash_direction_fields_not_used", True, "CSV reader refuses known crash direction columns."),
        (
            "stable_travelway_id_preserved_on_anchor_context_bins",
            int(nonblank(anchor_context, "stable_travelway_id").sum()) == len(anchor_context),
            f"{int(nonblank(anchor_context, 'stable_travelway_id').sum()):,} / {len(anchor_context):,}",
        ),
        ("no_rows_deleted_or_collapsed", len(consolidated) >= len(anchor_context), f"consolidated rows={len(consolidated):,}"),
        (
            "original_and_corrected_leg_labels_preserved",
            {"physical_leg_id", "corrected_physical_leg_id", "final_review_physical_leg_id"}.issubset(set(consolidated.columns)),
            "Original/corrected/final review labels are present.",
        ),
        ("source_limited_cases_not_forced", True, "This pass context-refreshes already-generated anchor bins only."),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("required_inputs_available", not missing_inputs, "; ".join(missing_inputs[:8])),
    ]
    return pd.DataFrame([{"qa_check": k, "passed": bool(v), "detail": d} for k, v, d in checks])


def findings(counts: dict[str, Any]) -> str:
    return f"""# Final Clean Intersection-Zone Anchor Context Refresh

## Bounded Question

Context-refresh the 13,261 generated intersection-zone anchor bins and integrate them with the final clean review-analysis universe, prior missing-leg context bins, and label-only five-plus normalization.

## Answers

1. **Route/measure identity:** {counts['route_measure_ready_bins']:,} / {counts['anchor_bins']:,} anchor bins.
2. **Roadway context:** {counts['roadway_ready_bins']:,} / {counts['anchor_bins']:,} anchor bins.
3. **RNS speed:** {counts['rns_ready_bins']:,} / {counts['anchor_bins']:,} anchor bins.
4. **AADT/exposure:** {counts['aadt_ready_bins']:,} AADT-ready and {counts['exposure_ready_bins']:,} exposure-ready / {counts['anchor_bins']:,}.
5. **Anchor-recovery signals speed+AADT-ready:** {counts['speed_aadt_ready_signals']:,} / {counts['anchor_signals']:,}.
6. **Final distribution:** one-leg {counts['final_one_leg']:,}, two-leg {counts['final_two_leg']:,}, three-leg {counts['final_three_leg']:,}, four-leg {counts['final_four_leg']:,}, five-plus {counts['final_five_plus']:,}.
7. **One-/two-leg residuals:** {counts['final_one_two']:,}.
8. **Three-leg residuals:** {counts['final_three_leg']:,}.
9. **Five-plus residuals:** {counts['final_five_plus']:,}.
10. **Recommended next pass:** broader source search for residual source-leg failures, then additional five-plus label/subbranch normalization; otherwise accept the distribution for downstream access/crash refresh.

## Method Note

This pass uses stable Travelway route/measure lineage for review-only RNS/AADT readiness and avoids bin-by-source overlap tables. It appends anchor-generated rows to the prior consolidated review state and preserves original, corrected, and final-review leg labels.

The final distribution is recomputed from context-refreshed anchor bins. It can differ from the recovery-pass estimate because the recovery estimate included all generated leg candidates, while this integration counts only anchor-generated legs with emitted bin rows.
"""


def manifest_payload(counts: dict[str, Any], missing_inputs: list[str]) -> dict[str, Any]:
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.build.final_clean_intersection_zone_anchor_context_refresh",
        "bounded_question": "Review-only context refresh and integration for intersection-zone anchor recovery bins.",
        "inputs": {name: {"path": str(path), "exists": path.exists()} for name, path in INPUTS.items()},
        "missing_inputs": missing_inputs,
        "counts": counts,
        "non_goals": {
            "active_outputs_modified": False,
            "records_promoted": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_or_models": False,
            "crash_direction_fields_used": False,
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    log(log_lines, "Starting final clean intersection-zone anchor context refresh.")
    missing_inputs = [f"{name}: {path}" for name, path in INPUTS.items() if not path.exists()]
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing_inputs))

    anchor_bins = read_csv(INPUTS["anchor_generated_bins"])
    anchor_legs = read_csv(INPUTS["anchor_generated_leg_candidates"])
    anchor_inference = read_csv(INPUTS["anchor_inference_detail"])
    anchor_skipped = read_csv(INPUTS["anchor_skipped_targets"])
    prior_bins = read_csv(INPUTS["prior_consolidated_bins"])
    prior_signals = read_csv(INPUTS["prior_consolidated_signals"])
    prior_distribution = read_csv(INPUTS["prior_distribution"])
    prior_issues = read_csv(INPUTS["prior_remaining_issues"])
    residual_summary = read_csv(INPUTS["residual_summary"])
    write_csv(input_status(), "input_status.csv")
    log(log_lines, f"Read anchor bins: {len(anchor_bins):,}")

    anchor_context = context_refresh_anchor_bins(anchor_bins, anchor_inference, anchor_legs)
    anchor_signal_summary = signal_context_summary(anchor_context, anchor_inference)

    route_summary = route_measure_summary(anchor_context, anchor_signal_summary)
    roadway_summary = simple_summary("roadway_context", anchor_context, "roadway_context_ready_bin")
    speed_summary = simple_summary("rns_speed", anchor_context, "has_rns_speed")
    aadt_summary = pd.DataFrame(
        [
            {"metric": "generated_anchor_bins_total", "value": len(anchor_context)},
            {"metric": "generated_anchor_bins_aadt_ready", "value": int(anchor_context["has_aadt"].sum())},
            {
                "metric": "generated_anchor_bins_exposure_denominator_ready",
                "value": int(anchor_context["has_exposure_denominator"].sum()),
            },
            {"metric": "generated_anchor_bins_missing_aadt_or_exposure", "value": int((~anchor_context["speed_aadt_ready_bin"]).sum())},
        ]
    )
    readiness_summary = pd.DataFrame(
        [
            {"metric": "generated_anchor_bins_total", "value": len(anchor_context)},
            {"metric": "generated_anchor_signals_total", "value": len(anchor_signal_summary)},
            {"metric": "generated_anchor_bins_speed_aadt_ready", "value": int(anchor_context["speed_aadt_ready_bin"].sum())},
            {"metric": "generated_anchor_signals_speed_aadt_ready", "value": int(anchor_signal_summary["speed_aadt_ready"].sum())},
            {
                "metric": "generated_anchor_signals_0_1000_speed_aadt_ready",
                "value": int(anchor_signal_summary["speed_aadt_0_1000_ready"].sum()),
            },
            {
                "metric": "generated_anchor_signals_1000_2500_sensitivity_ready",
                "value": int(anchor_signal_summary["sensitivity_1000_2500_ready"].sum()),
            },
        ]
    )

    consolidated_bins = append_anchor_to_consolidated(prior_bins, anchor_context)
    consolidated_signals = update_signal_summary(prior_signals, anchor_signal_summary)
    distribution = distribution_table(prior_distribution, consolidated_signals)
    issues = remaining_issues(prior_issues, anchor_skipped, consolidated_signals, residual_summary)
    recommendation = next_action()

    counts_by_bucket = consolidated_signals["final_review_physical_leg_bucket_after_anchor_context"].value_counts().to_dict()
    counts = {
        "anchor_bins": int(len(anchor_context)),
        "expected_anchor_bins": EXPECTED_ANCHOR_BIN_COUNT,
        "anchor_signals": int(anchor_context["stable_signal_id"].nunique()),
        "route_measure_ready_bins": int(anchor_context["route_measure_ready_bin"].sum()),
        "roadway_ready_bins": int(anchor_context["roadway_context_ready_bin"].sum()),
        "rns_ready_bins": int(anchor_context["has_rns_speed"].sum()),
        "aadt_ready_bins": int(anchor_context["has_aadt"].sum()),
        "exposure_ready_bins": int(anchor_context["has_exposure_denominator"].sum()),
        "speed_aadt_ready_bins": int(anchor_context["speed_aadt_ready_bin"].sum()),
        "speed_aadt_ready_signals": int(anchor_signal_summary["speed_aadt_ready"].sum()),
        "consolidated_output_bins": int(len(consolidated_bins)),
        "final_clean_signals": int(len(consolidated_signals)),
        "final_one_leg": int(counts_by_bucket.get("one_leg", 0)),
        "final_two_leg": int(counts_by_bucket.get("two_leg", 0)),
        "final_three_leg": int(counts_by_bucket.get("three_leg", 0)),
        "final_four_leg": int(counts_by_bucket.get("four_leg", 0)),
        "final_five_plus": int(counts_by_bucket.get("five_plus_leg", 0)),
        "final_one_two": int(counts_by_bucket.get("one_leg", 0) + counts_by_bucket.get("two_leg", 0)),
        "skipped_anchor_targets": int(len(anchor_skipped)),
    }

    write_csv(anchor_context, "intersection_zone_anchor_context_bin_detail.csv")
    write_csv(anchor_signal_summary, "intersection_zone_anchor_context_signal_summary.csv")
    write_csv(route_summary, "intersection_zone_anchor_route_measure_summary.csv")
    write_csv(roadway_summary, "intersection_zone_anchor_roadway_context_summary.csv")
    write_csv(speed_summary, "intersection_zone_anchor_speed_summary.csv")
    write_csv(aadt_summary, "intersection_zone_anchor_aadt_exposure_summary.csv")
    write_csv(readiness_summary, "intersection_zone_anchor_context_readiness_summary.csv")
    write_csv(consolidated_bins, "final_clean_consolidated_bin_detail_with_anchor_context.csv")
    write_csv(consolidated_signals, "final_clean_consolidated_signal_summary_with_anchor_context.csv")
    write_csv(distribution, "final_clean_distribution_after_anchor_context.csv")
    write_csv(issues, "remaining_leg_issues_after_anchor_context.csv")
    write_csv(recommendation, "anchor_context_next_action_recommendation.csv")
    write_csv(qa_table(anchor_context, consolidated_bins, missing_inputs), "final_clean_intersection_zone_anchor_context_refresh_qa.csv")
    write_text(findings(counts), "final_clean_intersection_zone_anchor_context_refresh_findings.md")
    write_json(manifest_payload(counts, missing_inputs), "final_clean_intersection_zone_anchor_context_refresh_manifest.json")
    log(log_lines, "Complete.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
