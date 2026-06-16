from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/crash_roadway_identity_core_integration"

CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")
SENS_DIR = OUTPUT_ROOT / "review/current/crash_travelway_identity_sensitivity"
FEAS_DIR = OUTPUT_ROOT / "review/current/crash_travelway_identity_feasibility"
ASSIGN_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_candidate_assignment"
SANITY_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_sanity_audit"
FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"

PRIMARY_BUFFER_FT = 50
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

CRASH_SOURCE_COLUMNS = [
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
    "geometry",
]

MATCH_COLS = [
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
    "matched_stable_travelway_id_candidates",
    "matched_stable_travelway_id",
    "candidate_travelway_count",
    "candidate_travelway_count_num",
    "match_method",
    "match_confidence",
    "route_key_compatibility",
    "geometry_distance_to_matched_travelway_ft",
    "tier_a_route_measure_status",
]

SPATIAL_COLS = [
    "buffer_width_ft",
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
    "stable_signal_id",
    "source_signal_id",
    "stable_bin_id",
    "stable_travelway_id",
    "final_review_physical_leg_id",
    "final_review_carriageway_subbranch_id",
    "distance_band",
    "analysis_window",
    "final_review_leg_source",
    "final_review_context_status",
    "source_route_name",
    "source_measure_start",
    "source_measure_end",
    "final_review_recovery_provenance",
    "residual_bucket",
    "assignment_fanout_count",
    "unweighted_assignment",
    "source_preserving_weight",
    "assignment_rule",
    "assignment_status",
]

REQUIRED_INPUTS = [
    SENS_DIR / "crash_travelway_identity_match_detail.csv",
    SENS_DIR / "crash_travelway_identity_assignment_candidates.csv",
    SENS_DIR / "crash_travelway_identity_signal_window_candidates.csv",
    SENS_DIR / "crash_spatial_vs_travelway_identity_comparison.csv",
    SENS_DIR / "crash_high_fanout_identity_reduction_audit.csv",
    SENS_DIR / "crash_unassigned_identity_sensitivity_audit.csv",
    SENS_DIR / "crash_travelway_identity_fanout_comparison.csv",
    SENS_DIR / "crash_travelway_identity_method_summary.csv",
    SENS_DIR / "crash_travelway_identity_readiness_decision.csv",
    SENS_DIR / "crash_travelway_identity_sensitivity_manifest.json",
    FEAS_DIR / "crash_field_inventory.csv",
    FEAS_DIR / "travelway_field_inventory.csv",
    FEAS_DIR / "crash_travelway_shared_key_candidates.csv",
    FEAS_DIR / "crash_key_missingness_summary.csv",
    FEAS_DIR / "crash_travelway_candidate_match_detail.csv",
    FEAS_DIR / "crash_travelway_match_method_summary.csv",
    FEAS_DIR / "crash_travelway_match_confidence_summary.csv",
    FEAS_DIR / "crash_travelway_identity_feasibility_manifest.json",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_signal_rollup.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_bin_rollup.csv",
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
    FINAL_LEG_DIR / "final_leg_corrected_context_readiness_summary.csv",
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


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _is_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _collapse(values: pd.Series, limit: int = 10) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _load_crash_geometry_hex() -> tuple[pd.DataFrame, list[str]]:
    schema_cols = list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)
    direction_cols = [col for col in schema_cols if _is_direction_field(col)]
    cols = [col for col in CRASH_SOURCE_COLUMNS if col in schema_cols and not _is_direction_field(col)]
    crashes = pd.read_parquet(CRASH_SOURCE, columns=cols)
    if "DOCUMENT_NBR" in crashes.columns:
        crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    else:
        crashes["stable_crash_id"] = ["crash_review_%09d" % idx for idx in range(len(crashes))]
    if "geometry" in crashes.columns:
        crashes["crash_geometry_wkb_hex"] = crashes["geometry"].map(lambda value: value.hex() if isinstance(value, (bytes, bytearray)) else "")
    else:
        crashes["crash_geometry_wkb_hex"] = ""
    keep = ["stable_crash_id", "crash_geometry_wkb_hex"]
    _checkpoint("load crash geometry hex inventory", len(crashes))
    return crashes[keep], direction_cols


def _load_match() -> pd.DataFrame:
    match = _read_csv(SENS_DIR / "crash_travelway_identity_match_detail.csv", usecols=MATCH_COLS)
    if "candidate_travelway_count_num" not in match.columns:
        match["candidate_travelway_count_num"] = _num(match, "candidate_travelway_count").astype(int)
    match["best_stable_travelway_id"] = _text(match, "matched_stable_travelway_id")
    match.loc[~match["best_stable_travelway_id"].str.startswith("tw_"), "best_stable_travelway_id"] = ""
    return match


def _build_core_identity(match: pd.DataFrame, geometry_hex: pd.DataFrame) -> pd.DataFrame:
    bins = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv", usecols=["stable_travelway_id"])
    represented = set(_text(bins, "stable_travelway_id").loc[_text(bins, "stable_travelway_id").str.startswith("tw_")])
    sw = _read_csv(SENS_DIR / "crash_travelway_identity_signal_window_candidates.csv", usecols=["stable_crash_id", "stable_travelway_id", "stable_signal_id", "analysis_window"])
    sw_summary = sw.groupby("stable_crash_id", dropna=False).agg(
        has_signal_window_candidates=("stable_signal_id", lambda s: True),
        signal_window_candidate_count=("stable_signal_id", "count"),
        signal_window_candidate_signals=("stable_signal_id", "nunique"),
        signal_window_candidate_windows=("analysis_window", "nunique"),
        signal_window_candidate_travelways=("stable_travelway_id", _collapse),
    ).reset_index()
    core = match.merge(geometry_hex, on="stable_crash_id", how="left")
    core = core.merge(sw_summary, on="stable_crash_id", how="left")
    core["has_signal_window_candidates"] = core["has_signal_window_candidates"].fillna(False).astype(bool)
    for col in ["signal_window_candidate_count", "signal_window_candidate_signals", "signal_window_candidate_windows"]:
        core[col] = pd.to_numeric(core[col], errors="coerce").fillna(0).astype(int)
    core["matched_travelway_represented_in_final_scaffold"] = core["best_stable_travelway_id"].isin(represented)
    core["crash_direction_fields_inventory_only"] = ""
    core["crash_direction_used_for_assignment"] = False
    core["crash_direction_use_status"] = "direction_fields_not_read_or_used"
    _checkpoint("build core crash roadway identity table", len(core))
    return core


def _identity_candidate_sets() -> pd.DataFrame:
    sw = _read_csv(
        SENS_DIR / "crash_travelway_identity_signal_window_candidates.csv",
        usecols=["stable_crash_id", "stable_travelway_id", "stable_signal_id", "analysis_window", "candidate_row_count"],
    )
    out = sw.groupby("stable_crash_id", dropna=False).agg(
        identity_candidate_travelway_ids=("stable_travelway_id", _collapse),
        identity_candidate_signal_ids=("stable_signal_id", _collapse),
        identity_candidate_window_values=("analysis_window", _collapse),
        identity_candidate_signal_count=("stable_signal_id", "nunique"),
        identity_candidate_window_count=("analysis_window", "nunique"),
        identity_candidate_row_count=("candidate_row_count", lambda s: pd.to_numeric(s, errors="coerce").sum()),
    ).reset_index()
    _checkpoint("summarize identity signal-window candidate sets", len(out))
    return out


def _load_spatial_50_with_identity(match: pd.DataFrame, candidate_sets: pd.DataFrame) -> pd.DataFrame:
    match_small = match[
        [
            "stable_crash_id",
            "best_stable_travelway_id",
            "matched_stable_travelway_id_candidates",
            "candidate_travelway_count_num",
            "match_method",
            "match_confidence",
            "route_key_compatibility",
            "geometry_distance_to_matched_travelway_ft",
            "tier_a_route_measure_status",
        ]
    ].copy()
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
        dtype=str,
        keep_default_na=False,
        usecols=lambda col: col in SPATIAL_COLS,
        chunksize=200_000,
        low_memory=False,
    ):
        chunk = chunk.loc[pd.to_numeric(chunk["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)].copy()
        if chunk.empty:
            continue
        chunk = chunk.merge(match_small, on="stable_crash_id", how="left")
        chunk = chunk.merge(candidate_sets, on="stable_crash_id", how="left")
        assigned_tw = _text(chunk, "stable_travelway_id")
        best_tw = _text(chunk, "best_stable_travelway_id")
        cand_tw = _text(chunk, "identity_candidate_travelway_ids")
        high_medium = _text(chunk, "match_confidence").isin(["high", "medium"])
        has_best = best_tw.str.startswith("tw_")
        in_candidate = [bool(tw and tw in set(cands.split("|"))) for tw, cands in zip(assigned_tw, cand_tw)]
        in_candidate_s = pd.Series(in_candidate, index=chunk.index)
        ambiguous = _num(chunk, "candidate_travelway_count_num").gt(1) | _text(chunk, "match_confidence").eq("medium")
        chunk["assignment_identity_compatibility"] = np.select(
            [
                high_medium & has_best & assigned_tw.eq(best_tw),
                high_medium & in_candidate_s & ~assigned_tw.eq(best_tw),
                high_medium & ambiguous,
                high_medium & has_best & ~assigned_tw.eq(best_tw),
                ~high_medium | ~has_best,
            ],
            [
                "spatial_assignment_matches_crash_travelway_identity",
                "spatial_assignment_route_measure_compatible",
                "spatial_assignment_identity_ambiguous",
                "spatial_assignment_conflicts_with_crash_travelway_identity",
                "spatial_assignment_no_crash_identity",
            ],
            default="spatial_assignment_identity_ambiguous",
        )
        chunk["identity_compatible_assignment_flag"] = chunk["assignment_identity_compatibility"].isin(
            [
                "spatial_assignment_matches_crash_travelway_identity",
                "spatial_assignment_route_measure_compatible",
                "spatial_assignment_identity_ambiguous",
            ]
        )
        chunk["identity_conflict_flag"] = chunk["assignment_identity_compatibility"].eq(
            "spatial_assignment_conflicts_with_crash_travelway_identity"
        )
        chunks.append(chunk)
    out = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    if not out.empty:
        out["original_spatial_source_preserving_weight"] = _num(out, "source_preserving_weight")
        keep = out.loc[out["identity_compatible_assignment_flag"]].copy()
        counts = keep.groupby("stable_crash_id", dropna=False)["stable_bin_id"].transform("count") if not keep.empty else pd.Series([], dtype=float)
        out["identity_constrained_source_preserving_weight"] = 0.0
        if not keep.empty:
            out.loc[keep.index, "identity_constrained_source_preserving_weight"] = 1.0 / counts.to_numpy(dtype=float)
    _checkpoint("build spatial 50ft with identity compatibility", len(out))
    return out


def _identity_only_candidates(spatial_with_identity: pd.DataFrame) -> pd.DataFrame:
    assigned = set(_text(spatial_with_identity, "stable_crash_id"))
    candidates = _read_csv(SENS_DIR / "crash_travelway_identity_assignment_candidates.csv")
    identity_only = candidates.loc[~_text(candidates, "stable_crash_id").isin(assigned)].copy()
    unassigned = _read_csv(SENS_DIR / "crash_unassigned_identity_sensitivity_audit.csv", usecols=["stable_crash_id", "unassigned_identity_class"])
    identity_only = identity_only.merge(unassigned, on="stable_crash_id", how="left")
    identity_only["identity_only_candidate_class"] = np.select(
        [
            _text(identity_only, "unassigned_identity_class").eq("travelway_identity_within_signal_window_candidate"),
            _text(identity_only, "unassigned_identity_class").str.contains("outside", case=False, na=False),
            _text(identity_only, "match_confidence").eq("low"),
        ],
        [
            "identity_within_signal_window_candidate",
            "identity_represented_travelway_outside_window",
            "identity_low_confidence_only",
        ],
        default="identity_outside_spatial_buffer_candidate",
    )
    identity_only["primary_assignment_flag"] = False
    identity_only["sensitivity_only"] = True
    _checkpoint("build identity-only signal-window candidates", len(identity_only))
    return identity_only


def _fanout_before_after(spatial: pd.DataFrame) -> pd.DataFrame:
    before = spatial.groupby("stable_crash_id", dropna=False).agg(
        before_signal_count=("stable_signal_id", "nunique"),
        before_bin_count=("stable_bin_id", "nunique"),
        before_leg_count=("final_review_physical_leg_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        before_assignment_rows=("stable_bin_id", "count"),
        compatibility_classes=("assignment_identity_compatibility", _collapse),
    ).reset_index()
    compatible = spatial.loc[spatial["identity_compatible_assignment_flag"]].copy()
    after = compatible.groupby("stable_crash_id", dropna=False).agg(
        after_signal_count=("stable_signal_id", "nunique"),
        after_bin_count=("stable_bin_id", "nunique"),
        after_leg_count=("final_review_physical_leg_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        after_assignment_rows=("stable_bin_id", "count"),
        identity_constrained_weight_sum=("identity_constrained_source_preserving_weight", "sum"),
    ).reset_index()
    out = before.merge(after, on="stable_crash_id", how="left")
    for col in ["after_signal_count", "after_bin_count", "after_leg_count", "after_assignment_rows", "identity_constrained_weight_sum"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    out["fanout_reduction_class"] = np.select(
        [
            out["after_assignment_rows"].eq(0),
            out["after_signal_count"].lt(out["before_signal_count"]),
            out["after_signal_count"].eq(out["before_signal_count"]),
            out["after_signal_count"].gt(out["before_signal_count"]),
        ],
        ["all_assignments_removed_by_identity_conflict_or_no_identity", "fanout_reduced", "fanout_unchanged", "fanout_increased"],
        default="no_identity_available",
    )
    _checkpoint("build fanout before/after identity constraint", len(out))
    return out


def _product_comparison(
    spatial: pd.DataFrame,
    compatible: pd.DataFrame,
    identity_only: pd.DataFrame,
) -> pd.DataFrame:
    products = [
        ("spatial_50ft_primary", spatial, "source_preserving_weight"),
        ("identity_compatible_spatial_50ft_subset", compatible, "identity_constrained_source_preserving_weight"),
        ("identity_only_signal_window_candidates", identity_only, None),
    ]
    rows: list[dict[str, Any]] = []
    for product, frame, weight_col in products:
        if frame.empty:
            rows.append({"product": product, "unique_crashes": 0, "assignment_rows": 0})
            continue
        row = {
            "product": product,
            "unique_crashes": int(frame["stable_crash_id"].nunique()),
            "assignment_rows": int(len(frame)),
            "weighted_crash_count": float(_num(frame, weight_col).sum()) if weight_col and weight_col in frame.columns else "",
            "signal_count": int(frame["stable_signal_id"].nunique()) if "stable_signal_id" in frame.columns else "",
            "signal_window_count": int(frame[["stable_signal_id", "analysis_window"]].drop_duplicates().shape[0])
            if {"stable_signal_id", "analysis_window"}.issubset(frame.columns)
            else "",
            "crashes_with_1_signal": int((frame.groupby("stable_crash_id")["stable_signal_id"].nunique() == 1).sum())
            if "stable_signal_id" in frame.columns
            else "",
            "crashes_with_2_signals": int((frame.groupby("stable_crash_id")["stable_signal_id"].nunique() == 2).sum())
            if "stable_signal_id" in frame.columns
            else "",
            "crashes_with_3_signals": int((frame.groupby("stable_crash_id")["stable_signal_id"].nunique() == 3).sum())
            if "stable_signal_id" in frame.columns
            else "",
            "crashes_with_4plus_signals": int((frame.groupby("stable_crash_id")["stable_signal_id"].nunique() >= 4).sum())
            if "stable_signal_id" in frame.columns
            else "",
        }
        rows.append(row)
    union_crashes = set(_text(spatial, "stable_crash_id")) | set(_text(identity_only, "stable_crash_id"))
    rows.append(
        {
            "product": "spatial_plus_identity_union_review_only",
            "unique_crashes": len(union_crashes),
            "assignment_rows": len(spatial) + len(identity_only),
            "weighted_crash_count": "",
            "signal_count": "",
            "signal_window_count": "",
        }
    )
    return pd.DataFrame(rows)


def _doctrine() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "product": "spatial_50ft_primary_geometry_catchment",
                "role": "primary_review_product",
                "use": "review crash assignment from final leg-corrected 50 ft bin-line catchments",
                "not_for": "rates/models without later approved denominator workflow",
            },
            {
                "product": "crash_core_roadway_identity_table",
                "role": "required_carried_crash_reference_field",
                "use": "carry crash RTE_NM/RNS_MP stable_travelway_id identity in crash QA and downstream products",
                "not_for": "standalone signal assignment",
            },
            {
                "product": "identity_compatible_spatial_50ft_subset",
                "role": "standard_sensitivity_product",
                "use": "test spatial assignment robustness after roadway-identity compatibility filtering",
                "not_for": "replacement of spatial 50 ft primary product",
            },
            {
                "product": "identity_only_signal_window_candidates",
                "role": "qa_sensitivity_candidate",
                "use": "explain spatial-unassigned crashes with represented Travelway signal-window evidence",
                "not_for": "primary assignment before map/logic review",
            },
        ]
    )


def _readiness(spatial: pd.DataFrame, compatible: pd.DataFrame, identity_only: pd.DataFrame, fanout: pd.DataFrame) -> pd.DataFrame:
    reduced = int(fanout["fanout_reduction_class"].eq("fanout_reduced").sum())
    all_removed = int(fanout["fanout_reduction_class"].eq("all_assignments_removed_by_identity_conflict_or_no_identity").sum())
    return pd.DataFrame(
        [
            {
                "decision_item": "travelway_identity_required_carried_field",
                "decision": "yes",
                "evidence": "RTE_NM/RNS_MP identity is highly complete and useful for crash QA",
            },
            {
                "decision_item": "identity_compatible_spatial_subset",
                "decision": "ready_as_key_sensitivity_product",
                "evidence": f"compatible_rows={len(compatible):,}; compatible_crashes={compatible['stable_crash_id'].nunique():,}; fanout_reduced_crashes={reduced:,}",
            },
            {
                "decision_item": "identity_only_candidates",
                "decision": "map_review_or_logic_review_before_primary_use",
                "evidence": f"candidate_rows={len(identity_only):,}; candidate_crashes={identity_only['stable_crash_id'].nunique():,}",
            },
            {
                "decision_item": "spatial_50ft_primary_status",
                "decision": "remain_primary_geometry_product",
                "evidence": "identity products constrain/explain spatial assignment but do not replace catchment geometry",
            },
            {
                "decision_item": "identity_filter_caution",
                "decision": "do_not_silently_drop_conflicts",
                "evidence": f"all_assignments_removed_or_no_identity_crashes={all_removed:,}",
            },
        ]
    )


def _qa(direction_cols: list[str], missing: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "outputs written only to review/current/crash_roadway_identity_core_integration"),
        ("no_records_promoted", True, "review-only integration"),
        ("no_rates_or_models", True, "no rates/models calculated"),
        ("no_final_production_crash_assignment_created", True, "identity-compatible outputs are review-only/sensitivity"),
        ("crash_direction_fields_not_used", True, "|".join(direction_cols) if direction_cols else "none detected"),
        ("direction_like_fields_inventory_only", True, "schema inventory only; no direction logic"),
        ("spatial_50ft_not_replaced", True, "spatial 50 ft remains primary product"),
        ("identity_products_review_only", True, "compatibility and identity-only products are sensitivity/QA"),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("missing_required_inputs", len(missing) == 0, "|".join(missing)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "notes"])


def _findings(core: pd.DataFrame, spatial: pd.DataFrame, compatible: pd.DataFrame, identity_only: pd.DataFrame, fanout: pd.DataFrame) -> str:
    conf = core["match_confidence"].value_counts().to_dict()
    compat_counts = spatial["assignment_identity_compatibility"].value_counts().to_dict()
    highfan = _read_csv(SENS_DIR / "crash_high_fanout_identity_reduction_audit.csv", usecols=["stable_crash_id", "high_fanout_identity_class"])
    reduced_high = int(highfan["high_fanout_identity_class"].eq("fanout_reducible_by_travelway_identity").sum())
    still_high = int(highfan["high_fanout_identity_class"].ne("fanout_reducible_by_travelway_identity").sum())
    fanout_reduced = int(fanout["fanout_reduction_class"].eq("fanout_reduced").sum())
    return f"""# Crash Roadway Identity Core Integration

Bounded question: carry crash roadway identity as a core field and create an identity-compatible spatial 50 ft sensitivity product without replacing the spatial 50 ft primary product.

## Findings

1. Core Travelway identity counts: high={conf.get('high', 0):,}, medium={conf.get('medium', 0):,}, low={conf.get('low', 0):,}, none={conf.get('none', 0):,}.
2. Spatial 50 ft assignment rows that match crash roadway identity: {compat_counts.get('spatial_assignment_matches_crash_travelway_identity', 0):,}.
3. Spatial 50 ft assignment rows that conflict with crash roadway identity: {compat_counts.get('spatial_assignment_conflicts_with_crash_travelway_identity', 0):,}.
4. Crashes remaining spatially assigned after identity-compatible filtering: {compatible['stable_crash_id'].nunique():,}.
5. Identity-compatible filtering reduces signal fanout for {fanout_reduced:,} crashes.
6. High-fanout crashes reducible by identity: {reduced_high:,}; high-fanout crashes still requiring corridor/ambiguous/manual treatment: {still_high:,}.
7. Spatially unassigned crashes with identity-only signal-window candidates: {identity_only['stable_crash_id'].nunique():,}.
8. Travelway identity should become a required carried field in crash products.
9. Identity-compatible spatial assignment is ready as a standard sensitivity product, not a replacement primary product.
10. Spatial 50 ft remains the primary crash geometry/catchment product.

## QA

No active outputs were modified. No records were promoted. No rates/models were calculated. No final production crash assignment was created. Crash direction fields were not used. Identity-compatible products are review-only/sensitivity.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start crash roadway identity core integration")
    missing = _missing_inputs()
    if missing:
        _write_csv(pd.DataFrame({"missing_input": missing}), "missing_inputs.csv")
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    geometry_hex, direction_cols = _load_crash_geometry_hex()
    match = _load_match()
    core = _build_core_identity(match, geometry_hex)
    candidate_sets = _identity_candidate_sets()
    spatial = _load_spatial_50_with_identity(match, candidate_sets)
    compatible = spatial.loc[spatial["identity_compatible_assignment_flag"]].copy()
    conflicts = spatial.loc[spatial["identity_conflict_flag"]].copy()
    identity_only = _identity_only_candidates(spatial)
    fanout = _fanout_before_after(spatial)
    comparison = _product_comparison(spatial, compatible, identity_only)
    doctrine = _doctrine()
    readiness = _readiness(spatial, compatible, identity_only, fanout)
    qa = _qa(direction_cols, missing)
    findings = _findings(core, spatial, compatible, identity_only, fanout)

    _write_csv(core, "crash_core_roadway_identity_table.csv")
    _write_csv(spatial, "crash_spatial_50ft_with_identity_compatibility.csv")
    _write_csv(compatible, "crash_identity_compatible_spatial_50ft_assignment.csv")
    _write_csv(conflicts, "crash_identity_conflict_spatial_assignments.csv")
    _write_csv(identity_only, "crash_identity_only_signal_window_candidates.csv")
    _write_csv(fanout, "crash_fanout_before_after_identity_constraint.csv")
    _write_csv(comparison, "crash_assignment_product_comparison.csv")
    _write_csv(doctrine, "crash_roadway_identity_doctrine.csv")
    _write_csv(readiness, "crash_roadway_identity_core_readiness_decision.csv")
    _write_text(findings, "crash_roadway_identity_core_integration_findings.md")
    _write_csv(qa, "crash_roadway_identity_core_integration_qa.csv")

    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "core crash roadway identity integration and identity-constrained crash assignment QA product",
        "output_dir": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "crash_core_roadway_identity_table.csv",
            "crash_spatial_50ft_with_identity_compatibility.csv",
            "crash_identity_compatible_spatial_50ft_assignment.csv",
            "crash_identity_conflict_spatial_assignments.csv",
            "crash_identity_only_signal_window_candidates.csv",
            "crash_fanout_before_after_identity_constraint.csv",
            "crash_assignment_product_comparison.csv",
            "crash_roadway_identity_doctrine.csv",
            "crash_roadway_identity_core_readiness_decision.csv",
            "crash_roadway_identity_core_integration_findings.md",
            "crash_roadway_identity_core_integration_qa.csv",
            "crash_roadway_identity_core_integration_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "core_crash_identity_rows": int(len(core)),
            "spatial_50ft_rows": int(len(spatial)),
            "spatial_50ft_crashes": int(spatial["stable_crash_id"].nunique()),
            "identity_compatible_rows": int(len(compatible)),
            "identity_compatible_crashes": int(compatible["stable_crash_id"].nunique()),
            "identity_conflict_rows": int(len(conflicts)),
            "identity_conflict_crashes": int(conflicts["stable_crash_id"].nunique()),
            "identity_only_candidate_rows": int(len(identity_only)),
            "identity_only_candidate_crashes": int(identity_only["stable_crash_id"].nunique()),
        },
        "qa": {
            "review_only": True,
            "spatial_50ft_replaced": False,
            "no_rates_or_models": True,
            "crash_direction_used": False,
            "direction_fields_inventory_only": direction_cols,
        },
    }
    _write_json(manifest, "crash_roadway_identity_core_integration_manifest.json")
    _checkpoint("complete crash roadway identity core integration")


if __name__ == "__main__":
    main()
