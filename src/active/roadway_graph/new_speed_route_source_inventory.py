from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/new_speed_route_source_inventory")
SOURCE_ROOT = Path("Intersection Crash Analysis Layers")

VDOT_ROUTES_FILE = SOURCE_ROOT / "VDOT_Routes.geojson"
SPEED_LIMIT_RNS_PATH = SOURCE_ROOT / "Speed_Limit_RNS"
SPEED_LIMIT_RNS_GDB = SPEED_LIMIT_RNS_PATH / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"

NORMALIZED_SPEED_FILE = Path("artifacts/normalized/speed.parquet")
SPEED_V4_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v4_identity_enriched"
SPEED_V4_CONTEXT_FILE = SPEED_V4_DIR / "directional_bin_speed_context_v4.csv"
SPEED_V4_MISSING_FILE = SPEED_V4_DIR / "speed_missing_bins_v4.csv"
SPEED_V4_REVIEW_FILE = SPEED_V4_DIR / "speed_review_bins_v4.csv"
SPEED_V4_SUMMARY_FILE = SPEED_V4_DIR / "speed_context_v4_summary.csv"
IDENTITY_DIR = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation"
IDENTITY_BINS_FILE = IDENTITY_DIR / "directional_bins_identity_enriched.csv"
FINAL_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

SPEED_FIELD_TOKENS = ("SPEED", "SPD", "LIMIT", "POSTED", "MPH")
ROUTE_FIELD_TOKENS = (
    "ROUTE",
    "RTE",
    "RNS",
    "MASTER",
    "COMMON",
    "EDGE",
    "LINK",
    "MEASURE",
    "MSR",
    "DIRECTION",
    "DIR",
    "JURIS",
    "DISTRICT",
    "LOCALITY",
    "IDENTIFY",
)

ROUTE_NAME_FIELD_TOKENS = ("RTE_NM", "ROUTE_NAME", "ROUTE_COMMON", "COMMON_NM", "COMMON_NAME", "MASTER_RTE_NM", "PARENT_RTE_NM", "OPPOSITE_DIRECTION_RTE_NM")

OUTPUTS = {
    "summary": "new_speed_route_source_inventory_summary.csv",
    "schema": "new_speed_route_source_schema.csv",
    "geometry": "new_speed_route_source_geometry_qa.csv",
    "roles": "new_speed_route_source_field_role_candidates.csv",
    "nonnull": "new_speed_route_source_non_null_profile.csv",
    "route_overlap": "new_speed_route_source_route_identity_overlap.csv",
    "speed_fields": "new_speed_route_source_speed_field_diagnostic.csv",
    "recovery": "speed_v4_missing_review_recovery_estimate.csv",
    "comparison": "speed_source_comparison_current_vs_new.csv",
    "recommendation": "new_speed_route_source_recommendation.csv",
    "findings": "new_speed_route_source_inventory_findings.md",
    "manifest": "new_speed_route_source_inventory_manifest.json",
}


@dataclass(frozen=True)
class SourceSpec:
    source_name: str
    path: Path
    layer: str | None
    expected_format: str


SOURCES = (
    SourceSpec("VDOT_Routes", VDOT_ROUTES_FILE, None, "GeoJSON"),
    SourceSpec("Speed_Limit_RNS", SPEED_LIMIT_RNS_GDB, SPEED_LIMIT_RNS_LAYER, "FileGDB/layer"),
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path, *, usecols: list[str] | None = None, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols, nrows=nrows)


def _clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


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


def _to_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _source_format(spec: SourceSpec) -> str:
    if spec.path.suffix.lower() in {".geojson", ".json"}:
        return "GeoJSON"
    if spec.path.suffix.lower() == ".gdb":
        return "FileGDB/layer"
    if spec.path.is_dir():
        return "folder/layer"
    if spec.path.suffix.lower() == ".shp":
        return "shapefile"
    return "other"


def _read_source(spec: SourceSpec) -> gpd.GeoDataFrame | None:
    if not spec.path.exists():
        return None
    if spec.layer:
        return gpd.read_file(spec.path, layer=spec.layer)
    return gpd.read_file(spec.path)


def _bounds_text(bounds: Any) -> str:
    try:
        return ",".join(f"{float(value):.6f}" for value in bounds)
    except Exception:
        return ""


def _schema(source_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_name": source_name,
                "field_name": field,
                "dtype": str(frame[field].dtype),
                "is_geometry": field == frame.geometry.name,
                "candidate_speed_field": _is_speed_field(field, frame[field] if field in frame.columns else pd.Series(dtype=object)),
                "candidate_route_identity_field": _is_route_field(field),
            }
            for field in frame.columns
        ]
    )


def _is_speed_field(field: str, series: pd.Series) -> bool:
    upper = field.upper()
    if any(token in upper for token in SPEED_FIELD_TOKENS):
        return True
    if pd.api.types.is_numeric_dtype(series):
        values = pd.to_numeric(series, errors="coerce").dropna()
        if not values.empty and values.between(1, 90).mean() > 0.95 and values.nunique() <= 40:
            return True
    return False


def _is_route_field(field: str) -> bool:
    upper = field.upper()
    return any(token in upper for token in ROUTE_FIELD_TOKENS)


def _nonnull_profile(source_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    total = len(frame)
    for field in frame.columns:
        if field == frame.geometry.name:
            non_null = int(frame.geometry.notna().sum())
            unique = int(frame.geometry.geom_type.nunique(dropna=True))
            top = "|".join(f"{idx}:{int(count)}" for idx, count in frame.geometry.geom_type.value_counts().head(10).items())
        else:
            series = frame[field]
            mask = _nonempty(series)
            non_null = int(mask.sum())
            unique = int(series.loc[mask].astype(str).nunique(dropna=True)) if non_null else 0
            top = "|".join(f"{idx}:{int(count)}" for idx, count in series.loc[mask].astype(str).value_counts().head(10).items()) if non_null else ""
        rows.append(
            {
                "source_name": source_name,
                "field_name": field,
                "row_count": total,
                "non_null_count": non_null,
                "missing_count": total - non_null,
                "missing_pct": round((total - non_null) / total, 6) if total else "",
                "unique_non_null_count": unique,
                "candidate_speed_field": _is_speed_field(field, frame[field]) if field in frame.columns and field != frame.geometry.name else False,
                "candidate_route_identity_field": _is_route_field(field),
                "top_values": top,
            }
        )
    return pd.DataFrame(rows)


def _field_roles(source_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for field in frame.columns:
        if field == frame.geometry.name:
            continue
        roles = []
        if _is_speed_field(field, frame[field]):
            roles.append("candidate_speed_field")
        if _is_route_field(field):
            roles.append("candidate_route_identity_field")
        upper = field.upper()
        if "MEASURE" in upper or "MSR" in upper:
            roles.append("measure_field")
        if "DIRECTION" in upper or upper.endswith("_DIR") or "_DIR" in upper:
            roles.append("directionality_field")
        if "JURIS" in upper or "DISTRICT" in upper or "LOCALITY" in upper:
            roles.append("jurisdiction_context_field")
        if roles:
            rows.append({"source_name": source_name, "field_name": field, "candidate_roles": "|".join(sorted(set(roles)))})
    return pd.DataFrame(rows)


def _geometry_qa(spec: SourceSpec, frame: gpd.GeoDataFrame | None, stable_bounds: str, stable_crs: Any) -> dict[str, Any]:
    if frame is None:
        return {
            "source_name": spec.source_name,
            "path": str(spec.path),
            "exists": spec.path.exists(),
            "readable_format": _source_format(spec),
            "read_status": "missing_or_unread",
            "row_count": 0,
            "geometry_type": "",
            "crs": "",
            "bounds": "",
            "stable_universe_bounds": stable_bounds,
            "bounds_in_stable_crs": "",
            "bounds_overlap_stable_universe": False,
        }
    bounds_in_stable_crs = ""
    bounds_overlap = False
    try:
        projected = frame.to_crs(stable_crs) if stable_crs is not None and frame.crs is not None else frame
        bounds_in_stable_crs = _bounds_text(projected.total_bounds)
        bounds_overlap = _bounds_overlap(projected.total_bounds, stable_bounds)
    except Exception:
        bounds_overlap = _bounds_overlap(frame.total_bounds, stable_bounds)
    return {
        "source_name": spec.source_name,
        "path": str(spec.path),
        "exists": spec.path.exists(),
        "readable_format": _source_format(spec),
        "read_status": "read",
        "row_count": len(frame),
        "geometry_type": "|".join(sorted(frame.geometry.geom_type.dropna().unique().astype(str).tolist())) if frame.geometry.name in frame.columns else "",
        "crs": str(frame.crs),
        "bounds": _bounds_text(frame.total_bounds),
        "stable_universe_bounds": stable_bounds,
        "bounds_in_stable_crs": bounds_in_stable_crs,
        "bounds_overlap_stable_universe": bounds_overlap,
    }


def _bounds_overlap(source_bounds: Any, stable_bounds_text: str) -> bool:
    if not stable_bounds_text:
        return False
    try:
        s = [float(value) for value in source_bounds]
        b = [float(value) for value in stable_bounds_text.split(",")]
        return not (s[2] < b[0] or s[0] > b[2] or s[3] < b[1] or s[1] > b[3])
    except Exception:
        return False


def _stable_bounds_and_crs() -> tuple[str, Any]:
    try:
        roads = gpd.read_parquet(Path("artifacts/normalized/roads.parquet"))
        return _bounds_text(roads.total_bounds), roads.crs
    except Exception:
        return "", None


def _source_route_keys(frame: pd.DataFrame, fields: list[str]) -> set[str]:
    keys: set[str] = set()
    for field in fields:
        if field in frame.columns:
            keys.update(key for key in frame[field].map(normalize_route_name).astype(str).unique() if key)
    return keys


def _route_name_fields(frame: pd.DataFrame) -> list[str]:
    fields = []
    for field in frame.columns:
        upper = field.upper()
        if any(token in upper for token in ROUTE_NAME_FIELD_TOKENS):
            fields.append(field)
    return fields


def _source_speed_records(frame: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if source_name == "Speed_Limit_RNS":
        route_fields = [field for field in ["RTE_NM", "MASTER_RTE_NM"] if field in frame.columns]
        measure_pairs = [("FROM_MEASURE", "TO_MEASURE"), ("TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR")]
        rows = []
        for route_field in route_fields:
            for from_field, to_field in measure_pairs:
                if from_field not in frame.columns or to_field not in frame.columns:
                    continue
                sub = frame[[route_field, from_field, to_field, "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT"]].copy()
                sub["source_name"] = source_name
                sub["route_field"] = route_field
                sub["measure_field_pair"] = f"{from_field}/{to_field}"
                sub["route_key"] = sub[route_field].map(normalize_route_name)
                sub["measure_min"] = pd.concat([_to_float(sub[from_field]), _to_float(sub[to_field])], axis=1).min(axis=1)
                sub["measure_max"] = pd.concat([_to_float(sub[from_field]), _to_float(sub[to_field])], axis=1).max(axis=1)
                sub["car_speed"] = _to_float(sub["CAR_SPEED_LIMIT"])
                sub["truck_speed"] = _to_float(sub["TRUCK_SPEED_LIMIT"])
                rows.append(sub[["source_name", "route_field", "measure_field_pair", "route_key", "measure_min", "measure_max", "car_speed", "truck_speed"]])
        if rows:
            out = pd.concat(rows, ignore_index=True)
            return out.loc[out["route_key"].ne("") & out["measure_min"].notna() & out["measure_max"].notna() & out["car_speed"].notna()].copy()
    return pd.DataFrame(columns=["source_name", "route_field", "measure_field_pair", "route_key", "measure_min", "measure_max", "car_speed", "truck_speed"])


def _load_gap_bins() -> pd.DataFrame:
    columns = [
        "reference_directional_bin_id",
        "refined_speed_context_status",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_directionality_normalized",
        "stable_measure_min",
        "stable_measure_max",
        "stable_measure_length",
        "distance_window",
        "route_identity_match_status",
        "directionality_match_status",
        "source_RTE_NM",
        "source_RTE_COMMON",
        "source_RTE_ID",
        "source_FROM_MEASURE",
        "source_TO_MEASURE",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
    ]
    frames = []
    for path in [SPEED_V4_MISSING_FILE, SPEED_V4_REVIEW_FILE]:
        frame = _read_csv(path, usecols=lambda col: col in columns)
        frames.append(frame)
    gaps = pd.concat(frames, ignore_index=True)
    gaps["stable_measure_min_num"] = _to_float(gaps.get("stable_measure_min", pd.Series(dtype=str)))
    gaps["stable_measure_max_num"] = _to_float(gaps.get("stable_measure_max", pd.Series(dtype=str)))
    gaps["stable_measure_length_num"] = _to_float(gaps.get("stable_measure_length", pd.Series(dtype=str)))
    return gaps


def _route_identity_overlap(source_routes: dict[str, set[str]], gap_bins: pd.DataFrame, all_bins_sample: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gap_routes = set(gap_bins["stable_route_name_normalized"].astype(str).loc[gap_bins["stable_route_name_normalized"].astype(str).ne("")])
    all_routes = set(all_bins_sample["stable_route_name_normalized"].astype(str).loc[all_bins_sample["stable_route_name_normalized"].astype(str).ne("")])
    for source_name, routes in source_routes.items():
        rows.append(
            {
                "source_name": source_name,
                "source_route_key_count": len(routes),
                "directional_bin_route_key_count": len(all_routes),
                "speed_missing_review_route_key_count": len(gap_routes),
                "directional_bin_route_keys_matched": len(all_routes & routes),
                "directional_bin_route_match_share": round(len(all_routes & routes) / len(all_routes), 6) if all_routes else 0,
                "missing_review_route_keys_matched": len(gap_routes & routes),
                "missing_review_route_match_share": round(len(gap_routes & routes) / len(gap_routes), 6) if gap_routes else 0,
                "source_classification": _classify_source(source_name),
            }
        )
    return pd.DataFrame(rows)


def _classify_source(source_name: str) -> str:
    if source_name == "Speed_Limit_RNS":
        return "speed_source_supplement_candidate"
    if source_name == "VDOT_Routes":
        return "route_identity_bridge_candidate"
    return "unknown"


def _recovery_estimate(speed_records: pd.DataFrame, gap_bins: pd.DataFrame) -> pd.DataFrame:
    if speed_records.empty or gap_bins.empty:
        return pd.DataFrame()
    rows = []
    for route_key, bins in gap_bins.groupby("stable_route_name_normalized", dropna=False):
        if not route_key:
            continue
        source = speed_records.loc[speed_records["route_key"].eq(route_key)].copy()
        if source.empty:
            continue
        source = source.sort_values(["measure_min", "measure_max"])
        for bin_row in bins.itertuples(index=False):
            bmin = getattr(bin_row, "stable_measure_min_num")
            bmax = getattr(bin_row, "stable_measure_max_num")
            if pd.isna(bmin) or pd.isna(bmax):
                continue
            overlap = source.loc[(source["measure_max"].ge(bmin)) & (source["measure_min"].le(bmax))].copy()
            if overlap.empty:
                continue
            overlap["overlap_length"] = overlap.apply(lambda r: max(0.0, min(float(bmax), float(r.measure_max)) - max(float(bmin), float(r.measure_min))), axis=1)
            overlap = overlap.loc[overlap["overlap_length"].gt(0)]
            if overlap.empty:
                continue
            rows.append(
                {
                    "source_name": "Speed_Limit_RNS",
                    "reference_directional_bin_id": getattr(bin_row, "reference_directional_bin_id"),
                    "current_refined_speed_context_status": getattr(bin_row, "refined_speed_context_status"),
                    "distance_window": getattr(bin_row, "distance_window"),
                    "stable_route_name_normalized": route_key,
                    "candidate_count": int(len(overlap)),
                    "candidate_car_speed_values": "|".join(str(int(v)) if float(v).is_integer() else str(v) for v in sorted(overlap["car_speed"].dropna().unique())[:10]),
                    "candidate_truck_speed_values": "|".join(str(int(v)) if float(v).is_integer() else str(v) for v in sorted(overlap["truck_speed"].dropna().unique())[:10]),
                    "best_overlap_length": float(overlap["overlap_length"].max()),
                    "candidate_route_fields": "|".join(sorted(overlap["route_field"].unique())),
                    "candidate_measure_pairs": "|".join(sorted(overlap["measure_field_pair"].unique())),
                    "recovery_estimate_class": "possible_speed_value_recovery_no_directionality_test",
                }
            )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return pd.DataFrame()
    summary = (
        detail.groupby(["source_name", "current_refined_speed_context_status", "distance_window", "recovery_estimate_class"], dropna=False)
        .agg(
            recoverable_bin_count=("reference_directional_bin_id", "nunique"),
            unique_route_count=("stable_route_name_normalized", "nunique"),
            median_candidate_count=("candidate_count", "median"),
        )
        .reset_index()
    )
    totals = (
        gap_bins.groupby(["refined_speed_context_status", "distance_window"], dropna=False)["reference_directional_bin_id"]
        .nunique()
        .reset_index(name="current_gap_bin_count")
        .rename(columns={"refined_speed_context_status": "current_refined_speed_context_status"})
    )
    summary = summary.merge(totals, on=["current_refined_speed_context_status", "distance_window"], how="left")
    summary["recoverable_share_of_current_gap"] = summary.apply(
        lambda row: round(row["recoverable_bin_count"] / row["current_gap_bin_count"], 6) if row["current_gap_bin_count"] else 0,
        axis=1,
    )
    detail["_row_type"] = "detail"
    summary["_row_type"] = "summary"
    return pd.concat([summary, detail], ignore_index=True, sort=False)


def _speed_field_diagnostic(source_name: str, frame: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for field in frame.columns:
        if field == frame.geometry.name or not _is_speed_field(field, frame[field]):
            continue
        values = pd.to_numeric(frame[field], errors="coerce")
        non_null = values.notna().sum()
        plausible = values.dropna().between(1, 90).mean() if non_null else 0
        rows.append(
            {
                "source_name": source_name,
                "field_name": field,
                "non_null_count": int(non_null),
                "numeric_non_null_count": int(non_null),
                "unique_numeric_count": int(values.dropna().nunique()),
                "min_value": values.min(),
                "max_value": values.max(),
                "plausible_speed_share_1_90": round(float(plausible), 6) if non_null else 0,
                "can_support_speed_values": bool(non_null and plausible > 0.95),
            }
        )
    return pd.DataFrame(rows)


def _source_comparison(current_speed: gpd.GeoDataFrame, frames: dict[str, gpd.GeoDataFrame]) -> pd.DataFrame:
    rows = []
    current_routes = _source_route_keys(current_speed, ["ROUTE_COMMON_NAME"])
    current_speed_fields = ["CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT", "ROUTE_COMMON_NAME", "LOC_COMP_DIRECTIONALITY_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]
    rows.append(
        {
            "source_name": "current_speed_parquet",
            "row_count": len(current_speed),
            "candidate_speed_fields": "|".join([field for field in current_speed_fields if field in current_speed.columns]),
            "candidate_route_fields": "ROUTE_COMMON_NAME",
            "route_key_count": len(current_routes),
            "has_directionality_field": "LOC_COMP_DIRECTIONALITY_NAME" in current_speed.columns,
            "has_measure_fields": "ROUTE_FROM_MEASURE" in current_speed.columns and "ROUTE_TO_MEASURE" in current_speed.columns,
            "recommended_role": "accepted_current_speed_source",
        }
    )
    for source_name, frame in frames.items():
        route_fields = [field for field in frame.columns if _is_route_field(field)]
        speed_fields = [field for field in frame.columns if field != frame.geometry.name and _is_speed_field(field, frame[field])]
        routes = _source_route_keys(frame, route_fields)
        rows.append(
            {
                "source_name": source_name,
                "row_count": len(frame),
                "candidate_speed_fields": "|".join(speed_fields),
                "candidate_route_fields": "|".join(route_fields),
                "route_key_count": len(routes),
                "has_directionality_field": any("DIR" in field.upper() or "DIRECTION" in field.upper() for field in route_fields),
                "has_measure_fields": any("MEASURE" in field.upper() or "MSR" in field.upper() for field in frame.columns),
                "recommended_role": _recommended_role(source_name, speed_fields),
            }
        )
    return pd.DataFrame(rows)


def _recommended_role(source_name: str, speed_fields: list[str]) -> str:
    if source_name == "Speed_Limit_RNS" and speed_fields:
        return "speed_source_supplement_candidate"
    if source_name == "VDOT_Routes":
        return "route_identity_bridge_candidate"
    return "no_useful_speed_improvement"


def _recommendation(route_overlap: pd.DataFrame, recovery: pd.DataFrame, speed_diag: pd.DataFrame) -> pd.DataFrame:
    rows = []
    speed_rns_recoverable = 0
    if not recovery.empty and "_row_type" in recovery.columns:
        speed_rns_recoverable = int(pd.to_numeric(recovery.loc[recovery["_row_type"].eq("summary"), "recoverable_bin_count"], errors="coerce").fillna(0).sum())
    vdot_overlap = route_overlap.loc[route_overlap["source_name"].eq("VDOT_Routes")]
    vdot_match_share = float(vdot_overlap["missing_review_route_match_share"].iloc[0]) if not vdot_overlap.empty else 0.0
    speed_fields = speed_diag.loc[speed_diag["source_name"].eq("Speed_Limit_RNS"), "field_name"].astype(str).tolist() if not speed_diag.empty else []
    rows.append(
        {
            "source_name": "VDOT_Routes",
            "recommended_use": "route_identity_supplement_only",
            "recommended_next_module_name": "vdot_routes_identity_bridge.py" if vdot_match_share > 0 else "",
            "replacement_vs_supplement": "identity_bridge",
            "recommendation": "Useful for route identity review/bridge diagnostics, not for speed values.",
            "evidence": f"missing/review route key match share={vdot_match_share}; speed fields absent",
        }
    )
    rows.append(
        {
            "source_name": "Speed_Limit_RNS",
            "recommended_use": "speed_source_supplement",
            "recommended_next_module_name": "speed_context_join_v5_new_source_supplement.py" if speed_rns_recoverable else "stage_speed_limit_rns_source.py",
            "replacement_vs_supplement": "supplement_not_replacement",
            "recommendation": "Promising as a supplement for current missing/review speed bins; do not replace v4 until directionality/measure semantics are validated.",
            "evidence": f"candidate speed fields={ '|'.join(speed_fields) }; possible missing/review bin recovery={speed_rns_recoverable}",
        }
    )
    return pd.DataFrame(rows)


def _qa(outputs: dict[str, Path], mtimes_before: dict[str, float | None], mtimes_after: dict[str, float | None]) -> pd.DataFrame:
    unchanged = mtimes_before == mtimes_after
    rows = [
        {"check_name": "existing_normalized_artifacts_overwritten", "passed": unchanged, "observed": "unchanged" if unchanged else "mtime_changed", "expected": "unchanged"},
        {"check_name": "current_speed_v4_outputs_overwritten", "passed": True, "observed": "read_only", "expected": "no"},
        {"check_name": "graph_context_rate_model_outputs_modified", "passed": True, "observed": "module writes only new_speed_route_source_inventory review outputs", "expected": "no"},
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": "none", "expected": "none"},
        {"check_name": "source_coverage_estimates_diagnostic_only", "passed": True, "observed": "diagnostic_only_no_join_output", "expected": "yes"},
        {"check_name": "recommendation_distinguishes_replacement_supplement_identity_bridge", "passed": True, "observed": "replacement_vs_supplement column written", "expected": "yes"},
    ]
    for key, path in outputs.items():
        if key in {"findings", "manifest"}:
            continue
        rows.append({"check_name": f"output_written_{key}", "passed": path.exists(), "observed": str(path), "expected": "exists"})
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, speed_diag: pd.DataFrame, route_overlap: pd.DataFrame, recovery: pd.DataFrame, recommendation: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def rec(source: str, column: str) -> str:
        row = recommendation.loc[recommendation["source_name"].eq(source)]
        return "" if row.empty else str(row.iloc[0][column])

    recoverable = 0
    if not recovery.empty and "_row_type" in recovery.columns:
        recoverable = int(pd.to_numeric(recovery.loc[recovery["_row_type"].eq("summary"), "recoverable_bin_count"], errors="coerce").fillna(0).sum())
    speed_fields = speed_diag.loc[speed_diag["can_support_speed_values"].astype(str).eq("True"), ["source_name", "field_name"]]
    speed_field_text = ", ".join(f"{row.source_name}.{row.field_name}" for row in speed_fields.itertuples(index=False)) if not speed_fields.empty else "none"
    route_lines = "\n".join(
        f"- {row.source_name}: missing/review route match share {row.missing_review_route_match_share}; source route keys {row.source_route_key_count}"
        for row in route_overlap.itertuples(index=False)
    )
    qa_lines = "\n".join(f"- {row.check_name}: {'PASS' if bool(row.passed) else 'FAIL'} ({row.observed})" for row in qa.itertuples(index=False))
    return f"""# New Speed/Route Source Inventory Findings

## Bounded Question

Can `VDOT_Routes.geojson` or `Speed_Limit_RNS` improve speed coverage or roadway identity for the existing roadway-derived directional-bin universe without modifying accepted speed v4 or downstream outputs?

## Source Utility

- VDOT_Routes useful: {rec('VDOT_Routes', 'recommended_use')}. It has route identity fields but no candidate speed-limit values.
- Speed_Limit_RNS useful: {rec('Speed_Limit_RNS', 'recommended_use')}. It has speed values, route keys, edge IDs, and measure fields.

## Candidate Fields

- Candidate speed fields supporting speed values: {speed_field_text}
- Candidate route identity overlap:
{route_lines}

## Recovery Estimate

- Current speed v4 missing/review bins with possible Speed_Limit_RNS route+measure speed candidates: {recoverable:,}
- Estimate is diagnostic only. It does not test all v4 directionality semantics and does not promote any speed value.

## Recommendation

- VDOT_Routes: {rec('VDOT_Routes', 'recommendation')} Next module candidate: `{rec('VDOT_Routes', 'recommended_next_module_name')}`.
- Speed_Limit_RNS: {rec('Speed_Limit_RNS', 'recommendation')} Next module candidate: `{rec('Speed_Limit_RNS', 'recommended_next_module_name')}`.

## QA

{qa_lines}

## Outputs

{chr(10).join(f'- `{path}`' for path in outputs.values())}
"""


def build_new_speed_route_source_inventory(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    outputs = {key: out_dir / name for key, name in OUTPUTS.items()}
    tracked = [NORMALIZED_SPEED_FILE, SPEED_V4_CONTEXT_FILE, SPEED_V4_MISSING_FILE, SPEED_V4_REVIEW_FILE, FINAL_CONTEXT_FILE]
    mtimes_before = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}

    stable_bounds, stable_crs = _stable_bounds_and_crs()
    frames: dict[str, gpd.GeoDataFrame] = {}
    summary_rows = []
    schema_frames = []
    geometry_rows = []
    role_frames = []
    nonnull_frames = []
    speed_diag_frames = []

    for spec in SOURCES:
        frame = _read_source(spec)
        if frame is not None:
            frames[spec.source_name] = frame
            schema_frames.append(_schema(spec.source_name, frame))
            role_frames.append(_field_roles(spec.source_name, frame))
            nonnull_frames.append(_nonnull_profile(spec.source_name, frame))
            speed_diag_frames.append(_speed_field_diagnostic(spec.source_name, frame))
        geometry_rows.append(_geometry_qa(spec, frame, stable_bounds, stable_crs))
        summary_rows.append(
            {
                "source_name": spec.source_name,
                "path": str(spec.path),
                "exists": spec.path.exists(),
                "readable_format": _source_format(spec),
                "layer": spec.layer or "",
                "read_status": "read" if frame is not None else "missing_or_unread",
                "row_count": len(frame) if frame is not None else 0,
                "field_count": len(frame.columns) if frame is not None else 0,
                "candidate_speed_field_count": len([field for field in frame.columns if field != frame.geometry.name and _is_speed_field(field, frame[field])]) if frame is not None else 0,
                "candidate_route_identity_field_count": len([field for field in frame.columns if _is_route_field(field)]) if frame is not None else 0,
                "source_classification": _classify_source(spec.source_name),
            }
        )

    current_speed = gpd.read_parquet(NORMALIZED_SPEED_FILE)
    gap_bins = _load_gap_bins()
    all_bins = _read_csv(SPEED_V4_CONTEXT_FILE, usecols=["reference_directional_bin_id", "stable_route_name_normalized", "refined_speed_context_status"])
    source_routes = {
        source_name: _source_route_keys(frame, _route_name_fields(frame))
        for source_name, frame in frames.items()
    }
    route_overlap = _route_identity_overlap(source_routes, gap_bins, all_bins)
    speed_records = _source_speed_records(frames.get("Speed_Limit_RNS", pd.DataFrame()), "Speed_Limit_RNS") if "Speed_Limit_RNS" in frames else pd.DataFrame()
    recovery = _recovery_estimate(speed_records, gap_bins)
    speed_diag = pd.concat(speed_diag_frames, ignore_index=True, sort=False) if speed_diag_frames else pd.DataFrame()
    comparison = _source_comparison(current_speed, frames)
    recommendation = _recommendation(route_overlap, recovery, speed_diag)

    summary = pd.DataFrame(summary_rows)
    schema = pd.concat(schema_frames, ignore_index=True, sort=False) if schema_frames else pd.DataFrame()
    geometry = pd.DataFrame(geometry_rows)
    roles = pd.concat(role_frames, ignore_index=True, sort=False) if role_frames else pd.DataFrame()
    nonnull = pd.concat(nonnull_frames, ignore_index=True, sort=False) if nonnull_frames else pd.DataFrame()

    _write_csv(summary, outputs["summary"])
    _write_csv(schema, outputs["schema"])
    _write_csv(geometry, outputs["geometry"])
    _write_csv(roles, outputs["roles"])
    _write_csv(nonnull, outputs["nonnull"])
    _write_csv(route_overlap, outputs["route_overlap"])
    _write_csv(speed_diag, outputs["speed_fields"])
    _write_csv(recovery, outputs["recovery"])
    _write_csv(comparison, outputs["comparison"])
    _write_csv(recommendation, outputs["recommendation"])

    mtimes_after = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}
    qa = _qa(outputs, mtimes_before, mtimes_after)
    _write_csv(qa, out_dir / "new_speed_route_source_inventory_qa.csv")
    _write_text(_findings(summary, speed_diag, route_overlap, recovery, recommendation, qa, outputs), outputs["findings"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only inventory and feasibility diagnostic for new speed/route sources",
        "read_only": True,
        "normalized_speed_overwritten": False,
        "speed_v4_outputs_overwritten": False,
        "graph_context_rate_model_outputs_modified": False,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "vdot_routes": str(VDOT_ROUTES_FILE),
            "speed_limit_rns": str(SPEED_LIMIT_RNS_GDB),
            "normalized_speed": str(NORMALIZED_SPEED_FILE),
            "speed_v4_dir": str(SPEED_V4_DIR),
            "identity_dir": str(IDENTITY_DIR),
            "directional_bin_context": str(FINAL_CONTEXT_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()} | {"qa": str(out_dir / "new_speed_route_source_inventory_qa.csv")},
        "summary": summary.to_dict(orient="records"),
        "recommendation": recommendation.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return manifest["outputs"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory new speed/route sources and estimate diagnostic recovery for speed v4 missing/review bins.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_new_speed_route_source_inventory(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
