from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/conservative_travelway_windowed_access"

SANITY_DIR = OUTPUT_ROOT / "review/current/travelway_normalized_access_sanity_audit"
STABLE_ACCESS_DIR = OUTPUT_ROOT / "review/current/stable_lineage_final_access_rerun"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"

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
    SANITY_DIR / "access_source_denominator_validation.csv",
    SANITY_DIR / "travelway_assignment_method_summary.csv",
    SANITY_DIR / "travelway_assignment_distance_window_detail.csv",
    SANITY_DIR / "travelway_assignment_overcapture_risk_detail.csv",
    SANITY_DIR / "typed_vs_untyped_capture_explanation.csv",
    SANITY_DIR / "conservative_travelway_access_coverage_estimates.csv",
    SANITY_DIR / "travelway_normalized_access_sanity_manifest.json",
    STABLE_ACCESS_DIR / "stable_lineage_final_access_target_bins.csv",
    STABLE_ACCESS_DIR / "stable_lineage_untyped_spatial_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_untyped_travelway_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_source_point_accounting.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_spatial_vs_travelway_comparison.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_product_coverage_summary.csv",
    STABLE_ACCESS_DIR / "stable_lineage_final_access_rerun_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
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
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items: list[str] = []
    for value in values.dropna().astype(str):
        if value.strip() and value not in items:
            items.append(value)
        if len(items) >= limit:
            break
    return "|".join(items)


def _assignment_key(frame: pd.DataFrame) -> pd.Series:
    return _text(frame, "access_point_id") + "||" + _text(frame, "access_layer") + "||" + _text(frame, "target_bin_id")


def _load_broad_assignments() -> pd.DataFrame:
    untyped = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_untyped_travelway_assignment_detail.csv")
    typed = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv")
    broad = pd.concat([untyped, typed], ignore_index=True, sort=False)
    broad = broad.loc[_text(broad, "route_normalized_assignment_status").eq("assigned_review_only")].copy()
    risk = _read_csv(SANITY_DIR / "travelway_assignment_overcapture_risk_detail.csv")
    risk["assignment_key"] = _assignment_key(risk)
    broad["assignment_key"] = _assignment_key(broad)
    risk_cols = [
        "assignment_key",
        "assignment_distance_band",
        "nearest_distance_ft",
        "nearest_distance_band",
        "captured_100ft",
        "hybrid_leg_length_class",
        "leg_length_limitation_class",
        "within_valid_signal_relative_window",
        "route_only_spatially_far_from_signal",
        "overcapture_risk_class",
    ]
    out = broad.merge(risk[[col for col in risk_cols if col in risk.columns]], on="assignment_key", how="left", suffixes=("", "_risk"))
    return out


def _blocked_by_qa(frame: pd.DataFrame) -> pd.Series:
    return _bool_text(frame, "source_limited_holdout_flag") | _bool_text(frame, "grade_mainline_holdout_flag") | _bool_text(frame, "still_insufficient_evidence_flag")


def _base_acceptance(frame: pd.DataFrame) -> pd.Series:
    match_ok = _text(frame, "stable_travelway_assignment_match_class").isin(["direct_stable_travelway_id", "route_measure_overlap"])
    target_ok = _text(frame, "target_bin_id").ne("") & _text(frame, "stable_bin_id").ne("")
    window_ok = _bool_text(frame, "within_valid_signal_relative_window") & _text(frame, "analysis_window").isin(["0_1000", "1000_2500"])
    risk_ok = ~_text(frame, "overcapture_risk_class").isin(
        [
            "route_identity_match_but_distance_uncertain",
            "route_identity_match_but_beyond_signal_window",
            "long_route_overcapture_risk",
            "route_family_only_low_confidence",
            "manual_review_needed",
        ]
    )
    quality_ok = ~_text(frame, "route_normalized_quality_class").eq("low_confidence_route_family_only")
    return match_ok & target_ok & window_ok & risk_ok & quality_ok & ~_blocked_by_qa(frame)


def _rejection_reason(frame: pd.DataFrame) -> pd.Series:
    out = pd.Series("accepted", index=frame.index, dtype=str)
    out.loc[~_text(frame, "stable_travelway_assignment_match_class").isin(["direct_stable_travelway_id", "route_measure_overlap"]),] = "rejected_no_direct_or_route_measure_match"
    out.loc[~_bool_text(frame, "within_valid_signal_relative_window"),] = "rejected_outside_or_missing_signal_window"
    out.loc[_text(frame, "analysis_window").isin(["0_1000", "1000_2500"]).eq(False),] = "rejected_outside_0_2500_window"
    out.loc[_text(frame, "route_normalized_quality_class").eq("low_confidence_route_family_only"),] = "rejected_route_family_only_low_confidence"
    out.loc[_text(frame, "overcapture_risk_class").eq("long_route_overcapture_risk"),] = "rejected_long_route_overcapture_risk"
    out.loc[_text(frame, "overcapture_risk_class").isin(["route_identity_match_but_distance_uncertain", "manual_review_needed"]),] = "rejected_distance_uncertain_or_manual_review"
    out.loc[_text(frame, "overcapture_risk_class").eq("route_identity_match_but_beyond_signal_window"),] = "rejected_beyond_signal_window"
    out.loc[_text(frame, "target_bin_id").eq("") | _text(frame, "stable_bin_id").eq(""),] = "rejected_missing_target_bin"
    out.loc[_blocked_by_qa(frame)] = "rejected_by_scaffold_qa_flag"
    out.loc[_base_acceptance(frame)] = "accepted"
    return out


def _accepted_for_window(broad: pd.DataFrame, window_name: str) -> pd.DataFrame:
    base = broad.loc[_base_acceptance(broad)].copy()
    if window_name == "conservative_0_1000":
        base = base.loc[_text(base, "analysis_window").eq("0_1000")].copy()
    elif window_name == "conservative_0_2500":
        base = base.loc[_text(base, "analysis_window").isin(["0_1000", "1000_2500"])].copy()
    base["conservative_window"] = window_name
    if base.empty:
        return base
    fanout = base.groupby(["access_layer", "conservative_window", "access_point_id"], dropna=False)["stable_bin_id"].nunique().rename("conservative_fanout_count").reset_index()
    base = base.merge(fanout, on=["access_layer", "conservative_window", "access_point_id"], how="left")
    base["conservative_fanout_count"] = pd.to_numeric(base["conservative_fanout_count"], errors="coerce").fillna(1.0)
    base["unweighted_access_count"] = 1.0
    base["source_preserving_weighted_access_count"] = 1.0 / base["conservative_fanout_count"]
    base["assignment_product"] = "conservative_travelway_windowed"
    base["review_only_flag"] = "true"
    return base


def _accepted_outputs(broad: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    accepted = pd.concat(
        [
            _accepted_for_window(broad, "conservative_0_1000"),
            _accepted_for_window(broad, "conservative_0_2500"),
        ],
        ignore_index=True,
        sort=False,
    )
    keep = [
        "access_point_id",
        "access_layer",
        "access_control_category",
        "source_layer",
        "route_name",
        "route_measure",
        "route_key",
        "target_signal_id",
        "target_bin_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_stable_travelway_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "analysis_window",
        "conservative_window",
        "distance_band",
        "assignment_distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "nearest_distance_ft",
        "nearest_distance_band",
        "stable_travelway_assignment_match_class",
        "route_normalized_quality_class",
        "lineage_confidence",
        "overcapture_risk_class",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "speed_aadt_ready_bin",
        "conservative_fanout_count",
        "unweighted_access_count",
        "source_preserving_weighted_access_count",
        "assignment_product",
        "review_only_flag",
    ]
    untyped = accepted.loc[_text(accepted, "access_layer").eq("untyped"), [col for col in keep if col in accepted.columns]].copy()
    typed = accepted.loc[_text(accepted, "access_layer").eq("typed_v2"), [col for col in keep if col in accepted.columns]].copy()
    return untyped, typed


def _window_summary(accepted: pd.DataFrame) -> pd.DataFrame:
    if accepted.empty:
        return pd.DataFrame()
    return accepted.groupby(["access_layer", "conservative_window", "target_signal_id", "analysis_window"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        assignment_count=("access_point_id", "size"),
        unweighted_access_count=("unweighted_access_count", "sum"),
        weighted_access_count=("source_preserving_weighted_access_count", "sum"),
        physical_leg_count=("physical_leg_id", "nunique"),
        carriageway_subbranch_count=("carriageway_subbranch_id", "nunique"),
        final_alignment_class=("final_alignment_class", "first"),
        source_limited_holdout_flag=("source_limited_holdout_flag", "first"),
        grade_mainline_holdout_flag=("grade_mainline_holdout_flag", "first"),
        still_insufficient_evidence_flag=("still_insufficient_evidence_flag", "first"),
    ).reset_index()


def _source_accounting(broad: pd.DataFrame, accepted: pd.DataFrame, denominators: pd.DataFrame, spatial: pd.DataFrame) -> pd.DataFrame:
    broad["rejection_reason"] = _rejection_reason(broad)
    rows = []
    for layer in ["untyped", "typed_v2"]:
        total = int(denominators.loc[denominators["access_layer"].eq(layer), "total_source_points"].iloc[0])
        spatial_layer = spatial.loc[_text(spatial, "access_layer").eq(layer)]
        broad_layer = broad.loc[_text(broad, "access_layer").eq(layer)]
        accepted_layer = accepted.loc[_text(accepted, "access_layer").eq(layer)]
        for window in ["conservative_0_1000", "conservative_0_2500"]:
            acc_win = accepted_layer.loc[_text(accepted_layer, "conservative_window").eq(window)]
            route_family = _text(broad_layer, "route_normalized_quality_class").eq("low_confidence_route_family_only")
            distance_uncertain = _text(broad_layer, "overcapture_risk_class").isin(["route_identity_match_but_distance_uncertain", "manual_review_needed"])
            long_route = _text(broad_layer, "overcapture_risk_class").eq("long_route_overcapture_risk")
            outside_window = (
                _text(broad_layer, "overcapture_risk_class").eq("route_identity_match_but_beyond_signal_window")
                | ~_bool_text(broad_layer, "within_valid_signal_relative_window")
                | ~_text(broad_layer, "analysis_window").isin(["0_1000", "1000_2500"])
            )
            no_direct_or_measure = ~_text(broad_layer, "stable_travelway_assignment_match_class").isin(["direct_stable_travelway_id", "route_measure_overlap"])
            rows.append(
                {
                    "access_layer": layer,
                    "conservative_window": window,
                    "total_source_points": total,
                    "spatial_100ft_captured_source_points": int(_text(spatial_layer, "access_point_id").nunique()),
                    "broad_travelway_captured_source_points": int(_text(broad_layer, "access_point_id").nunique()),
                    "conservative_captured_source_points": int(_text(acc_win, "access_point_id").nunique()),
                    "conservative_assignment_count": int(len(acc_win)),
                    "rejected_route_family_only": int(_text(broad_layer.loc[route_family], "access_point_id").nunique()),
                    "rejected_distance_uncertain": int(_text(broad_layer.loc[distance_uncertain], "access_point_id").nunique()),
                    "rejected_long_route_overcapture_risk": int(_text(broad_layer.loc[long_route], "access_point_id").nunique()),
                    "rejected_outside_signal_window": int(_text(broad_layer.loc[outside_window], "access_point_id").nunique()),
                    "rejected_by_scaffold_qa_flag": int(_text(broad_layer.loc[_blocked_by_qa(broad_layer)], "access_point_id").nunique()),
                    "rejected_no_direct_or_route_measure_match": int(_text(broad_layer.loc[no_direct_or_measure], "access_point_id").nunique()),
                }
            )
    return pd.DataFrame(rows)


def _spatial_vs_conservative(spatial: pd.DataFrame, accepted: pd.DataFrame, denominators: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer in ["untyped", "typed_v2"]:
        total = int(denominators.loc[denominators["access_layer"].eq(layer), "total_source_points"].iloc[0])
        spatial_layer = spatial.loc[_text(spatial, "access_layer").eq(layer)]
        for window in ["conservative_0_1000", "conservative_0_2500"]:
            cons = accepted.loc[_text(accepted, "access_layer").eq(layer) & _text(accepted, "conservative_window").eq(window)]
            spatial_window = "0_1000" if window == "conservative_0_1000" else ""
            sp = spatial_layer.loc[_text(spatial_layer, "analysis_window").eq("0_1000")] if spatial_window else spatial_layer
            sp_points = set(_text(sp, "access_point_id"))
            con_points = set(_text(cons, "access_point_id"))
            sp_signals = set(_text(sp, "target_signal_id"))
            con_signals = set(_text(cons, "target_signal_id"))
            rows.append(
                {
                    "access_layer": layer,
                    "conservative_window": window,
                    "spatial_only_source_points": len(sp_points - con_points),
                    "conservative_only_source_points": len(con_points - sp_points),
                    "both_source_points": len(sp_points & con_points),
                    "neither_source_points": total - len(sp_points | con_points),
                    "spatial_only_signals": len(sp_signals - con_signals),
                    "conservative_only_signals": len(con_signals - sp_signals),
                    "both_signals": len(sp_signals & con_signals),
                    "newly_captured_signals_relative_to_spatial": len(con_signals - sp_signals),
                }
            )
    return pd.DataFrame(rows)


def _rejection_summary(broad: pd.DataFrame) -> pd.DataFrame:
    broad = broad.copy()
    broad["rejection_reason"] = _rejection_reason(broad)
    rejected = broad.loc[_text(broad, "rejection_reason").ne("accepted")]
    return rejected.groupby(["access_layer", "rejection_reason", "stable_travelway_assignment_match_class", "route_normalized_quality_class"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        assignment_count=("access_point_id", "size"),
        signal_count=("target_signal_id", "nunique"),
    ).reset_index().sort_values(["access_layer", "source_point_count"], ascending=[True, False])


def _by_scaffold_qa(accepted: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field in [
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "access_control_category",
        "physical_leg_id",
        "carriageway_subbranch_id",
    ]:
        if field not in accepted.columns:
            continue
        grouped = accepted.groupby(["access_layer", "conservative_window", field], dropna=False).agg(
            source_point_count=("access_point_id", "nunique"),
            assignment_count=("access_point_id", "size"),
            signal_count=("target_signal_id", "nunique"),
            weighted_assignment_total=("source_preserving_weighted_access_count", "sum"),
        ).reset_index().rename(columns={field: "qa_value"})
        grouped["qa_field"] = field
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _qa() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to conservative_travelway_windowed_access."),
            ("no_candidates_promoted", True, "Review-only access test."),
            ("no_crash_records_read", True, "No crash files are required inputs."),
            ("no_crash_direction_fields_read_or_used", True, "Reader blocks crash field tokens."),
            ("no_crash_assignment_or_catchments", True, "No crash assignment/catchment logic."),
            ("no_rates_or_models", True, "Counts and comparisons only."),
            ("typed_and_untyped_separate", True, "Separate output files and access_layer summaries."),
            ("weighted_and_unweighted_separate", True, "Detail rows carry separate unweighted and weighted fields."),
            ("broad_route_family_only_not_accepted", True, "Acceptance requires direct stable ID or route/measure overlap."),
            ("long_route_overcapture_not_accepted", True, "Acceptance excludes long-route overcapture risk."),
            ("source_point_counts_separate", True, "Source accounting separates source-point and assignment counts."),
            ("outputs_review_only", True, "No final metric is chosen."),
        ],
        columns=["qa_check", "passed", "detail"],
    )


def _findings(accounting: pd.DataFrame, comparison: pd.DataFrame, rejection: pd.DataFrame) -> str:
    def acct(layer: str, window: str, field: str) -> int:
        row = accounting.loc[accounting["access_layer"].eq(layer) & accounting["conservative_window"].eq(window)].iloc[0]
        return int(row[field])

    def comp(layer: str, window: str, field: str) -> int:
        row = comparison.loc[comparison["access_layer"].eq(layer) & comparison["conservative_window"].eq(window)].iloc[0]
        return int(row[field])

    def rej(layer: str) -> str:
        sub = (
            rejection.loc[rejection["access_layer"].eq(layer)]
            .groupby("rejection_reason", dropna=False)
            .agg(source_point_count=("source_point_count", "sum"))
            .reset_index()
            .sort_values("source_point_count", ascending=False)
            .head(5)
        )
        return "\n".join(f"- {row.rejection_reason}: {int(row.source_point_count):,} source points" for row in sub.itertuples(index=False))

    return f"""# Conservative Travelway-Windowed Access Findings

## Bounded Question

What access assignment remains if Travelway-normalized access must have source identity plus signal-relative window/distance support?

## Conservative Capture

- Untyped conservative 0-1,000 ft source points: {acct('untyped', 'conservative_0_1000', 'conservative_captured_source_points'):,}
- Untyped conservative 0-2,500 ft source points: {acct('untyped', 'conservative_0_2500', 'conservative_captured_source_points'):,}
- Typed v2 conservative 0-1,000 ft source points: {acct('typed_v2', 'conservative_0_1000', 'conservative_captured_source_points'):,}
- Typed v2 conservative 0-2,500 ft source points: {acct('typed_v2', 'conservative_0_2500', 'conservative_captured_source_points'):,}

## Spatial Comparison

- Untyped signals gained relative to spatial: {comp('untyped', 'conservative_0_1000', 'newly_captured_signals_relative_to_spatial'):,} in 0-1,000 ft; {comp('untyped', 'conservative_0_2500', 'newly_captured_signals_relative_to_spatial'):,} in 0-2,500 ft.
- Typed v2 signals gained relative to spatial: {comp('typed_v2', 'conservative_0_1000', 'newly_captured_signals_relative_to_spatial'):,} in 0-1,000 ft; {comp('typed_v2', 'conservative_0_2500', 'newly_captured_signals_relative_to_spatial'):,} in 0-2,500 ft.

## Rejections From Broad Travelway-Normalized Assignment

Untyped dominant rejection reasons:
{rej('untyped')}

Typed v2 dominant rejection reasons:
{rej('typed_v2')}

## Interpretation

The conservative Travelway-windowed product is a useful complement to spatial access because it preserves stable Travelway source identity and removes the broad long-route overcapture class. It is much smaller than the broad Travelway-normalized assignment and should be treated as a review-only sensitivity product, not a final metric.

## Recommendation

The next access step should compare spatial 100 ft access against conservative Travelway-windowed access by signal/leg and decide whether the crash/catchment design should carry spatial as primary with conservative Travelway-windowed as a source-identity sensitivity. Broad route/family matches should remain source-coverage diagnostics only.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    started = datetime.now(timezone.utc)
    _checkpoint("run_start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    broad = _load_broad_assignments()
    denominators = _read_csv(SANITY_DIR / "access_source_denominator_validation.csv")
    untyped_sp = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_untyped_spatial_assignment_detail.csv")
    typed_sp = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv")
    spatial_100 = pd.concat([untyped_sp, typed_sp], ignore_index=True, sort=False)
    spatial_100 = spatial_100.loc[pd.to_numeric(_text(spatial_100, "buffer_width_ft"), errors="coerce").eq(100)].copy()

    untyped, typed = _accepted_outputs(broad)
    accepted = pd.concat([untyped, typed], ignore_index=True, sort=False)
    signal_summary = _window_summary(accepted)
    accounting = _source_accounting(broad, accepted, denominators, spatial_100)
    comparison = _spatial_vs_conservative(spatial_100, accepted, denominators)
    rejection = _rejection_summary(broad)
    scaffold = _by_scaffold_qa(accepted)
    qa = _qa()

    _write_csv(untyped, "conservative_untyped_travelway_windowed_assignment_detail.csv")
    _write_csv(typed, "conservative_typed_v2_travelway_windowed_assignment_detail.csv")
    _write_csv(signal_summary, "conservative_travelway_windowed_signal_window_summary.csv")
    _write_csv(accounting, "conservative_travelway_windowed_source_point_accounting.csv")
    _write_csv(comparison, "spatial_vs_conservative_travelway_comparison.csv")
    _write_csv(rejection, "broad_travelway_rejection_reason_summary.csv")
    _write_csv(scaffold, "conservative_travelway_access_by_scaffold_qa_summary.csv")
    _write_csv(qa, "conservative_travelway_windowed_access_qa.csv")
    _write_text(_findings(accounting, comparison, rejection), "conservative_travelway_windowed_access_findings.md")

    manifest = {
        "created_at_utc": _now(),
        "started_at_utc": started.isoformat(),
        "script": "src.roadway_graph.conservative_travelway_windowed_access",
        "bounded_question": "Read-only conservative Travelway-windowed access assignment test requiring source identity and signal-relative window support.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "travelway_normalized_access_sanity_audit": str(SANITY_DIR),
            "stable_lineage_final_access_rerun": str(STABLE_ACCESS_DIR),
            "final_signal_leg_universe_overview": str(FINAL_OVERVIEW_DIR),
            "sanity_manifest": _load_json(SANITY_DIR / "travelway_normalized_access_sanity_manifest.json"),
            "stable_access_manifest": _load_json(STABLE_ACCESS_DIR / "stable_lineage_final_access_rerun_manifest.json"),
        },
        "metrics": accounting.to_dict(orient="records"),
        "outputs": [
            "conservative_untyped_travelway_windowed_assignment_detail.csv",
            "conservative_typed_v2_travelway_windowed_assignment_detail.csv",
            "conservative_travelway_windowed_signal_window_summary.csv",
            "conservative_travelway_windowed_source_point_accounting.csv",
            "spatial_vs_conservative_travelway_comparison.csv",
            "broad_travelway_rejection_reason_summary.csv",
            "conservative_travelway_access_by_scaffold_qa_summary.csv",
            "conservative_travelway_windowed_access_findings.md",
            "conservative_travelway_windowed_access_qa.csv",
            "conservative_travelway_windowed_access_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_direction_fields_read": False,
            "crash_assignment_or_catchments": False,
            "rates_or_models": False,
            "final_access_metric_chosen": False,
        },
    }
    _write_json(manifest, "conservative_travelway_windowed_access_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
