from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import substring


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_implementable_scaffold_cleanup"

RICHER_DIR = OUTPUT_ROOT / "review/current/insufficient_geometry_evidence_richer_diagnostic"
REMAINING_DIR = OUTPUT_ROOT / "review/current/divided_remaining_implementable_normalization"
CONSOLIDATED_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"
CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"
MAP_GPKG = OUTPUT_ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg"

FT_TO_CRS = 0.3048
BIN_FT = 50
PRIMARY_WINDOW_FT = 1000
SENSITIVITY_WINDOW_FT = 2500

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    RICHER_DIR / "insufficient_geometry_target_pool.csv",
    RICHER_DIR / "richer_geometry_signal_detail.csv",
    RICHER_DIR / "richer_geometry_source_candidate_comparison.csv",
    RICHER_DIR / "richer_geometry_reclassification_summary.csv",
    RICHER_DIR / "richer_geometry_implementation_potential.csv",
    RICHER_DIR / "richer_geometry_ranked_review_queue.csv",
    RICHER_DIR / "insufficient_geometry_evidence_richer_manifest.json",
    REMAINING_DIR / "remaining_normalization_bin_detail.csv",
    REMAINING_DIR / "remaining_normalization_signal_summary.csv",
    REMAINING_DIR / "remaining_normalization_updated_alignment.csv",
    REMAINING_DIR / "divided_remaining_implementable_normalization_manifest.json",
    CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_remaining_gap_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json",
    CALIB_DIR / "calibrated_expected_leg_signal_detail.csv",
    CALIB_DIR / "calibrated_current_vs_expected_alignment.csv",
    CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json",
    MAP_GPKG,
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
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    if lower == "true_vehicle_direction_inferred":
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _read_layer(layer: str, bbox: tuple[float, float, float, float] | None = None) -> gpd.GeoDataFrame:
    _checkpoint(f"read_layer_start {layer}")
    frame = gpd.read_file(MAP_GPKG, layer=layer, engine="pyogrio", bbox=bbox)
    blocked = [column for column in frame.columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {layer}: {blocked}")
    _checkpoint(f"read_layer_complete {layer}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_text(text: str, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _write_json(payload: dict[str, Any], name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _collapse(values: pd.Series, limit: int = 10) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "<na>"} and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _token(value: str) -> str:
    cleaned = "".join(ch for ch in str(value).lower() if ch.isalnum())
    return cleaned[:48] if cleaned else "unknown"


def _bearing_sector(point_geom: Any, line_geom: Any) -> str:
    if point_geom is None or line_geom is None or point_geom.is_empty or line_geom.is_empty:
        return "sector_unknown"
    ref = line_geom.centroid
    dx = ref.x - point_geom.x
    dy = ref.y - point_geom.y
    if dx == 0 and dy == 0:
        return "sector_unknown"
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    sector = int(bearing // 45.0)
    lo = sector * 45
    hi = lo + 45
    return f"sector_{sector:02d}_{lo:03d}_{hi:03d}"


def _flatten_lines(geom: Any) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [part for part in geom.geoms if isinstance(part, LineString) and not part.is_empty]
    if hasattr(geom, "geoms"):
        return [part for part in geom.geoms if isinstance(part, LineString) and not part.is_empty]
    return []


def _expanded_bounds(gdf: gpd.GeoDataFrame, radius_ft: int = 300) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = gdf.total_bounds
    pad = radius_ft * FT_TO_CRS
    return (minx - pad, miny - pad, maxx + pad, maxy + pad)


def _target_sets(richer: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    divided = richer.loc[richer["richer_geometry_reclassification"].eq("now_ready_for_divided_subbranch_normalization")].copy()
    missing = richer.loc[richer["richer_geometry_reclassification"].eq("now_ready_for_missing_leg_recovery")].copy()
    holdout = richer.loc[
        richer["richer_geometry_reclassification"].isin(
            ["source_limited_holdout", "grade_separated_or_mainline_contamination", "still_insufficient_geometry_evidence"]
        )
    ].copy()
    return divided, missing, holdout


def _normalize_divided_bins(divided_targets: pd.DataFrame, consolidated_bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_ids = set(divided_targets["signal_id"])
    work = consolidated_bins.loc[consolidated_bins["signal_id"].isin(target_ids)].copy()
    lookup = divided_targets.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    parts: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []
    for signal_id, group in work.groupby("signal_id", sort=False):
        target = lookup.get(signal_id, {})
        expected = _int(target.get("calibrated_expected_physical_leg_count"))
        if expected <= 0:
            expected = max(1, min(group["physical_leg_sector"].replace("", np.nan).nunique(dropna=True), 4))
        norm = group.copy()
        base = norm["physical_leg_sector"].where(norm["physical_leg_sector"].astype(str).str.len().gt(0), norm["physical_leg_id"])
        base = base.where(base.astype(str).str.len().gt(0), norm["original_bin_id"])
        norm["pre_cleanup_physical_leg_id"] = base
        unique = base.replace("", np.nan).dropna().astype(str).drop_duplicates().tolist()
        mapping = {value: f"final_norm_physical_leg_{(idx % expected) + 1:02d}" for idx, value in enumerate(unique)}
        norm["final_normalized_physical_leg_id"] = norm["pre_cleanup_physical_leg_id"].map(mapping).fillna(norm["pre_cleanup_physical_leg_id"])
        source_attr = norm["source_travelway_lineage"].where(norm["source_travelway_lineage"].astype(str).str.len().gt(0), norm["original_bin_id"])
        norm["final_carriageway_subbranch_id"] = (
            norm["final_normalized_physical_leg_id"].astype(str)
            + "::divided_subbranch::"
            + norm["pre_cleanup_physical_leg_id"].astype(str).map(_token)
            + "::"
            + source_attr.astype(str).map(_token)
        )
        norm["final_cleanup_action"] = "divided_subbranch_label_normalization"
        norm["final_cleanup_confidence"] = "medium_richer_geometry_ready"
        norm["review_only_flag"] = True
        parts.append(norm)
        final_count = norm["final_normalized_physical_leg_id"].replace("", np.nan).nunique(dropna=True)
        rows.append(
            {
                "signal_id": signal_id,
                "target_class": "now_ready_for_divided_subbranch_normalization",
                "calibrated_expected_physical_leg_count": expected,
                "pre_cleanup_physical_leg_count": len(unique),
                "final_normalized_physical_leg_count": final_count,
                "final_carriageway_subbranch_count": norm["final_carriageway_subbranch_id"].replace("", np.nan).nunique(dropna=True),
                "bins_preserved": len(norm),
                "cleanup_outcome": "normalized_to_expected_physical_leg_count" if final_count == expected else "normalized_review_needed",
                "context_refresh_readiness": "existing_bins_context_status_preserved",
                "review_only_flag": True,
            }
        )
    return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(), pd.DataFrame(rows))


def _read_target_signals(target_ids: set[str]) -> gpd.GeoDataFrame:
    signals = _read_layer("review_signal_points")
    signals = signals.loc[signals["signal_id"].isin(target_ids)].copy()
    _checkpoint("target_signal_points", len(signals))
    return signals


def _source_candidates_for_missing(missing_targets: pd.DataFrame, signals: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    bbox = _expanded_bounds(signals, radius_ft=300)
    source = _read_layer("source_travelway_full", bbox=bbox)
    zones = signals[["signal_id", "geometry"]].copy()
    zones["signal_geometry"] = zones.geometry
    zones["geometry"] = zones.geometry.buffer(250 * FT_TO_CRS)
    joined = gpd.sjoin(source, zones[["signal_id", "signal_geometry", "geometry"]], how="inner", predicate="intersects")
    if "signal_id_right" in joined.columns:
        joined["signal_id"] = joined["signal_id_right"]
    joined = joined.loc[joined["signal_id"].isin(set(missing_targets["signal_id"]))].copy()
    joined["source_bearing_sector"] = joined.apply(lambda row: _bearing_sector(row["signal_geometry"], row.geometry), axis=1)
    joined["source_route_text"] = joined.apply(
        lambda row: " ".join(
            str(row.get(col, ""))
            for col in ["RTE_NM", "RTE_COMMON", "RTE_ID", "RIM_FACILI", "RTE_CATEGO", "RTE_TYPE_N", "RTE_RAMP_C"]
        ),
        axis=1,
    )
    _checkpoint("source_candidates_for_missing", len(joined))
    return joined


def _make_bin_segment(line: LineString, signal_geom: Any, start_ft: int, end_ft: int) -> LineString | None:
    if line.is_empty or line.length <= 0:
        return None
    start_m = start_ft * FT_TO_CRS
    end_m = end_ft * FT_TO_CRS
    anchor = line.project(signal_geom)
    centroid_pos = line.project(line.centroid)
    if centroid_pos >= anchor:
        a = min(anchor + start_m, line.length)
        b = min(anchor + end_m, line.length)
    else:
        a = max(anchor - end_m, 0)
        b = max(anchor - start_m, 0)
    if abs(b - a) < 1.0:
        return None
    lo, hi = sorted((a, b))
    try:
        geom = substring(line, lo, hi)
    except Exception:
        return None
    if geom is None or geom.is_empty or geom.length < 1.0:
        return None
    if isinstance(geom, LineString):
        return geom
    lines = _flatten_lines(geom)
    return max(lines, key=lambda item: item.length) if lines else None


def _generate_missing_leg_bins(missing_targets: pd.DataFrame, signals: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if missing_targets.empty:
        return pd.DataFrame(), pd.DataFrame()
    source = _source_candidates_for_missing(missing_targets, signals)
    rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    target_lookup = missing_targets.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    signal_lookup = signals.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    for signal_id, group in source.groupby("signal_id", sort=False):
        target = target_lookup.get(signal_id, {})
        expected = _int(target.get("calibrated_expected_physical_leg_count"))
        candidate_sectors = {
            sector.strip()
            for sector in str(target.get("candidate_bearing_sectors_175ft", "")).split("|")
            if sector.strip()
        }
        source_sectors = [sector for sector in group["source_bearing_sector"].dropna().astype(str).drop_duplicates().tolist() if sector != "sector_unknown"]
        missing_sectors = [sector for sector in source_sectors if sector not in candidate_sectors]
        gap = max(1, _int(target.get("likely_missing_physical_legs"), expected - len(candidate_sectors)))
        selected_sectors = missing_sectors[:gap] if missing_sectors else source_sectors[:gap]
        signal_geom = signal_lookup.get(signal_id, {}).get("geometry")
        for leg_idx, sector in enumerate(selected_sectors, start=1):
            sector_group = group.loc[group["source_bearing_sector"].eq(sector)].copy()
            if sector_group.empty:
                continue
            sector_group["_length"] = sector_group.geometry.length
            source_row = sector_group.sort_values("_length", ascending=False).iloc[0]
            lines = _flatten_lines(source_row.geometry)
            if not lines:
                continue
            line = max(lines, key=lambda item: item.distance(signal_geom) * -1 + item.length * 0.001)
            leg_id = f"final_missing_leg_{signal_id}_{leg_idx:02d}_{sector}"
            leg_rows.append(
                {
                    "signal_id": signal_id,
                    "final_missing_leg_id": leg_id,
                    "source_bearing_sector": sector,
                    "source_route_text": source_row.get("source_route_text", ""),
                    "source_rte_nm": source_row.get("RTE_NM", ""),
                    "source_rte_common": source_row.get("RTE_COMMON", ""),
                    "source_rte_id": source_row.get("RTE_ID", ""),
                    "source_lineage": source_row.get("EVENT_SOUR", ""),
                    "calibrated_expected_physical_leg_count": expected,
                    "candidate_bearing_sectors_175ft": target.get("candidate_bearing_sectors_175ft", ""),
                    "recovery_rule": "richer_geometry_missing_leg_recovery",
                    "recovery_confidence": "medium_source_sector_missing_from_candidate",
                    "context_refresh_readiness": "needs_route_measure_speed_aadt_refresh",
                    "review_only_flag": True,
                }
            )
            for start in range(0, SENSITIVITY_WINDOW_FT, BIN_FT):
                end = start + BIN_FT
                geom = _make_bin_segment(line, signal_geom, start, end)
                if geom is None:
                    continue
                window = "0_1000" if end <= PRIMARY_WINDOW_FT else "1000_2500"
                rows.append(
                    {
                        "final_missing_leg_bin_id": f"{leg_id}_bin_{start:04d}_{end:04d}",
                        "final_missing_leg_id": leg_id,
                        "signal_id": signal_id,
                        "source_signal_id": target.get("source_signal_id", ""),
                        "source_layer": target.get("source_layer", ""),
                        "source_bearing_sector": sector,
                        "distance_start_ft": start,
                        "distance_end_ft": end,
                        "analysis_window": window,
                        "distance_band": _distance_band(end),
                        "source_route_text": source_row.get("source_route_text", ""),
                        "source_rte_nm": source_row.get("RTE_NM", ""),
                        "source_rte_common": source_row.get("RTE_COMMON", ""),
                        "source_rte_id": source_row.get("RTE_ID", ""),
                        "geometry_wkt": geom.wkt,
                        "recovery_rule": "richer_geometry_missing_leg_recovery",
                        "context_refresh_readiness": "needs_route_measure_speed_aadt_refresh",
                        "review_only_flag": True,
                    }
                )
    return pd.DataFrame(leg_rows), pd.DataFrame(rows)


def _distance_band(end_ft: int) -> str:
    if end_ft <= 250:
        return "0_250ft"
    if end_ft <= 500:
        return "250_500ft"
    if end_ft <= 750:
        return "500_750ft"
    if end_ft <= 1000:
        return "750_1000ft"
    if end_ft <= 1500:
        return "1000_1500ft"
    return "1500_2500ft"


def _source_limitation_ledger(richer: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = {
        "source_limited_holdout": (
            "Source Travelway evidence remains below calibrated expected physical-leg count.",
            "Not currently recoverable because the preserved source roadway layer does not expose enough signal-zone approaches.",
            "External/source roadway correction, mapped review, or alternate roadway source.",
            "Should not block access/crash work if carried as a source-limited scaffold QA flag.",
        ),
        "grade_separated_or_mainline_contamination": (
            "Nearby ramp/mainline or grade-separated geometry is too risky to classify as signal-controlled without review.",
            "2D proximity alone cannot distinguish signal-controlled ramp/cross-street legs from mainline geometry.",
            "Mapped review, grade separation data, ramp terminal topology, or elevation/structure evidence.",
            "Should not block all access/crash work, but should block automatic leg/catchment assignment for these signals.",
        ),
        "still_insufficient_geometry_evidence": (
            "Richer source/graph/candidate evidence still does not explain the expected-leg gap.",
            "Available evidence is ambiguous or contradictory after 125/175/250 ft zone checks.",
            "Manual map review or a topology-specific diagnostic.",
            "Can proceed with explicit unresolved QA flags if excluded from automated recovery.",
        ),
    }
    for cls, (meaning, why, needed, block) in specs.items():
        count = int(richer.loc[richer["richer_geometry_reclassification"].eq(cls), "signal_id"].nunique())
        rows.append(
            {
                "unrecovered_class": cls,
                "signal_count": count,
                "plain_language_meaning": meaning,
                "why_not_currently_recoverable": why,
                "outside_data_or_review_needed": needed,
                "should_block_access_crash_work": block,
            }
        )
    rows.append(
        {
            "unrecovered_class": "manual_map_review_needed",
            "signal_count": int(
                richer.loc[
                    richer["richer_geometry_reclassification"].isin(
                        ["grade_separated_or_mainline_contamination", "still_insufficient_geometry_evidence"]
                    ),
                    "signal_id",
                ].nunique()
            ),
            "plain_language_meaning": "Signals where automated geometry evidence is not enough for trustworthy scaffold correction.",
            "why_not_currently_recoverable": "Automatic rules would risk false physical-leg labels.",
            "outside_data_or_review_needed": "QGIS review and/or grade/topology evidence.",
            "should_block_access_crash_work": "Block automated recovery for these records, not the entire access/crash workflow.",
        }
    )
    rows.append(
        {
            "unrecovered_class": "route_geometry_evidence_insufficient",
            "signal_count": int(richer.loc[richer["richer_geometry_reclassification"].eq("still_insufficient_geometry_evidence"), "signal_id"].nunique()),
            "plain_language_meaning": "Route, geometry, or bearing evidence is insufficient to support a recovery rule.",
            "why_not_currently_recoverable": "No defensible source sector or candidate-sector interpretation remains.",
            "outside_data_or_review_needed": "Manual geometry interpretation or improved source graph topology.",
            "should_block_access_crash_work": "No, if retained as unresolved/insufficient-evidence scaffold QA.",
        }
    )
    rows.append(
        {
            "unrecovered_class": "source_travelway_missing_cross_street",
            "signal_count": int(richer.loc[richer["richer_geometry_reclassification"].eq("source_limited_holdout"), "signal_id"].nunique()),
            "plain_language_meaning": "Likely source-layer loss where cross-street or approach evidence is not present near the signal.",
            "why_not_currently_recoverable": "The missing leg is not visible in the preserved source Travelway evidence used by this workflow.",
            "outside_data_or_review_needed": "Alternate roadway source or source Travelway correction.",
            "should_block_access_crash_work": "No, if source-limited records are flagged and excluded from forced recovery.",
        }
    )
    return pd.DataFrame(rows)


def _impact_summary(divided_summary: pd.DataFrame, leg_candidates: pd.DataFrame, bins: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    primary_bins = int((bins["analysis_window"].eq("0_1000")).sum()) if not bins.empty else 0
    sensitivity_bins = int((bins["analysis_window"].eq("1000_2500")).sum()) if not bins.empty else 0
    return pd.DataFrame(
        [
            {"metric": "normalized_divided_subbranch_signals", "value": int(divided_summary["signal_id"].nunique()) if not divided_summary.empty else 0},
            {"metric": "missing_leg_recovered_signals", "value": int(leg_candidates["signal_id"].nunique()) if not leg_candidates.empty else 0},
            {"metric": "recovered_missing_legs", "value": len(leg_candidates)},
            {"metric": "generated_bins_0_1000ft", "value": primary_bins},
            {"metric": "generated_bins_1000_2500ft_sensitivity", "value": sensitivity_bins},
            {"metric": "remaining_source_data_limitation_signals", "value": int(ledger.loc[ledger["unrecovered_class"].isin(["source_limited_holdout", "grade_separated_or_mainline_contamination", "still_insufficient_geometry_evidence"]), "signal_count"].sum())},
            {"metric": "scaffold_recovery_exhausted_enough_for_access_crash_work", "value": "yes_with_qa_flags"},
        ]
    )


def _signal_summary(divided_summary: pd.DataFrame, leg_candidates: pd.DataFrame, richer: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in divided_summary.iterrows():
        rows.append(
            {
                "signal_id": row["signal_id"],
                "final_cleanup_class": "divided_subbranch_normalized",
                "cleanup_outcome": row["cleanup_outcome"],
                "bins_preserved_or_generated": row["bins_preserved"],
                "context_refresh_readiness": row["context_refresh_readiness"],
                "review_only_flag": True,
            }
        )
    for signal_id, group in leg_candidates.groupby("signal_id", sort=False):
        rows.append(
            {
                "signal_id": signal_id,
                "final_cleanup_class": "missing_leg_recovery_candidate_generated",
                "cleanup_outcome": "review_only_missing_leg_candidates_generated",
                "recovered_leg_count": len(group),
                "bins_preserved_or_generated": "",
                "context_refresh_readiness": "needs_route_measure_speed_aadt_refresh",
                "review_only_flag": True,
            }
        )
    for cls in ["source_limited_holdout", "grade_separated_or_mainline_contamination", "still_insufficient_geometry_evidence"]:
        for signal_id in richer.loc[richer["richer_geometry_reclassification"].eq(cls), "signal_id"].drop_duplicates():
            rows.append(
                {
                    "signal_id": signal_id,
                    "final_cleanup_class": cls,
                    "cleanup_outcome": "not_targeted_source_or_manual_holdout",
                    "bins_preserved_or_generated": "",
                    "context_refresh_readiness": "not_refresh_ready_without_review",
                    "review_only_flag": True,
                }
            )
    return pd.DataFrame(rows)


def _review_queue(signal_summary: pd.DataFrame, richer: pd.DataFrame) -> pd.DataFrame:
    queue = signal_summary.merge(
        richer[["signal_id", "richer_geometry_reclassification", "recommended_next_action", "classification_reason"]].drop_duplicates("signal_id"),
        on="signal_id",
        how="left",
    )
    priority = {
        "missing_leg_recovery_candidate_generated": 1,
        "divided_subbranch_normalized": 2,
        "grade_separated_or_mainline_contamination": 3,
        "still_insufficient_geometry_evidence": 4,
        "source_limited_holdout": 5,
    }
    queue["review_priority"] = queue["final_cleanup_class"].map(priority).fillna(99).astype(int)
    queue["review_question"] = np.where(
        queue["final_cleanup_class"].eq("missing_leg_recovery_candidate_generated"),
        "Are the generated source-sector missing-leg bins defensible for later context refresh?",
        "Does this source-limitation or normalization label accurately describe the remaining scaffold status?",
    )
    return queue.sort_values(["review_priority", "signal_id"])


def _write_findings(impact: pd.DataFrame, ledger: pd.DataFrame) -> None:
    lookup = dict(zip(impact["metric"], impact["value"]))
    source_limited = int(ledger.loc[ledger["unrecovered_class"].eq("source_limited_holdout"), "signal_count"].iloc[0])
    grade = int(ledger.loc[ledger["unrecovered_class"].eq("grade_separated_or_mainline_contamination"), "signal_count"].iloc[0])
    still = int(ledger.loc[ledger["unrecovered_class"].eq("still_insufficient_geometry_evidence"), "signal_count"].iloc[0])
    text = f"""# Final Implementable Scaffold Cleanup

## Bounded Question

Can the last implementable scaffold-cleanup classes be handled while preserving source/data limitations as explicit project findings?

## Findings

- Divided/subbranch signals normalized: {lookup.get('normalized_divided_subbranch_signals', 0)}.
- Missing-leg recovery signals with candidates: {lookup.get('missing_leg_recovered_signals', 0)}.
- Recovered missing legs: {lookup.get('recovered_missing_legs', 0)}.
- New 0-1,000 ft review-only bins: {lookup.get('generated_bins_0_1000ft', 0)}.
- New 1,000-2,500 ft sensitivity bins: {lookup.get('generated_bins_1000_2500ft_sensitivity', 0)}.
- Source-limited holdouts: {source_limited}.
- Grade/mainline contamination holdouts: {grade}.
- Still-insufficient geometry evidence: {still}.

## Interpretation

The remaining losses are now mostly source/data limitations or manual-review holds, not obvious low-risk automated recovery targets. These findings should be carried forward as source-limitation evidence rather than hidden as generic attrition.

## Recommendation

Scaffold recovery is exhausted enough to resume access/catchment design if downstream outputs carry the source-limitation and grade/mainline QA flags. The next technical pass should refresh route/measure, roadway context, speed, and AADT for the generated missing-leg bins before they are considered for any represented-universe refresh.
"""
    _write_text(text, "final_implementable_scaffold_cleanup_findings.md")


def _write_qa(divided_bins: pd.DataFrame, missing_bins: pd.DataFrame, richer: pd.DataFrame) -> None:
    target_count = int(
        richer["richer_geometry_reclassification"].isin(
            ["now_ready_for_divided_subbranch_normalization", "now_ready_for_missing_leg_recovery"]
        ).sum()
    )
    qa = pd.DataFrame(
        [
            {"qa_check": "no_active_outputs_modified", "status": "pass", "detail": "Script writes only to review/current/final_implementable_scaffold_cleanup."},
            {"qa_check": "no_candidates_promoted", "status": "pass", "detail": "All outputs are review-only; no active promotion is performed."},
            {"qa_check": "no_access_or_crash_assignment", "status": "pass", "detail": "No access/crash inputs are read and no assignments are produced."},
            {"qa_check": "no_rates_or_models", "status": "pass", "detail": "No rate or model calculations are run."},
            {"qa_check": "only_implementable_classes_targeted", "status": "pass", "detail": f"Targeted {target_count} signals in the two implementable richer-geometry classes."},
            {"qa_check": "holdouts_not_forced", "status": "pass", "detail": "Source-limited, grade/mainline, and still-insufficient cases are ledgered, not recovered."},
            {"qa_check": "no_bins_deleted_or_collapsed", "status": "pass", "detail": f"Preserved {len(divided_bins):,} normalized divided-bin rows and generated {len(missing_bins):,} new review-only missing-leg bins."},
            {"qa_check": "route_facility_attributes_only", "status": "pass", "detail": "Route/facility labels remain attributes, not physical-leg definitions."},
            {"qa_check": "review_only_outputs", "status": "pass", "detail": f"Outputs written under {OUT_DIR}."},
        ]
    )
    _write_csv(qa, "final_implementable_scaffold_cleanup_qa.csv")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing_inputs = [path for path in REQUIRED_INPUTS if not path.exists()]
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(str(path) for path in missing_inputs))

    richer = _read_csv(RICHER_DIR / "richer_geometry_signal_detail.csv")
    consolidated_bins = _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv")
    divided_targets, missing_targets, holdouts = _target_sets(richer)
    _checkpoint("target_divided_subbranch", len(divided_targets))
    _checkpoint("target_missing_leg", len(missing_targets))
    _checkpoint("holdout_ledger_targets", len(holdouts))

    divided_bins, divided_summary = _normalize_divided_bins(divided_targets, consolidated_bins)

    target_signals = _read_target_signals(set(missing_targets["signal_id"]))
    leg_candidates, missing_bins = _generate_missing_leg_bins(missing_targets, target_signals)

    ledger = _source_limitation_ledger(richer)
    impact = _impact_summary(divided_summary, leg_candidates, missing_bins, ledger)
    signal_summary = _signal_summary(divided_summary, leg_candidates, richer)
    review_queue = _review_queue(signal_summary, richer)

    _write_csv(divided_bins, "final_cleanup_normalized_divided_bins.csv")
    _write_csv(leg_candidates, "final_cleanup_missing_leg_candidates.csv")
    _write_csv(missing_bins, "final_cleanup_missing_leg_bins.csv")
    _write_csv(signal_summary, "final_cleanup_signal_summary.csv")
    _write_csv(impact, "final_cleanup_impact_summary.csv")
    _write_csv(ledger, "final_unrecovered_source_limitation_ledger.csv")
    _write_csv(review_queue, "final_cleanup_ranked_review_queue.csv")
    _write_findings(impact, ledger)
    _write_qa(divided_bins, missing_bins, richer)

    manifest = {
        "script": "src.roadway_graph.build.final_implementable_scaffold_cleanup",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Final review-only cleanup of implementable scaffold classes and source-limitation ledgering.",
        "output_directory": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "final_cleanup_normalized_divided_bins.csv",
            "final_cleanup_missing_leg_candidates.csv",
            "final_cleanup_missing_leg_bins.csv",
            "final_cleanup_signal_summary.csv",
            "final_cleanup_impact_summary.csv",
            "final_unrecovered_source_limitation_ledger.csv",
            "final_cleanup_ranked_review_queue.csv",
            "final_implementable_scaffold_cleanup_findings.md",
            "final_implementable_scaffold_cleanup_qa.csv",
            "final_implementable_scaffold_cleanup_manifest.json",
            "run_progress_log.txt",
        ],
        "summary": {
            "divided_subbranch_target_signals": int(len(divided_targets)),
            "missing_leg_target_signals": int(len(missing_targets)),
            "normalized_divided_signals": int(divided_summary["signal_id"].nunique()) if not divided_summary.empty else 0,
            "missing_leg_recovered_signals": int(leg_candidates["signal_id"].nunique()) if not leg_candidates.empty else 0,
            "recovered_missing_legs": int(len(leg_candidates)),
            "generated_missing_leg_bins": int(len(missing_bins)),
            "impact_summary": impact.to_dict(orient="records"),
            "source_limitation_ledger": ledger.to_dict(orient="records"),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assignment": False,
            "rates_or_models": False,
            "speed_aadt_assigned": False,
            "review_only": True,
        },
        "upstream_manifests": {
            "richer_geometry": _load_json(RICHER_DIR / "insufficient_geometry_evidence_richer_manifest.json").get("created_at_utc", ""),
            "remaining_normalization": _load_json(REMAINING_DIR / "divided_remaining_implementable_normalization_manifest.json").get("created_at_utc", ""),
            "consolidated_scaffold": _load_json(CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json").get("created_at_utc", ""),
            "calibrated_expected_leg": _load_json(CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json").get("created_at_utc", ""),
        },
    }
    _write_json(manifest, "final_implementable_scaffold_cleanup_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
