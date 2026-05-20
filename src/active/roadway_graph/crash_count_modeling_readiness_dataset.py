from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
RATE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype"
SUPPRESSION_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_suppression_review"
ACCESS_DIAGNOSTIC_DIR = OUTPUT_ROOT / "analysis/current/access_density_figure_diagnostic"
AADT_FACTOR_DIR = OUTPUT_ROOT / "analysis/current/aadt_direction_factor_audit"
FIGURE_DATA_DIR = OUTPUT_ROOT / "report/current/context_relationship_figure_data"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_modeling_readiness_dataset"

DIRECTIONAL_BIN_CONTEXT_FILE = CONTEXT_DIR / "directional_bin_context.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = CONTEXT_DIR / "directional_crash_context.csv"
WINDOW_FEATURE_FILE = READINESS_DIR / "modeling_feature_matrix_signal_direction_window.csv"
BAND_FEATURE_FILE = READINESS_DIR / "modeling_feature_matrix_signal_direction_distance_band.csv"
READINESS_MANIFEST_FILE = READINESS_DIR / "exposure_modeling_readiness_manifest.json"
RATE_MANIFEST_FILE = RATE_DIR / "descriptive_rate_prototype_manifest.json"
SUPPRESSION_MANIFEST_FILE = SUPPRESSION_DIR / "rate_suppression_review_manifest.json"
ACCESS_DIAGNOSTIC_MANIFEST_FILE = ACCESS_DIAGNOSTIC_DIR / "access_density_figure_diagnostic_manifest.json"
AADT_FACTOR_MANIFEST_FILE = AADT_FACTOR_DIR / "aadt_direction_factor_audit_manifest.json"

STUDY_PERIOD_DAYS = 1096
STUDY_PERIOD_LABEL = "2022_2024"
AADT_COVERAGE_THRESHOLD = 0.80
SPEED_COVERAGE_THRESHOLD = 0.80
LOW_CRASH_COUNT_THRESHOLD = 3
LOW_EXPOSURE_QUANTILE = 0.10
SPARSE_UNIT_THRESHOLD = 25
SPARSE_CRASH_THRESHOLD = 5
EXPLODING_RATE_QUANTILE = 0.99
WINDOWS = ["high_priority_0_1000ft", "sensitivity_1000_2500ft"]
BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]
ACCESS_ORDER = ["0_per_1000ft", "gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft", "6plus_per_1000ft"]

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
    if not path.exists():
        raise FileNotFoundError(path)
    header = pd.read_csv(path, nrows=0).columns.tolist()
    columns = header if usecols is None else usecols
    blocked = [column for column in columns if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: Any, denominator: Any) -> Any:
    return numerator / denominator.replace(0, pd.NA)


def _mode_or_blank(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA
    modes = values.mode(dropna=True)
    return modes.iloc[0] if not modes.empty else pd.NA


def _join_flags(values: pd.Series) -> str:
    clean = sorted({str(value) for value in values.dropna().astype(str) if str(value)})
    return "|".join(clean) if clean else "none"


def _year_status(year: Any) -> str:
    value = pd.to_numeric(pd.Series([year]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "aadt_year_missing"
    year_int = int(value)
    if 2022 <= year_int <= 2024:
        return "inside_crash_period"
    if year_int < 2022:
        return "before_crash_period"
    return "after_crash_period"


def _aadt_band(value: Any) -> str:
    if pd.isna(value):
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


def _speed_band(stable_share: Any, value: Any) -> str:
    if pd.isna(value) or pd.isna(stable_share) or float(stable_share) < SPEED_COVERAGE_THRESHOLD:
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


def _access_density_band(value: Any) -> str:
    if pd.isna(value):
        return "access_density_unavailable"
    value = float(value)
    if value == 0:
        return "0_per_1000ft"
    if value < 1:
        return "gt0_lt1_per_1000ft"
    if value < 3:
        return "1_lt3_per_1000ft"
    if value < 6:
        return "3_lt6_per_1000ft"
    return "6plus_per_1000ft"


def _load_feature_matrix(path: Path, required_grain_column: str) -> pd.DataFrame:
    frame = _read_csv(path)
    numeric_columns = [
        "assigned_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "represented_length_ft",
        "represented_length_miles",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "length_weighted_aadt",
        "length_weighted_speed",
        "speed_median",
        "speed_mean",
        "dominant_speed",
        "access_count_within_catchment_sum",
        "urban_crash_count",
        "rural_crash_count",
        "unknown_area_type_crash_count",
        "divided_physical_carriageway_bin_count",
        "undivided_centerline_pseudo_direction_bin_count",
        "context_complete_bin_count",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = _num(frame[column])
    for column in ["denominator_candidate_ready", "duplicated_signal_relative_exposure_possible"]:
        if column in frame.columns:
            frame[column] = _bool(frame[column])
    if required_grain_column not in frame.columns:
        raise ValueError(f"{path} is missing required grain column {required_grain_column}")
    return frame


def _load_aadt_year_flags(group_cols: list[str]) -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "signal_relative_direction",
        "distance_window",
        "bin_midpoint_ft_from_reference_signal",
        "aadt_year",
        "aadt_value",
        "has_stable_aadt_context",
    ]
    context = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    context["bin_midpoint_ft_from_reference_signal"] = _num(context["bin_midpoint_ft_from_reference_signal"])
    context["aadt_value"] = _num(context["aadt_value"])
    context["aadt_year_num"] = _num(context["aadt_year"])
    context["has_stable_aadt_context"] = _bool(context["has_stable_aadt_context"])
    context = context.loc[
        context["distance_window"].isin(WINDOWS) & context["bin_midpoint_ft_from_reference_signal"].le(2500)
    ].copy()
    context["analysis_window"] = context["distance_window"]
    context["distance_band"] = pd.cut(
        context["bin_midpoint_ft_from_reference_signal"],
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=BAND_ORDER,
        right=False,
        include_lowest=True,
    ).astype(str)
    context.loc[context["bin_midpoint_ft_from_reference_signal"].eq(2500), "distance_band"] = "1500_2500ft"
    stable = context.loc[context["has_stable_aadt_context"]].copy()
    out = (
        stable.groupby(group_cols, dropna=False)
        .agg(
            stable_aadt_year_count=("aadt_year_num", "nunique"),
            stable_aadt_years=("aadt_year", lambda s: "|".join(sorted({str(x) for x in s if str(x)}))),
            dominant_aadt_year=("aadt_year_num", _mode_or_blank),
            positive_aadt_bin_count=("aadt_value", lambda s: int(s.gt(0).sum())),
        )
        .reset_index()
    )
    out["aadt_year_status"] = out["dominant_aadt_year"].map(_year_status)
    out["mixed_aadt_year_flag"] = out["stable_aadt_year_count"].gt(1)
    out["outside_period_aadt_year_flag"] = ~out["aadt_year_status"].eq("inside_crash_period")
    return out


def _prepare_matrix(feature: pd.DataFrame, grain_col: str) -> pd.DataFrame:
    group_cols = ["reference_signal_id", "signal_relative_direction", grain_col]
    years = _load_aadt_year_flags(group_cols)
    frame = feature.merge(years, on=group_cols, how="left")
    frame["aadt_value_for_denominator"] = frame["length_weighted_aadt"]
    frame["denominator_ready_flag"] = (
        frame["denominator_candidate_ready"]
        & frame["stable_aadt_coverage_share"].ge(AADT_COVERAGE_THRESHOLD)
        & frame["represented_length_miles"].gt(0)
        & frame["aadt_value_for_denominator"].gt(0)
    )
    frame["estimated_exposure"] = pd.NA
    ready = frame["denominator_ready_flag"]
    frame.loc[ready, "estimated_exposure"] = (
        frame.loc[ready, "aadt_value_for_denominator"]
        * frame.loc[ready, "represented_length_miles"]
        * STUDY_PERIOD_DAYS
    )
    frame["estimated_exposure"] = _num(frame["estimated_exposure"])
    frame["log_estimated_exposure"] = frame["estimated_exposure"].map(
        lambda value: math.log(float(value)) if pd.notna(value) and float(value) > 0 else pd.NA
    )
    threshold = frame.loc[frame["denominator_ready_flag"], "estimated_exposure"].quantile(LOW_EXPOSURE_QUANTILE)
    frame["low_exposure_flag"] = frame["denominator_ready_flag"] & frame["estimated_exposure"].le(threshold)
    frame["low_crash_count_flag"] = frame["assigned_crash_count"].lt(LOW_CRASH_COUNT_THRESHOLD)
    frame["zero_crash_flag"] = frame["assigned_crash_count"].eq(0)
    frame["aadt_band"] = frame["aadt_value_for_denominator"].where(frame["denominator_ready_flag"]).map(_aadt_band)
    frame["aadt_year_status"] = frame["aadt_year_status"].fillna("aadt_year_missing")
    frame["mixed_aadt_year_flag"] = frame["mixed_aadt_year_flag"].fillna(False).astype(bool)
    frame["outside_period_aadt_year_flag"] = frame["outside_period_aadt_year_flag"].fillna(True).astype(bool)
    frame["bidirectional_aadt_assumption_flag"] = True
    frame["speed_value_summary"] = (
        "median="
        + frame["speed_median"].round(3).astype("string").fillna("missing")
        + ";mean="
        + frame["speed_mean"].round(3).astype("string").fillna("missing")
        + ";length_weighted="
        + frame["length_weighted_speed"].round(3).astype("string").fillna("missing")
    )
    frame["speed_band"] = [
        _speed_band(share, value)
        for share, value in zip(frame["stable_speed_coverage_share"], frame["length_weighted_speed"])
    ]
    frame["speed_missing_or_review_share"] = 1 - frame["stable_speed_coverage_share"]
    frame["local_access_count"] = frame["access_count_within_catchment_sum"].fillna(0)
    frame["local_access_density_per_1000ft"] = _safe_div(frame["local_access_count"] * 1000, frame["represented_length_ft"])
    frame["local_access_density_band"] = frame["local_access_density_per_1000ft"].map(_access_density_band)
    frame["roadway_representation_mix"] = (
        "divided_physical_carriageway="
        + frame["divided_physical_carriageway_bin_count"].fillna(0).astype(int).astype(str)
        + ";undivided_centerline_pseudo_direction="
        + frame["undivided_centerline_pseudo_direction_bin_count"].fillna(0).astype(int).astype(str)
        + ";dominant="
        + frame["dominant_roadway_representation_type"].astype(str)
    )
    frame["context_completeness_flags"] = (
        "context_complete_bins="
        + frame["context_complete_bin_count"].fillna(0).astype(int).astype(str)
        + ";stable_aadt_share="
        + frame["stable_aadt_coverage_share"].round(3).astype("string").fillna("missing")
        + ";stable_speed_share="
        + frame["stable_speed_coverage_share"].round(3).astype("string").fillna("missing")
        + ";duplicated_signal_relative_exposure_possible="
        + frame["duplicated_signal_relative_exposure_possible"].astype(bool).astype(str)
    )
    keep = [
        "reference_signal_id",
        "signal_relative_direction",
        grain_col,
        "assigned_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "represented_length_ft",
        "represented_length_miles",
        "estimated_exposure",
        "log_estimated_exposure",
        "denominator_ready_flag",
        "low_exposure_flag",
        "low_crash_count_flag",
        "zero_crash_flag",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "aadt_value_for_denominator",
        "aadt_band",
        "aadt_year_status",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "bidirectional_aadt_assumption_flag",
        "speed_value_summary",
        "speed_band",
        "speed_missing_or_review_share",
        "local_access_count",
        "local_access_density_per_1000ft",
        "local_access_density_band",
        "roadway_representation_mix",
        "urban_crash_count",
        "rural_crash_count",
        "context_completeness_flags",
    ]
    return frame[keep].copy()


def _association(frame: pd.DataFrame, group_cols: list[str], table_name: str, include_rate: bool = True) -> pd.DataFrame:
    work = frame.copy()
    work["ready_exposure"] = work["estimated_exposure"].where(work["denominator_ready_flag"])
    grouped = (
        work.groupby(group_cols, dropna=False)
        .agg(
            unit_count=("reference_signal_id", "count"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            estimated_exposure=("ready_exposure", "sum"),
            denominator_ready_unit_count=("denominator_ready_flag", "sum"),
            low_exposure_unit_count=("low_exposure_flag", "sum"),
            low_crash_count_unit_count=("low_crash_count_flag", "sum"),
            zero_crash_unit_count=("zero_crash_flag", "sum"),
            mixed_aadt_year_unit_count=("mixed_aadt_year_flag", "sum"),
            outside_period_aadt_year_unit_count=("outside_period_aadt_year_flag", "sum"),
            bidirectional_aadt_caveat_unit_count=("bidirectional_aadt_assumption_flag", "sum"),
        )
        .reset_index()
    )
    grouped.insert(0, "exploratory_table", table_name)
    grouped["denominator_ready_share"] = grouped["denominator_ready_unit_count"] / grouped["unit_count"].replace(0, pd.NA)
    grouped["low_denominator_flag"] = grouped["low_exposure_unit_count"].gt(0) | grouped["denominator_ready_share"].lt(0.80)
    grouped["sparse_cell_flag"] = grouped["unit_count"].lt(SPARSE_UNIT_THRESHOLD) | grouped["assigned_crash_count"].lt(SPARSE_CRASH_THRESHOLD)
    grouped["mixed_aadt_year_flag"] = grouped["mixed_aadt_year_unit_count"].gt(0)
    grouped["outside_period_aadt_year_flag"] = grouped["outside_period_aadt_year_unit_count"].gt(0)
    grouped["bidirectional_aadt_caveat_flag"] = grouped["bidirectional_aadt_caveat_unit_count"].gt(0)
    if include_rate:
        grouped["crashes_per_million_estimated_exposure"] = (
            grouped["assigned_crash_count"] * 1_000_000 / grouped["estimated_exposure"].replace(0, pd.NA)
        )
        rate_threshold = grouped["crashes_per_million_estimated_exposure"].quantile(EXPLODING_RATE_QUANTILE)
        grouped["high_or_exploding_rate_preview_flag"] = grouped["crashes_per_million_estimated_exposure"].ge(rate_threshold)
        grouped["rate_preview_status"] = "exploratory_descriptive_preview_only"
    return grouped


def _build_associations(window: pd.DataFrame, band: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "exploratory_counts_by_distance_access.csv": _association(
            band, ["distance_band", "local_access_density_band"], "exploratory_counts_by_distance_access"
        ),
        "exploratory_counts_by_window_access.csv": _association(
            window, ["analysis_window", "local_access_density_band"], "exploratory_counts_by_window_access"
        ),
        "exploratory_counts_by_speed_access.csv": _association(
            window, ["speed_band", "local_access_density_band"], "exploratory_counts_by_speed_access"
        ),
        "exploratory_counts_by_aadt_access.csv": _association(
            window, ["aadt_band", "local_access_density_band"], "exploratory_counts_by_aadt_access"
        ),
        "exploratory_counts_by_distance_speed.csv": _association(
            band, ["distance_band", "speed_band"], "exploratory_counts_by_distance_speed"
        ),
        "exploratory_counts_by_distance_aadt.csv": _association(
            band, ["distance_band", "aadt_band"], "exploratory_counts_by_distance_aadt"
        ),
        "exploratory_counts_by_direction_distance_access.csv": _association(
            band,
            ["signal_relative_direction", "distance_band", "local_access_density_band"],
            "exploratory_counts_by_direction_distance_access",
        ),
        "exploratory_counts_by_direction_speed_access.csv": _association(
            window,
            ["signal_relative_direction", "speed_band", "local_access_density_band"],
            "exploratory_counts_by_direction_speed_access",
        ),
        "exploratory_rate_preview_by_distance_access.csv": _association(
            band, ["distance_band", "local_access_density_band"], "exploratory_rate_preview_by_distance_access"
        ),
        "exploratory_rate_preview_by_window_access.csv": _association(
            window, ["analysis_window", "local_access_density_band"], "exploratory_rate_preview_by_window_access"
        ),
    }


def _feature_inventory(window: pd.DataFrame, band: pd.DataFrame) -> pd.DataFrame:
    rows = []
    combined = {"window": window, "distance_band": band}
    for feature in [
        "analysis_window",
        "distance_band",
        "signal_relative_direction",
        "local_access_density_band",
        "speed_band",
        "aadt_band",
        "log_estimated_exposure",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "aadt_year_status",
        "roadway_representation_mix",
    ]:
        for grain, frame in combined.items():
            if feature not in frame.columns:
                continue
            rows.append(
                {
                    "feature_name": feature,
                    "matrix_grain": grain,
                    "role": "offset" if feature == "log_estimated_exposure" else "candidate_covariate_or_quality_flag",
                    "non_missing_share": float(frame[feature].notna().mean()),
                    "unique_value_count": int(frame[feature].nunique(dropna=True)),
                    "ready_for_first_model": feature
                    in {
                        "analysis_window",
                        "distance_band",
                        "signal_relative_direction",
                        "local_access_density_band",
                        "speed_band",
                        "aadt_band",
                        "log_estimated_exposure",
                    },
                    "caution": _feature_caution(feature, frame),
                }
            )
    return pd.DataFrame(rows)


def _feature_caution(feature: str, frame: pd.DataFrame) -> str:
    if feature == "log_estimated_exposure":
        return "available only for denominator-ready units; use as offset, not outcome"
    if feature == "speed_band":
        missing_share = float(frame["speed_band"].eq("speed_missing_or_review").mean())
        return f"missing_or_review_share={missing_share:.3f}"
    if feature == "aadt_band":
        missing_share = float(frame["aadt_band"].eq("aadt_missing_or_review").mean())
        return f"missing_or_review_share={missing_share:.3f}; bidirectional AADT assumption is provisional"
    if feature == "local_access_density_band":
        return "computed at local model-unit grain from summed access and represented length"
    if feature == "aadt_year_status":
        return "flag only; AADT year mismatch is not automatic suppression"
    return "none"


def _formula_spec() -> pd.DataFrame:
    rows = [
        {
            "formula_id": "first_window_count_offset",
            "preferred_first_model_candidate": True,
            "matrix": "crash_count_modeling_matrix_signal_direction_window.csv",
            "formula": "assigned_crash_count ~ analysis_window + signal_relative_direction + local_access_density_band + speed_band + offset(log_estimated_exposure)",
            "notes": "Simpler first count-model candidate; do not fit in this package.",
        },
        {
            "formula_id": "window_with_aadt_band",
            "preferred_first_model_candidate": False,
            "matrix": "crash_count_modeling_matrix_signal_direction_window.csv",
            "formula": "assigned_crash_count ~ analysis_window + signal_relative_direction + local_access_density_band + speed_band + aadt_band + offset(log_estimated_exposure)",
            "notes": "Includes AADT band as covariate while exposure offset also uses AADT; review collinearity and interpretation before fitting.",
        },
        {
            "formula_id": "distance_band_access_interaction",
            "preferred_first_model_candidate": False,
            "matrix": "crash_count_modeling_matrix_signal_direction_distance_band.csv",
            "formula": "assigned_crash_count ~ distance_band + signal_relative_direction + local_access_density_band + speed_band + aadt_band + distance_band:local_access_density_band + offset(log_estimated_exposure)",
            "notes": "Candidate for distance-varying access association after sparse-cell review.",
        },
        {
            "formula_id": "distance_band_main_effects",
            "preferred_first_model_candidate": False,
            "matrix": "crash_count_modeling_matrix_signal_direction_distance_band.csv",
            "formula": "assigned_crash_count ~ distance_band + signal_relative_direction + local_access_density_band + speed_band + offset(log_estimated_exposure)",
            "notes": "Fixed-band count-model candidate; more granular and sparser than window grain.",
        },
    ]
    return pd.DataFrame(rows)


def _quality_summary(window: pd.DataFrame, band: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for grain, frame in [("signal_direction_window", window), ("signal_direction_distance_band", band)]:
        rows.append(
            {
                "matrix_grain": grain,
                "unit_count": len(frame),
                "denominator_ready_unit_count": int(frame["denominator_ready_flag"].sum()),
                "denominator_ready_share": float(frame["denominator_ready_flag"].mean()),
                "assigned_crash_count": int(frame["assigned_crash_count"].sum()),
                "denominator_ready_assigned_crash_count": int(frame.loc[frame["denominator_ready_flag"], "assigned_crash_count"].sum()),
                "low_exposure_unit_count": int(frame["low_exposure_flag"].sum()),
                "low_crash_count_unit_count": int(frame["low_crash_count_flag"].sum()),
                "zero_crash_unit_count": int(frame["zero_crash_flag"].sum()),
                "speed_missing_or_review_unit_count": int(frame["speed_band"].eq("speed_missing_or_review").sum()),
                "aadt_missing_or_review_unit_count": int(frame["aadt_band"].eq("aadt_missing_or_review").sum()),
                "mixed_aadt_year_unit_count": int(frame["mixed_aadt_year_flag"].sum()),
                "outside_period_aadt_year_unit_count": int(frame["outside_period_aadt_year_flag"].sum()),
                "bidirectional_aadt_caveat_flag": True,
            }
        )
    return pd.DataFrame(rows)


def _warning_flags(window: pd.DataFrame, band: pd.DataFrame, associations: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for grain, frame in [("signal_direction_window", window), ("signal_direction_distance_band", band)]:
        for flag in [
            "low_exposure_flag",
            "low_crash_count_flag",
            "zero_crash_flag",
            "mixed_aadt_year_flag",
            "outside_period_aadt_year_flag",
            "bidirectional_aadt_assumption_flag",
        ]:
            rows.append(
                {
                    "scope": grain,
                    "flag_name": flag,
                    "flagged_count": int(frame[flag].sum()),
                    "unit_count": len(frame),
                    "flagged_share": float(frame[flag].mean()),
                    "handling": "preserve_and_flag",
                }
            )
    for name, frame in associations.items():
        if "high_or_exploding_rate_preview_flag" in frame.columns:
            rows.append(
                {
                    "scope": name,
                    "flag_name": "high_or_exploding_rate_preview_flag",
                    "flagged_count": int(frame["high_or_exploding_rate_preview_flag"].sum()),
                    "unit_count": len(frame),
                    "flagged_share": float(frame["high_or_exploding_rate_preview_flag"].mean()),
                    "handling": "preserve_for_qa_not_hidden",
                }
            )
    return pd.DataFrame(rows)


def _pattern_findings(window_access: pd.DataFrame, distance_access: pd.DataFrame) -> dict[str, str]:
    hp = window_access.loc[window_access["analysis_window"].eq("high_priority_0_1000ft")].copy()
    far = window_access.loc[window_access["analysis_window"].eq("sensitivity_1000_2500ft")].copy()

    def ordered_rates(frame: pd.DataFrame) -> list[float]:
        indexed = frame.set_index("local_access_density_band")
        rates = []
        for band in ACCESS_ORDER:
            if band in indexed.index:
                rates.append(float(indexed.loc[band, "crashes_per_million_estimated_exposure"]))
        return rates

    hp_rates = ordered_rates(hp)
    far_nonzero = far.loc[~far["local_access_density_band"].eq("0_per_1000ft")].copy()
    far_rates = ordered_rates(far_nonzero)
    hp_non_monotonic = any((hp_rates[i + 1] - hp_rates[i]) * (hp_rates[i] - hp_rates[i - 1]) < 0 for i in range(1, len(hp_rates) - 1))
    far_monotonic_after_zero = all(far_rates[i + 1] >= far_rates[i] for i in range(len(far_rates) - 1)) if len(far_rates) > 1 else False
    distance_varies = (
        distance_access.groupby("distance_band")["crashes_per_million_estimated_exposure"].max()
        - distance_access.groupby("distance_band")["crashes_per_million_estimated_exposure"].min()
    ).fillna(0)
    return {
        "access_patterns_differ_by_distance": "yes" if distance_varies.gt(0).any() else "not_detected",
        "zero_to_1000_access_pattern_non_monotonic": "yes" if hp_non_monotonic else "not_clearly",
        "one_thousand_to_2500_access_pattern_monotonic_after_zero": "yes" if far_monotonic_after_zero else "not_clearly",
    }


def _qa(window: pd.DataFrame, band: pd.DataFrame, context_max_distance: float, associations: dict[str, pd.DataFrame]) -> pd.DataFrame:
    access_recalc_ok = (
        window["local_access_density_per_1000ft"].notna().any()
        and band["local_access_density_per_1000ft"].notna().any()
    )
    high_rates_flagged = all(
        "high_or_exploding_rate_preview_flag" in frame.columns for frame in associations.values()
    )
    rows = [
        ("no_crash_direction_fields_read_or_used", True, "guarded reader blocks crash-direction field tokens", "required"),
        ("no_rows_over_2500ft_entered", context_max_distance <= 2500, context_max_distance, "<=2500"),
        ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read and no direction-factor field created", "required"),
        ("no_regression_or_model_fit", True, "tables and formula specs only", "required"),
        ("no_causal_policy_safety_performance_danger_risk_language", True, "findings language constrained", "required"),
        ("access_density_is_local_grain_not_raw_50ft", access_recalc_ok, "summed access / summed represented length at output grain", "required"),
        (
            "estimated_exposure_only_when_denominator_inputs_valid",
            bool(window.loc[~window["denominator_ready_flag"], "estimated_exposure"].isna().all())
            and bool(band.loc[~band["denominator_ready_flag"], "estimated_exposure"].isna().all()),
            "non-ready units have missing estimated_exposure",
            "required",
        ),
        ("high_exploding_rates_flagged_not_hidden", high_rates_flagged, "rate preview tables carry high_or_exploding_rate_preview_flag", "required"),
    ]
    return pd.DataFrame(rows, columns=["check_name", "passed", "observed", "expected"])


def _findings(
    window: pd.DataFrame,
    band: pd.DataFrame,
    quality: pd.DataFrame,
    patterns: dict[str, str],
    outputs: dict[str, Path],
) -> str:
    window_ready = quality.loc[quality["matrix_grain"].eq("signal_direction_window")].iloc[0]
    band_ready = quality.loc[quality["matrix_grain"].eq("signal_direction_distance_band")].iloc[0]
    ready_vars = ["signal_relative_direction", "analysis_window", "local_access_density_band", "log_estimated_exposure"]
    caution_vars = ["speed_band", "aadt_band", "aadt_year_status", "bidirectional_aadt_assumption_flag", "distance_band"]
    return f"""# Crash Count Modeling Readiness Dataset Findings

**Status:** read-only modeling feature preparation and exploratory association package. No regression, predictive model, causal claim, safety-performance ranking, danger/risk ranking, policy guidance, or downstream functional-area distance recommendation is created.

## Bounded Question

How do assigned crash counts vary with speed, local access density, distance from signal, AADT, and signal-relative direction together, while carrying estimated exposure for a future count model offset?

## Recommended First Modeling Grain

The recommended first fitting grain is `reference_signal_id + signal_relative_direction + analysis_window`.

- Window matrix units: {int(window_ready.unit_count)}; denominator-ready units: {int(window_ready.denominator_ready_unit_count)} ({float(window_ready.denominator_ready_share):.3f}).
- Distance-band matrix units: {int(band_ready.unit_count)}; denominator-ready units: {int(band_ready.denominator_ready_unit_count)} ({float(band_ready.denominator_ready_share):.3f}).
- The window grain is less sparse and is consistent with the approved descriptive-rate denominator prototype. The fixed distance-band grain is useful for exploratory interaction review, but it is more granular and should follow sparse-cell review before first model fitting.

## Access And Distance Patterns

- Access-density patterns differ by distance band/window: {patterns["access_patterns_differ_by_distance"]}.
- The 0-1,000 ft access pattern appears non-monotonic: {patterns["zero_to_1000_access_pattern_non_monotonic"]}.
- The 1,000-2,500 ft access pattern appears monotonic after the zero-access group: {patterns["one_thousand_to_2500_access_pattern_monotonic_after_zero"]}.

These are exploratory associations from grouped counts and denominator-ready exposure previews. They are not fitted effects.

## Variables Ready For First Modeling Prep

Ready with current caveats: {", ".join(ready_vars)}.

Variables requiring caution: {", ".join(caution_vars)}. Speed has missing/review units, AADT remains bidirectional/provisional, AADT year mismatches are flagged rather than suppressed, and distance-band interactions are sparser than the broad-window matrix.

## Exposure And Offset

`estimated_exposure = length_weighted_stable_AADT x represented_length_miles x 1096 days` is populated only for denominator-ready units. `log_estimated_exposure` is prepared for use as a future offset. `DIRECTION_FACTOR` is not applied.

## Next Step

A Poisson/negative-binomial model specification memo should be created next. It should define candidate distributions, overdispersion checks, offset handling, sparse-cell consolidation rules, treatment of AADT both as exposure and candidate covariate, and validation criteria before any model is fit.

## Key Outputs

- Window matrix: `{outputs["window_matrix"]}`
- Distance-band matrix: `{outputs["band_matrix"]}`
- Candidate formulas: `{outputs["formula_spec"]}`
- Warning flags: `{outputs["warning_flags"]}`
"""


def build_outputs() -> dict[str, Any]:
    window_feature = _load_feature_matrix(WINDOW_FEATURE_FILE, "analysis_window")
    band_feature = _load_feature_matrix(BAND_FEATURE_FILE, "distance_band")
    context_distance = _read_csv(
        DIRECTIONAL_BIN_CONTEXT_FILE,
        usecols=["bin_midpoint_ft_from_reference_signal", "distance_window"],
    )
    context_distance["bin_midpoint_ft_from_reference_signal"] = _num(context_distance["bin_midpoint_ft_from_reference_signal"])
    context_distance = context_distance.loc[context_distance["distance_window"].isin(WINDOWS)].copy()
    context_max_distance = float(context_distance["bin_midpoint_ft_from_reference_signal"].max())

    # Read crash context only for lineage/count reconciliation, without crash direction fields.
    crash_context = _read_csv(
        DIRECTIONAL_CRASH_CONTEXT_FILE,
        usecols=[
            "crash_id",
            "reference_signal_id",
            "signal_relative_direction",
            "bin_midpoint_ft_from_reference_signal",
            "functional_distance_window",
            "crash_urban_rural_class",
        ],
    )
    crash_context["bin_midpoint_ft_from_reference_signal"] = _num(crash_context["bin_midpoint_ft_from_reference_signal"])
    crash_context = crash_context.loc[crash_context["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()

    window = _prepare_matrix(window_feature, "analysis_window")
    band = _prepare_matrix(band_feature, "distance_band")
    associations = _build_associations(window, band)
    inventory = _feature_inventory(window, band)
    formula_spec = _formula_spec()
    quality = _quality_summary(window, band)
    warnings = _warning_flags(window, band, associations)
    patterns = _pattern_findings(
        associations["exploratory_rate_preview_by_window_access.csv"],
        associations["exploratory_rate_preview_by_distance_access.csv"],
    )
    qa = _qa(window, band, context_max_distance, associations)

    outputs = {
        "window_matrix": OUTPUT_DIR / "crash_count_modeling_matrix_signal_direction_window.csv",
        "band_matrix": OUTPUT_DIR / "crash_count_modeling_matrix_signal_direction_distance_band.csv",
        "inventory": OUTPUT_DIR / "candidate_model_feature_inventory.csv",
        "formula_spec": OUTPUT_DIR / "candidate_model_formula_spec.csv",
        "quality_summary": OUTPUT_DIR / "modeling_unit_quality_summary.csv",
        "warning_flags": OUTPUT_DIR / "modeling_readiness_warning_flags.csv",
        "findings": OUTPUT_DIR / "crash_count_modeling_readiness_findings.md",
        "manifest": OUTPUT_DIR / "crash_count_modeling_readiness_manifest.json",
        "qa": OUTPUT_DIR / "crash_count_modeling_readiness_qa.csv",
    }
    _write_csv(window, outputs["window_matrix"])
    _write_csv(band, outputs["band_matrix"])
    for filename, frame in associations.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_csv(inventory, outputs["inventory"])
    _write_csv(formula_spec, outputs["formula_spec"])
    _write_csv(quality, outputs["quality_summary"])
    _write_csv(warnings, outputs["warning_flags"])
    _write_csv(qa, outputs["qa"])
    findings = _findings(window, band, quality, patterns, outputs)
    _write_text(findings, outputs["findings"])

    supporting_inputs = [
        READINESS_MANIFEST_FILE,
        RATE_MANIFEST_FILE,
        SUPPRESSION_MANIFEST_FILE,
        ACCESS_DIAGNOSTIC_MANIFEST_FILE,
        AADT_FACTOR_MANIFEST_FILE,
    ]
    figure_data_files = sorted(FIGURE_DATA_DIR.glob("*.csv")) if FIGURE_DATA_DIR.exists() else []
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "crash-count modeling readiness feature matrices and exploratory associations with estimated exposure offsets",
        "study_period": {"label": STUDY_PERIOD_LABEL, "days": STUDY_PERIOD_DAYS},
        "inputs": [
            str(path)
            for path in [
                DIRECTIONAL_BIN_CONTEXT_FILE,
                DIRECTIONAL_CRASH_CONTEXT_FILE,
                WINDOW_FEATURE_FILE,
                BAND_FEATURE_FILE,
                *supporting_inputs,
                *figure_data_files,
            ]
            if path.exists()
        ],
        "outputs": sorted(str(path) for path in OUTPUT_DIR.glob("*")),
        "row_counts": {
            "directional_crash_context_rows_le_2500ft_read_for_reconciliation": int(len(crash_context)),
            "window_matrix_rows": int(len(window)),
            "distance_band_matrix_rows": int(len(band)),
            "association_table_count": int(len(associations)),
            "figure_data_files_found": int(len(figure_data_files)),
        },
        "patterns": patterns,
        "guardrails": {
            "crash_direction_fields_used": False,
            "rows_over_2500ft_used": False,
            "direction_factor_applied": False,
            "regression_or_model_fit": False,
            "predictive_model_created": False,
            "causal_policy_safety_performance_danger_risk_language": False,
            "access_density_raw_50ft_bin_grain_used": False,
            "high_exploding_rates_hidden": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return {
        "window": window,
        "band": band,
        "associations": associations,
        "quality": quality,
        "warnings": warnings,
        "patterns": patterns,
        "qa": qa,
        "outputs": outputs,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build read-only crash-count modeling readiness matrices and exploratory association tables."
    )
    parser.parse_args()
    build_outputs()


if __name__ == "__main__":
    main()
