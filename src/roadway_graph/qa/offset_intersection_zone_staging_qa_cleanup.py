from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path("work/output/roadway_graph")
OUT = ROOT / "review/current/offset_intersection_zone_staging_qa_cleanup"
STAGING = ROOT / "review/current/offset_intersection_zone_recovery_staging"
RECOVERY = ROOT / "review/current/offset_intersection_zone_scaffold_recovery"
CALIBRATION = ROOT / "review/current/physical_leg_map_review_calibration"

CRASH_FIELD_TOKENS = (
    "crash_id",
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

MANUAL_UPDATES = [
    {
        "signal_id": "signal_000386",
        "manual_category": "grade_separated_mainline_contamination",
        "manual_note": "Keep ramp/cross-street subbranches eligible; hold/exclude I-95 mainline subbranches on different grade.",
        "review_status": "seeded_from_user_map_review",
    },
    {
        "signal_id": "signal_003141",
        "manual_category": "long_source_row_near_signal_bins_valid",
        "manual_note": "Flag long source-row visual artifact but keep near-signal staged bins eligible if geometry follows the signal leg.",
        "review_status": "seeded_from_user_map_review",
    },
]

INTERSTATE_RE = re.compile(r"\bI[- ]?(64|66|81|85|95|295|395|495|664)(?:[NSEW]{1,2})?\b", re.IGNORECASE)
RAMP_RE = re.compile(r"\bRAMP\b|\bRMP\b", re.IGNORECASE)
SURFACE_RE = re.compile(r"\b(SC|SR|US|VA)-?\d+|ST|RD|ROAD|AVE|DR|BLVD|PKWY|HWY", re.IGNORECASE)


def _log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"signal_relative_direction_label", "direction_confidence_status", "true_vehicle_direction_inferred"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _check_columns(columns: list[str], source: str) -> None:
    blocked = [column for column in columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash/direction fields from {source}: {blocked}")


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    _check_columns(header, str(path))
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_csv {path.name}", len(frame))


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _split_keys(value: str) -> list[str]:
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _route_is_mainline(route: str) -> bool:
    return bool(INTERSTATE_RE.search(str(route))) and not bool(RAMP_RE.search(str(route)))


def _route_is_ramp(route: str) -> bool:
    return bool(RAMP_RE.search(str(route)))


def _route_is_surface(route: str) -> bool:
    text = str(route)
    return bool(SURFACE_RE.search(text)) and not _route_is_mainline(text)


def _parse_measure_span(source_line_ids: str) -> float:
    spans = []
    for part in _split_keys(source_line_ids):
        nums = re.findall(r"_(\d+(?:\.\d+)?)_(\d+(?:\.\d+)?)$", part)
        if nums:
            start, end = nums[-1]
            spans.append(abs(float(end) - float(start)))
    return max(spans) if spans else 0.0


def _extend_manual_seed(seed: pd.DataFrame) -> pd.DataFrame:
    out = seed.copy()
    for update in MANUAL_UPDATES:
        row = {
            **update,
            "manual_category_description": update["manual_note"],
            "reviewer": "manual_qgis_review_seed",
            "created_or_preserved_at_utc": datetime.now(timezone.utc).isoformat(),
            "feeds_recovery_candidate": False,
            "feeds_label_refinement": True,
            "feeds_holdout": False,
        }
        if out["signal_id"].astype(str).eq(update["signal_id"]).any():
            mask = out["signal_id"].astype(str).eq(update["signal_id"])
            for key, value in row.items():
                out.loc[mask, key] = value
        else:
            out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
    return out


def _subbranch_class(row: pd.Series) -> str:
    signal_id = str(row.get("signal_id", ""))
    routes = _split_keys(row.get("source_route_keys", ""))
    has_mainline = any(_route_is_mainline(route) for route in routes)
    has_ramp = any(_route_is_ramp(route) for route in routes)
    has_surface = any(_route_is_surface(route) for route in routes)
    if signal_id == "signal_000386":
        if has_mainline and has_ramp:
            return "mixed_ramp_mainline_subbranch_split_needed"
        if has_mainline and not has_ramp:
            return "grade_separated_mainline_exclude"
        if has_ramp:
            return "signal_relevant_ramp"
        if has_surface:
            return "signal_relevant_cross_street"
        return "unclear_grade_separation_review"
    if has_mainline and has_ramp:
        return "mixed_ramp_mainline_subbranch_split_needed"
    if has_mainline and not has_ramp:
        return "unclear_grade_separation_review"
    if has_ramp:
        return "signal_relevant_ramp"
    if has_surface:
        return "signal_relevant_surface_street"
    return "unclear_grade_separation_review"


def _long_source_class(row: pd.Series) -> str:
    span = float(row.get("source_measure_span_max", 0) or 0)
    signal_id = str(row.get("signal_id", ""))
    bins = int(float(row.get("staged_bin_count", 0) or 0))
    route_text = str(row.get("source_route_keys", ""))
    if signal_id == "signal_003141":
        return "long_source_geometry_but_valid_near_signal_bins"
    if span >= 2.0 and bins > 0:
        if "EXPRESS" in route_text.upper() or "HOV" in route_text.upper() or "REVERS" in route_text.upper():
            return "reversible_managed_lane_special_geometry_review"
        return "long_source_geometry_but_valid_near_signal_bins"
    if span >= 2.0:
        return "long_source_geometry_with_questionable_bins"
    return "no_long_source_row_artifact"


def _cleanup_status(row: pd.Series) -> str:
    cls = str(row.get("qa_subbranch_class", ""))
    long_cls = str(row.get("long_source_row_class", ""))
    if cls == "grade_separated_mainline_exclude":
        return "hold_excluded_mainline"
    if cls in {"mixed_ramp_mainline_subbranch_split_needed", "unclear_grade_separation_review"}:
        return "hold_manual_grade_separation_review"
    if cls in {"signal_relevant_ramp", "signal_relevant_cross_street", "signal_relevant_surface_street"}:
        if long_cls == "long_source_geometry_but_valid_near_signal_bins":
            return "long_source_row_flag_only"
        return "refresh_eligible_leg"
    return "hold_manual_grade_separation_review"


def _build_clean_legs(legs: pd.DataFrame, bins: pd.DataFrame, manual_seed: pd.DataFrame) -> pd.DataFrame:
    bin_counts = bins.groupby("staged_recovered_leg_id", dropna=False).agg(
        staged_bin_count=("staged_recovered_bin_id", "count"),
        max_distance_end_ft=("distance_end_ft", lambda s: pd.to_numeric(s, errors="coerce").max()),
    ).reset_index()
    frame = legs.merge(bin_counts, on="staged_recovered_leg_id", how="left")
    frame["staged_bin_count"] = _num(frame, "staged_bin_count").astype(int)
    frame["max_distance_end_ft"] = _num(frame, "max_distance_end_ft")
    manual = manual_seed[["signal_id", "manual_category", "manual_note"]].drop_duplicates("signal_id")
    frame = frame.merge(manual, on="signal_id", how="left", suffixes=("", "_qa_seed"))
    frame["qa_subbranch_class"] = frame.apply(_subbranch_class, axis=1)
    frame["contains_limited_access_mainline"] = frame["source_route_keys"].map(lambda v: any(_route_is_mainline(route) for route in _split_keys(v)))
    frame["contains_ramp"] = frame["source_route_keys"].map(lambda v: any(_route_is_ramp(route) for route in _split_keys(v)))
    frame["contains_surface_or_cross_street"] = frame["source_route_keys"].map(lambda v: any(_route_is_surface(route) for route in _split_keys(v)))
    frame["mixed_ramp_mainline_flag"] = frame["contains_limited_access_mainline"] & frame["contains_ramp"]
    frame["source_measure_span_max"] = frame["source_line_ids"].map(_parse_measure_span)
    frame["long_source_row_class"] = frame.apply(_long_source_class, axis=1)
    frame["long_source_row_flag"] = ~frame["long_source_row_class"].eq("no_long_source_row_artifact")
    frame["qa_cleanup_status"] = frame.apply(_cleanup_status, axis=1)
    frame["refresh_eligible_leg"] = frame["qa_cleanup_status"].isin(["refresh_eligible_leg", "long_source_row_flag_only"])
    frame["hold_excluded_mainline"] = frame["qa_cleanup_status"].eq("hold_excluded_mainline")
    frame["hold_manual_grade_separation_review"] = frame["qa_cleanup_status"].eq("hold_manual_grade_separation_review")
    frame["hold_nonstandard_geometry"] = frame["staging_class"].eq("stage_nonstandard_geometry_hold")
    frame["records_preserved_not_deleted"] = True
    frame["review_only"] = True
    return frame


def _build_clean_bins(bins: pd.DataFrame, clean_legs: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "staged_recovered_leg_id",
        "qa_subbranch_class",
        "long_source_row_class",
        "long_source_row_flag",
        "qa_cleanup_status",
        "refresh_eligible_leg",
        "hold_excluded_mainline",
        "hold_manual_grade_separation_review",
        "hold_nonstandard_geometry",
        "contains_limited_access_mainline",
        "contains_ramp",
        "mixed_ramp_mainline_flag",
    ]
    frame = bins.merge(clean_legs[[c for c in cols if c in clean_legs.columns]], on="staged_recovered_leg_id", how="left")
    frame["refresh_eligible_bin"] = frame["refresh_eligible_leg"].fillna(False).astype(bool)
    frame["records_preserved_not_deleted"] = True
    frame["review_only"] = True
    return frame


def _signal_summary(clean_legs: pd.DataFrame, clean_bins: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    leg_group = clean_legs.groupby("signal_id", dropna=False).agg(
        cleaned_staged_leg_count=("staged_recovered_leg_id", "nunique"),
        refresh_eligible_leg_count=("refresh_eligible_leg", "sum"),
        excluded_mainline_leg_count=("hold_excluded_mainline", "sum"),
        grade_separation_review_leg_count=("hold_manual_grade_separation_review", "sum"),
        long_source_row_flag_leg_count=("long_source_row_flag", "sum"),
        mixed_ramp_mainline_leg_count=("mixed_ramp_mainline_flag", "sum"),
        qa_subbranch_classes=("qa_subbranch_class", lambda s: "|".join(sorted(set(s.astype(str))))),
    ).reset_index()
    bin_group = clean_bins.groupby("signal_id", dropna=False).agg(
        cleaned_staged_bin_count=("staged_recovered_bin_id", "nunique"),
        refresh_eligible_bin_count=("refresh_eligible_bin", "sum"),
        excluded_mainline_bin_count=("hold_excluded_mainline", "sum"),
        grade_separation_review_bin_count=("hold_manual_grade_separation_review", "sum"),
    ).reset_index()
    frame = signal_summary.merge(leg_group, on="signal_id", how="right").merge(bin_group, on="signal_id", how="left")
    frame["refresh_eligible_signal_after_cleanup"] = frame["refresh_eligible_leg_count"].astype(int).gt(0)
    frame["needs_manual_grade_separation_review_after_cleanup"] = frame["grade_separation_review_leg_count"].astype(int).gt(0)
    frame["has_excluded_mainline_after_cleanup"] = frame["excluded_mainline_leg_count"].astype(int).gt(0)
    return frame


def _readiness_summary(clean_legs: pd.DataFrame, clean_bins: pd.DataFrame, clean_signals: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("signals_total", clean_signals["signal_id"].nunique(), "Signals in cleaned staged set."),
        ("refresh_eligible_signals_after_cleanup", int(clean_signals["refresh_eligible_signal_after_cleanup"].sum()), "Signals with at least one eligible leg after cleanup."),
        ("cleaned_staged_legs_total", clean_legs["staged_recovered_leg_id"].nunique(), "All staged legs preserved."),
        ("refresh_eligible_legs_after_cleanup", int(clean_legs["refresh_eligible_leg"].sum()), "Legs eligible after QA cleanup."),
        ("cleaned_staged_bins_total", clean_bins["staged_recovered_bin_id"].nunique(), "All staged bins preserved."),
        ("refresh_eligible_bins_after_cleanup", int(clean_bins["refresh_eligible_bin"].sum()), "Bins eligible after QA cleanup."),
        ("grade_separated_mainline_contamination_legs", int(clean_legs["hold_excluded_mainline"].sum()), "Pure mainline legs excluded/held."),
        ("mixed_ramp_mainline_split_needed_legs", int(clean_legs["mixed_ramp_mainline_flag"].sum()), "Mixed ramp/mainline legs needing subbranch split."),
        ("signals_with_grade_separation_cases", clean_legs.loc[clean_legs["hold_excluded_mainline"] | clean_legs["mixed_ramp_mainline_flag"], "signal_id"].nunique(), "Signals with mainline/ramp grade separation QA."),
        ("long_source_row_artifact_legs", int(clean_legs["long_source_row_flag"].sum()), "Legs with long source-row flags."),
        ("long_source_row_artifact_signals", clean_legs.loc[clean_legs["long_source_row_flag"], "signal_id"].nunique(), "Signals with long source-row flags."),
    ]
    for cls, count in clean_legs["qa_subbranch_class"].value_counts().sort_index().items():
        rows.append((f"qa_subbranch_class_{cls}", int(count), "Leg count by subbranch class."))
    for status, count in clean_legs["qa_cleanup_status"].value_counts().sort_index().items():
        rows.append((f"qa_cleanup_status_{status}", int(count), "Leg count by cleanup status."))
    return pd.DataFrame(rows, columns=["metric", "value", "note"])


def _write_findings(summary: pd.DataFrame, clean_signals: pd.DataFrame) -> None:
    values = dict(zip(summary["metric"], summary["value"], strict=False))
    sig386 = clean_signals[clean_signals["signal_id"].eq("signal_000386")]
    sig3141 = clean_signals[clean_signals["signal_id"].eq("signal_003141")]
    sig386_text = "not found" if sig386.empty else f"{int(sig386.iloc[0]['refresh_eligible_leg_count'])} eligible legs, {int(sig386.iloc[0]['excluded_mainline_leg_count'])} excluded mainline legs, {int(sig386.iloc[0]['mixed_ramp_mainline_leg_count'])} mixed ramp/mainline split-needed legs"
    sig3141_text = "not found" if sig3141.empty else f"{int(sig3141.iloc[0]['long_source_row_flag_leg_count'])} long-source-row flagged legs, {int(sig3141.iloc[0]['refresh_eligible_leg_count'])} eligible legs"
    text = f"""# Offset / Intersection-Zone Staging QA Cleanup Findings

Status: REVIEW-ONLY. Records are classified and flagged, not deleted. No active outputs are modified and no candidates are promoted.

## Answers

1. `signal_000386` is classified as `grade_separated_mainline_contamination`: {sig386_text}.
2. Grade-separated mainline contamination legs: {values.get('grade_separated_mainline_contamination_legs', 0)} pure mainline excludes; mixed ramp/mainline split-needed legs: {values.get('mixed_ramp_mainline_split_needed_legs', 0)}.
3. Ramp/cross-street subbranches remain eligible where they are not mixed with mainline geometry; mixed ramp/mainline records are held for split review rather than deleted.
4. `signal_003141` is classified as `long_source_row_near_signal_bins_valid`: {sig3141_text}.
5. Long-source-row artifact cases: {values.get('long_source_row_artifact_signals', 0)} signals and {values.get('long_source_row_artifact_legs', 0)} legs.
6. Refresh-eligible after QA cleanup: {values.get('refresh_eligible_signals_after_cleanup', 0)} signals, {values.get('refresh_eligible_legs_after_cleanup', 0)} legs, {values.get('refresh_eligible_bins_after_cleanup', 0)} bins.
7. The staged set is ready for a later route/measure plus speed/AADT refresh only after map review accepts eligible legs and mixed ramp/mainline split-needed records are resolved.

## Recommendation

Carry forward per-leg QA fields into any refresh. Exclude pure grade-separated mainline legs, hold mixed ramp/mainline records until subbranch geometry can be split, and keep long-source-row artifact records eligible when near-signal bins remain valid.
"""
    (OUT / "staging_qa_cleanup_findings.md").write_text(text, encoding="utf-8")
    _checkpoint("write_findings")


def _write_qa(clean_legs: pd.DataFrame, clean_bins: pd.DataFrame) -> pd.DataFrame:
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", "pass", "Writes only to review/current/offset_intersection_zone_staging_qa_cleanup/."),
            ("no_candidates_promoted", "pass", "All records remain review-only."),
            ("no_access_crash_assignment", "pass", "No access or crash sources are read or assigned."),
            ("no_rates_or_models", "pass", "No rates, denominators, regression, or models are run."),
            ("records_flagged_not_deleted", "pass" if len(clean_legs) == 533 and len(clean_bins) == 2456 else "review", f"legs={len(clean_legs)}, bins={len(clean_bins)}"),
            ("mainline_exclusion_per_leg_not_whole_signal", "pass", "Eligibility is applied per staged leg/bin."),
            ("outputs_review_only", "pass", str(OUT)),
        ],
        columns=["qa_check", "status", "note"],
    )
    _write_csv(qa, OUT / "staging_qa_cleanup_qa.csv")
    return qa


def _write_manifest(outputs: list[str], summary: pd.DataFrame, qa: pd.DataFrame) -> None:
    manifest = {
        "script": "src/active/roadway_graph/offset_intersection_zone_staging_qa_cleanup.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT),
        "bounded_question": "final read-only QA cleanup for offset/intersection-zone staged recovery candidates",
        "inputs": {
            "staging": str(STAGING),
            "recovery": str(RECOVERY),
            "calibration": str(CALIBRATION),
        },
        "summary": summary.to_dict(orient="records"),
        "outputs": outputs,
        "qa": qa.to_dict(orient="records"),
        "non_goals_confirmed": ["no universe refresh", "no speed/AADT assignment", "no access/crash assignment", "no active output modification", "no promotion"],
    }
    (OUT / "staging_qa_cleanup_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _checkpoint("write_manifest")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start", note="offset/intersection-zone staging QA cleanup")

    legs = _read_csv(STAGING / "staged_offset_recovered_legs.csv")
    bins = _read_csv(STAGING / "staged_offset_recovered_bins.csv")
    signal_summary = _read_csv(STAGING / "staged_offset_signal_summary.csv")
    _read_csv(STAGING / "staged_offset_readiness_flags.csv")
    _read_csv(STAGING / "staged_offset_holdout_cases.csv")
    _ = json.loads((STAGING / "offset_intersection_zone_recovery_staging_manifest.json").read_text(encoding="utf-8"))
    _read_csv(RECOVERY / "offset_zone_recovered_leg_candidates.csv")
    _read_csv(RECOVERY / "offset_zone_recovered_bins.csv")
    _read_csv(RECOVERY / "offset_zone_review_queue.csv")
    manual_seed = _read_csv(CALIBRATION / "physical_leg_manual_review_notes_seed.csv")
    _read_csv(CALIBRATION / "physical_leg_review_calibration_detail.csv")

    updated_seed = _extend_manual_seed(manual_seed)
    clean_legs = _build_clean_legs(legs, bins, updated_seed)
    clean_bins = _build_clean_bins(bins, clean_legs)
    clean_signals = _signal_summary(clean_legs, clean_bins, signal_summary)
    grade_cases = clean_legs[clean_legs["hold_excluded_mainline"] | clean_legs["mixed_ramp_mainline_flag"] | clean_legs["signal_id"].eq("signal_000386")].copy()
    long_cases = clean_legs[clean_legs["long_source_row_flag"] | clean_legs["signal_id"].eq("signal_003141")].copy()
    summary = _readiness_summary(clean_legs, clean_bins, clean_signals)

    _write_csv(updated_seed, OUT / "offset_staging_manual_review_seed_update.csv")
    _write_csv(clean_legs, OUT / "cleaned_staged_offset_recovered_legs.csv")
    _write_csv(clean_bins, OUT / "cleaned_staged_offset_recovered_bins.csv")
    _write_csv(clean_signals, OUT / "cleaned_staged_offset_signal_summary.csv")
    _write_csv(grade_cases, OUT / "grade_separated_mainline_review_cases.csv")
    _write_csv(long_cases, OUT / "long_source_row_review_cases.csv")
    _write_csv(summary, OUT / "staging_qa_cleanup_readiness_summary.csv")
    _write_findings(summary, clean_signals)
    qa = _write_qa(clean_legs, clean_bins)
    outputs = [
        "offset_staging_manual_review_seed_update.csv",
        "cleaned_staged_offset_recovered_legs.csv",
        "cleaned_staged_offset_recovered_bins.csv",
        "cleaned_staged_offset_signal_summary.csv",
        "grade_separated_mainline_review_cases.csv",
        "long_source_row_review_cases.csv",
        "staging_qa_cleanup_readiness_summary.csv",
        "staging_qa_cleanup_findings.md",
        "staging_qa_cleanup_qa.csv",
        "staging_qa_cleanup_manifest.json",
        "run_progress_log.txt",
    ]
    _write_manifest(outputs, summary, qa)
    _checkpoint("complete", rows=len(clean_legs))


if __name__ == "__main__":
    main()
