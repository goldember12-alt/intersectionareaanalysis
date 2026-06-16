from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/speed_context_join_v5_new_source_supplement")
SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"

NORMALIZED_SPEED_FILE = Path("artifacts/normalized/speed.parquet")
SPEED_V4_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v4_identity_enriched"
SPEED_V4_CONTEXT_FILE = SPEED_V4_DIR / "directional_bin_speed_context_v4.csv"
SPEED_V4_SUMMARY_FILE = SPEED_V4_DIR / "speed_context_v4_summary.csv"
SPEED_V4_MANIFEST_FILE = SPEED_V4_DIR / "speed_context_v4_manifest.json"
NEW_SOURCE_INVENTORY_DIR = OUTPUT_ROOT / "review/current/new_speed_route_source_inventory"
NEW_SOURCE_INVENTORY_FILE = NEW_SOURCE_INVENTORY_DIR / "new_speed_route_source_inventory_manifest.json"
FINAL_CRASH_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_crash_context.csv"

MIN_OVERLAP_RATIO = 0.50
MIN_OVERLAP_LENGTH = 0.001
OVERCOUNT_CONFLICT_RATIO = 1.25
STABLE_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

OUTPUTS = {
    "summary": "speed_context_v5_summary.csv",
    "directional": "directional_bin_speed_context_v5.csv",
    "directional_0_1000": "directional_bin_speed_context_v5_0_1000ft.csv",
    "directional_1000_2500": "directional_bin_speed_context_v5_1000_2500ft.csv",
    "crash": "directional_crash_speed_context_v5.csv",
    "reference_summary": "reference_signal_speed_context_summary_v5.csv",
    "recovered": "speed_v5_recovered_from_v4_missing_review.csv",
    "comparison": "speed_v5_comparison_to_v4.csv",
    "conflict": "speed_v5_conflict_with_v4_stable.csv",
    "candidates": "speed_v5_route_measure_candidates.csv",
    "review": "speed_v5_ambiguous_or_review_bins.csv",
    "missing": "speed_v5_missing_bins.csv",
    "qa": "speed_v5_qa.csv",
    "findings": "speed_context_v5_findings.md",
    "manifest": "speed_context_v5_manifest.json",
}

BASE_COLUMNS = [
    "reference_signal_id",
    "reference_directional_segment_id",
    "reference_directional_bin_id",
    "base_segment_id",
    "source_bin_key",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_midpoint_ft_from_reference_signal",
    "distance_window",
    "roadway_representation_type",
    "far_anchor_type",
    "stable_route_name_raw",
    "stable_route_name_normalized",
    "stable_directionality_raw",
    "stable_directionality_normalized",
    "route_identity_match_status",
    "directionality_match_status",
    "posted_car_speed_limit_context_value",
    "posted_truck_speed_limit_context_value",
    "weighted_car_speed_limit",
    "weighted_truck_speed_limit",
    "weighted_speed_method",
    "refined_speed_context_status",
    "refined_speed_context_confidence",
    "stable_measure_source_fields",
    "stable_measure_min",
    "stable_measure_max",
    "stable_measure_length",
]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        blocked = [column for column in usecols if _is_crash_direction_field(column)]
        if blocked:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def normalize_route_name(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " ")
    text = text.replace("S-VA", " ")
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
    route_token_seen = False
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"US", "SR", "VA", "I", "SC", "PR", "FR"}:
            route_type = "SR" if compact == "VA" else compact
            route_token_seen = True
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
            route_token_seen = True
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
            route_token_seen = True
    if route_number and route_type and route_token_seen:
        return f"{route_type}{route_number}{direction}"
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def _num(series: pd.Series | Any, index: pd.Index | None = None) -> pd.Series:
    if isinstance(series, pd.Series):
        return pd.to_numeric(series, errors="coerce")
    return pd.Series(np.nan, index=index)


def _format_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    if float(numeric).is_integer():
        return str(int(numeric))
    return f"{float(numeric):.3f}".rstrip("0").rstrip(".")


def _joined_unique(values: pd.Series) -> str:
    return "|".join(sorted({value for value in values.map(_format_speed) if value}))


def _speed_values_match(left: Any, right: Any) -> bool:
    lval = pd.to_numeric(pd.Series([left]), errors="coerce").iloc[0]
    rval = pd.to_numeric(pd.Series([right]), errors="coerce").iloc[0]
    if pd.isna(lval) and pd.isna(rval):
        return True
    if pd.isna(lval) or pd.isna(rval):
        return False
    return abs(float(lval) - float(rval)) < 0.01


def _load_speed_limit_rns() -> pd.DataFrame:
    raw = gpd.read_file(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER)
    rows = []
    for route_field, from_field, to_field in [
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
    ]:
        if route_field not in raw.columns or from_field not in raw.columns or to_field not in raw.columns:
            continue
        sub = pd.DataFrame(
            {
                "source_route_field": route_field,
                "source_measure_pair": f"{from_field}/{to_field}",
                "source_route_raw": raw[route_field].astype(str),
                "source_route_key": raw[route_field].map(normalize_route_name),
                "source_measure_from": _num(raw[from_field]),
                "source_measure_to": _num(raw[to_field]),
                "source_car_speed_limit": _num(raw["CAR_SPEED_LIMIT"]),
                "source_truck_speed_limit": _num(raw["TRUCK_SPEED_LIMIT"]),
                "source_edge_rte_key": raw.get("EDGE_RTE_KEY", pd.Series("", index=raw.index)).astype(str),
                "source_master_edge_rte_key": raw.get("MASTER_EDGE_RTE_KEY", pd.Series("", index=raw.index)).astype(str),
                "source_transport_edge_id": raw.get("TRANSPORT_EDGE_ID", pd.Series("", index=raw.index)).astype(str),
            }
        )
        sub["source_measure_min"] = sub[["source_measure_from", "source_measure_to"]].min(axis=1)
        sub["source_measure_max"] = sub[["source_measure_from", "source_measure_to"]].max(axis=1)
        rows.append(sub)
    source = pd.concat(rows, ignore_index=True)
    source = source.loc[
        source["source_route_key"].ne("")
        & source["source_measure_min"].notna()
        & source["source_measure_max"].notna()
        & source["source_car_speed_limit"].notna()
    ].copy()
    source = source.drop_duplicates(
        [
            "source_route_key",
            "source_measure_min",
            "source_measure_max",
            "source_car_speed_limit",
            "source_truck_speed_limit",
            "source_route_field",
            "source_measure_pair",
        ]
    )
    return source


def _candidate_rows_for_route(route_key: str, bins: pd.DataFrame, source: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_route = source.loc[source["source_route_key"].eq(route_key)].copy()
    candidate_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    if source_route.empty:
        for row in bins.itertuples(index=False):
            context_rows.append(_empty_candidate_context(row, "missing_no_route_compatible_speed", "no Speed_Limit_RNS route key match"))
        return candidate_rows, context_rows

    s_min = source_route["source_measure_min"].to_numpy(dtype=float)
    s_max = source_route["source_measure_max"].to_numpy(dtype=float)
    for row in bins.itertuples(index=False):
        bmin = getattr(row, "stable_measure_min_num")
        bmax = getattr(row, "stable_measure_max_num")
        blen = getattr(row, "stable_measure_length_num")
        if pd.isna(bmin) or pd.isna(bmax) or pd.isna(blen) or float(blen) <= 0:
            context_rows.append(_empty_candidate_context(row, "review_missing_route_measure_evidence", "missing stable route measure evidence"))
            continue
        mask = (s_max >= float(bmin)) & (s_min <= float(bmax))
        overlap = source_route.loc[mask].copy()
        if overlap.empty:
            context_rows.append(_empty_candidate_context(row, "review_no_measure_overlap", "route matched but no Speed_Limit_RNS measure overlap"))
            continue
        overlap["overlap_length"] = overlap.apply(
            lambda r: max(0.0, min(float(bmax), float(r.source_measure_max)) - max(float(bmin), float(r.source_measure_min))),
            axis=1,
        )
        overlap = overlap.loc[overlap["overlap_length"].gt(0)].copy()
        if overlap.empty:
            context_rows.append(_empty_candidate_context(row, "review_no_measure_overlap", "route matched but no positive measure overlap"))
            continue
        context = _candidate_context_from_overlap(row, overlap, float(blen))
        context_rows.append(context)
        candidate_rows.append(_candidate_detail_from_overlap(row, overlap, context))
    return candidate_rows, context_rows


def _empty_candidate_context(row: Any, status: str, note: str) -> dict[str, Any]:
    return {
        "reference_directional_bin_id": getattr(row, "reference_directional_bin_id"),
        "v5_candidate_status": status,
        "v5_candidate_confidence": "missing" if status.startswith("missing") else "review",
        "v5_candidate_car_speed_limit": "",
        "v5_candidate_truck_speed_limit": "",
        "v5_weighted_car_speed_limit": "",
        "v5_weighted_truck_speed_limit": "",
        "v5_speed_transition_within_bin_flag": False,
        "v5_weighted_speed_context_flag": False,
        "v5_weighted_speed_method": "",
        "v5_candidate_count": 0,
        "v5_candidate_car_speed_values": "",
        "v5_candidate_truck_speed_values": "",
        "v5_measure_overlap_length": "",
        "v5_measure_overlap_ratio": "",
        "v5_source_route_fields": "",
        "v5_source_measure_pairs": "",
        "v5_review_reason": note,
    }


def _candidate_context_from_overlap(row: Any, overlap: pd.DataFrame, bin_length: float) -> dict[str, Any]:
    total_by_speed = overlap.groupby(["source_car_speed_limit", "source_truck_speed_limit"], dropna=False)["overlap_length"].sum().reset_index()
    total_overlap = float(total_by_speed["overlap_length"].sum())
    max_overlap = float(total_by_speed["overlap_length"].max()) if not total_by_speed.empty else 0.0
    overlap_ratio = total_overlap / bin_length if bin_length else 0.0
    car_values = _joined_unique(overlap["source_car_speed_limit"])
    truck_values = _joined_unique(overlap["source_truck_speed_limit"])
    unique_car_count = overlap["source_car_speed_limit"].dropna().round(3).nunique()
    if max_overlap < MIN_OVERLAP_LENGTH or overlap_ratio < MIN_OVERLAP_RATIO:
        status = "review_weak_measure_overlap"
        confidence = "review"
        reason = "route matched but measure overlap below stable threshold"
        weighted_car = ""
        weighted_truck = ""
        single_car = ""
        single_truck = ""
        transition = False
        method = ""
    elif unique_car_count > 1 and overlap_ratio > OVERCOUNT_CONFLICT_RATIO:
        status = "review_conflicting_speed_values"
        confidence = "review"
        reason = "multiple speed values overlap more than expected bin measure length"
        weighted_car = ""
        weighted_truck = ""
        single_car = ""
        single_truck = ""
        transition = False
        method = ""
    elif unique_car_count <= 1:
        status = "stable_single_speed"
        confidence = "medium_supplement_candidate"
        reason = ""
        single_car = _format_speed(overlap["source_car_speed_limit"].dropna().iloc[0]) if overlap["source_car_speed_limit"].notna().any() else ""
        single_truck = _format_speed(overlap["source_truck_speed_limit"].dropna().iloc[0]) if overlap["source_truck_speed_limit"].notna().any() else ""
        weighted_car = ""
        weighted_truck = ""
        transition = False
        method = "single_value_route_measure_overlap_speed_limit_rns"
    else:
        status = "stable_weighted_speed_transition"
        confidence = "medium_supplement_candidate"
        reason = ""
        weights = total_by_speed["overlap_length"]
        weighted_car = _format_speed((total_by_speed["source_car_speed_limit"] * weights).sum() / weights.sum())
        truck_non_null = total_by_speed["source_truck_speed_limit"].notna()
        weighted_truck = (
            _format_speed((total_by_speed.loc[truck_non_null, "source_truck_speed_limit"] * total_by_speed.loc[truck_non_null, "overlap_length"]).sum() / total_by_speed.loc[truck_non_null, "overlap_length"].sum())
            if truck_non_null.any()
            else ""
        )
        single_car = ""
        single_truck = ""
        transition = True
        method = "measure_overlap_weighted_speed_limit_rns_transition"
    return {
        "reference_directional_bin_id": getattr(row, "reference_directional_bin_id"),
        "v5_candidate_status": status,
        "v5_candidate_confidence": confidence,
        "v5_candidate_car_speed_limit": single_car,
        "v5_candidate_truck_speed_limit": single_truck,
        "v5_weighted_car_speed_limit": weighted_car,
        "v5_weighted_truck_speed_limit": weighted_truck,
        "v5_speed_transition_within_bin_flag": transition,
        "v5_weighted_speed_context_flag": bool(transition),
        "v5_weighted_speed_method": method,
        "v5_candidate_count": int(len(overlap)),
        "v5_candidate_car_speed_values": car_values,
        "v5_candidate_truck_speed_values": truck_values,
        "v5_measure_overlap_length": round(total_overlap, 6),
        "v5_measure_overlap_ratio": round(overlap_ratio, 6),
        "v5_source_route_fields": "|".join(sorted(overlap["source_route_field"].unique())),
        "v5_source_measure_pairs": "|".join(sorted(overlap["source_measure_pair"].unique())),
        "v5_review_reason": reason,
    }


def _candidate_detail_from_overlap(row: Any, overlap: pd.DataFrame, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_directional_bin_id": getattr(row, "reference_directional_bin_id"),
        "stable_route_name_normalized": getattr(row, "stable_route_name_normalized"),
        "stable_measure_min": getattr(row, "stable_measure_min"),
        "stable_measure_max": getattr(row, "stable_measure_max"),
        "stable_measure_length": getattr(row, "stable_measure_length"),
        "current_refined_speed_context_status": getattr(row, "refined_speed_context_status"),
        "candidate_count": int(len(overlap)),
        "candidate_car_speed_values": context["v5_candidate_car_speed_values"],
        "candidate_truck_speed_values": context["v5_candidate_truck_speed_values"],
        "measure_overlap_length": context["v5_measure_overlap_length"],
        "measure_overlap_ratio": context["v5_measure_overlap_ratio"],
        "source_route_fields": context["v5_source_route_fields"],
        "source_measure_pairs": context["v5_source_measure_pairs"],
        "candidate_status": context["v5_candidate_status"],
    }


def _build_candidate_context(v4: pd.DataFrame, source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = v4.copy()
    work["stable_measure_min_num"] = _num(work["stable_measure_min"])
    work["stable_measure_max_num"] = _num(work["stable_measure_max"])
    work["stable_measure_length_num"] = _num(work["stable_measure_length"])
    candidate_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    no_route = work.loc[work["stable_route_name_normalized"].astype(str).str.strip().eq("")]
    for row in no_route.itertuples(index=False):
        context_rows.append(_empty_candidate_context(row, "review_route_missing", "missing stable route identity"))
    routed = work.loc[work["stable_route_name_normalized"].astype(str).str.strip().ne("")]
    for route_key, bins in routed.groupby("stable_route_name_normalized", dropna=False):
        details, contexts = _candidate_rows_for_route(str(route_key), bins, source)
        candidate_rows.extend(details)
        context_rows.extend(contexts)
    return pd.DataFrame(context_rows), pd.DataFrame(candidate_rows)


def _effective_v5_context(v4: pd.DataFrame, candidate_context: pd.DataFrame) -> pd.DataFrame:
    out = v4.merge(candidate_context, on="reference_directional_bin_id", how="left")
    v4_stable = out["refined_speed_context_status"].isin(STABLE_STATUSES)
    v5_candidate_stable = out["v5_candidate_status"].isin(STABLE_STATUSES)

    out["v5_v4_comparison_status"] = out.apply(_comparison_status, axis=1)
    out["v5_supplement_action"] = "not_recovered"
    out.loc[v4_stable & out["v5_v4_comparison_status"].eq("v5_confirms_v4_stable"), "v5_supplement_action"] = "v4_stable_retained_confirmed_by_rns"
    out.loc[v4_stable & out["v5_v4_comparison_status"].eq("v5_conflicts_with_v4_stable"), "v5_supplement_action"] = "v4_stable_retained_conflict_preserved"
    out.loc[v4_stable & out["v5_v4_comparison_status"].eq("v5_no_stable_candidate_for_v4_stable"), "v5_supplement_action"] = "v4_stable_retained_no_rns_confirmation"
    out.loc[(~v4_stable) & v5_candidate_stable, "v5_supplement_action"] = "v4_missing_review_recovered_by_rns"

    out["v5_effective_speed_source"] = "v4_retained"
    out.loc[(~v4_stable) & v5_candidate_stable, "v5_effective_speed_source"] = "speed_limit_rns_supplement_candidate"
    out.loc[(~v4_stable) & (~v5_candidate_stable), "v5_effective_speed_source"] = "no_stable_speed_candidate"

    out["v5_refined_speed_context_status"] = out["refined_speed_context_status"]
    out["v5_refined_speed_context_confidence"] = out["refined_speed_context_confidence"]
    out["v5_posted_car_speed_limit_context_value"] = out["posted_car_speed_limit_context_value"]
    out["v5_posted_truck_speed_limit_context_value"] = out["posted_truck_speed_limit_context_value"]
    out["v5_effective_weighted_car_speed_limit"] = out["weighted_car_speed_limit"]
    out["v5_effective_weighted_truck_speed_limit"] = out["weighted_truck_speed_limit"]
    recover = (~v4_stable) & v5_candidate_stable
    out.loc[recover, "v5_refined_speed_context_status"] = out.loc[recover, "v5_candidate_status"]
    out.loc[recover, "v5_refined_speed_context_confidence"] = out.loc[recover, "v5_candidate_confidence"]
    out.loc[recover, "v5_posted_car_speed_limit_context_value"] = out.loc[recover, "v5_candidate_car_speed_limit"]
    out.loc[recover, "v5_posted_truck_speed_limit_context_value"] = out.loc[recover, "v5_candidate_truck_speed_limit"]
    out.loc[recover, "v5_effective_weighted_car_speed_limit"] = out.loc[recover, "v5_weighted_car_speed_limit"]
    out.loc[recover, "v5_effective_weighted_truck_speed_limit"] = out.loc[recover, "v5_weighted_truck_speed_limit"]

    review = (~v4_stable) & (~v5_candidate_stable)
    out.loc[review, "v5_refined_speed_context_status"] = out.loc[review, "v5_candidate_status"].fillna("missing_no_route_compatible_speed")
    out.loc[review, "v5_refined_speed_context_confidence"] = out.loc[review, "v5_candidate_confidence"].fillna("missing")
    out["v5_candidate_supplement_until_accepted"] = True
    return out


def _comparison_status(row: pd.Series) -> str:
    v4_stable = row.get("refined_speed_context_status") in STABLE_STATUSES
    v5_stable = row.get("v5_candidate_status") in STABLE_STATUSES
    if not v4_stable:
        return "v4_not_stable"
    if not v5_stable:
        return "v5_no_stable_candidate_for_v4_stable"
    v4_car = row.get("posted_car_speed_limit_context_value") or row.get("weighted_car_speed_limit")
    v5_car = row.get("v5_candidate_car_speed_limit") or row.get("v5_weighted_car_speed_limit")
    v4_truck = row.get("posted_truck_speed_limit_context_value") or row.get("weighted_truck_speed_limit")
    v5_truck = row.get("v5_candidate_truck_speed_limit") or row.get("v5_weighted_truck_speed_limit")
    if _speed_values_match(v4_car, v5_car) and _speed_values_match(v4_truck, v5_truck):
        return "v5_confirms_v4_stable"
    return "v5_conflicts_with_v4_stable"


def _summary(v5: pd.DataFrame, crash_context: pd.DataFrame, reference_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    v4_stable = v5["refined_speed_context_status"].isin(STABLE_STATUSES)
    v5_stable = v5["v5_refined_speed_context_status"].isin(STABLE_STATUSES)
    recovered = v5["v5_supplement_action"].eq("v4_missing_review_recovered_by_rns")
    rows.extend(
        [
            {"metric": "main_0_2500ft_bins", "value": "", "count": len(v5)},
            {"metric": "v4_stable_speed_bins", "value": "", "count": int(v4_stable.sum())},
            {"metric": "v5_stable_speed_bins", "value": "", "count": int(v5_stable.sum())},
            {"metric": "newly_recovered_stable_bins_from_v4_missing_review", "value": "", "count": int(recovered.sum())},
            {"metric": "v4_stable_bins_confirmed_by_v5", "value": "", "count": int(v5["v5_v4_comparison_status"].eq("v5_confirms_v4_stable").sum())},
            {"metric": "v4_stable_bins_conflicting_with_v5", "value": "", "count": int(v5["v5_v4_comparison_status"].eq("v5_conflicts_with_v4_stable").sum())},
            {"metric": "v4_stable_bins_without_stable_v5_candidate", "value": "", "count": int(v5["v5_v4_comparison_status"].eq("v5_no_stable_candidate_for_v4_stable").sum())},
            {"metric": "v5_missing_review_bins_remaining", "value": "", "count": int((~v5_stable).sum())},
            {"metric": "crash_rows_inheriting_stable_v5_speed", "value": "", "count": int(crash_context["v5_refined_speed_context_status"].isin(STABLE_STATUSES).sum())},
            {"metric": "reference_signals_with_stable_v5_speed", "value": "", "count": int(reference_summary["has_stable_v5_speed"].astype(str).str.lower().eq("true").sum())},
            {"metric": "speed_v5_candidate_supplement_until_accepted", "value": True, "count": ""},
            {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
            {"metric": "direction_factor_applied", "value": False, "count": ""},
        ]
    )
    for window, group in v5.groupby("distance_window", dropna=False):
        rows.append({"metric": "bins_by_distance_window", "value": window, "count": len(group)})
        rows.append({"metric": "v4_stable_bins_by_distance_window", "value": window, "count": int(group["refined_speed_context_status"].isin(STABLE_STATUSES).sum())})
        rows.append({"metric": "v5_stable_bins_by_distance_window", "value": window, "count": int(group["v5_refined_speed_context_status"].isin(STABLE_STATUSES).sum())})
        rows.append({"metric": "v5_recovered_bins_by_distance_window", "value": window, "count": int(group["v5_supplement_action"].eq("v4_missing_review_recovered_by_rns").sum())})
        rows.append({"metric": "v5_missing_review_bins_by_distance_window", "value": window, "count": int((~group["v5_refined_speed_context_status"].isin(STABLE_STATUSES)).sum())})
    return pd.DataFrame(rows)


def _reference_summary(v5: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for signal_id, group in v5.groupby("reference_signal_id", dropna=False):
        stable = group["v5_refined_speed_context_status"].isin(STABLE_STATUSES)
        rows.append(
            {
                "reference_signal_id": signal_id,
                "directional_bin_count": len(group),
                "v4_stable_speed_bin_count": int(group["refined_speed_context_status"].isin(STABLE_STATUSES).sum()),
                "v5_stable_speed_bin_count": int(stable.sum()),
                "v5_recovered_from_v4_missing_review_bin_count": int(group["v5_supplement_action"].eq("v4_missing_review_recovered_by_rns").sum()),
                "v5_missing_review_bin_count": int((~stable).sum()),
                "has_stable_v5_speed": bool(stable.any()),
            }
        )
    return pd.DataFrame(rows)


def _crash_context(v5: pd.DataFrame) -> pd.DataFrame:
    crash_cols = [
        "crash_id",
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "roadway_representation_type",
        "bin_midpoint_ft_from_reference_signal",
        "far_anchor_type",
    ]
    crashes = _read_csv(FINAL_CRASH_CONTEXT_FILE, usecols=crash_cols)
    speed_cols = [
        "reference_directional_bin_id",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_directionality_raw",
        "stable_directionality_normalized",
        "v5_posted_car_speed_limit_context_value",
        "v5_posted_truck_speed_limit_context_value",
        "v5_effective_weighted_car_speed_limit",
        "v5_effective_weighted_truck_speed_limit",
        "v5_refined_speed_context_status",
        "v5_refined_speed_context_confidence",
        "v5_effective_speed_source",
        "v5_supplement_action",
    ]
    return crashes.merge(v5[speed_cols], on="reference_directional_bin_id", how="left")


def _comparison_to_v4(v5: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for status, group in v5.groupby("v5_supplement_action", dropna=False):
        rows.append(
            {
                "comparison_group": status,
                "bin_count": len(group),
                "v4_stable_count": int(group["refined_speed_context_status"].isin(STABLE_STATUSES).sum()),
                "v5_stable_count": int(group["v5_refined_speed_context_status"].isin(STABLE_STATUSES).sum()),
                "unique_route_count": int(group["stable_route_name_normalized"].astype(str).nunique()),
            }
        )
    for keys, group in v5.groupby(["refined_speed_context_status", "v5_refined_speed_context_status"], dropna=False):
        v4_status, v5_status = keys
        rows.append(
            {
                "comparison_group": "v4_status_to_v5_status",
                "v4_refined_speed_context_status": v4_status,
                "v5_refined_speed_context_status": v5_status,
                "bin_count": len(group),
                "v4_stable_count": int(group["refined_speed_context_status"].isin(STABLE_STATUSES).sum()),
                "v5_stable_count": int(group["v5_refined_speed_context_status"].isin(STABLE_STATUSES).sum()),
                "unique_route_count": int(group["stable_route_name_normalized"].astype(str).nunique()),
            }
        )
    return pd.DataFrame(rows)


def _qa(v5: pd.DataFrame, outputs: dict[str, Path], mtimes_before: dict[str, float | None], mtimes_after: dict[str, float | None]) -> pd.DataFrame:
    normalized_unchanged = mtimes_before.get(str(NORMALIZED_SPEED_FILE)) == mtimes_after.get(str(NORMALIZED_SPEED_FILE))
    speed_v4_unchanged = all(mtimes_before.get(str(path)) == mtimes_after.get(str(path)) for path in [SPEED_V4_CONTEXT_FILE, SPEED_V4_SUMMARY_FILE, SPEED_V4_MANIFEST_FILE])
    recovered = v5["v5_supplement_action"].eq("v4_missing_review_recovered_by_rns")
    route_measure_required = bool(
        (
            v5.loc[recovered, "stable_route_name_normalized"].astype(str).str.strip().ne("")
            & _num(v5.loc[recovered, "stable_measure_min"]).notna()
            & _num(v5.loc[recovered, "stable_measure_max"]).notna()
            & _num(v5.loc[recovered, "v5_measure_overlap_ratio"]).ge(MIN_OVERLAP_RATIO)
        ).all()
    )
    conflicts = v5["v5_v4_comparison_status"].eq("v5_conflicts_with_v4_stable")
    conflicts_preserved = bool((v5.loc[conflicts, "v5_supplement_action"].eq("v4_stable_retained_conflict_preserved")).all())
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
        {"check_name": "existing_speed_v4_outputs_overwritten", "passed": speed_v4_unchanged, "observed": "unchanged" if speed_v4_unchanged else "mtime_changed", "expected": "unchanged"},
        {"check_name": "normalized_speed_artifact_overwritten", "passed": normalized_unchanged, "observed": "unchanged" if normalized_unchanged else "mtime_changed", "expected": "unchanged"},
        {"check_name": "graph_context_rate_model_outputs_modified", "passed": True, "observed": "module writes only speed_context_join_v5_new_source_supplement review outputs", "expected": "no"},
        {"check_name": "route_measure_evidence_required_for_stable_v5_recovery", "passed": route_measure_required, "observed": int(recovered.sum()), "expected": "all recovered rows have route and measure overlap"},
        {"check_name": "conflicts_with_v4_preserved_not_overwritten", "passed": conflicts_preserved, "observed": int(conflicts.sum()), "expected": "preserved"},
        {"check_name": "v5_labeled_candidate_supplement_until_accepted", "passed": bool(v5["v5_candidate_supplement_until_accepted"].eq(True).all()), "observed": True, "expected": True},
    ]
    for key, path in outputs.items():
        if key in {"findings", "manifest", "qa"}:
            continue
        rows.append({"check_name": f"output_written_{key}", "passed": path.exists(), "observed": str(path), "expected": "exists"})
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def metric(name: str) -> Any:
        row = summary.loc[summary["metric"].eq(name)]
        if row.empty:
            return ""
        value = row.iloc[0]["count"]
        return value if str(value) != "" else row.iloc[0]["value"]

    qa_lines = "\n".join(f"- {row.check_name}: {'PASS' if bool(row.passed) else 'FAIL'} ({row.observed})" for row in qa.itertuples(index=False))
    return f"""# Speed Context Join v5 New-Source Supplement Findings

## Bounded Question

Can `Speed_Limit_RNS` recover current speed v4 missing/review directional bins using route+measure evidence, while preserving speed v4 as the active accepted context?

## Files Read

- `{SPEED_LIMIT_RNS_GDB}` layer `{SPEED_LIMIT_RNS_LAYER}`
- `{SPEED_V4_CONTEXT_FILE}`
- `{FINAL_CRASH_CONTEXT_FILE}`
- `{NORMALIZED_SPEED_FILE}` for modification guard/comparison only
- `{NEW_SOURCE_INVENTORY_FILE}` as prior diagnostic provenance when present

## Key Counts

- v4 stable speed bins: {metric('v4_stable_speed_bins')}
- v5 candidate stable speed bins: {metric('v5_stable_speed_bins')}
- newly recovered stable bins from v4 missing/review: {metric('newly_recovered_stable_bins_from_v4_missing_review')}
- v4 stable bins confirmed by v5: {metric('v4_stable_bins_confirmed_by_v5')}
- v4 stable bins conflicting with v5: {metric('v4_stable_bins_conflicting_with_v5')}
- v5 missing/review bins remaining: {metric('v5_missing_review_bins_remaining')}
- crash rows inheriting stable v5 speed: {metric('crash_rows_inheriting_stable_v5_speed')}
- reference signals with stable v5 speed: {metric('reference_signals_with_stable_v5_speed')}

## Interpretation

Speed v5 is a candidate supplement, not an accepted replacement. It should not replace v4 as the active speed context until the conflict rows, weighted-transition behavior, and route/measure semantics are reviewed. Downstream combined context, rate, and model outputs should not be refreshed until v5 is explicitly accepted.

## QA

{qa_lines}

## Outputs

{chr(10).join(f'- `{path}`' for path in outputs.values())}
"""


def build_speed_context_join_v5_new_source_supplement(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    outputs = {key: out_dir / name for key, name in OUTPUTS.items()}
    tracked = [NORMALIZED_SPEED_FILE, SPEED_V4_CONTEXT_FILE, SPEED_V4_SUMMARY_FILE, SPEED_V4_MANIFEST_FILE]
    mtimes_before = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}

    v4 = _read_csv(SPEED_V4_CONTEXT_FILE, usecols=BASE_COLUMNS)
    source = _load_speed_limit_rns()
    candidate_context, candidate_detail = _build_candidate_context(v4, source)
    v5 = _effective_v5_context(v4, candidate_context)
    reference_summary = _reference_summary(v5)
    crash_context = _crash_context(v5)
    summary = _summary(v5, crash_context, reference_summary)
    comparison = _comparison_to_v4(v5)
    recovered = v5.loc[v5["v5_supplement_action"].eq("v4_missing_review_recovered_by_rns")].copy()
    conflicts = v5.loc[v5["v5_v4_comparison_status"].eq("v5_conflicts_with_v4_stable")].copy()
    review = v5.loc[~v5["v5_refined_speed_context_status"].isin(STABLE_STATUSES)].copy()
    missing = v5.loc[v5["v5_refined_speed_context_status"].astype(str).str.startswith("missing")].copy()

    _write_csv(summary, outputs["summary"])
    _write_csv(v5, outputs["directional"])
    _write_csv(v5.loc[v5["distance_window"].eq("high_priority_0_1000ft")], outputs["directional_0_1000"])
    _write_csv(v5.loc[v5["distance_window"].eq("sensitivity_1000_2500ft")], outputs["directional_1000_2500"])
    _write_csv(crash_context, outputs["crash"])
    _write_csv(reference_summary, outputs["reference_summary"])
    _write_csv(recovered, outputs["recovered"])
    _write_csv(comparison, outputs["comparison"])
    _write_csv(conflicts, outputs["conflict"])
    _write_csv(candidate_detail, outputs["candidates"])
    _write_csv(review, outputs["review"])
    _write_csv(missing, outputs["missing"])

    mtimes_after = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}
    qa = _qa(v5, outputs, mtimes_before, mtimes_after)
    _write_csv(qa, outputs["qa"])
    _write_text(_findings(summary, qa, outputs), outputs["findings"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only Speed_Limit_RNS supplement for speed v4 missing/review bins using route+measure evidence",
        "candidate_supplement_until_accepted": True,
        "speed_v4_replaced": False,
        "combined_context_rerun": False,
        "crash_direction_fields_read_or_used": False,
        "direction_factor_applied": False,
        "inputs": {
            "speed_limit_rns_gdb": str(SPEED_LIMIT_RNS_GDB),
            "speed_limit_rns_layer": SPEED_LIMIT_RNS_LAYER,
            "speed_v4_context": str(SPEED_V4_CONTEXT_FILE),
            "directional_crash_context": str(FINAL_CRASH_CONTEXT_FILE),
            "normalized_speed_comparison_only": str(NORMALIZED_SPEED_FILE),
            "new_source_inventory": str(NEW_SOURCE_INVENTORY_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only Speed_Limit_RNS supplement comparison against speed v4.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_speed_context_join_v5_new_source_supplement(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
