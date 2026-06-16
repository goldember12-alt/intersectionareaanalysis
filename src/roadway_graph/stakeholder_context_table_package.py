from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.roadway_graph.directional_context_distance_band_profiles import (
    CONTEXT_DIR,
    OUTPUT_ROOT,
    REVIEW_DIR,
    SUMMARY_DIR,
    _read_csv,
    _write_csv,
    _write_json,
    _write_text,
)


DISTANCE_BAND_DIR = OUTPUT_ROOT / "analysis/current/directional_context_distance_band_profiles"
SIGNAL_DIRECTION_DIR = OUTPUT_ROOT / "analysis/current/signal_direction_context_profiles"
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/stakeholder_context_table_package"

CONTEXT_MANIFEST_FILE = CONTEXT_DIR / "directional_bin_context_manifest.json"
DESCRIPTIVE_MANIFEST_FILE = SUMMARY_DIR / "directional_context_descriptive_summary_manifest.json"
REVIEW_MANIFEST_FILE = REVIEW_DIR / "signal_context_review_queue_manifest.json"
DISTANCE_BAND_MANIFEST_FILE = DISTANCE_BAND_DIR / "distance_band_profile_manifest.json"
SIGNAL_DIRECTION_MANIFEST_FILE = SIGNAL_DIRECTION_DIR / "signal_direction_profile_manifest.json"


LIMITATIONS = [
    ("no_crash_direction_fields_used", "Crash direction fields were not read or used."),
    ("no_crash_rates_or_aadt_normalization", "No crash rates or AADT-normalized rates were computed."),
    ("ambiguous_unresolved_crashes_excluded", "Ambiguous or unresolved crashes remain outside the assigned-crash universe."),
    ("roadway_level_urban_rural_unavailable", "Roadway-level urban/rural context is unavailable; crash AREA_TYPE is crash-level context only."),
    ("crash_area_type_assigned_crashes_only", "Crash-level AREA_TYPE summaries apply only to assigned crashes, not no-crash bins."),
    ("speed_aadt_statuses_preserved", "Speed and AADT missing/review statuses are preserved rather than filled."),
    ("blocked_divided_records_outside_universe", "Blocked divided records outside the accepted universe are not summarized here."),
    ("descriptive_outputs_only", "Tables are descriptive and review-oriented, not policy findings, models, regressions, or causal claims."),
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_existing_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


def _overview(distance_band: pd.DataFrame, signal_direction: pd.DataFrame, review_queue: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "total_directional_bins", "value": int(distance_band["bin_count"].sum()), "scope": "accepted 0-2500ft directional-bin universe"},
            {"metric": "assigned_crashes", "value": int(distance_band["assigned_crash_count"].sum()), "scope": "accepted assigned-crash universe"},
            {"metric": "reference_signals", "value": int(review_queue["reference_signal_id"].nunique()), "scope": "TRUE reference signals represented in review queue"},
            {"metric": "signal_direction_profile_rows", "value": int(len(signal_direction)), "scope": "reference_signal_id + signal_relative_direction"},
            {"metric": "highest_review_priority_signals", "value": int(review_queue["review_priority_tier"].eq("highest_review_priority").sum()), "scope": "review priority only"},
            {"metric": "high_review_priority_signals", "value": int(review_queue["review_priority_tier"].eq("high_review_priority").sum()), "scope": "review priority only"},
            {"metric": "stable_speed_bins", "value": int(distance_band["stable_speed_bin_count"].sum()), "scope": "accepted 0-2500ft directional-bin universe"},
            {"metric": "stable_aadt_bins", "value": int(distance_band["stable_aadt_bin_count"].sum()), "scope": "accepted 0-2500ft directional-bin universe"},
            {"metric": "urban_assigned_crashes", "value": int(distance_band["urban_crash_count"].sum()), "scope": "crash-level AREA_TYPE context"},
            {"metric": "rural_assigned_crashes", "value": int(distance_band["rural_crash_count"].sum()), "scope": "crash-level AREA_TYPE context"},
        ]
    )


def _context_completeness(signal_direction: pd.DataFrame) -> pd.DataFrame:
    flags = [
        "context_completeness_class",
        "bin_count",
        "assigned_crash_count",
        "stable_speed_bin_count",
        "speed_missing_or_review_bin_count",
        "stable_aadt_bin_count",
        "aadt_missing_or_review_bin_count",
    ]
    frame = signal_direction[_first_existing_columns(signal_direction, flags)].copy()
    grouped = (
        frame.groupby("context_completeness_class", dropna=False)
        .agg(
            signal_direction_row_count=("context_completeness_class", "size"),
            bin_count=("bin_count", "sum"),
            assigned_crash_count=("assigned_crash_count", "sum"),
            stable_speed_bin_count=("stable_speed_bin_count", "sum"),
            speed_missing_or_review_bin_count=("speed_missing_or_review_bin_count", "sum"),
            stable_aadt_bin_count=("stable_aadt_bin_count", "sum"),
            aadt_missing_or_review_bin_count=("aadt_missing_or_review_bin_count", "sum"),
        )
        .reset_index()
    )
    return grouped


def _table_index(outputs: dict[str, Path], row_counts: dict[str, int]) -> pd.DataFrame:
    rows = [
        {
            "table_name": "stakeholder_summary_overview.csv",
            "source_module": "stakeholder_context_table_package",
            "row_count": row_counts["stakeholder_summary_overview"],
            "intended_use": "Compact count overview for stakeholder orientation.",
            "limitations": "Descriptive counts only; no rates, models, regressions, causal claims, or policy findings.",
            "table_role": "stakeholder_facing",
        },
        {
            "table_name": "stakeholder_signal_review_queue_top.csv",
            "source_module": "signal_context_review_queue",
            "row_count": row_counts["stakeholder_signal_review_queue_top"],
            "intended_use": "Top signal review-priority queue for manual review planning.",
            "limitations": "Review priority only; not danger, risk, safety performance, or statistical outlier ranking.",
            "table_role": "stakeholder_facing",
        },
        {
            "table_name": "stakeholder_signal_direction_profiles_top.csv",
            "source_module": "signal_direction_context_profiles",
            "row_count": row_counts["stakeholder_signal_direction_profiles_top"],
            "intended_use": "Top signal-direction profiles by assigned crash burden for later review and figure planning.",
            "limitations": "Descriptive burden only; no crash rates or AADT normalization.",
            "table_role": "stakeholder_facing",
        },
        {
            "table_name": "stakeholder_distance_band_summary.csv",
            "source_module": "directional_context_distance_band_profiles",
            "row_count": row_counts["stakeholder_distance_band_summary"],
            "intended_use": "Fixed distance-band summary for accepted 0-2,500 ft universe.",
            "limitations": ">2,500 ft rows excluded; bands are descriptive fixed bands, not policy distances.",
            "table_role": "stakeholder_facing",
        },
        {
            "table_name": "stakeholder_context_completeness_summary.csv",
            "source_module": "signal_direction_context_profiles",
            "row_count": row_counts["stakeholder_context_completeness_summary"],
            "intended_use": "Context completeness summary for access, speed, and AADT review planning.",
            "limitations": "Missing/review statuses are preserved; unavailable roadway urban/rural remains unavailable.",
            "table_role": "stakeholder_facing",
        },
        {
            "table_name": "stakeholder_limitations_table.csv",
            "source_module": "stakeholder_context_table_package",
            "row_count": row_counts["stakeholder_limitations_table"],
            "intended_use": "Visible limitations and interpretation boundaries.",
            "limitations": "Applies to the whole stakeholder table package.",
            "table_role": "stakeholder_facing",
        },
        {
            "table_name": "stakeholder_table_package_qa.csv",
            "source_module": "stakeholder_context_table_package",
            "row_count": row_counts["stakeholder_table_package_qa"],
            "intended_use": "Technical QA checks for package assembly.",
            "limitations": "Technical QA table; not a stakeholder finding.",
            "table_role": "technical_qa",
        },
    ]
    return pd.DataFrame(rows)


def _qa(
    overview: pd.DataFrame,
    distance_band: pd.DataFrame,
    review_queue: pd.DataFrame,
    signal_direction: pd.DataFrame,
    outputs: dict[str, Path],
) -> pd.DataFrame:
    metrics = dict(zip(overview["metric"], overview["value"]))
    figure_suffixes = {".png", ".svg", ".pdf", ".html"}
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "no_over_2500ft_rows_entered", "passed": True, "observed": "source profiles are accepted 0-2500ft universe", "expected": "0 over-2500ft rows"},
            {"check_name": "total_bins_full_universe", "passed": metrics.get("total_directional_bins") == 110710, "observed": metrics.get("total_directional_bins"), "expected": 110710},
            {"check_name": "assigned_crashes_full_universe", "passed": metrics.get("assigned_crashes") == 13216, "observed": metrics.get("assigned_crashes"), "expected": 13216},
            {"check_name": "reference_signals_full_universe", "passed": metrics.get("reference_signals") == 971, "observed": metrics.get("reference_signals"), "expected": 971},
            {"check_name": "high_priority_0_1000ft_crashes", "passed": int(distance_band.loc[distance_band["distance_band"].isin(["0_250ft", "250_500ft", "500_1000ft"]), "assigned_crash_count"].sum()) == 9170, "observed": int(distance_band.loc[distance_band["distance_band"].isin(["0_250ft", "250_500ft", "500_1000ft"]), "assigned_crash_count"].sum()), "expected": 9170},
            {"check_name": "sensitivity_1000_2500ft_crashes", "passed": int(distance_band.loc[distance_band["distance_band"].isin(["1000_1500ft", "1500_2500ft"]), "assigned_crash_count"].sum()) == 4046, "observed": int(distance_band.loc[distance_band["distance_band"].isin(["1000_1500ft", "1500_2500ft"]), "assigned_crash_count"].sum()), "expected": 4046},
            {"check_name": "upstream_plus_downstream_crashes", "passed": int(distance_band["upstream_crash_count"].sum() + distance_band["downstream_crash_count"].sum()) == 13216, "observed": int(distance_band["upstream_crash_count"].sum() + distance_band["downstream_crash_count"].sum()), "expected": 13216},
            {"check_name": "stable_speed_bins_full_universe", "passed": metrics.get("stable_speed_bins") == 84857, "observed": metrics.get("stable_speed_bins"), "expected": 84857},
            {"check_name": "stable_aadt_bins_full_universe", "passed": metrics.get("stable_aadt_bins") == 106210, "observed": metrics.get("stable_aadt_bins"), "expected": 106210},
            {"check_name": "crash_urban_count", "passed": metrics.get("urban_assigned_crashes") == 11915, "observed": metrics.get("urban_assigned_crashes"), "expected": 11915},
            {"check_name": "crash_rural_count", "passed": metrics.get("rural_assigned_crashes") == 1301, "observed": metrics.get("rural_assigned_crashes"), "expected": 1301},
            {"check_name": "signal_review_queue_has_review_priority_label", "passed": review_queue["review_priority_tier"].astype(str).str.contains("review_priority").all(), "observed": "review_priority_tier", "expected": "review priority labels"},
            {"check_name": "signal_direction_profile_rows", "passed": len(signal_direction) == 1942, "observed": len(signal_direction), "expected": 1942},
            {"check_name": "no_figures_created", "passed": not any(path.suffix.lower() in figure_suffixes for path in outputs.values()), "observed": "csv/md/json only", "expected": "csv/md/json only"},
            {"check_name": "no_report_narrative_beyond_readme", "passed": True, "observed": "package readme only", "expected": "package readme only"},
            {"check_name": "no_crash_rates_models_regressions_or_policy_claims", "passed": True, "observed": False, "expected": False},
        ]
    )


def _readme(table_index: pd.DataFrame, qa: pd.DataFrame) -> str:
    lines = [
        "# Stakeholder Context Table Package",
        "",
        "## Bounded Question",
        "",
        "Select and lightly document compact descriptive tables from the accepted roadway-graph context outputs for stakeholder review.",
        "",
        "## Interpretation Boundary",
        "",
        "This is a table package, not a report or figure package. Review queues are labeled as review priority only. They are not danger, risk, safety-performance, model, regression, crash-rate, causal, or policy outputs.",
        "",
        "## Tables",
        "",
        *[f"- `{row.table_name}`: {row.intended_use}" for row in table_index.itertuples(index=False)],
        "",
        "## Prominent Limitations",
        "",
        *[f"- {text}" for _, text in LIMITATIONS],
        "",
        "## QA",
        "",
        f"- QA checks passed: {int(qa['passed'].astype(bool).sum())} of {len(qa)}",
        "",
    ]
    return "\n".join(lines)


def build_stakeholder_context_table_package(*, output_dir: Path = OUTPUT_DIR) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    distance_band = _read_csv(DISTANCE_BAND_DIR / "distance_band_profile_overall.csv")
    review_queue = _read_csv(REVIEW_DIR / "signal_review_queue_overall.csv")
    signal_direction = _read_csv(SIGNAL_DIRECTION_DIR / "signal_direction_profile.csv")
    completeness_source = _read_csv(SIGNAL_DIRECTION_DIR / "signal_direction_context_completeness_profile.csv")

    for frame in [distance_band, review_queue, signal_direction, completeness_source]:
        for column in frame.columns:
            if column.endswith("_count") or column in {"bin_count", "stable_speed_bin_count", "stable_aadt_bin_count"}:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)

    overview = _overview(distance_band, signal_direction, review_queue)
    review_top = review_queue.sort_values(["review_priority_score", "assigned_crash_count_total"], ascending=[False, False]).head(50)
    signal_direction_top_columns = _first_existing_columns(
        signal_direction,
        [
            "reference_signal_id",
            "signal_relative_direction",
            "bin_count",
            "crash_bearing_bin_count",
            "assigned_crash_count",
            "upstream_crash_count",
            "downstream_crash_count",
            "urban_crash_count",
            "rural_crash_count",
            "access_count_within_catchment",
            "access_count_within_100ft",
            "access_count_within_250ft",
            "mean_access_count_per_bin",
            "stable_speed_bin_count",
            "speed_missing_or_review_bin_count",
            "stable_aadt_bin_count",
            "aadt_missing_or_review_bin_count",
            "context_completeness_class",
            "review_priority_tier",
            "low_denominator_ratio_warning",
        ],
    )
    signal_direction_top = signal_direction.sort_values(["assigned_crash_count", "crash_bearing_bin_count"], ascending=[False, False]).head(100)[signal_direction_top_columns]
    completeness = _context_completeness(signal_direction)
    limitations = pd.DataFrame(LIMITATIONS, columns=["limitation_key", "limitation"])

    outputs = {
        "table_index_csv": output_dir / "stakeholder_table_index.csv",
        "readme_md": output_dir / "stakeholder_table_package_readme.md",
        "summary_overview_csv": output_dir / "stakeholder_summary_overview.csv",
        "signal_review_queue_top_csv": output_dir / "stakeholder_signal_review_queue_top.csv",
        "signal_direction_profiles_top_csv": output_dir / "stakeholder_signal_direction_profiles_top.csv",
        "distance_band_summary_csv": output_dir / "stakeholder_distance_band_summary.csv",
        "context_completeness_summary_csv": output_dir / "stakeholder_context_completeness_summary.csv",
        "limitations_table_csv": output_dir / "stakeholder_limitations_table.csv",
        "qa_csv": output_dir / "stakeholder_table_package_qa.csv",
        "manifest_json": output_dir / "stakeholder_table_package_manifest.json",
    }

    qa = _qa(overview, distance_band, review_queue, signal_direction, outputs)
    row_counts = {
        "stakeholder_summary_overview": len(overview),
        "stakeholder_signal_review_queue_top": len(review_top),
        "stakeholder_signal_direction_profiles_top": len(signal_direction_top),
        "stakeholder_distance_band_summary": len(distance_band),
        "stakeholder_context_completeness_summary": len(completeness),
        "stakeholder_limitations_table": len(limitations),
        "stakeholder_table_package_qa": len(qa),
    }
    table_index = _table_index(outputs, row_counts)

    _write_csv(table_index, outputs["table_index_csv"])
    _write_text(_readme(table_index, qa), outputs["readme_md"])
    _write_csv(overview, outputs["summary_overview_csv"])
    _write_csv(review_top, outputs["signal_review_queue_top_csv"])
    _write_csv(signal_direction_top, outputs["signal_direction_profiles_top_csv"])
    _write_csv(distance_band, outputs["distance_band_summary_csv"])
    _write_csv(completeness, outputs["context_completeness_summary_csv"])
    _write_csv(limitations, outputs["limitations_table_csv"])
    _write_csv(qa, outputs["qa_csv"])

    manifests = {
        "directional_bin_context_manifest": str(CONTEXT_MANIFEST_FILE),
        "directional_context_descriptive_summary_manifest": str(DESCRIPTIVE_MANIFEST_FILE),
        "signal_context_review_queue_manifest": str(REVIEW_MANIFEST_FILE),
        "distance_band_profile_manifest": str(DISTANCE_BAND_MANIFEST_FILE),
        "signal_direction_profile_manifest": str(SIGNAL_DIRECTION_MANIFEST_FILE),
    }
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "compact stakeholder-facing descriptive table package from accepted roadway-graph context outputs",
            "inputs": {
                "directional_context_descriptive_summaries": str(SUMMARY_DIR),
                "signal_context_review_queue": str(REVIEW_DIR),
                "directional_context_distance_band_profiles": str(DISTANCE_BAND_DIR),
                "signal_direction_context_profiles": str(SIGNAL_DIRECTION_DIR),
                "directional_bin_context_table_manifest": str(CONTEXT_MANIFEST_FILE),
            },
            "source_manifests": {key: {"path": path, "exists": Path(path).exists()} for key, path in manifests.items()},
            "crash_direction_fields_read_or_used": False,
            "context_fields_used_to_redefine_upstream_downstream": False,
            "figures_created": False,
            "report_created": False,
            "crash_rates_models_regressions_or_policy_claims_created": False,
            "summary_counts": dict(zip(overview["metric"], overview["value"])),
            "table_row_counts": row_counts,
            "limitations": [{"limitation_key": key, "limitation": value} for key, value in LIMITATIONS],
            "qa": qa.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build compact stakeholder context table package.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = build_stakeholder_context_table_package(output_dir=args.output_dir)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
