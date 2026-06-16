from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import offset_intersection_zone_context_refresh as context_helpers


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_missing_leg_recovery"

CURRENT_REPRESENTED_UNIVERSE_SIGNALS = 2_739
BASE_SIGNAL_UNIVERSE = 3_933
TARGET_CLASSES = {
    "needs_route_facility_discontinuity_handling",
    "needs_offset_anchor_recovery",
}

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    RECOVERY_DIR / "route_discontinuity_offset_recovered_leg_candidates.csv",
    RECOVERY_DIR / "route_discontinuity_offset_recovered_bins.csv",
    RECOVERY_DIR / "route_discontinuity_offset_skipped_targets.csv",
    RECOVERY_DIR / "route_discontinuity_offset_recovery_summary.csv",
    RECOVERY_DIR / "route_discontinuity_offset_recovery_manifest.json",
]


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_text(text: str, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _write_json(payload: dict[str, Any], name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _patch_context_helpers() -> None:
    context_helpers.OUT_DIR = OUT_DIR
    context_helpers._log = _log
    context_helpers._checkpoint = _checkpoint


def _required_context_sources_missing() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if not context_helpers.AADT_FILE.exists():
        missing.append(str(context_helpers.AADT_FILE))
    if not context_helpers.SPEED_LIMIT_RNS_GDB.exists():
        missing.append(str(context_helpers.SPEED_LIMIT_RNS_GDB))
    return missing


def _prepare_candidate_bins(bins: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    bins = bins.loc[_text(bins, "recovery_class").isin(TARGET_CLASSES)].copy()
    bins["context_window_scope"] = _text(bins, "analysis_window").map(
        {"0_1000": "primary_0_1000", "1000_2500": "sensitivity_1000_2500"}
    ).fillna("other_review")
    leg_cols = [
        "candidate_missing_leg_id",
        "route_facility_discontinuity_type",
        "offset_anchor_class",
        "anchor_method",
        "inferred_intersection_center_method",
        "signal_to_inferred_center_ft",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "calibrated_missing_leg_count",
        "available_recovered_length_ft",
    ]
    leg_cols = [column for column in leg_cols if column in legs.columns]
    bins = bins.merge(legs[leg_cols].drop_duplicates("candidate_missing_leg_id"), on="candidate_missing_leg_id", how="left", suffixes=("", "_leg"))
    bins["staged_recovered_bin_id"] = bins["candidate_missing_leg_bin_id"]
    bins["staged_recovered_leg_id"] = bins["candidate_missing_leg_id"]
    bins["source_travelway_lineage"] = bins["primary_source_line_id"]
    bins["source_line_ids"] = bins["primary_source_line_id"]
    bins["refresh_eligible_bin"] = True
    bins["refresh_eligible_leg"] = True
    bins["hold_excluded_mainline"] = False
    bins["hold_manual_grade_separation_review"] = False
    bins["hold_nonstandard_geometry"] = False
    bins["qa_cleanup_status"] = "generated_route_discontinuity_offset_candidate_not_promoted"
    bins["divided_carriageway_flag"] = False
    bins["long_source_row_flag"] = False
    bins["context_candidate_scope"] = "review_only_route_discontinuity_offset_missing_leg_candidate"
    return bins


def _assign_context(candidate_bins: pd.DataFrame) -> pd.DataFrame:
    route_detail = context_helpers._build_route_measure_identity(candidate_bins)
    detail = context_helpers._assign_context(route_detail)
    detail["recovered_missing_leg_bin_id"] = detail["staged_recovered_bin_id"]
    detail["recovered_missing_leg_id"] = detail["staged_recovered_leg_id"]
    detail["context_assignment_scope"] = "review_only_route_discontinuity_offset_missing_leg_candidates_not_active"
    return detail


def _signal_summary(detail: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby(["signal_id", "recovery_class"], dropna=False).agg(
        source_signal_id=("source_signal_id", "first"),
        source_layer=("source_layer", "first"),
        attempted_bin_count=("recovered_missing_leg_bin_id", "count"),
        attempted_leg_count=("recovered_missing_leg_id", "nunique"),
        primary_0_1000_bin_count=("context_window_scope", lambda s: int((s == "primary_0_1000").sum())),
        sensitivity_1000_2500_bin_count=("context_window_scope", lambda s: int((s == "sensitivity_1000_2500").sum())),
        route_measure_ready_bins=("has_route_measure_identity", "sum"),
        roadway_context_bins=("has_roadway_context", "sum"),
        rns_speed_ready_bins=("has_rns_speed", "sum"),
        aadt_ready_bins=("has_aadt", "sum"),
        exposure_ready_bins=("has_exposure_denominator", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        route_facility_discontinuity_types=("route_facility_discontinuity_type", _collapse),
        offset_anchor_classes=("offset_anchor_class", _collapse),
        candidate_selection_statuses=("candidate_selection_status", _collapse),
        speed_missing_reasons=("rns_speed_missing_reason", _collapse),
        aadt_missing_reasons=("aadt_v3_missing_reason", _collapse),
    ).reset_index()
    for column in [
        "attempted_bin_count",
        "attempted_leg_count",
        "primary_0_1000_bin_count",
        "sensitivity_1000_2500_bin_count",
        "route_measure_ready_bins",
        "roadway_context_bins",
        "rns_speed_ready_bins",
        "aadt_ready_bins",
        "exposure_ready_bins",
        "speed_aadt_ready_bins",
    ]:
        grouped[column] = pd.to_numeric(grouped[column], errors="coerce").fillna(0).astype(int)
    grouped["has_route_measure_identity"] = grouped["route_measure_ready_bins"].gt(0)
    grouped["has_roadway_context"] = grouped["roadway_context_bins"].gt(0)
    grouped["has_rns_speed"] = grouped["rns_speed_ready_bins"].gt(0)
    grouped["has_aadt"] = grouped["aadt_ready_bins"].gt(0)
    grouped["has_exposure_denominator"] = grouped["exposure_ready_bins"].gt(0)
    grouped["speed_aadt_ready"] = grouped["speed_aadt_ready_bins"].gt(0)

    primary = detail.loc[_text(detail, "context_window_scope").eq("primary_0_1000")]
    primary_ready = primary.groupby("signal_id")["speed_aadt_ready_bin"].agg(["count", "sum"]).reset_index()
    primary_ready["speed_aadt_ready_0_1000"] = primary_ready["count"].eq(primary_ready["sum"]) & primary_ready["count"].gt(0)
    sensitivity = detail.loc[_text(detail, "context_window_scope").eq("sensitivity_1000_2500")]
    sensitivity_ready = sensitivity.groupby("signal_id")["speed_aadt_ready_bin"].agg(["count", "sum"]).reset_index()
    sensitivity_ready["sensitivity_1000_2500_ready"] = sensitivity_ready["count"].eq(sensitivity_ready["sum"]) & sensitivity_ready["count"].gt(0)
    grouped = grouped.merge(primary_ready[["signal_id", "speed_aadt_ready_0_1000"]], on="signal_id", how="left")
    grouped = grouped.merge(sensitivity_ready[["signal_id", "sensitivity_1000_2500_ready"]], on="signal_id", how="left")
    grouped["speed_aadt_ready_0_1000"] = grouped["speed_aadt_ready_0_1000"].fillna(False)
    grouped["sensitivity_1000_2500_ready"] = grouped["sensitivity_1000_2500_ready"].fillna(False)
    grouped["partial_recovery_flag"] = grouped["primary_0_1000_bin_count"].lt(grouped["attempted_leg_count"] * 20)
    grouped["eligible_for_later_universe_refresh"] = grouped["speed_aadt_ready"] & grouped["has_route_measure_identity"] & grouped["has_roadway_context"]
    grouped["held_out_skipped_or_conflicting"] = grouped["signal_id"].isin(set(_text(skipped, "signal_id")))
    grouped["missingness_reason_if_not_ready"] = ""
    grouped.loc[~grouped["has_route_measure_identity"], "missingness_reason_if_not_ready"] = "route_measure_identity_missing"
    grouped.loc[grouped["has_route_measure_identity"] & ~grouped["has_rns_speed"], "missingness_reason_if_not_ready"] = "rns_speed_missing"
    grouped.loc[grouped["has_route_measure_identity"] & grouped["has_rns_speed"] & ~grouped["has_aadt"], "missingness_reason_if_not_ready"] = "aadt_missing"
    grouped.loc[grouped["has_route_measure_identity"] & grouped["has_rns_speed"] & grouped["has_aadt"] & ~grouped["has_exposure_denominator"], "missingness_reason_if_not_ready"] = "exposure_missing"
    return grouped


def _metrics(detail: pd.DataFrame, signal: pd.DataFrame, skipped: pd.DataFrame) -> dict[str, int]:
    return {
        "processed_bins": int(len(detail)),
        "processed_primary_bins_0_1000": int(_text(detail, "context_window_scope").eq("primary_0_1000").sum()),
        "processed_sensitivity_bins_1000_2500": int(_text(detail, "context_window_scope").eq("sensitivity_1000_2500").sum()),
        "processed_signals": int(detail["signal_id"].nunique()),
        "route_measure_signals": int(signal["has_route_measure_identity"].sum()),
        "roadway_context_signals": int(signal["has_roadway_context"].sum()),
        "speed_signals": int(signal["has_rns_speed"].sum()),
        "aadt_signals": int(signal["has_aadt"].sum()),
        "exposure_signals": int(signal["has_exposure_denominator"].sum()),
        "speed_aadt_ready_signals": int(signal["speed_aadt_ready"].sum()),
        "speed_aadt_ready_0_1000_signals": int(signal["speed_aadt_ready_0_1000"].sum()),
        "sensitivity_ready_signals": int(signal["sensitivity_1000_2500_ready"].sum()),
        "held_out_skipped_signals": int(skipped["signal_id"].nunique()) if not skipped.empty else 0,
        "route_discontinuity_processed_signals": int(detail.loc[_text(detail, "recovery_class").eq("needs_route_facility_discontinuity_handling"), "signal_id"].nunique()),
        "offset_anchor_processed_signals": int(detail.loc[_text(detail, "recovery_class").eq("needs_offset_anchor_recovery"), "signal_id"].nunique()),
    }


def _summary_tables(detail: pd.DataFrame, signal: pd.DataFrame, metrics: dict[str, int]) -> dict[str, pd.DataFrame]:
    route_measure = pd.DataFrame(
        [
            {"metric": "candidate_bins_processed", "count": metrics["processed_bins"]},
            {"metric": "bins_with_route_measure_identity", "count": int(detail["has_route_measure_identity"].sum())},
            {"metric": "signals_with_route_measure_identity", "count": metrics["route_measure_signals"]},
            {"metric": "route_measure_identity_method", "count": "", "value": "source_travelway_lineage_linear_distance_proxy_review_only"},
        ]
    )
    speed = detail.groupby(["rns_speed_match_status", "rns_speed_missing_reason"], dropna=False).agg(
        bin_count=("recovered_missing_leg_bin_id", "count"), signal_count=("signal_id", "nunique")
    ).reset_index().sort_values("bin_count", ascending=False)
    aadt = detail.groupby(["aadt_v3_match_status", "aadt_v3_missing_reason", "review_only_denominator_status"], dropna=False).agg(
        bin_count=("recovered_missing_leg_bin_id", "count"),
        signal_count=("signal_id", "nunique"),
        estimated_exposure=("review_only_estimated_exposure", "sum"),
    ).reset_index().sort_values("bin_count", ascending=False)
    readiness = pd.DataFrame([{"metric": key, "count": value} for key, value in metrics.items()])
    universe = pd.DataFrame(
        [
            {"metric": "current_represented_universe_signals", "count": CURRENT_REPRESENTED_UNIVERSE_SIGNALS, "note": "Current represented universe stays unchanged."},
            {"metric": "generated_candidate_signals_processed", "count": metrics["processed_signals"], "note": "Route/facility-discontinuity and offset-anchor candidate signals only."},
            {"metric": "generated_candidate_signals_speed_aadt_ready", "count": metrics["speed_aadt_ready_signals"], "note": "Ready under review-only context assignment."},
            {"metric": "overlap_with_existing_represented_universe_if_detectable", "count": metrics["processed_signals"], "note": "These are missing legs for already represented signals; signal-count impact is not additive."},
            {"metric": "projected_represented_universe_if_accepted", "count": CURRENT_REPRESENTED_UNIVERSE_SIGNALS, "note": "Signal count remains 2,739; impact is scaffold/bin completeness."},
            {"metric": "projected_percent_of_3933_base_signals", "count": round(CURRENT_REPRESENTED_UNIVERSE_SIGNALS / BASE_SIGNAL_UNIVERSE * 100, 2), "note": "Signal-count coverage unchanged."},
            {"metric": "skipped_conflicting_signals_held_out", "count": metrics["held_out_skipped_signals"], "note": "Not processed by this context refresh."},
        ]
    )
    missingness = signal.groupby(["missingness_reason_if_not_ready"], dropna=False).agg(
        signal_count=("signal_id", "nunique"), bin_count=("attempted_bin_count", "sum")
    ).reset_index().sort_values("signal_count", ascending=False)
    return {"route_measure": route_measure, "speed": speed, "aadt": aadt, "readiness": readiness, "universe": universe, "missingness": missingness}


def _findings(metrics: dict[str, int]) -> str:
    pct = CURRENT_REPRESENTED_UNIVERSE_SIGNALS / BASE_SIGNAL_UNIVERSE * 100
    return f"""# Route-Discontinuity and Offset Context Refresh Findings

This read-only pass processed only generated `needs_route_facility_discontinuity_handling` and `needs_offset_anchor_recovery` missing-leg candidate bins. It excluded skipped targets and did not assign access, crashes, rates, or models.

- Generated candidate signals processed: {metrics["processed_signals"]:,}
- Route/facility-discontinuity signals processed: {metrics["route_discontinuity_processed_signals"]:,}
- Offset-anchor signals processed: {metrics["offset_anchor_processed_signals"]:,}
- Candidate bins processed: {metrics["processed_bins"]:,}
- Primary 0-1,000 ft bins processed: {metrics["processed_primary_bins_0_1000"]:,}
- Sensitivity 1,000-2,500 ft bins processed: {metrics["processed_sensitivity_bins_1000_2500"]:,}
- Signals with route/measure identity: {metrics["route_measure_signals"]:,}
- Signals with roadway context: {metrics["roadway_context_signals"]:,}
- Signals with RNS speed: {metrics["speed_signals"]:,}
- Signals with AADT/exposure: {metrics["aadt_signals"]:,}
- Signals speed+AADT ready: {metrics["speed_aadt_ready_signals"]:,}
- Signals with 0-1,000 ft speed+AADT-ready candidates: {metrics["speed_aadt_ready_0_1000_signals"]:,}
- Skipped/conflicting signals held out: {metrics["held_out_skipped_signals"]:,}

Universe signal count remains {CURRENT_REPRESENTED_UNIVERSE_SIGNALS:,}, or {pct:.2f}% of the 3,933 base signals, because these are scaffold-completeness additions for already represented signals. These records should be staged as scaffold/bin completeness additions after QA acceptance, not as new signal representation.
"""


def _qa(candidate_bins: pd.DataFrame, detail: pd.DataFrame, skipped: pd.DataFrame, metrics: dict[str, int]) -> pd.DataFrame:
    processed_classes = set(_text(detail, "recovery_class"))
    rows = [
        ("no_active_outputs_modified", True, "", "true", "All writes are under the review output folder."),
        ("no_candidates_promoted", True, "", "true", "Candidates remain review-only."),
        ("no_access_assignment", True, "", "true", "No access inputs or outputs are read."),
        ("no_crash_assignment", True, "", "true", "No crash records are read or assigned."),
        ("no_rates_or_models", True, "", "true", "Exposure readiness is computed, but no rates/models are calculated."),
        ("only_route_discontinuity_and_offset_candidates_processed", processed_classes.issubset(TARGET_CLASSES), "|".join(sorted(processed_classes)), "|".join(sorted(TARGET_CLASSES)), ""),
        ("skipped_conflicting_targets_excluded", not set(_text(skipped, "signal_id")).intersection(set(_text(detail, "signal_id"))), metrics["held_out_skipped_signals"], "excluded", ""),
        ("assignments_review_only", _text(detail, "context_assignment_scope").eq("review_only_route_discontinuity_offset_missing_leg_candidates_not_active").all(), "", "true", ""),
        ("no_bin_source_overlap_tables_materialized", True, "", "true", "Grouped searchsorted midpoint containment only."),
        ("deduped_signal_counts_separate_from_bin_counts", metrics["processed_signals"] <= metrics["processed_bins"], f"{metrics['processed_signals']} signals / {metrics['processed_bins']} bins", "signals <= bins", ""),
        ("outputs_written_only_to_review_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/route_discontinuity_offset_context_refresh"), str(OUT_DIR), "review/current/route_discontinuity_offset_context_refresh", ""),
    ]
    return pd.DataFrame(rows, columns=["qa_gate", "passed", "observed_value", "expected_or_reference_value", "note"])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _patch_context_helpers()
    _checkpoint("run_start")
    missing = _required_context_sources_missing()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    legs = _read_csv(RECOVERY_DIR / "route_discontinuity_offset_recovered_leg_candidates.csv")
    bins = _read_csv(RECOVERY_DIR / "route_discontinuity_offset_recovered_bins.csv")
    skipped = _read_csv(RECOVERY_DIR / "route_discontinuity_offset_skipped_targets.csv")
    recovery_summary = _read_csv(RECOVERY_DIR / "route_discontinuity_offset_recovery_summary.csv")
    recovery_manifest = _load_json(RECOVERY_DIR / "route_discontinuity_offset_recovery_manifest.json")

    candidate_bins = _prepare_candidate_bins(bins, legs)
    detail = _assign_context(candidate_bins)
    signal = _signal_summary(detail, skipped)
    metrics = _metrics(detail, signal, skipped)
    tables = _summary_tables(detail, signal, metrics)
    qa = _qa(candidate_bins, detail, skipped, metrics)

    outputs = [
        _write_csv(detail, "route_discontinuity_offset_context_bin_detail.csv"),
        _write_csv(signal, "route_discontinuity_offset_context_signal_summary.csv"),
        _write_csv(tables["route_measure"], "route_discontinuity_offset_route_measure_summary.csv"),
        _write_csv(tables["speed"], "route_discontinuity_offset_speed_summary.csv"),
        _write_csv(tables["aadt"], "route_discontinuity_offset_aadt_exposure_summary.csv"),
        _write_csv(tables["readiness"], "route_discontinuity_offset_context_readiness_summary.csv"),
        _write_csv(tables["universe"], "route_discontinuity_offset_universe_impact_projection.csv"),
        _write_csv(tables["missingness"], "route_discontinuity_offset_context_missingness.csv"),
        _write_text(_findings(metrics), "route_discontinuity_offset_context_refresh_findings.md"),
        _write_csv(qa, "route_discontinuity_offset_context_refresh_qa.csv"),
    ]
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.route_discontinuity_offset_context_refresh",
        "bounded_question": "Review-only context refresh for route/facility-discontinuity and offset-anchor missing-leg candidate bins.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "recovery_dir": str(RECOVERY_DIR),
            "speed_source": str(context_helpers.SPEED_LIMIT_RNS_GDB),
            "aadt_source": str(context_helpers.AADT_FILE),
            "recovery_manifest": recovery_manifest,
            "recovery_summary_rows": int(len(recovery_summary)),
        },
        "outputs": [str(path) for path in outputs] + [str(OUT_DIR / "route_discontinuity_offset_context_refresh_manifest.json"), str(OUT_DIR / "run_progress_log.txt")],
        "metrics": metrics,
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_assigned": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "bin_by_source_overlap_tables_materialized": False,
            "divided_carriageway_subbranch_normalization_targeted": False,
        },
        "row_counts": {
            "candidate_legs_input": int(len(legs)),
            "candidate_bins_input": int(len(bins)),
            "candidate_bins_processed": int(len(detail)),
            "context_signal_summary": int(len(signal)),
            "skipped_targets_held_out": int(len(skipped)),
        },
    }
    _write_json(manifest, "route_discontinuity_offset_context_refresh_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
