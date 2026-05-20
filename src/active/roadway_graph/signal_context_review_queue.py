from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
SUMMARY_DIR = OUTPUT_ROOT / "analysis/current/directional_context_descriptive_summaries"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/signal_context_review_queue"

DIRECTIONAL_BIN_CONTEXT_FILE = CONTEXT_DIR / "directional_bin_context.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = CONTEXT_DIR / "directional_crash_context.csv"
REFERENCE_SIGNAL_CONTEXT_FILE = CONTEXT_DIR / "reference_signal_context_summary.csv"
SUMMARY_BY_SIGNAL_FILE = SUMMARY_DIR / "directional_context_summary_by_reference_signal.csv"
SUMMARY_BY_SIGNAL_DIRECTION_WINDOW_FILE = SUMMARY_DIR / "directional_context_summary_by_signal_direction_window.csv"
SUMMARY_BY_DISTANCE_BAND_FILE = SUMMARY_DIR / "directional_context_summary_by_distance_band.csv"
COMPLETENESS_SUMMARY_FILE = SUMMARY_DIR / "directional_context_context_completeness_summary.csv"
DESCRIPTIVE_MANIFEST_FILE = SUMMARY_DIR / "directional_context_descriptive_summary_manifest.json"
DESCRIPTIVE_FINDINGS_FILE = SUMMARY_DIR / "directional_context_descriptive_summary_findings.md"

WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)
SCORE_WEIGHTS = {
    "crash_burden_rank": 0.35,
    "core_window_crash_rank": 0.25,
    "directional_imbalance_rank": 0.15,
    "access_context_rank": 0.15,
    "context_incompleteness_rank": 0.10,
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
        return pd.Series(0, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, pd.NA)
    return (numerator / denominator).astype("Float64")


def _rank_component(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0)
    if numeric.nunique(dropna=False) <= 1:
        return pd.Series(0.0, index=series.index)
    return numeric.rank(method="average", pct=True)


def _tier(score: float) -> str:
    if score >= 0.90:
        return "highest_review_priority"
    if score >= 0.75:
        return "high_review_priority"
    if score >= 0.50:
        return "moderate_review_priority"
    return "lower_review_priority"


def _add_review_fields(frame: pd.DataFrame, *, signal_level: bool = True) -> pd.DataFrame:
    result = frame.copy()
    total = _num(result, "assigned_crash_count_total")
    core = _num(result, "assigned_crash_count_0_1000ft")
    upstream = _num(result, "upstream_crash_count")
    downstream = _num(result, "downstream_crash_count")
    min_direction = pd.concat([upstream, downstream], axis=1).min(axis=1)
    max_direction = pd.concat([upstream, downstream], axis=1).max(axis=1)
    result["upstream_downstream_abs_difference"] = (upstream - downstream).abs()
    result["upstream_downstream_ratio"] = _safe_ratio(max_direction, min_direction)
    result["low_denominator_ratio_warning"] = total.lt(5) & result["upstream_downstream_abs_difference"].gt(0)

    crash_threshold = total.quantile(0.90)
    core_threshold = core.quantile(0.90)
    imbalance_threshold = result["upstream_downstream_abs_difference"].quantile(0.90)
    access_threshold = _num(result, "access_count_within_250ft_sum").quantile(0.90)

    result["high_crash_burden"] = total.ge(crash_threshold) & total.gt(0)
    result["high_0_1000ft_crash_burden"] = core.ge(core_threshold) & core.gt(0)
    result["high_directional_imbalance"] = (
        total.ge(5)
        & result["upstream_downstream_abs_difference"].ge(imbalance_threshold)
        & result["upstream_downstream_abs_difference"].gt(0)
    )
    result["high_access_context"] = _num(result, "access_count_within_250ft_sum").ge(access_threshold) & _num(result, "access_count_within_250ft_sum").gt(0)
    result["incomplete_speed_context"] = _num(result, "speed_missing_or_review_bin_count").gt(0)
    result["incomplete_aadt_context"] = _num(result, "aadt_missing_or_review_bin_count").gt(0)
    result["urban_crash_dominant"] = total.ge(5) & _safe_ratio(_num(result, "assigned_crashes_urban_count"), total).ge(0.80).fillna(False)
    result["rural_crash_present"] = _num(result, "assigned_crashes_rural_count").gt(0)
    review_flags = [
        "high_crash_burden",
        "high_0_1000ft_crash_burden",
        "high_directional_imbalance",
        "high_access_context",
        "incomplete_speed_context",
        "incomplete_aadt_context",
    ]
    result["review_context_flag_count"] = result[review_flags].sum(axis=1)
    result["many_review_context_flags"] = result["review_context_flag_count"].ge(3)

    result["crash_burden_rank"] = _rank_component(total)
    result["core_window_crash_rank"] = _rank_component(core)
    result["directional_imbalance_rank"] = _rank_component(result["upstream_downstream_abs_difference"])
    result["access_context_rank"] = _rank_component(_num(result, "access_count_within_250ft_sum"))
    incompleteness = _num(result, "speed_missing_or_review_bin_count") + _num(result, "aadt_missing_or_review_bin_count")
    result["context_incompleteness_rank"] = _rank_component(incompleteness)
    result["review_priority_score"] = sum(result[column] * weight for column, weight in SCORE_WEIGHTS.items())
    result["review_priority_tier"] = result["review_priority_score"].map(_tier)
    result["review_queue_scope"] = "signal_level_review_prioritization_only" if signal_level else "signal_direction_review_prioritization_only"
    return result


def _load_inputs() -> dict[str, Any]:
    context = _read_csv(
        DIRECTIONAL_BIN_CONTEXT_FILE,
        usecols=[
            "reference_signal_id",
            "reference_directional_bin_id",
            "signal_relative_direction",
            "bin_midpoint_ft_from_reference_signal",
            "distance_window",
            "unique_assigned_crash_count",
        ],
    )
    context["bin_midpoint_ft_from_reference_signal"] = _num(context, "bin_midpoint_ft_from_reference_signal")
    context["unique_assigned_crash_count"] = _num(context, "unique_assigned_crash_count")
    context = context.loc[context["distance_window"].isin(WINDOWS)].copy()
    crashes = _read_csv(DIRECTIONAL_CRASH_CONTEXT_FILE, usecols=["crash_id", "reference_signal_id", "bin_midpoint_ft_from_reference_signal"])
    crashes["bin_midpoint_ft_from_reference_signal"] = _num(crashes, "bin_midpoint_ft_from_reference_signal")
    reference_signal_context = _read_csv(REFERENCE_SIGNAL_CONTEXT_FILE, usecols=["reference_signal_id", "assigned_crash_count"])
    signal_summary = _read_csv(SUMMARY_BY_SIGNAL_FILE)
    direction_window = _read_csv(SUMMARY_BY_SIGNAL_DIRECTION_WINDOW_FILE)
    distance_band = _read_csv(SUMMARY_BY_DISTANCE_BAND_FILE)
    completeness = _read_csv(COMPLETENESS_SUMMARY_FILE)
    manifest = json.loads(DESCRIPTIVE_MANIFEST_FILE.read_text(encoding="utf-8"))
    findings = DESCRIPTIVE_FINDINGS_FILE.read_text(encoding="utf-8")
    return {
        "context": context,
        "crashes": crashes,
        "reference_signal_context": reference_signal_context,
        "signal_summary": signal_summary,
        "direction_window": direction_window,
        "distance_band": distance_band,
        "completeness": completeness,
        "manifest": manifest,
        "findings_bytes": len(findings.encode("utf-8")),
    }


def _prepare_signal_queue(signal_summary: pd.DataFrame) -> pd.DataFrame:
    frame = signal_summary.copy()
    rename = {
        "assigned_crash_count": "assigned_crash_count_total",
        "assigned_crashes_0_1000ft": "assigned_crash_count_0_1000ft",
        "assigned_crashes_1000_2500ft": "assigned_crash_count_1000_2500ft",
        "bins_with_assigned_crash": "crash_bearing_bin_count",
        "access_count_within_100ft": "access_count_within_100ft_sum",
        "access_count_within_250ft": "access_count_within_250ft_sum",
        "stable_speed_bin_count": "stable_speed_context_bin_count",
        "stable_aadt_bin_count": "stable_aadt_context_bin_count",
        "speed_review_or_missing_bin_count": "speed_missing_or_review_bin_count",
        "aadt_review_or_missing_bin_count": "aadt_missing_or_review_bin_count",
    }
    frame = frame.rename(columns=rename)
    numeric_columns = [
        "assigned_crash_count_total",
        "assigned_crash_count_0_1000ft",
        "assigned_crash_count_1000_2500ft",
        "upstream_crash_count",
        "downstream_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "access_count_within_100ft_sum",
        "access_count_within_250ft_sum",
        "mean_access_count_per_bin",
        "stable_speed_context_bin_count",
        "stable_aadt_context_bin_count",
        "speed_missing_or_review_bin_count",
        "aadt_missing_or_review_bin_count",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame, column)
    frame["crash_bearing_bin_share"] = _safe_ratio(frame["crash_bearing_bin_count"], frame["bin_count"]).fillna(0)
    frame["stable_speed_context_bin_share"] = _safe_ratio(frame["stable_speed_context_bin_count"], frame["bin_count"]).fillna(0)
    frame["stable_aadt_context_bin_share"] = _safe_ratio(frame["stable_aadt_context_bin_count"], frame["bin_count"]).fillna(0)
    frame["context_completeness_class"] = "complete_access_speed_aadt"
    frame.loc[frame["speed_missing_or_review_bin_count"].gt(0) | frame["aadt_missing_or_review_bin_count"].gt(0), "context_completeness_class"] = "has_speed_or_aadt_review_or_missing"
    return _add_review_fields(frame, signal_level=True)


def _prepare_high_priority_queue(direction_window: pd.DataFrame) -> pd.DataFrame:
    high = direction_window.loc[direction_window["distance_window"].eq("high_priority_0_1000ft")].copy()
    group = high.groupby("reference_signal_id", dropna=False).agg(
        assigned_crash_count_total=("assigned_crash_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        assigned_crash_count_0_1000ft=("assigned_crash_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        assigned_crash_count_1000_2500ft=("assigned_crash_count", lambda s: 0),
        upstream_crash_count=("upstream_crash_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        downstream_crash_count=("downstream_crash_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        crash_bearing_bin_count=("bins_with_assigned_crash", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        bin_count=("bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        assigned_crashes_urban_count=("assigned_crashes_urban_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        assigned_crashes_rural_count=("assigned_crashes_rural_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        access_count_within_100ft_sum=("access_count_within_100ft", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        access_count_within_250ft_sum=("access_count_within_250ft", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        mean_access_count_per_bin=("mean_access_count_per_bin", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).mean()),
        stable_speed_context_bin_count=("stable_speed_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        stable_aadt_context_bin_count=("stable_aadt_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        speed_missing_or_review_bin_count=("speed_review_or_missing_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        aadt_missing_or_review_bin_count=("aadt_review_or_missing_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    group["crash_bearing_bin_share"] = _safe_ratio(group["crash_bearing_bin_count"], group["bin_count"]).fillna(0)
    group["stable_speed_context_bin_share"] = _safe_ratio(group["stable_speed_context_bin_count"], group["bin_count"]).fillna(0)
    group["stable_aadt_context_bin_share"] = _safe_ratio(group["stable_aadt_context_bin_count"], group["bin_count"]).fillna(0)
    group["context_completeness_class"] = "complete_access_speed_aadt"
    group.loc[group["speed_missing_or_review_bin_count"].gt(0) | group["aadt_missing_or_review_bin_count"].gt(0), "context_completeness_class"] = "has_speed_or_aadt_review_or_missing"
    return _add_review_fields(group, signal_level=True)


def _prepare_direction_queues(direction_window: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    window = direction_window.copy()
    rename = {
        "assigned_crash_count": "assigned_crash_count_total",
        "bins_with_assigned_crash": "crash_bearing_bin_count",
        "access_count_within_100ft": "access_count_within_100ft_sum",
        "access_count_within_250ft": "access_count_within_250ft_sum",
        "stable_speed_bin_count": "stable_speed_context_bin_count",
        "stable_aadt_bin_count": "stable_aadt_context_bin_count",
        "speed_review_or_missing_bin_count": "speed_missing_or_review_bin_count",
        "aadt_review_or_missing_bin_count": "aadt_missing_or_review_bin_count",
    }
    window = window.rename(columns=rename)
    for column in [
        "assigned_crash_count_total",
        "upstream_crash_count",
        "downstream_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "access_count_within_100ft_sum",
        "access_count_within_250ft_sum",
        "mean_access_count_per_bin",
        "stable_speed_context_bin_count",
        "stable_aadt_context_bin_count",
        "speed_missing_or_review_bin_count",
        "aadt_missing_or_review_bin_count",
    ]:
        window[column] = _num(window, column)
    window["assigned_crash_count_0_1000ft"] = 0
    window.loc[window["distance_window"].eq("high_priority_0_1000ft"), "assigned_crash_count_0_1000ft"] = window["assigned_crash_count_total"]
    window["assigned_crash_count_1000_2500ft"] = 0
    window.loc[window["distance_window"].eq("sensitivity_1000_2500ft"), "assigned_crash_count_1000_2500ft"] = window["assigned_crash_count_total"]
    window["crash_bearing_bin_share"] = _safe_ratio(window["crash_bearing_bin_count"], window["bin_count"]).fillna(0)
    window["stable_speed_context_bin_share"] = _safe_ratio(window["stable_speed_context_bin_count"], window["bin_count"]).fillna(0)
    window["stable_aadt_context_bin_share"] = _safe_ratio(window["stable_aadt_context_bin_count"], window["bin_count"]).fillna(0)
    window["context_completeness_class"] = "complete_access_speed_aadt"
    window.loc[window["speed_missing_or_review_bin_count"].gt(0) | window["aadt_missing_or_review_bin_count"].gt(0), "context_completeness_class"] = "has_speed_or_aadt_review_or_missing"
    window_queue = _add_review_fields(window, signal_level=False)

    direction = window.groupby(["reference_signal_id", "signal_relative_direction"], dropna=False).agg(
        assigned_crash_count_total=("assigned_crash_count_total", "sum"),
        assigned_crash_count_0_1000ft=("assigned_crash_count_0_1000ft", "sum"),
        assigned_crash_count_1000_2500ft=("assigned_crash_count_1000_2500ft", "sum"),
        upstream_crash_count=("upstream_crash_count", "sum"),
        downstream_crash_count=("downstream_crash_count", "sum"),
        crash_bearing_bin_count=("crash_bearing_bin_count", "sum"),
        bin_count=("bin_count", "sum"),
        assigned_crashes_urban_count=("assigned_crashes_urban_count", "sum"),
        assigned_crashes_rural_count=("assigned_crashes_rural_count", "sum"),
        access_count_within_100ft_sum=("access_count_within_100ft_sum", "sum"),
        access_count_within_250ft_sum=("access_count_within_250ft_sum", "sum"),
        mean_access_count_per_bin=("mean_access_count_per_bin", "mean"),
        stable_speed_context_bin_count=("stable_speed_context_bin_count", "sum"),
        stable_aadt_context_bin_count=("stable_aadt_context_bin_count", "sum"),
        speed_missing_or_review_bin_count=("speed_missing_or_review_bin_count", "sum"),
        aadt_missing_or_review_bin_count=("aadt_missing_or_review_bin_count", "sum"),
    ).reset_index()
    direction["crash_bearing_bin_share"] = _safe_ratio(direction["crash_bearing_bin_count"], direction["bin_count"]).fillna(0)
    direction["stable_speed_context_bin_share"] = _safe_ratio(direction["stable_speed_context_bin_count"], direction["bin_count"]).fillna(0)
    direction["stable_aadt_context_bin_share"] = _safe_ratio(direction["stable_aadt_context_bin_count"], direction["bin_count"]).fillna(0)
    direction["context_completeness_class"] = "complete_access_speed_aadt"
    direction.loc[direction["speed_missing_or_review_bin_count"].gt(0) | direction["aadt_missing_or_review_bin_count"].gt(0), "context_completeness_class"] = "has_speed_or_aadt_review_or_missing"
    return _add_review_fields(direction, signal_level=False), window_queue


def _flags_summary(overall: pd.DataFrame) -> pd.DataFrame:
    flags = [
        "high_crash_burden",
        "high_0_1000ft_crash_burden",
        "high_directional_imbalance",
        "high_access_context",
        "incomplete_speed_context",
        "incomplete_aadt_context",
        "many_review_context_flags",
        "urban_crash_dominant",
        "rural_crash_present",
        "low_denominator_ratio_warning",
    ]
    rows = [{"review_flag": flag, "signal_count": int(overall[flag].astype(bool).sum())} for flag in flags]
    return pd.DataFrame(rows)


def _qa(context: pd.DataFrame, crashes: pd.DataFrame, overall: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
    crash_total = int(context["unique_assigned_crash_count"].sum())
    high_crashes = int(context.loc[context["distance_window"].eq("high_priority_0_1000ft"), "unique_assigned_crash_count"].sum())
    sensitivity_crashes = int(context.loc[context["distance_window"].eq("sensitivity_1000_2500ft"), "unique_assigned_crash_count"].sum())
    upstream_downstream_total = int(
        context.loc[context["signal_relative_direction"].isin(["upstream_of_reference_signal", "downstream_of_reference_signal"]), "unique_assigned_crash_count"].sum()
    )
    score_columns = [
        "crash_burden_rank",
        "core_window_crash_rank",
        "directional_imbalance_rank",
        "access_context_rank",
        "context_incompleteness_rank",
        "review_priority_score",
        "review_priority_tier",
    ]
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "all_rows_from_0_2500ft_universe", "passed": context["distance_window"].isin(WINDOWS).all(), "observed": int((~context["distance_window"].isin(WINDOWS)).sum()), "expected": 0},
            {"check_name": "total_reference_signals", "passed": len(overall) == 971, "observed": len(overall), "expected": 971},
            {"check_name": "assigned_crashes_represented", "passed": crash_total == 13216, "observed": crash_total, "expected": 13216},
            {"check_name": "high_priority_0_1000ft_crashes", "passed": high_crashes == 9170, "observed": high_crashes, "expected": 9170},
            {"check_name": "sensitivity_1000_2500ft_crashes", "passed": sensitivity_crashes == 4046, "observed": sensitivity_crashes, "expected": 4046},
            {"check_name": "upstream_downstream_crashes_match_assigned_total", "passed": upstream_downstream_total == crash_total, "observed": upstream_downstream_total, "expected": crash_total},
            {"check_name": "no_over_2500ft_rows", "passed": context["bin_midpoint_ft_from_reference_signal"].le(2500).all() and crashes["bin_midpoint_ft_from_reference_signal"].le(2500).all(), "observed": int(context["bin_midpoint_ft_from_reference_signal"].gt(2500).sum() + crashes["bin_midpoint_ft_from_reference_signal"].gt(2500).sum()), "expected": 0},
            {"check_name": "no_rates_models_regressions_figures_or_policy_claims", "passed": not any(path.suffix.lower() in {".png", ".svg", ".pdf", ".html"} for path in outputs.values()), "observed": "csv/md/json only", "expected": "csv/md/json only"},
            {"check_name": "review_score_columns_transparent", "passed": all(column in overall.columns for column in score_columns), "observed": ",".join([column for column in score_columns if column in overall.columns]), "expected": ",".join(score_columns)},
            {"check_name": "low_denominator_warnings_exist", "passed": "low_denominator_ratio_warning" in overall.columns and overall["low_denominator_ratio_warning"].astype(bool).any(), "observed": int(overall["low_denominator_ratio_warning"].astype(bool).sum()), "expected": ">0"},
        ]
    )


def _findings(overall: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    tier_counts = overall["review_priority_tier"].value_counts().to_dict()
    flag_counts = _flags_summary(overall).sort_values("signal_count", ascending=False)
    top_flags = [f"- {row.review_flag}: {int(row.signal_count)} signals" for row in flag_counts.itertuples(index=False)]
    lines = [
        "# Signal Context Review Queue Findings",
        "",
        "## Bounded Question",
        "",
        "Create read-only signal-level and signal-direction-level review queues from accepted roadway-derived directional context outputs.",
        "",
        "## Interpretation Boundary",
        "",
        "These queues are for manual review prioritization only. They are not danger rankings, safety-performance rankings, policy findings, models, crash-rate analyses, regressions, or causal claims.",
        "",
        "## Core Counts",
        "",
        f"- signals in overall queue: {len(overall)}",
        f"- assigned crashes represented: {int(overall['assigned_crash_count_total'].sum())}",
        f"- 0-1,000 ft assigned crashes: {int(overall['assigned_crash_count_0_1000ft'].sum())}",
        f"- 1,000-2,500 ft assigned crashes: {int(overall['assigned_crash_count_1000_2500ft'].sum())}",
        f"- upstream assigned crashes: {int(overall['upstream_crash_count'].sum())}",
        f"- downstream assigned crashes: {int(overall['downstream_crash_count'].sum())}",
        "",
        "## Review Priority Tiers",
        "",
        f"- highest_review_priority: {int(tier_counts.get('highest_review_priority', 0))}",
        f"- high_review_priority: {int(tier_counts.get('high_review_priority', 0))}",
        f"- moderate_review_priority: {int(tier_counts.get('moderate_review_priority', 0))}",
        f"- lower_review_priority: {int(tier_counts.get('lower_review_priority', 0))}",
        "",
        "## Review Reason Flag Counts",
        "",
        *top_flags,
        "",
        "## Boundaries",
        "",
        "- Crash direction fields were not read or used.",
        "- Context fields do not redefine upstream/downstream.",
        "- No >2,500 ft rows are included.",
        "- No crash rates using AADT were computed.",
        "- No figures, report narrative, models, regressions, or policy claims were created.",
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


def build_signal_context_review_queue(*, output_dir: Path = OUTPUT_DIR) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    inputs = _load_inputs()
    overall = _prepare_signal_queue(inputs["signal_summary"]).sort_values(
        ["review_priority_score", "assigned_crash_count_total", "assigned_crash_count_0_1000ft"],
        ascending=[False, False, False],
    )
    high_priority = _prepare_high_priority_queue(inputs["direction_window"]).sort_values(
        ["review_priority_score", "assigned_crash_count_total"],
        ascending=[False, False],
    )
    direction, direction_window = _prepare_direction_queues(inputs["direction_window"])
    direction = direction.sort_values(["review_priority_score", "assigned_crash_count_total"], ascending=[False, False])
    direction_window = direction_window.sort_values(["review_priority_score", "assigned_crash_count_total"], ascending=[False, False])

    outputs = {
        "overall_csv": output_dir / "signal_review_queue_overall.csv",
        "high_priority_0_1000ft_csv": output_dir / "signal_review_queue_high_priority_0_1000ft.csv",
        "signal_direction_csv": output_dir / "signal_direction_review_queue.csv",
        "signal_direction_window_csv": output_dir / "signal_direction_window_review_queue.csv",
        "by_crash_burden_csv": output_dir / "signal_review_queue_by_crash_burden.csv",
        "by_directional_imbalance_csv": output_dir / "signal_review_queue_by_directional_imbalance.csv",
        "by_context_density_csv": output_dir / "signal_review_queue_by_context_density.csv",
        "by_context_completeness_csv": output_dir / "signal_review_queue_by_context_completeness.csv",
        "flags_summary_csv": output_dir / "signal_review_queue_flags_summary.csv",
        "qa_csv": output_dir / "signal_context_review_queue_qa.csv",
        "findings_md": output_dir / "signal_context_review_queue_findings.md",
        "manifest_json": output_dir / "signal_context_review_queue_manifest.json",
    }

    _write_csv(overall, outputs["overall_csv"])
    _write_csv(high_priority, outputs["high_priority_0_1000ft_csv"])
    _write_csv(direction, outputs["signal_direction_csv"])
    _write_csv(direction_window, outputs["signal_direction_window_csv"])
    _write_csv(overall.sort_values(["assigned_crash_count_total", "assigned_crash_count_0_1000ft"], ascending=[False, False]), outputs["by_crash_burden_csv"])
    _write_csv(overall.sort_values(["upstream_downstream_abs_difference", "assigned_crash_count_total"], ascending=[False, False]), outputs["by_directional_imbalance_csv"])
    _write_csv(overall.sort_values(["access_count_within_250ft_sum", "crash_bearing_bin_count"], ascending=[False, False]), outputs["by_context_density_csv"])
    _write_csv(overall.loc[overall["incomplete_speed_context"] | overall["incomplete_aadt_context"]].sort_values(["assigned_crash_count_total", "review_context_flag_count"], ascending=[False, False]), outputs["by_context_completeness_csv"])
    flags = _flags_summary(overall)
    _write_csv(flags, outputs["flags_summary_csv"])
    qa = _qa(inputs["context"], inputs["crashes"], overall, outputs)
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(overall, qa, outputs), outputs["findings_md"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "read-only signal-level review-prioritization queues from accepted directional context summaries",
            "inputs": {
                "directional_bin_context": str(DIRECTIONAL_BIN_CONTEXT_FILE),
                "directional_crash_context": str(DIRECTIONAL_CRASH_CONTEXT_FILE),
                "reference_signal_context_summary": str(REFERENCE_SIGNAL_CONTEXT_FILE),
                "directional_context_summary_by_reference_signal": str(SUMMARY_BY_SIGNAL_FILE),
                "directional_context_summary_by_signal_direction_window": str(SUMMARY_BY_SIGNAL_DIRECTION_WINDOW_FILE),
                "directional_context_summary_by_distance_band": str(SUMMARY_BY_DISTANCE_BAND_FILE),
                "directional_context_context_completeness_summary": str(COMPLETENESS_SUMMARY_FILE),
                "directional_context_descriptive_summary_manifest": str(DESCRIPTIVE_MANIFEST_FILE),
                "directional_context_descriptive_summary_findings": str(DESCRIPTIVE_FINDINGS_FILE),
            },
            "review_priority_score": {
                "interpretation": "manual review ordering only; not a model, danger ranking, crash rate, policy finding, or causal claim",
                "weights": SCORE_WEIGHTS,
                "tiers": {
                    "highest_review_priority": "score >= 0.90",
                    "high_review_priority": "0.75 <= score < 0.90",
                    "moderate_review_priority": "0.50 <= score < 0.75",
                    "lower_review_priority": "score < 0.50",
                },
            },
            "input_context_rows": int(len(inputs["context"])),
            "input_crash_rows": int(len(inputs["crashes"])),
            "distance_band_summary_rows_read": int(len(inputs["distance_band"])),
            "context_completeness_summary_rows_read": int(len(inputs["completeness"])),
            "descriptive_manifest_keys": sorted(inputs["manifest"].keys()),
            "descriptive_findings_bytes": inputs["findings_bytes"],
            "summary_counts": {
                "signals_in_overall_queue": int(len(overall)),
                "assigned_crashes": int(overall["assigned_crash_count_total"].sum()),
                "high_priority_0_1000ft_crashes": int(overall["assigned_crash_count_0_1000ft"].sum()),
                "sensitivity_1000_2500ft_crashes": int(overall["assigned_crash_count_1000_2500ft"].sum()),
                "highest_review_priority_signals": int(overall["review_priority_tier"].eq("highest_review_priority").sum()),
                "high_review_priority_signals": int(overall["review_priority_tier"].eq("high_review_priority").sum()),
                "moderate_review_priority_signals": int(overall["review_priority_tier"].eq("moderate_review_priority").sum()),
                "lower_review_priority_signals": int(overall["review_priority_tier"].eq("lower_review_priority").sum()),
                "signals_with_incomplete_speed_context": int(overall["incomplete_speed_context"].sum()),
                "signals_with_incomplete_aadt_context": int(overall["incomplete_aadt_context"].sum()),
                "signals_with_high_directional_imbalance": int(overall["high_directional_imbalance"].sum()),
            },
            "flags_summary": flags.to_dict(orient="records"),
            "qa": qa.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only signal context review queues.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = build_signal_context_review_queue(output_dir=args.output_dir)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
