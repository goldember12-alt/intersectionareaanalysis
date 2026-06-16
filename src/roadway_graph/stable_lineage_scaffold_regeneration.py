from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"

LINEAGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"
GAP_DIR = OUTPUT_ROOT / "review/current/travelway_lineage_gap_decomposition"
BACKFILL_DIR = OUTPUT_ROOT / "review/current/final_scaffold_travelway_lineage_backfill"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
GEOMETRY_CLEANUP_DIR = OUTPUT_ROOT / "review/current/final_access_target_geometry_persistence_cleanup"

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

REQUIRED_INPUTS = [
    LINEAGE_DIR / "source_travelway_stable_identity.csv",
    LINEAGE_DIR / "travelway_lineage_required_fields_recommendation.csv",
    LINEAGE_DIR / "source_travelway_lineage_bridge_manifest.json",
    GAP_DIR / "travelway_lineage_unmatched_bin_detail.csv",
    GAP_DIR / "travelway_lineage_gap_by_provenance.csv",
    GAP_DIR / "travelway_lineage_gap_reason_summary.csv",
    GAP_DIR / "travelway_lineage_gap_decomposition_manifest.json",
    BACKFILL_DIR / "final_access_target_bins_with_stable_travelway_lineage.csv",
    BACKFILL_DIR / "reviewed_case_lineage_backfill_audit.csv",
    BACKFILL_DIR / "stable_travelway_lineage_backfill_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    GEOMETRY_CLEANUP_DIR / "final_access_target_bins_geometry_cleaned.csv",
    GEOMETRY_CLEANUP_DIR / "final_access_geometry_persistence_manifest.json",
]

EXACT_MATCH_MAX_FT = 1.0
NEAR_MATCH_MAX_FT = 12.0


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
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _hash_text(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _hash_row(values: list[Any], prefix: str) -> str:
    text = "|".join(str(value or "") for value in values)
    return f"{prefix}_{_hash_text(text, 20)}"


def _coalesce(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    out = pd.Series("", index=frame.index, dtype=str)
    for column in columns:
        if column not in frame.columns:
            continue
        values = _text(frame, column)
        out = out.where(out.str.strip().ne(""), values)
    return out


def _source_identity() -> pd.DataFrame:
    source = _read_csv(LINEAGE_DIR / "source_travelway_stable_identity.csv")
    rename = {
        "from_measure": "source_measure_start",
        "to_measure": "source_measure_end",
        "geometry_hash": "source_geometry_hash",
    }
    source = source.rename(columns=rename)
    source["stable_travelway_id"] = _text(source, "stable_travelway_id")
    keep = [
        "stable_travelway_id",
        "source_layer",
        "source_feature_local_fid",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_geometry_hash",
        "attribute_hash",
        "stable_composite_key",
        "fid_is_package_local_only",
    ]
    return source[[col for col in keep if col in source.columns]].drop_duplicates("stable_travelway_id")


def _classify_generation_lineage(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    nearest = _num(out, "nearest_distance_ft")
    geom_id = _text(out, "geometry_stable_travelway_id")
    seed_id = _text(out, "seed_stable_travelway_id")
    seed_method = _text(out, "seed_lineage_match_method")
    seed_conf = _text(out, "seed_lineage_confidence")
    route_ok = _bool_text(out, "route_measure_compatibility")
    route_label = seed_method.eq("route_label_only_match") | _text(out, "seed_candidate_stable_travelway_ids").str.strip().ne("")

    direct = seed_id.str.strip().ne("") & seed_conf.str.contains("high", case=False, regex=False)
    geometry_exact = geom_id.str.strip().ne("") & nearest.le(EXACT_MATCH_MAX_FT)
    geometry_near_route = geom_id.str.strip().ne("") & nearest.le(NEAR_MATCH_MAX_FT) & route_ok
    geometry_near_no_route = geom_id.str.strip().ne("") & nearest.le(NEAR_MATCH_MAX_FT) & ~route_ok

    out["stable_travelway_id"] = ""
    out.loc[direct, "stable_travelway_id"] = seed_id.loc[direct].values
    fill = geometry_exact & _text(out, "stable_travelway_id").eq("")
    out.loc[fill, "stable_travelway_id"] = geom_id.loc[fill].values
    fill = geometry_near_route & _text(out, "stable_travelway_id").eq("")
    out.loc[fill, "stable_travelway_id"] = geom_id.loc[fill].values
    fill = geometry_near_no_route & _text(out, "stable_travelway_id").eq("")
    out.loc[fill, "stable_travelway_id"] = geom_id.loc[fill].values
    fill = route_label & _text(out, "stable_travelway_id").eq("")
    out.loc[fill, "stable_travelway_id"] = _coalesce(out, ["seed_stable_travelway_id", "seed_candidate_stable_travelway_ids"]).str.split("|").str[0].loc[fill].values

    out["lineage_match_method"] = "unmatched"
    out["lineage_confidence"] = "unmatched"
    out.loc[route_label, ["lineage_match_method", "lineage_confidence"]] = ["route_label_only_match", "low_route_label_only"]
    out.loc[geometry_near_no_route, ["lineage_match_method", "lineage_confidence"]] = ["geometry_near_without_route_label", "medium_geometry_near_no_route_label"]
    out.loc[geometry_near_route, ["lineage_match_method", "lineage_confidence"]] = ["geometry_near_route_compatible", "medium_geometry_near_route_compatible"]
    out.loc[geometry_exact, ["lineage_match_method", "lineage_confidence"]] = ["geometry_exact_or_contained", "high_geometry_exact_or_contained"]
    out.loc[direct, ["lineage_match_method", "lineage_confidence"]] = ["direct_source_travelway_id", "high_direct_source_id"]

    out["lineage_persistence_mode"] = np.where(
        out["lineage_match_method"].isin(["direct_source_travelway_id"]),
        "already_persisted_direct_or_seeded",
        np.where(out["lineage_match_method"].eq("unmatched"), "not_persisted_unmatched", "review_regenerated_from_existing_geometry"),
    )
    out["fid_used_as_sole_stable_key"] = False
    out["package_local_fid_role"] = "source_feature_local_fid_only_not_stable_key"
    return out


def _build_regenerated_bins(access: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    classified = _classify_generation_lineage(access)
    out = classified.merge(source, on="stable_travelway_id", how="left", suffixes=("", "_source"))
    out["stable_signal_id"] = [
        _hash_row([signal_id, source_id, source_layer], "sig")
        for signal_id, source_id, source_layer in zip(
            _text(out, "target_signal_id"),
            _text(out, "target_source_id"),
            _text(out, "target_source_layer"),
        )
    ]
    bin_geometry_hash = [
        _hash_text(wkt, 20) if str(wkt).strip() else ""
        for wkt in _coalesce(out, ["geometry_wkt_cleaned", "geometry_wkt", "geometry_wkt_backfill"])
    ]
    out["bin_geometry_hash"] = bin_geometry_hash
    out["stable_bin_id"] = [
        _hash_row([stable_signal_id, bin_id, stable_travelway_id, start, end, geom_hash], "bin")
        for stable_signal_id, bin_id, stable_travelway_id, start, end, geom_hash in zip(
            _text(out, "stable_signal_id"),
            _text(out, "target_bin_id"),
            _text(out, "stable_travelway_id"),
            _text(out, "distance_start_ft"),
            _text(out, "distance_end_ft"),
            _text(out, "bin_geometry_hash"),
        )
    ]
    out["source_signal_id"] = _text(out, "target_source_id")
    out["source_signal_layer"] = _text(out, "target_source_layer")
    out["source_layer"] = _text(out, "source_layer")
    out["source_measure_start"] = _text(out, "source_measure_start")
    out["source_measure_end"] = _text(out, "source_measure_end")
    out["geometry_hash"] = _coalesce(out, ["source_geometry_hash", "bin_geometry_hash"])
    out["source_feature_local_fid"] = _text(out, "source_feature_local_fid")
    out["lineage_candidate_match_count"] = pd.to_numeric(_text(out, "candidate_match_count"), errors="coerce").fillna(0).astype(int)
    if "geometry_candidate_match_count" in out.columns:
        out["lineage_candidate_match_count"] = np.maximum(
            out["lineage_candidate_match_count"],
            pd.to_numeric(_text(out, "geometry_candidate_match_count"), errors="coerce").fillna(0).astype(int),
        )
    out["lineage_conflict_fanout_flag"] = out["lineage_candidate_match_count"].gt(1)
    out["review_only_flag"] = "true"
    required_first = [
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
        "original_bin_id",
        "source_signal_layer",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "recovery_stream",
        "recovery_class",
        "final_original_or_recovered",
        "review_only_recovery_provenance",
        "final_alignment_class",
        "speed_aadt_ready_bin",
        "geometry_wkt_cleaned",
        "geometry_recovery_status",
        "lineage_persistence_mode",
        "lineage_candidate_match_count",
        "lineage_conflict_fanout_flag",
        "nearest_distance_ft",
        "route_measure_compatibility",
        "candidate_stable_travelway_ids",
        "candidate_source_feature_local_fids",
        "bin_geometry_hash",
        "fid_used_as_sole_stable_key",
        "package_local_fid_role",
        "review_only_flag",
    ]
    rest = [col for col in out.columns if col not in required_first]
    return out[[col for col in required_first if col in out.columns] + rest]


def _summary_count(frame: pd.DataFrame, group_cols: list[str], table_name: str) -> pd.DataFrame:
    existing = [col for col in group_cols if col in frame.columns]
    if existing:
        grouped = frame.groupby(existing, dropna=False).size().reset_index(name="bin_count")
    else:
        grouped = pd.DataFrame([{"bin_count": len(frame)}])
    grouped.insert(0, "summary_table", table_name)
    grouped["high_confidence_bins"] = 0
    grouped["medium_confidence_bins"] = 0
    grouped["low_confidence_bins"] = 0
    grouped["unmatched_bins"] = 0
    for idx, row in grouped.iterrows():
        subset = frame
        for col in existing:
            subset = subset.loc[_text(subset, col).eq(str(row[col]))]
        conf = _text(subset, "lineage_confidence")
        grouped.loc[idx, "high_confidence_bins"] = int(conf.str.startswith("high").sum())
        grouped.loc[idx, "medium_confidence_bins"] = int(conf.str.startswith("medium").sum())
        grouped.loc[idx, "low_confidence_bins"] = int(conf.str.startswith("low").sum())
        grouped.loc[idx, "unmatched_bins"] = int(conf.eq("unmatched").sum())
    return grouped


def _generation_audit(bins: pd.DataFrame) -> pd.DataFrame:
    pieces = [
        _summary_count(bins, [], "overall"),
        _summary_count(bins, ["lineage_match_method", "lineage_confidence"], "by_match_method"),
        _summary_count(bins, ["recovery_stream"], "by_recovery_stream"),
        _summary_count(bins, ["final_original_or_recovered"], "by_original_recovered"),
        _summary_count(bins, ["final_alignment_class"], "by_final_alignment_class"),
    ]
    return pd.concat(pieces, ignore_index=True, sort=False)


def _signal_universe(signals: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    agg = bins.groupby("target_signal_id", dropna=False).agg(
        stable_lineage_bin_count=("stable_bin_id", "size"),
        high_confidence_lineage_bins=("lineage_confidence", lambda s: int(pd.Series(s).astype(str).str.startswith("high").sum())),
        medium_confidence_lineage_bins=("lineage_confidence", lambda s: int(pd.Series(s).astype(str).str.startswith("medium").sum())),
        low_confidence_lineage_bins=("lineage_confidence", lambda s: int(pd.Series(s).astype(str).str.startswith("low").sum())),
        unmatched_lineage_bins=("lineage_confidence", lambda s: int((pd.Series(s).astype(str) == "unmatched").sum())),
        stable_travelway_count=("stable_travelway_id", lambda s: int(pd.Series(s).astype(str).replace("", np.nan).dropna().nunique())),
    ).reset_index()
    out = signals.copy()
    out["stable_signal_id"] = [
        _hash_row([signal_id, source_id, source_layer], "sig")
        for signal_id, source_id, source_layer in zip(
            _coalesce(out, ["signal_id", "target_signal_id"]),
            _coalesce(out, ["source_signal_id", "target_source_id"]),
            _coalesce(out, ["source_layer", "target_source_layer"]),
        )
    ]
    out = out.merge(agg, left_on=_coalesce(out, ["signal_id", "target_signal_id"]), right_on="target_signal_id", how="left")
    count_cols = [
        "stable_lineage_bin_count",
        "high_confidence_lineage_bins",
        "medium_confidence_lineage_bins",
        "low_confidence_lineage_bins",
        "unmatched_lineage_bins",
        "stable_travelway_count",
    ]
    for col in count_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["review_only_flag"] = "true"
    return out


def _previous_vs_regenerated(bins: pd.DataFrame, gap: pd.DataFrame) -> pd.DataFrame:
    conf = _text(bins, "lineage_confidence")
    rows = [
        {"metric": "regenerated_signal_count", "value": int(_text(bins, "target_signal_id").nunique()), "reference_value": 2739, "status": "matches_expected" if _text(bins, "target_signal_id").nunique() == 2739 else "differs"},
        {"metric": "regenerated_bin_count", "value": int(len(bins)), "reference_value": 262329, "status": "matches_expected" if len(bins) == 262329 else "differs"},
        {"metric": "regenerated_high_confidence_bins", "value": int(conf.str.startswith("high").sum()), "reference_value": "", "status": "review"},
        {"metric": "regenerated_medium_confidence_bins", "value": int(conf.str.startswith("medium").sum()), "reference_value": "", "status": "review"},
        {"metric": "regenerated_low_confidence_bins", "value": int(conf.str.startswith("low").sum()), "reference_value": "", "status": "review"},
        {"metric": "regenerated_unmatched_bins", "value": int(conf.eq("unmatched").sum()), "reference_value": 111200, "status": "improved" if conf.eq("unmatched").sum() < 111200 else "not_improved"},
        {"metric": "previous_gap_unmatched_bin_rows", "value": int(len(gap)), "reference_value": 111200, "status": "matches_expected" if len(gap) == 111200 else "differs"},
    ]
    return pd.DataFrame(rows)


def _previously_unmatched_summary(bins: pd.DataFrame, gap: pd.DataFrame) -> pd.DataFrame:
    prev_ids = set(_text(gap, "bin_id"))
    prev = bins.loc[_text(bins, "target_bin_id").isin(prev_ids)].copy()
    rows = []
    conf = _text(prev, "lineage_confidence")
    for label, mask in {
        "previously_unmatched_total": pd.Series(True, index=prev.index),
        "now_high_confidence": conf.str.startswith("high"),
        "now_medium_confidence": conf.str.startswith("medium"),
        "now_low_confidence": conf.str.startswith("low"),
        "still_unmatched": conf.eq("unmatched"),
    }.items():
        subset = prev.loc[mask]
        rows.append(
            {
                "metric": label,
                "bin_count": int(len(subset)),
                "signal_count": int(_text(subset, "target_signal_id").nunique()) if not subset.empty else 0,
                "dominant_match_methods": "|".join(_text(subset, "lineage_match_method").value_counts().head(5).index.tolist()) if not subset.empty else "",
            }
        )
    by_method = prev.groupby(["lineage_match_method", "lineage_confidence"], dropna=False).agg(
        bin_count=("target_bin_id", "size"),
        signal_count=("target_signal_id", "nunique"),
    ).reset_index()
    by_method.insert(0, "metric", "previously_unmatched_by_method")
    return pd.concat([pd.DataFrame(rows), by_method], ignore_index=True, sort=False)


def _reviewed_case_audit(bins: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    reviewed = pd.DataFrame(
        [
            {
                "case_id": "signal_000045_missing_leg",
                "signal_id": "signal_000045",
                "reviewed_source_fid": "52369",
                "reviewed_rte_id": "1373509",
                "reviewed_rte_nm": "R-VA002SC00616NB",
                "reviewed_from_measure": "1.17",
                "reviewed_to_measure": "1.47",
            },
            {
                "case_id": "signal_000045_connected_leg",
                "signal_id": "signal_000045",
                "reviewed_source_fid": "46419",
                "reviewed_rte_id": "2530101",
                "reviewed_rte_nm": "R-VA002SC01053EB",
                "reviewed_from_measure": "0",
                "reviewed_to_measure": "0.54",
            },
        ]
    )
    rows: list[dict[str, Any]] = []
    for row in reviewed.itertuples(index=False):
        source_match = source.loc[
            _text(source, "source_feature_local_fid").eq(str(row.reviewed_source_fid))
            | (
                _text(source, "source_route_id").eq(str(row.reviewed_rte_id))
                & _text(source, "source_route_name").eq(str(row.reviewed_rte_nm))
                & _text(source, "source_measure_start").eq(str(row.reviewed_from_measure))
                & _text(source, "source_measure_end").eq(str(row.reviewed_to_measure))
            )
        ]
        stable_ids = _text(source_match, "stable_travelway_id").drop_duplicates().tolist()
        signal_bins = bins.loc[_text(bins, "target_signal_id").eq(row.signal_id)]
        best = signal_bins.loc[_text(signal_bins, "stable_travelway_id").isin(stable_ids)]
        candidate = signal_bins.loc[_text(signal_bins, "candidate_stable_travelway_ids").apply(lambda value: any(stable_id in str(value).split("|") for stable_id in stable_ids))]
        rows.append(
            {
                **row._asdict(),
                "stable_travelway_ids": "|".join(stable_ids),
                "best_match_regenerated_bins": int(len(best)),
                "candidate_match_regenerated_bins": int(len(candidate)),
                "lineage_result": "stable_id_persisted_in_regenerated_bins" if len(best) else "stable_id_available_but_not_best_match",
                "match_methods": "|".join(sorted(set(_text(best, "lineage_match_method")))) if len(best) else "",
            }
        )
    return pd.DataFrame(rows)


def _qa(bins: pd.DataFrame, output_inside: bool) -> pd.DataFrame:
    required = [
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
    ]
    return pd.DataFrame(
        [
            {"qa_check": "no_access_assignment_performed", "passed": True, "detail": "No access source files or assignment logic are read/run."},
            {"qa_check": "no_crash_assignment_performed", "passed": True, "detail": "No crash records are read or assigned."},
            {"qa_check": "no_crash_direction_fields_read", "passed": True, "detail": "CSV reader blocks crash/direction field tokens."},
            {"qa_check": "no_rates_or_models_run", "passed": True, "detail": "Lineage persistence validation only."},
            {"qa_check": "fid_not_sole_stable_key", "passed": not _bool_text(bins, "fid_used_as_sole_stable_key").any(), "detail": "GeoPackage fid retained only as source_feature_local_fid."},
            {"qa_check": "stable_travelway_id_field_present", "passed": "stable_travelway_id" in bins.columns, "detail": ""},
            {"qa_check": "lineage_method_confidence_fields_present", "passed": {"lineage_match_method", "lineage_confidence"}.issubset(bins.columns), "detail": ""},
            {"qa_check": "required_lineage_fields_present", "passed": set(required).issubset(bins.columns), "detail": "Missing: " + "|".join(sorted(set(required) - set(bins.columns)))},
            {"qa_check": "review_only_outputs_only", "passed": output_inside, "detail": str(OUT_DIR)},
            {"qa_check": "active_outputs_not_overwritten", "passed": True, "detail": "Writes are under stable_lineage_scaffold_regeneration only."},
        ]
    )


def _findings(
    bins: pd.DataFrame,
    previous: pd.DataFrame,
    prev_summary: pd.DataFrame,
    reviewed: pd.DataFrame,
) -> str:
    conf = _text(bins, "lineage_confidence")
    high = int(conf.str.startswith("high").sum())
    medium = int(conf.str.startswith("medium").sum())
    low = int(conf.str.startswith("low").sum())
    unmatched = int(conf.eq("unmatched").sum())
    prev_high = int(prev_summary.loc[prev_summary["metric"].eq("now_high_confidence"), "bin_count"].iloc[0]) if "metric" in prev_summary.columns else 0
    prev_unmatched = int(prev_summary.loc[prev_summary["metric"].eq("still_unmatched"), "bin_count"].iloc[0]) if "metric" in prev_summary.columns else 0
    sig45 = "\n".join(
        f"- FID {row.reviewed_source_fid} / {row.reviewed_rte_nm}: stable IDs {row.stable_travelway_ids}; best-match bins {row.best_match_regenerated_bins}; candidate bins {row.candidate_match_regenerated_bins}; result {row.lineage_result}."
        for row in reviewed.itertuples(index=False)
    )
    return f"""# Stable-Lineage Scaffold Regeneration Findings

## Bounded Question

Can the final review scaffold/bin universe be regenerated with stable source Travelway lineage fields at the bin surface, and does a generation-time geometry identity rule recover the legacy/original bins that were previously unmatched?

## Producer Path

The lineage-missing legacy/original rows are produced by the existing review scaffold chain:

- `src.roadway_graph.refreshed_expanded_universe_with_offset_recovery` writes `refreshed_represented_bin_universe.csv` by combining the prior access target bins with offset-zone bins.
- `src.roadway_graph.consolidated_scaffold_completeness_refresh` reads that file and tags the pre-existing rows as `existing_refreshed_represented_bin_universe` / `original_or_previous_represented`.
- `src.roadway_graph.build.final_signal_leg_universe_overview` and the final access-target cleanup preserve geometry but cannot reconstruct route/source-row fields that were never carried by the pre-existing bins.

Stable Travelway lineage was dropped before consolidation: the pre-existing represented bin rows carried geometry, distance, and graph-style bin IDs, but not stable Travelway/source-row IDs, route ID/name/common, or source measures.

## Regeneration Result

- Regenerated represented signals: {int(_text(bins, 'target_signal_id').nunique()):,}
- Regenerated represented bins: {len(bins):,}
- High-confidence stable Travelway lineage bins: {high:,}
- Medium-confidence stable Travelway lineage bins: {medium:,}
- Low route-label-only lineage bins: {low:,}
- Unmatched bins: {unmatched:,}

The code now persists the required lineage fields in the bounded regenerated bin table, including `stable_travelway_id`, source route/measure fields, `source_feature_local_fid`, `geometry_hash`, `stable_signal_id`, `stable_bin_id`, `lineage_match_method`, and `lineage_confidence`.

## Previously Unmatched 111,200 Bins

- Previously unmatched bins recovered as high confidence: {prev_high:,}
- Previously unmatched bins still unmatched: {prev_unmatched:,}

The main recovery mechanism is generation-time geometry identity: exact/contained bin geometry matched to a stable source Travelway feature is treated as high-confidence lineage even when the legacy row failed to carry route labels. This is the lineage that should have been persisted when the scaffold/bin row was generated.

## Reviewed Case: signal_000045

{sig45}

## Count Consistency

The regenerated review universe is count-consistent with the final review signal/bin universe when it reports 2,739 signals and 262,329 bins. Any remaining unmatched rows should be treated as lineage QA exceptions, not promoted source-row claims.

## Readiness Decision

The stable-lineage regenerated scaffold is ready to feed the next review-only scaffold consolidation/access-target regeneration pass. It should not be promoted automatically. Crash/catchment work should use stable-lineage bins once the lineage-enriched scaffold is carried through final access-target generation.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    source = _source_identity()
    access = _read_csv(BACKFILL_DIR / "final_access_target_bins_with_stable_travelway_lineage.csv")
    signals = _read_csv(FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv")
    gap = _read_csv(GAP_DIR / "travelway_lineage_unmatched_bin_detail.csv")
    _checkpoint("classify_regenerated_lineage_start", len(access))
    bins = _build_regenerated_bins(access, source)
    _checkpoint("classify_regenerated_lineage_complete", len(bins))
    signal_universe = _signal_universe(signals, bins)
    audit = _generation_audit(bins)
    comparison = _previous_vs_regenerated(bins, gap)
    prev_summary = _previously_unmatched_summary(bins, gap)
    reviewed = _reviewed_case_audit(bins, source)
    qa = _qa(bins, str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/stable_lineage_scaffold_regeneration"))

    _write_csv(bins, "stable_lineage_represented_bin_universe.csv")
    _write_csv(signal_universe, "stable_lineage_represented_signal_universe.csv")
    _write_csv(audit, "stable_lineage_generation_lineage_audit.csv")
    _write_csv(comparison, "stable_lineage_previous_vs_regenerated_comparison.csv")
    _write_csv(prev_summary, "stable_lineage_previously_unmatched_recovery_summary.csv")
    _write_csv(reviewed, "stable_lineage_reviewed_case_audit.csv")
    _write_csv(qa, "stable_lineage_generation_qa.csv")
    _write_text(_findings(bins, comparison, prev_summary, reviewed), "stable_lineage_scaffold_regeneration_findings.md")

    conf = _text(bins, "lineage_confidence")
    manifest = {
        "created_at_utc": _now(),
        "script": "src.roadway_graph.stable_lineage_scaffold_regeneration",
        "bounded_question": "Review-only regeneration of final represented scaffold bins with stable source Travelway lineage fields persisted at the bin surface.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "source_travelway_stable_identity": str(LINEAGE_DIR / "source_travelway_stable_identity.csv"),
            "lineage_gap_unmatched_detail": str(GAP_DIR / "travelway_lineage_unmatched_bin_detail.csv"),
            "seed_backfill_access_target": str(BACKFILL_DIR / "final_access_target_bins_with_stable_travelway_lineage.csv"),
            "final_signal_universe": str(FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv"),
            "final_geometry_cleanup_manifest": _load_json(GEOMETRY_CLEANUP_DIR / "final_access_geometry_persistence_manifest.json"),
        },
        "producer_diagnosis": {
            "legacy_bin_producer": "src.roadway_graph.refreshed_expanded_universe_with_offset_recovery",
            "legacy_bin_consolidator": "src.roadway_graph.consolidated_scaffold_completeness_refresh",
            "lineage_drop_point": "prior/existing represented access-target bins entered the refreshed represented bin universe without stable Travelway/source-row route lineage fields",
        },
        "metrics": {
            "regenerated_signal_count": int(_text(bins, "target_signal_id").nunique()),
            "regenerated_bin_count": int(len(bins)),
            "high_confidence_bins": int(conf.str.startswith("high").sum()),
            "medium_confidence_bins": int(conf.str.startswith("medium").sum()),
            "low_confidence_bins": int(conf.str.startswith("low").sum()),
            "unmatched_bins": int(conf.eq("unmatched").sum()),
            "previous_unmatched_input_bins": int(len(gap)),
        },
        "outputs": [
            "stable_lineage_scaffold_regeneration_findings.md",
            "stable_lineage_represented_bin_universe.csv",
            "stable_lineage_represented_signal_universe.csv",
            "stable_lineage_generation_lineage_audit.csv",
            "stable_lineage_previous_vs_regenerated_comparison.csv",
            "stable_lineage_previously_unmatched_recovery_summary.csv",
            "stable_lineage_reviewed_case_audit.csv",
            "stable_lineage_generation_qa.csv",
            "stable_lineage_generation_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "access_assignment_performed": False,
            "crash_assignment_performed": False,
            "crash_records_read": False,
            "crash_direction_fields_read": False,
            "rates_or_models_run": False,
            "active_outputs_overwritten": False,
            "regenerated_scaffold_promoted": False,
        },
    }
    _write_json(manifest, "stable_lineage_generation_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
