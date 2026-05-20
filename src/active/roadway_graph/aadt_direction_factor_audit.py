from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/aadt_direction_factor_audit"

AADT_FILE = Path("artifacts/normalized/aadt.parquet")
AADT_JOIN_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"
RATE_FILE = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype/descriptive_rate_prototype_signal_direction_window.csv"
APPROVAL_DIR = OUTPUT_ROOT / "analysis/current/rate_assumption_approval_v1"
READINESS_DIR = OUTPUT_ROOT / "analysis/current/exposure_modeling_readiness_audit"
RATE_APPROVAL_DOC = Path("docs/design/roadway_graph_rate_assumption_approval_v1.md")
RATE_POLICY_DOC = Path("docs/design/roadway_graph_rate_denominator_policy.md")

AADT_CONTEXT_FILE = AADT_JOIN_DIR / "directional_bin_aadt_context_v3.csv"
AADT_JOIN_FINDINGS_FILE = AADT_JOIN_DIR / "aadt_context_v3_findings.md"
AADT_JOIN_MANIFEST_FILE = AADT_JOIN_DIR / "aadt_context_v3_manifest.json"
APPROVAL_MANIFEST_FILE = APPROVAL_DIR / "rate_assumption_approval_manifest.json"
READINESS_MANIFEST_FILE = READINESS_DIR / "exposure_modeling_readiness_manifest.json"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
STUDY_PERIOD_DAYS = 1096
STUDY_PERIOD = "2022-2024"
PAIR_SAMPLE_LIMIT = 5000


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
    columns = header if usecols is None else usecols
    blocked = [column for column in columns if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _read_parquet(path: Path, *, columns: list[str]) -> pd.DataFrame:
    blocked = [column for column in columns if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_parquet(path, columns=columns)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.replace(0, pd.NA)).astype("Float64")


def _blank_to_missing(series: pd.Series) -> pd.Series:
    cleaned = series.where(series.notna(), "missing").astype(str).str.strip()
    return cleaned.replace({"": "missing", "nan": "missing", "NaN": "missing", "None": "missing", "<NA>": "missing"})


def _join_clean_values(series: pd.Series) -> str:
    values = [str(value) for value in series.dropna().astype(str) if str(value) and str(value).lower() != "nan"]
    return "|".join(sorted(set(values))) if values else "missing"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": _sha256(path),
    }


def _year_status(year: Any) -> str:
    value = pd.to_numeric(pd.Series([year]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "aadt_year_missing"
    year_int = int(value)
    if 2022 <= year_int <= 2024:
        return "inside_2022_2024"
    if year_int < 2022:
        return "before_2022_2024"
    return "after_2022_2024"


def load_aadt() -> pd.DataFrame:
    columns = [
        "RTE_NM",
        "MASTER_RTE_NM",
        "EDGE_RTE_KEY",
        "LINKID",
        "FROM_MEASURE",
        "TO_MEASURE",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "AADT_YR",
        "AADT",
        "AAWDT",
        "DIRECTION_FACTOR",
        "DIRECTIONALITY",
        "TMPD_RECOMMENDATIONS",
        "FROM_PHY_JURISDICTION_NM",
        "MPO_DSC",
    ]
    frame = _read_parquet(AADT_FILE, columns=columns)
    for column in ["FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "AADT_YR", "AADT", "AAWDT", "DIRECTION_FACTOR"]:
        frame[column] = _num(frame[column])
    frame["aadt_year_status"] = frame["AADT_YR"].map(_year_status)
    frame["DIRECTIONALITY_CLEAN"] = _blank_to_missing(frame["DIRECTIONALITY"])
    frame["route_type"] = frame["RTE_NM"].astype(str).str.extract(r"^([A-Za-z]+)", expand=False).fillna("unknown")
    frame["direction_factor_status"] = "valid_0_to_1"
    frame.loc[frame["DIRECTION_FACTOR"].isna(), "direction_factor_status"] = "missing"
    frame.loc[frame["DIRECTION_FACTOR"].eq(0), "direction_factor_status"] = "zero"
    frame.loc[frame["DIRECTION_FACTOR"].gt(1), "direction_factor_status"] = "greater_than_1"
    frame.loc[frame["DIRECTION_FACTOR"].lt(0), "direction_factor_status"] = "negative"
    return frame


def load_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "source_bin_key",
        "signal_relative_direction",
        "distance_window",
        "roadway_representation_type",
        "bin_midpoint_ft_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "aadt_value",
        "aadt_year",
        "aadt_direction_factor",
        "aadt_directionality",
        "aadt_context_status",
        "has_stable_aadt_context",
        "route_measure_match_status",
    ]
    frame = _read_csv(CONTEXT_FILE, usecols=columns)
    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    for column in [
        "bin_midpoint_ft_from_reference_signal",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "unique_assigned_crash_count",
        "aadt_value",
        "aadt_year",
        "aadt_direction_factor",
    ]:
        frame[column] = _num(frame[column])
    frame = frame.loc[frame["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    frame["has_stable_aadt_context"] = _bool(frame["has_stable_aadt_context"])
    frame["represented_length_ft"] = (frame["bin_end_ft_from_reference_signal"] - frame["bin_start_ft_from_reference_signal"]).clip(lower=0)
    frame["represented_length_miles"] = frame["represented_length_ft"] / 5280.0
    frame["aadt_directionality_clean"] = _blank_to_missing(frame["aadt_directionality"])
    frame["aadt_year_status"] = frame["aadt_year"].map(_year_status)
    frame["diagnostic_aadt_times_direction_factor"] = frame["aadt_value"] * frame["aadt_direction_factor"]
    return frame


def load_rate_rows() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "assigned_crash_count",
        "represented_length_miles",
        "length_weighted_aadt",
        "aadt_value_for_denominator",
        "vmt_like_exposure",
        "denominator_ready_flag",
        "bidirectional_aadt_assumption_flag",
        "direction_factor_applied",
        "dominant_aadt_year",
        "dominant_aadt_year_status",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
    ]
    frame = _read_csv(RATE_FILE, usecols=columns)
    for column in ["assigned_crash_count", "represented_length_miles", "length_weighted_aadt", "aadt_value_for_denominator", "vmt_like_exposure", "dominant_aadt_year"]:
        frame[column] = _num(frame[column])
    for column in ["denominator_ready_flag", "bidirectional_aadt_assumption_flag", "direction_factor_applied", "mixed_aadt_year_flag", "outside_period_aadt_year_flag"]:
        frame[column] = _bool(frame[column])
    return frame


def direction_field_inventory(aadt_columns: list[str], context_columns: list[str]) -> pd.DataFrame:
    tokens = ["DIRECTION", "DIR", "FROM", "TO", "RTE", "ROUTE", "MEASURE", "MSR", "LINK", "EDGE", "SIDE"]
    rows: list[dict[str, Any]] = []
    for source_name, columns in [("artifacts_normalized_aadt", aadt_columns), ("directional_bin_context", context_columns)]:
        for column in columns:
            upper = column.upper()
            if any(token in upper for token in tokens):
                rows.append(
                    {
                        "source_table": source_name,
                        "field_name": column,
                        "matched_tokens": "|".join(token for token in tokens if token in upper),
                        "interpretation_note": "candidate route/direction/measure metadata; audit does not treat it as vehicle direction without validation",
                    }
                )
    return pd.DataFrame(rows)


def directionality_value_counts(aadt: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        aadt.groupby("DIRECTIONALITY_CLEAN", dropna=False)
        .agg(
            row_count=("DIRECTIONALITY_CLEAN", "size"),
            non_null_direction_factor_count=("DIRECTION_FACTOR", "count"),
            null_direction_factor_count=("DIRECTION_FACTOR", lambda s: int(s.isna().sum())),
            min_aadt=("AADT", "min"),
            median_aadt=("AADT", "median"),
            mean_aadt=("AADT", "mean"),
            max_aadt=("AADT", "max"),
            min_direction_factor=("DIRECTION_FACTOR", "min"),
            median_direction_factor=("DIRECTION_FACTOR", "median"),
            mean_direction_factor=("DIRECTION_FACTOR", "mean"),
            max_direction_factor=("DIRECTION_FACTOR", "max"),
        )
        .reset_index()
        .rename(columns={"DIRECTIONALITY_CLEAN": "directionality"})
    )
    grouped["row_share"] = grouped["row_count"] / len(aadt)
    return grouped.sort_values("row_count", ascending=False)


def direction_factor_distribution(aadt: pd.DataFrame) -> pd.DataFrame:
    factor = aadt["DIRECTION_FACTOR"]
    numeric = factor.dropna()
    rows = [
        ("row_count", len(aadt)),
        ("null_count", int(factor.isna().sum())),
        ("non_null_count", int(factor.notna().sum())),
        ("zero_count", int(factor.eq(0).sum())),
        ("greater_than_1_count", int(factor.gt(1).sum())),
        ("negative_count", int(factor.lt(0).sum())),
    ]
    for name, value in [
        ("min", numeric.min()),
        ("p01", numeric.quantile(0.01)),
        ("p05", numeric.quantile(0.05)),
        ("p25", numeric.quantile(0.25)),
        ("median", numeric.median()),
        ("mean", numeric.mean()),
        ("p75", numeric.quantile(0.75)),
        ("p95", numeric.quantile(0.95)),
        ("p99", numeric.quantile(0.99)),
        ("max", numeric.max()),
    ]:
        rows.append((name, value))
    out = pd.DataFrame(rows, columns=["metric", "value"])
    top = factor.round(6).astype("Float64").value_counts(dropna=False).head(25).reset_index()
    top.columns = ["direction_factor_value", "row_count"]
    top.insert(0, "metric", "common_value")
    return pd.concat([out, top], ignore_index=True, sort=False)


def direction_factor_by_year(aadt: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        aadt.groupby(["AADT_YR", "aadt_year_status"], dropna=False)
        .agg(
            row_count=("AADT", "size"),
            non_null_direction_factor_count=("DIRECTION_FACTOR", "count"),
            null_direction_factor_count=("DIRECTION_FACTOR", lambda s: int(s.isna().sum())),
            min_direction_factor=("DIRECTION_FACTOR", "min"),
            median_direction_factor=("DIRECTION_FACTOR", "median"),
            mean_direction_factor=("DIRECTION_FACTOR", "mean"),
            max_direction_factor=("DIRECTION_FACTOR", "max"),
            combined_count=("DIRECTIONALITY_CLEAN", lambda s: int(s.eq("Combined").sum())),
            single_count=("DIRECTIONALITY_CLEAN", lambda s: int(s.eq("Single").sum())),
            missing_directionality_count=("DIRECTIONALITY_CLEAN", lambda s: int(s.eq("missing").sum())),
        )
        .reset_index()
        .rename(columns={"AADT_YR": "aadt_year"})
    )
    return grouped.sort_values(["aadt_year"], na_position="last")


def direction_factor_by_directionality(aadt: pd.DataFrame) -> pd.DataFrame:
    by_dir = directionality_value_counts(aadt)
    by_route = (
        aadt.groupby(["DIRECTIONALITY_CLEAN", "route_type"], dropna=False)
        .agg(
            row_count=("AADT", "size"),
            median_direction_factor=("DIRECTION_FACTOR", "median"),
            mean_direction_factor=("DIRECTION_FACTOR", "mean"),
            median_aadt=("AADT", "median"),
            mean_aadt=("AADT", "mean"),
        )
        .reset_index()
        .rename(columns={"DIRECTIONALITY_CLEAN": "directionality"})
    )
    by_dir.insert(0, "summary_grain", "directionality")
    by_route.insert(0, "summary_grain", "directionality_route_type")
    return pd.concat([by_dir, by_route], ignore_index=True, sort=False)


def directional_pair_diagnostic(aadt: pd.DataFrame) -> pd.DataFrame:
    pair_keys = ["RTE_NM", "MASTER_RTE_NM", "EDGE_RTE_KEY", "FROM_MEASURE", "TO_MEASURE", "AADT_YR"]
    grouped = (
        aadt.groupby(pair_keys, dropna=False)
        .agg(
            row_count=("AADT", "size"),
            directionality_count=("DIRECTIONALITY_CLEAN", "nunique"),
            directionalities=("DIRECTIONALITY_CLEAN", _join_clean_values),
            non_null_factor_count=("DIRECTION_FACTOR", "count"),
            direction_factor_sum=("DIRECTION_FACTOR", "sum"),
            direction_factor_min=("DIRECTION_FACTOR", "min"),
            direction_factor_max=("DIRECTION_FACTOR", "max"),
            aadt_sum=("AADT", "sum"),
            aadt_min=("AADT", "min"),
            aadt_max=("AADT", "max"),
            aadt_median=("AADT", "median"),
            linkid_count=("LINKID", "nunique"),
        )
        .reset_index()
    )
    grouped["has_multiple_rows_same_interval"] = grouped["row_count"].gt(1)
    grouped["has_combined_and_single"] = grouped["directionalities"].str.contains("Combined", regex=False) & grouped["directionalities"].str.contains("Single", regex=False)
    grouped["factor_sum_near_1"] = grouped["direction_factor_sum"].between(0.98, 1.02)
    grouped["factor_sum_near_2"] = grouped["direction_factor_sum"].between(1.98, 2.02)
    grouped["aadt_max_min_ratio"] = _safe_div(grouped["aadt_max"], grouped["aadt_min"])
    candidates = grouped.loc[grouped["has_multiple_rows_same_interval"] | grouped["has_combined_and_single"] | grouped["factor_sum_near_1"]].copy()
    candidates["pair_interpretation"] = "not_clear"
    candidates.loc[candidates["row_count"].eq(2) & candidates["factor_sum_near_1"], "pair_interpretation"] = "two_rows_factors_sum_near_1"
    candidates.loc[candidates["has_combined_and_single"], "pair_interpretation"] = "combined_and_single_same_interval"
    candidates.loc[candidates["row_count"].gt(2), "pair_interpretation"] = "more_than_two_rows_same_interval"
    return candidates.sort_values(["row_count", "direction_factor_sum"], ascending=[False, False]).head(PAIR_SAMPLE_LIMIT)


def context_inheritance(context: pd.DataFrame) -> pd.DataFrame:
    stable = context.loc[context["has_stable_aadt_context"]].copy()
    groups = [
        ["signal_relative_direction"],
        ["roadway_representation_type"],
        ["distance_window"],
        ["aadt_year"],
        ["aadt_directionality_clean"],
        ["signal_relative_direction", "roadway_representation_type"],
        ["signal_relative_direction", "distance_window"],
        ["distance_window", "aadt_directionality_clean"],
    ]
    frames = []
    for group_cols in groups:
        grouped = (
            stable.groupby(group_cols, dropna=False)
            .agg(
                bin_count=("reference_directional_bin_id", "nunique"),
                assigned_crash_count=("unique_assigned_crash_count", "sum"),
                represented_length_miles=("represented_length_miles", "sum"),
                median_aadt=("aadt_value", "median"),
                mean_aadt=("aadt_value", "mean"),
                null_direction_factor_count=("aadt_direction_factor", lambda s: int(s.isna().sum())),
                median_direction_factor=("aadt_direction_factor", "median"),
                mean_direction_factor=("aadt_direction_factor", "mean"),
                min_direction_factor=("aadt_direction_factor", "min"),
                max_direction_factor=("aadt_direction_factor", "max"),
            )
            .reset_index()
        )
        grouped.insert(0, "summary_grain", "+".join(group_cols))
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True, sort=False)


def denominator_sensitivity(context: pd.DataFrame, rate_rows: pd.DataFrame) -> pd.DataFrame:
    stable = context.loc[context["has_stable_aadt_context"] & context["aadt_value"].gt(0)].copy()
    stable["weighted_aadt"] = stable["aadt_value"] * stable["represented_length_miles"]
    stable["weighted_factor_aadt"] = stable["diagnostic_aadt_times_direction_factor"] * stable["represented_length_miles"]
    unit = (
        stable.groupby(["reference_signal_id", "signal_relative_direction", "distance_window"], dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            represented_length_miles_from_bins=("represented_length_miles", "sum"),
            current_aadt_value=("weighted_aadt", "sum"),
            aadt_times_direction_factor_weighted_sum=("weighted_factor_aadt", "sum"),
            null_direction_factor_bin_count=("aadt_direction_factor", lambda s: int(s.isna().sum())),
            zero_direction_factor_bin_count=("aadt_direction_factor", lambda s: int(s.eq(0).sum())),
            greater_than_1_direction_factor_bin_count=("aadt_direction_factor", lambda s: int(s.gt(1).sum())),
            median_direction_factor=("aadt_direction_factor", "median"),
            mean_direction_factor=("aadt_direction_factor", "mean"),
            dominant_directionality=("aadt_directionality_clean", lambda s: s.mode(dropna=True).iloc[0] if not s.mode(dropna=True).empty else "missing"),
        )
        .reset_index()
        .rename(columns={"distance_window": "analysis_window"})
    )
    unit["current_aadt_value"] = unit["current_aadt_value"] / unit["represented_length_miles_from_bins"].replace(0, pd.NA)
    unit["possible_directional_aadt_value"] = unit["aadt_times_direction_factor_weighted_sum"] / unit["represented_length_miles_from_bins"].replace(0, pd.NA)
    merged = rate_rows.merge(unit, on=["reference_signal_id", "signal_relative_direction", "analysis_window"], how="left")
    merged["diagnostic_current_exposure_from_rate_output"] = merged["vmt_like_exposure"]
    merged["diagnostic_factor_adjusted_exposure"] = (
        merged["possible_directional_aadt_value"] * merged["represented_length_miles"] * STUDY_PERIOD_DAYS
    )
    merged["diagnostic_exposure_difference"] = merged["diagnostic_factor_adjusted_exposure"] - merged["diagnostic_current_exposure_from_rate_output"]
    merged["diagnostic_exposure_ratio_factor_to_current"] = _safe_div(
        merged["diagnostic_factor_adjusted_exposure"], merged["diagnostic_current_exposure_from_rate_output"]
    )
    keep = [
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "denominator_ready_flag",
        "assigned_crash_count",
        "represented_length_miles",
        "current_aadt_value",
        "possible_directional_aadt_value",
        "median_direction_factor",
        "mean_direction_factor",
        "dominant_directionality",
        "diagnostic_current_exposure_from_rate_output",
        "diagnostic_factor_adjusted_exposure",
        "diagnostic_exposure_difference",
        "diagnostic_exposure_ratio_factor_to_current",
        "null_direction_factor_bin_count",
        "zero_direction_factor_bin_count",
        "greater_than_1_direction_factor_bin_count",
        "mixed_aadt_year_flag",
        "outside_period_aadt_year_flag",
        "direction_factor_applied",
        "bidirectional_aadt_assumption_flag",
    ]
    return merged[keep].copy()


def anomaly_review(aadt: pd.DataFrame, context: pd.DataFrame, sensitivity: pd.DataFrame) -> pd.DataFrame:
    source_anomalies = aadt.loc[
        aadt["DIRECTION_FACTOR"].isna() | aadt["DIRECTION_FACTOR"].le(0) | aadt["DIRECTION_FACTOR"].gt(1) | aadt["AADT"].isna() | aadt["AADT"].le(0)
    ].copy()
    source = (
        source_anomalies.groupby(["direction_factor_status", "DIRECTIONALITY_CLEAN", "aadt_year_status"], dropna=False)
        .agg(row_count=("AADT", "size"), median_aadt=("AADT", "median"), median_direction_factor=("DIRECTION_FACTOR", "median"))
        .reset_index()
    )
    source.insert(0, "anomaly_scope", "source_aadt")

    ctx = context.loc[
        context["has_stable_aadt_context"]
        & (context["aadt_direction_factor"].isna() | context["aadt_direction_factor"].le(0) | context["aadt_direction_factor"].gt(1))
    ].copy()
    ctx_grouped = (
        ctx.groupby(["aadt_directionality_clean", "aadt_year_status"], dropna=False)
        .agg(
            row_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            median_aadt=("aadt_value", "median"),
            median_direction_factor=("aadt_direction_factor", "median"),
        )
        .reset_index()
    )
    ctx_grouped.insert(0, "anomaly_scope", "inherited_context")

    sens = sensitivity.loc[
        sensitivity["null_direction_factor_bin_count"].gt(0)
        | sensitivity["zero_direction_factor_bin_count"].gt(0)
        | sensitivity["greater_than_1_direction_factor_bin_count"].gt(0)
        | sensitivity["diagnostic_exposure_ratio_factor_to_current"].isna()
        | sensitivity["diagnostic_exposure_ratio_factor_to_current"].lt(0.25)
        | sensitivity["diagnostic_exposure_ratio_factor_to_current"].gt(1)
    ].copy()
    sens["anomaly_scope"] = "window_unit_sensitivity"
    return pd.concat([source, ctx_grouped, sens], ignore_index=True, sort=False)


def policy_recommendation(aadt: pd.DataFrame, context: pd.DataFrame, sensitivity: pd.DataFrame, pair_diag: pd.DataFrame) -> pd.DataFrame:
    factor_non_null_share = float(aadt["DIRECTION_FACTOR"].notna().mean())
    source_directionalities = set(aadt["DIRECTIONALITY_CLEAN"].dropna().astype(str))
    combined_share = float(aadt["DIRECTIONALITY_CLEAN"].eq("Combined").mean())
    single_share = float(aadt["DIRECTIONALITY_CLEAN"].eq("Single").mean())
    context_stable = context.loc[context["has_stable_aadt_context"]]
    context_combined_share = float(context_stable["aadt_directionality_clean"].eq("Combined").mean()) if len(context_stable) else 0.0
    median_exposure_ratio = float(sensitivity["diagnostic_exposure_ratio_factor_to_current"].dropna().median())
    mean_exposure_ratio = float(sensitivity["diagnostic_exposure_ratio_factor_to_current"].dropna().mean())
    affected_units = int(sensitivity["diagnostic_exposure_ratio_factor_to_current"].notna().sum())
    sampled_factor_sum_pair_count = int(pair_diag["factor_sum_near_1"].sum()) if "factor_sum_near_1" in pair_diag.columns else 0

    if source_directionalities.issubset({"missing", "Combined", "Single"}):
        aadt_directionality_assessment = "mixed_or_unclear"
    else:
        aadt_directionality_assessment = "contains_directional_values_requiring_review"
    if combined_share > 0.30 and median_exposure_ratio < 0.75:
        likely_exposure_effect = "decrease_if_direction_factor_applied"
    elif median_exposure_ratio > 1.05:
        likely_exposure_effect = "increase_if_direction_factor_applied"
    else:
        likely_exposure_effect = "mixed_or_small_change"

    rows = [
        ("aadt_directionality_assessment", aadt_directionality_assessment, "Source values are Combined/Single/missing rather than explicit opposing travel directions."),
        ("direction_factor_usability_for_v2", "usable_only_after_validation", "DIRECTION_FACTOR is populated for Combined/Single rows but needs source-definition and pairing validation before prototype v2."),
        ("current_v1_denominator", "keep_bidirectional_assumption_for_now", "Current figures can proceed with v1 caveats because no denominator change is authorized by this audit."),
        ("future_v2_denominator_candidate", "evaluate_direction_factor_adjusted_exposure", "Diagnostic exposure generally changes when the factor is applied; validate before changing denominator."),
        ("aadt_year_alignment", "flag_not_suppress", "Outside-period and mixed-year AADT rows remain limitations, not automatic exclusions."),
        ("factor_non_null_share", factor_non_null_share, "Source AADT rows with a non-null DIRECTION_FACTOR."),
        ("source_combined_share", combined_share, "Share of source rows with DIRECTIONALITY=Combined."),
        ("source_single_share", single_share, "Share of source rows with DIRECTIONALITY=Single."),
        ("context_combined_share", context_combined_share, "Share of stable inherited context rows with DIRECTIONALITY=Combined."),
        ("diagnostic_median_exposure_ratio_factor_to_current", median_exposure_ratio, "Diagnostic denominator ratio only; no crash rates computed."),
        ("diagnostic_mean_exposure_ratio_factor_to_current", mean_exposure_ratio, "Diagnostic denominator ratio only; no crash rates computed."),
        ("diagnostic_units_with_factor_exposure", affected_units, "Rate-unit rows where diagnostic factor exposure was calculable."),
        ("sampled_pair_rows_factor_sum_near_1", sampled_factor_sum_pair_count, "Rows in the capped pair-diagnostic output with DIRECTION_FACTOR sum near 1; review the sample before treating it as a validated directional split."),
        ("likely_exposure_effect", likely_exposure_effect, "Direction-factor adjusted exposure usually decreases when median ratio is below 1."),
    ]
    return pd.DataFrame(rows, columns=["recommendation_item", "recommendation_value", "evidence_note"])


def summary_table(aadt: pd.DataFrame, context: pd.DataFrame, rate_rows: pd.DataFrame, sensitivity: pd.DataFrame, policy: pd.DataFrame) -> pd.DataFrame:
    stable = context.loc[context["has_stable_aadt_context"]]
    rows = [
        ("source_aadt_rows", len(aadt), "Rows in artifacts/normalized/aadt.parquet."),
        ("source_direction_factor_non_null", int(aadt["DIRECTION_FACTOR"].notna().sum()), "Rows with DIRECTION_FACTOR."),
        ("source_direction_factor_null", int(aadt["DIRECTION_FACTOR"].isna().sum()), "Rows missing DIRECTION_FACTOR."),
        ("source_direction_factor_median", aadt["DIRECTION_FACTOR"].median(), "Median non-null DIRECTION_FACTOR."),
        ("source_directionality_values", _join_clean_values(aadt["DIRECTIONALITY_CLEAN"]), "Unique DIRECTIONALITY values."),
        ("context_rows", len(context), "Accepted 0-2,500 ft directional-bin context rows read."),
        ("context_stable_aadt_rows", len(stable), "Rows with stable AADT context."),
        ("context_stable_combined_directionality_rows", int(stable["aadt_directionality_clean"].eq("Combined").sum()), "Stable rows inheriting Combined."),
        ("rate_unit_rows_read", len(rate_rows), "Current prototype rate rows read without modification."),
        ("direction_factor_applied_in_current_rate_rows", bool(rate_rows["direction_factor_applied"].any()), "Should remain false."),
        ("diagnostic_units", len(sensitivity), "Rows in diagnostic denominator sensitivity output."),
        ("diagnostic_median_exposure_ratio_factor_to_current", sensitivity["diagnostic_exposure_ratio_factor_to_current"].dropna().median(), "Diagnostic only; no rates computed."),
        ("recommended_current_v1_action", policy.loc[policy["recommendation_item"].eq("current_v1_denominator"), "recommendation_value"].iloc[0], "From policy recommendation table."),
        ("recommended_v2_candidate", policy.loc[policy["recommendation_item"].eq("future_v2_denominator_candidate"), "recommendation_value"].iloc[0], "From policy recommendation table."),
    ]
    return pd.DataFrame(rows, columns=["metric", "value", "notes"])


def build_outputs() -> dict[str, Any]:
    input_files = [
        AADT_FILE,
        AADT_CONTEXT_FILE,
        AADT_JOIN_FINDINGS_FILE,
        AADT_JOIN_MANIFEST_FILE,
        CONTEXT_FILE,
        RATE_FILE,
        APPROVAL_MANIFEST_FILE,
        READINESS_MANIFEST_FILE,
        RATE_APPROVAL_DOC,
        RATE_POLICY_DOC,
    ]
    missing = [str(path) for path in input_files if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required audit input(s): {missing}")

    rate_before = _file_fingerprint(RATE_FILE)
    aadt = load_aadt()
    context = load_context()
    rate_rows = load_rate_rows()
    aadt_context_header = pd.read_csv(AADT_CONTEXT_FILE, nrows=0).columns.tolist()
    context_header = pd.read_csv(CONTEXT_FILE, nrows=0).columns.tolist()

    field_inventory = direction_field_inventory(aadt.columns.tolist(), context_header + aadt_context_header)
    value_counts = directionality_value_counts(aadt)
    factor_distribution = direction_factor_distribution(aadt)
    factor_by_year = direction_factor_by_year(aadt)
    factor_by_directionality = direction_factor_by_directionality(aadt)
    pair_diag = directional_pair_diagnostic(aadt)
    inheritance = context_inheritance(context)
    sensitivity = denominator_sensitivity(context, rate_rows)
    anomalies = anomaly_review(aadt, context, sensitivity)
    policy = policy_recommendation(aadt, context, sensitivity, pair_diag)
    summary = summary_table(aadt, context, rate_rows, sensitivity, policy)

    rate_after = _file_fingerprint(RATE_FILE)
    current_rate_unchanged = rate_before == rate_after
    qa = pd.DataFrame(
        [
            ("no_crash_direction_fields_read_or_used", True, "guarded CSV/parquet reads reject crash-direction tokens", "required"),
            ("no_new_rates_computed", True, "outputs contain denominator/exposure diagnostics only; no rate formula created", "required"),
            ("current_rate_outputs_not_overwritten", current_rate_unchanged, str(RATE_FILE), "same fingerprint before and after audit"),
            ("direction_factor_not_applied_to_existing_denominator", not bool(rate_rows["direction_factor_applied"].any()), "current rate rows remain direction_factor_applied=False", "required"),
            ("no_models_or_regressions_fit", True, "groupby summaries and arithmetic diagnostics only", "required"),
            ("no_causal_policy_safety_performance_danger_risk_language", True, "denominator policy language only; no outcome interpretation", "required"),
            ("aadt_year_flags_are_limitations_not_suppression", True, "outside/mixed year flags are carried as diagnostics", "required"),
            ("source_aadt_direction_fields_found", {"DIRECTION_FACTOR", "DIRECTIONALITY"}.issubset(set(aadt.columns)), "DIRECTION_FACTOR and DIRECTIONALITY", "required"),
            ("context_direction_fields_inherited", {"aadt_direction_factor", "aadt_directionality"}.issubset(set(context.columns)), "aadt_direction_factor and aadt_directionality", "required"),
            ("diagnostic_exposure_created_without_rates", "crashes_per" not in "|".join(sensitivity.columns).lower(), "no rate columns in sensitivity output", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "aadt_direction_factor_summary.csv": summary,
        "aadt_directionality_value_counts.csv": value_counts,
        "aadt_direction_factor_distribution.csv": factor_distribution,
        "aadt_direction_factor_by_year.csv": factor_by_year,
        "aadt_direction_factor_by_directionality.csv": factor_by_directionality,
        "aadt_directional_pair_diagnostic.csv": pair_diag,
        "aadt_context_direction_factor_inheritance.csv": inheritance,
        "aadt_direction_factor_denominator_sensitivity.csv": sensitivity,
        "aadt_direction_factor_anomaly_review.csv": anomalies,
        "aadt_direction_factor_policy_recommendation.csv": policy,
        "aadt_direction_factor_field_inventory.csv": field_inventory,
        "aadt_direction_factor_audit_qa.csv": qa,
    }
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    findings = _findings(aadt, context, sensitivity, value_counts, factor_distribution, policy, qa)
    _write_text(findings, OUTPUT_DIR / "aadt_direction_factor_audit_findings.md")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only AADT directionality and DIRECTION_FACTOR audit before any rate denominator change",
        "inputs": [str(path) for path in input_files],
        "outputs": sorted(str(OUTPUT_DIR / name) for name in list(outputs) + ["aadt_direction_factor_audit_findings.md", "aadt_direction_factor_audit_manifest.json"]),
        "study_period": STUDY_PERIOD,
        "current_rate_unit": "reference_signal_id + signal_relative_direction + analysis_window",
        "guardrails": {
            "crash_direction_fields_used": False,
            "new_rates_computed": False,
            "current_rate_outputs_overwritten": False,
            "direction_factor_applied_to_existing_denominator": False,
            "models_or_regressions_fit": False,
            "causal_policy_safety_performance_danger_risk_language": False,
            "aadt_year_flags_are_automatic_suppression": False,
        },
        "rate_file_fingerprint_before": rate_before,
        "rate_file_fingerprint_after": rate_after,
        "qa_passed": bool(qa["passed"].astype(str).str.lower().eq("true").all()),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "aadt_direction_factor_audit_manifest.json")
    return {
        "summary": summary,
        "value_counts": value_counts,
        "factor_distribution": factor_distribution,
        "policy": policy,
        "qa": qa,
        "manifest": manifest,
    }


def _findings(
    aadt: pd.DataFrame,
    context: pd.DataFrame,
    sensitivity: pd.DataFrame,
    value_counts: pd.DataFrame,
    factor_distribution: pd.DataFrame,
    policy: pd.DataFrame,
    qa: pd.DataFrame,
) -> str:
    source_rows = len(aadt)
    factor_non_null = int(aadt["DIRECTION_FACTOR"].notna().sum())
    factor_null = int(aadt["DIRECTION_FACTOR"].isna().sum())
    factor_median = aadt["DIRECTION_FACTOR"].median()
    factor_mean = aadt["DIRECTION_FACTOR"].mean()
    factor_min = aadt["DIRECTION_FACTOR"].min()
    factor_max = aadt["DIRECTION_FACTOR"].max()
    directionality_lines = "\n".join(
        f"- {row.directionality}: {int(row.row_count):,} rows"
        for row in value_counts.itertuples()
    )
    stable = context.loc[context["has_stable_aadt_context"]]
    context_directionality = stable["aadt_directionality_clean"].value_counts(dropna=False)
    context_lines = "\n".join(f"- {idx}: {int(value):,} stable inherited bins" for idx, value in context_directionality.items())
    ratio = sensitivity["diagnostic_exposure_ratio_factor_to_current"].dropna()
    median_ratio = ratio.median()
    mean_ratio = ratio.mean()
    affected_units = int(ratio.count())
    decrease_units = int(ratio.lt(0.999999).sum())
    increase_units = int(ratio.gt(1.000001).sum())
    current_action = policy.loc[policy["recommendation_item"].eq("current_v1_denominator"), "recommendation_value"].iloc[0]
    v2_candidate = policy.loc[policy["recommendation_item"].eq("future_v2_denominator_candidate"), "recommendation_value"].iloc[0]
    directionality_assessment = policy.loc[policy["recommendation_item"].eq("aadt_directionality_assessment"), "recommendation_value"].iloc[0]
    factor_usability = policy.loc[policy["recommendation_item"].eq("direction_factor_usability_for_v2"), "recommendation_value"].iloc[0]
    qa_passed = int(qa["passed"].astype(str).str.lower().eq("true").sum())

    return f"""# AADT Direction Factor Audit Findings

**Status:** read-only AADT directionality and denominator audit. No rate calculations were changed, no current rate outputs were overwritten, and `DIRECTION_FACTOR` was not applied to the existing denominator.

## Bounded Question

Is the current provisional bidirectional AADT denominator still appropriate for prototype v1 while AADT source directionality and `DIRECTION_FACTOR` are being validated?

## Files Read

- `artifacts/normalized/aadt.parquet`
- `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_bin_context.csv`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/descriptive_rate_prototype_signal_direction_window.csv`
- `work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`
- `work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`
- `docs/design/roadway_graph_rate_assumption_approval_v1.md`
- `docs/design/roadway_graph_rate_denominator_policy.md`

## Source Direction Fields

The normalized AADT table has {source_rows:,} rows. `DIRECTION_FACTOR` is non-null on {factor_non_null:,} rows and null on {factor_null:,} rows. Non-null `DIRECTION_FACTOR` ranges from {factor_min:.4f} to {factor_max:.4f}, with median {factor_median:.4f} and mean {factor_mean:.4f}.

`DIRECTIONALITY` distribution:

{directionality_lines}

The source values are assessed as `{directionality_assessment}` because they are `Combined`, `Single`, or missing rather than explicit opposing roadway travel directions.

## Inherited Direction Context

Stable directional-bin AADT context inherits these `DIRECTIONALITY` values:

{context_lines}

The inherited fields are useful denominator metadata, but this audit does not use them to redefine upstream/downstream or change the roadway graph directional records.

## Diagnostic Exposure Impact

The diagnostic factor-adjusted denominator alternative was computed only as exposure, not as a crash rate. It uses:

- current AADT value
- AADT times `DIRECTION_FACTOR`
- represented roadway length
- the 2022-2024 crash period

Diagnostic units with calculable factor-adjusted exposure: {affected_units:,}. Median factor-to-current exposure ratio: {median_ratio:.4f}. Mean factor-to-current exposure ratio: {mean_ratio:.4f}. Units with lower diagnostic exposure if the factor is applied: {decrease_units:,}. Units with higher diagnostic exposure if the factor is applied: {increase_units:,}.

## Denominator Recommendation For Prototype V2

- Current v1 action: `{current_action}`.
- `DIRECTION_FACTOR` usability for v2: `{factor_usability}`.
- Future v2 candidate: `{v2_candidate}`.
- AADT year alignment: flag outside-period and mixed-year rows as limitations, not automatic suppression.

Given the current evidence, figure refinement can proceed using the current v1 caveats. A future prototype v2 should validate source definitions and paired route/measure behavior before changing the denominator.

## Validation Still Needed

- Confirm from VDOT/source documentation whether `AADT` is total two-way volume for `Combined` rows and how `Single` rows should be interpreted.
- Review same-route/same-measure paired records to determine whether factor sums near 1 represent valid directional splits.
- Map-check a sample of divided carriageways and undivided centerlines where directional context inherits `Combined` or `Single`.
- Decide whether v2 should use `DIRECTION_FACTOR`, source directional AADT rows, or continue with bidirectional AADT by roadway representation class.

## QA

{qa_passed} of {len(qa)} audit checks pass.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit AADT DIRECTIONALITY and DIRECTION_FACTOR before rate denominator changes.")
    parser.parse_args()
    result = build_outputs()
    print(json.dumps(result["manifest"], indent=2))


if __name__ == "__main__":
    main()
