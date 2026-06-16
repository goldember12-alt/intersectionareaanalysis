from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
INPUT_DIR = Path("review/current/endpoint_junction_qa")
OUTPUT_DIR = Path("review/current/endpoint_junction_qa_prioritization")
TABLES_DIR = Path("tables/current")

UNRESOLVED_RECOVERY_STATUSES = {
    "recovered_low_review_only",
    "still_unresolved_source_missing",
    "still_unresolved_endpoint_or_one_sided",
    "still_unresolved_ambiguous_geometry",
    "still_unresolved_role_excluded",
    "still_unresolved_unknown",
}

NO_ACTION_CATEGORIES = {
    "valid_dead_end_or_one_sided_edge",
    "crossing_without_supported_junction",
    "unknown_endpoint_junction_issue",
}

FAMILY_BY_CATEGORY = {
    "near_miss_endpoint": "endpoint_snap_tolerance_experiment",
    "signal_offset_candidate": "signal_snap_association_tolerance_experiment",
    "unsplit_intersection_candidate": "unsplit_intersection_split_experiment",
    "endpoint_cluster": "endpoint_cluster_consolidation_experiment",
    "opposite_anchor_outside_true_reference_scope": "opposite_anchor_true_scope_relaxation_experiment",
    "divided_carriageway_representation_issue": "divided_carriageway_anchor_parallel_representation_experiment",
    "source_missing_leg_candidate": "valid_exclusion_no_action_category",
    "valid_dead_end_or_one_sided_edge": "valid_exclusion_no_action_category",
    "crossing_without_supported_junction": "valid_exclusion_no_action_category",
    "unknown_endpoint_junction_issue": "valid_exclusion_no_action_category",
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _num(series: pd.Series | None, default: float = 0.0) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _load_inputs(output_root: Path) -> dict[str, pd.DataFrame]:
    review = output_root / INPUT_DIR
    tables = output_root / TABLES_DIR
    return {
        "summary": _read_csv(review / "endpoint_junction_qa_summary.csv"),
        "signal_summary": _read_csv(review / "endpoint_junction_qa_signal_summary.csv"),
        "flags": _read_csv(review / "endpoint_junction_qa_segment_flags.csv"),
        "queue": _read_csv(review / "endpoint_junction_qa_ranked_review_queue.csv"),
        "segments": _read_csv(tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv"),
        "signals": _read_csv(tables / "signal_graph_nodes.csv"),
        "adjacent_edges": _read_csv(tables / "signal_adjacent_edges.csv"),
    }


def _enrich_flags(flags: pd.DataFrame) -> pd.DataFrame:
    out = flags.copy()
    out["proposed_experiment_family"] = out["diagnostic_category"].map(FAMILY_BY_CATEGORY).fillna(
        "valid_exclusion_no_action_category"
    )
    out["is_mainline_divided_unresolved"] = (
        out.get("roadway_role_class", pd.Series("", index=out.index)).eq("mainline_divided_carriageway")
        & out.get("divided_pairing_status", pd.Series("", index=out.index)).eq("unpaired")
        & out.get("recovery_status", pd.Series("", index=out.index)).isin(UNRESOLVED_RECOVERY_STATUSES)
    )
    out["is_true_reference_signal_case"] = out.get("reference_signal_id", pd.Series("", index=out.index)).ne("")
    out["has_oriented_segment"] = out.get("oriented_segment_id", pd.Series("", index=out.index)).ne("")
    out["is_accepted_pair_related"] = out.get("divided_pairing_status", pd.Series("", index=out.index)).str.contains(
        "paired|accepted", case=False, na=False
    )
    out["affected_unresolved_divided_rows_numeric"] = _num(out.get("affected_unresolved_divided_rows"))
    out["review_priority_score_numeric"] = _num(out.get("review_priority_score"))
    return out


def _family_summary(flags: pd.DataFrame) -> pd.DataFrame:
    if flags.empty:
        return pd.DataFrame()
    total = len(flags)
    groups = [
        "diagnostic_category",
        "proposed_experiment_family",
        "roadway_role_class",
        "divided_pairing_status",
        "recovery_status",
        "opposite_anchor_type",
        "route_type_name",
        "route_category",
    ]
    out = flags.groupby(groups, dropna=False).agg(
        flag_count=("affected_record_id", "count"),
        unique_oriented_segments=("oriented_segment_id", lambda s: s[s.astype(str).ne("")].nunique()),
        unique_reference_signals=("reference_signal_id", lambda s: s[s.astype(str).ne("")].nunique()),
        mainline_unresolved_flag_count=("is_mainline_divided_unresolved", "sum"),
        accepted_pair_related_flag_count=("is_accepted_pair_related", "sum"),
    ).reset_index()
    out["flag_share"] = (out["flag_count"] / total).round(6)
    return out.sort_values(["mainline_unresolved_flag_count", "flag_count"], ascending=[False, False])


def _unresolved_impact(flags: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    if flags.empty:
        return pd.DataFrame()
    mainline_unresolved_segments = segments[
        segments.get("roadway_role_class", pd.Series("", index=segments.index)).eq("mainline_divided_carriageway")
        & segments.get("divided_pairing_status", pd.Series("", index=segments.index)).eq("unpaired")
        & segments.get("recovery_status", pd.Series("", index=segments.index)).isin(UNRESOLVED_RECOVERY_STATUSES)
    ].copy()
    total_unresolved_segments = mainline_unresolved_segments["oriented_segment_id"].nunique()
    total_unresolved_signals = mainline_unresolved_segments["reference_signal_id"].nunique()
    rows = []
    for family, group in flags.groupby("proposed_experiment_family", dropna=False):
        direct = group[group["is_mainline_divided_unresolved"]]
        direct_segments = direct["oriented_segment_id"][direct["oriented_segment_id"].ne("")].nunique()
        direct_signals = direct["reference_signal_id"][direct["reference_signal_id"].ne("")].nunique()
        signal_overlap = mainline_unresolved_segments[
            mainline_unresolved_segments["reference_signal_id"].isin(
                group["reference_signal_id"][group["reference_signal_id"].ne("")]
            )
        ]
        rows.append(
            {
                "proposed_experiment_family": family,
                "flag_count": len(group),
                "direct_unresolved_mainline_divided_flags": int(direct["is_mainline_divided_unresolved"].sum()),
                "direct_unresolved_mainline_divided_segments": direct_segments,
                "direct_unresolved_reference_signals": direct_signals,
                "signal_overlap_unresolved_mainline_divided_segments": signal_overlap[
                    "oriented_segment_id"
                ].nunique(),
                "signal_overlap_reference_signals": signal_overlap["reference_signal_id"].nunique(),
                "share_of_all_unresolved_mainline_divided_segments_direct": round(
                    direct_segments / total_unresolved_segments, 6
                )
                if total_unresolved_segments
                else 0.0,
                "share_of_all_unresolved_reference_signals_direct": round(
                    direct_signals / total_unresolved_signals, 6
                )
                if total_unresolved_signals
                else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["direct_unresolved_mainline_divided_segments", "signal_overlap_unresolved_mainline_divided_segments"],
        ascending=[False, False],
    )


def _benefit(value: int, signal_count: int) -> str:
    if value >= 500 or signal_count >= 150:
        return "high"
    if value >= 100 or signal_count >= 40:
        return "medium"
    if value > 0 or signal_count > 0:
        return "low"
    return "none"


def _priority(family: str, benefit: str, risk: str) -> str:
    if family == "valid_exclusion_no_action_category":
        return "diagnostic_only"
    if risk == "high" and benefit != "high":
        return "defer"
    if family == "signal_snap_association_tolerance_experiment":
        return "priority_1_sample_experiment"
    if family == "divided_carriageway_anchor_parallel_representation_experiment":
        return "priority_2_review_design_only"
    if benefit == "high" and risk == "medium":
        return "priority_2_sample_experiment"
    if benefit in {"medium", "high"}:
        return "priority_3_small_sample_only"
    return "defer"


def _experiment_candidates(flags: pd.DataFrame, impact: pd.DataFrame) -> pd.DataFrame:
    family_notes = {
        "endpoint_snap_tolerance_experiment": {
            "risk": "high",
            "scope": "sample/subset only",
            "concerns": "near endpoints can reflect valid dead ends, ramp geometry, divided carriageway separation, or source digitization; naive snapping can create false connectivity",
            "metrics": "node counts by type; endpoint count; near-miss count; new shared-node count; signal adjacency changes; Step 5 eligibility deltas; accepted pair deltas must be zero unless explicitly reviewed",
        },
        "signal_snap_association_tolerance_experiment": {
            "risk": "medium",
            "scope": "sample/subset first, then bounded statewide dry run if stable",
            "concerns": "larger tolerance can attach signals to the wrong carriageway, ramp, or frontage road",
            "metrics": "signal match-distance distribution; zero/one/two/high adjacent-edge signal counts; TRUE/CONDITIONAL/FALSE signal eligibility; affected reference signals; changed signal graph node IDs",
        },
        "unsplit_intersection_split_experiment": {
            "risk": "high",
            "scope": "small reviewed sample only",
            "concerns": "crossing geometry may be grade-separated or otherwise intentionally unconnected; splitting all crossings would create false paths",
            "metrics": "new junction count; crossing-without-supported-junction count; unsplit candidate count; route/ramp exclusion counts; graph component count; changed adjacent edges",
        },
        "endpoint_cluster_consolidation_experiment": {
            "risk": "medium",
            "scope": "cluster sample only",
            "concerns": "clusters can include valid nearby endpoints on divided roads or ramps; consolidation must avoid merging distinct carriageways",
            "metrics": "cluster count; merged-node count; affected routes/components; adjacent-edge count changes; near-miss endpoint deltas",
        },
        "opposite_anchor_true_scope_relaxation_experiment": {
            "risk": "medium",
            "scope": "review-only dry run on unresolved mainline divided rows",
            "concerns": "non-TRUE opposite anchors can be valid boundaries but should not become TRUE reference signals by assumption",
            "metrics": "opposite anchor status counts; reciprocal boundary counts; crash-ready subset deltas; divided-pair candidate deltas; no crash assignment",
        },
        "divided_carriageway_anchor_parallel_representation_experiment": {
            "risk": "medium",
            "scope": "review-only dry run on the 44 low-confidence representation cases first",
            "concerns": "previous recovery found all candidates low-confidence and likely false-positive; representation rules need stronger evidence before promotion",
            "metrics": "parallel/overlap/side score distributions; same-side/self-pair flags; accepted pair preservation; recovered high/medium must remain review-only until checked",
        },
        "valid_exclusion_no_action_category": {
            "risk": "low",
            "scope": "diagnostic only",
            "concerns": "these cases should not be repaired automatically; preserve them as exclusions or unknown review cases",
            "metrics": "stable exclusion counts; unresolved categories; accepted pair preservation",
        },
    }
    rows = []
    impact_by_family = impact.set_index("proposed_experiment_family") if not impact.empty else pd.DataFrame()
    for family in sorted(set(FAMILY_BY_CATEGORY.values())):
        group = flags[flags["proposed_experiment_family"].eq(family)]
        direct_segments = 0
        direct_signals = 0
        signal_overlap_segments = 0
        if not impact_by_family.empty and family in impact_by_family.index:
            rec = impact_by_family.loc[family]
            direct_segments = int(rec["direct_unresolved_mainline_divided_segments"])
            direct_signals = int(rec["direct_unresolved_reference_signals"])
            signal_overlap_segments = int(rec["signal_overlap_unresolved_mainline_divided_segments"])
        benefit = _benefit(direct_segments or signal_overlap_segments, direct_signals)
        risk = family_notes[family]["risk"]
        rows.append(
            {
                "proposed_experiment_family": family,
                "diagnostic_categories": ";".join(
                    sorted([cat for cat, fam in FAMILY_BY_CATEGORY.items() if fam == family])
                ),
                "flag_count": len(group),
                "affected_unresolved_mainline_divided_segments_direct": direct_segments,
                "affected_reference_signals_direct": direct_signals,
                "signal_overlap_unresolved_mainline_divided_segments": signal_overlap_segments,
                "expected_benefit": benefit,
                "false_positive_risk": risk,
                "test_scope_recommendation": family_notes[family]["scope"],
                "false_positive_concerns": family_notes[family]["concerns"],
                "before_after_qa_metrics": family_notes[family]["metrics"],
                "recommended_priority": _priority(family, benefit, risk),
            }
        )
    priority_order = {
        "priority_1_sample_experiment": 1,
        "priority_2_review_design_only": 2,
        "priority_2_sample_experiment": 3,
        "priority_3_small_sample_only": 4,
        "diagnostic_only": 5,
        "defer": 6,
    }
    out = pd.DataFrame(rows)
    out["_priority_sort"] = out["recommended_priority"].map(priority_order).fillna(9)
    return out.sort_values(["_priority_sort", "flag_count"], ascending=[True, False]).drop(columns="_priority_sort")


def _top_review_examples(queue: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    source = queue.copy()
    if source.empty:
        source = flags.copy()
    source["proposed_experiment_family"] = source["diagnostic_category"].map(FAMILY_BY_CATEGORY).fillna(
        "valid_exclusion_no_action_category"
    )
    source["review_priority_score_numeric"] = _num(source.get("review_priority_score"))
    pieces = []
    for family, group in source.sort_values("review_priority_score_numeric", ascending=False).groupby(
        "proposed_experiment_family", dropna=False
    ):
        take = 8 if family != "valid_exclusion_no_action_category" else 10
        pieces.append(group.head(take))
    out = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    out = out.sort_values("review_priority_score_numeric", ascending=False).head(50)
    keep = [
        "review_priority_score",
        "diagnostic_category",
        "proposed_experiment_family",
        "diagnostic_confidence",
        "affected_record_id",
        "oriented_segment_id",
        "graph_edge_id",
        "graph_node_id",
        "reference_signal_id",
        "route_name",
        "route_common",
        "route_stem",
        "roadway_role_class",
        "route_type_name",
        "route_category",
        "divided_pairing_status",
        "recovery_status",
        "opposite_anchor_type",
        "opposite_anchor_step5_status",
        "distance_ft",
        "nearby_record_id",
        "nearby_route_common",
        "affected_unresolved_divided_rows",
        "affected_signal_count",
        "evidence_summary",
    ]
    return out[[column for column in keep if column in out.columns]]


def _no_action_examples(flags: pd.DataFrame) -> pd.DataFrame:
    if flags.empty:
        return flags.copy()
    no_action = flags[
        flags["diagnostic_category"].isin(NO_ACTION_CATEGORIES)
        | flags["route_category"].str.contains("Ramp|Frontage|Service", case=False, na=False)
        | flags["route_type_name"].str.contains("Ramp|Frontage|Service", case=False, na=False)
    ].copy()
    no_action["reason_to_avoid_automatic_repair"] = no_action["diagnostic_category"].map(
        {
            "valid_dead_end_or_one_sided_edge": "valid one-sided or dead-end boundaries must not be forced into reciprocal pairing",
            "crossing_without_supported_junction": "crossing geometry is review evidence only and may be grade-separated or otherwise unconnected",
            "unknown_endpoint_junction_issue": "unknown cases need better evidence before any graph rule change",
        }
    ).fillna("ramp/frontage/service-like source context should not be repaired by generic endpoint rules")
    no_action["review_priority_score_numeric"] = _num(no_action.get("review_priority_score"))
    keep = [
        "diagnostic_category",
        "proposed_experiment_family",
        "reason_to_avoid_automatic_repair",
        "affected_record_id",
        "oriented_segment_id",
        "graph_edge_id",
        "graph_node_id",
        "reference_signal_id",
        "route_name",
        "route_common",
        "roadway_role_class",
        "route_type_name",
        "route_category",
        "divided_pairing_status",
        "recovery_status",
        "opposite_anchor_type",
        "distance_ft",
        "nearby_record_id",
        "evidence_summary",
    ]
    return no_action.sort_values("review_priority_score_numeric", ascending=False)[
        [column for column in keep if column in no_action.columns]
    ].head(60)


def _write_design_md(path: Path, candidates: pd.DataFrame, impact: pd.DataFrame, flags: pd.DataFrame) -> None:
    counts = flags["proposed_experiment_family"].value_counts().to_dict() if not flags.empty else {}
    priority = candidates[candidates["recommended_priority"].ne("diagnostic_only")].head(3)
    safest = candidates[candidates["recommended_priority"].eq("priority_1_sample_experiment")]
    if safest.empty:
        safest_text = "No production graph-rule experiment is safe enough for automatic application. Continue diagnostic review."
    else:
        row = safest.iloc[0]
        safest_text = (
            f"The safest first experiment is `{row['proposed_experiment_family']}` as a sample-only dry run. "
            "It changes no production outputs and compares signal association/adjacency metrics before and after."
        )

    lines = [
        "# Endpoint/Junction Rule Experiment Design",
        "",
        "**Status: CURRENT REVIEW DESIGN.** This pass prioritizes endpoint/junction QA findings and designs graph-rule experiments. It does not change graph construction.",
        "",
        "## Boundary",
        "",
        "No crash data was read. No crashes were assigned. Crash direction fields were not used. Accepted divided pairs were not modified. Recovered divided-pair candidates were not promoted. Default geometric direction outputs were not modified. QGIS, ArcGIS, and Network Analyst were not required.",
        "",
        "## What The QA Results Mean",
        "",
        "The endpoint/junction QA output is a review surface, not a repair instruction. Large near-miss, signal-offset, and unsplit-intersection counts show where graph-build rules may deserve narrow experiments. They do not prove that snapping, splitting, or scope relaxation would be correct.",
        "",
        "Issue-family counts:",
    ]
    for family, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"- `{family}`: {count}")
    lines.extend(
        [
            "",
            "## Why Automatic Repair Is Not Appropriate",
            "",
            "Endpoint proximity can represent true topology errors, but it can also represent divided carriageways, ramps, frontage roads, source digitization artifacts, or valid dead ends. Crossing lines can be grade-separated or otherwise intentionally unconnected. Non-TRUE opposite anchors can be valid segment boundaries without becoming TRUE reference signals. A broad snap/split pass would create false connectivity risk.",
            "",
            "## Safest First Experiment",
            "",
            safest_text,
            "",
            "The first experiment should be a dry run only: write alternate review outputs, compare metrics, and leave accepted pairs and default geometric direction outputs unchanged.",
            "",
            "## Proposed Experiment Priorities",
            "",
        ]
    )
    for _, row in priority.iterrows():
        lines.append(
            "- `{}`: priority `{}`, benefit `{}`, risk `{}`, scope `{}`".format(
                row["proposed_experiment_family"],
                row["recommended_priority"],
                row["expected_benefit"],
                row["false_positive_risk"],
                row["test_scope_recommendation"],
            )
        )
    diagnostic_only = candidates[candidates["recommended_priority"].eq("diagnostic_only")]
    lines.extend(["", "## Categories To Keep Diagnostic Only", ""])
    for _, row in diagnostic_only.iterrows():
        lines.append(
            f"- `{row['proposed_experiment_family']}`: {row['false_positive_concerns']}"
        )
    lines.extend(
        [
            "",
            "## Required Before/After QA Metrics",
            "",
        ]
    )
    for _, row in candidates.iterrows():
        lines.append(f"### {row['proposed_experiment_family']}")
        lines.append("")
        lines.append(row["before_after_qa_metrics"])
        lines.append("")
    lines.extend(
        [
            "## Recommendation",
            "",
            "Run a sample-only signal snap/association tolerance dry run first, because it is narrower than endpoint snapping or line splitting and can be evaluated with signal match distance, adjacent-edge counts, and Step 5 eligibility deltas. Keep endpoint snapping, unsplit intersection splitting, broad TRUE-scope relaxation, and generic divided-pair promotion out of production until review evidence improves.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(output_root: Path = OUTPUT_ROOT) -> dict[str, object]:
    data = _load_inputs(output_root)
    out_dir = output_root / OUTPUT_DIR
    flags = _enrich_flags(data["flags"])
    queue = _enrich_flags(data["queue"]) if not data["queue"].empty else data["queue"]
    summary = _family_summary(flags)
    impact = _unresolved_impact(flags, data["segments"])
    candidates = _experiment_candidates(flags, impact)
    examples = _top_review_examples(queue, flags)
    no_action = _no_action_examples(flags)

    _write_csv(summary, out_dir / "endpoint_junction_issue_family_summary.csv")
    _write_csv(impact, out_dir / "endpoint_junction_unresolved_divided_impact.csv")
    _write_csv(candidates, out_dir / "endpoint_junction_rule_experiment_candidates.csv")
    _write_csv(examples, out_dir / "endpoint_junction_top_review_examples.csv")
    _write_csv(no_action, out_dir / "endpoint_junction_no_action_or_valid_exclusion_examples.csv")
    _write_design_md(out_dir / "endpoint_junction_rule_experiment_design.md", candidates, impact, flags)

    manifest = {
        "input_dir": (output_root / INPUT_DIR).as_posix(),
        "output_dir": out_dir.as_posix(),
        "crash_data_read": False,
        "graph_construction_changed": False,
        "accepted_pairs_modified": False,
        "geometric_direction_outputs_modified": False,
        "issue_family_counts": flags["proposed_experiment_family"].value_counts().to_dict(),
        "recommended_first_experiment": "signal_snap_association_tolerance_experiment_sample_dry_run",
    }
    (out_dir / "endpoint_junction_qa_prioritization_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prioritize endpoint/junction QA findings into graph-rule experiments.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(run(args.output_root), indent=2))


if __name__ == "__main__":
    main()
