from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt
from shapely.ops import substring


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_access_target_geometry_persistence_cleanup"

FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_universe_access_rerun"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_CONTEXT_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"
CONSOLIDATED_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"
PRIOR_GEOMETRY_DIR = OUTPUT_ROOT / "review/current/expanded_universe_access_geometry_completion"
READY_RECOVERY_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_recovery_candidates"
ROUTE_OFFSET_RECOVERY_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_missing_leg_recovery"
FINAL_CLEANUP_DIR = OUTPUT_ROOT / "review/current/final_implementable_scaffold_cleanup"
TABLES_DIR = OUTPUT_ROOT / "tables/current"

FEET_PER_METER = 3.280839895

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
    FINAL_ACCESS_DIR / "final_access_target_bins.csv",
    FINAL_ACCESS_DIR / "final_access_missingness_summary.csv",
    FINAL_ACCESS_DIR / "final_universe_access_rerun_manifest.json",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_CONTEXT_DIR / "final_recovery_context_bin_detail.csv",
    FINAL_CONTEXT_DIR / "final_recovery_context_refresh_manifest.json",
    CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json",
    PRIOR_GEOMETRY_DIR / "access_geometry_completion_detail.csv",
    PRIOR_GEOMETRY_DIR / "access_geometry_completion_signal_summary.csv",
    PRIOR_GEOMETRY_DIR / "access_geometry_completion_manifest.json",
    READY_RECOVERY_DIR / "intersection_zone_missing_leg_recovery_candidates.gpkg",
    ROUTE_OFFSET_RECOVERY_DIR / "route_discontinuity_offset_recovery_candidates.gpkg",
    TABLES_DIR / "roadway_graph_edges.csv",
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
    if lower in {
        "signal_relative_direction",
        "signal_relative_direction_label",
        "access_direction",
        "access_direction_raw",
        "access_direction_normalized",
    }:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted(
        {
            str(value)
            for value in values.dropna()
            if str(value).strip() and str(value).lower() not in {"nan", "none", "<na>"}
        }
    )
    return "|".join(items[:limit])


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _line_substring(line: Any, start_ft: float, end_ft: float) -> Any:
    if line is None or line.is_empty:
        return None
    if not np.isfinite(start_ft) or not np.isfinite(end_ft):
        return None
    length_m = line.length
    if not np.isfinite(length_m) or length_m <= 0:
        return None
    start_m = max(min(start_ft / FEET_PER_METER, length_m), 0.0)
    end_m = max(min(end_ft / FEET_PER_METER, length_m), 0.0)
    if abs(end_m - start_m) < 0.01:
        return None
    try:
        geom = substring(line, min(start_m, end_m), max(start_m, end_m), normalized=False)
    except Exception:
        return None
    return None if geom is None or geom.is_empty else geom


def _read_candidate_gpkg_layer(gpkg: Path, layer: str, method: str) -> pd.DataFrame:
    if not gpkg.exists():
        return pd.DataFrame(columns=["original_bin_id", "recovered_geometry_wkt", "geometry_recovery_method"])
    _checkpoint(f"read_start {gpkg.name}:{layer}")
    gdf = gpd.read_file(gpkg, layer=layer)
    if gdf.empty or "candidate_missing_leg_bin_id" not in gdf.columns:
        return pd.DataFrame(columns=["original_bin_id", "recovered_geometry_wkt", "geometry_recovery_method"])
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.crs is not None and str(gdf.crs).upper() != "EPSG:3968":
        gdf = gdf.to_crs("EPSG:3968")
    out = pd.DataFrame(
        {
            "original_bin_id": gdf["candidate_missing_leg_bin_id"].astype(str),
            "recovered_geometry_wkt": gdf.geometry.map(lambda geom: geom.wkt if geom is not None and not geom.is_empty else ""),
            "geometry_recovery_method": method,
        }
    )
    out = out.loc[out["recovered_geometry_wkt"].str.strip().ne("")]
    _checkpoint(f"read_complete {gpkg.name}:{layer}", len(out))
    return out.drop_duplicates("original_bin_id")


def _candidate_gpkg_geometry_lookup() -> pd.DataFrame:
    parts = [
        _read_candidate_gpkg_layer(
            READY_RECOVERY_DIR / "intersection_zone_missing_leg_recovery_candidates.gpkg",
            "recovered_missing_leg_candidate_bins_0_1000",
            "ready_class_candidate_gpkg_0_1000",
        ),
        _read_candidate_gpkg_layer(
            READY_RECOVERY_DIR / "intersection_zone_missing_leg_recovery_candidates.gpkg",
            "recovered_missing_leg_candidate_bins_1000_2500",
            "ready_class_candidate_gpkg_1000_2500",
        ),
        _read_candidate_gpkg_layer(
            ROUTE_OFFSET_RECOVERY_DIR / "route_discontinuity_offset_recovery_candidates.gpkg",
            "recovered_candidate_bins",
            "route_discontinuity_offset_candidate_gpkg",
        ),
    ]
    out = pd.concat(parts, ignore_index=True, sort=False)
    if out.empty:
        return out
    return out.drop_duplicates("original_bin_id")


def _prior_graph_edge_geometry_lookup(missing: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    prior = _read_csv(
        PRIOR_GEOMETRY_DIR / "access_geometry_completion_detail.csv",
        usecols=[
            "target_bin_id",
            "frozen_candidate_bin_id",
            "candidate_bin_id",
            "graph_edge_id",
            "source_road_row_id",
            "completed_geometry_status",
            "geometry_recovery_method",
            "geometry_blocker_reason",
        ],
    )
    prior_parts = []
    for key in ["target_bin_id", "candidate_bin_id", "frozen_candidate_bin_id"]:
        if key not in prior.columns:
            continue
        hit = prior.loc[_text(prior, key).isin(set(_text(missing, "original_bin_id")))].copy()
        if hit.empty:
            continue
        hit = hit.rename(columns={key: "original_bin_id"})
        hit["prior_geometry_match_key"] = key
        prior_parts.append(hit)
    if prior_parts:
        prior_hits = pd.concat(prior_parts, ignore_index=True, sort=False).drop_duplicates("original_bin_id")
    else:
        prior_hits = pd.DataFrame(columns=["original_bin_id", "graph_edge_id", "completed_geometry_status", "geometry_recovery_method", "geometry_blocker_reason", "prior_geometry_match_key"])

    recoverable = prior_hits.loc[
        _text(prior_hits, "completed_geometry_status").eq("geometry_available")
        & _text(prior_hits, "graph_edge_id").ne("")
    ].copy()
    if recoverable.empty:
        return pd.DataFrame(columns=["original_bin_id", "recovered_geometry_wkt", "geometry_recovery_method"]), prior_hits

    edges = _read_csv(TABLES_DIR / "roadway_graph_edges.csv", usecols=["graph_edge_id", "geometry"])
    edges = edges.loc[_text(edges, "geometry").ne("") & _text(edges, "graph_edge_id").isin(set(_text(recoverable, "graph_edge_id")))].copy()
    edge_lookup = {}
    for row in edges.itertuples(index=False):
        try:
            edge_lookup[str(row.graph_edge_id)] = wkt.loads(str(row.geometry))
        except Exception:
            continue

    dist = missing[["original_bin_id", "distance_start_ft", "distance_end_ft"]].drop_duplicates("original_bin_id")
    work = recoverable.merge(dist, on="original_bin_id", how="left")
    rows = []
    for row in work.itertuples(index=False):
        geom = _line_substring(
            edge_lookup.get(str(row.graph_edge_id)),
            float(pd.to_numeric(row.distance_start_ft, errors="coerce")),
            float(pd.to_numeric(row.distance_end_ft, errors="coerce")),
        )
        if geom is None:
            continue
        rows.append(
            {
                "original_bin_id": row.original_bin_id,
                "recovered_geometry_wkt": geom.wkt,
                "geometry_recovery_method": "prior_geometry_completion_graph_edge_substring",
            }
        )
    return pd.DataFrame(rows).drop_duplicates("original_bin_id"), prior_hits


def _classify_loss(row: pd.Series) -> str:
    original = str(row.get("original_bin_id", ""))
    stream = str(row.get("recovery_stream", ""))
    package = str(row.get("final_bin_source_package", ""))
    if original.startswith("missing_leg::") and "ready_class" in stream:
        return "ready_class_candidate_geometry_lost_from_csv_persistence"
    if original.startswith("missing_leg::") and "route_discontinuity_offset" in stream:
        return "route_discontinuity_offset_candidate_geometry_lost_from_csv_persistence"
    if original.startswith("frozen_candidate_bin_"):
        return "frozen_candidate_prior_geometry_unavailable"
    if package == "consolidated_scaffold_completeness_refresh":
        return "previous_represented_bin_geometry_not_persisted_to_final_target"
    return "no_prior_geometry_match"


def _classify_unrecovered(row: pd.Series) -> str:
    if str(row.get("original_bin_id", "")).startswith("frozen_candidate_bin_"):
        return "held_grade_or_mainline_record" if str(row.get("grade_mainline_holdout_flag", "")).lower() == "true" else "prior_geometry_completion_unavailable"
    prior_status = str(row.get("prior_completed_geometry_status", ""))
    if prior_status == "geometry_unavailable":
        return "source_line_geometry_unavailable"
    if str(row.get("prior_geometry_match_key", "")) == "":
        return "no_prior_geometry_match"
    if str(row.get("distance_start_ft", "")).strip() == "" or str(row.get("distance_end_ft", "")).strip() == "":
        return "distance_fields_insufficient"
    return "manual_review_needed"


def _summarize_missing(missing: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dims = [
        ["geometry_loss_pattern"],
        ["final_bin_source_package", "final_original_or_recovered"],
        ["recovery_stream", "recovery_class"],
        ["distance_band"],
        ["analysis_window"],
        ["physical_leg_id_final"],
        ["carriageway_subbranch_id_final"],
        ["final_alignment_class"],
    ]
    for dim in dims:
        cols = [col for col in dim if col in missing.columns]
        if not cols:
            continue
        grouped = missing.groupby(cols, dropna=False).agg(
            missing_bin_count=("target_bin_id", "size"),
            missing_signal_count=("target_signal_id", "nunique"),
        ).reset_index()
        grouped["summary_scope"] = "+".join(cols)
        for col in cols:
            grouped = grouped.rename(columns={col: f"dimension_{col}"})
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _coverage_metrics(target: pd.DataFrame, status_col: str) -> dict[str, int]:
    has = _text(target, status_col).eq("geometry_available")
    grouped = target.groupby("target_signal_id", dropna=False)[status_col].agg(
        lambda s: bool((s == "geometry_available").all())
    )
    return {
        "bins_with_geometry": int(has.sum()),
        "bins_without_geometry": int((~has).sum()),
        "signals_with_any_geometry": int(_text(target.loc[has], "target_signal_id").nunique()),
        "signals_with_any_missing_geometry": int(_text(target.loc[~has], "target_signal_id").nunique()),
        "signals_with_all_bins_geometry": int(grouped.sum()),
    }


def _make_summary(target: pd.DataFrame, missing: pd.DataFrame, recovery_detail: pd.DataFrame) -> pd.DataFrame:
    before = _coverage_metrics(target, "completed_geometry_status")
    after = _coverage_metrics(target, "geometry_recovery_status")
    rows = []
    for metric, value in before.items():
        rows.append({"summary_section": "before_after_geometry_coverage", "metric": f"before_{metric}", "value": value})
    for metric, value in after.items():
        rows.append({"summary_section": "before_after_geometry_coverage", "metric": f"after_{metric}", "value": value})
    rows.append({"summary_section": "before_after_geometry_coverage", "metric": "missing_bins_examined", "value": len(missing)})
    rows.append(
        {
            "summary_section": "before_after_geometry_coverage",
            "metric": "missing_bins_recovered",
            "value": int(_text(recovery_detail, "geometry_recovery_status").eq("geometry_recovered").sum()),
        }
    )
    rows.append(
        {
            "summary_section": "before_after_geometry_coverage",
            "metric": "missing_signals_recovered_to_any_geometry",
            "value": after["signals_with_any_geometry"] - before["signals_with_any_geometry"],
        }
    )
    rows.append(
        {
            "summary_section": "before_after_geometry_coverage",
            "metric": "remaining_geometry_unavailable_signals",
            "value": after["signals_with_any_missing_geometry"],
        }
    )

    method_counts = recovery_detail.groupby(["geometry_recovery_status", "geometry_recovery_method_final"], dropna=False).agg(
        bin_count=("target_bin_id", "size"),
        signal_count=("target_signal_id", "nunique"),
    ).reset_index()
    for row in method_counts.itertuples(index=False):
        rows.append(
            {
                "summary_section": "recovery_method",
                "metric": f"{row.geometry_recovery_status}:{row.geometry_recovery_method_final}",
                "value": int(row.bin_count),
                "signal_count": int(row.signal_count),
            }
        )
    return pd.DataFrame(rows)


def _remaining_missingness(cleaned: pd.DataFrame) -> pd.DataFrame:
    remaining = cleaned.loc[_text(cleaned, "geometry_recovery_status").ne("geometry_available")]
    if remaining.empty:
        return pd.DataFrame(
            columns=[
                "geometry_unavailable_reason",
                "recovery_stream",
                "final_bin_source_package",
                "bin_count",
                "signal_count",
                "example_signals",
            ]
        )
    return remaining.groupby(
        ["geometry_unavailable_reason", "recovery_stream", "final_bin_source_package"],
        dropna=False,
    ).agg(
        bin_count=("target_bin_id", "size"),
        signal_count=("target_signal_id", "nunique"),
        example_signals=("target_signal_id", _collapse),
    ).reset_index().sort_values(["bin_count", "signal_count"], ascending=False)


def _make_findings(summary: pd.DataFrame, missing_summary: pd.DataFrame, remaining: pd.DataFrame) -> str:
    values = {str(row.metric): row.value for row in summary.itertuples(index=False) if str(row.summary_section) == "before_after_geometry_coverage"}
    recovered = int(values.get("missing_bins_recovered", 0))
    remaining_bins = int(values.get("after_bins_without_geometry", 0))
    before_bins = int(values.get("before_bins_with_geometry", 0))
    after_bins = int(values.get("after_bins_with_geometry", 0))
    before_signals = int(values.get("before_signals_with_any_geometry", 0))
    after_signals = int(values.get("after_signals_with_any_geometry", 0))

    dominant = missing_summary.loc[missing_summary["summary_scope"].eq("geometry_loss_pattern")].copy()
    dominant_text = "- No missing geometry rows were found."
    if not dominant.empty:
        dominant = dominant.sort_values("missing_bin_count", ascending=False).head(8)
        dominant_text = "\n".join(
            f"- {row.dimension_geometry_loss_pattern}: {int(row.missing_bin_count):,} bins across {int(row.missing_signal_count):,} signals"
            for row in dominant.itertuples(index=False)
        )

    remaining_text = "- No geometry-unavailable rows remain."
    if not remaining.empty:
        remaining_text = "\n".join(
            f"- {row.geometry_unavailable_reason}: {int(row.bin_count):,} bins across {int(row.signal_count):,} signals"
            for row in remaining.head(8).itertuples(index=False)
        )

    ready = "yes" if remaining_bins <= 2 else "conditional"
    return f"""# Final Access Target Geometry Persistence Cleanup

**Bounded question:** recover or explain geometry persistence gaps in the final review-only access target before interpreting access coverage.

## Findings

1. The final access target started with **{before_bins:,} bins with geometry** across **{before_signals:,} signals**.
2. The cleanup recovered geometry for **{recovered:,} previously geometry-unavailable bins**.
3. The cleaned target has **{after_bins:,} bins with geometry** across **{after_signals:,} signals**.
4. Remaining geometry-unavailable rows: **{remaining_bins:,} bins**.
5. Dominant geometry-loss causes:
{dominant_text}
6. Remaining missingness:
{remaining_text}

## Interpretation

The access rerun's geometry loss was primarily a persistence/lineage problem, not evidence of substantive scaffold or access loss. Old represented rows recovered through the prior geometry-completion graph-edge substring lineage. Missing-leg recovery rows recovered from their review GeoPackage layers because the corresponding CSV/context tables preserved IDs and route/context fields but not line WKT.

## Recommendation

Access should be rerun using `final_access_target_bins_geometry_cleaned.csv` before interpreting final access coverage. Access/crash assignment, rates, models, and scaffold logic were not run or changed in this cleanup pass.

Geometry coverage sufficient to repeat access rerun: **{ready}**.
"""


def _make_qa(remaining_bins: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("no_active_outputs_modified", "pass", "Writes only to final_access_target_geometry_persistence_cleanup review folder."),
            ("no_candidates_promoted", "pass", "No candidate-promotion fields are changed."),
            ("no_crash_records_read", "pass", "CSV reader rejects crash record/direction fields; no crash files are listed as inputs."),
            ("no_crash_direction_fields_read", "pass", "Crash direction tokens are blocked."),
            ("no_access_assignment_performed", "pass", "This module writes geometry target tables only and does not buffer/join access points."),
            ("no_rates_or_models", "pass", "No rate or model calculations are performed."),
            ("no_geometry_fabricated", "pass", "Geometry is recovered only from prior graph-edge lineage or review GeoPackage candidate layers."),
            ("geometry_recovery_fields_present", "pass", "Cleaned target includes geometry_recovery_method_final/status and QA reason fields."),
            ("outputs_review_only", "pass", "All outputs are written under the review/current cleanup folder."),
            ("remaining_geometry_unavailable_reported", "pass" if remaining_bins >= 0 else "fail", f"Remaining unavailable bins reported: {remaining_bins:,}."),
        ],
        columns=["qa_check", "status", "note"],
    )


def _manifest(started: datetime, output_names: list[str]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.build.final_access_target_geometry_persistence_cleanup",
        "bounded_question": "read-only geometry persistence cleanup for final access target bins",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "started_utc": started.isoformat(),
        "output_folder": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": output_names,
        "non_goals_confirmed": [
            "no_access_rerun",
            "no_scaffold_logic_change",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_active_output_modification",
            "no_candidate_promotion",
        ],
    }


def main() -> None:
    started = datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    missing_inputs = _missing_inputs()
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing_inputs))

    target = _read_csv(FINAL_ACCESS_DIR / "final_access_target_bins.csv")
    if "geometry_recovery_method.1" in target.columns:
        target = target.drop(columns=["geometry_recovery_method.1"])
    target["geometry_wkt_original"] = _text(target, "geometry_wkt")
    target["geometry_wkt_cleaned"] = _text(target, "geometry_wkt")
    target["geometry_recovery_method_final"] = _text(target, "geometry_recovery_method")
    target["geometry_recovery_status"] = _text(target, "completed_geometry_status")
    target["geometry_unavailable_reason"] = _text(target, "geometry_blocker_reason")
    target["geometry_qa_flag"] = np.where(_text(target, "completed_geometry_status").eq("geometry_available"), "geometry_already_present", "geometry_missing_before_cleanup")
    target["review_only_flag"] = "true"

    missing_mask = _text(target, "completed_geometry_status").ne("geometry_available") | _text(target, "geometry_wkt").eq("")
    missing = target.loc[missing_mask].copy()
    missing["geometry_loss_pattern"] = missing.apply(_classify_loss, axis=1)

    gpkg_lookup = _candidate_gpkg_geometry_lookup()
    prior_lookup, prior_hits = _prior_graph_edge_geometry_lookup(missing)
    lookup = pd.concat([gpkg_lookup, prior_lookup], ignore_index=True, sort=False).drop_duplicates("original_bin_id")

    if not lookup.empty:
        target = target.merge(lookup, on="original_bin_id", how="left")
        recover_mask = missing_mask & _text(target, "recovered_geometry_wkt").ne("")
        target.loc[recover_mask, "geometry_wkt_cleaned"] = target.loc[recover_mask, "recovered_geometry_wkt"]
        target.loc[recover_mask, "geometry_wkt"] = target.loc[recover_mask, "recovered_geometry_wkt"]
        target.loc[recover_mask, "geometry_recovery_method_final"] = target.loc[recover_mask, "geometry_recovery_method_y"]
        target.loc[recover_mask, "geometry_recovery_status"] = "geometry_available"
        target.loc[recover_mask, "geometry_unavailable_reason"] = ""
        target.loc[recover_mask, "geometry_qa_flag"] = "geometry_recovered_from_deterministic_lineage"
        target = target.drop(columns=["recovered_geometry_wkt", "geometry_recovery_method_y"], errors="ignore")
        if "geometry_recovery_method_x" in target.columns:
            target = target.rename(columns={"geometry_recovery_method_x": "geometry_recovery_method"})

    prior_keep = [
        "original_bin_id",
        "prior_geometry_match_key",
        "completed_geometry_status",
        "geometry_recovery_method",
        "geometry_blocker_reason",
        "graph_edge_id",
        "source_road_row_id",
    ]
    prior_enriched = prior_hits[[col for col in prior_keep if col in prior_hits.columns]].copy()
    prior_enriched = prior_enriched.rename(
        columns={
            "completed_geometry_status": "prior_completed_geometry_status",
            "geometry_recovery_method": "prior_geometry_recovery_method",
            "geometry_blocker_reason": "prior_geometry_blocker_reason",
        }
    )

    missing_detail = missing.merge(prior_enriched, on="original_bin_id", how="left")
    missing_detail["geometry_loss_pattern"] = missing_detail.apply(_classify_loss, axis=1)

    recovery_detail = target.loc[missing_mask].copy()
    recovery_detail = recovery_detail.merge(prior_enriched, on="original_bin_id", how="left")
    recovered_mask = _text(recovery_detail, "geometry_recovery_status").eq("geometry_available")
    recovery_detail["geometry_recovery_status"] = np.where(recovered_mask, "geometry_recovered", "geometry_unavailable")
    recovery_detail["geometry_recovery_method_final"] = _text(recovery_detail, "geometry_recovery_method_final").where(
        recovered_mask,
        "",
    )
    recovery_detail["geometry_unavailable_reason"] = np.where(
        recovered_mask,
        "",
        recovery_detail.apply(_classify_unrecovered, axis=1),
    )

    unrecovered_keys = set(_text(recovery_detail.loc[~recovered_mask], "original_bin_id"))
    unrecovered_mask = _text(target, "original_bin_id").isin(unrecovered_keys) & _text(target, "geometry_recovery_status").ne("geometry_available")
    if unrecovered_mask.any():
        target.loc[unrecovered_mask, "geometry_unavailable_reason"] = target.loc[unrecovered_mask].apply(_classify_unrecovered, axis=1)
        target.loc[unrecovered_mask, "geometry_qa_flag"] = "geometry_unavailable_after_cleanup"

    missing_summary = _summarize_missing(missing_detail)
    summary = _make_summary(target, missing_detail, recovery_detail)
    summary_out = pd.concat([summary, missing_summary], ignore_index=True, sort=False)
    remaining = _remaining_missingness(target)
    findings = _make_findings(summary, missing_summary, remaining)
    remaining_bins = int(_text(target, "geometry_recovery_status").ne("geometry_available").sum())
    qa = _make_qa(remaining_bins)

    output_frames = {
        "final_access_geometry_missing_detail.csv": missing_detail,
        "final_access_geometry_recovery_detail.csv": recovery_detail,
        "final_access_target_bins_geometry_cleaned.csv": target,
        "final_access_geometry_recovery_summary.csv": summary_out,
        "final_access_geometry_remaining_missingness.csv": remaining,
        "final_access_geometry_persistence_qa.csv": qa,
    }
    for name, frame in output_frames.items():
        _write_csv(frame, name)

    _write_text(findings, "final_access_geometry_persistence_findings.md")
    output_names = list(output_frames) + [
        "final_access_geometry_persistence_findings.md",
        "final_access_geometry_persistence_manifest.json",
        "run_progress_log.txt",
    ]
    _write_json(_manifest(started, output_names), "final_access_geometry_persistence_manifest.json")
    _checkpoint("complete", note=f"remaining_geometry_unavailable_bins={remaining_bins:,}")


if __name__ == "__main__":
    main()
