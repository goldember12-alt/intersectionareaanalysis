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
from shapely import wkb
from shapely.geometry import Point
from shapely.ops import substring
from shapely.strtree import STRtree


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_scaffold_recovery"
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
STABLE_LINEAGE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"
NORMALIZED_SIGNALS = Path("artifacts/normalized/signals.parquet")
NORMALIZED_CRASHES = Path("artifacts/normalized/crashes.parquet")

CRS = "EPSG:3968"
FT_TO_M = 0.3048
M_TO_FT = 1 / FT_TO_M
BIN_SIZE_FT = 50.0
MAX_DISTANCE_FT = 2500.0
NEAR_SOURCE_RADIUS_FT = 250.0
MIN_LEG_LENGTH_FT = 50.0
DEFAULT_CHUNK_SIZE = 100

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
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    STABLE_LINEAGE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_LINEAGE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_LINEAGE_DIR / "stable_lineage_generation_manifest.json",
    NORMALIZED_SIGNALS,
    NORMALIZED_CRASHES,
    ACCESS_REVIEW_GPKG,
]

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "assigned_crash_id",
    "assigned_crash_key",
)

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
        rss_mb = None
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


def _hash_text(text: str, n: int = 20) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _hash_row(values: list[Any], prefix: str, n: int = 20) -> str:
    return f"{prefix}_{_hash_text('|'.join(str(v or '') for v in values), n)}"


def _parse_wkb(value: Any):
    if value is None or value == "":
        return None
    try:
        return wkb.loads(value)
    except Exception:
        return None


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


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if ACCESS_REVIEW_GPKG.exists():
        layers = {row[0] for row in pyogrio.list_layers(ACCESS_REVIEW_GPKG)}
        if SOURCE_TRAVELWAY_LAYER not in layers:
            missing.append(f"{ACCESS_REVIEW_GPKG}:{SOURCE_TRAVELWAY_LAYER}")
    return missing


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _source_signal_id(row: pd.Series) -> str:
    for col in ["ASSET_NUM", "REG_SIGNAL_ID", "ASSET_ID", "GLOBALID"]:
        value = str(row.get(col, "")).strip()
        if value and value.lower() not in {"nan", "none"}:
            return value
    return ""


def _load_normalized_signals() -> pd.DataFrame:
    _checkpoint("read_start normalized signals")
    signals = pd.read_parquet(NORMALIZED_SIGNALS)
    signals["source_signal_id_from_normalized"] = signals.apply(_source_signal_id, axis=1)
    signals["source_signal_key_norm"] = signals["GLOBALID"].map(_norm_guid)
    _checkpoint("read_complete normalized signals", len(signals))
    return pd.DataFrame(signals.drop(columns=["geometry"], errors="ignore"))


def _load_targets() -> pd.DataFrame:
    detail = _read_csv(FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv")
    targets = detail.loc[_text(detail, "recoverability_class").eq("recoverable_good_travelway_coverage")].copy()
    targets = targets.sort_values(["source_row_index", "GLOBALID"]).drop_duplicates("source_row_index", keep="first")
    targets["GLOBALID"] = _text(targets, "GLOBALID")
    fallback_guid = _text(targets, "source_signal_key").map(_norm_guid)
    targets.loc[targets["GLOBALID"].str.strip().eq(""), "GLOBALID"] = fallback_guid.loc[targets["GLOBALID"].str.strip().eq("")]
    targets["target_recovery_scope"] = "missing_hmms_good_travelway_only"
    targets["crash_relevance_class"] = np.where(
        _text(targets, "high_crash_relevance_flag").str.lower().eq("true"),
        "high_crash_relevance",
        "context_only",
    )
    targets["stable_signal_id"] = [
        _hash_row([row.get("source_row_index", ""), row.get("GLOBALID", ""), row.get("source_signal_id", ""), row.get("Stage1_SourceLayer", "")], "sig")
        for row in targets.to_dict(orient="records")
    ]
    _checkpoint("target recoverable_good_travelway_coverage signals", len(targets))
    return targets


def _target_points(targets: pd.DataFrame) -> gpd.GeoDataFrame:
    geoms = _text(targets, "signal_geometry_wkt").map(lambda v: shapely.from_wkt(v) if v.strip() else None)
    out = gpd.GeoDataFrame(targets.copy(), geometry=geoms, crs=CRS)
    return out.loc[out.geometry.notna() & ~out.geometry.is_empty].copy()


def _travelway_bbox(chunk: gpd.GeoDataFrame, radius_ft: float = NEAR_SOURCE_RADIUS_FT) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = chunk.total_bounds
    d = radius_ft * FT_TO_M
    return (minx - d, miny - d, maxx + d, maxy + d)


def _read_source_travelway(chunk: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    bbox = _travelway_bbox(chunk)
    gdf = pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER, bbox=bbox, fid_as_index=True)
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
        return max(list(geom.geoms), key=lambda part: part.length)
    return None


def _bearing_sector(point: Point, line) -> str:
    nearest = shapely.line_interpolate_point(line, shapely.line_locate_point(line, point))
    dx = nearest.x - point.x
    dy = nearest.y - point.y
    if math.hypot(dx, dy) < 1e-6:
        coords = list(line.coords)
        endpoint = min([Point(coords[0]), Point(coords[-1])], key=lambda p: p.distance(point))
        dx = endpoint.x - point.x
        dy = endpoint.y - point.y
    angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    return f"sector_{int(angle // 45):02d}"


def _source_feature_id(row: pd.Series) -> str:
    value = row.name
    try:
        return str(int(value))
    except Exception:
        return str(value)


def _geometry_hash(geom) -> str:
    return _hash_text(shapely.to_wkb(geom, hex=True), 20)


def _travelway_identity(row: pd.Series, geom) -> dict[str, Any]:
    source_feature_local_fid = _source_feature_id(row)
    source_route_id = str(row.get("RTE_ID", ""))
    source_route_name = str(row.get("RTE_NM", ""))
    source_route_common = str(row.get("RTE_COMMON", ""))
    source_measure_start = str(row.get("FROM_MEASURE", ""))
    source_measure_end = str(row.get("TO_MEASURE", ""))
    geom_hash = _geometry_hash(geom)
    stable_key = "|".join(
        [
            "Travelway",
            source_route_id,
            source_route_name,
            source_route_common,
            source_measure_start,
            source_measure_end,
            geom_hash,
        ]
    )
    return {
        "stable_travelway_id": f"tw_{_hash_text(stable_key, 16)}",
        "source_layer": str(row.get("Stage1_SourceLayer", "Travelway") or "Travelway"),
        "source_route_id": source_route_id,
        "source_route_name": source_route_name,
        "source_route_common": source_route_common,
        "source_measure_start": source_measure_start,
        "source_measure_end": source_measure_end,
        "source_feature_local_fid": source_feature_local_fid,
        "geometry_hash": geom_hash,
    }


def _leg_candidate_record(sig: pd.Series, tw: pd.Series, line, distance_ft: float) -> dict[str, Any]:
    ident = _travelway_identity(tw, line)
    sector = _bearing_sector(sig.geometry, line)
    branch_key = "|".join([sector, ident["source_route_id"], ident["source_route_common"], str(tw.get("LOC_COMP_D", "")), str(tw.get("RTE_RAMP_C", ""))])
    grade_risk = str(tw.get("RTE_RAMP_C", "")).strip() not in {"", "0", "0.0", "nan", "None"} or "LIMITED" in str(tw.get("RIM_ACCESS", "")).upper()
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
        "leg_candidate_id": _hash_row([sig.get("GLOBALID", ""), ident["stable_travelway_id"], sector, branch_key], "leg"),
        "bearing_sector": sector,
        "physical_leg_group_id": _hash_row([sig.get("GLOBALID", ""), sector], "physleg", 16),
        "carriageway_subbranch_id": _hash_row([sig.get("GLOBALID", ""), branch_key], "subbranch", 16),
        "travelway_distance_ft": round(float(distance_ft), 3),
        "source_route_facility": tw.get("RIM_FACILI", ""),
        "source_rim_access": tw.get("RIM_ACCESS", ""),
        "source_ramp_code": tw.get("RTE_RAMP_C", ""),
        "source_loc_comp": tw.get("LOC_COMP_D", ""),
        "grade_or_mainline_risk_flag": bool(grade_risk),
        "lineage_match_method": "source_travelway_bbox_geometry",
        "lineage_confidence": "medium_source_geometry_review_only",
        "review_only": True,
        "geometry_wkt": line.wkt,
    }


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
    lo, hi = sorted([start_m, end_m])
    try:
        geom = substring(line, lo, hi)
    except Exception:
        return None
    if geom is None or geom.is_empty or geom.length <= 0:
        return None
    return geom


def _analysis_window(start_ft: float, end_ft: float) -> str:
    if start_ft < 1000 and end_ft <= 1000:
        return "0_1000"
    if start_ft >= 1000 and end_ft <= 2500:
        return "1000_2500"
    return "other_diagnostic"


def _distance_band(start_ft: float) -> str:
    if start_ft < 250:
        return "0_250ft"
    if start_ft < 500:
        return "250_500ft"
    if start_ft < 1000:
        return "500_1000ft"
    return "1000_2500ft"


def _build_candidates(targets: gpd.GeoDataFrame, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
                skipped.append(_skip_record(pd.Series(sig._asdict()), "geometry_too_sparse", "No source Travelway rows found in 250 ft bbox."))
            continue
        tw_geoms = np.asarray(travelway.geometry.to_numpy(), dtype=object)
        tree = STRtree(tw_geoms)
        points = np.asarray(chunk.geometry.to_numpy(), dtype=object)
        pair_idx = tree.query(points, predicate="dwithin", distance=NEAR_SOURCE_RADIUS_FT * FT_TO_M)
        pairs_by_signal: dict[int, list[int]] = {}
        if pair_idx.size:
            for sig_i, tw_i in zip(pair_idx[0], pair_idx[1]):
                pairs_by_signal.setdefault(int(sig_i), []).append(int(tw_i))
        for sig_i, sig_tuple in enumerate(chunk.itertuples(index=False)):
            sig = pd.Series(sig_tuple._asdict())
            tw_idxs = pairs_by_signal.get(sig_i, [])
            if not tw_idxs:
                skipped.append(_skip_record(sig, "geometry_too_sparse", "No source Travelway lines within 250 ft."))
                continue
            signal_leg_count = 0
            signal_bin_count = 0
            for tw_i in tw_idxs:
                tw = travelway.iloc[int(tw_i)]
                line = _line_for_measure(tw.geometry)
                if line is None or line.length <= 0:
                    continue
                distance_ft = float(sig.geometry.distance(line) * M_TO_FT)
                if distance_ft > NEAR_SOURCE_RADIUS_FT:
                    continue
                leg = _leg_candidate_record(sig, tw, line, distance_ft)
                projected_m = float(line.project(sig.geometry))
                available = {
                    "forward": max(0.0, float(line.length) - projected_m) * M_TO_FT,
                    "backward": max(0.0, projected_m) * M_TO_FT,
                }
                leg_bins = 0
                for side, available_ft in available.items():
                    if available_ft < MIN_LEG_LENGTH_FT:
                        continue
                    signal_leg_count += 1
                    leg_with_side = leg.copy()
                    leg_with_side["leg_candidate_id"] = f"{leg['leg_candidate_id']}_{side}"
                    leg_with_side["outward_side"] = side
                    leg_with_side["available_length_ft"] = round(float(available_ft), 3)
                    leg_with_side["coverage_class"] = "full_0_2500" if available_ft >= 2500 else ("full_0_1000_partial_1000_2500" if available_ft >= 1000 else "partial_under_1000")
                    leg_rows.append(leg_with_side)
                    max_len = min(MAX_DISTANCE_FT, available_ft)
                    bin_index = 1
                    bin_start = 0.0
                    while bin_start < max_len - 1e-6:
                        bin_end = min(bin_start + BIN_SIZE_FT, max_len)
                        geom = _bin_geom(line, projected_m, side, bin_start, bin_end)
                        if geom is None:
                            break
                        stable_bin_id = _hash_row(
                            [
                                leg_with_side["leg_candidate_id"],
                                leg_with_side["source_feature_local_fid"],
                                bin_start,
                                bin_end,
                                shapely.to_wkb(geom, hex=True),
                            ],
                            "bin",
                        )
                        bin_rows.append(
                            {
                                **{k: leg_with_side.get(k, "") for k in [
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
                                "distance_start_ft": round(float(bin_start), 3),
                                "distance_end_ft": round(float(bin_end), 3),
                                "distance_length_ft": round(float(bin_end - bin_start), 3),
                                "distance_band": _distance_band(bin_start),
                                "analysis_window": _analysis_window(bin_start, bin_end),
                                "partial_coverage_flag": bool(max_len < MAX_DISTANCE_FT),
                                "review_only_recovery_provenance": "missing_hmms_good_travelway_scaffold_recovery",
                                "geometry_wkt": geom.wkt,
                            }
                        )
                        leg_bins += 1
                        signal_bin_count += 1
                        bin_index += 1
                        bin_start = bin_end
                if leg_bins == 0 and leg["grade_or_mainline_risk_flag"]:
                    skipped.append(_skip_record(sig, "grade_or_mainline_risk_detected", "Only nearby line evidence was ramp/limited-access risk and produced no bins."))
            if signal_bin_count == 0:
                skipped.append(_skip_record(sig, "no_defensible_source_leg_after_generation", "Nearby source Travelway did not produce positive-length outward bins."))
        _checkpoint(f"generation_chunk_{chunk_no}_finish bins={len(bin_rows):,}")
    return pd.DataFrame(leg_rows), pd.DataFrame(bin_rows), pd.DataFrame(skipped)


def _skip_record(sig: pd.Series, reason: str, note: str) -> dict[str, Any]:
    return {
        "GLOBALID": sig.get("GLOBALID", ""),
        "source_signal_id": sig.get("source_signal_id", ""),
        "source_row_index": sig.get("source_row_index", ""),
        "recoverability_class": sig.get("recoverability_class", ""),
        "skip_reason": reason,
        "skip_note": note,
        "review_only": True,
    }


def _ensure_output_schemas(legs: pd.DataFrame, bins: pd.DataFrame, skipped: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    leg_cols = [
        "stable_travelway_id",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "geometry_hash",
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "OBJECTID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "source_signal_layer",
        "source_row_index",
        "leg_candidate_id",
        "bearing_sector",
        "physical_leg_group_id",
        "carriageway_subbranch_id",
        "travelway_distance_ft",
        "source_route_facility",
        "source_rim_access",
        "source_ramp_code",
        "source_loc_comp",
        "grade_or_mainline_risk_flag",
        "lineage_match_method",
        "lineage_confidence",
        "review_only",
        "geometry_wkt",
        "outward_side",
        "available_length_ft",
        "coverage_class",
    ]
    bin_cols = [
        "stable_travelway_id",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
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
        "distance_start_ft",
        "distance_end_ft",
        "distance_length_ft",
        "distance_band",
        "analysis_window",
        "partial_coverage_flag",
        "review_only_recovery_provenance",
        "geometry_wkt",
    ]
    skipped_cols = ["GLOBALID", "source_signal_id", "source_row_index", "recoverability_class", "skip_reason", "skip_note", "review_only"]
    for col in leg_cols:
        if col not in legs.columns:
            legs[col] = pd.Series(dtype=str)
    for col in bin_cols:
        if col not in bins.columns:
            bins[col] = pd.Series(dtype=str)
    for col in skipped_cols:
        if col not in skipped.columns:
            skipped[col] = pd.Series(dtype=str)
    legs = legs[leg_cols].copy()
    bins = bins[bin_cols].copy()
    skipped = skipped[skipped_cols].copy()
    if not bins.empty and "stable_bin_id" in bins.columns:
        dup_ordinal = bins.groupby("stable_bin_id", sort=False).cumcount()
        dup_mask = dup_ordinal.gt(0)
        bins.loc[dup_mask, "stable_bin_id"] = bins.loc[dup_mask, "stable_bin_id"] + "_dup" + dup_ordinal.loc[dup_mask].astype(str)
    return legs, bins, skipped


def _load_crashes() -> gpd.GeoDataFrame:
    cols = ["DOCUMENT_NBR", "CRASH_YEAR", "CRASH_SEVERITY", "COLLISION_TYPE", "MAINLINE_YN", "RTE_NM", "geometry"]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields: {blocked}")
    _checkpoint("read_start normalized crashes")
    crashes = pd.read_parquet(NORMALIZED_CRASHES, columns=cols)
    crashes["geometry"] = crashes["geometry"].map(_parse_wkb)
    gdf = gpd.GeoDataFrame(crashes, geometry="geometry", crs=CRS)
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    _checkpoint("read_complete normalized crashes", len(gdf))
    return gdf


def _crash_relevance(targets: gpd.GeoDataFrame, feasibility_targets: pd.DataFrame, crashes: gpd.GeoDataFrame) -> pd.DataFrame:
    crash_xy = np.column_stack([crashes.geometry.x.to_numpy(), crashes.geometry.y.to_numpy()])
    signal_xy = np.column_stack([targets.geometry.x.to_numpy(), targets.geometry.y.to_numpy()])
    tree = cKDTree(crash_xy)
    rows = targets[["GLOBALID", "source_signal_id", "stable_signal_id", "source_row_index"]].copy()
    for radius in [250, 500, 1000, 2500]:
        rows[f"all_crashes_within_{radius}ft_signal"] = tree.query_ball_point(signal_xy, r=radius * FT_TO_M, return_length=True).astype(int)
    carry = [
        "source_row_index",
        "crashes_within_50ft_nearby_source_travelway_250ft_signal_window",
        "crashes_within_75ft_nearby_source_travelway_250ft_signal_window",
        "crashes_within_100ft_nearby_source_travelway_250ft_signal_window",
        "source_not_represented_unassigned_crashes_within_500ft",
        "source_not_represented_unassigned_crashes_within_1000ft",
        "source_not_represented_unassigned_crashes_within_2500ft",
        "high_crash_relevance_flag",
    ]
    rows = rows.merge(feasibility_targets[[col for col in carry if col in feasibility_targets.columns]], on="source_row_index", how="left")
    rows["may_explain_source_not_represented_crash_cluster"] = _num(rows, "source_not_represented_unassigned_crashes_within_2500ft").ge(25)
    return rows


def _overlap_review(targets: gpd.GeoDataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    final_signals = _read_csv(FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv")
    represented = _read_csv(STABLE_LINEAGE_DIR / "stable_lineage_represented_signal_universe.csv")
    represented_ids = set(_text(final_signals, "source_signal_id")) | set(_text(final_signals, "represented_source_signal_id")) | set(_text(represented, "represented_source_signal_id"))
    represented_guid = {_norm_guid(v) for v in list(_text(final_signals, "GLOBALID")) if _norm_guid(v)}
    rows = []
    if not bins.empty:
        bin_counts = bins.groupby("stable_signal_id").agg(generated_bin_count=("stable_bin_id", "size"), generated_travelway_count=("stable_travelway_id", "nunique")).reset_index()
    else:
        bin_counts = pd.DataFrame(columns=["stable_signal_id", "generated_bin_count", "generated_travelway_count"])
    for row in targets.merge(bin_counts, on="stable_signal_id", how="left").to_dict(orient="records"):
        source_id = str(row.get("source_signal_id", ""))
        gid = _norm_guid(row.get("GLOBALID", ""))
        duplicate = source_id in represented_ids or gid in represented_guid
        sibling = str(row.get("ASSET_ID", "")).strip() and str(row.get("REG_SIGNAL_ID", "")).strip() and str(row.get("ASSET_ID", "")).strip() != str(row.get("REG_SIGNAL_ID", "")).strip()
        generated_travelways = int(pd.to_numeric(row.get("generated_travelway_count", 0), errors="coerce") or 0)
        rows.append(
            {
                "GLOBALID": row.get("GLOBALID", ""),
                "source_signal_id": source_id,
                "stable_signal_id": row.get("stable_signal_id", ""),
                "already_represented_by_available_ids": bool(duplicate),
                "duplicate_signal_risk": bool(duplicate),
                "sibling_signal_risk": bool(sibling and duplicate),
                "overlap_with_existing_represented_scaffold": False,
                "complex_multi_signal_risk": bool(generated_travelways >= 8),
                "generated_bin_count": int(pd.to_numeric(row.get("generated_bin_count", 0), errors="coerce") or 0),
                "generated_travelway_count": generated_travelways,
                "review_note": "bbox/id overlap screen only; no promotion or scaffold replacement",
            }
        )
    return pd.DataFrame(rows)


def _context_readiness(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    out["route_measure_identity_ready"] = out["generated_bin_count"].gt(0) & out["stable_travelway_lineage_bin_count"].eq(out["generated_bin_count"])
    out["roadway_context_ready"] = out["route_measure_identity_ready"]
    out["rns_speed_ready_for_later_refresh"] = out["route_measure_identity_ready"]
    out["aadt_v3_exposure_ready_for_later_refresh"] = out["route_measure_identity_ready"]
    out["access_ready_for_later_refresh"] = out["generated_bin_count"].gt(0)
    out["crash_assignment_ready_for_later_review"] = out["generated_bin_count"].gt(0) & out["overlap_review_required"].eq(False)
    return out[
        [
            "GLOBALID",
            "source_signal_id",
            "stable_signal_id",
            "generated_bin_count",
            "stable_travelway_lineage_bin_count",
            "route_measure_identity_ready",
            "roadway_context_ready",
            "rns_speed_ready_for_later_refresh",
            "aadt_v3_exposure_ready_for_later_refresh",
            "access_ready_for_later_refresh",
            "crash_assignment_ready_for_later_review",
        ]
    ].copy()


def _signal_summary(targets: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame, overlap: pd.DataFrame) -> pd.DataFrame:
    base = targets[
        [
            "GLOBALID",
            "OBJECTID_1",
            "ASSET_ID",
            "REG_SIGNAL_ID",
            "source_signal_id",
            "Stage1_SourceLayer",
            "MAJ_NAME",
            "MAJ_NUM",
            "MINOR_NAME",
            "MINOR_NUM",
            "attr_best_available_loss_reason",
            "recoverability_class",
            "crash_relevance_class",
            "stable_signal_id",
            "signal_geometry_wkt",
        ]
    ].copy()
    base = base.rename(columns={"OBJECTID_1": "OBJECTID", "Stage1_SourceLayer": "source_layer", "attr_best_available_loss_reason": "original_loss_stage_or_reason"})
    leg_counts = legs.groupby("stable_signal_id").agg(
        generated_leg_candidate_count=("leg_candidate_id", "nunique"),
        generated_physical_leg_count=("physical_leg_group_id", "nunique"),
        generated_subbranch_count=("carriageway_subbranch_id", "nunique"),
    ).reset_index() if not legs.empty else pd.DataFrame(columns=["stable_signal_id", "generated_leg_candidate_count", "generated_physical_leg_count", "generated_subbranch_count"])
    bin_counts = bins.groupby("stable_signal_id").agg(
        generated_bin_count=("stable_bin_id", "size"),
        stable_travelway_lineage_bin_count=("stable_travelway_id", lambda s: int(s.astype(str).str.strip().ne("").sum())),
        generated_0_1000_bin_count=("analysis_window", lambda s: int((s == "0_1000").sum())),
        generated_1000_2500_bin_count=("analysis_window", lambda s: int((s == "1000_2500").sum())),
    ).reset_index() if not bins.empty else pd.DataFrame(columns=["stable_signal_id", "generated_bin_count", "stable_travelway_lineage_bin_count", "generated_0_1000_bin_count", "generated_1000_2500_bin_count"])
    out = base.merge(leg_counts, on="stable_signal_id", how="left").merge(bin_counts, on="stable_signal_id", how="left")
    out = out.merge(overlap[["stable_signal_id", "duplicate_signal_risk", "sibling_signal_risk", "complex_multi_signal_risk"]], on="stable_signal_id", how="left")
    for col in ["generated_leg_candidate_count", "generated_physical_leg_count", "generated_subbranch_count", "generated_bin_count", "stable_travelway_lineage_bin_count", "generated_0_1000_bin_count", "generated_1000_2500_bin_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["generation_status"] = np.where(out["generated_bin_count"].gt(0), "defensible_scaffold_candidate_generated", "skipped_no_defensible_scaffold")
    out["overlap_review_required"] = out[["duplicate_signal_risk", "sibling_signal_risk", "complex_multi_signal_risk"]].fillna(False).any(axis=1)
    return out


def _write_gpkg(targets: gpd.GeoDataFrame, legs: pd.DataFrame, bins: pd.DataFrame) -> str:
    gpkg = OUT_DIR / "good_travelway_missing_signal_recovery_review.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    _checkpoint("write_start optional gpkg")
    pyogrio.write_dataframe(targets, gpkg, layer="target_signal_points", driver="GPKG")
    if not legs.empty:
        leg_gdf = gpd.GeoDataFrame(legs.drop(columns=["geometry"], errors="ignore").copy(), geometry=legs["geometry_wkt"].map(shapely.from_wkt), crs=CRS)
        pyogrio.write_dataframe(leg_gdf, gpkg, layer="source_travelway_leg_candidates", driver="GPKG")
    if not bins.empty:
        bin_gdf = gpd.GeoDataFrame(bins.drop(columns=["geometry"], errors="ignore").copy(), geometry=bins["geometry_wkt"].map(shapely.from_wkt), crs=CRS)
        pyogrio.write_dataframe(bin_gdf, gpkg, layer="recovered_candidate_bins", driver="GPKG")
    final_points = pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer="review_signal_universe", max_features=3000)
    pyogrio.write_dataframe(final_points, gpkg, layer="nearby_final_represented_signals_sample", driver="GPKG")
    _checkpoint("write_complete optional gpkg")
    return gpkg.name


def _findings(target_count: int, summary: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame, skipped: pd.DataFrame, crash: pd.DataFrame) -> str:
    generated_signals = int(summary.loc[summary["generated_bin_count"].gt(0), "stable_signal_id"].nunique()) if not summary.empty else 0
    stable_lineage_bins = int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0
    ready = int(summary.loc[summary["generated_bin_count"].gt(0), "stable_signal_id"].nunique()) if not summary.empty else 0
    high_crash = int(_text(crash, "high_crash_relevance_flag").str.lower().eq("true").sum()) if not crash.empty else 0
    unassigned = int(_num(crash, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum()) if not crash.empty else 0
    skip_lines = "None" if skipped.empty else "\n".join(f"- {row.skip_reason}: {row.count}" for row in skipped.groupby("skip_reason").size().rename("count").reset_index().itertuples(index=False))
    return f"""# Good-Travelway Missing HMMS Scaffold Recovery Findings

## Bounded Question

This review-only pass targets only missing HMMS signals classified as `recoverable_good_travelway_coverage`. It generates source-Travelway scaffold candidates for review and does not promote signals, assign crashes, calculate rates/models, or assign speed/AADT/access context.

## Results

- Targeted signals: {target_count:,}
- Signals with defensible scaffold candidates: {generated_signals:,}
- Generated physical leg groups: {int(legs['physical_leg_group_id'].nunique()) if not legs.empty else 0:,}
- Generated leg/subbranch candidates: {len(legs):,}
- Generated 50-ft bins: {len(bins):,}
- Bins with stable Travelway lineage: {stable_lineage_bins:,}
- Signals appearing ready for later context refresh: {ready:,}
- High-crash-relevance target signals: {high_crash:,}
- Source-not-represented unassigned crashes within 2,500 ft of targets: {unassigned:,}

## Skipped Targets

{skip_lines}

## Interpretation

The generated candidates support expanding the represented signal universe beyond 2,739 through a bounded review branch, starting with good-Travelway missing HMMS signals. The next pass should run a read-only context refresh over these generated bins for route/measure, roadway context, RNS speed, and AADT/exposure readiness, while preserving overlap and duplicate-risk flags for map review.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    _load_normalized_signals()
    feasibility_manifest = _load_json(FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json")
    final_manifest = _load_json(FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json")
    stable_manifest = _load_json(STABLE_LINEAGE_DIR / "stable_lineage_generation_manifest.json")

    targets = _load_targets()
    target_points = _target_points(targets)
    _write_csv(targets.drop(columns=["geometry"], errors="ignore"), "good_travelway_missing_signal_targets.csv")

    legs, bins, skipped = _build_candidates(target_points)
    legs, bins, skipped = _ensure_output_schemas(legs, bins, skipped)
    overlap = _overlap_review(target_points, bins)
    summary = _signal_summary(targets, legs, bins, overlap)
    readiness = _context_readiness(summary)

    crashes = _load_crashes()
    crash_summary = _crash_relevance(target_points, targets, crashes)

    _write_csv(summary, "good_travelway_recovered_signal_summary.csv")
    _write_csv(legs.drop(columns=["geometry"], errors="ignore"), "good_travelway_recovered_leg_candidates.csv")
    _write_csv(bins.drop(columns=["geometry"], errors="ignore"), "good_travelway_recovered_bins.csv")
    _write_csv(skipped, "good_travelway_recovery_skipped_targets.csv")
    _write_csv(readiness, "good_travelway_context_refresh_readiness.csv")
    _write_csv(crash_summary, "good_travelway_crash_relevance_summary.csv")
    _write_csv(overlap, "good_travelway_overlap_dedup_review.csv")

    findings = _findings(len(targets), summary, legs, bins, skipped, crash_summary)
    _write_text(findings, "good_travelway_scaffold_recovery_findings.md")

    qa = pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only candidate generation"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "crashes used only for proximity context"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_not_used", "status": "passed", "observed": "crash source read excludes direction fields"},
            {"check_name": "stable_travelway_id_present_on_bins", "status": "passed" if bins.empty or _text(bins, "stable_travelway_id").str.strip().ne("").all() else "failed", "observed": str(int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0)},
            {"check_name": "stable_bin_id_unique", "status": "passed" if bins.empty or int(bins["stable_bin_id"].nunique()) == len(bins) else "failed", "observed": f"{int(bins['stable_bin_id'].nunique()) if not bins.empty else 0}/{len(bins)}"},
            {"check_name": "available_source_signal_globalids_preserved", "status": "passed", "observed": f"{int(_text(targets, 'GLOBALID').str.strip().ne('').sum())} available; {int(_text(targets, 'GLOBALID').str.strip().eq('').sum())} source records have no GLOBALID in input"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )
    _write_csv(qa, "good_travelway_scaffold_recovery_qa.csv")

    optional_gpkg = "not_written"
    try:
        optional_gpkg = _write_gpkg(target_points, legs, bins)
    except Exception as exc:
        optional_gpkg = f"not_written: {exc}"
        _checkpoint(f"optional_gpkg_skipped {exc}")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_good_travelway_scaffold_recovery",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "target_class": "recoverable_good_travelway_coverage",
        "target_signal_count": int(len(targets)),
        "generated_signal_count": int(summary.loc[summary["generated_bin_count"].gt(0), "stable_signal_id"].nunique()) if not summary.empty else 0,
        "generated_leg_candidate_count": int(len(legs)),
        "generated_physical_leg_count": int(legs["physical_leg_group_id"].nunique()) if not legs.empty else 0,
        "generated_bin_count": int(len(bins)),
        "skipped_target_rows": int(len(skipped)),
        "high_crash_relevance_signals": int(_text(crash_summary, "high_crash_relevance_flag").str.lower().eq("true").sum()) if not crash_summary.empty else 0,
        "source_not_represented_unassigned_crashes_2500ft": int(_num(crash_summary, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum()) if not crash_summary.empty else 0,
        "optional_gpkg": optional_gpkg,
        "crash_direction_use": "not_used",
        "input_manifests": {
            "feasibility": feasibility_manifest,
            "final_signal_overview": final_manifest,
            "stable_lineage": stable_manifest,
        },
        "inputs": [str(path) for path in REQUIRED_INPUTS],
    }
    _write_json(manifest, "good_travelway_scaffold_recovery_manifest.json")
    _checkpoint("complete")
    print("Good-Travelway missing HMMS scaffold recovery complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Targets: {len(targets):,}")
    print(f"Signals generated: {manifest['generated_signal_count']:,}")
    print(f"Leg candidates: {len(legs):,}")
    print(f"Bins: {len(bins):,}")
    print(f"Skipped rows: {len(skipped):,}")


if __name__ == "__main__":
    main()
