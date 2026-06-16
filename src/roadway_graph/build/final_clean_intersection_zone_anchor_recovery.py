"""Review-only intersection-zone anchor missing-leg recovery.

Bounded question:
    Generate review-only missing-leg candidate bins for residual two-/three-leg
    signals whose residual label audit indicates likely recovery with an
    inferred intersection-zone anchor.

This pass does not modify active outputs, promote records, assign crashes or
access, assign speed/AADT, calculate rates/models, context-refresh generated
bins, or use crash direction fields.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyogrio
from shapely import wkt
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_intersection_zone_anchor_recovery"

ML_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_context_refresh_and_integration"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_label_audit"
CONSOLIDATION_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_leg_distribution_consolidation"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
SOURCE_TRAVELWAY = ROOT / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"
SOURCE_LAYER = "source_travelway_full"

BIN_SIZE_FT = 50
PRIMARY_MAX_FT = 1000
SENSITIVITY_MAX_FT = 2500
MIN_SEGMENT_FT = 5
SOURCE_RADIUS_FT = 350
INTERSECTION_CLUSTER_RADIUS_FT = 60

EXPECTED_TARGETS = 1093
CURRENT_DISTRIBUTION = {
    "one_leg": 46,
    "two_leg": 398,
    "three_leg": 1265,
    "four_leg": 1841,
    "five_plus_leg": 169,
}

INPUTS = {
    "missing_leg_context_bin_detail": ML_CONTEXT_DIR / "missing_leg_context_bin_detail.csv",
    "missing_leg_context_signal_summary": ML_CONTEXT_DIR / "missing_leg_context_signal_summary.csv",
    "consolidated_context_bins": ML_CONTEXT_DIR / "final_clean_consolidated_bin_detail_with_missing_leg_context.csv",
    "consolidated_context_signals": ML_CONTEXT_DIR / "final_clean_consolidated_signal_summary_with_missing_leg_context.csv",
    "distribution_after_missing_leg_context": ML_CONTEXT_DIR / "final_clean_distribution_after_missing_leg_context.csv",
    "remaining_issues_after_missing_leg_context": ML_CONTEXT_DIR / "remaining_leg_issues_after_missing_leg_context.csv",
    "missing_leg_context_manifest": ML_CONTEXT_DIR
    / "final_clean_missing_leg_context_refresh_and_integration_manifest.json",
    "residual_targets": RESIDUAL_DIR / "residual_leg_label_target_detail.csv",
    "residual_two": RESIDUAL_DIR / "residual_two_leg_reclassification.csv",
    "residual_three": RESIDUAL_DIR / "residual_three_leg_reclassification.csv",
    "residual_five": RESIDUAL_DIR / "residual_five_plus_reclassification.csv",
    "residual_source_evidence": RESIDUAL_DIR / "residual_source_travelway_evidence_summary.csv",
    "residual_summary": RESIDUAL_DIR / "residual_leg_recoverability_summary.csv",
    "residual_next_action": RESIDUAL_DIR / "residual_leg_next_action_recommendation.csv",
    "residual_manifest": RESIDUAL_DIR / "final_clean_residual_leg_label_audit_manifest.json",
    "consolidated_bins": CONSOLIDATION_DIR / "consolidated_leg_bin_detail.csv",
    "consolidated_signals": CONSOLIDATION_DIR / "consolidated_leg_signal_summary.csv",
    "remaining_two": CONSOLIDATION_DIR / "remaining_two_leg_issue_detail.csv",
    "remaining_three": CONSOLIDATION_DIR / "remaining_three_leg_issue_detail.csv",
    "skipped_generation": CONSOLIDATION_DIR / "skipped_missing_leg_generation_audit.csv",
    "consolidation_manifest": CONSOLIDATION_DIR / "final_clean_leg_distribution_consolidation_manifest.json",
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "final_manifest": FINAL_DIR / "final_clean_universe_context_summary_manifest.json",
    "source_travelway": SOURCE_TRAVELWAY,
}

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_dt",
)


_T0 = time.perf_counter()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(lines: list[str], message: str) -> None:
    elapsed = time.perf_counter() - _T0
    line = f"{now()} {message} elapsed_s={elapsed:.1f}"
    lines.append(line)
    print(message)


def clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "null"} else text


def stable_hash(parts: Iterable[Any], prefix: str, n: int = 20) -> str:
    text = "|".join(clean(part) for part in parts)
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:n]}"


def geom_hash(geom: Any) -> str:
    if geom is None or geom.is_empty:
        return ""
    return hashlib.sha1(geom.wkb).hexdigest()[:20]


def blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, usecols=cols, low_memory=False)


def write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)


def write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")


def write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def text_col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype="string")
    return frame[column].astype("string").fillna("").str.strip()


def nonblank(frame: pd.DataFrame, column: str) -> pd.Series:
    text = text_col(frame, column)
    return text.ne("") & ~text.str.lower().isin({"nan", "none", "<na>", "null"})


def num_col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def parse_wkt(value: Any):
    text = clean(value)
    if not text:
        return None
    try:
        geom = wkt.loads(text)
        if geom.is_empty:
            return None
        return geom
    except Exception:
        return None


def line_components(geom: Any) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
    return []


def sector_from_delta(dx: float, dy: float) -> str | None:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    sector = int(((angle + 22.5) % 360.0) // 45)
    return f"sector_{sector:02d}"


def sector_between(a: Point, b: Point) -> str | None:
    return sector_from_delta(b.x - a.x, b.y - a.y)


def parse_sectors(value: Any) -> set[str]:
    text = clean(value)
    if not text:
        return set()
    return {part.strip() for part in text.replace(",", "|").split("|") if part.strip().startswith("sector_")}


def distance_band(start_ft: float, end_ft: float) -> str:
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


def leg_bucket(count: int | float) -> str:
    if pd.isna(count) or int(count) <= 0:
        return "zero_or_unknown_leg"
    count = int(count)
    if count == 1:
        return "one_leg"
    if count == 2:
        return "two_leg"
    if count == 3:
        return "three_leg"
    if count == 4:
        return "four_leg"
    return "five_plus_leg"


def read_source_travelway(lines: list[str]) -> pd.DataFrame:
    fields = [
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "FROM_MEASURE",
        "TO_MEASURE",
        "RIM_FACILI",
        "RTE_RAMP_C",
        "RIM_MEDIAN",
        "MEDIAN_IND",
    ]
    log(lines, "Reading source_travelway_full geometry and lineage columns.")
    gdf = pyogrio.read_dataframe(
        SOURCE_TRAVELWAY,
        layer=SOURCE_LAYER,
        columns=fields,
        fid_as_index=True,
    )
    gdf = gdf.reset_index().rename(columns={"fid": "source_feature_local_fid"})
    if "source_feature_local_fid" not in gdf.columns:
        gdf["source_feature_local_fid"] = gdf.index
    fid = pd.to_numeric(gdf["source_feature_local_fid"], errors="coerce")
    gdf["source_feature_local_fid"] = fid.fillna(pd.Series(gdf.index, index=gdf.index)).astype(int)
    gdf["geom_hash"] = [geom_hash(geom) for geom in gdf.geometry]
    gdf["stable_travelway_id"] = [
        stable_hash([row.source_feature_local_fid, row.RTE_ID, row.RTE_NM, row.FROM_MEASURE, row.TO_MEASURE, row.geom_hash], "tw", 16)
        for row in gdf.itertuples(index=False)
    ]
    log(lines, f"Read source Travelway rows: {len(gdf):,}")
    return gdf


def endpoint_anchor_from_bins(signal_bins: pd.DataFrame) -> Point | None:
    points: list[Point] = []
    if signal_bins.empty:
        return None
    work = signal_bins.copy()
    work["distance_start_num"] = num_col(work, "distance_start_ft")
    min_start = work["distance_start_num"].min()
    if pd.isna(min_start):
        min_start = 0
    near = work[work["distance_start_num"].fillna(999999) <= min_start + 50].head(60)
    for value in near.get("geometry_wkt", []):
        geom = parse_wkt(value)
        for line in line_components(geom):
            coords = list(line.coords)
            if coords:
                points.append(Point(coords[0]))
    if not points:
        for value in work.head(60).get("geometry_wkt", []):
            geom = parse_wkt(value)
            for line in line_components(geom):
                coords = list(line.coords)
                if coords:
                    points.append(Point(coords[0]))
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return Point(sum(xs) / len(xs), sum(ys) / len(ys))


def nearest_component(geom: Any, anchor: Point) -> LineString | None:
    comps = line_components(geom)
    if not comps:
        return None
    return min(comps, key=lambda line: line.distance(anchor))


def source_candidates(tree: STRtree, geoms: list[Any], source: pd.DataFrame, anchor: Point, radius: float) -> pd.DataFrame:
    idxs = tree.query(anchor.buffer(radius))
    if len(idxs) == 0:
        return source.iloc[[]].copy()
    rows: list[int] = []
    for idx in idxs:
        geom = geoms[int(idx)]
        if geom is not None and not geom.is_empty and geom.distance(anchor) <= radius:
            rows.append(int(idx))
    if not rows:
        return source.iloc[[]].copy()
    return source.iloc[rows].copy()


def infer_intersection_anchor(raw_anchor: Point | None, candidates: pd.DataFrame) -> tuple[Point | None, str, float | None]:
    if raw_anchor is None:
        return None, "anchor_unavailable", None
    if candidates.empty:
        return raw_anchor, "low_anchor_confidence", 0.0

    lines: list[tuple[int, LineString]] = []
    for idx, row in candidates.iterrows():
        comp = nearest_component(row.geometry, raw_anchor)
        if comp is not None:
            lines.append((idx, comp))
    intersections: list[Point] = []
    limited = lines[:28]
    for i, (_, a) in enumerate(limited):
        for _, b in limited[i + 1 :]:
            if a.distance(b) > INTERSECTION_CLUSTER_RADIUS_FT:
                continue
            inter = a.intersection(b)
            if inter.is_empty:
                continue
            if isinstance(inter, Point):
                intersections.append(inter)
            elif hasattr(inter, "geoms"):
                intersections.extend([g for g in inter.geoms if isinstance(g, Point)])
    close = [p for p in intersections if p.distance(raw_anchor) <= SOURCE_RADIUS_FT]
    if len(close) >= 3:
        anchor = Point(sum(p.x for p in close) / len(close), sum(p.y for p in close) / len(close))
        return anchor, "high_line_intersection_cluster", raw_anchor.distance(anchor)
    if len(close) >= 1:
        anchor = Point(sum(p.x for p in close) / len(close), sum(p.y for p in close) / len(close))
        return anchor, "medium_line_intersection_cluster", raw_anchor.distance(anchor)

    nearest_points: list[Point] = []
    for _, line in lines[:32]:
        proj = line.project(raw_anchor)
        nearest_points.append(line.interpolate(proj))
    if len(nearest_points) >= 2:
        anchor = Point(
            sum(p.x for p in nearest_points) / len(nearest_points),
            sum(p.y for p in nearest_points) / len(nearest_points),
        )
        return anchor, "medium_source_zone_centroid", raw_anchor.distance(anchor)
    return raw_anchor, "low_anchor_confidence", 0.0


def orient_line(line: LineString, anchor: Point, desired_sector: str | None) -> tuple[float, int]:
    proj = line.project(anchor)
    coords = list(line.coords)
    start_sector = sector_between(anchor, Point(coords[0])) if coords else None
    end_sector = sector_between(anchor, Point(coords[-1])) if coords else None
    if desired_sector and end_sector == desired_sector and start_sector != desired_sector:
        return proj, 1
    if desired_sector and start_sector == desired_sector and end_sector != desired_sector:
        return proj, -1
    return proj, 1 if (line.length - proj) >= proj else -1


def segment_for_bin(line: LineString, anchor_proj: float, direction: int, start_ft: float, end_ft: float):
    if direction >= 0:
        a = min(line.length, anchor_proj + start_ft)
        b = min(line.length, anchor_proj + end_ft)
    else:
        a = max(0.0, anchor_proj - end_ft)
        b = max(0.0, anchor_proj - start_ft)
    if b - a < MIN_SEGMENT_FT:
        return None
    try:
        seg = substring(line, a, b)
    except Exception:
        return None
    if seg is None or seg.is_empty or seg.length < MIN_SEGMENT_FT:
        return None
    return seg


def build_targets(two: pd.DataFrame, three: pd.DataFrame, final_signals: pd.DataFrame) -> pd.DataFrame:
    two_t = two[text_col(two, "residual_two_leg_reclassified").eq("recoverable_with_intersection_zone_anchor")].copy()
    two_t["anchor_target_class"] = "recoverable_with_intersection_zone_anchor"
    two_t["residual_bucket"] = "two_leg"
    three_t = three[
        text_col(three, "residual_three_leg_reclassified").eq(
            "recoverable_missing_fourth_with_intersection_zone_anchor"
        )
    ].copy()
    three_t["anchor_target_class"] = "recoverable_missing_fourth_with_intersection_zone_anchor"
    three_t["residual_bucket"] = "three_leg"
    targets = pd.concat([two_t, three_t], ignore_index=True, sort=False)
    signal_cols = [
        col
        for col in [
            "stable_signal_id",
            "source_signal_id",
            "GLOBALID",
            "OBJECTID",
            "ASSET_ID",
            "REG_SIGNAL_ID",
            "source_signal_layer",
            "source_system",
            "signal_geometry_wkt",
            "recovery_branch",
            "clean_universe_component",
            "high_crash_relevance",
            "missing_globalid",
        ]
        if col in final_signals.columns
    ]
    targets = targets.drop(columns=[col for col in signal_cols if col != "stable_signal_id" and col in targets.columns], errors="ignore")
    targets = targets.merge(final_signals[signal_cols].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    return targets


def classify_source_row(row: pd.Series, sector: str | None, missing_sectors: set[str]) -> str:
    text = " ".join(clean(row.get(col)) for col in ["RTE_NM", "RTE_COMMON", "RIM_FACILI", "RTE_RAMP_C"]).upper()
    if sector not in missing_sectors:
        return "not_a_missing_leg"
    if "RAMP" in text or "RMP" in text:
        return "source_supported_missing_carriageway_subbranch"
    if "INTERSTATE" in text or " IS" in text:
        return "grade_or_mainline_risk"
    return "source_supported_missing_physical_leg"


def generate_for_targets(
    targets: pd.DataFrame,
    bins_by_signal: dict[str, pd.DataFrame],
    source: pd.DataFrame,
    tree: STRtree,
    geoms: list[Any],
    lines: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    anchor_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    bin_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    for n, target in enumerate(targets.itertuples(index=False), start=1):
        stable_signal_id = clean(getattr(target, "stable_signal_id", ""))
        signal_bins = bins_by_signal.get(stable_signal_id, pd.DataFrame())
        raw_anchor = parse_wkt(getattr(target, "signal_geometry_wkt", "")) or endpoint_anchor_from_bins(signal_bins)
        candidates_350 = source_candidates(tree, geoms, source, raw_anchor, SOURCE_RADIUS_FT) if raw_anchor is not None else source.iloc[[]].copy()
        anchor, method, offset_ft = infer_intersection_anchor(raw_anchor, candidates_350)
        missing_sectors = parse_sectors(getattr(target, "missing_source_sectors_350ft", ""))
        if not missing_sectors:
            missing_sectors = parse_sectors(getattr(target, "missing_source_sectors_250ft", ""))

        anchor_rows.append(
            {
                "stable_signal_id": stable_signal_id,
                "source_signal_id": clean(getattr(target, "source_signal_id", "")),
                "residual_bucket": clean(getattr(target, "residual_bucket", "")),
                "anchor_target_class": clean(getattr(target, "anchor_target_class", "")),
                "raw_anchor_x": raw_anchor.x if raw_anchor is not None else pd.NA,
                "raw_anchor_y": raw_anchor.y if raw_anchor is not None else pd.NA,
                "inferred_anchor_x": anchor.x if anchor is not None else pd.NA,
                "inferred_anchor_y": anchor.y if anchor is not None else pd.NA,
                "anchor_method": method,
                "anchor_confidence": method,
                "signal_to_anchor_offset_ft": round(offset_ft, 2) if offset_ft is not None else pd.NA,
                "source_rows_within_350ft": len(candidates_350),
                "target_missing_sectors": "|".join(sorted(missing_sectors)),
            }
        )

        if n % 100 == 0:
            log(lines, f"Processed anchor targets: {n:,} / {len(targets):,}")

        if anchor is None or method in {"anchor_unavailable", "low_anchor_confidence"}:
            skipped_rows.append(skip_row(target, "anchor_confidence_too_low", method))
            continue
        if not missing_sectors:
            skipped_rows.append(skip_row(target, "source_leg_not_found_after_anchor", method))
            continue

        generated_signal = False
        used_sectors: set[str] = set()
        residual_bucket = clean(getattr(target, "residual_bucket", ""))
        max_generated_sectors = 1 if residual_bucket == "three_leg" else 2
        candidates_iter = candidates_350.copy()
        if not candidates_iter.empty:
            candidates_iter["_anchor_distance"] = candidates_iter.geometry.distance(anchor)
            candidates_iter = candidates_iter.sort_values("_anchor_distance")
        for idx, src in candidates_iter.iterrows():
            line = nearest_component(src.geometry, anchor)
            if line is None:
                continue
            near_pt = line.interpolate(line.project(anchor))
            coords = list(line.coords)
            if not coords:
                continue
            start_sector = sector_between(anchor, Point(coords[0]))
            end_sector = sector_between(anchor, Point(coords[-1]))
            sector = end_sector if end_sector in missing_sectors else start_sector if start_sector in missing_sectors else sector_between(anchor, near_pt)
            leg_class = classify_source_row(src, sector, missing_sectors)
            source_rows.append(
                {
                    "stable_signal_id": stable_signal_id,
                    "source_signal_id": clean(getattr(target, "source_signal_id", "")),
                    "source_feature_local_fid": src.get("source_feature_local_fid", idx),
                    "stable_travelway_id": src.get("stable_travelway_id", ""),
                    "source_route_id": src.get("RTE_ID", ""),
                    "source_route_name": src.get("RTE_NM", ""),
                    "source_route_common": src.get("RTE_COMMON", ""),
                    "source_measure_start": src.get("FROM_MEASURE", ""),
                    "source_measure_end": src.get("TO_MEASURE", ""),
                    "anchor_bearing_sector": sector or "",
                    "source_leg_classification": leg_class,
                    "distance_to_inferred_anchor_ft": round(src.geometry.distance(anchor), 2),
                    "anchor_method": method,
                }
            )
            if leg_class not in {
                "source_supported_missing_physical_leg",
                "source_supported_missing_carriageway_subbranch",
            }:
                continue
            if sector not in missing_sectors:
                continue
            if not sector or sector in used_sectors:
                continue
            if len(used_sectors) >= max_generated_sectors:
                continue
            used_sectors.add(sector)

            anchor_proj, direction = orient_line(line, anchor, sector)
            physical_leg_id = stable_hash([stable_signal_id, "intersection_zone_anchor", sector], "physleg", 16)
            subbranch_id = stable_hash([stable_signal_id, physical_leg_id, src.get("stable_travelway_id", ""), src.get("source_feature_local_fid", idx)], "subbranch", 16)
            leg_rows.append(
                {
                    "stable_signal_id": stable_signal_id,
                    "source_signal_id": clean(getattr(target, "source_signal_id", "")),
                    "residual_bucket": clean(getattr(target, "residual_bucket", "")),
                    "anchor_target_class": clean(getattr(target, "anchor_target_class", "")),
                    "physical_leg_id": physical_leg_id,
                    "corrected_physical_leg_id": physical_leg_id,
                    "carriageway_subbranch_id": subbranch_id,
                    "corrected_carriageway_subbranch_id": subbranch_id,
                    "source_bearing_sector": sector or "",
                    "stable_travelway_id": src.get("stable_travelway_id", ""),
                    "source_feature_local_fid": src.get("source_feature_local_fid", idx),
                    "source_leg_classification": leg_class,
                    "anchor_method": method,
                    "lineage_confidence": "medium_review_only_intersection_zone_anchor",
                }
            )
            for start_ft in range(0, SENSITIVITY_MAX_FT, BIN_SIZE_FT):
                end_ft = start_ft + BIN_SIZE_FT
                seg = segment_for_bin(line, anchor_proj, direction, start_ft, end_ft)
                if seg is None:
                    continue
                stable_bin_id = stable_hash(
                    [stable_signal_id, src.get("stable_travelway_id", ""), sector, start_ft, end_ft, geom_hash(seg)],
                    "bin",
                    20,
                )
                bin_rows.append(
                    {
                        "stable_signal_id": stable_signal_id,
                        "source_signal_id": clean(getattr(target, "source_signal_id", "")),
                        "GLOBALID": clean(getattr(target, "GLOBALID", "")),
                        "stable_bin_id": stable_bin_id,
                        "stable_travelway_id": src.get("stable_travelway_id", ""),
                        "source_layer": SOURCE_LAYER,
                        "source_route_id": src.get("RTE_ID", ""),
                        "source_route_name": src.get("RTE_NM", ""),
                        "source_route_common": src.get("RTE_COMMON", ""),
                        "source_measure_start": src.get("FROM_MEASURE", ""),
                        "source_measure_end": src.get("TO_MEASURE", ""),
                        "source_feature_local_fid": src.get("source_feature_local_fid", idx),
                        "geometry_hash": geom_hash(seg),
                        "lineage_match_method": "intersection_zone_anchor_source_travelway_missing_sector",
                        "lineage_confidence": "medium_review_only_intersection_zone_anchor",
                        "physical_leg_id": physical_leg_id,
                        "corrected_physical_leg_id": physical_leg_id,
                        "carriageway_subbranch_id": subbranch_id,
                        "corrected_carriageway_subbranch_id": subbranch_id,
                        "source_bearing_sector": sector or "",
                        "distance_start_ft": start_ft,
                        "distance_end_ft": end_ft,
                        "distance_band": distance_band(start_ft, end_ft),
                        "analysis_window": "0_1000" if end_ft <= PRIMARY_MAX_FT else "1000_2500",
                        "geometry_wkt": seg.wkt,
                        "partial_coverage_flag": bool(seg.length < BIN_SIZE_FT - 1),
                        "anchor_method": method,
                        "anchor_confidence": method,
                        "review_only_recovery_provenance": "final_clean_intersection_zone_anchor_recovery",
                        "leg_recovery_status": "generated_intersection_zone_anchor_missing_leg_candidate",
                        "review_only": True,
                    }
                )
                generated_signal = True
        if not generated_signal:
            skipped_rows.append(skip_row(target, "source_leg_not_found_after_anchor", method))

    return (
        pd.DataFrame(anchor_rows),
        pd.DataFrame(source_rows),
        pd.DataFrame(leg_rows),
        pd.DataFrame(bin_rows),
        pd.DataFrame(skipped_rows),
    )


def skip_row(target: Any, reason: str, method: str) -> dict[str, Any]:
    return {
        "stable_signal_id": clean(getattr(target, "stable_signal_id", "")),
        "source_signal_id": clean(getattr(target, "source_signal_id", "")),
        "residual_bucket": clean(getattr(target, "residual_bucket", "")),
        "anchor_target_class": clean(getattr(target, "anchor_target_class", "")),
        "skip_reason": reason,
        "anchor_method": method,
        "review_only": True,
    }


def revised_distribution(targets: pd.DataFrame, generated_legs: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    base = signal_summary[["stable_signal_id", "final_review_physical_leg_count"]].copy()
    base["final_review_physical_leg_count"] = pd.to_numeric(base["final_review_physical_leg_count"], errors="coerce").fillna(0).astype(int)
    gen = (
        generated_legs.groupby("stable_signal_id")["corrected_physical_leg_id"].nunique().reset_index(name="anchor_generated_leg_count")
        if not generated_legs.empty
        else pd.DataFrame(columns=["stable_signal_id", "anchor_generated_leg_count"])
    )
    base = base.merge(gen, on="stable_signal_id", how="left")
    base["anchor_generated_leg_count"] = base["anchor_generated_leg_count"].fillna(0).astype(int)
    base["after_anchor_leg_count"] = base["final_review_physical_leg_count"] + base["anchor_generated_leg_count"]
    base["before_bucket"] = base["final_review_physical_leg_count"].map(leg_bucket)
    base["after_bucket"] = base["after_anchor_leg_count"].map(leg_bucket)

    rows: list[dict[str, Any]] = []
    for scenario, col in [
        ("before_intersection_zone_anchor_generation", "before_bucket"),
        ("after_intersection_zone_anchor_generation", "after_bucket"),
    ]:
        counts = base[col].value_counts().to_dict()
        total = int(sum(counts.values()))
        for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
            count = int(counts.get(bucket, 0))
            rows.append(
                {
                    "distribution_scenario": scenario,
                    "physical_leg_bucket": bucket,
                    "signal_count": count,
                    "share": round(count / total, 4) if total else 0,
                }
            )
        rows.append(
            {
                "distribution_scenario": scenario,
                "physical_leg_bucket": "two_leg_or_less_combined",
                "signal_count": int(counts.get("one_leg", 0) + counts.get("two_leg", 0)),
                "share": round((counts.get("one_leg", 0) + counts.get("two_leg", 0)) / total, 4) if total else 0,
            }
        )
    return pd.DataFrame(rows)


def context_readiness(bins: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        return pd.DataFrame(
            [
                {"metric": "generated_bins", "value": 0},
                {"metric": "generated_signals", "value": 0},
            ]
        )
    route_ready = (
        nonblank(bins, "stable_travelway_id")
        & (nonblank(bins, "source_route_id") | nonblank(bins, "source_route_name") | nonblank(bins, "source_route_common"))
        & (num_col(bins, "source_measure_start").notna() | num_col(bins, "source_measure_end").notna())
    )
    return pd.DataFrame(
        [
            {"metric": "generated_bins", "value": len(bins)},
            {"metric": "generated_signals", "value": int(bins["stable_signal_id"].nunique())},
            {"metric": "generated_physical_legs", "value": len(legs)},
            {"metric": "route_measure_ready_bins", "value": int(route_ready.sum())},
            {"metric": "roadway_context_ready_bins", "value": int(nonblank(bins, "stable_travelway_id").sum())},
            {"metric": "rns_ready_for_later_bins", "value": int(route_ready.sum())},
            {"metric": "aadt_v3_exposure_ready_for_later_bins", "value": int(route_ready.sum())},
            {"metric": "access_ready_for_later_bins", "value": int(nonblank(bins, "stable_travelway_id").sum())},
            {"metric": "crash_assignment_ready_for_later_bins", "value": int(nonblank(bins, "stable_travelway_id").sum())},
        ]
    )


def summary_table(targets: pd.DataFrame, legs: pd.DataFrame, bins: pd.DataFrame, skipped: pd.DataFrame, anchors: pd.DataFrame) -> pd.DataFrame:
    two_targets = int((targets["residual_bucket"] == "two_leg").sum())
    three_targets = int((targets["residual_bucket"] == "three_leg").sum())
    generated_signals = set(bins["stable_signal_id"]) if not bins.empty else set()
    two_generated = int(targets[(targets["residual_bucket"] == "two_leg") & targets["stable_signal_id"].isin(generated_signals)]["stable_signal_id"].nunique())
    three_generated = int(targets[(targets["residual_bucket"] == "three_leg") & targets["stable_signal_id"].isin(generated_signals)]["stable_signal_id"].nunique())
    rows = [
        ("target_signals", len(targets)),
        ("two_leg_residual_targets", two_targets),
        ("three_leg_missing_fourth_targets", three_targets),
        ("signals_with_generated_anchor_candidates", len(generated_signals)),
        ("two_leg_residuals_improved", two_generated),
        ("three_leg_missing_fourth_cases_improved", three_generated),
        ("signals_skipped", int(skipped["stable_signal_id"].nunique()) if not skipped.empty else 0),
        ("generated_physical_legs", len(legs)),
        ("generated_bins", len(bins)),
        ("generated_bins_0_1000", int((text_col(bins, "analysis_window") == "0_1000").sum()) if not bins.empty else 0),
        ("generated_bins_1000_2500", int((text_col(bins, "analysis_window") == "1000_2500").sum()) if not bins.empty else 0),
        ("bins_with_stable_travelway_id", int(nonblank(bins, "stable_travelway_id").sum()) if not bins.empty else 0),
    ]
    if not anchors.empty:
        for method, count in anchors["anchor_method"].value_counts().items():
            rows.append((f"anchor_method_{method}", int(count)))
    if not skipped.empty:
        for reason, count in skipped["skip_reason"].value_counts().items():
            rows.append((f"skip_reason_{reason}", int(count)))
    return pd.DataFrame([{"metric": key, "value": value} for key, value in rows])


def qa_table(bins: pd.DataFrame, missing_inputs: list[str]) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_clean_intersection_zone_anchor_recovery."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_crash_assignment", True, "Crash records are not read."),
        ("no_access_assignment", True, "Access sources are not read or assigned."),
        ("no_rates_or_models", True, "No rates, models, regressions, or predictions are calculated."),
        ("no_speed_aadt_context_refresh", True, "Only readiness flags are produced."),
        ("crash_direction_fields_not_used", True, "CSV reader refuses known crash direction columns."),
        ("source_limited_cases_not_forced", True, "Target filter excludes confirmed source-limited/manual classes."),
        (
            "stable_travelway_id_preserved_on_generated_bins",
            bins.empty or int(nonblank(bins, "stable_travelway_id").sum()) == len(bins),
            f"{int(nonblank(bins, 'stable_travelway_id').sum()) if not bins.empty else 0:,} / {len(bins):,}",
        ),
        ("generated_bins_review_only", bins.empty or bool(pd.Series(bins["review_only"]).astype(bool).all()), "Generated rows carry review_only=True."),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("required_inputs_available", not missing_inputs, "; ".join(missing_inputs[:8])),
    ]
    return pd.DataFrame([{"qa_check": key, "passed": bool(passed), "detail": detail} for key, passed, detail in checks])


def findings(counts: dict[str, Any]) -> str:
    return f"""# Final Clean Intersection-Zone Anchor Recovery

## Bounded Question

Generate review-only missing-leg candidate bins for residual two-/three-leg signals where the residual label audit indicated likely recovery with an inferred intersection-zone anchor.

## Findings

1. **Targets processed:** {counts['target_signals']:,}.
2. **Signals with defensible missing-leg candidates:** {counts['generated_signals']:,}.
3. **Generated physical legs:** {counts['generated_legs']:,}.
4. **Generated bins:** {counts['generated_bins']:,}.
5. **Two-leg residuals improved:** {counts['two_leg_improved']:,}.
6. **Three-leg missing-fourth cases improved:** {counts['three_leg_improved']:,}.
7. **Main anchor methods/confidence:** see `intersection_zone_anchor_generation_summary.csv`; the primary methods are line-intersection clusters and source-zone centroids.
8. **Skipped targets:** {counts['skipped_signals']:,}; reasons are listed in `intersection_zone_anchor_skipped_targets.csv`.
9. **Stable lineage:** {counts['bins_with_stable_travelway_id']:,} / {counts['generated_bins']:,} generated bins carry `stable_travelway_id`.
10. **Revised distribution estimate:** one-leg {counts['after_one_leg']:,}, two-leg {counts['after_two_leg']:,}, three-leg {counts['after_three_leg']:,}, four-leg {counts['after_four_leg']:,}, five-plus {counts['after_five_plus']:,}.
11. **Context-refresh readiness:** generated bins carry route/measure and stable Travelway lineage readiness flags only; speed/AADT are not assigned in this pass.
12. **Next pass:** context-refresh these generated anchor-recovery bins if the QA counts are acceptable; otherwise map-review or refine the skipped ambiguous/source-not-found subset.

## Method Notes

Signal geometry is often missing in the final clean universe, so the working raw anchor is inferred from near-signal endpoints of existing bins where signal point geometry is unavailable. The intersection-zone anchor is then inferred from nearby source Travelway line intersections or source-zone centroid evidence. Source-limited and manual-review residual labels are excluded from the target pool.

## Non-Goals Honored

No active outputs were modified, no records were promoted, no crash/access assignment was performed, no rates/models were calculated, and no speed/AADT context refresh was run.
"""


def manifest(counts: dict[str, Any], missing_inputs: list[str]) -> dict[str, Any]:
    return {
        "created_utc": now(),
        "script": "src.roadway_graph.build.final_clean_intersection_zone_anchor_recovery",
        "bounded_question": "Review-only intersection-zone anchor missing-leg recovery for residual two-/three-leg cases.",
        "inputs": {name: {"path": str(path), "exists": path.exists()} for name, path in INPUTS.items()},
        "missing_inputs": missing_inputs,
        "counts": counts,
        "outputs": [
            "intersection_zone_anchor_target_signals.csv",
            "intersection_zone_anchor_inference_detail.csv",
            "intersection_zone_anchor_source_leg_detail.csv",
            "intersection_zone_anchor_generated_leg_candidates.csv",
            "intersection_zone_anchor_generated_bins.csv",
            "intersection_zone_anchor_skipped_targets.csv",
            "intersection_zone_anchor_generation_summary.csv",
            "intersection_zone_anchor_revised_distribution_estimate.csv",
            "intersection_zone_anchor_context_refresh_readiness.csv",
            "final_clean_intersection_zone_anchor_recovery_findings.md",
            "final_clean_intersection_zone_anchor_recovery_qa.csv",
            "final_clean_intersection_zone_anchor_recovery_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals": {
            "active_outputs_modified": False,
            "records_promoted": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_models": False,
            "speed_aadt_context_refresh": False,
            "crash_direction_fields_used": False,
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    log(log_lines, "Starting final clean intersection-zone anchor recovery.")
    missing_inputs = [f"{name}: {path}" for name, path in INPUTS.items() if not path.exists()]
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing_inputs))

    two = read_csv(INPUTS["residual_two"])
    three = read_csv(INPUTS["residual_three"])
    final_signals = read_csv(INPUTS["final_signals"])
    consolidated_bins = read_csv(
        INPUTS["consolidated_context_bins"],
        usecols=[
            "stable_signal_id",
            "stable_bin_id",
            "source_signal_id",
            "geometry_wkt",
            "distance_start_ft",
            "final_review_physical_leg_id",
            "final_review_leg_source",
        ],
    )
    signal_summary = read_csv(INPUTS["consolidated_context_signals"])
    targets = build_targets(two, three, final_signals)
    write_csv(targets, "intersection_zone_anchor_target_signals.csv")
    log(log_lines, f"Built target pool: {len(targets):,}")

    source = read_source_travelway(log_lines)
    geoms = list(source.geometry)
    tree = STRtree(geoms)
    bins_by_signal = {sid: frame for sid, frame in consolidated_bins.groupby("stable_signal_id", sort=False)}

    anchors, source_detail, legs, bins, skipped = generate_for_targets(
        targets, bins_by_signal, source, tree, geoms, log_lines
    )
    summary = summary_table(targets, legs, bins, skipped, anchors)
    distribution = revised_distribution(targets, legs, signal_summary)
    readiness = context_readiness(bins, legs)

    counts_map = dict(zip(summary["metric"], summary["value"]))
    after = distribution[distribution["distribution_scenario"] == "after_intersection_zone_anchor_generation"]
    after_counts = dict(zip(after["physical_leg_bucket"], after["signal_count"]))
    counts = {
        "target_signals": int(counts_map.get("target_signals", len(targets))),
        "expected_targets": EXPECTED_TARGETS,
        "generated_signals": int(counts_map.get("signals_with_generated_anchor_candidates", 0)),
        "generated_legs": int(counts_map.get("generated_physical_legs", 0)),
        "generated_bins": int(counts_map.get("generated_bins", 0)),
        "two_leg_improved": int(counts_map.get("two_leg_residuals_improved", 0)),
        "three_leg_improved": int(counts_map.get("three_leg_missing_fourth_cases_improved", 0)),
        "skipped_signals": int(counts_map.get("signals_skipped", 0)),
        "bins_with_stable_travelway_id": int(counts_map.get("bins_with_stable_travelway_id", 0)),
        "after_one_leg": int(after_counts.get("one_leg", 0)),
        "after_two_leg": int(after_counts.get("two_leg", 0)),
        "after_three_leg": int(after_counts.get("three_leg", 0)),
        "after_four_leg": int(after_counts.get("four_leg", 0)),
        "after_five_plus": int(after_counts.get("five_plus_leg", 0)),
    }

    write_csv(anchors, "intersection_zone_anchor_inference_detail.csv")
    write_csv(source_detail, "intersection_zone_anchor_source_leg_detail.csv")
    write_csv(legs, "intersection_zone_anchor_generated_leg_candidates.csv")
    write_csv(bins, "intersection_zone_anchor_generated_bins.csv")
    write_csv(skipped, "intersection_zone_anchor_skipped_targets.csv")
    write_csv(summary, "intersection_zone_anchor_generation_summary.csv")
    write_csv(distribution, "intersection_zone_anchor_revised_distribution_estimate.csv")
    write_csv(readiness, "intersection_zone_anchor_context_refresh_readiness.csv")
    write_csv(qa_table(bins, missing_inputs), "final_clean_intersection_zone_anchor_recovery_qa.csv")
    write_text(findings(counts), "final_clean_intersection_zone_anchor_recovery_findings.md")
    write_json(manifest(counts, missing_inputs), "final_clean_intersection_zone_anchor_recovery_manifest.json")

    log(log_lines, "Complete.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
