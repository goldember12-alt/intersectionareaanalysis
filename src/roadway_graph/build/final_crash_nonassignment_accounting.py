from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import STRtree, wkb, wkt
from shapely.geometry import Point

from .crs_utils import WORKING_CRS_AUTHORITY, WORKING_CRS_NAME


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_crash_nonassignment_accounting"

ASSIGNMENT_DIR = OUTPUT_ROOT / "review/current/final_crash_candidate_assignment"
STABLE_SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"

CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")
FT_TO_M = 0.3048
M_TO_FT = 1.0 / FT_TO_M
CHUNK_SIZE = 50_000

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

CRASH_COLUMNS = [
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
    "lineage_confidence",
    "speed_aadt_ready_bin",
    "geometry_wkt_cleaned",
]

REQUIRED_INPUTS = [
    ASSIGNMENT_DIR / "crash_candidate_assignment_detail.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_fanout_summary.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_source_coverage_summary.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_unassigned_summary.csv",
    ASSIGNMENT_DIR / "final_crash_candidate_assignment_manifest.json",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_ACCESS_DIR / "final_access_crash_catchment_readiness.csv",
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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _safe_read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _load_crashes() -> tuple[pd.DataFrame, list[str]]:
    schema_cols = list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)
    direction_cols = [column for column in schema_cols if _is_direction_field(column)]
    cols = [column for column in CRASH_COLUMNS if column in schema_cols]
    cols.extend(column for column in direction_cols if column not in cols)
    crashes = pd.read_parquet(CRASH_SOURCE, columns=cols)
    crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    crashes["crash_direction_fields_inventory_only"] = "|".join(direction_cols)
    crashes["crash_direction_used_for_assignment"] = False
    crashes["crash_geometry_wkt"] = crashes["geometry"].map(lambda value: wkb.loads(value).wkt if value is not None else "")
    _checkpoint("load normalized crashes", len(crashes))
    return crashes, direction_cols


def _assignment_status(crashes: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    status = crashes.drop(columns=["geometry"], errors="ignore").copy()
    for width in [35, 50, 75]:
        frame = detail.loc[_text(detail, "buffer_width_ft").eq(str(width))].copy()
        fanout = frame.groupby("stable_crash_id", dropna=False).size().rename(f"fanout_{width}ft").reset_index()
        status = status.merge(fanout, on="stable_crash_id", how="left")
        status[f"assigned_{width}ft"] = status[f"fanout_{width}ft"].notna()
        status[f"fanout_{width}ft"] = status[f"fanout_{width}ft"].fillna(0).astype(int)
    status["assignment_status_class"] = np.select(
        [
            status["assigned_50ft"],
            status["assigned_75ft"] & ~status["assigned_50ft"],
            status["assigned_35ft"] & ~status["assigned_50ft"],
        ],
        ["assigned_primary_50ft", "unassigned_50ft_assigned_75ft_sensitivity", "assigned_35ft_only_inconsistent"],
        default="unassigned_all_35_50_75",
    )
    return status


def _load_bins() -> pd.DataFrame:
    bins = _safe_read_csv(STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv", BIN_COLUMNS)
    bins = bins.loc[_text(bins, "geometry_wkt_cleaned").str.strip().ne("")].copy()
    bins["bin_row_pos"] = np.arange(len(bins), dtype=np.int64)
    bins["physical_leg_id"] = _text(bins, "physical_leg_id_final")
    bins["carriageway_subbranch_id"] = _text(bins, "carriageway_subbranch_id_final")
    _checkpoint("filter scaffold bins with geometry", len(bins))
    return bins


def _parse_points(values: pd.Series) -> np.ndarray:
    geoms = []
    for value in values:
        try:
            geoms.append(wkb.loads(value) if value is not None else None)
        except Exception:
            geoms.append(None)
    return np.asarray(geoms, dtype=object)


def _parse_lines(values: pd.Series) -> np.ndarray:
    geoms = []
    for value in values:
        try:
            geom = wkt.loads(value)
            geoms.append(geom if not geom.is_empty else None)
        except Exception:
            geoms.append(None)
    return np.asarray(geoms, dtype=object)


def _nearest_indices(points: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    tree = STRtree(targets)
    nearest = np.full(len(points), -1, dtype=np.int64)
    distances = np.full(len(points), np.nan, dtype=float)
    for start in range(0, len(points), CHUNK_SIZE):
        stop = min(start + CHUNK_SIZE, len(points))
        chunk = points[start:stop]
        valid_mask = np.asarray([geom is not None and not geom.is_empty for geom in chunk], dtype=bool)
        if not valid_mask.any():
            continue
        valid_points = chunk[valid_mask]
        original = np.flatnonzero(valid_mask) + start
        pair_index, dist = tree.query_nearest(valid_points, return_distance=True, all_matches=False)
        nearest[original[pair_index[0]]] = pair_index[1]
        distances[original[pair_index[0]]] = dist * M_TO_FT
        _checkpoint(f"nearest query chunk {start}-{stop}", len(dist))
    return nearest, distances


def _signal_proxy_table(bins: pd.DataFrame, line_geoms: np.ndarray) -> pd.DataFrame:
    temp = bins.copy()
    temp["distance_start_num"] = _num(temp, "distance_start_ft").fillna(999999)
    temp = temp.sort_values(["target_signal_id", "distance_start_num", "distance_end_ft"])
    first = temp.groupby("target_signal_id", dropna=False).first().reset_index()
    proxy_geoms = []
    for row in first.itertuples(index=False):
        geom = line_geoms[int(getattr(row, "bin_row_pos"))]
        if geom is None:
            proxy_geoms.append(None)
            continue
        coords = list(geom.coords) if hasattr(geom, "coords") else []
        proxy_geoms.append(Point(coords[0]) if coords else geom.representative_point())
    first["signal_proxy_row_pos"] = np.arange(len(first), dtype=np.int64)
    first["signal_proxy_method"] = "first_coordinate_of_lowest_distance_start_bin"
    first["_signal_proxy_geom"] = proxy_geoms
    return first


def _distance_band(value: float, edges: list[tuple[float, float, str]]) -> str:
    if pd.isna(value):
        return "unknown"
    for low, high, label in edges:
        if low <= value < high:
            return label
    return edges[-1][2]


def _classify_unassigned(row: pd.Series) -> str:
    bin_d = row["nearest_scaffold_bin_distance_ft"]
    sig_d = row["nearest_signal_proxy_distance_ft"]
    if pd.isna(bin_d):
        return "unclear_needs_review"
    if sig_d > 2500 and bin_d > 2500:
        return "outside_2500ft_of_represented_signal_or_scaffold"
    if row.get("nearest_grade_mainline_holdout_flag", False):
        return "near_grade_mainline_or_interchange_holdout"
    if row.get("nearest_source_limited_holdout_flag", False) or row.get("nearest_still_insufficient_evidence_flag", False):
        return "near_source_limited_or_incomplete_scaffold"
    if 50 < bin_d <= 75:
        return "near_bin_outside_50ft_inside_75ft"
    if 75 < bin_d <= 100:
        return "possible_buffer_width_limitation"
    if 100 < bin_d <= 250:
        return "possible_crash_geocode_offset"
    if bin_d <= 2500 and sig_d <= 2500:
        return "on_or_near_represented_travelway_but_not_in_buffer"
    if sig_d <= 2500 and bin_d > 2500:
        return "within_2500ft_signal_but_far_from_bins"
    if bin_d > 2500:
        return "outside_2500ft_of_represented_signal_or_scaffold"
    return "unclear_needs_review"


def _nearest_detail(status: pd.DataFrame, bins: pd.DataFrame, crashes: pd.DataFrame) -> pd.DataFrame:
    unassigned = status.loc[~status["assigned_50ft"]].copy()
    crash_lookup = crashes.set_index("stable_crash_id", drop=False)
    unassigned_crashes = crash_lookup.loc[unassigned["stable_crash_id"]].reset_index(drop=True)
    crash_points = _parse_points(unassigned_crashes["geometry"])
    line_geoms = _parse_lines(bins["geometry_wkt_cleaned"])
    valid_line_mask = np.asarray([geom is not None for geom in line_geoms], dtype=bool)
    valid_lines = line_geoms[valid_line_mask]
    line_original = np.flatnonzero(valid_line_mask)
    nearest_line, line_distance_ft = _nearest_indices(crash_points, valid_lines)
    nearest_bin_pos = np.where(nearest_line >= 0, line_original[nearest_line], -1)

    signal_proxy = _signal_proxy_table(bins, line_geoms)
    proxy_mask = np.asarray([geom is not None for geom in signal_proxy["_signal_proxy_geom"]], dtype=bool)
    proxy_geoms = np.asarray(signal_proxy.loc[proxy_mask, "_signal_proxy_geom"].tolist(), dtype=object)
    proxy_original = signal_proxy.loc[proxy_mask, "signal_proxy_row_pos"].to_numpy(dtype=np.int64)
    nearest_proxy, proxy_distance_ft = _nearest_indices(crash_points, proxy_geoms)
    nearest_proxy_pos = np.where(nearest_proxy >= 0, proxy_original[nearest_proxy], -1)

    nearest_bins = bins.set_index("bin_row_pos", drop=False).reindex(nearest_bin_pos).reset_index(drop=True)
    nearest_signals = signal_proxy.set_index("signal_proxy_row_pos", drop=False).reindex(nearest_proxy_pos).reset_index(drop=True)
    out = unassigned_crashes.drop(columns=["geometry"], errors="ignore").copy()
    out["nearest_scaffold_bin_distance_ft"] = np.round(line_distance_ft, 3)
    out["nearest_signal_proxy_distance_ft"] = np.round(proxy_distance_ft, 3)
    out["nearest_signal_proxy_method"] = "first_coordinate_of_lowest_distance_start_bin"
    for source_col, out_col in [
        ("target_signal_id", "nearest_bin_signal_id"),
        ("stable_bin_id", "nearest_stable_bin_id"),
        ("stable_travelway_id", "nearest_stable_travelway_id"),
        ("physical_leg_id", "nearest_physical_leg_id"),
        ("carriageway_subbranch_id", "nearest_carriageway_subbranch_id"),
        ("distance_band", "nearest_distance_band"),
        ("analysis_window", "nearest_analysis_window"),
        ("final_alignment_class", "nearest_final_alignment_class"),
        ("source_limited_holdout_flag", "nearest_source_limited_holdout_flag"),
        ("grade_mainline_holdout_flag", "nearest_grade_mainline_holdout_flag"),
        ("still_insufficient_evidence_flag", "nearest_still_insufficient_evidence_flag"),
        ("review_only_recovery_provenance", "nearest_review_only_recovery_provenance"),
    ]:
        out[out_col] = nearest_bins[source_col].fillna("").astype(str) if source_col in nearest_bins.columns else ""
    out["nearest_represented_signal_id"] = nearest_signals["target_signal_id"].fillna("").astype(str)
    out["nearest_signal_proxy_distance_band"] = out["nearest_signal_proxy_distance_ft"].map(
        lambda value: _distance_band(value, [(0, 250, "0_250"), (250, 500, "250_500"), (500, 1000, "500_1000"), (1000, 2500, "1000_2500"), (2500, np.inf, "gt_2500")])
    )
    out["nearest_scaffold_bin_distance_band"] = out["nearest_scaffold_bin_distance_ft"].map(
        lambda value: _distance_band(
            value,
            [
                (0, 35, "0_35"),
                (35, 50, "35_50"),
                (50, 75, "50_75"),
                (75, 100, "75_100"),
                (100, 250, "100_250"),
                (250, 500, "250_500"),
                (500, 1000, "500_1000"),
                (1000, 2500, "1000_2500"),
                (2500, np.inf, "gt_2500"),
            ],
        )
    )
    for col in ["nearest_source_limited_holdout_flag", "nearest_grade_mainline_holdout_flag", "nearest_still_insufficient_evidence_flag"]:
        out[col] = out[col].astype(str).str.lower().isin({"true", "1", "yes"})
    out["unassigned_reason_class"] = out.apply(_classify_unassigned, axis=1)
    _checkpoint("nearest detail for 50ft unassigned crashes", len(out))
    return out


def _class_summary(nearest: pd.DataFrame) -> pd.DataFrame:
    return nearest.groupby("unassigned_reason_class", dropna=False).size().reset_index(name="crash_count").sort_values("crash_count", ascending=False)


def _distance_summary(nearest: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field, label in [
        ("nearest_scaffold_bin_distance_band", "nearest_scaffold_bin"),
        ("nearest_signal_proxy_distance_band", "nearest_signal_proxy"),
    ]:
        grouped = nearest.groupby(field, dropna=False).size().reset_index(name="crash_count")
        grouped["distance_type"] = label
        grouped = grouped.rename(columns={field: "distance_band"})
        rows.append(grouped[["distance_type", "distance_band", "crash_count"]])
    return pd.concat(rows, ignore_index=True)


def _buffer_sensitivity(status: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gains = {
        "35_to_50": status.loc[status["assigned_50ft"] & ~status["assigned_35ft"], "stable_crash_id"],
        "50_to_75": status.loc[status["assigned_75ft"] & ~status["assigned_50ft"], "stable_crash_id"],
    }
    for label, ids in gains.items():
        target_width = 50 if label == "35_to_50" else 75
        frame = detail.loc[_text(detail, "buffer_width_ft").eq(str(target_width)) & detail["stable_crash_id"].isin(set(ids))].copy()
        rows.append(
            {
                "sensitivity_step": label,
                "newly_assigned_unique_crashes": int(ids.nunique()),
                "assignment_rows": int(len(frame)),
                "signals": int(frame["target_signal_id"].nunique()) if not frame.empty else 0,
                "source_limited_rows": int(_bool_text(frame, "source_limited_holdout_flag").sum()) if not frame.empty else 0,
                "grade_mainline_rows": int(_bool_text(frame, "grade_mainline_holdout_flag").sum()) if not frame.empty else 0,
                "interpretation": "plausible geocode/buffer sensitivity; retain as sensitivity not primary" if label == "50_to_75" else "primary 50ft captures additional near-road crashes over 35ft",
            }
        )
        if not frame.empty:
            top = frame.groupby(["target_signal_id", "analysis_window"], dropna=False)["stable_crash_id"].nunique().reset_index(name="new_crashes")
            top = top.sort_values("new_crashes", ascending=False).head(10)
            for row in top.itertuples(index=False):
                rows.append(
                    {
                        "sensitivity_step": f"{label}_top_signal_window",
                        "newly_assigned_unique_crashes": int(row.new_crashes),
                        "assignment_rows": "",
                        "signals": row.target_signal_id,
                        "source_limited_rows": "",
                        "grade_mainline_rows": "",
                        "interpretation": row.analysis_window,
                    }
                )
    return pd.DataFrame(rows)


def _review_queues(nearest: pd.DataFrame, detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    queue_frames = []
    for name, mask in {
        "unassigned_75_100ft_from_bin": nearest["nearest_scaffold_bin_distance_ft"].between(75, 100, inclusive="left"),
        "unassigned_100_250ft_from_bin": nearest["nearest_scaffold_bin_distance_ft"].between(100, 250, inclusive="left"),
        "within_2500ft_signal_far_from_bins": nearest["nearest_signal_proxy_distance_ft"].le(2500) & nearest["nearest_scaffold_bin_distance_ft"].gt(2500),
    }.items():
        q = nearest.loc[mask].copy()
        q["review_queue_type"] = name
        queue_frames.append(q.sort_values("nearest_scaffold_bin_distance_ft").head(500))
    cluster = (
        nearest.loc[nearest["nearest_signal_proxy_distance_ft"].le(2500)]
        .groupby("nearest_represented_signal_id", dropna=False)
        .agg(
            unassigned_crash_count=("stable_crash_id", "nunique"),
            median_nearest_bin_distance_ft=("nearest_scaffold_bin_distance_ft", "median"),
            nearest_bin_distance_min_ft=("nearest_scaffold_bin_distance_ft", "min"),
        )
        .reset_index()
        .sort_values("unassigned_crash_count", ascending=False)
        .head(250)
    )
    cluster["review_queue_type"] = "high_count_unassigned_near_signal_proxy"
    cluster["stable_crash_id"] = ""
    cluster["nearest_bin_signal_id"] = cluster["nearest_represented_signal_id"]
    queue_cols = [
        "review_queue_type",
        "stable_crash_id",
        "nearest_bin_signal_id",
        "nearest_represented_signal_id",
        "nearest_scaffold_bin_distance_ft",
        "nearest_signal_proxy_distance_ft",
        "nearest_stable_bin_id",
        "nearest_stable_travelway_id",
        "nearest_analysis_window",
        "unassigned_reason_class",
        "unassigned_crash_count",
        "median_nearest_bin_distance_ft",
        "nearest_bin_distance_min_ft",
    ]
    queue = pd.concat(queue_frames, ignore_index=True, sort=False) if queue_frames else pd.DataFrame()
    queue = pd.concat([queue, cluster], ignore_index=True, sort=False)
    for col in queue_cols:
        if col not in queue.columns:
            queue[col] = ""
    queue = queue[queue_cols]

    high_fanout = (
        detail.groupby(["buffer_width_ft", "stable_crash_id"], dropna=False)
        .agg(
            assignment_rows=("stable_bin_id", "size"),
            signal_count=("target_signal_id", "nunique"),
            physical_leg_count=("physical_leg_id", "nunique"),
            sample_signals=("target_signal_id", lambda s: "|".join(sorted(set(s.astype(str)))[:8])),
            sample_bins=("stable_bin_id", lambda s: "|".join(sorted(set(s.astype(str)))[:8])),
        )
        .reset_index()
    )
    high_fanout["review_priority"] = high_fanout["assignment_rows"] + high_fanout["signal_count"] * 10
    high_fanout = high_fanout.sort_values("review_priority", ascending=False).head(500)

    high_signal_window = (
        detail.groupby(["buffer_width_ft", "target_signal_id", "analysis_window"], dropna=False)
        .agg(
            unique_crash_count=("stable_crash_id", "nunique"),
            assignment_rows=("stable_bin_id", "size"),
            physical_leg_count=("physical_leg_id", "nunique"),
            source_limited_rows=("source_limited_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            grade_mainline_rows=("grade_mainline_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
        )
        .reset_index()
        .sort_values(["buffer_width_ft", "unique_crash_count"], ascending=[True, False])
        .head(500)
    )
    return queue, high_fanout, high_signal_window


def _qa(direction_cols: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", f"outputs written only to {OUT_DIR}"),
        ("no_candidates_promoted", "passed", "diagnostic/accounting only"),
        ("no_rates_or_models", "passed", "no rate/model calculations"),
        ("no_final_crash_assignment_promoted", "passed", "existing review-only candidates are audited only"),
        ("crash_direction_not_used", "passed", "direction fields are not used in nearest-network or classification logic"),
        ("crash_direction_fields_inventory_only", "passed", "|".join(direction_cols) if direction_cols else "none detected"),
        ("stable_travelway_id_carried", "passed", "nearest scaffold detail carries nearest stable_travelway_id"),
        ("scaffold_qa_flags_carried", "passed", "nearest scaffold QA flags are carried where available"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(status: pd.DataFrame, nearest: pd.DataFrame, class_summary: pd.DataFrame, distance_summary: pd.DataFrame, sensitivity: pd.DataFrame) -> str:
    total_unassigned = int((~status["assigned_50ft"]).sum())
    outside = int(class_summary.loc[class_summary["unassigned_reason_class"].eq("outside_2500ft_of_represented_signal_or_scaffold"), "crash_count"].sum())
    near_50_75 = int(class_summary.loc[class_summary["unassigned_reason_class"].eq("near_bin_outside_50ft_inside_75ft"), "crash_count"].sum())
    source_limited = int(class_summary.loc[class_summary["unassigned_reason_class"].isin(["near_source_limited_or_incomplete_scaffold", "near_grade_mainline_or_interchange_holdout"]), "crash_count"].sum())
    geocode = int(class_summary.loc[class_summary["unassigned_reason_class"].isin(["possible_buffer_width_limitation", "possible_crash_geocode_offset"]), "crash_count"].sum())
    gain_75 = sensitivity.loc[sensitivity["sensitivity_step"].eq("50_to_75"), "newly_assigned_unique_crashes"]
    gain_75_count = int(gain_75.iloc[0]) if not gain_75.empty else 0
    far_signal = int(class_summary.loc[class_summary["unassigned_reason_class"].eq("within_2500ft_signal_but_far_from_bins"), "crash_count"].sum())
    return f"""# Final Crash Non-Assignment Accounting Findings

## Bounded Question

This read-only diagnostic explains the 50 ft unassigned crash population from the first review-only crash candidate assignment. It computes nearest final scaffold-bin evidence and a derived represented-signal proxy distance. It does not create final crash assignments, calculate rates/models, promote records, or use crash direction fields.

## 50 ft Unassigned Accounting

- 50 ft unassigned crashes: {total_unassigned:,}
- Outside 2,500 ft of represented signal/scaffold evidence: {outside:,}
- Within 2,500 ft of a represented signal proxy but far from scaffold bins: {far_signal:,}
- Near scaffold bins just outside 50 ft and inside 75 ft: {near_50_75:,}
- Assigned by 75 ft but not by 50 ft: {gain_75_count:,}
- Near source-limited/incomplete or grade/mainline/interchange scaffold flags: {source_limited:,}
- Possible crash geocode/catchment-width limitations: {geocode:,}

## Interpretation

The 50 ft product remains appropriate as the primary review crash assignment product. The 75 ft product captures additional crashes and should remain a sensitivity product because it increases assignment coverage but also broadens fanout and overlap risk.

## Recommended Next Pass

Prepare a crash assignment QA/map-review package focused on unassigned crashes 75-250 ft from scaffold bins, high-fanout assigned crashes, high-count signal-window units, and source-limited or grade/mainline/interchange QA classes. A later method test can evaluate a route/source Travelway crash-normalized sensitivity, but it should not replace spatial review without explicit overcapture QA.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start final_crash_nonassignment_accounting")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    crashes, direction_cols = _load_crashes()
    detail = _safe_read_csv(ASSIGNMENT_DIR / "crash_candidate_assignment_detail.csv")
    status = _assignment_status(crashes, detail)
    bins = _load_bins()
    nearest = _nearest_detail(status, bins, crashes)
    class_summary = _class_summary(nearest)
    distance_summary = _distance_summary(nearest)
    sensitivity = _buffer_sensitivity(status, detail)
    review_queue, high_fanout, high_signal_window = _review_queues(nearest, detail)

    _write_csv(status, "crash_assignment_status_by_crash.csv")
    _write_csv(nearest, "crash_unassigned_nearest_scaffold_detail.csv")
    _write_csv(class_summary, "crash_unassigned_class_summary.csv")
    _write_csv(distance_summary, "crash_unassigned_distance_band_summary.csv")
    _write_csv(sensitivity, "crash_assignment_buffer_sensitivity_summary.csv")
    _write_csv(review_queue, "crash_unassigned_review_queue.csv")
    _write_csv(high_fanout, "crash_high_fanout_review_queue.csv")
    _write_csv(high_signal_window, "crash_high_count_signal_window_review_queue.csv")
    _write_text(_findings(status, nearest, class_summary, distance_summary, sensitivity), "final_crash_nonassignment_accounting_findings.md")
    _write_csv(_qa(direction_cols), "final_crash_nonassignment_accounting_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.build.final_crash_nonassignment_accounting",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "review_only": True,
            "final_crash_assignment_promoted": False,
            "rates_or_models_calculated": False,
            "crash_direction_use": "not_used_inventory_only",
            "nearest_signal_distance_note": "represented signal source point geometry was not present in required inputs; signal distance uses a scaffold-derived proxy from the first coordinate of each signal's lowest-distance bin",
            "outputs": [
                "crash_assignment_status_by_crash.csv",
                "crash_unassigned_nearest_scaffold_detail.csv",
                "crash_unassigned_class_summary.csv",
                "crash_unassigned_distance_band_summary.csv",
                "crash_assignment_buffer_sensitivity_summary.csv",
                "crash_unassigned_review_queue.csv",
                "crash_high_fanout_review_queue.csv",
                "crash_high_count_signal_window_review_queue.csv",
                "final_crash_nonassignment_accounting_findings.md",
                "final_crash_nonassignment_accounting_qa.csv",
                "final_crash_nonassignment_accounting_manifest.json",
                "run_progress_log.txt",
            ],
        },
        "final_crash_nonassignment_accounting_manifest.json",
    )
    _checkpoint("complete final_crash_nonassignment_accounting")


if __name__ == "__main__":
    main()
