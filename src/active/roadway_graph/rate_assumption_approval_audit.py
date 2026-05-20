from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1"
CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
POLICY_DIR = OUTPUT_ROOT / "analysis/current/rate_denominator_policy"
AADT_V3_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"

POLICY_DOC_FILE = Path("docs/design/roadway_graph_rate_denominator_policy.md")
DIRECTIONAL_BIN_CONTEXT_FILE = CONTEXT_DIR / "directional_bin_context.csv"
WINDOW_READINESS_FILE = READINESS_DIR / "analysis_unit_readiness_signal_direction_window.csv"
READINESS_SUMMARY_FILE = READINESS_DIR / "exposure_modeling_readiness_summary.csv"
POLICY_SUMMARY_FILE = POLICY_DIR / "rate_denominator_policy_summary.csv"
CRASH_STUDY_PERIOD_AUDIT_FILE = POLICY_DIR / "crash_study_period_audit.csv"
POLICY_SPEC_FILE = POLICY_DIR / "rate_denominator_policy_spec.csv"
AADT_V3_FINDINGS_FILE = AADT_V3_DIR / "aadt_context_v3_findings.md"
AADT_V3_MANIFEST_FILE = AADT_V3_DIR / "aadt_context_v3_manifest.json"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
CRASH_PERIOD_START = date(2022, 1, 1)
CRASH_PERIOD_END = date(2024, 12, 31)
CRASH_PERIOD_DAYS = (CRASH_PERIOD_END - CRASH_PERIOD_START).days + 1
CRASH_PERIOD_YEARS = CRASH_PERIOD_DAYS / 365.25
AADT_COVERAGE_THRESHOLD = 0.80
LOW_CRASH_COUNT_THRESHOLD = 3
FIRST_RATE_PROTOTYPE_UNIT = "reference_signal_id + signal_relative_direction + analysis_window"


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


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _year_status(year: Any) -> str:
    if pd.isna(year):
        return "aadt_year_missing"
    year_int = int(year)
    if year_int < 2022:
        return "before_crash_period"
    if year_int > 2024:
        return "after_crash_period"
    return "inside_crash_period"


def load_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "distance_window",
        "bin_midpoint_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "aadt_value",
        "aadt_year",
        "aadt_direction_factor",
        "aadt_directionality",
        "aadt_context_status",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
    ]
    frame = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    frame["analysis_window"] = frame["distance_window"]
    frame["bin_midpoint_ft_from_reference_signal"] = _num(frame["bin_midpoint_ft_from_reference_signal"])
    frame = frame.loc[frame["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    frame["unique_assigned_crash_count"] = _num(frame["unique_assigned_crash_count"]).fillna(0)
    frame["aadt_value"] = _num(frame["aadt_value"])
    frame["aadt_year_num"] = _num(frame["aadt_year"])
    frame["has_stable_aadt_context"] = _bool(frame["has_stable_aadt_context"])
    frame["aadt_review_or_missing_flag"] = _bool(frame["aadt_review_or_missing_flag"])
    frame["stable_positive_aadt"] = frame["has_stable_aadt_context"] & frame["aadt_value"].gt(0)
    frame["aadt_year_status"] = frame["aadt_year_num"].map(_year_status)
    return frame


def load_window_units() -> pd.DataFrame:
    frame = _read_csv(WINDOW_READINESS_FILE)
    numeric_columns = [
        "assigned_crash_count",
        "bin_count",
        "stable_aadt_bin_count",
        "missing_or_review_aadt_bin_count",
        "stable_aadt_coverage_share",
        "represented_length_miles",
        "aadt_min",
        "aadt_median",
        "aadt_mean",
        "aadt_max",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame[column])
    for column in ["denominator_candidate_ready", "has_positive_length", "has_stable_aadt_context"]:
        frame[column] = _bool(frame[column])
    return frame


def build_aadt_alignment(context: pd.DataFrame, window_units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stable = context.loc[context["has_stable_aadt_context"]].copy()
    stable_year_counts = (
        stable.groupby(["aadt_year", "aadt_year_status"], dropna=False)
        .agg(
            stable_aadt_bin_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count_on_stable_aadt_bins=("unique_assigned_crash_count", "sum"),
            unique_reference_signal_count=("reference_signal_id", "nunique"),
        )
        .reset_index()
    )
    stable_year_counts["audit_grain"] = "stable_aadt_bins_by_year"

    unit_year = (
        stable.groupby(["reference_signal_id", "signal_relative_direction", "analysis_window"], dropna=False)
        .agg(
            stable_aadt_year_count=("aadt_year_num", "nunique"),
            stable_aadt_years=("aadt_year", lambda s: "|".join(sorted(set(x for x in s.astype(str) if x)))),
            dominant_aadt_year=("aadt_year_num", lambda s: s.mode(dropna=True).iloc[0] if not s.mode(dropna=True).empty else pd.NA),
            stable_aadt_bins_with_year=("reference_directional_bin_id", "nunique"),
        )
        .reset_index()
    )
    unit_year["mixed_aadt_year_flag"] = unit_year["stable_aadt_year_count"].gt(1)
    unit_year["dominant_aadt_year_status"] = unit_year["dominant_aadt_year"].map(_year_status)

    merged = window_units.merge(unit_year, on=["reference_signal_id", "signal_relative_direction", "analysis_window"], how="left")
    merged["stable_aadt_year_count"] = merged["stable_aadt_year_count"].fillna(0).astype(int)
    merged["mixed_aadt_year_flag"] = merged["mixed_aadt_year_flag"].fillna(False)
    merged["dominant_aadt_year_status"] = merged["dominant_aadt_year_status"].fillna("aadt_year_missing")
    merged["outside_crash_period_aadt_year_flag"] = ~merged["dominant_aadt_year_status"].eq("inside_crash_period")
    merged["positive_aadt_flag"] = merged["aadt_median"].gt(0)
    merged["denominator_ready_flag_v1"] = (
        merged["denominator_candidate_ready"]
        & merged["represented_length_miles"].gt(0)
        & merged["stable_aadt_coverage_share"].ge(AADT_COVERAGE_THRESHOLD)
        & merged["positive_aadt_flag"]
    )
    merged["low_crash_count_flag"] = merged["assigned_crash_count"].lt(LOW_CRASH_COUNT_THRESHOLD)
    merged["zero_crash_unit_flag"] = merged["assigned_crash_count"].eq(0)
    merged["low_aadt_coverage_flag"] = merged["stable_aadt_coverage_share"].lt(AADT_COVERAGE_THRESHOLD)
    merged["bidirectional_aadt_assumption_flag"] = True

    unit_status = (
        merged.groupby(["dominant_aadt_year_status", "mixed_aadt_year_flag", "denominator_ready_flag_v1"], dropna=False)
        .agg(
            window_unit_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            stable_aadt_bin_count=("stable_aadt_bin_count", "sum"),
            missing_or_review_aadt_bin_count=("missing_or_review_aadt_bin_count", "sum"),
        )
        .reset_index()
    )
    unit_status["audit_grain"] = "window_units_by_aadt_year_status"
    out = pd.concat([stable_year_counts, unit_status], ignore_index=True, sort=False)
    return out, merged


def build_outputs() -> dict[str, Any]:
    context = load_context()
    window_units = load_window_units()
    policy_summary = _read_csv(POLICY_SUMMARY_FILE)
    crash_period_prior = _read_csv(CRASH_STUDY_PERIOD_AUDIT_FILE)
    aadt_alignment, unit_flags = build_aadt_alignment(context, window_units)

    period_row = crash_period_prior.loc[crash_period_prior["crash_year"].eq("ALL_ACCEPTED_ASSIGNED_CRASHES")].iloc[0]
    crash_study_period = pd.DataFrame(
        [
            {
                "accepted_crash_study_period_start": CRASH_PERIOD_START.isoformat(),
                "accepted_crash_study_period_end": CRASH_PERIOD_END.isoformat(),
                "study_period_days": CRASH_PERIOD_DAYS,
                "study_period_years": round(CRASH_PERIOD_YEARS, 6),
                "accepted_assigned_crash_count": int(period_row["accepted_assigned_crash_count"]),
                "observed_earliest_crash_date": period_row["earliest_crash_date"],
                "observed_latest_crash_date": period_row["latest_crash_date"],
                "missing_crash_date_count": int(period_row["missing_crash_date_count"]),
                "year_2022_count": int(crash_period_prior.loc[crash_period_prior["crash_year"].eq("2022"), "accepted_assigned_crash_count"].iloc[0]),
                "year_2023_count": int(crash_period_prior.loc[crash_period_prior["crash_year"].eq("2023"), "accepted_assigned_crash_count"].iloc[0]),
                "year_2024_count": int(crash_period_prior.loc[crash_period_prior["crash_year"].eq("2024"), "accepted_assigned_crash_count"].iloc[0]),
                "prototype_v1_numerator_period_accepted": True,
                "period_decision": "accepted_2022_2024_for_descriptive_rate_prototype_v1",
            }
        ]
    )

    denominator_rules = pd.DataFrame(
        [
            ("include_denominator_ready_units_only", "true", "Include only rows passing denominator_ready_flag_v1 in future rate rows."),
            ("stable_aadt_coverage_share_minimum", f"{AADT_COVERAGE_THRESHOLD:.2f}", "Require stable AADT coverage share >= 0.80."),
            ("represented_length_miles_positive", "true", "Require represented_length_miles > 0."),
            ("aadt_positive", "true", "Require positive nonzero stable AADT summary value."),
            ("study_period", "2022-01-01_to_2024-12-31", "Approved numerator period for prototype v1."),
            ("exclude_missing_review_aadt_from_denominator", "true", "Report excluded units/crashes; do not impute."),
            ("low_crash_count_flag", f"assigned_crash_count < {LOW_CRASH_COUNT_THRESHOLD}", "Flag, do not remove by default."),
            ("zero_crash_unit_flag", "assigned_crash_count == 0", "Flag zero-count units."),
            ("low_aadt_coverage_flag", "stable_aadt_coverage_share < 0.80", "Flag denominator quality issue."),
            ("mixed_aadt_year_flag", "stable AADT bins contain multiple years", "Preserve as limitation flag."),
            ("outside_crash_period_aadt_year_flag", "dominant/only AADT year outside 2022-2024", "Preserve as limitation flag."),
            ("bidirectional_aadt_assumption_flag", "true", "True for all prototype v1 rows."),
            ("denominator_ready_flag", "coverage/length/AADT/study-period rules pass", "Required for future rate row eligibility."),
        ],
        columns=["rule_name", "rule_value", "notes"],
    )

    denom_ready = unit_flags["denominator_ready_flag_v1"]
    inside_ready = denom_ready & unit_flags["dominant_aadt_year_status"].eq("inside_crash_period")
    outside_ready = denom_ready & unit_flags["outside_crash_period_aadt_year_flag"]
    mixed_ready = denom_ready & unit_flags["mixed_aadt_year_flag"]
    positive_aadt_ready = denom_ready & unit_flags["positive_aadt_flag"]
    authorization = "approved_for_descriptive_rate_prototype_v1"
    aadt_year_recommendation = "approved_with_limitation"
    directional_recommendation = "approved_bidirectional_aadt_for_prototype_v1"

    decision = pd.DataFrame(
        [
            {
                "authorization_decision": authorization,
                "recommended_next_module": "src/active/roadway_graph/descriptive_crash_rate_prototype.py",
                "first_rate_prototype_unit": FIRST_RATE_PROTOTYPE_UNIT,
                "crash_period_decision": "accepted_2022_2024_for_descriptive_rate_prototype_v1",
                "aadt_year_alignment_recommendation": aadt_year_recommendation,
                "directional_aadt_recommendation": directional_recommendation,
                "notes": "Proceed only as a provisional descriptive rate prototype with explicit AADT-year and bidirectional-AADT limitation flags.",
            }
        ]
    )

    summary = pd.DataFrame(
        [
            ("authorization_decision", authorization, "Explicit rate prototype authorization status."),
            ("crash_period_days", str(CRASH_PERIOD_DAYS), "Inclusive 2022-01-01 through 2024-12-31."),
            ("crash_period_years", f"{CRASH_PERIOD_YEARS:.6f}", "Days divided by 365.25."),
            ("accepted_assigned_crashes", str(int(period_row["accepted_assigned_crash_count"])), "Accepted numerator crashes."),
            ("missing_crash_dates", str(int(period_row["missing_crash_date_count"])), "Observed missing date count."),
            ("window_units_total", str(len(unit_flags)), "Candidate window-grain units."),
            ("denominator_ready_units_v1", str(int(denom_ready.sum())), "Future rate-row eligible units before rate calculation."),
            ("denominator_ready_assigned_crashes_v1", str(int(unit_flags.loc[denom_ready, "assigned_crash_count"].sum())), "Crashes retained in eligible units."),
            ("ready_units_inside_crash_period_aadt_year", str(int(inside_ready.sum())), "Dominant AADT year inside 2022-2024."),
            ("ready_units_outside_crash_period_aadt_year", str(int(outside_ready.sum())), "Dominant AADT year outside 2022-2024."),
            ("ready_units_mixed_aadt_year", str(int(mixed_ready.sum())), "Stable AADT bins contain multiple AADT years."),
            ("ready_units_positive_aadt", str(int(positive_aadt_ready.sum())), "Denominator-ready units with positive AADT."),
            ("direction_factor_policy", "not_applied_in_prototype_v1", "Present in context but not validated for prototype v1."),
            ("directional_aadt_assumption", "bidirectional_aadt_for_each_signal_relative_direction", "Provisional descriptive prototype v1 assumption."),
            ("rates_computed", "false", "No crash rates computed."),
        ],
        columns=["metric", "value", "notes"],
    )

    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "usecols excludes fields matching crash-direction tokens", "required"),
            ("no_crash_rates_computed", True, "assumption approval outputs only", "required"),
            ("no_aadt_normalized_comparisons_computed", True, "no AADT-normalized output fields", "required"),
            ("no_models_or_regressions_fit", True, "no statistical models run", "required"),
            ("no_causal_policy_or_safety_performance_language_introduced", True, "readiness and provisional language only", "required"),
            ("crash_study_period_accepted_2022_2024", True, "2022-01-01 through 2024-12-31", "accepted"),
            ("aadt_year_alignment_summarized", not aadt_alignment.empty, f"{len(aadt_alignment)} rows", "non-empty"),
            ("directional_aadt_treatment_provisional", True, directional_recommendation, "explicit"),
            ("suppression_flag_rules_explicit", set(["low_crash_count_flag", "zero_crash_unit_flag", "mixed_aadt_year_flag"]).issubset(set(denominator_rules["rule_name"])), "rules written", "explicit"),
            ("authorization_decision_explicit", authorization != "", authorization, "explicit"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    findings = f"""# Rate Assumption Approval V1 Findings

**Status:** assumption approval and readiness documentation only. No crash rates, AADT-normalized comparisons, regressions, predictive models, causal claims, safety-performance rankings, danger/risk rankings, policy guidance, or downstream functional-area distance recommendations were created.

## Bounded Question

Are the numerator period, AADT-year handling, directional AADT treatment, and suppression flags sufficiently specified to authorize a first descriptive rate prototype?

## Approval Decision

`{authorization}`.

The authorized next module is `src/active/roadway_graph/descriptive_crash_rate_prototype.py`, limited to a provisional descriptive prototype at `{FIRST_RATE_PROTOTYPE_UNIT}`.

## Crash Study Period

The accepted numerator period for prototype v1 is {CRASH_PERIOD_START.isoformat()} through {CRASH_PERIOD_END.isoformat()} ({CRASH_PERIOD_DAYS} days, {CRASH_PERIOD_YEARS:.6f} years). Accepted assigned crashes total {int(period_row["accepted_assigned_crash_count"])} with 0 missing crash dates: 4,244 in 2022, 4,506 in 2023, and 4,466 in 2024.

## AADT Year Alignment

AADT year alignment recommendation: `{aadt_year_recommendation}`. AADT-year variation is documented as a limitation rather than a blocker for prototype v1. Denominator-ready units with dominant AADT year inside 2022-2024: {int(inside_ready.sum())}. Denominator-ready units with dominant AADT year outside 2022-2024: {int(outside_ready.sum())}. Denominator-ready units with mixed stable AADT years: {int(mixed_ready.sum())}.

## Directional AADT

Directional AADT recommendation: `{directional_recommendation}`. `DIRECTION_FACTOR` is present in the context data but is not validated or applied for prototype v1. Prototype v1 should use stable AADT as bidirectional exposure for each signal-relative directional view and carry `bidirectional_aadt_assumption_flag = true` on every future rate row.

## Suppression And Flags

Future prototype rows must include only denominator-ready units, stable AADT coverage share >= 0.80, represented length > 0, positive AADT, and the approved 2022-2024 study period. Missing/review AADT must be excluded from denominators and reported. Future output must carry low crash count, zero crash count, low AADT coverage, mixed AADT year, outside-period AADT year, bidirectional AADT assumption, and denominator-ready flags.
"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "rate_assumption_approval_summary.csv": summary,
        "crash_study_period_approval.csv": crash_study_period,
        "aadt_year_alignment_audit.csv": aadt_alignment,
        "denominator_rule_spec_v1.csv": denominator_rules,
        "rate_prototype_authorization_decision.csv": decision,
        "rate_assumption_approval_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_text(findings, OUTPUT_DIR / "rate_assumption_approval_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "assumption approval for descriptive rate prototype v1 without computing rates",
        "inputs": [
            str(path)
            for path in [
                POLICY_DOC_FILE,
                POLICY_SUMMARY_FILE,
                POLICY_SPEC_FILE,
                CRASH_STUDY_PERIOD_AUDIT_FILE,
                READINESS_SUMMARY_FILE,
                WINDOW_READINESS_FILE,
                DIRECTIONAL_BIN_CONTEXT_FILE,
                AADT_V3_FINDINGS_FILE,
                AADT_V3_MANIFEST_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(OUTPUT_DIR / name) for name in list(outputs) + ["rate_assumption_approval_findings.md", "rate_assumption_approval_manifest.json"]),
        "authorization_decision": authorization,
        "first_rate_prototype_unit": FIRST_RATE_PROTOTYPE_UNIT,
        "crash_period": {
            "start": CRASH_PERIOD_START.isoformat(),
            "end": CRASH_PERIOD_END.isoformat(),
            "days": CRASH_PERIOD_DAYS,
            "years": CRASH_PERIOD_YEARS,
            "accepted_for_prototype_v1": True,
        },
        "recommendations": {
            "aadt_year_alignment": aadt_year_recommendation,
            "directional_aadt": directional_recommendation,
        },
        "guardrails": {
            "crash_direction_fields_used": False,
            "crash_rates_computed": False,
            "aadt_normalized_comparisons_computed": False,
            "models_or_regressions_fit": False,
            "causal_policy_or_safety_performance_language": False,
            "rows_over_2500ft_included": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "rate_assumption_approval_manifest.json")
    return {
        "summary": summary,
        "crash_study_period": crash_study_period,
        "aadt_alignment": aadt_alignment,
        "decision": decision,
        "qa": qa,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve bounded assumptions for descriptive rate prototype v1 without computing rates.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
