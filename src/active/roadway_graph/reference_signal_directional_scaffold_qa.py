from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
INPUT_DIR = Path("review/current/reference_signal_directional_scaffold")
QA_DIR = Path("review/current/reference_signal_directional_scaffold_qa")

SEGMENTS_FILE = "reference_signal_directional_segment_candidates.csv"
BINS_FILE = "reference_signal_directional_bins_50ft_candidates.csv"
NODE_INVENTORY_FILE = "reference_signal_node_inventory.csv"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _is_usable_segments(segments: pd.DataFrame) -> pd.Series:
    no_review = _text(segments, "review_flag").str.upper().ne("TRUE")
    no_blocker = _text(segments, "blocker_reason").eq("")
    accepted_representation = _text(segments, "roadway_representation_type").isin(
        ["undivided_centerline_pseudo_direction", "divided_physical_carriageway"]
    )
    no_low_recovery = _text(segments, "recovery_status").ne("recovered_low_review_only")
    no_unknown_role = _text(segments, "roadway_role_class").ne("unknown_review")
    accepted_divided = ~_text(segments, "roadway_representation_type").eq("divided_physical_carriageway") | _text(
        segments, "divided_pairing_status"
    ).eq("paired")
    return no_review & no_blocker & accepted_representation & no_low_recovery & no_unknown_role & accepted_divided


def _exclusion_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    if str(row.get("review_flag", "")).upper() == "TRUE":
        reasons.append("review_flag_true")
    blocker = str(row.get("blocker_reason", ""))
    if blocker:
        reasons.extend([reason for reason in blocker.split("|") if reason])
    if str(row.get("roadway_representation_type", "")) not in {
        "undivided_centerline_pseudo_direction",
        "divided_physical_carriageway",
    }:
        reasons.append("roadway_representation_not_prototype_usable")
    if str(row.get("recovery_status", "")) == "recovered_low_review_only":
        reasons.append("low_confidence_divided_recovery_review_only")
    if str(row.get("roadway_role_class", "")) == "unknown_review":
        reasons.append("unknown_roadway_role")
    if str(row.get("roadway_representation_type", "")) == "divided_physical_carriageway" and str(
        row.get("divided_pairing_status", "")
    ) != "paired":
        reasons.append("divided_physical_not_accepted_pair")
    return "|".join(dict.fromkeys(reasons)) or "not_excluded"


def _id_uniqueness_qa(segments: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def add(record_type: str, id_column: str, frame: pd.DataFrame) -> None:
        total = len(frame)
        nonblank = int(_text(frame, id_column).ne("").sum()) if id_column in frame.columns else 0
        unique = int(_text(frame, id_column).nunique()) if id_column in frame.columns else 0
        duplicate = max(0, nonblank - unique)
        rows.append(
            {
                "record_type": record_type,
                "id_column": id_column,
                "row_count": total,
                "nonblank_id_count": nonblank,
                "unique_id_count": unique,
                "duplicate_id_count": duplicate,
                "blank_id_count": total - nonblank,
                "qa_status": "pass" if duplicate == 0 and total == nonblank else "fail",
            }
        )

    add("segment", "reference_directional_segment_id", segments)
    add("bin", "reference_directional_bin_id", bins)
    return pd.DataFrame(rows)


def _pair_symmetry_qa(segments: pd.DataFrame, usable: pd.DataFrame) -> pd.DataFrame:
    if segments.empty:
        return pd.DataFrame()

    def qa(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "scope",
                    "reference_signal_id",
                    "far_anchor_id",
                    "far_anchor_type",
                    "directional_records",
                    "downstream_records",
                    "upstream_records",
                    "has_required_pair",
                    "paired_id_missing_rows",
                    "paired_id_not_found_rows",
                    "qa_status",
                ]
            )
        work = frame.copy()
        ids = set(_text(work, "reference_directional_segment_id"))

        def connection_key(row: pd.Series) -> str:
            segment_id = str(row.get("reference_directional_segment_id", ""))
            paired_id = str(row.get("paired_opposite_directional_segment_id", ""))
            representation = str(row.get("roadway_representation_type", ""))
            if representation == "divided_physical_carriageway" and paired_id:
                return "paired_directional_ids:" + "||".join(sorted([segment_id, paired_id]))
            return "reference_anchor:" + str(row.get("reference_signal_id", "")) + "||" + str(row.get("far_anchor_id", ""))

        work["pair_symmetry_connection_key"] = work.apply(connection_key, axis=1)
        base = (
            work.groupby(["pair_symmetry_connection_key", "reference_signal_id"], dropna=False)
            .agg(
                directional_records=("reference_directional_segment_id", "count"),
                far_anchor_ids=("far_anchor_id", lambda values: "|".join(sorted(set(str(value) for value in values if str(value))))),
                far_anchor_types=("far_anchor_type", lambda values: "|".join(sorted(set(str(value) for value in values if str(value))))),
                roadway_representation_types=(
                    "roadway_representation_type",
                    lambda values: "|".join(sorted(set(str(value) for value in values if str(value)))),
                ),
                downstream_records=(
                    "signal_relative_direction",
                    lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum()),
                ),
                upstream_records=(
                    "signal_relative_direction",
                    lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum()),
                ),
                paired_id_missing_rows=(
                    "paired_opposite_directional_segment_id",
                    lambda values: int(values.astype(str).eq("").sum()),
                ),
                paired_id_not_found_rows=(
                    "paired_opposite_directional_segment_id",
                    lambda values: int((values.astype(str).ne("") & ~values.astype(str).isin(ids)).sum()),
                ),
            )
            .reset_index()
        )
        base.insert(0, "scope", scope)
        base["has_required_pair"] = (
            (base["downstream_records"].gt(0)) & (base["upstream_records"].gt(0))
        ).map({True: "TRUE", False: "FALSE"})
        base["qa_status"] = (
            base["has_required_pair"].eq("TRUE")
            & base["paired_id_missing_rows"].eq(0)
            & base["paired_id_not_found_rows"].eq(0)
        ).map({True: "pass", False: "fail"})
        return base

    return pd.concat([qa(segments, "all_candidates"), qa(usable, "prototype_usable")], ignore_index=True)


def _bin_ordering_qa(segments: pd.DataFrame, bins: pd.DataFrame, usable: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        return pd.DataFrame()
    usable_ids = set(_text(usable, "reference_directional_segment_id"))
    segment_lengths = _num(segments, "segment_length_ft")
    length_lookup = dict(zip(_text(segments, "reference_directional_segment_id"), segment_lengths))
    rows = []
    work = bins.copy()
    work["_idx"] = _num(work, "bin_index_from_reference_signal")
    work["_start"] = _num(work, "bin_start_ft_from_reference_signal")
    work["_end"] = _num(work, "bin_end_ft_from_reference_signal")
    work["_mid"] = _num(work, "bin_midpoint_ft_from_reference_signal")
    work["_travel_idx"] = _num(work, "bin_index_in_travel_direction")
    for segment_id, group in work.groupby("reference_directional_segment_id", sort=False):
        group = group.sort_values("_idx")
        idx = list(group["_idx"].astype(int))
        starts = list(group["_start"])
        ends = list(group["_end"])
        travel = list(group["_travel_idx"].astype(int))
        start_ok = bool(idx and idx[0] == 1)
        contiguous = idx == list(range(1, len(idx) + 1))
        starts_ok = starts == sorted(starts)
        ends_gt_starts = all(e > s for s, e in zip(starts, ends))
        first_start_zero = bool(starts and abs(float(starts[0])) < 0.001)
        length = float(length_lookup.get(segment_id, 0.0) or 0.0)
        final_end = float(ends[-1]) if ends else 0.0
        length_diff = abs(final_end - length) if length > 0 else 0.0
        direction = str(group["travel_direction"].iloc[0])
        if direction == "anchor_to_reference":
            travel_ok = travel == list(range(len(travel), 0, -1))
        else:
            travel_ok = travel == list(range(1, len(travel) + 1))
        status = "pass" if all([start_ok, contiguous, starts_ok, ends_gt_starts, first_start_zero, length_diff <= 1.0, travel_ok]) else "fail"
        rows.append(
            {
                "reference_directional_segment_id": segment_id,
                "scope": "prototype_usable" if segment_id in usable_ids else "excluded_or_review",
                "travel_direction": direction,
                "signal_relative_direction": str(group["signal_relative_direction"].iloc[0]),
                "bin_count": len(group),
                "starts_at_one": "TRUE" if start_ok else "FALSE",
                "contiguous_index_from_reference": "TRUE" if contiguous else "FALSE",
                "distance_ordered_from_reference": "TRUE" if starts_ok else "FALSE",
                "first_bin_start_zero": "TRUE" if first_start_zero else "FALSE",
                "all_bin_ends_gt_starts": "TRUE" if ends_gt_starts else "FALSE",
                "segment_length_ft": round(length, 3),
                "last_bin_end_ft_from_reference": round(final_end, 3),
                "length_difference_ft": round(length_diff, 3),
                "travel_order_index_ok": "TRUE" if travel_ok else "FALSE",
                "qa_status": status,
            }
        )
    return pd.DataFrame(rows)


def _aggregate(frame: pd.DataFrame, group_columns: list[str], bins: pd.DataFrame | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    present = [column for column in group_columns if column in frame.columns]
    if not present:
        return pd.DataFrame()
    out = (
        frame.groupby(present, dropna=False)
        .agg(
            directional_segments=("reference_directional_segment_id", "count"),
            downstream_records=(
                "signal_relative_direction",
                lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum()),
            ),
            upstream_records=(
                "signal_relative_direction",
                lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum()),
            ),
            divided_physical_records=(
                "roadway_representation_type",
                lambda values: int(values.astype(str).eq("divided_physical_carriageway").sum()),
            ),
            undivided_pseudo_records=(
                "roadway_representation_type",
                lambda values: int(values.astype(str).eq("undivided_centerline_pseudo_direction").sum()),
            ),
            method_allowed_anchor_relaxation_records=(
                "anchor_relaxation_used",
                lambda values: int(values.astype(str).eq("TRUE").sum()),
            ),
        )
        .reset_index()
        .sort_values("directional_segments", ascending=False)
    )
    if bins is not None and not bins.empty:
        key = present[0] if len(present) == 1 else None
        if key and key in bins.columns:
            bin_counts = bins.groupby(key).size().rename("directional_bins").reset_index()
            out = out.merge(bin_counts, on=key, how="left")
            out["directional_bins"] = _num(out, "directional_bins").fillna(0).astype(int)
    return out


def _blocker_summary(excluded: pd.DataFrame) -> pd.DataFrame:
    if excluded.empty:
        return pd.DataFrame(columns=["exclusion_reason", "excluded_segments"])
    exploded = excluded.assign(exclusion_reason=_text(excluded, "exclusion_reason").str.split("|")).explode("exclusion_reason")
    exploded = exploded.loc[_text(exploded, "exclusion_reason").ne("")]
    return (
        exploded.groupby("exclusion_reason", dropna=False)
        .agg(
            excluded_segments=("reference_directional_segment_id", "count"),
            unique_reference_signals=("reference_signal_id", "nunique"),
            downstream_records=(
                "signal_relative_direction",
                lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum()),
            ),
            upstream_records=(
                "signal_relative_direction",
                lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum()),
            ),
        )
        .reset_index()
        .sort_values("excluded_segments", ascending=False)
    )


def _missing_true_signal_summary(nodes: pd.DataFrame, usable: pd.DataFrame) -> pd.DataFrame:
    if nodes.empty:
        return pd.DataFrame()
    usable_signals = set(_text(usable, "reference_signal_id"))
    true_nodes = nodes.loc[_text(nodes, "is_true_reference_signal").eq("TRUE")].copy()
    true_nodes["represented_in_prototype_usable_surface"] = _text(true_nodes, "signal_id").isin(usable_signals).map(
        {True: "TRUE", False: "FALSE"}
    )
    missing = true_nodes.loc[_text(true_nodes, "represented_in_prototype_usable_surface").eq("FALSE")].copy()
    if missing.empty:
        return pd.DataFrame(columns=["metric", "value", "notes"])
    rows = [
        {
            "metric": "missing_true_reference_signals_from_prototype_usable_surface",
            "value": len(missing),
            "notes": "TRUE signals with no non-review, non-blocked directional segment in the prototype usable surface.",
        }
    ]
    if "adjacent_edge_count_band" in missing.columns:
        for band, count in _text(missing, "adjacent_edge_count_band").value_counts().items():
            rows.append({"metric": f"missing_by_adjacent_edge_count_band_{band}", "value": int(count), "notes": ""})
    return pd.DataFrame(rows)


def _summary_rows(
    segments: pd.DataFrame,
    bins: pd.DataFrame,
    usable: pd.DataFrame,
    usable_bins: pd.DataFrame,
    excluded: pd.DataFrame,
    excluded_bins: pd.DataFrame,
    id_qa: pd.DataFrame,
    pair_qa: pd.DataFrame,
    bin_qa: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    add("candidate_directional_segments", len(segments))
    add("candidate_directional_bins", len(bins))
    add("prototype_usable_directional_segments", len(usable))
    add("prototype_usable_directional_bins", len(usable_bins))
    add("excluded_directional_segments", len(excluded))
    add("excluded_directional_bins", len(excluded_bins))
    add("prototype_usable_true_reference_signals", _text(usable, "reference_signal_id").nunique())
    add("prototype_usable_downstream_records", int(_text(usable, "signal_relative_direction").eq("downstream_of_reference_signal").sum()))
    add("prototype_usable_upstream_records", int(_text(usable, "signal_relative_direction").eq("upstream_of_reference_signal").sum()))
    add("prototype_usable_divided_physical_records", int(_text(usable, "roadway_representation_type").eq("divided_physical_carriageway").sum()))
    add("prototype_usable_undivided_pseudo_direction_records", int(_text(usable, "roadway_representation_type").eq("undivided_centerline_pseudo_direction").sum()))
    add(
        "prototype_usable_method_allowed_non_true_endpoint_anchor_records",
        int(_text(usable, "far_anchor_type").ne("true_signal").sum()),
        "Usable records whose far anchor is not a TRUE signal.",
    )
    add("id_uniqueness_fail_rows", int(_text(id_qa, "qa_status").eq("fail").sum()))
    usable_pair_qa = pair_qa.loc[_text(pair_qa, "scope").eq("prototype_usable")]
    add("prototype_usable_pair_symmetry_fail_rows", int(_text(usable_pair_qa, "qa_status").eq("fail").sum()))
    usable_bin_qa = bin_qa.loc[_text(bin_qa, "scope").eq("prototype_usable")]
    add("prototype_usable_bin_ordering_fail_rows", int(_text(usable_bin_qa, "qa_status").eq("fail").sum()))
    add("blocked_segments_leaked_into_usable", int(_text(usable, "blocker_reason").ne("").sum()), "Expected 0.")
    add("review_segments_leaked_into_usable", int(_text(usable, "review_flag").str.upper().eq("TRUE").sum()), "Expected 0.")
    add(
        "low_confidence_divided_recovery_rows_leaked_into_usable",
        int(_text(usable, "recovery_status").eq("recovered_low_review_only").sum()),
        "Expected 0.",
    )
    add("unknown_roadway_role_rows_leaked_into_usable", int(_text(usable, "roadway_role_class").eq("unknown_review").sum()), "Expected 0.")
    add("crash_data_read", "False")
    add("crash_assignment_outputs_read", "False")
    add("crash_direction_fields_used", "False")
    return pd.DataFrame(rows)


def _findings(summary: dict[str, int], blocker_summary: pd.DataFrame, recommendation: str) -> str:
    blockers = "None"
    if not blocker_summary.empty:
        blockers = "\n".join(
            f"- {row.exclusion_reason}: {int(row.excluded_segments)} segments"
            for row in blocker_summary.head(8).itertuples(index=False)
        )
    return f"""# Directional Scaffold QA Findings

**Status:** Read-only QA and conservative prototype usable surface for the reference-signal-centered directional scaffold.

## Bounded Question

This module validates the current directional scaffold candidates and separates non-review, non-blocked records into a prototype usable surface for later crash assignment by direction. It does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crashes, repair geometry, force divided pairs, or change scaffold construction logic.

## Prototype Usable Surface

- Prototype usable directional segments: {summary["usable_segments"]}
- Prototype usable 50-ft bins: {summary["usable_bins"]}
- TRUE reference signals represented: {summary["usable_true_signals"]}
- Usable downstream records: {summary["usable_downstream"]}
- Usable upstream records: {summary["usable_upstream"]}
- Usable divided physical records: {summary["usable_divided"]}
- Usable undivided pseudo-direction records: {summary["usable_undivided"]}
- Usable non-TRUE/non-signal/endpoint far-anchor records: {summary["usable_non_true_anchor"]}

Method-allowed anchor relaxation is retained in the usable surface when the record is otherwise non-review and non-blocked.

## Exclusions

- Excluded directional segments: {summary["excluded_segments"]}
- Excluded directional bins: {summary["excluded_bins"]}

Main exclusion reasons:

{blockers}

## QA Results

- ID uniqueness failures: {summary["id_failures"]}
- Prototype pair symmetry failures: {summary["pair_failures"]}
- Prototype bin ordering failures: {summary["bin_failures"]}
- Blocked/review/low-confidence recovery/unknown-role leakage into usable surface: {summary["leakage_failures"]}

## Recommendation

{recommendation}
"""


def build_directional_scaffold_qa(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    in_dir = output_root / INPUT_DIR
    out_dir = output_root / QA_DIR
    segments = _read_csv(in_dir / SEGMENTS_FILE)
    bins = _read_csv(in_dir / BINS_FILE)
    nodes = _read_csv(in_dir / NODE_INVENTORY_FILE)

    usable_mask = _is_usable_segments(segments)
    usable = segments.loc[usable_mask].copy()
    excluded = segments.loc[~usable_mask].copy()
    excluded["exclusion_reason"] = excluded.apply(_exclusion_reason, axis=1)
    usable_ids = set(_text(usable, "reference_directional_segment_id"))
    excluded_ids = set(_text(excluded, "reference_directional_segment_id"))
    usable_bins = bins.loc[_text(bins, "reference_directional_segment_id").isin(usable_ids)].copy()
    excluded_bins = bins.loc[_text(bins, "reference_directional_segment_id").isin(excluded_ids)].copy()

    id_qa = _id_uniqueness_qa(segments, bins)
    pair_qa = _pair_symmetry_qa(segments, usable)
    bin_qa = _bin_ordering_qa(segments, bins, usable)
    qa_signal = _aggregate(usable, ["reference_signal_id"], usable_bins)
    qa_anchor = _aggregate(usable, ["far_anchor_type"], usable_bins)
    qa_representation = _aggregate(usable, ["roadway_representation_type"], usable_bins)
    blocker_summary = _blocker_summary(excluded)
    missing_true = _missing_true_signal_summary(nodes, usable)
    summary = _summary_rows(segments, bins, usable, usable_bins, excluded, excluded_bins, id_qa, pair_qa, bin_qa)

    output_files = {
        "summary": out_dir / "directional_scaffold_qa_summary.csv",
        "usable_segments": out_dir / "directional_scaffold_prototype_usable_segments.csv",
        "usable_bins": out_dir / "directional_scaffold_prototype_usable_bins_50ft.csv",
        "excluded_segments": out_dir / "directional_scaffold_excluded_segments.csv",
        "excluded_bins": out_dir / "directional_scaffold_excluded_bins_50ft.csv",
        "pair_qa": out_dir / "directional_scaffold_pair_symmetry_qa.csv",
        "bin_qa": out_dir / "directional_scaffold_bin_ordering_qa.csv",
        "id_qa": out_dir / "directional_scaffold_id_uniqueness_qa.csv",
        "qa_signal": out_dir / "directional_scaffold_qa_by_reference_signal.csv",
        "qa_anchor": out_dir / "directional_scaffold_qa_by_anchor_type.csv",
        "qa_representation": out_dir / "directional_scaffold_qa_by_roadway_representation_type.csv",
        "blocker_summary": out_dir / "directional_scaffold_blocker_summary.csv",
        "missing_true": out_dir / "directional_scaffold_missing_true_signal_summary.csv",
        "findings": out_dir / "directional_scaffold_qa_findings.md",
        "manifest": out_dir / "directional_scaffold_qa_manifest.json",
    }

    _write_csv(summary, output_files["summary"])
    _write_csv(usable, output_files["usable_segments"])
    _write_csv(usable_bins, output_files["usable_bins"])
    _write_csv(excluded, output_files["excluded_segments"])
    _write_csv(excluded_bins, output_files["excluded_bins"])
    _write_csv(pair_qa, output_files["pair_qa"])
    _write_csv(bin_qa, output_files["bin_qa"])
    _write_csv(id_qa, output_files["id_qa"])
    _write_csv(qa_signal, output_files["qa_signal"])
    _write_csv(qa_anchor, output_files["qa_anchor"])
    _write_csv(qa_representation, output_files["qa_representation"])
    _write_csv(blocker_summary, output_files["blocker_summary"])
    _write_csv(missing_true, output_files["missing_true"])

    leakage_failures = int(
        _text(usable, "blocker_reason").ne("").sum()
        + _text(usable, "review_flag").str.upper().eq("TRUE").sum()
        + _text(usable, "recovery_status").eq("recovered_low_review_only").sum()
        + _text(usable, "roadway_role_class").eq("unknown_review").sum()
    )
    summary_counts = {
        "usable_segments": len(usable),
        "usable_bins": len(usable_bins),
        "excluded_segments": len(excluded),
        "excluded_bins": len(excluded_bins),
        "usable_true_signals": int(_text(usable, "reference_signal_id").nunique()),
        "usable_downstream": int(_text(usable, "signal_relative_direction").eq("downstream_of_reference_signal").sum()),
        "usable_upstream": int(_text(usable, "signal_relative_direction").eq("upstream_of_reference_signal").sum()),
        "usable_divided": int(_text(usable, "roadway_representation_type").eq("divided_physical_carriageway").sum()),
        "usable_undivided": int(_text(usable, "roadway_representation_type").eq("undivided_centerline_pseudo_direction").sum()),
        "usable_non_true_anchor": int(_text(usable, "far_anchor_type").ne("true_signal").sum()),
        "id_failures": int(_text(id_qa, "qa_status").eq("fail").sum()),
        "pair_failures": int(_text(pair_qa.loc[_text(pair_qa, "scope").eq("prototype_usable")], "qa_status").eq("fail").sum()),
        "bin_failures": int(_text(bin_qa.loc[_text(bin_qa, "scope").eq("prototype_usable")], "qa_status").eq("fail").sum()),
        "leakage_failures": leakage_failures,
    }
    ready = (
        summary_counts["id_failures"] == 0
        and summary_counts["pair_failures"] == 0
        and summary_counts["bin_failures"] == 0
        and leakage_failures == 0
    )
    recommendation = (
        "The prototype usable directional surface is ready for a later crash-assignment-by-direction prototype, provided that later module still remains spatial/directional-assignment only and keeps excluded rows out."
        if ready
        else "Do not use this surface for later crash assignment by direction until QA failures are resolved."
    )
    _write_text(_findings(summary_counts, blocker_summary, recommendation), output_files["findings"])

    input_files = [
        in_dir / SEGMENTS_FILE,
        in_dir / BINS_FILE,
        in_dir / NODE_INVENTORY_FILE,
        in_dir / "reference_signal_directional_scaffold_manifest.json",
        in_dir / "directional_blockers.csv",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "QA and conservative prototype usable surface for the reference-signal-centered directional scaffold.",
        "read_only": True,
        "qa_prototype_output_only": True,
        "raw_crash_data_read": False,
        "crash_assignment_outputs_read": False,
        "crash_direction_fields_used": False,
        "crash_distributions_used": False,
        "scaffold_construction_changed": False,
        "geometry_repair_performed": False,
        "divided_pairs_forced": False,
        "review_only_divided_recovery_promoted": False,
        "input_files": [str(path) for path in input_files if path.exists()],
        "output_files": [str(path) for path in output_files.values()],
        "summary_counts": summary_counts,
        "prototype_usable_surface_ready_for_later_crash_assignment_by_direction": ready,
        "recommendation": recommendation,
    }
    _write_json(manifest, output_files["manifest"])
    return {key: str(path) for key, path in output_files.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QA the reference-signal directional scaffold and write a conservative prototype usable surface.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_directional_scaffold_qa(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
