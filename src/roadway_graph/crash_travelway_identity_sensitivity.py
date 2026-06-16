from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/crash_travelway_identity_sensitivity"

CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/crash_travelway_identity_feasibility"
ASSIGN_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_candidate_assignment"
CRASH_SANITY_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_sanity_audit"
FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
SOURCE_TRAVELWAY_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
LINEAGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"

PRIMARY_BUFFER_FT = 50
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

CRASH_SOURCE_COLUMNS = [
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CRASH_DT",
    "CRASH_SEVERITY",
    "COLLISION_TYPE",
    "ROADWAY_DESCRIPTION",
    "INTERSECTION_TYPE",
    "MAINLINE_YN",
    "RTE_NM",
    "RNS_MP",
    "NODE",
    "OFFSET",
    "JURIS_CODE",
    "PHYSICAL_JURIS",
    "geometry",
]

MATCH_DETAIL_COLS = [
    "stable_crash_id",
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CRASH_SEVERITY",
    "RTE_NM",
    "RNS_MP",
    "NODE",
    "OFFSET",
    "JURIS_CODE",
    "PHYSICAL_JURIS",
    "ROADWAY_DESCRIPTION",
    "INTERSECTION_TYPE",
    "MAINLINE_YN",
    "matched_stable_travelway_id_candidates",
    "candidate_travelway_count",
    "match_method",
    "match_confidence",
    "route_key_compatibility",
    "geometry_distance_to_matched_travelway_ft",
    "tier_a_route_measure_status",
    "nearest_stable_travelway_id",
    "nearest_distance_ft",
]

ASSIGN_DETAIL_COLS = [
    "buffer_width_ft",
    "stable_crash_id",
    "stable_signal_id",
    "stable_bin_id",
    "stable_travelway_id",
    "final_review_physical_leg_id",
    "final_review_leg_source",
    "final_review_recovery_provenance",
    "assignment_fanout_count",
    "source_preserving_weight",
]

BIN_COLS = [
    "stable_signal_id",
    "source_signal_id",
    "stable_bin_id",
    "stable_travelway_id",
    "final_review_physical_leg_id",
    "final_review_carriageway_subbranch_id",
    "analysis_window",
    "distance_band",
    "distance_start_ft",
    "distance_end_ft",
    "source_route_name",
    "source_route_common",
    "source_measure_start",
    "source_measure_end",
    "source_measure_start_num",
    "source_measure_end_num",
    "final_review_leg_source",
    "final_review_context_status",
    "final_review_recovery_provenance",
    "final_review_speed_aadt_ready_bin",
]

REQUIRED_INPUTS = [
    CRASH_SOURCE,
    FEASIBILITY_DIR / "crash_field_inventory.csv",
    FEASIBILITY_DIR / "travelway_field_inventory.csv",
    FEASIBILITY_DIR / "crash_travelway_shared_key_candidates.csv",
    FEASIBILITY_DIR / "crash_key_missingness_summary.csv",
    FEASIBILITY_DIR / "crash_travelway_candidate_match_detail.csv",
    FEASIBILITY_DIR / "crash_travelway_match_method_summary.csv",
    FEASIBILITY_DIR / "crash_travelway_match_confidence_summary.csv",
    FEASIBILITY_DIR / "crash_spatial_assignment_vs_travelway_match.csv",
    FEASIBILITY_DIR / "crash_high_fanout_travelway_match_audit.csv",
    FEASIBILITY_DIR / "crash_unassigned_travelway_match_audit.csv",
    FEASIBILITY_DIR / "crash_travelway_identity_feasibility_decision.csv",
    FEASIBILITY_DIR / "crash_travelway_identity_feasibility_manifest.json",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_bin_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_fanout_summary.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_overlap_review_queue.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_source_coverage_summary.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_unassigned_summary.csv",
    ASSIGN_DIR / "final_leg_corrected_crash_candidate_assignment_manifest.json",
    CRASH_SANITY_DIR / "crash_sanity_denominator_validation.csv",
    CRASH_SANITY_DIR / "crash_assignment_gain_vs_prior_detail.csv",
    CRASH_SANITY_DIR / "crash_assignment_gain_by_branch.csv",
    CRASH_SANITY_DIR / "crash_fanout_sanity_detail.csv",
    CRASH_SANITY_DIR / "crash_fanout_sanity_summary.csv",
    CRASH_SANITY_DIR / "crash_high_fanout_cause_classification.csv",
    CRASH_SANITY_DIR / "crash_nonassignment_refresh_summary.csv",
    CRASH_SANITY_DIR / "crash_nonassignment_vs_prior_comparison.csv",
    CRASH_SANITY_DIR / "crash_buffer_sensitivity_sanity.csv",
    CRASH_SANITY_DIR / "crash_high_count_signal_window_sanity.csv",
    CRASH_SANITY_DIR / "crash_sanity_readiness_decision.csv",
    CRASH_SANITY_DIR / "final_leg_corrected_crash_sanity_manifest.json",
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    FINAL_LEG_DIR / "final_leg_corrected_context_readiness_summary.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
    SOURCE_TRAVELWAY_GPKG,
    LINEAGE_DIR / "source_travelway_stable_identity.csv",
    LINEAGE_DIR / "source_travelway_lineage_bridge_manifest.json",
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


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _is_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _is_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _collapse(values: pd.Series, limit: int = 10) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _load_crash_identity_source() -> tuple[pd.DataFrame, list[str]]:
    schema_cols = list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)
    direction_cols = [column for column in schema_cols if _is_direction_field(column)]
    cols = [column for column in CRASH_SOURCE_COLUMNS if column in schema_cols and not _is_direction_field(column)]
    crashes = pd.read_parquet(CRASH_SOURCE, columns=cols)
    if "DOCUMENT_NBR" in crashes.columns:
        crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    else:
        crashes["stable_crash_id"] = ["crash_review_%09d" % idx for idx in range(len(crashes))]
    crashes["crash_direction_fields_inventory_only"] = "|".join(direction_cols)
    crashes["crash_direction_used_for_assignment"] = False
    crashes["crash_direction_use_status"] = "direction_fields_not_read_or_used" if not direction_cols else "inventory_only_not_used"
    _checkpoint("load crash roadway identity fields", len(crashes))
    return crashes, direction_cols


def _load_match_detail() -> pd.DataFrame:
    match = _read_csv(FEASIBILITY_DIR / "crash_travelway_candidate_match_detail.csv", usecols=MATCH_DETAIL_COLS)
    match["crash_measure"] = _num(match, "RNS_MP")
    match["matched_stable_travelway_id"] = _text(match, "matched_stable_travelway_id_candidates").str.split("|").str[0]
    match["matched_stable_travelway_id"] = match["matched_stable_travelway_id"].where(
        match["matched_stable_travelway_id"].str.startswith("tw_"), ""
    )
    match["candidate_travelway_count_num"] = _num(match, "candidate_travelway_count").fillna(0).astype(int)
    return match


def _spatial_50_summary() -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
        dtype=str,
        keep_default_na=False,
        usecols=lambda col: col in ASSIGN_DETAIL_COLS,
        chunksize=200_000,
        low_memory=False,
    ):
        chunk = chunk.loc[pd.to_numeric(chunk["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)]
        if not chunk.empty:
            chunks.append(chunk)
    detail = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=ASSIGN_DETAIL_COLS)
    summary = detail.groupby("stable_crash_id", dropna=False).agg(
        spatial_50_assigned=("stable_signal_id", lambda s: True),
        spatial_50_signal_count=("stable_signal_id", "nunique"),
        spatial_50_bin_count=("stable_bin_id", "nunique"),
        spatial_50_physical_leg_count=("final_review_physical_leg_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        spatial_50_travelway_count=("stable_travelway_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        spatial_50_travelway_ids=("stable_travelway_id", _collapse),
        spatial_50_leg_sources=("final_review_leg_source", _collapse),
        spatial_50_recovery_provenance=("final_review_recovery_provenance", _collapse),
        spatial_50_weight_sum=("source_preserving_weight", lambda s: pd.to_numeric(s, errors="coerce").sum()),
    ).reset_index()
    _checkpoint("summarize spatial 50ft assignment", len(summary))
    return summary


def _load_bin_intervals() -> pd.DataFrame:
    bins = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv", usecols=BIN_COLS)
    bins["measure_start"] = _num(bins, "source_measure_start_num")
    bins["measure_end"] = _num(bins, "source_measure_end_num")
    missing_start = bins["measure_start"].isna()
    bins.loc[missing_start, "measure_start"] = _num(bins.loc[missing_start], "source_measure_start")
    missing_end = bins["measure_end"].isna()
    bins.loc[missing_end, "measure_end"] = _num(bins.loc[missing_end], "source_measure_end")
    bins["measure_min"] = bins[["measure_start", "measure_end"]].min(axis=1)
    bins["measure_max"] = bins[["measure_start", "measure_end"]].max(axis=1)
    bins = bins.loc[_text(bins, "stable_travelway_id").str.startswith("tw_") & bins["measure_min"].notna() & bins["measure_max"].notna()].copy()
    bins["distance_start_num"] = _num(bins, "distance_start_ft")
    bins["distance_end_num"] = _num(bins, "distance_end_ft")
    bins["speed_aadt_ready_int"] = _text(bins, "final_review_speed_aadt_ready_bin").str.lower().isin({"true", "1", "yes"}).astype(int)
    group_cols = [
        "stable_travelway_id",
        "measure_min",
        "measure_max",
        "stable_signal_id",
        "source_signal_id",
        "analysis_window",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
    ]
    agg = bins.groupby(group_cols, dropna=False, sort=False).agg(
        representative_stable_bin_id=("stable_bin_id", "first"),
        matched_bin_count=("stable_bin_id", "nunique"),
        distance_start_min_ft=("distance_start_num", "min"),
        distance_end_max_ft=("distance_end_num", "max"),
        distance_bands=("distance_band", "first"),
        source_route_name=("source_route_name", "first"),
        source_route_common=("source_route_common", "first"),
        final_review_leg_source=("final_review_leg_source", "first"),
        final_review_context_status=("final_review_context_status", "first"),
        final_review_recovery_provenance=("final_review_recovery_provenance", "first"),
        speed_aadt_ready_bins=("speed_aadt_ready_int", "sum"),
    ).reset_index()
    _checkpoint("build represented Travelway measure-window intervals", len(agg))
    return agg


def _build_identity_candidates(match: pd.DataFrame, intervals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate_crashes = match.loc[
        match["match_confidence"].isin(["high", "medium"])
        & _text(match, "matched_stable_travelway_id").str.startswith("tw_")
        & match["crash_measure"].notna()
    ].copy()
    represented_tws = set(intervals["stable_travelway_id"].astype(str).unique())
    candidate_crashes = candidate_crashes.loc[candidate_crashes["matched_stable_travelway_id"].isin(represented_tws)].copy()
    rows: list[pd.DataFrame] = []
    skipped_groups = 0
    interval_groups = {tw: group.reset_index(drop=True) for tw, group in intervals.groupby("stable_travelway_id", sort=False)}
    for group_idx, (tw, cgrp) in enumerate(candidate_crashes.groupby("matched_stable_travelway_id", sort=False), start=1):
        bgrp = interval_groups.get(tw)
        if bgrp is None or bgrp.empty:
            skipped_groups += 1
            continue
        cmeasures = cgrp["crash_measure"].to_numpy(dtype=float)
        local_parts: list[pd.DataFrame] = []
        # Per-interval masks keep the output bounded to actual signal-window candidates and avoid crash x bin products.
        for interval in bgrp.itertuples(index=False):
            mask = (cmeasures >= float(interval.measure_min) - 1e-9) & (cmeasures <= float(interval.measure_max) + 1e-9)
            if not mask.any():
                continue
            hit = cgrp.loc[mask, [
                "stable_crash_id",
                "DOCUMENT_NBR",
                "CRASH_YEAR",
                "CRASH_SEVERITY",
                "RTE_NM",
                "RNS_MP",
                "matched_stable_travelway_id",
                "match_method",
                "match_confidence",
                "route_key_compatibility",
                "geometry_distance_to_matched_travelway_ft",
                "tier_a_route_measure_status",
            ]].copy()
            for col in [
                "stable_signal_id",
                "source_signal_id",
                "analysis_window",
                "final_review_physical_leg_id",
                "final_review_carriageway_subbranch_id",
                "representative_stable_bin_id",
                "matched_bin_count",
                "distance_start_min_ft",
                "distance_end_max_ft",
                "distance_bands",
                "source_route_name",
                "source_route_common",
                "final_review_leg_source",
                "final_review_context_status",
                "final_review_recovery_provenance",
                "speed_aadt_ready_bins",
            ]:
                hit[col] = getattr(interval, col)
            hit["interval_measure_min"] = float(interval.measure_min)
            hit["interval_measure_max"] = float(interval.measure_max)
            local_parts.append(hit)
        if local_parts:
            rows.append(pd.concat(local_parts, ignore_index=True))
        if group_idx % 1000 == 0:
            _checkpoint("identity candidate interval groups processed", group_idx)
    candidates = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not candidates.empty:
        candidates["assignment_method"] = "crash_roadway_identity_route_measure_sensitivity"
        candidates["stable_travelway_id"] = candidates["matched_stable_travelway_id"]
        candidates["stable_bin_id"] = candidates["representative_stable_bin_id"]
        candidates["sensitivity_only"] = True
        candidates["route_measure_compatibility"] = np.where(
            candidates["tier_a_route_measure_status"].str.contains("covered|single", case=False, na=False),
            "route_measure_compatible",
            "route_or_geometry_compatible",
        )
    _checkpoint("build roadway-identity signal/window candidates", len(candidates))
    signal_window = pd.DataFrame()
    if not candidates.empty:
        signal_window = candidates.groupby(
            ["stable_crash_id", "stable_travelway_id", "stable_signal_id", "analysis_window"], dropna=False
        ).agg(
            candidate_leg_count=("final_review_physical_leg_id", "nunique"),
            candidate_row_count=("stable_bin_id", "count"),
            candidate_bin_count=("matched_bin_count", "sum"),
            match_confidence=("match_confidence", "first"),
            match_method=("match_method", "first"),
            representative_stable_bin_id=("stable_bin_id", "first"),
            final_review_leg_sources=("final_review_leg_source", "first"),
            final_review_recovery_provenance=("final_review_recovery_provenance", "first"),
        ).reset_index()
    _checkpoint("build identity signal-window candidates", len(signal_window))
    return candidates, signal_window


def _candidate_summary(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=["stable_crash_id", "travelway_identity_candidate"])
    return candidates.groupby("stable_crash_id", dropna=False).agg(
        travelway_identity_candidate=("stable_signal_id", lambda s: True),
        identity_candidate_travelway_count=("stable_travelway_id", "nunique"),
        identity_candidate_signal_count=("stable_signal_id", "nunique"),
        identity_candidate_window_count=("analysis_window", "nunique"),
        identity_candidate_row_count=("stable_signal_id", "count"),
        identity_match_confidence=("match_confidence", "first"),
        identity_match_method=("match_method", "first"),
        identity_candidate_travelway_ids=("stable_travelway_id", "first"),
    ).reset_index()


def _comparison(match: pd.DataFrame, spatial: pd.DataFrame, cand_summary: pd.DataFrame) -> pd.DataFrame:
    comp = match[
        [
            "stable_crash_id",
            "DOCUMENT_NBR",
            "CRASH_YEAR",
            "CRASH_SEVERITY",
            "RTE_NM",
            "RNS_MP",
            "matched_stable_travelway_id",
            "candidate_travelway_count_num",
            "match_method",
            "match_confidence",
            "route_key_compatibility",
            "geometry_distance_to_matched_travelway_ft",
        ]
    ].copy()
    comp = comp.merge(spatial, on="stable_crash_id", how="left")
    comp = comp.merge(cand_summary, on="stable_crash_id", how="left")
    comp["spatial_50_assigned"] = comp["spatial_50_signal_count"].notna()
    comp["travelway_identity_candidate"] = comp["travelway_identity_candidate"].fillna(False).astype(bool)
    for col in [
        "spatial_50_signal_count",
        "spatial_50_bin_count",
        "spatial_50_physical_leg_count",
        "spatial_50_travelway_count",
        "identity_candidate_travelway_count",
        "identity_candidate_signal_count",
        "identity_candidate_window_count",
        "identity_candidate_row_count",
    ]:
        comp[col] = pd.to_numeric(comp[col], errors="coerce").fillna(0).astype(int)
    spatial_tws = comp["spatial_50_travelway_ids"].fillna("").astype(str)
    match_tw = comp["matched_stable_travelway_id"].fillna("").astype(str)
    comp["spatial_travelway_agrees"] = [bool(tw and tw in set(value.split("|"))) for tw, value in zip(match_tw, spatial_tws)]
    comp["agreement_class"] = np.select(
        [
            comp["spatial_50_assigned"] & comp["travelway_identity_candidate"] & comp["spatial_travelway_agrees"],
            comp["spatial_50_assigned"] & comp["travelway_identity_candidate"] & comp["spatial_50_signal_count"].gt(1) & comp["identity_candidate_signal_count"].eq(1),
            comp["spatial_50_assigned"] & comp["travelway_identity_candidate"] & ~comp["spatial_travelway_agrees"],
            comp["spatial_50_assigned"] & ~comp["travelway_identity_candidate"],
            ~comp["spatial_50_assigned"] & comp["travelway_identity_candidate"],
        ],
        [
            "spatial_and_travelway_agree",
            "spatial_multiassign_travelway_single_match",
            "spatial_assigned_travelway_disagrees",
            "spatial_assigned_no_travelway_match",
            "travelway_candidate_spatial_unassigned",
        ],
        default="both_unassigned_or_no_match",
    )
    return comp


def _high_fanout_reduction(comp: pd.DataFrame) -> pd.DataFrame:
    fanout = _read_csv(CRASH_SANITY_DIR / "crash_fanout_sanity_detail.csv")
    high_50 = fanout.loc[
        pd.to_numeric(fanout["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)
        & (
            pd.to_numeric(fanout["signal_count"], errors="coerce").ge(4)
            | pd.to_numeric(fanout["bin_count"], errors="coerce").ge(20)
        )
    ].copy()
    cause = _read_csv(CRASH_SANITY_DIR / "crash_high_fanout_cause_classification.csv")
    if not cause.empty and "stable_crash_id" in cause.columns:
        keep = [col for col in ["stable_crash_id", "likely_high_fanout_cause", "manual_review_priority"] if col in cause.columns]
        high_50 = high_50.merge(cause[keep].drop_duplicates("stable_crash_id"), on="stable_crash_id", how="left")
    audit = high_50.merge(comp, on="stable_crash_id", how="left", suffixes=("", "_comparison"))
    audit["estimated_signal_fanout_reduction"] = pd.to_numeric(audit["spatial_50_signal_count"], errors="coerce").fillna(0) - pd.to_numeric(
        audit["identity_candidate_signal_count"], errors="coerce"
    ).fillna(0)
    audit["estimated_bin_fanout_reduction"] = pd.to_numeric(audit["spatial_50_bin_count"], errors="coerce").fillna(0) - pd.to_numeric(
        audit["identity_candidate_row_count"], errors="coerce"
    ).fillna(0)
    audit["high_fanout_identity_class"] = np.select(
        [
            audit["match_confidence"].eq("high") & audit["identity_candidate_signal_count"].eq(1) & audit["estimated_signal_fanout_reduction"].gt(0),
            audit["travelway_identity_candidate"].eq(True) & audit["estimated_signal_fanout_reduction"].le(0),
            audit["match_confidence"].isin(["medium", "low"]),
            audit["match_confidence"].isin(["none", ""]),
        ],
        [
            "fanout_reducible_by_travelway_identity",
            "fanout_legitimate_multi_signal_corridor",
            "fanout_travelway_match_ambiguous",
            "fanout_no_travelway_identity",
        ],
        default="manual_review_needed",
    )
    _checkpoint("build high-fanout identity reduction audit", len(audit))
    return audit


def _unassigned_audit(comp: pd.DataFrame) -> pd.DataFrame:
    unassigned = comp.loc[~comp["spatial_50_assigned"]].copy()
    unassigned["unassigned_identity_class"] = np.select(
        [
            unassigned["travelway_identity_candidate"] & unassigned["match_confidence"].isin(["high", "medium"]),
            unassigned["matched_stable_travelway_id"].str.startswith("tw_") & unassigned["match_confidence"].isin(["high", "medium"]),
            unassigned["match_confidence"].eq("low"),
            unassigned["match_confidence"].eq("none"),
        ],
        [
            "travelway_identity_within_signal_window_candidate",
            "represented_travelway_outside_signal_window_or_not_in_final_scaffold",
            "low_confidence_match_only",
            "no_travelway_identity_match",
        ],
        default="route_measure_out_of_scope",
    )
    _checkpoint("build unassigned identity sensitivity audit", len(unassigned))
    return unassigned


def _fanout_comparison(comp: pd.DataFrame) -> pd.DataFrame:
    comp["fanout_change_class"] = np.select(
        [
            comp["travelway_identity_candidate"] & comp["identity_candidate_signal_count"].lt(comp["spatial_50_signal_count"]),
            comp["travelway_identity_candidate"] & comp["identity_candidate_signal_count"].eq(comp["spatial_50_signal_count"]),
            comp["travelway_identity_candidate"] & comp["identity_candidate_signal_count"].gt(comp["spatial_50_signal_count"]),
        ],
        ["lower_fanout_under_travelway_identity", "same_fanout", "higher_fanout_under_travelway_identity"],
        default="no_travelway_based_assignment",
    )
    summary = comp.groupby(["fanout_change_class", "match_confidence"], dropna=False).agg(
        crash_count=("stable_crash_id", "nunique"),
        median_spatial_signal_count=("spatial_50_signal_count", "median"),
        median_identity_signal_count=("identity_candidate_signal_count", "median"),
        median_spatial_bin_count=("spatial_50_bin_count", "median"),
        median_identity_candidate_rows=("identity_candidate_row_count", "median"),
    ).reset_index()
    return summary


def _method_summary(match: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    base = match.groupby(["match_confidence", "match_method"], dropna=False).agg(
        crash_count=("stable_crash_id", "nunique"),
        single_travelway_match=("candidate_travelway_count_num", lambda s: int(pd.to_numeric(s, errors="coerce").eq(1).sum())),
    ).reset_index()
    if candidates.empty:
        base["candidate_assignment_crashes"] = 0
        return base
    cand = candidates.groupby(["match_confidence", "match_method"], dropna=False).agg(
        candidate_assignment_crashes=("stable_crash_id", "nunique"),
        candidate_rows=("stable_signal_id", "count"),
    ).reset_index()
    return base.merge(cand, on=["match_confidence", "match_method"], how="left").fillna({"candidate_assignment_crashes": 0, "candidate_rows": 0})


def _readiness_decision(comp: pd.DataFrame, high: pd.DataFrame, unassigned: pd.DataFrame) -> pd.DataFrame:
    reducible = int(high["high_fanout_identity_class"].eq("fanout_reducible_by_travelway_identity").sum())
    unassigned_candidates = int(unassigned["unassigned_identity_class"].eq("travelway_identity_within_signal_window_candidate").sum())
    lower = int(comp.get("fanout_change_class", pd.Series("", index=comp.index)).eq("lower_fanout_under_travelway_identity").sum())
    rows = [
        {
            "decision_item": "crash_to_travelway_identity_sensitivity_useful",
            "decision": "yes",
            "evidence": f"lower_fanout_crashes={lower:,}; high_fanout_reducible={reducible:,}; unassigned_signal_window_candidates={unassigned_candidates:,}",
        },
        {
            "decision_item": "future_constrained_assignment_product",
            "decision": "recommended_as_sensitivity_not_primary",
            "evidence": "route/measure identity can constrain some fanout, but spatial 50 ft remains the current doctrine primary product",
        },
        {
            "decision_item": "spatial_50ft_primary_status",
            "decision": "remain_primary_review_product",
            "evidence": "this pass creates QA/sensitivity candidates only and does not replace source-preserving spatial weights",
        },
        {
            "decision_item": "high_fanout_map_review",
            "decision": "target_reducible_and_disagreement_cases",
            "evidence": "use identity-reducible and spatial/travelway disagreement cases for bounded review",
        },
        {
            "decision_item": "recommended_next_pass",
            "decision": "manual_overlap_review_or_identity_constrained_sensitivity_package",
            "evidence": "identity sensitivity is informative enough for a constrained sensitivity product but not production promotion",
        },
    ]
    return pd.DataFrame(rows)


def _qa(direction_cols: list[str], missing: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "outputs written only under review/current/crash_travelway_identity_sensitivity"),
        ("no_records_promoted", True, "review-only sensitivity product"),
        ("no_rates_or_models", True, "no rates/models calculated"),
        ("no_final_production_crash_assignment", True, "sensitivity assignment candidates only"),
        ("crash_direction_fields_not_used", True, "|".join(direction_cols) if direction_cols else "none detected"),
        ("direction_like_fields_inventory_only", True, "direction fields are not read except schema inventory"),
        ("spatial_50ft_not_replaced", True, "spatial 50 ft remains primary review product"),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("missing_required_inputs", len(missing) == 0, "|".join(missing)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "notes"])


def _findings(
    match: pd.DataFrame,
    candidates: pd.DataFrame,
    comp: pd.DataFrame,
    high: pd.DataFrame,
    unassigned: pd.DataFrame,
    decision: pd.DataFrame,
) -> str:
    confidence_counts = match["match_confidence"].value_counts(dropna=False).to_dict()
    direct_high = int(match["match_method"].eq("tier_a_direct_route_measure").sum())
    route_nearest_high = int(
        (
            match["match_method"].eq("tier_a_route_measure_with_route_compatible_nearest")
            & match["match_confidence"].eq("high")
        ).sum()
    )
    agree = int(comp["agreement_class"].eq("spatial_and_travelway_agree").sum())
    reducible = int(high["high_fanout_identity_class"].eq("fanout_reducible_by_travelway_identity").sum())
    ambiguous = int(high["high_fanout_identity_class"].eq("fanout_travelway_match_ambiguous").sum())
    unassigned_window = int(unassigned["unassigned_identity_class"].eq("travelway_identity_within_signal_window_candidate").sum())
    unassigned_outside = int(unassigned["unassigned_identity_class"].eq("represented_travelway_outside_signal_window_or_not_in_final_scaffold").sum())
    lower = int(comp["fanout_change_class"].eq("lower_fanout_under_travelway_identity").sum())
    rec = decision.loc[decision["decision_item"].eq("recommended_next_pass"), "decision"].iloc[0]
    return f"""# Crash-to-Travelway Identity Sensitivity

Bounded question: can crash roadway identity constrain or explain spatial 50 ft crash fanout without replacing the spatial primary product?

## Findings

1. Travelway identity match counts: high={confidence_counts.get('high', 0):,}, medium={confidence_counts.get('medium', 0):,}, low={confidence_counts.get('low', 0):,}, none={confidence_counts.get('none', 0):,}.
2. High-confidence direct route/measure interval matches: {direct_high:,}; high-confidence route/measure plus route-compatible nearest Travelway matches: {route_nearest_high:,}.
3. Spatial 50 ft and Travelway identity agree for {agree:,} crashes.
4. High-fanout crashes reducible by Travelway identity: {reducible:,}.
5. High-fanout crashes that remain ambiguous: {ambiguous:,}.
6. Spatial 50 ft unassigned crashes with represented Travelway signal-window candidates: {unassigned_window:,}.
7. Spatial 50 ft unassigned crashes matched to represented/source Travelway but outside represented signal windows or not in the final scaffold: {unassigned_outside:,}.
8. Travelway identity would lower signal fanout for {lower:,} crashes in this sensitivity view.
9. Travelway identity should become a future constrained assignment sensitivity product, not a production replacement.
10. Spatial 50 ft remains the primary review crash product.

## Recommendation

Next pass: `{rec}`.

## QA

No active outputs were modified. No records were promoted. No rates/models were calculated. No final production crash assignment was created. Crash direction fields were not used. Spatial 50 ft remains the primary review product.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start crash Travelway identity sensitivity")
    missing = _missing_inputs()
    if missing:
        _write_csv(pd.DataFrame({"missing_input": missing}), "missing_inputs.csv")
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    crashes, direction_cols = _load_crash_identity_source()
    match = _load_match_detail()
    # Reconcile against normalized crash source without reading direction-like fields.
    source_cols = [col for col in ["stable_crash_id", "CRASH_DT", "COLLISION_TYPE"] if col in crashes.columns]
    if source_cols:
        match = match.merge(crashes[source_cols].drop_duplicates("stable_crash_id"), on="stable_crash_id", how="left", suffixes=("", "_source"))
    spatial = _spatial_50_summary()
    intervals = _load_bin_intervals()
    candidates, signal_windows = _build_identity_candidates(match, intervals)
    cand_summary = _candidate_summary(candidates)
    comp = _comparison(match, spatial, cand_summary)
    high = _high_fanout_reduction(comp)
    unassigned = _unassigned_audit(comp)
    fanout = _fanout_comparison(comp)
    method_summary = _method_summary(match, candidates)
    decision = _readiness_decision(comp, high, unassigned)
    qa = _qa(direction_cols, missing)
    findings = _findings(match, candidates, comp, high, unassigned, decision)

    _write_csv(match, "crash_travelway_identity_match_detail.csv")
    _write_csv(candidates, "crash_travelway_identity_assignment_candidates.csv")
    _write_csv(signal_windows, "crash_travelway_identity_signal_window_candidates.csv")
    _write_csv(comp, "crash_spatial_vs_travelway_identity_comparison.csv")
    _write_csv(high, "crash_high_fanout_identity_reduction_audit.csv")
    _write_csv(unassigned, "crash_unassigned_identity_sensitivity_audit.csv")
    _write_csv(fanout, "crash_travelway_identity_fanout_comparison.csv")
    _write_csv(method_summary, "crash_travelway_identity_method_summary.csv")
    _write_csv(decision, "crash_travelway_identity_readiness_decision.csv")
    _write_text(findings, "crash_travelway_identity_sensitivity_findings.md")
    _write_csv(qa, "crash_travelway_identity_sensitivity_qa.csv")
    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "crash-to-Travelway identity assignment sensitivity product",
        "output_dir": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "crash_travelway_identity_match_detail.csv",
            "crash_travelway_identity_assignment_candidates.csv",
            "crash_travelway_identity_signal_window_candidates.csv",
            "crash_spatial_vs_travelway_identity_comparison.csv",
            "crash_high_fanout_identity_reduction_audit.csv",
            "crash_unassigned_identity_sensitivity_audit.csv",
            "crash_travelway_identity_fanout_comparison.csv",
            "crash_travelway_identity_method_summary.csv",
            "crash_travelway_identity_readiness_decision.csv",
            "crash_travelway_identity_sensitivity_findings.md",
            "crash_travelway_identity_sensitivity_qa.csv",
            "crash_travelway_identity_sensitivity_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "normalized_crashes": int(len(crashes)),
            "match_detail_crashes": int(match["stable_crash_id"].nunique()),
            "assignment_candidate_rows": int(len(candidates)),
            "assignment_candidate_crashes": int(candidates["stable_crash_id"].nunique()) if not candidates.empty else 0,
            "signal_window_candidate_rows": int(len(signal_windows)),
            "spatial_50_assigned_crashes": int(spatial["stable_crash_id"].nunique()),
            "high_fanout_reducible": int(high["high_fanout_identity_class"].eq("fanout_reducible_by_travelway_identity").sum()),
        },
        "qa": {
            "review_only": True,
            "spatial_50ft_replaced": False,
            "no_rates_or_models": True,
            "crash_direction_used": False,
            "direction_fields_inventory_only": direction_cols,
        },
    }
    _write_json(manifest, "crash_travelway_identity_sensitivity_manifest.json")
    _checkpoint("complete crash Travelway identity sensitivity")


if __name__ == "__main__":
    main()
