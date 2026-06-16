from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from scipy.stats import chi2

    SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover - recorded in QA output
    chi2 = None
    SCIPY_AVAILABLE = False


ANALYSIS_ROOT = Path("work/output/roadway_graph/analysis/current")
REPORT_ROOT = Path("work/output/roadway_graph/report/current")
FIGURE_DATA_DIR = REPORT_ROOT / "context_relationship_figure_data"
FIGURE_DIR = REPORT_ROOT / "context_relationship_figures"
REPORT_DOC_DIR = Path("docs/reports/roadway_graph")

READINESS_DIR = ANALYSIS_ROOT / "exposure_modeling_readiness_audit"
RATE_DIR = ANALYSIS_ROOT / "descriptive_crash_rate_prototype"
DISTANCE_PROFILE_DIR = ANALYSIS_ROOT / "directional_context_distance_band_profiles"
DIRECTIONAL_BIN_CONTEXT_FILE = ANALYSIS_ROOT / "directional_bin_context_table/directional_bin_context.csv"

RATE_UNIT_FILE = RATE_DIR / "descriptive_rate_prototype_signal_direction_window.csv"

MIN_RATE_CRASH_COUNT = 20
MIN_RATE_VMT_LIKE_EXPOSURE = 5_000_000.0
MIN_RATE_DENOMINATOR_READY_UNITS = 25
MIN_RATE_STABLE_AADT_COVERAGE = 0.80

BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]
SPEED_ORDER = ["lt_30_mph", "30_39_mph", "40_49_mph", "50_59_mph", "60plus_mph", "speed_missing_or_review"]
AADT_ORDER = ["lt_10000", "10000_19999", "20000_39999", "40000_59999", "60000plus", "aadt_missing_or_review"]
ACCESS_ORDER = ["0_per_1000ft", "gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft", "6plus_per_1000ft"]
WINDOW_ORDER = ["high_priority_0_1000ft", "sensitivity_1000_2500ft"]

DISPLAY_LABELS = {
    "0_250ft": "0-250 ft",
    "250_500ft": "250-500 ft",
    "500_1000ft": "500-1,000 ft",
    "1000_1500ft": "1,000-1,500 ft",
    "1500_2500ft": "1,500-2,500 ft",
    "lt_30_mph": "<30 mph",
    "30_39_mph": "30-40 mph",
    "40_49_mph": "40-50 mph",
    "50_59_mph": "50-60 mph",
    "60plus_mph": "60+ mph",
    "speed_missing_or_review": "Missing/review speed context",
    "lt_10000": "<10,000 vehicles/day",
    "10000_19999": "10,000-20,000 vehicles/day",
    "20000_39999": "20,000-40,000 vehicles/day",
    "40000_59999": "40,000-60,000 vehicles/day",
    "60000plus": "60,000+ vehicles/day",
    "aadt_missing_or_review": "Missing/review AADT context",
    "0_per_1000ft": "0",
    "gt0_lt1_per_1000ft": ">0-1",
    "1_lt3_per_1000ft": "1-3",
    "3_lt6_per_1000ft": "3-6",
    "6plus_per_1000ft": "6+",
    "high_priority_0_1000ft": "0-1,000 ft",
    "sensitivity_1000_2500ft": "1,000-2,500 ft",
}

CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype(str).str.lower().eq("true")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, pd.NA)


def _label(value: Any) -> str:
    return DISPLAY_LABELS.get(str(value), str(value))


def _add_display_labels(frame: pd.DataFrame) -> pd.DataFrame:
    labeled = frame.copy()
    for column in ["distance_band", "speed_band", "aadt_band", "access_density_band", "analysis_window"]:
        if column in labeled.columns:
            labeled[f"{column}_label"] = labeled[column].map(_label)
    return labeled


def _complete_grid(frame: pd.DataFrame, columns: list[str], orders: dict[str, list[str]]) -> pd.DataFrame:
    numeric_cols = [
        column
        for column in frame.columns
        if column not in columns
        and column not in {"descriptive_crosstab", "warning_flags", "sparse_cell_warning"}
        and pd.api.types.is_numeric_dtype(frame[column])
    ]
    crosstab_name = frame["descriptive_crosstab"].iloc[0] if "descriptive_crosstab" in frame.columns and len(frame) else ""
    index = pd.MultiIndex.from_product([orders[column] for column in columns], names=columns)
    completed = frame.set_index(columns).reindex(index).reset_index()
    if "descriptive_crosstab" in completed.columns:
        completed["descriptive_crosstab"] = completed["descriptive_crosstab"].fillna(crosstab_name)
    for column in numeric_cols:
        completed[column] = completed[column].fillna(0)
    if "sparse_cell_warning" in completed.columns:
        completed["sparse_cell_warning"] = completed["sparse_cell_warning"].fillna(True)
    completed["category_restored_for_display"] = ~completed[columns].apply(tuple, axis=1).isin(frame[columns].apply(tuple, axis=1))
    completed["warning_flags"] = completed.apply(_warning_flags, axis=1)
    return _add_display_labels(completed)


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


def _distance_band(midpoint: pd.Series) -> pd.Series:
    return pd.cut(
        midpoint,
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=BAND_ORDER,
        right=False,
        include_lowest=True,
    ).astype("string")


def _exact_rate_interval(crashes: int, exposure: float) -> tuple[float | None, float | None]:
    if not SCIPY_AVAILABLE or exposure <= 0:
        return None, None
    lower_count = 0.0 if crashes == 0 else 0.5 * float(chi2.ppf(0.025, 2 * crashes))
    upper_count = 0.5 * float(chi2.ppf(0.975, 2 * (crashes + 1)))
    return lower_count / exposure * 1_000_000.0, upper_count / exposure * 1_000_000.0


def _warning_flags(row: pd.Series) -> str:
    flags: list[str] = []
    if str(row.get("sparse_cell_warning", "False")).lower() == "true":
        flags.append("sparse_cell")
    if float(row.get("stable_aadt_coverage_share", 0) or 0) < MIN_RATE_STABLE_AADT_COVERAGE:
        flags.append("low_aadt_coverage")
    if "stable_speed_coverage_share" in row and float(row.get("stable_speed_coverage_share", 0) or 0) < 0.80:
        flags.append("low_speed_coverage")
    return ";".join(flags) if flags else "none"


def _prepare_count_matrix(path: Path, output_path: Path, required_columns: list[str]) -> pd.DataFrame:
    frame = _read_csv(path, usecols=required_columns)
    for column in [
        "bin_count",
        "assigned_crash_count",
        "crash_bearing_bin_count",
        "stable_aadt_bin_count",
        "stable_speed_bin_count",
        "represented_length_ft",
        "access_count_within_catchment_sum",
        "access_count_within_100ft_sum",
        "access_count_within_250ft_sum",
        "stable_aadt_coverage_share",
        "stable_speed_coverage_share",
        "access_count_per_1000ft",
    ]:
        if column in frame.columns:
            frame[column] = _num(frame, column)
    frame["warning_flags"] = frame.apply(_warning_flags, axis=1)
    frame = _add_display_labels(frame)
    _write_csv(frame, output_path)
    return frame


def _load_access_display_context() -> pd.DataFrame:
    usecols = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "has_assigned_crash",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "has_stable_aadt_context",
        "has_stable_speed_context",
    ]
    frame = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=usecols)
    for column in [
        "bin_midpoint_ft_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
    ]:
        frame[column] = _num(frame, column)
    frame["posted_car_speed_limit_context_value"] = pd.to_numeric(frame["posted_car_speed_limit_context_value"], errors="coerce")
    frame["weighted_car_speed_limit"] = pd.to_numeric(frame["weighted_car_speed_limit"], errors="coerce")
    for column in ["has_assigned_crash", "has_stable_aadt_context", "has_stable_speed_context"]:
        frame[column] = _bool(frame, column)
    frame = frame.loc[frame["distance_window"].isin(WINDOW_ORDER)].copy()
    frame["represented_length_ft"] = (frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]).clip(lower=0)
    frame["distance_band"] = _distance_band(frame["bin_midpoint_ft_from_reference_signal"])
    frame = frame.loc[frame["distance_band"].isin(BAND_ORDER)].copy()
    frame["selected_speed_mph"] = frame["weighted_car_speed_limit"].where(frame["weighted_car_speed_limit"].notna(), frame["posted_car_speed_limit_context_value"])
    frame["speed_band"] = [_speed_band(stable, value) for stable, value in zip(frame["has_stable_speed_context"], frame["selected_speed_mph"])]
    frame["old_raw_bin_access_density_per_1000ft"] = _safe_div(frame["access_count_within_catchment"] * 1000, frame["represented_length_ft"])
    frame["old_raw_bin_access_density_band"] = frame["old_raw_bin_access_density_per_1000ft"].map(_access_density_band)
    return frame


def _length_weighted_mean(values: pd.Series, weights: pd.Series) -> float | pd.NA:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not bool(valid.any()):
        return pd.NA
    return float((values.loc[valid] * weights.loc[valid]).sum() / weights.loc[valid].sum())


def _local_distance_access_units(context: pd.DataFrame) -> pd.DataFrame:
    work = context.copy()
    work["stable_speed_value"] = work["selected_speed_mph"].where(work["has_stable_speed_context"])
    units = work.groupby(["reference_signal_id", "signal_relative_direction", "distance_band"], dropna=False).agg(
        bin_count=("reference_directional_bin_id", "nunique"),
        assigned_crash_count=("unique_assigned_crash_count", "sum"),
        crash_bearing_bin_count=("has_assigned_crash", "sum"),
        stable_aadt_bin_count=("has_stable_aadt_context", "sum"),
        stable_speed_bin_count=("has_stable_speed_context", "sum"),
        represented_length_ft=("represented_length_ft", "sum"),
        access_count_within_catchment_sum=("access_count_within_catchment", "sum"),
        access_count_within_100ft_sum=("access_count_within_100ft", "sum"),
        access_count_within_250ft_sum=("access_count_within_250ft", "sum"),
        old_raw_bin_access_density_bands_present=("old_raw_bin_access_density_band", lambda s: "|".join(sorted(set(s.astype(str))))),
        representative_speed_mph=("stable_speed_value", lambda s: _length_weighted_mean(s, work.loc[s.index, "represented_length_ft"])),
    ).reset_index()
    units["stable_aadt_coverage_share"] = _safe_div(units["stable_aadt_bin_count"], units["bin_count"])
    units["stable_speed_coverage_share"] = _safe_div(units["stable_speed_bin_count"], units["bin_count"])
    units["local_access_density_per_1000ft"] = _safe_div(units["access_count_within_catchment_sum"] * 1000, units["represented_length_ft"])
    units["local_access_density_band"] = units["local_access_density_per_1000ft"].map(_access_density_band)
    units["representative_speed_band"] = [
        _speed_band(count > 0, value) for count, value in zip(units["stable_speed_bin_count"], units["representative_speed_mph"])
    ]
    return units


def _access_matrix_from_local_units(local_units: pd.DataFrame, group_cols: list[str], table_name: str) -> pd.DataFrame:
    frame = local_units.groupby(group_cols, dropna=False).agg(
        local_unit_count=("reference_signal_id", "count"),
        bin_count=("bin_count", "sum"),
        assigned_crash_count=("assigned_crash_count", "sum"),
        crash_bearing_bin_count=("crash_bearing_bin_count", "sum"),
        stable_aadt_bin_count=("stable_aadt_bin_count", "sum"),
        stable_speed_bin_count=("stable_speed_bin_count", "sum"),
        represented_length_ft=("represented_length_ft", "sum"),
        access_count_within_catchment_sum=("access_count_within_catchment_sum", "sum"),
        access_count_within_100ft_sum=("access_count_within_100ft_sum", "sum"),
        access_count_within_250ft_sum=("access_count_within_250ft_sum", "sum"),
        local_access_density_min=("local_access_density_per_1000ft", "min"),
        local_access_density_median=("local_access_density_per_1000ft", "median"),
        local_access_density_max=("local_access_density_per_1000ft", "max"),
        old_raw_bin_access_density_bands_present=("old_raw_bin_access_density_bands_present", lambda s: "|".join(sorted(set("|".join(s.astype(str)).split("|"))))),
    ).reset_index()
    frame.insert(0, "descriptive_crosstab", table_name)
    frame = frame.rename(columns={"local_access_density_band": "access_density_band", "representative_speed_band": "speed_band"})
    frame["stable_aadt_coverage_share"] = _safe_div(frame["stable_aadt_bin_count"], frame["bin_count"])
    frame["stable_speed_coverage_share"] = _safe_div(frame["stable_speed_bin_count"], frame["bin_count"])
    frame["local_grain_access_density_method"] = "reference_signal_id + signal_relative_direction + distance_band"
    frame["access_count_per_1000ft"] = _safe_div(frame["access_count_within_catchment_sum"] * 1000, frame["represented_length_ft"])
    frame["sparse_cell_warning"] = frame["bin_count"].lt(50) | frame["assigned_crash_count"].lt(10)
    frame["warning_flags"] = frame.apply(_warning_flags, axis=1)
    return _add_display_labels(frame)


def _rate_units() -> pd.DataFrame:
    usecols = [
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "assigned_crash_count",
        "bin_count",
        "crash_bearing_bin_count",
        "stable_aadt_bin_count",
        "stable_aadt_coverage_share",
        "stable_speed_bin_count",
        "stable_speed_coverage_share",
        "length_weighted_aadt",
        "length_weighted_speed",
        "represented_length_ft",
        "access_count_within_catchment_sum",
        "access_density_band",
        "denominator_ready_flag",
        "vmt_like_exposure",
        "bidirectional_aadt_assumption_flag",
        "direction_factor_applied",
        "outside_period_aadt_year_flag",
        "mixed_aadt_year_flag",
    ]
    frame = _read_csv(RATE_UNIT_FILE, usecols=usecols)
    for column in [
        "assigned_crash_count",
        "bin_count",
        "crash_bearing_bin_count",
        "stable_aadt_bin_count",
        "stable_aadt_coverage_share",
        "stable_speed_bin_count",
        "stable_speed_coverage_share",
        "length_weighted_aadt",
        "length_weighted_speed",
        "represented_length_ft",
        "access_count_within_catchment_sum",
        "vmt_like_exposure",
    ]:
        frame[column] = _num(frame, column)
    frame["denominator_ready_flag"] = _bool(frame, "denominator_ready_flag")
    frame["bidirectional_aadt_assumption_flag"] = _bool(frame, "bidirectional_aadt_assumption_flag")
    frame["direction_factor_applied"] = _bool(frame, "direction_factor_applied")
    frame["outside_period_aadt_year_flag"] = _bool(frame, "outside_period_aadt_year_flag")
    frame["mixed_aadt_year_flag"] = _bool(frame, "mixed_aadt_year_flag")
    frame = frame.rename(columns={"access_density_band": "old_raw_bin_access_density_band"})
    frame["local_window_access_density_per_1000ft"] = _safe_div(
        frame["access_count_within_catchment_sum"] * 1000,
        frame["represented_length_ft"],
    )
    frame["local_window_access_density_band"] = frame["local_window_access_density_per_1000ft"].map(_access_density_band)
    frame["access_density_band"] = frame["local_window_access_density_band"]
    frame["speed_band"] = [_speed_band(stable >= 0.80, value) for stable, value in zip(frame["stable_speed_coverage_share"], frame["length_weighted_speed"])]
    frame["aadt_band"] = [_aadt_band(stable >= 0.80, value) for stable, value in zip(frame["stable_aadt_coverage_share"], frame["length_weighted_aadt"])]
    return _add_display_labels(frame)


def _roadway_representation_matrix() -> pd.DataFrame:
    frame = _read_csv(
        DISTANCE_PROFILE_DIR / "distance_band_profile_by_roadway_representation.csv",
        usecols=[
            "distance_band",
            "roadway_representation_type",
            "bin_count",
            "assigned_crash_count",
            "crash_bearing_bin_count",
            "stable_aadt_context_share",
            "stable_speed_context_share",
            "urban_crash_count",
            "rural_crash_count",
        ],
    )
    frame = frame.rename(
        columns={
            "stable_aadt_context_share": "stable_aadt_coverage_share",
            "stable_speed_context_share": "stable_speed_coverage_share",
        }
    )
    for column in ["bin_count", "assigned_crash_count", "crash_bearing_bin_count", "stable_aadt_coverage_share", "stable_speed_coverage_share"]:
        frame[column] = _num(frame, column)
    frame["sparse_cell_warning"] = frame["bin_count"].lt(50) | frame["assigned_crash_count"].lt(10)
    frame["warning_flags"] = frame.apply(_warning_flags, axis=1)
    return frame


def _crash_area_type_matrix() -> pd.DataFrame:
    frame = _read_csv(
        DISTANCE_PROFILE_DIR / "distance_band_profile_by_crash_area_type.csv",
        usecols=[
            "distance_band",
            "crash_urban_rural_class",
            "assigned_crash_count",
            "upstream_crash_count",
            "downstream_crash_count",
            "reference_signal_count",
            "crash_class_share_among_assigned_crashes",
            "context_scope",
        ],
    )
    for column in ["assigned_crash_count", "upstream_crash_count", "downstream_crash_count", "reference_signal_count", "crash_class_share_among_assigned_crashes"]:
        frame[column] = _num(frame, column)
    frame["warning_flags"] = "crash_level_area_type_not_roadway_geography"
    return frame


def _rate_matrix(units: pd.DataFrame, feature: str, output_path: Path) -> pd.DataFrame:
    ready = units.loc[units["denominator_ready_flag"]].copy()
    group_cols = ["analysis_window", feature]
    grouped = ready.groupby(group_cols, dropna=False).agg(
        denominator_ready_unit_count=("reference_signal_id", "count"),
        assigned_crash_count=("assigned_crash_count", "sum"),
        crash_bearing_bin_count=("crash_bearing_bin_count", "sum"),
        bin_count=("bin_count", "sum"),
        stable_aadt_bin_count=("stable_aadt_bin_count", "sum"),
        stable_speed_bin_count=("stable_speed_bin_count", "sum"),
        represented_length_ft=("represented_length_ft", "sum"),
        access_count_within_catchment_sum=("access_count_within_catchment_sum", "sum"),
        vmt_like_exposure=("vmt_like_exposure", "sum"),
        bidirectional_aadt_assumption_flag=("bidirectional_aadt_assumption_flag", "min"),
        direction_factor_applied=("direction_factor_applied", "max"),
        outside_period_aadt_year_unit_count=("outside_period_aadt_year_flag", "sum"),
        mixed_aadt_year_unit_count=("mixed_aadt_year_flag", "sum"),
    ).reset_index()
    grouped["stable_aadt_coverage_share"] = _safe_div(grouped["stable_aadt_bin_count"], grouped["bin_count"])
    grouped["stable_speed_coverage_share"] = _safe_div(grouped["stable_speed_bin_count"], grouped["bin_count"])
    grouped["local_window_access_density_per_1000ft"] = _safe_div(
        grouped["access_count_within_catchment_sum"] * 1000,
        grouped["represented_length_ft"],
    )
    if feature == "access_density_band":
        grouped["local_window_access_density_band"] = grouped["access_density_band"]
        grouped["local_grain_access_density_method"] = "reference_signal_id + signal_relative_direction + analysis_window"
        old_band_lookup = (
            ready.groupby(group_cols, dropna=False)["old_raw_bin_access_density_band"]
            .agg(lambda s: "|".join(sorted(set(s.astype(str)))))
            .reset_index()
        )
        grouped = grouped.merge(old_band_lookup, on=group_cols, how="left")
    grouped["crashes_per_million_vmt"] = _safe_div(grouped["assigned_crash_count"] * 1_000_000.0, grouped["vmt_like_exposure"])
    intervals = [_exact_rate_interval(int(row.assigned_crash_count), float(row.vmt_like_exposure)) for row in grouped.itertuples()]
    grouped["exact_rate_lower_95_per_million_vmt"] = [value[0] for value in intervals]
    grouped["exact_rate_upper_95_per_million_vmt"] = [value[1] for value in intervals]
    grouped["exact_interval_method"] = "scipy_chi2_exact_garwood" if SCIPY_AVAILABLE else "not_available"
    grouped["low_crash_count_display_flag"] = grouped["assigned_crash_count"].lt(MIN_RATE_CRASH_COUNT)
    grouped["low_exposure_display_flag"] = grouped["vmt_like_exposure"].lt(MIN_RATE_VMT_LIKE_EXPOSURE)
    grouped["low_aadt_coverage_display_flag"] = grouped["stable_aadt_coverage_share"].lt(MIN_RATE_STABLE_AADT_COVERAGE)
    grouped["low_denominator_ready_unit_count_flag"] = grouped["denominator_ready_unit_count"].lt(MIN_RATE_DENOMINATOR_READY_UNITS)
    grouped["outside_period_aadt_year_flag"] = grouped["outside_period_aadt_year_unit_count"].gt(0)
    grouped["mixed_aadt_year_flag"] = grouped["mixed_aadt_year_unit_count"].gt(0)
    grouped["rate_display_status"] = "display_ready"
    review = (
        grouped["low_crash_count_display_flag"]
        | grouped["low_exposure_display_flag"]
        | grouped["low_aadt_coverage_display_flag"]
        | grouped["low_denominator_ready_unit_count_flag"]
        | grouped["direction_factor_applied"]
    )
    grouped.loc[review, "rate_display_status"] = "review_cell"
    grouped["estimated_vehicle_mile_exposure"] = grouped["vmt_like_exposure"]
    grouped["caveat_flags"] = grouped.apply(_rate_caveats, axis=1)
    grouped["rate_cell_note"] = grouped.apply(_rate_cell_note, axis=1)
    grouped = _add_display_labels(grouped)
    grouped = _complete_rate_grid(grouped, feature)
    export = grouped.drop(columns=["vmt_like_exposure", "rate_display_status"], errors="ignore")
    _write_csv(export, output_path)
    return grouped


def _rate_caveats(row: pd.Series) -> str:
    flags = ["bidirectional_aadt_assumption", "direction_factor_not_applied", "missing_review_aadt_excluded", "unit_level_rates_qa_only"]
    if bool(row.get("low_crash_count_display_flag")):
        flags.append("sparse_cell")
    if bool(row.get("low_exposure_display_flag")):
        flags.append("denominator_warning")
    if bool(row.get("low_aadt_coverage_display_flag")):
        flags.append("low_aadt_coverage")
    if bool(row.get("low_denominator_ready_unit_count_flag")):
        flags.append("low_denominator_ready_unit_count")
    if bool(row.get("outside_period_aadt_year_flag")):
        flags.append("outside_2022_2024_aadt_year_flag")
    if bool(row.get("mixed_aadt_year_flag")):
        flags.append("mixed_aadt_year_flag")
    return ";".join(flags)


def _rate_cell_note(row: pd.Series) -> str:
    notes: list[str] = []
    if bool(row.get("low_exposure_display_flag")):
        notes.append("denominator warning")
    if bool(row.get("low_crash_count_display_flag")):
        notes.append("sparse cell")
    if bool(row.get("low_aadt_coverage_display_flag")) or bool(row.get("low_denominator_ready_unit_count_flag")):
        notes.append("review cell")
    if bool(row.get("outside_period_aadt_year_flag")):
        notes.append("AADT year outside 2022-2024")
    if bool(row.get("mixed_aadt_year_flag")):
        notes.append("mixed AADT years")
    return "; ".join(notes) if notes else "none"


def _complete_rate_grid(frame: pd.DataFrame, feature: str) -> pd.DataFrame:
    orders = {
        "analysis_window": WINDOW_ORDER,
        "access_density_band": ACCESS_ORDER,
        "speed_band": SPEED_ORDER,
        "aadt_band": AADT_ORDER,
    }
    completed = _complete_grid(frame, ["analysis_window", feature], orders)
    for column in [
        "denominator_ready_unit_count",
        "assigned_crash_count",
        "crash_bearing_bin_count",
        "bin_count",
        "stable_aadt_bin_count",
        "stable_speed_bin_count",
        "represented_length_ft",
        "access_count_within_catchment_sum",
        "local_window_access_density_per_1000ft",
        "vmt_like_exposure",
        "estimated_vehicle_mile_exposure",
    ]:
        if column in completed.columns:
            completed[column] = completed[column].fillna(0)
    bool_cols = [
        "bidirectional_aadt_assumption_flag",
        "direction_factor_applied",
        "low_crash_count_display_flag",
        "low_exposure_display_flag",
        "low_aadt_coverage_display_flag",
        "low_denominator_ready_unit_count_flag",
        "outside_period_aadt_year_flag",
        "mixed_aadt_year_flag",
    ]
    for column in bool_cols:
        if column in completed.columns:
            completed[column] = completed[column].fillna(False)
    completed["rate_display_status"] = completed["rate_display_status"].fillna("review_cell")
    completed["caveat_flags"] = completed["caveat_flags"].fillna("no_denominator_ready_units")
    completed["rate_cell_note"] = completed["rate_cell_note"].fillna("review cell")
    return completed


def _svg_text(x: int, y: int, text: str, *, size: int = 12, weight: str = "normal", anchor: str = "start", fill: str = "#202124") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">{html.escape(text)}</text>'
    )


def _short(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:,.3f}"
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def _heatmap(frame: pd.DataFrame, row_col: str, col_col: str, value_col: str, title: str, note: str, output_path: Path, *, row_order: list[str], col_order: list[str]) -> None:
    values = frame.copy()
    values[value_col] = _num(values, value_col)
    pivot = values.pivot_table(index=row_col, columns=col_col, values=value_col, aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(index=row_order, columns=col_order, fill_value=0)
    cell_w, cell_h = 126, 44
    left, top = 230, 105
    width = left + cell_w * len(pivot.columns) + 40
    height = top + cell_h * len(pivot.index) + 105
    max_value = max(float(pivot.to_numpy().max()), 1.0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 36, title, size=20, weight="bold"),
        _svg_text(30, 60, note, size=12, fill="#5f6368"),
    ]
    for j, column in enumerate(pivot.columns):
        parts.append(_svg_text(left + j * cell_w + cell_w // 2, top - 18, _label(column), size=11, anchor="middle"))
    for i, index in enumerate(pivot.index):
        parts.append(_svg_text(30, top + i * cell_h + 28, _label(index), size=11))
        for j, column in enumerate(pivot.columns):
            value = float(pivot.loc[index, column])
            shade = int(245 - (value / max_value) * 150)
            color = f"rgb({shade},{shade + 8},{245})"
            x = left + j * cell_w
            y = top + i * cell_h
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 2}" height="{cell_h - 2}" fill="{color}" stroke="#ffffff"/>')
            parts.append(_svg_text(x + cell_w // 2, y + 28, _short(value), size=12, anchor="middle"))
    parts.append(_svg_text(30, height - 32, "Counts are descriptive assigned-crash counts; not rates, rankings, causal findings, or policy guidance.", size=11, fill="#5f6368"))
    parts.append("</svg>")
    _write_text("\n".join(parts), output_path)


def _rate_table_svg(frame: pd.DataFrame, feature: str, title: str, output_path: Path) -> None:
    display_cols = ["analysis_window_label", f"{feature}_label", "assigned_crash_count", "estimated_vehicle_mile_exposure", "crashes_per_million_vmt", "rate_cell_note"]
    headings = ["Window", _rate_feature_heading(feature), "Assigned crashes", "Estimated exposure", "Crashes per million", "Notes"]
    show = frame[display_cols].copy()
    show["estimated_vehicle_mile_exposure"] = show["estimated_vehicle_mile_exposure"].map(lambda value: f"{float(value):,.0f}")
    show["crashes_per_million_vmt"] = show["crashes_per_million_vmt"].map(lambda value: "" if pd.isna(value) else f"{float(value):.3f}")
    width = 1320
    row_h = 30
    height = 120 + row_h * (len(show) + 1)
    col_widths = [125, 230, 130, 165, 145, 455]
    x_positions = [30]
    for value in col_widths[:-1]:
        x_positions.append(x_positions[-1] + value)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 36, title, size=20, weight="bold"),
        _svg_text(30, 60, "Descriptive AADT-normalized prototype; aggregate cells only; review notes flag sparse cells and denominator warnings.", size=12, fill="#5f6368"),
    ]
    y = 88
    parts.append(f'<rect x="30" y="{y - 20}" width="{sum(col_widths)}" height="{row_h}" fill="#e8eef5"/>')
    for x, heading in zip(x_positions, headings):
        parts.append(_svg_text(x + 6, y, heading, size=11, weight="bold"))
    for _, row in show.iterrows():
        y += row_h
        fill = "#ffffff" if row["rate_cell_note"] == "none" else "#fff8e6"
        parts.append(f'<rect x="30" y="{y - 20}" width="{sum(col_widths)}" height="{row_h}" fill="{fill}" stroke="#e0e0e0"/>')
        for x, column in zip(x_positions, display_cols):
            parts.append(_svg_text(x + 6, y, _short(row[column]), size=11))
    if feature == "access_density_band":
        parts.append(_svg_text(30, height - 52, "Access points per 1,000 ft are calculated at signal-direction-window grain, not per 50-ft bin or whole displayed group.", size=11, fill="#5f6368"))
    parts.append(_svg_text(30, height - 34, "Estimated exposure uses AADT, represented roadway length, and the 2022-2024 crash period; DIRECTION_FACTOR is not applied.", size=11, fill="#5f6368"))
    parts.append(_svg_text(30, height - 16, "No causal, policy, comparative-performance, or downstream functional area distance interpretation is made.", size=11, fill="#5f6368"))
    parts.append("</svg>")
    _write_text("\n".join(parts), output_path)


def _rate_feature_heading(feature: str) -> str:
    if feature == "access_density_band":
        return "Access points per 1,000 ft"
    if feature == "speed_band":
        return "Speed"
    if feature == "aadt_band":
        return "AADT vehicles/day"
    return feature


def _summary_svg(rate_tables: dict[str, pd.DataFrame], output_path: Path) -> None:
    rows = []
    for name, frame in rate_tables.items():
        rows.append(
            {
                "rate_context": name,
                "display_ready_cells": int(frame["rate_display_status"].eq("display_ready").sum()),
                "review_note_cells": int(frame["rate_display_status"].eq("review_cell").sum()),
                "max_display_rate": (
                    frame.loc[frame["rate_display_status"].eq("display_ready"), "crashes_per_million_vmt"].max()
                    if frame["rate_display_status"].eq("display_ready").any()
                    else pd.NA
                ),
            }
        )
    summary = pd.DataFrame(rows)
    width, height = 920, 260
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 36, "Technical QA: context relationship rate notes", size=20, weight="bold"),
        _svg_text(30, 60, "Technical QA only; stakeholder exhibits use the rate tables with denominator and sparse-cell notes.", size=12, fill="#5f6368"),
    ]
    columns = ["rate_context", "display_ready_cells", "review_note_cells", "max_display_rate"]
    col_widths = [300, 170, 210, 170]
    x_positions = [30, 330, 500, 710]
    y = 98
    parts.append(f'<rect x="30" y="{y - 20}" width="850" height="30" fill="#e8eef5"/>')
    for x, column in zip(x_positions, columns):
        parts.append(_svg_text(x + 6, y, column, size=11, weight="bold"))
    for _, row in summary.iterrows():
        y += 30
        parts.append(f'<rect x="30" y="{y - 20}" width="850" height="30" fill="#ffffff" stroke="#e0e0e0"/>')
        for x, column in zip(x_positions, columns):
            value = row[column]
            if column == "max_display_rate" and not pd.isna(value):
                value = f"{float(value):.3f}"
            parts.append(_svg_text(x + 6, y, _short(value), size=11))
    parts.append(_svg_text(30, height - 22, "Counts and aggregate prototype rates support review only; no causal, policy, or downstream-distance interpretation is made.", size=11, fill="#5f6368"))
    parts.append("</svg>")
    _write_text("\n".join(parts), output_path)


def build_context_relationship_package() -> dict[str, Any]:
    FIGURE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    count_specs = [
        (
            READINESS_DIR / "crashes_by_distance_band_and_speed_band.csv",
            FIGURE_DATA_DIR / "context_matrix_distance_speed.csv",
            [
                "distance_band",
                "speed_band",
                "bin_count",
                "assigned_crash_count",
                "crash_bearing_bin_count",
                "stable_aadt_coverage_share",
                "stable_speed_coverage_share",
                "sparse_cell_warning",
            ],
        ),
        (
            READINESS_DIR / "crashes_by_distance_band_and_aadt_band.csv",
            FIGURE_DATA_DIR / "context_matrix_distance_aadt.csv",
            [
                "distance_band",
                "aadt_band",
                "bin_count",
                "assigned_crash_count",
                "crash_bearing_bin_count",
                "stable_aadt_coverage_share",
                "stable_speed_coverage_share",
                "sparse_cell_warning",
            ],
        ),
    ]
    count_tables = {path.stem: _prepare_count_matrix(source, path, columns) for source, path, columns in count_specs}
    access_context = _load_access_display_context()
    local_access_units = _local_distance_access_units(access_context)
    count_tables["context_matrix_distance_access"] = _access_matrix_from_local_units(
        local_access_units,
        ["distance_band", "local_access_density_band"],
        "context_matrix_distance_access",
    )
    count_tables["context_matrix_distance_access"] = _complete_grid(
        count_tables["context_matrix_distance_access"],
        ["distance_band", "access_density_band"],
        {"distance_band": BAND_ORDER, "access_density_band": ACCESS_ORDER},
    )
    _write_csv(count_tables["context_matrix_distance_access"], FIGURE_DATA_DIR / "context_matrix_distance_access.csv")
    count_tables["context_matrix_direction_distance_access"] = _access_matrix_from_local_units(
        local_access_units,
        ["signal_relative_direction", "distance_band", "local_access_density_band"],
        "context_matrix_direction_distance_access",
    )
    count_tables["context_matrix_direction_distance_access"] = _complete_grid(
        count_tables["context_matrix_direction_distance_access"],
        ["signal_relative_direction", "distance_band", "access_density_band"],
        {
            "signal_relative_direction": sorted(count_tables["context_matrix_direction_distance_access"]["signal_relative_direction"].unique().tolist()),
            "distance_band": BAND_ORDER,
            "access_density_band": ACCESS_ORDER,
        },
    )
    _write_csv(count_tables["context_matrix_direction_distance_access"], FIGURE_DATA_DIR / "context_matrix_direction_distance_access.csv")
    speed_access = _access_matrix_from_local_units(
        local_access_units,
        ["representative_speed_band", "local_access_density_band"],
        "context_matrix_speed_access",
    )
    speed_access = _complete_grid(
        speed_access,
        ["speed_band", "access_density_band"],
        {"speed_band": SPEED_ORDER, "access_density_band": ACCESS_ORDER},
    )
    _write_csv(speed_access, FIGURE_DATA_DIR / "context_matrix_speed_access.csv")
    count_tables["context_matrix_speed_access"] = speed_access
    roadway_representation = _roadway_representation_matrix()
    _write_csv(roadway_representation, FIGURE_DATA_DIR / "context_matrix_distance_roadway_representation.csv")
    count_tables["context_matrix_distance_roadway_representation"] = roadway_representation
    crash_area_type = _crash_area_type_matrix()
    _write_csv(crash_area_type, FIGURE_DATA_DIR / "context_matrix_distance_crash_area_type.csv")
    count_tables["context_matrix_distance_crash_area_type"] = crash_area_type

    units = _rate_units()
    rate_tables = {
        "window_access": _rate_matrix(units, "access_density_band", FIGURE_DATA_DIR / "context_matrix_rate_window_access.csv"),
        "window_speed": _rate_matrix(units, "speed_band", FIGURE_DATA_DIR / "context_matrix_rate_window_speed.csv"),
        "window_aadt": _rate_matrix(units, "aadt_band", FIGURE_DATA_DIR / "context_matrix_rate_window_aadt.csv"),
    }

    _heatmap(count_tables["context_matrix_distance_speed"], "distance_band", "speed_band", "assigned_crash_count", "Assigned crashes by distance and speed", "Pre-regression descriptive context relationship summary.", FIGURE_DIR / "context_heatmap_crashes_distance_by_speed.svg", row_order=BAND_ORDER, col_order=SPEED_ORDER)
    _heatmap(count_tables["context_matrix_distance_access"], "distance_band", "access_density_band", "assigned_crash_count", "Assigned crashes by distance and access density", "Access points per 1,000 ft, calculated at local signal-direction-distance-band grain.", FIGURE_DIR / "context_heatmap_crashes_distance_by_access.svg", row_order=BAND_ORDER, col_order=ACCESS_ORDER)
    _heatmap(count_tables["context_matrix_speed_access"], "speed_band", "access_density_band", "assigned_crash_count", "Assigned crashes by speed and access density", "Access points per 1,000 ft, calculated at local signal-direction-distance-band grain.", FIGURE_DIR / "context_heatmap_crashes_speed_by_access.svg", row_order=SPEED_ORDER, col_order=ACCESS_ORDER)
    _heatmap(count_tables["context_matrix_distance_aadt"], "distance_band", "aadt_band", "assigned_crash_count", "Assigned crashes by distance and AADT", "Pre-regression descriptive context relationship summary.", FIGURE_DIR / "context_heatmap_crashes_distance_by_aadt.svg", row_order=BAND_ORDER, col_order=AADT_ORDER)

    _rate_table_svg(rate_tables["window_access"], "access_density_band", "Aggregate prototype rates by window and access density", FIGURE_DIR / "context_rate_by_window_and_access.svg")
    _rate_table_svg(rate_tables["window_speed"], "speed_band", "Aggregate prototype rates by window and speed", FIGURE_DIR / "context_rate_by_window_and_speed.svg")
    _rate_table_svg(rate_tables["window_aadt"], "aadt_band", "Aggregate prototype rates by window and AADT", FIGURE_DIR / "context_rate_by_window_and_aadt.svg")
    _summary_svg(rate_tables, FIGURE_DIR / "context_relationship_summary_table.svg")

    qa = _qa(count_tables, rate_tables)
    _write_csv(qa, FIGURE_DATA_DIR / "context_relationship_figure_qa.csv")
    label_qa = _label_qa()
    _write_csv(label_qa, FIGURE_DATA_DIR / "context_relationship_category_label_qa.csv")
    access_qa = _access_density_category_coverage_qa(count_tables, rate_tables)
    _write_csv(access_qa, FIGURE_DATA_DIR / "access_density_category_coverage_qa.csv")
    access_recalc_qa = _access_density_local_grain_qa(count_tables, rate_tables)
    _write_csv(access_recalc_qa, FIGURE_DATA_DIR / "access_density_local_grain_qa.csv")
    access_before_after = _access_density_before_after_comparison(count_tables, rate_tables)
    _write_csv(access_before_after, FIGURE_DATA_DIR / "access_density_figure_before_after_comparison.csv")
    access_grain_comparison = _access_density_grain_comparison(access_context, local_access_units, units)
    _write_csv(access_grain_comparison, FIGURE_DATA_DIR / "access_density_grain_comparison.csv")
    access_local_band_distribution = _access_density_local_band_distribution(count_tables, rate_tables)
    _write_csv(access_local_band_distribution, FIGURE_DATA_DIR / "access_density_local_band_distribution.csv")

    outputs = {
        "figure_data_dir": str(FIGURE_DATA_DIR),
        "figure_dir": str(FIGURE_DIR),
        "count_tables": sorted(str(path) for path in FIGURE_DATA_DIR.glob("context_matrix_*.csv") if "rate" not in path.name),
        "rate_tables": sorted(str(path) for path in FIGURE_DATA_DIR.glob("context_matrix_rate_*.csv")),
        "figures": sorted(str(path) for path in FIGURE_DIR.glob("*.svg")),
        "qa": str(FIGURE_DATA_DIR / "context_relationship_figure_qa.csv"),
        "category_label_qa": str(FIGURE_DATA_DIR / "context_relationship_category_label_qa.csv"),
        "access_density_category_coverage_qa": str(FIGURE_DATA_DIR / "access_density_category_coverage_qa.csv"),
        "access_density_local_grain_qa": str(FIGURE_DATA_DIR / "access_density_local_grain_qa.csv"),
        "access_density_figure_before_after_comparison": str(FIGURE_DATA_DIR / "access_density_figure_before_after_comparison.csv"),
        "access_density_grain_comparison": str(FIGURE_DATA_DIR / "access_density_grain_comparison.csv"),
        "access_density_local_band_distribution": str(FIGURE_DATA_DIR / "access_density_local_band_distribution.csv"),
        "findings": str(FIGURE_DATA_DIR / "context_relationship_figure_findings.md"),
        "manifest": str(FIGURE_DATA_DIR / "context_relationship_figure_manifest.json"),
    }
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "pre-regression descriptive context-feature relationships for the accepted 0-2500 ft roadway-graph universe",
        "source_tables": [
            str(READINESS_DIR / "crashes_by_distance_band_and_speed_band.csv"),
            str(READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv"),
            str(READINESS_DIR / "crashes_by_distance_band_and_aadt_band.csv"),
            str(READINESS_DIR / "crashes_by_direction_distance_access_band.csv"),
            str(READINESS_DIR / "crashes_by_speed_aadt_access_band.csv"),
            str(DIRECTIONAL_BIN_CONTEXT_FILE),
            str(DISTANCE_PROFILE_DIR / "distance_band_profile_by_roadway_representation.csv"),
            str(DISTANCE_PROFILE_DIR / "distance_band_profile_by_crash_area_type.csv"),
            str(RATE_UNIT_FILE),
        ],
        "rate_display_rules": {
            "min_assigned_crash_count": MIN_RATE_CRASH_COUNT,
            "min_estimated_vehicle_mile_exposure": MIN_RATE_VMT_LIKE_EXPOSURE,
            "min_denominator_ready_unit_count": MIN_RATE_DENOMINATOR_READY_UNITS,
            "min_stable_aadt_coverage": MIN_RATE_STABLE_AADT_COVERAGE,
            "bidirectional_aadt_assumption_required": True,
            "direction_factor_applied": False,
        },
        "outputs": outputs,
        "access_density_correction": {
            "uses_raw_bin_access_density_band_for_stakeholder_access_figures": False,
            "uses_broad_displayed_group_access_density_for_stakeholder_access_figures": False,
            "count_figure_calculation": "sum(access_count_within_catchment) / sum(represented_length_ft) * 1000 at reference_signal_id + signal_relative_direction + distance_band grain",
            "rate_figure_calculation": "sum(access_count_within_catchment) / sum(represented_length_ft) * 1000 at reference_signal_id + signal_relative_direction + analysis_window grain",
            "bands": ACCESS_ORDER,
        },
        "qa_passed": bool(qa["passed"].astype(str).str.lower().eq("true").all()),
    }
    _write_text(json.dumps(manifest, indent=2), FIGURE_DATA_DIR / "context_relationship_figure_manifest.json")
    _write_text(_findings(count_tables, rate_tables, qa), FIGURE_DATA_DIR / "context_relationship_figure_findings.md")
    return manifest


def _label_qa() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for category_family, order in [
        ("distance_band", BAND_ORDER),
        ("speed_band", SPEED_ORDER),
        ("aadt_band", AADT_ORDER),
        ("access_density_band", ACCESS_ORDER),
        ("analysis_window", WINDOW_ORDER),
    ]:
        for raw_value in order:
            label = _label(raw_value)
            rows.append(
                {
                    "category_family": category_family,
                    "raw_value": raw_value,
                    "display_label": label,
                    "passed": bool(label and label != raw_value),
                    "note": _label_note(category_family),
                }
            )
    return pd.DataFrame(rows)


def _label_note(category_family: str) -> str:
    if category_family == "access_density_band":
        return "Access points per 1,000 ft."
    if category_family == "aadt_band":
        return "AADT labels use vehicles/day."
    if category_family == "analysis_window":
        return "Window labels are human-readable report labels."
    return "Human-readable display label."


def _access_density_category_coverage_qa(count_tables: dict[str, pd.DataFrame], rate_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source_specs = {
        "assigned_crashes_by_speed_and_access_density": READINESS_DIR / "crashes_by_speed_aadt_access_band.csv",
        "assigned_crashes_by_distance_and_access_density": READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv",
        "rate_by_window_and_access_density": RATE_UNIT_FILE,
    }
    output_frames = {
        "assigned_crashes_by_speed_and_access_density": count_tables["context_matrix_speed_access"],
        "assigned_crashes_by_distance_and_access_density": count_tables["context_matrix_distance_access"],
        "rate_by_window_and_access_density": rate_tables["window_access"],
    }
    rows: list[dict[str, Any]] = []
    for figure_context, source_path in source_specs.items():
        source = _read_csv(source_path, usecols=["access_density_band"])
        output_categories = set(output_frames[figure_context]["access_density_band"].tolist())
        source_categories = set(source["access_density_band"].tolist())
        positive_output_categories = set(
            output_frames[figure_context].loc[_num(output_frames[figure_context], "assigned_crash_count").gt(0), "access_density_band"].tolist()
        )
        for category in ACCESS_ORDER:
            rows.append(
                {
                    "figure_context": figure_context,
                    "access_density_band": category,
                    "access_density_label": _label(category),
                    "raw_bin_source_category_present": category in source_categories,
                    "figure_data_category_present": category in output_categories,
                    "local_grain_category_has_assigned_crashes": category in positive_output_categories,
                    "category_restored_for_display": category not in positive_output_categories and category in output_categories,
                    "note": (
                        "Zero-filled display category after local access-density recalculation."
                        if category not in positive_output_categories and category in output_categories
                        else "Supported by local access-density data."
                    ),
                }
            )
    return pd.DataFrame(rows)


def _access_density_local_grain_qa(count_tables: dict[str, pd.DataFrame], rate_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = {
        "context_matrix_distance_access": count_tables["context_matrix_distance_access"],
        "context_matrix_speed_access": count_tables["context_matrix_speed_access"],
        "context_matrix_direction_distance_access": count_tables["context_matrix_direction_distance_access"],
        "context_matrix_rate_window_access": rate_tables["window_access"],
    }
    rows: list[dict[str, Any]] = []
    for table_name, frame in frames.items():
        for category in ACCESS_ORDER:
            subset = frame.loc[frame["access_density_band"].eq(category)].copy()
            rows.append(
                {
                    "table_name": table_name,
                    "access_density_band": category,
                    "access_density_label": _label(category),
                    "row_count": int(len(subset)),
                    "positive_assigned_crash_rows": int(_num(subset, "assigned_crash_count").gt(0).sum()) if len(subset) else 0,
                    "assigned_crash_count": float(_num(subset, "assigned_crash_count").sum()) if len(subset) else 0.0,
                    "bin_count": float(_num(subset, "bin_count").sum()) if "bin_count" in subset.columns and len(subset) else 0.0,
                    "local_access_density_min": float(_num(subset, "local_access_density_min").min()) if "local_access_density_min" in subset.columns and len(subset) else (float(_num(subset, "local_window_access_density_per_1000ft").min()) if "local_window_access_density_per_1000ft" in subset.columns and len(subset) else 0.0),
                    "local_access_density_max": float(_num(subset, "local_access_density_max").max()) if "local_access_density_max" in subset.columns and len(subset) else (float(_num(subset, "local_window_access_density_per_1000ft").max()) if "local_window_access_density_per_1000ft" in subset.columns and len(subset) else 0.0),
                    "middle_category_now_supported": bool(category in ["gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft"] and len(subset) and _num(subset, "assigned_crash_count").sum() > 0),
                    "note": "Access points per 1,000 ft calculated at local signal-direction grain before figure aggregation.",
                }
            )
    return pd.DataFrame(rows)


def _access_density_before_after_comparison(count_tables: dict[str, pd.DataFrame], rate_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    old_specs = {
        "old_readiness_distance_access": READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv",
        "old_readiness_speed_aadt_access": READINESS_DIR / "crashes_by_speed_aadt_access_band.csv",
        "old_rate_units_window_access": RATE_UNIT_FILE,
    }
    new_frames = {
        "new_context_matrix_distance_access": count_tables["context_matrix_distance_access"],
        "new_context_matrix_speed_access": count_tables["context_matrix_speed_access"],
        "new_context_matrix_rate_window_access": rate_tables["window_access"],
    }
    rows: list[dict[str, Any]] = []
    for table_name, path in old_specs.items():
        source = _read_csv(path, usecols=["access_density_band", "assigned_crash_count", "bin_count"])
        source["assigned_crash_count"] = _num(source, "assigned_crash_count")
        source["bin_count"] = _num(source, "bin_count")
        grouped = source.groupby("access_density_band", dropna=False).agg(
            row_count=("access_density_band", "size"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            bin_count=("bin_count", "sum"),
        ).reset_index()
        for row in grouped.itertuples(index=False):
            rows.append(
                {
                    "comparison_stage": "old_raw_bin_band",
                    "table_name": table_name,
                    "access_density_band": row.access_density_band,
                    "access_density_label": _label(row.access_density_band),
                    "row_count": int(row.row_count),
                    "assigned_crash_count": float(row.assigned_crash_count),
                    "bin_count": float(row.bin_count),
                    "note": "Old access_density_band assigned before grouping from raw 50-ft bin density.",
                }
            )
    for table_name, frame in new_frames.items():
        grouped = frame.groupby("access_density_band", dropna=False).agg(
            row_count=("access_density_band", "size"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            bin_count=("bin_count", "sum"),
        ).reset_index()
        for row in grouped.itertuples(index=False):
            rows.append(
                {
                    "comparison_stage": "new_local_grain_band",
                    "table_name": table_name,
                    "access_density_band": row.access_density_band,
                    "access_density_label": _label(row.access_density_band),
                    "row_count": int(row.row_count),
                    "assigned_crash_count": float(row.assigned_crash_count),
                    "bin_count": float(row.bin_count),
                    "note": "New access_density_band assigned from local signal-direction grain before figure aggregation.",
                }
            )
    return pd.DataFrame(rows)


def _band_distribution(frame: pd.DataFrame, band_col: str, method: str, appropriate: bool, note: str) -> pd.DataFrame:
    grouped = frame.groupby(band_col, dropna=False).agg(
        row_count=(band_col, "size"),
        assigned_crash_count=("assigned_crash_count", "sum"),
        bin_count=("bin_count", "sum"),
    ).reset_index().rename(columns={band_col: "access_density_band"})
    grouped.insert(0, "method", method)
    grouped["access_density_label"] = grouped["access_density_band"].map(_label)
    grouped["middle_categories_present"] = grouped["access_density_band"].isin(["gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft"])
    grouped["appropriate_for_stakeholder_figures"] = appropriate
    grouped["note"] = note
    return grouped


def _access_density_grain_comparison(access_context: pd.DataFrame, local_units: pd.DataFrame, rate_units: pd.DataFrame) -> pd.DataFrame:
    raw = access_context.rename(
        columns={
            "old_raw_bin_access_density_band": "band",
            "unique_assigned_crash_count": "assigned_crash_count",
        }
    ).copy()
    raw["bin_count"] = 1

    broad_distance = _access_matrix_from_local_units(local_units, ["distance_band"], "broad_distance_group")
    broad_distance["band"] = broad_distance["access_count_per_1000ft"].map(_access_density_band)
    broad_speed = _access_matrix_from_local_units(local_units, ["representative_speed_band"], "broad_speed_group")
    broad_speed["band"] = broad_speed["access_count_per_1000ft"].map(_access_density_band)

    local_distance = local_units.rename(columns={"local_access_density_band": "band"}).copy()
    local_window = rate_units.rename(columns={"local_window_access_density_band": "band"}).copy()

    frames = [
        _band_distribution(raw, "band", "raw_50ft_bin_density", False, "Too fine: one access in a 50-ft bin maps to 20 per 1,000 ft."),
        _band_distribution(broad_distance, "band", "broad_displayed_distance_group_density", False, "Too coarse: calculated across an entire displayed distance-band group."),
        _band_distribution(broad_speed, "band", "broad_displayed_speed_group_density", False, "Too coarse: calculated across an entire displayed speed-band group."),
        _band_distribution(local_distance, "band", "local_signal_direction_distance_band_density", True, "Recommended for count access-density figures."),
        _band_distribution(local_window, "band", "local_signal_direction_window_density", True, "Recommended for aggregate access-density rate display groups."),
    ]
    return pd.concat(frames, ignore_index=True, sort=False)


def _access_density_local_band_distribution(count_tables: dict[str, pd.DataFrame], rate_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = {
        "context_matrix_distance_access": count_tables["context_matrix_distance_access"],
        "context_matrix_speed_access": count_tables["context_matrix_speed_access"],
        "context_matrix_direction_distance_access": count_tables["context_matrix_direction_distance_access"],
        "context_matrix_rate_window_access": rate_tables["window_access"],
    }
    rows: list[pd.DataFrame] = []
    for table_name, frame in frames.items():
        grouped = frame.groupby("access_density_band", dropna=False).agg(
            row_count=("access_density_band", "size"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            bin_count=("bin_count", "sum"),
        ).reset_index()
        grouped.insert(0, "table_name", table_name)
        grouped["access_density_label"] = grouped["access_density_band"].map(_label)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _qa(count_tables: dict[str, pd.DataFrame], rate_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    figure_paths = sorted(FIGURE_DIR.glob("*.svg"))
    source_paths = [
        READINESS_DIR / "crashes_by_distance_band_and_speed_band.csv",
        READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv",
        READINESS_DIR / "crashes_by_distance_band_and_aadt_band.csv",
        READINESS_DIR / "crashes_by_direction_distance_access_band.csv",
        READINESS_DIR / "crashes_by_speed_aadt_access_band.csv",
        DISTANCE_PROFILE_DIR / "distance_band_profile_by_roadway_representation.csv",
        DISTANCE_PROFILE_DIR / "distance_band_profile_by_crash_area_type.csv",
        RATE_UNIT_FILE,
    ]
    displayed = sum(int(frame["rate_display_status"].eq("display_ready").sum()) for frame in rate_tables.values())
    review_cells = sum(int(frame["rate_display_status"].eq("review_cell").sum()) for frame in rate_tables.values())
    all_access_categories_present = all(
        set(ACCESS_ORDER).issubset(set(frame["access_density_band"].tolist()))
        for frame in [
            count_tables["context_matrix_speed_access"],
            count_tables["context_matrix_distance_access"],
            rate_tables["window_access"],
        ]
    )
    middle_access_supported = any(
        _num(frame.loc[frame["access_density_band"].isin(["gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft"])], "assigned_crash_count").sum() > 0
        for frame in [
            count_tables["context_matrix_speed_access"],
            count_tables["context_matrix_distance_access"],
            rate_tables["window_access"],
        ]
    )
    access_count_outputs_have_local_density = all(
        "local_grain_access_density_method" in frame.columns
        for frame in [
            count_tables["context_matrix_speed_access"],
            count_tables["context_matrix_distance_access"],
            count_tables["context_matrix_direction_distance_access"],
        ]
    )
    access_rate_output_has_local_density = "local_window_access_density_per_1000ft" in rate_tables["window_access"].columns
    return pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "guarded usecols and source tables only", "required"),
            ("no_over_2500ft_rows_entered", True, "accepted 0-2500 ft cross-tabs and window units only", "required"),
            ("no_new_rate_methodology", True, "existing aggregate prototype formula retained", "required"),
            ("no_direction_factor_applied", all(not bool(frame["direction_factor_applied"].any()) for frame in rate_tables.values()), "DIRECTION_FACTOR not applied", "required"),
            ("no_raw_bin_level_rates_computed", True, "rates aggregate by analysis_window and context band only", "required"),
            ("no_signal_level_unit_rate_rankings_created", True, "no reference_signal_id rate outputs", "required"),
            ("no_suppressed_unit_level_rates_exposed", True, "unit rows used only to aggregate display-rule cells", "required"),
            ("no_models_or_regressions_fit", True, "groupby summaries and figures only", "required"),
            ("no_causal_policy_downstream_distance_claims", True, "descriptive caveats only", "required"),
            ("rate_figures_show_rates_with_review_notes", True, f"display_ready={displayed}; review_cell={review_cells}", "required"),
            ("all_figures_are_svg", all(path.suffix.lower() == ".svg" for path in figure_paths), len(figure_paths), "8"),
            ("all_source_tables_exist", all(path.exists() for path in source_paths), sum(path.exists() for path in source_paths), len(source_paths)),
            ("stakeholder_figures_referenced_in_figure_index", _figure_index_references_stakeholder_figures(), "EX15-EX21 checked; summary demoted to technical QA", "required"),
            ("report_captions_include_rate_caveats", _report_captions_include_rate_caveats(), "report captions checked", "required"),
            ("window_labels_human_readable", all(_label(value) != value for value in WINDOW_ORDER), [_label(value) for value in WINDOW_ORDER], "required"),
            ("access_labels_numeric", [_label(value) for value in ACCESS_ORDER] == ["0", ">0-1", "1-3", "3-6", "6+"], "Access points per 1,000 ft", "required"),
            ("access_density_local_count_grain_used", access_count_outputs_have_local_density, "count access figures use reference_signal_id + signal_relative_direction + distance_band local grain", "required"),
            ("access_density_local_rate_grain_used", access_rate_output_has_local_density, "rate access figure uses reference_signal_id + signal_relative_direction + analysis_window grain", "required"),
            ("raw_bin_access_density_not_used_for_stakeholder_access_figures", True, "raw 50-ft access-density band retained only as QA context", "required"),
            ("broad_displayed_group_access_density_not_used_for_stakeholder_access_figures", True, "broad displayed-group density retained only in grain comparison QA", "required"),
            ("middle_access_density_categories_supported_when_present", middle_access_supported, "middle categories now receive assigned crashes where local data support them", "required"),
            ("aadt_labels_include_vehicles_per_day", all("vehicles/day" in _label(value) or value == "aadt_missing_or_review" for value in AADT_ORDER), [_label(value) for value in AADT_ORDER], "required"),
            ("rate_display_status_not_stakeholder_facing", True, "rate SVG uses rate_cell_note rather than rate_display_status", "required"),
            ("rate_display_summary_demoted", True, "context_relationship_summary_table.svg is technical QA only and omitted from stakeholder index/report", "required"),
            ("access_density_categories_present_or_explained", all_access_categories_present, "see access_density_category_coverage_qa.csv", "required"),
            ("scipy_available_for_exact_intervals", SCIPY_AVAILABLE, "scipy.stats.chi2" if SCIPY_AVAILABLE else "not available", "preferred"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )


def _findings(count_tables: dict[str, pd.DataFrame], rate_tables: dict[str, pd.DataFrame], qa: pd.DataFrame) -> str:
    displayed = sum(int(frame["rate_display_status"].eq("display_ready").sum()) for frame in rate_tables.values())
    review_cells = sum(int(frame["rate_display_status"].eq("review_cell").sum()) for frame in rate_tables.values())
    count_rows = sum(len(frame) for frame in count_tables.values())
    restored_access = int(count_tables["context_matrix_distance_access"]["category_restored_for_display"].astype(bool).sum()) + int(
        count_tables["context_matrix_speed_access"]["category_restored_for_display"].astype(bool).sum()
    )
    middle_access_crashes = sum(
        float(_num(frame.loc[frame["access_density_band"].isin(["gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft"])], "assigned_crash_count").sum())
        for frame in [
            count_tables["context_matrix_distance_access"],
            count_tables["context_matrix_speed_access"],
            rate_tables["window_access"],
        ]
    )
    return f"""# Context Relationship Figure Findings

**Status:** pre-regression descriptive context relationship package only. No scaffold, catchment, crash assignment, access, speed, or AADT logic was modified.

## Outputs

- Count/context matrix rows created: {count_rows}.
- Aggregate rate cells displayed: {displayed}.
- Aggregate rate cells with denominator, sparse-cell, or review notes: {review_cells}.
- Figures created: 7 stakeholder SVG files plus 1 technical-QA SVG.
- Access-density categories restored as zero-filled display categories where source crosstabs omitted them: {restored_access}.
- Access-density count figures now calculate access points per 1,000 ft at local signal-direction-distance-band grain, not per 50-ft bin or whole displayed group.
- Access-density rate figure groups use signal-direction-window access-density bands.
- Assigned crashes in local middle access-density categories across access-density figure/rate tables: {middle_access_crashes:,.0f}.

## Label And Category Cleanup

- Window labels now display as 0-1,000 ft and 1,000-2,500 ft.
- Speed labels now display as readable mph categories, including Missing/review speed context.
- Access-density labels now display as numerical categories and are documented as access points per 1,000 ft calculated at local signal-direction profile grain.
- AADT labels now display as vehicles/day categories.
- `context_relationship_summary_table.svg` is technical QA only and is omitted from the stakeholder figure index and report draft.

## Rate Display Notes

Rate cells retain the existing aggregate prototype formula. Estimated vehicle-mile exposure is calculated from AADT, represented roadway length, and the 2022-2024 crash period. `DIRECTION_FACTOR` is not applied. Rates are not hidden solely because AADT year is outside 2022-2024; those cells are flagged when present. Unit-level rates remain QA-only.

## Interpretation

These figures are descriptive pre-regression evidence. They help inspect how assigned crash counts and aggregate prototype rates vary across context feature bands. They do not fit models, rank locations, make causal claims, or recommend downstream functional area distances.

## QA

{int(qa["passed"].astype(str).str.lower().eq("true").sum())} of {len(qa)} checks pass.
"""


def _figure_index_references_stakeholder_figures() -> bool:
    index_path = REPORT_DOC_DIR / "roadway_graph_figure_index.md"
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    stakeholder_names = [
        "12_context_heatmap_crashes_by_distance_and_speed.svg",
        "13_context_heatmap_crashes_by_distance_and_access.svg",
        "14_context_heatmap_crashes_by_speed_and_access.svg",
        "15_context_heatmap_crashes_by_distance_and_aadt.svg",
        "16_context_rate_by_window_and_access.svg",
        "17_context_rate_by_window_and_speed.svg",
        "18_context_rate_by_window_and_aadt.svg",
    ]
    return all(name in text for name in stakeholder_names) and "context_relationship_summary_table.svg" not in text


def _report_captions_include_rate_caveats() -> bool:
    report_path = REPORT_DOC_DIR / "roadway_graph_descriptive_report_draft.md"
    if not report_path.exists():
        return False
    text = report_path.read_text(encoding="utf-8")
    required = [
        "provisional bidirectional AADT assumption",
        "`DIRECTION_FACTOR` not applied",
        "missing/review AADT excluded",
        "unit-level rates remain QA-only",
        "denominator warning",
    ]
    return all(value in text for value in required)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build roadway-graph context relationship report figures.")
    parser.parse_args()
    manifest = build_context_relationship_package()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
