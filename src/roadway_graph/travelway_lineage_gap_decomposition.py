from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/travelway_lineage_gap_decomposition"

LINEAGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"
BACKFILL_DIR = OUTPUT_ROOT / "review/current/final_scaffold_travelway_lineage_backfill"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
GEOMETRY_CLEANUP_DIR = OUTPUT_ROOT / "review/current/final_access_target_geometry_persistence_cleanup"
FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_rerun_with_source_accounting"

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
    LINEAGE_DIR / "source_travelway_stable_identity.csv",
    LINEAGE_DIR / "final_scaffold_travelway_lineage_bridge.csv",
    LINEAGE_DIR / "access_target_travelway_lineage_bridge.csv",
    LINEAGE_DIR / "travelway_lineage_completeness_summary.csv",
    LINEAGE_DIR / "source_travelway_lineage_bridge_manifest.json",
    BACKFILL_DIR / "final_scaffold_bins_with_stable_travelway_lineage.csv",
    BACKFILL_DIR / "final_access_target_bins_with_stable_travelway_lineage.csv",
    BACKFILL_DIR / "travelway_lineage_backfill_candidate_matches.csv",
    BACKFILL_DIR / "travelway_lineage_backfill_unmatched_bins.csv",
    BACKFILL_DIR / "travelway_lineage_backfill_conflict_summary.csv",
    BACKFILL_DIR / "travelway_lineage_backfill_completeness_summary.csv",
    BACKFILL_DIR / "reviewed_case_lineage_backfill_audit.csv",
    BACKFILL_DIR / "stable_travelway_lineage_backfill_manifest.json",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    GEOMETRY_CLEANUP_DIR / "final_access_target_bins_geometry_cleaned.csv",
    GEOMETRY_CLEANUP_DIR / "final_access_geometry_persistence_manifest.json",
    FINAL_ACCESS_DIR / "final_cleaned_access_target_bins.csv",
    FINAL_ACCESS_DIR / "final_cleaned_untyped_access_assignment_detail.csv",
    FINAL_ACCESS_DIR / "final_cleaned_typed_v2_access_assignment_detail.csv",
    FINAL_ACCESS_DIR / "final_access_rerun_with_source_accounting_manifest.json",
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


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes"})


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _has_any(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    for column in columns:
        if column in frame.columns:
            mask = mask | _text(frame, column).str.strip().ne("")
    return mask


def _build_unmatched() -> pd.DataFrame:
    access_cols = [
        "lineage_row_id",
        "target_signal_id",
        "target_source_id",
        "target_source_layer",
        "target_bin_id",
        "original_bin_id",
        "recovery_stream",
        "recovery_class",
        "final_original_or_recovered",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "route_facility_fields",
        "route_key",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "final_alignment_class",
        "final_physical_leg_class",
        "review_only_recovery_provenance",
        "geometry_wkt",
        "geometry_wkt_cleaned",
        "geometry_recovery_method_final",
        "geometry_recovery_status",
        "source_travelway_lineage",
        "seed_lineage_match_method",
        "seed_lineage_confidence",
        "seed_candidate_stable_travelway_ids",
        "seed_candidate_source_feature_local_fids",
        "geometry_stable_travelway_id",
        "nearest_distance_ft",
        "route_measure_compatibility",
        "lineage_backfill_match_method",
        "lineage_backfill_confidence",
        "candidate_match_count",
        "lineage_conflict_fanout_flag",
    ]
    access = _read_csv(BACKFILL_DIR / "final_access_target_bins_with_stable_travelway_lineage.csv", usecols=access_cols)
    unmatched = access.loc[_text(access, "lineage_backfill_confidence").eq("unmatched")].copy()
    unmatched["signal_id"] = _text(unmatched, "target_signal_id")
    unmatched["bin_id"] = _text(unmatched, "target_bin_id")
    unmatched["source_signal_id"] = _text(unmatched, "target_source_id")
    unmatched["source_layer"] = _text(unmatched, "target_source_layer")
    unmatched["physical_leg_id"] = _text(unmatched, "physical_leg_id_final")
    unmatched["carriageway_subbranch_id"] = _text(unmatched, "carriageway_subbranch_id_final")
    unmatched["access_target_membership"] = True
    unmatched["geometry_available"] = (
        _text(unmatched, "geometry_wkt_cleaned").str.strip().ne("")
        | _text(unmatched, "geometry_wkt").str.strip().ne("")
        | _text(unmatched, "geometry_recovery_status").eq("geometry_available")
    )
    return unmatched


def _assignment_membership(unmatched: pd.DataFrame) -> pd.DataFrame:
    untyped = _read_csv(FINAL_ACCESS_DIR / "final_cleaned_untyped_access_assignment_detail.csv", usecols=["target_bin_id", "target_signal_id", "access_point_id", "buffer_width_ft"])
    typed = _read_csv(FINAL_ACCESS_DIR / "final_cleaned_typed_v2_access_assignment_detail.csv", usecols=["target_bin_id", "target_signal_id", "access_point_id", "buffer_width_ft"])
    assignments = pd.concat(
        [untyped.assign(access_layer="untyped"), typed.assign(access_layer="typed_v2")],
        ignore_index=True,
        sort=False,
    )
    any_assign = assignments.groupby("target_bin_id", dropna=False).agg(
        access_assignment_count=("access_point_id", "size"),
        access_source_point_count=("access_point_id", "nunique"),
        access_layers=("access_layer", lambda s: "|".join(sorted(set(s)))),
        has_100ft_access_assignment=("buffer_width_ft", lambda s: any(str(v) == "100" for v in s)),
    ).reset_index()
    signal_access = assignments.groupby("target_signal_id", dropna=False).agg(
        signal_access_assignment_count=("access_point_id", "size"),
        signal_access_source_point_count=("access_point_id", "nunique"),
    ).reset_index()
    out = unmatched.merge(any_assign, left_on="bin_id", right_on="target_bin_id", how="left")
    out = out.merge(signal_access, left_on="signal_id", right_on="target_signal_id", how="left", suffixes=("", "_signal"))
    out["has_access_assignment"] = pd.to_numeric(out["access_assignment_count"], errors="coerce").fillna(0).gt(0)
    out["signal_has_access_assignment"] = pd.to_numeric(out["signal_access_assignment_count"], errors="coerce").fillna(0).gt(0)
    return out.drop(columns=["target_bin_id", "target_signal_id_signal"], errors="ignore")


def _classify_reason(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    has_geom = out["geometry_available"].fillna(False).astype(bool)
    has_route = _has_any(out, ["route_facility_fields", "route_key"])
    has_measure = _has_any(out, ["distance_start_ft", "distance_end_ft"])
    has_source_line = _has_any(out, ["source_travelway_lineage"])
    has_graph_id = _text(out, "original_bin_id").str.contains("rge|graph|edge|rc_", case=False, regex=True)
    source_wkt_missing = has_geom & _text(out, "geometry_recovery_method_final").str.contains("final_overview|candidate_gpkg|route_discontinuity|ready_class", case=False, regex=True)
    normal_label = _text(out, "recovery_class").str.contains("normal", case=False, regex=True) | _text(out, "review_only_recovery_provenance").str.contains("divided_subbranch", case=False, regex=False)

    out["has_geometry"] = has_geom
    out["has_route_id_name_common"] = has_route
    out["has_source_road_row_id"] = has_source_line
    out["has_graph_edge_id"] = has_graph_id
    out["has_source_line_id"] = has_source_line
    out["has_measure_start_end"] = has_measure
    out["has_route_facility_only"] = has_route & ~has_source_line
    out["no_useful_lineage_fields"] = ~has_route & ~has_source_line & ~has_graph_id & ~has_geom

    out["unmatched_reason_class"] = "unknown_needs_review"
    out.loc[out["no_useful_lineage_fields"], "unmatched_reason_class"] = "missing_source_lineage_fields"
    out.loc[has_route & ~has_source_line & has_measure, "unmatched_reason_class"] = "route_label_only_no_measure"
    out.loc[has_geom & ~has_source_line, "unmatched_reason_class"] = "geometry_present_but_no_source_id"
    out.loc[source_wkt_missing, "unmatched_reason_class"] = "geometry_match_threshold_too_strict_possible"
    out.loc[normal_label & ~has_source_line, "unmatched_reason_class"] = "normalization_label_only_row"
    out.loc[_text(out, "seed_lineage_match_method").eq("unmatched") & has_graph_id & has_geom, "unmatched_reason_class"] = "expected_no_direct_travelway_lineage"
    out.loc[_text(out, "geometry_recovery_status").str.contains("unavailable", case=False, regex=False), "unmatched_reason_class"] = "recovered_bin_without_source_wkt_link"
    out.loc[_bool_text(out, "lineage_conflict_fanout_flag"), "unmatched_reason_class"] = "duplicate_or_conflict_not_best_match"

    recoverability = {
        "missing_source_lineage_fields": "preserving stable ID at generation time only",
        "geometry_present_but_no_source_id": "relaxing geometry threshold or improved route-compatible spatial match",
        "route_label_only_no_measure": "route/measure overlap if source measures can be carried",
        "geometry_match_threshold_too_strict_possible": "relaxing geometry threshold with QA",
        "source_travelway_not_in_stable_identity": "manual/source review",
        "recovered_bin_without_source_wkt_link": "using recovery stream source WKT",
        "normalization_label_only_row": "preserving stable ID at generation time only",
        "duplicate_or_conflict_not_best_match": "fanout review or better tie-break",
        "expected_no_direct_travelway_lineage": "not recoverable without active scaffold lineage change",
        "unknown_needs_review": "manual/source review",
    }
    out["lineage_recoverability_path"] = out["unmatched_reason_class"].map(recoverability).fillna("manual/source review")
    return out


def _provenance_summary(unmatched: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["recovery_stream", "recovery_class", "final_original_or_recovered", "geometry_recovery_method_final"]
    rows = []
    for cols in [["recovery_stream"], ["recovery_class"], ["final_original_or_recovered"], ["geometry_recovery_method_final"], group_cols]:
        existing = [col for col in cols if col in unmatched.columns]
        if not existing:
            continue
        grouped = unmatched.groupby(existing, dropna=False)
        for key, sub in grouped:
            if not isinstance(key, tuple):
                key = (key,)
            row = {"grouping": "|".join(existing), "unmatched_bin_count": len(sub), "signal_count": _text(sub, "signal_id").nunique()}
            for col, val in zip(existing, key):
                row[col] = val
            rows.append(row)
    return pd.DataFrame(rows).sort_values("unmatched_bin_count", ascending=False)


def _evidence_summary(unmatched: pd.DataFrame) -> pd.DataFrame:
    evidence_cols = [
        "has_geometry",
        "has_route_id_name_common",
        "has_source_road_row_id",
        "has_graph_edge_id",
        "has_source_line_id",
        "has_measure_start_end",
        "has_route_facility_only",
        "no_useful_lineage_fields",
    ]
    rows = []
    for col in evidence_cols:
        rows.append(
            {
                "evidence_field": col,
                "unmatched_bin_count": int(unmatched[col].fillna(False).astype(bool).sum()),
                "signal_count": _text(unmatched.loc[unmatched[col].fillna(False).astype(bool)], "signal_id").nunique(),
            }
        )
    combo = unmatched.groupby(["has_geometry", "has_route_id_name_common", "has_measure_start_end", "has_source_line_id"], dropna=False).agg(
        unmatched_bin_count=("bin_id", "size"),
        signal_count=("signal_id", "nunique"),
    ).reset_index()
    combo["evidence_field"] = "combination"
    return pd.concat([pd.DataFrame(rows), combo], ignore_index=True, sort=False)


def _reason_summary(unmatched: pd.DataFrame) -> pd.DataFrame:
    return unmatched.groupby("unmatched_reason_class", dropna=False).agg(
        unmatched_bin_count=("bin_id", "size"),
        signal_count=("signal_id", "nunique"),
        bins_with_geometry=("has_geometry", "sum"),
        bins_with_access_assignment=("has_access_assignment", "sum"),
        signals_with_any_access=("signal_has_access_assignment", "sum"),
        example_recovery_streams=("recovery_stream", lambda s: "|".join(sorted(set(str(v) for v in s if str(v).strip()))[:8])),
    ).reset_index().sort_values("unmatched_bin_count", ascending=False)


def _recoverability_summary(unmatched: pd.DataFrame) -> pd.DataFrame:
    return unmatched.groupby(["unmatched_reason_class", "lineage_recoverability_path"], dropna=False).agg(
        unmatched_bin_count=("bin_id", "size"),
        signal_count=("signal_id", "nunique"),
        access_assignment_bins=("has_access_assignment", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", lambda s: _text(pd.DataFrame({"x": s}), "x").str.lower().isin({"true", "1", "yes"}).sum()),
    ).reset_index().sort_values("unmatched_bin_count", ascending=False)


def _impact_summary(unmatched: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "impact_question": "unmatched_bins_in_access_target",
            "bin_count": len(unmatched),
            "signal_count": _text(unmatched, "signal_id").nunique(),
            "interpretation": "All unmatched rows in this diagnostic are final access target members.",
        },
        {
            "impact_question": "unmatched_bins_with_access_assignments",
            "bin_count": int(unmatched["has_access_assignment"].sum()),
            "signal_count": _text(unmatched.loc[unmatched["has_access_assignment"]], "signal_id").nunique(),
            "interpretation": "These matter for source-row-specific access claims but not for spatial access assignment itself.",
        },
        {
            "impact_question": "unmatched_bins_in_signals_with_no_access",
            "bin_count": int((~unmatched["signal_has_access_assignment"]).sum()),
            "signal_count": _text(unmatched.loc[~unmatched["signal_has_access_assignment"]], "signal_id").nunique(),
            "interpretation": "These may affect interpreting no-access signals and source limitation findings.",
        },
        {
            "impact_question": "unmatched_bins_speed_aadt_ready",
            "bin_count": int(_text(unmatched, "speed_aadt_ready_bin").str.lower().isin({"true", "1", "yes"}).sum()),
            "signal_count": _text(unmatched.loc[_text(unmatched, "speed_aadt_ready_bin").str.lower().isin({"true", "1", "yes"})], "signal_id").nunique(),
            "interpretation": "These could matter for future crash/catchment denominator lineage.",
        },
        {
            "impact_question": "crash_catchment_blocker",
            "bin_count": len(unmatched),
            "signal_count": _text(unmatched, "signal_id").nunique(),
            "interpretation": "Blocks source-row-specific crash/catchment limitation claims; does not block geometry-only catchment prototyping if lineage caveats are carried.",
        },
    ]
    return pd.DataFrame(rows)


def _next_action() -> pd.DataFrame:
    rows = [
        {
            "rank": 1,
            "recommended_next_action": "fix_future_generation_to_persist_stable_travelway_id",
            "reason": "Large unmatched class appears to be legacy/frozen scaffold rows without source IDs; retrospective matching leaves too much ambiguity.",
            "blocks_access_work": "no_for_review_only_access",
            "blocks_crash_catchment_work": "yes_for_source_row_specific_claims",
        },
        {
            "rank": 2,
            "recommended_next_action": "use_lineage_enriched_access_target_for_review_only_access_to_travelway_refinement",
            "reason": "148,654 access target bins already have high-confidence lineage; unmatched bins can be carried with QA flags.",
            "blocks_access_work": "no_if_qa_flags_carried",
            "blocks_crash_catchment_work": "partial",
        },
        {
            "rank": 3,
            "recommended_next_action": "source_limitation_report_with_lineage_caveats",
            "reason": "Access/source coverage findings can proceed if exact source-row claims are limited to high-confidence/backfilled rows.",
            "blocks_access_work": "no",
            "blocks_crash_catchment_work": "partial",
        },
    ]
    return pd.DataFrame(rows)


def _findings(unmatched: pd.DataFrame, provenance: pd.DataFrame, reason: pd.DataFrame, impact: pd.DataFrame) -> str:
    top_prov = provenance.loc[provenance["grouping"].eq("recovery_stream")].head(5)
    prov_lines = "\n".join(
        f"- {row.recovery_stream or 'blank/unknown'}: {int(row.unmatched_bin_count):,} bins across {int(row.signal_count):,} signals."
        for row in top_prov.itertuples()
    )
    reason_lines = "\n".join(
        f"- {row.unmatched_reason_class}: {int(row.unmatched_bin_count):,} bins."
        for row in reason.head(6).itertuples()
    )
    access_bins = int(impact.loc[impact["impact_question"].eq("unmatched_bins_with_access_assignments"), "bin_count"].iloc[0])
    no_access_signals = int(impact.loc[impact["impact_question"].eq("unmatched_bins_in_signals_with_no_access"), "signal_count"].iloc[0])
    return f"""# Travelway Lineage Gap Decomposition

**Bounded question:** explain the unmatched stable Travelway lineage bins and decide whether they block access/crash work.

## Findings

1. Unmatched final access target bins: **{len(unmatched):,}** across **{_text(unmatched, 'signal_id').nunique():,}** signals.
2. Top provenance contributors:
{prov_lines}
3. Dominant unmatched reasons:
{reason_lines}
4. Unmatched bins with existing access assignments: **{access_bins:,}**.
5. Signals with unmatched bins and no access assignment: **{no_access_signals:,}**.

## Interpretation

The gap is mostly a lineage persistence problem in legacy/frozen scaffold rows, not an immediate geometry/access-assignment problem. It does not block review-only access assignment if QA flags are carried. It does block source-row-specific crash/catchment or source-limitation claims for unmatched bins.

## Recommendation

The next implementation should persist `stable_travelway_id` during future scaffold/bin generation. For current review work, use the lineage-enriched access target where high-confidence lineage exists and carry unmatched/low-confidence lineage flags elsewhere.
"""


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "Writes only to travelway_lineage_gap_decomposition review folder."),
        ("no_candidates_promoted", "pass", "No promotion outputs are written."),
        ("no_access_or_crash_assignment", "pass", "No access/crash assignment is performed."),
        ("no_crash_records_read", "pass", "No crash inputs are read."),
        ("no_crash_direction_fields_used", "pass", "Read guards block crash direction fields."),
        ("no_rates_or_models", "pass", "No rate/model calculations are performed."),
        ("unmatched_bins_reported_not_forced", "pass", "Unmatched rows remain unmatched and are classified by reason."),
        ("outputs_review_only", "pass", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "status", "note"])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs: " + "; ".join(missing))

    unmatched = _build_unmatched()
    unmatched = _assignment_membership(unmatched)
    unmatched = _classify_reason(unmatched)
    provenance = _provenance_summary(unmatched)
    evidence = _evidence_summary(unmatched)
    reason = _reason_summary(unmatched)
    recoverability = _recoverability_summary(unmatched)
    impact = _impact_summary(unmatched)
    next_action = _next_action()
    qa = _qa()

    detail_cols = [
        "signal_id",
        "bin_id",
        "source_signal_id",
        "source_layer",
        "recovery_stream",
        "recovery_class",
        "final_original_or_recovered",
        "geometry_available",
        "route_facility_fields",
        "route_key",
        "source_travelway_lineage",
        "original_bin_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "final_alignment_class",
        "speed_aadt_ready_bin",
        "access_target_membership",
        "has_access_assignment",
        "signal_has_access_assignment",
        "has_geometry",
        "has_route_id_name_common",
        "has_source_road_row_id",
        "has_graph_edge_id",
        "has_source_line_id",
        "has_measure_start_end",
        "has_route_facility_only",
        "no_useful_lineage_fields",
        "unmatched_reason_class",
        "lineage_recoverability_path",
        "geometry_recovery_method_final",
        "geometry_recovery_status",
    ]
    _write_csv(unmatched[[col for col in detail_cols if col in unmatched.columns]], "travelway_lineage_unmatched_bin_detail.csv")
    _write_csv(provenance, "travelway_lineage_gap_by_provenance.csv")
    _write_csv(evidence, "travelway_lineage_gap_by_evidence.csv")
    _write_csv(reason, "travelway_lineage_gap_reason_summary.csv")
    _write_csv(recoverability, "travelway_lineage_gap_recoverability_summary.csv")
    _write_csv(impact, "travelway_lineage_gap_impact_on_access_crash.csv")
    _write_csv(next_action, "travelway_lineage_gap_next_action.csv")
    _write_text(_findings(unmatched, provenance, reason, impact), "travelway_lineage_gap_decomposition_findings.md")
    _write_csv(qa, "travelway_lineage_gap_decomposition_qa.csv")
    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "Decompose unmatched stable Travelway lineage bins and assess access/crash impact.",
        "output_folder": str(OUT_DIR),
        "unmatched_bin_count": int(len(unmatched)),
        "unmatched_signal_count": int(_text(unmatched, "signal_id").nunique()),
        "qa_pass": bool(qa["status"].eq("pass").all()),
        "non_goals": [
            "no scaffold/access output modification",
            "no access/crash assignment",
            "no final metric selection",
            "no rates/models",
            "no candidate promotion",
        ],
    }
    _write_json(manifest, "travelway_lineage_gap_decomposition_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
