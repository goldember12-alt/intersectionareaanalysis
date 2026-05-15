from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
QA_REVIEW_DIR = Path("review/current/crash_assignment_qa")
FEET_PER_METER = 3.280839895
FAR_ASSIGNED_DISTANCE_FT = 50.0
SUSPICIOUS_ASSIGNED_DISTANCE_FT = 70.0
UNRESOLVED_NEAR_SCAFFOLD_FT = 100.0
UNRESOLVED_NEAREST_SAMPLE_SIZE = 1000


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_wkt_csv(path: Path, crs=None) -> gpd.GeoDataFrame:
    frame = _read_csv(path)
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=[], crs=crs)
    if "geometry" not in frame.columns:
        return gpd.GeoDataFrame(frame, crs=crs)
    frame["geometry"] = frame["geometry"].map(lambda value: wkt.loads(value) if str(value).strip() else None)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=crs)


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns:
        out["geometry"] = out["geometry"].map(lambda geom: geom.wkt if hasattr(geom, "wkt") else str(geom or ""))
    out.to_csv(path, index=False)


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _truthy(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.upper().isin({"TRUE", "1", "YES", "Y"})


def _group_count(frame: pd.DataFrame, columns: list[str], count_name: str = "assigned_crashes") -> pd.DataFrame:
    present = [column for column in columns if column in frame.columns]
    if frame.empty or not present:
        return pd.DataFrame(columns=[*present, count_name])
    return frame.groupby(present, dropna=False).size().reset_index(name=count_name).sort_values(count_name, ascending=False)


def _distance_stats(frame: pd.DataFrame, group_columns: list[str], distance_column: str = "distance_to_bin_ft") -> pd.DataFrame:
    present = [column for column in group_columns if column in frame.columns]
    if frame.empty or not present or distance_column not in frame.columns:
        return pd.DataFrame(columns=[*present, "assigned_crashes"])
    out = (
        frame.assign(_distance=_num(frame, distance_column))
        .groupby(present, dropna=False)["_distance"]
        .agg(
            assigned_crashes="count",
            min_distance_ft="min",
            mean_distance_ft="mean",
            median_distance_ft="median",
            p95_distance_ft=lambda value: value.quantile(0.95),
            max_distance_ft="max",
        )
        .reset_index()
        .sort_values("assigned_crashes", ascending=False)
    )
    for column in ["min_distance_ft", "mean_distance_ft", "median_distance_ft", "p95_distance_ft", "max_distance_ft"]:
        out[column] = out[column].round(3)
    return out


def _safe_percent(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 3)


def _quantile_rows(values: pd.Series) -> list[dict[str, object]]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return []
    rows: list[dict[str, object]] = []
    for label, quantile in [
        ("min", 0.0),
        ("p05", 0.05),
        ("p25", 0.25),
        ("median", 0.5),
        ("p75", 0.75),
        ("p95", 0.95),
        ("p99", 0.99),
        ("max", 1.0),
    ]:
        rows.append({"distribution": "assigned_distance_to_bin_ft", "statistic": label, "value": round(float(numeric.quantile(quantile)), 3)})
    return rows


def _build_segment_enrichment(tables: Path, review: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    segments = _read_csv(tables / "signal_oriented_roadway_segments_crash_ready.csv")
    recovery = _read_csv(tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv")
    roles = _read_csv(tables / "signal_oriented_roadway_segments_role_enriched.csv")
    eligibility = _read_csv(tables / "signal_step5_eligibility.csv")
    endpoint_flags = _read_csv(review / "endpoint_junction_qa" / "endpoint_junction_qa_segment_flags.csv")

    segment_key = "oriented_segment_id"
    enrichment = segments.copy()
    for optional, columns in [
        (
            recovery,
            [
                "oriented_segment_id",
                "recovery_status",
                "promotion_recommendation",
                "recovery_confidence",
                "recovery_method",
                "recovery_reason",
                "roadway_role_class",
                "divided_pairing_status",
                "pairing_problem_reason",
                "geometric_direction_status",
                "geometric_direction_problem_reason",
            ],
        ),
        (
            roles,
            [
                "oriented_segment_id",
                "roadway_role_class",
                "roadway_role_reason",
                "roadway_role_confidence",
                "divided_pairing_status",
            ],
        ),
    ]:
        if optional.empty or segment_key not in optional.columns:
            continue
        present = [column for column in columns if column in optional.columns]
        enrichment = enrichment.merge(optional[present].drop_duplicates(segment_key), on=segment_key, how="left", suffixes=("", "_optional"))
        for column in [c for c in present if c != segment_key]:
            optional_col = f"{column}_optional"
            if optional_col in enrichment.columns:
                enrichment[column] = enrichment[column].where(_text(enrichment, column).ne(""), enrichment[optional_col])
                enrichment = enrichment.drop(columns=[optional_col])

    offset_signals = set()
    if not eligibility.empty and {"signal_id", "signal_offset_relaxation_applied"}.issubset(eligibility.columns):
        offset_signals = set(
            eligibility.loc[_truthy(eligibility["signal_offset_relaxation_applied"]), "signal_id"].astype(str)
        )

    both_true = _truthy(_text(enrichment, "both_endpoint_signals_true"))
    enrichment["anchor_relaxation_segment"] = (~both_true).map({True: "TRUE", False: "FALSE"})
    enrichment["signal_association_tolerance_segment"] = _text(enrichment, "reference_signal_id").isin(offset_signals).map({True: "TRUE", False: "FALSE"})

    def source_flag(row: pd.Series) -> str:
        anchor = str(row.get("anchor_relaxation_segment", "")).upper() == "TRUE"
        signal_offset = str(row.get("signal_association_tolerance_segment", "")).upper() == "TRUE"
        if anchor and signal_offset:
            return "anchor_relaxation_and_signal_association_tolerance"
        if signal_offset:
            return "signal_association_tolerance"
        if anchor:
            return "anchor_relaxation"
        return "baseline_true_to_true_signal_boundary"

    enrichment["bounded_scaffold_source"] = enrichment.apply(source_flag, axis=1)

    flags_by_segment = pd.DataFrame(columns=["oriented_segment_id", "endpoint_qa_flag_count", "endpoint_qa_categories"])
    if not endpoint_flags.empty and "oriented_segment_id" in endpoint_flags.columns:
        flags_by_segment = (
            endpoint_flags.loc[_text(endpoint_flags, "oriented_segment_id").ne("")]
            .groupby("oriented_segment_id", dropna=False)
            .agg(
                endpoint_qa_flag_count=("diagnostic_category", "count"),
                endpoint_qa_categories=("diagnostic_category", lambda values: "|".join(sorted(set(str(value) for value in values if str(value))))),
            )
            .reset_index()
        )
        enrichment = enrichment.merge(flags_by_segment, on="oriented_segment_id", how="left")
    enrichment["endpoint_qa_flag_count"] = _num(enrichment, "endpoint_qa_flag_count").fillna(0).astype(int)
    enrichment["endpoint_qa_categories"] = _text(enrichment, "endpoint_qa_categories")

    review_status = _truthy(_text(enrichment, "requires_manual_review"))
    qa_review = _text(enrichment, "qa_status").str.contains("review", case=False, na=False)
    recovery_review = _text(enrichment, "recovery_status").str.startswith("still_unresolved") | _text(enrichment, "recovery_status").eq("recovered_low_review_only")
    endpoint_review = enrichment["endpoint_qa_flag_count"].gt(0)
    enrichment["geometry_review_caveat"] = (review_status | qa_review | recovery_review | endpoint_review).map({True: "TRUE", False: "FALSE"})

    return enrichment, eligibility


def _nearest_unresolved_to_scaffold(
    unresolved: gpd.GeoDataFrame,
    bins: gpd.GeoDataFrame,
    *,
    max_distance_ft: float,
) -> pd.DataFrame:
    if unresolved.empty or bins.empty:
        return pd.DataFrame()
    max_distance = max_distance_ft / FEET_PER_METER
    left = unresolved[["crash_id", "unresolved_reason", "nearest_search_radius_ft", "geometry"]].copy()
    right_columns = [
        column
        for column in [
            "bin_id",
            "oriented_segment_id",
            "reference_signal_id",
            "roadway_directionality_type",
            "orientation_record_type",
            "geometry",
        ]
        if column in bins.columns
    ]
    nearest = gpd.sjoin_nearest(left, bins[right_columns], how="inner", max_distance=max_distance, distance_col="nearest_scaffold_m")
    nearest = nearest.drop(columns=["index_right"], errors="ignore")
    nearest["nearest_scaffold_distance_ft"] = _num(nearest, "nearest_scaffold_m") * FEET_PER_METER
    nearest = nearest.sort_values(["nearest_scaffold_distance_ft", "crash_id"]).copy()
    return pd.DataFrame(nearest.drop(columns=["geometry"], errors="ignore"))


def _methodology_markdown(summary: dict[str, object]) -> str:
    return f"""# Crash Assignment QA Methodology Findings

**Status:** Review output for the current roadway_graph / Step 5 crash-ready crash assignment.

## Bounded Question

This QA evaluates the completed spatial crash-to-bin assignment. It does not change the roadway scaffold, alter crash assignment logic, repair geometry, promote review-only cases, infer vehicle direction, or classify crashes as upstream/downstream.

## Inputs Read

- `work/output/roadway_graph/tables/current/crash_oriented_segment_bin_assignment.csv`
- `work/output/roadway_graph/tables/current/crash_oriented_segment_assignment_unresolved.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_step5_eligibility.csv`
- optional current segment enrichment and endpoint QA review outputs when present

## Findings

- Assigned crashes: {summary["assigned_crashes"]}
- Unresolved crashes: {summary["unresolved_crashes"]}
- Assignment rate: {summary["assignment_rate_percent"]}%
- Median assigned distance to bin: {summary["median_assigned_distance_ft"]} ft
- 95th percentile assigned distance to bin: {summary["p95_assigned_distance_ft"]} ft
- Max assigned distance to bin: {summary["max_assigned_distance_ft"]} ft
- Assigned crashes on anchor-relaxation segments: {summary["assigned_on_anchor_relaxation_segments"]}
- Assigned crashes on signal-association-tolerance segments: {summary["assigned_on_signal_association_tolerance_segments"]}
- Assigned crashes on geometry review caveat segments: {summary["assigned_on_geometry_review_caveat_segments"]}
- Unresolved crashes within {UNRESOLVED_NEAR_SCAFFOLD_FT:g} ft of crash-ready bins in the QA nearest-neighbor screen: {summary["unresolved_near_scaffold_rows"]}

## Interpretation

The assignment is suitable for spatial QA and descriptive coverage review. It is not ready for directional or upstream/downstream interpretation because event direction remains unresolved and the QA still finds assigned crashes on scaffold rows that carry review caveats.
"""


def build_crash_assignment_qa(
    *,
    output_root: Path = OUTPUT_ROOT,
    far_distance_ft: float = FAR_ASSIGNED_DISTANCE_FT,
    suspicious_distance_ft: float = SUSPICIOUS_ASSIGNED_DISTANCE_FT,
    unresolved_near_scaffold_ft: float = UNRESOLVED_NEAR_SCAFFOLD_FT,
    unresolved_sample_size: int = UNRESOLVED_NEAREST_SAMPLE_SIZE,
) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    qa_dir = output_root / QA_REVIEW_DIR

    assigned = _read_wkt_csv(tables / "crash_oriented_segment_bin_assignment.csv")
    unresolved = _read_wkt_csv(tables / "crash_oriented_segment_assignment_unresolved.csv", crs=assigned.crs)
    segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_crash_ready.csv", crs=assigned.crs)
    bins = _read_wkt_csv(tables / "signal_oriented_segment_bins_50ft_crash_ready.csv", crs=assigned.crs)
    segment_enrichment, eligibility = _build_segment_enrichment(tables, review)

    enriched_assigned = pd.DataFrame(assigned.drop(columns=["geometry"], errors="ignore")).merge(
        segment_enrichment.drop(columns=["geometry"], errors="ignore"),
        on="oriented_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    enriched_assigned["distance_to_bin_ft_num"] = _num(enriched_assigned, "distance_to_bin_ft")
    enriched_assigned["far_distance_review_flag"] = enriched_assigned["distance_to_bin_ft_num"].gt(far_distance_ft).map({True: "TRUE", False: "FALSE"})
    enriched_assigned["suspicious_large_distance_flag"] = enriched_assigned["distance_to_bin_ft_num"].gt(suspicious_distance_ft).map({True: "TRUE", False: "FALSE"})

    assigned_count = len(assigned)
    unresolved_count = len(unresolved)
    total_count = assigned_count + unresolved_count
    assigned_distance = enriched_assigned["distance_to_bin_ft_num"].dropna()

    unresolved_nearest = _nearest_unresolved_to_scaffold(unresolved, bins, max_distance_ft=unresolved_near_scaffold_ft)
    unresolved_near_queue = unresolved_nearest.sort_values(["nearest_scaffold_distance_ft", "crash_id"]).copy()
    unresolved_sample = unresolved_nearest.head(unresolved_sample_size).copy()

    assigned_far = enriched_assigned.loc[enriched_assigned["distance_to_bin_ft_num"].gt(far_distance_ft)].copy()
    assigned_far = assigned_far.sort_values(["distance_to_bin_ft_num", "crash_id"], ascending=[False, True])

    anchor_assigned = int(_truthy(_text(enriched_assigned, "anchor_relaxation_segment")).sum())
    signal_offset_assigned = int(_truthy(_text(enriched_assigned, "signal_association_tolerance_segment")).sum())
    caveat_assigned = int(_truthy(_text(enriched_assigned, "geometry_review_caveat")).sum())
    summary = {
        "total_crashes_considered": total_count,
        "assigned_crashes": assigned_count,
        "unresolved_crashes": unresolved_count,
        "assignment_rate_percent": _safe_percent(assigned_count, total_count),
        "median_assigned_distance_ft": round(float(assigned_distance.median()), 3) if not assigned_distance.empty else "",
        "p95_assigned_distance_ft": round(float(assigned_distance.quantile(0.95)), 3) if not assigned_distance.empty else "",
        "max_assigned_distance_ft": round(float(assigned_distance.max()), 3) if not assigned_distance.empty else "",
        "assigned_far_distance_review_rows": int(len(assigned_far)),
        "assigned_suspicious_large_distance_rows": int(enriched_assigned["distance_to_bin_ft_num"].gt(suspicious_distance_ft).sum()),
        "assigned_on_anchor_relaxation_segments": anchor_assigned,
        "assigned_on_signal_association_tolerance_segments": signal_offset_assigned,
        "assigned_on_geometry_review_caveat_segments": caveat_assigned,
        "unresolved_near_scaffold_rows": int(len(unresolved_nearest)),
        "crash_data_read": True,
        "raw_normalized_crash_file_read": False,
        "crash_direction_fields_used": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
    }

    summary_rows = [{"metric": key, "value": value} for key, value in summary.items()]
    _write_csv(pd.DataFrame(summary_rows), qa_dir / "crash_assignment_qa_summary.csv")

    distance_rows = _quantile_rows(enriched_assigned["distance_to_bin_ft_num"])
    if "distance_band" in enriched_assigned.columns:
        band_counts = _group_count(enriched_assigned, ["distance_band"])
        distance_rows.extend(
            {"distribution": "assigned_distance_band", "statistic": row["distance_band"], "value": row["assigned_crashes"]}
            for _, row in band_counts.iterrows()
        )
    _write_csv(pd.DataFrame(distance_rows), qa_dir / "crash_assignment_distance_distribution.csv")

    by_signal = _distance_stats(enriched_assigned, ["reference_signal_id"])
    if not by_signal.empty:
        signal_extra = (
            enriched_assigned.groupby("reference_signal_id", dropna=False)
            .agg(
                assigned_segments=("oriented_segment_id", "nunique"),
                assigned_bins=("bin_id", "nunique"),
                far_distance_review_rows=("far_distance_review_flag", lambda values: int((values == "TRUE").sum())),
                anchor_relaxation_assigned=("anchor_relaxation_segment", lambda values: int((values.astype(str).str.upper() == "TRUE").sum())),
                signal_association_tolerance_assigned=("signal_association_tolerance_segment", lambda values: int((values.astype(str).str.upper() == "TRUE").sum())),
                geometry_review_caveat_assigned=("geometry_review_caveat", lambda values: int((values.astype(str).str.upper() == "TRUE").sum())),
            )
            .reset_index()
        )
        by_signal = by_signal.merge(signal_extra, on="reference_signal_id", how="left")
        by_signal = by_signal.sort_values(["assigned_crashes", "p95_distance_ft"], ascending=[False, False])
    _write_csv(by_signal, qa_dir / "crash_assignment_by_reference_signal.csv")

    flag_groups = []
    for columns in [
        ["roadway_directionality_type", "orientation_record_type"],
        ["bounded_scaffold_source"],
        ["opposite_anchor_type", "opposite_anchor_step5_status"],
        ["qa_status", "requires_manual_review"],
        ["roadway_role_class"],
        ["divided_pairing_status"],
        ["recovery_status", "promotion_recommendation"],
        ["geometry_review_caveat", "endpoint_qa_categories"],
        ["distance_band", "far_distance_review_flag", "suspicious_large_distance_flag"],
    ]:
        group = _distance_stats(enriched_assigned, columns)
        if not group.empty:
            group.insert(0, "grouping", "+".join(columns))
            flag_groups.append(group)
    by_flag = pd.concat(flag_groups, ignore_index=True, sort=False) if flag_groups else pd.DataFrame()
    _write_csv(by_flag, qa_dir / "crash_assignment_by_segment_or_bin_flag.csv")

    recovery_source = _distance_stats(enriched_assigned, ["bounded_scaffold_source", "recovery_status", "promotion_recommendation"])
    _write_csv(recovery_source, qa_dir / "crash_assignment_by_recovery_source.csv")

    _write_csv(unresolved_sample, qa_dir / "unresolved_crash_nearest_scaffold_distance_sample.csv")
    _write_csv(unresolved_near_queue, qa_dir / "unresolved_crash_near_scaffold_review_queue.csv")
    far_columns = [
        "crash_id",
        "oriented_segment_id",
        "bin_id",
        "reference_signal_id",
        "distance_to_bin_ft",
        "distance_band",
        "bounded_scaffold_source",
        "roadway_directionality_type",
        "orientation_record_type",
        "opposite_anchor_type",
        "opposite_anchor_step5_status",
        "qa_status",
        "requires_manual_review",
        "geometry_review_caveat",
        "endpoint_qa_categories",
        "recovery_status",
        "promotion_recommendation",
        "DOCUMENT_NBR",
        "CRASH_YEAR",
        "RTE_NM",
    ]
    _write_csv(assigned_far[[column for column in far_columns if column in assigned_far.columns]], qa_dir / "assigned_crash_far_distance_review_queue.csv")

    offset_signals = pd.DataFrame()
    if not eligibility.empty and "signal_offset_relaxation_applied" in eligibility.columns:
        offset_signals = eligibility.loc[_truthy(eligibility["signal_offset_relaxation_applied"])].copy()
    recovered_summary = pd.DataFrame()
    if not offset_signals.empty:
        signal_counts = _distance_stats(enriched_assigned, ["reference_signal_id"])
        signal_counts = signal_counts.rename(columns={"reference_signal_id": "signal_id"})
        seg_counts = (
            segment_enrichment.loc[_truthy(_text(segment_enrichment, "signal_association_tolerance_segment"))]
            .groupby("reference_signal_id", dropna=False)
            .agg(
                crash_ready_segments=("oriented_segment_id", "nunique"),
                anchor_relaxation_segments=("anchor_relaxation_segment", lambda values: int((values.astype(str).str.upper() == "TRUE").sum())),
                geometry_review_caveat_segments=("geometry_review_caveat", lambda values: int((values.astype(str).str.upper() == "TRUE").sum())),
            )
            .reset_index()
            .rename(columns={"reference_signal_id": "signal_id"})
        )
        recovered_summary = offset_signals.merge(seg_counts, on="signal_id", how="left").merge(signal_counts, on="signal_id", how="left")
        for column in ["crash_ready_segments", "anchor_relaxation_segments", "geometry_review_caveat_segments", "assigned_crashes"]:
            if column in recovered_summary.columns:
                recovered_summary[column] = _num(recovered_summary, column).fillna(0).astype(int)
        recovered_summary = recovered_summary.sort_values(["assigned_crashes", "signal_id"], ascending=[False, True])
    _write_csv(recovered_summary, qa_dir / "recovered_scaffold_assigned_crash_summary.csv")

    _write_text(_methodology_markdown(summary), qa_dir / "crash_assignment_qa_methodology_findings.md")

    input_files = [
        tables / "crash_oriented_segment_bin_assignment.csv",
        tables / "crash_oriented_segment_assignment_unresolved.csv",
        tables / "signal_oriented_roadway_segments_crash_ready.csv",
        tables / "signal_oriented_segment_bins_50ft_crash_ready.csv",
        tables / "signal_step5_eligibility.csv",
        tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv",
        tables / "signal_oriented_roadway_segments_role_enriched.csv",
        review / "endpoint_junction_qa" / "endpoint_junction_qa_segment_flags.csv",
    ]
    output_files = [
        qa_dir / "crash_assignment_qa_summary.csv",
        qa_dir / "crash_assignment_distance_distribution.csv",
        qa_dir / "crash_assignment_by_reference_signal.csv",
        qa_dir / "crash_assignment_by_segment_or_bin_flag.csv",
        qa_dir / "crash_assignment_by_recovery_source.csv",
        qa_dir / "unresolved_crash_nearest_scaffold_distance_sample.csv",
        qa_dir / "unresolved_crash_near_scaffold_review_queue.csv",
        qa_dir / "assigned_crash_far_distance_review_queue.csv",
        qa_dir / "recovered_scaffold_assigned_crash_summary.csv",
        qa_dir / "crash_assignment_qa_methodology_findings.md",
        qa_dir / "crash_assignment_qa_manifest.json",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "QA of completed spatial crash assignment onto current roadway_graph Step 5 crash-ready segment/bin scaffold.",
        "qa_only": True,
        "raw_normalized_crash_file_read": False,
        "crash_assignment_outputs_read": True,
        "crash_direction_fields_used": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
        "upstream_downstream_inferred": False,
        "input_files": [str(path) for path in input_files if path.exists()],
        "output_files": [str(path) for path in output_files],
        "thresholds": {
            "far_assigned_distance_ft": far_distance_ft,
            "suspicious_assigned_distance_ft": suspicious_distance_ft,
            "unresolved_near_scaffold_ft": unresolved_near_scaffold_ft,
            "unresolved_nearest_sample_size": unresolved_sample_size,
        },
        "summary": summary,
    }
    _write_json(manifest, qa_dir / "crash_assignment_qa_manifest.json")

    return {path.stem: str(path) for path in output_files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build QA outputs for roadway_graph crash assignment without changing assignment or scaffold logic.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--far-distance-ft", type=float, default=FAR_ASSIGNED_DISTANCE_FT)
    parser.add_argument("--suspicious-distance-ft", type=float, default=SUSPICIOUS_ASSIGNED_DISTANCE_FT)
    parser.add_argument("--unresolved-near-scaffold-ft", type=float, default=UNRESOLVED_NEAR_SCAFFOLD_FT)
    parser.add_argument("--unresolved-sample-size", type=int, default=UNRESOLVED_NEAREST_SAMPLE_SIZE)
    args = parser.parse_args(argv)
    outputs = build_crash_assignment_qa(
        output_root=args.output_root,
        far_distance_ft=args.far_distance_ft,
        suspicious_distance_ft=args.suspicious_distance_ft,
        unresolved_near_scaffold_ft=args.unresolved_near_scaffold_ft,
        unresolved_sample_size=args.unresolved_sample_size,
    )
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
