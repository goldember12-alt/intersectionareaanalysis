from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
SCAFFOLD_DIR = Path("review/current/reference_signal_directional_scaffold")

SEGMENT_SOURCE = "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv"
BIN_SOURCE = "signal_oriented_segment_bins_50ft_crash_ready.csv"


SEGMENT_COLUMNS = [
    "reference_directional_segment_id",
    "base_segment_id",
    "reference_signal_id",
    "far_anchor_id",
    "far_anchor_type",
    "travel_direction",
    "signal_relative_direction",
    "downstream_of_signal_id",
    "upstream_of_signal_id",
    "from_node_id",
    "to_node_id",
    "from_anchor_id",
    "to_anchor_id",
    "roadway_representation_type",
    "segment_length_ft",
    "paired_opposite_directional_segment_id",
    "shared_geometry_with_opposite_direction",
    "geometry_source",
    "direction_method",
    "direction_confidence",
    "anchor_relaxation_used",
    "signal_association_tolerance_used",
    "review_flag",
    "blocker_reason",
    "base_roadway_directionality_type",
    "base_orientation_record_type",
    "divided_pairing_status",
    "recovery_status",
    "roadway_role_class",
]

BIN_COLUMNS = [
    "reference_directional_bin_id",
    "reference_directional_segment_id",
    "base_segment_id",
    "reference_signal_id",
    "far_anchor_id",
    "far_anchor_type",
    "travel_direction",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_start_ft_from_reference_signal",
    "bin_end_ft_from_reference_signal",
    "bin_midpoint_ft_from_reference_signal",
    "roadway_representation_type",
    "direction_confidence",
    "review_flag",
    "bin_index_in_travel_direction",
    "bin_start_ft_in_travel_direction",
    "bin_end_ft_in_travel_direction",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
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


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _truthy(value: object) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "1", "YES", "Y"}


def _slug(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_").lower() or "blank"


def _directional_id(base_segment_id: object, travel_direction: str) -> str:
    suffix = "a_to_b" if travel_direction == "reference_to_anchor" else "b_to_a"
    return f"rds_{_slug(base_segment_id)}_{suffix}"


def _extract_signal_id(value: object) -> str:
    match = re.search(r"signal_\d{6}", str(value or ""))
    return match.group(0) if match else ""


def _endpoint_flags(path: Path) -> pd.DataFrame:
    flags = _read_csv(path)
    if flags.empty or "oriented_segment_id" not in flags.columns:
        return pd.DataFrame(columns=["oriented_segment_id", "endpoint_qa_categories"])
    return (
        flags.loc[_text(flags, "oriented_segment_id").ne("")]
        .groupby("oriented_segment_id", dropna=False)
        .agg(
            endpoint_qa_categories=(
                "diagnostic_category",
                lambda values: "|".join(sorted(set(str(value) for value in values if str(value)))),
            )
        )
        .reset_index()
    )


def _prepare_segments(output_root: Path) -> pd.DataFrame:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    segments = _read_csv(tables / SEGMENT_SOURCE)
    if segments.empty:
        return segments
    flags = _endpoint_flags(review / "endpoint_junction_qa" / "endpoint_junction_qa_segment_flags.csv")
    if not flags.empty:
        segments = segments.merge(flags, left_on="oriented_segment_id", right_on="oriented_segment_id", how="left")
    else:
        segments["endpoint_qa_categories"] = ""
    segments["endpoint_qa_categories"] = _text(segments, "endpoint_qa_categories")
    segments["reference_signal_id"] = _text(segments, "reference_signal_id").where(
        _text(segments, "reference_signal_id").ne(""),
        _text(segments, "from_signal_id"),
    )
    segments["opposite_anchor_signal_id"] = _text(segments, "opposite_anchor_signal_id").where(
        _text(segments, "opposite_anchor_signal_id").ne(""),
        _text(segments, "to_anchor_id").map(_extract_signal_id),
    )
    return segments


def _signal_inventory(signals: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame()
    represented = set(_text(segments, "reference_signal_id"))
    out = signals.copy()
    out["is_true_reference_signal"] = _text(out, "usable_for_step5").eq("TRUE").map({True: "TRUE", False: "FALSE"})
    out["represented_in_directional_scaffold"] = _text(out, "signal_id").isin(represented).map({True: "TRUE", False: "FALSE"})
    keep = [
        "signal_id",
        "source_signal_id",
        "usable_for_step5",
        "is_true_reference_signal",
        "represented_in_directional_scaffold",
        "signal_offset_relaxation_applied",
        "signal_offset_relaxation_reason",
        "observed_adjacent_edge_count",
        "adjacent_edge_count_band",
        "graph_gap_issue_flags",
    ]
    return out[[column for column in keep if column in out.columns]].copy()


def _far_anchor_type(row: pd.Series) -> str:
    raw_type = str(row.get("opposite_anchor_type", "") or row.get("to_anchor_type", ""))
    step5 = str(row.get("opposite_anchor_step5_status", ""))
    endpoint_flags = str(row.get("endpoint_qa_categories", ""))
    if raw_type == "signalized_intersection":
        return "true_signal" if step5 == "TRUE" else "non_true_signal"
    if raw_type == "non_signalized_roadway_intersection":
        return "non_signal_intersection"
    if raw_type == "road_endpoint_dead_end":
        if "valid_dead_end_or_one_sided_edge" in endpoint_flags:
            return "valid_dead_end_or_one_sided_boundary"
        return "roadway_endpoint"
    if raw_type:
        return "other_defensible_graph_anchor"
    return "blocked_or_unknown"


def _signal_offset_lookup(signals: pd.DataFrame) -> set[str]:
    if signals.empty or "signal_offset_relaxation_applied" not in signals.columns:
        return set()
    return set(_text(signals, "signal_id").loc[_text(signals, "signal_offset_relaxation_applied").str.upper().eq("TRUE")])


def _base_blockers(row: pd.Series) -> list[str]:
    blockers: list[str] = []
    if str(row.get("reference_signal_step5_status", "")) != "TRUE":
        blockers.append("reference_signal_not_true")
    if not _truthy(row.get("a_centered_use_allowed", "")):
        blockers.append("a_centered_use_not_allowed")
    if str(row.get("opposite_anchor_valid_for_segment_boundary", "")).upper() == "FALSE":
        blockers.append("opposite_anchor_not_valid_boundary")
    if pd.to_numeric(pd.Series([row.get("length_ft_num") or row.get("length_ft")]), errors="coerce").fillna(0).iloc[0] < 50:
        blockers.append("segment_under_50ft")
    if str(row.get("roadway_role_class", "")) == "unknown_review":
        blockers.append("unknown_roadway_role")
    return blockers


def _record_from_row(
    row: pd.Series,
    *,
    travel_direction: str,
    representation: str,
    method: str,
    confidence: str,
    paired_id: str,
    shared_geometry: bool,
    signal_offset_ids: set[str],
    blockers: list[str] | None = None,
) -> dict[str, object]:
    blockers = blockers or []
    base_id = str(row.get("oriented_segment_id", ""))
    reference_signal_id = str(row.get("reference_signal_id", ""))
    far_anchor_id = str(row.get("opposite_anchor_id", "") or row.get("to_anchor_id", ""))
    from_anchor_id = str(row.get("from_anchor_id", ""))
    to_anchor_id = str(row.get("to_anchor_id", ""))
    if travel_direction == "reference_to_anchor":
        signal_relative = "downstream_of_reference_signal"
        downstream_of = reference_signal_id
        upstream_of = ""
        from_node = from_anchor_id
        to_node = to_anchor_id
    else:
        signal_relative = "upstream_of_reference_signal"
        downstream_of = ""
        upstream_of = reference_signal_id
        from_node = to_anchor_id
        to_node = from_anchor_id

    anchor_relaxation = str(row.get("both_endpoint_signals_true", "")).upper() != "TRUE"
    review = bool(blockers) or _truthy(row.get("requires_manual_review", "")) or representation == "blocked_or_review"
    length = row.get("length_ft_num") or row.get("length_ft") or ""
    return {
        "reference_directional_segment_id": _directional_id(base_id, travel_direction),
        "base_segment_id": base_id,
        "reference_signal_id": reference_signal_id,
        "far_anchor_id": far_anchor_id,
        "far_anchor_type": _far_anchor_type(row),
        "travel_direction": travel_direction,
        "signal_relative_direction": signal_relative,
        "downstream_of_signal_id": downstream_of,
        "upstream_of_signal_id": upstream_of,
        "from_node_id": from_node,
        "to_node_id": to_node,
        "from_anchor_id": from_anchor_id,
        "to_anchor_id": to_anchor_id,
        "roadway_representation_type": representation,
        "segment_length_ft": length,
        "paired_opposite_directional_segment_id": paired_id,
        "shared_geometry_with_opposite_direction": "TRUE" if shared_geometry else "FALSE",
        "geometry_source": "step5_crash_ready_scaffold_geometry",
        "direction_method": method,
        "direction_confidence": confidence,
        "anchor_relaxation_used": "TRUE" if anchor_relaxation else "FALSE",
        "signal_association_tolerance_used": "TRUE" if reference_signal_id in signal_offset_ids else "FALSE",
        "review_flag": "TRUE" if review else "FALSE",
        "blocker_reason": "|".join(dict.fromkeys(blockers)),
        "base_roadway_directionality_type": row.get("roadway_directionality_type", ""),
        "base_orientation_record_type": row.get("orientation_record_type", ""),
        "divided_pairing_status": row.get("divided_pairing_status", ""),
        "recovery_status": row.get("recovery_status", ""),
        "roadway_role_class": row.get("roadway_role_class", ""),
    }


def _build_directional_segments(segments: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    signal_offset_ids = _signal_offset_lookup(signals)
    rows: list[dict[str, object]] = []
    by_id = {str(row.oriented_segment_id): pd.Series(row._asdict()) for row in segments.itertuples(index=False)}

    for row in segments.itertuples(index=False):
        series = pd.Series(row._asdict())
        base_id = str(series.get("oriented_segment_id", ""))
        roadway_type = str(series.get("roadway_directionality_type", ""))
        blockers = _base_blockers(series)
        if roadway_type == "undivided":
            downstream_id = _directional_id(base_id, "reference_to_anchor")
            upstream_id = _directional_id(base_id, "anchor_to_reference")
            method = "undivided_centerline_pseudo_direction_from_reference_signal"
            confidence = str(series.get("geometric_direction_confidence", "")) or "medium"
            if confidence in {"", "not_applicable", "unresolved"}:
                confidence = "medium"
            rows.append(
                _record_from_row(
                    series,
                    travel_direction="reference_to_anchor",
                    representation="undivided_centerline_pseudo_direction",
                    method=method,
                    confidence=confidence,
                    paired_id=upstream_id,
                    shared_geometry=True,
                    signal_offset_ids=signal_offset_ids,
                    blockers=blockers,
                )
            )
            rows.append(
                _record_from_row(
                    series,
                    travel_direction="anchor_to_reference",
                    representation="undivided_centerline_pseudo_direction",
                    method=method,
                    confidence=confidence,
                    paired_id=downstream_id,
                    shared_geometry=True,
                    signal_offset_ids=signal_offset_ids,
                    blockers=blockers,
                )
            )
            continue

        if roadway_type == "divided" and str(series.get("divided_pairing_status", "")) == "paired":
            orientation = str(series.get("geometric_movement_orientation", ""))
            travel_direction = "reference_to_anchor" if orientation == "A_to_B" else "anchor_to_reference" if orientation == "B_to_A" else ""
            if not travel_direction:
                travel_direction = "reference_to_anchor"
                blockers = [*blockers, "paired_divided_row_missing_geometric_movement_orientation"]
            opposite_base_id = str(series.get("paired_opposite_segment_id", ""))
            opposite = by_id.get(opposite_base_id)
            opposite_travel = "anchor_to_reference" if travel_direction == "reference_to_anchor" else "reference_to_anchor"
            paired_id = _directional_id(opposite_base_id, opposite_travel) if opposite is not None else ""
            if not paired_id:
                blockers = [*blockers, "paired_divided_opposite_segment_missing"]
            rows.append(
                _record_from_row(
                    series,
                    travel_direction=travel_direction,
                    representation="divided_physical_carriageway",
                    method="accepted_divided_pairing_right_hand_rule",
                    confidence=str(series.get("geometric_direction_confidence", "")) or str(series.get("pair_confidence", "")) or "medium",
                    paired_id=paired_id,
                    shared_geometry=False,
                    signal_offset_ids=signal_offset_ids,
                    blockers=blockers,
                )
            )
            continue

        if roadway_type == "divided":
            blockers = [*blockers, "divided_physical_direction_not_accepted_or_unpaired"]
            if str(series.get("recovery_status", "")) == "recovered_low_review_only":
                blockers.append("low_confidence_divided_recovery_review_only")
            downstream_id = _directional_id(base_id, "reference_to_anchor")
            upstream_id = _directional_id(base_id, "anchor_to_reference")
            for travel_direction, paired_id in [
                ("reference_to_anchor", upstream_id),
                ("anchor_to_reference", downstream_id),
            ]:
                rows.append(
                    _record_from_row(
                        series,
                        travel_direction=travel_direction,
                        representation="blocked_or_review",
                        method="divided_physical_direction_blocked_pending_pairing_review",
                        confidence="blocked",
                        paired_id=paired_id,
                        shared_geometry=True,
                        signal_offset_ids=signal_offset_ids,
                        blockers=blockers,
                    )
                )
            continue

        blockers = [*blockers, "unknown_or_unsupported_roadway_directionality"]
        downstream_id = _directional_id(base_id, "reference_to_anchor")
        upstream_id = _directional_id(base_id, "anchor_to_reference")
        for travel_direction, paired_id in [("reference_to_anchor", upstream_id), ("anchor_to_reference", downstream_id)]:
            rows.append(
                _record_from_row(
                    series,
                    travel_direction=travel_direction,
                    representation="blocked_or_review",
                    method="unsupported_directionality_blocked",
                    confidence="blocked",
                    paired_id=paired_id,
                    shared_geometry=True,
                    signal_offset_ids=signal_offset_ids,
                    blockers=blockers,
                )
            )

    out = pd.DataFrame(rows)
    for column in SEGMENT_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[SEGMENT_COLUMNS].copy()


def _build_directional_bins(segment_candidates: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    if segment_candidates.empty or bins.empty:
        return pd.DataFrame(columns=BIN_COLUMNS)
    bins = bins.copy()
    bins["_bin_index_num"] = _num(bins, "bin_index").fillna(0).astype(int)
    bins["_bin_start_num"] = _num(bins, "bin_start_ft")
    bins["_bin_end_num"] = _num(bins, "bin_end_ft")
    bins["_bin_mid_num"] = _num(bins, "bin_midpoint_ft")
    max_index = bins.groupby("oriented_segment_id")["_bin_index_num"].max().to_dict()
    max_end = bins.groupby("oriented_segment_id")["_bin_end_num"].max().to_dict()
    records: list[dict[str, object]] = []
    keep_segments = segment_candidates.set_index("reference_directional_segment_id", drop=False)
    bins_by_segment = {segment_id: group.copy() for segment_id, group in bins.groupby("oriented_segment_id", sort=False)}
    for seg in keep_segments.itertuples(index=False):
        base_id = str(seg.base_segment_id)
        base_bins = bins_by_segment.get(base_id)
        if base_bins is None or base_bins.empty:
            continue
        max_bin = int(max_index.get(base_id, 0))
        segment_length = float(max_end.get(base_id, 0.0) or 0.0)
        for _, bin_row in base_bins.iterrows():
            bin_index = int(bin_row["_bin_index_num"])
            if seg.travel_direction == "anchor_to_reference":
                travel_index = max_bin - bin_index + 1
                travel_start = segment_length - float(bin_row["_bin_end_num"])
                travel_end = segment_length - float(bin_row["_bin_start_num"])
            else:
                travel_index = bin_index + 1
                travel_start = bin_row["_bin_start_num"]
                travel_end = bin_row["_bin_end_num"]
            records.append(
                {
                    "reference_directional_bin_id": f"{seg.reference_directional_segment_id}_bin_{bin_index + 1:04d}",
                    "reference_directional_segment_id": seg.reference_directional_segment_id,
                    "base_segment_id": base_id,
                    "reference_signal_id": seg.reference_signal_id,
                    "far_anchor_id": seg.far_anchor_id,
                    "far_anchor_type": seg.far_anchor_type,
                    "travel_direction": seg.travel_direction,
                    "signal_relative_direction": seg.signal_relative_direction,
                    "bin_index_from_reference_signal": bin_index + 1,
                    "bin_start_ft_from_reference_signal": round(float(bin_row["_bin_start_num"]), 3),
                    "bin_end_ft_from_reference_signal": round(float(bin_row["_bin_end_num"]), 3),
                    "bin_midpoint_ft_from_reference_signal": round(float(bin_row["_bin_mid_num"]), 3),
                    "roadway_representation_type": seg.roadway_representation_type,
                    "direction_confidence": seg.direction_confidence,
                    "review_flag": seg.review_flag,
                    "bin_index_in_travel_direction": travel_index,
                    "bin_start_ft_in_travel_direction": round(float(travel_start), 3),
                    "bin_end_ft_in_travel_direction": round(float(travel_end), 3),
                }
            )
    out = pd.DataFrame(records)
    for column in BIN_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[BIN_COLUMNS].copy()


def _anchor_inventory(segment_candidates: pd.DataFrame) -> pd.DataFrame:
    if segment_candidates.empty:
        return pd.DataFrame(columns=["reference_signal_id", "far_anchor_id", "far_anchor_type", "directional_records"])
    return (
        segment_candidates.groupby(["reference_signal_id", "far_anchor_id", "far_anchor_type"], dropna=False)
        .agg(
            directional_records=("reference_directional_segment_id", "count"),
            downstream_records=("signal_relative_direction", lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum())),
            upstream_records=("signal_relative_direction", lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum())),
            review_records=("review_flag", lambda values: int(values.astype(str).eq("TRUE").sum())),
            blocked_records=("blocker_reason", lambda values: int(values.astype(str).ne("").sum())),
        )
        .reset_index()
        .sort_values(["reference_signal_id", "far_anchor_type", "far_anchor_id"])
    )


def _segment_pairs(segment_candidates: pd.DataFrame) -> pd.DataFrame:
    if segment_candidates.empty:
        return pd.DataFrame(columns=["reference_directional_segment_id", "paired_opposite_directional_segment_id"])
    cols = [
        "reference_directional_segment_id",
        "paired_opposite_directional_segment_id",
        "base_segment_id",
        "reference_signal_id",
        "far_anchor_id",
        "far_anchor_type",
        "travel_direction",
        "signal_relative_direction",
        "roadway_representation_type",
        "shared_geometry_with_opposite_direction",
        "review_flag",
        "blocker_reason",
    ]
    return segment_candidates[cols].copy()


def _summary(segment_candidates: pd.DataFrame, bins: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    true_signals = signals.loc[_text(signals, "usable_for_step5").eq("TRUE")].copy() if not signals.empty else pd.DataFrame()
    represented = set(_text(segment_candidates, "reference_signal_id"))
    add("true_reference_signals_total", len(true_signals), "TRUE rows in signal_step5_eligibility.csv.")
    add("true_reference_signals_represented", len(set(_text(true_signals, "signal_id")) & represented), "")
    add("reference_signal_centered_directional_segment_candidates", len(segment_candidates), "")
    add("downstream_of_reference_records", int(_text(segment_candidates, "signal_relative_direction").eq("downstream_of_reference_signal").sum()), "")
    add("upstream_of_reference_records", int(_text(segment_candidates, "signal_relative_direction").eq("upstream_of_reference_signal").sum()), "")
    add("far_anchor_true_signal_records", int(_text(segment_candidates, "far_anchor_type").eq("true_signal").sum()), "")
    add("far_anchor_non_true_signal_records", int(_text(segment_candidates, "far_anchor_type").eq("non_true_signal").sum()), "")
    add("far_anchor_non_signal_intersection_records", int(_text(segment_candidates, "far_anchor_type").eq("non_signal_intersection").sum()), "")
    add("far_anchor_endpoint_or_boundary_records", int(_text(segment_candidates, "far_anchor_type").isin(["roadway_endpoint", "valid_dead_end_or_one_sided_boundary"]).sum()), "")
    add("divided_physical_carriageway_records", int(_text(segment_candidates, "roadway_representation_type").eq("divided_physical_carriageway").sum()), "")
    add("undivided_centerline_pseudo_direction_records", int(_text(segment_candidates, "roadway_representation_type").eq("undivided_centerline_pseudo_direction").sum()), "")
    add("directional_records_with_paired_opposite", int(_text(segment_candidates, "paired_opposite_directional_segment_id").ne("").sum()), "")
    add("directional_records_without_paired_opposite", int(_text(segment_candidates, "paired_opposite_directional_segment_id").eq("").sum()), "")
    add("directional_bins_50ft_generated", len(bins), "")
    add("directionally_blocked_records", int(_text(segment_candidates, "blocker_reason").ne("").sum()), "")
    add("crash_data_read", "False", "")
    add("crash_assignment_outputs_read", "False", "")
    add("crash_direction_fields_used", "False", "")
    for reason, count in _text(segment_candidates, "blocker_reason").loc[_text(segment_candidates, "blocker_reason").ne("")].value_counts().items():
        add(f"blocker_reason_{reason}", int(count), "")
    return pd.DataFrame(rows)


def _qa_by_reference_signal(segment_candidates: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    if segment_candidates.empty:
        return pd.DataFrame()
    bin_counts = bins.groupby("reference_signal_id").size().rename("directional_bin_rows").reset_index() if not bins.empty else pd.DataFrame(columns=["reference_signal_id", "directional_bin_rows"])
    out = (
        segment_candidates.groupby("reference_signal_id", dropna=False)
        .agg(
            directional_segment_candidates=("reference_directional_segment_id", "count"),
            unique_far_anchors=("far_anchor_id", "nunique"),
            downstream_records=("signal_relative_direction", lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum())),
            upstream_records=("signal_relative_direction", lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum())),
            divided_physical_records=("roadway_representation_type", lambda values: int(values.astype(str).eq("divided_physical_carriageway").sum())),
            undivided_pseudo_records=("roadway_representation_type", lambda values: int(values.astype(str).eq("undivided_centerline_pseudo_direction").sum())),
            blocked_records=("blocker_reason", lambda values: int(values.astype(str).ne("").sum())),
            review_records=("review_flag", lambda values: int(values.astype(str).eq("TRUE").sum())),
        )
        .reset_index()
        .merge(bin_counts, on="reference_signal_id", how="left")
    )
    out["directional_bin_rows"] = _num(out, "directional_bin_rows").fillna(0).astype(int)
    return out.sort_values(["blocked_records", "directional_segment_candidates"], ascending=[False, False])


def _qa_by_anchor_type(segment_candidates: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    if segment_candidates.empty:
        return pd.DataFrame()
    bin_counts = bins.groupby("far_anchor_type").size().rename("directional_bin_rows").reset_index() if not bins.empty else pd.DataFrame(columns=["far_anchor_type", "directional_bin_rows"])
    out = (
        segment_candidates.groupby("far_anchor_type", dropna=False)
        .agg(
            directional_segment_candidates=("reference_directional_segment_id", "count"),
            unique_reference_signals=("reference_signal_id", "nunique"),
            unique_far_anchors=("far_anchor_id", "nunique"),
            downstream_records=("signal_relative_direction", lambda values: int(values.astype(str).eq("downstream_of_reference_signal").sum())),
            upstream_records=("signal_relative_direction", lambda values: int(values.astype(str).eq("upstream_of_reference_signal").sum())),
            blocked_records=("blocker_reason", lambda values: int(values.astype(str).ne("").sum())),
        )
        .reset_index()
        .merge(bin_counts, on="far_anchor_type", how="left")
    )
    out["directional_bin_rows"] = _num(out, "directional_bin_rows").fillna(0).astype(int)
    return out.sort_values("directional_segment_candidates", ascending=False)


def _blockers(segment_candidates: pd.DataFrame) -> pd.DataFrame:
    blocked = segment_candidates.loc[_text(segment_candidates, "blocker_reason").ne("")].copy()
    if blocked.empty:
        return pd.DataFrame(columns=SEGMENT_COLUMNS)
    return blocked.sort_values(["blocker_reason", "reference_signal_id", "far_anchor_id", "travel_direction"])


def _findings(summary_counts: dict[str, int], blockers: pd.DataFrame) -> str:
    blocker_lines = "None"
    if not blockers.empty:
        exploded = blockers.assign(blocker_reason=_text(blockers, "blocker_reason").str.split("|")).explode("blocker_reason")
        blocker_lines = "\n".join(
            f"- {reason}: {int(count)} records"
            for reason, count in _text(exploded, "blocker_reason").value_counts().head(8).items()
        )
    return f"""# Reference-Signal-Centered Directional Scaffold Findings

**Status:** Read-only candidate/audit output for the roadway_graph / Step 5 directional scaffold.

## Bounded Question

This module builds candidate directional records centered on TRUE reference signals. For every defensible A-to-B scaffold segment, A is the TRUE reference signal and B may be a TRUE signal, non-TRUE signal, non-signalized intersection, endpoint, valid one-sided boundary, or other defensible graph anchor.

It uses roadway, signal, graph, scaffold, geometric-direction, divided-pairing, recovery, role, and endpoint-QA outputs only. It does not read crash data, crash assignment outputs, crash direction fields, or crash distributions.

## Directional Interpretation

- Downstream-of-reference records: {summary_counts["downstream"]}
- Upstream-of-reference records: {summary_counts["upstream"]}
- Divided physical carriageway records: {summary_counts["divided_physical"]}
- Undivided centerline pseudo-direction records: {summary_counts["undivided_pseudo"]}
- 50-foot directional bin records: {summary_counts["bins"]}

Undivided centerlines receive two pseudo-directional records from the same centerline geometry. Bins for both downstream and upstream records are indexed from the TRUE reference signal A.

## Far Anchors

- TRUE-signal far-anchor records: {summary_counts["true_anchor"]}
- Non-TRUE signal records: {summary_counts["non_true_anchor"]}
- Non-signal intersection records: {summary_counts["non_signal_anchor"]}
- Endpoint or one-sided boundary records: {summary_counts["endpoint_anchor"]}

The output is reference-signal-centered. If B is also TRUE, B may have separate B-centered records elsewhere in the table.

## Blockers

{blocker_lines}

Blocked records are retained for audit visibility and should not be used for later directional crash assignment without a reviewed promotion rule.

## Recommendation

Use only non-review, non-blocked directional records for any later directional crash-assignment prototype. The scaffold is a candidate/audit output, not yet a final crash-assignment-by-direction surface, because unpaired divided rows and low-confidence recovery rows remain blocked or review-only.
"""


def build_reference_signal_directional_scaffold(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    out_dir = output_root / SCAFFOLD_DIR

    signals = _read_csv(tables / "signal_step5_eligibility.csv")
    segments = _prepare_segments(output_root)
    bins_source = _read_csv(tables / BIN_SOURCE)

    directional_segments = _build_directional_segments(segments, signals)
    directional_bins = _build_directional_bins(directional_segments, bins_source)
    blockers = _blockers(directional_segments)
    summary = _summary(directional_segments, directional_bins, signals)

    output_files = {
        "summary": out_dir / "reference_signal_directional_scaffold_summary.csv",
        "node_inventory": out_dir / "reference_signal_node_inventory.csv",
        "anchor_inventory": out_dir / "reference_signal_anchor_inventory.csv",
        "segment_candidates": out_dir / "reference_signal_directional_segment_candidates.csv",
        "segment_pairs": out_dir / "reference_signal_directional_segment_pairs.csv",
        "bins": out_dir / "reference_signal_directional_bins_50ft_candidates.csv",
        "undivided": out_dir / "undivided_centerline_pseudo_direction_records.csv",
        "divided": out_dir / "divided_physical_direction_records.csv",
        "nontrue_anchor": out_dir / "signal_to_nontrue_anchor_direction_records.csv",
        "endpoint": out_dir / "signal_to_endpoint_direction_records.csv",
        "blockers": out_dir / "directional_blockers.csv",
        "qa_signal": out_dir / "directional_scaffold_qa_by_reference_signal.csv",
        "qa_anchor": out_dir / "directional_scaffold_qa_by_anchor_type.csv",
        "findings": out_dir / "reference_signal_directional_scaffold_findings.md",
        "manifest": out_dir / "reference_signal_directional_scaffold_manifest.json",
    }

    node_inventory = _signal_inventory(signals, directional_segments)
    anchor_inventory = _anchor_inventory(directional_segments)
    segment_pairs = _segment_pairs(directional_segments)
    qa_signal = _qa_by_reference_signal(directional_segments, directional_bins)
    qa_anchor = _qa_by_anchor_type(directional_segments, directional_bins)

    _write_csv(summary, output_files["summary"])
    _write_csv(node_inventory, output_files["node_inventory"])
    _write_csv(anchor_inventory, output_files["anchor_inventory"])
    _write_csv(directional_segments, output_files["segment_candidates"])
    _write_csv(segment_pairs, output_files["segment_pairs"])
    _write_csv(directional_bins, output_files["bins"])
    _write_csv(directional_segments.loc[_text(directional_segments, "roadway_representation_type").eq("undivided_centerline_pseudo_direction")], output_files["undivided"])
    _write_csv(directional_segments.loc[_text(directional_segments, "roadway_representation_type").eq("divided_physical_carriageway")], output_files["divided"])
    _write_csv(directional_segments.loc[_text(directional_segments, "far_anchor_type").eq("non_true_signal")], output_files["nontrue_anchor"])
    _write_csv(directional_segments.loc[_text(directional_segments, "far_anchor_type").isin(["roadway_endpoint", "valid_dead_end_or_one_sided_boundary"])], output_files["endpoint"])
    _write_csv(blockers, output_files["blockers"])
    _write_csv(qa_signal, output_files["qa_signal"])
    _write_csv(qa_anchor, output_files["qa_anchor"])

    summary_counts = {
        "true_signals_represented": int(summary.loc[summary["metric"].eq("true_reference_signals_represented"), "value"].iloc[0]),
        "directional_segments": len(directional_segments),
        "downstream": int(_text(directional_segments, "signal_relative_direction").eq("downstream_of_reference_signal").sum()),
        "upstream": int(_text(directional_segments, "signal_relative_direction").eq("upstream_of_reference_signal").sum()),
        "true_anchor": int(_text(directional_segments, "far_anchor_type").eq("true_signal").sum()),
        "non_true_anchor": int(_text(directional_segments, "far_anchor_type").eq("non_true_signal").sum()),
        "non_signal_anchor": int(_text(directional_segments, "far_anchor_type").eq("non_signal_intersection").sum()),
        "endpoint_anchor": int(_text(directional_segments, "far_anchor_type").isin(["roadway_endpoint", "valid_dead_end_or_one_sided_boundary"]).sum()),
        "divided_physical": int(_text(directional_segments, "roadway_representation_type").eq("divided_physical_carriageway").sum()),
        "undivided_pseudo": int(_text(directional_segments, "roadway_representation_type").eq("undivided_centerline_pseudo_direction").sum()),
        "bins": len(directional_bins),
        "blocked": len(blockers),
    }
    _write_text(_findings(summary_counts, blockers), output_files["findings"])

    input_files = [
        tables / "signal_step5_eligibility.csv",
        tables / SEGMENT_SOURCE,
        tables / BIN_SOURCE,
        tables / "signal_oriented_roadway_segments_geometric_direction.csv",
        tables / "signal_oriented_segment_bins_geometric_direction.csv",
        tables / "divided_carriageway_pair_candidates.csv",
        tables / "divided_carriageway_pair_candidates_recovery.csv",
        tables / "signal_oriented_roadway_segments_role_enriched.csv",
        review / "endpoint_junction_qa" / "endpoint_junction_qa_segment_flags.csv",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Reference-signal-centered directional scaffold candidate/audit from TRUE signals to defensible far anchors.",
        "read_only": True,
        "candidate_audit_output_only": True,
        "raw_crash_data_read": False,
        "crash_assignment_outputs_read": False,
        "crash_direction_fields_used": False,
        "crash_distributions_used": False,
        "scaffold_construction_changed": False,
        "crash_assignment_logic_changed": False,
        "upstream_downstream_from_crashes_inferred": False,
        "input_files": [str(path) for path in input_files if path.exists()],
        "output_files": [str(path) for path in output_files.values()],
        "summary_counts": summary_counts,
        "bin_ordering_rule": "All bin_index_from_reference_signal values are ordered by distance from TRUE reference signal A for both downstream and upstream records.",
        "recommendation": "Use only non-review, non-blocked directional records for any later directional crash-assignment prototype.",
    }
    _write_json(manifest, output_files["manifest"])
    return {key: str(path) for key, path in output_files.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only reference-signal-centered directional scaffold candidate/audit.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_reference_signal_directional_scaffold(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
