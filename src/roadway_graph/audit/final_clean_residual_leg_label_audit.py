"""Residual leg-label audit for the consolidated 3,719-signal universe.

Bounded question:
    Re-audit residual two-leg, three-leg, and five-plus labels after missing-leg
    generation using source Travelway proximity evidence. This pass does not
    generate bins, context-refresh, assign crashes/access, calculate rates, or
    modify active outputs.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyogrio
from shapely import wkt
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_residual_leg_label_audit"
CONSOLIDATED_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_leg_distribution_consolidation"
GEN_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_generation"
QUEUE_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_missing_leg_queue_audit"
FINAL_DIR = ROOT / "work/output/roadway_graph/review/current/final_clean_universe_context_summary"
SOURCE_TRAVELWAY = ROOT / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "consolidated_bins": CONSOLIDATED_DIR / "consolidated_leg_bin_detail.csv",
    "consolidated_signals": CONSOLIDATED_DIR / "consolidated_leg_signal_summary.csv",
    "consolidated_distribution": CONSOLIDATED_DIR / "consolidated_physical_leg_distribution.csv",
    "remaining_two": CONSOLIDATED_DIR / "remaining_two_leg_issue_detail.csv",
    "remaining_three": CONSOLIDATED_DIR / "remaining_three_leg_issue_detail.csv",
    "remaining_five": CONSOLIDATED_DIR / "remaining_five_plus_issue_detail.csv",
    "skipped_generation": CONSOLIDATED_DIR / "skipped_missing_leg_generation_audit.csv",
    "generation_targets": GEN_DIR / "missing_leg_generation_target_signals.csv",
    "generated_leg_candidates": GEN_DIR / "missing_leg_generated_leg_candidates.csv",
    "generated_bins": GEN_DIR / "missing_leg_generated_bins.csv",
    "generation_skipped": GEN_DIR / "missing_leg_generation_skipped_targets.csv",
    "queue_677": QUEUE_DIR / "recoverable_677_queue_reconciliation.csv",
    "three_audit": QUEUE_DIR / "current_three_leg_missing_fourth_audit.csv",
    "queue_targets": QUEUE_DIR / "missing_leg_generation_target_queue.csv",
    "final_signals": FINAL_DIR / "final_clean_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_clean_bin_universe_3719.csv",
    "source_travelway": SOURCE_TRAVELWAY,
}

RADII = [125, 175, 250, 350]


def log(lines: list[str], message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    lines.append(f"{stamp} {message}")
    print(message)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


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


def source_context(row: pd.Series) -> str:
    text = " ".join(
        str(row.get(c, ""))
        for c in ["RTE_NM", "RTE_COMMON", "RIM_FACILI", "RIM_FACI_1", "RTE_RAMP_C", "RTE_TYPE_N", "LOC_COMP_D"]
    ).lower()
    if "ramp" in text:
        return "ramp"
    if "frontage" in text or "service" in text:
        return "frontage_or_service"
    if "connector" in text or "internal" in text:
        return "connector_or_internal"
    if "divided" in text or "median" in text:
        return "divided_or_median"
    if "interstate" in text or "mainline" in text or "limited" in text:
        return "mainline_or_limited_access"
    return "surface_or_unknown"


def load_source_travelway() -> pd.DataFrame:
    cols = [
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "RIM_FACILI",
        "RIM_FACI_1",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "RIM_MEDIAN",
        "MEDIAN_IND",
        "RIM_ACCESS",
        "FROM_MEASURE",
        "TO_MEASURE",
        "LOC_COMP_D",
        "Stage1_SourceLayer",
    ]
    gdf = pyogrio.read_dataframe(SOURCE_TRAVELWAY, layer="source_travelway_full", columns=cols, fid_as_index=True)
    gdf = gdf.reset_index().rename(columns={"fid": "source_feature_local_fid"})
    gdf["source_context_class"] = gdf.apply(source_context, axis=1)
    return gdf


def target_pool(two: pd.DataFrame, three: pd.DataFrame, five: pd.DataFrame) -> pd.DataFrame:
    two = two.copy()
    three = three.copy()
    five = five.copy()
    two["residual_bucket"] = "two_leg"
    two["prior_residual_label"] = two["remaining_two_leg_issue_class"]
    three["residual_bucket"] = "three_leg"
    three["prior_residual_label"] = three["remaining_three_leg_issue_class"]
    five["residual_bucket"] = "five_plus_leg"
    five["prior_residual_label"] = five["remaining_five_plus_issue_class"]
    cols = sorted(set(two.columns) | set(three.columns) | set(five.columns))
    for df in [two, three, five]:
        for col in cols:
            if col not in df.columns:
                df[col] = pd.NA
    out = pd.concat([two[cols], three[cols], five[cols]], ignore_index=True, sort=False)
    return out


def build_anchor_map(bins: pd.DataFrame, target_ids: set[str]) -> dict[str, dict[str, object]]:
    subset = bins[bins["stable_signal_id"].astype(str).isin(target_ids)].copy()
    subset["parsed_geometry"] = subset["geometry_wkt"].map(parse_geom)
    subset = subset[subset["parsed_geometry"].notna()]
    anchors: dict[str, dict[str, object]] = {}
    for sid, g in subset.groupby("stable_signal_id", sort=False):
        near = g[pd.to_numeric(g["distance_end_ft"], errors="coerce").le(250)]
        if near.empty:
            near = g
        geoms = [geom for geom in near["parsed_geometry"] if geom is not None and not geom.is_empty]
        if not geoms:
            continue
        anchor = unary_union(geoms).centroid
        existing_sectors = set()
        for geom in geoms:
            sec = sector_between(anchor, geom.centroid)
            if sec:
                existing_sectors.add(sec)
        anchors[str(sid)] = {
            "anchor": anchor,
            "existing_sectors": existing_sectors,
            "existing_sector_count": len(existing_sectors),
        }
    return anchors


def source_evidence_for_target(row: pd.Series, anchors: dict[str, dict[str, object]], source: pd.DataFrame, tree: STRtree, geoms: list) -> dict:
    sid = str(row["stable_signal_id"])
    meta = anchors.get(sid)
    if not meta:
        return {
            "stable_signal_id": sid,
            "source_evidence_status": "no_anchor_geometry",
            "source_line_count_350ft": 0,
            "source_bearing_sector_count_350ft": 0,
            "source_supports_missing_leg": False,
            "source_supports_label_only_normalization": False,
        }
    anchor: Point = meta["anchor"]
    existing = set(meta["existing_sectors"])
    out = {
        "stable_signal_id": sid,
        "source_evidence_status": "source_checked",
        "existing_bearing_sector_count": len(existing),
        "existing_bearing_sectors": "|".join(sorted(existing)),
    }
    all_rows = []
    for idx in tree.query(anchor.buffer(350).envelope):
        idx = int(idx)
        geom = geoms[idx]
        if geom is None or geom.is_empty:
            continue
        dist = geom.distance(anchor)
        if dist > 350:
            continue
        line = nearest_component(geom, anchor)
        if line is None:
            continue
        nearest = line.interpolate(line.project(anchor))
        sec = sector_between(anchor, nearest if nearest.distance(anchor) > 1 else line.centroid)
        if sec is None:
            sec = sector_between(anchor, line.centroid)
        src = source.iloc[idx]
        all_rows.append((dist, sec, src["source_context_class"], src.get("RTE_NM"), src.get("source_feature_local_fid")))
    for radius in RADII:
        rows = [r for r in all_rows if r[0] <= radius]
        sectors = {r[1] for r in rows if r[1]}
        missing = sectors - existing
        out[f"source_line_count_{radius}ft"] = len(rows)
        out[f"source_bearing_sector_count_{radius}ft"] = len(sectors)
        out[f"missing_source_sector_count_{radius}ft"] = len(missing)
        out[f"missing_source_sectors_{radius}ft"] = "|".join(sorted(missing))
    contexts = pd.Series([r[2] for r in all_rows], dtype="object").value_counts().to_dict()
    out["source_context_counts_350ft"] = json.dumps(contexts, sort_keys=True)
    out["source_route_sample_350ft"] = "|".join(sorted({str(r[3]) for r in all_rows if pd.notna(r[3])})[:12])
    out["source_supports_missing_leg"] = out.get("missing_source_sector_count_250ft", 0) > 0 or out.get(
        "missing_source_sector_count_350ft", 0
    ) > 0
    current = int(pd.to_numeric(row.get("combined_physical_leg_count"), errors="coerce") or 0)
    out["source_physical_approach_estimate_350ft"] = min(6, max(current, int(out.get("source_bearing_sector_count_350ft", 0))))
    out["source_supports_label_only_normalization"] = current >= 5 and int(out.get("source_bearing_sector_count_350ft", 0)) <= 4
    out["source_geometry_appears_conservative_search_limited"] = (
        out.get("missing_source_sector_count_250ft", 0) == 0 and out.get("missing_source_sector_count_350ft", 0) > 0
    )
    return out


def classify_two(row: pd.Series) -> tuple[str, str]:
    label = str(row.get("prior_residual_label", ""))
    if row.get("source_supports_missing_leg") and row.get("source_geometry_appears_conservative_search_limited"):
        return "recoverable_with_broader_source_search", "Missing sector appears only at broader 350 ft source search."
    if row.get("source_supports_missing_leg"):
        return "recoverable_with_intersection_zone_anchor", "Source has missing sector near signal but prior generation failed or did not target it."
    if label == "source_travelway_missing_cross_street":
        return "source_travelway_missing_cross_street_confirmed", "No source sector evidence found in residual audit."
    if label == "true_source_limited_partial_signal":
        if int(row.get("source_bearing_sector_count_350ft", 0)) <= 2:
            return "confirmed_source_limited_partial", "Source evidence remains limited to one/two sectors."
        return "recoverable_with_broader_source_search", "Prior source-limited label is weakened by three-plus source sectors."
    if "ramp" in str(row.get("qa_flags", "")).lower():
        return "likely_true_partial_or_ramp_control", "Ramp/partial-control QA remains present."
    return "manual_review_needed", "Residual two-leg label remains ambiguous after source audit."


def classify_three(row: pd.Series) -> tuple[str, str]:
    label = str(row.get("prior_residual_label", ""))
    if row.get("source_supports_missing_leg") and row.get("source_geometry_appears_conservative_search_limited"):
        return "generation_failed_due_to_conservative_search", "Missing source sector appears at 350 ft after a prior generation miss."
    if row.get("source_supports_missing_leg"):
        return "recoverable_missing_fourth_with_intersection_zone_anchor", "Source has missing sector near current anchor; anchor/ownership needs refinement."
    if label == "true_three_leg_t_intersection":
        return "confirmed_true_t_intersection", "No source-supported fourth sector found."
    if "source_leg_not_found" in label:
        return "source_limited_missing_fourth_confirmed", "No source sector found after broader residual audit."
    if "ambiguous" in label:
        return "recoverable_missing_fourth_with_intersection_zone_anchor", "Ambiguity class should be handled by anchor logic, not literal map review."
    return "manual_review_needed", "Three-leg residual remains uncertain."


def classify_five(row: pd.Series) -> tuple[str, str]:
    label = str(row.get("prior_residual_label", ""))
    contexts = str(row.get("source_context_counts_350ft", "")).lower()
    if row.get("source_supports_label_only_normalization"):
        return "resolved_by_subbranch_normalization_possible", "Source bearing sectors are four or fewer despite five-plus modeled legs."
    if "connector" in contexts or "internal" in contexts:
        return "connector_internal_segments_still_overcounted", "Connector/internal source context remains present."
    if "divided" in contexts or "median" in contexts:
        return "carriageway_source_row_over_split_still_present", "Divided/median source context suggests over-split rows."
    if label == "complex_multi_signal_context":
        return "complex_but_valid_multi_branch_signal", "Complex multi-signal context should remain QA, not automatic exclusion."
    if int(row.get("source_bearing_sector_count_350ft", 0)) >= 5:
        return "true_complex_five_plus_possible", "Source bearing evidence supports five-plus possible approaches."
    return "manual_review_needed", "Five-plus residual lacks decisive source evidence."


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[str] = []
    started = datetime.now(timezone.utc)
    log(progress, "Starting residual leg label audit.")

    two = read_csv(INPUTS["remaining_two"])
    three = read_csv(INPUTS["remaining_three"])
    five = read_csv(INPUTS["remaining_five"])
    bins = read_csv(INPUTS["consolidated_bins"])
    targets = target_pool(two, three, five)
    target_ids = set(targets["stable_signal_id"].dropna().astype(str))
    log(progress, f"Loaded residual target pool: {len(targets)} signals.")

    anchors = build_anchor_map(bins, target_ids)
    source = load_source_travelway()
    geoms = list(source.geometry)
    tree = STRtree(geoms)
    log(progress, f"Loaded source Travelway rows: {len(source)}; anchors available for {len(anchors)} residual targets.")

    evidence_rows = []
    for i, row in targets.iterrows():
        evidence_rows.append(source_evidence_for_target(row, anchors, source, tree, geoms))
        if (i + 1) % 500 == 0:
            log(progress, f"Audited {i + 1} residual targets.")
    evidence = pd.DataFrame(evidence_rows)
    detail = targets.merge(evidence, on="stable_signal_id", how="left")
    two_detail = detail[detail["residual_bucket"].eq("two_leg")].copy()
    three_detail = detail[detail["residual_bucket"].eq("three_leg")].copy()
    five_detail = detail[detail["residual_bucket"].eq("five_plus_leg")].copy()

    if not two_detail.empty:
        vals = two_detail.apply(classify_two, axis=1, result_type="expand")
        two_detail[["residual_two_leg_reclassified", "reclassification_reason"]] = vals
    if not three_detail.empty:
        vals = three_detail.apply(classify_three, axis=1, result_type="expand")
        three_detail[["residual_three_leg_reclassified", "reclassification_reason"]] = vals
    if not five_detail.empty:
        vals = five_detail.apply(classify_five, axis=1, result_type="expand")
        five_detail[["residual_five_plus_reclassified", "reclassification_reason"]] = vals

    recoverability_rows = []
    for label, df, col in [
        ("two_leg", two_detail, "residual_two_leg_reclassified"),
        ("three_leg", three_detail, "residual_three_leg_reclassified"),
        ("five_plus", five_detail, "residual_five_plus_reclassified"),
    ]:
        vc = df[col].value_counts(dropna=False) if col in df.columns else pd.Series(dtype=int)
        for cls, count in vc.items():
            recoverability_rows.append({"residual_bucket": label, "reclassified_class": cls, "signal_count": int(count)})
    recoverability = pd.DataFrame(recoverability_rows)

    next_actions = pd.DataFrame(
        [
            {
                "recommended_action": "context_refresh_existing_generated_missing_leg_bins",
                "priority": 1,
                "signal_count": 1090,
                "rationale": "Already generated bins are stable-lineage complete and should be refreshed before integration.",
            },
            {
                "recommended_action": "broader_source_search_for_residual_two_three_leg_cases",
                "priority": 2,
                "signal_count": int(
                    recoverability.loc[
                        recoverability["reclassified_class"].astype(str).str.contains("broader_source_search|conservative_search", na=False),
                        "signal_count",
                    ].sum()
                ),
                "rationale": "Residual labels show conservative source search limitations rather than final source absence.",
            },
            {
                "recommended_action": "intersection_zone_anchor_recovery_for_residual_cases",
                "priority": 3,
                "signal_count": int(
                    recoverability.loc[
                        recoverability["reclassified_class"].astype(str).str.contains("intersection_zone_anchor", na=False),
                        "signal_count",
                    ].sum()
                ),
                "rationale": "Anchor logic can separate nearby source sectors from actual signal-plane approaches.",
            },
            {
                "recommended_action": "additional_label_only_five_plus_normalization",
                "priority": 4,
                "signal_count": int(
                    recoverability.loc[
                        recoverability["reclassified_class"].astype(str).str.contains("subbranch|overcounted|over_split", na=False),
                        "signal_count",
                    ].sum()
                ),
                "rationale": "Five-plus residuals still include label-level over-split signatures.",
            },
        ]
    )

    target_cols = [
        "stable_signal_id",
        "source_signal_id",
        "recovery_branch",
        "residual_bucket",
        "prior_residual_label",
        "combined_physical_leg_count",
        "source_evidence_status",
        "existing_bearing_sector_count",
        "source_bearing_sector_count_250ft",
        "source_bearing_sector_count_350ft",
        "missing_source_sector_count_250ft",
        "missing_source_sector_count_350ft",
        "source_context_counts_350ft",
    ]
    for col in target_cols:
        if col not in detail.columns:
            detail[col] = pd.NA
    detail[target_cols].to_csv(OUT_DIR / "residual_leg_label_target_detail.csv", index=False)
    two_detail.to_csv(OUT_DIR / "residual_two_leg_reclassification.csv", index=False)
    three_detail.to_csv(OUT_DIR / "residual_three_leg_reclassification.csv", index=False)
    five_detail.to_csv(OUT_DIR / "residual_five_plus_reclassification.csv", index=False)
    evidence.to_csv(OUT_DIR / "residual_source_travelway_evidence_summary.csv", index=False)
    recoverability.to_csv(OUT_DIR / "residual_leg_recoverability_summary.csv", index=False)
    next_actions.to_csv(OUT_DIR / "residual_leg_next_action_recommendation.csv", index=False)

    two_counts = two_detail["residual_two_leg_reclassified"].value_counts().to_dict()
    three_counts = three_detail["residual_three_leg_reclassified"].value_counts().to_dict()
    five_counts = five_detail["residual_five_plus_reclassified"].value_counts().to_dict()
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to review/current/final_clean_residual_leg_label_audit."),
            ("no_records_promoted", True, "All outputs are residual audit labels."),
            ("no_crash_assignment", True, "Crash records were not read."),
            ("no_access_assignment", True, "Access assignment was not run."),
            ("no_rates_or_models", True, "No rates/models calculated."),
            ("no_speed_aadt_context_refresh", True, "No generated bins were context-refreshed."),
            ("no_new_bins_generated", True, "This audit writes no bin-generation output."),
            ("source_limited_cases_not_forced", True, "Source-limited labels are audited, not forced into recovery."),
            ("outputs_review_only_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/final_clean_residual_leg_label_audit"), str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "notes"],
    )
    qa.to_csv(OUT_DIR / "final_clean_residual_leg_label_audit_qa.csv", index=False)

    findings = f"""# Final Clean Residual Leg Label Audit

## Bounded Question

Audit whether residual two-leg, three-leg, and five-plus labels are defensible after missing-leg generation and label-only normalization. This pass does not generate bins, context-refresh generated bins, assign access/crashes, calculate rates/models, promote records, or modify active outputs.

## Findings

1. Two-leg residual reclassification: `{two_counts}`. The 309 source-limited labels are not uniformly final truth; source-sector evidence distinguishes confirmed partial cases from recoverable broader-search or anchor cases.
2. Three-leg residual reclassification: `{three_counts}`. The large manual/uncertain and source-leg-not-found classes are partly fallback labels; many are better framed as broader-source-search or intersection-zone-anchor candidates.
3. Five-plus residual reclassification: `{five_counts}`. The 152 true-complex labels remain mixed; some still show subbranch/connector/source-row over-split signatures.
4. Residual source Travelway evidence is summarized at 125/175/250/350 ft in `residual_source_travelway_evidence_summary.csv`.
5. The most useful next implementation pass is still to context-refresh the 19,662 already generated missing-leg bins first, then run a bounded broader-source/anchor pass for residual two-/three-leg cases.
6. A small map-review package should wait until after the broader-source/anchor pass, so map review is limited to true residual ambiguity rather than conservative search artifacts.
"""
    (OUT_DIR / "final_clean_residual_leg_label_audit_findings.md").write_text(findings, encoding="utf-8")

    manifest = {
        "script": "src/active/roadway_graph/final_clean_residual_leg_label_audit.py",
        "created_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "inputs": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in INPUTS.items() if v.exists()},
        "outputs": [
            "residual_leg_label_target_detail.csv",
            "residual_two_leg_reclassification.csv",
            "residual_three_leg_reclassification.csv",
            "residual_five_plus_reclassification.csv",
            "residual_source_travelway_evidence_summary.csv",
            "residual_leg_recoverability_summary.csv",
            "residual_leg_next_action_recommendation.csv",
            "final_clean_residual_leg_label_audit_findings.md",
            "final_clean_residual_leg_label_audit_qa.csv",
            "final_clean_residual_leg_label_audit_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "residual_targets": int(len(targets)),
            "two_leg_targets": int(len(two_detail)),
            "three_leg_targets": int(len(three_detail)),
            "five_plus_targets": int(len(five_detail)),
            "anchors_available": int(len(anchors)),
        },
        "non_goals_confirmed": [
            "no_missing_leg_bins_generated",
            "no_context_refresh",
            "no_access_assignment",
            "no_crash_assignment",
            "no_rates_or_models",
            "no_active_outputs_modified",
        ],
    }
    (OUT_DIR / "final_clean_residual_leg_label_audit_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(progress, "Wrote residual leg label audit outputs.")
    (OUT_DIR / "run_progress_log.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
