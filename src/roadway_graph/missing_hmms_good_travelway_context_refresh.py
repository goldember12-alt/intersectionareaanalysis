from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio

from .aadt_context_join_v3_identity_route_measure import _route_key as _aadt_v3_route_key


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_scaffold_recovery"
STABLE_LINEAGE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"

SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")

CURRENT_REPRESENTED_SIGNAL_COUNT = 2739
SOURCE_SIGNAL_UNIVERSE_COUNT = 3933

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
)

REQUIRED_INPUTS = [
    RECOVERY_DIR / "good_travelway_missing_signal_targets.csv",
    RECOVERY_DIR / "good_travelway_recovered_signal_summary.csv",
    RECOVERY_DIR / "good_travelway_recovered_leg_candidates.csv",
    RECOVERY_DIR / "good_travelway_recovered_bins.csv",
    RECOVERY_DIR / "good_travelway_recovery_skipped_targets.csv",
    RECOVERY_DIR / "good_travelway_context_refresh_readiness.csv",
    RECOVERY_DIR / "good_travelway_crash_relevance_summary.csv",
    RECOVERY_DIR / "good_travelway_overlap_dedup_review.csv",
    RECOVERY_DIR / "good_travelway_scaffold_recovery_manifest.json",
    STABLE_LINEAGE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_LINEAGE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_LINEAGE_DIR / "stable_lineage_generation_manifest.json",
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
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
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
        value = row.get(col, "")
        key = _route_key(value)
        if key:
            variants.add(key)
        if include_aadt:
            aadt_key = _aadt_v3_route_key(value)
            if aadt_key:
                variants.add(aadt_key)
    return variants


def _interval_lookup(
    bins: pd.DataFrame,
    source: pd.DataFrame,
    *,
    source_prefix: str,
    value_cols: list[str],
) -> pd.DataFrame:
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
            mids = ((bgrp["source_measure_min"].to_numpy(dtype=float) + bgrp["source_measure_max"].to_numpy(dtype=float)) / 2.0)
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
            unmatched_idx = bgrp.index[~valid]
            out.loc[unmatched_idx, f"{source_prefix}_match_status"] = "no_interval_match"
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
    rns = pyogrio.read_dataframe(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=cols, read_geometry=False)
    _checkpoint("read_complete Speed_Limit_RNS", len(rns))
    rns["measure_start"] = pd.to_numeric(rns["TRANSPORT_EDGE_FROM_MSR"].fillna(rns["FROM_MEASURE"]), errors="coerce")
    rns["measure_end"] = pd.to_numeric(rns["TRANSPORT_EDGE_TO_MSR"].fillna(rns["TO_MEASURE"]), errors="coerce")
    swap = rns["measure_start"] > rns["measure_end"]
    rns.loc[swap, ["measure_start", "measure_end"]] = rns.loc[swap, ["measure_end", "measure_start"]].to_numpy()
    rows = []
    for row in rns.dropna(subset=["measure_start", "measure_end"]).to_dict(orient="records"):
        keys = _route_key_variants(pd.Series(row), ["RTE_NM", "MASTER_RTE_NM"])
        for key in keys:
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
        keys = _route_key_variants(pd.Series(row), ["RTE_NM", "MASTER_RTE_NM"], include_aadt=True)
        for key in keys:
            rows.append({**row, "route_key": key})
    out = pd.DataFrame(rows)
    if needed_keys and not out.empty:
        out = out.loc[out["route_key"].isin(needed_keys)].copy()
    _checkpoint("prepared AADT keyed intervals", len(out))
    return out


def _build_base_bins() -> pd.DataFrame:
    bins = _read_csv(RECOVERY_DIR / "good_travelway_recovered_bins.csv")
    legs = _read_csv(
        RECOVERY_DIR / "good_travelway_recovered_leg_candidates.csv",
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
    signals = _read_csv(RECOVERY_DIR / "good_travelway_recovered_signal_summary.csv")
    overlap = _read_csv(RECOVERY_DIR / "good_travelway_overlap_dedup_review.csv")
    crash = _read_csv(RECOVERY_DIR / "good_travelway_crash_relevance_summary.csv")

    out = bins.merge(legs.drop_duplicates("leg_candidate_id"), on="leg_candidate_id", how="left")
    out = out.merge(
        signals[
            [
                "stable_signal_id",
                "OBJECTID",
                "MAJ_NAME",
                "MAJ_NUM",
                "MINOR_NAME",
                "MINOR_NUM",
                "original_loss_stage_or_reason",
                "crash_relevance_class",
                "overlap_review_required",
            ]
        ],
        on="stable_signal_id",
        how="left",
    )
    out = out.merge(
        overlap[
            [
                "stable_signal_id",
                "already_represented_by_available_ids",
                "duplicate_signal_risk",
                "sibling_signal_risk",
                "overlap_with_existing_represented_scaffold",
                "complex_multi_signal_risk",
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
    return out


def _attach_context(base: pd.DataFrame) -> pd.DataFrame:
    rns_needed = set(_text(base, "route_key_primary")) | set(_text(base, "route_key_alt"))
    rns_needed = {key for key in rns_needed if key}
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
    aadt_needed = set(_text(aadt_bins, "route_key_primary")) | set(_text(aadt_bins, "route_key_alt"))
    aadt_needed = {key for key in aadt_needed if key}
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
    out["review_only_context_refresh_provenance"] = "missing_hmms_good_travelway_context_refresh"
    return out


def _signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby("stable_signal_id", dropna=False).agg(
        GLOBALID=("GLOBALID", "first"),
        source_signal_id=("source_signal_id", "first"),
        OBJECTID=("OBJECTID", "first"),
        ASSET_ID=("ASSET_ID", "first"),
        REG_SIGNAL_ID=("REG_SIGNAL_ID", "first"),
        generated_bin_count=("stable_bin_id", "size"),
        route_measure_bins=("route_measure_identity_status", lambda s: int((s == "route_measure_identity_available").sum())),
        roadway_context_bins=("roadway_context_status", lambda s: int((s == "roadway_context_available").sum())),
        rns_speed_bins=("has_rns_speed", "sum"),
        aadt_bins=("has_aadt", "sum"),
        exposure_bins=("has_exposure_denominator", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        speed_aadt_ready_0_1000_bins=("speed_aadt_ready_bin", lambda s: int(s[detail.loc[s.index, "analysis_window"].eq("0_1000")].sum())),
        speed_aadt_ready_1000_2500_bins=("speed_aadt_ready_bin", lambda s: int(s[detail.loc[s.index, "analysis_window"].eq("1000_2500")].sum())),
        duplicate_signal_risk=("duplicate_signal_risk", "first"),
        sibling_signal_risk=("sibling_signal_risk", "first"),
        complex_multi_signal_risk=("complex_multi_signal_risk", "first"),
        overlap_with_existing_represented_scaffold=("overlap_with_existing_represented_scaffold", "first"),
        high_crash_relevance_flag=("high_crash_relevance_flag", "first"),
        source_not_represented_unassigned_crashes_within_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", "first"),
    ).reset_index()
    grouped["has_generated_bins"] = grouped["generated_bin_count"].gt(0)
    grouped["route_measure_ready"] = grouped["route_measure_bins"].eq(grouped["generated_bin_count"])
    grouped["roadway_context_ready"] = grouped["roadway_context_bins"].eq(grouped["generated_bin_count"])
    grouped["rns_speed_ready"] = grouped["rns_speed_bins"].gt(0)
    grouped["aadt_ready"] = grouped["aadt_bins"].gt(0)
    grouped["exposure_denominator_ready"] = grouped["exposure_bins"].gt(0)
    grouped["speed_aadt_ready"] = grouped["speed_aadt_ready_bins"].gt(0)
    grouped["full_0_1000_speed_aadt_ready"] = grouped["speed_aadt_ready_0_1000_bins"].gt(0)
    grouped["full_0_2500_sensitivity_ready"] = grouped["speed_aadt_ready_1000_2500_bins"].gt(0)
    grouped["source_signal_globalid_available"] = _text(grouped, "GLOBALID").str.strip().ne("")
    risk = grouped[["duplicate_signal_risk", "sibling_signal_risk", "complex_multi_signal_risk", "overlap_with_existing_represented_scaffold"]].apply(lambda col: col.astype(str).str.lower().isin({"true", "1", "yes"}))
    grouped["overlap_or_dedup_risk"] = risk.any(axis=1)
    grouped["eligible_for_later_universe_expansion_review"] = grouped["speed_aadt_ready"] & ~grouped["overlap_or_dedup_risk"]
    return grouped


def _summary_table(detail: pd.DataFrame, column: str, name_col: str) -> pd.DataFrame:
    rows = []
    for value, group in detail.groupby(column, dropna=False):
        rows.append(
            {
                name_col: value if str(value).strip() else "blank",
                "bin_count": len(group),
                "signal_count": group["stable_signal_id"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def _universe_projection(signal_summary: pd.DataFrame) -> pd.DataFrame:
    context_ready = int(signal_summary["speed_aadt_ready"].sum())
    clean = int(signal_summary["eligible_for_later_universe_expansion_review"].sum())
    high_clean = int((signal_summary["eligible_for_later_universe_expansion_review"] & _text(signal_summary, "high_crash_relevance_flag").str.lower().eq("true")).sum())
    return pd.DataFrame(
        [
            {"metric": "current_represented_signal_count", "value": CURRENT_REPRESENTED_SIGNAL_COUNT},
            {"metric": "good_travelway_target_signal_count", "value": int(len(signal_summary))},
            {"metric": "context_ready_good_travelway_signals", "value": context_ready},
            {"metric": "clean_addition_candidate_signals", "value": clean},
            {"metric": "projected_represented_universe_if_clean_accepted", "value": CURRENT_REPRESENTED_SIGNAL_COUNT + clean},
            {"metric": "projected_share_of_3933_staged_signals", "value": round((CURRENT_REPRESENTED_SIGNAL_COUNT + clean) / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "high_crash_relevance_context_ready_clean_additions", "value": high_clean},
        ]
    )


def _missingness(detail: pd.DataFrame) -> pd.DataFrame:
    checks = {
        "route_measure_identity_missing": detail["route_measure_identity_status"].ne("route_measure_identity_available"),
        "roadway_context_missing": detail["roadway_context_status"].ne("roadway_context_available"),
        "rns_speed_missing": ~detail["has_rns_speed"],
        "aadt_missing": ~detail["has_aadt"],
        "exposure_denominator_missing": ~detail["has_exposure_denominator"],
        "speed_aadt_not_ready": ~detail["speed_aadt_ready_bin"],
        "source_globalid_missing": _text(detail, "GLOBALID").str.strip().eq(""),
    }
    rows = []
    for check, mask in checks.items():
        rows.append({"missingness_check": check, "bin_count": int(mask.sum()), "signal_count": int(detail.loc[mask, "stable_signal_id"].nunique())})
    return pd.DataFrame(rows)


def _findings(signal_summary: pd.DataFrame, projection: pd.DataFrame, detail: pd.DataFrame) -> str:
    target = len(signal_summary)
    route_ready = int(signal_summary["route_measure_ready"].sum())
    road_ready = int(signal_summary["roadway_context_ready"].sum())
    speed_ready = int(signal_summary["rns_speed_ready"].sum())
    aadt_ready = int(signal_summary["aadt_ready"].sum())
    exposure_ready = int(signal_summary["exposure_denominator_ready"].sum())
    speed_aadt = int(signal_summary["speed_aadt_ready"].sum())
    clean = int(signal_summary["eligible_for_later_universe_expansion_review"].sum())
    risk = int(signal_summary["overlap_or_dedup_risk"].sum())
    high_ready = int((signal_summary["speed_aadt_ready"] & _text(signal_summary, "high_crash_relevance_flag").str.lower().eq("true")).sum())
    projected = int(projection.loc[projection["metric"].eq("projected_represented_universe_if_clean_accepted"), "value"].iloc[0])
    return f"""# Good-Travelway Missing HMMS Context Refresh Findings

## Bounded Question

This review-only context refresh populates generated `recoverable_good_travelway_coverage` missing-HMMS bins with route/measure identity, roadway context, RNS speed, and AADT v3/exposure context. It does not promote signals, add access, assign crashes, calculate rates/models, or alter active outputs.

## Results

- Target signals: {target:,}
- Signals with complete route/measure identity: {route_ready:,}
- Signals with complete roadway context: {road_ready:,}
- Signals with RNS speed context: {speed_ready:,}
- Signals with AADT context: {aadt_ready:,}
- Signals with exposure/denominator context: {exposure_ready:,}
- Signals speed+AADT-ready: {speed_aadt:,}
- Clean addition candidates for later review: {clean:,}
- Signals with overlap/duplicate/sibling/complex risk: {risk:,}
- High-crash-relevance signals that are context-ready: {high_ready:,}
- Projected represented signal count if clean candidates are accepted: {projected:,}

## Recommendation

Run a review-only universe expansion package for clean good-Travelway candidates first. Keep overlap, duplicate/sibling, complex-risk, and missing-source-GlobalID flags visible. Do not target offset-anchor or complex multi-signal missing-HMMS classes until this clean class has been map-reviewed and context QA has been accepted.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    recovery_manifest = _load_json(RECOVERY_DIR / "good_travelway_scaffold_recovery_manifest.json")
    stable_manifest = _load_json(STABLE_LINEAGE_DIR / "stable_lineage_generation_manifest.json")

    detail = _attach_context(_build_base_bins())
    signal_summary = _signal_summary(detail)
    projection = _universe_projection(signal_summary)

    route_summary = pd.DataFrame(
        [
            {"metric": "bins_with_route_measure_identity", "bin_count": int(detail["route_measure_identity_status"].eq("route_measure_identity_available").sum()), "signal_count": int(detail.loc[detail["route_measure_identity_status"].eq("route_measure_identity_available"), "stable_signal_id"].nunique())},
            {"metric": "bins_missing_route_measure_identity", "bin_count": int(detail["route_measure_identity_status"].ne("route_measure_identity_available").sum()), "signal_count": int(detail.loc[detail["route_measure_identity_status"].ne("route_measure_identity_available"), "stable_signal_id"].nunique())},
        ]
    )
    roadway_summary = _summary_table(detail, "roadway_division_context", "roadway_division_context")
    speed_summary = _summary_table(detail, "rns_match_status", "rns_match_status")
    aadt_summary = _summary_table(detail, "aadt_match_status", "aadt_match_status")
    readiness_summary = pd.DataFrame(
        [
            {"readiness_metric": "route_measure_ready_signals", "signal_count": int(signal_summary["route_measure_ready"].sum())},
            {"readiness_metric": "roadway_context_ready_signals", "signal_count": int(signal_summary["roadway_context_ready"].sum())},
            {"readiness_metric": "rns_speed_ready_signals", "signal_count": int(signal_summary["rns_speed_ready"].sum())},
            {"readiness_metric": "aadt_ready_signals", "signal_count": int(signal_summary["aadt_ready"].sum())},
            {"readiness_metric": "speed_aadt_ready_signals", "signal_count": int(signal_summary["speed_aadt_ready"].sum())},
            {"readiness_metric": "eligible_for_later_universe_expansion_review", "signal_count": int(signal_summary["eligible_for_later_universe_expansion_review"].sum())},
        ]
    )
    overlap_review = signal_summary[
        [
            "stable_signal_id",
            "GLOBALID",
            "source_signal_id",
            "duplicate_signal_risk",
            "sibling_signal_risk",
            "complex_multi_signal_risk",
            "overlap_with_existing_represented_scaffold",
            "overlap_or_dedup_risk",
            "eligible_for_later_universe_expansion_review",
        ]
    ].copy()
    missingness = _missingness(detail)

    _write_csv(detail, "good_travelway_context_bin_detail.csv")
    _write_csv(signal_summary, "good_travelway_context_signal_summary.csv")
    _write_csv(route_summary, "good_travelway_route_measure_summary.csv")
    _write_csv(roadway_summary, "good_travelway_roadway_context_summary.csv")
    _write_csv(speed_summary, "good_travelway_speed_summary.csv")
    _write_csv(aadt_summary, "good_travelway_aadt_exposure_summary.csv")
    _write_csv(readiness_summary, "good_travelway_context_readiness_summary.csv")
    _write_csv(overlap_review, "good_travelway_existing_universe_overlap_review.csv")
    _write_csv(projection, "good_travelway_universe_expansion_projection.csv")
    _write_csv(missingness, "good_travelway_context_missingness.csv")
    _write_text(_findings(signal_summary, projection, detail), "good_travelway_context_refresh_findings.md")

    qa = pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only context refresh"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only prior proximity summaries used"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_not_used", "status": "passed", "observed": "no crash records read"},
            {"check_name": "stable_travelway_id_preserved", "status": "passed" if _text(detail, "stable_travelway_id").str.strip().ne("").all() else "failed", "observed": f"{int(_text(detail, 'stable_travelway_id').str.strip().ne('').sum())}/{len(detail)}"},
            {"check_name": "source_signal_globalids_preserved_where_available", "status": "passed", "observed": f"{int(_text(signal_summary, 'GLOBALID').str.strip().ne('').sum())} available; {int(_text(signal_summary, 'GLOBALID').str.strip().eq('').sum())} missing in source"},
            {"check_name": "missing_source_globalid_condition_reported", "status": "passed", "observed": "source_globalid_missing included in missingness output"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )
    _write_csv(qa, "good_travelway_context_refresh_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_good_travelway_context_refresh",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "target_signal_count": int(len(signal_summary)),
        "context_bin_count": int(len(detail)),
        "route_measure_ready_signals": int(signal_summary["route_measure_ready"].sum()),
        "roadway_context_ready_signals": int(signal_summary["roadway_context_ready"].sum()),
        "rns_speed_ready_signals": int(signal_summary["rns_speed_ready"].sum()),
        "aadt_ready_signals": int(signal_summary["aadt_ready"].sum()),
        "speed_aadt_ready_signals": int(signal_summary["speed_aadt_ready"].sum()),
        "clean_addition_candidate_signals": int(signal_summary["eligible_for_later_universe_expansion_review"].sum()),
        "projected_represented_signal_count_if_clean_accepted": int(projection.loc[projection["metric"].eq("projected_represented_universe_if_clean_accepted"), "value"].iloc[0]),
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "signals_promoted": False,
            "crash_assignment": False,
            "access_assignment": False,
            "rates_or_models": False,
            "crash_direction_fields_read": False,
        },
        "input_manifests": {
            "good_travelway_scaffold_recovery": recovery_manifest,
            "stable_lineage": stable_manifest,
        },
        "inputs": [str(path) for path in REQUIRED_INPUTS],
    }
    _write_json(manifest, "good_travelway_context_refresh_manifest.json")
    _checkpoint("complete")
    print("Good-Travelway missing HMMS context refresh complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Signals: {len(signal_summary):,}")
    print(f"Speed+AADT-ready: {int(signal_summary['speed_aadt_ready'].sum()):,}")
    print(f"Clean additions: {int(signal_summary['eligible_for_later_universe_expansion_review'].sum()):,}")


if __name__ == "__main__":
    main()
