"""Review-only source-Travelway missing-leg candidate generation.

Bounded question:
    Generate review-only missing physical-leg candidate bins for the
    high-confidence 1,448-signal queue from the final clean missing-leg audit.

This pass does not modify active outputs, promote records, assign crashes or
access, assign speed/AADT, calculate rates/models, or use crash direction
fields.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyogrio
from shapely import wkt
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_generation"
QUEUE_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_queue_audit"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
LEG_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_leg_recovery_normalization"
SOURCE_TRAVELWAY = ROOT / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "target_queue": QUEUE_DIR / "missing_leg_generation_target_queue.csv",
    "queue_summary": QUEUE_DIR / "missing_leg_generation_target_summary.csv",
    "queue_manifest": QUEUE_DIR / "missing_leg_queue_audit_manifest.json",
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "final_distribution": FINAL_DIR / "final_clean_physical_leg_distribution.csv",
    "final_window_availability": FINAL_DIR / "final_clean_bin_window_availability.csv",
    "leg_source_zone": LEG_DIR / "final_clean_source_zone_expected_leg_detail.csv",
    "one_two_detail": LEG_DIR / "one_two_leg_recoverability_detail.csv",
    "leg_proposals": LEG_DIR / "corrected_leg_label_proposals.csv",
    "remaining_issue_summary": LEG_DIR / "remaining_leg_issue_summary.csv",
    "source_travelway": SOURCE_TRAVELWAY,
}

DISTANCE_BREAKS = [(i, i + 50) for i in range(0, 1000, 50)]
SENSITIVITY_BREAKS = [(i, i + 50) for i in range(1000, 2500, 50)]


def log(lines: list[str], message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    lines.append(f"{stamp} {message}")
    print(message)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def stable_hash(parts: Iterable[object], prefix: str, n: int = 20) -> str:
    text = "|".join("" if pd.isna(p) else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:n]}"


def geom_hash(geom) -> str:
    if geom is None or geom.is_empty:
        return ""
    return hashlib.sha1(geom.wkb).hexdigest()[:20]


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


def distance_band(start: float, end: float) -> str:
    if end <= 250:
        return "0_250ft"
    if end <= 500:
        return "250_500ft"
    if end <= 750:
        return "500_750ft"
    if end <= 1000:
        return "750_1000ft"
    if end <= 1500:
        return "1000_1500ft"
    return "1500_2500ft"


def bearing_sector(dx: float, dy: float) -> str | None:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    sector = int(((angle + 22.5) % 360) // 45)
    return f"sector_{sector:02d}"


def sector_between(a: Point, b: Point) -> str | None:
    return bearing_sector(b.x - a.x, b.y - a.y)


def parse_geom(value: object):
    if pd.isna(value):
        return None
    try:
        geom = wkt.loads(str(value))
        if geom.is_empty:
            return None
        return geom
    except Exception:
        return None


def line_components(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
    return []


def nearest_component(geom, anchor: Point) -> LineString | None:
    comps = line_components(geom)
    if not comps:
        return None
    return min(comps, key=lambda g: g.distance(anchor))


def endpoint_point(line: LineString, start: bool) -> Point:
    coords = list(line.coords)
    return Point(coords[0] if start else coords[-1])


def orient_line_for_sector(line: LineString, anchor: Point, desired_sector: str | None) -> tuple[float, int]:
    """Return anchor project distance and direction sign along line."""
    start_proj = line.project(anchor)
    if desired_sector is None:
        # Choose longer available side.
        return start_proj, 1 if (line.length - start_proj) >= start_proj else -1
    start_sector = sector_between(anchor, endpoint_point(line, True))
    end_sector = sector_between(anchor, endpoint_point(line, False))
    if end_sector == desired_sector and start_sector != desired_sector:
        return start_proj, 1
    if start_sector == desired_sector and end_sector != desired_sector:
        return start_proj, -1
    return start_proj, 1 if (line.length - start_proj) >= start_proj else -1


def segment_for_bin(line: LineString, anchor_proj: float, direction: int, start_ft: float, end_ft: float):
    if direction >= 0:
        a = min(line.length, anchor_proj + start_ft)
        b = min(line.length, anchor_proj + end_ft)
    else:
        a = max(0.0, anchor_proj - end_ft)
        b = max(0.0, anchor_proj - start_ft)
    if b - a < 5:
        return None
    try:
        seg = substring(line, a, b)
        if seg.is_empty or seg.length < 5:
            return None
        return seg
    except Exception:
        return None


def load_source_travelway() -> pd.DataFrame:
    cols = [
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "FROM_MEASURE",
        "TO_MEASURE",
        "RTE_FROM_M",
        "RTE_TO_MSR",
        "LOC_COMP_D",
        "RIM_FACILI",
        "RTE_RAMP_C",
        "RIM_ACCESS",
        "Stage1_SourceLayer",
    ]
    gdf = pyogrio.read_dataframe(SOURCE_TRAVELWAY, layer="source_travelway_full", columns=cols, fid_as_index=True)
    gdf = gdf.reset_index().rename(columns={"fid": "source_feature_local_fid"})
    gdf["source_feature_local_fid"] = gdf["source_feature_local_fid"].astype(int)
    gdf["geometry_hash"] = gdf.geometry.map(geom_hash)
    gdf["stable_travelway_id"] = gdf.apply(
        lambda r: stable_hash(
            [
                "source_travelway_full",
                r.get("source_feature_local_fid"),
                r.get("RTE_ID"),
                r.get("RTE_NM"),
                r.get("FROM_MEASURE"),
                r.get("TO_MEASURE"),
                r.get("geometry_hash"),
            ],
            "tw",
            16,
        ),
        axis=1,
    )
    return gdf


def build_targets(queue: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    include_classes = {
        "ready_for_source_travelway_missing_leg_generation",
        "three_leg_missing_fourth_ready",
    }
    targets = queue[queue["next_generation_class"].isin(include_classes)].copy()
    targets = targets.merge(
        signals[
            [
                "stable_signal_id",
                "source_signal_id",
                "GLOBALID",
                "recovery_branch",
                "signal_geometry_wkt",
                "review_only_recovery_provenance",
            ]
        ].drop_duplicates("stable_signal_id"),
        on="stable_signal_id",
        how="left",
        suffixes=("", "_signal"),
    )
    for col in ["source_signal_id", "GLOBALID", "recovery_branch"]:
        signal_col = f"{col}_signal"
        if signal_col in targets.columns:
            targets[col] = targets[col].combine_first(targets[signal_col])
            targets = targets.drop(columns=[signal_col])
    targets["target_generation_scope"] = targets["next_generation_class"]
    return targets


def prepare_signal_bins(bins: pd.DataFrame, target_ids: set[str]) -> dict[str, pd.DataFrame]:
    subset = bins[bins["stable_signal_id"].astype(str).isin(target_ids)].copy()
    subset["parsed_geometry"] = subset["geometry_wkt"].map(parse_geom)
    subset = subset[subset["parsed_geometry"].notna()]
    return {sid: g.copy() for sid, g in subset.groupby("stable_signal_id", sort=False)}


def signal_anchor_and_existing_sectors(bin_df: pd.DataFrame) -> tuple[Point | None, set[str]]:
    if bin_df.empty:
        return None, set()
    near = bin_df[pd.to_numeric(bin_df["distance_end_ft"], errors="coerce").le(250)].copy()
    if near.empty:
        near = bin_df.copy()
    geoms = [g for g in near["parsed_geometry"] if g is not None and not g.is_empty]
    if not geoms:
        return None, set()
    anchor = unary_union(geoms).centroid
    sectors = set()
    for geom in geoms:
        centroid = geom.centroid
        sec = sector_between(anchor, centroid)
        if sec:
            sectors.add(sec)
    return anchor, sectors


def generate_for_signal(
    target: pd.Series,
    bin_df: pd.DataFrame,
    source_df: pd.DataFrame,
    tree: STRtree,
    geoms: list,
) -> tuple[list[dict], list[dict], list[dict], dict | None]:
    sid = str(target["stable_signal_id"])
    source_signal_id = target.get("source_signal_id")
    anchor, existing_sectors = signal_anchor_and_existing_sectors(bin_df)
    missing_count = int(pd.to_numeric(target.get("missing_leg_count_to_generate"), errors="coerce") or 0)
    if anchor is None:
        return [], [], [], {"stable_signal_id": sid, "source_signal_id": source_signal_id, "skip_reason": "no_existing_bin_anchor"}
    if missing_count <= 0:
        return [], [], [], {"stable_signal_id": sid, "source_signal_id": source_signal_id, "skip_reason": "missing_leg_count_zero"}

    candidate_idx = tree.query(anchor.buffer(250).envelope)
    candidates = []
    for idx in candidate_idx:
        geom = geoms[int(idx)]
        if geom is None or geom.is_empty:
            continue
        dist = geom.distance(anchor)
        if dist > 250:
            continue
        line = nearest_component(geom, anchor)
        if line is None or line.length < 50:
            continue
        nearest = line.interpolate(line.project(anchor))
        sec = sector_between(anchor, nearest if nearest.distance(anchor) > 1 else line.centroid)
        if sec is None:
            sec = sector_between(anchor, line.centroid)
        if sec in existing_sectors:
            continue
        row = source_df.iloc[int(idx)]
        candidates.append((dist, sec, line, row))

    if not candidates:
        return [], [], [], {"stable_signal_id": sid, "source_signal_id": source_signal_id, "skip_reason": "source_leg_not_found"}

    selected = []
    used_sectors = set()
    for dist, sec, line, row in sorted(candidates, key=lambda x: (x[0], str(x[1]))):
        if sec in used_sectors:
            continue
        selected.append((dist, sec, line, row))
        used_sectors.add(sec)
        if len(selected) >= missing_count:
            break

    leg_rows: list[dict] = []
    source_rows: list[dict] = []
    bin_rows: list[dict] = []
    for leg_num, (dist, sec, line, row) in enumerate(selected, start=1):
        corrected_leg_id = stable_hash([sid, "missing_leg", sec, row["source_feature_local_fid"]], "physleg", 16)
        subbranch_id = stable_hash([corrected_leg_id, row["source_feature_local_fid"]], "subbranch", 16)
        anchor_proj, direction = orient_line_for_sector(line, anchor, sec)
        source_rows.append(
            {
                "stable_signal_id": sid,
                "source_signal_id": source_signal_id,
                "source_bearing_sector": sec,
                "source_feature_local_fid": row["source_feature_local_fid"],
                "stable_travelway_id": row["stable_travelway_id"],
                "source_route_id": row.get("RTE_ID"),
                "source_route_name": row.get("RTE_NM"),
                "source_route_common": row.get("RTE_COMMON"),
                "source_measure_start": row.get("FROM_MEASURE"),
                "source_measure_end": row.get("TO_MEASURE"),
                "source_distance_to_anchor_ft": round(float(dist), 3),
                "source_leg_selection_status": "selected_for_missing_leg_generation",
                "recovery_class": target.get("next_generation_class"),
            }
        )
        leg_rows.append(
            {
                "stable_signal_id": sid,
                "source_signal_id": source_signal_id,
                "generated_missing_leg_id": corrected_leg_id,
                "corrected_physical_leg_id": corrected_leg_id,
                "corrected_carriageway_subbranch_id": subbranch_id,
                "source_bearing_sector": sec,
                "stable_travelway_id": row["stable_travelway_id"],
                "source_feature_local_fid": row["source_feature_local_fid"],
                "lineage_match_method": "source_travelway_near_anchor_absent_bearing_sector",
                "lineage_confidence": "medium_review_only",
                "recovery_class": target.get("next_generation_class"),
            }
        )
        for start, end in DISTANCE_BREAKS + SENSITIVITY_BREAKS:
            seg = segment_for_bin(line, anchor_proj, direction, start, end)
            if seg is None:
                continue
            stable_bin_id = stable_hash([sid, corrected_leg_id, row["source_feature_local_fid"], start, end, geom_hash(seg)], "bin", 20)
            bin_rows.append(
                {
                    "stable_signal_id": sid,
                    "source_signal_id": source_signal_id,
                    "GLOBALID": target.get("GLOBALID"),
                    "stable_bin_id": stable_bin_id,
                    "stable_travelway_id": row["stable_travelway_id"],
                    "source_layer": "source_travelway_full",
                    "source_route_id": row.get("RTE_ID"),
                    "source_route_name": row.get("RTE_NM"),
                    "source_route_common": row.get("RTE_COMMON"),
                    "source_measure_start": row.get("FROM_MEASURE"),
                    "source_measure_end": row.get("TO_MEASURE"),
                    "source_feature_local_fid": row["source_feature_local_fid"],
                    "geometry_hash": geom_hash(seg),
                    "lineage_match_method": "source_travelway_near_anchor_absent_bearing_sector",
                    "lineage_confidence": "medium_review_only",
                    "physical_leg_id": corrected_leg_id,
                    "corrected_physical_leg_id": corrected_leg_id,
                    "carriageway_subbranch_id": subbranch_id,
                    "corrected_carriageway_subbranch_id": subbranch_id,
                    "source_bearing_sector": sec,
                    "distance_start_ft": start,
                    "distance_end_ft": end,
                    "distance_band": distance_band(start, end),
                    "analysis_window": "0_1000" if end <= 1000 else "1000_2500",
                    "geometry_wkt": seg.wkt,
                    "partial_coverage_flag": False,
                    "review_only_recovery_provenance": "final_clean_missing_leg_generation",
                    "leg_recovery_status": "generated_missing_leg_candidate",
                    "review_only": True,
                }
            )

    if not bin_rows:
        return [], [], [], {"stable_signal_id": sid, "source_signal_id": source_signal_id, "skip_reason": "source_geometry_ambiguous"}
    return source_rows, leg_rows, bin_rows, None


def distribution_after_generation(signals: pd.DataFrame, bins: pd.DataFrame, generated_legs: pd.DataFrame) -> pd.DataFrame:
    current = (
        signals[["stable_signal_id", "signal_level_physical_leg_count"]]
        .copy()
        .rename(columns={"signal_level_physical_leg_count": "current_count"})
    )
    binned = bins.groupby("stable_signal_id")["physical_leg_id"].apply(lambda s: s.dropna().astype(str).nunique()).reset_index(name="binned_count")
    current = current.merge(binned, on="stable_signal_id", how="left")
    current["current_count"] = pd.to_numeric(current["current_count"], errors="coerce")
    current["binned_count"] = current["binned_count"].fillna(0)
    current["current_count"] = current["binned_count"].where(current["binned_count"].gt(0), current["current_count"]).fillna(0)
    add = generated_legs.groupby("stable_signal_id")["corrected_physical_leg_id"].nunique().reset_index(name="generated_leg_count")
    current = current.merge(add, on="stable_signal_id", how="left")
    current["generated_leg_count"] = current["generated_leg_count"].fillna(0)
    current["after_generation_count"] = current["current_count"] + current["generated_leg_count"]
    rows = []
    for scenario, col in [("current", "current_count"), ("after_actual_missing_leg_generation", "after_generation_count")]:
        tmp = current[col].map(leg_bucket).value_counts().rename_axis("physical_leg_bucket").reset_index(name="signal_count")
        tmp["distribution_scenario"] = scenario
        tmp["share"] = (tmp["signal_count"] / tmp["signal_count"].sum()).round(4)
        rows.append(tmp)
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[str] = []
    started = datetime.now(timezone.utc)
    log(progress, "Starting final clean missing-leg generation.")

    queue = read_csv(INPUTS["target_queue"])
    signals = read_csv(INPUTS["final_signals"])
    bins = read_csv(INPUTS["final_bins"])
    targets = build_targets(queue, signals)
    log(progress, f"Loaded target pool: {len(targets)} high-confidence signals.")

    target_ids = set(targets["stable_signal_id"].dropna().astype(str))
    signal_bins = prepare_signal_bins(bins, target_ids)
    source_df = load_source_travelway()
    source_geoms = list(source_df.geometry)
    tree = STRtree(source_geoms)
    log(progress, f"Loaded source Travelway rows: {len(source_df)}.")

    all_source_rows: list[dict] = []
    all_leg_rows: list[dict] = []
    all_bin_rows: list[dict] = []
    skipped: list[dict] = []
    for i, target in targets.iterrows():
        sid = str(target["stable_signal_id"])
        bdf = signal_bins.get(sid)
        if bdf is None or bdf.empty:
            skipped.append({"stable_signal_id": sid, "source_signal_id": target.get("source_signal_id"), "skip_reason": "no_existing_bins_for_target"})
            continue
        source_rows, leg_rows, bin_rows, skip = generate_for_signal(target, bdf, source_df, tree, source_geoms)
        if skip:
            skipped.append(skip)
        else:
            all_source_rows.extend(source_rows)
            all_leg_rows.extend(leg_rows)
            all_bin_rows.extend(bin_rows)
        if (i + 1) % 250 == 0:
            log(progress, f"Processed {i + 1} target rows.")

    source_detail = pd.DataFrame(all_source_rows)
    leg_candidates = pd.DataFrame(all_leg_rows)
    gen_bins = pd.DataFrame(all_bin_rows)
    skipped_df = pd.DataFrame(skipped)

    targets.to_csv(OUT_DIR / "missing_leg_generation_target_signals.csv", index=False)
    source_detail.to_csv(OUT_DIR / "missing_leg_generation_source_leg_detail.csv", index=False)
    leg_candidates.to_csv(OUT_DIR / "missing_leg_generated_leg_candidates.csv", index=False)
    gen_bins.to_csv(OUT_DIR / "missing_leg_generated_bins.csv", index=False)
    skipped_df.to_csv(OUT_DIR / "missing_leg_generation_skipped_targets.csv", index=False)

    if gen_bins.empty:
        dist = pd.DataFrame()
    else:
        dist = distribution_after_generation(signals, bins, leg_candidates)
    if not dist.empty:
        dist.to_csv(OUT_DIR / "missing_leg_generation_revised_distribution_estimate.csv", index=False)
    else:
        pd.DataFrame(columns=["physical_leg_bucket", "signal_count", "distribution_scenario", "share"]).to_csv(
            OUT_DIR / "missing_leg_generation_revised_distribution_estimate.csv", index=False
        )

    summary_rows = [
        ("target_signals", len(targets)),
        ("signals_with_generated_missing_leg_candidates", gen_bins["stable_signal_id"].nunique() if not gen_bins.empty else 0),
        ("signals_skipped", skipped_df["stable_signal_id"].nunique() if not skipped_df.empty else 0),
        ("generated_physical_legs", leg_candidates["corrected_physical_leg_id"].nunique() if not leg_candidates.empty else 0),
        ("generated_bins", len(gen_bins)),
        ("generated_bins_0_1000", int(gen_bins["analysis_window"].eq("0_1000").sum()) if not gen_bins.empty else 0),
        ("generated_bins_1000_2500", int(gen_bins["analysis_window"].eq("1000_2500").sum()) if not gen_bins.empty else 0),
        ("bins_missing_stable_travelway_id", int(gen_bins["stable_travelway_id"].isna().sum()) if not gen_bins.empty else 0),
        (
            "one_two_target_success_signals",
            gen_bins.loc[gen_bins["stable_signal_id"].isin(targets.loc[targets["queue_source"].eq("recoverable_677_under_captured_one_two"), "stable_signal_id"]), "stable_signal_id"].nunique()
            if not gen_bins.empty
            else 0,
        ),
        (
            "three_leg_target_success_signals",
            gen_bins.loc[gen_bins["stable_signal_id"].isin(targets.loc[targets["queue_source"].eq("current_three_leg_missing_fourth_audit"), "stable_signal_id"]), "stable_signal_id"].nunique()
            if not gen_bins.empty
            else 0,
        ),
    ]
    summary = pd.DataFrame(summary_rows, columns=["metric", "value"])
    summary.to_csv(OUT_DIR / "missing_leg_generation_summary.csv", index=False)

    readiness = pd.DataFrame(
        [
            ("route_measure_identity_ready_bins", int(gen_bins[["source_route_id", "source_measure_start", "source_measure_end"]].notna().all(axis=1).sum()) if not gen_bins.empty else 0),
            ("roadway_context_ready_for_later_refresh", len(gen_bins)),
            ("rns_speed_ready_for_later_refresh", len(gen_bins)),
            ("aadt_v3_exposure_ready_for_later_refresh", len(gen_bins)),
            ("access_ready_later", len(gen_bins)),
            ("crash_assignment_ready_later", len(gen_bins)),
        ],
        columns=["readiness_metric", "bin_count"],
    )
    readiness["signal_count"] = gen_bins["stable_signal_id"].nunique() if not gen_bins.empty else 0
    readiness.to_csv(OUT_DIR / "missing_leg_generation_context_refresh_readiness.csv", index=False)

    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to review/current/final_clean_missing_leg_generation."),
            ("no_records_promoted", True, "Generated rows are review-only candidates."),
            ("no_crash_assignment", True, "Crash records were not read."),
            ("no_access_assignment", True, "Access assignment was not run."),
            ("no_rates_or_models", True, "No rates/models calculated."),
            ("no_speed_aadt_assignment", True, "Only later-refresh readiness flags were written."),
            ("crash_direction_fields_not_used", True, "No crash fields were read."),
            ("source_limited_cases_not_forced", True, "Only high-confidence queue classes were targeted."),
            ("stable_travelway_id_preserved_on_generated_bins", bool(gen_bins.empty or gen_bins["stable_travelway_id"].notna().all()), "Generated bins carry source-derived stable Travelway IDs."),
            ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/final_clean_missing_leg_generation"), str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "notes"],
    )
    qa.to_csv(OUT_DIR / "final_clean_missing_leg_generation_qa.csv", index=False)

    skip_counts = skipped_df["skip_reason"].value_counts().to_dict() if not skipped_df.empty else {}
    success = int(gen_bins["stable_signal_id"].nunique()) if not gen_bins.empty else 0
    generated_legs = int(leg_candidates["corrected_physical_leg_id"].nunique()) if not leg_candidates.empty else 0
    findings = f"""# Final Clean Missing-Leg Generation

## Bounded Question

Generate review-only missing-leg candidate bins for the high-confidence 1,448-signal queue. This pass does not context-refresh generated bins, assign speed/AADT, assign access/crashes, calculate rates/models, promote records, or modify active outputs.

## Findings

1. Target signals: **{len(targets):,}**.
2. Signals with generated missing-leg candidates: **{success:,}**.
3. Generated physical legs: **{generated_legs:,}**.
4. Generated bins: **{len(gen_bins):,}**.
5. One/two-leg target successes and three-leg target successes are reported in `missing_leg_generation_summary.csv`.
6. Skipped targets by reason: `{skip_counts}`.
7. Stable-lineage completeness: generated bins missing `stable_travelway_id` = **{int(gen_bins["stable_travelway_id"].isna().sum()) if not gen_bins.empty else 0}**.
8. Revised physical-leg distribution after generation is in `missing_leg_generation_revised_distribution_estimate.csv`.
9. Generated bins are ready for a bounded context-refresh pass because they carry route/measure/source Travelway lineage, but speed/AADT were not assigned here.
10. Next pass should context-refresh generated missing-leg bins, then rerun the final clean universe summary with label-only normalization plus generated missing-leg candidates.

## Method Note

For each target, this pass used existing final-clean bin geometry as the signal-zone anchor, selected nearby source Travelway rows within 250 ft whose bearing sector was not already represented by current bins, and generated 50-ft review-only bins outward from the anchor along source Travelway geometry.
"""
    (OUT_DIR / "final_clean_missing_leg_generation_findings.md").write_text(findings, encoding="utf-8")

    manifest = {
        "script": "src/active/roadway_graph/final_clean_missing_leg_generation.py",
        "created_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "inputs": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in INPUTS.items() if v.exists()},
        "outputs": [
            "missing_leg_generation_target_signals.csv",
            "missing_leg_generation_source_leg_detail.csv",
            "missing_leg_generated_leg_candidates.csv",
            "missing_leg_generated_bins.csv",
            "missing_leg_generation_skipped_targets.csv",
            "missing_leg_generation_summary.csv",
            "missing_leg_generation_revised_distribution_estimate.csv",
            "missing_leg_generation_context_refresh_readiness.csv",
            "final_clean_missing_leg_generation_findings.md",
            "final_clean_missing_leg_generation_qa.csv",
            "final_clean_missing_leg_generation_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "target_signals": int(len(targets)),
            "signals_generated": int(success),
            "signals_skipped": int(skipped_df["stable_signal_id"].nunique()) if not skipped_df.empty else 0,
            "generated_physical_legs": int(generated_legs),
            "generated_bins": int(len(gen_bins)),
            "generated_bins_missing_stable_travelway_id": int(gen_bins["stable_travelway_id"].isna().sum()) if not gen_bins.empty else 0,
        },
        "non_goals_confirmed": [
            "no_context_refresh",
            "no_speed_aadt_assignment",
            "no_access_assignment",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_active_outputs_modified",
        ],
    }
    (OUT_DIR / "final_clean_missing_leg_generation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(progress, "Wrote final clean missing-leg generation outputs.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
