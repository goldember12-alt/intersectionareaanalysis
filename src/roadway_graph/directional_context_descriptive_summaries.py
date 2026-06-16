from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
INPUT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/directional_context_descriptive_summaries"

DIRECTIONAL_BIN_CONTEXT_FILE = INPUT_DIR / "directional_bin_context.csv"
DIRECTIONAL_BIN_CONTEXT_0_1000_FILE = INPUT_DIR / "directional_bin_context_0_1000ft.csv"
DIRECTIONAL_BIN_CONTEXT_1000_2500_FILE = INPUT_DIR / "directional_bin_context_1000_2500ft.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = INPUT_DIR / "directional_crash_context.csv"
REFERENCE_SIGNAL_CONTEXT_FILE = INPUT_DIR / "reference_signal_context_summary.csv"
CONTEXT_MANIFEST_FILE = INPUT_DIR / "directional_bin_context_manifest.json"
CONTEXT_FINDINGS_FILE = INPUT_DIR / "directional_bin_context_findings.md"

WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)
STABLE_SPEED_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
STABLE_AADT_STATUSES = {"stable_aadt_assigned_route_measure", "stable_aadt_assigned_single_route_candidate"}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        blocked = [column for column in usecols if _is_crash_direction_field(column)]
        if blocked:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, pd.NA)
    return (numerator / denominator).astype("Float64")


def _load_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
        "unique_assigned_crash_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "assigned_crashes_with_area_type_count",
        "bin_crash_area_type_summary_status",
        "has_assigned_crash",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "nearest_access_distance_ft",
        "access_context_status",
        "access_ambiguity_count",
        "has_access_context",
        "aadt_value",
        "aadt_year",
        "aadt_context_status",
        "aadt_context_confidence",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
        "roadway_urban_rural_class",
        "roadway_urban_rural_context_status",
        "context_completeness_class",
    ]
    frame = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    numeric_columns = [
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "unique_assigned_crash_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "assigned_crashes_with_area_type_count",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "nearest_access_distance_ft",
        "access_ambiguity_count",
        "aadt_value",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame, column)
    for column in [
        "has_assigned_crash",
        "has_access_context",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
    ]:
        frame[column] = _bool(frame, column)
    frame["represented_length_ft"] = (frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]).clip(lower=0)
    frame["selected_speed_mph"] = frame["weighted_car_speed_limit"].fillna(frame["posted_car_speed_limit_context_value"])
    frame["distance_band"] = pd.cut(
        frame["bin_midpoint_ft_from_reference_signal"],
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"],
        right=False,
        include_lowest=True,
    ).astype(str)
    frame.loc[frame["bin_midpoint_ft_from_reference_signal"].eq(2500), "distance_band"] = "1500_2500ft"
    frame["speed_band"] = [_speed_band(stable, value) for stable, value in zip(frame["has_stable_speed_context"], frame["selected_speed_mph"])]
    frame["aadt_band"] = [_aadt_band(stable, value) for stable, value in zip(frame["has_stable_aadt_context"], frame["aadt_value"])]
    return frame


def _load_crashes() -> pd.DataFrame:
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_midpoint_ft_from_reference_signal",
        "functional_distance_window",
        "crash_area_type_raw",
        "crash_urban_rural_class",
        "crash_urban_rural_context_status",
        "has_crash_area_type",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "posted_car_speed_limit_context_value",
        "aadt_value",
        "refined_speed_context_status",
        "aadt_context_status",
    ]
    frame = _read_csv(DIRECTIONAL_CRASH_CONTEXT_FILE, usecols=columns)
    for column in [
        "bin_midpoint_ft_from_reference_signal",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "posted_car_speed_limit_context_value",
        "aadt_value",
    ]:
        frame[column] = _num(frame, column)
    midpoint = frame["bin_midpoint_ft_from_reference_signal"]
    frame = frame.loc[midpoint.le(2500)].copy()
    frame["distance_window"] = "sensitivity_1000_2500ft"
    frame.loc[frame["bin_midpoint_ft_from_reference_signal"].lt(1000), "distance_window"] = "high_priority_0_1000ft"
    frame["distance_band"] = pd.cut(
        frame["bin_midpoint_ft_from_reference_signal"],
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"],
        right=False,
        include_lowest=True,
    ).astype(str)
    frame.loc[frame["bin_midpoint_ft_from_reference_signal"].eq(2500), "distance_band"] = "1500_2500ft"
    frame["has_stable_speed_context"] = frame["refined_speed_context_status"].isin(STABLE_SPEED_STATUSES)
    frame["has_stable_aadt_context"] = frame["aadt_context_status"].isin(STABLE_AADT_STATUSES)
    frame["speed_band"] = [_speed_band(stable, value) for stable, value in zip(frame["has_stable_speed_context"], frame["posted_car_speed_limit_context_value"])]
    frame["aadt_band"] = [_aadt_band(stable, value) for stable, value in zip(frame["has_stable_aadt_context"], frame["aadt_value"])]
    frame["access_count_class"] = pd.cut(
        frame["access_count_within_catchment"].fillna(0),
        bins=[-1, 0, 1, 3, 999999],
        labels=["0", "1", "2_3", "4plus"],
    ).astype(str)
    return frame


def _validate_companion_inputs() -> dict[str, Any]:
    high = _read_csv(DIRECTIONAL_BIN_CONTEXT_0_1000_FILE, usecols=["reference_directional_bin_id"])
    sensitivity = _read_csv(DIRECTIONAL_BIN_CONTEXT_1000_2500_FILE, usecols=["reference_directional_bin_id"])
    reference_signals = _read_csv(REFERENCE_SIGNAL_CONTEXT_FILE, usecols=["reference_signal_id"])
    manifest = json.loads(CONTEXT_MANIFEST_FILE.read_text(encoding="utf-8"))
    findings_text = CONTEXT_FINDINGS_FILE.read_text(encoding="utf-8")
    return {
        "directional_bin_context_0_1000ft_rows": int(len(high)),
        "directional_bin_context_1000_2500ft_rows": int(len(sensitivity)),
        "reference_signal_context_summary_rows": int(len(reference_signals)),
        "reference_signal_context_summary_unique_signals": int(reference_signals["reference_signal_id"].nunique()),
        "directional_bin_context_manifest_keys": sorted(manifest.keys()),
        "directional_bin_context_findings_bytes": len(findings_text.encode("utf-8")),
    }


def _speed_band(stable: bool, value: Any) -> str:
    if not stable or pd.isna(value):
        return "speed_missing_or_review"
    value = float(value)
    if value < 30:
        return "lt_30_mph"
    if value < 40:
        return "30_39_mph"
    if value < 50:
        return "40_49_mph"
    if value < 60:
        return "50_59_mph"
    return "60plus_mph"


def _aadt_band(stable: bool, value: Any) -> str:
    if not stable or pd.isna(value):
        return "aadt_missing_or_review"
    value = float(value)
    if value < 10000:
        return "lt_10000"
    if value < 20000:
        return "10000_19999"
    if value < 40000:
        return "20000_39999"
    if value < 60000:
        return "40000_59999"
    return "60000plus"


def _with_all_window(frame: pd.DataFrame) -> pd.DataFrame:
    all_rows = frame.copy()
    all_rows["distance_window"] = "all_0_2500ft"
    return pd.concat([frame, all_rows], ignore_index=True)


def _summarize_bins(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    grouped = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            represented_length_ft=("represented_length_ft", "sum"),
            bins_with_assigned_crash=("has_assigned_crash", "sum"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            upstream_crash_count=("unique_assigned_crash_count", lambda s: int(s[frame.loc[s.index, "signal_relative_direction"].eq("upstream_of_reference_signal")].sum())),
            downstream_crash_count=("unique_assigned_crash_count", lambda s: int(s[frame.loc[s.index, "signal_relative_direction"].eq("downstream_of_reference_signal")].sum())),
            access_context_bin_count=("has_access_context", "sum"),
            access_count_within_catchment=("access_count_within_catchment", "sum"),
            access_count_within_100ft=("access_count_within_100ft", "sum"),
            access_count_within_250ft=("access_count_within_250ft", "sum"),
            mean_access_count_per_bin=("access_count_within_catchment", "mean"),
            median_access_count_per_bin=("access_count_within_catchment", "median"),
            bins_with_zero_access=("access_count_within_catchment", lambda s: int(s.fillna(0).eq(0).sum())),
            bins_with_access=("access_count_within_catchment", lambda s: int(s.fillna(0).gt(0).sum())),
            stable_speed_bin_count=("has_stable_speed_context", "sum"),
            speed_review_or_missing_bin_count=("speed_review_or_missing_flag", "sum"),
            stable_aadt_bin_count=("has_stable_aadt_context", "sum"),
            aadt_review_or_missing_bin_count=("aadt_review_or_missing_flag", "sum"),
            assigned_crashes_urban_count=("assigned_crashes_urban_count", "sum"),
            assigned_crashes_rural_count=("assigned_crashes_rural_count", "sum"),
            assigned_crashes_unknown_area_type_count=("assigned_crashes_unknown_area_type_count", "sum"),
            assigned_crashes_with_area_type_count=("assigned_crashes_with_area_type_count", "sum"),
        )
        .reset_index()
    )
    _add_derived(grouped)
    return grouped


def _add_derived(frame: pd.DataFrame) -> None:
    frame["crash_count_per_bin"] = _safe_div(frame["assigned_crash_count"], frame["bin_count"])
    frame["crash_bearing_bin_share"] = _safe_div(frame["bins_with_assigned_crash"], frame["bin_count"])
    frame["access_context_coverage_share"] = _safe_div(frame["access_context_bin_count"], frame["bin_count"])
    frame["speed_context_coverage_share"] = _safe_div(frame["stable_speed_bin_count"], frame["bin_count"])
    frame["aadt_context_coverage_share"] = _safe_div(frame["stable_aadt_bin_count"], frame["bin_count"])
    frame["access_density_per_1000ft"] = _safe_div(frame["access_count_within_catchment"] * 1000, frame["represented_length_ft"])
    frame["upstream_downstream_crash_difference"] = frame["downstream_crash_count"] - frame["upstream_crash_count"]
    frame["upstream_downstream_crash_ratio"] = _safe_div(frame["downstream_crash_count"], frame["upstream_crash_count"])
    frame["low_denominator_ratio_flag"] = frame[["downstream_crash_count", "upstream_crash_count"]].min(axis=1).lt(5)
    frame["urban_crash_share"] = _safe_div(frame["assigned_crashes_urban_count"], frame["assigned_crash_count"])
    frame["rural_crash_share"] = _safe_div(frame["assigned_crashes_rural_count"], frame["assigned_crash_count"])


def _summary_by_window(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(_with_all_window(context), ["distance_window"])


def _summary_by_direction(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(_with_all_window(context), ["distance_window", "signal_relative_direction"])


def _summary_by_reference_signal(context: pd.DataFrame) -> pd.DataFrame:
    base = _summarize_bins(context, ["reference_signal_id"])
    windows = (
        context.pivot_table(
            index="reference_signal_id",
            columns="distance_window",
            values="unique_assigned_crash_count",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(columns={
            "high_priority_0_1000ft": "assigned_crashes_0_1000ft",
            "sensitivity_1000_2500ft": "assigned_crashes_1000_2500ft",
        })
        .reset_index()
    )
    directions = (
        context.pivot_table(
            index="reference_signal_id",
            columns="signal_relative_direction",
            values="unique_assigned_crash_count",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(columns={
            "upstream_of_reference_signal": "upstream_assigned_crash_count",
            "downstream_of_reference_signal": "downstream_assigned_crash_count",
        })
        .reset_index()
    )
    out = base.merge(windows, on="reference_signal_id", how="left").merge(directions, on="reference_signal_id", how="left")
    for column in [
        "assigned_crashes_0_1000ft",
        "assigned_crashes_1000_2500ft",
        "upstream_assigned_crash_count",
        "downstream_assigned_crash_count",
    ]:
        if column not in out.columns:
            out[column] = 0
        out[column] = out[column].fillna(0).astype(int)
    out["has_complete_access_context"] = out["access_context_bin_count"].eq(out["bin_count"])
    out["has_any_speed_review_or_missing"] = out["speed_review_or_missing_bin_count"].gt(0)
    out["has_any_aadt_review_or_missing"] = out["aadt_review_or_missing_bin_count"].gt(0)
    out["has_assigned_crash_area_type_for_all_assigned_crashes"] = out["assigned_crashes_with_area_type_count"].eq(out["assigned_crash_count"])
    out["roadway_urban_rural_context_status"] = "source_not_found"
    return out


def _summary_by_signal_direction_window(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(context, ["reference_signal_id", "signal_relative_direction", "distance_window"])


def _summary_by_distance_band(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(context, ["distance_band"])


def _summary_by_roadway_representation(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(_with_all_window(context), ["distance_window", "signal_relative_direction", "roadway_representation_type"])


def _summary_by_speed_band(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(_with_all_window(context), ["distance_window", "speed_band"])


def _summary_by_aadt_band(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(_with_all_window(context), ["distance_window", "aadt_band"])


def _summary_access_exposure(context: pd.DataFrame) -> pd.DataFrame:
    return _summarize_bins(context, ["signal_relative_direction", "distance_window", "distance_band"])


def _summary_crash_area_type(crashes: pd.DataFrame) -> pd.DataFrame:
    out = (
        pd.concat([crashes, crashes.assign(distance_window="all_0_2500ft")], ignore_index=True)
        .groupby(["distance_window", "signal_relative_direction", "distance_band", "crash_urban_rural_class"], dropna=False)
        .agg(
            assigned_crash_count=("crash_id", "nunique"),
            crashes_with_area_type=("has_crash_area_type", lambda s: int(s.astype(str).str.lower().isin(["true", "1", "yes"]).sum())),
        )
        .reset_index()
    )
    totals = out.groupby(["distance_window", "signal_relative_direction", "distance_band"], dropna=False)["assigned_crash_count"].transform("sum")
    out["crash_class_share"] = _safe_div(out["assigned_crash_count"], totals)
    out["context_scope"] = "crash_level_area_type_not_roadway_urban_rural"
    return out


def _context_completeness_summary(context: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for group_cols in [[], ["distance_window"], ["signal_relative_direction"], ["distance_window", "signal_relative_direction"]]:
        if group_cols:
            summary = _summarize_bins(context, group_cols)
            summary["summary_scope"] = "|".join(group_cols)
        else:
            summary = _summarize_bins(context.assign(summary_scope="all_0_2500ft"), ["summary_scope"])
        frames.append(summary)
    return pd.concat(frames, ignore_index=True, sort=False)


def _qa(context: pd.DataFrame, crashes: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
    high = int(context["distance_window"].eq("high_priority_0_1000ft").sum())
    sensitivity = int(context["distance_window"].eq("sensitivity_1000_2500ft").sum())
    crash_count = int(context["unique_assigned_crash_count"].sum())
    upstream_downstream_total = int(
        context.loc[context["signal_relative_direction"].isin(["upstream_of_reference_signal", "downstream_of_reference_signal"]), "unique_assigned_crash_count"].sum()
    )
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "all_rows_from_0_2500ft_combined_context", "passed": context["distance_window"].isin(WINDOWS).all(), "observed": int((~context["distance_window"].isin(WINDOWS)).sum()), "expected": 0},
            {"check_name": "distance_window_splits_sum", "passed": high + sensitivity == len(context), "observed": high + sensitivity, "expected": len(context)},
            {"check_name": "total_bins", "passed": len(context) == 110710, "observed": len(context), "expected": 110710},
            {"check_name": "assigned_crashes", "passed": crash_count == 13216, "observed": crash_count, "expected": 13216},
            {"check_name": "bins_with_assigned_crashes", "passed": int(context["has_assigned_crash"].sum()) == 8552, "observed": int(context["has_assigned_crash"].sum()), "expected": 8552},
            {"check_name": "stable_speed_bins", "passed": int(context["has_stable_speed_context"].sum()) == 84857, "observed": int(context["has_stable_speed_context"].sum()), "expected": 84857},
            {"check_name": "stable_aadt_bins", "passed": int(context["has_stable_aadt_context"].sum()) == 106210, "observed": int(context["has_stable_aadt_context"].sum()), "expected": 106210},
            {"check_name": "urban_crash_count", "passed": int(context["assigned_crashes_urban_count"].sum()) == 11915, "observed": int(context["assigned_crashes_urban_count"].sum()), "expected": 11915},
            {"check_name": "rural_crash_count", "passed": int(context["assigned_crashes_rural_count"].sum()) == 1301, "observed": int(context["assigned_crashes_rural_count"].sum()), "expected": 1301},
            {"check_name": "upstream_downstream_crashes_equal_assigned_total", "passed": upstream_downstream_total == crash_count, "observed": upstream_downstream_total, "expected": crash_count},
            {"check_name": "no_over_2500ft_rows", "passed": context["bin_midpoint_ft_from_reference_signal"].le(2500).all(), "observed": int(context["bin_midpoint_ft_from_reference_signal"].gt(2500).sum()), "expected": 0},
            {"check_name": "no_figures_or_report_created", "passed": not any(path.suffix.lower() in {".png", ".svg", ".pdf", ".html"} for path in outputs.values()), "observed": "csv/md/json only", "expected": "csv/md/json only"},
            {"check_name": "crash_context_rows_match_assigned_crashes", "passed": len(crashes) == 13216, "observed": len(crashes), "expected": 13216},
        ]
    )


def _findings(context: pd.DataFrame, summaries: dict[str, pd.DataFrame], qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    by_direction = summaries["direction"].loc[summaries["direction"]["distance_window"].eq("all_0_2500ft")]
    upstream = int(by_direction.loc[by_direction["signal_relative_direction"].eq("upstream_of_reference_signal"), "assigned_crash_count"].sum())
    downstream = int(by_direction.loc[by_direction["signal_relative_direction"].eq("downstream_of_reference_signal"), "assigned_crash_count"].sum())
    by_window = summaries["window"]
    high = int(by_window.loc[by_window["distance_window"].eq("high_priority_0_1000ft"), "assigned_crash_count"].sum())
    sensitivity = int(by_window.loc[by_window["distance_window"].eq("sensitivity_1000_2500ft"), "assigned_crash_count"].sum())
    lines = [
        "# Directional Context Descriptive Summary Findings",
        "",
        "## Bounded Question",
        "",
        "Create read-only descriptive summaries from the accepted 0-2,500 ft directional-bin context table without changing scaffold, catchments, crash assignment, or access/speed/AADT joins.",
        "",
        "## Core Counts",
        "",
        f"- total bins summarized: {len(context)}",
        f"- assigned crashes summarized: {int(context['unique_assigned_crash_count'].sum())}",
        f"- reference signals summarized: {context['reference_signal_id'].nunique()}",
        f"- upstream assigned crashes: {upstream}",
        f"- downstream assigned crashes: {downstream}",
        f"- 0-1,000 ft assigned crashes: {high}",
        f"- 1,000-2,500 ft assigned crashes: {sensitivity}",
        f"- stable speed bins: {int(context['has_stable_speed_context'].sum())}",
        f"- stable AADT bins: {int(context['has_stable_aadt_context'].sum())}",
        f"- assigned urban crashes: {int(context['assigned_crashes_urban_count'].sum())}",
        f"- assigned rural crashes: {int(context['assigned_crashes_rural_count'].sum())}",
        "",
        "## Boundaries",
        "",
        "- Crash direction fields were not read or used.",
        "- Context fields do not redefine upstream/downstream.",
        "- No >2,500 ft bins are included.",
        "- No figures were created.",
        "- No report narrative, model, regression, crash rate, or policy claim was created.",
        "- Crash AREA_TYPE is summarized as crash-level context only, not roadway-level urban/rural truth.",
        "",
        "## QA",
        "",
        f"- QA checks passed: {int(qa['passed'].astype(bool).sum())} of {len(qa)}",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_directional_context_descriptive_summaries(*, output_dir: Path = OUTPUT_DIR) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    context = _load_context()
    crashes = _load_crashes()
    companion_inputs = _validate_companion_inputs()

    summaries = {
        "window": _summary_by_window(context),
        "direction": _summary_by_direction(context),
        "reference_signal": _summary_by_reference_signal(context),
        "signal_direction_window": _summary_by_signal_direction_window(context),
        "distance_band": _summary_by_distance_band(context),
        "roadway_representation": _summary_by_roadway_representation(context),
        "speed_band": _summary_by_speed_band(context),
        "aadt_band": _summary_by_aadt_band(context),
        "access_exposure": _summary_access_exposure(context),
        "crash_area_type": _summary_crash_area_type(crashes),
        "context_completeness": _context_completeness_summary(context),
    }
    outputs = {
        "summary_by_window_csv": output_dir / "directional_context_summary_by_window.csv",
        "summary_by_signal_relative_direction_csv": output_dir / "directional_context_summary_by_signal_relative_direction.csv",
        "summary_by_reference_signal_csv": output_dir / "directional_context_summary_by_reference_signal.csv",
        "summary_by_signal_direction_window_csv": output_dir / "directional_context_summary_by_signal_direction_window.csv",
        "summary_by_distance_band_csv": output_dir / "directional_context_summary_by_distance_band.csv",
        "summary_by_roadway_representation_csv": output_dir / "directional_context_summary_by_roadway_representation.csv",
        "summary_by_speed_band_csv": output_dir / "directional_context_summary_by_speed_band.csv",
        "summary_by_aadt_band_csv": output_dir / "directional_context_summary_by_aadt_band.csv",
        "summary_access_exposure_csv": output_dir / "directional_context_summary_access_exposure.csv",
        "summary_crash_area_type_csv": output_dir / "directional_context_summary_crash_area_type.csv",
        "context_completeness_summary_csv": output_dir / "directional_context_context_completeness_summary.csv",
        "qa_csv": output_dir / "directional_context_descriptive_summary_qa.csv",
        "findings_md": output_dir / "directional_context_descriptive_summary_findings.md",
        "manifest_json": output_dir / "directional_context_descriptive_summary_manifest.json",
    }
    _write_csv(summaries["window"], outputs["summary_by_window_csv"])
    _write_csv(summaries["direction"], outputs["summary_by_signal_relative_direction_csv"])
    _write_csv(summaries["reference_signal"], outputs["summary_by_reference_signal_csv"])
    _write_csv(summaries["signal_direction_window"], outputs["summary_by_signal_direction_window_csv"])
    _write_csv(summaries["distance_band"], outputs["summary_by_distance_band_csv"])
    _write_csv(summaries["roadway_representation"], outputs["summary_by_roadway_representation_csv"])
    _write_csv(summaries["speed_band"], outputs["summary_by_speed_band_csv"])
    _write_csv(summaries["aadt_band"], outputs["summary_by_aadt_band_csv"])
    _write_csv(summaries["access_exposure"], outputs["summary_access_exposure_csv"])
    _write_csv(summaries["crash_area_type"], outputs["summary_crash_area_type_csv"])
    _write_csv(summaries["context_completeness"], outputs["context_completeness_summary_csv"])

    qa = _qa(context, crashes, outputs)
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(context, summaries, qa, outputs), outputs["findings_md"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "read-only descriptive summaries from accepted 0-2500ft directional-bin context table",
            "inputs": {
                "directional_bin_context": str(DIRECTIONAL_BIN_CONTEXT_FILE),
                "directional_bin_context_0_1000ft": str(DIRECTIONAL_BIN_CONTEXT_0_1000_FILE),
                "directional_bin_context_1000_2500ft": str(DIRECTIONAL_BIN_CONTEXT_1000_2500_FILE),
                "directional_crash_context": str(DIRECTIONAL_CRASH_CONTEXT_FILE),
                "reference_signal_context_summary": str(REFERENCE_SIGNAL_CONTEXT_FILE),
                "directional_bin_context_manifest": str(CONTEXT_MANIFEST_FILE),
                "directional_bin_context_findings": str(CONTEXT_FINDINGS_FILE),
            },
            "crash_direction_fields_read_or_used": False,
            "context_fields_used_to_redefine_upstream_downstream": False,
            "figures_created": False,
            "report_created": False,
            "modeling_or_policy_claims_created": False,
            "summary_counts": {
                "total_bins": len(context),
                "assigned_crashes": int(context["unique_assigned_crash_count"].sum()),
                "bins_with_assigned_crashes": int(context["has_assigned_crash"].sum()),
                "reference_signals": int(context["reference_signal_id"].nunique()),
                "stable_speed_bins": int(context["has_stable_speed_context"].sum()),
                "stable_aadt_bins": int(context["has_stable_aadt_context"].sum()),
                "assigned_urban_crashes": int(context["assigned_crashes_urban_count"].sum()),
                "assigned_rural_crashes": int(context["assigned_crashes_rural_count"].sum()),
            },
            "companion_input_checks": companion_inputs,
            "qa": qa.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only directional context descriptive summaries.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = build_directional_context_descriptive_summaries(output_dir=args.output_dir)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
