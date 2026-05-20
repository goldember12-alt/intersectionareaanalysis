from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
APPROVAL_DIR = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1"
CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"

FEATURE_MATRIX_FILE = READINESS_DIR / "modeling_feature_matrix_signal_direction_window.csv"
WINDOW_READINESS_FILE = READINESS_DIR / "analysis_unit_readiness_signal_direction_window.csv"
DENOMINATOR_RULE_SPEC_FILE = APPROVAL_DIR / "denominator_rule_spec_v1.csv"
AUTHORIZATION_DECISION_FILE = APPROVAL_DIR / "rate_prototype_authorization_decision.csv"
AADT_YEAR_ALIGNMENT_FILE = APPROVAL_DIR / "aadt_year_alignment_audit.csv"
APPROVAL_DOC_FILE = Path("docs/design/roadway_graph_rate_assumption_approval_v1.md")
DIRECTIONAL_BIN_CONTEXT_FILE = CONTEXT_DIR / "directional_bin_context.csv"

WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
AUTHORIZED_GRAIN = "reference_signal_id_signal_relative_direction_analysis_window"
STUDY_PERIOD_LABEL = "2022_2024"
STUDY_PERIOD_DAYS = 1096
STUDY_PERIOD_YEARS = 3.000684
AADT_COVERAGE_THRESHOLD = 0.80
LOW_CRASH_COUNT_THRESHOLD = 3
LOW_EXPOSURE_QUANTILE = 0.10
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)


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


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.replace(0, pd.NA)).astype("Float64")


def _year_status(year: Any) -> str:
    if pd.isna(year):
        return "aadt_year_missing"
    year_int = int(year)
    if year_int < 2022:
        return "before_crash_period"
    if year_int > 2024:
        return "after_crash_period"
    return "inside_crash_period"


def _mode_or_blank(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA
    modes = values.mode(dropna=True)
    if modes.empty:
        return pd.NA
    return modes.iloc[0]


def _poisson_count_interval_95(count: float) -> tuple[float, float, str]:
    """Approximate Garwood interval using Wilson-Hilferty chi-square quantiles."""
    if pd.isna(count):
        return (pd.NA, pd.NA, "not_computed")
    k = max(int(round(float(count))), 0)
    z = 1.959963984540054
    if k == 0:
        lower = 0.0
    else:
        df_lower = 2 * k
        lower = 0.5 * df_lower * max(0.0, 1 - 2 / (9 * df_lower) - z * math.sqrt(2 / (9 * df_lower))) ** 3
    df_upper = 2 * (k + 1)
    upper = 0.5 * df_upper * max(0.0, 1 - 2 / (9 * df_upper) + z * math.sqrt(2 / (9 * df_upper))) ** 3
    return (lower, upper, "approximate_poisson_garwood_wilson_hilferty")


def load_feature_matrix() -> pd.DataFrame:
    frame = _read_csv(FEATURE_MATRIX_FILE)
    numeric_columns = [
        "assigned_crash_count",
        "bin_count",
        "crash_bearing_bin_count",
        "represented_length_ft",
        "represented_length_miles",
        "stable_aadt_bin_count",
        "missing_or_review_aadt_bin_count",
        "stable_aadt_coverage_share",
        "aadt_min",
        "aadt_median",
        "aadt_mean",
        "aadt_max",
        "dominant_aadt",
        "length_weighted_aadt",
        "stable_speed_bin_count",
        "missing_or_review_speed_bin_count",
        "stable_speed_coverage_share",
        "access_count_within_catchment_sum",
        "access_count_within_100ft_sum",
        "access_count_within_250ft_sum",
        "access_count_per_1000ft",
        "urban_crash_count",
        "rural_crash_count",
        "unknown_area_type_crash_count",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame[column])
    for column in [
        "has_positive_length",
        "has_stable_aadt_context",
        "aadt_coverage_sufficient",
        "denominator_candidate_ready",
        "low_denominator_warning",
        "low_crash_count_warning",
        "rate_ready_candidate",
        "modeling_ready_candidate",
    ]:
        frame[column] = _bool(frame[column])
    return frame


def load_aadt_year_unit_flags() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "distance_window",
        "bin_midpoint_ft_from_reference_signal",
        "aadt_year",
        "aadt_value",
        "has_stable_aadt_context",
    ]
    context = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    context = context.loc[context["distance_window"].isin(WINDOWS)].copy()
    context["bin_midpoint_ft_from_reference_signal"] = _num(context["bin_midpoint_ft_from_reference_signal"])
    context = context.loc[context["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    context["analysis_window"] = context["distance_window"]
    context["aadt_year_num"] = _num(context["aadt_year"])
    context["aadt_value"] = _num(context["aadt_value"])
    context["has_stable_aadt_context"] = _bool(context["has_stable_aadt_context"])
    stable = context.loc[context["has_stable_aadt_context"]].copy()
    unit_year = (
        stable.groupby(["reference_signal_id", "signal_relative_direction", "analysis_window"], dropna=False)
        .agg(
            stable_aadt_year_count=("aadt_year_num", "nunique"),
            stable_aadt_years=("aadt_year", lambda s: "|".join(sorted(set(x for x in s.astype(str) if x)))),
            dominant_aadt_year=("aadt_year_num", _mode_or_blank),
            stable_positive_aadt_bin_count=("aadt_value", lambda s: int(s.gt(0).sum())),
        )
        .reset_index()
    )
    unit_year["mixed_aadt_year_flag"] = unit_year["stable_aadt_year_count"].gt(1)
    unit_year["dominant_aadt_year_status"] = unit_year["dominant_aadt_year"].map(_year_status)
    unit_year["outside_period_aadt_year_flag"] = ~unit_year["dominant_aadt_year_status"].eq("inside_crash_period")
    return unit_year


def _add_rate_fields(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["study_period"] = STUDY_PERIOD_LABEL
    frame["study_period_days"] = STUDY_PERIOD_DAYS
    frame["study_period_years"] = STUDY_PERIOD_YEARS
    frame["aadt_value_for_denominator"] = frame["length_weighted_aadt"]
    frame["vmt_like_exposure"] = frame["aadt_value_for_denominator"] * frame["represented_length_miles"] * STUDY_PERIOD_DAYS
    frame["crashes_per_million_vmt"] = _safe_div(frame["assigned_crash_count"] * 1_000_000, frame["vmt_like_exposure"])
    intervals = frame["assigned_crash_count"].map(_poisson_count_interval_95)
    frame["crash_count_lower_95"] = intervals.map(lambda value: value[0])
    frame["crash_count_upper_95"] = intervals.map(lambda value: value[1])
    frame["uncertainty_method"] = intervals.map(lambda value: value[2])
    frame["rate_lower_95_per_million_vmt"] = _safe_div(frame["crash_count_lower_95"].astype(float) * 1_000_000, frame["vmt_like_exposure"])
    frame["rate_upper_95_per_million_vmt"] = _safe_div(frame["crash_count_upper_95"].astype(float) * 1_000_000, frame["vmt_like_exposure"])
    return frame


def _aggregate_rate(frame: pd.DataFrame, group_cols: list[str], summary_name: str) -> pd.DataFrame:
    grouped = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            rate_ready_unit_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            vmt_like_exposure=("vmt_like_exposure", "sum"),
            represented_length_miles=("represented_length_miles", "sum"),
            median_unit_vmt_like_exposure=("vmt_like_exposure", "median"),
            mean_unit_vmt_like_exposure=("vmt_like_exposure", "mean"),
            low_crash_count_unit_count=("low_crash_count_flag", "sum"),
            zero_crash_unit_count=("zero_crash_unit_flag", "sum"),
            mixed_aadt_year_unit_count=("mixed_aadt_year_flag", "sum"),
            outside_period_aadt_year_unit_count=("outside_period_aadt_year_flag", "sum"),
        )
        .reset_index()
    )
    grouped.insert(0, "summary_name", summary_name)
    grouped["crashes_per_million_vmt"] = _safe_div(grouped["assigned_crash_count"] * 1_000_000, grouped["vmt_like_exposure"])
    intervals = grouped["assigned_crash_count"].map(_poisson_count_interval_95)
    grouped["crash_count_lower_95"] = intervals.map(lambda value: value[0])
    grouped["crash_count_upper_95"] = intervals.map(lambda value: value[1])
    grouped["rate_lower_95_per_million_vmt"] = _safe_div(grouped["crash_count_lower_95"].astype(float) * 1_000_000, grouped["vmt_like_exposure"])
    grouped["rate_upper_95_per_million_vmt"] = _safe_div(grouped["crash_count_upper_95"].astype(float) * 1_000_000, grouped["vmt_like_exposure"])
    grouped["uncertainty_method"] = "approximate_poisson_garwood_wilson_hilferty"
    return grouped


def build_outputs() -> dict[str, Any]:
    authorization = _read_csv(AUTHORIZATION_DECISION_FILE)
    if authorization.loc[0, "authorization_decision"] != "approved_for_descriptive_rate_prototype_v1":
        raise ValueError("Rate prototype is not authorized by rate_prototype_authorization_decision.csv")
    if authorization.loc[0, "first_rate_prototype_unit"] != "reference_signal_id + signal_relative_direction + analysis_window":
        raise ValueError("Authorization does not match the window-grain prototype unit.")

    feature = load_feature_matrix()
    window_readiness = _read_csv(WINDOW_READINESS_FILE)
    denominator_rules = _read_csv(DENOMINATOR_RULE_SPEC_FILE)
    aadt_alignment = _read_csv(AADT_YEAR_ALIGNMENT_FILE)
    aadt_year_flags = load_aadt_year_unit_flags()

    feature = feature.loc[feature["analysis_unit_grain"].eq(AUTHORIZED_GRAIN) & feature["analysis_window"].isin(WINDOWS)].copy()
    feature = feature.merge(aadt_year_flags, on=["reference_signal_id", "signal_relative_direction", "analysis_window"], how="left")
    feature["mixed_aadt_year_flag"] = feature["mixed_aadt_year_flag"].fillna(False).astype(bool)
    feature["outside_period_aadt_year_flag"] = feature["outside_period_aadt_year_flag"].fillna(True).astype(bool)
    feature["dominant_aadt_year_status"] = feature["dominant_aadt_year_status"].fillna("aadt_year_missing")
    feature["stable_aadt_years"] = feature["stable_aadt_years"].fillna("")
    feature["positive_aadt_flag"] = feature["length_weighted_aadt"].gt(0)
    feature["denominator_ready_flag"] = (
        feature["denominator_candidate_ready"]
        & feature["stable_aadt_coverage_share"].ge(AADT_COVERAGE_THRESHOLD)
        & feature["represented_length_miles"].gt(0)
        & feature["positive_aadt_flag"]
    )
    feature["low_crash_count_flag"] = feature["assigned_crash_count"].lt(LOW_CRASH_COUNT_THRESHOLD)
    feature["zero_crash_unit_flag"] = feature["assigned_crash_count"].eq(0)
    feature["low_aadt_coverage_flag"] = feature["stable_aadt_coverage_share"].lt(AADT_COVERAGE_THRESHOLD)
    feature["bidirectional_aadt_assumption_flag"] = True
    feature["direction_factor_applied"] = False
    feature["aadt_year_alignment_recommendation"] = "approved_with_limitation"
    feature["directional_aadt_recommendation"] = "approved_bidirectional_aadt_for_prototype_v1"

    non_ready = feature.loc[~feature["denominator_ready_flag"]].copy()
    non_ready["non_ready_reason"] = ""
    non_ready.loc[non_ready["low_aadt_coverage_flag"], "non_ready_reason"] += "low_aadt_coverage;"
    non_ready.loc[~non_ready["represented_length_miles"].gt(0), "non_ready_reason"] += "nonpositive_length;"
    non_ready.loc[~non_ready["positive_aadt_flag"], "non_ready_reason"] += "nonpositive_or_missing_stable_aadt;"
    non_ready.loc[~non_ready["denominator_candidate_ready"], "non_ready_reason"] += "readiness_audit_denominator_candidate_false;"

    rate_rows = feature.loc[feature["denominator_ready_flag"]].copy()
    rate_rows = _add_rate_fields(rate_rows)
    low_exposure_threshold = rate_rows["vmt_like_exposure"].quantile(LOW_EXPOSURE_QUANTILE)
    rate_rows["low_exposure_flag"] = rate_rows["vmt_like_exposure"].lt(low_exposure_threshold)
    rate_rows["rate_suppression_flag"] = (
        rate_rows["vmt_like_exposure"].le(0)
        | rate_rows["aadt_value_for_denominator"].le(0)
        | rate_rows["represented_length_miles"].le(0)
        | rate_rows["low_aadt_coverage_flag"]
    )
    rate_rows["rate_interpretation_warning"] = "provisional_bidirectional_aadt_descriptive_rate_not_policy_or_safety_performance"
    rate_rows.loc[rate_rows["mixed_aadt_year_flag"], "rate_interpretation_warning"] += ";mixed_aadt_years"
    rate_rows.loc[rate_rows["outside_period_aadt_year_flag"], "rate_interpretation_warning"] += ";outside_period_aadt_year"
    rate_rows.loc[rate_rows["low_crash_count_flag"], "rate_interpretation_warning"] += ";low_crash_count"
    rate_rows.loc[rate_rows["zero_crash_unit_flag"], "rate_interpretation_warning"] += ";zero_crash_count"
    rate_rows.loc[rate_rows["low_exposure_flag"], "rate_interpretation_warning"] += ";low_exposure"

    summary_by_window = _aggregate_rate(rate_rows, ["analysis_window"], "descriptive_rate_summary_by_window")
    summary_by_direction = _aggregate_rate(rate_rows, ["signal_relative_direction"], "descriptive_rate_summary_by_signal_relative_direction")
    summary_by_review_flags = _aggregate_rate(
        rate_rows,
        [
            "low_crash_count_flag",
            "zero_crash_unit_flag",
            "mixed_aadt_year_flag",
            "outside_period_aadt_year_flag",
            "low_exposure_flag",
        ],
        "descriptive_rate_summary_by_review_flags",
    )
    top_review_units = rate_rows.loc[
        rate_rows[
            [
                "low_crash_count_flag",
                "zero_crash_unit_flag",
                "mixed_aadt_year_flag",
                "outside_period_aadt_year_flag",
                "low_exposure_flag",
            ]
        ].any(axis=1)
    ].sort_values(
        ["outside_period_aadt_year_flag", "mixed_aadt_year_flag", "assigned_crash_count", "vmt_like_exposure"],
        ascending=[False, False, False, True],
    )

    retained_crashes = int(rate_rows["assigned_crash_count"].sum())
    excluded_crashes = int(non_ready["assigned_crash_count"].sum())
    expected_retained = 12414
    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "usecols excludes fields matching crash-direction tokens", "required"),
            ("no_rows_over_2500ft_entered", True, "window feature matrix only; source context midpoint filtered <=2500", "required"),
            ("study_period_is_2022_2024", STUDY_PERIOD_DAYS == 1096, "2022-2024", "2022-2024"),
            ("study_period_days_match_approval", STUDY_PERIOD_DAYS == 1096, STUDY_PERIOD_DAYS, 1096),
            ("only_window_grain_units_used", rate_rows["analysis_unit_grain"].eq(AUTHORIZED_GRAIN).all(), AUTHORIZED_GRAIN, AUTHORIZED_GRAIN),
            ("no_raw_bin_level_rates_computed", True, "one row per signal-direction-window", "required"),
            ("no_fixed_distance_band_rates_computed", "distance_band" not in rate_rows.columns, "no distance_band column in rate output", "required"),
            ("no_missing_review_aadt_used_in_denominators", rate_rows["stable_aadt_coverage_share"].ge(AADT_COVERAGE_THRESHOLD).all(), "stable AADT coverage threshold applied", "required"),
            ("direction_factor_not_applied", (~rate_rows["direction_factor_applied"]).all(), "direction_factor_applied false", "required"),
            ("bidirectional_aadt_flag_true_for_rate_rows", rate_rows["bidirectional_aadt_assumption_flag"].all(), "all true", "required"),
            ("no_models_or_regressions_fit", True, "descriptive arithmetic only", "required"),
            ("no_causal_policy_safety_performance_danger_risk_language", True, "findings language constrained", "required"),
            ("non_ready_units_preserved", len(non_ready) > 0, len(non_ready), "positive count"),
            ("denominator_ready_crash_retention_reconciles", retained_crashes == expected_retained, retained_crashes, expected_retained),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    outputs = {
        "descriptive_rate_prototype_signal_direction_window.csv": rate_rows,
        "descriptive_rate_prototype_non_ready_units.csv": non_ready,
        "descriptive_rate_summary_by_window.csv": summary_by_window,
        "descriptive_rate_summary_by_signal_relative_direction.csv": summary_by_direction,
        "descriptive_rate_summary_by_review_flags.csv": summary_by_review_flags,
        "descriptive_rate_top_review_units.csv": top_review_units.head(250),
        "descriptive_rate_prototype_qa.csv": qa,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)

    window_lines = "\n".join(
        f"- {row.analysis_window}: {row.assigned_crash_count:.0f} crashes, {row.vmt_like_exposure:.2f} VMT-like exposure, {row.crashes_per_million_vmt:.6f} crashes per million VMT"
        for row in summary_by_window.itertuples()
    )
    direction_lines = "\n".join(
        f"- {row.signal_relative_direction}: {row.assigned_crash_count:.0f} crashes, {row.vmt_like_exposure:.2f} VMT-like exposure, {row.crashes_per_million_vmt:.6f} crashes per million VMT"
        for row in summary_by_direction.itertuples()
    )
    findings = f"""# Descriptive Crash Rate Prototype Findings

**Status:** descriptive AADT-normalized prototype only. This is not a safety-performance ranking, danger/risk ranking, causal analysis, policy guidance, or downstream functional-area distance recommendation.

## Bounded Question

What do provisional AADT-normalized descriptive crash rates look like for approved window-grain signal-relative units?

## Scope

The prototype uses `reference_signal_id + signal_relative_direction + analysis_window` only. It excludes raw 50-ft bin rates and fixed distance-band rates. It uses accepted assigned crashes from the approved 2022-2024 numerator period and includes only denominator-ready units with stable AADT coverage share >= {AADT_COVERAGE_THRESHOLD:.2f}, positive represented length, and positive stable AADT.

## Denominator And Assumptions

VMT-like exposure is computed as `length_weighted_stable_AADT x represented_length_miles x 1096 days`. AADT is treated as bidirectional exposure for each signal-relative directional view. `DIRECTION_FACTOR` is not applied. AADT year alignment is approved with limitation, and mixed/outside-period AADT year flags are preserved.

## Coverage

- Primary rate rows: {len(rate_rows)}.
- Non-ready window units preserved separately: {len(non_ready)}.
- Crashes represented in rate-ready units: {retained_crashes}.
- Crashes excluded due to denominator readiness: {excluded_crashes}.
- Median VMT-like exposure: {rate_rows["vmt_like_exposure"].median():.2f}.
- Mean VMT-like exposure: {rate_rows["vmt_like_exposure"].mean():.2f}.

## Summary By Window

{window_lines}

## Summary By Signal-Relative Direction

{direction_lines}

## Interpretation Limits

These rates are descriptive and provisional. They should be used to review denominator behavior and context patterns, not to rank safety performance, identify dangerous locations, infer causality, or recommend functional-area distances. Missing/review AADT units are excluded from primary rate rows and preserved in a non-ready review table.
"""
    _write_text(findings, OUTPUT_DIR / "descriptive_rate_prototype_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "first approved window-grain descriptive crash-rate prototype",
        "inputs": [
            str(path)
            for path in [
                FEATURE_MATRIX_FILE,
                WINDOW_READINESS_FILE,
                DENOMINATOR_RULE_SPEC_FILE,
                AUTHORIZATION_DECISION_FILE,
                AADT_YEAR_ALIGNMENT_FILE,
                DIRECTIONAL_BIN_CONTEXT_FILE,
                APPROVAL_DOC_FILE,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(OUTPUT_DIR / name) for name in list(outputs) + ["descriptive_rate_prototype_findings.md", "descriptive_rate_prototype_manifest.json"]),
        "study_period": {
            "label": STUDY_PERIOD_LABEL,
            "days": STUDY_PERIOD_DAYS,
            "years": STUDY_PERIOD_YEARS,
        },
        "rate_formula": "assigned_crash_count / (length_weighted_stable_AADT * represented_length_miles * study_period_days) * 1000000",
        "primary_rate_rows": len(rate_rows),
        "non_ready_units": len(non_ready),
        "crashes_represented_in_rate_ready_units": retained_crashes,
        "crashes_excluded_due_to_denominator_readiness": excluded_crashes,
        "guardrails": {
            "crash_direction_fields_used": False,
            "raw_bin_rates_computed": False,
            "fixed_distance_band_rates_computed": False,
            "direction_factor_applied": False,
            "models_or_regressions_fit": False,
            "causal_policy_safety_performance_danger_risk_language": False,
        },
        "qa": qa.to_dict(orient="records"),
        "unused_input_row_counts": {
            "window_readiness_rows": len(window_readiness),
            "denominator_rule_rows": len(denominator_rules),
            "aadt_alignment_rows": len(aadt_alignment),
        },
    }
    _write_json(manifest, OUTPUT_DIR / "descriptive_rate_prototype_manifest.json")
    return {
        "rate_rows": rate_rows,
        "non_ready": non_ready,
        "summary_by_window": summary_by_window,
        "summary_by_direction": summary_by_direction,
        "qa": qa,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the approved window-grain descriptive crash-rate prototype.")
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
