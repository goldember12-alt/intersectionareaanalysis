from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
REVIEW_DIR = Path("review/current/codex_native_divided_pairing_recovery_review")
TABLES_DIR = Path("tables/current")
GEOJSON_DIR = Path("review/geojson/current")

REVIEW_STATUSES = {"recovered_high", "recovered_medium", "recovered_low_review_only"}
PROMOTABLE_STATUSES = {"recovered_high", "recovered_medium"}
EXCLUDED_GENERIC_ROLES = {
    "ramp_or_connector",
    "frontage_or_service_road",
    "turn_lane_or_auxiliary",
    "unknown_review",
    "one_way_pair_candidate",
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_wkt_csv(path: Path) -> gpd.GeoDataFrame:
    frame = _read_csv(path)
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=[])
    if "geometry" in frame.columns:
        frame["geometry"] = frame["geometry"].map(wkt.loads)
        return gpd.GeoDataFrame(frame, geometry="geometry")
    return gpd.GeoDataFrame(frame)


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns and isinstance(frame, gpd.GeoDataFrame):
        out["geometry"] = frame.geometry.to_wkt()
    out.to_csv(path, index=False)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty or "geometry" not in frame.columns:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    else:
        frame.to_file(path, driver="GeoJSON")


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _coalesce(frame: pd.DataFrame, *columns: str) -> pd.Series:
    result = pd.Series([""] * len(frame), index=frame.index, dtype=object)
    for column in columns:
        if column in frame.columns:
            values = frame[column].fillna("").astype(str)
            result = result.where(result.astype(str).ne(""), values)
    return result


def _metric_rows(enriched: pd.DataFrame, candidates: pd.DataFrame, still_unresolved: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(group: str, key: str, value: object, count: int) -> None:
        rows.append({"metric_group": group, "metric_key": key, "metric_value": value, "row_count": int(count)})

    for column, group in [
        ("recovery_method", "candidate_recovery_method"),
        ("roadway_role_class", "candidate_roadway_role"),
        ("recovery_confidence", "candidate_confidence"),
        ("rte_type_name", "candidate_route_type"),
        ("rte_category", "candidate_route_category"),
        ("opposite_anchor_type", "candidate_anchor_type"),
        ("recovery_reason", "candidate_recovery_reason"),
    ]:
        if column in candidates.columns:
            for value, count in candidates[column].fillna("").value_counts(dropna=False).sort_index().items():
                add(group, column, value, count)

    for column, group in [
        ("divided_pairing_status", "enriched_prior_pairing_status"),
        ("recovery_status", "enriched_recovery_status"),
        ("promotion_recommendation", "enriched_promotion_recommendation"),
        ("roadway_role_class", "enriched_roadway_role"),
    ]:
        if column in enriched.columns:
            for value, count in enriched[column].fillna("").value_counts(dropna=False).sort_index().items():
                add(group, column, value, count)

    if "likely_blocker" in still_unresolved.columns:
        for value, count in still_unresolved["likely_blocker"].fillna("").value_counts(dropna=False).sort_index().items():
            add("still_unresolved_likely_blocker", "likely_blocker", value, count)
    return pd.DataFrame(rows)


def _false_positive_screen(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    out = candidates.copy()
    out["side_score_numeric"] = _num(out.get("side_score", pd.Series(index=out.index)))
    out["parallelism_score_numeric"] = _num(out.get("parallelism_score", pd.Series(index=out.index)))
    out["projected_overlap_score_numeric"] = _num(out.get("projected_overlap_score", pd.Series(index=out.index)))
    out["lateral_separation_ft_numeric"] = _num(out.get("lateral_separation_ft", pd.Series(index=out.index)))
    text = (
        out.get("route_name", pd.Series("", index=out.index)).astype(str)
        + " "
        + out.get("route_common", pd.Series("", index=out.index)).astype(str)
        + " "
        + out.get("recovery_reason", pd.Series("", index=out.index)).astype(str)
    ).str.lower()
    out["flag_possible_cross_street"] = (
        (out["parallelism_score_numeric"] < 0.60)
        | ((out["projected_overlap_score_numeric"] < 0.15) & (out["same_anchor_cluster"].astype(str).str.lower().ne("true")))
    )
    out["flag_possible_ramp_connector"] = text.str.contains(r"\bramp\b|\bconnector\b|\bloop\b|\bslip\b", regex=True)
    out["flag_possible_frontage_service"] = text.str.contains(r"\bfrontage\b|\bservice\b|\bcollector[- ]?distributor\b|\bc-d\b", regex=True)
    out["flag_possible_same_side_or_self_pair"] = (
        out["original_oriented_segment_id"].eq(out["paired_opposite_segment_id"])
        | (out["lateral_separation_ft_numeric"] < 10.0)
    )
    out["flag_weak_overlap"] = out["projected_overlap_score_numeric"] < 0.25
    out["flag_unstable_side_separation"] = (out["side_score_numeric"] < 0.55) | out["recovery_reason"].astype(str).str.contains("ambiguous", case=False, na=False)
    out["flag_suspicious_endpoint_case"] = (
        out.get("opposite_anchor_type", pd.Series("", index=out.index)).astype(str).str.lower().str.contains("endpoint")
        | out.get("opposite_anchor_step5_status", pd.Series("", index=out.index)).astype(str).isin(["FALSE", "CONDITIONAL"])
    )
    flag_cols = [column for column in out.columns if column.startswith("flag_")]
    out["false_positive_flag_count"] = out[flag_cols].sum(axis=1)
    out["false_positive_screen_result"] = out["false_positive_flag_count"].map(
        lambda count: "likely_false_positive_review" if count >= 2 else "needs_review" if count == 1 else "no_screen_flag"
    )
    keep_cols = [
        "original_oriented_segment_id",
        "recovered_pair_id",
        "paired_opposite_segment_id",
        "reference_signal_id",
        "route_name",
        "route_common",
        "route_stem",
        "roadway_role_class",
        "recovery_status",
        "recovery_confidence",
        "recovery_reason",
        "promotion_recommendation",
        "side_score",
        "parallelism_score",
        "projected_overlap_score",
        "lateral_separation_ft",
        "bearing_diff_degrees",
        "same_anchor_cluster",
        "false_positive_flag_count",
        "false_positive_screen_result",
    ] + flag_cols
    out = out.sort_values(
        ["false_positive_flag_count", "parallelism_score_numeric", "projected_overlap_score_numeric"],
        ascending=[False, True, True],
    )
    return out[[column for column in keep_cols if column in out.columns]]


def _ranked_queue(candidates: pd.DataFrame, false_screen: pd.DataFrame, enriched: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    out = candidates.copy()
    out["side_score_numeric"] = _num(out.get("side_score", pd.Series(index=out.index)))
    out["parallelism_score_numeric"] = _num(out.get("parallelism_score", pd.Series(index=out.index)))
    out["projected_overlap_score_numeric"] = _num(out.get("projected_overlap_score", pd.Series(index=out.index)))
    out["lateral_separation_ft_numeric"] = _num(out.get("lateral_separation_ft", pd.Series(index=out.index)))
    flag_counts = false_screen.set_index("original_oriented_segment_id").get("false_positive_flag_count", pd.Series(dtype=float))
    out["false_positive_flag_count"] = out["original_oriented_segment_id"].map(flag_counts).fillna(0).astype(int)
    confidence_rank = out["recovery_status"].map({"recovered_high": 3, "recovered_medium": 2, "recovered_low_review_only": 1}).fillna(0)
    out["codex_review_score"] = (
        confidence_rank * 10.0
        + out["parallelism_score_numeric"] * 3.0
        + out["projected_overlap_score_numeric"] * 3.0
        + out["side_score_numeric"] * 2.0
        - out["false_positive_flag_count"] * 2.5
    ).round(4)
    length_by_segment = enriched.set_index("oriented_segment_id").get("length_ft", pd.Series(dtype=object))
    prior_status = enriched.set_index("oriented_segment_id").get("divided_pairing_status", pd.Series(dtype=object))
    out["segment_length_ft"] = out["original_oriented_segment_id"].map(length_by_segment).fillna("")
    out["prior_pairing_status"] = out["original_oriented_segment_id"].map(prior_status).fillna("")
    cols = [
        "codex_review_score",
        "original_oriented_segment_id",
        "recovered_pair_id",
        "paired_opposite_segment_id",
        "reference_signal_id",
        "route_name",
        "route_common",
        "route_stem",
        "rte_type_name",
        "rte_category",
        "opposite_anchor_type",
        "opposite_anchor_step5_status",
        "segment_length_ft",
        "bearing_diff_degrees",
        "parallelism_score",
        "projected_overlap_score",
        "lateral_separation_ft",
        "side_score",
        "roadway_role_class",
        "prior_pairing_status",
        "recovery_status",
        "recovery_confidence",
        "recovery_reason",
        "recovery_method",
        "promotion_recommendation",
        "false_positive_flag_count",
    ]
    return out[[column for column in cols if column in out.columns]].sort_values("codex_review_score", ascending=False)


def _likely_blocker(row: pd.Series) -> str:
    status = str(row.get("recovery_status", ""))
    role = str(row.get("roadway_role_class", ""))
    reason = " ".join(
        str(row.get(column, ""))
        for column in [
            "recovery_reason",
            "pairing_problem_reason",
            "missing_reciprocal_reason",
            "geometric_direction_problem_reason",
            "readiness_revision_reason",
        ]
    ).lower()
    opposite_status = str(row.get("opposite_anchor_step5_status", "")).upper()
    opposite_type = str(row.get("opposite_anchor_type", "")).lower()
    if role in EXCLUDED_GENERIC_ROLES:
        if role == "one_way_pair_candidate":
            return "one_way_or_couplet_candidate"
        return "non_mainline_role_exclusion"
    if opposite_status in {"FALSE", "CONDITIONAL"}:
        return "opposite_anchor_outside_true_reference_scope"
    if "one_sided" in status or "one-sided" in reason or "endpoint" in reason or opposite_type in {"endpoint", "road_endpoint", "road_endpoint_dead_end"}:
        return "endpoint_or_one_sided_edge"
    if "route" in reason or "stem" in reason or "scope" in reason:
        return "route_stem_or_scope_issue"
    if "ambiguous" in reason or "side" in reason or "bracket" in reason or status == "still_unresolved_ambiguous_geometry":
        return "ambiguous_side_geometry"
    if "source" in reason or "missing" in reason:
        return "missing_opposite_travelway_geometry"
    return "unknown"


def _unresolved_summary(still_unresolved: pd.DataFrame) -> pd.DataFrame:
    if still_unresolved.empty:
        return pd.DataFrame(columns=["likely_blocker", "roadway_role_class", "opposite_anchor_type", "row_count"])
    out = still_unresolved.copy()
    out["likely_blocker"] = out.apply(_likely_blocker, axis=1)
    return (
        out.groupby(["likely_blocker", "roadway_role_class", "opposite_anchor_type"], dropna=False)
        .size()
        .reset_index(name="row_count")
        .sort_values(["likely_blocker", "roadway_role_class", "opposite_anchor_type"])
    )


def _examples(queue: pd.DataFrame, false_screen: pd.DataFrame, still_unresolved: pd.DataFrame) -> pd.DataFrame:
    samples = []
    for label, frame in [
        ("strongest_candidate", queue.head(10)),
        ("weakest_candidate", queue.tail(10)),
        ("likely_false_positive", false_screen.loc[false_screen["false_positive_flag_count"].astype(int) >= 2].head(10)),
        ("still_unresolved", still_unresolved.head(20)),
    ]:
        sample = frame.copy()
        if sample.empty:
            continue
        sample.insert(0, "example_type", label)
        samples.append(sample)
    if not samples:
        return pd.DataFrame()
    return pd.concat(samples, ignore_index=True, sort=False)


def _write_optional_static_artifacts(
    review_root: Path,
    queue: pd.DataFrame,
    false_screen: pd.DataFrame,
    recovered_geo: gpd.GeoDataFrame,
    unresolved_geo: gpd.GeoDataFrame,
) -> None:
    strongest_ids = set(queue.head(40).get("original_oriented_segment_id", pd.Series(dtype=str)).astype(str))
    false_ids = set(false_screen.head(40).get("original_oriented_segment_id", pd.Series(dtype=str)).astype(str))
    strong_geo = recovered_geo.loc[recovered_geo.get("oriented_segment_id", pd.Series("", index=recovered_geo.index)).astype(str).isin(strongest_ids)].copy()
    false_geo = recovered_geo.loc[recovered_geo.get("oriented_segment_id", pd.Series("", index=recovered_geo.index)).astype(str).isin(false_ids)].copy()
    _write_geojson(strong_geo, review_root / "strongest_recovery_candidates.geojson")
    _write_geojson(false_geo, review_root / "likely_false_positive_recovery_candidates.geojson")
    _write_geojson(unresolved_geo.head(100), review_root / "still_unresolved_sample.geojson")

    try:
        import matplotlib.pyplot as plt

        if not queue.empty:
            fig, ax = plt.subplots(figsize=(7, 4))
            queue["codex_review_score"].astype(float).hist(ax=ax, bins=12)
            ax.set_title("Recovery Candidate Codex Review Scores")
            ax.set_xlabel("score")
            ax.set_ylabel("candidate rows")
            fig.tight_layout()
            fig.savefig(review_root / "recovery_candidate_score_distribution.png", dpi=160)
            plt.close(fig)
    except Exception as exc:  # pragma: no cover - optional artifact only
        (review_root / "optional_plot_error.txt").write_text(str(exc), encoding="utf-8")


def _markdown_summary(
    *,
    output_root: Path,
    review_root: Path,
    candidates: pd.DataFrame,
    false_screen: pd.DataFrame,
    queue: pd.DataFrame,
    unresolved_summary: pd.DataFrame,
    enriched: pd.DataFrame,
) -> str:
    existing = int(enriched.get("recovery_status", pd.Series(dtype=str)).eq("existing_accepted_pair").sum())
    high = int(enriched.get("recovery_status", pd.Series(dtype=str)).eq("recovered_high").sum())
    medium = int(enriched.get("recovery_status", pd.Series(dtype=str)).eq("recovered_medium").sum())
    low = int(enriched.get("recovery_status", pd.Series(dtype=str)).eq("recovered_low_review_only").sum())
    unresolved = int(enriched.get("recovery_status", pd.Series(dtype=str)).astype(str).str.startswith("still_unresolved").sum())
    likely_false = int(false_screen.get("false_positive_flag_count", pd.Series(dtype=float)).astype(float).ge(2).sum()) if not false_screen.empty else 0
    blocker_lines = "\n".join(
        f"- `{row.likely_blocker}`: {int(row.row_count)}"
        for row in unresolved_summary.groupby("likely_blocker", dropna=False)["row_count"].sum().reset_index().itertuples()
    )
    return f"""# Codex-Native Divided Pairing Recovery Review

## Bounded Question

This review inspects the no-crash divided-pairing recovery outputs using only tabular, geometry-derived, and static repository-native artifacts. It does not use QGIS, ArcGIS Network Analyst, crash data, crash direction fields, or crash distributions.

## Inputs

The review consumed existing roadway_graph recovery, role, accepted-pair, and graph scaffold outputs under `{output_root}`.

## Findings

- Existing accepted pair rows preserved in recovery-enriched output: {existing}
- Recovered high rows: {high}
- Recovered medium rows: {medium}
- Recovered low review-only rows: {low}
- Candidate rows inspected: {len(candidates)}
- Candidate rows with two or more false-positive screen flags: {likely_false}
- Still unresolved rows after recovery: {unresolved}

## What Improved

The recovery prototype created a small review-only candidate queue. It did not produce high- or medium-confidence candidates suitable for promotion. That is a useful conservative result: the current geometry and role evidence is not strong enough to expand accepted divided pairs without later visual confirmation or a narrower rule.

## What Remains Unresolved

{blocker_lines if blocker_lines else "- No unresolved rows were present in the inspected input."}

## What Should Not Be Promoted

Do not promote any recovery candidate into the default geometric direction model from this review. Low-confidence candidates remain review-only. Accepted high/medium divided pairs from the previous pairing pass remain preserved and unchanged.

## Static Review Artifacts

- `recovery_candidate_metric_summary.csv`
- `recovery_candidate_false_positive_screen.csv`
- `recovery_candidate_ranked_review_queue.csv`
- `still_unresolved_diagnostic_summary.csv`
- `codex_native_review_examples.csv`
- optional GeoJSON subsets for strongest candidates, likely false positives, and unresolved samples
- optional PNG score distribution if matplotlib is available

## Later GIS Review Needed

Later QGIS review should verify whether low-confidence candidate pairs are true opposite carriageways or false positives caused by cross-streets, ramps/connectors, same-side geometry, endpoint artifacts, or weak overlap. Until that review is complete, keep these candidates out of production direction/upstream-downstream logic.
"""


def build_codex_native_review(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / TABLES_DIR
    review = output_root / "review/current"
    geojson = output_root / GEOJSON_DIR
    review_root = output_root / REVIEW_DIR
    review_root.mkdir(parents=True, exist_ok=True)

    candidates = _read_csv(tables / "divided_carriageway_pair_candidates_recovery.csv")
    enriched = _read_wkt_csv(tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv")
    recovered = _read_wkt_csv(review / "divided_pairing_recovered_rows.csv")
    still_unresolved = _read_wkt_csv(review / "divided_pairing_still_unresolved_rows.csv")
    _ = _read_csv(review / "divided_pairing_recovery_summary.csv")
    _ = _read_csv(tables / "roadway_role_classification.csv")
    _ = _read_wkt_csv(tables / "signal_oriented_roadway_segments_role_enriched.csv")
    _ = _read_csv(tables / "divided_carriageway_pair_candidates.csv")
    _ = _read_wkt_csv(tables / "signal_oriented_roadway_segments_divided_pairing_enriched.csv")
    _ = _read_csv(tables / "roadway_graph_nodes.csv")
    _ = _read_csv(tables / "roadway_graph_edges.csv")
    recovered_geo = gpd.read_file(geojson / "divided_pairing_recovery_review.geojson") if (geojson / "divided_pairing_recovery_review.geojson").exists() else recovered
    unresolved_geo = (
        gpd.read_file(geojson / "divided_pairing_still_unresolved_review.geojson")
        if (geojson / "divided_pairing_still_unresolved_review.geojson").exists()
        else still_unresolved
    )

    still_unresolved_plain = pd.DataFrame(still_unresolved.drop(columns="geometry", errors="ignore")).copy()
    if not still_unresolved_plain.empty:
        still_unresolved_plain["likely_blocker"] = still_unresolved_plain.apply(_likely_blocker, axis=1)

    false_screen = _false_positive_screen(candidates)
    queue = _ranked_queue(candidates, false_screen, pd.DataFrame(enriched.drop(columns="geometry", errors="ignore")))
    unresolved_summary = _unresolved_summary(still_unresolved_plain)
    metrics = _metric_rows(pd.DataFrame(enriched.drop(columns="geometry", errors="ignore")), candidates, still_unresolved_plain)
    examples = _examples(queue, false_screen, still_unresolved_plain)

    _write_csv(metrics, review_root / "recovery_candidate_metric_summary.csv")
    _write_csv(false_screen, review_root / "recovery_candidate_false_positive_screen.csv")
    _write_csv(queue, review_root / "recovery_candidate_ranked_review_queue.csv")
    _write_csv(unresolved_summary, review_root / "still_unresolved_diagnostic_summary.csv")
    _write_csv(examples, review_root / "codex_native_review_examples.csv")
    _write_optional_static_artifacts(review_root, queue, false_screen, recovered_geo, unresolved_geo)

    markdown = _markdown_summary(
        output_root=output_root,
        review_root=review_root,
        candidates=candidates,
        false_screen=false_screen,
        queue=queue,
        unresolved_summary=unresolved_summary,
        enriched=pd.DataFrame(enriched.drop(columns="geometry", errors="ignore")),
    )
    (review_root / "codex_native_divided_pairing_recovery_review.md").write_text(markdown, encoding="utf-8")
    (review_root / "input_manifest.json").write_text(
        json.dumps(
            {
                "crash_data_read": False,
                "accepted_pairs_overwritten": False,
                "qgis_required": False,
                "arcgis_network_analyst_used": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "review_root": str(review_root),
        "metric_summary": str(review_root / "recovery_candidate_metric_summary.csv"),
        "false_positive_screen": str(review_root / "recovery_candidate_false_positive_screen.csv"),
        "ranked_queue": str(review_root / "recovery_candidate_ranked_review_queue.csv"),
        "unresolved_summary": str(review_root / "still_unresolved_diagnostic_summary.csv"),
        "examples": str(review_root / "codex_native_review_examples.csv"),
        "markdown": str(review_root / "codex_native_divided_pairing_recovery_review.md"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Codex-native divided pairing recovery review artifacts.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_codex_native_review(output_root=args.output_root)
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
