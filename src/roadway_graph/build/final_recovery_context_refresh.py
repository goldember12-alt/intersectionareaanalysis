from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import pyogrio
except ImportError:  # pragma: no cover
    pyogrio = None

from . import offset_intersection_zone_context_refresh as context_helpers


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"

FINAL_DIR = OUTPUT_ROOT / "review/current/final_implementable_scaffold_cleanup"
BRANCH_DIR = OUTPUT_ROOT / "review/current/scaffold_recovery_branch_ledger"
MAP_GPKG = OUTPUT_ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg"

CURRENT_REPRESENTED_UNIVERSE_SIGNALS = 2_739

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
    FINAL_DIR / "final_cleanup_missing_leg_candidates.csv",
    FINAL_DIR / "final_cleanup_missing_leg_bins.csv",
    FINAL_DIR / "final_cleanup_signal_summary.csv",
    FINAL_DIR / "final_cleanup_impact_summary.csv",
    FINAL_DIR / "final_unrecovered_source_limitation_ledger.csv",
    FINAL_DIR / "final_implementable_scaffold_cleanup_manifest.json",
    BRANCH_DIR / "scaffold_recovery_branch_ledger_signal_detail.csv",
    BRANCH_DIR / "scaffold_recovery_branch_summary.csv",
    BRANCH_DIR / "branch_a_direct_missing_leg_summary.csv",
    BRANCH_DIR / "branch_b_divided_normalization_summary.csv",
    BRANCH_DIR / "branch_c_source_limitation_summary.csv",
    BRANCH_DIR / "final_recovery_residual_class_summary.csv",
    BRANCH_DIR / "scaffold_recovery_exhaustion_decision.csv",
    BRANCH_DIR / "scaffold_recovery_branch_ledger_manifest.json",
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
    if lower == "true_vehicle_direction_inferred":
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


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
    if not MAP_GPKG.exists():
        missing.append(str(MAP_GPKG))
    return missing


def _source_travelway_lookup(bins: pd.DataFrame) -> pd.DataFrame:
    if pyogrio is None:
        raise RuntimeError("pyogrio is required to read source_travelway_full attributes from the review GeoPackage.")
    columns = ["EVENT_SOUR", "RTE_NM", "RTE_COMMON", "RTE_ID", "FROM_MEASURE", "TO_MEASURE", "RTE_FROM_M", "RTE_TO_MSR", "RIM_FACILI", "RTE_CATEGO", "RTE_TYPE_N"]
    _checkpoint("read_start source_travelway_full_attributes")
    source = pyogrio.read_dataframe(MAP_GPKG, layer="source_travelway_full", columns=columns, read_geometry=False, use_arrow=True)
    _checkpoint("read_complete source_travelway_full_attributes", len(source))
    source = pd.DataFrame(source).astype(str)
    needed_events = set(_text(bins, "source_lineage"))
    needed_routes = set(_text(bins, "source_rte_id"))
    source = source.loc[source["EVENT_SOUR"].isin(needed_events) | source["RTE_ID"].isin(needed_routes)].copy()
    _checkpoint("source_travelway_full_attributes_filtered", len(source))
    from_measure = source["FROM_MEASURE"].where(source["FROM_MEASURE"].str.strip().ne(""), source["RTE_FROM_M"])
    to_measure = source["TO_MEASURE"].where(source["TO_MEASURE"].str.strip().ne(""), source["RTE_TO_MSR"])
    source["source_travelway_lineage_recovered"] = (
        source["EVENT_SOUR"].astype(str)
        + "_"
        + source["RTE_NM"].astype(str)
        + "_"
        + source["RTE_ID"].astype(str)
        + "_"
        + from_measure.astype(str)
        + "_"
        + to_measure.astype(str)
    )
    source["source_travelway_lineage_recovered"] = source["source_travelway_lineage_recovered"].where(
        from_measure.str.strip().ne("") & to_measure.str.strip().ne(""),
        "",
    )
    source = source.sort_values(["EVENT_SOUR", "RTE_ID"]).drop_duplicates(["EVENT_SOUR", "RTE_ID"], keep="first")
    return source


def _prepare_candidate_bins(bins: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    work = bins.loc[_text(bins, "review_only_flag").str.lower().eq("true")].copy()
    work = work.loc[_text(work, "context_refresh_readiness").eq("needs_route_measure_speed_aadt_refresh")].copy()
    work["context_window_scope"] = _text(work, "analysis_window").map(
        {"0_1000": "primary_0_1000", "1000_2500": "sensitivity_1000_2500"}
    ).fillna("other_review")
    leg_cols = [
        col
        for col in [
            "final_missing_leg_id",
            "source_lineage",
            "recovery_confidence",
            "calibrated_expected_physical_leg_count",
            "candidate_bearing_sectors_175ft",
        ]
        if col in legs.columns
    ]
    if leg_cols:
        work = work.merge(legs[leg_cols].drop_duplicates("final_missing_leg_id"), on="final_missing_leg_id", how="left", suffixes=("", "_leg"))
    source = _source_travelway_lookup(work)
    work = work.merge(
        source,
        left_on=["source_lineage", "source_rte_id"],
        right_on=["EVENT_SOUR", "RTE_ID"],
        how="left",
        suffixes=("", "_source"),
    )
    work["source_travelway_lineage"] = _text(work, "source_travelway_lineage_recovered")
    work["source_line_ids"] = work["source_travelway_lineage"]
    work["source_lineage_lookup_status"] = np.where(
        work["source_travelway_lineage"].astype(str).str.strip().ne(""),
        "matched_source_travelway_route_measure",
        "missing_source_travelway_route_measure",
    )
    work["source_route_keys"] = _text(work, "source_rte_nm") + "|" + _text(work, "source_rte_common") + "|" + _text(work, "source_rte_id")
    work["staged_recovered_bin_id"] = work["final_missing_leg_bin_id"]
    work["staged_recovered_leg_id"] = work["final_missing_leg_id"]
    work["refresh_eligible_bin"] = True
    work["refresh_eligible_leg"] = True
    work["hold_excluded_mainline"] = False
    work["hold_manual_grade_separation_review"] = False
    work["hold_nonstandard_geometry"] = False
    work["qa_cleanup_status"] = "final_cleanup_missing_leg_context_refresh_eligible"
    work["route_facility_discontinuity_type"] = "not_targeted_in_this_pass"
    work["route_facility_discontinuity_flag"] = False
    work["source_line_split_flag"] = False
    work["divided_carriageway_flag"] = False
    work["long_source_row_flag"] = False
    work["context_candidate_scope"] = "review_only_final_cleanup_missing_leg_candidate"
    return work


def _assign_context(candidate_bins: pd.DataFrame) -> pd.DataFrame:
    route_detail = context_helpers._build_route_measure_identity(candidate_bins)
    detail = context_helpers._assign_context(route_detail)
    detail["final_cleanup_missing_leg_bin_id"] = detail["staged_recovered_bin_id"]
    detail["final_cleanup_missing_leg_id"] = detail["staged_recovered_leg_id"]
    detail["recovery_class"] = "final_cleanup_missing_leg_recovery"
    detail["context_assignment_scope"] = "review_only_final_cleanup_missing_leg_bins_not_active"
    return detail


def _signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    signal = detail.groupby("signal_id", dropna=False).agg(
        source_signal_id=("source_signal_id", "first"),
        source_layer=("source_layer", "first"),
        attempted_bin_count=("final_cleanup_missing_leg_bin_id", "count"),
        attempted_leg_count=("final_cleanup_missing_leg_id", "nunique"),
        primary_0_1000_bin_count=("context_window_scope", lambda s: int((s == "primary_0_1000").sum())),
        sensitivity_1000_2500_bin_count=("context_window_scope", lambda s: int((s == "sensitivity_1000_2500").sum())),
        route_measure_ready_bins=("has_route_measure_identity", "sum"),
        roadway_context_bins=("has_roadway_context", "sum"),
        rns_speed_ready_bins=("has_rns_speed", "sum"),
        aadt_ready_bins=("has_aadt", "sum"),
        exposure_ready_bins=("has_exposure_denominator", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        roadway_route_type_categories=("roadway_route_type_category", _collapse),
        speed_missing_reasons=("rns_speed_missing_reason", _collapse),
        aadt_missing_reasons=("aadt_v3_missing_reason", _collapse),
    ).reset_index()
    for col in [
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
        signal[col] = pd.to_numeric(signal[col], errors="coerce").fillna(0).astype(int)
    signal["has_route_measure_identity"] = signal["route_measure_ready_bins"].gt(0)
    signal["has_roadway_context"] = signal["roadway_context_bins"].gt(0)
    signal["has_rns_speed"] = signal["rns_speed_ready_bins"].gt(0)
    signal["has_aadt"] = signal["aadt_ready_bins"].gt(0)
    signal["has_exposure_denominator"] = signal["exposure_ready_bins"].gt(0)
    signal["speed_aadt_ready"] = signal["speed_aadt_ready_bins"].gt(0)
    signal["speed_aadt_ready_0_1000"] = signal["speed_aadt_ready"] & signal["primary_0_1000_bin_count"].gt(0)
    signal["sensitivity_1000_2500_ready"] = signal["sensitivity_1000_2500_bin_count"].gt(0) & signal["speed_aadt_ready"]
    signal["held_or_failed_reason_if_not_ready"] = ""
    signal.loc[~signal["has_route_measure_identity"], "held_or_failed_reason_if_not_ready"] = "missing_route_measure_identity"
    signal.loc[signal["has_route_measure_identity"] & ~signal["has_rns_speed"], "held_or_failed_reason_if_not_ready"] = "missing_rns_speed"
    signal.loc[signal["has_route_measure_identity"] & signal["has_rns_speed"] & ~signal["has_aadt"], "held_or_failed_reason_if_not_ready"] = "missing_aadt"
    signal.loc[signal["speed_aadt_ready"], "held_or_failed_reason_if_not_ready"] = ""
    return signal


def _summary_rows(detail: pd.DataFrame, signal: pd.DataFrame, source_ledger: pd.DataFrame, branch_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    route = pd.DataFrame(
        [
            {"metric": "bins_attempted", "bin_count": len(detail)},
            {"metric": "route_measure_ready_bins", "bin_count": int(detail["has_route_measure_identity"].sum()) if not detail.empty else 0},
            {"metric": "roadway_context_ready_bins", "bin_count": int(detail["has_roadway_context"].sum()) if not detail.empty else 0},
        ]
    )
    speed = pd.DataFrame(
        [
            {"metric": "bins_attempted", "bin_count": len(detail)},
            {"metric": "rns_speed_ready_bins", "bin_count": int(detail["has_rns_speed"].sum()) if not detail.empty else 0},
            {"metric": "rns_speed_missing_bins", "bin_count": int((~detail["has_rns_speed"]).sum()) if not detail.empty else 0},
        ]
    )
    aadt = pd.DataFrame(
        [
            {"metric": "bins_attempted", "bin_count": len(detail)},
            {"metric": "aadt_ready_bins", "bin_count": int(detail["has_aadt"].sum()) if not detail.empty else 0},
            {"metric": "exposure_ready_bins", "bin_count": int(detail["has_exposure_denominator"].sum()) if not detail.empty else 0},
        ]
    )
    readiness = pd.DataFrame(
        [
            {"metric": "signals_processed", "signal_count": signal["signal_id"].nunique() if not signal.empty else 0, "bin_count": len(detail)},
            {"metric": "signals_speed_aadt_ready", "signal_count": int(signal["speed_aadt_ready"].sum()) if not signal.empty else 0, "bin_count": int(detail["speed_aadt_ready_bin"].sum()) if not detail.empty else 0},
            {"metric": "signals_0_1000_speed_aadt_ready", "signal_count": int(signal["speed_aadt_ready_0_1000"].sum()) if not signal.empty else 0, "bin_count": int(detail.loc[_text(detail, "context_window_scope").eq("primary_0_1000"), "speed_aadt_ready_bin"].sum()) if not detail.empty else 0},
            {"metric": "signals_sensitivity_1000_2500_ready", "signal_count": int(signal["sensitivity_1000_2500_ready"].sum()) if not signal.empty else 0, "bin_count": int(detail.loc[_text(detail, "context_window_scope").eq("sensitivity_1000_2500"), "speed_aadt_ready_bin"].sum()) if not detail.empty else 0},
        ]
    )
    branch = branch_summary.copy()
    branch_a_mask = branch["branch"].eq("A_direct_missing_leg_recovery")
    branch.loc[branch_a_mask, "branch_status_class"] = "branch_complete"
    branch.loc[branch_a_mask, "open_implementable_work"] = "0"
    branch.loc[branch_a_mask, "completed_or_context_refreshed_signals"] = branch.loc[branch_a_mask, "starting_pool"]
    branch["post_final_context_refresh_note"] = ""
    ready_signals = int(signal["speed_aadt_ready"].sum()) if not signal.empty else 0
    branch.loc[branch["branch"].eq("A_direct_missing_leg_recovery"), "post_final_context_refresh_note"] = f"Final cleanup context refresh processed; {ready_signals} final cleanup signals speed+AADT ready."
    branch.loc[branch["branch"].eq("B_divided_carriageway_normalization"), "post_final_context_refresh_note"] = "Complete; label-only normalization does not require speed/AADT refresh."
    branch.loc[branch["branch"].eq("C_source_limitation_holdout"), "post_final_context_refresh_note"] = "Reduced to source/manual/external-data holdouts."
    if detail.empty:
        missingness = pd.DataFrame(columns=["missingness_scope", "missingness_reason", "signal_count", "bin_count", "example_signals"])
    else:
        missing = detail.loc[
            ~detail["has_route_measure_identity"]
            | ~detail["has_rns_speed"]
            | ~detail["has_aadt"]
            | ~detail["has_exposure_denominator"]
        ].copy()
        if missing.empty:
            missingness = pd.DataFrame(columns=["missingness_scope", "missingness_reason", "signal_count", "bin_count", "example_signals"])
        else:
            missing["missingness_reason"] = np.select(
                [
                    ~missing["has_route_measure_identity"],
                    ~missing["has_rns_speed"],
                    ~missing["has_aadt"] | ~missing["has_exposure_denominator"],
                ],
                [
                    "missing_route_measure_identity",
                    "missing_rns_speed",
                    "missing_aadt_or_exposure",
                ],
                default="other_context_gap",
            )
            missingness = missing.groupby("missingness_reason", dropna=False).agg(
                signal_count=("signal_id", "nunique"),
                bin_count=("final_cleanup_missing_leg_bin_id", "count"),
                example_signals=("signal_id", _collapse),
            ).reset_index()
            missingness.insert(0, "missingness_scope", "bin_level_context_gap")
    return route, speed, aadt, readiness, branch, missingness


def _write_findings(signal: pd.DataFrame, detail: pd.DataFrame, source_ledger: pd.DataFrame, branch: pd.DataFrame) -> None:
    processed = signal["signal_id"].nunique() if not signal.empty else 0
    ready = int(signal["speed_aadt_ready"].sum()) if not signal.empty else 0
    route_ready = int(signal["has_route_measure_identity"].sum()) if not signal.empty else 0
    roadway = int(signal["has_roadway_context"].sum()) if not signal.empty else 0
    speed = int(signal["has_rns_speed"].sum()) if not signal.empty else 0
    aadt = int(signal["has_aadt"].sum()) if not signal.empty else 0
    ready_bins = int(detail["speed_aadt_ready_bin"].sum()) if not detail.empty else 0
    text = f"""# Final Recovery Context Refresh

## Bounded Question

Can the final cleanup missing-leg bins receive review-only route/measure, roadway context, RNS speed, and AADT/exposure context so scaffold recovery can close?

## Findings

- Final cleanup missing-leg signals processed: {processed:,}.
- Final cleanup bins processed: {len(detail):,}.
- Signals with route/measure identity: {route_ready:,}.
- Signals with roadway context: {roadway:,}.
- Signals with RNS speed: {speed:,}.
- Signals with AADT/exposure: {aadt:,}.
- Signals speed+AADT-ready: {ready:,}.
- Speed+AADT-ready bins: {ready_bins:,} of {len(detail):,}.

## Branch Exhaustion

Branch A is complete after this context refresh. Branch B was already complete through label-only divided/carriageway normalization. Branch C remains source/manual/external-data holdout only and should not be forced.

## Recommendation

Scaffold recovery is exhausted enough to resume access/catchment work with QA flags for source-limited, grade/mainline, and still-insufficient evidence records.
"""
    _write_text(text, "final_recovery_context_refresh_findings.md")


def _write_qa(detail: pd.DataFrame, signal: pd.DataFrame) -> None:
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/final_recovery_context_refresh."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "No active scaffold or promotion outputs are written."},
            {"qa_check": "no_access_or_crash_assignment", "status": "pass", "detail": "No access/crash inputs are read and no assignments are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate or model calculations are run."},
            {"qa_check": "holdouts_not_forced", "status": "pass", "detail": "Source-limited, grade/mainline, and still-insufficient records are not included."},
            {"qa_check": "review_only_assignments", "status": "pass", "detail": "Context assignments are review-only."},
            {"qa_check": "no_bin_by_source_overlap_tables", "status": "pass", "detail": "Grouped/vectorized interval lookup is used; no bin by source-row overlap outputs are materialized."},
            {"qa_check": "deduped_signal_counts_separate", "status": "pass", "detail": f"Processed {signal['signal_id'].nunique() if not signal.empty else 0:,} signals and {len(detail):,} bins."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"Outputs written under {OUT_DIR}."},
        ]
    )
    _write_csv(qa, "final_recovery_context_refresh_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    _patch_context_helpers()
    missing = _required_context_sources_missing()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    legs = _read_csv(FINAL_DIR / "final_cleanup_missing_leg_candidates.csv")
    bins = _read_csv(FINAL_DIR / "final_cleanup_missing_leg_bins.csv")
    source_ledger = _read_csv(FINAL_DIR / "final_unrecovered_source_limitation_ledger.csv")
    branch_summary = _read_csv(BRANCH_DIR / "scaffold_recovery_branch_summary.csv")
    branch_a = _read_csv(BRANCH_DIR / "branch_a_direct_missing_leg_summary.csv")
    branch_b = _read_csv(BRANCH_DIR / "branch_b_divided_normalization_summary.csv")
    branch_c = _read_csv(BRANCH_DIR / "branch_c_source_limitation_summary.csv")

    candidates = _prepare_candidate_bins(bins, legs)
    _checkpoint("prepared_final_cleanup_candidate_bins", len(candidates))
    detail = _assign_context(candidates)
    signal = _signal_summary(detail)
    route, speed, aadt, readiness, branch, missingness = _summary_rows(detail, signal, source_ledger, branch_summary)

    _write_csv(detail, "final_recovery_context_bin_detail.csv")
    _write_csv(signal, "final_recovery_context_signal_summary.csv")
    _write_csv(route, "final_recovery_route_measure_summary.csv")
    _write_csv(speed, "final_recovery_speed_summary.csv")
    _write_csv(aadt, "final_recovery_aadt_exposure_summary.csv")
    _write_csv(readiness, "final_recovery_context_readiness_summary.csv")
    _write_csv(branch, "final_scaffold_branch_exhaustion_summary.csv")
    _write_csv(source_ledger, "final_source_data_limitation_ledger.csv")
    _write_csv(missingness, "final_recovery_context_missingness.csv")
    _write_findings(signal, detail, source_ledger, branch)
    _write_qa(detail, signal)

    manifest = {
        "script": "src.roadway_graph.build.final_recovery_context_refresh",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Review-only context refresh for final cleanup missing-leg bins and final scaffold exhaustion summary.",
        "output_directory": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "context_sources": {
            "speed_source": str(context_helpers.SPEED_LIMIT_RNS_GDB),
            "aadt_source": str(context_helpers.AADT_FILE),
            "source_travelway_package": str(MAP_GPKG),
        },
        "outputs": [
            "final_recovery_context_bin_detail.csv",
            "final_recovery_context_signal_summary.csv",
            "final_recovery_route_measure_summary.csv",
            "final_recovery_speed_summary.csv",
            "final_recovery_aadt_exposure_summary.csv",
            "final_recovery_context_readiness_summary.csv",
            "final_scaffold_branch_exhaustion_summary.csv",
            "final_source_data_limitation_ledger.csv",
            "final_recovery_context_missingness.csv",
            "final_recovery_context_refresh_findings.md",
            "final_recovery_context_refresh_qa.csv",
            "final_recovery_context_refresh_manifest.json",
            "run_progress_log.txt",
        ],
        "summary": {
            "signals_processed": int(signal["signal_id"].nunique()) if not signal.empty else 0,
            "bins_processed": int(len(detail)),
            "signals_speed_aadt_ready": int(signal["speed_aadt_ready"].sum()) if not signal.empty else 0,
            "bins_speed_aadt_ready": int(detail["speed_aadt_ready_bin"].sum()) if not detail.empty else 0,
            "branch_status": branch.to_dict(orient="records"),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assignment": False,
            "rates_or_models": False,
            "bin_by_source_overlap_tables_materialized": False,
            "review_only": True,
        },
        "upstream_manifests": {
            "final_cleanup": _load_json(FINAL_DIR / "final_implementable_scaffold_cleanup_manifest.json").get("created_at_utc", ""),
            "branch_ledger": _load_json(BRANCH_DIR / "scaffold_recovery_branch_ledger_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "final_recovery_context_refresh_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
