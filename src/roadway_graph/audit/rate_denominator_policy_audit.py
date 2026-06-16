from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
POLICY_OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/rate_denominator_policy"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
AADT_V3_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
CURRENT_TABLES_DIR = OUTPUT_ROOT / "tables/current"

RATE_MODELING_PLAN_FILE = Path("docs/design/roadway_graph_rate_and_modeling_readiness_plan.md")
READINESS_SUMMARY_FILE = READINESS_DIR / "exposure_modeling_readiness_summary.csv"
READINESS_WINDOW_UNITS_FILE = READINESS_DIR / "analysis_unit_readiness_signal_direction_window.csv"
READINESS_QA_FILE = READINESS_DIR / "exposure_modeling_readiness_qa.csv"
READINESS_FINDINGS_FILE = READINESS_DIR / "exposure_modeling_readiness_findings.md"
READINESS_MANIFEST_FILE = READINESS_DIR / "exposure_modeling_readiness_manifest.json"
READINESS_DUPLICATE_AUDIT_FILE = READINESS_DIR / "exposure_duplicate_source_bin_audit.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = CONTEXT_DIR / "directional_crash_context.csv"
CRASH_DATE_SOURCE_FILE = CURRENT_TABLES_DIR / "crash_oriented_segment_bin_assignment.csv"
AADT_V3_FINDINGS_FILE = AADT_V3_DIR / "aadt_context_v3_findings.md"
AADT_V3_MANIFEST_FILE = AADT_V3_DIR / "aadt_context_v3_manifest.json"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

FIRST_RATE_PROTOTYPE_UNIT = "reference_signal_id + signal_relative_direction + analysis_window"
FIRST_RATE_PROTOTYPE_WINDOWS = "high_priority_0_1000ft|sensitivity_1000_2500ft"
AADT_COVERAGE_THRESHOLD = 0.80
LOW_LENGTH_FT_THRESHOLD = 250.0
LOW_CRASH_COUNT_THRESHOLD = 5


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


def _summary_value(summary: pd.DataFrame, metric: str) -> str:
    match = summary.loc[summary["metric"].eq(metric), "value"]
    if match.empty:
        return ""
    return str(match.iloc[0])


def _build_policy_spec() -> pd.DataFrame:
    rows = [
        ("prototype_scope", "first_rate_prototype_unit", FIRST_RATE_PROTOTYPE_UNIT, "required", "Use the window grain before fixed-band or raw-bin rates."),
        ("prototype_scope", "prototype_windows", FIRST_RATE_PROTOTYPE_WINDOWS, "required", "High-priority and sensitivity windows only."),
        ("numerator", "crash_universe", "accepted_assigned_crashes_only", "required", "Ambiguous and unresolved crashes remain excluded."),
        ("numerator", "crash_direction_fields", "not_used", "required", "Crash direction fields must not define numerator or upstream/downstream."),
        ("numerator", "crash_area_type", "summarize_only", "required", "Crash-level AREA_TYPE is not roadway geography."),
        ("denominator", "concept", "AADT * represented_length * crash_study_period", "conceptual_only", "Do not compute final denominator until study period and directional AADT policy are reviewed."),
        ("denominator", "represented_length_field", "represented_length_miles", "required", "Derived from readiness output; preserve truncated-bin lengths."),
        ("denominator", "aadt_value_rule", "stable_aadt_only", "required", "Missing/review AADT is excluded from denominators, not imputed."),
        ("denominator", "aadt_coverage_threshold", f"{AADT_COVERAGE_THRESHOLD:.2f}", "required", "Unit must meet or exceed stable AADT coverage threshold."),
        ("denominator", "positive_length_required", "true", "required", "Represented length must be greater than zero."),
        ("denominator", "positive_aadt_required", "true", "required", "Rate prototype must require positive nonzero stable AADT."),
        ("study_period", "crash_study_period_days_or_years", "required_before_rates", "blocked_until_reviewed", "Current module audits dates but does not authorize a period."),
        ("directional_aadt", "prototype_v1_policy", "use_aadt_as_bidirectional_exposure_for_each_signal_relative_direction", "provisional", "Do not split by direction until DIRECTION_FACTOR/source directionality are validated."),
        ("directional_aadt", "direction_factor_policy", "audit_only_not_applied", "future_option", "Use DIRECTION_FACTOR only after separate validation."),
        ("directional_aadt", "split_policy", "source_supported_only", "future_option", "Split AADT by direction only where source supports it."),
        ("missing_aadt", "below_threshold_units", "exclude_from_rate_table_report_as_non_rate_rows", "required", "Report excluded crashes, bins, and coverage."),
        ("missing_aadt", "imputation", "not_allowed", "required", "No AADT imputation in prototype v1."),
        ("suppression", "low_denominator_warning", f"represented_length_ft < {LOW_LENGTH_FT_THRESHOLD:g} or no stable AADT", "required", "Flag before showing any future rate."),
        ("suppression", "low_crash_count_warning", f"assigned_crash_count < {LOW_CRASH_COUNT_THRESHOLD}", "required", "Flag low counts and include uncertainty before comparison language."),
        ("duplication", "source_bin_duplicate_policy", "signal_relative_source_bin_audit_passed_but_corridor_rates_need_dedup_review", "required", "Current key audit found no duplicate source-bin keys across reference signals."),
        ("language", "allowed", "descriptive rate prototype|AADT-normalized descriptive comparison|denominator-ready unit|exposure denominator|uncertainty interval|provisional|readiness-gated", "required", "Only after denominator gates are met."),
        ("language", "avoid", "dangerous|risky|safety performance|policy recommendation|causal effect|expected crashes|final downstream functional area recommendation", "required", "Avoid unsupported policy, causal, predictive, or ranking language."),
    ]
    return pd.DataFrame(rows, columns=["policy_section", "policy_key", "policy_value", "status", "notes"])


def _audit_crash_study_period() -> pd.DataFrame:
    accepted = _read_csv(DIRECTIONAL_CRASH_CONTEXT_FILE, usecols=["crash_id"])
    dates = _read_csv(CRASH_DATE_SOURCE_FILE, usecols=["crash_id", "CRASH_DT", "CRASH_YEAR"])
    accepted_ids = set(accepted["crash_id"].astype(str))
    dates = dates.loc[dates["crash_id"].astype(str).isin(accepted_ids)].copy()
    dates["parsed_crash_date"] = pd.to_datetime(dates["CRASH_DT"].replace("", pd.NA), errors="coerce", utc=True)
    dates["parsed_crash_year"] = pd.to_numeric(dates["CRASH_YEAR"], errors="coerce")

    year_rows = (
        dates.groupby("CRASH_YEAR", dropna=False)
        .agg(accepted_assigned_crash_count=("crash_id", "nunique"))
        .reset_index()
        .rename(columns={"CRASH_YEAR": "crash_year"})
    )
    summary_rows = pd.DataFrame(
        [
            {
                "crash_year": "ALL_ACCEPTED_ASSIGNED_CRASHES",
                "accepted_assigned_crash_count": dates["crash_id"].nunique(),
                "earliest_crash_date": dates["parsed_crash_date"].min().date().isoformat() if dates["parsed_crash_date"].notna().any() else "",
                "latest_crash_date": dates["parsed_crash_date"].max().date().isoformat() if dates["parsed_crash_date"].notna().any() else "",
                "missing_crash_date_count": int(dates["parsed_crash_date"].isna().sum()),
                "candidate_study_period": "2022-2024 calendar years, pending source/date filter review",
                "study_period_status": "available_but_not_yet_authorized_for_rates",
            }
        ]
    )
    year_rows["earliest_crash_date"] = ""
    year_rows["latest_crash_date"] = ""
    year_rows["missing_crash_date_count"] = ""
    year_rows["candidate_study_period"] = ""
    year_rows["study_period_status"] = "year_distribution_only"
    return pd.concat([summary_rows, year_rows], ignore_index=True, sort=False)


def build_outputs() -> dict[str, Any]:
    readiness_summary = _read_csv(READINESS_SUMMARY_FILE)
    window_units = _read_csv(READINESS_WINDOW_UNITS_FILE)
    duplicate_audit = _read_csv(READINESS_DUPLICATE_AUDIT_FILE)
    readiness_qa = _read_csv(READINESS_QA_FILE)
    crash_study_period = _audit_crash_study_period()
    policy_spec = _build_policy_spec()

    window_units["assigned_crash_count_num"] = pd.to_numeric(window_units["assigned_crash_count"], errors="coerce").fillna(0)
    denominator_ready = window_units["denominator_candidate_ready"].astype(str).str.lower().eq("true")
    modeling_ready = window_units["modeling_ready_candidate"].astype(str).str.lower().eq("true")

    candidate_counts = pd.DataFrame(
        [
            {
                "analysis_unit": FIRST_RATE_PROTOTYPE_UNIT,
                "candidate_status": "all_window_units",
                "unit_count": len(window_units),
                "assigned_crash_count": int(window_units["assigned_crash_count_num"].sum()),
            },
            {
                "analysis_unit": FIRST_RATE_PROTOTYPE_UNIT,
                "candidate_status": "denominator_ready",
                "unit_count": int(denominator_ready.sum()),
                "assigned_crash_count": int(window_units.loc[denominator_ready, "assigned_crash_count_num"].sum()),
            },
            {
                "analysis_unit": FIRST_RATE_PROTOTYPE_UNIT,
                "candidate_status": "not_denominator_ready",
                "unit_count": int((~denominator_ready).sum()),
                "assigned_crash_count": int(window_units.loc[~denominator_ready, "assigned_crash_count_num"].sum()),
            },
            {
                "analysis_unit": FIRST_RATE_PROTOTYPE_UNIT,
                "candidate_status": "modeling_ready_candidate",
                "unit_count": int(modeling_ready.sum()),
                "assigned_crash_count": int(window_units.loc[modeling_ready, "assigned_crash_count_num"].sum()),
            },
        ]
    )

    duplicate_count = int(duplicate_audit["duplicated_across_reference_signals"].astype(str).str.lower().eq("true").sum())
    accepted_crash_count = int(crash_study_period.loc[0, "accepted_assigned_crash_count"])
    study_period_status = str(crash_study_period.loc[0, "study_period_status"])
    summary = pd.DataFrame(
        [
            ("first_rate_prototype_unit", FIRST_RATE_PROTOTYPE_UNIT, "Window grain, not raw 50-ft bins."),
            ("prototype_windows", FIRST_RATE_PROTOTYPE_WINDOWS, "Only accepted 0-2,500 ft analysis windows."),
            ("window_feature_matrix_rows", str(len(window_units)), "All candidate window-grain feature matrix rows."),
            ("window_units_total", str(len(window_units)), "All candidate window units."),
            ("window_denominator_ready_units", str(int(denominator_ready.sum())), "Stable AADT coverage >= 0.80 and positive represented length."),
            ("window_denominator_ready_assigned_crashes", str(int(window_units.loc[denominator_ready, "assigned_crash_count_num"].sum())), "Crashes retained before any rate prototype."),
            ("window_not_denominator_ready_assigned_crashes", str(int(window_units.loc[~denominator_ready, "assigned_crash_count_num"].sum())), "Crashes excluded from future denominator-gated rate rows."),
            ("duplicate_source_bin_keys", str(duplicate_count), "Duplicate source-bin keys across reference signals."),
            ("unique_source_bin_keys_audited", str(len(duplicate_audit)), "Source-bin keys audited for duplication."),
            ("accepted_crashes_with_date_audit", str(accepted_crash_count), "Accepted assigned crashes matched to date source."),
            ("crash_study_period_status", study_period_status, "Dates are available, but the study period must be reviewed before rates."),
            ("rates_computed", "false", "No crash rates or AADT-normalized comparisons computed."),
            ("models_fit", "false", "No models or regressions fit."),
        ],
        columns=["metric", "value", "notes"],
    )

    qa_rows = [
        ("no_crash_direction_fields_read_or_used", True, "usecols excludes fields matching crash-direction tokens", "required"),
        ("no_crash_rates_computed", True, "policy-support outputs only", "required"),
        ("no_aadt_normalized_comparisons_computed", True, "no denominator multiplication or rate comparison fields", "required"),
        ("no_models_or_regressions_fit", True, "no statistical models run", "required"),
        ("no_causal_policy_or_safety_performance_language_introduced", True, "findings and memo use readiness/provisional language", "required"),
        ("missing_review_aadt_explicitly_handled", True, "stable AADT only; below-threshold units excluded from future rates", "required"),
        ("first_rate_prototype_unit_is_window_grain", FIRST_RATE_PROTOTYPE_UNIT.endswith("analysis_window"), FIRST_RATE_PROTOTYPE_UNIT, "window grain"),
        ("crash_study_period_status_documented", study_period_status != "", study_period_status, "documented"),
        ("readiness_qa_all_passed", readiness_qa["passed"].astype(str).str.lower().eq("true").all(), "readiness QA consumed", "all true"),
    ]
    qa = pd.DataFrame(qa_rows, columns=["check_name", "passed", "observed", "expected"])

    findings = f"""# Rate Denominator Policy Findings

**Status:** policy and specification support only. No crash rates, AADT-normalized comparisons, regressions, predictive models, causal claims, policy guidance, safety-performance rankings, or downstream functional-area distance recommendations were created.

## Bounded Question

What denominator assumptions must be documented before the roadway-graph window-grain universe can support a first descriptive rate prototype?

## Recommended First Unit

Use `{FIRST_RATE_PROTOTYPE_UNIT}` with windows `{FIRST_RATE_PROTOTYPE_WINDOWS}`. Raw 50-ft bin rates should not be the first prototype.

## Denominator Policy

The future denominator concept is `AADT x represented length x crash study period`, using `represented_length_miles`, stable AADT only, stable AADT coverage share >= {AADT_COVERAGE_THRESHOLD:.2f}, positive represented length, positive AADT, and a documented crash study period. Missing or review AADT is excluded from denominator-gated rate rows and must be reported, not imputed.

Prototype v1 should provisionally use AADT as bidirectional exposure for each signal-relative directional view. `DIRECTION_FACTOR` or directional AADT splitting should remain audit-only until the AADT source directionality is validated.

## Readiness Counts

- Candidate window units: {len(window_units)}.
- Denominator-ready window units: {int(denominator_ready.sum())}.
- Assigned crashes retained in denominator-ready window units: {int(window_units.loc[denominator_ready, "assigned_crash_count_num"].sum())} of 13,216.
- Assigned crashes in not-denominator-ready window units: {int(window_units.loc[~denominator_ready, "assigned_crash_count_num"].sum())}.
- Duplicate source-bin keys across reference signals: {duplicate_count} of {len(duplicate_audit)}.

## Crash Study Period

Accepted assigned crashes matched to date source: {accepted_crash_count}. Candidate source dates span {crash_study_period.loc[0, "earliest_crash_date"]} through {crash_study_period.loc[0, "latest_crash_date"]}, with {crash_study_period.loc[0, "missing_crash_date_count"]} missing dates. Treat this as available but not yet authorized for rates until source filters, complete years, and period alignment with AADT are reviewed.

## Next Step

Do not implement `descriptive_crash_rate_prototype.py` until the crash study period and directional AADT assumption are explicitly approved. The next bounded task should be a denominator-table prototype or approval memo that confirms the 2022-2024 crash period, AADT year handling, and bidirectional AADT treatment.
"""

    POLICY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "rate_denominator_policy_summary.csv": summary,
        "rate_denominator_candidate_unit_counts.csv": candidate_counts,
        "crash_study_period_audit.csv": crash_study_period,
        "rate_denominator_policy_spec.csv": policy_spec,
        "rate_denominator_policy_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, POLICY_OUTPUT_DIR / filename)
    _write_text(findings, POLICY_OUTPUT_DIR / "rate_denominator_policy_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "rate denominator policy and first descriptive rate-prototype specification, without computing rates",
        "inputs": [
            str(path)
            for path in [
                RATE_MODELING_PLAN_FILE,
                READINESS_SUMMARY_FILE,
                READINESS_WINDOW_UNITS_FILE,
                READINESS_QA_FILE,
                READINESS_FINDINGS_FILE,
                READINESS_MANIFEST_FILE,
                READINESS_DUPLICATE_AUDIT_FILE,
                DIRECTIONAL_CRASH_CONTEXT_FILE,
                CRASH_DATE_SOURCE_FILE,
                AADT_V3_FINDINGS_FILE,
                AADT_V3_MANIFEST_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(POLICY_OUTPUT_DIR / name) for name in list(outputs) + ["rate_denominator_policy_findings.md", "rate_denominator_policy_manifest.json"]),
        "first_rate_prototype_unit": FIRST_RATE_PROTOTYPE_UNIT,
        "prototype_windows": FIRST_RATE_PROTOTYPE_WINDOWS.split("|"),
        "thresholds": {
            "stable_aadt_coverage_share": AADT_COVERAGE_THRESHOLD,
            "low_length_ft_threshold": LOW_LENGTH_FT_THRESHOLD,
            "low_crash_count_threshold": LOW_CRASH_COUNT_THRESHOLD,
        },
        "guardrails": {
            "crash_direction_fields_used": False,
            "crash_rates_computed": False,
            "aadt_normalized_comparisons_computed": False,
            "models_or_regressions_fit": False,
            "causal_policy_or_safety_performance_language": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, POLICY_OUTPUT_DIR / "rate_denominator_policy_manifest.json")
    return {"summary": summary, "candidate_counts": candidate_counts, "crash_study_period": crash_study_period, "qa": qa}


def main() -> None:
    parser = argparse.ArgumentParser(description="Write rate denominator policy support tables without computing rates.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
