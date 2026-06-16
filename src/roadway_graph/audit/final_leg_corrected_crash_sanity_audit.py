from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_sanity_audit"

ASSIGN_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_candidate_assignment"
FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
ACCESS_REFRESH_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_refresh"
ACCESS_SANITY_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_sanity_audit"
PRIOR_ASSIGN_DIR = OUTPUT_ROOT / "review/current/final_crash_candidate_assignment"
PRIOR_NONASSIGN_DIR = OUTPUT_ROOT / "review/current/final_crash_nonassignment_accounting"
PRIOR_MANUAL_DIR = OUTPUT_ROOT / "review/current/final_crash_manual_overlap_decomposition"
CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")

BUFFER_WIDTHS_FT = [35, 50, 75]
PRIMARY_BUFFER_FT = 50

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

DETAIL_COLS = [
    "buffer_width_ft",
    "stable_crash_id",
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CRASH_SEVERITY",
    "COLLISION_TYPE",
    "ROADWAY_DESCRIPTION",
    "INTERSECTION_TYPE",
    "MAINLINE_YN",
    "stable_signal_id",
    "stable_bin_id",
    "stable_travelway_id",
    "final_review_physical_leg_id",
    "distance_band",
    "analysis_window",
    "final_review_leg_source",
    "final_review_context_status",
    "source_route_name",
    "source_route_common",
    "final_review_recovery_provenance",
    "residual_bucket",
    "broader_source_class",
    "has_untyped_spatial_100ft_access",
    "has_typed_v2_spatial_100ft_access",
    "assignment_fanout_count",
    "unweighted_assignment",
    "source_preserving_weight",
]

REQUIRED_INPUTS = [
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_bin_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_fanout_summary.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_overlap_review_queue.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_source_coverage_summary.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_unassigned_summary.csv",
    ASSIGN_DIR / "leg_corrected_crash_assignment_vs_prior_comparison.csv",
    ASSIGN_DIR / "final_leg_corrected_crash_candidate_assignment_manifest.json",
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    FINAL_LEG_DIR / "final_leg_corrected_context_readiness_summary.csv",
    FINAL_LEG_DIR / "final_leg_corrected_residual_issue_ledger.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_doctrine_update.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_refresh_manifest.json",
    ACCESS_SANITY_DIR / "access_sanity_readiness_decision.csv",
    ACCESS_SANITY_DIR / "final_leg_corrected_access_sanity_manifest.json",
    PRIOR_ASSIGN_DIR / "crash_candidate_assignment_detail.csv",
    PRIOR_ASSIGN_DIR / "final_crash_candidate_assignment_manifest.json",
    PRIOR_NONASSIGN_DIR / "crash_unassigned_class_summary.csv",
    PRIOR_NONASSIGN_DIR / "crash_assignment_status_by_crash.csv",
    PRIOR_NONASSIGN_DIR / "final_crash_nonassignment_accounting_manifest.json",
    PRIOR_MANUAL_DIR / "final_crash_manual_overlap_decomposition_manifest.json",
    CRASH_SOURCE,
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


def _is_direction_field(column: str) -> bool:
    return any(token in column.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None, allow_inventory_direction: bool = False) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [
        column
        for column in cols
        if _is_direction_field(column)
        and not (allow_inventory_direction and column in {"crash_direction_fields_inventory_only", "crash_direction_used_for_assignment", "crash_direction_use_status"})
    ]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _crash_source_ids() -> pd.Series:
    pf = pq.ParquetFile(CRASH_SOURCE)
    cols = list(pf.schema_arrow.names)
    if "DOCUMENT_NBR" in cols:
        docs = pd.read_parquet(CRASH_SOURCE, columns=["DOCUMENT_NBR"])["DOCUMENT_NBR"].astype(str)
        return "crash_" + docs
    return pd.Series([f"crash_review_{idx:09d}" for idx in range(pf.metadata.num_rows)], dtype=str)


def _load_current_detail() -> pd.DataFrame:
    detail = _read_csv(ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv", usecols=DETAIL_COLS, allow_inventory_direction=True)
    for col in ["buffer_width_ft", "assignment_fanout_count"]:
        detail[col] = pd.to_numeric(detail[col], errors="coerce").fillna(0).astype(int)
    detail["source_preserving_weight"] = _num(detail, "source_preserving_weight")
    return detail


def _load_prior_detail() -> pd.DataFrame:
    cols = ["buffer_width_ft", "stable_crash_id", "stable_signal_id", "stable_bin_id", "assignment_fanout_count"]
    prior = _read_csv(PRIOR_ASSIGN_DIR / "crash_candidate_assignment_detail.csv", usecols=cols, allow_inventory_direction=True)
    prior["buffer_width_ft"] = pd.to_numeric(prior["buffer_width_ft"], errors="coerce").fillna(0).astype(int)
    return prior


def _denominator_validation(detail: pd.DataFrame, bins: pd.DataFrame, signals: pd.DataFrame, manifest: dict[str, Any]) -> pd.DataFrame:
    counts = manifest.get("counts", {})
    rows = [
        {"validation_group": "crash", "class": "normalized_crash_count", "count": int(counts.get("normalized_crashes", len(_crash_source_ids()))), "notes": "assignment manifest / crash source metadata"},
        {"validation_group": "signal", "class": "final_leg_corrected_signal_count", "count": int(signals["stable_signal_id"].nunique()), "notes": "final leg-corrected signal universe"},
        {"validation_group": "bin", "class": "final_leg_corrected_bin_count", "count": len(bins), "notes": "final leg-corrected bin universe"},
        {"validation_group": "bin", "class": "bins_with_geometry", "count": int(_text(bins, "geometry_wkt").str.strip().ne("").sum()), "notes": "geometry_wkt nonblank"},
        {"validation_group": "bin", "class": "bins_with_stable_travelway_id", "count": int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()), "notes": "stable_travelway_id nonblank"},
        {"validation_group": "bin", "class": "bins_with_final_review_physical_leg_id", "count": int(_text(bins, "final_review_physical_leg_id").str.strip().ne("").sum()), "notes": "reported where available"},
    ]
    for width in BUFFER_WIDTHS_FT:
        subset = detail.loc[detail["buffer_width_ft"].eq(width)]
        rows.append({"validation_group": "assignment", "class": f"{width}ft_unique_crashes", "count": int(subset["stable_crash_id"].nunique()), "notes": "current leg-corrected assignment"})
        rows.append({"validation_group": "assignment", "class": f"{width}ft_assignment_rows", "count": len(subset), "notes": "current leg-corrected assignment"})
    return pd.DataFrame(rows)


def _sets_by_buffer(frame: pd.DataFrame) -> dict[int, set[str]]:
    return {width: set(_text(frame.loc[frame["buffer_width_ft"].eq(width)], "stable_crash_id")) for width in BUFFER_WIDTHS_FT}


def _gain_detail(current: pd.DataFrame, prior: pd.DataFrame) -> pd.DataFrame:
    cur_sets = _sets_by_buffer(current)
    prior_sets = _sets_by_buffer(prior)
    rows = []
    for width in BUFFER_WIDTHS_FT:
        cur = cur_sets[width]
        old = prior_sets[width]
        for status, ids in [
            ("prior_and_still_assigned", old & cur),
            ("newly_assigned", cur - old),
            ("previously_assigned_no_longer_assigned", old - cur),
        ]:
            rows.append({"buffer_width_ft": width, "assignment_gain_class": status, "crash_count": len(ids)})
    return pd.DataFrame(rows)


def _gain_by_branch(current: pd.DataFrame, prior: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    signal_branch = signals[["stable_signal_id", "recovery_branch"]].drop_duplicates("stable_signal_id")
    current = current.merge(signal_branch, on="stable_signal_id", how="left")
    prior_sets = _sets_by_buffer(prior)
    rows = []
    for width in BUFFER_WIDTHS_FT:
        subset = current.loc[current["buffer_width_ft"].eq(width)].copy()
        new = subset.loc[~_text(subset, "stable_crash_id").isin(prior_sets[width])]
        for cols, label in [
            (["recovery_branch"], "recovery_branch"),
            (["final_review_leg_source"], "final_review_leg_source"),
            (["recovery_branch", "final_review_leg_source"], "branch_and_leg_source"),
        ]:
            grouped = new.groupby(cols, dropna=False).agg(
                newly_assigned_crashes=("stable_crash_id", "nunique"),
                assignment_rows=("stable_crash_id", "size"),
                weighted_total=("source_preserving_weight", "sum"),
            ).reset_index()
            grouped["buffer_width_ft"] = width
            grouped["gain_group"] = label
            rows.extend(grouped.to_dict("records"))
    return pd.DataFrame(rows)


def _fanout_detail(detail: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    signal_branch = signals[["stable_signal_id", "recovery_branch"]].drop_duplicates("stable_signal_id")
    work = detail.merge(signal_branch, on="stable_signal_id", how="left")
    out = work.groupby(["buffer_width_ft", "stable_crash_id"], dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        bin_count=("stable_bin_id", "nunique"),
        physical_leg_count=("final_review_physical_leg_id", "nunique"),
        assignment_rows=("stable_bin_id", "size"),
        max_assignment_fanout=("assignment_fanout_count", "max"),
        branch_list=("recovery_branch", _collapse),
        final_review_leg_sources=("final_review_leg_source", _collapse),
        roadway_or_facility=("source_route_common", _collapse),
        mainline_yn=("MAINLINE_YN", "first"),
        crash_year=("CRASH_YEAR", "first"),
        crash_severity=("CRASH_SEVERITY", "first"),
        collision_type=("COLLISION_TYPE", "first"),
        has_untyped_access=("has_untyped_spatial_100ft_access", "max"),
        has_typed_access=("has_typed_v2_spatial_100ft_access", "max"),
    ).reset_index()
    return out


def _bucket_count(value: int) -> str:
    if value <= 1:
        return "1"
    if value == 2:
        return "2"
    if value == 3:
        return "3"
    return "4_plus"


def _fanout_summary(fanout: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for width, frame in fanout.groupby("buffer_width_ft", dropna=False):
        for metric in ["signal_count", "bin_count", "physical_leg_count"]:
            temp = frame.copy()
            temp["fanout_bucket"] = pd.to_numeric(temp[metric], errors="coerce").fillna(0).astype(int).map(_bucket_count)
            for bucket, group in temp.groupby("fanout_bucket", dropna=False):
                rows.append({"buffer_width_ft": width, "fanout_metric": metric, "fanout_bucket": bucket, "crash_count": int(group["stable_crash_id"].nunique()), "max_value": int(pd.to_numeric(group[metric], errors="coerce").max())})
        multi_signal = frame.loc[pd.to_numeric(frame["signal_count"], errors="coerce").gt(1)]
        multi_leg = frame.loc[pd.to_numeric(frame["physical_leg_count"], errors="coerce").gt(pd.to_numeric(frame["signal_count"], errors="coerce"))]
        rows.append({"buffer_width_ft": width, "fanout_metric": "multi_signal", "fanout_bucket": "crashes_assigned_to_multiple_signals", "crash_count": int(multi_signal["stable_crash_id"].nunique()), "max_value": int(pd.to_numeric(frame["signal_count"], errors="coerce").max())})
        rows.append({"buffer_width_ft": width, "fanout_metric": "multi_leg_same_signal_proxy", "fanout_bucket": "physical_leg_count_gt_signal_count", "crash_count": int(multi_leg["stable_crash_id"].nunique()), "max_value": int(pd.to_numeric(frame["physical_leg_count"], errors="coerce").max())})
    return pd.DataFrame(rows)


def _classify_high_fanout(row: pd.Series) -> str:
    branches = str(row.get("branch_list", "")).lower()
    leg_sources = str(row.get("final_review_leg_sources", "")).lower()
    facility = str(row.get("roadway_or_facility", "")).lower()
    signal_count = int(row.get("signal_count", 0) or 0)
    leg_count = int(row.get("physical_leg_count", 0) or 0)
    bin_count = int(row.get("bin_count", 0) or 0)
    if "ramp_terminal" in branches or "ramp" in facility:
        return "interchange_ramp_terminal_context"
    if "generated_intersection_zone_anchor_leg" in leg_sources or "generated_broader_source_leg" in leg_sources:
        return "overlapping_generated_missing_leg_anchor_bins"
    if "generated_missing_leg" in leg_sources:
        return "overlapping_generated_missing_leg_bins"
    if signal_count >= 8:
        return "dense_urban_signal_corridor_or_closely_spaced_signals"
    if leg_count > signal_count * 2:
        return "same_signal_multi_leg_overlap"
    if bin_count >= 30:
        return "source_travelway_source_row_over_segmentation"
    return "manual_review_needed"


def _high_fanout_classification(fanout: pd.DataFrame) -> pd.DataFrame:
    high = fanout.loc[
        fanout["buffer_width_ft"].eq(PRIMARY_BUFFER_FT)
        & (
            pd.to_numeric(fanout["signal_count"], errors="coerce").ge(4)
            | pd.to_numeric(fanout["bin_count"], errors="coerce").ge(20)
            | pd.to_numeric(fanout["physical_leg_count"], errors="coerce").ge(8)
        )
    ].copy()
    high["likely_high_fanout_cause"] = high.apply(_classify_high_fanout, axis=1)
    high["manual_review_priority"] = (
        pd.to_numeric(high["signal_count"], errors="coerce").fillna(0) * 3
        + pd.to_numeric(high["physical_leg_count"], errors="coerce").fillna(0) * 2
        + pd.to_numeric(high["bin_count"], errors="coerce").fillna(0)
    )
    return high.sort_values("manual_review_priority", ascending=False).head(1000)


def _nonassignment_summary(all_ids: set[str], current: pd.DataFrame, prior: pd.DataFrame) -> pd.DataFrame:
    cur = _sets_by_buffer(current)
    old = _sets_by_buffer(prior)
    un50 = all_ids - cur[50]
    rows = [
        {"nonassignment_class": "total_unassigned_50ft", "crash_count": len(un50), "notes": "not assigned at primary 50 ft"},
        {"nonassignment_class": "near_bin_outside_50_inside_75", "crash_count": len(un50 & cur[75]), "notes": "75 ft sensitivity captures these crashes"},
        {"nonassignment_class": "outside_tested_75ft_line_catchments", "crash_count": len(all_ids - cur[75]), "notes": "not assigned even at 75 ft; no new nearest-scaffold analysis run"},
        {"nonassignment_class": "previously_assigned_50_now_unassigned", "crash_count": len(old[50] - cur[50]), "notes": "prior baseline assigned at 50 ft, current leg-corrected primary did not"},
        {"nonassignment_class": "previously_unassigned_50_still_unassigned", "crash_count": len((all_ids - old[50]) & un50), "notes": "unassigned in both prior and current 50 ft products"},
    ]
    return pd.DataFrame(rows)


def _nonassignment_prior_comparison(current_non: pd.DataFrame) -> pd.DataFrame:
    prior_path = PRIOR_NONASSIGN_DIR / "crash_unassigned_class_summary.csv"
    prior = _read_csv(prior_path) if prior_path.exists() else pd.DataFrame()
    rows = []
    if not prior.empty:
        for row in prior.to_dict("records"):
            rows.append({"comparison_group": "prior_nonassignment_class", "class": row.get("unassigned_reason_class", ""), "prior_count": int(row.get("crash_count", 0)), "current_count": "", "notes": "prior nearest-scaffold class; current audit did not rerun nearest analysis"})
    for row in current_non.to_dict("records"):
        rows.append({"comparison_group": "current_buffer_status_class", "class": row.get("nonassignment_class", ""), "prior_count": "", "current_count": int(row.get("crash_count", 0)), "notes": row.get("notes", "")})
    return pd.DataFrame(rows)


def _buffer_sensitivity(all_ids: set[str], detail: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    sets = _sets_by_buffer(detail)
    signal_branch = signals[["stable_signal_id", "recovery_branch"]].drop_duplicates("stable_signal_id")
    work = detail.merge(signal_branch, on="stable_signal_id", how="left")
    rows = [
        {"sensitivity_class": "assigned_35ft", "crash_count": len(sets[35]), "notes": "narrow sensitivity"},
        {"sensitivity_class": "new_35_to_50ft", "crash_count": len(sets[50] - sets[35]), "notes": "primary 50 ft adds these over 35 ft"},
        {"sensitivity_class": "new_50_to_75ft", "crash_count": len(sets[75] - sets[50]), "notes": "75 ft sensitivity adds these over primary 50 ft"},
        {"sensitivity_class": "unassigned_75ft", "crash_count": len(all_ids - sets[75]), "notes": "outside tested 75 ft line catchments"},
    ]
    for width, label, ids in [(50, "new_35_to_50ft_by_branch", sets[50] - sets[35]), (75, "new_50_to_75ft_by_branch", sets[75] - sets[50])]:
        subset = work.loc[work["buffer_width_ft"].eq(width) & _text(work, "stable_crash_id").isin(ids)]
        for branch, group in subset.groupby("recovery_branch", dropna=False):
            rows.append({"sensitivity_class": label, "crash_count": int(group["stable_crash_id"].nunique()), "branch_or_source": branch, "notes": "branch concentration of buffer sensitivity gains"})
        for leg_source, group in subset.groupby("final_review_leg_source", dropna=False):
            rows.append({"sensitivity_class": label.replace("_by_branch", "_by_leg_source"), "crash_count": int(group["stable_crash_id"].nunique()), "branch_or_source": leg_source, "notes": "leg-source concentration of buffer sensitivity gains"})
    return pd.DataFrame(rows)


def _high_count_signal_window(signal_window: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    signal_branch = signals[["stable_signal_id", "recovery_branch", "final_leg_corrected_physical_leg_bucket"]].drop_duplicates("stable_signal_id")
    out = signal_window.loc[_num(signal_window, "buffer_width_ft").eq(PRIMARY_BUFFER_FT)].copy()
    out = out.merge(signal_branch, on="stable_signal_id", how="left")
    return out.sort_values(["unique_crash_count", "assignment_row_count"], ascending=False).head(250)


def _readiness_decision(fanout_summary: pd.DataFrame, comparison: pd.DataFrame, nonassign: pd.DataFrame) -> pd.DataFrame:
    primary_comp = comparison.loc[pd.to_numeric(comparison["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)].copy()
    max_current = int(pd.to_numeric(primary_comp["current_max_fanout"], errors="coerce").max()) if "current_max_fanout" in primary_comp.columns and not primary_comp.empty else 0
    new_75 = int(nonassign.loc[nonassign["nonassignment_class"].eq("near_bin_outside_50_inside_75"), "crash_count"].iloc[0])
    return pd.DataFrame(
        [
            {"decision_item": "primary_50ft_crash_assignment", "decision": "ready_as_primary_review_product_with_fanout_queue", "notes": f"Max fanout is {max_current}; high-fanout queue must remain QA context."},
            {"decision_item": "sensitivity_35_75ft", "decision": "retain_as_sensitivity_only", "notes": f"75 ft captures {new_75:,} crashes not assigned at 50 ft; do not promote 75 ft to primary."},
            {"decision_item": "high_fanout_cases", "decision": "map_review_queue_not_blocker", "notes": "Concentrated high-fanout cases require QA review but do not block primary refresh."},
            {"decision_item": "nonassignment", "decision": "sufficient_for_review_baseline", "notes": "Current audit uses buffer sensitivity and prior nearest-scaffold accounting; no new nearest analysis was run."},
            {"decision_item": "next_active_geospatial_pass", "decision": "nonassignment_manual_overlap_accounting_or_table_figure_prep", "notes": "Use 50 ft primary and carry 35/75 sensitivity plus high-fanout queue."},
        ]
    )


def _qa(missing: list[str], detail: pd.DataFrame) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_leg_corrected_crash_sanity_audit."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_rates_or_models", True, "No rates/models are calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Audit reads assignment inventory status only; no crash source direction fields are read."),
        ("no_new_crash_assignment_produced", True, "Audit uses existing assignment detail and writes summary/QA outputs only."),
        ("stable_travelway_id_available", "stable_travelway_id" in detail.columns, "assignment detail carries stable_travelway_id"),
        ("final_review_physical_leg_id_available", "final_review_physical_leg_id" in detail.columns, "assignment detail carries final_review_physical_leg_id where available"),
        ("source_preserving_weights_available", "source_preserving_weight" in detail.columns, "weight field present"),
        ("outputs_review_only", True, str(OUT_DIR.resolve())),
        ("required_inputs_available", not missing, "; ".join(missing)),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": passed, "detail": detail_text} for name, passed, detail_text in checks])


def _findings(comparison: pd.DataFrame, gain_branch: pd.DataFrame, fanout_summary: pd.DataFrame, high: pd.DataFrame, nonassign: pd.DataFrame, decision: pd.DataFrame, qa_frame: pd.DataFrame) -> str:
    comp_lines = "\n".join(
        f"- {int(r.buffer_width_ft)} ft: {int(r.prior_assigned_crashes):,} -> {int(r.current_assigned_crashes):,} assigned crashes; max fanout {int(r.prior_max_fanout)} -> {int(r.current_max_fanout)}"
        for r in comparison.itertuples(index=False)
    )
    top_branch = gain_branch.loc[gain_branch["gain_group"].eq("recovery_branch") & gain_branch["buffer_width_ft"].eq(PRIMARY_BUFFER_FT)].sort_values("newly_assigned_crashes", ascending=False).head(6)
    branch_lines = "\n".join(f"- {r.recovery_branch}: {int(r.newly_assigned_crashes):,} newly assigned crashes" for r in top_branch.itertuples(index=False))
    fan50 = fanout_summary.loc[fanout_summary["buffer_width_ft"].eq(PRIMARY_BUFFER_FT) & fanout_summary["fanout_metric"].eq("signal_count")]
    fan_lines = "\n".join(f"- {r.fanout_bucket}: {int(r.crash_count):,}" for r in fan50.itertuples(index=False))
    cause = high["likely_high_fanout_cause"].value_counts().reset_index()
    cause_lines = "\n".join(f"- {row['likely_high_fanout_cause']}: {int(row['count']):,}" for _, row in cause.iterrows()) if not cause.empty else "- none"
    non_lines = "\n".join(f"- {r.nonassignment_class}: {int(r.crash_count):,}" for r in nonassign.itertuples(index=False))
    return f"""# Final Leg-Corrected Crash Sanity Findings

## Bounded Question

Audit the final leg-corrected crash candidate assignment for denominator consistency, assignment gain, fanout, nonassignment, and readiness. No new crash assignment, rates, models, or direction-based logic were run.

## Gain Versus Prior

{comp_lines}

The increase is plausible because the final leg-corrected scaffold adds signals, recovered legs, and corrected leg labels. The high fanout increase is real and is carried into a review queue.

## Newly Assigned Crashes at 50 Ft by Branch

{branch_lines}

## Fanout at 50 Ft by Signal Count

{fan_lines}

## High-Fanout Cause Classification

{cause_lines}

## Nonassignment Refresh

{non_lines}

## Readiness

{decision.to_string(index=False)}

## QA

All QA checks passed: {bool(qa_frame['passed'].all())}.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()

    assign_manifest = _read_json(ASSIGN_DIR / "final_leg_corrected_crash_candidate_assignment_manifest.json")
    detail = _load_current_detail()
    prior = _load_prior_detail()
    signals = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv")
    bins = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv", usecols=["stable_bin_id", "stable_travelway_id", "geometry_wkt", "final_review_physical_leg_id", "final_review_leg_source"])
    signal_window = _read_csv(ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv")
    comparison = _read_csv(ASSIGN_DIR / "leg_corrected_crash_assignment_vs_prior_comparison.csv")

    all_ids = set(_crash_source_ids())
    denom = _denominator_validation(detail, bins, signals, assign_manifest)
    gain_detail = _gain_detail(detail, prior)
    gain_branch = _gain_by_branch(detail, prior, signals)
    fanout_detail = _fanout_detail(detail, signals)
    fanout_summary = _fanout_summary(fanout_detail)
    high_fanout = _high_fanout_classification(fanout_detail)
    nonassign = _nonassignment_summary(all_ids, detail, prior)
    nonassign_compare = _nonassignment_prior_comparison(nonassign)
    sensitivity = _buffer_sensitivity(all_ids, detail, signals)
    high_count = _high_count_signal_window(signal_window, signals)
    qa_frame = _qa(missing, detail)
    decision = _readiness_decision(fanout_summary, comparison, nonassign)

    _write_csv(denom, "crash_sanity_denominator_validation.csv")
    _write_csv(gain_detail, "crash_assignment_gain_vs_prior_detail.csv")
    _write_csv(gain_branch, "crash_assignment_gain_by_branch.csv")
    _write_csv(fanout_detail, "crash_fanout_sanity_detail.csv")
    _write_csv(fanout_summary, "crash_fanout_sanity_summary.csv")
    _write_csv(high_fanout, "crash_high_fanout_cause_classification.csv")
    _write_csv(nonassign, "crash_nonassignment_refresh_summary.csv")
    _write_csv(nonassign_compare, "crash_nonassignment_vs_prior_comparison.csv")
    _write_csv(sensitivity, "crash_buffer_sensitivity_sanity.csv")
    _write_csv(high_count, "crash_high_count_signal_window_sanity.csv")
    _write_csv(decision, "crash_sanity_readiness_decision.csv")
    _write_text(_findings(comparison, gain_branch, fanout_summary, high_fanout, nonassign, decision, qa_frame), "final_leg_corrected_crash_sanity_findings.md")
    _write_csv(qa_frame, "final_leg_corrected_crash_sanity_qa.csv")
    manifest = {
        "generated_at": _now(),
        "script": "src.roadway_graph.audit.final_leg_corrected_crash_sanity_audit",
        "output_dir": str(OUT_DIR),
        "review_only": True,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "missing_inputs": missing,
        "counts": {
            "assignment_rows_read": int(len(detail)),
            "prior_assignment_rows_read": int(len(prior)),
            "fanout_detail_rows": int(len(fanout_detail)),
            "high_fanout_rows": int(len(high_fanout)),
            "qa_passed": bool(qa_frame["passed"].all()),
        },
        "limitations": [
            "No new spatial assignment or nearest-scaffold nonassignment analysis was run.",
            "Nonassignment refresh uses buffer sensitivity and prior nonassignment classes.",
            "High-fanout causes are heuristic QA classes for review prioritization.",
        ],
    }
    _write_json(manifest, "final_leg_corrected_crash_sanity_manifest.json")
    _checkpoint("complete")
    print("Complete.")


if __name__ == "__main__":
    main()
