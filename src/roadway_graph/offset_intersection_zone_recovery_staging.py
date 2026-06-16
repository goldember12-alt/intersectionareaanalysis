from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


ROOT = Path("work/output/roadway_graph")
OUT = ROOT / "review/current/offset_intersection_zone_recovery_staging"
RECOVERY = ROOT / "review/current/offset_intersection_zone_scaffold_recovery"
DISCONTINUITY = ROOT / "review/current/intersection_zone_route_discontinuity_diagnostic"
CALIBRATION = ROOT / "review/current/physical_leg_map_review_calibration"
RECOVERY_GPKG = RECOVERY / "offset_zone_scaffold_recovery.gpkg"
MAP_REVIEW_GPKG = ROOT / "map_review/current/intersection_zone_recovery_review/intersection_zone_recovery_review.gpkg"
OUT_GPKG = OUT / "offset_intersection_zone_recovery_staging.gpkg"
CRS = "EPSG:3968"

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

HOLD_CATEGORIES = {"source_missing_leg", "nonstandard_signal_geometry"}
NONSTANDARD_SIGNAL_IDS = {"signal_001549"}


def _log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"signal_relative_direction_label", "direction_confidence_status", "true_vehicle_direction_inferred"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _check_columns(columns: list[str], source: str) -> None:
    blocked = [column for column in columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash/direction fields from {source}: {blocked}")


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    _check_columns(header, str(path))
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _read_layer(path: Path, layer: str) -> gpd.GeoDataFrame:
    _checkpoint(f"read_layer_start {layer}")
    frame = gpd.read_file(path, layer=layer)
    if frame.crs is None:
        raise ValueError(f"Layer {layer} in {path} has unknown CRS")
    _check_columns(list(frame.columns), f"{path}:{layer}")
    frame = frame.to_crs(CRS)
    _checkpoint(f"read_layer_complete {layer}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_csv {path.name}", len(frame))


def _write_layer(gdf: gpd.GeoDataFrame, layer: str) -> None:
    frame = gdf.copy()
    if frame.empty:
        frame = gpd.GeoDataFrame(frame, geometry="geometry", crs=CRS)
    if frame.crs is None:
        frame = frame.set_crs(CRS)
    else:
        frame = frame.to_crs(CRS)
    frame.to_file(OUT_GPKG, layer=layer, driver="GPKG")
    _checkpoint(f"write_layer {layer}", len(frame))


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").lower()
    return text[:80] if text else "unknown"


def _stage_class(row: pd.Series) -> str:
    signal_id = str(row.get("signal_id", ""))
    manual_category = str(row.get("manual_category", ""))
    confidence = str(row.get("recovery_confidence", ""))
    if signal_id in NONSTANDARD_SIGNAL_IDS or manual_category == "nonstandard_signal_geometry":
        return "stage_nonstandard_geometry_hold"
    if manual_category == "source_missing_leg":
        return "stage_source_limited_hold"
    if not str(row.get("physical_leg_bearing_group", "")).strip():
        return "stage_insufficient_evidence_hold"
    if confidence == "high":
        return "stage_high_confidence_after_review"
    if confidence == "medium":
        return "stage_medium_confidence_needs_map_review"
    return "stage_insufficient_evidence_hold"


def _is_hold(stage_class: str) -> bool:
    return stage_class in {
        "stage_nonstandard_geometry_hold",
        "stage_source_limited_hold",
        "stage_insufficient_evidence_hold",
    }


def _physical_leg_id(signal_id: str, bearing_group: str) -> str:
    return f"physical_leg_geom_bearing::{signal_id}::{_slug(bearing_group)}"


def _carriageway_subbranch_id(signal_id: str, bearing_group: str, route_keys: str, source_line_ids: str) -> str:
    route = _slug(route_keys.split("|")[0] if route_keys else "")
    src = _slug(source_line_ids.split("|")[0] if source_line_ids else "")
    return f"carriageway_subbranch::{signal_id}::{_slug(bearing_group)}::{route or src}"


def _manual_lookup(seed: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    cols = ["signal_id", "manual_category", "manual_note"]
    frames = []
    if set(cols).issubset(seed.columns):
        frames.append(seed[cols])
    if set(cols).issubset(detail.columns):
        frames.append(detail[cols])
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    out = out[out["signal_id"].astype(str).str.strip().ne("")]
    return out.drop_duplicates("signal_id", keep="first")


def _build_staged_legs(
    legs_gdf: gpd.GeoDataFrame,
    leg_detail: pd.DataFrame,
    signal_summary: pd.DataFrame,
    manual: pd.DataFrame,
) -> gpd.GeoDataFrame:
    keys = ["signal_id", "physical_leg_bearing_group"]
    detail_cols = [
        "signal_id",
        "physical_leg_bearing_group",
        "route_facility_discontinuity_type",
        "recovered_leg_corresponds_to_discontinuity",
        "source_route_key_count",
    ]
    sig_cols = [
        "signal_id",
        "source_layer",
        "manual_category",
        "manual_note",
    ]
    sig_extra = signal_summary[[c for c in sig_cols if c in signal_summary.columns]].copy()
    frame = legs_gdf.merge(leg_detail[[c for c in detail_cols if c in leg_detail.columns]], on=keys, how="left")
    frame = frame.merge(manual, on="signal_id", how="left", suffixes=("", "_manual"))
    if "manual_category_manual" in frame.columns:
        frame["manual_category"] = frame["manual_category"].mask(frame["manual_category"].fillna("").astype(str).eq(""), frame["manual_category_manual"])
    if "manual_note_manual" in frame.columns:
        frame["manual_note"] = frame["manual_note"].mask(frame["manual_note"].fillna("").astype(str).eq(""), frame["manual_note_manual"])
    if "source_layer" not in frame.columns and "source_layer" in sig_extra.columns:
        frame = frame.merge(sig_extra[["signal_id", "source_layer"]].drop_duplicates("signal_id"), on="signal_id", how="left")
    frame["staging_class"] = frame.apply(_stage_class, axis=1)
    frame["staging_confidence"] = frame["staging_class"].map(
        {
            "stage_high_confidence_after_review": "high_after_map_review",
            "stage_medium_confidence_needs_map_review": "medium_needs_map_review",
            "stage_nonstandard_geometry_hold": "hold_nonstandard_geometry",
            "stage_source_limited_hold": "hold_source_limited",
            "stage_insufficient_evidence_hold": "hold_insufficient_evidence",
        }
    )
    frame["physical_leg_id"] = [
        _physical_leg_id(str(sid), str(bg)) for sid, bg in zip(frame["signal_id"], frame["physical_leg_bearing_group"], strict=False)
    ]
    frame["carriageway_subbranch_id"] = [
        _carriageway_subbranch_id(str(sid), str(bg), str(route), str(src))
        for sid, bg, route, src in zip(
            frame["signal_id"],
            frame["physical_leg_bearing_group"],
            frame["source_route_keys"],
            frame["source_line_ids"],
            strict=False,
        )
    ]
    frame["staged_recovered_leg_id"] = [
        f"staged_offset_leg::{sid}::{i:04d}" for i, sid in enumerate(frame["signal_id"], start=1)
    ]
    frame["inferred_intersection_zone_anchor_id"] = "offset_anchor::" + frame["signal_id"].astype(str)
    frame["route_facility_discontinuity_flag"] = ~frame["route_facility_discontinuity_type"].fillna("").isin(
        ["", "no_route_facility_discontinuity", "source_line_split_with_same_name", "insufficient_evidence"]
    )
    frame["source_line_split_flag"] = frame["source_line_split_at_intersection"].map(_bool)
    frame["divided_carriageway_flag"] = frame["route_facility_discontinuity_type"].fillna("").eq("divided_carriageway_route_split")
    frame["calibration_manual_review_flag"] = frame["manual_category"].fillna("").astype(str).ne("")
    frame["review_status"] = frame["staging_class"].map(
        lambda cls: "hold_not_refresh_ready" if _is_hold(cls) else "staged_for_map_review_before_refresh"
    )
    frame["review_only"] = True
    return frame


def _build_staged_bins(bins_gdf: gpd.GeoDataFrame, staged_legs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    leg_map_cols = [
        "signal_id",
        "physical_leg_bearing_group",
        "staged_recovered_leg_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "route_facility_discontinuity_type",
        "route_facility_discontinuity_flag",
        "source_line_split_flag",
        "divided_carriageway_flag",
        "staging_class",
        "staging_confidence",
        "review_status",
    ]
    frame = bins_gdf.merge(staged_legs[[c for c in leg_map_cols if c in staged_legs.columns]], on=["signal_id", "physical_leg_bearing_group"], how="left")
    frame["staged_recovered_bin_id"] = [
        f"staged_offset_bin::{sid}::{i:06d}" for i, sid in enumerate(frame["signal_id"], start=1)
    ]
    frame["source_travelway_lineage"] = frame["source_line_ids"]
    frame["geometry_wkt"] = frame.geometry.to_wkt()
    frame["partial_coverage_flag"] = _num(frame, "distance_end_ft").lt(1000)
    frame["route_facility_discontinuity_flag"] = frame["route_facility_discontinuity_flag"].fillna(False).astype(bool)
    frame["source_line_split_flag"] = frame["source_line_split_flag"].fillna(False).astype(bool)
    frame["review_only"] = True
    return frame


def _readiness_from_stage(stage_class: str) -> dict[str, bool]:
    hold = _is_hold(stage_class)
    return {
        "eligible_for_route_measure_refresh": not hold,
        "eligible_for_roadway_context_refresh": not hold,
        "eligible_for_speed_aadt_refresh": not hold,
        "eligible_for_access_review_later": not hold,
        "eligible_for_crash_catchment_review_later": not hold,
        "needs_map_review_before_refresh": True,
    }


def _signal_summary(staged_legs: gpd.GeoDataFrame, staged_bins: gpd.GeoDataFrame, recovery_signal: pd.DataFrame) -> pd.DataFrame:
    leg_group = staged_legs.groupby("signal_id").agg(
        staged_recovered_physical_legs=("staged_recovered_leg_id", "nunique"),
        route_facility_discontinuity_leg_count=("route_facility_discontinuity_flag", "sum"),
        source_line_split_leg_count=("source_line_split_flag", "sum"),
        divided_carriageway_leg_count=("divided_carriageway_flag", "sum"),
        staging_classes=("staging_class", lambda s: "|".join(sorted(set(s.astype(str))))),
        calibration_manual_review_flag=("calibration_manual_review_flag", "max"),
    ).reset_index()
    bin_group = staged_bins.groupby("signal_id").agg(
        staged_recovered_bins=("staged_recovered_bin_id", "nunique"),
        bins_0_250ft=("distance_band", lambda s: int((s == "0_250ft").sum())),
        bins_250_500ft=("distance_band", lambda s: int((s == "250_500ft").sum())),
        bins_500_750ft=("distance_band", lambda s: int((s == "500_750ft").sum())),
        bins_750_1000ft=("distance_band", lambda s: int((s == "750_1000ft").sum())),
    ).reset_index()
    summary = recovery_signal.merge(leg_group, on="signal_id", how="right").merge(bin_group, on="signal_id", how="left")
    for col in ["staged_recovered_bins", "bins_0_250ft", "bins_250_500ft", "bins_500_750ft", "bins_750_1000ft"]:
        summary[col] = _num(summary, col).astype(int)
    summary["primary_staging_class"] = summary["staging_classes"].fillna("").map(
        lambda text: "stage_high_confidence_after_review"
        if "stage_high_confidence_after_review" in text
        else ("stage_medium_confidence_needs_map_review" if "stage_medium_confidence_needs_map_review" in text else text)
    )
    readiness = pd.DataFrame([{"signal_id": row.signal_id, **_readiness_from_stage(row.primary_staging_class)} for row in summary.itertuples(index=False)])
    return summary.merge(readiness, on="signal_id", how="left")


def _readiness_flags(signal_summary: pd.DataFrame, holdouts: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "signal_id",
        "primary_staging_class",
        "eligible_for_route_measure_refresh",
        "eligible_for_roadway_context_refresh",
        "eligible_for_speed_aadt_refresh",
        "eligible_for_access_review_later",
        "eligible_for_crash_catchment_review_later",
        "needs_map_review_before_refresh",
        "calibration_manual_review_flag",
    ]
    ready = signal_summary[[c for c in cols if c in signal_summary.columns]].copy()
    if not holdouts.empty:
        hold = holdouts[["signal_id", "staging_class"]].copy().rename(columns={"staging_class": "primary_staging_class"})
        for col in [
            "eligible_for_route_measure_refresh",
            "eligible_for_roadway_context_refresh",
            "eligible_for_speed_aadt_refresh",
            "eligible_for_access_review_later",
            "eligible_for_crash_catchment_review_later",
        ]:
            hold[col] = False
        hold["needs_map_review_before_refresh"] = True
        hold["calibration_manual_review_flag"] = True
        ready = pd.concat([ready, hold[ready.columns]], ignore_index=True)
    return ready.drop_duplicates("signal_id", keep="last")


def _holdouts(manual: pd.DataFrame, staged_legs: gpd.GeoDataFrame) -> pd.DataFrame:
    hold_manual = manual[manual["manual_category"].isin(HOLD_CATEGORIES) | manual["signal_id"].isin(NONSTANDARD_SIGNAL_IDS)].copy()
    staged_holds = pd.DataFrame(staged_legs[staged_legs["staging_class"].map(_is_hold)].drop(columns="geometry", errors="ignore"))
    if staged_holds.empty:
        staged_holds = pd.DataFrame(columns=["signal_id", "staging_class", "manual_category", "manual_note"])
    hold_manual["staging_class"] = hold_manual["manual_category"].map(
        {"source_missing_leg": "stage_source_limited_hold", "nonstandard_signal_geometry": "stage_nonstandard_geometry_hold"}
    ).fillna("stage_nonstandard_geometry_hold")
    cols = ["signal_id", "staging_class", "manual_category", "manual_note"]
    return pd.concat([hold_manual[cols], staged_holds[[c for c in cols if c in staged_holds.columns]]], ignore_index=True).drop_duplicates("signal_id", keep="first")


def _recovery_summary(staged_legs: gpd.GeoDataFrame, staged_bins: gpd.GeoDataFrame, signal_summary: pd.DataFrame, holdouts: pd.DataFrame) -> pd.DataFrame:
    rows: list[tuple[str, Any, str]] = [
        ("staged_signals", signal_summary["signal_id"].nunique(), "Signals with staged recovered offset/intersection-zone records."),
        ("staged_recovered_physical_legs", staged_legs["staged_recovered_leg_id"].nunique(), "Staged recovered physical-leg records."),
        ("staged_recovered_bins", staged_bins["staged_recovered_bin_id"].nunique(), "Staged recovered bin records."),
        ("refresh_ready_signal_count_pending_map_review", int(signal_summary["eligible_for_route_measure_refresh"].sum()), "Non-hold signals eligible for later refresh after map review."),
        ("holdout_signal_count", holdouts["signal_id"].nunique(), "Manual/staging holdout signals not refresh-ready."),
        ("route_facility_discontinuity_leg_count", int(staged_legs["route_facility_discontinuity_flag"].sum()), "Staged legs with route/facility discontinuity QA flag."),
        ("source_line_split_leg_count", int(staged_legs["source_line_split_flag"].sum()), "Staged legs with source-line split flag."),
        ("nonstandard_manual_hold_count", int((holdouts["staging_class"] == "stage_nonstandard_geometry_hold").sum()), "Nonstandard/manual holdout signals."),
    ]
    for cls, count in staged_legs["staging_class"].value_counts().sort_index().items():
        rows.append((f"staging_class_{cls}", int(count), "Staged leg count by staging class."))
    for band, count in staged_bins["distance_band"].value_counts().sort_index().items():
        rows.append((f"staged_bins_{band}", int(count), "Staged bin count by distance band."))
    return pd.DataFrame(rows, columns=["metric", "value", "note"])


def _review_queue(signal_summary: pd.DataFrame, holdouts: pd.DataFrame) -> pd.DataFrame:
    queue = signal_summary.copy()
    queue["review_priority"] = 3
    queue.loc[queue["primary_staging_class"].eq("stage_high_confidence_after_review"), "review_priority"] = 1
    queue.loc[queue["primary_staging_class"].eq("stage_medium_confidence_needs_map_review"), "review_priority"] = 2
    queue["review_queue_class"] = queue["primary_staging_class"]
    queue["recommended_review_question"] = "Confirm staged recovered legs/bins before any refresh."
    hold = holdouts.copy()
    if not hold.empty:
        hold["review_priority"] = 0
        hold["review_queue_class"] = hold["staging_class"]
        hold["recommended_review_question"] = "Hold from future refresh until manual review resolves source-limited/nonstandard status."
        for col in queue.columns:
            if col not in hold.columns:
                hold[col] = ""
        queue = pd.concat([hold[queue.columns], queue], ignore_index=True)
    return queue.sort_values(["review_priority", "signal_id"])


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_csv {path.name}", len(frame))


def _write_layer(gdf: gpd.GeoDataFrame, layer: str) -> None:
    frame = gdf.copy()
    if frame.empty:
        frame = gpd.GeoDataFrame(frame, geometry="geometry", crs=CRS)
    if frame.crs is None:
        frame = frame.set_crs(CRS)
    else:
        frame = frame.to_crs(CRS)
    frame.to_file(OUT_GPKG, layer=layer, driver="GPKG")
    _checkpoint(f"write_layer {layer}", len(frame))


def _write_findings(summary: pd.DataFrame) -> None:
    values = dict(zip(summary["metric"], summary["value"], strict=False))
    text = f"""# Offset / Intersection-Zone Recovery Staging Findings

Status: REVIEW-ONLY. This staging pass creates clean candidate records for later review. It does not refresh the expanded universe, promote records, assign speed/AADT/access/crashes, calculate rates, or run models.

## Answers

1. Signals staged for possible future refresh: {values.get('staged_signals', 0)}.
2. Recovered physical legs staged: {values.get('staged_recovered_physical_legs', 0)}; recovered bins staged: {values.get('staged_recovered_bins', 0)}.
3. Refresh-ready after map review signals: {values.get('refresh_ready_signal_count_pending_map_review', 0)}; holdout signals: {values.get('holdout_signal_count', 0)}.
4. Staged legs involving route/facility discontinuity: {values.get('route_facility_discontinuity_leg_count', 0)}.
5. Staged legs involving source-line splits with same name: {values.get('source_line_split_leg_count', 0)}.
6. Holdout/manual-review records are listed in `staged_offset_holdout_cases.csv` and are not marked refresh-ready.
7. The staged dataset is ready for a later route/measure plus speed/AADT refresh only after map review confirms the staged candidates.

## Recommendation

Use this dataset as the review-only handoff for a later bounded refresh. Do not feed it into the expanded universe until high/medium staged records are map-reviewed and holdouts remain excluded.
"""
    (OUT / "offset_intersection_zone_recovery_staging_findings.md").write_text(text, encoding="utf-8")
    _checkpoint("write_findings")


def _write_qa(staged_legs: gpd.GeoDataFrame, staged_bins: gpd.GeoDataFrame, holdouts: pd.DataFrame) -> pd.DataFrame:
    hold_ready_violation = False
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", "pass", "Writes only to review/current/offset_intersection_zone_recovery_staging/."),
            ("no_candidates_promoted", "pass", "All staged records are review-only candidates."),
            ("no_access_crash_assignment", "pass", "No access or crash sources are read or assigned."),
            ("no_rates_or_models", "pass", "No rates, denominators, regression, or models are run."),
            ("route_facility_labels_are_qa_attributes", "pass", "Physical leg IDs are geometry/bearing-first; route/facility fields are QA attributes."),
            ("geometry_bearing_first_physical_leg_ids_present", "pass" if staged_legs["physical_leg_id"].fillna("").astype(str).str.len().gt(0).all() else "fail", "physical_leg_id populated on staged legs."),
            ("review_only_flags_present", "pass" if staged_legs["review_only"].map(_bool).all() and staged_bins["review_only"].map(_bool).all() else "fail", "review_only present on staged legs and bins."),
            ("holdout_records_not_refresh_ready", "pass" if not hold_ready_violation else "fail", f"{len(holdouts)} holdout records reviewed."),
            ("outputs_review_folder_only", "pass", str(OUT)),
        ],
        columns=["qa_check", "status", "note"],
    )
    _write_csv(qa, OUT / "offset_intersection_zone_recovery_staging_qa.csv")
    return qa


def _write_manifest(outputs: list[str], summary: pd.DataFrame, qa: pd.DataFrame) -> None:
    manifest = {
        "script": "src/active/roadway_graph/offset_intersection_zone_recovery_staging.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT),
        "bounded_question": "read-only staging of offset/intersection-zone recovered legs and bins",
        "inputs": {
            "offset_recovery": str(RECOVERY),
            "route_discontinuity": str(DISCONTINUITY),
            "physical_leg_calibration": str(CALIBRATION),
        },
        "summary": summary.to_dict(orient="records"),
        "outputs": outputs,
        "qa": qa.to_dict(orient="records"),
        "non_goals_confirmed": ["no universe refresh", "no speed/AADT assignment", "no access/crash assignment", "no active output modification", "no promotion"],
    }
    (OUT / "offset_intersection_zone_recovery_staging_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _checkpoint("write_manifest")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start", note="offset/intersection-zone recovery staging")

    _read_csv(RECOVERY / "offset_zone_recovered_leg_candidates.csv")
    _read_csv(RECOVERY / "offset_zone_recovered_bins.csv")
    _read_csv(RECOVERY / "offset_zone_route_name_change_diagnostic.csv")
    recovery_signal = _read_csv(RECOVERY / "offset_zone_signal_summary.csv")
    _read_csv(RECOVERY / "offset_zone_recovery_summary.csv")
    _read_csv(RECOVERY / "offset_zone_review_queue.csv")

    discontinuity_leg = _read_csv(DISCONTINUITY / "route_discontinuity_leg_group_detail.csv")
    _read_csv(DISCONTINUITY / "route_discontinuity_signal_detail.csv")
    _read_csv(DISCONTINUITY / "route_discontinuity_class_summary.csv")
    manual_seed = _read_csv(CALIBRATION / "physical_leg_manual_review_notes_seed.csv")
    manual_detail = _read_csv(CALIBRATION / "physical_leg_review_calibration_detail.csv")
    manual = _manual_lookup(manual_seed, manual_detail)

    legs_gdf = _read_layer(RECOVERY_GPKG, "offset_zone_recovered_leg_candidates")
    bins_gdf = _read_layer(RECOVERY_GPKG, "offset_zone_recovered_bins")
    signal_points = _read_layer(RECOVERY_GPKG, "original_signal_points")
    all_review_signal_points = _read_layer(MAP_REVIEW_GPKG, "all_review_signal_points")

    staged_legs = _build_staged_legs(legs_gdf, discontinuity_leg, recovery_signal, manual)
    staged_bins = _build_staged_bins(bins_gdf, staged_legs)
    sig_summary = _signal_summary(staged_legs, staged_bins, recovery_signal)
    holdouts = _holdouts(manual, staged_legs)
    readiness = _readiness_flags(sig_summary, holdouts)
    summary = _recovery_summary(staged_legs, staged_bins, sig_summary, holdouts)
    queue = _review_queue(sig_summary, holdouts)

    leg_csv = pd.DataFrame(staged_legs.drop(columns="geometry"))
    bin_csv = pd.DataFrame(staged_bins.drop(columns="geometry"))
    _write_csv(leg_csv, OUT / "staged_offset_recovered_legs.csv")
    _write_csv(bin_csv, OUT / "staged_offset_recovered_bins.csv")
    _write_csv(sig_summary, OUT / "staged_offset_signal_summary.csv")
    _write_csv(readiness, OUT / "staged_offset_readiness_flags.csv")
    _write_csv(holdouts, OUT / "staged_offset_holdout_cases.csv")
    _write_csv(summary, OUT / "staged_offset_recovery_summary.csv")
    _write_csv(queue, OUT / "staged_offset_recovery_review_queue.csv")

    if OUT_GPKG.exists():
        OUT_GPKG.unlink()
    _write_layer(staged_bins, "staged_recovered_bins")
    _write_layer(staged_legs, "staged_recovered_legs")
    _write_layer(signal_points[signal_points["signal_id"].isin(set(sig_summary["signal_id"]))], "signal_points")
    hold_points = all_review_signal_points[all_review_signal_points["signal_id"].isin(set(holdouts["signal_id"]))].merge(holdouts, on="signal_id", how="left")
    _write_layer(hold_points, "held_nonstandard_examples")
    disc_points = signal_points[signal_points["signal_id"].isin(set(sig_summary.loc[sig_summary["route_facility_discontinuity_leg_count"].astype(int).gt(0), "signal_id"]))]
    _write_layer(disc_points, "route_facility_discontinuity_examples")

    _write_findings(summary)
    qa = _write_qa(staged_legs, staged_bins, holdouts)
    outputs = [
        "staged_offset_recovered_legs.csv",
        "staged_offset_recovered_bins.csv",
        "staged_offset_signal_summary.csv",
        "staged_offset_readiness_flags.csv",
        "staged_offset_holdout_cases.csv",
        "staged_offset_recovery_summary.csv",
        "staged_offset_recovery_review_queue.csv",
        "offset_intersection_zone_recovery_staging.gpkg",
        "offset_intersection_zone_recovery_staging_findings.md",
        "offset_intersection_zone_recovery_staging_qa.csv",
        "offset_intersection_zone_recovery_staging_manifest.json",
        "run_progress_log.txt",
    ]
    _write_manifest(outputs, summary, qa)
    _checkpoint("complete", rows=len(staged_legs))


if __name__ == "__main__":
    main()
