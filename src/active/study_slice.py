from __future__ import annotations

import json
import sys
import hashlib
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid as shapely_make_valid
from shapely.geometry import Point
from shapely.strtree import STRtree

from .config import RuntimeConfig, load_runtime_config


STUDY_SLICE_DIRNAME = "stage1b_study_slice"
QC_SUMMARY_NAME = "stage1b_study_slice_qc.json"
NEAREST_ROAD_QC_SUMMARY_NAME = "stage1b_signal_nearest_road_qc.json"
SPEED_CONTEXT_QC_SUMMARY_NAME = "stage1b_signal_speed_context_qc.json"
FUNCTIONAL_DISTANCE_QC_SUMMARY_NAME = "stage1b_signal_functional_distance_qc.json"
BUFFER_QC_SUMMARY_NAME = "stage1b_signal_buffer_qc.json"
DONUT_QC_SUMMARY_NAME = "stage1b_signal_donut_qc.json"
MULTIZONE_QC_SUMMARY_NAME = "stage1b_signal_multizone_qc.json"
ROAD_INTERSECTION_QC_SUMMARY_NAME = "stage1b_road_zone_intersection_qc.json"
ROAD_CLEANUP_QC_SUMMARY_NAME = "stage1b_road_zone_cleanup_qc.json"
ROAD_OWNERSHIP_QC_SUMMARY_NAME = "stage1b_road_claim_ownership_qc.json"
SEGMENT_RAW_QC_SUMMARY_NAME = "stage1b_segmented_road_pieces_qc.json"
SEGMENT_SUPPORT_QC_SUMMARY_NAME = "stage1b_segment_support_qc.json"
SEGMENT_IDENTITY_QC_SUPPORT_QC_SUMMARY_NAME = "stage1b_segment_identity_qc_support_qc.json"
SEGMENT_CANONICAL_ROAD_IDENTITY_QC_SUMMARY_NAME = "stage1b_segment_canonical_road_identity_qc.json"
SEGMENT_LINK_IDENTITY_SUPPORT_QC_SUMMARY_NAME = "stage1b_segment_link_identity_support_qc.json"
SEGMENT_DIRECTIONALITY_SUPPORT_QC_SUMMARY_NAME = "stage1b_segment_directionality_support_qc.json"
SEGMENT_ORACLE_DIRECTION_PREP_QC_SUMMARY_NAME = "stage1b_segment_oracle_direction_prep_qc.json"
OUTPUT_ROADS_NAME = "Study_Roads_Divided.parquet"
OUTPUT_SIGNALS_NAME = "Study_Signals.parquet"
OUTPUT_SIGNALS_NEAREST_ROAD_NAME = "Study_Signals_NearestRoad.parquet"
OUTPUT_SIGNALS_SPEED_CONTEXT_NAME = "Study_Signals_SpeedContext.parquet"
OUTPUT_SIGNALS_FUNCTIONAL_DISTANCE_NAME = "Study_Signals_FunctionalDistance.parquet"
OUTPUT_SIGNALS_ZONE1_BUFFER_NAME = "Study_Signals_Zone1CriticalBuffer.parquet"
OUTPUT_SIGNALS_ZONE2_FULL_BUFFER_NAME = "Study_Signals_Zone2DesiredFullBuffer.parquet"
OUTPUT_SIGNALS_ZONE2_DONUT_NAME = "Study_Signals_Zone2FunctionalDonut.parquet"
OUTPUT_SIGNALS_MULTIZONE_NAME = "Study_Signals_StagedMultiZone.parquet"
OUTPUT_ROAD_ZONE_INTERSECTION_NAME = "Functional_Road_Segments_Raw.parquet"
OUTPUT_ROAD_ZONE_PRECLAIM_NAME = "Functional_Road_Segments_PreClaim.parquet"
OUTPUT_ROAD_ZONE_OWNED_NAME = "Zone_Road_Claims_Owned.parquet"
OUTPUT_SEGMENT_RAW_NAME = "Functional_Segments_Raw.parquet"
OUTPUT_SEGMENT_SUPPORT_NAME = "Functional_Segments_Raw_Support.parquet"
OUTPUT_SEGMENT_IDENTITY_QC_SUPPORT_NAME = "Functional_Segments_Raw_Support_IdentityQC.parquet"
OUTPUT_SEGMENT_CANONICAL_ROAD_IDENTITY_NAME = "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad.parquet"
OUTPUT_SEGMENT_LINK_IDENTITY_SUPPORT_NAME = "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit.parquet"
OUTPUT_SEGMENT_DIRECTIONALITY_SUPPORT_NAME = "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport.parquet"
OUTPUT_SEGMENT_ORACLE_DIRECTION_PREP_NAME = "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep.parquet"
DIVIDED_SIGNAL_TOLERANCE_FEET = 20.0
FEET_TO_METERS = 0.3048
TIE_DISTANCE_TOLERANCE_METERS = 0.001
SIGNAL_SPEED_SEARCH_FEET = 150.0
DEFAULT_ASSIGNED_SPEED = 35
MIN_SEGMENT_FT = 50.0
ORACLE_EXPORT_DIRNAME = "oracle_exports"
ORACLE_BROAD_LOOKUP_FILENAME = "cotedop_oracle_broad_lookup.csv"
ORACLE_GIS_KEYS_FILENAME = "cotedop_gis_keys.csv"
LEGACY_COMPARISON_GDBS = (
    "CrashIntersectionAnalysis.gdb",
    "IntersectionCrashAnalysis.gdb",
    "thirdstep_work.gdb",
)
FUNCTIONAL_DISTANCE_TABLE = {
    25: (155, 355),
    30: (200, 450),
    35: (250, 550),
    40: (305, 680),
    45: (360, 810),
    50: (425, 950),
    55: (495, 1100),
}


def _canonical_crs_label(crs_obj) -> str | None:
    if crs_obj is None:
        return None
    try:
        epsg = crs_obj.to_epsg()
    except Exception:
        epsg = None
    if epsg:
        return f"EPSG:{epsg}"
    return str(crs_obj)


def _leading_code(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    return text.str.extract(r"^(\d+)")[0].fillna("")


def _key_field_summary(gdf: gpd.GeoDataFrame, fields: list[str]) -> dict[str, dict[str, int | bool]]:
    summary: dict[str, dict[str, int | bool]] = {}
    for field in fields:
        if field not in gdf.columns:
            summary[field] = {
                "present": False,
                "non_null_count": 0,
                "non_blank_count": 0,
                "unique_non_blank_count": 0,
            }
            continue
        values = gdf[field]
        non_blank = values.dropna().astype(str).str.strip()
        non_blank = non_blank.loc[non_blank != ""]
        summary[field] = {
            "present": True,
            "non_null_count": int(values.notna().sum()),
            "non_blank_count": int(len(non_blank)),
            "unique_non_blank_count": int(non_blank.nunique(dropna=True)),
        }
    return summary


def _dataset_summary(gdf: gpd.GeoDataFrame, *, key_fields: list[str]) -> dict[str, object]:
    summary: dict[str, object] = {
        "row_count": int(len(gdf)),
        "crs": _canonical_crs_label(gdf.crs),
        "geometry_types": sorted({str(v) for v in gdf.geometry.geom_type.dropna().unique().tolist()}),
        "null_geometry_count": int(gdf.geometry.isna().sum()),
        "columns": list(gdf.columns),
        "key_fields": _key_field_summary(gdf, key_fields),
    }
    if len(gdf) and summary["null_geometry_count"] < len(gdf):
        summary["total_bounds"] = [float(v) for v in gdf.loc[gdf.geometry.notna()].total_bounds.tolist()]
    else:
        summary["total_bounds"] = None

    if not gdf.empty and gdf.geom_type.isin(["LineString", "MultiLineString"]).any():
        length_m = float(gdf.length.sum())
        summary["total_length_m"] = length_m
        summary["total_length_ft"] = length_m / FEET_TO_METERS

    if "Stage1_SourceGDB" in gdf.columns:
        counts = (
            gdf["Stage1_SourceGDB"]
            .fillna("<null>")
            .astype(str)
            .value_counts(dropna=False)
            .sort_index()
            .to_dict()
        )
        summary["source_gdb_counts"] = {str(k): int(v) for k, v in counts.items()}

    return summary


def _load_normalized_input(config: RuntimeConfig, layer_key: str) -> gpd.GeoDataFrame:
    path = config.normalized_dir / f"{layer_key}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing normalized Stage 1A input: {path}")
    gdf = gpd.read_parquet(path)
    if gdf.crs is None:
        raise ValueError(f"Normalized Stage 1A input '{layer_key}' has no CRS.")
    if _canonical_crs_label(gdf.crs) != config.working_crs:
        gdf = gdf.to_crs(config.working_crs)
    return gdf


def filter_divided_roads(roads_gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    facility_code = _leading_code(roads_gdf.get("RIM_FACILI", pd.Series(index=roads_gdf.index, dtype="object")))
    median_code = _leading_code(roads_gdf.get("RIM_MEDIAN", pd.Series(index=roads_gdf.index, dtype="object")))

    divided_mask = facility_code.isin({"2", "4"})
    non_undivided_median_mask = median_code != "1"
    study_mask = divided_mask & non_undivided_median_mask

    study_roads = roads_gdf.loc[study_mask].copy()
    filter_summary = {
        "input_row_count": int(len(roads_gdf)),
        "output_row_count": int(len(study_roads)),
        "dropped_row_count": int((~study_mask).sum()),
        "divided_facility_code_counts": {
            str(k): int(v)
            for k, v in facility_code.loc[study_mask].value_counts(dropna=False).sort_index().to_dict().items()
        },
        "median_code_counts": {
            str(k): int(v)
            for k, v in median_code.loc[study_mask].value_counts(dropna=False).sort_index().to_dict().items()
        },
        "criteria": {
            "included_facility_codes": ["2", "4"],
            "excluded_median_code": "1",
            "legacy_reference": "(RIM_FACILI LIKE '%2%' OR RIM_FACILI LIKE '%4%') AND RIM_MEDIAN NOT LIKE '1-%'",
        },
    }
    return study_roads, filter_summary


def filter_signals_to_study_roads(
    signals_gdf: gpd.GeoDataFrame,
    study_roads_gdf: gpd.GeoDataFrame,
    *,
    tolerance_feet: float,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    tolerance_meters = tolerance_feet * FEET_TO_METERS
    buffered_roads = study_roads_gdf[["geometry"]].copy()
    buffered_roads["geometry"] = buffered_roads.geometry.buffer(tolerance_meters)

    joined = gpd.sjoin(
        signals_gdf[["geometry"]].copy(),
        buffered_roads,
        how="inner",
        predicate="intersects",
    )
    matched_index = pd.Index(joined.index.unique())
    matched_mask = signals_gdf.index.isin(matched_index)
    study_signals = signals_gdf.loc[matched_mask].copy()

    filter_summary = {
        "input_row_count": int(len(signals_gdf)),
        "output_row_count": int(len(study_signals)),
        "dropped_row_count": int((~matched_mask).sum()),
        "search_distance_feet": tolerance_feet,
        "search_distance_meters": tolerance_meters,
        "raw_join_match_count": int(len(joined)),
        "matched_signal_count": int(matched_mask.sum()),
        "unmatched_signal_count": int((~matched_mask).sum()),
    }
    return study_signals, filter_summary


def _legacy_comparison_status(config: RuntimeConfig) -> dict[str, object]:
    searched = [str(config.repo_root / name) for name in LEGACY_COMPARISON_GDBS]
    available = [path for path in searched if Path(path).exists()]
    return {
        "searched_locations": searched,
        "available_locations": available,
        "status": "unavailable" if not available else "available_but_not_used",
        "notes": (
            "No repo-local legacy ArcPy working geodatabase was available for direct Study_Roads_Divided/Study_Signals comparison."
            if not available
            else "Legacy geodatabase candidates exist, but this bounded slice does not yet wire direct layer-level ArcPy output comparison."
        ),
    }


def _load_stage1b_output(path: Path, *, label: str) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required Stage 1B study-slice output for {label}: {path}")
    gdf = gpd.read_parquet(path)
    if gdf.crs is None:
        raise ValueError(f"Stage 1B study-slice output '{label}' has no CRS: {path}")
    return gdf


def _distance_distribution(distance_ft: pd.Series) -> dict[str, object]:
    if distance_ft.empty:
        return {
            "count": 0,
            "min_ft": None,
            "max_ft": None,
            "mean_ft": None,
            "median_ft": None,
            "p90_ft": None,
            "p95_ft": None,
            "p99_ft": None,
            "bin_counts_ft": {},
        }
    quantiles = distance_ft.quantile([0.5, 0.9, 0.95, 0.99])
    bin_edges = [-0.001, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, float("inf")]
    bucketed = pd.cut(distance_ft, bins=bin_edges, include_lowest=True, right=True)
    bin_counts: dict[str, int] = {}
    for interval, count in bucketed.value_counts(sort=False, dropna=False).items():
        left = max(0.0, interval.left)
        right = "inf" if np.isposinf(interval.right) else f"{interval.right:g}"
        label = f"[{left:g}, {right}]"
        bin_counts[label] = int(count)

    return {
        "count": int(distance_ft.count()),
        "min_ft": float(distance_ft.min()),
        "max_ft": float(distance_ft.max()),
        "mean_ft": float(distance_ft.mean()),
        "median_ft": float(quantiles.loc[0.5]),
        "p90_ft": float(quantiles.loc[0.9]),
        "p95_ft": float(quantiles.loc[0.95]),
        "p99_ft": float(quantiles.loc[0.99]),
        "bin_counts_ft": bin_counts,
    }


def _numeric_distribution(series: pd.Series) -> dict[str, object]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }
    quantiles = clean.quantile([0.5, 0.9, 0.95, 0.99])
    return {
        "count": int(clean.count()),
        "min": float(clean.min()),
        "max": float(clean.max()),
        "mean": float(clean.mean()),
        "median": float(quantiles.loc[0.5]),
        "p90": float(quantiles.loc[0.9]),
        "p95": float(quantiles.loc[0.95]),
        "p99": float(quantiles.loc[0.99]),
    }


def _value_counts_numeric(series: pd.Series) -> dict[str, int]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    counts = clean.value_counts().sort_index()
    output: dict[str, int] = {}
    for value, count in counts.items():
        label = str(int(value)) if float(value).is_integer() else str(float(value))
        output[label] = int(count)
    return output


def _choose_assigned_speed(raw_speed) -> tuple[int, str]:
    try:
        speed = float(raw_speed)
        if np.isnan(speed):
            return DEFAULT_ASSIGNED_SPEED, "default_35_missing_raw_speed"
        if speed < 15:
            return DEFAULT_ASSIGNED_SPEED, "default_35_raw_speed_below_15"
        return int(speed), "assigned_from_car_speed_limit"
    except Exception:
        return DEFAULT_ASSIGNED_SPEED, "default_35_missing_raw_speed"


def _functional_distance_pair(assigned_speed) -> tuple[int, int, int, str]:
    try:
        speed = int(round(float(assigned_speed)))
    except Exception:
        speed = int(DEFAULT_ASSIGNED_SPEED)
    rounded_bin = int(5 * round(float(speed) / 5))
    if rounded_bin in FUNCTIONAL_DISTANCE_TABLE:
        dist_lim, dist_des = FUNCTIONAL_DISTANCE_TABLE[rounded_bin]
        mapping_rule = "direct_lookup"
    else:
        dist_lim, dist_des = FUNCTIONAL_DISTANCE_TABLE[DEFAULT_ASSIGNED_SPEED]
        mapping_rule = "fallback_to_35_bin"
    return int(rounded_bin), int(dist_lim), int(dist_des), mapping_rule


def enrich_signals_with_nearest_road(
    signals_gdf: gpd.GeoDataFrame,
    roads_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    road_fields = [
        "RTE_NM",
        "RTE_ID",
        "EVENT_SOUR",
        "RTE_COMMON",
        "FROM_MEASURE",
        "TO_MEASURE",
        "RIM_FACILI",
        "RIM_MEDIAN",
        "Stage1_SourceGDB",
        "Stage1_SourceLayer",
    ]

    roads = roads_gdf.reset_index(drop=True).copy()
    signals = signals_gdf.reset_index(drop=True).copy()
    roads["NearestRoad_RowID"] = roads.index.astype("int64")
    signals["Signal_RowID"] = signals.index.astype("int64")

    tree = STRtree(roads.geometry.values)
    pair_indices, pair_distances_m = tree.query_nearest(
        signals.geometry.values,
        all_matches=True,
        return_distance=True,
    )
    signal_idx = pair_indices[0]
    road_idx = pair_indices[1]

    candidates = pd.DataFrame(
        {
            "Signal_RowID": signal_idx.astype("int64"),
            "NearestRoad_RowID": road_idx.astype("int64"),
            "NearestRoad_Distance_M": pair_distances_m.astype("float64"),
        }
    )
    candidates["NearestRoad_Distance_FT"] = candidates["NearestRoad_Distance_M"] / FEET_TO_METERS

    candidate_roads = roads[["NearestRoad_RowID", *road_fields]].copy()
    candidates = candidates.merge(candidate_roads, on="NearestRoad_RowID", how="left")

    tie_counts = candidates.groupby("Signal_RowID").size().rename("NearestRoad_TieCount")
    min_dist_m = candidates.groupby("Signal_RowID")["NearestRoad_Distance_M"].min().rename("NearestRoad_MinDistance_M")
    candidates = candidates.merge(tie_counts, on="Signal_RowID", how="left")
    candidates = candidates.merge(min_dist_m, on="Signal_RowID", how="left")
    candidates["NearestRoad_IsTied"] = candidates["NearestRoad_TieCount"] > 1
    candidates["NearestRoad_IsMinDistance"] = (
        (candidates["NearestRoad_Distance_M"] - candidates["NearestRoad_MinDistance_M"]).abs()
        <= TIE_DISTANCE_TOLERANCE_METERS
    )

    sort_fields = [
        "Signal_RowID",
        "NearestRoad_Distance_M",
        "RTE_ID",
        "RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "EVENT_SOUR",
        "NearestRoad_RowID",
    ]
    for field in ("RTE_ID", "RTE_NM", "EVENT_SOUR"):
        candidates[field] = candidates[field].fillna("").astype(str)
    for field in ("FROM_MEASURE", "TO_MEASURE"):
        candidates[field] = pd.to_numeric(candidates[field], errors="coerce")

    chosen = candidates.sort_values(sort_fields, kind="stable").drop_duplicates("Signal_RowID", keep="first").copy()
    chosen["NearestRoad_TieBreakRule"] = np.where(
        chosen["NearestRoad_TieCount"] > 1,
        "sorted by distance, RTE_ID, RTE_NM, FROM_MEASURE, TO_MEASURE, EVENT_SOUR, NearestRoad_RowID",
        "single nearest road",
    )

    rename_map = {
        "RTE_NM": "NearestRoad_RTE_NM",
        "RTE_ID": "NearestRoad_RTE_ID",
        "EVENT_SOUR": "NearestRoad_EVENT_SOUR",
        "RTE_COMMON": "NearestRoad_RTE_COMMON",
        "FROM_MEASURE": "NearestRoad_FROM_MEASURE",
        "TO_MEASURE": "NearestRoad_TO_MEASURE",
        "RIM_FACILI": "NearestRoad_RIM_FACILI",
        "RIM_MEDIAN": "NearestRoad_RIM_MEDIAN",
        "Stage1_SourceGDB": "NearestRoad_SourceGDB",
        "Stage1_SourceLayer": "NearestRoad_SourceLayer",
    }
    chosen = chosen.rename(columns=rename_map)
    chosen["NearestRoad_IsAmbiguous"] = chosen["NearestRoad_TieCount"] > 1

    output_fields = [
        "Signal_RowID",
        "NearestRoad_RowID",
        "NearestRoad_Distance_M",
        "NearestRoad_Distance_FT",
        "NearestRoad_TieCount",
        "NearestRoad_IsTied",
        "NearestRoad_IsAmbiguous",
        "NearestRoad_TieBreakRule",
        "NearestRoad_RTE_NM",
        "NearestRoad_RTE_ID",
        "NearestRoad_EVENT_SOUR",
        "NearestRoad_RTE_COMMON",
        "NearestRoad_FROM_MEASURE",
        "NearestRoad_TO_MEASURE",
        "NearestRoad_RIM_FACILI",
        "NearestRoad_RIM_MEDIAN",
        "NearestRoad_SourceGDB",
        "NearestRoad_SourceLayer",
    ]
    enriched = signals.merge(chosen[output_fields], on="Signal_RowID", how="left")

    unmatched_count = int(enriched["NearestRoad_RowID"].isna().sum())
    ambiguous_cases = chosen.loc[chosen["NearestRoad_TieCount"] > 1].copy()
    ambiguous_sample = []
    if not ambiguous_cases.empty:
        sample_ids = ambiguous_cases["Signal_RowID"].sort_values().head(10).tolist()
        sample_candidates = candidates.loc[candidates["Signal_RowID"].isin(sample_ids)].copy()
        sample_candidates = sample_candidates.sort_values(
            ["Signal_RowID", "NearestRoad_Distance_M", "RTE_ID", "RTE_NM", "NearestRoad_RowID"],
            kind="stable",
        )
        for signal_row_id, group in sample_candidates.groupby("Signal_RowID", sort=True):
            signal_row = enriched.loc[enriched["Signal_RowID"] == signal_row_id].iloc[0]
            signal_identifier = (
                signal_row.get("REG_SIGNAL_ID")
                or signal_row.get("SIGNAL_NO")
                or signal_row.get("INTNO")
                or signal_row.get("INTNUM")
                or signal_row_id
            )
            ambiguous_sample.append(
                {
                    "Signal_RowID": int(signal_row_id),
                    "SignalIdentifier": str(signal_identifier),
                    "TieCount": int(group["NearestRoad_TieCount"].iloc[0]),
                    "Distance_FT": float(group["NearestRoad_Distance_FT"].iloc[0]),
                    "CandidateRoads": [
                        {
                            "NearestRoad_RowID": int(row.NearestRoad_RowID),
                            "RTE_ID": row.RTE_ID,
                            "RTE_NM": row.RTE_NM,
                            "EVENT_SOUR": row.EVENT_SOUR,
                            "FROM_MEASURE": None if pd.isna(row.FROM_MEASURE) else float(row.FROM_MEASURE),
                            "TO_MEASURE": None if pd.isna(row.TO_MEASURE) else float(row.TO_MEASURE),
                        }
                        for row in group.itertuples(index=False)
                    ],
                }
            )

    chosen_dist_ft = chosen["NearestRoad_Distance_FT"]
    qc = {
        "input_signal_count": int(len(signals)),
        "input_road_count": int(len(roads)),
        "output_signal_count": int(len(enriched)),
        "unmatched_signal_count": unmatched_count,
        "matched_signal_count": int(len(enriched) - unmatched_count),
        "tied_signal_count": int((chosen["NearestRoad_TieCount"] > 1).sum()),
        "ambiguous_signal_count": int((chosen["NearestRoad_IsAmbiguous"]).sum()),
        "max_tie_count": int(chosen["NearestRoad_TieCount"].max()) if not chosen.empty else 0,
        "distance_distribution_ft": _distance_distribution(chosen_dist_ft),
        "distance_within_study_filter_count": int((chosen_dist_ft <= DIVIDED_SIGNAL_TOLERANCE_FEET).sum()),
        "distance_exceeds_study_filter_count": int((chosen_dist_ft > DIVIDED_SIGNAL_TOLERANCE_FEET).sum()),
        "tie_distance_tolerance_meters": TIE_DISTANCE_TOLERANCE_METERS,
        "tie_break_rule": "sorted by distance, RTE_ID, RTE_NM, FROM_MEASURE, TO_MEASURE, EVENT_SOUR, NearestRoad_RowID",
        "ambiguous_signal_samples": ambiguous_sample,
    }
    return enriched, qc


def enrich_signals_with_speed_context(
    signals_gdf: gpd.GeoDataFrame,
    speed_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    search_radius_m = SIGNAL_SPEED_SEARCH_FEET * FEET_TO_METERS

    signals = signals_gdf.copy()
    speed = speed_gdf.reset_index(drop=True).copy()
    if "Signal_RowID" not in signals.columns:
        signals = signals.reset_index(drop=True)
        signals["Signal_RowID"] = signals.index.astype("int64")
    else:
        signals["Signal_RowID"] = pd.to_numeric(signals["Signal_RowID"], errors="raise").astype("int64")

    speed["SpeedContext_RowID"] = speed.index.astype("int64")

    signal_helper_fields = [
        "Signal_RowID",
        "NearestRoad_RTE_COMMON",
        "REG_SIGNAL_ID",
        "SIGNAL_NO",
        "INTNO",
        "INTNUM",
    ]
    speed_fields = [
        "SpeedContext_RowID",
        "EVENT_SOURCE_ID",
        "CAR_SPEED_LIMIT",
        "TRUCK_SPEED_LIMIT",
        "ROUTE_COMMON_NAME",
        "LOC_COMP_DIRECTIONALITY_NAME",
        "ROUTE_FROM_MEASURE",
        "ROUTE_TO_MEASURE",
        "Stage1_SourceGDB",
        "Stage1_SourceLayer",
    ]

    pair_indices, pair_distances_m = STRtree(speed.geometry.values).query_nearest(
        signals.geometry.values,
        max_distance=search_radius_m,
        all_matches=True,
        return_distance=True,
    )
    signal_idx = pair_indices[0]
    speed_idx = pair_indices[1]

    candidates = pd.DataFrame(
        {
            "Signal_RowID": signals.iloc[signal_idx]["Signal_RowID"].to_numpy(dtype="int64"),
            "SpeedContext_RowID": speed.iloc[speed_idx]["SpeedContext_RowID"].to_numpy(dtype="int64"),
            "SpeedContext_Distance_M": pair_distances_m.astype("float64"),
        }
    )
    candidates["SpeedContext_Distance_FT"] = candidates["SpeedContext_Distance_M"] / FEET_TO_METERS
    candidates = candidates.merge(signals[signal_helper_fields], on="Signal_RowID", how="left")
    candidates = candidates.merge(speed[speed_fields], on="SpeedContext_RowID", how="left")
    candidates["NearestRoad_RTE_COMMON"] = candidates["NearestRoad_RTE_COMMON"].fillna("").astype(str)
    candidates["ROUTE_COMMON_NAME"] = candidates["ROUTE_COMMON_NAME"].fillna("").astype(str)
    candidates["SpeedContext_RouteCommonMatch"] = (
        candidates["NearestRoad_RTE_COMMON"] == candidates["ROUTE_COMMON_NAME"]
    )

    candidate_count = candidates.groupby("Signal_RowID").size().rename("SpeedContext_CandidateCount")
    any_route_match = candidates.groupby("Signal_RowID")["SpeedContext_RouteCommonMatch"].any().rename("SpeedContext_AnyRouteCommonMatch")
    candidates = candidates.merge(candidate_count, on="Signal_RowID", how="left")
    candidates = candidates.merge(any_route_match, on="Signal_RowID", how="left")

    sort_fields = [
        "Signal_RowID",
        "SpeedContext_Distance_M",
        "SpeedContext_RouteCommonMatch",
        "ROUTE_COMMON_NAME",
        "EVENT_SOURCE_ID",
        "ROUTE_FROM_MEASURE",
        "ROUTE_TO_MEASURE",
        "SpeedContext_RowID",
    ]
    candidates["EVENT_SOURCE_ID"] = candidates["EVENT_SOURCE_ID"].fillna("").astype(str)
    for field in ("ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT"):
        candidates[field] = pd.to_numeric(candidates[field], errors="coerce")

    chosen = candidates.sort_values(
        sort_fields,
        ascending=[True, True, False, True, True, True, True, True],
        kind="stable",
    ).drop_duplicates("Signal_RowID", keep="first").copy()

    def _speed_method(row) -> str:
        if row["SpeedContext_CandidateCount"] > 1 and bool(row["SpeedContext_AnyRouteCommonMatch"]):
            return "closest_tie_prefer_route_common"
        if row["SpeedContext_CandidateCount"] > 1:
            return "closest_tie_no_route_common_match"
        if bool(row["SpeedContext_RouteCommonMatch"]):
            return "closest_within_150ft_route_common_match"
        return "closest_within_150ft_route_common_mismatch"

    chosen["SpeedContext_Method"] = chosen.apply(_speed_method, axis=1)
    chosen["SpeedContext_IsAmbiguous"] = chosen["SpeedContext_CandidateCount"] > 1
    chosen["SpeedContext_TieBreakRule"] = np.where(
        chosen["SpeedContext_CandidateCount"] > 1,
        "sorted by distance, route-common match, ROUTE_COMMON_NAME, EVENT_SOURCE_ID, ROUTE_FROM_MEASURE, ROUTE_TO_MEASURE, SpeedContext_RowID",
        "single nearest speed segment",
    )

    rename_map = {
        "EVENT_SOURCE_ID": "SpeedContext_EVENT_SOURCE_ID",
        "CAR_SPEED_LIMIT": "SpeedContext_CAR_SPEED_LIMIT",
        "TRUCK_SPEED_LIMIT": "SpeedContext_TRUCK_SPEED_LIMIT",
        "ROUTE_COMMON_NAME": "SpeedContext_ROUTE_COMMON_NAME",
        "LOC_COMP_DIRECTIONALITY_NAME": "SpeedContext_DIRECTIONALITY_NAME",
        "ROUTE_FROM_MEASURE": "SpeedContext_ROUTE_FROM_MEASURE",
        "ROUTE_TO_MEASURE": "SpeedContext_ROUTE_TO_MEASURE",
        "Stage1_SourceGDB": "SpeedContext_SourceGDB",
        "Stage1_SourceLayer": "SpeedContext_SourceLayer",
    }
    chosen = chosen.rename(columns=rename_map)

    output_fields = [
        "Signal_RowID",
        "SpeedContext_RowID",
        "SpeedContext_Distance_M",
        "SpeedContext_Distance_FT",
        "SpeedContext_CandidateCount",
        "SpeedContext_IsAmbiguous",
        "SpeedContext_TieBreakRule",
        "SpeedContext_Method",
        "SpeedContext_RouteCommonMatch",
        "SpeedContext_AnyRouteCommonMatch",
        "SpeedContext_EVENT_SOURCE_ID",
        "SpeedContext_CAR_SPEED_LIMIT",
        "SpeedContext_TRUCK_SPEED_LIMIT",
        "SpeedContext_ROUTE_COMMON_NAME",
        "SpeedContext_DIRECTIONALITY_NAME",
        "SpeedContext_ROUTE_FROM_MEASURE",
        "SpeedContext_ROUTE_TO_MEASURE",
        "SpeedContext_SourceGDB",
        "SpeedContext_SourceLayer",
    ]
    enriched = signals.merge(chosen[output_fields], on="Signal_RowID", how="left")
    enriched["SpeedContext_SearchRadius_FT"] = SIGNAL_SPEED_SEARCH_FEET

    assigned_pairs = [_choose_assigned_speed(v) for v in enriched["SpeedContext_CAR_SPEED_LIMIT"]]
    enriched["Assigned_Speed"] = pd.Series([item[0] for item in assigned_pairs], index=enriched.index, dtype="int64")
    enriched["Assigned_Speed_Rule"] = [item[1] for item in assigned_pairs]
    enriched["Assigned_Speed_Defaulted"] = enriched["Assigned_Speed_Rule"] != "assigned_from_car_speed_limit"
    enriched.loc[enriched["SpeedContext_RowID"].isna(), "SpeedContext_Method"] = "default_no_speed_within_150ft"
    enriched["SpeedContext_IsAmbiguous"] = enriched["SpeedContext_IsAmbiguous"].fillna(False).astype(bool)
    enriched["SpeedContext_CandidateCount"] = (
        enriched["SpeedContext_CandidateCount"].fillna(0).astype("int64")
    )
    enriched["SpeedContext_RouteCommonMatch"] = enriched["SpeedContext_RouteCommonMatch"].fillna(False).astype(bool)
    enriched["SpeedContext_AnyRouteCommonMatch"] = enriched["SpeedContext_AnyRouteCommonMatch"].fillna(False).astype(bool)

    unmatched = enriched.loc[enriched["SpeedContext_RowID"].isna()].copy()
    ambiguous = chosen.loc[chosen["SpeedContext_CandidateCount"] > 1].copy()

    ambiguous_sample = []
    if not ambiguous.empty:
        sample_ids = ambiguous["Signal_RowID"].sort_values().head(10).tolist()
        sample_candidates = candidates.loc[candidates["Signal_RowID"].isin(sample_ids)].copy()
        sample_candidates = sample_candidates.sort_values(
            [
                "Signal_RowID",
                "SpeedContext_Distance_M",
                "SpeedContext_RouteCommonMatch",
                "ROUTE_COMMON_NAME",
                "EVENT_SOURCE_ID",
                "SpeedContext_RowID",
            ],
            ascending=[True, True, False, True, True, True],
            kind="stable",
        )
        for signal_row_id, group in sample_candidates.groupby("Signal_RowID", sort=True):
            signal_row = enriched.loc[enriched["Signal_RowID"] == signal_row_id].iloc[0]
            signal_identifier = (
                signal_row.get("REG_SIGNAL_ID")
                or signal_row.get("SIGNAL_NO")
                or signal_row.get("INTNO")
                or signal_row.get("INTNUM")
                or signal_row_id
            )
            ambiguous_sample.append(
                {
                    "Signal_RowID": int(signal_row_id),
                    "SignalIdentifier": str(signal_identifier),
                    "CandidateCount": int(group["SpeedContext_CandidateCount"].iloc[0]),
                    "AnyRouteCommonMatch": bool(group["SpeedContext_AnyRouteCommonMatch"].iloc[0]),
                    "Distance_FT": float(group["SpeedContext_Distance_FT"].iloc[0]),
                    "Candidates": [
                        {
                            "SpeedContext_RowID": int(row.SpeedContext_RowID),
                            "EVENT_SOURCE_ID": row.EVENT_SOURCE_ID,
                            "ROUTE_COMMON_NAME": row.ROUTE_COMMON_NAME,
                            "CAR_SPEED_LIMIT": None if pd.isna(row.CAR_SPEED_LIMIT) else float(row.CAR_SPEED_LIMIT),
                            "TRUCK_SPEED_LIMIT": None if pd.isna(row.TRUCK_SPEED_LIMIT) else float(row.TRUCK_SPEED_LIMIT),
                            "RouteCommonMatch": bool(row.SpeedContext_RouteCommonMatch),
                            "ROUTE_FROM_MEASURE": None if pd.isna(row.ROUTE_FROM_MEASURE) else float(row.ROUTE_FROM_MEASURE),
                            "ROUTE_TO_MEASURE": None if pd.isna(row.ROUTE_TO_MEASURE) else float(row.ROUTE_TO_MEASURE),
                        }
                        for row in group.itertuples(index=False)
                    ],
                }
            )

    qc = {
        "input_signal_count": int(len(signals)),
        "output_signal_count": int(len(enriched)),
        "study_signal_universe_unchanged": int(len(signals)) == int(len(enriched)),
        "speed_search_radius_feet": SIGNAL_SPEED_SEARCH_FEET,
        "raw_speed_match_count": int(enriched["SpeedContext_RowID"].notna().sum()),
        "raw_speed_unmatched_count": int(enriched["SpeedContext_RowID"].isna().sum()),
        "assigned_speed_non_null_count": int(enriched["Assigned_Speed"].notna().sum()),
        "assigned_speed_null_count": int(enriched["Assigned_Speed"].isna().sum()),
        "assigned_speed_defaulted_count": int(enriched["Assigned_Speed_Defaulted"].sum()),
        "defaulted_due_to_no_speed_candidate_count": int((enriched["Assigned_Speed_Rule"] == "default_35_missing_raw_speed").sum()),
        "defaulted_due_to_low_speed_count": int((enriched["Assigned_Speed_Rule"] == "default_35_raw_speed_below_15").sum()),
        "ambiguous_signal_count": int((enriched["SpeedContext_IsAmbiguous"]).sum()),
        "exact_nearest_tied_signal_count": int((chosen["SpeedContext_CandidateCount"] > 1).sum()),
        "tied_with_route_common_match_count": int(((chosen["SpeedContext_CandidateCount"] > 1) & (chosen["SpeedContext_AnyRouteCommonMatch"])).sum()),
        "tied_without_route_common_match_count": int(((chosen["SpeedContext_CandidateCount"] > 1) & (~chosen["SpeedContext_AnyRouteCommonMatch"])).sum()),
        "max_speed_candidate_count": int(chosen["SpeedContext_CandidateCount"].max()) if not chosen.empty else 0,
        "route_common_match_assigned_count": int(enriched["SpeedContext_RouteCommonMatch"].sum()),
        "route_common_match_assigned_share_of_raw_matches": (
            float(enriched["SpeedContext_RouteCommonMatch"].sum()) / float(enriched["SpeedContext_RowID"].notna().sum())
            if int(enriched["SpeedContext_RowID"].notna().sum()) > 0 else None
        ),
        "speed_distance_distribution_ft": _distance_distribution(
            enriched.loc[enriched["SpeedContext_RowID"].notna(), "SpeedContext_Distance_FT"]
        ),
        "raw_car_speed_limit_distribution": {
            **_numeric_distribution(enriched["SpeedContext_CAR_SPEED_LIMIT"]),
            "value_counts": _value_counts_numeric(enriched["SpeedContext_CAR_SPEED_LIMIT"]),
        },
        "assigned_speed_distribution": {
            **_numeric_distribution(enriched["Assigned_Speed"]),
            "value_counts": _value_counts_numeric(enriched["Assigned_Speed"]),
        },
        "method_counts": {
            str(k): int(v)
            for k, v in enriched["SpeedContext_Method"].fillna("<null>").value_counts(dropna=False).sort_index().to_dict().items()
        },
        "ambiguous_signal_samples": ambiguous_sample,
        "unmatched_signal_samples": [
            {
                "Signal_RowID": int(row.Signal_RowID),
                "SignalIdentifier": str(
                    row.REG_SIGNAL_ID or row.SIGNAL_NO or row.INTNO or row.INTNUM or row.Signal_RowID
                ),
                "NearestRoad_RTE_COMMON": row.NearestRoad_RTE_COMMON,
                "NearestRoad_RTE_ID": row.NearestRoad_RTE_ID,
                "NearestRoad_Distance_FT": None if pd.isna(row.NearestRoad_Distance_FT) else float(row.NearestRoad_Distance_FT),
            }
            for row in unmatched.head(10).itertuples(index=False)
        ],
    }
    return enriched, qc


def derive_signal_functional_distances(
    signals_speed_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    enriched = signals_speed_gdf.copy()

    derived = [_functional_distance_pair(v) for v in enriched["Assigned_Speed"]]
    enriched["Dist_Lim"] = pd.Series([item[1] for item in derived], index=enriched.index, dtype="int64")
    enriched["Dist_Des"] = pd.Series([item[2] for item in derived], index=enriched.index, dtype="int64")

    assigned_speed_bin = pd.Series([item[0] for item in derived], index=enriched.index, dtype="int64")
    mapping_rule = pd.Series([item[3] for item in derived], index=enriched.index)

    beyond_20ft_mask = (
        enriched["SpeedContext_RowID"].notna()
        & pd.to_numeric(enriched["SpeedContext_Distance_FT"], errors="coerce").gt(DIVIDED_SIGNAL_TOLERANCE_FEET)
        & pd.to_numeric(enriched["SpeedContext_Distance_FT"], errors="coerce").le(SIGNAL_SPEED_SEARCH_FEET)
    )
    defaulted_mask = enriched["Assigned_Speed_Defaulted"].fillna(False).astype(bool)
    matched_mask = enriched["SpeedContext_RowID"].notna()

    observed_speeds = sorted(pd.to_numeric(enriched["Assigned_Speed"], errors="coerce").dropna().astype(int).unique().tolist())
    mapping_summary = []
    for speed in observed_speeds:
        speed_bin, dist_lim, dist_des, rule = _functional_distance_pair(speed)
        mapping_summary.append(
            {
                "Assigned_Speed": int(speed),
                "RoundedSpeedBin": int(speed_bin),
                "Dist_Lim": int(dist_lim),
                "Dist_Des": int(dist_des),
                "MappingRule": rule,
            }
        )

    qc = {
        "input_signal_count": int(len(signals_speed_gdf)),
        "output_signal_count": int(len(enriched)),
        "study_signal_universe_unchanged": int(len(signals_speed_gdf)) == int(len(enriched)),
        "assigned_speed_non_null_count": int(pd.to_numeric(enriched["Assigned_Speed"], errors="coerce").notna().sum()),
        "dist_lim_non_null_count": int(enriched["Dist_Lim"].notna().sum()),
        "dist_des_non_null_count": int(enriched["Dist_Des"].notna().sum()),
        "default_assigned_speed_row_count": int(defaulted_mask.sum()),
        "matched_speed_assignment_row_count": int(matched_mask.sum()),
        "defaulted_vs_matched_breakdown": {
            "default_assigned_speed_rows": int(defaulted_mask.sum()),
            "matched_speed_rows": int(matched_mask.sum()),
            "matched_nondefault_speed_rows": int((matched_mask & ~defaulted_mask).sum()),
            "unmatched_speed_rows": int((~matched_mask).sum()),
        },
        "functional_distance_rows_from_speed_matches_beyond_20ft_within_150ft": int(beyond_20ft_mask.sum()),
        "functional_distance_rows_from_speed_matches_beyond_20ft_within_150ft_defaulted": int((beyond_20ft_mask & defaulted_mask).sum()),
        "functional_distance_rows_from_speed_matches_beyond_20ft_within_150ft_nondefault": int((beyond_20ft_mask & ~defaulted_mask).sum()),
        "assigned_speed_distribution": {
            **_numeric_distribution(enriched["Assigned_Speed"]),
            "value_counts": _value_counts_numeric(enriched["Assigned_Speed"]),
        },
        "dist_lim_distribution": {
            **_numeric_distribution(enriched["Dist_Lim"]),
            "value_counts": _value_counts_numeric(enriched["Dist_Lim"]),
        },
        "dist_des_distribution": {
            **_numeric_distribution(enriched["Dist_Des"]),
            "value_counts": _value_counts_numeric(enriched["Dist_Des"]),
        },
        "functional_distance_mapping_table": mapping_summary,
        "mapping_rule_counts": {
            str(k): int(v)
            for k, v in mapping_rule.value_counts(dropna=False).sort_index().to_dict().items()
        },
        "rounded_speed_bin_counts": {
            str(k): int(v)
            for k, v in assigned_speed_bin.value_counts(dropna=False).sort_index().to_dict().items()
        },
    }
    return enriched, qc


def create_signal_centered_buffers(
    signals_gdf: gpd.GeoDataFrame,
    *,
    distance_field: str,
    zone_type: str,
    output_name: str,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    buffered = signals_gdf.copy()
    distance_ft = pd.to_numeric(buffered[distance_field], errors="coerce")
    if distance_ft.isna().any():
        raise ValueError(f"Cannot buffer '{output_name}': null values found in {distance_field}.")

    distance_m = distance_ft * FEET_TO_METERS
    buffered["Buffer_SourceDistanceField"] = distance_field
    buffered["Buffer_OutputName"] = output_name
    buffered["Buffer_ZoneType"] = zone_type
    buffered["Buffer_Distance_FT"] = distance_ft.astype("float64")
    buffered["Buffer_Distance_M"] = distance_m.astype("float64")
    buffered["Buffer_CenterBasis"] = "signal_point"
    buffered["Buffer_DistanceUnits_Input"] = "feet"
    buffered["Buffer_DistanceUnits_BufferCRS"] = "meters_in_epsg_3968"
    buffered["Buffer_DissolveStatus"] = "pre_dissolve_one_feature_per_signal"
    buffered["geometry"] = buffered.geometry.buffer(distance_m)

    summary = {
        "output_name": output_name,
        "source_signal_count": int(len(signals_gdf)),
        "feature_count": int(len(buffered)),
        "distance_field_used": distance_field,
        "zone_type": zone_type,
        "geometry_basis": "signal-centered point buffer",
        "distance_units": {
            "input_distance_field_units": "feet",
            "buffer_execution_units": "meters_in_epsg_3968",
        },
        "dissolve_status": "pre_dissolve_one_feature_per_signal",
        "overlap_status": "geometries may overlap; no dissolve applied",
        "distance_distribution_ft": {
            **_numeric_distribution(buffered["Buffer_Distance_FT"]),
            "value_counts": _value_counts_numeric(buffered["Buffer_Distance_FT"]),
        },
    }
    return buffered, summary


def create_signal_functional_donut(
    zone2_full_gdf: gpd.GeoDataFrame,
    zone1_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    if _canonical_crs_label(zone2_full_gdf.crs) != _canonical_crs_label(zone1_gdf.crs):
        raise ValueError("Zone1 and Zone2Full buffers must share the same CRS.")
    if "Signal_RowID" not in zone2_full_gdf.columns or "Signal_RowID" not in zone1_gdf.columns:
        raise ValueError("Both buffer inputs must contain Signal_RowID for one-feature-per-signal alignment.")

    zone2 = zone2_full_gdf.sort_values("Signal_RowID", kind="stable").copy()
    zone1 = zone1_gdf.sort_values("Signal_RowID", kind="stable").copy()
    if zone2["Signal_RowID"].tolist() != zone1["Signal_RowID"].tolist():
        raise ValueError("Zone1 and Zone2Full buffers do not align one-to-one by Signal_RowID.")

    donut = zone2.copy()
    donut["Donut_OuterSourceOutput"] = "Study_Signals_Zone2DesiredFullBuffer"
    donut["Donut_InnerSourceOutput"] = "Study_Signals_Zone1CriticalBuffer"
    donut["Donut_Operation"] = "zone2_full_minus_zone1_critical"
    donut["Donut_ZoneType"] = "Zone 2: Functional"
    donut["Donut_DissolveStatus"] = "pre_dissolve_one_feature_per_signal"
    donut["Donut_OverlapStatus"] = "geometries may overlap; no dissolve applied"
    donut["geometry"] = donut.geometry.difference(zone1.geometry)

    empty_count = int(donut.geometry.is_empty.sum())
    null_count = int(donut.geometry.isna().sum())
    summary = {
        "feature_count": int(len(donut)),
        "geometry_basis": "per-signal donut from zone2 desired full buffer minus zone1 critical buffer",
        "operation": "difference(zone2_full, zone1_critical)",
        "source_outer_output": "Study_Signals_Zone2DesiredFullBuffer",
        "source_inner_output": "Study_Signals_Zone1CriticalBuffer",
        "one_feature_per_signal": True,
        "dissolve_status": "pre_dissolve_one_feature_per_signal",
        "overlap_status": "geometries may overlap; no dissolve applied",
        "empty_geometry_count": empty_count,
        "null_geometry_count": null_count,
    }
    return donut, summary


def _buffer_unit_validation(gdf: gpd.GeoDataFrame) -> dict[str, object]:
    buffer_ft = pd.to_numeric(gdf["Buffer_Distance_FT"], errors="coerce")
    buffer_m = pd.to_numeric(gdf["Buffer_Distance_M"], errors="coerce")
    expected_m = buffer_ft * FEET_TO_METERS
    matches = np.isclose(buffer_m, expected_m, equal_nan=False)
    return {
        "crs": _canonical_crs_label(gdf.crs),
        "crs_axis_units": "meters",
        "feet_to_meter_factor_used": FEET_TO_METERS,
        "rows_checked": int(len(gdf)),
        "stored_buffer_distance_matches_ft_times_0_3048": bool(matches.all()),
        "matching_row_count": int(matches.sum()),
        "nonmatching_row_count": int((~matches).sum()),
        "sample_buffer_distance_ft": None if buffer_ft.empty else float(buffer_ft.iloc[0]),
        "sample_buffer_distance_m": None if buffer_m.empty else float(buffer_m.iloc[0]),
    }


def create_staged_multizone_geometry(
    zone1_gdf: gpd.GeoDataFrame,
    zone2_donut_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    if _canonical_crs_label(zone1_gdf.crs) != _canonical_crs_label(zone2_donut_gdf.crs):
        raise ValueError("Zone1 and Zone2 donut inputs must share the same CRS.")

    zone1 = zone1_gdf.copy()
    zone2 = zone2_donut_gdf.copy()

    zone1["Zone_Type"] = "Zone 1: Critical"
    zone1["Zone_Class"] = "Zone1"
    zone1["Zone_SourceOutput"] = "Study_Signals_Zone1CriticalBuffer"
    zone1["Zone_GeometryMethod"] = "signal_point_buffer"
    zone1["Zone_PrimaryDistanceField"] = "Dist_Lim"
    zone1["Zone_SecondaryDistanceField"] = pd.NA
    zone1["Zone_DissolveStatus"] = "pre_dissolve_one_feature_per_signal"
    zone1["Zone_OverlapStatus"] = "geometries may overlap; no dissolve applied"

    zone2["Zone_Type"] = "Zone 2: Functional"
    zone2["Zone_Class"] = "Zone2"
    zone2["Zone_SourceOutput"] = "Study_Signals_Zone2FunctionalDonut"
    zone2["Zone_GeometryMethod"] = "zone2_full_minus_zone1_critical"
    zone2["Zone_PrimaryDistanceField"] = "Dist_Des"
    zone2["Zone_SecondaryDistanceField"] = "Dist_Lim"
    zone2["Zone_DissolveStatus"] = "pre_dissolve_one_feature_per_signal"
    zone2["Zone_OverlapStatus"] = "geometries may overlap; no dissolve applied"

    combined_df = pd.concat([zone1, zone2], ignore_index=True, sort=False)
    combined = gpd.GeoDataFrame(combined_df, geometry="geometry", crs=zone1.crs)

    summary = {
        "feature_count": int(len(combined)),
        "combine_method": "row-wise concatenation of Zone 1 critical buffers and Zone 2 functional donuts into one staged layer",
        "source_inputs": [
            "Study_Signals_Zone1CriticalBuffer",
            "Study_Signals_Zone2FunctionalDonut",
        ],
        "one_combined_layer": True,
        "one_feature_per_signal_per_zone": True,
        "dissolve_status": "pre_dissolve_one_feature_per_signal",
        "overlap_status": "geometries may overlap; no dissolve applied",
        "empty_geometry_count": int(combined.geometry.is_empty.sum()),
        "null_geometry_count": int(combined.geometry.isna().sum()),
        "zone_type_counts": {
            str(k): int(v)
            for k, v in combined["Zone_Type"].value_counts(dropna=False).sort_index().to_dict().items()
        },
        "traceability": {
            "signal_rowid_present": "Signal_RowID" in combined.columns,
            "signal_rowid_non_null_count": int(combined["Signal_RowID"].notna().sum()) if "Signal_RowID" in combined.columns else 0,
            "reg_signal_id_present": "REG_SIGNAL_ID" in combined.columns,
            "signal_no_present": "SIGNAL_NO" in combined.columns,
            "intno_present": "INTNO" in combined.columns,
            "intnum_present": "INTNUM" in combined.columns,
        },
    }
    return combined, summary


def create_raw_road_zone_intersection(
    roads_gdf: gpd.GeoDataFrame,
    multizone_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    if _canonical_crs_label(roads_gdf.crs) != _canonical_crs_label(multizone_gdf.crs):
        raise ValueError("Road and multi-zone inputs must share the same CRS.")

    intersected = gpd.overlay(roads_gdf, multizone_gdf, how="intersection", keep_geom_type=False)
    intersected["RoadZone_IntersectionMethod"] = "geopandas_overlay_intersection"
    intersected["RoadZone_ProcessingStage"] = "pre_cleanup_pre_claim_pre_segmentation"
    intersected["RoadZone_OverlapStatus"] = "multiple rows per road may occur from multiple signal/zone overlaps"

    road_event_unique = 0
    if "EVENT_SOUR" in intersected.columns:
        road_event_unique = int(intersected["EVENT_SOUR"].astype(str).nunique())

    summary = {
        "feature_count": int(len(intersected)),
        "operation": "geopandas overlay intersection of Study_Roads_Divided and Study_Signals_StagedMultiZone",
        "processing_stage": "pre_cleanup_pre_claim_pre_segmentation",
        "multiple_rows_per_road_possible": True,
        "road_zone_overlap_possible": True,
        "empty_geometry_count": int(intersected.geometry.is_empty.sum()),
        "null_geometry_count": int(intersected.geometry.isna().sum()),
        "geometry_type_counts": {
            str(k): int(v)
            for k, v in intersected.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
        },
        "unique_roads_represented_by_rte_id": int(intersected["RTE_ID"].astype(str).nunique()) if "RTE_ID" in intersected.columns else 0,
        "unique_roads_represented_by_event_sour": road_event_unique,
        "unique_signals_represented": int(intersected["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in intersected.columns else 0,
        "zone_type_counts": {
            str(k): int(v)
            for k, v in intersected["Zone_Type"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Type" in intersected.columns else {},
        "zone_class_counts": {
            str(k): int(v)
            for k, v in intersected["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in intersected.columns else {},
        "traceability_fields_present": {
            "road_rte_id": "RTE_ID" in intersected.columns,
            "road_rte_nm": "RTE_NM" in intersected.columns,
            "road_event_sour": "EVENT_SOUR" in intersected.columns,
            "signal_rowid": "Signal_RowID" in intersected.columns,
            "zone_type": "Zone_Type" in intersected.columns,
            "zone_class": "Zone_Class" in intersected.columns,
            "zone_source_output": "Zone_SourceOutput" in intersected.columns,
        },
    }
    return intersected, summary


def _road_identifier_summary(gdf: gpd.GeoDataFrame) -> dict[str, object]:
    summary: dict[str, object] = {
        "unique_roads_represented_by_rte_id": 0,
        "unique_roads_represented_by_event_sour": 0,
        "unique_rte_id_event_sour_pairs": 0,
        "notes": (
            "RTE_ID alone is not treated as a stable unique road key for this bounded slice. "
            "EVENT_SOUR and the (RTE_ID, EVENT_SOUR) pair are reported as more defensible coverage summaries."
        ),
    }
    if "RTE_ID" in gdf.columns:
        summary["unique_roads_represented_by_rte_id"] = int(gdf["RTE_ID"].astype(str).nunique())
    if "EVENT_SOUR" in gdf.columns:
        summary["unique_roads_represented_by_event_sour"] = int(gdf["EVENT_SOUR"].astype(str).nunique())
    if "RTE_ID" in gdf.columns and "EVENT_SOUR" in gdf.columns:
        pairs = (
            gdf[["RTE_ID", "EVENT_SOUR"]]
            .fillna("<null>")
            .astype(str)
            .drop_duplicates()
        )
        summary["unique_rte_id_event_sour_pairs"] = int(len(pairs))
    return summary


def create_minimal_preclaim_road_zone_geometry(
    raw_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    cleaned = raw_gdf.copy()
    before_row_count = int(len(cleaned))

    null_geometry_count_before = int(cleaned.geometry.isna().sum())
    empty_geometry_count_before = int(cleaned.geometry.is_empty.sum())
    invalid_geometry_count_before = int((~cleaned.geometry.is_valid).sum())
    line_length_before = cleaned.length
    zero_length_count_before = int((line_length_before <= 0).sum())

    repair_attempted_rows = invalid_geometry_count_before
    if repair_attempted_rows:
        invalid_mask = ~cleaned.geometry.is_valid
        cleaned.loc[invalid_mask, "geometry"] = cleaned.loc[invalid_mask, "geometry"].map(shapely_make_valid)

    invalid_geometry_count_after_repair = int((~cleaned.geometry.is_valid).sum())

    removed_null_geometry = 0
    if null_geometry_count_before:
        mask = cleaned.geometry.notna()
        removed_null_geometry = int((~mask).sum())
        cleaned = cleaned.loc[mask].copy()

    removed_empty_geometry = 0
    if not cleaned.empty:
        empty_mask = cleaned.geometry.is_empty
        removed_empty_geometry = int(empty_mask.sum())
        if removed_empty_geometry:
            cleaned = cleaned.loc[~empty_mask].copy()

    removed_non_line_geometry = 0
    if not cleaned.empty:
        line_mask = cleaned.geom_type.isin(["LineString", "MultiLineString"])
        removed_non_line_geometry = int((~line_mask).sum())
        if removed_non_line_geometry:
            cleaned = cleaned.loc[line_mask].copy()

    removed_zero_length_geometry = 0
    if not cleaned.empty:
        zero_length_mask = cleaned.length <= 0
        removed_zero_length_geometry = int(zero_length_mask.sum())
        if removed_zero_length_geometry:
            cleaned = cleaned.loc[~zero_length_mask].copy()

    cleaned["RoadZone_ProcessingStage"] = "minimal_geometry_cleanup_pre_claim_pre_segmentation"
    cleaned["RoadZone_CleanupStatus"] = "minimum_required_geometry_cleanup_only"
    cleaned["RoadZone_CleanupRules"] = (
        "repair invalid geometry if present; drop null geometry; drop empty geometry; "
        "drop non-line artifacts after repair; drop zero-length geometries"
    )
    cleaned["RoadZone_ClaimStatus"] = "pre_claim"
    cleaned["RoadZone_SegmentationStatus"] = "pre_segmentation"
    cleaned["RoadZone_OverlapStatus"] = "overlap resolution not applied; multiple rows per road may remain"

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(cleaned)),
        "rows_removed_total": int(before_row_count - len(cleaned)),
        "cleanup_rules": [
            {
                "rule_name": "invalid_geometry_repair",
                "required_for_usable_preclaim_geometry": True,
                "action": "repair invalid geometries with shapely.make_valid before any row drops",
                "rows_flagged_before_rule": invalid_geometry_count_before,
                "rows_removed_by_rule": 0,
            },
            {
                "rule_name": "null_geometry_removal",
                "required_for_usable_preclaim_geometry": True,
                "action": "drop rows whose geometry is null",
                "rows_flagged_before_rule": null_geometry_count_before,
                "rows_removed_by_rule": removed_null_geometry,
            },
            {
                "rule_name": "empty_geometry_removal",
                "required_for_usable_preclaim_geometry": True,
                "action": "drop rows whose geometry is empty",
                "rows_flagged_before_rule": empty_geometry_count_before,
                "rows_removed_by_rule": removed_empty_geometry,
            },
            {
                "rule_name": "non_line_geometry_removal",
                "required_for_usable_preclaim_geometry": True,
                "action": "drop repaired artifacts that are no longer LineString or MultiLineString",
                "rows_flagged_before_rule": removed_non_line_geometry,
                "rows_removed_by_rule": removed_non_line_geometry,
            },
            {
                "rule_name": "zero_length_geometry_removal",
                "required_for_usable_preclaim_geometry": True,
                "action": "drop line geometries whose length is zero or negative in the working CRS",
                "rows_flagged_before_rule": zero_length_count_before,
                "rows_removed_by_rule": removed_zero_length_geometry,
            },
        ],
        "geometry_health": {
            "invalid_geometry_count_before_repair": invalid_geometry_count_before,
            "invalid_geometry_repair_attempted_rows": repair_attempted_rows,
            "invalid_geometry_count_after_repair": invalid_geometry_count_after_repair,
            "null_geometry_count_before_cleanup": null_geometry_count_before,
            "empty_geometry_count_before_cleanup": empty_geometry_count_before,
            "zero_length_count_before_cleanup": zero_length_count_before,
            "null_geometry_count_after_cleanup": int(cleaned.geometry.isna().sum()),
            "empty_geometry_count_after_cleanup": int(cleaned.geometry.is_empty.sum()),
            "invalid_geometry_count_after_cleanup": int((~cleaned.geometry.is_valid).sum()),
            "zero_length_count_after_cleanup": int((cleaned.length <= 0).sum()) if not cleaned.empty else 0,
            "geometry_type_counts_after_cleanup": {
                str(k): int(v)
                for k, v in cleaned.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
        },
        "signal_representation": {
            "unique_signals_represented_after_cleanup": int(cleaned["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in cleaned.columns else 0,
        },
        "zone_class_counts_after_cleanup": {
            str(k): int(v)
            for k, v in cleaned["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in cleaned.columns else {},
        "zone_type_counts_after_cleanup": {
            str(k): int(v)
            for k, v in cleaned["Zone_Type"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Type" in cleaned.columns else {},
        "road_identifier_summary_after_cleanup": _road_identifier_summary(cleaned),
        "output_status": {
            "pre_claim": True,
            "pre_segmentation": True,
            "multiple_rows_per_road_possible": True,
            "overlapping_possible": True,
            "claim_logic_applied": False,
            "overlap_resolution_applied": False,
            "stable_segment_id_design_applied": False,
        },
    }
    return cleaned, summary


def _claim_geometry_hash(geom) -> str | None:
    if geom is None:
        return None
    return hashlib.sha1(geom.normalize().wkb).hexdigest()


def _signal_identifier(row: pd.Series) -> str:
    for field in ("REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "INTNUM"):
        if field in row.index:
            value = row.get(field)
            if value is not None and str(value).strip() not in ("", "nan", "<null>"):
                return str(value)
    value = row.get("Signal_RowID")
    return "<null>" if value is None else str(value)


def _geometry_part_count(geom) -> int:
    if geom is None:
        return 0
    geom_type = getattr(geom, "geom_type", None)
    if geom_type == "MultiLineString":
        return int(len(list(geom.geoms)))
    if geom_type == "LineString":
        return 1
    return 0


def assign_signal_ownership_to_claim_pieces(
    preclaim_gdf: gpd.GeoDataFrame,
    signal_points_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    if _canonical_crs_label(preclaim_gdf.crs) != _canonical_crs_label(signal_points_gdf.crs):
        raise ValueError("Pre-claim road pieces and signal points must share the same CRS.")

    working = preclaim_gdf.reset_index(drop=True).copy()
    working["Ownership_SourceRowID"] = working.index.astype("int64")
    working["Ownership_ClaimGeomHash"] = working.geometry.map(_claim_geometry_hash)
    working["Ownership_GroupKey"] = (
        working["EVENT_SOUR"].fillna("<null>").astype(str)
        + "|"
        + working["RTE_ID"].fillna("<null>").astype(str)
        + "|"
        + working["Zone_Class"].fillna("<null>").astype(str)
        + "|"
        + working["Zone_Type"].fillna("<null>").astype(str)
        + "|"
        + working["Ownership_ClaimGeomHash"].fillna("<null>").astype(str)
    )

    signal_points = signal_points_gdf[["geometry"]].reset_index(drop=True).copy()
    signal_points["Signal_RowID"] = signal_points.index.astype("int64")
    signal_points = signal_points.rename(columns={"geometry": "Ownership_SignalGeometry"})
    working = working.merge(signal_points, on="Signal_RowID", how="left")

    event_source = working["EVENT_SOUR"].fillna("<null>").astype(str)
    nearest_event_source = working["NearestRoad_EVENT_SOUR"].fillna("<null>").astype(str)
    route_id = working["RTE_ID"].fillna("<null>").astype(str)
    nearest_route_id = working["NearestRoad_RTE_ID"].fillna("<null>").astype(str)
    working["Ownership_EventMatch"] = event_source.eq(nearest_event_source)
    working["Ownership_RouteMatch"] = route_id.eq(nearest_route_id)

    piece_centroids = gpd.GeoSeries(working.geometry.centroid, index=working.index, crs=working.crs)
    signal_geometry = gpd.GeoSeries(working["Ownership_SignalGeometry"], index=working.index, crs=working.crs)
    working["Ownership_NearDist_M"] = piece_centroids.distance(signal_geometry)
    working["Ownership_NearDist_FT"] = working["Ownership_NearDist_M"] / FEET_TO_METERS
    working["Ownership_HasSignalGeometry"] = working["Ownership_SignalGeometry"].notna()

    group_row_count = working.groupby("Ownership_GroupKey").size().rename("Ownership_GroupRowCount")
    group_candidate_count = (
        working.groupby("Ownership_GroupKey")["Signal_RowID"]
        .nunique(dropna=True)
        .rename("Ownership_CandidateCount")
    )
    working = working.merge(group_row_count, on="Ownership_GroupKey", how="left")
    working = working.merge(group_candidate_count, on="Ownership_GroupKey", how="left")
    working["Ownership_CandidateCount"] = working["Ownership_CandidateCount"].fillna(0).astype("int64")
    working["Ownership_GroupRowCount"] = working["Ownership_GroupRowCount"].fillna(0).astype("int64")
    working["Is_Contested"] = working["Ownership_CandidateCount"] > 1
    working["Ownership_UncontestedDuplicate"] = (
        (working["Ownership_CandidateCount"] == 1) & (working["Ownership_GroupRowCount"] > 1)
    )
    working["Ownership_ContestStatus"] = np.where(
        working["Is_Contested"],
        "contested_multi_signal",
        np.where(
            working["Ownership_UncontestedDuplicate"],
            "uncontested_duplicate_same_signal",
            "uncontested_single_signal",
        ),
    )
    working["Ownership_Rule"] = np.where(
        working["Is_Contested"],
        "event_match_desc_then_route_match_desc_then_piece_centroid_to_signal_distance_asc_then_signal_rowid_asc",
        np.where(
            working["Ownership_UncontestedDuplicate"],
            "single_signal_duplicate_exact_piece_keep_lowest_source_rowid",
            "single_signal_candidate_only",
        ),
    )

    sort_columns = [
        "Ownership_GroupKey",
        "Ownership_EventMatch",
        "Ownership_RouteMatch",
        "Ownership_NearDist_M",
        "Signal_RowID",
        "Ownership_SourceRowID",
    ]
    owned = (
        working.sort_values(
            sort_columns,
            ascending=[True, False, False, True, True, True],
            kind="stable",
        )
        .drop_duplicates("Ownership_GroupKey", keep="first")
        .copy()
    )
    owned["Ownership_Assigned"] = True
    owned["Ownership_AssignmentStatus"] = "assigned"
    owned["RoadZone_ProcessingStage"] = "ownership_assigned_pre_segmentation"
    owned["RoadZone_ClaimStatus"] = "owned"
    owned["RoadZone_SegmentationStatus"] = "pre_segmentation"
    owned["RoadZone_OverlapStatus"] = "ownership assigned per claim piece; segmentation and downstream cleanup not applied"
    owned = owned.drop(columns=["Ownership_SignalGeometry"])

    kept_per_group = owned["Ownership_GroupKey"].nunique()
    unresolved_group_count = int(group_row_count.index.nunique() - kept_per_group)
    contested_group_count = int(owned["Is_Contested"].sum())
    uncontested_group_count = int((~owned["Is_Contested"]).sum())
    uncontested_duplicate_group_count = int(owned["Ownership_UncontestedDuplicate"].sum())

    contested_working = working.loc[working["Is_Contested"]].copy()
    contested_samples: list[dict[str, object]] = []
    if not contested_working.empty:
        kept_lookup = owned.set_index("Ownership_GroupKey")[["Signal_RowID", "Ownership_NearDist_M", "Ownership_EventMatch", "Ownership_RouteMatch"]]
        for claim_group_key, group in contested_working.groupby("Ownership_GroupKey", sort=True):
            group = group.sort_values(
                ["Ownership_EventMatch", "Ownership_RouteMatch", "Ownership_NearDist_M", "Signal_RowID", "Ownership_SourceRowID"],
                ascending=[False, False, True, True, True],
                kind="stable",
            )
            winner = kept_lookup.loc[claim_group_key]
            sample = {
                "Ownership_GroupKey": str(claim_group_key),
                "EVENT_SOUR": str(group["EVENT_SOUR"].iloc[0]),
                "RTE_ID": str(group["RTE_ID"].iloc[0]),
                "Zone_Class": str(group["Zone_Class"].iloc[0]),
                "Zone_Type": str(group["Zone_Type"].iloc[0]),
                "Ownership_CandidateCount": int(group["Ownership_CandidateCount"].iloc[0]),
                "selected_signal_rowid": int(winner["Signal_RowID"]),
                "selected_rule": str(group["Ownership_Rule"].iloc[0]),
                "candidates": [],
            }
            for row in group.itertuples(index=False):
                sample["candidates"].append(
                    {
                        "Signal_RowID": int(row.Signal_RowID),
                        "SignalIdentifier": _signal_identifier(pd.Series(row._asdict())),
                        "Ownership_EventMatch": bool(row.Ownership_EventMatch),
                        "Ownership_RouteMatch": bool(row.Ownership_RouteMatch),
                        "Ownership_NearDist_M": round(float(row.Ownership_NearDist_M), 3),
                        "Ownership_NearDist_FT": round(float(row.Ownership_NearDist_FT), 3),
                        "kept": int(row.Signal_RowID) == int(winner["Signal_RowID"])
                        and abs(float(row.Ownership_NearDist_M) - float(winner["Ownership_NearDist_M"])) < 1e-9
                        and bool(row.Ownership_EventMatch) == bool(winner["Ownership_EventMatch"])
                        and bool(row.Ownership_RouteMatch) == bool(winner["Ownership_RouteMatch"]),
                    }
                )
            contested_samples.append(sample)
        contested_samples = contested_samples[:10]

    summary = {
        "before_row_count": int(len(preclaim_gdf)),
        "after_row_count": int(len(owned)),
        "rows_removed_total": int(len(preclaim_gdf) - len(owned)),
        "claim_piece_definition": {
            "grouping_rule": "same EVENT_SOUR, same RTE_ID, same Zone_Class, same Zone_Type, and same normalized exact geometry hash",
            "contested_piece_rule": "a claim piece is contested when a claim group has more than one distinct Signal_RowID candidate",
            "uncontested_duplicate_rule": "duplicate rows for the same exact claim piece and the same Signal_RowID are treated as uncontested duplicates, not multi-signal contests",
        },
        "ownership_rule": {
            "rule_name": "event_match_then_route_match_then_nearest_signal_then_signal_rowid",
            "sort_priority": [
                "Ownership_EventMatch descending",
                "Ownership_RouteMatch descending",
                "Ownership_NearDist_M ascending",
                "Signal_RowID ascending",
                "Ownership_SourceRowID ascending",
            ],
            "event_match_definition": "road piece EVENT_SOUR equals candidate signal NearestRoad_EVENT_SOUR",
            "route_match_definition": "road piece RTE_ID equals candidate signal NearestRoad_RTE_ID",
            "distance_definition": "distance from claim-piece centroid to source Study_Signals point geometry",
        },
        "piece_counts": {
            "owned_piece_count": int(len(owned)),
            "uncontested_piece_count": uncontested_group_count,
            "contested_piece_count": contested_group_count,
            "uncontested_duplicate_same_signal_piece_count": uncontested_duplicate_group_count,
            "contested_pieces_assigned": contested_group_count,
            "unresolved_piece_count": unresolved_group_count,
        },
        "geometry_health": {
            "null_geometry_count_after_assignment": int(owned.geometry.isna().sum()),
            "empty_geometry_count_after_assignment": int(owned.geometry.is_empty.sum()),
            "invalid_geometry_count_after_assignment": int((~owned.geometry.is_valid).sum()),
            "geometry_type_counts_after_assignment": {
                str(k): int(v)
                for k, v in owned.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
        },
        "zone_class_counts_after_assignment": {
            str(k): int(v)
            for k, v in owned["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in owned.columns else {},
        "road_identifier_summary_after_assignment": _road_identifier_summary(owned),
        "signal_representation_after_assignment": {
            "unique_signals_represented": int(owned["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in owned.columns else 0,
        },
        "contested_case_samples": contested_samples,
        "output_status": {
            "pre_segmentation": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return owned, summary


def create_first_segmented_road_pieces(
    owned_claims_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    working = owned_claims_gdf.reset_index(drop=True).copy()
    before_row_count = int(len(working))
    before_geometry_type_counts = {
        str(k): int(v)
        for k, v in working.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
    }
    source_multipart_mask = working.geom_type == "MultiLineString"
    source_singlepart_mask = working.geom_type == "LineString"
    source_multipart_count = int(source_multipart_mask.sum())
    source_singlepart_count = int(source_singlepart_mask.sum())

    working["Segment_SourceOwnedRowID"] = working.index.astype("int64")
    working["Segment_SourceGeomType"] = working.geom_type.astype(str)
    working["Segment_SourcePartCount"] = working.geometry.map(_geometry_part_count).astype("int64")
    working["Segment_MultipartSource"] = working["Segment_SourcePartCount"] > 1
    working["Segment_GeometryOperation"] = "explode_multilinestring_to_singlepart_linestring"

    working.index = pd.Index(working["Segment_SourceOwnedRowID"], name="Segment_SourceOwnedRowID_Index")
    exploded = working.explode(index_parts=True)
    exploded["Segment_PartIndex0"] = exploded.index.get_level_values(-1).astype("int64")
    exploded = exploded.reset_index(level=1, drop=True).reset_index(drop=True)
    exploded["Segment_PartIndex0"] = exploded["Segment_PartIndex0"].fillna(0).astype("int64")
    exploded["Segment_PartIndex"] = exploded["Segment_PartIndex0"] + 1

    after_explode_row_count = int(len(exploded))
    added_rows_from_multipart_split = int(after_explode_row_count - before_row_count)

    removed_null_geometry = 0
    if not exploded.empty:
        null_mask = exploded.geometry.isna()
        removed_null_geometry = int(null_mask.sum())
        if removed_null_geometry:
            exploded = exploded.loc[~null_mask].copy()

    removed_empty_geometry = 0
    if not exploded.empty:
        empty_mask = exploded.geometry.is_empty
        removed_empty_geometry = int(empty_mask.sum())
        if removed_empty_geometry:
            exploded = exploded.loc[~empty_mask].copy()

    removed_non_linestring_geometry = 0
    if not exploded.empty:
        line_mask = exploded.geom_type == "LineString"
        removed_non_linestring_geometry = int((~line_mask).sum())
        if removed_non_linestring_geometry:
            exploded = exploded.loc[line_mask].copy()

    removed_zero_length_geometry = 0
    if not exploded.empty:
        zero_length_mask = exploded.length <= 0
        removed_zero_length_geometry = int(zero_length_mask.sum())
        if removed_zero_length_geometry:
            exploded = exploded.loc[~zero_length_mask].copy()

    exploded["RoadZone_ProcessingStage"] = "segmented_raw_pre_stable_id"
    exploded["RoadZone_SegmentationStatus"] = "first_segmented_output_no_stable_id_design"
    exploded["Segment_IsSinglepart"] = True
    exploded["Segment_HasStableID"] = False

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(exploded)),
        "segmentation_definition": {
            "definition": "segmented means each owned road-claim geometry is converted into explicit singlepart line pieces suitable for downstream segment-level work",
            "geometry_operation": "GeoPandas explode(index_parts=True) on owned claim geometries to split MultiLineString claims into individual LineString parts",
            "stable_segment_ids_created": False,
        },
        "row_change_accounting": {
            "input_owned_rows": before_row_count,
            "input_singlepart_rows": source_singlepart_count,
            "input_multipart_rows": source_multipart_count,
            "rows_after_explode_before_filters": after_explode_row_count,
            "added_rows_from_multipart_split": added_rows_from_multipart_split,
            "removed_null_geometry_rows": removed_null_geometry,
            "removed_empty_geometry_rows": removed_empty_geometry,
            "removed_non_linestring_rows": removed_non_linestring_geometry,
            "removed_zero_length_rows": removed_zero_length_geometry,
            "final_segment_rows": int(len(exploded)),
        },
        "multipart_accounting": {
            "source_multipart_row_count": source_multipart_count,
            "source_singlepart_row_count": source_singlepart_count,
            "source_part_count_distribution": {
                str(k): int(v)
                for k, v in (
                    working.loc[working["Segment_MultipartSource"], "Segment_SourcePartCount"]
                    .value_counts(dropna=False)
                    .sort_index()
                    .to_dict()
                    .items()
                )
            },
        },
        "geometry_health": {
            "geometry_types_before": before_geometry_type_counts,
            "geometry_types_after": {
                str(k): int(v)
                for k, v in exploded.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_segmentation": int(exploded.geometry.isna().sum()),
            "empty_geometry_count_after_segmentation": int(exploded.geometry.is_empty.sum()),
            "invalid_geometry_count_after_segmentation": int((~exploded.geometry.is_valid).sum()),
            "zero_length_count_after_segmentation": int((exploded.length <= 0).sum()) if not exploded.empty else 0,
        },
        "zone_class_counts_after_segmentation": {
            str(k): int(v)
            for k, v in exploded["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in exploded.columns else {},
        "signal_representation_after_segmentation": {
            "unique_signals_represented": int(exploded["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in exploded.columns else 0,
        },
        "road_identifier_summary_after_segmentation": _road_identifier_summary(exploded),
        "output_status": {
            "ownership_resolved": True,
            "pre_segmentation_cleanup_only": False,
            "first_segmented_output": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return exploded, summary


def enrich_segment_support_fields(
    segments_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    enriched = segments_gdf.copy()
    before_row_count = int(len(enriched))

    # These are the minimum downstream-support geometry fields carried by the legacy segmentation phase.
    enriched["Seg_Len_Ft"] = enriched.length / FEET_TO_METERS
    midpoints = enriched.geometry.interpolate(0.5, normalized=True)
    enriched["Mid_X"] = midpoints.x.astype("float64")
    enriched["Mid_Y"] = midpoints.y.astype("float64")
    enriched["RoadZone_ProcessingStage"] = "segmented_raw_support_fields_added"

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(enriched)),
        "row_change_accounting": {
            "input_segment_rows": before_row_count,
            "rows_removed": 0,
            "rows_added": 0,
            "final_segment_rows": int(len(enriched)),
            "geometry_row_set_changed": False,
        },
        "new_fields_added": [
            {
                "field_name": "Seg_Len_Ft",
                "type": "DOUBLE",
                "units": "feet",
                "why_needed_now": "minimum segment-length support field used by later bounded QC and downstream segment calculations",
            },
            {
                "field_name": "Mid_X",
                "type": "DOUBLE",
                "units": "working CRS x coordinate (meters in EPSG:3968)",
                "why_needed_now": "minimum explicit midpoint support field for later directional/measure-based segment work",
            },
            {
                "field_name": "Mid_Y",
                "type": "DOUBLE",
                "units": "working CRS y coordinate (meters in EPSG:3968)",
                "why_needed_now": "minimum explicit midpoint support field for later directional/measure-based segment work",
            },
        ],
        "geometry_support_rule": {
            "geometry_operation": "attribute enrichment only; no geometry modification",
            "segment_length_rule": "Seg_Len_Ft = geometry length in EPSG:3968 meters converted to feet",
            "midpoint_rule": "Mid_X and Mid_Y are taken from geometry.interpolate(0.5, normalized=True) in EPSG:3968",
            "stable_segment_ids_created": False,
        },
        "geometry_health": {
            "geometry_types_after_enrichment": {
                str(k): int(v)
                for k, v in enriched.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_enrichment": int(enriched.geometry.isna().sum()),
            "empty_geometry_count_after_enrichment": int(enriched.geometry.is_empty.sum()),
            "invalid_geometry_count_after_enrichment": int((~enriched.geometry.is_valid).sum()),
            "zero_length_count_after_enrichment": int((enriched.length <= 0).sum()) if not enriched.empty else 0,
        },
        "new_field_null_counts": {
            "Seg_Len_Ft": int(enriched["Seg_Len_Ft"].isna().sum()),
            "Mid_X": int(enriched["Mid_X"].isna().sum()),
            "Mid_Y": int(enriched["Mid_Y"].isna().sum()),
        },
        "new_field_ranges": {
            "Seg_Len_Ft_min": None if enriched.empty else float(enriched["Seg_Len_Ft"].min()),
            "Seg_Len_Ft_max": None if enriched.empty else float(enriched["Seg_Len_Ft"].max()),
        },
        "zone_class_counts_after_enrichment": {
            str(k): int(v)
            for k, v in enriched["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in enriched.columns else {},
        "signal_representation_after_enrichment": {
            "unique_signals_represented": int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0,
        },
        "road_identifier_summary_after_enrichment": _road_identifier_summary(enriched),
        "output_status": {
            "same_geometry_row_set_as_functional_segments_raw": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return enriched, summary


def enrich_segment_identity_qc_support_fields(
    segments_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    enriched = segments_gdf.copy().reset_index(drop=True)
    before_row_count = int(len(enriched))
    input_signal_count = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0

    # Temporary row helper only for immediate bounded audit/join use within this slice family.
    enriched["Segment_RowID_Temp"] = np.arange(len(enriched), dtype="int64")
    short_segment_mask = pd.to_numeric(enriched.get("Seg_Len_Ft"), errors="coerce") < MIN_SEGMENT_FT
    enriched["QC_ShortSegment"] = short_segment_mask.fillna(False).astype("int8")
    enriched["RoadZone_ProcessingStage"] = "segmented_support_identity_qc_added"

    flagged_short_count = int(enriched["QC_ShortSegment"].sum())
    signal_count_after = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0
    composite_traceability_fields = {"Segment_SourceOwnedRowID", "Segment_PartIndex"}
    composite_unique_count = 0
    composite_is_unique = False
    if composite_traceability_fields.issubset(enriched.columns):
        composite_keys = (
            enriched[["Segment_SourceOwnedRowID", "Segment_PartIndex"]]
            .fillna("<null>")
            .astype(str)
            .drop_duplicates()
        )
        composite_unique_count = int(len(composite_keys))
        composite_is_unique = composite_unique_count == before_row_count

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(enriched)),
        "row_change_accounting": {
            "input_segment_rows": before_row_count,
            "rows_removed": 0,
            "rows_added": 0,
            "rows_flagged_short_segment": flagged_short_count,
            "rows_flagged_not_short_segment": int(len(enriched) - flagged_short_count),
            "final_segment_rows": int(len(enriched)),
            "geometry_row_set_changed": False,
        },
        "new_fields_added": [
            {
                "field_name": "Segment_RowID_Temp",
                "type": "INT64",
                "temporary_non_stable": True,
                "why_needed_now": "single-field row helper for immediate bounded audit and join work after Functional_Segments_Raw_Support without introducing a stable segment ID design",
                "scope_note": "Valid only for this specific output row order; not stable across reruns, upstream ordering changes, or later cleanup stages.",
            },
            {
                "field_name": "QC_ShortSegment",
                "type": "SHORT",
                "temporary_non_stable": False,
                "why_needed_now": "explicitly flags pieces shorter than the legacy minimum segment threshold for immediate QC without deleting rows in this bounded slice",
                "threshold_rule": f"1 when Seg_Len_Ft < {MIN_SEGMENT_FT}, else 0",
            },
        ],
        "identity_support_rule": {
            "stable_segment_ids_created": False,
            "temporary_row_helper_created": True,
            "temporary_row_helper_field": "Segment_RowID_Temp",
            "temporary_row_helper_is_unique_within_output": int(enriched["Segment_RowID_Temp"].nunique()) == int(len(enriched)),
            "existing_traceability_fields_preserved": [
                field for field in [
                    "RTE_ID",
                    "EVENT_SOUR",
                    "Signal_RowID",
                    "Zone_Type",
                    "Zone_Class",
                    "Ownership_SourceRowID",
                    "Ownership_Assigned",
                    "Segment_SourceOwnedRowID",
                    "Segment_PartIndex",
                ] if field in enriched.columns
            ],
            "existing_source_part_traceability_composite": {
                "fields": ["Segment_SourceOwnedRowID", "Segment_PartIndex"],
                "present": composite_traceability_fields.issubset(enriched.columns),
                "unique_combination_count": composite_unique_count,
                "is_unique_for_output_rows": composite_is_unique,
            },
        },
        "qc_support_rule": {
            "short_segment_threshold_ft": MIN_SEGMENT_FT,
            "short_segment_action": "flag_only_no_row_deletion",
        },
        "geometry_health": {
            "geometry_types_after_enrichment": {
                str(k): int(v)
                for k, v in enriched.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_enrichment": int(enriched.geometry.isna().sum()),
            "empty_geometry_count_after_enrichment": int(enriched.geometry.is_empty.sum()),
            "invalid_geometry_count_after_enrichment": int((~enriched.geometry.is_valid).sum()),
            "zero_length_count_after_enrichment": int((enriched.length <= 0).sum()) if not enriched.empty else 0,
        },
        "new_field_null_counts": {
            "Segment_RowID_Temp": int(enriched["Segment_RowID_Temp"].isna().sum()),
            "QC_ShortSegment": int(enriched["QC_ShortSegment"].isna().sum()),
        },
        "short_segment_qc": {
            "flagged_count": flagged_short_count,
            "unflagged_count": int(len(enriched) - flagged_short_count),
            "flagged_share": (
                float(flagged_short_count) / float(len(enriched))
                if len(enriched) > 0 else None
            ),
            "flagged_length_distribution_ft": _numeric_distribution(
                enriched.loc[enriched["QC_ShortSegment"] == 1, "Seg_Len_Ft"]
            ) if "Seg_Len_Ft" in enriched.columns else _numeric_distribution(pd.Series(dtype="float64")),
            "flagged_zone_class_counts": {
                str(k): int(v)
                for k, v in (
                    enriched.loc[enriched["QC_ShortSegment"] == 1, "Zone_Class"]
                    .value_counts(dropna=False)
                    .sort_index()
                    .to_dict()
                    .items()
                )
            } if "Zone_Class" in enriched.columns else {},
        },
        "zone_class_counts_after_enrichment": {
            str(k): int(v)
            for k, v in enriched["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in enriched.columns else {},
        "signal_representation_after_enrichment": {
            "unique_signals_represented_before": input_signal_count,
            "unique_signals_represented_after": signal_count_after,
            "all_currently_represented_owned_signals_preserved": input_signal_count == signal_count_after,
        },
        "road_coverage_summary_after_enrichment": {
            **_road_identifier_summary(enriched),
            "segment_row_count": int(len(enriched)),
            "total_segment_length_ft": float(enriched["Seg_Len_Ft"].sum()) if "Seg_Len_Ft" in enriched.columns and not enriched.empty else 0.0,
            "rows_with_non_null_seg_len_ft": int(enriched["Seg_Len_Ft"].notna().sum()) if "Seg_Len_Ft" in enriched.columns else 0,
        },
        "output_status": {
            "same_geometry_row_set_as_functional_segments_raw_support": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return enriched, summary


def _normalize_text_series(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
    )


def _normalize_route_name_series(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .map(lambda v: " ".join(str(v).strip().upper().split()) if str(v).strip() else "")
    )


def enrich_segment_canonical_road_identity_fields(
    segments_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    enriched = segments_gdf.copy()
    before_row_count = int(len(enriched))
    input_signal_count = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0

    route_id_source = _normalize_text_series(enriched.get("RTE_ID", pd.Series(index=enriched.index, dtype="object")))
    route_name_common = _normalize_text_series(enriched.get("RTE_COMMON", pd.Series(index=enriched.index, dtype="object")))
    route_name_rte = _normalize_text_series(enriched.get("RTE_NM", pd.Series(index=enriched.index, dtype="object")))
    dir_code_source = _normalize_text_series(enriched.get("LOC_COMP_D", pd.Series(index=enriched.index, dtype="object")))

    enriched["RouteID_Norm"] = route_id_source
    enriched["RouteNm_Norm"] = route_name_common.where(route_name_common != "", route_name_rte)
    enriched["DirCode_Norm"] = dir_code_source
    enriched["RoadZone_ProcessingStage"] = "segmented_support_canonical_road_identity_added"

    signal_count_after = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(enriched)),
        "row_change_accounting": {
            "input_segment_rows": before_row_count,
            "rows_removed": 0,
            "rows_added": 0,
            "final_segment_rows": int(len(enriched)),
            "geometry_row_set_changed": False,
        },
        "new_fields_added": [
            {
                "field_name": "RouteID_Norm",
                "type": "TEXT",
                "source_fields_used": ["RTE_ID"],
                "why_needed_now": "minimum explicit canonical route identifier carry-forward for immediate downstream segment-side road lineage work using existing travelway attributes only",
            },
            {
                "field_name": "RouteNm_Norm",
                "type": "TEXT",
                "source_fields_used": ["RTE_COMMON", "RTE_NM"],
                "source_rule": "prefer RTE_COMMON, fallback to RTE_NM when RTE_COMMON is blank",
                "why_needed_now": "minimum explicit canonical route-name carry-forward for immediate downstream segment-side road lineage work using existing travelway attributes only",
            },
            {
                "field_name": "DirCode_Norm",
                "type": "TEXT",
                "source_fields_used": ["LOC_COMP_D"],
                "why_needed_now": "minimum explicit canonical directional-context carry-forward for immediate downstream segment-side road lineage work using existing travelway attributes only",
            },
        ],
        "canonical_identity_rule": {
            "derivation_uses_only_existing_row_lineage": True,
            "stable_segment_ids_created": False,
            "segment_rowid_temp_remains_temporary_non_stable": True,
            "carried_forward_canonical_road_identity_fields": ["RouteID_Norm", "RouteNm_Norm", "DirCode_Norm"],
            "not_added_in_this_slice": [
                {
                    "field_name": "LinkID_Norm",
                    "reason": "not derived here because this bounded slice is limited to direct travelway-lineage carry-forward and does not introduce external link/AADT fallback logic",
                },
                {
                    "field_name": "FromNode_Norm",
                    "reason": "not derived here because node fields are not directly present in the current row lineage and remain optional/informational at this stage",
                },
                {
                    "field_name": "ToNode_Norm",
                    "reason": "not derived here because node fields are not directly present in the current row lineage and remain optional/informational at this stage",
                },
            ],
        },
        "geometry_health": {
            "geometry_types_after_enrichment": {
                str(k): int(v)
                for k, v in enriched.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_enrichment": int(enriched.geometry.isna().sum()),
            "empty_geometry_count_after_enrichment": int(enriched.geometry.is_empty.sum()),
            "invalid_geometry_count_after_enrichment": int((~enriched.geometry.is_valid).sum()),
            "zero_length_count_after_enrichment": int((enriched.length <= 0).sum()) if not enriched.empty else 0,
        },
        "new_field_null_counts": {
            "RouteID_Norm": int((enriched["RouteID_Norm"] == "").sum()),
            "RouteNm_Norm": int((enriched["RouteNm_Norm"] == "").sum()),
            "DirCode_Norm": int((enriched["DirCode_Norm"] == "").sum()),
        },
        "zone_class_counts_after_enrichment": {
            str(k): int(v)
            for k, v in enriched["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in enriched.columns else {},
        "signal_representation_after_enrichment": {
            "unique_signals_represented_before": input_signal_count,
            "unique_signals_represented_after": signal_count_after,
            "all_currently_represented_owned_signals_preserved": input_signal_count == signal_count_after,
        },
        "road_coverage_summary_after_enrichment": {
            **_road_identifier_summary(enriched),
            "unique_routeid_norm": int(enriched["RouteID_Norm"].replace("", pd.NA).dropna().nunique()),
            "unique_routenm_norm": int(enriched["RouteNm_Norm"].replace("", pd.NA).dropna().nunique()),
            "unique_dircode_norm": int(enriched["DirCode_Norm"].replace("", pd.NA).dropna().nunique()),
            "unique_routeid_dircode_pairs": int(
                len(
                    enriched[["RouteID_Norm", "DirCode_Norm"]]
                    .replace("", pd.NA)
                    .dropna()
                    .drop_duplicates()
                )
            ),
        },
        "output_status": {
            "same_geometry_row_set_as_functional_segments_raw_support_identityqc": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return enriched, summary


def audit_segment_link_identity_support(
    segments_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    enriched = segments_gdf.copy()
    before_row_count = int(len(enriched))
    input_signal_count = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0

    direct_link_candidates = [
        "LinkID_Norm",
        "LINKID",
        "LinkID",
        "LINK_ID",
        "TMSLINKID",
        "TMS_LINKID",
        "LRS_LINKID",
        "LRS_LINK_ID",
    ]
    candidate_presence = {field: field in enriched.columns for field in direct_link_candidates}
    present_candidate_fields = [field for field, present in candidate_presence.items() if present]

    enriched["LinkID_AuditStatus"] = "not_directly_available_from_current_lineage"
    enriched["RoadZone_ProcessingStage"] = "segmented_support_link_identity_audited"

    signal_count_after = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(enriched)),
        "row_change_accounting": {
            "input_segment_rows": before_row_count,
            "rows_removed": 0,
            "rows_added": 0,
            "final_segment_rows": int(len(enriched)),
            "geometry_row_set_changed": False,
        },
        "link_identity_outcome": {
            "linkid_norm_added": False,
            "direct_link_identity_available_from_current_lineage": False,
            "outcome": "explicit_audit_only_no_direct_linkid_available",
            "reason": "No direct link-identity source field exists on the current row lineage, so LinkID_Norm was not created.",
        },
        "new_fields_added": [
            {
                "field_name": "LinkID_AuditStatus",
                "type": "TEXT",
                "why_needed_now": "explicit inspectable audit result showing that direct link identity is not available from the current carried-forward row lineage at this bounded boundary",
                "value_rule": "constant 'not_directly_available_from_current_lineage' for this output",
            },
        ],
        "direct_lineage_evidence": {
            "candidate_link_fields_checked": direct_link_candidates,
            "candidate_field_presence": candidate_presence,
            "present_candidate_fields": present_candidate_fields,
            "evidence_from_current_rows": "No direct link-id candidate field is present on Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad rows.",
            "legacy_travelway_normalization_reference": {
                "travelway_role_direct_source_for_linkid_norm": [],
                "interpretation": "The legacy role-based travelway normalization contract does not define a direct LinkID_Norm source from travelway lineage alone.",
            },
        },
        "geometry_health": {
            "geometry_types_after_enrichment": {
                str(k): int(v)
                for k, v in enriched.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_enrichment": int(enriched.geometry.isna().sum()),
            "empty_geometry_count_after_enrichment": int(enriched.geometry.is_empty.sum()),
            "invalid_geometry_count_after_enrichment": int((~enriched.geometry.is_valid).sum()),
            "zero_length_count_after_enrichment": int((enriched.length <= 0).sum()) if not enriched.empty else 0,
        },
        "new_field_null_counts": {
            "LinkID_AuditStatus": int((enriched["LinkID_AuditStatus"] == "").sum()),
        },
        "zone_class_counts_after_enrichment": {
            str(k): int(v)
            for k, v in enriched["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in enriched.columns else {},
        "signal_representation_after_enrichment": {
            "unique_signals_represented_before": input_signal_count,
            "unique_signals_represented_after": signal_count_after,
            "all_currently_represented_owned_signals_preserved": input_signal_count == signal_count_after,
        },
        "road_coverage_summary_after_enrichment": {
            **_road_identifier_summary(enriched),
            "unique_routeid_norm": int(enriched["RouteID_Norm"].replace("", pd.NA).dropna().nunique()) if "RouteID_Norm" in enriched.columns else 0,
            "unique_routenm_norm": int(enriched["RouteNm_Norm"].replace("", pd.NA).dropna().nunique()) if "RouteNm_Norm" in enriched.columns else 0,
            "unique_dircode_norm": int(enriched["DirCode_Norm"].replace("", pd.NA).dropna().nunique()) if "DirCode_Norm" in enriched.columns else 0,
        },
        "output_status": {
            "same_geometry_row_set_as_functional_segments_raw_support_identityqc_canonicalroad": True,
            "segment_rowid_temp_remains_temporary_non_stable": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return enriched, summary


def _extract_linestring_endpoint_xy(geom) -> tuple[float | None, float | None, float | None, float | None]:
    if geom is None or getattr(geom, "geom_type", None) != "LineString":
        return None, None, None, None
    coords = list(geom.coords)
    if not coords:
        return None, None, None, None
    start_x, start_y = coords[0][0], coords[0][1]
    end_x, end_y = coords[-1][0], coords[-1][1]
    return float(start_x), float(start_y), float(end_x), float(end_y)


def enrich_segment_directionality_support_fields(
    segments_gdf: gpd.GeoDataFrame,
    signal_points_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    if "Signal_RowID" not in segments_gdf.columns:
        raise ValueError("Directionality support requires Signal_RowID on segment rows.")
    reconstructed_signal_rowid = False
    if "Signal_RowID" not in signal_points_gdf.columns:
        signal_points_gdf = signal_points_gdf.reset_index(drop=True).copy()
        signal_points_gdf["Signal_RowID"] = signal_points_gdf.index.astype("int64")
        reconstructed_signal_rowid = True

    enriched = segments_gdf.copy().reset_index(drop=True)
    before_row_count = int(len(enriched))
    input_signal_count = int(enriched["Signal_RowID"].astype(str).nunique())

    node_candidate_fields = [
        "FromNode_Norm",
        "ToNode_Norm",
        "BEGINNODE",
        "ENDNODE",
        "FROM_NODE",
        "TO_NODE",
    ]
    node_candidate_presence = {field: field in enriched.columns for field in node_candidate_fields}
    present_node_fields = [field for field, present in node_candidate_presence.items() if present]

    signal_lookup = signal_points_gdf[["Signal_RowID", "geometry"]].copy()
    signal_lookup = signal_lookup.rename(columns={"geometry": "OwnedSignal_Geometry"})
    signal_lookup["OwnedSignal_X"] = signal_lookup["OwnedSignal_Geometry"].x.astype("float64")
    signal_lookup["OwnedSignal_Y"] = signal_lookup["OwnedSignal_Geometry"].y.astype("float64")
    enriched = enriched.merge(signal_lookup, on="Signal_RowID", how="left")

    endpoint_xy = enriched.geometry.map(_extract_linestring_endpoint_xy)
    endpoint_df = pd.DataFrame(
        endpoint_xy.tolist(),
        columns=["Start_X", "Start_Y", "End_X", "End_Y"],
        index=enriched.index,
    )
    enriched[["Start_X", "Start_Y", "End_X", "End_Y"]] = endpoint_df.astype("float64")

    start_points = [
        Point(xy[0], xy[1]) if xy[0] is not None and xy[1] is not None else None
        for xy in endpoint_xy.tolist()
    ]
    end_points = [
        Point(xy[2], xy[3]) if xy[2] is not None and xy[3] is not None else None
        for xy in endpoint_xy.tolist()
    ]
    signal_geoms = enriched["OwnedSignal_Geometry"].tolist()

    dist_start_m: list[float | None] = []
    dist_end_m: list[float | None] = []
    for start_pt, end_pt, signal_geom in zip(start_points, end_points, signal_geoms):
        if start_pt is None or end_pt is None or signal_geom is None:
            dist_start_m.append(None)
            dist_end_m.append(None)
            continue
        dist_start_m.append(float(start_pt.distance(signal_geom)))
        dist_end_m.append(float(end_pt.distance(signal_geom)))

    enriched["Dist_StartToSignal_Ft"] = pd.Series(dist_start_m, index=enriched.index, dtype="float64") / FEET_TO_METERS
    enriched["Dist_EndToSignal_Ft"] = pd.Series(dist_end_m, index=enriched.index, dtype="float64") / FEET_TO_METERS

    tolerance_ft = TIE_DISTANCE_TOLERANCE_METERS / FEET_TO_METERS
    diff_ft = enriched["Dist_StartToSignal_Ft"] - enriched["Dist_EndToSignal_Ft"]
    signal_missing_mask = enriched["OwnedSignal_Geometry"].isna()
    ambiguous_mask = diff_ft.abs().le(tolerance_ft) & ~signal_missing_mask
    start_mask = diff_ft.lt(-tolerance_ft)
    end_mask = diff_ft.gt(tolerance_ft)

    enriched["Signal_NearEnd_Label"] = np.where(
        signal_missing_mask,
        "MISSING_SIGNAL_GEOMETRY",
        np.where(
            ambiguous_mask,
            "AMBIGUOUS",
            np.where(start_mask, "START", np.where(end_mask, "END", "AMBIGUOUS")),
        ),
    )
    enriched["Signal_End_Ambiguous"] = ambiguous_mask.astype("int8")
    enriched["Signal_NearEnd_Dist_Ft"] = enriched[["Dist_StartToSignal_Ft", "Dist_EndToSignal_Ft"]].min(axis=1)
    enriched["Signal_FarEnd_Dist_Ft"] = enriched[["Dist_StartToSignal_Ft", "Dist_EndToSignal_Ft"]].max(axis=1)
    enriched["NodeID_AuditStatus"] = "not_directly_available_from_current_lineage"
    enriched["Directionality_AuditStatus"] = np.where(
        signal_missing_mask,
        "owned_signal_geometry_lookup_missing",
        np.where(
            ambiguous_mask,
            "endpoint_distance_tie_within_tolerance",
            "endpoint_near_signal_computed",
        ),
    )
    enriched["RoadZone_ProcessingStage"] = "segmented_support_directionality_support_added"

    signal_count_after = int(enriched["Signal_RowID"].astype(str).nunique())
    label_counts = {
        str(k): int(v)
        for k, v in enriched["Signal_NearEnd_Label"].value_counts(dropna=False).sort_index().to_dict().items()
    }

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(enriched)),
        "row_change_accounting": {
            "input_segment_rows": before_row_count,
            "rows_removed": 0,
            "rows_added": 0,
            "final_segment_rows": int(len(enriched)),
            "geometry_row_set_changed": False,
        },
        "new_fields_added": [
            {
                "field_name": "NodeID_AuditStatus",
                "type": "TEXT",
                "why_needed_now": "explicit inspectable audit result showing that direct node identity is not available from the current carried-forward row lineage at this bounded boundary",
            },
            {
                "field_name": "OwnedSignal_X",
                "type": "DOUBLE",
                "units": "working CRS x coordinate (meters in EPSG:3968)",
                "why_needed_now": "explicit owned-signal point coordinate used to derive first endpoint-based directionality support",
            },
            {
                "field_name": "OwnedSignal_Y",
                "type": "DOUBLE",
                "units": "working CRS y coordinate (meters in EPSG:3968)",
                "why_needed_now": "explicit owned-signal point coordinate used to derive first endpoint-based directionality support",
            },
            {
                "field_name": "Start_X",
                "type": "DOUBLE",
                "units": "working CRS x coordinate (meters in EPSG:3968)",
                "why_needed_now": "captures the start vertex coordinate of each owned LineString segment for endpoint-based directionality support",
            },
            {
                "field_name": "Start_Y",
                "type": "DOUBLE",
                "units": "working CRS y coordinate (meters in EPSG:3968)",
                "why_needed_now": "captures the start vertex coordinate of each owned LineString segment for endpoint-based directionality support",
            },
            {
                "field_name": "End_X",
                "type": "DOUBLE",
                "units": "working CRS x coordinate (meters in EPSG:3968)",
                "why_needed_now": "captures the end vertex coordinate of each owned LineString segment for endpoint-based directionality support",
            },
            {
                "field_name": "End_Y",
                "type": "DOUBLE",
                "units": "working CRS y coordinate (meters in EPSG:3968)",
                "why_needed_now": "captures the end vertex coordinate of each owned LineString segment for endpoint-based directionality support",
            },
            {
                "field_name": "Dist_StartToSignal_Ft",
                "type": "DOUBLE",
                "units": "feet",
                "why_needed_now": "measures owned-signal distance to the start endpoint so later downstream labeling can infer which end is nearer the signal",
            },
            {
                "field_name": "Dist_EndToSignal_Ft",
                "type": "DOUBLE",
                "units": "feet",
                "why_needed_now": "measures owned-signal distance to the end endpoint so later downstream labeling can infer which end is nearer the signal",
            },
            {
                "field_name": "Signal_NearEnd_Label",
                "type": "TEXT",
                "why_needed_now": "explicitly labels whether the start or end endpoint is nearer the owned signal, or whether the inference is ambiguous",
            },
            {
                "field_name": "Signal_NearEnd_Dist_Ft",
                "type": "DOUBLE",
                "units": "feet",
                "why_needed_now": "records the nearer endpoint distance to the owned signal for auditable downstream support",
            },
            {
                "field_name": "Signal_FarEnd_Dist_Ft",
                "type": "DOUBLE",
                "units": "feet",
                "why_needed_now": "records the farther endpoint distance to the owned signal for auditable downstream support",
            },
            {
                "field_name": "Signal_End_Ambiguous",
                "type": "SHORT",
                "why_needed_now": "flags segments where start and end endpoint distances to the owned signal tie within tolerance",
            },
            {
                "field_name": "Directionality_AuditStatus",
                "type": "TEXT",
                "why_needed_now": "records whether endpoint-near-signal support was computed cleanly, tied within tolerance, or blocked by missing signal geometry",
            },
        ],
        "node_identity_outcome": {
            "fromnode_norm_added": False,
            "tonode_norm_added": False,
            "direct_node_identity_available_from_current_lineage": False,
            "reason": "No direct node-identity source field exists on the current row lineage, so FromNode_Norm and ToNode_Norm were not created.",
            "candidate_node_fields_checked": node_candidate_fields,
            "candidate_field_presence": node_candidate_presence,
            "present_candidate_fields": present_node_fields,
            "legacy_reference": {
                "travelway_role_direct_source_for_from_to_nodes": [],
                "phase_state_interpretation": "FromNode_Norm and ToNode_Norm are optional or expected-missing through this stage unless a later implementation adds a source.",
            },
        },
        "signal_geometry_lookup": {
            "lookup_used": True,
            "lookup_path_required": "Study_Signals.parquet via Signal_RowID",
            "signal_rowid_reconstructed_from_output_row_order": reconstructed_signal_rowid,
            "why_required": "Current segment rows do not carry reliable owned-signal point geometry; XCOORD/YCOORD are largely null and do not align to the working CRS point coordinates.",
            "signal_lookup_missing_count": int(signal_missing_mask.sum()),
        },
        "directionality_support_rule": {
            "scope": "first endpoint-based geometry support layer only; not a complete downstream directionality system",
            "endpoint_extraction": "Start_X/Start_Y use the first LineString vertex; End_X/End_Y use the last LineString vertex",
            "distance_rule": "Distances are Euclidean distances in EPSG:3968 meters converted to feet between each endpoint and the owned signal point",
            "near_end_rule": f"START when Dist_StartToSignal_Ft < Dist_EndToSignal_Ft - {tolerance_ft}, END when Dist_EndToSignal_Ft < Dist_StartToSignal_Ft - {tolerance_ft}, otherwise AMBIGUOUS",
            "limitations": [
                "This does not by itself assign downstream/upstream flow role.",
                "Endpoint-near-signal support can be ambiguous for nearly symmetric segments or very short pieces.",
                "This layer depends on owned-signal lookup by Signal_RowID because current segment rows do not carry signal point geometry directly.",
            ],
        },
        "geometry_health": {
            "geometry_types_after_enrichment": {
                str(k): int(v)
                for k, v in enriched.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_enrichment": int(enriched.geometry.isna().sum()),
            "empty_geometry_count_after_enrichment": int(enriched.geometry.is_empty.sum()),
            "invalid_geometry_count_after_enrichment": int((~enriched.geometry.is_valid).sum()),
            "zero_length_count_after_enrichment": int((enriched.length <= 0).sum()) if not enriched.empty else 0,
        },
        "new_field_null_counts": {
            "OwnedSignal_X": int(enriched["OwnedSignal_X"].isna().sum()),
            "OwnedSignal_Y": int(enriched["OwnedSignal_Y"].isna().sum()),
            "Start_X": int(enriched["Start_X"].isna().sum()),
            "Start_Y": int(enriched["Start_Y"].isna().sum()),
            "End_X": int(enriched["End_X"].isna().sum()),
            "End_Y": int(enriched["End_Y"].isna().sum()),
            "Dist_StartToSignal_Ft": int(enriched["Dist_StartToSignal_Ft"].isna().sum()),
            "Dist_EndToSignal_Ft": int(enriched["Dist_EndToSignal_Ft"].isna().sum()),
            "Signal_NearEnd_Dist_Ft": int(enriched["Signal_NearEnd_Dist_Ft"].isna().sum()),
            "Signal_FarEnd_Dist_Ft": int(enriched["Signal_FarEnd_Dist_Ft"].isna().sum()),
        },
        "directionality_label_counts": label_counts,
        "directionality_summary": {
            "computed_clean_count": int((enriched["Directionality_AuditStatus"] == "endpoint_near_signal_computed").sum()),
            "ambiguous_count": int(enriched["Signal_End_Ambiguous"].sum()),
            "missing_signal_geometry_count": int((enriched["Directionality_AuditStatus"] == "owned_signal_geometry_lookup_missing").sum()),
            "near_end_distance_ft_distribution": _numeric_distribution(enriched["Signal_NearEnd_Dist_Ft"]),
            "far_end_distance_ft_distribution": _numeric_distribution(enriched["Signal_FarEnd_Dist_Ft"]),
        },
        "zone_class_counts_after_enrichment": {
            str(k): int(v)
            for k, v in enriched["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in enriched.columns else {},
        "signal_representation_after_enrichment": {
            "unique_signals_represented_before": input_signal_count,
            "unique_signals_represented_after": signal_count_after,
            "all_currently_represented_owned_signals_preserved": input_signal_count == signal_count_after,
        },
        "road_coverage_summary_after_enrichment": {
            **_road_identifier_summary(enriched),
            "unique_routeid_norm": int(enriched["RouteID_Norm"].replace("", pd.NA).dropna().nunique()) if "RouteID_Norm" in enriched.columns else 0,
            "unique_routenm_norm": int(enriched["RouteNm_Norm"].replace("", pd.NA).dropna().nunique()) if "RouteNm_Norm" in enriched.columns else 0,
            "unique_dircode_norm": int(enriched["DirCode_Norm"].replace("", pd.NA).dropna().nunique()) if "DirCode_Norm" in enriched.columns else 0,
        },
        "output_status": {
            "same_geometry_row_set_as_functional_segments_raw_support_identityqc_canonicalroad_linkaudit": True,
            "segment_rowid_temp_remains_temporary_non_stable": True,
            "stable_segment_id_design_applied": False,
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return enriched.drop(columns=["OwnedSignal_Geometry"]), summary


def enrich_segment_oracle_direction_prep_fields(
    segments_gdf: gpd.GeoDataFrame,
    repo_root: Path,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    enriched = segments_gdf.copy()
    before_row_count = int(len(enriched))
    input_signal_count = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0

    oracle_dir = repo_root / ORACLE_EXPORT_DIRNAME
    broad_lookup_path = oracle_dir / ORACLE_BROAD_LOOKUP_FILENAME
    gis_keys_path = oracle_dir / ORACLE_GIS_KEYS_FILENAME
    broad_lookup_exists = broad_lookup_path.exists()
    gis_keys_exists = gis_keys_path.exists()

    broad_lookup_rows = 0
    broad_lookup_route_count = 0
    route_summary = pd.DataFrame(columns=[
        "OracleRouteNm_Candidate",
        "OracleBroadRouteDistinctTMSLinkIDCount",
        "OracleBroadRouteRowCount",
    ])
    if broad_lookup_exists:
        broad_df = pd.read_csv(broad_lookup_path, usecols=["TMSLINKID", "RTE_NM"])
        broad_lookup_rows = int(len(broad_df))
        broad_df["OracleRouteNm_Candidate"] = _normalize_route_name_series(broad_df["RTE_NM"])
        broad_df["TMSLINKID"] = _normalize_text_series(broad_df["TMSLINKID"])
        broad_df = broad_df.loc[broad_df["OracleRouteNm_Candidate"] != ""].copy()
        broad_lookup_route_count = int(broad_df["OracleRouteNm_Candidate"].nunique())
        route_summary = (
            broad_df.groupby("OracleRouteNm_Candidate", dropna=False)
            .agg(
                OracleBroadRouteDistinctTMSLinkIDCount=("TMSLINKID", lambda s: int(s.replace("", pd.NA).dropna().nunique())),
                OracleBroadRouteRowCount=("OracleRouteNm_Candidate", "size"),
            )
            .reset_index()
        )

    gis_keys_rows = 0
    gis_keys_columns: list[str] = []
    if gis_keys_exists:
        gis_keys_sample = pd.read_csv(gis_keys_path, nrows=5)
        gis_keys_rows = int(sum(1 for _ in open(gis_keys_path, "r", encoding="utf-8")) - 1)
        gis_keys_columns = [str(c) for c in gis_keys_sample.columns]

    enriched["OracleDirection_DependencyStatus"] = "oracle_required_for_trustworthy_downstream_directionality"
    enriched["OracleRouteNm_Candidate"] = _normalize_route_name_series(enriched.get("RTE_NM", pd.Series(index=enriched.index, dtype="object")))
    if not route_summary.empty:
        enriched = enriched.merge(route_summary, on="OracleRouteNm_Candidate", how="left")
    else:
        enriched["OracleBroadRouteDistinctTMSLinkIDCount"] = pd.Series(0, index=enriched.index, dtype="int64")
        enriched["OracleBroadRouteRowCount"] = pd.Series(0, index=enriched.index, dtype="int64")

    enriched["OracleBroadRouteDistinctTMSLinkIDCount"] = (
        pd.to_numeric(enriched["OracleBroadRouteDistinctTMSLinkIDCount"], errors="coerce").fillna(0).astype("int64")
    )
    enriched["OracleBroadRouteRowCount"] = (
        pd.to_numeric(enriched["OracleBroadRouteRowCount"], errors="coerce").fillna(0).astype("int64")
    )
    enriched["OracleBroadRoutePresent"] = (enriched["OracleBroadRouteDistinctTMSLinkIDCount"] > 0).astype("int8")
    enriched["OracleBroadRouteAmbiguous"] = (enriched["OracleBroadRouteDistinctTMSLinkIDCount"] > 1).astype("int8")

    has_link_identity = False
    if "LinkID_Norm" in enriched.columns:
        has_link_identity = bool(_normalize_text_series(enriched["LinkID_Norm"]).ne("").any())
    has_node_identity = False
    if {"FromNode_Norm", "ToNode_Norm"}.issubset(enriched.columns):
        has_node_identity = bool(
            _normalize_text_series(enriched["FromNode_Norm"]).ne("").any()
            and _normalize_text_series(enriched["ToNode_Norm"]).ne("").any()
        )
    has_signal_measure_support = bool("Signal_M" in enriched.columns and pd.to_numeric(enriched["Signal_M"], errors="coerce").notna().any())
    has_segment_measure_support = bool("SegMid_M" in enriched.columns and pd.to_numeric(enriched["SegMid_M"], errors="coerce").notna().any())

    def _oracle_missing_reason(row: pd.Series) -> str:
        reasons: list[str] = []
        route_candidate = row.get("OracleRouteNm_Candidate")
        route_present = int(row.get("OracleBroadRoutePresent", 0)) == 1
        if route_candidate in (None, "", " "):
            reasons.append("missing_oracle_route_candidate")
        elif not route_present:
            reasons.append("oracle_route_not_found_in_broad_lookup")
        if not has_link_identity:
            reasons.append("missing_link_identity")
        if not has_node_identity:
            reasons.append("missing_node_identity")
        if not has_signal_measure_support:
            reasons.append("missing_signal_measure_support")
        if not has_segment_measure_support:
            reasons.append("missing_segment_measure_support")
        return "|".join(reasons)

    enriched["OracleDirection_Ready"] = 0
    enriched["OracleDirection_MissingReason"] = enriched.apply(_oracle_missing_reason, axis=1)
    enriched["RoadZone_ProcessingStage"] = "segmented_support_oracle_direction_prep_added"

    signal_count_after = int(enriched["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in enriched.columns else 0
    route_present_count = int(enriched["OracleBroadRoutePresent"].sum())
    route_ambiguous_count = int(enriched["OracleBroadRouteAmbiguous"].sum())
    route_candidate_blank_count = int(_normalize_text_series(enriched["OracleRouteNm_Candidate"]).eq("").sum())

    summary = {
        "before_row_count": before_row_count,
        "after_row_count": int(len(enriched)),
        "row_change_accounting": {
            "input_segment_rows": before_row_count,
            "rows_removed": 0,
            "rows_added": 0,
            "final_segment_rows": int(len(enriched)),
            "geometry_row_set_changed": False,
        },
        "new_fields_added": [
            {
                "field_name": "OracleDirection_DependencyStatus",
                "type": "TEXT",
                "why_needed_now": "explicitly records that trustworthy downstream directionality remains Oracle-dependent at this boundary",
            },
            {
                "field_name": "OracleRouteNm_Candidate",
                "type": "TEXT",
                "source_fields_used": ["RTE_NM"],
                "why_needed_now": "provides the current-row Oracle-style route-name candidate because raw RTE_NM aligns to Oracle broad lookup RTE_NM more closely than RouteNm_Norm built from RTE_COMMON",
            },
            {
                "field_name": "OracleBroadRoutePresent",
                "type": "SHORT",
                "why_needed_now": "shows whether the Oracle route-name candidate is present in the repo-local Oracle broad lookup",
            },
            {
                "field_name": "OracleBroadRouteDistinctTMSLinkIDCount",
                "type": "LONG",
                "why_needed_now": "shows how many distinct Oracle TMSLINKIDs share the matched Oracle route-name candidate, making route-only ambiguity explicit",
            },
            {
                "field_name": "OracleBroadRouteAmbiguous",
                "type": "SHORT",
                "why_needed_now": "flags rows where route-only Oracle lookup remains ambiguous because the candidate route maps to more than one TMSLINKID",
            },
            {
                "field_name": "OracleDirection_Ready",
                "type": "SHORT",
                "why_needed_now": "explicit row-level readiness flag for a later Oracle direction match using current GIS-side key material",
            },
            {
                "field_name": "OracleDirection_MissingReason",
                "type": "TEXT",
                "why_needed_now": "explicit row-level reason showing which Oracle-direction prerequisites are still missing at this boundary",
            },
        ],
        "oracle_direction_boundary": {
            "trustworthy_downstream_directionality_available_without_oracle": False,
            "reason": "Current lineage and geometry support alone do not provide trustworthy final downstream directionality; Oracle-backed network reference remains required.",
            "oracle_backed_direction_enrichment_performed": False,
            "oracle_backed_prep_enrichment_performed": bool(broad_lookup_exists),
        },
        "oracle_artifact_status": {
            "oracle_export_dir": str(oracle_dir),
            "broad_lookup_path": str(broad_lookup_path),
            "broad_lookup_exists": broad_lookup_exists,
            "broad_lookup_rows": broad_lookup_rows,
            "broad_lookup_distinct_routes": broad_lookup_route_count,
            "gis_keys_path": str(gis_keys_path),
            "gis_keys_exists": gis_keys_exists,
            "gis_keys_rows": gis_keys_rows,
            "gis_keys_columns": gis_keys_columns,
        },
        "oracle_readiness_contract_gap": {
            "current_segment_has_link_identity": has_link_identity,
            "current_segment_has_node_identity": has_node_identity,
            "current_segment_has_signal_measure_support": has_signal_measure_support,
            "current_segment_has_segment_measure_support": has_segment_measure_support,
            "current_segment_has_oracle_route_candidate": route_candidate_blank_count < len(enriched),
            "current_segment_has_route_candidate_present_in_broad_lookup": route_present_count > 0,
            "why_oracle_direction_not_ready": (
                "Repo-local Oracle broad lookup exists, but the current segment boundary still lacks LinkID_Norm, FromNode_Norm/ToNode_Norm, Signal_M, and SegMid_M support needed for the existing Oracle matching contract."
            ),
        },
        "geometry_health": {
            "geometry_types_after_enrichment": {
                str(k): int(v)
                for k, v in enriched.geom_type.value_counts(dropna=False).sort_index().to_dict().items()
            },
            "null_geometry_count_after_enrichment": int(enriched.geometry.isna().sum()),
            "empty_geometry_count_after_enrichment": int(enriched.geometry.is_empty.sum()),
            "invalid_geometry_count_after_enrichment": int((~enriched.geometry.is_valid).sum()),
            "zero_length_count_after_enrichment": int((enriched.length <= 0).sum()) if not enriched.empty else 0,
        },
        "new_field_null_counts": {
            "OracleRouteNm_Candidate": int(_normalize_text_series(enriched["OracleRouteNm_Candidate"]).eq("").sum()),
            "OracleBroadRoutePresent": int(enriched["OracleBroadRoutePresent"].isna().sum()),
            "OracleBroadRouteDistinctTMSLinkIDCount": int(enriched["OracleBroadRouteDistinctTMSLinkIDCount"].isna().sum()),
            "OracleBroadRouteAmbiguous": int(enriched["OracleBroadRouteAmbiguous"].isna().sum()),
            "OracleDirection_Ready": int(enriched["OracleDirection_Ready"].isna().sum()),
            "OracleDirection_MissingReason": int(_normalize_text_series(enriched["OracleDirection_MissingReason"]).eq("").sum()),
        },
        "oracle_route_candidate_summary": {
            "route_candidate_non_blank_rows": int(len(enriched) - route_candidate_blank_count),
            "route_candidate_blank_rows": route_candidate_blank_count,
            "broad_route_present_rows": route_present_count,
            "broad_route_missing_rows": int(len(enriched) - route_present_count),
            "route_only_ambiguous_rows": route_ambiguous_count,
            "route_only_unique_tmslinkid_rows": int(
                ((enriched["OracleBroadRoutePresent"] == 1) & (enriched["OracleBroadRouteDistinctTMSLinkIDCount"] == 1)).sum()
            ),
        },
        "oracle_direction_readiness_summary": {
            "ready_rows": int(enriched["OracleDirection_Ready"].sum()),
            "not_ready_rows": int((enriched["OracleDirection_Ready"] == 0).sum()),
            "missing_reason_counts": {
                str(k): int(v)
                for k, v in enriched["OracleDirection_MissingReason"].value_counts(dropna=False).sort_index().to_dict().items()
            },
        },
        "zone_class_counts_after_enrichment": {
            str(k): int(v)
            for k, v in enriched["Zone_Class"].value_counts(dropna=False).sort_index().to_dict().items()
        } if "Zone_Class" in enriched.columns else {},
        "signal_representation_after_enrichment": {
            "unique_signals_represented_before": input_signal_count,
            "unique_signals_represented_after": signal_count_after,
            "all_currently_represented_owned_signals_preserved": input_signal_count == signal_count_after,
        },
        "road_coverage_summary_after_enrichment": {
            **_road_identifier_summary(enriched),
            "unique_routeid_norm": int(enriched["RouteID_Norm"].replace("", pd.NA).dropna().nunique()) if "RouteID_Norm" in enriched.columns else 0,
            "unique_routenm_norm": int(enriched["RouteNm_Norm"].replace("", pd.NA).dropna().nunique()) if "RouteNm_Norm" in enriched.columns else 0,
            "unique_oracle_route_candidate": int(enriched["OracleRouteNm_Candidate"].replace("", pd.NA).dropna().nunique()),
        },
        "output_status": {
            "same_geometry_row_set_as_functional_segments_raw_support_identityqc_canonicalroad_linkaudit_directionalitysupport": True,
            "segment_rowid_temp_remains_temporary_non_stable": True,
            "stable_segment_id_design_applied": False,
            "oracle_backed_direction_enrichment_performed": False,
            "oracle_backed_prep_enrichment_performed": bool(broad_lookup_exists),
            "crash_assignment_applied": False,
            "access_assignment_applied": False,
            "downstream_aggregation_applied": False,
        },
    }
    return enriched, summary


def run_stage1b_study_slice() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    roads_output = output_dir / OUTPUT_ROADS_NAME
    signals_output = output_dir / OUTPUT_SIGNALS_NAME
    summary_output = config.parity_dir / QC_SUMMARY_NAME

    roads = _load_normalized_input(config, "roads")
    signals = _load_normalized_input(config, "signals")

    study_roads, road_filter_summary = filter_divided_roads(roads)
    study_signals, signal_filter_summary = filter_signals_to_study_roads(
        signals,
        study_roads,
        tolerance_feet=DIVIDED_SIGNAL_TOLERANCE_FEET,
    )

    study_roads.to_parquet(roads_output, index=False)
    study_signals.to_parquet(signals_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "First bounded open-source runtime slice for Study_Roads_Divided and Study_Signals",
        "authoritative_input_boundary": "artifacts/normalized",
        "outputs": {
            "Study_Roads_Divided": {
                "path": str(roads_output),
                **_dataset_summary(study_roads, key_fields=["RTE_NM", "RTE_ID", "EVENT_SOUR"]),
            },
            "Study_Signals": {
                "path": str(signals_output),
                **_dataset_summary(study_signals, key_fields=["REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "INTNUM"]),
            },
        },
        "input_summaries": {
            "roads_normalized": _dataset_summary(roads, key_fields=["RTE_NM", "RTE_ID", "EVENT_SOUR"]),
            "signals_normalized": _dataset_summary(signals, key_fields=["REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "INTNUM"]),
        },
        "qc": {
            "road_filter": road_filter_summary,
            "signal_filter": signal_filter_summary,
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_signal_nearest_road() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    roads_input = output_dir / OUTPUT_ROADS_NAME
    signals_input = output_dir / OUTPUT_SIGNALS_NAME
    signals_output = output_dir / OUTPUT_SIGNALS_NEAREST_ROAD_NAME
    summary_output = config.parity_dir / NEAREST_ROAD_QC_SUMMARY_NAME

    study_roads = _load_stage1b_output(roads_input, label="Study_Roads_Divided")
    study_signals = _load_stage1b_output(signals_input, label="Study_Signals")

    enriched_signals, nearest_qc = enrich_signals_with_nearest_road(study_signals, study_roads)
    enriched_signals.to_parquet(signals_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Nearest study-road enrichment for Study_Signals",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_study_slice": str(output_dir),
        },
        "inputs": {
            "Study_Roads_Divided": {
                "path": str(roads_input),
                **_dataset_summary(study_roads, key_fields=["RTE_NM", "RTE_ID", "EVENT_SOUR"]),
            },
            "Study_Signals": {
                "path": str(signals_input),
                **_dataset_summary(study_signals, key_fields=["REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "INTNUM"]),
            },
        },
        "outputs": {
            "Study_Signals_NearestRoad": {
                "path": str(signals_output),
                **_dataset_summary(
                    enriched_signals,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "NearestRoad_RTE_ID",
                        "NearestRoad_EVENT_SOUR",
                    ],
                ),
            }
        },
        "qc": {
            "nearest_road_enrichment": nearest_qc,
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_signal_speed_context() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    signals_input = output_dir / OUTPUT_SIGNALS_NEAREST_ROAD_NAME
    speed_input = config.normalized_dir / "speed.parquet"
    signals_output = output_dir / OUTPUT_SIGNALS_SPEED_CONTEXT_NAME
    summary_output = config.parity_dir / SPEED_CONTEXT_QC_SUMMARY_NAME

    study_signals_nearest = _load_stage1b_output(signals_input, label="Study_Signals_NearestRoad")
    speed = _load_normalized_input(config, "speed")

    enriched_signals, speed_qc = enrich_signals_with_speed_context(study_signals_nearest, speed)
    enriched_signals.to_parquet(signals_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Posted-speed context enrichment for Study_Signals_NearestRoad",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_working_outputs": str(output_dir),
        },
        "inputs": {
            "Study_Signals_NearestRoad": {
                "path": str(signals_input),
                **_dataset_summary(
                    study_signals_nearest,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "NearestRoad_RTE_ID",
                        "NearestRoad_EVENT_SOUR",
                    ],
                ),
            },
            "speed_normalized": {
                "path": str(speed_input),
                **_dataset_summary(speed, key_fields=["EVENT_SOURCE_ID", "ROUTE_COMMON_NAME", "CAR_SPEED_LIMIT"]),
            },
        },
        "outputs": {
            "Study_Signals_SpeedContext": {
                "path": str(signals_output),
                **_dataset_summary(
                    enriched_signals,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "SpeedContext_EVENT_SOURCE_ID",
                        "Assigned_Speed",
                    ],
                ),
            }
        },
        "qc": {
            "speed_context_enrichment": speed_qc,
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_signal_functional_distance() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    signals_input = output_dir / OUTPUT_SIGNALS_SPEED_CONTEXT_NAME
    signals_output = output_dir / OUTPUT_SIGNALS_FUNCTIONAL_DISTANCE_NAME
    summary_output = config.parity_dir / FUNCTIONAL_DISTANCE_QC_SUMMARY_NAME

    study_signals_speed = _load_stage1b_output(signals_input, label="Study_Signals_SpeedContext")
    enriched_signals, functional_qc = derive_signal_functional_distances(study_signals_speed)
    enriched_signals.to_parquet(signals_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Signal-level functional-distance derivation from Assigned_Speed",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_working_outputs": str(output_dir),
        },
        "inputs": {
            "Study_Signals_SpeedContext": {
                "path": str(signals_input),
                **_dataset_summary(
                    study_signals_speed,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Assigned_Speed",
                        "SpeedContext_EVENT_SOURCE_ID",
                    ],
                ),
            }
        },
        "outputs": {
            "Study_Signals_FunctionalDistance": {
                "path": str(signals_output),
                **_dataset_summary(
                    enriched_signals,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Assigned_Speed",
                        "Dist_Lim",
                        "Dist_Des",
                    ],
                ),
            }
        },
        "functional_distance_rule": {
            "table": {
                str(k): {"Dist_Lim": int(v[0]), "Dist_Des": int(v[1])}
                for k, v in FUNCTIONAL_DISTANCE_TABLE.items()
            },
            "assigned_speed_handling": "round Assigned_Speed to nearest 5 mph; if rounded bin is not in the mapping table, use the 35 mph pair",
            "legacy_reference": "lookup_speed = int(5 * round(float(speed) / 5)); d_lim, d_des = FUNCTIONAL_DISTANCES.get(lookup_speed, FUNCTIONAL_DISTANCES[35])",
            "derived_fields": ["Dist_Lim", "Dist_Des"],
        },
        "qc": {
            "functional_distance_derivation": functional_qc,
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_signal_buffers() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    signals_input = output_dir / OUTPUT_SIGNALS_FUNCTIONAL_DISTANCE_NAME
    zone1_output = output_dir / OUTPUT_SIGNALS_ZONE1_BUFFER_NAME
    zone2_output = output_dir / OUTPUT_SIGNALS_ZONE2_FULL_BUFFER_NAME
    summary_output = config.parity_dir / BUFFER_QC_SUMMARY_NAME

    study_signals_functional = _load_stage1b_output(signals_input, label="Study_Signals_FunctionalDistance")

    zone1_buffers, zone1_summary = create_signal_centered_buffers(
        study_signals_functional,
        distance_field="Dist_Lim",
        zone_type="Zone 1: Critical",
        output_name="Study_Signals_Zone1CriticalBuffer",
    )
    zone2_buffers, zone2_summary = create_signal_centered_buffers(
        study_signals_functional,
        distance_field="Dist_Des",
        zone_type="Zone 2 Full: Desired Distance",
        output_name="Study_Signals_Zone2DesiredFullBuffer",
    )

    zone1_buffers.to_parquet(zone1_output, index=False)
    zone2_buffers.to_parquet(zone2_output, index=False)

    assigned_speed_bin = pd.Series(
        [_functional_distance_pair(v)[0] for v in study_signals_functional["Assigned_Speed"]],
        index=study_signals_functional.index,
        dtype="int64",
    )
    mapping_rule = pd.Series(
        [_functional_distance_pair(v)[3] for v in study_signals_functional["Assigned_Speed"]],
        index=study_signals_functional.index,
    )
    defaulted_mask = study_signals_functional["Assigned_Speed_Defaulted"].fillna(False).astype(bool)
    beyond_20ft_mask = (
        study_signals_functional["SpeedContext_RowID"].notna()
        & pd.to_numeric(study_signals_functional["SpeedContext_Distance_FT"], errors="coerce").gt(DIVIDED_SIGNAL_TOLERANCE_FEET)
        & pd.to_numeric(study_signals_functional["SpeedContext_Distance_FT"], errors="coerce").le(SIGNAL_SPEED_SEARCH_FEET)
    )

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Signal-centered functional-area buffer products from Dist_Lim and Dist_Des",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_working_outputs": str(output_dir),
        },
        "inputs": {
            "Study_Signals_FunctionalDistance": {
                "path": str(signals_input),
                **_dataset_summary(
                    study_signals_functional,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Assigned_Speed",
                        "Dist_Lim",
                        "Dist_Des",
                    ],
                ),
            }
        },
        "buffer_rule": {
            "geometry_basis": "each polygon is a point-centered buffer around the source signal geometry",
            "distance_units": "Dist_Lim and Dist_Des are treated as feet and converted to meters for buffering in EPSG:3968",
            "dissolve_status": "no dissolve; one feature per source signal in each output",
            "legacy_reference": {
                "zone1": "PairwiseBuffer(signals_with_speed, zone1_poly, 'Dist_Lim', dissolve_option='NONE')",
                "zone2full": "PairwiseBuffer(signals_with_speed, zone2_full, 'Dist_Des', dissolve_option='NONE')",
            },
        },
        "outputs": {
            "Study_Signals_Zone1CriticalBuffer": {
                "path": str(zone1_output),
                **_dataset_summary(
                    zone1_buffers,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Dist_Lim",
                        "Buffer_Distance_FT",
                    ],
                ),
                **zone1_summary,
            },
            "Study_Signals_Zone2DesiredFullBuffer": {
                "path": str(zone2_output),
                **_dataset_summary(
                    zone2_buffers,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Dist_Des",
                        "Buffer_Distance_FT",
                    ],
                ),
                **zone2_summary,
            },
        },
        "qc": {
            "source_signal_count": int(len(study_signals_functional)),
            "source_signal_universe_unchanged_into_each_output": {
                "Study_Signals_Zone1CriticalBuffer": int(len(zone1_buffers)) == int(len(study_signals_functional)),
                "Study_Signals_Zone2DesiredFullBuffer": int(len(zone2_buffers)) == int(len(study_signals_functional)),
            },
            "carry_forward_counts": {
                "default_assigned_speed_rows": int(defaulted_mask.sum()),
                "fallback_to_35_bin_rows": int((mapping_rule == "fallback_to_35_bin").sum()),
                "matched_speed_candidate_beyond_20ft_within_150ft_rows": int(beyond_20ft_mask.sum()),
            },
            "assigned_speed_distribution": {
                **_numeric_distribution(study_signals_functional["Assigned_Speed"]),
                "value_counts": _value_counts_numeric(study_signals_functional["Assigned_Speed"]),
            },
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_signal_donut() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    zone1_input = output_dir / OUTPUT_SIGNALS_ZONE1_BUFFER_NAME
    zone2_input = output_dir / OUTPUT_SIGNALS_ZONE2_FULL_BUFFER_NAME
    donut_output = output_dir / OUTPUT_SIGNALS_ZONE2_DONUT_NAME
    summary_output = config.parity_dir / DONUT_QC_SUMMARY_NAME

    zone1_buffers = _load_stage1b_output(zone1_input, label="Study_Signals_Zone1CriticalBuffer")
    zone2_buffers = _load_stage1b_output(zone2_input, label="Study_Signals_Zone2DesiredFullBuffer")

    donut, donut_summary = create_signal_functional_donut(zone2_buffers, zone1_buffers)
    donut.to_parquet(donut_output, index=False)

    mapping_rule = pd.Series(
        [_functional_distance_pair(v)[3] for v in donut["Assigned_Speed"]],
        index=donut.index,
    )
    defaulted_mask = donut["Assigned_Speed_Defaulted"].fillna(False).astype(bool)
    beyond_20ft_mask = (
        donut["SpeedContext_RowID"].notna()
        & pd.to_numeric(donut["SpeedContext_Distance_FT"], errors="coerce").gt(DIVIDED_SIGNAL_TOLERANCE_FEET)
        & pd.to_numeric(donut["SpeedContext_Distance_FT"], errors="coerce").le(SIGNAL_SPEED_SEARCH_FEET)
    )

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Per-signal functional donut geometry from Zone2DesiredFullBuffer minus Zone1CriticalBuffer",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_working_outputs": str(output_dir),
        },
        "unit_validation": {
            "epsg_3968_axis_units_confirmed": "meters",
            "zone1_buffer": _buffer_unit_validation(zone1_buffers),
            "zone2_full_buffer": _buffer_unit_validation(zone2_buffers),
            "correction_needed": False,
            "notes": "No correction was applied. Buffer distances remain feet in the data contract and were converted to meters for buffering because EPSG:3968 uses meter axis units.",
        },
        "inputs": {
            "Study_Signals_Zone1CriticalBuffer": {
                "path": str(zone1_input),
                **_dataset_summary(
                    zone1_buffers,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Buffer_Distance_FT",
                    ],
                ),
            },
            "Study_Signals_Zone2DesiredFullBuffer": {
                "path": str(zone2_input),
                **_dataset_summary(
                    zone2_buffers,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Buffer_Distance_FT",
                    ],
                ),
            },
        },
        "donut_rule": {
            "operation": "geometry difference of Study_Signals_Zone2DesiredFullBuffer minus Study_Signals_Zone1CriticalBuffer",
            "derived_strictly_from_prior_buffers": True,
            "one_feature_per_signal": True,
            "dissolve_status": "pre_dissolve_one_feature_per_signal",
            "overlap_status": "geometries may overlap; no dissolve applied",
        },
        "outputs": {
            "Study_Signals_Zone2FunctionalDonut": {
                "path": str(donut_output),
                **_dataset_summary(
                    donut,
                    key_fields=[
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                        "Assigned_Speed",
                        "Dist_Lim",
                        "Dist_Des",
                    ],
                ),
                **donut_summary,
            }
        },
        "qc": {
            "carry_forward_counts": {
                "default_assigned_speed_rows": int(defaulted_mask.sum()),
                "fallback_to_35_bin_rows": int((mapping_rule == "fallback_to_35_bin").sum()),
                "matched_speed_candidate_beyond_20ft_within_150ft_rows": int(beyond_20ft_mask.sum()),
            },
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_signal_multizone() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    zone1_input = output_dir / OUTPUT_SIGNALS_ZONE1_BUFFER_NAME
    zone2_input = output_dir / OUTPUT_SIGNALS_ZONE2_DONUT_NAME
    multizone_output = output_dir / OUTPUT_SIGNALS_MULTIZONE_NAME
    summary_output = config.parity_dir / MULTIZONE_QC_SUMMARY_NAME

    zone1_buffers = _load_stage1b_output(zone1_input, label="Study_Signals_Zone1CriticalBuffer")
    zone2_donut = _load_stage1b_output(zone2_input, label="Study_Signals_Zone2FunctionalDonut")

    multizone, multizone_summary = create_staged_multizone_geometry(zone1_buffers, zone2_donut)
    multizone.to_parquet(multizone_output, index=False)

    signal_level = zone1_buffers.sort_values("Signal_RowID", kind="stable").drop_duplicates("Signal_RowID", keep="first")
    mapping_rule = pd.Series(
        [_functional_distance_pair(v)[3] for v in signal_level["Assigned_Speed"]],
        index=signal_level.index,
    )
    defaulted_mask = signal_level["Assigned_Speed_Defaulted"].fillna(False).astype(bool)
    beyond_20ft_mask = (
        signal_level["SpeedContext_RowID"].notna()
        & pd.to_numeric(signal_level["SpeedContext_Distance_FT"], errors="coerce").gt(DIVIDED_SIGNAL_TOLERANCE_FEET)
        & pd.to_numeric(signal_level["SpeedContext_Distance_FT"], errors="coerce").le(SIGNAL_SPEED_SEARCH_FEET)
    )

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Staged multi-zone geometry layer from Zone1CriticalBuffer and Zone2FunctionalDonut",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_working_outputs": str(output_dir),
        },
        "inputs": {
            "Study_Signals_Zone1CriticalBuffer": {
                "path": str(zone1_input),
                **_dataset_summary(
                    zone1_buffers,
                    key_fields=[
                        "Signal_RowID",
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "Buffer_Distance_FT",
                    ],
                ),
            },
            "Study_Signals_Zone2FunctionalDonut": {
                "path": str(zone2_input),
                **_dataset_summary(
                    zone2_donut,
                    key_fields=[
                        "Signal_RowID",
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "Assigned_Speed",
                    ],
                ),
            },
        },
        "staged_output_contract": {
            "one_combined_layer": True,
            "zone_label_field": "Zone_Type",
            "zone_class_field": "Zone_Class",
            "source_output_field": "Zone_SourceOutput",
            "primary_distance_field_field": "Zone_PrimaryDistanceField",
            "secondary_distance_field_field": "Zone_SecondaryDistanceField",
            "geometry_method_field": "Zone_GeometryMethod",
            "description": "single staged multi-zone layer combining Zone 1 critical buffers and Zone 2 functional donuts for later road interaction",
        },
        "outputs": {
            "Study_Signals_StagedMultiZone": {
                "path": str(multizone_output),
                **_dataset_summary(
                    multizone,
                    key_fields=[
                        "Signal_RowID",
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "Zone_Type",
                        "Zone_Class",
                    ],
                ),
                **multizone_summary,
            }
        },
        "qc": {
            "carry_forward_source_signal_counts": {
                "default_assigned_speed_rows": int(defaulted_mask.sum()),
                "fallback_to_35_bin_rows": int((mapping_rule == "fallback_to_35_bin").sum()),
                "matched_speed_candidate_beyond_20ft_within_150ft_rows": int(beyond_20ft_mask.sum()),
            },
            "carry_forward_staged_row_counts": {
                "default_assigned_speed_rows": int(defaulted_mask.sum()) * 2,
                "fallback_to_35_bin_rows": int((mapping_rule == "fallback_to_35_bin").sum()) * 2,
                "matched_speed_candidate_beyond_20ft_within_150ft_rows": int(beyond_20ft_mask.sum()) * 2,
            },
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_road_zone_intersection() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    roads_input = output_dir / OUTPUT_ROADS_NAME
    zones_input = output_dir / OUTPUT_SIGNALS_MULTIZONE_NAME
    road_zone_output = output_dir / OUTPUT_ROAD_ZONE_INTERSECTION_NAME
    summary_output = config.parity_dir / ROAD_INTERSECTION_QC_SUMMARY_NAME

    study_roads = _load_stage1b_output(roads_input, label="Study_Roads_Divided")
    staged_multizone = _load_stage1b_output(zones_input, label="Study_Signals_StagedMultiZone")

    raw_intersection, intersection_summary = create_raw_road_zone_intersection(study_roads, staged_multizone)
    raw_intersection.to_parquet(road_zone_output, index=False)

    source_signal_level = staged_multizone.sort_values(["Signal_RowID", "Zone_Class"], kind="stable").drop_duplicates("Signal_RowID", keep="first")
    mapping_rule = pd.Series(
        [_functional_distance_pair(v)[3] for v in source_signal_level["Assigned_Speed"]],
        index=source_signal_level.index,
    )
    defaulted_mask = source_signal_level["Assigned_Speed_Defaulted"].fillna(False).astype(bool)
    beyond_20ft_mask = (
        source_signal_level["SpeedContext_RowID"].notna()
        & pd.to_numeric(source_signal_level["SpeedContext_Distance_FT"], errors="coerce").gt(DIVIDED_SIGNAL_TOLERANCE_FEET)
        & pd.to_numeric(source_signal_level["SpeedContext_Distance_FT"], errors="coerce").le(SIGNAL_SPEED_SEARCH_FEET)
    )

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Raw road-zone intersection between Study_Roads_Divided and Study_Signals_StagedMultiZone",
        "authoritative_input_boundary": {
            "normalized_stage1a": str(config.normalized_dir),
            "stage1b_working_outputs": str(output_dir),
        },
        "inputs": {
            "Study_Roads_Divided": {
                "path": str(roads_input),
                **_dataset_summary(
                    study_roads,
                    key_fields=["RTE_ID", "RTE_NM", "EVENT_SOUR"],
                ),
            },
            "Study_Signals_StagedMultiZone": {
                "path": str(zones_input),
                **_dataset_summary(
                    staged_multizone,
                    key_fields=["Signal_RowID", "Zone_Type", "Zone_Class", "Zone_SourceOutput"],
                ),
            },
        },
        "intersection_rule": {
            "operation": "geopandas overlay intersection",
            "result_description": "raw intersected road geometries inheriting zone membership from the staged multi-zone layer",
            "cleanup_status": "pre_cleanup_pre_claim_pre_segmentation",
            "multiple_rows_per_road_possible": True,
            "road_zone_overlap_possible": True,
        },
        "outputs": {
            "Functional_Road_Segments_Raw": {
                "path": str(road_zone_output),
                **_dataset_summary(
                    raw_intersection,
                    key_fields=["RTE_ID", "RTE_NM", "EVENT_SOUR", "Signal_RowID", "Zone_Type", "Zone_Class"],
                ),
                **intersection_summary,
            }
        },
        "qc": {
            "carry_forward_source_signal_counts": {
                "default_assigned_speed_rows": int(defaulted_mask.sum()),
                "fallback_to_35_bin_rows": int((mapping_rule == "fallback_to_35_bin").sum()),
                "matched_speed_candidate_beyond_20ft_within_150ft_rows": int(beyond_20ft_mask.sum()),
            },
            "legacy_arcpy_comparison": _legacy_comparison_status(config),
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_road_zone_cleanup() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    raw_input = output_dir / OUTPUT_ROAD_ZONE_INTERSECTION_NAME
    cleaned_output = output_dir / OUTPUT_ROAD_ZONE_PRECLAIM_NAME
    summary_output = config.parity_dir / ROAD_CLEANUP_QC_SUMMARY_NAME

    raw_intersection = _load_stage1b_output(raw_input, label="Functional_Road_Segments_Raw")
    cleaned_preclaim, cleanup_summary = create_minimal_preclaim_road_zone_geometry(raw_intersection)
    cleaned_preclaim.to_parquet(cleaned_output, index=False)

    source_signal_count = int(raw_intersection["Signal_RowID"].astype(str).nunique()) if "Signal_RowID" in raw_intersection.columns else 0
    represented_after_cleanup = cleanup_summary["signal_representation"]["unique_signals_represented_after_cleanup"]

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Minimal post-intersection cleanup for a usable pre-claim road-zone geometry set",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(raw_input),
            "upstream_state_required": "Functional_Road_Segments_Raw only; no earlier slice was revisited",
        },
        "method_boundary": {
            "allowed_cleanup_scope": [
                "invalid geometry repair if needed",
                "null geometry removal if needed",
                "empty geometry removal if needed",
                "strictly necessary non-line artifact removal after repair if needed",
                "strictly necessary zero-length geometry removal if needed",
            ],
            "not_applied": [
                "claim logic",
                "overlap resolution",
                "stable segment ID design",
                "segmentation cleanup",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
            ],
            "minimum_necessary_rationale": (
                "This slice only enforces geometry-validity and geometry-usability conditions required for a still-pre-claim, "
                "still-pre-segmentation road-zone layer. It does not change ownership, resolve overlaps, or stabilize segments."
            ),
        },
        "inputs": {
            "Functional_Road_Segments_Raw": {
                "path": str(raw_input),
                **_dataset_summary(
                    raw_intersection,
                    key_fields=["RTE_ID", "RTE_NM", "EVENT_SOUR", "Signal_RowID", "Zone_Type", "Zone_Class"],
                ),
                "road_identifier_summary": _road_identifier_summary(raw_intersection),
            }
        },
        "outputs": {
            "Functional_Road_Segments_PreClaim": {
                "path": str(cleaned_output),
                **_dataset_summary(
                    cleaned_preclaim,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "RoadZone_ProcessingStage",
                    ],
                ),
                **cleanup_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(raw_intersection)),
                "after": int(len(cleaned_preclaim)),
            },
            "all_2006_signals_still_represented": source_signal_count == 2006 and represented_after_cleanup == 2006,
            "source_signal_count_from_raw_input": source_signal_count,
            "cleaned_signal_count": represented_after_cleanup,
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No legacy cleaned road-claim artifact was compared in this bounded slice; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_road_claim_ownership() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    preclaim_input = output_dir / OUTPUT_ROAD_ZONE_PRECLAIM_NAME
    signals_input = output_dir / OUTPUT_SIGNALS_NAME
    owned_output = output_dir / OUTPUT_ROAD_ZONE_OWNED_NAME
    summary_output = config.parity_dir / ROAD_OWNERSHIP_QC_SUMMARY_NAME

    preclaim = _load_stage1b_output(preclaim_input, label="Functional_Road_Segments_PreClaim")
    signal_points = _load_stage1b_output(signals_input, label="Study_Signals")
    owned_claims, ownership_summary = assign_signal_ownership_to_claim_pieces(preclaim, signal_points)
    owned_claims.to_parquet(owned_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Bounded signal-ownership assignment for pre-claim road-zone pieces",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(preclaim_input),
            "required_supporting_signal_geometry": str(signals_input),
            "notes": "Ownership assignment starts from Functional_Road_Segments_PreClaim and uses Study_Signals point geometry only to compute candidate distance.",
        },
        "method_boundary": {
            "implemented_scope": [
                "identify exact claim-piece groups",
                "separate contested multi-signal pieces from uncontested pieces",
                "assign one owner per contested piece with an explicit deterministic rule",
                "carry ownership traceability fields into the owned output",
                "record contested-case QC samples",
            ],
            "not_applied": [
                "stable segment ID design",
                "segmentation cleanup beyond ownership assignment",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
            ],
        },
        "inputs": {
            "Functional_Road_Segments_PreClaim": {
                "path": str(preclaim_input),
                **_dataset_summary(
                    preclaim,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "RoadZone_ClaimStatus",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(preclaim),
            },
            "Study_Signals": {
                "path": str(signals_input),
                **_dataset_summary(
                    signal_points,
                    key_fields=["REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "INTNUM"],
                ),
            },
        },
        "outputs": {
            "Zone_Road_Claims_Owned": {
                "path": str(owned_output),
                **_dataset_summary(
                    owned_claims,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Is_Contested",
                        "Ownership_Assigned",
                        "Ownership_Rule",
                        "Ownership_CandidateCount",
                    ],
                ),
                **ownership_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(preclaim)),
                "after": int(len(owned_claims)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy Zone_Road_Claims or Zone_Road_Claims_Clean artifact was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_raw() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    owned_input = output_dir / OUTPUT_ROAD_ZONE_OWNED_NAME
    segmented_output = output_dir / OUTPUT_SEGMENT_RAW_NAME
    summary_output = config.parity_dir / SEGMENT_RAW_QC_SUMMARY_NAME

    owned_claims = _load_stage1b_output(owned_input, label="Zone_Road_Claims_Owned")
    segmented_raw, segment_summary = create_first_segmented_road_pieces(owned_claims)
    segmented_raw.to_parquet(segmented_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "First segmented road-piece output from ownership-resolved claim geometry",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(owned_input),
            "notes": "Segmentation starts from ownership-resolved claim pieces only and does not revisit earlier road-zone outputs.",
        },
        "method_boundary": {
            "implemented_scope": [
                "convert ownership-resolved road claims into explicit singlepart road pieces",
                "preserve road, signal, zone, and ownership traceability fields",
                "record multipart split accounting and post-segmentation geometry health",
            ],
            "not_applied": [
                "stable segment ID design",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
            ],
        },
        "inputs": {
            "Zone_Road_Claims_Owned": {
                "path": str(owned_input),
                **_dataset_summary(
                    owned_claims,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Is_Contested",
                        "Ownership_Assigned",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(owned_claims),
            }
        },
        "outputs": {
            "Functional_Segments_Raw": {
                "path": str(segmented_output),
                **_dataset_summary(
                    segmented_raw,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Ownership_Assigned",
                        "Segment_SourceOwnedRowID",
                    ],
                ),
                **segment_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(owned_claims)),
                "after": int(len(segmented_raw)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy Functional_Segments_Raw artifact was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_support() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    segment_input = output_dir / OUTPUT_SEGMENT_RAW_NAME
    segment_output = output_dir / OUTPUT_SEGMENT_SUPPORT_NAME
    summary_output = config.parity_dir / SEGMENT_SUPPORT_QC_SUMMARY_NAME

    segmented_raw = _load_stage1b_output(segment_input, label="Functional_Segments_Raw")
    segmented_support, support_summary = enrich_segment_support_fields(segmented_raw)
    segmented_support.to_parquet(segment_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Minimal segment-level support-field enrichment from Functional_Segments_Raw",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(segment_input),
            "notes": "This slice starts from Functional_Segments_Raw only and adds bounded support attributes without changing the geometry row set.",
        },
        "method_boundary": {
            "implemented_scope": [
                "derive minimum segment-length support field",
                "derive minimum midpoint support fields",
                "preserve the existing segmented geometry row set unchanged",
            ],
            "not_applied": [
                "stable segment ID design",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
                "broader cleanup or reassignment",
            ],
        },
        "inputs": {
            "Functional_Segments_Raw": {
                "path": str(segment_input),
                **_dataset_summary(
                    segmented_raw,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_SourceOwnedRowID",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(segmented_raw),
            }
        },
        "outputs": {
            "Functional_Segments_Raw_Support": {
                "path": str(segment_output),
                **_dataset_summary(
                    segmented_support,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Seg_Len_Ft",
                        "Mid_X",
                        "Mid_Y",
                    ],
                ),
                **support_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(segmented_raw)),
                "after": int(len(segmented_support)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy segment-support artifact was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_identity_qc_support() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    segment_input = output_dir / OUTPUT_SEGMENT_SUPPORT_NAME
    segment_output = output_dir / OUTPUT_SEGMENT_IDENTITY_QC_SUPPORT_NAME
    summary_output = config.parity_dir / SEGMENT_IDENTITY_QC_SUPPORT_QC_SUMMARY_NAME

    segmented_support = _load_stage1b_output(segment_input, label="Functional_Segments_Raw_Support")
    segmented_identity_qc, identity_qc_summary = enrich_segment_identity_qc_support_fields(segmented_support)
    segmented_identity_qc.to_parquet(segment_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Minimal segment identity/QC support enrichment from Functional_Segments_Raw_Support",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(segment_input),
            "notes": "This slice starts from Functional_Segments_Raw_Support only and adds bounded segment-level identity/QC support attributes without changing the geometry row set.",
        },
        "method_boundary": {
            "implemented_scope": [
                "derive one explicit temporary non-stable row helper for immediate bounded audit/join use",
                f"flag short segment pieces using the legacy {MIN_SEGMENT_FT:g} ft threshold without deleting rows",
                "preserve the existing segmented geometry row set and carried-forward traceability unchanged",
            ],
            "not_applied": [
                "stable segment ID design",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
                "segment deletion or broader cleanup",
            ],
        },
        "inputs": {
            "Functional_Segments_Raw_Support": {
                "path": str(segment_input),
                **_dataset_summary(
                    segmented_support,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Ownership_Assigned",
                        "Segment_SourceOwnedRowID",
                        "Segment_PartIndex",
                        "Seg_Len_Ft",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(segmented_support),
            }
        },
        "outputs": {
            "Functional_Segments_Raw_Support_IdentityQC": {
                "path": str(segment_output),
                **_dataset_summary(
                    segmented_identity_qc,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Ownership_Assigned",
                        "Segment_SourceOwnedRowID",
                        "Segment_PartIndex",
                        "Segment_RowID_Temp",
                        "QC_ShortSegment",
                    ],
                ),
                **identity_qc_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(segmented_support)),
                "after": int(len(segmented_identity_qc)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy post-support segment identity/QC ArcPy boundary was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_canonical_road_identity() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    segment_input = output_dir / OUTPUT_SEGMENT_IDENTITY_QC_SUPPORT_NAME
    segment_output = output_dir / OUTPUT_SEGMENT_CANONICAL_ROAD_IDENTITY_NAME
    summary_output = config.parity_dir / SEGMENT_CANONICAL_ROAD_IDENTITY_QC_SUMMARY_NAME

    segmented_identity_qc = _load_stage1b_output(segment_input, label="Functional_Segments_Raw_Support_IdentityQC")
    segmented_canonical_road, canonical_summary = enrich_segment_canonical_road_identity_fields(segmented_identity_qc)
    segmented_canonical_road.to_parquet(segment_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Minimal segment-side canonical road identity enrichment from Functional_Segments_Raw_Support_IdentityQC",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(segment_input),
            "notes": "This slice starts from Functional_Segments_Raw_Support_IdentityQC only and adds bounded canonical road identity attributes from existing road lineage on current rows without changing the geometry row set.",
        },
        "method_boundary": {
            "implemented_scope": [
                "derive only the minimum canonical road identity carry-forward fields available directly from existing travelway lineage",
                "preserve temporary/non-stable Segment_RowID_Temp as temporary and do not introduce any stable segment ID",
                "preserve the existing segmented geometry row set and carried-forward traceability unchanged",
            ],
            "not_applied": [
                "stable segment ID design",
                "external joins or AADT fallback logic",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
            ],
        },
        "inputs": {
            "Functional_Segments_Raw_Support_IdentityQC": {
                "path": str(segment_input),
                **_dataset_summary(
                    segmented_identity_qc,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "RTE_COMMON",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "QC_ShortSegment",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(segmented_identity_qc),
            }
        },
        "outputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad": {
                "path": str(segment_output),
                **_dataset_summary(
                    segmented_canonical_road,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "RTE_COMMON",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                    ],
                ),
                **canonical_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(segmented_identity_qc)),
                "after": int(len(segmented_canonical_road)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy post-identity-QC canonical-road-identity ArcPy boundary was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_link_identity_support() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    segment_input = output_dir / OUTPUT_SEGMENT_CANONICAL_ROAD_IDENTITY_NAME
    segment_output = output_dir / OUTPUT_SEGMENT_LINK_IDENTITY_SUPPORT_NAME
    summary_output = config.parity_dir / SEGMENT_LINK_IDENTITY_SUPPORT_QC_SUMMARY_NAME

    segmented_canonical = _load_stage1b_output(segment_input, label="Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad")
    segmented_link_audit, link_audit_summary = audit_segment_link_identity_support(segmented_canonical)
    segmented_link_audit.to_parquet(segment_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "Minimum justified segment-side link-identity support outcome from Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(segment_input),
            "notes": "This slice starts from Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad only and determines whether direct link identity is available from the current row lineage without changing the geometry row set.",
        },
        "method_boundary": {
            "implemented_scope": [
                "audit direct link-identity availability from current carried-forward row lineage only",
                "record an explicit inspectable audit result when direct LinkID_Norm is not available",
                "preserve the existing segmented geometry row set and carried-forward traceability unchanged",
            ],
            "not_applied": [
                "stable segment ID design",
                "external joins or AADT fallback logic",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
            ],
        },
        "inputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad": {
                "path": str(segment_input),
                **_dataset_summary(
                    segmented_canonical,
                    key_fields=[
                        "RTE_ID",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(segmented_canonical),
            }
        },
        "outputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit": {
                "path": str(segment_output),
                **_dataset_summary(
                    segmented_link_audit,
                    key_fields=[
                        "RTE_ID",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                        "LinkID_AuditStatus",
                    ],
                ),
                **link_audit_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(segmented_canonical)),
                "after": int(len(segmented_link_audit)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy post-canonical-road link-identity-support ArcPy boundary was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_directionality_support() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    segment_input = output_dir / OUTPUT_SEGMENT_LINK_IDENTITY_SUPPORT_NAME
    signals_input = output_dir / OUTPUT_SIGNALS_NAME
    segment_output = output_dir / OUTPUT_SEGMENT_DIRECTIONALITY_SUPPORT_NAME
    summary_output = config.parity_dir / SEGMENT_DIRECTIONALITY_SUPPORT_QC_SUMMARY_NAME

    segmented_link_audit = _load_stage1b_output(segment_input, label="Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit")
    study_signals = _load_stage1b_output(signals_input, label="Study_Signals")
    segmented_directionality, directionality_summary = enrich_segment_directionality_support_fields(
        segmented_link_audit,
        study_signals,
    )
    segmented_directionality.to_parquet(segment_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "First bounded downstream-directionality support from owned segment pieces and owned signal relationship",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(segment_input),
            "notes": "This slice starts from Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit and adds bounded node-availability audit plus first endpoint-based directionality support without changing the geometry row set.",
        },
        "method_boundary": {
            "implemented_scope": [
                "audit whether node identity is directly available from current carried-forward row lineage",
                "look up owned signal point geometry from the existing Stage 1B Study_Signals output using Signal_RowID because current segment rows do not carry reliable signal geometry directly",
                "derive first endpoint-based segment-to-owned-signal geometry support fields only",
            ],
            "not_applied": [
                "stable segment ID design",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
                "final downstream/upstream flow-role classification",
            ],
        },
        "inputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit": {
                "path": str(segment_input),
                **_dataset_summary(
                    segmented_link_audit,
                    key_fields=[
                        "RTE_ID",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                        "LinkID_AuditStatus",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(segmented_link_audit),
            },
            "Study_Signals": {
                "path": str(signals_input),
                **_dataset_summary(
                    study_signals,
                    key_fields=[
                        "Signal_RowID",
                        "REG_SIGNAL_ID",
                        "SIGNAL_NO",
                        "INTNO",
                        "INTNUM",
                    ],
                ),
            },
        },
        "outputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport": {
                "path": str(segment_output),
                **_dataset_summary(
                    segmented_directionality,
                    key_fields=[
                        "RTE_ID",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                        "LinkID_AuditStatus",
                        "NodeID_AuditStatus",
                        "Signal_NearEnd_Label",
                        "Directionality_AuditStatus",
                    ],
                ),
                **directionality_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(segmented_link_audit)),
                "after": int(len(segmented_directionality)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local legacy endpoint-based directionality-support ArcPy boundary was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_stage1b_segment_oracle_direction_prep() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / STUDY_SLICE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    config.parity_dir.mkdir(parents=True, exist_ok=True)

    segment_input = output_dir / OUTPUT_SEGMENT_DIRECTIONALITY_SUPPORT_NAME
    segment_output = output_dir / OUTPUT_SEGMENT_ORACLE_DIRECTION_PREP_NAME
    summary_output = config.parity_dir / SEGMENT_ORACLE_DIRECTION_PREP_QC_SUMMARY_NAME

    segmented_directionality = _load_stage1b_output(
        segment_input,
        label="Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport",
    )
    segmented_oracle_prep, oracle_prep_summary = enrich_segment_oracle_direction_prep_fields(
        segmented_directionality,
        config.repo_root,
    )
    segmented_oracle_prep.to_parquet(segment_output, index=False)

    payload = {
        "interpreter": sys.executable,
        "repo_root": str(config.repo_root),
        "config_path": str(config.config_path),
        "stage": "Stage 1B",
        "task": "First bounded Oracle-direction integration prep from directionality-support segments",
        "authoritative_input_boundary": {
            "stage1b_working_output": str(segment_input),
            "notes": "This slice starts from Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport and adds bounded Oracle-direction dependency/readiness fields plus minimal repo-local Oracle broad-lookup route coverage support without changing the geometry row set.",
        },
        "method_boundary": {
            "implemented_scope": [
                "explicitly confirm that trustworthy downstream directionality remains Oracle-dependent at this boundary",
                "build the minimum row-level Oracle join-readiness package from current segment lineage",
                "use the repo-local Oracle broad lookup only for bounded route-candidate presence and ambiguity support",
            ],
            "not_applied": [
                "stable segment ID design",
                "Oracle final direction labeling",
                "crash assignment",
                "access assignment",
                "downstream aggregation",
            ],
        },
        "inputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport": {
                "path": str(segment_input),
                **_dataset_summary(
                    segmented_directionality,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                        "LinkID_AuditStatus",
                        "NodeID_AuditStatus",
                        "Signal_NearEnd_Label",
                        "Directionality_AuditStatus",
                    ],
                ),
                "road_identifier_summary": _road_identifier_summary(segmented_directionality),
            }
        },
        "outputs": {
            "Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep": {
                "path": str(segment_output),
                **_dataset_summary(
                    segmented_oracle_prep,
                    key_fields=[
                        "RTE_ID",
                        "RTE_NM",
                        "EVENT_SOUR",
                        "Signal_RowID",
                        "Zone_Type",
                        "Zone_Class",
                        "Segment_RowID_Temp",
                        "RouteID_Norm",
                        "RouteNm_Norm",
                        "DirCode_Norm",
                        "OracleRouteNm_Candidate",
                        "OracleBroadRoutePresent",
                        "OracleDirection_Ready",
                        "OracleDirection_MissingReason",
                    ],
                ),
                **oracle_prep_summary,
            }
        },
        "qc": {
            "before_after_feature_counts": {
                "before": int(len(segmented_directionality)),
                "after": int(len(segmented_oracle_prep)),
            },
            "legacy_arcpy_comparison": {
                **_legacy_comparison_status(config),
                "notes": "No repo-local Oracle-direction-prep ArcPy boundary was available for direct parity comparison; no parity claim is made.",
            },
        },
    }
    summary_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0
