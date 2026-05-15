from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
ASSIGNMENT_INPUT_DIR = Path("review/current/crash_directional_catchment_assignment_prototype")
QA_INPUT_DIR = Path("review/current/crash_directional_catchment_assignment_qa")
CATCHMENT_INPUT_DIR = Path("review/current/reference_signal_directional_bin_catchments")
SCAFFOLD_INPUT_DIR = Path("review/current/reference_signal_directional_scaffold_qa")
READINESS_OUTPUT_DIR = Path("review/current/crash_directional_assignment_analysis_readiness")

ASSIGNMENTS_FILE = "crash_directional_catchment_assignments.csv"
AMBIGUOUS_FILE = "crash_directional_catchment_ambiguous.csv"
UNRESOLVED_FILE = "crash_directional_catchment_unresolved.csv"
CATCHMENT_INDEX_FILE = "directional_bin_catchment_index.csv"
USABLE_SEGMENTS_FILE = "directional_scaffold_prototype_usable_segments.csv"
USABLE_BINS_FILE = "directional_scaffold_prototype_usable_bins_50ft.csv"

DOWNSTREAM = "downstream_of_reference_signal"
UPSTREAM = "upstream_of_reference_signal"
DIVIDED = "divided_physical_carriageway"
UNDIVIDED = "undivided_centerline_pseudo_direction"
WINDOWS = [250, 500, 1000, 1500, 2500, 5000]


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _group_count(frame: pd.DataFrame, columns: list[str], count_name: str = "crash_count") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*columns, count_name])
    return frame.groupby(columns, dropna=False).size().reset_index(name=count_name).sort_values(count_name, ascending=False)


def _window_label(distance_ft: float) -> str:
    if pd.isna(distance_ft):
        return "unknown_distance"
    if distance_ft <= 250:
        return "0_to_250ft"
    if distance_ft <= 500:
        return "250_to_500ft"
    if distance_ft <= 1000:
        return "500_to_1000ft"
    if distance_ft <= 1500:
        return "1000_to_1500ft"
    if distance_ft <= 2500:
        return "1500_to_2500ft"
    if distance_ft <= 5000:
        return "2500_to_5000ft"
    return "over_5000ft"


def _readiness_class(distance_ft: float) -> str:
    if pd.isna(distance_ft):
        return "assignment_valid_but_functional_relevance_uncertain"
    if distance_ft <= 500:
        return "core_0_500ft"
    if distance_ft <= 1000:
        return "standard_0_1000ft"
    if distance_ft <= 2500:
        return "extended_0_2500ft"
    if distance_ft <= 5000:
        return "assignment_valid_but_functional_relevance_uncertain"
    return "long_distance_review"


def _recommended_use(readiness_class: str) -> str:
    return {
        "core_0_500ft": "include_core_summary",
        "standard_0_1000ft": "include_standard_summary",
        "extended_0_2500ft": "include_extended_sensitivity",
        "long_distance_review": "review_before_functional_analysis",
        "assignment_valid_but_functional_relevance_uncertain": "assignment_only_do_not_analyze",
    }.get(readiness_class, "assignment_only_do_not_analyze")


def _enrich_assignments(assignments: pd.DataFrame, catchments: pd.DataFrame, bins: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    out = assignments.copy()
    catchment_keep = [
        "catchment_id",
        "catchment_status",
        "side_relative_to_reference_to_anchor",
        "catchment_confidence",
    ]
    bin_keep = [
        "reference_directional_bin_id",
        "far_anchor_type",
        "bin_midpoint_ft_from_reference_signal",
    ]
    segment_keep = [
        "reference_directional_segment_id",
        "far_anchor_type",
        "segment_length_ft",
        "roadway_role_class",
    ]
    out = out.merge(catchments[[c for c in catchment_keep if c in catchments.columns]], on="catchment_id", how="left")
    out = out.merge(bins[[c for c in bin_keep if c in bins.columns]], on="reference_directional_bin_id", how="left", suffixes=("", "_bin"))
    out = out.merge(segments[[c for c in segment_keep if c in segments.columns]], on="reference_directional_segment_id", how="left", suffixes=("", "_segment"))
    if "far_anchor_type" not in out.columns and "far_anchor_type_segment" in out.columns:
        out["far_anchor_type"] = out["far_anchor_type_segment"]
    elif "far_anchor_type_segment" in out.columns:
        out["far_anchor_type"] = out["far_anchor_type"].where(out["far_anchor_type"].astype(str).ne(""), out["far_anchor_type_segment"])
    midpoint = _num(out, "bin_midpoint_ft_from_reference_signal")
    midpoint = midpoint.where(~midpoint.isna(), (_num(out, "bin_start_ft_from_reference_signal") + _num(out, "bin_end_ft_from_reference_signal")) / 2.0)
    out["bin_midpoint_ft_from_reference_signal"] = midpoint
    out["functional_distance_window"] = out["bin_midpoint_ft_from_reference_signal"].map(_window_label)
    for window in WINDOWS:
        out[f"functional_window_{window}ft"] = out["bin_midpoint_ft_from_reference_signal"].le(window)
    out["full_segment_assignment"] = True
    out["long_distance_review_flag"] = out["bin_midpoint_ft_from_reference_signal"].gt(5000)
    out["analysis_readiness_class"] = out["bin_midpoint_ft_from_reference_signal"].map(_readiness_class)
    out["recommended_use"] = out["analysis_readiness_class"].map(_recommended_use)
    return out


def _balance_by_window(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    grouped = frame.groupby(group_columns + ["signal_relative_direction"], dropna=False).size().unstack(fill_value=0)
    for direction in [DOWNSTREAM, UPSTREAM]:
        if direction not in grouped.columns:
            grouped[direction] = 0
    out = grouped.reset_index().rename(columns={DOWNSTREAM: "downstream", UPSTREAM: "upstream"})
    out["total"] = out["downstream"] + out["upstream"]
    return out.sort_values(group_columns)


def build_crash_directional_assignment_analysis_readiness(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    assignment_dir = output_root / ASSIGNMENT_INPUT_DIR
    qa_dir = output_root / QA_INPUT_DIR
    catchment_dir = output_root / CATCHMENT_INPUT_DIR
    scaffold_dir = output_root / SCAFFOLD_INPUT_DIR
    out_dir = output_root / READINESS_OUTPUT_DIR

    assignments = _read_csv(assignment_dir / ASSIGNMENTS_FILE)
    ambiguous = _read_csv(assignment_dir / AMBIGUOUS_FILE)
    unresolved = _read_csv(assignment_dir / UNRESOLVED_FILE)
    catchments = _read_csv(catchment_dir / CATCHMENT_INDEX_FILE)
    segments = _read_csv(scaffold_dir / USABLE_SEGMENTS_FILE)
    bins = _read_csv(scaffold_dir / USABLE_BINS_FILE)

    readiness = _enrich_assignments(assignments, catchments, bins, segments)
    output_columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_index_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "functional_window_250ft",
        "functional_window_500ft",
        "functional_window_1000ft",
        "functional_window_1500ft",
        "functional_window_2500ft",
        "functional_window_5000ft",
        "full_segment_assignment",
        "long_distance_review_flag",
        "analysis_readiness_class",
        "recommended_use",
        "functional_distance_window",
        "far_anchor_type",
        "catchment_method",
        "side_relative_to_reference_to_anchor",
    ]
    readiness_out = readiness[[c for c in output_columns if c in readiness.columns]].copy()

    by_window = _group_count(readiness, ["analysis_readiness_class", "recommended_use", "functional_distance_window"])
    by_signal_window = _group_count(readiness, ["reference_signal_id", "analysis_readiness_class", "functional_distance_window"])
    by_direction_window = _balance_by_window(readiness, ["analysis_readiness_class", "functional_distance_window"])
    by_representation_window = (
        readiness.groupby(["roadway_representation_type", "analysis_readiness_class", "functional_distance_window"], dropna=False)
        .size()
        .reset_index(name="crash_count")
        .sort_values(["roadway_representation_type", "functional_distance_window"])
    )

    long_distance = readiness.loc[readiness["long_distance_review_flag"].eq(True)].copy()
    long_distance_review = long_distance.sort_values(
        ["reference_signal_id", "bin_midpoint_ft_from_reference_signal", "crash_id"],
        ascending=[True, False, True],
    )
    ambiguous_summary = pd.concat(
        [
            _group_count(ambiguous, ["ambiguity_reason"], "ambiguous_crash_count").assign(summary_type="reason"),
            _group_count(ambiguous, ["candidate_signal_relative_directions"], "ambiguous_crash_count").assign(summary_type="candidate_signal_relative_directions"),
            _group_count(ambiguous, ["candidate_catchment_count"], "ambiguous_crash_count").assign(summary_type="candidate_catchment_count"),
        ],
        ignore_index=True,
        sort=False,
    )
    unresolved_summary = _group_count(unresolved, ["unresolved_reason"], "unresolved_crash_count")

    total = len(readiness)
    downstream = int(readiness["signal_relative_direction"].eq(DOWNSTREAM).sum())
    upstream = int(readiness["signal_relative_direction"].eq(UPSTREAM).sum())
    divided = int(readiness["roadway_representation_type"].eq(DIVIDED).sum())
    undivided = int(readiness["roadway_representation_type"].eq(UNDIVIDED).sum())
    core = int(readiness["functional_window_500ft"].sum())
    standard = int(readiness["functional_window_1000ft"].sum())
    extended = int(readiness["functional_window_2500ft"].sum())
    long_count = int(readiness["long_distance_review_flag"].sum())
    qa_rows = [
        {"metric": "crash_direction_fields_read_or_used", "value": False, "notes": "No raw crash fields are read."},
        {"metric": "assignment_scaffold_or_catchment_logic_changed", "value": False, "notes": "Read-only classification layer."},
        {"metric": "unique_assignments_classified", "value": total, "notes": ""},
        {"metric": "ambiguous_rows_kept_separate", "value": len(ambiguous), "notes": ""},
        {"metric": "unresolved_rows_kept_separate", "value": len(unresolved), "notes": ""},
        {"metric": "downstream_assignments", "value": downstream, "notes": ""},
        {"metric": "upstream_assignments", "value": upstream, "notes": ""},
        {"metric": "divided_assignments", "value": divided, "notes": ""},
        {"metric": "undivided_assignments", "value": undivided, "notes": ""},
        {"metric": "core_0_500ft_cumulative", "value": core, "notes": "Safest first descriptive window."},
        {"metric": "standard_0_1000ft_cumulative", "value": standard, "notes": ""},
        {"metric": "extended_0_2500ft_cumulative", "value": extended, "notes": ""},
        {"metric": "long_distance_over_5000ft_review", "value": long_count, "notes": "Assignment valid, functional relevance uncertain."},
        {"metric": "unique_assignment_crash_id_duplicates", "value": int(readiness["crash_id"].duplicated().sum()), "notes": "Expected 0."},
        {"metric": "ambiguous_in_readiness_rows", "value": int(readiness["crash_id"].isin(set(ambiguous["crash_id"])).sum()), "notes": "Expected 0."},
        {"metric": "unresolved_in_readiness_rows", "value": int(readiness["crash_id"].isin(set(unresolved["crash_id"])).sum()), "notes": "Expected 0."},
    ]
    summary = pd.DataFrame(qa_rows)

    top_long_signal = _group_count(long_distance, ["reference_signal_id"], "long_distance_crash_count").head(20)
    long_by_anchor = _group_count(long_distance, ["far_anchor_type"], "long_distance_crash_count")
    long_by_representation = _group_count(long_distance, ["roadway_representation_type"], "long_distance_crash_count")
    long_by_segment = _group_count(long_distance, ["reference_directional_segment_id"], "long_distance_crash_count").head(50)
    long_distance_review = long_distance_review.merge(
        top_long_signal.rename(columns={"long_distance_crash_count": "reference_signal_long_distance_count"}),
        on="reference_signal_id",
        how="left",
    )

    window_lines = [f"- {row.analysis_readiness_class} / {row.functional_distance_window}: {row.crash_count}" for row in by_window.itertuples(index=False)]
    direction_window_lines = [f"- {row.analysis_readiness_class} / {row.functional_distance_window}: downstream {row.downstream}, upstream {row.upstream}" for row in by_direction_window.itertuples(index=False)]
    rep_window_lines = [f"- {row.roadway_representation_type} / {row.analysis_readiness_class} / {row.functional_distance_window}: {row.crash_count}" for row in by_representation_window.itertuples(index=False)]
    top_long_lines = [f"- {row.reference_signal_id}: {row.long_distance_crash_count}" for row in top_long_signal.itertuples(index=False)]
    findings = "\n".join(
        [
            "# Crash Directional Assignment Analysis Readiness",
            "",
            "## Bounded Question",
            "",
            "Classify uniquely assigned directional crashes into conservative analysis-readiness windows. This is assignment-only filtering and not final crash analysis.",
            "",
            "## QA",
            "",
            "- Crash direction fields read or used: False",
            "- Assignment/scaffold/catchment logic changed: False",
            f"- Unique assignments classified: {total}",
            f"- Ambiguous kept separate: {len(ambiguous)}",
            f"- Unresolved kept separate: {len(unresolved)}",
            "",
            "## Window Counts",
            "",
            *(window_lines or ["- none"]),
            "",
            "## Downstream/Upstream By Window",
            "",
            *(direction_window_lines or ["- none"]),
            "",
            "## Divided/Undivided By Window",
            "",
            *(rep_window_lines or ["- none"]),
            "",
            "## Long-Distance Review",
            "",
            f"- Over 5000 ft review rows: {long_count}",
            *(top_long_lines or ["- none"]),
            "",
            "## Recommendation",
            "",
            "The safest first descriptive upstream/downstream subset is `core_0_500ft` / `include_core_summary`, with `standard_0_1000ft` suitable as a next conservative summary and `extended_0_2500ft` reserved for sensitivity. Rows over 2500 ft should remain assignment-only or review-focused until functional relevance is reviewed.",
            "",
        ]
    )

    outputs = {
        "by_crash_csv": out_dir / "crash_directional_assignment_readiness_by_crash.csv",
        "summary_csv": out_dir / "crash_directional_assignment_readiness_summary.csv",
        "by_window_csv": out_dir / "assignments_by_functional_distance_window.csv",
        "by_signal_window_csv": out_dir / "assignments_by_reference_signal_and_window.csv",
        "by_direction_window_csv": out_dir / "assignments_by_signal_relative_direction_and_window.csv",
        "by_representation_window_csv": out_dir / "assignments_by_roadway_representation_and_window.csv",
        "long_distance_review_csv": out_dir / "long_distance_assignment_review_queue.csv",
        "ambiguous_summary_csv": out_dir / "ambiguous_assignment_readiness_summary.csv",
        "unresolved_summary_csv": out_dir / "unresolved_assignment_readiness_summary.csv",
        "findings_md": out_dir / "crash_directional_assignment_readiness_findings.md",
        "manifest_json": out_dir / "crash_directional_assignment_readiness_manifest.json",
    }
    _write_csv(readiness_out, outputs["by_crash_csv"])
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(by_window, outputs["by_window_csv"])
    _write_csv(by_signal_window, outputs["by_signal_window_csv"])
    _write_csv(by_direction_window, outputs["by_direction_window_csv"])
    _write_csv(by_representation_window, outputs["by_representation_window_csv"])
    _write_csv(long_distance_review[[c for c in [
        "crash_id",
        "reference_signal_id",
        "reference_signal_long_distance_count",
        "far_anchor_type",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_midpoint_ft_from_reference_signal",
        "analysis_readiness_class",
        "recommended_use",
    ] if c in long_distance_review.columns]], outputs["long_distance_review_csv"])
    _write_csv(ambiguous_summary, outputs["ambiguous_summary_csv"])
    _write_csv(unresolved_summary, outputs["unresolved_summary_csv"])
    _write_text(findings, outputs["findings_md"])

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only directional assignment analysis-readiness classification",
        "assignment_only_not_final_crash_analysis": True,
        "inputs": {
            "assignments": str(assignment_dir / ASSIGNMENTS_FILE),
            "ambiguous": str(assignment_dir / AMBIGUOUS_FILE),
            "unresolved": str(assignment_dir / UNRESOLVED_FILE),
            "assignment_qa_folder": str(qa_dir),
            "catchment_index": str(catchment_dir / CATCHMENT_INDEX_FILE),
            "usable_segments": str(scaffold_dir / USABLE_SEGMENTS_FILE),
            "usable_bins": str(scaffold_dir / USABLE_BINS_FILE),
        },
        "method": {
            "crash_direction_fields_read_or_used": False,
            "assignment_scaffold_or_catchment_logic_changed": False,
            "crash_distributions_used": False,
            "windows_ft": WINDOWS,
        },
        "qa": {row["metric"]: row["value"] for row in qa_rows},
        "long_distance_summaries": {
            "by_reference_signal_top20": top_long_signal.to_dict(orient="records"),
            "by_far_anchor_type": long_by_anchor.to_dict(orient="records"),
            "by_roadway_representation_type": long_by_representation.to_dict(orient="records"),
            "by_segment_top50": long_by_segment.to_dict(orient="records"),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify directional crash assignments into conservative analysis-readiness windows.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_crash_directional_assignment_analysis_readiness(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
