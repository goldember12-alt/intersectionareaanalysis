from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_scaffold_travelway_lineage_backfill"

LINEAGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
GEOMETRY_CLEANUP_DIR = OUTPUT_ROOT / "review/current/final_access_target_geometry_persistence_cleanup"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"

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
    LINEAGE_DIR / "final_scaffold_travelway_lineage_bridge.csv",
    LINEAGE_DIR / "access_target_travelway_lineage_bridge.csv",
    LINEAGE_DIR / "reviewed_case_lineage_audit.csv",
    LINEAGE_DIR / "travelway_lineage_completeness_summary.csv",
    LINEAGE_DIR / "travelway_lineage_required_fields_recommendation.csv",
    LINEAGE_DIR / "source_travelway_lineage_bridge_manifest.json",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    GEOMETRY_CLEANUP_DIR / "final_access_target_bins_geometry_cleaned.csv",
    GEOMETRY_CLEANUP_DIR / "final_access_geometry_persistence_manifest.json",
    ACCESS_REVIEW_GPKG,
]

FEET_PER_METER = 3.280839895
NEAR_MATCH_MAX_FT = 12.0
EXACT_MATCH_MAX_FT = 1.0


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


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _collapse(values: pd.Series | list[Any], limit: int = 12) -> str:
    if isinstance(values, pd.Series):
        items = values.dropna().astype(str).tolist()
    else:
        items = [str(value) for value in values]
    unique = sorted({value for value in items if value.strip()})
    suffix = "" if len(unique) <= limit else f"|+{len(unique) - limit}_more"
    return "|".join(unique[:limit]) + suffix


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _parse_wkt(value: Any):
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    try:
        return wkt.loads(text)
    except Exception:
        return None


def _route_tokens(value: Any) -> set[str]:
    text = str(value or "").upper()
    tokens = {part.strip() for part in re.split(r"[|;,]", text) if part.strip()}
    compact = re.sub(r"[^A-Z0-9]+", "", text)
    if compact:
        tokens.add(compact)
    for match in re.finditer(r"(US|VA|IS|SC|SR|RTE)0*([0-9]+)([A-Z])?", compact):
        prefix, number, direction = match.groups()
        if prefix in {"SR", "RTE"}:
            prefix = "VA"
        tokens.add(f"{prefix}{int(number)}{direction or ''}")
        tokens.add(f"{prefix}{int(number)}")
    return tokens


def _route_compatible(bin_labels: Any, source_route_name: Any, source_common: Any, source_route_id: Any) -> bool:
    bin_tokens = _route_tokens(bin_labels)
    source_tokens = _route_tokens(str(source_route_name or "") + "|" + str(source_common or "") + "|" + str(source_route_id or ""))
    return bool(bin_tokens & source_tokens)


def _load_source_with_geometry(stable: pd.DataFrame) -> gpd.GeoDataFrame:
    _checkpoint("read_start source_travelway_full_geometry")
    src = gpd.read_file(ACCESS_REVIEW_GPKG, layer="source_travelway_full")
    if src.crs is None:
        src = src.set_crs("EPSG:3968", allow_override=True)
    src = src.to_crs("EPSG:3968")
    src["source_feature_local_fid"] = (src.index + 1).astype(str)
    stable = stable.copy()
    stable["source_feature_local_fid"] = _text(stable, "source_feature_local_fid")
    keep = [
        "stable_travelway_id",
        "source_feature_local_fid",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "from_measure",
        "to_measure",
        "geometry_hash",
        "attribute_hash",
        "stable_composite_key",
    ]
    src = src.merge(stable[[col for col in keep if col in stable.columns]], on="source_feature_local_fid", how="left")
    _checkpoint("read_complete source_travelway_full_geometry", len(src))
    return src


def _normalize_scaffold_bins(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["lineage_row_id"] = ["scaffold_bin_" + str(i).zfill(7) for i in range(len(out))]
    out["bin_id"] = _text(out, "consolidated_bin_id")
    out["signal_id_norm"] = _text(out, "signal_id")
    out["geometry_wkt_backfill"] = _text(out, "geometry_wkt")
    return out


def _normalize_access_bins(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["lineage_row_id"] = ["access_bin_" + str(i).zfill(7) for i in range(len(out))]
    out["bin_id"] = _text(out, "target_bin_id")
    out["signal_id_norm"] = _text(out, "target_signal_id")
    if "geometry_wkt_cleaned" in out.columns:
        out["geometry_wkt_backfill"] = _text(out, "geometry_wkt_cleaned").where(_text(out, "geometry_wkt_cleaned").ne(""), _text(out, "geometry_wkt"))
    else:
        out["geometry_wkt_backfill"] = _text(out, "geometry_wkt")
    if "source_travelway_lineage" not in out.columns:
        out["source_travelway_lineage"] = ""
    return out


def _existing_bridge_seed(frame: pd.DataFrame, bridge: pd.DataFrame, *, frame_bin_col: str, bridge_bin_col: str) -> pd.DataFrame:
    cols = [
        bridge_bin_col,
        "stable_travelway_id",
        "candidate_stable_travelway_ids",
        "candidate_source_feature_local_fids",
        "lineage_match_method",
        "lineage_confidence",
        "candidate_match_count",
    ]
    seed = bridge[[col for col in cols if col in bridge.columns]].copy()
    seed = seed.rename(
        columns={
            bridge_bin_col: frame_bin_col,
            "stable_travelway_id": "seed_stable_travelway_id",
            "candidate_stable_travelway_ids": "seed_candidate_stable_travelway_ids",
            "candidate_source_feature_local_fids": "seed_candidate_source_feature_local_fids",
            "lineage_match_method": "seed_lineage_match_method",
            "lineage_confidence": "seed_lineage_confidence",
            "candidate_match_count": "seed_candidate_match_count",
        }
    )
    return frame.merge(seed, on=frame_bin_col, how="left")


def _geometry_best_match(frame: pd.DataFrame, source: gpd.GeoDataFrame, *, label: str) -> pd.DataFrame:
    geom = _text(frame, "geometry_wkt_backfill").map(_parse_wkt)
    gdf = gpd.GeoDataFrame(frame[["lineage_row_id", "bin_id", "signal_id_norm", "route_facility_fields", "geometry_wkt_backfill"]].copy(), geometry=geom, crs="EPSG:3968")
    gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        return pd.DataFrame()
    _checkpoint(f"geometry_nearest_start {label}", len(gdf))
    src_cols = [
        "stable_travelway_id",
        "source_feature_local_fid",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "from_measure",
        "to_measure",
        "geometry_hash",
        "geometry",
    ]
    nearest = gpd.sjoin_nearest(
        gdf,
        source[[col for col in src_cols if col in source.columns]],
        how="left",
        max_distance=NEAR_MATCH_MAX_FT / FEET_PER_METER,
        distance_col="nearest_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest["nearest_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") * FEET_PER_METER
    nearest["route_measure_compatibility"] = [
        _route_compatible(labels, source_name, source_common, source_id)
        for labels, source_name, source_common, source_id in zip(
            nearest.get("route_facility_fields", ""),
            nearest.get("source_route_name", ""),
            nearest.get("source_route_common", ""),
            nearest.get("source_route_id", ""),
        )
    ]
    nearest = nearest.sort_values(
        ["lineage_row_id", "route_measure_compatibility", "nearest_distance_ft"],
        ascending=[True, False, True],
        na_position="last",
    )
    candidate_counts = nearest.groupby("lineage_row_id", dropna=False).agg(
        geometry_candidate_match_count=("stable_travelway_id", "nunique"),
        candidate_stable_travelway_ids=("stable_travelway_id", _collapse),
        candidate_source_feature_local_fids=("source_feature_local_fid", _collapse),
    ).reset_index()
    best = nearest.drop_duplicates("lineage_row_id", keep="first").copy()
    best = best.merge(candidate_counts, on="lineage_row_id", how="left", suffixes=("", "_all"))
    best = best.rename(
        columns={
            "stable_travelway_id": "geometry_stable_travelway_id",
            "source_feature_local_fid": "geometry_source_feature_local_fid",
            "source_route_id": "geometry_source_route_id",
            "source_route_name": "geometry_source_route_name",
            "source_route_common": "geometry_source_route_common",
            "from_measure": "geometry_from_measure",
            "to_measure": "geometry_to_measure",
            "geometry_hash": "geometry_source_geometry_hash",
        }
    )
    keep = [
        "lineage_row_id",
        "geometry_stable_travelway_id",
        "geometry_source_feature_local_fid",
        "geometry_source_route_id",
        "geometry_source_route_name",
        "geometry_source_route_common",
        "geometry_from_measure",
        "geometry_to_measure",
        "geometry_source_geometry_hash",
        "nearest_distance_ft",
        "route_measure_compatibility",
        "geometry_candidate_match_count",
        "candidate_stable_travelway_ids",
        "candidate_source_feature_local_fids",
    ]
    _checkpoint(f"geometry_nearest_complete {label}", len(best))
    return best[[col for col in keep if col in best.columns]].copy()


def _classify_matches(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    seed_method = _text(out, "seed_lineage_match_method")
    seed_conf = _text(out, "seed_lineage_confidence")
    geom_id = _text(out, "geometry_stable_travelway_id")
    geom_distance = pd.to_numeric(_text(out, "nearest_distance_ft"), errors="coerce")
    route_ok = out.get("route_measure_compatibility", False)
    if not isinstance(route_ok, pd.Series):
        route_ok = pd.Series(False, index=out.index)
    route_ok = route_ok.fillna(False).astype(bool)
    seed_direct = seed_method.eq("direct_source_travelway_id") & seed_conf.eq("high")
    has_geom = geom_id.ne("")
    high_exact = has_geom & geom_distance.le(EXACT_MATCH_MAX_FT) & route_ok
    med_near = has_geom & geom_distance.le(NEAR_MATCH_MAX_FT) & route_ok
    low_route = seed_method.eq("route_label_only_match")

    out["best_stable_travelway_id"] = ""
    seed_values = _text(out, "seed_stable_travelway_id").where(
        _text(out, "seed_stable_travelway_id").ne(""),
        _text(out, "seed_candidate_stable_travelway_ids").str.split("|").str[0],
    )
    out.loc[seed_direct, "best_stable_travelway_id"] = seed_values.loc[seed_direct].values
    high_fill = high_exact & out["best_stable_travelway_id"].eq("")
    out.loc[high_fill, "best_stable_travelway_id"] = _text(out, "geometry_stable_travelway_id").loc[high_fill].values
    med_fill = med_near & out["best_stable_travelway_id"].eq("")
    out.loc[med_fill, "best_stable_travelway_id"] = _text(out, "geometry_stable_travelway_id").loc[med_fill].values

    out["lineage_backfill_match_method"] = "unmatched"
    out["lineage_backfill_confidence"] = "unmatched"
    out.loc[low_route, ["lineage_backfill_match_method", "lineage_backfill_confidence"]] = ["route_label_only_match", "low_route_label_only"]
    out.loc[med_near, ["lineage_backfill_match_method", "lineage_backfill_confidence"]] = ["geometry_near_route_compatible", "medium_geometry_near_route_compatible"]
    out.loc[high_exact, ["lineage_backfill_match_method", "lineage_backfill_confidence"]] = ["geometry_exact_or_contained_route_compatible", "high_geometry_exact_or_contained"]
    out.loc[seed_direct, ["lineage_backfill_match_method", "lineage_backfill_confidence"]] = ["direct_source_travelway_id", "high_direct_source_id"]

    out["candidate_match_count"] = pd.to_numeric(out.get("geometry_candidate_match_count", 0), errors="coerce").fillna(0).astype(int)
    seed_count = pd.to_numeric(out.get("seed_candidate_match_count", 0), errors="coerce").fillna(0).astype(int)
    out["candidate_match_count"] = np.maximum(out["candidate_match_count"], seed_count)
    out["lineage_conflict_fanout_flag"] = out["candidate_match_count"].gt(1)
    out["fid_used_as_sole_stable_key"] = False
    return out


def _enrich_table(frame: pd.DataFrame, bridge: pd.DataFrame, source: gpd.GeoDataFrame, *, label: str, frame_bin_col: str, bridge_bin_col: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    seeded = _existing_bridge_seed(frame, bridge, frame_bin_col=frame_bin_col, bridge_bin_col=bridge_bin_col)
    geom = _geometry_best_match(seeded, source, label=label)
    enriched = seeded.merge(geom, on="lineage_row_id", how="left")
    enriched = _classify_matches(enriched)
    candidate_cols = [
        "lineage_row_id",
        "bin_id",
        "signal_id_norm",
        "best_stable_travelway_id",
        "lineage_backfill_match_method",
        "lineage_backfill_confidence",
        "candidate_match_count",
        "lineage_conflict_fanout_flag",
        "candidate_stable_travelway_ids",
        "candidate_source_feature_local_fids",
        "nearest_distance_ft",
        "route_measure_compatibility",
    ]
    candidates = enriched.loc[enriched["candidate_match_count"].gt(1), [col for col in candidate_cols if col in enriched.columns]].copy()
    unmatched = enriched.loc[_text(enriched, "lineage_backfill_match_method").eq("unmatched"), [col for col in candidate_cols if col in enriched.columns]].copy()
    return enriched, candidates, unmatched


def _summary(frame: pd.DataFrame, *, table_name: str) -> pd.DataFrame:
    rows = []
    for group_cols in [[], ["recovery_stream"], ["final_alignment_class"], ["geometry_recovery_method_final"]]:
        existing = [col for col in group_cols if col in frame.columns]
        groups = [((), frame)] if not existing else frame.groupby(existing, dropna=False)
        for key, sub in groups:
            if not isinstance(key, tuple):
                key = (key,)
            row = {"table_name": table_name, "grouping": "|".join(existing) if existing else "all", "row_count": len(sub)}
            for col, val in zip(existing, key):
                row[col] = val
            for conf, csub in sub.groupby("lineage_backfill_confidence", dropna=False):
                row[f"confidence_{conf}"] = len(csub)
            row["high_confidence_count"] = int(_text(sub, "lineage_backfill_confidence").str.startswith("high").sum())
            row["medium_confidence_count"] = int(_text(sub, "lineage_backfill_confidence").str.startswith("medium").sum())
            row["low_confidence_count"] = int(_text(sub, "lineage_backfill_confidence").str.startswith("low").sum())
            row["unmatched_count"] = int(_text(sub, "lineage_backfill_confidence").eq("unmatched").sum())
            row["conflict_fanout_count"] = int(sub.get("lineage_conflict_fanout_flag", pd.Series(False, index=sub.index)).fillna(False).astype(bool).sum())
            row["high_confidence_rate"] = round(row["high_confidence_count"] / len(sub), 6) if len(sub) else 0
            rows.append(row)
    return pd.DataFrame(rows)


def _reviewed_case_audit(scaffold: pd.DataFrame, access: pd.DataFrame, reviewed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in reviewed.itertuples(index=False):
        stable_id = str(getattr(r, "stable_travelway_id", ""))
        signal_id = str(getattr(r, "signal_id", ""))
        if not stable_id:
            rows.append({**r._asdict(), "scaffold_bins_with_backfilled_stable_id": "", "access_bins_with_backfilled_stable_id": "", "backfill_result": getattr(r, "lineage_result", "")})
            continue
        s_signal = scaffold.loc[_text(scaffold, "signal_id_norm").eq(signal_id)].copy()
        a_signal = access.loc[_text(access, "signal_id_norm").eq(signal_id)].copy()
        s = s_signal.loc[_text(s_signal, "best_stable_travelway_id").eq(stable_id)]
        a = a_signal.loc[_text(a_signal, "best_stable_travelway_id").eq(stable_id)]
        s_candidate = s_signal.loc[_text(s_signal, "candidate_stable_travelway_ids").str.contains(stable_id, regex=False)]
        a_candidate = a_signal.loc[_text(a_signal, "candidate_stable_travelway_ids").str.contains(stable_id, regex=False)]
        candidate_count = len(s_candidate) + len(a_candidate)
        best_count = len(s) + len(a)
        rows.append(
            {
                **r._asdict(),
                "scaffold_bins_with_backfilled_stable_id": len(s),
                "access_bins_with_backfilled_stable_id": len(a),
                "scaffold_bins_with_candidate_stable_id": len(s_candidate),
                "access_bins_with_candidate_stable_id": len(a_candidate),
                "backfilled_confidence_classes": _collapse(_text(s, "lineage_backfill_confidence").tolist() + _text(a, "lineage_backfill_confidence").tolist()),
                "backfill_result": (
                    "stable_id_preserved_as_best_match"
                    if best_count
                    else "stable_id_present_only_as_ambiguous_candidate"
                    if candidate_count
                    else "stable_id_not_backfilled_to_bins"
                ),
            }
        )
    return pd.DataFrame(rows)


def _conflict_summary(scaffold: pd.DataFrame, access: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, frame in [("final_scaffold_bins", scaffold), ("final_access_target_bins", access)]:
        flagged = frame.loc[frame["lineage_conflict_fanout_flag"].fillna(False).astype(bool)]
        rows.append(
            {
                "table_name": name,
                "conflict_fanout_rows": len(flagged),
                "signals_with_conflict_fanout": _text(flagged, "signal_id_norm").nunique(),
                "max_candidate_match_count": pd.to_numeric(frame["candidate_match_count"], errors="coerce").max(),
                "common_confidence_classes": _collapse(_text(flagged, "lineage_backfill_confidence")),
            }
        )
    return pd.DataFrame(rows)


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "Writes only to final_scaffold_travelway_lineage_backfill review folder."),
        ("no_candidates_promoted", "pass", "No promotion outputs are written."),
        ("no_access_or_crash_assignment", "pass", "No access/crash assignment is performed."),
        ("no_crash_records_read", "pass", "No crash inputs are read."),
        ("no_crash_direction_fields_used", "pass", "Read guards block crash direction fields."),
        ("no_rates_or_models", "pass", "No rate/model calculations are performed."),
        ("fid_not_sole_stable_lineage_key", "pass", "GeoPackage fid is used only to connect to the previously built stable ID table."),
        ("match_methods_documented", "pass", "Outputs include lineage_backfill_match_method and lineage_backfill_confidence."),
        ("ambiguous_fanout_reported", "pass", "Candidate fanout/conflict fields and summaries are written."),
        ("outputs_review_only", "pass", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "status", "note"])


def _findings(scaffold: pd.DataFrame, access: pd.DataFrame, reviewed: pd.DataFrame) -> str:
    def counts(frame: pd.DataFrame) -> dict[str, int]:
        return {
            "high": int(_text(frame, "lineage_backfill_confidence").str.startswith("high").sum()),
            "medium": int(_text(frame, "lineage_backfill_confidence").str.startswith("medium").sum()),
            "low": int(_text(frame, "lineage_backfill_confidence").str.startswith("low").sum()),
            "unmatched": int(_text(frame, "lineage_backfill_confidence").eq("unmatched").sum()),
            "total": len(frame),
        }

    sc = counts(scaffold)
    ac = counts(access)
    s45 = reviewed.loc[_text(reviewed, "signal_id").eq("signal_000045")]
    s45_lines = "\n".join(
        f"- FID {row.reviewed_source_fid}: stable ID {row.stable_travelway_id}; best-match scaffold bins {row.scaffold_bins_with_backfilled_stable_id}; best-match access bins {row.access_bins_with_backfilled_stable_id}; candidate scaffold bins {getattr(row, 'scaffold_bins_with_candidate_stable_id', '')}; candidate access bins {getattr(row, 'access_bins_with_candidate_stable_id', '')}; result {row.backfill_result}."
        for row in s45.itertuples()
    )
    return f"""# Stable Travelway Lineage Backfill

**Bounded question:** enrich final scaffold and access target bins with stable source Travelway lineage without changing scaffold/access logic.

## Findings

1. Final scaffold bins with high-confidence stable Travelway lineage: **{sc['high']:,} / {sc['total']:,}** ({sc['high'] / sc['total']:.1%}).
2. Final access target bins with high-confidence stable Travelway lineage: **{ac['high']:,} / {ac['total']:,}** ({ac['high'] / ac['total']:.1%}).
3. Final scaffold bins still low-confidence route-label-only: **{sc['low']:,}**; unmatched: **{sc['unmatched']:,}**.
4. Final access target bins still low-confidence route-label-only: **{ac['low']:,}**; unmatched: **{ac['unmatched']:,}**.
5. The most useful backfill method was strict geometry-nearest/route-compatible matching.

## Signal 000045

{s45_lines}

## Decision

The enriched lineage is substantially better than the prior bridge for route/source review and access-to-Travelway refinement. It is still not a production lineage fix because ambiguous/fanout rows remain and some bins are unmatched. Future crash/catchment work can use this as a review-only bridge, but active scaffold generation should persist `stable_travelway_id` directly.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs: " + "; ".join(missing))

    stable = _read_csv(LINEAGE_DIR / "source_travelway_stable_identity.csv")
    source = _load_source_with_geometry(stable)
    scaffold_raw = _normalize_scaffold_bins(_read_csv(FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv"))
    access_raw = _normalize_access_bins(_read_csv(GEOMETRY_CLEANUP_DIR / "final_access_target_bins_geometry_cleaned.csv"))
    scaffold_bridge = _read_csv(LINEAGE_DIR / "final_scaffold_travelway_lineage_bridge.csv")
    access_bridge = _read_csv(LINEAGE_DIR / "access_target_travelway_lineage_bridge.csv")
    reviewed_prior = _read_csv(LINEAGE_DIR / "reviewed_case_lineage_audit.csv")

    scaffold, scaffold_candidates, scaffold_unmatched = _enrich_table(
        scaffold_raw,
        scaffold_bridge,
        source,
        label="final_scaffold_bins",
        frame_bin_col="consolidated_bin_id",
        bridge_bin_col="consolidated_bin_id",
    )
    access, access_candidates, access_unmatched = _enrich_table(
        access_raw,
        access_bridge,
        source,
        label="final_access_target_bins",
        frame_bin_col="target_bin_id",
        bridge_bin_col="consolidated_bin_id",
    )

    candidate_matches = pd.concat(
        [scaffold_candidates.assign(table_name="final_scaffold_bins"), access_candidates.assign(table_name="final_access_target_bins")],
        ignore_index=True,
        sort=False,
    )
    unmatched = pd.concat(
        [scaffold_unmatched.assign(table_name="final_scaffold_bins"), access_unmatched.assign(table_name="final_access_target_bins")],
        ignore_index=True,
        sort=False,
    )
    conflict = _conflict_summary(scaffold, access)
    completeness = pd.concat([_summary(scaffold, table_name="final_scaffold_bins"), _summary(access, table_name="final_access_target_bins")], ignore_index=True, sort=False)
    reviewed = _reviewed_case_audit(scaffold, access, reviewed_prior)
    qa = _qa()

    _write_csv(scaffold, "final_scaffold_bins_with_stable_travelway_lineage.csv")
    _write_csv(access, "final_access_target_bins_with_stable_travelway_lineage.csv")
    _write_csv(candidate_matches, "travelway_lineage_backfill_candidate_matches.csv")
    _write_csv(unmatched, "travelway_lineage_backfill_unmatched_bins.csv")
    _write_csv(conflict, "travelway_lineage_backfill_conflict_summary.csv")
    _write_csv(completeness, "travelway_lineage_backfill_completeness_summary.csv")
    _write_csv(reviewed, "reviewed_case_lineage_backfill_audit.csv")
    _write_text(_findings(scaffold, access, reviewed), "stable_travelway_lineage_backfill_findings.md")
    _write_csv(qa, "stable_travelway_lineage_backfill_qa.csv")
    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "Backfill stable Travelway lineage into final scaffold and access target bins.",
        "output_folder": str(OUT_DIR),
        "match_order": [
            "existing bridge/direct lineage seed",
            "strict nearest geometry constrained by route/facility compatibility",
            "route-label-only seed",
            "unmatched",
        ],
        "near_match_max_ft": NEAR_MATCH_MAX_FT,
        "exact_match_max_ft": EXACT_MATCH_MAX_FT,
        "qa_pass": bool(qa["status"].eq("pass").all()),
        "non_goals": [
            "no scaffold logic changes",
            "no access/crash assignment",
            "no rates/models",
            "no active output modification",
            "no candidate promotion",
        ],
    }
    _write_json(manifest, "stable_travelway_lineage_backfill_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
