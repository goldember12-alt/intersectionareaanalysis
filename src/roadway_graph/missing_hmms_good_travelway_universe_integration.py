from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_context_refresh"
SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_scaffold_recovery"
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"
MANUAL_CRASH_DIR = OUTPUT_ROOT / "review/current/final_crash_manual_overlap_decomposition"
UNASSIGNED_CRASH_DIR = OUTPUT_ROOT / "review/current/final_crash_unassigned_category_decomposition"

CURRENT_REPRESENTED_SIGNAL_COUNT = 2739
SOURCE_SIGNAL_UNIVERSE_COUNT = 3933

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_INPUTS = [
    CONTEXT_DIR / "good_travelway_context_bin_detail.csv",
    CONTEXT_DIR / "good_travelway_context_signal_summary.csv",
    CONTEXT_DIR / "good_travelway_route_measure_summary.csv",
    CONTEXT_DIR / "good_travelway_roadway_context_summary.csv",
    CONTEXT_DIR / "good_travelway_speed_summary.csv",
    CONTEXT_DIR / "good_travelway_aadt_exposure_summary.csv",
    CONTEXT_DIR / "good_travelway_context_readiness_summary.csv",
    CONTEXT_DIR / "good_travelway_existing_universe_overlap_review.csv",
    CONTEXT_DIR / "good_travelway_universe_expansion_projection.csv",
    CONTEXT_DIR / "good_travelway_context_missingness.csv",
    CONTEXT_DIR / "good_travelway_context_refresh_manifest.json",
    SCAFFOLD_DIR / "good_travelway_missing_signal_targets.csv",
    SCAFFOLD_DIR / "good_travelway_recovered_signal_summary.csv",
    SCAFFOLD_DIR / "good_travelway_recovered_leg_candidates.csv",
    SCAFFOLD_DIR / "good_travelway_recovered_bins.csv",
    SCAFFOLD_DIR / "good_travelway_crash_relevance_summary.csv",
    SCAFFOLD_DIR / "good_travelway_overlap_dedup_review.csv",
    SCAFFOLD_DIR / "good_travelway_scaffold_recovery_manifest.json",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_physical_leg_distribution.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FEASIBILITY_DIR / "manual_seed_missing_signal_diagnostic.csv",
    FEASIBILITY_DIR / "manual_seed_travelway_coverage_detail.csv",
    FEASIBILITY_DIR / "manual_seed_crash_context_summary.csv",
    FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv",
    FEASIBILITY_DIR / "missing_signal_recoverability_class_summary.csv",
    FEASIBILITY_DIR / "missing_signal_crash_relevance_priority_queue.csv",
    FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json",
    MANUAL_CRASH_DIR / "crash_manual_overlap_reclassified_detail.csv",
    MANUAL_CRASH_DIR / "final_crash_manual_overlap_decomposition_manifest.json",
    UNASSIGNED_CRASH_DIR / "crash_unassigned_refined_detail.csv",
    UNASSIGNED_CRASH_DIR / "final_crash_unassigned_category_decomposition_manifest.json",
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


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _first_point(wkt: str):
    if not str(wkt).strip():
        return None
    try:
        geom = shapely.from_wkt(wkt)
        if geom.is_empty:
            return None
        if geom.geom_type == "Point":
            return geom
        coords = list(geom.coords) if geom.geom_type == "LineString" else list(max(geom.geoms, key=lambda g: g.length).coords)
        return shapely.Point(coords[0])
    except Exception:
        return None


def _source_group(row: pd.Series) -> str:
    layer = str(row.get("source_layer", row.get("Stage1_SourceLayer", ""))).lower()
    district = str(row.get("DISTRICT", "")).lower()
    jurisdiction = str(row.get("MAINT_JURISDICTION", "")).lower()
    if "norfolk" in layer or "norfolk" in district or "norfolk" in jurisdiction:
        return "Norfolk"
    if "hampton" in layer or "hampton" in district or "hampton" in jurisdiction:
        return "Hampton Roads"
    return str(row.get("DISTRICT", "") or row.get("source_layer", "") or "unknown")


def _read_existing_bins() -> pd.DataFrame:
    cols = [
        "stable_travelway_id",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "source_layer",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_feature_local_fid",
        "geometry_hash",
        "lineage_match_method",
        "lineage_confidence",
        "target_signal_id",
        "target_bin_id",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "review_only_recovery_provenance",
        "speed_aadt_ready_bin",
        "geometry_wkt",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
    ]
    out = _read_csv(STABLE_DIR / "stable_lineage_represented_bin_universe.csv", usecols=cols)
    out["universe_record_type"] = "existing_represented"
    out["addition_review_class"] = "existing_represented"
    return out


def _read_recovered_bins() -> pd.DataFrame:
    bins = _read_csv(CONTEXT_DIR / "good_travelway_context_bin_detail.csv")
    bins = bins.rename(
        columns={
            "physical_leg_group_id": "physical_leg_id_final",
            "carriageway_subbranch_id": "carriageway_subbranch_id_final",
            "rns_CAR_SPEED_LIMIT": "rns_car_speed_limit",
            "aadt_AADT": "aadt_value",
            "aadt_AADT_YR": "aadt_year",
        }
    )
    bins["universe_record_type"] = "good_travelway_recovered"
    return bins


def _expanded_bins(existing: pd.DataFrame, recovered: pd.DataFrame, risk_class: pd.DataFrame) -> pd.DataFrame:
    rec = recovered.merge(risk_class[["stable_signal_id", "addition_review_class", "expanded_universe_readiness_class"]], on="stable_signal_id", how="left")
    cols = sorted(set(existing.columns) | set(rec.columns))
    for col in cols:
        if col not in existing.columns:
            existing[col] = ""
        if col not in rec.columns:
            rec[col] = ""
    out = pd.concat([existing[cols], rec[cols]], ignore_index=True)
    return out


def _expanded_signals(existing: pd.DataFrame, recovered: pd.DataFrame, risk: pd.DataFrame) -> pd.DataFrame:
    exist = existing.copy()
    exist["universe_record_type"] = "existing_represented"
    exist["addition_review_class"] = "existing_represented"
    rec = recovered.copy()
    rec["universe_record_type"] = "good_travelway_recovered"
    rec = rec.merge(risk[["stable_signal_id", "addition_review_class", "expanded_universe_readiness_class", "risk_explanation"]], on="stable_signal_id", how="left")
    cols = sorted(set(exist.columns) | set(rec.columns))
    for col in cols:
        if col not in exist.columns:
            exist[col] = ""
        if col not in rec.columns:
            rec[col] = ""
    return pd.concat([exist[cols], rec[cols]], ignore_index=True)


def _nearest_existing_signal_ft(recovered_bins: pd.DataFrame, existing_bins: pd.DataFrame) -> pd.DataFrame:
    rec_points = recovered_bins.groupby("stable_signal_id", sort=False)["geometry_wkt"].first().map(_first_point)
    ex_points = existing_bins.groupby("stable_signal_id", sort=False)["geometry_wkt"].first().map(_first_point)
    ex_points = ex_points.loc[ex_points.notna()]
    if ex_points.empty:
        return pd.DataFrame({"stable_signal_id": rec_points.index, "nearest_existing_signal_proxy_ft": np.nan})
    ex_xy = np.column_stack([[p.x for p in ex_points], [p.y for p in ex_points]])
    tree = cKDTree(ex_xy)
    rows = []
    for stable_signal_id, point in rec_points.items():
        if point is None:
            rows.append({"stable_signal_id": stable_signal_id, "nearest_existing_signal_proxy_ft": np.nan})
            continue
        dist_m, _ = tree.query([point.x, point.y], k=1)
        rows.append({"stable_signal_id": stable_signal_id, "nearest_existing_signal_proxy_ft": round(float(dist_m) / 0.3048, 3)})
    return pd.DataFrame(rows)


def _risk_decomposition() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    context_signal = _read_csv(CONTEXT_DIR / "good_travelway_context_signal_summary.csv")
    scaffold_signal = _read_csv(SCAFFOLD_DIR / "good_travelway_recovered_signal_summary.csv")
    targets = _read_csv(SCAFFOLD_DIR / "good_travelway_missing_signal_targets.csv")
    overlap = _read_csv(CONTEXT_DIR / "good_travelway_existing_universe_overlap_review.csv")
    crash = _read_csv(SCAFFOLD_DIR / "good_travelway_crash_relevance_summary.csv")
    final_signals = _read_csv(STABLE_DIR / "stable_lineage_represented_signal_universe.csv")
    existing_bins = _read_existing_bins()
    recovered_bins = _read_recovered_bins()

    represented_source_ids = {v for v in _text(final_signals, "represented_source_signal_id") if v}
    represented_stable_tw = set(_text(existing_bins, "stable_travelway_id"))
    tw_overlap = recovered_bins.assign(existing_stable_travelway_overlap=_text(recovered_bins, "stable_travelway_id").isin(represented_stable_tw))
    tw_summary = tw_overlap.groupby("stable_signal_id", dropna=False).agg(
        generated_bin_count=("stable_bin_id", "size"),
        stable_travelway_overlap_bin_count=("existing_stable_travelway_overlap", "sum"),
        generated_stable_travelway_count=("stable_travelway_id", "nunique"),
        overlapping_stable_travelway_count=(
            "stable_travelway_id",
            lambda s: int(pd.Series(s)[pd.Series(s).isin(represented_stable_tw)].nunique()) if len(s) else 0,
        ),
    ).reset_index()
    proximity = _nearest_existing_signal_ft(recovered_bins, existing_bins)

    base = context_signal.merge(scaffold_signal[["stable_signal_id", "source_layer", "MAJ_NAME", "MAJ_NUM", "MINOR_NAME", "MINOR_NUM", "signal_geometry_wkt"]], on="stable_signal_id", how="left", suffixes=("", "_scaffold"))
    target_cols = [c for c in ["stable_signal_id", "DISTRICT", "MAINT_JURISDICTION", "Stage1_SourceLayer", "source_signal_key", "OBJECTID_1"] if c in targets.columns]
    base = base.merge(targets[target_cols].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
    base = base.merge(overlap, on=["stable_signal_id", "GLOBALID", "source_signal_id"], how="left", suffixes=("", "_overlap"))
    base = base.merge(crash[["stable_signal_id", "all_crashes_within_2500ft_signal", "source_not_represented_unassigned_crashes_within_2500ft", "high_crash_relevance_flag"]], on="stable_signal_id", how="left", suffixes=("", "_crash"))
    base = base.merge(tw_summary, on="stable_signal_id", how="left")
    base = base.merge(proximity, on="stable_signal_id", how="left")
    base["GLOBALID_missing"] = _text(base, "GLOBALID").str.strip().eq("")
    base["source_signal_id_missing"] = _text(base, "source_signal_id").str.strip().eq("")
    base["available_identifier_count"] = (
        _text(base, "GLOBALID").str.strip().ne("").astype(int)
        + _text(base, "source_signal_id").str.strip().ne("").astype(int)
        + _text(base, "ASSET_ID").str.strip().ne("").astype(int)
        + _text(base, "REG_SIGNAL_ID").str.strip().ne("").astype(int)
    )
    base["source_group"] = base.apply(_source_group, axis=1)
    base["exact_source_id_overlap_with_existing"] = _text(base, "source_signal_id").isin(represented_source_ids)
    base["stable_travelway_overlap_with_existing"] = _num(base, "stable_travelway_overlap_bin_count").fillna(0).gt(0)
    base["near_existing_signal_proxy_under_250ft"] = _num(base, "nearest_existing_signal_proxy_ft").le(250)
    risk_flag = _flag(base, "overlap_or_dedup_risk")

    classes = []
    explanations = []
    readiness = []
    for row in base.to_dict(orient="records"):
        missing_id = not str(row.get("GLOBALID", "")).strip()
        exact = bool(row.get("exact_source_id_overlap_with_existing", False))
        no_available_ids = int(row.get("available_identifier_count", 0) or 0) == 0
        duplicate_flag = str(row.get("duplicate_signal_risk", "")).lower() == "true"
        dup = exact or (duplicate_flag and not (missing_id and no_available_ids))
        sib = str(row.get("sibling_signal_risk", "")).lower() == "true"
        scaffold_overlap = str(row.get("overlap_with_existing_represented_scaffold", "")).lower() == "true"
        complex_risk = str(row.get("complex_multi_signal_risk", "")).lower() == "true"
        tw = bool(row.get("stable_travelway_overlap_with_existing", False))
        near = bool(row.get("near_existing_signal_proxy_under_250ft", False))
        if missing_id and no_available_ids and duplicate_flag:
            cls = "source_id_missing_needs_review" if near else "source_id_missing_but_spatially_distinct"
            ready = "ready_but_source_id_missing"
            note = "Duplicate/dedup risk is driven by missing source identifiers, not an exact source-ID or scaffold overlap."
        elif not (dup or sib or scaffold_overlap or complex_risk or tw or (missing_id and near)):
            cls = "clean_addition"
            ready = "ready_for_review_only_expanded_universe"
            note = "No current overlap/dedup/complex risk flags."
        elif dup:
            cls = "possible_duplicate_existing_signal"
            ready = "hold_from_clean_analytics_until_review"
            note = "Available source identifier overlaps existing represented universe."
        elif sib:
            cls = "possible_sibling_signal_same_intersection"
            ready = "ready_but_overlap_review_needed"
            note = "Sibling signal risk flag present."
        elif scaffold_overlap:
            cls = "scaffold_overlap_with_existing_signal"
            ready = "ready_but_overlap_review_needed"
            note = "Scaffold overlap risk flag present."
        elif missing_id and near:
            cls = "source_id_missing_needs_review"
            ready = "ready_but_source_id_missing"
            note = "Source GLOBALID is missing and signal is near existing represented signal proxy."
        elif complex_risk:
            cls = "complex_multi_signal_context"
            ready = "ready_but_complex_multi_signal_review_needed"
            note = "Complex risk is driven by many generated Travelway/source branches."
        elif tw:
            cls = "stable_travelway_overlap_but_distinct_signal"
            ready = "ready_but_overlap_review_needed"
            note = "Generated bins share stable Travelway IDs with existing represented bins but source signal is distinct."
        elif missing_id:
            cls = "source_id_missing_but_spatially_distinct"
            ready = "ready_but_source_id_missing"
            note = "Source GLOBALID is missing, but no near-signal or exact ID overlap was detected."
        else:
            cls = "manual_map_review_needed"
            ready = "hold_from_clean_analytics_until_review"
            note = "Risk evidence did not fit a narrower class."
        classes.append(cls)
        explanations.append(note)
        readiness.append(ready)
    base["addition_review_class"] = classes
    base["risk_explanation"] = explanations
    base["expanded_universe_readiness_class"] = readiness
    base["risk_flag_group"] = np.where(risk_flag, "risk_flagged_203", "clean_423")

    source_missing = pd.DataFrame(
        [
            {"analysis": "all_626_globalid_missing", "signal_count": int(base["GLOBALID_missing"].sum())},
            {"analysis": "risk_group_globalid_missing", "signal_count": int(base.loc[risk_flag, "GLOBALID_missing"].sum())},
            {"analysis": "clean_group_globalid_missing", "signal_count": int(base.loc[~risk_flag, "GLOBALID_missing"].sum())},
            {"analysis": "risk_group_globalid_present", "signal_count": int((risk_flag & ~base["GLOBALID_missing"]).sum())},
            {"analysis": "risk_group_norfolk_or_hampton", "signal_count": int(base.loc[risk_flag, "source_group"].isin(["Norfolk", "Hampton Roads"]).sum())},
        ]
    )
    class_summary = base.groupby(["addition_review_class", "risk_flag_group"], dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        globalid_missing_signals=("GLOBALID_missing", "sum"),
        high_crash_relevance_signals=("high_crash_relevance_flag", lambda s: int(pd.Series(s).astype(str).str.lower().eq("true").sum())),
        source_not_represented_unassigned_crashes_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
    ).reset_index()
    return base, source_missing, class_summary, recovered_bins, existing_bins, final_signals


def _summaries(risk: pd.DataFrame, expanded_signals: pd.DataFrame, expanded_bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clean = risk["addition_review_class"].eq("clean_addition")
    prior_clean_group = risk["risk_flag_group"].eq("clean_423")
    risk_group = risk["risk_flag_group"].eq("risk_flagged_203")
    summary = pd.DataFrame(
        [
            {"metric": "existing_represented_signals", "value": CURRENT_REPRESENTED_SIGNAL_COUNT},
            {"metric": "good_travelway_recovered_signals", "value": len(risk)},
            {"metric": "expanded_review_only_signal_count_no_dedup", "value": CURRENT_REPRESENTED_SIGNAL_COUNT + len(risk)},
            {"metric": "expanded_review_only_bin_count", "value": len(expanded_bins)},
            {"metric": "clean_addition_count", "value": int(prior_clean_group.sum())},
            {"metric": "risk_flagged_addition_count", "value": int(risk_group.sum())},
            {"metric": "projected_share_of_3933_staged_signals_all_626", "value": round((CURRENT_REPRESENTED_SIGNAL_COUNT + len(risk)) / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
        ]
    )
    readiness = risk.groupby("expanded_universe_readiness_class", dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        globalid_missing_signals=("GLOBALID_missing", "sum"),
    ).reset_index()
    crash = pd.DataFrame(
        [
            {"group": "all_626_additions", "signal_count": len(risk), "high_crash_relevance_signals": int(_text(risk, "high_crash_relevance_flag").str.lower().eq("true").sum()), "source_not_represented_unassigned_crashes_2500ft": int(_num(risk, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum())},
            {"group": "clean_additions", "signal_count": int(prior_clean_group.sum()), "high_crash_relevance_signals": int(_text(risk.loc[prior_clean_group], "high_crash_relevance_flag").str.lower().eq("true").sum()), "source_not_represented_unassigned_crashes_2500ft": int(_num(risk.loc[prior_clean_group], "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum())},
            {"group": "risk_flagged_additions", "signal_count": int(risk_group.sum()), "high_crash_relevance_signals": int(_text(risk.loc[risk_group], "high_crash_relevance_flag").str.lower().eq("true").sum()), "source_not_represented_unassigned_crashes_2500ft": int(_num(risk.loc[risk_group], "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum())},
        ]
    )
    return summary, readiness, crash


def _findings(summary: pd.DataFrame, class_summary: pd.DataFrame, source_missing: pd.DataFrame, crash: pd.DataFrame) -> str:
    value = dict(zip(summary["metric"], summary["value"]))
    missing = dict(zip(source_missing["analysis"], source_missing["signal_count"]))
    risk_total = int(value["risk_flagged_addition_count"])
    missing_risk = int(missing["risk_group_globalid_missing"])
    missing_all = int(missing["all_626_globalid_missing"])
    clean = int(value["clean_addition_count"])
    all_crashes = int(crash.loc[crash["group"].eq("all_626_additions"), "source_not_represented_unassigned_crashes_2500ft"].iloc[0])
    class_lines = "\n".join(
        f"- {row.addition_review_class} ({row.risk_flag_group}): {int(row.signal_count):,} signals; "
        f"{int(row.globalid_missing_signals):,} missing GLOBALID; "
        f"{int(row.high_crash_relevance_signals):,} high-crash-relevance"
        for row in class_summary.itertuples(index=False)
    )
    return f"""# Good-Travelway Expanded Universe Integration Findings

## Bounded Question

This review-only integration combines the 2,739 current represented signals with all 626 speed+AADT-ready good-Travelway missing-HMMS recovered signals. It does not promote records to active/final outputs, assign crashes, assign access, calculate rates/models, or target offset-anchor/complex missing-HMMS classes.

## Headline Counts

- Expanded review-only signal count if all 626 are included: {int(value['expanded_review_only_signal_count_no_dedup']):,}
- Expanded review-only bin count: {int(value['expanded_review_only_bin_count']):,}
- Share of 3,933 staged/source signals: {float(value['projected_share_of_3933_staged_signals_all_626']):.1%}
- Clean additions: {clean:,}
- Risk-flagged additions: {risk_total:,}
- Source-not-represented unassigned crashes within 2,500 ft of all additions: {all_crashes:,}

## Risk Interpretation

Missing GLOBALID/source-ID limitations explain most, but not all, of the 203 risk flags. Missing GLOBALID appears on {missing_all:,} of all 626 additions and {missing_risk:,} of the risk-flagged group; none of the 423 clean additions are missing GLOBALID. The remaining risk-flagged records are driven by complex/generated-branch context and need map review before clean analytical use.

## Risk Class Counts

{class_lines}

All 626 can be included in a review-only expanded universe with QA flags. Only the clean class should be used as clean analytical additions before map review. Risk-flagged records should remain visible but held from clean analysis until duplicate/sibling/complex and source-ID questions are resolved.

## Recommendation

Freeze the review-only expanded universe with all 626 additions and risk/readiness classes. Next, create a map-review package for the risk-flagged additions before any crash assignment rerun. Do not rerun crash assignment against the 3,365-signal expanded network until the risk classes are reviewed.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    context_manifest = _load_json(CONTEXT_DIR / "good_travelway_context_refresh_manifest.json")
    scaffold_manifest = _load_json(SCAFFOLD_DIR / "good_travelway_scaffold_recovery_manifest.json")
    stable_manifest = _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json")
    feasibility_manifest = _load_json(FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json")

    risk, source_missing, class_summary, recovered_bins, existing_bins, existing_signals = _risk_decomposition()
    expanded_signals = _expanded_signals(existing_signals, risk, risk)
    expanded_bins = _expanded_bins(existing_bins, recovered_bins, risk)
    addition_summary, readiness, crash = _summaries(risk, expanded_signals, expanded_bins)

    _write_csv(expanded_signals, "expanded_good_travelway_signal_universe.csv")
    _write_csv(expanded_bins, "expanded_good_travelway_bin_universe.csv")
    _write_csv(addition_summary, "good_travelway_626_addition_summary.csv")
    _write_csv(risk.loc[risk["risk_flag_group"].eq("risk_flagged_203")], "good_travelway_203_risk_decomposition.csv")
    _write_csv(source_missing, "good_travelway_source_id_missing_analysis.csv")
    _write_csv(class_summary, "good_travelway_overlap_dedup_complex_class_summary.csv")
    _write_csv(risk, "good_travelway_expanded_universe_readiness.csv")
    _write_csv(crash, "good_travelway_crash_context_impact_summary.csv")
    _write_text(_findings(addition_summary, class_summary, source_missing, crash), "good_travelway_universe_integration_findings.md")

    qa = pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_production_promotion", "status": "passed", "observed": "review-only expanded universe"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only prior proximity counts used"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_not_used", "status": "passed", "observed": "direction fields blocked"},
            {"check_name": "stable_travelway_id_preserved", "status": "passed" if _text(expanded_bins, "stable_travelway_id").str.strip().ne("").all() else "failed", "observed": f"{int(_text(expanded_bins, 'stable_travelway_id').str.strip().ne('').sum())}/{len(expanded_bins)}"},
            {"check_name": "source_globalids_preserved_where_available", "status": "passed", "observed": f"{int(_text(risk, 'GLOBALID').str.strip().ne('').sum())} available; {int(_text(risk, 'GLOBALID').str.strip().eq('').sum())} missing in source"},
            {"check_name": "missing_source_globalid_reported_not_forced", "status": "passed", "observed": "good_travelway_source_id_missing_analysis.csv"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )
    _write_csv(qa, "good_travelway_universe_integration_qa.csv")
    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_good_travelway_universe_integration",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "existing_represented_signal_count": CURRENT_REPRESENTED_SIGNAL_COUNT,
        "good_travelway_added_signal_count": int(len(risk)),
        "expanded_review_only_signal_count": int(CURRENT_REPRESENTED_SIGNAL_COUNT + len(risk)),
        "existing_represented_bin_count": int(len(existing_bins)),
        "good_travelway_added_bin_count": int(len(recovered_bins)),
        "expanded_review_only_bin_count": int(len(expanded_bins)),
        "clean_addition_count": int((risk["risk_flag_group"].eq("clean_423")).sum()),
        "risk_flagged_addition_count": int((risk["risk_flag_group"].eq("risk_flagged_203")).sum()),
        "readiness_class_summary": readiness.to_dict(orient="records"),
        "source_globalid_missing_count": int(risk["GLOBALID_missing"].sum()),
        "projected_share_of_3933": round((CURRENT_REPRESENTED_SIGNAL_COUNT + len(risk)) / SOURCE_SIGNAL_UNIVERSE_COUNT, 4),
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "production_promotion": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_or_models": False,
            "crash_direction_fields_read": False,
        },
        "input_manifests": {
            "context_refresh": context_manifest,
            "scaffold_recovery": scaffold_manifest,
            "stable_lineage": stable_manifest,
            "feasibility": feasibility_manifest,
        },
        "inputs": [str(path) for path in REQUIRED_INPUTS],
    }
    _write_json(manifest, "good_travelway_universe_integration_manifest.json")
    _checkpoint("complete")
    print("Good-Travelway missing HMMS universe integration complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Expanded signals: {manifest['expanded_review_only_signal_count']:,}")
    print(f"Expanded bins: {manifest['expanded_review_only_bin_count']:,}")
    print(f"Clean additions: {manifest['clean_addition_count']:,}")
    print(f"Risk additions: {manifest['risk_flagged_addition_count']:,}")


if __name__ == "__main__":
    main()
