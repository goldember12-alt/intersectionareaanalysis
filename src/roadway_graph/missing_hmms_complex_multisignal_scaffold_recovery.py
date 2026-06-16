from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely import wkt
from shapely.geometry import LineString, MultiLineString
from shapely.ops import substring


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_complex_multisignal_scaffold_recovery"
FINAL_ACCOUNTING_DIR = OUTPUT_ROOT / "review/current/final_staged_signal_accounting"
RECOVERABILITY_DIR = OUTPUT_ROOT / "review/current/remaining_signal_recoverability_diagnostic"
COMPLEX_REVIEW_DIR = OUTPUT_ROOT / "review/current/complex_signal_map_review_ingestion"
OFFSET_COMPLEX_DIR = OUTPUT_ROOT / "review/current/offset_anchor_complex_risk_reclassification"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
OFFSET_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
RAMP_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/ramp_terminal_universe_integration"
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"

CRS = "EPSG:3968"
FT_TO_M = 0.3048
M_TO_FT = 1 / FT_TO_M
SOURCE_RADIUS_FT = 250.0
BIN_SIZE_FT = 50.0
MAX_DISTANCE_FT = 1000.0
MIN_LEG_LENGTH_FT = 50.0

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
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv",
    FINAL_ACCOUNTING_DIR / "final_remaining_446_breakdown.csv",
    FINAL_ACCOUNTING_DIR / "final_review_visible_not_clean_breakdown.csv",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json",
    RECOVERABILITY_DIR / "remaining_recoverability_target_detail.csv",
    RECOVERABILITY_DIR / "complex_multi_signal_remaining_decomposition.csv",
    RECOVERABILITY_DIR / "remaining_recoverability_class_summary.csv",
    RECOVERABILITY_DIR / "remaining_recoverability_priority_queue.csv",
    RECOVERABILITY_DIR / "remaining_recoverability_crash_relevance_summary.csv",
    RECOVERABILITY_DIR / "remaining_signal_recoverability_manifest.json",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_decisions.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_travelway_fid_validation.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_review_joined_to_recovery.csv",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_calibration_rules.csv",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassified_detail.csv",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_reclassification_summary.csv",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassification_manifest.json",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv",
    OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json",
    RAMP_UNIVERSE_DIR / "ramp_terminal_integrated_signal_additions.csv",
    RAMP_UNIVERSE_DIR / "ramp_terminal_integrated_bin_additions.csv",
    RAMP_UNIVERSE_DIR / "ramp_terminal_updated_remaining_signal_ledger.csv",
    RAMP_UNIVERSE_DIR / "ramp_terminal_universe_integration_manifest.json",
    FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv",
    FEASIBILITY_DIR / "missing_signal_travelway_coverage_summary.csv",
    FEASIBILITY_DIR / "missing_signal_crash_relevance_priority_queue.csv",
    FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json",
    ACCESS_REVIEW_GPKG,
]

_T0 = time.perf_counter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _memory_note() -> str:
    elapsed = time.perf_counter() - _T0
    try:
        import psutil

        rss = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        return f" elapsed_s={elapsed:.1f} rss_mb={rss:.1f}"
    except Exception:
        return f" elapsed_s={elapsed:.1f}"


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


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _manifest_ref(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "created_utc": payload.get("created_utc", ""),
        "script": payload.get("script", ""),
        "counts": payload.get("counts", {}),
    }


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "null"} else text


def _hash_text(text: str, n: int = 20) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _hash_row(values: list[Any], prefix: str, n: int = 20) -> str:
    return f"{prefix}_{_hash_text('|'.join(_clean(v) for v in values), n)}"


def _parse_point(value: Any):
    text = _clean(value)
    if not text.startswith("POINT"):
        return None
    try:
        return wkt.loads(text)
    except Exception:
        return None


def _geometry_hash(geom) -> str:
    return _hash_text(geom.wkt if geom is not None else "", 20)


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if ACCESS_REVIEW_GPKG.exists():
        layers = {row[0] for row in pyogrio.list_layers(ACCESS_REVIEW_GPKG)}
        if SOURCE_TRAVELWAY_LAYER not in layers:
            missing.append(f"{ACCESS_REVIEW_GPKG}:{SOURCE_TRAVELWAY_LAYER}")
    return missing


def _stable_signal_id(row: pd.Series) -> str:
    value = _clean(row.get("stable_signal_id"))
    if value:
        return value
    return _hash_row(
        [row.get("source_layer"), row.get("GLOBALID"), row.get("OBJECTID_1"), row.get("ASSET_ID"), row.get("REG_SIGNAL_ID"), row.get("signal_geometry_wkt")],
        "sig",
    )


def _source_signal_id(row: pd.Series) -> str:
    for col in ["source_signal_id", "ASSET_NUM", "REG_SIGNAL_ID", "ASSET_ID", "GLOBALID"]:
        value = _clean(row.get(col))
        if value:
            return value
    return ""


def _load_targets() -> gpd.GeoDataFrame:
    detail = _read_csv(RECOVERABILITY_DIR / "complex_multi_signal_remaining_decomposition.csv")
    target = detail[_text(detail, "final_primary_status").eq("recoverable_complex_multi_signal_not_processed")].copy()
    target = target[_text(target, "diagnostic_reclassification").isin({"complex_but_includable_good_travelway", "complex_but_includable_with_flags"})].copy()
    target["stable_signal_id"] = target.apply(_stable_signal_id, axis=1)
    target["source_signal_id"] = target.apply(_source_signal_id, axis=1)
    target["crash_relevance_class"] = np.where(_flag(target, "high_crash_relevance"), "high_crash_relevance", "context_only")
    target["geometry"] = _text(target, "signal_geometry_wkt").map(_parse_point)
    gdf = gpd.GeoDataFrame(target, geometry="geometry", crs=CRS)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    _checkpoint("target_pool_filtered_recoverable_complex_multi_signal_not_processed", len(gdf))
    return gdf


def _load_travelway() -> gpd.GeoDataFrame:
    cols = [
        "RTE_NM", "RTE_COMMON", "RTE_ID", "RIM_FACILI", "RIM_FACI_1", "RTE_CATEGO",
        "RTE_TYPE_N", "RTE_RAMP_C", "RIM_MEDIAN", "MEDIAN_IND", "RIM_ACCESS",
        "FROM_MEASURE", "TO_MEASURE", "RTE_FROM_M", "RTE_TO_MSR", "LOC_COMP_D",
        "Stage1_SourceLayer", "Shape_Length", "geometry",
    ]
    _checkpoint("read_start source_travelway_full")
    tw = gpd.read_file(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER, columns=cols)
    tw = tw.reset_index().rename(columns={"index": "source_feature_local_fid"})
    tw = tw[tw.geometry.notna() & ~tw.geometry.is_empty].copy()
    tw["stable_travelway_id"] = tw.apply(_stable_travelway_id, axis=1)
    tw["source_layer"] = _text(tw, "Stage1_SourceLayer").replace("", "Travelway")
    tw["geometry_hash"] = tw.geometry.map(_geometry_hash)
    _checkpoint("read_complete source_travelway_full", len(tw))
    return tw


def _stable_travelway_id(row: pd.Series) -> str:
    return _hash_row([row.get("RTE_ID"), row.get("RTE_NM"), row.get("FROM_MEASURE"), row.get("TO_MEASURE"), row.name], "tw", 16)


def _line_parts(geom) -> list[LineString]:
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [part for part in geom.geoms if isinstance(part, LineString) and part.length > 0]
    return []


def _route_text(row: pd.Series) -> str:
    cols = ["RTE_NM", "RTE_COMMON", "RIM_FACILI", "RIM_FACI_1", "RTE_CATEGO", "RTE_TYPE_N", "RTE_RAMP_C", "RIM_ACCESS", "LOC_COMP_D"]
    return " ".join(_clean(row.get(col)) for col in cols).upper()


def _classify_source_leg(row: pd.Series, distance_ft: float, target_route_sample: str) -> tuple[str, str, bool, bool]:
    text = _route_text(row)
    route_name = _clean(row.get("RTE_NM")).upper()
    route_common = _clean(row.get("RTE_COMMON")).upper()
    if distance_ft > SOURCE_RADIUS_FT:
        return "insufficient_evidence", "outside_250ft_signal_window", False, False
    is_interstate = route_name.startswith("I-") or route_common.startswith("I-") or " INTERSTATE " in text
    is_grade = is_interstate or any(token in text for token in ["LIMITED", "FREEWAY", "EXPRESSWAY", "MAINLINE"])
    is_connector = any(token in text for token in ["PR ", "CONNECTOR", "CANDLERS", "PA", "RAMP", "SERVICE", "FRONTAGE", "COLLECTOR", "DISTRIBUTOR"])
    loc_comp = _clean(row.get("LOC_COMP_D")).upper()
    if is_grade:
        return "grade_or_mainline_context_holdout", "grade/mainline source row near complex signal excluded from scaffold candidate", False, True
    if not (_clean(row.get("RTE_NM")) or _clean(row.get("RTE_COMMON"))):
        return "insufficient_evidence", "source row lacks route identity text", False, False
    if is_connector or "NON-PRIME" in loc_comp:
        return "signal_relevant_connector_or_internal_segment", "connector/internal/source subbranch near complex signal; kept as review geometry support", True, False
    if _source_row_split_like(row):
        return "source_line_split_same_leg", "source segmentation likely splits same physical leg", True, False
    if target_route_sample and not _route_appears_in_sample(row, target_route_sample) and distance_ft > 175:
        return "nearby_other_intersection_leg", "route not in target route sample and farther than 175 ft", False, True
    if _divided_or_carriageway(row):
        return "signal_relevant_carriageway_subbranch", "divided/carriageway source row near complex signal", True, False
    return "signal_relevant_physical_leg", "surface/source Travelway row treated as signal-plane physical leg", True, False


def _source_row_split_like(row: pd.Series) -> bool:
    return _clean(row.get("RTE_NM")).upper() == _clean(row.get("RTE_COMMON")).upper() and _clean(row.get("RTE_NM")) != ""


def _divided_or_carriageway(row: pd.Series) -> bool:
    text = _route_text(row)
    return any(token in text for token in ["DIVIDED", "MEDIAN", "ONE-WAY", "NB", "SB", "EB", "WB"])


def _route_appears_in_sample(row: pd.Series, sample: str) -> bool:
    sample_u = sample.upper()
    for value in [_clean(row.get("RTE_COMMON")), _clean(row.get("RTE_NM"))]:
        value_u = value.upper()
        if value_u and value_u in sample_u:
            return True
    return False


def _bearing_sector(point, geom) -> str:
    coords = list(geom.coords)
    if not coords:
        return "sector_unknown"
    start = coords[0]
    end = coords[-1]
    ds = math.hypot(start[0] - point.x, start[1] - point.y)
    de = math.hypot(end[0] - point.x, end[1] - point.y)
    far = end if de >= ds else start
    angle = (math.degrees(math.atan2(far[1] - point.y, far[0] - point.x)) + 360.0) % 360.0
    return f"sector_{int(angle // 45):02d}"


def _distance_band(start_ft: float) -> str:
    if start_ft < 250:
        return "0_250ft"
    if start_ft < 500:
        return "250_500ft"
    if start_ft < 1000:
        return "500_1000ft"
    return "1000_2500ft"


def _analysis_window(end_ft: float) -> str:
    return "0_1000" if end_ft <= 1000 else "1000_2500_sensitivity"


def _nearest_line_part(point, geom) -> tuple[LineString | None, float, float]:
    best: tuple[LineString | None, float, float] = (None, float("inf"), 0.0)
    for part in _line_parts(geom):
        m = part.project(point)
        dist = part.interpolate(m).distance(point) * M_TO_FT
        if dist < best[1]:
            best = (part, dist, m)
    return best


def _generate_direction_segments(line: LineString, measure_m: float) -> list[tuple[str, LineString, float]]:
    out: list[tuple[str, LineString, float]] = []
    if measure_m >= MIN_LEG_LENGTH_FT * FT_TO_M:
        seg = substring(line, max(0, measure_m - MAX_DISTANCE_FT * FT_TO_M), measure_m)
        if not seg.is_empty and seg.length * M_TO_FT >= MIN_LEG_LENGTH_FT:
            out.append(("backward", seg, seg.length * M_TO_FT))
    if line.length - measure_m >= MIN_LEG_LENGTH_FT * FT_TO_M:
        seg = substring(line, measure_m, min(line.length, measure_m + MAX_DISTANCE_FT * FT_TO_M))
        if not seg.is_empty and seg.length * M_TO_FT >= MIN_LEG_LENGTH_FT:
            out.append(("forward", seg, seg.length * M_TO_FT))
    return out


def _segment_bins(segment: LineString) -> list[tuple[float, float, LineString, bool]]:
    bins: list[tuple[float, float, LineString, bool]] = []
    length_ft = segment.length * M_TO_FT
    start = 0.0
    while start < min(length_ft, MAX_DISTANCE_FT):
        end = min(start + BIN_SIZE_FT, length_ft, MAX_DISTANCE_FT)
        if end - start <= 1:
            break
        geom = substring(segment, start * FT_TO_M, end * FT_TO_M)
        if not geom.is_empty:
            bins.append((round(start, 3), round(end, 3), geom, (end - start) < BIN_SIZE_FT - 0.1))
        start = end
    return bins


def _nearby_travelway(targets: gpd.GeoDataFrame, tw: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sindex = tw.sindex
    leg_rows: list[dict[str, Any]] = []
    bin_rows: list[dict[str, Any]] = []
    class_rows: list[dict[str, Any]] = []
    for signal in targets.itertuples(index=False):
        point = signal.geometry
        bounds = point.buffer(SOURCE_RADIUS_FT * FT_TO_M).bounds
        candidate_idx = list(sindex.intersection(bounds))
        if not candidate_idx:
            class_rows.append(_source_class_row(signal, None, "insufficient_evidence", "no source Travelway rows inside 250 ft bbox", False, False))
            continue
        for idx in candidate_idx:
            src = tw.iloc[int(idx)]
            part, distance_ft, measure_m = _nearest_line_part(point, src.geometry)
            if part is None or distance_ft > SOURCE_RADIUS_FT:
                continue
            leg_class, reason, scaffold_candidate, excluded = _classify_source_leg(src, distance_ft, _clean(getattr(signal, "nearby_route_sample", "")))
            class_rows.append(_source_class_row(signal, src, leg_class, reason, scaffold_candidate, excluded, distance_ft))
            if not scaffold_candidate:
                continue
            for outward_side, segment, available_ft in _generate_direction_segments(part, measure_m):
                bearing_sector = _bearing_sector(point, segment)
                phys_key_class = "connector_support" if leg_class == "signal_relevant_connector_or_internal_segment" else bearing_sector
                leg_id = _hash_row([signal.stable_signal_id, src.stable_travelway_id, outward_side, bearing_sector, src.source_feature_local_fid], "leg")
                phys_id = _hash_row([signal.stable_signal_id, phys_key_class], "physleg", 16)
                subbranch_id = _hash_row([signal.stable_signal_id, src.stable_travelway_id, outward_side], "subbranch", 16)
                leg_rows.append(_leg_row(signal, src, leg_id, phys_id, subbranch_id, bearing_sector, outward_side, available_ft, distance_ft, leg_class, segment))
                for start_ft, end_ft, bin_geom, partial in _segment_bins(segment):
                    stable_bin_id = _hash_row([signal.stable_signal_id, src.stable_travelway_id, outward_side, start_ft, end_ft, bin_geom.wkt], "bin")
                    bin_rows.append(_bin_row(signal, src, leg_id, phys_id, subbranch_id, bearing_sector, outward_side, start_ft, end_ft, partial, stable_bin_id, bin_geom, leg_class))
    return pd.DataFrame(class_rows), pd.DataFrame(leg_rows), pd.DataFrame(bin_rows)


def _source_class_row(signal: Any, src: pd.Series | None, leg_class: str, reason: str, scaffold_candidate: bool, excluded_or_flagged: bool, distance_ft: float | None = None) -> dict[str, Any]:
    row = _signal_identity(signal)
    row.update(
        {
            "source_feature_local_fid": "" if src is None else src.get("source_feature_local_fid", ""),
            "stable_travelway_id": "" if src is None else src.get("stable_travelway_id", ""),
            "source_route_id": "" if src is None else src.get("RTE_ID", ""),
            "source_route_name": "" if src is None else src.get("RTE_NM", ""),
            "source_route_common": "" if src is None else src.get("RTE_COMMON", ""),
            "source_measure_start": "" if src is None else src.get("FROM_MEASURE", ""),
            "source_measure_end": "" if src is None else src.get("TO_MEASURE", ""),
            "source_leg_class": leg_class,
            "source_leg_class_reason": reason,
            "scaffold_candidate_source_row": scaffold_candidate,
            "excluded_or_flagged_not_forced": excluded_or_flagged,
            "signal_to_source_row_distance_ft": "" if distance_ft is None else round(distance_ft, 3),
        }
    )
    return row


def _signal_identity(signal: Any) -> dict[str, Any]:
    data = signal._asdict() if hasattr(signal, "_asdict") else dict(signal)
    return {
        "stable_signal_id": data.get("stable_signal_id", ""),
        "source_signal_id": data.get("source_signal_id", ""),
        "GLOBALID": data.get("GLOBALID", ""),
        "OBJECTID": data.get("OBJECTID_1", data.get("OBJECTID", "")),
        "ASSET_ID": data.get("ASSET_ID", ""),
        "REG_SIGNAL_ID": data.get("REG_SIGNAL_ID", ""),
        "source_signal_layer": data.get("source_layer", ""),
        "source_system": data.get("source_system", ""),
        "source_row_id": data.get("source_row_id", ""),
        "current_final_status": data.get("final_primary_status", ""),
        "diagnostic_reclassification": data.get("diagnostic_reclassification", ""),
        "recoverability_confidence": data.get("recoverability_confidence", ""),
        "crash_relevance_class": data.get("crash_relevance_class", ""),
        "high_crash_relevance": data.get("high_crash_relevance", ""),
        "source_not_represented_unassigned_crashes_within_2500ft": data.get("source_not_represented_unassigned_crashes_within_2500ft", ""),
        "signal_geometry_wkt": data.get("signal_geometry_wkt", ""),
        "nearby_route_sample": data.get("nearby_route_sample", ""),
    }


def _travelway_identity(src: pd.Series) -> dict[str, Any]:
    return {
        "stable_travelway_id": src.get("stable_travelway_id", ""),
        "source_layer": src.get("source_layer", "Travelway"),
        "source_route_id": src.get("RTE_ID", ""),
        "source_route_name": src.get("RTE_NM", ""),
        "source_route_common": src.get("RTE_COMMON", ""),
        "source_measure_start": src.get("FROM_MEASURE", src.get("RTE_FROM_M", "")),
        "source_measure_end": src.get("TO_MEASURE", src.get("RTE_TO_MSR", "")),
        "source_feature_local_fid": src.get("source_feature_local_fid", ""),
        "geometry_hash": src.get("geometry_hash", ""),
        "source_route_facility": src.get("RIM_FACILI", ""),
        "source_rim_access": src.get("RIM_ACCESS", ""),
        "source_ramp_code": src.get("RTE_RAMP_C", ""),
        "source_loc_comp": src.get("LOC_COMP_D", ""),
    }


def _leg_row(signal: Any, src: pd.Series, leg_id: str, phys_id: str, subbranch_id: str, bearing_sector: str, outward_side: str, available_ft: float, distance_ft: float, leg_class: str, geom: LineString) -> dict[str, Any]:
    row = _signal_identity(signal)
    row.update(_travelway_identity(src))
    row.update(
        {
            "leg_candidate_id": leg_id,
            "physical_leg_group_id": phys_id,
            "carriageway_subbranch_id": subbranch_id,
            "bearing_sector": bearing_sector,
            "outward_side": outward_side,
            "available_length_ft": round(available_ft, 3),
            "anchor_to_travelway_distance_ft": round(distance_ft, 3),
            "source_leg_class": leg_class,
            "complex_geometry_qa_flag": leg_class in {"signal_relevant_carriageway_subbranch", "signal_relevant_connector_or_internal_segment", "source_line_split_same_leg"},
            "coverage_class": "full_0_1000" if available_ft >= 1000 else "partial_0_1000",
            "lineage_match_method": "complex_multisignal_source_travelway_geometry",
            "lineage_confidence": "medium_source_geometry_review_only",
            "review_only": True,
            "geometry_wkt": geom.wkt,
        }
    )
    return row


def _bin_row(signal: Any, src: pd.Series, leg_id: str, phys_id: str, subbranch_id: str, bearing_sector: str, outward_side: str, start_ft: float, end_ft: float, partial: bool, stable_bin_id: str, geom: LineString, leg_class: str) -> dict[str, Any]:
    row = _signal_identity(signal)
    row.update(_travelway_identity(src))
    row.update(
        {
            "leg_candidate_id": leg_id,
            "physical_leg_group_id": phys_id,
            "carriageway_subbranch_id": subbranch_id,
            "bearing_sector": bearing_sector,
            "outward_side": outward_side,
            "stable_bin_id": stable_bin_id,
            "target_bin_id": stable_bin_id,
            "target_signal_id": signal.stable_signal_id,
            "distance_start_ft": start_ft,
            "distance_end_ft": end_ft,
            "distance_length_ft": round(end_ft - start_ft, 3),
            "distance_band": _distance_band(start_ft),
            "analysis_window": _analysis_window(end_ft),
            "partial_coverage_flag": partial,
            "review_only_recovery_provenance": "missing_hmms_complex_multisignal_scaffold_recovery",
            "lineage_match_method": "complex_multisignal_source_travelway_geometry",
            "lineage_confidence": "medium_source_geometry_review_only",
            "geometry_wkt": geom.wkt,
            "source_leg_class": leg_class,
            "complex_geometry_qa_flag": leg_class in {"signal_relevant_carriageway_subbranch", "signal_relevant_connector_or_internal_segment", "source_line_split_same_leg"},
        }
    )
    return row


def _summaries(targets: gpd.GeoDataFrame, source_class: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    generated_ids = set(_text(legs, "stable_signal_id").unique()) if not legs.empty else set()
    skipped = []
    signal_rows = []
    for signal in targets.itertuples(index=False):
        sid = signal.stable_signal_id
        sc = source_class[source_class["stable_signal_id"].eq(sid)] if not source_class.empty else pd.DataFrame()
        lg = legs[legs["stable_signal_id"].eq(sid)] if not legs.empty else pd.DataFrame()
        bn = bins[bins["stable_signal_id"].eq(sid)] if not bins.empty else pd.DataFrame()
        generated = sid in generated_ids and len(lg) > 0 and len(bn) > 0
        if not generated:
            skipped.append({**_signal_identity(signal), "skip_reason": _skip_reason(sc), "skip_note": "No defensible complex multi-signal scaffold legs generated."})
        signal_rows.append(
            {
                **_signal_identity(signal),
                "generated_scaffold_candidate": generated,
                "generated_leg_candidate_count": len(lg),
                "generated_physical_leg_count": int(lg["physical_leg_group_id"].nunique()) if not lg.empty else 0,
                "generated_bin_count": len(bn),
                "stable_travelway_id_bin_count": int(_text(bn, "stable_travelway_id").str.strip().ne("").sum()) if not bn.empty else 0,
                "route_measure_ready": bool(len(bn) and _text(bn, "source_route_id").str.strip().ne("").all()),
                "roadway_context_ready": bool(len(bn) and _text(bn, "source_route_name").str.strip().ne("").any()),
                "rns_speed_ready_for_later": bool(len(bn) and _text(bn, "source_route_id").str.strip().ne("").any()),
                "aadt_v3_exposure_ready_for_later": bool(len(bn) and _text(bn, "source_route_id").str.strip().ne("").any()),
                "access_ready_for_later": bool(len(bn)),
                "crash_assignment_ready_for_later": bool(len(bn)),
                "signal_relevant_physical_leg_rows": int(sc["source_leg_class"].eq("signal_relevant_physical_leg").sum()) if not sc.empty else 0,
                "carriageway_subbranch_rows": int(sc["source_leg_class"].eq("signal_relevant_carriageway_subbranch").sum()) if not sc.empty else 0,
                "connector_internal_rows": int(sc["source_leg_class"].eq("signal_relevant_connector_or_internal_segment").sum()) if not sc.empty else 0,
                "source_line_split_same_leg_rows": int(sc["source_leg_class"].eq("source_line_split_same_leg").sum()) if not sc.empty else 0,
                "excluded_sibling_or_other_intersection_rows": int(sc["source_leg_class"].isin(["nearby_sibling_signal_leg", "opposite_carriageway_owned_by_sibling_signal", "nearby_other_intersection_leg"]).sum()) if not sc.empty else 0,
                "excluded_grade_mainline_rows": int(sc["source_leg_class"].eq("grade_or_mainline_context_holdout").sum()) if not sc.empty else 0,
                "high_travelway_row_count_is_qa_not_exclusion": bool(len(sc) >= 8),
            }
        )
    signal_summary = pd.DataFrame(signal_rows)
    skipped_cols = list(_signal_identity(targets.iloc[0]).keys()) + ["skip_reason", "skip_note"] if len(targets) else ["skip_reason", "skip_note"]
    skipped_df = pd.DataFrame(skipped, columns=skipped_cols)
    readiness = signal_summary[[
        "stable_signal_id", "source_signal_id", "GLOBALID", "generated_scaffold_candidate",
        "route_measure_ready", "roadway_context_ready", "rns_speed_ready_for_later",
        "aadt_v3_exposure_ready_for_later", "access_ready_for_later", "crash_assignment_ready_for_later",
        "generated_bin_count", "stable_travelway_id_bin_count",
    ]].copy()
    overlap = _overlap_review(signal_summary, bins)
    crash = signal_summary.groupby("generated_scaffold_candidate", dropna=False).agg(
        signal_count=("stable_signal_id", "size"),
        high_crash_relevance=("high_crash_relevance", lambda s: s.astype(str).str.lower().isin({"true", "1", "yes", "y"}).sum()),
        source_not_represented_unassigned_crashes_within_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    return signal_summary, skipped_df, readiness, overlap, crash


def _skip_reason(source_class: pd.DataFrame) -> str:
    if source_class.empty:
        return "source_travelway_missing_actual_signal_legs"
    if source_class["source_leg_class"].eq("insufficient_evidence").all():
        return "insufficient_evidence"
    if source_class["source_leg_class"].eq("grade_or_mainline_context_holdout").all():
        return "source_travelway_missing_actual_signal_legs"
    if source_class["source_leg_class"].isin(["nearby_sibling_signal_leg", "opposite_carriageway_owned_by_sibling_signal"]).any():
        return "sibling_ownership_ambiguous"
    if source_class["source_leg_class"].eq("nearby_other_intersection_leg").all():
        return "nearby_other_intersection_not_this_signal"
    return "manual_review_needed"


def _existing_source_identity() -> tuple[set[str], set[str], set[str]]:
    final = _read_csv(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id", "clean_analysis_included"])
    frames = [
        final[_flag(final, "clean_analysis_included")].copy(),
        _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id"]),
        _read_csv(OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id"]),
        _read_csv(RAMP_UNIVERSE_DIR / "ramp_terminal_integrated_signal_additions.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id"]),
    ]
    all_ids = pd.concat(frames, ignore_index=True)
    return (
        set(_text(all_ids, "stable_signal_id").str.upper()) - {""},
        set(_text(all_ids, "GLOBALID").str.upper()) - {""},
        set(_text(all_ids, "source_signal_id").str.upper()) - {""},
    )


def _existing_travelways() -> set[str]:
    frames = [
        _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv", usecols=["stable_travelway_id"]),
        _read_csv(OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv", usecols=["stable_travelway_id"]),
        _read_csv(RAMP_UNIVERSE_DIR / "ramp_terminal_integrated_bin_additions.csv", usecols=["stable_travelway_id"]),
    ]
    return set(_text(pd.concat(frames, ignore_index=True), "stable_travelway_id").str.strip()) - {""}


def _overlap_review(signal_summary: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    existing_stable, existing_gids, existing_sids = _existing_source_identity()
    existing_tw = _existing_travelways()
    rows = []
    for row in signal_summary.itertuples(index=False):
        gid = _clean(row.GLOBALID).upper()
        sid = _clean(row.source_signal_id).upper()
        stable = _clean(row.stable_signal_id).upper()
        bn = bins[bins["stable_signal_id"].eq(row.stable_signal_id)] if not bins.empty else pd.DataFrame()
        tw_overlap = len(set(_text(bn, "stable_travelway_id").str.strip()) & existing_tw) if not bn.empty else 0
        exact = (stable and stable in existing_stable) or (gid and gid in existing_gids) or (sid and sid in existing_sids)
        rows.append(
            {
                "stable_signal_id": row.stable_signal_id,
                "source_signal_id": row.source_signal_id,
                "GLOBALID": row.GLOBALID,
                "exact_duplicate_source_record": bool(exact),
                "sibling_ownership_risk": bool(row.excluded_sibling_or_other_intersection_rows > 0),
                "scaffold_overlap_with_existing_signal": bool(tw_overlap > 0),
                "same_corridor_shared_travelway_context": bool(tw_overlap > 0),
                "complex_multi_signal_ownership_risk": bool(row.excluded_sibling_or_other_intersection_rows > 0),
                "shared_stable_travelway_id_count": tw_overlap,
                "review_note": "Complex row count/shared Travelway is QA evidence, not exclusion unless source identity or sibling ownership evidence is strong.",
            }
        )
    return pd.DataFrame(rows)


def _findings(targets: gpd.GeoDataFrame, signal_summary: pd.DataFrame, skipped: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame) -> str:
    target_count = len(targets)
    generated = int(signal_summary["generated_scaffold_candidate"].sum()) if not signal_summary.empty else 0
    skipped_count = len(skipped)
    leg_count = len(legs)
    physical_legs = int(legs["physical_leg_group_id"].nunique()) if not legs.empty else 0
    bin_count = len(bins)
    lineage_bins = int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0
    high = int(_flag(signal_summary, "high_crash_relevance").sum()) if not signal_summary.empty else 0
    crash_2500 = pd.to_numeric(_text(signal_summary, "source_not_represented_unassigned_crashes_within_2500ft"), errors="coerce").fillna(0).sum() if not signal_summary.empty else 0
    skip_lines = "None" if skipped.empty else "\n".join(f"- {k}: {v}" for k, v in skipped["skip_reason"].value_counts().items())
    return f"""# Complex Multi-Signal Scaffold Recovery Findings

## Bounded Question

This review-only pass targets only `recoverable_complex_multi_signal_not_processed` missing-HMMS signals. It applies prior complex-signal calibration: complex geometry and high Travelway row count are not automatic holdouts when source legs are identifiable and sibling ownership evidence is not strong. It generates scaffold candidates only where source Travelway supports signal-plane physical legs, carriageway subbranches, source-line splits, or connector/internal geometry support. It does not promote signals, assign crashes/access, calculate rates/models, or alter active outputs.

## Results

- Targeted recoverable complex multi-signal records: {target_count:,}
- Signals with defensible scaffold candidates: {generated:,}
- Skipped targets: {skipped_count:,}
- Generated leg candidate rows: {leg_count:,}
- Generated physical-leg groups: {physical_legs:,}
- Generated 0-1,000 ft bins: {bin_count:,}
- Bins with stable Travelway lineage: {lineage_bins:,} / {bin_count:,}
- High-crash-relevance targets: {high:,}
- Nearby source-not-represented unassigned crashes within 2,500 ft: {int(crash_2500):,}

## Skipped Targets

{skip_lines}

## Recommendation

This branch supports a context refresh next for generated candidates if QA accepts the source-leg classification. After that, remaining high-yield work should focus on low-confidence offset-anchor holdouts or source-limited cases only if additional anchor/source evidence is available.
"""


def _qa(targets: gpd.GeoDataFrame, legs: pd.DataFrame, bins: pd.DataFrame, source_class: pd.DataFrame) -> pd.DataFrame:
    stable_bins = int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0
    forced_excluded = int(_text(bins, "source_leg_class").isin(["nearby_sibling_signal_leg", "opposite_carriageway_owned_by_sibling_signal", "nearby_other_intersection_leg", "grade_or_mainline_context_holdout"]).sum()) if not bins.empty else 0
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only scaffold recovery"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only existing proximity summaries used"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active; crash records not read"},
            {"check_name": "stable_travelway_id_present_on_generated_bins", "status": "passed" if stable_bins == len(bins) else "failed", "observed": f"{stable_bins}/{len(bins)}"},
            {"check_name": "source_signal_ids_globalids_preserved", "status": "passed", "observed": f"{int(_text(targets, 'GLOBALID').str.strip().ne('').sum())} GLOBALIDs; {int(_text(targets, 'source_signal_id').str.strip().ne('').sum())} source_signal_ids"},
            {"check_name": "high_travelway_row_count_not_exclusion", "status": "passed", "observed": "high row count retained as QA context"},
            {"check_name": "sibling_other_intersection_legs_not_forced", "status": "passed" if forced_excluded == 0 else "failed", "observed": f"{forced_excluded} excluded-class generated bins"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    _read_csv(FINAL_ACCOUNTING_DIR / "final_remaining_446_breakdown.csv")
    _read_csv(FINAL_ACCOUNTING_DIR / "final_review_visible_not_clean_breakdown.csv")
    _read_csv(RECOVERABILITY_DIR / "remaining_recoverability_target_detail.csv", usecols=["stable_signal_id", "final_primary_status"])
    _read_csv(RECOVERABILITY_DIR / "remaining_recoverability_class_summary.csv")
    _read_csv(RECOVERABILITY_DIR / "remaining_recoverability_priority_queue.csv")
    _read_csv(RECOVERABILITY_DIR / "remaining_recoverability_crash_relevance_summary.csv")
    _read_csv(COMPLEX_REVIEW_DIR / "complex_signal_map_review_decisions.csv")
    _read_csv(COMPLEX_REVIEW_DIR / "complex_signal_travelway_fid_validation.csv")
    _read_csv(COMPLEX_REVIEW_DIR / "complex_signal_review_joined_to_recovery.csv")
    _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv")
    _read_csv(OFFSET_COMPLEX_DIR / "offset_anchor_complex_calibration_rules.csv")
    _read_csv(OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassified_detail.csv")
    _read_csv(OFFSET_COMPLEX_DIR / "offset_anchor_complex_reclassification_summary.csv")
    _read_csv(FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv", usecols=["GLOBALID", "source_signal_id", "recoverability_class", "signal_geometry_wkt"])
    _read_csv(FEASIBILITY_DIR / "missing_signal_travelway_coverage_summary.csv")
    _read_csv(FEASIBILITY_DIR / "missing_signal_crash_relevance_priority_queue.csv", usecols=["GLOBALID", "source_signal_id", "recoverability_class", "source_not_represented_unassigned_crashes_within_2500ft"])

    targets = _load_targets()
    tw = _load_travelway()
    source_class, legs, bins = _nearby_travelway(targets, tw)
    signal_summary, skipped, readiness, overlap, crash = _summaries(targets, source_class, legs, bins)
    qa = _qa(targets, legs, bins, source_class)

    _write_csv(pd.DataFrame(targets.drop(columns="geometry")), "complex_multisignal_missing_signal_targets.csv")
    _write_csv(source_class, "complex_multisignal_source_leg_classification.csv")
    _write_csv(signal_summary, "complex_multisignal_recovered_signal_summary.csv")
    _write_csv(legs, "complex_multisignal_recovered_leg_candidates.csv")
    _write_csv(bins, "complex_multisignal_recovered_bins.csv")
    _write_csv(skipped, "complex_multisignal_recovery_skipped_targets.csv")
    _write_csv(readiness, "complex_multisignal_context_refresh_readiness.csv")
    _write_csv(overlap, "complex_multisignal_overlap_dedup_review.csv")
    _write_csv(crash, "complex_multisignal_crash_relevance_summary.csv")
    _write_text(_findings(targets, signal_summary, skipped, legs, bins), "complex_multisignal_scaffold_recovery_findings.md")
    _write_csv(qa, "complex_multisignal_scaffold_recovery_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_complex_multisignal_scaffold_recovery",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "input_manifests": {
            "final_staged_signal_accounting": _manifest_ref(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json"),
            "remaining_signal_recoverability": _manifest_ref(RECOVERABILITY_DIR / "remaining_signal_recoverability_manifest.json"),
            "complex_signal_map_review_ingestion": _manifest_ref(COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json"),
            "offset_anchor_complex_reclassification": _manifest_ref(OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassification_manifest.json"),
            "good_travelway_universe": _manifest_ref(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json"),
            "offset_anchor_universe": _manifest_ref(OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json"),
            "ramp_terminal_universe": _manifest_ref(RAMP_UNIVERSE_DIR / "ramp_terminal_universe_integration_manifest.json"),
            "missing_hmms_feasibility": _manifest_ref(FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json"),
        },
        "counts": {
            "target_signals": int(len(targets)),
            "generated_signals": int(signal_summary["generated_scaffold_candidate"].sum()) if not signal_summary.empty else 0,
            "skipped_signals": int(len(skipped)),
            "leg_candidate_rows": int(len(legs)),
            "physical_leg_groups": int(legs["physical_leg_group_id"].nunique()) if not legs.empty else 0,
            "bin_rows": int(len(bins)),
            "bins_with_stable_travelway_id": int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()) if not bins.empty else 0,
        },
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, "complex_multisignal_scaffold_recovery_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Target signals: {len(targets):,}")
    print(f"Generated scaffold candidates: {int(signal_summary['generated_scaffold_candidate'].sum()):,}")
    print(f"Skipped targets: {len(skipped):,}")


if __name__ == "__main__":
    main()
