"""Phase 2 undivided centerline synthetic directionality.

This review-only pass creates paired upstream/downstream interpretation rows for
undivided centerline bins where signal-centered approach geometry is sufficient.
It does not assign a single direct label to undivided source rows and does not
create directional crash assignments.
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
DIRECT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality"

UNDIVIDED_CLASS = "undivided_centerline_requires_synthetic_direction"
DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}


def write_log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR / name, index=False, quoting=csv.QUOTE_MINIMAL)
    write_log(f"Wrote {name}: {len(df):,} rows")


def parse_point_wkt(value: object) -> tuple[float, float]:
    if not isinstance(value, str) or "POINT" not in value.upper():
        return (np.nan, np.nan)
    nums = re.findall(r"-?\d+(?:\.\d+)?", value)
    if len(nums) < 2:
        return (np.nan, np.nan)
    return (float(nums[0]), float(nums[1]))


def parse_linestring_endpoints(value: object) -> tuple[float, float, float, float, float, float]:
    if not isinstance(value, str) or "LINESTRING" not in value.upper():
        return (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", value)]
    if len(nums) < 4:
        return (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    dim = 3 if "LINESTRING Z" in value.upper() or len(nums) % 3 == 0 else 2
    coords = list(zip(nums[0::dim], nums[1::dim]))
    if len(coords) < 2:
        return (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    x0, y0 = coords[0]
    x1, y1 = coords[-1]
    mx = sum(x for x, _ in coords) / len(coords)
    my = sum(y for _, y in coords) / len(coords)
    return (x0, y0, x1, y1, mx, my)


def bearing_deg(x0: pd.Series, y0: pd.Series, x1: pd.Series, y1: pd.Series) -> pd.Series:
    dx = x1 - x0
    dy = y1 - y0
    b = (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0
    b[(dx.abs() < 1e-9) & (dy.abs() < 1e-9)] = np.nan
    return b


def angular_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a - b).abs() + 180.0) % 360.0 - 180.0


def axis_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    diff = angular_distance(a, b).abs()
    return np.minimum(diff, 180.0 - diff)


def build_inferred_anchors(target: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["stable_signal_id", "stable_travelway_id", "signal_approach_id", "carriageway_source_subpart_id"]
    work = target[["stable_bin_id", "distance_start_ft", "x0", "y0", "x1", "y1", "mx", "my"]].copy()
    work["anchor_group_key"] = target[group_cols].fillna("__missing__").agg("|".join, axis=1)
    work["distance_start_ft"] = pd.to_numeric(work["distance_start_ft"], errors="coerce")
    rows: list[dict[str, object]] = []
    for key, g in work.sort_values(["anchor_group_key", "distance_start_ft"]).groupby("anchor_group_key", sort=False):
        g = g.dropna(subset=["x0", "y0", "x1", "y1", "mx", "my"])
        if g.empty:
            rows.append(
                {
                    "anchor_group_key": key,
                    "inferred_anchor_x": np.nan,
                    "inferred_anchor_y": np.nan,
                    "signal_anchor_method": "no_bin_geometry",
                    "anchor_support_bin_count": 0,
                }
            )
            continue
        first = g.iloc[0]
        if len(g) >= 2:
            second = g.iloc[1]
            d0 = math.hypot(first["x0"] - second["mx"], first["y0"] - second["my"])
            d1 = math.hypot(first["x1"] - second["mx"], first["y1"] - second["my"])
            if d0 >= d1:
                ax, ay = first["x0"], first["y0"]
            else:
                ax, ay = first["x1"], first["y1"]
            method = "inferred_from_nearest_bin_endpoint_and_next_bin"
        else:
            ax, ay = first["x0"], first["y0"]
            method = "inferred_from_single_nearest_bin_start_endpoint"
        rows.append(
            {
                "anchor_group_key": key,
                "inferred_anchor_x": ax,
                "inferred_anchor_y": ay,
                "signal_anchor_method": method,
                "anchor_support_bin_count": len(g),
            }
        )
    return pd.DataFrame(rows)


def classify_geometry(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    out["bin_bearing"] = bearing_deg(out["x0"], out["y0"], out["x1"], out["y1"])
    out["approach_bearing_from_signal"] = bearing_deg(out["anchor_x"], out["anchor_y"], out["mx"], out["my"])
    out["approach_axis_diff_deg"] = axis_distance(out["bin_bearing"], out["approach_bearing_from_signal"])
    out["approach_axis_consistency"] = np.select(
        [
            out["approach_axis_diff_deg"].isna(),
            out["approach_axis_diff_deg"] <= 30.0,
            out["approach_axis_diff_deg"] <= 60.0,
        ],
        ["not_testable", "strong_axis_match", "moderate_axis_match"],
        default="weak_axis_match",
    )
    has_geom = out[["x0", "y0", "x1", "y1", "mx", "my"]].notna().all(axis=1)
    has_anchor = out["anchor_x"].notna() & out["anchor_y"].notna()
    canonical_anchor = out["signal_anchor_method"].eq("canonical_signal_geometry")
    inferred_multi = out["signal_anchor_method"].eq("inferred_from_nearest_bin_endpoint_and_next_bin")

    out["approach_geometry_confidence"] = np.select(
        [
            has_geom & has_anchor & canonical_anchor & (out["approach_axis_diff_deg"] <= 30.0),
            has_geom & has_anchor & ((canonical_anchor & (out["approach_axis_diff_deg"] <= 60.0)) | (inferred_multi & (out["approach_axis_diff_deg"] <= 30.0))),
            has_geom & has_anchor & (out["approach_axis_diff_deg"] <= 60.0),
        ],
        ["high", "medium", "low"],
        default="insufficient",
    )
    out["synthetic_source_bin_status"] = np.select(
        [
            out["approach_geometry_confidence"].isin(["high", "medium"]),
            ~has_geom,
            ~has_anchor,
            out["approach_axis_diff_deg"].isna(),
            out["approach_axis_diff_deg"] > 60.0,
            out["approach_geometry_confidence"].eq("low"),
        ],
        [
            "synthetic_directionality_ready",
            "insufficient_approach_geometry",
            "insufficient_approach_geometry",
            "synthetic_direction_uncertain",
            "bidirectional_or_undirected",
            "synthetic_direction_uncertain",
        ],
        default="manual_review_needed",
    )
    return out


def make_synthetic_rows(ready: pd.DataFrame) -> pd.DataFrame:
    if ready.empty:
        return pd.DataFrame()
    common = ready.copy()
    upstream = common.copy()
    upstream["synthetic_directional_role"] = "synthetic_upstream_to_signal"
    upstream["public_directional_role"] = "upstream_to_signal"
    downstream = common.copy()
    downstream["synthetic_directional_role"] = "synthetic_downstream_from_signal"
    downstream["public_directional_role"] = "downstream_from_signal"
    syn = pd.concat([upstream, downstream], ignore_index=True, sort=False)
    role_code = np.where(syn["public_directional_role"].eq("upstream_to_signal"), "upstream", "downstream")
    syn["synthetic_direction_id"] = syn["stable_bin_id"].astype(str) + "__" + role_code
    syn["synthetic_directionality_method"] = "paired_undivided_centerline_signal_axis_interpretation"
    syn["synthetic_directionality_confidence"] = syn["approach_geometry_confidence"]
    syn["synthetic_directionality_scope"] = "undivided_centerline_interpretation"
    syn["directional_crash_assignment_ready"] = "context_only_not_directional_crash_assignment"
    syn["synthetic_directionality_reason"] = (
        "Undivided centerline represents both travel directions; paired interpretation rows are derived from signal-centered centerline axis."
    )
    return syn


def summarize_signal(target: pd.DataFrame, synthetic: pd.DataFrame) -> pd.DataFrame:
    base = target.groupby("stable_signal_id", dropna=False).agg(
        undivided_target_bins=("stable_bin_id", "count"),
        synthetic_ready_source_bins=("synthetic_source_bin_status", lambda s: int((s == "synthetic_directionality_ready").sum())),
        undirected_or_unclear_bins=("synthetic_source_bin_status", lambda s: int((s != "synthetic_directionality_ready").sum())),
    ).reset_index()
    syn = synthetic.groupby("stable_signal_id", dropna=False).agg(
        synthetic_interpretation_rows=("synthetic_direction_id", "count"),
        synthetic_upstream_rows=("public_directional_role", lambda s: int((s == "upstream_to_signal").sum())),
        synthetic_downstream_rows=("public_directional_role", lambda s: int((s == "downstream_from_signal").sum())),
    ).reset_index()
    out = base.merge(syn, on="stable_signal_id", how="left")
    for col in ["synthetic_interpretation_rows", "synthetic_upstream_rows", "synthetic_downstream_rows"]:
        out[col] = out[col].fillna(0).astype(int)
    out["has_synthetic_directional_coverage"] = out["synthetic_interpretation_rows"] > 0
    return out


def summarize_approach(target: pd.DataFrame, synthetic: pd.DataFrame) -> pd.DataFrame:
    keys = ["stable_signal_id", "signal_approach_id"]
    base = target.groupby(keys, dropna=False).agg(
        undivided_target_bins=("stable_bin_id", "count"),
        synthetic_ready_source_bins=("synthetic_source_bin_status", lambda s: int((s == "synthetic_directionality_ready").sum())),
        undirected_or_unclear_bins=("synthetic_source_bin_status", lambda s: int((s != "synthetic_directionality_ready").sum())),
    ).reset_index()
    syn = synthetic.groupby(keys, dropna=False).agg(
        synthetic_interpretation_rows=("synthetic_direction_id", "count"),
        synthetic_upstream_rows=("public_directional_role", lambda s: int((s == "upstream_to_signal").sum())),
        synthetic_downstream_rows=("public_directional_role", lambda s: int((s == "downstream_from_signal").sum())),
    ).reset_index()
    out = base.merge(syn, on=keys, how="left")
    for col in ["synthetic_interpretation_rows", "synthetic_upstream_rows", "synthetic_downstream_rows"]:
        out[col] = out[col].fillna(0).astype(int)
    out["has_synthetic_upstream_downstream_pair"] = (out["synthetic_upstream_rows"] > 0) & (out["synthetic_downstream_rows"] > 0)
    return out


def summarize_window(target: pd.DataFrame, synthetic: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for keys, level in [
        (["stable_signal_id", "analysis_window"], "signal_window"),
        (["stable_signal_id", "signal_approach_id", "analysis_window"], "signal_approach_window"),
    ]:
        base = target.groupby(keys, dropna=False).agg(
            undivided_target_bins=("stable_bin_id", "count"),
            synthetic_ready_source_bins=("synthetic_source_bin_status", lambda s: int((s == "synthetic_directionality_ready").sum())),
            undirected_or_unclear_bins=("synthetic_source_bin_status", lambda s: int((s != "synthetic_directionality_ready").sum())),
        ).reset_index()
        syn = synthetic.groupby(keys, dropna=False).agg(
            synthetic_interpretation_rows=("synthetic_direction_id", "count")
        ).reset_index()
        out = base.merge(syn, on=keys, how="left")
        out["synthetic_interpretation_rows"] = out["synthetic_interpretation_rows"].fillna(0).astype(int)
        out.insert(0, "summary_level", level)
        frames.append(out)
    return pd.concat(frames, ignore_index=True, sort=False)


def combined_summary(direct: pd.DataFrame, target: pd.DataFrame, synthetic: pd.DataFrame) -> pd.DataFrame:
    direct_labeled = direct["combined_direct_directionality_label"].isin(DIRECT_LABELS)
    rows = [
        ("direct_divided_one_way_source_bins", len(direct)),
        ("direct_divided_one_way_labeled_bins", int(direct_labeled.sum())),
        ("direct_downstream_labels", int((direct["combined_direct_directionality_label"] == "downstream_from_signal").sum())),
        ("direct_upstream_labels", int((direct["combined_direct_directionality_label"] == "upstream_to_signal").sum())),
        ("undivided_centerline_source_bins", len(target)),
        ("undivided_synthetic_ready_source_bins", int((target["synthetic_source_bin_status"] == "synthetic_directionality_ready").sum())),
        ("undivided_synthetic_interpretation_rows", len(synthetic)),
        ("undivided_remaining_undirected_or_unclear_bins", int((target["synthetic_source_bin_status"] != "synthetic_directionality_ready").sum())),
        (
            "signals_with_any_direct_or_synthetic_coverage",
            int(len(set(direct.loc[direct_labeled, "stable_signal_id"]).union(set(synthetic["stable_signal_id"])))),
        ),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def build_compatibility() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "directionality_product": "direct_divided_one_way_directionality",
                "directional_crash_assignment_ready": "potential_future_candidate_after_map_review",
                "note": "Direct row labels may support future directional crash/access rules after validation; no assignment is made here.",
            },
            {
                "directionality_product": "undivided_centerline_synthetic_interpretation",
                "directional_crash_assignment_ready": "context_only_not_directional_crash_assignment",
                "note": "Synthetic rows support roadway context summaries but should not split crash counts without a validated crash-direction-independent assignment rule.",
            },
        ]
    )


def build_qa(target: pd.DataFrame, synthetic: pd.DataFrame, direct: pd.DataFrame) -> pd.DataFrame:
    synthetic_ids_conflict = int(synthetic["synthetic_direction_id"].duplicated().sum()) if not synthetic.empty else 0
    non_undivided_synthetic = int((~synthetic["directionality_support_class"].eq(UNDIVIDED_CLASS)).sum()) if not synthetic.empty else 0
    single_direct_labels = int(
        synthetic.get("combined_direct_directionality_label", pd.Series(index=synthetic.index, dtype=object)).isin(DIRECT_LABELS).sum()
    ) if not synthetic.empty else 0
    weak_created = int((synthetic["approach_geometry_confidence"].isin(["low", "insufficient"])).sum()) if not synthetic.empty else 0
    direct_altered = "synthetic_direction_id" in direct.columns
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to analysis/current undivided centerline folder."),
        ("no_records_promoted", True, "Review-only synthetic interpretations."),
        ("no_access_crash_assignment", True, "No access/crash assignment run."),
        ("no_rates_models", True, "No rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("direct_divided_one_way_rows_not_altered", not direct_altered, "Direct rows read only for summary."),
        ("undivided_rows_not_assigned_single_direct_labels", single_direct_labels == 0, f"single direct labels on synthetic rows={single_direct_labels}"),
        ("synthetic_rows_marked_as_interpretations", bool((synthetic["synthetic_directionality_scope"] == "undivided_centerline_interpretation").all()) if not synthetic.empty else True, "Synthetic scope field is explicit."),
        ("no_duplicate_synthetic_direction_id_conflicts", synthetic_ids_conflict == 0, f"duplicate synthetic ids={synthetic_ids_conflict}"),
        ("no_synthetic_rows_for_non_undivided_classes", non_undivided_synthetic == 0, f"non-undivided synthetic rows={non_undivided_synthetic}"),
        ("weak_ambiguous_cases_not_forced", weak_created == 0, f"low/insufficient confidence synthetic rows={weak_created}"),
        ("outputs_review_only_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def write_findings(target: pd.DataFrame, synthetic: pd.DataFrame, signal_summary: pd.DataFrame, approach_summary: pd.DataFrame, combined: pd.DataFrame, qa: pd.DataFrame) -> None:
    ready_bins = int((target["synthetic_source_bin_status"] == "synthetic_directionality_ready").sum())
    unclear = len(target) - ready_bins
    signals = int(signal_summary["has_synthetic_directional_coverage"].sum())
    approaches = int(approach_summary["has_synthetic_upstream_downstream_pair"].sum())
    metrics = dict(zip(combined["metric"], combined["value"]))
    text = f"""# Undivided Centerline Synthetic Directionality Findings

## Bounded Question

This Phase 2 pass creates paired review-only upstream/downstream interpretation rows for undivided centerline bins where signal-centered approach geometry is sufficient. It does not assign a single direct label to undivided rows and does not create directional crash assignments.

## Results

- Undivided centerline target bins: {len(target):,}
- Source bins with synthetic directionality: {ready_bins:,}
- Synthetic interpretation rows created: {len(synthetic):,}
- Bins remaining bidirectional/undirected or unclear: {unclear:,}
- Signals with synthetic directional coverage: {signals:,}
- Approaches with synthetic upstream/downstream pair: {approaches:,}

## Combined Coverage Context

- Direct divided/one-way labels after relaxed recovery: {metrics.get("direct_divided_one_way_labeled_bins", 0):,}
- Undivided synthetic-ready source bins: {metrics.get("undivided_synthetic_ready_source_bins", 0):,}
- Undivided synthetic interpretation rows: {metrics.get("undivided_synthetic_interpretation_rows", 0):,}
- Signals with any direct or synthetic coverage: {metrics.get("signals_with_any_direct_or_synthetic_coverage", 0):,}

## Crash Assignment Compatibility

Synthetic undivided directionality is context-only for now. It should not be used to split crash counts upstream/downstream until a separate crash-direction-independent assignment rule is defined and validated.

## Recommendation

Phase 3 should integrate direct and synthetic directionality into an enhanced canonical review dataset after map-review sampling, while separately defining whether and how directional access/crash aggregation can be done without crash direction fields.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_undivided_centerline_directionality_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_undivided_centerline_directionality_findings.md")


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.build.final_analysis_undivided_centerline_directionality",
        "bounded_question": "Create synthetic upstream/downstream interpretation rows for undivided centerline bins.",
        "inputs": {
            "doctrine": str(DOCTRINE_DIR),
            "direct_relaxed_recovery": str(DIRECT_DIR),
            "canonical": str(CANONICAL_DIR),
            "enhanced": str(ENHANCED_DIR),
        },
        "outputs": list(outputs),
        "non_goals": [
            "No direct divided/one-way relabeling",
            "No directional crash assignment",
            "No crash direction fields",
            "No access/crash assignment",
            "No rates/models",
            "No active output modification",
        ],
    }
    (OUT_DIR / "final_analysis_undivided_centerline_directionality_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_log("Wrote final_analysis_undivided_centerline_directionality_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting undivided centerline synthetic directionality.")

    doctrine_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "distance_start_ft",
        "distance_end_ft",
        "analysis_window",
        "signal_approach_id",
        "carriageway_source_subpart_id",
        "final_review_leg_source",
        "final_review_recovery_provenance",
        "source_measure_midpoint",
        "route_key_common",
        "route_key_name",
        "rim_median_raw",
        "rim_facility_raw",
        "rim_facility_secondary_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "source_bearing_sector",
        "signal_approach_bearing",
        "directionality_support_class",
        "directionality_source_evidence",
        "recommended_directionality_action",
    ]
    bin_cols = ["stable_bin_id", "source_signal_id", "distance_band", "geometry_wkt"]
    signal_cols = ["stable_signal_id", "signal_geometry_wkt"]

    doctrine = read_csv(DOCTRINE_DIR / "bin_directionality_support_detail.csv", usecols=lambda c: c in doctrine_cols)
    bins = read_csv(CANONICAL_DIR / "analysis_bin.csv", usecols=lambda c: c in bin_cols)
    signals = read_csv(CANONICAL_DIR / "analysis_signal.csv", usecols=lambda c: c in signal_cols)
    direct = read_csv(DIRECT_DIR / "combined_direct_divided_directionality_detail.csv")
    write_log(f"Loaded doctrine={len(doctrine):,}; bins={len(bins):,}; direct={len(direct):,}.")

    target = doctrine[doctrine["directionality_support_class"].eq(UNDIVIDED_CLASS)].copy()
    target = target.merge(bins, on="stable_bin_id", how="left", validate="one_to_one")
    endpoints = target["geometry_wkt"].map(parse_linestring_endpoints).apply(pd.Series)
    endpoints.columns = ["x0", "y0", "x1", "y1", "mx", "my"]
    target = pd.concat([target, endpoints], axis=1)

    signal_xy = signals.copy()
    xy = signal_xy["signal_geometry_wkt"].map(parse_point_wkt).apply(pd.Series)
    xy.columns = ["signal_x", "signal_y"]
    signal_xy = pd.concat([signal_xy.drop(columns=["signal_geometry_wkt"]), xy], axis=1)

    group_cols = ["stable_signal_id", "stable_travelway_id", "signal_approach_id", "carriageway_source_subpart_id"]
    target["anchor_group_key"] = target[group_cols].fillna("__missing__").agg("|".join, axis=1)
    inferred = build_inferred_anchors(target)
    target = target.merge(inferred, on="anchor_group_key", how="left")
    target = target.merge(signal_xy, on="stable_signal_id", how="left")
    has_signal = target["signal_x"].notna() & target["signal_y"].notna()
    target["anchor_x"] = np.where(has_signal, target["signal_x"], target["inferred_anchor_x"])
    target["anchor_y"] = np.where(has_signal, target["signal_y"], target["inferred_anchor_y"])
    target["signal_anchor_method"] = np.where(has_signal, "canonical_signal_geometry", target["signal_anchor_method"])

    target = classify_geometry(target)
    write_log(f"Built undivided target pool={len(target):,} bins.")

    ready = target[target["synthetic_source_bin_status"].eq("synthetic_directionality_ready")].copy()
    synthetic = make_synthetic_rows(ready)
    uncertain = target[~target["synthetic_source_bin_status"].eq("synthetic_directionality_ready")].copy()
    uncertain["uncertain_status"] = target.loc[uncertain.index, "synthetic_source_bin_status"]

    target_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "signal_approach_id",
        "carriageway_source_subpart_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "rim_median_raw",
        "rim_facility_raw",
        "rim_facility_secondary_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "final_review_leg_source",
        "final_review_recovery_provenance",
        "directionality_support_class",
        "directionality_source_evidence",
    ]
    geometry_cols = target_cols + [
        "x0",
        "y0",
        "x1",
        "y1",
        "mx",
        "my",
        "anchor_x",
        "anchor_y",
        "signal_anchor_method",
        "anchor_support_bin_count",
        "approach_bearing_from_signal",
        "bin_bearing",
        "approach_axis_diff_deg",
        "approach_axis_consistency",
        "approach_geometry_confidence",
        "synthetic_source_bin_status",
    ]
    synthetic_cols = geometry_cols + [
        "synthetic_direction_id",
        "synthetic_directional_role",
        "public_directional_role",
        "synthetic_directionality_method",
        "synthetic_directionality_confidence",
        "synthetic_directionality_scope",
        "directional_crash_assignment_ready",
        "synthetic_directionality_reason",
    ]
    synthetic_cols = [c for c in synthetic_cols if c in synthetic.columns]

    write_csv(target[target_cols], "undivided_centerline_target_bins.csv")
    write_csv(target[geometry_cols], "undivided_centerline_approach_geometry_detail.csv")
    write_csv(synthetic[synthetic_cols], "undivided_centerline_synthetic_direction_rows.csv")
    write_csv(uncertain[geometry_cols + ["uncertain_status"]], "undivided_centerline_uncertain_bins.csv")

    signal_summary = summarize_signal(target, synthetic)
    approach_summary = summarize_approach(target, synthetic)
    window_summary = summarize_window(target, synthetic)
    combined = combined_summary(direct, target, synthetic)
    compatibility = build_compatibility()
    write_csv(signal_summary, "undivided_centerline_signal_summary.csv")
    write_csv(approach_summary, "undivided_centerline_approach_summary.csv")
    write_csv(window_summary, "undivided_centerline_window_summary.csv")
    write_csv(combined, "combined_direct_and_synthetic_directionality_summary.csv")
    write_csv(compatibility, "directional_crash_assignment_compatibility.csv")

    examples = pd.concat(
        [
            synthetic[synthetic["synthetic_directionality_confidence"].eq("high")].head(20),
            synthetic[synthetic["synthetic_directionality_confidence"].eq("medium")].head(20),
            uncertain[uncertain["synthetic_source_bin_status"].eq("bidirectional_or_undirected")].head(20),
            uncertain[uncertain["synthetic_source_bin_status"].eq("synthetic_direction_uncertain")].head(20),
            uncertain[uncertain["synthetic_source_bin_status"].eq("insufficient_approach_geometry")].head(20),
        ],
        ignore_index=True,
        sort=False,
    ).drop_duplicates("stable_bin_id")
    write_csv(examples, "undivided_centerline_directionality_examples.csv")

    next_action = pd.DataFrame(
        [
            {
                "recommendation": "integrate_direct_and_synthetic_directionality_after_map_review_then_define_directional_crash_access_rules",
                "undivided_target_bins": len(target),
                "synthetic_ready_source_bins": len(ready),
                "synthetic_interpretation_rows": len(synthetic),
                "remaining_unclear_bins": len(uncertain),
                "phase3_recommendation": "enhanced_canonical_directionality_integration_and_context_only_usage",
                "rationale": "Synthetic undivided rows are useful for context summaries but not directional crash assignment without a separate validated rule.",
            }
        ]
    )
    write_csv(next_action, "undivided_centerline_directionality_next_action.csv")

    qa = build_qa(target, synthetic, direct)
    write_csv(qa, "final_analysis_undivided_centerline_directionality_qa.csv")
    write_findings(target, synthetic, signal_summary, approach_summary, combined, qa)

    outputs = [
        "undivided_centerline_target_bins.csv",
        "undivided_centerline_approach_geometry_detail.csv",
        "undivided_centerline_synthetic_direction_rows.csv",
        "undivided_centerline_uncertain_bins.csv",
        "undivided_centerline_signal_summary.csv",
        "undivided_centerline_approach_summary.csv",
        "undivided_centerline_window_summary.csv",
        "combined_direct_and_synthetic_directionality_summary.csv",
        "directional_crash_assignment_compatibility.csv",
        "undivided_centerline_directionality_examples.csv",
        "undivided_centerline_directionality_next_action.csv",
        "final_analysis_undivided_centerline_directionality_findings.md",
        "final_analysis_undivided_centerline_directionality_qa.csv",
        "final_analysis_undivided_centerline_directionality_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed undivided centerline synthetic directionality.")


if __name__ == "__main__":
    main()
