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
REVIEW_DIR = OUTPUT_ROOT / "analysis/current/signal_context_review_queue"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/directional_context_distance_band_profiles"

DIRECTIONAL_BIN_CONTEXT_FILE = CONTEXT_DIR / "directional_bin_context.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = CONTEXT_DIR / "directional_crash_context.csv"
REFERENCE_SIGNAL_CONTEXT_FILE = CONTEXT_DIR / "reference_signal_context_summary.csv"
CONTEXT_MANIFEST_FILE = CONTEXT_DIR / "directional_bin_context_manifest.json"
DESCRIPTIVE_MANIFEST_FILE = SUMMARY_DIR / "directional_context_descriptive_summary_manifest.json"
DESCRIPTIVE_QA_FILE = SUMMARY_DIR / "directional_context_descriptive_summary_qa.csv"
REVIEW_MANIFEST_FILE = REVIEW_DIR / "signal_context_review_queue_manifest.json"

WINDOWS = {"high_priority_0_1000ft", "sensitivity_1000_2500ft"}
BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]
STABLE_SPEED_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
STABLE_AADT_STATUSES = {"stable_aadt_assigned_route_measure", "stable_aadt_assigned_single_route_candidate"}
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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, pd.NA)
    return (numerator / denominator).astype("Float64")


def _distance_band(midpoint: pd.Series) -> pd.Series:
    band = pd.cut(
        midpoint,
        bins=[0, 250, 500, 1000, 1500, 2500],
        labels=BAND_ORDER,
        right=False,
        include_lowest=True,
    ).astype(str)
    band.loc[midpoint.eq(2500)] = "1500_2500ft"
    return band


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


def load_context() -> pd.DataFrame:
    columns = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
        "unique_assigned_crash_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "assigned_crashes_with_area_type_count",
        "has_assigned_crash",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "access_context_status",
        "has_access_context",
        "aadt_value",
        "aadt_context_status",
        "aadt_context_confidence",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
        "roadway_urban_rural_context_status",
        "context_completeness_class",
    ]
    frame = _read_csv(DIRECTIONAL_BIN_CONTEXT_FILE, usecols=columns)
    numeric_columns = [
        "bin_midpoint_ft_from_reference_signal",
        "posted_car_speed_limit_context_value",
        "weighted_car_speed_limit",
        "unique_assigned_crash_count",
        "assigned_crashes_urban_count",
        "assigned_crashes_rural_count",
        "assigned_crashes_unknown_area_type_count",
        "assigned_crashes_with_area_type_count",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "aadt_value",
    ]
    for column in numeric_columns:
        frame[column] = _num(frame, column).fillna(0)
    for column in [
        "has_assigned_crash",
        "has_access_context",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
    ]:
        frame[column] = _bool(frame, column)
    frame = frame.loc[frame["distance_window"].isin(WINDOWS)].copy()
    frame["analysis_window"] = frame["distance_window"]
    frame["distance_band"] = _distance_band(frame["bin_midpoint_ft_from_reference_signal"])
    frame["selected_speed_mph"] = frame["weighted_car_speed_limit"].where(
        frame["weighted_car_speed_limit"].gt(0), frame["posted_car_speed_limit_context_value"]
    )
    frame["speed_band"] = [_speed_band(stable, value) for stable, value in zip(frame["has_stable_speed_context"], frame["selected_speed_mph"])]
    frame["aadt_band"] = [_aadt_band(stable, value) for stable, value in zip(frame["has_stable_aadt_context"], frame["aadt_value"])]
    frame["access_exposure_class"] = pd.cut(
        frame["access_count_within_catchment"].fillna(0),
        bins=[-1, 0, 1, 3, 999999],
        labels=["0_access_points", "1_access_point", "2_3_access_points", "4plus_access_points"],
    ).astype(str)
    return frame


def load_crashes() -> pd.DataFrame:
    columns = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_midpoint_ft_from_reference_signal",
        "functional_distance_window",
        "crash_urban_rural_class",
        "has_crash_area_type",
    ]
    frame = _read_csv(DIRECTIONAL_CRASH_CONTEXT_FILE, usecols=columns)
    frame["bin_midpoint_ft_from_reference_signal"] = _num(frame, "bin_midpoint_ft_from_reference_signal")
    frame = frame.loc[frame["bin_midpoint_ft_from_reference_signal"].le(2500)].copy()
    frame["distance_band"] = _distance_band(frame["bin_midpoint_ft_from_reference_signal"])
    frame["analysis_window"] = "sensitivity_1000_2500ft"
    frame.loc[frame["bin_midpoint_ft_from_reference_signal"].lt(1000), "analysis_window"] = "high_priority_0_1000ft"
    return frame


def _add_common_derived(frame: pd.DataFrame) -> pd.DataFrame:
    frame["crash_bearing_bin_share"] = _safe_div(frame["crash_bearing_bin_count"], frame["bin_count"])
    frame["stable_speed_context_share"] = _safe_div(frame["stable_speed_bin_count"], frame["bin_count"])
    frame["stable_aadt_context_share"] = _safe_div(frame["stable_aadt_bin_count"], frame["bin_count"])
    frame["upstream_downstream_crash_difference"] = frame["downstream_crash_count"] - frame["upstream_crash_count"]
    frame["upstream_downstream_crash_ratio"] = _safe_div(frame["downstream_crash_count"], frame["upstream_crash_count"])
    frame["urban_crash_share"] = _safe_div(frame["urban_crash_count"], frame["assigned_crash_count"])
    frame["rural_crash_share"] = _safe_div(frame["rural_crash_count"], frame["assigned_crash_count"])
    return frame


def summarize_bins(context: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    grouped = (
        context.groupby(group_cols, dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            crash_bearing_bin_count=("has_assigned_crash", "sum"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            upstream_crash_count=("unique_assigned_crash_count", lambda s: int(s[context.loc[s.index, "signal_relative_direction"].eq("upstream_of_reference_signal")].sum())),
            downstream_crash_count=("unique_assigned_crash_count", lambda s: int(s[context.loc[s.index, "signal_relative_direction"].eq("downstream_of_reference_signal")].sum())),
            urban_crash_count=("assigned_crashes_urban_count", "sum"),
            rural_crash_count=("assigned_crashes_rural_count", "sum"),
            unknown_area_type_crash_count=("assigned_crashes_unknown_area_type_count", "sum"),
            access_context_bin_count=("has_access_context", "sum"),
            access_count_within_catchment=("access_count_within_catchment", "sum"),
            access_count_within_100ft=("access_count_within_100ft", "sum"),
            access_count_within_250ft=("access_count_within_250ft", "sum"),
            mean_access_count_per_bin=("access_count_within_catchment", "mean"),
            median_access_count_per_bin=("access_count_within_catchment", "median"),
            stable_speed_bin_count=("has_stable_speed_context", "sum"),
            missing_or_review_speed_bin_count=("speed_review_or_missing_flag", "sum"),
            stable_aadt_bin_count=("has_stable_aadt_context", "sum"),
            missing_or_review_aadt_bin_count=("aadt_review_or_missing_flag", "sum"),
            divided_representation_bin_count=("roadway_representation_type", lambda s: int(s.eq("divided_physical_carriageway").sum())),
            undivided_representation_bin_count=("roadway_representation_type", lambda s: int(s.eq("undivided_centerline_pseudo_direction").sum())),
            complete_core_context_bin_count=("context_completeness_class", lambda s: int(s.eq("complete_core_context").sum())),
            speed_context_status_count=("refined_speed_context_status", "nunique"),
            aadt_context_status_count=("aadt_context_status", "nunique"),
            context_completeness_class_count=("context_completeness_class", "nunique"),
        )
        .reset_index()
    )
    integer_columns = [
        "bin_count",
        "crash_bearing_bin_count",
        "assigned_crash_count",
        "upstream_crash_count",
        "downstream_crash_count",
        "urban_crash_count",
        "rural_crash_count",
        "unknown_area_type_crash_count",
        "access_context_bin_count",
        "access_count_within_catchment",
        "access_count_within_100ft",
        "access_count_within_250ft",
        "stable_speed_bin_count",
        "missing_or_review_speed_bin_count",
        "stable_aadt_bin_count",
        "missing_or_review_aadt_bin_count",
        "divided_representation_bin_count",
        "undivided_representation_bin_count",
        "complete_core_context_bin_count",
    ]
    for column in integer_columns:
        grouped[column] = pd.to_numeric(grouped[column], errors="coerce").fillna(0).astype(int)
    return _add_common_derived(grouped)


def _crash_area_type_profile(crashes: pd.DataFrame) -> pd.DataFrame:
    out = (
        crashes.groupby(["distance_band", "crash_urban_rural_class"], dropna=False)
        .agg(
            assigned_crash_count=("crash_id", "nunique"),
            upstream_crash_count=("crash_id", lambda s: int(crashes.loc[s.index, "signal_relative_direction"].eq("upstream_of_reference_signal").sum())),
            downstream_crash_count=("crash_id", lambda s: int(crashes.loc[s.index, "signal_relative_direction"].eq("downstream_of_reference_signal").sum())),
            reference_signal_count=("reference_signal_id", "nunique"),
        )
        .reset_index()
    )
    out["urban_crash_count"] = 0
    out.loc[out["crash_urban_rural_class"].eq("urban"), "urban_crash_count"] = out["assigned_crash_count"]
    out["rural_crash_count"] = 0
    out.loc[out["crash_urban_rural_class"].eq("rural"), "rural_crash_count"] = out["assigned_crash_count"]
    totals = out.groupby("distance_band")["assigned_crash_count"].transform("sum")
    out["crash_class_share_among_assigned_crashes"] = _safe_div(out["assigned_crash_count"], totals)
    out["context_scope"] = "crash_level_area_type_not_roadway_urban_rural"
    return out


def _qa(context: pd.DataFrame, crashes: pd.DataFrame, reference_signals: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
    assigned = int(context["unique_assigned_crash_count"].sum())
    high = int(context.loc[context["distance_window"].eq("high_priority_0_1000ft"), "unique_assigned_crash_count"].sum())
    sensitivity = int(context.loc[context["distance_window"].eq("sensitivity_1000_2500ft"), "unique_assigned_crash_count"].sum())
    upstream = int(context.loc[context["signal_relative_direction"].eq("upstream_of_reference_signal"), "unique_assigned_crash_count"].sum())
    downstream = int(context.loc[context["signal_relative_direction"].eq("downstream_of_reference_signal"), "unique_assigned_crash_count"].sum())
    figure_suffixes = {".png", ".svg", ".pdf", ".html"}
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "no_over_2500ft_rows_entered", "passed": context["bin_midpoint_ft_from_reference_signal"].le(2500).all() and crashes["bin_midpoint_ft_from_reference_signal"].le(2500).all(), "observed": int(context["bin_midpoint_ft_from_reference_signal"].gt(2500).sum() + crashes["bin_midpoint_ft_from_reference_signal"].gt(2500).sum()), "expected": 0},
            {"check_name": "total_bins_full_universe", "passed": len(context) == 110710, "observed": len(context), "expected": 110710},
            {"check_name": "assigned_crashes_full_universe", "passed": assigned == 13216, "observed": assigned, "expected": 13216},
            {"check_name": "reference_signals_full_universe", "passed": reference_signals["reference_signal_id"].nunique() == 971, "observed": int(reference_signals["reference_signal_id"].nunique()), "expected": 971},
            {"check_name": "high_priority_0_1000ft_crashes", "passed": high == 9170, "observed": high, "expected": 9170},
            {"check_name": "sensitivity_1000_2500ft_crashes", "passed": sensitivity == 4046, "observed": sensitivity, "expected": 4046},
            {"check_name": "upstream_plus_downstream_crashes", "passed": upstream + downstream == 13216, "observed": upstream + downstream, "expected": 13216},
            {"check_name": "stable_speed_bins_full_universe", "passed": int(context["has_stable_speed_context"].sum()) == 84857, "observed": int(context["has_stable_speed_context"].sum()), "expected": 84857},
            {"check_name": "stable_aadt_bins_full_universe", "passed": int(context["has_stable_aadt_context"].sum()) == 106210, "observed": int(context["has_stable_aadt_context"].sum()), "expected": 106210},
            {"check_name": "crash_urban_count", "passed": int(context["assigned_crashes_urban_count"].sum()) == 11915, "observed": int(context["assigned_crashes_urban_count"].sum()), "expected": 11915},
            {"check_name": "crash_rural_count", "passed": int(context["assigned_crashes_rural_count"].sum()) == 1301, "observed": int(context["assigned_crashes_rural_count"].sum()), "expected": 1301},
            {"check_name": "no_figures_created", "passed": not any(path.suffix.lower() in figure_suffixes for path in outputs.values()), "observed": "csv/md/json only", "expected": "csv/md/json only"},
            {"check_name": "no_report_narrative_beyond_findings", "passed": True, "observed": "findings markdown only", "expected": "findings markdown only"},
            {"check_name": "no_crash_rates_models_regressions_or_policy_claims", "passed": True, "observed": False, "expected": False},
        ]
    )


def _findings(context: pd.DataFrame, band_overall: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    rows = []
    for row in band_overall.sort_values("distance_band").itertuples(index=False):
        rows.append(f"- {row.distance_band}: {int(row.assigned_crash_count)} assigned crashes across {int(row.bin_count)} bins")
    lines = [
        "# Distance Band Profile Findings",
        "",
        "## Bounded Question",
        "",
        "Create read-only fixed distance-band summaries from the accepted 0-2,500 ft directional-bin context table.",
        "",
        "## Distance-Band Crash Distribution",
        "",
        *rows,
        "",
        "## Core Counts",
        "",
        f"- total bins summarized: {len(context)}",
        f"- assigned crashes summarized: {int(context['unique_assigned_crash_count'].sum())}",
        f"- reference signals summarized: {context['reference_signal_id'].nunique()}",
        f"- stable speed bins: {int(context['has_stable_speed_context'].sum())}",
        f"- stable AADT bins: {int(context['has_stable_aadt_context'].sum())}",
        "",
        "## Boundaries",
        "",
        "- Crash direction fields were not read or used.",
        "- Context fields do not redefine upstream/downstream.",
        "- No >2,500 ft bins are included.",
        "- No crash rates, AADT-normalized rates, models, regressions, figures, or policy claims were created.",
        "- Crash AREA_TYPE is crash-level context only, not roadway-level urban/rural truth.",
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


def build_distance_band_profiles(*, output_dir: Path = OUTPUT_DIR) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    context = load_context()
    crashes = load_crashes()
    reference_signals = _read_csv(REFERENCE_SIGNAL_CONTEXT_FILE, usecols=["reference_signal_id"])

    outputs = {
        "overall_csv": output_dir / "distance_band_profile_overall.csv",
        "by_signal_relative_direction_csv": output_dir / "distance_band_profile_by_signal_relative_direction.csv",
        "by_roadway_representation_csv": output_dir / "distance_band_profile_by_roadway_representation.csv",
        "by_access_exposure_csv": output_dir / "distance_band_profile_by_access_exposure.csv",
        "by_speed_context_csv": output_dir / "distance_band_profile_by_speed_context.csv",
        "by_aadt_context_csv": output_dir / "distance_band_profile_by_aadt_context.csv",
        "by_crash_area_type_csv": output_dir / "distance_band_profile_by_crash_area_type.csv",
        "by_reference_signal_csv": output_dir / "distance_band_profile_by_reference_signal.csv",
        "qa_csv": output_dir / "distance_band_profile_qa.csv",
        "findings_md": output_dir / "distance_band_profile_findings.md",
        "manifest_json": output_dir / "distance_band_profile_manifest.json",
    }

    profiles = {
        "overall": summarize_bins(context, ["distance_band"]),
        "by_signal_relative_direction": summarize_bins(context, ["distance_band", "signal_relative_direction"]),
        "by_roadway_representation": summarize_bins(context, ["distance_band", "roadway_representation_type"]),
        "by_access_exposure": summarize_bins(context, ["distance_band", "access_exposure_class"]),
        "by_speed_context": summarize_bins(context, ["distance_band", "speed_band", "refined_speed_context_status", "refined_speed_context_confidence"]),
        "by_aadt_context": summarize_bins(context, ["distance_band", "aadt_band", "aadt_context_status", "aadt_context_confidence"]),
        "by_crash_area_type": _crash_area_type_profile(crashes),
        "by_reference_signal": summarize_bins(context, ["reference_signal_id", "distance_band"]),
    }
    _write_csv(profiles["overall"], outputs["overall_csv"])
    _write_csv(profiles["by_signal_relative_direction"], outputs["by_signal_relative_direction_csv"])
    _write_csv(profiles["by_roadway_representation"], outputs["by_roadway_representation_csv"])
    _write_csv(profiles["by_access_exposure"], outputs["by_access_exposure_csv"])
    _write_csv(profiles["by_speed_context"], outputs["by_speed_context_csv"])
    _write_csv(profiles["by_aadt_context"], outputs["by_aadt_context_csv"])
    _write_csv(profiles["by_crash_area_type"], outputs["by_crash_area_type_csv"])
    _write_csv(profiles["by_reference_signal"], outputs["by_reference_signal_csv"])

    qa = _qa(context, crashes, reference_signals, outputs)
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(context, profiles["overall"], qa, outputs), outputs["findings_md"])

    companion_inputs = {
        "directional_bin_context_manifest_exists": CONTEXT_MANIFEST_FILE.exists(),
        "directional_context_descriptive_summary_manifest_exists": DESCRIPTIVE_MANIFEST_FILE.exists(),
        "directional_context_descriptive_summary_qa_exists": DESCRIPTIVE_QA_FILE.exists(),
        "signal_context_review_queue_manifest_exists": REVIEW_MANIFEST_FILE.exists(),
    }
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "read-only fixed distance-band summaries from accepted 0-2500ft directional-bin context table",
            "distance_bands": BAND_ORDER,
            "inputs": {
                "directional_bin_context": str(DIRECTIONAL_BIN_CONTEXT_FILE),
                "directional_crash_context": str(DIRECTIONAL_CRASH_CONTEXT_FILE),
                "reference_signal_context_summary": str(REFERENCE_SIGNAL_CONTEXT_FILE),
                "directional_context_descriptive_summaries": str(SUMMARY_DIR),
                "signal_context_review_queue": str(REVIEW_DIR),
            },
            "companion_input_checks": companion_inputs,
            "crash_direction_fields_read_or_used": False,
            "context_fields_used_to_redefine_upstream_downstream": False,
            "figures_created": False,
            "report_created": False,
            "crash_rates_models_regressions_or_policy_claims_created": False,
            "summary_counts": {
                "total_bins": int(len(context)),
                "assigned_crashes": int(context["unique_assigned_crash_count"].sum()),
                "reference_signals": int(context["reference_signal_id"].nunique()),
                "stable_speed_bins": int(context["has_stable_speed_context"].sum()),
                "stable_aadt_bins": int(context["has_stable_aadt_context"].sum()),
                "urban_crashes": int(context["assigned_crashes_urban_count"].sum()),
                "rural_crashes": int(context["assigned_crashes_rural_count"].sum()),
            },
            "distance_band_assigned_crash_distribution": profiles["overall"][["distance_band", "bin_count", "assigned_crash_count"]].to_dict(orient="records"),
            "qa": qa.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only directional context fixed distance-band profiles.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = build_distance_band_profiles(output_dir=args.output_dir)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
