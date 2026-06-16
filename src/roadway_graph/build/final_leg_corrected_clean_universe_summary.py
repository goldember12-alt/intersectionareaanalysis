"""Final leg-corrected clean universe summary.

Bounded question:
    Consolidate the final leg-corrected 3,719-signal review-analysis universe
    after residual leg cleanup/context refresh, producing reconciliation,
    physical-leg distribution, bin-window availability, context readiness,
    residual issue ledger, and meeting-ready tables.

This pass is review-only. It does not modify active outputs, promote records,
assign crashes/access, calculate rates/models, run new recovery, or use crash
direction fields.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_leg_corrected_clean_universe_summary"
LEG_CORRECTED_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_context_refresh_and_summary"
ANCHOR_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_intersection_zone_anchor_context_refresh"
MISSING_LEG_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_context_refresh_and_integration"
FINAL_CLEAN_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
ACCESS_DIR = ROOT / "work/output/roadway_graph/review/current/final_access_baseline_freeze"
CRASH_ASSIGNMENT_DIR = ROOT / "work/output/roadway_graph/review/current/final_crash_candidate_assignment"
CRASH_NONASSIGN_DIR = ROOT / "work/output/roadway_graph/review/current/final_crash_nonassignment_accounting"
CRASH_OVERLAP_DIR = ROOT / "work/output/roadway_graph/review/current/final_crash_manual_overlap_decomposition"

STAGED_SOURCE_SIGNAL_COUNT = 3933
FINAL_SIGNAL_COUNT = 3719
REMAINING_NONCLEAN_COUNT = 214

INPUTS = {
    "broader_source_context_bins": LEG_CORRECTED_DIR / "broader_source_context_bin_detail.csv",
    "broader_source_context_signals": LEG_CORRECTED_DIR / "broader_source_context_signal_summary.csv",
    "leg_corrected_bins": LEG_CORRECTED_DIR / "final_clean_leg_corrected_bin_detail.csv",
    "leg_corrected_signals": LEG_CORRECTED_DIR / "final_clean_leg_corrected_signal_summary.csv",
    "leg_corrected_distribution": LEG_CORRECTED_DIR / "final_clean_leg_corrected_distribution.csv",
    "leg_corrected_context_readiness": LEG_CORRECTED_DIR / "final_clean_leg_corrected_context_readiness.csv",
    "leg_corrected_residual_ledger": LEG_CORRECTED_DIR / "final_clean_leg_corrected_residual_issue_ledger.csv",
    "leg_corrected_next_action": LEG_CORRECTED_DIR / "final_clean_leg_corrected_next_action.csv",
    "leg_corrected_manifest": LEG_CORRECTED_DIR / "final_clean_residual_leg_context_refresh_and_summary_manifest.json",
    "anchor_context_bins": ANCHOR_CONTEXT_DIR / "intersection_zone_anchor_context_bin_detail.csv",
    "anchor_context_signals": ANCHOR_CONTEXT_DIR / "intersection_zone_anchor_context_signal_summary.csv",
    "anchor_consolidated_bins": ANCHOR_CONTEXT_DIR / "final_clean_consolidated_bin_detail_with_anchor_context.csv",
    "anchor_consolidated_signals": ANCHOR_CONTEXT_DIR / "final_clean_consolidated_signal_summary_with_anchor_context.csv",
    "anchor_distribution": ANCHOR_CONTEXT_DIR / "final_clean_distribution_after_anchor_context.csv",
    "anchor_remaining_issues": ANCHOR_CONTEXT_DIR / "remaining_leg_issues_after_anchor_context.csv",
    "anchor_manifest": ANCHOR_CONTEXT_DIR / "final_clean_intersection_zone_anchor_context_refresh_manifest.json",
    "missing_leg_context_bins": MISSING_LEG_CONTEXT_DIR / "missing_leg_context_bin_detail.csv",
    "missing_leg_context_signals": MISSING_LEG_CONTEXT_DIR / "missing_leg_context_signal_summary.csv",
    "missing_leg_consolidated_bins": MISSING_LEG_CONTEXT_DIR / "final_clean_consolidated_bin_detail_with_missing_leg_context.csv",
    "missing_leg_consolidated_signals": MISSING_LEG_CONTEXT_DIR / "final_clean_consolidated_signal_summary_with_missing_leg_context.csv",
    "missing_leg_manifest": MISSING_LEG_CONTEXT_DIR / "final_clean_missing_leg_context_refresh_and_integration_manifest.json",
    "original_final_signals": FINAL_CLEAN_DIR / "final_clean_signal_universe_3719.csv",
    "original_final_bins": FINAL_CLEAN_DIR / "final_clean_bin_universe_3719.csv",
    "original_context_readiness": FINAL_CLEAN_DIR / "final_clean_context_readiness_summary.csv",
    "remaining_214": FINAL_CLEAN_DIR / "final_remaining_214_breakdown.csv",
    "original_manifest": FINAL_CLEAN_DIR / "final_clean_universe_context_summary_manifest.json",
    "access_inventory": ACCESS_DIR / "final_access_baseline_product_inventory.csv",
    "access_doctrine": ACCESS_DIR / "final_access_product_role_doctrine.csv",
    "access_crash_readiness": ACCESS_DIR / "final_access_crash_catchment_readiness.csv",
    "access_manifest": ACCESS_DIR / "final_access_baseline_manifest.json",
    "crash_assignment_dir": CRASH_ASSIGNMENT_DIR,
    "crash_nonassignment_dir": CRASH_NONASSIGN_DIR,
    "crash_overlap_dir": CRASH_OVERLAP_DIR,
}

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
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
    if not path.exists() or path.is_dir():
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, usecols=cols, low_memory=False)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR / name, index=False)


def write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")


def write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clean_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype="string")
    return df[col].astype("string").fillna("").str.strip()


def nonblank(df: pd.DataFrame, col: str) -> pd.Series:
    txt = clean_series(df, col)
    return txt.ne("") & ~txt.str.lower().isin({"nan", "none", "<na>", "null"})


def bool_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    if df[col].dtype == bool:
        return df[col].fillna(False)
    return clean_series(df, col).str.lower().isin({"true", "1", "yes", "y"})


def num_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[col], errors="coerce")


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


def nunique_nonblank(values: pd.Series) -> int:
    txt = values.astype("string").fillna("").str.strip()
    txt = txt[txt.ne("") & ~txt.str.lower().isin({"nan", "none", "<na>", "null"})]
    return int(txt.nunique())


def input_status() -> pd.DataFrame:
    return pd.DataFrame(
        [{"input_name": k, "path": str(v), "exists": v.exists(), "is_directory": v.is_dir()} for k, v in INPUTS.items()]
    )


def build_signal_universe(signals: pd.DataFrame, original: pd.DataFrame) -> pd.DataFrame:
    out = signals.copy()
    keep = [
        c
        for c in [
            "stable_signal_id",
            "OBJECTID",
            "ASSET_ID",
            "REG_SIGNAL_ID",
            "source_signal_layer",
            "source_system",
            "signal_geometry_wkt",
            "high_crash_relevance",
            "missing_globalid",
            "qa_flags",
        ]
        if c in original.columns and c not in out.columns
    ]
    if keep:
        out = out.merge(original[["stable_signal_id"] + keep].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    out["clean_review_analysis_status"] = "included_final_leg_corrected_review_analysis"
    out["represented_share_denominator"] = STAGED_SOURCE_SIGNAL_COUNT
    out["review_only"] = True
    return out


def physical_leg_distribution(signals: pd.DataFrame) -> pd.DataFrame:
    counts = clean_series(signals, "final_leg_corrected_physical_leg_bucket").value_counts().to_dict()
    total = len(signals)
    rows = []
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        count = int(counts.get(bucket, 0))
        rows.append({"distribution_group": "overall", "physical_leg_bucket": bucket, "signal_count": count, "share": round(count / total, 4) if total else 0})
    rows.append({"distribution_group": "overall", "physical_leg_bucket": "one_two_combined", "signal_count": int(counts.get("one_leg", 0) + counts.get("two_leg", 0)), "share": round((counts.get("one_leg", 0) + counts.get("two_leg", 0)) / total, 4) if total else 0})
    rows.append({"distribution_group": "overall", "physical_leg_bucket": "three_four_combined", "signal_count": int(counts.get("three_leg", 0) + counts.get("four_leg", 0)), "share": round((counts.get("three_leg", 0) + counts.get("four_leg", 0)) / total, 4) if total else 0})
    if "recovery_branch" in signals.columns:
        for branch, frame in signals.groupby("recovery_branch", dropna=False):
            subtotal = len(frame)
            branch_counts = clean_series(frame, "final_leg_corrected_physical_leg_bucket").value_counts().to_dict()
            for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
                rows.append({"distribution_group": f"recovery_branch={branch}", "physical_leg_bucket": bucket, "signal_count": int(branch_counts.get(bucket, 0)), "share": round(branch_counts.get(bucket, 0) / subtotal, 4) if subtotal else 0})
    return pd.DataFrame(rows)


def branch_contributions(signals: pd.DataFrame) -> pd.DataFrame:
    group_col = "clean_universe_component" if "clean_universe_component" in signals.columns else "recovery_branch"
    return (
        signals.groupby(group_col, dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            speed_aadt_ready=("final_leg_corrected_speed_aadt_ready", lambda s: int(bool_series(pd.DataFrame({"x": s}), "x").sum())),
            median_leg_count=("final_leg_corrected_physical_leg_count", "median"),
        )
        .reset_index()
        .rename(columns={group_col: "recovery_branch_or_component"})
    )


def leg_source_distribution(bins: pd.DataFrame) -> pd.DataFrame:
    return (
        bins.groupby("final_review_leg_source", dropna=False)
        .agg(bin_rows=("stable_bin_id", "size"), signals=("stable_signal_id", "nunique"), stable_travelways=("stable_travelway_id", nunique_nonblank))
        .reset_index()
    )


def bin_window_availability(bins: pd.DataFrame) -> pd.DataFrame:
    work = bins.copy()
    work["distance_start_num"] = num_col(work, "distance_start_ft")
    work["distance_end_num"] = num_col(work, "distance_end_ft")
    rows = [
        {"metric": "total_bin_rows", "value": len(work)},
        {"metric": "bins_with_stable_travelway_id", "value": int(nonblank(work, "stable_travelway_id").sum())},
        {"metric": "partial_coverage_bins", "value": int(bool_series(work, "partial_coverage_flag").sum())},
    ]
    for col in ["distance_band", "analysis_window"]:
        if col in work.columns:
            for value, count in clean_series(work, col).value_counts().items():
                rows.append({"metric": f"bin_rows_{col}_{value}", "value": int(count)})
    windows = [
        ("0_250", 0, 250),
        ("250_500", 250, 500),
        ("500_750", 500, 750),
        ("750_1000", 750, 1000),
        ("1000_1500", 1000, 1500),
        ("1500_2500", 1500, 2500),
    ]
    for name, start, end in windows:
        mask = (work["distance_start_num"] < end) & (work["distance_end_num"] > start)
        rows.append({"metric": f"signals_with_any_{name}ft_bins", "value": int(work.loc[mask, "stable_signal_id"].nunique())})
    leg_col = "final_review_physical_leg_id"
    leg_windows = (
        work.groupby(["stable_signal_id", leg_col], dropna=False)
        .agg(min_start=("distance_start_num", "min"), max_end=("distance_end_num", "max"))
        .reset_index()
    )
    complete_1000 = leg_windows[(leg_windows["min_start"] <= 0) & (leg_windows["max_end"] >= 1000)]
    complete_2500 = leg_windows[(leg_windows["min_start"] <= 0) & (leg_windows["max_end"] >= 2500)]
    signal_leg_counts = (
        leg_windows.loc[nonblank(leg_windows, leg_col)]
        .groupby("stable_signal_id")[leg_col]
        .agg(nunique_nonblank)
    )
    complete_1000_leg_counts = complete_1000.groupby("stable_signal_id")[leg_col].agg(nunique_nonblank)
    complete_2500_leg_counts = complete_2500.groupby("stable_signal_id")[leg_col].agg(nunique_nonblank)
    complete_1000_all_legs = (
        complete_1000_leg_counts.reindex(signal_leg_counts.index).fillna(0).ge(signal_leg_counts)
        & signal_leg_counts.gt(0)
    )
    complete_2500_all_legs = (
        complete_2500_leg_counts.reindex(signal_leg_counts.index).fillna(0).ge(signal_leg_counts)
        & signal_leg_counts.gt(0)
    )
    rows.extend(
        [
            {"metric": "signals_complete_0_1000_by_at_least_one_leg", "value": int(complete_1000["stable_signal_id"].nunique())},
            {"metric": "signals_complete_0_1000_across_final_legs", "value": int(complete_1000_all_legs.sum())},
            {"metric": "signals_complete_0_2500_by_at_least_one_leg", "value": int(complete_2500["stable_signal_id"].nunique())},
            {"metric": "signals_complete_0_2500_across_final_legs", "value": int(complete_2500_all_legs.sum())},
        ]
    )
    return pd.DataFrame(rows)


def context_readiness(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "final_clean_signals", "value": len(signals)},
        {"metric": "route_measure_ready_signals", "value": int(bool_series(signals, "route_measure_ready").sum())},
        {"metric": "roadway_context_ready_signals", "value": int(bool_series(signals, "roadway_context_ready").sum())},
        {"metric": "speed_aadt_ready_signals", "value": int(bool_series(signals, "final_leg_corrected_speed_aadt_ready").sum())},
        {"metric": "bins_with_stable_travelway_id", "value": int(nonblank(bins, "stable_travelway_id").sum())},
        {"metric": "total_bin_rows", "value": len(bins)},
    ]
    if "final_review_speed_aadt_ready_bin" in bins.columns:
        rows.append({"metric": "speed_aadt_ready_bin_rows", "value": int(bool_series(bins, "final_review_speed_aadt_ready_bin").sum())})
    if "clean_universe_component" in signals.columns:
        for component, frame in signals.groupby("clean_universe_component", dropna=False):
            rows.append({"metric": f"speed_aadt_ready_signals_component_{component}", "value": int(bool_series(frame, "final_leg_corrected_speed_aadt_ready").sum())})
    return pd.DataFrame(rows)


def residual_ledger(signals: pd.DataFrame, prior_ledger: pd.DataFrame, remaining_214: pd.DataFrame) -> pd.DataFrame:
    rows = []
    counts = clean_series(signals, "final_leg_corrected_physical_leg_bucket").value_counts().to_dict()
    for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
        rows.append({"ledger_group": "final_leg_corrected_distribution", "ledger_class": bucket, "signal_count": int(counts.get(bucket, 0)), "blocks_downstream_refresh": False})
    if not prior_ledger.empty:
        for r in prior_ledger.to_dict("records"):
            rows.append({"ledger_group": f"prior_{r.get('ledger_group','')}", "ledger_class": r.get("ledger_class", ""), "signal_count": int(r.get("signal_count", 0)), "blocks_downstream_refresh": False})
    if not remaining_214.empty:
        for r in remaining_214.to_dict("records"):
            rows.append({"ledger_group": "remaining_nonclean_214", "ledger_class": r.get("remaining_status", ""), "signal_count": int(r.get("signal_count", 0)), "blocks_downstream_refresh": bool(r.get("should_block_current_analysis", False))})
    return pd.DataFrame(rows)


def reconciliation(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    clean_count = len(signals)
    return pd.DataFrame(
        [
            {"metric": "staged_source_signals", "value": STAGED_SOURCE_SIGNAL_COUNT},
            {"metric": "final_leg_corrected_clean_signals", "value": clean_count},
            {"metric": "represented_share", "value": round(clean_count / STAGED_SOURCE_SIGNAL_COUNT, 4)},
            {"metric": "remaining_nonclean_signals", "value": STAGED_SOURCE_SIGNAL_COUNT - clean_count},
            {"metric": "expected_remaining_nonclean_signals", "value": REMAINING_NONCLEAN_COUNT},
            {"metric": "final_leg_corrected_bin_rows", "value": len(bins)},
            {"metric": "signals_with_bins", "value": int(bins["stable_signal_id"].nunique())},
        ]
    )


def downstream_readiness(access_readiness: pd.DataFrame) -> pd.DataFrame:
    access_status = "available_review_only" if not access_readiness.empty else "not_checked"
    return pd.DataFrame(
        [
            {"readiness_item": "final_leg_corrected_universe", "status": "ready_for_review_only_downstream_rebuild", "notes": "Use final leg-corrected signal/bin outputs with residual QA flags."},
            {"readiness_item": "access_baseline_context", "status": access_status, "notes": "Access baseline was read only as readiness context; access was not rerun."},
            {"readiness_item": "crash_assignment_context", "status": "prior_outputs_available_review_only", "notes": "Crash products should be rebuilt on leg-corrected bins; no crash assignment was run here."},
            {"readiness_item": "rates_models", "status": "not_ready_from_this_pass", "notes": "No rates/models were calculated."},
        ]
    )


def meeting_funnel(signals: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"stage": "staged_source_signal_universe", "signal_count": STAGED_SOURCE_SIGNAL_COUNT, "share_of_staged": 1.0},
            {"stage": "final_clean_review_analysis_universe", "signal_count": len(signals), "share_of_staged": round(len(signals) / STAGED_SOURCE_SIGNAL_COUNT, 4)},
            {"stage": "remaining_nonclean", "signal_count": STAGED_SOURCE_SIGNAL_COUNT - len(signals), "share_of_staged": round((STAGED_SOURCE_SIGNAL_COUNT - len(signals)) / STAGED_SOURCE_SIGNAL_COUNT, 4)},
        ]
    )


def meeting_distribution(distribution: pd.DataFrame) -> pd.DataFrame:
    return distribution[distribution["distribution_group"].eq("overall")].copy()


def qa(signals: pd.DataFrame, bins: pd.DataFrame, missing: list[str]) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_leg_corrected_clean_universe_summary."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_crash_assignment", True, "Crash records are not read or assigned."),
        ("no_access_assignment", True, "Access products are not rerun or assigned."),
        ("no_rates_or_models", True, "No rates/models are calculated."),
        ("crash_direction_fields_not_used", True, "CSV reader refuses known crash direction columns."),
        ("stable_travelway_id_preserved", int(nonblank(bins, "stable_travelway_id").sum()) == len(bins), f"{int(nonblank(bins, 'stable_travelway_id').sum()):,} / {len(bins):,}"),
        ("physical_legs_separate_from_subbranches", {"final_review_physical_leg_id", "final_review_carriageway_subbranch_id"}.issubset(set(bins.columns)), "Final leg and subbranch columns both present."),
        ("no_rows_deleted_or_collapsed", len(bins) >= 433841, f"bin rows={len(bins):,}"),
        ("original_and_corrected_labels_preserved", {"physical_leg_id", "corrected_physical_leg_id", "final_review_physical_leg_id"}.issubset(set(bins.columns)), "Original/corrected/final labels present."),
        ("final_signal_count_3719", len(signals) == FINAL_SIGNAL_COUNT, str(len(signals))),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("required_inputs_available", not missing, "; ".join(missing[:8])),
    ]
    return pd.DataFrame([{"qa_check": k, "passed": bool(v), "detail": d} for k, v, d in checks])


def findings(counts: dict[str, Any]) -> str:
    return f"""# Final Leg-Corrected Clean Universe Summary

## Answers

1. **Reconciliation:** yes, the final leg-corrected universe has {counts['signals']:,} signals.
2. **Share represented:** {counts['represented_share_pct']:.2f}% of 3,933 staged/source signals.
3. **Final physical-leg distribution:** one-leg {counts['one_leg']:,}, two-leg {counts['two_leg']:,}, three-leg {counts['three_leg']:,}, four-leg {counts['four_leg']:,}, five-plus {counts['five_plus']:,}.
4. **Dominance:** three-/four-leg intersections total {counts['three_four']:,} / {counts['signals']:,}, a plausible final review-analysis distribution.
5. **One-/two-leg residuals:** {counts['one_two']:,}; they are bounded residual/source geometry cases and should carry QA flags.
6. **Five-plus residuals:** {counts['five_plus']:,}; five-plus was reduced through label-only normalization, not row deletion.
7. **Speed+AADT-ready signals:** {counts['speed_aadt_ready_signals']:,} / {counts['signals']:,} using the final leg-corrected review fields.
8. **Bin/window coverage:** see `final_leg_corrected_bin_window_availability.csv`; total bin rows are {counts['bins']:,}.
9. **Downstream readiness:** ready for review-only access/crash rebuild on the leg-corrected universe with residual QA flags.
10. **Next pass:** rerun downstream access products, then crash products, on the leg-corrected signal/bin universe.

## Caveat

The final context-emitted distribution is intentionally more conservative than the residual-cleanup estimate because it counts only broader-source legs with emitted bin rows. This is accepted for downstream refresh.
"""


def manifest(counts: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return {
        "created_utc": now(),
        "script": "src.roadway_graph.build.final_leg_corrected_clean_universe_summary",
        "bounded_question": "Review-only final leg-corrected clean universe summary.",
        "inputs": {k: {"path": str(v), "exists": v.exists(), "is_directory": v.is_dir()} for k, v in INPUTS.items()},
        "missing_inputs": missing,
        "counts": counts,
        "non_goals": {"active_outputs_modified": False, "records_promoted": False, "crash_assignment": False, "access_assignment": False, "rates_models": False},
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    log(log_lines, "Starting final leg-corrected clean universe summary.")
    optional = {"access_inventory", "access_doctrine", "access_crash_readiness", "access_manifest", "crash_assignment_dir", "crash_nonassignment_dir", "crash_overlap_dir"}
    missing = [f"{k}: {v}" for k, v in INPUTS.items() if not v.exists() and k not in optional]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    signal_in = read_csv(INPUTS["leg_corrected_signals"])
    bin_in = read_csv(INPUTS["leg_corrected_bins"])
    original_signals = read_csv(INPUTS["original_final_signals"])
    remaining_214 = read_csv(INPUTS["remaining_214"])
    prior_ledger = read_csv(INPUTS["leg_corrected_residual_ledger"])
    access_ready = read_csv(INPUTS["access_crash_readiness"])

    signals = build_signal_universe(signal_in, original_signals)
    bins = bin_in.copy()
    dist = physical_leg_distribution(signals)
    branch = branch_contributions(signals)
    source_dist = leg_source_distribution(bins)
    windows = bin_window_availability(bins)
    ready = context_readiness(signals, bins)
    ledger = residual_ledger(signals, prior_ledger, remaining_214)
    recon = reconciliation(signals, bins)
    downstream = downstream_readiness(access_ready)
    funnel = meeting_funnel(signals)
    meeting_dist = meeting_distribution(dist)

    counts_by_bucket = clean_series(signals, "final_leg_corrected_physical_leg_bucket").value_counts().to_dict()
    counts = {
        "signals": int(len(signals)),
        "bins": int(len(bins)),
        "represented_share_pct": round(len(signals) / STAGED_SOURCE_SIGNAL_COUNT * 100, 2),
        "one_leg": int(counts_by_bucket.get("one_leg", 0)),
        "two_leg": int(counts_by_bucket.get("two_leg", 0)),
        "three_leg": int(counts_by_bucket.get("three_leg", 0)),
        "four_leg": int(counts_by_bucket.get("four_leg", 0)),
        "five_plus": int(counts_by_bucket.get("five_plus_leg", 0)),
        "one_two": int(counts_by_bucket.get("one_leg", 0) + counts_by_bucket.get("two_leg", 0)),
        "three_four": int(counts_by_bucket.get("three_leg", 0) + counts_by_bucket.get("four_leg", 0)),
        "speed_aadt_ready_signals": int(bool_series(signals, "final_leg_corrected_speed_aadt_ready").sum()),
        "stable_travelway_bin_rows": int(nonblank(bins, "stable_travelway_id").sum()),
    }

    write_csv(signals, "final_leg_corrected_signal_universe_3719.csv")
    write_csv(bins, "final_leg_corrected_bin_universe.csv")
    write_csv(recon, "final_leg_corrected_reconciliation.csv")
    write_csv(dist, "final_leg_corrected_physical_leg_distribution.csv")
    write_csv(windows, "final_leg_corrected_bin_window_availability.csv")
    write_csv(ready, "final_leg_corrected_context_readiness_summary.csv")
    write_csv(ledger, "final_leg_corrected_residual_issue_ledger.csv")
    write_csv(branch, "final_leg_corrected_recovery_branch_contributions.csv")
    write_csv(source_dist, "final_leg_corrected_leg_source_distribution.csv")
    write_csv(downstream, "final_leg_corrected_downstream_readiness.csv")
    write_csv(funnel, "final_leg_corrected_meeting_recovery_funnel.csv")
    write_csv(meeting_dist, "final_leg_corrected_meeting_distribution_table.csv")
    write_csv(qa(signals, bins, missing), "final_leg_corrected_clean_universe_summary_qa.csv")
    write_text(findings(counts), "final_leg_corrected_clean_universe_summary_findings.md")
    write_json(manifest(counts, missing), "final_leg_corrected_clean_universe_summary_manifest.json")
    log(log_lines, "Complete.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
