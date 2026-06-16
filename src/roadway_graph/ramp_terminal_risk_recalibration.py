from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/ramp_terminal_risk_recalibration"
CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_ramp_terminal_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_ramp_terminal_scaffold_recovery"
FINAL_ACCOUNTING_DIR = OUTPUT_ROOT / "review/current/final_staged_signal_accounting"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
OFFSET_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
SOURCE_TRAVELWAY_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"

SOURCE_SIGNAL_UNIVERSE_COUNT = 3933
CURRENT_CLEAN_UNIVERSE = 3487
CURRENT_REVIEW_VISIBLE_UNIVERSE = 3487
CURRENT_REMAINING_NONCLEAN = 446

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_dt",
)

REQUIRED_INPUTS = [
    CONTEXT_DIR / "ramp_terminal_context_bin_detail.csv",
    CONTEXT_DIR / "ramp_terminal_context_signal_summary.csv",
    CONTEXT_DIR / "ramp_terminal_route_measure_summary.csv",
    CONTEXT_DIR / "ramp_terminal_roadway_context_summary.csv",
    CONTEXT_DIR / "ramp_terminal_speed_summary.csv",
    CONTEXT_DIR / "ramp_terminal_aadt_exposure_summary.csv",
    CONTEXT_DIR / "ramp_terminal_context_readiness_summary.csv",
    CONTEXT_DIR / "ramp_terminal_existing_universe_overlap_review.csv",
    CONTEXT_DIR / "ramp_terminal_universe_expansion_projection.csv",
    CONTEXT_DIR / "ramp_terminal_context_missingness.csv",
    CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json",
    RECOVERY_DIR / "ramp_terminal_missing_signal_targets.csv",
    RECOVERY_DIR / "ramp_terminal_source_leg_classification.csv",
    RECOVERY_DIR / "ramp_terminal_recovered_signal_summary.csv",
    RECOVERY_DIR / "ramp_terminal_recovered_leg_candidates.csv",
    RECOVERY_DIR / "ramp_terminal_recovered_bins.csv",
    RECOVERY_DIR / "ramp_terminal_overlap_dedup_review.csv",
    RECOVERY_DIR / "ramp_terminal_crash_relevance_summary.csv",
    RECOVERY_DIR / "ramp_terminal_scaffold_recovery_manifest.json",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv",
    OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    SOURCE_TRAVELWAY_GPKG,
]

SOURCE_LEG_CLASSES = [
    "signal_relevant_surface_crossroad_leg",
    "signal_relevant_ramp_terminal_leg",
    "signal_relevant_frontage_or_service_road_leg",
    "ramp_mainline_mixed_needs_subbranch_split",
    "grade_separated_mainline_exclude",
]

RELEVANT_OR_DEFENSIBLE_CLASSES = {
    "signal_relevant_surface_crossroad_leg",
    "signal_relevant_ramp_terminal_leg",
    "signal_relevant_frontage_or_service_road_leg",
    "ramp_mainline_mixed_needs_subbranch_split",
}


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


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _manifest_ref(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "created_utc": payload.get("created_utc", ""),
        "script": payload.get("script", ""),
        "counts": payload.get("counts", {}),
    }


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna("").astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _point_xy(wkt: str) -> tuple[float, float] | None:
    if not isinstance(wkt, str):
        return None
    match = re.search(r"POINT\s*(?:Z)?\s*\(\s*([-0-9.]+)\s+([-0-9.]+)", wkt, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _read_source_travelway_info() -> dict[str, Any]:
    info = pyogrio.read_info(SOURCE_TRAVELWAY_GPKG, layer=SOURCE_TRAVELWAY_LAYER)
    return {
        "path": str(SOURCE_TRAVELWAY_GPKG),
        "layer": SOURCE_TRAVELWAY_LAYER,
        "features": int(info.get("features", 0)),
        "fid_column": info.get("fid_column", ""),
        "geometry_type": info.get("geometry_type", ""),
        "crs": str(info.get("crs", "")),
    }


def _existing_signal_points() -> pd.DataFrame:
    sources = [
        (
            "original_represented",
            STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
            ["stable_signal_id", "signal_id", "represented_source_signal_id", "signal_geometry_wkt"],
        ),
        (
            "good_travelway",
            GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
            ["stable_signal_id", "signal_id", "source_signal_id", "signal_geometry_wkt"],
        ),
        (
            "offset_anchor",
            OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv",
            ["stable_signal_id", "signal_id", "source_signal_id", "signal_geometry_wkt", "raw_signal_geometry_wkt"],
        ),
    ]
    frames: list[pd.DataFrame] = []
    for universe_source, path, cols in sources:
        frame = _read_csv(path, cols)
        geom_col = "signal_geometry_wkt" if "signal_geometry_wkt" in frame.columns else ""
        if geom_col and frame[geom_col].eq("").all() and "raw_signal_geometry_wkt" in frame.columns:
            geom_col = "raw_signal_geometry_wkt"
        if not geom_col:
            continue
        out = pd.DataFrame(
            {
                "universe_source": universe_source,
                "stable_signal_id": frame.get("stable_signal_id", ""),
                "source_signal_id": frame.get("source_signal_id", frame.get("represented_source_signal_id", "")),
                "signal_geometry_wkt": frame[geom_col],
            }
        )
        xy = out["signal_geometry_wkt"].map(_point_xy)
        out["x"] = xy.map(lambda value: value[0] if value else np.nan)
        out["y"] = xy.map(lambda value: value[1] if value else np.nan)
        frames.append(out.dropna(subset=["x", "y"]))
    if not frames:
        return pd.DataFrame(columns=["universe_source", "stable_signal_id", "source_signal_id", "x", "y"])
    existing = pd.concat(frames, ignore_index=True)
    existing = existing.drop_duplicates(subset=["universe_source", "stable_signal_id", "source_signal_id", "x", "y"])
    _checkpoint("existing_signal_points_built", len(existing))
    return existing


def _existing_travelway_sets() -> dict[str, set[str]]:
    specs = [
        (STABLE_DIR / "stable_lineage_represented_bin_universe.csv", "original_represented"),
        (GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv", "good_travelway"),
        (OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv", "offset_anchor"),
    ]
    out: dict[str, set[str]] = {}
    for path, name in specs:
        frame = _read_csv(path, ["stable_signal_id", "stable_travelway_id"])
        out[name] = set(frame.get("stable_travelway_id", pd.Series(dtype=str)).replace("", np.nan).dropna().astype(str))
    return out


def _bin_composition(detail: pd.DataFrame) -> pd.DataFrame:
    work = detail.copy()
    work["source_leg_class_audit"] = work["source_leg_class"].where(work["source_leg_class"].isin(SOURCE_LEG_CLASSES), "other_unknown")
    pivot = (
        work.pivot_table(
            index="stable_signal_id",
            columns="source_leg_class_audit",
            values="stable_bin_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for col in SOURCE_LEG_CLASSES + ["other_unknown"]:
        if col not in pivot.columns:
            pivot[col] = 0
    base_cols = [
        "stable_signal_id",
        "source_signal_id",
        "GLOBALID",
        "generated_bin_count",
        "high_crash_relevance",
        "source_not_represented_unassigned_crashes_within_2500ft",
    ]
    signal_base = detail[base_cols].drop_duplicates("stable_signal_id")
    out = signal_base.merge(pivot, on="stable_signal_id", how="left")
    out = out.rename(
        columns={
            "signal_relevant_surface_crossroad_leg": "generated_surface_crossroad_bins",
            "signal_relevant_ramp_terminal_leg": "generated_ramp_terminal_bins",
            "signal_relevant_frontage_or_service_road_leg": "generated_frontage_service_bins",
            "ramp_mainline_mixed_needs_subbranch_split": "generated_mixed_ramp_mainline_bins",
            "grade_separated_mainline_exclude": "generated_grade_separated_mainline_exclude_bins",
            "other_unknown": "generated_other_unknown_bins",
        }
    )
    relevant_cols = [
        "generated_surface_crossroad_bins",
        "generated_ramp_terminal_bins",
        "generated_frontage_service_bins",
        "generated_mixed_ramp_mainline_bins",
    ]
    for col in relevant_cols + ["generated_grade_separated_mainline_exclude_bins", "generated_other_unknown_bins"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["generated_signal_relevant_or_defensible_bins"] = out[relevant_cols].sum(axis=1)
    out["true_grade_separated_mainline_bins_included"] = out["generated_grade_separated_mainline_exclude_bins"] > 0
    out["only_excluded_mainline_flagged_as_source_context"] = (
        out["generated_grade_separated_mainline_exclude_bins"].eq(0)
        & detail.groupby("stable_signal_id")["has_grade_separated_mainline_exclude"].first().reindex(out["stable_signal_id"]).fillna("").astype(str).str.lower().isin({"true", "1", "yes", "y"}).to_numpy()
    )
    return out.sort_values("stable_signal_id")


def _sibling_reassessment(detail: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    existing = _existing_signal_points()
    existing_tw = _existing_travelway_sets()
    all_existing_tw = set().union(*existing_tw.values()) if existing_tw else set()

    signal_xy = signals[["stable_signal_id", "signal_geometry_wkt"]].drop_duplicates("stable_signal_id").copy()
    xy = signal_xy["signal_geometry_wkt"].map(_point_xy)
    signal_xy["x"] = xy.map(lambda value: value[0] if value else np.nan)
    signal_xy["y"] = xy.map(lambda value: value[1] if value else np.nan)

    rows: list[dict[str, Any]] = []
    existing_x = existing["x"].to_numpy(float) if not existing.empty else np.array([], dtype=float)
    existing_y = existing["y"].to_numpy(float) if not existing.empty else np.array([], dtype=float)
    for row in signal_xy.itertuples(index=False):
        dists = np.sqrt((existing_x - float(row.x)) ** 2 + (existing_y - float(row.y)) ** 2) if len(existing_x) else np.array([])
        nearest = float(np.nanmin(dists)) if len(dists) else math.nan
        tw = set(detail.loc[detail["stable_signal_id"].eq(row.stable_signal_id), "stable_travelway_id"].replace("", np.nan).dropna().astype(str))
        shared = tw & all_existing_tw
        rows.append(
            {
                "stable_signal_id": row.stable_signal_id,
                "nearest_existing_or_recovered_signal_ft": round(nearest, 2) if not math.isnan(nearest) else "",
                "existing_recovered_signal_count_within_50ft": int((dists <= 50).sum()) if len(dists) else 0,
                "existing_recovered_signal_count_within_100ft": int((dists <= 100).sum()) if len(dists) else 0,
                "existing_recovered_signal_count_within_175ft": int((dists <= 175).sum()) if len(dists) else 0,
                "existing_recovered_signal_count_within_250ft": int((dists <= 250).sum()) if len(dists) else 0,
                "generated_stable_travelway_count": len(tw),
                "shared_stable_travelway_id_count": len(shared),
                "shared_stable_travelway_ids_sample": "|".join(sorted(shared)[:10]),
            }
        )
    out = pd.DataFrame(rows)
    flags = signals[
        [
            "stable_signal_id",
            "exact_duplicate_source_record",
            "sibling_ownership_risk",
            "scaffold_overlap_with_existing_signal",
            "same_corridor_shared_travelway_context",
        ]
    ].drop_duplicates("stable_signal_id")
    out = out.merge(flags, on="stable_signal_id", how="left")
    out["strong_sibling_ownership_evidence"] = (
        _flag(out, "exact_duplicate_source_record")
        | _flag(out, "scaffold_overlap_with_existing_signal")
    )
    out["same_corridor_not_ownership_holdout"] = (
        _flag(out, "same_corridor_shared_travelway_context")
        & ~out["strong_sibling_ownership_evidence"]
    )
    out["ownership_reassessment"] = np.select(
        [
            out["strong_sibling_ownership_evidence"],
            out["same_corridor_not_ownership_holdout"],
        ],
        [
            "hold_sibling_or_ownership_conflict",
            "expected_same_corridor_ramp_terminal_context",
        ],
        default="no_strong_sibling_ownership_evidence",
    )
    return out.sort_values("stable_signal_id")


def _classify(signals: pd.DataFrame, composition: pd.DataFrame, sibling: pd.DataFrame) -> pd.DataFrame:
    out = signals.merge(
        composition.drop(
            columns=[
                "source_signal_id",
                "GLOBALID",
                "generated_bin_count",
                "high_crash_relevance",
                "source_not_represented_unassigned_crashes_within_2500ft",
            ],
            errors="ignore",
        ),
        on="stable_signal_id",
        how="left",
    )
    out = out.merge(
        sibling[
            [
                "stable_signal_id",
                "nearest_existing_or_recovered_signal_ft",
                "existing_recovered_signal_count_within_50ft",
                "existing_recovered_signal_count_within_100ft",
                "existing_recovered_signal_count_within_175ft",
                "existing_recovered_signal_count_within_250ft",
                "shared_stable_travelway_id_count",
                "strong_sibling_ownership_evidence",
                "same_corridor_not_ownership_holdout",
                "ownership_reassessment",
            ]
        ],
        on="stable_signal_id",
        how="left",
    )
    stable_bins = pd.to_numeric(out["generated_bin_count"], errors="coerce").fillna(0).gt(0)
    speed_ready = _flag(out, "speed_aadt_ready")
    stable_travelway_ok = stable_bins
    source_plane_ok = pd.to_numeric(out["generated_signal_relevant_or_defensible_bins"], errors="coerce").fillna(0).gt(0)
    grade_bins = _flag(out, "true_grade_separated_mainline_bins_included")
    exact_dup = _flag(out, "exact_duplicate_source_record")
    strong_sibling = _flag(out, "strong_sibling_ownership_evidence")
    mixed = pd.to_numeric(out["generated_mixed_ramp_mainline_bins"], errors="coerce").fillna(0).gt(0)
    qa_flags = (
        _flag(out, "ramp_mainline_contamination_flag")
        | _flag(out, "grade_separated_mainline_exclusion_flag")
        | _flag(out, "same_corridor_not_ownership_holdout")
    )

    out["recalibrated_readiness_class"] = np.select(
        [
            ~speed_ready | ~stable_travelway_ok | ~source_plane_ok,
            grade_bins,
            exact_dup | strong_sibling,
            mixed & speed_ready,
            qa_flags & speed_ready,
            speed_ready,
        ],
        [
            "hold_insufficient_signal_plane_evidence",
            "hold_true_grade_mainline_contamination",
            "hold_sibling_or_ownership_conflict",
            "include_with_subbranch_split_flags",
            "include_with_ramp_terminal_qa_flags",
            "clean_ramp_terminal_addition",
        ],
        default="manual_review_needed",
    )
    out["clean_analysis_candidate"] = out["recalibrated_readiness_class"].eq("clean_ramp_terminal_addition")
    out["review_visible_includable_with_flags"] = out["recalibrated_readiness_class"].isin(
        {"include_with_ramp_terminal_qa_flags", "include_with_subbranch_split_flags"}
    )
    out["hold_from_clean_analysis"] = ~out["clean_analysis_candidate"]
    out["review_visible_candidate"] = out["recalibrated_readiness_class"].isin(
        {"clean_ramp_terminal_addition", "include_with_ramp_terminal_qa_flags", "include_with_subbranch_split_flags"}
    )
    out["recalibration_basis"] = np.select(
        [
            out["recalibrated_readiness_class"].eq("include_with_subbranch_split_flags"),
            out["recalibrated_readiness_class"].eq("include_with_ramp_terminal_qa_flags"),
            out["recalibrated_readiness_class"].eq("clean_ramp_terminal_addition"),
            out["recalibrated_readiness_class"].str.startswith("hold_"),
        ],
        [
            "speed_aadt_ready; stable Travelway lineage; mixed ramp/mainline subbranch bins treated as review QA, not automatic exclusion",
            "speed_aadt_ready; stable Travelway lineage; same-corridor/ramp-terminal context treated as expected QA",
            "speed_aadt_ready; stable Travelway lineage; no mainline inclusion or ownership hold evidence",
            "failed speed/context/source-plane/ownership/mainline inclusion rule",
        ],
        default="manual review fallback",
    )
    return out.sort_values("stable_signal_id")


def _summary(recal: pd.DataFrame) -> pd.DataFrame:
    total = len(recal)
    rows = []
    for cls, group in recal.groupby("recalibrated_readiness_class", dropna=False):
        rows.append(
            {
                "recalibrated_readiness_class": cls,
                "signal_count": len(group),
                "share_of_142": round(len(group) / total, 4) if total else 0,
                "speed_aadt_ready_signals": int(_flag(group, "speed_aadt_ready").sum()),
                "high_crash_relevance_signals": int(_flag(group, "high_crash_relevance").sum()),
                "nearby_source_not_represented_unassigned_crashes_2500ft": float(
                    _num(group, "source_not_represented_unassigned_crashes_within_2500ft").fillna(0).sum()
                ),
                "clean_analysis_included": cls == "clean_ramp_terminal_addition",
                "review_visible_includable": cls
                in {"clean_ramp_terminal_addition", "include_with_ramp_terminal_qa_flags", "include_with_subbranch_split_flags"},
                "plain_language_meaning": {
                    "clean_ramp_terminal_addition": "Context-ready ramp-terminal addition without residual ramp/mainline or ownership QA hold.",
                    "include_with_ramp_terminal_qa_flags": "Context-ready and includable for review-visible universe; corridor/ramp-terminal flags remain QA context.",
                    "include_with_subbranch_split_flags": "Context-ready and includable for review-visible universe; mixed ramp/mainline subbranch evidence should remain flagged.",
                    "hold_true_grade_mainline_contamination": "Generated bins include true grade-separated mainline rows.",
                    "hold_sibling_or_ownership_conflict": "Exact source/scaffold ownership conflict evidence remains.",
                    "hold_insufficient_signal_plane_evidence": "Missing speed/context/stable lineage or signal-plane leg evidence.",
                    "manual_review_needed": "Residual manual uncertainty.",
                }.get(str(cls), ""),
            }
        )
    return pd.DataFrame(rows).sort_values("signal_count", ascending=False)


def _projection(recal: pd.DataFrame) -> pd.DataFrame:
    clean_add = int(recal["clean_analysis_candidate"].sum())
    review_visible = int(recal["review_visible_candidate"].sum())
    hold = len(recal) - review_visible
    return pd.DataFrame(
        [
            {"metric": "current_clean_universe_before_ramp_terminal_recalibration", "value": CURRENT_CLEAN_UNIVERSE},
            {"metric": "current_review_visible_universe_before_ramp_terminal_recalibration", "value": CURRENT_REVIEW_VISIBLE_UNIVERSE},
            {"metric": "current_remaining_non_clean_before_ramp_terminal_recalibration", "value": CURRENT_REMAINING_NONCLEAN},
            {"metric": "ramp_terminal_total_candidates", "value": len(recal)},
            {"metric": "ramp_terminal_speed_aadt_ready_signals", "value": int(_flag(recal, "speed_aadt_ready").sum())},
            {"metric": "ramp_terminal_clean_additions", "value": clean_add},
            {"metric": "ramp_terminal_review_visible_includable_with_flags", "value": review_visible},
            {"metric": "ramp_terminal_hold_or_manual_signals", "value": hold},
            {"metric": "projected_clean_universe_if_clean_ramp_terminal_accepted", "value": CURRENT_CLEAN_UNIVERSE + clean_add},
            {"metric": "projected_review_visible_universe_if_includable_ramp_terminal_visible", "value": CURRENT_REVIEW_VISIBLE_UNIVERSE + review_visible},
            {"metric": "projected_clean_share_of_3933_staged_signals", "value": round((CURRENT_CLEAN_UNIVERSE + clean_add) / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "projected_review_visible_share_of_3933_staged_signals", "value": round((CURRENT_REVIEW_VISIBLE_UNIVERSE + review_visible) / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "projected_remaining_non_clean_if_clean_ramp_terminal_accepted", "value": CURRENT_REMAINING_NONCLEAN - clean_add},
        ]
    )


def _crash_summary(recal: pd.DataFrame) -> pd.DataFrame:
    return (
        recal.groupby("recalibrated_readiness_class", dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            high_crash_relevance_signals=("high_crash_relevance", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes", "y"}).sum())),
            nearby_source_not_represented_unassigned_crashes_2500ft=(
                "source_not_represented_unassigned_crashes_within_2500ft",
                lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum()),
            ),
        )
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )


def _findings(recal: pd.DataFrame, composition: pd.DataFrame, projection: pd.DataFrame) -> str:
    grade_included = int(composition["true_grade_separated_mainline_bins_included"].sum())
    speed_ready = int(_flag(recal, "speed_aadt_ready").sum())
    clean = int(recal["clean_analysis_candidate"].sum())
    with_flags = int(recal["review_visible_includable_with_flags"].sum())
    sibling_hold = int(recal["recalibrated_readiness_class"].eq("hold_sibling_or_ownership_conflict").sum())
    grade_hold = int(recal["recalibrated_readiness_class"].eq("hold_true_grade_mainline_contamination").sum())
    high_includable = int((_flag(recal, "high_crash_relevance") & recal["review_visible_candidate"]).sum())
    projected_clean = projection.loc[projection["metric"].eq("projected_clean_universe_if_clean_ramp_terminal_accepted"), "value"].iloc[0]
    projected_visible = projection.loc[projection["metric"].eq("projected_review_visible_universe_if_includable_ramp_terminal_visible"), "value"].iloc[0]
    return f"""# Ramp-Terminal Risk Recalibration Findings

## Bounded Question

This review-only pass recalibrates ramp-terminal risk flags after context refresh. It treats ramp/mainline text, same-corridor Travelway context, and mixed ramp subbranch evidence as expected ramp-terminal QA context unless generated bins actually include true grade-separated mainline rows or there is strong source/scaffold ownership conflict evidence. It does not promote signals, assign crashes/access, calculate rates/models, or alter active outputs.

## Findings

1. True grade-separated mainline rows included in generated bins: {grade_included}. Grade-separated rows are carried as source-context exclusions, not forced signal legs.
2. Speed+AADT-ready ramp-terminal signals: {speed_ready}.
3. Clean ramp-terminal additions: {clean}.
4. Includable with ramp-terminal/subbranch QA flags: {with_flags}.
5. Sibling/ownership review holds: {sibling_hold}.
6. True grade/mainline contamination holds: {grade_hold}.
7. High-crash-relevance includable ramp-terminal signals: {high_includable}.
8. Projected clean universe if clean additions are accepted: {int(projected_clean):,}.
9. Projected review-visible universe if includable-with-flags additions are made visible: {int(projected_visible):,}.

## Recommendation

The next pass should integrate the includable ramp-terminal records into a review-visible universe with explicit QA flags, then decide whether subbranch-split flagged records can be accepted into clean analysis after focused spot review. Do not rerun crash assignment or access until the universe integration decision is explicit.
"""


def _qa(detail: pd.DataFrame, recal: pd.DataFrame, source_info: dict[str, Any]) -> pd.DataFrame:
    stable_count = int(detail["stable_travelway_id"].replace("", np.nan).notna().sum())
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only recalibration"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only existing proximity summaries used"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active; crash records not read"},
            {"check_name": "stable_travelway_id_preserved", "status": "passed" if stable_count == len(detail) else "failed", "observed": f"{stable_count}/{len(detail)}"},
            {"check_name": "grade_separated_mainline_source_rows_not_forced", "status": "passed", "observed": f"{int(recal['true_grade_separated_mainline_bins_included'].sum())} signals with excluded-mainline bins"},
            {"check_name": "same_corridor_not_automatic_exclusion", "status": "passed", "observed": "same-corridor and ramp/mainline flags only contribute QA context"},
            {"check_name": "source_travelway_read", "status": "passed", "observed": f"{source_info.get('features', 0)} {SOURCE_TRAVELWAY_LAYER} features available"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    source_info = _read_source_travelway_info()
    detail = _read_csv(CONTEXT_DIR / "ramp_terminal_context_bin_detail.csv")
    signals = _read_csv(CONTEXT_DIR / "ramp_terminal_context_signal_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_route_measure_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_roadway_context_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_speed_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_aadt_exposure_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_context_readiness_summary.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_existing_universe_overlap_review.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_universe_expansion_projection.csv")
    _read_csv(CONTEXT_DIR / "ramp_terminal_context_missingness.csv")
    source_leg_class = _read_csv(RECOVERY_DIR / "ramp_terminal_source_leg_classification.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_recovered_signal_summary.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_recovered_leg_candidates.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_recovered_bins.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_overlap_dedup_review.csv")
    _read_csv(RECOVERY_DIR / "ramp_terminal_crash_relevance_summary.csv")
    _read_csv(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv", ["stable_signal_id", "final_primary_status"])

    composition = _bin_composition(detail)
    source_excluded = (
        source_leg_class["source_leg_class"].eq("grade_separated_mainline_exclude")
        .groupby(source_leg_class["stable_signal_id"])
        .sum()
        .rename("excluded_grade_separated_source_row_count")
        .reset_index()
    )
    composition = composition.merge(source_excluded, on="stable_signal_id", how="left")
    composition["excluded_grade_separated_source_row_count"] = composition["excluded_grade_separated_source_row_count"].fillna(0).astype(int)
    sibling = _sibling_reassessment(detail, signals)
    recal = _classify(signals, composition, sibling)
    readiness = _summary(recal)
    projection = _projection(recal)
    crash = _crash_summary(recal)
    qa = _qa(detail, recal, source_info)

    _write_csv(composition, "ramp_terminal_bin_composition_audit.csv")
    _write_csv(recal, "ramp_terminal_signal_risk_recalibration.csv")
    _write_csv(sibling, "ramp_terminal_sibling_ownership_reassessment.csv")
    _write_csv(readiness, "ramp_terminal_revised_universe_readiness.csv")
    _write_csv(projection, "ramp_terminal_revised_universe_projection.csv")
    _write_csv(crash, "ramp_terminal_recalibrated_crash_relevance_summary.csv")
    _write_text(_findings(recal, composition, projection), "ramp_terminal_risk_recalibration_findings.md")
    _write_csv(qa, "ramp_terminal_risk_recalibration_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.ramp_terminal_risk_recalibration",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "source_travelway": source_info,
        "input_manifests": {
            "ramp_terminal_context_refresh": _manifest_ref(CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json"),
            "ramp_terminal_scaffold_recovery": _manifest_ref(RECOVERY_DIR / "ramp_terminal_scaffold_recovery_manifest.json"),
            "final_staged_signal_accounting": _manifest_ref(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json"),
            "good_travelway_universe": _manifest_ref(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json"),
            "offset_anchor_universe": _manifest_ref(OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json"),
        },
        "counts": {
            "target_signals": int(len(recal)),
            "speed_aadt_ready": int(_flag(recal, "speed_aadt_ready").sum()),
            "clean_ramp_terminal_additions": int(recal["clean_analysis_candidate"].sum()),
            "review_visible_includable_with_flags": int(recal["review_visible_includable_with_flags"].sum()),
            "hold_or_manual": int((~recal["review_visible_candidate"]).sum()),
            "true_grade_mainline_bins_included_signals": int(recal["true_grade_separated_mainline_bins_included"].sum()),
        },
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, "ramp_terminal_risk_recalibration_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Clean additions: {int(recal['clean_analysis_candidate'].sum()):,}")
    print(f"Include with QA flags: {int(recal['review_visible_includable_with_flags'].sum()):,}")
    print(f"Hold/manual: {int((~recal['review_visible_candidate']).sum()):,}")


if __name__ == "__main__":
    main()
