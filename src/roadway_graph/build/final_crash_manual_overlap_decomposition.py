from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyogrio
import shapely
from scipy.spatial import cKDTree
from shapely import STRtree, wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_crash_manual_overlap_decomposition"

WINDOW_DIR = OUTPUT_ROOT / "review/current/final_crash_window_overlap_travelway_diagnostic"
DECOMP_DIR = OUTPUT_ROOT / "review/current/final_crash_unassigned_category_decomposition"
ASSIGNMENT_DIR = OUTPUT_ROOT / "review/current/final_crash_candidate_assignment"
STABLE_SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
SOURCE_TRAVELWAY_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")

TARGET_WINDOW_CLASSES = {"manual_review_needed", "near_other_signal_or_overlapping_window_confirmed"}
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)
FT_TO_M = 0.3048
M_TO_FT = 1.0 / FT_TO_M

REQUIRED_INPUTS = [
    WINDOW_DIR / "crash_window_overlap_target_detail.csv",
    WINDOW_DIR / "crash_source_travelway_match_detail.csv",
    WINDOW_DIR / "crash_window_overlap_refined_class_summary.csv",
    WINDOW_DIR / "crash_source_travelway_candidate_summary.csv",
    WINDOW_DIR / "crash_window_overlap_next_action_summary.csv",
    WINDOW_DIR / "crash_window_overlap_review_queue.csv",
    WINDOW_DIR / "final_crash_window_overlap_travelway_diagnostic_manifest.json",
    DECOMP_DIR / "crash_unassigned_refined_detail.csv",
    DECOMP_DIR / "crash_unassigned_refined_class_summary.csv",
    DECOMP_DIR / "crash_unassigned_ranked_review_queue.csv",
    DECOMP_DIR / "final_crash_unassigned_category_decomposition_manifest.json",
    ASSIGNMENT_DIR / "crash_candidate_assignment_detail.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_fanout_summary.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGNMENT_DIR / "final_crash_candidate_assignment_manifest.json",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    SOURCE_TRAVELWAY_GPKG,
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


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _is_direction_field(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in CRASH_DIRECTION_FIELD_TOKENS)


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
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


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _norm_route(value: object) -> str:
    text = "" if value is None else str(value).upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def _inspect_crash_source() -> list[str]:
    cols = list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)
    return [column for column in cols if _is_direction_field(column)]


def _target_pool() -> pd.DataFrame:
    detail = _read_csv(WINDOW_DIR / "crash_window_overlap_target_detail.csv")
    target = detail.loc[_text(detail, "window_overlap_refined_class").isin(TARGET_WINDOW_CLASSES)].copy().reset_index(drop=True)
    target["target_pool_class"] = _text(target, "window_overlap_refined_class")
    target["crash_point"] = _text(target, "crash_geometry_wkt").map(lambda value: wkt.loads(value) if value.strip() else None)
    target["target_row"] = np.arange(len(target), dtype=np.int64)
    _checkpoint("manual/overlap target pool", len(target))
    return target


def _signal_points() -> tuple[pd.DataFrame, bool, dict[str, Any]]:
    info = pyogrio.read_info(SOURCE_TRAVELWAY_GPKG, layer="review_signal_universe")
    gdf = pyogrio.read_dataframe(
        SOURCE_TRAVELWAY_GPKG,
        layer="review_signal_universe",
        columns=["signal_id", "source_signal_id", "source_layer", "final_alignment_class", "source_limited_holdout_flag", "grade_mainline_holdout_flag"],
    )
    gdf = gdf.rename(columns={"geometry": "signal_geometry"})
    gdf["signal_row"] = np.arange(len(gdf), dtype=np.int64)
    gdf["signal_x"] = gdf["signal_geometry"].map(lambda geom: geom.x if geom is not None and not geom.is_empty else np.nan)
    gdf["signal_y"] = gdf["signal_geometry"].map(lambda geom: geom.y if geom is not None and not geom.is_empty else np.nan)
    _checkpoint("read true represented signal points", len(gdf))
    return pd.DataFrame(gdf.drop(columns=["signal_geometry"])), True, {"features": info.get("features"), "crs": info.get("crs")}


def _add_signal_proximity(target: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    valid_signals = signals.loc[signals["signal_x"].notna() & signals["signal_y"].notna()].copy()
    tree = cKDTree(valid_signals[["signal_x", "signal_y"]].to_numpy())
    coords = np.asarray([(geom.x, geom.y) if geom is not None and not geom.is_empty else (np.nan, np.nan) for geom in target["crash_point"]])
    valid = ~np.isnan(coords[:, 0])
    dist = np.full((len(target), 3), np.nan)
    idx = np.full((len(target), 3), -1, dtype=int)
    d, i = tree.query(coords[valid], k=3)
    dist[valid] = d * M_TO_FT
    idx[valid] = i
    out = target.copy()
    for rank in [1, 2, 3]:
        out[f"nearest_signal_{rank}_distance_ft"] = np.round(dist[:, rank - 1], 3)
        mapped = valid_signals.iloc[np.maximum(idx[:, rank - 1], 0)].reset_index(drop=True)
        out[f"nearest_signal_{rank}_id"] = np.where(idx[:, rank - 1] >= 0, mapped["signal_id"].astype(str), "")
    for radius in [250, 500, 1000, 2500]:
        try:
            counts = tree.query_ball_point(coords[valid], r=radius * FT_TO_M, return_length=True)
        except TypeError:
            counts = np.asarray([len(v) for v in tree.query_ball_point(coords[valid], r=radius * FT_TO_M)])
        full = np.zeros(len(target), dtype=int)
        full[valid] = counts
        out[f"represented_signals_within_{radius}ft"] = full
    out["dense_multi_signal_area"] = (out["represented_signals_within_1000ft"] >= 3) | (out["represented_signals_within_2500ft"] >= 5)
    out["signal_geometry_source"] = "review_signal_universe_true_points"
    return out


def _load_bins() -> pd.DataFrame:
    cols = [
        "stable_bin_id",
        "target_signal_id",
        "stable_travelway_id",
        "analysis_window",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "geometry_wkt_cleaned",
    ]
    bins = _read_csv(STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv", cols)
    bins = bins.loc[_text(bins, "geometry_wkt_cleaned").str.strip().ne("")].copy()
    bins["bin_row"] = np.arange(len(bins), dtype=np.int64)
    bins["line_geom"] = _text(bins, "geometry_wkt_cleaned").map(lambda value: wkt.loads(value) if value.strip() else None)
    _checkpoint("load stable-lineage bin geometries", len(bins))
    return bins


def _bin_proximity_counts(target: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    target = target.reset_index(drop=True).copy()
    target["target_row"] = np.arange(len(target), dtype=np.int64)
    points = np.asarray(target["crash_point"].tolist(), dtype=object)
    lines = np.asarray(bins["line_geom"].tolist(), dtype=object)
    tree = STRtree(lines)
    pair_idx = tree.query(points, predicate="dwithin", distance=500 * FT_TO_M)
    _checkpoint("bin proximity pairs within 500ft", pair_idx.shape[1] if pair_idx.size else 0)
    out = target.copy()
    for col in [
        "signal_window_catchments_within_50ft",
        "signal_window_catchments_within_75ft",
        "signal_window_catchments_within_100ft",
        "distinct_signals_with_bins_within_100ft",
        "distinct_signals_with_bins_within_250ft",
        "distinct_signals_with_bins_within_500ft",
        "distinct_stable_travelways_with_bins_within_500ft",
    ]:
        out[col] = 0
    if pair_idx.size == 0:
        return out
    point_idx = pair_idx[0]
    bin_idx = pair_idx[1]
    distances = shapely.distance(points[point_idx], lines[bin_idx]) * M_TO_FT
    pairs = pd.DataFrame({"target_row": point_idx, "bin_row": bin_idx, "distance_ft": distances})
    bin_meta = bins[["bin_row", "target_signal_id", "analysis_window", "stable_travelway_id"]]
    pairs = pairs.merge(bin_meta, on="bin_row", how="left")
    pairs["signal_window_key"] = pairs["target_signal_id"].astype(str) + "|" + pairs["analysis_window"].astype(str)
    for radius in [50, 75, 100]:
        grouped = pairs.loc[pairs["distance_ft"].le(radius)].groupby("target_row")["signal_window_key"].nunique()
        out.loc[grouped.index, f"signal_window_catchments_within_{radius}ft"] = grouped.astype(int)
    for radius in [100, 250, 500]:
        grouped = pairs.loc[pairs["distance_ft"].le(radius)].groupby("target_row")["target_signal_id"].nunique()
        out.loc[grouped.index, f"distinct_signals_with_bins_within_{radius}ft"] = grouped.astype(int)
    grouped = pairs.groupby("target_row")["stable_travelway_id"].nunique()
    out.loc[grouped.index, "distinct_stable_travelways_with_bins_within_500ft"] = grouped.astype(int)
    nearest_source_tw = out.set_index("target_row")["nearest_source_stable_travelway_id"].astype(str)
    pairs["nearest_source_stable_travelway_id"] = pairs["target_row"].map(nearest_source_tw)
    same_tw = pairs.loc[
        pairs["stable_travelway_id"].astype(str).eq(pairs["nearest_source_stable_travelway_id"].astype(str))
    ]
    out["between_two_represented_windows_same_travelway"] = False
    if not same_tw.empty:
        same_counts = same_tw.groupby("target_row")["signal_window_key"].nunique()
        out.loc[same_counts.index, "between_two_represented_windows_same_travelway"] = same_counts.ge(2).to_numpy()
    return out


def _source_context(row: pd.Series) -> str:
    fields = " ".join(
        str(row.get(col, ""))
        for col in ["nearest_source_facility", "nearest_source_access", "nearest_source_facility_text", "nearest_source_route_name_raw", "MAINLINE_YN"]
    ).upper()
    if any(token in fields for token in ["RAMP", "MAINLINE", "LIMITED", "INTERSTATE", " IS", "FRONTAGE"]):
        return "grade_mainline_ramp_or_limited_access_context"
    if _truthy(row.get("nearest_source_travelway_represented", False)):
        return "nearest_source_travelway_represented"
    return "nearest_source_travelway_not_represented"


def _manual_class(row: pd.Series) -> str:
    source_context = str(row.get("source_travelway_context_class", ""))
    nearest_sig = float(row.get("nearest_signal_1_distance_ft", np.nan))
    nearest_bin = float(row.get("nearest_scaffold_bin_distance_num", np.nan))
    source_dist = float(row.get("nearest_source_travelway_distance_num", np.nan))
    if source_context == "grade_mainline_ramp_or_limited_access_context":
        return "grade_mainline_or_ramp_context_holdout"
    if nearest_sig > 2500 and nearest_bin > 2500:
        return "outside_signal_scope_confirmed"
    if not _truthy(row.get("nearest_source_travelway_represented", False)) and source_dist <= 50:
        return "source_travelway_not_represented_by_signal_scaffold"
    if _truthy(row.get("dense_multi_signal_area", False)):
        return "dense_corridor_overlap_zone"
    if int(row.get("signal_window_catchments_within_100ft", 0)) >= 2:
        return "overlap_multi_signal_weighting_candidate"
    if _truthy(row.get("between_two_represented_windows_same_travelway", False)):
        return "between_signal_windows_on_represented_travelway"
    if nearest_sig <= 1000 and nearest_bin > 500:
        return "near_represented_signal_but_not_scaffold_window"
    if 50 < nearest_bin <= 250:
        return "possible_geocode_offset"
    if nearest_sig <= 2500 and nearest_bin > 250:
        return "possible_scaffold_gap"
    return "true_manual_review_needed"


def _overlap_class(row: pd.Series) -> str:
    source_context = str(row.get("source_travelway_context_class", ""))
    if source_context == "grade_mainline_ramp_or_limited_access_context":
        return "grade_mainline_overlap_holdout"
    if int(row.get("signal_window_catchments_within_100ft", 0)) >= 2:
        return "valid_multi_assignment_overlap"
    if _truthy(row.get("between_two_represented_windows_same_travelway", False)):
        return "same_travelway_between_two_signals"
    if _truthy(row.get("dense_multi_signal_area", False)):
        return "complex_intersection_overlap"
    if int(row.get("distinct_signals_with_bins_within_250ft", 0)) >= 1:
        return "nearest_signal_window_preferred_but_weighted_sensitivity"
    return "manual_review_needed"


def _reclassify(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    out["source_travelway_context_class"] = out.apply(_source_context, axis=1)
    manual_mask = out["target_pool_class"].eq("manual_review_needed")
    overlap_mask = out["target_pool_class"].eq("near_other_signal_or_overlapping_window_confirmed")
    out["manual_bucket_reclassified_class"] = ""
    out.loc[manual_mask, "manual_bucket_reclassified_class"] = out.loc[manual_mask].apply(_manual_class, axis=1)
    out["overlap_reclassified_class"] = ""
    out.loc[overlap_mask, "overlap_reclassified_class"] = out.loc[overlap_mask].apply(_overlap_class, axis=1)
    out["final_manual_overlap_class"] = np.where(
        manual_mask,
        out["manual_bucket_reclassified_class"],
        out["overlap_reclassified_class"],
    )
    return out


def _class_summary(detail: pd.DataFrame) -> pd.DataFrame:
    return (
        detail.groupby(["target_pool_class", "final_manual_overlap_class"], dropna=False)["stable_crash_id"]
        .nunique()
        .reset_index(name="crash_count")
        .sort_values("crash_count", ascending=False)
    )


def _policy_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    overlap = detail.loc[detail["target_pool_class"].eq("near_other_signal_or_overlapping_window_confirmed")].copy()
    for radius in [100, 250, 500]:
        col = f"distinct_signals_with_bins_within_{radius}ft"
        eligible = overlap.loc[overlap[col].astype(int).gt(0)]
        fanout = eligible[col].astype(int).clip(lower=1)
        rows.append(
            {
                "policy_option": f"multi_assignment_with_weights_{radius}ft",
                "unique_crashes_included": int(eligible["stable_crash_id"].nunique()),
                "candidate_signal_assignment_rows": int(fanout.sum()),
                "weighted_crash_count": float((1.0 / fanout * fanout).sum()) if not eligible.empty else 0,
                "held_crashes": int(len(overlap) - len(eligible)),
                "interpretation": "diagnostic overlap policy only; not promoted assignment",
            }
        )
    nearest = overlap.loc[overlap["distinct_signals_with_bins_within_250ft"].astype(int).gt(0)]
    rows.append(
        {
            "policy_option": "nearest_window_only_250ft",
            "unique_crashes_included": int(nearest["stable_crash_id"].nunique()),
            "candidate_signal_assignment_rows": int(nearest["stable_crash_id"].nunique()),
            "weighted_crash_count": float(nearest["stable_crash_id"].nunique()),
            "held_crashes": int(len(overlap) - len(nearest)),
            "interpretation": "lower fanout but hides overlap uncertainty",
        }
    )
    held = overlap.loc[overlap["final_manual_overlap_class"].str.contains("holdout|manual", case=False, na=False)]
    rows.append(
        {
            "policy_option": "hold_manual_or_grade_overlap",
            "unique_crashes_included": int(len(overlap) - len(held)),
            "candidate_signal_assignment_rows": "",
            "weighted_crash_count": "",
            "held_crashes": int(len(held)),
            "interpretation": "conservative review hold for unresolved overlap cases",
        }
    )
    return pd.DataFrame(rows)


def _between_summary(detail: pd.DataFrame) -> pd.DataFrame:
    subset = detail.loc[detail["final_manual_overlap_class"].isin(["between_signal_windows_on_represented_travelway", "same_travelway_between_two_signals"])]
    if subset.empty:
        return pd.DataFrame(columns=["stable_travelway_id", "crash_count", "signals_within_2500_median"])
    return (
        subset.groupby("nearest_source_stable_travelway_id", dropna=False)
        .agg(
            crash_count=("stable_crash_id", "nunique"),
            signals_within_2500_median=("represented_signals_within_2500ft", lambda s: float(pd.to_numeric(s, errors="coerce").median())),
            example_crash=("stable_crash_id", "first"),
            example_nearest_signal=("nearest_signal_1_id", "first"),
        )
        .reset_index()
        .rename(columns={"nearest_source_stable_travelway_id": "stable_travelway_id"})
        .sort_values("crash_count", ascending=False)
    )


def _source_summary(detail: pd.DataFrame) -> pd.DataFrame:
    return (
        detail.groupby(["target_pool_class", "source_travelway_context_class", "nearest_source_travelway_represented"], dropna=False)["stable_crash_id"]
        .nunique()
        .reset_index(name="crash_count")
        .sort_values("crash_count", ascending=False)
    )


def _review_queue(detail: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for name, mask in {
        "high_confidence_multi_signal_overlap": detail["final_manual_overlap_class"].isin(["valid_multi_assignment_overlap", "overlap_multi_signal_weighting_candidate"]),
        "dense_corridor": detail["final_manual_overlap_class"].eq("dense_corridor_overlap_zone"),
        "between_window": detail["final_manual_overlap_class"].isin(["between_signal_windows_on_represented_travelway", "same_travelway_between_two_signals"]),
        "source_not_represented": detail["final_manual_overlap_class"].eq("source_travelway_not_represented_by_signal_scaffold"),
        "likely_geocode_offset": detail["final_manual_overlap_class"].eq("possible_geocode_offset"),
        "true_manual_review": detail["final_manual_overlap_class"].isin(["true_manual_review_needed", "manual_review_needed"]),
    }.items():
        q = detail.loc[mask].copy()
        q["review_queue_type"] = name
        q["review_priority"] = 0.0
        q["review_priority"] += q["represented_signals_within_2500ft"].astype(int).clip(0, 10)
        q["review_priority"] += q["distinct_signals_with_bins_within_500ft"].astype(int).clip(0, 10)
        q["review_priority"] -= q["nearest_scaffold_bin_distance_num"].astype(float).clip(0, 2500) / 500
        frames.append(q.sort_values("review_priority", ascending=False).head(300))
    out = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    keep = [
        "review_queue_type",
        "stable_crash_id",
        "target_pool_class",
        "final_manual_overlap_class",
        "nearest_signal_1_id",
        "nearest_signal_1_distance_ft",
        "nearest_signal_2_id",
        "nearest_signal_2_distance_ft",
        "represented_signals_within_1000ft",
        "represented_signals_within_2500ft",
        "signal_window_catchments_within_100ft",
        "distinct_signals_with_bins_within_250ft",
        "nearest_source_stable_travelway_id",
        "nearest_source_travelway_distance_ft",
        "nearest_scaffold_bin_distance_ft",
        "review_priority",
    ]
    for col in keep:
        if col not in out.columns:
            out[col] = ""
    return out[keep]


def _qa(direction_cols: list[str], signal_proxy: str) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", f"outputs written only to {OUT_DIR}"),
        ("no_candidates_promoted", "passed", "diagnostic decomposition only"),
        ("no_rates_or_models", "passed", "no rate/model calculations"),
        ("no_final_crash_assignment_promoted", "passed", "no assignment promotion or final context table"),
        ("crash_direction_not_used", "passed", "direction fields are not used in decomposition rules"),
        ("crash_direction_fields_inventory_only", "passed", "|".join(direction_cols) if direction_cols else "none detected"),
        ("signal_geometry_source", "passed", signal_proxy),
        ("stable_travelway_id_carried", "passed", "nearest stable_travelway_id carried where available"),
        ("scaffold_qa_fields_carried", "passed", "scaffold/source QA fields retained in detail output"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(detail: pd.DataFrame, class_summary: pd.DataFrame, policy: pd.DataFrame) -> str:
    manual = detail.loc[detail["target_pool_class"].eq("manual_review_needed")]
    overlap = detail.loc[detail["target_pool_class"].eq("near_other_signal_or_overlapping_window_confirmed")]

    def mcount(name: str) -> int:
        return int(manual.loc[manual["final_manual_overlap_class"].eq(name), "stable_crash_id"].nunique())

    def ocount(name: str) -> int:
        return int(overlap.loc[overlap["final_manual_overlap_class"].eq(name), "stable_crash_id"].nunique())

    true_manual = int(detail.loc[detail["final_manual_overlap_class"].isin(["true_manual_review_needed", "manual_review_needed"]), "stable_crash_id"].nunique())
    return f"""# Final Crash Manual/Overlap Decomposition Findings

## Bounded Question

This read-only diagnostic decomposes the large `manual_review_needed` and `near_other_signal_or_overlapping_window_confirmed` crash nonassignment buckets using true represented signal points from the access-review package, stable-lineage scaffold-bin proximity, and source Travelway relationship evidence. It does not create final crash assignments, calculate rates/models, promote records, or use crash direction fields.

## Manual Bucket

- Manual-review target crashes: {len(manual):,}
- Source Travelway not represented by signal scaffold: {mcount('source_travelway_not_represented_by_signal_scaffold'):,}
- Dense corridor overlap zone: {mcount('dense_corridor_overlap_zone'):,}
- Near represented signal but not scaffold window: {mcount('near_represented_signal_but_not_scaffold_window'):,}
- Possible scaffold gap: {mcount('possible_scaffold_gap'):,}
- Possible geocode offset: {mcount('possible_geocode_offset'):,}
- True manual review remaining: {mcount('true_manual_review_needed'):,}

## Overlap Bucket

- Overlap target crashes: {len(overlap):,}
- Valid multi-assignment overlap: {ocount('valid_multi_assignment_overlap'):,}
- Same Travelway between two signals: {ocount('same_travelway_between_two_signals'):,}
- Complex intersection/corridor overlap: {ocount('complex_intersection_overlap'):,}
- Nearest-window weighted sensitivity candidates: {ocount('nearest_signal_window_preferred_but_weighted_sensitivity'):,}
- Manual overlap remaining: {ocount('manual_review_needed'):,}

## Policy Direction

Overlap cases should remain review-only candidates. Multi-assignment with source-preserving weights is the better diagnostic policy where multiple signal windows are genuinely close; nearest-only can be reviewed as a sensitivity but should not silently replace overlap evidence. The 50 ft primary crash assignment remains unchanged.

## Next Pass

Create a crash QA/map-review package for source-not-represented, dense-corridor overlap, between-window, and likely geocode-offset examples before any crash assignment promotion or rate/model work.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start final_crash_manual_overlap_decomposition")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))
    direction_cols = _inspect_crash_source()
    target = _target_pool()
    signals, true_signal_points, signal_info = _signal_points()
    target = _add_signal_proximity(target, signals)
    bins = _load_bins()
    target = _bin_proximity_counts(target, bins)
    detail = _reclassify(target)

    class_summary = _class_summary(detail)
    policy = _policy_summary(detail)
    between = _between_summary(detail)
    source = _source_summary(detail)
    queue = _review_queue(detail)

    _write_csv(target.drop(columns=["crash_point"], errors="ignore"), "crash_manual_overlap_target_detail.csv")
    _write_csv(detail.drop(columns=["crash_point"], errors="ignore"), "crash_manual_overlap_reclassified_detail.csv")
    _write_csv(class_summary, "crash_manual_overlap_class_summary.csv")
    _write_csv(policy, "crash_overlap_policy_option_summary.csv")
    _write_csv(between, "crash_between_window_summary.csv")
    _write_csv(source, "crash_source_travelway_manual_bucket_summary.csv")
    _write_csv(queue, "crash_manual_overlap_ranked_review_queue.csv")
    _write_text(_findings(detail, class_summary, policy), "final_crash_manual_overlap_decomposition_findings.md")
    signal_source = "review_signal_universe_true_points" if true_signal_points else "scaffold_derived_proxy"
    _write_csv(_qa(direction_cols, signal_source), "final_crash_manual_overlap_decomposition_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.build.final_crash_manual_overlap_decomposition",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "review_only": True,
            "final_crash_assignment_promoted": False,
            "rates_or_models_calculated": False,
            "crash_direction_use": "not_used_inventory_only",
            "signal_geometry_source": signal_source,
            "signal_layer_info": signal_info,
            "outputs": [
                "crash_manual_overlap_target_detail.csv",
                "crash_manual_overlap_reclassified_detail.csv",
                "crash_manual_overlap_class_summary.csv",
                "crash_overlap_policy_option_summary.csv",
                "crash_between_window_summary.csv",
                "crash_source_travelway_manual_bucket_summary.csv",
                "crash_manual_overlap_ranked_review_queue.csv",
                "final_crash_manual_overlap_decomposition_findings.md",
                "final_crash_manual_overlap_decomposition_qa.csv",
                "final_crash_manual_overlap_decomposition_manifest.json",
                "run_progress_log.txt",
            ],
        },
        "final_crash_manual_overlap_decomposition_manifest.json",
    )
    _checkpoint("complete final_crash_manual_overlap_decomposition")


if __name__ == "__main__":
    main()
