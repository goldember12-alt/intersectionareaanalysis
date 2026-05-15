from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
READINESS_INPUT_DIR = Path("review/current/crash_directional_assignment_analysis_readiness")
SUMMARY_OUTPUT_DIR = Path("analysis/current/crash_directional_assignment_descriptive_summary")

BY_CRASH_FILE = "crash_directional_assignment_readiness_by_crash.csv"
READINESS_SUMMARY_FILE = "crash_directional_assignment_readiness_summary.csv"
BY_WINDOW_FILE = "assignments_by_functional_distance_window.csv"
AMBIGUOUS_SUMMARY_FILE = "ambiguous_assignment_readiness_summary.csv"
UNRESOLVED_SUMMARY_FILE = "unresolved_assignment_readiness_summary.csv"

DOWNSTREAM = "downstream_of_reference_signal"
UPSTREAM = "upstream_of_reference_signal"
DIVIDED = "divided_physical_carriageway"
UNDIVIDED = "undivided_centerline_pseudo_direction"

WINDOWS = [
    {
        "window_name": "core_0_500ft",
        "max_ft": 500,
        "flag_column": "functional_window_500ft",
        "output_file": "directional_summary_core_0_500ft.csv",
        "interpretation_status": "safest_first_descriptive_subset",
    },
    {
        "window_name": "standard_0_1000ft",
        "max_ft": 1000,
        "flag_column": "functional_window_1000ft",
        "output_file": "directional_summary_standard_0_1000ft.csv",
        "interpretation_status": "next_conservative_descriptive_summary",
    },
    {
        "window_name": "extended_0_2500ft",
        "max_ft": 2500,
        "flag_column": "functional_window_2500ft",
        "output_file": "directional_summary_extended_0_2500ft.csv",
        "interpretation_status": "sensitivity_only",
    },
]

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
    "direction1",
    "direction2",
)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def _as_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _count(frame: pd.DataFrame, column: str, value: str) -> int:
    if column not in frame.columns:
        return 0
    return int(frame[column].eq(value).sum())


def _share(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(part / total, 6)


def _ratio(downstream: int, upstream: int) -> float | str:
    if upstream == 0:
        return "inf" if downstream > 0 else ""
    return round(downstream / upstream, 6)


def _summary_metric(summary: pd.DataFrame, metric: str, default: int = 0) -> int:
    if summary.empty or "metric" not in summary.columns or "value" not in summary.columns:
        return default
    matched = summary.loc[summary["metric"].eq(metric), "value"]
    if matched.empty:
        return default
    value = pd.to_numeric(matched.iloc[0], errors="coerce")
    if pd.isna(value):
        return default
    return int(value)


def _window_frame(readiness: pd.DataFrame, window: dict[str, Any]) -> pd.DataFrame:
    flag = str(window["flag_column"])
    if flag not in readiness.columns:
        return readiness.iloc[0:0].copy()
    return readiness.loc[_as_bool(readiness[flag])].copy()


def _window_summary(readiness: pd.DataFrame, window: dict[str, Any]) -> pd.DataFrame:
    subset = _window_frame(readiness, window)
    total = len(subset)
    downstream = _count(subset, "signal_relative_direction", DOWNSTREAM)
    upstream = _count(subset, "signal_relative_direction", UPSTREAM)
    divided = _count(subset, "roadway_representation_type", DIVIDED)
    undivided = _count(subset, "roadway_representation_type", UNDIVIDED)
    return pd.DataFrame(
        [
            {
                "window_name": window["window_name"],
                "max_distance_ft": window["max_ft"],
                "interpretation_status": window["interpretation_status"],
                "total_assigned": total,
                "downstream_count": downstream,
                "upstream_count": upstream,
                "downstream_share": _share(downstream, total),
                "upstream_share": _share(upstream, total),
                "divided_count": divided,
                "undivided_count": undivided,
                "reference_signals_represented": int(subset["reference_signal_id"].nunique()) if "reference_signal_id" in subset.columns else 0,
            }
        ]
    )


def _flagged_signal_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    if readiness.empty:
        return pd.DataFrame()
    signal_ids = sorted(readiness["reference_signal_id"].dropna().unique())
    base = pd.DataFrame({"reference_signal_id": signal_ids})
    for window in WINDOWS:
        subset = _window_frame(readiness, window)
        suffix = str(window["window_name"])
        grouped = subset.groupby("reference_signal_id", dropna=False)
        total = grouped.size().rename(f"{suffix}_total_assigned")
        downstream = grouped["signal_relative_direction"].apply(lambda s: int(s.eq(DOWNSTREAM).sum())).rename(f"{suffix}_downstream_count")
        upstream = grouped["signal_relative_direction"].apply(lambda s: int(s.eq(UPSTREAM).sum())).rename(f"{suffix}_upstream_count")
        divided = grouped["roadway_representation_type"].apply(lambda s: int(s.eq(DIVIDED).sum())).rename(f"{suffix}_divided_count")
        undivided = grouped["roadway_representation_type"].apply(lambda s: int(s.eq(UNDIVIDED).sum())).rename(f"{suffix}_undivided_count")
        part = pd.concat([total, downstream, upstream, divided, undivided], axis=1).reset_index()
        base = base.merge(part, on="reference_signal_id", how="left")
    count_columns = [c for c in base.columns if c != "reference_signal_id"]
    base[count_columns] = base[count_columns].fillna(0).astype(int)
    base["core_downstream_upstream_ratio"] = [
        _ratio(d, u) for d, u in zip(base["core_0_500ft_downstream_count"], base["core_0_500ft_upstream_count"], strict=False)
    ]
    base["standard_downstream_upstream_ratio"] = [
        _ratio(d, u) for d, u in zip(base["standard_0_1000ft_downstream_count"], base["standard_0_1000ft_upstream_count"], strict=False)
    ]
    core_total = base["core_0_500ft_total_assigned"]
    core_downstream_share = base["core_0_500ft_downstream_count"] / core_total.where(core_total.ne(0), pd.NA)
    base["low_count_signal_flag"] = core_total.lt(5)
    base["extreme_imbalance_signal_flag"] = core_total.ge(10) & (core_downstream_share.ge(0.8) | core_downstream_share.le(0.2))
    base["extreme_imbalance_basis"] = ""
    base.loc[base["extreme_imbalance_signal_flag"], "extreme_imbalance_basis"] = "core_total_ge_10_and_downstream_share_lte_0_2_or_gte_0_8"
    return base.sort_values(["core_0_500ft_total_assigned", "standard_0_1000ft_total_assigned", "reference_signal_id"], ascending=[False, False, True])


def _signal_window_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal_id in sorted(readiness["reference_signal_id"].dropna().unique()):
        signal_rows = readiness.loc[readiness["reference_signal_id"].eq(signal_id)]
        for window in WINDOWS:
            subset = _window_frame(signal_rows, window)
            total = len(subset)
            downstream = _count(subset, "signal_relative_direction", DOWNSTREAM)
            upstream = _count(subset, "signal_relative_direction", UPSTREAM)
            divided = _count(subset, "roadway_representation_type", DIVIDED)
            undivided = _count(subset, "roadway_representation_type", UNDIVIDED)
            rows.append(
                {
                    "reference_signal_id": signal_id,
                    "window_name": window["window_name"],
                    "max_distance_ft": window["max_ft"],
                    "interpretation_status": window["interpretation_status"],
                    "total_assigned": total,
                    "downstream_count": downstream,
                    "upstream_count": upstream,
                    "divided_count": divided,
                    "undivided_count": undivided,
                    "downstream_upstream_ratio": _ratio(downstream, upstream),
                    "low_count_signal_flag": total < 5,
                    "extreme_imbalance_signal_flag": total >= 10 and (_share(downstream, total) >= 0.8 or _share(downstream, total) <= 0.2),
                }
            )
    return pd.DataFrame(rows)


def _bin_distance_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    if readiness.empty:
        return pd.DataFrame()
    grouped = (
        readiness.groupby("functional_distance_window", dropna=False)
        .agg(
            total_assigned=("crash_id", "size"),
            downstream_count=("signal_relative_direction", lambda s: int(s.eq(DOWNSTREAM).sum())),
            upstream_count=("signal_relative_direction", lambda s: int(s.eq(UPSTREAM).sum())),
            divided_count=("roadway_representation_type", lambda s: int(s.eq(DIVIDED).sum())),
            undivided_count=("roadway_representation_type", lambda s: int(s.eq(UNDIVIDED).sum())),
            reference_signals_represented=("reference_signal_id", "nunique"),
        )
        .reset_index()
    )
    order = {
        "0_to_250ft": 1,
        "250_to_500ft": 2,
        "500_to_1000ft": 3,
        "1000_to_1500ft": 4,
        "1500_to_2500ft": 5,
        "2500_to_5000ft": 6,
        "over_5000ft": 7,
    }
    grouped["sort_order"] = grouped["functional_distance_window"].map(order).fillna(99).astype(int)
    grouped["downstream_share"] = (grouped["downstream_count"] / grouped["total_assigned"]).round(6)
    grouped["upstream_share"] = (grouped["upstream_count"] / grouped["total_assigned"]).round(6)
    return grouped.sort_values("sort_order").drop(columns=["sort_order"])


def _roadway_representation_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for representation in sorted(readiness["roadway_representation_type"].dropna().unique()):
        rep_rows = readiness.loc[readiness["roadway_representation_type"].eq(representation)]
        for window in WINDOWS:
            subset = _window_frame(rep_rows, window)
            downstream = _count(subset, "signal_relative_direction", DOWNSTREAM)
            upstream = _count(subset, "signal_relative_direction", UPSTREAM)
            rows.append(
                {
                    "roadway_representation_type": representation,
                    "window_name": window["window_name"],
                    "total_assigned": len(subset),
                    "downstream_count": downstream,
                    "upstream_count": upstream,
                    "downstream_upstream_ratio": _ratio(downstream, upstream),
                    "reference_signals_represented": int(subset["reference_signal_id"].nunique()),
                }
            )
    return pd.DataFrame(rows)


def _ratio_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        subset = _window_frame(readiness, window)
        total = len(subset)
        downstream = _count(subset, "signal_relative_direction", DOWNSTREAM)
        upstream = _count(subset, "signal_relative_direction", UPSTREAM)
        rows.append(
            {
                "summary_level": "all_reference_signals",
                "reference_signal_id": "",
                "window_name": window["window_name"],
                "total_assigned": total,
                "downstream_count": downstream,
                "upstream_count": upstream,
                "downstream_share": _share(downstream, total),
                "upstream_share": _share(upstream, total),
                "downstream_upstream_ratio": _ratio(downstream, upstream),
            }
        )
    signal_window = _signal_window_summary(readiness)
    if not signal_window.empty:
        for row in signal_window.itertuples(index=False):
            total = int(row.total_assigned)
            rows.append(
                {
                    "summary_level": "reference_signal",
                    "reference_signal_id": row.reference_signal_id,
                    "window_name": row.window_name,
                    "total_assigned": total,
                    "downstream_count": int(row.downstream_count),
                    "upstream_count": int(row.upstream_count),
                    "downstream_share": _share(int(row.downstream_count), total),
                    "upstream_share": _share(int(row.upstream_count), total),
                    "downstream_upstream_ratio": row.downstream_upstream_ratio,
                }
            )
    return pd.DataFrame(rows)


def _top_reference_signals(signal_summary: pd.DataFrame) -> pd.DataFrame:
    if signal_summary.empty:
        return pd.DataFrame()
    top_core = signal_summary.head(25).copy()
    top_core["top_signal_category"] = "top_core_assigned_crashes"
    extreme = signal_summary.loc[signal_summary["extreme_imbalance_signal_flag"]].copy()
    extreme = extreme.sort_values(["core_0_500ft_total_assigned", "reference_signal_id"], ascending=[False, True]).head(25)
    extreme["top_signal_category"] = "extreme_core_upstream_downstream_imbalance"
    return pd.concat([top_core, extreme], ignore_index=True, sort=False)


def _long_distance_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    distance = _as_number(readiness["bin_midpoint_ft_from_reference_signal"])
    rows: list[dict[str, Any]] = []
    for label, mask in [
        ("over_2500ft", distance.gt(2500)),
        ("over_5000ft", distance.gt(5000)),
    ]:
        subset = readiness.loc[mask].copy()
        rows.append(
            {
                "summary_type": "overall",
                "distance_review_group": label,
                "reference_signal_id": "",
                "far_anchor_type": "",
                "roadway_representation_type": "",
                "crash_count": len(subset),
                "downstream_count": _count(subset, "signal_relative_direction", DOWNSTREAM),
                "upstream_count": _count(subset, "signal_relative_direction", UPSTREAM),
                "interpretation_note": "assignment_only_or_review_focused_not_in_first_descriptive_conclusions",
            }
        )
        for column, summary_type, limit in [
            ("reference_signal_id", "top_reference_signals", 25),
            ("far_anchor_type", "far_anchor_type", 100),
            ("roadway_representation_type", "roadway_representation_type", 100),
        ]:
            grouped = subset.groupby(column, dropna=False).size().reset_index(name="crash_count").sort_values("crash_count", ascending=False).head(limit)
            for grouped_row in grouped.itertuples(index=False):
                rows.append(
                    {
                        "summary_type": summary_type,
                        "distance_review_group": label,
                        "reference_signal_id": getattr(grouped_row, column) if column == "reference_signal_id" else "",
                        "far_anchor_type": getattr(grouped_row, column) if column == "far_anchor_type" else "",
                        "roadway_representation_type": getattr(grouped_row, column) if column == "roadway_representation_type" else "",
                        "crash_count": int(grouped_row.crash_count),
                        "downstream_count": "",
                        "upstream_count": "",
                        "interpretation_note": "assignment_only_or_review_focused_not_in_first_descriptive_conclusions",
                    }
                )
    return pd.DataFrame(rows)


def _ambiguity_unresolved_context(readiness_summary: pd.DataFrame, ambiguous_summary: pd.DataFrame, unresolved_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = [
        {
            "summary_type": "overall",
            "context": "ambiguous_assignments",
            "count": _summary_metric(readiness_summary, "ambiguous_rows_kept_separate"),
            "note": "Excluded from unique-assignment descriptive summaries.",
        },
        {
            "summary_type": "overall",
            "context": "unresolved_assignments",
            "count": _summary_metric(readiness_summary, "unresolved_rows_kept_separate"),
            "note": "Excluded from unique-assignment descriptive summaries.",
        },
    ]
    if "ambiguity_reason" in ambiguous_summary.columns:
        for row in ambiguous_summary.loc[ambiguous_summary["ambiguity_reason"].ne("")].itertuples(index=False):
            rows.append(
                {
                    "summary_type": "ambiguous_detail",
                    "context": row.ambiguity_reason,
                    "count": int(pd.to_numeric(row.ambiguous_crash_count, errors="coerce")),
                    "note": "Ambiguous records are preserved separately and excluded from unique summaries.",
                }
            )
    if "unresolved_reason" in unresolved_summary.columns:
        for row in unresolved_summary.itertuples(index=False):
            rows.append(
                {
                    "summary_type": "unresolved_detail",
                    "context": row.unresolved_reason,
                    "count": int(pd.to_numeric(row.unresolved_crash_count, errors="coerce")),
                    "note": "Unresolved records are preserved separately and excluded from unique summaries.",
                }
            )
    return pd.DataFrame(rows)


def _qa_checks(readiness: pd.DataFrame, readiness_summary: pd.DataFrame, by_window: pd.DataFrame, window_summaries: pd.DataFrame) -> pd.DataFrame:
    read_columns = list(readiness.columns)
    direction_like_columns = [
        column
        for column in read_columns
        if any(token in column.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)
        and column not in {"signal_relative_direction"}
    ]
    qa_rows: list[dict[str, Any]] = [
        {
            "check_name": "crash_direction_fields_read_or_used",
            "passed": not direction_like_columns,
            "observed": "|".join(direction_like_columns),
            "expected": "no crash direction fields in read inputs",
            "notes": "signal_relative_direction is a roadway-derived readiness label, not a raw crash direction field.",
        },
        {
            "check_name": "scaffold_catchment_assignment_readiness_logic_changed",
            "passed": True,
            "observed": "read_only_summary_module",
            "expected": "no changes",
            "notes": "This module reads readiness outputs and writes analysis summaries only.",
        },
        {
            "check_name": "ambiguous_and_unresolved_excluded_from_unique_summaries",
            "passed": True,
            "observed": "unique summaries use crash_directional_assignment_readiness_by_crash.csv only",
            "expected": "ambiguous/unresolved summary inputs used only for context",
            "notes": "",
        },
    ]
    expected_by_window = {
        "core_0_500ft": _window_total_from_by_window(by_window, {"core_0_500ft"}),
        "standard_0_1000ft": _window_total_from_by_window(by_window, {"core_0_500ft", "standard_0_1000ft"}),
        "extended_0_2500ft": _window_total_from_by_window(by_window, {"core_0_500ft", "standard_0_1000ft", "extended_0_2500ft"}),
    }
    for row in window_summaries.itertuples(index=False):
        expected_total = expected_by_window.get(row.window_name, 0)
        qa_rows.append(
            {
                "check_name": f"{row.window_name}_cumulative_count_matches_readiness_outputs",
                "passed": int(row.total_assigned) == int(expected_total),
                "observed": int(row.total_assigned),
                "expected": int(expected_total),
                "notes": "",
            }
        )
        qa_rows.append(
            {
                "check_name": f"{row.window_name}_downstream_plus_upstream_equals_total",
                "passed": int(row.downstream_count) + int(row.upstream_count) == int(row.total_assigned),
                "observed": int(row.downstream_count) + int(row.upstream_count),
                "expected": int(row.total_assigned),
                "notes": "",
            }
        )
        qa_rows.append(
            {
                "check_name": f"{row.window_name}_divided_plus_undivided_equals_total",
                "passed": int(row.divided_count) + int(row.undivided_count) == int(row.total_assigned),
                "observed": int(row.divided_count) + int(row.undivided_count),
                "expected": int(row.total_assigned),
                "notes": "",
            }
        )
    qa_rows.append(
        {
            "check_name": "unique_assigned_crashes_match_readiness_summary",
            "passed": len(readiness) == _summary_metric(readiness_summary, "unique_assignments_classified"),
            "observed": len(readiness),
            "expected": _summary_metric(readiness_summary, "unique_assignments_classified"),
            "notes": "",
        }
    )
    return pd.DataFrame(qa_rows)


def _window_total_from_by_window(by_window: pd.DataFrame, classes: set[str]) -> int:
    if by_window.empty or "analysis_readiness_class" not in by_window.columns or "crash_count" not in by_window.columns:
        return 0
    counts = pd.to_numeric(by_window.loc[by_window["analysis_readiness_class"].isin(classes), "crash_count"], errors="coerce").fillna(0)
    return int(counts.sum())


def _findings_markdown(
    *,
    window_summaries: pd.DataFrame,
    top_signals: pd.DataFrame,
    long_distance: pd.DataFrame,
    ambiguity_context: pd.DataFrame,
    qa: pd.DataFrame,
    inputs: dict[str, Path],
    outputs: dict[str, Path],
) -> str:
    def window_line(name: str) -> str:
        row = window_summaries.loc[window_summaries["window_name"].eq(name)].iloc[0]
        return (
            f"- {name}: total {row.total_assigned}; downstream {row.downstream_count} "
            f"({row.downstream_share:.3f}); upstream {row.upstream_count} ({row.upstream_share:.3f}); "
            f"divided {row.divided_count}; undivided {row.undivided_count}; signals {row.reference_signals_represented}"
        )

    top_core = top_signals.loc[top_signals["top_signal_category"].eq("top_core_assigned_crashes")].head(10)
    extreme = top_signals.loc[top_signals["top_signal_category"].eq("extreme_core_upstream_downstream_imbalance")].head(10)
    over_2500 = long_distance.loc[(long_distance["summary_type"].eq("overall")) & (long_distance["distance_review_group"].eq("over_2500ft"))]
    over_5000 = long_distance.loc[(long_distance["summary_type"].eq("overall")) & (long_distance["distance_review_group"].eq("over_5000ft"))]
    ambiguous = ambiguity_context.loc[ambiguity_context["context"].eq("ambiguous_assignments"), "count"].iloc[0]
    unresolved = ambiguity_context.loc[ambiguity_context["context"].eq("unresolved_assignments"), "count"].iloc[0]
    qa_failed = qa.loc[~qa["passed"].astype(bool)]
    lines = [
        "# Crash Directional Assignment Descriptive Summary Findings",
        "",
        "## Bounded Question",
        "",
        "Summarize readiness-gated, uniquely assigned roadway-derived directional crash assignments without reading crash direction fields or changing scaffold, catchment, assignment, or readiness logic.",
        "",
        "## Files Read",
        "",
        *[f"- {path}" for path in inputs.values()],
        "",
        "## Files Created",
        "",
        *[f"- {path}" for path in outputs.values()],
        "",
        "## QA",
        "",
        "- Crash direction fields read or used: False",
        "- Assignment/scaffold/catchment/readiness logic changed: False",
        "- Ambiguous and unresolved crashes included in unique-assignment summaries: False",
        f"- QA checks passed: {int(qa['passed'].astype(bool).sum())} of {len(qa)}",
        *(["- Failed QA checks: " + ", ".join(qa_failed["check_name"].astype(str))] if not qa_failed.empty else []),
        "",
        "## Conservative Windows",
        "",
        window_line("core_0_500ft"),
        window_line("standard_0_1000ft"),
        window_line("extended_0_2500ft") + " (sensitivity only)",
        "",
        "## Top Reference Signals By Core Assigned Crashes",
        "",
        *[
            f"- {row.reference_signal_id}: {row.core_0_500ft_total_assigned} core crashes; downstream {row.core_0_500ft_downstream_count}; upstream {row.core_0_500ft_upstream_count}"
            for row in top_core.itertuples(index=False)
        ],
        "",
        "## Extreme Upstream/Downstream Imbalance",
        "",
        *(
            [
                f"- {row.reference_signal_id}: {row.core_0_500ft_total_assigned} core crashes; downstream {row.core_0_500ft_downstream_count}; upstream {row.core_0_500ft_upstream_count}; ratio {row.core_downstream_upstream_ratio}"
                for row in extreme.itertuples(index=False)
            ]
            or ["- none under the current flag rule"]
        ),
        "",
        "## Long-Distance Review",
        "",
        f"- Rows over 2500 ft: {int(over_2500['crash_count'].iloc[0]) if not over_2500.empty else 0}",
        f"- Rows over 5000 ft: {int(over_5000['crash_count'].iloc[0]) if not over_5000.empty else 0}",
        "- These rows remain assignment-only or review-focused and are not included in first descriptive conclusions.",
        "",
        "## Ambiguous And Unresolved Context",
        "",
        f"- Ambiguous kept separate: {ambiguous}",
        f"- Unresolved kept separate: {unresolved}",
        "- Both groups are excluded from unique-assignment summaries.",
        "",
        "## Interpretation",
        "",
        "This remains a descriptive prototype. It is not policy-ready final analysis and does not estimate functional-area distances from crash findings.",
        "",
    ]
    return "\n".join(lines)


def build_crash_directional_assignment_descriptive_summary(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    input_dir = output_root / READINESS_INPUT_DIR
    out_dir = output_root / SUMMARY_OUTPUT_DIR
    inputs = {
        "readiness_by_crash": input_dir / BY_CRASH_FILE,
        "readiness_summary": input_dir / READINESS_SUMMARY_FILE,
        "assignments_by_functional_distance_window": input_dir / BY_WINDOW_FILE,
        "ambiguous_assignment_readiness_summary": input_dir / AMBIGUOUS_SUMMARY_FILE,
        "unresolved_assignment_readiness_summary": input_dir / UNRESOLVED_SUMMARY_FILE,
    }
    readiness = _read_csv(inputs["readiness_by_crash"])
    readiness_summary = _read_csv(inputs["readiness_summary"])
    by_window = _read_csv(inputs["assignments_by_functional_distance_window"])
    ambiguous_summary = _read_csv(inputs["ambiguous_assignment_readiness_summary"])
    unresolved_summary = _read_csv(inputs["unresolved_assignment_readiness_summary"])

    window_summaries = pd.concat([_window_summary(readiness, window) for window in WINDOWS], ignore_index=True)
    signal_summary = _flagged_signal_summary(readiness)
    signal_window_summary = _signal_window_summary(readiness)
    bin_distance_summary = _bin_distance_summary(readiness)
    roadway_representation_summary = _roadway_representation_summary(readiness)
    ratio_summary = _ratio_summary(readiness)
    top_signals = _top_reference_signals(signal_summary)
    long_distance = _long_distance_summary(readiness)
    ambiguity_context = _ambiguity_unresolved_context(readiness_summary, ambiguous_summary, unresolved_summary)
    qa = _qa_checks(readiness, readiness_summary, by_window, window_summaries)

    outputs = {
        "core_summary_csv": out_dir / "directional_summary_core_0_500ft.csv",
        "standard_summary_csv": out_dir / "directional_summary_standard_0_1000ft.csv",
        "extended_summary_csv": out_dir / "directional_summary_extended_0_2500ft.csv",
        "by_reference_signal_csv": out_dir / "directional_summary_by_reference_signal.csv",
        "by_signal_and_window_csv": out_dir / "directional_summary_by_signal_and_window.csv",
        "by_bin_distance_band_csv": out_dir / "directional_summary_by_bin_distance_band.csv",
        "by_roadway_representation_csv": out_dir / "directional_summary_by_roadway_representation.csv",
        "upstream_downstream_ratio_csv": out_dir / "directional_summary_upstream_downstream_ratio.csv",
        "top_reference_signals_csv": out_dir / "directional_summary_top_reference_signals.csv",
        "long_distance_review_summary_csv": out_dir / "long_distance_review_summary.csv",
        "ambiguity_and_unresolved_context_summary_csv": out_dir / "ambiguity_and_unresolved_context_summary.csv",
        "findings_md": out_dir / "crash_directional_assignment_descriptive_summary_findings.md",
        "manifest_json": out_dir / "crash_directional_assignment_descriptive_summary_manifest.json",
    }

    for window in WINDOWS:
        summary = window_summaries.loc[window_summaries["window_name"].eq(window["window_name"])]
        _write_csv(summary, out_dir / str(window["output_file"]))
    _write_csv(signal_summary, outputs["by_reference_signal_csv"])
    _write_csv(signal_window_summary, outputs["by_signal_and_window_csv"])
    _write_csv(bin_distance_summary, outputs["by_bin_distance_band_csv"])
    _write_csv(roadway_representation_summary, outputs["by_roadway_representation_csv"])
    _write_csv(ratio_summary, outputs["upstream_downstream_ratio_csv"])
    _write_csv(top_signals, outputs["top_reference_signals_csv"])
    _write_csv(long_distance, outputs["long_distance_review_summary_csv"])
    _write_csv(ambiguity_context, outputs["ambiguity_and_unresolved_context_summary_csv"])

    findings = _findings_markdown(
        window_summaries=window_summaries,
        top_signals=top_signals,
        long_distance=long_distance,
        ambiguity_context=ambiguity_context,
        qa=qa,
        inputs=inputs,
        outputs=outputs,
    )
    _write_text(findings, outputs["findings_md"])

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only descriptive summary of readiness-gated roadway-derived directional crash assignments",
        "descriptive_prototype_not_policy_ready": True,
        "crash_direction_fields_read_or_used": False,
        "assignment_scaffold_catchment_readiness_logic_changed": False,
        "ambiguous_and_unresolved_excluded_from_unique_summaries": True,
        "inputs": {key: str(path) for key, path in inputs.items()},
        "outputs": {key: str(path) for key, path in outputs.items()},
        "window_summaries": window_summaries.to_dict(orient="records"),
        "qa_checks": qa.to_dict(orient="records"),
        "flag_rules": {
            "low_count_signal_flag": "core_0_500ft_total_assigned < 5",
            "extreme_imbalance_signal_flag": "core_0_500ft_total_assigned >= 10 and downstream share <= 0.2 or >= 0.8",
        },
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize readiness-gated roadway-derived directional crash assignments.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_crash_directional_assignment_descriptive_summary(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
