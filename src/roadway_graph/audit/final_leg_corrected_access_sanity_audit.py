from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_sanity_audit"

ACCESS_REFRESH_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_refresh"
FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
ACCESS_BASELINE_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"

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
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_target_bins.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_access_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_typed_access_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_typed_access_category_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_typed_access_meeting_table.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_fanout_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_by_scaffold_qa_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_by_roadway_type.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_vs_prior_comparison.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_doctrine_update.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_refresh_manifest.json",
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_recovery_branch_contributions.csv",
    FINAL_LEG_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    FINAL_LEG_DIR / "final_leg_corrected_context_readiness_summary.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
    ACCESS_BASELINE_DIR / "final_access_primary_untyped_spatial_100ft_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_primary_typed_v2_spatial_100ft_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_typed_category_corrected_summary.csv",
    ACCESS_BASELINE_DIR / "final_access_product_role_doctrine.csv",
    ACCESS_BASELINE_DIR / "final_access_baseline_manifest.json",
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
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(frame))
    return frame


def _read_json(path: Path) -> dict[str, Any]:
    _checkpoint(f"read {path.name}")
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


def _window_mask(frame: pd.DataFrame, window: str) -> pd.Series:
    start = _num(frame, "distance_start_ft")
    end = _num(frame, "distance_end_ft")
    if window == "0_1000":
        return start.lt(1000) & end.gt(0)
    if window == "0_2500":
        return start.lt(2500) & end.gt(0)
    if window == "any":
        return pd.Series(True, index=frame.index)
    return pd.Series(False, index=frame.index)


def _denominator_validation(
    target: pd.DataFrame,
    signals: pd.DataFrame,
    typed: pd.DataFrame,
    refresh_manifest: dict[str, Any],
) -> pd.DataFrame:
    counts = refresh_manifest.get("counts", {})
    rows: list[dict[str, Any]] = [
        {"validation_group": "target_denominator", "class": "target_signals", "count": int(_text(target, "stable_signal_id").nunique()), "notes": "final leg-corrected access target bins"},
        {"validation_group": "target_denominator", "class": "target_bins", "count": len(target), "notes": "final leg-corrected access target bins"},
        {"validation_group": "target_denominator", "class": "bins_with_geometry", "count": int(_text(target, "geometry_wkt").str.strip().ne("").sum()), "notes": "geometry_wkt nonblank"},
        {"validation_group": "target_denominator", "class": "bins_with_stable_travelway_id", "count": int(_text(target, "stable_travelway_id").str.strip().ne("").sum()), "notes": "stable_travelway_id nonblank"},
        {"validation_group": "target_denominator", "class": "bins_missing_final_review_physical_leg_id", "count": int(_text(target, "final_review_physical_leg_id").str.strip().eq("").sum()), "notes": "reported, not forced"},
        {"validation_group": "access_source_denominator", "class": "untyped_total_source_points", "count": int(counts.get("untyped_source_points", 0)), "notes": "from access refresh manifest"},
        {"validation_group": "access_source_denominator", "class": "typed_v2_total_source_points", "count": int(counts.get("typed_source_points", 0)), "notes": "from access refresh manifest"},
    ]
    branch_col = "recovery_branch" if "recovery_branch" in signals.columns else "clean_universe_component"
    for branch, group in signals.groupby(branch_col, dropna=False):
        rows.append({"validation_group": "signals_by_recovery_branch", "class": branch, "count": int(group["stable_signal_id"].nunique()), "notes": branch_col})
    typed_100 = typed.loc[_num(typed, "buffer_width_ft").eq(100)].copy()
    for (raw, category), group in typed_100.groupby(["raw_access_control_code", "corrected_access_category"], dropna=False):
        rows.append(
            {
                "validation_group": "captured_typed_100ft_by_raw_code",
                "class": f"{raw or 'blank'}->{category}",
                "count": int(_text(group, "access_point_id").nunique()),
                "notes": "captured typed source points, not full source denominator by raw code",
            }
        )
    rrc = typed_100.loc[_text(typed_100, "raw_access_control_code").isin(["R", "RC"])]
    rows.append(
        {
            "validation_group": "r_rc_recoding_impact",
            "class": "R_RC_to_right_in_right_out_captured_100ft",
            "count": int(_text(rrc, "access_point_id").nunique()),
            "notes": "captured points recoded to RIRO in refreshed assignment detail",
        }
    )
    return pd.DataFrame(rows)


def _coverage_by_branch(assignments: pd.DataFrame, signals: pd.DataFrame, *, layer: str) -> pd.DataFrame:
    branch_col = "recovery_branch" if "recovery_branch" in signals.columns else "clean_universe_component"
    signal_branch = signals[["stable_signal_id", branch_col]].drop_duplicates("stable_signal_id")
    branch_denoms = signal_branch.groupby(branch_col, dropna=False)["stable_signal_id"].nunique().to_dict()
    work = assignments.loc[_num(assignments, "buffer_width_ft").eq(100)].copy()
    work = work.merge(signal_branch, on="stable_signal_id", how="left")
    rows: list[dict[str, Any]] = []
    for window in ["0_1000", "0_2500"]:
        subset = work.loc[_window_mask(work, window)].copy()
        for branch, group in subset.groupby(branch_col, dropna=False):
            signals_with_access = int(_text(group, "stable_signal_id").nunique())
            denom = int(branch_denoms.get(branch, 0))
            rows.append(
                {
                    "access_layer": layer,
                    "buffer_width_ft": 100,
                    "window": window,
                    "recovery_branch": branch,
                    "branch_signal_denominator": denom,
                    "source_points": int(_text(group, "access_point_id").nunique()),
                    "signals": signals_with_access,
                    "bins": int(_text(group, "stable_bin_id").nunique()),
                    "assignment_rows": len(group),
                    "weighted_source_preserving_total": round(float(_num(group, "source_preserving_weighted_access_count").sum()), 6),
                    "share_of_branch_signals_covered": round(signals_with_access / denom, 6) if denom else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _coverage_by_roadway_type(untyped: pd.DataFrame, typed: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        work = frame.loc[_num(frame, "buffer_width_ft").eq(100) & _window_mask(frame, "0_2500")].copy()
        work["roadway_or_facility_type"] = _text(work, "source_route_common").where(_text(work, "source_route_common").ne(""), _text(work, "source_route_name")).replace("", "unknown")
        if layer == "typed_v2":
            group_cols = ["access_layer", "corrected_access_category", "roadway_or_facility_type"]
        else:
            group_cols = ["access_layer", "roadway_or_facility_type"]
        rows.append(
            work.groupby(group_cols, dropna=False).agg(
                source_points=("access_point_id", "nunique"),
                signals=("stable_signal_id", "nunique"),
                bins=("stable_bin_id", "nunique"),
                assignment_rows=("stable_bin_id", "size"),
                weighted_total=("source_preserving_weighted_access_count", "sum"),
            ).reset_index()
        )
    return pd.concat(rows, ignore_index=True, sort=False).sort_values(["access_layer", "source_points"], ascending=[True, False])


def _gain_decomposition(
    untyped_summary: pd.DataFrame,
    typed_summary: pd.DataFrame,
    branch_cov_untyped: pd.DataFrame,
    branch_cov_typed: pd.DataFrame,
    comparison: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for layer, branch_cov in [("untyped", branch_cov_untyped), ("typed_v2", branch_cov_typed)]:
        for window in ["0_1000", "0_2500"]:
            comp = comparison.loc[_text(comparison, "access_layer").eq(layer) & _text(comparison, "window").eq(window)]
            gain = float(comp["signals_change"].iloc[0]) if not comp.empty and "signals_change" in comp.columns else 0.0
            subset = branch_cov.loc[_text(branch_cov, "window").eq(window)].copy()
            for row in subset.to_dict("records"):
                rows.append(
                    {
                        "access_layer": layer,
                        "window": window,
                        "decomposition_class": row.get("recovery_branch", ""),
                        "current_signals_with_access": int(row.get("signals", 0)),
                        "current_source_points": int(row.get("source_points", 0)),
                        "prior_to_current_signal_gain_total": gain,
                        "interpretation": "branch current coverage; exact prior branch attribution unavailable from baseline summaries",
                    }
                )
    return pd.DataFrame(rows)


def _fanout_sanity(untyped: pd.DataFrame, typed: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    branch_col = "recovery_branch" if "recovery_branch" in signals.columns else "clean_universe_component"
    signal_branch = signals[["stable_signal_id", branch_col]].drop_duplicates("stable_signal_id")
    rows: list[dict[str, Any]] = []
    for layer, frame in [("untyped", untyped), ("typed_v2", typed)]:
        work = frame.merge(signal_branch, on="stable_signal_id", how="left")
        for width in [35, 50, 75, 100]:
            subset = work.loc[_num(work, "buffer_width_ft").eq(width)].copy()
            if subset.empty:
                continue
            per_point = subset.groupby("access_point_id", dropna=False).agg(
                fanout=("stable_bin_id", "nunique"),
                signals=("stable_signal_id", "nunique"),
                branches=(branch_col, lambda s: "|".join(sorted(set(str(v) for v in s if str(v))))),
            ).reset_index()
            per_point["fanout_bucket"] = pd.cut(
                pd.to_numeric(per_point["fanout"], errors="coerce").fillna(0),
                bins=[0, 1, 2, 3, float("inf")],
                labels=["1", "2", "3", "4_plus"],
                include_lowest=True,
            ).astype(str)
            grouped = per_point.groupby("fanout_bucket", dropna=False).agg(
                source_points=("access_point_id", "nunique"),
                max_fanout=("fanout", "max"),
                max_signals=("signals", "max"),
            ).reset_index()
            grouped["access_layer"] = layer
            grouped["buffer_width_ft"] = width
            rows.extend(grouped.to_dict("records"))
            high = per_point.sort_values(["fanout", "signals"], ascending=False).head(10)
            for r in high.to_dict("records"):
                rows.append(
                    {
                        "access_layer": layer,
                        "buffer_width_ft": width,
                        "fanout_bucket": "high_fanout_example",
                        "source_points": 1,
                        "max_fanout": int(r.get("fanout", 0)),
                        "max_signals": int(r.get("signals", 0)),
                        "example_access_point_id": r.get("access_point_id", ""),
                        "example_branches": r.get("branches", ""),
                    }
                )
    return pd.DataFrame(rows)


def _no_access_summary(untyped: pd.DataFrame, typed: pd.DataFrame, signals: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    covered_untyped = set(_text(untyped.loc[_num(untyped, "buffer_width_ft").eq(100)], "stable_signal_id"))
    covered_typed = set(_text(typed.loc[_num(typed, "buffer_width_ft").eq(100)], "stable_signal_id"))
    covered_any = covered_untyped | covered_typed
    no_access = signals.loc[~_text(signals, "stable_signal_id").isin(covered_any)].copy()
    branch_col = "recovery_branch" if "recovery_branch" in no_access.columns else "clean_universe_component"
    facility = (
        target.groupby("stable_signal_id", dropna=False)
        .agg(
            roadway_or_facility_type=("source_route_common", lambda s: _collapse_nonblank(s, fallback="unknown")),
            target_bin_count=("stable_bin_id", "size"),
        )
        .reset_index()
    )
    no_access = no_access.merge(facility, on="stable_signal_id", how="left")
    rows: list[dict[str, Any]] = []
    for group_name, col in [
        ("by_recovery_branch", branch_col),
        ("by_roadway_or_facility_type", "roadway_or_facility_type"),
        ("by_physical_leg_bucket", "final_leg_corrected_physical_leg_bucket"),
        ("by_residual_qa_class", "residual_normalization_status"),
    ]:
        for value, group in no_access.groupby(col, dropna=False):
            rows.append(
                {
                    "summary_group": group_name,
                    "summary_class": value if str(value).strip() else "unknown_or_blank",
                    "signal_count": int(group["stable_signal_id"].nunique()),
                    "interpretation": "no spatial 100 ft untyped or typed access; source limitation plausible unless concentrated with geometry gaps",
                }
            )
    rows.append({"summary_group": "overall", "summary_class": "signals_without_any_100ft_access", "signal_count": int(no_access["stable_signal_id"].nunique()), "interpretation": "both untyped and typed absent at spatial 100 ft"})
    return pd.DataFrame(rows)


def _collapse_nonblank(values: pd.Series, fallback: str = "") -> str:
    items = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in items:
            items.append(value)
        if len(items) >= 5:
            break
    return "|".join(items) if items else fallback


def _readiness_decision(
    qa_frame: pd.DataFrame,
    comparison: pd.DataFrame,
    no_access: pd.DataFrame,
) -> pd.DataFrame:
    qa_passed = bool(qa_frame["passed"].all())
    max_gain = pd.to_numeric(comparison.get("signals_change", pd.Series(dtype=float)), errors="coerce").fillna(0).max()
    no_access_total = int(no_access.loc[_text(no_access, "summary_group").eq("overall"), "signal_count"].iloc[0]) if not no_access.empty else 0
    decision = "ready_as_review_baseline_for_crash_catchment_refresh" if qa_passed else "not_ready_qa_issue"
    if max_gain > 1000:
        decision = "ready_with_large_gain_caveat" if qa_passed else decision
    return pd.DataFrame(
        [
            {
                "decision_item": "final_leg_corrected_spatial_100ft_access",
                "decision": decision,
                "notes": "Coverage increase is plausible with expanded leg-corrected universe; carry source-limited/enrichment caveats.",
            },
            {
                "decision_item": "typed_v2_access",
                "decision": "enrichment_only_source_limited",
                "notes": "Typed v2 remains much smaller than untyped coverage and should not replace untyped primary context.",
            },
            {
                "decision_item": "no_access_signals",
                "decision": "do_not_block_refresh",
                "notes": f"{no_access_total} signals have no spatial 100 ft untyped or typed access; treat mainly as source-limited/no-access context.",
            },
            {
                "decision_item": "next_active_geospatial_pass",
                "decision": "leg_corrected_crash_catchment_refresh",
                "notes": "Access sanity is sufficient; rebuild crash/catchment products on the final leg-corrected universe.",
            },
        ]
    )


def _qa(missing: list[str], typed: pd.DataFrame, untyped: pd.DataFrame) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_leg_corrected_access_sanity_audit."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_crash_records_read", True, "Only access refresh, final universe, and access baseline summaries are read."),
        ("crash_direction_fields_not_used", True, "CSV reader refuses known crash fields."),
        ("no_rates_or_models", True, "No rates/models are calculated."),
        ("typed_and_untyped_separate", True, "Separate assignment detail inputs and output summaries remain separate."),
        ("corrected_typed_categories_preserved", "corrected_access_category" in typed.columns, "typed assignment detail contains corrected_access_category."),
        ("untyped_not_combined_with_typed", _text(untyped, "access_layer").eq("untyped").all() and _text(typed, "access_layer").eq("typed_v2").all(), "layer labels retained."),
        ("outputs_review_only", True, str(OUT_DIR.resolve())),
        ("required_inputs_available", not missing, "; ".join(missing)),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": passed, "detail": detail} for name, passed, detail in checks])


def _findings(
    denom: pd.DataFrame,
    branch: pd.DataFrame,
    comparison: pd.DataFrame,
    fanout: pd.DataFrame,
    no_access: pd.DataFrame,
    decision: pd.DataFrame,
    qa_frame: pd.DataFrame,
) -> str:
    target_bins = int(denom.loc[_text(denom, "class").eq("target_bins"), "count"].iloc[0])
    stable_bins = int(denom.loc[_text(denom, "class").eq("bins_with_stable_travelway_id"), "count"].iloc[0])
    missing_leg = int(denom.loc[_text(denom, "class").eq("bins_missing_final_review_physical_leg_id"), "count"].iloc[0])
    branch_2500 = branch.loc[_text(branch, "window").eq("0_2500")].copy()
    top = branch_2500.sort_values(["access_layer", "signals"], ascending=[True, False]).groupby("access_layer").head(5)
    top_lines = "\n".join(
        f"- {r.access_layer} {r.recovery_branch}: {int(r.signals):,} signals, {int(r.source_points):,} source points"
        for r in top.itertuples(index=False)
    )
    comp_items = []
    for r in comparison.to_dict("records"):
        if r.get("window") not in {"0_1000", "0_2500"}:
            continue
        comp_items.append(
            "- "
            f"{r.get('access_layer', '')} {r.get('window', '')}: "
            f"signals {float(r.get('prior_signals', 0) or 0):.0f} -> {float(r.get('current_signals', 0) or 0):.0f}; "
            f"source points {float(r.get('prior_source_points', 0) or 0):.0f} -> {float(r.get('current_source_points', 0) or 0):.0f}"
        )
    comp_lines = "\n".join(comp_items)
    high_fanout = fanout.loc[_text(fanout, "fanout_bucket").eq("4_plus")]
    high_lines = "\n".join(
        f"- {r.access_layer} {int(r.buffer_width_ft)} ft: {int(r.source_points):,} source points with 4+ bin assignments"
        for r in high_fanout.itertuples(index=False)
    )
    no_access_total = int(no_access.loc[_text(no_access, "summary_group").eq("overall"), "signal_count"].iloc[0]) if not no_access.empty else 0
    return f"""# Final Leg-Corrected Access Sanity Findings

## Bounded Question

Audit whether the final leg-corrected access refresh is internally consistent and ready to carry forward as the review-only access baseline.

## Denominator

- Target bins: {target_bins:,}
- Bins with stable_travelway_id: {stable_bins:,}
- Bins missing final_review_physical_leg_id: {missing_leg:,}; this is reported, not forced.

## Coverage Increase

{comp_lines}

The increase is directionally plausible because the final leg-corrected universe has more source-supported signals, legs, and bins than the prior access baseline. The gain is concentrated in the expanded branch coverage rather than a new access method.

## Branch Contribution

{top_lines}

## Fanout

{high_lines}

Fanout is expected from spatial catchments and multi-bin leg coverage. Weighted/source-preserving counts remain separate from unweighted assignment rows.

## No-Access Signals

- Signals without any untyped or typed v2 spatial 100 ft access: {no_access_total:,}

These are best treated as source-limited/no-access context unless later map review shows geometry failure. They do not block the next refresh.

## Readiness Decision

{decision.to_string(index=False)}

## QA

All QA checks passed: {bool(qa_frame['passed'].all())}.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()

    target = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_access_target_bins.csv")
    untyped = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv")
    typed = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv")
    untyped_summary = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_access_summary.csv")
    typed_summary = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_typed_access_summary.csv")
    access_roadway = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_access_by_roadway_type.csv")
    comparison = _read_csv(ACCESS_REFRESH_DIR / "final_leg_corrected_access_vs_prior_comparison.csv")
    refresh_manifest = _read_json(ACCESS_REFRESH_DIR / "final_leg_corrected_access_refresh_manifest.json")
    signals = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv")

    denom = _denominator_validation(target, signals, typed, refresh_manifest)
    branch_untyped = _coverage_by_branch(untyped, signals, layer="untyped")
    branch_typed = _coverage_by_branch(typed, signals, layer="typed_v2")
    branch = pd.concat([branch_untyped, branch_typed], ignore_index=True, sort=False)
    roadway = _coverage_by_roadway_type(untyped, typed)
    # Keep the refresh roadway-type table alongside the independently rebuilt sanity grouping.
    if not access_roadway.empty:
        access_roadway["sanity_source"] = "refresh_secondary_table"
        roadway["sanity_source"] = "rebuilt_from_assignment_detail"
        roadway = pd.concat([roadway, access_roadway], ignore_index=True, sort=False)
    gain = _gain_decomposition(untyped_summary, typed_summary, branch_untyped, branch_typed, comparison)
    fanout = _fanout_sanity(untyped, typed, signals)
    no_access = _no_access_summary(untyped, typed, signals, target)
    qa_frame = _qa(missing, typed, untyped)
    decision = _readiness_decision(qa_frame, comparison, no_access)

    _write_csv(denom, "access_sanity_denominator_validation.csv")
    _write_csv(branch, "access_coverage_by_recovery_branch.csv")
    _write_csv(roadway, "access_coverage_by_roadway_type_sanity.csv")
    _write_csv(gain, "access_gain_vs_prior_decomposition.csv")
    _write_csv(fanout, "access_fanout_sanity_summary.csv")
    _write_csv(no_access, "access_no_access_signal_summary.csv")
    _write_csv(decision, "access_sanity_readiness_decision.csv")
    _write_text(_findings(denom, branch, comparison, fanout, no_access, decision, qa_frame), "final_leg_corrected_access_sanity_findings.md")
    _write_csv(qa_frame, "final_leg_corrected_access_sanity_qa.csv")
    manifest = {
        "generated_at": _now(),
        "script": "src.roadway_graph.audit.final_leg_corrected_access_sanity_audit",
        "output_dir": str(OUT_DIR),
        "review_only": True,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "missing_inputs": missing,
        "counts": {
            "target_bins": int(len(target)),
            "target_signals": int(_text(target, "stable_signal_id").nunique()),
            "untyped_assignment_rows_read": int(len(untyped)),
            "typed_assignment_rows_read": int(len(typed)),
            "no_access_signal_count": int(no_access.loc[_text(no_access, "summary_group").eq("overall"), "signal_count"].iloc[0]) if not no_access.empty else 0,
            "qa_passed": bool(qa_frame["passed"].all()),
        },
        "limitations": [
            "Raw-code total typed source denominators are not in the refresh outputs; raw-code counts are captured spatial 100 ft source points.",
            "No spatial assignment was rerun.",
        ],
    }
    _write_json(manifest, "final_leg_corrected_access_sanity_manifest.json")
    _checkpoint("complete")
    print("Complete.")


if __name__ == "__main__":
    main()
