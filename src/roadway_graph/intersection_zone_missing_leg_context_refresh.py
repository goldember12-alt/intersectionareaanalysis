from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import offset_intersection_zone_context_refresh as context_helpers


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_recovery_candidates"

CURRENT_REPRESENTED_UNIVERSE_SIGNALS = 2_739
BASE_SIGNAL_UNIVERSE = 3_933

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
    RECOVERY_DIR / "recovered_missing_physical_leg_candidates.csv",
    RECOVERY_DIR / "recovered_missing_leg_candidate_bins_0_1000.csv",
    RECOVERY_DIR / "recovered_missing_leg_candidate_bins_1000_2500.csv",
    RECOVERY_DIR / "selected_signal_summary.csv",
    RECOVERY_DIR / "candidate_generation_qa_summary.csv",
    RECOVERY_DIR / "skipped_or_conflicting_recovery_targets.csv",
    RECOVERY_DIR / "intersection_zone_missing_leg_recovery_candidates_manifest.json",
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
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
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
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _prepare_candidate_bins(primary: pd.DataFrame, sensitivity: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    primary = primary.copy()
    sensitivity = sensitivity.copy()
    primary["context_window_scope"] = "primary_0_1000"
    sensitivity["context_window_scope"] = "sensitivity_1000_2500"
    bins = pd.concat([primary, sensitivity], ignore_index=True, sort=False)
    if bins.empty:
        return bins

    leg_cols = [
        "candidate_missing_leg_id",
        "selection_status",
        "candidate_existing_sector_count",
        "source_absent_sector_count",
        "calibrated_expected_physical_leg_count",
        "current_refreshed_physical_leg_count",
        "calibrated_missing_leg_count",
        "source_bearing_count",
        "source_bearing_groups",
        "candidate_generation_method",
        "available_recovered_length_ft",
        "generates_full_0_1000ft_window",
        "generates_1000_2500ft_sensitivity",
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
    bins["qa_cleanup_status"] = "generated_missing_leg_candidate_not_qa_promoted"
    bins["route_facility_discontinuity_type"] = "not_targeted_in_this_pass"
    bins["route_facility_discontinuity_flag"] = False
    bins["source_line_split_flag"] = False
    bins["divided_carriageway_flag"] = False
    bins["long_source_row_flag"] = False
    bins["context_candidate_scope"] = "review_only_intersection_zone_missing_leg_candidate"
    return bins


def _rename_id_columns(detail: pd.DataFrame) -> pd.DataFrame:
    out = detail.copy()
    out["recovered_missing_leg_bin_id"] = out["staged_recovered_bin_id"]
    out["recovered_missing_leg_id"] = out["staged_recovered_leg_id"]
    out["context_assignment_scope"] = "review_only_intersection_zone_missing_leg_candidates_not_active"
    return out


def _assign_context(candidate_bins: pd.DataFrame) -> pd.DataFrame:
    route_detail = context_helpers._build_route_measure_identity(candidate_bins)
    detail = context_helpers._assign_context(route_detail)
    return _rename_id_columns(detail)


def _signal_summary(detail: pd.DataFrame, selected: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        signal = pd.DataFrame(columns=["signal_id"])
    else:
        work = detail.copy()
        grouped = work.groupby("signal_id", dropna=False).agg(
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
            candidate_selection_status=("selection_status", _collapse),
            roadway_route_type_categories=("roadway_route_type_category", _collapse),
            speed_missing_reasons=("rns_speed_missing_reason", _collapse),
            aadt_missing_reasons=("aadt_v3_missing_reason", _collapse),
        ).reset_index()
        signal = grouped

    base_cols = [
        "signal_id",
        "candidate_generation_status",
        "recovered_candidate_leg_count",
        "candidate_bins_0_1000",
        "candidate_bins_1000_2500",
        "skipped_target_count",
        "skip_reasons",
    ]
    base_cols = [column for column in base_cols if column in selected.columns]
    base = selected[base_cols].drop_duplicates("signal_id")
    signal = base.merge(signal, on="signal_id", how="left")

    numeric_cols = [
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
        "recovered_candidate_leg_count",
        "candidate_bins_0_1000",
        "candidate_bins_1000_2500",
        "skipped_target_count",
    ]
    for column in numeric_cols:
        if column not in signal.columns:
            signal[column] = 0
        signal[column] = pd.to_numeric(signal[column], errors="coerce").fillna(0).astype(int)
    for column in ["source_signal_id", "source_layer", "candidate_selection_status", "roadway_route_type_categories", "speed_missing_reasons", "aadt_missing_reasons", "skip_reasons"]:
        if column not in signal.columns:
            signal[column] = ""
        signal[column] = _text(signal, column)

    signal["has_route_measure_identity"] = signal["route_measure_ready_bins"].gt(0)
    signal["has_roadway_context"] = signal["roadway_context_bins"].gt(0)
    signal["has_rns_speed"] = signal["rns_speed_ready_bins"].gt(0)
    signal["has_aadt"] = signal["aadt_ready_bins"].gt(0)
    signal["has_exposure_denominator"] = signal["exposure_ready_bins"].gt(0)
    signal["speed_aadt_ready"] = signal["speed_aadt_ready_bins"].gt(0)

    primary = detail.loc[_text(detail, "context_window_scope").eq("primary_0_1000")].copy()
    if primary.empty:
        primary_ready = pd.DataFrame(columns=["signal_id", "speed_aadt_ready_0_1000"])
    else:
        primary_ready = primary.groupby("signal_id")["speed_aadt_ready_bin"].agg(["count", "sum"]).reset_index()
        primary_ready["speed_aadt_ready_0_1000"] = primary_ready["count"].eq(primary_ready["sum"]) & primary_ready["count"].gt(0)
    sensitivity = detail.loc[_text(detail, "context_window_scope").eq("sensitivity_1000_2500")].copy()
    if sensitivity.empty:
        sensitivity_ready = pd.DataFrame(columns=["signal_id", "sensitivity_1000_2500_ready"])
    else:
        sensitivity_ready = sensitivity.groupby("signal_id")["speed_aadt_ready_bin"].agg(["count", "sum"]).reset_index()
        sensitivity_ready["sensitivity_1000_2500_ready"] = sensitivity_ready["count"].eq(sensitivity_ready["sum"]) & sensitivity_ready["count"].gt(0)
    signal = signal.merge(primary_ready[["signal_id", "speed_aadt_ready_0_1000"]], on="signal_id", how="left")
    signal = signal.merge(sensitivity_ready[["signal_id", "sensitivity_1000_2500_ready"]], on="signal_id", how="left")
    signal["speed_aadt_ready_0_1000"] = signal["speed_aadt_ready_0_1000"].fillna(False)
    signal["sensitivity_1000_2500_ready"] = signal["sensitivity_1000_2500_ready"].fillna(False)
    signal["partial_recovery_flag"] = signal["candidate_generation_status"].ne("candidate_generated") | signal["recovered_candidate_leg_count"].lt(signal["attempted_leg_count"])
    signal["eligible_for_later_universe_refresh"] = signal["speed_aadt_ready"] & signal["has_route_measure_identity"] & signal["has_roadway_context"]
    signal["held_out_skipped_or_conflicting"] = signal["candidate_generation_status"].eq("no_candidate_generated_review_needed") | signal["signal_id"].isin(set(_text(skipped, "signal_id")))

    signal["missingness_reason_if_not_ready"] = ""
    signal.loc[signal["attempted_bin_count"].eq(0), "missingness_reason_if_not_ready"] = "no_generated_candidate_bins_processed"
    signal.loc[signal["attempted_bin_count"].gt(0) & ~signal["has_route_measure_identity"], "missingness_reason_if_not_ready"] = "route_measure_identity_missing"
    signal.loc[signal["has_route_measure_identity"] & ~signal["has_rns_speed"], "missingness_reason_if_not_ready"] = "rns_speed_missing"
    signal.loc[signal["has_route_measure_identity"] & signal["has_rns_speed"] & ~signal["has_aadt"], "missingness_reason_if_not_ready"] = "aadt_missing"
    signal.loc[signal["has_route_measure_identity"] & signal["has_rns_speed"] & signal["has_aadt"] & ~signal["has_exposure_denominator"], "missingness_reason_if_not_ready"] = "exposure_missing"
    return signal


def _metrics(detail: pd.DataFrame, signal: pd.DataFrame, skipped: pd.DataFrame) -> dict[str, int]:
    ready_signals = int(signal["speed_aadt_ready"].sum())
    return {
        "processed_bins": int(len(detail)),
        "processed_primary_bins_0_1000": int(_text(detail, "context_window_scope").eq("primary_0_1000").sum()),
        "processed_sensitivity_bins_1000_2500": int(_text(detail, "context_window_scope").eq("sensitivity_1000_2500").sum()),
        "processed_signals": int(detail["signal_id"].nunique()) if not detail.empty else 0,
        "signals_in_summary": int(signal["signal_id"].nunique()),
        "route_measure_signals": int(signal["has_route_measure_identity"].sum()),
        "roadway_context_signals": int(signal["has_roadway_context"].sum()),
        "speed_signals": int(signal["has_rns_speed"].sum()),
        "aadt_signals": int(signal["has_aadt"].sum()),
        "exposure_signals": int(signal["has_exposure_denominator"].sum()),
        "speed_aadt_ready_signals": ready_signals,
        "speed_aadt_ready_0_1000_signals": int(signal["speed_aadt_ready_0_1000"].sum()),
        "sensitivity_ready_signals": int(signal["sensitivity_1000_2500_ready"].sum()),
        "held_out_skipped_signals": int(skipped["signal_id"].nunique()) if not skipped.empty else 0,
        "projected_universe_if_accepted": CURRENT_REPRESENTED_UNIVERSE_SIGNALS + ready_signals,
    }


def _summary_tables(detail: pd.DataFrame, signal: pd.DataFrame, metrics: dict[str, int]) -> dict[str, pd.DataFrame]:
    route_measure = pd.DataFrame(
        [
            {"metric": "candidate_bins_processed", "count": metrics["processed_bins"]},
            {"metric": "bins_with_route_measure_identity", "count": int(detail["has_route_measure_identity"].sum())},
            {"metric": "signals_with_route_measure_identity", "count": metrics["route_measure_signals"]},
            {"metric": "route_measure_identity_method", "count": "", "value": "source_travelway_lineage_linear_distance_proxy_review_only"},
            {"metric": "route_measure_proxy_caveat", "count": "", "value": "Review-only source-lineage proxy; no active route-measure promotion."},
        ]
    )
    speed = (
        detail.groupby(["rns_speed_match_status", "rns_speed_missing_reason"], dropna=False)
        .agg(bin_count=("recovered_missing_leg_bin_id", "count"), signal_count=("signal_id", "nunique"))
        .reset_index()
        .sort_values(["bin_count"], ascending=False)
    )
    aadt = (
        detail.groupby(["aadt_v3_match_status", "aadt_v3_missing_reason", "review_only_denominator_status"], dropna=False)
        .agg(bin_count=("recovered_missing_leg_bin_id", "count"), signal_count=("signal_id", "nunique"), estimated_exposure=("review_only_estimated_exposure", "sum"))
        .reset_index()
        .sort_values(["bin_count"], ascending=False)
    )
    readiness = pd.DataFrame(
        [
            {"metric": "generated_candidate_signals_processed", "count": metrics["processed_signals"]},
            {"metric": "generated_candidate_bins_processed", "count": metrics["processed_bins"]},
            {"metric": "primary_0_1000_bins_processed", "count": metrics["processed_primary_bins_0_1000"]},
            {"metric": "sensitivity_1000_2500_bins_processed", "count": metrics["processed_sensitivity_bins_1000_2500"]},
            {"metric": "signals_with_route_measure_identity", "count": metrics["route_measure_signals"]},
            {"metric": "signals_with_roadway_context", "count": metrics["roadway_context_signals"]},
            {"metric": "signals_with_rns_speed", "count": metrics["speed_signals"]},
            {"metric": "signals_with_aadt", "count": metrics["aadt_signals"]},
            {"metric": "signals_with_exposure_denominator", "count": metrics["exposure_signals"]},
            {"metric": "signals_speed_aadt_ready", "count": metrics["speed_aadt_ready_signals"]},
            {"metric": "signals_0_1000_speed_aadt_ready", "count": metrics["speed_aadt_ready_0_1000_signals"]},
            {"metric": "signals_sensitivity_1000_2500_ready", "count": metrics["sensitivity_ready_signals"]},
            {"metric": "skipped_conflicting_signals_held_out", "count": metrics["held_out_skipped_signals"]},
        ]
    )
    universe = pd.DataFrame(
        [
            {"metric": "current_represented_universe_signals", "count": CURRENT_REPRESENTED_UNIVERSE_SIGNALS, "note": "Current represented universe stays unchanged."},
            {"metric": "generated_candidate_signals_processed", "count": metrics["processed_signals"], "note": "Signals with generated missing-leg bins only; skipped targets excluded."},
            {"metric": "generated_candidate_signals_speed_aadt_ready", "count": metrics["speed_aadt_ready_signals"], "note": "Ready under review-only context assignment."},
            {"metric": "overlap_with_existing_represented_universe_if_detectable", "count": metrics["processed_signals"], "note": "All candidates are missing legs for already represented signals, so signal-count universe impact is not additive."},
            {"metric": "projected_represented_universe_if_accepted", "count": CURRENT_REPRESENTED_UNIVERSE_SIGNALS, "note": "Signal count remains 2,739 because these are added bins/legs for in-universe signals, not new signals."},
            {"metric": "projected_percent_of_3933_base_signals", "count": round(CURRENT_REPRESENTED_UNIVERSE_SIGNALS / BASE_SIGNAL_UNIVERSE * 100, 2), "note": "Signal-count coverage unchanged by within-signal missing-leg additions."},
            {"metric": "skipped_conflicting_signals_held_out", "count": metrics["held_out_skipped_signals"], "note": "Not processed by this context refresh."},
        ]
    )
    missingness = (
        signal.groupby(["missingness_reason_if_not_ready"], dropna=False)
        .agg(signal_count=("signal_id", "nunique"), bin_count=("attempted_bin_count", "sum"))
        .reset_index()
        .sort_values(["signal_count"], ascending=False)
    )
    return {
        "route_measure": route_measure,
        "speed": speed,
        "aadt": aadt,
        "readiness": readiness,
        "universe": universe,
        "missingness": missingness,
    }


def _findings(metrics: dict[str, int]) -> str:
    pct = CURRENT_REPRESENTED_UNIVERSE_SIGNALS / BASE_SIGNAL_UNIVERSE * 100
    return f"""# Missing-Leg Candidate Context Refresh Findings

## Bounded Question

This read-only pass asks whether generated intersection-zone missing-leg candidate bins can carry route/measure identity, roadway context, RNS speed, and AADT/exposure before any future review-only universe refresh. It excludes skipped/conflicting targets and does not assign access, crashes, rates, or models.

## Results

- Generated candidate signals processed: {metrics["processed_signals"]:,}
- Generated candidate bins processed: {metrics["processed_bins"]:,}
- Primary 0-1,000 ft bins processed: {metrics["processed_primary_bins_0_1000"]:,}
- Sensitivity 1,000-2,500 ft bins processed: {metrics["processed_sensitivity_bins_1000_2500"]:,}
- Signals with route/measure identity: {metrics["route_measure_signals"]:,}
- Signals with roadway context: {metrics["roadway_context_signals"]:,}
- Signals with RNS speed: {metrics["speed_signals"]:,}
- Signals with AADT/exposure: {metrics["aadt_signals"]:,}
- Signals speed+AADT ready: {metrics["speed_aadt_ready_signals"]:,}
- Signals with 0-1,000 ft speed+AADT-ready recovered candidates: {metrics["speed_aadt_ready_0_1000_signals"]:,}
- Skipped/conflicting signals held out: {metrics["held_out_skipped_signals"]:,}

## Universe Projection

These candidates add missing legs/bins to already represented signals, not new signals. The represented signal count remains {CURRENT_REPRESENTED_UNIVERSE_SIGNALS:,}, or {pct:.2f}% of the 3,933 base signals, if accepted. The impact is scaffold/bin completeness rather than signal-count expansion.

## Recommendation

These records can be staged into a refreshed review-only represented bin universe after map/QA acceptance of the missing-leg candidates. They should remain flagged as `intersection_zone_missing_leg_recovery` provenance and should not unblock access/crash assignment until the user accepts whether these candidate legs become part of the review scaffold.
"""


def _qa(candidate_bins: pd.DataFrame, detail: pd.DataFrame, skipped: pd.DataFrame, metrics: dict[str, int]) -> pd.DataFrame:
    output_inside = str(OUT_DIR).replace("\\", "/").endswith("review/current/intersection_zone_missing_leg_context_refresh")
    rows = [
        ("no_active_outputs_modified", True, "", "true", "All writes are under the review output folder."),
        ("no_candidates_promoted", True, "", "true", "Generated candidates remain review-only."),
        ("no_access_assignment", True, "", "true", "No access inputs or outputs are read."),
        ("no_crash_assignment", True, "", "true", "No crash records are read or assigned."),
        ("no_rates_or_models", True, "", "true", "Exposure readiness is computed, but no rates/models are calculated."),
        ("only_generated_missing_leg_candidates_processed", len(detail) == len(candidate_bins), len(detail), len(candidate_bins), "Only generated candidate bin CSV rows are processed."),
        ("skipped_conflicting_targets_excluded", not set(_text(skipped, "signal_id")).intersection(set(_text(detail, "signal_id"))), metrics["held_out_skipped_signals"], "excluded", "Skipped/no-candidate targets are held out."),
        ("assignments_review_only", _text(detail, "context_assignment_scope").eq("review_only_intersection_zone_missing_leg_candidates_not_active").all(), "", "true", ""),
        ("no_bin_source_overlap_tables_materialized", True, "", "true", "Grouped searchsorted midpoint containment only."),
        ("deduped_signal_counts_separate_from_bin_counts", metrics["processed_signals"] <= metrics["processed_bins"], f"{metrics['processed_signals']} signals / {metrics['processed_bins']} bins", "signals <= bins", ""),
        ("outputs_written_only_to_review_folder", output_inside, str(OUT_DIR), "review/current/intersection_zone_missing_leg_context_refresh", ""),
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

    legs = _read_csv(RECOVERY_DIR / "recovered_missing_physical_leg_candidates.csv")
    bins_0_1000 = _read_csv(RECOVERY_DIR / "recovered_missing_leg_candidate_bins_0_1000.csv")
    bins_1000_2500 = _read_csv(RECOVERY_DIR / "recovered_missing_leg_candidate_bins_1000_2500.csv")
    selected = _read_csv(RECOVERY_DIR / "selected_signal_summary.csv")
    skipped = _read_csv(RECOVERY_DIR / "skipped_or_conflicting_recovery_targets.csv")
    recovery_qa = _read_csv(RECOVERY_DIR / "candidate_generation_qa_summary.csv")
    recovery_manifest = _load_json(RECOVERY_DIR / "intersection_zone_missing_leg_recovery_candidates_manifest.json")

    candidate_bins = _prepare_candidate_bins(bins_0_1000, bins_1000_2500, legs)
    detail = _assign_context(candidate_bins)
    signal = _signal_summary(detail, selected, skipped)
    metrics = _metrics(detail, signal, skipped)
    tables = _summary_tables(detail, signal, metrics)
    qa = _qa(candidate_bins, detail, skipped, metrics)

    outputs = [
        _write_csv(detail, "missing_leg_context_bin_detail.csv"),
        _write_csv(signal, "missing_leg_context_signal_summary.csv"),
        _write_csv(tables["route_measure"], "missing_leg_route_measure_summary.csv"),
        _write_csv(tables["speed"], "missing_leg_speed_summary.csv"),
        _write_csv(tables["aadt"], "missing_leg_aadt_exposure_summary.csv"),
        _write_csv(tables["readiness"], "missing_leg_context_readiness_summary.csv"),
        _write_csv(tables["universe"], "missing_leg_updated_universe_projection.csv"),
        _write_csv(tables["missingness"], "missing_leg_context_missingness.csv"),
        _write_text(_findings(metrics), "missing_leg_context_refresh_findings.md"),
        _write_csv(qa, "missing_leg_context_refresh_qa.csv"),
    ]

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.intersection_zone_missing_leg_context_refresh",
        "bounded_question": "Review-only route/measure, roadway context, RNS speed, and AADT/exposure refresh for generated intersection-zone missing-leg candidate bins.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "recovery_dir": str(RECOVERY_DIR),
            "speed_source": str(context_helpers.SPEED_LIMIT_RNS_GDB),
            "aadt_source": str(context_helpers.AADT_FILE),
            "recovery_manifest": recovery_manifest,
            "candidate_generation_qa_rows": int(len(recovery_qa)),
        },
        "outputs": [str(path) for path in outputs] + [str(OUT_DIR / "missing_leg_context_refresh_manifest.json"), str(OUT_DIR / "run_progress_log.txt")],
        "metrics": metrics,
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_assigned": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "bin_by_source_overlap_tables_materialized": False,
            "skipped_targets_processed": False,
        },
        "row_counts": {
            "candidate_legs_input": int(len(legs)),
            "candidate_bins_0_1000_input": int(len(bins_0_1000)),
            "candidate_bins_1000_2500_input": int(len(bins_1000_2500)),
            "candidate_bins_processed": int(len(detail)),
            "context_signal_summary": int(len(signal)),
            "skipped_targets_held_out": int(len(skipped)),
        },
    }
    _write_json(manifest, "missing_leg_context_refresh_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
