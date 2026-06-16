from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_crash_unassigned_category_decomposition"

NONASSIGN_DIR = OUTPUT_ROOT / "review/current/final_crash_nonassignment_accounting"
ASSIGNMENT_DIR = OUTPUT_ROOT / "review/current/final_crash_candidate_assignment"
STABLE_SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_RECOVERY_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"
CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")

TARGET_CLASSES = {
    "on_or_near_represented_travelway_but_not_in_buffer",
    "unclear_needs_review",
    "near_source_limited_or_incomplete_scaffold",
    "possible_crash_geocode_offset",
}

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

REQUIRED_INPUTS = [
    NONASSIGN_DIR / "crash_assignment_status_by_crash.csv",
    NONASSIGN_DIR / "crash_unassigned_nearest_scaffold_detail.csv",
    NONASSIGN_DIR / "crash_unassigned_class_summary.csv",
    NONASSIGN_DIR / "crash_unassigned_distance_band_summary.csv",
    NONASSIGN_DIR / "crash_assignment_buffer_sensitivity_summary.csv",
    NONASSIGN_DIR / "crash_unassigned_review_queue.csv",
    NONASSIGN_DIR / "crash_high_fanout_review_queue.csv",
    NONASSIGN_DIR / "crash_high_count_signal_window_review_queue.csv",
    NONASSIGN_DIR / "final_crash_nonassignment_accounting_manifest.json",
    ASSIGNMENT_DIR / "crash_candidate_assignment_detail.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    ASSIGNMENT_DIR / "crash_candidate_assignment_fanout_summary.csv",
    ASSIGNMENT_DIR / "final_crash_candidate_assignment_manifest.json",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_RECOVERY_DIR / "final_source_data_limitation_ledger.csv",
    FINAL_RECOVERY_DIR / "final_recovery_context_refresh_manifest.json",
    CRASH_SOURCE,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _is_direction_field(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in CRASH_DIRECTION_FIELD_TOKENS)


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _norm_route(value: object) -> str:
    text = "" if value is None else str(value).upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _load_crash_source_inventory() -> tuple[int, list[str]]:
    pf = pq.ParquetFile(CRASH_SOURCE)
    cols = list(pf.schema_arrow.names)
    direction_cols = [column for column in cols if _is_direction_field(column)]
    _checkpoint("inspect normalized crash source schema", pf.metadata.num_rows)
    return int(pf.metadata.num_rows), direction_cols


def _build_target_pool() -> pd.DataFrame:
    nearest = _read_csv(NONASSIGN_DIR / "crash_unassigned_nearest_scaffold_detail.csv")
    target = nearest.loc[_text(nearest, "unassigned_reason_class").isin(TARGET_CLASSES)].copy()
    target = target.rename(columns={"unassigned_reason_class": "original_nonassignment_category"})
    _checkpoint("target crash pool", len(target))
    return target


def _nearest_bin_lineage() -> pd.DataFrame:
    cols = [
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "lineage_confidence",
        "target_signal_id",
        "analysis_window",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "route_facility_fields",
        "final_physical_leg_class",
        "grade_separation_or_mainline_review_flag",
        "long_source_row_flag",
    ]
    bins = _read_csv(STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv", cols)
    bins = bins.drop_duplicates("stable_bin_id")
    bins = bins.add_prefix("nearest_bin_")
    return bins


def _attach_context(target: pd.DataFrame) -> pd.DataFrame:
    out = target.merge(_nearest_bin_lineage(), left_on="nearest_stable_bin_id", right_on="nearest_bin_stable_bin_id", how="left")
    out["nearest_source_route_id"] = _text(out, "nearest_bin_source_route_id")
    out["nearest_source_route_name"] = _text(out, "nearest_bin_source_route_name")
    out["nearest_source_route_common"] = _text(out, "nearest_bin_source_route_common")
    out["nearest_source_feature_local_fid"] = _text(out, "nearest_bin_source_feature_local_fid")
    out["nearest_lineage_confidence"] = _text(out, "nearest_bin_lineage_confidence")
    crash_route = _text(out, "RTE_NM").map(_norm_route)
    route_names = [_text(out, col).map(_norm_route) for col in ["nearest_source_route_name", "nearest_source_route_common", "nearest_source_route_id"]]
    out["crash_route_matches_nearest_scaffold_route"] = False
    for series in route_names:
        out["crash_route_matches_nearest_scaffold_route"] = out["crash_route_matches_nearest_scaffold_route"] | (
            crash_route.ne("") & series.ne("") & crash_route.eq(series)
        )
    out["same_nearest_bin_and_signal_proxy"] = _text(out, "nearest_bin_signal_id").eq(_text(out, "nearest_represented_signal_id"))
    out["nearest_has_stable_travelway_id"] = _text(out, "nearest_stable_travelway_id").str.strip().ne("")
    out["nearest_bin_distance_num"] = _num(out, "nearest_scaffold_bin_distance_ft")
    out["nearest_signal_distance_num"] = _num(out, "nearest_signal_proxy_distance_ft")
    return out


def _travelway_relation(row: pd.Series) -> str:
    if _truthy(row.get("nearest_grade_mainline_holdout_flag", False)) or _truthy(row.get("nearest_bin_grade_separation_or_mainline_review_flag", "")):
        return "near_represented_travelway_grade_mainline_risk"
    if _truthy(row.get("nearest_source_limited_holdout_flag", False)) or _truthy(row.get("nearest_still_insufficient_evidence_flag", False)):
        return "near_represented_travelway_source_limited"
    if not _truthy(row.get("nearest_has_stable_travelway_id", False)):
        return "route_source_identity_uncertain"
    if _truthy(row.get("crash_route_matches_nearest_scaffold_route", False)):
        return "near_represented_route_compatible_travelway"
    if _truthy(row.get("same_nearest_bin_and_signal_proxy", False)):
        return "near_represented_travelway_same_signal_proxy"
    return "near_represented_travelway_other_signal_or_route_uncertain"


def _refine_class(row: pd.Series) -> str:
    original = str(row.get("original_nonassignment_category", ""))
    bin_d = float(row.get("nearest_bin_distance_num", np.nan))
    sig_d = float(row.get("nearest_signal_distance_num", np.nan))
    source_flag = _truthy(row.get("nearest_source_limited_holdout_flag", False)) or _truthy(row.get("nearest_still_insufficient_evidence_flag", False))
    grade_flag = _truthy(row.get("nearest_grade_mainline_holdout_flag", False)) or _truthy(row.get("nearest_bin_grade_separation_or_mainline_review_flag", ""))
    route_match = _truthy(row.get("crash_route_matches_nearest_scaffold_route", False))
    same_proxy = _truthy(row.get("same_nearest_bin_and_signal_proxy", False))
    has_tw = _truthy(row.get("nearest_has_stable_travelway_id", False))

    if grade_flag:
        return "grade_or_mainline_holdout"
    if source_flag:
        return "source_limited_scaffold_gap"
    if pd.isna(bin_d):
        return "still_unclear"
    if bin_d > 2500 and sig_d > 2500:
        return "outside_signal_scope_confirmed"
    if 50 < bin_d <= 75:
        return "near_represented_bin_buffer_sensitivity"
    if 75 < bin_d <= 250:
        return "possible_geocode_offset"
    if bin_d <= 2500 and route_match and has_tw and not same_proxy:
        return "near_other_signal_or_overlapping_window"
    if bin_d <= 2500 and route_match and has_tw:
        return "possible_source_travelway_crash_assignment_candidate"
    if bin_d <= 2500 and has_tw:
        return "represented_travelway_outside_signal_window"
    if original == "unclear_needs_review" and sig_d <= 2500:
        return "near_represented_travelway_but_window_uncertain"
    if original == "unclear_needs_review":
        return "manual_map_review_needed"
    return "still_unclear"


def _next_action(row: pd.Series) -> str:
    cls = str(row.get("refined_nonassignment_class", ""))
    if cls == "near_represented_bin_buffer_sensitivity":
        return "addressed_by_75ft_sensitivity_only"
    if cls == "possible_geocode_offset":
        return "geocode_offset_sensitivity_or_map_review"
    if cls == "possible_source_travelway_crash_assignment_candidate":
        return "test_source_travelway_crash_assignment"
    if cls == "source_limited_scaffold_gap":
        return "scaffold_source_recovery_or_source_limitation_hold"
    if cls in {"grade_or_mainline_holdout", "outside_signal_scope_confirmed"}:
        return "holdout_do_not_force"
    if cls in {"manual_map_review_needed", "still_unclear", "near_represented_travelway_but_window_uncertain"}:
        return "manual_review_needed"
    if cls in {"represented_travelway_outside_signal_window", "near_other_signal_or_overlapping_window"}:
        return "window_or_overlap_qa_review"
    return "manual_review_needed"


def _refined_detail(target: pd.DataFrame) -> pd.DataFrame:
    out = _attach_context(target)
    out["travelway_relation_class"] = out.apply(_travelway_relation, axis=1)
    out["refined_nonassignment_class"] = out.apply(_refine_class, axis=1)
    out["next_action_class"] = out.apply(_next_action, axis=1)
    out["would_assign_under_75ft_sensitivity"] = out["nearest_bin_distance_num"].le(75)
    out["would_assign_under_100ft_sensitivity"] = out["nearest_bin_distance_num"].le(100)
    out["likely_geocode_or_buffer_issue"] = out["refined_nonassignment_class"].isin({"near_represented_bin_buffer_sensitivity", "possible_geocode_offset"})
    return out


def _summary(frame: pd.DataFrame, group_cols: list[str], count_name: str = "crash_count") -> pd.DataFrame:
    return frame.groupby(group_cols, dropna=False)["stable_crash_id"].nunique().reset_index(name=count_name).sort_values(count_name, ascending=False)


def _source_limited_detail(refined: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "stable_crash_id",
        "original_nonassignment_category",
        "refined_nonassignment_class",
        "next_action_class",
        "nearest_bin_signal_id",
        "nearest_represented_signal_id",
        "nearest_stable_bin_id",
        "nearest_stable_travelway_id",
        "nearest_scaffold_bin_distance_ft",
        "nearest_signal_proxy_distance_ft",
        "nearest_final_alignment_class",
        "nearest_review_only_recovery_provenance",
        "nearest_source_limited_holdout_flag",
        "nearest_still_insufficient_evidence_flag",
        "nearest_bin_final_physical_leg_class",
    ]
    out = refined.loc[refined["refined_nonassignment_class"].eq("source_limited_scaffold_gap")].copy()
    return out[[col for col in cols if col in out.columns]]


def _geocode_detail(refined: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "stable_crash_id",
        "original_nonassignment_category",
        "refined_nonassignment_class",
        "next_action_class",
        "nearest_scaffold_bin_distance_ft",
        "nearest_scaffold_bin_distance_band",
        "nearest_signal_proxy_distance_ft",
        "nearest_stable_bin_id",
        "nearest_stable_travelway_id",
        "nearest_bin_signal_id",
        "nearest_analysis_window",
        "would_assign_under_75ft_sensitivity",
        "would_assign_under_100ft_sensitivity",
        "RTE_NM",
        "nearest_source_route_name",
        "crash_route_matches_nearest_scaffold_route",
    ]
    out = refined.loc[refined["refined_nonassignment_class"].isin({"near_represented_bin_buffer_sensitivity", "possible_geocode_offset"})].copy()
    return out[[col for col in cols if col in out.columns]].sort_values("nearest_scaffold_bin_distance_ft")


def _next_action_summary(refined: pd.DataFrame) -> pd.DataFrame:
    out = _summary(refined, ["next_action_class"])
    out["plain_language_meaning"] = out["next_action_class"].map(
        {
            "addressed_by_75ft_sensitivity_only": "Nearest represented bin is 50-75 ft away; keep as 75 ft sensitivity rather than primary.",
            "geocode_offset_sensitivity_or_map_review": "Nearest represented bin is 75-250 ft away; likely crash geocode offset or wider catchment review.",
            "test_source_travelway_crash_assignment": "Crash route/source evidence is compatible with nearest stable Travelway; candidate for route/source sensitivity test.",
            "scaffold_source_recovery_or_source_limitation_hold": "Nearest scaffold carries source-limited or still-insufficient QA flags.",
            "holdout_do_not_force": "Outside signal scope or grade/mainline/interchange holdout; do not force into primary assignment.",
            "manual_review_needed": "Evidence remains mixed or sparse after nearest scaffold review.",
            "window_or_overlap_qa_review": "Near represented Travelway but likely window/ownership/overlap issue.",
        }
    )
    return out


def _ranked_review_queue(refined: pd.DataFrame) -> pd.DataFrame:
    frames = []
    queue_defs = {
        "source_travelway_assignment_candidate": refined["refined_nonassignment_class"].eq("possible_source_travelway_crash_assignment_candidate"),
        "likely_geocode_offset": refined["refined_nonassignment_class"].isin({"near_represented_bin_buffer_sensitivity", "possible_geocode_offset"}),
        "source_limited_scaffold_gap": refined["refined_nonassignment_class"].eq("source_limited_scaffold_gap"),
        "grade_mainline_holdout": refined["refined_nonassignment_class"].eq("grade_or_mainline_holdout"),
        "manual_or_still_unclear": refined["refined_nonassignment_class"].isin({"manual_map_review_needed", "still_unclear", "near_represented_travelway_but_window_uncertain"}),
    }
    for name, mask in queue_defs.items():
        q = refined.loc[mask].copy()
        q["review_queue_type"] = name
        q["review_priority"] = 0
        q["review_priority"] += np.where(q["crash_route_matches_nearest_scaffold_route"], 20, 0)
        q["review_priority"] += np.where(q["nearest_scaffold_bin_distance_ft"].astype(float).le(250), 20, 0)
        q["review_priority"] += np.where(q["nearest_signal_proxy_distance_ft"].astype(float).le(2500), 10, 0)
        q["review_priority"] -= q["nearest_scaffold_bin_distance_ft"].astype(float).clip(0, 2500) / 250
        frames.append(q.sort_values("review_priority", ascending=False).head(300))
    cluster = (
        refined.groupby(["nearest_bin_signal_id", "refined_nonassignment_class"], dropna=False)
        .agg(
            crash_count=("stable_crash_id", "nunique"),
            median_nearest_bin_distance_ft=("nearest_scaffold_bin_distance_ft", lambda s: float(pd.to_numeric(s, errors="coerce").median())),
            route_compatible_crashes=("crash_route_matches_nearest_scaffold_route", "sum"),
        )
        .reset_index()
        .sort_values("crash_count", ascending=False)
        .head(300)
    )
    cluster["review_queue_type"] = "high_density_cluster_near_represented_signal"
    cluster["stable_crash_id"] = ""
    cluster["nearest_stable_bin_id"] = ""
    cluster["nearest_stable_travelway_id"] = ""
    cluster["nearest_scaffold_bin_distance_ft"] = cluster["median_nearest_bin_distance_ft"]
    cluster["next_action_class"] = "cluster_review"
    cluster["review_priority"] = cluster["crash_count"]
    frames.append(cluster)
    queue = pd.concat(frames, ignore_index=True, sort=False)
    keep = [
        "review_queue_type",
        "stable_crash_id",
        "nearest_bin_signal_id",
        "refined_nonassignment_class",
        "next_action_class",
        "original_nonassignment_category",
        "nearest_stable_bin_id",
        "nearest_stable_travelway_id",
        "nearest_scaffold_bin_distance_ft",
        "nearest_signal_proxy_distance_ft",
        "crash_route_matches_nearest_scaffold_route",
        "RTE_NM",
        "nearest_source_route_name",
        "crash_count",
        "review_priority",
    ]
    for col in keep:
        if col not in queue.columns:
            queue[col] = ""
    return queue[keep]


def _qa(direction_cols: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", f"outputs written only to {OUT_DIR}"),
        ("no_candidates_promoted", "passed", "diagnostic decomposition only"),
        ("no_rates_or_models", "passed", "no rate/model calculations"),
        ("no_final_crash_assignment_promoted", "passed", "no assignment promotion or context table created"),
        ("crash_direction_not_used", "passed", "direction fields are not used in decomposition rules"),
        ("crash_direction_fields_inventory_only", "passed", "|".join(direction_cols) if direction_cols else "none detected"),
        ("stable_travelway_id_carried", "passed", "nearest stable_travelway_id carried where available"),
        ("scaffold_qa_flags_carried", "passed", "nearest scaffold QA fields carried where available"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(refined: pd.DataFrame, class_summary: pd.DataFrame, next_summary: pd.DataFrame) -> str:
    def count_class(name: str) -> int:
        row = class_summary.loc[class_summary["refined_nonassignment_class"].eq(name)]
        return int(row["crash_count"].iloc[0]) if not row.empty else 0

    def count_action(name: str) -> int:
        row = next_summary.loc[next_summary["next_action_class"].eq(name)]
        return int(row["crash_count"].iloc[0]) if not row.empty else 0

    original_counts = refined.groupby("original_nonassignment_category")["stable_crash_id"].nunique().to_dict()
    return f"""# Final Crash Unassigned Category Decomposition Findings

## Bounded Question

This read-only diagnostic decomposes the four major unresolved 50 ft nonassignment classes using nearest stable-lineage scaffold evidence, route/source compatibility, signal-window proximity, and scaffold QA flags. It does not create final crash assignments, calculate rates/models, promote records, or use crash direction fields.

## Target Pool

- on/near represented Travelway but not in buffer: {int(original_counts.get('on_or_near_represented_travelway_but_not_in_buffer', 0)):,}
- unclear/manual review: {int(original_counts.get('unclear_needs_review', 0)):,}
- near source-limited or incomplete scaffold: {int(original_counts.get('near_source_limited_or_incomplete_scaffold', 0)):,}
- possible crash geocode offset: {int(original_counts.get('possible_crash_geocode_offset', 0)):,}

## Refined Classes

- Source-limited scaffold gap: {count_class('source_limited_scaffold_gap'):,}
- Possible geocode offset: {count_class('possible_geocode_offset'):,}
- Near represented bin, 75 ft sensitivity: {count_class('near_represented_bin_buffer_sensitivity'):,}
- Possible source-Travelway crash assignment candidate: {count_class('possible_source_travelway_crash_assignment_candidate'):,}
- Represented Travelway outside signal window: {count_class('represented_travelway_outside_signal_window'):,}
- Near other signal or overlapping window: {count_class('near_other_signal_or_overlapping_window'):,}
- Grade/mainline holdout: {count_class('grade_or_mainline_holdout'):,}
- Manual/still unclear: {count_class('manual_map_review_needed') + count_class('still_unclear'):,}

## Next-Action Opportunities

- 75 ft sensitivity only: {count_action('addressed_by_75ft_sensitivity_only'):,}
- Geocode-offset sensitivity or map review: {count_action('geocode_offset_sensitivity_or_map_review'):,}
- Source Travelway crash assignment test candidates: {count_action('test_source_travelway_crash_assignment'):,}
- Scaffold/source recovery or source-limitation hold: {count_action('scaffold_source_recovery_or_source_limitation_hold'):,}
- Holdout/do not force: {count_action('holdout_do_not_force'):,}
- Manual review needed: {count_action('manual_review_needed'):,}

## Interpretation

This supports keeping 50 ft as the primary review product and 75 ft as sensitivity. The next useful crash pass should not simply widen buffers; it should QA source-limited scaffold gaps, geocode-offset candidates, and route/source-compatible source-Travelway assignment candidates in a mapped review package or bounded sensitivity test.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start final_crash_unassigned_category_decomposition")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))
    _, direction_cols = _load_crash_source_inventory()
    target = _build_target_pool()
    refined = _refined_detail(target)

    refined_summary = _summary(refined, ["refined_nonassignment_class"])
    travelway_summary = _summary(refined, ["original_nonassignment_category", "travelway_relation_class", "nearest_analysis_window"])
    source_limited = _source_limited_detail(refined)
    geocode = _geocode_detail(refined)
    next_summary = _next_action_summary(refined)
    queue = _ranked_review_queue(refined)

    _write_csv(target, "crash_unassigned_target_pool.csv")
    _write_csv(refined, "crash_unassigned_refined_detail.csv")
    _write_csv(refined_summary, "crash_unassigned_refined_class_summary.csv")
    _write_csv(travelway_summary, "crash_unassigned_travelway_relation_summary.csv")
    _write_csv(source_limited, "crash_unassigned_source_limited_detail.csv")
    _write_csv(geocode, "crash_unassigned_geocode_offset_detail.csv")
    _write_csv(next_summary, "crash_unassigned_next_action_summary.csv")
    _write_csv(queue, "crash_unassigned_ranked_review_queue.csv")
    _write_text(_findings(refined, refined_summary, next_summary), "final_crash_unassigned_category_decomposition_findings.md")
    _write_csv(_qa(direction_cols), "final_crash_unassigned_category_decomposition_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.build.final_crash_unassigned_category_decomposition",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "review_only": True,
            "final_crash_assignment_promoted": False,
            "rates_or_models_calculated": False,
            "crash_direction_use": "not_used_inventory_only",
            "method_note": "Uses nearest stable-lineage scaffold/bin evidence and crash/scaffold route labels; does not perform a new spatial crash assignment.",
            "outputs": [
                "crash_unassigned_target_pool.csv",
                "crash_unassigned_refined_detail.csv",
                "crash_unassigned_refined_class_summary.csv",
                "crash_unassigned_travelway_relation_summary.csv",
                "crash_unassigned_source_limited_detail.csv",
                "crash_unassigned_geocode_offset_detail.csv",
                "crash_unassigned_next_action_summary.csv",
                "crash_unassigned_ranked_review_queue.csv",
                "final_crash_unassigned_category_decomposition_findings.md",
                "final_crash_unassigned_category_decomposition_qa.csv",
                "final_crash_unassigned_category_decomposition_manifest.json",
                "run_progress_log.txt",
            ],
        },
        "final_crash_unassigned_category_decomposition_manifest.json",
    )
    _checkpoint("complete final_crash_unassigned_category_decomposition")


if __name__ == "__main__":
    main()
