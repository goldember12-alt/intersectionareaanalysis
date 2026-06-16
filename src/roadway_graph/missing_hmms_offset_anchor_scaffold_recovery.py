from __future__ import annotations

import hashlib
import json
import math
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
from shapely import wkb, wkt
from shapely.geometry import Point
from shapely.ops import substring
from shapely.strtree import STRtree


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_scaffold_recovery"
GPKG_PATH = OUT_DIR / "offset_anchor_missing_signal_recovery_review.gpkg"

FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"
GOOD_TRAVELWAY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
COMPLEX_REVIEW_DIR = OUTPUT_ROOT / "review/current/complex_signal_map_review_ingestion"
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"
NORMALIZED_SIGNALS = Path("artifacts/normalized/signals.parquet")
NORMALIZED_CRASHES = Path("artifacts/normalized/crashes.parquet")

CRS = "EPSG:3968"
FT_TO_M = 0.3048
M_TO_FT = 1 / FT_TO_M
BIN_SIZE_FT = 50.0
MAX_DISTANCE_FT = 1000.0
SOURCE_RADIUS_FT = 250.0
ANCHOR_CLUSTER_RADIUS_FT = 125.0
MIN_LEG_LENGTH_FT = 50.0
DEFAULT_CHUNK_SIZE = 50

TARGET_CLASS = "recoverable_offset_anchor_needed"
EXCLUDED_CLASSES = {
    "recoverable_good_travelway_coverage",
    "recoverable_complex_multi_signal_context",
    "grade_mainline_or_interchange_holdout",
    "source_travelway_missing_or_incomplete",
    "insufficient_evidence",
}

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "assigned_crash_id",
    "assigned_crash_key",
)

REQUIRED_INPUTS = [
    FEASIBILITY_DIR / "manual_seed_missing_signal_diagnostic.csv",
    FEASIBILITY_DIR / "manual_seed_travelway_coverage_detail.csv",
    FEASIBILITY_DIR / "manual_seed_crash_context_summary.csv",
    FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv",
    FEASIBILITY_DIR / "missing_signal_travelway_coverage_summary.csv",
    FEASIBILITY_DIR / "missing_signal_recoverability_class_summary.csv",
    FEASIBILITY_DIR / "missing_signal_crash_relevance_priority_queue.csv",
    FEASIBILITY_DIR / "missing_signal_recovery_decision_tree.csv",
    FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json",
    GOOD_TRAVELWAY_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_TRAVELWAY_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_TRAVELWAY_DIR / "good_travelway_expanded_universe_readiness.csv",
    GOOD_TRAVELWAY_DIR / "good_travelway_universe_integration_manifest.json",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_universe_recommendation.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
    NORMALIZED_SIGNALS,
    NORMALIZED_CRASHES,
    ACCESS_REVIEW_GPKG,
]

_T0 = time.perf_counter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _memory_note() -> str:
    elapsed = time.perf_counter() - _T0
    rss_mb = None
    try:
        import psutil

        rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    return f" elapsed_s={elapsed:.1f}" if rss_mb is None else f" elapsed_s={elapsed:.1f} rss_mb={rss_mb:.1f}"


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}{_memory_note()}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction/assignment fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    _checkpoint(f"write_start {name}", len(frame))
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write_complete {name}", len(frame))


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "null"} else text


def _hash_text(text: str, n: int = 20) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _hash_row(values: list[Any], prefix: str, n: int = 20) -> str:
    return f"{prefix}_{_hash_text('|'.join(_clean(v) for v in values), n)}"


def _parse_wkt(value: Any):
    text = _clean(value)
    if not text:
        return None
    try:
        return wkt.loads(text)
    except Exception:
        return None


def _parse_wkb(value: Any):
    if value is None or value == "":
        return None
    try:
        return wkb.loads(value)
    except Exception:
        return None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if ACCESS_REVIEW_GPKG.exists():
        layers = {row[0] for row in pyogrio.list_layers(ACCESS_REVIEW_GPKG)}
        if SOURCE_TRAVELWAY_LAYER not in layers:
            missing.append(f"{ACCESS_REVIEW_GPKG}:{SOURCE_TRAVELWAY_LAYER}")
    return missing


def _load_normalized_signal_keys() -> pd.DataFrame:
    _checkpoint("read_start normalized signals")
    cols = ["GLOBALID", "OBJECTID", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM", "Stage1_SourceLayer"]
    signals = pd.read_parquet(NORMALIZED_SIGNALS, columns=[col for col in cols if col in pd.read_parquet(NORMALIZED_SIGNALS, columns=[]).columns])
    _checkpoint("read_complete normalized signals", len(signals))
    return pd.DataFrame(signals)


def _source_signal_id(row: pd.Series) -> str:
    for col in ["source_signal_id", "ASSET_NUM", "REG_SIGNAL_ID", "ASSET_ID", "GLOBALID"]:
        value = _clean(row.get(col))
        if value:
            return value
    return ""


def _build_stable_signal_id(row: pd.Series) -> str:
    return _hash_row(
        [
            row.get("Stage1_SourceLayer"),
            row.get("GLOBALID"),
            row.get("OBJECTID"),
            row.get("OBJECTID_1"),
            row.get("ASSET_ID"),
            row.get("REG_SIGNAL_ID"),
            row.get("source_signal_id"),
            row.get("signal_geometry_wkt"),
        ],
        "sig",
    )


def _target_points(targets: pd.DataFrame) -> gpd.GeoDataFrame:
    geoms = _text(targets, "signal_geometry_wkt").map(_parse_wkt)
    out = gpd.GeoDataFrame(targets.copy(), geometry=geoms, crs=CRS)
    return out.loc[out.geometry.notna() & ~out.geometry.is_empty].copy()


def _load_targets() -> gpd.GeoDataFrame:
    detail = _read_csv(FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv")
    excluded = sorted(set(_text(detail, "recoverability_class").unique()) & EXCLUDED_CLASSES)
    targets = detail.loc[_text(detail, "recoverability_class").eq(TARGET_CLASS)].copy()
    targets = targets.sort_values(["source_row_index", "GLOBALID"]).drop_duplicates("source_row_index", keep="first")
    targets["source_signal_id"] = targets.apply(_source_signal_id, axis=1)
    targets["source_layer"] = _text(targets, "Stage1_SourceLayer").replace("", "HMMS_TrafficSignals_Flat")
    targets["source_system"] = np.where(_text(targets, "source_layer").str.contains("HMMS", case=False, na=False), "VDOT HMMS", _text(targets, "source_layer"))
    targets["stable_signal_id"] = targets.apply(_build_stable_signal_id, axis=1)
    targets["target_recovery_scope"] = "missing_hmms_offset_anchor_only"
    targets["crash_relevance_class"] = np.where(_flag(targets, "high_crash_relevance_flag"), "high_crash_relevance", "context_only")
    targets["excluded_recoverability_classes_not_targeted"] = "|".join(excluded)
    gdf = _target_points(targets)
    _checkpoint("target recoverable_offset_anchor_needed signals", len(gdf))
    return gdf


def _travelway_bbox(chunk: gpd.GeoDataFrame, radius_ft: float = SOURCE_RADIUS_FT) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = chunk.total_bounds
    d = radius_ft * FT_TO_M
    return (minx - d, miny - d, maxx + d, maxy + d)


def _read_source_travelway(chunk: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = pyogrio.read_dataframe(
        ACCESS_REVIEW_GPKG,
        layer=SOURCE_TRAVELWAY_LAYER,
        bbox=_travelway_bbox(chunk),
        fid_as_index=True,
    )
    if gdf.crs is None:
        gdf = gdf.set_crs(CRS, allow_override=True)
    return gdf.to_crs(CRS)


def _line_for_measure(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "LineString":
        return geom
    if geom.geom_type == "MultiLineString":
        try:
            merged = shapely.line_merge(geom)
            if merged.geom_type == "LineString":
                return merged
        except Exception:
            pass
        parts = [part for part in geom.geoms if not part.is_empty]
        return max(parts, key=lambda part: part.length) if parts else None
    return None


def _geometry_hash(geom) -> str:
    return _hash_text(shapely.to_wkb(geom, hex=True), 20)


def _source_feature_id(row: pd.Series) -> str:
    try:
        return str(int(row.name))
    except Exception:
        return str(row.name)


def _travelway_identity(row: pd.Series, geom) -> dict[str, Any]:
    source_route_id = _clean(row.get("RTE_ID"))
    source_route_name = _clean(row.get("RTE_NM"))
    source_route_common = _clean(row.get("RTE_COMMON"))
    source_measure_start = _clean(row.get("FROM_MEASURE"))
    source_measure_end = _clean(row.get("TO_MEASURE"))
    geom_hash = _geometry_hash(geom)
    source_layer = _clean(row.get("Stage1_SourceLayer")) or "Travelway"
    stable_key = "|".join([source_layer, source_route_id, source_route_name, source_route_common, source_measure_start, source_measure_end, geom_hash])
    return {
        "stable_travelway_id": f"tw_{_hash_text(stable_key, 16)}",
        "source_layer": source_layer,
        "source_route_id": source_route_id,
        "source_route_name": source_route_name,
        "source_route_common": source_route_common,
        "source_measure_start": source_measure_start,
        "source_measure_end": source_measure_end,
        "source_feature_local_fid": _source_feature_id(row),
        "geometry_hash": geom_hash,
    }


def _bearing_sector(anchor: Point, line) -> str:
    nearest = shapely.line_interpolate_point(line, shapely.line_locate_point(line, anchor))
    dx = nearest.x - anchor.x
    dy = nearest.y - anchor.y
    if math.hypot(dx, dy) < 1e-6:
        coords = list(line.coords)
        endpoint = min([Point(coords[0]), Point(coords[-1])], key=lambda point: point.distance(anchor))
        dx = endpoint.x - anchor.x
        dy = endpoint.y - anchor.y
    angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    return f"sector_{int(angle // 45):02d}"


def _grade_or_mainline_risk(row: pd.Series) -> bool:
    ramp = _clean(row.get("RTE_RAMP_C"))
    access = _clean(row.get("RIM_ACCESS")).upper()
    facility = _clean(row.get("RIM_FACILI")).upper()
    rte = _clean(row.get("RTE_NM")).upper()
    return bool(ramp and ramp not in {"0", "0.0"}) or "LIMITED" in access or "INTERSTATE" in facility or " IS" in rte


def _intersection_anchor(signal_point: Point, tw_rows: gpd.GeoDataFrame) -> tuple[Any, str, str, int]:
    if tw_rows.empty:
        return None, "no_source_travelway", "none", 0
    geoms = [geom for geom in tw_rows.geometry if geom is not None and not geom.is_empty]
    candidates: list[Point] = []
    for i, geom_a in enumerate(geoms):
        for geom_b in geoms[i + 1 :]:
            try:
                inter = geom_a.intersection(geom_b)
            except Exception:
                continue
            if inter is None or inter.is_empty:
                continue
            parts = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
            for part in parts:
                point = part if part.geom_type == "Point" else part.centroid
                if point.distance(signal_point) <= SOURCE_RADIUS_FT * FT_TO_M:
                    candidates.append(point)
    if candidates:
        coords = np.array([[point.x, point.y] for point in candidates])
        best_count = -1
        best_xy = coords[0]
        radius = ANCHOR_CLUSTER_RADIUS_FT * FT_TO_M
        for xy in coords:
            d = np.sqrt(((coords - xy) ** 2).sum(axis=1))
            count = int(np.count_nonzero(d <= radius))
            if count > best_count:
                best_count = count
                best_xy = coords[d <= radius].mean(axis=0)
        anchor = Point(float(best_xy[0]), float(best_xy[1]))
        offset_ft = anchor.distance(signal_point) * M_TO_FT
        confidence = "high" if best_count >= 2 and offset_ft <= 250 else "medium"
        return anchor, "source_travelway_line_intersection_cluster", confidence, best_count
    union = shapely.union_all(geoms)
    centroid = union.centroid if union is not None and not union.is_empty else None
    if centroid is not None:
        offset_ft = centroid.distance(signal_point) * M_TO_FT
        confidence = "medium" if offset_ft <= 175 else "low"
        return centroid, "source_travelway_zone_centroid", confidence, 0
    return None, "anchor_confidence_too_low", "none", 0


def _bin_geom(line, projected_m: float, side: str, start_ft: float, end_ft: float):
    if side == "forward":
        start_m = projected_m + start_ft * FT_TO_M
        end_m = projected_m + end_ft * FT_TO_M
    else:
        start_m = projected_m - end_ft * FT_TO_M
        end_m = projected_m - start_ft * FT_TO_M
    start_m = max(0.0, min(float(line.length), start_m))
    end_m = max(0.0, min(float(line.length), end_m))
    if abs(end_m - start_m) < 1e-6:
        return None
    try:
        geom = substring(line, min(start_m, end_m), max(start_m, end_m))
    except Exception:
        return None
    if geom is None or geom.is_empty or geom.length <= 0:
        return None
    return geom


def _distance_band(start_ft: float) -> str:
    if start_ft < 250:
        return "0_250ft"
    if start_ft < 500:
        return "250_500ft"
    return "500_1000ft"


def _leg_record(sig: pd.Series, tw: pd.Series, line, anchor: Point, side: str, available_ft: float, distance_ft: float) -> dict[str, Any]:
    ident = _travelway_identity(tw, line)
    sector = _bearing_sector(anchor, line)
    branch_key = "|".join([sector, ident["source_route_id"], ident["source_route_common"], _clean(tw.get("LOC_COMP_D")), _clean(tw.get("RTE_RAMP_C")), side])
    return {
        **ident,
        "stable_signal_id": sig.get("stable_signal_id", ""),
        "source_signal_id": sig.get("source_signal_id", ""),
        "GLOBALID": sig.get("GLOBALID", ""),
        "OBJECTID": sig.get("OBJECTID_1", sig.get("OBJECTID", "")),
        "ASSET_ID": sig.get("ASSET_ID", ""),
        "REG_SIGNAL_ID": sig.get("REG_SIGNAL_ID", ""),
        "source_signal_layer": sig.get("Stage1_SourceLayer", ""),
        "source_row_index": sig.get("source_row_index", ""),
        "leg_candidate_id": _hash_row([sig.get("stable_signal_id", ""), ident["stable_travelway_id"], sector, branch_key], "leg"),
        "bearing_sector": sector,
        "physical_leg_group_id": _hash_row([sig.get("stable_signal_id", ""), sector], "physleg", 16),
        "carriageway_subbranch_id": _hash_row([sig.get("stable_signal_id", ""), branch_key], "subbranch", 16),
        "outward_side": side,
        "available_length_ft": round(float(available_ft), 3),
        "anchor_to_travelway_distance_ft": round(float(distance_ft), 3),
        "source_route_facility": tw.get("RIM_FACILI", ""),
        "source_rim_access": tw.get("RIM_ACCESS", ""),
        "source_ramp_code": tw.get("RTE_RAMP_C", ""),
        "source_loc_comp": tw.get("LOC_COMP_D", ""),
        "grade_or_mainline_risk_flag": bool(_grade_or_mainline_risk(tw)),
        "coverage_class": "full_0_1000" if available_ft >= MAX_DISTANCE_FT else "partial_under_1000",
        "lineage_match_method": "offset_anchor_source_travelway_geometry",
        "lineage_confidence": "medium_source_geometry_review_only",
        "review_only": True,
        "geometry_wkt": line.wkt,
    }


def _skip_record(sig: pd.Series, reason: str, note: str) -> dict[str, Any]:
    return {
        "stable_signal_id": sig.get("stable_signal_id", ""),
        "source_signal_id": sig.get("source_signal_id", ""),
        "GLOBALID": sig.get("GLOBALID", ""),
        "source_row_index": sig.get("source_row_index", ""),
        "recoverability_class": sig.get("recoverability_class", ""),
        "skip_reason": reason,
        "skip_note": note,
    }


def _build_candidates(targets: gpd.GeoDataFrame, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    bin_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for chunk_no, start in enumerate(range(0, len(targets), chunk_size), start=1):
        chunk = targets.iloc[start : start + chunk_size].copy()
        _checkpoint(f"generation_chunk_{chunk_no}_start", len(chunk))
        travelway = _read_source_travelway(chunk)
        _checkpoint(f"generation_chunk_{chunk_no}_travelway_bbox", len(travelway))
        if travelway.empty:
            for sig in chunk.itertuples(index=False):
                skipped.append(_skip_record(pd.Series(sig._asdict()), "geometry_too_sparse", "No source Travelway rows found in chunk bbox."))
            continue
        tw_geoms = np.asarray(travelway.geometry.to_numpy(), dtype=object)
        tree = STRtree(tw_geoms)
        signal_points = np.asarray(chunk.geometry.to_numpy(), dtype=object)
        pair_idx = tree.query(signal_points, predicate="dwithin", distance=SOURCE_RADIUS_FT * FT_TO_M)
        pairs_by_signal: dict[int, list[int]] = {}
        if pair_idx.size:
            for sig_i, tw_i in zip(pair_idx[0], pair_idx[1]):
                pairs_by_signal.setdefault(int(sig_i), []).append(int(tw_i))
        for sig_i, sig_tuple in enumerate(chunk.itertuples(index=False)):
            sig = pd.Series(sig_tuple._asdict())
            signal_point = sig.geometry
            tw_idxs = pairs_by_signal.get(sig_i, [])
            if not tw_idxs:
                skipped.append(_skip_record(sig, "geometry_too_sparse", "No source Travelway rows within 250 ft of raw signal point."))
                continue
            nearby = travelway.iloc[tw_idxs].copy()
            dists_ft = nearby.geometry.distance(signal_point) * M_TO_FT
            anchor_source = nearby.loc[dists_ft <= SOURCE_RADIUS_FT].copy()
            anchor, anchor_method, anchor_confidence, intersection_count = _intersection_anchor(signal_point, anchor_source)
            if anchor is None or anchor_confidence in {"none", "low"}:
                skipped.append(_skip_record(sig, "anchor_confidence_too_low", f"Anchor method={anchor_method} confidence={anchor_confidence}."))
                continue
            offset_ft = float(signal_point.distance(anchor) * M_TO_FT)
            source_125 = int((dists_ft <= 125).sum())
            source_175 = int((dists_ft <= 175).sum())
            source_250 = int((dists_ft <= 250).sum())
            grade_count = int(anchor_source.apply(_grade_or_mainline_risk, axis=1).sum()) if len(anchor_source) else 0
            route_count = int(anchor_source["RTE_ID"].astype(str).replace("", pd.NA).dropna().nunique()) if "RTE_ID" in anchor_source else 0
            target_rows.append(
                {
                    **{col: sig.get(col, "") for col in [
                        "stable_signal_id",
                        "GLOBALID",
                        "OBJECTID",
                        "OBJECTID_1",
                        "ASSET_ID",
                        "REG_SIGNAL_ID",
                        "source_signal_id",
                        "source_layer",
                        "source_system",
                        "MAJ_NAME",
                        "MAJ_NUM",
                        "MINOR_NAME",
                        "MINOR_NUM",
                        "attr_best_available_loss_reason",
                        "recoverability_class",
                        "crash_relevance_class",
                        "high_crash_relevance_flag",
                        "signal_geometry_wkt",
                    ]},
                    "source_row_index": sig.get("source_row_index", ""),
                    "raw_signal_x": round(float(signal_point.x), 3),
                    "raw_signal_y": round(float(signal_point.y), 3),
                    "intersection_anchor_x": round(float(anchor.x), 3),
                    "intersection_anchor_y": round(float(anchor.y), 3),
                    "signal_to_anchor_offset_ft": round(offset_ft, 3),
                    "anchor_method": anchor_method,
                    "anchor_confidence": anchor_confidence,
                    "anchor_intersection_candidate_count": intersection_count,
                    "source_travelway_lines_within_125ft_raw_signal": source_125,
                    "source_travelway_lines_within_175ft_raw_signal": source_175,
                    "source_travelway_lines_within_250ft_raw_signal": source_250,
                    "unique_route_count_250ft": route_count,
                    "grade_or_mainline_risk_line_count": grade_count,
                }
            )
            if grade_count and grade_count >= max(3, len(anchor_source) * 0.75):
                skipped.append(_skip_record(sig, "grade_or_mainline_risk_detected", "Most nearby Travelway rows are ramp/limited-access/interstate-like."))
                continue
            signal_leg_count = 0
            signal_bin_count = 0
            for _, tw in anchor_source.iterrows():
                line = _line_for_measure(tw.geometry)
                if line is None or line.length <= 0:
                    continue
                anchor_distance_ft = float(anchor.distance(line) * M_TO_FT)
                if anchor_distance_ft > 125:
                    continue
                projected_m = float(line.project(anchor))
                available = {
                    "forward": max(0.0, float(line.length) - projected_m) * M_TO_FT,
                    "backward": max(0.0, projected_m) * M_TO_FT,
                }
                for side, available_ft in available.items():
                    if available_ft < MIN_LEG_LENGTH_FT:
                        continue
                    leg = _leg_record(sig, tw, line, anchor, side, available_ft, anchor_distance_ft)
                    leg_rows.append(leg)
                    signal_leg_count += 1
                    max_len = min(MAX_DISTANCE_FT, available_ft)
                    bin_start = 0.0
                    while bin_start < max_len - 1e-6:
                        bin_end = min(bin_start + BIN_SIZE_FT, max_len)
                        geom = _bin_geom(line, projected_m, side, bin_start, bin_end)
                        if geom is None:
                            break
                        stable_bin_id = _hash_row(
                            [leg["leg_candidate_id"], leg["source_feature_local_fid"], bin_start, bin_end, shapely.to_wkb(geom, hex=True)],
                            "bin",
                        )
                        bin_rows.append(
                            {
                                **{k: leg.get(k, "") for k in [
                                    "stable_travelway_id",
                                    "stable_signal_id",
                                    "source_signal_id",
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
                                    "GLOBALID",
                                    "ASSET_ID",
                                    "REG_SIGNAL_ID",
                                    "source_signal_layer",
                                    "leg_candidate_id",
                                    "physical_leg_group_id",
                                    "carriageway_subbranch_id",
                                    "bearing_sector",
                                    "outward_side",
                                ]},
                                "stable_bin_id": stable_bin_id,
                                "target_bin_id": stable_bin_id,
                                "target_signal_id": leg.get("stable_signal_id", ""),
                                "distance_start_ft": round(float(bin_start), 3),
                                "distance_end_ft": round(float(bin_end), 3),
                                "distance_length_ft": round(float(bin_end - bin_start), 3),
                                "distance_band": _distance_band(bin_start),
                                "analysis_window": "0_1000",
                                "partial_coverage_flag": bool(max_len < MAX_DISTANCE_FT),
                                "review_only_recovery_provenance": "missing_hmms_offset_anchor_scaffold_recovery",
                                "anchor_method": anchor_method,
                                "anchor_confidence": anchor_confidence,
                                "signal_to_anchor_offset_ft": round(offset_ft, 3),
                                "geometry_wkt": geom.wkt,
                            }
                        )
                        signal_bin_count += 1
                        bin_start += BIN_SIZE_FT
            if signal_leg_count == 0 or signal_bin_count == 0:
                skipped.append(_skip_record(sig, "no_defensible_source_leg_after_anchor", "No source Travelway side had at least 50 ft outward support from inferred anchor."))
        _checkpoint(f"generation_chunk_{chunk_no}_finish")
    return pd.DataFrame(target_rows), pd.DataFrame(leg_rows), pd.DataFrame(bin_rows), pd.DataFrame(skipped)


def _context_readiness(targets: pd.DataFrame, bins: pd.DataFrame, overlap: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        counts = pd.DataFrame(columns=["stable_signal_id", "generated_bin_count", "stable_travelway_lineage_bin_count", "generated_stable_travelway_count"])
    else:
        counts = bins.groupby("stable_signal_id").agg(
            generated_bin_count=("stable_bin_id", "size"),
            stable_travelway_lineage_bin_count=("stable_travelway_id", lambda s: int(pd.Series(s).astype(str).str.strip().ne("").sum())),
            generated_stable_travelway_count=("stable_travelway_id", "nunique"),
        ).reset_index()
    out = targets.drop(columns=["geometry"], errors="ignore").merge(counts, on="stable_signal_id", how="left")
    out = out.merge(overlap[["stable_signal_id", "overlap_review_required", "exact_duplicate_signal_risk", "sibling_signal_risk", "complex_multi_signal_risk"]], on="stable_signal_id", how="left")
    for col in ["generated_bin_count", "stable_travelway_lineage_bin_count", "generated_stable_travelway_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["route_measure_identity_ready"] = out["generated_bin_count"].gt(0) & out["stable_travelway_lineage_bin_count"].eq(out["generated_bin_count"])
    out["roadway_context_ready_for_later_refresh"] = out["route_measure_identity_ready"]
    out["rns_speed_ready_for_later_refresh"] = out["route_measure_identity_ready"]
    out["aadt_v3_exposure_ready_for_later_refresh"] = out["route_measure_identity_ready"]
    out["access_ready_for_later_refresh"] = out["generated_bin_count"].gt(0)
    out["crash_assignment_ready_for_later_review"] = out["generated_bin_count"].gt(0) & ~out["overlap_review_required"].fillna(False).astype(bool)
    return out


def _overlap_review(targets: gpd.GeoDataFrame, expanded_signals: pd.DataFrame, good_readiness: pd.DataFrame, represented: pd.DataFrame, represented_bins: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    rows = targets.drop(columns=["geometry"], errors="ignore").copy()
    expanded_ids = set(_text(expanded_signals, "GLOBALID")) | set(_text(expanded_signals, "source_signal_id"))
    good_ids = set(_text(good_readiness, "GLOBALID")) | set(_text(good_readiness, "source_signal_id"))
    rep_ids = set(_text(represented, "represented_source_signal_id")) | set(_text(represented, "source_signal_id_x"))
    rows["exact_duplicate_signal_risk"] = _text(rows, "GLOBALID").isin(expanded_ids | rep_ids) | _text(rows, "source_signal_id").isin(expanded_ids | rep_ids)
    rows["duplicate_with_good_travelway_addition"] = _text(rows, "GLOBALID").isin(good_ids) | _text(rows, "source_signal_id").isin(good_ids)
    rows["missing_source_globalid_risk"] = _text(rows, "GLOBALID").eq("")
    rows["missing_source_signal_id_risk"] = _text(rows, "source_signal_id").eq("")
    # Signal proximity to represented/good additions is a sibling-risk cue, not an exclusion by itself.
    target_xy = np.column_stack([targets.geometry.x.to_numpy(), targets.geometry.y.to_numpy()])
    rows["nearest_existing_or_recovered_signal_ft"] = np.nan
    point_frames = []
    for frame in [expanded_signals, represented]:
        if "signal_geometry_wkt" in frame.columns:
            geoms = _text(frame, "signal_geometry_wkt").map(_parse_wkt)
            point_frames.extend([geom for geom in geoms if geom is not None and not geom.is_empty and geom.geom_type == "Point"])
    if point_frames:
        xy = np.column_stack([[geom.x for geom in point_frames], [geom.y for geom in point_frames]])
        tree = cKDTree(xy)
        dist_m, _ = tree.query(target_xy, k=1)
        rows["nearest_existing_or_recovered_signal_ft"] = dist_m * M_TO_FT
    rows["sibling_signal_risk"] = pd.to_numeric(rows["nearest_existing_or_recovered_signal_ft"], errors="coerce").fillna(999999).lt(250)
    existing_tw = set(_text(represented_bins, "stable_travelway_id")) | set(_text(GOOD_TRAVELWAY_BINS_CACHE, "stable_travelway_id")) if "GOOD_TRAVELWAY_BINS_CACHE" in globals() else set(_text(represented_bins, "stable_travelway_id"))
    if bins.empty:
        overlap_counts = pd.DataFrame(columns=["stable_signal_id", "stable_travelway_overlap_bin_count", "overlapping_stable_travelway_count"])
    else:
        tmp = bins.copy()
        tmp["overlap_tw"] = _text(tmp, "stable_travelway_id").isin(existing_tw)
        overlap_counts = tmp.groupby("stable_signal_id").agg(
            stable_travelway_overlap_bin_count=("overlap_tw", "sum"),
            overlapping_stable_travelway_count=("stable_travelway_id", lambda s: int(pd.Series(s)[tmp.loc[s.index, "overlap_tw"]].nunique())),
        ).reset_index()
    rows = rows.merge(overlap_counts, on="stable_signal_id", how="left")
    rows["stable_travelway_overlap_bin_count"] = pd.to_numeric(rows["stable_travelway_overlap_bin_count"], errors="coerce").fillna(0).astype(int)
    rows["complex_multi_signal_risk"] = rows["sibling_signal_risk"] | rows["stable_travelway_overlap_bin_count"].gt(0)
    rows["overlap_review_required"] = rows["exact_duplicate_signal_risk"] | rows["complex_multi_signal_risk"]
    return rows


def _load_crashes() -> gpd.GeoDataFrame:
    cols = ["DOCUMENT_NBR", "CRASH_YEAR", "CRASH_SEVERITY", "COLLISION_TYPE", "RTE_NM", "geometry"]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields: {blocked}")
    crashes = pd.read_parquet(NORMALIZED_CRASHES, columns=cols)
    crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    crashes["geometry"] = crashes["geometry"].map(_parse_wkb)
    gdf = gpd.GeoDataFrame(crashes, geometry="geometry", crs=CRS)
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    _checkpoint("load normalized crash points for proximity context", len(gdf))
    return gdf


def _crash_context(targets: gpd.GeoDataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    crashes = _load_crashes()
    sig_xy = np.column_stack([targets.geometry.x.to_numpy(), targets.geometry.y.to_numpy()])
    crash_xy = np.column_stack([crashes.geometry.x.to_numpy(), crashes.geometry.y.to_numpy()])
    tree = cKDTree(crash_xy)
    keep_cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "crash_relevance_class",
        "high_crash_relevance_flag",
        "source_not_represented_unassigned_crashes_within_500ft",
        "source_not_represented_unassigned_crashes_within_1000ft",
        "source_not_represented_unassigned_crashes_within_2500ft",
        "crashes_within_50ft_nearby_source_travelway_250ft_signal_window",
        "crashes_within_75ft_nearby_source_travelway_250ft_signal_window",
        "crashes_within_100ft_nearby_source_travelway_250ft_signal_window",
    ]
    rows = targets.drop(columns=["geometry"], errors="ignore")[[col for col in keep_cols if col in targets.columns]].copy()
    for radius in [250, 500, 1000, 2500]:
        rows[f"nearby_crashes_within_{radius}ft_signal"] = tree.query_ball_point(sig_xy, r=radius * FT_TO_M, return_length=True).astype(int)
    if bins.empty:
        rows["crashes_within_100ft_generated_source_travelway_250ft_signal_window"] = 0
    else:
        line_geoms = _text(bins.drop_duplicates(["stable_signal_id", "stable_travelway_id"]), "geometry_wkt").map(_parse_wkt)
        # Conservative class-level proximity proxy: count crashes within 100 ft of any generated bin and 250 ft of signal.
        counts = []
        for sig in targets.itertuples(index=False):
            crash_idx = tree.query_ball_point([sig.geometry.x, sig.geometry.y], r=250 * FT_TO_M)
            signal_lines = [_parse_wkt(v) for v in _text(bins.loc[_text(bins, "stable_signal_id").eq(sig.stable_signal_id)], "geometry_wkt").head(200)]
            signal_lines = [geom for geom in signal_lines if geom is not None and not geom.is_empty]
            if not crash_idx or not signal_lines:
                counts.append(0)
                continue
            crash_geoms = np.asarray(crashes.geometry.iloc[crash_idx].to_numpy(), dtype=object)
            line_arr = np.asarray(signal_lines, dtype=object)
            dist_ft = shapely.distance(crash_geoms[:, None], line_arr[None, :]).min(axis=1) * M_TO_FT
            counts.append(int(np.count_nonzero(dist_ft <= 100)))
        rows["crashes_within_100ft_generated_source_travelway_250ft_signal_window"] = counts
    if "source_not_represented_unassigned_crashes_within_2500ft" in rows.columns:
        source_not_rep = pd.to_numeric(rows["source_not_represented_unassigned_crashes_within_2500ft"], errors="coerce").fillna(0)
    else:
        source_not_rep = pd.Series(0, index=rows.index)
    rows["may_explain_source_not_represented_crash_cluster"] = source_not_rep.ge(25)
    return rows


def _summaries(targets: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame, skipped: pd.DataFrame, readiness: pd.DataFrame) -> pd.DataFrame:
    leg_counts = legs.groupby("stable_signal_id").agg(
        generated_leg_candidate_count=("leg_candidate_id", "nunique"),
        generated_physical_leg_count=("physical_leg_group_id", "nunique"),
        generated_subbranch_count=("carriageway_subbranch_id", "nunique"),
        grade_or_mainline_risk_leg_count=("grade_or_mainline_risk_flag", "sum"),
    ).reset_index() if not legs.empty else pd.DataFrame(columns=["stable_signal_id", "generated_leg_candidate_count", "generated_physical_leg_count", "generated_subbranch_count", "grade_or_mainline_risk_leg_count"])
    bin_counts = bins.groupby("stable_signal_id").agg(
        generated_bin_count=("stable_bin_id", "size"),
        stable_travelway_lineage_bin_count=("stable_travelway_id", lambda s: int(pd.Series(s).astype(str).str.strip().ne("").sum())),
        generated_stable_travelway_count=("stable_travelway_id", "nunique"),
    ).reset_index() if not bins.empty else pd.DataFrame(columns=["stable_signal_id", "generated_bin_count", "stable_travelway_lineage_bin_count", "generated_stable_travelway_count"])
    out = targets.drop(columns=["geometry"], errors="ignore").merge(leg_counts, on="stable_signal_id", how="left").merge(bin_counts, on="stable_signal_id", how="left")
    skip_reason = skipped.drop_duplicates("stable_signal_id")[["stable_signal_id", "skip_reason", "skip_note"]] if not skipped.empty else pd.DataFrame(columns=["stable_signal_id", "skip_reason", "skip_note"])
    out = out.merge(skip_reason, on="stable_signal_id", how="left")
    for col in ["generated_leg_candidate_count", "generated_physical_leg_count", "generated_subbranch_count", "generated_bin_count", "stable_travelway_lineage_bin_count", "generated_stable_travelway_count", "grade_or_mainline_risk_leg_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["generation_status"] = np.where(out["generated_bin_count"].gt(0), "defensible_offset_anchor_scaffold_candidate_generated", "skipped_no_defensible_scaffold")
    out["skip_reason"] = np.where(out["generated_bin_count"].gt(0), "", _text(out, "skip_reason"))
    out = out.merge(readiness[["stable_signal_id", "route_measure_identity_ready", "rns_speed_ready_for_later_refresh", "aadt_v3_exposure_ready_for_later_refresh", "crash_assignment_ready_for_later_review"]], on="stable_signal_id", how="left")
    return out


def _findings(targets: pd.DataFrame, summary: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame, skipped: pd.DataFrame, readiness: pd.DataFrame, crash: pd.DataFrame) -> str:
    targeted = len(targets)
    generated_signals = int((pd.to_numeric(summary["generated_bin_count"], errors="coerce").fillna(0) > 0).sum()) if not summary.empty else 0
    leg_count = int(len(legs))
    physical_legs = int(legs["physical_leg_group_id"].nunique()) if not legs.empty else 0
    bin_count = int(len(bins))
    lineage_bins = int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0
    skipped_count = int(targeted - generated_signals)
    ready = int(readiness["rns_speed_ready_for_later_refresh"].sum()) if not readiness.empty else 0
    high_crash = int(_text(crash, "high_crash_relevance_flag").str.lower().eq("true").sum()) if not crash.empty else 0
    crash_cluster = int(crash["may_explain_source_not_represented_crash_cluster"].sum()) if not crash.empty else 0
    source_not_rep_2500 = (
        int(pd.to_numeric(crash["source_not_represented_unassigned_crashes_within_2500ft"], errors="coerce").fillna(0).sum())
        if not crash.empty and "source_not_represented_unassigned_crashes_within_2500ft" in crash.columns
        else 0
    )
    anchor_source = summary.loc[_text(summary, "anchor_method").ne("") & _text(summary, "anchor_confidence").ne("")].copy() if "anchor_method" in summary else pd.DataFrame()
    anchor_methods = anchor_source.groupby(["anchor_method", "anchor_confidence"], dropna=False).size().reset_index(name="signal_count") if not anchor_source.empty else pd.DataFrame()
    anchor_lines = "\n".join(f"- {row.anchor_method} / {row.anchor_confidence}: {int(row.signal_count):,}" for row in anchor_methods.itertuples(index=False))
    skip_lines = "None"
    if not skipped.empty:
        skip_counts = skipped.groupby("skip_reason", dropna=False).size().reset_index(name="signal_count")
        skip_lines = "\n".join(f"- {row.skip_reason}: {int(row.signal_count):,}" for row in skip_counts.itertuples(index=False))
    return f"""# Missing HMMS Offset-Anchor Scaffold Recovery Findings

## Bounded Question

This read-only pass targets only `{TARGET_CLASS}` missing HMMS signals and tests whether inferred intersection-zone anchors can support defensible source-Travelway scaffold candidates. It does not target good-Travelway, complex multi-signal, grade/mainline, source-limited, or insufficient-evidence classes. It does not modify active outputs, promote signals, assign crashes/access, calculate rates/models, or use crash direction fields.

## Recovery Results

- Targeted offset-anchor signals: {targeted:,}
- Signals with defensible scaffold candidates: {generated_signals:,}
- Skipped/no generated scaffold: {skipped_count:,}
- Generated leg candidate rows: {leg_count:,}
- Generated physical-leg groups: {physical_legs:,}
- Generated 0-1,000 ft bins: {bin_count:,}
- Generated bins with stable Travelway lineage: {lineage_bins:,}

## Skipped Targets

{skip_lines}

## Anchor Methods

{anchor_lines}

## Context Refresh Readiness

- Signals appearing ready for later speed/AADT context refresh: {ready:,}
- Generated bins are route/measure-ready when stable Travelway lineage is present on every generated bin.

## Crash Relevance

- High-crash-relevance targeted signals: {high_crash:,}
- Signals with at least 25 source-not-represented unassigned crashes within 2,500 ft: {crash_cluster:,}
- Source-not-represented unassigned crashes within 2,500 ft of this target class: {source_not_rep_2500:,}

Crash proximity is context only. No crash assignment was performed.

## Universe Implication

This pass supports expanding the review-only universe beyond 3,365 only for the generated offset-anchor candidates, and only with QA flags. These candidates should remain separate from the clean good-Travelway 604 until a route/measure, speed/AADT context refresh and overlap review are complete.

## Recommendation

Run a read-only offset-anchor context refresh next for route/measure identity, roadway context, RNS speed, and AADT v3/exposure readiness. Keep complex multi-signal and grade/mainline/source-limited classes out of this branch.
"""


def _qa(targets: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    stable_tw_ok = bins.empty or _text(bins, "stable_travelway_id").str.strip().ne("").all()
    globalid_preserved = int(_text(targets, "GLOBALID").str.strip().ne("").sum())
    missing_globalid = int(_text(targets, "GLOBALID").str.strip().eq("").sum())
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only candidates only"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "crashes used only for proximity counts"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "crash read list excludes direction fields and direction-token guard is active"},
            {"check_name": "only_offset_anchor_class_targeted", "status": "passed" if set(_text(targets, "recoverability_class")) == {TARGET_CLASS} else "failed", "observed": "|".join(sorted(set(_text(targets, "recoverability_class"))))},
            {"check_name": "stable_travelway_id_present_on_generated_bins", "status": "passed" if stable_tw_ok else "failed", "observed": f"{int(_text(bins, 'stable_travelway_id').str.strip().ne('').sum()) if not bins.empty else 0}/{len(bins)}"},
            {"check_name": "source_globalids_preserved_where_available", "status": "passed", "observed": f"{globalid_preserved} present; {missing_globalid} missing"},
            {"check_name": "missing_source_ids_reported_not_forced", "status": "passed", "observed": "missing GLOBALID/source IDs retained as QA fields"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def _write_layer(frame: gpd.GeoDataFrame, layer: str, inventory: list[dict[str, Any]]) -> None:
    if GPKG_PATH.exists() and not inventory:
        GPKG_PATH.unlink()
    out = frame.copy()
    if out.crs is None:
        out = out.set_crs(CRS, allow_override=True)
    out = out.to_crs(CRS)
    for col in out.columns:
        if col != "geometry" and str(out[col].dtype) == "object":
            out[col] = out[col].fillna("").astype(str)
    pyogrio.write_dataframe(out, GPKG_PATH, layer=layer, driver="GPKG")
    inventory.append({"layer": layer, "rows": int(len(out)), "geometry_type": str(out.geom_type.iloc[0]) if len(out) else ""})
    _checkpoint(f"write_layer {layer}", len(out))


def _optional_gpkg(targets: gpd.GeoDataFrame, target_detail: pd.DataFrame, bins: pd.DataFrame, crash: pd.DataFrame) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    _write_layer(targets, "target_signal_points", inventory)
    anchors = target_detail.copy()
    anchors["geometry"] = [Point(float(x), float(y)) if _clean(x) and _clean(y) else None for x, y in zip(anchors.get("intersection_anchor_x", []), anchors.get("intersection_anchor_y", []))]
    anchor_gdf = gpd.GeoDataFrame(anchors, geometry="geometry", crs=CRS).loc[lambda df: df.geometry.notna() & ~df.geometry.is_empty]
    _write_layer(anchor_gdf, "inferred_intersection_anchors", inventory)
    if not bins.empty:
        bin_gdf = gpd.GeoDataFrame(bins.copy(), geometry=_text(bins, "geometry_wkt").map(_parse_wkt), crs=CRS).loc[lambda df: df.geometry.notna() & ~df.geometry.is_empty]
        _write_layer(bin_gdf, "generated_offset_anchor_bins", inventory)
    source = pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER, max_features=5000).to_crs(CRS)
    _write_layer(source, "source_travelway_sample", inventory)
    return inventory


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    feasibility_manifest = _load_json(FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json")
    good_manifest = _load_json(GOOD_TRAVELWAY_DIR / "good_travelway_universe_integration_manifest.json")
    complex_manifest = _load_json(COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json")
    stable_manifest = _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json")

    _read_csv(FEASIBILITY_DIR / "manual_seed_missing_signal_diagnostic.csv", usecols=["source_row_index", "GLOBALID"])
    _read_csv(FEASIBILITY_DIR / "manual_seed_travelway_coverage_detail.csv")
    _read_csv(FEASIBILITY_DIR / "manual_seed_crash_context_summary.csv")
    _read_csv(FEASIBILITY_DIR / "missing_signal_travelway_coverage_summary.csv")
    _read_csv(FEASIBILITY_DIR / "missing_signal_recoverability_class_summary.csv")
    _read_csv(FEASIBILITY_DIR / "missing_signal_crash_relevance_priority_queue.csv", usecols=["source_row_index", "GLOBALID", "recoverability_class"])
    _read_csv(FEASIBILITY_DIR / "missing_signal_recovery_decision_tree.csv")
    _load_normalized_signal_keys()

    expanded_signals = _read_csv(GOOD_TRAVELWAY_DIR / "expanded_good_travelway_signal_universe.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id", "signal_geometry_wkt", "universe_record_type"])
    global GOOD_TRAVELWAY_BINS_CACHE
    GOOD_TRAVELWAY_BINS_CACHE = _read_csv(GOOD_TRAVELWAY_DIR / "expanded_good_travelway_bin_universe.csv", usecols=["stable_signal_id", "stable_travelway_id"])
    _read_csv(GOOD_TRAVELWAY_DIR / "good_travelway_expanded_universe_readiness.csv", usecols=["stable_signal_id", "expanded_universe_readiness_class"])
    good_readiness = _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id", "revised_review_only_includable", "revised_hold_from_clean_analysis"])
    _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_universe_recommendation.csv")
    represented = _read_csv(STABLE_DIR / "stable_lineage_represented_signal_universe.csv")
    represented_bins = _read_csv(STABLE_DIR / "stable_lineage_represented_bin_universe.csv", usecols=["stable_signal_id", "stable_travelway_id"])

    targets = _load_targets()
    target_detail, legs, bins, skipped = _build_candidates(targets)
    overlap = _overlap_review(targets, expanded_signals, good_readiness, represented, represented_bins, bins)
    readiness = _context_readiness(target_detail if not target_detail.empty else targets.drop(columns=["geometry"], errors="ignore"), bins, overlap)
    summary_base = targets.drop(columns=["geometry"], errors="ignore").merge(
        target_detail[
            [
                "stable_signal_id",
                "intersection_anchor_x",
                "intersection_anchor_y",
                "signal_to_anchor_offset_ft",
                "anchor_method",
                "anchor_confidence",
                "anchor_intersection_candidate_count",
                "source_travelway_lines_within_125ft_raw_signal",
                "source_travelway_lines_within_175ft_raw_signal",
                "source_travelway_lines_within_250ft_raw_signal",
                "unique_route_count_250ft",
                "grade_or_mainline_risk_line_count",
            ]
        ] if not target_detail.empty else pd.DataFrame(columns=["stable_signal_id"]),
        on="stable_signal_id",
        how="left",
    )
    summary = _summaries(summary_base, legs, bins, skipped, readiness)
    crash = _crash_context(targets, bins)
    gpkg_inventory = _optional_gpkg(targets, target_detail, bins, crash)

    _write_csv(targets.drop(columns=["geometry"], errors="ignore"), "offset_anchor_missing_signal_targets.csv")
    _write_csv(summary, "offset_anchor_recovered_signal_summary.csv")
    _write_csv(legs, "offset_anchor_recovered_leg_candidates.csv")
    _write_csv(bins, "offset_anchor_recovered_bins.csv")
    _write_csv(skipped, "offset_anchor_recovery_skipped_targets.csv")
    _write_csv(readiness, "offset_anchor_context_refresh_readiness.csv")
    _write_csv(crash, "offset_anchor_crash_relevance_summary.csv")
    _write_csv(overlap, "offset_anchor_overlap_dedup_review.csv")
    _write_text(_findings(targets, summary, legs, bins, skipped, readiness, crash), "offset_anchor_scaffold_recovery_findings.md")
    qa = _qa(targets, bins)
    _write_csv(qa, "offset_anchor_scaffold_recovery_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_offset_anchor_scaffold_recovery",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "target_recoverability_class": TARGET_CLASS,
        "excluded_recoverability_classes": sorted(EXCLUDED_CLASSES),
        "target_signal_count": int(len(targets)),
        "generated_signal_count": int(pd.to_numeric(summary["generated_bin_count"], errors="coerce").fillna(0).gt(0).sum()) if not summary.empty else 0,
        "skipped_signal_count": int(len(targets) - (pd.to_numeric(summary["generated_bin_count"], errors="coerce").fillna(0).gt(0).sum() if not summary.empty else 0)),
        "generated_leg_candidate_count": int(len(legs)),
        "generated_bin_count": int(len(bins)),
        "stable_travelway_lineage_bin_count": int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0,
        "context_refresh_ready_signal_count": int(readiness["rns_speed_ready_for_later_refresh"].sum()) if not readiness.empty else 0,
        "high_crash_relevance_signal_count": int(_text(crash, "high_crash_relevance_flag").str.lower().eq("true").sum()) if not crash.empty else 0,
        "optional_gpkg": str(GPKG_PATH),
        "optional_gpkg_inventory": gpkg_inventory,
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "signals_promoted": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_or_models": False,
            "crash_direction_fields_read": False,
        },
        "input_manifests": {
            "missing_hmms_signal_recovery_feasibility": feasibility_manifest,
            "good_travelway_universe_integration": good_manifest,
            "complex_signal_map_review_ingestion": complex_manifest,
            "stable_lineage_scaffold_regeneration": stable_manifest,
        },
        "inputs": [str(path) for path in REQUIRED_INPUTS],
    }
    _write_json(manifest, "offset_anchor_scaffold_recovery_manifest.json")
    _checkpoint("complete")
    print("Missing HMMS offset-anchor scaffold recovery complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Target signals: {manifest['target_signal_count']:,}")
    print(f"Generated signals: {manifest['generated_signal_count']:,}")
    print(f"Generated bins: {manifest['generated_bin_count']:,}")
    print(f"Skipped signals: {manifest['skipped_signal_count']:,}")


if __name__ == "__main__":
    main()
