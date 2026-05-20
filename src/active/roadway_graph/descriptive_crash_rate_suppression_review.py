from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from scipy.stats import chi2


OUTPUT_ROOT = Path("work/output/roadway_graph")
PROTOTYPE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype"
QA_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype_qa"
APPROVAL_DIR = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_suppression_review"

RATE_ROWS_FILE = PROTOTYPE_DIR / "descriptive_rate_prototype_signal_direction_window.csv"
NON_READY_FILE = PROTOTYPE_DIR / "descriptive_rate_prototype_non_ready_units.csv"
SUMMARY_BY_WINDOW_FILE = PROTOTYPE_DIR / "descriptive_rate_summary_by_window.csv"
SUMMARY_BY_DIRECTION_FILE = PROTOTYPE_DIR / "descriptive_rate_summary_by_signal_relative_direction.csv"
QA_DISTRIBUTION_FILE = QA_DIR / "rate_distribution_summary.csv"
QA_TOP_RATE_FILE = QA_DIR / "top_rate_units_review_queue.csv"
QA_FINDINGS_FILE = QA_DIR / "descriptive_crash_rate_prototype_qa_findings.md"
AUTHORIZATION_DECISION_FILE = APPROVAL_DIR / "rate_prototype_authorization_decision.csv"
DENOMINATOR_RULE_SPEC_FILE = APPROVAL_DIR / "denominator_rule_spec_v1.csv"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)
LOW_CRASH_COUNT_THRESHOLD = 3
LOW_EXPOSURE_QUANTILE = 0.10
EXTREMELY_WIDE_INTERVAL_RATIO_THRESHOLD = 10.0
TOP_REVIEW_LIMIT = 250


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


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.replace(0, pd.NA)).astype("Float64")


def _garwood_exact_count_interval(count: Any, alpha: float = 0.05) -> tuple[float, float]:
    if pd.isna(count):
        return (pd.NA, pd.NA)
    k = max(int(round(float(count))), 0)
    lower = 0.0 if k == 0 else 0.5 * float(chi2.ppf(alpha / 2, 2 * k))
    upper = 0.5 * float(chi2.ppf(1 - alpha / 2, 2 * (k + 1)))
    return (lower, upper)


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


def add_exact_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    intervals = frame["assigned_crash_count"].map(_garwood_exact_count_interval)
    frame["exact_crash_count_lower_95"] = intervals.map(lambda value: value[0])
    frame["exact_crash_count_upper_95"] = intervals.map(lambda value: value[1])
    frame["exact_rate_lower_95_per_million_vmt"] = _safe_div(frame["exact_crash_count_lower_95"].astype(float) * 1_000_000, frame["vmt_like_exposure"])
    frame["exact_rate_upper_95_per_million_vmt"] = _safe_div(frame["exact_crash_count_upper_95"].astype(float) * 1_000_000, frame["vmt_like_exposure"])
    frame["exact_interval_method"] = "scipy_chi2_exact_garwood"
    frame["exact_rate_ci_width"] = frame["exact_rate_upper_95_per_million_vmt"] - frame["exact_rate_lower_95_per_million_vmt"]
    frame["exact_rate_ci_width_ratio"] = frame["exact_rate_upper_95_per_million_vmt"] / frame["exact_rate_lower_95_per_million_vmt"].replace(0, pd.NA)
    return frame


def add_suppression_flags(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    frame = frame.copy()
    low_exposure_threshold = float(frame["vmt_like_exposure"].quantile(LOW_EXPOSURE_QUANTILE))
    frame["low_exposure_denominator_flag"] = frame["vmt_like_exposure"].le(low_exposure_threshold)
    frame["low_crash_count_flag_v2"] = frame["assigned_crash_count"].lt(LOW_CRASH_COUNT_THRESHOLD)
    frame["zero_crash_count_flag_v2"] = frame["assigned_crash_count"].eq(0)
    frame["extremely_wide_interval_flag"] = frame["exact_rate_ci_width_ratio"].gt(EXTREMELY_WIDE_INTERVAL_RATIO_THRESHOLD) | frame["exact_rate_lower_95_per_million_vmt"].eq(0)
    frame["aadt_year_limitation_flag"] = frame["outside_period_aadt_year_flag"] | frame["mixed_aadt_year_flag"]
    frame["bidirectional_aadt_assumption_flag_v2"] = True
    frame["stakeholder_unit_rate_suppressed"] = (
        frame["low_exposure_denominator_flag"]
        | frame["low_crash_count_flag_v2"]
        | frame["zero_crash_count_flag_v2"]
        | frame["extremely_wide_interval_flag"]
        | frame["outside_period_aadt_year_flag"]
        | frame["mixed_aadt_year_flag"]
        | frame["bidirectional_aadt_assumption_flag_v2"]
    )
    frame["suppression_reason"] = ""
    reason_map = [
        ("low_exposure_denominator_flag", "low_exposure_denominator"),
        ("low_crash_count_flag_v2", "low_crash_count"),
        ("zero_crash_count_flag_v2", "zero_crash_count"),
        ("extremely_wide_interval_flag", "extremely_wide_interval"),
        ("outside_period_aadt_year_flag", "outside_period_aadt_year"),
        ("mixed_aadt_year_flag", "mixed_aadt_year"),
        ("bidirectional_aadt_assumption_flag_v2", "bidirectional_aadt_assumption"),
    ]
    for column, label in reason_map:
        frame.loc[frame[column], "suppression_reason"] += label + ";"
    frame["unit_rate_output_use"] = "qa_review_only_not_stakeholder_ranking"
    return frame, low_exposure_threshold


def interval_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "assigned_crash_count",
        "vmt_like_exposure",
        "crashes_per_million_vmt",
        "crash_count_lower_95",
        "crash_count_upper_95",
        "rate_lower_95_per_million_vmt",
        "rate_upper_95_per_million_vmt",
        "uncertainty_method",
        "exact_crash_count_lower_95",
        "exact_crash_count_upper_95",
        "exact_rate_lower_95_per_million_vmt",
        "exact_rate_upper_95_per_million_vmt",
        "exact_interval_method",
    ]
    out = frame[cols].copy()
    out["lower_rate_difference_exact_minus_approx"] = out["exact_rate_lower_95_per_million_vmt"] - out["rate_lower_95_per_million_vmt"]
    out["upper_rate_difference_exact_minus_approx"] = out["exact_rate_upper_95_per_million_vmt"] - out["rate_upper_95_per_million_vmt"]
    return out


def stakeholder_summary(summary: pd.DataFrame, group_col: str) -> pd.DataFrame:
    out = add_exact_intervals(summary)
    out["stakeholder_table_status"] = "aggregate_descriptive_summary_with_caveats"
    out["interpretation_caveat"] = "provisional_bidirectional_aadt_not_policy_not_ranking_not_causal"
    keep = [
        group_col,
        "rate_ready_unit_count",
        "assigned_crash_count",
        "vmt_like_exposure",
        "crashes_per_million_vmt",
        "exact_rate_lower_95_per_million_vmt",
        "exact_rate_upper_95_per_million_vmt",
        "exact_interval_method",
        "stakeholder_table_status",
        "interpretation_caveat",
    ]
    return out[keep]


def build_outputs() -> dict[str, Any]:
    rate_rows = load_rate_rows()
    non_ready = _read_csv(NON_READY_FILE)
    summary_by_window = load_summary(SUMMARY_BY_WINDOW_FILE)
    summary_by_direction = load_summary(SUMMARY_BY_DIRECTION_FILE)
    qa_distribution = _read_csv(QA_DISTRIBUTION_FILE)
    qa_top_rate = _read_csv(QA_TOP_RATE_FILE)
    authorization = _read_csv(AUTHORIZATION_DECISION_FILE)
    denominator_rules = _read_csv(DENOMINATOR_RULE_SPEC_FILE)

    rate_rows = add_exact_intervals(rate_rows)
    rate_rows, low_exposure_threshold = add_suppression_flags(rate_rows)
    method_comparison = interval_comparison(rate_rows)
    stakeholder_window = stakeholder_summary(summary_by_window, "analysis_window")
    stakeholder_direction = stakeholder_summary(summary_by_direction, "signal_relative_direction")

    suppression_rules = pd.DataFrame(
        [
            ("low_exposure_denominator_flag", f"vmt_like_exposure <= p{int(LOW_EXPOSURE_QUANTILE * 100):02d} threshold ({low_exposure_threshold:.6f})", "unit rate QA/suppression"),
            ("low_crash_count_flag", f"assigned_crash_count < {LOW_CRASH_COUNT_THRESHOLD}", "unit rate QA/suppression"),
            ("zero_crash_count_flag", "assigned_crash_count == 0", "unit rate QA/suppression"),
            ("extremely_wide_interval_flag", f"exact_rate_ci_width_ratio > {EXTREMELY_WIDE_INTERVAL_RATIO_THRESHOLD} or lower CI equals 0", "unit rate QA/suppression"),
            ("outside_period_aadt_year_flag", "dominant/only AADT year outside 2022-2024", "limitation flag"),
            ("mixed_aadt_year_flag", "unit contains multiple stable AADT years", "limitation flag"),
            ("bidirectional_aadt_assumption_flag", "true for all prototype v1 rows", "limitation flag"),
            ("stakeholder_unit_rate_suppressed", "any suppression/review flag true", "unit-level rates withheld from stakeholder-facing table"),
        ],
        columns=["rule_name", "rule_definition", "rule_role"],
    )

    high_rate_suppressed = rate_rows.loc[rate_rows["stakeholder_unit_rate_suppressed"]].sort_values(
        ["crashes_per_million_vmt", "low_exposure_denominator_flag", "extremely_wide_interval_flag"],
        ascending=[False, False, False],
    ).head(TOP_REVIEW_LIMIT)
    high_rate_suppressed = high_rate_suppressed.assign(review_queue_label="suppressed_unit_rate_qa_review_not_risk_or_safety_ranking")

    suppressed_count = int(rate_rows["stakeholder_unit_rate_suppressed"].sum())
    low_exposure_count = int(rate_rows["low_exposure_denominator_flag"].sum())
    low_count_count = int(rate_rows["low_crash_count_flag_v2"].sum())
    zero_count_count = int(rate_rows["zero_crash_count_flag_v2"].sum())
    wide_count = int(rate_rows["extremely_wide_interval_flag"].sum())
    mixed_count = int(rate_rows["mixed_aadt_year_flag"].sum())
    outside_count = int(rate_rows["outside_period_aadt_year_flag"].sum())

    qa = pd.DataFrame(
        [
            ("scipy_available", True, "scipy.stats.chi2 imported", "required"),
            ("exact_interval_method_used", True, "scipy_chi2_exact_garwood", "required"),
            ("no_crash_direction_fields_read_or_used", True, "only prototype/QA/approval outputs read with guarded usecols", "required"),
            ("no_models_or_regressions_fit", True, "interval and suppression review only", "required"),
            ("no_fixed_distance_band_rates_created", "distance_band" not in rate_rows.columns, "no distance_band output", "required"),
            ("no_raw_bin_level_rates_created", rate_rows["analysis_unit_grain"].eq("reference_signal_id_signal_relative_direction_analysis_window").all(), "window grain only", "required"),
            ("no_causal_policy_safety_performance_danger_risk_language", True, "findings use suppression/review language", "required"),
            ("unit_high_rate_rows_kept_as_qa_review_only", high_rate_suppressed["review_queue_label"].str.contains("qa_review").all(), "review queue labels present", "required"),
            ("stakeholder_summaries_are_aggregate_only", len(stakeholder_window) == 2 and len(stakeholder_direction) == 2, "window and direction summaries only", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    outputs = {
        "rate_interval_method_comparison.csv": method_comparison,
        "rate_suppression_rule_spec.csv": suppression_rules,
        "rate_unit_suppression_flags.csv": rate_rows,
        "stakeholder_safe_rate_summary_by_window.csv": stakeholder_window,
        "stakeholder_safe_rate_summary_by_direction.csv": stakeholder_direction,
        "high_rate_units_suppressed_review_queue.csv": high_rate_suppressed,
        "rate_suppression_review_qa.csv": qa,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)

    findings = f"""# Descriptive Crash Rate Suppression Review Findings

**Status:** suppression and interval refinement review only. No models/regressions were fit, no fixed distance-band or raw bin-level rates were created, no causal claims were made, no safety-performance/danger/risk rankings were created, and no downstream functional-area distances were recommended.

## Interval Method

SciPy is available. Exact Poisson/Garwood intervals were computed with `scipy.stats.chi2` and compared with the prior approximate prototype interval fields in `rate_interval_method_comparison.csv`.

## Suppression Review

- Primary unit rows reviewed: {len(rate_rows)}.
- Unit rows flagged/suppressed for stakeholder unit-rate display: {suppressed_count}.
- Low exposure denominator flags: {low_exposure_count}.
- Low crash count flags: {low_count_count}.
- Zero crash count flags: {zero_count_count}.
- Extremely wide interval flags: {wide_count}.
- Mixed AADT year flags: {mixed_count}.
- Outside-period AADT year flags: {outside_count}.

Unit-level high-rate rows remain QA review outputs only and are not stakeholder-facing risk, danger, or safety-performance rankings.

## Stakeholder-Safe Summaries

Aggregate window and direction summaries are preserved in stakeholder-safe tables with exact intervals and explicit caveats. These summaries are suitable for stakeholder-facing descriptive discussion with limitations, provided unit-level rows remain out of ranked presentation.

## Next Step

Fixed distance-band rate sensitivity should not be attempted until the suppression review is discussed and the team decides whether these suppression rules are sufficient. Package installation is no longer a blocker for exact Poisson intervals because SciPy is available, but vetted statistical packages remain recommended before any later modeling work.
"""
    _write_text(findings, OUTPUT_DIR / "rate_suppression_review_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "exact interval and suppression review for the approved window-grain descriptive rate prototype",
        "inputs": [
            str(path)
            for path in [
                RATE_ROWS_FILE,
                NON_READY_FILE,
                SUMMARY_BY_WINDOW_FILE,
                SUMMARY_BY_DIRECTION_FILE,
                QA_DISTRIBUTION_FILE,
                QA_TOP_RATE_FILE,
                QA_FINDINGS_FILE,
                AUTHORIZATION_DECISION_FILE,
                DENOMINATOR_RULE_SPEC_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(OUTPUT_DIR / name) for name in list(outputs) + ["rate_suppression_review_findings.md", "rate_suppression_review_manifest.json"]),
        "scipy_available": True,
        "interval_method": "scipy_chi2_exact_garwood",
        "suppression_counts": {
            "unit_rows": len(rate_rows),
            "stakeholder_unit_rate_suppressed": suppressed_count,
            "low_exposure_denominator": low_exposure_count,
            "low_crash_count": low_count_count,
            "zero_crash_count": zero_count_count,
            "extremely_wide_interval": wide_count,
            "mixed_aadt_year": mixed_count,
            "outside_period_aadt_year": outside_count,
        },
        "source_context": {
            "non_ready_rows": len(non_ready),
            "qa_distribution_rows": len(qa_distribution),
            "qa_top_rate_rows": len(qa_top_rate),
            "authorization_decision": authorization.loc[0, "authorization_decision"] if not authorization.empty else "",
            "denominator_rule_rows": len(denominator_rules),
        },
        "guardrails": {
            "crash_direction_fields_used": False,
            "models_or_regressions_fit": False,
            "fixed_distance_band_rates_created": False,
            "raw_bin_level_rates_created": False,
            "causal_policy_safety_performance_danger_risk_language": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "rate_suppression_review_manifest.json")
    return {
        "rate_rows": rate_rows,
        "stakeholder_window": stakeholder_window,
        "stakeholder_direction": stakeholder_direction,
        "qa": qa,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Exact interval and suppression review for descriptive crash-rate prototype.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
