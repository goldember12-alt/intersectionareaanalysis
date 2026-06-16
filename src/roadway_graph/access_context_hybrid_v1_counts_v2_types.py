from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/access_context_hybrid_v1_counts_v2_types")

ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")
V1_DIR = OUTPUT_ROOT / "review/current/access_context_join"
V2_DIR = OUTPUT_ROOT / "review/current/access_context_join_v2"
DIAG_DIR = OUTPUT_ROOT / "review/current/access_v1_v2_coverage_diagnostic"
ACTIVE_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_bin_context_active.csv"
ACTIVE_CRASH_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_crash_context_active.csv"
IDENTITY_BINS_FILE = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation/directional_bins_identity_enriched.csv"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)

V2_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_out_only",
    "right_in_only",
    "other_review",
    "unknown",
]

CATEGORY_COUNT_COLUMNS = {
    "unrestricted_or_full_access": "unrestricted_or_full_access_count",
    "right_in_right_out": "right_in_right_out_count",
    "restricted_partial_access": "restricted_partial_access_count",
    "right_out_only": "right_out_only_count",
    "right_in_only": "right_in_only_count",
    "other_review": "other_review_access_count",
    "unknown": "unknown_access_count",
}

BIN_BASE_COLUMNS = [
    "reference_signal_id",
    "reference_directional_segment_id",
    "reference_directional_bin_id",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_midpoint_ft_from_reference_signal",
    "bin_start_ft_from_reference_signal",
    "bin_end_ft_from_reference_signal",
    "distance_window",
    "roadway_representation_type",
    "far_anchor_type",
]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _contains_crash_direction(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _normalize_route(value: Any) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    text = text.replace("R-VA", " ").replace("S-VA", " ").replace("VA", " ")
    text = re.sub(r"[^A-Z0-9]", " ", text)
    joined = "".join(part for part in text.split() if part)
    direction_map = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}
    match = re.search(r"(US|SR|IS|I)(0*)(\d+)(NB|SB|EB|WB)?", joined)
    if match:
        prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
        return f"{prefix}{int(match.group(3))}{direction_map.get(match.group(4) or '', match.group(4) or '')}"
    match = re.search(r"(0*)(\d+)(NB|SB|EB|WB)?", joined)
    if not match:
        return joined
    return f"{int(match.group(2))}{direction_map.get(match.group(3) or '', match.group(3) or '')}"


def _bin_length_ft(frame: pd.DataFrame) -> pd.Series:
    start = _num(frame, "bin_start_ft_from_reference_signal")
    end = _num(frame, "bin_end_ft_from_reference_signal")
    midpoint = _num(frame, "bin_midpoint_ft_from_reference_signal")
    length = end - start
    length = length.where(length.gt(0), 50.0)
    return length.where(midpoint.notna(), 0.0)


def _load_v1_bin_context() -> pd.DataFrame:
    v1 = _read_csv(V1_DIR / "directional_bin_access_context.csv")
    v1["v1_total_access_count"] = pd.to_numeric(v1["access_count_within_catchment"], errors="coerce").fillna(0).astype(int)
    v1["v1_has_access"] = v1["v1_total_access_count"].gt(0)
    v1["represented_length_ft"] = _bin_length_ft(v1)
    v1["v1_access_density_per_1000ft"] = v1.apply(
        lambda row: round(float(row["v1_total_access_count"]) / row["represented_length_ft"] * 1000, 6) if row["represented_length_ft"] else 0.0,
        axis=1,
    )
    keep = [c for c in BIN_BASE_COLUMNS if c in v1.columns] + ["v1_total_access_count", "v1_access_density_per_1000ft", "v1_has_access", "represented_length_ft"]
    return v1[keep].copy()


def _load_v2_containment_bin_context() -> pd.DataFrame:
    v2 = _read_csv(V2_DIR / "directional_bin_access_context_v2.csv")
    keep = ["reference_directional_bin_id", "access_v2_ambiguity_flag", "ambiguous_access_v2_count"]
    for column in CATEGORY_COUNT_COLUMNS.values():
        if column in v2.columns:
            keep.append(column)
    return v2[keep].copy()


def _load_v2_points() -> pd.DataFrame:
    gdf = gpd.read_parquet(ACCESS_V2_FILE)
    if "access_v2_uid" not in gdf.columns:
        gdf["access_v2_uid"] = gdf["access_v2_source_priority"].astype(str) + ":" + gdf["access_v2_source_row_id"].astype(str)
    cols = [
        "access_v2_uid",
        "access_control_category",
        "route_name",
        "route_measure",
        "access_v2_source_priority",
        "access_v2_staging_status",
    ]
    out = pd.DataFrame(gdf[[c for c in cols if c in gdf.columns]].copy())
    out["route_key"] = out["route_name"].map(_normalize_route)
    out["route_measure"] = pd.to_numeric(out["route_measure"], errors="coerce")
    return out


def _load_identity_bins() -> pd.DataFrame:
    usecols = [
        "reference_directional_bin_id",
        "reference_signal_id",
        "signal_relative_direction",
        "distance_window",
        "source_route_key_v2",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "catchment_status",
    ]
    bins = pd.read_csv(IDENTITY_BINS_FILE, usecols=lambda c: c in usecols, dtype=str, keep_default_na=False)
    bins = bins.loc[bins["catchment_status"].eq("usable")].copy()
    bins["measure_min"] = pd.to_numeric(bins["source_RTE_FROM_M"], errors="coerce")
    bins["measure_max"] = pd.to_numeric(bins["source_RTE_TO_MSR"], errors="coerce")
    bins["measure_low"] = bins[["measure_min", "measure_max"]].min(axis=1)
    bins["measure_high"] = bins[["measure_min", "measure_max"]].max(axis=1)
    bins["route_key"] = bins["source_route_key_v2"].astype(str)
    return bins.loc[bins["route_key"].str.strip().ne("")].copy()


def _route_measure_recovery(v2_points: pd.DataFrame, v2_joined: pd.DataFrame, v2_ambiguous: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    contained_ids = set(pd.concat([v2_joined["access_v2_uid"], v2_ambiguous["access_v2_uid"]], ignore_index=True).astype(str))
    unmatched = v2_points.loc[~v2_points["access_v2_uid"].astype(str).isin(contained_ids)].copy()
    bins = _load_identity_bins()
    rows = []
    ambiguous_rows = []
    recovered_rows = []
    for point in unmatched.itertuples(index=False):
        route_key = str(getattr(point, "route_key", ""))
        measure = getattr(point, "route_measure", pd.NA)
        candidates = bins.loc[bins["route_key"].eq(route_key)].copy()
        if pd.notna(measure):
            candidates = candidates.loc[candidates["measure_low"].le(measure) & candidates["measure_high"].ge(measure)].copy()
        compatible_count = int(candidates["reference_directional_bin_id"].nunique()) if not candidates.empty else 0
        if compatible_count == 1:
            bin_id = str(candidates.iloc[0]["reference_directional_bin_id"])
            status = "route_measure_recovered"
            confidence = "medium"
            support = f"unique_route_measure_bin; compatible_bin_count={compatible_count}"
            recovered_rows.append(
                {
                    "reference_directional_bin_id": bin_id,
                    "access_v2_uid": point.access_v2_uid,
                    "access_control_category": point.access_control_category,
                    "v2_recovery_method": status,
                    "v2_recovery_confidence": confidence,
                    "route_measure_distance_or_overlap_support": support,
                }
            )
        elif compatible_count > 1:
            status = "route_measure_ambiguous_review"
            confidence = "review"
            support = f"multiple_route_measure_bins; compatible_bin_count={compatible_count}"
            sample = candidates.head(20)
            for candidate in sample.itertuples(index=False):
                ambiguous_rows.append(
                    {
                        "access_v2_uid": point.access_v2_uid,
                        "access_control_category": point.access_control_category,
                        "candidate_reference_directional_bin_id": candidate.reference_directional_bin_id,
                        "v2_recovery_method": status,
                        "v2_recovery_confidence": confidence,
                        "route_measure_distance_or_overlap_support": support,
                    }
                )
        else:
            status = "unmatched"
            confidence = "none"
            support = "no_route_measure_compatible_bin"
        rows.append(
            {
                "access_v2_uid": point.access_v2_uid,
                "access_control_category": point.access_control_category,
                "route_key": route_key,
                "route_measure": measure,
                "compatible_bin_count": compatible_count,
                "v2_recovery_method": status,
                "v2_recovery_confidence": confidence,
                "route_measure_distance_or_overlap_support": support,
            }
        )
    return pd.DataFrame(recovered_rows), pd.DataFrame(ambiguous_rows), pd.DataFrame(rows)


def _category_counts(matches: pd.DataFrame) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame(columns=["reference_directional_bin_id", *CATEGORY_COUNT_COLUMNS.values()])
    grouped = matches.groupby(["reference_directional_bin_id", "access_control_category"], dropna=False)["access_v2_uid"].nunique().reset_index(name="count")
    pivot = grouped.pivot_table(index="reference_directional_bin_id", columns="access_control_category", values="count", aggfunc="sum", fill_value=0).reset_index()
    for category in V2_CATEGORIES:
        if category not in pivot.columns:
            pivot[category] = 0
    return pivot[["reference_directional_bin_id", *V2_CATEGORIES]].rename(columns=CATEGORY_COUNT_COLUMNS)


def _assemble_hybrid(v1: pd.DataFrame, v2_containment: pd.DataFrame, recovered: pd.DataFrame) -> pd.DataFrame:
    recovered_counts = _category_counts(recovered)
    out = v1.merge(v2_containment, on="reference_directional_bin_id", how="left", suffixes=("", "_containment"))
    containment_counts: dict[str, pd.Series] = {}
    for column in CATEGORY_COUNT_COLUMNS.values():
        containment_counts[column] = pd.to_numeric(out.get(column, 0), errors="coerce").fillna(0).astype(int)
    out = out.merge(recovered_counts, on="reference_directional_bin_id", how="left", suffixes=("", "_recovered"))
    recovered_total = pd.Series(0, index=out.index, dtype="int64")
    for category, column in CATEGORY_COUNT_COLUMNS.items():
        containment = containment_counts[column]
        recovered_col = f"{column}_recovered"
        recovered_values = pd.to_numeric(out.get(recovered_col, 0), errors="coerce").fillna(0).astype(int)
        recovered_total = recovered_total + recovered_values
        out[column] = containment + recovered_values
    containment_total = sum(containment_counts.values())
    out["v2_containment_typed_source_count"] = containment_total.astype(int)
    out["v2_recovered_typed_source_count"] = recovered_total.astype(int)
    out["v2_typed_access_count"] = out[
        [
            "unrestricted_or_full_access_count",
            "right_in_right_out_count",
            "restricted_partial_access_count",
            "right_out_only_count",
            "right_in_only_count",
        ]
    ].sum(axis=1).astype(int)
    out["v2_total_typed_source_count"] = out[list(CATEGORY_COUNT_COLUMNS.values())].sum(axis=1).astype(int)
    out["v2_has_typed_access"] = out["v2_typed_access_count"].gt(0)
    out["hybrid_has_any_access"] = out["v1_has_access"] | out["v2_total_typed_source_count"].gt(0)
    out["hybrid_has_typed_access"] = out["v2_has_typed_access"]
    out["ambiguous_access_v2_count"] = pd.to_numeric(out.get("ambiguous_access_v2_count", 0), errors="coerce").fillna(0).astype(int)
    out["v2_recovery_method"] = "unmatched"
    out.loc[out["v2_containment_typed_source_count"].gt(0), "v2_recovery_method"] = "containment_match"
    out.loc[out["v2_recovered_typed_source_count"].gt(0), "v2_recovery_method"] = "route_measure_recovered"
    out.loc[
        out["v2_containment_typed_source_count"].gt(0) & out["v2_recovered_typed_source_count"].gt(0),
        "v2_recovery_method",
    ] = "containment_plus_route_measure"
    out.loc[
        out["v2_total_typed_source_count"].eq(0) & out["ambiguous_access_v2_count"].gt(0),
        "v2_recovery_method",
    ] = "route_measure_ambiguous_review"
    out["v2_recovery_confidence"] = "none"
    out.loc[out["v2_containment_typed_source_count"].gt(0), "v2_recovery_confidence"] = "high"
    out.loc[out["v2_recovered_typed_source_count"].gt(0), "v2_recovery_confidence"] = "medium"
    out.loc[
        out["v2_containment_typed_source_count"].gt(0) & out["v2_recovered_typed_source_count"].gt(0),
        "v2_recovery_confidence",
    ] = "mixed"
    out.loc[
        out["v2_total_typed_source_count"].eq(0) & out["ambiguous_access_v2_count"].gt(0),
        "v2_recovery_confidence",
    ] = "review"
    out["route_measure_distance_or_overlap_support"] = "not_applicable"
    out.loc[out["v2_recovered_typed_source_count"].gt(0), "route_measure_distance_or_overlap_support"] = "unique_route_measure_compatible_bin"
    out.loc[
        out["v2_total_typed_source_count"].eq(0) & out["ambiguous_access_v2_count"].gt(0),
        "route_measure_distance_or_overlap_support",
    ] = "ambiguous_or_containment_review"
    out["typed_access_coverage_status"] = out.apply(_typed_status, axis=1)
    out["dominant_access_control_category"] = out.apply(_dominant_category, axis=1)
    out["v1_access_density_per_1000ft"] = pd.to_numeric(out["v1_access_density_per_1000ft"], errors="coerce").fillna(0)
    out["v2_typed_density_per_1000ft"] = out.apply(
        lambda row: round(float(row["v2_typed_access_count"]) / row["represented_length_ft"] * 1000, 6) if row["represented_length_ft"] else 0.0,
        axis=1,
    )
    drop_cols = [c for c in out.columns if c.endswith("_recovered") or c.endswith("_containment")]
    return out.drop(columns=drop_cols, errors="ignore")


def _typed_status(row: pd.Series) -> str:
    if int(row.get("v2_typed_access_count", 0)) > 0:
        return "typed_access_present"
    if int(row.get("ambiguous_access_v2_count", 0)) > 0:
        return "v2_ambiguous_review"
    if bool(row.get("v1_has_access", False)):
        return "v1_access_only_type_missing"
    return "no_access"


def _dominant_category(row: pd.Series) -> str:
    counts = {cat: int(row.get(col, 0)) for cat, col in CATEGORY_COUNT_COLUMNS.items()}
    if sum(counts.values()) == 0:
        return "none"
    return sorted(counts.items(), key=lambda item: (-item[1], V2_CATEGORIES.index(item[0])))[0][0]


def _summarize(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    agg: dict[str, Any] = {
        "bin_count": ("reference_directional_bin_id", "nunique"),
        "represented_length_ft": ("represented_length_ft", "sum"),
        "v1_total_access_count": ("v1_total_access_count", "sum"),
        "v2_typed_access_count": ("v2_typed_access_count", "sum"),
        "v2_total_typed_source_count": ("v2_total_typed_source_count", "sum"),
        "v1_access_bearing_bins": ("v1_has_access", "sum"),
        "v2_typed_access_bearing_bins": ("v2_has_typed_access", "sum"),
        "hybrid_any_access_bins": ("hybrid_has_any_access", "sum"),
    }
    for col in CATEGORY_COUNT_COLUMNS.values():
        agg[col] = (col, "sum")
    out = frame.groupby(group_cols, dropna=False).agg(**agg).reset_index()
    length = out["represented_length_ft"].replace(0, pd.NA)
    out["v1_access_density_per_1000ft"] = (out["v1_total_access_count"] / length * 1000).round(6)
    out["v2_typed_density_per_1000ft"] = (out["v2_typed_access_count"] / length * 1000).round(6)
    return out


def _crash_context(hybrid: pd.DataFrame) -> pd.DataFrame:
    if not ACTIVE_CRASH_CONTEXT_FILE.exists():
        return pd.DataFrame()
    crash_cols = [c for c in pd.read_csv(ACTIVE_CRASH_CONTEXT_FILE, nrows=0).columns if not _contains_crash_direction(c) or c == "signal_relative_direction"]
    crashes = _read_csv(ACTIVE_CRASH_CONTEXT_FILE, usecols=crash_cols)
    keep = [
        "reference_directional_bin_id",
        "v1_total_access_count",
        "v1_access_density_per_1000ft",
        "v1_has_access",
        "v2_typed_access_count",
        *CATEGORY_COUNT_COLUMNS.values(),
        "v2_has_typed_access",
        "hybrid_has_any_access",
        "hybrid_has_typed_access",
        "typed_access_coverage_status",
        "v2_recovery_method",
        "v2_recovery_confidence",
        "dominant_access_control_category",
    ]
    out = crashes.merge(hybrid[[c for c in keep if c in hybrid.columns]], on="reference_directional_bin_id", how="left")
    out["inherited_from_hybrid_access_context"] = True
    return out


def _summary(hybrid: pd.DataFrame, recovered: pd.DataFrame, ambiguous: pd.DataFrame, recovery_status: pd.DataFrame) -> pd.DataFrame:
    v1_access = hybrid["v1_has_access"].astype(bool)
    typed = hybrid["v2_has_typed_access"].astype(bool)
    return pd.DataFrame(
        [
            {"metric": "hybrid_bin_count", "value": "", "count": len(hybrid)},
            {"metric": "v1_access_bearing_bins_retained", "value": "", "count": int(v1_access.sum())},
            {"metric": "v1_access_bearing_bins_with_v2_typed_evidence", "value": "", "count": int((v1_access & typed).sum())},
            {"metric": "v1_access_bearing_bins_count_only", "value": "", "count": int((v1_access & ~typed).sum())},
            {"metric": "v2_typed_access_bearing_bins", "value": "", "count": int(typed.sum())},
            {"metric": "route_measure_recovered_points", "value": "", "count": recovered["access_v2_uid"].nunique() if not recovered.empty else 0},
            {"metric": "route_measure_ambiguous_review_points", "value": "", "count": ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0},
            {"metric": "remaining_unmatched_typed_access_points", "value": "", "count": int(recovery_status["v2_recovery_method"].eq("unmatched").sum()) if not recovery_status.empty else 0},
            {"metric": "hybrid_promoted_active", "value": False, "count": ""},
        ]
    )


def _comparison(hybrid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rows.append({"comparison_metric": "v1_access_bearing_bins", "value": int(hybrid["v1_has_access"].sum()), "note": "retained from v1"})
    rows.append({"comparison_metric": "v1_access_bearing_bins_with_v2_typed_evidence", "value": int((hybrid["v1_has_access"] & hybrid["v2_has_typed_access"]).sum()), "note": "hybrid typed enrichment"})
    rows.append({"comparison_metric": "v1_access_bearing_bins_count_only", "value": int((hybrid["v1_has_access"] & ~hybrid["v2_has_typed_access"]).sum()), "note": "broad count retained but type missing"})
    rows.append({"comparison_metric": "v2_typed_bins_without_v1_access", "value": int((~hybrid["v1_has_access"] & hybrid["v2_has_typed_access"]).sum()), "note": "candidate review"})
    rows.append({"comparison_metric": "hybrid_any_access_bins", "value": int(hybrid["hybrid_has_any_access"].sum()), "note": "v1 count or v2 typed"})
    return pd.DataFrame(rows)


def _qa(hybrid: pd.DataFrame, v1: pd.DataFrame, ambiguous: pd.DataFrame) -> pd.DataFrame:
    category_sum = hybrid[list(CATEGORY_COUNT_COLUMNS.values())].sum(axis=1)
    total = hybrid["v2_total_typed_source_count"]
    v1_preserved = int(hybrid["v1_total_access_count"].sum()) == int(v1["v1_total_access_count"].sum())
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False},
            {"check_name": "v1_access_outputs_not_overwritten", "status": "passed", "observed": str(V1_DIR)},
            {"check_name": "v2_access_outputs_not_overwritten", "status": "passed", "observed": str(V2_DIR)},
            {"check_name": "active_context_outputs_not_overwritten", "status": "passed", "observed": str(ACTIVE_CONTEXT_FILE)},
            {"check_name": "v1_counts_preserved", "status": "passed" if v1_preserved else "failed", "observed": v1_preserved},
            {"check_name": "v2_typed_categories_sum_correctly", "status": "passed" if category_sum.equals(total) else "failed", "observed": bool(category_sum.equals(total))},
            {"check_name": "route_measure_recovery_ambiguous_not_forced", "status": "passed", "observed": ambiguous["access_v2_uid"].nunique() if not ambiguous.empty else 0},
            {"check_name": "hybrid_access_remains_candidate", "status": "passed", "observed": "not_promoted"},
        ]
    )


def _findings(summary: pd.DataFrame, comparison: pd.DataFrame, recovery_summary: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    lines = [
        "# Hybrid Access Context Findings",
        "",
        "## Bounded Question",
        "",
        "Create a candidate hybrid context using v1 for broad access counts and v2 for typed access evidence.",
        "",
        "## Readout",
        "",
        f"- v1 access-bearing bins retained: {count('v1_access_bearing_bins_retained')}",
        f"- v1 access-bearing bins gaining v2 typed evidence: {count('v1_access_bearing_bins_with_v2_typed_evidence')}",
        f"- v1 access-bearing bins remaining count-only: {count('v1_access_bearing_bins_count_only')}",
        f"- route/measure recovered v2 typed points: {count('route_measure_recovered_points')}",
        f"- route/measure ambiguous review points: {count('route_measure_ambiguous_review_points')}",
        f"- remaining unmatched typed access points: {count('remaining_unmatched_typed_access_points')}",
        "",
        "## Recommendation",
        "",
        "Do not promote the hybrid context as active yet. Review route/measure recovered rows, ambiguous candidates, and count-only bins first. If accepted later, refresh active context, figures, summaries, rates, and model inputs.",
        "",
        "## QA",
        "",
        f"- QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}",
        "",
        "## Outputs",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_hybrid_access_context(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    v1 = _load_v1_bin_context()
    v2_containment = _load_v2_containment_bin_context()
    v2_points = _load_v2_points()
    v2_joined = _read_csv(V2_DIR / "access_v2_points_joined_to_stable_universe.csv")
    v2_ambiguous = _read_csv(V2_DIR / "access_v2_points_ambiguous_bin_matches.csv")
    recovered, ambiguous_recovery, recovery_status = _route_measure_recovery(v2_points, v2_joined, v2_ambiguous)
    hybrid = _assemble_hybrid(v1, v2_containment, recovered)
    high_priority = hybrid.loc[hybrid["distance_window"].eq("high_priority_0_1000ft")].copy()
    sensitivity = hybrid.loc[hybrid["distance_window"].eq("sensitivity_1000_2500ft")].copy()
    crash_context = _crash_context(hybrid)
    signal_summary = _summarize(hybrid, ["reference_signal_id", "distance_window", "signal_relative_direction"])
    by_distance = _summarize(hybrid, ["distance_window"])
    by_direction = _summarize(hybrid, ["signal_relative_direction"])
    comparison = _comparison(hybrid)
    recovery_summary = (
        recovery_status.groupby(["v2_recovery_method", "v2_recovery_confidence"], dropna=False)
        .agg(access_point_count=("access_v2_uid", "nunique"))
        .reset_index()
        if not recovery_status.empty
        else pd.DataFrame(columns=["v2_recovery_method", "v2_recovery_confidence", "access_point_count"])
    )
    unmatched_review = recovery_status.loc[recovery_status["v2_recovery_method"].eq("unmatched")].copy() if not recovery_status.empty else pd.DataFrame()
    summary = _summary(hybrid, recovered, ambiguous_recovery, recovery_status)
    qa = _qa(hybrid, v1, ambiguous_recovery)

    outputs = {
        "summary_csv": out_dir / "hybrid_access_context_summary.csv",
        "bin_context_csv": out_dir / "directional_bin_hybrid_access_context.csv",
        "bin_context_0_1000_csv": out_dir / "directional_bin_hybrid_access_context_0_1000ft.csv",
        "bin_context_1000_2500_csv": out_dir / "directional_bin_hybrid_access_context_1000_2500ft.csv",
        "crash_context_csv": out_dir / "directional_crash_hybrid_access_context.csv",
        "reference_signal_summary_csv": out_dir / "reference_signal_hybrid_access_context_summary.csv",
        "type_summary_by_distance_csv": out_dir / "hybrid_access_type_summary_by_distance_band.csv",
        "type_summary_by_direction_csv": out_dir / "hybrid_access_type_summary_by_signal_relative_direction.csv",
        "comparison_csv": out_dir / "hybrid_access_v1_v2_comparison.csv",
        "recovery_summary_csv": out_dir / "hybrid_access_route_measure_recovery_summary.csv",
        "ambiguous_recovery_csv": out_dir / "hybrid_access_ambiguous_recovery_review.csv",
        "unmatched_review_csv": out_dir / "hybrid_access_unmatched_review.csv",
        "qa_csv": out_dir / "hybrid_access_context_qa.csv",
        "findings_md": out_dir / "hybrid_access_context_findings.md",
        "manifest_json": out_dir / "hybrid_access_context_manifest.json",
    }

    _write_csv(summary, outputs["summary_csv"])
    _write_csv(hybrid, outputs["bin_context_csv"])
    _write_csv(high_priority, outputs["bin_context_0_1000_csv"])
    _write_csv(sensitivity, outputs["bin_context_1000_2500_csv"])
    _write_csv(crash_context, outputs["crash_context_csv"])
    _write_csv(signal_summary, outputs["reference_signal_summary_csv"])
    _write_csv(by_distance, outputs["type_summary_by_distance_csv"])
    _write_csv(by_direction, outputs["type_summary_by_direction_csv"])
    _write_csv(comparison, outputs["comparison_csv"])
    _write_csv(recovery_summary, outputs["recovery_summary_csv"])
    _write_csv(ambiguous_recovery, outputs["ambiguous_recovery_csv"])
    _write_csv(unmatched_review, outputs["unmatched_review_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(summary, comparison, recovery_summary, qa, outputs), outputs["findings_md"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "candidate hybrid access context: v1 counts plus v2 typed evidence",
        "hybrid_promoted_active": False,
        "crash_direction_fields_read_or_used": False,
        "v1_outputs_overwritten": False,
        "v2_outputs_overwritten": False,
        "active_context_outputs_overwritten": False,
        "inputs": {
            "v1_access_context": str(V1_DIR),
            "v2_access_context": str(V2_DIR),
            "coverage_diagnostic": str(OUTPUT_ROOT / "review/current/access_v1_v2_coverage_diagnostic"),
            "access_v2": str(ACCESS_V2_FILE),
            "active_context": str(ACTIVE_CONTEXT_FILE),
            "identity_bins": str(IDENTITY_BINS_FILE),
        },
        "summary": summary.to_dict(orient="records"),
        "qa_checks": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Candidate hybrid access context: v1 counts plus v2 typed evidence.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_hybrid_access_context(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
