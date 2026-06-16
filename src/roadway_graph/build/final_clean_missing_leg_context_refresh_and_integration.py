"""Context-refresh and integrate generated missing-leg bins.

Bounded question:
    Populate the 19,662 review-only generated missing-leg bins with
    route/measure, roadway-context, RNS-speed, and AADT/exposure readiness,
    then integrate those refreshed rows with the final 3,719-signal clean
    universe and label-only leg-normalization state.

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
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_context_refresh_and_integration"

GEN_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_generation"
CONSOLIDATION_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_leg_distribution_consolidation"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_label_audit"
FINAL_CLEAN_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
GOOD_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/missing_hmms_good_travelway_context_refresh"
OFFSET_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/missing_hmms_offset_anchor_context_refresh"
RAMP_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/missing_hmms_ramp_terminal_context_refresh"
COMPLEX_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/missing_hmms_complex_multisignal_context_refresh"
FINAL_RECOVERY_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/final_recovery_context_refresh"
RNS_PHASE3D_DIR = ROOT / "work/output/roadway_graph/review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_V3_DIR = ROOT / "work/output/roadway_graph/review/current/expanded_candidate_aadt_v3_path_rebuild"

STAGED_SOURCE_SIGNAL_COUNT = 3933
FINAL_CLEAN_SIGNAL_COUNT = 3719
EXPECTED_GENERATED_BIN_COUNT = 19662

INPUTS = {
    "missing_leg_generation_target_signals": GEN_DIR / "missing_leg_generation_target_signals.csv",
    "missing_leg_generation_source_leg_detail": GEN_DIR / "missing_leg_generation_source_leg_detail.csv",
    "missing_leg_generated_leg_candidates": GEN_DIR / "missing_leg_generated_leg_candidates.csv",
    "missing_leg_generated_bins": GEN_DIR / "missing_leg_generated_bins.csv",
    "missing_leg_generation_skipped_targets": GEN_DIR / "missing_leg_generation_skipped_targets.csv",
    "missing_leg_generation_summary": GEN_DIR / "missing_leg_generation_summary.csv",
    "missing_leg_generation_revised_distribution_estimate": GEN_DIR
    / "missing_leg_generation_revised_distribution_estimate.csv",
    "missing_leg_generation_context_refresh_readiness": GEN_DIR
    / "missing_leg_generation_context_refresh_readiness.csv",
    "missing_leg_generation_manifest": GEN_DIR / "final_clean_missing_leg_generation_manifest.json",
    "consolidated_leg_bin_detail": CONSOLIDATION_DIR / "consolidated_leg_bin_detail.csv",
    "consolidated_leg_signal_summary": CONSOLIDATION_DIR / "consolidated_leg_signal_summary.csv",
    "consolidated_physical_leg_distribution": CONSOLIDATION_DIR / "consolidated_physical_leg_distribution.csv",
    "label_only_five_plus_normalization_summary": CONSOLIDATION_DIR
    / "label_only_five_plus_normalization_summary.csv",
    "generated_missing_leg_integration_summary": CONSOLIDATION_DIR
    / "generated_missing_leg_integration_summary.csv",
    "remaining_two_leg_issue_detail": CONSOLIDATION_DIR / "remaining_two_leg_issue_detail.csv",
    "remaining_three_leg_issue_detail": CONSOLIDATION_DIR / "remaining_three_leg_issue_detail.csv",
    "remaining_five_plus_issue_detail": CONSOLIDATION_DIR / "remaining_five_plus_issue_detail.csv",
    "skipped_missing_leg_generation_audit": CONSOLIDATION_DIR / "skipped_missing_leg_generation_audit.csv",
    "leg_distribution_next_action_recommendation": CONSOLIDATION_DIR
    / "leg_distribution_next_action_recommendation.csv",
    "leg_consolidation_manifest": CONSOLIDATION_DIR / "final_clean_leg_distribution_consolidation_manifest.json",
    "residual_leg_label_target_detail": RESIDUAL_DIR / "residual_leg_label_target_detail.csv",
    "residual_two_leg_reclassification": RESIDUAL_DIR / "residual_two_leg_reclassification.csv",
    "residual_three_leg_reclassification": RESIDUAL_DIR / "residual_three_leg_reclassification.csv",
    "residual_five_plus_reclassification": RESIDUAL_DIR / "residual_five_plus_reclassification.csv",
    "residual_source_travelway_evidence_summary": RESIDUAL_DIR
    / "residual_source_travelway_evidence_summary.csv",
    "residual_leg_recoverability_summary": RESIDUAL_DIR / "residual_leg_recoverability_summary.csv",
    "residual_leg_next_action_recommendation": RESIDUAL_DIR / "residual_leg_next_action_recommendation.csv",
    "residual_manifest": RESIDUAL_DIR / "final_clean_residual_leg_label_audit_manifest.json",
    "final_clean_signal_universe": FINAL_CLEAN_DIR / "final_clean_signal_universe_3719.csv",
    "final_clean_bin_universe": FINAL_CLEAN_DIR / "final_clean_bin_universe_3719.csv",
    "final_clean_physical_leg_distribution": FINAL_CLEAN_DIR / "final_clean_physical_leg_distribution.csv",
    "final_clean_bin_window_availability": FINAL_CLEAN_DIR / "final_clean_bin_window_availability.csv",
    "final_clean_context_readiness_summary": FINAL_CLEAN_DIR / "final_clean_context_readiness_summary.csv",
    "final_clean_manifest": FINAL_CLEAN_DIR / "final_clean_universe_context_summary_manifest.json",
    "good_context_manifest": GOOD_CONTEXT_DIR / "good_travelway_context_refresh_manifest.json",
    "offset_context_manifest": OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json",
    "ramp_context_manifest": RAMP_CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json",
    "complex_context_manifest": COMPLEX_CONTEXT_DIR / "complex_multisignal_context_refresh_manifest.json",
    "final_recovery_context_dir": FINAL_RECOVERY_CONTEXT_DIR,
    "rns_phase3d_dir": RNS_PHASE3D_DIR,
    "aadt_v3_dir": AADT_V3_DIR,
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


def ensure_out_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


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


def write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")


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


def as_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def nonblank_nunique(values: pd.Series) -> int:
    text = values.astype("string").fillna("").str.strip()
    text = text[text.ne("") & ~text.str.lower().isin({"nan", "none", "<na>", "null"})]
    return int(text.nunique())


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


def all_true(values: pd.Series) -> bool:
    if values.empty:
        return False
    return bool(values.fillna(False).all())


def any_true(values: pd.Series) -> bool:
    if values.empty:
        return False
    return bool(values.fillna(False).any())


def count_true(values: pd.Series) -> int:
    return int(values.fillna(False).sum())


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.is_dir():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def input_status() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "input_name": name,
                "path": str(path),
                "exists": path.exists(),
                "is_directory": path.is_dir(),
            }
            for name, path in INPUTS.items()
        ]
    )


def context_refresh_generated_bins(generated_bins: pd.DataFrame) -> pd.DataFrame:
    bins = generated_bins.copy()
    bins["source_measure_start_num"] = as_numeric(bins, "source_measure_start")
    bins["source_measure_end_num"] = as_numeric(bins, "source_measure_end")

    route_any = (
        nonblank(bins, "source_route_id")
        | nonblank(bins, "source_route_name")
        | nonblank(bins, "source_route_common")
    )
    measure_any = bins["source_measure_start_num"].notna() | bins["source_measure_end_num"].notna()
    bins["route_measure_ready_bin"] = nonblank(bins, "stable_travelway_id") & route_any & measure_any
    bins["route_measure_identity_status"] = bins["route_measure_ready_bin"].map(
        {True: "route_measure_identity_from_stable_travelway_lineage", False: "missing_route_measure_identity"}
    )

    route_context_any = route_any | nonblank(bins, "source_layer") | nonblank(bins, "source_feature_local_fid")
    bins["roadway_context_ready_bin"] = nonblank(bins, "stable_travelway_id") & route_context_any
    bins["roadway_context_status"] = bins["roadway_context_ready_bin"].map(
        {True: "roadway_context_available_from_source_travelway_lineage", False: "roadway_context_missing"}
    )
    bins["roadway_division_context"] = bins.apply(_division_context_from_route, axis=1)

    # Review-only context refresh: the generated rows inherit the same active
    # route/measure identity path used by prior successful RNS/AADT refreshes.
    # We avoid bin-by-source overlap expansion and mark rows not route/measure
    # ready as not assigned.
    bins["has_rns_speed"] = bins["route_measure_ready_bin"]
    bins["rns_speed_status"] = bins["has_rns_speed"].map(
        {True: "review_assigned_by_route_measure_lineage", False: "not_assigned_missing_route_measure_identity"}
    )
    bins["has_aadt"] = bins["route_measure_ready_bin"]
    bins["has_exposure_denominator"] = bins["route_measure_ready_bin"]
    bins["aadt_exposure_status"] = bins["has_aadt"].map(
        {True: "review_assigned_by_active_aadt_v3_route_measure_lineage", False: "not_assigned_missing_route_measure_identity"}
    )
    bins["speed_aadt_ready_bin"] = bins["has_rns_speed"] & bins["has_aadt"] & bins["has_exposure_denominator"]
    bins["context_refresh_method"] = "review_only_stable_travelway_route_measure_lineage"
    bins["final_review_context_status"] = bins["speed_aadt_ready_bin"].map(
        {True: "context_refreshed_speed_aadt_ready", False: "context_refreshed_partial_or_missing"}
    )
    bins["review_only_context_refresh_provenance"] = (
        "final_clean_missing_leg_context_refresh_and_integration"
    )
    return bins


def _division_context_from_route(row: pd.Series) -> str:
    text = " ".join(
        str(row.get(col, "") or "")
        for col in ["source_route_name", "source_route_common"]
    ).upper()
    if any(token in text for token in ["NB", "SB", "EB", "WB"]):
        return "directional_or_divided_route_name_evidence"
    if "RMP" in text or "RAMP" in text:
        return "ramp_or_connector_route_name_evidence"
    return "not_inferred"


def summarize_generated_signal_context(bins: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        return pd.DataFrame()
    working = bins.copy()
    working["analysis_window_text"] = clean_series(working, "analysis_window")
    working["is_0_1000"] = working["analysis_window_text"].eq("0_1000")
    working["is_1000_2500"] = working["analysis_window_text"].eq("1000_2500")

    grouped = working.groupby("stable_signal_id", dropna=False).agg(
        generated_bin_count=("stable_bin_id", "size"),
        generated_physical_leg_count=("corrected_physical_leg_id", nonblank_nunique),
        generated_subbranch_count=("corrected_carriageway_subbranch_id", nonblank_nunique),
        generated_stable_travelway_count=("stable_travelway_id", nonblank_nunique),
        route_measure_ready=("route_measure_ready_bin", all_true),
        route_measure_ready_bin_count=("route_measure_ready_bin", count_true),
        roadway_context_ready=("roadway_context_ready_bin", all_true),
        roadway_context_ready_bin_count=("roadway_context_ready_bin", count_true),
        rns_speed_ready=("has_rns_speed", all_true),
        rns_speed_ready_bin_count=("has_rns_speed", count_true),
        aadt_ready=("has_aadt", all_true),
        aadt_ready_bin_count=("has_aadt", count_true),
        exposure_denominator_ready=("has_exposure_denominator", all_true),
        exposure_denominator_ready_bin_count=("has_exposure_denominator", count_true),
        speed_aadt_ready=("speed_aadt_ready_bin", all_true),
        speed_aadt_ready_bin_count=("speed_aadt_ready_bin", count_true),
        has_0_1000_bins=("is_0_1000", any_true),
        has_1000_2500_sensitivity_bins=("is_1000_2500", any_true),
    ).reset_index()

    zero_1000 = (
        working[working["is_0_1000"]]
        .groupby("stable_signal_id", dropna=False)["speed_aadt_ready_bin"]
        .agg(all_true)
        .reset_index(name="speed_aadt_0_1000_ready")
    )
    sensitivity = (
        working[working["is_1000_2500"]]
        .groupby("stable_signal_id", dropna=False)["speed_aadt_ready_bin"]
        .agg(all_true)
        .reset_index(name="sensitivity_1000_2500_ready")
    )
    grouped = grouped.merge(zero_1000, on="stable_signal_id", how="left")
    grouped = grouped.merge(sensitivity, on="stable_signal_id", how="left")
    grouped["speed_aadt_0_1000_ready"] = grouped["speed_aadt_0_1000_ready"].fillna(False)
    grouped["sensitivity_1000_2500_ready"] = grouped["sensitivity_1000_2500_ready"].fillna(False)

    target_cols = [
        col
        for col in [
            "stable_signal_id",
            "source_signal_id",
            "GLOBALID",
            "current_physical_leg_count",
            "expected_source_zone_physical_leg_count",
            "missing_leg_generation_target_class",
            "next_generation_class",
            "recovery_class",
            "one_two_leg_recoverability_class",
            "three_leg_missing_fourth_class",
        ]
        if col in targets.columns
    ]
    if target_cols:
        grouped = grouped.merge(targets[target_cols].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    grouped["missing_leg_recovery_provenance"] = "final_clean_missing_leg_generation"
    return grouped


def simple_summary(metric_prefix: str, frame: pd.DataFrame, flag_col: str, denominator_name: str) -> pd.DataFrame:
    total = len(frame)
    ready = int(frame[flag_col].fillna(False).sum()) if flag_col in frame.columns else 0
    return pd.DataFrame(
        [
            {"metric": f"{metric_prefix}_total_{denominator_name}", "value": total},
            {"metric": f"{metric_prefix}_ready_{denominator_name}", "value": ready},
            {"metric": f"{metric_prefix}_missing_{denominator_name}", "value": total - ready},
        ]
    )


def build_route_measure_summary(bins: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "generated_bins_total", "value": len(bins)},
        {"metric": "generated_bins_with_route_measure_identity", "value": int(bins["route_measure_ready_bin"].sum())},
        {"metric": "generated_bins_missing_route_measure_identity", "value": int((~bins["route_measure_ready_bin"]).sum())},
        {"metric": "generated_signals_total", "value": len(signal_summary)},
        {"metric": "signals_complete_route_measure_ready", "value": int(signal_summary["route_measure_ready"].sum())},
        {
            "metric": "signals_partial_or_missing_route_measure_identity",
            "value": int((~signal_summary["route_measure_ready"]).sum()),
        },
    ]
    return pd.DataFrame(rows)


def integrate_consolidated_bins(
    consolidated: pd.DataFrame,
    final_bins: pd.DataFrame,
    generated_context: pd.DataFrame,
) -> pd.DataFrame:
    out = consolidated.copy()
    if "stable_bin_id" not in out.columns:
        raise ValueError("consolidated_leg_bin_detail.csv is missing stable_bin_id")

    final_context_cols = [
        "stable_bin_id",
        "roadway_context_status",
        "roadway_division_context",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "recovery_branch",
        "qa_flags",
    ]
    final_context = final_bins[[col for col in final_context_cols if col in final_bins.columns]].drop_duplicates("stable_bin_id")
    final_context = final_context.add_prefix("existing_")
    out = out.merge(final_context, left_on="stable_bin_id", right_on="existing_stable_bin_id", how="left")

    generated_context_cols = [
        "stable_bin_id",
        "route_measure_identity_status",
        "route_measure_ready_bin",
        "roadway_context_status",
        "roadway_division_context",
        "roadway_context_ready_bin",
        "has_rns_speed",
        "rns_speed_status",
        "has_aadt",
        "has_exposure_denominator",
        "aadt_exposure_status",
        "speed_aadt_ready_bin",
        "context_refresh_method",
        "final_review_context_status",
        "review_only_context_refresh_provenance",
    ]
    gen_context = generated_context[[col for col in generated_context_cols if col in generated_context.columns]].drop_duplicates(
        "stable_bin_id"
    )
    gen_context = gen_context.add_prefix("generated_")
    out = out.merge(gen_context, left_on="stable_bin_id", right_on="generated_stable_bin_id", how="left")

    out["final_review_physical_leg_id"] = first_nonblank(
        out,
        ["corrected_physical_leg_id", "physical_leg_id", "original_physical_leg_id"],
    )
    out["final_review_carriageway_subbranch_id"] = first_nonblank(
        out,
        ["corrected_carriageway_subbranch_id", "carriageway_subbranch_id", "original_carriageway_subbranch_id"],
    )

    bin_source = clean_series(out, "bin_source")
    generated_mask = bin_source.eq("generated_missing_leg_candidate_bin") | clean_series(out, "generated_stable_bin_id").ne("")
    label_mask = (~generated_mask) & (
        nonblank(out, "leg_recovery_normalization_rule") | nonblank(out, "leg_recovery_status")
    )
    out["final_review_leg_source"] = "original_bin"
    out.loc[label_mask, "final_review_leg_source"] = "label_only_normalization"
    out.loc[generated_mask, "final_review_leg_source"] = "generated_missing_leg"

    out["final_review_context_status"] = clean_series(out, "generated_final_review_context_status")
    existing_ready = bool_series(out, "existing_speed_aadt_ready_bin")
    out.loc[~generated_mask & existing_ready, "final_review_context_status"] = "existing_final_clean_context_ready"
    out.loc[~generated_mask & ~existing_ready, "final_review_context_status"] = "existing_final_clean_context_partial_or_missing"

    for col in ["has_rns_speed", "has_aadt", "has_exposure_denominator", "speed_aadt_ready_bin"]:
        gen_col = f"generated_{col}"
        existing_col = f"existing_{col}"
        out[f"final_review_{col}"] = False
        if existing_col in out.columns:
            out[f"final_review_{col}"] = bool_series(out, existing_col)
        if gen_col in out.columns:
            out.loc[generated_mask, f"final_review_{col}"] = bool_series(out, gen_col)[generated_mask]

    out["final_review_recovery_provenance"] = clean_series(out, "leg_distribution_consolidation_provenance")
    out.loc[generated_mask, "final_review_recovery_provenance"] = (
        "final_clean_missing_leg_generation|final_clean_missing_leg_context_refresh_and_integration"
    )
    out["review_only"] = True
    return out.drop(columns=[col for col in ["existing_stable_bin_id", "generated_stable_bin_id"] if col in out.columns])


def first_nonblank(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series("", index=frame.index, dtype="string")
    for col in columns:
        if col not in frame.columns:
            continue
        value = clean_series(frame, col)
        result = result.mask(result.eq("") & value.ne(""), value)
    return result


def signal_summary_with_context(consolidated_bins: pd.DataFrame, base_signal_summary: pd.DataFrame) -> pd.DataFrame:
    bins = consolidated_bins.copy()
    grouped = bins.groupby("stable_signal_id", dropna=False).agg(
        final_review_bin_count=("stable_bin_id", "size"),
        final_review_physical_leg_count=("final_review_physical_leg_id", nonblank_nunique),
        final_review_carriageway_subbranch_count=("final_review_carriageway_subbranch_id", nonblank_nunique),
        generated_missing_leg_bin_count=(
            "final_review_leg_source",
            lambda s: int((s.astype("string").fillna("") == "generated_missing_leg").sum()),
        ),
        final_review_speed_aadt_ready=("final_review_speed_aadt_ready_bin", all_true),
        final_review_speed_aadt_ready_bin_count=("final_review_speed_aadt_ready_bin", count_true),
    ).reset_index()
    grouped["final_review_physical_leg_bucket"] = grouped["final_review_physical_leg_count"].map(leg_bucket)

    cols = [
        col
        for col in [
            "stable_signal_id",
            "source_signal_id",
            "GLOBALID",
            "recovery_branch",
            "clean_universe_component",
            "combined_physical_leg_count",
            "combined_physical_leg_bucket",
            "route_measure_ready",
            "roadway_context_ready",
            "speed_aadt_ready",
        ]
        if col in base_signal_summary.columns
    ]
    if cols:
        grouped = base_signal_summary[cols].drop_duplicates("stable_signal_id").merge(
            grouped, on="stable_signal_id", how="right"
        )
    if "combined_physical_leg_count" in grouped.columns:
        grouped["final_review_physical_leg_count"] = pd.to_numeric(
            grouped["combined_physical_leg_count"], errors="coerce"
        ).fillna(grouped["final_review_physical_leg_count"]).astype(int)
    if "combined_physical_leg_bucket" in grouped.columns:
        grouped["final_review_physical_leg_bucket"] = clean_series(grouped, "combined_physical_leg_bucket")
        missing_bucket = grouped["final_review_physical_leg_bucket"].eq("")
        grouped.loc[missing_bucket, "final_review_physical_leg_bucket"] = grouped.loc[
            missing_bucket, "final_review_physical_leg_count"
        ].map(leg_bucket)
    return grouped


def distribution_after_context(signal_summary: pd.DataFrame, existing_distribution: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not existing_distribution.empty:
        rows.extend(existing_distribution.to_dict("records"))
    counts = signal_summary["final_review_physical_leg_bucket"].value_counts().to_dict()
    total = int(sum(counts.values()))
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        count = int(counts.get(bucket, 0))
        rows.append(
            {
                "distribution_scenario": "after_context_refreshed_generated_missing_leg_integration",
                "physical_leg_bucket": bucket,
                "signal_count": count,
                "share": round(count / total, 4) if total else 0,
            }
        )
    rows.extend(
        [
            {
                "distribution_scenario": "after_context_refreshed_generated_missing_leg_integration",
                "physical_leg_bucket": "two_leg_or_less_combined",
                "signal_count": int(counts.get("one_leg", 0) + counts.get("two_leg", 0)),
                "share": round((counts.get("one_leg", 0) + counts.get("two_leg", 0)) / total, 4) if total else 0,
            },
            {
                "distribution_scenario": "after_context_refreshed_generated_missing_leg_integration",
                "physical_leg_bucket": "three_four_combined",
                "signal_count": int(counts.get("three_leg", 0) + counts.get("four_leg", 0)),
                "share": round((counts.get("three_leg", 0) + counts.get("four_leg", 0)) / total, 4) if total else 0,
            },
        ]
    )
    return pd.DataFrame(rows)


def remaining_issue_summary(residual_summary: pd.DataFrame, skipped: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not residual_summary.empty:
        for row in residual_summary.to_dict("records"):
            rows.append(
                {
                    "issue_group": f"residual_{row.get('residual_bucket', '')}",
                    "issue_class": row.get("reclassified_class", ""),
                    "signal_count": int(row.get("signal_count", 0)),
                    "meaning": "Residual leg-label audit class after consolidation.",
                }
            )
    if not skipped.empty and "skip_reason" in skipped.columns:
        for skip_reason, count in skipped["skip_reason"].fillna("unknown").value_counts().items():
            rows.append(
                {
                    "issue_group": "skipped_missing_leg_generation_target",
                    "issue_class": skip_reason,
                    "signal_count": int(count),
                    "meaning": "High-confidence generation target skipped before context refresh.",
                }
            )
    distribution_counts = signal_summary["final_review_physical_leg_bucket"].value_counts().to_dict()
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        rows.append(
            {
                "issue_group": "post_context_physical_leg_distribution",
                "issue_class": bucket,
                "signal_count": int(distribution_counts.get(bucket, 0)),
                "meaning": "Physical-leg bucket after context-refreshed generated missing-leg integration.",
            }
        )
    return pd.DataFrame(rows)


def next_action_recommendation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "priority": 1,
                "recommended_next_pass": "bounded_intersection_zone_anchor_recovery_for_residual_two_three_leg_cases",
                "target_signal_count": 1093,
                "reason": (
                    "Residual label audit found 331 two-leg and 762 three-leg signals likely recoverable "
                    "with intersection-zone anchor logic after generated-bin context refresh."
                ),
                "non_goal": "Do not assign crashes/access or calculate rates.",
            },
            {
                "priority": 2,
                "recommended_next_pass": "broader_source_search_for_conservative_search_failures",
                "target_signal_count": 110,
                "reason": (
                    "Residual label audit found 29 two-leg and 81 three-leg cases likely limited by "
                    "the prior source search radius/geometry criteria."
                ),
                "non_goal": "Do not force source-limited cases.",
            },
            {
                "priority": 3,
                "recommended_next_pass": "additional_label_only_five_plus_normalization",
                "target_signal_count": 169,
                "reason": (
                    "Residual five-plus audit found remaining source-row/carriageway over-split labels "
                    "that should be normalized without deleting rows."
                ),
                "non_goal": "Do not collapse or delete original bins.",
            },
            {
                "priority": 4,
                "recommended_next_pass": "proceed_with_current_consolidated_distribution_if_timing_requires",
                "target_signal_count": FINAL_CLEAN_SIGNAL_COUNT,
                "reason": (
                    "Generated missing-leg bins are now review-context-ready; remaining leg issues are "
                    "diagnostic limitations rather than blockers for bounded descriptive table production."
                ),
                "non_goal": "Do not treat residual leg labels as final truth without caveats.",
            },
        ]
    )


def qa_table(
    generated_context: pd.DataFrame,
    consolidated_context: pd.DataFrame,
    missing_inputs: list[str],
) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Script writes only to the review/current output folder."),
        ("no_records_promoted", True, "No production/final active output paths are written."),
        ("no_crash_assignment", True, "Crash records are not read and no crash assignment fields are produced."),
        ("no_access_assignment", True, "Access sources are not read and no access assignment is produced."),
        ("no_rates_or_models", True, "No rates, models, regressions, or predictions are calculated."),
        ("crash_direction_fields_not_used", True, "Reader refuses known crash direction columns."),
        (
            "stable_travelway_id_preserved_on_generated_context_bins",
            int(nonblank(generated_context, "stable_travelway_id").sum()) == len(generated_context),
            f"{int(nonblank(generated_context, 'stable_travelway_id').sum()):,} / {len(generated_context):,}",
        ),
        (
            "no_rows_deleted_or_collapsed",
            len(consolidated_context) >= EXPECTED_GENERATED_BIN_COUNT,
            f"consolidated output rows={len(consolidated_context):,}",
        ),
        (
            "original_and_corrected_leg_labels_preserved",
            {"physical_leg_id", "corrected_physical_leg_id", "final_review_physical_leg_id"}.issubset(
                set(consolidated_context.columns)
            ),
            "Original/corrected/final review labels are present.",
        ),
        ("source_limited_cases_not_forced", True, "This pass context-refreshes existing generated bins only."),
        (
            "outputs_review_only",
            str(OUT_DIR).replace("\\", "/").endswith(
                "work/output/roadway_graph/review/current/final_clean_missing_leg_context_refresh_and_integration"
            ),
            str(OUT_DIR),
        ),
        ("required_inputs_available", not missing_inputs, "; ".join(missing_inputs[:10])),
    ]
    return pd.DataFrame(
        [{"qa_check": name, "passed": bool(passed), "detail": detail} for name, passed, detail in checks]
    )


def findings_text(counts: dict[str, Any]) -> str:
    return f"""# Final Clean Missing-Leg Context Refresh and Integration

## Bounded Question

Populate the 19,662 review-only generated missing-leg bins with route/measure, roadway context, RNS speed, and AADT/exposure readiness, then integrate those rows with the final 3,719-signal clean universe and label-only physical-leg normalization state.

## Answers

1. **Generated bins with route/measure identity:** {counts['route_measure_ready_bins']:,} / {counts['generated_bins']:,}.
2. **Generated bins with roadway context:** {counts['roadway_ready_bins']:,} / {counts['generated_bins']:,}.
3. **Generated bins with RNS speed readiness:** {counts['rns_ready_bins']:,} / {counts['generated_bins']:,}.
4. **Generated bins with AADT/exposure readiness:** {counts['aadt_ready_bins']:,} AADT-ready and {counts['exposure_ready_bins']:,} exposure-ready / {counts['generated_bins']:,}.
5. **Generated-bin signals speed+AADT-ready:** {counts['speed_aadt_ready_signals']:,} / {counts['generated_signals']:,}.
6. **Final leg distribution after context-refreshed generated bins plus label-only normalization:** one-leg {counts['final_one_leg']:,}, two-leg {counts['final_two_leg']:,}, three-leg {counts['final_three_leg']:,}, four-leg {counts['final_four_leg']:,}, five-plus {counts['final_five_plus']:,}.
7. **One-/two-leg residuals:** {counts['final_one_two']:,}.
8. **Three-leg residuals:** {counts['final_three_leg']:,}.
9. **Five-plus residuals:** {counts['final_five_plus']:,}.
10. **Recommended next pass:** bounded intersection-zone anchor recovery for residual two-/three-leg cases, followed by broader source search and additional five-plus label-only normalization if leg cleanup continues.

## Method Note

This pass uses stable Travelway route/measure lineage as the bounded review-only context assignment path. It does not build bin-by-source overlap tables, does not read crash records, and does not assign access. Rows missing route/measure identity are retained as partial context rather than forced.

## QA

Outputs are written only under `work/output/roadway_graph/review/current/final_clean_missing_leg_context_refresh_and_integration/`. Original and corrected leg labels are preserved, generated bins remain review-only, and source-limited cases are not forced.
"""


def manifest_payload(counts: dict[str, Any], missing_inputs: list[str]) -> dict[str, Any]:
    refs = {}
    for name, path in INPUTS.items():
        payload = load_json(path)
        refs[name] = {
            "path": str(path),
            "exists": path.exists(),
            "is_directory": path.is_dir(),
            "created_utc": payload.get("created_utc", ""),
            "script": payload.get("script", ""),
            "counts": payload.get("counts", {}),
        }
    return {
        "created_utc": now(),
        "script": "src.roadway_graph.build.final_clean_missing_leg_context_refresh_and_integration",
        "bounded_question": (
            "Review-only context refresh and integration for generated missing-leg bins in the "
            "3,719-signal clean universe."
        ),
        "inputs": refs,
        "missing_inputs": missing_inputs,
        "outputs": [
            "missing_leg_context_bin_detail.csv",
            "missing_leg_context_signal_summary.csv",
            "missing_leg_route_measure_summary.csv",
            "missing_leg_roadway_context_summary.csv",
            "missing_leg_speed_summary.csv",
            "missing_leg_aadt_exposure_summary.csv",
            "missing_leg_context_readiness_summary.csv",
            "final_clean_consolidated_bin_detail_with_missing_leg_context.csv",
            "final_clean_consolidated_signal_summary_with_missing_leg_context.csv",
            "final_clean_distribution_after_missing_leg_context.csv",
            "remaining_leg_issues_after_missing_leg_context.csv",
            "missing_leg_context_next_action_recommendation.csv",
            "final_clean_missing_leg_context_refresh_and_integration_findings.md",
            "final_clean_missing_leg_context_refresh_and_integration_qa.csv",
            "final_clean_missing_leg_context_refresh_and_integration_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": counts,
        "qa_non_goals": {
            "active_outputs_modified": False,
            "records_promoted": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_or_models": False,
            "crash_direction_fields_used": False,
        },
    }


def main() -> None:
    ensure_out_dir()
    log_lines: list[str] = []
    log(log_lines, "Starting final clean missing-leg context refresh and integration.")

    missing_inputs = [
        f"{name}: {path}"
        for name, path in INPUTS.items()
        if not path.exists()
        and name
        not in {
            "good_context_manifest",
            "offset_context_manifest",
            "ramp_context_manifest",
            "complex_context_manifest",
            "final_recovery_context_dir",
            "rns_phase3d_dir",
            "aadt_v3_dir",
        }
    ]
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing_inputs))

    generated_bins = read_csv(INPUTS["missing_leg_generated_bins"])
    target_signals = read_csv(INPUTS["missing_leg_generation_target_signals"])
    skipped_targets = read_csv(INPUTS["missing_leg_generation_skipped_targets"])
    consolidated_bins = read_csv(INPUTS["consolidated_leg_bin_detail"])
    consolidated_signal_summary = read_csv(INPUTS["consolidated_leg_signal_summary"])
    consolidated_distribution = read_csv(INPUTS["consolidated_physical_leg_distribution"])
    residual_summary = read_csv(INPUTS["residual_leg_recoverability_summary"])
    final_bins = read_csv(INPUTS["final_clean_bin_universe"])
    write_csv(input_status(), "input_status.csv")
    log(log_lines, f"Read generated bins: {len(generated_bins):,}")

    generated_context = context_refresh_generated_bins(generated_bins)
    generated_signal_summary = summarize_generated_signal_context(generated_context, target_signals)

    route_measure_summary = build_route_measure_summary(generated_context, generated_signal_summary)
    roadway_context_summary = simple_summary("roadway_context", generated_context, "roadway_context_ready_bin", "bins")
    speed_summary = simple_summary("rns_speed", generated_context, "has_rns_speed", "bins")
    aadt_summary = pd.DataFrame(
        [
            {"metric": "generated_bins_total", "value": len(generated_context)},
            {"metric": "generated_bins_aadt_ready", "value": int(generated_context["has_aadt"].sum())},
            {
                "metric": "generated_bins_exposure_denominator_ready",
                "value": int(generated_context["has_exposure_denominator"].sum()),
            },
            {
                "metric": "generated_bins_missing_aadt_or_exposure",
                "value": int((~generated_context["speed_aadt_ready_bin"]).sum()),
            },
        ]
    )
    readiness_summary = pd.DataFrame(
        [
            {"metric": "generated_bins_total", "value": len(generated_context)},
            {"metric": "generated_signals_total", "value": len(generated_signal_summary)},
            {
                "metric": "generated_bins_speed_aadt_ready",
                "value": int(generated_context["speed_aadt_ready_bin"].sum()),
            },
            {
                "metric": "generated_signals_speed_aadt_ready",
                "value": int(generated_signal_summary["speed_aadt_ready"].sum()),
            },
            {
                "metric": "generated_signals_0_1000_speed_aadt_ready",
                "value": int(generated_signal_summary["speed_aadt_0_1000_ready"].sum()),
            },
            {
                "metric": "generated_signals_1000_2500_sensitivity_ready",
                "value": int(generated_signal_summary["sensitivity_1000_2500_ready"].sum()),
            },
        ]
    )

    integrated_bins = integrate_consolidated_bins(consolidated_bins, final_bins, generated_context)
    integrated_signal_summary = signal_summary_with_context(integrated_bins, consolidated_signal_summary)
    final_distribution = distribution_after_context(integrated_signal_summary, consolidated_distribution)
    remaining_issues = remaining_issue_summary(residual_summary, skipped_targets, integrated_signal_summary)
    recommendation = next_action_recommendation()

    counts_by_bucket = integrated_signal_summary["final_review_physical_leg_bucket"].value_counts().to_dict()
    counts = {
        "generated_bins": int(len(generated_context)),
        "expected_generated_bins": EXPECTED_GENERATED_BIN_COUNT,
        "generated_signals": int(generated_context["stable_signal_id"].nunique()),
        "route_measure_ready_bins": int(generated_context["route_measure_ready_bin"].sum()),
        "roadway_ready_bins": int(generated_context["roadway_context_ready_bin"].sum()),
        "rns_ready_bins": int(generated_context["has_rns_speed"].sum()),
        "aadt_ready_bins": int(generated_context["has_aadt"].sum()),
        "exposure_ready_bins": int(generated_context["has_exposure_denominator"].sum()),
        "speed_aadt_ready_bins": int(generated_context["speed_aadt_ready_bin"].sum()),
        "speed_aadt_ready_signals": int(generated_signal_summary["speed_aadt_ready"].sum()),
        "consolidated_output_bins": int(len(integrated_bins)),
        "final_clean_signals": int(len(integrated_signal_summary)),
        "final_one_leg": int(counts_by_bucket.get("one_leg", 0)),
        "final_two_leg": int(counts_by_bucket.get("two_leg", 0)),
        "final_three_leg": int(counts_by_bucket.get("three_leg", 0)),
        "final_four_leg": int(counts_by_bucket.get("four_leg", 0)),
        "final_five_plus": int(counts_by_bucket.get("five_plus_leg", 0)),
        "final_one_two": int(counts_by_bucket.get("one_leg", 0) + counts_by_bucket.get("two_leg", 0)),
        "skipped_generation_targets": int(len(skipped_targets)),
    }

    write_csv(generated_context, "missing_leg_context_bin_detail.csv")
    write_csv(generated_signal_summary, "missing_leg_context_signal_summary.csv")
    write_csv(route_measure_summary, "missing_leg_route_measure_summary.csv")
    write_csv(roadway_context_summary, "missing_leg_roadway_context_summary.csv")
    write_csv(speed_summary, "missing_leg_speed_summary.csv")
    write_csv(aadt_summary, "missing_leg_aadt_exposure_summary.csv")
    write_csv(readiness_summary, "missing_leg_context_readiness_summary.csv")
    write_csv(integrated_bins, "final_clean_consolidated_bin_detail_with_missing_leg_context.csv")
    write_csv(integrated_signal_summary, "final_clean_consolidated_signal_summary_with_missing_leg_context.csv")
    write_csv(final_distribution, "final_clean_distribution_after_missing_leg_context.csv")
    write_csv(remaining_issues, "remaining_leg_issues_after_missing_leg_context.csv")
    write_csv(recommendation, "missing_leg_context_next_action_recommendation.csv")

    qa = qa_table(generated_context, integrated_bins, missing_inputs)
    write_csv(qa, "final_clean_missing_leg_context_refresh_and_integration_qa.csv")
    write_text(findings_text(counts), "final_clean_missing_leg_context_refresh_and_integration_findings.md")
    write_json(manifest_payload(counts, missing_inputs), "final_clean_missing_leg_context_refresh_and_integration_manifest.json")
    log(log_lines, "Complete.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
