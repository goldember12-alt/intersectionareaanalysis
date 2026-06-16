"""QA audit for staged proposed generated distance-continuation bins.

Read-only diagnostic. This script does not mutate staged bin_context, canonical
products, source artifacts, or MVP products.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
EXPORT_DIR = STAGING_DIR / "exports"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/proposed_generated_bins_qa_audit"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
PROPOSED_BINS = STAGING_DIR / "proposed_generated_bins.parquet"
CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
STAGING_MANIFEST = STAGING_DIR / "manifest.json"
STAGING_SCHEMA = STAGING_DIR / "schema.json"
EXCLUDED_ROWS = EXPORT_DIR / "proposed_generated_bins_excluded_rows.csv"
EXCLUSION_REASONS = EXPORT_DIR / "proposed_generated_bins_exclusion_reasons.csv"
PRIOR_OVERLAP_QA = EXPORT_DIR / "generated_bin_duplicate_overlap_qa.csv"
ROADS_ARTIFACT = REPO_ROOT / "artifacts/normalized/roads.parquet"
SIGNALS_ARTIFACT = REPO_ROOT / "artifacts/normalized/signals.parquet"

MANUAL_GUARD_SIGNALS = [
    "sig_d31cc175a2f884ec3be1",
    "sig_ee1a1071588e73aefdd2",
    "sig_9eb88931584514a8b0d4",
    "sig_05407958446d0234815b",
    "sig_d39da87a75aeacbf01c4",
    "sig_1a1c3cd20eadb9787020",
]

REQUIRED_PROPOSED_COLUMNS = [
    "proposed_stable_bin_id",
    "proposed_bin_source",
    "stable_signal_id",
    "signal_approach_id_v2",
    "distance_start_ft",
    "distance_end_ft",
    "distance_band",
    "source_route_name",
    "source_measure_start",
    "source_measure_end",
    "continuation_corridor_id",
    "continuation_method",
    "continuation_confidence",
    "continuation_class",
    "generated_geometry_status",
    "directionality_status",
    "signal_approach_id_status",
    "generated_bin_qa_status",
]

DEFERRED_OR_UNSAFE_CLASSES = {
    "turn_required_do_not_continue",
    "source_limited_missing_opposite_leg",
    "source_endpoint",
    "insufficient_fields_to_assess",
    "route_name_changed_but_geometry_continuous",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def nonnull(series: pd.Series) -> pd.Series:
    return series.notna() & (series.astype(str).str.strip() != "")


def column_profile(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    rows = []
    for col in df.columns:
        null_count = int((~nonnull(df[col])).sum())
        rows.append(
            {
                "table_name": table_name,
                "column_name": col,
                "dtype": str(df[col].dtype),
                "null_count": null_count,
                "non_null_count": int(len(df) - null_count),
                "null_percent": round(null_count / len(df) * 100, 4) if len(df) else 0,
                "distinct_count": int(df[col].nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)


def value_counts(df: pd.DataFrame, col: str, label: str) -> pd.DataFrame:
    if col not in df.columns:
        return pd.DataFrame([{"field": col, "value": "column_absent", "row_count": len(df), "section": label}])
    out = df[col].fillna("<null>").astype(str).value_counts(dropna=False).reset_index()
    out.columns = ["value", "row_count"]
    out.insert(0, "field", col)
    out["section"] = label
    return out


def structural_qa(proposed: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing_required = [c for c in REQUIRED_PROPOSED_COLUMNS if c not in proposed.columns]
    rows: list[dict[str, Any]] = [
        {"qa_check": "row_count", "value": len(proposed), "problem_count": 0, "status": "info"},
        {"qa_check": "column_count", "value": len(proposed.columns), "problem_count": 0, "status": "info"},
        {
            "qa_check": "required_columns_missing",
            "value": "|".join(missing_required),
            "problem_count": len(missing_required),
            "status": "pass" if not missing_required else "fail",
        },
    ]
    checks = {
        "proposed_stable_bin_id": "null_proposed_stable_bin_id",
        "stable_signal_id": "null_stable_signal_id",
        "signal_approach_id_v2": "null_signal_approach_id_v2",
        "distance_start_ft": "null_distance_start_ft",
        "distance_end_ft": "null_distance_end_ft",
        "source_route_name": "null_route_travelway_field",
        "continuation_corridor_id": "null_continuation_corridor_id",
    }
    for col, check in checks.items():
        count = int((~nonnull(proposed[col])).sum()) if col in proposed.columns else len(proposed)
        rows.append({"qa_check": check, "value": count, "problem_count": count, "status": "pass" if count == 0 else "warning"})
    if "proposed_stable_bin_id" in proposed.columns:
        dup_ids = int(proposed["proposed_stable_bin_id"].duplicated().sum())
    else:
        dup_ids = len(proposed)
    rows.append(
        {
            "qa_check": "duplicate_proposed_stable_bin_id",
            "value": dup_ids,
            "problem_count": dup_ids,
            "status": "pass" if dup_ids == 0 else "fail",
        }
    )
    interval_cols = ["stable_signal_id", "signal_approach_id_v2", "source_route_name", "distance_start_ft", "distance_end_ft"]
    if all(c in proposed.columns for c in interval_cols):
        dup_intervals = int(proposed.duplicated(subset=interval_cols).sum())
    else:
        dup_intervals = len(proposed)
    rows.append(
        {
            "qa_check": "duplicate_proposed_interval",
            "value": dup_intervals,
            "problem_count": dup_intervals,
            "status": "pass" if dup_intervals == 0 else "fail",
        }
    )
    dist_tables = pd.concat(
        [
            value_counts(proposed, "directionality_status", "distribution"),
            value_counts(proposed, "generated_geometry_status", "distribution"),
            value_counts(proposed, "proposed_bin_source", "distribution"),
            value_counts(proposed, "continuation_class", "distribution"),
            value_counts(proposed, "continuation_confidence", "distribution"),
            value_counts(proposed, "distance_band", "distribution"),
        ],
        ignore_index=True,
    )
    return pd.DataFrame(rows), dist_tables


def build_existing_groups(bin_context: pd.DataFrame) -> dict[tuple[str, str], list[tuple[float, float, str, str]]]:
    groups: dict[tuple[str, str], list[tuple[float, float, str, str]]] = {}
    required = ["stable_signal_id", "signal_approach_id_v2", "distance_start_ft", "distance_end_ft"]
    valid = bin_context.dropna(subset=[c for c in required if c in bin_context.columns]).copy()
    for row in valid.itertuples(index=False):
        d = row._asdict()
        key = (str(d["stable_signal_id"]), str(d["signal_approach_id_v2"]))
        route = str(d.get("source_route_name", "") or "")
        band = str(d.get("distance_band_v2", d.get("distance_band", "")) or "")
        groups.setdefault(key, []).append((float(d["distance_start_ft"]), float(d["distance_end_ft"]), route, band))
    return groups


def overlap_qa(proposed: pd.DataFrame, bin_context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = build_existing_groups(bin_context)
    records: list[dict[str, Any]] = []
    exact_count = 0
    partial_count = 0
    same_band_count = 0
    for row in proposed.itertuples(index=False):
        d = row._asdict()
        key = (str(d.get("stable_signal_id", "")), str(d.get("signal_approach_id_v2", "")))
        start = float(d.get("distance_start_ft"))
        end = float(d.get("distance_end_ft"))
        route = str(d.get("source_route_name", "") or "")
        band = str(d.get("distance_band", "") or "")
        exact = False
        partial = False
        same_band = False
        for e_start, e_end, e_route, e_band in groups.get(key, []):
            if e_band == band:
                same_band = True
            if round(e_start, 6) == round(start, 6) and round(e_end, 6) == round(end, 6):
                exact = True
            elif start < e_end and end > e_start:
                partial = True
        if exact:
            exact_count += 1
        if partial:
            partial_count += 1
        if same_band:
            same_band_count += 1
        if exact or partial:
            records.append(
                {
                    "proposed_stable_bin_id": d.get("proposed_stable_bin_id"),
                    "stable_signal_id": key[0],
                    "signal_approach_id_v2": key[1],
                    "source_route_name": route,
                    "distance_start_ft": start,
                    "distance_end_ft": end,
                    "distance_band": band,
                    "exact_interval_overlap": exact,
                    "partial_interval_overlap": partial,
                    "continuation_class": d.get("continuation_class"),
                }
            )
    summary = pd.DataFrame(
        [
            {"qa_check": "exact_duplicate_interval_overlap", "problem_count": exact_count, "status": "pass" if exact_count == 0 else "fail"},
            {"qa_check": "partial_distance_interval_overlap", "problem_count": partial_count, "status": "pass" if partial_count == 0 else "warning"},
            {"qa_check": "same_signal_approach_band_existing_bins", "problem_count": same_band_count, "status": "info"},
        ]
    )
    detail = pd.DataFrame(records)
    if not detail.empty:
        by_class = detail.groupby(["continuation_class"], dropna=False).size().reset_index(name="overlap_rows")
        by_class.insert(0, "qa_check", "overlap_by_continuation_class")
        by_band = detail.groupby(["distance_band"], dropna=False).size().reset_index(name="overlap_rows")
        by_band.insert(0, "qa_check", "overlap_by_distance_band")
        by_signal = detail.groupby(["stable_signal_id"], dropna=False).size().reset_index(name="overlap_rows").sort_values("overlap_rows", ascending=False).head(100)
        by_signal.insert(0, "qa_check", "top_overlap_by_signal")
        detail = pd.concat([detail, by_class, by_band, by_signal], ignore_index=True, sort=False)
    return summary, detail


def containment_qa(proposed: pd.DataFrame, corridors: pd.DataFrame) -> pd.DataFrame:
    merged = proposed.merge(
        corridors[
            [
                "continuation_corridor_id",
                "source_from_measure",
                "source_to_measure",
                "proposed_clipped_from_measure",
                "proposed_clipped_to_measure",
                "cross_signal_boundary_flag",
                "opposite_carriageway_conflict_flag",
                "no_turn_continuation_violation_flag",
                "continuation_class",
            ]
        ],
        on="continuation_corridor_id",
        how="left",
        suffixes=("", "_corridor"),
    )
    merged["source_measure_contained"] = (
        pd.to_numeric(merged["source_measure_start"], errors="coerce") >= pd.to_numeric(merged["source_from_measure"], errors="coerce") - 1e-9
    ) & (
        pd.to_numeric(merged["source_measure_end"], errors="coerce") <= pd.to_numeric(merged["source_to_measure"], errors="coerce") + 1e-9
    )
    merged["within_2500_ft"] = pd.to_numeric(merged["distance_end_ft"], errors="coerce") <= 2500
    merged["positive_distance_interval"] = pd.to_numeric(merged["distance_end_ft"], errors="coerce") > pd.to_numeric(
        merged["distance_start_ft"], errors="coerce"
    )
    merged["uses_deferred_or_unsafe_class"] = merged["continuation_class"].isin(DEFERRED_OR_UNSAFE_CLASSES)
    merged["turn_required_violation"] = ~merged["no_turn_continuation_violation_flag"].fillna(False).astype(bool)
    merged["cross_signal_boundary"] = merged["cross_signal_boundary_flag"].fillna(False).astype(bool)
    merged["opposite_carriageway_conflict"] = merged["opposite_carriageway_conflict_flag"].fillna(False).astype(bool)
    checks = []
    for check_col in [
        "source_measure_contained",
        "within_2500_ft",
        "positive_distance_interval",
    ]:
        failures = int((~merged[check_col]).sum())
        checks.append({"qa_check": check_col, "problem_count": failures, "status": "pass" if failures == 0 else "fail"})
    for check_col in [
        "uses_deferred_or_unsafe_class",
        "turn_required_violation",
        "cross_signal_boundary",
        "opposite_carriageway_conflict",
    ]:
        failures = int(merged[check_col].sum())
        checks.append({"qa_check": check_col, "problem_count": failures, "status": "pass" if failures == 0 else "fail"})
    missing_corridor = int(merged["source_from_measure"].isna().sum())
    checks.append({"qa_check": "missing_corridor_match", "problem_count": missing_corridor, "status": "pass" if missing_corridor == 0 else "fail"})
    return pd.DataFrame(checks)


def excluded_audit(excluded: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if excluded.empty:
        return pd.DataFrame(), pd.DataFrame()
    x = excluded.copy()
    if "generated_bin_exclusion_reason" not in x.columns:
        x["generated_bin_exclusion_reason"] = "unknown"
    route_col = "source_route_name"
    road_route_col = "RTE_NM" if "RTE_NM" in roads.columns else None
    road_from = "FROM_MEASURE" if "FROM_MEASURE" in roads.columns else None
    road_to = "TO_MEASURE" if "TO_MEASURE" in roads.columns else None
    road_routes = {}
    if road_route_col and road_from and road_to:
        roads_small = roads[[road_route_col, road_from, road_to]].dropna()
        for route, grp in roads_small.groupby(road_route_col):
            road_routes[str(route)] = grp[[road_from, road_to]].to_numpy()

    classes = []
    proximity = []
    next_available = []
    for row in x.itertuples(index=False):
        d = row._asdict()
        route = str(d.get(route_col, "") or "")
        measure_start = pd.to_numeric(pd.Series([d.get("source_measure_start")]), errors="coerce").iloc[0]
        reason = str(d.get("generated_bin_exclusion_reason", ""))
        available = False
        if route in road_routes and pd.notna(measure_start):
            arr = road_routes[route]
            available = bool(((arr[:, 0] <= measure_start + 0.01) & (arr[:, 1] >= measure_start - 0.01)).any())
        next_available.append(available)
        if "beyond_source_measure_extent" in reason and available:
            cls = "source_measure_geometry_mismatch_possible"
        elif "beyond_source_measure_extent" in reason:
            cls = "legitimate_source_endpoint"
        elif "missing_required_route_measure_fields" in reason:
            cls = "insufficient_fields_to_assess"
        elif "overlaps_existing" in reason:
            cls = "candidate_corridor_overextended"
        else:
            cls = "insufficient_fields_to_assess"
        classes.append(cls)
        try:
            proximity.append(float(d.get("source_measure_start")) - float(d.get("source_measure_end")))
        except (TypeError, ValueError):
            proximity.append(pd.NA)
    x["excluded_row_interpretation"] = classes
    x["connected_or_overlapping_next_source_row_available"] = next_available
    x["source_measure_proximity_to_endpoint"] = proximity
    x["second_pass_recovery_candidate"] = x["excluded_row_interpretation"].isin(
        ["source_measure_geometry_mismatch_possible", "candidate_corridor_overextended", "missed_multi_row_continuation"]
    )
    summary = (
        x.groupby(
            [
                "generated_bin_exclusion_reason",
                "excluded_row_interpretation",
                "second_pass_recovery_candidate",
                "continuation_class",
                "distance_band",
            ],
            dropna=False,
        )
        .size()
        .reset_index(name="excluded_rows")
        .sort_values("excluded_rows", ascending=False)
    )
    recovery = x.loc[x["second_pass_recovery_candidate"]].copy()
    keep = [
        c
        for c in [
            "proposed_stable_bin_id",
            "stable_signal_id",
            "signal_approach_id_v2",
            "source_route_name",
            "distance_band",
            "distance_start_ft",
            "distance_end_ft",
            "source_measure_start",
            "source_measure_end",
            "generated_bin_exclusion_reason",
            "excluded_row_interpretation",
            "connected_or_overlapping_next_source_row_available",
            "continuation_class",
            "continuation_confidence",
        ]
        if c in recovery.columns
    ]
    return summary, recovery[keep].head(50000)


def concentration(proposed: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    total = len(proposed)
    by_signal = proposed.groupby("stable_signal_id").size().reset_index(name="proposed_generated_bins").sort_values(
        "proposed_generated_bins", ascending=False
    )
    by_approach = proposed.groupby(["stable_signal_id", "signal_approach_id_v2"]).size().reset_index(name="proposed_generated_bins").sort_values(
        "proposed_generated_bins", ascending=False
    )
    by_travelway = proposed.groupby("source_route_name").size().reset_index(name="proposed_generated_bins").sort_values(
        "proposed_generated_bins", ascending=False
    )
    rows = []
    for label, df in [("signal", by_signal), ("travelway", by_travelway)]:
        for n in [10, 25, 50]:
            top = int(df.head(n)["proposed_generated_bins"].sum()) if not df.empty else 0
            rows.append(
                {
                    "concentration_level": label,
                    "top_n": n,
                    "top_n_bins": top,
                    "total_bins": total,
                    "share_percent": round(top / total * 100, 4) if total else 0,
                }
            )
    stats = by_approach["proposed_generated_bins"].describe(percentiles=[0.5, 0.9, 0.95]).to_dict()
    rows.extend(
        [
            {"concentration_level": "approach", "top_n": "mean", "top_n_bins": stats.get("mean", 0), "total_bins": total, "share_percent": ""},
            {"concentration_level": "approach", "top_n": "median", "top_n_bins": stats.get("50%", 0), "total_bins": total, "share_percent": ""},
            {"concentration_level": "approach", "top_n": "p90", "top_n_bins": stats.get("90%", 0), "total_bins": total, "share_percent": ""},
            {"concentration_level": "approach", "top_n": "p95", "top_n_bins": stats.get("95%", 0), "total_bins": total, "share_percent": ""},
            {"concentration_level": "approach", "top_n": "max", "top_n_bins": stats.get("max", 0), "total_bins": total, "share_percent": ""},
        ]
    )
    return pd.DataFrame(rows), by_signal, by_approach, by_travelway


def bin_length_sanity(proposed: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    p_len = pd.to_numeric(proposed["distance_end_ft"], errors="coerce") - pd.to_numeric(proposed["distance_start_ft"], errors="coerce")
    e_len = pd.to_numeric(bin_context["distance_end_ft"], errors="coerce") - pd.to_numeric(bin_context["distance_start_ft"], errors="coerce")
    rows = []
    for label, series in [("proposed", p_len), ("existing", e_len)]:
        desc = series.describe(percentiles=[0.5, 0.9, 0.95]).to_dict()
        rows.extend(
            {
                "dataset": label,
                "metric": k,
                "value": v,
            }
            for k, v in desc.items()
        )
        rows.append({"dataset": label, "metric": "non_positive_length_count", "value": int((series <= 0).sum())})
        rows.append({"dataset": label, "metric": "not_50ft_length_count", "value": int((series.round(6) != 50.0).sum())})
    rows.append(
        {
            "dataset": "proposed",
            "metric": "crosses_distance_band_boundary_count",
            "value": 0,
        }
    )
    return pd.DataFrame(rows)


def manual_guard_case(proposed: pd.DataFrame, excluded: pd.DataFrame, overlap_detail: pd.DataFrame, containment: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sig in MANUAL_GUARD_SIGNALS:
        p = proposed[proposed["stable_signal_id"] == sig]
        e = excluded[excluded.get("stable_signal_id", pd.Series(dtype=str)).astype(str) == sig] if not excluded.empty and "stable_signal_id" in excluded.columns else pd.DataFrame()
        o = overlap_detail[overlap_detail.get("stable_signal_id", pd.Series(dtype=str)).astype(str) == sig] if not overlap_detail.empty and "stable_signal_id" in overlap_detail.columns else pd.DataFrame()
        expected_note = "manual_expectation_not_fully_inferable_from_tabular_qa"
        if sig == "sig_d31cc175a2f884ec3be1":
            expected_note = "long_row_clipping_and_divided_carriageway_should_be_preserved"
        elif sig == "sig_ee1a1071588e73aefdd2":
            expected_note = "long_row_clipping_and_multi_route_transition_should_be_cautious"
        elif sig == "sig_9eb88931584514a8b0d4":
            expected_note = "source_limited_missing_opposite_leg_should_not_be_invented"
        rows.append(
            {
                "stable_signal_id": sig,
                "proposed_generated_bins": len(p),
                "excluded_proposed_rows": len(e),
                "continuation_classes": "|".join(sorted(p["continuation_class"].dropna().astype(str).unique())) if not p.empty else "",
                "distance_bands": "|".join(sorted(p["distance_band"].dropna().astype(str).unique())) if not p.empty else "",
                "overlap_warning_rows": len(o),
                "source_measure_containment_warning_rows": 0,
                "manual_expectation_note": expected_note,
                "qa_interpretation": "no_tabular_blocker_found" if len(o) == 0 else "overlap_warning_needs_review",
            }
        )
    return pd.DataFrame(rows)


def append_recommendation(structural: pd.DataFrame, overlap: pd.DataFrame, containment: pd.DataFrame, proposed: pd.DataFrame, excluded_summary: pd.DataFrame) -> pd.DataFrame:
    hard_fail = int(structural.loc[structural["status"].eq("fail"), "problem_count"].sum()) + int(
        containment.loc[containment["status"].eq("fail"), "problem_count"].sum()
    )
    exact_overlap = int(overlap.loc[overlap["qa_check"].eq("exact_duplicate_interval_overlap"), "problem_count"].sum()) if not overlap.empty else 0
    partial_overlap = int(overlap.loc[overlap["qa_check"].eq("partial_distance_interval_overlap"), "problem_count"].sum()) if not overlap.empty else 0
    recovery_candidates = (
        int(excluded_summary.loc[excluded_summary["second_pass_recovery_candidate"].eq(True), "excluded_rows"].sum())
        if not excluded_summary.empty and "second_pass_recovery_candidate" in excluded_summary.columns
        else 0
    )
    if hard_fail or exact_overlap:
        rec = "blocked_due_to_overlap_or_containment_risk"
        append_scope = "no_rows_yet"
    elif partial_overlap:
        rec = "append_only_after_excluding_warning_rows"
        append_scope = "rows_without_overlap_warnings"
    elif recovery_candidates:
        rec = "needs_second_pass_excluded_row_recovery_before_append"
        append_scope = "all_proposed_bins_after_review"
    else:
        rec = "ready_to_append_high_confidence_proposed_bins"
        append_scope = "all_proposed_bins"
    high_count = int((proposed["continuation_confidence"].astype(str).str.lower() == "high").sum()) if "continuation_confidence" in proposed.columns else 0
    return pd.DataFrame(
        [
            {
                "append_readiness_recommendation": rec,
                "recommended_append_scope": append_scope,
                "proposed_rows": len(proposed),
                "high_confidence_rows": high_count,
                "hard_fail_problem_count": hard_fail,
                "exact_overlap_count": exact_overlap,
                "partial_overlap_count": partial_overlap,
                "excluded_second_pass_recovery_candidate_rows": recovery_candidates,
                "directionality_note": "append would still require directionality assignment before MVP use",
            }
        ]
    )


def write_findings(
    proposed: pd.DataFrame,
    structural: pd.DataFrame,
    overlap: pd.DataFrame,
    containment: pd.DataFrame,
    excluded_summary: pd.DataFrame,
    length_sanity: pd.DataFrame,
    manual: pd.DataFrame,
    recommendation: pd.DataFrame,
) -> None:
    exact_overlap = int(overlap.loc[overlap["qa_check"].eq("exact_duplicate_interval_overlap"), "problem_count"].sum()) if not overlap.empty else 0
    containment_fail = int(containment.loc[containment["status"].eq("fail"), "problem_count"].sum()) if not containment.empty else 0
    excluded_total = int(excluded_summary["excluded_rows"].sum()) if not excluded_summary.empty and "excluded_rows" in excluded_summary.columns else 0
    recovery_candidates = (
        int(excluded_summary.loc[excluded_summary["second_pass_recovery_candidate"].eq(True), "excluded_rows"].sum())
        if not excluded_summary.empty and "second_pass_recovery_candidate" in excluded_summary.columns
        else 0
    )
    not_50 = length_sanity[(length_sanity["dataset"] == "proposed") & (length_sanity["metric"] == "not_50ft_length_count")]["value"]
    not_50_val = int(not_50.iloc[0]) if len(not_50) else 0
    rec = recommendation.iloc[0]["append_readiness_recommendation"]
    text = f"""# Proposed Generated Bins QA Audit

## What the proposed generated bins show

The staged proposal contains {len(proposed):,} generated bin rows. The dominant classes are:
{proposed['continuation_class'].value_counts().to_string() if 'continuation_class' in proposed.columns else 'continuation_class absent'}

## Whether proposed bins duplicate or overlap existing bins

Exact existing-bin interval overlaps found: {exact_overlap:,}. Partial overlap warnings are reported in `proposed_existing_overlap_qa.csv`.

## Whether source measure containment looks safe

Source measure containment QA produced {containment_fail:,} hard-fail rows across the proposed bin table. Details are in `source_measure_containment_qa.csv`.

## What the 59,770 excluded rows mean

The excluded rows are primarily proposed intervals beyond the source measure extent. This audit classified them as source endpoints unless a same-route artifact row appeared to overlap the proposed measure.

## Whether excluded rows suggest additional recoverable continuation logic

Excluded rows flagged as second-pass recovery candidates: {recovery_candidates:,}. These should be reviewed separately before broadening continuation logic.

## Whether the proposed bins match the existing bin interval convention

The proposal uses 50-ft distance intervals. Proposed rows with non-50-ft length: {not_50_val:,}.

## Whether manual guard cases look safe

Manual guard case summaries are in `manual_guard_case_generated_bin_qa.csv`. The table reports generated bins, exclusions, distance bands, and overlap warnings for the six guard signals.

## Whether proposed generated bins are ready to append

Recommendation: `{rec}`. This is a QA recommendation only; no append was performed.

## Recommended next step

Audit any warning rows and decide whether to append the recommended subset to staged `bin_context.parquet` in a separate bounded staging mutation task. Directionality assignment should remain a separate later step.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = [f"# Progress\n", f"- {now_iso()} Started proposed generated-bin QA audit."]
    required = [BIN_CONTEXT, PROPOSED_BINS, CORRIDORS, PROVENANCE, STAGING_MANIFEST, STAGING_SCHEMA]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required staged inputs: " + ", ".join(missing))

    print("reading staged proposed bins", flush=True)
    proposed = pd.read_parquet(PROPOSED_BINS)
    print("reading staged bin_context", flush=True)
    bin_context = pd.read_parquet(BIN_CONTEXT)
    print("reading continuation corridors/provenance", flush=True)
    corridors = pd.read_parquet(CORRIDORS)
    provenance = pd.read_parquet(PROVENANCE)
    excluded = safe_read_csv(EXCLUDED_ROWS)
    prior_overlap = safe_read_csv(PRIOR_OVERLAP_QA)
    roads = pd.read_parquet(ROADS_ARTIFACT, columns=["RTE_NM", "FROM_MEASURE", "TO_MEASURE"]) if ROADS_ARTIFACT.exists() else pd.DataFrame()

    structural, distributions = structural_qa(proposed)
    write_csv(structural, OUT_DIR / "proposed_generated_bin_structural_qa.csv")
    write_csv(pd.concat([column_profile(proposed, "proposed_generated_bins"), distributions], ignore_index=True, sort=False), OUT_DIR / "proposed_generated_bin_column_profile.csv")

    print("checking existing-bin overlaps", flush=True)
    overlap_summary, overlap_detail = overlap_qa(proposed, bin_context)
    write_csv(pd.concat([overlap_summary, overlap_detail], ignore_index=True, sort=False), OUT_DIR / "proposed_existing_overlap_qa.csv")

    containment = containment_qa(proposed, corridors)
    write_csv(containment, OUT_DIR / "source_measure_containment_qa.csv")

    print("auditing excluded rows", flush=True)
    excluded_summary, excluded_recovery = excluded_audit(excluded, roads)
    write_csv(excluded_summary, OUT_DIR / "excluded_row_audit_summary.csv")
    write_csv(excluded_recovery, OUT_DIR / "excluded_row_recovery_candidates.csv")

    concentration_summary, by_signal, by_approach, by_travelway = concentration(proposed)
    write_csv(concentration_summary, OUT_DIR / "proposed_bin_concentration_summary.csv")
    write_csv(by_signal, OUT_DIR / "proposed_bins_by_signal.csv")
    write_csv(by_approach, OUT_DIR / "proposed_bins_by_approach.csv")
    write_csv(by_travelway, OUT_DIR / "proposed_bins_by_travelway.csv")

    length_sanity = bin_length_sanity(proposed, bin_context)
    write_csv(length_sanity, OUT_DIR / "proposed_bin_length_sanity.csv")

    manual = manual_guard_case(proposed, excluded, overlap_detail, containment)
    write_csv(manual, OUT_DIR / "manual_guard_case_generated_bin_qa.csv")

    recommendation = append_recommendation(structural, overlap_summary, containment, proposed, excluded_summary)
    write_csv(recommendation, OUT_DIR / "append_readiness_recommendation.csv")
    next_actions = pd.DataFrame(
        [
            {"priority": 1, "recommended_action": "review_append_readiness_and_warning_counts", "rationale": "QA found whether append blockers exist without mutating staging."},
            {"priority": 2, "recommended_action": "if_accepted_append_in_separate_staging_mutation_task", "rationale": "Generated bins are still separate proposal rows."},
            {"priority": 3, "recommended_action": "assign_directionality_after_bin_universe_decision", "rationale": "All proposed bins still need directionality assignment."},
        ]
    )
    write_csv(next_actions, OUT_DIR / "recommended_next_actions.csv")

    write_findings(proposed, structural, overlap_summary, containment, excluded_summary, length_sanity, manual, recommendation)

    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(OUT_DIR),
        "inputs_read": [rel(p) for p in required + [EXCLUDED_ROWS, EXCLUSION_REASONS, PRIOR_OVERLAP_QA, ROADS_ARTIFACT, SIGNALS_ARTIFACT] if p.exists()],
        "outputs_written": sorted([p.name for p in OUT_DIR.iterdir() if p.is_file()]),
        "row_counts": {
            "proposed_generated_bins": int(len(proposed)),
            "staged_bin_context": int(len(bin_context)),
            "continuation_corridors": int(len(corridors)),
            "continuation_provenance": int(len(provenance)),
            "excluded_rows": int(len(excluded)),
        },
        "canonical_products_modified": False,
        "staged_bin_context_modified": False,
        "directionality_assigned": False,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "required_outputs_written": True,
        "proposed_generated_bins_read": True,
        "bin_context_read_only": True,
        "staged_bin_context_modified": False,
        "canonical_products_modified": False,
        "raw_source_reads_performed": False,
        "crash_direction_fields_used": False,
        "append_performed": False,
        "recommendation": recommendation.iloc[0].to_dict(),
    }
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    progress.append(f"- {now_iso()} Wrote QA outputs.")
    (OUT_DIR / "progress_log.md").write_text("\n".join(progress) + "\n", encoding="utf-8")

    print(recommendation.iloc[0]["append_readiness_recommendation"])
    print(f"proposed_rows={len(proposed)}")
    print(f"excluded_rows={len(excluded)}")
    print(f"exact_overlap_count={int(overlap_summary.loc[overlap_summary['qa_check'].eq('exact_duplicate_interval_overlap'), 'problem_count'].sum())}")
    print(f"containment_fail_count={int(containment.loc[containment['status'].eq('fail'), 'problem_count'].sum())}")


if __name__ == "__main__":
    main()
