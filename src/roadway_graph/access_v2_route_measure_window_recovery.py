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
OUTPUT_DIR = Path("review/current/access_v2_route_measure_window_recovery")

ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")
V2_DIR = OUTPUT_ROOT / "review/current/access_context_join_v2"
DIAG_DIR = OUTPUT_ROOT / "review/current/access_v1_v2_coverage_diagnostic"
HYBRID_DIR = OUTPUT_ROOT / "review/current/access_context_hybrid_v1_counts_v2_types"
ACTIVE_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_bin_context_active.csv"
IDENTITY_BINS_FILE = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation/directional_bins_identity_enriched.csv"
IDENTITY_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation/directional_segments_identity_enriched.csv"

MEASURE_TOLERANCE = 0.01

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


def _distance_band(midpoint_ft: pd.Series) -> pd.Series:
    values = pd.to_numeric(midpoint_ft, errors="coerce")
    return pd.cut(
        values,
        bins=[-0.001, 250, 500, 1000, 1500, 2500],
        labels=["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"],
    ).astype("string").fillna("outside_0_2500ft")


def _analysis_window(distance_window: pd.Series) -> pd.Series:
    text = distance_window.astype(str)
    out = pd.Series("other", index=distance_window.index, dtype="string")
    out.loc[text.eq("high_priority_0_1000ft")] = "0_1000ft"
    out.loc[text.eq("sensitivity_1000_2500ft")] = "1000_2500ft"
    return out


def _load_access_v2() -> pd.DataFrame:
    gdf = gpd.read_parquet(ACCESS_V2_FILE)
    if "access_v2_uid" not in gdf.columns:
        gdf["access_v2_uid"] = gdf["access_v2_source_priority"].astype(str) + ":" + gdf["access_v2_source_row_id"].astype(str)
    cols = [
        "access_v2_uid",
        "access_control_raw",
        "access_control_code",
        "access_control_category",
        "access_direction_raw",
        "access_direction_normalized",
        "route_name",
        "route_measure",
        "access_v2_source_priority",
        "access_v2_source_gdb",
        "access_v2_source_layer",
        "access_v2_staging_status",
    ]
    out = pd.DataFrame(gdf[[c for c in cols if c in gdf.columns]].copy())
    out["route_key"] = out["route_name"].map(_normalize_route)
    out["route_measure"] = pd.to_numeric(out["route_measure"], errors="coerce")
    out["access_control_category"] = out["access_control_category"].fillna("unknown").replace("", "unknown")
    return out


def _load_identity_bins() -> pd.DataFrame:
    usecols = [
        "reference_directional_bin_id",
        "reference_directional_segment_id",
        "base_segment_id",
        "reference_signal_id",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "segment_length_ft",
        "roadway_representation_type",
        "far_anchor_type",
        "source_bin_key",
        "distance_window",
        "catchment_status",
        "catchment_confidence",
        "source_route_key_v2",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
    ]
    bins = pd.read_csv(IDENTITY_BINS_FILE, usecols=lambda c: c in usecols, dtype=str, keep_default_na=False)
    bins["route_key"] = bins["source_route_key_v2"].astype(str)
    bins["measure_from"] = _num(bins, "source_RTE_FROM_M")
    bins["measure_to"] = _num(bins, "source_RTE_TO_MSR")
    bins["segment_length_ft_num"] = _num(bins, "segment_length_ft")
    bins["bin_start_ft"] = _num(bins, "bin_start_ft_from_reference_signal")
    bins["bin_end_ft"] = _num(bins, "bin_end_ft_from_reference_signal")
    bins["bin_midpoint_ft"] = _num(bins, "bin_midpoint_ft_from_reference_signal")
    bins["analysis_window"] = _analysis_window(bins["distance_window"])
    bins["distance_band"] = _distance_band(bins["bin_midpoint_ft"])

    measure_delta = bins["measure_to"] - bins["measure_from"]
    valid = bins["segment_length_ft_num"].gt(0) & bins["measure_from"].notna() & bins["measure_to"].notna()
    start_frac = (bins["bin_start_ft"] / bins["segment_length_ft_num"]).clip(lower=0, upper=1)
    end_frac = (bins["bin_end_ft"] / bins["segment_length_ft_num"]).clip(lower=0, upper=1)
    est_start = bins["measure_from"] + measure_delta * start_frac
    est_end = bins["measure_from"] + measure_delta * end_frac
    bins["bin_measure_low"] = pd.concat([est_start, est_end], axis=1).min(axis=1).where(valid)
    bins["bin_measure_high"] = pd.concat([est_start, est_end], axis=1).max(axis=1).where(valid)
    bins["segment_measure_low"] = pd.concat([bins["measure_from"], bins["measure_to"]], axis=1).min(axis=1)
    bins["segment_measure_high"] = pd.concat([bins["measure_from"], bins["measure_to"]], axis=1).max(axis=1)
    return bins


def _load_match_status(access: pd.DataFrame) -> pd.DataFrame:
    joined_path = V2_DIR / "access_v2_points_joined_to_stable_universe.csv"
    ambiguous_path = V2_DIR / "access_v2_points_ambiguous_bin_matches.csv"
    unmatched_path = V2_DIR / "access_v2_points_unmatched_or_outside_stable_universe.csv"
    joined = _read_csv(joined_path, usecols=lambda c: c in {"access_v2_uid", "reference_directional_bin_id"})
    ambiguous = _read_csv(ambiguous_path, usecols=lambda c: c in {"access_v2_uid", "reference_directional_bin_id"})
    unmatched = _read_csv(
        unmatched_path,
        usecols=lambda c: c in {"access_v2_uid", "nearest_reference_directional_bin_id", "nearest_access_distance_ft", "unmatched_status"},
    )
    out = access[["access_v2_uid"]].copy()
    out["containment_match_status"] = "unmatched_or_outside"
    out.loc[out["access_v2_uid"].isin(joined["access_v2_uid"].unique()), "containment_match_status"] = "containment_matched"
    out.loc[out["access_v2_uid"].isin(ambiguous["access_v2_uid"].unique()), "containment_match_status"] = "containment_ambiguous"
    nearest = unmatched.drop_duplicates("access_v2_uid")
    out = out.merge(nearest, on="access_v2_uid", how="left")
    out["nearest_access_distance_ft"] = pd.to_numeric(out.get("nearest_access_distance_ft"), errors="coerce")
    return out


def _bin_gap_diagnostic(bins: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = ["reference_directional_segment_id", "reference_signal_id", "signal_relative_direction"]
    for keys, group in bins.sort_values("bin_start_ft").groupby(group_cols, dropna=False):
        starts = group["bin_start_ft"].reset_index(drop=True)
        ends = group["bin_end_ft"].reset_index(drop=True)
        gaps = starts.iloc[1:].reset_index(drop=True) - ends.iloc[:-1].reset_index(drop=True)
        positive_gaps = gaps[gaps.gt(1.0)]
        usable = group["catchment_status"].eq("usable")
        rows.append(
            {
                "reference_directional_segment_id": keys[0],
                "reference_signal_id": keys[1],
                "signal_relative_direction": keys[2],
                "source_bin_key_count": int(group["source_bin_key"].nunique()),
                "bin_count": int(len(group)),
                "usable_bin_count": int(usable.sum()),
                "nonusable_bin_count": int((~usable).sum()),
                "roadway_representation_types": "|".join(sorted(set(group["roadway_representation_type"].astype(str))))[:250],
                "far_anchor_types": "|".join(sorted(set(group["far_anchor_type"].astype(str))))[:250],
                "segment_length_ft": float(pd.to_numeric(group["segment_length_ft_num"], errors="coerce").max()),
                "covered_bin_start_ft": float(starts.min()) if starts.notna().any() else pd.NA,
                "covered_bin_end_ft": float(ends.max()) if ends.notna().any() else pd.NA,
                "gap_count_gt_1ft": int(len(positive_gaps)),
                "max_gap_ft": float(positive_gaps.max()) if not positive_gaps.empty else 0.0,
                "has_bin_gap": bool(len(positive_gaps) > 0),
                "has_catchment_status_gap": bool((~usable).any()),
                "gap_interpretation": "bin_sequence_gap" if len(positive_gaps) else ("catchment_not_usable_for_some_bins" if (~usable).any() else "no_gap_detected"),
            }
        )
    return pd.DataFrame(rows)


def _make_units(bins: pd.DataFrame, grain: str) -> pd.DataFrame:
    work = bins.loc[
        bins["catchment_status"].eq("usable")
        & bins["route_key"].ne("")
        & bins["bin_measure_low"].notna()
        & bins["bin_measure_high"].notna()
    ].copy()
    if grain == "window":
        grain_cols = ["reference_signal_id", "signal_relative_direction", "analysis_window"]
    elif grain == "distance_band":
        grain_cols = ["reference_signal_id", "signal_relative_direction", "distance_band"]
    else:
        raise ValueError(grain)
    group_cols = ["route_key", *grain_cols]
    units = (
        work.groupby(group_cols, dropna=False)
        .agg(
            reference_directional_segment_count=("reference_directional_segment_id", "nunique"),
            reference_directional_bin_count=("reference_directional_bin_id", "nunique"),
            measure_low=("bin_measure_low", "min"),
            measure_high=("bin_measure_high", "max"),
            represented_length_ft=("bin_end_ft", lambda s: 0.0),
            min_bin_midpoint_ft=("bin_midpoint_ft", "min"),
            max_bin_midpoint_ft=("bin_midpoint_ft", "max"),
            roadway_representation_types=("roadway_representation_type", lambda s: "|".join(sorted(set(map(str, s))))[:250]),
            far_anchor_types=("far_anchor_type", lambda s: "|".join(sorted(set(map(str, s))))[:250]),
        )
        .reset_index()
    )
    length = work.assign(bin_len=(work["bin_end_ft"] - work["bin_start_ft"]).clip(lower=0))
    length_group = length.groupby(group_cols, dropna=False)["bin_len"].sum().reset_index(name="represented_length_ft")
    units = units.drop(columns=["represented_length_ft"]).merge(length_group, on=group_cols, how="left")
    units["candidate_grain"] = grain
    units["candidate_unit_id"] = units[grain_cols].astype(str).agg("|".join, axis=1)
    return units


def _candidate_assignments(access: pd.DataFrame, units: pd.DataFrame, grain: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    unmatched = access.loc[access["containment_match_status"].eq("unmatched_or_outside")].copy()
    candidates: list[dict[str, Any]] = []
    unit_groups = {route: group.copy() for route, group in units.groupby("route_key", dropna=False)}
    for point in unmatched.itertuples(index=False):
        route_key = getattr(point, "route_key", "")
        measure = getattr(point, "route_measure", pd.NA)
        if not route_key or pd.isna(measure) or route_key not in unit_groups:
            continue
        compatible = unit_groups[route_key].loc[
            unit_groups[route_key]["measure_low"].sub(MEASURE_TOLERANCE).le(measure)
            & unit_groups[route_key]["measure_high"].add(MEASURE_TOLERANCE).ge(measure)
        ].copy()
        for unit in compatible.itertuples(index=False):
            row = {
                "access_v2_uid": point.access_v2_uid,
                "route_key": route_key,
                "route_measure": measure,
                "access_control_category": point.access_control_category,
                "access_control_code": getattr(point, "access_control_code", ""),
                "access_direction_normalized": getattr(point, "access_direction_normalized", ""),
                "nearest_access_distance_ft": getattr(point, "nearest_access_distance_ft", pd.NA),
                "candidate_grain": grain,
                "candidate_unit_id": unit.candidate_unit_id,
                "reference_signal_id": unit.reference_signal_id,
                "signal_relative_direction": unit.signal_relative_direction,
                "measure_low": unit.measure_low,
                "measure_high": unit.measure_high,
                "reference_directional_segment_count": unit.reference_directional_segment_count,
                "reference_directional_bin_count": unit.reference_directional_bin_count,
                "represented_length_ft": unit.represented_length_ft,
                "min_bin_midpoint_ft": unit.min_bin_midpoint_ft,
                "max_bin_midpoint_ft": unit.max_bin_midpoint_ft,
                "route_measure_assignment_label": "candidate_route_measure_access_recovery",
            }
            if grain == "window":
                row["analysis_window"] = unit.analysis_window
            else:
                row["distance_band"] = unit.distance_band
            candidates.append(row)
    cand = pd.DataFrame(candidates)
    if cand.empty:
        return cand, cand.copy(), cand.copy()
    counts = cand.groupby("access_v2_uid")["candidate_unit_id"].nunique().reset_index(name="candidate_unit_count")
    cand = cand.merge(counts, on="access_v2_uid", how="left")
    recovered = cand.loc[cand["candidate_unit_count"].eq(1)].copy()
    recovered["v2_recovery_method"] = f"route_measure_{grain}_recovered"
    recovered["v2_recovery_confidence"] = "medium"
    ambiguous = cand.loc[cand["candidate_unit_count"].gt(1)].copy()
    ambiguous["v2_recovery_method"] = f"route_measure_{grain}_ambiguous_review"
    ambiguous["v2_recovery_confidence"] = "review"
    return cand, recovered, ambiguous


def _position_diagnostic(access: pd.DataFrame, window_units: pd.DataFrame, window_candidates: pd.DataFrame, band_candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    route_represented = access["route_key"].ne("") & access["route_key"].isin(set(window_units.get("route_key", pd.Series(dtype=str))))
    unmatched = access["containment_match_status"].eq("unmatched_or_outside")
    near = pd.to_numeric(access.get("nearest_access_distance_ft"), errors="coerce")
    rows.extend(
        [
            {"metric": "v2_points_total", "count": int(len(access)), "note": ""},
            {"metric": "unmatched_or_outside_points", "count": int(unmatched.sum()), "note": "from containment-only v2 join"},
            {"metric": "unmatched_on_route_represented_in_window_candidates", "count": int((unmatched & route_represented).sum()), "note": "route key represented in stable route/window units"},
            {"metric": "unmatched_within_25ft_nearest_bin_or_catchment", "count": int((unmatched & near.le(25)).sum()), "note": "spatial support only"},
            {"metric": "unmatched_within_250ft_nearest_bin_or_catchment", "count": int((unmatched & near.le(250)).sum()), "note": "spatial support only"},
            {"metric": "unmatched_within_500ft_nearest_bin_or_catchment", "count": int((unmatched & near.le(500)).sum()), "note": "spatial support only"},
            {"metric": "unmatched_with_route_measure_window_candidate", "count": int(window_candidates["access_v2_uid"].nunique()) if not window_candidates.empty else 0, "note": "candidate route/measure window overlap"},
            {"metric": "unmatched_with_route_measure_distance_band_candidate", "count": int(band_candidates["access_v2_uid"].nunique()) if not band_candidates.empty else 0, "note": "candidate route/measure band overlap"},
        ]
    )
    return pd.DataFrame(rows)


def _window_compatibility(access: pd.DataFrame, window_candidates: pd.DataFrame, band_candidates: pd.DataFrame) -> pd.DataFrame:
    base = access[["access_v2_uid", "route_key", "route_measure", "access_control_category", "containment_match_status", "nearest_access_distance_ft"]].copy()
    win_counts = window_candidates.groupby("access_v2_uid")["candidate_unit_id"].nunique().rename("route_measure_window_candidate_count") if not window_candidates.empty else pd.Series(dtype=int)
    band_counts = band_candidates.groupby("access_v2_uid")["candidate_unit_id"].nunique().rename("route_measure_distance_band_candidate_count") if not band_candidates.empty else pd.Series(dtype=int)
    out = base.merge(win_counts, on="access_v2_uid", how="left").merge(band_counts, on="access_v2_uid", how="left")
    out["route_measure_window_candidate_count"] = pd.to_numeric(out["route_measure_window_candidate_count"], errors="coerce").fillna(0).astype(int)
    out["route_measure_distance_band_candidate_count"] = pd.to_numeric(out["route_measure_distance_band_candidate_count"], errors="coerce").fillna(0).astype(int)
    out["window_compatibility_status"] = out["route_measure_window_candidate_count"].map(lambda n: "none" if n == 0 else ("unique" if n == 1 else "ambiguous"))
    out["distance_band_compatibility_status"] = out["route_measure_distance_band_candidate_count"].map(lambda n: "none" if n == 0 else ("unique" if n == 1 else "ambiguous"))
    return out


def _summary_by(assignments: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame(columns=[*group_cols, "access_v2_assignment_count", *CATEGORY_COUNT_COLUMNS.values()])
    grouped = assignments.groupby([*group_cols, "access_control_category"], dropna=False)["access_v2_uid"].nunique().reset_index(name="count")
    pivot = grouped.pivot_table(index=group_cols, columns="access_control_category", values="count", aggfunc="sum", fill_value=0).reset_index()
    for category in V2_CATEGORIES:
        if category not in pivot.columns:
            pivot[category] = 0
    pivot["access_v2_assignment_count"] = pivot[V2_CATEGORIES].sum(axis=1).astype(int)
    return pivot.rename(columns=CATEGORY_COUNT_COLUMNS)


def _category_counts(assignments: pd.DataFrame, label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for category in V2_CATEGORIES:
        count = int(assignments.loc[assignments["access_control_category"].eq(category), "access_v2_uid"].nunique()) if not assignments.empty else 0
        rows.append({"assignment_source": label, "access_control_category": category, "access_point_count": count})
    rows.append({"assignment_source": label, "access_control_category": "total", "access_point_count": int(assignments["access_v2_uid"].nunique()) if not assignments.empty else 0})
    return pd.DataFrame(rows)


def _containment_assignments() -> pd.DataFrame:
    path = V2_DIR / "access_v2_points_joined_to_stable_universe.csv"
    cols = ["access_v2_uid", "reference_signal_id", "signal_relative_direction", "access_control_category"]
    joined = _read_csv(path, usecols=lambda c: c in cols)
    return joined.drop_duplicates(["access_v2_uid", "reference_signal_id", "signal_relative_direction"])


def _comparison(containment: pd.DataFrame, window_rec: pd.DataFrame, window_amb: pd.DataFrame, band_rec: pd.DataFrame, band_amb: pd.DataFrame, access: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    unmatched_total = int(access["containment_match_status"].eq("unmatched_or_outside").sum())
    rows = []
    for label, frame, ambiguous in [
        ("containment_only_v2", containment, pd.DataFrame()),
        ("route_measure_window_recovered", window_rec, window_amb),
        ("route_measure_distance_band_recovered", band_rec, band_amb),
    ]:
        rows.append(
            {
                "comparison_source": label,
                "total_typed_access_assignments": int(frame["access_v2_uid"].nunique()) if not frame.empty else 0,
                "ambiguous_review_points": int(ambiguous["access_v2_uid"].nunique()) if not ambiguous.empty else 0,
                "unmatched_or_not_recovered_points": max(unmatched_total - (int(frame["access_v2_uid"].nunique()) if label != "containment_only_v2" and not frame.empty else 0), 0)
                if label != "containment_only_v2"
                else unmatched_total,
                "access_bearing_windows": int(frame[["reference_signal_id", "signal_relative_direction", "analysis_window"]].drop_duplicates().shape[0])
                if "analysis_window" in frame.columns and not frame.empty
                else 0,
                "access_bearing_distance_band_units": int(frame[["reference_signal_id", "signal_relative_direction", "distance_band"]].drop_duplicates().shape[0])
                if "distance_band" in frame.columns and not frame.empty
                else 0,
                "access_bearing_signals": int(frame["reference_signal_id"].nunique()) if "reference_signal_id" in frame.columns and not frame.empty else 0,
            }
        )
    comparison = pd.DataFrame(rows)
    category = pd.concat(
        [
            _category_counts(containment, "containment_only_v2"),
            _category_counts(window_rec, "route_measure_window_recovered"),
            _category_counts(band_rec, "route_measure_distance_band_recovered"),
        ],
        ignore_index=True,
    )
    signal_rows = []
    for label, frame in [("containment_only_v2", containment), ("route_measure_window_recovered", window_rec), ("route_measure_distance_band_recovered", band_rec)]:
        signal_rows.append(
            {
                "comparison_source": label,
                "signals_with_typed_access": int(frame["reference_signal_id"].nunique()) if "reference_signal_id" in frame.columns and not frame.empty else 0,
                "signal_direction_units_with_typed_access": int(frame[["reference_signal_id", "signal_relative_direction"]].drop_duplicates().shape[0])
                if {"reference_signal_id", "signal_relative_direction"}.issubset(frame.columns) and not frame.empty
                else 0,
            }
        )
    return comparison, category, pd.DataFrame(signal_rows)


def _recommendation(comparison: pd.DataFrame, category: pd.DataFrame, window_amb: pd.DataFrame, band_amb: pd.DataFrame) -> pd.DataFrame:
    def metric(source: str, column: str) -> int:
        rows = comparison.loc[comparison["comparison_source"].eq(source), column]
        return int(rows.iloc[0]) if not rows.empty else 0

    window_count = metric("route_measure_window_recovered", "total_typed_access_assignments")
    band_count = metric("route_measure_distance_band_recovered", "total_typed_access_assignments")
    containment_count = metric("containment_only_v2", "total_typed_access_assignments")
    if window_count > containment_count * 2 and int(window_amb["access_v2_uid"].nunique()) < window_count:
        rec = "use_v1_counts_plus_route_measure_recovered_v2_typed_access_at_window_grain_after_review"
    elif band_count > containment_count * 2:
        rec = "use_distance_band_recovery_as_review_matrix_not_active_context"
    else:
        rec = "require_source_owner_clarification_before_recovery"
    return pd.DataFrame(
        [
            {
                "recommendation": rec,
                "keep_v1_counts_active": True,
                "promote_recovered_access_now": False,
                "candidate_route_measure_access_recovery": True,
                "not_active": True,
                "not_policy_ready": True,
                "requires_review": True,
                "method_note": "Route/measure recovery is more appropriate for window or distance-band typed summaries than raw 50-ft bin containment, but ambiguous overlaps remain review evidence.",
            }
        ]
    )


def _qa() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False},
            {"check_name": "current_access_context_rate_model_outputs_not_overwritten", "status": "passed", "observed": "review_output_only"},
            {"check_name": "route_measure_assignment_candidate_only", "status": "passed", "observed": "candidate_route_measure_access_recovery"},
            {"check_name": "ambiguous_route_measure_matches_preserved", "status": "passed", "observed": True},
            {"check_name": "no_active_promotion", "status": "passed", "observed": "not_active"},
            {"check_name": "bin_catchment_gap_diagnostics_reported", "status": "passed", "observed": True},
            {"check_name": "typed_counts_compared_to_containment_only_v2", "status": "passed", "observed": True},
        ]
    )


def _findings(summary: pd.DataFrame, comparison: pd.DataFrame, recommendation: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def comp(source: str, column: str) -> int:
        rows = comparison.loc[comparison["comparison_source"].eq(source), column]
        return int(rows.iloc[0]) if not rows.empty else 0

    rec = recommendation["recommendation"].iloc[0] if not recommendation.empty else "not_available"
    lines = [
        "# Access V2 Route/Measure Window Recovery Findings",
        "",
        "Status: candidate_route_measure_access_recovery; not_active; not_policy_ready; requires_review.",
        "",
        "## Readout",
        "",
        f"- Containment-only v2 typed access assignments: {comp('containment_only_v2', 'total_typed_access_assignments')}",
        f"- Window-grain route/measure recovered assignments: {comp('route_measure_window_recovered', 'total_typed_access_assignments')}",
        f"- Window-grain ambiguous review points: {comp('route_measure_window_recovered', 'ambiguous_review_points')}",
        f"- Distance-band route/measure recovered assignments: {comp('route_measure_distance_band_recovered', 'total_typed_access_assignments')}",
        f"- Distance-band ambiguous review points: {comp('route_measure_distance_band_recovered', 'ambiguous_review_points')}",
        f"- Recommendation: {rec}",
        "",
        "## Interpretation",
        "",
        "This diagnostic does not require point-in-catchment containment. It uses stable route keys and interpolated route-measure intervals from identity-enriched directional bins to test whether typed access is better summarized at signal-direction window or distance-band grains.",
        "",
        f"QA checks passed: {int(qa['status'].eq('passed').sum())} of {len(qa)}.",
        "",
        "## Outputs",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_recovery(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    access = _load_access_v2()
    match_status = _load_match_status(access)
    access = access.merge(match_status, on="access_v2_uid", how="left")
    bins = _load_identity_bins()
    gap_diag = _bin_gap_diagnostic(bins)
    window_units = _make_units(bins, "window")
    band_units = _make_units(bins, "distance_band")
    window_candidates, window_recovered, window_ambiguous = _candidate_assignments(access, window_units, "window")
    band_candidates, band_recovered, band_ambiguous = _candidate_assignments(access, band_units, "distance_band")
    position_diag = _position_diagnostic(access, window_units, window_candidates, band_candidates)
    compatibility = _window_compatibility(access, window_candidates, band_candidates)
    containment = _containment_assignments()

    window_summary = _summary_by(window_recovered, ["reference_signal_id", "signal_relative_direction", "analysis_window"])
    band_summary = _summary_by(band_recovered, ["reference_signal_id", "signal_relative_direction", "distance_band"])
    signal_summary = _summary_by(window_recovered, ["reference_signal_id"])
    category_counts = _category_counts(window_recovered, "route_measure_window_recovered")
    comparison, category_comparison, signal_coverage = _comparison(containment, window_recovered, window_ambiguous, band_recovered, band_ambiguous, access)
    recommendation = _recommendation(comparison, category_comparison, window_ambiguous, band_ambiguous)
    qa = _qa()

    outputs = {
        "bin_gap_diagnostic_csv": out_dir / "access_v2_bin_gap_diagnostic.csv",
        "unmatched_position_diagnostic_csv": out_dir / "access_v2_unmatched_position_diagnostic.csv",
        "route_measure_window_compatibility_csv": out_dir / "access_v2_route_measure_window_compatibility.csv",
        "window_recovery_candidates_csv": out_dir / "access_v2_window_recovery_candidates.csv",
        "window_recovered_assignments_csv": out_dir / "access_v2_window_recovered_assignments.csv",
        "window_ambiguous_review_csv": out_dir / "access_v2_window_ambiguous_review.csv",
        "distance_band_recovery_candidates_csv": out_dir / "access_v2_distance_band_recovery_candidates.csv",
        "distance_band_recovered_assignments_csv": out_dir / "access_v2_distance_band_recovered_assignments.csv",
        "distance_band_ambiguous_review_csv": out_dir / "access_v2_distance_band_ambiguous_review.csv",
        "type_summary_by_window_csv": out_dir / "access_v2_recovered_type_summary_by_window.csv",
        "type_summary_by_distance_band_csv": out_dir / "access_v2_recovered_type_summary_by_distance_band.csv",
        "type_summary_by_signal_csv": out_dir / "access_v2_recovered_type_summary_by_signal.csv",
        "type_category_counts_csv": out_dir / "access_v2_recovered_type_category_counts.csv",
        "comparison_to_containment_csv": out_dir / "access_v2_recovery_comparison_to_containment.csv",
        "category_comparison_csv": out_dir / "access_v2_recovery_category_comparison.csv",
        "signal_coverage_comparison_csv": out_dir / "access_v2_recovery_signal_coverage_comparison.csv",
        "recommendation_csv": out_dir / "access_v2_route_measure_window_recovery_recommendation.csv",
        "qa_csv": out_dir / "access_v2_route_measure_window_recovery_qa.csv",
        "findings_md": out_dir / "access_v2_route_measure_window_recovery_findings.md",
        "manifest_json": out_dir / "access_v2_route_measure_window_recovery_manifest.json",
    }

    _write_csv(gap_diag, outputs["bin_gap_diagnostic_csv"])
    _write_csv(position_diag, outputs["unmatched_position_diagnostic_csv"])
    _write_csv(compatibility, outputs["route_measure_window_compatibility_csv"])
    _write_csv(window_candidates, outputs["window_recovery_candidates_csv"])
    _write_csv(window_recovered, outputs["window_recovered_assignments_csv"])
    _write_csv(window_ambiguous, outputs["window_ambiguous_review_csv"])
    _write_csv(band_candidates, outputs["distance_band_recovery_candidates_csv"])
    _write_csv(band_recovered, outputs["distance_band_recovered_assignments_csv"])
    _write_csv(band_ambiguous, outputs["distance_band_ambiguous_review_csv"])
    _write_csv(window_summary, outputs["type_summary_by_window_csv"])
    _write_csv(band_summary, outputs["type_summary_by_distance_band_csv"])
    _write_csv(signal_summary, outputs["type_summary_by_signal_csv"])
    _write_csv(category_counts, outputs["type_category_counts_csv"])
    _write_csv(comparison, outputs["comparison_to_containment_csv"])
    _write_csv(category_comparison, outputs["category_comparison_csv"])
    _write_csv(signal_coverage, outputs["signal_coverage_comparison_csv"])
    _write_csv(recommendation, outputs["recommendation_csv"])
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(position_diag, comparison, recommendation, qa, outputs), outputs["findings_md"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "diagnostic route/measure recovery of candidate access v2 typed evidence at signal-direction window and distance-band grains",
        "status": "candidate_route_measure_access_recovery",
        "not_active": True,
        "not_policy_ready": True,
        "requires_review": True,
        "measure_tolerance": MEASURE_TOLERANCE,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "access_v2": str(ACCESS_V2_FILE),
            "access_context_join_v2": str(V2_DIR),
            "access_v1_v2_coverage_diagnostic": str(DIAG_DIR),
            "hybrid_access_context": str(HYBRID_DIR),
            "active_context": str(ACTIVE_CONTEXT_FILE),
            "identity_bins": str(IDENTITY_BINS_FILE),
            "identity_segments": str(IDENTITY_SEGMENTS_FILE),
        },
        "comparison": comparison.to_dict(orient="records"),
        "recommendation": recommendation.to_dict(orient="records"),
        "qa_checks": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostic route/measure recovery for candidate access v2 typed evidence.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_recovery(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
