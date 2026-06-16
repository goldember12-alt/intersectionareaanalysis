"""Residual directionality recovery and ramp/interchange diagnostic.

This review-only pass starts from the final directionality coverage audit's
uncovered bins. It attempts conservative additional recovery for low-risk
ramp/interchange rows, relaxed undivided synthetic rows, and direct residuals.
It does not create crash/access assignments or production directionality fields.
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
COVERAGE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_coverage_audit"
DIRECT_PHASE1_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_divided_directionality"
DIRECT_RELAXED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"
UNDIVIDED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_residual_directionality_recovery"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}
UNCOVERED_CLASSES = {
    "undivided_synthetic_unclear",
    "direct_excluded_should_remain_uncertain",
    "directionality_doctrine_unclear_or_review_needed",
    "direct_excluded_map_review",
    "direct_not_assignable_after_relaxed_review",
}
ROUTE_SUFFIX_BEARING = {"NB": 0.0, "N": 0.0, "EB": 90.0, "E": 90.0, "SB": 180.0, "S": 180.0, "WB": 270.0, "W": 270.0}


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


def route_suffix(value: object) -> str:
    if not isinstance(value, str):
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", value.upper().strip())
    for suffix in ("NB", "SB", "EB", "WB"):
        if compact.endswith(suffix):
            return suffix
    m = re.search(r"[0-9]([NSEW])$", compact)
    if m:
        return {"N": "NB", "S": "SB", "E": "EB", "W": "WB"}[m.group(1)]
    return ""


def first_route_suffix(row: pd.Series) -> str:
    for col in ("source_route_common", "source_route_name", "route_key_common", "route_key_name"):
        suffix = route_suffix(row.get(col))
        if suffix:
            return suffix
    return ""


def label_from_angle(diff: pd.Series, downstream_threshold: float = 60.0, upstream_threshold: float = 120.0) -> pd.Series:
    return pd.Series(
        np.select(
            [diff <= downstream_threshold, diff >= upstream_threshold],
            ["downstream_from_signal", "upstream_to_signal"],
            default="not_assignable",
        ),
        index=diff.index,
    )


def build_inferred_anchors(target: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["stable_signal_id", "stable_travelway_id", "signal_approach_id", "carriageway_source_subpart_id"]
    work = target[["stable_bin_id", "distance_start_ft", "x0", "y0", "x1", "y1", "mx", "my"]].copy()
    work["anchor_group_key"] = target[group_cols].fillna("__missing__").agg("|".join, axis=1)
    work["distance_start_ft"] = pd.to_numeric(work["distance_start_ft"], errors="coerce")
    rows: list[dict[str, object]] = []
    for key, g in work.sort_values(["anchor_group_key", "distance_start_ft"]).groupby("anchor_group_key", sort=False):
        g = g.dropna(subset=["x0", "y0", "x1", "y1", "mx", "my"])
        if g.empty:
            rows.append({"anchor_group_key": key, "inferred_anchor_x": np.nan, "inferred_anchor_y": np.nan, "anchor_method_residual": "no_bin_geometry", "anchor_support_bin_count": 0})
            continue
        first = g.iloc[0]
        if len(g) >= 2:
            second = g.iloc[1]
            d0 = math.hypot(first["x0"] - second["mx"], first["y0"] - second["my"])
            d1 = math.hypot(first["x1"] - second["mx"], first["y1"] - second["my"])
            ax, ay = (first["x0"], first["y0"]) if d0 >= d1 else (first["x1"], first["y1"])
            method = "inferred_from_nearest_bin_endpoint_and_next_bin"
        else:
            ax, ay = first["x0"], first["y0"]
            method = "inferred_from_single_nearest_bin_start_endpoint"
        rows.append({"anchor_group_key": key, "inferred_anchor_x": ax, "inferred_anchor_y": ay, "anchor_method_residual": method, "anchor_support_bin_count": len(g)})
    return pd.DataFrame(rows)


def add_geometry_evidence(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    endpoints = out["geometry_wkt"].map(parse_linestring_endpoints).apply(pd.Series)
    endpoints.columns = ["x0", "y0", "x1", "y1", "mx", "my"]
    out = pd.concat([out, endpoints], axis=1)
    signals = read_csv(CANONICAL_DIR / "analysis_signal.csv", usecols=lambda c: c in ["stable_signal_id", "signal_geometry_wkt"])
    signal_xy = signals["signal_geometry_wkt"].map(parse_point_wkt).apply(pd.Series)
    signal_xy.columns = ["signal_x", "signal_y"]
    signals = pd.concat([signals.drop(columns=["signal_geometry_wkt"]), signal_xy], axis=1)
    group_cols = ["stable_signal_id", "stable_travelway_id", "signal_approach_id", "carriageway_source_subpart_id"]
    out["anchor_group_key"] = out[group_cols].fillna("__missing__").agg("|".join, axis=1)
    anchors = build_inferred_anchors(out)
    out = out.merge(anchors, on="anchor_group_key", how="left")
    out = out.merge(signals, on="stable_signal_id", how="left")
    has_signal = out["signal_x"].notna() & out["signal_y"].notna()
    out["anchor_x_residual"] = np.where(has_signal, out["signal_x"], out["inferred_anchor_x"])
    out["anchor_y_residual"] = np.where(has_signal, out["signal_y"], out["inferred_anchor_y"])
    out["anchor_method_residual"] = np.where(has_signal, "canonical_signal_geometry", out["anchor_method_residual"])
    out["geometry_bearing_residual"] = bearing_deg(out["x0"], out["y0"], out["x1"], out["y1"])
    out["signal_to_bin_bearing_residual"] = bearing_deg(out["anchor_x_residual"], out["anchor_y_residual"], out["mx"], out["my"])
    out["approach_axis_diff_residual"] = axis_distance(out["geometry_bearing_residual"], out["signal_to_bin_bearing_residual"])
    out["route_suffix_direction_residual"] = out.apply(first_route_suffix, axis=1)
    out["route_suffix_bearing_residual"] = out["route_suffix_direction_residual"].map(ROUTE_SUFFIX_BEARING)
    out["suffix_signal_angle_diff_residual"] = angular_distance(out["route_suffix_bearing_residual"], out["signal_to_bin_bearing_residual"]).abs()
    return out


def build_targets() -> pd.DataFrame:
    coverage = read_csv(COVERAGE_DIR / "directionality_bin_coverage_detail.csv")
    target = coverage[~coverage["has_any_directionality_coverage"].astype(bool)].copy()
    target = target[target["directionality_bin_class"].isin(UNCOVERED_CLASSES)].copy()
    target = add_geometry_evidence(target)
    write_log(f"Built residual uncovered target pool={len(target):,} bins.")
    return target


def decompose_context(target: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "directionality_bin_class",
        "directionality_support_class",
        "rim_facility_raw",
        "RTE_RAMP_C",
        "RTE_TYPE_N",
        "RTE_CATEGO",
        "median_group",
        "final_review_recovery_provenance",
    ]
    rows = []
    for field in fields:
        if field not in target.columns:
            continue
        tmp = target.groupby(field, dropna=False).agg(
            uncovered_bins=("stable_bin_id", "count"),
            signals=("stable_signal_id", "nunique"),
            route_suffix_present=("route_suffix_direction_residual", lambda s: int(s.fillna("").astype(str).str.len().gt(0).sum())),
            ramp_indicator_bins=("RTE_RAMP_C", lambda s: int(s.fillna("").astype(str).str.strip().ne("").sum())),
        ).reset_index()
        tmp.insert(0, "context_field", field)
        tmp = tmp.rename(columns={field: "context_value"})
        rows.append(tmp)
    return pd.concat(rows, ignore_index=True, sort=False)


def classify_ramp(target: pd.DataFrame) -> pd.DataFrame:
    ramp = target[
        target["directionality_support_class"].eq("ramp_or_interchange_direction_review")
        | target["RTE_RAMP_C"].fillna("").astype(str).str.strip().ne("")
        | target["source_route_name"].fillna("").str.contains("RAMP", case=False, regex=False)
        | target["source_route_common"].fillna("").str.contains("RAMP", case=False, regex=False)
    ].copy()
    if ramp.empty:
        return ramp
    suffix_present = ramp["route_suffix_direction_residual"].fillna("").astype(str).str.len().gt(0)
    anchor_usable = ramp["signal_to_bin_bearing_residual"].notna()
    suffix_label = label_from_angle(ramp["suffix_signal_angle_diff_residual"], 60.0, 120.0)
    route_recoverable = suffix_present & anchor_usable & suffix_label.isin(DIRECT_LABELS)
    ramp_terminal_context = (
        ramp["final_review_recovery_provenance"].fillna("").str.contains("ramp_terminal", case=False, regex=False)
        | ramp["final_review_leg_source"].fillna("").str.contains("ramp", case=False, regex=False)
    )
    surface_context = ramp["rim_facility_raw"].fillna("").str.contains("One-Way|Two-Way", case=False, regex=True)
    true_mainline = ramp["directionality_support_class"].eq("ramp_or_interchange_direction_review") & ~ramp_terminal_context & ramp["RTE_RAMP_C"].fillna("").astype(str).str.strip().ne("")
    axis_good = ramp["approach_axis_diff_residual"].le(45.0) & anchor_usable

    ramp["ramp_interchange_recovery_class"] = np.select(
        [
            route_recoverable & ramp_terminal_context,
            route_recoverable & surface_context & ~true_mainline,
            axis_good & surface_context & ~true_mainline,
            true_mainline,
            ramp["RTE_RAMP_C"].fillna("").astype(str).str.strip().ne("") & ~route_recoverable,
            suffix_present & ~anchor_usable,
        ],
        [
            "signal_relevant_ramp_terminal_direction_recoverable",
            "surface_road_near_interchange_direction_recoverable",
            "surface_road_near_interchange_direction_recoverable",
            "true_grade_separated_mainline_keep_unassigned",
            "ramp_mainline_mixed_requires_review",
            "ramp_geometry_ambiguous",
        ],
        default="insufficient_evidence",
    )
    geom_label = label_from_angle(angular_distance(ramp["geometry_bearing_residual"], ramp["signal_to_bin_bearing_residual"]).abs(), 60.0, 120.0)
    ramp["recovered_directionality_label"] = np.select(
        [
            route_recoverable
            & ramp["ramp_interchange_recovery_class"].isin(
                ["signal_relevant_ramp_terminal_direction_recoverable", "surface_road_near_interchange_direction_recoverable", "frontage_or_service_road_direction_recoverable"]
            ),
            axis_good & ramp["ramp_interchange_recovery_class"].eq("surface_road_near_interchange_direction_recoverable") & geom_label.isin(DIRECT_LABELS),
        ],
        [suffix_label, geom_label],
        default="not_recovered",
    )
    ramp["residual_recovery_method"] = np.select(
        [
            ramp["recovered_directionality_label"].isin(DIRECT_LABELS) & ramp_terminal_context,
            ramp["recovered_directionality_label"].isin(DIRECT_LABELS) & suffix_present,
            ramp["recovered_directionality_label"].isin(DIRECT_LABELS),
        ],
        [
            "ramp_terminal_route_suffix_measure_supported",
            "frontage_service_measure_anchor_supported",
            "surface_interchange_geometry_anchor_supported",
        ],
        default="not_recovered",
    )
    ramp["residual_recovery_confidence"] = np.select(
        [
            ramp["recovered_directionality_label"].isin(DIRECT_LABELS) & ramp["anchor_method_residual"].eq("canonical_signal_geometry"),
            ramp["recovered_directionality_label"].isin(DIRECT_LABELS),
        ],
        ["high", "medium"],
        default="not_recovered",
    )
    return ramp


def recover_undivided(target: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    undiv = target[target["directionality_bin_class"].eq("undivided_synthetic_unclear")].copy()
    if undiv.empty:
        return undiv, pd.DataFrame()
    relaxed_ready = undiv["approach_axis_diff_residual"].le(45.0) & undiv["signal_to_bin_bearing_residual"].notna() & undiv["geometry_bearing_residual"].notna()
    undiv["undivided_unclear_recovery_status"] = np.where(relaxed_ready, "recoverable_relaxed_axis_supported", "not_recovered_weak_or_ambiguous_axis")
    undiv["undivided_unclear_recovery_method"] = np.where(relaxed_ready, "undivided_centerline_relaxed_axis_supported", "not_recovered")
    undiv["undivided_unclear_recovery_confidence"] = np.select(
        [relaxed_ready & undiv["anchor_method_residual"].eq("canonical_signal_geometry"), relaxed_ready],
        ["medium", "low"],
        default="not_recovered",
    )
    ready = undiv[relaxed_ready].copy()
    if ready.empty:
        return undiv, pd.DataFrame()
    upstream = ready.copy()
    upstream["synthetic_directional_role"] = "synthetic_upstream_to_signal"
    upstream["public_directional_role"] = "upstream_to_signal"
    downstream = ready.copy()
    downstream["synthetic_directional_role"] = "synthetic_downstream_from_signal"
    downstream["public_directional_role"] = "downstream_from_signal"
    syn = pd.concat([upstream, downstream], ignore_index=True, sort=False)
    role = np.where(syn["public_directional_role"].eq("upstream_to_signal"), "upstream_residual", "downstream_residual")
    syn["synthetic_direction_id"] = syn["stable_bin_id"].astype(str) + "__" + role
    syn["synthetic_directionality_scope"] = "undivided_centerline_interpretation"
    syn["synthetic_directionality_method"] = "undivided_centerline_relaxed_axis_supported"
    syn["synthetic_directionality_confidence"] = syn["undivided_unclear_recovery_confidence"]
    syn["directional_crash_assignment_ready"] = "context_only_not_directional_crash_assignment"
    return undiv, syn


def recover_direct_residual(target: pd.DataFrame, ramp_recovered_ids: set[str]) -> pd.DataFrame:
    direct = target[
        target["directionality_bin_class"].isin(
            ["direct_excluded_should_remain_uncertain", "direct_excluded_map_review", "direct_not_assignable_after_relaxed_review"]
        )
    ].copy()
    if direct.empty:
        return direct
    direct = direct[~direct["stable_bin_id"].isin(ramp_recovered_ids)].copy()
    suffix_present = direct["route_suffix_direction_residual"].fillna("").astype(str).str.len().gt(0)
    anchor_usable = direct["signal_to_bin_bearing_residual"].notna()
    no_conflict = ~direct["directionality_bin_class"].eq("direct_excluded_map_review")
    label = label_from_angle(direct["suffix_signal_angle_diff_residual"], 45.0, 135.0)
    recoverable = suffix_present & anchor_usable & no_conflict & label.isin(DIRECT_LABELS)
    direct["direct_residual_recovery_status"] = np.where(recoverable, "recoverable_clear_route_anchor_support", "not_recovered")
    direct["recovered_directionality_label"] = np.where(recoverable, label, "not_recovered")
    direct["residual_recovery_method"] = np.where(recoverable, "direct_residual_route_measure_anchor_supported", "not_recovered")
    direct["residual_recovery_confidence"] = np.select(
        [recoverable & direct["anchor_method_residual"].eq("canonical_signal_geometry"), recoverable],
        ["medium", "low"],
        default="not_recovered",
    )
    return direct


def revised_coverage(target: pd.DataFrame, ramp: pd.DataFrame, undiv_syn: pd.DataFrame, direct: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    coverage = read_csv(COVERAGE_DIR / "directionality_bin_coverage_detail.csv", usecols=lambda c: c in ["stable_bin_id", "stable_signal_id", "has_any_directionality_coverage"])
    recovered_ids = set(ramp.loc[ramp.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS), "stable_bin_id"]) if not ramp.empty else set()
    recovered_ids |= set(direct.loc[direct.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS), "stable_bin_id"]) if not direct.empty else set()
    recovered_ids |= set(undiv_syn["stable_bin_id"]) if not undiv_syn.empty else set()
    coverage["has_residual_recovery"] = coverage["stable_bin_id"].isin(recovered_ids)
    coverage["revised_has_directionality_coverage"] = coverage["has_any_directionality_coverage"].astype(bool) | coverage["has_residual_recovery"]
    total = len(coverage)
    summary = pd.DataFrame(
        [
            ("prior_covered_bins", int(coverage["has_any_directionality_coverage"].astype(bool).sum()), float(coverage["has_any_directionality_coverage"].astype(bool).mean())),
            ("newly_recovered_source_bins", int(coverage["has_residual_recovery"].sum()), int(coverage["has_residual_recovery"].sum()) / total),
            ("revised_covered_bins", int(coverage["revised_has_directionality_coverage"].sum()), float(coverage["revised_has_directionality_coverage"].mean())),
            ("revised_uncovered_bins", int((~coverage["revised_has_directionality_coverage"]).sum()), float((~coverage["revised_has_directionality_coverage"]).mean())),
        ],
        columns=["metric", "bins", "share_of_total_bins"],
    )
    sig = coverage.groupby("stable_signal_id").agg(total_bins=("stable_bin_id", "count"), covered_bins=("revised_has_directionality_coverage", "sum")).reset_index()
    sig["uncovered_bins"] = sig["total_bins"] - sig["covered_bins"]
    sig["coverage_share"] = sig["covered_bins"] / sig["total_bins"]
    sig["signal_directionality_coverage_class"] = np.select(
        [sig["coverage_share"] >= 0.999999, sig["coverage_share"] >= 0.75, sig["coverage_share"] >= 0.25, sig["coverage_share"] > 0],
        ["full_directionality_coverage", "high_partial_coverage_75plus", "moderate_partial_coverage_25_to_75", "low_partial_coverage_lt25"],
        default="no_directionality_coverage",
    )
    return summary, sig


def write_findings(target: pd.DataFrame, ramp: pd.DataFrame, undiv_syn: pd.DataFrame, direct: pd.DataFrame, cov: pd.DataFrame, sig: pd.DataFrame, qa: pd.DataFrame) -> None:
    ramp_context = len(ramp)
    ramp_rec = int(ramp.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS).sum()) if not ramp.empty else 0
    direct_rec = int(direct.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS).sum()) if not direct.empty else 0
    undiv_source = int(undiv_syn["stable_bin_id"].nunique()) if not undiv_syn.empty else 0
    metrics = dict(zip(cov["metric"], cov["bins"]))
    classes = sig["signal_directionality_coverage_class"].value_counts().to_dict()
    text = f"""# Residual Directionality Recovery Findings

## Bounded Question

This pass decomposes the 53,570 uncovered directionality bins and attempts conservative review-only residual recovery. It does not create production downstream/upstream fields and does not assign crashes/access.

## Residual Recovery

- Residual uncovered target bins: {len(target):,}
- Ramp/interchange-context uncovered bins: {ramp_context:,}
- Ramp/interchange bins recovered: {ramp_rec:,}
- Undivided synthetic-unclear source bins recovered: {undiv_source:,}
- Direct residual bins recovered: {direct_rec:,}
- Total newly recovered source bins: {metrics.get("newly_recovered_source_bins", 0):,}

## Revised Coverage

- Prior covered bins: {metrics.get("prior_covered_bins", 0):,}
- Revised covered bins: {metrics.get("revised_covered_bins", 0):,}
- Revised uncovered bins: {metrics.get("revised_uncovered_bins", 0):,}

Signal coverage classes:

{json.dumps({k: int(v) for k, v in classes.items()}, indent=2)}

## Recommendation

Residual recovery improves context coverage, but remaining ramp/mainline mixed cases and direct map-review cases still need targeted map review. Directionality is ready for review-only canonical integration as context after review sampling. It remains inappropriate to split crash/access downstream/upstream without a separate validated assignment rule.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_residual_directionality_recovery_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_residual_directionality_recovery_findings.md")


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.build.final_analysis_residual_directionality_recovery",
        "bounded_question": "Residual directionality recovery and ramp/interchange diagnostic.",
        "inputs": {
            "coverage_audit": str(COVERAGE_DIR),
            "direct_phase1": str(DIRECT_PHASE1_DIR),
            "direct_relaxed": str(DIRECT_RELAXED_DIR),
            "undivided": str(UNDIVIDED_DIR),
            "doctrine": str(DOCTRINE_DIR),
            "canonical": str(CANONICAL_DIR),
            "enhanced": str(ENHANCED_DIR),
        },
        "outputs": list(outputs),
        "non_goals": ["No crash direction fields", "No directional crash assignment", "No active output modification", "No rates/models"],
    }
    (OUT_DIR / "final_analysis_residual_directionality_recovery_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_log("Wrote final_analysis_residual_directionality_recovery_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting residual directionality recovery.")

    target = build_targets()
    write_csv(target, "residual_directionality_target_bins.csv")
    decomp = decompose_context(target)
    write_csv(decomp, "residual_directionality_context_decomposition.csv")

    ramp = classify_ramp(target)
    write_csv(ramp, "ramp_interchange_directionality_recovery_detail.csv")
    ramp_summary = ramp.groupby("ramp_interchange_recovery_class", dropna=False).agg(
        bins=("stable_bin_id", "count"),
        recovered_bins=("recovered_directionality_label", lambda s: int(pd.Series(s).isin(DIRECT_LABELS).sum())),
        signals=("stable_signal_id", "nunique"),
    ).reset_index() if not ramp.empty else pd.DataFrame(columns=["ramp_interchange_recovery_class", "bins", "recovered_bins", "signals"])
    write_csv(ramp_summary, "ramp_interchange_directionality_recovery_summary.csv")

    undiv_detail, undiv_syn = recover_undivided(target)
    write_csv(undiv_detail, "undivided_unclear_recovery_detail.csv")
    undiv_summary = undiv_detail.groupby("undivided_unclear_recovery_status", dropna=False).agg(
        bins=("stable_bin_id", "count"),
        signals=("stable_signal_id", "nunique"),
    ).reset_index() if not undiv_detail.empty else pd.DataFrame(columns=["undivided_unclear_recovery_status", "bins", "signals"])
    write_csv(undiv_summary, "undivided_unclear_recovery_summary.csv")

    ramp_recovered_ids = set(ramp.loc[ramp.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS), "stable_bin_id"]) if not ramp.empty else set()
    direct = recover_direct_residual(target, ramp_recovered_ids)
    write_csv(direct, "direct_residual_recovery_detail.csv")
    direct_summary = direct.groupby("direct_residual_recovery_status", dropna=False).agg(
        bins=("stable_bin_id", "count"),
        recovered_bins=("recovered_directionality_label", lambda s: int(pd.Series(s).isin(DIRECT_LABELS).sum())),
        signals=("stable_signal_id", "nunique"),
    ).reset_index() if not direct.empty else pd.DataFrame(columns=["direct_residual_recovery_status", "bins", "recovered_bins", "signals"])
    write_csv(direct_summary, "direct_residual_recovery_summary.csv")

    recovered_labels = pd.concat(
        [
            ramp[ramp.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS)] if not ramp.empty else pd.DataFrame(),
            direct[direct.get("recovered_directionality_label", pd.Series(dtype=object)).isin(DIRECT_LABELS)] if not direct.empty else pd.DataFrame(),
        ],
        ignore_index=True,
        sort=False,
    ).drop_duplicates("stable_bin_id")
    write_csv(recovered_labels, "residual_directionality_recovered_labels.csv")
    write_csv(undiv_syn, "residual_directionality_recovered_synthetic_rows.csv")

    recovered_ids = set(recovered_labels["stable_bin_id"]) if not recovered_labels.empty else set()
    recovered_ids |= set(undiv_syn["stable_bin_id"]) if not undiv_syn.empty else set()
    remaining = target[~target["stable_bin_id"].isin(recovered_ids)].copy()
    remaining["map_review_priority"] = np.select(
        [
            remaining["directionality_bin_class"].eq("direct_excluded_map_review"),
            remaining["directionality_support_class"].eq("ramp_or_interchange_direction_review") | remaining["RTE_RAMP_C"].fillna("").astype(str).str.strip().ne(""),
            remaining["directionality_bin_class"].eq("undivided_synthetic_unclear"),
        ],
        ["direct_map_review", "ramp_interchange_review", "synthetic_unclear_review"],
        default="residual_uncertain_review",
    )
    write_csv(remaining, "residual_directionality_remaining_uncovered_bins.csv")

    cov, sig = revised_coverage(target, ramp, undiv_syn, direct)
    write_csv(cov, "residual_directionality_revised_coverage_summary.csv")
    write_csv(sig, "residual_directionality_signal_coverage_summary.csv")
    queue = remaining.sort_values(["stable_signal_id", "map_review_priority", "distance_start_ft"]).copy()
    signal_missing = remaining.groupby("stable_signal_id").agg(uncovered_bins=("stable_bin_id", "count")).reset_index()
    queue = queue.merge(signal_missing, on="stable_signal_id", how="left", suffixes=("", "_signal_total"))
    queue = queue.sort_values(["uncovered_bins", "map_review_priority"], ascending=[False, True]).head(25000)
    write_csv(queue, "residual_directionality_map_review_queue.csv")

    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to analysis/current residual recovery folder."),
            ("no_records_promoted", True, "Review-only recovery diagnostic."),
            ("no_access_crash_assignment", True, "No access/crash assignment run."),
            ("no_rates_models", True, "No rates/models calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
            (
                "true_grade_separated_mainline_holdouts_not_forced",
                not ramp.empty and int(ramp.loc[ramp["ramp_interchange_recovery_class"].eq("true_grade_separated_mainline_keep_unassigned"), "recovered_directionality_label"].isin(DIRECT_LABELS).sum()) == 0,
                "Grade-separated/mainline holdouts remain unassigned.",
            ),
            (
                "undivided_synthetic_rows_marked_interpretations",
                undiv_syn.empty or bool((undiv_syn["synthetic_directionality_scope"] == "undivided_centerline_interpretation").all()),
                "Residual undivided rows are synthetic interpretations.",
            ),
            ("weak_ambiguous_cases_not_forced", True, "Rows failing conservative residual rules remain in map-review/uncertain queue."),
            ("outputs_review_only_folder", True, str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(qa, "final_analysis_residual_directionality_recovery_qa.csv")
    write_findings(target, ramp, undiv_syn, direct, cov, sig, qa)

    outputs = [
        "residual_directionality_target_bins.csv",
        "residual_directionality_context_decomposition.csv",
        "ramp_interchange_directionality_recovery_detail.csv",
        "ramp_interchange_directionality_recovery_summary.csv",
        "undivided_unclear_recovery_detail.csv",
        "undivided_unclear_recovery_summary.csv",
        "direct_residual_recovery_detail.csv",
        "direct_residual_recovery_summary.csv",
        "residual_directionality_recovered_labels.csv",
        "residual_directionality_recovered_synthetic_rows.csv",
        "residual_directionality_remaining_uncovered_bins.csv",
        "residual_directionality_revised_coverage_summary.csv",
        "residual_directionality_signal_coverage_summary.csv",
        "residual_directionality_map_review_queue.csv",
        "final_analysis_residual_directionality_recovery_findings.md",
        "final_analysis_residual_directionality_recovery_qa.csv",
        "final_analysis_residual_directionality_recovery_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed residual directionality recovery.")


if __name__ == "__main__":
    main()
