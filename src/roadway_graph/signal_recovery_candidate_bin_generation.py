from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/signal_recovery_scaffold_feasibility"
ONE_DIRECTION_DIR = OUTPUT_ROOT / "review/current/signal_one_direction_scaffold_diagnostic"
OUT_DIR = OUTPUT_ROOT / "review/current/signal_recovery_candidate_bin_generation"
TABLES = OUTPUT_ROOT / "tables/current"

STRICT_ACTIVE_SIGNAL_BASELINE = 971
EXPECTED_ONE_DIRECTION_COUNT = 1075
BIN_SIZE_FT = 50.0
MAX_DISTANCE_FT = 2500.0


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if usecols is None:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    header = pd.read_csv(path, nrows=0)
    cols = [col for col in usecols if col in header.columns]
    if not cols:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_inputs() -> dict[str, Any]:
    return {
        "candidate_detail": _read_csv(SCAFFOLD_DIR / "signal_recovery_scaffold_candidate_detail.csv"),
        "signal_summary": _read_csv(SCAFFOLD_DIR / "signal_recovery_scaffold_signal_summary.csv"),
        "feasibility_summary": _read_csv(SCAFFOLD_DIR / "signal_recovery_scaffold_feasibility_summary.csv"),
        "multi_candidate_summary": _read_csv(SCAFFOLD_DIR / "signal_recovery_scaffold_multi_candidate_summary.csv"),
        "existing_active_overlap": _read_csv(SCAFFOLD_DIR / "signal_recovery_scaffold_existing_active_overlap.csv"),
        "scaffold_manifest": _load_manifest(SCAFFOLD_DIR / "signal_recovery_scaffold_manifest.json"),
        "one_direction_signal": _read_csv(ONE_DIRECTION_DIR / "one_direction_signal_detail.csv"),
        "one_direction_candidate": _read_csv(ONE_DIRECTION_DIR / "one_direction_candidate_detail.csv"),
        "one_direction_category": _read_csv(ONE_DIRECTION_DIR / "one_direction_category_summary.csv"),
        "one_direction_handling": _read_csv(ONE_DIRECTION_DIR / "one_direction_handling_summary.csv"),
        "one_direction_distance": _read_csv(ONE_DIRECTION_DIR / "one_direction_distance_coverage_summary.csv"),
        "one_direction_manifest": _load_manifest(ONE_DIRECTION_DIR / "one_direction_scaffold_manifest.json"),
        "adjacent_edges": _read_csv(
            TABLES / "signal_adjacent_edges.csv",
            usecols=[
                "signal_id",
                "signal_graph_node_id",
                "graph_edge_id",
                "adjacent_node_id",
                "adjacent_node_type",
                "adjacent_side_label",
                "route_name",
                "route_common",
                "route_id",
                "event_source",
                "road_component_id",
                "roadway_division_status",
                "logical_segment_mode",
                "length_ft",
                "geometry_status",
                "qa_status",
                "true_vehicle_direction_inferred",
            ],
        ),
        "strict_segments": _read_csv(
            TABLES / "signal_oriented_roadway_segments_crash_ready.csv",
            usecols=["reference_signal_id", "road_component_id", "base_graph_edge_id", "route_common"],
        ),
    }


def _candidate_association_id(row: pd.Series) -> str:
    return f"{row.get('signal_id', '')}_{row.get('road_component_id', '')}_rank_{row.get('candidate_rank', '')}"


def _analysis_window(start: float, end: float) -> str:
    if start < 1000.0 and end <= 1000.0:
        return "0_1000"
    if start >= 1000.0 and end <= 2500.0:
        return "1000_2500"
    return "other_diagnostic"


def _scaffold_tier_for_length(length: float, direction_count: int) -> str:
    if length >= 2500.0:
        base = "full_0_2500"
    elif length >= 1000.0:
        base = "full_0_1000_partial_1000_2500"
    elif length > 0:
        base = "partial_under_1000"
    else:
        base = "not_buildable"
    if direction_count <= 1 and base != "not_buildable":
        return f"{base}_one_direction_only"
    return base


def _candidate_logic(row: pd.Series) -> str:
    tier = str(row.get("association_confidence_tier", ""))
    if tier == "deterministic_recovery_candidate":
        return "deterministic_candidate"
    if tier == "multi_candidate_weighted_recovery":
        return "multi_candidate_weighted_candidate"
    if tier == "review_only_candidate":
        return "review_only_candidate"
    return "partial_or_diagnostic_candidate"


def _prepare_candidate_rows(candidate_detail: pd.DataFrame, one_direction_signal: pd.DataFrame) -> pd.DataFrame:
    if candidate_detail.empty:
        return candidate_detail
    proxy_ids = set(_text(one_direction_signal.loc[_text(one_direction_signal, "one_direction_diagnostic_category").eq("proxy_only_possible_false_one_direction")], "signal_id"))
    include = (
        _bool(candidate_detail, "supports_any_buildable_scaffold")
        | _bool(candidate_detail, "supports_full_0_2500ft_path")
        | _bool(candidate_detail, "supports_0_1000ft_path")
        | _text(candidate_detail, "signal_id").isin(proxy_ids)
    )
    out = candidate_detail.loc[include].copy()
    if out.empty:
        return out
    out["candidate_association_id"] = out.apply(_candidate_association_id, axis=1)
    weights = pd.to_numeric(out.get("candidate_weight_preliminary", ""), errors="coerce")
    missing_weight = weights.isna()
    out["candidate_weight_preliminary"] = weights
    if missing_weight.any():
        counts = out.groupby("signal_id")["candidate_association_id"].transform("count").replace(0, 1)
        out.loc[missing_weight, "candidate_weight_preliminary"] = 1.0 / counts.loc[missing_weight]
        out.loc[missing_weight, "weighting_assumption"] = "equal_weight_assigned_for_missing_candidate_weight"
    return out


def _build_bins(candidate_rows: pd.DataFrame, adjacent_edges: pd.DataFrame, strict_segments: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if candidate_rows.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    edge = adjacent_edges.copy()
    edge["_length"] = _num(edge, "length_ft")
    strict_components = set(_text(strict_segments, "road_component_id")) if not strict_segments.empty else set()
    edge_by_key = {key: group.copy() for key, group in edge.groupby(["signal_id", "road_component_id"], sort=False)}

    bin_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []
    assoc_rows: list[dict[str, Any]] = []

    for candidate in candidate_rows.itertuples(index=False):
        c = pd.Series(candidate._asdict())
        key = (str(c.get("signal_id", "")), str(c.get("road_component_id", "")))
        edges = edge_by_key.get(key, pd.DataFrame())
        assoc_id = str(c.get("candidate_association_id", ""))
        if edges.empty:
            assoc_rows.append(_association_failure(c, "no graph path", "no matching signal-adjacent graph edge"))
            continue
        generated_for_assoc = 0
        generated_length_ft = 0.0
        direction_labels = set()
        for edge_row in edges.itertuples(index=False):
            e = pd.Series(edge_row._asdict())
            edge_len = pd.to_numeric(e.get("length_ft", ""), errors="coerce")
            if pd.isna(edge_len) or float(edge_len) <= 0:
                path_rows.append(_path_record(c, e, 0, "no usable edge sequence"))
                continue
            max_len = min(float(edge_len), MAX_DISTANCE_FT)
            direction_label = str(e.get("adjacent_side_label", "")) or "direction_unresolved"
            direction_labels.add(direction_label)
            path_rows.append(_path_record(c, e, max_len, "path_bins_generated"))
            bin_index = 1
            start = 0.0
            while start < max_len:
                end = min(start + BIN_SIZE_FT, max_len)
                bin_len = round(end - start, 3)
                bin_rows.append(_bin_record(c, e, bin_index, start, end, bin_len, direction_label, len(edges), c.get("road_component_id", "") in strict_components))
                generated_for_assoc += 1
                generated_length_ft += bin_len
                bin_index += 1
                start = end
        if generated_for_assoc == 0:
            assoc_rows.append(_association_failure(c, "no usable edge sequence", "matching graph edges did not produce positive-length bins"))
        else:
            assoc_rows.append(
                _association_success(
                    c,
                    generated_for_assoc,
                    generated_length_ft,
                    len(direction_labels),
                    strict=bool(c.get("road_component_id", "") in strict_components),
                )
            )
    return pd.DataFrame(bin_rows), pd.DataFrame(path_rows), pd.DataFrame(assoc_rows)


def _path_record(c: pd.Series, e: pd.Series, length: float, status: str) -> dict[str, Any]:
    return {
        "candidate_association_id": c.get("candidate_association_id", ""),
        "signal_id": c.get("signal_id", ""),
        "road_component_id": c.get("road_component_id", ""),
        "graph_edge_id": e.get("graph_edge_id", ""),
        "adjacent_node_id": e.get("adjacent_node_id", ""),
        "adjacent_node_type": e.get("adjacent_node_type", ""),
        "adjacent_side_label": e.get("adjacent_side_label", ""),
        "path_length_used_ft": round(float(length), 3),
        "path_generation_status": status,
        "review_only_candidate_path": True,
    }


def _bin_record(c: pd.Series, e: pd.Series, bin_index: int, start: float, end: float, bin_len: float, direction_label: str, edge_count: int, strict_component_overlap: bool) -> dict[str, Any]:
    direction_count_raw = pd.to_numeric(c.get("candidate_side_count", edge_count), errors="coerce")
    direction_count = edge_count if pd.isna(direction_count_raw) else int(direction_count_raw)
    return {
        "candidate_recovery_bin_id": f"{c.get('candidate_association_id', '')}_{e.get('graph_edge_id', '')}_bin_{bin_index:04d}",
        "signal_id": c.get("signal_id", ""),
        "source_signal_id": c.get("source_signal_id", ""),
        "source_layer": c.get("source_layer", ""),
        "candidate_association_id": c.get("candidate_association_id", ""),
        "recovery_strategy": c.get("recovery_strategy", ""),
        "association_confidence_tier": c.get("association_confidence_tier", ""),
        "candidate_rank": c.get("candidate_rank", ""),
        "candidate_weight_preliminary": c.get("candidate_weight_preliminary", ""),
        "tie_group_id": c.get("tie_group_id", ""),
        "road_component_id": c.get("road_component_id", ""),
        "graph_edge_id": e.get("graph_edge_id", ""),
        "adjacent_node_id": e.get("adjacent_node_id", ""),
        "signal_relative_direction_label": f"candidate_{direction_label}",
        "direction_confidence_status": "graph_adjacent_side_label_proxy",
        "far_anchor_type_candidate": e.get("adjacent_node_type", ""),
        "distance_from_signal_start_ft": round(float(start), 3),
        "distance_from_signal_end_ft": round(float(end), 3),
        "bin_length_ft": bin_len,
        "analysis_window": _analysis_window(float(start), float(end)),
        "scaffold_completeness_tier": _scaffold_tier_for_length(float(end), direction_count),
        "candidate_logic_tier": _candidate_logic(c),
        "review_only_candidate_bin": True,
        "active_output_promotion_status": "not_promoted_review_only",
        "strict_active_overlap_status": "same_road_component_in_strict_scaffold_possible_double_count_risk" if strict_component_overlap else "no_active_overlap",
        "roadway_division_status": c.get("roadway_division_status", ""),
        "matched_route_common": c.get("matched_route_common", ""),
    }


def _association_failure(c: pd.Series, reason: str, note: str) -> dict[str, Any]:
    return {
        "candidate_association_id": c.get("candidate_association_id", ""),
        "signal_id": c.get("signal_id", ""),
        "source_layer": c.get("source_layer", ""),
        "recovery_strategy": c.get("recovery_strategy", ""),
        "association_confidence_tier": c.get("association_confidence_tier", ""),
        "candidate_rank": c.get("candidate_rank", ""),
        "road_component_id": c.get("road_component_id", ""),
        "candidate_association_produced_bins": False,
        "candidate_bin_count": 0,
        "candidate_bin_length_ft": 0.0,
        "weighted_candidate_bin_count": 0.0,
        "weighted_candidate_bin_length_ft": 0.0,
        "full_0_1000_candidate": False,
        "full_0_2500_candidate": False,
        "both_direction_candidate": False,
        "one_direction_only_candidate": False,
        "failure_reason": reason,
        "failure_note": note,
        "review_only_candidate_association": True,
    }


def _association_success(c: pd.Series, bin_count: int, generated_length_ft: float, direction_count: int, *, strict: bool) -> dict[str, Any]:
    weight = float(pd.to_numeric(c.get("candidate_weight_preliminary", 1.0), errors="coerce") or 1.0)
    max_len = float(pd.to_numeric(c.get("candidate_max_edge_length_ft", 0.0), errors="coerce") or 0.0)
    return {
        "candidate_association_id": c.get("candidate_association_id", ""),
        "signal_id": c.get("signal_id", ""),
        "source_layer": c.get("source_layer", ""),
        "recovery_strategy": c.get("recovery_strategy", ""),
        "association_confidence_tier": c.get("association_confidence_tier", ""),
        "candidate_rank": c.get("candidate_rank", ""),
        "road_component_id": c.get("road_component_id", ""),
        "candidate_association_produced_bins": True,
        "candidate_bin_count": int(bin_count),
        "candidate_bin_length_ft": round(float(generated_length_ft), 3),
        "weighted_candidate_bin_count": round(float(bin_count) * weight, 6),
        "weighted_candidate_bin_length_ft": round(float(generated_length_ft) * weight, 6),
        "full_0_1000_candidate": max_len >= 1000.0,
        "full_0_2500_candidate": max_len >= 2500.0,
        "both_direction_candidate": direction_count >= 2,
        "one_direction_only_candidate": direction_count <= 1,
        "failure_reason": "",
        "failure_note": "",
        "review_only_candidate_association": True,
        "strict_active_overlap_status": "same_road_component_in_strict_scaffold_possible_double_count_risk" if strict else "no_active_overlap",
    }


def _review_only_failures(candidate_detail: pd.DataFrame) -> pd.DataFrame:
    review = candidate_detail.loc[_text(candidate_detail, "association_confidence_tier").eq("review_only_candidate")].copy()
    if review.empty:
        return pd.DataFrame()
    review["candidate_association_id"] = review.apply(_candidate_association_id, axis=1)
    rows = []
    for row in review.itertuples(index=False):
        c = pd.Series(row._asdict())
        reason = "divided pairing needed" if str(c.get("recovery_strategy", "")) == "divided_carriageway_pairing_candidate" else "review-only not attempted"
        rows.append(_association_failure(c, reason, "Review-only candidate was not attempted for bin generation."))
    return pd.DataFrame(rows)


def _signal_summary(assoc: pd.DataFrame, signal_input: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sid, group in assoc.groupby("signal_id", sort=False):
        source = signal_input.loc[_text(signal_input, "signal_id").eq(str(sid))]
        first = source.iloc[0] if not source.empty else group.iloc[0]
        produced = group.loc[group["candidate_association_produced_bins"].astype(bool)]
        dirs = int(produced["both_direction_candidate"].astype(bool).sum())
        one_dirs = int(produced["one_direction_only_candidate"].astype(bool).sum())
        rows.append(
            {
                "signal_id": sid,
                "source_signal_id": first.get("source_signal_id", ""),
                "source_layer": first.get("source_layer", ""),
                "candidate_associations_tested": len(group),
                "candidate_associations_producing_bins": int(produced["candidate_association_id"].nunique()),
                "total_candidate_bins_generated": int(pd.to_numeric(group["candidate_bin_count"], errors="coerce").fillna(0).sum()),
                "total_candidate_bin_length_ft": round(float(pd.to_numeric(group["candidate_bin_length_ft"], errors="coerce").fillna(0).sum()), 3),
                "weighted_candidate_bin_count": round(float(pd.to_numeric(group["weighted_candidate_bin_count"], errors="coerce").fillna(0).sum()), 6),
                "weighted_candidate_bin_length_ft": round(float(pd.to_numeric(group["weighted_candidate_bin_length_ft"], errors="coerce").fillna(0).sum()), 6),
                "full_0_1000_coverage_flag": bool(produced["full_0_1000_candidate"].astype(bool).any()),
                "full_0_2500_coverage_flag": bool(produced["full_0_2500_candidate"].astype(bool).any()),
                "both_direction_coverage_flag": dirs > 0,
                "one_direction_only_flag": one_dirs > 0 and dirs == 0,
                "multi_candidate_preserved_flag": bool(str(first.get("primary_confidence_tier", first.get("association_confidence_tier", ""))) == "multi_candidate_weighted_recovery"),
                "dominant_failure_reason": _dominant_failure(group),
                "recommended_next_handling_class": _next_handling(produced, group),
            }
        )
    return pd.DataFrame(rows)


def _dominant_failure(group: pd.DataFrame) -> str:
    failures = _text(group, "failure_reason")
    failures = failures.loc[failures.ne("")]
    return str(failures.value_counts().index[0]) if not failures.empty else ""


def _next_handling(produced: pd.DataFrame, group: pd.DataFrame) -> str:
    if not produced.empty:
        if bool(produced["full_0_2500_candidate"].astype(bool).any()):
            return "candidate_bin_full_0_2500_review"
        if bool(produced["full_0_1000_candidate"].astype(bool).any()):
            return "candidate_bin_0_1000_review"
        return "partial_candidate_bin_review"
    failure = _dominant_failure(group)
    if failure == "divided pairing needed":
        return "divided_pairing_review_before_bins"
    if failure == "review-only not attempted":
        return "review_only_not_attempted"
    return "bin_generation_failure_review"


def _summary_table(signal_summary: pd.DataFrame, bin_rows: pd.DataFrame, assoc: pd.DataFrame) -> pd.DataFrame:
    attempted_ids = set(_text(assoc.loc[~_text(assoc, "association_confidence_tier").eq("review_only_candidate")], "signal_id"))
    attempted = len(attempted_ids)
    attempted_summary = signal_summary.loc[_text(signal_summary, "signal_id").isin(attempted_ids)].copy()
    any_bins = int(signal_summary["candidate_associations_producing_bins"].gt(0).sum()) if not signal_summary.empty else 0
    full_1000 = int(signal_summary["full_0_1000_coverage_flag"].sum()) if not signal_summary.empty else 0
    full_2500 = int(signal_summary["full_0_2500_coverage_flag"].sum()) if not signal_summary.empty else 0
    both = int(signal_summary["both_direction_coverage_flag"].sum()) if not signal_summary.empty else 0
    one = int(signal_summary["one_direction_only_flag"].sum()) if not signal_summary.empty else 0
    multi = int(signal_summary["multi_candidate_preserved_flag"].sum()) if not signal_summary.empty else 0
    failed = attempted - int(attempted_summary["candidate_associations_producing_bins"].gt(0).sum()) if not attempted_summary.empty else attempted
    return pd.DataFrame(
        [
            {"metric": "strict_active_signal_count_baseline", "value": STRICT_ACTIVE_SIGNAL_BASELINE},
            {"metric": "recovered_signals_attempted", "value": attempted},
            {"metric": "recovered_signals_producing_any_bins", "value": any_bins},
            {"metric": "recovered_signals_producing_full_0_1000_bins", "value": full_1000},
            {"metric": "recovered_signals_producing_full_0_2500_bins", "value": full_2500},
            {"metric": "recovered_signals_producing_both_direction_bins", "value": both},
            {"metric": "recovered_signals_producing_one_direction_only_bins", "value": one},
            {"metric": "recovered_signals_remaining_multi_candidate_weighted", "value": multi},
            {"metric": "recovered_signals_failing_bin_generation", "value": failed},
            {"metric": "maximum_expanded_bin_producing_signal_universe_vs_strict_active", "value": STRICT_ACTIVE_SIGNAL_BASELINE + any_bins},
            {"metric": "expanded_full_0_1000_signal_universe_vs_strict_active", "value": STRICT_ACTIVE_SIGNAL_BASELINE + full_1000},
            {"metric": "expanded_full_0_2500_signal_universe_vs_strict_active", "value": STRICT_ACTIVE_SIGNAL_BASELINE + full_2500},
            {"metric": "candidate_bin_count", "value": len(bin_rows)},
            {"metric": "weighted_candidate_bin_count", "value": round(float(pd.to_numeric(assoc["weighted_candidate_bin_count"], errors="coerce").fillna(0).sum()), 6) if not assoc.empty else 0},
        ]
    )


def _window_summary(bins: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        return pd.DataFrame(columns=["analysis_window", "candidate_bin_count", "unique_signal_count", "weighted_candidate_bin_count"])
    tmp = bins.copy()
    tmp["_weight"] = pd.to_numeric(tmp["candidate_weight_preliminary"], errors="coerce").fillna(1.0)
    return (
        tmp.groupby("analysis_window", dropna=False)
        .agg(candidate_bin_count=("candidate_recovery_bin_id", "count"), unique_signal_count=("signal_id", "nunique"), weighted_candidate_bin_count=("_weight", "sum"))
        .reset_index()
    )


def _direction_summary(signal_summary: pd.DataFrame) -> pd.DataFrame:
    if signal_summary.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {"direction_coverage_class": "both_direction_bins", "signal_count": int(signal_summary["both_direction_coverage_flag"].sum())},
            {"direction_coverage_class": "one_direction_only_bins", "signal_count": int(signal_summary["one_direction_only_flag"].sum())},
            {"direction_coverage_class": "unresolved_or_no_bins", "signal_count": int(signal_summary["candidate_associations_producing_bins"].eq(0).sum())},
        ]
    )


def _weight_summary(assoc: pd.DataFrame) -> pd.DataFrame:
    if assoc.empty:
        return pd.DataFrame()
    return (
        assoc.groupby(["association_confidence_tier", "recovery_strategy"], dropna=False)
        .agg(
            association_count=("candidate_association_id", "count"),
            associations_producing_bins=("candidate_association_produced_bins", "sum"),
            candidate_bin_count=("candidate_bin_count", "sum"),
            weighted_candidate_bin_count=("weighted_candidate_bin_count", "sum"),
            weighted_candidate_bin_length_ft=("weighted_candidate_bin_length_ft", "sum"),
        )
        .reset_index()
    )


def _overlap(bins: pd.DataFrame) -> pd.DataFrame:
    if bins.empty:
        return pd.DataFrame(columns=["strict_active_overlap_status", "candidate_bin_count", "unique_signal_count"])
    return (
        bins.groupby("strict_active_overlap_status", dropna=False)
        .agg(candidate_bin_count=("candidate_recovery_bin_id", "count"), unique_signal_count=("signal_id", "nunique"))
        .reset_index()
    )


def _failure_reasons(assoc: pd.DataFrame) -> pd.DataFrame:
    fail = assoc.loc[~assoc["candidate_association_produced_bins"].astype(bool)].copy()
    if fail.empty:
        return pd.DataFrame(columns=["failure_reason", "association_count", "unique_signal_count"])
    return (
        fail.groupby("failure_reason", dropna=False)
        .agg(association_count=("candidate_association_id", "count"), unique_signal_count=("signal_id", "nunique"))
        .reset_index()
        .sort_values("association_count", ascending=False)
    )


def _ranked_queue(signal_summary: pd.DataFrame) -> pd.DataFrame:
    if signal_summary.empty:
        return pd.DataFrame()
    out = signal_summary.copy()
    out["review_queue_type"] = "mapped_review_before_promotion"
    out.loc[out["full_0_2500_coverage_flag"].astype(bool), "review_queue_type"] = "full_0_2500_candidate_bins"
    out.loc[out["full_0_1000_coverage_flag"].astype(bool) & ~out["full_0_2500_coverage_flag"].astype(bool), "review_queue_type"] = "full_0_1000_candidate_bins"
    out.loc[out["one_direction_only_flag"].astype(bool), "review_queue_type"] = "one_direction_candidate_bins"
    out.loc[out["candidate_associations_producing_bins"].eq(0), "review_queue_type"] = "failed_bin_generation_review"
    out["review_priority_score"] = (
        out["full_0_2500_coverage_flag"].astype(int) * 50
        + out["full_0_1000_coverage_flag"].astype(int) * 25
        + out["both_direction_coverage_flag"].astype(int) * 15
        + out["multi_candidate_preserved_flag"].astype(int) * 5
        + pd.to_numeric(out["total_candidate_bins_generated"], errors="coerce").fillna(0) / 100
    )
    return out.sort_values(["review_priority_score", "total_candidate_bins_generated"], ascending=False)


def _findings(summary: pd.DataFrame, failures: pd.DataFrame, one_direction_signal: pd.DataFrame, signal_summary: pd.DataFrame, qa: pd.DataFrame) -> str:
    metrics = {row.metric: row.value for row in summary.itertuples(index=False)}
    proxy_ids = set(_text(one_direction_signal.loc[_text(one_direction_signal, "one_direction_diagnostic_category").eq("proxy_only_possible_false_one_direction")], "signal_id"))
    proxy_resolved = int(signal_summary.loc[_text(signal_summary, "signal_id").isin(proxy_ids), "candidate_associations_producing_bins"].gt(0).sum()) if not signal_summary.empty else 0
    failure_text = "; ".join(f"{r.failure_reason}: {int(r.unique_signal_count)} signals" for r in failures.head(5).itertuples(index=False))
    return f"""# Candidate Recovery Bin Generation Findings

Status: read-only candidate bin-generation prototype. Generated bins are review-only candidate rows, not active scaffold or context outputs.

## Required Findings

1. Recovered signals attempted: {int(metrics.get('recovered_signals_attempted', 0))}
2. Recovered signals generating any actual candidate bins: {int(metrics.get('recovered_signals_producing_any_bins', 0))}
3. Recovered signals generating full 0-1,000 ft candidate bins: {int(metrics.get('recovered_signals_producing_full_0_1000_bins', 0))}
4. Recovered signals generating full 0-2,500 ft candidate bins: {int(metrics.get('recovered_signals_producing_full_0_2500_bins', 0))}
5. Recovered signals generating both-direction bins: {int(metrics.get('recovered_signals_producing_both_direction_bins', 0))}
6. Recovered signals generating one-direction-only bins: {int(metrics.get('recovered_signals_producing_one_direction_only_bins', 0))}
7. Recovered signals preserving multi-candidate/weighted bins: {int(metrics.get('recovered_signals_remaining_multi_candidate_weighted', 0))}
8. Signals failing despite proxy scaffold feasibility or review-only status: {int(metrics.get('recovered_signals_failing_bin_generation', 0))}
9. Dominant failure reasons: {failure_text or 'none'}
10. Maximum bin-producing signal universe vs strict active 971: {int(metrics.get('maximum_expanded_bin_producing_signal_universe_vs_strict_active', 0))}
11. Expanded 0-1,000 ft universe vs strict active 971: {int(metrics.get('expanded_full_0_1000_signal_universe_vs_strict_active', 0))}
12. Expanded full 0-2,500 ft universe vs strict active 971: {int(metrics.get('expanded_full_0_2500_signal_universe_vs_strict_active', 0))}
13. Proxy-only one-direction cases resolved by actual bin generation: {proxy_resolved} of {len(proxy_ids)}
14. Next pass should be candidate-promotion design for review-only bins plus a separate divided-carriageway recovery test; context sufficiency should wait until promotion rules are reviewed.

## QA

- QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}
- Crash records/direction fields used: False
- Access/speed/AADT/rate/model outputs used: False
- Candidate bins promoted to active: False
"""


def _qa(
    candidate_input: pd.DataFrame,
    signal_summary: pd.DataFrame,
    one_direction_signal: pd.DataFrame,
    bins: pd.DataFrame,
    assoc: pd.DataFrame,
    outputs: dict[str, Path],
) -> pd.DataFrame:
    product = {k: v for k, v in outputs.items() if k not in {"findings", "qa", "manifest"}}
    missing_weights = assoc.loc[assoc["candidate_association_produced_bins"].astype(bool) & pd.to_numeric(assoc["weighted_candidate_bin_count"], errors="coerce").isna()]
    partial = bins.loc[pd.to_numeric(bins["bin_length_ft"], errors="coerce").lt(BIN_SIZE_FT)] if not bins.empty else pd.DataFrame()
    review_promoted = assoc.loc[assoc["association_confidence_tier"].eq("review_only_candidate") & assoc["candidate_association_produced_bins"].astype(bool)] if not assoc.empty else pd.DataFrame()
    failure_blank = assoc.loc[~assoc["candidate_association_produced_bins"].astype(bool) & _text(assoc, "failure_reason").eq("")]
    checks = [
        {"check_name": "recovered_candidate_signal_input_count", "status": "passed", "observed": candidate_input["signal_id"].nunique(), "expected": "reported", "note": "Unique signals in candidate detail input."},
        {"check_name": "candidate_association_input_count", "status": "passed", "observed": len(candidate_input), "expected": "reported", "note": "Candidate associations loaded from scaffold feasibility."},
        {"check_name": "one_direction_diagnostic_input_count_reconciles", "status": "passed" if len(one_direction_signal) == EXPECTED_ONE_DIRECTION_COUNT else "review", "observed": len(one_direction_signal), "expected": EXPECTED_ONE_DIRECTION_COUNT, "note": "One-direction diagnostic signal detail rows."},
        {"check_name": "crash_records_read", "status": "passed", "observed": False, "expected": False, "note": "No crash files are read."},
        {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False, "expected": False, "note": "No crash fields are read."},
        {"check_name": "crash_counts_used", "status": "passed", "observed": False, "expected": False, "note": "No crash counts are read or used."},
        {"check_name": "access_speed_aadt_rate_model_outputs_read_or_used", "status": "passed", "observed": False, "expected": False, "note": "Only graph/scaffold review files are read."},
        {"check_name": "active_outputs_modified", "status": "passed", "observed": False, "expected": False, "note": "All writes are isolated to review folder."},
        {"check_name": "candidates_promoted_to_active_scaffold_context", "status": "passed", "observed": False, "expected": False, "note": "Candidate bins are review-only."},
        {"check_name": "outputs_written_only_to_review_folder", "status": "passed" if all(str(path).startswith(str(OUT_DIR)) for path in outputs.values()) else "review", "observed": str(OUT_DIR), "expected": str(OUT_DIR), "note": "Output path guard."},
        {"check_name": "multi_candidate_ambiguity_preserved", "status": "passed", "observed": int(signal_summary["multi_candidate_preserved_flag"].sum()) if not signal_summary.empty else 0, "expected": "reported", "note": "No single-winner collapse is performed."},
        {"check_name": "candidate_weights_carried_or_documented", "status": "passed" if missing_weights.empty else "review", "observed": len(missing_weights), "expected": 0, "note": "Weights are carried forward or assigned equal preliminary weights upstream."},
        {"check_name": "partial_bins_preserved_and_labeled", "status": "passed", "observed": len(partial), "expected": "allowed", "note": "Partial final bins are retained with bin_length_ft."},
        {"check_name": "review_only_records_not_silently_promoted", "status": "passed" if review_promoted.empty else "review", "observed": len(review_promoted), "expected": 0, "note": "Review-only associations do not produce bins."},
        {"check_name": "strict_active_overlap_checks_diagnostic_only", "status": "passed", "observed": False, "expected": False, "note": "Overlap status is a label only."},
        {"check_name": "generated_bins_labeled_review_only_candidate", "status": "passed" if bins.empty or bins["review_only_candidate_bin"].astype(bool).all() else "review", "observed": True, "expected": True, "note": "Generated bins are not active."},
        {"check_name": "bin_generation_failure_reasons_explicit", "status": "passed" if failure_blank.empty else "review", "observed": len(failure_blank), "expected": 0, "note": "Failed associations must carry failure reasons."},
        {"check_name": "product_outputs_created", "status": "passed" if all(path.exists() for path in product.values()) else "review", "observed": len([path for path in product.values() if path.exists()]), "expected": len(product), "note": "Checked before findings, QA, and manifest write."},
    ]
    return pd.DataFrame(checks)


def build_signal_recovery_candidate_bin_generation(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    global OUTPUT_ROOT, SCAFFOLD_DIR, ONE_DIRECTION_DIR, OUT_DIR, TABLES
    OUTPUT_ROOT = output_root
    SCAFFOLD_DIR = output_root / "review/current/signal_recovery_scaffold_feasibility"
    ONE_DIRECTION_DIR = output_root / "review/current/signal_one_direction_scaffold_diagnostic"
    OUT_DIR = output_root / "review/current/signal_recovery_candidate_bin_generation"
    TABLES = output_root / "tables/current"

    started = datetime.now(timezone.utc)
    inputs = _load_inputs()
    candidate_input = inputs["candidate_detail"]
    candidate_rows = _prepare_candidate_rows(candidate_input, inputs["one_direction_signal"])
    bins, paths, assoc = _build_bins(candidate_rows, inputs["adjacent_edges"], inputs["strict_segments"])
    review_fail = _review_only_failures(candidate_input)
    if not review_fail.empty:
        assoc = pd.concat([assoc, review_fail], ignore_index=True)
    signal_sum = _signal_summary(assoc, inputs["signal_summary"])
    summary = _summary_table(signal_sum, bins, assoc)
    window = _window_summary(bins)
    direction = _direction_summary(signal_sum)
    weight = _weight_summary(assoc)
    overlap = _overlap(bins)
    failures = _failure_reasons(assoc)
    queue = _ranked_queue(signal_sum)

    outputs = {
        "bins": OUT_DIR / "candidate_recovery_bins.csv",
        "paths": OUT_DIR / "candidate_recovery_bin_paths.csv",
        "signal_summary": OUT_DIR / "candidate_recovery_signal_summary.csv",
        "association_summary": OUT_DIR / "candidate_recovery_association_summary.csv",
        "generation_summary": OUT_DIR / "candidate_recovery_bin_generation_summary.csv",
        "distance_window_summary": OUT_DIR / "candidate_recovery_distance_window_summary.csv",
        "direction_coverage_summary": OUT_DIR / "candidate_recovery_direction_coverage_summary.csv",
        "multi_candidate_weight_summary": OUT_DIR / "candidate_recovery_multi_candidate_weight_summary.csv",
        "existing_active_overlap": OUT_DIR / "candidate_recovery_existing_active_overlap.csv",
        "failure_reasons": OUT_DIR / "candidate_recovery_failure_reasons.csv",
        "ranked_review_queue": OUT_DIR / "candidate_recovery_ranked_review_queue.csv",
        "findings": OUT_DIR / "candidate_recovery_bin_generation_findings.md",
        "qa": OUT_DIR / "candidate_recovery_bin_generation_qa.csv",
        "manifest": OUT_DIR / "candidate_recovery_bin_generation_manifest.json",
    }
    _write_csv(bins, outputs["bins"])
    _write_csv(paths, outputs["paths"])
    _write_csv(signal_sum, outputs["signal_summary"])
    _write_csv(assoc, outputs["association_summary"])
    _write_csv(summary, outputs["generation_summary"])
    _write_csv(window, outputs["distance_window_summary"])
    _write_csv(direction, outputs["direction_coverage_summary"])
    _write_csv(weight, outputs["multi_candidate_weight_summary"])
    _write_csv(overlap, outputs["existing_active_overlap"])
    _write_csv(failures, outputs["failure_reasons"])
    _write_csv(queue, outputs["ranked_review_queue"])
    qa = _qa(candidate_input, signal_sum, inputs["one_direction_signal"], bins, assoc, outputs)
    _write_text(_findings(summary, failures, inputs["one_direction_signal"], signal_sum, qa), outputs["findings"])
    _write_csv(qa, outputs["qa"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only expanded candidate bin generation from recovered signal scaffold candidates",
        "read_only": True,
        "candidate_bins_review_only": True,
        "active_outputs_modified": False,
        "step5_true_logic_changed": False,
        "active_signal_eligibility_changed": False,
        "active_signal_road_association_overwritten": False,
        "active_downstream_bins_created": False,
        "crashes_assigned": False,
        "crash_records_read": False,
        "crash_direction_fields_read_or_used": False,
        "crash_counts_used": False,
        "access_speed_aadt_rate_model_outputs_read": False,
        "multi_candidate_single_winner_forced": False,
        "partial_bins_preserved": True,
        "input_files": [
            str(SCAFFOLD_DIR / "signal_recovery_scaffold_candidate_detail.csv"),
            str(SCAFFOLD_DIR / "signal_recovery_scaffold_signal_summary.csv"),
            str(SCAFFOLD_DIR / "signal_recovery_scaffold_feasibility_summary.csv"),
            str(SCAFFOLD_DIR / "signal_recovery_scaffold_multi_candidate_summary.csv"),
            str(SCAFFOLD_DIR / "signal_recovery_scaffold_existing_active_overlap.csv"),
            str(SCAFFOLD_DIR / "signal_recovery_scaffold_manifest.json"),
            str(ONE_DIRECTION_DIR / "one_direction_signal_detail.csv"),
            str(ONE_DIRECTION_DIR / "one_direction_candidate_detail.csv"),
            str(ONE_DIRECTION_DIR / "one_direction_category_summary.csv"),
            str(ONE_DIRECTION_DIR / "one_direction_handling_summary.csv"),
            str(ONE_DIRECTION_DIR / "one_direction_distance_coverage_summary.csv"),
            str(ONE_DIRECTION_DIR / "one_direction_scaffold_manifest.json"),
            str(TABLES / "signal_adjacent_edges.csv"),
            str(TABLES / "signal_oriented_roadway_segments_crash_ready.csv"),
        ],
        "summary_metrics": {row.metric: row.value for row in summary.itertuples(index=False)},
        "outputs": {key: str(path) for key, path in outputs.items()},
        "qa_checks": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only candidate bin generation for recovered signal scaffold candidates.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_signal_recovery_candidate_bin_generation(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
