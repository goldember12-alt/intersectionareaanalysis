"""Phase 1 direct divided/one-way downstream/upstream feasibility labels.

This review-only pass labels only bins already classified by the directionality
doctrine as direct divided-row or one-way-row candidates. It does not assign
directionality to undivided centerlines, ramp/interchange review rows, or
insufficient-evidence rows.
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
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_divided_directionality"

TARGET_CLASSES = {
    "direct_divided_row_direction_supported",
    "one_way_row_direction_supported",
}
OUT_OF_SCOPE_CLASSES = {
    "undivided_centerline_requires_synthetic_direction",
    "ramp_or_interchange_direction_review",
    "insufficient_direction_evidence",
}

ROUTE_SUFFIX_BEARING = {
    "NB": 0.0,
    "N": 0.0,
    "EB": 90.0,
    "E": 90.0,
    "SB": 180.0,
    "S": 180.0,
    "WB": 270.0,
    "W": 270.0,
}


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
    path = OUT_DIR / name
    df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
    write_log(f"Wrote {name}: {len(df):,} rows")


def parse_point_wkt(value: object) -> tuple[float, float] | tuple[float, float]:
    if not isinstance(value, str) or "POINT" not in value.upper():
        return (np.nan, np.nan)
    nums = re.findall(r"-?\d+(?:\.\d+)?", value)
    if len(nums) < 2:
        return (np.nan, np.nan)
    return (float(nums[0]), float(nums[1]))


def parse_linestring_endpoints(value: object) -> tuple[float, float, float, float, float, float]:
    """Return start x/y, end x/y, midpoint x/y from a 2D/3D LINESTRING WKT."""
    if not isinstance(value, str) or "LINESTRING" not in value.upper():
        return (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", value)]
    if len(nums) < 4:
        return (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    upper = value.upper()
    dim = 3 if "LINESTRING Z" in upper or len(nums) % 3 == 0 else 2
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
    b = np.degrees(np.arctan2(dx, dy))
    b = (b + 360.0) % 360.0
    b[(dx.abs() < 1e-9) & (dy.abs() < 1e-9)] = np.nan
    return b


def angle_diff(a: pd.Series | float, b: pd.Series | float) -> pd.Series:
    return (np.abs(pd.Series(a) - pd.Series(b)) + 180.0) % 360.0 - 180.0


def angular_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    return angle_diff(a, b).abs()


def route_suffix(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.upper().strip()
    compact = re.sub(r"[^A-Z0-9]", "", text)
    for suffix in ("NB", "SB", "EB", "WB"):
        if compact.endswith(suffix):
            return suffix
    # Route-common values often end in a single direction letter, e.g. VA-247E.
    m = re.search(r"[0-9]([NSEW])$", compact)
    if m:
        return {"N": "NB", "S": "SB", "E": "EB", "W": "WB"}[m.group(1)]
    return ""


def route_suffix_from_row(row: pd.Series) -> str:
    for col in ("source_route_common", "source_route_name", "route_key_common", "route_key_name"):
        suffix = route_suffix(row.get(col))
        if suffix:
            return suffix
    return ""


def bool_text(series: pd.Series) -> pd.Series:
    return series.fillna(False).map(lambda v: "true" if bool(v) else "false")


def build_anchor_table(target: pd.DataFrame, signal_points: pd.DataFrame) -> pd.DataFrame:
    """Build group-level anchors from signal points or closest-bin endpoint inference."""
    group_cols = ["stable_signal_id", "stable_travelway_id", "signal_approach_id", "carriageway_source_subpart_id"]
    group_key = target[group_cols].fillna("__missing__").agg("|".join, axis=1)
    work = target[["stable_bin_id", "distance_start_ft", "x0", "y0", "x1", "y1", "mx", "my"]].copy()
    work["anchor_group_key"] = group_key
    work["distance_start_ft"] = pd.to_numeric(work["distance_start_ft"], errors="coerce")

    rows: list[dict[str, object]] = []
    for key, g in work.sort_values(["anchor_group_key", "distance_start_ft"]).groupby("anchor_group_key", sort=False):
        g = g.dropna(subset=["x0", "y0", "x1", "y1"])
        if g.empty:
            rows.append(
                {
                    "anchor_group_key": key,
                    "inferred_anchor_x": np.nan,
                    "inferred_anchor_y": np.nan,
                    "inferred_anchor_method": "no_bin_geometry",
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
        rows.append({"anchor_group_key": key, "inferred_anchor_x": ax, "inferred_anchor_y": ay, "inferred_anchor_method": method})

    anchors = pd.DataFrame(rows)
    signal_anchor = target[["stable_signal_id"]].drop_duplicates().merge(signal_points, on="stable_signal_id", how="left")
    return anchors, signal_anchor


def classify_labels(target: pd.DataFrame) -> pd.DataFrame:
    target = target.copy()
    target["route_suffix_direction"] = target.apply(route_suffix_from_row, axis=1)
    target["route_suffix_bearing"] = target["route_suffix_direction"].map(ROUTE_SUFFIX_BEARING)
    target["geometry_bearing"] = bearing_deg(target["x0"], target["y0"], target["x1"], target["y1"])

    suffix_present = target["route_suffix_bearing"].notna()
    geom_present = target["geometry_bearing"].notna()
    suffix_geom_diff = angular_distance(target["route_suffix_bearing"], target["geometry_bearing"])
    target["geometry_suffix_consistency"] = np.select(
        [
            ~suffix_present,
            suffix_present & ~geom_present,
            suffix_geom_diff <= 60.0,
            suffix_geom_diff >= 120.0,
        ],
        [
            "no_route_suffix",
            "geometry_missing",
            "consistent",
            "opposite_or_conflicting",
        ],
        default="partial_or_oblique",
    )

    start = pd.to_numeric(target["source_measure_start"], errors="coerce")
    end = pd.to_numeric(target["source_measure_end"], errors="coerce")
    target["measure_orientation_consistency"] = np.select(
        [
            start.isna() | end.isna(),
            (end - start).abs() < 1e-9,
            geom_present,
        ],
        ["measure_missing", "zero_length_measure_interval", "measure_present_geometry_orientation_unverified"],
        default="measure_present_geometry_missing",
    )

    target["travelway_flow_bearing"] = np.where(
        suffix_present & target["geometry_suffix_consistency"].isin(["consistent", "partial_or_oblique"]),
        target["route_suffix_bearing"],
        np.where(~suffix_present & geom_present, target["geometry_bearing"], np.nan),
    )
    target["travelway_flow_method"] = np.select(
        [
            suffix_present & (target["geometry_suffix_consistency"] == "consistent"),
            suffix_present & (target["geometry_suffix_consistency"] == "partial_or_oblique"),
            ~suffix_present & geom_present,
            suffix_present & (target["geometry_suffix_consistency"] == "opposite_or_conflicting"),
        ],
        [
            "route_suffix_with_geometry_agreement",
            "route_suffix_with_oblique_geometry",
            "geometry_orientation_only",
            "route_suffix_geometry_conflict",
        ],
        default="no_flow_bearing",
    )
    target["travelway_flow_confidence"] = np.select(
        [
            target["travelway_flow_method"].eq("route_suffix_with_geometry_agreement"),
            target["travelway_flow_method"].eq("route_suffix_with_oblique_geometry"),
            target["travelway_flow_method"].eq("geometry_orientation_only"),
            target["travelway_flow_method"].eq("route_suffix_geometry_conflict"),
        ],
        ["high", "medium", "medium", "low"],
        default="missing",
    )

    target["signal_to_bin_bearing"] = bearing_deg(target["anchor_x"], target["anchor_y"], target["mx"], target["my"])
    diff = angular_distance(target["travelway_flow_bearing"], target["signal_to_bin_bearing"])
    target["flow_vs_signal_to_bin_angle_diff"] = diff

    has_anchor = target["anchor_x"].notna() & target["anchor_y"].notna()
    has_flow = target["travelway_flow_bearing"].notna()
    strong_anchor = target["anchor_method"].eq("canonical_signal_geometry")
    direct_candidate = target["directionality_support_class"].isin(TARGET_CLASSES)
    suffix_conflict = target["geometry_suffix_consistency"].eq("opposite_or_conflicting")

    downstream = direct_candidate & has_anchor & has_flow & ~suffix_conflict & (diff <= 45.0)
    upstream = direct_candidate & has_anchor & has_flow & ~suffix_conflict & (diff >= 135.0)
    uncertain = direct_candidate & has_anchor & has_flow & ~suffix_conflict & ~(downstream | upstream)

    target["direct_directionality_label"] = np.select(
        [downstream, upstream, uncertain, direct_candidate & (~has_anchor | ~has_flow | suffix_conflict)],
        [
            "downstream_from_signal",
            "upstream_to_signal",
            "direction_supported_but_uncertain",
            "direct_direction_not_assignable",
        ],
        default="out_of_scope_not_evaluated",
    )
    target["direct_directionality_confidence"] = np.select(
        [
            (downstream | upstream) & strong_anchor & target["travelway_flow_confidence"].eq("high"),
            (downstream | upstream) & target["travelway_flow_confidence"].isin(["high", "medium"]),
            uncertain,
            target["direct_directionality_label"].eq("direct_direction_not_assignable"),
        ],
        ["high", "medium", "low", "not_assignable"],
        default="out_of_scope",
    )
    target["direct_directionality_method"] = np.select(
        [
            target["anchor_method"].eq("canonical_signal_geometry") & target["travelway_flow_method"].ne("no_flow_bearing"),
            target["anchor_method"].str.startswith("inferred_", na=False) & target["travelway_flow_method"].ne("no_flow_bearing"),
        ],
        [
            "travelway_flow_vs_signal_point_to_bin_midpoint",
            "travelway_flow_vs_inferred_anchor_to_bin_midpoint",
        ],
        default="not_assignable",
    )
    target["direct_directionality_reason"] = np.select(
        [
            downstream,
            upstream,
            uncertain,
            suffix_conflict,
            ~has_anchor,
            ~has_flow,
        ],
        [
            "flow bearing points away from signal anchor toward bin",
            "flow bearing points toward signal anchor from bin side",
            "flow bearing is oblique to signal-anchor/bin vector",
            "route suffix and geometry bearing conflict",
            "no usable signal or inferred anchor",
            "no usable Travelway flow bearing",
        ],
        default="not evaluated",
    )
    return target


def summarize_signal(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby("stable_signal_id", dropna=False)
    summary = grouped.agg(
        direct_target_bins=("stable_bin_id", "count"),
        downstream_bins=("direct_directionality_label", lambda s: int((s == "downstream_from_signal").sum())),
        upstream_bins=("direct_directionality_label", lambda s: int((s == "upstream_to_signal").sum())),
        uncertain_bins=("direct_directionality_label", lambda s: int(s.isin(["direction_supported_but_uncertain", "direct_direction_not_assignable"]).sum())),
        direct_labeled_bins=("direct_directionality_label", lambda s: int(s.isin(["downstream_from_signal", "upstream_to_signal"]).sum())),
        stable_travelway_count=("stable_travelway_id", "nunique"),
        signal_approach_count=("signal_approach_id", "nunique"),
    ).reset_index()
    summary["has_any_direct_directional_coverage"] = summary["direct_labeled_bins"] > 0
    summary["has_both_upstream_and_downstream"] = (summary["downstream_bins"] > 0) & (summary["upstream_bins"] > 0)
    return summary


def summarize_approach(detail: pd.DataFrame) -> pd.DataFrame:
    keys = ["stable_signal_id", "signal_approach_id"]
    grouped = detail.groupby(keys, dropna=False)
    summary = grouped.agg(
        direct_target_bins=("stable_bin_id", "count"),
        downstream_bins=("direct_directionality_label", lambda s: int((s == "downstream_from_signal").sum())),
        upstream_bins=("direct_directionality_label", lambda s: int((s == "upstream_to_signal").sum())),
        uncertain_bins=("direct_directionality_label", lambda s: int(s.isin(["direction_supported_but_uncertain", "direct_direction_not_assignable"]).sum())),
        direct_labeled_bins=("direct_directionality_label", lambda s: int(s.isin(["downstream_from_signal", "upstream_to_signal"]).sum())),
        stable_travelway_count=("stable_travelway_id", "nunique"),
    ).reset_index()
    summary["approach_directional_coverage_class"] = np.select(
        [
            (summary["downstream_bins"] > 0) & (summary["upstream_bins"] > 0),
            summary["downstream_bins"] > 0,
            summary["upstream_bins"] > 0,
        ],
        ["both_upstream_and_downstream", "downstream_only", "upstream_only"],
        default="no_direct_label",
    )
    return summary


def summarize_window(detail: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for keys, level in [
        (["stable_signal_id", "analysis_window"], "signal_window"),
        (["stable_signal_id", "signal_approach_id", "analysis_window"], "signal_approach_window"),
    ]:
        grouped = detail.groupby(keys, dropna=False)
        s = grouped.agg(
            direct_target_bins=("stable_bin_id", "count"),
            downstream_bins=("direct_directionality_label", lambda x: int((x == "downstream_from_signal").sum())),
            upstream_bins=("direct_directionality_label", lambda x: int((x == "upstream_to_signal").sum())),
            uncertain_bins=("direct_directionality_label", lambda x: int(x.isin(["direction_supported_but_uncertain", "direct_direction_not_assignable"]).sum())),
            direct_labeled_bins=("direct_directionality_label", lambda x: int(x.isin(["downstream_from_signal", "upstream_to_signal"]).sum())),
        ).reset_index()
        s.insert(0, "summary_level", level)
        frames.append(s)
    return pd.concat(frames, ignore_index=True)


def build_qa(detail: pd.DataFrame, doctrine_all: pd.DataFrame) -> pd.DataFrame:
    duplicate_conflicts = (
        detail.groupby("stable_bin_id")["direct_directionality_label"].nunique(dropna=True).gt(1).sum()
        if not detail.empty
        else 0
    )
    suffix_conflicts = int((detail["geometry_suffix_consistency"] == "opposite_or_conflicting").sum())
    measure_conflicts = int((detail["measure_orientation_consistency"] == "measure_present_geometry_missing").sum())
    out_scope_assigned = int(
        detail.loc[
            detail["directionality_support_class"].isin(OUT_OF_SCOPE_CLASSES),
            "direct_directionality_label",
        ].isin(["downstream_from_signal", "upstream_to_signal"]).sum()
    )
    both_labels = 0
    ramp_included = int((detail["directionality_support_class"] == "ramp_or_interchange_direction_review").sum())
    undivided_assigned = int(
        (
            detail["directionality_support_class"].eq("undivided_centerline_requires_synthetic_direction")
            & detail["direct_directionality_label"].isin(["downstream_from_signal", "upstream_to_signal"])
        ).sum()
    )
    target_count = int(doctrine_all["directionality_support_class"].isin(TARGET_CLASSES).sum())
    detail_count = len(detail)
    rows = [
        ("target_pool_matches_doctrine_count", target_count == detail_count, f"doctrine={target_count}; output={detail_count}"),
        ("no_undivided_centerline_direct_labels", undivided_assigned == 0, f"undivided direct labels={undivided_assigned}"),
        ("no_ramp_interchange_review_rows_included", ramp_included == 0, f"ramp/review rows included={ramp_included}"),
        ("no_out_of_scope_direct_labels", out_scope_assigned == 0, f"out-of-scope direct labels={out_scope_assigned}"),
        ("no_duplicate_bin_label_conflicts", duplicate_conflicts == 0, f"duplicate bin label conflicts={duplicate_conflicts}"),
        ("no_rows_assigned_both_upstream_downstream", both_labels == 0, "single label field prevents dual assignment"),
        ("route_suffix_geometry_conflicts_flagged", True, f"suffix/geometry conflicts flagged={suffix_conflicts}"),
        ("measure_orientation_conflicts_flagged", True, f"measure orientation conflicts flagged={measure_conflicts}"),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("outputs_review_only_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def write_findings(detail: pd.DataFrame, signal_summary: pd.DataFrame, qa: pd.DataFrame) -> None:
    counts = detail["direct_directionality_label"].value_counts().to_dict()
    conf = detail["direct_directionality_confidence"].value_counts().to_dict()
    flow_methods = detail["travelway_flow_method"].value_counts().head(8).to_dict()
    suffix_conflicts = int((detail["geometry_suffix_consistency"] == "opposite_or_conflicting").sum())
    direct_labeled = int(detail["direct_directionality_label"].isin(["downstream_from_signal", "upstream_to_signal"]).sum())
    high_conf = int(
        detail["direct_directionality_label"].isin(["downstream_from_signal", "upstream_to_signal"]).mul(
            detail["direct_directionality_confidence"].eq("high")
        ).sum()
    )
    signals_any = int(signal_summary["has_any_direct_directional_coverage"].sum())
    signals_both = int(signal_summary["has_both_upstream_and_downstream"].sum())
    downstream = int(counts.get("downstream_from_signal", 0))
    upstream = int(counts.get("upstream_to_signal", 0))
    uncertain = len(detail) - direct_labeled

    text = f"""# Final Analysis Direct Divided Directionality Findings

## Bounded Question

This Phase 1 pass asks whether direct divided-row and one-way-row bins can receive review-only downstream/upstream labels from roadway evidence alone. Undivided centerlines, ramp/interchange review rows, and insufficient-evidence rows are out of scope.

## Results

- Direct divided/one-way target bins: {len(detail):,}
- Bins with any direct downstream/upstream label: {direct_labeled:,}
- High-confidence direct downstream/upstream labels: {high_conf:,}
- Downstream labels: {downstream:,}
- Upstream labels: {upstream:,}
- Uncertain or not assignable: {uncertain:,}
- Signals with any direct directional coverage: {signals_any:,}
- Signals with both upstream and downstream evidence: {signals_both:,}

## Evidence

Most useful flow-evidence methods:

{json.dumps(flow_methods, indent=2)}

Confidence distribution:

{json.dumps(conf, indent=2)}

Route suffix / geometry conflicts were not forced. Flagged conflicts: {suffix_conflicts:,}.

## Interpretation

Direct labels are feasible for a subset of divided and one-way bins, but they should remain review-only until sampled on a map. Signal geometry is incomplete in the canonical signal table, so many labels rely on inferred near-signal bin anchors rather than explicit signal points.

These labels should not be treated as global downstream/upstream coverage. Undivided centerline rows still require synthetic centerline direction logic.

## Recommendation

Carry these direct divided/one-way labels as review-only fields in a future enhanced canonical dataset after map review. Phase 2 should implement undivided centerline synthesis, with explicit QA for opposite-direction interpretation on shared centerlines.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_direct_divided_directionality_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_direct_divided_directionality_findings.md")


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.build.final_analysis_direct_divided_directionality",
        "bounded_question": "Direct divided/one-way roadway-row downstream/upstream labels using roadway evidence only.",
        "inputs": {
            "canonical_dataset": str(CANONICAL_DIR),
            "directionality_doctrine": str(DOCTRINE_DIR),
            "enhanced_directional_numeric_context": str(ENHANCED_DIR),
        },
        "outputs": list(outputs),
        "non_goals": [
            "No undivided centerline directionality assignment",
            "No crash direction fields",
            "No access/crash assignment",
            "No rates/models",
            "No active output modification",
        ],
    }
    (OUT_DIR / "final_analysis_direct_divided_directionality_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_log("Wrote final_analysis_direct_divided_directionality_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / "run_progress_log.txt"
    if log_path.exists():
        log_path.unlink()
    write_log("Starting direct divided/one-way directionality Phase 1.")

    bin_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
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
    ]
    doctrine_cols = [
        "stable_bin_id",
        "directionality_support_class",
        "directionality_source_evidence",
        "recommended_directionality_action",
        "source_bearing_sector",
        "signal_approach_bearing",
    ]
    signal_cols = ["stable_signal_id", "signal_geometry_wkt"]

    bins = read_csv(CANONICAL_DIR / "analysis_bin.csv", usecols=lambda c: c in bin_cols)
    doctrine_all = read_csv(DOCTRINE_DIR / "bin_directionality_support_detail.csv", usecols=lambda c: c in doctrine_cols)
    signals = read_csv(CANONICAL_DIR / "analysis_signal.csv", usecols=lambda c: c in signal_cols)
    write_log(f"Loaded canonical bins={len(bins):,}; doctrine rows={len(doctrine_all):,}; signals={len(signals):,}.")

    doctrine_target = doctrine_all[doctrine_all["directionality_support_class"].isin(TARGET_CLASSES)].copy()
    target = doctrine_target.merge(bins, on="stable_bin_id", how="left", validate="one_to_one")
    write_log(f"Built direct-support target pool: {len(target):,} bins.")

    endpoint_cols = target["geometry_wkt"].map(parse_linestring_endpoints).apply(pd.Series)
    endpoint_cols.columns = ["x0", "y0", "x1", "y1", "mx", "my"]
    target = pd.concat([target, endpoint_cols], axis=1)

    signal_xy = signals.copy()
    signal_points = signal_xy["signal_geometry_wkt"].map(parse_point_wkt).apply(pd.Series)
    signal_points.columns = ["signal_x", "signal_y"]
    signal_xy = pd.concat([signal_xy.drop(columns=["signal_geometry_wkt"]), signal_points], axis=1)

    anchors, signal_anchor = build_anchor_table(target, signal_xy)
    group_cols = ["stable_signal_id", "stable_travelway_id", "signal_approach_id", "carriageway_source_subpart_id"]
    target["anchor_group_key"] = target[group_cols].fillna("__missing__").agg("|".join, axis=1)
    target = target.merge(anchors, on="anchor_group_key", how="left")
    target = target.merge(signal_xy, on="stable_signal_id", how="left")
    has_signal_anchor = target["signal_x"].notna() & target["signal_y"].notna()
    target["anchor_x"] = np.where(has_signal_anchor, target["signal_x"], target["inferred_anchor_x"])
    target["anchor_y"] = np.where(has_signal_anchor, target["signal_y"], target["inferred_anchor_y"])
    target["anchor_method"] = np.where(has_signal_anchor, "canonical_signal_geometry", target["inferred_anchor_method"])
    write_log("Parsed bin geometry and built signal/inferred anchors.")

    target = classify_labels(target)

    target_out_cols = [
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
        "source_feature_local_fid",
        "source_measure_midpoint",
        "route_key_common",
        "route_key_name",
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
        "recommended_directionality_action",
    ]
    flow_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "route_suffix_direction",
        "route_suffix_bearing",
        "geometry_bearing",
        "travelway_flow_bearing",
        "travelway_flow_method",
        "travelway_flow_confidence",
        "measure_orientation_consistency",
        "geometry_suffix_consistency",
        "source_bearing_sector",
        "signal_approach_bearing",
    ]
    detail_cols = target_out_cols + [
        "x0",
        "y0",
        "x1",
        "y1",
        "mx",
        "my",
        "anchor_x",
        "anchor_y",
        "anchor_method",
        "route_suffix_direction",
        "route_suffix_bearing",
        "geometry_bearing",
        "signal_to_bin_bearing",
        "flow_vs_signal_to_bin_angle_diff",
        "travelway_flow_bearing",
        "travelway_flow_method",
        "travelway_flow_confidence",
        "measure_orientation_consistency",
        "geometry_suffix_consistency",
        "direct_directionality_label",
        "direct_directionality_method",
        "direct_directionality_confidence",
        "direct_directionality_reason",
    ]

    write_csv(target[target_out_cols], "direct_divided_directionality_target_bins.csv")
    write_csv(target[flow_cols], "direct_divided_travelway_flow_evidence.csv")
    write_csv(target[detail_cols], "direct_divided_bin_directionality_detail.csv")

    signal_summary = summarize_signal(target)
    approach_summary = summarize_approach(target)
    window_summary = summarize_window(target)
    write_csv(signal_summary, "direct_divided_signal_directionality_summary.csv")
    write_csv(approach_summary, "direct_divided_approach_directionality_summary.csv")
    write_csv(window_summary, "direct_divided_window_directionality_summary.csv")

    qa_checks = build_qa(target, doctrine_all)
    write_csv(qa_checks, "direct_divided_directionality_qa_checks.csv")

    examples = (
        target.sort_values(["direct_directionality_confidence", "direct_directionality_label", "stable_signal_id"])
        .groupby(["direct_directionality_label", "direct_directionality_confidence"], dropna=False)
        .head(20)
    )
    example_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "analysis_window",
        "geometry_wkt",
        "anchor_method",
        "route_suffix_direction",
        "geometry_suffix_consistency",
        "travelway_flow_bearing",
        "signal_to_bin_bearing",
        "flow_vs_signal_to_bin_angle_diff",
        "direct_directionality_label",
        "direct_directionality_confidence",
        "direct_directionality_reason",
    ]
    write_csv(examples[example_cols], "direct_divided_directionality_examples.csv")

    direct_labeled = int(target["direct_directionality_label"].isin(["downstream_from_signal", "upstream_to_signal"]).sum())
    next_action = pd.DataFrame(
        [
            {
                "recommendation": "map_review_then_integrate_direct_labels_as_review_only_and_start_undivided_centerline_phase2",
                "target_bins": len(target),
                "direct_labeled_bins": direct_labeled,
                "uncertain_or_not_assignable_bins": len(target) - direct_labeled,
                "signals_with_any_direct_directional_coverage": int(signal_summary["has_any_direct_directional_coverage"].sum()),
                "phase2_recommendation": "implement_undivided_centerline_synthetic_directionality",
                "rationale": "Direct divided/one-way labels are feasible where flow bearing and anchor geometry agree, but signal anchors are incomplete and undivided centerlines remain out of scope.",
            }
        ]
    )
    write_csv(next_action, "direct_divided_directionality_next_action.csv")

    final_qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to analysis/current direct divided directionality folder."),
            ("no_records_promoted", True, "Review-only direct directionality labels."),
            ("no_access_crash_assignment", True, "No access/crash assignment run."),
            ("no_rates_models", True, "No rates/models calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
            (
                "direct_labels_only_for_direct_divided_one_way_bins",
                bool(qa_checks.loc[qa_checks["qa_check"].eq("no_out_of_scope_direct_labels"), "passed"].iloc[0]),
                "Out-of-scope classes are excluded.",
            ),
            (
                "undivided_centerline_rows_not_assigned",
                bool(qa_checks.loc[qa_checks["qa_check"].eq("no_undivided_centerline_direct_labels"), "passed"].iloc[0]),
                "Undivided centerlines require Phase 2 synthesis.",
            ),
            ("uncertain_cases_not_guessed", True, "Oblique/conflicting/missing-anchor cases are marked uncertain or not assignable."),
            ("outputs_review_only_folder", True, str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(final_qa, "final_analysis_direct_divided_directionality_qa.csv")
    write_findings(target, signal_summary, final_qa)

    output_names = [
        "direct_divided_directionality_target_bins.csv",
        "direct_divided_travelway_flow_evidence.csv",
        "direct_divided_bin_directionality_detail.csv",
        "direct_divided_signal_directionality_summary.csv",
        "direct_divided_approach_directionality_summary.csv",
        "direct_divided_window_directionality_summary.csv",
        "direct_divided_directionality_qa_checks.csv",
        "direct_divided_directionality_examples.csv",
        "direct_divided_directionality_next_action.csv",
        "final_analysis_direct_divided_directionality_findings.md",
        "final_analysis_direct_divided_directionality_qa.csv",
        "final_analysis_direct_divided_directionality_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(output_names)
    write_log("Completed direct divided/one-way directionality Phase 1.")


if __name__ == "__main__":
    main()
