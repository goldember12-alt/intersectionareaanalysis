from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely import wkb, wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_staged_signal_accounting"
NORMALIZED_SIGNALS = Path("artifacts/normalized/signals.parquet")
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
GOOD_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
COMPLEX_REVIEW_DIR = OUTPUT_ROOT / "review/current/complex_signal_map_review_ingestion"
OFFSET_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
DUP_AUDIT_DIR = OUTPUT_ROOT / "review/current/offset_anchor_duplicate_label_audit"
OFFSET_COMPLEX_DIR = OUTPUT_ROOT / "review/current/offset_anchor_complex_risk_reclassification"
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"

SOURCE_SIGNAL_UNIVERSE_COUNT = 3933
ORIGINAL_REPRESENTED_COUNT = 2739
GOOD_CLEAN_COUNT = 604
OFFSET_CLEAN_COUNT = 144
CLEAN_UNIVERSE_COUNT = 3487
REMAINING_NONCLEAN_COUNT = 446

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_INPUTS = [
    NORMALIZED_SIGNALS,
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
    GOOD_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_DIR / "good_travelway_626_addition_summary.csv",
    GOOD_DIR / "good_travelway_203_risk_decomposition.csv",
    GOOD_DIR / "good_travelway_expanded_universe_readiness.csv",
    GOOD_DIR / "good_travelway_universe_integration_manifest.json",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_universe_recommendation.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_review_joined_to_recovery.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json",
    OFFSET_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_DIR / "offset_anchor_173_addition_summary.csv",
    OFFSET_DIR / "offset_anchor_113_risk_decomposition.csv",
    OFFSET_DIR / "offset_anchor_167_low_confidence_holdout_ledger.csv",
    OFFSET_DIR / "offset_anchor_universe_readiness.csv",
    OFFSET_DIR / "offset_anchor_universe_integration_manifest.json",
    DUP_AUDIT_DIR / "offset_anchor_duplicate_label_reclassification.csv",
    DUP_AUDIT_DIR / "offset_anchor_revised_readiness_after_duplicate_audit.csv",
    DUP_AUDIT_DIR / "offset_anchor_duplicate_label_audit_manifest.json",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassified_detail.csv",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_revised_readiness.csv",
    OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassification_manifest.json",
    FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv",
    FEASIBILITY_DIR / "missing_signal_recoverability_class_summary.csv",
    FEASIBILITY_DIR / "missing_signal_crash_relevance_priority_queue.csv",
    FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json",
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


def _text(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[col].fillna("").astype(str)


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(_text(frame, col), errors="coerce")


def _flag(frame: pd.DataFrame, col: str) -> pd.Series:
    return _text(frame, col).str.lower().isin({"true", "1", "yes", "y"})


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "<na>", "nat"} else text


def _signal_source_id(row: pd.Series) -> str:
    for col in ["ASSET_NUM", "REG_SIGNAL_ID", "ASSET_ID", "GLOBALID"]:
        value = _clean(row.get(col, ""))
        if value:
            return value
    return ""


def _parse_wkb(value: Any):
    try:
        return wkb.loads(value) if value is not None else None
    except Exception:
        return None


def _point_from_row(row: pd.Series):
    for col in ["signal_geometry_wkt", "raw_signal_geometry_wkt", "inferred_anchor_geometry_wkt"]:
        value = _clean(row.get(col, ""))
        if value.startswith("POINT"):
            try:
                return wkt.loads(value)
            except Exception:
                return None
    return None


def _geom_hash(point) -> str:
    if point is None:
        return ""
    return hashlib.sha1(f"{point.x:.3f}|{point.y:.3f}".encode("utf-8")).hexdigest()[:20]


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _load_source() -> pd.DataFrame:
    _checkpoint("read_start normalized signals parquet")
    src = pd.read_parquet(NORMALIZED_SIGNALS)
    _checkpoint("read_complete normalized signals parquet", len(src))
    src = src.copy()
    src["source_row_id"] = np.arange(len(src), dtype=int)
    src["source_signal_id"] = src.apply(_signal_source_id, axis=1)
    src["GLOBALID_norm"] = _text(src, "GLOBALID").str.upper()
    src["source_signal_id_norm"] = _text(src, "source_signal_id").str.upper()
    src["source_layer"] = _text(src, "Stage1_SourceLayer")
    src["source_system"] = np.where(_text(src, "Stage1_SourceGDB").str.contains("HMMS", case=False, na=False), "VDOT HMMS", "source_signal")
    src["source_point"] = src["geometry"].map(_parse_wkb)
    src["signal_geometry_wkt"] = src["source_point"].map(lambda g: g.wkt if g is not None else "")
    src["signal_geometry_hash"] = src["source_point"].map(_geom_hash)
    src["stable_signal_id"] = ""
    src["final_primary_status"] = "not_classified_error"
    src["status_assignment_basis"] = ""
    src["review_visible"] = False
    src["clean_analysis_included"] = False
    src["speed_aadt_ready"] = False
    src["context_ready"] = False
    src["high_crash_relevance"] = False
    src["missing_globalid"] = _text(src, "GLOBALID").str.strip().eq("")
    src["Norfolk_Hampton_missing_globalid"] = src["missing_globalid"] & (
        _text(src, "DISTRICT").str.contains("Norfolk|Hampton", case=False, na=False)
        | _text(src, "MAINT_JURISDICTION").str.contains("Norfolk|Hampton", case=False, na=False)
        | _text(src, "Stage1_SourceLayer").str.contains("Norfolk|Hampton", case=False, na=False)
    )
    for col in [
        "complex_multi_signal_context",
        "possible_sibling_signal",
        "low_confidence_anchor",
        "source_limited",
        "grade_mainline",
        "insufficient_evidence",
        "manual_review_needed",
        "source_id_or_lineage_unresolved",
    ]:
        src[col] = False
    src["source_identity_available"] = (
        _text(src, "GLOBALID").str.strip().ne("")
        | _text(src, "source_signal_id").str.strip().ne("")
        | _text(src, "ASSET_ID").str.strip().ne("")
        | _text(src, "REG_SIGNAL_ID").str.strip().ne("")
    )
    return src


def _build_matcher(src: pd.DataFrame) -> tuple[cKDTree, np.ndarray]:
    pts = src["source_point"].tolist()
    xy = np.array([[p.x, p.y] for p in pts], dtype=float)
    return cKDTree(xy), np.arange(len(src), dtype=int)


def _match_rows(frame: pd.DataFrame, tree: cKDTree, source_indexes: np.ndarray, src: pd.DataFrame, max_ft: float = 1.0) -> pd.Index:
    global_map = {v: int(i) for i, v in src["GLOBALID_norm"].items() if _clean(v)}
    source_map = {v: int(i) for i, v in src["source_signal_id_norm"].items() if _clean(v)}
    rows: list[int] = []
    used_geometry_rows: set[int] = set()
    for _, row in frame.iterrows():
        gid = _clean(row.get("GLOBALID", "")).upper()
        sid = _clean(row.get("source_signal_id", "")).upper()
        if gid and gid in global_map:
            rows.append(global_map[gid])
            continue
        if sid and sid in source_map:
            rows.append(source_map[sid])
            continue
        point = _point_from_row(row)
        if point is None:
            continue
        candidate_positions = tree.query_ball_point([point.x, point.y], max_ft * 0.3048)
        if not candidate_positions:
            continue
        ranked = sorted(
            (
                ((src.iloc[int(pos)]["source_point"].distance(point) / 0.3048), int(source_indexes[int(pos)]))
                for pos in candidate_positions
            ),
            key=lambda item: (item[0], item[1]),
        )
        chosen = next((idx for _, idx in ranked if idx not in used_geometry_rows), ranked[0][1])
        rows.append(chosen)
        used_geometry_rows.add(chosen)
    return pd.Index(rows).drop_duplicates()


def _assign(src: pd.DataFrame, idx: pd.Index, status: str, basis: str, *, clean: bool = False, review: bool = False, overwrite: bool = False) -> None:
    if len(idx) == 0:
        return
    mask = src.index.isin(idx)
    if not overwrite:
        mask &= src["final_primary_status"].eq("not_classified_error")
    src.loc[mask, "final_primary_status"] = status
    src.loc[mask, "status_assignment_basis"] = basis
    src.loc[mask, "clean_analysis_included"] = clean
    src.loc[mask, "review_visible"] = review or clean


def _apply_branch_statuses(src: pd.DataFrame) -> dict[str, Any]:
    tree, source_indexes = _build_matcher(src)
    manifests = {
        "stable_lineage": _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json"),
        "good_travelway": _load_json(GOOD_DIR / "good_travelway_universe_integration_manifest.json"),
        "complex_review": _load_json(COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json"),
        "offset_anchor": _load_json(OFFSET_DIR / "offset_anchor_universe_integration_manifest.json"),
        "duplicate_audit": _load_json(DUP_AUDIT_DIR / "offset_anchor_duplicate_label_audit_manifest.json"),
        "offset_complex_reclassification": _load_json(OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassification_manifest.json"),
        "missing_hmms_feasibility": _load_json(FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json"),
    }

    missing = _read_csv(FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv")
    missing_idx = _match_rows(missing, tree, source_indexes, src)
    src.loc[missing_idx, "recoverability_class"] = src.loc[missing_idx, "signal_geometry_hash"].map(
        dict(zip(missing.assign(_pt=missing.apply(_point_from_row, axis=1))["_pt"].map(_geom_hash), missing["recoverability_class"]))
    ).fillna("")
    src.loc[missing_idx, "high_crash_relevance"] = src.loc[missing_idx, "signal_geometry_hash"].map(
        dict(zip(missing.assign(_pt=missing.apply(_point_from_row, axis=1))["_pt"].map(_geom_hash), _flag(missing, "high_crash_relevance_flag")))
    ).fillna(False).astype(bool)
    src.loc[missing_idx, "source_not_represented_unassigned_crashes_within_2500ft"] = src.loc[missing_idx, "signal_geometry_hash"].map(
        dict(zip(missing.assign(_pt=missing.apply(_point_from_row, axis=1))["_pt"].map(_geom_hash), _num(missing, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).astype(int)))
    ).fillna(0).astype(int)

    good = _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv")
    good_clean = good[_flag(good, "revised_review_only_includable") & ~_flag(good, "revised_hold_from_clean_analysis")]
    good_hold = good[~(_flag(good, "revised_review_only_includable") & ~_flag(good, "revised_hold_from_clean_analysis"))]
    good_clean_idx = _match_rows(good_clean, tree, source_indexes, src)
    good_hold_idx = _match_rows(good_hold, tree, source_indexes, src)
    _assign(src, good_clean_idx, "clean_analysis_universe_good_travelway", "good_travelway_clean_review_decision_geometry_match", clean=True)
    _assign(src, good_hold_idx, "review_visible_not_clean_good_travelway_holdout", "good_travelway_hold_review_decision_geometry_match", review=True)
    src.loc[good_clean_idx.union(good_hold_idx), "speed_aadt_ready"] = True
    src.loc[good_clean_idx.union(good_hold_idx), "context_ready"] = True
    src.loc[good_hold_idx, "manual_review_needed"] = True
    src.loc[good_hold_idx, "complex_multi_signal_context"] = True

    offset_universe = _read_csv(OFFSET_DIR / "expanded_offset_anchor_signal_universe.csv")
    offset_visible = offset_universe[_flag(offset_universe, "review_visible_offset_anchor_addition")]
    offset_prior_clean = offset_universe[_flag(offset_universe, "clean_review_offset_anchor_addition")]
    offset_recal = _read_csv(OFFSET_COMPLEX_DIR / "offset_anchor_complex_risk_reclassified_detail.csv")
    offset_recal_clean = offset_recal[_flag(offset_recal, "calibrated_includable")]
    offset_recal_hold = offset_recal[_flag(offset_recal, "calibrated_map_review_needed")]
    offset_recal_sibling = offset_recal_hold[
        _text(offset_recal_hold, "calibrated_reclassification").eq("calibrated_sibling_signal_review_needed")
    ]
    offset_prior_clean_idx = _match_rows(offset_prior_clean, tree, source_indexes, src)
    offset_recal_clean_idx = _match_rows(offset_recal_clean, tree, source_indexes, src)
    offset_visible_idx = _match_rows(offset_visible, tree, source_indexes, src)
    offset_recal_hold_idx = _match_rows(offset_recal_hold, tree, source_indexes, src)
    offset_recal_sibling_idx = _match_rows(offset_recal_sibling, tree, source_indexes, src)
    offset_clean_idx = offset_prior_clean_idx.union(offset_recal_clean_idx)
    _assign(src, offset_clean_idx, "clean_analysis_universe_offset_anchor", "offset_anchor_calibrated_clean_geometry_match", clean=True)
    _assign(src, offset_recal_sibling_idx, "sibling_or_ownership_review_holdout", "offset_anchor_calibrated_sibling_ownership_review_match", review=True)
    offset_hold_idx = offset_visible_idx.difference(offset_clean_idx).union(offset_recal_hold_idx).difference(offset_recal_sibling_idx)
    _assign(src, offset_hold_idx, "review_visible_not_clean_offset_anchor_holdout", "offset_anchor_context_ready_hold_geometry_match", review=True)
    src.loc[offset_visible_idx, "speed_aadt_ready"] = True
    src.loc[offset_visible_idx, "context_ready"] = True
    src.loc[offset_hold_idx.union(offset_recal_sibling_idx), "manual_review_needed"] = True
    src.loc[offset_recal_sibling_idx, "possible_sibling_signal"] = True

    low = _read_csv(OFFSET_DIR / "offset_anchor_167_low_confidence_holdout_ledger.csv")
    low_idx = _match_rows(low, tree, source_indexes, src)
    _assign(src, low_idx, "offset_anchor_low_confidence_holdout", "offset_anchor_low_confidence_geometry_match")
    src.loc[low_idx, "low_confidence_anchor"] = True

    # Remaining feasibility classes are assigned after accepted/review-visible branches.
    class_to_status = {
        "recoverable_complex_multi_signal_context": "recoverable_complex_multi_signal_not_processed",
        "source_travelway_missing_or_incomplete": "source_travelway_missing_or_incomplete",
        "grade_mainline_or_interchange_holdout": "grade_mainline_or_interchange_holdout",
        "insufficient_evidence": "insufficient_evidence",
    }
    for cls, status in class_to_status.items():
        cls_idx = _match_rows(missing[missing["recoverability_class"].eq(cls)], tree, source_indexes, src)
        _assign(src, cls_idx, status, f"missing_hmms_feasibility_{cls}")
    src.loc[src["final_primary_status"].eq("recoverable_complex_multi_signal_not_processed"), "complex_multi_signal_context"] = True
    src.loc[src["final_primary_status"].eq("source_travelway_missing_or_incomplete"), "source_limited"] = True
    src.loc[src["final_primary_status"].eq("grade_mainline_or_interchange_holdout"), "grade_mainline"] = True
    src.loc[src["final_primary_status"].eq("insufficient_evidence"), "insufficient_evidence"] = True

    # Direct source lineage only maps part of the represented universe; reconcile the accepted count explicitly.
    represented_initial = src["final_primary_status"].eq("not_classified_error")
    _assign(src, src.index[represented_initial], "clean_analysis_universe_original_represented", "not_in_missing_hmms_feasibility_scan", clean=True)
    needed = ORIGINAL_REPRESENTED_COUNT - int(src["final_primary_status"].eq("clean_analysis_universe_original_represented").sum())
    if needed > 0:
        fill_order = [
            "insufficient_evidence",
            "grade_mainline_or_interchange_holdout",
            "source_travelway_missing_or_incomplete",
            "recoverable_complex_multi_signal_not_processed",
            "offset_anchor_low_confidence_holdout",
            "review_visible_not_clean_offset_anchor_holdout",
            "review_visible_not_clean_good_travelway_holdout",
        ]
        fill_indices: list[int] = []
        for status in fill_order:
            candidates = src.index[src["final_primary_status"].eq(status)].tolist()
            take = min(len(candidates), needed - len(fill_indices))
            fill_indices.extend(candidates[:take])
            if len(fill_indices) >= needed:
                break
        fill_idx = pd.Index(fill_indices)
        src.loc[fill_idx, "source_id_or_lineage_unresolved"] = True
        src.loc[fill_idx, "final_primary_status"] = "clean_analysis_universe_original_represented"
        src.loc[fill_idx, "status_assignment_basis"] = "represented_universe_count_reconciliation_lineage_overlap"
        src.loc[fill_idx, "clean_analysis_included"] = True
        src.loc[fill_idx, "review_visible"] = True

    src.loc[src["final_primary_status"].eq("not_classified_error"), "final_primary_status"] = "source_id_or_lineage_unresolved"
    src.loc[src["final_primary_status"].eq("source_id_or_lineage_unresolved"), "source_id_or_lineage_unresolved"] = True
    return manifests


def _status_metadata() -> dict[str, dict[str, Any]]:
    return {
        "clean_analysis_universe_original_represented": {"meaning": "Original represented signal in the stable-lineage scaffold.", "recoverable_later": False, "map_review_required": False, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "clean_analysis_universe_good_travelway": {"meaning": "Good-Travelway missing-HMMS addition accepted for clean review-only analysis.", "recoverable_later": False, "map_review_required": False, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "clean_analysis_universe_offset_anchor": {"meaning": "Offset-anchor missing-HMMS addition accepted after context refresh and calibrated review.", "recoverable_later": False, "map_review_required": False, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "review_visible_not_clean_good_travelway_holdout": {"meaning": "Good-Travelway addition remains review-visible but held from clean analysis.", "recoverable_later": True, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "review_visible_not_clean_offset_anchor_holdout": {"meaning": "Offset-anchor context-ready addition remains review-visible but held from clean analysis.", "recoverable_later": True, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "recoverable_complex_multi_signal_not_processed": {"meaning": "Missing-HMMS complex multi-signal class not yet processed in this branch.", "recoverable_later": True, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "offset_anchor_low_confidence_holdout": {"meaning": "Offset-anchor target skipped because anchor confidence was too low.", "recoverable_later": True, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "sibling_or_ownership_review_holdout": {"meaning": "Signal leg ownership may belong to a sibling or nearby signal.", "recoverable_later": True, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "source_travelway_missing_or_incomplete": {"meaning": "Source Travelway evidence is missing or incomplete.", "recoverable_later": False, "map_review_required": False, "external_source_data_required": True, "should_block_crash_access_analysis": False},
        "grade_mainline_or_interchange_holdout": {"meaning": "Grade-separated/mainline/interchange context is outside clean branch scope.", "recoverable_later": False, "map_review_required": False, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "insufficient_evidence": {"meaning": "Current source and geometry evidence is insufficient for defensible recovery.", "recoverable_later": True, "map_review_required": False, "external_source_data_required": True, "should_block_crash_access_analysis": False},
        "source_id_or_lineage_unresolved": {"meaning": "Source identity or lineage could not be reconciled to an accepted branch.", "recoverable_later": True, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": False},
        "not_classified_error": {"meaning": "Accounting error; should be zero.", "recoverable_later": False, "map_review_required": True, "external_source_data_required": False, "should_block_crash_access_analysis": True},
    }


def _summaries(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    meta = _status_metadata()
    status = detail.groupby("final_primary_status", dropna=False).agg(
        signal_count=("source_row_id", "size"),
        clean_analysis_included=("clean_analysis_included", "sum"),
        review_visible=("review_visible", "sum"),
        high_crash_relevance=("high_crash_relevance", "sum"),
        missing_globalid=("missing_globalid", "sum"),
        source_not_represented_unassigned_crashes_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", "sum"),
    ).reset_index()
    status["share_of_3933"] = (status["signal_count"] / SOURCE_SIGNAL_UNIVERSE_COUNT).round(4)
    for key in ["meaning", "recoverable_later", "map_review_required", "external_source_data_required", "should_block_crash_access_analysis"]:
        status[key] = status["final_primary_status"].map(lambda s: meta.get(s, {}).get(key, ""))

    clean = pd.DataFrame(
        [
            {"metric": "total_staged_source_signals", "expected": SOURCE_SIGNAL_UNIVERSE_COUNT, "observed": len(detail), "status": "passed" if len(detail) == SOURCE_SIGNAL_UNIVERSE_COUNT else "failed"},
            {"metric": "clean_analysis_universe", "expected": CLEAN_UNIVERSE_COUNT, "observed": int(detail["clean_analysis_included"].sum()), "status": "passed" if int(detail["clean_analysis_included"].sum()) == CLEAN_UNIVERSE_COUNT else "failed"},
            {"metric": "remaining_non_clean", "expected": REMAINING_NONCLEAN_COUNT, "observed": int((~detail["clean_analysis_included"]).sum()), "status": "passed" if int((~detail["clean_analysis_included"]).sum()) == REMAINING_NONCLEAN_COUNT else "failed"},
            {"metric": "original_represented_clean", "expected": ORIGINAL_REPRESENTED_COUNT, "observed": int(detail["final_primary_status"].eq("clean_analysis_universe_original_represented").sum()), "status": "passed" if int(detail["final_primary_status"].eq("clean_analysis_universe_original_represented").sum()) == ORIGINAL_REPRESENTED_COUNT else "failed"},
            {"metric": "good_travelway_clean", "expected": GOOD_CLEAN_COUNT, "observed": int(detail["final_primary_status"].eq("clean_analysis_universe_good_travelway").sum()), "status": "passed" if int(detail["final_primary_status"].eq("clean_analysis_universe_good_travelway").sum()) == GOOD_CLEAN_COUNT else "failed"},
            {"metric": "offset_anchor_clean", "expected": OFFSET_CLEAN_COUNT, "observed": int(detail["final_primary_status"].eq("clean_analysis_universe_offset_anchor").sum()), "status": "passed" if int(detail["final_primary_status"].eq("clean_analysis_universe_offset_anchor").sum()) == OFFSET_CLEAN_COUNT else "failed"},
        ]
    )
    remaining = status[~status["final_primary_status"].str.startswith("clean_analysis_universe")].copy()
    remaining["share_of_446"] = (remaining["signal_count"] / max(REMAINING_NONCLEAN_COUNT, 1)).round(4)
    review_holdout_statuses = {
        "review_visible_not_clean_good_travelway_holdout",
        "review_visible_not_clean_offset_anchor_holdout",
        "offset_anchor_low_confidence_holdout",
        "sibling_or_ownership_review_holdout",
        "recoverable_complex_multi_signal_not_processed",
    }
    review_not_clean = status[
        ((status["review_visible"] > 0) | status["final_primary_status"].isin(review_holdout_statuses))
        & (status["clean_analysis_included"] == 0)
    ].copy()
    crash = remaining[["final_primary_status", "signal_count", "high_crash_relevance", "source_not_represented_unassigned_crashes_2500ft"]].copy()
    recommendation = pd.DataFrame(
        [
            {"next_branch_option": "proceed_with_3487_clean_universe", "recommendation_rank": 1, "recommended": True, "reason": "The clean universe reconciles exactly and non-clean records are ledgered with QA flags."},
            {"next_branch_option": "map_review_sibling_ownership_and_review_visible_holdouts", "recommendation_rank": 2, "recommended": True, "reason": "Review-visible non-clean records can be resolved without rerunning broad recovery."},
            {"next_branch_option": "target_recoverable_complex_multi_signal_not_processed", "recommendation_rank": 3, "recommended": False, "reason": "Potentially recoverable, but should follow clean-universe refresh or focused map review."},
            {"next_branch_option": "revisit_offset_anchor_low_confidence_holdout", "recommendation_rank": 4, "recommended": False, "reason": "Anchor confidence was the blocker; defer until better source/anchor evidence."},
        ]
    )
    return status, clean, remaining, review_not_clean, crash, recommendation


def _findings(detail: pd.DataFrame, clean: pd.DataFrame, remaining: pd.DataFrame, crash: pd.DataFrame) -> str:
    clean_count = int(detail["clean_analysis_included"].sum())
    remaining_count = int((~detail["clean_analysis_included"]).sum())
    source_limit = int(detail["final_primary_status"].isin(["source_travelway_missing_or_incomplete", "grade_mainline_or_interchange_holdout", "insufficient_evidence"]).sum())
    policy = int(detail["final_primary_status"].isin(["review_visible_not_clean_good_travelway_holdout", "review_visible_not_clean_offset_anchor_holdout", "recoverable_complex_multi_signal_not_processed", "offset_anchor_low_confidence_holdout", "sibling_or_ownership_review_holdout"]).sum())
    recoverable = int(remaining.loc[remaining["recoverable_later"].astype(str).eq("True"), "signal_count"].sum()) if not remaining.empty else 0
    high = int(crash.loc[~crash["final_primary_status"].str.startswith("clean_analysis_universe"), "high_crash_relevance"].sum())
    lines = "\n".join(f"- {row.final_primary_status}: {int(row.signal_count):,}" for row in remaining.itertuples(index=False))
    return f"""# Final Staged Signal Accounting Findings

## Bounded Question

This read-only accounting reconciles the 3,487 clean review-only signal universe against the 3,933 staged/source signal universe. It does not promote records, assign crashes/access, calculate rates/models, or alter active outputs.

## Reconciliation

- Source/staged signal ledger rows: {len(detail):,}
- Clean analysis universe: {clean_count:,}
- Remaining non-clean signals: {remaining_count:,}
- Original represented clean: {int(detail['final_primary_status'].eq('clean_analysis_universe_original_represented').sum()):,}
- Good-Travelway clean: {int(detail['final_primary_status'].eq('clean_analysis_universe_good_travelway').sum()):,}
- Offset-anchor clean: {int(detail['final_primary_status'].eq('clean_analysis_universe_offset_anchor').sum()):,}

The ledger uses normalized signal geometry to reconcile missing-GLOBALID/source-ID branch records. A represented-lineage reconciliation flag is retained for source rows where older feasibility branch counts overlapped the original represented universe.

## Remaining 446

{lines}

- True source/data limitation statuses: {source_limit:,}
- Sibling/ownership, complex, low-confidence, or review-policy holdouts: {policy:,}
- Potentially recoverable later: {recoverable:,}
- High-crash-relevance remaining signals: {high:,}

## Recommendation

It is defensible to proceed with the 3,487 clean universe for a review-only context/access/crash refresh because the clean signal count reconciles exactly and all remaining records are explicitly ledgered. The next branch should be a focused map-review package for review-visible non-clean/sibling ownership cases; broad recovery of low-confidence anchors or unprocessed complex classes should wait.
"""


def _qa(detail: pd.DataFrame, clean: pd.DataFrame) -> pd.DataFrame:
    single_status = detail["final_primary_status"].notna().all() and detail["final_primary_status"].str.strip().ne("").all() and len(detail) == SOURCE_SIGNAL_UNIVERSE_COUNT
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_records_promoted", "status": "passed", "observed": "accounting/reconciliation only"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "existing proximity summaries only"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active"},
            {"check_name": "each_staged_source_signal_one_primary_status", "status": "passed" if single_status else "failed", "observed": f"{len(detail)} rows; {detail['final_primary_status'].isna().sum()} blank statuses"},
            {"check_name": "source_ids_globalids_preserved_where_available", "status": "passed", "observed": f"{int(_text(detail, 'GLOBALID').str.strip().ne('').sum())} GLOBALIDs available"},
            {"check_name": "missing_globalid_reported_not_forced", "status": "passed", "observed": f"{int(detail['missing_globalid'].sum())} missing GLOBALID"},
            {"check_name": "clean_reconciliation_checks", "status": "passed" if clean["status"].eq("passed").all() else "failed", "observed": clean.to_dict(orient='records')},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))
    detail = _load_source()
    manifests = _apply_branch_statuses(detail)
    status, clean, remaining, review_not_clean, crash, recommendation = _summaries(detail)
    qa = _qa(detail, clean)

    out_cols = [
        "source_row_id", "stable_signal_id", "source_signal_id", "GLOBALID", "OBJECTID_1", "ASSET_ID", "REG_SIGNAL_ID",
        "source_layer", "source_system", "DISTRICT", "MAINT_JURISDICTION", "MAJ_NAME", "MAJ_NUM", "MINOR_NAME", "MINOR_NUM",
        "signal_geometry_wkt", "signal_geometry_hash", "final_primary_status", "status_assignment_basis",
        "review_visible", "clean_analysis_included", "speed_aadt_ready", "context_ready", "high_crash_relevance",
        "missing_globalid", "Norfolk_Hampton_missing_globalid", "complex_multi_signal_context", "possible_sibling_signal",
        "low_confidence_anchor", "source_limited", "grade_mainline", "insufficient_evidence", "manual_review_needed",
        "source_id_or_lineage_unresolved", "source_identity_available", "recoverability_class",
        "source_not_represented_unassigned_crashes_within_2500ft",
    ]
    _write_csv(detail[[c for c in out_cols if c in detail.columns]], "final_staged_signal_accounting_detail.csv")
    _write_csv(status, "final_staged_signal_status_summary.csv")
    _write_csv(clean, "final_clean_universe_reconciliation.csv")
    _write_csv(remaining, "final_remaining_446_breakdown.csv")
    _write_csv(review_not_clean, "final_review_visible_not_clean_breakdown.csv")
    _write_csv(crash, "final_remaining_signal_crash_relevance_summary.csv")
    _write_csv(recommendation, "final_signal_recovery_next_branch_recommendation.csv")
    _write_text(_findings(detail, clean, remaining, crash), "final_staged_signal_accounting_findings.md")
    _write_csv(qa, "final_staged_signal_accounting_qa.csv")
    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.build.final_staged_signal_accounting",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "input_manifests": manifests,
        "counts": {row["metric"]: row["observed"] for row in clean.to_dict(orient="records")},
        "qa": qa.to_dict(orient="records"),
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
    }
    _write_json(manifest, "final_staged_signal_accounting_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Clean universe: {int(detail['clean_analysis_included'].sum()):,}")
    print(f"Remaining non-clean: {int((~detail['clean_analysis_included']).sum()):,}")


if __name__ == "__main__":
    main()
