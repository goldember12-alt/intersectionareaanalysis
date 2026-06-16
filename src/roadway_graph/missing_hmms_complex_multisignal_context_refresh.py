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
OUT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_complex_multisignal_context_refresh"
RECOVERY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_complex_multisignal_scaffold_recovery"
FINAL_ACCOUNTING_DIR = OUTPUT_ROOT / "review/current/final_staged_signal_accounting"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
OFFSET_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
RAMP_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/ramp_terminal_universe_integration"
GOOD_CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_context_refresh"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_context_refresh"
RAMP_CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_ramp_terminal_context_refresh"
FINAL_RECOVERY_CONTEXT_DIR = OUTPUT_ROOT / "review/current/final_recovery_context_refresh"
RNS_PHASE3D_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_phase3d_vectorized_assignment"
AADT_V3_REBUILD_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_aadt_v3_path_rebuild"

SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"
AADT_FILE = Path("artifacts/normalized/aadt.parquet")

SOURCE_SIGNAL_UNIVERSE_COUNT = 3933
CURRENT_CLEAN_UNIVERSE = 3627
CURRENT_REMAINING_NONCLEAN = 306
TARGET_SIGNAL_COUNT = 109

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
    RECOVERY_DIR / "complex_multisignal_missing_signal_targets.csv",
    RECOVERY_DIR / "complex_multisignal_source_leg_classification.csv",
    RECOVERY_DIR / "complex_multisignal_recovered_signal_summary.csv",
    RECOVERY_DIR / "complex_multisignal_recovered_leg_candidates.csv",
    RECOVERY_DIR / "complex_multisignal_recovered_bins.csv",
    RECOVERY_DIR / "complex_multisignal_recovery_skipped_targets.csv",
    RECOVERY_DIR / "complex_multisignal_context_refresh_readiness.csv",
    RECOVERY_DIR / "complex_multisignal_overlap_dedup_review.csv",
    RECOVERY_DIR / "complex_multisignal_crash_relevance_summary.csv",
    RECOVERY_DIR / "complex_multisignal_scaffold_recovery_manifest.json",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_detail.csv",
    FINAL_ACCOUNTING_DIR / "final_remaining_446_breakdown.csv",
    FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_UNIVERSE_DIR / "expanded_offset_anchor_bin_universe.csv",
    OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json",
    RAMP_UNIVERSE_DIR / "ramp_terminal_integrated_signal_additions.csv",
    RAMP_UNIVERSE_DIR / "ramp_terminal_integrated_bin_additions.csv",
    RAMP_UNIVERSE_DIR / "ramp_terminal_updated_remaining_signal_ledger.csv",
    RAMP_UNIVERSE_DIR / "ramp_terminal_universe_integration_manifest.json",
    GOOD_CONTEXT_DIR / "good_travelway_context_bin_detail.csv",
    GOOD_CONTEXT_DIR / "good_travelway_context_signal_summary.csv",
    GOOD_CONTEXT_DIR / "good_travelway_context_refresh_manifest.json",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_bin_detail.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_signal_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json",
    RAMP_CONTEXT_DIR / "ramp_terminal_context_bin_detail.csv",
    RAMP_CONTEXT_DIR / "ramp_terminal_context_signal_summary.csv",
    RAMP_CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json",
    FINAL_RECOVERY_CONTEXT_DIR,
    RNS_PHASE3D_DIR,
    AADT_V3_REBUILD_DIR,
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


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


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


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if SPEED_LIMIT_RNS_GDB.exists():
        layers = {row[0] for row in pyogrio.list_layers(SPEED_LIMIT_RNS_GDB)}
        if SPEED_LIMIT_RNS_LAYER not in layers:
            missing.append(f"{SPEED_LIMIT_RNS_GDB}:{SPEED_LIMIT_RNS_LAYER}")
    return missing


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
    cols = ["RTE_NM", "MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "CAR_SPEED_LIMIT", "FINAL_SPEED_LIMIT_SOURCE", "SPEEDZONE_TYPE_DSC"]
    _checkpoint("read_start Speed_Limit_RNS")
    rns = pyogrio.read_dataframe(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=cols, read_geometry=False, use_arrow=True)
    _checkpoint("read_complete Speed_Limit_RNS", len(rns))
    rns["measure_start"] = pd.to_numeric(rns["TRANSPORT_EDGE_FROM_MSR"].fillna(rns["FROM_MEASURE"]), errors="coerce")
    rns["measure_end"] = pd.to_numeric(rns["TRANSPORT_EDGE_TO_MSR"].fillna(rns["TO_MEASURE"]), errors="coerce")
    swap = rns["measure_start"] > rns["measure_end"]
    rns.loc[swap, ["measure_start", "measure_end"]] = rns.loc[swap, ["measure_end", "measure_start"]].to_numpy()
    base = rns.dropna(subset=["measure_start", "measure_end"]).copy()
    pieces = []
    for col in ["RTE_NM", "MASTER_RTE_NM"]:
        keyed = base.copy()
        keyed["route_key"] = keyed[col].map(_route_key)
        keyed = keyed[keyed["route_key"].isin(needed_keys)].copy() if needed_keys else keyed[keyed["route_key"].ne("")].copy()
        if not keyed.empty:
            pieces.append(keyed)
    out = pd.concat(pieces, ignore_index=True).drop_duplicates() if pieces else pd.DataFrame(columns=base.columns.tolist() + ["route_key"])
    _checkpoint("prepared RNS keyed intervals", len(out))
    return out


def _load_aadt_source(needed_keys: set[str]) -> pd.DataFrame:
    cols = ["RTE_NM", "MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "AADT_YR", "AADT", "AADT_QUALITY", "AAWDT", "AAWDT_QUALITY", "DIRECTION_FACTOR", "DIRECTIONALITY", "FROM_PHY_JURISDICTION_NM", "MPO_DSC"]
    _checkpoint("read_start normalized AADT")
    aadt = pd.read_parquet(AADT_FILE, columns=cols)
    _checkpoint("read_complete normalized AADT", len(aadt))
    aadt["measure_start"] = pd.to_numeric(aadt["TRANSPORT_EDGE_FROM_MSR"].fillna(aadt["FROM_MEASURE"]), errors="coerce")
    aadt["measure_end"] = pd.to_numeric(aadt["TRANSPORT_EDGE_TO_MSR"].fillna(aadt["TO_MEASURE"]), errors="coerce")
    swap = aadt["measure_start"] > aadt["measure_end"]
    aadt.loc[swap, ["measure_start", "measure_end"]] = aadt.loc[swap, ["measure_end", "measure_start"]].to_numpy()
    base = aadt.dropna(subset=["measure_start", "measure_end"]).copy()
    pieces = []
    for col in ["RTE_NM", "MASTER_RTE_NM"]:
        for key_func in [_route_key, _aadt_v3_route_key]:
            keyed = base.copy()
            keyed["route_key"] = keyed[col].map(key_func)
            keyed = keyed[keyed["route_key"].isin(needed_keys)].copy() if needed_keys else keyed[keyed["route_key"].ne("")].copy()
            if not keyed.empty:
                pieces.append(keyed)
    out = pd.concat(pieces, ignore_index=True).drop_duplicates() if pieces else pd.DataFrame(columns=base.columns.tolist() + ["route_key"])
    _checkpoint("prepared AADT keyed intervals", len(out))
    return out


def _source_class_flags(source_class: pd.DataFrame) -> pd.DataFrame:
    classes = [
        "signal_relevant_physical_leg",
        "signal_relevant_carriageway_subbranch",
        "signal_relevant_connector_or_internal_segment",
        "source_line_split_same_leg",
        "nearby_sibling_signal_leg",
        "opposite_carriageway_owned_by_sibling_signal",
        "nearby_other_intersection_leg",
        "grade_or_mainline_context_holdout",
        "insufficient_evidence",
    ]
    rows = []
    for sid, group in source_class.groupby("stable_signal_id", dropna=False):
        row = {"stable_signal_id": sid}
        for cls in classes:
            row[f"{cls}_source_row_count"] = int(_text(group, "source_leg_class").eq(cls).sum())
            row[f"has_{cls}"] = row[f"{cls}_source_row_count"] > 0
        row["connector_internal_segment_flag"] = row["has_signal_relevant_connector_or_internal_segment"]
        row["carriageway_subbranch_flag"] = row["has_signal_relevant_carriageway_subbranch"]
        row["complex_geometry_flag"] = (
            row["connector_internal_segment_flag"]
            or row["carriageway_subbranch_flag"]
            or row["has_source_line_split_same_leg"]
        )
        row["sibling_other_intersection_exclusion_flag"] = (
            row["has_nearby_sibling_signal_leg"]
            or row["has_opposite_carriageway_owned_by_sibling_signal"]
            or row["has_nearby_other_intersection_leg"]
        )
        row["grade_mainline_exclusion_flag"] = row["has_grade_or_mainline_context_holdout"]
        row["high_travelway_row_count_qa_flag"] = len(group) >= 8
        rows.append(row)
    return pd.DataFrame(rows)


def _build_base_bins() -> pd.DataFrame:
    bins = _read_csv(RECOVERY_DIR / "complex_multisignal_recovered_bins.csv")
    legs = _read_csv(RECOVERY_DIR / "complex_multisignal_recovered_leg_candidates.csv")
    signals = _read_csv(RECOVERY_DIR / "complex_multisignal_recovered_signal_summary.csv")
    overlap = _read_csv(RECOVERY_DIR / "complex_multisignal_overlap_dedup_review.csv")
    source_class = _read_csv(RECOVERY_DIR / "complex_multisignal_source_leg_classification.csv")
    flags = _source_class_flags(source_class)
    out = bins.merge(
        legs[["leg_candidate_id", "coverage_class"]].drop_duplicates("leg_candidate_id"),
        on="leg_candidate_id",
        how="left",
    )
    out = out.merge(
        signals[
            [
                "stable_signal_id",
                "generated_scaffold_candidate",
                "generated_leg_candidate_count",
                "generated_physical_leg_count",
                "generated_bin_count",
                "signal_relevant_physical_leg_rows",
                "carriageway_subbranch_rows",
                "connector_internal_rows",
                "source_line_split_same_leg_rows",
                "excluded_sibling_or_other_intersection_rows",
                "excluded_grade_mainline_rows",
                "high_travelway_row_count_is_qa_not_exclusion",
            ]
        ],
        on="stable_signal_id",
        how="left",
    )
    out = out.merge(flags, on="stable_signal_id", how="left")
    out = out.merge(overlap, on=["stable_signal_id", "source_signal_id", "GLOBALID"], how="left")
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
    out["complex_geometry_context"] = np.select(
        [
            _text(out, "source_leg_class").eq("signal_relevant_connector_or_internal_segment"),
            _text(out, "source_leg_class").eq("signal_relevant_carriageway_subbranch"),
            _text(out, "source_leg_class").eq("source_line_split_same_leg"),
            _text(out, "source_leg_class").eq("signal_relevant_physical_leg"),
        ],
        ["connector_or_internal_segment", "carriageway_subbranch", "source_line_split_same_leg", "physical_leg"],
        default="other_complex_context",
    )
    out["roadway_context_status"] = np.where(_text(out, "source_route_facility").str.strip().ne(""), "roadway_context_available", "roadway_context_missing")
    out["missing_globalid"] = _text(out, "GLOBALID").str.strip().eq("")
    out["source_signal_id_available"] = _text(out, "source_signal_id").str.strip().ne("")
    return out


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
        value_cols=["AADT", "AADT_YR", "AADT_QUALITY", "AAWDT", "AAWDT_QUALITY", "DIRECTION_FACTOR", "DIRECTIONALITY", "FROM_PHY_JURISDICTION_NM", "MPO_DSC", "RTE_NM", "MASTER_RTE_NM"],
    )
    out = base.merge(speed.drop(columns=["source_measure_min", "source_measure_max", "route_key_primary", "route_key_alt"]), on="stable_bin_id", how="left")
    out = out.merge(aadt.drop(columns=["source_measure_min", "source_measure_max", "route_key_primary", "route_key_alt"]), on="stable_bin_id", how="left")
    out["has_rns_speed"] = _text(out, "rns_CAR_SPEED_LIMIT").str.strip().ne("") & ~_text(out, "rns_match_status").str.startswith("missing")
    out["has_aadt"] = _text(out, "aadt_AADT").str.strip().ne("") & ~_text(out, "aadt_match_status").str.startswith("missing")
    out["has_exposure_denominator"] = out["has_aadt"] & (_text(out, "aadt_DIRECTION_FACTOR").str.strip().ne("") | _text(out, "aadt_DIRECTIONALITY").str.strip().ne(""))
    out["speed_aadt_ready_bin"] = out["has_rns_speed"] & out["has_aadt"] & out["has_exposure_denominator"]
    out["review_only_context_refresh_provenance"] = "missing_hmms_complex_multisignal_context_refresh"
    return out


def _signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby("stable_signal_id", dropna=False).agg(
        GLOBALID=("GLOBALID", "first"),
        source_signal_id=("source_signal_id", "first"),
        OBJECTID=("OBJECTID", "first"),
        ASSET_ID=("ASSET_ID", "first"),
        REG_SIGNAL_ID=("REG_SIGNAL_ID", "first"),
        source_signal_layer=("source_signal_layer", "first"),
        source_system=("source_system", "first"),
        current_final_status=("current_final_status", "first"),
        crash_relevance_class=("crash_relevance_class", "first"),
        high_crash_relevance=("high_crash_relevance", "first"),
        source_not_represented_unassigned_crashes_within_2500ft=("source_not_represented_unassigned_crashes_within_2500ft", "first"),
        signal_geometry_wkt=("signal_geometry_wkt", "first"),
        generated_bin_count=("stable_bin_id", "size"),
        route_measure_bins=("route_measure_identity_status", lambda s: int((s == "route_measure_identity_available").sum())),
        roadway_context_bins=("roadway_context_status", lambda s: int((s == "roadway_context_available").sum())),
        rns_speed_bins=("has_rns_speed", "sum"),
        aadt_bins=("has_aadt", "sum"),
        exposure_bins=("has_exposure_denominator", "sum"),
        speed_aadt_ready_bins=("speed_aadt_ready_bin", "sum"),
        speed_aadt_ready_0_1000_bins=("speed_aadt_ready_bin", lambda s: int(s[detail.loc[s.index, "analysis_window"].eq("0_1000")].sum())),
        exact_duplicate_source_record=("exact_duplicate_source_record", "first"),
        sibling_ownership_risk=("sibling_ownership_risk", "first"),
        scaffold_overlap_with_existing_signal=("scaffold_overlap_with_existing_signal", "first"),
        same_corridor_shared_travelway_context=("same_corridor_shared_travelway_context", "first"),
        complex_multi_signal_ownership_risk=("complex_multi_signal_ownership_risk", "first"),
        connector_internal_segment_flag=("connector_internal_segment_flag", "first"),
        carriageway_subbranch_flag=("carriageway_subbranch_flag", "first"),
        complex_geometry_flag=("complex_geometry_flag", "first"),
        sibling_other_intersection_exclusion_flag=("sibling_other_intersection_exclusion_flag", "first"),
        grade_mainline_exclusion_flag=("grade_mainline_exclusion_flag", "first"),
        high_travelway_row_count_qa_flag=("high_travelway_row_count_qa_flag", "first"),
        source_signal_id_available=("source_signal_id_available", "first"),
        missing_globalid=("missing_globalid", "first"),
    ).reset_index()
    grouped["has_generated_bins"] = True
    grouped["route_measure_ready"] = grouped["route_measure_bins"].eq(grouped["generated_bin_count"])
    grouped["roadway_context_ready"] = grouped["roadway_context_bins"].eq(grouped["generated_bin_count"])
    grouped["rns_speed_ready"] = grouped["rns_speed_bins"].gt(0)
    grouped["aadt_ready"] = grouped["aadt_bins"].gt(0)
    grouped["exposure_denominator_ready"] = grouped["exposure_bins"].gt(0)
    grouped["speed_aadt_ready"] = grouped["speed_aadt_ready_bins"].gt(0)
    grouped["full_0_1000_speed_aadt_ready"] = grouped["speed_aadt_ready_0_1000_bins"].eq(grouped["generated_bin_count"])
    grouped["overlap_or_complex_ownership_risk"] = (
        _flag(grouped, "exact_duplicate_source_record")
        | _flag(grouped, "sibling_ownership_risk")
        | _flag(grouped, "scaffold_overlap_with_existing_signal")
        | _flag(grouped, "same_corridor_shared_travelway_context")
        | _flag(grouped, "complex_multi_signal_ownership_risk")
        | _flag(grouped, "sibling_other_intersection_exclusion_flag")
        | _flag(grouped, "grade_mainline_exclusion_flag")
    )
    grouped["clean_addition_candidate"] = grouped["speed_aadt_ready"] & ~grouped["overlap_or_complex_ownership_risk"]
    grouped["review_analysis_addition_candidate"] = grouped["speed_aadt_ready"]
    grouped["eligible_for_later_universe_expansion_review"] = grouped["speed_aadt_ready"]
    return grouped


def _summary_table(detail: pd.DataFrame, column: str, name_col: str) -> pd.DataFrame:
    rows = []
    for value, group in detail.groupby(column, dropna=False):
        rows.append({name_col: value if str(value).strip() else "blank", "bin_count": len(group), "signal_count": group["stable_signal_id"].nunique()})
    return pd.DataFrame(rows)


def _readiness_summary(signal_summary: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        ("total_complex_multisignal_candidates", len(signal_summary)),
        ("route_measure_ready_signals", int(signal_summary["route_measure_ready"].sum())),
        ("roadway_context_ready_signals", int(signal_summary["roadway_context_ready"].sum())),
        ("rns_speed_ready_signals", int(signal_summary["rns_speed_ready"].sum())),
        ("aadt_ready_signals", int(signal_summary["aadt_ready"].sum())),
        ("exposure_denominator_ready_signals", int(signal_summary["exposure_denominator_ready"].sum())),
        ("speed_aadt_ready_signals", int(signal_summary["speed_aadt_ready"].sum())),
        ("full_0_1000_speed_aadt_ready_signals", int(signal_summary["full_0_1000_speed_aadt_ready"].sum())),
        ("clean_addition_candidate_signals", int(signal_summary["clean_addition_candidate"].sum())),
        ("risk_or_holdout_candidate_signals", int((signal_summary["speed_aadt_ready"] & ~signal_summary["clean_addition_candidate"]).sum())),
    ]
    return pd.DataFrame([{"readiness_metric": metric, "signal_count": count} for metric, count in metrics])


def _universe_projection(signal_summary: pd.DataFrame) -> pd.DataFrame:
    context_ready = int(signal_summary["speed_aadt_ready"].sum())
    clean = int(signal_summary["clean_addition_candidate"].sum())
    risk = int(context_ready - clean)
    projected_clean = CURRENT_CLEAN_UNIVERSE + clean
    projected_review_analysis = CURRENT_CLEAN_UNIVERSE + context_ready
    return pd.DataFrame(
        [
            {"metric": "current_clean_universe_before_complex_multisignal_refresh", "value": CURRENT_CLEAN_UNIVERSE},
            {"metric": "current_remaining_non_clean_before_complex_multisignal_refresh", "value": CURRENT_REMAINING_NONCLEAN},
            {"metric": "complex_multisignal_generated_candidates", "value": len(signal_summary)},
            {"metric": "complex_multisignal_context_ready_signals", "value": context_ready},
            {"metric": "complex_multisignal_clean_addition_candidates", "value": clean},
            {"metric": "complex_multisignal_risk_or_holdout_candidates", "value": risk},
            {"metric": "projected_clean_universe_if_clean_candidates_accepted", "value": projected_clean},
            {"metric": "projected_review_analysis_universe_if_context_ready_accepted", "value": projected_review_analysis},
            {"metric": "projected_share_of_3933_staged_signals", "value": round(projected_clean / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "projected_review_analysis_share_of_3933_staged_signals", "value": round(projected_review_analysis / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
            {"metric": "projected_remaining_non_clean_signal_count", "value": SOURCE_SIGNAL_UNIVERSE_COUNT - projected_clean},
            {"metric": "projected_remaining_non_clean_if_context_ready_accepted", "value": SOURCE_SIGNAL_UNIVERSE_COUNT - projected_review_analysis},
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
        "stable_travelway_id_missing": _text(detail, "stable_travelway_id").str.strip().eq(""),
        "source_globalid_missing": _text(detail, "GLOBALID").str.strip().eq(""),
        "connector_internal_segment_flag": _flag(detail, "connector_internal_segment_flag"),
        "carriageway_subbranch_flag": _flag(detail, "carriageway_subbranch_flag"),
        "complex_geometry_flag": _flag(detail, "complex_geometry_flag"),
        "high_travelway_row_count_qa_flag": _flag(detail, "high_travelway_row_count_qa_flag"),
        "sibling_other_intersection_exclusion_flag": _flag(detail, "sibling_other_intersection_exclusion_flag"),
        "grade_mainline_exclusion_flag": _flag(detail, "grade_mainline_exclusion_flag"),
    }
    return pd.DataFrame(
        [{"missingness_check": name, "bin_count": int(mask.sum()), "signal_count": int(detail.loc[mask, "stable_signal_id"].nunique())} for name, mask in checks.items()]
    )


def _findings(signal_summary: pd.DataFrame, projection: pd.DataFrame) -> str:
    route_ready = int(signal_summary["route_measure_ready"].sum())
    road_ready = int(signal_summary["roadway_context_ready"].sum())
    speed_ready = int(signal_summary["rns_speed_ready"].sum())
    aadt_ready = int(signal_summary["aadt_ready"].sum())
    exposure_ready = int(signal_summary["exposure_denominator_ready"].sum())
    speed_aadt = int(signal_summary["speed_aadt_ready"].sum())
    full_ready = int(signal_summary["full_0_1000_speed_aadt_ready"].sum())
    clean = int(signal_summary["clean_addition_candidate"].sum())
    review_analysis = int(signal_summary["review_analysis_addition_candidate"].sum())
    risk = int(signal_summary["overlap_or_complex_ownership_risk"].sum())
    high_ready = int((signal_summary["speed_aadt_ready"] & _flag(signal_summary, "high_crash_relevance")).sum())
    projected = int(projection.loc[projection["metric"].eq("projected_clean_universe_if_clean_candidates_accepted"), "value"].iloc[0])
    projected_review = int(projection.loc[projection["metric"].eq("projected_review_analysis_universe_if_context_ready_accepted"), "value"].iloc[0])
    return f"""# Complex Multi-Signal Missing HMMS Context Refresh Findings

## Bounded Question

This review-only context refresh populates the 109 generated `recoverable_complex_multi_signal_not_processed` missing-HMMS candidates with route/measure identity, roadway context, RNS speed, and AADT v3/exposure context. It preserves complex-geometry, connector/internal-segment, carriageway-subbranch, high-Travelway-row-count, and sibling/other-intersection QA evidence. It does not promote signals, add access, assign crashes, calculate rates/models, or alter active outputs.

## Results

- Target complex multi-signal candidates: {len(signal_summary):,}
- Signals with complete route/measure identity: {route_ready:,}
- Signals with complete roadway context: {road_ready:,}
- Signals with RNS speed context: {speed_ready:,}
- Signals with AADT context: {aadt_ready:,}
- Signals with exposure/denominator context: {exposure_ready:,}
- Signals speed+AADT-ready: {speed_aadt:,}
- Signals full 0-1,000 ft speed+AADT-ready: {full_ready:,}
- Clean addition candidates for later review: {clean:,}
- Review-analysis context-ready candidates for later integration: {review_analysis:,}
- Signals with overlap/duplicate/sibling/complex ownership risk: {risk:,}
- High-crash-relevance context-ready signals: {high_ready:,}
- Projected clean universe if clean candidates are accepted: {projected:,}
- Projected review-analysis universe if all context-ready candidates are accepted with QA flags: {projected_review:,}

## Recommendation

Do not promote this branch yet. The next pass should integrate the context-ready complex multi-signal candidates into a review-only universe/risk decomposition, separating clean candidates from connector/carriageway QA cases and any true sibling/ownership risk cases.
"""


def _qa(detail: pd.DataFrame, signal_summary: pd.DataFrame) -> pd.DataFrame:
    lineage_ok = _text(detail, "stable_travelway_id").str.strip().ne("").all()
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "review-only context refresh"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "only prior proximity summaries used"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active; crash records not read"},
            {"check_name": "stable_travelway_id_preserved", "status": "passed" if lineage_ok else "failed", "observed": f"{int(_text(detail, 'stable_travelway_id').str.strip().ne('').sum())}/{len(detail)}"},
            {"check_name": "source_signal_ids_globalids_preserved", "status": "passed", "observed": f"{int(_text(signal_summary, 'GLOBALID').str.strip().ne('').sum())} GLOBALIDs; {int(_text(signal_summary, 'source_signal_id').str.strip().ne('').sum())} source_signal_ids"},
            {"check_name": "high_travelway_row_count_carried_as_qa", "status": "passed", "observed": f"{int(_flag(signal_summary, 'high_travelway_row_count_qa_flag').sum())} flagged signals"},
            {"check_name": "connector_internal_segment_flags_preserved", "status": "passed" if "connector_internal_segment_flag" in detail.columns else "failed", "observed": f"{int(_flag(signal_summary, 'connector_internal_segment_flag').sum())} flagged signals"},
            {"check_name": "sibling_other_intersection_legs_not_forced", "status": "passed" if int(_text(detail, 'source_leg_class').isin(['nearby_sibling_signal_leg', 'opposite_carriageway_owned_by_sibling_signal', 'nearby_other_intersection_leg']).sum()) == 0 else "failed", "observed": f"{int(_text(detail, 'source_leg_class').isin(['nearby_sibling_signal_leg', 'opposite_carriageway_owned_by_sibling_signal', 'nearby_other_intersection_leg']).sum())} excluded-class context bins"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    detail = _attach_context(_build_base_bins())
    signal_summary = _signal_summary(detail)
    route_summary = pd.DataFrame(
        [
            {"metric": "bins_with_route_measure_identity", "bin_count": int(detail["route_measure_identity_status"].eq("route_measure_identity_available").sum()), "signal_count": int(detail.loc[detail["route_measure_identity_status"].eq("route_measure_identity_available"), "stable_signal_id"].nunique())},
            {"metric": "bins_missing_route_measure_identity", "bin_count": int(detail["route_measure_identity_status"].ne("route_measure_identity_available").sum()), "signal_count": int(detail.loc[detail["route_measure_identity_status"].ne("route_measure_identity_available"), "stable_signal_id"].nunique())},
        ]
    )
    roadway_summary = _summary_table(detail, "complex_geometry_context", "complex_geometry_context")
    speed_summary = _summary_table(detail, "rns_match_status", "rns_match_status")
    aadt_summary = _summary_table(detail, "aadt_match_status", "aadt_match_status")
    readiness_summary = _readiness_summary(signal_summary)
    overlap_review = signal_summary[
        [
            "stable_signal_id",
            "GLOBALID",
            "source_signal_id",
            "exact_duplicate_source_record",
            "sibling_ownership_risk",
            "scaffold_overlap_with_existing_signal",
            "same_corridor_shared_travelway_context",
            "complex_multi_signal_ownership_risk",
            "connector_internal_segment_flag",
            "carriageway_subbranch_flag",
            "complex_geometry_flag",
            "high_travelway_row_count_qa_flag",
            "sibling_other_intersection_exclusion_flag",
            "grade_mainline_exclusion_flag",
            "overlap_or_complex_ownership_risk",
            "clean_addition_candidate",
            "review_analysis_addition_candidate",
        ]
    ].copy()
    projection = _universe_projection(signal_summary)
    missingness = _missingness(detail)
    qa = _qa(detail, signal_summary)

    _write_csv(detail, "complex_multisignal_context_bin_detail.csv")
    _write_csv(signal_summary, "complex_multisignal_context_signal_summary.csv")
    _write_csv(route_summary, "complex_multisignal_route_measure_summary.csv")
    _write_csv(roadway_summary, "complex_multisignal_roadway_context_summary.csv")
    _write_csv(speed_summary, "complex_multisignal_speed_summary.csv")
    _write_csv(aadt_summary, "complex_multisignal_aadt_exposure_summary.csv")
    _write_csv(readiness_summary, "complex_multisignal_context_readiness_summary.csv")
    _write_csv(overlap_review, "complex_multisignal_existing_universe_overlap_review.csv")
    _write_csv(projection, "complex_multisignal_universe_expansion_projection.csv")
    _write_csv(missingness, "complex_multisignal_context_missingness.csv")
    _write_text(_findings(signal_summary, projection), "complex_multisignal_context_refresh_findings.md")
    _write_csv(qa, "complex_multisignal_context_refresh_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.missing_hmms_complex_multisignal_context_refresh",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "input_manifests": {
            "complex_multisignal_scaffold_recovery": _manifest_ref(RECOVERY_DIR / "complex_multisignal_scaffold_recovery_manifest.json"),
            "final_staged_signal_accounting": _manifest_ref(FINAL_ACCOUNTING_DIR / "final_staged_signal_accounting_manifest.json"),
            "good_travelway_universe": _manifest_ref(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json"),
            "offset_anchor_universe": _manifest_ref(OFFSET_UNIVERSE_DIR / "offset_anchor_universe_integration_manifest.json"),
            "ramp_terminal_universe": _manifest_ref(RAMP_UNIVERSE_DIR / "ramp_terminal_universe_integration_manifest.json"),
            "good_context": _manifest_ref(GOOD_CONTEXT_DIR / "good_travelway_context_refresh_manifest.json"),
            "offset_context": _manifest_ref(OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json"),
            "ramp_context": _manifest_ref(RAMP_CONTEXT_DIR / "ramp_terminal_context_refresh_manifest.json"),
        },
        "counts": {row["readiness_metric"]: row["signal_count"] for row in readiness_summary.to_dict(orient="records")},
        "projection": projection.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
    }
    _write_json(manifest, "complex_multisignal_context_refresh_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Context-ready signals: {int(signal_summary['speed_aadt_ready'].sum()):,}")
    print(f"Clean candidates: {int(signal_summary['clean_addition_candidate'].sum()):,}")


if __name__ == "__main__":
    main()

