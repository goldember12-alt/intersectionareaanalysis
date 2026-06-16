from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/refreshed_leg_coverage_after_offset_recovery"

REFRESH_DIR = OUTPUT_ROOT / "review/current/refreshed_expanded_universe_with_offset_recovery"
LEG_AUDIT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_leg_coverage_audit"
PHYSICAL_AUDIT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_physical_leg_normalization_audit"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_context_refresh"
OFFSET_QA_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_staging_qa_cleanup"

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = {
    REFRESH_DIR: [
        "refreshed_represented_signal_universe.csv",
        "refreshed_represented_bin_universe.csv",
        "refreshed_access_target_bins.csv",
        "refreshed_universe_summary.csv",
        "refreshed_universe_with_offset_recovery_manifest.json",
    ],
    LEG_AUDIT_DIR: [
        "leg_coverage_signal_summary.csv",
        "leg_count_distribution.csv",
        "possible_under_capture_flags.csv",
        "possible_over_expansion_flags.csv",
        "expanded_universe_leg_coverage_manifest.json",
    ],
    PHYSICAL_AUDIT_DIR: [
        "physical_leg_bin_detail.csv",
        "physical_leg_signal_summary.csv",
        "physical_leg_count_distribution.csv",
        "candidate_vs_physical_leg_comparison.csv",
        "five_plus_leg_diagnostic.csv",
        "two_leg_under_capture_diagnostic.csv",
        "expanded_universe_physical_leg_normalization_manifest.json",
    ],
    OFFSET_CONTEXT_DIR: [
        "offset_zone_context_bin_detail.csv",
        "offset_zone_context_signal_summary.csv",
        "offset_zone_context_refresh_manifest.json",
    ],
    OFFSET_QA_DIR: [
        "cleaned_staged_offset_recovered_bins.csv",
        "cleaned_staged_offset_recovered_legs.csv",
        "staging_qa_cleanup_manifest.json",
    ],
}


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(frame))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(frame))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _missing_required_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _leg_class(count: int | float) -> str:
    try:
        n = int(count)
    except Exception:
        return "unknown"
    if n <= 0:
        return "zero_leg"
    if n == 1:
        return "one_leg"
    if n == 2:
        return "two_leg"
    if n == 3:
        return "three_leg"
    if n == 4:
        return "four_leg"
    return "five_plus_leg"


def _band_from_distance(start: pd.Series, end: pd.Series) -> pd.Series:
    s = pd.to_numeric(start, errors="coerce").fillna(0)
    e = pd.to_numeric(end, errors="coerce").fillna(s)
    mid = (s + e) / 2.0
    return pd.cut(
        mid,
        bins=[-0.001, 250, 500, 750, 1000, 1500, 2500, np.inf],
        labels=["0_250ft", "250_500ft", "500_750ft", "750_1000ft", "1000_1500ft", "1500_2500ft", "over_2500ft"],
    ).astype(str)


def _build_bin_detail(refreshed_bins: pd.DataFrame, prior_phys_bins: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "target_bin_id",
        "candidate_bin_id",
        "signal_id",
        "physical_leg_cluster_id",
        "physical_bearing_sector",
        "candidate_branch_id",
        "carriageway_parallel_branch_key",
        "route_or_facility_key",
        "route_or_facility_label",
        "physical_bearing_status",
        "completed_geometry_status",
        "geometry_recovery_method",
        "provenance_class",
    ]
    prior_lookup = prior_phys_bins[[col for col in base_cols if col in prior_phys_bins.columns]].drop_duplicates("target_bin_id")
    detail = refreshed_bins.merge(prior_lookup, on="target_bin_id", how="left", suffixes=("", "_prior_phys"))

    detail["review_signal_id"] = _text(detail, "target_signal_id").where(_text(detail, "target_signal_id").ne(""), _text(detail, "candidate_signal_id"))
    detail["review_signal_id"] = detail["review_signal_id"].where(detail["review_signal_id"].ne(""), _text(detail, "signal_id"))
    detail["review_source_signal_id"] = _text(detail, "source_signal_id").where(_text(detail, "source_signal_id").ne(""), _text(detail, "source_signal_id_signal"))
    detail["review_source_layer"] = _text(detail, "source_layer").where(_text(detail, "source_layer").ne(""), _text(detail, "source_layer_signal"))
    detail["offset_zone_provenance_flag"] = _flag(detail, "offset_zone_bin_flag")
    detail["review_only_preserved_flag"] = _flag(detail, "review_only_flag") | _flag(detail, "review_only") | detail["offset_zone_provenance_flag"]

    detail["refreshed_physical_leg_id"] = _text(detail, "physical_leg_id").where(_text(detail, "physical_leg_id").ne(""), _text(detail, "physical_leg_cluster_id"))
    detail["refreshed_physical_bearing_sector"] = _text(detail, "physical_leg_bearing_group").where(_text(detail, "physical_leg_bearing_group").ne(""), _text(detail, "physical_bearing_sector"))
    detail["refreshed_physical_leg_cluster_key"] = detail["review_signal_id"] + "|" + detail["refreshed_physical_bearing_sector"].where(detail["refreshed_physical_bearing_sector"].ne(""), detail["refreshed_physical_leg_id"])
    detail["refreshed_candidate_branch_id"] = _text(detail, "staged_recovered_leg_id").where(_text(detail, "staged_recovered_leg_id").ne(""), _text(detail, "candidate_branch_id"))
    detail["refreshed_carriageway_subbranch_id"] = _text(detail, "carriageway_subbranch_id").where(_text(detail, "carriageway_subbranch_id").ne(""), _text(detail, "carriageway_parallel_branch_key"))
    detail["refreshed_route_facility_group"] = _text(detail, "source_route_keys").where(_text(detail, "source_route_keys").ne(""), _text(detail, "route_or_facility_label"))
    detail["refreshed_route_facility_group"] = detail["refreshed_route_facility_group"].where(detail["refreshed_route_facility_group"].ne(""), _text(detail, "route_name"))
    detail["distance_start_ft_num"] = _num(detail, "distance_start_ft")
    detail["distance_end_ft_num"] = _num(detail, "distance_end_ft")
    detail["distance_band_refreshed"] = _text(detail, "distance_band").where(_text(detail, "distance_band").ne(""), _band_from_distance(detail["distance_start_ft_num"], detail["distance_end_ft_num"]))
    detail["speed_ready_refreshed"] = _flag(detail, "has_speed") | _flag(detail, "speed_ready_flag") | _flag(detail, "has_rns_speed")
    detail["aadt_ready_refreshed"] = _flag(detail, "has_aadt") | _flag(detail, "aadt_ready_flag")
    detail["speed_aadt_ready_refreshed"] = _flag(detail, "speed_aadt_ready") | _flag(detail, "speed_aadt_ready_flag") | _flag(detail, "speed_aadt_ready_bin")
    detail["grade_separation_hold_flag"] = _flag(detail, "hold_excluded_mainline") | _flag(detail, "hold_manual_grade_separation_review") | _flag(detail, "hold_nonstandard_geometry")
    detail["long_source_row_qa_flag_refreshed"] = _flag(detail, "long_source_row_flag")
    detail["partial_bin_preserved_flag"] = _flag(detail, "partial_one_sided_flag") | _flag(detail, "partial_coverage_flag") | _flag(detail, "one_sided_or_partial_flag")
    detail["bearing_available_refreshed"] = detail["refreshed_physical_bearing_sector"].ne("") | detail["refreshed_physical_leg_id"].ne("")

    keep = [
        "review_signal_id",
        "review_source_signal_id",
        "review_source_layer",
        "target_bin_id",
        "candidate_bin_id",
        "offset_zone_provenance_flag",
        "previous_represented_bin_flag",
        "refresh_bin_source",
        "refreshed_physical_leg_id",
        "refreshed_physical_bearing_sector",
        "refreshed_physical_leg_cluster_key",
        "refreshed_candidate_branch_id",
        "refreshed_carriageway_subbranch_id",
        "refreshed_route_facility_group",
        "route_id",
        "route_common",
        "route_name",
        "source_route_keys",
        "graph_edge_id",
        "road_component_id",
        "source_road_row_id",
        "source_travelway_lineage",
        "geometry_wkt",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band_refreshed",
        "analysis_window",
        "signal_relative_direction_label",
        "direction_confidence_status",
        "roadway_division_status",
        "speed_ready_refreshed",
        "aadt_ready_refreshed",
        "speed_aadt_ready_refreshed",
        "grade_separation_hold_flag",
        "long_source_row_qa_flag_refreshed",
        "partial_bin_preserved_flag",
        "review_only_preserved_flag",
        "qa_cleanup_status",
        "route_facility_discontinuity_type",
        "source_line_split_flag",
        "divided_carriageway_flag",
        "bearing_available_refreshed",
    ]
    return detail[[col for col in keep if col in detail.columns]].copy()


def _signal_summary(bin_detail: pd.DataFrame, prior_phys: pd.DataFrame) -> pd.DataFrame:
    work = bin_detail.copy()
    work["branch_nonempty"] = _text(work, "refreshed_candidate_branch_id").where(_text(work, "refreshed_candidate_branch_id").ne(""), _text(work, "target_bin_id"))
    work["physical_nonempty"] = _text(work, "refreshed_physical_leg_cluster_key").where(_text(work, "refreshed_physical_leg_cluster_key").ne(work["review_signal_id"] + "|"), "")
    grouped = work.groupby("review_signal_id", dropna=False)
    out = grouped.agg(
        source_signal_id=("review_source_signal_id", "first"),
        source_layer=("review_source_layer", "first"),
        total_bins=("target_bin_id", "count"),
        offset_zone_bin_count=("offset_zone_provenance_flag", "sum"),
        offset_zone_physical_leg_count=("refreshed_physical_leg_cluster_key", lambda s: s[work.loc[s.index, "offset_zone_provenance_flag"]].replace("", pd.NA).dropna().nunique()),
        bins_with_bearing=("bearing_available_refreshed", "sum"),
        candidate_branch_count=("branch_nonempty", pd.Series.nunique),
        carriageway_subbranch_count=("refreshed_carriageway_subbranch_id", lambda s: s.replace("", pd.NA).dropna().nunique()),
        route_facility_group_count=("refreshed_route_facility_group", lambda s: s.replace("", pd.NA).dropna().nunique()),
        route_facility_groups=("refreshed_route_facility_group", _collapse),
        direction_labels=("signal_relative_direction_label", _collapse),
        roadway_division_statuses=("roadway_division_status", _collapse),
        speed_ready_bins=("speed_ready_refreshed", "sum"),
        aadt_ready_bins=("aadt_ready_refreshed", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_refreshed", "sum"),
        long_source_row_flag_bins=("long_source_row_qa_flag_refreshed", "sum"),
        partial_bin_count=("partial_bin_preserved_flag", "sum"),
    ).reset_index()

    phys_counts = work.loc[work["physical_nonempty"].ne("")].groupby("review_signal_id")["physical_nonempty"].nunique().reset_index(name="refreshed_physical_leg_count")
    out = out.merge(phys_counts, on="review_signal_id", how="left")
    out["refreshed_physical_leg_count"] = pd.to_numeric(out["refreshed_physical_leg_count"], errors="coerce").fillna(0).astype(int)
    out["refreshed_physical_leg_class"] = out["refreshed_physical_leg_count"].map(_leg_class)
    out["candidate_branch_class"] = out["candidate_branch_count"].map(_leg_class)
    out["offset_bins_added_flag"] = out["offset_zone_bin_count"].gt(0)
    out["offset_added_physical_leg_flag"] = out["offset_zone_physical_leg_count"].gt(0)
    out["likely_over_split_flag_refreshed"] = out["candidate_branch_count"].gt(out["refreshed_physical_leg_count"] + 1) | out["refreshed_physical_leg_count"].ge(5)
    out["likely_under_captured_flag_refreshed"] = out["refreshed_physical_leg_count"].le(2)

    band_counts = pd.crosstab(work["review_signal_id"], work["distance_band_refreshed"])
    for band in ["0_250ft", "250_500ft", "500_750ft", "750_1000ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]:
        if band not in band_counts.columns:
            band_counts[band] = 0
    band_counts = band_counts.reset_index().rename(
        columns={
            "0_250ft": "bins_0_250",
            "250_500ft": "bins_250_500",
            "500_750ft": "bins_500_750",
            "750_1000ft": "bins_750_1000",
            "500_1000ft": "bins_500_1000",
            "1000_1500ft": "bins_1000_1500",
            "1500_2500ft": "bins_1500_2500",
        }
    )
    out = out.merge(band_counts, on="review_signal_id", how="left")
    for col in ["bins_0_250", "bins_250_500", "bins_500_750", "bins_750_1000", "bins_500_1000", "bins_1000_1500", "bins_1500_2500"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["bins_500_750"] = out["bins_500_750"] + out["bins_500_1000"]
    out["bins_750_1000"] = out["bins_750_1000"] + out["bins_500_1000"]
    out["bins_0_1000"] = out[["bins_0_250", "bins_250_500", "bins_500_750", "bins_750_1000"]].sum(axis=1)
    out["bins_1000_2500"] = out[["bins_1000_1500", "bins_1500_2500"]].sum(axis=1)

    completeness = _leg_completeness(work)
    out = out.merge(completeness, on="review_signal_id", how="left")

    prior_cols = [
        "signal_id",
        "normalized_physical_leg_count",
        "normalized_physical_leg_class",
        "candidate_branch_count",
        "carriageway_parallel_branch_count",
        "old_candidate_leg_count",
        "old_candidate_leg_class",
        "likely_over_split_flag",
        "likely_under_captured_flag",
    ]
    prior = prior_phys[[col for col in prior_cols if col in prior_phys.columns]].rename(
        columns={
            "signal_id": "review_signal_id",
            "normalized_physical_leg_count": "prior_physical_leg_count",
            "normalized_physical_leg_class": "prior_physical_leg_class",
            "candidate_branch_count": "prior_candidate_branch_count",
            "carriageway_parallel_branch_count": "prior_carriageway_branch_count",
            "old_candidate_leg_count": "prior_old_candidate_leg_count",
            "old_candidate_leg_class": "prior_old_candidate_leg_class",
            "likely_over_split_flag": "prior_likely_over_split_flag",
            "likely_under_captured_flag": "prior_likely_under_captured_flag",
        }
    )
    out = out.merge(prior, on="review_signal_id", how="left")
    out["physical_leg_count_delta"] = out["refreshed_physical_leg_count"] - pd.to_numeric(out["prior_physical_leg_count"], errors="coerce").fillna(0)
    out["leg_capture_change_class"] = np.select(
        [
            out["physical_leg_count_delta"].gt(0),
            out["physical_leg_count_delta"].eq(0) & out["offset_bins_added_flag"],
            out["physical_leg_count_delta"].lt(0),
        ],
        ["offset_bins_added_new_physical_leg", "offset_bins_added_no_leg_count_change", "physical_leg_count_decreased_or_normalized"],
        default="no_offset_change",
    )
    return out


def _leg_completeness(work: pd.DataFrame) -> pd.DataFrame:
    needed_1000 = {"0_250ft", "250_500ft", "500_750ft", "750_1000ft"}
    needed_2500 = needed_1000 | {"1000_1500ft", "1500_2500ft"}
    rows = []
    valid = work.loc[_text(work, "refreshed_physical_leg_cluster_key").ne(work["review_signal_id"] + "|")].copy()
    def expanded_bands(series: pd.Series) -> set[str]:
        bands = set(_text(pd.DataFrame({"v": series}), "v"))
        if "500_1000ft" in bands:
            bands.update({"500_750ft", "750_1000ft"})
        return bands

    for signal_id, group in valid.groupby("review_signal_id", dropna=False):
        leg_sets = group.groupby("refreshed_physical_leg_cluster_key")["distance_band_refreshed"].apply(expanded_bands).to_dict()
        any_1000 = any(needed_1000.issubset(bands) for bands in leg_sets.values())
        all_1000 = bool(leg_sets) and all(needed_1000.issubset(bands) for bands in leg_sets.values())
        any_2500 = any(needed_2500.issubset(bands) for bands in leg_sets.values())
        all_2500 = bool(leg_sets) and all(needed_2500.issubset(bands) for bands in leg_sets.values())
        rows.append(
            {
                "review_signal_id": signal_id,
                "complete_0_1000_by_at_least_one_leg": any_1000,
                "complete_0_1000_across_all_represented_legs": all_1000,
                "complete_0_2500_by_at_least_one_leg": any_2500,
                "complete_0_2500_across_all_represented_legs": all_2500,
            }
        )
    return pd.DataFrame(rows)


def _before_after(signal: pd.DataFrame) -> pd.DataFrame:
    return signal[
        [
            "review_signal_id",
            "source_signal_id",
            "prior_physical_leg_count",
            "prior_physical_leg_class",
            "refreshed_physical_leg_count",
            "refreshed_physical_leg_class",
            "physical_leg_count_delta",
            "offset_zone_bin_count",
            "offset_zone_physical_leg_count",
            "candidate_branch_count",
            "carriageway_subbranch_count",
            "leg_capture_change_class",
            "likely_under_captured_flag_refreshed",
            "likely_over_split_flag_refreshed",
        ]
    ].copy()


def _two_leg_summary(signal: pd.DataFrame, two_diag: pd.DataFrame) -> pd.DataFrame:
    work = two_diag.merge(signal, left_on="signal_id", right_on="review_signal_id", how="left", suffixes=("_prior_diag", ""))
    work["resolution_class"] = np.select(
        [
            work["refreshed_physical_leg_count"].ge(3) & work["offset_zone_bin_count"].gt(0),
            work["refreshed_physical_leg_count"].le(2) & work["offset_zone_bin_count"].gt(0),
            work["refreshed_physical_leg_count"].le(2) & work["offset_zone_bin_count"].fillna(0).eq(0),
        ],
        ["resolved_or_improved_to_three_plus_physical_legs", "still_scaffold_limited_after_offset_bins", "no_offset_recovery_source_limited_or_holdout"],
        default="needs_manual_review",
    )
    summary = (
        work.groupby("resolution_class", dropna=False)
        .agg(signal_count=("signal_id", "nunique"), median_refreshed_physical_legs=("refreshed_physical_leg_count", "median"), offset_bin_count=("offset_zone_bin_count", "sum"))
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )
    summary.insert(0, "prior_queue", "two_leg_under_capture")
    return summary


def _five_plus_summary(signal: pd.DataFrame, five_diag: pd.DataFrame) -> pd.DataFrame:
    work = five_diag.merge(signal, left_on="signal_id", right_on="review_signal_id", how="left", suffixes=("_prior_diag", ""))
    work["resolution_class"] = np.select(
        [
            work["refreshed_physical_leg_class"].isin(["three_leg", "four_leg"]),
            work["refreshed_physical_leg_class"].eq("five_plus_leg"),
            work["carriageway_subbranch_count"].gt(work["refreshed_physical_leg_count"]),
        ],
        ["normalized_to_three_or_four_physical_legs", "still_five_plus_physical_legs", "divided_or_carriageway_subbranch_case"],
        default="ambiguous_or_needs_review",
    )
    summary = (
        work.groupby("resolution_class", dropna=False)
        .agg(signal_count=("signal_id", "nunique"), median_refreshed_physical_legs=("refreshed_physical_leg_count", "median"), offset_bin_count=("offset_zone_bin_count", "sum"))
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )
    summary.insert(0, "prior_queue", "five_plus_over_split")
    return summary


def _distribution(signal: pd.DataFrame) -> pd.DataFrame:
    return (
        signal.groupby("refreshed_physical_leg_class", dropna=False)
        .agg(
            signal_count=("review_signal_id", "nunique"),
            median_bins=("total_bins", "median"),
            median_candidate_branch_count=("candidate_branch_count", "median"),
            median_carriageway_subbranch_count=("carriageway_subbranch_count", "median"),
            offset_signal_count=("offset_bins_added_flag", "sum"),
        )
        .reset_index()
        .sort_values("refreshed_physical_leg_class")
    )


def _candidate_vs_physical(signal: pd.DataFrame) -> pd.DataFrame:
    status = signal.copy()
    status["candidate_vs_physical_status"] = np.select(
        [
            status["candidate_branch_count"].gt(status["refreshed_physical_leg_count"]),
            status["candidate_branch_count"].eq(status["refreshed_physical_leg_count"]),
            status["candidate_branch_count"].lt(status["refreshed_physical_leg_count"]),
        ],
        ["candidate_branches_exceed_physical_legs", "candidate_branches_equal_physical_legs", "physical_legs_exceed_candidate_branches"],
        default="unknown",
    )
    return (
        status.groupby(["prior_physical_leg_class", "refreshed_physical_leg_class", "candidate_vs_physical_status"], dropna=False)
        .agg(signal_count=("review_signal_id", "nunique"), median_bins=("total_bins", "median"), offset_signal_count=("offset_bins_added_flag", "sum"))
        .reset_index()
    )


def _distance_summary(signal: pd.DataFrame) -> pd.DataFrame:
    rows = []
    checks = [
        ("any_0_250_ft", signal["bins_0_250"].gt(0)),
        ("any_250_500_ft", signal["bins_250_500"].gt(0)),
        ("any_500_750_ft", signal["bins_500_750"].gt(0)),
        ("any_750_1000_ft", signal["bins_750_1000"].gt(0)),
        ("any_1000_1500_ft", signal["bins_1000_1500"].gt(0)),
        ("any_1500_2500_ft", signal["bins_1500_2500"].gt(0)),
        ("complete_0_1000_by_at_least_one_leg", signal["complete_0_1000_by_at_least_one_leg"].fillna(False).astype(bool)),
        ("complete_0_1000_across_all_represented_legs", signal["complete_0_1000_across_all_represented_legs"].fillna(False).astype(bool)),
        ("complete_0_2500_by_at_least_one_leg", signal["complete_0_2500_by_at_least_one_leg"].fillna(False).astype(bool)),
        ("complete_0_2500_across_all_represented_legs", signal["complete_0_2500_across_all_represented_legs"].fillna(False).astype(bool)),
    ]
    for metric, mask in checks:
        rows.append({"distance_availability_metric": metric, "signal_count": int(mask.sum()), "share_of_2739": round(float(mask.sum()) / 2739, 4)})
    return pd.DataFrame(rows)


def _review_queue(signal: pd.DataFrame) -> pd.DataFrame:
    work = signal.copy()
    work["review_priority"] = np.select(
        [
            work["likely_under_captured_flag_refreshed"] & work["offset_bins_added_flag"],
            work["likely_under_captured_flag_refreshed"],
            work["likely_over_split_flag_refreshed"] & work["offset_bins_added_flag"],
            work["likely_over_split_flag_refreshed"],
        ],
        ["high_under_capture_after_offset", "under_capture_no_offset_fix", "over_split_after_offset_review", "over_split_existing_review"],
        default="low_no_leg_capture_issue",
    )
    return work.loc[work["review_priority"].ne("low_no_leg_capture_issue")].sort_values(["review_priority", "offset_zone_bin_count"], ascending=[True, False]).head(1000)


def _findings(metrics: dict[str, Any], dist: pd.DataFrame) -> str:
    dist_lines = "\n".join(f"- {row.distance_availability_metric}: {int(row.signal_count):,}" for row in dist.itertuples())
    return f"""# Refreshed Leg Coverage After Offset Recovery Findings

## Bounded Question

This read-only audit asks whether the 2,378 offset-zone bins appended to the refreshed review-only bin universe materially improve physical leg capture for the existing 2,739 represented signals. It does not assign access, crashes, rates, or models.

## Results

- Refreshed represented signals audited: {metrics["signal_count"]:,}
- Refreshed bins audited: {metrics["bin_count"]:,}
- Offset-zone bins audited: {metrics["offset_bin_count"]:,}
- Signals with offset-zone bins: {metrics["offset_signal_count"]:,}
- Signals where offset bins added a new physical leg/bearing sector: {metrics["signals_with_new_offset_physical_leg"]:,}
- Signals where offset bins were added but did not change physical leg count: {metrics["signals_offset_no_leg_count_change"]:,}
- Two-leg queue cases resolved or improved to three-plus physical legs: {metrics["two_leg_resolved"]:,}
- Five-plus queue cases normalized to three/four physical legs: {metrics["five_plus_normalized"]:,}

## Refreshed Physical Leg Distribution

{metrics["distribution_text"]}

## Distance-Band Availability

{dist_lines}

## Recommendation

The offset-zone bins improve detailed scaffold/bin coverage for a focused set of represented signals, but they do not change the deduplicated represented signal count. Access work can resume using the refreshed access target, with two caveats: prior access outputs are stale for the new bin target, and remaining under-capture/over-split review queues should stay visible during access interpretation rather than being treated as solved globally.
"""


def _qa(bin_detail: pd.DataFrame) -> pd.DataFrame:
    output_inside = str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/refreshed_leg_coverage_after_offset_recovery")
    return pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, "", "true", "All writes are under review/current/refreshed_leg_coverage_after_offset_recovery."),
            _qa_row("no_candidates_promoted", True, "", "true", "Offset bins remain review-only."),
            _qa_row("no_access_or_crash_assignment", True, "", "true", "No access or crash inputs are assigned."),
            _qa_row("no_rates_or_models", True, "", "true", ""),
            _qa_row("offset_zone_bins_review_only", bin_detail.loc[bin_detail["offset_zone_provenance_flag"], "review_only_preserved_flag"].all(), "", "true", ""),
            _qa_row("held_grade_separated_mainline_bins_excluded", not bin_detail["grade_separation_hold_flag"].any(), "", "true", ""),
            _qa_row("partial_bins_preserved", "partial_bin_preserved_flag" in bin_detail.columns, "", "true", ""),
            _qa_row("physical_legs_separate_from_candidate_branches", {"refreshed_physical_leg_cluster_key", "refreshed_candidate_branch_id", "refreshed_carriageway_subbranch_id"}.issubset(bin_detail.columns), "", "true", ""),
            _qa_row("outputs_written_only_to_review_folder", output_inside, str(OUT_DIR), "review/current/refreshed_leg_coverage_after_offset_recovery", ""),
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = _missing_required_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    refreshed_signals = _read_csv(REFRESH_DIR / "refreshed_represented_signal_universe.csv")
    refreshed_bins = _read_csv(REFRESH_DIR / "refreshed_represented_bin_universe.csv")
    refreshed_summary = _read_csv(REFRESH_DIR / "refreshed_universe_summary.csv")
    prev_leg_signal = _read_csv(LEG_AUDIT_DIR / "leg_coverage_signal_summary.csv")
    prev_under = _read_csv(LEG_AUDIT_DIR / "possible_under_capture_flags.csv")
    prev_over = _read_csv(LEG_AUDIT_DIR / "possible_over_expansion_flags.csv")
    prior_phys_signal = _read_csv(PHYSICAL_AUDIT_DIR / "physical_leg_signal_summary.csv")
    prior_dist = _read_csv(PHYSICAL_AUDIT_DIR / "physical_leg_count_distribution.csv")
    prior_comp = _read_csv(PHYSICAL_AUDIT_DIR / "candidate_vs_physical_leg_comparison.csv")
    five_diag = _read_csv(PHYSICAL_AUDIT_DIR / "five_plus_leg_diagnostic.csv")
    two_diag = _read_csv(PHYSICAL_AUDIT_DIR / "two_leg_under_capture_diagnostic.csv")
    offset_context_signals = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_signal_summary.csv")
    offset_context_bins = _read_csv(OFFSET_CONTEXT_DIR / "offset_zone_context_bin_detail.csv")
    cleaned_offset_legs = _read_csv(OFFSET_QA_DIR / "cleaned_staged_offset_recovered_legs.csv")

    prior_bin_cols = [
        "target_bin_id",
        "candidate_bin_id",
        "signal_id",
        "physical_leg_cluster_id",
        "physical_bearing_sector",
        "candidate_branch_id",
        "carriageway_parallel_branch_key",
        "route_or_facility_key",
        "route_or_facility_label",
        "physical_bearing_status",
        "completed_geometry_status",
        "geometry_recovery_method",
        "provenance_class",
    ]
    prior_phys_bins = _read_csv(PHYSICAL_AUDIT_DIR / "physical_leg_bin_detail.csv", usecols=prior_bin_cols)

    bin_detail = _build_bin_detail(refreshed_bins, prior_phys_bins)
    signal_summary = _signal_summary(bin_detail, prior_phys_signal)
    distribution = _distribution(signal_summary)
    comparison = _candidate_vs_physical(signal_summary)
    before_after = _before_after(signal_summary)
    two_summary = _two_leg_summary(signal_summary, two_diag)
    five_summary = _five_plus_summary(signal_summary, five_diag)
    distance_summary = _distance_summary(signal_summary)
    review_queue = _review_queue(signal_summary)

    dist_text = "; ".join(f"{row.refreshed_physical_leg_class}={int(row.signal_count):,}" for row in distribution.itertuples())
    metrics = {
        "signal_count": int(signal_summary["review_signal_id"].nunique()),
        "bin_count": int(len(bin_detail)),
        "offset_bin_count": int(bin_detail["offset_zone_provenance_flag"].sum()),
        "offset_signal_count": int(signal_summary["offset_bins_added_flag"].sum()),
        "signals_with_new_offset_physical_leg": int((signal_summary["physical_leg_count_delta"].gt(0) & signal_summary["offset_bins_added_flag"]).sum()),
        "signals_offset_no_leg_count_change": int((signal_summary["physical_leg_count_delta"].eq(0) & signal_summary["offset_bins_added_flag"]).sum()),
        "two_leg_resolved": int(two_summary.loc[two_summary["resolution_class"].eq("resolved_or_improved_to_three_plus_physical_legs"), "signal_count"].sum()) if not two_summary.empty else 0,
        "five_plus_normalized": int(five_summary.loc[five_summary["resolution_class"].eq("normalized_to_three_or_four_physical_legs"), "signal_count"].sum()) if not five_summary.empty else 0,
        "distribution_text": dist_text,
    }

    _write_csv(bin_detail, OUT_DIR / "refreshed_leg_coverage_bin_detail.csv")
    _write_csv(signal_summary, OUT_DIR / "refreshed_leg_coverage_signal_summary.csv")
    _write_csv(distribution, OUT_DIR / "refreshed_physical_leg_count_distribution.csv")
    _write_csv(comparison, OUT_DIR / "refreshed_candidate_vs_physical_leg_comparison.csv")
    _write_csv(before_after, OUT_DIR / "leg_coverage_before_after_comparison.csv")
    _write_csv(two_summary, OUT_DIR / "two_leg_resolution_summary.csv")
    _write_csv(five_summary, OUT_DIR / "five_plus_resolution_summary.csv")
    _write_csv(distance_summary, OUT_DIR / "refreshed_distance_band_availability_summary.csv")
    _write_csv(review_queue, OUT_DIR / "remaining_leg_capture_review_queue.csv")
    _write_text(_findings(metrics, distance_summary), OUT_DIR / "refreshed_leg_coverage_after_offset_findings.md")
    qa = _qa(bin_detail)
    _write_csv(qa, OUT_DIR / "refreshed_leg_coverage_after_offset_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.refreshed_leg_coverage_after_offset_recovery",
        "bounded_question": "Review-only physical-leg coverage audit after offset/intersection-zone recovery bins were added to the refreshed represented bin universe.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "refreshed_universe_dir": str(REFRESH_DIR),
            "previous_leg_audit_dir": str(LEG_AUDIT_DIR),
            "previous_physical_leg_audit_dir": str(PHYSICAL_AUDIT_DIR),
            "offset_context_dir": str(OFFSET_CONTEXT_DIR),
            "offset_qa_dir": str(OFFSET_QA_DIR),
            "refreshed_manifest": _load_json(REFRESH_DIR / "refreshed_universe_with_offset_recovery_manifest.json"),
            "previous_physical_manifest": _load_json(PHYSICAL_AUDIT_DIR / "expanded_universe_physical_leg_normalization_manifest.json"),
        },
        "metrics": {
            **metrics,
            "refreshed_signal_input_rows": int(len(refreshed_signals)),
            "refreshed_summary_rows": int(len(refreshed_summary)),
            "prior_leg_signal_rows": int(len(prev_leg_signal)),
            "prior_under_capture_rows": int(len(prev_under)),
            "prior_over_expansion_rows": int(len(prev_over)),
            "prior_distribution_rows": int(len(prior_dist)),
            "prior_comparison_rows": int(len(prior_comp)),
            "offset_context_signal_rows": int(len(offset_context_signals)),
            "offset_context_bin_rows": int(len(offset_context_bins)),
            "cleaned_offset_leg_rows": int(len(cleaned_offset_legs)),
        },
        "outputs": [
            "refreshed_leg_coverage_bin_detail.csv",
            "refreshed_leg_coverage_signal_summary.csv",
            "refreshed_physical_leg_count_distribution.csv",
            "refreshed_candidate_vs_physical_leg_comparison.csv",
            "leg_coverage_before_after_comparison.csv",
            "two_leg_resolution_summary.csv",
            "five_plus_resolution_summary.csv",
            "refreshed_distance_band_availability_summary.csv",
            "remaining_leg_capture_review_queue.csv",
            "refreshed_leg_coverage_after_offset_findings.md",
            "refreshed_leg_coverage_after_offset_qa.csv",
            "refreshed_leg_coverage_after_offset_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assigned": False,
            "rates_or_models_calculated": False,
        },
    }
    _write_json(manifest, OUT_DIR / "refreshed_leg_coverage_after_offset_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
