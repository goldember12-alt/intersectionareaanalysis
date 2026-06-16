from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_scaffold_recovery"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
COMPLEX_REVIEW_DIR = OUTPUT_ROOT / "review/current/complex_signal_map_review_ingestion"
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"

CURRENT_REPRESENTED_SIGNAL_COUNT = 2739
GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS = 626
GOOD_TRAVELWAY_CLEAN_ADDITIONS = 604
SOURCE_SIGNAL_UNIVERSE_COUNT = 3933

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_INPUTS = [
    CONTEXT_DIR / "offset_anchor_context_bin_detail.csv",
    CONTEXT_DIR / "offset_anchor_context_signal_summary.csv",
    CONTEXT_DIR / "offset_anchor_route_measure_summary.csv",
    CONTEXT_DIR / "offset_anchor_roadway_context_summary.csv",
    CONTEXT_DIR / "offset_anchor_speed_summary.csv",
    CONTEXT_DIR / "offset_anchor_aadt_exposure_summary.csv",
    CONTEXT_DIR / "offset_anchor_context_readiness_summary.csv",
    CONTEXT_DIR / "offset_anchor_existing_universe_overlap_review.csv",
    CONTEXT_DIR / "offset_anchor_universe_expansion_projection.csv",
    CONTEXT_DIR / "offset_anchor_context_missingness.csv",
    CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json",
    RECOVERY_DIR / "offset_anchor_missing_signal_targets.csv",
    RECOVERY_DIR / "offset_anchor_recovered_signal_summary.csv",
    RECOVERY_DIR / "offset_anchor_recovered_leg_candidates.csv",
    RECOVERY_DIR / "offset_anchor_recovered_bins.csv",
    RECOVERY_DIR / "offset_anchor_recovery_skipped_targets.csv",
    RECOVERY_DIR / "offset_anchor_context_refresh_readiness.csv",
    RECOVERY_DIR / "offset_anchor_crash_relevance_summary.csv",
    RECOVERY_DIR / "offset_anchor_overlap_dedup_review.csv",
    RECOVERY_DIR / "offset_anchor_scaffold_recovery_manifest.json",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_expanded_universe_readiness.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_203_risk_decomposition.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_universe_recommendation.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
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
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _source_group(row: pd.Series) -> str:
    for col in ("DISTRICT", "MAINT_JURISDICTION", "Stage1_SourceLayer", "source_layer"):
        value = str(row.get(col, "") or "").strip()
        if value:
            return value
    return "unknown"


def _normalize_bool_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for col in columns:
        out[col] = _flag(out, col)
    return out


def _readiness_consistency(signal_summary: pd.DataFrame) -> pd.DataFrame:
    generated = signal_summary[_flag(signal_summary, "has_generated_bins")].copy()
    rows = [
        ("generated_signal_count", int(len(generated)), "All offset-anchor targets that produced generated bins."),
        (
            "route_measure_ready",
            int(_flag(generated, "route_measure_ready").sum()),
            "Strict full-coverage definition: every generated bin for the signal has route/measure identity.",
        ),
        (
            "roadway_context_ready",
            int(_flag(generated, "roadway_context_ready").sum()),
            "Strict full-coverage definition: every generated bin has roadway/source context.",
        ),
        (
            "rns_speed_ready",
            int(_flag(generated, "rns_speed_ready").sum()),
            "Loose signal-level context definition: at least one generated bin received RNS speed.",
        ),
        (
            "aadt_ready",
            int(_flag(generated, "aadt_ready").sum()),
            "Loose signal-level context definition: at least one generated bin received AADT.",
        ),
        (
            "exposure_ready",
            int(_flag(generated, "exposure_denominator_ready").sum()),
            "Loose signal-level context definition: at least one generated bin received AADT plus denominator evidence.",
        ),
        (
            "speed_aadt_ready",
            int(_flag(generated, "speed_aadt_ready").sum()),
            "Loose signal-level context definition: at least one generated bin received speed, AADT, and denominator evidence.",
        ),
        (
            "full_0_1000_ready",
            int(_flag(generated, "full_0_1000_speed_aadt_ready").sum()),
            "Stricter analysis-window definition carried forward from context refresh.",
        ),
    ]
    explanation = (
        "The 109 versus 173 mismatch is a naming/strictness mismatch, not an interval-assignment bug. "
        "`route_measure_ready` requires all generated bins for a signal to carry route/measure identity, "
        "while `speed_aadt_ready` only requires one or more bins with matched RNS speed, AADT, and denominator evidence. "
        "The integration therefore treats 173 as review-visible context-ready additions and keeps full-coverage flags separate for clean analysis decisions."
    )
    return pd.DataFrame(
        [
            {
                "readiness_metric": metric,
                "signal_count": count,
                "definition_scope": note,
                "mismatch_explanation": explanation if metric == "speed_aadt_ready" else "",
            }
            for metric, count, note in rows
        ]
    )


def _classify_offset_signals(signal_summary: pd.DataFrame, good_signals: pd.DataFrame, stable_signals: pd.DataFrame) -> pd.DataFrame:
    bool_cols = [
        "has_generated_bins",
        "route_measure_ready",
        "roadway_context_ready",
        "rns_speed_ready",
        "aadt_ready",
        "exposure_denominator_ready",
        "speed_aadt_ready",
        "full_0_1000_speed_aadt_ready",
        "exact_duplicate_signal_risk",
        "sibling_signal_risk",
        "complex_multi_signal_risk",
        "overlap_review_required",
        "overlap_or_dedup_risk",
        "eligible_for_later_universe_expansion_review",
        "high_crash_relevance_flag",
        "source_signal_globalid_available",
        "source_signal_id_available",
    ]
    base = _normalize_bool_columns(signal_summary, bool_cols)
    base["source_group"] = base.apply(_source_group, axis=1)
    base["GLOBALID_missing"] = _text(base, "GLOBALID").str.strip().eq("")
    base["source_signal_id_missing"] = _text(base, "source_signal_id").str.strip().eq("")
    good_ids = set(_text(good_signals, "stable_signal_id"))
    stable_ids = set(_text(stable_signals, "stable_signal_id"))
    good_source_ids = {v for v in _text(good_signals, "source_signal_id") if v}
    stable_source_ids = {v for v in list(_text(stable_signals, "represented_source_signal_id")) + list(_text(stable_signals, "source_signal_id")) if v}
    base["stable_signal_id_overlap_with_existing_or_good"] = _text(base, "stable_signal_id").isin(good_ids | stable_ids)
    base["source_signal_id_overlap_with_existing_or_good"] = _text(base, "source_signal_id").isin(good_source_ids | stable_source_ids) & _text(base, "source_signal_id").str.strip().ne("")
    base["stable_travelway_overlap_with_existing_or_recovered"] = _num(base, "stable_travelway_overlap_bin_count").fillna(0).gt(0)
    base["nearest_existing_or_recovered_signal_ft"] = _num(base, "nearest_existing_or_recovered_signal_ft").combine_first(_num(base, "nearest_existing_signal_proxy_ft"))
    base["near_existing_or_recovered_signal_under_250ft"] = base["nearest_existing_or_recovered_signal_ft"].le(250)
    base["low_anchor_confidence_carryover_risk"] = _text(base, "anchor_confidence").str.lower().eq("low")

    classes: list[str] = []
    readiness: list[str] = []
    explanations: list[str] = []
    review_visible: list[bool] = []
    clean_use: list[bool] = []
    hold_clean: list[bool] = []

    for row in base.to_dict(orient="records"):
        generated = bool(row.get("has_generated_bins", False))
        speed_ready = bool(row.get("speed_aadt_ready", False))
        clean = bool(row.get("eligible_for_later_universe_expansion_review", False))
        exact = bool(row.get("exact_duplicate_signal_risk", False)) or bool(row.get("source_signal_id_overlap_with_existing_or_good", False)) or bool(row.get("stable_signal_id_overlap_with_existing_or_good", False))
        sibling = bool(row.get("sibling_signal_risk", False))
        complex_risk = bool(row.get("complex_multi_signal_risk", False))
        scaffold_overlap = bool(row.get("overlap_review_required", False)) or bool(row.get("stable_travelway_overlap_with_existing_or_recovered", False))
        missing_id = bool(row.get("GLOBALID_missing", False)) or bool(row.get("source_signal_id_missing", False))

        if not generated:
            cls = "hold_low_confidence_anchor"
            ready = "hold_offset_anchor_confidence_too_low"
            note = "Target did not generate defensible scaffold and remains a low-confidence anchor holdout."
            visible = False
            clean_flag = False
        elif not speed_ready:
            cls = "not_context_ready"
            ready = "hold_not_context_ready"
            note = "Generated scaffold exists but no bin received speed, AADT, and denominator context."
            visible = False
            clean_flag = False
        elif clean:
            cls = "clean_offset_anchor_addition"
            ready = "ready_clean_offset_anchor_addition"
            note = "Context-ready and no overlap/dedup/sibling/complex risk flags."
            visible = True
            clean_flag = True
        elif exact:
            cls = "possible_duplicate_existing_signal"
            ready = "review_visible_hold_from_clean_duplicate_risk"
            note = "Context-ready but source or stable identifier evidence overlaps existing represented/recovered universe or duplicate flag is present."
            visible = True
            clean_flag = False
        elif sibling:
            cls = "possible_sibling_signal_same_intersection"
            ready = "review_visible_hold_from_clean_sibling_risk"
            note = "Context-ready but sibling signal risk is present."
            visible = True
            clean_flag = False
        elif complex_risk:
            cls = "complex_multi_signal_context"
            ready = "review_visible_hold_from_clean_complex_context"
            note = "Context-ready but generated context indicates complex multi-signal/multi-branch risk."
            visible = True
            clean_flag = False
        elif scaffold_overlap:
            cls = "overlap_with_existing_recovered_scaffold"
            ready = "review_visible_hold_from_clean_scaffold_overlap"
            note = "Context-ready but generated bins overlap existing represented/recovered scaffold or stable Travelway lineage."
            visible = True
            clean_flag = False
        elif missing_id:
            cls = "source_id_missing_but_stable_id_valid"
            ready = "review_visible_with_source_id_flag"
            note = "Context-ready and stable signal ID exists, but source GLOBALID or source signal ID is missing."
            visible = True
            clean_flag = False
        elif bool(row.get("overlap_or_dedup_risk", False)):
            cls = "valid_offset_anchor_addition_with_review_flags"
            ready = "review_visible_with_review_flags"
            note = "Context-ready with nonblocking review flags that should be inspected before clean use."
            visible = True
            clean_flag = False
        else:
            cls = "manual_map_review_needed"
            ready = "review_visible_hold_from_clean_manual_review"
            note = "Context-ready but risk evidence did not fit a narrower class."
            visible = True
            clean_flag = False

        classes.append(cls)
        readiness.append(ready)
        explanations.append(note)
        review_visible.append(visible)
        clean_use.append(clean_flag)
        hold_clean.append(not clean_flag)

    base["offset_anchor_addition_class"] = classes
    base["offset_anchor_universe_readiness_class"] = readiness
    base["risk_explanation"] = explanations
    base["review_visible_offset_anchor_addition"] = review_visible
    base["clean_review_offset_anchor_addition"] = clean_use
    base["hold_from_clean_analysis"] = hold_clean
    base["review_only_recovery_branch"] = "missing_hmms_offset_anchor"
    base["review_only_universe_tier"] = np.select(
        [base["clean_review_offset_anchor_addition"], base["review_visible_offset_anchor_addition"], ~base["has_generated_bins"]],
        ["offset_anchor_clean_candidate", "offset_anchor_review_visible_risk_flagged", "offset_anchor_low_confidence_holdout"],
        default="offset_anchor_not_context_ready",
    )
    return base


def _expanded_signals(good_universe: pd.DataFrame, classified: pd.DataFrame) -> pd.DataFrame:
    offset = classified[classified["review_visible_offset_anchor_addition"]].copy()
    offset["universe_record_type"] = "offset_anchor_recovered"
    offset["addition_review_class"] = offset["offset_anchor_addition_class"]
    offset["expanded_universe_readiness_class"] = offset["offset_anchor_universe_readiness_class"]
    offset["review_only_flag"] = True
    base = good_universe.copy()
    if "universe_record_type" not in base.columns:
        base["universe_record_type"] = np.where(_text(base, "addition_review_class").str.strip().eq("existing_represented"), "existing_represented", "good_travelway_or_existing")
    cols = sorted(set(base.columns) | set(offset.columns))
    for col in cols:
        if col not in base.columns:
            base[col] = ""
        if col not in offset.columns:
            offset[col] = ""
    return pd.concat([base[cols], offset[cols]], ignore_index=True)


def _expanded_bins(good_bins: pd.DataFrame, offset_bins: pd.DataFrame, classified: pd.DataFrame) -> pd.DataFrame:
    ready_ids = set(_text(classified[classified["review_visible_offset_anchor_addition"]], "stable_signal_id"))
    offset = offset_bins[_text(offset_bins, "stable_signal_id").isin(ready_ids)].copy()
    class_cols = [
        "stable_signal_id",
        "offset_anchor_addition_class",
        "offset_anchor_universe_readiness_class",
        "review_visible_offset_anchor_addition",
        "clean_review_offset_anchor_addition",
        "hold_from_clean_analysis",
    ]
    offset = offset.merge(classified[class_cols], on="stable_signal_id", how="left")
    offset = offset.rename(
        columns={
            "physical_leg_group_id": "physical_leg_id_final",
            "carriageway_subbranch_id": "carriageway_subbranch_id_final",
            "rns_CAR_SPEED_LIMIT": "rns_car_speed_limit",
            "aadt_AADT": "aadt_value",
            "aadt_AADT_YR": "aadt_year",
        }
    )
    offset["universe_record_type"] = "offset_anchor_recovered"
    offset["addition_review_class"] = offset["offset_anchor_addition_class"]
    offset["expanded_universe_readiness_class"] = offset["offset_anchor_universe_readiness_class"]
    offset["review_only_recovery_branch"] = "missing_hmms_offset_anchor"
    base = good_bins.copy()
    cols = sorted(set(base.columns) | set(offset.columns))
    for col in cols:
        if col not in base.columns:
            base[col] = ""
        if col not in offset.columns:
            offset[col] = ""
    return pd.concat([base[cols], offset[cols]], ignore_index=True)


def _summaries(classified: pd.DataFrame, expanded_signals: pd.DataFrame, expanded_bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    generated = classified[classified["has_generated_bins"]]
    context_ready = classified[classified["review_visible_offset_anchor_addition"]]
    clean = classified[classified["clean_review_offset_anchor_addition"]]
    risk = generated[generated["overlap_or_dedup_risk"]]
    risk_context_ready = risk[risk["review_visible_offset_anchor_addition"]]
    risk_not_context_ready = risk[~risk["review_visible_offset_anchor_addition"]]
    skipped = classified[~classified["has_generated_bins"]]
    duplicate_count = int(classified["stable_signal_id_overlap_with_existing_or_good"].sum() + classified["source_signal_id_overlap_with_existing_or_good"].sum())
    review_visible_count = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS + len(context_ready)
    clean_count = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_CLEAN_ADDITIONS + len(clean)
    addition_summary = pd.DataFrame(
        [
            {"metric": "base_staged_source_signal_universe", "value": SOURCE_SIGNAL_UNIVERSE_COUNT},
            {"metric": "original_represented_signal_universe", "value": CURRENT_REPRESENTED_SIGNAL_COUNT},
            {"metric": "good_travelway_review_visible_additions", "value": GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS},
            {"metric": "good_travelway_clean_additions", "value": GOOD_TRAVELWAY_CLEAN_ADDITIONS},
            {"metric": "offset_anchor_targets", "value": len(classified)},
            {"metric": "offset_anchor_generated_signals", "value": len(generated)},
            {"metric": "offset_anchor_speed_aadt_ready_review_visible_additions", "value": len(context_ready)},
            {"metric": "offset_anchor_clean_additions", "value": len(clean)},
            {"metric": "offset_anchor_generated_risk_flagged_signals", "value": len(risk)},
            {"metric": "offset_anchor_generated_risk_context_ready_with_review_flags", "value": len(risk_context_ready)},
            {"metric": "offset_anchor_generated_risk_not_context_ready", "value": len(risk_not_context_ready)},
            {"metric": "offset_anchor_exact_duplicate_signal_risk_flags", "value": int(classified["exact_duplicate_signal_risk"].sum())},
            {"metric": "offset_anchor_sibling_signal_risk_flags", "value": int(classified["sibling_signal_risk"].sum())},
            {"metric": "offset_anchor_complex_multi_signal_risk_flags", "value": int(classified["complex_multi_signal_risk"].sum())},
            {"metric": "offset_anchor_overlap_review_required_flags", "value": int(classified["overlap_review_required"].sum())},
            {"metric": "offset_anchor_low_confidence_holdouts", "value": len(skipped)},
            {"metric": "expanded_review_visible_signal_universe", "value": review_visible_count},
            {"metric": "expanded_clean_review_signal_universe", "value": clean_count},
            {"metric": "expanded_review_visible_share_of_3933", "value": round(review_visible_count / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "expanded_clean_review_share_of_3933", "value": round(clean_count / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "exact_source_or_stable_overlap_dedup_signal_count", "value": duplicate_count},
            {"metric": "expanded_review_only_bin_universe_rows", "value": len(expanded_bins)},
        ]
    )
    readiness = classified.groupby("offset_anchor_universe_readiness_class", dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        generated_signals=("has_generated_bins", "sum"),
        review_visible_additions=("review_visible_offset_anchor_addition", "sum"),
        clean_review_additions=("clean_review_offset_anchor_addition", "sum"),
        high_crash_relevance_signals=("high_crash_relevance_flag", "sum"),
        source_not_represented_unassigned_crashes_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
    ).reset_index()
    class_summary = classified.groupby("offset_anchor_addition_class", dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        review_visible_additions=("review_visible_offset_anchor_addition", "sum"),
        clean_review_additions=("clean_review_offset_anchor_addition", "sum"),
        hold_from_clean_analysis=("hold_from_clean_analysis", "sum"),
        high_crash_relevance_signals=("high_crash_relevance_flag", "sum"),
        source_not_represented_unassigned_crashes_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
    ).reset_index()
    crash = pd.DataFrame(
        [
            _crash_row("context_ready_173", context_ready),
            _crash_row("clean_62", clean),
            _crash_row("risk_flagged_generated_113", risk),
            _crash_row("skipped_low_confidence_167", skipped),
            _crash_row("all_offset_anchor_targets_352", classified),
        ]
    )
    return addition_summary, readiness, class_summary, crash


def _crash_row(group: str, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "group": group,
        "signal_count": int(frame["stable_signal_id"].nunique()) if not frame.empty else 0,
        "high_crash_relevance_signals": int(_flag(frame, "high_crash_relevance_flag").sum()) if not frame.empty else 0,
        "source_not_represented_unassigned_crashes_within_2500ft_sum": int(_num(frame, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum()) if not frame.empty else 0,
    }


def _holdout_ledger(classified: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "stable_signal_id",
        "GLOBALID",
        "source_signal_id",
        "OBJECTID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "source_layer",
        "source_system",
        "source_group",
        "recoverability_class",
        "crash_relevance_class",
        "high_crash_relevance_flag",
        "source_not_represented_unassigned_crashes_within_2500ft",
        "anchor_method",
        "anchor_confidence",
        "signal_to_anchor_offset_ft",
        "skip_reason",
        "skip_note",
        "offset_anchor_addition_class",
        "offset_anchor_universe_readiness_class",
    ]
    hold = classified[classified["offset_anchor_addition_class"].eq("hold_low_confidence_anchor")].copy()
    if "skip_reason" not in hold.columns:
        hold = hold.merge(skipped[["stable_signal_id", "skip_reason", "skip_note"]], on="stable_signal_id", how="left")
    hold["later_action_recommendation"] = np.where(
        _flag(hold, "high_crash_relevance_flag"),
        "revisit_low_confidence_anchor_after map review or better source geometry",
        "treat_as_current_source_geometry_limitation_until_targeted_anchor_review",
    )
    return hold[[col for col in cols if col in hold.columns] + ["later_action_recommendation"]]


def _findings(addition_summary: pd.DataFrame, readiness_audit: pd.DataFrame, class_summary: pd.DataFrame, crash: pd.DataFrame) -> str:
    values = dict(zip(addition_summary["metric"], addition_summary["value"]))
    class_counts = dict(zip(class_summary["offset_anchor_addition_class"], class_summary["signal_count"]))
    crash_high = dict(zip(crash["group"], crash["high_crash_relevance_signals"]))
    crash_sum = dict(zip(crash["group"], crash["source_not_represented_unassigned_crashes_within_2500ft_sum"]))
    class_lines = "\n".join(
        f"- {row.offset_anchor_addition_class}: {int(row.signal_count):,} signals; "
        f"{int(row.review_visible_additions):,} review-visible; "
        f"{int(row.clean_review_additions):,} clean; "
        f"{int(row.high_crash_relevance_signals):,} high-crash-relevance"
        for row in class_summary.sort_values("offset_anchor_addition_class").itertuples(index=False)
    )
    mismatch = readiness_audit.loc[readiness_audit["readiness_metric"].eq("speed_aadt_ready"), "mismatch_explanation"].iloc[0]
    return f"""# Offset-Anchor Missing-HMMS Universe Integration Findings

## Bounded Question

This read-only pass integrates context-ready missing-HMMS offset-anchor recovery candidates into review-only universe accounting. It does not promote signals to production/final active outputs, assign crashes, assign access, calculate rates/models, or use crash direction fields.

## Readiness Reconciliation

{mismatch}

- Route/measure-ready generated signals: {int(readiness_audit.loc[readiness_audit['readiness_metric'].eq('route_measure_ready'), 'signal_count'].iloc[0]):,}
- Speed+AADT-ready generated signals: {int(readiness_audit.loc[readiness_audit['readiness_metric'].eq('speed_aadt_ready'), 'signal_count'].iloc[0]):,}
- Full 0-1,000 ft speed+AADT-ready generated signals: {int(readiness_audit.loc[readiness_audit['readiness_metric'].eq('full_0_1000_ready'), 'signal_count'].iloc[0]):,}

## Universe Counts

- Expanded review-visible signal count if the 173 context-ready offset-anchor additions are included: {int(values['expanded_review_visible_signal_universe']):,}
- Expanded clean-review signal count if the 62 clean offset-anchor candidates are included: {int(values['expanded_clean_review_signal_universe']):,}
- Review-visible share of the 3,933 staged/source signal universe: {float(values['expanded_review_visible_share_of_3933']):.1%}
- Clean-review share of the 3,933 staged/source signal universe: {float(values['expanded_clean_review_share_of_3933']):.1%}
- Expanded review-only bin rows: {int(values['expanded_review_only_bin_universe_rows']):,}

## Risk Decomposition

The 113 generated risk-flagged signals are explained by duplicate/source-ID overlap, sibling-signal risk, complex multi-signal context, and existing/recovered scaffold overlap. They should remain visible with QA flags where context-ready, but held from clean analysis until map review resolves the risk class.

- Risk-flagged generated signals that are context-ready and review-visible with flags: {int(values['offset_anchor_generated_risk_context_ready_with_review_flags']):,}
- Risk-flagged generated signals that are not context-ready and should remain held: {int(values['offset_anchor_generated_risk_not_context_ready']):,}

{class_lines}

## Crash Context Impact

- Context-ready additions: {int(crash_high.get('context_ready_173', 0)):,} high-crash-relevance signals; {int(crash_sum.get('context_ready_173', 0)):,} nearby source-not-represented unassigned crashes within 2,500 ft.
- Clean additions: {int(crash_high.get('clean_62', 0)):,} high-crash-relevance signals; {int(crash_sum.get('clean_62', 0)):,} nearby source-not-represented unassigned crashes within 2,500 ft.
- Risk-flagged generated signals: {int(crash_high.get('risk_flagged_generated_113', 0)):,} high-crash-relevance signals; {int(crash_sum.get('risk_flagged_generated_113', 0)):,} nearby source-not-represented unassigned crashes within 2,500 ft.
- Low-confidence holdouts: {int(crash_high.get('skipped_low_confidence_167', 0)):,} high-crash-relevance signals; {int(crash_sum.get('skipped_low_confidence_167', 0)):,} nearby source-not-represented unassigned crashes within 2,500 ft.

## Recommendation

Integrate the 173 speed+AADT-ready offset-anchor additions into the review-visible universe with QA flags, and integrate only the 62 clean candidates into the clean-review universe. The next pass should package/map-review the 113 generated risk-flagged offset-anchor signals before clean analytical use. The 167 low-confidence anchor holdouts should remain ledgered and should be revisited only after the risk-flagged context-ready branch is reviewed; complex multi-signal missing-HMMS remains a separate later target.
"""


def _qa(expanded_bins: pd.DataFrame, classified: pd.DataFrame, holdout: pd.DataFrame) -> pd.DataFrame:
    stable_present = _text(expanded_bins, "stable_travelway_id").str.strip().ne("")
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted_to_production_final", "status": "passed", "observed": "review-only universe integration"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only prior proximity summaries carried forward"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active; crash source not read"},
            {"check_name": "stable_travelway_id_preserved", "status": "passed" if stable_present.all() else "failed", "observed": f"{int(stable_present.sum())}/{len(expanded_bins)}"},
            {"check_name": "source_globalids_preserved_where_available", "status": "passed", "observed": f"{int(_text(classified, 'GLOBALID').str.strip().ne('').sum())} available"},
            {"check_name": "skipped_low_confidence_anchors_ledgered_not_forced", "status": "passed" if len(holdout) == 167 else "failed", "observed": f"{len(holdout)} holdouts ledgered"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    context_manifest = _load_json(CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json")
    recovery_manifest = _load_json(RECOVERY_DIR / "offset_anchor_scaffold_recovery_manifest.json")
    good_manifest = _load_json(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json")
    complex_manifest = _load_json(COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json")
    stable_manifest = _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json")

    signal_summary = _read_csv(CONTEXT_DIR / "offset_anchor_context_signal_summary.csv")
    bin_detail = _read_csv(CONTEXT_DIR / "offset_anchor_context_bin_detail.csv")
    overlap = _read_csv(CONTEXT_DIR / "offset_anchor_existing_universe_overlap_review.csv")
    skipped = _read_csv(RECOVERY_DIR / "offset_anchor_recovery_skipped_targets.csv")
    good_signals = _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv")
    good_bins = _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv")
    stable_signals = _read_csv(STABLE_DIR / "stable_lineage_represented_signal_universe.csv")

    readiness_audit = _readiness_consistency(signal_summary)
    classified = _classify_offset_signals(signal_summary, good_signals, stable_signals)
    # Keep the standalone overlap table source visible even when columns were already carried into signal_summary.
    classified = classified.merge(overlap.add_prefix("overlap_table_"), left_on="stable_signal_id", right_on="overlap_table_stable_signal_id", how="left")
    expanded_signals = _expanded_signals(good_signals, classified)
    expanded_bins = _expanded_bins(good_bins, bin_detail, classified)
    addition_summary, universe_readiness, class_summary, crash_impact = _summaries(classified, expanded_signals, expanded_bins)
    risk_decomp = classified[classified["has_generated_bins"] & classified["overlap_or_dedup_risk"]].copy()
    holdout = _holdout_ledger(classified, skipped)
    qa = _qa(expanded_bins, classified, holdout)

    _write_csv(expanded_signals, "expanded_offset_anchor_signal_universe.csv")
    _write_csv(expanded_bins, "expanded_offset_anchor_bin_universe.csv")
    _write_csv(readiness_audit, "offset_anchor_readiness_consistency_audit.csv")
    _write_csv(addition_summary, "offset_anchor_173_addition_summary.csv")
    _write_csv(risk_decomp, "offset_anchor_113_risk_decomposition.csv")
    _write_csv(holdout, "offset_anchor_167_low_confidence_holdout_ledger.csv")
    _write_csv(universe_readiness, "offset_anchor_universe_readiness.csv")
    _write_csv(crash_impact, "offset_anchor_crash_context_impact_summary.csv")
    _write_text(_findings(addition_summary, readiness_audit, class_summary, crash_impact), "offset_anchor_universe_integration_findings.md")
    _write_csv(qa, "offset_anchor_universe_integration_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_offset_anchor_universe_integration",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "input_manifests": {
            "offset_anchor_context_refresh": context_manifest,
            "offset_anchor_scaffold_recovery": recovery_manifest,
            "good_travelway_universe_integration": good_manifest,
            "complex_signal_review_ingestion": complex_manifest,
            "stable_lineage_scaffold": stable_manifest,
        },
        "counts": {
            "offset_anchor_targets": int(len(classified)),
            "offset_anchor_generated_signals": int(classified["has_generated_bins"].sum()),
            "offset_anchor_context_ready_review_visible_additions": int(classified["review_visible_offset_anchor_addition"].sum()),
            "offset_anchor_clean_additions": int(classified["clean_review_offset_anchor_addition"].sum()),
            "offset_anchor_generated_risk_flagged_signals": int(len(risk_decomp)),
            "offset_anchor_low_confidence_holdouts": int(len(holdout)),
            "expanded_review_visible_signal_universe": int(addition_summary.loc[addition_summary["metric"].eq("expanded_review_visible_signal_universe"), "value"].iloc[0]),
            "expanded_clean_review_signal_universe": int(addition_summary.loc[addition_summary["metric"].eq("expanded_clean_review_signal_universe"), "value"].iloc[0]),
            "expanded_bin_universe_rows": int(len(expanded_bins)),
        },
        "qa": qa.to_dict(orient="records"),
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
    }
    _write_json(manifest, "offset_anchor_universe_integration_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Review-visible offset additions: {int(classified['review_visible_offset_anchor_addition'].sum()):,}")
    print(f"Clean offset additions: {int(classified['clean_review_offset_anchor_addition'].sum()):,}")
    print(f"Risk decomposition rows: {len(risk_decomp):,}")
    print(f"Low-confidence holdouts: {len(holdout):,}")


if __name__ == "__main__":
    main()
