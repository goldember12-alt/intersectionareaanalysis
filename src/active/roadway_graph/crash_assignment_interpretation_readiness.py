from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .crash_assignment_qa import (
    OUTPUT_ROOT,
    FEET_PER_METER,
    _build_segment_enrichment,
    _num,
    _read_csv,
    _read_wkt_csv,
    _text,
    _truthy,
    _write_csv,
    _write_json,
    _write_text,
)


READINESS_DIR = Path("review/current/crash_assignment_interpretation_readiness")
QA_DIR = Path("review/current/crash_assignment_qa")
LOW_CONFIDENCE_DISTANCE_FT = 50.0
HIGH_PRIORITY_DISTANCE_FT = 70.0


def _distance_band(distance_ft: float) -> str:
    if pd.isna(distance_ft):
        return "unknown"
    if distance_ft <= 10:
        return "000_to_010ft"
    if distance_ft <= 25:
        return "010_to_025ft"
    if distance_ft <= 50:
        return "025_to_050ft"
    if distance_ft <= 70:
        return "050_to_070ft"
    if distance_ft <= 75:
        return "070_to_075ft"
    if distance_ft <= 100:
        return "075_to_100ft"
    return "over_100ft"


def _count_with_stats(frame: pd.DataFrame, columns: list[str], distance_column: str = "distance_to_bin_ft_num") -> pd.DataFrame:
    present = [column for column in columns if column in frame.columns]
    if frame.empty or not present:
        return pd.DataFrame(columns=[*present, "assigned_crashes"])
    out = (
        frame.groupby(present, dropna=False)
        .agg(
            assigned_crashes=("crash_id", "count"),
            unique_reference_signals=("reference_signal_id", "nunique"),
            unique_segments=("oriented_segment_id", "nunique"),
            min_distance_ft=(distance_column, "min"),
            mean_distance_ft=(distance_column, "mean"),
            median_distance_ft=(distance_column, "median"),
            p95_distance_ft=(distance_column, lambda value: value.quantile(0.95)),
            max_distance_ft=(distance_column, "max"),
        )
        .reset_index()
        .sort_values("assigned_crashes", ascending=False)
    )
    for column in ["min_distance_ft", "mean_distance_ft", "median_distance_ft", "p95_distance_ft", "max_distance_ft"]:
        out[column] = out[column].round(3)
    return out


def _write_geojson(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path, geometry_column: str = "geometry") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty or geometry_column not in frame.columns:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        return
    out = gpd.GeoDataFrame(frame.copy(), geometry=geometry_column)
    out = out.loc[out.geometry.notna() & ~out.geometry.is_empty].copy()
    if out.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    else:
        out.to_file(path, driver="GeoJSON")


def _serious_caveat(row: pd.Series) -> bool:
    categories = str(row.get("endpoint_qa_categories", ""))
    recovery = str(row.get("recovery_status", ""))
    if "unknown_endpoint_junction_issue" in categories:
        return True
    if recovery == "recovered_low_review_only":
        return True
    if recovery.startswith("still_unresolved_unknown"):
        return True
    if str(row.get("roadway_role_class", "")) in {"unknown_review"}:
        return True
    return False


def _caveat_class(row: pd.Series) -> str:
    categories = str(row.get("endpoint_qa_categories", ""))
    recovery = str(row.get("recovery_status", ""))
    source = str(row.get("bounded_scaffold_source", ""))
    requires_review = str(row.get("requires_manual_review", "")).upper() == "TRUE"

    if "unknown_endpoint_junction_issue" in categories:
        return "review_required_unknown_endpoint_junction"
    if recovery == "recovered_low_review_only":
        return "high_risk_low_confidence_divided_recovery"
    if recovery.startswith("still_unresolved_unknown"):
        return "review_required_unresolved_divided_geometry"
    if "signal_association_tolerance" in source:
        return "provisional_signal_association_tolerance"
    if "valid_dead_end_or_one_sided_edge" in categories:
        return "caveated_valid_dead_end_or_one_sided_boundary"
    if "opposite_anchor_outside_true_reference_scope" in categories or source == "anchor_relaxation":
        return "method_allowed_anchor_relaxation"
    if requires_review:
        return "review_required_manual_or_qa_status"
    if str(row.get("geometry_review_caveat", "")).upper() == "TRUE":
        return "other_geometry_caveat"
    return "no_geometry_caveat"


def _confidence_tier(row: pd.Series) -> str:
    distance = row.get("distance_to_bin_ft_num")
    caveat = str(row.get("geometry_caveat_class", ""))
    source = str(row.get("bounded_scaffold_source", ""))
    serious = bool(row.get("serious_geometry_caveat", False))

    if pd.isna(distance):
        return "review_required_unknown_distance"
    if distance > HIGH_PRIORITY_DISTANCE_FT:
        return "high_priority_review_distance_over_70ft"
    if serious:
        return "review_required_serious_geometry_caveat"
    if caveat == "high_risk_low_confidence_divided_recovery":
        return "review_required_serious_geometry_caveat"
    if "signal_association_tolerance" in source:
        return "provisional_signal_association_review"
    if distance > LOW_CONFIDENCE_DISTANCE_FT:
        return "low_confidence_review_distance_50_to_70ft"
    if distance > 25:
        return "medium_confidence_spatial_assignment"
    if caveat in {"method_allowed_anchor_relaxation", "caveated_valid_dead_end_or_one_sided_boundary", "other_geometry_caveat"}:
        return "medium_confidence_caveated_spatial_assignment"
    return "high_confidence_spatial_assignment"


def _directional_eligibility(row: pd.Series) -> tuple[str, str]:
    tier = str(row.get("assignment_confidence_tier", ""))
    directionality = str(row.get("roadway_directionality_type", ""))
    orientation = str(row.get("orientation_record_type", ""))
    caveat = str(row.get("geometry_caveat_class", ""))
    source = str(row.get("bounded_scaffold_source", ""))

    if tier.startswith("high_priority") or tier.startswith("review_required") or tier.startswith("provisional"):
        return "not_ready_review_required", "assignment confidence or geometry caveat requires review first"
    if directionality == "undivided":
        return "not_ready_requires_event_direction_source", "undivided centerline assignment still needs validated event direction source"
    if orientation in {"review_only"}:
        return "not_ready_review_only_geometry", "review-only orientation cannot support directional interpretation yet"
    if "signal_association_tolerance" in source:
        return "not_ready_signal_association_spot_check", "signal-association-tolerance scaffold must be spot checked first"
    if caveat != "no_geometry_caveat" and caveat != "method_allowed_anchor_relaxation":
        return "not_ready_caveated_geometry", "geometry caveat is not automatically acceptable for directional interpretation"
    return "spatially_plausible_not_directional_ready", "spatial assignment appears plausible, but upstream/downstream still requires validated direction method"


def _priority_score(row: pd.Series) -> int:
    score = 0
    distance = row.get("distance_to_bin_ft_num", 0)
    if pd.notna(distance):
        if distance > 70:
            score += 50
        elif distance > 50:
            score += 30
        elif distance > 25:
            score += 10
    if bool(row.get("serious_geometry_caveat", False)):
        score += 40
    if str(row.get("assignment_confidence_tier", "")).startswith("provisional"):
        score += 25
    if str(row.get("geometry_caveat_class", "")) == "caveated_valid_dead_end_or_one_sided_boundary":
        score += 10
    return score


def _findings_markdown(summary: dict[str, object]) -> str:
    return f"""# Crash Assignment Interpretation-Readiness Findings

**Status:** Read-only interpretation-readiness QA over the current roadway_graph crash assignment.

## Bounded Question

This pass classifies existing spatial crash assignments and unresolved-near-scaffold rows for review readiness. It does not change the roadway scaffold, crash assignment logic, geometric direction outputs, or upstream/downstream status.

## Key Counts

- Assigned crashes reviewed: {summary["assigned_crashes"]}
- Unresolved-near-scaffold rows reviewed: {summary["unresolved_near_scaffold_rows"]}
- High-confidence spatial assignments: {summary["high_confidence_spatial_assignment"]}
- Medium/caveated spatial assignments: {summary["medium_or_caveated_spatial_assignment"]}
- Low-confidence or review assignments: {summary["low_or_review_assignment"]}
- High-priority assigned-crash review rows: {summary["high_priority_assigned_review_rows"]}
- Recovered signal-association assigned crashes: {summary["signal_association_assigned_crashes"]}

## Interpretation

The current assignment layer is useful for spatial QA and review prioritization. It is not ready for upstream/downstream interpretation. Before directional interpretation begins, high-priority distance rows, serious geometry caveats, low-confidence divided recovery rows, and signal-association-tolerance cases need spot checks or explicit acceptance rules. Undivided centerline assignments also need a validated event-direction source before they can become upstream/downstream records.
"""


def build_interpretation_readiness(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    qa = output_root / QA_DIR
    out_dir = output_root / READINESS_DIR
    geojson_dir = out_dir / "geojson"

    assigned = _read_wkt_csv(tables / "crash_oriented_segment_bin_assignment.csv")
    unresolved = _read_wkt_csv(tables / "crash_oriented_segment_assignment_unresolved.csv", crs=assigned.crs)
    segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_crash_ready.csv", crs=assigned.crs)
    segment_enrichment, eligibility = _build_segment_enrichment(tables, review)
    unresolved_near = _read_csv(qa / "unresolved_crash_near_scaffold_review_queue.csv")
    recovered_signal_summary = _read_csv(qa / "recovered_scaffold_assigned_crash_summary.csv")

    assigned_base = pd.DataFrame(assigned.drop(columns=["geometry"], errors="ignore")).merge(
        segment_enrichment.drop(columns=["geometry"], errors="ignore"),
        on="oriented_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    assigned_geom = assigned[["crash_id", "geometry"]].copy() if "crash_id" in assigned.columns else gpd.GeoDataFrame(columns=["crash_id", "geometry"], geometry="geometry", crs=assigned.crs)
    assigned_base["distance_to_bin_ft_num"] = _num(assigned_base, "distance_to_bin_ft")
    assigned_base["assignment_distance_readiness_band"] = assigned_base["distance_to_bin_ft_num"].map(_distance_band)
    assigned_base["geometry_caveat_class"] = assigned_base.apply(_caveat_class, axis=1)
    assigned_base["serious_geometry_caveat"] = assigned_base.apply(_serious_caveat, axis=1)
    assigned_base["assignment_confidence_tier"] = assigned_base.apply(_confidence_tier, axis=1)
    assigned_base["review_priority_score"] = assigned_base.apply(_priority_score, axis=1)
    directional = assigned_base.apply(_directional_eligibility, axis=1, result_type="expand")
    assigned_base["directional_preliminary_eligibility"] = directional[0]
    assigned_base["directional_preliminary_reason"] = directional[1]

    assignment_confidence = _count_with_stats(
        assigned_base,
        ["assignment_confidence_tier", "assignment_distance_readiness_band"],
    )
    _write_csv(assignment_confidence, out_dir / "assignment_confidence_tiers.csv")

    caveat_strat = _count_with_stats(
        assigned_base,
        ["geometry_caveat_class", "endpoint_qa_categories", "recovery_status", "bounded_scaffold_source"],
    )
    _write_csv(caveat_strat, out_dir / "geometry_caveat_stratification.csv")
    _write_csv(_count_with_stats(assigned_base, ["geometry_caveat_class"]), out_dir / "assigned_crashes_by_caveat_class.csv")
    _write_csv(
        _count_with_stats(assigned_base, ["assignment_confidence_tier", "bounded_scaffold_source", "recovery_status", "promotion_recommendation"]),
        out_dir / "assigned_crashes_by_confidence_and_recovery_source.csv",
    )

    if not unresolved_near.empty:
        unresolved_near["nearest_scaffold_distance_ft_num"] = _num(unresolved_near, "nearest_scaffold_distance_ft")
        unresolved_near["nearest_scaffold_distance_band"] = unresolved_near["nearest_scaffold_distance_ft_num"].map(_distance_band)
        unresolved_near["unresolved_review_priority"] = unresolved_near["nearest_scaffold_distance_ft_num"].map(
            lambda distance: "highest_near_miss_0_to_25ft"
            if pd.notna(distance) and distance <= 25
            else "high_near_miss_25_to_50ft"
            if pd.notna(distance) and distance <= 50
            else "medium_near_miss_50_to_75ft"
            if pd.notna(distance) and distance <= 75
            else "lower_near_miss_75_to_100ft"
        )
    _write_csv(
        unresolved_near.groupby(["unresolved_reason", "unresolved_review_priority"], dropna=False)
        .size()
        .reset_index(name="unresolved_crashes")
        .sort_values("unresolved_crashes", ascending=False)
        if not unresolved_near.empty
        else pd.DataFrame(columns=["unresolved_reason", "unresolved_review_priority", "unresolved_crashes"]),
        out_dir / "unresolved_near_scaffold_reason_summary.csv",
    )
    _write_csv(
        unresolved_near.groupby(["nearest_scaffold_distance_band", "roadway_directionality_type", "orientation_record_type"], dropna=False)
        .size()
        .reset_index(name="unresolved_crashes")
        .sort_values(["nearest_scaffold_distance_band", "unresolved_crashes"], ascending=[True, False])
        if not unresolved_near.empty
        else pd.DataFrame(columns=["nearest_scaffold_distance_band", "roadway_directionality_type", "orientation_record_type", "unresolved_crashes"]),
        out_dir / "unresolved_near_scaffold_by_distance_band.csv",
    )
    unresolved_ranked = unresolved_near.sort_values(["nearest_scaffold_distance_ft_num", "crash_id"]).copy() if not unresolved_near.empty else unresolved_near
    _write_csv(unresolved_ranked, out_dir / "unresolved_near_scaffold_ranked_review_queue.csv")

    signal_assoc = assigned_base.loc[_text(assigned_base, "bounded_scaffold_source").str.contains("signal_association_tolerance", na=False)].copy()
    signal_queue = pd.DataFrame()
    if not recovered_signal_summary.empty:
        recovered = recovered_signal_summary.copy()
        recovered["assigned_crashes"] = _num(recovered, "assigned_crashes").fillna(0).astype(int)
        recovered["p95_distance_ft"] = _num(recovered, "p95_distance_ft")
        recovered["geometry_review_caveat_segments"] = _num(recovered, "geometry_review_caveat_segments").fillna(0).astype(int)
        recovered["spot_check_priority_score"] = (
            recovered["assigned_crashes"]
            + recovered["geometry_review_caveat_segments"].mul(20)
            + recovered["p95_distance_ft"].fillna(0).gt(50).astype(int).mul(30)
            + recovered["p95_distance_ft"].fillna(0).gt(70).astype(int).mul(40)
        )
        recovered["spot_check_priority"] = recovered["spot_check_priority_score"].map(
            lambda score: "high" if score >= 100 else "medium" if score >= 40 else "lower"
        )
        signal_queue = recovered.sort_values(["spot_check_priority_score", "assigned_crashes"], ascending=[False, False])
    _write_csv(signal_queue, out_dir / "signal_association_recovered_case_review_queue.csv")

    eligibility_table = _count_with_stats(
        assigned_base,
        ["directional_preliminary_eligibility", "directional_preliminary_reason", "assignment_confidence_tier", "roadway_directionality_type", "orientation_record_type"],
    )
    _write_csv(eligibility_table, out_dir / "directional_interpretation_preliminary_eligibility.csv")

    assigned_with_geom = gpd.GeoDataFrame(
        assigned_base.merge(assigned_geom, on="crash_id", how="left"),
        geometry="geometry",
        crs=assigned.crs,
    )
    low_confidence = assigned_with_geom.loc[
        _text(assigned_with_geom, "assignment_confidence_tier").str.contains("low|review|provisional", regex=True, na=False)
    ].copy()
    _write_geojson(low_confidence, geojson_dir / "low_confidence_assigned_crashes.geojson")

    unresolved_with_geom = unresolved_ranked.merge(
        pd.DataFrame(unresolved[["crash_id", "geometry"]].copy()),
        on="crash_id",
        how="left",
    ) if not unresolved_ranked.empty and "crash_id" in unresolved.columns else pd.DataFrame()
    _write_geojson(unresolved_with_geom.head(1000), geojson_dir / "unresolved_near_scaffold_priority_review.geojson")

    signal_review_geo = _read_wkt_csv(out_dir / "signal_association_recovered_case_review_queue.csv", crs=assigned.crs)
    _write_geojson(signal_review_geo, geojson_dir / "signal_association_recovered_case_review.geojson")

    segment_flags = (
        assigned_base.groupby("oriented_segment_id", dropna=False)
        .agg(
            assigned_crashes=("crash_id", "count"),
            high_priority_review_rows=("assignment_confidence_tier", lambda values: int(values.astype(str).str.startswith("high_priority").sum())),
            review_required_rows=("assignment_confidence_tier", lambda values: int(values.astype(str).str.contains("review_required|provisional|low_confidence", regex=True).sum())),
            directional_ready_rows=("directional_preliminary_eligibility", lambda values: int(values.astype(str).eq("spatially_plausible_not_directional_ready").sum())),
        )
        .reset_index()
    )
    directional_ineligible_segments = segments.merge(segment_flags, on="oriented_segment_id", how="inner")
    directional_ineligible_segments = directional_ineligible_segments.loc[
        _num(directional_ineligible_segments, "review_required_rows").gt(0)
        | _num(directional_ineligible_segments, "high_priority_review_rows").gt(0)
    ].copy()
    _write_geojson(directional_ineligible_segments, geojson_dir / "directional_ineligible_assigned_segments.geojson")

    tier_counts = assigned_base["assignment_confidence_tier"].value_counts(dropna=False).to_dict()
    caveat_counts = assigned_base["geometry_caveat_class"].value_counts(dropna=False).to_dict()
    summary = {
        "assigned_crashes": int(len(assigned_base)),
        "unresolved_near_scaffold_rows": int(len(unresolved_near)),
        "high_confidence_spatial_assignment": int(tier_counts.get("high_confidence_spatial_assignment", 0)),
        "medium_or_caveated_spatial_assignment": int(
            tier_counts.get("medium_confidence_spatial_assignment", 0)
            + tier_counts.get("medium_confidence_caveated_spatial_assignment", 0)
        ),
        "low_or_review_assignment": int(len(assigned_base) - tier_counts.get("high_confidence_spatial_assignment", 0) - tier_counts.get("medium_confidence_spatial_assignment", 0) - tier_counts.get("medium_confidence_caveated_spatial_assignment", 0)),
        "high_priority_assigned_review_rows": int(_text(assigned_base, "assignment_confidence_tier").str.startswith("high_priority").sum()),
        "signal_association_assigned_crashes": int(len(signal_assoc)),
        "assignment_confidence_tier_counts": {str(k): int(v) for k, v in tier_counts.items()},
        "geometry_caveat_class_counts": {str(k): int(v) for k, v in caveat_counts.items()},
        "raw_crash_data_read": False,
        "crash_direction_fields_used": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
    }
    _write_text(_findings_markdown(summary), out_dir / "crash_assignment_interpretation_readiness_findings.md")

    outputs = [
        out_dir / "assignment_confidence_tiers.csv",
        out_dir / "geometry_caveat_stratification.csv",
        out_dir / "assigned_crashes_by_caveat_class.csv",
        out_dir / "assigned_crashes_by_confidence_and_recovery_source.csv",
        out_dir / "unresolved_near_scaffold_reason_summary.csv",
        out_dir / "unresolved_near_scaffold_by_distance_band.csv",
        out_dir / "unresolved_near_scaffold_ranked_review_queue.csv",
        out_dir / "signal_association_recovered_case_review_queue.csv",
        out_dir / "directional_interpretation_preliminary_eligibility.csv",
        out_dir / "crash_assignment_interpretation_readiness_findings.md",
        out_dir / "crash_assignment_interpretation_readiness_manifest.json",
        geojson_dir / "low_confidence_assigned_crashes.geojson",
        geojson_dir / "unresolved_near_scaffold_priority_review.geojson",
        geojson_dir / "signal_association_recovered_case_review.geojson",
        geojson_dir / "directional_ineligible_assigned_segments.geojson",
    ]
    inputs = [
        tables / "crash_oriented_segment_bin_assignment.csv",
        tables / "crash_oriented_segment_assignment_unresolved.csv",
        tables / "signal_oriented_roadway_segments_crash_ready.csv",
        tables / "signal_oriented_segment_bins_50ft_crash_ready.csv",
        tables / "signal_step5_eligibility.csv",
        tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv",
        tables / "signal_oriented_roadway_segments_role_enriched.csv",
        review / "endpoint_junction_qa" / "endpoint_junction_qa_segment_flags.csv",
        qa / "unresolved_crash_near_scaffold_review_queue.csv",
        qa / "recovered_scaffold_assigned_crash_summary.csv",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Interpretation-readiness classification over existing spatial crash assignment and graph QA caveats.",
        "read_only": True,
        "raw_crash_data_read": False,
        "crash_direction_fields_used": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
        "upstream_downstream_inferred": False,
        "input_files": [str(path) for path in inputs if path.exists()],
        "output_files": [str(path) for path in outputs],
        "classification_thresholds": {
            "medium_confidence_distance_upper_ft": 50,
            "low_confidence_distance_lower_ft": 50,
            "high_priority_distance_lower_ft": 70,
        },
        "summary": summary,
    }
    _write_json(manifest, out_dir / "crash_assignment_interpretation_readiness_manifest.json")
    return {path.stem: str(path) for path in outputs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify current roadway_graph crash assignment for interpretation readiness without changing assignment results.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_interpretation_readiness(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
