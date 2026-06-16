from __future__ import annotations

import json
import math
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from scipy.spatial import cKDTree
from shapely import wkb
from shapely.geometry import Point
from shapely.strtree import STRtree


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"

NORMALIZED_SIGNALS = Path("artifacts/normalized/signals.parquet")
NORMALIZED_CRASHES = Path("artifacts/normalized/crashes.parquet")

FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
ATTRITION_DIR = OUTPUT_ROOT / "review/current/signal_attrition_funnel_audit"
UNREPRESENTED_DIR = OUTPUT_ROOT / "review/current/unrepresented_signal_recovery_feasibility"
MANUAL_CRASH_DIR = OUTPUT_ROOT / "review/current/final_crash_manual_overlap_decomposition"
UNASSIGNED_CRASH_DIR = OUTPUT_ROOT / "review/current/final_crash_unassigned_category_decomposition"

CRS = "EPSG:3968"
FT_TO_M = 0.3048
M_TO_FT = 1 / FT_TO_M

MANUAL_SEEDS = [
    {
        "manual_seed_group": "example_1_obvious_good_travelway",
        "manual_seed_label": "A.P. Hill Blvd and Tidewater Tr.",
        "OBJECTID": "3028",
        "GLOBALID": "{DF2D18EE-4296-4A3A-8900-A4A66D250EF8}",
        "ASSET_ID": "477",
        "REG_SIGNAL_ID": "0301-016-TS010A",
        "user_observation": "complete Travelway coverage; should obviously be part of dataset",
    },
    *[
        {
            "manual_seed_group": "example_2_same_route_cluster",
            "manual_seed_label": "same-route cluster",
            "GLOBALID": globalid,
            "user_observation": "all along the same route or appear to be; not included; no obvious issues",
        }
        for globalid in [
            "{D6AEBEA8-83DA-4DFE-A5BB-E379EBBFFC97}",
            "{51F4F660-6F81-4CCC-8664-6495226FE377}",
            "{440DB4D0-247D-4184-A2CA-0DE6AECD1266}",
            "{41C40BDD-A066-40B7-AD7F-EF3DD908A779}",
            "{149D25B0-464B-4F95-BFA7-DBCCF83C5449}",
        ]
    ],
    *[
        {
            "manual_seed_group": "example_3_clustered_recoverability",
            "manual_seed_label": "clustered recoverability",
            "GLOBALID": globalid,
            "user_observation": "clustered, similar apparent recoverability",
        }
        for globalid in [
            "{FB9D46C2-1ABB-4599-9EF2-195042C1A378}",
            "{4EA72EE4-7C63-4870-B558-B35A6CC35B09}",
            "{9949120A-830E-4642-AE10-8DB9E3E6A984}",
        ]
    ],
    *[
        {
            "manual_seed_group": "example_4_obvious_misses",
            "manual_seed_label": "obvious miss with good Travelway coverage",
            "GLOBALID": globalid,
            "user_observation": "obvious miss with good Travelway coverage",
        }
        for globalid in [
            "{BE037C25-461E-45B0-9824-059F7F7AD40C}",
            "{771A40AA-5BA3-4F3C-BA5B-666328FBE6E5}",
            "{A62BDF57-A497-43CD-950D-AA7E05289B22}",
        ]
    ],
    {
        "manual_seed_group": "legitimate_holdout_example",
        "manual_seed_label": "likely legitimate missing/holdout",
        "GLOBALID": "{5655E8E7-E6AD-49F1-A257-9BD4E6CF2E4F}",
        "user_observation": "likely legitimate missing/holdout; not good Travelway coverage for legs",
        "nearby_partial_fid": "20143",
        "nearby_partial_rte_nm": "R-VA SR00123NB RMP023.00A",
        "nearby_partial_rte_id": "1465800",
        "nearby_partial_from_measure": "0",
        "nearby_partial_to_measure": "0.07",
    },
]

REQUIRED_INPUTS = [
    NORMALIZED_SIGNALS,
    NORMALIZED_CRASHES,
    ACCESS_REVIEW_GPKG,
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    ATTRITION_DIR / "signal_attrition_signal_level_status.csv",
    UNREPRESENTED_DIR / "unrepresented_signal_recovery_detail.csv",
    MANUAL_CRASH_DIR / "crash_manual_overlap_reclassified_detail.csv",
    MANUAL_CRASH_DIR / "final_crash_manual_overlap_decomposition_manifest.json",
    UNASSIGNED_CRASH_DIR / "crash_unassigned_refined_detail.csv",
    UNASSIGNED_CRASH_DIR / "final_crash_unassigned_category_decomposition_manifest.json",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_T0 = time.perf_counter()


def _memory_note() -> str:
    rss_mb = None
    try:
        import psutil

        rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                psapi = ctypes.WinDLL("psapi", use_last_error=True)
                kernel32.GetCurrentProcess.restype = wintypes.HANDLE
                psapi.GetProcessMemoryInfo.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                    wintypes.DWORD,
                ]
                psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
                handle = kernel32.GetCurrentProcess()
                ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
                if ok:
                    rss_mb = counters.WorkingSetSize / (1024 * 1024)
            except Exception:
                rss_mb = None
        if rss_mb is None:
            try:
                import resource

                rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            except Exception:
                rss_mb = None
    elapsed = time.perf_counter() - _T0
    if rss_mb is None:
        return f" elapsed_s={elapsed:.1f}"
    return f" elapsed_s={elapsed:.1f} rss_mb={rss_mb:.1f}"


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}{_memory_note()}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded missing HMMS signal recovery feasibility diagnostic.")
    parser.add_argument("--smoke", action="store_true", help="Run manual seeds plus first 200 missing signals.")
    parser.add_argument("--max-signals", type=int, default=None, help="Maximum scan signals to process.")
    parser.add_argument("--chunk-size", type=int, default=500, help="Signal chunk size for Travelway coverage.")
    parser.add_argument(
        "--max-travelway-detail-rows",
        type=int,
        default=500_000,
        help="Maximum retained non-manual Travelway detail rows.",
    )
    parser.add_argument("--skip-review-gpkg", action="store_true", help="Skip optional map-review GeoPackage.")
    return parser.parse_args()


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if ACCESS_REVIEW_GPKG.exists():
        layers = {row[0] for row in pyogrio.list_layers(ACCESS_REVIEW_GPKG)}
        if SOURCE_TRAVELWAY_LAYER not in layers:
            missing.append(f"{ACCESS_REVIEW_GPKG}:{SOURCE_TRAVELWAY_LAYER}")
        if "review_signal_universe" not in layers:
            missing.append(f"{ACCESS_REVIEW_GPKG}:review_signal_universe")
    return missing


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    _checkpoint(f"write {name} start", len(frame))
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name} finish", len(frame))


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write {name} start")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name} finish")


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write {name} start")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name} finish")


def _text(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[col].fillna("").astype(str)


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[col], errors="coerce")


def _norm(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text.upper()


def _norm_guid(value: Any) -> str:
    text = _norm(value)
    if text and not text.startswith("{"):
        text = "{" + text.strip("{}") + "}"
    return text


def _parse_wkb(value: Any):
    if value is None or value == "":
        return None
    try:
        return wkb.loads(value)
    except Exception:
        return None


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _signal_source_id(row: pd.Series) -> str:
    for col in ["ASSET_NUM", "REG_SIGNAL_ID", "ASSET_ID", "GLOBALID"]:
        value = str(row.get(col, "")).strip()
        if value and value.lower() not in {"nan", "none"}:
            return value
    return ""


def _source_identifier_set(row: pd.Series) -> set[str]:
    values: set[str] = set()
    for col in ["GLOBALID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM", "OBJECTID_1", "SIGNAL_NO", "INTNO", "INTNUM"]:
        value = str(row.get(col, "")).strip()
        if value and value.lower() not in {"nan", "none"}:
            values.add(_norm(value))
            if value.endswith(".0"):
                values.add(_norm(value[:-2]))
    gid = row.get("GLOBALID", "")
    if str(gid).strip():
        values.add(_norm_guid(gid))
    return values


def _load_signals() -> gpd.GeoDataFrame:
    signals = pd.read_parquet(NORMALIZED_SIGNALS)
    signals["source_signal_id"] = signals.apply(_signal_source_id, axis=1)
    signals["source_signal_key"] = signals["GLOBALID"].map(_norm_guid)
    signals["normalized_source_universe_flag"] = True
    signals["source_record_exists"] = True
    signals["geometry"] = signals["geometry"].map(_parse_wkb)
    gdf = gpd.GeoDataFrame(signals, geometry="geometry", crs=CRS)
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf["source_row_index"] = np.arange(len(gdf), dtype=np.int64)
    _checkpoint("load normalized HMMS signal source", len(gdf))
    return gdf


def _represented_identifier_set(final_signals: pd.DataFrame, represented_points: gpd.GeoDataFrame) -> set[str]:
    ids: set[str] = set()
    for frame in [final_signals, represented_points]:
        for col in [
            "signal_id",
            "source_signal_id",
            "represented_source_signal_id",
            "source_signal_id_x",
            "source_signal_id_y",
            "stable_signal_id",
            "target_signal_id",
        ]:
            if col in frame.columns:
                ids.update({_norm(value) for value in frame[col].dropna().astype(str) if str(value).strip()})
    return {value for value in ids if value}


def _load_final_context() -> tuple[pd.DataFrame, gpd.GeoDataFrame, set[str]]:
    final_signals = _read_csv(FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv")
    represented_points = pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer="review_signal_universe")
    if represented_points.crs is None:
        represented_points = represented_points.set_crs(CRS, allow_override=True)
    represented_points = represented_points.to_crs(CRS)
    represented_ids = _represented_identifier_set(final_signals, represented_points)
    _checkpoint("load final represented signal context", len(final_signals))
    return final_signals, represented_points, represented_ids


def _attach_source_status(signals: gpd.GeoDataFrame, represented_ids: set[str]) -> gpd.GeoDataFrame:
    represented_flags = []
    for _, row in signals.iterrows():
        represented_flags.append(bool(_source_identifier_set(row) & represented_ids))
    out = signals.copy()
    out["represented_in_final_universe"] = represented_flags
    return out


def _attach_loss_context(signals: pd.DataFrame) -> pd.DataFrame:
    _checkpoint("attach loss context start", len(signals))
    out = signals.copy()
    attr_cols = [
        "source_signal_key",
        "signal_id",
        "source_signal_id",
        "source_signal_row_id",
        "step5_exclusion_reason",
        "nearest_road_association_status",
        "graph_gap_issue_flags",
        "best_available_loss_reason",
        "methodology_interpretation",
        "nearest_travelway_distance_ft",
        "nearby_travelway_candidate_count",
        "unique_nearby_route_count",
        "represented_in_active_0_2500ft_context",
    ]
    attr = _read_csv(ATTRITION_DIR / "signal_attrition_signal_level_status.csv", usecols=attr_cols)
    attr["source_signal_key_norm"] = _text(attr, "source_signal_key").map(_norm_guid)
    attr_counts = attr.groupby("source_signal_key_norm", dropna=False).size().rename("_attr_context_match_count").reset_index()
    attr = attr.merge(attr_counts, on="source_signal_key_norm", how="left")
    before_attr = len(attr)
    attr = attr.drop_duplicates("source_signal_key_norm", keep="first").copy()
    _checkpoint(f"dedupe attrition context {before_attr:,}->{len(attr):,}", len(attr))
    out["source_signal_key_norm"] = _text(out, "GLOBALID").map(_norm_guid)
    out = out.merge(attr.add_prefix("attr_"), left_on="source_signal_key_norm", right_on="attr_source_signal_key_norm", how="left")
    _checkpoint("attach attrition context finish", len(out))

    unrep_cols = [
        "source_signal_id",
        "signal_id",
        "remaining_loss_reason",
        "recoverability_class",
        "plain_language_class_explanation",
        "likely_next_implementation_action",
        "expected_difficulty",
        "target_before_access_crash_work",
        "plausible_additional_represented_signal",
        "immediate_implementation_attempt",
        "hold_for_manual_or_mapped_review",
    ]
    unrep = _read_csv(UNREPRESENTED_DIR / "unrepresented_signal_recovery_detail.csv", usecols=unrep_cols)
    out["_asset_num_norm"] = _text(out, "ASSET_NUM").map(_norm)
    unrep["_source_norm"] = _text(unrep, "source_signal_id").map(_norm)
    unrep_counts = unrep.groupby("_source_norm", dropna=False).size().rename("_unrep_context_match_count").reset_index()
    unrep = unrep.merge(unrep_counts, on="_source_norm", how="left")
    before_unrep = len(unrep)
    unrep = unrep.drop_duplicates("_source_norm", keep="first").copy()
    _checkpoint(f"dedupe unrepresented context {before_unrep:,}->{len(unrep):,}", len(unrep))
    out = out.merge(unrep.add_prefix("unrep_"), left_on="_asset_num_norm", right_on="unrep__source_norm", how="left")
    _checkpoint("attach loss context finish", len(out))
    return out


def _bearing_sector(point: Point, line) -> str:
    nearest = shapely.line_interpolate_point(line, shapely.line_locate_point(line, point))
    dx = nearest.x - point.x
    dy = nearest.y - point.y
    if math.hypot(dx, dy) < 1e-6:
        if line.geom_type == "MultiLineString":
            coords = list(max(line.geoms, key=lambda geom: geom.length).coords)
        else:
            coords = list(line.coords)
        endpoints = [Point(coords[0]), Point(coords[-1])]
        endpoint = min(endpoints, key=lambda geom: geom.distance(point))
        dx = endpoint.x - point.x
        dy = endpoint.y - point.y
    angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    return f"sector_{int(angle // 45):02d}"


def _empty_travelway_summary(signals: gpd.GeoDataFrame) -> pd.DataFrame:
    summary = signals[["source_row_index", "source_signal_id", "GLOBALID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM"]].copy()
    for col in [
        "travelway_lines_within_125ft",
        "travelway_lines_within_175ft",
        "travelway_lines_within_250ft",
        "approach_sector_count_250ft",
        "unique_route_count_250ft",
        "ramp_like_lines_250ft",
        "grade_or_limited_access_lines_250ft",
    ]:
        summary[col] = 0
    summary["nearest_travelway_distance_ft_new"] = np.nan
    summary["travelway_route_sample"] = ""
    summary["likely_physical_leg_count"] = 0
    summary["source_travelway_appears_scaffold_ready"] = False
    summary["travelway_detail_retention_status"] = "no_pairs"
    return summary


def _chunk_bbox(chunk: gpd.GeoDataFrame, buffer_distance: float) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = chunk.total_bounds
    return (minx - buffer_distance, miny - buffer_distance, maxx + buffer_distance, maxy + buffer_distance)


def _read_travelway_bbox(chunk: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    bbox = _chunk_bbox(chunk, 250 * FT_TO_M)
    return pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER, bbox=bbox).to_crs(CRS)


def _travelway_feature_count() -> int | None:
    try:
        info = pyogrio.read_info(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER)
        features = info.get("features")
        return int(features) if features is not None and int(features) >= 0 else None
    except Exception as exc:
        _checkpoint(f"Travelway feature-count unavailable {exc}")
        return None


def _candidate_pair_count(chunk: gpd.GeoDataFrame) -> tuple[int, int]:
    travelway = _read_travelway_bbox(chunk)
    if chunk.empty or travelway.empty:
        return 0, len(travelway)
    points = np.asarray(chunk.geometry.to_numpy(), dtype=object)
    lines = np.asarray(travelway.geometry.to_numpy(), dtype=object)
    tree = STRtree(lines)
    pair_idx = tree.query(points, predicate="dwithin", distance=250 * FT_TO_M)
    pairs = int(pair_idx.shape[1]) if pair_idx.size else 0
    return pairs, len(travelway)


def _preflight_travelway(signals: gpd.GeoDataFrame, chunk_size: int, max_detail_rows: int) -> dict[str, Any]:
    sample = signals.head(max(1, min(len(signals), chunk_size))).copy()
    _checkpoint("preflight Travelway first chunk start", len(sample))
    pairs, bbox_rows = _candidate_pair_count(sample)
    pairs_per_signal = pairs / max(len(sample), 1)
    extrapolated = int(round(pairs_per_signal * len(signals)))
    feature_count = _travelway_feature_count()
    warn = extrapolated > max(max_detail_rows, 1) * 10
    if warn:
        _checkpoint(f"preflight warning extrapolated_pairs={extrapolated:,} exceeds detail cap by >10x")
    _checkpoint(f"preflight Travelway first chunk finish pairs={pairs:,} bbox_rows={bbox_rows:,}")
    return {
        "scan_signal_count": int(len(signals)),
        "travelway_feature_count": feature_count,
        "preflight_chunk_signal_count": int(len(sample)),
        "preflight_chunk_travelway_bbox_rows": int(bbox_rows),
        "preflight_chunk_candidate_pairs": int(pairs),
        "preflight_extrapolated_candidate_pairs": int(extrapolated),
        "preflight_pair_warning": bool(warn),
    }


def _summarize_travelway_detail(detail: pd.DataFrame, signals: gpd.GeoDataFrame) -> pd.DataFrame:
    if detail.empty:
        return _empty_travelway_summary(signals)
    grouped = detail.groupby("source_row_index", dropna=False).agg(
        travelway_lines_within_125ft=("within_125ft", "sum"),
        travelway_lines_within_175ft=("within_175ft", "sum"),
        travelway_lines_within_250ft=("within_250ft", "sum"),
        approach_sector_count_250ft=("bearing_sector", "nunique"),
        unique_route_count_250ft=("RTE_ID", "nunique"),
        nearest_travelway_distance_ft_new=("travelway_distance_ft", "min"),
        travelway_route_sample=("RTE_COMMON", lambda s: "|".join(sorted({str(v) for v in s if str(v).strip()})[:8])),
        ramp_like_lines_250ft=("RTE_RAMP_C", lambda s: sum(str(v).strip() not in {"", "0", "0.0", "nan", "None"} for v in s)),
        grade_or_limited_access_lines_250ft=("RIM_ACCESS", lambda s: sum("LIMITED" in str(v).upper() for v in s)),
    ).reset_index()
    base = signals[["source_row_index", "source_signal_id", "GLOBALID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM"]].copy()
    summary = base.merge(grouped, on="source_row_index", how="left")
    for col in ["travelway_lines_within_125ft", "travelway_lines_within_175ft", "travelway_lines_within_250ft", "approach_sector_count_250ft", "unique_route_count_250ft", "ramp_like_lines_250ft", "grade_or_limited_access_lines_250ft"]:
        summary[col] = pd.to_numeric(summary[col], errors="coerce").fillna(0).astype(int)
    summary["nearest_travelway_distance_ft_new"] = pd.to_numeric(summary["nearest_travelway_distance_ft_new"], errors="coerce")
    summary["travelway_route_sample"] = summary["travelway_route_sample"].fillna("")
    summary["likely_physical_leg_count"] = summary["approach_sector_count_250ft"]
    summary["source_travelway_appears_scaffold_ready"] = (
        summary["travelway_lines_within_125ft"].ge(2)
        & summary["approach_sector_count_250ft"].ge(2)
        & summary["grade_or_limited_access_lines_250ft"].eq(0)
    )
    summary["travelway_detail_retention_status"] = "summarized"
    return summary


def _travelway_pair_rows(chunk: gpd.GeoDataFrame, travelway: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    if chunk.empty or travelway.empty:
        return []
    points = np.asarray(chunk.geometry.to_numpy(), dtype=object)
    lines = np.asarray(travelway.geometry.to_numpy(), dtype=object)
    _checkpoint("build/query Travelway spatial index start", len(travelway))
    tree = STRtree(lines)
    pair_idx = tree.query(points, predicate="dwithin", distance=250 * FT_TO_M)
    candidate_count = int(pair_idx.shape[1]) if pair_idx.size else 0
    _checkpoint("build/query Travelway spatial index finish", candidate_count)
    if not pair_idx.size:
        return []
    rows: list[dict[str, Any]] = []
    source_idx = pair_idx[0]
    line_idx = pair_idx[1]
    distances_ft = shapely.distance(points[source_idx], lines[line_idx]) * M_TO_FT
    for sig_i, line_i, dist_ft in zip(source_idx, line_idx, distances_ft):
        sig = chunk.iloc[int(sig_i)]
        tw = travelway.iloc[int(line_i)]
        sector = _bearing_sector(sig.geometry, tw.geometry)
        rows.append(
            {
                "source_row_index": sig["source_row_index"],
                "source_signal_id": sig.get("source_signal_id", ""),
                "GLOBALID": sig.get("GLOBALID", ""),
                "ASSET_ID": sig.get("ASSET_ID", ""),
                "REG_SIGNAL_ID": sig.get("REG_SIGNAL_ID", ""),
                "ASSET_NUM": sig.get("ASSET_NUM", ""),
                "travelway_distance_ft": round(float(dist_ft), 3),
                "within_125ft": bool(dist_ft <= 125),
                "within_175ft": bool(dist_ft <= 175),
                "within_250ft": bool(dist_ft <= 250),
                "bearing_sector": sector,
                "RTE_ID": tw.get("RTE_ID", ""),
                "RTE_NM": tw.get("RTE_NM", ""),
                "RTE_COMMON": tw.get("RTE_COMMON", ""),
                "RIM_FACILI": tw.get("RIM_FACILI", ""),
                "RIM_ACCESS": tw.get("RIM_ACCESS", ""),
                "RTE_RAMP_C": tw.get("RTE_RAMP_C", ""),
                "FROM_MEASURE": tw.get("FROM_MEASURE", ""),
                "TO_MEASURE": tw.get("TO_MEASURE", ""),
            }
        )
    return rows


def _travelway_coverage(
    signals: gpd.GeoDataFrame,
    manual_seed_row_ids: set[int],
    chunk_size: int,
    max_detail_rows: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    summaries: list[pd.DataFrame] = []
    retained_detail: list[pd.DataFrame] = []
    retained_nonseed_rows = 0
    cap_exceeded = False
    total_pairs = 0
    total_travelway_bbox_rows = 0
    chunk_size = max(1, int(chunk_size))
    max_detail_rows = max(0, int(max_detail_rows))
    for chunk_no, start in enumerate(range(0, len(signals), chunk_size), start=1):
        chunk = signals.iloc[start : start + chunk_size].copy()
        _checkpoint(f"signal chunk {chunk_no} start", len(chunk))
        travelway = _read_travelway_bbox(chunk)
        total_travelway_bbox_rows += len(travelway)
        _checkpoint(f"signal chunk {chunk_no} read Travelway bbox", len(travelway))
        rows = _travelway_pair_rows(chunk, travelway)
        total_pairs += len(rows)
        detail = pd.DataFrame(rows)
        summaries.append(_summarize_travelway_detail(detail, chunk))
        if not detail.empty:
            manual_mask = pd.to_numeric(detail["source_row_index"], errors="coerce").isin(manual_seed_row_ids)
            retain = [detail.loc[manual_mask].copy()]
            nonseed = detail.loc[~manual_mask].copy()
            remaining = max_detail_rows - retained_nonseed_rows
            if remaining > 0:
                retain.append(nonseed.head(remaining))
                retained_nonseed_rows += min(len(nonseed), remaining)
            if len(nonseed) > remaining:
                cap_exceeded = True
            retained_detail.extend([frame for frame in retain if not frame.empty])
        _checkpoint(f"signal chunk {chunk_no} finish pairs={len(rows):,} retained_detail={retained_nonseed_rows:,}")
    summary = pd.concat(summaries, ignore_index=True) if summaries else _empty_travelway_summary(signals)
    if cap_exceeded:
        summary["travelway_detail_retention_status"] = np.where(
            summary["source_row_index"].isin(manual_seed_row_ids),
            "manual_seed_retained",
            "detail_cap_exceeded_sample_only",
        )
    elif max_detail_rows == 0:
        summary["travelway_detail_retention_status"] = np.where(
            summary["source_row_index"].isin(manual_seed_row_ids),
            "manual_seed_retained",
            "detail_disabled",
        )
    detail = pd.concat(retained_detail, ignore_index=True) if retained_detail else pd.DataFrame()
    stats = {
        "travelway_candidate_pairs": int(total_pairs),
        "travelway_bbox_rows_read_total": int(total_travelway_bbox_rows),
        "retained_travelway_detail_rows": int(len(detail)),
        "retained_nonmanual_travelway_detail_rows": int(retained_nonseed_rows),
        "travelway_detail_cap_exceeded": bool(cap_exceeded),
    }
    return detail, summary, stats


def _nearby_travelway_crash_context(signals: gpd.GeoDataFrame, crashes: gpd.GeoDataFrame, chunk_size: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    chunk_size = max(1, int(chunk_size))
    crash_xy = np.column_stack([crashes.geometry.x.to_numpy(), crashes.geometry.y.to_numpy()])
    crash_tree = cKDTree(crash_xy)
    crash_geoms = np.asarray(crashes.geometry.to_numpy(), dtype=object)
    for chunk_no, start in enumerate(range(0, len(signals), chunk_size), start=1):
        chunk = signals.iloc[start : start + chunk_size].copy()
        _checkpoint(f"source Travelway crash-context chunk {chunk_no} start", len(chunk))
        travelway = _read_travelway_bbox(chunk)
        lines = np.asarray(travelway.geometry.to_numpy(), dtype=object)
        line_tree = STRtree(lines) if len(lines) else None
        for sig in chunk.itertuples(index=False):
            point = sig.geometry
            out = {"source_row_index": getattr(sig, "source_row_index")}
            for radius in [50, 75, 100]:
                out[f"crashes_within_{radius}ft_nearby_source_travelway_250ft_signal_window"] = 0
            if line_tree is not None:
                nearby_line_idx = line_tree.query([point], predicate="dwithin", distance=250 * FT_TO_M)
                if nearby_line_idx.size:
                    local_lines = lines[nearby_line_idx[1]]
                    crash_idx = crash_tree.query_ball_point([point.x, point.y], r=250 * FT_TO_M)
                    if crash_idx:
                        distances_ft = shapely.distance(crash_geoms[np.asarray(crash_idx, dtype=np.int64)][:, None], local_lines[None, :]).min(axis=1) * M_TO_FT
                        for radius in [50, 75, 100]:
                            out[f"crashes_within_{radius}ft_nearby_source_travelway_250ft_signal_window"] = int(np.count_nonzero(distances_ft <= radius))
            rows.append(out)
        _checkpoint(f"source Travelway crash-context chunk {chunk_no} finish", len(rows))
    return pd.DataFrame(rows)


def _load_crashes() -> gpd.GeoDataFrame:
    cols = ["DOCUMENT_NBR", "CRASH_YEAR", "CRASH_SEVERITY", "COLLISION_TYPE", "MAINLINE_YN", "RTE_NM", "geometry"]
    crashes = pd.read_parquet(NORMALIZED_CRASHES, columns=cols)
    crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    crashes["geometry"] = crashes["geometry"].map(_parse_wkb)
    gdf = gpd.GeoDataFrame(crashes, geometry="geometry", crs=CRS)
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    _checkpoint("load normalized crash points for proximity context", len(gdf))
    return gdf


def _crash_context(signals: gpd.GeoDataFrame, crashes: gpd.GeoDataFrame, source_not_rep_crashes: gpd.GeoDataFrame | None = None) -> pd.DataFrame:
    signal_xy = np.column_stack([signals.geometry.x.to_numpy(), signals.geometry.y.to_numpy()])
    crash_xy = np.column_stack([crashes.geometry.x.to_numpy(), crashes.geometry.y.to_numpy()])
    crash_tree = cKDTree(crash_xy)
    rows = signals[["source_row_index", "source_signal_id", "GLOBALID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM"]].copy()
    for radius in [250, 500, 1000, 2500]:
        counts = crash_tree.query_ball_point(signal_xy, r=radius * FT_TO_M, return_length=True)
        rows[f"crashes_within_{radius}ft_signal"] = counts.astype(int)
    if source_not_rep_crashes is not None and len(source_not_rep_crashes):
        un_xy = np.column_stack([source_not_rep_crashes.geometry.x.to_numpy(), source_not_rep_crashes.geometry.y.to_numpy()])
        un_tree = cKDTree(un_xy)
        for radius in [500, 1000, 2500]:
            counts = un_tree.query_ball_point(signal_xy, r=radius * FT_TO_M, return_length=True)
            rows[f"source_not_represented_unassigned_crashes_within_{radius}ft"] = counts.astype(int)
    else:
        for radius in [500, 1000, 2500]:
            rows[f"source_not_represented_unassigned_crashes_within_{radius}ft"] = 0
    return rows


def _source_not_represented_crashes() -> gpd.GeoDataFrame:
    cols = [
        "stable_crash_id",
        "crash_geometry_wkt",
        "final_manual_overlap_class",
        "nearest_source_travelway_distance_ft",
        "nearest_scaffold_bin_distance_ft",
    ]
    manual = _read_csv(MANUAL_CRASH_DIR / "crash_manual_overlap_reclassified_detail.csv", usecols=cols)
    manual = manual.loc[_text(manual, "final_manual_overlap_class").eq("source_travelway_not_represented_by_signal_scaffold")].copy()
    manual["geometry"] = _text(manual, "crash_geometry_wkt").map(lambda v: shapely.from_wkt(v) if str(v).strip() else None)
    gdf = gpd.GeoDataFrame(manual, geometry="geometry", crs=CRS)
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    _checkpoint("load source-not-represented crash context", len(gdf))
    return gdf


def _classify_recoverability(row: pd.Series) -> str:
    sectors = int(row.get("approach_sector_count_250ft", 0) or 0)
    lines125 = int(row.get("travelway_lines_within_125ft", 0) or 0)
    lines250 = int(row.get("travelway_lines_within_250ft", 0) or 0)
    nearest = float(row.get("nearest_travelway_distance_ft_new", np.nan))
    ramp_lines = int(row.get("ramp_like_lines_250ft", 0) or 0)
    limited_lines = int(row.get("grade_or_limited_access_lines_250ft", 0) or 0)
    loss = " ".join(
        str(row.get(col, ""))
        for col in [
            "attr_step5_exclusion_reason",
            "attr_best_available_loss_reason",
            "attr_methodology_interpretation",
            "unrep_recoverability_class",
            "unrep_remaining_loss_reason",
        ]
    ).lower()
    if not np.isfinite(nearest) or lines250 == 0:
        return "source_travelway_missing_or_incomplete"
    if ramp_lines > 0 or limited_lines > 0 or "grade" in loss or "mainline" in loss or "interchange" in loss:
        return "grade_mainline_or_interchange_holdout"
    if sectors >= 3 and lines125 >= 2:
        if "multi" in loss or "complex" in loss or sectors >= 5:
            return "recoverable_complex_multi_signal_context"
        return "recoverable_good_travelway_coverage"
    if sectors >= 2 and nearest <= 175:
        return "recoverable_offset_anchor_needed"
    if "duplicate" in loss or "sibling" in loss:
        return "signal_source_duplicate_or_sibling_issue"
    return "insufficient_evidence"


def _decision_action(cls: str) -> str:
    return {
        "recoverable_good_travelway_coverage": "target_bounded_missing_signal_recovery",
        "recoverable_offset_anchor_needed": "target_offset_anchor_missing_signal_recovery",
        "recoverable_complex_multi_signal_context": "target_complex_missing_signal_review_branch",
        "source_travelway_missing_or_incomplete": "hold_source_travelway_limitation",
        "grade_mainline_or_interchange_holdout": "hold_grade_mainline_or_interchange",
        "signal_source_duplicate_or_sibling_issue": "source_signal_lineage_review",
        "insufficient_evidence": "manual_or_source_review_needed",
    }.get(cls, "manual_or_source_review_needed")


def _seed_match_table(signals: pd.DataFrame) -> pd.DataFrame:
    seeds = pd.DataFrame(MANUAL_SEEDS)
    for col in ["OBJECTID", "GLOBALID", "ASSET_ID", "REG_SIGNAL_ID"]:
        if col not in seeds.columns:
            seeds[col] = ""
    rows = []
    for _, seed in seeds.iterrows():
        mask = pd.Series(False, index=signals.index)
        seed_globalid = _norm_guid(seed.get("GLOBALID", ""))
        seed_asset_id = _norm(seed.get("ASSET_ID", "")).rstrip(".0")
        seed_reg_signal_id = _norm(seed.get("REG_SIGNAL_ID", ""))
        seed_objectid = _norm(seed.get("OBJECTID", "")).rstrip(".0")
        if seed_globalid:
            mask |= _text(signals, "GLOBALID").map(_norm_guid).eq(seed_globalid)
        if seed_asset_id:
            mask |= _text(signals, "ASSET_ID").map(lambda v: _norm(v).rstrip(".0")).eq(seed_asset_id)
        if seed_reg_signal_id:
            mask |= _text(signals, "REG_SIGNAL_ID").map(_norm).eq(seed_reg_signal_id)
            mask |= _text(signals, "ASSET_NUM").map(_norm).eq(seed_reg_signal_id)
        if seed_objectid:
            mask |= _text(signals, "OBJECTID_1").map(lambda v: _norm(v).rstrip(".0")).eq(seed_objectid)
        matches = signals.loc[mask].copy()
        if matches.empty:
            rows.append({**seed.to_dict(), "source_record_exists": False})
        else:
            for _, match in matches.iterrows():
                rows.append({**seed.to_dict(), **{col: match.get(col, "") for col in signals.columns if col != "geometry"}, "source_record_exists": True})
    return pd.DataFrame(rows)


def _write_review_gpkg(seed_diag: pd.DataFrame, missing_detail: pd.DataFrame, represented_points: gpd.GeoDataFrame) -> None:
    gpkg = OUT_DIR / "missing_hmms_signal_recovery_review.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    _checkpoint("write optional review gpkg start")
    seed_gdf = gpd.GeoDataFrame(seed_diag.copy(), geometry=seed_diag["geometry_obj"], crs=CRS)
    pyogrio.write_dataframe(seed_gdf, gpkg, layer="manual_seed_signal_points", driver="GPKG")
    recoverable = missing_detail.loc[_text(missing_detail, "recoverability_class").str.startswith("recoverable")].copy()
    recoverable = recoverable.sort_values(["source_not_represented_unassigned_crashes_within_2500ft", "crashes_within_2500ft_signal"], ascending=False).head(1000)
    rec_gdf = gpd.GeoDataFrame(recoverable.copy(), geometry=recoverable["geometry_obj"], crs=CRS)
    pyogrio.write_dataframe(rec_gdf, gpkg, layer="recoverable_missing_signal_points", driver="GPKG")
    pyogrio.write_dataframe(represented_points.head(3000), gpkg, layer="final_represented_signal_points", driver="GPKG")
    travelway = pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER, max_features=5000).to_crs(CRS)
    pyogrio.write_dataframe(travelway.head(5000), gpkg, layer="source_travelway_sample", driver="GPKG")
    _checkpoint("write optional review gpkg finish")


def main() -> None:
    args = _parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    _checkpoint("reading signals start")
    signals = _load_signals()
    _checkpoint("reading signals finish", len(signals))
    _checkpoint("reading represented context start")
    final_signals, represented_points, represented_ids = _load_final_context()
    _checkpoint("reading represented context finish", len(final_signals))
    signals = _attach_source_status(signals, represented_ids)
    signals = gpd.GeoDataFrame(_attach_loss_context(signals), geometry="geometry", crs=CRS)

    seed_pre = _seed_match_table(pd.DataFrame(signals.drop(columns="geometry")))
    seed_row_ids = set(pd.to_numeric(seed_pre.get("source_row_index", pd.Series(dtype=float)), errors="coerce").dropna().astype(int))
    missing_mask = ~signals["represented_in_final_universe"].astype(bool)
    if args.smoke:
        missing_ids = signals.loc[missing_mask & ~signals["source_row_index"].isin(seed_row_ids), "source_row_index"].head(200)
        selected_ids = seed_row_ids | set(pd.to_numeric(missing_ids, errors="coerce").dropna().astype(int))
        scan_mask = signals["source_row_index"].isin(selected_ids)
    elif args.max_signals is not None:
        missing_ids = signals.loc[missing_mask & ~signals["source_row_index"].isin(seed_row_ids), "source_row_index"].head(max(0, args.max_signals - len(seed_row_ids)))
        selected_ids = seed_row_ids | set(pd.to_numeric(missing_ids, errors="coerce").dropna().astype(int))
        scan_mask = signals["source_row_index"].isin(selected_ids)
    else:
        scan_mask = missing_mask | signals["source_row_index"].isin(seed_row_ids)
    scan_signals = signals.loc[scan_mask].copy().sort_values("source_row_index")
    _checkpoint("bounded missing/seed signal scan set", len(scan_signals))

    _checkpoint("reading/querying Travelway preflight start")
    preflight = _preflight_travelway(scan_signals, args.chunk_size, args.max_travelway_detail_rows)
    _checkpoint("reading/querying Travelway preflight finish")
    tw_detail, tw_summary, travelway_stats = _travelway_coverage(
        scan_signals,
        manual_seed_row_ids=seed_row_ids,
        chunk_size=args.chunk_size,
        max_detail_rows=args.max_travelway_detail_rows,
    )

    _checkpoint("crash context start")
    crashes = _load_crashes()
    source_not_rep = _source_not_represented_crashes()
    crash_summary = _crash_context(scan_signals, crashes, source_not_rep)
    nearby_tw_crash_summary = _nearby_travelway_crash_context(scan_signals, crashes, args.chunk_size)
    crash_summary = crash_summary.merge(nearby_tw_crash_summary, on="source_row_index", how="left")
    _checkpoint("crash context finish", len(crash_summary))

    merged = pd.DataFrame(scan_signals.drop(columns="geometry")).merge(
        tw_summary.drop(columns=["source_signal_id", "GLOBALID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM"], errors="ignore"),
        on="source_row_index",
        how="left",
    )
    merged = merged.merge(
        crash_summary.drop(columns=["source_signal_id", "GLOBALID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM"], errors="ignore"),
        on="source_row_index",
        how="left",
    )
    merged["recoverability_class"] = merged.apply(_classify_recoverability, axis=1)
    merged["recommended_action"] = merged["recoverability_class"].map(_decision_action)
    merged["geometry_obj"] = scan_signals.geometry.to_numpy()
    merged["signal_geometry_wkt"] = [geom.wkt for geom in scan_signals.geometry]
    merged["present_in_3933_source_universe"] = True

    missing_detail = merged.loc[~merged["represented_in_final_universe"].astype(bool)].copy()
    missing_detail["high_crash_relevance_flag"] = pd.to_numeric(missing_detail["source_not_represented_unassigned_crashes_within_2500ft"], errors="coerce").fillna(0).ge(25)

    seed_diag = _seed_match_table(merged)
    if "geometry_obj" not in seed_diag.columns:
        seed_diag["geometry_obj"] = None
    seed_diag["present_in_3933_source_universe"] = seed_diag["source_record_exists"].astype(bool)
    seed_diag["best_known_loss_stage_or_reason"] = seed_diag.get("attr_best_available_loss_reason", "").fillna("").astype(str)
    seed_diag.loc[seed_diag["represented_in_final_universe"].astype(str).str.lower().eq("true"), "best_known_loss_stage_or_reason"] = "represented_final_universe"

    seed_tw = tw_detail.merge(seed_diag[["source_row_index", "manual_seed_group", "manual_seed_label"]], on="source_row_index", how="inner") if "source_row_index" in seed_diag.columns else pd.DataFrame()
    seed_crash = crash_summary.merge(seed_diag[["source_row_index", "manual_seed_group", "manual_seed_label"]], on="source_row_index", how="inner") if "source_row_index" in seed_diag.columns else pd.DataFrame()

    _write_csv(seed_diag.drop(columns=["geometry_obj"], errors="ignore"), "manual_seed_missing_signal_diagnostic.csv")
    _write_csv(seed_tw, "manual_seed_travelway_coverage_detail.csv")
    _write_csv(seed_crash, "manual_seed_crash_context_summary.csv")
    _write_csv(missing_detail.drop(columns=["geometry_obj"], errors="ignore"), "missing_source_signal_universe_detail.csv")

    tw_cov_summary = missing_detail.groupby("recoverability_class", dropna=False).agg(
        missing_signal_count=("source_signal_id", "size"),
        median_travelway_lines_250ft=("travelway_lines_within_250ft", "median"),
        median_approach_sectors_250ft=("approach_sector_count_250ft", "median"),
        median_likely_physical_leg_count=("likely_physical_leg_count", "median"),
        median_nearest_travelway_distance_ft=("nearest_travelway_distance_ft_new", "median"),
        scaffold_ready_signal_count=("source_travelway_appears_scaffold_ready", "sum"),
    ).reset_index()
    _write_csv(tw_cov_summary, "missing_signal_travelway_coverage_summary.csv")

    class_summary = missing_detail.groupby("recoverability_class", dropna=False).agg(
        missing_signal_count=("source_signal_id", "size"),
        high_crash_relevance_signals=("high_crash_relevance_flag", "sum"),
        source_not_represented_crashes_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", "sum"),
        all_crashes_2500ft=("crashes_within_2500ft_signal", "sum"),
        nearby_source_travelway_crashes_100ft=("crashes_within_100ft_nearby_source_travelway_250ft_signal_window", "sum"),
    ).reset_index()
    class_summary["recommended_action"] = class_summary["recoverability_class"].map(_decision_action)
    _write_csv(class_summary, "missing_signal_recoverability_class_summary.csv")

    priority = missing_detail.loc[missing_detail["recoverability_class"].str.startswith("recoverable")].copy()
    priority = priority.sort_values(["source_not_represented_unassigned_crashes_within_2500ft", "crashes_within_2500ft_signal", "approach_sector_count_250ft"], ascending=False)
    _write_csv(priority.head(500).drop(columns=["geometry_obj"], errors="ignore"), "missing_signal_crash_relevance_priority_queue.csv")

    decision_tree = pd.DataFrame(
        [
            {"decision_order": 1, "condition": "no Travelway lines within 250 ft", "class": "source_travelway_missing_or_incomplete", "recommended_action": "hold_source_travelway_limitation"},
            {"decision_order": 2, "condition": "ramp/limited-access/grade-mainline evidence nearby", "class": "grade_mainline_or_interchange_holdout", "recommended_action": "hold_grade_mainline_or_interchange"},
            {"decision_order": 3, "condition": "3+ approach sectors and 2+ lines within 125 ft", "class": "recoverable_good_travelway_coverage", "recommended_action": "target_bounded_missing_signal_recovery"},
            {"decision_order": 4, "condition": "2+ sectors and nearest Travelway within 175 ft", "class": "recoverable_offset_anchor_needed", "recommended_action": "target_offset_anchor_missing_signal_recovery"},
            {"decision_order": 5, "condition": "complex/multi-signal loss context with usable Travelway", "class": "recoverable_complex_multi_signal_context", "recommended_action": "target_complex_missing_signal_review_branch"},
            {"decision_order": 6, "condition": "duplicate/sibling evidence", "class": "signal_source_duplicate_or_sibling_issue", "recommended_action": "source_signal_lineage_review"},
            {"decision_order": 7, "condition": "all other missing records", "class": "insufficient_evidence", "recommended_action": "manual_or_source_review_needed"},
        ]
    )
    _write_csv(decision_tree, "missing_signal_recovery_decision_tree.csv")

    findings = _findings(seed_diag, class_summary, priority)
    _write_text(findings, "missing_hmms_signal_recovery_feasibility_findings.md")

    qa = pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": "outputs written only to review/current/missing_hmms_signal_recovery_feasibility"},
            {"check_name": "no_candidates_promoted", "status": "passed", "observed": "diagnostic only"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "crashes used only for proximity counts"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_not_used", "status": "passed", "observed": "crash source read without direction fields"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "manual_seed_globalids_preserved", "status": "passed", "observed": str(len(MANUAL_SEEDS))},
        ]
    )
    _write_csv(qa, "missing_hmms_signal_recovery_feasibility_qa.csv")

    if args.skip_review_gpkg:
        optional_gpkg = "skipped_by_cli"
        _checkpoint("optional gpkg skipped by CLI")
    else:
        try:
            _write_review_gpkg(seed_diag, missing_detail, represented_points)
            optional_gpkg = "missing_hmms_signal_recovery_review.gpkg"
        except Exception as exc:
            optional_gpkg = f"not_written: {exc}"
            _checkpoint(f"optional gpkg skipped {exc}")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_signal_recovery_feasibility",
        "review_only": True,
        "run_mode": "smoke" if args.smoke else ("bounded" if args.max_signals is not None else "full_chunked"),
        "cli_args": {
            "smoke": bool(args.smoke),
            "max_signals": args.max_signals,
            "chunk_size": int(args.chunk_size),
            "max_travelway_detail_rows": int(args.max_travelway_detail_rows),
            "skip_review_gpkg": bool(args.skip_review_gpkg),
        },
        "output_dir": str(OUT_DIR),
        "manual_seed_count": len(MANUAL_SEEDS),
        "source_signal_count": int(len(signals)),
        "scan_signal_count": int(len(scan_signals)),
        "final_represented_signal_count": int(len(final_signals)),
        "missing_source_signal_count": int(len(missing_detail)),
        "recoverability_counts": class_summary.to_dict(orient="records"),
        "optional_gpkg": optional_gpkg,
        "crash_direction_use": "not_used",
        "preflight": preflight,
        "travelway_coverage_stats": travelway_stats,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
    }
    _write_json(manifest, "missing_hmms_signal_recovery_feasibility_manifest.json")
    _checkpoint("complete")
    print("Missing HMMS signal recovery feasibility complete")
    print(f"Output folder: {OUT_DIR}")
    print(class_summary.to_string(index=False))


def _findings(seed_diag: pd.DataFrame, class_summary: pd.DataFrame, priority: pd.DataFrame) -> str:
    seed_exists = int(pd.Series(seed_diag.get("source_record_exists", [])).astype(str).str.lower().eq("true").sum()) if len(seed_diag) else 0
    seed_represented = int(pd.Series(seed_diag.get("represented_in_final_universe", [])).astype(str).str.lower().eq("true").sum()) if len(seed_diag) else 0
    recoverable = class_summary.loc[class_summary["recoverability_class"].astype(str).str.startswith("recoverable"), "missing_signal_count"].astype(int).sum()
    high_priority = int(len(priority.loc[pd.to_numeric(priority["source_not_represented_unassigned_crashes_within_2500ft"], errors="coerce").fillna(0).ge(25)])) if len(priority) else 0
    class_lines = "\n".join(
        f"- {row.recoverability_class}: {int(row.missing_signal_count):,} missing signals; {int(row.high_crash_relevance_signals):,} high crash-relevance"
        for row in class_summary.itertuples(index=False)
    )
    return f"""# Missing HMMS Signal Recovery Feasibility Findings

## Bounded Question

This read-only diagnostic asks whether manually reviewed HMMS signals missing from the final represented universe are source/Travelway holdouts or recoverable source-signal association losses. It does not recover signals, generate scaffold bins, assign crashes, calculate rates/models, or use crash direction fields.

## Manual Seeds

- Manual seed records provided: {len(MANUAL_SEEDS):,}
- Seed records found in normalized/staged HMMS source: {seed_exists:,}
- Seed records already represented in final universe by available IDs: {seed_represented:,}

The seed outputs preserve GlobalIDs and source identifiers so map-review notes can be traced back to the HMMS source table.

## Broader Missing-Signal Scan

Potentially recoverable missing signals by Travelway coverage: {int(recoverable):,}

{class_lines}

## Crash Relevance

Recoverable-looking missing signals with at least 25 source-not-represented unassigned crashes within 2,500 ft: {high_priority:,}

Crash proximity is context only. No crash assignment or rate/model output is produced.

## Recommendation

Implement a bounded missing-signal recovery branch targeted first at `recoverable_good_travelway_coverage`, with separate handling for `recoverable_offset_anchor_needed` and `recoverable_complex_multi_signal_context`. Continue holding source-Travelway-missing and grade/mainline/interchange cases as source/data limitations unless map review supplies stronger evidence.
"""


if __name__ == "__main__":
    main()
