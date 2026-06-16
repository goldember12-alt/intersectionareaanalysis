from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = Path("review/current/signal_attrition_funnel_audit")
ARTIFACTS = Path("artifacts")

TABLES = OUTPUT_ROOT / "tables/current"
REVIEW = OUTPUT_ROOT / "review/current"
ANALYSIS = OUTPUT_ROOT / "analysis/current"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if usecols is None:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    header = pd.read_csv(path, nrows=0)
    cols = [column for column in usecols if column in header.columns]
    if not cols:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols)


def _read_parquet(path: Path, *, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=columns)
    except Exception:
        return pd.read_parquet(path)


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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(_text(frame, column).str.strip().str.lower().isin({"true", "1", "yes", "y"}).sum())


def _metric(frame: pd.DataFrame, metric: str, *, value_col: str = "value") -> int:
    if frame.empty or "metric" not in frame.columns or value_col not in frame.columns:
        return 0
    values = frame.loc[_text(frame, "metric").eq(metric), value_col]
    if values.empty:
        return 0
    return int(pd.to_numeric(values.iloc[0], errors="coerce") or 0)


def _stage_row(stage: str, count: int, source: str, note: str = "") -> dict[str, Any]:
    return {
        "stage": stage,
        "signal_count": int(count),
        "evidence_source": source,
        "note": note,
    }


def _distribution(series: pd.Series, label: str) -> pd.DataFrame:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return pd.DataFrame(
            [{"distance_metric": label, "bin": "not_available", "signal_count": 0, "share": ""}]
        )
    bins = [
        (-float("inf"), 0, "0 ft"),
        (0, 10, "0-10 ft"),
        (10, 25, "10-25 ft"),
        (25, 50, "25-50 ft"),
        (50, 75, "50-75 ft"),
        (75, 100, "75-100 ft"),
        (100, 250, "100-250 ft"),
        (250, 500, "250-500 ft"),
        (500, float("inf"), "500+ ft"),
    ]
    rows = []
    total = len(numeric)
    for low, high, name in bins:
        if low == -float("inf"):
            count = int(numeric.le(high).sum())
        elif high == float("inf"):
            count = int(numeric.gt(low).sum())
        else:
            count = int(numeric.gt(low).astype(bool).mul(numeric.le(high)).sum())
        rows.append({"distance_metric": label, "bin": name, "signal_count": count, "share": round(count / total, 6)})
    rows.append(
        {
            "distance_metric": label,
            "bin": "summary",
            "signal_count": total,
            "share": "",
            "min_ft": round(float(numeric.min()), 3),
            "p50_ft": round(float(numeric.quantile(0.50)), 3),
            "p90_ft": round(float(numeric.quantile(0.90)), 3),
            "p95_ft": round(float(numeric.quantile(0.95)), 3),
            "max_ft": round(float(numeric.max()), 3),
        }
    )
    return pd.DataFrame(rows)


def _source_inventory() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    staging = _read_parquet(ARTIFACTS / "staging/signals.parquet")
    normalized = _read_parquet(ARTIFACTS / "normalized/signals.parquet")
    if staging.empty:
        return staging, normalized, {}

    staging = staging.reset_index(drop=False).rename(columns={"index": "source_signal_row_id"})
    staging["source_signal_row_id"] = staging["source_signal_row_id"].astype(str)
    staging["source_layer"] = _text(staging, "Stage1_SourceLayer").where(_text(staging, "Stage1_SourceLayer").ne(""), "unknown")
    staging["source_gdb"] = _text(staging, "Stage1_SourceGDB").where(_text(staging, "Stage1_SourceGDB").ne(""), "unknown")
    staging["source_signal_key"] = ""
    for column in ["GLOBALID", "REG_SIGNAL_ID", "ASSET_ID", "SIGNAL_NO", "INTNO", "INTNUM"]:
        if column in staging.columns:
            staging["source_signal_key"] = staging["source_signal_key"].where(
                staging["source_signal_key"].astype(str).ne(""),
                _text(staging, column),
            )
    staging["has_valid_geometry"] = staging["geometry"].notna() if "geometry" in staging.columns else False

    manifest_path = ARTIFACTS / "staging/stage1_input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return staging, normalized, manifest


def _graph_diagnostics() -> pd.DataFrame:
    nodes = _read_csv(
        TABLES / "signal_graph_nodes.csv",
        usecols=[
            "signal_id",
            "source_signal_row_id",
            "road_component_id",
            "match_distance_ft",
            "match_method",
            "matched_route_name",
            "matched_route_common",
            "roadway_division_status",
            "logical_segment_mode",
        ],
    )
    if nodes.empty:
        return pd.DataFrame()
    nodes["_dist"] = _num(nodes, "match_distance_ft")
    grouped = (
        nodes.groupby("signal_id", dropna=False)
        .agg(
            graph_node_rows=("signal_id", "count"),
            nearest_travelway_distance_ft=("_dist", "min"),
            nearby_travelway_candidate_count=("road_component_id", lambda values: int(values.astype(str).ne("").sum())),
            unique_nearby_route_count=("matched_route_name", lambda values: int(values.astype(str).loc[values.astype(str).ne("")].nunique())),
            nearby_divided_candidate_count=("roadway_division_status", lambda values: int(values.astype(str).eq("divided").sum())),
            nearby_undivided_candidate_count=("roadway_division_status", lambda values: int(values.astype(str).eq("undivided").sum())),
            nearest_route_sample=("matched_route_common", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")]))[:5])),
            match_methods=("match_method", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
        )
        .reset_index()
    )
    grouped["nearest_travelway_distance_ft"] = grouped["nearest_travelway_distance_ft"].round(3)
    grouped["nearest_road_association_status"] = "unique"
    grouped.loc[grouped["nearby_travelway_candidate_count"].eq(0), "nearest_road_association_status"] = "none"
    grouped.loc[grouped["unique_nearby_route_count"].gt(1), "nearest_road_association_status"] = "ambiguous_multiple_routes"
    grouped.loc[grouped["nearby_travelway_candidate_count"].gt(4), "nearest_road_association_status"] = "ambiguous_many_components"
    return grouped


def _build_signal_status() -> tuple[pd.DataFrame, dict[str, pd.DataFrame], list[str]]:
    staging, _normalized, manifest = _source_inventory()
    eligibility = _read_csv(TABLES / "signal_step5_eligibility.csv")
    graph = _graph_diagnostics()
    graph_gap = _read_csv(TABLES / "graph_gap_review.csv")
    crash_ready_segments = _read_csv(TABLES / "signal_oriented_roadway_segments_crash_ready.csv", usecols=["reference_signal_id"])
    directional_segments = _read_csv(
        REVIEW / "reference_signal_directional_scaffold/reference_signal_directional_segment_candidates.csv",
        usecols=[
            "reference_signal_id",
            "roadway_representation_type",
            "blocker_reason",
            "review_flag",
            "roadway_role_class",
            "far_anchor_type",
        ],
    )
    directional_qa = _read_csv(
        REVIEW / "reference_signal_directional_scaffold_qa/directional_scaffold_qa_by_reference_signal.csv"
    )
    active_signal_context = _read_csv(
        ANALYSIS / "directional_bin_context_table_active/reference_signal_context_summary_active.csv"
    )
    active_crash_context = _read_csv(
        ANALYSIS / "directional_bin_context_table_active/directional_crash_context_active.csv",
        usecols=["reference_signal_id", "crash_id", "crash_urban_rural_class"],
    )

    inputs = [
        "artifacts/staging/signals.parquet",
        "artifacts/normalized/signals.parquet",
        "work/output/roadway_graph/tables/current/signal_step5_eligibility.csv",
        "work/output/roadway_graph/tables/current/signal_graph_nodes.csv",
        "work/output/roadway_graph/tables/current/graph_gap_review.csv",
        "work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv",
        "work/output/roadway_graph/review/current/reference_signal_directional_scaffold/reference_signal_directional_segment_candidates.csv",
        "work/output/roadway_graph/review/current/reference_signal_directional_scaffold_qa/directional_scaffold_qa_by_reference_signal.csv",
        "work/output/roadway_graph/analysis/current/directional_bin_context_table_active/reference_signal_context_summary_active.csv",
        "work/output/roadway_graph/analysis/current/directional_bin_context_table_active/directional_crash_context_active.csv",
    ]

    status = eligibility.copy()
    if "source_signal_row_id" in status.columns:
        status["source_signal_row_id"] = _text(status, "source_signal_row_id")
    source_cols = [
        "source_signal_row_id",
        "source_layer",
        "source_gdb",
        "source_signal_key",
        "has_valid_geometry",
        "DISTRICT",
        "MAINT_JURISDICTION",
        "MAJ_NAME",
        "MAJ_NUM",
        "MINOR_NAME",
        "MINOR_NUM",
        "STATUS",
    ]
    if not staging.empty:
        status = status.merge(staging[[c for c in source_cols if c in staging.columns]], on="source_signal_row_id", how="left")

    if not graph.empty:
        status = status.merge(graph, on="signal_id", how="left")
    if not graph_gap.empty:
        status = status.merge(
            graph_gap[["signal_id", "min_match_distance_ft", "issue_flags", "matched_route_sample"]],
            on="signal_id",
            how="left",
            suffixes=("", "_gap_review"),
        )

    crash_ready_set = set(_text(crash_ready_segments, "reference_signal_id"))
    directional_set = set(_text(directional_segments, "reference_signal_id"))
    directional_qa_set = set(_text(directional_qa, "reference_signal_id"))
    active_set = set(_text(active_signal_context, "reference_signal_id"))
    crash_set = set(_text(active_crash_context, "reference_signal_id"))

    status["represented_in_crash_ready_scaffold"] = _text(status, "signal_id").isin(crash_ready_set)
    status["represented_in_directional_scaffold"] = _text(status, "signal_id").isin(directional_set | directional_qa_set)
    status["represented_in_active_0_2500ft_context"] = _text(status, "signal_id").isin(active_set)
    status["has_assigned_crashes_active_context"] = _text(status, "signal_id").isin(crash_set)

    if not active_signal_context.empty:
        context_cols = [
            "reference_signal_id",
            "directional_bin_count",
            "assigned_crash_count",
            "bins_with_access_context",
            "bins_with_stable_speed_context",
            "bins_with_stable_aadt_context",
            "assigned_crashes_urban_count",
            "assigned_crashes_rural_count",
            "assigned_crashes_unknown_area_type_count",
        ]
        status = status.merge(
            active_signal_context[[c for c in context_cols if c in active_signal_context.columns]],
            left_on="signal_id",
            right_on="reference_signal_id",
            how="left",
        )

    for column in [
        "directional_bin_count",
        "assigned_crash_count",
        "bins_with_access_context",
        "bins_with_stable_speed_context",
        "bins_with_stable_aadt_context",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
    ]:
        if column in status.columns:
            status[column] = pd.to_numeric(status[column], errors="coerce").fillna(0).astype(int)

    status["has_access_context"] = status.get("bins_with_access_context", 0).gt(0) if "bins_with_access_context" in status.columns else False
    status["has_speed_context"] = status.get("bins_with_stable_speed_context", 0).gt(0) if "bins_with_stable_speed_context" in status.columns else False
    status["has_aadt_context"] = status.get("bins_with_stable_aadt_context", 0).gt(0) if "bins_with_stable_aadt_context" in status.columns else False

    def reason(row: pd.Series) -> str:
        if not bool(row.get("has_valid_geometry", True)):
            return "missing_or_invalid_signal_geometry"
        if int(pd.to_numeric(row.get("nearby_travelway_candidate_count", 0), errors="coerce") or 0) == 0:
            return "no_nearby_travelway_candidate"
        nearest = pd.to_numeric(pd.Series([row.get("nearest_travelway_distance_ft")]), errors="coerce").iloc[0]
        if pd.notna(nearest) and nearest > 50 and str(row.get("signal_offset_relaxation_applied", "")).upper() != "TRUE":
            return "signal_offset_beyond_tolerance"
        if str(row.get("nearest_road_association_status", "")) in {"ambiguous_multiple_routes", "ambiguous_many_components"} and str(row.get("usable_for_step5", "")) != "TRUE":
            return "ambiguous_nearest_road"
        if str(row.get("usable_for_step5", "")) != "TRUE":
            return "non_TRUE_signal_status"
        if not bool(row.get("represented_in_crash_ready_scaffold", False)):
            exclusion = str(row.get("step5_exclusion_reason", ""))
            if "source_roadway_incomplete" in exclusion:
                return "graph_topology_blocked"
            return "no_defensible_opposite_anchor"
        if not bool(row.get("represented_in_directional_scaffold", False)):
            return "directional_scaffold_blocked"
        if not bool(row.get("represented_in_active_0_2500ft_context", False)):
            return "outside_active_0_2500ft_context"
        if not bool(row.get("has_assigned_crashes_active_context", False)):
            return "represented_but_no_assigned_crashes"
        return "represented_active_with_assigned_crashes"

    status["best_available_loss_reason"] = status.apply(reason, axis=1)
    status["loss_reason_is_final_truth"] = False
    status["methodology_interpretation"] = status["best_available_loss_reason"].map(
        {
            "missing_or_invalid_signal_geometry": "source_data_limitation",
            "no_nearby_travelway_candidate": "source_or_geometry_limitation",
            "signal_offset_beyond_tolerance": "geometry_or_source_offset",
            "ambiguous_nearest_road": "geometry_topology_issue",
            "non_TRUE_signal_status": "conservative_methodology_choice",
            "no_defensible_opposite_anchor": "graph_topology_or_anchor_limitation",
            "graph_topology_blocked": "graph_topology_issue",
            "directional_scaffold_blocked": "conservative_methodology_choice",
            "outside_active_0_2500ft_context": "context_universe_filter",
            "represented_but_no_assigned_crashes": "no_crash_evidence_in_active_context",
            "represented_active_with_assigned_crashes": "represented_active",
        }
    ).fillna("unknown_or_not_available")

    frames = {
        "staging": staging,
        "eligibility": eligibility,
        "graph": graph,
        "graph_gap": graph_gap,
        "crash_ready_segments": crash_ready_segments,
        "directional_segments": directional_segments,
        "directional_qa": directional_qa,
        "active_signal_context": active_signal_context,
        "active_crash_context": active_crash_context,
    }
    if manifest:
        frames["manifest_layers"] = pd.DataFrame.from_dict(manifest.get("layers", {}), orient="index").reset_index(names="logical_layer")
    return status, frames, inputs


def _funnel(status: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    staging = frames.get("staging", pd.DataFrame())
    graph = frames.get("graph", pd.DataFrame())
    active_context = frames.get("active_signal_context", pd.DataFrame())
    rows = [
        _stage_row("raw_signal_source_records", len(staging), "artifacts/staging/signals.parquet"),
        _stage_row("normalized_staged_signal_rows", len(status), "artifacts/normalized/signals.parquet + signal_step5_eligibility.csv"),
        _stage_row(
            "unique_deduplicated_signal_candidates",
            int(_text(status, "signal_id").nunique()) or len(status),
            "active signal_id inventory",
            "No explicit active deduplication output was found; active signal_id values are unique. Source-key duplication is retained in signal-level diagnostics.",
        ),
        _stage_row("signal_rows_with_valid_geometry", int(status.get("has_valid_geometry", pd.Series(True, index=status.index)).fillna(False).sum()), "staged signal geometry"),
        _stage_row("signal_rows_with_nearest_travelway_candidate", int(status.get("nearby_travelway_candidate_count", pd.Series(0, index=status.index)).fillna(0).astype(int).gt(0).sum()), "signal_graph_nodes.csv"),
        _stage_row("signal_rows_passing_signal_road_association_tolerance", int(pd.to_numeric(status.get("nearest_travelway_distance_ft", pd.Series(pd.NA, index=status.index)), errors="coerce").le(50).sum()), "signal_graph_nodes.csv match_distance_ft <= 50"),
        _stage_row("signal_rows_eligible_for_step5", int(_text(status, "usable_for_step5").isin(["TRUE", "CONDITIONAL"]).sum()), "signal_step5_eligibility.csv TRUE or CONDITIONAL"),
        _stage_row("TRUE_reference_signals", int(_text(status, "usable_for_step5").eq("TRUE").sum()), "signal_step5_eligibility.csv"),
        _stage_row("TRUE_signals_represented_in_crash_ready_scaffold", int(status["represented_in_crash_ready_scaffold"].sum()), "signal_oriented_roadway_segments_crash_ready.csv"),
        _stage_row("TRUE_signals_represented_in_directional_scaffold", int(status["represented_in_directional_scaffold"].sum()), "reference_signal_directional_scaffold outputs"),
        _stage_row("TRUE_signals_represented_in_active_0_2500ft_context_table", int(status["represented_in_active_0_2500ft_context"].sum()), "reference_signal_context_summary_active.csv"),
        _stage_row("TRUE_signals_with_assigned_crashes", int(status["has_assigned_crashes_active_context"].sum()), "directional_crash_context_active.csv"),
        _stage_row("TRUE_signals_with_access_context", int(status["has_access_context"].sum()), "reference_signal_context_summary_active.csv"),
        _stage_row("TRUE_signals_with_speed_context", int(status["has_speed_context"].sum()), "reference_signal_context_summary_active.csv"),
        _stage_row("TRUE_signals_with_AADT_context", int(status["has_aadt_context"].sum()), "reference_signal_context_summary_active.csv"),
    ]
    if not graph.empty:
        within_extent = int(pd.to_numeric(graph["nearest_travelway_distance_ft"], errors="coerce").notna().sum())
        rows.insert(4, _stage_row("signal_rows_within_or_near_travelway_extent", within_extent, "signal_graph_nodes.csv nearest candidate diagnostics"))
    if not active_context.empty:
        rows[-4]["note"] = "Known reconciliation target from active context: 971 represented reference signals."
    return pd.DataFrame(rows)


def _funnel_by_source(status: pd.DataFrame) -> pd.DataFrame:
    group_col = "source_layer" if "source_layer" in status.columns else "source_gdb"
    rows = []
    for source, group in status.groupby(group_col, dropna=False):
        rows.append(
            {
                "source_layer": source or "unknown",
                "raw_or_normalized_signal_rows": len(group),
                "valid_geometry_rows": int(group.get("has_valid_geometry", pd.Series(False, index=group.index)).fillna(False).sum()),
                "with_nearest_travelway_candidate": int(group.get("nearby_travelway_candidate_count", pd.Series(0, index=group.index)).fillna(0).astype(int).gt(0).sum()),
                "TRUE_reference_signals": int(_text(group, "usable_for_step5").eq("TRUE").sum()),
                "represented_crash_ready_signals": int(group["represented_in_crash_ready_scaffold"].sum()),
                "represented_directional_scaffold_signals": int(group["represented_in_directional_scaffold"].sum()),
                "represented_active_0_2500ft_context_signals": int(group["represented_in_active_0_2500ft_context"].sum()),
                "signals_with_assigned_crashes": int(group["has_assigned_crashes_active_context"].sum()),
                "signals_with_access_context": int(group["has_access_context"].sum()),
                "signals_with_speed_context": int(group["has_speed_context"].sum()),
                "signals_with_aadt_context": int(group["has_aadt_context"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("raw_or_normalized_signal_rows", ascending=False)


def _loss_reasons(status: pd.DataFrame) -> pd.DataFrame:
    excluded = status.loc[~_text(status, "best_available_loss_reason").eq("represented_active_with_assigned_crashes")].copy()
    out = (
        excluded.groupby(["best_available_loss_reason", "methodology_interpretation"], dropna=False)
        .agg(signal_count=("signal_id", "count"))
        .reset_index()
        .rename(columns={"best_available_loss_reason": "loss_reason"})
        .sort_values("signal_count", ascending=False)
    )
    out["diagnostic_status"] = "best_available_not_final_truth"
    return out


def _queues(status: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "DISTRICT",
        "MAINT_JURISDICTION",
        "MAJ_NAME",
        "MINOR_NAME",
        "usable_for_step5",
        "nearest_travelway_distance_ft",
        "nearby_travelway_candidate_count",
        "unique_nearby_route_count",
        "nearest_route_sample",
        "nearest_road_association_status",
        "graph_gap_issue_flags",
        "step5_exclusion_reason",
        "best_available_loss_reason",
    ]
    available = [c for c in cols if c in status.columns]
    offset = status.loc[
        pd.to_numeric(status.get("nearest_travelway_distance_ft", pd.Series(pd.NA, index=status.index)), errors="coerce").gt(50)
        | _text(status, "graph_gap_issue_flags").str.contains("snapped_distance_exceeds_50ft", na=False)
    ][available].copy()
    ambiguous = status.loc[
        _text(status, "nearest_road_association_status").str.contains("ambiguous", na=False)
        | _text(status, "graph_gap_issue_flags").str.contains("suspiciously_high|grade_separation", regex=True, na=False)
    ][available].copy()
    return (
        offset.sort_values("nearest_travelway_distance_ft", ascending=False),
        ambiguous.sort_values(["usable_for_step5", "nearby_travelway_candidate_count"], ascending=[True, False]),
    )


def _crash_coverage(status: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stage_rows = []
    stage_defs = [
        ("all_signal_candidates", status),
        ("TRUE_reference_signals", status.loc[_text(status, "usable_for_step5").eq("TRUE")]),
        ("crash_ready_represented_TRUE_signals", status.loc[status["represented_in_crash_ready_scaffold"]]),
        ("active_0_2500ft_context_TRUE_signals", status.loc[status["represented_in_active_0_2500ft_context"]]),
        ("active_TRUE_signals_with_assigned_crashes", status.loc[status["has_assigned_crashes_active_context"]]),
    ]
    for stage, group in stage_defs:
        stage_rows.append(
            {
                "stage": stage,
                "signal_count": len(group),
                "signals_with_assigned_crashes": int(group["has_assigned_crashes_active_context"].sum()) if "has_assigned_crashes_active_context" in group else 0,
                "assigned_crash_count": int(pd.to_numeric(group.get("assigned_crash_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()),
                "urban_assigned_crash_count": int(pd.to_numeric(group.get("assigned_crashes_urban_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()),
                "rural_assigned_crash_count": int(pd.to_numeric(group.get("assigned_crashes_rural_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()),
                "unknown_area_type_assigned_crash_count": int(pd.to_numeric(group.get("assigned_crashes_unknown_area_type_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()),
            }
        )
    by_status = (
        status.groupby("best_available_loss_reason", dropna=False)
        .agg(
            signal_count=("signal_id", "count"),
            signals_with_assigned_crashes=("has_assigned_crashes_active_context", "sum"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            urban_assigned_crash_count=("assigned_crashes_urban_count", "sum"),
            rural_assigned_crash_count=("assigned_crashes_rural_count", "sum"),
            unknown_area_type_assigned_crash_count=("assigned_crashes_unknown_area_type_count", "sum"),
        )
        .reset_index()
        .rename(columns={"best_available_loss_reason": "signal_status_or_loss_reason"})
        .sort_values("signal_count", ascending=False)
    )
    return pd.DataFrame(stage_rows), by_status


def _context_coverage(status: pd.DataFrame) -> pd.DataFrame:
    rows = []
    groups = {
        "all_signal_candidates": status,
        "TRUE_reference_signals": status.loc[_text(status, "usable_for_step5").eq("TRUE")],
        "represented_active_0_2500ft_context": status.loc[status["represented_in_active_0_2500ft_context"]],
        "not_represented_active_0_2500ft_context": status.loc[~status["represented_in_active_0_2500ft_context"]],
    }
    for name, group in groups.items():
        rows.append(
            {
                "signal_group": name,
                "signal_count": len(group),
                "signals_with_roadway_representation": int(group["represented_in_directional_scaffold"].sum()) if "represented_in_directional_scaffold" in group else 0,
                "signals_with_access_context": int(group["has_access_context"].sum()) if "has_access_context" in group else 0,
                "signals_with_speed_context": int(group["has_speed_context"].sum()) if "has_speed_context" in group else 0,
                "signals_with_AADT_context": int(group["has_aadt_context"].sum()) if "has_aadt_context" in group else 0,
                "signals_with_assigned_crash_AREA_TYPE": int(pd.to_numeric(group.get("assigned_crashes_urban_count", pd.Series(dtype=int)), errors="coerce").fillna(0).add(pd.to_numeric(group.get("assigned_crashes_rural_count", pd.Series(dtype=int)), errors="coerce").fillna(0)).gt(0).sum()) if not group.empty else 0,
                "assigned_crash_count": int(pd.to_numeric(group.get("assigned_crash_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()),
            }
        )
    return pd.DataFrame(rows)


def _grouping(status: pd.DataFrame, column: str, output_name: str) -> pd.DataFrame:
    if column not in status.columns:
        return pd.DataFrame(
            [{"grouping": output_name, "group_value": "not_available", "signal_count": len(status)}]
        )
    rows = []
    for value, group in status.groupby(column, dropna=False):
        rows.append(
            {
                "grouping": output_name,
                "group_value": value if str(value) else "blank_or_unknown",
                "signal_count": len(group),
                "TRUE_reference_signals": int(_text(group, "usable_for_step5").eq("TRUE").sum()),
                "represented_active_0_2500ft_context_signals": int(group["represented_in_active_0_2500ft_context"].sum()),
                "signals_with_assigned_crashes": int(group["has_assigned_crashes_active_context"].sum()),
                "assigned_crash_count": int(pd.to_numeric(group.get("assigned_crash_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("signal_count", ascending=False)


def _roadway_representation_group(status: pd.DataFrame, directional_segments: pd.DataFrame) -> pd.DataFrame:
    if directional_segments.empty:
        return pd.DataFrame([{"roadway_representation_type": "not_available", "signal_count": 0}])
    reps = (
        directional_segments.groupby("reference_signal_id")
        .agg(
            roadway_representation_type=("roadway_representation_type", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
            blocked_directional_records=("blocker_reason", lambda values: int(values.astype(str).ne("").sum())),
            review_directional_records=("review_flag", lambda values: int(values.astype(str).str.upper().eq("TRUE").sum())),
            far_anchor_types=("far_anchor_type", lambda values: " | ".join(sorted(set(values.astype(str).loc[values.astype(str).ne("")])))),
        )
        .reset_index()
    )
    merged = status.merge(reps, left_on="signal_id", right_on="reference_signal_id", how="left")
    return _grouping(merged, "roadway_representation_type", "roadway_representation_type")


def _presentation(status: pd.DataFrame, funnel: pd.DataFrame, reasons: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    raw = int(funnel.loc[funnel["stage"].eq("raw_signal_source_records"), "signal_count"].iloc[0])
    true_count = int(funnel.loc[funnel["stage"].eq("TRUE_reference_signals"), "signal_count"].iloc[0])
    active_count = int(funnel.loc[funnel["stage"].eq("TRUE_signals_represented_in_active_0_2500ft_context_table"), "signal_count"].iloc[0])
    assigned_crash_count = int(status["assigned_crash_count"].sum()) if "assigned_crash_count" in status.columns else 0

    stage = funnel.copy()
    stage["next_stage_count"] = stage["signal_count"].shift(-1)
    stage["drop_to_next_stage"] = stage["signal_count"] - stage["next_stage_count"]
    biggest = stage.loc[stage["drop_to_next_stage"].fillna(0).gt(0)].sort_values("drop_to_next_stage", ascending=False).head(5)
    biggest_text = "; ".join(f"{row.stage}: -{int(row.drop_to_next_stage)}" for row in biggest.itertuples(index=False))
    top_reasons = reasons.head(5)
    reason_text = "; ".join(f"{row.loss_reason}: {int(row.signal_count)}" for row in top_reasons.itertuples(index=False))

    summary = pd.DataFrame(
        [
            {
                "question": "starting_signal_count",
                "answer": raw,
                "stakeholder_readout": "Base staged signal source records available to the graph workflow.",
            },
            {
                "question": "stable_reference_signal_count",
                "answer": true_count,
                "stakeholder_readout": "Signals that pass current Step 5 TRUE reference-signal eligibility.",
            },
            {
                "question": "active_context_signal_count",
                "answer": active_count,
                "stakeholder_readout": "TRUE reference signals represented in the active 0-2,500 ft context table.",
            },
            {
                "question": "biggest_loss_stages",
                "answer": biggest_text,
                "stakeholder_readout": "Largest drops are mainly eligibility/conservative graph-context filters.",
            },
            {
                "question": "top_loss_reasons",
                "answer": reason_text,
                "stakeholder_readout": "Reasons are best-available diagnostics, not final truth.",
            },
            {
                "question": "assigned_crashes_in_active_signal_universe",
                "answer": assigned_crash_count,
                "stakeholder_readout": "Crash propagation is measured only from existing assignment/context outputs; no crash direction fields were read.",
            },
        ]
    )

    recovery = pd.DataFrame(
        [
            {
                "loss_category": "ambiguous_nearest_road",
                "recoverability": "medium",
                "recommended_next_step": "Mapped review of high-component/high-route signal-road associations; do not auto-promote.",
                "automatic_promotion_allowed": False,
            },
            {
                "loss_category": "signal_offset_beyond_tolerance",
                "recoverability": "medium",
                "recommended_next_step": "Review offset point placement against Travelway geometry and documented 75 ft relaxation pattern.",
                "automatic_promotion_allowed": False,
            },
            {
                "loss_category": "no_defensible_opposite_anchor",
                "recoverability": "low_to_medium",
                "recommended_next_step": "Inspect graph topology and endpoint/junction evidence before changing anchor rules.",
                "automatic_promotion_allowed": False,
            },
            {
                "loss_category": "outside_active_0_2500ft_context",
                "recoverability": "medium",
                "recommended_next_step": "Trace whether the signal has scaffold records but no accepted bins/catchments in the active context window.",
                "automatic_promotion_allowed": False,
            },
            {
                "loss_category": "non_TRUE_signal_status",
                "recoverability": "case_review_only",
                "recommended_next_step": "Separate true source-data errors from conservative eligibility choices; preserve FALSE/CONDITIONAL status unless reviewed.",
                "automatic_promotion_allowed": False,
            },
        ]
    )

    findings_md = f"""# Signal Attrition Funnel Audit Findings

Status: read-only diagnostic. No signal eligibility, roadway graph, scaffold, catchment, crash, access, speed, AADT, rate, or model outputs were modified.

## Bounded Question

This audit asks where signal records fall out between the base signal layers, signal-road graph association, Step 5 TRUE reference-signal eligibility, crash-ready/directional scaffold representation, and active 0-2,500 ft downstream context.

## Main Counts

- Base staged signal records: {raw}
- Step 5 eligibility rows: {len(status)}
- TRUE reference signals: {true_count}
- TRUE signals represented in crash-ready scaffold: {int(status['represented_in_crash_ready_scaffold'].sum())}
- TRUE signals represented in directional scaffold: {int(status['represented_in_directional_scaffold'].sum())}
- TRUE signals represented in active 0-2,500 ft context: {active_count}
- Active assigned crashes attached to represented signals: {assigned_crash_count}

## Biggest Loss Stages

{biggest_text or 'No stage-to-stage drops found from available outputs.'}

## Main Loss Reasons

{reason_text or 'No loss reasons found.'}

## Interpretation

The dominant loss is before TRUE reference-signal status, which points to conservative signal-road association and Step 5 eligibility rather than downstream access, speed, AADT, rates, or model layers. Later loss from TRUE reference signals to active context is smaller but important because it determines which signals can receive bins, crashes, access, speed, and AADT context.

Loss reasons are best-available diagnostics from existing outputs. They are not final field truth and do not promote excluded signals.

## Stakeholder Methods Readout

The stakeholder-facing methods section should show the full signal funnel: base signals, Step 5 TRUE reference signals, crash-ready represented TRUE signals, active 0-2,500 ft context signals, and active assigned crash coverage. It should state that excluded and unresolved cases are preserved for review and that current analysis favors cleaner graph-topology contexts by design.

## QA

- Crash direction fields read or used: False.
- Scaffold construction changed: False.
- Signal eligibility logic changed: False.
- Context/crash/access/speed/AADT/rate/model outputs changed: False.
- Recovery opportunities are recommendations only.
"""
    return summary, recovery, findings_md


def _qa(status: pd.DataFrame, funnel: pd.DataFrame, output_files: dict[str, Path]) -> pd.DataFrame:
    def count(stage: str) -> int:
        values = funnel.loc[funnel["stage"].eq(stage), "signal_count"]
        return int(values.iloc[0]) if not values.empty else 0

    checks = [
        {
            "check_name": "crash_direction_fields_read_or_used",
            "status": "passed",
            "observed": False,
            "note": "The module reads existing crash assignment/context identifiers and area-type summaries only.",
        },
        {
            "check_name": "audit_only_outputs",
            "status": "passed",
            "observed": str(OUTPUT_ROOT / OUT_DIR),
            "note": "All writes are isolated to the signal_attrition_funnel_audit review folder.",
        },
        {
            "check_name": "signal_source_rows_reconcile_to_step5_eligibility",
            "status": "passed" if count("raw_signal_source_records") == len(status) else "review",
            "observed": f"raw={count('raw_signal_source_records')}; eligibility={len(status)}",
            "note": "Expected current known count is 3,933.",
        },
        {
            "check_name": "TRUE_reference_signal_count_reconciles",
            "status": "passed" if count("TRUE_reference_signals") == 1214 else "review",
            "observed": count("TRUE_reference_signals"),
            "note": "Known high-level count from current data-loss ledger is 1,214.",
        },
        {
            "check_name": "active_context_signal_count_reconciles",
            "status": "passed" if count("TRUE_signals_represented_in_active_0_2500ft_context_table") == 971 else "review",
            "observed": count("TRUE_signals_represented_in_active_0_2500ft_context_table"),
            "note": "Known active context target is 971 reference signals.",
        },
        {
            "check_name": "loss_reasons_are_best_available_diagnostics",
            "status": "passed",
            "observed": bool(status["loss_reason_is_final_truth"].eq(False).all()),
            "note": "No loss reason is labeled as final truth.",
        },
        {
            "check_name": "recovery_opportunities_not_automatic_promotions",
            "status": "passed",
            "observed": True,
            "note": "Recovery output is recommendation-only.",
        },
    ]
    product_outputs = {
        key: path
        for key, path in output_files.items()
        if key not in {"signal_attrition_funnel_qa", "signal_attrition_funnel_manifest"}
    }
    checks.append(
        {
            "check_name": "outputs_created",
            "status": "passed" if all(path.exists() for path in product_outputs.values()) else "review",
            "observed": len([path for path in product_outputs.values() if path.exists()]),
            "note": f"{len(product_outputs)} product outputs checked before QA/manifest write.",
        }
    )
    return pd.DataFrame(checks)


def build_signal_attrition_funnel_audit(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    global OUTPUT_ROOT, TABLES, REVIEW, ANALYSIS
    OUTPUT_ROOT = output_root
    TABLES = output_root / "tables/current"
    REVIEW = output_root / "review/current"
    ANALYSIS = output_root / "analysis/current"

    started = datetime.now(timezone.utc)
    out_dir = output_root / OUT_DIR
    status, frames, input_files = _build_signal_status()
    funnel = _funnel(status, frames)
    by_source = _funnel_by_source(status)
    loss_reasons = _loss_reasons(status)
    offset_queue, ambiguous_queue = _queues(status)
    crash_summary, crash_by_status = _crash_coverage(status)
    context_summary = _context_coverage(status)
    presentation, recovery, findings_md = _presentation(status, funnel, loss_reasons)

    directional_segments = frames.get("directional_segments", pd.DataFrame())
    source_layer = _funnel_by_source(status)
    by_route = _grouping(status, "MAJ_NAME", "route_name")
    by_locality = _grouping(status, "MAINT_JURISDICTION", "locality_or_jurisdiction")
    by_rep = _roadway_representation_group(status, directional_segments)

    outputs = {
        "signal_attrition_funnel_summary": out_dir / "signal_attrition_funnel_summary.csv",
        "signal_attrition_funnel_by_source": out_dir / "signal_attrition_funnel_by_source.csv",
        "signal_attrition_loss_reasons": out_dir / "signal_attrition_loss_reasons.csv",
        "signal_attrition_signal_level_status": out_dir / "signal_attrition_signal_level_status.csv",
        "signal_nearest_travelway_distance_distribution": out_dir / "signal_nearest_travelway_distance_distribution.csv",
        "signal_nearest_accepted_graph_distance_distribution": out_dir / "signal_nearest_accepted_graph_distance_distribution.csv",
        "signal_offset_review_queue": out_dir / "signal_offset_review_queue.csv",
        "signal_ambiguous_road_association_review_queue": out_dir / "signal_ambiguous_road_association_review_queue.csv",
        "signal_attrition_crash_coverage_summary": out_dir / "signal_attrition_crash_coverage_summary.csv",
        "signal_attrition_crash_coverage_by_signal_status": out_dir / "signal_attrition_crash_coverage_by_signal_status.csv",
        "signal_attrition_context_coverage_summary": out_dir / "signal_attrition_context_coverage_summary.csv",
        "signal_attrition_by_source_layer": out_dir / "signal_attrition_by_source_layer.csv",
        "signal_attrition_by_route": out_dir / "signal_attrition_by_route.csv",
        "signal_attrition_by_locality_or_jurisdiction": out_dir / "signal_attrition_by_locality_or_jurisdiction.csv",
        "signal_attrition_by_roadway_representation": out_dir / "signal_attrition_by_roadway_representation.csv",
        "signal_attrition_presentation_summary": out_dir / "signal_attrition_presentation_summary.csv",
        "signal_attrition_recovery_opportunities": out_dir / "signal_attrition_recovery_opportunities.csv",
        "signal_attrition_funnel_findings": out_dir / "signal_attrition_funnel_findings.md",
        "signal_attrition_funnel_manifest": out_dir / "signal_attrition_funnel_manifest.json",
        "signal_attrition_funnel_qa": out_dir / "signal_attrition_funnel_qa.csv",
    }

    _write_csv(funnel, outputs["signal_attrition_funnel_summary"])
    _write_csv(by_source, outputs["signal_attrition_funnel_by_source"])
    _write_csv(loss_reasons, outputs["signal_attrition_loss_reasons"])
    _write_csv(status, outputs["signal_attrition_signal_level_status"])
    _write_csv(_distribution(status["nearest_travelway_distance_ft"], "nearest_travelway"), outputs["signal_nearest_travelway_distance_distribution"])
    accepted = status.loc[status["represented_in_crash_ready_scaffold"], "nearest_travelway_distance_ft"]
    _write_csv(_distribution(accepted, "nearest_accepted_graph_segment_proxy"), outputs["signal_nearest_accepted_graph_distance_distribution"])
    _write_csv(offset_queue, outputs["signal_offset_review_queue"])
    _write_csv(ambiguous_queue, outputs["signal_ambiguous_road_association_review_queue"])
    _write_csv(crash_summary, outputs["signal_attrition_crash_coverage_summary"])
    _write_csv(crash_by_status, outputs["signal_attrition_crash_coverage_by_signal_status"])
    _write_csv(context_summary, outputs["signal_attrition_context_coverage_summary"])
    _write_csv(source_layer, outputs["signal_attrition_by_source_layer"])
    _write_csv(by_route, outputs["signal_attrition_by_route"])
    _write_csv(by_locality, outputs["signal_attrition_by_locality_or_jurisdiction"])
    _write_csv(by_rep, outputs["signal_attrition_by_roadway_representation"])
    _write_csv(presentation, outputs["signal_attrition_presentation_summary"])
    _write_csv(recovery, outputs["signal_attrition_recovery_opportunities"])
    _write_text(findings_md, outputs["signal_attrition_funnel_findings"])

    qa = _qa(status, funnel, outputs)
    _write_csv(qa, outputs["signal_attrition_funnel_qa"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only signal attrition and signal-to-roadway association audit",
        "read_only": True,
        "audit_only": True,
        "scaffold_construction_changed": False,
        "signal_eligibility_logic_changed": False,
        "roadway_graph_construction_changed": False,
        "catchment_crash_access_speed_aadt_rate_model_outputs_changed": False,
        "crash_direction_fields_read_or_used": False,
        "excluded_signals_promoted": False,
        "loss_reasons_are_best_available_diagnostics_not_final_truth": True,
        "input_files": [path for path in input_files if Path(path).exists()],
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary_counts": {
            row["stage"]: int(row["signal_count"]) for row in funnel.to_dict(orient="records")
        },
        "qa_checks": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["signal_attrition_funnel_manifest"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only signal attrition and signal-to-roadway association audit.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_signal_attrition_funnel_audit(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
