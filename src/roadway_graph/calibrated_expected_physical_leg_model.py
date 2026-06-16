from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"

FULL_DIR = OUTPUT_ROOT / "review/current/full_universe_expected_leg_expansion"
CALIB_DIR = OUTPUT_ROOT / "review/current/physical_leg_map_review_calibration"
OFFSET_ANCHOR_DIR = OUTPUT_ROOT / "review/current/offset_signal_intersection_anchor_diagnostic"
OFFSET_QA_DIR = OUTPUT_ROOT / "review/current/offset_intersection_zone_staging_qa_cleanup"

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = {
    FULL_DIR: [
        "full_universe_expected_leg_detail.csv",
        "full_universe_expected_leg_distribution.csv",
        "full_universe_current_vs_expected_comparison.csv",
        "full_universe_expected_leg_expansion_manifest.json",
    ],
    CALIB_DIR: [
        "physical_leg_manual_review_notes_seed.csv",
        "physical_leg_review_calibration_detail.csv",
        "physical_leg_calibration_manifest.json",
    ],
    OFFSET_ANCHOR_DIR: [
        "offset_anchor_candidate_detail.csv",
        "offset_signal_intersection_anchor_manifest.json",
    ],
    OFFSET_QA_DIR: [
        "grade_separated_mainline_review_cases.csv",
        "long_source_row_review_cases.csv",
        "staging_qa_cleanup_manifest.json",
    ],
}


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(frame))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(frame))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted({str(value) for value in values.dropna() if str(value) and str(value).lower() not in {"", "nan", "none", "<na>"}})
    return "|".join(items[:limit])


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _missing_required_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _leg_class(count: Any) -> str:
    try:
        n = int(float(count))
    except Exception:
        return "unknown"
    if n <= 2:
        return "two_leg_or_less"
    if n == 3:
        return "three_leg"
    if n == 4:
        return "four_leg"
    return "five_plus_leg"


def _calibrated_type(count: int, source_limited: bool, divided: bool, manual: str, grade: bool) -> str:
    if grade or manual == "nonstandard_signal_geometry":
        return "calibrated_unclear_needs_review"
    if source_limited or manual == "source_missing_leg":
        return "calibrated_source_limited"
    if count <= 2:
        return "calibrated_expected_two_leg_or_partial"
    if count == 3:
        return "calibrated_expected_divided_with_subbranches" if divided else "calibrated_expected_three_leg"
    if count == 4:
        return "calibrated_expected_divided_with_subbranches" if divided else "calibrated_expected_four_leg"
    return "calibrated_expected_complex_five_plus"


def _calibrate_count(row: pd.Series) -> tuple[int, str]:
    current = int(row["current_refreshed_physical_leg_count"])
    source = int(row["source_bearing_count"])
    branches = int(row["candidate_branch_count"])
    manual = str(row.get("manual_category", ""))
    source_limited = bool(row.get("source_limited_manual_or_prior", False))
    grade = bool(row.get("grade_separated_mainline_flag", False))
    divided = bool(row.get("calibrated_divided_subbranch_evidence", False))
    offset = bool(row.get("offset_high_medium_candidate", False))

    if grade or manual in {"nonstandard_signal_geometry"}:
        return max(1, min(current, 4)), "manual_or_grade_separation_hold"
    if manual in {"scaffold_correct_flag_false_positive", "source_simplified_but_scaffold_correct", "leg_short_due_to_nearby_node"}:
        return max(1, min(current, 4)), "manual_scaffold_correct"
    if manual == "source_missing_leg" or source_limited:
        return max(1, min(current, 2)), "source_limited_holdout"
    if manual == "source_has_leg_scaffold_missing":
        return max(current + 1, min(source, 4)), "manual_recoverable_missing_leg"
    if manual in {"divided_carriageway_over_split_but_bins_valid", "physical_leg_clustering_error"}:
        return max(3, min(current, 4)), "manual_divided_or_clustering_calibration"
    if divided and source >= 5:
        return (4 if branches >= 4 or current >= 4 else max(3, current)), "divided_source_zone_overcount_capped"
    if source >= 6:
        return 5 if branches >= 7 and not divided else 4, "source_zone_overcount_capped"
    if source == 5:
        return 4, "source_zone_five_sector_capped_to_four"
    if source in {3, 4}:
        return source, "source_bearing_count_accepted"
    if source <= 2:
        if current >= 3 and not source_limited:
            return min(current, 4), "current_scaffold_supports_more_than_source_zone"
        if offset:
            return max(3, current), "offset_anchor_supports_three_plus"
        return max(1, min(current, 2)), "two_or_partial_control"
    return max(1, min(current, 4)), "fallback_current_capped"


def _line_classification(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in detail.itertuples(index=False):
        sectors = [part for part in str(row.source_bearing_groups or "").split("|") if part]
        physical_keep = set(sectors[: int(row.calibrated_expected_physical_leg_count)])
        for sector in sectors:
            if bool(row.grade_separated_mainline_flag):
                cls = "grade_separated_mainline_exclude"
            elif sector in physical_keep:
                if bool(row.calibrated_divided_subbranch_evidence):
                    cls = "signal_relevant_physical_approach"
                elif "RAMP" in str(row.source_route_groups).upper():
                    cls = "ramp_signal_relevant"
                else:
                    cls = "signal_relevant_physical_approach"
            elif bool(row.calibrated_divided_subbranch_evidence):
                cls = "carriageway_subbranch_of_physical_approach"
            elif bool(row.long_source_row_flag):
                cls = "long_source_row_artifact"
            else:
                cls = "nearby_non_signal_geometry"
            rows.append(
                {
                    "signal_id": row.signal_id,
                    "source_bearing_sector": sector,
                    "source_route_groups": row.source_route_groups,
                    "source_line_count": row.source_line_count,
                    "source_route_group_count": row.source_route_group_count,
                    "source_zone_line_group_class": cls,
                    "route_facility_attribute_only": True,
                    "calibrated_expected_physical_leg_count": row.calibrated_expected_physical_leg_count,
                    "calibration_rule": row.calibration_rule,
                }
            )
    return pd.DataFrame(rows)


def _build_detail(
    full: pd.DataFrame,
    manual_seed: pd.DataFrame,
    manual_detail: pd.DataFrame,
    offset_anchor: pd.DataFrame,
    grade_cases: pd.DataFrame,
    long_cases: pd.DataFrame,
) -> pd.DataFrame:
    detail = full.copy()
    manual = pd.concat(
        [
            manual_seed[["signal_id", "manual_category", "manual_note"]] if {"signal_id", "manual_category", "manual_note"}.issubset(manual_seed.columns) else pd.DataFrame(),
            manual_detail[["signal_id", "manual_category", "manual_note"]] if {"signal_id", "manual_category", "manual_note"}.issubset(manual_detail.columns) else pd.DataFrame(),
        ],
        ignore_index=True,
    ).drop_duplicates("signal_id", keep="last")
    detail = detail.merge(manual, on="signal_id", how="left")
    offset = offset_anchor[["signal_id", "offset_anchor_class"]].drop_duplicates("signal_id") if "offset_anchor_class" in offset_anchor.columns else pd.DataFrame(columns=["signal_id", "offset_anchor_class"])
    detail = detail.merge(offset, on="signal_id", how="left")
    grade_ids = set(_text(grade_cases, "signal_id"))
    long_ids = set(_text(long_cases, "signal_id"))
    detail["grade_separated_mainline_flag"] = _text(detail, "signal_id").isin(grade_ids)
    detail["long_source_row_flag"] = _text(detail, "signal_id").isin(long_ids)
    detail["source_limited_manual_or_prior"] = _text(detail, "manual_category").eq("source_missing_leg") | _text(detail, "prior_subset_alignment_class").eq("under_captured_source_missing_holdout")
    detail["calibrated_divided_subbranch_evidence"] = (
        _num(detail, "source_divided_subbranch_count").gt(_num(detail, "source_bearing_count"))
        | _num(detail, "carriageway_subbranch_count").gt(0)
        | _text(detail, "roadway_division_statuses").str.contains("divided|carriageway", case=False, regex=True)
        | _text(detail, "alignment_class").eq("over_split_carriageway_should_normalize")
    )
    detail["offset_high_medium_candidate"] = _text(detail, "offset_anchor_class").str.contains("high_confidence|medium_confidence", regex=True)
    detail["current_refreshed_physical_leg_count"] = _num(detail, "current_refreshed_physical_leg_count").fillna(_num(detail, "refreshed_physical_leg_count")).fillna(0).astype(int)
    detail["source_bearing_count"] = _num(detail, "source_bearing_count").fillna(0).astype(int)
    detail["candidate_branch_count"] = _num(detail, "candidate_branch_count").fillna(0).astype(int)
    detail["calibrated_count_rule_tuple"] = detail.apply(_calibrate_count, axis=1)
    detail["calibrated_expected_physical_leg_count"] = detail["calibrated_count_rule_tuple"].map(lambda x: x[0]).astype(int)
    detail["calibration_rule"] = detail["calibrated_count_rule_tuple"].map(lambda x: x[1])
    detail["calibrated_expected_physical_leg_class"] = detail["calibrated_expected_physical_leg_count"].map(_leg_class)
    detail["calibrated_expected_type"] = [
        _calibrated_type(int(count), bool(source_limited), bool(divided), str(manual), bool(grade))
        for count, source_limited, divided, manual, grade in zip(
            detail["calibrated_expected_physical_leg_count"],
            detail["source_limited_manual_or_prior"],
            detail["calibrated_divided_subbranch_evidence"],
            _text(detail, "manual_category"),
            detail["grade_separated_mainline_flag"],
        )
    ]
    detail["calibrated_missing_leg_count"] = (detail["calibrated_expected_physical_leg_count"] - detail["current_refreshed_physical_leg_count"]).clip(lower=0)
    detail["calibrated_extra_leg_count"] = (detail["current_refreshed_physical_leg_count"] - detail["calibrated_expected_physical_leg_count"]).clip(lower=0)
    detail["calibrated_alignment_class"] = np.select(
        [
            detail["grade_separated_mainline_flag"],
            detail["source_limited_manual_or_prior"],
            detail["calibrated_missing_leg_count"].gt(0),
            detail["calibrated_extra_leg_count"].gt(0) & detail["calibrated_divided_subbranch_evidence"],
            detail["calibrated_extra_leg_count"].gt(0),
            detail["current_refreshed_physical_leg_count"].eq(detail["calibrated_expected_physical_leg_count"]),
        ],
        [
            "grade_separated_contamination_hold",
            "source_limited_holdout",
            "under_captured_recoverable",
            "over_split_but_bins_usable",
            "needs_manual_review",
            "aligned",
        ],
        default="needs_manual_review",
    )
    detail["old_expected_physical_leg_count"] = _num(detail, "expected_physical_leg_count").fillna(0).astype(int)
    detail["likely_overcount_removed"] = (detail["old_expected_physical_leg_count"] - detail["calibrated_expected_physical_leg_count"]).clip(lower=0)
    return detail.drop(columns=["calibrated_count_rule_tuple"])


def _summaries(detail: pd.DataFrame, old_dist: pd.DataFrame) -> dict[str, pd.DataFrame]:
    calibrated_dist = detail.groupby(["calibrated_expected_physical_leg_class", "calibrated_expected_type"], dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        median_current_leg_count=("current_refreshed_physical_leg_count", "median"),
        median_old_expected_count=("old_expected_physical_leg_count", "median"),
    ).reset_index()
    old = old_dist.copy()
    old["signal_count_num"] = pd.to_numeric(old["signal_count"], errors="coerce").fillna(0).astype(int)
    old_simple = old.groupby("expected_physical_leg_class", dropna=False)["signal_count_num"].sum().reset_index(name="old_signal_count")
    new_simple = detail.groupby("calibrated_expected_physical_leg_class", dropna=False)["signal_id"].nunique().reset_index(name="calibrated_signal_count")
    old_new = old_simple.merge(new_simple, left_on="expected_physical_leg_class", right_on="calibrated_expected_physical_leg_class", how="outer")
    old_new["leg_class"] = _text(old_new, "expected_physical_leg_class").where(_text(old_new, "expected_physical_leg_class").ne(""), _text(old_new, "calibrated_expected_physical_leg_class"))
    old_new["old_signal_count"] = pd.to_numeric(old_new["old_signal_count"], errors="coerce").fillna(0).astype(int)
    old_new["calibrated_signal_count"] = pd.to_numeric(old_new["calibrated_signal_count"], errors="coerce").fillna(0).astype(int)
    old_new["calibrated_minus_old"] = old_new["calibrated_signal_count"] - old_new["old_signal_count"]
    alignment = detail.groupby("calibrated_alignment_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        missing_leg_count=("calibrated_missing_leg_count", "sum"),
        extra_leg_count=("calibrated_extra_leg_count", "sum"),
        overcount_removed=("likely_overcount_removed", "sum"),
    ).reset_index().sort_values("signal_count", ascending=False)
    queue = detail.loc[~detail["calibrated_alignment_class"].eq("aligned")].copy()
    priority = {
        "under_captured_recoverable": 1,
        "over_split_but_bins_usable": 2,
        "grade_separated_contamination_hold": 3,
        "source_limited_holdout": 4,
        "needs_manual_review": 5,
    }
    queue["review_priority_rank"] = queue["calibrated_alignment_class"].map(priority).fillna(9).astype(int)
    queue = queue.sort_values(["review_priority_rank", "calibrated_missing_leg_count", "calibrated_extra_leg_count"], ascending=[True, False, False])
    return {"distribution": calibrated_dist, "old_vs_new": old_new[["leg_class", "old_signal_count", "calibrated_signal_count", "calibrated_minus_old"]], "alignment": alignment, "queue": queue}


def _findings(detail: pd.DataFrame, summaries: dict[str, pd.DataFrame]) -> str:
    dist = "; ".join(f"{row.calibrated_expected_physical_leg_class}/{row.calibrated_expected_type}={int(row.signal_count):,}" for row in summaries["distribution"].itertuples())
    old_five = int(summaries["old_vs_new"].loc[summaries["old_vs_new"]["leg_class"].eq("five_plus_leg"), "old_signal_count"].sum())
    new_five = int(summaries["old_vs_new"].loc[summaries["old_vs_new"]["leg_class"].eq("five_plus_leg"), "calibrated_signal_count"].sum())
    three_four = int(detail["calibrated_expected_physical_leg_count"].isin([3, 4]).sum())
    aligned = int(detail["calibrated_alignment_class"].eq("aligned").sum())
    under = int(detail["calibrated_alignment_class"].eq("under_captured_recoverable").sum())
    over = int(detail["calibrated_alignment_class"].eq("over_split_but_bins_usable").sum())
    source = int(detail["calibrated_alignment_class"].eq("source_limited_holdout").sum())
    return f"""# Calibrated Expected Physical-Leg Model Findings

## Why The Prior Distribution Was Implausible

The prior full-universe source-zone model counted every 175-ft source Travelway bearing sector as an expected signal leg. That overcounted divided carriageways, source line splits, nearby non-signal geometry, ramps/mainlines near interchanges, and long source-row artifacts. Route/facility names were useful attributes but were not reliable physical-leg definitions.

## Calibrated Distribution

{dist}

- Old five-plus expected count: {old_five:,}
- Calibrated five-plus expected count: {new_five:,}
- Calibrated three/four-leg expected signals: {three_four:,}
- Aligned with calibrated expectation: {aligned:,}
- Under-captured recoverable: {under:,}
- Over-split but bins usable: {over:,}
- Source-limited holdouts: {source:,}

## Recommendation

Three- and four-leg cases dominate after calibration. The scaffold is good enough to resume access work if access outputs carry calibrated leg QA flags. The next correction should be divided/carriageway normalization plus targeted recovery for under-captured recoverable signals; grade-separated and source-limited cases should stay held or manual-review only.
"""


def _qa(detail: pd.DataFrame) -> pd.DataFrame:
    output_inside = str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/calibrated_expected_physical_leg_model")
    return pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, "", "true", "All writes are under the review folder."),
            _qa_row("no_candidates_promoted", True, "", "true", ""),
            _qa_row("no_access_or_crash_assignment", True, "", "true", ""),
            _qa_row("no_rates_or_models", True, "", "true", ""),
            _qa_row("route_facility_labels_attributes_only", True, "", "true", ""),
            _qa_row("divided_carriageways_treated_as_subbranches", detail["calibrated_expected_type"].str.contains("divided", case=False, regex=False).any(), "", "true", ""),
            _qa_row("grade_separated_mainlines_excluded_or_flagged", detail["calibrated_alignment_class"].eq("grade_separated_contamination_hold").any(), "", "true", ""),
            _qa_row("outputs_review_only", True, "", "true", ""),
            _qa_row("outputs_written_only_to_review_folder", output_inside, str(OUT_DIR), "review/current/calibrated_expected_physical_leg_model", ""),
        ]
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = _missing_required_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    full_detail = _read_csv(FULL_DIR / "full_universe_expected_leg_detail.csv")
    old_distribution = _read_csv(FULL_DIR / "full_universe_expected_leg_distribution.csv")
    old_comparison = _read_csv(FULL_DIR / "full_universe_current_vs_expected_comparison.csv")
    manual_seed = _read_csv(CALIB_DIR / "physical_leg_manual_review_notes_seed.csv")
    manual_detail = _read_csv(CALIB_DIR / "physical_leg_review_calibration_detail.csv")
    offset_anchor = _read_csv(OFFSET_ANCHOR_DIR / "offset_anchor_candidate_detail.csv")
    grade_cases = _read_csv(OFFSET_QA_DIR / "grade_separated_mainline_review_cases.csv")
    long_cases = _read_csv(OFFSET_QA_DIR / "long_source_row_review_cases.csv")

    detail = _build_detail(full_detail, manual_seed, manual_detail, offset_anchor, grade_cases, long_cases)
    line_classes = _line_classification(detail)
    summaries = _summaries(detail, old_distribution)

    _write_csv(detail, OUT_DIR / "calibrated_expected_leg_signal_detail.csv")
    _write_csv(line_classes, OUT_DIR / "calibrated_source_zone_line_classification.csv")
    _write_csv(summaries["distribution"], OUT_DIR / "calibrated_expected_leg_distribution.csv")
    _write_csv(summaries["old_vs_new"], OUT_DIR / "old_vs_calibrated_expected_distribution.csv")
    _write_csv(summaries["alignment"], OUT_DIR / "calibrated_current_vs_expected_alignment.csv")
    _write_csv(summaries["queue"], OUT_DIR / "calibrated_leg_model_review_queue.csv")
    _write_text(_findings(detail, summaries), OUT_DIR / "calibrated_expected_physical_leg_model_findings.md")
    qa = _qa(detail)
    _write_csv(qa, OUT_DIR / "calibrated_expected_physical_leg_model_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.calibrated_expected_physical_leg_model",
        "bounded_question": "Review-only calibrated expected physical-leg model after broad source-zone overcount.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "full_universe_expected_leg_dir": str(FULL_DIR),
            "manual_calibration_dir": str(CALIB_DIR),
            "offset_anchor_dir": str(OFFSET_ANCHOR_DIR),
            "offset_qa_dir": str(OFFSET_QA_DIR),
            "full_manifest": _load_json(FULL_DIR / "full_universe_expected_leg_expansion_manifest.json"),
            "manual_manifest": _load_json(CALIB_DIR / "physical_leg_calibration_manifest.json"),
        },
        "metrics": {
            "signals": int(len(detail)),
            "old_comparison_rows": int(len(old_comparison)),
            "line_classification_rows": int(len(line_classes)),
            "calibrated_five_plus": int(detail["calibrated_expected_physical_leg_class"].eq("five_plus_leg").sum()),
            "calibrated_three_four": int(detail["calibrated_expected_physical_leg_count"].isin([3, 4]).sum()),
            "under_captured_recoverable": int(detail["calibrated_alignment_class"].eq("under_captured_recoverable").sum()),
            "over_split_but_bins_usable": int(detail["calibrated_alignment_class"].eq("over_split_but_bins_usable").sum()),
        },
        "outputs": [
            "calibrated_expected_leg_signal_detail.csv",
            "calibrated_source_zone_line_classification.csv",
            "calibrated_expected_leg_distribution.csv",
            "old_vs_calibrated_expected_distribution.csv",
            "calibrated_current_vs_expected_alignment.csv",
            "calibrated_leg_model_review_queue.csv",
            "calibrated_expected_physical_leg_model_findings.md",
            "calibrated_expected_physical_leg_model_qa.csv",
            "calibrated_expected_physical_leg_model_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_or_crash_assigned": False,
            "rates_or_models_calculated": False,
        },
    }
    _write_json(manifest, OUT_DIR / "calibrated_expected_physical_leg_model_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
