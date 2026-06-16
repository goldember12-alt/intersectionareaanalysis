from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/crash_roadway_identity_assignment_doctrine"

CORE_DIR = OUTPUT_ROOT / "review/current/crash_roadway_identity_core_integration"
ASSIGN_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_candidate_assignment"
SANITY_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_sanity_audit"
FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

REQUIRED_INPUTS = [
    CORE_DIR / "crash_core_roadway_identity_table.csv",
    CORE_DIR / "crash_spatial_50ft_with_identity_compatibility.csv",
    CORE_DIR / "crash_identity_compatible_spatial_50ft_assignment.csv",
    CORE_DIR / "crash_identity_conflict_spatial_assignments.csv",
    CORE_DIR / "crash_identity_only_signal_window_candidates.csv",
    CORE_DIR / "crash_fanout_before_after_identity_constraint.csv",
    CORE_DIR / "crash_assignment_product_comparison.csv",
    CORE_DIR / "crash_roadway_identity_doctrine.csv",
    CORE_DIR / "crash_roadway_identity_core_readiness_decision.csv",
    CORE_DIR / "crash_roadway_identity_core_integration_manifest.json",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_fanout_summary.csv",
    ASSIGN_DIR / "final_leg_corrected_crash_candidate_assignment_manifest.json",
    SANITY_DIR / "crash_fanout_sanity_detail.csv",
    SANITY_DIR / "crash_fanout_sanity_summary.csv",
    SANITY_DIR / "crash_high_fanout_cause_classification.csv",
    SANITY_DIR / "crash_sanity_readiness_decision.csv",
    SANITY_DIR / "final_leg_corrected_crash_sanity_manifest.json",
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
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
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _is_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _collapse(values: pd.Series, limit: int = 10) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _load_core_identity() -> pd.DataFrame:
    cols = [
        "stable_crash_id",
        "DOCUMENT_NBR",
        "CRASH_YEAR",
        "CRASH_DT",
        "CRASH_SEVERITY",
        "COLLISION_TYPE",
        "RTE_NM",
        "RNS_MP",
        "NODE",
        "OFFSET",
        "JURIS_CODE",
        "PHYSICAL_JURIS",
        "best_stable_travelway_id",
        "matched_stable_travelway_id_candidates",
        "candidate_travelway_count_num",
        "match_method",
        "match_confidence",
        "route_key_compatibility",
        "geometry_distance_to_matched_travelway_ft",
        "matched_travelway_represented_in_final_scaffold",
        "has_signal_window_candidates",
        "signal_window_candidate_count",
        "signal_window_candidate_signals",
        "signal_window_candidate_windows",
    ]
    return _read_csv(CORE_DIR / "crash_core_roadway_identity_table.csv", usecols=cols)


def _spatial_summary(spatial: pd.DataFrame) -> pd.DataFrame:
    spatial["identity_compatible_assignment_flag"] = _text(spatial, "identity_compatible_assignment_flag").str.lower().isin({"true", "1", "yes"})
    spatial["identity_conflict_flag"] = _text(spatial, "identity_conflict_flag").str.lower().isin({"true", "1", "yes"})
    grouped = spatial.groupby("stable_crash_id", dropna=False).agg(
        spatial_50_assigned=("stable_bin_id", lambda s: True),
        spatial_assignment_rows=("stable_bin_id", "count"),
        spatial_signal_count=("stable_signal_id", "nunique"),
        spatial_bin_count=("stable_bin_id", "nunique"),
        spatial_leg_count=("final_review_physical_leg_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        identity_compatible_spatial_rows=("identity_compatible_assignment_flag", "sum"),
        identity_conflict_spatial_rows=("identity_conflict_flag", "sum"),
        spatial_identity_classes=("assignment_identity_compatibility", _collapse),
        original_spatial_weight_sum=("original_spatial_source_preserving_weight", lambda s: pd.to_numeric(s, errors="coerce").sum()),
    ).reset_index()
    compatible = spatial.loc[spatial["identity_compatible_assignment_flag"]].copy()
    if compatible.empty:
        grouped["identity_compatible_signal_count"] = 0
        grouped["identity_compatible_bin_count"] = 0
        grouped["identity_compatible_leg_count"] = 0
        grouped["identity_compatible_weight_sum"] = 0.0
        return grouped
    compat = compatible.groupby("stable_crash_id", dropna=False).agg(
        identity_compatible_signal_count=("stable_signal_id", "nunique"),
        identity_compatible_bin_count=("stable_bin_id", "nunique"),
        identity_compatible_leg_count=("final_review_physical_leg_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        identity_compatible_weight_sum=("identity_constrained_source_preserving_weight", lambda s: pd.to_numeric(s, errors="coerce").sum()),
    ).reset_index()
    out = grouped.merge(compat, on="stable_crash_id", how="left")
    for col in [
        "identity_compatible_signal_count",
        "identity_compatible_bin_count",
        "identity_compatible_leg_count",
        "identity_compatible_weight_sum",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def _identity_only_summary(identity_only: pd.DataFrame) -> pd.DataFrame:
    if identity_only.empty:
        return pd.DataFrame(columns=["stable_crash_id"])
    return identity_only.groupby("stable_crash_id", dropna=False).agg(
        identity_only_candidate=("stable_signal_id", lambda s: True),
        identity_only_candidate_rows=("stable_signal_id", "count"),
        identity_only_candidate_signals=("stable_signal_id", "nunique"),
        identity_only_candidate_windows=("analysis_window", "nunique"),
        identity_only_candidate_classes=("identity_only_candidate_class", _collapse),
        identity_only_confidence=("match_confidence", _collapse),
        identity_only_windows=("analysis_window", _collapse),
    ).reset_index()


def _build_status(core: pd.DataFrame, spatial_summary: pd.DataFrame, identity_only_summary: pd.DataFrame) -> pd.DataFrame:
    status = core.merge(spatial_summary, on="stable_crash_id", how="left").merge(identity_only_summary, on="stable_crash_id", how="left")
    status["spatial_50_assigned"] = status["spatial_50_assigned"].fillna(False).astype(bool)
    status["identity_only_candidate"] = status["identity_only_candidate"].fillna(False).astype(bool)
    numeric_cols = [
        "spatial_assignment_rows",
        "spatial_signal_count",
        "spatial_bin_count",
        "spatial_leg_count",
        "identity_compatible_spatial_rows",
        "identity_compatible_signal_count",
        "identity_compatible_bin_count",
        "identity_compatible_leg_count",
        "identity_conflict_spatial_rows",
        "identity_only_candidate_rows",
        "identity_only_candidate_signals",
        "identity_only_candidate_windows",
        "signal_window_candidate_count",
        "signal_window_candidate_signals",
        "signal_window_candidate_windows",
    ]
    for col in numeric_cols:
        status[col] = pd.to_numeric(status[col], errors="coerce").fillna(0).astype(int)
    high_medium = _text(status, "match_confidence").isin(["high", "medium"])
    low_only = _text(status, "match_confidence").eq("low")
    has_compatible = status["identity_compatible_spatial_rows"].gt(0)
    has_conflict = status["identity_conflict_spatial_rows"].gt(0)
    no_usable_identity = ~high_medium
    status["crash_level_assignment_class"] = np.select(
        [
            status["spatial_50_assigned"] & has_compatible & status["identity_conflict_spatial_rows"].eq(0),
            status["spatial_50_assigned"] & has_compatible & has_conflict,
            status["spatial_50_assigned"] & high_medium & ~has_compatible & has_conflict & status["candidate_travelway_count_num"].astype(float).gt(1),
            status["spatial_50_assigned"] & high_medium & ~has_compatible & has_conflict,
            status["spatial_50_assigned"] & no_usable_identity,
            ~status["spatial_50_assigned"] & status["identity_only_candidate"] & high_medium,
            ~status["spatial_50_assigned"] & status["identity_only_candidate"] & low_only,
        ],
        [
            "spatial_and_identity_agree",
            "spatial_multirow_identity_filters_to_subset",
            "spatial_assigned_identity_ambiguous",
            "spatial_assigned_identity_conflict_no_compatible_rows",
            "spatial_assigned_no_identity_available",
            "identity_only_signal_window_candidate",
            "low_confidence_identity_only",
        ],
        default="spatial_unassigned_no_identity_candidate",
    )
    _checkpoint("build crash-level identity/spatial status", len(status))
    return status


def _class_summary(status: pd.DataFrame) -> pd.DataFrame:
    return status.groupby("crash_level_assignment_class", dropna=False).agg(
        crash_count=("stable_crash_id", "nunique"),
        high_identity=("match_confidence", lambda s: int((s == "high").sum())),
        medium_identity=("match_confidence", lambda s: int((s == "medium").sum())),
        low_identity=("match_confidence", lambda s: int((s == "low").sum())),
        no_identity=("match_confidence", lambda s: int((s == "none").sum())),
        median_spatial_signals=("spatial_signal_count", "median"),
        median_identity_compatible_signals=("identity_compatible_signal_count", "median"),
    ).reset_index()


def _compatible_rollups(compatible: pd.DataFrame) -> pd.DataFrame:
    if compatible.empty:
        return pd.DataFrame()
    return compatible.groupby(["analysis_window", "assignment_identity_compatibility"], dropna=False).agg(
        unique_crashes=("stable_crash_id", "nunique"),
        assignment_rows=("stable_bin_id", "count"),
        weighted_crash_count=("identity_constrained_source_preserving_weight", lambda s: pd.to_numeric(s, errors="coerce").sum()),
        signals=("stable_signal_id", "nunique"),
        bins=("stable_bin_id", "nunique"),
    ).reset_index()


def _fanout_compare(status: pd.DataFrame) -> pd.DataFrame:
    out = status[
        [
            "stable_crash_id",
            "crash_level_assignment_class",
            "match_confidence",
            "spatial_signal_count",
            "spatial_bin_count",
            "spatial_leg_count",
            "identity_compatible_signal_count",
            "identity_compatible_bin_count",
            "identity_compatible_leg_count",
            "identity_only_candidate_signals",
            "identity_only_candidate_rows",
        ]
    ].copy()
    out["signal_fanout_reduction"] = out["spatial_signal_count"] - out["identity_compatible_signal_count"]
    out["bin_fanout_reduction"] = out["spatial_bin_count"] - out["identity_compatible_bin_count"]
    out["leg_fanout_reduction"] = out["spatial_leg_count"] - out["identity_compatible_leg_count"]
    out["collapses_to_one_signal_after_identity_filter"] = out["identity_compatible_signal_count"].eq(1) & out["spatial_signal_count"].gt(1)
    out["remains_high_fanout_after_identity_filter"] = out["identity_compatible_signal_count"].ge(4) | out["identity_compatible_bin_count"].ge(20)
    out["fanout_change_class"] = np.select(
        [
            out["identity_compatible_signal_count"].eq(0) & out["spatial_signal_count"].gt(0),
            out["signal_fanout_reduction"].gt(0),
            out["signal_fanout_reduction"].eq(0) & out["spatial_signal_count"].gt(0),
        ],
        ["no_identity_compatible_spatial_rows", "fanout_reduced", "fanout_unchanged"],
        default="not_spatially_assigned",
    )
    return out


def _conflict_diagnosis(status: pd.DataFrame) -> pd.DataFrame:
    work = status.loc[status["identity_conflict_spatial_rows"].gt(0)].copy()
    work["row_level_conflict_diagnosis"] = np.select(
        [
            work["identity_compatible_spatial_rows"].gt(0),
            work["candidate_travelway_count_num"].astype(float).gt(1),
            work["match_confidence"].eq("low"),
            work["match_confidence"].eq("none"),
            work["identity_compatible_spatial_rows"].eq(0) & work["match_confidence"].isin(["high", "medium"]),
        ],
        [
            "conflict_rows_extra_neighboring_catchments_with_compatible_rows_present",
            "crash_identity_ambiguous",
            "crash_identity_low_confidence",
            "no_usable_crash_identity",
            "no_compatible_spatial_rows_likely_geometry_or_route_identity_issue",
        ],
        default="manual_review_needed",
    )
    return work[
        [
            "stable_crash_id",
            "match_confidence",
            "best_stable_travelway_id",
            "spatial_signal_count",
            "spatial_bin_count",
            "identity_compatible_spatial_rows",
            "identity_conflict_spatial_rows",
            "spatial_identity_classes",
            "row_level_conflict_diagnosis",
        ]
    ].copy()


def _identity_only_classification(identity_only: pd.DataFrame) -> pd.DataFrame:
    if identity_only.empty:
        return pd.DataFrame()
    group = identity_only.groupby("stable_crash_id", dropna=False).agg(
        identity_only_candidate_rows=("stable_signal_id", "count"),
        identity_only_candidate_signals=("stable_signal_id", "nunique"),
        identity_only_candidate_windows=("analysis_window", "nunique"),
        identity_confidence=("match_confidence", _collapse),
        candidate_windows=("analysis_window", _collapse),
        candidate_distance_windows=("distance_bands", _collapse),
        candidate_class_source=("identity_only_candidate_class", _collapse),
        route_measure_compatibility=("route_measure_compatibility", _collapse),
    ).reset_index()
    confidence = _text(group, "identity_confidence")
    group["identity_only_doctrine_class"] = np.select(
        [
            confidence.str.contains("high", na=False) & group["identity_only_candidate_signals"].le(2),
            confidence.str.contains("high|medium", regex=True, na=False) & group["candidate_windows"].str.contains("0_1000", na=False),
            confidence.str.contains("high|medium", regex=True, na=False),
            confidence.str.contains("low", na=False),
        ],
        [
            "strong_identity_only_candidate",
            "route_measure_supported_but_spatially_outside_buffer",
            "identity_candidate_but_window_uncertain",
            "low_confidence_hold",
        ],
        default="outside_spatial_buffer_possible_geocode_offset",
    )
    return group


def _product_comparison(status: pd.DataFrame, compatible: pd.DataFrame, identity_only: pd.DataFrame) -> pd.DataFrame:
    spatial_crashes = status.loc[status["spatial_50_assigned"], "stable_crash_id"]
    compat_crashes = set(_text(compatible, "stable_crash_id"))
    identity_only_crashes = set(_text(identity_only, "stable_crash_id"))
    rows = [
        {
            "product": "spatial_50ft_primary",
            "unique_crashes": int(spatial_crashes.nunique()),
            "assignment_rows": int(status["spatial_assignment_rows"].sum()),
            "weighted_crash_count": int(spatial_crashes.nunique()),
            "signal_count": "",
            "signal_window_count": "",
            "crashes_with_4plus_signals": int((status["spatial_signal_count"] >= 4).sum()),
        },
        {
            "product": "identity_compatible_spatial_50ft",
            "unique_crashes": len(compat_crashes),
            "assignment_rows": len(compatible),
            "weighted_crash_count": float(pd.to_numeric(compatible.get("identity_constrained_source_preserving_weight", pd.Series(dtype=float)), errors="coerce").sum()),
            "signal_count": int(compatible["stable_signal_id"].nunique()) if not compatible.empty else 0,
            "signal_window_count": int(compatible[["stable_signal_id", "analysis_window"]].drop_duplicates().shape[0]) if not compatible.empty else 0,
            "crashes_with_4plus_signals": int((status["identity_compatible_signal_count"] >= 4).sum()),
        },
        {
            "product": "identity_only_signal_window_candidates",
            "unique_crashes": len(identity_only_crashes),
            "assignment_rows": len(identity_only),
            "weighted_crash_count": "",
            "signal_count": int(identity_only["stable_signal_id"].nunique()) if not identity_only.empty else 0,
            "signal_window_count": int(identity_only[["stable_signal_id", "analysis_window"]].drop_duplicates().shape[0]) if not identity_only.empty else 0,
            "crashes_with_4plus_signals": int((identity_only.groupby("stable_crash_id")["stable_signal_id"].nunique() >= 4).sum()) if not identity_only.empty else 0,
        },
        {
            "product": "spatial_plus_identity_compatible_union",
            "unique_crashes": int(len(set(spatial_crashes.astype(str)) | compat_crashes)),
            "assignment_rows": int(status["spatial_assignment_rows"].sum() + len(compatible)),
            "weighted_crash_count": "",
            "signal_count": "",
            "signal_window_count": "",
            "crashes_with_4plus_signals": "",
        },
        {
            "product": "spatial_plus_identity_only_candidate_union_diagnostic",
            "unique_crashes": int(len(set(spatial_crashes.astype(str)) | identity_only_crashes)),
            "assignment_rows": int(status["spatial_assignment_rows"].sum() + len(identity_only)),
            "weighted_crash_count": "",
            "signal_count": "",
            "signal_window_count": "",
            "crashes_with_4plus_signals": "",
        },
    ]
    return pd.DataFrame(rows)


def _doctrine() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("core_crash_roadway_identity_table", "required_carried_field", "carry in all crash QA/assignment outputs", "not a standalone signal assignment"),
            ("spatial_50ft_primary", "primary_geometry_product", "primary review crash catchment product", "not replaced by identity filtering"),
            ("identity_compatible_spatial_50ft", "standard_sensitivity_product", "standard carried QA/sensitivity assignment", "not production primary by itself"),
            ("identity_only_signal_window_candidates", "diagnostic_review_only", "explain spatially unassigned crashes and candidate map review", "not primary before validation"),
            ("spatial_only_conflicts", "qa_review_class", "review geometry/catchment or route identity mismatch", "do not silently discard"),
            ("low_or_no_identity_crashes", "spatial_fallback", "retain spatial-only interpretation where identity absent", "do not force identity labels"),
        ],
        columns=["product_or_class", "doctrine_role", "recommended_use", "not_for"],
    )


def _findings(status: pd.DataFrame, fanout: pd.DataFrame, conflict: pd.DataFrame, identity_class: pd.DataFrame) -> str:
    class_counts = status["crash_level_assignment_class"].value_counts().to_dict()
    spatial_with_compat = int((status["spatial_50_assigned"] & status["identity_compatible_spatial_rows"].gt(0)).sum())
    spatial_conflict_only = int((status["spatial_50_assigned"] & status["identity_compatible_spatial_rows"].eq(0) & status["identity_conflict_spatial_rows"].gt(0)).sum())
    no_identity = int((status["spatial_50_assigned"] & status["match_confidence"].isin(["none", "low"])).sum())
    reduced = int(fanout["fanout_change_class"].eq("fanout_reduced").sum())
    collapse_one = int(fanout["collapses_to_one_signal_after_identity_filter"].sum())
    remain_high = int(fanout["remains_high_fanout_after_identity_filter"].sum())
    conflict_top = conflict["row_level_conflict_diagnosis"].value_counts().idxmax() if not conflict.empty else "none"
    identity_only = int(status["crash_level_assignment_class"].eq("identity_only_signal_window_candidate").sum())
    strong_identity_only = int(identity_class["identity_only_doctrine_class"].eq("strong_identity_only_candidate").sum()) if not identity_class.empty else 0
    return f"""# Crash Roadway Identity Assignment Doctrine

Bounded question: aggregate row-level crash roadway-identity compatibility to crash-level assignment doctrine without replacing the spatial 50 ft primary product.

## Findings

1. Spatially assigned crashes with at least one identity-compatible spatial row: {spatial_with_compat:,}.
2. Spatially assigned crashes with only identity-conflicting rows: {spatial_conflict_only:,}.
3. Spatially assigned crashes with no usable high/medium roadway identity: {no_identity:,}.
4. Identity-compatible filtering reduces fanout for {reduced:,} crashes.
5. Crashes collapsing to one signal after identity filtering: {collapse_one:,}.
6. Crashes remaining high-fanout after identity filtering: {remain_high:,}.
7. Row-level conflicts mostly mean: `{conflict_top}`. The row-level conflict count should not be read as a crash-level failure because many crashes also retain compatible rows.
8. Identity-only candidate crashes remain review/sensitivity only: {identity_only:,} high/medium candidates, including {strong_identity_only:,} strong candidates by this pass's doctrine labels.
9. Identity-compatible spatial 50 ft should become a standard carried crash sensitivity product.
10. Spatial 50 ft remains the primary geometry product.

## Class Counts

{pd.Series(class_counts).to_string()}

## QA

No active outputs were modified. No records were promoted. No rates/models were calculated. No final production crash assignment was created. Crash direction fields were not used. Identity-compatible products are review-only/standard sensitivity.
"""


def _qa(missing: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "outputs written only to review/current/crash_roadway_identity_assignment_doctrine"),
        ("no_records_promoted", True, "review-only doctrine/comparison"),
        ("no_rates_or_models", True, "no rates/models calculated"),
        ("no_final_production_crash_assignment_created", True, "standard sensitivity product only"),
        ("crash_direction_fields_not_used", True, "no direction-like fields read or used"),
        ("spatial_50ft_not_replaced", True, "spatial 50 ft remains primary"),
        ("identity_products_review_only_standard_sensitivity", True, "compatible product is standard sensitivity; identity-only remains diagnostic"),
        ("source_preserving_weights_recalculated_or_documented", True, "identity-compatible rows carry identity_constrained_source_preserving_weight"),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("missing_required_inputs", len(missing) == 0, "|".join(missing)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "notes"])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start crash roadway identity assignment doctrine")
    missing = _missing_inputs()
    if missing:
        _write_csv(pd.DataFrame({"missing_input": missing}), "missing_inputs.csv")
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    core = _load_core_identity()
    spatial = _read_csv(CORE_DIR / "crash_spatial_50ft_with_identity_compatibility.csv")
    compatible = _read_csv(CORE_DIR / "crash_identity_compatible_spatial_50ft_assignment.csv")
    identity_only = _read_csv(CORE_DIR / "crash_identity_only_signal_window_candidates.csv")

    spatial_summary = _spatial_summary(spatial)
    identity_summary = _identity_only_summary(identity_only)
    status = _build_status(core, spatial_summary, identity_summary)
    class_summary = _class_summary(status)
    compatible_rollups = _compatible_rollups(compatible)
    fanout = _fanout_compare(status)
    conflict = _conflict_diagnosis(status)
    identity_class = _identity_only_classification(identity_only)
    product_comparison = _product_comparison(status, compatible, identity_only)
    doctrine = _doctrine()
    findings = _findings(status, fanout, conflict, identity_class)
    qa = _qa(missing)

    _write_csv(status, "crash_level_identity_spatial_status.csv")
    _write_csv(class_summary, "crash_level_assignment_class_summary.csv")
    _write_csv(compatible, "identity_compatible_spatial_50ft_assignment_detail.csv")
    _write_csv(compatible_rollups, "identity_compatible_spatial_50ft_rollups.csv")
    _write_csv(fanout, "crash_fanout_spatial_vs_identity_compatible.csv")
    _write_csv(conflict, "crash_row_level_conflict_diagnosis.csv")
    _write_csv(identity_class, "identity_only_candidate_classification.csv")
    _write_csv(product_comparison, "crash_assignment_product_doctrine_comparison.csv")
    _write_csv(doctrine, "crash_roadway_identity_assignment_doctrine.csv")
    _write_text(findings, "crash_roadway_identity_assignment_doctrine_findings.md")
    _write_csv(qa, "crash_roadway_identity_assignment_doctrine_qa.csv")
    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "crash-level roadway identity assignment doctrine and comparison",
        "output_dir": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "crash_level_identity_spatial_status.csv",
            "crash_level_assignment_class_summary.csv",
            "identity_compatible_spatial_50ft_assignment_detail.csv",
            "identity_compatible_spatial_50ft_rollups.csv",
            "crash_fanout_spatial_vs_identity_compatible.csv",
            "crash_row_level_conflict_diagnosis.csv",
            "identity_only_candidate_classification.csv",
            "crash_assignment_product_doctrine_comparison.csv",
            "crash_roadway_identity_assignment_doctrine.csv",
            "crash_roadway_identity_assignment_doctrine_findings.md",
            "crash_roadway_identity_assignment_doctrine_qa.csv",
            "crash_roadway_identity_assignment_doctrine_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "crash_level_rows": int(len(status)),
            "spatial_assigned_crashes": int(status["spatial_50_assigned"].sum()),
            "identity_compatible_spatial_crashes": int((status["identity_compatible_spatial_rows"] > 0).sum()),
            "identity_only_candidate_crashes": int(status["identity_only_candidate"].sum()),
            "identity_compatible_assignment_rows": int(len(compatible)),
        },
        "qa": {
            "review_only": True,
            "spatial_50ft_replaced": False,
            "no_rates_or_models": True,
            "crash_direction_used": False,
        },
    }
    _write_json(manifest, "crash_roadway_identity_assignment_doctrine_manifest.json")
    _checkpoint("complete crash roadway identity assignment doctrine")


if __name__ == "__main__":
    main()
