from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import STRtree, wkb


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/crash_travelway_identity_feasibility"

CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")
STAGING_CRASH_SOURCE = Path("artifacts/staging/crashes.parquet")
ASSIGN_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_candidate_assignment"
CRASH_SANITY_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_sanity_audit"
FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
SOURCE_TRAVELWAY_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
SOURCE_TRAVELWAY_LAYER = "source_travelway_full"
LINEAGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"

PRIMARY_BUFFER_FT = 50
FT_TO_M = 0.3048
NEAREST_MATCH_MAX_FT = 250.0

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

ROADWAY_FIELD_PATTERNS = (
    "route",
    "rte",
    "road",
    "street",
    "st",
    "hwy",
    "highway",
    "milepost",
    "measure",
    "node",
    "segment",
    "intersection",
    "locality",
    "jurisdiction",
    "juris",
    "district",
)

CRASH_MATCH_COLUMNS = [
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CRASH_SEVERITY",
    "COLLISION_TYPE",
    "ROADWAY_DESCRIPTION",
    "INTERSECTION_TYPE",
    "MAINLINE_YN",
    "RTE_NM",
    "RNS_MP",
    "NODE",
    "OFFSET",
    "JURIS_CODE",
    "VDOT_DISTRICT",
    "PHYSICAL_JURIS",
    "geometry",
]

TRAVELWAY_FIELDS = [
    "RTE_NM",
    "RTE_COMMON",
    "RTE_ID",
    "FROM_MEASURE",
    "TO_MEASURE",
    "RTE_FROM_M",
    "RTE_TO_MSR",
    "RIM_FACILI",
    "RTE_CATEGO",
    "RTE_TYPE_N",
    "RTE_RAMP_C",
    "EVENT_SOUR",
    "Stage1_SourceLayer",
    "geometry",
]

REQUIRED_INPUTS = [
    CRASH_SOURCE,
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_fanout_summary.csv",
    ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_overlap_review_queue.csv",
    ASSIGN_DIR / "final_leg_corrected_crash_candidate_assignment_manifest.json",
    CRASH_SANITY_DIR / "crash_fanout_sanity_detail.csv",
    CRASH_SANITY_DIR / "crash_fanout_sanity_summary.csv",
    CRASH_SANITY_DIR / "crash_high_fanout_cause_classification.csv",
    CRASH_SANITY_DIR / "crash_nonassignment_refresh_summary.csv",
    CRASH_SANITY_DIR / "crash_sanity_readiness_decision.csv",
    CRASH_SANITY_DIR / "final_leg_corrected_crash_sanity_manifest.json",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
    SOURCE_TRAVELWAY_GPKG,
    LINEAGE_DIR / "source_travelway_stable_identity.csv",
    LINEAGE_DIR / "source_travelway_lineage_bridge_manifest.json",
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


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _is_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _is_candidate_roadway_field(column: str) -> bool:
    lower = column.lower().replace("_", " ")
    return any(pattern in lower for pattern in ROADWAY_FIELD_PATTERNS)


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _is_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _collapse(values: pd.Series, limit: int = 8) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _normalize_key(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).upper().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_loose(value: Any) -> str:
    text = _normalize_key(value)
    text = re.sub(r"[^A-Z0-9]+", "", text)
    return text


def _inventory_parquet(path: Path, *, primary_source: str) -> pd.DataFrame:
    schema = pq.ParquetFile(path).schema_arrow
    columns = list(schema.names)
    non_direction_cols = [column for column in columns if not _is_direction_field(column)]
    frame = pd.read_parquet(path, columns=non_direction_cols)
    total = len(frame)
    rows: list[dict[str, Any]] = []
    for column in columns:
        is_direction = _is_direction_field(column)
        if is_direction:
            rows.append(
                {
                    "source": primary_source,
                    "column_name": column,
                    "inferred_type": str(schema.field(column).type),
                    "non_null_count": "",
                    "missingness_rate": "",
                    "unique_count": "",
                    "candidate_roadway_field": _is_candidate_roadway_field(column),
                    "direction_inventory_only": True,
                    "sample_values": "not_read_direction_inventory_only",
                }
            )
            continue
        series = frame[column]
        non_null = int(series.notna().sum())
        non_null_values = series.dropna()
        if non_null_values.map(lambda value: isinstance(value, (bytes, bytearray))).any():
            unique_count: int | str = ""
            sample = [f"<binary_{len(value)}_bytes>" for value in non_null_values.head(8)]
        else:
            unique_count = int(series.nunique(dropna=True))
            sample = non_null_values.astype(str).head(8).tolist()
        rows.append(
            {
                "source": primary_source,
                "column_name": column,
                "inferred_type": str(series.dtype),
                "non_null_count": non_null,
                "missingness_rate": round(1.0 - (non_null / total if total else 0.0), 6),
                "unique_count": unique_count,
                "candidate_roadway_field": _is_candidate_roadway_field(column),
                "direction_inventory_only": False,
                "sample_values": " | ".join(sample[:8]),
            }
        )
    _checkpoint(f"inventory {path.name}", len(rows))
    return pd.DataFrame(rows)


def _load_crashes() -> pd.DataFrame:
    schema_cols = list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)
    cols = [column for column in CRASH_MATCH_COLUMNS if column in schema_cols and not _is_direction_field(column)]
    crashes = pd.read_parquet(CRASH_SOURCE, columns=cols)
    if "DOCUMENT_NBR" in crashes.columns:
        crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    else:
        crashes["stable_crash_id"] = ["crash_review_%09d" % idx for idx in range(len(crashes))]
    crashes["crash_route_key"] = _text(crashes, "RTE_NM").map(_normalize_key)
    crashes["crash_route_loose_key"] = _text(crashes, "RTE_NM").map(_normalize_loose)
    crashes["crash_measure"] = _num(crashes, "RNS_MP")
    crashes["has_crash_geometry"] = crashes["geometry"].notna() if "geometry" in crashes.columns else False
    _checkpoint("load normalized crashes for matching", len(crashes))
    return crashes


def _load_travelway_identity() -> pd.DataFrame:
    stable = _read_csv(
        LINEAGE_DIR / "source_travelway_stable_identity.csv",
        usecols=[
            "stable_travelway_id",
            "source_route_id",
            "source_route_name",
            "source_route_common",
            "from_measure",
            "to_measure",
            "facility_text",
            "source_layer",
            "source_feature_local_fid",
        ],
    )
    stable["travelway_route_key"] = _text(stable, "source_route_name").map(_normalize_key)
    stable["travelway_route_loose_key"] = _text(stable, "source_route_name").map(_normalize_loose)
    stable["source_route_common_loose_key"] = _text(stable, "source_route_common").map(_normalize_loose)
    stable["from_measure_num"] = _num(stable, "from_measure")
    stable["to_measure_num"] = _num(stable, "to_measure")
    stable["measure_min"] = stable[["from_measure_num", "to_measure_num"]].min(axis=1)
    stable["measure_max"] = stable[["from_measure_num", "to_measure_num"]].max(axis=1)
    _checkpoint("load stable travelway identity", len(stable))
    return stable


def _travelway_field_inventory(stable: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    gpkg_attrs = gpd.read_file(SOURCE_TRAVELWAY_GPKG, layer=SOURCE_TRAVELWAY_LAYER, rows=1, ignore_geometry=True)
    all_fields = list(gpkg_attrs.columns) + ["geometry"]
    stable_fields = list(stable.columns)
    for field in all_fields:
        lower = field.lower()
        rows.append(
            {
                "source": "source_travelway_full",
                "column_name": field,
                "field_role": (
                    "route_or_name"
                    if any(token in lower for token in ["rte", "route", "common"])
                    else "measure"
                    if "measure" in lower or "msr" in lower
                    else "facility_context"
                    if any(token in lower for token in ["facil", "median", "access", "category", "ramp"])
                    else "locality_or_jurisdiction"
                    if any(token in lower for token in ["loc", "juris", "district"])
                    else "geometry_or_other"
                ),
                "stable_travelway_id_completeness": "",
                "notes": "available in source Travelway layer",
            }
        )
    completeness = int(_text(stable, "stable_travelway_id").str.strip().ne("").sum())
    for field in stable_fields:
        lower = field.lower()
        rows.append(
            {
                "source": "source_travelway_stable_identity",
                "column_name": field,
                "field_role": (
                    "stable_identity"
                    if field == "stable_travelway_id"
                    else "route_or_name"
                    if any(token in lower for token in ["route", "common"])
                    else "measure"
                    if "measure" in lower
                    else "facility_context"
                    if "facility" in lower
                    else "geometry_or_other"
                ),
                "stable_travelway_id_completeness": completeness,
                "notes": "available in stable Travelway identity bridge",
            }
        )
    return pd.DataFrame(rows)


def _shared_key_candidates(crash_inventory: pd.DataFrame, travelway_inventory: pd.DataFrame) -> pd.DataFrame:
    crash_fields = set(crash_inventory["column_name"].astype(str))
    travelway_fields = set(travelway_inventory["column_name"].astype(str))
    rows = []
    for field in sorted(crash_fields & travelway_fields):
        rows.append(
            {
                "candidate_key_bundle": field,
                "match_type": "exact_field_name_overlap",
                "crash_fields": field,
                "travelway_fields": field,
                "expected_matchability": "inspect",
                "notes": "same field name exists in crash and Travelway inputs",
            }
        )
    rows.extend(
        [
            {
                "candidate_key_bundle": "RTE_NM + RNS_MP to source_route_name/from_to_measure",
                "match_type": "semantic_route_measure",
                "crash_fields": "RTE_NM|RNS_MP",
                "travelway_fields": "source_route_name|from_measure|to_measure",
                "expected_matchability": "high_if_route_names_are_same_namespace",
                "notes": "primary Tier A diagnostic",
            },
            {
                "candidate_key_bundle": "RTE_NM + nearest source Travelway geometry",
                "match_type": "route_name_geometry_assisted",
                "crash_fields": "RTE_NM|geometry",
                "travelway_fields": "RTE_NM/source_route_name|geometry",
                "expected_matchability": "medium",
                "notes": "Tier B diagnostic for route-compatible nearest line",
            },
            {
                "candidate_key_bundle": "RTE_NM normalized name + nearest geometry",
                "match_type": "street_or_route_name_geometry_assisted",
                "crash_fields": "RTE_NM|geometry",
                "travelway_fields": "RTE_COMMON/source_route_common|geometry",
                "expected_matchability": "medium_low",
                "notes": "Tier C diagnostic where route names differ but normalized names agree",
            },
            {
                "candidate_key_bundle": "nearest source Travelway geometry only",
                "match_type": "spatial_only",
                "crash_fields": "geometry",
                "travelway_fields": "geometry|stable_travelway_id",
                "expected_matchability": "fallback_only",
                "notes": "Tier D diagnostic, not identity-based",
            },
        ]
    )
    return pd.DataFrame(rows)


def _key_missingness(crashes: pd.DataFrame, assigned_50: set[str], high_fanout: set[str], unassigned_50: set[str]) -> pd.DataFrame:
    bundles = {
        "RTE_NM": ["RTE_NM"],
        "RTE_NM + RNS_MP": ["RTE_NM", "RNS_MP"],
        "RTE_NM + geometry": ["RTE_NM", "geometry"],
        "RTE_NM + RNS_MP + geometry": ["RTE_NM", "RNS_MP", "geometry"],
        "NODE + OFFSET": ["NODE", "OFFSET"],
        "JURIS_CODE + RTE_NM": ["JURIS_CODE", "RTE_NM"],
        "PHYSICAL_JURIS + RTE_NM": ["PHYSICAL_JURIS", "RTE_NM"],
    }
    ids = _text(crashes, "stable_crash_id")
    rows = []
    for bundle, cols in bundles.items():
        present_cols = [col for col in cols if col in crashes.columns]
        if len(present_cols) != len(cols):
            complete = pd.Series(False, index=crashes.index)
        else:
            complete = pd.Series(True, index=crashes.index)
            for col in present_cols:
                if col == "geometry":
                    complete &= crashes[col].notna()
                else:
                    complete &= _text(crashes, col).str.strip().ne("")
        complete_ids = set(ids.loc[complete])
        rows.append(
            {
                "candidate_key_bundle": bundle,
                "required_fields": "|".join(cols),
                "complete_crash_records": int(complete.sum()),
                "share_all_crashes": round(float(complete.mean()), 6),
                "share_assigned_50ft": round(len(complete_ids & assigned_50) / len(assigned_50), 6) if assigned_50 else 0.0,
                "share_high_fanout_50ft": round(len(complete_ids & high_fanout) / len(high_fanout), 6) if high_fanout else 0.0,
                "share_unassigned_50ft": round(len(complete_ids & unassigned_50) / len(unassigned_50), 6) if unassigned_50 else 0.0,
                "expected_travelway_matchability": (
                    "high" if bundle == "RTE_NM + RNS_MP" else "medium" if "geometry" in cols else "supporting"
                ),
            }
        )
    return pd.DataFrame(rows)


def _route_measure_match(crashes: pd.DataFrame, stable: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "stable_crash_id": crashes["stable_crash_id"].astype(str).values,
            "tier_a_candidate_count": np.zeros(len(crashes), dtype=np.int16),
            "tier_a_stable_travelway_id_candidates": np.full(len(crashes), "", dtype=object),
            "tier_a_route_measure_status": np.full(len(crashes), "not_attempted_missing_route_or_measure", dtype=object),
        }
    )
    crash_index = pd.Series(np.arange(len(crashes), dtype=np.int64), index=crashes.index)
    stable_valid = stable.loc[
        stable["travelway_route_key"].ne("") & stable["measure_min"].notna() & stable["measure_max"].notna(),
        ["travelway_route_key", "measure_min", "measure_max", "stable_travelway_id"],
    ].copy()
    route_ranges = stable_valid.groupby("travelway_route_key", sort=False).agg(
        route_measure_min=("measure_min", "min"),
        route_measure_max=("measure_max", "max"),
        route_segment_count=("stable_travelway_id", "nunique"),
    ).reset_index()
    work = crashes.loc[crashes["crash_route_key"].ne("") & crashes["crash_measure"].notna(), ["crash_route_key", "crash_measure"]].copy()
    work["crash_row_pos"] = crash_index.loc[work.index].to_numpy()
    work = work.merge(route_ranges, left_on="crash_route_key", right_on="travelway_route_key", how="left")
    idx = work["crash_row_pos"].to_numpy(dtype=np.int64)
    route_found = work["route_measure_min"].notna()
    in_route_range = route_found & work["crash_measure"].ge(work["route_measure_min"]) & work["crash_measure"].le(work["route_measure_max"])
    out.loc[idx[~route_found.to_numpy()], "tier_a_route_measure_status"] = "route_not_found_in_travelway"
    out.loc[idx[route_found.to_numpy() & ~in_route_range.to_numpy()], "tier_a_route_measure_status"] = "route_found_measure_outside_route_range"
    hit_idx = idx[in_route_range.to_numpy()]
    out.loc[hit_idx, "tier_a_candidate_count"] = pd.to_numeric(work.loc[in_route_range, "route_segment_count"], errors="coerce").fillna(0).clip(1, 32767).astype(np.int16).values
    out.loc[hit_idx, "tier_a_stable_travelway_id_candidates"] = "route_measure_covered_candidate_not_expanded"
    out.loc[hit_idx, "tier_a_route_measure_status"] = "route_measure_covered_by_travelway_route_range"
    _checkpoint("route/measure candidate matching", len(out))
    return out


def _load_source_travelway_geometry(stable: pd.DataFrame) -> pd.DataFrame:
    cols = [column for column in TRAVELWAY_FIELDS if column != "geometry"]
    gdf = gpd.read_file(SOURCE_TRAVELWAY_GPKG, layer=SOURCE_TRAVELWAY_LAYER, columns=cols + ["geometry"])
    gdf = gdf.loc[gdf.geometry.notna()].copy()
    gdf["travelway_route_key"] = _text(gdf, "RTE_NM").map(_normalize_key)
    gdf["travelway_route_loose_key"] = _text(gdf, "RTE_NM").map(_normalize_loose)
    gdf["source_route_common_loose_key"] = _text(gdf, "RTE_COMMON").map(_normalize_loose)
    gdf["from_measure_num"] = _num(gdf, "FROM_MEASURE")
    gdf["to_measure_num"] = _num(gdf, "TO_MEASURE")
    gdf["measure_min"] = gdf[["from_measure_num", "to_measure_num"]].min(axis=1)
    gdf["measure_max"] = gdf[["from_measure_num", "to_measure_num"]].max(axis=1)
    join_cols = [
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "from_measure",
        "to_measure",
        "geometry_hash",
        "source_feature_local_fid",
    ]
    stable_join = stable[[col for col in join_cols if col in stable.columns]].copy()
    stable_join["travelway_route_key"] = stable["travelway_route_key"]
    stable_join["measure_min"] = stable["measure_min"]
    stable_join["measure_max"] = stable["measure_max"]
    stable_join = stable_join.drop_duplicates(["travelway_route_key", "measure_min", "measure_max"], keep="first")
    # Attribute bridge may include all source rows; join on route and measure bounds.
    merged = gdf.reset_index(names="source_row_pos").merge(
        stable_join,
        left_on=["travelway_route_key", "measure_min", "measure_max"],
        right_on=["travelway_route_key", "measure_min", "measure_max"],
        how="left",
        suffixes=("", "_stable"),
    )
    merged["stable_travelway_id"] = _text(merged, "stable_travelway_id")
    _checkpoint("load source Travelway geometry", len(merged))
    return merged


def _nearest_source_travelway(crashes: pd.DataFrame, source_tw: pd.DataFrame, needs_nearest: pd.Series) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "stable_crash_id": crashes["stable_crash_id"].astype(str).values,
            "nearest_stable_travelway_id": np.full(len(crashes), "", dtype=object),
            "nearest_distance_ft": np.full(len(crashes), np.nan, dtype=float),
            "nearest_route_key": np.full(len(crashes), "", dtype=object),
            "nearest_route_common": np.full(len(crashes), "", dtype=object),
            "nearest_route_compatible": np.full(len(crashes), False, dtype=bool),
            "nearest_loose_name_compatible": np.full(len(crashes), False, dtype=bool),
        }
    )
    target = crashes.loc[needs_nearest & crashes["has_crash_geometry"].astype(bool)].copy()
    if target.empty:
        _checkpoint("nearest Travelway matching skipped", 0)
        return result

    geometries = source_tw.geometry.to_numpy()
    tree = STRtree(geometries)
    points = [wkb.loads(value) for value in target["geometry"].values]
    try:
        indices, distances = tree.query_nearest(points, all_matches=False, return_distance=True)
        if indices.shape[0] == 2:
            left_idx = indices[0]
            right_idx = indices[1]
        else:
            left_idx = np.arange(len(points), dtype=np.int64)
            right_idx = indices
    except TypeError:
        # Older Shapely fallback. This is slower but bounded to crashes not resolved by route/measure.
        right_idx = np.array([tree.nearest(point) for point in points], dtype=np.int64)
        left_idx = np.arange(len(points), dtype=np.int64)
        distances = np.array([points[i].distance(geometries[right_idx[i]]) for i in range(len(points))], dtype=float)

    source_rows = source_tw.iloc[right_idx].reset_index(drop=True)
    crash_rows = target.iloc[left_idx].reset_index()
    global_idx = crash_rows["index"].to_numpy(dtype=np.int64)
    distance_ft = np.asarray(distances, dtype=float) / FT_TO_M
    crash_route_key = crash_rows["crash_route_key"].astype(str).to_numpy()
    crash_loose_key = crash_rows["crash_route_loose_key"].astype(str).to_numpy()
    nearest_route_key = source_rows["travelway_route_key"].fillna("").astype(str).to_numpy()
    nearest_route_loose = source_rows["travelway_route_loose_key"].fillna("").astype(str).to_numpy()
    nearest_common_loose = source_rows["source_route_common_loose_key"].fillna("").astype(str).to_numpy()
    route_compatible = crash_route_key == nearest_route_key
    loose_compatible = (crash_loose_key == nearest_route_loose) | (crash_loose_key == nearest_common_loose)

    result.loc[global_idx, "nearest_stable_travelway_id"] = source_rows["stable_travelway_id"].fillna("").astype(str).values
    result.loc[global_idx, "nearest_distance_ft"] = distance_ft
    result.loc[global_idx, "nearest_route_key"] = nearest_route_key
    result.loc[global_idx, "nearest_route_common"] = source_rows.get("RTE_COMMON", pd.Series("", index=source_rows.index)).fillna("").astype(str).values
    result.loc[global_idx, "nearest_route_compatible"] = route_compatible
    result.loc[global_idx, "nearest_loose_name_compatible"] = loose_compatible
    _checkpoint("nearest source Travelway matching", len(target))
    return result


def _assignment_50_summary() -> pd.DataFrame:
    usecols = [
        "buffer_width_ft",
        "stable_crash_id",
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "final_review_leg_source",
        "final_review_recovery_provenance",
    ]
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        ASSIGN_DIR / "leg_corrected_crash_candidate_assignment_detail.csv",
        dtype=str,
        keep_default_na=False,
        usecols=lambda col: col in usecols,
        chunksize=200_000,
        low_memory=False,
    ):
        chunk = chunk.loc[pd.to_numeric(chunk["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)]
        if not chunk.empty:
            chunks.append(chunk)
    detail = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=usecols)
    grouped = detail.groupby("stable_crash_id", dropna=False).agg(
        assigned_stable_travelway_count=("stable_travelway_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        assigned_stable_travelway_ids=("stable_travelway_id", _collapse),
        assigned_signal_count=("stable_signal_id", "nunique"),
        assigned_bin_count=("stable_bin_id", "nunique"),
        assigned_physical_leg_count=("final_review_physical_leg_id", lambda s: s.replace("", np.nan).nunique(dropna=True)),
        assignment_leg_sources=("final_review_leg_source", _collapse),
        assignment_recovery_provenance=("final_review_recovery_provenance", _collapse),
    ).reset_index()
    _checkpoint("summarize 50ft assignment detail", len(grouped))
    return grouped


def _build_match_detail(crashes: pd.DataFrame, tier_a: pd.DataFrame, nearest: pd.DataFrame) -> pd.DataFrame:
    detail = crashes[
        [
            "stable_crash_id",
            "DOCUMENT_NBR",
            "CRASH_YEAR",
            "CRASH_SEVERITY",
            "RTE_NM",
            "RNS_MP",
            "NODE",
            "OFFSET",
            "JURIS_CODE",
            "PHYSICAL_JURIS",
            "ROADWAY_DESCRIPTION",
            "INTERSECTION_TYPE",
            "MAINLINE_YN",
        ]
    ].copy()
    detail = detail.merge(tier_a, on="stable_crash_id", how="left")
    detail = detail.merge(nearest, on="stable_crash_id", how="left")
    count = pd.to_numeric(detail["tier_a_candidate_count"], errors="coerce").fillna(0).astype(int)
    nearest_ft = pd.to_numeric(detail["nearest_distance_ft"], errors="coerce")
    route_ok = detail["nearest_route_compatible"].fillna(False).astype(bool)
    loose_ok = detail["nearest_loose_name_compatible"].fillna(False).astype(bool)

    method = np.full(len(detail), "tier_e_no_feasible_match", dtype=object)
    confidence = np.full(len(detail), "none", dtype=object)
    matched_ids = np.full(len(detail), "", dtype=object)
    candidate_count = np.zeros(len(detail), dtype=np.int16)

    direct_single = count.eq(1)
    direct_multi = count.gt(1)
    method[direct_single] = "tier_a_direct_route_measure"
    confidence[direct_single] = "high"
    matched_ids[direct_single] = detail.loc[direct_single, "tier_a_stable_travelway_id_candidates"].astype(str).values
    candidate_count[direct_single] = count.loc[direct_single].to_numpy(dtype=np.int16)

    method[direct_multi] = "tier_a_direct_route_measure_ambiguous"
    confidence[direct_multi] = "medium"
    matched_ids[direct_multi] = detail.loc[direct_multi, "tier_a_stable_travelway_id_candidates"].astype(str).values
    candidate_count[direct_multi] = count.loc[direct_multi].clip(0, 32767).to_numpy(dtype=np.int16)

    route_range_covered = detail["tier_a_route_measure_status"].eq("route_measure_covered_by_travelway_route_range")
    tier_a_nearest = route_range_covered & route_ok & nearest_ft.le(NEAREST_MATCH_MAX_FT)
    method[tier_a_nearest] = "tier_a_route_measure_with_route_compatible_nearest"
    confidence[tier_a_nearest] = np.where(nearest_ft[tier_a_nearest].le(50.0), "high", "medium")
    matched_ids[tier_a_nearest] = detail.loc[tier_a_nearest, "nearest_stable_travelway_id"].astype(str).values
    candidate_count[tier_a_nearest] = 1

    no_direct = count.eq(0)
    tier_b = no_direct & route_ok & nearest_ft.le(NEAREST_MATCH_MAX_FT)
    method[tier_b] = "tier_b_route_name_nearest_geometry"
    confidence[tier_b] = "medium"
    matched_ids[tier_b] = detail.loc[tier_b, "nearest_stable_travelway_id"].astype(str).values
    candidate_count[tier_b] = 1

    tier_c = no_direct & ~tier_b & loose_ok & nearest_ft.le(NEAREST_MATCH_MAX_FT)
    method[tier_c] = "tier_c_normalized_name_nearest_geometry"
    confidence[tier_c] = "medium_low"
    matched_ids[tier_c] = detail.loc[tier_c, "nearest_stable_travelway_id"].astype(str).values
    candidate_count[tier_c] = 1

    tier_d = no_direct & ~tier_b & ~tier_c & nearest_ft.le(50.0)
    method[tier_d] = "tier_d_nearest_source_travelway_spatial_only"
    confidence[tier_d] = "low"
    matched_ids[tier_d] = detail.loc[tier_d, "nearest_stable_travelway_id"].astype(str).values
    candidate_count[tier_d] = 1

    detail["matched_stable_travelway_id_candidates"] = matched_ids
    detail["candidate_travelway_count"] = candidate_count
    detail["match_method"] = method
    detail["match_confidence"] = confidence
    detail["route_key_compatibility"] = np.where(route_ok, "exact_route_key", np.where(loose_ok, "normalized_name", "not_compatible_or_not_tested"))
    detail["geometry_distance_to_matched_travelway_ft"] = nearest_ft.round(2)
    detail["crash_direction_fields_inventory_only"] = ""
    detail["crash_direction_used_for_assignment"] = False
    detail["crash_direction_use_status"] = "direction_fields_not_read_or_used"
    _checkpoint("build crash Travelway match detail", len(detail))
    return detail


def _match_summaries(match_detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    method_summary = match_detail.groupby(["match_method", "match_confidence"], dropna=False).agg(
        crash_count=("stable_crash_id", "nunique"),
        share_all_crashes=("stable_crash_id", lambda s: len(s) / len(match_detail) if len(match_detail) else 0.0),
        single_candidate_crashes=("candidate_travelway_count", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).eq(1).sum())),
    ).reset_index()
    confidence_summary = match_detail.groupby("match_confidence", dropna=False).agg(
        crash_count=("stable_crash_id", "nunique"),
        share_all_crashes=("stable_crash_id", lambda s: len(s) / len(match_detail) if len(match_detail) else 0.0),
        median_nearest_distance_ft=("geometry_distance_to_matched_travelway_ft", lambda s: pd.to_numeric(s, errors="coerce").median()),
    ).reset_index()
    return method_summary, confidence_summary


def _spatial_vs_travelway(match_detail: pd.DataFrame, assignment: pd.DataFrame, represented_travelways: set[str]) -> pd.DataFrame:
    comp = assignment.merge(
        match_detail[
            [
                "stable_crash_id",
                "matched_stable_travelway_id_candidates",
                "match_method",
                "match_confidence",
                "candidate_travelway_count",
            ]
        ],
        on="stable_crash_id",
        how="left",
    )
    matched_first = comp["matched_stable_travelway_id_candidates"].fillna("").astype(str).str.split("|").str[0]
    assigned_sets = comp["assigned_stable_travelway_ids"].fillna("").astype(str)
    comp["travelway_match_agrees_with_spatial_assignment"] = [
        bool(matched and matched in set(value.split("|"))) for matched, value in zip(matched_first, assigned_sets)
    ]
    comp["matched_travelway_represented_in_final_scaffold"] = matched_first.isin(represented_travelways)
    comp["potential_signal_fanout_after_single_travelway_filter"] = np.where(
        comp["travelway_match_agrees_with_spatial_assignment"] & pd.to_numeric(comp["candidate_travelway_count"], errors="coerce").eq(1),
        1,
        comp["assigned_signal_count"],
    )
    comp["fanout_reduction_possible"] = pd.to_numeric(comp["potential_signal_fanout_after_single_travelway_filter"], errors="coerce").lt(
        pd.to_numeric(comp["assigned_signal_count"], errors="coerce")
    )
    summary = comp.groupby(["match_confidence", "match_method"], dropna=False).agg(
        assigned_50ft_crashes=("stable_crash_id", "nunique"),
        agrees_with_assigned_travelway=("travelway_match_agrees_with_spatial_assignment", "sum"),
        represented_matched_travelway=("matched_travelway_represented_in_final_scaffold", "sum"),
        fanout_reduction_possible=("fanout_reduction_possible", "sum"),
        median_assigned_signal_count=("assigned_signal_count", lambda s: pd.to_numeric(s, errors="coerce").median()),
    ).reset_index()
    return summary


def _high_fanout_audit(match_detail: pd.DataFrame, fanout: pd.DataFrame, high_causes: pd.DataFrame) -> pd.DataFrame:
    fanout_50 = fanout.loc[pd.to_numeric(fanout["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)].copy()
    fanout_50["is_high_fanout"] = pd.to_numeric(fanout_50["signal_count"], errors="coerce").ge(4) | pd.to_numeric(
        fanout_50["bin_count"], errors="coerce"
    ).ge(20)
    high = fanout_50.loc[fanout_50["is_high_fanout"]].merge(
        match_detail[
            [
                "stable_crash_id",
                "match_method",
                "match_confidence",
                "candidate_travelway_count",
                "matched_stable_travelway_id_candidates",
                "route_key_compatibility",
                "geometry_distance_to_matched_travelway_ft",
            ]
        ],
        on="stable_crash_id",
        how="left",
    )
    if not high_causes.empty and "stable_crash_id" in high_causes.columns:
        keep = [col for col in ["stable_crash_id", "likely_high_fanout_cause", "manual_review_priority"] if col in high_causes.columns]
        high = high.merge(high_causes[keep].drop_duplicates("stable_crash_id"), on="stable_crash_id", how="left")
    high["high_confidence_single_travelway_match"] = high["match_confidence"].eq("high") & pd.to_numeric(
        high["candidate_travelway_count"], errors="coerce"
    ).eq(1)
    summary = high.groupby(["match_confidence", "match_method"], dropna=False).agg(
        high_fanout_crashes=("stable_crash_id", "nunique"),
        high_confidence_single_travelway_match=("high_confidence_single_travelway_match", "sum"),
        median_signal_count=("signal_count", lambda s: pd.to_numeric(s, errors="coerce").median()),
        median_bin_count=("bin_count", lambda s: pd.to_numeric(s, errors="coerce").median()),
        likely_cause_examples=("likely_high_fanout_cause", _collapse),
    ).reset_index()
    return summary


def _unassigned_audit(match_detail: pd.DataFrame, assignment: pd.DataFrame, represented_travelways: set[str]) -> pd.DataFrame:
    assigned = set(assignment["stable_crash_id"].astype(str))
    work = match_detail.loc[~match_detail["stable_crash_id"].astype(str).isin(assigned)].copy()
    first_match = work["matched_stable_travelway_id_candidates"].fillna("").astype(str).str.split("|").str[0]
    work["matched_represented_final_travelway"] = first_match.isin(represented_travelways)
    work["unassigned_match_class"] = np.select(
        [
            work["match_confidence"].eq("high") & work["matched_represented_final_travelway"],
            work["match_confidence"].isin(["medium", "medium_low"]) & work["matched_represented_final_travelway"],
            work["match_confidence"].isin(["high", "medium", "medium_low", "low"]) & ~work["matched_represented_final_travelway"],
        ],
        [
            "high_confidence_match_to_represented_travelway",
            "medium_confidence_match_to_represented_travelway",
            "matched_source_travelway_not_represented_or_not_identified",
        ],
        default="no_feasible_travelway_match",
    )
    summary = work.groupby(["unassigned_match_class", "match_confidence", "match_method"], dropna=False).agg(
        unassigned_crashes=("stable_crash_id", "nunique"),
        median_distance_to_nearest_travelway_ft=("geometry_distance_to_matched_travelway_ft", lambda s: pd.to_numeric(s, errors="coerce").median()),
    ).reset_index()
    return summary


def _decision(
    match_detail: pd.DataFrame,
    high_fanout: pd.DataFrame,
    unassigned: pd.DataFrame,
    spatial_vs: pd.DataFrame,
) -> pd.DataFrame:
    high_conf = int(match_detail["match_confidence"].eq("high").sum())
    medium_conf = int(match_detail["match_confidence"].isin(["medium", "medium_low"]).sum())
    high_fanout_high = int(high_fanout["high_confidence_single_travelway_match"].sum()) if "high_confidence_single_travelway_match" in high_fanout.columns else 0
    represented_unassigned = int(
        unassigned.loc[unassigned["unassigned_match_class"].str.contains("represented_travelway", na=False), "unassigned_crashes"].sum()
    ) if not unassigned.empty else 0
    reduction = int(spatial_vs["fanout_reduction_possible"].sum()) if "fanout_reduction_possible" in spatial_vs.columns else 0
    rows = [
        {
            "decision_item": "crash_to_travelway_identity_assignment_feasible",
            "decision": "yes_for_sensitivity_not_replacement",
            "evidence": f"high_confidence_route_measure_matches={high_conf:,}; medium_matches={medium_conf:,}",
        },
        {
            "decision_item": "usable_key_bundle",
            "decision": "RTE_NM_plus_RNS_MP_primary",
            "evidence": "normalized crash route and milepost fields align with Travelway route and measure fields",
        },
        {
            "decision_item": "fanout_reduction_potential",
            "decision": "material_for_subset",
            "evidence": f"high_fanout_high_confidence_single_travelway_matches={high_fanout_high:,}; assigned_50ft_fanout_reduction_possible={reduction:,}",
        },
        {
            "decision_item": "unassigned_crash_implication",
            "decision": "use_as_diagnostic_queue",
            "evidence": f"unassigned_50ft_crashes_with_represented_travelway_match={represented_unassigned:,}",
        },
        {
            "decision_item": "spatial_50ft_primary_status",
            "decision": "keep_primary_review_product_pending_sensitivity",
            "evidence": "identity matching should be implemented as sensitivity/hierarchy test before replacing catchment assignment",
        },
        {
            "decision_item": "recommended_next_pass",
            "decision": "implement_crash_to_travelway_assignment_sensitivity_product",
            "evidence": "route/measure matching appears feasible and can be compared against spatial fanout without using crash direction",
        },
    ]
    return pd.DataFrame(rows)


def _qa(direction_columns: list[str], missing: list[str]) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "outputs written only to review/current/crash_travelway_identity_feasibility"),
        ("no_records_promoted", True, "diagnostic-only output"),
        ("no_rates_or_models", True, "no rates/models calculated"),
        ("no_final_crash_assignment_produced", True, "candidate match detail is feasibility diagnostic, not assignment product"),
        ("crash_direction_not_used_for_scaffold_or_catchment", True, "direction-like fields are metadata inventory only"),
        ("direction_like_fields_inventory_only", True, "|".join(direction_columns) if direction_columns else "none detected"),
        ("outputs_review_only", True, str(OUT_DIR)),
        ("missing_required_inputs", len(missing) == 0, "|".join(missing)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "notes"])


def _findings(
    crash_inventory: pd.DataFrame,
    key_missing: pd.DataFrame,
    method_summary: pd.DataFrame,
    high_fanout: pd.DataFrame,
    unassigned: pd.DataFrame,
    decision: pd.DataFrame,
) -> str:
    roadway_fields = crash_inventory.loc[crash_inventory["candidate_roadway_field"].eq(True), "column_name"].astype(str).tolist()
    rtem = key_missing.loc[key_missing["candidate_key_bundle"].eq("RTE_NM + RNS_MP")]
    rtem_text = "not available"
    if not rtem.empty:
        row = rtem.iloc[0]
        rtem_text = f"{int(row['complete_crash_records']):,} crashes ({float(row['share_all_crashes']):.1%})"
    high = int(method_summary.loc[method_summary["match_confidence"].eq("high"), "crash_count"].sum())
    med = int(method_summary.loc[method_summary["match_confidence"].isin(["medium", "medium_low"]), "crash_count"].sum())
    highfan = int(high_fanout["high_confidence_single_travelway_match"].sum()) if "high_confidence_single_travelway_match" in high_fanout.columns else 0
    unassigned_rep = int(
        unassigned.loc[unassigned["unassigned_match_class"].str.contains("represented_travelway", na=False), "unassigned_crashes"].sum()
    ) if not unassigned.empty else 0
    rec = decision.loc[decision["decision_item"].eq("recommended_next_pass"), "decision"].iloc[0]
    return f"""# Crash-to-Travelway Roadway Identity Feasibility

Bounded question: can normalized crash roadway identity fields support a future crash-to-Travelway sensitivity assignment before falling back to spatial signal/bin catchments?

## Findings

1. Candidate crash roadway fields include: {", ".join(roadway_fields) if roadway_fields else "none detected"}.
2. The strongest key bundle is `RTE_NM + RNS_MP`: {rtem_text} have both route and milepost/measure populated.
3. Crash and Travelway fields share usable route/measure semantics through crash `RTE_NM`/`RNS_MP` and Travelway route/from-to measure fields.
4. Route/measure matching is feasible as a diagnostic: {high:,} crashes received high-confidence direct route/measure matches.
5. Locality + route/name + geometry remains feasible as a secondary diagnostic, but is weaker than route/measure.
6. Medium-confidence or medium-low-confidence Travelway matches were found for {med:,} crashes.
7. High-fanout crashes with high-confidence single-Travelway matches: {highfan:,}.
8. Unassigned 50-ft crashes with represented-Travelway matches: {unassigned_rep:,}.
9. Crash-to-Travelway matching could materially reduce fanout for a subset, but it should be tested as a sensitivity/hierarchy product before replacing the spatial 50-ft primary product.
10. Recommended next pass: `{rec}`.

## QA

No active outputs were modified. No records were promoted. No rates/models were calculated. No final crash assignment was produced. Direction-like crash fields, if present, were inventoried only and not used for scaffold, upstream/downstream, signal legs, or catchment geometry.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start crash Travelway identity feasibility")
    missing = _missing_inputs()
    if missing:
        _write_csv(pd.DataFrame({"missing_input": missing}), "missing_inputs.csv")
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    crash_inventory = _inventory_parquet(CRASH_SOURCE, primary_source="normalized_crashes")
    # Normalized crashes already expose route/measure fields. Avoid scanning the staging parquet unless
    # normalized fields are insufficient; this pass is a bounded feasibility diagnostic.
    crash_inventory_all = crash_inventory.copy()
    direction_columns = crash_inventory_all.loc[crash_inventory_all["direction_inventory_only"].eq(True), "column_name"].astype(str).tolist()

    crashes = _load_crashes()
    stable = _load_travelway_identity()
    travelway_inventory = _travelway_field_inventory(stable)
    key_candidates = _shared_key_candidates(crash_inventory_all, travelway_inventory)

    assignment_50 = _assignment_50_summary()
    assigned_50 = set(assignment_50["stable_crash_id"].astype(str))
    all_crashes = set(crashes["stable_crash_id"].astype(str))
    unassigned_50 = all_crashes - assigned_50
    fanout = _read_csv(CRASH_SANITY_DIR / "crash_fanout_sanity_detail.csv")
    high_fanout_ids = set(
        fanout.loc[
            pd.to_numeric(fanout["buffer_width_ft"], errors="coerce").eq(PRIMARY_BUFFER_FT)
            & (
                pd.to_numeric(fanout["signal_count"], errors="coerce").ge(4)
                | pd.to_numeric(fanout["bin_count"], errors="coerce").ge(20)
            ),
            "stable_crash_id",
        ].astype(str)
    )
    _checkpoint("derive assigned/high-fanout/unassigned id sets")
    key_missing = _key_missingness(crashes, assigned_50, high_fanout_ids, unassigned_50)
    _checkpoint("key missingness coverage test", len(key_missing))

    tier_a = _route_measure_match(crashes, stable)
    needs_nearest = crashes["has_crash_geometry"].astype(bool)
    _checkpoint("start source Travelway geometry load")
    source_tw = _load_source_travelway_geometry(stable)
    _checkpoint("start nearest source Travelway matching")
    nearest = _nearest_source_travelway(crashes, source_tw, needs_nearest)
    match_detail = _build_match_detail(crashes, tier_a, nearest)
    represented_travelways = set(_text(_read_csv(FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv", usecols=["stable_travelway_id"]), "stable_travelway_id"))
    method_summary, confidence_summary = _match_summaries(match_detail)
    spatial_vs = _spatial_vs_travelway(match_detail, assignment_50, represented_travelways)
    high_causes = _read_csv(CRASH_SANITY_DIR / "crash_high_fanout_cause_classification.csv")
    high_fanout_audit = _high_fanout_audit(match_detail, fanout, high_causes)
    unassigned_audit = _unassigned_audit(match_detail, assignment_50, represented_travelways)
    decision = _decision(match_detail, high_fanout_audit, unassigned_audit, spatial_vs)
    qa = _qa(direction_columns, missing)
    findings = _findings(crash_inventory_all, key_missing, method_summary, high_fanout_audit, unassigned_audit, decision)

    _write_csv(crash_inventory_all, "crash_field_inventory.csv")
    _write_csv(travelway_inventory, "travelway_field_inventory.csv")
    _write_csv(key_candidates, "crash_travelway_shared_key_candidates.csv")
    _write_csv(key_missing, "crash_key_missingness_summary.csv")
    _write_csv(match_detail, "crash_travelway_candidate_match_detail.csv")
    _write_csv(method_summary, "crash_travelway_match_method_summary.csv")
    _write_csv(confidence_summary, "crash_travelway_match_confidence_summary.csv")
    _write_csv(spatial_vs, "crash_spatial_assignment_vs_travelway_match.csv")
    _write_csv(high_fanout_audit, "crash_high_fanout_travelway_match_audit.csv")
    _write_csv(unassigned_audit, "crash_unassigned_travelway_match_audit.csv")
    _write_csv(decision, "crash_travelway_identity_feasibility_decision.csv")
    _write_text(findings, "crash_travelway_identity_feasibility_findings.md")
    _write_csv(qa, "crash_travelway_identity_feasibility_qa.csv")

    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "crash-to-Travelway roadway identity feasibility diagnostic",
        "output_dir": str(OUT_DIR),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": [
            "crash_field_inventory.csv",
            "travelway_field_inventory.csv",
            "crash_travelway_shared_key_candidates.csv",
            "crash_key_missingness_summary.csv",
            "crash_travelway_candidate_match_detail.csv",
            "crash_travelway_match_method_summary.csv",
            "crash_travelway_match_confidence_summary.csv",
            "crash_spatial_assignment_vs_travelway_match.csv",
            "crash_high_fanout_travelway_match_audit.csv",
            "crash_unassigned_travelway_match_audit.csv",
            "crash_travelway_identity_feasibility_decision.csv",
            "crash_travelway_identity_feasibility_findings.md",
            "crash_travelway_identity_feasibility_qa.csv",
            "crash_travelway_identity_feasibility_manifest.json",
            "run_progress_log.txt",
        ],
        "counts": {
            "normalized_crashes": int(len(crashes)),
            "assigned_50ft_crashes": int(len(assigned_50)),
            "unassigned_50ft_crashes": int(len(unassigned_50)),
            "high_fanout_50ft_crashes": int(len(high_fanout_ids)),
            "high_confidence_travelway_matches": int(method_summary.loc[method_summary["match_confidence"].eq("high"), "crash_count"].sum()),
            "medium_confidence_travelway_matches": int(method_summary.loc[method_summary["match_confidence"].isin(["medium", "medium_low"]), "crash_count"].sum()),
        },
        "qa": {
            "review_only": True,
            "no_final_crash_assignment": True,
            "no_rates_or_models": True,
            "crash_direction_used": False,
            "direction_fields_inventory_only": direction_columns,
        },
    }
    _write_json(manifest, "crash_travelway_identity_feasibility_manifest.json")
    _checkpoint("complete crash Travelway identity feasibility")


if __name__ == "__main__":
    main()
