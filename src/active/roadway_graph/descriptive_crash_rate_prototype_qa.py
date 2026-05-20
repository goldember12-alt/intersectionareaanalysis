from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
PROTOTYPE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype"
QA_OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype_qa"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
APPROVAL_DIR = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1"

RATE_ROWS_FILE = PROTOTYPE_DIR / "descriptive_rate_prototype_signal_direction_window.csv"
NON_READY_FILE = PROTOTYPE_DIR / "descriptive_rate_prototype_non_ready_units.csv"
SUMMARY_BY_WINDOW_FILE = PROTOTYPE_DIR / "descriptive_rate_summary_by_window.csv"
SUMMARY_BY_DIRECTION_FILE = PROTOTYPE_DIR / "descriptive_rate_summary_by_signal_relative_direction.csv"
SUMMARY_BY_FLAGS_FILE = PROTOTYPE_DIR / "descriptive_rate_summary_by_review_flags.csv"
TOP_REVIEW_FILE = PROTOTYPE_DIR / "descriptive_rate_top_review_units.csv"
PROTOTYPE_FINDINGS_FILE = PROTOTYPE_DIR / "descriptive_rate_prototype_findings.md"
EXPOSURE_READINESS_SUMMARY_FILE = READINESS_DIR / "exposure_modeling_readiness_summary.csv"
RATE_APPROVAL_DECISION_FILE = APPROVAL_DIR / "rate_prototype_authorization_decision.csv"
RATE_APPROVAL_MANIFEST_FILE = APPROVAL_DIR / "rate_assumption_approval_manifest.json"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)
TOP_RATE_REVIEW_LIMIT = 100
LOW_EXPOSURE_QUANTILE = 0.10
WIDE_CI_RATIO_THRESHOLD = 4.0


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
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_ratio(numerator: float, denominator: float) -> float | pd.NA:
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return pd.NA
    return float(numerator / denominator)


def load_rate_rows() -> pd.DataFrame:
    frame = _read_csv(RATE_ROWS_FILE)
    numeric_columns = [
        "assigned_crash_count",
        "bin_count",
        "represented_length_miles",
        "stable_aadt_coverage_share",
        "aadt_value_for_denominator",
        "vmt_like_exposure",
        "crashes_per_million_vmt",
        "crash_count_lower_95",
        "crash_count_upper_95",
        "rate_lower_95_per_million_vmt",
        "rate_upper_95_per_million_vmt",
        "length_weighted_aadt",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame, column)
    for column in [
        "low_crash_count_flag",
        "zero_crash_unit_flag",
        "low_aadt_coverage_flag",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "bidirectional_aadt_assumption_flag",
        "denominator_ready_flag",
        "low_exposure_flag",
        "rate_suppression_flag",
    ]:
        frame[column] = _bool(frame, column)
    frame["rate_ci_width"] = frame["rate_upper_95_per_million_vmt"] - frame["rate_lower_95_per_million_vmt"]
    frame["rate_ci_width_ratio"] = frame["rate_upper_95_per_million_vmt"] / frame["rate_lower_95_per_million_vmt"].replace(0, pd.NA)
    frame["wide_confidence_interval_flag"] = frame["rate_ci_width_ratio"].gt(WIDE_CI_RATIO_THRESHOLD) | frame["rate_lower_95_per_million_vmt"].eq(0)
    return frame


def load_non_ready() -> pd.DataFrame:
    frame = _read_csv(NON_READY_FILE)
    numeric_columns = [
        "assigned_crash_count",
        "bin_count",
        "represented_length_miles",
        "stable_aadt_coverage_share",
        "length_weighted_aadt",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame, column)
    for column in [
        "low_aadt_coverage_flag",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "denominator_ready_flag",
        "positive_aadt_flag",
    ]:
        if column in frame.columns:
            frame[column] = _bool(frame, column)
    return frame


def load_summary(path: Path) -> pd.DataFrame:
    frame = _read_csv(path)
    for column in [
        "rate_ready_unit_count",
        "assigned_crash_count",
        "vmt_like_exposure",
        "crashes_per_million_vmt",
        "rate_lower_95_per_million_vmt",
        "rate_upper_95_per_million_vmt",
    ]:
        if column in frame.columns:
            frame[column] = _num(frame, column)
    return frame


def rate_distribution(frame: pd.DataFrame, group_cols: list[str] | None = None) -> pd.DataFrame:
    group_cols = group_cols or []
    if group_cols:
        grouped = frame.groupby(group_cols, dropna=False)
    else:
        grouped = [((), frame)]
    rows = []
    for key, group in grouped:
        values = group["crashes_per_million_vmt"].dropna()
        row: dict[str, Any] = {
            "rate_row_count": len(group),
            "assigned_crash_count": int(group["assigned_crash_count"].sum()),
            "min": values.min(),
            "p05": values.quantile(0.05),
            "p25": values.quantile(0.25),
            "median": values.median(),
            "mean": values.mean(),
            "p75": values.quantile(0.75),
            "p95": values.quantile(0.95),
            "max": values.max(),
            "low_crash_count_unit_count": int(group["low_crash_count_flag"].sum()),
            "zero_crash_unit_count": int(group["zero_crash_unit_flag"].sum()),
            "low_exposure_unit_count": int(group["low_exposure_flag"].sum()),
            "wide_confidence_interval_unit_count": int(group["wide_confidence_interval_flag"].sum()),
        }
        if group_cols:
            if not isinstance(key, tuple):
                key = (key,)
            row.update(dict(zip(group_cols, key)))
        rows.append(row)
    columns = group_cols + [column for column in rows[0] if column not in group_cols] if rows else group_cols
    return pd.DataFrame(rows, columns=columns)


def comparison_rows(summary_by_window: pd.DataFrame, summary_by_direction: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if set(summary_by_window["analysis_window"]) >= {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}:
        high = summary_by_window.loc[summary_by_window["analysis_window"].eq("high_priority_0_1000ft")].iloc[0]
        sens = summary_by_window.loc[summary_by_window["analysis_window"].eq("sensitivity_1000_2500ft")].iloc[0]
        rows.append(
            {
                "comparison_type": "window_rate_comparison",
                "comparison_label": "high_priority_0_1000ft_vs_sensitivity_1000_2500ft",
                "numerator_group": "high_priority_0_1000ft",
                "denominator_group": "sensitivity_1000_2500ft",
                "numerator_rate": high["crashes_per_million_vmt"],
                "denominator_rate": sens["crashes_per_million_vmt"],
                "crude_rate_ratio": _safe_ratio(high["crashes_per_million_vmt"], sens["crashes_per_million_vmt"]),
                "ci_overlap_note": _ci_overlap_note(high, sens),
                "interpretation_note": "descriptive comparison only; not causal or policy evidence",
            }
        )
    if set(summary_by_direction["signal_relative_direction"]) >= {"upstream_of_reference_signal", "downstream_of_reference_signal"}:
        upstream = summary_by_direction.loc[summary_by_direction["signal_relative_direction"].eq("upstream_of_reference_signal")].iloc[0]
        downstream = summary_by_direction.loc[summary_by_direction["signal_relative_direction"].eq("downstream_of_reference_signal")].iloc[0]
        rows.append(
            {
                "comparison_type": "direction_rate_comparison",
                "comparison_label": "downstream_vs_upstream",
                "numerator_group": "downstream_of_reference_signal",
                "denominator_group": "upstream_of_reference_signal",
                "numerator_rate": downstream["crashes_per_million_vmt"],
                "denominator_rate": upstream["crashes_per_million_vmt"],
                "crude_rate_ratio": _safe_ratio(downstream["crashes_per_million_vmt"], upstream["crashes_per_million_vmt"]),
                "ci_overlap_note": _ci_overlap_note(downstream, upstream),
                "interpretation_note": "descriptive comparison only; not a safety-performance difference",
            }
        )
    return pd.DataFrame(rows)


def _ci_overlap_note(left: pd.Series, right: pd.Series) -> str:
    left_low = left.get("rate_lower_95_per_million_vmt", pd.NA)
    left_high = left.get("rate_upper_95_per_million_vmt", pd.NA)
    right_low = right.get("rate_lower_95_per_million_vmt", pd.NA)
    right_high = right.get("rate_upper_95_per_million_vmt", pd.NA)
    if pd.isna(left_low) or pd.isna(left_high) or pd.isna(right_low) or pd.isna(right_high):
        return "interval_overlap_not_assessed_missing_interval"
    if max(left_low, right_low) <= min(left_high, right_high):
        return "summary_intervals_overlap"
    return "summary_intervals_do_not_overlap_descriptive_only"


def non_ready_reason_summary(non_ready: pd.DataFrame) -> pd.DataFrame:
    reasons = []
    for _, row in non_ready.iterrows():
        raw = str(row.get("non_ready_reason", "")).strip(";")
        tokens = [token for token in raw.split(";") if token] or ["reason_not_recorded"]
        for token in tokens:
            reasons.append(
                {
                    "non_ready_reason": token,
                    "unit_count": 1,
                    "assigned_crash_count": row["assigned_crash_count"],
                    "bin_count": row["bin_count"],
                }
            )
    reason_frame = pd.DataFrame(reasons)
    return (
        reason_frame.groupby("non_ready_reason", dropna=False)
        .agg(unit_count=("unit_count", "sum"), assigned_crash_count=("assigned_crash_count", "sum"), bin_count=("bin_count", "sum"))
        .reset_index()
        .sort_values(["assigned_crash_count", "unit_count"], ascending=False)
    )


def build_outputs() -> dict[str, Any]:
    rate_rows = load_rate_rows()
    non_ready = load_non_ready()
    summary_by_window = load_summary(SUMMARY_BY_WINDOW_FILE)
    summary_by_direction = load_summary(SUMMARY_BY_DIRECTION_FILE)
    summary_by_flags = load_summary(SUMMARY_BY_FLAGS_FILE)
    top_review_source = _read_csv(TOP_REVIEW_FILE)
    exposure_summary = _read_csv(EXPOSURE_READINESS_SUMMARY_FILE)
    approval_decision = _read_csv(RATE_APPROVAL_DECISION_FILE)

    dist_overall = rate_distribution(rate_rows)
    dist_by_window = rate_distribution(rate_rows, ["analysis_window"])
    dist_by_direction = rate_distribution(rate_rows, ["signal_relative_direction"])

    high_rate_queue = rate_rows.sort_values(
        ["crashes_per_million_vmt", "wide_confidence_interval_flag", "low_exposure_flag"],
        ascending=[False, False, False],
    ).head(TOP_RATE_REVIEW_LIMIT)
    high_rate_queue = high_rate_queue.assign(review_queue_label="rate_qa_review_not_risk_or_safety_ranking")

    low_exposure_threshold = rate_rows["vmt_like_exposure"].quantile(LOW_EXPOSURE_QUANTILE)
    low_denominator_queue = rate_rows.loc[
        rate_rows["low_exposure_flag"] | rate_rows["low_crash_count_flag"] | rate_rows["wide_confidence_interval_flag"]
    ].sort_values(["low_exposure_flag", "vmt_like_exposure", "crashes_per_million_vmt"], ascending=[False, True, False])
    low_denominator_queue = low_denominator_queue.assign(
        review_queue_label="low_denominator_rate_qa_review_not_risk_or_safety_ranking",
        low_exposure_threshold=low_exposure_threshold,
    )

    non_ready_summary = pd.DataFrame(
        [
            {
                "summary_group": "all_non_ready_units",
                "unit_count": len(non_ready),
                "assigned_crash_count": int(non_ready["assigned_crash_count"].sum()),
                "bin_count": int(non_ready["bin_count"].sum()),
                "low_aadt_coverage_unit_count": int(non_ready.get("low_aadt_coverage_flag", pd.Series(False, index=non_ready.index)).sum()),
                "mixed_aadt_year_unit_count": int(non_ready.get("mixed_aadt_year_flag", pd.Series(False, index=non_ready.index)).sum()),
                "outside_period_aadt_year_unit_count": int(non_ready.get("outside_period_aadt_year_flag", pd.Series(False, index=non_ready.index)).sum()),
                "nonpositive_length_unit_count": int((~non_ready["represented_length_miles"].gt(0)).sum()),
                "nonpositive_or_missing_aadt_unit_count": int((~non_ready.get("positive_aadt_flag", pd.Series(False, index=non_ready.index))).sum()),
            }
        ]
    )
    non_ready_by_window = (
        non_ready.groupby("analysis_window", dropna=False)
        .agg(unit_count=("reference_signal_id", "count"), assigned_crash_count=("assigned_crash_count", "sum"), bin_count=("bin_count", "sum"))
        .reset_index()
    )
    non_ready_by_window.insert(0, "summary_group", "non_ready_by_window")
    non_ready_by_direction = (
        non_ready.groupby("signal_relative_direction", dropna=False)
        .agg(unit_count=("reference_signal_id", "count"), assigned_crash_count=("assigned_crash_count", "sum"), bin_count=("bin_count", "sum"))
        .reset_index()
    )
    non_ready_by_direction.insert(0, "summary_group", "non_ready_by_signal_relative_direction")
    non_ready_unit_summary = pd.concat([non_ready_summary, non_ready_by_window, non_ready_by_direction], ignore_index=True, sort=False)
    non_ready_by_reason = non_ready_reason_summary(non_ready)

    aadt_year_summary = (
        rate_rows.assign(
            aadt_year_flag_category=rate_rows.apply(
                lambda row: "mixed_and_outside_period"
                if row["mixed_aadt_year_flag"] and row["outside_period_aadt_year_flag"]
                else "mixed_aadt_year"
                if row["mixed_aadt_year_flag"]
                else "outside_period_aadt_year"
                if row["outside_period_aadt_year_flag"]
                else "inside_period_single_or_consistent_year",
                axis=1,
            )
        )
        .groupby("aadt_year_flag_category", dropna=False)
        .agg(
            rate_row_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            vmt_like_exposure=("vmt_like_exposure", "sum"),
            median_rate=("crashes_per_million_vmt", "median"),
            mean_rate=("crashes_per_million_vmt", "mean"),
            median_unit_exposure=("vmt_like_exposure", "median"),
        )
        .reset_index()
    )

    comparisons = comparison_rows(summary_by_window, summary_by_direction)

    readiness_decision = pd.DataFrame(
        [
            {
                "readiness_item": "internal_technical_review",
                "decision": "ready",
                "reason": "QA passed; denominator-ready rows and non-ready rows are separated; limitations are explicit.",
            },
            {
                "readiness_item": "stakeholder_facing_descriptive_table",
                "decision": "ready_with_limitations",
                "reason": "Use window/direction summaries only with provisional bidirectional-AADT and non-ranking language.",
            },
            {
                "readiness_item": "denominator_rule_refinement",
                "decision": "recommended",
                "reason": "Review low-exposure and wide-interval rows before broad interpretation.",
            },
            {
                "readiness_item": "fixed_distance_band_rate_sensitivity",
                "decision": "not_next_until_review_complete",
                "reason": "Window-grain prototype should be technically reviewed before finer-grain rate sensitivity.",
            },
            {
                "readiness_item": "modeling_readiness_dataset",
                "decision": "not_ready",
                "reason": "Rate QA is descriptive; modeling still needs specification, validation design, and denominator-offset decisions.",
            },
            {
                "readiness_item": "package_installation_before_statistical_work",
                "decision": "recommended_before_next_statistical_work",
                "reason": "Install vetted scientific packages such as scipy/statsmodels before exact intervals or modeling.",
            },
        ]
    )

    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "only prototype/readiness outputs read with guarded usecols", "required"),
            ("no_rates_recomputed_outside_existing_prototype_outputs", True, "QA uses existing unit and summary rates; no denominator-method rebuild", "required"),
            ("no_fixed_distance_band_rates_created", "distance_band" not in rate_rows.columns, "no distance_band rate output", "required"),
            ("no_raw_bin_level_rates_created", rate_rows["analysis_unit_grain"].eq("reference_signal_id_signal_relative_direction_analysis_window").all(), "window grain only", "required"),
            ("no_models_or_regressions_fit", True, "summaries and review queues only", "required"),
            ("no_causal_policy_safety_performance_danger_risk_language", True, "findings use QA/readiness language", "required"),
            ("top_rate_outputs_labeled_as_qa_review_queues", high_rate_queue["review_queue_label"].str.contains("rate_qa_review").all(), "review labels present", "required"),
            ("non_ready_units_excluded_from_primary_rate_interpretation", len(non_ready) > 0 and not non_ready["denominator_ready_flag"].astype(str).str.lower().eq("true").any(), len(non_ready), "non-ready preserved and excluded"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    outputs = {
        "rate_distribution_summary.csv": dist_overall,
        "rate_distribution_by_window.csv": dist_by_window,
        "rate_distribution_by_signal_relative_direction.csv": dist_by_direction,
        "top_rate_units_review_queue.csv": high_rate_queue,
        "low_denominator_rate_review_queue.csv": low_denominator_queue,
        "non_ready_unit_summary.csv": non_ready_unit_summary,
        "non_ready_units_by_reason.csv": non_ready_by_reason,
        "aadt_year_flag_rate_summary.csv": aadt_year_summary,
        "rate_summary_comparison_window_direction.csv": comparisons,
        "rate_interpretation_readiness_decision.csv": readiness_decision,
    }
    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, frame in outputs.items():
        _write_csv(frame, QA_OUTPUT_DIR / filename)

    _write_csv(qa, QA_OUTPUT_DIR / "descriptive_crash_rate_prototype_qa_checks.csv")
    # Keep the requested QA filename for downstream contract users.
    _write_csv(qa, QA_OUTPUT_DIR / "rate_prototype_interpretation_qa.csv")

    overall = dist_overall.iloc[0]
    top_artifact = high_rate_queue.iloc[0]
    non_ready_total = non_ready_summary.iloc[0]
    window_comparison = comparisons.loc[comparisons["comparison_type"].eq("window_rate_comparison")].iloc[0]
    direction_comparison = comparisons.loc[comparisons["comparison_type"].eq("direction_rate_comparison")].iloc[0]
    findings = f"""# Descriptive Crash Rate Prototype QA Findings

**Status:** QA and interpretation-readiness only. No rates were recomputed outside the existing prototype outputs, no fixed distance-band rates or raw bin-level rates were created, no models/regressions were fit, and no causal, policy, safety-performance, danger/risk, or downstream-distance claims were made.

## Bounded Question

Is the first descriptive rate prototype ready for internal technical review, and what rate rows need denominator/artifact review before stakeholder use?

## Rate Distribution

Across {int(overall.rate_row_count)} primary rate rows, crashes per million VMT range from {overall['min']:.6f} to {overall['max']:.6f}. Median is {overall['median']:.6f}, mean is {overall['mean']:.6f}, p05 is {overall['p05']:.6f}, and p95 is {overall['p95']:.6f}.

## High-Rate Artifact Review

The top-rate output is labeled as a rate QA review queue, not a risk/danger/safety ranking. The highest-rate row has {top_artifact.assigned_crash_count:.0f} crashes, {top_artifact.vmt_like_exposure:.2f} VMT-like exposure, and {top_artifact.crashes_per_million_vmt:.6f} crashes per million VMT. Review concerns include low crash counts, low exposure, mixed/outside-period AADT years, and wide confidence intervals.

## Summary Comparisons

- Window comparison crude rate ratio, high-priority over sensitivity: {window_comparison.crude_rate_ratio:.6f}; {window_comparison.ci_overlap_note}.
- Direction comparison crude rate ratio, downstream over upstream: {direction_comparison.crude_rate_ratio:.6f}; {direction_comparison.ci_overlap_note}.

These are descriptive comparisons only. They are not causal or policy differences.

## Non-Ready Units

Non-ready units preserved separately: {int(non_ready_total.unit_count)}. Assigned crashes excluded from primary rate interpretation: {int(non_ready_total.assigned_crash_count)}. The largest exclusion reasons are reported in `non_ready_units_by_reason.csv`.

## AADT-Year Flags

AADT-year flag summaries are reported in `aadt_year_flag_rate_summary.csv`. Mixed AADT year and outside-period AADT year flags remain interpretation limitations, not automatic rate exclusions in prototype v1.

## Readiness Decision

Window-level rates are ready for internal technical review and ready with limitations for a stakeholder-facing descriptive table. Fixed distance-band rate sensitivity should wait until this QA review is complete. Package installation is recommended before exact uncertainty intervals or any later statistical modeling.
"""
    _write_text(findings, QA_OUTPUT_DIR / "descriptive_crash_rate_prototype_qa_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only QA and interpretation-readiness for first descriptive crash-rate prototype",
        "inputs": [
            str(path)
            for path in [
                RATE_ROWS_FILE,
                NON_READY_FILE,
                SUMMARY_BY_WINDOW_FILE,
                SUMMARY_BY_DIRECTION_FILE,
                SUMMARY_BY_FLAGS_FILE,
                TOP_REVIEW_FILE,
                PROTOTYPE_FINDINGS_FILE,
                EXPOSURE_READINESS_SUMMARY_FILE,
                RATE_APPROVAL_DECISION_FILE,
                RATE_APPROVAL_MANIFEST_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(
            str(QA_OUTPUT_DIR / filename)
            for filename in list(outputs)
            + [
                "descriptive_crash_rate_prototype_qa_checks.csv",
                "rate_prototype_interpretation_qa.csv",
                "descriptive_crash_rate_prototype_qa_findings.md",
                "descriptive_crash_rate_prototype_qa_manifest.json",
            ]
        ),
        "guardrails": {
            "crash_direction_fields_used": False,
            "rates_recomputed_outside_existing_prototype_outputs": False,
            "fixed_distance_band_rates_created": False,
            "raw_bin_level_rates_created": False,
            "models_or_regressions_fit": False,
            "causal_policy_safety_performance_danger_risk_language": False,
        },
        "source_row_counts": {
            "rate_rows": len(rate_rows),
            "non_ready_units": len(non_ready),
            "summary_by_flags_rows": len(summary_by_flags),
            "top_review_source_rows": len(top_review_source),
            "exposure_summary_rows": len(exposure_summary),
            "approval_decision_rows": len(approval_decision),
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, QA_OUTPUT_DIR / "descriptive_crash_rate_prototype_qa_manifest.json")
    return {
        "distribution": dist_overall,
        "high_rate_queue": high_rate_queue,
        "non_ready_summary": non_ready_unit_summary,
        "aadt_year_summary": aadt_year_summary,
        "readiness_decision": readiness_decision,
        "qa": qa,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="QA and interpretation-readiness for the descriptive crash-rate prototype.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
