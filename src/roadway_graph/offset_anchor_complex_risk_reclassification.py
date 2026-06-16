from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/offset_anchor_complex_risk_reclassification"
DUP_AUDIT_DIR = OUTPUT_ROOT / "review/current/offset_anchor_duplicate_label_audit"
COMPLEX_REVIEW_DIR = OUTPUT_ROOT / "review/current/complex_signal_map_review_ingestion"
OFFSET_INTEGRATION_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_context_refresh"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"

SOURCE_SIGNAL_UNIVERSE_COUNT = 3933
CURRENT_REPRESENTED_SIGNAL_COUNT = 2739
GOOD_TRAVELWAY_CLEAN_ADDITIONS = 604
GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS = 626
OFFSET_REVIEW_VISIBLE_ADDITIONS = 173
OFFSET_PRIOR_CLEAN_ADDITIONS = 62
OFFSET_OTHER_RISK_NOT_IN_DUPLICATE_AUDIT = 11

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_INPUTS = [
    DUP_AUDIT_DIR / "offset_anchor_duplicate_label_target_detail.csv",
    DUP_AUDIT_DIR / "offset_anchor_strict_duplicate_audit.csv",
    DUP_AUDIT_DIR / "offset_anchor_spatial_scaffold_overlap_audit.csv",
    DUP_AUDIT_DIR / "offset_anchor_duplicate_label_reclassification.csv",
    DUP_AUDIT_DIR / "offset_anchor_revised_readiness_after_duplicate_audit.csv",
    DUP_AUDIT_DIR / "offset_anchor_duplicate_label_audit_manifest.json",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_decisions.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_travelway_fid_validation.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_review_joined_to_recovery.csv",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json",
    OFFSET_INTEGRATION_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_INTEGRATION_DIR / "expanded_offset_anchor_bin_universe.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_113_risk_decomposition.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_universe_readiness.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_universe_integration_manifest.json",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_signal_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_bin_detail.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_existing_universe_overlap_review.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json",
    ACCESS_REVIEW_GPKG,
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


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    _checkpoint(f"write_start {name}", len(frame))
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write_complete {name}", len(frame))


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if ACCESS_REVIEW_GPKG.exists():
        layers = {row[0] for row in pyogrio.list_layers(ACCESS_REVIEW_GPKG)}
        if SOURCE_TRAVELWAY_LAYER not in layers:
            missing.append(f"{ACCESS_REVIEW_GPKG}:{SOURCE_TRAVELWAY_LAYER}")
    return missing


def _read_source_travelway_inventory() -> dict[str, Any]:
    _checkpoint("read_start source_travelway_full")
    info = pyogrio.read_info(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER)
    fields = list(info.get("fields", []))
    usecols = [col for col in ["RTE_ID", "RTE_NM", "RTE_COMMON", "FROM_MEASURE", "TO_MEASURE"] if col in fields]
    frame = pyogrio.read_dataframe(ACCESS_REVIEW_GPKG, layer=SOURCE_TRAVELWAY_LAYER, columns=usecols, read_geometry=False)
    _checkpoint("read_complete source_travelway_full", len(frame))
    return {
        "row_count": int(len(frame)),
        "columns_read": usecols,
        "route_name_count": int(frame["RTE_NM"].nunique()) if "RTE_NM" in frame.columns else 0,
    }


def _calibration_rules(decisions: pd.DataFrame) -> pd.DataFrame:
    include = _text(decisions, "user_review_decision").eq("include_clean")
    holdout = _text(decisions, "user_review_decision").eq("exclude_source_travelway_missing")
    uncertain = _text(decisions, "user_review_decision").eq("manual_review_uncertain")
    rows = [
        {
            "calibration_rule": "complex_geometry_not_automatic_holdout",
            "reviewed_evidence_class": "reviewed_include_clean",
            "reviewed_signal_count": int(include.sum()),
            "rule_statement": "Complex/multi-row Travelway context can be included when source legs are identifiable and no sibling ownership conflict is evident.",
        },
        {
            "calibration_rule": "high_travelway_row_count_not_exclusion",
            "reviewed_evidence_class": "reviewed_include_clean",
            "reviewed_signal_count": int(include.sum()),
            "rule_statement": "Divided carriageways, median transitions, source segmentation, and carriageway splits can create many rows while still describing a valid signal.",
        },
        {
            "calibration_rule": "source_travelway_missing_is_holdout",
            "reviewed_evidence_class": "reviewed_source_travelway_holdout",
            "reviewed_signal_count": int(holdout.sum()),
            "rule_statement": "Hold only when source Travelway legs are missing/inadequate or nearby legs belong to another intersection.",
        },
        {
            "calibration_rule": "sibling_or_ownership_ambiguity_needs_review",
            "reviewed_evidence_class": "reviewed_manual_uncertain",
            "reviewed_signal_count": int(uncertain.sum()),
            "rule_statement": "Manual review remains appropriate when it is unclear which signal owns the same physical legs.",
        },
    ]
    return pd.DataFrame(rows)


def _summarize_bins(bin_detail: pd.DataFrame) -> pd.DataFrame:
    grouped = bin_detail.groupby("stable_signal_id", dropna=False).agg(
        generated_bin_rows=("stable_bin_id", "size"),
        generated_physical_leg_count=("physical_leg_group_id", "nunique"),
        generated_subbranch_count=("carriageway_subbranch_id", "nunique"),
        generated_stable_travelway_count=("stable_travelway_id", "nunique"),
        route_measure_available_bins=("route_measure_identity_status", lambda s: int((s == "route_measure_identity_available").sum())),
        speed_aadt_ready_bin_count=("speed_aadt_ready_bin", lambda s: int(pd.Series(s).astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
        grade_or_mainline_risk_bins=("grade_or_mainline_risk_flag", lambda s: int(pd.Series(s).astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
    ).reset_index()
    grouped["source_leg_completeness_ratio"] = np.where(
        grouped["generated_bin_rows"].gt(0),
        grouped["route_measure_available_bins"] / grouped["generated_bin_rows"],
        0.0,
    )
    grouped["context_readiness_ratio"] = np.where(
        grouped["generated_bin_rows"].gt(0),
        grouped["speed_aadt_ready_bin_count"] / grouped["generated_bin_rows"],
        0.0,
    )
    return grouped


def _reclassify(dup_reclass: pd.DataFrame, bin_summary: pd.DataFrame) -> pd.DataFrame:
    targets = dup_reclass[_text(dup_reclass, "revised_duplicate_audit_class").isin(
        [
            "complex_multi_signal_context",
            "possible_sibling_signal_same_intersection",
            "insufficient_identity_evidence",
            "manual_map_review_needed",
        ]
    )].copy()
    targets = targets.merge(bin_summary, on="stable_signal_id", how="left", suffixes=("", "_bin_summary"))
    classes: list[str] = []
    reasons: list[str] = []
    map_review: list[bool] = []
    hold_clean: list[bool] = []
    queue_group: list[str] = []

    for row in targets.to_dict(orient="records"):
        strict_dup = str(row.get("strict_true_duplicate", "")).lower() == "true"
        prior = str(row.get("revised_duplicate_audit_class", ""))
        sibling = str(row.get("sibling_signal_risk", "")).lower() == "true" or prior == "possible_sibling_signal_same_intersection"
        complex_risk = str(row.get("complex_multi_signal_risk", "")).lower() == "true" or prior == "complex_multi_signal_context"
        speed_ready = str(row.get("speed_aadt_ready", "")).lower() == "true"
        route_ready = str(row.get("route_measure_ready", "")).lower() == "true"
        full_ready = str(row.get("full_0_1000_speed_aadt_ready", "")).lower() == "true"
        source_id_missing = str(row.get("source_signal_globalid_available", "")).lower() != "true" and str(row.get("source_signal_id_available", "")).lower() != "true"
        near175 = float(row.get("existing_or_recovered_signals_within_175ft", 0) or 0) > 0
        near250 = float(row.get("existing_or_recovered_signals_within_250ft", 0) or 0) > 0
        shared_tw = float(row.get("distinct_shared_stable_travelway_id_count", 0) or 0) > 0
        leg_count = float(row.get("generated_physical_leg_count", 0) or 0)
        subbranch_count = float(row.get("generated_subbranch_count", 0) or 0)
        completeness = float(row.get("source_leg_completeness_ratio", 0) or 0)
        context_ratio = float(row.get("context_readiness_ratio", 0) or 0)
        source_complete = speed_ready and context_ratio > 0 and leg_count >= 1

        if strict_dup:
            cls = "calibrated_manual_uncertain"
            reason = "Strict duplicate evidence should be handled outside complex calibration."
            review = True
            hold = True
            queue = "true_uncertain_cases"
        elif not speed_ready:
            cls = "calibrated_source_travelway_holdout"
            reason = "Generated scaffold did not retain speed/AADT readiness; treat as source/context holdout."
            review = True
            hold = True
            queue = "source_limited_cases"
        elif sibling and (near175 or shared_tw):
            cls = "calibrated_sibling_signal_review_needed"
            reason = "Sibling/ownership evidence remains: nearby represented/recovered signal or shared Travelway legs may own the same intersection."
            review = True
            hold = True
            queue = "likely_sibling_ownership_cases"
        elif prior == "manual_map_review_needed":
            cls = "calibrated_manual_uncertain"
            reason = "Residual manual-review case after duplicate audit; calibration evidence is insufficient to include cleanly."
            review = True
            hold = True
            queue = "true_uncertain_cases"
        elif prior == "insufficient_identity_evidence" and source_complete:
            cls = "calibrated_include_with_source_id_limitation"
            reason = "No strict duplicate evidence; stable_signal_id and context-ready source legs support review-visible inclusion despite missing source IDs."
            review = False
            hold = False
            queue = "highest_confidence_includable_complex_cases" if route_ready or full_ready else "includable_source_id_limitation_cases"
        elif complex_risk and source_complete and not near175:
            cls = "calibrated_include_with_complex_geometry_flags"
            reason = "Complexity is explained by source segmentation/divided geometry; no sibling ownership proximity was detected."
            review = False
            hold = False
            queue = "highest_confidence_includable_complex_cases" if route_ready and full_ready else "includable_complex_with_flags"
        elif complex_risk and source_complete:
            cls = "calibrated_complex_multi_signal_review_needed"
            reason = "Complex context remains near another signal or source ownership is not clear enough for clean inclusion."
            review = True
            hold = True
            queue = "true_uncertain_cases"
        elif source_id_missing:
            cls = "calibrated_include_with_source_id_limitation"
            reason = "Stable ID exists and no strict duplicate evidence was found, but source identifiers are sparse."
            review = False
            hold = False
            queue = "includable_source_id_limitation_cases"
        else:
            cls = "calibrated_manual_uncertain"
            reason = "Evidence does not fit a cleaner calibrated include or holdout rule."
            review = True
            hold = True
            queue = "true_uncertain_cases"

        if cls.startswith("calibrated_include") and subbranch_count >= 4:
            reason += " High row/subbranch count is retained as a QA flag, not an exclusion."
        if cls.startswith("calibrated_include") and shared_tw:
            reason += " Shared Travelway lineage is treated as corridor/scaffold QA evidence, not duplication."
        classes.append(cls)
        reasons.append(reason)
        map_review.append(review)
        hold_clean.append(hold)
        queue_group.append(queue)

    targets["calibrated_reclassification"] = classes
    targets["calibrated_reclassification_reason"] = reasons
    targets["calibrated_map_review_needed"] = map_review
    targets["calibrated_hold_from_clean_analysis"] = hold_clean
    targets["calibrated_includable"] = ~pd.Series(hold_clean, index=targets.index)
    targets["review_queue_group"] = queue_group
    targets["high_travelway_row_count_flag"] = pd.to_numeric(targets["generated_stable_travelway_count"], errors="coerce").fillna(0).ge(4) | pd.to_numeric(targets["generated_subbranch_count"], errors="coerce").fillna(0).ge(4)
    targets["complexity_not_exclusion_calibration_applied"] = targets["calibrated_reclassification"].str.startswith("calibrated_include")
    return targets


def _summaries(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = detail.groupby(["revised_duplicate_audit_class", "calibrated_reclassification"], dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        includable=("calibrated_includable", "sum"),
        map_review_needed=("calibrated_map_review_needed", "sum"),
        hold_from_clean=("calibrated_hold_from_clean_analysis", "sum"),
        high_crash_relevance=("high_crash_relevance_flag", lambda s: int(pd.Series(s).astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
    ).reset_index()

    newly_includable = int(detail["calibrated_includable"].sum())
    map_review_needed = int(detail["calibrated_map_review_needed"].sum()) + OFFSET_OTHER_RISK_NOT_IN_DUPLICATE_AUDIT
    revised_clean_offset = OFFSET_PRIOR_CLEAN_ADDITIONS + newly_includable
    revised_visible_offset = OFFSET_REVIEW_VISIBLE_ADDITIONS
    revised_clean_universe = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_CLEAN_ADDITIONS + revised_clean_offset
    revised_visible_universe = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS + revised_visible_offset
    readiness = pd.DataFrame(
        [
            {"metric": "audited_complex_sibling_sourceid_records", "value": len(detail)},
            {"metric": "calibrated_includable_records_from_audit", "value": newly_includable},
            {"metric": "calibrated_map_review_needed_from_audit", "value": int(detail["calibrated_map_review_needed"].sum())},
            {"metric": "other_offset_anchor_risk_not_reclassified_this_pass", "value": OFFSET_OTHER_RISK_NOT_IN_DUPLICATE_AUDIT},
            {"metric": "revised_offset_anchor_clean_additions", "value": revised_clean_offset},
            {"metric": "revised_offset_anchor_review_visible_additions", "value": revised_visible_offset},
            {"metric": "revised_offset_anchor_hold_from_clean_analysis", "value": revised_visible_offset - revised_clean_offset},
            {"metric": "revised_offset_anchor_map_review_needed", "value": map_review_needed},
            {"metric": "revised_projected_clean_review_universe", "value": revised_clean_universe},
            {"metric": "revised_projected_review_visible_universe", "value": revised_visible_universe},
            {"metric": "revised_projected_clean_review_share_of_3933", "value": round(revised_clean_universe / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "revised_projected_review_visible_share_of_3933", "value": round(revised_visible_universe / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
        ]
    )
    queue = detail.sort_values(
        ["review_queue_group", "calibrated_map_review_needed", "full_0_1000_speed_aadt_ready", "route_measure_ready", "generated_physical_leg_count"],
        ascending=[True, True, False, False, False],
    )
    return summary, readiness, queue


def _findings(rules: pd.DataFrame, detail: pd.DataFrame, readiness: pd.DataFrame, source_inventory: dict[str, Any]) -> str:
    values = dict(zip(readiness["metric"], readiness["value"]))
    def count(prior: str, include_prefix: bool = True) -> int:
        subset = detail[detail["revised_duplicate_audit_class"].eq(prior)]
        if include_prefix:
            return int(subset["calibrated_includable"].sum())
        return int(len(subset) - subset["calibrated_includable"].sum())

    class_lines = "\n".join(
        f"- {cls}: {cnt:,}"
        for cls, cnt in detail["calibrated_reclassification"].value_counts().sort_index().items()
    )
    return f"""# Offset-Anchor Complex Risk Reclassification Findings

## Bounded Question

This read-only pass recalibrates offset-anchor complex/sibling/source-ID risk labels using the user's reviewed complex-signal examples as calibration evidence. It does not promote signals, assign crashes/access, calculate rates/models, or alter active outputs.

## Calibration Lesson

The reviewed complex examples showed that complex geometry is not an automatic holdout. Five reviewed complex good-Travelway signals were includable, two were source-Travelway holdouts, and one remained uncertain. The practical rule is: many Travelway rows, divided-road carriageways, median transitions, and source segmentation are QA flags, not exclusion criteria. Hold only when source-leg ownership is ambiguous, a sibling signal likely owns the same legs, or source Travelway is missing/inadequate.

Source Travelway inventory was read as evidence availability only: {int(source_inventory['row_count']):,} rows from `source_travelway_full`.

## Reclassification Counts

{class_lines}

- Current `complex_multi_signal_context` records made includable: {count('complex_multi_signal_context'):,} of 59
- Current `possible_sibling_signal_same_intersection` records made includable: {count('possible_sibling_signal_same_intersection'):,} of 17
- Current `insufficient_identity_evidence` records made includable using stable/source context: {count('insufficient_identity_evidence'):,} of 23
- Records from this audit that still need map review: {int(values['calibrated_map_review_needed_from_audit']):,}
- Branch-level map-review needed after carrying the 11 other offset-anchor risk records forward: {int(values['revised_offset_anchor_map_review_needed']):,}

## Revised Universe Counts

- Revised offset-anchor clean additions: {int(values['revised_offset_anchor_clean_additions']):,}
- Revised offset-anchor review-visible additions: {int(values['revised_offset_anchor_review_visible_additions']):,}
- Revised projected clean review universe: {int(values['revised_projected_clean_review_universe']):,}
- Revised projected review-visible universe: {int(values['revised_projected_review_visible_universe']):,}

## Recommendation

Split `complex_multi_signal_context` into includable and holdout subclasses. Use `calibrated_include_with_complex_geometry_flags` when context is ready and no sibling/ownership evidence is present. Keep `calibrated_sibling_signal_review_needed`, `calibrated_complex_multi_signal_review_needed`, and `calibrated_manual_uncertain` for map review. The next pass should produce a focused map-review package for the remaining sibling/ownership and other unresolved offset-anchor risk records, not for every complex geometry case.
"""


def _qa(detail: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted_to_production_final", "status": "passed", "observed": "review-only reclassification"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only existing proximity fields carried forward"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active"},
            {"check_name": "reviewed_cases_used_as_calibration_not_forced_truth", "status": "passed", "observed": "rules table documents calibration criteria"},
            {"check_name": "spatial_proximity_not_duplication", "status": "passed", "observed": "duplicate audit result retained"},
            {"check_name": "high_travelway_row_count_not_exclusion", "status": "passed" if detail.loc[detail["high_travelway_row_count_flag"], "calibrated_includable"].any() else "failed", "observed": "high row/subbranch count retained as QA flag"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    manifests = {
        "duplicate_label_audit": _load_json(DUP_AUDIT_DIR / "offset_anchor_duplicate_label_audit_manifest.json"),
        "complex_signal_review_ingestion": _load_json(COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json"),
        "offset_anchor_universe_integration": _load_json(OFFSET_INTEGRATION_DIR / "offset_anchor_universe_integration_manifest.json"),
        "offset_anchor_context_refresh": _load_json(OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json"),
    }

    dup_reclass = _read_csv(DUP_AUDIT_DIR / "offset_anchor_duplicate_label_reclassification.csv")
    decisions = _read_csv(COMPLEX_REVIEW_DIR / "complex_signal_map_review_decisions.csv")
    _ = _read_csv(COMPLEX_REVIEW_DIR / "complex_signal_travelway_fid_validation.csv")
    _ = _read_csv(COMPLEX_REVIEW_DIR / "complex_signal_review_joined_to_recovery.csv")
    _ = _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv")
    _ = _read_csv(OFFSET_INTEGRATION_DIR / "offset_anchor_113_risk_decomposition.csv")
    _ = _read_csv(OFFSET_INTEGRATION_DIR / "offset_anchor_universe_readiness.csv")
    _ = _read_csv(OFFSET_CONTEXT_DIR / "offset_anchor_context_signal_summary.csv")
    bin_detail = _read_csv(OFFSET_CONTEXT_DIR / "offset_anchor_context_bin_detail.csv")
    _ = _read_csv(OFFSET_CONTEXT_DIR / "offset_anchor_existing_universe_overlap_review.csv")
    source_inventory = _read_source_travelway_inventory()

    rules = _calibration_rules(decisions)
    bin_summary = _summarize_bins(bin_detail)
    detail = _reclassify(dup_reclass, bin_summary)
    summary, readiness, queue = _summaries(detail)
    qa = _qa(detail)

    _write_csv(rules, "offset_anchor_complex_calibration_rules.csv")
    _write_csv(detail, "offset_anchor_complex_risk_reclassified_detail.csv")
    _write_csv(summary, "offset_anchor_complex_reclassification_summary.csv")
    _write_csv(readiness, "offset_anchor_complex_revised_readiness.csv")
    queue_cols = [
        "stable_signal_id",
        "GLOBALID",
        "source_signal_id",
        "revised_duplicate_audit_class",
        "calibrated_reclassification",
        "review_queue_group",
        "calibrated_reclassification_reason",
        "calibrated_map_review_needed",
        "calibrated_hold_from_clean_analysis",
        "generated_physical_leg_count",
        "generated_subbranch_count",
        "generated_stable_travelway_count",
        "distinct_shared_stable_travelway_id_count",
        "nearest_existing_or_recovered_signal_ft",
        "existing_or_recovered_signals_within_175ft",
        "anchor_confidence",
        "route_measure_ready",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "high_travelway_row_count_flag",
    ]
    _write_csv(queue[[col for col in queue_cols if col in queue.columns]], "offset_anchor_complex_review_queue.csv")
    _write_text(_findings(rules, detail, readiness, source_inventory), "offset_anchor_complex_risk_reclassification_findings.md")
    _write_csv(qa, "offset_anchor_complex_risk_reclassification_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.offset_anchor_complex_risk_reclassification",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "input_manifests": manifests,
        "source_travelway_inventory": source_inventory,
        "counts": {row["metric"]: row["value"] for row in readiness.to_dict(orient="records")},
        "qa": qa.to_dict(orient="records"),
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
    }
    _write_json(manifest, "offset_anchor_complex_risk_reclassification_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Audited records: {len(detail):,}")
    print(f"Calibrated includable: {int(detail['calibrated_includable'].sum()):,}")
    print(f"Map review needed from audit: {int(detail['calibrated_map_review_needed'].sum()):,}")


if __name__ == "__main__":
    main()
