from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .crs_utils import CATCHMENT_CRS_METADATA_FILE, coordinate_profile, crs_sanity_frame


OUTPUT_ROOT = Path("work/output/roadway_graph")
ASSIGNMENT_INPUT_DIR = Path("review/current/crash_directional_catchment_assignment_prototype")
CATCHMENT_INPUT_DIR = Path("review/current/reference_signal_directional_bin_catchments")
SCAFFOLD_INPUT_DIR = Path("review/current/reference_signal_directional_scaffold_qa")
QA_OUTPUT_DIR = Path("review/current/crash_directional_catchment_assignment_qa")

ASSIGNMENTS_FILE = "crash_directional_catchment_assignments.csv"
AMBIGUOUS_FILE = "crash_directional_catchment_ambiguous.csv"
UNRESOLVED_FILE = "crash_directional_catchment_unresolved.csv"
SUMMARY_FILE = "crash_directional_catchment_assignment_summary.csv"
CATCHMENT_INDEX_FILE = "directional_bin_catchment_index.csv"
CATCHMENT_GEOJSON_FILE = "directional_bin_catchment_polygons.geojson"
CATCHMENT_CRS_METADATA = CATCHMENT_CRS_METADATA_FILE
USABLE_SEGMENTS_FILE = "directional_scaffold_prototype_usable_segments.csv"
USABLE_BINS_FILE = "directional_scaffold_prototype_usable_bins_50ft.csv"

DOWNSTREAM = "downstream_of_reference_signal"
UPSTREAM = "upstream_of_reference_signal"
DIVIDED = "divided_physical_carriageway"
UNDIVIDED = "undivided_centerline_pseudo_direction"


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


def _distance_band(distance_ft: float) -> str:
    if pd.isna(distance_ft):
        return "unknown"
    if distance_ft <= 250:
        return "0000_to_0250ft"
    if distance_ft <= 500:
        return "0250_to_0500ft"
    if distance_ft <= 1000:
        return "0500_to_1000ft"
    if distance_ft <= 1500:
        return "1000_to_1500ft"
    if distance_ft <= 2500:
        return "1500_to_2500ft"
    if distance_ft <= 5000:
        return "2500_to_5000ft"
    return "over_5000ft"


def _group_count(frame: pd.DataFrame, columns: list[str], count_name: str = "crash_count") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*columns, count_name])
    return frame.groupby(columns, dropna=False).size().reset_index(name=count_name).sort_values(count_name, ascending=False)


def _balance(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*columns, "downstream", "upstream", "total_assigned", "downstream_share", "upstream_share", "absolute_imbalance", "imbalance_flag"])
    grouped = frame.groupby(columns + ["signal_relative_direction"], dropna=False).size().unstack(fill_value=0)
    for direction in [DOWNSTREAM, UPSTREAM]:
        if direction not in grouped.columns:
            grouped[direction] = 0
    out = grouped.reset_index().rename(columns={DOWNSTREAM: "downstream", UPSTREAM: "upstream"})
    out["total_assigned"] = out["downstream"] + out["upstream"]
    out["downstream_share"] = (out["downstream"] / out["total_assigned"]).where(out["total_assigned"].ne(0), 0).round(6)
    out["upstream_share"] = (out["upstream"] / out["total_assigned"]).where(out["total_assigned"].ne(0), 0).round(6)
    out["absolute_imbalance"] = (out["downstream"] - out["upstream"]).abs()
    out["imbalance_flag"] = "balanced_or_low_count"
    out.loc[(out["total_assigned"].ge(10)) & ((out["downstream_share"].ge(0.9)) | (out["upstream_share"].ge(0.9))), "imbalance_flag"] = "extreme_90_10_or_more"
    return out.sort_values(["absolute_imbalance", "total_assigned"], ascending=False)


def _enrich_assignments(assignments: pd.DataFrame, catchment_index: pd.DataFrame, bins: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    catchment_cols = [
        "catchment_id",
        "catchment_status",
        "side_relative_to_reference_to_anchor",
        "catchment_confidence",
        "catchment_blocker_reason",
    ]
    bin_cols = [
        "reference_directional_bin_id",
        "far_anchor_type",
        "bin_midpoint_ft_from_reference_signal",
        "direction_confidence",
        "review_flag",
    ]
    segment_cols = ["reference_directional_segment_id", "far_anchor_type", "segment_length_ft", "roadway_role_class"]
    out = assignments.merge(
        catchment_index[[column for column in catchment_cols if column in catchment_index.columns]],
        on="catchment_id",
        how="left",
        suffixes=("", "_catchment"),
    )
    out = out.merge(
        bins[[column for column in bin_cols if column in bins.columns]],
        on="reference_directional_bin_id",
        how="left",
        suffixes=("", "_bin"),
    )
    out = out.merge(
        segments[[column for column in segment_cols if column in segments.columns]],
        on="reference_directional_segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    if "far_anchor_type" not in out.columns and "far_anchor_type_segment" in out.columns:
        out["far_anchor_type"] = out["far_anchor_type_segment"]
    elif "far_anchor_type_segment" in out.columns:
        out["far_anchor_type"] = out["far_anchor_type"].where(out["far_anchor_type"].astype(str).ne(""), out["far_anchor_type_segment"])
    midpoint = _num(out, "bin_midpoint_ft_from_reference_signal")
    missing_midpoint = midpoint.isna() | midpoint.eq(0)
    midpoint = midpoint.where(~missing_midpoint, (_num(out, "bin_start_ft_from_reference_signal") + _num(out, "bin_end_ft_from_reference_signal")) / 2.0)
    out["distance_midpoint_ft_from_reference_signal"] = midpoint
    out["distance_band_from_reference_signal"] = out["distance_midpoint_ft_from_reference_signal"].map(_distance_band)
    return out


def _explode_ambiguous_candidates(ambiguous: pd.DataFrame, catchment_index: pd.DataFrame) -> pd.DataFrame:
    if ambiguous.empty:
        return pd.DataFrame()
    rows = []
    for row in ambiguous.itertuples(index=False):
        for catchment_id in str(row.candidate_catchment_ids).split("|"):
            if catchment_id:
                rows.append({"crash_id": row.crash_id, "catchment_id": catchment_id})
    exploded = pd.DataFrame(rows)
    if exploded.empty:
        return exploded
    keep = [
        "catchment_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "roadway_representation_type",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "side_relative_to_reference_to_anchor",
        "catchment_status",
    ]
    return exploded.merge(catchment_index[[column for column in keep if column in catchment_index.columns]], on="catchment_id", how="left")


def _ambiguous_qa(ambiguous: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if ambiguous.empty:
        empty = pd.DataFrame()
        return empty, empty
    frame = ambiguous.copy()
    frame["same_signal_vs_multiple_reference_signals"] = "unknown"
    frame.loc[_num(frame, "candidate_reference_signal_count").eq(1), "same_signal_vs_multiple_reference_signals"] = "same_reference_signal"
    frame.loc[_num(frame, "candidate_reference_signal_count").gt(1), "same_signal_vs_multiple_reference_signals"] = "multiple_reference_signals"
    frame["same_bin_vs_adjacent_bins"] = "unknown"
    if not candidates.empty and "bin_index_from_reference_signal" in candidates.columns:
        bin_scope = candidates.copy()
        bin_scope["_bin_index"] = pd.to_numeric(bin_scope["bin_index_from_reference_signal"], errors="coerce")
        bin_scope = (
            bin_scope.groupby("crash_id", dropna=False)
            .agg(candidate_bin_index_count=("_bin_index", "nunique"), min_bin_index=("_bin_index", "min"), max_bin_index=("_bin_index", "max"))
            .reset_index()
        )
        bin_scope["same_bin_vs_adjacent_bins"] = "multiple_nonadjacent_bins"
        bin_scope.loc[bin_scope["candidate_bin_index_count"].eq(1), "same_bin_vs_adjacent_bins"] = "same_bin"
        bin_scope.loc[
            bin_scope["candidate_bin_index_count"].gt(1) & (bin_scope["max_bin_index"] - bin_scope["min_bin_index"]).le(1),
            "same_bin_vs_adjacent_bins",
        ] = "adjacent_bins"
        frame = frame.merge(bin_scope[["crash_id", "same_bin_vs_adjacent_bins"]], on="crash_id", how="left", suffixes=("", "_computed"))
        frame["same_bin_vs_adjacent_bins"] = frame["same_bin_vs_adjacent_bins_computed"].where(
            frame["same_bin_vs_adjacent_bins_computed"].fillna("").astype(str).ne(""),
            frame["same_bin_vs_adjacent_bins"],
        )
        frame = frame.drop(columns=["same_bin_vs_adjacent_bins_computed"], errors="ignore")
    else:
        frame.loc[_num(frame, "candidate_bin_count").eq(1), "same_bin_vs_adjacent_bins"] = "same_bin"
        frame.loc[_num(frame, "candidate_bin_count").gt(1), "same_bin_vs_adjacent_bins"] = "multiple_bins"
    summary_parts = [
        _group_count(frame, ["candidate_catchment_count"], "ambiguous_crash_count").assign(summary_type="candidate_catchment_count"),
        _group_count(frame, ["candidate_signal_relative_directions"], "ambiguous_crash_count").assign(summary_type="signal_relative_direction_set"),
        _group_count(frame, ["same_signal_vs_multiple_reference_signals"], "ambiguous_crash_count").assign(summary_type="reference_signal_scope"),
        _group_count(frame, ["same_bin_vs_adjacent_bins"], "ambiguous_crash_count").assign(summary_type="bin_scope"),
    ]
    if not candidates.empty:
        rep_sets = candidates.groupby("crash_id")["roadway_representation_type"].apply(lambda values: "|".join(sorted(set(values.astype(str))))).reset_index(name="candidate_roadway_representation_types")
        signal_counts = candidates.groupby(["reference_signal_id"], dropna=False)["crash_id"].nunique().reset_index(name="ambiguous_crash_count").sort_values("ambiguous_crash_count", ascending=False)
        summary_parts.append(_group_count(rep_sets, ["candidate_roadway_representation_types"], "ambiguous_crash_count").assign(summary_type="roadway_representation_type_set"))
    else:
        signal_counts = pd.DataFrame(columns=["reference_signal_id", "ambiguous_crash_count"])
    summary = pd.concat(summary_parts, ignore_index=True, sort=False)
    top_cases = frame.sort_values(["candidate_catchment_count", "candidate_reference_signal_count", "crash_id"], ascending=[False, False, True]).head(200)
    top_signals = signal_counts.head(50).assign(record_type="top_ambiguous_reference_signal")
    top_cases = pd.concat([top_cases.assign(record_type="top_ambiguous_crash"), top_signals], ignore_index=True, sort=False)
    return summary, top_cases


def _crs_sanity(output_root: Path, assignment_summary: pd.DataFrame) -> pd.DataFrame:
    geojson_path = output_root / CATCHMENT_INPUT_DIR / CATCHMENT_GEOJSON_FILE
    metadata_path = output_root / CATCHMENT_INPUT_DIR / CATCHMENT_CRS_METADATA
    rows = []
    handling = assignment_summary.loc[assignment_summary["metric"].eq("catchment_crs_handling"), "value"]
    handling_value = handling.iloc[0] if not handling.empty else ""
    authoritative = assignment_summary.loc[assignment_summary["metric"].eq("catchment_authoritative_crs"), "value"]
    authoritative_value = authoritative.iloc[0] if not authoritative.empty else ""
    if geojson_path.exists():
        catchments = gpd.read_file(geojson_path)
        rows.append(coordinate_profile(catchments, str(geojson_path)))
        out = crs_sanity_frame(rows, authoritative_crs=authoritative_value or "EPSG:3968")
        out["catchment_crs_handling"] = handling_value
        out["metadata_file"] = str(metadata_path)
        out["recommendation"] = "Use the shared catchment CRS metadata convention; no assignment-local CRS override should be needed."
        return out
    else:
        rows.append(
            {
                "dataset": str(geojson_path),
                "crs": "missing",
                "catchment_crs_handling": handling_value,
                "recommendation": "Catchment GeoJSON was unavailable for CRS QA.",
            }
        )
    return pd.DataFrame(rows)


def build_crash_directional_assignment_qa(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    assignment_dir = output_root / ASSIGNMENT_INPUT_DIR
    catchment_dir = output_root / CATCHMENT_INPUT_DIR
    scaffold_dir = output_root / SCAFFOLD_INPUT_DIR
    out_dir = output_root / QA_OUTPUT_DIR

    assignments = _read_csv(assignment_dir / ASSIGNMENTS_FILE)
    ambiguous = _read_csv(assignment_dir / AMBIGUOUS_FILE)
    unresolved = _read_csv(assignment_dir / UNRESOLVED_FILE)
    assignment_summary = _read_csv(assignment_dir / SUMMARY_FILE)
    catchment_index = _read_csv(catchment_dir / CATCHMENT_INDEX_FILE)
    segments = _read_csv(scaffold_dir / USABLE_SEGMENTS_FILE)
    bins = _read_csv(scaffold_dir / USABLE_BINS_FILE)

    enriched = _enrich_assignments(assignments, catchment_index, bins, segments)
    ambiguous_candidates = _explode_ambiguous_candidates(ambiguous, catchment_index)

    by_signal = _group_count(enriched, ["reference_signal_id"])
    by_direction = _group_count(enriched, ["signal_relative_direction"])
    by_representation = _group_count(enriched, ["roadway_representation_type"])
    by_bin = _group_count(enriched, ["bin_index_from_reference_signal"])
    by_distance = _group_count(enriched, ["distance_band_from_reference_signal"])
    by_catchment_method = _group_count(enriched, ["catchment_method"])
    by_far_anchor_type = _group_count(enriched, ["far_anchor_type"])
    balance_by_signal = _balance(enriched, ["reference_signal_id"])
    balance_by_representation = _balance(enriched, ["roadway_representation_type"])
    balance_by_bin_distance = _balance(enriched, ["bin_index_from_reference_signal", "distance_band_from_reference_signal"])

    undivided = enriched.loc[enriched["roadway_representation_type"].eq(UNDIVIDED)].copy()
    divided = enriched.loc[enriched["roadway_representation_type"].eq(DIVIDED)].copy()
    undivided_qa = pd.concat(
        [
            _group_count(undivided, ["reference_signal_id"]).assign(summary_type="by_reference_signal"),
            _group_count(undivided, ["bin_index_from_reference_signal"]).assign(summary_type="by_bin_index"),
            _group_count(undivided, ["side_relative_to_reference_to_anchor"]).assign(summary_type="by_catchment_side"),
            _balance(undivided, ["reference_signal_id"]).assign(summary_type="downstream_upstream_balance_by_signal"),
        ],
        ignore_index=True,
        sort=False,
    )
    divided_qa = pd.concat(
        [
            _group_count(divided, ["reference_signal_id"]).assign(summary_type="by_reference_signal"),
            _group_count(divided, ["bin_index_from_reference_signal"]).assign(summary_type="by_bin_index"),
            _balance(divided, ["reference_signal_id"]).assign(summary_type="downstream_upstream_balance_by_signal"),
        ],
        ignore_index=True,
        sort=False,
    )
    ambiguous_qa, ambiguous_top = _ambiguous_qa(ambiguous, ambiguous_candidates)
    unresolved_summary = _group_count(unresolved, ["unresolved_reason"], "crash_count")
    crs_sanity = _crs_sanity(output_root, assignment_summary)

    unique_count = len(enriched)
    downstream_count = int(enriched["signal_relative_direction"].eq(DOWNSTREAM).sum())
    upstream_count = int(enriched["signal_relative_direction"].eq(UPSTREAM).sum())
    divided_count = int(enriched["roadway_representation_type"].eq(DIVIDED).sum())
    undivided_count = int(enriched["roadway_representation_type"].eq(UNDIVIDED).sum())
    ambiguous_count = len(ambiguous)
    unresolved_count = len(unresolved)
    nonusable_assigned = int(_text(enriched, "catchment_status").ne("usable").sum())
    inherited_not_true = int(_text(enriched, "inherited_direction_from_catchment").str.lower().ne("true").sum())
    status_not_assigned = int(_text(enriched, "assignment_status").ne("assigned_unique_catchment").sum())
    duplicate_unique_crash_ids = int(enriched["crash_id"].duplicated().sum())
    ambiguous_overlap = int(enriched["crash_id"].isin(set(ambiguous["crash_id"])).sum())
    unresolved_overlap = int(enriched["crash_id"].isin(set(unresolved["crash_id"])).sum())

    qa_rows = [
        {"metric": "crash_direction_fields_read_or_used", "value": False, "notes": "This QA reads assignment IDs and catchment/scaffold fields only."},
        {"metric": "scaffold_catchment_or_assignment_logic_changed", "value": False, "notes": "Read-only QA module."},
        {"metric": "total_unique_assignments", "value": unique_count, "notes": "Rows in unique assignment output."},
        {"metric": "assigned_downstream", "value": downstream_count, "notes": ""},
        {"metric": "assigned_upstream", "value": upstream_count, "notes": ""},
        {"metric": "assigned_divided_physical", "value": divided_count, "notes": ""},
        {"metric": "assigned_undivided_pseudo_direction", "value": undivided_count, "notes": ""},
        {"metric": "ambiguous_crashes", "value": ambiguous_count, "notes": ""},
        {"metric": "unresolved_crashes", "value": unresolved_count, "notes": ""},
        {"metric": "assigned_divided_plus_undivided_equals_unique", "value": divided_count + undivided_count == unique_count, "notes": ""},
        {"metric": "assigned_downstream_plus_upstream_equals_unique", "value": downstream_count + upstream_count == unique_count, "notes": ""},
        {"metric": "assigned_rows_with_nonusable_catchment_status", "value": nonusable_assigned, "notes": "Expected 0."},
        {"metric": "assigned_rows_not_inherited_from_catchment", "value": inherited_not_true, "notes": "Expected 0."},
        {"metric": "assigned_rows_with_unexpected_assignment_status", "value": status_not_assigned, "notes": "Expected 0."},
        {"metric": "duplicate_unique_assignment_crash_ids", "value": duplicate_unique_crash_ids, "notes": "Expected 0."},
        {"metric": "ambiguous_crashes_in_unique_assignments", "value": ambiguous_overlap, "notes": "Expected 0."},
        {"metric": "unresolved_crashes_in_unique_assignments", "value": unresolved_overlap, "notes": "Expected 0."},
    ]
    qa_summary = pd.DataFrame(qa_rows)

    top_signal_lines = [f"- {row.reference_signal_id}: {row.crash_count}" for row in by_signal.head(10).itertuples(index=False)]
    top_ambiguous_signal_frame = (
        ambiguous_candidates.groupby("reference_signal_id")["crash_id"].nunique().reset_index(name="ambiguous_crash_count").sort_values("ambiguous_crash_count", ascending=False)
        if not ambiguous_candidates.empty
        else pd.DataFrame(columns=["reference_signal_id", "ambiguous_crash_count"])
    )
    top_ambiguous_lines = [f"- {row.reference_signal_id}: {row.ambiguous_crash_count}" for row in top_ambiguous_signal_frame.head(10).itertuples(index=False)]
    distance_lines = [f"- {row.distance_band_from_reference_signal}: {row.crash_count}" for row in by_distance.head(10).itertuples(index=False)]
    ambiguity_lines = []
    if not ambiguous_qa.empty:
        subset = ambiguous_qa.loc[ambiguous_qa["summary_type"].isin(["candidate_catchment_count", "signal_relative_direction_set", "reference_signal_scope", "bin_scope"])].head(20)
        for row in subset.itertuples(index=False):
            label = next((getattr(row, col) for col in ["candidate_catchment_count", "candidate_signal_relative_directions", "same_signal_vs_multiple_reference_signals", "same_bin_vs_adjacent_bins"] if hasattr(row, col) and str(getattr(row, col)) != "nan"), "")
            ambiguity_lines.append(f"- {row.summary_type}: {label} = {row.ambiguous_crash_count}")
    crs_line = "CRS QA unavailable."
    if not crs_sanity.empty:
        row = crs_sanity.iloc[0]
        crs_line = f"Catchment GeoJSON CRS `{row.get('crs', '')}` has projected-looking coordinate ranges: {row.get('coordinates_appear_projected', '')}; shared CRS handling: `{row.get('catchment_crs_handling', '')}`."

    findings = "\n".join(
        [
            "# Crash Directional Catchment Assignment QA",
            "",
            "## Bounded Question",
            "",
            "Read-only QA for crash-to-directional-catchment assignment outputs. This remains assignment-only and is not final crash analysis.",
            "",
            "## QA Invariants",
            "",
            f"- Crash direction fields read or used: False",
            f"- Scaffold/catchment/assignment logic changed: False",
            f"- Assigned divided + undivided equals unique: {divided_count + undivided_count == unique_count}",
            f"- Assigned downstream + upstream equals unique: {downstream_count + upstream_count == unique_count}",
            f"- Non-usable catchments in assignments: {nonusable_assigned}",
            f"- Ambiguous rows included in unique assignments: {ambiguous_overlap}",
            f"- Unresolved rows included in unique assignments: {unresolved_overlap}",
            "",
            "## Assignment Counts",
            "",
            f"- Total unique assignments: {unique_count}",
            f"- Downstream: {downstream_count}",
            f"- Upstream: {upstream_count}",
            f"- Divided physical: {divided_count}",
            f"- Undivided pseudo-direction: {undivided_count}",
            f"- Ambiguous: {ambiguous_count}",
            f"- Unresolved: {unresolved_count}",
            "",
            "## Top Reference Signals",
            "",
            *(top_signal_lines or ["- none"]),
            "",
            "## Top Ambiguous Reference Signals",
            "",
            *(top_ambiguous_lines or ["- none"]),
            "",
            "## Distance Pattern",
            "",
            *(distance_lines or ["- none"]),
            "",
            "## Ambiguity Pattern",
            "",
            *(ambiguity_lines or ["- none"]),
            "",
            "## CRS QA",
            "",
            crs_line,
            "",
        ]
    )

    outputs = {
        "summary_csv": out_dir / "crash_directional_assignment_qa_summary.csv",
        "by_reference_signal_csv": out_dir / "assignments_by_reference_signal.csv",
        "by_signal_relative_direction_csv": out_dir / "assignments_by_signal_relative_direction.csv",
        "by_roadway_representation_type_csv": out_dir / "assignments_by_roadway_representation_type.csv",
        "by_bin_index_csv": out_dir / "assignments_by_bin_index.csv",
        "by_distance_band_csv": out_dir / "assignments_by_distance_band_from_reference.csv",
        "by_catchment_method_csv": out_dir / "assignments_by_catchment_method.csv",
        "by_far_anchor_type_csv": out_dir / "assignments_by_far_anchor_type.csv",
        "balance_by_signal_csv": out_dir / "assignments_downstream_upstream_balance_by_signal.csv",
        "balance_by_representation_csv": out_dir / "assignments_downstream_upstream_balance_by_roadway_representation_type.csv",
        "balance_by_bin_distance_csv": out_dir / "assignments_downstream_upstream_balance_by_bin_index_distance_band.csv",
        "undivided_qa_csv": out_dir / "undivided_assignment_qa.csv",
        "divided_qa_csv": out_dir / "divided_assignment_qa.csv",
        "ambiguous_qa_csv": out_dir / "ambiguous_assignment_qa.csv",
        "ambiguous_top_cases_csv": out_dir / "ambiguous_assignment_top_cases.csv",
        "unresolved_summary_csv": out_dir / "unresolved_assignment_summary.csv",
        "crs_sanity_csv": out_dir / "assignment_crs_sanity_qa.csv",
        "findings_md": out_dir / "crash_directional_assignment_qa_findings.md",
        "manifest_json": out_dir / "crash_directional_assignment_qa_manifest.json",
    }
    _write_csv(qa_summary, outputs["summary_csv"])
    _write_csv(by_signal, outputs["by_reference_signal_csv"])
    _write_csv(by_direction, outputs["by_signal_relative_direction_csv"])
    _write_csv(by_representation, outputs["by_roadway_representation_type_csv"])
    _write_csv(by_bin, outputs["by_bin_index_csv"])
    _write_csv(by_distance, outputs["by_distance_band_csv"])
    _write_csv(by_catchment_method, outputs["by_catchment_method_csv"])
    _write_csv(by_far_anchor_type, outputs["by_far_anchor_type_csv"])
    _write_csv(balance_by_signal, outputs["balance_by_signal_csv"])
    _write_csv(balance_by_representation, outputs["balance_by_representation_csv"])
    _write_csv(balance_by_bin_distance, outputs["balance_by_bin_distance_csv"])
    _write_csv(undivided_qa, outputs["undivided_qa_csv"])
    _write_csv(divided_qa, outputs["divided_qa_csv"])
    _write_csv(ambiguous_qa, outputs["ambiguous_qa_csv"])
    _write_csv(ambiguous_top, outputs["ambiguous_top_cases_csv"])
    _write_csv(unresolved_summary, outputs["unresolved_summary_csv"])
    _write_csv(crs_sanity, outputs["crs_sanity_csv"])
    _write_text(findings, outputs["findings_md"])

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only QA for crash directional catchment assignment outputs",
        "assignment_only_not_final_crash_analysis": True,
        "inputs": {
            "assignments": str(assignment_dir / ASSIGNMENTS_FILE),
            "ambiguous": str(assignment_dir / AMBIGUOUS_FILE),
            "unresolved": str(assignment_dir / UNRESOLVED_FILE),
            "assignment_summary": str(assignment_dir / SUMMARY_FILE),
            "catchment_index": str(catchment_dir / CATCHMENT_INDEX_FILE),
            "catchment_geojson_for_crs_qa": str(catchment_dir / CATCHMENT_GEOJSON_FILE),
            "catchment_crs_metadata": str(catchment_dir / CATCHMENT_CRS_METADATA),
            "usable_segments": str(scaffold_dir / USABLE_SEGMENTS_FILE),
            "usable_bins": str(scaffold_dir / USABLE_BINS_FILE),
        },
        "method": {
            "crash_direction_fields_read_or_used": False,
            "scaffold_catchment_or_assignment_logic_changed": False,
            "crash_distributions_used": False,
        },
        "qa": {row["metric"]: row["value"] for row in qa_rows},
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only QA summaries for crash directional catchment assignments.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_crash_directional_assignment_qa(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
