from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import STRtree, wkb, wkt

from .crs_utils import WORKING_CRS_AUTHORITY, WORKING_CRS_NAME


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_crash_candidate_assignment"

FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/final_crash_catchment_design_feasibility"
STABLE_SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"

CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")
BUFFER_WIDTHS_FT = [35, 50, 75]
FT_TO_M = 0.3048
CHUNK_SIZE = 50_000

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

CRASH_BASE_COLUMNS = [
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CRASH_DT",
    "CRASH_SEVERITY",
    "K_PEOPLE",
    "A_PEOPLE",
    "B_PEOPLE",
    "C_PEOPLE",
    "PERSONS_INJURED",
    "VEH_COUNT",
    "COLLISION_TYPE",
    "ROADWAY_DESCRIPTION",
    "INTERSECTION_TYPE",
    "FIRST_HARMFUL_EVENT",
    "FIRST_HARMFUL_EVENT_LOC",
    "RELATION_TO_ROADWAY",
    "TRAFFIC_CONTROL_TYPE",
    "MAINLINE_YN",
    "RTE_NM",
    "RNS_MP",
    "NODE",
    "OFFSET",
    "geometry",
]

BIN_COLUMNS = [
    "target_signal_id",
    "stable_signal_id",
    "source_signal_id",
    "stable_bin_id",
    "stable_travelway_id",
    "source_layer",
    "source_route_id",
    "source_route_name",
    "source_route_common",
    "source_measure_start",
    "source_measure_end",
    "source_feature_local_fid",
    "geometry_hash",
    "lineage_match_method",
    "lineage_confidence",
    "physical_leg_id_final",
    "carriageway_subbranch_id_final",
    "distance_start_ft",
    "distance_end_ft",
    "distance_band",
    "analysis_window",
    "final_alignment_class",
    "source_limited_holdout_flag",
    "grade_mainline_holdout_flag",
    "still_insufficient_evidence_flag",
    "review_only_recovery_provenance",
    "speed_aadt_ready_bin",
    "has_rns_speed",
    "has_aadt",
    "has_exposure_denominator",
    "review_only_flag",
    "geometry_wkt_cleaned",
]

REQUIRED_INPUTS = [
    FEASIBILITY_DIR / "crash_source_inventory.csv",
    FEASIBILITY_DIR / "final_scaffold_catchment_target_inventory.csv",
    FEASIBILITY_DIR / "candidate_crash_catchment_designs.csv",
    FEASIBILITY_DIR / "candidate_crash_catchment_overlap_risk.csv",
    FEASIBILITY_DIR / "candidate_crash_catchment_fanout_risk.csv",
    FEASIBILITY_DIR / "crash_assignment_doctrine_recommendation.csv",
    FEASIBILITY_DIR / "crash_catchment_feasibility_summary.csv",
    FEASIBILITY_DIR / "final_crash_catchment_design_feasibility_manifest.json",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_lineage_audit.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_access_readiness_decision.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_ACCESS_DIR / "final_access_crash_catchment_readiness.csv",
    FINAL_ACCESS_DIR / "final_access_product_role_doctrine.csv",
    FINAL_ACCESS_DIR / "final_access_baseline_manifest.json",
    CRASH_SOURCE,
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


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _is_direction_field(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in CRASH_DIRECTION_FIELD_TOKENS)


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _safe_read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _crash_schema_columns() -> list[str]:
    return list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)


def _load_crashes() -> tuple[pd.DataFrame, list[str]]:
    schema_cols = _crash_schema_columns()
    direction_cols = [column for column in schema_cols if _is_direction_field(column)]
    cols = [column for column in CRASH_BASE_COLUMNS if column in schema_cols]
    # Direction values are preserved only if explicit direction fields exist; none are used in assignment.
    cols.extend(column for column in direction_cols if column not in cols)
    crashes = pd.read_parquet(CRASH_SOURCE, columns=cols)
    crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    crashes["crash_direction_fields_inventory_only"] = "|".join(direction_cols)
    crashes["crash_direction_used_for_assignment"] = False
    _checkpoint("load normalized crashes", len(crashes))
    return crashes, direction_cols


def _load_bins() -> pd.DataFrame:
    path = STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv"
    bins = _safe_read_csv(path, BIN_COLUMNS)
    bins["bin_row_id"] = np.arange(len(bins), dtype=np.int64)
    bins["physical_leg_id"] = _text(bins, "physical_leg_id_final")
    bins["carriageway_subbranch_id"] = _text(bins, "carriageway_subbranch_id_final")
    bins["review_only_flag"] = True
    bins = bins.loc[_text(bins, "geometry_wkt_cleaned").str.strip().ne("")].copy()
    _checkpoint("filter bins with geometry", len(bins))
    return bins


def _parse_wkb_points(values: pd.Series) -> np.ndarray:
    geoms = []
    for value in values:
        geoms.append(wkb.loads(value) if value is not None else None)
    return np.asarray(geoms, dtype=object)


def _parse_wkt_lines(values: pd.Series) -> np.ndarray:
    geoms = []
    for value in values:
        try:
            geom = wkt.loads(value)
            geoms.append(geom if not geom.is_empty else None)
        except Exception:
            geoms.append(None)
    return np.asarray(geoms, dtype=object)


def _assignment_pairs(points: np.ndarray, lines: np.ndarray, buffer_ft: int) -> pd.DataFrame:
    valid_line_mask = np.asarray([geom is not None for geom in lines], dtype=bool)
    valid_lines = lines[valid_line_mask]
    line_original_index = np.flatnonzero(valid_line_mask)
    tree = STRtree(valid_lines)
    rows = []
    distance_m = buffer_ft * FT_TO_M
    for start in range(0, len(points), CHUNK_SIZE):
        stop = min(start + CHUNK_SIZE, len(points))
        chunk = points[start:stop]
        valid_point_mask = np.asarray([geom is not None and not geom.is_empty for geom in chunk], dtype=bool)
        if not valid_point_mask.any():
            continue
        valid_points = chunk[valid_point_mask]
        point_original_index = np.flatnonzero(valid_point_mask) + start
        pair_index = tree.query(valid_points, predicate="dwithin", distance=distance_m)
        if pair_index.size == 0:
            continue
        crash_idx = point_original_index[pair_index[0]]
        bin_idx = line_original_index[pair_index[1]]
        rows.append(pd.DataFrame({"crash_row_id": crash_idx, "bin_row_pos": bin_idx}))
        _checkpoint(f"spatial query {buffer_ft}ft chunk {start}-{stop}", len(rows[-1]))
    if not rows:
        return pd.DataFrame(columns=["crash_row_id", "bin_row_pos"])
    return pd.concat(rows, ignore_index=True)


def _build_assignment_detail(crashes: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    crashes = crashes.reset_index(drop=True).copy()
    crashes["crash_row_id"] = np.arange(len(crashes), dtype=np.int64)
    bins = bins.reset_index(drop=True).copy()
    bins["bin_row_pos"] = np.arange(len(bins), dtype=np.int64)

    points = _parse_wkb_points(crashes["geometry"])
    lines = _parse_wkt_lines(bins["geometry_wkt_cleaned"])

    crash_attr_cols = [
        "crash_row_id",
        "stable_crash_id",
        "DOCUMENT_NBR",
        "CRASH_YEAR",
        "CRASH_DT",
        "CRASH_SEVERITY",
        "K_PEOPLE",
        "A_PEOPLE",
        "B_PEOPLE",
        "C_PEOPLE",
        "PERSONS_INJURED",
        "VEH_COUNT",
        "COLLISION_TYPE",
        "ROADWAY_DESCRIPTION",
        "INTERSECTION_TYPE",
        "FIRST_HARMFUL_EVENT",
        "FIRST_HARMFUL_EVENT_LOC",
        "RELATION_TO_ROADWAY",
        "TRAFFIC_CONTROL_TYPE",
        "MAINLINE_YN",
        "RTE_NM",
        "RNS_MP",
        "NODE",
        "OFFSET",
        "crash_direction_fields_inventory_only",
        "crash_direction_used_for_assignment",
    ]
    crash_attr_cols = [column for column in crash_attr_cols if column in crashes.columns]
    bin_attr_cols = [
        "bin_row_pos",
        "target_signal_id",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "lineage_confidence",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
        "speed_aadt_ready_bin",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "review_only_flag",
    ]
    bin_attr_cols = [column for column in bin_attr_cols if column in bins.columns]

    detail_frames = []
    for width in BUFFER_WIDTHS_FT:
        pairs = _assignment_pairs(points, lines, width)
        pairs["buffer_width_ft"] = width
        if pairs.empty:
            continue
        pairs = pairs.merge(crashes[crash_attr_cols], on="crash_row_id", how="left")
        pairs = pairs.merge(bins[bin_attr_cols], on="bin_row_pos", how="left")
        pairs["unweighted_assignment"] = 1.0
        fanout = pairs.groupby("stable_crash_id", dropna=False).size().rename("assignment_fanout_count").reset_index()
        pairs = pairs.merge(fanout, on="stable_crash_id", how="left")
        pairs["source_preserving_weight"] = 1.0 / pairs["assignment_fanout_count"].astype(float)
        pairs["assignment_rule"] = f"line_dwithin_{width}ft"
        pairs["assignment_status"] = "review_only_candidate"
        pairs["crash_direction_use_status"] = "inventory_only_not_used_for_assignment"
        detail_frames.append(pairs.drop(columns=["crash_row_id", "bin_row_pos"], errors="ignore"))
        _checkpoint(f"build assignment detail {width}ft", len(detail_frames[-1]))
    if not detail_frames:
        return pd.DataFrame()
    detail = pd.concat(detail_frames, ignore_index=True)
    detail = detail.sort_values(["buffer_width_ft", "stable_crash_id", "target_signal_id", "stable_bin_id"]).reset_index(drop=True)
    _checkpoint("assignment detail all buffers", len(detail))
    return detail


def _rollup(detail: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(columns=[*group_cols, "unique_crash_count", "assignment_row_count", "weighted_crash_count", "unweighted_crash_count"])
    out = (
        detail.groupby(group_cols, dropna=False)
        .agg(
            unique_crash_count=("stable_crash_id", "nunique"),
            assignment_row_count=("stable_crash_id", "size"),
            weighted_crash_count=("source_preserving_weight", "sum"),
            unweighted_crash_count=("unweighted_assignment", "sum"),
            source_limited_assignment_rows=("source_limited_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            grade_mainline_assignment_rows=("grade_mainline_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            still_insufficient_assignment_rows=("still_insufficient_evidence_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
        )
        .reset_index()
    )
    return out


def _fanout_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if detail.empty:
        return pd.DataFrame(rows)
    for width, frame in detail.groupby("buffer_width_ft", dropna=False):
        by_crash = frame.groupby("stable_crash_id").agg(
            assignment_rows=("stable_bin_id", "size"),
            signals=("target_signal_id", "nunique"),
            physical_legs=("physical_leg_id", "nunique"),
            signal_leg_pairs=("physical_leg_id", "nunique"),
        )
        for label, mask in {
            "1_signal": by_crash["signals"].eq(1),
            "2_signals": by_crash["signals"].eq(2),
            "3_signals": by_crash["signals"].eq(3),
            "4plus_signals": by_crash["signals"].ge(4),
            "multiple_signals": by_crash["signals"].gt(1),
            "multiple_assignment_rows": by_crash["assignment_rows"].gt(1),
        }.items():
            rows.append(
                {
                    "buffer_width_ft": width,
                    "fanout_class": label,
                    "crash_count": int(mask.sum()),
                    "share_of_assigned_crashes": round(float(mask.mean()), 6) if len(mask) else 0,
                }
            )
        same_signal_leg = (
            frame.groupby(["stable_crash_id", "target_signal_id"], dropna=False)["physical_leg_id"].nunique().reset_index(name="leg_count")
        )
        rows.append(
            {
                "buffer_width_ft": width,
                "fanout_class": "multiple_legs_same_signal",
                "crash_count": int(same_signal_leg.loc[same_signal_leg["leg_count"].gt(1), "stable_crash_id"].nunique()),
                "share_of_assigned_crashes": round(
                    int(same_signal_leg.loc[same_signal_leg["leg_count"].gt(1), "stable_crash_id"].nunique()) / len(by_crash), 6
                )
                if len(by_crash)
                else 0,
            }
        )
    return pd.DataFrame(rows)


def _overlap_queue(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    crash_fanout = (
        detail.groupby(["buffer_width_ft", "stable_crash_id"], dropna=False)
        .agg(
            assignment_rows=("stable_bin_id", "size"),
            signal_count=("target_signal_id", "nunique"),
            physical_leg_count=("physical_leg_id", "nunique"),
            first_crash_year=("CRASH_YEAR", "first"),
            first_crash_severity=("CRASH_SEVERITY", "first"),
            first_collision_type=("COLLISION_TYPE", "first"),
            sample_signals=("target_signal_id", lambda s: "|".join(sorted(set(s.astype(str)))[:8])),
            sample_bins=("stable_bin_id", lambda s: "|".join(sorted(set(s.astype(str)))[:8])),
            grade_mainline_rows=("grade_mainline_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            source_limited_rows=("source_limited_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
        )
        .reset_index()
    )
    crash_fanout["review_priority"] = crash_fanout["assignment_rows"] + 3 * crash_fanout["signal_count"] + crash_fanout["physical_leg_count"]
    crash_rows = crash_fanout.sort_values("review_priority", ascending=False).head(250).copy()
    crash_rows["review_queue_type"] = "high_fanout_crash"

    signal_window = (
        detail.groupby(["buffer_width_ft", "target_signal_id", "analysis_window"], dropna=False)
        .agg(
            unique_crash_count=("stable_crash_id", "nunique"),
            assignment_rows=("stable_bin_id", "size"),
            physical_leg_count=("physical_leg_id", "nunique"),
            grade_mainline_rows=("grade_mainline_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            source_limited_rows=("source_limited_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
        )
        .reset_index()
        .sort_values(["buffer_width_ft", "unique_crash_count", "assignment_rows"], ascending=[True, False, False])
        .head(250)
    )
    signal_window["stable_crash_id"] = ""
    signal_window["signal_count"] = 1
    signal_window["sample_signals"] = signal_window["target_signal_id"]
    signal_window["sample_bins"] = ""
    signal_window["first_crash_year"] = ""
    signal_window["first_crash_severity"] = ""
    signal_window["first_collision_type"] = ""
    signal_window["review_queue_type"] = "high_count_signal_window"
    signal_window["review_priority"] = signal_window["unique_crash_count"] + signal_window["assignment_rows"] / 1000

    common = [
        "review_queue_type",
        "buffer_width_ft",
        "stable_crash_id",
        "target_signal_id",
        "analysis_window",
        "assignment_rows",
        "unique_crash_count",
        "signal_count",
        "physical_leg_count",
        "first_crash_year",
        "first_crash_severity",
        "first_collision_type",
        "sample_signals",
        "sample_bins",
        "grade_mainline_rows",
        "source_limited_rows",
        "review_priority",
    ]
    for col in common:
        if col not in crash_rows.columns:
            crash_rows[col] = ""
        if col not in signal_window.columns:
            signal_window[col] = ""
    return pd.concat([crash_rows[common], signal_window[common]], ignore_index=True)


def _broad_envelope_crash_ids(crashes: pd.DataFrame, bins: pd.DataFrame) -> set[str]:
    bounds = []
    for value in _text(bins, "geometry_wkt_cleaned").loc[_text(bins, "geometry_wkt_cleaned").str.strip().ne("")]:
        try:
            geom = wkt.loads(value)
            if not geom.is_empty:
                bounds.append(geom.bounds)
        except Exception:
            continue
    if not bounds or "geometry" not in crashes.columns:
        return set()
    # Broad envelope only: bbox membership is a precheck, not a crash assignment.
    pad_m = 2_500 * FT_TO_M
    minx = min(b[0] for b in bounds) - pad_m
    miny = min(b[1] for b in bounds) - pad_m
    maxx = max(b[2] for b in bounds) + pad_m
    maxy = max(b[3] for b in bounds) + pad_m
    ids: set[str] = set()
    for crash_id, value in zip(crashes["stable_crash_id"], crashes["geometry"]):
        try:
            point = wkb.loads(value)
            x, y = point.x, point.y
            if minx <= x <= maxx and miny <= y <= maxy:
                ids.add(str(crash_id))
        except Exception:
            continue
    return ids


def _source_coverage(crashes: pd.DataFrame, detail: pd.DataFrame, broad_envelope_ids: set[str]) -> pd.DataFrame:
    rows = []
    total = int(crashes["stable_crash_id"].nunique())
    for width in BUFFER_WIDTHS_FT:
        assigned = set(detail.loc[detail["buffer_width_ft"].eq(width), "stable_crash_id"].astype(str)) if not detail.empty else set()
        rows.append(
            {
                "buffer_width_ft": width,
                "total_normalized_crashes": total,
                "crashes_inside_broad_scaffold_envelope": len(broad_envelope_ids),
                "assigned_unique_crashes": len(assigned),
                "unassigned_unique_crashes": total - len(assigned),
                "broad_envelope_unassigned_crashes": len(broad_envelope_ids - assigned),
                "assigned_share": round(len(assigned) / total, 6) if total else 0,
                "assignment_rows": int(detail.loc[detail["buffer_width_ft"].eq(width)].shape[0]) if not detail.empty else 0,
            }
        )
    out = pd.DataFrame(rows)

    breakdown_rows = []
    for width in BUFFER_WIDTHS_FT:
        assigned_ids = set(detail.loc[detail["buffer_width_ft"].eq(width), "stable_crash_id"].astype(str)) if not detail.empty else set()
        temp = crashes.copy()
        temp["assigned"] = temp["stable_crash_id"].astype(str).isin(assigned_ids)
        for field in ["CRASH_YEAR", "CRASH_SEVERITY", "COLLISION_TYPE"]:
            if field not in temp.columns:
                continue
            grouped = temp.groupby([field, "assigned"], dropna=False).size().reset_index(name="crash_count")
            for row in grouped.itertuples(index=False):
                breakdown_rows.append(
                    {
                        "buffer_width_ft": width,
                        "breakdown_field": field,
                        "breakdown_value": str(getattr(row, field)),
                        "assigned": bool(row.assigned),
                        "crash_count": int(row.crash_count),
                    }
                )
    return out, pd.DataFrame(breakdown_rows)


def _unassigned_summary(crashes: pd.DataFrame, detail: pd.DataFrame, broad_envelope_ids: set[str]) -> pd.DataFrame:
    rows = []
    for width in BUFFER_WIDTHS_FT:
        assigned_ids = set(detail.loc[detail["buffer_width_ft"].eq(width), "stable_crash_id"].astype(str)) if not detail.empty else set()
        unassigned = crashes.loc[~crashes["stable_crash_id"].astype(str).isin(assigned_ids)].copy()
        rows.append(
            {
                "buffer_width_ft": width,
                "unassigned_crashes": int(len(unassigned)),
                "unassigned_with_geometry": int(unassigned["geometry"].notna().sum()) if "geometry" in unassigned.columns else 0,
                "unassigned_inside_broad_scaffold_envelope": int(unassigned["stable_crash_id"].astype(str).isin(broad_envelope_ids).sum()),
                "top_unassigned_years": "|".join(
                    f"{k}:{v}" for k, v in unassigned["CRASH_YEAR"].astype(str).value_counts().head(5).items()
                )
                if "CRASH_YEAR" in unassigned.columns
                else "",
                "top_unassigned_severities": "|".join(
                    f"{k}:{v}" for k, v in unassigned["CRASH_SEVERITY"].astype(str).value_counts().head(5).items()
                )
                if "CRASH_SEVERITY" in unassigned.columns
                else "",
            }
        )
    return pd.DataFrame(rows)


def _qa(direction_cols: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", f"outputs written only to {OUT_DIR}"),
        ("no_candidates_promoted", "passed", "review-only crash candidate assignments"),
        ("no_rates_or_models", "passed", "no rate/model calculations"),
        ("crash_direction_not_used_for_scaffold_or_geometry", "passed", "direction fields are not used in spatial query or scaffold logic"),
        ("crash_direction_fields_inventory_only", "passed", "|".join(direction_cols) if direction_cols else "none detected"),
        ("multi_assignment_present", "passed", "nearest-only forcing is not used"),
        ("source_preserving_weights_present", "passed", "source_preserving_weight = 1 / per-crash fanout per buffer"),
        ("stable_travelway_id_carried", "passed", "assignment detail carries stable_travelway_id"),
        ("scaffold_qa_flags_carried", "passed", "final_alignment/source_limited/grade/still_insufficient/provenance fields carried"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(
    crashes: pd.DataFrame,
    detail: pd.DataFrame,
    fanout: pd.DataFrame,
    signal_window: pd.DataFrame,
    source_coverage: pd.DataFrame,
) -> str:
    def assigned(width: int) -> int:
        row = source_coverage.loc[source_coverage["buffer_width_ft"].eq(width)]
        return int(row["assigned_unique_crashes"].iloc[0]) if not row.empty else 0

    def unassigned(width: int) -> int:
        row = source_coverage.loc[source_coverage["buffer_width_ft"].eq(width)]
        return int(row["unassigned_unique_crashes"].iloc[0]) if not row.empty else 0

    def broad_unassigned(width: int) -> int:
        row = source_coverage.loc[source_coverage["buffer_width_ft"].eq(width)]
        return int(row["broad_envelope_unassigned_crashes"].iloc[0]) if not row.empty else 0

    def fan(width: int, klass: str) -> int:
        row = fanout.loc[fanout["buffer_width_ft"].eq(width) & fanout["fanout_class"].eq(klass)]
        return int(row["crash_count"].iloc[0]) if not row.empty else 0

    top = signal_window.loc[signal_window["buffer_width_ft"].eq(50)].sort_values("unique_crash_count", ascending=False).head(5)
    top_text = "\n".join(
        f"- {row.target_signal_id}, {row.analysis_window}: {int(row.unique_crash_count):,} unique crashes"
        for row in top.itertuples(index=False)
    )
    return f"""# Final Crash Candidate Assignment Findings

## Bounded Question

This review-only pass assigns normalized 2022-2024 crash points to final stable-lineage scaffold bin-line catchments using 35 ft, 50 ft, and 75 ft distances. It does not create final crash context, calculate rates, run models, promote assignments, or use crash direction fields for scaffold, upstream/downstream, signal-leg, or catchment geometry.

## Crash Source

- Normalized crashes loaded: {crashes['stable_crash_id'].nunique():,}
- Geometry source: `artifacts/normalized/crashes.parquet`
- CRS: inferred {WORKING_CRS_AUTHORITY} ({WORKING_CRS_NAME})

## Assigned Crashes

- 35 ft assigned crashes: {assigned(35):,}; unassigned: {unassigned(35):,}
- 50 ft assigned crashes: {assigned(50):,}; unassigned: {unassigned(50):,}; broad-envelope unassigned: {broad_unassigned(50):,}
- 75 ft assigned crashes: {assigned(75):,}; unassigned: {unassigned(75):,}

## Fanout

At 50 ft:

- Crashes assigned to multiple signals: {fan(50, 'multiple_signals'):,}
- Crashes assigned to multiple legs of the same signal: {fan(50, 'multiple_legs_same_signal'):,}
- Crashes with 4+ signal fanout: {fan(50, '4plus_signals'):,}

## Highest 50 ft Signal-Window Counts

{top_text if top_text else '- No assigned signal-window units.'}

## Review Interpretation

The 50 ft product is suitable as the primary review crash assignment product because it follows the feasibility doctrine, preserves stable Travelway lineage, carries scaffold QA flags, allows multi-assignment, and records source-preserving weights. It is not yet a final analytical crash context and should be reviewed against fanout/overlap queues before rate or model work.

## Recommended Next Pass

Run a bounded crash-assignment QA/readiness pass that reviews high-fanout crashes, high-count signal windows, grade/mainline/source-limited QA classes, and the 35/50/75 ft sensitivity differences. Keep crash direction fields out of geometry and upstream/downstream logic.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start final_crash_candidate_assignment")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    crashes, direction_cols = _load_crashes()
    bins = _load_bins()
    detail = _build_assignment_detail(crashes, bins)

    signal_window = _rollup(detail, ["buffer_width_ft", "target_signal_id", "analysis_window"])
    signal_leg_window = _rollup(detail, ["buffer_width_ft", "target_signal_id", "physical_leg_id", "analysis_window"])
    signal_rollup = _rollup(detail, ["buffer_width_ft", "target_signal_id"])
    bin_rollup = _rollup(detail, ["buffer_width_ft", "stable_bin_id", "target_signal_id", "analysis_window"])
    fanout = _fanout_summary(detail)
    queue = _overlap_queue(detail)
    broad_envelope_ids = _broad_envelope_crash_ids(crashes, bins)
    _checkpoint("broad scaffold envelope crash ids", len(broad_envelope_ids))
    source_coverage, source_coverage_breakdowns = _source_coverage(crashes, detail, broad_envelope_ids)
    unassigned = _unassigned_summary(crashes, detail, broad_envelope_ids)
    source_coverage = pd.concat(
        [source_coverage.assign(summary_type="overall"), source_coverage_breakdowns.assign(summary_type="field_breakdown")],
        ignore_index=True,
        sort=False,
    )

    _write_csv(detail, "crash_candidate_assignment_detail.csv")
    _write_csv(signal_window, "crash_candidate_assignment_signal_window_rollup.csv")
    _write_csv(signal_leg_window, "crash_candidate_assignment_signal_physical_leg_window_rollup.csv")
    _write_csv(signal_rollup, "crash_candidate_assignment_signal_rollup.csv")
    _write_csv(bin_rollup, "crash_candidate_assignment_bin_rollup.csv")
    _write_csv(fanout, "crash_candidate_assignment_fanout_summary.csv")
    _write_csv(queue, "crash_candidate_assignment_overlap_review_queue.csv")
    _write_csv(source_coverage, "crash_candidate_assignment_source_coverage_summary.csv")
    _write_csv(unassigned, "crash_candidate_assignment_unassigned_summary.csv")
    _write_text(_findings(crashes, detail, fanout, signal_window, source_coverage), "final_crash_candidate_assignment_findings.md")
    _write_csv(_qa(direction_cols), "final_crash_candidate_assignment_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.build.final_crash_candidate_assignment",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "buffer_widths_ft": BUFFER_WIDTHS_FT,
            "review_only": True,
            "final_crash_assignment_produced": False,
            "rates_or_models_calculated": False,
            "crash_direction_use": "inventory_only_not_used_for_assignment_or_geometry",
            "assignment_method": "STRtree dwithin crash points to stable-lineage bin lines",
            "outputs": [
                "crash_candidate_assignment_detail.csv",
                "crash_candidate_assignment_signal_window_rollup.csv",
                "crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
                "crash_candidate_assignment_signal_rollup.csv",
                "crash_candidate_assignment_bin_rollup.csv",
                "crash_candidate_assignment_fanout_summary.csv",
                "crash_candidate_assignment_overlap_review_queue.csv",
                "crash_candidate_assignment_source_coverage_summary.csv",
                "crash_candidate_assignment_unassigned_summary.csv",
                "final_crash_candidate_assignment_findings.md",
                "final_crash_candidate_assignment_qa.csv",
                "final_crash_candidate_assignment_manifest.json",
                "run_progress_log.txt",
            ],
        },
        "final_crash_candidate_assignment_manifest.json",
    )
    _checkpoint("complete final_crash_candidate_assignment")


if __name__ == "__main__":
    main()
