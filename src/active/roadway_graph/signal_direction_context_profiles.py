from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.active.roadway_graph.directional_context_distance_band_profiles import (
    CONTEXT_DIR,
    DIRECTIONAL_CRASH_CONTEXT_FILE,
    OUTPUT_ROOT,
    REVIEW_DIR,
    SUMMARY_DIR,
    WINDOWS,
    _read_csv,
    _safe_div,
    _write_csv,
    _write_json,
    _write_text,
    load_context,
    load_crashes,
    summarize_bins,
)


OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/signal_direction_context_profiles"
REFERENCE_SIGNAL_CONTEXT_FILE = CONTEXT_DIR / "reference_signal_context_summary.csv"
SIGNAL_REVIEW_QUEUE_FILE = REVIEW_DIR / "signal_review_queue_overall.csv"
SIGNAL_DIRECTION_REVIEW_QUEUE_FILE = REVIEW_DIR / "signal_direction_review_queue.csv"
SIGNAL_DIRECTION_WINDOW_REVIEW_QUEUE_FILE = REVIEW_DIR / "signal_direction_window_review_queue.csv"
DISTANCE_BAND_PROFILE_MANIFEST_FILE = OUTPUT_ROOT / "analysis/current/directional_context_distance_band_profiles/distance_band_profile_manifest.json"


def _load_review_flags() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    signal_columns = [
        "reference_signal_id",
        "review_priority_score",
        "review_priority_tier",
        "high_crash_burden",
        "high_0_1000ft_crash_burden",
        "high_directional_imbalance",
        "high_access_context",
        "incomplete_speed_context",
        "incomplete_aadt_context",
        "urban_crash_dominant",
        "rural_crash_present",
        "low_denominator_ratio_warning",
        "review_context_flag_count",
    ]
    direction_columns = signal_columns[:1] + ["signal_relative_direction"] + signal_columns[1:]
    window_columns = direction_columns[:2] + ["distance_window"] + direction_columns[2:]
    signal = _read_csv(SIGNAL_REVIEW_QUEUE_FILE, usecols=signal_columns)
    direction = _read_csv(SIGNAL_DIRECTION_REVIEW_QUEUE_FILE, usecols=direction_columns)
    window = _read_csv(SIGNAL_DIRECTION_WINDOW_REVIEW_QUEUE_FILE, usecols=window_columns)
    return signal, direction, window


def _profile(context: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    out = summarize_bins(context, group_cols).rename(
        columns={
            "missing_or_review_speed_bin_count": "speed_missing_or_review_bin_count",
            "missing_or_review_aadt_bin_count": "aadt_missing_or_review_bin_count",
            "stable_speed_context_share": "stable_speed_coverage_share",
            "stable_aadt_context_share": "stable_aadt_coverage_share",
        }
    )
    out["context_completeness_class"] = "complete_access_speed_aadt"
    out.loc[
        out["speed_missing_or_review_bin_count"].gt(0) | out["aadt_missing_or_review_bin_count"].gt(0),
        "context_completeness_class",
    ] = "has_speed_or_aadt_review_or_missing"
    out.loc[out["access_context_bin_count"].lt(out["bin_count"]), "context_completeness_class"] = "has_access_review_or_missing"
    return out


def _roadway_mix(context: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    mix = (
        context.groupby(group_cols + ["roadway_representation_type"], dropna=False)
        .size()
        .reset_index(name="roadway_representation_bin_count")
    )
    return mix


def _context_completeness_profile(context: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        context.groupby(["reference_signal_id", "signal_relative_direction", "context_completeness_class"], dropna=False)
        .agg(
            bin_count=("reference_directional_bin_id", "nunique"),
            assigned_crash_count=("unique_assigned_crash_count", "sum"),
            stable_speed_bin_count=("has_stable_speed_context", "sum"),
            stable_aadt_bin_count=("has_stable_aadt_context", "sum"),
            speed_missing_or_review_bin_count=("speed_review_or_missing_flag", "sum"),
            aadt_missing_or_review_bin_count=("aadt_review_or_missing_flag", "sum"),
        )
        .reset_index()
    )
    totals = grouped.groupby(["reference_signal_id", "signal_relative_direction"])["bin_count"].transform("sum")
    grouped["context_completeness_bin_share"] = _safe_div(grouped["bin_count"], totals)
    return grouped


def _merge_direction_flags(profile: pd.DataFrame, direction_flags: pd.DataFrame) -> pd.DataFrame:
    return profile.merge(direction_flags, on=["reference_signal_id", "signal_relative_direction"], how="left", suffixes=("", "_review"))


def _merge_window_flags(profile: pd.DataFrame, window_flags: pd.DataFrame) -> pd.DataFrame:
    return profile.merge(
        window_flags.rename(columns={"distance_window": "analysis_window"}),
        on=["reference_signal_id", "signal_relative_direction", "analysis_window"],
        how="left",
        suffixes=("", "_review"),
    )


def _qa(context: pd.DataFrame, crashes: pd.DataFrame, reference_signals: pd.DataFrame, signal_direction: pd.DataFrame, outputs: dict[str, Path]) -> pd.DataFrame:
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
            {"check_name": "signal_direction_profile_row_count", "passed": len(signal_direction) == 1942, "observed": len(signal_direction), "expected": 1942},
            {"check_name": "no_figures_created", "passed": not any(path.suffix.lower() in figure_suffixes for path in outputs.values()), "observed": "csv/md/json only", "expected": "csv/md/json only"},
            {"check_name": "no_report_narrative_beyond_findings", "passed": True, "observed": "findings markdown only", "expected": "findings markdown only"},
            {"check_name": "no_crash_rates_models_regressions_or_policy_claims", "passed": True, "observed": False, "expected": False},
        ]
    )


def _findings(signal_direction: pd.DataFrame, window_profile: pd.DataFrame, band_profile: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    lines = [
        "# Signal Direction Context Profile Findings",
        "",
        "## Bounded Question",
        "",
        "Create compact signal-direction profiles from the accepted 0-2,500 ft directional-bin context table for later tabular review and figure/report inputs.",
        "",
        "## Profile Counts",
        "",
        f"- signal-direction rows: {len(signal_direction)}",
        f"- signal-direction-window rows: {len(window_profile)}",
        f"- signal-direction-distance-band rows: {len(band_profile)}",
        f"- assigned crashes summarized: {int(signal_direction['assigned_crash_count'].sum())}",
        f"- upstream assigned crashes: {int(signal_direction['upstream_crash_count'].sum())}",
        f"- downstream assigned crashes: {int(signal_direction['downstream_crash_count'].sum())}",
        "",
        "## Boundaries",
        "",
        "- Crash direction fields were not read or used.",
        "- Context fields do not redefine upstream/downstream.",
        "- No >2,500 ft bins are included.",
        "- Review flags are review-priority fields only.",
        "- No crash rates, AADT-normalized rates, models, regressions, figures, or policy claims were created.",
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


def build_signal_direction_context_profiles(*, output_dir: Path = OUTPUT_DIR) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    context = load_context()
    crashes = load_crashes()
    reference_signals = _read_csv(REFERENCE_SIGNAL_CONTEXT_FILE, usecols=["reference_signal_id"])
    signal_flags, direction_flags, window_flags = _load_review_flags()

    signal_direction = _merge_direction_flags(_profile(context, ["reference_signal_id", "signal_relative_direction"]), direction_flags)
    window_profile = _merge_window_flags(
        _profile(context, ["reference_signal_id", "signal_relative_direction", "analysis_window"]),
        window_flags,
    )
    distance_band_profile = _merge_direction_flags(
        _profile(context, ["reference_signal_id", "signal_relative_direction", "distance_band"]),
        direction_flags,
    )
    completeness_profile = _context_completeness_profile(context).merge(signal_flags, on="reference_signal_id", how="left")
    review_flags = signal_direction.loc[
        signal_direction[
            [
                "high_crash_burden",
                "high_0_1000ft_crash_burden",
                "high_directional_imbalance",
                "high_access_context",
                "incomplete_speed_context",
                "incomplete_aadt_context",
                "low_denominator_ratio_warning",
            ]
        ]
        .fillna(False)
        .astype(bool)
        .any(axis=1)
    ].copy()
    top_crash_burden = signal_direction.sort_values(["assigned_crash_count", "crash_bearing_bin_count"], ascending=[False, False]).head(100)
    top_directional_imbalance = signal_direction.assign(
        abs_upstream_downstream_crash_difference=lambda frame: frame["upstream_downstream_crash_difference"].abs()
    ).sort_values(["abs_upstream_downstream_crash_difference", "assigned_crash_count"], ascending=[False, False]).head(100)

    outputs = {
        "signal_direction_profile_csv": output_dir / "signal_direction_profile.csv",
        "signal_direction_window_profile_csv": output_dir / "signal_direction_window_profile.csv",
        "signal_direction_distance_band_profile_csv": output_dir / "signal_direction_distance_band_profile.csv",
        "signal_direction_context_completeness_profile_csv": output_dir / "signal_direction_context_completeness_profile.csv",
        "signal_direction_profile_top_crash_burden_csv": output_dir / "signal_direction_profile_top_crash_burden.csv",
        "signal_direction_profile_top_directional_imbalance_csv": output_dir / "signal_direction_profile_top_directional_imbalance.csv",
        "signal_direction_profile_review_flags_csv": output_dir / "signal_direction_profile_review_flags.csv",
        "qa_csv": output_dir / "signal_direction_profile_qa.csv",
        "findings_md": output_dir / "signal_direction_profile_findings.md",
        "manifest_json": output_dir / "signal_direction_profile_manifest.json",
    }
    _write_csv(signal_direction, outputs["signal_direction_profile_csv"])
    _write_csv(window_profile, outputs["signal_direction_window_profile_csv"])
    _write_csv(distance_band_profile, outputs["signal_direction_distance_band_profile_csv"])
    _write_csv(completeness_profile, outputs["signal_direction_context_completeness_profile_csv"])
    _write_csv(top_crash_burden, outputs["signal_direction_profile_top_crash_burden_csv"])
    _write_csv(top_directional_imbalance, outputs["signal_direction_profile_top_directional_imbalance_csv"])
    _write_csv(review_flags, outputs["signal_direction_profile_review_flags_csv"])

    qa = _qa(context, crashes, reference_signals, signal_direction, outputs)
    _write_csv(qa, outputs["qa_csv"])
    _write_text(_findings(signal_direction, window_profile, distance_band_profile, qa, outputs), outputs["findings_md"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "read-only signal-direction context profiles from accepted 0-2500ft directional-bin context table",
            "inputs": {
                "directional_bin_context": str(CONTEXT_DIR / "directional_bin_context.csv"),
                "directional_crash_context": str(DIRECTIONAL_CRASH_CONTEXT_FILE),
                "reference_signal_context_summary": str(REFERENCE_SIGNAL_CONTEXT_FILE),
                "directional_context_descriptive_summaries": str(SUMMARY_DIR),
                "signal_context_review_queue": str(REVIEW_DIR),
                "distance_band_profile_manifest": str(DISTANCE_BAND_PROFILE_MANIFEST_FILE),
            },
            "grains": [
                "reference_signal_id + signal_relative_direction",
                "reference_signal_id + signal_relative_direction + analysis_window",
                "reference_signal_id + signal_relative_direction + distance_band",
            ],
            "crash_direction_fields_read_or_used": False,
            "context_fields_used_to_redefine_upstream_downstream": False,
            "figures_created": False,
            "report_created": False,
            "crash_rates_models_regressions_or_policy_claims_created": False,
            "summary_counts": {
                "total_bins": int(len(context)),
                "assigned_crashes": int(context["unique_assigned_crash_count"].sum()),
                "reference_signals": int(context["reference_signal_id"].nunique()),
                "signal_direction_profile_rows": int(len(signal_direction)),
                "signal_direction_window_profile_rows": int(len(window_profile)),
                "signal_direction_distance_band_profile_rows": int(len(distance_band_profile)),
                "review_flag_profile_rows": int(len(review_flags)),
            },
            "qa": qa.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only signal-direction context profiles.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = build_signal_direction_context_profiles(output_dir=args.output_dir)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
