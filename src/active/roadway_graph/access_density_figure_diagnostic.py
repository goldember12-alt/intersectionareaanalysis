"""Read-only diagnostic for access-density bins in context relationship figures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/access_density_figure_diagnostic"

DIRECTIONAL_BIN_CONTEXT_FILE = (
    OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"
)
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
FIGURE_DATA_DIR = OUTPUT_ROOT / "report/current/context_relationship_figure_data"
DISTANCE_PROFILE_DIR = OUTPUT_ROOT / "analysis/current/directional_context_distance_band_profiles"
COPIED_FIGURE_DIRS = [
    Path("docs/reports/roadway_graph/figures"),
    Path("docs/reports/roadway_graph/figures/figures"),
]

BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]
SPEED_ORDER = ["lt_30_mph", "30_39_mph", "40_49_mph", "50_59_mph", "60plus_mph", "speed_missing_or_review"]
ACCESS_ORDER = ["0_per_1000ft", "gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft", "6plus_per_1000ft"]
MIDDLE_ACCESS_BANDS = ["gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft"]
WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, **kwargs)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, pd.NA)
    return numerator / denominator


def _distance_band(midpoint: pd.Series) -> pd.Series:
    return pd.cut(
        midpoint,
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=BAND_ORDER,
        right=False,
        include_lowest=True,
    ).astype("string")


def _speed_band(stable: Any, value: Any) -> str:
    if not bool(stable) or pd.isna(value):
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


def _label_access_band(value: str) -> str:
    return {
        "0_per_1000ft": "0",
        "gt0_lt1_per_1000ft": ">0-1",
        "1_lt3_per_1000ft": "1-3",
        "3_lt6_per_1000ft": "3-6",
        "6plus_per_1000ft": "6+",
        "access_density_unavailable": "Unavailable",
    }.get(value, value)


def _load_context() -> pd.DataFrame:
    columns = [
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
        "access_context_status",
        "has_access_context",
        "has_stable_speed_context",
    ]
    frame = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    for column in [
        "bin_midpoint_ft_from_reference_signal",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
    ]:
        frame[column] = _num(frame[column])
    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    frame["represented_length_ft"] = (
        frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]
    ).clip(lower=0)
    frame["distance_band"] = _distance_band(frame["bin_midpoint_ft_from_reference_signal"])
    frame = frame.loc[frame["distance_band"].isin(BAND_ORDER)].copy()
    frame["selected_speed_mph"] = frame["weighted_car_speed_limit"].where(
        frame["weighted_car_speed_limit"].notna(), frame["posted_car_speed_limit_context_value"]
    )
    frame["speed_band"] = [
        _speed_band(stable, value)
        for stable, value in zip(frame["has_stable_speed_context"].fillna(False), frame["selected_speed_mph"])
    ]
    frame["bin_access_count_per_1000ft"] = _safe_div(
        frame["access_count_within_catchment"].fillna(0) * 1000,
        frame["represented_length_ft"],
    )
    frame["current_raw_bin_access_density_band"] = frame["bin_access_count_per_1000ft"].map(_access_density_band)
    return frame


def _source_field_audit() -> pd.DataFrame:
    rows = [
        {
            "artifact": str(READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv"),
            "field": "access_density_band",
            "role": "current source category for distance-by-access figure",
            "finding": "Created in exposure_modeling_readiness_audit.py from raw-bin access density before figure grouping.",
        },
        {
            "artifact": str(READINESS_DIR / "crashes_by_speed_aadt_access_band.csv"),
            "field": "access_density_band",
            "role": "current source category for speed-by-access figure",
            "finding": "Created in exposure_modeling_readiness_audit.py from raw-bin access density before later aggregation by speed/access.",
        },
        {
            "artifact": str(DIRECTIONAL_BIN_CONTEXT_FILE),
            "field": "access_count_within_catchment",
            "role": "numerator used for current raw-bin density",
            "finding": "Current density calculation uses this field; within-100ft and within-250ft counts are carried as context sums but do not define access_density_band.",
        },
        {
            "artifact": str(DIRECTIONAL_BIN_CONTEXT_FILE),
            "field": "bin_end_ft_from_reference_signal - bin_start_ft_from_reference_signal",
            "role": "denominator used for current raw-bin density",
            "finding": "Current raw-bin density divides by represented bin length, which is usually 50 ft.",
        },
    ]
    return pd.DataFrame(rows)


def _count_distribution(context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field in ["access_count_within_catchment", "access_count_within_100ft", "access_count_within_250ft"]:
        counts = (
            context.groupby(field, dropna=False)
            .agg(
                bin_count=("reference_directional_bin_id", "nunique"),
                assigned_crash_count=("unique_assigned_crash_count", "sum"),
                represented_length_ft=("represented_length_ft", "sum"),
            )
            .reset_index()
            .rename(columns={field: "access_count"})
        )
        counts.insert(0, "source_field", field)
        rows.append(counts)
    return pd.concat(rows, ignore_index=True, sort=False).sort_values(["source_field", "access_count"])


def _raw_density_distribution(context: pd.DataFrame) -> pd.DataFrame:
    values = context["bin_access_count_per_1000ft"]
    quantiles = values.quantile([0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1]).reset_index()
    quantiles.columns = ["quantile", "bin_access_count_per_1000ft"]
    band_counts = (
        context.groupby("current_raw_bin_access_density_band", dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            represented_length_ft=("represented_length_ft", "sum"),
            access_count_within_catchment_sum=("access_count_within_catchment", "sum"),
            min_density=("bin_access_count_per_1000ft", "min"),
            median_density=("bin_access_count_per_1000ft", "median"),
            max_density=("bin_access_count_per_1000ft", "max"),
        )
        .reset_index()
        .rename(columns={"current_raw_bin_access_density_band": "access_density_band"})
    )
    band_counts["access_density_band_label"] = band_counts["access_density_band"].map(_label_access_band)
    band_counts["summary_type"] = "current_raw_bin_band_counts"
    quantiles["summary_type"] = "raw_bin_density_quantiles"
    return pd.concat([band_counts, quantiles], ignore_index=True, sort=False)


def _grouped_density(context: pd.DataFrame, group_cols: list[str], grain: str) -> pd.DataFrame:
    frame = (
        context.groupby(group_cols, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            represented_length_ft=("represented_length_ft", "sum"),
            access_count_within_catchment_sum=("access_count_within_catchment", "sum"),
            access_count_within_100ft_sum=("access_count_within_100ft", "sum"),
            access_count_within_250ft_sum=("access_count_within_250ft", "sum"),
        )
        .reset_index()
    )
    frame.insert(0, "group_grain", grain)
    frame["recommended_access_count_per_1000ft"] = _safe_div(
        frame["access_count_within_catchment_sum"] * 1000,
        frame["represented_length_ft"],
    )
    frame["recommended_access_density_band"] = frame["recommended_access_count_per_1000ft"].map(_access_density_band)
    frame["recommended_access_density_band_label"] = frame["recommended_access_density_band"].map(_label_access_band)
    return frame


def _all_grouped_density(context: pd.DataFrame) -> pd.DataFrame:
    frames = [
        _grouped_density(context, ["distance_band"], "distance_band"),
        _grouped_density(context, ["speed_band"], "speed_band"),
        _grouped_density(context, ["distance_band", "speed_band"], "distance_band_speed_band"),
        _grouped_density(context, ["distance_band", "signal_relative_direction"], "distance_band_signal_relative_direction"),
    ]
    return pd.concat(frames, ignore_index=True, sort=False)


def _current_band_assignment() -> pd.DataFrame:
    rows = []
    specs = [
        ("readiness_distance_access", READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv"),
        ("readiness_direction_distance_access", READINESS_DIR / "crashes_by_direction_distance_access_band.csv"),
        ("readiness_speed_aadt_access", READINESS_DIR / "crashes_by_speed_aadt_access_band.csv"),
        ("figure_distance_access", FIGURE_DATA_DIR / "context_matrix_distance_access.csv"),
        ("figure_speed_access", FIGURE_DATA_DIR / "context_matrix_speed_access.csv"),
    ]
    for table_name, path in specs:
        if not path.exists():
            rows.append({"table_name": table_name, "path": str(path), "table_exists": False})
            continue
        frame = _read_csv(path)
        if "access_density_band" not in frame.columns:
            rows.append({"table_name": table_name, "path": str(path), "table_exists": True, "has_access_density_band": False})
            continue
        grouped = (
            frame.groupby("access_density_band", dropna=False)
            .agg(
                row_count=("access_density_band", "size"),
                bin_count=("bin_count", "sum") if "bin_count" in frame.columns else ("access_density_band", "size"),
                assigned_crash_count=("assigned_crash_count", "sum") if "assigned_crash_count" in frame.columns else ("access_density_band", "size"),
            )
            .reset_index()
        )
        grouped.insert(0, "table_name", table_name)
        grouped.insert(1, "path", str(path))
        grouped["table_exists"] = True
        if "category_restored_for_display" in frame.columns:
            restored = frame.groupby("access_density_band")["category_restored_for_display"].sum().reset_index()
            grouped = grouped.merge(restored, on="access_density_band", how="left")
        else:
            grouped["category_restored_for_display"] = pd.NA
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False)


def _input_row_counts() -> dict[str, int]:
    paths = [
        DIRECTIONAL_BIN_CONTEXT_FILE,
        READINESS_DIR / "crashes_by_distance_band_and_access_density_band.csv",
        READINESS_DIR / "crashes_by_direction_distance_access_band.csv",
        READINESS_DIR / "crashes_by_speed_aadt_access_band.csv",
        READINESS_DIR / "crashes_by_distance_band_and_speed_band.csv",
        FIGURE_DATA_DIR / "context_matrix_distance_access.csv",
        FIGURE_DATA_DIR / "context_matrix_speed_access.csv",
    ]
    if DISTANCE_PROFILE_DIR.exists():
        paths.extend(sorted(DISTANCE_PROFILE_DIR.glob("*.csv")))
    for directory in [Path("docs/reports/roadway_graph/figures/figure_data"), Path("docs/reports/roadway_graph/figures/figures/figure_data")]:
        if directory.exists():
            paths.extend(sorted(directory.glob("*.csv")))

    row_counts: dict[str, int] = {}
    for path in paths:
        if path.exists():
            row_counts[str(path)] = len(pd.read_csv(path))
    return row_counts


def _recommended_assignment(grouped_density: pd.DataFrame) -> pd.DataFrame:
    return (
        grouped_density.groupby(["group_grain", "recommended_access_density_band", "recommended_access_density_band_label"], dropna=False)
        .agg(
            group_count=("group_grain", "size"),
            bin_count=("bin_count", "sum"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            represented_length_ft=("represented_length_ft", "sum"),
            access_count_within_catchment_sum=("access_count_within_catchment_sum", "sum"),
            min_recommended_access_count_per_1000ft=("recommended_access_count_per_1000ft", "min"),
            median_recommended_access_count_per_1000ft=("recommended_access_count_per_1000ft", "median"),
            max_recommended_access_count_per_1000ft=("recommended_access_count_per_1000ft", "max"),
        )
        .reset_index()
        .sort_values(["group_grain", "recommended_access_density_band"])
    )


def _middle_category_diagnostic(current: pd.DataFrame, recommended: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    raw_counts = context["current_raw_bin_access_density_band"].value_counts(dropna=False).to_dict()
    rows = []
    for band in ACCESS_ORDER:
        current_assigned = current.loc[current["access_density_band"].eq(band), "assigned_crash_count"].sum()
        current_rows = current.loc[current["access_density_band"].eq(band), "row_count"].sum()
        restored_rows = current.loc[current["access_density_band"].eq(band), "category_restored_for_display"].fillna(0).sum()
        recommended_groups = recommended.loc[recommended["recommended_access_density_band"].eq(band), "group_count"].sum()
        recommended_assigned = recommended.loc[recommended["recommended_access_density_band"].eq(band), "assigned_crash_count"].sum()
        rows.append(
            {
                "access_density_band": band,
                "access_density_band_label": _label_access_band(band),
                "raw_bin_count_current_band": int(raw_counts.get(band, 0)),
                "current_table_rows": int(current_rows) if pd.notna(current_rows) else 0,
                "current_assigned_crash_count": float(current_assigned) if pd.notna(current_assigned) else 0,
                "current_rows_restored_for_display": float(restored_rows) if pd.notna(restored_rows) else 0,
                "recommended_group_count": int(recommended_groups) if pd.notna(recommended_groups) else 0,
                "recommended_assigned_crash_count": float(recommended_assigned) if pd.notna(recommended_assigned) else 0,
                "diagnostic_note": (
                    "middle category absent under current raw-bin assignment"
                    if band in MIDDLE_ACCESS_BANDS and int(raw_counts.get(band, 0)) == 0
                    else "category has current raw-bin support"
                ),
            }
        )
    return pd.DataFrame(rows)


def _write_findings(
    summary: dict[str, Any],
    paths: dict[str, Path],
    current: pd.DataFrame,
    recommended: pd.DataFrame,
) -> None:
    middle_current_assigned = current.loc[current["access_density_band"].isin(MIDDLE_ACCESS_BANDS), "assigned_crash_count"].sum()
    middle_restored = current.loc[current["access_density_band"].isin(MIDDLE_ACCESS_BANDS), "category_restored_for_display"].fillna(0).sum()
    middle_recommended_groups = recommended.loc[
        recommended["recommended_access_density_band"].isin(MIDDLE_ACCESS_BANDS), "group_count"
    ].sum()
    text = f"""# Access-Density Figure Diagnostic

Bounded question: diagnose why the copied context relationship access-density figures show nonzero values only in the `0` and `6+` access-points-per-1,000-ft categories.

## Finding

The current figure source tables use `access_density_band` from `exposure_modeling_readiness_audit.py`. That field is assigned at the raw directional-bin level from:

`access_count_within_catchment / represented_length_ft * 1000`

The represented bin length is usually 50 ft. With that denominator, one access point in a bin becomes about 20 access points per 1,000 ft, so a raw bin with any catchment access is classified as `6plus_per_1000ft`. Raw bins with no catchment access are classified as `0_per_1000ft`.

Current middle-category assigned crashes across the audited current tables: {middle_current_assigned:,.0f}

Current middle-category rows restored only for display: {middle_restored:,.0f}

Recommended grouped middle-category rows identified by this diagnostic: {middle_recommended_groups:,.0f}

## Interpretation

The middle categories are zero because the current category assignment is made before grouping, using mostly 50-ft bin-level density. The zero middle categories in the figure data are then restored for display after the fact so that all expected labels appear.

The current access-density relationship figures are potentially misleading as stakeholder context figures because the labels imply group-level access points per 1,000 ft, while the displayed categories are inherited from raw-bin-level density.

## Recommended Calculation

For stakeholder context relationship figures, compute access density at the displayed group level:

`total access_count_within_catchment / total represented_length_ft * 1000`

Then assign the displayed group to:

- `0`
- `>0-1`
- `1-3`
- `3-6`
- `6+`

Use group-level density for displayed groups such as `distance_band`, `speed_band`, `distance_band + speed_band`, and `distance_band + signal_relative_direction`. Do not use raw 50-ft bin-level density for grouped figures unless a figure explicitly communicates that it is a raw-bin density distribution.

## QA

- No crash direction fields were read or used.
- Rows outside the accepted 0-2,500 ft windows were excluded.
- Source context joins were not modified.
- Report figures were not overwritten or regenerated.
- Current and recommended access-density band assignments were compared.
- The cause of the 0/middle-category pattern is documented.

## Outputs

"""
    for name, path in paths.items():
        text += f"- `{name}`: `{path}`\n"
    paths["findings"].write_text(text, encoding="utf-8")


def build_outputs() -> dict[str, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    context = _load_context()
    source_field_audit = _source_field_audit()
    count_distribution = _count_distribution(context)
    raw_density_distribution = _raw_density_distribution(context)
    grouped_density = _all_grouped_density(context)
    current_assignment = _current_band_assignment()
    recommended_assignment = _recommended_assignment(grouped_density)
    middle_diagnostic = _middle_category_diagnostic(current_assignment, recommended_assignment, context)
    input_row_counts = _input_row_counts()

    paths = {
        "source_field_audit": OUTPUT_DIR / "access_density_source_field_audit.csv",
        "count_distribution_raw_bins": OUTPUT_DIR / "access_count_distribution_raw_bins.csv",
        "density_distribution_raw_bins": OUTPUT_DIR / "access_density_distribution_raw_bins.csv",
        "density_distribution_grouped": OUTPUT_DIR / "access_density_distribution_grouped.csv",
        "band_assignment_current": OUTPUT_DIR / "access_density_band_assignment_current.csv",
        "band_assignment_recommended": OUTPUT_DIR / "access_density_band_assignment_recommended.csv",
        "middle_category_diagnostic": OUTPUT_DIR / "access_density_middle_category_diagnostic.csv",
        "findings": OUTPUT_DIR / "access_density_figure_diagnostic_findings.md",
        "manifest": OUTPUT_DIR / "access_density_figure_diagnostic_manifest.json",
    }

    source_field_audit.to_csv(paths["source_field_audit"], index=False)
    count_distribution.to_csv(paths["count_distribution_raw_bins"], index=False)
    raw_density_distribution.to_csv(paths["density_distribution_raw_bins"], index=False)
    grouped_density.to_csv(paths["density_distribution_grouped"], index=False)
    current_assignment.to_csv(paths["band_assignment_current"], index=False)
    recommended_assignment.to_csv(paths["band_assignment_recommended"], index=False)
    middle_diagnostic.to_csv(paths["middle_category_diagnostic"], index=False)

    summary = {
        "raw_bin_count": int(context["reference_directional_bin_id"].nunique()),
        "rows_over_2500ft_included": bool(context["bin_midpoint_ft_from_reference_signal"].ge(2500).any()),
        "median_represented_length_ft": float(context["represented_length_ft"].median()),
        "one_access_point_density_at_median_bin_length": float(1000 / context["represented_length_ft"].median()),
    }
    _write_findings(summary, paths, current_assignment, recommended_assignment)

    manifest = {
        "bounded_question": "read-only diagnostic for access-density binning in context relationship figures",
        "files_read": sorted(input_row_counts),
        "input_row_counts": input_row_counts,
        "outputs": {key: str(value) for key, value in paths.items()},
        "summary": summary,
        "qa": {
            "crash_direction_fields_read_or_used": False,
            "rows_over_2500ft_included": False,
            "source_context_joins_modified": False,
            "report_figures_overwritten": False,
            "current_and_recommended_bands_compared": True,
            "middle_category_cause_documented": True,
        },
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return paths


def main() -> None:
    outputs = build_outputs()
    print(json.dumps({key: str(value) for key, value in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
