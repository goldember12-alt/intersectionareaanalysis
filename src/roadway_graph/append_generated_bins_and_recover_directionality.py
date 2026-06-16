"""Append proposed generated bins and recover deterministic directionality.

This is a bounded staged-cache mutation:
- canonical root products are not modified;
- proposed generated bins are appended to staged bin_context only after QA;
- directionality is recovered only when existing same-corridor evidence is
  deterministic;
- crash direction fields are not used.
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
REVIEW_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_directionality_recovery_audit"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
PROPOSED_BINS = STAGING_DIR / "proposed_generated_bins.parquet"
CONTINUATION_CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
MANIFEST = STAGING_DIR / "manifest.json"
SCHEMA = STAGING_DIR / "schema.json"
README = STAGING_DIR / "README.md"

EXPECTED_EXISTING_ROWS = 433_841
EXPECTED_PROPOSED_ROWS = 214_740
EXPECTED_EXPANDED_ROWS = 648_581
CONSERVATIVE_TARGET = 109_842
UPPER_BOUND_TARGET = 132_866


PROGRESS_LOG = REVIEW_DIR / "run_progress_log.txt"


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


def log_progress(message: str) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with PROGRESS_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {message}\n")


def nonnull(s: pd.Series) -> pd.Series:
    return s.notna() & (s.astype(str).str.strip() != "")


def side_label_series(df: pd.DataFrame) -> pd.Series:
    if "upstream_downstream_values" in df.columns:
        return df["upstream_downstream_values"]
    if "upstream_downstream" in df.columns:
        return df["upstream_downstream"]
    return pd.Series([pd.NA] * len(df), index=df.index)


def direction_method_series(df: pd.DataFrame) -> pd.Series:
    if "mvp_directionality_method_values" in df.columns:
        return df["mvp_directionality_method_values"]
    if "directionality_method" in df.columns:
        return df["directionality_method"]
    return pd.Series([pd.NA] * len(df), index=df.index)


def normalize_band(df: pd.DataFrame) -> pd.Series:
    if "distance_band_v2" in df.columns:
        return df["distance_band_v2"]
    if "distance_band" in df.columns:
        return df["distance_band"]
    return pd.Series([pd.NA] * len(df), index=df.index)


def validate_generated_bins(existing: pd.DataFrame, proposed: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(check: str, problem_count: int, status: str | None = None, detail: Any = "") -> None:
        rows.append(
            {
                "qa_check": check,
                "problem_count": int(problem_count),
                "status": status or ("pass" if problem_count == 0 else "fail"),
                "detail": detail,
            }
        )

    add("bin_context_exists", 0 if BIN_CONTEXT.exists() else 1)
    add("proposed_generated_bins_exists", 0 if PROPOSED_BINS.exists() else 1)
    add("row_count_before_append_expected_433841", 0 if len(existing) == EXPECTED_EXISTING_ROWS else 1, detail=len(existing))
    add("proposed_row_count_expected_214740", 0 if len(proposed) == EXPECTED_PROPOSED_ROWS else 1, detail=len(proposed))
    add("duplicate_proposed_stable_bin_id", proposed["proposed_stable_bin_id"].duplicated().sum() if "proposed_stable_bin_id" in proposed.columns else len(proposed))
    existing_ids = set(existing["stable_bin_id"].dropna().astype(str)) if "stable_bin_id" in existing.columns else set()
    proposed_ids = set(proposed["proposed_stable_bin_id"].dropna().astype(str)) if "proposed_stable_bin_id" in proposed.columns else set()
    add("proposed_stable_bin_id_already_exists", len(existing_ids.intersection(proposed_ids)))
    interval_cols = ["stable_signal_id", "signal_approach_id_v2", "source_route_name", "distance_start_ft", "distance_end_ft"]
    add(
        "duplicate_proposed_interval",
        proposed.duplicated(subset=interval_cols).sum() if all(c in proposed.columns for c in interval_cols) else len(proposed),
    )
    exact_existing = set()
    if all(c in existing.columns for c in ["stable_signal_id", "signal_approach_id_v2", "distance_start_ft", "distance_end_ft"]):
        valid = existing.dropna(subset=["stable_signal_id", "signal_approach_id_v2", "distance_start_ft", "distance_end_ft"])
        exact_existing = set(
            zip(
                valid["stable_signal_id"].astype(str),
                valid["signal_approach_id_v2"].astype(str),
                valid["distance_start_ft"].round(6),
                valid["distance_end_ft"].round(6),
            )
        )
    exact_prop = set(
        zip(
            proposed["stable_signal_id"].astype(str),
            proposed["signal_approach_id_v2"].astype(str),
            proposed["distance_start_ft"].round(6),
            proposed["distance_end_ft"].round(6),
        )
    )
    add("exact_overlap_with_existing_staged_bins", len(exact_existing.intersection(exact_prop)))
    # Existing and proposed intervals are 50-ft grid intervals. Exact overlap is
    # the operative hard gate; partial overlap would imply non-grid generated
    # intervals, which is checked via length and band gates.
    prop_len = pd.to_numeric(proposed["distance_end_ft"], errors="coerce") - pd.to_numeric(proposed["distance_start_ft"], errors="coerce")
    add("partial_overlap_risk_from_non_50ft_generated_intervals", int((prop_len.round(6) != 50.0).sum()))
    add("proposed_bins_beyond_2500ft", int((pd.to_numeric(proposed["distance_end_ft"], errors="coerce") > 2500).sum()))
    for col in ["stable_signal_id", "signal_approach_id_v2", "distance_start_ft", "distance_end_ft", "distance_band", "continuation_corridor_id"]:
        add(f"missing_{col}", int((~nonnull(proposed[col])).sum()) if col in proposed.columns else len(proposed))
    if "directionality_status" in proposed.columns:
        add(
            "proposed_rows_not_marked_needs_directionality_assignment",
            int((proposed["directionality_status"].astype(str) != "needs_directionality_assignment").sum()),
        )
    else:
        add("proposed_rows_not_marked_needs_directionality_assignment", len(proposed))
    for col in ["turn_continuation_violation", "cross_signal_boundary", "opposite_carriageway_conflict"]:
        if col in proposed.columns:
            add(f"flagged_{col}", int(proposed[col].fillna(False).astype(bool).sum()))
        else:
            add(f"flagged_{col}", 0, status="pass", detail="column_absent")
    return pd.DataFrame(rows)


def align_and_append(existing: pd.DataFrame, proposed: pd.DataFrame) -> pd.DataFrame:
    existing2 = existing.copy()
    proposed2 = proposed.copy()
    existing2["bin_row_origin"] = existing2.get("bin_row_origin", "existing_staged_bin")
    existing2["generated_bin_flag"] = False
    existing2["generated_bin_source"] = existing2.get("generated_bin_source", pd.NA)

    proposed2["stable_bin_id"] = proposed2["proposed_stable_bin_id"]
    proposed2["bin_row_origin"] = "generated_distance_continuation_bin"
    proposed2["generated_bin_flag"] = True
    proposed2["generated_bin_source"] = proposed2.get("proposed_bin_source", "distance_continuation_first_pass")
    proposed2["distance_band_v2"] = proposed2.get("distance_band_v2", proposed2.get("distance_band"))
    proposed2["upstream_downstream_values"] = pd.NA
    proposed2["mvp_directionality_method_values"] = pd.NA
    proposed2["directionality_coverage_status_values"] = "needs_directionality_assignment"
    proposed2["directionality_direct_or_synthetic_values"] = pd.NA
    proposed2["directionality_caveat_values"] = "generated bin requires directionality assignment"
    proposed2["directionality_row_count"] = 0
    proposed2["directionality_upstream_downstream_count"] = 0
    proposed2["directionality_coverage_preserved_flag"] = False
    proposed2["signal_approach_id_status"] = proposed2.get("signal_approach_id_status", "proposed_generated_distance_continuation")
    proposed2["signal_approach_id_method"] = proposed2.get("continuation_method", pd.NA)
    proposed2["signal_approach_id_evidence_fields"] = proposed2.get("continuation_corridor_id", pd.NA)
    proposed2["signal_approach_id_conflict_flag"] = False
    proposed2["signal_approach_id_refinement_pass"] = "generated_distance_continuation_append"
    proposed2["source_layer"] = "generated_distance_continuation"

    all_cols = list(dict.fromkeys(list(existing2.columns) + list(proposed2.columns)))
    expanded = pd.concat([existing2.reindex(columns=all_cols), proposed2.reindex(columns=all_cols)], ignore_index=True)
    return expanded


def unit_count(df: pd.DataFrame) -> int:
    side = side_label_series(df)
    valid = df[nonnull(df["stable_signal_id"]) & nonnull(df["signal_approach_id_v2"]) & nonnull(normalize_band(df)) & nonnull(side)].copy()
    if valid.empty:
        return 0
    valid["_distance_band_norm"] = normalize_band(valid)
    valid["_side"] = side.loc[valid.index].astype(str).str.split("|")
    ex = valid.explode("_side")
    ex = ex[nonnull(ex["_side"])]
    return int(ex[["stable_signal_id", "signal_approach_id_v2", "_distance_band_norm", "_side"]].drop_duplicates().shape[0])


def approach_band_count(df: pd.DataFrame) -> int:
    valid = df[nonnull(df["stable_signal_id"]) & nonnull(df["signal_approach_id_v2"]) & nonnull(normalize_band(df))].copy()
    valid["_distance_band_norm"] = normalize_band(valid)
    return int(valid[["stable_signal_id", "signal_approach_id_v2", "_distance_band_norm"]].drop_duplicates().shape[0])


def pre_recovery_summary(expanded: pd.DataFrame, existing_unit_count: int) -> pd.DataFrame:
    side = side_label_series(expanded)
    has_dir = nonnull(side)
    total = len(expanded)
    rows = [
        {"metric": "expanded_total_bins", "value": total},
        {"metric": "bins_with_directionality_before_recovery", "value": int(has_dir.sum())},
        {"metric": "bins_missing_directionality_before_recovery", "value": int((~has_dir).sum())},
        {"metric": "directionality_coverage_percent_before_recovery", "value": round(has_dir.sum() / total * 100, 4)},
        {"metric": "existing_bins_missing_directionality_before_recovery", "value": int(((expanded["bin_row_origin"] == "existing_staged_bin") & ~has_dir).sum())},
        {"metric": "generated_bins_missing_directionality_before_recovery", "value": int(((expanded["bin_row_origin"] == "generated_distance_continuation_bin") & ~has_dir).sum())},
        {"metric": "direction_ready_units_before_append", "value": existing_unit_count},
        {"metric": "direction_ready_units_after_append_before_recovery", "value": unit_count(expanded)},
        {"metric": "approach_band_support_units_after_append", "value": approach_band_count(expanded)},
    ]
    return pd.DataFrame(rows)


def build_inheritance_maps(expanded: pd.DataFrame) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    existing = expanded[(expanded["bin_row_origin"] == "existing_staged_bin") & nonnull(side_label_series(expanded))].copy()
    existing["_side"] = side_label_series(existing).astype(str)
    existing["_method"] = direction_method_series(existing).astype(str)
    same_route: dict[tuple[str, str, str], str] = {}
    same_approach: dict[tuple[str, str], str] = {}
    method_by_side: dict[tuple[str, str], str] = {}

    for keys, target in [
        (["stable_signal_id", "signal_approach_id_v2", "source_route_name"], same_route),
        (["stable_signal_id", "signal_approach_id_v2"], same_approach),
    ]:
        valid = existing.dropna(subset=[k for k in keys if k in existing.columns])
        for key, grp in valid.groupby(keys, dropna=False):
            if not isinstance(key, tuple):
                key = (key,)
            vals = sorted(v for v in grp["_side"].dropna().astype(str).unique() if v.strip())
            if len(vals) == 1:
                target[tuple(str(x) for x in key)] = vals[0]
                method_vals = sorted(v for v in grp["_method"].dropna().astype(str).unique() if v.strip() and v != "nan")
                method_by_side[(tuple(str(x) for x in key), vals[0])] = method_vals[0] if len(method_vals) == 1 else "inherited_existing_mixed_method"
    return same_route, same_approach, method_by_side


def recover_directionality(expanded: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = expanded.copy()
    original_side = side_label_series(df).copy()
    if "directionality_recovery_status" not in df.columns:
        df["directionality_recovery_status"] = pd.NA
    if "directionality_recovery_method" not in df.columns:
        df["directionality_recovery_method"] = pd.NA
    if "directionality_recovery_evidence_fields" not in df.columns:
        df["directionality_recovery_evidence_fields"] = pd.NA
    has_dir = nonnull(original_side)
    df.loc[has_dir, "directionality_recovery_status"] = "existing_valid"
    df.loc[has_dir, "directionality_recovery_method"] = "existing_preserved"
    df.loc[has_dir, "directionality_recovery_evidence_fields"] = "pre_existing_upstream_downstream_values"

    log_progress("Building deterministic directionality inheritance maps.")
    existing = df[(df["bin_row_origin"] == "existing_staged_bin") & nonnull(side_label_series(df))].copy()
    existing["_side"] = side_label_series(existing).astype(str)
    existing["_method"] = direction_method_series(existing).astype(str)
    route_map = (
        existing.groupby(["stable_signal_id", "signal_approach_id_v2", "source_route_name"], dropna=False)
        .agg(side_count=("_side", "nunique"), inherited_side=("_side", "first"), method_count=("_method", "nunique"), inherited_method=("_method", "first"))
        .reset_index()
    )
    route_map = route_map[route_map["side_count"] == 1].copy()
    approach_map = (
        existing.groupby(["stable_signal_id", "signal_approach_id_v2"], dropna=False)
        .agg(side_count=("_side", "nunique"), inherited_side=("_side", "first"), method_count=("_method", "nunique"), inherited_method=("_method", "first"))
        .reset_index()
    )
    approach_map = approach_map[approach_map["side_count"] == 1].copy()

    log_progress("Applying same-route deterministic directionality inheritance.")
    missing_base = df[~nonnull(side_label_series(df))].copy()
    missing_base["_row_index"] = missing_base.index
    route_assign = missing_base.merge(
        route_map[
            [
                "stable_signal_id",
                "signal_approach_id_v2",
                "source_route_name",
                "inherited_side",
                "inherited_method",
            ]
        ],
        on=["stable_signal_id", "signal_approach_id_v2", "source_route_name"],
        how="left",
    )
    route_assign = route_assign[nonnull(route_assign["inherited_side"])].copy()
    route_indices = route_assign["_row_index"].astype(int).tolist()
    if route_indices:
        df.loc[route_indices, "upstream_downstream_values"] = route_assign.set_index("_row_index")["inherited_side"]
        df.loc[route_indices, "directionality_coverage_status_values"] = "covered_directional_mvp"
        df.loc[route_indices, "mvp_directionality_method_values"] = route_assign.set_index("_row_index")["inherited_method"]
        method_values = []
        for _, row in route_assign.iterrows():
            origin = str(row.get("bin_row_origin", ""))
            klass = str(row.get("continuation_class", ""))
            if origin == "generated_distance_continuation_bin":
                if "divided_carriageway" in klass:
                    method_values.append("recovered_divided_carriageway_direct_continuation")
                elif "synthetic" in str(row.get("inherited_method", "")).lower():
                    method_values.append("recovered_synthetic_undivided_continuation")
                else:
                    method_values.append("recovered_generated_same_corridor_inheritance")
            else:
                method_values.append("recovered_existing_same_corridor_inheritance")
        route_assign["_recovery_method"] = method_values
        df.loc[route_indices, "directionality_recovery_method"] = route_assign.set_index("_row_index")["_recovery_method"]
        df.loc[route_indices, "directionality_recovery_status"] = "recovered"
        df.loc[route_indices, "directionality_recovery_evidence_fields"] = "stable_signal_id|signal_approach_id_v2|source_route_name"

    log_progress("Applying same-approach neighbor-continuity directionality inheritance.")
    remaining = df[~nonnull(side_label_series(df))].copy()
    remaining["_row_index"] = remaining.index
    approach_assign = remaining.merge(
        approach_map[["stable_signal_id", "signal_approach_id_v2", "inherited_side", "inherited_method"]],
        on=["stable_signal_id", "signal_approach_id_v2"],
        how="left",
    )
    approach_assign = approach_assign[nonnull(approach_assign["inherited_side"])].copy()
    approach_indices = approach_assign["_row_index"].astype(int).tolist()
    if approach_indices:
        df.loc[approach_indices, "upstream_downstream_values"] = approach_assign.set_index("_row_index")["inherited_side"]
        df.loc[approach_indices, "directionality_coverage_status_values"] = "covered_directional_mvp"
        df.loc[approach_indices, "mvp_directionality_method_values"] = approach_assign.set_index("_row_index")["inherited_method"]
        approach_assign["_recovery_method"] = approach_assign["bin_row_origin"].map(
            {
                "generated_distance_continuation_bin": "recovered_generated_neighbor_continuity",
                "existing_staged_bin": "recovered_existing_neighbor_continuity",
            }
        ).fillna("recovered_neighbor_continuity")
        df.loc[approach_indices, "directionality_recovery_method"] = approach_assign.set_index("_row_index")["_recovery_method"]
        df.loc[approach_indices, "directionality_recovery_status"] = "recovered"
        df.loc[approach_indices, "directionality_recovery_evidence_fields"] = "stable_signal_id|signal_approach_id_v2"

    recovered_mask = nonnull(side_label_series(df)) & ~nonnull(original_side)
    if "directionality_direct_or_synthetic_values" in df.columns:
        inherited = df.loc[recovered_mask, "mvp_directionality_method_values"].astype(str).str.lower()
        df.loc[recovered_mask & inherited.str.contains("synthetic", na=False), "directionality_direct_or_synthetic_values"] = "synthetic"
        df.loc[recovered_mask & inherited.str.contains("direct", na=False), "directionality_direct_or_synthetic_values"] = "direct"
        df.loc[recovered_mask & ~inherited.str.contains("synthetic|direct", regex=True, na=False), "directionality_direct_or_synthetic_values"] = "inherited"
    df.loc[recovered_mask, "directionality_caveat_values"] = "directionality inherited deterministically from existing same approach/corridor bins"
    df.loc[recovered_mask, "directionality_upstream_downstream_count"] = side_label_series(df.loc[recovered_mask]).astype(str).str.split("|").map(lambda x: len([v for v in x if v]))
    df.loc[recovered_mask, "directionality_coverage_preserved_flag"] = False

    log_progress("Classifying unresolved directionality rows.")
    still_missing = df.index[~nonnull(side_label_series(df))]
    if len(still_missing):
        miss = df.loc[still_missing, ["stable_signal_id", "signal_approach_id_v2", "source_route_name"]].copy()
        miss["_row_index"] = miss.index
        miss_route = miss.merge(
            route_map[["stable_signal_id", "signal_approach_id_v2", "source_route_name", "inherited_side"]],
            on=["stable_signal_id", "signal_approach_id_v2", "source_route_name"],
            how="left",
        )
        miss_app = miss.merge(
            approach_map[["stable_signal_id", "signal_approach_id_v2", "inherited_side"]],
            on=["stable_signal_id", "signal_approach_id_v2"],
            how="left",
        )
        route_available = nonnull(miss_route["inherited_side"]).to_numpy()
        app_available = nonnull(miss_app["inherited_side"]).to_numpy()
        missing_key = (~nonnull(miss["stable_signal_id"]) | ~nonnull(miss["signal_approach_id_v2"])).to_numpy()
        reason = pd.Series("unresolved_no_directional_neighbor", index=miss.index, dtype="object")
        reason.loc[missing_key] = "unresolved_missing_route_or_corridor_fields"
        reason.loc[route_available | app_available] = "unresolved_multiple_side_candidates"
        df.loc[still_missing, "directionality_recovery_status"] = reason.values
        df.loc[still_missing, "directionality_recovery_method"] = "not_recovered"
        df.loc[still_missing, "directionality_recovery_evidence_fields"] = "deterministic_side_evidence_not_available"

    applied_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "signal_approach_id_v2",
        "bin_row_origin",
        "source_route_name",
        "directionality_recovery_method",
        "directionality_recovery_evidence_fields",
    ]
    applied = df.loc[recovered_mask, [c for c in applied_cols if c in df.columns]].copy()
    applied["distance_band"] = normalize_band(df.loc[applied.index])
    applied["recovered_upstream_downstream"] = side_label_series(df.loc[applied.index]).values

    changed_existing = (
        (df["bin_row_origin"] == "existing_staged_bin")
        & nonnull(original_side)
        & (side_label_series(df).astype(str) != original_side.astype(str))
    )
    conflicts = []
    if changed_existing.any():
        conflicts.append({"conflict_check": "existing_directionality_changed", "problem_count": int(changed_existing.sum())})
    dup_ids = int(df["stable_bin_id"].duplicated().sum()) if "stable_bin_id" in df.columns else len(df)
    conflicts.append({"conflict_check": "duplicate_stable_bin_id", "problem_count": dup_ids})
    missing_gen_app = int(((df["bin_row_origin"] == "generated_distance_continuation_bin") & ~nonnull(df["signal_approach_id_v2"])).sum())
    conflicts.append({"conflict_check": "generated_bins_missing_signal_approach_id_v2", "problem_count": missing_gen_app})
    beyond_2500 = int(((df["bin_row_origin"] == "generated_distance_continuation_bin") & (pd.to_numeric(df["distance_end_ft"], errors="coerce") > 2500)).sum())
    conflicts.append({"conflict_check": "generated_bins_beyond_2500ft", "problem_count": beyond_2500})
    conflicts.append({"conflict_check": "crash_direction_fields_used", "problem_count": 0})
    return df, applied.reset_index(drop=True), pd.DataFrame(conflicts)


def summary_tables(before_existing: pd.DataFrame, expanded_before: pd.DataFrame, recovered: pd.DataFrame, applied: pd.DataFrame) -> dict[str, pd.DataFrame]:
    before_side = side_label_series(expanded_before)
    after_side = side_label_series(recovered)
    existing_side = side_label_series(before_existing)
    total = len(recovered)
    method_counts = recovered["directionality_recovery_method"].fillna("unknown").value_counts().reset_index()
    method_counts.columns = ["directionality_recovery_method", "row_count"]
    unresolved = recovered[~nonnull(after_side)].copy()
    unresolved_summary = (
        unresolved.groupby("directionality_recovery_status", dropna=False)
        .size()
        .reset_index(name="unresolved_rows")
        .sort_values("unresolved_rows", ascending=False)
    )
    unit_before_append = unit_count(before_existing)
    unit_after_append_pre = unit_count(expanded_before)
    unit_after = unit_count(recovered)
    unit_summary = pd.DataFrame(
        [
            {"metric": "direction_ready_units_before_append", "value": unit_before_append},
            {"metric": "direction_ready_units_after_append_before_recovery", "value": unit_after_append_pre},
            {"metric": "direction_ready_units_after_recovery", "value": unit_after},
            {"metric": "additional_units_recovered_by_directionality", "value": unit_after - unit_after_append_pre},
            {"metric": "approach_band_support_units_after_recovery", "value": approach_band_count(recovered)},
            {"metric": "conservative_target", "value": CONSERVATIVE_TARGET},
            {"metric": "upper_bound_target", "value": UPPER_BOUND_TARGET},
            {"metric": "percent_conservative_target_reached", "value": round(unit_after / CONSERVATIVE_TARGET * 100, 4)},
            {"metric": "percent_upper_bound_target_reached", "value": round(unit_after / UPPER_BOUND_TARGET * 100, 4)},
        ]
    )
    qa = pd.DataFrame(
        [
            {"qa_check": "expanded_bin_row_count", "value": total, "problem_count": 0 if total == EXPECTED_EXPANDED_ROWS else 1},
            {"qa_check": "row_loss_count", "value": EXPECTED_EXPANDED_ROWS - total, "problem_count": 0 if total == EXPECTED_EXPANDED_ROWS else abs(EXPECTED_EXPANDED_ROWS - total)},
            {"qa_check": "duplicate_stable_bin_id_count", "value": int(recovered["stable_bin_id"].duplicated().sum()), "problem_count": int(recovered["stable_bin_id"].duplicated().sum())},
            {"qa_check": "approach_id_coverage_percent", "value": round(nonnull(recovered["signal_approach_id_v2"]).sum() / total * 100, 4), "problem_count": 0},
            {"qa_check": "bins_with_directionality_before_recovery", "value": int(nonnull(before_side).sum()), "problem_count": 0},
            {"qa_check": "bins_with_directionality_after_recovery", "value": int(nonnull(after_side).sum()), "problem_count": 0},
            {"qa_check": "new_bins_assigned_directionality", "value": int((nonnull(after_side) & ~nonnull(before_side)).sum()), "problem_count": 0},
            {
                "qa_check": "existing_bins_newly_assigned_directionality",
                "value": int(((recovered["bin_row_origin"] == "existing_staged_bin") & nonnull(after_side) & ~nonnull(before_side)).sum()),
                "problem_count": 0,
            },
            {
                "qa_check": "generated_bins_newly_assigned_directionality",
                "value": int(((recovered["bin_row_origin"] == "generated_distance_continuation_bin") & nonnull(after_side) & ~nonnull(before_side)).sum()),
                "problem_count": 0,
            },
            {"qa_check": "remaining_bins_missing_directionality", "value": int((~nonnull(after_side)).sum()), "problem_count": 0},
            {"qa_check": "directionality_coverage_percent_after_recovery", "value": round(nonnull(after_side).sum() / total * 100, 4), "problem_count": 0},
            {"qa_check": "existing_directionality_values_changed", "value": 0, "problem_count": 0},
            {"qa_check": "crash_direction_fields_used", "value": 0, "problem_count": 0},
        ]
    )
    rec_by_band = (
        recovered.assign(_has_dir=nonnull(after_side), _band=normalize_band(recovered))
        .groupby(["_band", "directionality_recovery_method"], dropna=False)["_has_dir"]
        .sum()
        .reset_index(name="bins_with_directionality")
        .rename(columns={"_band": "distance_band"})
    )
    rec_by_origin = (
        recovered.assign(_has_dir=nonnull(after_side))
        .groupby(["bin_row_origin", "directionality_recovery_method"], dropna=False)["_has_dir"]
        .sum()
        .reset_index(name="bins_with_directionality")
    )
    rec_by_class = (
        recovered.assign(_has_dir=nonnull(after_side))
        .groupby(["continuation_class", "directionality_recovery_method"], dropna=False)["_has_dir"]
        .sum()
        .reset_index(name="bins_with_directionality")
    )
    backlog_signal = (
        unresolved.groupby("stable_signal_id", dropna=False).size().reset_index(name="remaining_missing_directionality_bins").sort_values("remaining_missing_directionality_bins", ascending=False)
    )
    backlog_approach = (
        unresolved.groupby(["stable_signal_id", "signal_approach_id_v2"], dropna=False)
        .size()
        .reset_index(name="remaining_missing_directionality_bins")
        .sort_values("remaining_missing_directionality_bins", ascending=False)
    )
    backlog_band = (
        unresolved.assign(_band=normalize_band(unresolved))
        .groupby("_band", dropna=False)
        .size()
        .reset_index(name="remaining_missing_directionality_bins")
        .rename(columns={"_band": "distance_band"})
    )
    units_by_band = []
    temp = recovered[nonnull(after_side)].copy()
    temp["_band"] = normalize_band(temp)
    temp["_side"] = after_side.loc[temp.index].astype(str).str.split("|")
    ex = temp.explode("_side")
    ex = ex[nonnull(ex["_side"])]
    if not ex.empty:
        units_by_band = (
            ex[["stable_signal_id", "signal_approach_id_v2", "_band", "_side"]]
            .drop_duplicates()
            .groupby("_band")
            .size()
            .reset_index(name="direction_ready_units")
            .rename(columns={"_band": "distance_band"})
        )
    else:
        units_by_band = pd.DataFrame(columns=["distance_band", "direction_ready_units"])
    return {
        "method_counts": method_counts,
        "unresolved_summary": unresolved_summary,
        "unresolved_sample": unresolved.head(5000),
        "unit_summary": unit_summary,
        "qa": qa,
        "recovery_by_band": rec_by_band,
        "recovery_by_origin": rec_by_origin,
        "recovery_by_class": rec_by_class,
        "backlog_signal": backlog_signal,
        "backlog_approach": backlog_approach,
        "backlog_band": backlog_band,
        "units_by_band": units_by_band,
        "applied": applied,
    }


def update_metadata(recovered: pd.DataFrame, applied: pd.DataFrame, qa: pd.DataFrame) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    update = {
        "timestamp_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "operation": "appended_generated_bins_and_recovered_directionality",
        "canonical_root_products_unchanged": True,
        "staged_bin_context_row_count": int(len(recovered)),
        "generated_bins_appended": EXPECTED_PROPOSED_ROWS,
        "directionality_recovered_rows": int(len(applied)),
        "remaining_directionality_missing_rows": int((~nonnull(side_label_series(recovered))).sum()),
        "mvp_regeneration_deferred": True,
        "note": "Staged candidate only; not promoted canonical cache.",
    }
    manifest.setdefault("staging_updates", []).append(update)
    manifest["latest_expanded_directionality_recovery"] = update
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    schema = json.loads(SCHEMA.read_text(encoding="utf-8")) if SCHEMA.exists() else {"tables": {}}
    schema.setdefault("tables", {})
    schema["tables"]["bin_context"] = {
        "path": rel(BIN_CONTEXT),
        "row_count": int(len(recovered)),
        "expected_grain": "one bin row, including existing staged bins and generated distance continuation bins",
        "status": "staged_candidate_expanded_not_promoted",
        "columns": [{"name": c, "dtype": str(recovered[c].dtype)} for c in recovered.columns],
    }
    SCHEMA.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    existing = README.read_text(encoding="utf-8") if README.exists() else ""
    section = f"""

## Expanded Bin Context Directionality Recovery

Generated: {now_iso()}

QA-passed proposed generated bins were appended to staged `bin_context.parquet`.
Canonical root products remain unchanged. This remains a staged candidate, not a
promoted canonical cache. MVP regeneration is deferred until structural QA
passes.

Expanded bin rows: {len(recovered)}
Generated bins appended: {EXPECTED_PROPOSED_ROWS}
Directionality recovered rows: {len(applied)}
Remaining rows missing directionality: {(~nonnull(side_label_series(recovered))).sum()}
"""
    marker = "## Expanded Bin Context Directionality Recovery"
    if marker in existing:
        existing = existing.split(marker)[0].rstrip() + "\n"
    README.write_text(existing.rstrip() + section, encoding="utf-8")


def write_findings(tables: dict[str, pd.DataFrame], append_summary: pd.DataFrame, recommendation: str) -> None:
    qa = tables["qa"]
    unit = tables["unit_summary"]
    before = int(unit.loc[unit["metric"] == "direction_ready_units_after_append_before_recovery", "value"].iloc[0])
    after = int(unit.loc[unit["metric"] == "direction_ready_units_after_recovery", "value"].iloc[0])
    recovered = after - before
    remaining = int(qa.loc[qa["qa_check"] == "remaining_bins_missing_directionality", "value"].iloc[0])
    text = f"""# Expanded Directionality Recovery Audit

## What appending proposed generated bins changed

The staged `bin_context.parquet` now contains {EXPECTED_EXPANDED_ROWS:,} rows: {EXPECTED_EXISTING_ROWS:,} existing staged bins plus {EXPECTED_PROPOSED_ROWS:,} generated distance-continuation bins.

## Directionality before recovery

Before recovery, generated bins had no upstream/downstream assignment. Existing direction-ready unit count after append but before recovery was {before:,}.

## Deterministic directionality rules applied

Rules applied only when existing same-corridor or same-approach evidence had one non-conflicting upstream/downstream value. Crash direction fields were not used.

## Directionality after recovery

Direction-ready units after recovery: {after:,}. Newly recovered direction-ready units: {recovered:,}. Remaining rows missing directionality: {remaining:,}.

## New distance-aware direction units recovered

See `current_vs_recovered_unit_summary.csv` and `recovered_units_by_distance_band.csv`.

## Remaining directionality blockers

Remaining blockers are summarized in `directionality_unresolved_summary.csv`; unresolved rows were left unfilled.

## Whether the expanded staged bin_context is ready for MVP unit regeneration

Recommendation: `{recommendation}`. This should receive structural QA before MVP regeneration.

## Recommended next step

Run a structural readiness audit of the expanded staged `bin_context.parquet`, then decide whether to regenerate distance-aware MVP units from this staged cache.
"""
    (REVIEW_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_LOG.write_text("", encoding="utf-8")
    log_progress("Started append and directionality recovery.")
    progress = [f"# Progress", f"- {now_iso()} Started append and directionality recovery."]
    required = [BIN_CONTEXT, PROPOSED_BINS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, SIGNAL_APPROACHES, APPROACH_WINDOWS, MANIFEST, SCHEMA, README]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))

    print("reading staged inputs", flush=True)
    log_progress("Reading staged inputs.")
    existing = pd.read_parquet(BIN_CONTEXT)
    proposed = pd.read_parquet(PROPOSED_BINS)
    pd.read_parquet(CONTINUATION_CORRIDORS)
    pd.read_parquet(CONTINUATION_PROVENANCE)
    pd.read_parquet(SIGNAL_APPROACHES)
    pd.read_parquet(APPROACH_WINDOWS)
    existing_unit_count = unit_count(existing)
    validation = validate_generated_bins(existing, proposed)
    log_progress("Writing pre-append generated-bin validation.")
    write_csv(validation, REVIEW_DIR / "pre_append_generated_bin_validation.csv")
    blocking = validation[validation["status"].eq("fail") & (validation["problem_count"] > 0)]
    if not blocking.empty:
        recommendation = "expanded_bin_context_append_blocked_by_generated_bin_qa"
        write_csv(pd.DataFrame([{"recommendation": recommendation, "blocking_checks": "|".join(blocking["qa_check"].astype(str))}]), REVIEW_DIR / "recommended_next_actions.csv")
        print(recommendation)
        return

    print("appending generated bins in memory", flush=True)
    log_progress("Appending generated bins in memory.")
    expanded_before = align_and_append(existing, proposed)
    append_summary = pd.DataFrame(
        [
            {"metric": "existing_rows_before_append", "value": len(existing)},
            {"metric": "generated_bins_appended", "value": len(proposed)},
            {"metric": "expanded_rows_after_append", "value": len(expanded_before)},
            {"metric": "expected_expanded_rows", "value": EXPECTED_EXPANDED_ROWS},
            {"metric": "row_loss_count", "value": EXPECTED_EXPANDED_ROWS - len(expanded_before)},
        ]
    )
    write_csv(append_summary, REVIEW_DIR / "append_summary.csv")
    write_csv(append_summary, EXPORT_DIR / "generated_bins_append_summary.csv")
    write_csv(pre_recovery_summary(expanded_before, existing_unit_count), REVIEW_DIR / "directionality_pre_recovery_summary.csv")

    print("recovering deterministic directionality", flush=True)
    log_progress("Recovering deterministic directionality.")
    recovered, applied, conflicts = recover_directionality(expanded_before)
    tables = summary_tables(existing, expanded_before, recovered, applied)
    log_progress("Built recovery summary tables.")
    conflict_all = pd.concat([conflicts], ignore_index=True)
    write_csv(conflict_all, REVIEW_DIR / "directionality_conflict_checks.csv")
    hard_conflicts = int(conflict_all["problem_count"].sum())
    if hard_conflicts:
        recommendation = "expanded_bin_context_directionality_recovery_blocked_by_conflicts"
        print(recommendation)
        return

    print("writing updated staged bin_context", flush=True)
    log_progress("Writing updated staged bin_context parquet.")
    recovered.to_parquet(BIN_CONTEXT, index=False)

    expanded_summary = pd.DataFrame(
        [
            {"metric": "expanded_bin_rows", "value": len(recovered)},
            {"metric": "assigned_approach_id_rows", "value": int(nonnull(recovered["signal_approach_id_v2"]).sum())},
            {"metric": "approach_id_coverage_percent", "value": round(nonnull(recovered["signal_approach_id_v2"]).sum() / len(recovered) * 100, 4)},
            {"metric": "bins_with_directionality", "value": int(nonnull(side_label_series(recovered)).sum())},
            {"metric": "bins_missing_directionality", "value": int((~nonnull(side_label_series(recovered))).sum())},
            {"metric": "directionality_coverage_percent", "value": round(nonnull(side_label_series(recovered)).sum() / len(recovered) * 100, 4)},
        ]
    )
    write_csv(expanded_summary, REVIEW_DIR / "expanded_bin_context_summary.csv")
    log_progress("Writing review and staging exports.")
    write_csv(expanded_summary, EXPORT_DIR / "expanded_bin_context_post_append_summary.csv")
    write_csv(tables["method_counts"], REVIEW_DIR / "directionality_recovery_method_counts.csv")
    write_csv(tables["recovery_by_band"], REVIEW_DIR / "directionality_recovery_by_distance_band.csv")
    write_csv(tables["recovery_by_origin"], REVIEW_DIR / "directionality_recovery_by_origin.csv")
    write_csv(tables["recovery_by_class"], REVIEW_DIR / "directionality_recovery_by_continuation_class.csv")
    write_csv(tables["unresolved_summary"], REVIEW_DIR / "directionality_unresolved_summary.csv")
    write_csv(tables["unresolved_sample"], REVIEW_DIR / "directionality_unresolved_rows_sample.csv")
    write_csv(tables["qa"], REVIEW_DIR / "directionality_qa_after_recovery.csv")
    write_csv(tables["unit_summary"], REVIEW_DIR / "current_vs_recovered_unit_summary.csv")
    write_csv(tables["units_by_band"], REVIEW_DIR / "recovered_units_by_distance_band.csv")
    write_csv(tables["method_counts"], REVIEW_DIR / "recovered_units_by_method.csv")
    write_csv(tables["backlog_signal"], REVIEW_DIR / "remaining_directionality_backlog_by_signal.csv")
    write_csv(tables["backlog_approach"], REVIEW_DIR / "remaining_directionality_backlog_by_approach.csv")
    write_csv(tables["backlog_band"], REVIEW_DIR / "remaining_directionality_backlog_by_distance_band.csv")
    write_csv(tables["applied"], EXPORT_DIR / "directionality_recovery_applied_rows.csv")
    write_csv(tables["unresolved_sample"], EXPORT_DIR / "directionality_recovery_unresolved_rows.csv")
    write_csv(conflict_all, EXPORT_DIR / "directionality_recovery_conflicts.csv")
    write_csv(tables["unit_summary"], EXPORT_DIR / "directionality_unit_impact_after_recovery.csv")
    write_csv(tables["qa"], EXPORT_DIR / "expanded_bin_context_final_structural_summary.csv")
    apply_summary = pd.DataFrame(
        [
            {"metric": "directionality_recovered_rows", "value": len(applied)},
            {"metric": "remaining_directionality_missing_rows", "value": int((~nonnull(side_label_series(recovered))).sum())},
            {"metric": "direction_ready_units_after_recovery", "value": int(tables["unit_summary"].loc[tables["unit_summary"]["metric"] == "direction_ready_units_after_recovery", "value"].iloc[0])},
        ]
    )
    write_csv(apply_summary, EXPORT_DIR / "directionality_recovery_apply_summary.csv")

    unit_after = int(tables["unit_summary"].loc[tables["unit_summary"]["metric"] == "direction_ready_units_after_recovery", "value"].iloc[0])
    unresolved_count = int((~nonnull(side_label_series(recovered))).sum())
    recommendation = (
        "expanded_bin_context_directionality_recovery_ready_for_review"
        if unresolved_count == 0 or unit_after > existing_unit_count
        else "expanded_bin_context_directionality_recovery_partial_success"
    )
    next_actions = pd.DataFrame(
        [
            {"priority": 1, "recommended_action": "audit_expanded_staged_bin_context_structural_readiness", "rationale": "Expanded bin_context was mutated and should be structurally QAed before MVP work."},
            {"priority": 2, "recommended_action": "regenerate_distance_aware_mvp_units_from_staged_bin_context_after_structural_QA", "rationale": "Directionality was recovered deterministically where possible."},
            {"priority": 3, "recommended_action": "prepare_directionality_review_for_remaining_blockers_if_needed", "rationale": "Unresolved directionality remains explicit and flagged."},
        ]
    )
    write_csv(next_actions, REVIEW_DIR / "recommended_next_actions.csv")
    update_metadata(recovered, applied, tables["qa"])
    log_progress("Updated staging manifest, schema, and README.")
    write_findings(tables, append_summary, recommendation)
    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(REVIEW_DIR),
        "inputs_read": [rel(p) for p in required],
        "staged_files_updated": [rel(BIN_CONTEXT), rel(MANIFEST), rel(SCHEMA), rel(README)],
        "canonical_products_modified": False,
        "mvp_regenerated": False,
        "generated_bins_appended": int(len(proposed)),
        "expanded_bin_context_rows": int(len(recovered)),
        "directionality_recovered_rows": int(len(applied)),
        "remaining_directionality_missing_rows": unresolved_count,
    }
    (REVIEW_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa_manifest = {
        "required_outputs_written": True,
        "row_loss_count": int(EXPECTED_EXPANDED_ROWS - len(recovered)),
        "duplicate_stable_bin_id_count": int(recovered["stable_bin_id"].duplicated().sum()),
        "canonical_products_modified": False,
        "crash_direction_fields_used": False,
        "directionality_assignment_deterministic_only": True,
        "recommendation": recommendation,
    }
    (REVIEW_DIR / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2), encoding="utf-8")
    progress.append(f"- {now_iso()} Appended generated bins and recovered deterministic directionality.")
    progress.append(f"- {now_iso()} See run_progress_log.txt for flushed stage-by-stage log.")
    progress_text = "\n".join(progress) + "\n"
    (REVIEW_DIR / "progress_log.md").write_text(progress_text, encoding="utf-8")
    log_progress("Completed append and directionality recovery.")
    print(recommendation)
    print(f"expanded_bin_context_rows={len(recovered)}")
    print(f"directionality_recovered_rows={len(applied)}")
    print(f"remaining_directionality_missing_rows={unresolved_count}")
    print(f"direction_ready_units_after_recovery={unit_after}")


if __name__ == "__main__":
    main()
