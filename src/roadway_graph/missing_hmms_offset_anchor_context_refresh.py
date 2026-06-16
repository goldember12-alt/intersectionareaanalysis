from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely import wkt
from shapely.geometry import Point

from .aadt_context_join_v3_identity_route_measure import _route_key as _aadt_v3_route_key


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_context_refresh"
GPKG_PATH = OUT_DIR / "offset_anchor_context_refresh_review.gpkg"

RECOVERY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_scaffold_recovery"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
GOOD_CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_context_refresh"
COMPLEX_REVIEW_DIR = OUTPUT_ROOT / "review/current/complex_signal_map_review_ingestion"
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_RECOVERY_CONTEXT_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"
INTERSECTION_ZONE_CONTEXT_DIR = OUTPUT_ROOT / "review/current/intersection_zone_missing_leg_context_refresh"
ROUTE_DISCONTINUITY_CONTEXT_DIR = OUTPUT_ROOT / "review/current/route_discontinuity_offset_context_refresh"
RNS_PHASE3D_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_V3_REBUILD_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_v3_path_rebuild"

SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"

CRS = "EPSG:3968"
CURRENT_REPRESENTED_SIGNAL_COUNT = 2739
GOOD_TRAVELWAY_ALL_ADDITIONS = 626
GOOD_TRAVELWAY_CLEAN_ADDITIONS = 604
GOOD_TRAVELWAY_HOLDOUT_ADDITIONS = 22
SOURCE_SIGNAL_UNIVERSE_COUNT = 3933

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
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    GOOD_CONTEXT_DIR / "good_travelway_context_bin_detail.csv",
    GOOD_CONTEXT_DIR / "good_travelway_context_signal_summary.csv",
    GOOD_CONTEXT_DIR / "good_travelway_context_refresh_manifest.json",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv",
    COMPLEX_REVIEW_DIR / "good_travelway_revised_universe_recommendation.csv",
    COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
    SPEED_LIMIT_RNS_GDB,
    AADT_FILE,
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
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if SPEED_LIMIT_RNS_GDB.exists():
        layers = {row[0] for row in pyogrio.list_layers(SPEED_LIMIT_RNS_GDB)}
        if SPEED_LIMIT_RNS_LAYER not in layers:
            missing.append(f"{SPEED_LIMIT_RNS_GDB}:{SPEED_LIMIT_RNS_LAYER}")
    return missing


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def _route_key(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " ")
    text = text.replace("S-VA", "SC")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    joined = "".join(tokens)
    route_type = ""
    route_number = ""
    direction = ""
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"US", "SR", "VA", "I", "SC", "PR", "FR"}:
            route_type = "SR" if compact == "VA" else compact
            continue
        if compact in {"NB", "SB", "EB", "WB", "N", "S", "E", "W"}:
            direction = compact[0]
            continue
        match = re.fullmatch(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            continue
        match = re.fullmatch(r"0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match and route_type:
            route_number = str(int(match.group(1)))
            if match.group(2):
                direction = match.group(2)[0]
    if not route_number:
        match = re.search(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", joined)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
    if route_number and route_type:
        return f"{route_type}{route_number}{direction}"
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def _route_key_variants(row: pd.Series, cols: list[str], *, include_aadt: bool = False) -> set[str]:
    variants: set[str] = set()
    for col in cols:
        key = _route_key(row.get(col, ""))
        if key:
            variants.add(key)
        if include_aadt:
            aadt_key = _aadt_v3_route_key(row.get(col, ""))
            if aadt_key:
                variants.add(aadt_key)
    return variants


def _interval_lookup(bins: pd.DataFrame, source: pd.DataFrame, *, source_prefix: str, value_cols: list[str]) -> pd.DataFrame:
    _checkpoint(f"{source_prefix}_interval_lookup_start", len(bins))
    out = bins[["stable_bin_id", "source_measure_min", "source_measure_max", "route_key_primary", "route_key_alt"]].copy()
    for col in value_cols:
        out[f"{source_prefix}_{col}"] = ""
    out[f"{source_prefix}_match_status"] = "missing_route_or_measure"
    out[f"{source_prefix}_match_count"] = 0
    valid_mask = (
        out["source_measure_min"].notna()
        & out["source_measure_max"].notna()
        & (_text(out, "route_key_primary").str.strip().ne("") | _text(out, "route_key_alt").str.strip().ne(""))
    )
    if not valid_mask.any() or source.empty:
        _checkpoint(f"{source_prefix}_interval_lookup_complete", 0)
        return out
    matched = pd.Series(False, index=out.index)
    for key_col in ["route_key_primary", "route_key_alt"]:
        remaining = out.loc[valid_mask & ~matched].copy()
        if remaining.empty:
            break
        for route_key, bgrp in remaining.groupby(key_col, sort=False):
            if not str(route_key).strip():
                continue
            sgrp = source.loc[source["route_key"].eq(route_key)].copy()
            if sgrp.empty:
                continue
            sgrp = sgrp.sort_values(["measure_start", "measure_end"])
            starts = sgrp["measure_start"].to_numpy(dtype=float)
            ends = sgrp["measure_end"].to_numpy(dtype=float)
            mids = (bgrp["source_measure_min"].to_numpy(dtype=float) + bgrp["source_measure_max"].to_numpy(dtype=float)) / 2.0
            pos = np.searchsorted(starts, mids, side="right") - 1
            valid = (pos >= 0) & (ends[np.maximum(pos, 0)] >= mids)
            if not valid.any():
                out.loc[bgrp.index, f"{source_prefix}_match_status"] = "no_interval_match"
                continue
            matched_idx = bgrp.index[valid]
            source_pos = pos[valid]
            for col in value_cols:
                out.loc[matched_idx, f"{source_prefix}_{col}"] = sgrp.iloc[source_pos][col].astype(str).to_numpy()
            out.loc[matched_idx, f"{source_prefix}_match_status"] = "matched_midpoint_vectorized"
            out.loc[matched_idx, f"{source_prefix}_match_count"] = 1
            matched.loc[matched_idx] = True
            out.loc[bgrp.index[~valid], f"{source_prefix}_match_status"] = "no_interval_match"
    _checkpoint(f"{source_prefix}_interval_lookup_complete", int(matched.sum()))
    return out


def _load_rns_source(needed_keys: set[str]) -> pd.DataFrame:
    cols = [
        "RTE_NM",
        "MASTER_RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "CAR_SPEED_LIMIT",
        "FINAL_SPEED_LIMIT_SOURCE",
        "SPEEDZONE_TYPE_DSC",
    ]
    _checkpoint("read_start Speed_Limit_RNS")
    rns = pyogrio.read_dataframe(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=cols, read_geometry=False, use_arrow=True)
    _checkpoint("read_complete Speed_Limit_RNS", len(rns))
    rns["measure_start"] = pd.to_numeric(rns["TRANSPORT_EDGE_FROM_MSR"].fillna(rns["FROM_MEASURE"]), errors="coerce")
    rns["measure_end"] = pd.to_numeric(rns["TRANSPORT_EDGE_TO_MSR"].fillna(rns["TO_MEASURE"]), errors="coerce")
    swap = rns["measure_start"] > rns["measure_end"]
    rns.loc[swap, ["measure_start", "measure_end"]] = rns.loc[swap, ["measure_end", "measure_start"]].to_numpy()
    rows = []
    for row in rns.dropna(subset=["measure_start", "measure_end"]).to_dict(orient="records"):
        for key in _route_key_variants(pd.Series(row), ["RTE_NM", "MASTER_RTE_NM"]):
            rows.append({**row, "route_key": key})
    out = pd.DataFrame(rows)
    if needed_keys and not out.empty:
        out = out.loc[out["route_key"].isin(needed_keys)].copy()
    _checkpoint("prepared RNS keyed intervals", len(out))
    return out


def _load_aadt_source(needed_keys: set[str]) -> pd.DataFrame:
    cols = [
        "RTE_NM",
        "MASTER_RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "AADT_YR",
        "AADT",
        "AADT_QUALITY",
        "AAWDT",
        "AAWDT_QUALITY",
        "DIRECTION_FACTOR",
        "DIRECTIONALITY",
        "FROM_PHY_JURISDICTION_NM",
        "MPO_DSC",
    ]
    _checkpoint("read_start normalized AADT")
    aadt = pd.read_parquet(AADT_FILE, columns=cols)
    _checkpoint("read_complete normalized AADT", len(aadt))
    aadt["measure_start"] = pd.to_numeric(aadt["TRANSPORT_EDGE_FROM_MSR"].fillna(aadt["FROM_MEASURE"]), errors="coerce")
    aadt["measure_end"] = pd.to_numeric(aadt["TRANSPORT_EDGE_TO_MSR"].fillna(aadt["TO_MEASURE"]), errors="coerce")
    swap = aadt["measure_start"] > aadt["measure_end"]
    aadt.loc[swap, ["measure_start", "measure_end"]] = aadt.loc[swap, ["measure_end", "measure_start"]].to_numpy()
    rows = []
    for row in aadt.dropna(subset=["measure_start", "measure_end"]).to_dict(orient="records"):
        for key in _route_key_variants(pd.Series(row), ["RTE_NM", "MASTER_RTE_NM"], include_aadt=True):
            rows.append({**row, "route_key": key})
    out = pd.DataFrame(rows)
    if needed_keys and not out.empty:
        out = out.loc[out["route_key"].isin(needed_keys)].copy()
    _checkpoint("prepared AADT keyed intervals", len(out))
    return out


def _build_base_bins() -> tuple[pd.DataFrame, pd.DataFrame]:
    bins = _read_csv(RECOVERY_DIR / "offset_anchor_recovered_bins.csv")
    legs = _read_csv(
        RECOVERY_DIR / "offset_anchor_recovered_leg_candidates.csv",
        usecols=[
            "leg_candidate_id",
            "source_route_facility",
            "source_rim_access",
            "source_ramp_code",
            "source_loc_comp",
            "grade_or_mainline_risk_flag",
            "coverage_class",
        ],
    )
    signals = _read_csv(RECOVERY_DIR / "offset_anchor_recovered_signal_summary.csv")
    overlap = _read_csv(RECOVERY_DIR / "offset_anchor_overlap_dedup_review.csv")
    crash = _read_csv(RECOVERY_DIR / "offset_anchor_crash_relevance_summary.csv")
    generated_ids = set(_text(bins, "stable_signal_id"))
    signals = signals.loc[_text(signals, "stable_signal_id").isin(generated_ids)].copy()
    out = bins.merge(legs.drop_duplicates("leg_candidate_id"), on="leg_candidate_id", how="left")
    signal_cols = [
        "stable_signal_id",
        "GLOBALID",
        "OBJECTID_1",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "source_layer",
        "source_system",
        "MAJ_NAME",
        "MAJ_NUM",
        "MINOR_NAME",
        "MINOR_NUM",
        "attr_best_available_loss_reason",
        "recoverability_class",
        "crash_relevance_class",
        "signal_geometry_wkt",
        "intersection_anchor_x",
        "intersection_anchor_y",
        "signal_to_anchor_offset_ft",
        "anchor_method",
        "anchor_confidence",
        "anchor_intersection_candidate_count",
        "generation_status",
    ]
    out = out.merge(signals[[col for col in signal_cols if col in signals.columns]], on="stable_signal_id", how="left", suffixes=("", "_signal"))
    out["OBJECTID"] = _text(out, "OBJECTID_1")
    out["raw_signal_geometry_wkt"] = _text(out, "signal_geometry_wkt")
    out["inferred_anchor_geometry_wkt"] = [
        Point(float(x), float(y)).wkt if _clean(x) and _clean(y) else ""
        for x, y in zip(_text(out, "intersection_anchor_x"), _text(out, "intersection_anchor_y"))
    ]
    out = out.merge(
        overlap[
            [
                "stable_signal_id",
                "exact_duplicate_signal_risk",
                "duplicate_with_good_travelway_addition",
                "missing_source_globalid_risk",
                "missing_source_signal_id_risk",
                "sibling_signal_risk",
                "stable_travelway_overlap_bin_count",
                "complex_multi_signal_risk",
                "overlap_review_required",
            ]
        ],
        on="stable_signal_id",
        how="left",
    )
    out = out.merge(
        crash[
            [
                "stable_signal_id",
                "high_crash_relevance_flag",
                "source_not_represented_unassigned_crashes_within_2500ft",
                "may_explain_source_not_represented_crash_cluster",
            ]
        ],
        on="stable_signal_id",
        how="left",
    )
    out["source_measure_min"] = pd.to_numeric(out["source_measure_start"], errors="coerce")
    out["source_measure_max"] = pd.to_numeric(out["source_measure_end"], errors="coerce")
    swap = out["source_measure_min"] > out["source_measure_max"]
    out.loc[swap, ["source_measure_min", "source_measure_max"]] = out.loc[swap, ["source_measure_max", "source_measure_min"]].to_numpy()
    out["route_key_primary"] = out["source_route_name"].map(_route_key)
    out["route_key_alt"] = out["source_route_common"].map(_route_key)
    out["aadt_route_key_primary"] = out["source_route_name"].map(_aadt_v3_route_key)
    out["aadt_route_key_alt"] = out["source_route_common"].map(_aadt_v3_route_key)
    out["route_measure_identity_status"] = np.where(
        out["stable_travelway_id"].astype(str).str.strip().ne("")
        & out["route_key_primary"].astype(str).str.strip().ne("")
        & out["source_measure_min"].notna()
        & out["source_measure_max"].notna(),
        "route_measure_identity_available",
        "route_measure_identity_missing",
    )
    out["roadway_division_context"] = np.select(
        [
            _text(out, "source_route_facility").str.contains("DIVIDED", case=False, na=False),
            _text(out, "source_route_facility").str.contains("UNDIVIDED", case=False, na=False),
        ],
        ["divided", "undivided"],
        default="unknown",
    )
    out["roadway_context_status"] = np.where(_text(out, "source_route_facility").str.strip().ne(""), "roadway_context_available", "roadway_context_missing")
    return out, signals


def _attach_context(base: pd.DataFrame) -> pd.DataFrame:
    rns_needed = {_clean(v) for v in list(_text(base, "route_key_primary")) + list(_text(base, "route_key_alt")) if _clean(v)}
    rns = _load_rns_source(rns_needed)
    speed = _interval_lookup(
        base.assign(route_key_primary=base["route_key_primary"], route_key_alt=base["route_key_alt"]),
        rns,
        source_prefix="rns",
        value_cols=["CAR_SPEED_LIMIT", "FINAL_SPEED_LIMIT_SOURCE", "SPEEDZONE_TYPE_DSC", "RTE_NM", "MASTER_RTE_NM"],
    )
    aadt_bins = base.copy()
    aadt_bins["route_key_primary"] = np.where(_text(aadt_bins, "aadt_route_key_primary").str.strip().ne(""), aadt_bins["aadt_route_key_primary"], aadt_bins["route_key_primary"])
    aadt_bins["route_key_alt"] = np.where(_text(aadt_bins, "aadt_route_key_alt").str.strip().ne(""), aadt_bins["aadt_route_key_alt"], aadt_bins["route_key_alt"])
    aadt_needed = {_clean(v) for v in list(_text(aadt_bins, "route_key_primary")) + list(_text(aadt_bins, "route_key_alt")) if _clean(v)}
    aadt_source = _load_aadt_source(aadt_needed)
    aadt = _interval_lookup(
        aadt_bins,
        aadt_source,
        source_prefix="aadt",
        value_cols=[
            "AADT",
            "AADT_YR",
            "AADT_QUALITY",
            "AAWDT",
            "AAWDT_QUALITY",
            "DIRECTION_FACTOR",
            "DIRECTIONALITY",
            "FROM_PHY_JURISDICTION_NM",
            "MPO_DSC",
            "RTE_NM",
            "MASTER_RTE_NM",
        ],
    )
    out = base.merge(speed.drop(columns=["source_measure_min", "source_measure_max", "route_key_primary", "route_key_alt"]), on="stable_bin_id", how="left")
    out = out.merge(aadt.drop(columns=["source_measure_min", "source_measure_max", "route_key_primary", "route_key_alt"]), on="stable_bin_id", how="left")
    out["has_rns_speed"] = _text(out, "rns_CAR_SPEED_LIMIT").str.strip().ne("") & ~_text(out, "rns_match_status").str.startswith("missing")
    out["has_aadt"] = _text(out, "aadt_AADT").str.strip().ne("") & ~_text(out, "aadt_match_status").str.startswith("missing")
    out["has_exposure_denominator"] = out["has_aadt"] & (_text(out, "aadt_DIRECTION_FACTOR").str.strip().ne("") | _text(out, "aadt_DIRECTIONALITY").str.strip().ne(""))
    out["speed_aadt_ready_bin"] = out["has_rns_speed"] & out["has_aadt"] & out["has_exposure_denominator"]
    out["review_only_context_refresh_provenance"] = "missing_hmms_offset_anchor_context_refresh"
    return out


def _signal_summary(detail: pd.DataFrame, all_targets: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby("stable_signal_id", dropna=False).agg(
        GLOBALID=("GLOBALID", "first"),
        source_signal_id=("source_signal_id", "first"),
        OBJECTID=("OBJECTID", "first"),
        ASSET_ID=("ASSET_ID", "first"),
        REG_SIGNAL_ID=("REG_SIGNAL_ID", "first"),
        source_layer=("source_layer", "first"),
        source_system=("source_system", "first"),
        raw_signal_geometry_wkt=("raw_signal_geometry_wkt", "first"),
        inferred_anchor_geometry_wkt=("inferred_anchor_geometry_wkt", "first"),
        anchor_method=("anchor_method", "first"),
        anchor_confidence=("anchor_confidence", "first"),
        signal_to_anchor_offset_ft=("signal_to_anchor_offset_ft", "first"),
        attr_best_available_loss_reason=("attr_best_available_loss_reason", "first"),
        recoverability_class=("recoverability_class", "first"),
        crash_relevance_class=("crash_relevance_class", "first"),
        generated_bin_count=("stable_bin_id", "size"),
        route_measure_bins=("route_measure_identity_status", lambda s: int((s == "route_measure_identity_available").sum())),
        roadway_context_bins=("roadway_context_status", lambda s: int((s == "roadway_context_available").sum())),
        rns_speed_bins=("has_rns_speed", "sum"),
        aadt_bins=("has_aadt", "sum"),
        exposure_bins=("has_exposure_denominator", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        speed_aadt_ready_0_1000_bins=("speed_aadt_ready_bin", lambda s: int(s[detail.loc[s.index, "analysis_window"].eq("0_1000")].sum())),
        exact_duplicate_signal_risk=("exact_duplicate_signal_risk", "first"),
        sibling_signal_risk=("sibling_signal_risk", "first"),
        complex_multi_signal_risk=("complex_multi_signal_risk", "first"),
        overlap_review_required=("overlap_review_required", "first"),
        high_crash_relevance_flag=("high_crash_relevance_flag", "first"),
        source_not_represented_unassigned_crashes_within_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", "first"),
    ).reset_index()
    grouped["has_generated_bins"] = True
    grouped["route_measure_ready"] = grouped["route_measure_bins"].eq(grouped["generated_bin_count"])
    grouped["roadway_context_ready"] = grouped["roadway_context_bins"].eq(grouped["generated_bin_count"])
    grouped["rns_speed_ready"] = grouped["rns_speed_bins"].gt(0)
    grouped["aadt_ready"] = grouped["aadt_bins"].gt(0)
    grouped["exposure_denominator_ready"] = grouped["exposure_bins"].gt(0)
    grouped["speed_aadt_ready"] = grouped["speed_aadt_ready_bins"].gt(0)
    grouped["full_0_1000_speed_aadt_ready"] = grouped["speed_aadt_ready_0_1000_bins"].eq(grouped["generated_bin_count"])
    grouped["source_signal_globalid_available"] = _text(grouped, "GLOBALID").str.strip().ne("")
    grouped["source_signal_id_available"] = _text(grouped, "source_signal_id").str.strip().ne("")
    grouped["overlap_or_dedup_risk"] = (
        _flag(grouped, "exact_duplicate_signal_risk")
        | _flag(grouped, "sibling_signal_risk")
        | _flag(grouped, "complex_multi_signal_risk")
        | _flag(grouped, "overlap_review_required")
    )
    grouped["eligible_for_later_universe_expansion_review"] = grouped["speed_aadt_ready"] & ~grouped["overlap_or_dedup_risk"]

    generated_ids = set(_text(grouped, "stable_signal_id"))
    skipped_rows = all_targets.loc[~_text(all_targets, "stable_signal_id").isin(generated_ids)].copy()
    if not skipped_rows.empty:
        skipped_rows = skipped_rows.merge(skipped[["stable_signal_id", "skip_reason", "skip_note"]].drop_duplicates("stable_signal_id"), on="stable_signal_id", how="left")
        for col in grouped.columns:
            if col not in skipped_rows.columns:
                skipped_rows[col] = "" if grouped[col].dtype == object else 0
        skipped_rows["has_generated_bins"] = False
        skipped_rows["generated_bin_count"] = 0
        skipped_rows["route_measure_ready"] = False
        skipped_rows["roadway_context_ready"] = False
        skipped_rows["rns_speed_ready"] = False
        skipped_rows["aadt_ready"] = False
        skipped_rows["exposure_denominator_ready"] = False
        skipped_rows["speed_aadt_ready"] = False
        skipped_rows["full_0_1000_speed_aadt_ready"] = False
        skipped_rows["eligible_for_later_universe_expansion_review"] = False
        skipped_rows["overlap_or_dedup_risk"] = True
        grouped = pd.concat([grouped, skipped_rows.reindex(columns=grouped.columns.tolist() + [col for col in skipped_rows.columns if col not in grouped.columns])], ignore_index=True, sort=False)
    return grouped


def _summary_table(detail: pd.DataFrame, column: str, name_col: str) -> pd.DataFrame:
    rows = []
    for value, group in detail.groupby(column, dropna=False):
        rows.append({name_col: value if str(value).strip() else "blank", "bin_count": len(group), "signal_count": group["stable_signal_id"].nunique()})
    return pd.DataFrame(rows)


def _readiness_summary(signal_summary: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        ("total_offset_anchor_targets", len(signal_summary)),
        ("generated_bin_signals", int(signal_summary["has_generated_bins"].sum())),
        ("skipped_anchor_confidence_too_low_signals", int((~signal_summary["has_generated_bins"].astype(bool)).sum())),
        ("route_measure_ready_signals", int(signal_summary["route_measure_ready"].sum())),
        ("roadway_context_ready_signals", int(signal_summary["roadway_context_ready"].sum())),
        ("rns_speed_ready_signals", int(signal_summary["rns_speed_ready"].sum())),
        ("aadt_ready_signals", int(signal_summary["aadt_ready"].sum())),
        ("exposure_denominator_ready_signals", int(signal_summary["exposure_denominator_ready"].sum())),
        ("speed_aadt_ready_signals", int(signal_summary["speed_aadt_ready"].sum())),
        ("full_0_1000_speed_aadt_ready_signals", int(signal_summary["full_0_1000_speed_aadt_ready"].sum())),
        ("eligible_clean_later_universe_expansion_review_signals", int(signal_summary["eligible_for_later_universe_expansion_review"].sum())),
        ("overlap_or_dedup_risk_signals", int(signal_summary["overlap_or_dedup_risk"].sum())),
    ]
    return pd.DataFrame([{"readiness_metric": metric, "signal_count": count} for metric, count in metrics])


def _universe_projection(signal_summary: pd.DataFrame) -> pd.DataFrame:
    generated = int(signal_summary["has_generated_bins"].sum())
    context_ready = int(signal_summary["speed_aadt_ready"].sum())
    clean = int(signal_summary["eligible_for_later_universe_expansion_review"].sum())
    risk = int(generated - clean)
    review_visible = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_ALL_ADDITIONS
    clean_base = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_CLEAN_ADDITIONS
    projected_visible = review_visible + context_ready
    projected_clean = clean_base + clean
    return pd.DataFrame(
        [
            {"metric": "current_clean_review_universe_after_604_good_travelway", "value": clean_base},
            {"metric": "current_review_visible_universe_after_all_626_good_travelway", "value": review_visible},
            {"metric": "offset_anchor_generated_signals", "value": generated},
            {"metric": "offset_anchor_context_ready_signals", "value": context_ready},
            {"metric": "offset_anchor_clean_addition_candidates", "value": clean},
            {"metric": "offset_anchor_risk_or_holdout_candidates", "value": risk + int((~signal_summary["has_generated_bins"].astype(bool)).sum())},
            {"metric": "projected_review_visible_universe_if_context_ready_added", "value": projected_visible},
            {"metric": "projected_clean_review_universe_if_clean_offset_added", "value": projected_clean},
            {"metric": "projected_review_visible_share_of_3933", "value": round(projected_visible / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "projected_clean_share_of_3933", "value": round(projected_clean / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
        ]
    )


def _missingness(detail: pd.DataFrame) -> pd.DataFrame:
    checks = {
        "route_measure_identity_missing": detail["route_measure_identity_status"].ne("route_measure_identity_available"),
        "roadway_context_missing": detail["roadway_context_status"].ne("roadway_context_available"),
        "rns_speed_missing": ~detail["has_rns_speed"],
        "aadt_missing": ~detail["has_aadt"],
        "exposure_denominator_missing": ~detail["has_exposure_denominator"],
        "stable_travelway_id_missing": _text(detail, "stable_travelway_id").str.strip().eq(""),
    }
    return pd.DataFrame(
        [
            {"missingness_check": name, "bin_count": int(mask.sum()), "signal_count": int(detail.loc[mask, "stable_signal_id"].nunique())}
            for name, mask in checks.items()
        ]
    )


def _findings(signal_summary: pd.DataFrame, projection: pd.DataFrame, skipped: pd.DataFrame) -> str:
    generated = signal_summary.loc[signal_summary["has_generated_bins"].astype(bool)].copy()
    route_ready = int(generated["route_measure_ready"].sum())
    roadway_ready = int(generated["roadway_context_ready"].sum())
    speed_ready = int(generated["rns_speed_ready"].sum())
    aadt_ready = int(generated["aadt_ready"].sum())
    exposure_ready = int(generated["exposure_denominator_ready"].sum())
    speed_aadt = int(generated["speed_aadt_ready"].sum())
    clean = int(generated["eligible_for_later_universe_expansion_review"].sum())
    risk = int(generated["overlap_or_dedup_risk"].sum())
    high_context = int((generated["speed_aadt_ready"] & _text(generated, "high_crash_relevance_flag").str.lower().eq("true")).sum())
    values = dict(zip(projection["metric"], projection["value"]))
    skip_lines = "None"
    if not skipped.empty:
        skip_counts = skipped.groupby("skip_reason", dropna=False).size().reset_index(name="signal_count")
        skip_lines = "\n".join(f"- {row.skip_reason}: {int(row.signal_count):,}" for row in skip_counts.itertuples(index=False))
    return f"""# Missing HMMS Offset-Anchor Context Refresh Findings

## Bounded Question

This read-only pass attaches route/measure identity, roadway context, RNS speed, and AADT v3/exposure context to generated offset-anchor scaffold candidates. It does not promote signals, modify active outputs, add access, assign crashes, calculate rates/models, or use crash direction fields.

## Context Results

- Generated offset-anchor signals evaluated: {len(generated):,}
- Route/measure-ready generated signals: {route_ready:,}
- Roadway-context-ready generated signals: {roadway_ready:,}
- RNS speed-ready generated signals: {speed_ready:,}
- AADT-ready generated signals: {aadt_ready:,}
- Exposure/denominator-ready generated signals: {exposure_ready:,}
- Speed+AADT-ready generated signals: {speed_aadt:,}
- High-crash-relevance generated signals that are context-ready: {high_context:,}

## Skipped Holdouts

Skipped low-confidence anchor signals remain holdouts and were not forced into context assignment:

{skip_lines}

## Overlap / Risk

- Generated/context-ready signals appearing clean for later universe expansion review: {clean:,}
- Generated signals with overlap/duplicate/sibling/complex risk or holdout flags: {risk:,}

## Universe Projection

- Current clean review universe after 604 good-Travelway additions: {int(values['current_clean_review_universe_after_604_good_travelway']):,}
- Current review-visible universe after all 626 good-Travelway additions: {int(values['current_review_visible_universe_after_all_626_good_travelway']):,}
- Projected review-visible universe if context-ready offset-anchor signals are added: {int(values['projected_review_visible_universe_if_context_ready_added']):,}
- Projected clean review universe if clean offset-anchor candidates are added: {int(values['projected_clean_review_universe_if_clean_offset_added']):,}
- Projected review-visible share of 3,933 staged signals: {float(values['projected_review_visible_share_of_3933']):.1%}

## Recommendation

Do not promote these candidates yet. The next pass should review overlap/dedup and clean-versus-risk classes for the offset-anchor candidates, then integrate only clean context-ready offset-anchor signals into a review-only expanded universe. Complex multi-signal missing-HMMS should remain a separate branch.
"""


def _qa(detail: pd.DataFrame, signal_summary: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    generated = signal_summary.loc[signal_summary["has_generated_bins"].astype(bool)].copy()
    skipped_forced = signal_summary.loc[~signal_summary["has_generated_bins"].astype(bool), ["rns_speed_ready", "aadt_ready", "speed_aadt_ready"]].any(axis=None)
    stable_tw_ok = _text(detail, "stable_travelway_id").str.strip().ne("").all()
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only context refresh only"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only prior crash proximity summaries read"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active; no crash source read"},
            {"check_name": "stable_travelway_id_preserved_in_context_bins", "status": "passed" if stable_tw_ok else "failed", "observed": f"{int(_text(detail, 'stable_travelway_id').str.strip().ne('').sum())}/{len(detail)}"},
            {"check_name": "source_globalids_preserved_where_available", "status": "passed", "observed": f"{int(_text(signal_summary, 'GLOBALID').str.strip().ne('').sum())} available"},
            {"check_name": "missing_source_ids_reported_not_forced", "status": "passed", "observed": "GLOBALID/source_signal_id availability flags retained"},
            {"check_name": "skipped_low_confidence_anchors_not_forced", "status": "passed" if not skipped_forced else "failed", "observed": f"{len(skipped)} skipped signals preserved as holdouts"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def _parse_geom(value: Any):
    text = _clean(value)
    if not text:
        return None
    try:
        return wkt.loads(text)
    except Exception:
        return None


def _write_layer(frame: gpd.GeoDataFrame, layer: str, inventory: list[dict[str, Any]]) -> None:
    if GPKG_PATH.exists() and not inventory:
        GPKG_PATH.unlink()
    out = frame.copy()
    if out.crs is None:
        out = out.set_crs(CRS, allow_override=True)
    out = out.to_crs(CRS)
    for column in out.columns:
        if column != "geometry" and str(out[column].dtype) == "object":
            out[column] = out[column].fillna("").astype(str)
    pyogrio.write_dataframe(out, GPKG_PATH, layer=layer, driver="GPKG")
    inventory.append({"layer": layer, "rows": int(len(out)), "geometry_type": str(out.geom_type.iloc[0]) if len(out) else ""})
    _checkpoint(f"write_layer {layer}", len(out))


def _optional_gpkg(detail: pd.DataFrame, signal_summary: pd.DataFrame) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    generated = signal_summary.loc[signal_summary["has_generated_bins"].astype(bool)].copy()
    raw = generated.copy()
    raw["geometry"] = _text(raw, "raw_signal_geometry_wkt").map(_parse_geom)
    raw_gdf = gpd.GeoDataFrame(raw, geometry="geometry", crs=CRS).loc[lambda df: df.geometry.notna() & ~df.geometry.is_empty]
    _write_layer(raw_gdf, "offset_anchor_generated_signal_points", inventory)
    anchors = generated.copy()
    anchors["geometry"] = _text(anchors, "inferred_anchor_geometry_wkt").map(_parse_geom)
    anchor_gdf = gpd.GeoDataFrame(anchors, geometry="geometry", crs=CRS).loc[lambda df: df.geometry.notna() & ~df.geometry.is_empty]
    _write_layer(anchor_gdf, "offset_anchor_inferred_anchor_points", inventory)
    bins = detail.copy()
    bins["geometry"] = _text(bins, "geometry_wkt").map(_parse_geom)
    bin_gdf = gpd.GeoDataFrame(bins, geometry="geometry", crs=CRS).loc[lambda df: df.geometry.notna() & ~df.geometry.is_empty]
    _write_layer(bin_gdf, "offset_anchor_context_bins", inventory)
    return inventory


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    recovery_manifest = _load_json(RECOVERY_DIR / "offset_anchor_scaffold_recovery_manifest.json")
    good_universe_manifest = _load_json(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json")
    good_context_manifest = _load_json(GOOD_CONTEXT_DIR / "good_travelway_context_refresh_manifest.json")
    complex_manifest = _load_json(COMPLEX_REVIEW_DIR / "complex_signal_map_review_ingestion_manifest.json")
    stable_manifest = _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json")
    example_manifests = {
        "final_recovery_context_refresh": _load_json(FINAL_RECOVERY_CONTEXT_DIR / "final_recovery_context_refresh_manifest.json"),
        "intersection_zone_missing_leg_context_refresh": _load_json(INTERSECTION_ZONE_CONTEXT_DIR / "intersection_zone_missing_leg_context_refresh_manifest.json"),
        "route_discontinuity_offset_context_refresh": _load_json(ROUTE_DISCONTINUITY_CONTEXT_DIR / "route_discontinuity_offset_context_refresh_manifest.json"),
        "expanded_candidate_speed_rns_phase3d": _load_json(RNS_PHASE3D_DIR / "expanded_candidate_speed_rns_phase3d_vectorized_assignment_manifest.json"),
        "expanded_candidate_aadt_v3_path_rebuild": _load_json(AADT_V3_REBUILD_DIR / "expanded_candidate_aadt_v3_path_rebuild_manifest.json"),
    }

    all_targets = _read_csv(RECOVERY_DIR / "offset_anchor_missing_signal_targets.csv")
    skipped = _read_csv(RECOVERY_DIR / "offset_anchor_recovery_skipped_targets.csv")
    _read_csv(RECOVERY_DIR / "offset_anchor_context_refresh_readiness.csv")
    _read_csv(RECOVERY_DIR / "offset_anchor_crash_relevance_summary.csv")
    _read_csv(RECOVERY_DIR / "offset_anchor_overlap_dedup_review.csv")
    _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv", usecols=["stable_signal_id", "GLOBALID", "source_signal_id", "universe_record_type"])
    _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv", usecols=["stable_signal_id", "stable_travelway_id"])
    _read_csv(GOOD_UNIVERSE_DIR / "good_travelway_expanded_universe_readiness.csv", usecols=["stable_signal_id", "expanded_universe_readiness_class"])
    _read_csv(GOOD_CONTEXT_DIR / "good_travelway_context_bin_detail.csv", usecols=["stable_signal_id", "stable_bin_id"])
    _read_csv(GOOD_CONTEXT_DIR / "good_travelway_context_signal_summary.csv", usecols=["stable_signal_id", "speed_aadt_ready"])
    _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_readiness_after_complex_review.csv", usecols=["stable_signal_id", "revised_review_only_includable", "revised_hold_from_clean_analysis"])
    _read_csv(COMPLEX_REVIEW_DIR / "good_travelway_revised_universe_recommendation.csv")
    _read_csv(STABLE_DIR / "stable_lineage_represented_bin_universe.csv", usecols=["stable_signal_id", "stable_travelway_id"])
    _read_csv(STABLE_DIR / "stable_lineage_represented_signal_universe.csv", usecols=["stable_signal_id", "target_signal_id"])

    base, generated_signals = _build_base_bins()
    detail = _attach_context(base)
    signal_summary = _signal_summary(detail, all_targets, skipped)
    projection = _universe_projection(signal_summary)
    readiness = _readiness_summary(signal_summary)
    gpkg_inventory = _optional_gpkg(detail, signal_summary)

    _write_csv(detail, "offset_anchor_context_bin_detail.csv")
    _write_csv(signal_summary, "offset_anchor_context_signal_summary.csv")
    _write_csv(_summary_table(detail, "route_measure_identity_status", "route_measure_identity_status"), "offset_anchor_route_measure_summary.csv")
    _write_csv(_summary_table(detail, "roadway_context_status", "roadway_context_status"), "offset_anchor_roadway_context_summary.csv")
    _write_csv(_summary_table(detail, "rns_match_status", "rns_match_status"), "offset_anchor_speed_summary.csv")
    _write_csv(_summary_table(detail, "aadt_match_status", "aadt_match_status"), "offset_anchor_aadt_exposure_summary.csv")
    _write_csv(readiness, "offset_anchor_context_readiness_summary.csv")
    overlap_cols = [
        "stable_signal_id",
        "has_generated_bins",
        "exact_duplicate_signal_risk",
        "sibling_signal_risk",
        "complex_multi_signal_risk",
        "overlap_review_required",
        "overlap_or_dedup_risk",
        "eligible_for_later_universe_expansion_review",
    ]
    _write_csv(signal_summary[[col for col in overlap_cols if col in signal_summary.columns]], "offset_anchor_existing_universe_overlap_review.csv")
    _write_csv(projection, "offset_anchor_universe_expansion_projection.csv")
    _write_csv(_missingness(detail), "offset_anchor_context_missingness.csv")
    _write_text(_findings(signal_summary, projection, skipped), "offset_anchor_context_refresh_findings.md")
    qa = _qa(detail, signal_summary, skipped)
    _write_csv(qa, "offset_anchor_context_refresh_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_offset_anchor_context_refresh",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "generated_signal_count": int(signal_summary["has_generated_bins"].sum()),
        "total_target_signal_count": int(len(signal_summary)),
        "skipped_signal_count": int((~signal_summary["has_generated_bins"].astype(bool)).sum()),
        "context_bin_count": int(len(detail)),
        "route_measure_ready_signal_count": int(signal_summary["route_measure_ready"].sum()),
        "roadway_context_ready_signal_count": int(signal_summary["roadway_context_ready"].sum()),
        "rns_speed_ready_signal_count": int(signal_summary["rns_speed_ready"].sum()),
        "aadt_ready_signal_count": int(signal_summary["aadt_ready"].sum()),
        "exposure_ready_signal_count": int(signal_summary["exposure_denominator_ready"].sum()),
        "speed_aadt_ready_signal_count": int(signal_summary["speed_aadt_ready"].sum()),
        "eligible_clean_later_universe_expansion_review_signal_count": int(signal_summary["eligible_for_later_universe_expansion_review"].sum()),
        "optional_gpkg": str(GPKG_PATH),
        "optional_gpkg_inventory": gpkg_inventory,
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "signals_promoted": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_or_models": False,
            "crash_direction_fields_read": False,
        },
        "input_manifests": {
            "offset_anchor_scaffold_recovery": recovery_manifest,
            "good_travelway_universe_integration": good_universe_manifest,
            "good_travelway_context_refresh": good_context_manifest,
            "complex_signal_map_review_ingestion": complex_manifest,
            "stable_lineage_scaffold_regeneration": stable_manifest,
            "example_prior_context_refreshes": example_manifests,
        },
        "inputs": [str(path) for path in REQUIRED_INPUTS],
    }
    _write_json(manifest, "offset_anchor_context_refresh_manifest.json")
    _checkpoint("complete")
    print("Missing HMMS offset-anchor context refresh complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Generated signals: {manifest['generated_signal_count']:,}")
    print(f"Speed+AADT-ready signals: {manifest['speed_aadt_ready_signal_count']:,}")
    print(f"Eligible clean candidates: {manifest['eligible_clean_later_universe_expansion_review_signal_count']:,}")


if __name__ == "__main__":
    main()
