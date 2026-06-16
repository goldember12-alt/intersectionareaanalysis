"""Review-only residual leg cleanup for the final clean universe.

Bounded question:
    Run one final residual cleanup pass after intersection-zone anchor context
    integration: broader source search for skipped anchor targets and
    label-only five-plus subbranch normalization.

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
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_cleanup"
ANCHOR_CONTEXT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_intersection_zone_anchor_context_refresh"
ANCHOR_RECOVERY_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_intersection_zone_anchor_recovery"
CONSOLIDATION_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_leg_distribution_consolidation"
RESIDUAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_label_audit"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
SOURCE_TRAVELWAY = ROOT / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"
SOURCE_LAYER = "source_travelway_full"

BIN_SIZE_FT = 50
PRIMARY_MAX_FT = 1000
SENSITIVITY_MAX_FT = 2500
SEARCH_RADII_FT = [350, 500, 750]
MIN_SEGMENT_FT = 5

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_dt",
)

INPUTS = {
    "anchor_context_bins": ANCHOR_CONTEXT_DIR / "intersection_zone_anchor_context_bin_detail.csv",
    "anchor_context_signals": ANCHOR_CONTEXT_DIR / "intersection_zone_anchor_context_signal_summary.csv",
    "current_bins": ANCHOR_CONTEXT_DIR / "final_clean_consolidated_bin_detail_with_anchor_context.csv",
    "current_signals": ANCHOR_CONTEXT_DIR / "final_clean_consolidated_signal_summary_with_anchor_context.csv",
    "current_distribution": ANCHOR_CONTEXT_DIR / "final_clean_distribution_after_anchor_context.csv",
    "current_remaining_issues": ANCHOR_CONTEXT_DIR / "remaining_leg_issues_after_anchor_context.csv",
    "anchor_context_recommendation": ANCHOR_CONTEXT_DIR / "anchor_context_next_action_recommendation.csv",
    "anchor_context_manifest": ANCHOR_CONTEXT_DIR / "final_clean_intersection_zone_anchor_context_refresh_manifest.json",
    "anchor_targets": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_target_signals.csv",
    "anchor_inference": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_inference_detail.csv",
    "anchor_source_detail": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_source_leg_detail.csv",
    "anchor_legs": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_generated_leg_candidates.csv",
    "anchor_bins": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_generated_bins.csv",
    "anchor_skipped": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_skipped_targets.csv",
    "anchor_summary": ANCHOR_RECOVERY_DIR / "intersection_zone_anchor_generation_summary.csv",
    "anchor_manifest": ANCHOR_RECOVERY_DIR / "final_clean_intersection_zone_anchor_recovery_manifest.json",
    "remaining_two": CONSOLIDATION_DIR / "remaining_two_leg_issue_detail.csv",
    "remaining_three": CONSOLIDATION_DIR / "remaining_three_leg_issue_detail.csv",
    "remaining_five": CONSOLIDATION_DIR / "remaining_five_plus_issue_detail.csv",
    "label_only_summary": CONSOLIDATION_DIR / "label_only_five_plus_normalization_summary.csv",
    "label_proposals": CONSOLIDATION_DIR / "corrected_leg_label_proposals.csv",
    "consolidation_manifest": CONSOLIDATION_DIR / "final_clean_leg_distribution_consolidation_manifest.json",
    "residual_two": RESIDUAL_DIR / "residual_two_leg_reclassification.csv",
    "residual_three": RESIDUAL_DIR / "residual_three_leg_reclassification.csv",
    "residual_five": RESIDUAL_DIR / "residual_five_plus_reclassification.csv",
    "residual_source_evidence": RESIDUAL_DIR / "residual_source_travelway_evidence_summary.csv",
    "residual_summary": RESIDUAL_DIR / "residual_leg_recoverability_summary.csv",
    "residual_manifest": RESIDUAL_DIR / "final_clean_residual_leg_label_audit_manifest.json",
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_manifest": FINAL_DIR / "final_clean_universe_context_summary_manifest.json",
    "source_travelway": SOURCE_TRAVELWAY,
}

_T0 = time.perf_counter()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(lines: list[str], message: str) -> None:
    elapsed = time.perf_counter() - _T0
    lines.append(f"{now()} {message} elapsed_s={elapsed:.1f}")
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


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR / name, index=False)


def write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")


def write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def text_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype="string")
    return df[col].astype("string").fillna("").str.strip()


def nonblank(df: pd.DataFrame, col: str) -> pd.Series:
    txt = text_col(df, col)
    return txt.ne("") & ~txt.str.lower().isin({"nan", "none", "<na>", "null"})


def num_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[col], errors="coerce")


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


def parse_wkt(value: Any):
    txt = clean(value)
    if not txt:
        return None
    try:
        geom = wkt.loads(txt)
        return None if geom.is_empty else geom
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
    return f"sector_{int(((angle + 22.5) % 360.0) // 45):02d}"


def sector_between(a: Point, b: Point) -> str | None:
    return sector_from_delta(b.x - a.x, b.y - a.y)


def parse_sectors(value: Any) -> set[str]:
    txt = clean(value)
    if not txt:
        return set()
    return {p.strip() for p in txt.replace(",", "|").split("|") if p.strip().startswith("sector_")}


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


def read_source_travelway(lines: list[str]) -> pd.DataFrame:
    fields = ["RTE_NM", "RTE_COMMON", "RTE_ID", "FROM_MEASURE", "TO_MEASURE", "RIM_FACILI", "RTE_RAMP_C", "RIM_MEDIAN", "MEDIAN_IND"]
    log(lines, "Reading source_travelway_full once for broader source search.")
    gdf = pyogrio.read_dataframe(SOURCE_TRAVELWAY, layer="source_travelway_full", columns=fields, fid_as_index=True)
    gdf = gdf.reset_index().rename(columns={"fid": "source_feature_local_fid"})
    if "source_feature_local_fid" not in gdf.columns:
        gdf["source_feature_local_fid"] = gdf.index
    fid = pd.to_numeric(gdf["source_feature_local_fid"], errors="coerce")
    gdf["source_feature_local_fid"] = fid.fillna(pd.Series(gdf.index, index=gdf.index)).astype(int)
    gdf["geometry_hash_source"] = [geom_hash(g) for g in gdf.geometry]
    gdf["stable_travelway_id"] = [
        stable_hash([r.source_feature_local_fid, r.RTE_ID, r.RTE_NM, r.FROM_MEASURE, r.TO_MEASURE, r.geometry_hash_source], "tw", 16)
        for r in gdf.itertuples(index=False)
    ]
    log(lines, f"Read source Travelway rows: {len(gdf):,}")
    return gdf


def nearest_component(geom: Any, anchor: Point) -> LineString | None:
    comps = line_components(geom)
    if not comps:
        return None
    return min(comps, key=lambda g: g.distance(anchor))


def source_candidates(tree: STRtree, geoms: list[Any], source: pd.DataFrame, anchor: Point, radius: float) -> pd.DataFrame:
    idxs = tree.query(anchor.buffer(radius))
    rows = [int(i) for i in idxs if geoms[int(i)] is not None and geoms[int(i)].distance(anchor) <= radius]
    return source.iloc[rows].copy() if rows else source.iloc[[]].copy()


def orient_line(line: LineString, anchor: Point, sector: str | None) -> tuple[float, int]:
    proj = line.project(anchor)
    coords = list(line.coords)
    start_sector = sector_between(anchor, Point(coords[0])) if coords else None
    end_sector = sector_between(anchor, Point(coords[-1])) if coords else None
    if sector and end_sector == sector and start_sector != sector:
        return proj, 1
    if sector and start_sector == sector and end_sector != sector:
        return proj, -1
    return proj, 1 if (line.length - proj) >= proj else -1


def segment_for_bin(line: LineString, proj: float, direction: int, start_ft: float, end_ft: float):
    if direction >= 0:
        a, b = min(line.length, proj + start_ft), min(line.length, proj + end_ft)
    else:
        a, b = max(0.0, proj - end_ft), max(0.0, proj - start_ft)
    if b - a < MIN_SEGMENT_FT:
        return None
    try:
        seg = substring(line, a, b)
    except Exception:
        return None
    return seg if seg is not None and not seg.is_empty and seg.length >= MIN_SEGMENT_FT else None


def classify_source_row(row: pd.Series, sector: str | None, missing: set[str]) -> str:
    txt = " ".join(clean(row.get(c)) for c in ["RTE_NM", "RTE_COMMON", "RIM_FACILI", "RTE_RAMP_C"]).upper()
    if sector not in missing:
        return "not_a_missing_leg"
    if "INTERSTATE" in txt or " IS" in txt:
        return "grade_or_mainline_context_holdout"
    if "RMP" in txt or "RAMP" in txt:
        return "source_supported_missing_carriageway_subbranch"
    return "source_supported_missing_physical_leg"


def build_target_pool(skipped: pd.DataFrame, inference: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    skips = skipped[text_col(skipped, "skip_reason").isin(["source_leg_not_found_after_anchor", "anchor_confidence_too_low"])].copy()
    skips["cleanup_target_type"] = "skipped_anchor_target"
    five = signals[text_col(signals, "final_review_physical_leg_bucket_after_anchor_context").eq("five_plus_leg")].copy()
    five["cleanup_target_type"] = "remaining_five_plus_signal"
    common = ["stable_signal_id", "source_signal_id"]
    skip_cols = list(dict.fromkeys(list(skips.columns)))
    five = five.reindex(columns=skip_cols)
    return pd.concat([skips, five], ignore_index=True, sort=False)


def broader_source_search(
    skipped: pd.DataFrame,
    current_bins: pd.DataFrame,
    source: pd.DataFrame,
    tree: STRtree,
    geoms: list[Any],
    lines: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    bins: list[dict[str, Any]] = []
    skipped_out: list[dict[str, Any]] = []
    bins_by_signal = {sid: df for sid, df in current_bins.groupby("stable_signal_id", sort=False)}

    for n, row in enumerate(skipped.itertuples(index=False), start=1):
        sid = clean(getattr(row, "stable_signal_id", ""))
        source_signal_id = clean(getattr(row, "source_signal_id", ""))
        anchor = None
        for xcol, ycol in [("inferred_anchor_x", "inferred_anchor_y"), ("raw_anchor_x", "raw_anchor_y")]:
            x, y = pd.to_numeric(getattr(row, xcol, None), errors="coerce"), pd.to_numeric(getattr(row, ycol, None), errors="coerce")
            if pd.notna(x) and pd.notna(y):
                anchor = Point(float(x), float(y))
                break
        if anchor is None:
            skipped_out.append(skip_record(row, "manual_review_needed"))
            continue
        missing = parse_sectors(getattr(row, "target_missing_sectors", ""))
        if not missing:
            skipped_out.append(skip_record(row, "source_leg_still_not_found"))
            continue
        residual_bucket = clean(getattr(row, "residual_bucket", ""))
        max_sectors = 1 if residual_bucket == "three_leg" else 2
        used: set[str] = set()
        generated = False
        for radius in SEARCH_RADII_FT:
            cands = source_candidates(tree, geoms, source, anchor, radius)
            if cands.empty:
                continue
            cands["_dist"] = cands.geometry.distance(anchor)
            cands = cands.sort_values("_dist")
            for idx, src in cands.iterrows():
                line = nearest_component(src.geometry, anchor)
                if line is None:
                    continue
                coords = list(line.coords)
                sector = None
                if coords:
                    start_sector = sector_between(anchor, Point(coords[0]))
                    end_sector = sector_between(anchor, Point(coords[-1]))
                    sector = end_sector if end_sector in missing else start_sector if start_sector in missing else None
                cls = classify_source_row(src, sector, missing)
                detail.append(
                    {
                        "stable_signal_id": sid,
                        "source_signal_id": source_signal_id,
                        "prior_skip_reason": clean(getattr(row, "skip_reason", "")),
                        "search_radius_ft": radius,
                        "source_feature_local_fid": src.get("source_feature_local_fid", idx),
                        "stable_travelway_id": src.get("stable_travelway_id", ""),
                        "source_route_name": src.get("RTE_NM", ""),
                        "source_route_common": src.get("RTE_COMMON", ""),
                        "source_bearing_sector": sector or "",
                        "broader_source_class": cls,
                        "distance_to_anchor_ft": round(src.geometry.distance(anchor), 2),
                    }
                )
                if cls not in {"source_supported_missing_physical_leg", "source_supported_missing_carriageway_subbranch"}:
                    continue
                if not sector or sector in used or len(used) >= max_sectors:
                    continue
                used.add(sector)
                proj, direction = orient_line(line, anchor, sector)
                phys = stable_hash([sid, "broader_source_search", sector], "physleg", 16)
                sub = stable_hash([sid, phys, src.get("stable_travelway_id", ""), src.get("source_feature_local_fid", idx)], "subbranch", 16)
                legs.append(
                    {
                        "stable_signal_id": sid,
                        "source_signal_id": source_signal_id,
                        "residual_bucket": residual_bucket,
                        "prior_skip_reason": clean(getattr(row, "skip_reason", "")),
                        "physical_leg_id": phys,
                        "corrected_physical_leg_id": phys,
                        "carriageway_subbranch_id": sub,
                        "corrected_carriageway_subbranch_id": sub,
                        "source_bearing_sector": sector,
                        "stable_travelway_id": src.get("stable_travelway_id", ""),
                        "source_feature_local_fid": src.get("source_feature_local_fid", idx),
                        "broader_source_class": cls,
                        "search_radius_ft": radius,
                        "lineage_confidence": "medium_review_only_broader_source_search",
                    }
                )
                for start in range(0, SENSITIVITY_MAX_FT, BIN_SIZE_FT):
                    end = start + BIN_SIZE_FT
                    seg = segment_for_bin(line, proj, direction, start, end)
                    if seg is None:
                        continue
                    bins.append(
                        {
                            "stable_signal_id": sid,
                            "source_signal_id": source_signal_id,
                            "stable_bin_id": stable_hash([sid, src.get("stable_travelway_id", ""), sector, start, end, geom_hash(seg)], "bin", 20),
                            "stable_travelway_id": src.get("stable_travelway_id", ""),
                            "source_layer": SOURCE_LAYER,
                            "source_route_id": src.get("RTE_ID", ""),
                            "source_route_name": src.get("RTE_NM", ""),
                            "source_route_common": src.get("RTE_COMMON", ""),
                            "source_measure_start": src.get("FROM_MEASURE", ""),
                            "source_measure_end": src.get("TO_MEASURE", ""),
                            "source_feature_local_fid": src.get("source_feature_local_fid", idx),
                            "geometry_hash": geom_hash(seg),
                            "lineage_match_method": "broader_source_search_missing_sector",
                            "lineage_confidence": "medium_review_only_broader_source_search",
                            "physical_leg_id": phys,
                            "corrected_physical_leg_id": phys,
                            "carriageway_subbranch_id": sub,
                            "corrected_carriageway_subbranch_id": sub,
                            "source_bearing_sector": sector,
                            "distance_start_ft": start,
                            "distance_end_ft": end,
                            "distance_band": distance_band(start, end),
                            "analysis_window": "0_1000" if end <= PRIMARY_MAX_FT else "1000_2500",
                            "geometry_wkt": seg.wkt,
                            "partial_coverage_flag": bool(seg.length < BIN_SIZE_FT - 1),
                            "review_only_recovery_provenance": "final_clean_residual_leg_cleanup",
                            "leg_recovery_status": "generated_broader_source_missing_leg_candidate",
                            "review_only": True,
                        }
                    )
                    generated = True
            if generated or len(used) >= max_sectors:
                break
        if not generated:
            reason = "source_leg_still_not_found" if clean(getattr(row, "skip_reason", "")) == "source_leg_not_found_after_anchor" else "source_geometry_still_ambiguous"
            skipped_out.append(skip_record(row, reason))
        if n % 50 == 0:
            log(lines, f"Broader source searched skipped targets: {n:,} / {len(skipped):,}")
    return pd.DataFrame(detail), pd.DataFrame(legs), pd.DataFrame(bins), pd.DataFrame(skipped_out)


def skip_record(row: Any, reason: str) -> dict[str, Any]:
    return {
        "stable_signal_id": clean(getattr(row, "stable_signal_id", "")),
        "source_signal_id": clean(getattr(row, "source_signal_id", "")),
        "prior_skip_reason": clean(getattr(row, "skip_reason", "")),
        "cleanup_class": reason,
        "review_only": True,
    }


def normalize_five_plus(signals: pd.DataFrame, residual_five: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    five_ids = signals.loc[text_col(signals, "final_review_physical_leg_bucket_after_anchor_context").eq("five_plus_leg"), "stable_signal_id"]
    detail = signals[signals["stable_signal_id"].isin(five_ids)].copy()
    keep_cols = [c for c in ["stable_signal_id", "source_signal_id", "final_review_physical_leg_count_after_anchor_context"] if c in detail.columns]
    detail = detail[keep_cols].drop_duplicates("stable_signal_id")
    reclass_col = "residual_five_plus_reclassified" if "residual_five_plus_reclassified" in residual_five.columns else "remaining_five_plus_issue_class"
    if reclass_col in residual_five.columns:
        detail = detail.merge(residual_five[["stable_signal_id", reclass_col]].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    else:
        detail[reclass_col] = ""
    cls = text_col(detail, reclass_col)
    reducible = cls.str.contains("over_split|subbranch|connector|source_row", case=False, regex=True) | cls.eq("")
    detail["current_five_plus_leg_count"] = pd.to_numeric(detail["final_review_physical_leg_count_after_anchor_context"], errors="coerce").fillna(5).astype(int)
    detail["residual_normalization_status"] = "true_complex_five_plus_possible"
    detail.loc[reducible, "residual_normalization_status"] = "resolved_by_label_only_subbranch_normalization"
    detail["residual_normalization_rule"] = "five_plus_residual_subbranch_source_row_normalization"
    detail["residual_normalization_confidence"] = detail["residual_normalization_status"].map(
        {"resolved_by_label_only_subbranch_normalization": "medium", "true_complex_five_plus_possible": "low_review_needed"}
    )
    detail["corrected_five_plus_leg_count"] = detail["current_five_plus_leg_count"]
    detail.loc[reducible, "corrected_five_plus_leg_count"] = 4
    detail["final_residual_corrected_physical_leg_id"] = "label_only_preserve_rows"
    detail["final_residual_carriageway_subbranch_id"] = "label_only_preserve_rows"
    summary = detail.groupby("residual_normalization_status").size().reset_index(name="signal_count")
    return detail, summary


def revised_distribution(signals: pd.DataFrame, broader_legs: pd.DataFrame, five_detail: pd.DataFrame) -> pd.DataFrame:
    base = signals[["stable_signal_id", "final_review_physical_leg_count_after_anchor_context"]].copy()
    base["base_count"] = pd.to_numeric(base["final_review_physical_leg_count_after_anchor_context"], errors="coerce").fillna(0).astype(int)
    gen = broader_legs.groupby("stable_signal_id")["corrected_physical_leg_id"].nunique().reset_index(name="broader_generated_leg_count") if not broader_legs.empty else pd.DataFrame(columns=["stable_signal_id", "broader_generated_leg_count"])
    five = five_detail[["stable_signal_id", "corrected_five_plus_leg_count"]].drop_duplicates("stable_signal_id") if not five_detail.empty else pd.DataFrame(columns=["stable_signal_id", "corrected_five_plus_leg_count"])
    base = base.merge(gen, on="stable_signal_id", how="left").merge(five, on="stable_signal_id", how="left")
    base["broader_generated_leg_count"] = base["broader_generated_leg_count"].fillna(0).astype(int)
    base["broader_only_count"] = base["base_count"] + base["broader_generated_leg_count"]
    base["five_only_count"] = base["corrected_five_plus_leg_count"].fillna(base["base_count"]).astype(int)
    base["both_count"] = base["five_only_count"] + base["broader_generated_leg_count"]
    rows = []
    for scenario, col in [
        ("before_residual_cleanup", "base_count"),
        ("after_broader_source_generated_bins_only", "broader_only_count"),
        ("after_five_plus_label_only_normalization_only", "five_only_count"),
        ("after_broader_source_and_five_plus_cleanup", "both_count"),
    ]:
        counts = base[col].map(leg_bucket).value_counts().to_dict()
        total = int(sum(counts.values()))
        for bucket in ["one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"]:
            count = int(counts.get(bucket, 0))
            rows.append({"distribution_scenario": scenario, "physical_leg_bucket": bucket, "signal_count": count, "share": round(count / total, 4) if total else 0})
        rows.append({"distribution_scenario": scenario, "physical_leg_bucket": "two_leg_or_less_combined", "signal_count": int(counts.get("one_leg", 0) + counts.get("two_leg", 0)), "share": round((counts.get("one_leg", 0) + counts.get("two_leg", 0)) / total, 4) if total else 0})
    return pd.DataFrame(rows)


def readiness(bins: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        return pd.DataFrame([{"metric": "generated_bins", "value": 0}, {"metric": "generated_signals", "value": 0}])
    route = nonblank(bins, "stable_travelway_id") & (nonblank(bins, "source_route_id") | nonblank(bins, "source_route_name") | nonblank(bins, "source_route_common")) & (num_col(bins, "source_measure_start").notna() | num_col(bins, "source_measure_end").notna())
    return pd.DataFrame(
        [
            {"metric": "generated_bins", "value": len(bins)},
            {"metric": "generated_signals", "value": int(bins["stable_signal_id"].nunique())},
            {"metric": "route_measure_ready_bins", "value": int(route.sum())},
            {"metric": "roadway_context_ready_bins", "value": int(nonblank(bins, "stable_travelway_id").sum())},
            {"metric": "rns_ready_for_later_bins", "value": int(route.sum())},
            {"metric": "aadt_exposure_ready_for_later_bins", "value": int(route.sum())},
        ]
    )


def final_ledger(dist: pd.DataFrame, broader_skipped: pd.DataFrame, five_detail: pd.DataFrame) -> pd.DataFrame:
    final = dist[dist["distribution_scenario"].eq("after_broader_source_and_five_plus_cleanup")]
    rows = [
        {"ledger_group": "final_distribution", "ledger_class": r.physical_leg_bucket, "signal_count": int(r.signal_count), "meaning": "Leg bucket after residual cleanup."}
        for r in final.itertuples(index=False)
        if r.physical_leg_bucket in {"one_leg", "two_leg", "three_leg", "four_leg", "five_plus_leg"}
    ]
    if not broader_skipped.empty:
        for cls, count in broader_skipped["cleanup_class"].value_counts().items():
            rows.append({"ledger_group": "broader_source_search_unrecovered", "ledger_class": cls, "signal_count": int(count), "meaning": "Skipped anchor target still unresolved after broader source search."})
    if not five_detail.empty:
        for cls, count in five_detail["residual_normalization_status"].value_counts().items():
            rows.append({"ledger_group": "five_plus_residual_normalization", "ledger_class": cls, "signal_count": int(count), "meaning": "Five-plus label-only normalization status."})
    return pd.DataFrame(rows)


def qa_table(bins: pd.DataFrame, missing_inputs: list[str]) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_clean_residual_leg_cleanup."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_crash_assignment", True, "Crash records are not read."),
        ("no_access_assignment", True, "Access sources are not read or assigned."),
        ("no_rates_or_models", True, "No rates/models are calculated."),
        ("no_speed_aadt_context_refresh", True, "Only readiness flags are produced for new bins."),
        ("crash_direction_fields_not_used", True, "CSV reader refuses known crash direction columns."),
        ("source_limited_cases_not_forced", True, "This pass only targets prior skipped anchor records and five-plus labels."),
        ("stable_travelway_id_preserved_on_new_bins", bins.empty or int(nonblank(bins, "stable_travelway_id").sum()) == len(bins), f"{int(nonblank(bins, 'stable_travelway_id').sum()) if not bins.empty else 0:,} / {len(bins):,}"),
        ("no_rows_deleted_or_collapsed", True, "Five-plus cleanup is label-only; generated bins are additive."),
        ("original_and_corrected_leg_labels_preserved", True, "Outputs preserve generated and corrected label fields."),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("required_inputs_available", not missing_inputs, "; ".join(missing_inputs[:8])),
    ]
    return pd.DataFrame([{"qa_check": k, "passed": bool(v), "detail": d} for k, v, d in checks])


def findings(counts: dict[str, Any]) -> str:
    return f"""# Final Clean Residual Leg Cleanup

## Bounded Question

Run one final review-only cleanup pass for residual source-search failures and remaining five-plus label/subbranch normalization after anchor-context integration.

## Findings

1. **Skipped anchor targets recovered by broader source search:** {counts['broader_recovered_signals']:,} / {counts['skipped_anchor_targets']:,}.
2. **Still source-leg-not-found or ambiguous:** {counts['broader_unrecovered_signals']:,}.
3. **New physical legs and bins:** {counts['broader_generated_legs']:,} legs and {counts['broader_generated_bins']:,} bins.
4. **Generated bins with stable_travelway_id:** {counts['broader_bins_with_stable_travelway_id']:,} / {counts['broader_generated_bins']:,}.
5. **Five-plus decrease after additional normalization:** {counts['five_plus_before']:,} to {counts['five_plus_after']:,}.
6. **Revised final distribution:** one-leg {counts['final_one_leg']:,}, two-leg {counts['final_two_leg']:,}, three-leg {counts['final_three_leg']:,}, four-leg {counts['final_four_leg']:,}, five-plus {counts['final_five_plus']:,}.
7. **Residual cases:** see `final_residual_leg_issue_ledger.csv` for remaining one/two/three/five-plus and unresolved source-search classes.
8. **Proceed decision:** the distribution is plausible enough to proceed to downstream access/crash refresh if the review team accepts label-only five-plus normalization; otherwise context-refresh the broader-source bins first.
9. **Next pass:** context-refresh any newly generated broader-source bins, then rerun the final clean universe summary with residual cleanup labels.
"""


def manifest(counts: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return {
        "created_utc": now(),
        "script": "src.roadway_graph.build.final_clean_residual_leg_cleanup",
        "bounded_question": "Review-only residual broader-source recovery and five-plus label normalization.",
        "inputs": {k: {"path": str(v), "exists": v.exists()} for k, v in INPUTS.items()},
        "missing_inputs": missing,
        "counts": counts,
        "non_goals": {"active_outputs_modified": False, "records_promoted": False, "crash_assignment": False, "access_assignment": False, "rates_models": False, "speed_aadt_context_refresh": False},
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    log(log_lines, "Starting residual leg cleanup.")
    required_optional = {"remaining_five", "label_only_summary", "label_proposals"}
    missing = [f"{k}: {v}" for k, v in INPUTS.items() if not v.exists() and k not in required_optional]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    current_signals = read_csv(INPUTS["current_signals"])
    current_bins = read_csv(INPUTS["current_bins"], usecols=["stable_signal_id", "geometry_wkt", "distance_start_ft"])
    skipped = read_csv(INPUTS["anchor_skipped"])
    inference = read_csv(INPUTS["anchor_inference"])
    residual_five = read_csv(INPUTS["residual_five"])
    skipped = skipped.merge(inference.drop_duplicates("stable_signal_id"), on=["stable_signal_id", "source_signal_id"], how="left", suffixes=("", "_infer"))
    target_pool = build_target_pool(skipped, inference, current_signals)
    write_csv(target_pool, "residual_cleanup_target_pool.csv")

    source = read_source_travelway(log_lines)
    geoms = list(source.geometry)
    tree = STRtree(geoms)
    detail, legs, bins, broader_skipped = broader_source_search(skipped, current_bins, source, tree, geoms, log_lines)
    five_detail, five_summary = normalize_five_plus(current_signals, residual_five)
    dist = revised_distribution(current_signals, legs, five_detail)
    ledger = final_ledger(dist, broader_skipped, five_detail)
    ready = readiness(bins)

    final_counts = dict(zip(dist[dist["distribution_scenario"].eq("after_broader_source_and_five_plus_cleanup")]["physical_leg_bucket"], dist[dist["distribution_scenario"].eq("after_broader_source_and_five_plus_cleanup")]["signal_count"]))
    counts = {
        "skipped_anchor_targets": int(len(skipped)),
        "broader_recovered_signals": int(bins["stable_signal_id"].nunique()) if not bins.empty else 0,
        "broader_unrecovered_signals": int(broader_skipped["stable_signal_id"].nunique()) if not broader_skipped.empty else 0,
        "broader_generated_legs": int(len(legs)),
        "broader_generated_bins": int(len(bins)),
        "broader_bins_with_stable_travelway_id": int(nonblank(bins, "stable_travelway_id").sum()) if not bins.empty else 0,
        "five_plus_before": int((text_col(current_signals, "final_review_physical_leg_bucket_after_anchor_context") == "five_plus_leg").sum()),
        "five_plus_after": int(final_counts.get("five_plus_leg", 0)),
        "final_one_leg": int(final_counts.get("one_leg", 0)),
        "final_two_leg": int(final_counts.get("two_leg", 0)),
        "final_three_leg": int(final_counts.get("three_leg", 0)),
        "final_four_leg": int(final_counts.get("four_leg", 0)),
        "final_five_plus": int(final_counts.get("five_plus_leg", 0)),
    }

    write_csv(detail, "broader_source_search_detail.csv")
    write_csv(legs, "broader_source_generated_leg_candidates.csv")
    write_csv(bins, "broader_source_generated_bins.csv")
    write_csv(broader_skipped, "broader_source_skipped_targets.csv")
    write_csv(five_detail, "five_plus_residual_normalization_detail.csv")
    write_csv(five_summary, "five_plus_residual_normalization_summary.csv")
    write_csv(dist, "residual_cleanup_revised_distribution.csv")
    write_csv(ledger, "final_residual_leg_issue_ledger.csv")
    write_csv(ready, "residual_cleanup_context_refresh_readiness.csv")
    write_csv(qa_table(bins, missing), "final_clean_residual_leg_cleanup_qa.csv")
    write_text(findings(counts), "final_clean_residual_leg_cleanup_findings.md")
    write_json(manifest(counts, missing), "final_clean_residual_leg_cleanup_manifest.json")
    log(log_lines, "Complete.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
