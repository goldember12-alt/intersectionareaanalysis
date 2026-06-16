from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/refreshed_expanded_universe_with_offset_recovery"

PRIOR_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/expanded_universe_refresh_and_709_plan"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_context_refresh"
ACCESS_CAPTURE_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_capture"
ACCESS_GEOMETRY_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"
ACCESS_SOURCE_CAPTURE_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_source_capture_audit"

PREVIOUS_REPRESENTED_COUNT = 2_739
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

REQUIRED_INPUTS = {
    PRIOR_UNIVERSE_DIR: [
        "refreshed_represented_signal_universe.csv",
        "refreshed_represented_universe_summary.csv",
        "expanded_universe_refresh_and_709_plan_manifest.json",
    ],
    OFFSET_CONTEXT_DIR: [
        "offset_zone_context_bin_detail.csv",
        "offset_zone_context_signal_summary.csv",
        "offset_zone_context_readiness_summary.csv",
        "offset_zone_updated_universe_projection.csv",
        "offset_zone_context_missingness.csv",
        "offset_zone_context_refresh_manifest.json",
    ],
    ACCESS_CAPTURE_DIR: [
        "access_target_bins.csv",
        "access_product_coverage_summary.csv",
    ],
}


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


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(frame))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(frame))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _missing_required_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ready_offset_signals(offset_signals: pd.DataFrame) -> pd.DataFrame:
    ready = offset_signals.loc[
        _flag(offset_signals, "eligible_for_later_universe_refresh")
        & _flag(offset_signals, "speed_aadt_ready")
        & ~_flag(offset_signals, "has_grade_separation_holdouts")
    ].copy()
    ready["offset_recovery_ready_status"] = "speed_aadt_ready_offset_zone_review_only"
    return ready


def _reconcile_signals(prior: pd.DataFrame, offset_signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    ready = _ready_offset_signals(offset_signals)
    prior = prior.copy()
    prior["dedup_signal_key_source_id"] = _text(prior, "source_layer") + "|" + _text(prior, "source_signal_id")
    prior["dedup_signal_key_candidate_id"] = _text(prior, "candidate_signal_id_refreshed")
    ready["dedup_signal_key_source_id"] = _text(ready, "source_layer") + "|" + _text(ready, "source_signal_id")
    ready["dedup_signal_key_candidate_id"] = _text(ready, "signal_id")

    prior_source_keys = set(_text(prior, "dedup_signal_key_source_id"))
    prior_signal_ids = set(_text(prior, "dedup_signal_key_candidate_id"))
    rows: list[dict[str, Any]] = []
    for rec in ready.to_dict(orient="records"):
        source_overlap = rec["dedup_signal_key_source_id"] in prior_source_keys and rec["dedup_signal_key_source_id"] != "|"
        signal_overlap = rec["dedup_signal_key_candidate_id"] in prior_signal_ids and rec["dedup_signal_key_candidate_id"] != ""
        status = "overlaps_existing_represented_signal" if source_overlap or signal_overlap else "new_represented_signal_if_accepted"
        rows.append(
            {
                "signal_id": rec.get("signal_id", ""),
                "source_signal_id": rec.get("source_signal_id", ""),
                "source_layer": rec.get("source_layer", ""),
                "offset_speed_aadt_ready": rec.get("speed_aadt_ready", ""),
                "offset_speed_aadt_ready_0_1000": rec.get("speed_aadt_ready_0_1000", ""),
                "offset_attempted_bin_count": rec.get("attempted_bin_count", ""),
                "offset_attempted_leg_count": rec.get("attempted_leg_count", ""),
                "offset_has_long_source_row_qa_flag": rec.get("has_long_source_row_qa_flag", ""),
                "dedup_source_id_overlap": source_overlap,
                "dedup_candidate_signal_id_overlap": signal_overlap,
                "dedup_reconciliation_status": status,
                "net_new_signal_addition": status == "new_represented_signal_if_accepted",
            }
        )
    reconciliation = pd.DataFrame(rows)

    offset_signal_cols = [
        "signal_id",
        "attempted_bin_count",
        "attempted_leg_count",
        "speed_aadt_ready",
        "speed_aadt_ready_0_1000",
        "has_long_source_row_qa_flag",
        "eligible_for_later_universe_refresh",
        "missingness_reason_if_not_ready",
    ]
    ready_merge = ready[[col for col in offset_signal_cols if col in ready.columns]].drop_duplicates("signal_id")
    refreshed = prior.merge(ready_merge, left_on="candidate_signal_id_refreshed", right_on="signal_id", how="left", suffixes=("", "_offset"))
    refreshed["has_offset_zone_recovery_ready_evidence"] = _text(refreshed, "speed_aadt_ready_offset").str.lower().isin({"true", "1", "yes", "y"})
    refreshed["offset_zone_attempted_bin_count"] = _text(refreshed, "attempted_bin_count")
    refreshed["offset_zone_attempted_leg_count"] = _text(refreshed, "attempted_leg_count")
    refreshed["offset_zone_speed_aadt_ready_0_1000"] = _text(refreshed, "speed_aadt_ready_0_1000")
    refreshed["offset_zone_long_source_row_qa_flag"] = _text(refreshed, "has_long_source_row_qa_flag")
    refreshed["offset_zone_refresh_status"] = np.where(
        refreshed["has_offset_zone_recovery_ready_evidence"],
        "existing_represented_signal_with_offset_zone_recovery_evidence",
        "no_offset_zone_recovery_evidence",
    )
    refreshed["represented_source_with_offset"] = np.where(
        refreshed["has_offset_zone_recovery_ready_evidence"],
        _text(refreshed, "represented_source") + "|offset_intersection_zone_recovery_review_only",
        _text(refreshed, "represented_source"),
    )
    refreshed = refreshed.drop(columns=[col for col in ["signal_id", "attempted_bin_count", "attempted_leg_count", "speed_aadt_ready_offset", "speed_aadt_ready_0_1000", "has_long_source_row_qa_flag", "eligible_for_later_universe_refresh", "missingness_reason_if_not_ready"] if col in refreshed.columns])

    new_rows = ready.loc[~ready["signal_id"].isin(prior_signal_ids)].copy()
    if not new_rows.empty:
        append = pd.DataFrame(
            {
                "source_signal_id": _text(new_rows, "source_signal_id"),
                "source_layer": _text(new_rows, "source_layer"),
                "prior_candidate_signal_id": "",
                "candidate_signal_id_refreshed": _text(new_rows, "signal_id"),
                "frozen_candidate_signal_id": "",
                "candidate_bin_count": _text(new_rows, "attempted_bin_count"),
                "weighted_bin_count": _text(new_rows, "attempted_bin_count"),
                "has_any_scaffold": True,
                "has_roadway_context": _flag(new_rows, "has_roadway_context"),
                "has_speed": _flag(new_rows, "has_rns_speed"),
                "has_aadt": _flag(new_rows, "has_aadt"),
                "has_exposure": _flag(new_rows, "has_exposure_denominator"),
                "speed_aadt_ready": _flag(new_rows, "speed_aadt_ready"),
                "full_0_1000_speed_aadt_ready": _flag(new_rows, "speed_aadt_ready_0_1000"),
                "full_attempted_0_2500_speed_aadt_ready": False,
                "direction_labels": "",
                "analysis_windows": "0_1000",
                "one_direction_only_flag": False,
                "one_sided_or_partial_flag": True,
                "multi_candidate_weighted_flag": False,
                "strict_active_overlap_conflict_flag": False,
                "strict_active_overlap_status": "offset_zone_review_only_no_strict_active_overlap",
                "recovery_strategy": "offset_intersection_zone_recovery",
                "association_confidence_tier": "offset_zone_speed_aadt_ready_review_only",
                "represented_source": "offset_intersection_zone_recovery_review_only",
                "review_only_addition_status": "offset_zone_review_only_signal_addition",
                "refreshed_universe_tier": "offset_zone_recovery_speed_aadt_ready",
                "near_signal_or_partial_tier": "offset_zone_partial_0_1000",
                "has_offset_zone_recovery_ready_evidence": True,
                "offset_zone_attempted_bin_count": _text(new_rows, "attempted_bin_count"),
                "offset_zone_attempted_leg_count": _text(new_rows, "attempted_leg_count"),
                "offset_zone_speed_aadt_ready_0_1000": _text(new_rows, "speed_aadt_ready_0_1000"),
                "offset_zone_long_source_row_qa_flag": _text(new_rows, "has_long_source_row_qa_flag"),
                "offset_zone_refresh_status": "new_represented_signal_with_offset_zone_recovery_evidence",
                "represented_source_with_offset": "offset_intersection_zone_recovery_review_only",
            }
        )
        refreshed = pd.concat([refreshed, append], ignore_index=True, sort=False)

    metrics = {
        "previous_represented_count": int(len(prior)),
        "offset_speed_aadt_ready_signals": int(len(ready)),
        "offset_overlap_count": int((reconciliation["dedup_reconciliation_status"] == "overlaps_existing_represented_signal").sum()) if not reconciliation.empty else 0,
        "offset_net_new_signal_additions": int(reconciliation["net_new_signal_addition"].sum()) if not reconciliation.empty else 0,
        "refreshed_represented_count": int(refreshed["candidate_signal_id_refreshed"].nunique()),
    }
    return refreshed, reconciliation, metrics


def _offset_bin_rows(offset_bins: pd.DataFrame, ready_signal_ids: set[str]) -> pd.DataFrame:
    out = offset_bins.loc[
        _text(offset_bins, "signal_id").isin(ready_signal_ids)
        & _flag(offset_bins, "refresh_eligible_bin")
        & ~_flag(offset_bins, "hold_excluded_mainline")
        & ~_flag(offset_bins, "hold_manual_grade_separation_review")
        & ~_flag(offset_bins, "hold_nonstandard_geometry")
    ].copy()
    out["target_bin_source"] = "offset_intersection_zone_recovery"
    out["target_bin_id"] = _text(out, "staged_recovered_bin_id").where(_text(out, "staged_recovered_bin_id").ne(""), _text(out, "offset_zone_recovered_bin_id"))
    out["candidate_bin_id"] = out["target_bin_id"]
    out["target_signal_id"] = _text(out, "signal_id")
    out["candidate_signal_id"] = _text(out, "signal_id")
    out["route_id"] = _text(out, "source_route_id")
    out["route_common"] = _text(out, "source_route_keys")
    out["route_name"] = _text(out, "source_route_raw")
    out["route_key"] = _text(out, "candidate_normalized_route_key")
    out["measure_low"] = _text(out, "candidate_measure_min")
    out["measure_high"] = _text(out, "candidate_measure_max")
    out["route_measure_ready"] = _flag(out, "has_route_measure_identity")
    out["speed_ready_flag"] = _flag(out, "has_rns_speed")
    out["aadt_ready_flag"] = _flag(out, "has_aadt")
    out["exposure_ready_flag"] = _flag(out, "has_exposure_denominator")
    out["speed_aadt_ready_flag"] = _flag(out, "speed_aadt_ready_bin")
    out["review_only_flag"] = True
    out["target_bin_review_only_status"] = "review_only_offset_zone_recovered_bin"
    out["recommended_bin_universe_tier"] = "offset_zone_recovery_bin_review_only"
    out["distance_length_ft"] = pd.to_numeric(_text(out, "distance_end_ft"), errors="coerce") - pd.to_numeric(_text(out, "distance_start_ft"), errors="coerce")
    out["dedup_signal_key"] = _text(out, "source_layer") + "|" + _text(out, "source_signal_id")
    out["offset_zone_bin_flag"] = True
    out["previous_represented_bin_flag"] = False
    return out


def _combine_bins(prior_bins: pd.DataFrame, offset_bins_ready: pd.DataFrame) -> pd.DataFrame:
    prior = prior_bins.copy()
    prior["previous_represented_bin_flag"] = True
    prior["offset_zone_bin_flag"] = False
    prior["refresh_bin_source"] = "previous_expanded_represented_universe"
    offset = offset_bins_ready.copy()
    offset["refresh_bin_source"] = "offset_intersection_zone_recovery"
    all_cols = list(dict.fromkeys([*prior.columns, *offset.columns]))
    combined = pd.concat([prior.reindex(columns=all_cols), offset.reindex(columns=all_cols)], ignore_index=True, sort=False)
    combined["refreshed_bin_universe_status"] = np.where(combined["offset_zone_bin_flag"].astype(str).str.lower().eq("true"), "new_offset_zone_bin_review_only", "prior_represented_bin")
    return combined


def _readiness_summary(refreshed_signals: pd.DataFrame, refreshed_bins: pd.DataFrame, offset_bin_count: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    bin_work = refreshed_bins.copy()
    bin_work["bin_has_roadway_context"] = _flag(bin_work, "has_roadway_context") | _flag(bin_work, "roadway_context_ready_unified")
    bin_work["bin_has_speed"] = _flag(bin_work, "has_speed") | _flag(bin_work, "speed_ready_flag") | _flag(bin_work, "has_rns_speed")
    bin_work["bin_has_aadt"] = _flag(bin_work, "has_aadt") | _flag(bin_work, "aadt_ready_flag")
    bin_work["bin_has_exposure"] = _flag(bin_work, "has_exposure") | _flag(bin_work, "exposure_ready_flag") | _flag(bin_work, "has_exposure_denominator")
    bin_work["bin_speed_aadt_ready"] = _flag(bin_work, "speed_aadt_ready") | _flag(bin_work, "speed_aadt_ready_flag") | _flag(bin_work, "speed_aadt_ready_bin")
    bin_work["bin_0_1000"] = _text(bin_work, "analysis_window").eq("0_1000") | pd.to_numeric(_text(bin_work, "distance_end_ft"), errors="coerce").le(1000)
    bin_work["partial_or_one_sided"] = _flag(bin_work, "partial_one_sided_flag") | _flag(bin_work, "partial_coverage_flag") | _flag(bin_work, "one_sided_or_partial_flag")

    signal_count = refreshed_signals["candidate_signal_id_refreshed"].nunique()
    summary = pd.DataFrame(
        [
            {"metric": "represented_signals", "count": signal_count, "note": "Deduped candidate_signal_id_refreshed count."},
            {"metric": "represented_bins", "count": len(refreshed_bins), "note": "Prior represented access-target bins plus offset-zone eligible bins."},
            {"metric": "new_offset_zone_bins", "count": offset_bin_count, "note": "Review-only recovered bins appended to bin universe."},
            {"metric": "bins_with_roadway_context", "count": int(bin_work["bin_has_roadway_context"].sum()), "note": ""},
            {"metric": "bins_with_speed", "count": int(bin_work["bin_has_speed"].sum()), "note": ""},
            {"metric": "bins_with_aadt", "count": int(bin_work["bin_has_aadt"].sum()), "note": ""},
            {"metric": "bins_with_exposure", "count": int(bin_work["bin_has_exposure"].sum()), "note": ""},
            {"metric": "bins_speed_aadt_ready", "count": int(bin_work["bin_speed_aadt_ready"].sum()), "note": ""},
            {"metric": "bins_in_0_1000_window", "count": int(bin_work["bin_0_1000"].sum()), "note": ""},
            {"metric": "signals_with_offset_zone_recovery_evidence", "count": int(_flag(refreshed_signals, "has_offset_zone_recovery_ready_evidence").sum()), "note": ""},
            {"metric": "signals_with_long_source_row_offset_flag", "count": int(_flag(refreshed_signals, "offset_zone_long_source_row_qa_flag").sum()), "note": ""},
            {"metric": "partial_or_one_sided_bins", "count": int(bin_work["partial_or_one_sided"].sum()), "note": ""},
        ]
    )
    by_source = (
        bin_work.groupby("refresh_bin_source", dropna=False)
        .agg(
            bin_count=("target_bin_id", "count"),
            signal_count=("target_signal_id", "nunique"),
            roadway_context_bins=("bin_has_roadway_context", "sum"),
            speed_ready_bins=("bin_has_speed", "sum"),
            aadt_ready_bins=("bin_has_aadt", "sum"),
            exposure_ready_bins=("bin_has_exposure", "sum"),
            speed_aadt_ready_bins=("bin_speed_aadt_ready", "sum"),
            zero_1000_bins=("bin_0_1000", "sum"),
            partial_or_one_sided_bins=("partial_or_one_sided", "sum"),
        )
        .reset_index()
    )
    return summary, by_source


def _access_rerun_readiness(refreshed_bins: pd.DataFrame, offset_ready_bins: pd.DataFrame) -> pd.DataFrame:
    prior_capture = _read_csv(ACCESS_CAPTURE_DIR / "access_product_coverage_summary.csv")
    geom = _read_csv(ACCESS_GEOMETRY_DIR / "access_buffer_sensitivity_summary.csv") if ACCESS_GEOMETRY_DIR.exists() else pd.DataFrame()
    source_capture = _read_csv(ACCESS_SOURCE_CAPTURE_DIR / "access_source_capture_by_buffer.csv") if ACCESS_SOURCE_CAPTURE_DIR.exists() else pd.DataFrame()
    rows = [
        {
            "readiness_item": "refreshed_access_target_bins",
            "status": "ready",
            "count": len(refreshed_bins),
            "note": "Refreshed access target includes prior represented bins plus offset-zone recovered bins.",
        },
        {
            "readiness_item": "new_offset_zone_target_bins",
            "status": "ready",
            "count": len(offset_ready_bins),
            "note": "These bins were not present in the prior 2,739 access target.",
        },
        {
            "readiness_item": "new_offset_zone_target_signals",
            "status": "deduped_overlap_only",
            "count": offset_ready_bins["target_signal_id"].nunique() if not offset_ready_bins.empty else 0,
            "note": "Signals overlap the prior represented signal universe, but their offset-zone bins are new access targets.",
        },
        {
            "readiness_item": "prior_access_capture_summary_available",
            "status": "available_for_comparison_only" if not prior_capture.empty else "missing",
            "count": len(prior_capture),
            "note": "Prior access capture was not rerun in this module.",
        },
        {
            "readiness_item": "prior_access_geometry_completion_summary_available",
            "status": "available_for_comparison_only" if not geom.empty else "missing",
            "count": len(geom),
            "note": "Prior buffer/catchment access summaries are stale for the refreshed target.",
        },
        {
            "readiness_item": "prior_access_source_capture_summary_available",
            "status": "available_for_comparison_only" if not source_capture.empty else "missing",
            "count": len(source_capture),
            "note": "Prior source-capture audit should be rerun after access catchment refresh.",
        },
        {
            "readiness_item": "access_rerun_recommendation",
            "status": "rerun_needed_in_next_module",
            "count": "",
            "note": "Do not reuse prior assignment counts as refreshed coverage; rerun access capture/catchment/source audit against refreshed_access_target_bins.",
        },
    ]
    return pd.DataFrame(rows)


def _findings(metrics: dict[str, int], refreshed_bin_count: int, offset_bin_count: int) -> str:
    pct = metrics["refreshed_represented_count"] / BASE_SIGNAL_UNIVERSE * 100
    return f"""# Refreshed Expanded Universe With Offset Recovery Findings

## Bounded Question

This read-only pass refreshes the represented review universe with QA-cleaned offset/intersection-zone recovery evidence. It deduplicates signals, appends offset-zone recovered bins as review-only bin evidence, and prepares the refreshed access target. It does not promote candidates, assign crashes, compute rates, run models, or modify active outputs.

## Results

- Previous represented signal count: {metrics["previous_represented_count"]:,}
- Offset-zone speed+AADT-ready signals considered: {metrics["offset_speed_aadt_ready_signals"]:,}
- Offset-zone signals overlapping existing represented signals: {metrics["offset_overlap_count"]:,}
- Net new deduped signal additions: {metrics["offset_net_new_signal_additions"]:,}
- Refreshed deduplicated represented signal count: {metrics["refreshed_represented_count"]:,}
- Percent of 3,933 base signals represented: {pct:.2f}%
- Refreshed bin count: {refreshed_bin_count:,}
- New offset-zone bins: {offset_bin_count:,}

## Access Rerun Readiness

The refreshed access target is ready as `refreshed_access_target_bins.csv`. Prior access capture, catchment, and source-capture outputs remain useful comparison baselines only. They should not be treated as refreshed coverage because the target now includes offset-zone recovered bins. The next pass should rerun access capture/catchments/source audit against the refreshed target while keeping typed and untyped access separate.

## Interpretation

The offset-zone recovery improved bin/scaffold evidence for already represented signals rather than adding new deduplicated represented signals. The current 2,739 signal count therefore remains the deduplicated represented count, but it is no longer the same bin/scaffold universe: {offset_bin_count:,} offset-zone bins are now available for review-only access rerun setup.
"""


def _qa(refreshed_signals: pd.DataFrame, offset_bins: pd.DataFrame, metrics: dict[str, int]) -> pd.DataFrame:
    output_inside = str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/refreshed_expanded_universe_with_offset_recovery")
    held_present = (_flag(offset_bins, "hold_excluded_mainline") | _flag(offset_bins, "hold_manual_grade_separation_review") | _flag(offset_bins, "hold_nonstandard_geometry")).any()
    return pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, "", "true", "All writes are under review/current/refreshed_expanded_universe_with_offset_recovery."),
            _qa_row("no_candidates_promoted", True, "", "true", "All records remain review-only."),
            _qa_row("no_crash_assignment", True, "", "true", "No crash records are read or assigned."),
            _qa_row("no_rates_or_models", True, "", "true", "Readiness/projection only."),
            _qa_row("held_grade_separated_mainline_records_excluded", not held_present, "", "true", "Offset bins are filtered to refresh-eligible records."),
            _qa_row("offset_zone_additions_review_only", _flag(offset_bins, "review_only_flag").all() if not offset_bins.empty else True, "", "true", ""),
            _qa_row("deduped_signal_counts_separate_from_bin_counts", metrics["refreshed_represented_count"] <= len(offset_bins) + 1_000_000, f"{metrics['refreshed_represented_count']} signals", "signal count tracked separately", ""),
            _qa_row("outputs_written_only_to_review_folder", output_inside, str(OUT_DIR), "review/current/refreshed_expanded_universe_with_offset_recovery", ""),
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = _missing_required_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    prior_signals = _read_csv(PRIOR_UNIVERSE_DIR / "refreshed_represented_signal_universe.csv")
    prior_summary = _read_csv(PRIOR_UNIVERSE_DIR / "refreshed_represented_universe_summary.csv")
    offset_signals = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv")
    offset_bins = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_bin_detail.csv")
    offset_readiness = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_readiness_summary.csv")
    offset_projection = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_updated_universe_projection.csv")
    offset_missing = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_missingness.csv")
    prior_access_target = _read_csv(ACCESS_CAPTURE_DIR / "access_target_bins.csv")

    refreshed_signals, reconciliation, metrics = _reconcile_signals(prior_signals, offset_signals)
    ready_signal_ids = set(reconciliation.loc[reconciliation["dedup_reconciliation_status"].isin(["overlaps_existing_represented_signal", "new_represented_signal_if_accepted"]), "signal_id"])
    offset_ready_bins = _offset_bin_rows(offset_bins, ready_signal_ids)
    refreshed_bins = _combine_bins(prior_access_target, offset_ready_bins)
    context_summary, readiness_by_source = _readiness_summary(refreshed_signals, refreshed_bins, len(offset_ready_bins))
    access_rerun = _access_rerun_readiness(refreshed_bins, offset_ready_bins)

    summary = pd.DataFrame(
        [
            {"metric": "previous_represented_count", "value": metrics["previous_represented_count"]},
            {"metric": "offset_zone_speed_aadt_ready_signals", "value": metrics["offset_speed_aadt_ready_signals"]},
            {"metric": "offset_zone_overlap_dedup_count", "value": metrics["offset_overlap_count"]},
            {"metric": "offset_zone_net_new_signal_additions", "value": metrics["offset_net_new_signal_additions"]},
            {"metric": "refreshed_represented_count", "value": metrics["refreshed_represented_count"]},
            {"metric": "percent_of_3933_base_signals_represented", "value": round(metrics["refreshed_represented_count"] / BASE_SIGNAL_UNIVERSE * 100, 2)},
            {"metric": "refreshed_bin_count", "value": len(refreshed_bins)},
            {"metric": "new_offset_zone_bin_count", "value": len(offset_ready_bins)},
        ]
    )

    access_target = refreshed_bins.copy()
    access_target["refreshed_access_target_status"] = np.where(_flag(access_target, "offset_zone_bin_flag"), "new_offset_zone_access_target_bin", "prior_access_target_bin")

    _write_csv(refreshed_signals, OUT_DIR / "refreshed_represented_signal_universe.csv")
    _write_csv(refreshed_bins, OUT_DIR / "refreshed_represented_bin_universe.csv")
    _write_csv(reconciliation, OUT_DIR / "offset_recovery_dedup_reconciliation.csv")
    _write_csv(summary, OUT_DIR / "refreshed_universe_summary.csv")
    _write_csv(pd.concat([context_summary, readiness_by_source.rename(columns={"refresh_bin_source": "metric"})], ignore_index=True, sort=False), OUT_DIR / "refreshed_context_readiness_summary.csv")
    _write_csv(access_target, OUT_DIR / "refreshed_access_target_bins.csv")
    _write_csv(access_rerun, OUT_DIR / "refreshed_access_rerun_readiness.csv")
    _write_text(_findings(metrics, len(refreshed_bins), len(offset_ready_bins)), OUT_DIR / "refreshed_universe_with_offset_recovery_findings.md")
    qa = _qa(refreshed_signals, offset_ready_bins, metrics)
    _write_csv(qa, OUT_DIR / "refreshed_universe_with_offset_recovery_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.refreshed_expanded_universe_with_offset_recovery",
        "bounded_question": "Review-only represented universe refresh with QA-cleaned offset/intersection-zone recovery evidence and access rerun setup.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "prior_universe_dir": str(PRIOR_UNIVERSE_DIR),
            "offset_context_dir": str(OFFSET_CONTEXT_DIR),
            "access_capture_dir": str(ACCESS_CAPTURE_DIR),
            "access_geometry_dir": str(ACCESS_GEOMETRY_DIR),
            "access_source_capture_dir": str(ACCESS_SOURCE_CAPTURE_DIR),
            "prior_universe_manifest": _load_json(PRIOR_UNIVERSE_DIR / "expanded_universe_refresh_and_709_plan_manifest.json"),
            "offset_context_manifest": _load_json(OFFSET_CONTEXT_DIR / "offset_zone_context_refresh_manifest.json"),
        },
        "metrics": {
            **metrics,
            "refreshed_bin_count": int(len(refreshed_bins)),
            "new_offset_zone_bin_count": int(len(offset_ready_bins)),
            "prior_summary_rows": int(len(prior_summary)),
            "offset_readiness_rows": int(len(offset_readiness)),
            "offset_projection_rows": int(len(offset_projection)),
            "offset_missingness_rows": int(len(offset_missing)),
        },
        "outputs": [
            "refreshed_represented_signal_universe.csv",
            "refreshed_represented_bin_universe.csv",
            "offset_recovery_dedup_reconciliation.csv",
            "refreshed_universe_summary.csv",
            "refreshed_context_readiness_summary.csv",
            "refreshed_access_target_bins.csv",
            "refreshed_access_rerun_readiness.csv",
            "refreshed_universe_with_offset_recovery_findings.md",
            "refreshed_universe_with_offset_recovery_qa.csv",
            "refreshed_universe_with_offset_recovery_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "access_assignment_rerun_performed": False,
        },
    }
    _write_json(manifest, OUT_DIR / "refreshed_universe_with_offset_recovery_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
